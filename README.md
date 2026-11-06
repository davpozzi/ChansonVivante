# 🎵 ChansonsVivante

Informazioni sul progetto: [www.davidepozzi.it/chansonsvivante](https://www.davidepozzi.it/chansonsvivante)

🇮🇹 **Italiano** | 🇬🇧 **English**

---

## 🇮🇹 Italiano

### Cos'è questo programma?

**ChansonsVivante** è un'applicazione desktop con interfaccia grafica basata sul motore open-source [Demucs](https://github.com/facebookresearch/demucs). Permette di separare una traccia audio nelle sue componenti: voce, batteria, basso e altri strumenti, oppure di ottenere due tracce (voce e base strumentale).

### Funzionalità

- **Formati di esportazione:** FLAC, WAV e MP3 a 320 kbps.
- **Profondità audio:** selezione 16-bit o 24-bit. FLAC usa la profondità selezionata; con l'implementazione attuale, WAV selezionato a 16-bit viene scritto come PCM floating-point a 32-bit, mentre WAV 24-bit viene scritto a 24-bit. L'esportazione MP3 usa 320 kbps e non applica la selezione bit-depth.
- **Modelli AI:** `htdemucs` e `htdemucs_ft`.
- **Shifts:** da 0 a 3 passaggi di elaborazione.
- **Separazione:** due tracce (voce e base) oppure quattro stem (voce, batteria, basso e altro).
- **Accelerazione:** usa CUDA quando disponibile; altrimenti usa la CPU.
- **Gestione VRAM:** modalità automatica, manuale con slider da 1 a 12 GB, oppure solo CPU. La modalità automatica stima il budget a partire dalla memoria GPU libera. Se si verifica un errore CUDA di memoria, l'app prova segmenti audio progressivamente più corti e infine ripiega sulla CPU.
- **Interfaccia:** GUI desktop nativa Flet, tema scuro e indicatore di attività durante l'elaborazione. Lo splash viene mostrato prima dell'importazione della UI; il motore AI viene caricato in background mentre l'interfaccia è già visibile. L'icona della finestra usa `logo.ico`.

> **Importante sulla VRAM:** il budget impostato è un obiettivo indicativo, non un limite rigido. PyTorch, il modello, il driver, Windows e altri programmi possono occupare memoria aggiuntiva. La segmentazione riduce il fabbisogno, ma non garantisce che ogni modello funzioni su qualsiasi GPU; in caso di memoria insufficiente l'app tenta la CPU, che può essere molto più lenta.

> **Nota sull'avanzamento:** l'indicatore è indeterminato: segnala che l'elaborazione è in corso, ma non mostra una percentuale effettiva né una stima del tempo rimanente.

### Requisiti

- Windows per la distribuzione EXE descritta qui sotto.
- Per eseguire il sorgente: Python e le dipendenze compatibili con il progetto, tra cui Flet 0.28.3, PyTorch, SoundFile, Demucs e imageio-ffmpeg.
- FFmpeg è utilizzato da Demucs/imageio-ffmpeg per le operazioni audio che ne richiedono l'eseguibile.
- Per l'accelerazione NVIDIA è necessaria una build di PyTorch compatibile con CUDA, oltre a GPU e driver compatibili. La sola presenza di una GPU NVIDIA non garantisce che CUDA sia disponibile.
- Senza CUDA, o selezionando **Solo CPU**, l'elaborazione viene eseguita dal processore.

**Compatibilità dei file:** la finestra di selezione propone MP3, WAV, FLAC e M4A. La lettura è effettuata tramite SoundFile/libsndfile: i formati effettivamente leggibili dipendono dalla versione e dalle capacità della libreria installata. In particolare, il supporto M4A non è garantito.

### Avvio della versione EXE

1. Estrai tutto il contenuto dello ZIP in una cartella sul computer.
2. Avvia `app_demucs.exe` da quella cartella.
3. Non spostare l'EXE fuori dalla cartella estratta: la distribuzione PyInstaller dipende dai file e dalla cartella `_internal` presenti accanto all'eseguibile. Per un collegamento sul Desktop, crea un collegamento all'EXE senza spostarlo.
4. Seleziona la traccia audio con **Scegli file**.
5. Scegli la cartella di destinazione con **Scegli cartella**. Per impostazione predefinita viene usata `Downloads/Output_Audio`.
6. Seleziona formato, profondità, modello, shifts e modalità di separazione.
7. Scegli **Automatica**, **Manuale** (e il budget VRAM) oppure **Solo CPU**.
8. Premi **Avvia separazione**.

I risultati vengono salvati in una sottocartella con struttura `<destinazione>/<modello>/<nome-traccia>/`. Su Windows l'applicazione tenta di aprire automaticamente la cartella al termine dell'elaborazione.

### Archivio

Il codice applicativo è organizzato nel package `chansonvivante/`: `ui/` contiene la finestra Flet; `services/` separa runtime/configurazione, gestione modelli, pipeline audio/GPU e ponte eventi con la UI. `app_demucs.py` è il punto di ingresso leggero e mostra lo splash prima di importare la UI.

---

## 🇬🇧 English

### What is this software?

**ChansonsVivante** is a desktop application with a graphical interface powered by the open-source [Demucs](https://github.com/facebookresearch/demucs) engine. It separates an audio track into vocals, drums, bass and other instruments, or creates two outputs (vocals and instrumental accompaniment).

### Features

- **Export formats:** FLAC, WAV and MP3 at 320 kbps.
- **Audio bit depth:** 16-bit or 24-bit selection. FLAC uses the selected bit depth; with the current implementation, WAV selected as 16-bit is written as 32-bit floating-point PCM, while WAV 24-bit is written at 24-bit. MP3 export uses 320 kbps and does not use the bit-depth selection.
- **AI models:** `htdemucs` and `htdemucs_ft`.
- **Shifts:** 0 to 3 processing shifts.
- **Separation modes:** two stems (vocals and instrumental) or four stems (vocals, drums, bass and other).
- **Acceleration:** uses CUDA when available; otherwise it uses the CPU.
- **VRAM management:** automatic mode, manual mode with a 1–12 GB slider, or CPU-only mode. Automatic mode estimates a budget from currently free GPU memory. If a CUDA out-of-memory error occurs, the app retries with progressively shorter audio segments and finally falls back to the CPU.
- **Interface:** native Flet desktop GUI, dark theme and activity indicator while processing. The splash is displayed before the UI is imported; the AI engine loads in the background while the interface is already visible. The window icon uses `logo.ico`.

> **VRAM note:** the selected budget is a target, not a hard memory cap. PyTorch, the model, the driver, Windows and other applications may allocate additional memory. Segmentation reduces memory demand but cannot guarantee that every model will run on every GPU. If GPU memory remains insufficient, the app attempts CPU processing, which can be much slower.

> **Progress note:** the indicator is indeterminate. It shows that processing is running, but does not report an actual percentage or an estimated time remaining.

### Requirements

- Windows for the packaged EXE distribution described below.
- To run from source: Python and compatible project dependencies, including Flet 0.28.3, PyTorch, SoundFile, Demucs and imageio-ffmpeg.
- FFmpeg is used by Demucs/imageio-ffmpeg for audio operations that require its executable.
- NVIDIA acceleration requires a PyTorch build compatible with CUDA, as well as a compatible GPU and driver. Having an NVIDIA GPU alone does not guarantee CUDA availability.
- Without CUDA, or when **CPU-only** is selected, processing runs on the CPU.

**Input compatibility:** the file picker offers MP3, WAV, FLAC and M4A. Audio is read through SoundFile/libsndfile, so the formats that can actually be decoded depend on the installed library version and its enabled codecs. M4A support in particular is not guaranteed.

### Launching the EXE version

1. Extract the entire ZIP archive into a folder on your computer.
2. Run `app_demucs.exe` from that folder.
3. Do not move the EXE out of the extracted folder: the PyInstaller distribution relies on the accompanying files and the `_internal` directory. To place it on the Desktop, create a shortcut instead of moving the executable.
4. Select the source audio track with **Choose file**.
5. Select the output folder with **Choose folder**. The default is `Downloads/Output_Audio`.
6. Choose the format, bit depth, model, shifts and separation mode.
7. Select **Automatic**, **Manual** (and the VRAM budget), or **CPU only**.
8. Click **Start separation**.

Output files are saved under `<destination>/<model>/<track-name>/`. On Windows, the application attempts to open the output folder when processing finishes.

### Archive

The application code is organized in the `chansonvivante/` package: `ui/` contains the Flet window and `services/` handles the Demucs engine, models, GPU and logs. `app_demucs.py` is the lightweight entry point and displays the splash before importing the UI.
