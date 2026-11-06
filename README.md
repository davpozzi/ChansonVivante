# 🎵 ChansonsVivante

Informazioni sul progetto: [www.davidepozzi.it/chansonsvivante](https://www.davidepozzi.it/chansonsvivante)

🇮🇹 **Italiano** | 🇬🇧 **English**

---

## 🇮🇹 Italiano

### Cos'è questo programma?

**ChansonsVivante** è un'applicazione desktop con interfaccia grafica basata sul motore open-source [Demucs](https://github.com/facebookresearch/demucs). Permette di separare una traccia audio nelle sue componenti: voce, batteria, basso e altri strumenti, oppure di ottenere due tracce (voce e base strumentale).

### Funzionalità

- **Formati di esportazione:** FLAC, WAV e MP3 a 320 kbps.
- **Profondità audio:** selezione 16-bit o 24-bit per i formati WAV e FLAC.
- **Modelli AI:** `htdemucs` e `htdemucs_ft`.
- **Shifts:** da 0 a 3 passaggi di elaborazione.
- **Separazione:** due tracce (voce e base) oppure quattro stem (voce, batteria, basso e altro).
- **Interfaccia:** tema scuro e indicatore di attività durante l'elaborazione.

> **Nota sull'avanzamento:** l'indicatore attuale è indeterminato: segnala che l'elaborazione è in corso, ma non mostra una percentuale effettiva né una stima del tempo rimanente.

### Requisiti

- Windows per la distribuzione EXE descritta qui sotto.
- Per eseguire il sorgente: Python e le dipendenze compatibili con il progetto, tra cui CustomTkinter, PyTorch, SoundFile, Demucs e imageio-ffmpeg.
- FFmpeg è utilizzato da Demucs/imageio-ffmpeg per le operazioni audio che ne richiedono l'eseguibile.
- La disponibilità CUDA dipende da GPU, driver e versione di PyTorch installata. In assenza di CUDA, l'applicazione utilizza la CPU.

**Compatibilità dei file:** la finestra di selezione propone MP3, WAV, FLAC e M4A. La lettura è effettuata tramite SoundFile/libsndfile: i formati effettivamente leggibili dipendono dalla versione e dalle capacità della libreria installata. In particolare, il supporto M4A non è garantito.

### Avvio della versione EXE

1. Estrai tutto il contenuto dello ZIP in una cartella sul computer.
2. Avvia `app_demucs.exe` da quella cartella.
3. Non spostare l'EXE fuori dalla cartella estratta: la distribuzione PyInstaller dipende dai file e dalla cartella `_internal` presenti accanto all'eseguibile. Per un collegamento sul Desktop, crea un collegamento all'EXE senza spostarlo.
4. Seleziona la traccia audio con **Scegli File**.
5. Scegli la cartella di destinazione con **Scegli Cartella**. Per impostazione predefinita viene usata `Downloads/Output_Audio`.
6. Seleziona formato, profondità, modello, shifts e modalità di separazione.
7. Premi **Avvia Separazione**.

I risultati vengono salvati in una sottocartella con struttura `<destinazione>/<modello>/<nome-traccia>/`. Su Windows l'applicazione tenta di aprire automaticamente la cartella al termine dell'elaborazione.

---

## 🇬🇧 English

### What is this software?

**ChansonsVivante** is a desktop application with a graphical interface powered by the open-source [Demucs](https://github.com/facebookresearch/demucs) engine. It separates an audio track into vocals, drums, bass and other instruments, or creates two outputs (vocals and instrumental accompaniment).

### Features

- **Export formats:** FLAC, WAV and MP3 at 320 kbps.
- **Audio bit depth:** 16-bit or 24-bit selection for WAV and FLAC.
- **AI models:** `htdemucs` and `htdemucs_ft`.
- **Shifts:** 0 to 3 processing shifts.
- **Separation modes:** two stems (vocals and instrumental) or four stems (vocals, drums, bass and other).
- **Interface:** dark theme and an activity indicator while processing.

> **Progress note:** the current indicator is indeterminate. It shows that processing is running, but does not report an actual percentage or an estimated time remaining.

### Requirements

- Windows for the packaged EXE distribution described below.
- To run from source: Python and compatible project dependencies, including CustomTkinter, PyTorch, SoundFile, Demucs and imageio-ffmpeg.
- FFmpeg is used by Demucs/imageio-ffmpeg for audio operations that require its executable.
- CUDA availability depends on the GPU, drivers and installed PyTorch build. The application uses the CPU when CUDA is unavailable.

**Input compatibility:** the file picker offers MP3, WAV, FLAC and M4A. Audio is read through SoundFile/libsndfile, so the formats that can actually be decoded depend on the installed library version and its enabled codecs. M4A support in particular is not guaranteed.

### Launching the EXE version

1. Extract the entire ZIP archive into a folder on your computer.
2. Run `app_demucs.exe` from that folder.
3. Do not move the EXE out of the extracted folder: the PyInstaller distribution relies on the accompanying files and the `_internal` directory. To place it on the Desktop, create a shortcut instead of moving the executable.
4. Select the source audio track with **Choose File**.
5. Select the output folder with **Choose Folder**. The default is `Downloads/Output_Audio`.
6. Choose the format, bit depth, model, shifts and separation mode.
7. Click **Start Separation**.

Output files are saved under `<destination>/<model>/<track-name>/`. On Windows, the application attempts to open the output folder when processing finishes.
