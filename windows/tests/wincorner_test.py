#!/usr/bin/env python3
"""The session corner's rules, on any OS (windows/src/wincorner.py: the model
imports anywhere; only its window needs Windows): what state a session is in
and since when, "done" until it is looked at and kept across a restart, a
record caught mid-write, the name it shows, the order, the sessions handed
over to another machine, the right-click menu, and what Send to asks.

    python windows/tests/wincorner_test.py
"""
import json
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="backslashreplace")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "windows" / "src"))
sys.path.insert(0, str(ROOT))
import aht  # noqa: E402
import wincorner as C  # noqa: E402

failed = 0


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
       [x[1] for x in C.menu_items(r, ["homebox"]) if x != "-"] == [None, "hide"])
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
    idle = C.Row(id="s", pid=5, name="n", kind="here", status="idle", state="idle")
    busy = C.Row(id="s", pid=5, name="n", kind="here", status="busy", state="working")
    acts = [x[1] for x in C.menu_items(idle, ["homebox", "pc"]) if x != "-"]
    ck("an idle session: Go to Tab, Branch, Send to each machine, Hide",
       acts == ["goto", "branch", "send:homebox", "send:pc", "hide"], acts)
    labels = [x[0] for x in C.menu_items(busy, ["homebox"]) if x != "-"]
    grey = [x[1] for x in C.menu_items(busy, ["homebox"]) if x != "-"]
    ck("a working one: Branch and Send wait, and say so",
       grey == ["goto", None, None, "hide"] and "once it has finished" in labels[1], labels)
    ck("no machine set up: Send says where to add one",
       any("add one in aht's window" in x[0] for x in C.menu_items(idle, []) if x != "-"))
    away = C.Row(id="away:x", name="paper", kind="away", can_open=False, machine="pc")
    ck("a handed-over one: Open Session (here not possible) and Take Back",
       [x[1] for x in C.menu_items(away, []) if x != "-"] == [None, "take-back", "hide"])

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
