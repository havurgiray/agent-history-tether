#!/usr/bin/env python3
"""[4] hook backstop: transcript-authoritative claude + generic backends."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)
from first_sections import made_projA, tagged, moved_to_projB

# what earlier sections left: projA tagged ([1], uid), moved to projB and
# reconciled ([2]).  The copies [3] and [3b] made are left out: the hook
# here deals with uid's folder alone
projA = made_projA()
uid = tagged(projA)
projB = moved_to_projB(projA)

print("\n[4] hook backstop: transcript-authoritative claude + generic backends")
shutil.move(projB, str(roots / "projD"))
projD = os.path.realpath(str(roots / "projD"))
hook_in = json.dumps({"cwd": projD,
                      "transcript_path": str(tools / "claude" / enc(projD) / "t.jsonl")})
r = subprocess.run([PY, LAUNCH, "hook"], env=env, input=hook_in,
                   capture_output=True, text=True)
ck(r.returncode == 0, "hook ran")
ck((tools / "claude" / enc(projD)).is_dir(), "hook relinked the claude store")
ck((tools / "gemini" / sha(projD)).is_dir(), "hook relinked the gemini store too")
reg = json.loads((sb / ".aht" / "registry.json").read_text())
ck(reg["projects"][uid]["real_path"] == projD, "registry re-pointed by the hook")

done()
