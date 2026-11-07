# Release Windows

Le release si generano dal branch `main` creando e pubblicando un tag Git nel formato `vX.Y.Z` (ad esempio `v1.0.0`).

Il workflow `.github/workflows/release-windows.yml` costruisce una distribuzione PyInstaller **onedir**, crea uno ZIP portabile e un installer Inno Setup, quindi pubblica entrambi nella GitHub Release.

Il runtime Flet, il CLI di packaging e il client desktop Windows sono bloccati alla stessa versione in `requirements.txt`. Flet 1.1.2 include inoltre le correzioni per l'identità della finestra nella barra delle applicazioni e per la cache del client desktop.

## Creare una release
Apri **Releases → Draft a new release**, crea un tag `v1.0.0` scegliendo come target `main`, quindi pubblica. Il workflow si attiva sul tag e carica i due pacchetti.

In alternativa, **Actions → Build Windows release → Run workflow** permette di inserire una versione e pubblicare la release dal commit selezionato.

## Pacchetti
- **Setup**: installa in `%LOCALAPPDATA%\Programs\ChansonVivante`, senza privilegi amministrativi. Crea il collegamento nel menu Start; quello sul Desktop è opzionale.
- **Portable ZIP**: estrarre la cartella `ChansonVivante` e avviare `ChansonVivante.exe`. Non spostare l'EXE fuori dalla cartella: la distribuzione è `onedir` e contiene DLL e runtime necessari.

I pesi Demucs non sono inclusi e vengono scaricati al primo utilizzo. La disponibilità di CUDA dipende dalla build PyTorch, dal driver NVIDIA e dall'hardware.

La pipeline di release è per Windows x64. La build di release parte quando viene pubblicato un tag, non a ogni push sul branch.

La PR esegue inoltre `.github/workflows/windows-packaging-smoke.yml` su un runner Windows: installa le dipendenze, crea il pacchetto `onedir` con gli stessi argomenti PyInstaller della release e verifica EXE, metadati versione Windows e presenza dell'icona. Il pacchetto viene conservato come artifact per 7 giorni. Questo test non pubblica tag o release e non sostituisce la verifica visiva di taskbar e titlebar su un desktop Windows.
