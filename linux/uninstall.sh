#!/bin/sh
# Stop and remove aht's Linux automation. History is never touched.
#   ./uninstall.sh                    stop the watcher + hook, keep the data
#   ./uninstall.sh --remove-emblems   also clear file-manager emblems
#   ./uninstall.sh --purge            also remove markers + registry + config
set -e
SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/.aht/tools/agent-history-tether"
if [ -f "$DEST/uninstall.py" ]; then
  exec python3 "$DEST/uninstall.py" "$@"
else
  exec python3 "$SRC/uninstall.py" "$@"
fi
