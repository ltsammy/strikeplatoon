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
  --name "104Launcher" ^
  --distpath "dist" ^
  --workpath "build\pyinstaller" ^
  --specpath "." ^
  --add-data "launcher\logo.png;." ^
  --add-data "launcher\logo.ico;." ^
  --icon "launcher\logo.ico" ^
  "launcher\launcher.py"

echo.
if exist "dist\104Launcher.exe" (
    echo [OK] EXE erstellt: dist\104Launcher.exe
) else (
    echo [FEHLER] Build fehlgeschlagen.
)
pause
