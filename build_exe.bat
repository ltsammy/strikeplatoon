@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo  104 Launcher - EXE erstellen (PyInstaller)
echo ============================================

python -m pip install --upgrade pip
python -m pip install -r launcher\requirements.txt pyinstaller

python -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --noupx ^
  --name "launcher" ^
  --distpath "dist" ^
  --workpath "build\pyinstaller" ^
  --specpath "." ^
  --add-data "launcher\logo.png;." ^
  --add-data "launcher\logo.ico;." ^
  --add-data "launcher\background.jpg;." ^
  --icon "launcher\logo.ico" ^
  "launcher\launcher_qt.py"

echo.
if exist "dist\launcher.exe" (
  echo [OK] EXE erstellt: dist\launcher.exe
) else (
    echo [FEHLER] Build fehlgeschlagen.
)
pause
