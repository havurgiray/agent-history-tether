#!/usr/bin/env python3
"""Where aht.exe's entry point (windows/src/aht_main.py) sends each command,
on any OS, with stand-ins for the Windows layer, the core's CLI and the
window's folder chooser: `_agent` and `_core` go to the core without the
Windows layer (they answer another aht, not a person); `_pick-folder` goes
to aht_web.pick_folder_here, sharp on a scaled display and without the
layer; every other command sets the layer up first, and its own commands
(install, watch, uninstall) go to it.  Nothing is shown and nothing is
written outside a throwaway folder.

    python windows/tests/aht_main_test.py
"""
import ast
import os
import shutil
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "windows" / "src"))
sys.path.insert(0, str(ROOT))
if os.name == "nt":
    import win_fcntl
    sys.modules.setdefault("fcntl", win_fcntl)

T = Path(tempfile.mkdtemp(prefix="aht-main-test-"))
os.environ["AHT_HOME"] = str(T / "home" / ".aht")
os.environ["LOCALAPPDATA"] = str(T / "localappdata")

calls = []
layer = types.ModuleType("winlayer")
layer.activate = lambda: calls.append(("activate",))
layer.enable_dpi_awareness = lambda: calls.append(("dpi",))
layer.COMMANDS = {"install": lambda a: calls.append(("install", a)) or 0}
web = types.ModuleType("aht_web")
web.pick_folder_here = lambda a: calls.append(("pick", a)) or 0
sys.modules["winlayer"] = layer
sys.modules["aht_web"] = web

import aht_main  # noqa: E402

aht_main.aht.main = lambda a: calls.append(("core", a)) or 0

FAILS = []
def ck(c, m):
    print(("  PASS " if c else "  FAIL ") + m)
    if not c:
        FAILS.append(m)

def run(argv, system="nt"):
    calls.clear()
    aht_main.os = types.SimpleNamespace(name=system, environ=os.environ)
    try:
        code = aht_main.main(argv)
    finally:
        aht_main.os = os
    return code, list(calls)

try:
    # the stand-in's name is the window's own: aht_web.py has that function
    real = ast.parse((ROOT / "aht_web.py").read_text(encoding="utf-8"))
    ck(any(isinstance(n, ast.FunctionDef) and n.name == "pick_folder_here" for n in real.body),
       "aht_web.py has pick_folder_here")
    code, got = run(["_agent"])
    ck(got == [("core", ["_agent"])], f"_agent goes to the core without the Windows layer ({got})")
    code, got = run(["_core", "--id"])
    ck(got == [("core", ["_core", "--id"])], f"_core --id too ({got})")
    code, got = run(["status", "--json"])
    ck(got == [("activate",), ("core", ["status", "--json"])],
       f"any other command sets the layer up first ({got})")
    code, got = run([])
    ck(got == [("activate",), ("core", [])], f"so does no command at all ({got})")
    code, got = run(["install"])
    ck(got == [("activate",), ("install", [])], f"install goes to the layer ({got})")
    code, got = run(["_pick-folder", "Pick one"])
    ck(code == 0 and got == [("dpi",), ("pick", ["Pick one"])],
       f"_pick-folder goes to aht_web.pick_folder_here, DPI-aware, without the layer ({got})")
    web.pick_folder_here = lambda a: 3
    code, got = run(["_pick-folder"])
    ck(code == 3, "and its exit code is aht's")
    code, got = run(["install"], system="posix")
    ck(code == 2 and got == [], f"off Windows, install is refused ({got})")
    code, got = run(["_agent"], system="posix")
    ck(got == [("core", ["_agent"])], f"and _agent still reaches the core ({got})")
finally:
    shutil.rmtree(T, ignore_errors=True)

print("\nAHT_MAIN RESULT:", "ALL PASS" if not FAILS else "%d FAIL" % len(FAILS))
for f in FAILS:
    print("  -", f)
sys.exit(1 if FAILS else 0)
