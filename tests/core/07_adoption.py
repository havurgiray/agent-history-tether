#!/usr/bin/env python3
"""[7] adoption after total registry loss (store-corroborated)."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)
from first_sections import (made_projA, tagged, moved_to_projB, copied_to_projC,
                            parent_copied, hooked_to_projD, conflict_projE,
                            restored_projF)

# what earlier sections left: every project folder there was when [7] ran
# (it counts the adoptions planned among them): projA tagged ([1]), moved to
# projB ([2]), copied to projC ([3]) and to box/projC ([3b]), moved to projD
# by the hook ([4]), to projE ([5]), then backed up, moved to projF and
# restored there ([6])
projA = made_projA()
uid = tagged(projA)
projB = moved_to_projB(projA)
projC = copied_to_projC(projB)
nested = parent_copied(projC)
projD = hooked_to_projD(projB)
projE = conflict_projE(projD)
projF = restored_projF(projE)

print("\n[7] adoption after total registry loss (store-corroborated)")
os.remove(sb / ".aht" / "registry.json")
r = run("adopt", "--json")
d = json.loads(r.stdout)
ck(len(d["planned"]) >= 2, f"planned adoptions found ({len(d['planned'])})")
r = run("adopt", "--apply", "--json")
d = json.loads(r.stdout)
ck(len(d["adopted"]) >= 2, "adoption applied")
reg = json.loads((sb / ".aht" / "registry.json").read_text())
ck(any(e["real_path"] == projF for e in reg["projects"].values()),
   "moved+restored project re-adopted")

done()
