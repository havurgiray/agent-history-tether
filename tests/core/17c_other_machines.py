#!/usr/bin/env python3
"""[17c] other machines: Watch, Search everywhere, sleep and silence."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)

# what earlier sections left: sqlite3, imported by [17] and [17b]
import sqlite3

print("\n[17c] other machines: Watch, Search everywhere, sleep and silence")
# box and empty are folders standing in for other machines (aht's core runs
# there with their own home); lab answers through the stand-in ssh but takes
# no key.  What would keep a machine awake is a stand-in that notes its
# calls: nothing here runs a real agent, ssh, caffeinate or systemd-inhibit
FIXTURES3 = HERE / "fixtures" / "phase3"
we = iso_env("machines")
wb = Path(we["HOME"]).parent
wbox, wempty, wfar = wb / "box", wb / "empty", wb / "far"
(wbox / "home" / ".claude" / "sessions").mkdir(parents=True)
(wempty / "home").mkdir(parents=True)
(wfar / "127.0.0.4" / "home").mkdir(parents=True)
(wfar / "127.0.0.4" / "path").write_text("/usr/bin:/bin")
(wfar / "127.0.0.4" / "refuse").write_text("Permission denied (publickey,password).\n")
wstub = wb / "stubs"
wstub.mkdir()
awlog = wb / "awake.log"
for _t in ("caffeinate", "systemd-inhibit"):
    # a quick try (`… true`, as `remote check` does) ends at once; a hold
    # waits, as the real ones do; with a "refused" file it fails as polkit can
    (wstub / _t).write_text(
        f'#!/bin/sh\necho "$$ {_t} $*" >> "{awlog}"\n'
        f'if [ -f "{wb / "refused"}" ]; then echo "Failed to inhibit: Access denied" >&2; '
        'exit 1; fi\nfor a; do last="$a"; done\n[ "$last" = true ] && exit 0\nexec sleep 600\n')
(wstub / "tmux").write_text(f'#!/bin/sh\nexec "{PY}" "{HERE / "fake_tmux.py"}" "$@"\n')
(wstub / "claude").write_text('#!/bin/sh\necho "9.9.9 (Claude Code)"\n')
(wstub / "ssh").write_text(f'#!/bin/sh\nexec "{PY}" "{HERE / "fake_ssh.py"}" "$@"\n')
for _f in wstub.iterdir():
    _f.chmod(0o755)
(wb / "no-tabs.json").write_text("{}")
wlog = wb / "notices.log"
we.update(AHT_MACHINE_NAME="mac", AHT_NOTIFY_LOG=str(wlog), AHT_NO_SEARCH_INDEX="1",
          AHT_ITERM_TABS=str(wb / "no-tabs.json"), AHT_CLAUDE=str(wstub / "claude"),
          AHT_REMOTE_PATH=str(wstub), FAKE_SSH_DIR=str(wfar),
          PATH=str(wstub) + os.pathsep + we["PATH"])
def W(*a, **extra):
    r = subprocess.run([PY, LAUNCH, *a], env=dict(we, **extra), capture_output=True, text=True)
    try:
        d = json.loads(r.stdout)
    except ValueError:
        d = {"unparsed": r.stdout[-400:] + r.stderr[-600:]}
    if isinstance(d, dict):
        d["_rc"] = r.returncode
    return d
def until(cond, secs=10.0):
    end = time.time() + secs
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.1)
    return bool(cond())
def holds(tool):
    """The stand-in `tool`s that hold this machine awake right now (pids)."""
    rows = [l.split() for l in awlog.read_text().splitlines()] if awlog.is_file() else []
    return [int(r[0]) for r in rows if len(r) > 2 and r[1] == tool and r[-1] != "true"
            and core._pid_alive(int(r[0]))]
wsleep = []
def sleeper():
    p = subprocess.Popen(["sleep", "600"], cwd="/")
    wsleep.append(p)
    return p
def say(rec, pid, cwd, status, waiting=None):
    rec.write_text(json.dumps({"pid": pid, "cwd": cwd, "sessionId": f"w{pid}", "status": status,
                               **({"waitingFor": waiting} if waiting else {})}))
fx3 = []
W("config", "--set", "remotes=" + json.dumps({"box": {"root": str(wbox)},
                                              "empty": {"root": str(wempty)},
                                              "lab": {"ssh": "me@127.0.0.4"}}))
# never sent: AHT_NOTIFY_LOG notes where it would go
W("config", "--set", "notify_phone=ntfy:aht-test-only")

st = W("status", "--json").get("handover") or {}
ck(st.get("can_reach") is True and st.get("supported") is (os.name != "nt"),
   f"status: can_reach wherever an ssh client is, supported as before ({st.get('can_reach')}, "
   f"{st.get('supported')})")
fx3 += fixture_ok({"handover": st}, "status.json", FIXTURES3)
d = W("remote", "list", "--json")
rows = d.get("remotes") or {}
ck(sorted(rows) == ["box", "empty", "lab"]
   and all(r.get("watch") is False and "system" in r and "last_heard" in r for r in rows.values()),
   f"remote list: each machine with watch, system and last_heard ({rows})")
fx3 += fixture_ok(d, "remote_list.json", FIXTURES3)
d = W("remote", "watch", "box", "--json")
fx3 += fixture_ok(d, "remote_watch.json", FIXTURES3)
wcfg = json.loads((wb / ".aht" / "config.json").read_text())
listed = subprocess.run([PY, LAUNCH, "remote"], env=we, capture_output=True, text=True).stdout
ck({k: d.get(k) for k in ("remote", "watch", "applied")}
   == {"remote": "box", "watch": True, "applied": True} and d["_rc"] == 0
   and wcfg["remotes"]["box"].get("watch") is True
   and any("box" in l and "(watched)" in l for l in listed.splitlines())
   and not any("lab" in l and "(watched)" in l for l in listed.splitlines()),
   f"remote watch: at once, kept in the config, listed as watched ({d}, {listed.strip()})")
d = W("remote", "watch", "nope", "--json")
ck(d["_rc"] == 2 and d.get("applied") is False and "unknown machine" in d.get("error", ""),
   f"remote watch: an unknown machine is an error ({d})")
W("config", "--set", "remotes=" + json.dumps(dict(wcfg["remotes"], pc={
    "ssh": "me@127.0.0.9", "system": "Windows"})))
d = W("remote", "watch", "pc", "--json")
ck(d["_rc"] == 0 and d.get("applied") is True and d.get("watch") is True,
   f"remote watch: a Windows PC can be watched now (it answers) ({d})")
W("config", "--set", "remotes=" + json.dumps(wcfg["remotes"]))

# notices: a session on the watched box, and one here; each names its machine
ppaper = str(wbox / "home" / "code" / "paper")
os.makedirs(ppaper)
here_p = os.path.realpath(str(wb / "home" / "code" / "notes"))
os.makedirs(here_p)
wsess = wb / "tools" / "sessions"
wsess.mkdir(parents=True, exist_ok=True)
bs, hs = sleeper(), sleeper()
brec = wbox / "home" / ".claude" / "sessions" / f"{bs.pid}.json"
hrec = wsess / f"{hs.pid}.json"
nstate = wb / ".aht" / "run" / "notices.json"
bjson = wb / ".aht" / "run" / "board.json"
def tick(**extra):
    """One notices check, as the notices agent runs it every half minute,
    with the machines' last-asked times cleared (each is asked every 55 s
    or every 2 minutes)."""
    if nstate.is_file():
        s = json.loads(nstate.read_text())
        s["asked"] = {}
        nstate.write_text(json.dumps(s))
    return W("notices", "--json", **extra).get("notices") or []
def told():
    return [json.loads(l) for l in wlog.read_text().splitlines()] if wlog.is_file() else []
say(brec, bs.pid, ppaper, "busy")
say(hrec, hs.pid, here_p, "busy")
tick()
say(brec, bs.pid, ppaper, "waiting", "approve Bash: make test")
say(hrec, hs.pid, here_p, "waiting", "approve Edit")
got = tick()
boxn = next((l for l in told() if l["title"] == "paper on box waits for you"), {})
ck(sorted(n["title"] for n in got) == ["notes on mac waits for you", "paper on box waits for you"]
   and boxn.get("message") == "approve Bash: make test"
   and boxn.get("phone") == "ntfy:aht-test-only",
   f"a watched box with a waiting session: “… on box waits for you”, to the phone too; a "
   f"notice here names this machine ({[n['title'] for n in got]}, {boxn})")
# box's own aht sends its notices to the phone: here they are only shown
(wbox / "home" / ".aht" / "run").mkdir(parents=True, exist_ok=True)
(wbox / "home" / ".aht" / "config.json").write_text(json.dumps({"notify_phone": "ntfy:aht-box"}))
(wbox / "home" / ".aht" / "run" / "notices.json").write_text(json.dumps(
    {"at": time.time(), "version": core.VERSION}))
say(brec, bs.pid, ppaper, "busy")
tick()
n0 = len(told())
say(brec, bs.pid, ppaper, "waiting", "approve Bash: make lint")
tick()
ck([(l["title"], l["phone"]) for l in told()[n0:]] == [("paper on box waits for you", "")],
   f"box's own notices ran within 3 minutes: the notice is not sent to the phone again "
   f"({told()[n0:]})")
# Watch off: box is asked no more (lab, never watched, never was)
heard0 = json.loads(bjson.read_text()).get("box", {}).get("heard")
W("remote", "watch", "box", "--off", "--json")
say(brec, bs.pid, ppaper, "busy")
got = tick()
s = json.loads(nstate.read_text())
ck(not got and "box" not in (s.get("asked") or {}) and heard0
   and json.loads(bjson.read_text()).get("box", {}).get("heard") == heard0
   and not (wfar / "127.0.0.4" / "commands.log").exists(),
   f"Watch off: the notices ask nothing ({got}, {s.get('asked')})")
W("remote", "watch", "box", "--json")
# what was seen on a machine no longer asked is forgotten: box's session,
# busy when Watch went off, finished meanwhile; with Watch on again that
# is a first sight, not “done after” all the hours box was not asked
tick()                                      # box asked again: its session works
W("remote", "watch", "box", "--off", "--json")
tick()
s = json.loads(nstate.read_text())
kept_box = [k for k in s.get("seen") or {} if k.startswith("box:")]
for k in kept_box:                          # had it been kept: busy since 4 hours
    if s["seen"][k].get("busy_since"):
        s["seen"][k]["busy_since"] -= 4 * 3600
nstate.write_text(json.dumps(s))
say(brec, bs.pid, ppaper, "idle")
W("remote", "watch", "box", "--json")
got = tick()
ck(not kept_box and not [n for n in got if n["kind"] == "finished"],
   f"Watch off forgets what was seen on box: no “is done” when it is watched again "
   f"({kept_box}, {[n['title'] for n in got]})")

# a machine that holds a project and stays silent: one notice, then none;
# when it answers again, one more, on screen only
projApi = os.path.realpath(str(wb / "home" / "code" / "api"))
os.makedirs(projApi)
subprocess.run([PY, LAUNCH, "tag", projApi, "--apply"], env=we, capture_output=True)
away_probe = ("import sys, json; sys.path.insert(0, sys.argv[1]); import aht\n"
              "uid = aht.read_marker(sys.argv[2])\n"
              "aht._update_entry(uid, away=json.loads(sys.argv[3]) or None)\n")
def set_away(rec):
    subprocess.run([PY, "-c", away_probe, str(HERE.parent), projApi, json.dumps(rec)],
                   env=we, capture_output=True)
def quiet_for(m, secs):
    """Move the clock: machine m's first unanswered ask `secs` earlier."""
    s = json.loads(nstate.read_text())
    q = (s.get("quiet") or {}).get(m) or {}
    if q.get("first_miss"):
        q["first_miss"] -= secs
        nstate.write_text(json.dumps(s))
    return bool(q.get("first_miss"))
quiets = lambda got: [n for n in got if n["kind"] == "quiet"]
# the 10 minutes count from the first ask it did not answer, not from when
# it was last heard: lab (its ssh fails, 255), last heard 2 hours ago,
# gives no notice at the first check; with the clock past 10 minutes, one
set_away({"v": 2, "remote": "lab", "holder": "lab", "path": projApi, "remote_path": projApi,
          "since": core._now(), "agent": "claude", "driven_by": "here"})
bj = json.loads(bjson.read_text())
lheard = time.time() - 7200
bj["lab"] = {"heard": lheard, "sessions": []}
bjson.write_text(json.dumps(bj))
g1 = tick()
moved = quiet_for("lab", core.QUIET_AFTER + 5)
g2, g3 = tick(), tick()
ck(not quiets(g1) and moved and [n["title"] for n in quiets(g2)] == ["api on lab: no answer"]
   and quiets(g2)[0]["message"].startswith(f"lab has not answered since {core._clock(lheard)}.")
   and not quiets(g3),
   f"a holder last heard 2 hours ago: no notice at the first miss; 10 minutes on, one "
   f"({quiets(g1)}, {moved}, {quiets(g2)}, {quiets(g3)})")
set_away({"v": 2, "remote": "box", "holder": "box", "path": projApi, "remote_path": projApi,
          "since": core._now(), "agent": "claude", "driven_by": "here"})
bj = json.loads(bjson.read_text())
heard = bj["box"]["heard"] = time.time() - 700
bjson.write_text(json.dumps(bj))
n0 = len(told())
got0 = tick(AHT_TEST_DROP="board")
moved = quiet_for("box", core.QUIET_AFTER + 5)
got1, got2, got3 = tick(AHT_TEST_DROP="board"), tick(AHT_TEST_DROP="board"), tick()
q1 = [n for n in got1 if n["kind"] == "quiet"]
ck(not quiets(got0) and moved and len(q1) == 1 and q1[0]["title"] == "api on box: no answer"
   and q1[0]["message"] == f"box has not answered since {core._clock(heard)}. The work on api "
                           "there may have stopped (asleep, off or offline)."
   and not [n for n in got2 if n["kind"] == "quiet"],
   f"a silent holder: none at the first miss, one “has not answered” notice 10 minutes "
   f"on, none the next time ({quiets(got0)}, {q1}, {got2})")
q3 = [n for n in got3 if n["kind"] == "quiet"]
phones = {l["title"]: l["phone"] for l in told()[n0:]}
ck([n["title"] for n in q3] == ["box answers again"]
   and phones.get("api on box: no answer") == "ntfy:aht-test-only"
   and phones.get("box answers again") == ""
   and not json.loads(nstate.read_text()).get("quiet"),
   f"…to the phone too; when it answers again, one notice on screen only ({q3}, {phones})")
set_away(None)

# the board: when each machine last answered, and what it said then
bj = json.loads(bjson.read_text())
bj["lab"] = {"heard": time.time() - 1500, "sessions": [
    {"agent": "claude", "project": "/home/me/code/api", "pid": 4242, "session": "s-lab",
     "status": "working", "raw_status": "busy", "waiting_for": None}]}
bjson.write_text(json.dumps(bj))
(wbox / "home" / ".aht" / "run" / "notices.json").write_text(json.dumps(
    {"at": time.time(), "version": core.VERSION}))         # box's own notices just ran
b = W("board", "--json")
fx3 += fixture_ok(b, "board.json", FIXTURES3)
bm = {m["machine"]: m for m in b.get("machines", [])}
bx, lb = bm.get("box", {}), bm.get("lab", {})
ck(bm.get("mac", {}).get("stale") is False and bx.get("reachable") and bx.get("stale") is False
   and time.time() - (bx.get("last_heard") or 0) < 60
   and [s.get("session") for s in bx.get("last_sessions") or [] if s["agent"] == "claude"]
   == [f"w{bs.pid}"] and bx.get("phone_here") is True,
   f"board: box answered now, its sessions kept for when it does not ({bx.get('last_heard')})")
ck(not lb.get("reachable") and "Permission denied" in (lb.get("error") or "")
   and lb.get("stale") is True and lb.get("last_heard") == bj["lab"]["heard"]
   and [s["session"] for s in lb.get("last_sessions") or []] == ["s-lab"],
   f"board: lab, silent for 25 minutes, is stale and shows what it said last "
   f"({lb.get('error')}, {lb.get('stale')})")
# remote add and remote remove forget what a machine of that name said on
# the board: one set up anew shows none of the old one's sessions
nh = wfar / "127.0.0.5"
(nh / "bin").mkdir(parents=True)
(nh / "home").mkdir()
os.symlink(PY, nh / "bin" / "python3")
(nh / "path").write_text(f"{nh / 'bin'}:/usr/bin:/bin")
(nh / "env").write_text(f"AHT_CLAUDE={wstub / 'claude'}\nAHT_SESSION_BUS={nh / 'no-bus'}\n")
def old_board(m):
    bj = json.loads(bjson.read_text())
    bj[m] = {"heard": time.time() - 90000, "sessions": [
        {"agent": "claude", "project": "/home/me/code/old", "pid": 4343, "session": "s-old",
         "status": "working", "raw_status": "busy", "waiting_for": None}]}
    bjson.write_text(json.dumps(bj))
old_board("new")
r = subprocess.run([PY, LAUNCH, "remote", "add", "new", "me@127.0.0.5"], env=we,
                   capture_output=True, text=True)
bj = json.loads(bjson.read_text())
ck(r.returncode == 0 and "new" in json.loads((wb / ".aht" / "config.json").read_text())["remotes"] and "new" not in bj
   and {"box", "lab"} <= set(bj),
   f"remote add: nothing heard from an earlier machine of that name is kept "
   f"({r.stderr.strip()[-200:]}, {sorted(bj)})")
# added again under its name: what was chosen for it stays (its paths and
# pairs, whether it is watched), and what it said before
wcfg = wb / ".aht" / "config.json"
cj = json.loads(wcfg.read_text())
first_mid = cj["remotes"]["new"].get("machine_id")
cj["remotes"]["new"].update(paths=[["/Users/me/work", "/home/me/work"]], watch=True,
                            machine_id="feedfacecafe")
wcfg.write_text(json.dumps(cj))
r = subprocess.run([PY, LAUNCH, "remote", "add", "new", "me@127.0.0.5"], env=we,
                   capture_output=True, text=True)
nr = json.loads(wcfg.read_text())["remotes"]["new"]
ck(r.returncode == 0 and nr.get("paths") == [["/Users/me/work", "/home/me/work"]]
   and nr.get("watch") is True and nr.get("home")
   and nr.get("machine_id") == (first_mid or "feedfacecafe"),
   f"remote add again: its paths (pairs too), Watch and what it said are kept ({nr})")
old_board("new")
r = subprocess.run([PY, LAUNCH, "remote", "remove", "new"], env=we, capture_output=True, text=True)
bj = json.loads(bjson.read_text())
ck(r.returncode == 0 and "new" not in json.loads((wb / ".aht" / "config.json").read_text())["remotes"] and "new" not in bj
   and {"box", "lab"} <= set(bj),
   f"remote remove: its last sessions go from the board too ({r.stderr.strip()[-200:]}, "
   f"{sorted(bj)})")

# remote check: rows for asking, rows for handing over, and keeping awake
d = W("remote", "check", "box", "--json")
crows = (d.get("machines") or [{}])[0].get("checks") or []
aw = next((c for c in crows if "awake" in c["check"]), {})
native = "caffeinate" if sys.platform == "darwin" else "systemd-inhibit"
ck([c["check"] for c in crows[:3]] == ["reachable", "key login without a prompt", "python3 there"]
   and all(c["ok"] and c["group"] == "ask" for c in crows[:3])
   and {c["group"] for c in crows[3:]} == {"handover"}
   and aw.get("ok") is True and aw.get("needed") is False and native in aw.get("detail", "")
   and any(l.split()[1:2] == [native] and l.endswith(" true")
           for l in awlog.read_text().splitlines()),
   f"remote check: grouped rows; the keep-awake tool was tried there ({aw})")
fx3 += fixture_ok(d, "remote_check.json", FIXTURES3)
(wb / "refused").write_text("")
d = W("remote", "check", "box", "--json")
(wb / "refused").unlink()
aw = next((c for c in (d.get("machines") or [{}])[0].get("checks") or []
           if "awake" in c["check"]), {})
ck(aw.get("ok") is False and "refused" in aw.get("detail", "")
   and "Access denied" in aw.get("detail", ""),
   f"remote check: a keep-awake tool that is refused there is said so ({aw})")
d = W("remote", "check", "lab", "--json")
m = (d.get("machines") or [{}])[0]
ck(m.get("error") and [(c["check"], c["ok"]) for c in m.get("checks", [])]
   == [("reachable", True), ("key login without a prompt", False)]
   and "ssh-copy-id me@127.0.0.4" in m["checks"][1].get("fix", ""),
   f"remote check: a machine that takes no key gets its rows for asking, with the fix "
   f"({m.get('checks')})")
# the texts a Windows PC shows, and the fixes for a Mac and for host keys
_osname = core.os.name
try:
    core.os.name = "nt"
    _pc = core.Remote("mac", {"ssh": "me@mac.local", "system": "Darwin"})
    rk_ = core._reach_rows(_pc, err="cannot reach mac (me@mac.local): me@mac.local: "
                                     "Permission denied (publickey).")
    rh_ = core._reach_rows(_pc, err="cannot reach mac (me@mac.local): Host key "
                                     "verification failed.")
    rr_ = core._reach_rows(_pc, err="cannot reach mac (me@mac.local): ssh: connect to host "
                                     "mac.local port 22: Connection refused")
    rp_ = core._reach_rows(core.Remote("box", {"ssh": "me@box"}),
                           err="box gave no usable answer to “probe”: sh: 1: exec: python3: "
                               "not found")
finally:
    core.os.name = _osname
ck(rk_[1].get("fix") == core.FIX_AGENT_NT and "ssh-agent" in core.FIX_AGENT_NT
   and rh_[1].get("fix") == "Connect once in a terminal (`ssh me@mac.local`) and accept the "
                           "machine's key. aht never accepts a key for you."
   and rr_[0]["ok"] is False and rr_[0].get("fix") == core.FIX_MAC_LOGIN
   and [(c["check"], c["ok"]) for c in rp_] == [("reachable", True),
                                                ("key login without a prompt", True),
                                                ("python3 there", False)],
   f"remote check from Windows: ssh-agent, host keys, Remote Login on the Mac, python3 "
   f"({rk_}, {rh_}, {rr_}, {rp_})")

# Search everywhere: each machine searches its own index, read only
bstore = wbox / "home" / ".claude" / "projects" / enc(ppaper)
bstore.mkdir(parents=True)
(bstore / "sb1.jsonl").write_text(
    json.dumps({"type": "user", "cwd": ppaper, "entrypoint": "cli", "timestamp": iso(time.time()),
                "message": {"role": "user", "content": "the walrus parser drops comments"}})
    + "\n" + json.dumps({"type": "ai-title", "aiTitle": "Walrus comments"}) + "\n")
benv = dict(we, HOME=str(wbox / "home"), AHT_HOME=str(wbox / "home" / ".aht"),
            AHT_ROOT_CLAUDE=str(wbox / "home" / ".claude" / "projects"))
subprocess.run([PY, LAUNCH, "search", "--update", "--json"], env=benv, capture_output=True)
bdb = wbox / "home" / ".aht" / "search.db"
_db = sqlite3.connect(str(bdb))            # a row an older aht could have kept unmasked
_db.execute("insert into msgs values (?,?,?,?,?,?,?)",
            (f"the walrus key is {KEY}", "user", "claude", "sb1", ppaper, time.time(), "x"))
_db.commit()
_db.close()
bsha = hashlib.sha256(bdb.read_bytes()).hexdigest()
bfiles = sorted(os.listdir(bdb.parent))
lstore = wb / "tools" / "claude" / enc(here_p)
lstore.mkdir(parents=True)
(lstore / "sl1.jsonl").write_text(
    json.dumps({"type": "user", "cwd": here_p, "entrypoint": "cli", "timestamp": iso(time.time()),
                "message": {"role": "user", "content": "tidy the walrus module"}}) + "\n")
r = subprocess.run([PY, LAUNCH, "search", "walrus", "--everywhere", "--json"], env=we,
                   capture_output=True, text=True)
try:
    d = json.loads(r.stdout)
except ValueError:
    d = {}
fx3 += fixture_ok(d, "search_everywhere.json", FIXTURES3)
res, mach = d.get("results") or [], {m["machine"]: m for m in d.get("machines") or []}
ck([x["machine"] for x in res] == [None, "box"] and res[0]["session"] == "sl1"
   and res[1]["session"] == "sb1" and "resume" not in res[1] and res[0].get("resume"),
   f"search --everywhere: this machine's hits first (machine null), then box's, labelled; "
   f"nothing to run here from box's ({[(x.get('machine'), x.get('session')) for x in res]})")
bm_ = mach.get("box", {})
ck(bm_.get("reachable") and bm_.get("indexed") is True and bm_.get("results") == 1
   and bm_.get("index_at") and bm_.get("error") is None
   and mach.get("empty", {}).get("indexed") is False
   and mach.get("empty", {}).get("error") == core.NO_INDEX
   and not (wempty / "home" / ".aht" / "search.db").exists()
   and mach.get("lab", {}).get("reachable") is False
   and "Permission denied" in (mach.get("lab", {}).get("error") or ""),
   f"search --everywhere: per machine whether it answered and has an index; none is made "
   f"there ({d.get('machines')})")
ck(KEY not in r.stdout and "Xq7Xq7Xq7Xq7" not in r.stdout and "[Anthropic API key: " in r.stdout,
   "search --everywhere: a key in another machine's index is masked (there and here)")
ck(hashlib.sha256(bdb.read_bytes()).hexdigest() == bsha and sorted(os.listdir(bdb.parent)) == bfiles,
   "search on box leaves box's search.db as it was (sha256), and no journal next to it")
d = W("search", "walrus", "--json", "--no-update")
ck(d.get("results") and all(x.get("machine", "missing") is None for x in d["results"])
   and "machines" not in d,
   f"search without --everywhere: every row says machine null ({d.get('results')})")

# keeping a machine awake while an agent works there: caffeinate on macOS,
# systemd-inhibit on Linux (both stand-ins), every 0.2 s instead of 30
AWAKE = ("import sys; sys.path.insert(0, sys.argv[1]); import aht\n"
         "aht.IS_MAC = sys.argv[2] == 'mac'; aht.IS_LINUX = not aht.IS_MAC\n"
         "sys.exit(aht.main(sys.argv[3:]))")
awp = os.path.realpath(str(wb / "home" / "code" / "held"))
os.makedirs(awp)
def awake(kind, name, every="0.2"):
    return subprocess.Popen([PY, "-c", AWAKE, str(HERE.parent), kind, "_awake", "--path", awp,
                             "--name", name, "--hours", "1"], env=dict(we, AHT_AWAKE_EVERY=every),
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
whelpers = []
for kind, tool in (("mac", "caffeinate"), ("linux", "systemd-inhibit")):
    ws_ = sleeper()
    arec = wsess / f"{ws_.pid}.json"
    say(arec, ws_.pid, awp, "busy")
    h = awake(kind, f"aht-held-{kind}")
    whelpers.append(h)
    pidf = wb / ".aht" / "remote" / "run" / f"aht-held-{kind}" / "awake.pid"
    started = until(lambda: holds(tool)) and pidf.is_file()
    line = next((l for l in reversed(awlog.read_text().splitlines())
                 if l.split()[1:2] == [tool]), "")
    say(arec, ws_.pid, awp, "idle")
    let_go = until(lambda: not holds(tool)) and h.poll() is None
    say(arec, ws_.pid, awp, "waiting", "approve Bash")
    again = until(lambda: holds(tool))
    arec.unlink()
    ended = until(lambda: h.poll() is not None) and not holds(tool) and not pidf.exists()
    ck(started and let_go and again and ended
       and (" -i /bin/sh -c " in line if kind == "mac"
            else "--what=sleep:idle" in line and "--mode=block" in line),
       f"keep awake ({tool}): held while the session works or waits, let go when idle, ended "
       f"after three looks with no session ({started}, {let_go}, {again}, {ended}: {line})")
# `close` ends it through its pid file (`stop` does the same)
ws_ = sleeper()
arec = wsess / f"{ws_.pid}.json"
say(arec, ws_.pid, awp, "busy")
h = awake("mac", "aht-held-close", every="5")
whelpers.append(h)
held_ = until(lambda: holds("caffeinate"))
arec.unlink()                               # the session ended
r = subprocess.run([PY, LAUNCH, "_agent"], input=json.dumps({"op": "close", "path": awp,
                                                          "name": "aht-held-close"}),
                   env=we, capture_output=True, text=True)
ck(held_ and until(lambda: h.poll() is not None, 5) and not holds("caffeinate")
   and not (wb / ".aht" / "remote" / "run" / "aht-held-close" / "awake.pid").exists(),
   f"keep awake: `close` ends the helper through its pid file ({r.stdout.strip()[-120:]})")
# a handover's `start` starts it next to the session there, `stop` ends it
BOXOP = ("import sys, json; sys.path.insert(0, sys.argv[1]); import aht\n"
         "a = json.loads(sys.argv[3])\n"
         "print(json.dumps(aht.Remote('box', {'root': sys.argv[2]}).agent(a.pop('op'), "
         "timeout=60, **a)))")
def box_op(op, **a):
    r = subprocess.run([PY, "-c", BOXOP, str(HERE.parent), str(wbox), json.dumps(dict(a, op=op))],
                       env=dict(we, AHT_AWAKE_EVERY="0.2"), capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except ValueError:
        return {"error": r.stdout[-300:] + r.stderr[-300:]}
bp = str(wbox / "home" / "code" / "started")
os.makedirs(bp)
st = box_op("start", path=bp, name="aht-started-1", claude=str(wstub / "claude"),
            keep_awake=True, wait=5)
bpid = wbox / "home" / ".aht" / "remote" / "run" / "aht-started-1" / "awake.pid"
spawned = until(lambda: bpid.is_file())
hpid = json.loads(bpid.read_text())["pid"] if spawned else None
win = json.loads((wbox / "home" / ".faketmux" / "aht-started-1.json").read_text()) \
    if (wbox / "home" / ".faketmux" / "aht-started-1.json").is_file() else {}
srec = wbox / "home" / ".claude" / "sessions" / f"{win.get('pid')}.json"
held_ = False
if srec.is_file():
    rec_ = json.loads(srec.read_text())
    srec.write_text(json.dumps(dict(rec_, status="busy")))
    held_ = until(lambda: holds(native))
    srec.write_text(json.dumps(dict(rec_, status="idle")))
sp = box_op("stop", path=bp, name="aht-started-1", wait=10)
ck(st.get("ok") and st.get("keep_awake") == native and spawned and held_ and sp.get("stopped")
   and not bpid.exists() and hpid and until(lambda: not core._pid_alive(hpid), 5)
   and not holds(native),
   f"a handover's start keeps box awake while its session works; stop ends that "
   f"({st.get('keep_awake') or st.get('error')}, {spawned}, {held_}, {sp})")

r = subprocess.run([PY, LAUNCH, "night-shift", here_p, "--task", "tidy", "--back", "07:00",
                    "--to", "box"], env=we, capture_output=True, text=True)
ck("mac has to be awake then" in r.stdout,
   f"night shift: its texts name this machine, not “this Mac” ({r.stdout.strip()[-200:]})")
ck(not fx3, f"the phase-3 JSON keeps the shape of tests/fixtures/phase3 ({fx3})")
# nothing of these tests runs on: helpers, stand-in tools, sessions, windows
for h in whelpers:
    if h.poll() is None:
        h.kill()
    h.wait()
for f in list((wb / ".aht" / "remote" / "run").glob("*/awake.pid")) \
        + list((wbox / "home" / ".aht" / "remote" / "run").glob("*/awake.pid")):
    try:
        pid = int(json.loads(f.read_text())["pid"])
        if "_awake" in core._cmdline_of(pid):
            os.kill(pid, 9)
    except (OSError, ValueError, KeyError):
        pass
for pid in holds("caffeinate") + holds("systemd-inhibit"):
    try:
        os.kill(pid, 9)
    except OSError:
        pass
for w in (wbox / "home" / ".faketmux").glob("*.json"):
    rec_ = json.loads(w.read_text())
    if rec_.get("alive"):
        try:
            os.kill(int(rec_["pid"]), 15)
        except OSError:
            pass
for p in wsleep:
    p.kill()
    p.wait()

done()
