@echo off
setlocal

rem Avvia ChansonsVivante usando l'ambiente virtuale locale del progetto.
set "PROJECT_DIR=%~dp0"
set "PYTHONW=%PROJECT_DIR%.venv\Scripts\pythonw.exe"

if not exist "%PYTHONW%" (
    echo Ambiente virtuale non trovato: "%PYTHONW%"
    echo Crea .venv e installa le dipendenze del progetto prima di avviare l'app.
    pause
    exit /b 1
)

start "" "%PYTHONW%" "%PROJECT_DIR%app_demucs.py"
endlocal
