#!/usr/bin/env python3
"""[16] handover: on to another machine, and back -- the first part of the
handover suite's own checks: a handover and back with its safety rules,
the mirror, a newer agent CLI there.  [16] goes on in
16_handover_machines_aht.py, 16_handover_unfinished_aht.py and
16_handover_far_end_aht.py.

This unit: files copied with aht's own copy.
The suite is in handover_kit.py."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)
import handover_kit as kit

print("\n[16] handover: on to another machine, and back")
if kit.start("aht"):           # the skips, the mover line, AHT_TRANSFER
    h = kit.setup()                 # the stand-in machine "box"
    try:
        kit.own_checks(h)
    finally:
        kit.stop_stand_ins(h.bhome)
done()
