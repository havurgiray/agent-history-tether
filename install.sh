#!/bin/bash
# Install agent-history-tether from this repo.
#   - copies the tool into ~/.aht/tools/agent-history-tether/
#   - compiles the Swift binaries
#   - generates the LaunchAgent (background watcher) for THIS user
#   - installs the `aht` command
#   - registers the Claude Code SessionStart hook (backs up settings.json)
#
# Requirements: macOS + Xcode Command Line Tools (swiftc) + /usr/bin/python3
#               (both from `xcode-select --install`). No other dependencies.
set -e
SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/.aht/tools/agent-history-tether"

command -v swiftc >/dev/null 2>&1 || { echo "Missing swiftc. Run: xcode-select --install"; exit 1; }
[ -x /usr/bin/python3 ] || { echo "Missing /usr/bin/python3. Run: xcode-select --install"; exit 1; }

mkdir -p "$DEST"
for f in aht.py badge_icon.swift watcher.swift install.py uninstall.py README.md; do
  cp "$SRC/$f" "$DEST/$f"
done
[ -f "$SRC/macos/tray.swift" ] && cp "$SRC/macos/tray.swift" "$DEST/tray.swift"

/usr/bin/python3 "$DEST/install.py"

echo
echo "Done. Reconnect this Mac's existing projects with:"
echo "  aht adopt --apply"
echo "(If 'aht' is not found, open a new terminal — or follow the PATH note above.)"
