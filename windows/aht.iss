; aht's Windows installer (Inno Setup 6).  For this user only, no admin
; prompt: aht goes to %LOCALAPPDATA%\Programs\aht, gets a Start menu entry
; and an entry under Settings > Apps.  Each install or upgrade runs
; `aht install --here` (the hook, the watcher at sign-in, PATH; on an
; upgrade, a tray that starts at sign-in stays so; on a first install, the
; tray box decides); removing aht runs `aht uninstall` first.  No
; agent's history is touched by either.  `aht update --upgrade` runs it with
; /SILENT, and with /OPENWINDOW=1 when aht's window was open: it opens again.
;
;   iscc /DAppVersion=0.14.0 /DArch=x64 [/DSrc=dist\aht] aht.iss
;
; Src is PyInstaller's one-folder build (aht.spec); the installer lands in
; installer\aht-setup-<version>-windows-<arch>.exe.

#ifndef AppVersion
  #error Pass the version: iscc /DAppVersion=X.Y.Z /DArch=x64|arm64 aht.iss
#endif
#ifndef Arch
  #define Arch "x64"
#endif
#ifndef Src
  #define Src "dist\aht"
#endif
#if Arch == "arm64"
  #define Archs "arm64"
#else
  #define Archs "x64compatible"
#endif

[Setup]
AppId={{B3D9504B-56FA-4E4C-B91B-2DBA1B6A3542}
AppName=aht
AppVersion={#AppVersion}
AppVerName=aht {#AppVersion}
AppPublisher=aht (agent-history-tether)
AppPublisherURL=https://github.com/havurgiray/agent-history-tether
AppSupportURL=https://github.com/havurgiray/agent-history-tether/issues
AppUpdatesURL=https://github.com/havurgiray/agent-history-tether/releases
DefaultDirName={autopf}\aht
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed={#Archs}
ArchitecturesInstallIn64BitMode={#Archs}
MinVersion=10.0
OutputDir=installer
OutputBaseFilename=aht-setup-{#AppVersion}-windows-{#Arch}
SetupIconFile=app.ico
UninstallDisplayIcon={app}\aht-tray.exe
UninstallDisplayName=aht
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
ChangesEnvironment=yes
RestartApplications=no
VersionInfoVersion={#AppVersion}
VersionInfoDescription=aht installer
VersionInfoProductName=aht

[Tasks]
; asked on the first install only: later, Settings in aht's window or the
; tray's menu change it, and an upgrade keeps what they set
Name: "startup"; Description: "Show aht's tray icon when I sign in (the folder watcher starts at sign-in either way)"; Check: FirstInstall
Name: "path"; Description: "Add aht to PATH, so ""aht"" works in a terminal"

[InstallDelete]
; the previous version's libraries
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#Src}\*"; Excludes: "LICENSE,README.md"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\aht"; Filename: "{app}\aht-tray.exe"; Parameters: "--window"; Comment: "aht: your agents' projects, sessions and history"

[Run]
Filename: "{app}\aht.exe"; Parameters: "install --here{code:PathFlag}"; StatusMsg: "Setting up aht..."; Flags: runhidden waituntilterminated
; the box decides on a first install, also over a tray entry an earlier
; `aht install` left, which `install --here` keeps; either line also notes
; that the question was answered, so aht's welcome keeps the answer
Filename: "{app}\aht.exe"; Parameters: "autostart on"; Flags: runhidden waituntilterminated; Tasks: startup; Check: FirstInstall
Filename: "{app}\aht.exe"; Parameters: "autostart off"; Flags: runhidden waituntilterminated; Tasks: not startup; Check: FirstInstall
Filename: "{app}\aht-tray.exe"; Flags: nowait; Check: not OpenWindowAgain
Filename: "{app}\aht-tray.exe"; Parameters: "--window"; Flags: nowait; Check: OpenWindowAgain
Filename: "{app}\aht-tray.exe"; Parameters: "--window"; Description: "Open aht"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{app}\aht.exe"; Parameters: "uninstall"; Flags: runhidden waituntilterminated; RunOnceId: "AhtUninstall"

[Code]
var
  WasInstalled: Boolean;

function InitializeSetup: Boolean;
begin
  WasInstalled := RegKeyExists(HKCU,
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\{B3D9504B-56FA-4E4C-B91B-2DBA1B6A3542}_is1');
  Result := True;
end;

function FirstInstall: Boolean;
begin
  Result := not WasInstalled;
end;

{ `aht update --upgrade` passes /OPENWINDOW=1 when aht's window was open:
  the upgrade closes it, and it opens again here }
function OpenWindowAgain: Boolean;
begin
  Result := WizardSilent and (ExpandConstant('{param:OPENWINDOW|0}') = '1');
end;

function PathFlag(Param: String): String;
begin
  if WizardIsTaskSelected('path') then
    Result := ''
  else
    Result := ' --no-path';
end;

{ an aht that runs keeps its files open (the tray, the watcher, aht's window):
  those started from this folder stop before the files are replaced }
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  App: String;
  Code: Integer;
begin
  App := ExpandConstant('{app}');
  StringChangeEx(App, '''', '''''', True);
  Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -NonInteractive -Command "Get-CimInstance Win32_Process | ' +
    'Where-Object { ($_.Name -eq ''aht.exe'' -or $_.Name -eq ''aht-tray.exe'') -and ' +
    '$_.ExecutablePath -and $_.ExecutablePath.StartsWith(''' + App + '\'', ' +
    '[StringComparison]::OrdinalIgnoreCase) } | ' +
    'ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"',
    '', SW_HIDE, ewWaitUntilTerminated, Code);
  Result := '';
end;
