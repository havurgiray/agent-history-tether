@echo off
REM Build aht natively on a Windows machine: dist\aht (aht.exe, aht-tray.exe,
REM _internal\) and, when Inno Setup 6 is installed, the installer in installer\.
REM Needs Python 3.11+ from python.org (py launcher) and internet for pip.
cd /d "%~dp0"
py -3 src\make_icons.py app.ico || exit /b 1
py -3 -m pip install --upgrade pyinstaller || exit /b 1
py -3 -m PyInstaller --clean -y --distpath dist --workpath build aht.spec || exit /b 1
echo Built dist\aht\aht.exe + aht-tray.exe
for /f "tokens=2 delims==" %%v in ('findstr /b /c:"VERSION = " ..\aht.py') do set V=%%v
set V=%V: =%
set V=%V:"=%
REM the installer is named after the CPU the exes are for: that of the Python
REM that built them (an x64 Python on an ARM64 PC builds x64 exes)
for /f %%p in ('py -3 -c "import sysconfig; print(sysconfig.get_platform())"') do set PLAT=%%p
set A=x64
if /i "%PLAT%"=="win-arm64" set A=arm64
set ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" set ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" (echo No Inno Setup 6: the installer was not built & exit /b 0)
"%ISCC%" /Q /DAppVersion=%V% /DArch=%A% aht.iss || exit /b 1
echo Built installer\aht-setup-%V%-windows-%A%.exe
