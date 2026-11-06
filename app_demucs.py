import contextlib
import gc
import inspect
import os
import queue
import sys
import threading
from pathlib import Path
from urllib.parse import urlparse

# Tutti i dati scaricati durante l'esecuzione devono restare dentro ChansonVivante.
# In particolare, PyTorch/Demucs usa TORCH_HOME per i checkpoint dei modelli.
APP_ROOT = (
    Path(sys.executable).parent.resolve()
    if getattr(sys, "frozen", False)
    else Path(__file__).parent.resolve()
)
APP_MODELS_DIR = APP_ROOT / "models"
APP_CACHE_DIR = APP_ROOT / ".cache"
APP_MODELS_DIR.mkdir(parents=True, exist_ok=True)
APP_CACHE_DIR.mkdir(parents=True, exist_ok=True)

os.environ["TORCH_HOME"] = str(APP_MODELS_DIR)
os.environ["HF_HOME"] = str(APP_MODELS_DIR / "huggingface")
os.environ["HUGGINGFACE_HUB_CACHE"] = str(APP_MODELS_DIR / "huggingface" / "hub")
os.environ["TRANSFORMERS_CACHE"] = str(APP_MODELS_DIR / "huggingface" / "transformers")
os.environ["XDG_CACHE_HOME"] = str(APP_CACHE_DIR)

import yaml
import tkinter as tk
from tkinter import filedialog, messagebox

# Splash leggero: viene mostrato prima di caricare le librerie AI pesanti.
_splash = tk.Tk()
_splash.overrideredirect(True)
_splash.configure(bg="#111111")
_splash.geometry("420x180")
_splash.eval("tk::PlaceWindow . center")
tk.Label(
    _splash,
    text="ChansonVivante",
    bg="#111111",
    fg="white",
    font=("Segoe UI", 22, "bold"),
).pack(pady=(42, 8))
_splash_status = tk.Label(
    _splash,
    text="Avvio applicazione...",
    bg="#111111",
    fg="#aaaaaa",
    font=("Segoe UI", 10),
)
_splash_status.pack()
_splash.update()

# Disattiviamo esplicitamente torchcodec prima di caricare qualsiasi altra cosa.
os.environ["TORCHAUDIO_USE_TORCHCODEC"] = "0"
os.environ["PYTHONIOENCODING"] = "utf-8"

import customtkinter as ctk

# Le librerie pesanti vengono caricate dopo la comparsa della finestra principale.
# In questo modo l'avvio percepito non resta bloccato sull'import di PyTorch/Demucs.
torch = None
demucs = None
sf = None

_splash_status.configure(text="Avvio interfaccia...")
_splash.update()
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

GB = 1024 ** 3
VRAM_RESERVE_GB = 0.75
# Retry progressivamente più leggeri. None lascia a Demucs il segmento predefinito.
SEGMENT_RETRY_ORDER = [None, 5.0, 3.0, 2.0, 1.5]


def resource_path(relative_path):
    """Restituisce un percorso valido sia da sorgente sia da EXE."""
    return str((APP_ROOT / relative_path).resolve())


def is_cuda_oom(error):
    """Riconosce solo errori di memoria CUDA, senza nascondere altri bug."""
    oom_type = getattr(torch.cuda, "OutOfMemoryError", ())
    if oom_type and isinstance(error, oom_type):
        return True
    message = str(error).lower()
    return "out of memory" in message and ("cuda" in message or "cublas" in message)


def segment_for_budget(budget_gb):
    """Stima iniziale prudente; il budget è un obiettivo, non un hard cap."""
    if budget_gb >= 7.5:
        return None
    if budget_gb >= 5.0:
        return 5.0
    if budget_gb >= 3.2:
        return 3.0
    if budget_gb >= 2.0:
        return 2.0
    return 1.5


def available_cuda_memory():
    """Ritorna (memoria libera, totale) in GiB, oppure None se CUDA non è pronta."""
    try:
        if not torch.cuda.is_available():
            return None
        free_bytes, total_bytes = torch.cuda.mem_get_info()
        return free_bytes / GB, total_bytes / GB
    except Exception:
        return None



class QueueLogStream:
    """Inoltra stdout/stderr al thread GUI senza bloccare l'elaborazione."""
    def __init__(self, log_queue, level):
        self.log_queue = log_queue
        self.level = level
        self.buffer = ""

    def write(self, text):
        if not text:
            return 0
        self.buffer += str(text)
        # tqdm usa \r per aggiornare la stessa riga; trattiamo anche \n.
        while "\n" in self.buffer or "\r" in self.buffer:
            positions = [p for p in (self.buffer.find("\n"), self.buffer.find("\r")) if p >= 0]
            pos = min(positions)
            line = self.buffer[:pos].strip()
            self.buffer = self.buffer[pos + 1:]
            if line:
                self.log_queue.put(("log", self.level, line))
        return len(text)

    def flush(self):
        line = self.buffer.strip()
        if line:
            self.log_queue.put(("log", self.level, line))
        self.buffer = ""

    def isatty(self):
        return False


class DemucsApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("ChansonsVivante Audio Separator")
        self.geometry("760x790")
        self.resizable(False, False)

        icon_path = resource_path("logo.ico")
        if os.path.exists(icon_path):
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

        self.input_file = ctk.StringVar()
        # Per impostazione predefinita, salva direttamente nella cartella del progetto.
        self.output_dir = ctk.StringVar(value=str(APP_ROOT))
        self.format_var = ctk.StringVar(value="flac")
        self.bit_var = ctk.StringVar(value="16-bit")
        self.model_var = ctk.StringVar(value="htdemucs")
        self.stems_var = ctk.StringVar(value="Solo Voce e Base (2 tracce)")
        self.shifts_var = ctk.StringVar(value="1 (Standard)")
        self.device_mode_var = ctk.StringVar(value="Automatica")
        self.budget_gb = 3.0

        self.ui_queue = queue.Queue()
        self.log_window = None
        self.log_textbox = None
        self.log_history = []
        self.interactive_widgets = []
        self.has_cuda = False
        self.ai_ready = False
        self.create_widgets()
        self.status_label.configure(
            text="Interfaccia pronta · caricamento motore AI...",
            text_color="orange",
        )
        self.btn_start.configure(state="disabled")
        self.after(100, self.process_ui_queue)
        self.after(150, self.start_ai_dependency_loading)

    def start_ai_dependency_loading(self):
        """Carica PyTorch/Demucs in background dopo aver mostrato la GUI."""
        self.status_label.configure(
            text="Caricamento motore AI in background...",
            text_color="orange",
        )
        self.btn_start.configure(state="disabled")
        threading.Thread(
            target=self.load_ai_dependencies_worker,
            daemon=True,
        ).start()

    def load_ai_dependencies_worker(self):
        """Importa le librerie pesanti senza bloccare il thread della GUI."""
        global torch, demucs, sf
        try:
            import soundfile as soundfile_module
            import torch as torch_module
            import demucs as demucs_module
            import demucs.api  # noqa: F401
            import imageio_ffmpeg

            ffmpeg_exe_path = Path(imageio_ffmpeg.get_ffmpeg_exe())
            ffmpeg_folder = str(ffmpeg_exe_path.parent.resolve())
            os.environ["PATH"] = ffmpeg_folder + os.pathsep + os.environ.get("PATH", "")

            sf = soundfile_module
            torch = torch_module
            demucs = demucs_module
            self.ui_queue.put(("ai_ready",))
        except ImportError as error:
            self.ui_queue.put(("ai_error", f"Impossibile caricare il motore AI: {error}"))
        except Exception as error:
            self.ui_queue.put(("ai_error", f"Errore durante il caricamento del motore AI: {error}"))

    def create_widgets(self):
        ctk.CTkLabel(
            self,
            text="ChansonsVivante - AI Audio Separation",
            font=ctk.CTkFont(size=20, weight="bold"),
        ).pack(pady=(16, 10))

        frame_files = ctk.CTkFrame(self)
        frame_files.pack(pady=7, padx=20, fill="x")
        ctk.CTkLabel(frame_files, text="Traccia audio:").grid(
            row=0, column=0, padx=10, pady=9, sticky="w"
        )
        self.input_entry = ctk.CTkEntry(
            frame_files, textvariable=self.input_file, width=390, state="readonly"
        )
        self.input_entry.grid(row=0, column=1, padx=8, pady=9)
        btn_browse_in = ctk.CTkButton(
            frame_files, text="Scegli file", command=self.browse_input, width=110
        )
        btn_browse_in.grid(row=0, column=2, padx=8, pady=9)

        ctk.CTkLabel(frame_files, text="Salva in:").grid(
            row=1, column=0, padx=10, pady=9, sticky="w"
        )
        self.output_entry = ctk.CTkEntry(
            frame_files, textvariable=self.output_dir, width=390, state="readonly"
        )
        self.output_entry.grid(row=1, column=1, padx=8, pady=9)
        btn_browse_out = ctk.CTkButton(
            frame_files, text="Scegli cartella", command=self.browse_output, width=110
        )
        btn_browse_out.grid(row=1, column=2, padx=8, pady=9)

        frame_settings = ctk.CTkFrame(self)
        frame_settings.pack(pady=7, padx=20, fill="x")
        ctk.CTkLabel(frame_settings, text="Formato:").grid(
            row=0, column=0, padx=10, pady=8, sticky="w"
        )
        opt_format = ctk.CTkOptionMenu(
            frame_settings, variable=self.format_var, values=["flac", "wav", "mp3"]
        )
        opt_format.grid(row=0, column=1, padx=8, pady=8, sticky="w")
        ctk.CTkLabel(frame_settings, text="Qualità:").grid(
            row=0, column=2, padx=10, pady=8, sticky="w"
        )
        opt_bit = ctk.CTkOptionMenu(
            frame_settings, variable=self.bit_var, values=["16-bit", "24-bit"]
        )
        opt_bit.grid(row=0, column=3, padx=8, pady=8, sticky="w")

        ctk.CTkLabel(frame_settings, text="Modello AI:").grid(
            row=1, column=0, padx=10, pady=8, sticky="w"
        )
        opt_model = ctk.CTkOptionMenu(
            frame_settings, variable=self.model_var, values=["htdemucs", "htdemucs_ft"]
        )
        opt_model.grid(row=1, column=1, padx=8, pady=8, sticky="w")
        ctk.CTkLabel(
            frame_settings,
            text=(
                "htdemucs: modello standard, più veloce e consigliato per la maggior parte dei brani. "
                "htdemucs_ft: versione fine-tuned, può offrire una separazione leggermente migliore, "
                "ma richiede circa 4 volte più tempo."
            ),
            text_color="gray",
            wraplength=680,
            justify="left",
        ).grid(row=2, column=0, columnspan=4, padx=12, pady=(0, 6), sticky="w")
        ctk.CTkLabel(frame_settings, text="Shifts:").grid(
            row=1, column=2, padx=10, pady=8, sticky="w"
        )
        opt_shifts = ctk.CTkOptionMenu(
            frame_settings,
            variable=self.shifts_var,
            values=["0 (Veloce)", "1 (Standard)", "2 (Preciso)", "3 (Lento)"],
        )
        opt_shifts.grid(row=1, column=3, padx=8, pady=8, sticky="w")

        ctk.CTkLabel(frame_settings, text="Separazione:").grid(
            row=3, column=0, padx=10, pady=8, sticky="w"
        )
        opt_stems = ctk.CTkOptionMenu(
            frame_settings,
            variable=self.stems_var,
            values=[
                "Solo Voce e Base (2 tracce)",
                "Tutti gli strumenti (4 tracce)",
            ],
            width=235,
        )
        opt_stems.grid(row=3, column=1, columnspan=3, padx=8, pady=8, sticky="w")

        self.interactive_widgets.extend(
            [btn_browse_in, btn_browse_out, opt_format, opt_bit, opt_model, opt_shifts, opt_stems]
        )

        # Gestione GPU e budget VRAM
        frame_gpu = ctk.CTkFrame(self)
        frame_gpu.pack(pady=7, padx=20, fill="x")
        ctk.CTkLabel(
            frame_gpu,
            text="Accelerazione e memoria GPU",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).grid(row=0, column=0, columnspan=3, padx=12, pady=(10, 5), sticky="w")

        ctk.CTkLabel(frame_gpu, text="Modalità:").grid(
            row=1, column=0, padx=12, pady=7, sticky="w"
        )
        self.device_menu = ctk.CTkOptionMenu(
            frame_gpu,
            variable=self.device_mode_var,
            values=["Automatica", "Manuale", "Solo CPU"],
            command=self.on_device_mode_change,
            width=180,
        )
        self.device_menu.grid(row=1, column=1, padx=8, pady=7, sticky="w")

        self.budget_label = ctk.CTkLabel(frame_gpu, text="Budget VRAM: 3.0 GB")
        self.budget_label.grid(row=2, column=0, padx=12, pady=(8, 0), sticky="w")
        self.budget_slider = ctk.CTkSlider(
            frame_gpu,
            from_=1.0,
            to=12.0,
            number_of_steps=22,
            command=self.on_budget_change,
            width=390,
        )
        self.budget_slider.set(self.budget_gb)
        self.budget_slider.grid(row=2, column=1, padx=8, pady=(8, 0), sticky="w")
        self.budget_range_label = ctk.CTkLabel(frame_gpu, text="1–12 GB")
        self.budget_range_label.grid(row=2, column=2, padx=8, pady=(8, 0), sticky="w")

        self.gpu_info_label = ctk.CTkLabel(
            frame_gpu, text="Rilevamento GPU...", text_color="gray"
        )
        self.gpu_info_label.grid(
            row=3, column=0, columnspan=3, padx=12, pady=(5, 10), sticky="w"
        )
        self.interactive_widgets.extend([self.device_menu, self.budget_slider])

        self.status_label = ctk.CTkLabel(self, text="Pronto.", text_color="gray")
        self.status_label.pack(pady=(12, 5))
        self.progress_bar = ctk.CTkProgressBar(self, width=650, mode="indeterminate")
        self.progress_bar.pack(pady=8)
        self.progress_bar.set(0)

        self.btn_start = ctk.CTkButton(
            self,
            text="Avvia separazione",
            font=ctk.CTkFont(weight="bold"),
            height=42,
            command=self.start_thread,
        )
        self.btn_start.pack(pady=(14, 5))

        self.btn_logs = ctk.CTkButton(
            self, text="Mostra log", command=self.open_log_window, width=150
        )
        self.btn_logs.pack(pady=(0, 10))

        ctk.CTkLabel(
            self,
            text=(
                "Il budget VRAM è un obiettivo indicativo, non un limite hardware assoluto. "
                "La memoria usata da Windows, PyTorch e altri programmi può variare."
            ),
            text_color="gray",
            wraplength=690,
            justify="center",
        ).pack(padx=25, pady=(0, 10))

    def model_cache_entries(self, model_name):
        """Restituisce i file effettivi richiesti dalla cache Hugging Face o legacy."""
        from huggingface_hub import try_to_load_from_cache
        from demucs.hf import DEFAULT_NAMESPACE, hf_repo_name

        namespace = DEFAULT_NAMESPACE
        model_id = model_name
        if "/" in model_name:
            namespace, model_id = model_name.split("/", 1)
        repo_id = f"{namespace}/{hf_repo_name(model_id)}"
        yaml_name = f"{model_id}.yaml"
        cached_yaml = try_to_load_from_cache(repo_id, yaml_name)

        # Demucs 4.1 prova prima Hugging Face: i pesi sono file safetensors.
        if isinstance(cached_yaml, str) and Path(cached_yaml).is_file():
            with open(cached_yaml, "r", encoding="utf-8") as file:
                model_bag = yaml.safe_load(file) or {}
            entries = [(f"{repo_id}/{yaml_name}", Path(cached_yaml))]
            for signature in model_bag.get("models", []):
                filename = f"{signature}.safetensors"
                cached_file = try_to_load_from_cache(repo_id, filename)
                path = (
                    Path(cached_file)
                    if isinstance(cached_file, str) and Path(cached_file).is_file()
                    else None
                )
                entries.append((f"{repo_id}/{filename}", path))
            return entries

        # Compatibilità con il repository remoto legacy (.th).
        remote_root = Path(demucs.pretrained.REMOTE_ROOT)
        bag_file = remote_root / f"{model_name}.yaml"
        files_list = remote_root / "files.txt"
        if not bag_file.is_file() or not files_list.is_file():
            raise RuntimeError(
                f"Impossibile leggere i metadati Demucs per il modello '{model_name}'."
            )

        with bag_file.open("r", encoding="utf-8") as file:
            model_bag = yaml.safe_load(file) or {}
        remote_models = demucs.pretrained._parse_remote_files(files_list)
        checkpoint_dir = Path(torch.hub.get_dir()) / "checkpoints"
        entries = []
        for signature in model_bag.get("models", []):
            url = remote_models.get(signature)
            if not url:
                raise RuntimeError(
                    f"Checkpoint '{signature}' non trovato nei metadati Demucs."
                )
            filename = Path(urlparse(url).path).name
            entries.append((filename, checkpoint_dir / filename))
        return entries

    def is_model_installed(self, model_name):
        """Un modello è installato solo se sono presenti tutti i suoi file."""
        entries = self.model_cache_entries(model_name)
        return bool(entries) and all(
            path is not None and path.is_file() and path.stat().st_size > 0
            for _, path in entries
        )

    def check_model_on_startup(self):
        model_name = self.model_var.get()
        try:
            installed = self.is_model_installed(model_name)
        except Exception as error:
            self.append_log("WARNING", f"Controllo modello non riuscito: {error}")
            return

        if not installed:
            install = messagebox.askyesno(
                "Modello non installato",
                f"Il modello '{model_name}' non è installato. Vuoi installarlo ora?\n\n"
                "Il download verrà mostrato nella finestra dei log."
            )
            if install:
                self.start_model_installation(model_name)

    def start_model_installation(self, model_name):
        if getattr(self, "model_installing", False):
            return
        self.model_installing = True
        self.set_running_state(True)
        self.ui_queue.put(("status", f"Download del modello {model_name}...", "orange"))
        self.open_log_window()
        threading.Thread(
            target=self.install_model_worker, args=(model_name,), daemon=True
        ).start()

    def install_model_worker(self, model_name):
        """Scarica il modello e registra anche gli errori delle operazioni preliminari."""
        stdout_stream = QueueLogStream(self.ui_queue, "INFO")
        stderr_stream = QueueLogStream(self.ui_queue, "WARNING")
        try:
            # Tutte le operazioni, compresa la preparazione dei percorsi, devono
            # essere dentro il try: con pythonw.exe gli errori non appaiono in console.
            self.ui_queue.put(("log", "INFO", f"Avvio installazione modello: {model_name}"))
            self.ui_queue.put(("log", "INFO", f"Cartella modelli locale: {APP_MODELS_DIR}"))

            hf_cache_dir = Path(os.environ["HF_HOME"]) / "hub"
            checkpoint_dir = Path(torch.hub.get_dir()) / "checkpoints"
            self.ui_queue.put(("log", "INFO", f"Cache Hugging Face: {hf_cache_dir}"))
            self.ui_queue.put(("log", "INFO", f"Cache checkpoint legacy: {checkpoint_dir}"))

            with contextlib.redirect_stdout(stdout_stream), contextlib.redirect_stderr(stderr_stream):
                self.ui_queue.put(("log", "INFO", "Download e caricamento del modello in corso..."))
                separator = demucs.api.Separator(
                    model=model_name, device="cpu", shifts=0, overlap=0.25
                )
                del separator
                gc.collect()

            self.ui_queue.put(("log", "INFO", "Download terminato. Verifica dei file..."))
            cache_entries = self.model_cache_entries(model_name)
            for cache_name, cache_path in cache_entries:
                exists = (
                    cache_path is not None
                    and cache_path.is_file()
                    and cache_path.stat().st_size > 0
                )
                self.ui_queue.put((
                    "log",
                    "INFO" if exists else "ERROR",
                    f"{'OK' if exists else 'MANCANTE'}: {cache_name}"
                    + (f" -> {cache_path}" if cache_path is not None else ""),
                ))

            if not cache_entries or not self.is_model_installed(model_name):
                raise RuntimeError(
                    f"Il download di '{model_name}' è terminato, ma uno o più checkpoint "
                    "non risultano presenti nella cartella locale."
                )

            self.ui_queue.put((
                "done",
                f"Modello '{model_name}' installato e pronto.",
                None,
            ))
        except Exception as error:
            self.ui_queue.put((
                "error",
                f"Installazione di '{model_name}' non riuscita: "
                f"{type(error).__name__}: {error}",
            ))
        finally:
            try:
                stdout_stream.flush()
                stderr_stream.flush()
            except Exception as log_error:
                self.ui_queue.put((
                    "log",
                    "ERROR",
                    f"Errore durante la chiusura del log: {log_error}",
                ))
            self.ui_queue.put(("model_install_finished",))
            self.ui_queue.put(("finished",))

    def open_log_window(self):
        """Apre (o riporta in primo piano) la finestra dei log."""
        if self.log_window is not None and self.log_window.winfo_exists():
            self.log_window.deiconify()
            self.log_window.lift()
            return

        self.log_window = ctk.CTkToplevel(self)
        self.log_window.title("ChansonsVivante - Log elaborazione")
        self.log_window.geometry("820x480")
        self.log_window.minsize(600, 300)
        self.log_textbox = ctk.CTkTextbox(
            self.log_window, wrap="word", font=("Consolas", 11)
        )
        self.log_textbox.pack(fill="both", expand=True, padx=12, pady=(12, 6))
        self.log_textbox.configure(state="normal")
        for level, message in self.log_history:
            self.log_textbox.insert("end", f"[{level}] {message}\n")
        self.log_textbox.configure(state="disabled")
        controls = ctk.CTkFrame(self.log_window, fg_color="transparent")
        controls.pack(fill="x", padx=12, pady=(0, 12))
        ctk.CTkButton(controls, text="Svuota log", width=110, command=self.clear_log).pack(side="left")
        ctk.CTkButton(controls, text="Chiudi", width=90, command=self.log_window.withdraw).pack(side="right")
        self.log_window.protocol("WM_DELETE_WINDOW", self.log_window.withdraw)

    def append_log(self, level, message):
        self.log_history.append((level, message))
        # Evita una crescita illimitata della memoria durante sessioni molto lunghe.
        if len(self.log_history) > 5000:
            del self.log_history[:1000]
        if self.log_textbox is not None and self.log_window is not None:
            try:
                if self.log_window.winfo_exists():
                    self.log_textbox.configure(state="normal")
                    self.log_textbox.insert("end", f"[{level}] {message}\n")
                    self.log_textbox.see("end")
                    self.log_textbox.configure(state="disabled")
            except Exception:
                pass

    def clear_log(self):
        self.log_history.clear()
        if self.log_textbox is not None:
            self.log_textbox.configure(state="normal")
            self.log_textbox.delete("1.0", "end")
            self.log_textbox.configure(state="disabled")

    def refresh_gpu_info(self):
        memory = available_cuda_memory()
        if memory:
            free_gb, total_gb = memory
            self.gpu_info_label.configure(
                text=f"CUDA disponibile · VRAM libera {free_gb:.1f} GB / {total_gb:.1f} GB",
                text_color="green",
            )
        elif self.has_cuda:
            self.gpu_info_label.configure(
                text="CUDA rilevata; memoria libera non leggibile. Sarà usata la gestione prudenziale.",
                text_color="orange",
            )
        else:
            self.gpu_info_label.configure(
                text="GPU CUDA non disponibile: sarà possibile elaborare usando la CPU.",
                text_color="orange",
            )
        self.on_device_mode_change(self.device_mode_var.get())

    def on_budget_change(self, value):
        self.budget_gb = round(float(value) * 2) / 2
        self.budget_label.configure(text=f"Budget VRAM: {self.budget_gb:.1f} GB")

    def on_device_mode_change(self, _value=None):
        manual = self.device_mode_var.get() == "Manuale"
        state = "normal" if manual and self.has_cuda else "disabled"
        self.budget_slider.configure(state=state)
        self.device_menu.configure(
            values=["Automatica", "Manuale", "Solo CPU"] if self.has_cuda
            else ["Automatica", "Solo CPU"]
        )
        if not self.has_cuda and self.device_mode_var.get() == "Manuale":
            self.device_mode_var.set("Automatica")

    def browse_input(self):
        filename = filedialog.askopenfilename(
            filetypes=[
                ("File audio", "*.mp3 *.wav *.flac *.m4a"),
                ("Tutti i file", "*.*"),
            ]
        )
        if filename:
            self.input_file.set(filename)

    def browse_output(self):
        directory = filedialog.askdirectory()
        if directory:
            self.output_dir.set(directory)

    def set_running_state(self, running):
        state = "disabled" if running else "normal"
        self.btn_start.configure(
            state=state,
            text="Elaborazione in corso..." if running else "Avvia separazione",
        )
        for widget in self.interactive_widgets:
            widget.configure(state=state)
        if running:
            self.progress_bar.start()
        else:
            self.progress_bar.stop()
            self.progress_bar.set(0)
            self.refresh_gpu_info()

    def process_ui_queue(self):
        try:
            while True:
                item = self.ui_queue.get_nowait()
                kind = item[0]
                if kind == "log":
                    _, level, message = item
                    self.append_log(level, message)
                elif kind == "status":
                    _, message, color = item
                    self.status_label.configure(text=message, text_color=color)
                    self.append_log("INFO", message)
                elif kind == "error":
                    _, message = item
                    self.status_label.configure(text=f"Errore: {message}", text_color="red")
                    self.append_log("ERROR", message)
                    messagebox.showerror("Errore elaborazione AI", message)
                elif kind == "done":
                    _, message, folder = item
                    self.status_label.configure(text=message, text_color="green")
                    self.append_log("SUCCESS", message)
                    if folder and os.name == "nt":
                        try:
                            os.startfile(folder)
                        except OSError:
                            pass
                elif kind == "ai_ready":
                    self.ai_ready = True
                    try:
                        self.has_cuda = bool(torch.cuda.is_available())
                    except Exception:
                        self.has_cuda = False
                    self.status_label.configure(
                        text="Motore AI pronto. Pronto per l'elaborazione.",
                        text_color="green",
                    )
                    self.btn_start.configure(state="normal")
                    self.refresh_gpu_info()
                    self.after(100, self.check_model_on_startup)
                    self.append_log("SUCCESS", "Motore AI caricato.")
                elif kind == "ai_error":
                    _, message = item
                    self.status_label.configure(
                        text="Motore AI non disponibile.",
                        text_color="red",
                    )
                    self.append_log("ERROR", message)
                    messagebox.showerror("Errore avvio AI", message)
                elif kind == "model_install_finished":
                    self.model_installing = False
                elif kind == "finished":
                    self.set_running_state(False)
        except queue.Empty:
            pass
        self.after(100, self.process_ui_queue)

    def start_thread(self):
        if not self.ai_ready:
            messagebox.showinfo(
                "Motore AI",
                "Il motore AI è ancora in caricamento. Riprova tra qualche secondo.",
            )
            return

        input_name = self.input_file.get()
        if not input_name:
            messagebox.showerror("Errore", "Seleziona prima una traccia audio.")
            return
        if not Path(input_name).is_file():
            messagebox.showerror("Errore", "Il file audio selezionato non esiste.")
            return

        selected_model = self.model_var.get()
        try:
            installed = self.is_model_installed(selected_model)
        except Exception as error:
            messagebox.showerror("Errore modello", str(error))
            return
        if not installed:
            install = messagebox.askyesno(
                "Modello non installato",
                f"Il modello '{selected_model}' non è installato. Vuoi installarlo ora?\n\n"
                "Dopo il download, premi di nuovo 'Avvia separazione'."
            )
            if install:
                self.start_model_installation(selected_model)
            return

        settings = {
            "input_path": input_name,
            "output_dir": self.output_dir.get(),
            "format": self.format_var.get(),
            "model": self.model_var.get(),
            "is_24bit": self.bit_var.get() == "24-bit",
            "shifts": int(self.shifts_var.get().split()[0]),
            "two_stems": "2 tracce" in self.stems_var.get(),
            "device_mode": self.device_mode_var.get(),
            "budget_gb": self.budget_gb,
        }
        self.set_running_state(True)
        self.ui_queue.put(("status", "Preparazione separazione...", "orange"))
        threading.Thread(
            target=self.run_demucs_api, args=(settings,), daemon=True
        ).start()

    def choose_gpu_budget(self, settings):
        memory = available_cuda_memory()
        if memory is None:
            return None, "CUDA non disponibile o memoria GPU non rilevabile."

        free_gb, total_gb = memory
        reserve = max(VRAM_RESERVE_GB, total_gb * 0.12)
        usable_gb = max(0.0, free_gb - reserve)

        if settings["device_mode"] == "Solo CPU":
            return None, "Modalità CPU selezionata."

        if settings["device_mode"] == "Manuale":
            target = min(settings["budget_gb"], usable_gb)
            if target < 1.0:
                return None, (
                    f"VRAM libera insufficiente: {free_gb:.1f} GB. "
                    "Passaggio alla CPU per evitare un avvio destinato a fallire."
                )
            return target, (
                f"Budget richiesto {settings['budget_gb']:.1f} GB; "
                f"budget GPU effettivo stimato {target:.1f} GB."
            )

        if usable_gb < 1.0:
            return None, (
                f"Solo {free_gb:.1f} GB di VRAM libera: uso della CPU."
            )
        target = min(usable_gb, max(1.0, total_gb * 0.65))
        return target, (
            f"Gestione automatica: {free_gb:.1f} GB liberi, "
            f"budget GPU stimato {target:.1f} GB."
        )

    def separate_with_gpu(self, audio_tensor, sample_rate, settings, budget_gb):
        initial_segment = segment_for_budget(budget_gb)
        try:
            supports_segment = "segment" in inspect.signature(demucs.api.Separator).parameters
        except (TypeError, ValueError):
            supports_segment = False

        if not supports_segment:
            # Versioni Demucs meno recenti possono non esporre il parametro segment.
            # In quel caso evitiamo un TypeError e tentiamo una sola esecuzione standard.
            attempts = [None]
        elif initial_segment is None:
            attempts = SEGMENT_RETRY_ORDER
        else:
            attempts = [initial_segment] + [
                segment for segment in SEGMENT_RETRY_ORDER
                if segment is not None and segment < initial_segment
            ]

        last_oom_message = None
        for segment in attempts:
            try:
                self.ui_queue.put((
                    "status",
                    "Separazione su GPU" + (
                        f" · segmenti da {segment:g} s" if segment else " · segmentazione predefinita"
                    ),
                    "green",
                ))
                separator_kwargs = {
                    "model": settings["model"],
                    "device": "cuda",
                    "shifts": settings["shifts"],
                    "overlap": 0.25,
                }
                if segment is not None and supports_segment:
                    separator_kwargs["segment"] = segment
                separator = demucs.api.Separator(**separator_kwargs)
                origin, separated = separator.separate_tensor(audio_tensor, sample_rate)
                return separator, origin, separated
            except Exception as error:
                if not is_cuda_oom(error):
                    raise
                last_oom_message = str(error)
                # Rimuove i riferimenti del traceback a tensori/modelli CUDA prima del retry.
                try:
                    error.__traceback__ = None
                except Exception:
                    pass
                self.ui_queue.put((
                    "status",
                    "Memoria GPU esaurita: riduco i segmenti e riprovo...",
                    "orange",
                ))
                try:
                    del separator
                except UnboundLocalError:
                    pass
                gc.collect()
                try:
                    torch.cuda.empty_cache()
                except Exception:
                    pass

        raise RuntimeError(last_oom_message or "CUDA out of memory: memoria GPU insufficiente.")

    def run_demucs_api(self, settings):
        """Cattura i messaggi stdout/stderr di Demucs e delle librerie usate."""
        self.ui_queue.put(("log", "INFO", "Avvio elaborazione Demucs."))
        stdout_stream = QueueLogStream(self.ui_queue, "INFO")
        stderr_stream = QueueLogStream(self.ui_queue, "WARNING")
        try:
            with contextlib.redirect_stdout(stdout_stream), contextlib.redirect_stderr(stderr_stream):
                self._run_demucs_api_impl(settings)
        finally:
            stdout_stream.flush()
            stderr_stream.flush()

    def _run_demucs_api_impl(self, settings):
        try:
            input_path = Path(settings["input_path"]).resolve()
            out_dir = Path(settings["output_dir"]).resolve()
            fmt = settings["format"]

            self.ui_queue.put(("status", "Caricamento file audio...", "orange"))
            data, sample_rate = sf.read(
                str(input_path), dtype="float32", always_2d=True
            )
            audio_tensor = torch.from_numpy(data).t().contiguous()

            budget_gb, budget_message = self.choose_gpu_budget(settings)
            self.ui_queue.put(("status", budget_message, "orange"))

            separator = None
            if budget_gb is not None:
                try:
                    separator, origin, separated = self.separate_with_gpu(
                        audio_tensor, sample_rate, settings, budget_gb
                    )
                except Exception as error:
                    if not is_cuda_oom(error):
                        raise
                    gc.collect()
                    try:
                        torch.cuda.empty_cache()
                    except Exception:
                        pass
                    self.ui_queue.put((
                        "status",
                        "La GPU non ha memoria sufficiente anche con segmenti ridotti: riprovo su CPU. Potrebbe richiedere molto più tempo.",
                        "orange",
                    ))
                    separator = demucs.api.Separator(
                        model=settings["model"],
                        device="cpu",
                        shifts=settings["shifts"],
                        overlap=0.25,
                    )
                    origin, separated = separator.separate_tensor(audio_tensor, sample_rate)
            else:
                self.ui_queue.put(("status", "Separazione su CPU...", "orange"))
                separator = demucs.api.Separator(
                    model=settings["model"],
                    device="cpu",
                    shifts=settings["shifts"],
                    overlap=0.25,
                )
                origin, separated = separator.separate_tensor(audio_tensor, sample_rate)

            self.ui_queue.put(("status", "Salvataggio dei file separati...", "orange"))
            is_24bit = settings["is_24bit"]
            kwargs = {
                "samplerate": separator.samplerate,
                "bitrate": 320 if fmt == "mp3" else None,
                "preset": 2 if fmt == "mp3" else None,
                "clip": "rescale",
                "as_float": False if is_24bit or fmt == "mp3" else True,
                "bits_per_sample": 24 if is_24bit and fmt in ("wav", "flac") else 16,
            }

            # Una cartella per brano direttamente nella destinazione scelta:
            # niente sottocartella aggiuntiva con il nome del modello.
            final_folder = out_dir / input_path.stem
            final_folder.mkdir(parents=True, exist_ok=True)

            if settings["two_stems"]:
                vocals = separated["vocals"]
                accompaniment = sum(
                    tensor for name, tensor in separated.items() if name != "vocals"
                )
                demucs.api.save_audio(vocals, final_folder / f"vocals.{fmt}", **kwargs)
                demucs.api.save_audio(
                    accompaniment, final_folder / f"no_vocals.{fmt}", **kwargs
                )
            else:
                for stem_name, stem_tensor in separated.items():
                    demucs.api.save_audio(
                        stem_tensor, final_folder / f"{stem_name}.{fmt}", **kwargs
                    )

            if not final_folder.exists() or not any(final_folder.iterdir()):
                raise RuntimeError("I file non sono stati scritti nella cartella finale.")

            self.ui_queue.put((
                "done",
                "Completato con successo!",
                str(final_folder),
            ))
        except Exception as error:
            self.ui_queue.put(("error", str(error)))
        finally:
            self.ui_queue.put(("finished",))


if __name__ == "__main__":
    try:
        # Distrugge lo splash prima di creare la root principale:
        # Tkinter deve associare il default root all'istanza DemucsApp.
        try:
            _splash.destroy()
        except Exception:
            pass
        app = DemucsApp()
        app.mainloop()
    except Exception:
        try:
            _splash.destroy()
        except Exception:
            pass
        raise
