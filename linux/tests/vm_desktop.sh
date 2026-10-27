#!/bin/bash
# aht on a Linux desktop, without touching the one someone is logged in to:
# an invisible screen (Xvfb, a free display) with Openbox, a tray area (stalonetray) and
# a notice daemon (dunst) on a private session bus; then aht's tray, its
# menu, aht's window server, setup, the folder picker (a folder chosen, and
# Cancel), Continue's terminal, notices, Show in Files and start at login,
# each checked and screenshot; last, that no program crashed (a new report
# in /var/crash, or a crash in apport's log).
# Run by vm_check.sh.  Everything runs with a throwaway home in ./box (HOME,
# its XDG folders, the autostart folder and aht's home) and a stand-in
# systemctl, so the logged-in user's home and services are not touched.
# A made-up project; `claude` is a stand-in.
#
# Needs: xvfb openbox stalonetray dunst xdotool imagemagick x11-utils curl
#        libnotify-bin dbus gir1.2-ayatanaappindicator3-0.1 python3-gi
#        gir1.2-atspi-2.0 zenity and a terminal (xterm, or any x-terminal-emulator)
set -u
R="$(cd "$(dirname "$0")/../.." && pwd)"
OUT=$R/out; B=$R/box
[ -z "${AHT_IN_SESSION:-}" ] && { rm -rf "$OUT" "$B"; mkdir -p "$OUT"; }

result() {   # check ok(true|false|null) detail shot
  python3 -c 'import json,sys; print(json.dumps({"check": sys.argv[1], "ok": None if sys.argv[2] == "null" else sys.argv[2] == "true", "detail": sys.argv[3], "shot": sys.argv[4] or None}))' \
    "$1" "$2" "$3" "${4:-}" >> "$OUT/results.jsonl"
}
crashes() { stat -c '%n %Y' /var/crash/*.crash 2>/dev/null | LC_ALL=C sort; }
# apport notes every crash in its log, also one it writes no report for (a
# program that crashed already today, or whose last report nobody has opened)
ALOG_FILE=/var/log/apport.log
apport_lines() { [ -r "$ALOG_FILE" ] && wc -l < "$ALOG_FILE"; }
# the programs this check starts, and those the private bus starts for them
PROGS='Xvfb|dbus|openbox|stalonetray|dunst|python3|curl|xdotool|import|magick|zenity|x-terminal|gnome-terminal|xterm|konsole|nautilus|notify-send|xdg-|gio|tracker|gvfs|at-spi|dconf|ibus'

if [ -z "${AHT_IN_SESSION:-}" ]; then        # first the screen, then this script inside it
  # a throwaway home for everything the desktop part starts (the screen, the
  # private bus and what it starts, the apps): they write their settings,
  # recent files and caches there, not into the logged-in user's home
  REAL_HOME=$HOME
  export HOME=$B/home XDG_CONFIG_HOME=$B/home/.config XDG_DATA_HOME=$B/home/.local/share \
         XDG_CACHE_HOME=$B/home/.cache XDG_STATE_HOME=$B/home/.local/state
  mkdir -p "$XDG_CONFIG_HOME/autostart" "$XDG_DATA_HOME" "$XDG_CACHE_HOME" "$XDG_STATE_HOME" "$B/bin"
  # `systemctl --user` reaches the real user manager whatever HOME is: a
  # stand-in that only notes each call (the watcher is not running)
  printf '%s\n' '#!/bin/sh' "echo \"systemctl \$*\" >> \"$OUT/systemctl.log\"" \
    'case " $* " in *" is-active "*) echo inactive; exit 3;; esac' 'exit 1' > "$B/bin/systemctl"
  chmod +x "$B/bin/systemctl"; export PATH="$B/bin:$PATH"
  # each folder's own time (a file made and removed in it changes that) and
  # its entries; not ~/.config's ('..'), which the desktop session writes
  # to all the time
  real_home() {
    for d in "$REAL_HOME/.config/autostart" "$REAL_HOME/.config/systemd/user"; do
      stat -c '%n %y' "$d" 2>&1; ls -lA --time-style=full-iso "$d" 2>&1
    done
  }
  REAL=$(real_home)
  CRASHES=$(crashes); ALOG=$(apport_lines)
  # a free display number of its own (-displayfd), never one in use
  Xvfb -displayfd 3 -screen 0 1600x1000x24 -nolisten tcp 3>"$OUT/display" >/dev/null 2>&1 &
  XV=$!
  for i in $(seq 1 25); do sleep 0.2; [ -s "$OUT/display" ] && break; done
  [ -s "$OUT/display" ] || { echo '{"check": "the invisible screen", "ok": false, "detail": "Xvfb did not start"}' > "$OUT/results.jsonl"; exit 1; }
  sleep 0.5
  DISPLAY=":$(head -1 "$OUT/display")" AHT_IN_SESSION=1 dbus-run-session -- "$0"
  status=$?
  kill $XV 2>/dev/null
  # a program that crashed leaves a report in /var/crash (Ubuntu writes it some
  # seconds later, then shows a dialog on the real screen); a new one fails,
  # and so does a crash of one of this check's programs in apport's log
  sleep 3
  for i in $(seq 1 30); do pgrep -f 'share/apport/apport ' >/dev/null || break; sleep 1; done
  NEW=$(LC_ALL=C comm -13 <(echo "$CRASHES") <(crashes) | sed 's#.*/##; s/ [0-9]*$//' | paste -sd ' ' -)
  ACR=""
  if [ -n "$ALOG" ] && [ -r "$ALOG_FILE" ]; then
    [ "$(apport_lines)" -lt "$ALOG" ] && ALOG=0       # the log was rotated meanwhile
    # "executable: PATH (command line …)", or for a script "script: PATH,
    # interpreted by PYTHON (command line …)"
    ACR=$(tail -n +$((ALOG + 1)) "$ALOG_FILE" |
          sed -n -e 's/.*executable: \([^ ]*\).*/\1/p' -e 's/.*interpreted by \([^ ]*\).*/\1/p' |
          sed 's#.*/##' | grep -E "^($PROGS)" | LC_ALL=C sort -u | paste -sd ' ' -)
  fi
  D=""
  [ -n "$NEW" ] && D="new crash reports in /var/crash: $NEW"
  [ -n "$ACR" ] && D="${D:+$D; }apport's log has a crash of: $ACR"
  [ -z "$D" ] && D="no new crash reports"
  [ -z "$ALOG" ] && D="$D (apport's log could not be read, so only /var/crash was looked at)"
  if [ ! -d /var/crash ] && [ -z "$ALOG" ]; then
    result "nothing crashed" null "could not check: there is no /var/crash and no apport log here"
  else
    result "nothing crashed" "$([ -z "$NEW$ACR" ] && echo true || echo false)" "$D"
  fi
  [ -n "$NEW$ACR" ] && status=1
  # the stand-in systemctl and the throwaway home kept the real ones out of it
  SAME=$([ "$REAL" = "$(real_home)" ] && echo true || echo false)
  result "the logged-in user's home was not touched" "$SAME" \
    "$([ "$SAME" = true ] && echo "~/.config/autostart and ~/.config/systemd/user are as they were" ||
       echo "~/.config/autostart or ~/.config/systemd/user changed during the check")"
  [ "$SAME" = true ] || status=1
  exit $status
fi

# never the logged-in user's home: the part above set a throwaway one
[ "$HOME" = "$B/home" ] || { result "a throwaway home" false "HOME is $HOME, not $B/home"; exit 1; }

openbox >/dev/null 2>&1 &
sleep 0.5
stalonetray --geometry 6x1-0+0 --icon-size 32 --background "#e8e8e8" >/dev/null 2>&1 &
dunst >/dev/null 2>&1 &
sleep 1

shot() { import -window root png:- > "$OUT/$1.png" 2>/dev/null; echo "$1.png"; }
ok() { "$@" >/dev/null 2>&1 && echo true || echo false; }
seen() {   # seen NAME [PID]: 0 when an app on the screen (the one with PID, if it
           # is there) shows an item called NAME, 1 when not, 2 without AT-SPI
  timeout 5 python3 - "$1" "${2:-0}" 2>/dev/null <<'PY'
import sys
try:
    import gi
    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi
except (ImportError, ValueError):
    sys.exit(2)
name, pid = sys.argv[1], int(sys.argv[2] or 0)
def has(a, depth=0):
    try:
        if a.get_name() == name:
            return True
        return depth < 30 and any(has(a.get_child_at_index(i), depth + 1)
                                  for i in range(min(a.get_child_count(), 200)))
    except Exception:
        return False
def pid_of(a):
    try:
        return a.get_process_id()
    except Exception:
        return -1
desk = Atspi.get_desktop(0)
apps = [a for a in (desk.get_child_at_index(i) for i in range(desk.get_child_count()))
        if a is not None]
mine = [a for a in apps if pid and pid_of(a) == pid]
sys.exit(0 if any(has(a) for a in (mine or apps)) else 1)
PY
}

# ---- a throwaway aht home with one made-up project and session ----
P=$B/roots/demo-project
mkdir -p "$P" "$B/home/.aht" "$B/tools/nope" "$B/trash"
echo "# demo project" > "$P/README.md"
export AHT_HOME=$B/home/.aht AHT_ROOTS=$B/roots AHT_ROOT_CLAUDE=$B/tools/claude
for b in GEMINI CURSOR OPENCODE CODEX COPILOT KIMI KIMI_CODE; do export AHT_ROOT_$b=$B/tools/nope; done
export AHT_NO_ICONS=1 AHT_NO_BACKUP=1 AHT_TRASH=$B/trash
ENC=$(python3 "$R/aht.py" encode "$P"); mkdir -p "$B/tools/claude/$ENC"
printf '%s\n' "{\"type\":\"user\",\"cwd\":\"$P\",\"timestamp\":\"2026-10-25T18:00:00Z\",\"entrypoint\":\"cli\",\"message\":{\"role\":\"user\",\"content\":\"write a short README\"}}" \
  '{"type":"ai-title","aiTitle":"Write the README"}' > "$B/tools/claude/$ENC/demo1.jsonl"
# Continue runs this instead of the real claude; aht's window is only noted
# (AHT_WINDOW_LOG: no browser starts), and BROWSER notes any other page
printf '#!/bin/sh\necho "aht check: claude $*"\nsleep 600\n' > "$B/claude"; chmod +x "$B/claude"
export AHT_CLAUDE=$B/claude
export AHT_WINDOW_LOG=$OUT/browser.txt
printf '#!/bin/sh\necho "$1" >> %s/browser.txt\n' "$OUT" > "$B/browser"; chmod +x "$B/browser"
export BROWSER=$B/browser
# start at login writes into the throwaway home too (the core and the tray
# both honour AHT_AUTOSTART_DIR)
export AHT_AUTOSTART_DIR=$HOME/.config/autostart
AUTO=$AHT_AUTOSTART_DIR/aht-tray.desktop

# ---- 1. the tray starts and shows its icon ----
python3 "$R/linux/tray.py" > "$OUT/tray.log" 2>&1 &
TRAY=$!
sleep 6
ICON=$(xwininfo -root -tree 2>/dev/null | grep -m1 '("aht" "aht")' | grep -o '[0-9]*x[0-9]*+[0-9]*+[0-9]*  +[0-9]*+[0-9]*')
result "tray starts with its icon" "$(kill -0 $TRAY 2>/dev/null && [ -n "$ICON" ] && echo true || echo false)" \
  "icon at ${ICON:-nowhere}" "$(shot 01-tray)"

# ---- 2. its menu: Open aht… starts the window ----
X=$(echo "$ICON" | sed -E 's/.*\+([0-9]+)\+([0-9]+)$/\1/'); Y=$(echo "$ICON" | sed -E 's/.*\+([0-9]+)\+([0-9]+)$/\2/')
xdotool mousemove $((X + 16)) $((Y + 16)) click 1; sleep 1.5
MENU=$(shot 02-menu)
xdotool key Down Return                  # past the status lines, which take no focus
for i in $(seq 1 20); do sleep 1; [ -s "$OUT/browser.txt" ] && break; done
result "tray menu → Open aht… → the window" "$([ -s "$OUT/browser.txt" ] && echo true || echo false)" \
  "the page to open: $(head -1 "$OUT/browser.txt" 2>/dev/null | sed 's/code=.*/code=…/')" "$MENU"

# ---- talk to the window's server as the page does ----
ST=$AHT_HOME/run/window.json
PORT=$(python3 -c "import json;print(json.load(open('$ST'))['port'])" 2>/dev/null)
CONTROL=$(python3 -c "import json;print(json.load(open('$ST'))['control'])" 2>/dev/null)
BASE="http://127.0.0.1:$PORT"; JAR=$B/cookies
URL=$(curl -s "$BASE/launch?control=$CONTROL" | python3 -c "import json,sys;print(json.load(sys.stdin)['url'])" 2>/dev/null)
# the launch link answers with the cookie and sends the page on to /#k=KEY,
# the key the page sends with every call; the link is not followed here
KEY=$(curl -s -c "$JAR" -o /dev/null -D - "$URL" | tr -d '\r' | sed -n 's/^[Ll]ocation: .*#k=\([^&]*\).*/\1/p')
api() { curl -s -m 120 -b "$JAR" -H "X-AHT: $KEY" -H "Content-Type: application/json" -d "$2" "$BASE$1"; }
run() { api /api/run "$(python3 -c 'import json,sys;print(json.dumps({"args": sys.argv[1:]}))' "$@")"; }
field() { python3 -c "import json,sys; d=json.load(sys.stdin); print(eval(sys.argv[1]))" "$1" 2>/dev/null; }
PING=$(curl -s -m 10 -b "$JAR" -H "X-AHT: $KEY" "$BASE/api/ping" | field 'd["ok"]')
result "the window's server lets the page in" "$([ "$PING" = True ] && echo true || echo false)" \
  "port ${PORT:-none}$([ -z "$KEY" ] && echo ', no key for the page')"

# ---- 3. setup takes on the made-up project ----
ADOPTED=$(run setup --apply --json --adopt "$P" --update-check off | field 'd["json"]["adopted"]')
result "setup finds and takes on the project" "$(echo "$ADOPTED" | grep -q demo-project && echo true || echo false)" "adopted: $ADOPTED"

# ---- 4. the folder picker (zenity) ----
(api /api/pick-folder '{"prompt": "aht check: pick a folder"}' > "$B/pick.json") &
for i in $(seq 1 10); do sleep 1; W=$(xdotool search --name "aht check: pick a folder" 2>/dev/null | head -1); [ -n "$W" ] && break; done
PICKSHOT=$(shot 04-folder-picker)
if [ -n "$W" ]; then
  # GTK fills in a folder name a moment after it is typed and puts it behind
  # what was typed since: type the path, let the folders load, then type it
  # again over all of it
  xdotool windowactivate --sync "$W" key ctrl+l; sleep 0.5
  xdotool type --delay 20 "$P/"; sleep 1.5
  xdotool key ctrl+a; xdotool type --delay 20 "$P/"; sleep 1
  xdotool key Return; sleep 0.5; xdotool key Return
fi
for i in $(seq 1 10); do sleep 1; [ -s "$B/pick.json" ] && break; done
PICKED=$(field 'd["path"]' < "$B/pick.json")
result "folder picker" "$([ -n "$W" ] && [ "$PICKED" = "$P" ] && echo true || echo false)" \
  "picked: ${PICKED:-nothing}$([ "$PICKED" = "$P" ] || echo " (wanted $P)")" "$PICKSHOT"

# Cancel ends it: the answer says a chooser was shown, so the window asks
# for nothing more (no second box), and no chooser is left
(api /api/pick-folder '{"prompt": "aht check: cancel this"}' > "$B/pick-cancel.json") &
W=""
for i in $(seq 1 10); do sleep 1; W=$(xdotool search --name "aht check: cancel this" 2>/dev/null | head -1); [ -n "$W" ] && break; done
CANCELSHOT=$(shot 04b-folder-picker-cancel)
[ -n "$W" ] && xdotool windowactivate --sync "$W" key Escape
for i in $(seq 1 10); do sleep 1; [ -s "$B/pick-cancel.json" ] && break; done
ANSWER=$(field '(d["path"], d["chooser"])' < "$B/pick-cancel.json")
LEFT=$(xdotool search --name "aht check: cancel this" 2>/dev/null | wc -l)
result "Cancel in the folder picker ends it: no second box" \
  "$([ -n "$W" ] && [ "$ANSWER" = "('', True)" ] && [ "$LEFT" -eq 0 ] && echo true || echo false)" \
  "$([ -n "$W" ] || echo 'no chooser came up; ')answer: ${ANSWER:-none} (no path, a chooser was shown); choosers left: $LEFT" "$CANCELSHOT"

# ---- 5. Continue: a terminal in the project, running claude --resume ----
CONT=$(run resume-here "$P" | field 'd["ok"]')
sleep 4
TERM_PID=$(pgrep -f "$B/claude --resume demo1" | head -1)
result "Continue opens a terminal in the project" "$([ "$CONT" = True ] && [ -n "$TERM_PID" ] && echo true || echo false)" \
  "$(ps -o args= -p "${TERM_PID:-0}" 2>/dev/null)" "$(shot 05-continue)"
pkill -f "$B/claude --resume" 2>/dev/null

# ---- 6. notices, one after another ----
run notices --test >/dev/null; sleep 2
N1=$(dunstctl count displayed 2>/dev/null)
S1=$(shot 06-notice)
notify-send -a aht "demo-project waits for you" "it needs an answer"; sleep 2
result "notices show (see the screenshots)" "$([ "${N1:-0}" -ge 1 ] && echo true || echo false)" "on screen: ${N1:-0}" "$S1"
result "a second notice in a row" null "check the screenshot" "$(shot 06b-second-notice)"
dunstctl close-all 2>/dev/null

# ---- 7. Show in Files ----
REV=$(api /api/reveal "{\"path\": \"$P\"}" | field 'd["ok"]')
for i in $(seq 1 10); do sleep 1; FM=$(xdotool search --name "demo-project" 2>/dev/null | head -1); [ -n "$FM" ] && break; done
FMPID=$([ -n "$FM" ] && xdotool getwindowpid "$FM" 2>/dev/null)
# nautilus names its window before it has read the folder and drawn it (a
# fresh profile takes some seconds): the shot waits until README.md is in it
SHOWN=false
if [ -n "$FM" ]; then
  END=$((SECONDS + 20))
  while [ $SECONDS -lt $END ]; do
    seen README.md "$FMPID"; s=$?
    [ $s = 0 ] && { SHOWN=true; sleep 0.5; break; }
    [ $s = 2 ] && { SHOWN=unknown; break; }
    sleep 0.5
  done
fi
WHY=""
[ -n "$FM" ] && [ "$SHOWN" = false ] && WHY=", but README.md is not shown in it"
[ "$SHOWN" = unknown ] && WHY=", but README.md cannot be looked for (no AT-SPI: gir1.2-atspi-2.0)"
result "Show in Files opens the folder" "$([ "$REV" = True ] && [ "$SHOWN" = true ] && echo true || echo false)" \
  "$( [ -n "$FM" ] && xdotool getwindowname "$FM")$WHY" "$(shot 08-files)"
# closed by its process (SIGTERM, a normal exit): destroying its window makes
# nautilus abort, and Ubuntu then shows a crash dialog on the real screen
if [ -n "$FMPID" ]; then
  kill "$FMPID" 2>/dev/null
  for i in $(seq 1 10); do kill -0 "$FMPID" 2>/dev/null || break; sleep 0.5; done
fi

# ---- 8. start at login, on and off ----
ON=$(run autostart on --json | field 'd["json"]["on"]')
EXEC=$(grep -m1 '^Exec=' "$AUTO" 2>/dev/null)
# read back as the desktop reads it: GLib undoes the string escapes, then the
# quoting of each path; no command means nothing would start at login
TRAYPY=$(python3 - "$AUTO" 2>/dev/null <<'PY'
import sys
from gi.repository import Gio, GLib
info = Gio.DesktopAppInfo.new_from_filename(sys.argv[1])
print(GLib.shell_parse_argv(info.get_commandline())[1][1])
PY
)
OFF=$(run autostart off --json | field 'd["json"]["on"]')
result "start at login: on, then off" "$([ "$ON" = True ] && [ "$OFF" = False ] && [ -f "$TRAYPY" ] && echo true || echo false)" \
  "$EXEC$([ -f "$TRAYPY" ] || echo ' (the desktop cannot read the tray from it)')"

# ---- the end ----
kill $TRAY 2>/dev/null
pkill -f "$R/aht.py window" 2>/dev/null
for p in stalonetray dunst openbox; do pkill -P $$ -x $p 2>/dev/null; done
# what the private bus started for the apps (the file indexer, gvfs, the
# accessibility bus) would outlive it: stop each process on this session's bus
if [ -n "${DBUS_SESSION_BUS_ADDRESS:-}" ]; then
  BUS="DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS%%,*}"
  for p in $(pgrep -u "$(id -u)"); do
    { [ "$p" = $$ ] || [ "$p" = "$PPID" ]; } && continue      # this script, dbus-run-session
    tr '\0' '\n' 2>/dev/null < "/proc/$p/environ" | cut -d, -f1 | grep -qxF "$BUS" && kill "$p" 2>/dev/null
  done
fi
echo '{"check": "done"}' >> "$OUT/results.jsonl"
