#!/bin/bash
# Run the agent-history-tether test suites in isolated sandboxes, side by
# side: every core unit (tests/core/) and the other suites at once.
# Never touches real agent data — every backend root is a throwaway fake.
# Override the interpreter under test with AHT_PY (default: /usr/bin/python3)
# and how many run at once with AHT_JOBS (default: the number of CPUs).
set -e
cd "$(dirname "$0")"
PY="${AHT_PY:-/usr/bin/python3}"
AHT_PY="$PY" "$PY" core_test.py --all ${AHT_JOBS:+--jobs "$AHT_JOBS"}
echo
echo "✅ ALL AHT SUITES PASSED"
