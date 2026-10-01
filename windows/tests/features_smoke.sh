#!/bin/sh
# Smoke test of the commands added since 0.11 in the built aht.exe: search,
# journal, report, share, secrets, rules, loose ends, undo, tidy, limits,
# sessions, workspace.  Runs natively on Windows from Git Bash with
# AHT_SMOKE_NATIVE=1 (CI), under wine otherwise, or with AHT_SMOKE_POSIX=1
# against any `aht` command on macOS or Linux (to check the script itself).
# Every store is a throwaway fake; real agent data is never touched.
set -e

EXE="$1"
[ -n "$EXE" ] || { echo "usage: features_smoke.sh /path/to/aht.exe"; exit 2; }
export WINEDEBUG=-all

T=/tmp/aht-features-smoke
rm -rf "$T"
mkdir -p "$T/home/.aht" "$T/roots/paper" "$T/tools/claude" "$T/tools/nope" "$T/trash"
if [ -n "${AHT_SMOKE_POSIX:-}" ]; then
  RUN=""; WT="$(cd "$T" && pwd -P)"; SEP="/"      # /tmp is a link on macOS
elif [ -n "${AHT_SMOKE_NATIVE:-}" ]; then
  RUN=""; WT="$(cygpath -w -l "$T")"; SEP='\'
else
  RUN="wine"; WT='Z:\tmp\aht-features-smoke'; SEP='\'
fi
J() { printf '%s' "$1" | sed 's/\\/\\\\/g'; }           # a path as JSON text
P() { printf '%s' "$WT$SEP$1" | sed "s#/#$SEP#g"; }      # a path under the sandbox
W() { $RUN "$EXE" "$@" | tr -d '\r'; }
fail() { echo "FEATURES SMOKE FAIL: $*"; exit 1; }
has() { printf '%s\n' "$1" | grep -q -E -- "$2" || fail "$3 (got: $(printf '%s' "$1" | head -c 400))"; }

export AHT_HOME="$(P home/.aht)" AHT_ROOTS="$(P roots)"
export AHT_ROOT_CLAUDE="$(P tools/claude)"
for b in GEMINI CURSOR OPENCODE CODEX COPILOT KIMI KIMI_CODE; do
  export AHT_ROOT_$b="$(P tools/nope)"
done
export AHT_NO_NOTIFY=1 AHT_NO_ICONS=1 AHT_NO_BACKUP=1 AHT_NO_SEARCH_INDEX=""
export AHT_TRASH="$(P trash)"

PAPER="$(P roots/paper)"
echo "x = 1" > "$T/roots/paper/a.py"
ENC=$(W encode "$PAPER")
mkdir -p "$T/tools/claude/$ENC"
KEY="sk-""ant-""api03-""$(printf 'Qw7%.0s' 1 2 3 4 5 6 7 8 9 10 11 12)"
NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
cat > "$T/tools/claude/$ENC/s1.jsonl" <<EOF
{"type":"user","cwd":"$(J "$PAPER")","timestamp":"$NOW","message":{"role":"user","content":"deploy the heron service, the key is $KEY"}}
{"type":"ai-title","aiTitle":"Heron deploy"}
{"type":"assistant","cwd":"$(J "$PAPER")","timestamp":"$NOW","message":{"role":"assistant","content":[{"type":"text","text":"Deployed. Shall I also write the release notes?"}]}}
EOF
W tag "$PAPER" --apply >/dev/null

echo "== search =="
OUT=$(W search heron --json)
has "$OUT" '"Heron deploy"' "search did not find the session by a word"
printf '%s' "$OUT" | grep -q "$KEY" && fail "the search index holds the key"

echo "== journal / report / share =="
has "$(W journal "$PAPER" --json)" "heron service" "journal lacks the session"
has "$(W report --json --by project)" '"sessions": 1' "report did not count the session"
OUT=$(W share "$PAPER" --format md --json)
has "$OUT" "heron service" "share lacks the conversation"
printf '%s' "$OUT" | grep -q "$KEY" && fail "share leaked the key"

echo "== secrets / rules / loose ends =="
has "$(W secrets "$PAPER" --json)" "Anthropic API key" "secrets did not find the key"
echo "use tabs" > "$T/roots/paper/CLAUDE.md"
has "$(W rules "$PAPER" --json)" "CLAUDE.md" "rules did not see CLAUDE.md"
has "$(W loose-ends --json)" "release notes" "loose ends missed the open question"

echo "== undo a session (a real copy off macOS) =="
W config --set checkpoints=true >/dev/null
has "$(W checkpoint "$PAPER" --json)" '"method": "(copy|clone)"' "no copy was made"
echo "x = 2" > "$T/roots/paper/a.py"
echo "new" > "$T/roots/paper/made.txt"
has "$(W undo "$PAPER" --json)" '"added": 1' "undo did not see the new file"
W undo "$PAPER" --apply --json >/dev/null
grep -q "x = 1" "$T/roots/paper/a.py" || fail "undo did not put a.py back"
[ ! -e "$T/roots/paper/made.txt" ] || fail "undo left the new file"

echo "== tidy: read and remove a history without a folder =="
mkdir -p "$T/tools/claude/orphan-history"
printf '%s\n' '{"type":"user","cwd":"/gone","message":{"role":"user","content":"old work"}}' \
  > "$T/tools/claude/orphan-history/o1.jsonl"
has "$(W tidy --show=orphan-history)" "old work" "tidy --show did not show the history"
W tidy --remove-history=orphan-history --apply >/dev/null
[ ! -d "$T/tools/claude/orphan-history" ] || fail "the history was not moved to the Trash"
[ -d "$T/trash/orphan-history" ] || fail "the history is not in the Trash"

echo "== limits / sessions / tab names / workspace / checkup =="
has "$(W limits --json)" '"limits": \[\]' "limits failed"
has "$(W sessions --json)" '"Heron deploy"' "sessions lacks the title"
W tab-names --json >/dev/null || fail "tab-names failed"
W workspace --json >/dev/null || fail "workspace failed"
W checkup --json >/dev/null || fail "checkup failed"

echo "FEATURES SMOKE OK"
