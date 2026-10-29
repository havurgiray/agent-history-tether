#!/usr/bin/env python3
"""[8] surfaces: keys / status / doctor / projects."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)
from first_sections import (made_projA, tagged, moved_to_projB, hooked_to_projD,
                            conflict_projE, restored_projF)

# what earlier sections left: projF with its stores restored at its keys:
# projA tagged ([1]), moved to projB ([2]), to projD by the hook ([4]), to
# projE ([5]), then backed up, moved to projF and restored there ([6]).
# The copies of [3] and [3b] and the adoption of [7] are left out: no check
# here counts the projects, and keys reads the stores, not the registry
projA = made_projA()
uid = tagged(projA)
projB = moved_to_projB(projA)
projD = hooked_to_projD(projB)
projE = conflict_projE(projD)
projF = restored_projF(projE)

print("\n[8] surfaces: keys / status / doctor / projects")
r = run("keys", projF)
d = json.loads(r.stdout)
ck(d["backends"]["gemini"]["keys"][0] == sha(projF), "keys shows gemini sha256")
ck(d["backends"]["claude"]["exists"], "keys shows claude store exists")
r = run("status", "--json")
d = json.loads(r.stdout)
ck(any(b["name"] == "codex" and b["available"] for b in d["backends"]),
   "status lists backend availability")
ck(run("doctor").returncode == 0, "doctor runs")
ck(run("projects").returncode == 0, "projects runs")

done()
