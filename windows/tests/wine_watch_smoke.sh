#!/bin/sh
# Smoke test of the background watcher (change-notification backend + the
# polling fallback) for aht.  Runs under wine (build.sh invokes it inside the
# container) or natively on Windows from Git Bash with AHT_SMOKE_NATIVE=1.
# A project folder is renamed while `aht watch --once` runs; the watcher must
# notice, reconcile (forced Relink via AHT_ASSUME) and relink the fake claude
# store.
set -e

EXE="$1"
[ -n "$EXE" ] || { echo "usage: wine_watch_smoke.sh /path/to/aht.exe"; exit 2; }
export WINEDEBUG=-all
fail() { echo "WATCH FAIL: $*"; exit 1; }

T=/tmp/aht-watch
if [ -n "${AHT_SMOKE_NATIVE:-}" ]; then RUN=""; else RUN="wine"; fi
W() { $RUN "$EXE" "$@" | tr -d '\r'; }

run_case() {
    BACKEND="$1"
    rm -rf "$T"
    mkdir -p "$T/home/.aht" "$T/roots/projA" "$T/tools/claude"
    if [ -n "${AHT_SMOKE_NATIVE:-}" ]; then
        WT="$(cygpath -w -l "$T")"       # long form: the runner's TEMP is 8.3
    else
        WT='Z:\tmp\aht-watch'
    fi
    export AHT_HOME="$WT\\home\\.aht"
    export AHT_ROOTS="$WT\\roots"
    export AHT_ROOT_CLAUDE="$WT\\tools\\claude"
    for b in GEMINI CURSOR OPENCODE CODEX COPILOT KIMI KIMI_CODE; do
        export "AHT_ROOT_$b=$WT\\tools\\nope"
    done
    export AHT_NO_NOTIFY=1 AHT_NO_ICONS=1 AHT_NO_BACKUP=1 AHT_ASSUME=Relink

    ENCA=$(W encode "$WT\\roots\\projA")
    mkdir -p "$T/tools/claude/$ENCA"
    printf '%s\n' '{"cwd":"x"}' > "$T/tools/claude/$ENCA/s1.jsonl"
    W tag "$WT\\roots\\projA" --apply > /dev/null

    ( sleep 8; mv "$T/roots/projA" "$T/roots/projB" ) &
    timeout 120 $RUN "$EXE" watch --once --no-startup-scan --debounce 1 \
        --poll-interval 2 $BACKEND || fail "watcher ($BACKEND) did not exit cleanly"
    wait

    ENCB=$(W encode "$WT\\roots\\projB")
    [ -d "$T/tools/claude/$ENCB" ] || fail "watcher ($BACKEND) did not relink"
    echo "watch OK (${BACKEND:-notify} backend)"
}

run_case "--poll"
run_case ""

echo ""
echo "WATCH SMOKE OK — both backends relinked on a live rename"
