@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo  104 Launcher - EXE erstellen (PyInstaller)
echo ============================================

python -m pip install pyinstaller >nul 2>&1

python -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --name "launcher" ^
  --distpath "dist" ^
  --workpath "build\pyinstaller" ^
  --specpath "." ^
  --add-data "background.mp4;." ^
  --add-data "launcher\logo.png;." ^
  --add-data "launcher\logo.ico;." ^
  --icon "launcher\logo.ico" ^
  "launcher\launcher.py"

echo.
if exist "dist\launcher.exe" (
    echo [OK] EXE erstellt: dist\launcher.exe
) else (
    echo [FEHLER] Build fehlgeschlagen.
)
pause
