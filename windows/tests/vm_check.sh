#!/bin/bash
# Check aht on a real Windows machine from a Mac or Linux box, over ssh:
# copy this checkout there, build aht.exe and aht-tray.exe, run the smoke
# scripts natively (and winbadge_test.py and aht_main_test.py from source),
# then drive the desktop (vm_desktop.ps1: the tray, its menu, aht's window,
# setup, the folder picker (a folder chosen, Cancel, a path pasted into its
# Folder: field), Continue, notices, Show in Explorer, start at login, the
# watcher alone, Windows Security) and bring back a report with screenshots.
#
#   windows/tests/vm_check.sh USER@HOST [-i KEY] [--out DIR] [--no-build] [--installer]
#
# --installer also builds aht's installer there (Inno Setup 6, installed for
# that user if missing) and runs it for real in the logged-in session:
# installs aht, checks it, upgrades over it, removes it (installer_smoke.ps1).
# An aht that was installed there before is gone afterwards.
#
# The Windows machine needs OpenSSH Server with key login, Python 3.12
# (python.org or winget) and Git for Windows (its bash runs the smoke
# scripts), and USER logged in at the desktop, unlocked, and left alone
# while it runs.  It works in ~\aht-check (a copy without .git and the
# DEVNOTES files) with a throwaway aht home.  That folder stays there after
# the run, since --no-build runs the exes built in it; remove it when done:
#   ssh USER@HOST "rmdir /s /q aht-check"
# The machine's own tray and watcher, if they run, stop for the desktop check
# (there is one of each per sign-in) and start again after it; the HKCU Run
# entry is put back as it was.
set -u
HOST="${1:?usage: vm_check.sh USER@HOST [-i KEY] [--out DIR] [--no-build] [--installer]}"; shift
KEY=""; OUT="${TMPDIR:-/tmp}/aht-vm-check"; BUILD=1; INSTALLER=0
while [ $# -gt 0 ]; do
  case "$1" in
    -i) KEY="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    --no-build) BUILD=0; shift ;;
    --installer) INSTALLER=1; shift ;;
    *) echo "unknown option $1"; exit 2 ;;
  esac
done
SSHO=(-o BatchMode=yes -o ConnectTimeout=10)
[ -n "$KEY" ] && SSHO+=(-i "$KEY" -o IdentitiesOnly=yes)
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
# LC_ALL=C: what comes back may be in the machine's code page, not UTF-8
on() { ssh "${SSHO[@]}" "$HOST" "$@" | LC_ALL=C tr -d '\r'; }
# PowerShell code goes base64-encoded (UTF-16LE), so no quoting can break it
pwsh() { on "powershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand $(printf '%s' "\$ProgressPreference = 'SilentlyContinue'; $1" | iconv -f utf-8 -t utf-16le | base64 | tr -d '\n')"; }
rm -rf "$OUT"; mkdir -p "$OUT"
echo "== $HOST"

# the tools on that machine
PY=$(pwsh '@(Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe", "$env:ProgramFiles\Python3*\python.exe" -ErrorAction SilentlyContinue | Sort-Object FullName -Descending)[0].FullName')
BASH=$(pwsh '@("C:\Program Files\Git\bin\bash.exe", "$env:LOCALAPPDATA\Programs\Git\bin\bash.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1')
[ -n "$PY" ] || { echo "no Python 3 there (winget install Python.Python.3.12)"; exit 1; }
[ -n "$BASH" ] || { echo "no Git Bash there (winget install Git.Git)"; exit 1; }
echo "   python: $PY"; echo "   bash:   $BASH"

if [ "$BUILD" = 1 ]; then
  echo "== copy this checkout to ~\\aht-check and build"
  # an exe that runs cannot be replaced: this checkout's own, never the machine's aht
  pwsh 'Get-CimInstance Win32_Process | Where-Object { $_.Name -in "aht.exe", "aht-tray.exe" -and $_.ExecutablePath -like "$env:USERPROFILE\aht-check\*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }' >/dev/null
  (cd "$REPO" && COPYFILE_DISABLE=1 tar -czf - --exclude=.git --exclude='*/build' \
     --exclude='windows/dist' --exclude='__pycache__' --exclude='DEVNOTES*' \
     --exclude=$'Icon\r' --exclude='*.exe' --exclude='.DS_Store' .) |
    on "rmdir /s /q aht-check 2>nul & mkdir aht-check & tar -xzf - -C aht-check" || exit 1
  on "cd aht-check && \"$PY\" -m pip install --disable-pip-version-check -q \"pyinstaller==6.*\" && \"$PY\" windows\\src\\make_icons.py windows\\app.ico >nul && cd windows && \"$PY\" -m PyInstaller --clean -y --distpath dist --workpath build aht.spec > build.log 2>&1 && echo built || type build.log" | tail -3
else                                    # the exes as they are; the checks as they are now
  (cd "$REPO" && COPYFILE_DISABLE=1 tar -czf - windows/tests) | on "tar -xzf - -C aht-check" || exit 1
fi

echo "== the smoke scripts, natively"
SMOKE=$(on "\"$BASH\" -l aht-check/windows/tests/vm_smoke.sh")
# and from source, in this ssh session with no desktop: the badges, and
# where aht.exe's entry point sends each command
for t in winbadge_test aht_main_test; do
  SMOKE="$SMOKE
$(on "cd aht-check && \"$PY\" windows\\tests\\$t.py > $t.log 2>&1 && echo $t 0 || echo $t 1")"
done
echo "$SMOKE" | LC_ALL=C sed 's/^/   /'

echo "== the desktop (leave the machine alone for about four minutes)"
# the tasks' PowerShell runs in a console that never shows: Windows Terminal,
# the console of Windows 11, ignores -WindowStyle Hidden and would put an
# empty window in front of what the check looks at
HIDDEN="conhost.exe --headless powershell -NoProfile -ExecutionPolicy Bypass"
on "schtasks /create /tn aht-check /tr \"$HIDDEN -File %USERPROFILE%\\aht-check\\windows\\tests\\vm_desktop.ps1\" /sc once /st 00:00 /it /f >nul 2>&1 & rmdir /s /q aht-check\\out 2>nul & schtasks /run /tn aht-check >nul"
# (a read while the check writes the file fails; the next second's tries again)
pwsh '$f = "$env:USERPROFILE\aht-check\out\results.jsonl"; for ($i = 0; $i -lt 540; $i++) { if ((Test-Path $f) -and (Select-String -Quiet -SimpleMatch "`"check`": `"done`"" $f -ErrorAction SilentlyContinue)) { break }; Start-Sleep 1 }' >/dev/null
on "schtasks /delete /tn aht-check /f >nul 2>&1"
scp -q "${SSHO[@]}" "$HOST:aht-check/out/*" "$OUT/" 2>/dev/null
for t in wine_smoke wine_watch_smoke features_smoke winbadge_test aht_main_test; do scp -q "${SSHO[@]}" "$HOST:aht-check/$t.log" "$OUT/" 2>/dev/null; done

if [ "$INSTALLER" = 1 ]; then
  echo "== the installer, installed and removed for real"
  V=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' "$REPO/aht.py")
  # the CPU the exes are for: that of the Python that built them
  case "$(pwsh "& \"$PY\" -c 'import sysconfig; print(sysconfig.get_platform())'")" in
    *arm64*) A=arm64 ;;
    *) A=x64 ;;
  esac
  pwsh "Set-Location \$env:USERPROFILE\\aht-check\\windows; \$i = .\\iscc.ps1; & \$i /Q /DAppVersion=$V /DArch=$A aht.iss; if (\$LASTEXITCODE) { 'the installer did not build' }"
  on "schtasks /create /tn aht-check-installer /tr \"$HIDDEN -File %USERPROFILE%\\aht-check\\windows\\tests\\installer_smoke.ps1 -Out %USERPROFILE%\\aht-check\\out\\installer.txt\" /sc once /st 00:00 /it /f >nul 2>&1 & schtasks /run /tn aht-check-installer >nul"
  pwsh '$f = "$env:USERPROFILE\aht-check\out\installer.txt"; for ($i = 0; $i -lt 600; $i++) { if ((Test-Path $f) -and (Select-String -Quiet "INSTALLER SMOKE" $f -ErrorAction SilentlyContinue)) { break }; Start-Sleep 1 }' >/dev/null
  on "schtasks /delete /tn aht-check-installer /f >nul 2>&1"
  scp -q "${SSHO[@]}" "$HOST:aht-check/out/installer.txt" "$OUT/" 2>/dev/null
  grep -E "^  (ok|FAIL)|INSTALLER SMOKE" "$OUT/installer.txt" 2>/dev/null | LC_ALL=C tr -d '\r' |
    LC_ALL=C sed 's/^/   /'
  python3 - "$OUT" <<'PY'
import json, re, sys
out = sys.argv[1]
try:
    text = open(f"{out}/installer.txt", encoding="utf-8", errors="replace").read()
except OSError:
    text = ""
ok = "INSTALLER SMOKE OK" in text
fails = re.findall(r"FAIL  (.*?)  \(", text)
with open(f"{out}/results.jsonl", "a") as fh:
    fh.write(json.dumps({"check": "the installer: installs, works, removes itself", "ok": ok,
                         "detail": "; ".join(fails) or ("all its checks" if ok else "no result")}) + "\n")
PY
fi

# the report
SMOKE="$SMOKE" python3 "$REPO/tests/vm_report.py" "$OUT" "aht on Windows: $HOST"
