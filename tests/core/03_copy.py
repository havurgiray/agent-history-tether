#!/usr/bin/env python3
"""[3] copy -> fresh identity + duplicated dir stores."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)
from first_sections import made_projA, tagged, moved_to_projB

# what earlier sections left: projA tagged ([1]), moved to projB and
# reconciled ([2]): the registry's only project
projA = made_projA()
tagged(projA)
projB = moved_to_projB(projA)

print("\n[3] copy -> fresh identity + duplicated dir stores")
shutil.copytree(projB, str(roots / "projC"))
projC = os.path.realpath(str(roots / "projC"))
r = run("reconcile", "--notify", extra_env={"AHT_ASSUME": "Duplicate"})
d = json.loads(r.stdout)
ck(len(d["applied_copies"]) == 1, "copy detected and resolved")
ck((tools / "claude" / enc(projC)).is_dir(), "claude history duplicated for the copy")
ck((tools / "gemini" / sha(projC)).is_dir(), "gemini history duplicated for the copy")
idA = (Path(projB) / ".aht" / ".project-id").read_text()
idC = (Path(projC) / ".aht" / ".project-id").read_text()
ck(idA != idC, "copy has a fresh uuid")

done()
