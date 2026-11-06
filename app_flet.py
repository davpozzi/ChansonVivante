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
import asyncio
import flet as ft


class Value:
    def get(self):
        return self.value
    def set(self, value):
        self.value = value


torch = None
demucs = None
sf = None

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


class DemucsApp:
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



    def __init__(self, page):
        self.page = page
        page.title = "ChansonVivante — AI Audio Separation"
        page.theme_mode = ft.ThemeMode.DARK
        page.bgcolor = "#0b1020"
        page.padding = 0
        page.window_width = 900
        page.window_height = 940
        page.window_min_width = 760
        page.window_min_height = 780
        page.window_resizable = True
        self.input_file = Value("")
        self.output_dir = Value(str(APP_ROOT))
        self.format_var = Value("flac")
        self.bit_var = Value("16-bit")
        self.model_var = Value("htdemucs")
        self.stems_var = Value("Solo Voce e Base (2 tracce)")
        self.shifts_var = Value("1 (Standard)")
        self.device_mode_var = Value("Automatica")
        self.budget_gb = 3.0
        self.ui_queue = queue.Queue()
        self.log_history = []
        self.log_window = None
        self.log_textbox = None
        self.has_cuda = False
        self.ai_ready = False
        self.model_installing = False
        self._build_ui()
        self.page.run_task(self._poll_queue)
        self.page.run_task(self._load_ai_after_ui)

    def _build_ui(self):
        self.input_picker = ft.FilePicker(on_result=self._input_picked)
        self.output_picker = ft.FilePicker(on_result=self._output_picked)
        self.page.overlay.extend([self.input_picker, self.output_picker])

        self.input_field = ft.TextField(label="Traccia audio", value="", read_only=True,
            expand=True, border_radius=12, hint_text="Seleziona un file MP3, WAV, FLAC o M4A")
        self.output_field = ft.TextField(label="Cartella di destinazione", value=str(APP_ROOT),
            read_only=True, expand=True, border_radius=12)
        self.format_control = ft.Dropdown(label="Formato", value="flac", width=150,
            options=[ft.dropdown.Option(x) for x in ["flac", "wav", "mp3"]],
            on_change=lambda e: self.format_var.set(e.control.value))
        self.bit_control = ft.Dropdown(label="Qualità", value="16-bit", width=150,
            options=[ft.dropdown.Option(x) for x in ["16-bit", "24-bit"]],
            on_change=lambda e: self.bit_var.set(e.control.value))
        self.model_control = ft.Dropdown(label="Modello AI", value="htdemucs", expand=True,
            options=[ft.dropdown.Option(x) for x in ["htdemucs", "htdemucs_ft"]],
            on_change=lambda e: self.model_var.set(e.control.value))
        self.shifts_control = ft.Dropdown(label="Shifts", value="1 (Standard)", width=180,
            options=[ft.dropdown.Option(x) for x in ["0 (Veloce)", "1 (Standard)", "2 (Preciso)", "3 (Lento)"]],
            on_change=lambda e: self.shifts_var.set(e.control.value))
        self.stems_control = ft.Dropdown(label="Separazione", value=self.stems_var.get(), expand=True,
            options=[ft.dropdown.Option("Solo Voce e Base (2 tracce)"),
                     ft.dropdown.Option("Tutti gli strumenti (4 tracce)")],
            on_change=lambda e: self.stems_var.set(e.control.value))
        self.device_control = ft.Dropdown(label="Modalità GPU", value="Automatica", width=190,
            options=[ft.dropdown.Option(x) for x in ["Automatica", "Manuale", "Solo CPU"]],
            on_change=self._device_changed)
        self.budget_text = ft.Text("Budget VRAM: 3.0 GB", color="#cbd5e1", weight=ft.FontWeight.W_600)
        self.budget_slider = ft.Slider(min=1, max=12, divisions=22, value=3,
            on_change=self._budget_changed, expand=True)
        self.gpu_info = ft.Text("Rilevamento GPU...", color="#94a3b8", size=12)
        self.status_text = ft.Text("Interfaccia pronta · caricamento motore AI...", color="#fbbf24", size=13)
        self.progress = ft.ProgressRing(width=22, height=22, stroke_width=3, visible=False)
        self.start_button = ft.ElevatedButton("Avvia separazione", icon=ft.icons.PLAY_ARROW,
            on_click=self._start_clicked, height=48, expand=True,
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12)), disabled=True)
        self.logs_button = ft.OutlinedButton("Mostra log", icon=ft.icons.TERMINAL,
            on_click=lambda e: self.open_log_window())

        card_style = dict(bgcolor="#111a2e", border=ft.border.all(1, "#24324b"),
                          border_radius=18, padding=18)
        header = ft.Row([
            ft.Container(content=ft.Icon(ft.icons.GRAPHIC_EQ, size=30, color="#7dd3fc"),
                         bgcolor="#123047", padding=12, border_radius=14),
            ft.Column([
                ft.Text("ChansonVivante", size=25, weight=ft.FontWeight.BOLD, color="#f8fafc"),
                ft.Text("AI AUDIO SEPARATOR  ·  DEMUCS", size=11, color="#7dd3fc",
                        weight=ft.FontWeight.BOLD),
            ], spacing=3, expand=True),
            ft.Container(content=ft.Text("DESKTOP", size=10, weight=ft.FontWeight.BOLD,
                         color="#a5b4fc"), bgcolor="#24264a", padding=10, border_radius=20)
        ], alignment=ft.MainAxisAlignment.START)

        self.input_browse_button = ft.IconButton(ft.icons.AUDIO_FILE,
            tooltip="Scegli file audio", on_click=lambda e: self.input_picker.pick_files(
            allow_multiple=False, allowed_extensions=["mp3", "wav", "flac", "m4a"]))
        self.output_browse_button = ft.IconButton(ft.icons.FOLDER_OPEN,
            tooltip="Scegli cartella", on_click=lambda e: self.output_picker.get_directory_path())
        files = ft.Container(
            content=ft.Column([
                ft.Text("SORGENTE E DESTINAZIONE", size=11, color="#7dd3fc", weight=ft.FontWeight.BOLD),
                ft.Row([self.input_field, self.input_browse_button]),
                ft.Row([self.output_field, self.output_browse_button]),
            ], spacing=8), **card_style)

        settings = ft.Container(content=ft.Column([
            ft.Text("IMPOSTAZIONI DI SEPARAZIONE", size=11, color="#7dd3fc", weight=ft.FontWeight.BOLD),
            ft.Row([self.format_control, self.bit_control], wrap=True),
            ft.Row([self.model_control, self.shifts_control], wrap=True),
            ft.Text("htdemucs è il modello standard; htdemucs_ft può offrire una separazione leggermente migliore ma richiede circa 4 volte più tempo.",
                    color="#94a3b8", size=12),
            self.stems_control,
        ], spacing=12), **card_style)

        gpu = ft.Container(content=ft.Column([
            ft.Text("ACCELERAZIONE E MEMORIA GPU", size=11, color="#7dd3fc", weight=ft.FontWeight.BOLD),
            ft.Row([self.device_control, self.budget_text]),
            ft.Row([self.budget_slider, ft.Text("1–12 GB", size=11, color="#94a3b8")]),
            self.gpu_info,
        ], spacing=10), **card_style)

        footer = ft.Container(content=ft.Column([
            ft.Row([self.progress, self.status_text], spacing=12),
            ft.Row([self.start_button, self.logs_button]),
            ft.Text("Il budget VRAM è un obiettivo indicativo, non un limite hardware assoluto. La memoria usata da Windows, PyTorch e altri programmi può variare.",
                    color="#64748b", size=11, text_align=ft.TextAlign.CENTER),
        ], spacing=12), padding=ft.padding.symmetric(horizontal=4, vertical=8))

        self.page.add(ft.Container(
            content=ft.Column([header, files, settings, gpu, footer], spacing=14,
                scroll=ft.ScrollMode.AUTO),
            padding=ft.padding.symmetric(horizontal=26, vertical=22),
            expand=True,
        ))
        self.page.update()

    async def _load_ai_after_ui(self):
        self.status_text.value = "Caricamento motore AI in background..."
        self.page.update()
        threading.Thread(target=self.load_ai_dependencies_worker, daemon=True).start()

    async def _poll_queue(self):
        while True:
            try:
                while True:
                    item = self.ui_queue.get_nowait()
                    kind = item[0]
                    if kind == "log":
                        self.append_log(item[1], item[2])
                    elif kind == "status":
                        self.status_text.value = item[1]
                        self.status_text.color = item[2]
                        self.append_log("INFO", item[1])
                    elif kind == "error":
                        self.status_text.value = f"Errore: {item[1]}"
                        self.status_text.color = "#f87171"
                        self.append_log("ERROR", item[1])
                        self._message("Errore elaborazione AI", item[1])
                    elif kind == "done":
                        self.status_text.value = item[1]
                        self.status_text.color = "#4ade80"
                        self.append_log("SUCCESS", item[1])
                        if item[2] and os.name == "nt":
                            try: os.startfile(item[2])
                            except OSError: pass
                    elif kind == "ai_ready":
                        self.ai_ready = True
                        try: self.has_cuda = bool(torch.cuda.is_available())
                        except Exception: self.has_cuda = False
                        self.status_text.value = "Motore AI pronto. Pronto per l'elaborazione."
                        self.status_text.color = "#4ade80"
                        self.start_button.disabled = False
                        self.refresh_gpu_info()
                        self.append_log("SUCCESS", "Motore AI caricato.")
                        await asyncio.sleep(0.1)
                        self.check_model_on_startup()
                    elif kind == "ai_error":
                        self.status_text.value = "Motore AI non disponibile."
                        self.status_text.color = "#f87171"
                        self.append_log("ERROR", item[1])
                        self._message("Errore avvio AI", item[1])
                    elif kind == "model_install_finished":
                        self.model_installing = False
                    elif kind == "finished":
                        self.set_running_state(False)
            except queue.Empty:
                pass
            self.page.update()
            await asyncio.sleep(0.1)

    def _input_picked(self, e):
        if e.files:
            self.input_file.set(e.files[0].path)
            self.input_field.value = e.files[0].path
            self.page.update()

    def _output_picked(self, e):
        if e.path:
            self.output_dir.set(e.path)
            self.output_field.value = e.path
            self.page.update()

    def _message(self, title, message):
        dlg = ft.AlertDialog(title=ft.Text(title), content=ft.Text(message),
            actions=[ft.TextButton("OK", on_click=lambda e: self.page.close(dlg))])
        self.page.open(dlg)

    def _confirm(self, title, message, yes_callback):
        def yes(e):
            self.page.close(dlg)
            yes_callback()
        dlg = ft.AlertDialog(title=ft.Text(title), content=ft.Text(message),
            actions=[ft.TextButton("Annulla", on_click=lambda e: self.page.close(dlg)),
                     ft.FilledButton("Sì", on_click=yes)])
        self.page.open(dlg)

    def _start_clicked(self, e):
        self.start_thread()

    def _device_changed(self, e):
        self.device_mode_var.set(e.control.value)
        self.on_device_mode_change(e.control.value)
        self.page.update()

    def _budget_changed(self, e):
        self.on_budget_change(e.control.value)
        self.page.update()

    def check_model_on_startup(self):
        model_name = self.model_var.get()
        try:
            installed = self.is_model_installed(model_name)
        except Exception as error:
            self.append_log("WARNING", f"Controllo modello non riuscito: {error}")
            return
        if not installed:
            self._confirm("Modello non installato",
                f"Il modello '{model_name}' non è installato. Vuoi installarlo ora?\n\nIl download verrà mostrato nella finestra dei log.",
                lambda: self.start_model_installation(model_name))

    def start_thread(self):
        if not self.ai_ready:
            self._message("Motore AI", "Il motore AI è ancora in caricamento. Riprova tra qualche secondo.")
            return
        input_name = self.input_file.get()
        if not input_name:
            self._message("Errore", "Seleziona prima una traccia audio.")
            return
        if not Path(input_name).is_file():
            self._message("Errore", "Il file audio selezionato non esiste.")
            return
        selected_model = self.model_var.get()
        try: installed = self.is_model_installed(selected_model)
        except Exception as error:
            self._message("Errore modello", str(error)); return
        if not installed:
            self._confirm("Modello non installato",
                f"Il modello '{selected_model}' non è installato. Vuoi installarlo ora?\n\nDopo il download, premi di nuovo 'Avvia separazione'.",
                lambda: self.start_model_installation(selected_model))
            return
        settings = {
            "input_path": input_name, "output_dir": self.output_dir.get(),
            "format": self.format_var.get(), "model": self.model_var.get(),
            "is_24bit": self.bit_var.get() == "24-bit",
            "shifts": int(self.shifts_var.get().split()[0]),
            "two_stems": "2 tracce" in self.stems_var.get(),
            "device_mode": self.device_mode_var.get(), "budget_gb": self.budget_gb,
        }
        self.set_running_state(True)
        self.ui_queue.put(("status", "Preparazione separazione...", "#fbbf24"))
        threading.Thread(target=self.run_demucs_api, args=(settings,), daemon=True).start()

    def open_log_window(self):
        if self.log_window is not None:
            self.page.open(self.log_window)
            return
        self.log_content = ft.TextField(value="", multiline=True, min_lines=15,
            max_lines=24, read_only=True, text_size=12, expand=True,
            text_style=ft.TextStyle(font_family="Consolas"))
        dlg = ft.AlertDialog(
            modal=False, title=ft.Text("ChansonVivante · Log elaborazione"),
            content=ft.Container(content=self.log_content, width=760, height=430),
            actions=[
                ft.TextButton("Svuota log", on_click=lambda e: self.clear_log()),
                ft.TextButton("Chiudi", on_click=lambda e: self.page.close(dlg)),
            ])
        self.log_window = dlg
        self.page.open(dlg)
        self._refresh_log_view()

    def append_log(self, level, message):
        self.log_history.append((level, message))
        if len(self.log_history) > 5000:
            del self.log_history[:1000]
        if self.log_window is not None:
            self._refresh_log_view()

    def _refresh_log_view(self):
        if self.log_window is not None:
            self.log_content.value = "\n".join(f"[{level}] {msg}" for level, msg in self.log_history)
            self.page.update()

    def clear_log(self):
        self.log_history.clear()
        self._refresh_log_view()

    def refresh_gpu_info(self):
        memory = available_cuda_memory()
        if memory:
            free_gb, total_gb = memory
            self.gpu_info.value = f"CUDA disponibile · VRAM libera {free_gb:.1f} GB / {total_gb:.1f} GB"
            self.gpu_info.color = "#4ade80"
        elif self.has_cuda:
            self.gpu_info.value = "CUDA rilevata; memoria libera non leggibile. Sarà usata la gestione prudenziale."
            self.gpu_info.color = "#fbbf24"
        else:
            self.gpu_info.value = "GPU CUDA non disponibile: sarà possibile elaborare usando la CPU."
            self.gpu_info.color = "#fbbf24"
        self.on_device_mode_change(self.device_mode_var.get())

    def on_budget_change(self, value):
        self.budget_gb = round(float(value) * 2) / 2
        self.budget_text.value = f"Budget VRAM: {self.budget_gb:.1f} GB"

    def on_device_mode_change(self, _value=None):
        manual = self.device_mode_var.get() == "Manuale"
        self.budget_slider.disabled = not (manual and self.has_cuda)
        options = ["Automatica", "Manuale", "Solo CPU"] if self.has_cuda else ["Automatica", "Solo CPU"]
        self.device_control.options = [ft.dropdown.Option(x) for x in options]
        if not self.has_cuda and self.device_mode_var.get() == "Manuale":
            self.device_mode_var.set("Automatica")
            self.device_control.value = "Automatica"

    def set_running_state(self, running):
        self.start_button.disabled = running or not self.ai_ready
        self.start_button.text = "Elaborazione in corso..." if running else "Avvia separazione"
        for control in [self.input_field, self.output_field, self.format_control,
                        self.bit_control, self.model_control, self.shifts_control,
                        self.stems_control, self.device_control, self.budget_slider,
                        self.input_browse_button, self.output_browse_button]:
            control.disabled = running
        self.progress.visible = running
        self.page.update()

    def browse_input(self):
        self.input_picker.pick_files(allow_multiple=False,
            allowed_extensions=["mp3", "wav", "flac", "m4a"])

    def browse_output(self):
        self.output_picker.get_directory_path()

async def main(page: ft.Page):
    started = asyncio.get_running_loop().time()
    page.title = "ChansonVivante"
    page.bgcolor = "#0b1020"
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.vertical_alignment = ft.MainAxisAlignment.CENTER
    page.add(ft.Container(
        content=ft.Column([
            ft.Icon(ft.icons.GRAPHIC_EQ, size=54, color="#7dd3fc"),
            ft.Text("ChansonVivante", size=30, weight=ft.FontWeight.BOLD, color="#f8fafc"),
            ft.Text("Preparazione dell'ambiente audio…", color="#94a3b8", size=13),
            ft.ProgressRing(width=24, height=24, stroke_width=3, color="#7dd3fc"),
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=18),
        padding=50, bgcolor="#111a2e", border=ft.border.all(1, "#24324b"), border_radius=24
    ))
    page.update()
    await asyncio.sleep(max(0.0, 1.0 - (asyncio.get_running_loop().time() - started)))
    page.clean()
    DemucsApp(page)

if __name__ == "__main__":
    ft.app(target=main)
