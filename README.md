# ChansonVivante

Informazioni sul progetto: [www.davidepozzi.it/ChansonVivante](https://www.davidepozzi.it/ChansonVivante)

🇮🇹 **Italiano** | 🇬🇧 **English**

---

# 🇮🇹 Italiano

**ChansonVivante** è un'applicazione desktop con interfaccia grafica basata sul modello AI open-source [Demucs](https://github.com/facebookresearch/demucs).

Permette di separare una traccia audio nelle sue componenti (**voce, batteria, basso e altri strumenti**) oppure di ottenere due tracce: **voce e base strumentale**.

ChansonVivante rende Demucs accessibile attraverso una semplice interfaccia grafica per Windows, senza bisogno di utilizzare la riga di comando.

## Funzionalità

- **Formati di esportazione:** FLAC, WAV e MP3 a 320 kbps.
- **Profondità audio:** selezione 16-bit o 24-bit. FLAC usa la profondità selezionata; con l'implementazione attuale, WAV selezionato a 16-bit viene scritto come PCM floating-point a 32-bit, mentre WAV 24-bit viene scritto a 24-bit. L'esportazione MP3 usa 320 kbps e non applica la selezione bit-depth.
- **Modelli AI:** `htdemucs` e `htdemucs_ft`.
- **Shifts:** da 0 a 3, per aumentare potenzialmente la qualità della separazione a fronte di un maggiore tempo di elaborazione.
- **Separazione:** due tracce (voce e base) oppure quattro stem (voce, batteria, basso e altro).
- **Accelerazione:** utilizza CUDA quando disponibile; in caso contrario utilizza la CPU.
- **Gestione VRAM:** modalità automatica, manuale con slider da 1 a 12 GB, oppure solo CPU.
- **Gestione automatica degli errori CUDA:** in caso di memoria GPU insufficiente, l'app prova segmenti audio progressivamente più corti e, se necessario, ripiega sulla CPU.
- **Interfaccia:** GUI desktop realizzata con Flet, tema di sistema e indicatore di attività durante l'elaborazione.
- **Avvio ottimizzato:** la schermata iniziale viene mostrata prima del caricamento dell'interfaccia, mentre il motore AI viene inizializzato in background.

> **Importante sulla VRAM:** il budget impostato è un obiettivo indicativo, non un limite rigido. PyTorch, il modello, il driver, Windows e altri programmi possono occupare memoria aggiuntiva. La segmentazione riduce il fabbisogno, ma non garantisce che ogni modello funzioni su qualsiasi GPU. In caso di memoria insufficiente l'app tenta l'elaborazione tramite CPU, che può essere molto più lenta.

> **Nota sull'avanzamento:** l'indicatore di attività è indeterminato. Segnala che l'elaborazione è in corso, ma non mostra una percentuale effettiva né una stima del tempo rimanente.

## Screenshot

<img width="1055" height="1265" alt="image" src="https://github.com/user-attachments/assets/ea6fc0e4-e63e-42c5-a4ab-c5a6f4a65a1d" />

<img width="1050" height="1253" alt="image" src="https://github.com/user-attachments/assets/9d0b92d5-b93c-43a3-8d5c-0eae7962e932" />

## Download

Per Windows sono disponibili:

- **Installer:** installazione guidata tramite Inno Setup.
- **Portable ZIP:** versione portatile che non richiede installazione.

I modelli Demucs non sono inclusi nel pacchetto dell'applicazione e vengono scaricati automaticamente al primo utilizzo.

## Requisiti

- Windows per la distribuzione EXE.
- Per eseguire il sorgente: Python e le dipendenze compatibili con il progetto.
- Le principali dipendenze includono Flet 1.1.2, PyTorch, SoundFile, Demucs, PyYAML e imageio-ffmpeg.
- FFmpeg è utilizzato da Demucs/imageio-ffmpeg per le operazioni audio che ne richiedono l'eseguibile.
- Per l'accelerazione NVIDIA è necessaria una build di PyTorch compatibile con CUDA, oltre a una GPU e driver compatibili.
- La sola presenza di una GPU NVIDIA non garantisce che CUDA sia disponibile.
- Senza CUDA, o selezionando **Solo CPU**, l'elaborazione viene eseguita dal processore.

## Avvio della versione EXE

1. Seleziona la traccia audio con **Sfoglia...**.
2. Scegli la cartella di destinazione con **Sfoglia...**.
3. Seleziona formato, profondità, modello, shifts e modalità di separazione.
4. Scegli **Automatica**, **Manuale** oppure **Solo CPU**.
5. Se utilizzi la modalità manuale, imposta il budget VRAM desiderato.
6. Premi **Avvia separazione**.

I risultati vengono salvati nella sottocartella:

```text
<destinazione>/<nome-traccia>/
```

Su Windows l'applicazione tenta di aprire automaticamente la cartella al termine dell'elaborazione.

## Formati supportati

### Input

Sono disponibili:

- MP3
- WAV
- FLAC
- M4A

La compatibilità con M4A dipende dal supporto disponibile tramite `SoundFile`/`libsndfile` e non è quindi garantita in ogni configurazione.

### Output

Sono disponibili:

- FLAC
- WAV
- MP3 320 kbps

## Modelli

### `htdemucs`

Modello consigliato per la maggior parte degli utilizzi, con un buon compromesso tra qualità e tempo di elaborazione.

### `htdemucs_ft`

Variante che può offrire un miglioramento del risultato in alcuni casi, ma richiede più tempo di elaborazione.

L'interfaccia indica indicativamente un tempo che può arrivare a circa **4×** quello di `htdemucs`, a seconda dell'hardware e del brano.

## Shifts

È possibile scegliere da **0 a 3 shift**.

Aumentare gli shift può migliorare la qualità della separazione in alcuni casi, ma aumenta anche il tempo di elaborazione.

| Shift | Modalità |
|---:|---|
| 0 | Veloce |
| 1 | Standard |
| 2 | Preciso |
| 3 | Lento |

## 💾 Esportazione

### FLAC

È possibile esportare in:

- 16-bit
- 24-bit

FLAC è un formato lossless e permette di mantenere la qualità audio senza la perdita tipica dei formati lossy.

### WAV

È possibile selezionare:

- 16-bit
- 24-bit

**Nota tecnica:** con l'implementazione attuale, l'opzione WAV 16-bit viene scritta come PCM floating-point a 32-bit, mentre l'opzione 24-bit viene scritta come PCM a 24-bit.

### MP3

L'esportazione MP3 utilizza:

**320 kbps**

La selezione della profondità in bit non modifica l'MP3.

## Struttura dei risultati

Con la separazione a 2 stem:

```text
nome-traccia/
├── vocals.wav
└── no_vocals.wav
```

Con la separazione a 4 stem:

```text
nome-traccia/
├── vocals.wav
├── drums.wav
├── bass.wav
└── other.wav
```

L'estensione dei file cambia in base al formato selezionato.

## Versione Portable

Se utilizzi il pacchetto Portable ZIP:

1. estrai completamente l'archivio;
2. avvia l'eseguibile dalla cartella estratta.

Non spostare l'EXE fuori dalla cartella di distribuzione.

La versione Windows è realizzata con PyInstaller in modalità `onedir` e necessita dei file e della cartella `_internal` presenti accanto all'eseguibile.

## Modelli e primo avvio

I pesi dei modelli Demucs **non sono inclusi nell'applicazione**.

Al primo utilizzo del modello scelto, ChansonVivante scarica i file necessari e li memorizza localmente.

Il primo avvio di una determinata configurazione può quindi richiedere più tempo rispetto alle elaborazioni successive.

## Tecnologie

ChansonVivante utilizza principalmente:

- **Python**
- **Flet** - interfaccia grafica desktop
- **PyTorch** - elaborazione tramite modelli neurali
- **Demucs** - separazione audio
- **SoundFile / libsndfile** - lettura e scrittura audio
- **imageio-ffmpeg** - gestione di FFmpeg
- **PyInstaller** - packaging dell'applicazione Windows
- **Inno Setup** - installer Windows

## Struttura del progetto

```text
ChansonVivante/
├── ChansonVivante.py
├── chansonvivante/
│   ├── ui/
│   └── services/
├── packaging/
├── requirements.txt
└── .github/
    └── workflows/
```

`ChansonVivante.py` gestisce l'avvio dell'applicazione e la schermata iniziale, mentre la logica principale è suddivisa tra `ui/` e `services/`.

## Sviluppo

Per lo sviluppo è consigliato utilizzare un ambiente virtuale Python e installare le dipendenze indicate in `requirements.txt`.

Per utilizzare CUDA durante lo sviluppo è necessario installare una versione di PyTorch compatibile con la propria GPU NVIDIA e con la configurazione CUDA disponibile.

Il progetto include una GitHub Actions workflow per la creazione delle release Windows, comprensive di pacchetto Portable ZIP e installer.

## Crediti

ChansonVivante utilizza [Demucs](https://github.com/facebookresearch/demucs), progetto open-source per la separazione di sorgenti audio.

Un ringraziamento agli sviluppatori e ai contributori dei progetti open-source utilizzati da ChansonVivante.

---

# 🇬🇧 English

**ChansonVivante** is a desktop application with a graphical user interface built around the open-source AI model [Demucs](https://github.com/facebookresearch/demucs).

It allows you to separate an audio track into its individual components (**vocals, drums, bass and other instruments**) or produce two tracks: **vocals and instrumental**.

ChansonVivante makes Demucs accessible through a simple Windows graphical interface, without requiring command-line usage.

## Features

- **Export formats:** FLAC, WAV and 320 kbps MP3.
- **Audio bit depth:** 16-bit or 24-bit selection. FLAC uses the selected bit depth; with the current implementation, 16-bit WAV is written as 32-bit floating-point PCM, while 24-bit WAV is written as 24-bit PCM. MP3 export uses 320 kbps and does not apply the bit-depth selection.
- **AI models:** `htdemucs` and `htdemucs_ft`.
- **Shifts:** from 0 to 3, potentially improving separation quality at the cost of longer processing times.
- **Separation:** two tracks (vocals and instrumental) or four stems (vocals, drums, bass and other).
- **Acceleration:** uses CUDA when available; otherwise falls back to CPU processing.
- **VRAM management:** automatic mode, manual mode with a 1–12 GB slider, or CPU-only mode.
- **Automatic CUDA error handling:** if the GPU runs out of memory, the application retries with progressively shorter audio segments and eventually falls back to CPU processing if necessary.
- **Interface:** desktop GUI built with Flet, system theme and an activity indicator during processing.
- **Optimized startup:** the splash screen is displayed before the UI is loaded, while the AI engine is initialized in the background.

> **Important about VRAM:** the configured VRAM budget is a target, not a hard memory limit. PyTorch, the model, drivers, Windows and other applications may use additional GPU memory. Segmentation reduces memory requirements, but does not guarantee that every model will fit on every GPU. If GPU memory remains insufficient, the application attempts CPU processing, which can be significantly slower.

> **Progress note:** the activity indicator is indeterminate. It shows that processing is ongoing, but does not provide an actual percentage or estimated time remaining.
> 
## Screenshot

<img width="1055" height="1265" alt="image" src="https://github.com/user-attachments/assets/ea6fc0e4-e63e-42c5-a4ab-c5a6f4a65a1d" />

<img width="1050" height="1253" alt="image" src="https://github.com/user-attachments/assets/9d0b92d5-b93c-43a3-8d5c-0eae7962e932" />

## Download

Windows releases are available in two formats:

- **Installer:** guided installation using Inno Setup.
- **Portable ZIP:** portable version that does not require installation.

Demucs model weights are not bundled with the application and are downloaded automatically when first needed.

## Requirements

- Windows for the EXE distribution.
- To run from source: Python and the project's compatible dependencies.
- Main dependencies include Flet 1.1.2, PyTorch, SoundFile, Demucs, PyYAML and imageio-ffmpeg.
- FFmpeg is used by Demucs/imageio-ffmpeg for audio operations that require its executable.
- NVIDIA acceleration requires a PyTorch build compatible with CUDA, as well as a compatible GPU and drivers.
- Having an NVIDIA GPU alone does not guarantee that CUDA will be available.
- Without CUDA, or when **CPU-only** mode is selected, processing is performed by the CPU.

## Using the EXE version

1. Select the audio track using **Browse...**.
2. Select the destination folder using **Browse...**.
3. Choose the output format, bit depth, model, shifts and separation mode.
4. Select **Automatic**, **Manual** or **CPU-only** mode.
5. If using manual mode, set the desired VRAM budget.
6. Click **Start separation**.

Results are saved in:

```text
<destination>/<track-name>/
```

On Windows, the application attempts to automatically open the output folder when processing is complete.

## Supported formats

### Input

The file picker supports:

- MP3
- WAV
- FLAC
- M4A

M4A compatibility depends on the support provided by `SoundFile`/`libsndfile` and therefore cannot be guaranteed in every configuration.

### Output

Available output formats are:

- FLAC
- WAV
- MP3 320 kbps

## Models

### `htdemucs`

Recommended for most use cases, providing a good balance between separation quality and processing time.

### `htdemucs_ft`

A variant that can provide improved results in some cases, but requires more processing time.

The interface indicates that it can take approximately **4×** as long as `htdemucs`, depending on the hardware and the audio track.

## Shifts

You can select from **0 to 3 shifts**.

Increasing the number of shifts can improve separation quality in some cases, but also increases processing time.

| Shift | Mode |
|---:|---|
| 0 | Fast |
| 1 | Standard |
| 2 | Precise |
| 3 | Slow |

##  Export

### FLAC

Available bit depths:

- 16-bit
- 24-bit

FLAC is a lossless format and preserves audio quality without the data loss associated with lossy formats.

### WAV

Available bit depths:

- 16-bit
- 24-bit

**Technical note:** with the current implementation, the 16-bit WAV option is written as 32-bit floating-point PCM, while the 24-bit option is written as 24-bit PCM.

### MP3

MP3 export uses:

**320 kbps**

The selected bit depth does not affect MP3 output.

## Output structure

With 2-stem separation:

```text
track-name/
├── vocals.wav
└── no_vocals.wav
```

With 4-stem separation:

```text
track-name/
├── vocals.wav
├── drums.wav
├── bass.wav
└── other.wav
```

The file extension changes according to the selected output format.

## Portable version

If you use the Portable ZIP package:

1. fully extract the archive;
2. run the executable from the extracted folder.

Do not move the EXE outside the distribution folder.

The Windows version is built with PyInstaller in `onedir` mode and requires the accompanying files and `_internal` folder to remain next to the executable.

## Models and first launch

Demucs model weights are **not included with the application**.

When a model is used for the first time, ChansonVivante downloads the required files and stores them locally.

The first run with a particular model may therefore take longer than subsequent processing runs.

## Technologies

ChansonVivante is mainly built with:

- **Python**
- **Flet** - desktop graphical interface
- **PyTorch** - neural model processing
- **Demucs** - audio source separation
- **SoundFile / libsndfile** - audio reading and writing
- **imageio-ffmpeg** - FFmpeg management
- **PyInstaller** - Windows application packaging
- **Inno Setup** - Windows installer

## Project structure

```text
ChansonVivante/
├── ChansonVivante.py
├── chansonvivante/
│   ├── ui/
│   └── services/
├── packaging/
├── requirements.txt
└── .github/
    └── workflows/
```

`ChansonVivante.py` handles application startup and the initial splash screen, while the main application logic is divided between `ui/` and `services/`.

## Development

For development, it is recommended to use a Python virtual environment and install the dependencies listed in `requirements.txt`.

To use CUDA during development, install a PyTorch version compatible with the NVIDIA GPU and the available CUDA configuration.

The project includes a GitHub Actions workflow for building Windows releases, including the Portable ZIP package and installer.

## Credits

ChansonVivante uses [Demucs](https://github.com/facebookresearch/demucs), an open-source project for audio source separation.

Thanks to the developers and contributors of the open-source projects used by ChansonVivante.
