#!/bin/sh
# Smoke test of the background watcher (change-notification backend + the
# polling fallback) for aht, run INSIDE a wine container.  A project folder is
# renamed while `aht watch --once` runs; the watcher must notice, reconcile
# (forced Relink via AHT_ASSUME) and relink the fake claude store.
set -e

EXE="$1"
[ -n "$EXE" ] || { echo "usage: wine_watch_smoke.sh /path/to/aht.exe"; exit 2; }
export WINEDEBUG=-all
fail() { echo "WATCH FAIL: $*"; exit 1; }

run_case() {
    BACKEND="$1"
    T=/tmp/aht-watch
    rm -rf "$T"
    mkdir -p "$T/home/.aht" "$T/roots/projA" "$T/tools/claude"
    export AHT_HOME='Z:\tmp\aht-watch\home\.aht'
    export AHT_ROOTS='Z:\tmp\aht-watch\roots'
    export AHT_ROOT_CLAUDE='Z:\tmp\aht-watch\tools\claude'
    for b in GEMINI CURSOR OPENCODE CODEX COPILOT KIMI; do
        export AHT_ROOT_$b='Z:\tmp\aht-watch\tools\nope'
    done
    export AHT_NO_NOTIFY=1 AHT_NO_ICONS=1 AHT_NO_BACKUP=1 AHT_ASSUME=Relink

    ENCA=$(wine "$EXE" encode 'Z:\tmp\aht-watch\roots\projA' | tr -d '\r')
    mkdir -p "$T/tools/claude/$ENCA"
    printf '%s\n' '{"cwd":"x"}' > "$T/tools/claude/$ENCA/s1.jsonl"
    wine "$EXE" tag 'Z:\tmp\aht-watch\roots\projA' --apply > /dev/null

    ( sleep 8; mv "$T/roots/projA" "$T/roots/projB" ) &
    timeout 120 wine "$EXE" watch --once --no-startup-scan --debounce 1 \
        --poll-interval 2 $BACKEND || fail "watcher ($BACKEND) did not exit cleanly"
    wait

    ENCB=$(wine "$EXE" encode 'Z:\tmp\aht-watch\roots\projB' | tr -d '\r')
    [ -d "$T/tools/claude/$ENCB" ] || fail "watcher ($BACKEND) did not relink"
    echo "watch OK (${BACKEND:-notify} backend)"
}

run_case "--poll"
run_case ""

echo ""
echo "WATCH SMOKE OK — both backends relinked on a live rename"
