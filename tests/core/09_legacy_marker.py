#!/usr/bin/env python3
"""[9] a legacy .claude/.project-id marker is honoured."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)

print("\n[9] a legacy .claude/.project-id marker is honoured")
(roots / "legacy").mkdir()
legacy = os.path.realpath(str(roots / "legacy"))
(Path(legacy) / ".claude").mkdir()
(Path(legacy) / ".claude" / ".project-id").write_text("deadbeef" * 4 + "\n")
r = run("adopt", "--json")
d = json.loads(r.stdout)
ck(any(a["real"] == legacy for a in d["planned"]),
   "folder with only a .claude marker is planned for adoption")

done()
