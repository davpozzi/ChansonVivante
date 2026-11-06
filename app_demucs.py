import gc
import os
import queue
import sys
import threading
from pathlib import Path
from tkinter import filedialog, messagebox

# Disattiviamo esplicitamente torchcodec prima di caricare qualsiasi altra cosa.
os.environ["TORCHAUDIO_USE_TORCHCODEC"] = "0"
os.environ["PYTHONIOENCODING"] = "utf-8"

import customtkinter as ctk
import soundfile as sf
import torch

try:
    import demucs.api
except ImportError:
    raise SystemExit(
        "Errore: la libreria 'demucs' non è installata o non è configurata correttamente."
    )

try:
    import imageio_ffmpeg

    ffmpeg_exe_path = Path(imageio_ffmpeg.get_ffmpeg_exe())
    ffmpeg_folder = str(ffmpeg_exe_path.parent.resolve())
    os.environ["PATH"] = ffmpeg_folder + os.pathsep + os.environ.get("PATH", "")
except ImportError:
    raise SystemExit("Errore: il modulo 'imageio-ffmpeg' non è installato.")


ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

GB = 1024 ** 3
VRAM_RESERVE_GB = 0.75
# Retry progressivamente più leggeri. None lascia a Demucs il segmento predefinito.
SEGMENT_RETRY_ORDER = [None, 5.0, 3.0, 2.0, 1.5]


def resource_path(relative_path):
    """Restituisce un percorso valido sia da sorgente sia da EXE."""
    base_path = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent.resolve()
    return str((base_path / relative_path).resolve())


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
    if not torch.cuda.is_available():
        return None
    try:
        free_bytes, total_bytes = torch.cuda.mem_get_info()
        return free_bytes / GB, total_bytes / GB
    except Exception:
        return None


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
        self.output_dir = ctk.StringVar(
            value=str(Path.home() / "Downloads" / "Output_Audio")
        )
        self.format_var = ctk.StringVar(value="flac")
        self.bit_var = ctk.StringVar(value="16-bit")
        self.model_var = ctk.StringVar(value="htdemucs")
        self.stems_var = ctk.StringVar(value="Solo Voce e Base (2 tracce)")
        self.shifts_var = ctk.StringVar(value="1 (Standard)")
        self.device_mode_var = ctk.StringVar(value="Automatica")
        self.budget_gb = 3.0

        self.ui_queue = queue.Queue()
        self.interactive_widgets = []
        self.has_cuda = bool(torch.cuda.is_available())
        self.create_widgets()
        self.refresh_gpu_info()
        self.after(100, self.process_ui_queue)

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
            row=2, column=0, padx=10, pady=8, sticky="w"
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
        opt_stems.grid(row=2, column=1, columnspan=3, padx=8, pady=8, sticky="w")

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
        self.btn_start.pack(pady=14)

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
                if kind == "status":
                    _, message, color = item
                    self.status_label.configure(text=message, text_color=color)
                elif kind == "error":
                    _, message = item
                    self.status_label.configure(text=f"Errore: {message}", text_color="red")
                    messagebox.showerror("Errore elaborazione AI", message)
                elif kind == "done":
                    _, message, folder = item
                    self.status_label.configure(text=message, text_color="green")
                    if folder and os.name == "nt":
                        try:
                            os.startfile(folder)
                        except OSError:
                            pass
                elif kind == "finished":
                    self.set_running_state(False)
        except queue.Empty:
            pass
        self.after(100, self.process_ui_queue)

    def start_thread(self):
        input_name = self.input_file.get()
        if not input_name:
            messagebox.showerror("Errore", "Seleziona prima una traccia audio.")
            return
        if not Path(input_name).is_file():
            messagebox.showerror("Errore", "Il file audio selezionato non esiste.")
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
        if initial_segment is None:
            attempts = SEGMENT_RETRY_ORDER
        else:
            attempts = [initial_segment] + [
                segment for segment in SEGMENT_RETRY_ORDER
                if segment is not None and segment < initial_segment
            ]

        last_oom = None
        for segment in attempts:
            try:
                self.ui_queue.put((
                    "status",
                    "Separazione su GPU" + (
                        f" · segmenti da {segment:g} s" if segment else " · segmentazione predefinita"
                    ),
                    "green",
                ))
                separator = demucs.api.Separator(
                    model=settings["model"],
                    device="cuda",
                    shifts=settings["shifts"],
                    overlap=0.25,
                    segment=segment,
                )
                origin, separated = separator.separate_tensor(audio_tensor, sample_rate)
                return separator, origin, separated
            except Exception as error:
                if not is_cuda_oom(error):
                    raise
                last_oom = error
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
                torch.cuda.empty_cache()

        raise last_oom or RuntimeError("Memoria GPU insufficiente.")

    def run_demucs_api(self, settings):
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
                    torch.cuda.empty_cache()
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

            final_folder = out_dir / settings["model"] / input_path.stem
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
    app = DemucsApp()
    app.mainloop()
