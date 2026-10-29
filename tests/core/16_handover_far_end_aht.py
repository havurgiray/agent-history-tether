#!/usr/bin/env python3
"""[16] handover: on to another machine, and back -- phase1_suite, the rest:
a handover cut off at the start, set-asides there (file-history and
plans, a case rename, a packed repository, the rule), a sandbox on a real
machine, a Windows far end.

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
        kit.phase1_far_end(h.box, h.bhome, h.stubs, h.henv, h.hrun, h.J, h.hook,
                           h.project_row)
    finally:
        kit.stop_stand_ins(h.bhome)
done()
