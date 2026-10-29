#!/usr/bin/env python3
"""The PC tray's notices and arrivals, on any OS: a click on a notice the
core handed over runs Continue here only for an arrival's notice, never for
a balloon the tray showed itself after it (Restart watcher, Settings,
Folder badges…), and only once; the menu's "<project> came from mac —
Continue here" items; the core's words when `aht _arrival` refuses; the
"Projects brought here" list (a PC's project only while that PC answers);
how winlayer.notify_user hands a notice over (the core's queue_notice,
which starts the file over past 500 lines, or a plain append) and that the
tray then shows only the new one; and watcher_owner=none: no logon entry
for the watcher, a running one stopped (its stop event, else the pid it
wrote), no watcher started by the tray, install or a stale entry, and the
entry back with "agent".  The functions are lifted out of
windows/src/aht_tray.py and winlayer.py (they need Win32 to import), and
pc_answers out of aht.py, and run with stand-ins.  Nothing is shown, nothing runs, and
nothing is written outside a throwaway folder.

    python windows/tests/aht_tray_test.py
"""
import argparse
import ast
import json
import os
import shutil
import sys
import tempfile
import time
import types
from pathlib import Path

# a Windows console or pipe in cp1252 cannot print every character a
# check names (✓, →): print them escaped there rather than stop
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="backslashreplace")

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "windows" / "src" / "aht_tray.py"
WANT = {"arrivals", "_arrival_run", "_continue_here", "_dismiss", "notice_clicked",
        "pump_notices", "balloon", "brought_here"}
tree = ast.parse(SRC.read_text(encoding="utf-8"))
mod = ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in WANT],
                 type_ignores=[])

fails = []


def ck(ok, what):
    print(("  ok   " if ok else "  FAIL ") + what)
    if not ok:
        fails.append(what)


T = Path(tempfile.mkdtemp(prefix="aht-tray-test-"))
shown, clis, boxes, opened, warned, trayed = [], [], [], [], [], []
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
    "tray_log": lambda what, exc=None, level="error": trayed.append(f"{what}: {type(exc).__name__}" if exc else what),
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
    ck(ns["arrivals"]() == [] and trayed[-1:] == ["the menu could not read the arrivals: OSError"],
       f"the core's reader fails: no items, no error box; noted in aht's log ({trayed[-1:]})")
    fx = ROOT / "tests" / "fixtures" / "phase9" / "arrival.json"
    if fx.exists():
        one = json.loads(fx.read_text(encoding="utf-8"))
        got = ns["arrivals"]([one])
        ck(len(got) == 1 and got[0][0] == one["name"] and got[0][1].endswith(" — Continue here"),
           f"the core's sample (arrival.json): text — action ({got})")
    else:
        print("  --   the core's sample arrival.json: not there yet")
    # ---- Projects brought here: a PC's project only while that PC answers -------------
    core = ast.parse((ROOT / "aht.py").read_text(encoding="utf-8"))
    cns = {}
    exec(compile(ast.Module(body=[n for n in core.body if (isinstance(n, ast.FunctionDef) and n.name == "pc_answers")
                                  or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "NT_RUNNERS" for t in n.targets))],
                            type_ignores=[]), "aht.py", "exec"), cns)
    C = "C:\\Users\\me\\code\\"
    ns["aht"].read_copies = lambda: {
        C + "shop": {"kind": "brought", "from": "mac", "at": "2026-10-28T10:00:00"},
        C + "pcwork": {"kind": "brought", "from": "DESKTOP-B", "remote": "pcb", "system": "Windows", "at": "2026-10-28T11:00:00"},
        C + "mute": {"kind": "brought", "from": "DESKTOP-C", "remote": "pcc", "system": "Windows", "at": "2026-10-28T12:00:00"},
        C + "nameless": {"kind": "brought", "from": "DESKTOP-D", "system": "Windows", "at": "2026-10-28T13:00:00"},
        C + "api": {"kind": "handover", "from": "mac", "at": "2026-10-28T14:00:00"}}
    ns["aht"].remotes_config = lambda: {"pcb": {"ssh": "me@pcb", "system": "Windows", "runner": "aht"},
                                        "pcc": {"ssh": "me@pcc", "system": "Windows", "answers_why": "install aht on pcc"}}
    ns["aht"].pc_answers = cns["pc_answers"]
    got = ns["brought_here"]()
    ck(got == [(C + "pcwork", "pcwork", "DESKTOP-B"), (C + "shop", "shop", "mac")],
       f"Projects brought here: Send Back to a PC that answers, not to one that does not or one not set up ({got})")
    del ns["aht"].pc_answers                       # an older core: not to a PC
    ck(ns["brought_here"]() == [(C + "shop", "shop", "mac")], "…an older core (no pc_answers): no PC's project")

    # ---- winlayer.notify_user: the core's queue_notice, else a plain append ---------
    wl = ast.parse((ROOT / "windows" / "src" / "winlayer.py").read_text(encoding="utf-8"))
    toasts, handed = [], []
    W = T / "wl"
    (W / "run").mkdir(parents=True)
    wns = {"os": types.SimpleNamespace(environ={}), "time": time, "json": json, "CREATE_NO_WINDOW": 0, "_TOAST_PS": "",
           "subprocess": types.SimpleNamespace(run=lambda *a, **k: toasts.append(a) or types.SimpleNamespace(returncode=0)),
           "aht": types.SimpleNamespace(cfg_get=lambda k, d=None: d, aht_home=lambda: W,
                                        queue_notice=lambda path, rec: handed.append((path, rec)))}
    exec(compile(ast.Module(body=[n for n in wl.body if isinstance(n, ast.FunctionDef) and n.name == "notify_user"],
                            type_ignores=[]), "winlayer.py", "exec"), wns)
    (W / "run" / "tray-alive").touch()
    wns["notify_user"]("api waits for you", "Claude Code asks a question.", {"kind": "waiting"})
    ck(len(handed) == 1 and handed[0][0] == W / "run" / "tray-notices.jsonl"
       and set(handed[0][1]) == {"title", "message", "info", "at"} and handed[0][1]["info"] == {"kind": "waiting"}
       and not (W / "run" / "tray-notices.jsonl").exists() and not toasts,
       f"the tray runs: the notice goes to the core's queue_notice ({handed})")
    del wns["aht"].queue_notice                    # an older core: the append as before
    wns["notify_user"]("web is done", "Claude Code finished.")
    lines = (W / "run" / "tray-notices.jsonl").read_text(encoding="utf-8").splitlines()
    ck(len(lines) == 1 and json.loads(lines[0])["title"] == "web is done" and len(handed) == 1 and not toasts,
       "…an older core without queue_notice: appended to tray-notices.jsonl")
    os.utime(W / "run" / "tray-alive", (time.time() - 600, time.time() - 600))
    wns["notify_user"]("shop is done", "Claude Code finished.")
    ck(len(toasts) == 1 and len(lines) == len((W / "run" / "tray-notices.jsonl").read_text(encoding="utf-8").splitlines()),
       "no tray: a toast, nothing queued")

    # ---- P10 fix: a toast or a badge that fails is the core's warning, once an hour ----
    # (winlayer's notify_user and apply_badge, with the real core's warn_once and
    # _errmsg: the core's own "NOTICE not shown" and "BADGE not updated")
    sys.path.insert(0, str(ROOT))
    os.environ["AHT_HOME"] = str(T / "core" / ".aht")
    import aht as core
    key = "ghp_" + "R4nd0mT0k3nV4lu3Xy9Zq8Wp7Lm6Kj5Hg4Fd3"
    infos, toast_fail = [], [None]

    def toast_run(*a, **k):
        if isinstance(toast_fail[0], Exception):
            raise toast_fail[0]
        return types.SimpleNamespace(returncode=toast_fail[0] or 0)

    def badge_apply(path, marks):
        raise PermissionError(13, f"Access is denied ({key})", path)
    WB = T / "wb"
    (WB / "run").mkdir(parents=True)
    bns = {"os": types.SimpleNamespace(environ={}), "time": time, "json": json, "CREATE_NO_WINDOW": 0, "_TOAST_PS": "",
           "subprocess": types.SimpleNamespace(run=toast_run),
           "aht": types.SimpleNamespace(cfg_get=lambda k, d=None: d, aht_home=lambda: WB, warn_once=core.warn_once,
                                        _errmsg=core._errmsg, warn=core.warn, log=lambda m, *a: infos.append(m))}
    exec(compile(ast.Module(body=[n for n in wl.body if isinstance(n, ast.FunctionDef)
                                  and n.name in ("notify_user", "_warn_once", "apply_badge")],
                            type_ignores=[]), "winlayer.py", "exec"), bns)
    sys.modules["winbadge"] = types.SimpleNamespace(apply=badge_apply)
    try:
        for i in range(3):
            bns["apply_badge"](f"C:\\Users\\me\\code\\shop{i}", ["agent:claude"])
        toast_fail[0] = 1
        for i in range(3):
            bns["notify_user"](f"shop{i} is done", "Claude Code finished.")
        toast_fail[0] = FileNotFoundError(2, "The system cannot find the file specified", "powershell")
        bns["notify_user"]("web is done", "Claude Code finished.")
        bns["notify_user"]("api is done", "Claude Code finished.")
    except Exception as e:                       # noqa: BLE001 (an older winlayer: said below)
        infos.append(f"raised {e!r}")
    finally:
        sys.modules.pop("winbadge", None)
    clog = core.log_path().read_text(encoding="utf-8") if core.log_path().is_file() else ""
    warns = [ln.split("] ", 2)[-1] for ln in clog.splitlines() if "] [WARN ] " in ln]
    ck(warns[:1] and warns[0].startswith("BADGE not updated for C:\\Users\\me\\code\\shop0: PermissionError: [Errno 13] "
                                         "Access is denied ([GitHub token: ghp_…d3])")
       and sum(w.startswith("BADGE") for w in warns) == 1 and key not in clog and not infos,
       f"P10 fix: a badge that fails is a warning (not INFO), its key masked, once an hour, not once per folder ({warns[:1]}, {infos})")
    ck([w for w in warns if w.startswith("NOTICE")]
       == ["NOTICE not shown (shop0 is done): RuntimeError: PowerShell's toast ended with exit 1",
           "NOTICE not shown (web is done): FileNotFoundError: [Errno 2] The system cannot find the file specified: 'powershell'"],
       f"P10 fix: a toast that fails (an exit code, or no PowerShell) is the core's NOTICE not shown, once an hour per kind "
       f"({[w for w in warns if w.startswith('NOTICE')]})")

    # ---- the tray after the core started the queue over (past 500 lines) --------------
    queue(*[{"title": f"old {i}", "message": "x", "at": 1.0 + i} for i in range(5)])
    ns["pump_notices"]()
    n0 = len(shown)
    with open(ns["NOTICE_QUEUE"], "w", encoding="utf-8") as fh:   # as queue_notice does: only the new line
        fh.write(json.dumps({"title": "box is back", "message": "box answers again.", "at": time.time()}) + "\n")
    ns["pump_notices"]()
    ck(shown[n0:] == [("box is back", "box answers again.")], f"…the tray shows the new one only ({shown[n0:]})")
    # ---- watcher_owner=none on Windows ------------------------------------------------
    def lift(src, names, into):
        t = ast.parse(src.read_text(encoding="utf-8"))
        body = [n for n in t.body if (isinstance(n, ast.FunctionDef) and n.name in names)
                or (isinstance(n, ast.Assign) and any(getattr(x, "id", "") in names for x in n.targets))]
        exec(compile(ast.Module(body=body, type_ignores=[]), str(src), "exec"), into)
        missing = names - set(into)
        assert not missing, f"not found in {src.name}: {missing}"
    owner = ["none"]
    V = T / "wv"
    (V / "run").mkdir(parents=True)
    TRAY_ENTRY = '"C:\\Users\\me\\AppData\\Local\\aht\\aht-tray.exe"'
    WATCH_ENTRY = TRAY_ENTRY + " --watch"
    reg, did, wlog = {"entry": None}, [], []
    st = {"running": False, "stops": True, "pid": None}

    def stop(wait=6.0):
        did.append("stop")
        if st["stops"]:
            st["running"] = False
        return st["stops"]
    wv = {"json": json, "os": os, "sys": sys, "time": time, "ctypes": types.SimpleNamespace(get_last_error=lambda: 0),
          "argparse": argparse, "print": lambda *a, **k: did.append("print: " + " ".join(map(str, a))),
          "aht": types.SimpleNamespace(cfg_get=lambda k, d=None: owner[0] if k == "watcher_owner" else d,
                                       aht_home=lambda: V, warn=did.append, log=lambda m: did.append("log: " + m),
                                       watch_roots_config=lambda: []),
          "_run_key_get": lambda: reg["entry"],
          "_run_key_delete": lambda: (did.append("delete entry"), reg.update(entry=None)),
          "_run_key_set": lambda v: (did.append("set entry"), reg.update(entry=v)),
          "watcher_running": lambda: st["running"], "stop_watcher": stop,
          "_watcher_pid": lambda: st["pid"], "_end_process": lambda pid: (did.append(f"end {pid}"), True)[1],
          "start_watcher_hidden": lambda: did.append("start"), "_wlog": wlog.append,
          "_kernel32": types.SimpleNamespace(CreateMutexW=lambda *a: 7, CloseHandle=lambda h: did.append(f"close {h}"),
                                             CreateEventW=lambda *a: did.append("stop event") or 8),
          "MUTEX_NAME": "m", "STOP_EVENT_NAME": "e", "ERROR_ALREADY_EXISTS": 183}
    WLP = ROOT / "windows" / "src" / "winlayer.py"
    lift(WLP, {"watcher_wanted", "watcher_off", "_reload_watcher", "cmd_watch", "is_tray_entry",
               "RUN_VALUE", "ENTRY_OFF", "PID_FILE"}, wv)
    park = V / "run" / wv["ENTRY_OFF"]
    reg["entry"], st["running"] = WATCH_ENTRY, True
    done = wv["watcher_off"]()
    ck(reg["entry"] is None and park.read_text(encoding="utf-8") == WATCH_ENTRY and not st["running"]
       and len(done) == 2 and "removed" in done[0] and "asked to end" in done[1] and not any(d.startswith("end ") for d in did),
       f"none: the watcher's logon entry goes (kept aside for agent again), the watcher ends through its stop event ({done})")
    did.clear()
    park.unlink()
    reg["entry"] = TRAY_ENTRY
    st.update(running=True, stops=False, pid=4242)
    done = wv["watcher_off"]()
    ck(reg["entry"] == TRAY_ENTRY and "delete entry" not in did and not park.exists() and "end 4242" in did
       and done == ["the watcher (pid 4242) did not end when asked, so it was ended"],
       f"none: the tray's own entry stays; a watcher that does not end is ended by the pid it wrote ({done})")
    did.clear()
    st.update(running=True, stops=False, pid=None)
    done = wv["watcher_off"]()
    ck(done == ["the watcher was asked to end; it has not ended yet"] and not any(d.startswith("end ") for d in did),
       "…no pid file (or another program has that pid now): nothing is ended by its name")
    st.update(running=False, stops=True, pid=None)
    did.clear()
    ck(wv["_reload_watcher"]() is False and "start" not in did, "none: Reload starts no watcher")
    did.clear()
    ck(wv["cmd_watch"]([]) == 0 and "stop event" not in did and "close 7" in did
       and wlog[-1] == "watching is off (watcher_owner=none) — exiting" and not (V / "run" / wv["PID_FILE"]).exists(),
       f"none: a watcher started by a logon entry left from before ends at once ({wlog[-1:]})")
    # agent again: the entry comes back, the watcher starts
    owner[0] = "agent"
    reg["entry"] = None
    park.write_text(WATCH_ENTRY, encoding="utf-8")
    did.clear()
    ck(wv["_reload_watcher"]() is True and reg["entry"] == WATCH_ENTRY and not park.exists() and "start" in did,
       f"agent again: the logon entry is put back and the watcher starts ({did})")
    reg["entry"] = TRAY_ENTRY
    park.write_text(WATCH_ENTRY, encoding="utf-8")
    did.clear()
    wv["_reload_watcher"]()
    ck(reg["entry"] == TRAY_ENTRY and "set entry" not in did and not park.exists(), "…an entry there now (the tray's) stays")
    wsrc = WLP.read_text(encoding="utf-8")
    ck("aht.stop_watcher = watcher_off" in wsrc and "if not watcher_wanted():\n            # watcher_owner=none: no logon entry" in wsrc,
       "aht config --set watcher_owner=none reaches watcher_off on Windows; aht install writes no entry then")
    # the tray
    tv = {"winlayer": types.SimpleNamespace(watcher_wanted=lambda: owner[0] != "none", watcher_running=lambda: st["running"],
                                            start_watcher_hidden=lambda: did.append("start"), stop_watcher=lambda: did.append("stop")),
          "balloon": lambda t, m: did.append(("balloon", t)), "refresh": lambda force=False: None, "_in_thread": lambda fn: fn()}
    lift(SRC, {"WATCHING_OFF", "start_watcher_if_wanted", "act_toggle_watch", "act_restart"}, tv)
    owner[0], st["running"] = "none", False
    did.clear()
    tv["start_watcher_if_wanted"]()
    tv["act_toggle_watch"]()
    tv["act_restart"]()
    ck("start" not in did and did.count(("balloon", "Watching is off")) == 2,
       f"none: the tray starts no watcher (at its start, Resume watching, Restart watcher) and says why ({did})")
    owner[0] = "agent"
    did.clear()
    ck(tv["start_watcher_if_wanted"]() is True and did == ["start"], "agent: the tray keeps a watcher running, as before")
    # ---- phase 10: the tray's own errors in aht's log; Make a Problem Report… ----------
    import threading

    class SyncThread:                    # runs at start(): the checks see what it did
        def __init__(self, target=None, daemon=None):
            self.target = target

        def start(self):
            self.target()
    clock = [1000.0]
    sent10, boxes10, balloons10, popened, answers10, cli10 = [], [], [], [], [], {}
    remotes = [{"box": {}, "mini": {}}]

    def cli(*a):
        sent10.append(a)
        how = cli10.get(a[0])
        if isinstance(how, Exception):
            raise how
        code, out, err = how or (0, "", "")
        return types.SimpleNamespace(returncode=code, stdout=out, stderr=err)

    LOGF = T / "aht.log"
    LOGF.write_text("[2026-10-28 14:10:00] [WARN ] x\n", encoding="utf-8")

    def startfile(p):
        raise OSError(f"[WinError 1155] No application is associated with the file: '{p}'")
    pv = {"json": json, "threading": types.SimpleNamespace(Lock=threading.Lock, Thread=SyncThread),
          "time": types.SimpleNamespace(time=lambda: clock[0], strftime=lambda f: "20261028-141000"),
          "os": types.SimpleNamespace(path=os.path, startfile=startfile),
          "subprocess": types.SimpleNamespace(Popen=lambda a, **k: popened.append(a)),
          "_run_cli": cli, "msgbox": lambda t, m, f=0: (boxes10.append((t, m, f)), answers10.pop(0) if answers10 else 0)[1],
          "balloon": lambda t, m: balloons10.append((t, m)),
          "aht": types.SimpleNamespace(remotes_config=lambda: remotes[0], aht_home=lambda: T,
                                       log_path=lambda: LOGF)}
    t10 = ast.parse(SRC.read_text(encoding="utf-8"))
    consts = [n for n in t10.body if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Tuple)
              and {getattr(e, "id", "") for e in n.targets[0].elts} & {"MB_OK", "MB_OKCANCEL", "IDOK"}]
    exec(compile(ast.Module(body=consts, type_ignores=[]), str(SRC), "exec"), pv)
    lift(SRC, {"LOGGED", "LOG_LOCK", "REPORT_HOLDS", "_name", "tray_log", "_in_thread", "_run_action", "_size",
               "_machines_set_up", "_report_file", "act_problem_report", "act_openlog"}, pv)
    logs = lambda: [a for a in sent10 if a[0] == "_log"]
    ck(pv["tray_log"]("the tip could not read the registry", KeyError("projects")) is True
       and logs() == [("_log", "--level", "error", "--source", "tray", "--",
                       "the tip could not read the registry: KeyError: 'projects'")],
       f"P10: a caught error goes to `aht _log --level error --source tray -- …` ({logs()})")
    ck(pv["tray_log"]("the tip could not read the registry", KeyError("projects")) is False and len(logs()) == 1,
       "P10: …the same one again: not sent")
    clock[0] += 601
    ck(pv["tray_log"]("the tip could not read the registry", KeyError("projects")) is True and len(logs()) == 2,
       "P10: …ten minutes later: sent again")
    clock[0] += 61
    sent10.clear()
    got = [pv["tray_log"](f"problem {i}") for i in range(7)]
    ck(got == [True] * 5 + [False] * 2 and len(logs()) == 5, f"P10: at most five a minute ({got})")
    clock[0] += 61
    ck(pv["tray_log"]("problem 6") is True, "P10: …a minute later, more")
    sent10.clear()
    pv["tray_log"]("a  long\n line " + "x" * 900)
    ck(len(logs()[0][-1]) == 500 and "\n" not in logs()[0][-1] and "  " not in logs()[0][-1], "P10: …one line, at most 500 characters")
    cli10["_log"] = OSError("aht.exe is gone")
    try:
        ok = pv["tray_log"]("aht.exe could not be run")
    except Exception as e:                       # noqa: BLE001
        ok = e
    ck(ok is True, f"P10: …a log that cannot be written is no new failure ({ok!r})")
    del cli10["_log"]
    sent10.clear()

    def act_reconcile():
        def work():
            raise KeyError("applied_moves")
        pv["_in_thread"](work)
    act_reconcile()
    ck(logs() == [("_log", "--level", "error", "--source", "tray", "--", "act_reconcile failed: KeyError: 'applied_moves'")],
       f"P10: an action's work that fails is logged with the action's name ({logs()})")
    sent10.clear()

    def act_about():
        raise RuntimeError("MessageBoxW failed")
    pv["_run_action"](act_about)
    ck(logs()[-1][-1] == "act_about failed: RuntimeError: MessageBoxW failed"
       and balloons10[-1] == ("That did not work", "RuntimeError: MessageBoxW failed (noted in aht's log)"),
       f"P10: a menu item that fails is logged and said ({balloons10[-1:]})")
    clock[0] += 61                       # each check below in a minute of its own
    sent10.clear()
    balloons10.clear()
    pv["act_openlog"]()
    ck(logs() and logs()[-1][-1].startswith("the log did not open: OSError: [WinError 1155]")
       and balloons10 and balloons10[-1][0] == "The log did not open", f"P10: Open log that fails: logged and said ({balloons10})")
    # Make a Problem Report…
    OUT = str(T / "reports" / "problem-20261028-141000.txt")
    RP = "C:\\Users\\me\\.aht\\reports\\problem-20261028-141000.txt"
    good = json.dumps({"path": RP, "bytes": 18432, "errors": 7, "machines": [
        {"machine": "DESKTOP-B", "here": True, "reachable": True, "lines": 4, "error": None},
        {"machine": "box", "here": False, "reachable": True, "lines": 3, "error": None},
        {"machine": "mini", "here": False, "reachable": False, "lines": 0, "error": "ssh: timed out"}]})
    sent10.clear()
    cli10["report-problem"] = (0, good, "")
    answers10[:] = [pv["IDYES"]]
    pv["act_problem_report"]()
    asked = boxes10[-1]
    ck(asked[0] == "Make a Problem Report" and "Nothing is sent anywhere" in asked[1] and "how many projects aht tracks (not where they are)" in asked[1]
       and asked[2] & 0xF == pv["MB_YESNOCANCEL"], "P10: Make a Problem Report… says what it holds and asks about the other machines")
    ck(sent10 == [("report-problem", "--out", OUT, "--everywhere", "--json")] and (T / "reports").is_dir(),
       f"P10: …Yes: report-problem --out <aht's reports>/problem-<time>.txt --everywhere --json, its folder made ({sent10})")
    ck(popened == [["explorer", "/select,", RP]], f"P10: …the folder opens with the report selected ({popened})")
    ck(balloons10[-1] == ("Problem report saved", "problem-20261028-141000.txt, 18 KB. Nothing was sent anywhere. Not answered: mini."),
       f"P10: …and a balloon says so ({balloons10[-1]})")
    sent10.clear()
    answers10[:] = [7]
    pv["act_problem_report"]()
    ck(sent10 == [("report-problem", "--out", OUT, "--json")], f"P10: …No: this PC only ({sent10})")
    sent10.clear()
    answers10[:] = [pv["IDCANCEL"]]
    pv["act_problem_report"]()
    ck(sent10 == [], "P10: …Cancel: nothing runs")
    remotes[0] = {}
    answers10[:] = [pv["IDOK"]]
    pv["act_problem_report"]()
    ck(boxes10[-1][2] & 0xF == pv["MB_OKCANCEL"] and sent10 == [("report-problem", "--out", OUT, "--json")],
       "P10: no machines set up: OK or Cancel, then report-problem --json")
    # what the core refuses: its words, nothing logged; a crash: logged, said briefly
    sent10.clear()
    cli10["report-problem"] = (1, "", "aht: the report could not be written to ~\\Desktop: No space left on device\n")
    answers10[:] = [pv["IDOK"]]
    pv["act_problem_report"]()
    ck(boxes10[-1][:2] == ("The report was not made", "aht: the report could not be written to ~\\Desktop: No space left on device")
       and not logs(), f"P10: a refusal: the core's words, nothing logged ({boxes10[-1][:2]})")
    clock[0] += 61
    cli10["report-problem"] = (1, "", "Traceback (most recent call last):\n  File \"aht.py\", line 1\nKeyError: 'nope'\n")
    answers10[:] = [pv["IDOK"]]
    pv["act_problem_report"]()
    ck(boxes10[-1][1] == "aht stopped with an error (KeyError). It is noted in aht's log: Open log shows it."
       and logs()[-1][-1] == "report-problem failed unexpectedly: it crashed (KeyError)", f"P10: a crash: logged and said briefly ({logs()[-1:]})")
    clock[0] += 61
    cli10["report-problem"] = (0, "{}", "")
    answers10[:] = [pv["IDOK"]]
    pv["act_problem_report"]()
    ck(logs()[-1][-1] == "report-problem failed unexpectedly: its answer had no path", "P10: an answer without a path: logged")
    ck(pv["_size"](512) == "512 bytes" and pv["_size"](9216) == "9.0 KB" and pv["_size"](18432) == "18 KB"
       and pv["_size"](3 * 1024 * 1024) == "3.0 MB", "P10: sizes in words")
    tsrc = SRC.read_text(encoding="utf-8")
    ck('add(root, "Make a Problem Report…", act_problem_report)' in tsrc and "_run_action(actions.get(cmd, lambda: None))" in tsrc
       and 'tray_log(f"timer {wparam} failed", e)' in tsrc,
       "P10: the menu offers Make a Problem Report…; menu actions and timers are guarded")
    ck(not warned, f"Windows showed every balloon ({warned})")
finally:
    shutil.rmtree(T, ignore_errors=True)

print("TRAY TEST " + ("OK" if not fails else f"FAIL ({len(fails)})"))
sys.exit(1 if fails else 0)
