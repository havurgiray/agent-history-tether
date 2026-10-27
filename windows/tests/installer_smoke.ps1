# aht's installer, for real: install silently, check what it set up, start
# the program, upgrade over it twice (start at login on, then off: each
# stays as it was set), remove it silently, check that it is gone and that
# no agent's history went with it.  Then once more as a first install with
# the tray box unchecked, over a tray entry an earlier `aht install` left,
# and removed again.  After each first install aht knows the box's answer
# (its welcome keeps it).  An aht its installer put here before is removed
# first, silently, so the first install is a first one.  Used by CI, the
# release and vm_check.sh --installer.
#
#   powershell -File installer_smoke.ps1 [-Installer aht-setup-X.Y.Z-windows-x64.exe]
#                                        [-Version X.Y.Z] [-Out log.txt]
#
# Without them: the newest windows\installer\aht-setup-*.exe of this checkout
# and the VERSION in aht.py.  -Out: the output also goes to that file.
#
# It changes this user's real setup (the hook in ~/.claude/settings.json, the
# sign-in entry, PATH) and takes it away again: an aht installed before is
# gone afterwards (its uninstaller leaves ~/.aht and agents' history).  The
# tray-at-sign-in answer aht keeps in ~/.aht is put back as it was.
param([string]$Installer, [string]$Version, [string]$Out)
$Repo = Split-Path (Split-Path $PSScriptRoot)
if (-not $Version) { $Version = (Select-String -Path "$Repo\aht.py" -Pattern '^VERSION = "(.*)"').Matches[0].Groups[1].Value }
if (-not $Installer) {
  $Installer = (Get-ChildItem "$Repo\windows\installer\aht-setup-$Version-windows-*.exe" |
                Sort-Object LastWriteTime | Select-Object -Last 1).FullName
}
if ($Out) { Start-Transcript -Path $Out -Force | Out-Null }

$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"
$App = "$env:LOCALAPPDATA\Programs\aht"
$RunKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$Settings = "$env:USERPROFILE\.claude\settings.json"
$Lnk = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\aht.lnk"
# aht's entry under Settings > Apps, as its installer writes it (AppId in aht.iss)
$Arp = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{B3D9504B-56FA-4E4C-B91B-2DBA1B6A3542}_is1"
$Fails = @()
function Check($ok, $what, $detail) {
  if ($ok) { Write-Output "  ok    $what" } else { Write-Output "  FAIL  $what  ($detail)"; $script:Fails += $what }
}
function UserPath { return [Environment]::GetEnvironmentVariable("Path", "User") -split ";" }
# where aht keeps that the tray-at-sign-in question was answered: gone before
# each first install, so what is there afterwards is the installer's
$Answer = "$(if ($env:AHT_HOME) { $env:AHT_HOME } else { "$env:USERPROFILE\.aht" })\run\autostart.json"
$AnswerBefore = Get-Content -Raw $Answer -ErrorAction SilentlyContinue   # put back at the end
function Answer {  # the tray-at-sign-in answer in aht's status: answered, on
  return ((& "$App\aht.exe" status --json 2>$null) -join "`n" | ConvertFrom-Json -ErrorAction SilentlyContinue).autostart
}
function RunInstaller([string[]]$More) {
  # not Start-Process -Wait: that waits for the tray and the watcher the
  # installer starts too, which run on
  $a = @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-")
  if ($More) { $a += $More }
  $p = Start-Process -PassThru $Installer -ArgumentList $a
  $null = $p.Handle                     # keeps the exit code readable
  $null = $p.WaitForExit(300000)
  return $p.ExitCode
}
function Uninstall([string]$Dir) {
  Start-Process "$Dir\unins000.exe" -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"
  # the uninstaller runs a copy of itself from TEMP and returns at once
  for ($i = 0; $i -lt 90 -and ((Test-Path "$Dir\aht.exe") -or (Test-Path $Arp)); $i++) { Start-Sleep 1 }
  Start-Sleep 2
}

if (Test-Path $Arp) {
  # the installer asks the tray question only when aht is not installed yet
  $was = Get-ItemProperty $Arp
  $dir = Split-Path $was.UninstallString.Trim('"')
  Write-Output "== remove the aht $($was.DisplayVersion) installed here before ($dir), silently"
  Uninstall $dir
  Check (-not (Test-Path $Arp) -and -not (Test-Path "$dir\aht.exe")) "it is gone, so the next install is a first one" $dir
}

Write-Output "== install $Installer"
Remove-Item $Answer -ErrorAction SilentlyContinue
$code = RunInstaller
Check ($code -eq 0) "the installer exits 0" $code
$ver = (& "$App\aht.exe" version 2>&1) -join " "
Check ($ver -like "*$Version*") "aht.exe runs from $App" $ver
Check (Test-Path "$App\_internal") "one folder: _internal next to the exes" ""
Check (Test-Path "$App\aht-tray.exe") "aht-tray.exe" ""
Check (Test-Path $Lnk) "Start menu: aht" $Lnk
$run = (Get-ItemProperty $RunKey -ErrorAction SilentlyContinue)."aht-watcher"
Check ($run -like "*$App\aht-tray.exe*") "starts at sign-in" $run
$hook = Get-Content $Settings -Raw -ErrorAction SilentlyContinue
Check ($hook -like "*$($App.Replace('\', '\\'))\\aht.exe*") "the SessionStart hook points here" ""
Check ((UserPath) -contains $App) "on PATH" ""
$arp = Get-ChildItem HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall -ErrorAction SilentlyContinue |
  Where-Object { (Get-ItemProperty $_.PSPath).DisplayName -eq "aht" }
Check ([bool]$arp) "listed under Settings > Apps" ""
Start-Sleep 3
$tray = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq "$App\aht-tray.exe" })
Check ($tray.Count -ge 1) "the tray runs" ""
$kind = (& "$App\aht.exe" update --json 2>&1 | Out-String | ConvertFrom-Json -ErrorAction SilentlyContinue).how
Check ($kind -eq "installer") "aht knows it came from the installer" $kind
$a = Answer
Check ($a.answered -eq $true -and $a.on -eq $true) "the tray box checked: aht keeps that answer, the tray at sign-in" "answered $($a.answered), on $($a.on)"

Write-Output "== upgrade over it"
foreach ($state in "on", "off") {
  $null = & "$App\aht.exe" autostart $state
  $code = RunInstaller
  $run = (Get-ItemProperty $RunKey -ErrorAction SilentlyContinue)."aht-watcher"
  $want = if ($state -eq "on") { "`"$App\aht-tray.exe`"" } else { "`"$App\aht-tray.exe`" --watch" }
  Check ($code -eq 0 -and $run -eq $want) "an upgrade keeps start at login $state" "exit $code, $run"
}
Start-Sleep 3
$tray = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq "$App\aht-tray.exe" })
Check ($tray.Count -ge 1) "the tray runs after an upgrade" ""

Write-Output "== remove it"
$hist = Test-Path "$env:USERPROFILE\.claude\projects"
Uninstall $App
Check (-not (Test-Path "$App\aht.exe")) "the program is gone" ""
Check (-not (Test-Path $Lnk)) "the Start menu entry is gone" ""
$run = (Get-ItemProperty $RunKey -ErrorAction SilentlyContinue)."aht-watcher"
Check (-not $run) "nothing starts at sign-in" $run
$hook = Get-Content $Settings -Raw -ErrorAction SilentlyContinue
Check (-not ($hook -like "*aht.exe*")) "the hook is gone" ""
Check (-not ((UserPath) -contains $App)) "off PATH" ""
$left = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -like "$App\*" })
Check ($left.Count -eq 0) "no aht process left" ($left.Name -join ", ")
Check ((Test-Path "$env:USERPROFILE\.claude\projects") -eq $hist) "agents' history untouched" ""

Write-Output "== a first install with the tray box unchecked"
# the sign-in entry an earlier `aht install` (the zip) wrote for its tray
$old = "`"$env:LOCALAPPDATA\aht\aht-tray.exe`""
Set-ItemProperty $RunKey "aht-watcher" $old
Remove-Item $Answer -ErrorAction SilentlyContinue
$code = RunInstaller "/MERGETASKS=!startup"
$run = (Get-ItemProperty $RunKey -ErrorAction SilentlyContinue)."aht-watcher"
Check ($code -eq 0 -and $run -eq "`"$App\aht-tray.exe`" --watch") "the box unchecked: only the watcher starts at sign-in" "exit $code, $run"
$a = Answer
Check ($a.answered -eq $true -and $a.on -eq $false) "the box unchecked: aht keeps that answer, no tray at sign-in" "answered $($a.answered), on $($a.on)"
Uninstall $App
$run = (Get-ItemProperty $RunKey -ErrorAction SilentlyContinue)."aht-watcher"
Check (-not (Test-Path "$App\aht.exe") -and -not $run) "removed again, nothing starts at sign-in" $run
if ($run -eq $old) { Remove-ItemProperty $RunKey "aht-watcher" -ErrorAction SilentlyContinue }
if ($AnswerBefore) {
  $null = New-Item -ItemType Directory -Force (Split-Path $Answer)
  [IO.File]::WriteAllText($Answer, $AnswerBefore)
} else { Remove-Item $Answer -ErrorAction SilentlyContinue }

if ($Fails.Count) { Write-Output "INSTALLER SMOKE FAILED: $($Fails -join '; ')" } else { Write-Output "INSTALLER SMOKE OK" }
if ($Out) { Stop-Transcript | Out-Null }
exit [int]($Fails.Count -gt 0)
