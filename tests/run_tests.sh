#!/bin/bash
# Run the agent-history-tether test suites in isolated sandboxes.
# Never touches real agent data — every backend root is a throwaway fake.
# Override the interpreter under test with AHT_PY (default: /usr/bin/python3).
set -e
cd "$(dirname "$0")"
PY="${AHT_PY:-/usr/bin/python3}"
echo "=== multi-backend core (tag/move/copy/hook/conflict/backup/restore/adopt) ==="
AHT_PY="$PY" "$PY" core_test.py
echo
echo "=== linux layer (polling watcher + tray --check) ==="
AHT_PY="$PY" "$PY" linux_test.py
echo
echo "✅ ALL AHT SUITES PASSED"
