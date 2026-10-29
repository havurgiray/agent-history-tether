#!/usr/bin/env python3
"""Run aht as `python aht.py` does, from its compiled cache: a script is
compiled whole on every start (0.17 s for aht.py), an imported module is
read from __pycache__ (0.05 s).  The tests start aht thousands of times.
On Windows through the Windows entry point, which the core needs there
(it brings fcntl), as aht runs itself from a checkout there."""
import os
import runpy
import sys

repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if os.name == "nt":
    sys.argv[0] = os.path.join(repo, "windows", "src", "aht_main.py")
    sys.path[0] = os.path.dirname(sys.argv[0])
    runpy.run_path(sys.argv[0], run_name="__main__")
else:
    sys.path[0] = repo
    import aht
    sys.exit(aht.main())
