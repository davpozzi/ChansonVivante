import customtkinter as ctk
from tkinter import filedialog, messagebox
import threading
import subprocess
import os
import sys
from pathlib import Path
import shutil
import re
import demucs.separate

# Tema dell'applicazione
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class DemucsApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("ChansonsVivante Audio Separator")
        self.geometry("700x700")
        self.resizable(False, False)
        self.iconbitmap("logo.ico")

        # --- VARIABILI ---
        self.input_file = ctk.StringVar()
        self.output_dir = ctk.StringVar(value=str(Path.home() / "Desktop" / "Output_Audio"))
        self.format_var = ctk.StringVar(value="flac")
        self.bit_var = ctk.StringVar(value="16-bit")
        self.model_var = ctk.StringVar(value="htdemucs")
        self.stems_var = ctk.StringVar(value="Solo Voce e Base (2 tracce)")
        self.shifts_var = ctk.StringVar(value="1 (Standard)")

        self.create_widgets()

    def create_widgets(self):
        # TITOLO
        title = ctk.CTkLabel(self, text="ChansonsVivante - AI Audio Separation", font=ctk.CTkFont(size=20, weight="bold"))
        title.pack(pady=20)

        # SEZIONE 1: FILE E CARTELLE
        frame_files = ctk.CTkFrame(self)
        frame_files.pack(pady=10, padx=20, fill="x")

        # Input
        ctk.CTkLabel(frame_files, text="Traccia Audio:").grid(row=0, column=0, padx=10, pady=10, sticky="w")
        ctk.CTkEntry(frame_files, textvariable=self.input_file, width=350, state="readonly").grid(row=0, column=1, padx=10, pady=10)
        ctk.CTkButton(frame_files, text="Scegli File", command=self.browse_input).grid(row=0, column=2, padx=10, pady=10)

        # Output
        ctk.CTkLabel(frame_files, text="Salva in:").grid(row=1, column=0, padx=10, pady=10, sticky="w")
        ctk.CTkEntry(frame_files, textvariable=self.output_dir, width=350, state="readonly").grid(row=1, column=1, padx=10, pady=10)
        ctk.CTkButton(frame_files, text="Scegli Cartella", command=self.browse_output).grid(row=1, column=2, padx=10, pady=10)

        # SEZIONE 2: IMPOSTAZIONI
        frame_settings = ctk.CTkFrame(self)
        frame_settings.pack(pady=10, padx=20, fill="x")

        # Formato e Bitrate
        ctk.CTkLabel(frame_settings, text="Formato:").grid(row=0, column=0, padx=10, pady=10, sticky="w")
        ctk.CTkOptionMenu(frame_settings, variable=self.format_var, values=["flac", "wav", "mp3"]).grid(row=0, column=1, padx=10, pady=10, sticky="w")

        ctk.CTkLabel(frame_settings, text="Qualità:").grid(row=0, column=2, padx=10, pady=10, sticky="w")
        ctk.CTkOptionMenu(frame_settings, variable=self.bit_var, values=["16-bit", "24-bit"]).grid(row=0, column=3, padx=10, pady=10, sticky="w")

        # Modello e Shifts
        ctk.CTkLabel(frame_settings, text="Modello AI:").grid(row=1, column=0, padx=10, pady=10, sticky="w")
        ctk.CTkOptionMenu(frame_settings, variable=self.model_var, values=["htdemucs", "htdemucs_ft"]).grid(row=1, column=1, padx=10, pady=10, sticky="w")

        ctk.CTkLabel(frame_settings, text="Shifts:").grid(row=1, column=2, padx=10, pady=10, sticky="w")
        ctk.CTkOptionMenu(frame_settings, variable=self.shifts_var, values=["0 (Veloce)", "1 (Standard)", "2 (Preciso)", "3 (Lento)"]).grid(row=1, column=3, padx=10, pady=10, sticky="w")

        # Cosa Separare
        ctk.CTkLabel(frame_settings, text="Separazione:").grid(row=2, column=0, padx=10, pady=10, sticky="w")
        ctk.CTkOptionMenu(frame_settings, variable=self.stems_var, values=["Solo Voce e Base (2 tracce)", "Tutti gli strumenti (4 tracce)"], width=200).grid(row=2, column=1, columnspan=3, padx=10, pady=10, sticky="w")

        # SEZIONE 3: STATO E AVANZAMENTO
        self.status_label = ctk.CTkLabel(self, text="Pronto.", text_color="gray")
        self.status_label.pack(pady=(20, 5))

        self.progress_bar = ctk.CTkProgressBar(self, width=600)
        self.progress_bar.pack(pady=10)
        self.progress_bar.set(0)

        self.eta_label = ctk.CTkLabel(self, text="Tempo rimanente: --:--")
        self.eta_label.pack(pady=5)

        # PULSANTE START
        self.btn_start = ctk.CTkButton(self, text="Avvia Separazione", font=ctk.CTkFont(weight="bold"), height=40, command=self.start_thread)
        self.btn_start.pack(pady=20)

    # --- FUNZIONI UTILI ---
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
        self.btn_start.configure(state=state, text="Elaborazione in corso..." if is_running else "Avvia Separazione")
        
    def start_thread(self):
        if not self.input_file.get():
            messagebox.showerror("Errore", "Seleziona prima una traccia audio.")
            return
        
        self.update_ui_state(True)
        self.progress_bar.set(0)
        self.status_label.configure(text="Avvio motore AI...", text_color="orange")
        self.eta_label.configure(text="Calcolo in corso (potrebbe scaricare il modello...)")
        
        threading.Thread(target=self.run_demucs_process, daemon=True).start()

    def run_demucs_process(self):
        input_path = Path(self.input_file.get())
        out_dir = Path(self.output_dir.get())
        
        fmt = self.format_var.get()
        model = self.model_var.get()
        is_24bit = self.bit_var.get() == "24-bit"
        shift_val = self.shifts_var.get().split(" ")[0]
        is_2stems = "2 tracce" in self.stems_var.get()

        env = os.environ.copy()
        env["TORCHAUDIO_USE_TORCHCODEC"] = "0"

        # --- FIX: Costruzione intelligente del comando ---
        # Se siamo in versione Eseguibile (.exe)
        if getattr(sys, 'frozen', False):
            cmd = [sys.executable, "--run-demucs", "-n", model, "--out", str(out_dir), "--shifts", shift_val]
        else:
            # Se stiamo sviluppando normalmente in Python
            cmd = [sys.executable, os.path.abspath(__file__), "--run-demucs", "-n", model, "--out", str(out_dir), "--shifts", shift_val]
        
        if is_2stems:
            cmd.append("--two-stems=vocals")
            
        if fmt == "flac":
            cmd.append("--flac")
        elif fmt == "mp3":
            cmd.extend(["--mp3", "--mp3-bitrate", "320"])
            
        if is_24bit and fmt in ["wav", "flac"]:
            cmd.append("--int24")

        cmd.append(str(input_path))

        # Nasconde la finestra nera del terminale (su Windows)
        cflags = 0
        if os.name == "nt":
            cflags = subprocess.CREATE_NO_WINDOW

        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, universal_newlines=True, env=env, creationflags=cflags)

            total_passes = 1
            current_pass = 0
            last_pct = 0

            for line in process.stdout:
                match_models = re.search(r"bag of (\d+) models", line)
                if match_models:
                    total_passes = int(match_models.group(1))

                match_pct = re.search(r"(\d{1,3})%\|", line)
                match_eta = re.search(r"<(\d{2}:\d{2})", line)

                if match_pct:
                    pct = int(match_pct.group(1))
                    if pct < last_pct and last_pct > 80:
                        current_pass += 1
                        
                    last_pct = pct
                    overall_progress = (current_pass + (pct / 100.0)) / total_passes
                    overall_progress = min(overall_progress, 1.0)

                    self.after(0, self.progress_bar.set, overall_progress)
                    self.after(0, self.status_label.configure, text=f"Elaborazione: Fase {current_pass + 1} di {total_passes} ({int(overall_progress*100)}%)", text_color="orange")
                
                if match_eta:
                    eta = match_eta.group(1)
                    self.after(0, self.eta_label.configure, text=f"Tempo rimanente (fase attuale): {eta}")

            process.wait()

            if process.returncode == 0:
                self.after(0, self.status_label.configure, text="Completato con successo! ✔", text_color="green")
                self.after(0, self.eta_label.configure, text="Estrazione terminata.")
                self.after(0, self.progress_bar.set, 1.0)
                
                final_folder = out_dir / model / input_path.stem
                if os.name == 'nt':
                    os.startfile(final_folder)
            else:
                self.after(0, self.status_label.configure, text="Errore durante l'elaborazione.", text_color="red")
                
        except Exception as e:
            self.after(0, self.status_label.configure, text=f"Errore critico: {str(e)}", text_color="red")
            
        finally:
            self.after(0, self.update_ui_state, False)


if __name__ == "__main__":
    # --- IL TRUCCO MAGICO PER PYINSTALLER ---
    # Se il comando contiene "--run-demucs", l'exe si trasforma nel motore audio e non apre l'interfaccia.
    if len(sys.argv) > 1 and sys.argv[1] == "--run-demucs":
        # Rimuoviamo "--run-demucs" dalla lista per non confondere il modulo di Demucs
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        
        try:
            demucs.separate.main()
        except Exception as e:
            print(f"Errore Demucs: {e}")
        sys.exit(0)

    # Se non c'è il comando segreto, apri l'interfaccia grafica normalmente
    app = DemucsApp()
    app.mainloop()