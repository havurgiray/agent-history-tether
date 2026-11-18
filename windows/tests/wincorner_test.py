#!/usr/bin/env python3
"""The session corner's rules, on any OS (windows/src/wincorner.py: the model
imports anywhere; only its window needs Windows): what state a session is in
and since when, "done" until it is looked at and kept across a restart, a
record caught mid-write, the name it shows, the order, the sessions handed
over to another machine, the right-click menu, what Send to asks, what the
workspace's Save, Restore and Restart say, what Update Claude Code asks and
reports, and that a second click on an action does nothing while its look
ahead or its question is open (the corner without its window).

    python windows/tests/wincorner_test.py
"""
import json
import sys
import tempfile
import threading
import types
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="backslashreplace")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "windows" / "src"))
sys.path.insert(0, str(ROOT))
import aht  # noqa: E402
import wincorner as C  # noqa: E402

failed = 0
WS = ["save-workspace", "workspaces", "restart-workspace", "hide"]   # every menu ends so


def ck(name, ok, detail=""):
    global failed
    print(("  PASS " if ok else "  FAIL ") + name + (f" ({detail})" if detail and not ok else ""))
    failed += 0 if ok else 1


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def rec(sid, status, cwd="C:\\w\\proj", at=None, **kw):
    r = {"sessionId": sid, "status": status, "cwd": cwd}
    if at is not None:
        r["statusUpdatedAt"] = at * 1000
    r.update(kw)
    return r


print("\n[ages]")
ck("under a minute is now", C.age(59) == "now")
ck("minutes, hours, days", (C.age(61), C.age(3 * 3600 + 5), C.age(2 * 86400)) == ("1m", "3h", "2d"))

with tempfile.TemporaryDirectory() as td:
    home, run = Path(td) / "claude", Path(td) / "run"
    clock = Clock(1_000_000.0)
    live, moving = [], []
    m = C.Model(home, run, records=lambda: live, clock=clock, moving=lambda: moving)

    print("\n[states]")
    live[:] = [(10, rec("s1", "busy", at=clock.t - 120))]
    m.poll()
    r = m.rows[0]
    ck("a working session: working, for as long as it works", (r.state, r.age) == ("working", "2m"),
       (r.state, r.age))
    clock.t += 60
    live[:] = [(10, rec("s1", "idle", at=clock.t))]
    m.poll()
    ck("…then idle: done, from now", (m.rows[0].state, m.rows[0].age) == ("done", "now"))
    ck("the mark is kept in the run folder", "s1" in json.loads((run / "corner.json").read_text())["done"])
    m2 = C.Model(home, run, records=lambda: live, clock=clock, moving=lambda: [])
    m2.poll()
    ck("…and outlasts a restart", m2.rows[0].state == "done")
    m.seen("s1")
    m.poll()
    ck("looked at: idle, no age", (m.rows[0].state, m.rows[0].age) == ("idle", ""))

    print("\n[background sessions]")
    mb = C.Model(home, run, records=lambda: live, clock=clock, moving=lambda: [])
    # a tab that parked its conversation as a background job: its own status
    # froze ("busy"); the job is where the conversation runs
    live[:] = [(20, rec("tab", "busy", at=clock.t - 7200, kind="interactive", parkedJobId="j1")),
               (21, rec("job", "waiting", at=clock.t - 30, kind="bg", jobId="j1")),
               (22, rec("solo", "busy", at=clock.t - 60, kind="bg", jobId="j2"))]
    mb.poll()
    ck("background sessions have no row; the tab that parked one has one",
       [r.id for r in mb.rows] == ["tab"], [r.id for r in mb.rows])
    ck("…showing the state of the conversation it parked, not its own frozen one",
       (mb.rows[0].state, mb.rows[0].status, mb.rows[0].pid) == ("waiting", "waiting", 20),
       (mb.rows[0].state, mb.rows[0].status, mb.rows[0].pid))
    live[:] = [(20, rec("tab", "busy", at=clock.t - 7200, kind="interactive", parkedJobId="gone"))]
    mb.poll()
    ck("…and its own state when that job is no longer there", mb.rows[0].state == "working")
    live[:] = [(10, rec("s1", "waiting", at=clock.t - 200))]
    m.poll()
    ck("waiting for you, since when it began to", (m.rows[0].state, C.right_text(m.rows[0]))
       == ("waiting", "waits 3m"), C.right_text(m.rows[0]))
    live[:] = [(10, None)]
    m.poll()
    ck("a record caught mid-write: the session as it was", m.rows and m.rows[0].state == "waiting")
    live[:] = []
    m.poll()
    ck("a session that ended leaves the list", m.rows == [])

    print("\n[names]")
    proj = home / "projects" / aht._key_claude("C:\\w\\named")
    proj.mkdir(parents=True)
    tr = proj / "s2.jsonl"
    tr.write_text(json.dumps({"type": "ai-title", "aiTitle": "Fix the build"}) + "\n", encoding="utf-8")
    live[:] = [(11, rec("s2", "idle", cwd="C:\\w\\named", name="peer-7"))]
    m.poll()
    ck("Claude's own title, not the peer name", m.rows[0].name == "Fix the build", m.rows[0].name)
    with open(tr, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"type": "custom-title", "customTitle": "Release"}) + "\n")
    m.poll()
    ck("a title given later wins (only the new part is read)", m.rows[0].name == "Release")
    live[:] = [(12, rec("s3", "idle", cwd="C:\\w\\other", name="Mine", nameSource="user"))]
    m.poll()
    ck("a name you gave in the record, when the file has none", m.rows[0].name == "Mine")
    live[:] = [(13, rec("s4", "idle", cwd="C:\\w\\plain\\"))]
    m.poll()
    ck("else the folder's name", m.rows[0].name == "plain", m.rows[0].name)

    print("\n[order]")
    live[:] = [(20, rec("a", "idle", cwd="C:\\a", at=clock.t - 50)),
               (21, rec("b", "busy", cwd="C:\\b", at=clock.t - 500)),
               (22, rec("c", "busy", cwd="C:\\c", at=clock.t - 100)),
               (23, rec("d", "idle", cwd="C:\\d", at=clock.t - 10)),
               (24, rec("d", "idle", cwd="C:\\d", at=clock.t - 10))]
    m.poll()
    ck("working first, the one that started last on top; then by when they last worked; "
       "one row per session", [r.id for r in m.rows] == ["c", "b", "d", "a"], [r.id for r in m.rows])
    ck("the summary", m.summary() == "2 working", m.summary())

    print("\n[handed over]")
    m.away = [{"id": "away:x", "name": "paper", "project": "C:\\w\\paper", "machine": "homebox",
               "state": "working", "since": clock.t - 300, "can_open": True}]
    live[:] = []
    m.poll()
    r = m.rows[0]
    ck("a session on another machine, with where it is", (r.kind, r.state, C.right_text(r))
       == ("away", "working", "→ homebox 5m"), C.right_text(r))
    clock.t += 30
    m.away = [dict(m.away[0], state="idle", since=clock.t)]
    m.poll()
    ck("…done there is done here too", m.rows[0].state == "done")
    m.away = [dict(m.away[0], state="unknown", since=None)]
    m.poll()
    ck("…its machine not heard lately: a question mark",
       (m.rows[0].state, C.right_text(m.rows[0])) == ("unknown", "→ homebox ?"), C.right_text(m.rows[0]))
    ck("…and its mark waits", "away:x" in m.done)

    print("\n[on its way]")
    m.away = []
    moving[:] = [{"kind": "handover", "project": "C:\\w\\paper", "remote": "homebox",
                  "session": "x", "uuid": "u1", "stage": "checking homebox …", "started": clock.t}]
    m.poll()
    r = m.rows[0]
    ck("a session on its way there has a row of its own, with the stage before data moves",
       (r.kind, C.right_text(r), C.transfer_text(r.transfer))
       == ("away", "→ homebox", "Checking homebox …"), (r, C.transfer_text(r.transfer)))
    moving[0].update(stage="installing Claude Code 2.1.9 on homebox …", percent=30, eta=63)
    m.poll()
    ck("…a step that only takes time: how long it still takes, from the last time",
       C.transfer_text(m.rows[0].transfer)
       == "Installing Claude Code 2.1.9 on homebox … · 1 min left", C.transfer_text(m.rows[0].transfer))
    moving[0].update(over=True, eta=None)
    m.poll()
    ck("…and when it takes longer than that, it says so",
       C.transfer_text(m.rows[0].transfer).endswith("taking longer than before"))
    moving[0].update(over=False)
    moving[0].update(stage="sending the project to homebox …", percent=45,
                     done_bytes=45 << 20, total_bytes=100 << 20, eta=95)
    m.poll()
    r = m.rows[0]
    ck("…then how much went, of how much, and how long it still takes",
       C.right_text(r) == "→ homebox 45%"
       and C.transfer_text(r.transfer) == "45.0 MB of 100.0 MB · 2 min left" and "1 on the way"
       in m.summary(),
       (C.right_text(r), C.transfer_text(r.transfer)))
    ck("…and nothing to open until it is there",
       [x[1] for x in C.menu_items(r, ["homebox"]) if x != "-"] == [None] + WS)
    moving[:] = []
    m.poll()
    ck("once it is there: the handed-over sessions are listed again", m.away_stale and not m.rows)
    m.away_stale = False
    m.away = [{"id": "away:x", "name": "paper", "project": "C:\\w\\paper", "machine": "homebox",
               "state": "idle", "since": clock.t, "can_open": True}]
    moving[:] = [{"kind": "reclaim", "project": "C:\\w\\paper", "remote": "homebox",
                  "uuid": "u1", "percent": 80, "done_bytes": 2048, "total_bytes": 2560, "eta": 5}]
    m.poll()
    r = m.rows[0]
    ck("Take Back: on the session's own row, coming back",
       len(m.rows) == 1 and C.right_text(r) == "← homebox 80%"
       and C.transfer_text(r.transfer) == "2 KB of 2 KB · under a minute left",
       (m.rows, C.transfer_text(r.transfer)))
    moving[:] = []

    print("\n[menu]")
    ck("beside the sessions: the workspace saved, restored, restarted, and the list hidden",
       [x[1] for x in C.list_items() if x != "-"] == WS
       and [x[0] for x in C.list_items() if x != "-"][:3]
       == ["Save Workspace Now", "Restore Workspace…", "Restart Workspace…"], C.list_items())
    ck("while a restart is under way it is not offered a second time",
       [x[1] for x in C.list_items(True) if x != "-"] == WS[:2] + [None, "hide"]
       and "under way" in C.list_items(True)[2][0])
    idle = C.Row(id="s", pid=5, name="n", kind="here", status="idle", state="idle")
    busy = C.Row(id="s", pid=5, name="n", kind="here", status="busy", state="working")
    acts = [x[1] for x in C.menu_items(idle, ["homebox", "pc"]) if x != "-"]
    ck("an idle session: Go to Tab, Branch, its project's backups, Send to each machine, Hide",
       acts == ["goto", "branch", "backup-now", "backups", "send:homebox", "send:pc"] + WS, acts)
    labels = [x[0] for x in C.menu_items(busy, ["homebox"]) if x != "-"]
    grey = [x[1] for x in C.menu_items(busy, ["homebox"]) if x != "-"]
    ck("a working one: Branch and Send wait, and say so",
       grey == ["goto", None, "backup-now", "backups", None] + WS
       and "once it has finished" in labels[1], labels)
    none = C.menu_items(idle, [])
    at = next((i for i, x in enumerate(none) if x != "-" and x[0].startswith("Send to Another")), 0)
    ck("no machine set up: Send says where to add one, in a group of its own",
       none[at] == ("Send to Another Machine (add one in the Machines tab first)", None, False)
       and none[at - 1] == "-" and none[at + 1] == "-", none)
    some = C.menu_items(idle, ["homebox"])
    ck("…as with a machine set up: a line before Send, not two",
       some[some.index(("Send to homebox…", "send:homebox", False)) - 1] == "-"
       and not any(a == b == "-" for a, b in zip(some, some[1:])), some)
    away = C.Row(id="away:x", name="paper", kind="away", can_open=False, machine="pc")
    ck("a handed-over one: Open Session (here not possible) and Take Back",
       [x[1] for x in C.menu_items(away, []) if x != "-"] == [None, "take-back"] + WS)

    print("\n[workspace]")
    ck("Save Workspace Now says how much it holds",
       C.saved_text({"saved": "x.json", "tabs": 1, "sessions": 3})
       == "Workspace saved: 1 tab, 3 sessions")
    ck("…or why nothing was saved",
       C.saved_text({"saved": None, "why": "is Windows Terminal running?"})
       == "Workspace not saved: is Windows Terminal running?")
    WT = "Windows Terminal"
    OPENING = ("aht saves the workspace, ends every Claude session, closes Windows Terminal and "
               "starts it again with the same windows and tabs. Each session comes back in its "
               "tab, where it left off, with the options it had. Anything typed but not sent is "
               "lost, and so is the text the tabs show now.")
    CLOSING = "Yes closes Windows Terminal and opens the workspace again. No leaves everything as it is."
    full = {"applied": False, "terminal": WT, "blockers": [], "sessions": ["paper", "notes"],
            "working": ["build", "tests"], "tabs": 6, "plain": 2,
            "ending": ["npm run dev (Server)", "ssh homebox (Remote)"], "asks": True}
    q = C.restart_question(full).split("\n\n")
    ck("Restart Workspace asks: the terminal closes and the workspace opens again; what "
       "comes back, what stops, what does not come back",
       q == ["Close Windows Terminal and open the workspace again?", OPENING,
             "Sessions: paper, notes", "Working now, their task stops: build, tests",
             "2 plain tabs come back empty, in their folders.",
             "Ends and does not come back: npm run dev (Server); ssh homebox (Remote)",
             "Windows Terminal asks once more whether to quit: say yes there.", CLOSING], q)
    bare = {"applied": False, "terminal": WT, "blockers": [], "sessions": [], "working": [],
            "tabs": 1, "plain": 0, "ending": [], "asks": False}
    ck("…nothing to name: what happens, and what Yes and No do",
       C.restart_question(bare).split("\n\n")
       == ["Close Windows Terminal and open the workspace again?", OPENING, CLOSING],
       C.restart_question(bare))
    ck("…each paragraph only when there is something for it",
       [C.restart_question(dict(bare, **{k: full[k]})).split("\n\n")[2:-1]
        for k in ("sessions", "working", "plain", "ending", "asks")]
       == [["Sessions: paper, notes"], ["Working now, their task stops: build, tests"],
           ["2 plain tabs come back empty, in their folders."],
           ["Ends and does not come back: npm run dev (Server); ssh homebox (Remote)"],
           ["Windows Terminal asks once more whether to quit: say yes there."]])
    ck("…one plain tab, in its folder",
       C.restart_question(dict(bare, plain=1)).split("\n\n")[2:-1]
       == ["1 plain tab comes back empty, in its folder."])
    many = [f"p{i} (T{i})" for i in range(1, 10)]
    ck("…six programs that end are named, the others counted; six fit as they are",
       C.restart_question(dict(bare, ending=many)).split("\n\n")[2]
       == "Ends and does not come back: p1 (T1); p2 (T2); p3 (T3); p4 (T4); p5 (T5); p6 (T6) "
          "and 3 more"
       and C.restart_question(dict(bare, ending=many[:6])).split("\n\n")[2]
       == "Ends and does not come back: " + "; ".join(many[:6])
       and C.restart_question(dict(bare, ending=many[:7])).split("\n\n")[2].endswith(
           "p6 (T6) and 1 more"))
    q = C.restart_question({"sessions": ["a"]}).split("\n\n")
    ck("…a terminal without a name is “the terminal”",
       q[0] == "Close the terminal and open the workspace again?"
       and "closes the terminal and starts it again" in q[1]
       and q[-1] == "Yes closes the terminal and opens the workspace again. "
                    "No leaves everything as it is.", q)
    ck("it cannot restart: why, or that aht gave no answer",
       [C.not_restarted(x) for x in (None, {})] == ["Workspace not restarted: aht gave no answer"] * 2
       and C.not_restarted({"terminal": WT, "blockers": [
           "Windows Terminal is not open: Restore Workspace opens a saved workspace", "two"]})
       == "Workspace not restarted: Windows Terminal is not open: Restore Workspace opens a "
          "saved workspace")
    ck("once through: how many opened again, of how many",
       C.restarted_text({"applied": True, "terminal": WT, "blockers": [], "opened": 5, "of": 5,
                         "workspace": "x.json"}) == "Workspace restarted: 5 opened again"
       and C.restarted_text({"applied": True, "blockers": ["tab 3 did not open"], "opened": 4,
                             "of": 5}) == "Workspace restarted: 4 of 5 opened again"
       and C.restarted_text({"applied": True, "blockers": [], "opened": 4, "of": 5})
       == "Workspace restarted: 4 of 5 opened again"
       and C.restarted_text({"applied": True, "blockers": ["a tab is slow"], "opened": 5, "of": 5})
       == "Workspace restarted: 5 of 5 opened again")
    ck("…none: the first reason, or that nothing opened; no answer is said",
       C.restarted_text({"applied": False, "blockers": ["boom", "bang"], "opened": 0, "of": 5})
       == "Workspace not restarted: boom"
       and C.restarted_text({"blockers": ["boom"]}) == "Workspace not restarted: boom"
       and C.restarted_text({"applied": True, "blockers": [], "opened": 0, "of": 5})
       == "Workspace not restarted: nothing opened"
       and [C.restarted_text(x) for x in (None, {})]
       == ["Workspace not restarted: aht gave no answer"] * 2)
    ck("what went wrong, for a message: nothing when all came back",
       C.restart_trouble({"applied": True, "blockers": [], "opened": 5, "of": 5}) is None
       and C.restart_trouble({"applied": True, "opened": 4, "of": 5}) is None)
    ck("…no answer at all is said",
       [C.restart_trouble(x) for x in (None, {})]
       == [("Workspace not restarted", "aht gave no answer — see the log (Settings).")] * 2)
    ck("…some came back: each reason a sentence of its own",
       C.restart_trouble({"applied": True, "opened": 4, "of": 5, "blockers": [
           "tab 3 (notes) did not open", "aht could not end build.", "Windows Terminal took long",
           "iTerm2 is not here", "RuntimeError: bang", "aht's copy is old", "is it running?"]})
       == ("Not everything came back",
           "Tab 3 (notes) did not open.\n\naht could not end build.\n\nWindows Terminal took "
           "long.\n\niTerm2 is not here.\n\nRuntimeError: bang.\n\naht's copy is old.\n\n"
           "Is it running?"))
    ck("…nothing came back: under “not restarted”",
       C.restart_trouble({"applied": False, "opened": 0, "of": 5, "blockers": ["the terminal "
                          "did not start again"]})
       == ("Workspace not restarted", "The terminal did not start again.")
       and C.restart_trouble({"blockers": ["boom"]}) == ("Workspace not restarted", "Boom."))
    part = {"restarted": ["a", "b"], "failed": [{"session": "c", "why": "its tab is gone"}],
            "not_waited": []}
    ck("a restart in the tabs (after an update): which did not restart, each with why",
       C.restart_problems({"restarted": ["a"], "failed": [], "not_waited": []}) is None
       and C.restart_problems({"blockers": ["boom"]}) is None
       and C.restart_problems(part) == "c: its tab is gone"
       and C.restart_problems({"restarted": [], "failed": [{"session": "b", "why": "w"}],
                               "not_waited": ["c"]})
       == "b: w\n\nc: it was still working, so aht left it as it is")

    print("\n[update Claude Code]")
    plan = {"how": "winget", "command": ["winget", "upgrade", "Anthropic.ClaudeCode"],
            "before": "2.1.0", "while_running": False, "blockers": [],
            "restart": {"now": ["paper", "notes"], "after": ["build"],
                        "left_out": [{"session": "me", "why": "it is not in a tab"},
                                     {"session": "bg", "why": "it runs in the background"}]}}
    q = C.update_question(plan).split("\n\n")
    ck("the question: what updates it, what happens to the sessions, which, which not",
       q[0] == "aht updates Claude Code 2.1.0 with winget, the way it was installed."
       and q[1].startswith("winget cannot replace Claude Code while it runs, so every open "
                           "Claude session ends first, once it is idle,")
       and q[1].endswith("Anything typed into a session but not sent is lost.")
       and q[2:] == ["Sessions: paper, notes, build",
                     "Left as they are: me (it is not in a tab); bg (it runs in the background)",
                     "A notice says when it is done.", "Yes updates. No changes nothing."]
       and "upgrade" not in "".join(q), q)
    q = C.update_question({"command": ["x"], "restart": {}}).split("\n\n")
    ck("…an installer that replaces it while it runs; no version, no name, no session",
       q == ["aht updates Claude Code with its installer, the way it was installed.",
             "If that brings a newer version, every open Claude session ends and starts again "
             "in its tab, where it left off, with the options it had: an idle one at once, a "
             "working one once it is idle. Anything typed into a session but not sent is lost.",
             "A notice says when it is done.", "Yes updates. No changes nothing."], q)
    ck("…and the same with while_running true",
       C.update_question(dict(plan, while_running=True)).split("\n\n")[1] == q[1])
    ck("no question when aht gave no answer, refuses, or names no command",
       [C.update_refusal(x) for x in (None, {}, [1], "x", {"how": "winget"})] == [C.NO_ANSWER] * 5
       and C.NO_ANSWER == "aht gave no answer — see the log (Settings)."
       and C.NOT_UPDATED == "Claude Code was not updated"
       and C.update_refusal({"command": ["x"], "blockers": ["one", "two"]}) == "one\n\ntwo"
       and C.update_refusal(plan) is None)
    ck("the result: nothing to say when all went well (the core's notice says it)",
       C.update_problems({"applied": True, "updated": True, "before": "2.1.0", "after": "2.2.0",
                          "blockers": [], "warnings": [],
                          "restart": {"restarted": ["a"], "failed": [], "not_waited": []}}) is None
       and C.update_problems({"applied": True, "updated": False, "restart": None}) is None)
    ck("…no answer at all is said",
       [C.update_problems(x) for x in (None, {}, [], "x")] == [(C.NOT_UPDATED, C.NO_ANSWER)] * 4)
    ck("…a refusal, under “was not updated”",
       C.update_problems({"applied": False, "updated": False, "blockers": ["a restart or an update "
                          "of Claude Code is already under way"]})
       == ("Claude Code was not updated",
           "a restart or an update of Claude Code is already under way"))
    ck("…updated, yet not every session came back: the warnings and each session with why",
       C.update_problems({"applied": True, "updated": True, "after": "2.2.0", "blockers": [],
                          "warnings": ["w1"],
                          "restart": {"restarted": ["a"], "failed": [{"session": "b", "why": "y"}],
                                      "not_waited": ["c"]}})
       == ("Claude Code updated to 2.2.0",
           "w1\n\nb: y\n\nc: it was still working, so aht left it as it is"))

    print("\n[a second click]")
    # the corner without its window: nothing is drawn, a thread's work runs
    # at once, and what it hands to the window's thread waits in `handed`
    if not hasattr(C, "WNDPROC"):
        C.WNDPROC = lambda fn: fn
    handed, asked, told, noted, calls = [], [], [], [], []

    class Quiet(C.Corner):
        def place(self, force=False):
            pass

        def post(self, fn):
            handed.append(fn)

    class Inline:
        def __init__(self, target, daemon=None):
            self.target = target

        def start(self):
            self.target()

    def ask(title, text, no_default=False):
        # the question is open: what the menu says now, and a second click
        asked.append((title, text, no_default, c.items()[2]))
        c.restart_workspace()
        return answers.pop(0)

    def restart_workspace(apply=False):
        calls.append("apply" if apply else "plan")
        if isinstance(plans[0], Exception):
            raise plans.pop(0)
        return plans.pop(0)

    def looked(what, **kw):
        calls.append(what)
        return {"blockers": ["not now"]}

    live[:] = []
    m.note = None
    c = Quiet(m, {"ask": ask, "tell": lambda t, x: told.append((t, x)),
                  "note": lambda what, e: noted.append((what, type(e).__name__))}, run)
    kept = (C.threading, aht.restart_workspace, aht.branch_session, aht.send_session)
    C.threading = types.SimpleNamespace(Thread=Inline, Lock=threading.Lock)
    aht.restart_workspace = restart_workspace
    aht.branch_session = lambda pid, *a, **kw: looked(("branch", pid))
    aht.send_session = lambda pid, to, **kw: looked(("send", pid, to))
    GREY = ("Restart Workspace (under way)", None, False)
    CLOSES = "Restarting the workspace: closing Windows Terminal…"
    try:
        plan = {"applied": False, "terminal": WT, "blockers": [], "sessions": ["a", "b"],
                "working": ["c"], "tabs": 4, "plain": 1, "ending": [], "asks": False}
        plans = [plan, {"applied": True, "terminal": WT, "opened": 3, "of": 4,
                        "workspace": "x.json", "blockers": ["tab 4 (notes) did not open"]}]
        answers = [True]
        c.restart_workspace()
        ck("Restart Workspace: while it looks at the workspace the menu shows it under way",
           c.items()[2] == GREY and c.items(idle)[-3] == GREY
           and m.note == "Looking at the workspace…", (c.items(), m.note))
        c.restart_workspace()
        ck("…and a second click does nothing", len(handed) == 1 and calls == ["plan"],
           (len(handed), calls))
        handed.pop(0)()
        ck("…nor one while its question is open; No is what Enter presses",
           asked == [("Restart Workspace", C.restart_question(plan), True, GREY)]
           and calls == ["plan", "apply"], (asked, calls))
        ck("…then it restarts: its note says the terminal closes, and stays",
           c.restarting and c.items()[2] == GREY and m.note == CLOSES, (c.restarting, m.note))
        clock.t += 90
        c.tick()
        c.restart_workspace()
        ck("…a minute and more later too, and it is still not offered again",
           m.note == CLOSES and len(handed) == 1, m.note)
        c.say("Workspace saved: 1 tab, 3 sessions")
        clock.t += 9
        c.tick()
        ck("…and it comes back after another action's note", m.note == CLOSES, m.note)
        handed.pop(0)()
        ck("…the result: how many of how many, and what did not come back, in a message and the log",
           not c.restarting and m.note == "Workspace restarted: 3 of 4 opened again"
           and told == [("Not everything came back", "Tab 4 (notes) did not open.")]
           and noted == [("Restart Workspace: Not everything came back: "
                          "Tab 4 (notes) did not open.", "NoneType")]
           and c.items()[2] == ("Restart Workspace…", "restart-workspace", False),
           (m.note, told, noted))
        clock.t += 21
        c.tick()
        ck("…a note that then goes, as any other", m.note is None, m.note)

        plans = [plan]
        answers = [False]
        c.restart_workspace()
        handed.pop(0)()
        ck("No: nothing restarts, and it is offered again",
           not c.restarting and not c.looking and not handed and m.note is None
           and calls.count("apply") == 1
           and c.items()[2][1] == "restart-workspace", (c.restarting, c.looking, m.note))
        plans = [dict(plan, blockers=["Windows Terminal is not open: Restore Workspace opens "
                                      "a saved workspace"])]
        c.restart_workspace()
        handed.pop(0)()
        ck("it cannot restart: no question, why is said, and it is offered again",
           m.note == "Workspace not restarted: Windows Terminal is not open: Restore Workspace "
                     "opens a saved workspace"
           and not c.looking and len(asked) == 2 and len(told) == 1, (m.note, c.looking))
        plans = [None]
        c.restart_workspace()
        handed.pop(0)()
        ck("aht gave no answer: no question, said, and offered again",
           m.note == "Workspace not restarted: aht gave no answer" and not c.looking
           and len(asked) == 2, (m.note, c.looking))
        plans = [RuntimeError("boom")]
        c.restart_workspace()
        handed.pop(0)()
        ck("the look ahead failed: said, noted, and offered again",
           m.note == "Workspace not restarted: RuntimeError: boom" and not c.looking
           and len(asked) == 2 and noted[-1] == ("the corner's Restart Workspace failed", "RuntimeError"),
           (m.note, noted))
        plans = [dict(plan, terminal=None), RuntimeError("bang")]
        answers = [True]
        c.restart_workspace()
        handed.pop(0)()
        said = m.note
        handed.pop(0)()
        ck("the restart failed: said, told, and offered again",
           said == "Restarting the workspace: closing the terminal…"
           and m.note == "Workspace not restarted: RuntimeError: bang" and not c.restarting
           and not c.looking and told[1:] == [("Workspace not restarted", "RuntimeError: bang.")],
           (said, m.note, c.restarting, told))
        plans = [plan, {"applied": True, "terminal": WT, "blockers": [], "opened": 4, "of": 4,
                        "workspace": "x.json"}]
        answers = [True]
        was = len(noted)
        c.restart_workspace()
        handed.pop(0)()
        handed.pop(0)()
        ck("all came back: said under the top line, and no message",
           m.note == "Workspace restarted: 4 opened again" and not c.restarting
           and len(told) == 2 and len(noted) == was, (m.note, told, noted))
        plans = [plan, None]
        answers = [True]
        c.restart_workspace()
        handed.pop(0)()
        handed.pop(0)()
        ck("the restart gave no answer: said, and told where to look",
           m.note == "Workspace not restarted: aht gave no answer" and not c.restarting
           and told[2:] == [("Workspace not restarted",
                             "aht gave no answer — see the log (Settings).")], (m.note, told))

        del calls[:]
        row = C.Row(id="s", pid=5, name="n", kind="here", status="idle", state="idle")
        other = C.Row(id="t", pid=6, name="o", kind="here", status="idle", state="idle")
        c.branch(row)
        c.branch(row)
        c.branch(other)
        ck("Branch: a second click while it gets ready does nothing; another session's does",
           calls == [("branch", "5"), ("branch", "6")] and len(handed) == 2, calls)
        handed.pop(0)()
        handed.pop(0)()
        said = m.note
        c.branch(row)
        ck("…why it cannot branch is said, and Branch is there again",
           said == "o: not now" and calls[-1] == ("branch", "5") and len(handed) == 1,
           (said, calls))
        handed.pop(0)()
        del calls[:]
        c.send(row, "homebox")
        c.send(row, "homebox")
        c.send(row, "pc")
        ck("Send to: one look ahead for a session, whatever is clicked meanwhile",
           calls == [("send", "5", "homebox")] and len(handed) == 1, calls)
        handed.pop(0)()
        ck("…why it cannot go is told, and Send is there again",
           told[-1] == ("“n” cannot go to homebox now", "not now") and not c.looking
           and m.note is None, (told[-1], c.looking, m.note))
    finally:
        C.threading, aht.restart_workspace, aht.branch_session, aht.send_session = kept

    print("\n[send to]")
    q = C.send_question({"label": "paper", "to": "homebox", "project": "C:\\w\\paper",
                         "handover": {"there_path": "/home/me/w/paper"}, "warnings": ["w1"]})
    ck("the question says what moves, where, and how it comes back",
       all(x in q for x in ("C:\\w\\paper", "/home/me/w/paper", "Take Back", "Note: w1")), q)
    ck("…and that the session goes on there",
       "this tab connects to it" in q and "a PC" not in q)
    q = C.send_question({"label": "paper", "to": "pc", "project": "C:\\w\\paper",
                         "handover": {"pc": True}})
    ck("a PC: no session starts there", "Continue here" in q)

print(f"\nWINCORNER RESULT: {'ALL PASS' if not failed else f'{failed} FAILED'}")
sys.exit(1 if failed else 0)
