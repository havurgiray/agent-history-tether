#!/bin/bash
# Install agent-history-tether from this checkout (macOS).
#   - copies the tool into ~/.aht/tools/agent-history-tether/
#   - compiles the Swift binaries (watcher, badge tool, menu bar tray)
#   - generates the LaunchAgent (background watcher) for THIS user
#   - installs the `aht` command
#   - registers the Claude Code SessionStart hook (backs up settings.json)
#
# Requirements: macOS + Xcode Command Line Tools (swiftc) + /usr/bin/python3
#               (both from `xcode-select --install`). No other dependencies.
# No compiler?  Use the prebuilt aht.app from the releases page (or Homebrew)
# instead: it installs the same pieces from its own menu.
set -e
SRC="$(cd "$(dirname "$0")" && pwd)"

command -v swiftc >/dev/null 2>&1 || { echo "Missing swiftc. Run: xcode-select --install  (or install aht.app instead)"; exit 1; }
[ -x /usr/bin/python3 ] || { echo "Missing /usr/bin/python3. Run: xcode-select --install"; exit 1; }

/usr/bin/python3 "$SRC/install.py" --src "$SRC"

echo
echo "Done. Reconnect this Mac's existing projects with:"
echo "  aht adopt --apply"
echo "(If 'aht' is not found, open a new terminal — or follow the PATH note above.)"
