#!/usr/bin/env python3
"""[16g] handover between all three systems, at different paths --
phase7_suite of the handover suite.

This unit: files copied with rsync (when rsync 3 is missing, it says so
and runs nothing, as the original did).
The suite is in handover_kit.py."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)
import handover_kit as kit

if kit.start("rsync"):           # the skips, the mover line, AHT_TRANSFER
    print("\n[16g] handover between all three systems, at different paths")
    # what earlier sections left: handover_suite's setup of the stand-in
    # machine "box" (its stand-in tools, henv) and the config its first
    # lines set (box named, keep-awake off)
    h = kit.setup()
    kit.configure(h)
    try:
        kit.phase7_suite(h.stubs, h.henv, h.J)
    finally:
        kit.stop_stand_ins(h.bhome)
done()
