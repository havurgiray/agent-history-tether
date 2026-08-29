#!/bin/sh
# Install agent-history-tether on Linux.
#   - copies the shared core + the Linux layer into
#     ~/.aht/tools/agent-history-tether/
#   - installs the `aht` command into ~/.local/bin
#   - registers a systemd --user watcher (or an XDG autostart entry)
#   - registers the Claude Code SessionStart hook (backs up settings.json)
#
# Requirements: python3 (3.8+, stdlib only). Optional: zenity/kdialog for
# prompts, gio for folder emblems. No root, no pip, nothing outside $HOME.
set -e
SRC="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SRC/.." && pwd)"
DEST="$HOME/.aht/tools/agent-history-tether"

command -v python3 >/dev/null 2>&1 || { echo "python3 not found"; exit 1; }
python3 - <<'EOF' || exit 1
import sys
if sys.version_info < (3, 8):
    sys.exit("python3 >= 3.8 required, found %s" % sys.version.split()[0])
EOF

# The core is shared with macOS and lives at the repo root; if someone copied
# only this directory, fall back to a local copy.
if [ -f "$ROOT/aht.py" ]; then CORE="$ROOT/aht.py"
elif [ -f "$SRC/aht.py" ]; then CORE="$SRC/aht.py"
else echo "cannot find aht.py (expected at $ROOT/aht.py)"; exit 1; fi

mkdir -p "$DEST"
cp "$CORE" "$DEST/aht.py"
for f in watcher.py tray.py install.py uninstall.py README.md; do
  [ -f "$SRC/$f" ] && cp "$SRC/$f" "$DEST/$f"
done
chmod +x "$DEST/aht.py" "$DEST/watcher.py" "$DEST/tray.py" 2>/dev/null || true

python3 "$DEST/install.py"

echo
echo "Done. Reconnect this machine's existing projects with:"
echo "  aht adopt --apply"
echo "Then check everything with:  aht doctor"
