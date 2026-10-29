#!/usr/bin/env python3
"""[17f] another agent on the other machine: its window, --stop, the catch-up."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)

print("\n[17f] another agent on the other machine: its window, --stop, the catch-up")
FIXTURES8 = HERE / "fixtures" / "phase8"

def phase8_suite():
    """Hand Over and Bring Here into Codex, Kimi, agy or Vibe.  box is a
    folder standing in for another machine (its core runs there with a home
    of its own); its tmux is fake_tmux.py, which runs another agent's window
    line for real; the agent there is the stand-in Codex (fake_codex.py): it
    writes its session, prints for a while, then waits for its quit keys.
    Keeping awake is a stand-in that notes its calls.  No ssh, no real
    agent, no token."""
    fx8 = []
    ge = iso_env("phase8")
    gb = Path(ge["HOME"]).parent
    gbox = gb / "box"
    gbh = gbox / "home"
    for d in (".claude/sessions", ".claude/projects", ".aht"):
        (gbh / d).mkdir(parents=True, exist_ok=True)
    (gbh / ".claude.json").write_text("{}")
    gs = gb / "stubs"
    gs.mkdir()
    clog, tlog, awlog, nlog = (gb / n for n in ("calls.log", "terminal.log", "awake.log",
                                                 "notices.log"))
    (gs / "claude").write_text(f'#!/bin/sh\necho "claude $*" >> "{clog}"\n'
                               '[ "$1" = "--version" ] && echo "9.9.9 (Claude Code)"\nexit 0\n')
    for name in ("agy", "vibe"):
        (gs / name).write_text(f'#!/bin/sh\necho "{name} $*" >> "{clog}"\n')
    for name in ("codex", "kimi"):
        (gs / name).write_text(f'#!/bin/sh\nexec "{PY}" "{HERE / f"fake_{name}.py"}" "$@"\n')
    (gs / "tmux").write_text(f'#!/bin/sh\nexec "{PY}" "{HERE / "fake_tmux.py"}" "$@"\n')
    for t in ("caffeinate", "systemd-inhibit"):
        # a quick try (`… true`) ends at once; a hold waits, as the real ones do
        (gs / t).write_text(f'#!/bin/sh\necho "$$ {t} $*" >> "{awlog}"\nfor a; do last="$a"; '
                            'done\n[ "$last" = true ] && exit 0\nexec sleep 600\n')
    for f in gs.iterdir():
        f.chmod(0o755)
    (gb / "no-tabs.json").write_text("{}")
    ge.update({f"AHT_CLI_{n.upper()}": str(gs / n) for n in ("claude", "codex", "kimi", "agy",
                                                             "vibe")})
    ge.update(AHT_CLAUDE=str(gs / "claude"), AHT_TERMINAL_LOG=str(tlog),
              AHT_FAKE_CODEX_LOG=str(gb / "codex.log"), AHT_FAKE_KIMI_LOG=str(gb / "kimi.log"),
              AHT_CORE_DIR=str(HERE.parent), AHT_ITERM_TABS=str(gb / "no-tabs.json"),
              AHT_NO_SEARCH_INDEX="1", AHT_MACHINE_NAME="mac", AHT_REMOTE_MACHINE_NAME="box",
              AHT_REMOTE_PATH=str(gs), AHT_AGENT_PROCS="[]", AHT_REMOTE_AGENT_PROCS="[]",
              AHT_NO_MIRROR="1", AHT_NOTIFY_LOG=str(nlog), AHT_SESSION_BUS=str(gb / "no-bus"),
              AHT_CLAUDE_MANAGED_SETTINGS=str(gb / "no-managed-settings.json"))
    def G(*a, **extra):
        r = subprocess.run([PY, LAUNCH, *a], env=dict(ge, **extra), capture_output=True, text=True)
        try:
            d = json.loads(r.stdout)
        except ValueError:
            d = {"unparsed": r.stdout[-600:] + r.stderr[-900:]}
        if isinstance(d, dict):
            d["_rc"] = r.returncode
        return d
    GOP = ("import sys, json; sys.path.insert(0, sys.argv[1]); import aht\n"
           "a = json.loads(sys.argv[3])\n"
           "print(json.dumps(aht.Remote('box', {'root': sys.argv[2]}).agent(a.pop('op'), "
           "timeout=120, **a)))")
    def gop(op, extra=None, **a):
        """One op of box's core, as a handover asks it."""
        r = subprocess.run([PY, "-c", GOP, str(HERE.parent), str(gbox), json.dumps(dict(a, op=op))],
                           env=dict(ge, **(extra or {})), capture_output=True, text=True)
        try:
            return json.loads(r.stdout)
        except ValueError:
            return {"error": r.stdout[-300:] + r.stderr[-600:]}
    def until(cond, secs=10.0):
        end = time.time() + secs
        while time.time() < end:
            if cond():
                return True
            time.sleep(0.1)
        return bool(cond())
    q = core.shell_quote
    G("config", "--set", "remotes=" + json.dumps({"box": {"root": str(gbox), "paths": "home"}}))
    G("config", "--set", "handover_keep_awake=false")

    # a project here whose Claude Code session runs in never-ask mode
    api = os.path.realpath(str(Path(ge["HOME"]) / "code" / "api"))
    os.makedirs(api + "/src")
    Path(api, "src", "app.py").write_text("old\n")
    S1 = "4c1b2a3d-1111-4222-8333-444455556666"
    st1 = Path(ge["AHT_ROOT_CLAUDE"]) / enc(api)
    st1.mkdir(parents=True)
    (st1 / f"{S1}.jsonl").write_text("".join(json.dumps(e) + "\n" for e in (
        {"type": "user", "cwd": api, "sessionId": S1, "version": "9.9.9", "entrypoint": "cli",
         "timestamp": iso(time.time() - 600), "permissionMode": "bypassPermissions",
         "message": {"role": "user", "content": "fix the parser"}},
        {"type": "ai-title", "aiTitle": "Parser fix"},
        {"type": "assistant", "cwd": api, "sessionId": S1, "timestamp": iso(time.time() - 590),
         "message": {"role": "assistant", "content": [{"type": "text",
                                                       "text": "Half done; tests next."}]}})))
    iso_run(ge, "tag", api, "--apply")
    far = str(gbh / "code" / "api")         # where it goes on box ("home" paths)

    # (1) the dry run: each agent's own start line there, in the level of the
    # session here (never-ask), and the token line
    want = {"codex": "codex --dangerously-bypass-approvals-and-sandbox 'You are taking over "
                     "this project from Claude Code on mac. Read .aht/handover/relay-",
            "agy": "agy --dangerously-skip-permissions --remote-control -i 'You are taking "
                   "over this project from Claude Code on mac. Read .aht/handover/relay-",
            "vibe": "vibe --auto-approve 'You are taking over this project from Claude Code on "
                    "mac. Read .aht/handover/relay-",
            "kimi": "kimi --auto -S <the session Kimi starts there>"}
    got = {}
    for a in want:
        d = G("handover", api, "--to", "box", "--agent", a, "--json")
        got[a] = d
        p = d.get("perm") or {}
        ck(d.get("_rc") == 0 and not d.get("blockers") and d.get("agent") == a
           and (d.get("start_line") or "").startswith(want[a]) and p.get("level") == "never"
           and p.get("text") == f"{core.AGENT_NAMES[a]} on box starts in never-ask mode, like "
                                "the session here"
           and "uses tokens" in (d.get("tokens") or ""),
           f"hand over --agent {a}, dry run: its start line there with the level's flags, and "
           f"the token line ({d.get('start_line')}, {p.get('text')}, "
           f"{d.get('blockers') or d.get('error') or d.get('unparsed')})")
    fx8 += fixture_ok(got["codex"], "handover_agent_dry.json", FIXTURES8)
    r = subprocess.run([PY, LAUNCH, "handover", api, "--to", "box", "--agent", "codex"], env=ge,
                       capture_output=True, text=True)
    ck("agent there    Codex, a new session — Codex starts on box and reads the summary as "
       "its first turn: that uses tokens" in r.stdout and "starts with    codex " in r.stdout
       and "Claude Code    " not in r.stdout,
       f"hand over --agent codex, dry run in words: the agent, its token line, its start line "
       f"({r.stdout[-500:]})")

    # (2) --apply: the summary travels in a relay, Codex starts in a window
    # there, the record says who works there
    d = G("handover", api, "--to", "box", "--agent", "codex", "--apply", "--json",
          FAKE_CODEX_WORK="3")
    away = d.get("away") or {}
    win = away.get("window") or "none"
    run = gbh / ".aht" / "remote" / "run" / win
    wj = json.loads((run / "window.json").read_text()) if (run / "window.json").is_file() else {}
    cmd = (run / "command.txt").read_text() if (run / "command.txt").is_file() else ""
    rid = d.get("relay") or "none"
    rel = json.loads(Path(api, ".aht", "handover", f"relay-{rid}.json").read_text()) \
        if Path(api, ".aht", "handover", f"relay-{rid}.json").is_file() else {}
    ck(d.get("applied") and away.get("agent") == "codex" and away.get("relay") == rid
       and away.get("session") == S1 and wj.get("agent") == "codex" and wj.get("path") == far
       and " --dangerously-bypass-approvals-and-sandbox " in cmd
       and f"> {run / 'exited'}" in cmd.replace("'", "")
       and rel.get("kind") == "handover" and rel["to"].get("agent") == "codex"
       and rel["to"].get("machine") == "box" and rel["from"].get("session") == S1
       and Path(far, ".aht", "handover", f"relay-{rid}.md").is_file(),
       f"hand over --agent codex --apply: the summary travels in a relay, Codex starts in its "
       f"window there with the level's flag, window.json names it ({d.get('error') or d.get('blockers')}, "
       f"{wj}, {cmd[:200]})")
    until(lambda: any((gbh / ".codex" / "sessions").rglob("rollout-*.jsonl")), 10)
    roll = sorted((gbh / ".codex" / "sessions").rglob("rollout-*.jsonl"))
    first = roll[0].read_text() if roll else ""
    ck(roll and f".aht/handover/relay-{rid}.md first" in first and far in first,
       f"…the stand-in Codex there began its session with the summary as its first turn "
       f"({[str(x) for x in roll]})")
    reg = json.loads((gb / ".aht" / "registry.json").read_text())
    row = next((p for p in G("projects", "--json").get("projects") or []
                if p["real_path"] == api), {})
    fx8 += fixture_ok(row, "projects_away_agent.json", FIXTURES8)
    ck(row.get("away_agent") == "codex" and row.get("away_window") == win,
       f"projects --json: away_agent and away_window ({row.get('away_agent')}, {row.get('away_window')})")

    # (3) the board: one row for the window and Codex's process there, working
    # while it prints, then quiet
    fwin = gbh / ".faketmux" / f"{win}.json"
    wrec = json.loads(fwin.read_text()) if fwin.is_file() else {}
    procs = json.dumps([{"pid": wrec.get("pid") or 1, "cwd": far,
                         "args": "codex --dangerously-bypass-approvals-and-sandbox go"}])
    b = G("board", "--json", AHT_REMOTE_AGENT_PROCS=procs)
    bx = next((m for m in b.get("machines") or [] if m["machine"] == "box"), {})
    rows = [s for s in bx.get("sessions") or [] if s["agent"] == "codex"]
    ck(len(rows) == 1 and rows[0].get("window") == win and rows[0].get("raw_status") == "working"
       and rows[0].get("status") == "working" and rows[0].get("pid") == wrec.get("pid")
       and rows[0].get("not_running") is False and rows[0].get("handed_over")
       and rows[0].get("here_path") == api and rows[0].get("project") == far,
       f"board: the window and Codex's process there are one row, working while it prints "
       f"({rows})")
    # a Codex started by hand in that folder, outside the window: a row of its
    # own, not the window's pid
    b = G("board", "--json", AHT_REMOTE_AGENT_PROCS=json.dumps(
        [{"pid": 4343, "cwd": far, "args": "codex go on"}]))
    bx = next((m for m in b.get("machines") or [] if m["machine"] == "box"), {})
    rows = [(s.get("window"), s.get("pid")) for s in bx.get("sessions") or []
            if s["agent"] == "codex"]
    ck(len(rows) == 2 and set(rows) == {(None, 4343), (win, None)},
       f"board: a Codex outside the window, in the same folder, keeps its own row; the window's "
       f"row takes only a pid of its own pane ({rows})")
    def gact(ago):
        """The window's last output, `ago` seconds back."""
        w = json.loads(fwin.read_text())
        fwin.write_text(json.dumps(dict(w, activity=time.time() - ago)))
    gact(400)
    b = G("board", "--json", AHT_REMOTE_AGENT_PROCS=procs)
    fx8 += fixture_ok(b, "board_windows.json", FIXTURES8)
    bx = next((m for m in b.get("machines") or [] if m["machine"] == "box"), {})
    rows = [s for s in bx.get("sessions") or [] if s["agent"] == "codex"]
    txt = subprocess.run([PY, LAUNCH, "board"], env=dict(ge, AHT_REMOTE_AGENT_PROCS=procs),
                         capture_output=True, text=True).stdout
    ck(rows and rows[0].get("raw_status") == "quiet" and rows[0].get("status") == "quiet for 6 min"
       and 400 <= (rows[0].get("quiet_for") or 0) < 430 and "quiet for 6 min" in txt,
       f"board: quiet for 6 min once it wrote nothing since ({rows}, {txt[-300:]})")
    pk = G("attach", api, "--peek", "--json")
    ck(pk.get("open") and pk.get("raw_status") == "quiet" and pk.get("agent") == "codex"
       and any("waiting for you" in l for l in pk.get("screen") or []),
       f"attach --peek: the last screen lines there and the window's state ({pk})")

    # (4) "went quiet": a minute without output after working, once; a
    # shorter pause still counts as working
    nst = gb / ".aht" / "run" / "notices.json"
    def tick():
        if nst.is_file():
            s = json.loads(nst.read_text())
            s["asked"] = {}
            nst.write_text(json.dumps(s))
        return [n for n in G("notices", "--json").get("notices") or [] if n["kind"] == "went-quiet"]
    gact(1)
    t1 = tick()
    gact(30)
    t2 = tick()
    gact(400)
    t3, t4 = tick(), tick()
    told = [json.loads(l) for l in nlog.read_text().splitlines()] if nlog.is_file() else []
    ck(not t1 and not t2 and [(n["title"], n["message"]) for n in t3]
       == [("api on box went quiet", "Codex: done, or it waits for you")] and not t4
       and any(l["title"] == "api on box went quiet" for l in told),
       f"notices: “api on box went quiet” once, a minute after its output stopped; not for a "
       f"30 s pause ({t1}, {t2}, {t3}, {t4})")

    # (5) the close rule: a window whose agent runs is never closed
    c = gop("close", path=far, name=win)
    ck(c.get("closed") is False and c.get("reason") == "running" and fwin.is_file()
       and json.loads(fwin.read_text()).get("alive"),
       f"close: refused while Codex runs in the window ({c})")

    # (5b) a tmux there that fails (any error but "can't find session" or "no
    # server running"): whether Codex runs is not known, so nothing closes
    # or ends it, window.json stays, and the board says so
    bad = {"FAKE_TMUX_FAIL": "lost server"}
    c = gop("close", extra=bad, path=far, name=win)
    sp = gop("stop", extra=bad, path=far, name=win, agent="codex")
    d = G("reclaim", api, "--stop", "--apply", "--json", **bad)
    b = G("board", "--json", AHT_REMOTE_AGENT_PROCS=procs, **bad)
    bx = next((m for m in b.get("machines") or [] if m["machine"] == "box"), {})
    wrow = next((s for s in bx.get("sessions") or [] if s.get("window") == win), {})
    ck(c.get("closed") is False and c.get("reason") == "no-answer" and (run / "window.json").is_file()
       and sp.get("stopped") is False and sp.get("reason") == "no-answer"
       and not d.get("applied") and d.get("stop") is None
       # (its processes cannot be told from other programs then: those block too)
       and "tmux on box did not answer, so aht cannot tell whether Codex still runs in its "
           "window — try again in a moment, or end it yourself" in (d.get("blockers") or [])
       and not any("--stop" in x or "Codex still runs in its window on box" in x
                   for x in d.get("blockers") or [])
       and wrow.get("raw_status") == "unknown" and wrow.get("status") == "tmux did not answer"
       and wrow.get("not_running") is False and json.loads(fwin.read_text()).get("alive"),
       f"tmux there fails: close and stop refuse (no-answer), window.json stays, Take Back says "
       f"tmux did not answer, the board does not call it exited ({c}, {sp},"
       f"{d.get('blockers') or d.get('error')}, {wrow})")
    # no answer at all (a timeout: _tmux gives None): the same, here
    sil = "aht-silent-8"
    core.run_dir(sil).mkdir(parents=True)
    (core.run_dir(sil) / "window.json").write_text(json.dumps({"agent": "codex", "path": api}))
    keep_tmux = core._tmux
    core._tmux = lambda *a, **k: None
    try:
        s0 = core.window_state(sil)
        c0 = core._agent_close({"path": api, "name": sil})
        p0 = core._agent_stop({"path": api, "name": sil})
    finally:
        core._tmux = keep_tmux
    ck(s0["alive"] is None and s0["raw_status"] == "unknown" and not s0["not_running"]
       and c0.get("reason") == "no-answer" and p0.get("reason") == "no-answer"
       and not p0.get("stopped") and (core.run_dir(sil) / "window.json").is_file(),
       f"tmux gives no answer: alive unknown, close and stop refuse, window.json stays "
       f"({s0}, {c0}, {p0})")
    shutil.rmtree(core.run_dir(sil), ignore_errors=True)

    # (6) Take Back: refused while Codex runs; --stop only after 2 minutes
    # of quiet and once its own last message ends its turn
    keys = gbh / ".faketmux" / f"{win}.keys"
    d = G("reclaim", api, "--json")
    ck(d.get("_rc") == 3 and any("Codex still runs in its window on box (quiet for 6 min)" in x
                                 and "pass --stop" in x for x in d.get("blockers") or [])
       and not any("still running in this folder" in x for x in d.get("blockers") or []),
       f"take back: Codex still runs there, --stop is offered; its own processes there are "
       f"not listed as other programs ({d.get('blockers')})")
    gact(60)
    d = G("reclaim", api, "--stop", "--apply", "--json")
    ck(not d.get("applied") and (d.get("stop") or {}).get("reason") == "not-quiet"
       and any(x.startswith("Codex on box has been quiet for only 1 min — wait, or end it "
                            "yourself") for x in d.get("blockers") or [])
       and len(d.get("blockers") or []) == 1
       and not keys.exists() and json.loads((gb / ".aht" / "registry.json").read_text())
       ["projects"][core.read_marker(api)].get("away"),
       f"--stop refuses before 2 minutes of quiet: not-quiet ({d.get('stop')}, {d.get('blockers')})")
    gact(400)
    was = roll[0].read_text() if roll else ""
    if roll:
        with open(roll[0], "a") as fh:
            fh.write(json.dumps({"timestamp": iso(time.time()), "type": "event_msg",
                                 "payload": {"type": "user_message",
                                             "message": "now add the tests"}}) + "\n")
    d = G("reclaim", api, "--stop", "--apply", "--json")
    ck(not d.get("applied") and (d.get("stop") or {}).get("reason") == "turn-open"
       and (d.get("blockers") or []) == ["Codex's last turn is still open on box — wait, or "
                                         "end it yourself"] and not keys.exists(),
       f"--stop refuses while the user's message is the last in Codex's session: turn-open "
       f"({d.get('stop')}, {d.get('blockers')})")
    if roll:
        roll[0].write_text(was)
    d = G("reclaim", api, "--stop", "--json")
    r = subprocess.run([PY, LAUNCH, "reclaim", api, "--stop"], env=ge,
                       capture_output=True, text=True)
    ck(d.get("would_stop") and (d.get("stop") or {}).get("quit_keys") == ["C-c", "C-c"]
       and not keys.exists() and not d.get("blockers")
       and "Codex on box would be ended first (its quit keys: C-c C-c)" in r.stdout,
       f"--stop, dry run: Codex would be ended first, by its quit keys ({d.get('stop')}, "
       f"{d.get('blockers')}, {r.stdout[-300:]})")
    Path(far, "src", "app.py").write_text("new, from Codex\n")      # its work there
    d = G("reclaim", api, "--stop", "--apply", "--json")
    pressed = keys.read_text().split() if keys.is_file() else []
    e = json.loads((gb / ".aht" / "registry.json").read_text())["projects"][core.read_marker(api)]
    back = e.get("returned") or {}
    ck(d.get("applied") and d.get("stopped") and pressed == ["C-c", "C-c"]
       and Path(api, "src", "app.py").read_text() == "new, from Codex\n"
       and not e.get("away") and not (run / "window.json").exists()
       and not core._pid_alive(int(wrec.get("pid") or 0)),
       f"--stop, apply: its quit keys end Codex there, the window closes, its work comes back "
       f"({d.get('error') or d.get('blockers')}, {pressed}, {back})")
    cr = d.get("catchup") or {}
    bfile = Path(api, ".aht", "handover", f"relay-{cr.get('relay')}")
    brec = json.loads(Path(str(bfile) + ".json").read_text()) \
        if Path(str(bfile) + ".json").is_file() else {}
    btext = Path(str(bfile) + ".md").read_text() if Path(str(bfile) + ".md").is_file() else ""
    ck(brec.get("kind") == "back" and brec.get("note_for") == S1 and brec.get("back_of") == rid
       and brec["from"].get("agent") == "codex" and brec["from"].get("machine") == "box"
       and back.get("agent") == "codex" and back.get("relay") == brec.get("id")
       and "While Claude Code was away, Codex worked on box" in btext
       and "The parser is fixed; a test is still to do." in btext
       and Path(api, ".aht", "handover", f"relay-{rid}.closed").is_file(),
       f"take back writes a back relay with box's catch-up, for the Claude Code session that "
       f"left ({brec}, {btext[:300]})")
    hk = subprocess.run([PY, LAUNCH, "hook"], env=ge, capture_output=True, text=True,
                        input=json.dumps({"cwd": api, "session_id": S1, "source": "resume"})).stdout
    hk2 = subprocess.run([PY, LAUNCH, "hook"], env=ge, capture_output=True, text=True,
                         input=json.dumps({"cwd": api, "session_id": S1, "source": "resume"})).stdout
    ck("While Claude Code was away, Codex worked on box" in hk
       and f"relay-{brec.get('id')}.md" in hk and "Codex worked on it there, not Claude Code" in hk
       and "Codex worked on box" not in hk2,
       f"…the Claude Code session hears it from the hook when resumed, once ({hk[-600:]})")

    # (7) keep awake follows the window's output: held while Codex prints,
    # let go once it is quiet, ended with it
    native = "caffeinate" if sys.platform == "darwin" else "systemd-inhibit"
    def holds():
        rows = [l.split() for l in awlog.read_text().splitlines()] if awlog.is_file() else []
        return [int(r[0]) for r in rows if len(r) > 2 and r[1] == native and r[-1] != "true"
                and core._pid_alive(int(r[0]))]
    held_p = str(gbh / "code" / "held")
    os.makedirs(held_p)
    fast = {"AHT_AWAKE_EVERY": "0.2", "AHT_AWAKE_QUIET": "1.5", "AHT_STOP_QUIET": "0.5",
            "FAKE_CODEX_WORK": "3"}
    st = gop("start", extra=fast, path=held_p, name="aht-held-8", agent="codex",
             start_argv=["codex", "hold this"], keep_awake=True, wait=3)
    held = until(holds, 5)
    let_go = until(lambda: not holds(), 10)
    pidf = gbh / ".aht" / "remote" / "run" / "aht-held-8" / "awake.pid"
    alive = pidf.is_file()
    sp = gop("stop", extra=fast, path=held_p, name="aht-held-8")
    ck(st.get("started") and st.get("agent") == "codex" and held and let_go and alive
       and sp.get("stopped") and until(lambda: not pidf.exists(), 5) and not holds(),
       f"keep awake follows the window: held while Codex prints, let go when it is quiet, "
       f"ended with it ({st.get('error') or st.get('keep_awake')}, {held}, {let_go}, {alive}, {sp})")
    # that window's row says exited; a Codex running in its folder now is a
    # row of its own, not hidden in the exited one
    b = G("board", "--json", AHT_REMOTE_AGENT_PROCS=json.dumps(
        [{"pid": 4343, "cwd": held_p, "args": "codex go on"}]))
    bx_ = next((m for m in b.get("machines") or [] if m["machine"] == "box"), {})
    rows = [(s.get("window"), s.get("pid"), s.get("raw_status"))
            for s in bx_.get("sessions") or [] if s.get("project") == held_p]
    ck(len(rows) == 2 and set(rows) == {(None, 4343, "running"), ("aht-held-8", None, "exited")},
       f"board: an exited window's row does not take a Codex that runs in its folder now ({rows})")

    # (8) Bring Here into another agent: box's own project, its session in
    # edits mode; a new Codex session here reads the summary in that level
    bxenv = {k: v for k, v in ge.items() if not k.startswith("AHT_")}
    bxenv.update(core._sandbox_env(str(gbh)), AHT_MACHINE_NAME="box", AHT_NO_SEARCH_INDEX="1",
                 AHT_ITERM_TABS=str(gb / "no-tabs.json"), AHT_CLAUDE=str(gs / "claude"),
                 AHT_AGENT_PROCS="[]")
    def bx(*a):
        r = subprocess.run([PY, LAUNCH, *a], env=bxenv, capture_output=True, text=True)
        try:
            return json.loads(r.stdout)
        except ValueError:
            return {"unparsed": r.stdout[-300:] + r.stderr[-300:]}
    shop = gbh / "code" / "shop"
    (shop / "src").mkdir(parents=True)
    (shop / "src" / "app.py").write_text("print(1)\n")
    (gbh / ".aht" / "config.json").write_text("{}")
    bx("tag", str(shop), "--apply")
    S2 = "7d6e5f4a-2222-4333-8444-555566667777"
    sst = gbh / ".claude" / "projects" / enc(str(shop))
    sst.mkdir(parents=True)
    (sst / f"{S2}.jsonl").write_text("".join(json.dumps(e) + "\n" for e in (
        {"type": "user", "cwd": str(shop), "sessionId": S2, "version": "9.9.9",
         "entrypoint": "cli", "timestamp": iso(time.time() - 300), "permissionMode": "acceptEdits",
         "message": {"role": "user", "content": "refactor the checkout"}},
        {"type": "ai-title", "aiTitle": "Checkout refactor"})))
    d = G("bring", "/home/code/shop", "--from", "box", "--agent", "codex", "--json")
    fx8 += fixture_ok(d, "bring_agent_dry.json", FIXTURES8)
    dk = G("bring", "/home/code/shop", "--from", "box", "--agent", "kimi", "--json")
    ck(d.get("_rc") == 0 and d.get("agent") == "codex" and (d.get("perm") or {}).get("level") == "edits"
       and (d.get("start_line") or "").startswith(
           f"{q(gs / 'codex')} -a on-request -s workspace-write 'You are taking over this "
           "project from Claude Code on box. Read .aht/handover/relay-")
       and "uses tokens" in (d.get("tokens") or "")
       and dk.get("start_line") == q(gs / "kimi") and dk.get("first_prompt")
       and "paste the first prompt" in (dk.get("tokens") or ""),
       f"bring --agent, dry run: Codex here in its edits level (-a on-request -s "
       f"workspace-write); Kimi, with no edits mode, opens and you paste the first prompt "
       f"({d.get('start_line')}, {dk.get('start_line')}, {d.get('blockers') or d.get('error')})")
    n_t = len(tlog.read_text().splitlines()) if tlog.is_file() else 0
    d = G("bring", "/home/code/shop", "--from", "box", "--agent", "codex", "--apply", "--json")
    here = d.get("here_path") or "none"
    opened = "\n".join(tlog.read_text().splitlines()[n_t:]) if tlog.is_file() else ""
    hrec = json.loads(Path(here, ".aht", "handover", f"relay-{d.get('relay')}.json").read_text()) \
        if Path(here, ".aht", "handover", f"relay-{d.get('relay')}.json").is_file() else {}
    brow = next((p for p in bx("projects", "--json").get("projects") or []
                 if p["real_path"] == str(shop)), {})
    ck(d.get("applied") and "-a on-request -s workspace-write 'You are taking over this project "
       f"from Claude Code on box. Read .aht/handover/relay-{d.get('relay')}.md first" in opened
       and hrec.get("kind") == "bring" and hrec["to"].get("agent") == "codex"
       and brow.get("away_agent") == "codex",
       f"bring --agent codex --apply: Codex opens here with the summary; box records who works "
       f"here ({d.get('error') or d.get('blockers')}, {opened[-300:]}, {brow.get('away_agent')})")
    # Codex works here (the line the terminal ran), then Send Back: box's
    # Claude Code session gets the catch-up made here
    line = opened.splitlines()[-1] if opened else "true"
    subprocess.run(["/bin/sh", "-c", line], env=ge, capture_output=True, timeout=60)
    Path(here, "src", "app.py").write_text("print(2)\n")
    # while that Codex is still open in the folder (maybe in the middle of a
    # turn), Send Back waits, as for an open Claude Code session;
    # --allow-processes goes ahead.  One in another folder is no matter
    cx = [{"pid": 4242, "cwd": here, "args": "codex -a on-request -s workspace-write go"},
          {"pid": 4244, "cwd": str(gb), "args": "codex go"}]
    d1 = G("send-back", here, "--apply", "--json", AHT_AGENT_PROCS=json.dumps(cx))
    d2 = G("send-back", here, "--allow-processes", "--json", AHT_AGENT_PROCS=json.dumps(cx))
    d3 = G("send-back", here, "--json", AHT_AGENT_PROCS=json.dumps(cx[1:]))
    ck(not d1.get("applied") and (d1.get("blockers") or []) == [
           "Codex is still open in this project here (pid 4242) — exit it first, or pass "
           "--allow-processes to send the project back while it runs (what it does after that "
           "stays here)"]
       and not any("Codex" in x for x in d2.get("blockers") or [])
       and "Codex is still open in this project here (pid 4242); what it does from now on stays "
           "here" in (d2.get("warnings") or [])
       and not any("Codex" in x for x in (d3.get("blockers") or []) + (d3.get("warnings") or [])),
       f"send back: refused while the Codex Bring Here started is open in the folder; "
       f"--allow-processes goes ahead ({d1.get('blockers') or d1.get('error')}, "
       f"{d2.get('blockers')}, {d2.get('warnings')}, {d3.get('blockers')})")
    d = G("send-back", here, "--apply", "--json")
    bret = (json.loads((gbh / ".aht" / "registry.json").read_text())["projects"]
            [core.read_marker(str(shop))].get("returned") or {})
    bb = shop / ".aht" / "handover" / f"relay-{bret.get('relay')}"
    bbrec = json.loads(Path(str(bb) + ".json").read_text()) if Path(str(bb) + ".json").is_file() else {}
    bbtext = Path(str(bb) + ".md").read_text() if Path(str(bb) + ".md").is_file() else ""
    ck(d.get("applied") and (d.get("catchup") or {}).get("agent") == "codex"
       and bret.get("agent") == "codex" and bbrec.get("kind") == "back"
       and bbrec.get("note_for") == S2 and "Codex worked on mac" in bbtext
       and (shop / "src" / "app.py").read_text() == "print(2)\n",
       f"send back: home writes a back relay with the catch-up made here, for its Claude Code "
       f"session ({d.get('error') or d.get('blockers')}, {bret}, {bbtext[:200]})")

    # (9) Bring Here into Kimi in never-ask mode with --no-open: no run of its
    # own reads the summary, so the line it prints opens Kimi (no "-S <the
    # new session>"), and it gives the first prompt to paste
    shop2 = gbh / "code" / "shop2"
    (shop2 / "src").mkdir(parents=True)
    (shop2 / "src" / "app.py").write_text("print(1)\n")
    bx("tag", str(shop2), "--apply")
    S3 = "8e7f6a5b-3333-4444-8555-666677778888"
    st3 = gbh / ".claude" / "projects" / enc(str(shop2))
    st3.mkdir(parents=True)
    (st3 / f"{S3}.jsonl").write_text(json.dumps(
        {"type": "user", "cwd": str(shop2), "sessionId": S3, "version": "9.9.9",
         "entrypoint": "cli", "timestamp": iso(time.time() - 200),
         "permissionMode": "bypassPermissions",
         "message": {"role": "user", "content": "tidy the cart"}}) + "\n")
    klog = gb / "kimi.log"
    n_k = len(klog.read_text().splitlines()) if klog.is_file() else 0
    n_t = len(tlog.read_text().splitlines()) if tlog.is_file() else 0
    d = G("bring", "/home/code/shop2", "--from", "box", "--agent", "kimi", "--no-open", "--apply",
          "--json")
    ran = klog.read_text().splitlines()[n_k:] if klog.is_file() else []
    ck(d.get("applied") and (d.get("perm") or {}).get("level") == "never"
       and d.get("start_line") == f"{q(gs / 'kimi')} --auto" and d.get("agent_session") is None
       and "<the new session>" not in (d.get("command_line") or "<none>")
       and (d.get("first_prompt") or "").startswith(
           f"You are taking over this project from Claude Code on box. Read "
           f".aht/handover/relay-{d.get('relay')}.md first")
       and not ran and len(tlog.read_text().splitlines() if tlog.is_file() else []) == n_t,
       f"bring --agent kimi --no-open in never-ask: a line that opens Kimi, and the first prompt "
       f"to paste; no run of its own ({d.get('start_line')}, {d.get('command_line')}, "
       f"{d.get('first_prompt')}, {ran}, {d.get('blockers') or d.get('error')})")

    # (10) Hand Over with a task: every agent's start there carries it; in
    # never-ask mode Kimi's run of its own reads the summary and then works
    # on the task, instead of being told not to start
    task = "add the tests"
    for a in ("codex", "agy", "vibe"):
        dd = G("handover", api, "--to", "box", "--agent", a, "--task", task, "--json")
        ck(dd.get("_rc") == 0 and "Read .aht/handover/relay-" in (dd.get("start_line") or "")
           and "Then work on this: add the tests" in (dd.get("start_line") or ""),
           f"hand over --agent {a} --task: its start line there carries the task "
           f"({dd.get('start_line')}, {dd.get('blockers') or dd.get('error')})")
    kl = gbh / ".fake-kimi.log"
    d = G("handover", api, "--to", "box", "--agent", "kimi", "--task", task, "--apply", "--json")
    reads = [r["args"] for r in map(json.loads, kl.read_text().splitlines() if kl.is_file() else [])
             if "-p" in r["args"]]
    kp = reads[-1][reads[-1].index("-p") + 1] if reads else ""
    kw = (gbh / ".aht" / "remote" / "run" / ((d.get("away") or {}).get("window") or "none"))
    kwj = json.loads((kw / "window.json").read_text()) if (kw / "window.json").is_file() else {}
    kcmd = (kw / "command.txt").read_text() if (kw / "command.txt").is_file() else ""
    ck(d.get("applied") and d.get("first_prompt") is None and len(reads) == 1
       and kp.startswith("You are taking over this project from Claude Code on mac. This is "
                         "where the work stood:")
       and kp.endswith("\nThen work on this: add the tests") and "Do not start" not in kp
       and kwj.get("agent") == "kimi" and kwj.get("session")
       and f"--auto -S {kwj.get('session')}" in kcmd,
       f"hand over --agent kimi --task in never-ask: Kimi's own run reads the summary, then the "
       f"task; its window opens that session ({d.get('error') or d.get('blockers')}, "
       f"{kp[-160:]!r}, {kcmd[:200]})")

    ck(not fx8, f"the --json the front-ends read keeps every key of tests/fixtures/phase8 ({fx8})")
    # nothing of these tests runs on: windows, agents, helpers
    for w in (gbh / ".faketmux").glob("*.json"):
        rec = json.loads(w.read_text())
        if rec.get("alive"):
            try:
                if rec.get("runs"):
                    os.killpg(int(rec["pid"]), 9)
                else:
                    os.kill(int(rec["pid"]), 9)
            except OSError:
                pass
    for f in (gbh / ".aht" / "remote" / "run").glob("*/awake.pid"):
        try:
            pid = int(json.loads(f.read_text())["pid"])
            if "_awake" in core._cmdline_of(pid):
                os.kill(pid, 9)
        except (OSError, ValueError, KeyError):
            pass
    for pid in holds():
        try:
            os.kill(pid, 9)
        except OSError:
            pass

if os.name == "nt" or handover_name(sb) > 255:
    print("  SKIP another agent on the other machine: its stand-ins need macOS or Linux and a "
          "short sandbox path")
else:
    phase8_suite()

done()
