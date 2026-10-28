#!/usr/bin/env python3
"""The PC tray's notices and arrivals, on any OS: a click on a notice the
core handed over runs Continue here only for an arrival's notice, never for
a balloon the tray showed itself after it (Restart watcher, Settings,
Folder badges…), and only once; the menu's "<project> came from mac —
Continue here" items; and the core's words when `aht _arrival` refuses.
The functions are lifted out of windows/src/aht_tray.py (it needs Win32 to
import) and run with stand-ins.  Nothing is shown, nothing runs, and
nothing is written outside a throwaway folder.

    python windows/tests/aht_tray_test.py
"""
import ast
import json
import shutil
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "windows" / "src" / "aht_tray.py"
WANT = {"arrivals", "_arrival_run", "_continue_here", "_dismiss", "notice_clicked",
        "pump_notices", "balloon"}
tree = ast.parse(SRC.read_text(encoding="utf-8"))
mod = ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in WANT],
                 type_ignores=[])

fails = []


def ck(ok, what):
    print(("  ok   " if ok else "  FAIL ") + what)
    if not ok:
        fails.append(what)


T = Path(tempfile.mkdtemp(prefix="aht-tray-test-"))
shown, clis, boxes, opened, warned = [], [], [], [], []
answer = [0, None]                       # _arrival's exit code and error


def notify(_msg, nid):
    if getattr(nid, "szInfoTitle", ""):
        shown.append((nid.szInfoTitle, nid.szInfo))
    return 1


def run_cli(*a):
    clis.append(a)
    code, err = answer
    return types.SimpleNamespace(returncode=code, stderr="",
                                 stdout=json.dumps({"name": a[-2], "applied": not code, "error": err}))


ns = {
    "json": json,
    "aht": types.SimpleNamespace(warn=warned.append, read_arrivals=lambda: []),
    "shell32": types.SimpleNamespace(Shell_NotifyIconW=notify),
    "ctypes": types.SimpleNamespace(byref=lambda x: x, get_last_error=lambda: 0),
    "_nid": lambda flags=0: types.SimpleNamespace(flags=flags, szInfo="", szInfoTitle="", dwInfoFlags=0),
    "NIF_INFO": 0x10, "NIM_MODIFY": 1, "NIIF_INFO": 1,
    "LAST_NOTICE": [None], "QUEUE_AT": [0],
    "NOTICE_QUEUE": T / "run" / "tray-notices.jsonl", "TRAY_ALIVE": T / "run" / "tray-alive",
    "_run_cli": run_cli, "_in_thread": lambda fn: fn(),
    "msgbox": lambda t, m, *a: boxes.append((t, m)),
    "act_open_window": lambda *a, **k: opened.append(a),
}
exec(compile(mod, str(SRC), "exec"), ns)
LAST = ns["LAST_NOTICE"]


def queue(*notices):
    """The core hands notices to the tray (winlayer.notify_user)."""
    ns["NOTICE_QUEUE"].parent.mkdir(parents=True, exist_ok=True)
    with open(ns["NOTICE_QUEUE"], "a", encoding="utf-8") as fh:
        for n in notices:
            fh.write(json.dumps(n) + "\n")


def arrival(name, proj="shop", frm="mac"):
    return {"kind": "arrival", "title": f"{proj} came from {frm}",
            "message": f"Continue here opens Claude Code in {proj}. Nothing runs until you type.",
            "info": {"kind": "arrival", "name": name, "project": "C:\\Users\\me\\code\\" + proj,
                     "from": frm, "session": "s-1", "action": "Continue here"}}


WAITING = {"kind": "waiting", "title": "api waits for you", "message": "Claude Code asks a question.",
           "info": {"kind": "waiting", "project": "C:\\Users\\me\\code\\api"}}
try:
    # ---- an arrival's notice: its click is Continue here, once ----------------------
    queue(arrival("aht-shop-1a2b3c"))
    ns["pump_notices"]()
    ck(shown[-1] == ("shop came from mac", "Continue here opens Claude Code in shop. Nothing runs until you type.")
       and (T / "run" / "tray-alive").exists(), f"the arrival's notice is shown ({shown[-1] if shown else None})")
    ck(isinstance(LAST[0], dict) and LAST[0].get("name") == "aht-shop-1a2b3c",
       "…and its info is kept for a click (set after balloon(), which clears it)")
    ns["notice_clicked"]()
    ck(clis == [("_arrival", "--continue", "aht-shop-1a2b3c", "--json")] and not opened and not boxes,
       f"a click on it: aht _arrival --continue <name> ({clis})")
    ns["notice_clicked"]()
    ck(len(clis) == 1 and len(opened) == 1,
       "a second click on it: aht's window, no second Continue here")

    # ---- the stray click: the tray's own balloon after an arrival's notice -----------
    queue(arrival("aht-api-9f8e7d", "api", "box"))
    ns["pump_notices"]()
    ck(LAST[0] and LAST[0].get("name") == "aht-api-9f8e7d", "another arrival's notice is shown")
    for title, msg in [("aht", "The watcher was restarted."), ("aht", "Settings saved."),
                       ("Folder badges", "Folder badges are on.")]:
        n0, o0 = len(clis), len(opened)
        ns["balloon"](title, msg)
        ck(shown[-1] == (title, msg) and LAST[0] is None, f"the tray's own balloon “{msg}” forgets the arrival's info")
        ns["notice_clicked"]()
        ck(len(clis) == n0 and len(opened) == o0 + 1,
           f"…a click on it opens aht's window, never Continue here ({clis[n0:]})")

    # ---- several notices at once: the last one shown is the one a click answers ------
    queue(arrival("aht-web-0a0b0c", "web"), WAITING)
    ns["pump_notices"]()
    ck(shown[-1][0] == "api waits for you" and LAST[0] == WAITING["info"],
       "an arrival, then a waiting session: the click answers the waiting one")
    n0, o0 = len(clis), len(opened)
    ns["notice_clicked"]()
    ck(len(clis) == n0 and len(opened) == o0 + 1, "…it opens aht's window")
    queue(WAITING, arrival("aht-web-0a0b0c", "web"))
    ns["pump_notices"]()
    ns["notice_clicked"]()
    ck(clis[-1] == ("_arrival", "--continue", "aht-web-0a0b0c", "--json"), "a waiting session, then an arrival: Continue here")
    queue({"title": "aht 0.14.0 is out", "message": "Update with winget."})
    ns["pump_notices"]()
    ck(LAST[0] is None, "a notice without info: a click opens the window")

    # ---- the core refuses: its words, plainly ---------------------------------------
    said = ("shop was continued here already, at 14:10: Claude Code is open in its console. "
            "aht _arrival --continue aht-shop-1a2b3c --again opens it once more")
    answer[:] = [1, said]
    ns["_continue_here"]("aht-shop-1a2b3c")()
    ck(boxes[-1:] == [("Continue here did not work", said)],
       f"an already continued arrival: the core's refusal, in its words ({boxes[-1:] or None})")
    answer[:] = [1, None]
    clis_before = len(clis)
    ns["_dismiss"]("aht-gone-000000")()
    ck(clis[clis_before:] == [("_arrival", "--dismiss", "aht-gone-000000", "--json")]
       and boxes[-1] == ("The offer was not dismissed", "aht ended with 1"),
       f"no error in its JSON: how aht ended, never the JSON itself ({boxes[-1]})")
    answer[:] = [0, None]
    n0 = len(boxes)
    ns["_continue_here"]("aht-shop-1a2b3c")()
    ck(len(boxes) == n0, "it went: no message")

    # ---- the menu: "<project> came from mac — Continue here" ------------------------
    rows = [{"name": "aht-shop-1a2b3c", "project": "shop", "from": "mac", "text": "shop came from mac",
             "action": "Continue here", "continued": None},
            {"name": "aht-old-000000", "project": "old", "from": "mac", "continued": 1761651000.0},
            {"name": "n1", "project": "web", "from": "studio"}, "not a record", {"text": "no name"}]
    ck(ns["arrivals"](rows) == [("aht-shop-1a2b3c", "shop came from mac — Continue here"),
                                ("n1", "web came from studio — Continue here")],
       f"the menu offers what was not continued yet ({ns['arrivals'](rows)})")
    ns["aht"].read_arrivals = lambda: (_ for _ in ()).throw(OSError("unreadable"))
    ck(ns["arrivals"]() == [], "the core's reader fails: no items, no error")
    fx = ROOT / "tests" / "fixtures" / "phase9" / "arrival.json"
    if fx.exists():
        one = json.loads(fx.read_text(encoding="utf-8"))
        got = ns["arrivals"]([one])
        ck(len(got) == 1 and got[0][0] == one["name"] and got[0][1].endswith(" — Continue here"),
           f"the core's sample (arrival.json): text — action ({got})")
    else:
        print("  --   the core's sample arrival.json: not there yet")
    ck(not warned, f"Windows showed every balloon ({warned})")
finally:
    shutil.rmtree(T, ignore_errors=True)

print("TRAY TEST " + ("OK" if not fails else f"FAIL ({len(fails)})"))
sys.exit(1 if fails else 0)
