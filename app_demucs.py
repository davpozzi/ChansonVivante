import os
import sys

# Disattiviamo esplicitamente torchcodec prima di caricare qualsiasi altra cosa
os.environ["TORCHAUDIO_USE_TORCHCODEC"] = "0"
os.environ["PYTHONIOENCODING"] = "utf-8"

import customtkinter as ctk
from tkinter import filedialog, messagebox
import threading
from pathlib import Path

import torch
import soundfile as sf

# Importiamo l'API di alto livello di Demucs per l'elaborazione diretta in memoria
try:
    import demucs.api
except ImportError:
    print("Errore: la libreria 'demucs' non è installata o non è configurata correttamente nel venv.")
    sys.exit(1)

# Iniezione di imageio_ffmpeg per assicurarci che Demucs possa SCRIVERE i file finali (output)
try:
    import imageio_ffmpeg
    ffmpeg_exe_path = Path(imageio_ffmpeg.get_ffmpeg_exe())
    ffmpeg_folder = str(ffmpeg_exe_path.parent.resolve())
    os.environ["PATH"] = ffmpeg_folder + os.pathsep + os.environ.get("PATH", "")
except ImportError:
    print("Errore: il modulo 'imageio-ffmpeg' non è installato.")
    sys.exit(1)

# Tema dell'applicazione
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

def resource_path(relative_path):
    """ Gestisce i percorsi dei file in modo ASSOLUTO per Script ed EXE """
    if getattr(sys, 'frozen', False):
        base_path = Path(sys.executable).parent
    else:
        base_path = Path(__file__).parent.resolve()
    
    return str((base_path / relative_path).resolve())


class DemucsApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("ChansonsVivante Audio Separator")
        self.geometry("700x650")
        self.resizable(False, False)

        icon_path = resource_path("logo.ico")
        if os.path.exists(icon_path):
            self.iconbitmap(icon_path)

        # --- VARIABILI ---
        self.input_file = ctk.StringVar()
        self.output_dir = ctk.StringVar(value=str(Path(os.path.expanduser("~")) / "Downloads" / "Output_Audio"))
        self.format_var = ctk.StringVar(value="flac")
        self.bit_var    = ctk.StringVar(value="16-bit")
        self.model_var  = ctk.StringVar(value="htdemucs")
        self.stems_var  = ctk.StringVar(value="Solo Voce e Base (2 tracce)")
        self.shifts_var = ctk.StringVar(value="1 (Standard)")

        self.interactive_widgets = []
        self.check_gpu_availability()
        self.create_widgets()

    def check_gpu_availability(self):
        try:
            self.has_cuda = torch.cuda.is_available()
        except Exception:
            self.has_cuda = False

    def create_widgets(self):
        # TITOLO
        title = ctk.CTkLabel(self, text="ChansonsVivante - AI Audio Separation",
                             font=ctk.CTkFont(size=20, weight="bold"))
        title.pack(pady=20)

        # SEZIONE 1: FILE E CARTELLE
        frame_files = ctk.CTkFrame(self)
        frame_files.pack(pady=10, padx=20, fill="x")

        ctk.CTkLabel(frame_files, text="Traccia Audio:").grid(row=0, column=0, padx=10, pady=10, sticky="w")
        ctk.CTkEntry(frame_files, textvariable=self.input_file, width=350, state="readonly").grid(row=0, column=1, padx=10, pady=10)
        btn_browse_in = ctk.CTkButton(frame_files, text="Scegli File", command=self.browse_input)
        btn_browse_in.grid(row=0, column=2, padx=10, pady=10)

        ctk.CTkLabel(frame_files, text="Salva in:").grid(row=1, column=0, padx=10, pady=10, sticky="w")
        ctk.CTkEntry(frame_files, textvariable=self.output_dir, width=350, state="readonly").grid(row=1, column=1, padx=10, pady=10)
        btn_browse_out = ctk.CTkButton(frame_files, text="Scegli Cartella", command=self.browse_output)
        btn_browse_out.grid(row=1, column=2, padx=10, pady=10)

        # SEZIONE 2: IMPOSTAZIONI
        frame_settings = ctk.CTkFrame(self)
        frame_settings.pack(pady=10, padx=20, fill="x")

        ctk.CTkLabel(frame_settings, text="Formato:").grid(row=0, column=0, padx=10, pady=10, sticky="w")
        opt_format = ctk.CTkOptionMenu(frame_settings, variable=self.format_var, values=["flac", "wav", "mp3"])
        opt_format.grid(row=0, column=1, padx=10, pady=10, sticky="w")

        ctk.CTkLabel(frame_settings, text="Qualità:").grid(row=0, column=2, padx=10, pady=10, sticky="w")
        opt_bit = ctk.CTkOptionMenu(frame_settings, variable=self.bit_var, values=["16-bit", "24-bit"])
        opt_bit.grid(row=0, column=3, padx=10, pady=10, sticky="w")

        ctk.CTkLabel(frame_settings, text="Modello AI:").grid(row=1, column=0, padx=10, pady=10, sticky="w")
        opt_model = ctk.CTkOptionMenu(frame_settings, variable=self.model_var, values=["htdemucs", "htdemucs_ft"])
        opt_model.grid(row=1, column=1, padx=10, pady=10, sticky="w")

        ctk.CTkLabel(frame_settings, text="Shifts:").grid(row=1, column=2, padx=10, pady=10, sticky="w")
        opt_shifts = ctk.CTkOptionMenu(frame_settings, variable=self.shifts_var,
                                       values=["0 (Veloce)", "1 (Standard)", "2 (Preciso)", "3 (Lento)"])
        opt_shifts.grid(row=1, column=3, padx=10, pady=10, sticky="w")

        ctk.CTkLabel(frame_settings, text="Separazione:").grid(row=2, column=0, padx=10, pady=10, sticky="w")
        opt_stems = ctk.CTkOptionMenu(frame_settings, variable=self.stems_var,
                                      values=["Solo Voce e Base (2 tracce)", "Tutti gli strumenti (4 tracce)"], width=200)
        opt_stems.grid(row=2, column=1, columnspan=3, padx=10, pady=10, sticky="w")

        self.interactive_widgets.extend([btn_browse_in, btn_browse_out, opt_format, opt_bit, opt_model, opt_shifts, opt_stems])

        # SEZIONE 3: STATO E AVANZAMENTO
        self.status_label = ctk.CTkLabel(self, text="Pronto.", text_color="gray")
        self.status_label.pack(pady=(20, 5))

        self.progress_bar = ctk.CTkProgressBar(self, width=600)
        self.progress_bar.pack(pady=10)
        self.progress_bar.set(0)
        self.progress_bar.configure(mode="indefinite")

        # PULSANTE START
        self.btn_start = ctk.CTkButton(self, text="Avvia Separazione",
                                       font=ctk.CTkFont(weight="bold"), height=40,
                                       command=self.start_thread)
        self.btn_start.pack(pady=20)

    def browse_input(self):
        filename = filedialog.askopenfilename(filetypes=[("File Audio", "*.mp3 *.wav *.flac *.m4a")])
        if filename:
            self.input_file.set(filename)

    def browse_output(self):
        directory = filedialog.askdirectory()
        if directory:
            self.output_dir.set(directory)

    def update_ui_state(self, is_running):
        state = "disabled" if is_running else "normal"
        self.btn_start.configure(state=state,
                                 text="Elaborazione in corso..." if is_running else "Avvia Separazione")
        for widget in self.interactive_widgets:
            widget.configure(state=state)
        if is_running:
            self.progress_bar.start()
        else:
            self.progress_bar.stop()
            self.progress_bar.set(0)

    def start_thread(self):
        if not self.input_file.get():
            messagebox.showerror("Errore", "Seleziona prima una traccia audio.")
            return

        self.update_ui_state(True)
        device_str = "GPU Ultra-Veloce" if self.has_cuda else "CPU Lenta"
        self.status_label.configure(text=f"Separazione in corso ({device_str}). Attendere...", text_color="orange")

        threading.Thread(target=self.run_demucs_api, daemon=True).start()

    def run_demucs_api(self):
        try:
            input_path = Path(self.input_file.get()).resolve()
            out_dir    = Path(self.output_dir.get()).resolve()

            fmt       = self.format_var.get()
            model_name = self.model_var.get()
            is_24bit  = self.bit_var.get() == "24-bit"
            shift_val = int(self.shifts_var.get().split(" ")[0])
            is_2stems = "2 tracce" in self.stems_var.get()

            # 1. CARICAMENTO AUDIO SICURO CON SOUNDFILE (Bypassa Torchaudio/TorchCodec)
            self.after(0, lambda: self.status_label.configure(text="Caricamento file audio...", text_color="orange"))
            data, sample_rate = sf.read(str(input_path), dtype='float32', always_2d=True)
            
            # Demucs si aspetta la forma (canali, campioni)
            audio_tensor = torch.from_numpy(data).t()

            # 2. INIZIALIZZAZIONE SEPARATOR API DI DEMUCS
            self.after(0, lambda: self.status_label.configure(text="Inizializzazione Modello AI Demucs...", text_color="orange"))
            device = "cuda" if self.has_cuda else "cpu"
            
            separator = demucs.api.Separator(
                model=model_name,
                device=device,
                shifts=shift_val,
                overlap=0.25
            )

            # 3. ESECUZIONE DELLA SEPARAZIONE IN MEMORIA
            self.after(0, lambda: self.status_label.configure(text="AI in azione: Elaborazione audio...", text_color="green"))
            origin, separated = separator.separate_tensor(audio_tensor, sample_rate)

            # 4. SALVATAGGIO DEI FILE SUL DISCO
            self.after(0, lambda: self.status_label.configure(text="Salvataggio traccie divise sul disco...", text_color="orange"))
            
            # Impostazioni di esportazione
            kwargs = {
                # Demucs resamples the input to the model sample rate before returning stems.
                # The separated tensors must therefore be saved at separator.samplerate.
                "samplerate": separator.samplerate,
                "bitrate": 320 if fmt == "mp3" else None,
                "preset": 2 if fmt == "mp3" else None,
                "clip": "rescale",
                "as_float": False if is_24bit or fmt == "mp3" else True,
                "bits_per_sample": 24 if is_24bit and fmt in ["wav", "flac"] else 16
            }

            final_folder = out_dir / model_name / input_path.stem
            final_folder.mkdir(parents=True, exist_ok=True)

            if is_2stems:
                # Modalità 2 tracce: Vocals e No Vocals (Accomunando gli altri stem)
                vocals_tensor = separated["vocals"]
                
                # Misceliamo gli altri stem per ricreare la base musicale strumentale
                no_vocals_stems = [tensor for name, tensor in separated.items() if name != "vocals"]
                no_vocals_tensor = sum(no_vocals_stems)

                # Salvataggio Vocals
                demucs.api.save_audio(vocals_tensor, final_folder / f"vocals.{fmt}", **kwargs)
                # Salvataggio Base
                demucs.api.save_audio(no_vocals_tensor, final_folder / f"no_vocals.{fmt}", **kwargs)
            else:
                # Modalità 4 tracce nativa (Drums, Bass, Other, Vocals)
                for stem_name, stem_tensor in separated.items():
                    demucs.api.save_audio(stem_tensor, final_folder / f"{stem_name}.{fmt}", **kwargs)

            # Verifica finale della cartella
            has_files = final_folder.exists() and any(final_folder.iterdir())

            if has_files:
                self.after(0, lambda: self.status_label.configure(text="Completato con successo! ✔", text_color="green"))
                if os.name == "nt":
                    os.startfile(final_folder)
            else:
                raise Exception("I file non sono stati scritti correttamente nella cartella finale.")

        except Exception as e:
            self.after(0, lambda err=e: self.status_label.configure(text=f"Errore: {str(err)}", text_color="red"))
            self.after(0, lambda err=e: messagebox.showerror("Errore elaborazione AI", str(err)))
        finally:
            self.after(0, self.update_ui_state, False)


if __name__ == "__main__":
    app = DemucsApp()
    app.mainloop()