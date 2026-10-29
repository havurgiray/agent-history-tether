#!/usr/bin/env python3
"""[12] leveled logging: warnings/errors are tagged, filterable, counted."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)
from first_sections import (made_projA, tagged, moved_to_projB, hooked_to_projD,
                            conflict_projE)

# what earlier sections left: the [5] conflict in the log: projA tagged
# ([1]), moved to projB ([2]), to projD by the hook ([4]), then to projE,
# whose claude store was taken ([5]).  The copies of [3] and [3b] are left
# out: they log no warning or error, and no check here counts the projects
projA = made_projA()
uid = tagged(projA)
projB = moved_to_projB(projA)
projD = hooked_to_projD(projB)
projE = conflict_projE(projD)

print("\n[12] leveled logging: warnings/errors are tagged, filterable, counted")
r = run("logs", "--errors")
ck("[ERROR" in r.stdout and "CONFLICT" in r.stdout,
   "the [5] conflict was logged with an [ERROR] tag")
ck("[INFO" not in r.stdout, "--errors filters info lines out")
r = run("logs", "-n", "5")
ck(r.returncode == 0 and r.stdout.strip(), "plain logs tail works")
r = run("config", "--set", "log_level=nope", "--no-reload")
ck(r.returncode == 2 and "log_level" in r.stderr, "bad log_level rejected")
r = run("doctor")
ck("warnings/errors logged in the last 24h" in r.stdout,
   "doctor surfaces the recent-problems check")
r = run("status", "--json")
ck(json.loads(r.stdout)["log"]["recent_problems"] >= 1,
   "status counts recent problems")

done()
