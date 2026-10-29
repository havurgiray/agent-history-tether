#!/usr/bin/env python3
"""[16] handover: on to another machine, and back -- phase1_suite, the part
that compares the JSON with the front-ends' samples: an unfinished
handover is finished or undone, Release (with Keep in sync on, too),
offsite backups that only add, a machine that does not answer.

This unit: files copied with aht's own copy.
The suite is in handover_kit.py."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)
import handover_kit as kit

print("\n[16] handover: on to another machine, and back")
if kit.start("aht"):           # the skips, the mover line, AHT_TRANSFER
    # what earlier sections left: handover_suite's setup of the stand-in
    # machine "box" (its stand-in tools, henv) and the config its first
    # lines set (box named, keep-awake off)
    h = kit.setup()
    kit.configure(h)
    try:
        kit.phase1_unfinished(h.box, h.bhome, h.stubs, h.henv, h.hrun, h.J, h.hook,
                              h.project_row)
    finally:
        kit.stop_stand_ins(h.bhome)
done()
