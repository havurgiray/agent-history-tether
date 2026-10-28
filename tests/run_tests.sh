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
echo "=== the masker (keys masked whole, ordinary text left alone) ==="
"$PY" redact_test.py
echo
echo "=== linux layer (polling watcher + tray --check) ==="
AHT_PY="$PY" "$PY" linux_test.py
echo
echo "=== Windows badge cache and entry point (any OS; apply() on Windows only) ==="
"$PY" ../windows/tests/winbadge_test.py
"$PY" ../windows/tests/aht_main_test.py
"$PY" ../windows/tests/aht_tray_test.py
echo
echo "=== the far end asked directly: copy ops, and a PC that answers (any OS; cmd.exe on Windows) ==="
"$PY" ../windows/tests/agent_smoke.py
echo
echo "✅ ALL AHT SUITES PASSED"
