#!/usr/bin/env python3
"""[17g] a Windows PC that answers: Hand Over, Take Back, Watch, the board, search."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)

print("\n[17g] a Windows PC that answers: Hand Over, Take Back, Watch, the board, search")
FIXTURES9 = HERE / "fixtures" / "phase9"

def phase9_suite():
    """A Mac hands a project over to a PC and takes it back, watches the PC
    and searches it.  pc is a folder standing in for the PC (its core runs
    there with a home of its own and answers as a PC's does: system
    Windows, `start` queues Continue here, `stop` says windows); the PCs
    asked over "ssh" are fake_ssh.py hosts that read aht's command line the
    way cmd.exe does and run what the PC has (aht.exe, py, python).  No
    ssh, no real agent, no token."""
    import shlex
    fx9 = []
    ge = iso_env("phase9")
    gb = Path(ge["HOME"]).parent
    pcr = gb / "pc"
    pch = pcr / "home"
    for d in (".claude/sessions", ".claude/projects", ".aht"):
        (pch / d).mkdir(parents=True, exist_ok=True)
    gs = gb / "stubs"
    gs.mkdir()
    clog, tlog, nlog = gb / "calls.log", gb / "terminal.log", gb / "notices.log"
    # Claude Code here (9.9.9), and on the PC one whose version a `claude
    # install <version>` changes, as the real one does
    (gs / "claude").write_text(f'#!/bin/sh\necho "claude $*" >> "{clog}"\n'
                               '[ "$1" = "--version" ] && echo "9.9.9 (Claude Code)"\nexit 0\n')
    pver = gs / "pc-claude.ver"
    pver.write_text("9.9.9")
    (gs / "pc-claude").write_text(
        f'#!/bin/sh\necho "pc-claude $*" >> "{clog}"\n'
        f'[ "$1" = "--version" ] && echo "$(cat "{pver}") (Claude Code)"\n'
        f'[ "$1" = "install" ] && printf "%s" "$2" > "{pver}"\nexit 0\n')
    for f in gs.iterdir():
        if f.suffix != ".ver":
            f.chmod(0o755)
    (gb / "no-tabs.json").write_text("{}")
    ge.update(AHT_CLAUDE=str(gs / "claude"), AHT_REMOTE_CLAUDE=str(gs / "pc-claude"),
              AHT_TERMINAL_LOG=str(tlog), AHT_ITERM_TABS=str(gb / "no-tabs.json"),
              AHT_NO_SEARCH_INDEX="1", AHT_MACHINE_NAME="mac", AHT_REMOTE_MACHINE_NAME="pc",
              AHT_AGENT_PROCS="[]", AHT_REMOTE_AGENT_PROCS="[]", AHT_NO_MIRROR="1",
              AHT_NOTIFY_LOG=str(nlog), AHT_SESSION_BUS=str(gb / "no-bus"),
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
    # the PC's own aht (its tray asks it): its home, its name
    pe = {k: v for k, v in ge.items() if not k.startswith("AHT_REMOTE")}
    pe.update(HOME=str(pch), AHT_HOME=str(pch / ".aht"),
              AHT_ROOT_CLAUDE=str(pch / ".claude" / "projects"), AHT_MACHINE_NAME="pc",
              AHT_TERMINAL_LOG=str(gb / "pc-terminal.log"),
              AHT_NOTIFY_LOG=str(gb / "pc-notices.log"), AHT_CLAUDE=str(gs / "pc-claude"))
    def PCJ(*a):
        r = subprocess.run([PY, LAUNCH, *a], env=pe, capture_output=True, text=True)
        try:
            d = json.loads(r.stdout)
        except ValueError:
            d = {"unparsed": r.stdout[-600:] + r.stderr[-900:]}
        if isinstance(d, dict):
            d["_rc"] = r.returncode
        return d
    G("config", "--set", "remotes=" + json.dumps({"pc": {"root": str(pcr),
                                                         "system": "Windows"}}))

    # a project here, its Claude Code session, the folder trusted here
    shop = os.path.realpath(str(Path(ge["HOME"]) / "code" / "shop"))
    os.makedirs(shop + "/src")
    Path(shop, "src", "app.py").write_text("old\n")
    S1 = "5d6e7f80-1111-4222-8333-444455556666"
    st1 = Path(ge["AHT_ROOT_CLAUDE"]) / enc(shop)
    st1.mkdir(parents=True)
    (st1 / f"{S1}.jsonl").write_text("".join(json.dumps(e) + "\n" for e in (
        {"type": "user", "cwd": shop, "sessionId": S1, "version": "9.9.9", "entrypoint": "cli",
         "timestamp": iso(time.time() - 600), "message": {"role": "user",
                                                         "content": "refactor the checkout"}},
        {"type": "ai-title", "aiTitle": "Checkout flow"},
        {"type": "assistant", "cwd": shop, "sessionId": S1, "timestamp": iso(time.time() - 590),
         "message": {"role": "assistant", "content": [{"type": "text",
                                                       "text": "Half done; tests next."}]}})))
    Path(ge["AHT_ROOT_CLAUDE"]).parent.parent.joinpath(".claude.json").write_text(json.dumps(
        {"projects": {shop: {"hasTrustDialogAccepted": True}}}))
    (pch / ".claude.json").write_text(json.dumps({"projects": {}}))
    iso_run(ge, "tag", shop, "--apply")
    far = str(pcr) + shop                   # where it goes on the test PC

    # (1) the dry run: no tmux needed, no session starts, the tray's words
    d = G("handover", shop, "--to", "pc", "--json")
    fx9 += fixture_ok(d, "handover_to_pc_dry.json", FIXTURES9)
    ck(d["_rc"] == 0 and d.get("pc") is True and not d.get("blockers")
       and (d.get("there") or {}).get("system") == "Windows" and d.get("transfer") == "aht"
       and (d.get("plan") or {}).get("install_claude") is None,
       f"hand over to a PC, dry run: Windows there, aht's own copy, no tmux asked for "
       f"({d.get('blockers') or d.get('error') or d.get('unparsed')})")
    r = subprocess.run([PY, LAUNCH, "handover", shop, "--to", "pc"], env=ge, capture_output=True,
                       text=True)
    ck("   on pc          no session starts there: its tray offers “shop came from mac — "
       "Continue here”" in r.stdout,
       f"…in words: no session starts there, the tray's offer ({r.stdout[-500:]})")
    d = G("handover", shop, "--to", "pc", "--agent", "codex", "--json")
    ck(any("Codex does not start on pc: no session starts on a PC" in b
           for b in d.get("blockers") or []),
       f"hand over --agent codex to a PC: refused, no agent starts there ({d.get('blockers')})")
    pver.write_text("9.9.8")
    d = G("handover", shop, "--to", "pc", "--json")
    ck(not d.get("blockers") and (d.get("plan") or {}).get("install_claude") == "9.9.9",
       f"Claude Code 9.9.8 on the PC: the handover installs this machine's 9.9.9 there "
       f"({d.get('blockers')}, {(d.get('plan') or {}).get('install_claude')})")

    # (2) --apply: the files and the history go, Claude Code there is
    # brought to this machine's version (claude install), the trust is
    # carried, and Continue here is queued for the PC's tray.  The session
    # here skips permissions, and this machine caps the level at auto: the
    # arrival keeps the level the handover named (and its note), so the PC
    # never reads the session's own level again
    with open(st1 / f"{S1}.jsonl", "a") as fh:
        fh.write(json.dumps({"type": "user", "cwd": shop, "sessionId": S1,
                             "permissionMode": "bypassPermissions",
                             "timestamp": iso(time.time() - 300),
                             "message": {"role": "user", "content": "go on"}}) + "\n")
    G("config", "--set", "agent_permissions=max:auto")
    G("config", "--set", 'handover_claude_args=["--verbose"]')
    d = G("handover", shop, "--to", "pc", "--apply", "--json")
    fx9 += fixture_ok(d, "handover_to_pc_apply.json", FIXTURES9)
    away = d.get("away") or {}
    win = away.get("window") or "none"
    arr = pch / ".aht" / "arrivals" / f"{win}.json"
    rec = json.loads(arr.read_text()) if arr.is_file() else {}
    fx9 += fixture_ok(rec, "arrival.json", FIXTURES9)
    cj = json.loads((pch / ".claude.json").read_text())
    ck(d.get("applied") and d.get("started") is False and d.get("start_reason") == "windows"
       and d.get("arrival") == win and away.get("arrival") is True and away.get("mux") is None
       and away.get("system") == "Windows" and d.get("attach") is None
       and Path(far, "src", "app.py").read_text() == "old\n"
       and (pch / ".claude" / "projects" / enc(far) / f"{S1}.jsonl").is_file()
       and d.get("trust") == "carried over"
       and cj["projects"].get(far, {}).get("hasTrustDialogAccepted") is True,
       f"hand over to a PC --apply: the files and the history there, no session started, "
       f"the trust carried ({d.get('error') or d.get('blockers')}, {d.get('started')}, "
       f"{d.get('trust')})")
    ck("pc-claude install 9.9.9" in clog.read_text() and pver.read_text() == "9.9.9",
       f"…Claude Code on the PC was brought to 9.9.9 with `claude install 9.9.9` "
       f"({clog.read_text()[-300:]})")
    ck(rec.get("text") == "shop came from mac" and rec.get("action") == "Continue here"
       and rec.get("detail") == "Continue here opens Claude Code in shop, in the session "
                                "handed over from mac. Nothing runs until you type."
       and rec.get("argv") == ["_arrival", "--continue", win]
       and rec.get("resume") == ["resume-here", far, "--session", S1]
       and rec.get("path") == far and rec.get("session") == S1 and rec.get("from") == "mac"
       and rec.get("title") == "Checkout flow" and rec.get("attempt") == away.get("attempt")
       and (pch / ".aht" / "remote" / "run" / win / f"attempt-{away.get('attempt')}").is_file(),
       f"…the arrival there: “shop came from mac — Continue here”, what it runs, the "
       f"attempt's trace ({rec})")
    prun = pch / ".aht" / "remote" / "run" / win
    pnote = (prun / "note.txt").read_text() if (prun / "note.txt").is_file() else ""
    ck(rec.get("args") == ["--permission-mode", "auto", "--verbose"]
       and rec.get("claude_sandbox") is False and rec.get("note") == str(prun / "note.txt")
       and pnote.startswith("[aht] This session was handed over from “mac”"),
       f"…with the level the handover named (auto: capped here, though the session skips "
       f"permissions), handover_claude_args after it, and the note, in the PC's ~/.aht "
       f"({rec.get('args')}, {rec.get('claude_sandbox')}, {rec.get('note')}, {pnote[:80]!r})")
    row = next((p for p in G("projects", "--json").get("projects") or []
                if p["real_path"] == shop), {})
    fx9 += fixture_ok(row, "projects_away_on_pc.json", FIXTURES9)
    ck(row.get("away_arrival") is True and row.get("away_system") == "Windows"
       and row.get("away_window") == win,
       f"projects --json: away_arrival and away_system ({row.get('away_arrival')}, "
       f"{row.get('away_system')})")
    r = subprocess.run([PY, LAUNCH, "attach", shop, "--print"], env=ge, capture_output=True,
                       text=True)
    ck(r.returncode == 2 and "its tray offers Continue here" in r.stderr,
       f"attach: no session runs on a PC for aht to open ({r.stderr.strip()})")

    # (3) the PC's own aht: the tray's list, one notice, Continue here
    a = PCJ("_arrival", "--json")
    n1, n2 = PCJ("notices", "--json"), PCJ("notices", "--json")
    arrs = [n for n in n1.get("notices") or [] if n.get("kind") == "arrival"]
    ck([r.get("name") for r in a.get("arrivals") or []] == [win]
       and [(n["title"], n["message"]) for n in arrs]
       == [("shop came from mac", rec.get("detail"))]
       and (arrs[0].get("info") or {}).get("name") == win
       and not [n for n in n2.get("notices") or [] if n.get("kind") == "arrival"],
       f"on the PC: `_arrival --json` lists it; the notices announce it once "
       f"({a.get('arrivals')}, {arrs}, {n2.get('notices')})")
    c = PCJ("_arrival", "--continue", win, "--json")
    pterm = (gb / "pc-terminal.log").read_text() if (gb / "pc-terminal.log").is_file() else ""
    rec2 = json.loads(arr.read_text()) if arr.is_file() else {}
    ck(c.get("applied") and f"--resume {S1}" in pterm and far in pterm
       and rec2.get("continued") and rec2.get("notified"),
       f"Continue here (`_arrival --continue`): Claude Code resumes the session in a new "
       f"console there; the record notes it ({c}, {pterm[-300:]})")
    pset = prun / "settings.json"
    try:
        hook = json.loads(pset.read_text())["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    except (OSError, ValueError, KeyError, IndexError):
        hook = None
    ck(f"--permission-mode auto --verbose --resume {S1} --settings "
       f"{shlex.quote(str(pset))}" in pterm and "--dangerously-skip-permissions" not in pterm
       and hook == "cat " + shlex.quote(str(prun / "note.txt")),
       f"…in the level the handover named, never more (not the session's own skip "
       f"permissions), with a SessionStart hook that tells it the note ({pterm[-400:]}, "
       f"{hook})")
    nh = getattr(core, "_note_hook", None)
    nt_hook = nh(Path("C:\\Users\\me\\.aht\\remote\\run\\aht-shop-1\\note.txt"),
                 nt=True)["hooks"]["SessionStart"][0]["hooks"][0]["command"] if nh else None
    # Claude Code on Windows runs hooks through Git Bash, where `type` names
    # commands: the note is read with cat, the path's slashes forward
    ck(nt_hook == "cat C:/Users/me/.aht/remote/run/aht-shop-1/note.txt",
       f"…on Windows the hook is Git Bash's `cat`, with forward slashes ({nt_hook})")
    n_lines = pterm.count("\n")
    c2 = PCJ("_arrival", "--continue", win, "--json")
    pterm2 = (gb / "pc-terminal.log").read_text()
    c3 = PCJ("_arrival", "--continue", win, "--again", "--json")
    pterm3 = (gb / "pc-terminal.log").read_text()
    ck(c2["_rc"] == 1 and not c2.get("applied") and "was already used" in (c2.get("error") or "")
       and f"aht _arrival --continue {win} --again" in (c2.get("error") or "")
       and pterm2.count("\n") == n_lines
       and c3.get("applied") and pterm3.count("\n") == n_lines + 1,
       f"a second Continue here is refused (that session may be open), unless --again "
       f"({c2.get('error')}, {c3})")
    c = PCJ("_arrival", "--continue", "aht-nothing-123456", "--json")
    ck(c["_rc"] == 1 and "nothing to continue" in (c.get("error") or ""),
       f"Continue here on something that is not there: refused ({c})")

    # (4) the board asks the PC; a session open there blocks Take Back, and
    # --stop does not end it (a session on a PC is the user's to end)
    b = G("board", "--json")
    bx = next((m for m in b.get("machines") or [] if m["machine"] == "pc"), {})
    ck(bx.get("reachable") and bx.get("host"), f"board: the PC answers ({bx})")
    sl = subprocess.Popen(["sleep", "600"], cwd="/")
    srec = pch / ".claude" / "sessions" / f"{sl.pid}.json"
    srec.write_text(json.dumps({"pid": sl.pid, "cwd": far, "sessionId": S1, "status": "idle"}))
    try:
        d1 = G("reclaim", shop, "--json")
        d2 = G("reclaim", shop, "--stop", "--apply", "--json")
    finally:
        sl.kill()
        sl.wait()
        srec.unlink()
    ck(not d1.get("applied") and any("(aht does not end a session on a PC)" in x
                                     for x in d1.get("blockers") or [])
       and not d2.get("applied") and not d2.get("stopped") and not d2.get("would_stop")
       and any("(aht does not end a session on a PC)" in x for x in d2.get("blockers") or []),
       f"Take Back while a session is open on the PC: blocked, also with --stop "
       f"({d1.get('blockers')}, {d2.get('blockers')})")
    st = core.Remote("pc", {"root": str(pcr), "system": "Windows"})
    rq = subprocess.run([PY, "-c", "import sys, json; sys.path.insert(0, sys.argv[1]); "
                         "import aht; r = aht.Remote('pc', json.loads(sys.argv[2])); "
                         "print(json.dumps([r.agent('stop', path=sys.argv[3], name=sys.argv[4]),"
                         " r.agent('close', path=sys.argv[3], name=sys.argv[4])]))",
                         str(HERE.parent), json.dumps({"root": str(pcr), "system": "Windows"}),
                         far, win], env=ge, capture_output=True, text=True)
    try:
        stop, close = json.loads(rq.stdout)
    except ValueError:
        stop, close = {"err": rq.stderr[-300:]}, {}
    ck(stop.get("stopped") is False and stop.get("reason") == "windows"
       and close.get("closed") is False and close.get("reason") == "windows" and arr.is_file(),
       f"the ops on a PC: stop and close say windows, Continue here stays offered "
       f"({stop}, {close})")
    del st

    # (5) Take Back: what was done on the PC comes here; the PC forgets the
    # arrival, and notes its copy as one whose project went home
    Path(far, "src", "app.py").write_text("made on the pc\n")
    d = G("reclaim", shop, "--json")
    ck(not d.get("blockers") and (d.get("plan") or {}).get("project", {}).get("take") == 1,
       f"Take Back from a PC, dry run: one file changed there ({d.get('blockers') or d.get('error')}, "
       f"{d.get('plan')})")
    d = G("reclaim", shop, "--apply", "--json")
    cop = json.loads((pch / ".aht" / "remote" / "copies.json").read_text()) \
        if (pch / ".aht" / "remote" / "copies.json").is_file() else {}
    a = PCJ("_arrival", "--json")
    ck(d.get("applied") and Path(shop, "src", "app.py").read_text() == "made on the pc\n"
       and not arr.exists() and (cop.get(far) or {}).get("kind") == "returned"
       and a.get("arrivals") == [],
       f"Take Back from a PC --apply: the change came here, the arrival is gone there, its "
       f"copy is noted as returned ({d.get('error') or d.get('blockers')}, {cop.get(far)})")

    # (6) a link that drops after `start`: the next check finishes it, in a
    # PC's words
    d = G("handover", shop, "--to", "pc", "--apply", "--json", AHT_TEST_DROP="start")
    n = G("notices", "--json")
    msgs = [x["message"] for x in n.get("notices") or [] if x.get("kind") == "handover"]
    ck(not d.get("applied") and any("Handover of shop to pc finished: Continue here waits "
                                    "there" in m for m in msgs) and arr.is_file(),
       f"the link drops after “start”: the next check finishes it, Continue here waits on "
       f"the PC ({d.get('error')}, {msgs})")
    d = G("reclaim", shop, "--apply", "--json")
    ck(d.get("applied") and not arr.exists(), f"…and it comes back ({d.get('error')})")

    # (7) PCs asked over "ssh": fake_ssh reads aht's line as cmd.exe does
    fdir = gb / "far"
    sshbin = gb / "sshbin"
    sshbin.mkdir()
    (sshbin / "ssh").write_text(f'#!/bin/sh\nexec "{PY}" "{HERE / "fake_ssh.py"}" "$@"\n')
    (sshbin / "ssh").chmod(0o755)
    se = dict(ge, PATH=str(sshbin) + os.pathsep + ge["PATH"], FAKE_SSH_DIR=str(fdir))
    se.pop("AHT_REMOTE_CLAUDE", None)
    def S(*a, **extra):
        return G(*a, **dict(se, **extra))
    def host(ip, shell="", **has):
        h = fdir / ip
        (h / "home").mkdir(parents=True)
        (h / "windows").write_text(shell)
        (h / "path").write_text(ge["PATH"])
        (h / "env").write_text(f"AHT_CLAUDE={gs / 'pc-claude'}\nAHT_NO_ICONS=1\n"
                               "AHT_NO_NOTIFY=1\nAHT_MACHINE_NAME=pc\n")
        for k, v in has.items():
            (h / k).write_text(v)
        return h
    def lines(h):
        return [json.loads(l) for l in (h / "commands.log").read_text().splitlines()] \
            if (h / "commands.log").is_file() else []
    cid = hashlib.sha256(Path(CLI).read_bytes()).hexdigest()[:12]
    G("config", "--set", "remotes={}")
    hp = host("127.0.0.21", py="")
    r = subprocess.run([PY, LAUNCH, "remote", "add", "pcpy", "far@127.0.0.21"], env=se,
                       capture_output=True, text=True)
    cfg = json.loads((gb / ".aht" / "config.json").read_text())
    sent = lines(hp)
    ck(r.returncode == 0 and "aht answers there through aht's own copy, with py -3" in r.stdout
       and (cfg["remotes"].get("pcpy") or {}).get("runner") == "py"
       and cfg["remotes"]["pcpy"].get("system") == "Windows"
       and sorted(p.name for p in (hp / "home" / ".aht" / "remote").glob("aht*.py"))
       == [f"aht-{cid}.py"]
       and not any(x in c for c in sent[1:] for x in ("mkdir", "exec ", "cat ", "&&"))
       and [c.split(" ", 2)[:2] for c in sent[1:3]] == [["aht", "_agent"], ["py", "-3"]],
       f"remote add of a PC with Python: aht.exe tried first, then aht's own copy with "
       f"py -3, sent as bytes by a line of its own, no sh ({r.stdout.strip()} "
       f"{r.stderr.strip()[-300:]}, {[c[:60] for c in sent]})")
    d = S("remote", "check", "pcpy", "--json")
    fx9 += fixture_ok(d, "remote_check_pc.json", FIXTURES9)
    m = (d.get("machines") or [{}])[0]
    rows = {c["check"]: c for c in m.get("checks") or []}
    # the stand-in PC has no Claude login: on Linux its probe says so (macOS
    # keeps the login in the keychain, so there it is unknown); that row alone
    # may fail here
    bad = [k for k, c in rows.items() if c.get("needed") and not c.get("ok")
           and k != "Claude Code is logged in there"]
    ck(not bad and m.get("runner") == "py" and m.get("system") == "Windows"
       and (rows.get("aht answers there") or {}).get("ok")
       and "aht's own copy, with py -3" in rows["aht answers there"]["detail"]
       and rows.get("copies files with", {}).get("detail") == "aht's own copy"
       and (rows.get("no session starts there") or {}).get("ok")
       and "tmux there" not in rows and not any("awake" in k or "mosh" in k for k in rows),
       f"remote check of a PC: its own rows (aht answers there, Claude Code, aht installed, "
       f"no session starts there), no tmux, keep-awake or mosh rows ({sorted(rows)}; failing: "
       f"{[(k, c.get('detail')) for k, c in rows.items() if c.get('needed') and not c.get('ok')]})")
    lst = S("remote", "--json").get("remotes", {}).get("pcpy", {})
    st = (S("status", "--json").get("handover") or {}).get("remotes", {}).get("pcpy", {})
    ck(lst.get("answers") is True and lst.get("answers_why") is None
       and st.get("answers") is True,
       f"remote --json and status: the PC answers ({lst.get('answers')}, {st.get('answers')})")
    w = S("remote", "watch", "pcpy", "--json")
    b = S("board", "--json")
    bx = next((m for m in b.get("machines") or [] if m["machine"] == "pcpy"), {})
    ck(w.get("applied") and bx.get("reachable") and bx.get("sessions") == [],
       f"Watch a PC, and the board asks it ({w}, {bx.get('error')})")
    # search: the PC's own index answers
    hstore = hp / "home" / ".claude" / "projects" / "C--Users-me-code-heron"
    hstore.mkdir(parents=True)
    (hstore / "h1.jsonl").write_text(json.dumps(
        {"type": "user", "cwd": "C:\\Users\\me\\code\\heron", "sessionId": "h1",
         "timestamp": iso(time.time() - 60),
         "message": {"role": "user", "content": "deploy the heron service"}}) + "\n")
    he = {k: v for k, v in ge.items() if not k.startswith(("AHT_ROOT_", "AHT_REMOTE"))}
    he.update(HOME=str(hp / "home"), AHT_HOME=str(hp / "home" / ".aht"),
              AHT_ROOT_CLAUDE=str(hstore.parent))
    he.pop("AHT_NO_SEARCH_INDEX", None)
    subprocess.run([PY, LAUNCH, "search", "--update", "--quiet"], env=he, capture_output=True)
    d = S("search", "heron", "--everywhere", "--json")
    fm = next((m for m in d.get("machines") or [] if m.get("machine") == "pcpy"), {})
    hits = [x for x in d.get("results") or [] if x.get("machine") == "pcpy"]
    ck(fm.get("reachable") and fm.get("indexed") and len(hits) == 1,
       f"search everywhere: the PC searches its own index ({fm}, {len(hits)})")

    # aht.exe there, at this protocol: it answers, nothing is sent
    he2 = host("127.0.0.22", aht="")
    r = subprocess.run([PY, LAUNCH, "remote", "add", "pcexe", "far@127.0.0.22"], env=se,
                       capture_output=True, text=True)
    cfg = json.loads((gb / ".aht" / "config.json").read_text())
    ck(r.returncode == 0 and (cfg["remotes"].get("pcexe") or {}).get("runner") == "aht"
       and not (he2 / "home" / ".aht" / "remote").exists()
       and [c.split(" ", 2)[:2] for c in lines(he2)[1:]] == [["aht", "_agent"]] * 2,
       f"remote add of a PC with aht installed: aht.exe answers, no copy is sent "
       f"({r.stdout.strip()} {r.stderr.strip()[-200:]}, {lines(he2)[1:]})")
    # an older aht.exe there (protocol 2): Python is asked instead, or, with
    # no Python, the refusal says to update aht there
    old = gb / "old-aht.py"
    old.write_text("import json, sys\nsys.stdin.read()\nprint('\\n@@AHT@@' + json.dumps("
                   "{'ok': True, 'protocol': 2, 'version': '0.13.0', 'ops': ['probe']}))\n")
    ho = host("127.0.0.23", aht=str(old), py="")
    r = subprocess.run([PY, LAUNCH, "remote", "add", "pcold", "far@127.0.0.23"], env=se,
                       capture_output=True, text=True)
    cfg = json.loads((gb / ".aht" / "config.json").read_text())
    ck(r.returncode == 0 and (cfg["remotes"].get("pcold") or {}).get("runner") == "py",
       f"an aht.exe at protocol 2 there is not asked: aht's own copy with py -3 answers "
       f"({r.stdout.strip()} {r.stderr.strip()[-200:]})")
    host("127.0.0.24", aht=str(old))
    r = subprocess.run([PY, LAUNCH, "remote", "add", "pcold2", "far@127.0.0.24"], env=se,
                       capture_output=True, text=True)
    ck(r.returncode == 1 and "update aht on pcold2: the aht there (0.13.0, protocol 2, 3 is "
       "needed)" in r.stderr,
       f"…and with no Python there, a plain refusal: update aht there ({r.stderr.strip()})")
    # PowerShell as ssh's shell: the same line, read alike
    hs = host("127.0.0.25", "powershell\n", python="")
    r = subprocess.run([PY, LAUNCH, "remote", "add", "pcps", "far@127.0.0.25"], env=se,
                       capture_output=True, text=True)
    cfg = json.loads((gb / ".aht" / "config.json").read_text())
    ck(r.returncode == 0 and (cfg["remotes"].get("pcps") or {}).get("runner") == "python"
       and [c.split(" ", 2)[:2] for c in lines(hs)[1:4]]
       == [["aht", "_agent"], ["py", "-3"], ["python", "-X"]],
       f"a PC whose ssh starts PowerShell, with python only: the same lines, python answers "
       f"({r.stdout.strip()} {r.stderr.strip()[-200:]})")
    # a PC set up before aht knew it was one: its first question goes as a
    # sh line, cmd.exe does not know `exec`, and aht asks it as a PC from then on
    hb = host("127.0.0.26", py="")
    G("config", "--set", "remotes=" + json.dumps(dict(
        json.loads((gb / ".aht" / "config.json").read_text())["remotes"],
        pcb={"ssh": "far@127.0.0.26"})))
    b = S("board", "--json")
    bx = next((m for m in b.get("machines") or [] if m["machine"] == "pcb"), {})
    cfg = json.loads((gb / ".aht" / "config.json").read_text())
    ck(bx.get("reachable") and cfg["remotes"]["pcb"].get("system") == "Windows"
       and cfg["remotes"]["pcb"].get("runner") == "py"
       and lines(hb)[0].startswith("exec python3") and os.listdir(hb / "home") == [".aht"],
       f"a PC set up before: `exec` is not recognized there, so it is asked as a PC from then "
       f"on, nothing else made there ({bx.get('error')}, {lines(hb)[:2]})")

    # aht installed on the PC: its tray offers Continue here only from the
    # protocol that brought it on (an older aht there says nothing of it)
    pa = hp / "home" / ".aht"
    pa.mkdir(parents=True, exist_ok=True)
    if not (pa / "config.json").is_file():
        (pa / "config.json").write_text("{}")
    trow = {}
    for proto in (core.PC_PROTOCOL - 1, core.PC_PROTOCOL):
        (pa / "install.json").write_text(json.dumps({"version": "0.13.0", "protocol": proto}))
        m = (S("remote", "check", "pcpy", "--json").get("machines") or [{}])[0]
        trow[proto] = next((c for c in m.get("checks") or []
                            if c["check"] == "aht installed there (its tray offers Continue "
                                             "here)"), {})
    old_t, new_t = trow[core.PC_PROTOCOL - 1], trow[core.PC_PROTOCOL]
    ck(old_t.get("ok") is False
       and "update aht there: its tray does not show Continue here yet" in old_t.get("detail", "")
       and "winget upgrade" in old_t.get("fix", "")
       and new_t.get("ok") is True and new_t.get("detail") == "aht 0.13.0",
       f"remote check: “aht installed there (its tray offers Continue here)” passes only "
       f"from protocol {core.PC_PROTOCOL} ({old_t}, {new_t})")

    # aht's own copy cut short on the way (the link drops while it is
    # written): nothing is put in place, so it is sent again next time,
    # never a broken copy that stays
    data = Path(CLI).read_bytes()
    cut_home = gb / "cut-home"
    cut_home.mkdir()
    cenv = {"HOME": str(cut_home), "PATH": ge["PATH"], "LANG": "en_US.UTF-8"}
    wline = core.nt_agent_line("python", "", cid, write=".aht-new-cut1")
    wargs = [PY, "-X", "utf8", "-c", wline.split('"', 1)[1].rsplit('"', 1)[0]]
    w1 = subprocess.run(wargs, input=data[:200_000], env=cenv, capture_output=True)
    left1 = sorted(os.listdir(cut_home / ".aht" / "remote")) \
        if (cut_home / ".aht" / "remote").is_dir() else []
    w2 = subprocess.run(wargs, input=data, env=cenv, capture_output=True)
    good = cut_home / ".aht" / "remote" / f"aht-{cid}.py"
    ck(w1.returncode != 0 and b"aht-copy-cut-short" in w1.stderr
       and b"aht-copy-written" not in w1.stdout and left1 == []
       and b"aht-copy-written" in w2.stdout and good.is_file() and good.read_bytes() == data,
       f"a PC: aht's copy cut short is not written (its checksum is checked first); whole, it "
       f"is ({w1.returncode}, {w1.stderr[-200:]}, {left1})")
    shutil.rmtree(cut_home / ".aht")
    push = getattr(core, "sh_push_script", None)
    script = push(cid, ".aht-new-cut2") if push else "exit 9"
    s1 = subprocess.run(["/bin/sh", "-c", script], input=data[:200_000], env=cenv,
                        capture_output=True)
    left2 = sorted(os.listdir(cut_home / ".aht" / "remote")) \
        if (cut_home / ".aht" / "remote").is_dir() else ["(none)"]
    s2 = subprocess.run(["/bin/sh", "-c", script], input=data, env=cenv, capture_output=True)
    ck(s1.returncode == 3 and b"aht-copy-cut-short" in s1.stderr and left2 == []
       and s2.returncode == 0 and good.is_file() and good.read_bytes() == data,
       f"a Mac or Linux machine: the same, in sh ({s1.returncode}, {s1.stderr[-200:]}, "
       f"{left2}, {s2.returncode}, {s2.stderr[-200:]})")
    tb = subprocess.CompletedProcess([], 1, "", 'Traceback (most recent call last):\n  File '
                                     '"<string>", line 1, in <module>\n    '
                                     + core.nt_agent_line("py", "", cid).split('"', 1)[1]
                                     + "\nPermissionError: [Errno 13] Permission denied\n")
    ck(not core._nt_copy_missing(tb) and not core._nt_absent(tb)
       and core._nt_copy_missing(subprocess.CompletedProcess([], 1, "", "aht-copy-missing\n")),
       "a traceback that quotes the PC's line is not taken for a missing copy (the word is "
       "built, never in the line), nor for a program that is not there")
    # …and over the link: the first copy is cut off, the next one goes whole
    hc = host("127.0.0.27", py="", **{"cut-input": "200000"})
    r1 = subprocess.run([PY, LAUNCH, "remote", "add", "pccut", "far@127.0.0.27"], env=se,
                        capture_output=True, text=True)
    left3 = sorted(os.listdir(hc / "home" / ".aht" / "remote")) \
        if (hc / "home" / ".aht" / "remote").is_dir() else []
    r2 = subprocess.run([PY, LAUNCH, "remote", "add", "pccut", "far@127.0.0.27"], env=se,
                        capture_output=True, text=True)
    hcopy = hc / "home" / ".aht" / "remote" / f"aht-{cid}.py"
    ck(r1.returncode == 1 and not (hc / "cut-input").exists() and left3 == []
       and r2.returncode == 0 and hcopy.is_file() and hcopy.read_bytes() == data,
       f"a PC whose link drops while aht's copy goes: nothing there, and the next try sends "
       f"it whole ({r1.stderr.strip()[-200:]}, {left3}, {r2.stderr.strip()[-200:]})")
    shm = fdir / "127.0.0.31"
    (shm / "home").mkdir(parents=True)
    (shm / "path").write_text(f"{Path(PY).parent}:/usr/bin:/bin:/usr/sbin:/sbin")
    (shm / "cut-input").write_text("200000")
    rq = subprocess.run([PY, "-c", "import sys, json, os; sys.path.insert(0, sys.argv[1]); "
                         "import aht; r = aht.Remote('shcut', {'ssh': 'far@127.0.0.31'}); out = []\n"
                         "for i in (1, 2):\n"
                         "    try:\n        out.append(bool(r.agent('probe').get('ok')))\n"
                         "    except Exception as e:\n        out.append(type(e).__name__)\n"
                         "    d = sys.argv[2]\n"
                         "    out.append(sorted(os.listdir(d)) if os.path.isdir(d) else [])\n"
                         "print(json.dumps(out))",
                         str(HERE.parent), str(shm / "home" / ".aht" / "remote")],
                        env=se, capture_output=True, text=True)
    try:
        got = json.loads(rq.stdout)
    except ValueError:
        got = [rq.stdout[-200:], rq.stderr[-400:]]
    ck(got == ["LinkError", [], True, [f"aht-{cid}.py"]]
       and (shm / "home" / ".aht" / "remote" / f"aht-{cid}.py").read_bytes() == data,
       f"…and to a Mac or Linux machine over sh: the same ({got})")

    # Windows in another language: no English words are relied on
    hd = host("127.0.0.28", lang="de")
    r = subprocess.run([PY, LAUNCH, "remote", "add", "pcde", "far@127.0.0.28"], env=se,
                       capture_output=True, text=True)
    ck(r.returncode == 1 and "install aht on pcde" in r.stderr and "update aht" not in r.stderr,
       f"a German PC with nothing to answer: install aht there (no aht.exe answered, so "
       f"none is called older) ({r.stderr.strip()})")
    (hd / "python").write_text("")
    r = subprocess.run([PY, LAUNCH, "remote", "add", "pcde", "far@127.0.0.28"], env=se,
                       capture_output=True, text=True)
    (hd / "python").unlink()
    (hd / "py").write_text("")
    b = S("board", "--json")
    bx = next((m for m in b.get("machines") or [] if m["machine"] == "pcde"), {})
    cfg = json.loads((gb / ".aht" / "config.json").read_text())
    ck(r.returncode == 0 and bx.get("reachable")
       and cfg["remotes"]["pcde"].get("runner") == "py",
       f"…with python, then python gone and py there: what answers is found again "
       f"({r.stderr.strip()[-200:]}, {bx.get('error')}, {cfg['remotes']['pcde'].get('runner')})")
    hb2 = host("127.0.0.30", py="", lang="de")
    G("config", "--set", "remotes=" + json.dumps(dict(
        json.loads((gb / ".aht" / "config.json").read_text())["remotes"],
        pcb2={"ssh": "far@127.0.0.30"})))
    b = S("board", "--json")
    bx = next((m for m in b.get("machines") or [] if m["machine"] == "pcb2"), {})
    cfg = json.loads((gb / ".aht" / "config.json").read_text())
    ck(bx.get("reachable") and cfg["remotes"]["pcb2"].get("system") == "Windows"
       and lines(hb2)[0].startswith("exec python3"),
       f"a German PC set up before: its shell's answer, not its words, tells it is a PC "
       f"({bx.get('error')}, {lines(hb2)[:3]})")

    # the folder-identity blocker's command for a PC's folder: in its own
    # form, and `aht remote paths` takes it
    os.environ["AHT_MACHINE_NAME"], was_name = "mac", os.environ.get("AHT_MACHINE_NAME")
    try:
        fixc = core.identity_fix("pcpy", "/Users/me/code/shop", "C:\\Users\\me\\code\\shop") \
            if hasattr(core, "identity_fix") else ""
    finally:
        if was_name is None:
            os.environ.pop("AHT_MACHINE_NAME", None)
        else:
            os.environ["AHT_MACHINE_NAME"] = was_name
    words = shlex.split(fixc)
    pr = S(*words[1:], "--json") if words[:3] == ["aht", "remote", "paths"] else {}
    cfg = json.loads((gb / ".aht" / "config.json").read_text())
    ck(words == ["aht", "remote", "paths", "pcpy", "--add", "/Users/me/code",
                 "C:\\Users\\me\\code\\mac"]
       and pr.get("applied") and not pr.get("error")
       and ["/Users/me/code", "C:\\Users\\me\\code\\mac"] in cfg["remotes"]["pcpy"]["paths"],
       f"the identity blocker's fix for a PC: a C:\\ folder next to it, and `remote paths` "
       f"takes it ({fixc}, {pr.get('error')})")

    # the line itself: what cmd.exe and PowerShell both read as it is
    lines_ = [core.nt_agent_line(r, sb_, "0123456789ab", w)
              for r in ("py", "python") for sb_ in ("", "C:\\Users\\me\\aht-sbx-9")
              for w in (None, ".aht-new-1234")]
    ck(all(l.count('"') == 2 and not any(c in l for c in "%$`^&|<>!") for l in lines_)
       and core.nt_agent_line("aht") == "aht _agent"
       and core.nt_agent_line("aht", "C:\\Users\\me\\aht sbx")
       == 'aht _agent --sandbox "C:\\Users\\me\\aht sbx"'
       and "'C:\\\\Users\\\\me\\\\aht-sbx-9\\\\home'" in lines_[2]
       and "'_agent','--sandbox','C:\\\\Users\\\\me\\\\aht-sbx-9'" in lines_[2],
       f"the far end's line on a PC: one pair of quotes, nothing cmd.exe or PowerShell "
       f"expands; a sandbox is an argument ({lines_[2]})")
    ok_sb = [core.nt_sandbox_ok(x) for x in ("C:\\Users\\me\\aht-sbx-9", "D:\\x y\\s",
                                             "C:\\Users\\me\\..\\x", "C:\\a%b", "/tmp/x",
                                             "C:\\a\\", "C:\\a\\b.")]
    ck(ok_sb == [True, True, False, False, False, False, False],
       f"a PC's sandbox: a plain C:\\ folder only ({ok_sb})")
    ck(core._trust_key("C:\\Users\\me\\code\\shop") == "C:/Users/me/code/shop",
       "the trust key of a PC's folder uses forward slashes, as Claude Code writes it there")
    r = subprocess.run([PY, LAUNCH, "remote", "add", "pcsb", "far@127.0.0.21", "--sandbox",
                        "/tmp/aht-sbx"], env=se, capture_output=True, text=True)
    ck(r.returncode == 1 and "its sandbox is a folder such as" in r.stderr,
       f"remote add --sandbox /tmp/… for a PC: refused ({r.stderr.strip()})")
    ck(not fx9, f"the JSON keeps every key of the phase 9 samples ({fx9})")

if os.name == "nt" or handover_name(sb) > 255:
    print("  SKIP a Windows PC that answers: its stand-ins need macOS or Linux and a short "
          "sandbox path")
else:
    phase9_suite()

done()
