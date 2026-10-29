#!/usr/bin/env python3
"""[16] handover: on to another machine, and back -- the rest of the handover
suite's own checks: which session goes on, --status-file, the project
list, a path listed twice, several machines, discover, backups there,
--task, the board, the night shift, mirror --all.

This unit: files copied with rsync (when rsync 3 is missing, it says so
and runs nothing, as the original did).
The suite is in handover_kit.py."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)
import handover_kit as kit

print("\n[16] handover: on to another machine, and back")
if kit.start("rsync"):           # the skips, the mover line, AHT_TRANSFER
    # what earlier sections left: handover_suite's setup of the stand-in
    # machine "box" (its stand-in tools, henv) and the config its first
    # lines set (box named, keep-awake off)
    h = kit.setup()
    kit.configure(h)
    try:
        kit.own_checks_more(h)
    finally:
        kit.stop_stand_ins(h.bhome)
done()
