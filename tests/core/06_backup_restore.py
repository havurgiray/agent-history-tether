#!/usr/bin/env python3
"""[6] backup + restore across backends."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)
from first_sections import (made_projA, tagged, moved_to_projB, copied_to_projC,
                            parent_copied, hooked_to_projD, conflict_projE)

# what earlier sections left: every project the registry held when [6] ran
# (the backup counts what it snapshots among all of them): projA tagged
# ([1], uid), moved to projB ([2]), copied to projC ([3]) and to box/projC
# ([3b]), moved to projD by the hook ([4]), then to projE, whose claude
# store was taken ([5])
projA = made_projA()
uid = tagged(projA)
projB = moved_to_projB(projA)
projC = copied_to_projC(projB)
nested = parent_copied(projC)
projD = hooked_to_projD(projB)
projE = conflict_projE(projD)

print("\n[6] backup + restore across backends")
r = run("backup", "--json")
d = json.loads(r.stdout)
ck(d["counts"].get("backed-up", 0) >= 1, "backup pass snapshots")
snapdirs = [p for p in (sb / ".aht" / "backups").iterdir()
            if p.is_dir() and list(p.glob("*.zip"))]
ck(len(snapdirs) >= 1, "zips written")
meta = json.loads(sorted((sb / ".aht" / "backups" / uid)
                         .glob("*.meta.json"))[-1].read_text())
ck("gemini" in meta["backends"] and "codex" in meta["backends"]
   and "kimi" in meta["backends"],
   f"snapshot spans backends ({meta['backends']})")
r = run("backup", "--json")
ck(json.loads(r.stdout)["counts"].get("unchanged", 0) >= 1, "unchanged skip")

# lose two stores + move, restore via the travelling marker
shutil.rmtree(tools / "gemini" / sha(projE), ignore_errors=True)
old_claude = tools / "claude" / enc(projE)
shutil.move(projE, str(roots / "projF"))
projF = os.path.realpath(str(roots / "projF"))
r = run("restore", projF, "--apply", "--json")
d = json.loads(r.stdout)
ck(d["status"] == "restored", "restore applied")
ck((tools / "gemini" / sha(projF)).is_dir(), "gemini store restored at NEW key")
shutil.rmtree(tools / "kimi" / "sessions" / md5(projF), ignore_errors=True)
(tools / "kimi" / "user-history" / (md5(projF) + ".jsonl")).unlink()
r2 = run("restore", projF, "--apply", "--json")
ck((tools / "kimi" / "sessions" / md5(projF)).is_dir()
   and (tools / "kimi" / "user-history" / (md5(projF) + ".jsonl")).is_file(),
   "kimi sessions + companion restored at NEW key")
ck((tools / "claude" / enc(projF)).is_dir(), "claude store restored at NEW key")
ck(d["cwd_rewrites"] >= 1, "restore re-pointed session cwd values")
codex_files = list((tools / "codex").rglob("*.jsonl"))
ck(any(projF in f.read_text() for f in codex_files),
   "live codex session re-pointed at the restored folder's new path")

done()
