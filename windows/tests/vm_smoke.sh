#!/bin/sh
# The three smoke scripts against this checkout's own build, natively on
# Windows (Git Bash); one line each: name, exit status, last line.
cd "$(dirname "$0")/../.." || exit 1
export AHT_SMOKE_NATIVE=1
for t in wine_smoke wine_watch_smoke features_smoke; do
  sh "windows/tests/$t.sh" "$PWD/windows/dist/aht/aht.exe" > "$t.log" 2>&1
  echo "$t $? $(tail -1 "$t.log" | tr -d '\r')"
done
