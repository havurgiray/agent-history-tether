#!/usr/bin/env python3
"""[1] tag detects every backend's store."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)
from first_sections import made_projA

# what earlier sections left: projA with a file and every agent's store (the
# shared setup before [1])
projA = made_projA()

print("\n[1] tag detects every backend's store")
r = run("tag", projA, "--apply")
ck(r.returncode == 0 and "tagged:" in r.stdout, "tag applied")
for name in ("claude", "gemini", "cursor", "opencode", "kimi"):
    ck(name in r.stdout, f"store detected: {name}")
reg = json.loads((sb / ".aht" / "registry.json").read_text())
uid = list(reg["projects"])[0]
ck((Path(projA) / ".aht" / ".project-id").read_text().strip() == uid,
   "marker written and matches registry")

done()
