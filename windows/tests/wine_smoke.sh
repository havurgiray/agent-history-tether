#!/bin/sh
# End-to-end smoke test of the built aht.exe, run INSIDE a wine container
# (build.sh invokes this).  Every backend root is a throwaway fake via the
# AHT_ROOT_* overrides, so it never touches real agent data:
#   tag -> move+reconcile (claude+gemini dir renames, codex cwd rewrite) ->
#   hook -> badges -> backup/restore -> tray selftest
set -e

EXE="$1"
[ -n "$EXE" ] || { echo "usage: wine_smoke.sh /path/to/aht.exe"; exit 2; }
export WINEDEBUG=-all

W() { wine "$EXE" "$@" | tr -d '\r'; }
fail() { echo "SMOKE FAIL: $*"; exit 1; }

T=/tmp/aht-smoke
rm -rf "$T"
mkdir -p "$T/home/.aht" "$T/roots/projA/src" \
         "$T/tools/claude" "$T/tools/gemini" "$T/tools/codex/2026/08/29"

export AHT_HOME='Z:\tmp\aht-smoke\home\.aht'
export AHT_ROOTS='Z:\tmp\aht-smoke\roots'
export AHT_ROOT_CLAUDE='Z:\tmp\aht-smoke\tools\claude'
export AHT_ROOT_GEMINI='Z:\tmp\aht-smoke\tools\gemini'
export AHT_ROOT_CURSOR='Z:\tmp\aht-smoke\tools\nope'
export AHT_ROOT_OPENCODE='Z:\tmp\aht-smoke\tools\nope'
export AHT_ROOT_CODEX='Z:\tmp\aht-smoke\tools\codex'
export AHT_ROOT_COPILOT='Z:\tmp\aht-smoke\tools\nope'
export AHT_ROOT_KIMI='Z:\tmp\aht-smoke\tools\nope'
export AHT_NO_NOTIFY=1 AHT_NO_ICONS=1 AHT_NO_BACKUP=1

PROJA='Z:\tmp\aht-smoke\roots\projA'
PROJB='Z:\tmp\aht-smoke\roots\projB'

echo "== version =="
W version

echo "== encode / keys =="
ENC_TEST=$(W encode 'C:\Users\test\My Project')
[ "$ENC_TEST" = "C--Users-test-My-Project" ] || fail "encode gave: $ENC_TEST"

# fake stores for projA: claude dir (encoded), gemini dir (sha256 via `keys`),
# codex rollout with an embedded cwd
ENCA=$(W encode "$PROJA")
mkdir -p "$T/tools/claude/$ENCA"
printf '%s\n' '{"cwd":"Z:\\tmp\\aht-smoke\\roots\\projA"}' \
  > "$T/tools/claude/$ENCA/s1.jsonl"
SHAA=$(W keys "$PROJA" | grep -A4 '"gemini"' | grep -o '[0-9a-f]\{64\}' | head -1)
[ -n "$SHAA" ] || fail "could not read gemini key from aht keys"
mkdir -p "$T/tools/gemini/$SHAA"
echo '{"g":1}' > "$T/tools/gemini/$SHAA/chat.json"
printf '%s\n' '{"type":"session_meta","payload":{"cwd":"Z:\\tmp\\aht-smoke\\roots\\projA","id":"x"}}' \
  > "$T/tools/codex/2026/08/29/rollout-1.jsonl"

echo "== tag detects stores =="
TAG=$(W tag "$PROJA" --apply)
printf '%s\n' "$TAG"
printf '%s\n' "$TAG" | grep -q '^tagged:' || fail "tag did not apply"
printf '%s\n' "$TAG" | grep -q "claude" || fail "claude store not detected"
printf '%s\n' "$TAG" | grep -q "gemini" || fail "gemini store not detected"
[ -f "$T/roots/projA/.aht/.project-id" ] || fail "marker not written"

echo "== move + reconcile relinks every backend =="
mv "$T/roots/projA" "$T/roots/projB"
AHT_ASSUME=Relink W reconcile --notify > "$T/rec.json"
grep -q '"claude": "renamed"' "$T/rec.json" || fail "claude store not renamed"
grep -q '"gemini": "renamed"' "$T/rec.json" || fail "gemini store not renamed"
grep -q '"codex": "rewrote-' "$T/rec.json" || fail "codex cwd not rewritten"
ENCB=$(W encode "$PROJB")
[ -d "$T/tools/claude/$ENCB" ] || fail "claude dir not at new key"
grep -q 'projB' "$T/tools/codex/2026/08/29/rollout-1.jsonl" || fail "codex meta not re-pointed"
ls "$T/home/.aht/backups" > /dev/null 2>&1 || fail "pre-rewrite backup dir missing"

echo "== hook backstop =="
mv "$T/roots/projB" "$T/roots/projC"
printf '%s\n' '{"cwd":"Z:\\tmp\\aht-smoke\\roots\\projC"}' | wine "$EXE" hook
ENCC=$(W encode 'Z:\tmp\aht-smoke\roots\projC')
[ -d "$T/tools/claude/$ENCC" ] || fail "hook did not relink claude store"
grep -q 'projC' "$T/home/.aht/registry.json" || fail "registry not re-pointed"

echo "== status / doctor / projects / config =="
W status --json > "$T/status.json"
grep -q '"name": "gemini"' "$T/status.json" || fail "status lacks backend table"
grep -q '"tracked": 1' "$T/status.json" || fail "expected 1 tracked project"
W doctor > /dev/null || fail "doctor crashed"
W logs > /dev/null || fail "logs crashed"
W projects > /dev/null || fail "projects crashed"
W backends | grep -q 'kimi' || fail "backends page missing"
W config --set move_policy=apply --no-reload > /dev/null
W config --json | grep -q '"move_policy": "apply"' || fail "config set/get"

echo "== folder badges (desktop.ini + composited ico) =="
env AHT_NO_ICONS= wine "$EXE" icons --refresh > /dev/null || fail "icons --refresh crashed"
[ -f "$T/roots/projC/.aht/aht-badge.ico" ] || fail "badge ico not written"
[ -f "$T/roots/projC/desktop.ini" ] || fail "desktop.ini not written"
grep -q 'aht-badge.ico' "$T/roots/projC/desktop.ini" || fail "IconResource not set"

echo "== backup + restore across backends =="
W backup --json > "$T/bk.json"
grep -q '"backed-up": 1' "$T/bk.json" || fail "backup did not snapshot"
grep -q '"codex"' "$T/home/.aht/backups"/*/*.meta.json || fail "snapshot does not span codex"
rm -rf "$T/tools/claude/$ENCC"
mv "$T/roots/projC" "$T/roots/projD"
W restore 'Z:\tmp\aht-smoke\roots\projD' --apply --json > "$T/rs.json"
grep -q '"status": "restored"' "$T/rs.json" || fail "restore did not apply"
ENCD=$(W encode 'Z:\tmp\aht-smoke\roots\projD')
[ -f "$T/tools/claude/$ENCD/s1.jsonl" ] || fail "claude history not restored at new key"
W backup --list | grep -qi 'projD' || fail "backup --list empty"

echo "== copy-paste: the Duplicate option =="
cp -r "$T/roots/projD" "$T/roots/projCopy"
AHT_ASSUME=Duplicate W reconcile --notify > "$T/copy.json"
grep -q 'projCopy' "$T/copy.json" || fail "copy not detected"
ENCP=$(W encode 'Z:\tmp\aht-smoke\roots\projCopy')
[ -d "$T/tools/claude/$ENCP" ] || fail "claude history not duplicated for the copy"
A=$(cat "$T/roots/projD/.aht/.project-id")
B=$(cat "$T/roots/projCopy/.aht/.project-id")
[ "$A" != "$B" ] || fail "copy did not get a fresh id"

echo "== copy-paste a PARENT with a nested tethered project =="
mkdir "$T/roots/box"
cp -r "$T/roots/projD" "$T/roots/box/projD"
AHT_ASSUME=Duplicate W reconcile --notify > "$T/copy2.json"
ENCN=$(W encode 'Z:\tmp\aht-smoke\roots\box\projD')
[ -d "$T/tools/claude/$ENCN" ] || fail "nested parent-copy not duplicated"
[ -f "$T/roots/box/projD/.aht/.project-id" ] || fail "nested copy has no marker"

TRAY="$(dirname "$EXE")/aht-tray.exe"
if [ -f "$TRAY" ]; then
  echo "== tray selftest (headless) =="
  wine "$TRAY" --selftest || fail "tray selftest exited nonzero"
fi

echo ""
echo "SMOKE OK — all checks passed"
