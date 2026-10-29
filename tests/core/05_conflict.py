#!/usr/bin/env python3
"""[5] conflict: an occupied target is refused, others proceed."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)
from first_sections import (made_projA, tagged, moved_to_projB, copied_to_projC,
                            parent_copied, hooked_to_projD)

# what earlier sections left: every project the registry held when [5] ran
# ("move surfaced" counts the moves among all of them): projA tagged ([1],
# uid), moved to projB ([2]), copied to projC ([3]) and to box/projC ([3b]),
# then moved to projD and relinked by the hook ([4])
projA = made_projA()
uid = tagged(projA)
projB = moved_to_projB(projA)
projC = copied_to_projC(projB)
nested = parent_copied(projC)
projD = hooked_to_projD(projB)

print("\n[5] conflict: an occupied target is refused, others proceed")
projE = os.path.realpath(str(roots / "projE"))
(tools / "claude" / enc(projE)).mkdir()          # squatter on the claude target
(tools / "claude" / enc(projE) / "other.jsonl").write_text("{}")
shutil.move(projD, projE)
r = run("reconcile", "--apply")
d = json.loads(r.stdout)
allm = d["applied_moves"] + d["conflicts"]
ck(len(allm) == 1, "move surfaced")
st = allm[0]["stores"]
ck(str(st.get("claude", "")).startswith("conflict"), "claude target refused (occupied)")
ck(st.get("gemini") == "renamed", "gemini still relinked")
ck((tools / "claude" / enc(projE) / "other.jsonl").is_file(),
   "squatter store untouched")

done()
