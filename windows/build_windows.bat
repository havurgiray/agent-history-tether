@echo off
REM Build aht.exe natively on a Windows machine.
REM Needs Python 3.11+ from python.org (py launcher) and internet for pip.
cd /d "%~dp0"
py -3 src\make_icons.py app.ico || exit /b 1
py -3 -m pip install --upgrade pyinstaller || exit /b 1
py -3 -m PyInstaller --clean -y --distpath dist --workpath build aht.spec || exit /b 1
copy /y dist\aht.exe aht.exe >nul
copy /y dist\aht-tray.exe aht-tray.exe >nul
echo Built aht.exe + aht-tray.exe
