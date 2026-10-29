#!/usr/bin/env python3
"""[22] workspace, go to a tab, a checkup of open sessions, tidy, the usage limit."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)

import later_kit

# what earlier sections left: [17]'s project "Across" (projX, tagged) and
# its Claude Code store; [18]'s folder of open sessions (rec); [20]'s
# stand-in iTerm2 tabs file (tabs_file) and its stand-in Claude processes
# (title_line, fake_claude), which write into that store (tstore)
projX = later_kit.across_made()[0]
rec = tools / "sessions"
rec.mkdir(exist_ok=True)
tabs_file = sb / "iterm-tabs.json"
tstore = tools / "claude" / enc(projX)
def title_line(t, sid):
    return json.dumps({"type": "custom-title", "customTitle": t, "sessionId": sid}) + "\n"
def fake_claude(sid, title=None):
    """A stand-in Claude process: a live pid with a session record and a transcript."""
    proc = subprocess.Popen(["sleep", "600"], cwd="/", stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    (rec / f"{proc.pid}.json").write_text(json.dumps({"pid": proc.pid, "cwd": projX,
                                                      "sessionId": sid, "status": "idle"}))
    (tstore / f"{sid}.jsonl").write_text(title_line(title, sid) if title else "")
    return proc

print("\n[22] workspace, go to a tab, a checkup of open sessions, tidy, the usage limit")
ilog = sb / "iterm.log"
def ilines():
    return [json.loads(l) for l in ilog.read_text().splitlines()] if ilog.is_file() else []
tabs_file.write_text(json.dumps({
    "/dev/ttysW1": {"title": "Paper", "override": True, "pane": 1, "panes": 1, "window": 1, "tab": 1},
    "/dev/ttysW2": {"title": "Notes", "override": True, "pane": 1, "panes": 1, "window": 1, "tab": 2},
    "/dev/ttysW3": {"title": "", "override": False, "pane": 1, "panes": 1, "window": 1, "tab": 3}}))
p1 = fake_claude("w1", title="Paper")
shell = subprocess.Popen(["sleep", "600"], cwd="/", stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
started = "claude --dangerously-skip-permissions --model opus --resume old1 fix-it"
wenv = {"AHT_ITERM_LOG": str(ilog), "AHT_ITERM_TABS": str(tabs_file),
        "AHT_TTYS": json.dumps({str(p1.pid): "/dev/ttysW1"}),
        "AHT_TTY_PROCS": json.dumps({"/dev/ttysW1": [[p1.pid, started]],
                                     "/dev/ttysW2": [[shell.pid, "-zsh"]], "/dev/ttysW3": []}),
        "AHT_CWDS": json.dumps({str(shell.pid): projX}),
        "AHT_CMDLINES": json.dumps({str(p1.pid): started}), "AHT_CLAUDE_VERSION": "9.9.9"}
JS("workspace", "--save", "--json", extra_env=wenv)
JS("workspace", "--save", "--json", extra_env=wenv)
ws = JS("workspace", "--json", extra_env=wenv).get("workspaces", [])
snap = json.loads(next((sb / ".aht" / "workspaces").glob("*.json")).read_text())
e1 = next((e for e in snap["tabs"] if e["title"] == "Paper"), {})
e2 = next((e for e in snap["tabs"] if e["title"] == "Notes"), {})
ck(len(ws) == 1 and ws[0]["tabs"] == 3 and ws[0]["sessions"] == 1
   and e1.get("session") == "w1" and e1.get("args") == ["--dangerously-skip-permissions",
                                                        "--model", "opus"]
   and e2.get("cwd") == projX and e2.get("agent") is None,
   f"workspace: tabs, titles, folders and sessions kept; the same layout once ({ws}, {e1})")
r = run("workspace", "--restore", extra_env=wenv)
ck(r.returncode == 3 and "its session is open" in r.stdout and "that title is open" in r.stdout,
   "workspace: what is open now is skipped")
p1.kill(); p1.wait()
(rec / f"{p1.pid}.json").unlink()
tabs_file.write_text(json.dumps({"/dev/ttysW3": {"title": "", "override": False, "pane": 1,
                                                 "panes": 1, "window": 1, "tab": 1}}))
d = JS("workspace", "--restore", "--apply", "--json", extra_env=wenv)
script = next((x["script"] for x in ilines() if x.get("what") == "restore"), "")
ck(d.get("applied") and d["plan"]["opens"] == 2 and "--resume w1" in script
   and "--model opus" in script and "fix-it" not in script and "old1" not in script
   and "user.ahtTitle" in script and "Notes" in script
   and "CLAUDE_CODE_DISABLE_TERMINAL_TITLE=1" in script,
   f"workspace: opened again, each session resumed with its options, tabs titled ({d.get('plan')})")

# a second click right away opens nothing twice (a session takes a while to start)
d2 = JS("workspace", "--restore", "--apply", "--json", extra_env=wenv)
ck(not d2.get("applied") and "everything in it is open already" in (d2.get("blockers") or [])
   and sum(1 for x in ilines() if x.get("what") == "restore") == 1,
   f"workspace: a second Open Them right away opens nothing twice ({d2.get('blockers')})")
(sb / ".aht" / "run" / "workspace-opened.json").unlink()

# tab colours come from iTerm2's saved window state, profiles from iTerm2
import plistlib, sqlite3 as _sq
def keyed(obj):
    """An NSKeyedArchiver plist, as iTerm2 writes its saved sessions."""
    objs = ["$null"]
    def enc(o):
        if isinstance(o, dict):
            i = len(objs)
            objs.append(None)
            ks = [enc(k) for k in o]
            vs = [enc(v) for v in o.values()]
            objs[i] = {"NS.keys": ks, "NS.objects": vs, "$class": plistlib.UID(0)}
            return plistlib.UID(i)
        objs.append(o)
        return plistlib.UID(len(objs) - 1)
    root = enc(obj)
    return plistlib.dumps({"$archiver": "NSKeyedArchiver", "$version": 100000,
                           "$top": {"root": root}, "$objects": objs}, fmt=plistlib.FMT_BINARY)
orange = {"Red Component": 1.0, "Green Component": 0.5, "Blue Component": 0.0,
          "Color Space": "sRGB"}
state = sb / "iterm-state.sqlite"
db = _sq.connect(str(state))
db.execute("CREATE TABLE Node (key text not null, identifier text not null, "
           "parent integer not null, data blob)")
for key, blob in (
        ("Session", keyed({"TTY": "/dev/ttysW2", "Bookmark": {
            "Use Separate Colors for Light and Dark Mode": True,
            "Use Tab Color (Light)": True, "Tab Color (Light)": orange,
            "Use Tab Color (Dark)": True, "Tab Color (Dark)": orange}})),
        ("Session", keyed({"TTY": "/dev/ttysW1", "Bookmark": {
            "Use Tab Color": False, "Tab Color": orange}})),
        ("Session", b"not a plist at all, Tab Color"),
        ("Screen State", keyed({"TTY": "/dev/ttysW1"}))):
    db.execute("INSERT INTO Node VALUES (?, '', 0, ?)", (key, blob))
db.commit()
db.close()
tabs_file.write_text(json.dumps({
    "/dev/ttysW1": {"title": "Paper", "override": True, "pane": 1, "panes": 1, "window": 1,
                    "tab": 1, "profile": "Work"},
    "/dev/ttysW2": {"title": "Notes", "override": True, "pane": 1, "panes": 1, "window": 1,
                    "tab": 2, "profile": "Default"}}))
cenv = dict(wenv, AHT_ITERM_STATE=str(state),
            AHT_TTY_PROCS=json.dumps({"/dev/ttysW1": [[shell.pid, "-zsh"]],
                                      "/dev/ttysW2": [[shell.pid, "-zsh"]]}))
newest = Path(JS("workspace", "--save", "--json", extra_env=cenv).get("saved") or "missing")
snap2 = json.loads(newest.read_text())
c1 = next((e for e in snap2["tabs"] if e["title"] == "Paper"), {})
c2 = next((e for e in snap2["tabs"] if e["title"] == "Notes"), {})
ck(c2.get("color") == "#ff8000" and c1.get("color") is None and c1.get("profile") == "Work",
   f"workspace: each tab's colour and profile are kept ({c1}, {c2})")
tabs_file.write_text(json.dumps({"/dev/ttysW3": {"title": "", "override": False, "pane": 1,
                                                 "panes": 1, "window": 1, "tab": 1}}))
d = JS("workspace", "--restore", newest.stem, "--apply", "--json",
       extra_env=dict(cenv, AHT_ITERM_STARTED="1",
                      AHT_TTY_PROCS=json.dumps({"/dev/ttysW3": [[shell.pid, "-zsh"]]})))
script = [x["script"] for x in ilines() if x.get("what") == "restore"][-1]
ck(d.get("applied") and "set w to current window" in script
   and 'create tab with profile "Default"' in script and "create tab with default profile" in script
   and "bg;red;brightness;255" in script and "bg;green;brightness;128" in script
   and "bg;blue;brightness;0" in script and script.count("brightness") == 3
   and script.count("; clear") == 2,
   "workspace: tabs open with their profile and colour, in the window iTerm2 opened as it started")
(sb / ".aht" / "run" / "workspace-opened.json").unlink()

# saved every few minutes by the app, the last workspace_keep kept
run("config", "--set", "workspace_keep=2", "--no-reload")
a1 = JS("workspace", "--save", "--auto", "--json", extra_env=cenv)
a2 = JS("workspace", "--save", "--auto", "--json", extra_env=cenv)
run("config", "--set", "workspace_save_minutes=0", "--no-reload")
a3 = JS("workspace", "--save", "--auto", "--json", extra_env=cenv)
kept = len(list((sb / ".aht" / "workspaces").glob("*.json")))
ck(a1.get("saved") and not a2.get("saved") and "ago" in str(a2.get("skipped"))
   and a3.get("skipped") == "off" and kept == 2,
   f"workspace: saved on a timer, not more often, and only the last 2 kept ({a1}, {a2}, {a3}, {kept})")
run("config", "--unset", "workspace_keep")
run("config", "--unset", "workspace_save_minutes")

# go to a session's tab; a background session has none
p2 = fake_claude("w2")
genv = dict(wenv, AHT_TTYS=json.dumps({str(p2.pid): "/dev/ttysW3"}))
r = run("goto", str(p2.pid), extra_env=genv)
ck(r.returncode == 0 and {"tty": "/dev/ttysW3", "what": "goto", "text": ""} in ilines(),
   "goto: the session's tab is brought to the front")
r = run("goto", "w2", extra_env=dict(wenv, AHT_TTYS="{}"))
ck(r.returncode == 1 and "background" in r.stderr, "goto: a background session has no tab")
g = JS("goto", str(p2.pid), "--json", extra_env=dict(genv, AHT_ITERM_ANSWER="refused"))
ck(g.get("ok") is False and "Automation" in str(g.get("why")),
   f"goto: when macOS does not let aht control iTerm2, it says so and where to change it ({g})")

# getting started: iTerm2 and its settings, the app's switches, Remote Control
prefs = sb / "iterm-prefs.json"
agents = sb / "LaunchAgents"
agents.mkdir()
had = (tools / "settings.json").read_text() if (tools / "settings.json").exists() else None
(tools / "settings.json").write_text("{}")
senv = {"AHT_APPS": "Terminal", "AHT_ITERM_PREFS": str(prefs),
        "AHT_LAUNCH_AGENTS": str(agents), "AHT_ITERM_STATE": str(sb / "no-state.sqlite")}
gs = {x["id"]: x for x in JS("getting-started", "--json", extra_env=senv).get("steps", [])}
ck(list(gs) == ["iterm", "login", "remote_control", "corner", "chimes"]
   and not gs["iterm"]["ok"] and "iterm2.com" in gs["iterm"]["how"]
   and "cannot bring" in gs["corner"]["text"] and not gs["login"]["ok"],
   f"getting started without iTerm2: get it, and what needs it ({list(gs)})")
prefs.write_text(json.dumps({"EnableAPIServer": 1, "ShowNewOutputIndicator": 0}))
(agents / "com.aht.tray.plist").write_text("<plist/>")
(tools / "settings.json").write_text(json.dumps({"remoteControlAtStartup": True}))
run("config", "--set", "session_corner=true")
gs = {x["id"]: x for x in JS("getting-started", "--json",
                             extra_env=dict(senv, AHT_APPS="iTerm,Terminal")).get("steps", [])}
ck([i for i, x in gs.items() if not x["ok"]] == ["chimes", "tab_colours"]
   and gs["tab_colours"]["optional"] and gs["chimes"]["how"]
   and not gs["iterm_api"]["how"] and "brings" in gs["corner"]["text"],
   f"getting started with iTerm2 set up: only what is still off, with where to change it "
   f"({ {i: x['ok'] for i, x in gs.items()} })")
prefs.write_text("{}")
gs = {x["id"]: x for x in JS("getting-started", "--json",
                             extra_env=dict(senv, AHT_APPS="iTerm")).get("steps", [])}
ck(not gs["iterm_api"]["ok"] and "Magic" in gs["iterm_api"]["how"]
   and not gs["new_output_dot"]["ok"] and gs["new_output_dot"]["optional"],
   "getting started: iTerm2's defaults are the API off and the blue dot on")
r = run("getting-started", extra_env=dict(senv, AHT_APPS="iTerm"))
ck(r.returncode == 0 and "✗ iTerm2's Python API" in r.stdout and "○ Chimes (optional)" in r.stdout
   and "✓ Start at login" in r.stdout, "getting started in the terminal: done, to do, optional")
run("config", "--unset", "session_corner")
if had is None:
    (tools / "settings.json").unlink()
else:
    (tools / "settings.json").write_text(had)

# the checkup: open twice, stuck, outside the app, older Claude Code
(tools / "settings.json").write_text(json.dumps({"remoteControlAtStartup": True}))
old = int((time.time() - 5 * 3600) * 1000)
p3 = fake_claude("w3")
p4 = subprocess.Popen(["sleep", "600"], cwd="/", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
(rec / f"{p3.pid}.json").write_text(json.dumps({"pid": p3.pid, "cwd": projX, "sessionId": "w3",
    "status": "busy", "statusUpdatedAt": old, "version": "1.0.0", "kind": "interactive"}))
(rec / f"{p4.pid}.json").write_text(json.dumps({"pid": p4.pid, "cwd": projX, "sessionId": "w3",
    "status": "idle", "version": "9.9.9", "kind": "interactive", "bridgeSessionId": "b1"}))
os.utime(tstore / "w3.jsonl", (time.time() - 5 * 3600, time.time() - 5 * 3600))
cenv = dict(wenv, AHT_TTYS=json.dumps({str(p3.pid): "/dev/ttysW3", str(p2.pid): "/dev/ttysW3"}),
            AHT_CMDLINES=json.dumps({str(p3.pid): "claude --model sonnet --resume w3"}))
rows = {r["pid"]: r for r in JS("checkup", "--json", extra_env=cenv).get("sessions", [])}
i3, i4 = rows.get(p3.pid, {}).get("issues", []), rows.get(p4.pid, {}).get("issues", [])
ck(sorted(i3) == ["older", "outside the app", "stuck", "twice"] and i4 == ["twice"]
   and rows[p3.pid]["can_restart"],
   f"checkup: open twice, stuck, outside the app, older ({i3}, {i4})")
d = JS("checkup", "--restart", str(p3.pid), "--apply", "--json", extra_env=cenv)
typed = [x for x in ilines() if x.get("what") == "write"]
ck(d.get("applied") and p3.wait(timeout=5) is not None and typed
   and typed[-1]["tty"] == "/dev/ttysW3" and "--model sonnet --resume w3" in typed[-1]["text"],
   f"checkup --restart: ended, then started again in its tab with its options ({d})")
d = JS("checkup", "--close", str(p4.pid), "--apply", "--json", extra_env=cenv)
ck(d.get("applied") and p4.wait(timeout=5) is not None,
   "checkup --close: the process ends; its conversation stays")
for pr in (p2, shell):
    pr.kill(); pr.wait()
for f in rec.glob("*.json"):
    f.unlink()

# tidy: a history without a folder goes to the Trash, only when asked
orphan = tools / "claude" / "-gone-forever"
orphan.mkdir()
(orphan / "o1.jsonl").write_text(json.dumps({"type": "user", "cwd": "/gone/forever",
                                             "message": {"role": "user", "content": "x"}}) + "\n")
trash = sb / "trash"
d = JS("tidy", "--show=-gone-forever", "--json")
row = next((o for o in JS("tidy", "--json").get("orphans", []) if o["store"] == "-gone-forever"), {})
ck("# History of /gone/forever" in d.get("markdown", "") and "**You:** x" in d["markdown"]
   and row.get("sessions") == 1 and row.get("bytes", 0) > 0 and row.get("last"),
   f"tidy --show: a history to read before deciding, with its size and last use ({row})")
r = run("tidy", "--remove-history=-gone-forever", extra_env={"AHT_TRASH": str(trash)})
ck(r.returncode == 0 and orphan.is_dir(), "tidy --remove-history: a dry run first")
d = JS("tidy", "--remove-history=-gone-forever", "--apply", "--json",
       extra_env={"AHT_TRASH": str(trash)})
ck(d.get("applied") and not orphan.exists() and (trash / "-gone-forever" / "o1.jsonl").is_file(),
   "tidy --remove-history: moved to the Trash")
r = run("tidy", "--remove-history=" + enc(projX), "--apply", extra_env={"AHT_TRASH": str(trash)})
ck(r.returncode == 3 and (tools / "claude" / enc(projX)).is_dir(),
   "tidy --remove-history: never a history a tracked project owns")
# only a name that is one of the history folder's own entries, spelled so,
# and a real folder: on Windows a \ or a drive letter would lead out of it
croot = tools / "claude"
(croot / "a" / "b").mkdir(parents=True)
victim = sb / "victim"
victim.mkdir()
(victim / "keep.txt").write_text("x")
(croot / "afile.txt").write_text("x")
(croot / "-Gone-Case").mkdir()
(croot / "-Gone-Case" / "c.jsonl").write_text(json.dumps({"cwd": "/gone/case"}) + "\n")
bad = ["..", "a/b", "a\\b", "..\\x", "C:x", "afile.txt", "-gone-case"]
try:
    os.symlink(victim, croot / "linked", target_is_directory=True)
except OSError:                         # Windows without the right to make links
    print("  SKIP tidy --remove-history of a link: no symlink here")
else:
    # a link is listed (and can be read) but never removed, and says why
    lrows = {o["store"]: o for o in JS("tidy", "--json").get("orphans", [])}
    dl = JS("tidy", "--remove-history=linked", "--apply", "--json",
            extra_env={"AHT_TRASH": str(trash)})
    txt = run("tidy").stdout
    ck(lrows.get("linked", {}).get("link") is True
       and lrows.get("-Gone-Case", {}).get("link") is False
       and dl.get("blockers") == [core.LINK_ENTRY] and not dl.get("applied")
       and os.path.islink(croot / "linked") and (victim / "keep.txt").is_file()
       and "--remove-history=linked" not in txt and "--remove-history=-Gone-Case" in txt
       and core.LINK_ENTRY in txt,
       f"tidy: a link in the history folder is marked, its own reason, no remove command "
       f"({lrows.get('linked')}, {dl})")
refused = {}
for name in bad:
    d = JS("tidy", "--remove-history=" + name, "--apply", "--json",
           extra_env={"AHT_TRASH": str(trash)})
    refused[name] = d.get("blockers") == ["there is no such history"] and not d.get("applied")
d = JS("tidy", "--remove-history=-Gone-Case", "--apply", "--json",
       extra_env={"AHT_TRASH": str(trash)})
ck(all(refused.values()) and (victim / "keep.txt").is_file() and (croot / "a" / "b").is_dir()
   and (croot / "afile.txt").is_file() and d.get("applied") and not d.get("deleted")
   and (trash / "-Gone-Case" / "c.jsonl").is_file()
   and sorted(p.name for p in trash.iterdir()) == ["-Gone-Case", "-gone-forever"],
   f"tidy --remove-history: only an entry of the history folder, spelled as on disk, "
   f"no link and no file ({refused}, {d})")
# reading one before deciding: the same names, but a link may be read
(croot / "-Read-Me").mkdir()
(croot / "-Read-Me" / "r.jsonl").write_text(json.dumps({"cwd": "/gone/readme"}) + "\n")
(tools / "outside.jsonl").write_text(json.dumps({"cwd": "/not/a/history"}) + "\n")
shown = {name: JS("tidy", "--show=" + name, "--json").get("error")
         for name in ["..", "a/b", "a\\b", "..\\x", "C:x", "afile.txt", "-read-me"]}
d = JS("tidy", "--show=-Read-Me", "--json")
ck(all(v == "no such history" for v in shown.values())
   and "# History of /gone/readme" in d.get("markdown", ""),
   f"tidy --show: only an entry of the history folder, spelled as on disk ({shown})")
r = run("tidy", "--remove-history=-not-there", "--apply")
ck(r.returncode == 3 and r.stdout.splitlines()[:2] == ["-not-there",
                                                       "  ✗ there is no such history"]
   and "would move" not in r.stdout,
   f"tidy --remove-history: refused, it shows the name and why ({r.stdout!r})")
shutil.rmtree(croot / "-Read-Me")
(tools / "outside.jsonl").unlink()
for p in (croot / "linked", croot / "afile.txt"):
    if os.path.lexists(p):
        os.unlink(p)
shutil.rmtree(croot / "a")
# Windows: the shell says only that the item is gone; the Recycle Bin tells
# whether it went there or Windows deleted it for good (what aht's checks
# before could not foresee)
saved = (core._shell_delete, core._bin_items, core._in_recycle_bin)
got = {}
try:
    for case, (before, after, found, gone) in {
            "one more in the bin": (3, 4, False, True), "no bin on that drive":
            (None, None, False, True), "the same count": (3, 3, False, True),
            "a full bin let an older one go": (5, 5, True, True),
            "it stayed where it was": (3, 3, False, False)}.items():
        rb = sb / "rb"
        rb.mkdir()
        counts = iter([before, after])
        core._bin_items = lambda p: next(counts)
        core._in_recycle_bin = lambda p, since: found
        core._shell_delete = lambda p: gone and not shutil.rmtree(p)
        got[case] = core._to_recycle_bin(rb)
        shutil.rmtree(rb, ignore_errors=True)
finally:
    core._shell_delete, core._bin_items, core._in_recycle_bin = saved
ck(got == {"one more in the bin": "trash", "no bin on that drive": "deleted",
           "the same count": "deleted", "a full bin let an older one go": "trash",
           "it stayed where it was": ""},
   f"tidy --remove-history on Windows: in the Recycle Bin or deleted for good ({got})")
# Windows: aht only ever moves a history to the Recycle Bin.  What Windows
# would delete for good is refused before: no bin on that drive, a bin set
# to remove files at once, a history bigger than the bin holds; settings
# aht cannot read change nothing (the check after the delete still tells)
saved = (core._bin_items, core._bin_settings)
why = {}
try:
    for case, (items, settings, size) in {
            "no bin": (None, (False, 10 << 20), 1), "removes at once": (3, (True, 10 << 20), 1),
            "too big": (3, (False, 10 << 20), 11 << 20), "fits": (3, (False, 10 << 20), 9 << 20),
            "unreadable": (3, (None, None), 1 << 40)}.items():
        core._bin_items = lambda p, n=items: n
        core._bin_settings = lambda p, st=settings: st
        why[case] = core._bin_refusal(sb, size)
finally:
    core._bin_items, core._bin_settings = saved
ck(why["no bin"].startswith("that drive has no Recycle Bin, so Windows would delete it for good")
   and why["removes at once"].startswith("the Recycle Bin of that drive is set to remove files")
   and why["too big"].startswith("it is bigger (11.0 MB) than the Recycle Bin of that drive "
                                 "holds (10.0 MB)")
   and all("you can still delete it yourself" in why[k]
           for k in ("no bin", "removes at once", "too big"))
   and why["fits"] == "" and why["unreadable"] == ""
   and core._bin_default_cap(32 << 30) == (32 << 30) // 10
   and core._bin_default_cap(100 << 30) == (4 << 30) + (3 << 30)
   and (core._trash_refusal(sb, 1) == "" if os.name != "nt" else True),
   f"tidy --remove-history on Windows: refused when Windows would delete it for good ({why})")
(croot / "-gone-refused").mkdir()
(croot / "-gone-refused" / "r.jsonl").write_text(json.dumps({"cwd": "/gone/refused"}) + "\n")
probe = ("import sys; sys.path.insert(0, sys.argv[1]); import aht; "
         "aht._trash_refusal = lambda p, n: 'that drive has no Recycle Bin, so Windows would "
         "delete it for good'; aht._to_trash = lambda p: sys.exit(9); "
         "aht._trash_name = lambda: 'Recycle Bin'; sys.exit(aht.main(sys.argv[2:]))")
r = subprocess.run([PY, "-c", probe, str(HERE.parent), "tidy", "--remove-history=-gone-refused",
                    "--apply"], env=env, capture_output=True, text=True)
dr = subprocess.run([PY, "-c", probe.replace("aht._trash_refusal = lambda p, n: ", "_ = "),
                     str(HERE.parent), "tidy", "--remove-history=-gone-refused"],
                    env=env, capture_output=True, text=True)
ck(r.returncode == 3 and (croot / "-gone-refused" / "r.jsonl").is_file()
   and r.stdout.splitlines()[0] == "-gone-refused" and "would move" not in r.stdout
   and "  ✗ that drive has no Recycle Bin" in r.stdout
   and dr.stdout.startswith("would move to the Recycle Bin: -gone-refused"),
   f"tidy --remove-history: nothing gone when refused; the Recycle Bin by its name on Windows "
   f"({r.stdout!r}, {dr.stdout!r})")
shutil.rmtree(croot / "-gone-refused")
(croot / "-gone-nobin").mkdir()
(croot / "-gone-nobin" / "n.jsonl").write_text(json.dumps({"cwd": "/gone/nobin"}) + "\n")
probe = ("import sys, shutil; sys.path.insert(0, sys.argv[1]); import aht; "
         "aht._to_trash = lambda p: shutil.rmtree(p) or 'deleted'; "
         "sys.exit(aht.main(sys.argv[2:]))")
r = subprocess.run([PY, "-c", probe, str(HERE.parent), "tidy", "--remove-history=-gone-nobin",
                    "--apply"], env=env, capture_output=True, text=True)
ck(r.returncode == 0 and r.stdout.startswith("deleted for good, since it could not go to the "
                                             "Recycle Bin: -gone-nobin")
   and not (croot / "-gone-nobin").exists(),
   f"tidy --remove-history: says so when Windows deleted it for good ({r.stdout.strip()})")
# Linux without gio: the desktop's Trash, with what the file manager needs to
# put it back
_xdg = os.environ.get("XDG_DATA_HOME")
os.environ["XDG_DATA_HOME"] = str(sb / "xdg")
try:
    gone = []
    for _ in range(2):
        o = sb / "fd-orphan"
        o.mkdir()
        (o / "s.jsonl").write_text("{}\n")
        gone.append(core._freedesktop_trash(o) and not o.exists())
finally:
    if _xdg is None:
        os.environ.pop("XDG_DATA_HOME", None)
    else:
        os.environ["XDG_DATA_HOME"] = _xdg
ftr = sb / "xdg" / "Trash"
finfo = (ftr / "info" / "fd-orphan.trashinfo").read_text() \
    if (ftr / "info" / "fd-orphan.trashinfo").is_file() else ""
ck(gone == [True, True] and (ftr / "files" / "fd-orphan" / "s.jsonl").is_file()
   and (ftr / "files" / "fd-orphan.2").is_dir()
   and (ftr / "info" / "fd-orphan.2.trashinfo").is_file()
   and finfo.startswith("[Trash Info]\nPath=" + __import__("urllib.parse").parse.quote(
       str(sb / "fd-orphan")) + "\nDeletionDate=20"),
   f"tidy --remove-history on Linux: into the desktop's Trash, a second one by another "
   f"name ({gone}, {finfo!r})")

# Claude Code's own continue-after-the-limit, switched from aht
run("limits", "--auto-continue", "on")
st = json.loads((tools / "settings.json").read_text())
ck(st.get("autoContinueAtUsageLimit") is True and st.get("remoteControlAtStartup") is True
   and JS("limits", "--json").get("auto_continue") is True,
   "limits --auto-continue: Claude Code's setting, the others left as they were")

done()
