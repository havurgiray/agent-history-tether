#!/usr/bin/env python3
"""[3b] copying a PARENT folder duplicates the nested project too."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)
from first_sections import made_projA, tagged, moved_to_projB, copied_to_projC

# what earlier sections left: projA tagged ([1]), moved to projB ([2]),
# copied to projC with its stores duplicated and an id of its own ([3])
projA = made_projA()
tagged(projA)
projB = moved_to_projB(projA)
projC = copied_to_projC(projB)

print("\n[3b] copying a PARENT folder duplicates the nested project too")
(roots / "box").mkdir()
shutil.copytree(projC, str(roots / "box" / "projC"))
r = run("reconcile", "--notify", extra_env={"AHT_ASSUME": "Duplicate"})
d = json.loads(r.stdout)
nested = os.path.realpath(str(roots / "box" / "projC"))
ck(any(c["copy_path"] == nested for c in d["applied_copies"]),
   "nested copy inside a pasted parent was detected")
ck((tools / "claude" / enc(nested)).is_dir(),
   "nested copy got its own claude store at its own key")
ck((Path(nested) / ".aht" / ".project-id").read_text()
   != (Path(projC) / ".aht" / ".project-id").read_text(),
   "nested copy has a fresh uuid")

done()
