# Release Windows

Le release si generano dal branch `main` creando e pubblicando un tag Git nel formato `vX.Y.Z` (ad esempio `v1.0.0`).

Il workflow `.github/workflows/release-windows.yml` costruisce una distribuzione PyInstaller **onedir**, crea uno ZIP portabile e un installer Inno Setup, quindi pubblica entrambi nella GitHub Release.

## Creare una release
Apri **Releases → Draft a new release**, crea un tag `v1.0.0` scegliendo come target `main`, quindi pubblica. Il workflow si attiva sul tag e carica i due pacchetti.

In alternativa, **Actions → Build Windows release → Run workflow** permette di inserire una versione e pubblicare la release dal commit selezionato.

## Pacchetti
- **Setup**: installa in `%LOCALAPPDATA%\Programs\ChansonVivante`, senza privilegi amministrativi. Crea il collegamento nel menu Start; quello sul Desktop è opzionale.
- **Portable ZIP**: estrarre la cartella `ChansonVivante` e avviare `app_demucs.exe`. Non spostare l'EXE fuori dalla cartella.

I pesi Demucs non sono inclusi e vengono scaricati al primo utilizzo. La disponibilità di CUDA dipende dalla build PyTorch, dal driver NVIDIA e dall'hardware.

La pipeline è per Windows x64. La build parte quando viene pubblicato un tag, non a ogni push sul branch.
