#!/usr/bin/env python3
"""[7b] a codex-ONLY project (no marker, no dir store) is discovered."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)

print("\n[7b] a codex-ONLY project (no marker, no dir store) is discovered")
(roots / "projY").mkdir()
projY = os.path.realpath(str(roots / "projY"))
day = tools / "codex" / "2026" / "08" / "30"
day.mkdir(parents=True, exist_ok=True)
(day / "rollout-only.jsonl").write_text(
    json.dumps({"type": "session_meta", "payload": {"cwd": projY}}) + "\n")
r = run("adopt", "--json")
d = json.loads(r.stdout)
hit = next((a for a in d["planned"] if a["real"] == projY), None)
ck(hit is not None and hit["stores"] == ["codex"],
   "session-store cwd sweep planned the codex-only folder")

done()
