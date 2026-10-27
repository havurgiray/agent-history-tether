#!/bin/bash
# Check aht on a real Linux machine over ssh: copy this checkout there, run
# the test suites natively, then the desktop on an invisible screen
# (vm_desktop.sh: the tray, its menu, aht's window server, setup, the folder
# picker, Continue's terminal, notices, Show in Files, start at login, and
# that nothing crashed), and bring back a report with screenshots.
#
#   linux/tests/vm_check.sh HOST [--out DIR] [--no-suites] [--keep]
#
# The machine needs: python3, rsync (the handover tests), and for the
# desktop xvfb openbox stalonetray dunst xdotool imagemagick zenity
# python3-gi gir1.2-ayatanaappindicator3-0.1 gir1.2-atspi-2.0 x11-utils curl
# libnotify-bin dbus and a terminal (xterm will do).  It works in a folder of
# its own in /tmp there (mktemp -d /tmp/aht-sbx-check.XXXXXX), outside the
# home folder, so the desktop's file indexer never sees it: a copy without
# .git and the DEVNOTES files.  It removes that folder at the end, also when
# the run stops early (--keep leaves it there for a look and says where).
# The desktop part has an invisible screen of its own, a throwaway home (HOME,
# its XDG folders and aht's) and a stand-in systemctl, so the desktop someone
# is logged in to, their home and the machine's own ~/.aht are not touched.
set -u
HOST="${1:?usage: vm_check.sh HOST [--out DIR] [--no-suites] [--keep]}"; shift
OUT="${TMPDIR:-/tmp}/aht-linux-check"; SUITES=1; KEEP=0
while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT="$2"; shift 2 ;;
    --no-suites) SUITES=0; shift ;;
    --keep) KEEP=1; shift ;;
    *) echo "unknown option $1"; exit 2 ;;
  esac
done
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
on() { ssh -o BatchMode=yes -o ConnectTimeout=10 "$HOST" "$@"; }
rm -rf "$OUT"; mkdir -p "$OUT"
echo "== $HOST: $(on '. /etc/os-release; echo $PRETTY_NAME, python $(python3 -V 2>&1 | cut -d" " -f2)')"
MISSING=$(on 'for c in Xvfb openbox stalonetray dunst xdotool import zenity xwininfo curl notify-send dbus-run-session; do command -v $c >/dev/null || echo -n "$c "; done; { command -v x-terminal-emulator || command -v gnome-terminal || command -v konsole || command -v xterm; } >/dev/null || echo -n "a terminal (xterm) "; python3 -c "import gi; gi.require_version(\"AyatanaAppIndicator3\", \"0.1\")" 2>/dev/null || echo -n "gir1.2-ayatanaappindicator3-0.1 "; python3 -c "import gi; gi.require_version(\"Atspi\", \"2.0\")" 2>/dev/null || echo -n "gir1.2-atspi-2.0"')
[ -n "$MISSING" ] && echo "   missing for the desktop: $MISSING"

echo "== copy this checkout to a new folder in /tmp there"
D=$(on 'mktemp -d /tmp/aht-sbx-check.XXXXXX')
[[ "$D" =~ ^/tmp/aht-sbx-check\.[A-Za-z0-9]{6}$ ]] || { echo "   no folder made in /tmp there ($D)"; exit 1; }
# the copy goes again however the run ends
if [ "$KEEP" = 1 ]; then echo "   it stays there: $D"; else trap "on 'rm -rf $D'" EXIT; fi
(cd "$REPO" && COPYFILE_DISABLE=1 tar -czf - --exclude=.git --exclude='*/build' \
   --exclude='windows/dist' --exclude='__pycache__' --exclude='DEVNOTES*' \
   --exclude=$'Icon\r' --exclude='*.exe' --exclude='.DS_Store' .) |
  on "tar -xzf - -C $D 2>/dev/null" || exit 1

SMOKE=""
if [ "$SUITES" = 1 ]; then
  echo "== the test suites, natively"
  SMOKE=$(on 'cd '"$D"' && bash tests/run_tests.sh > out-suites.log 2>&1; s=$?; echo "run_tests $s $(grep -E "RESULT|ALL AHT" out-suites.log | tr "\n" " ")"')
  echo "   $SMOKE"
fi

if [ -z "$MISSING" ]; then
  echo "== the desktop, on an invisible screen"
  on "bash $D/linux/tests/vm_desktop.sh" >/dev/null 2>&1
  scp -q "$HOST:$D/out/*" "$OUT/" 2>/dev/null
else
  echo '{"check": "the desktop", "ok": false, "detail": "missing there: '"$MISSING"'"}' > "$OUT/results.jsonl"
fi
scp -q "$HOST:$D/out-suites.log" "$OUT/" 2>/dev/null

SMOKE="$SMOKE" python3 "$REPO/tests/vm_report.py" "$OUT" "aht on Linux: $HOST"
