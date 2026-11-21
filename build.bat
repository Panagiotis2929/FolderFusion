@echo off
setlocal
cd /d "%~dp0"

echo [1/3] Installing dependencies...
python -m pip install -r requirements.txt pyinstaller || goto :error

echo [2/3] Generating icon...
python branding.py || goto :error

echo [3/3] Building FolderFusion.exe...
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name FolderFusion ^
  --icon assets\icon.ico ^
  --add-data "assets;assets" ^
  --collect-all customtkinter ^
  --collect-all tkinterdnd2 ^
  main.py || goto :error

echo.
echo Done! Your app: dist\FolderFusion.exe
pause
exit /b 0

:error
echo.
echo Build failed. Scroll up to see the error.
pause
exit /b 1
