#!/bin/sh
# Smoke test of the commands added since 0.11 in the built aht.exe: search,
# journal, report, share, secrets, rules, loose ends, undo, tidy, switch
# (Summary Only) and relays, limits, sessions, workspace, asking other
# machines over Windows' own ssh (status, remote add, pickup), Bring Here's
# list and dry run from a test-mode machine; and the hidden ones
# another aht uses: `_core --id`
# (the core inside the exe is this checkout's aht.py, byte for byte) and
# `_agent`.  Runs natively on Windows from Git Bash with
# AHT_SMOKE_NATIVE=1 (CI), under wine otherwise, or with AHT_SMOKE_POSIX=1
# against any `aht` command on macOS or Linux (to check the script itself).
# Every store is a throwaway fake; real agent data is never touched.  It
# works in /tmp/aht-features-smoke (AHT_SMOKE_DIR in place of /tmp).
set -e

EXE="$1"
[ -n "$EXE" ] || { echo "usage: features_smoke.sh /path/to/aht.exe"; exit 2; }
export WINEDEBUG=-all
REPO="$(cd "$(dirname "$0")/../.." && pwd)"

T="${AHT_SMOKE_DIR:-/tmp}/aht-features-smoke"
rm -rf "$T"
mkdir -p "$T/home/.aht" "$T/roots/paper" "$T/tools/claude" "$T/tools/nope" "$T/trash"
if [ -n "${AHT_SMOKE_POSIX:-}" ]; then
  RUN=""; WT="$(cd "$T" && pwd -P)"; SEP="/"      # /tmp is a link on macOS
elif [ -n "${AHT_SMOKE_NATIVE:-}" ]; then
  RUN=""; WT="$(cygpath -w -l "$T")"; SEP='\'
else
  RUN="wine"; WT="Z:$(printf '%s' "$T" | tr '/' '\\')"; SEP='\'
fi
J() { printf '%s' "$1" | sed 's/\\/\\\\/g'; }           # a path as JSON text
P() {                                                     # a path under the sandbox
  if [ "$SEP" = "/" ]; then printf '%s/%s' "$WT" "$1"
  else printf '%s\\%s' "$WT" "$(printf '%s' "$1" | tr '/' '\\')"; fi
}
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

echo "== the core inside: _core --id, _agent =="
# the first 12 hex digits of the sha256 of this checkout's aht.py, as built
sum256() { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1"; else shasum -a 256 "$1"; fi; }
WANT=$(sum256 "$REPO/aht.py" | cut -c1-12)
GOT=$(W _core --id)
[ "$GOT" = "$WANT" ] || fail "_core --id is '$GOT', this checkout's aht.py is $WANT"
has "$(printf '%s' '{"op": "probe"}' | W _agent)" '^@@AHT@@\{.*"ok": true' "_agent did not answer the probe"

echo "== other machines: a PC asks them over its own ssh =="
# a PC can ask other machines (can_reach) and hand projects over (supported:
# aht's own copy moves the files); adding a machine that does not answer fails with ssh's own
# "cannot reach", never "getsockname" (Windows' ssh stops on the Control
# options).  Only natively: wine has no ssh, and on macOS or Linux the add
# would ask this machine's real ssh server
HO=$(W status --json | sed -n '/"handover": {/,/"remotes"/p')
has "$HO" '"supported": true' "status: the exe does not hand projects over"
if [ -n "${AHT_SMOKE_NATIVE:-}" ]; then
  has "$HO" '"can_reach": true' "status: Windows' own ssh is there, yet other machines cannot be asked"
  OUT=$(W remote add x nobody@127.0.0.1 2>&1)
  has "$OUT" "cannot reach x" "remote add to a machine that does not answer did not say so"
  printf '%s' "$OUT" | grep -q getsockname && fail "Windows' ssh got the Control options: $OUT"
  printf '%s' "$(W remote --json)" | grep -q '"x"' && fail "remote add kept a machine that did not answer"
fi

echo "== Pick Up from a machine that does not answer: a clean failure =="
# a name that never resolves (.invalid), so no machine is asked: natively and
# on macOS or Linux ssh says it cannot reach it, under wine there is no ssh;
# either way the JSON says so, nothing is written and nothing crashes
printf '%s' '{"remotes": {"gone": {"ssh": "nobody@aht-unreachable.invalid"}}}' > "$T/home/.aht/config.json"
RC=0; $RUN "$EXE" pickup "$(P roots/paper)" --from gone --json > "$T/pickup.out" 2>&1 || RC=$?
OUT=$(tr -d '\r' < "$T/pickup.out")
[ "$RC" = 1 ] || fail "pickup from a machine that does not answer exited $RC: $OUT"
has "$OUT" '"applied": false' "pickup from a machine that does not answer claims it applied"
has "$OUT" '"error": "(cannot reach gone|.*ssh)' "pickup from a machine that does not answer gave no error"
printf '%s' "$OUT" | grep -q Traceback && fail "pickup crashed: $OUT"
[ ! -e "$T/roots/paper/.aht/handover" ] || fail "pickup wrote a relay though nothing answered"
rm -f "$T/home/.aht/config.json"

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
if [ -n "${AHT_SMOKE_NATIVE:-}" ]; then       # and once to the real Recycle Bin
  mkdir -p "$T/tools/claude/orphan-recycled"
  printf '%s\n' '{"type":"user","cwd":"/gone-too","message":{"role":"user","content":"older work"}}' \
    > "$T/tools/claude/orphan-recycled/o2.jsonl"
  OUT=$(unset AHT_TRASH; W tidy --remove-history=orphan-recycled --apply)
  [ ! -d "$T/tools/claude/orphan-recycled" ] || fail "the history was not moved to the Recycle Bin: $OUT"
  # it is in the Recycle Bin, deleted from the fake Claude store; then it goes
  # for good (the $R… item and its $I… record), so no run leaves one behind
  RB=$(powershell.exe -NoProfile -NonInteractive -Command '
    $n = 0
    foreach ($i in @((New-Object -ComObject Shell.Application).NameSpace(10).Items())) {
      $was = [string]$i.ExtendedProperty("System.Recycle.DeletedFrom")
      if ($i.Name -ne "orphan-recycled" -or $was.TrimEnd("\") -notlike "*\tools\claude") { continue }
      $n++
      $r = $i.Path
      Remove-Item -LiteralPath $r -Recurse -Force -ErrorAction SilentlyContinue
      $meta = Join-Path (Split-Path $r) ("`$I" + (Split-Path $r -Leaf).Substring(2))
      Remove-Item -LiteralPath $meta -Force -ErrorAction SilentlyContinue
    }
    $n' | tr -d '\r')
  [ "${RB:-0}" -ge 1 ] 2>/dev/null || fail "the history is not in the Recycle Bin (found: ${RB:-nothing}): $OUT"
fi

echo "== switch: Summary Only from a Codex session, and the relay it leaves =="
# switch reads Codex's newer storage through sqlite3, so this also proves the
# module is inside the exe; no agent starts
mkdir -p "$T/tools/codex/2026/10/27"
export AHT_ROOT_CODEX="$(P tools/codex)"
CXID="c0dec0de-0000-4000-8000-000000000001"
cat > "$T/tools/codex/2026/10/27/rollout-2026-10-27T10-00-00-$CXID.jsonl" <<EOF
{"type":"session_meta","timestamp":"$NOW","payload":{"id":"$CXID","cwd":"$(J "$PAPER")"}}
{"type":"event_msg","timestamp":"$NOW","payload":{"type":"user_message","message":"tidy the pelican module"}}
{"type":"event_msg","timestamp":"$NOW","payload":{"type":"agent_message","message":"The pelican module is tidy."}}
EOF
OUT=$(W switch "$PAPER" --to claude --session "$CXID" --brief-only --apply --json)
has "$OUT" '"applied": true' "switch --brief-only did not write the summary"
has "$OUT" '"mode": "brief-only"' "switch --brief-only is not in Summary Only mode"
RID=$(printf '%s\n' "$OUT" | sed -n 's/.*"relay": "\([0-9a-f-]*\)".*/\1/p' | head -n 1)
[ -n "$RID" ] || fail "switch --brief-only named no relay: $(printf '%s' "$OUT" | head -c 400)"
grep -q "pelican module" "$T/roots/paper/.aht/handover/relay-$RID.md" \
  || fail "the summary lacks the Codex session's exchange"
OUT=$(W relays "$PAPER" --json)
has "$OUT" "\"id\": \"$RID\"" "relays does not list the hand-off"
has "$OUT" '"open": false' "a Summary Only hand-off counts as open"

echo "== Bring Here from a test-mode machine: its list and a dry run =="
# a folder stands in for the other machine (remotes.<name>.root): the exe runs
# itself there as `_agent`, with that folder's home.  Its project is
# registered by the exe run with that home; nothing is brought (no --apply)
mkdir -p "$T/mac/home/code/shop/bin" "$T/mac/home/.aht" "$T/mac/home/.claude/projects" "$T/landing"
printf 'print(1)\n' > "$T/mac/home/code/shop/app.py"
printf '#!/bin/sh\necho run\n' > "$T/mac/home/code/shop/bin/run.sh"
chmod 755 "$T/mac/home/code/shop/bin/run.sh"
SHOP="$(P mac/home/code/shop)"
( export HOME="$(P mac/home)" USERPROFILE="$(P mac/home)" AHT_HOME="$(P mac/home/.aht)" \
         AHT_ROOT_CLAUDE="$(P mac/home/.claude/projects)"
  SENC=$(W encode "$SHOP")
  mkdir -p "$T/mac/home/.claude/projects/$SENC"
  printf '%s\n' "{\"type\":\"user\",\"cwd\":\"$(J "$SHOP")\",\"message\":{\"role\":\"user\",\"content\":\"tidy the heron module\"}}" \
    > "$T/mac/home/.claude/projects/$SENC/s1.jsonl"
  W tag "$SHOP" --apply >/dev/null ) || fail "the project on the test machine could not be registered"
printf '{"remotes": {"mac": {"root": "%s", "paths": "home"}}}' "$(J "$(P mac)")" > "$T/home/.aht/config.json"
# the test machine is this PC, so its paths are spelt the Windows way
# (\home\code\shop); a Mac or Linux machine there would say /home/code/shop
OUT=$(W bring --from mac --list --json)
has "$OUT" '"path": "[\\/]+home[\\/]+code[\\/]+shop"' "bring --list does not list the project on the test machine"
has "$OUT" '"can_bring": true' "bring --list says the project cannot be brought"
THERE=$(printf '%s\n' "$OUT" | sed -n 's/.*"path": "\([^"]*shop\)".*/\1/p' | head -n 1 | sed 's/\\\\/\\/g')
LAND="$(P landing/shop)"
OUT=$(W bring "$THERE" --from mac --here "$LAND" --json)
has "$OUT" '"applied": false' "bring without --apply did something"
has "$OUT" '"blockers": \[\]' "the bring dry run is blocked"
has "$OUT" '"there_path": "[\\/]+home[\\/]+code[\\/]+shop"' "the bring dry run names another folder there"
has "$OUT" '"files": 3' "the bring dry run does not count the project's three files (its id too)"
printf '%s' "$OUT" | grep -q Traceback && fail "bring crashed: $OUT"
[ ! -e "$T/landing/shop" ] || fail "the bring dry run made the folder here"
rm -f "$T/home/.aht/config.json"

echo "== the line to continue a brought project, as cmd.exe runs it =="
# a folder noted as brought here from a Mac: its session gets git's
# core.filemode=false, and the line to type sets it with cmd.exe's own set
# (sh's VAR=x and export do not run there)
mkdir -p "$T/home/.aht/remote"
printf '{"%s": {"uuid": "0123456789abcdef0123456789abcdef", "from": "mac", "kind": "brought", "system": "Darwin", "at": "2026-10-28T10:00:00"}}' \
  "$(J "$PAPER")" > "$T/home/.aht/remote/copies.json"
OUT=$(W resume-here "$PAPER" --print)
if [ -z "${AHT_SMOKE_POSIX:-}" ]; then
  has "$OUT" '^set "GIT_CONFIG_COUNT=1" && set "GIT_CONFIG_KEY_0=core.filemode" && set "GIT_CONFIG_VALUE_0=false" && cd /d ' \
    "resume-here --print on a PC does not set git's settings as cmd.exe does"
  printf '%s' "$OUT" | grep -q 'export ' && fail "resume-here --print on a PC uses sh's export: $OUT"
fi
rm -f "$T/home/.aht/remote/copies.json"

echo "== limits / sessions / tab names / workspace / checkup =="
has "$(W limits --json)" '"limits": \[\]' "limits failed"
has "$(W sessions --json)" '"Heron deploy"' "sessions lacks the title"
W tab-names --json >/dev/null || fail "tab-names failed"
W workspace --json >/dev/null || fail "workspace failed"
W checkup --json >/dev/null || fail "checkup failed"

echo "== a project's sessions / setup / getting started / autostart =="
has "$(W sessions "$PAPER" --json)" '"title": "Heron deploy"' "the project's sessions lack the title"
has "$(W setup --json)" '"projects"' "setup gave no plan"
W getting-started --json >/dev/null || fail "getting-started failed"
W autostart --json >/dev/null || fail "autostart failed"

echo "== aht's window: the doors, the page, one command =="
OUT=$(W window --selftest) || fail "the window selftest failed: $OUT"
has "$OUT" "WINDOW SELFTEST OK" "the window selftest did not pass"

echo "FEATURES SMOKE OK"
