@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo  104 Launcher - Erstinstallation / Update
echo ============================================

:: Python prüfen
python --version >nul 2>&1
if errorlevel 1 (
    echo [FEHLER] Python nicht gefunden!
    echo Bitte Python 3.11+ von https://python.org installieren.
    pause
    exit /b 1
)

:: Abhängigkeiten installieren
echo.
echo [1/2] Installiere Abhängigkeiten...
python -m pip install -r "launcher\requirements.txt"

echo.
echo [2/2] Starte Launcher...
python "launcher\launcher_qt.py"

pause
