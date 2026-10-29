#!/usr/bin/env python3
"""[20] a session carries its iTerm2 tab's title (what the Claude app shows)."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)

import later_kit

# what earlier sections left: [17]'s project "Across" (projX, tagged) with
# an earlier session there (the note a new session starts with); [18]'s
# folder of open sessions (rec); [19]'s hook_out
projX = later_kit.across_made()[0]
rec = tools / "sessions"
rec.mkdir(exist_ok=True)
def hook_out(payload, **extra):
    return subprocess.run([PY, LAUNCH, "hook"], env=dict(env, **extra), capture_output=True,
                          text=True, input=json.dumps(payload)).stdout

print("\n[20] a session carries its iTerm2 tab's title (what the Claude app shows)")
tabs_file = sb / "iterm-tabs.json"
tabs_file.write_text(json.dumps({"/dev/ttysT1": {"title": "Paper", "pane": 1, "panes": 1},
                                 "/dev/ttysT2": {"title": "Paper", "pane": 1, "panes": 1}}))
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
def tab_hook(event, sid, tty, pid, **extra):
    payload = {"hook_event_name": event, "session_id": sid, "cwd": projX,
               "transcript_path": str(tstore / f"{sid}.jsonl"), "source": "startup"}
    out = hook_out(payload, AHT_ITERM_TABS=str(tabs_file), AHT_TTY=tty,
                   AHT_CLAUDE_PID=str(pid), **extra).strip()
    try:
        return json.loads(out)["hookSpecificOutput"].get("sessionTitle")
    except Exception:
        return out or None
a = fake_claude("t1")
ck(tab_hook("SessionStart", "t1", "/dev/ttysT1", a.pid) == "Paper",
   "tab names: a new session takes its tab's title")
with open(tstore / "t1.jsonl", "a") as fh:
    fh.write(title_line("Paper", "t1"))
ck(tab_hook("UserPromptSubmit", "t1", "/dev/ttysT1", a.pid) is None,
   "tab names: nothing said while the name is right")
tabs_file.write_text(json.dumps({"/dev/ttysT1": {"title": "Paper v2", "pane": 1, "panes": 1},
                                 "/dev/ttysT2": {"title": "Paper v2", "pane": 1, "panes": 1}}))
ck(tab_hook("UserPromptSubmit", "t1", "/dev/ttysT1", a.pid) == "Paper v2",
   "tab names: a renamed tab renames the session at the next prompt")
with open(tstore / "t1.jsonl", "a") as fh:
    fh.write(title_line("Paper v2", "t1"))
b = fake_claude("t2")
ck(tab_hook("SessionStart", "t2", "/dev/ttysT2", b.pid) == "Paper v2 · 2",
   "tab names: a second open session with that title gets “· 2”")
c = fake_claude("t3")
(tstore / "t3.jsonl").write_text(json.dumps({"type": "user", "forkedFrom": {"sessionId": "t1"},
                                             "message": {"role": "user", "content": "x"}})
                                 + "\n" + title_line("Paper v2", "t3"))
ck(tab_hook("UserPromptSubmit", "t3", "/dev/ttysT2", c.pid) == "Paper v2 ⑂ 2",
   "tab names: a branch that inherited the name becomes “⑂ 2”")
d_ = fake_claude("t4", title="My own name")
ck(tab_hook("UserPromptSubmit", "t4", "/dev/ttysT1", d_.pid) is None,
   "tab names: a name the user gave the session stays")
tabs_file.write_text(json.dumps({"/dev/ttysT1": {"title": "Paper v3", "pane": 1, "panes": 1},
                                 "/dev/ttysT2": {"title": "Paper v2", "pane": 1, "panes": 1}}))
ck(tab_hook("UserPromptSubmit", "t4", "/dev/ttysT1", d_.pid) == "Paper v3",
   "tab names: renaming the tab afterwards wins over the name given before")
with open(tstore / "t4.jsonl", "a") as fh:
    fh.write(title_line("Paper v3", "t4"))
live = sb / "iterm-live.json"
live.write_text(json.dumps({"/dev/ttysT1": {"title": "Paper v4", "pane": 1, "panes": 1}}))
ck(tab_hook("UserPromptSubmit", "t4", "/dev/ttysT1", d_.pid, AHT_ITERM_LIVE=str(live))
   == "Paper v4",
   "tab names: the tab is looked at as it is now, not as aht last saw all tabs")
with open(tstore / "t4.jsonl", "a") as fh:
    fh.write(title_line("Paper v4", "t4") + title_line("Mine again", "t4"))
ck(tab_hook("UserPromptSubmit", "t4", "/dev/ttysT1", d_.pid, AHT_ITERM_LIVE=str(live)) is None,
   "tab names: a name given after the tab's rename stays")
# a long session: its name is found further back than the last part
with open(tstore / "t4.jsonl", "a") as fh:
    filler = json.dumps({"type": "assistant", "message": {"role": "assistant",
                                                         "content": "x" * 4000}}) + "\n"
    fh.write(filler * 100)
ck(tab_hook("UserPromptSubmit", "t4", "/dev/ttysT1", d_.pid, AHT_ITERM_LIVE=str(live)) is None,
   "tab names: in a long session the name it has is still found, so it stays")
tabs_file.write_text(json.dumps({"/dev/ttysT1": {"title": "Paper v2", "pane": 1, "panes": 1},
                                 "/dev/ttysT2": {"title": "Paper v2", "pane": 1, "panes": 1}}))
run("config", "--set", "tab_names=false")
e_ = fake_claude("t5")
ck(tab_hook("SessionStart", "t5", "/dev/ttysT1", e_.pid) is None,
   "tab names: off in the settings, nothing happens")
run("config", "--unset", "tab_names")
run("config", "--set", "informed_sessions=true")
f_ = fake_claude("t6")
raw = hook_out({"hook_event_name": "SessionStart", "session_id": "t6", "cwd": projX,
                "transcript_path": str(tstore / "t6.jsonl"), "source": "startup"},
               AHT_ITERM_TABS=str(tabs_file), AHT_TTY="/dev/ttysT1", AHT_CLAUDE_PID=str(f_.pid))
try:
    hso = json.loads(raw)["hookSpecificOutput"]
except Exception:
    hso = {}
ck(hso.get("sessionTitle", "").startswith("Paper v2")
   and "[aht] The latest earlier session" in hso.get("additionalContext", ""),
   f"tab names: the start notes travel with the name, as JSON ({raw[:120]!r})")
run("config", "--unset", "informed_sessions")
probe = ("import sys, json; sys.path.insert(0, sys.argv[1]); import aht; "
         "print(aht.handover_session_name('t1', '/x/Paper', 'homebox')); "
         "print(aht.handover_session_name('nobody', '/x/Paper', 'homebox'))")
r = subprocess.run([PY, "-c", probe, str(HERE.parent)], env=env, capture_output=True, text=True)
ck(r.stdout.split() == ["Paper", "v2", "@", "homebox", "Paper"],
   f"handover: the session there is “<tab title> @ <machine>” ({r.stdout.strip() or r.stderr[-200:]})")
# a name set in aht's window: at the next prompt, and it stays until handed back
run("tab-names", "--rename", "t1", "--to", "Budget work")
ck(tab_hook("UserPromptSubmit", "t1", "/dev/ttysT1", a.pid) == "Budget work",
   "rename: the name set in aht arrives at the session's next prompt")
with open(tstore / "t1.jsonl", "a") as fh:
    fh.write(title_line("Budget work", "t1"))
ck(tab_hook("UserPromptSubmit", "t1", "/dev/ttysT1", a.pid) is None,
   "rename: it stays, whatever the tab is called")
run("tab-names", "--rename", "t1", "--to", "")
ck(str(tab_hook("UserPromptSubmit", "t1", "/dev/ttysT1", a.pid)).startswith("Paper v2"),
   "rename: following the tab again brings the tab's title back")

# the other way round: a session renamed gives its tab the name (the latest act wins)
live2 = sb / "iterm-live2.json"
def tab_now(**kw):
    t = json.loads(live2.read_text())
    if kw:
        t["/dev/ttysT3"].update(kw)
        live2.write_text(json.dumps(t))
    return t["/dev/ttysT3"]["title"]
live2.write_text(json.dumps({"/dev/ttysT3": {"title": "Thesis", "override": True,
                                             "panes": 1, "id": "7"}}))
k_ = fake_claude("t9")
L = {"AHT_ITERM_LIVE": str(live2)}
def say(t):
    with open(tstore / "t9.jsonl", "a") as fh:
        fh.write(title_line(t, "t9"))
ck(tab_hook("SessionStart", "t9", "/dev/ttysT3", k_.pid, **L) == "Thesis",
   "tab names: a session in a third tab takes its title")
say("Thesis")
tab_hook("UserPromptSubmit", "t9", "/dev/ttysT3", k_.pid, **L)
say("Chapter 2")                                            # /rename
ck(tab_hook("UserPromptSubmit", "t9", "/dev/ttysT3", k_.pid, **L) is None
   and tab_now() == "Chapter 2",
   "tab names: a session renamed with /rename gives its tab the name")
say("Chapter 3")
ck(tab_hook("UserPromptSubmit", "t9", "/dev/ttysT3", k_.pid, AHT_ITERM_API_OFF="1", **L) is None
   and tab_now() == "Chapter 2"
   and tab_hook("UserPromptSubmit", "t9", "/dev/ttysT3", k_.pid, AHT_ITERM_API_OFF="1",
                **L) is None,
   "tab names: with iTerm2's Python API off the tab keeps its title, the session its name")
say("Chapter 4")
tab_now(title="Thesis final")
ck(tab_hook("UserPromptSubmit", "t9", "/dev/ttysT3", k_.pid, **L) == "Thesis final",
   "tab names: both renamed since the last look: the tab wins")
ck(tab_hook("UserPromptSubmit", "t9", "/dev/ttysT3", k_.pid, **L) is None
   and tab_now() == "Thesis final",
   "tab names: the name aht gave, not taken yet, is not mistaken for a rename")
say("Thesis final")
T = {"AHT_ITERM_TABS": str(tabs_file), "AHT_ITERM_LIVE": str(live2),
     "AHT_TTYS": json.dumps({str(k_.pid): "/dev/ttysT3"})}
d = JS("tab-names", "--rename", "t9", "--to", "Defence", "--json", extra_env=T)
ck(d.get("tab") == "" and tab_now() == "Defence",
   f"rename: aht's Rename… gives the tab the name right away ({d})")
ck(tab_hook("UserPromptSubmit", "t9", "/dev/ttysT3", k_.pid, **L) == "Defence",
   "rename: … and the session at its next prompt")
say("Defence")
tab_now(title="Viva")
ck(tab_hook("UserPromptSubmit", "t9", "/dev/ttysT3", k_.pid, **L) == "Viva",
   "rename: renaming the tab afterwards wins over a name set in aht")
say("Viva")
tab_now(panes=2)
d = JS("tab-names", "--rename", "t9", "--to", "Two panes", "--json", extra_env=T)
ck(d.get("tab") == "panes" and tab_now() == "Viva",
   "rename: a tab holding two sessions keeps its title (it would name both)")
r = run("tab-names", "--rename", "t9", "--to", "Off", extra_env=dict(T, AHT_ITERM_API_OFF="1"))
ck("Enable Python API" in r.stdout, f"rename: says how to let the tab take names ({r.stdout!r})")
run("tab-names", "--rename", "t9", "--to", "")

# a key in a tab's title: the session takes the title as it is, and at its
# next prompt the name still counts as the tab's (a name read from a history
# is masked where it is shown, not where it is compared), so the tab keeps it
live3 = sb / "iterm-live3.json"
tkey = "gh" + "p_" + "Kd8" * 12                         # made up, in pieces
live3.write_text(json.dumps({"/dev/ttysT4": {"title": f"Deploy {tkey}", "override": True,
                                             "panes": 1, "id": "9"}}))
n_ = fake_claude("t10")
L3 = {"AHT_ITERM_LIVE": str(live3)}
first = tab_hook("SessionStart", "t10", "/dev/ttysT4", n_.pid, **L3)
with open(tstore / "t10.jsonl", "a") as fh:
    fh.write(title_line(f"Deploy {tkey}", "t10"))
nxt = tab_hook("UserPromptSubmit", "t10", "/dev/ttysT4", n_.pid, **L3)
T4 = {"AHT_ITERM_TABS": str(live3), "AHT_TTYS": json.dumps({str(n_.pid): "/dev/ttysT4"})}
row = next((r for r in JS("tab-names", "--json", extra_env=T4).get("sessions", [])
            if r["session"] == "t10"), {})
ck(first == f"Deploy {tkey}" and nxt is None
   and json.loads(live3.read_text())["/dev/ttysT4"]["title"] == f"Deploy {tkey}"
   and row.get("origin") == "tab" and "[GitHub token: " in str(row.get("name"))
   and tkey not in str(row.get("name")),
   f"tab names: a key in a tab's title is compared as it is and shown masked; the tab "
   f"keeps its title ({first!r}, {nxt!r}, {row.get('name')!r}, {row.get('origin')})")
n_.kill(); n_.wait()
(rec / f"{n_.pid}.json").unlink()

# aht speaks iTerm2's Python API itself: a WebSocket on a Unix socket, protobuf in it
import socket as _so, threading as _th
def pb_varint(n):
    out = bytearray()
    while True:
        b, n = n & 0x7F, n >> 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)
def pb_len(num, b):
    b = b.encode() if isinstance(b, str) else b
    return pb_varint(num << 3 | 2) + pb_varint(len(b)) + b
def pb_read(buf):
    out, i = {}, 0
    def vi():
        nonlocal i
        n = s_ = 0
        while True:
            c_ = buf[i]; i += 1
            n |= (c_ & 0x7F) << s_; s_ += 7
            if not c_ & 0x80:
                return n
    while i < len(buf):
        key = vi(); w = key & 7
        if w == 0:
            v = vi()
        elif w == 1:
            v = buf[i:i + 8]; i += 8
        else:
            n = vi(); v = buf[i:i + n]; i += n
        out.setdefault(key >> 3, []).append(v)
    return out
def fake_iterm(path, answer, seen):
    srv = _so.socket(_so.AF_UNIX, _so.SOCK_STREAM)
    srv.bind(str(path)); srv.listen(1)
    def serve():
        conn, _ = srv.accept()
        f = conn.makefile("rb")
        head = b""
        while not head.endswith(b"\r\n\r\n"):
            head += f.readline()
        seen["head"] = head.decode()
        conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                     b"Connection: Upgrade\r\nSec-WebSocket-Protocol: api.iterm2.com\r\n\r\n")
        b0, b1 = f.read(2)
        mask, n = f.read(4), b1 & 0x7F
        seen["masked"] = bool(b1 & 0x80)
        seen["req"] = bytes(c_ ^ mask[i % 4] for i, c_ in enumerate(f.read(n)))
        conn.sendall(b"\x89\x00")                               # a ping first
        seen["pong"] = f.read(6)[:1] == b"\x8a"
        conn.sendall(bytes([0x82, len(answer)]) + answer)
        try:
            f.read(8)
        except OSError:
            pass
        conn.close(); srv.close()
    t = _th.Thread(target=serve, daemon=True); t.start()
    return t
api_sock = sb / "api.sock"
if not socket_fits(sb):
    print(f"  SKIP iTerm2 API: the sandbox's path is too long for a socket ({len(str(api_sock))} "
          f"characters where 103 is the most).  Run it with a shorter TMPDIR (for example "
          f"TMPDIR=/tmp).")
else:
    seen = {}
    ok_answer = pb_varint(1 << 3) + pb_varint(1) + pb_len(132, pb_len(2, pb_len(1, "null")))
    th = fake_iterm(api_sock, ok_answer, seen)
    tab_now(panes=1)
    probe = ("import sys; sys.path.insert(0, sys.argv[1]); import aht; "
             "print(repr(aht.set_tab_title('/dev/ttysT3', sys.argv[2])))")
    api_env = dict(env, AHT_ITERM_API=str(api_sock), AHT_ITERM_API_KEY="cookie1 key1",
                   AHT_ITERM_TABS=str(tabs_file), AHT_ITERM_LIVE=str(live2))
    r = subprocess.run([PY, "-c", probe, str(HERE.parent), 'A "b" \\(x) ⑂'], env=api_env,
                       capture_output=True, text=True, timeout=30)
    th.join(10)
    req = pb_read(seen.get("req", b""))
    inv = pb_read(req.get(132, [b""])[0])
    ck(r.stdout.strip() == "''" and seen.get("masked") and seen.get("pong")
       and "x-iterm2-cookie: cookie1" in seen.get("head", "")
       and "x-iterm2-key: key1" in seen.get("head", "")
       and "Sec-WebSocket-Protocol: api.iterm2.com" in seen.get("head", "")
       and req.get(1) == [1] and pb_read(inv.get(7, [b""])[0]).get(1) == [b"7"]
       and inv.get(5, [b""])[0].decode() == 'iterm2.set_title(title: "A “b” \\\\\\\\(x) ⑂")',
       f"iTerm2 API: the tab's title set as Edit Tab Title does ({r.stdout.strip()} "
       f"{r.stderr[-300:]} {inv})")
    api_sock.unlink()
    seen = {}
    bad = pb_varint(1 << 3) + pb_varint(1) + pb_len(
        132, pb_len(1, pb_varint(1 << 3) + pb_varint(4) + pb_len(2, "no such tab")))
    th = fake_iterm(api_sock, bad, seen)
    r = subprocess.run([PY, "-c", probe, str(HERE.parent), "X"], env=api_env,
                       capture_output=True, text=True, timeout=30)
    th.join(10)
    ck("no such tab" in r.stdout, f"iTerm2 API: its refusal is reported ({r.stdout.strip()})")
    api_sock.unlink()
    r = subprocess.run([PY, "-c", probe, str(HERE.parent), "X"], env=api_env,
                       capture_output=True, text=True, timeout=30)
    ck(r.stdout.strip() == "'api-off'", f"iTerm2 API: switched off, said so ({r.stdout.strip()})")
for pr in (a, b, c, d_, e_, f_, k_):
    pr.kill(); pr.wait()
    (rec / f"{pr.pid}.json").unlink()

# name every open session after its tab, also one named otherwise
tabs_file.write_text(json.dumps({"/dev/ttysT1": {"title": "Alpha", "pane": 1, "panes": 1},
                                 "/dev/ttysT2": {"title": "Alpha", "pane": 1, "panes": 1}}))
g = fake_claude("t7", title="Draft")
h = fake_claude("t8")
tenv = {"AHT_ITERM_TABS": str(tabs_file),
        "AHT_TTYS": json.dumps({str(g.pid): "/dev/ttysT1", str(h.pid): "/dev/ttysT2"})}
d = JS("tab-names", "--sync-all", "--json", extra_env=tenv)
plan = sorted((x["from"] or "", x["to"]) for x in d.get("plan", []))
ck(plan == [("", "Alpha · 2"), ("Draft", "Alpha")] and not d.get("applied"),
   f"sync all: every session with a tab title takes it, a clash gets “· 2” ({plan})")
rows = {r["session"]: r for r in JS("tab-names", "--json", extra_env=tenv).get("sessions", [])}
ck(rows.get("t7", {}).get("origin") == "yours" and rows["t7"].get("tab") == "Alpha",
   f"tab names: the list says where each name came from ({rows.get('t7')})")
JS("tab-names", "--sync-all", "--apply", "--json", extra_env=tenv)
ck(tab_hook("UserPromptSubmit", "t7", "/dev/ttysT1", g.pid) == "Alpha",
   "sync all: applied at the next prompt, also over a name the user gave")
for pr in (g, h):
    pr.kill(); pr.wait()
    (rec / f"{pr.pid}.json").unlink()

done()
