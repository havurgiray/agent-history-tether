#!/usr/bin/env python3
"""[2] move -> reconcile relinks every backend."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)
from first_sections import made_projA, tagged

# what earlier sections left: projA with every agent's store, tagged ([1]),
# the registry's only project
projA = made_projA()
tagged(projA)

print("\n[2] move -> reconcile relinks every backend")
shutil.move(projA, str(roots / "projB"))
projB = os.path.realpath(str(roots / "projB"))
r = run("reconcile", "--apply")
d = json.loads(r.stdout)
ck(len(d["applied_moves"]) == 1, "one move applied")
st = d["applied_moves"][0]["stores"]
ck(st.get("claude") == "renamed", f"claude store renamed ({st.get('claude')})")
ck(st.get("gemini") == "renamed", f"gemini store renamed ({st.get('gemini')})")
ck(st.get("cursor") == "renamed", f"cursor store renamed ({st.get('cursor')})")
ck(st.get("opencode") == "renamed", "opencode store renamed")
ck(str(st.get("codex", "")).startswith("rewrote-"), f"codex cwd rewritten ({st.get('codex')})")
ck(str(st.get("copilot", "")).startswith("rewrote-"), "copilot cwd rewritten")
ck(st.get("kimi") == "renamed", "kimi sessions dir renamed")
ck((tools / "kimi" / "sessions" / md5(projB) / "sess-uuid-1" / "wire.jsonl").is_file(),
   "kimi sessions at new md5 key")
ck((tools / "kimi" / "user-history" / (md5(projB) + ".jsonl")).is_file()
   and not (tools / "kimi" / "user-history" / (md5(projA) + ".jsonl")).exists(),
   "kimi user-history companion renamed along")
ck((tools / "claude" / enc(projB)).is_dir(), "claude dir at new key")
ck((tools / "gemini" / sha(projB)).is_dir(), "gemini dir at new sha256 key")
ck((tools / "cursor" / md5(projB)).is_dir(), "cursor dir at new md5 key")
codex_files = list((tools / "codex").rglob("*.jsonl"))
ck(any(projB in f.read_text() for f in codex_files), "codex session points at new path")
ck(not any(projA in f.read_text() for f in codex_files), "old path gone from codex meta")
rewr = list((sb / ".aht" / "backups").rglob("rewrites/*/**/*.jsonl"))
ck(any(projA in f.read_text() for f in rewr),
   "pre-rewrite backup preserves the original codex session")

done()
