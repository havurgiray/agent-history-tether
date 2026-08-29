#!/bin/bash
# Uninstall agent-history-tether (stops the watcher, removes the hook and
# the `aht` command). History under ~/.claude/projects is NEVER touched.
#
#   ./uninstall.sh                 # stop automation, keep markers/registry/icons
#   ./uninstall.sh --remove-icons  # also clear the folder badges
#   ./uninstall.sh --purge         # also remove markers + registry (history kept)
INSTALLED="$HOME/.aht/tools/agent-history-tether/uninstall.py"
REPO="$(cd "$(dirname "$0")" && pwd)/uninstall.py"
if [ -f "$INSTALLED" ]; then
  /usr/bin/python3 "$INSTALLED" "$@"
else
  /usr/bin/python3 "$REPO" "$@"
fi
