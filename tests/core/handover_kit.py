"""The handover suite of the core tests ([16], [16c], [16g]), for the units
that run it once per mover (tests/core/16*_rsync.py and 16*_aht.py).

The original (tests/core_test.py) ran handover_suite() once per mover: its
setup of the stand-in machine "box", its own [16] checks, phase1_suite (the
rest of [16]), phase5_suite ([16c]) and phase7_suite ([16g]).  Here each part
is a unit of its own, and so are the halves of the two longest ones:

  own_checks + own_checks_more            handover_suite's own checks
  phase1_unfinished + phase1_far_end      phase1_suite
  phase5_suite, phase7_suite              as they were

Each unit sets up "box" itself (setup(), and configure() for the config
handover_suite's first lines leave), and a second half rebuilds, in a block
at its top, what the first half left that its checks need: no unit depends
on another.  The code is the original's, copied; a unit prints its section's
header itself (start() prints the mover line)."""
from common import *  # noqa: F401,F403  (the unit's sandbox, ck, run, ...)
import types

# what [14] left: the probe of a folder's marks (handover_suite uses it)
marks_probe = ("import sys; sys.path.insert(0, sys.argv[1]); import aht; "
               "print(aht.desired_marks(sys.argv[2], True))")


def start(mover):
    """The lines the original printed before running the suite with `mover`
    (its skips, the mover line), and AHT_TRANSFER set to it in env and
    os.environ.  False: this unit runs nothing (it then ends with done())."""
    if os.name == "nt":
        print("  SKIP the handover suite's stand-ins (tmux, a far sh) need macOS or Linux; "
              "[16c] tests the copy itself here and [16g] the rules across systems")
        return False
    if handover_name(sb) > 255:
        print(f"  SKIP the sandbox's path is too long for this test: the other machine's "
              f"history folder name holds it twice, {handover_name(sb)} characters where 255 "
              f"is the most.  Run it with a TMPDIR of at most "
              f"{(255 - len('/box/roots/Hand Over')) // 2 - len('/aht_core_12345678')} characters "
              f"(for example TMPDIR=/tmp).")
        return False
    if mover == "rsync" and not core.find_rsync():
        print("  (no rsync 3 here: the suite runs with aht's own copy only)")
        return False
    print(f"\n  --- the handover suite, files copied with {mover} ---")
    env["AHT_TRANSFER"] = os.environ["AHT_TRANSFER"] = mover
    return True


def setup():
    """handover_suite's setup: the stand-in machine "box", the stand-in
    tools, henv and the helpers its parts are handed."""
    box = Path(os.path.realpath(sb)) / "box"    # a folder standing in for the machine
    bhome = box / "home"
    (bhome / ".claude").mkdir(parents=True)
    (bhome / ".claude.json").write_text("{}")
    stubs = sb / "stubs"
    stubs.mkdir()
    fake = f'#!/bin/sh\nexec "{PY}" "{HERE / "fake_tmux.py"}" "$@"\n'
    (stubs / "tmux").write_text(fake)
    (stubs / "byobu").write_text(fake)
    (stubs / "claude").write_text('#!/bin/sh\necho "9.9.9 (Claude Code)"\n')
    for s in stubs.iterdir():
        s.chmod(0o755)
    henv = {"AHT_REMOTE_PATH": str(stubs), "AHT_CLAUDE": str(stubs / "claude"),
            "AHT_NO_MIRROR": "1"}
    def hrun(*a):
        return run(*a, extra_env=henv)
    def J(r):
        try:
            return json.loads(r.stdout)
        except Exception:
            return {"unparsed": r.stdout[-400:] + r.stderr[-400:]}
    def hook(path):
        return subprocess.run([PY, LAUNCH, "hook"], env=dict(env, **henv),
                              capture_output=True, text=True,
                              input=json.dumps({"cwd": path})).stdout
    def project_row(path):
        return next(p for p in J(hrun("projects", "--json"))["projects"]
                    if p["real_path"] == path)
    def open_there():
        return core.running_sessions(home=bhome / ".claude")
    return types.SimpleNamespace(box=box, bhome=bhome, stubs=stubs, henv=henv, hrun=hrun, J=J,
                                 hook=hook, project_row=project_row, open_there=open_there)


def configure(h):
    """What handover_suite's first lines leave in the config, for a unit that
    does not run them (and their check) itself."""
    h.hrun("config", "--set", "remotes=" + json.dumps({"box": {"root": str(h.box)}}))
    h.hrun("config", "--set", "handover_keep_awake=false")


def stop_stand_ins(bhome):
    """The end of handover_suite: the stand-in sessions on box are stopped."""
    for w in (bhome / ".faketmux").glob("*.json"):   # the stand-in sessions
        rec = json.loads(w.read_text())
        if rec.get("alive"):
            try:
                os.kill(int(rec["pid"]), 15)
            except OSError:
                pass


def own_checks(h):
    """handover_suite's own checks ([16]), the first part: a handover and back
    with its safety rules, the mirror, a newer agent CLI there (the rest is
    own_checks_more)."""
    box, bhome, stubs, henv, hrun, J, hook, project_row, open_there = (
        h.box, h.bhome, h.stubs, h.henv, h.hrun, h.J, h.hook, h.project_row, h.open_there)
    r = hrun("config", "--set", "remotes=" + json.dumps({"box": {"root": str(box)}}))
    ck(r.returncode == 0, "a machine can be named in the config")
    # the stand-in machines are this one: nothing here may keep it awake, and
    # no helper may outlive the test ([17c] tests the keep-awake helper)
    hrun("config", "--set", "handover_keep_awake=false")
    # which mover copies the files: a machine's row says so
    mover = os.environ.get("AHT_TRANSFER")
    d = J(hrun("remote", "check", "box", "--json"))
    m0 = (d.get("machines") or [{}])[0]
    row = next((c for c in m0.get("checks") or [] if c.get("key") == "transfer"), {})
    fx6 = fixture_ok(d, "remote_check.json", FIXTURES6)
    # auto takes rsync with rsync 3 here and any rsync there: the row says so
    ck(m0.get("transfer") == mover and row.get("transfer") == mover and row.get("ok")
       and not row.get("needed") and not fx6
       and (mover != "aht" or "rsync 3 here and any rsync there" in row.get("detail", ""))
       and all(c["needed"] == (mover == "rsync")
               for c in m0.get("checks") or [] if "rsync" in c["check"]),
       f"remote check: the machine's `transfer` is {mover}; rsync is needed only when the "
       f"setting asks for it ({row.get('detail')}; {fx6})")

    projH = os.path.realpath(str(roots / "Hand Over"))
    os.makedirs(projH + "/sub")
    os.makedirs(projH + "/node_modules/pkg")
    nfd = unicodedata.normalize("NFD", "Stürmer.txt")
    for rel, body in (("a.txt", "a1\n"), ("sub/b.txt", "b1\n"), ("c.txt", "c1\n"),
                      ("d.txt", "d1\n"), (nfd, "umlaut\n"), ("Icon\r", ""),
                      ("node_modules/pkg/x.js", "x\n")):
        Path(projH, rel).write_text(body)
    hstore = tools / "claude" / enc(projH)
    (hstore / "memory").mkdir(parents=True)
    (hstore / "memory" / "MEMORY.md").write_text("- note\n")
    outside = str(Path.home() / "elsewhere" / "notes.md")
    if outside.startswith(("/tmp/", "/private/", "/var/")):
        # a throwaway HOME there: aht counts such a path as a temporary file
        # and leaves it out, so the file stands somewhere aht does not
        outside = "/srv/elsewhere/notes.md"
    T0 = "".join(json.dumps(e) + "\n" for e in (
        {"type": "user", "cwd": projH, "version": "9.9.9",
         "message": {"role": "user", "content": "first question"}},
        {"type": "user", "isCompactSummary": True,
         "message": {"role": "user", "content": "SUMMARY: the parser is half done"}},
        {"type": "ai-title", "aiTitle": "Parser work"},
        {"type": "user", "message": {"role": "user", "content": "now fix the lexer"}},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "The lexer is fixed."},
            {"type": "tool_use", "name": "Edit", "input": {"file_path": projH + "/a.txt"}},
            {"type": "tool_use", "name": "Read", "input": {"file_path": outside}},
            {"type": "tool_use", "name": "TodoWrite", "input": {"todos": [
                {"content": "write the tests", "status": "pending"},
                {"content": "publish it", "status": "completed"}]}}]}}))
    (hstore / "s1.jsonl").write_text(T0)
    (sb / ".claude.json").write_text(json.dumps(
        {"projects": {projH: {"hasTrustDialogAccepted": True}}}))
    hrun("tag", projH, "--apply")
    rproj = str(box) + projH
    rstore = bhome / ".claude" / "projects" / enc(rproj)

    d = J(hrun("handover", projH, "--json"))
    ck(d.get("applied") is False and not d.get("blockers")
       and d.get("plan", {}).get("files") == 6 and not os.path.exists(rproj),
       f"dry run: what would travel is counted, nothing is sent ({d.get('plan') or d})")
    ck(d.get("outside_not_carried") == [outside] and d.get("title") == "Parser work",
       "dry run names the session and the outside files that stay behind")

    # SAFETY (1): an open session blocks, working or idle
    sess_dir = tools / "sessions"
    sess_dir.mkdir(exist_ok=True)
    sleeper = subprocess.Popen(["sleep", "600"], cwd="/")
    rec = sess_dir / f"{sleeper.pid}.json"
    rec.write_text(json.dumps({"pid": sleeper.pid, "cwd": projH, "status": "busy",
                               "sessionId": "s1", "name": "parser"}))
    r = hrun("handover", projH, "--apply", "--json")
    d = J(r)
    ck(r.returncode == 3 and not d.get("applied") and not os.path.exists(rproj)
       and any("WORKING" in b for b in d.get("blockers", [])),
       "a WORKING session blocks the handover; nothing leaves")
    rec.write_text(json.dumps({"pid": sleeper.pid, "cwd": projH, "status": "idle",
                               "sessionId": "s1"}))
    d = J(hrun("handover", projH, "--apply", "--json", "--allow-processes"))
    ck(not d.get("applied") and any("exit it first" in b for b in d.get("blockers", []))
       and not os.path.exists(rproj),
       "an open idle session blocks too, and no flag overrides that")
    sleeper.kill(); sleeper.wait()
    ck(core.running_sessions(inside=projH, home=tools) == [],
       "the record a finished session left behind does not block")
    worker = subprocess.Popen(["sleep", "600"], cwd=projH)
    d = J(hrun("handover", projH, "--apply", "--json"))
    ck(not d.get("applied") and any("still running in this folder" in b
                                    for b in d.get("blockers", [])),
       "a program running in the folder blocks")
    worker.kill(); worker.wait()

    r = hrun("handover", projH, "--apply", "--json")
    d = J(r)
    ck(r.returncode == 0 and d.get("applied") and d.get("started"),
       "handover applied and the session started over there "
       f"({d.get('error') or d.get('blockers') or d.get('unparsed') or 'ok'})")
    got = sorted(str(p.relative_to(rproj)) for p in Path(rproj).rglob("*") if p.is_file())
    ck("a.txt" in got and "sub/b.txt" in got and nfd in got
       and not any("node_modules" in g or g.startswith("Icon") for g in got),
       "the project arrived; per-machine folders and the icon file stayed")
    ck((rstore / "s1.jsonl").is_file() and (rstore / "s1.jsonl").read_text() == T0
       and (rstore / "memory" / "MEMORY.md").is_file(),
       "the history arrived under the key of the path over there")
    brief = sorted(Path(projH, ".aht", "handover").glob("*-to-*.md"))
    btxt = brief[-1].read_text() if brief else ""
    ck("SUMMARY: the parser is half done" in btxt and "now fix the lexer" in btxt
       and "The lexer is fixed." in btxt and "write the tests" in btxt
       and "publish it" not in btxt and outside in btxt
       and "first question" not in btxt,
       "readable summary: last compaction, latest exchange, open to-dos, "
       "outside files")
    ck(Path(projH, ".aht", "handover", ".gitignore").read_text().strip() == "*",
       "git is told to ignore the summaries: they quote the conversation")
    win = (d.get("away") or {}).get("window", "?")
    rrun = bhome / ".aht" / "remote" / "run" / win
    note = (rrun / "note.txt").read_text() if rrun.is_dir() else ""
    sett = (rrun / "settings.json").read_text() if rrun.is_dir() else ""
    ck("handed over" in note and outside in note and "note.txt" in sett
       and "SessionStart" in sett,
       "the resumed session is told on arrival what changed around it")
    wfile = bhome / ".faketmux" / f"{win}.json"
    line = json.loads(wfile.read_text())["command"] if wfile.is_file() else ""
    ck("--resume s1" in line and "--settings" in line
       and "--remote-control 'Hand Over'" in line,
       "it resumes the newest session, reachable from the phone")
    trust = json.loads((bhome / ".claude.json").read_text()).get("projects", {})
    ck(trust.get(rproj, {}).get("hasTrustDialogAccepted") is True
       and d.get("trust") == "carried over", "the folder's trust is carried over")
    r = subprocess.run([PY, "-c", marks_probe, str(HERE.parent), projH], env=env,
                       capture_output=True, text=True)
    ck(project_row(projH)["away"] and "agent:away" in r.stdout
       and "agent:claude" not in r.stdout, "the folder is marked as away")
    d = J(hrun("handover", projH, "--apply", "--json"))
    ck(any("already handed over" in b for b in d.get("blockers", [])),
       "a project that is away cannot be handed over again")
    warned = hook(projH)
    ck("WARNING" in warned and "handed over" in warned and project_row(projH)["away"],
       "a session started here meanwhile is warned; the record survives the hook")

    # work over there, and some here
    time.sleep(1.1)
    Path(rproj, "a.txt").write_text("a2 from the box\n")
    Path(rproj, "new.txt").write_text("born there\n")
    Path(rproj, "sub/b.txt").unlink()
    Path(rproj, "c.txt").write_text("c2 THERE\n")
    Path(projH, "c.txt").write_text("c2 HERE\n")
    Path(projH, "d.txt").write_text("d2 here only\n")
    T1 = T0 + json.dumps({"type": "user", "message": {"content": "continued there"}}) + "\n"
    (rstore / "s1.jsonl").write_text(T1)
    (rstore / "s2.jsonl").write_text('{"type":"user"}\n')

    live = open_there()
    srec = bhome / ".claude" / "sessions" / f"{live[0]['pid']}.json" if live else None
    ck(len(live) == 1, "one session is open over there")
    state = json.loads(srec.read_text())
    srec.write_text(json.dumps(dict(state, status="busy")))
    r = hrun("reclaim", projH, "--apply", "--stop", "--json")
    d = J(r)
    ck(r.returncode == 3 and not d.get("applied") and len(open_there()) == 1
       and any("WORKING" in b for b in d.get("blockers", []))
       and Path(projH, "a.txt").read_text() == "a1\n",
       "a session WORKING over there blocks the way back, --stop or not")
    srec.write_text(json.dumps(dict(state, status="idle")))
    d = J(hrun("reclaim", projH, "--apply", "--json"))
    ck(not d.get("applied") and any("--stop" in b for b in d.get("blockers", [])),
       "an idle session there blocks until it is ended")
    d = J(hrun("reclaim", projH, "--stop", "--json"))
    ck(not d.get("applied") and d.get("would_stop") and len(open_there()) == 1
       and d.get("plan", {}).get("project") == {"take": 1, "new": 1, "delete": 1,
                                                "conflict": 1, "kept": 1},
       f"dry run: the plan; the session is left alone ({d.get('plan') or d})")
    r = hrun("reclaim", projH, "--apply", "--stop", "--json")
    d = J(r)
    ck(r.returncode == 0 and d.get("applied") and d.get("stopped")
       and open_there() == [],
       "reclaim applied after ending the idle session "
       f"({d.get('error') or d.get('blockers') or d.get('unparsed') or 'ok'})")
    ck(Path(projH, "a.txt").read_text() == "a2 from the box\n"
       and Path(projH, "new.txt").is_file()
       and not Path(projH, "sub/b.txt").exists()
       and Path(projH, "d.txt").read_text() == "d2 here only\n",
       "changes made there arrived; what changed only here stayed")
    both = [p.name for p in Path(projH).glob("c (from *).txt")]
    ck(Path(projH, "c.txt").read_text() == "c2 HERE\n" and len(both) == 1
       and Path(projH, both[0]).read_text() == "c2 THERE\n",
       "changed on both sides: both versions are kept")
    aside = Path(d.get("set_aside") or "/nonexistent")
    ck((aside / "project" / "a.txt").is_file()
       and (aside / "project" / "a.txt").read_text() == "a1\n"
       and (aside / "project" / "sub" / "b.txt").is_file(),
       "SAFETY (3): what was replaced or removed is set aside, not lost")
    ck((hstore / "s1.jsonl").read_text() == T1 and (hstore / "s2.jsonl").is_file(),
       "the transcript came back continued, new sessions with it")
    ck(Path(projH, "Icon\r").exists() and Path(projH, "node_modules/pkg/x.js").exists(),
       "what never travelled is untouched")
    ck(project_row(projH)["away"] is None, "the project is no longer away")
    told, again = hook(projH), hook(projH)
    ck("is back on" in told and bool(both) and both[0] in told and again.strip() == "",
       "the next session here is told once what came back")

    # SAFETY (2): a transcript that is not a continuation never replaces ours
    d = J(hrun("handover", projH, "--apply", "--no-start", "--json"))
    ck(d.get("applied") and "started" not in d,
       "a second handover, transfer only "
       f"({d.get('error') or d.get('blockers') or d.get('unparsed') or 'ok'})")
    time.sleep(1.1)
    (rstore / "s1.jsonl").write_text("REWRITTEN" + T1[9:] + "more\n")
    d = J(hrun("reclaim", projH, "--apply", "--json"))
    odd = list(hstore.glob("s1.jsonl.aht-conflict-*"))
    ck(d.get("applied") and (hstore / "s1.jsonl").read_text() == T1 and len(odd) == 1
       and odd[0].read_text().startswith("REWRITTEN"),
       "a rewritten transcript is kept aside; ours stays as it was "
       f"({d.get('error') or d.get('blockers') or d.get('unparsed') or d.get('plan')}, "
       f"{[p.name for p in hstore.iterdir()]})")

    # mirror: the warm copy
    projM = os.path.realpath(str(roots / "mirrored"))
    os.makedirs(projM)
    Path(projM, "keep.txt").write_text("k\n")
    Path(projM, "gone.txt").write_text("g\n")
    r = hrun("mirror", projM, "--on", "--run", "--json")
    rm = str(box) + projM
    ck(J(r).get("mirrored", [{}])[0].get("status") == "synced"
       and Path(rm, "gone.txt").is_file(), "mirror: the copy over there is made")
    Path(projM, "gone.txt").unlink()
    Path(projM, "keep.txt").write_text("k2\n")
    hrun("mirror", "--run", "--json")
    kept = list((bhome / ".aht" / "remote" / "replaced").rglob("gone.txt"))
    ck(Path(rm, "keep.txt").read_text() == "k2\n" and not Path(rm, "gone.txt").exists()
       and len(kept) == 1,
       "mirror: it follows changes; what it removes there is set aside")
    ck(J(hrun("mirror", "--run", "--due", "--json")).get("mirrored") == [],
       "mirror: nothing is due right after a sync")
    os.makedirs(rm + "/busy")
    other = subprocess.Popen(["sleep", "600"], cwd=rm + "/busy")
    rows = J(hrun("mirror", "--run", "--json")).get("mirrored", [{}])
    ck(rows[0].get("status") == "skipped",
       "mirror: it stays out while something runs in the copy")
    other.kill(); other.wait()
    hook(projM)
    ck(project_row(projM)["mirror"] == "box", "the mirror setting survives the hook")

    # the history must stay readable where it returns to
    newer = stubs / "claude-newer"
    newer.write_text('#!/bin/sh\necho "9.9.10 (Claude Code)"\n')
    newer.chmod(0o755)
    J(hrun("handover", projH, "--apply", "--no-start", "--json"))
    time.sleep(1.1)
    Path(rproj, "a.txt").write_text("a3\n")
    r = run("reclaim", projH, "--apply", "--json",
            extra_env=dict(henv, AHT_REMOTE_CLAUDE=str(newer)))
    d = J(r)
    ck(r.returncode == 3 and not d.get("applied")
       and any("9.9.10" in b and "update" in b for b in d.get("blockers", []))
       and Path(projH, "a.txt").read_text() != "a3\n",
       "a newer agent CLI over there blocks the way back")
    now = (rstore / "s1.jsonl").read_text()
    (rstore / "s1.jsonl").write_text(now + json.dumps(
        {"type": "user", "version": "9.10.0", "message": {"content": "later"}}) + "\n")
    d = J(hrun("reclaim", projH, "--apply", "--json"))
    ck(not d.get("applied") and d.get("claude", {}).get("wrote_the_history") == "9.10.0"
       and any("9.10.0" in b for b in d.get("blockers", [])),
       "so does a history that a newer version wrote into")
    d = J(hrun("reclaim", projH, "--apply", "--ignore-version", "--json"))
    ck(d.get("applied") and any("9.10.0" in w for w in d.get("warnings", []))
       and Path(projH, "a.txt").read_text() == "a3\n",
       "--ignore-version takes it back anyway, with a warning")


def own_checks_more(h):
    """The rest of handover_suite's own checks ([16]): which session goes on,
    --status-file, the project list, a path listed twice, several machines,
    discover, backups there, --task, the board, the night shift, mirror --all."""
    box, bhome, stubs, henv, hrun, J, hook, project_row, open_there = (
        h.box, h.bhome, h.stubs, h.henv, h.hrun, h.J, h.hook, h.project_row, h.open_there)
    # what the checks before these left (own_checks): the project handed over
    # and back ("Hand Over", with its Claude history), the folder of the open
    # sessions' records, the project kept in sync with box
    projH = os.path.realpath(str(roots / "Hand Over"))
    os.makedirs(projH + "/sub")
    os.makedirs(projH + "/node_modules/pkg")
    nfd = unicodedata.normalize("NFD", "Stürmer.txt")
    for rel, body in (("a.txt", "a1\n"), ("sub/b.txt", "b1\n"), ("c.txt", "c1\n"),
                      ("d.txt", "d1\n"), (nfd, "umlaut\n"), ("Icon\r", ""),
                      ("node_modules/pkg/x.js", "x\n")):
        Path(projH, rel).write_text(body)
    hstore = tools / "claude" / enc(projH)
    (hstore / "memory").mkdir(parents=True)
    (hstore / "memory" / "MEMORY.md").write_text("- note\n")
    outside = str(Path.home() / "elsewhere" / "notes.md")
    if outside.startswith(("/tmp/", "/private/", "/var/")):
        # a throwaway HOME there: aht counts such a path as a temporary file
        # and leaves it out, so the file stands somewhere aht does not
        outside = "/srv/elsewhere/notes.md"
    T0 = "".join(json.dumps(e) + "\n" for e in (
        {"type": "user", "cwd": projH, "version": "9.9.9",
         "message": {"role": "user", "content": "first question"}},
        {"type": "user", "isCompactSummary": True,
         "message": {"role": "user", "content": "SUMMARY: the parser is half done"}},
        {"type": "ai-title", "aiTitle": "Parser work"},
        {"type": "user", "message": {"role": "user", "content": "now fix the lexer"}},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "The lexer is fixed."},
            {"type": "tool_use", "name": "Edit", "input": {"file_path": projH + "/a.txt"}},
            {"type": "tool_use", "name": "Read", "input": {"file_path": outside}},
            {"type": "tool_use", "name": "TodoWrite", "input": {"todos": [
                {"content": "write the tests", "status": "pending"},
                {"content": "publish it", "status": "completed"}]}}]}}))
    (hstore / "s1.jsonl").write_text(T0)
    (sb / ".claude.json").write_text(json.dumps(
        {"projects": {projH: {"hasTrustDialogAccepted": True}}}))
    hrun("tag", projH, "--apply")
    sess_dir = tools / "sessions"
    sess_dir.mkdir(exist_ok=True)
    # mirror: the warm copy
    projM = os.path.realpath(str(roots / "mirrored"))
    os.makedirs(projM)
    Path(projM, "keep.txt").write_text("k\n")
    Path(projM, "gone.txt").write_text("g\n")
    r = hrun("mirror", projM, "--on", "--run", "--json")
    Path(projM, "gone.txt").unlink()
    Path(projM, "keep.txt").write_text("k2\n")
    hrun("mirror", "--run", "--json")

    # which session goes on: the one used last, as `claude --continue` picks
    projS = os.path.realpath(str(roots / "sessions"))
    os.makedirs(projS)
    Path(projS, "f.txt").write_text("f\n")
    sstore = tools / "claude" / enc(projS)
    sstore.mkdir()
    def transcript(name, entry, *prompts, title=None, where=sstore, age=0):
        rows = [{"type": "user", "entrypoint": entry, "cwd": projS,
                 "message": {"role": "user", "content": p}} for p in prompts]
        if title:
            rows.append({"type": "ai-title", "aiTitle": title})
        f = Path(where) / f"{name}.jsonl"
        f.write_text("".join(json.dumps(r) + "\n" for r in rows))
        stamp = time.time() - age
        os.utime(f, (stamp, stamp))
    transcript("main", "cli", "the real work", title="Main thread", age=300)
    transcript("cron", "sdk-cli", "a nightly scripted run", age=200)
    transcript("loop", "cli", "/loop check the build", age=100)
    ck(core._sessions_of(sstore)[0] == "loop" and core.latest_session(sstore) == "main",
       "scripted runs and /loop sessions are passed over, however recent")
    hrun("tag", projS, "--apply")
    d = J(hrun("handover", projS, "--apply", "--no-start", "--json"))
    ck(d.get("applied") and d.get("session") == "main" and d.get("sessions") == 3,
       "handover goes on with the session last worked in")
    rs = bhome / ".claude" / "projects" / enc(str(box) + projS)
    time.sleep(1.1)
    transcript("main", "cli", "the real work", "a bit more there", title="Main thread",
               where=rs, age=50)
    transcript("branch", "cli", "the real work", "a bit more there", "after the branch",
               title="Main thread (branch)", where=rs)
    d = J(hrun("reclaim", projS, "--apply", "--json"))
    ck(d.get("applied") and d.get("session") == "branch"
       and d.get("session_title") == "Main thread (branch)"
       and d.get("handed_over_session") == "main"
       and d.get("handed_over_title") == "Main thread",
       "back from a branch made there: the branch goes on, the sent one is named")
    r1 = hrun("resume-here", projS, "--print").stdout
    r2 = hrun("resume-here", projS, "--handed-over", "--print").stdout
    ck("--resume branch" in r1 and "--resume main" in r2,
       "resume-here opens the latest; --handed-over the one that was sent")
    # what the file says while the handover runs (a spy notes each write);
    # once the command ends, the file is gone
    sf, seen_f = sb / "stage.json", sb / "stages-seen.json"
    spy = ("import atexit, json, os, sys; sys.path.insert(0, sys.argv[1]); import aht\n"
           "seen, w = [], aht.Progress._write\n"
           "def spy(self, force=False):\n"
           "    w(self, force)\n"
           "    try:\n"
           "        seen.append(json.loads(open(self.path).read()))\n"
           "    except (OSError, ValueError, TypeError):\n"
           "        pass\n"
           "aht.Progress._write = spy\n"
           "atexit.register(lambda: open(os.environ['SPY_OUT'], 'w').write(json.dumps(seen)))\n"
           "sys.exit(aht.main(sys.argv[2:]))\n")
    d = J(subprocess.run([PY, "-c", spy, str(HERE.parent), "handover", projM, "--apply",
                          "--no-start", "--json", "--status-file", str(sf)],
                         env=dict(env, **henv, SPY_OUT=str(seen_f)), capture_output=True,
                         text=True))
    stages = json.loads(seen_f.read_text()) if seen_f.is_file() else []
    ck(d.get("applied") and any("sending" in x.get("stage", "") and "percent" in x
                                for x in stages) and not sf.exists(),
       f"--status-file tells a front-end where the transfer stands, and goes when it ends "
       f"({[x.get('stage') for x in stages][:6]}, {sf.exists()})")
    d = J(hrun("reclaim", projM, "--apply", "--json"))
    ck(d.get("applied") and d.get("handed_over_session") is None,
       "no second session is offered when the work stayed in the one sent")
    row = project_row(projM)
    ck(row["mirror"] == "box" and row["mirror_synced_at"] and row["away_since"] is None,
       "the project list tells when a project was synced last")
    sitter = subprocess.Popen(["sleep", "600"], cwd="/")
    (tools / "sessions" / f"{sitter.pid}.json").write_text(json.dumps(
        {"pid": sitter.pid, "cwd": projM, "status": "busy"}))
    ck(project_row(projM)["open"] == "working" and project_row(projS)["open"] is None
       and project_row(projH)["agents"] == ["claude"],
       "the project list tells where an agent session is open")
    sitter.kill(); sitter.wait()

    # a path the registry lists twice: the folder's own marker decides
    regf = sb / ".aht" / "registry.json"
    reg = json.loads(regf.read_text())
    mine = next(u for u, e in reg["projects"].items() if e["real_path"] == projS)
    reg["projects"] = {"0" * 32: {"real_path": projS, "stores": {},
                                  "updated_at": "2020-01-01T00:00:00"},
                       **reg["projects"]}
    regf.write_text(json.dumps(reg))
    d = J(hrun("handover", projS, "--apply", "--no-start", "--json"))
    reg = json.loads(regf.read_text())
    ck(d.get("applied") and reg["projects"][mine].get("away")
       and not reg["projects"]["0" * 32].get("away"),
       "a path listed twice: the entry the folder's marker names is used")
    J(hrun("reclaim", projS, "--apply", "--json"))
    dr = J(hrun("doctor", "--json"))
    twice = next(c for c in dr["checks"] if c["check"] == "no folder is listed twice")
    d = J(hrun("prune", "--json"))
    ck(not twice["ok"] and [x["uuid"] for x in d["doubles"]] == ["0" * 32]
       and d["doubles"][0]["owner"] == mine,
       "doctor and prune name the stale one of two entries for a folder")
    d = J(hrun("prune", "--apply", "--json"))
    reg = json.loads(regf.read_text())
    ck("0" * 32 not in reg["projects"] and mine in reg["projects"]
       and read_text_or_none(Path(projS) / ".aht" / ".project-id") == mine,
       "prune drops it; the folder's own entry and its marker stay")

    # any number of machines
    box2 = Path(os.path.realpath(sb)) / "box2"
    (box2 / "home" / ".claude").mkdir(parents=True)
    hrun("config", "--set", "remotes=" + json.dumps(
        {"box": {"root": str(box)}, "box2": {"root": str(box2)}}))
    ck(J(hrun("status", "--json"))["handover"]["default_remote"] == "box"
       and sorted(J(hrun("remote", "list", "--json"))["remotes"]) == ["box", "box2"],
       "several machines; the first one stays the default")
    d = J(hrun("handover", projM, "--to", "box2", "--apply", "--no-start", "--json"))
    ck(d.get("applied") and Path(str(box2) + projM, "keep.txt").is_file()
       and project_row(projM)["away_remote"] == "box2",
       "--to hands a project to the machine named")
    r = hrun("remote", "remove", "box2")
    ck(r.returncode == 3 and "box2" in J(hrun("remote", "list", "--json"))["remotes"],
       "a machine that holds a project cannot be removed")
    d = J(hrun("reclaim", projM, "--apply", "--json"))
    r = hrun("remote", "remove", "box2")
    ck(d.get("applied") and r.returncode == 0
       and sorted(J(hrun("remote", "list", "--json"))["remotes"]) == ["box"],
       "once the project is back it can")
    ts = stubs / "tailscale"
    ts.write_text("#!/bin/sh\ncat <<'JSON'\n" + json.dumps({"Peer": {
        "a": {"HostName": "x", "DNSName": "homebox.net.ts.net.", "OS": "linux",
              "Online": True},
        "b": {"HostName": "phone", "DNSName": "phone.net.ts.net.", "OS": "iOS",
              "Online": True},
        "c": {"HostName": "old", "DNSName": "attic.net.ts.net.", "OS": "macOS",
              "Online": False}}}) + "\nJSON\n")
    ts.chmod(0o755)
    found = J(run("remote", "discover", "--json",
                  extra_env=dict(henv, AHT_TAILSCALE=str(ts)))).get("machines", [])
    names = [m["name"] for m in found if m["via"] == "tailscale"]
    ck(names == ["homebox", "attic"],
       f"discover: computers of the network, reachable ones first, no phones ({names})")
    ts.write_text("#!/bin/sh\necho 'Tailscale is stopped.' >&2\nexit 1\n")
    before = run("logs", "--errors", "-n", "400").stdout.count("discover")
    for _ in range(3):
        d = J(run("remote", "discover", "--json",
                  extra_env=dict(henv, AHT_TAILSCALE=str(ts))))
    after = run("logs", "--errors", "-n", "400").stdout.count("discover")
    ck(not [m for m in d.get("machines", []) if m["via"] == "tailscale"]
       and any("Tailscale is stopped" in n for n in d.get("notes", []))
       and after == before,
       "discover: a stopped Tailscale is told to the asker, not written to the log")

    # the history backups kept on the other machine too
    hrun("config", "--set", "offsite_backup=box")
    bdir = sb / ".aht" / "backups" / "u1"
    bdir.mkdir(parents=True, exist_ok=True)
    (bdir / "20260101-000000.zip").write_bytes(b"zip")
    d = J(hrun("backup", "--offsite", "--json"))
    copies = list((bhome / ".aht" / "offsite").rglob("20260101-000000.zip"))
    ck(d.get("machine") == "box" and len(copies) == 1,
       f"backups are copied to the other machine ({d})")
    (bdir / "20260101-000000.zip").unlink()
    d = J(hrun("backup", "--fetch-offsite", "--json"))
    ck((bdir / "20260101-000000.zip").read_bytes() == b"zip",
       "…and fetched back from it on a new Mac")
    hrun("config", "--unset", "offsite_backup")

    # hand over with a task: the session starts on it at once
    d = J(hrun("handover", projM, "--apply", "--json",
               "--task", "-- run the benchmark overnight"))
    win = (d.get("away") or {}).get("window", "?")
    wfile = bhome / ".faketmux" / f"{win}.json"
    line = json.loads(wfile.read_text())["command"] if wfile.is_file() else ""
    brief = sorted(Path(projM, ".aht", "handover").glob("*-to-*.md"))
    ck(d.get("applied") and "-- '-- run the benchmark overnight'" in line
       and "run the benchmark overnight" in brief[-1].read_text()
       and project_row(projM)["away"],
       "--task: the resumed session starts on it; the summary records it")
    boards = J(hrun("board", "--json")).get("machines", [])
    there = next((b for b in boards if b["machine"] == "box"), {})
    row = next((s for s in there.get("sessions", []) if s.get("project") == str(box) + projM), {})
    ck(there.get("reachable") and row.get("status") == "idle",
       f"board: the other machine's open sessions are listed ({there.get('error') or row})")
    J(hrun("reclaim", projM, "--apply", "--stop", "--json"))

    # the night shift: a handover with a task on a timer, and back again
    jobs_file = sb / ".aht" / "night-shift.json"
    r = hrun("night-shift", projM, "--task", "tidy the logs", "--to", "box", "--apply")
    ck(r.returncode == 3 and "tokens" in r.stdout and not jobs_file.exists(),
       "night shift: off until turned on, because it uses tokens")
    hrun("config", "--set", "night_shift=true")
    def job_state(want, secs=90):
        for _ in range(secs * 4):
            j = json.loads(jobs_file.read_text())[-1]
            if j["state"] == want:
                break
            time.sleep(0.25)
        return j
    d = J(hrun("night-shift", projM, "--task", "tidy the logs", "--to", "box",
               "--back", "07:00", "--apply", "--json"))
    j = job_state("started")
    ck(d.get("applied") and j["state"] == "started" and project_row(projM)["away"],
       f"night shift: handed over with the task when it starts ({j.get('log')})")
    jobs = json.loads(jobs_file.read_text())
    jobs[-1]["back_at"] = time.time() - 1
    jobs_file.write_text(json.dumps(jobs))
    hrun("notices")
    j = job_state("back")
    ck(j["state"] == "back" and not project_row(projM)["away"],
       f"night shift: taken back when it ends ({j.get('log')})")
    hrun("config", "--unset", "night_shift")

    # every project in sync with one machine at once
    d = J(hrun("mirror", "--all", "--on", "--to", "box", "--json"))
    names = [r["project"] for r in d.get("projects", [])]
    ck(names and d.get("bytes", 0) > 0 and not d.get("applied")
       and not any(n != m and n.startswith(m + "/") for n in names for m in names),
       f"mirror --all: every project, sizes added up, nested ones carried by their parent ({len(names)})")
    J(hrun("mirror", "--all", "--on", "--to", "box", "--apply", "--json"))
    rows = J(hrun("projects", "--json"))["projects"]
    ck(all(r["mirror"] == "box" for r in rows if r["real_path"] in names),
       "mirror --all --apply: each of them is kept in sync")
    J(hrun("mirror", "--all", "--off", "--apply", "--json"))
    rows = J(hrun("projects", "--json"))["projects"]
    ck(not [r for r in rows if r["mirror"]], "mirror --all --off: none any more")


def phase1_unfinished(box, bhome, stubs, henv, hrun, J, hook, project_row):
    """phase1_suite, the part that compares the JSON with the front-ends' samples:
    an unfinished handover is finished or undone, Release (with Keep in sync
    on, too), offsite backups that only add, a machine that does not answer
    (the rest is phase1_far_end)."""
    import shlex
    regf = sb / ".aht" / "registry.json"
    nlog = sb / "notices-phase1.log"
    nev = dict(henv, AHT_NOTIFY_LOG=str(nlog), AHT_NO_SEARCH_INDEX="1",
               AHT_ITERM_TABS=str(sb / "no-tabs.json"))
    (sb / "no-tabs.json").write_text("{}")
    def nrun(*a, **extra):
        return run(*a, extra_env=dict(nev, **extra))
    def entry(path):
        reg = json.loads(regf.read_text())
        return next((u, e) for u, e in reg["projects"].items() if e["real_path"] == path)
    def set_handing(uid, h):
        reg = json.loads(regf.read_text())
        reg["projects"][uid].pop("away", None)
        reg["projects"][uid]["handing"] = h
        regf.write_text(json.dumps(reg))
    def told():
        return [json.loads(l) for l in nlog.read_text().splitlines()] if nlog.is_file() else []
    fixture_misses = []
    # what the parts of phase1_suite in phase1_far_end left: the stand-in ssh
    # (the machine that does not answer below is asked through it), and the
    # project "Went On" (tagged, with its conversation; the cut-off checks
    # handed it over and back)
    far = Path(os.path.realpath(sb)) / "f"
    farbin = far / "bin"
    farbin.mkdir(parents=True)
    sshbin = sb / "sshbin"
    sshbin.mkdir()
    (sshbin / "ssh").write_text(f'#!/bin/sh\nexec "{PY}" "{HERE / "fake_ssh.py"}" "$@"\n')
    (sshbin / "ssh").chmod(0o755)
    sev = dict(nev, PATH=str(sshbin) + os.pathsep + env["PATH"], FAKE_SSH_DIR=str(far))
    sev.pop("AHT_REMOTE_PATH", None)
    def srun(*a, **extra):
        return run(*a, extra_env=dict(sev, **extra))
    projW = os.path.realpath(str(roots / "Went On"))
    os.makedirs(projW)
    Path(projW, "w.txt").write_text("w\n")
    wstore = tools / "claude" / enc(projW)
    wstore.mkdir()
    (wstore / "w1.jsonl").write_text(json.dumps(
        {"type": "user", "cwd": projW, "message": {"content": "start the work"}}) + "\n")
    hrun("tag", projW, "--apply")
    farW = bhome / ".claude" / "projects" / enc(str(box) + projW) / "w1.jsonl"
    def went_on(line):
        with open(farW, "a") as fh:
            fh.write(json.dumps({"type": "assistant", "message": {"content": line}}) + "\n")

    hrun("config", "--set", "remotes=" + json.dumps({"box": {"root": str(box)}}))
    st = J(hrun("status", "--json"))
    fixture_misses += fixture_ok({"handover": st.get("handover")}, "status_handover.json")
    ck(st.get("handover", {}).get("can_reach") is True
       and st.get("handover", {}).get("supported") is True,
       "status: can_reach (an ssh client is here) next to supported")

    projD = os.path.realpath(str(roots / "Dropped Link"))
    os.makedirs(projD)
    Path(projD, "f.txt").write_text("f\n")
    hrun("tag", projD, "--apply")
    uidD = entry(projD)[0]
    mf = sb / ".aht" / "handover" / uidD / "manifest.json"

    # the probe: what the far end speaks; test mode runs the core itself, no sh
    rem = core.Remote("box", {"root": str(box)})
    real_sh = core.Remote.sh
    def no_sh(*a, **k):
        raise AssertionError("sh was used")
    core.Remote.sh = no_sh
    try:
        info = rem.connect(projD)
        ro = sb / "read-only"
        (Path(str(box) + str(ro))).mkdir(parents=True)
        os.chmod(str(box) + str(ro), 0o555)
        ro_info = rem.connect(str(ro / "sub"))
        os.chmod(str(box) + str(ro), 0o755)
    finally:
        core.Remote.sh = real_sh
    cid = hashlib.sha256(Path(CLI).read_bytes()).hexdigest()[:12]
    ck(info.get("protocol") == core.AGENT_PROTOCOL == 3
       and {"probe", "offsite-list", "offsite-prune",
            "offsite-adopt"} | set(core.PC_OPS) <= set(info.get("ops") or [])
       and info.get("core_id") == cid and info.get("machine_id") is None
       and info.get("free_bytes", 0) > 0 and info.get("path_writable") is True
       and (ro_info.get("path_writable") is False or os.getuid() == 0),
       "probe: protocol 3 and its ops, the core's id, no machine id made there, free "
       "space and a write that was tried; test mode runs no sh")

    # the link drops after each step: the handover ends finished or not
    # finished, never with a lost record
    for op in ("prepare", "manifest"):
        d = J(nrun("handover", projD, "--apply", "--no-start", "--json", AHT_TEST_DROP=op))
        e = entry(projD)[1]
        ck(not d.get("applied") and "dropped" in (d.get("error") or "")
           and any("did not finish" in w for w in d.get("warnings", []))
           and not e.get("handing") and not e.get("away") and not mf.exists(),
           f"the link drops after “{op}”: the handover did not finish, the project stays "
           f"here ({d.get('error')})")
    d = J(nrun("handover", projD, "--apply", "--json", AHT_TEST_DROP="start"))
    e = entry(projD)[1]
    row = project_row(projD)
    fixture_misses += fixture_ok(row, "projects_handing.json")
    ck(not d.get("applied") and (e.get("handing") or {}).get("step") == "starting"
       and not e.get("away") and (row.get("handing") or {}).get("state") == "checking"
       and json.loads(mf.read_text()).get("attempt") == e["handing"]["attempt"],
       f"the link drops after “start”: not known yet, the record stays ({row.get('handing')})")
    d = J(nrun("notices", "--json"))
    e = entry(projD)[1]
    fixture_misses += fixture_ok(d, "notices_handover.json")
    ck(e.get("away") and not e.get("handing") and e["away"].get("attempt")
       == json.loads(mf.read_text()).get("attempt") and e["away"].get("v") == 2
       and any("finished: the session there runs" in n["message"]
               for n in d.get("notices", []))
       and any("finished" in n["message"] for n in told()),
       f"…the next check finds the session there: it is handed over ({d.get('notices')})")
    J(hrun("reclaim", projD, "--apply", "--stop", "--json"))

    # cut off without a word (this machine slept): a young record waits, and
    # so does one whose project a transfer holds; then it is undone
    h = {"v": 2, "attempt": "20260101-000000-abcd", "remote": "box", "host": "box",
         "path": projD, "since": core._now(), "driven_by": "here", "agent": "claude",
         "session": None, "window": "aht-x", "mux": "tmux", "step": "sending",
         "at": time.time()}
    set_handing(uidD, h)
    nrun("notices")
    young = entry(projD)[1].get("handing")
    meanwhile = hook(projD)
    set_handing(uidD, dict(h, at=time.time() - 300))
    with core.ProjectLock(uidD):
        nrun("notices")
        held = entry(projD)[1].get("handing")
        busy = (project_row(projD).get("handing") or {}).get("state")
    d = J(nrun("notices", "--json"))
    e = entry(projD)[1]
    ck(young and held and busy == "running" and not e.get("handing") and not e.get("away")
       and "did not finish" in meanwhile and "WARNING" in meanwhile
       and any(n["message"] == "The handover of Dropped Link to box did not finish. The "
               "project stays here; nothing runs there" for n in d.get("notices", [])),
       f"cut off: waits while young or busy, then did not finish ({d.get('notices')})")

    # recorded, and the copy there was worked on: it counts as handed over
    J(hrun("handover", projD, "--apply", "--no-start", "--json"))
    away = entry(projD)[1]["away"]
    set_handing(uidD, dict(away, step="recorded", at=time.time() - 300, error="gone"))
    time.sleep(1.1)
    Path(str(box) + projD, "f.txt").write_text("worked on there\n")
    d = J(nrun("notices", "--json"))
    e = entry(projD)[1]
    ck(e.get("away") and any("the copy there was worked on" in n["message"]
                             for n in d.get("notices", [])),
       f"…a copy worked on there counts as handed over ({d.get('notices')})")

    # Take Back refuses a record of what left from another attempt
    m = json.loads(mf.read_text())
    mf.write_text(json.dumps(dict(m, attempt="19990101-000000-dead")))
    d = J(hrun("reclaim", projD, "--apply", "--json"))
    ck(not d.get("applied") and "another handover attempt" in (d.get("error") or "")
       and entry(projD)[1].get("away") and Path(projD, "f.txt").read_text() == "f\n",
       f"an attempt that does not match is refused ({d.get('error')})")
    mf.write_text(json.dumps(m))

    # Release: the work there stays there; a dry run says so first
    Path(str(box) + projD, "g.txt").write_text("new there\n")
    d = J(hrun("reclaim", projD, "--release", "--json"))
    fixture_misses += fixture_ok(d, "reclaim_release_dry.json")
    ck(d.get("released") is False and d.get("would_lose") == {"files": 2, "history": 0,
                                                              "since": away["since"]}
       and d.get("pauses_sync") is None and entry(projD)[1].get("away"),
       f"Release, dry run: what stays there ({d.get('would_lose')})")
    r = hrun("remote", "remove", "box")
    ck(r.returncode == 3 and f"aht reclaim {shlex.quote(projD)} --release" in r.stderr,
       "a machine that holds a project points to Release")
    d = J(hrun("reclaim", projD, "--release", "--apply", "--json"))
    fixture_misses += fixture_ok(d, "reclaim_release_apply.json")
    e = entry(projD)[1]
    ck(d.get("released") is True and not e.get("away")
       and (e.get("returned") or {}).get("released") is True
       and Path(projD, "f.txt").read_text() == "f\n"
       and Path(str(box) + projD, "g.txt").is_file() and not mf.exists(),
       "Release: the files here stay as they are, the copy there is left alone")
    note = hook(projD)
    ck("released" in note and "did not come here" in note and hook(projD).strip() == "",
       "the next session here is told once that it was released")

    # what --include carries travels with the record: a handover finished
    # after the link dropped brings it back at Take Back too
    xhome = Path(os.path.realpath(sb)) / "xhome"    # only what is in HOME can travel
    extra = xhome / "notes"
    extra.mkdir(parents=True)
    (extra / "n.txt").write_text("n1\n")
    J(nrun("handover", projW, "--apply", "--include", str(extra), "--json",
           AHT_TEST_DROP="start", HOME=str(xhome)))
    h = entry(projW)[1].get("handing") or {}
    J(nrun("notices", "--json"))
    e = entry(projW)[1]
    Path(str(box) + str(extra), "n.txt").write_text("n2, written there\n")
    d = J(nrun("reclaim", projW, "--apply", "--stop", "--json", HOME=str(xhome)))
    back = entry(projW)[1].get("returned") or {}     # the machine, never a folder
    ck(h.get("extras") == [str(extra)] and e.get("extras") == [str(extra)]
       and "extras" not in (e.get("away") or {}) and d.get("applied")
       and (extra / "n.txt").read_text() == "n2, written there\n"
       and back.get("from") == ((e.get("away") or {}).get("host") or "box"),
       f"--include, and the link drops at the start: Take Back brings the folder back, "
       f"and names the machine it came from ({h.get('extras')}, {e.get('extras')}, "
       f"from {back.get('from')!r}, {d.get('error') or d.get('blockers')})")

    # Release while Keep in sync is on: what stays there is named (files and
    # the conversation), and the sync pauses, so the next one does not send
    # this copy over the work left there
    hrun("mirror", projW, "--on", "--to", "box")
    J(hrun("handover", projW, "--apply", "--no-start", "--json"))
    since = entry(projW)[1]["away"]["since"]
    Path(str(box) + projW, "w.txt").write_text("changed there\n")
    went_on("and on")
    (bhome / ".claude" / "file-history" / "w1").mkdir(parents=True, exist_ok=True)
    (bhome / ".claude" / "file-history" / "w1" / "w@v1").write_text("w\n")
    d = J(hrun("reclaim", projW, "--release", "--json"))
    r = hrun("reclaim", projW, "--release")
    ck(d.get("would_lose") == {"files": 1, "history": 2, "since": since}
       and d.get("pauses_sync") == "box"
       and "What stays there: 1 file and the conversation." in r.stdout
       and "Keep in sync with box will be paused, so the copy there stays as it is."
       in r.stdout and "is paused" not in r.stdout,
       f"Release, dry run: the file and the conversation that stay there, and the sync "
       f"that will pause ({d.get('would_lose')}, {d.get('pauses_sync')})")
    d = J(hrun("reclaim", projW, "--release", "--apply", "--json"))
    row = project_row(projW)
    fixture_misses += fixture_ok(row, "projects_mirror_paused.json")
    J(hrun("mirror", "--run", "--due", "--json"))
    ck(d.get("released") and d.get("pauses_sync") == "box" and row.get("mirror") == "box"
       and (row.get("mirror_paused") or {}).get("reason") == "released"
       and row["mirror_paused"].get("remote") == "box" and row["mirror_paused"].get("at")
       and Path(str(box) + projW, "w.txt").read_text() == "changed there\n",
       f"Release pauses Keep in sync with that machine: the next sync leaves the copy "
       f"there as it is ({row.get('mirror_paused')})")
    # turned on again, the sync looks first: the work Release left there
    # (a file and the conversation) pauses it; Replace Them sends this copy
    # over it, with theirs set aside there
    hrun("mirror", projW, "--on", "--to", "box")
    rows = J(hrun("mirror", "--run", "--due", "--json")).get("mirrored") or [{}]
    p = project_row(projW).get("mirror_paused") or {}
    ck(rows[0].get("status") == "paused" and p.get("reason") == "changed"
       and p.get("files") == ["w.txt"] and p.get("history") == 1
       and Path(str(box) + projW, "w.txt").read_text() == "changed there\n",
       f"…turned on again, the sync finds the work left there and pauses ({p})")
    d = J(hrun("mirror", projW, "--replace", "--apply", "--json"))
    kept = list((bhome / ".aht" / "remote" / "replaced" / entry(projW)[0]).rglob("w.txt"))
    ck(d.get("applied") and project_row(projW).get("mirror_paused") is None
       and Path(str(box) + projW, "w.txt").read_text() == "w\n"
       and any(k.read_text() == "changed there\n" for k in kept),
       f"…Replace Them sends this copy, theirs set aside there ({d.get('mirrored')})")
    # …or until a handover to that machine sends this copy over the one the
    # release left there (set aside there first): the pause ends with it, so
    # once the project is back the sync goes on
    J(hrun("handover", projW, "--apply", "--no-start", "--json"))
    Path(str(box) + projW, "w.txt").write_text("changed there again\n")
    J(hrun("reclaim", projW, "--release", "--apply", "--json"))
    paused_again = project_row(projW).get("mirror_paused")
    blocked = J(hrun("handover", projW, "--no-start", "--json"))
    ck(any("--replace-there" in b for b in blocked.get("blockers", []))
       and (blocked.get("copy_changed") or {}).get("files") == ["w.txt"],
       f"a handover over the copy Release left (changed there) blocks: Bring Them Here or "
       f"--replace-there ({blocked.get('blockers')})")
    plan = J(hrun("handover", projW, "--no-start", "--replace-there", "--json"))
    d = J(hrun("handover", projW, "--apply", "--no-start", "--replace-there", "--json"))
    row = project_row(projW)
    ck(paused_again and plan.get("ends_pause") == "box"
       and any("the copy that Release left on box is replaced" in w
               for w in plan.get("warnings", []))
       and d.get("applied") and d.get("ends_pause") == "box" and row.get("away_remote") == "box"
       and row.get("mirror") == "box" and row.get("mirror_paused") is None
       and Path(str(box) + projW, "w.txt").read_text() == "w\n",
       f"a handover to the machine Release paused the sync with ends the pause, and its "
       f"dry run says the copy left there is replaced ({plan.get('warnings')}, "
       f"{d.get('ends_pause')}, {row.get('mirror_paused')})")
    J(hrun("reclaim", projW, "--apply", "--json"))
    Path(projW, "w.txt").write_text("w, back here\n")
    J(hrun("mirror", projW, "--run", "--json"))
    ck(project_row(projW).get("mirror_paused") is None
       and Path(str(box) + projW, "w.txt").read_text() == "w, back here\n",
       "…and after Take Back the sync sends this copy there again")
    # a sync run that read the registry before a Release paused it looks
    # again when it sends: the copy there stays as it is
    far = Path(str(box) + projW, "w.txt")
    probe = ("import sys, json; sys.path.insert(0, sys.argv[1]); import aht\n"
             "uid, e = aht._entry_for(aht.load_registry(), sys.argv[2])\n"
             "open(sys.argv[3], 'w').write('left there\\n')\n"
             "aht._update_entry(uid, mirror=dict(e['mirror'], paused={\n"
             "    'reason': 'released', 'at': aht._now(), 'remote': 'box'}))\n"
             "print(json.dumps(aht.mirror_project(uid, e)))\n")
    r = subprocess.run([PY, "-c", probe, str(HERE.parent), projW, str(far)],
                       env=dict(env, **henv), capture_output=True, text=True)
    try:
        got = json.loads(r.stdout)
    except ValueError:
        got = {"error": r.stdout[-300:] + r.stderr[-300:]}
    ck(got.get("status") == "paused" and far.read_text() == "left there\n"
       and project_row(projW).get("mirror_paused"),
       f"Keep in sync: a run that began before a Release does not send over the copy "
       f"left there ({got})")
    hrun("mirror", projW, "--on", "--to", "box")    # on again: the pause ends
    far.write_text("w, back here\n")
    hrun("mirror", projW, "--off")

    # ---- offsite backups: a folder per computer, copying only adds ------------ #
    oev = dict(henv, AHT_MACHINE_NAME="testmac")
    def orun(*a, **extra):
        return run(*a, extra_env=dict(oev, **extra))
    hrun("config", "--set", "offsite_backup=box")
    up = sb / ".aht" / "backups" / "p1"
    up.mkdir(parents=True)
    zs = [f"2026010{i}-000000.zip" for i in range(1, 6)]
    for z in zs:
        (up / z).write_bytes(b"zip " + z.encode())
        (up / z.replace(".zip", ".meta.json")).write_text("{}")
    d = J(orun("backup", "--offsite", "--json"))
    fixture_misses += fixture_ok(d, "backup_offsite.json")
    mid = json.loads((sb / ".aht" / "machine.json").read_text())["id"]
    fold = bhome / ".aht" / "offsite" / mid
    there = fold / "backups" / "p1"
    zips = lambda p: sorted(x.name for x in p.glob("*.zip"))
    ck(d.get("folder") == mid and zips(there) == zs
       and json.loads((fold / "machine.json").read_text()).get("name") == "testmac",
       f"offsite: into a folder named by this computer's id, with machine.json ({d})")
    # copying only adds: a backup there of the same name but another size
    # stays as it is (and is named in "differs")
    (there / zs[0]).write_bytes(b"theirs, another size")
    d = J(orun("backup", "--offsite", "--json"))
    ck((there / zs[0]).read_bytes() == b"theirs, another size"
       and d.get("differs") == ["p1/" + zs[0]] and d.get("files") == 0,
       f"offsite: copying only adds; a backup there of another size stays as it is "
       f"({d.get('differs')})")
    (there / zs[0]).write_bytes(b"zip " + zs[0].encode())
    shutil.rmtree(up)
    d = J(orun("backup", "--offsite", "--json"))
    ck(d.get("removed") == 0 and zips(there) == zs,
       "offsite: no backups here (wiped, or a new computer) removes nothing there")
    up.mkdir()
    (up / zs[-1]).write_bytes(b"zip " + zs[-1].encode())
    d = J(orun("backup", "--offsite", "--json"))
    ck(d.get("removed") == 2 and zips(there) == zs[2:]
       and not (there / zs[0].replace(".zip", ".meta.json")).exists(),
       f"offsite: pruned here, removed there too, but the newest 3 stay ({zips(there)})")

    # a second computer of the same name gets a folder of its own
    h2 = sb / "second" / ".aht"
    (h2 / "backups" / "p2").mkdir(parents=True)
    (h2 / "backups" / "p2" / "20260201-000000.zip").write_bytes(b"the other one")
    (h2 / "config.json").write_text(json.dumps({"remotes": {"box": {"root": str(box)}},
                                                "offsite_backup": "box"}))
    orun("backup", "--offsite", "--json", AHT_HOME=str(h2))
    mid2 = json.loads((h2 / "machine.json").read_text())["id"]
    d = J(orun("backup", "--offsite-list", "--json"))
    fixture_misses += fixture_ok(d, "backup_offsite_list.json")
    rows = {f["id"]: f for f in d.get("folders", [])}
    ck(mid2 != mid and (bhome / ".aht" / "offsite" / mid2 / "backups" / "p2"
                        / "20260201-000000.zip").is_file()
       and zips(there) == zs[2:] and rows.get(mid, {}).get("mine") is True
       and rows.get(mid2, {}).get("mine") is False
       and rows.get(mid2, {}).get("name") == "testmac",
       f"offsite: a second computer of the same name has a folder of its own ({sorted(rows)})")
    r = orun("backup", "--fetch-offsite", "--from", "testmac")
    ck(r.returncode == 1 and "choose one by its id" in r.stderr,
       f"fetch --from a name two computers share asks for the id ({r.stderr.strip()})")
    d = J(orun("backup", "--fetch-offsite", "--from", mid2, "--json"))
    fixture_misses += fixture_ok(d, "backup_fetch_offsite.json")
    fixture_misses += fixture_ok(d, "backup_fetch_offsite.json", FIXTURES6)
    ck((sb / ".aht" / "backups" / "p2" / "20260201-000000.zip").read_bytes()
       == b"the other one" and d.get("from", {}).get("id") == mid2,
       "fetch --from an id brings that computer's backups here")
    shutil.rmtree(sb / ".aht" / "backups" / "p2")

    # an older aht's folder of this name: taken over only when every backup
    # in it is here too (another computer of this name may have made it)
    legacy = bhome / ".aht" / "offsite" / "testmac" / "backups" / "p1"
    legacy.mkdir(parents=True)
    (legacy / "20251201-000000.zip").write_bytes(b"older aht")
    d = J(orun("backup", "--offsite", "--json"))
    lst = J(orun("backup", "--offsite-list", "--json")).get("folders", [])
    ck(d.get("legacy") == ["testmac"] and (legacy / "20251201-000000.zip").is_file()
       and any(f["legacy"] and f["name"] == "testmac" and f["id"] is None for f in lst),
       "offsite: an older aht's folder with a backup this computer lacks is left alone")
    # two computers named testmac keep a folder by id, and the older aht's
    # folder is named testmac too: --from with a folder's name picks that one
    d = J(orun("backup", "--fetch-offsite", "--from=testmac", "--json"))
    ck(d.get("from") == {"id": None, "name": "testmac"}
       and (up / "20251201-000000.zip").read_bytes() == b"older aht",
       f"fetch --from an older aht's folder, named like computers with an id ({d})")
    (up / "20251201-000000.zip").write_bytes(b"older aht")
    d = J(orun("backup", "--offsite", "--json"))
    ck(d.get("adopted") == 1 and not (bhome / ".aht" / "offsite" / "testmac").exists()
       and (there / "20251201-000000.zip").read_bytes() == b"older aht",
       "…and taken over once every backup in it is here too")

    # fetching adds what is missing and never overwrites
    (up / zs[-1]).write_bytes(b"changed here, another size")
    d = J(orun("backup", "--fetch-offsite", "--json"))
    ck((up / zs[-1]).read_bytes() == b"changed here, another size"
       and (up / zs[2]).is_file()
       and (up / zs[-1].replace(".zip", "-from-testmac.zip")).read_bytes()
       == b"zip " + zs[-1].encode(),
       f"fetch: adds what is missing, never overwrites; theirs comes under its own name "
       f"({d.get('renamed')})")

    # the copies made before a rewrite (backups/<id>/rewrites) go there too:
    # only added, never removed there, and fetched back where they are missing
    rw = Path("rewrites") / "claude-20260102-000000" / "-x-proj"
    (up / rw).mkdir(parents=True)
    (up / rw / "s1.jsonl").write_text('{"cwd": "/x/proj"}\n')
    J(orun("backup", "--offsite", "--json"))
    sent_rw = (there / rw / "s1.jsonl").is_file()
    shutil.rmtree(up / "rewrites")
    J(orun("backup", "--offsite", "--json"))
    kept_rw = (there / rw / "s1.jsonl").is_file()
    J(orun("backup", "--fetch-offsite", "--json"))
    ck(sent_rw and kept_rw and (up / rw / "s1.jsonl").read_text() == '{"cwd": "/x/proj"}\n',
       f"offsite: the copies made before a rewrite go there, stay there when they are "
       f"deleted here, and come back with a fetch ({sent_rw}, {kept_rw})")
    # an older aht's folder: one with nothing left in it goes and is not
    # named; one with only such copies is taken over once they are here too
    old_home = bhome / ".aht" / "offsite" / "testmac"
    (old_home / "backups" / "p1").mkdir(parents=True)
    d1 = J(orun("backup", "--offsite", "--json"))
    gone = not old_home.exists()
    old_rw = old_home / "backups" / "p1" / "rewrites" / "claude-20251101-000000"
    old_rw.mkdir(parents=True)
    (old_rw / "a.jsonl").write_text("older aht\n")
    d2 = J(orun("backup", "--offsite", "--json"))
    (up / "rewrites" / "claude-20251101-000000").mkdir(parents=True)
    (up / "rewrites" / "claude-20251101-000000" / "a.jsonl").write_text("older aht\n")
    d3 = J(orun("backup", "--offsite", "--json"))
    ck(d1.get("legacy") == [] and gone and d2.get("legacy") == ["testmac"]
       and d3.get("adopted") == 1 and d3.get("legacy") == [] and not old_home.exists()
       and (there / "rewrites" / "claude-20251101-000000" / "a.jsonl").is_file(),
       f"offsite: an older aht's folder with nothing left goes unnamed; one with only "
       f"rewrites' copies is taken over once they are here too ({d1.get('legacy')}, "
       f"{d2.get('legacy')}, {d3.get('adopted')}, {d3.get('legacy')})")
    hrun("config", "--unset", "offsite_backup")
    shutil.rmtree(up)

    # a machine that does not answer: after an hour Release is offered, once
    h = dict(h, remote="gone", host="gone", at=time.time() - 4000, error="no answer",
             unreachable_since=time.time() - 3700, checked_at=time.time() - 100)
    hrun("config", "--set", "remotes=" + json.dumps(
        {"box": {"root": str(box)}, "gone": {"ssh": "me@127.0.0.9"}}))
    set_handing(uidD, h)
    d1 = J(srun("notices", "--json"))
    fixture_misses += fixture_ok(project_row(projD), "projects_handing_release.json")
    row = project_row(projD).get("handing") or {}
    reg = json.loads(regf.read_text())
    reg["projects"][uidD]["handing"]["checked_at"] = time.time() - 100
    regf.write_text(json.dumps(reg))
    d2 = J(srun("notices", "--json"))
    ck(any("has not answered since" in n["message"] for n in d1.get("notices", []))
       and not d2.get("notices") and row.get("state") == "unreachable"
       and row.get("release") is True,
       f"no answer for an hour: Release is offered once ({row}, {d2.get('notices')})")
    d = J(hrun("reclaim", projD, "--release", "--apply", "--json"))
    ck(d.get("released") and not entry(projD)[1].get("handing"),
       "…and Release drops the unfinished record")
    hrun("config", "--set", "remotes=" + json.dumps({"box": {"root": str(box)}}))
    ck(not fixture_misses, f"the JSON keeps every key of the samples the front-ends "
                           f"use ({fixture_misses})")


def phase1_far_end(box, bhome, stubs, henv, hrun, J, hook, project_row):
    """phase1_suite, the part that compares no JSON with a sample: a handover
    cut off at the start, set-asides there (file-history and plans, a case
    rename, a packed repository, the rule), a sandbox on a real machine, a
    Windows far end (the rest is phase1_unfinished)."""
    import shlex
    regf = sb / ".aht" / "registry.json"
    nlog = sb / "notices-phase1.log"
    nev = dict(henv, AHT_NOTIFY_LOG=str(nlog), AHT_NO_SEARCH_INDEX="1",
               AHT_ITERM_TABS=str(sb / "no-tabs.json"))
    (sb / "no-tabs.json").write_text("{}")
    def nrun(*a, **extra):
        return run(*a, extra_env=dict(nev, **extra))
    def entry(path):
        reg = json.loads(regf.read_text())
        return next((u, e) for u, e in reg["projects"].items() if e["real_path"] == path)
    def set_handing(uid, h):
        reg = json.loads(regf.read_text())
        reg["projects"][uid].pop("away", None)
        reg["projects"][uid]["handing"] = h
        regf.write_text(json.dumps(reg))
    # what the part of phase1_suite in phase1_unfinished left: the far end
    # named "box", and this computer's id (made by its first offsite backup)
    rem = core.Remote("box", {"root": str(box)})
    oev = dict(henv, AHT_MACHINE_NAME="testmac")
    def orun(*a, **extra):
        return run(*a, extra_env=dict(oev, **extra))
    hrun("config", "--set", "offsite_backup=box")
    d = J(orun("backup", "--offsite", "--json"))
    mid = json.loads((sb / ".aht" / "machine.json").read_text())["id"]
    hrun("config", "--unset", "offsite_backup")

    # cut off at the start: the conversation that went on there, or a session
    # that started there and has ended since, counts as handed over; only
    # when nothing at all happened there does the project stay here
    projW = os.path.realpath(str(roots / "Went On"))
    os.makedirs(projW)
    Path(projW, "w.txt").write_text("w\n")
    wstore = tools / "claude" / enc(projW)
    wstore.mkdir()
    (wstore / "w1.jsonl").write_text(json.dumps(
        {"type": "user", "cwd": projW, "message": {"content": "start the work"}}) + "\n")
    hrun("tag", projW, "--apply")
    uidW = entry(projW)[0]
    mfW = sb / ".aht" / "handover" / uidW / "manifest.json"
    farW = bhome / ".claude" / "projects" / enc(str(box) + projW) / "w1.jsonl"
    def went_on(line):
        with open(farW, "a") as fh:
            fh.write(json.dumps({"type": "assistant", "message": {"content": line}}) + "\n")
    def cut_off():
        """Handed over without a session there; then the record says the
        link dropped at the start."""
        J(hrun("handover", projW, "--apply", "--no-start", "--json"))
        set_handing(uidW, dict(entry(projW)[1]["away"], step="starting",
                               at=time.time() - 300, error="gone"))
    cut_off()
    went_on("the work went on there")
    d = J(nrun("notices", "--json"))
    e = entry(projW)[1]
    ck(e.get("away") and not e.get("handing") and mfW.is_file()
       and any("finished: the conversation went on there" in n["message"]
               for n in d.get("notices", [])),
       f"cut off, and only the conversation went on there: it is handed over "
       f"({d.get('notices')})")
    d = J(hrun("reclaim", projW, "--apply", "--json"))
    ck(d.get("applied") and "went on there" in (wstore / "w1.jsonl").read_text(),
       f"…and Take Back brings that conversation here ({d.get('error') or d.get('blockers')})")
    J(nrun("handover", projW, "--apply", "--json", AHT_TEST_DROP="start"))
    h = entry(projW)[1].get("handing") or {}
    subprocess.run([str(stubs / "tmux"), "kill-session", "-t", "=" + str(h.get("window"))],
                   env=dict(env, HOME=str(bhome)), capture_output=True)
    for _ in range(100):                        # the session there ends
        if not core.running_sessions(home=bhome / ".claude"):
            break
        time.sleep(0.1)
    d = J(nrun("notices", "--json"))
    e = entry(projW)[1]
    ck(h.get("step") == "starting" and e.get("away") and not e.get("handing")
       and any("finished: the session there started, and has ended since" in n["message"]
               for n in d.get("notices", [])),
       f"…a session that started there and has ended: handed over ({d.get('notices')})")
    J(hrun("reclaim", projW, "--apply", "--json"))
    cut_off()
    d = J(nrun("notices", "--json"))
    e = entry(projW)[1]
    ck(not e.get("away") and not e.get("handing") and not mfW.exists()
       and any(n["message"] == "The handover of Went On to box did not finish. The project "
               "stays here; nothing runs there" for n in d.get("notices", [])),
       f"…and when nothing at all happened there, it did not finish ({d.get('notices')})")

    # files there that the Claude store keeps beside the transcripts travel
    # with a set-aside too: /rewind's file-history and the plans
    projF = os.path.realpath(str(roots / "Planned"))
    os.makedirs(projF)
    Path(projF, "p.txt").write_text("p\n")
    fstore = tools / "claude" / enc(projF)
    fstore.mkdir()
    (fstore / "fh1.jsonl").write_text(json.dumps(
        {"type": "user", "cwd": projF, "slug": "the-plan",
         "message": {"content": "plan it"}}) + "\n")
    (tools / "file-history" / "fh1").mkdir(parents=True, exist_ok=True)
    (tools / "file-history" / "fh1" / "p@v1").write_text("v1\n")
    (tools / "plans").mkdir(exist_ok=True)
    (tools / "plans" / "the-plan.md").write_text("plan 1\n")
    hrun("tag", projF, "--apply")
    J(hrun("handover", projF, "--apply", "--no-start", "--json"))
    J(hrun("reclaim", projF, "--apply", "--json"))
    (tools / "file-history" / "fh1" / "p@v1").write_text("v1, again\n")
    (tools / "plans" / "the-plan.md").write_text("plan 2\n")
    time.sleep(1.1)
    J(hrun("handover", projF, "--apply", "--no-start", "--json"))
    uidF = entry(projF)[0]
    kept = sorted(str(p.relative_to(bhome / ".aht" / "remote" / "replaced" / uidF))
                  for p in (bhome / ".aht" / "remote" / "replaced" / uidF).rglob("*")
                  if p.is_file())
    ck(any(k.endswith("file-history/fh1/p@v1") for k in kept)
       and any(k.endswith("plans/the-plan.md") for k in kept)
       and (bhome / ".claude" / "plans" / "the-plan.md").read_text() == "plan 2\n",
       f"file-history and plans: what a handover replaces there is set aside ({kept})")
    J(hrun("reclaim", projF, "--apply", "--json"))

    # a name whose case changed there (readme.md → README.md) comes back: the
    # file stays in the working copy, the old one is set aside
    projC = os.path.realpath(str(roots / "Case Change"))
    os.makedirs(projC)
    Path(projC, "readme.md").write_text("r1\n")
    hrun("tag", projC, "--apply")
    J(hrun("handover", projC, "--apply", "--no-start", "--json"))
    os.rename(str(box) + projC + "/readme.md", str(box) + projC + "/tmp-name")
    os.rename(str(box) + projC + "/tmp-name", str(box) + projC + "/README.md")
    d = J(hrun("reclaim", projC, "--apply", "--json"))
    names = sorted(os.listdir(projC))
    aside = Path(d.get("set_aside") or "/nonexistent")
    ck(d.get("applied") and "README.md" in names and "readme.md" not in names
       and Path(projC, "README.md").read_text() == "r1\n"
       and (aside / "project" / "readme.md").read_text() == "r1\n",
       f"a case rename made there comes back; the old name is set aside ({names})")

    # a repository made there and packed (git gc leaves refs/heads empty)
    # comes back as a repository: folders travel back too
    if shutil.which("git"):
        projR = os.path.realpath(str(roots / "Repo Made There"))
        os.makedirs(projR)
        Path(projR, "r.txt").write_text("r\n")
        hrun("tag", projR, "--apply")
        J(hrun("handover", projR, "--apply", "--no-start", "--json"))
        rr = str(box) + projR
        g = ["git", "-c", "user.name=aht test", "-c", "user.email=test@example.invalid",
             "-C", rr]
        for c in (["init", "-q"], ["add", "r.txt"], ["commit", "-q", "-m", "first"],
                  ["gc", "-q"]):
            subprocess.run(g + c, capture_output=True)
        d = J(hrun("reclaim", projR, "--apply", "--json"))
        lg = subprocess.run(["git", "-C", projR, "log", "--oneline"], capture_output=True,
                            text=True)
        ck(d.get("applied") and lg.returncode == 0 and "first" in lg.stdout
           and Path(projR, ".git", "refs", "heads").is_dir(),
           f"a packed repository made there is a repository here too ({lg.stderr.strip()})")

    # set-asides there: the same rule (newest 5, everything under 30 days)
    far_aside = bhome / ".aht" / "remote" / "replaced" / "test-aside"
    for days in (40, 41, 42, 43, 44, 45, 1):
        (far_aside / time.strftime("%Y%m%d-%H%M%S",
                                   time.localtime(time.time() - days * 86400))).mkdir(parents=True)
    pr = rem.agent("prune", dir=str(far_aside), keep=5)
    ck(pr.get("pruned") == 2 and len(list(far_aside.iterdir())) == 5,
       f"set-asides there: the same rule ({pr})")
    shutil.rmtree(far_aside)

    # ---- a real machine, with ssh: a sandbox there, and a Windows PC --------- #
    # short names: the history folder there is named after the project's
    # path inside the sandbox, as long as the test machine's (see above)
    far = Path(os.path.realpath(sb)) / "f"
    farbin = far / "bin"
    farbin.mkdir(parents=True)
    if core.find_rsync():
        os.symlink(core.find_rsync()["path"], farbin / "rsync")
    machine = far / "127.0.0.1"
    realhome = machine / "home"
    (realhome / ".claude" / "projects").mkdir(parents=True)
    (realhome / ".claude" / "settings.json").write_text("{}")
    (realhome / ".profile").write_text("# the machine's own\n")
    (machine / "path").write_text(f"{farbin}:/usr/bin:/bin:/usr/sbin:/sbin")
    (machine / "env").write_text(f"AHT_ITERM_TABS={sb / 'no-tabs.json'}\n")
    sbx = far / "s"
    (sbx / "bin").mkdir(parents=True)
    for n in ("tmux", "claude"):
        shutil.copy(stubs / n, sbx / "bin" / n)
    sshbin = sb / "sshbin"
    sshbin.mkdir()
    (sshbin / "ssh").write_text(f'#!/bin/sh\nexec "{PY}" "{HERE / "fake_ssh.py"}" "$@"\n')
    (sshbin / "ssh").chmod(0o755)
    def snapshot(root):
        return sorted((str(p.relative_to(root)), p.is_dir(),
                       None if p.is_dir() else p.stat().st_mtime) for p in root.rglob("*"))
    before = snapshot(realhome)
    sev = dict(nev, PATH=str(sshbin) + os.pathsep + env["PATH"], FAKE_SSH_DIR=str(far))
    sev.pop("AHT_REMOTE_PATH", None)
    def srun(*a, **extra):
        return run(*a, extra_env=dict(sev, **extra))
    remotes = {"box": {"root": str(box)},
               "sbx": {"ssh": "far@127.0.0.1", "sandbox": str(sbx)}}
    hrun("config", "--set", "remotes=" + json.dumps(remotes))

    cid = hashlib.sha256(Path(CLI).read_bytes()).hexdigest()[:12]
    d = J(srun("remote", "check", "sbx", "--json"))
    m0 = (d.get("machines") or [{}])[0]
    rdir = sbx / "home" / ".aht" / "remote"
    ck(not m0.get("error") and m0.get("system") in ("Darwin", "Linux"),
       f"sandbox: remote check reaches it ({m0.get('error') or m0.get('system')})")
    cfg = json.loads((sb / ".aht" / "config.json").read_text())
    ck(cfg["remotes"]["sbx"].get("system") == m0.get("system")
       and sorted(p.name for p in rdir.glob("aht*.py")) == [f"aht-{cid}.py"],
       "…its system is remembered, and the copy of aht there is named by its checksum")
    srun("board", "--json")
    f1 = [(p.name, p.stat().st_mtime) for p in rdir.glob("aht*.py")]
    srun("board", "--json")
    f2 = [(p.name, p.stat().st_mtime) for p in rdir.glob("aht*.py")]
    ck(f1 == f2 == [(f"aht-{cid}.py", f1[0][1])],
       "two board runs: one copy there, not sent again")
    for i, age in ((1, 400), (2, 300), (3, 200)):
        old = rdir / f"aht-00000000000{i}.py"
        old.write_text("# another version\n")
        os.utime(old, (time.time() - age, time.time() - age))
    (rdir / "aht.py").write_text("# the copy older versions used\n")
    (rdir / f"aht-{cid}.py").unlink()
    srun("board", "--json")
    ck(sorted(p.name for p in rdir.glob("aht*.py"))
       == sorted([f"aht-{cid}.py", "aht-000000000002.py", "aht-000000000003.py"]),
       "a fourth version there prunes the oldest; the old aht.py is gone")

    projZ = os.path.realpath(str(roots / "Sandboxed"))
    os.makedirs(projZ)
    Path(projZ, "z.txt").write_text("z\n")
    zstore = tools / "claude" / enc(projZ)
    zstore.mkdir()
    (zstore / "z1.jsonl").write_text(json.dumps(
        {"type": "user", "cwd": projZ, "message": {"content": "hello"}}) + "\n")
    hrun("tag", projZ, "--apply")
    d = J(srun("handover", projZ, "--to", "sbx", "--apply", "--json", AHT_TEST_DROP="start"))
    e = entry(projZ)[1]
    ck(not d.get("applied") and (e.get("handing") or {}).get("step") == "starting",
       f"sandbox: the link drops after “start” ({d.get('error')})")
    d = J(srun("notices", "--json"))
    e = entry(projZ)[1]
    rz = str(sbx) + projZ
    ck(e.get("away") and not e.get("handing")
       and any("finished" in n["message"] for n in d.get("notices", []))
       and Path(rz, "z.txt").is_file()
       and (sbx / "home" / ".claude" / "projects" / enc(rz) / "z1.jsonl").is_file(),
       f"sandbox: finished at the next check; the project and its history are inside "
       f"the sandbox ({d.get('notices')})")
    calls = [json.loads(l) for l in (sbx / "home" / ".faketmux" / "calls.log")
             .read_text().splitlines()] \
        if (sbx / "home" / ".faketmux" / "calls.log").is_file() else []
    ck(calls and all(c["socket"] == "aht-sbx" for c in calls),
       f"sandbox: every tmux call there named a server of its own ({len(calls)})")
    rsbx = core.Remote("sbx", remotes["sbx"])
    rsbx._route = ("far@127.0.0.1", None)         # as it resolves: no ssh asked
    att = core.attach_command(rsbx, "tmux", "aht-x")
    ck(calls and all(c.get("tmpdir") == str(sbx / "tmux") for c in calls)
       and (sbx / "tmux").is_dir()
       and att[:5] == ["ssh", "-t", "far@127.0.0.1", "env",
                       "TMUX_TMPDIR=" + shlex.quote(str(sbx / "tmux"))],
       f"sandbox: that tmux server's socket is inside it too, and Open finds it there "
       f"({sorted({str(c.get('tmpdir')) for c in calls})}, {att[:5]})")
    d = J(srun("reclaim", projZ, "--apply", "--stop", "--json"))
    ck(d.get("applied"), f"sandbox: taken back ({d.get('error') or d.get('blockers')})")
    hrun("config", "--set", "offsite_backup=sbx")
    d = J(srun("backup", "--offsite", "--json"))
    ck((sbx / "home" / ".aht" / "offsite" / mid / "machine.json").is_file(),
       f"sandbox: backups go into the sandbox ({d.get('folder') or d})")
    hrun("config", "--unset", "offsite_backup")
    # a test machine added with its sandbox: aht's copy there is inside it
    # from the first connect on
    was_default = json.loads((sb / ".aht" / "config.json").read_text()).get("default_remote")
    r = srun("remote", "add", "sbx2", "far@127.0.0.1", "--sandbox", str(far / "s2"))
    cfg = json.loads((sb / ".aht" / "config.json").read_text())
    ck(r.returncode == 0 and (cfg["remotes"].get("sbx2") or {}).get("sandbox") == str(far / "s2")
       and [p.name for p in (far / "s2" / "home" / ".aht" / "remote").glob("aht*.py")]
       == [f"aht-{cid}.py"],
       f"remote add --sandbox: aht's copy there is inside the sandbox from the first "
       f"connect on ({r.stderr.strip() or cfg['remotes'].get('sbx2')})")
    if was_default is None:
        hrun("config", "--unset", "default_remote")
    ck(snapshot(realhome) == before,
       "sandbox: NOTHING was written outside it there — that machine's own home is "
       "as it was")

    # a machine whose ssh answers like Windows (cmd.exe): no sh script goes
    # there, its own command line is tried instead (aht.exe, then aht's copy
    # with py -3 or python); with neither, a plain refusal, nothing made
    pc = far / "127.0.0.2"
    (pc / "home").mkdir(parents=True)
    (pc / "windows").write_text("")
    r = srun("remote", "add", "pc", "me@127.0.0.2")
    def pc_log(m=pc):
        return [json.loads(l) for l in (m / "commands.log").read_text().splitlines()] \
            if (m / "commands.log").is_file() else []
    def firsts(m=pc):
        return [c.split(" ", 2)[:2] if not c.startswith("echo") else c for c in pc_log(m)]
    tried = ["echo aht-os %OS% $env:OS", ["aht", "_agent"], ["py", "-3"], ["python", "-X"]]
    cfg = json.loads((sb / ".aht" / "config.json").read_text())
    ck(r.returncode == 1 and "install aht on pc" in r.stderr
       and firsts() == tried and os.listdir(pc / "home") == []
       and "pc" not in cfg["remotes"],
       f"remote add: a PC with neither aht nor Python: no sh script, its own line tried "
       f"(aht.exe, py -3, python), then a plain refusal; nothing made there "
       f"({r.stderr.strip()}, {firsts()}, {os.listdir(pc / 'home')})")
    # …and one whose ssh starts PowerShell (OpenSSH on Windows can be set up so)
    ps = far / "127.0.0.3"
    (ps / "home").mkdir(parents=True)
    (ps / "windows").write_text("powershell\n")
    r = srun("remote", "add", "pc2", "me@127.0.0.3")
    cfg = json.loads((sb / ".aht" / "config.json").read_text())
    ck(r.returncode == 1 and "install aht on pc2" in r.stderr
       and firsts(ps) == tried and os.listdir(ps / "home") == []
       and "pc2" not in cfg["remotes"],
       f"remote add: a PC that answers in PowerShell reads the same lines, nothing made there "
       f"({r.stderr.strip()}, {firsts(ps)}, {os.listdir(ps / 'home')})")
    hrun("config", "--set", "remotes=" + json.dumps(dict(remotes, pc={"ssh": "me@127.0.0.2"})))
    d = J(srun("remote", "check", "pc", "--json"))
    srun("board", "--json")
    cfg = json.loads((sb / ".aht" / "config.json").read_text())
    m = (d.get("machines") or [{}])[0]
    rows = {c["check"]: c for c in m.get("checks") or []}
    lst = J(hrun("remote", "--json")).get("remotes", {}).get("pc", {})
    ck("install aht on pc" in (m.get("error") or "")
       and (rows.get("aht answers there") or {}).get("ok") is False
       and (rows.get("aht answers there") or {}).get("fix", "").startswith("On the PC: install aht")
       and (rows.get("reachable") or {}).get("ok") is True
       and cfg["remotes"]["pc"].get("system") == "Windows"
       and lst.get("answers") is False and "install aht on pc" in (lst.get("answers_why") or "")
       and pc_log()[4] == "echo aht-os %OS% $env:OS" and os.listdir(pc / "home") == []
       and not any("mkdir" in c or "exec" in c for c in pc_log()),
       f"remote check: one set up before asks its shell first and remembers a PC; the row "
       f"that fails says how to fix it; the list says it does not answer, and why; no sh "
       f"script was sent ({m.get('error')}, {rows.get('aht answers there')}, {lst}, "
       f"{pc_log()[4:]})")
    for w in (sbx / "home" / ".faketmux").glob("*.json"):
        rec = json.loads(w.read_text())
        if rec.get("alive"):
            try:
                os.kill(int(rec["pid"]), 15)
            except OSError:
                pass


FIXTURES5 = HERE / "fixtures" / "phase5"

def phase5_suite(henv, hrun, J, project_row):
    """Look before a sync overwrites: the copy there is compared with its own
    list from the last sync; a change there, many removals or another folder
    pause the sync; Bring Them Here, Replace Them, Allow the Removals; the
    copies note on the other machine and what it stops there; Hand Over's
    look at a changed copy."""
    fx = []
    def fx5(real, name, part=None):
        sample = json.loads((FIXTURES5 / name).read_text())
        return [f"{name}{m}" for m in same_shape(real, sample[part] if part else sample)]
    box = Path(os.path.realpath(sb)) / "box5"      # a machine of its own for these
    bhome = box / "home"
    (bhome / ".claude" / "projects").mkdir(parents=True)
    hrun("config", "--set", "remotes=" + json.dumps({"box": {"root": str(box)}}))
    nlog = sb / "notices-phase5.log"
    def nrun(*a, **extra):
        return J(run(*a, extra_env=dict(henv, AHT_NOTIFY_LOG=str(nlog), **extra)))
    def told():
        return [json.loads(l) for l in nlog.read_text().splitlines()] if nlog.is_file() else []
    def reg_entry(path):
        reg = json.loads((sb / ".aht" / "registry.json").read_text())
        return next((u, e) for u, e in reg["projects"].items() if e["real_path"] == path)
    def copies_there():
        try:
            return json.loads((bhome / ".aht" / "remote" / "copies.json").read_text())
        except (OSError, ValueError):
            return {}
    # box itself, with aht: its own home, its own registry, the Mac as "mac"
    benv = dict(iso_env("box5"), HOME=str(bhome), AHT_HOME=str(bhome / ".aht"),
                AHT_ROOT_CLAUDE=str(bhome / ".claude" / "projects"), AHT_MACHINE_NAME="box")
    def brun(*a):
        return subprocess.run([PY, LAUNCH, *a], env=benv, capture_output=True, text=True)
    brun("config", "--set", "remotes=" + json.dumps({"mac": {"root": str(sb / "mac5")}}))
    here = core._here()

    projS = os.path.realpath(str(roots / "Synced"))
    os.makedirs(projS + "/src")
    for i in range(40):
        Path(projS, "src", f"f{i:02d}.py").write_text(f"x = {i}\n")
    Path(projS, "README.md").write_text("readme\n")
    far = Path(str(box) + projS)
    hrun("mirror", projS, "--on", "--to", "box")
    rows = nrun("mirror", projS, "--run", "--json").get("mirrored") or [{}]
    uidS = reg_entry(projS)[0]
    thr = sb / ".aht" / "handover" / uidS / "there" / "box.json"
    t1 = json.loads(thr.read_text()) if thr.is_file() else {}
    c = copies_there().get(str(far)) or {}
    ck(rows[0].get("status") == "synced" and t1.get("kind") == "sync"
       and t1.get("remote") == "box" and "src/f00.py" in t1.get("here", {}).get("project", {})
       and "src/f00.py" in t1.get("there", {}).get("project", {})
       and c.get("kind") == "sync" and c.get("uuid") == uidS and c.get("from") == here
       and c.get("from_id") and c.get("at"),
       f"a sync writes there/box.json (both sides' lists) and box notes its copy in "
       f"copies.json ({rows[0].get('reason')}, {c})")

    # only touched there: no pause
    time.sleep(1.1)
    os.utime(far / "src" / "f01.py")
    rows = nrun("mirror", projS, "--run", "--json").get("mirrored") or [{}]
    ck(rows[0].get("status") == "synced" and not told(),
       f"a file there that was only touched does not pause the sync ({rows[0].get('reason')})")

    # touched there and edited here: the copy there is compared with the
    # checksum the last sync left in the base, not with this side's file
    time.sleep(1.1)
    os.utime(far / "src" / "f02.py")
    Path(projS, "src", "f02.py").write_text("x = 2  # edited here\n")
    rows = nrun("mirror", projS, "--run", "--json").get("mirrored") or [{}]
    sums = (json.loads(thr.read_text()).get("sums") or {}).get("project") or {}
    ck(rows[0].get("status") == "synced" and not told()
       and (far / "src" / "f02.py").read_text() == "x = 2  # edited here\n"
       and len(sums.get("src/f02.py") or "") == 64,
       f"a file only touched there and edited here does not pause the sync; the base keeps "
       f"the files' checksums there ({rows[0].get('reason')}, {len(sums)} checksums)")

    # a change there: the sync pauses, names the files, sends nothing, tells once
    time.sleep(1.1)
    (far / "README.md").write_text("edited on box\n")
    (far / "src" / "new_there.py").write_text("y = 1\n")
    Path(projS, "README.md").write_text("edited here\n")
    Path(projS, "src", "f00.py").write_text("changed here\n")
    d = nrun("mirror", projS, "--run", "--json")
    fx += fx5(d, "mirror_paused.json")
    p = ((d.get("mirrored") or [{}])[0]).get("paused") or {}
    again = nrun("mirror", projS, "--run", "--json").get("mirrored") or [{}]
    due = nrun("mirror", "--run", "--due", "--json").get("mirrored")
    row = project_row(projS)
    fx += fx5(row, "projects.json", "paused")
    ck(p.get("reason") == "changed" and p.get("files") == ["README.md", "src/new_there.py"]
       and p.get("changed") == 1 and p.get("new") == 1 and p.get("remote") == "box"
       and (far / "README.md").read_text() == "edited on box\n"
       and (far / "src" / "f00.py").read_text() == "x = 0\n"
       and again[0].get("status") == "paused" and due == []
       and (row.get("mirror_paused") or {}).get("reason") == "changed",
       f"a change in the copy there pauses the sync, with the files named; nothing is "
       f"replaced there ({p})")
    n = told()
    ck(len(n) == 1 and n[0]["title"] == "Keep in sync paused: Synced"
       and "Bring Them Here, Replace Them or Stop Syncing" in n[0]["message"],
       f"…and tells once ({n})")

    # Bring Them Here: Take Back on the synced copy, keeping both where both
    # changed, then the sync runs
    d = nrun("reclaim", projS, "--json")
    fx += fx5(d, "reclaim_copy_dry.json")
    ck(d.get("mode") == "copy" and not d.get("applied") and d.get("plan", {}).get("project")
       == {"take": 0, "new": 1, "delete": 0, "conflict": 1, "kept": 1},
       f"Bring Them Here, dry run: the plan of a Take Back on the copy ({d.get('plan') or d})")
    d = nrun("reclaim", projS, "--apply", "--json")
    fx += fx5(d, "reclaim_copy.json")
    both = [x.name for x in Path(projS).glob("README (from box *).md")]
    e = reg_entry(projS)[1]
    ck(d.get("applied") and d.get("mode") == "copy" and (d.get("sync") or {}).get("status")
       == "synced" and Path(projS, "README.md").read_text() == "edited here\n"
       and len(both) == 1 and Path(projS, both[0]).read_text() == "edited on box\n"
       and Path(projS, "src", "new_there.py").is_file()
       and (far / "README.md").read_text() == "edited here\n"
       and (far / both[0]).is_file() and (far / "src" / "f00.py").read_text() == "changed here\n"
       and not (e.get("mirror") or {}).get("paused") and not e.get("away")
       and (e.get("returned") or {}).get("mode") == "copy",
       f"…--apply brings them, keeps both versions of what changed on both, then the sync "
       f"runs ({d.get('error') or d.get('blockers') or d.get('sync')})")
    note = subprocess.run([PY, LAUNCH, "hook"], env=dict(env, **henv), capture_output=True,
                          text=True, input=json.dumps({"cwd": projS})).stdout
    ck("were brought here" in note and "Changed in BOTH copies" in note,
       f"the next session here is told what came from the copy ({note!r})")

    # Replace Them: once, theirs set aside there
    time.sleep(1.1)
    (far / "README.md").write_text("edited on box again\n")
    nrun("mirror", projS, "--run", "--json")
    d = nrun("mirror", projS, "--replace", "--json")
    fx += fx5(d, "mirror_replace_dry.json")
    dry_ok = d.get("would", {}).get("replace") == 1 and not d.get("applied") \
        and (far / "README.md").read_text() == "edited on box again\n"
    d = nrun("mirror", projS, "--replace", "--apply", "--json")
    fx += fx5(d, "mirror_replace_apply.json")
    kept = [k for k in (bhome / ".aht" / "remote" / "replaced" / uidS).rglob("README.md")
            if k.read_text() == "edited on box again\n"]
    ck(dry_ok and d.get("applied") and (far / "README.md").read_text() == "edited here\n"
       and len(kept) == 1 and not project_row(projS).get("mirror_paused")
       and ((d.get("mirrored") or [{}])[0]).get("ended_pause") == "changed",
       f"--replace sends this copy over the changed one, theirs set aside there "
       f"({d.get('mirrored')})")

    # many removals here: the sync pauses before it removes them there
    for i in range(4, 40):
        Path(projS, "src", f"f{i:02d}.py").unlink()
    d = nrun("mirror", projS, "--run", "--json")
    fx += fx5(d, "mirror_paused_removals.json")
    p = ((d.get("mirrored") or [{}])[0]).get("paused") or {}
    ck(p.get("reason") == "removals" and p.get("removed") == 36 and p.get("total", 0) >= 40
       and (far / "src" / "f39.py").is_file(),
       f"deleting most files here pauses the sync; nothing is removed there ({p})")
    d = nrun("mirror", projS, "--allow-removals", "--json")
    fx += fx5(d, "mirror_allow_removals_dry.json")
    dry_ok = d.get("would") == {"remove": 36, "total": p.get("total")} \
        and (far / "src" / "f39.py").is_file()
    d = nrun("mirror", projS, "--allow-removals", "--apply", "--json")
    fx += fx5(d, "mirror_allow_removals_apply.json")
    ck(dry_ok and d.get("applied") and not (far / "src" / "f39.py").exists()
       and list((bhome / ".aht" / "remote" / "replaced" / uidS).rglob("f39.py"))
       and not project_row(projS).get("mirror_paused"),
       f"--allow-removals lets that one sync remove them there, set aside there "
       f"({d.get('mirrored') or d.get('error')})")
    small = os.path.realpath(str(roots / "Small Sync"))
    os.makedirs(small)
    for i in range(5):
        Path(small, f"s{i}.txt").write_text("s\n")
    hrun("mirror", small, "--on", "--to", "box")
    nrun("mirror", small, "--run", "--json")
    for i in range(4):
        Path(small, f"s{i}.txt").unlink()
    rows = nrun("mirror", small, "--run", "--json").get("mirrored") or [{}]
    ck(rows[0].get("status") == "synced" and not Path(str(box) + small, "s0.txt").exists(),
       "…but a few files of a small project are removed as usual")
    hrun("mirror", small, "--off")

    # a first sync into a folder that holds another project: paused
    projO = os.path.realpath(str(roots / "Other Place"))
    os.makedirs(projO)
    Path(projO, "mine.txt").write_text("mine\n")
    farO = Path(str(box) + projO)
    (farO / ".aht").mkdir(parents=True)
    (farO / ".aht" / ".project-id").write_text("someone-elses-id\n")
    (farO / "theirs.txt").write_text("theirs\n")
    hrun("mirror", projO, "--on", "--to", "box")
    d = nrun("mirror", projO, "--run", "--json")
    fx += fx5(d, "mirror_paused_other_folder.json")
    p = ((d.get("mirrored") or [{}])[0]).get("paused") or {}
    ck(p.get("reason") == "other-folder" and p.get("marker") == "someone-elses-id"
       and "theirs.txt" in p.get("files", []) and (farO / "theirs.txt").is_file()
       and not (farO / "mine.txt").exists(),
       f"a first sync into a folder with another project's id pauses; nothing is sent ({p})")
    r = hrun("mirror", projO, "--off")
    ck(r.returncode == 0 and not project_row(projO).get("mirror")
       and (farO / "theirs.txt").is_file(),
       "Stop Syncing leaves that folder as it is")

    # box: the copy is noted; turning sync on there for it is refused, its
    # own Keep All leaves it out, its hook and its projects row say whose it is
    farS = str(far)
    own = bhome / "code" / "notes"
    own.mkdir(parents=True)
    (own / "todo.md").write_text("- box's own\n")
    brun("tag", farS, "--apply")
    brun("tag", str(own), "--apply")
    r = brun("mirror", farS, "--on", "--to", "mac")
    breg = json.loads((bhome / ".aht" / "registry.json").read_text())
    ck(r.returncode == 3 and f"a copy kept in sync from {here}" in r.stderr
       and not any((e.get("mirror") or {}).get("enabled") for e in breg["projects"].values()),
       f"on box, Keep in sync for the copy kept in sync from here is refused ({r.stderr.strip()})")
    try:
        d = json.loads(brun("mirror", "--all", "--on", "--to", "mac", "--json").stdout)
    except ValueError:
        d = {}
    fx += fx5(d, "mirror_all_on.json")
    ck(d.get("copies_skipped") == [farS]
       and [x["project"] for x in d.get("projects", [])] == [str(own)],
       f"box's own Keep All Projects in Sync leaves the copy out ({d.get('copies_skipped')})")
    try:
        brow = next(x for x in json.loads(brun("projects", "--json").stdout)["projects"]
                    if x["real_path"] == farS)
    except (ValueError, StopIteration):
        brow = {}
    fx += fx5(brow, "projects.json", "copy")
    bnote = subprocess.run([PY, LAUNCH, "hook"], env=benv, capture_output=True, text=True,
                           input=json.dumps({"cwd": farS})).stdout
    ck({k: (brow.get("copy_of") or {}).get(k) for k in ("from", "kind", "at")}
       == {"from": here, "kind": "sync", "at": c.get("at")}
       and f"a copy kept in sync from “{here}”" in bnote,
       f"box's row and hook name the machine it is kept in sync from "
       f"({brow.get('copy_of')}, {bnote!r})")

    # names the disk there cannot hold apart are listed
    m = {"files": {"A.txt": [1, 1], "a.txt": [1, 1], "b.txt": [1, 1], "Src/x": [1, 1]},
         "dirs": ["Src", "src"], "raw": {}, "twins": {"é.txt": ["é.txt", "é.txt"]}}
    probs = {x["kind"]: x for x in core.name_problems(m, {"case_sensitive": False})}
    ck(probs.get("case", {}).get("count") == 2 and ["A.txt", "a.txt"] in probs["case"]["names"]
       and probs.get("unicode", {}).get("count") == 1
       and [x["kind"] for x in core.name_problems(m, {"case_sensitive": True})] == ["unicode"],
       f"name_problems: two names one case apart on a disk that ignores case, and "
       f"Unicode twins ({probs})")
    os.environ["AHT_CASELESS"] = "1"
    try:                                    # the probe tries the disk there
        fsi = core.Remote("box", {"root": str(box)}).connect(projS, fs=True).get("fs")
    finally:
        os.environ.pop("AHT_CASELESS", None)
    ck((fsi or {}).get("case_sensitive") is False,
       f"the probe says whether the disk there ignores case (AHT_CASELESS reaches it) ({fsi})")
    projK = os.path.realpath(str(roots / "Cases"))
    os.makedirs(projK)
    Path(projK, "Readme.md").write_text("one\n")
    Path(projK, "README.md").write_text("two\n")
    if len(os.listdir(projK)) == 2:         # a disk that tells them apart (Linux)
        hrun("mirror", projK, "--on", "--to", "box")
        d = nrun("mirror", projK, "--run", "--json", AHT_CASELESS="1")
        r0 = (d.get("mirrored") or [{}])[0]
        ck(any(x["kind"] == "case" and ["README.md", "Readme.md"] in x["names"]
               for x in r0.get("names") or []),
           f"a sync to a disk that ignores case lists the two names (AHT_CASELESS) ({r0})")
        hrun("mirror", projK, "--off")
    else:
        print("  (case clash end to end skipped: this disk ignores case; Linux CI runs it)")

    # Hand Over looks at a changed copy too
    time.sleep(1.1)
    (far / "README.md").write_text("box, once more\n")
    d = nrun("handover", projS, "--no-start", "--json")
    fx += fx5(d, "handover_blocked.json")
    d2 = nrun("handover", projS, "--no-start", "--replace-there", "--json")
    ck(any("--replace-there" in b for b in d.get("blockers", []))
       and (d.get("copy_changed") or {}).get("files") == ["README.md"]
       and not any("--replace-there" in b for b in d2.get("blockers", []))
       and any("sets those changes aside there" in w for w in d2.get("warnings", [])),
       f"a handover dry run over a changed copy blocks; --replace-there is the way past "
       f"({d.get('blockers')}, {d2.get('blockers')})")

    # Stop Syncing: box drops its note (another project's note stays)
    rem = core.Remote("box", {"root": str(box)})
    other = rem.agent("uncopy", path=farS, uuid="not-this-project")
    r = hrun("mirror", projS, "--off")
    ck(other.get("dropped") is False and r.returncode == 0 and farS not in copies_there()
       and "kept in sync" not in subprocess.run(
           [PY, LAUNCH, "hook"], env=benv, capture_output=True, text=True,
           input=json.dumps({"cwd": farS})).stdout,
       f"Stop Syncing drops box's note on its copy; uncopy leaves another project's "
       f"({other}, {copies_there()})")

    # box's aht registered its copy as a project (its hook ran there), and
    # after Stop Syncing nothing notes it as a copy: Hand Over refuses to go
    # over it, as over any live project of box's own (the identity check)
    d = nrun("handover", projS, "--no-start", "--replace-there", "--json")
    ck(any("is a live project of its own there" in b for b in d.get("blockers", [])),
       f"identity: box's own live project with this id is not handed over onto "
       f"({d.get('blockers')})")
    breg = bhome / ".aht" / "registry.json"
    r5 = json.loads(breg.read_text())
    r5["projects"] = {u: e for u, e in r5["projects"].items() if e.get("real_path") != farS}
    breg.write_text(json.dumps(r5))
    # a handover and a take back write there.json too, and box's note says
    # what its copy is: handed over, then returned
    d = nrun("handover", projS, "--apply", "--no-start", "--replace-there", "--json")
    k1 = json.loads(thr.read_text()).get("kind")
    c1 = (copies_there().get(farS) or {}).get("kind")
    (far / "src" / "f00.py").write_text("done on box\n")
    d2 = nrun("reclaim", projS, "--apply", "--json")
    k2 = json.loads(thr.read_text()).get("kind")
    c2 = (copies_there().get(farS) or {}).get("kind")
    bnote = subprocess.run([PY, LAUNCH, "hook"], env=benv, capture_output=True, text=True,
                           input=json.dumps({"cwd": farS})).stdout
    ck(d.get("applied") and d2.get("applied") and d2.get("mode") == "away"
       and k1 == "handover" and c1 == "handover" and k2 == "take-back" and c2 == "returned"
       and Path(projS, "src", "f00.py").read_text() == "done on box\n"
       and "went back to" in bnote,
       f"handover and take back write there/box.json; box's note goes handover → returned "
       f"({d.get('error')}, {d2.get('error') or d2.get('blockers')}, {k1}, {c1}, {k2}, {c2})")
    # one base per machine: a handover and take back with pc5 leaves box's
    # alone, so box's changed copy still pauses the sync, Hand Over to box
    # still blocks, and Bring Them Here asks box
    pc5 = Path(os.path.realpath(sb)) / "pc5"
    hrun("config", "--set", "remotes=" + json.dumps(
        {"box": {"root": str(box)}, "pc5": {"root": str(pc5)}}))
    projM = os.path.realpath(str(roots / "Two Machines"))
    os.makedirs(projM)
    for n in ("README.md", "a.txt", "b.txt"):
        Path(projM, n).write_text(f"{n}\n")
    hrun("mirror", projM, "--on", "--to", "box")
    nrun("mirror", projM, "--run", "--json")
    uidM = reg_entry(projM)[0]
    farM = Path(str(box) + projM)
    d1 = nrun("handover", projM, "--to", "pc5", "--apply", "--no-start", "--json")
    d2 = nrun("reclaim", projM, "--apply", "--json")
    bases = sorted(x.name for x in (sb / ".aht" / "handover" / uidM / "there").glob("*.json"))
    time.sleep(1.1)
    (farM / "README.md").write_text("README, edited on box\n")
    p = ((nrun("mirror", projM, "--run", "--json").get("mirrored") or [{}])[0]
         .get("paused") or {})
    ho = nrun("handover", projM, "--to", "box", "--no-start", "--json")
    rc = nrun("reclaim", projM, "--json")
    ck(d1.get("applied") and d2.get("applied") and d2.get("mode") == "away"
       and bases == ["box.json", "pc5.json"]
       and p.get("reason") == "changed" and p.get("files") == ["README.md"]
       and (farM / "README.md").read_text() == "README, edited on box\n"
       and any("--from box" in b and "--replace-there" in b for b in ho.get("blockers", []))
       and rc.get("mode") == "copy" and rc.get("remote") == "box"
       and (rc.get("plan") or {}).get("project", {}).get("take") == 1,
       f"one base per machine: after a handover and take back with pc5, box's changed copy "
       f"still pauses the sync, blocks Hand Over and is what Bring Them Here asks "
       f"({d1.get('error') or d1.get('blockers')}, {d2.get('error')}, {bases}, {p}, "
       f"{ho.get('blockers')}, {rc.get('remote')}, {rc.get('plan')})")
    hrun("mirror", projM, "--off")
    hrun("config", "--set", "remotes=" + json.dumps({"box": {"root": str(box)}}))
    # an earlier version's single there.json counts for the machine it names
    hd0 = sb / ".aht" / "handover" / "0ld0ne"
    hd0.mkdir(parents=True)
    (hd0 / "there.json").write_text(json.dumps({
        "v": 1, "remote": "box", "remote_path": "/x", "at": "2026-10-01T10:00:00",
        "here": {"project": {}}, "there": {"project": {}}}))
    snippet = ("import sys, json; sys.path.insert(0, sys.argv[1]); import aht as c; "
               "print(json.dumps([bool(c.read_there('0ld0ne', 'box', '/x')), "
               "bool(c.read_there('0ld0ne', 'pc5')), "
               "(c.read_there('0ld0ne') or {}).get('remote')]))")
    r = subprocess.run([PY, "-c", snippet, str(HERE.parent)], env=env, capture_output=True,
                       text=True)
    ck(r.stdout.strip() == '[true, false, "box"]',
       f"an earlier version's there.json is read as the base of the machine it names "
       f"({r.stdout.strip()}{r.stderr[-300:]})")
    shutil.rmtree(hd0)

    # a copy whose project went home, synced back there: the folder there is
    # that machine's own live project, so a first sync pauses
    projQ = os.path.realpath(str(roots / "Went Home"))
    os.makedirs(projQ)
    Path(projQ, "a.txt").write_text("a, as it came back\n")
    Path(projQ, "b.txt").write_text("b\n")
    hrun("tag", projQ, "--apply")
    uidQ = reg_entry(projQ)[0]
    cpm = sb / ".aht" / "remote" / "copies.json"
    cpm_was = cpm.read_text() if cpm.is_file() else None
    cpm.parent.mkdir(parents=True, exist_ok=True)
    cpm.write_text(json.dumps(dict(json.loads(cpm_was or "{}"), **{projQ: {
        "uuid": uidQ, "from": "box", "from_id": "b0b0b0b0b0b0", "kind": "returned",
        "attempt": None, "at": "2026-10-27T10:00:00"}})))
    farQ = Path(str(box) + projQ)
    (farQ / ".aht").mkdir(parents=True)
    (farQ / ".aht" / ".project-id").write_text(uidQ + "\n")
    (farQ / "a.txt").write_text("a, box's own work\n")
    (farQ / "c.txt").write_text("c\n")
    brun("tag", str(farQ), "--apply")
    r = hrun("mirror", projQ, "--on", "--to", "box")
    row = (nrun("mirror", projQ, "--run", "--json").get("mirrored") or [{}])[0]
    p = row.get("paused") or {}
    ck(r.returncode == 0 and p.get("reason") == "other-folder" and p.get("owner") == "own"
       and p.get("marker") == uidQ and "a live project of box's own" in row.get("reason", "")
       and (farQ / "a.txt").read_text() == "a, box's own work\n"
       and not (farQ / "b.txt").exists(),
       f"a returned copy synced back where it came from pauses: the folder there is that "
       f"machine's own live project ({r.stderr.strip()}, {p})")
    hrun("mirror", projQ, "--off")
    if cpm_was is None:
        cpm.unlink()
    else:
        cpm.write_text(cpm_was)

    # no base (a project synced before there were bases): only files that
    # differ and are newer there pause; Bring Them Here keeps both
    projN = os.path.realpath(str(roots / "Synced Before"))
    os.makedirs(projN)
    for i in range(4):
        Path(projN, f"n{i}.txt").write_text(f"n{i}\n")
    hrun("mirror", projN, "--on", "--to", "box")
    nrun("mirror", projN, "--run", "--json")
    uidN = reg_entry(projN)[0]
    farN = Path(str(box) + projN)
    def forget_base():
        shutil.rmtree(sb / ".aht" / "handover" / uidN / "there", ignore_errors=True)
    forget_base()
    time.sleep(1.1)
    Path(projN, "n1.txt").write_text("n1, edited here\n")
    os.utime(farN / "n3.txt")
    r1 = (nrun("mirror", projN, "--run", "--json").get("mirrored") or [{}])[0]
    forget_base()
    time.sleep(1.1)
    (farN / "n2.txt").write_text("n2, edited on box\n")
    p = ((nrun("mirror", projN, "--run", "--json").get("mirrored") or [{}])[0]
         .get("paused") or {})
    ck(r1.get("status") == "synced" and (farN / "n1.txt").read_text() == "n1, edited here\n"
       and p.get("reason") == "changed" and p.get("files") == ["n2.txt"]
       and p.get("changed") == 1 and (farN / "n2.txt").read_text() == "n2, edited on box\n",
       f"a sync with no base sends what is newer here, and pauses for a file that differs "
       f"and is newer there ({r1.get('reason')}, {p})")
    dry = nrun("reclaim", projN, "--json")
    d = nrun("reclaim", projN, "--apply", "--json")
    both = [x.name for x in Path(projN).glob("n2 (from box *).txt")]
    ck(dry.get("mode") == "copy" and (dry.get("plan") or {}).get("project", {})
       .get("conflict") == 1 and d.get("applied") and (d.get("sync") or {}).get("status")
       == "synced" and Path(projN, "n2.txt").read_text() == "n2\n" and len(both) == 1
       and Path(projN, both[0]).read_text() == "n2, edited on box\n",
       f"…and Bring Them Here with no base keeps both versions of such a file "
       f"({dry.get('plan') or dry.get('blockers')}, {d.get('error') or d.get('blockers')})")
    hrun("mirror", projN, "--off")

    # Replace Them keeps the removals guard: many removals need Allow the
    # Removals too
    projR = os.path.realpath(str(roots / "Replace Many"))
    os.makedirs(projR)
    for i in range(42):
        Path(projR, f"r{i:02d}.txt").write_text(f"r{i}\n")
    hrun("mirror", projR, "--on", "--to", "box")
    nrun("mirror", projR, "--run", "--json")
    farR = Path(str(box) + projR)
    for i in range(6, 42):
        Path(projR, f"r{i:02d}.txt").unlink()
    time.sleep(1.1)
    (farR / "r00.txt").write_text("r0, edited on box\n")
    p = ((nrun("mirror", projR, "--run", "--json").get("mirrored") or [{}])[0]
         .get("paused") or {})
    dry = nrun("mirror", projR, "--replace", "--json")
    fx += fx5(dry, "mirror_replace_dry.json")
    rm = dry.get("removals") or {}
    ap = nrun("mirror", projR, "--replace", "--apply", "--json")
    still = ((reg_entry(projR)[1].get("mirror") or {}).get("paused") or {}).get("reason")
    ck(p.get("reason") == "changed" and rm.get("removed") == 36 and rm.get("total") == 43
       and rm.get("over") is True and len(rm.get("files") or []) == 36
       and any("--allow-removals" in b for b in dry.get("blockers", []))
       and not ap.get("applied") and any("--allow-removals" in b for b in ap.get("blockers", []))
       and (ap.get("removals") or {}).get("over") and (farR / "r41.txt").is_file()
       and (farR / "r00.txt").read_text() == "r0, edited on box\n" and still == "changed",
       f"Replace Them over many removals: the dry run says so (removals.over) and --apply "
       f"refuses without --allow-removals; the pause stays ({p.get('reason')}, {rm}, "
       f"{ap.get('blockers') or ap.get('mirrored')}, {still})")
    d = nrun("mirror", projR, "--replace", "--allow-removals", "--apply", "--json")
    ck(d.get("applied") and not (farR / "r41.txt").exists()
       and (farR / "r00.txt").read_text() == "r0\n"
       and list((bhome / ".aht" / "remote" / "replaced").rglob("r41.txt")),
       f"…with both, it replaces them and removes them there, set aside there "
       f"({d.get('blockers') or d.get('mirrored')})")
    hrun("mirror", projR, "--off")

    # Bring Them Here has a removals guard too, never takes the project's
    # id, and never brings an empty or missing folder here
    projB = os.path.realpath(str(roots / "Bring Back"))
    os.makedirs(projB)
    for i in range(42):
        Path(projB, f"b{i:02d}.txt").write_text(f"b{i}\n")
    hrun("mirror", projB, "--on", "--to", "box")
    nrun("mirror", projB, "--run", "--json")
    uidB = reg_entry(projB)[0]
    farB = Path(str(box) + projB)
    time.sleep(1.1)
    for i in range(6, 42):
        (farB / f"b{i:02d}.txt").unlink()
    (farB / ".aht" / ".project-id").unlink()
    (farB / "b00.txt").write_text("b0, edited on box\n")
    nrun("mirror", projB, "--run", "--json")
    dry = nrun("reclaim", projB, "--json")
    rm = dry.get("removals") or {}
    ap = nrun("reclaim", projB, "--apply", "--json")
    ck(dry.get("mode") == "copy" and rm.get("removed") == 36 and rm.get("total") == 42
       and rm.get("over") is True and any("--allow-removals" in b for b in dry.get("blockers", []))
       and not ap.get("applied") and Path(projB, "b41.txt").is_file(),
       f"Bring Them Here over many removals: the dry run says so and --apply refuses "
       f"without --allow-removals ({rm}, {dry.get('blockers')}, {ap.get('applied')})")
    d = nrun("reclaim", projB, "--allow-removals", "--apply", "--json")
    ck(d.get("applied") and not Path(projB, "b41.txt").exists()
       and Path(projB, "b00.txt").read_text() == "b0, edited on box\n"
       and core.read_marker(projB) == uidB,
       f"…--allow-removals lets it, and the project's id stays "
       f"({d.get('error') or d.get('blockers')}, {core.read_marker(projB)})")
    for x in farB.iterdir():
        shutil.rmtree(x) if x.is_dir() else x.unlink()
    em = nrun("reclaim", projB, "--allow-removals", "--apply", "--json")
    shutil.rmtree(farB)
    gone = nrun("reclaim", projB, "--allow-removals", "--json")
    ck(not em.get("applied") and any(f"({farB}) is empty" in b for b in em.get("blockers", []))
       and any(f"({farB}) is missing" in b for b in gone.get("blockers", []))
       and Path(projB, "b00.txt").is_file() and core.read_marker(projB) == uidB,
       f"…and an empty or missing folder there is never brought here, whatever is allowed "
       f"({em.get('blockers')}, {gone.get('blockers')})")
    hrun("mirror", projB, "--off")

    # what --include carries is looked at too
    projX = os.path.realpath(str(roots / "With Extra"))
    os.makedirs(projX)
    Path(projX, "a.txt").write_text("a\n")
    xdir = Path(os.path.realpath(sb)) / "extras5" / "notes"
    xdir.mkdir(parents=True)
    (xdir / "n.md").write_text("n\n")
    xfile = xdir.parent / "todo.txt"
    xfile.write_text("todo\n")
    hrun("mirror", projX, "--on", "--to", "box")
    uidX = reg_entry(projX)[0]
    regf5 = sb / ".aht" / "registry.json"
    reg = json.loads(regf5.read_text())
    reg["projects"][uidX]["extras"] = [str(xdir), str(xfile)]
    regf5.write_text(json.dumps(reg))
    r1 = (nrun("mirror", projX, "--run", "--json").get("mirrored") or [{}])[0]
    farXd, farXf = Path(str(box) + str(xdir)), Path(str(box) + str(xfile))
    trees = sorted(json.loads((sb / ".aht" / "handover" / uidX / "there" / "box.json")
                              .read_text())["there"])
    time.sleep(1.1)
    farXf.write_text("todo, edited on box\n")
    (farXd / "n.md").write_text("n, edited on box\n")
    p = ((nrun("mirror", projX, "--run", "--json").get("mirrored") or [{}])[0]
         .get("paused") or {})
    ck(r1.get("status") == "synced" and f"extra:{xfile}" in trees and f"extra:{xdir}" in trees
       and p.get("reason") == "changed" and p.get("files") == sorted([f"{xdir}/n.md", str(xfile)])
       and farXf.read_text() == "todo, edited on box\n",
       f"a changed --include'd file or folder there pauses the sync too ({trees}, {p})")
    hrun("mirror", projX, "--off")

    # uncopy drops only a note on a copy kept in sync
    notes = copies_there()
    held = str(Path(os.path.realpath(sb)) / "held-there")
    notes[held] = {"uuid": "u-held", "from": here, "from_id": "f0f0f0f0f0f0",
                   "kind": "handover", "attempt": "a1", "at": "2026-10-27T10:00:00"}
    (bhome / ".aht" / "remote" / "copies.json").write_text(json.dumps(notes))
    got = core.Remote("box", {"root": str(box)}).agent("uncopy", path=held, uuid="u-held")
    kept = (copies_there().get(held) or {}).get("kind")
    ck(got.get("dropped") is False and kept == "handover",
       f"Stop Syncing leaves the other machine's note on a handed-over copy ({got}, {kept})")
    notes.pop(held)
    (bhome / ".aht" / "remote" / "copies.json").write_text(json.dumps(notes))
    ck(not fx, f"the phase-5 JSON keeps the shape of tests/fixtures/phase5 ({fx})")
    hrun("config", "--set", "remotes=" + json.dumps(
        {"box": {"root": str(Path(os.path.realpath(sb)) / "box")}}))


def phase7_suite(stubs, henv, J):
    """Handover between systems at different paths, with a folder standing in
    for the other machine ("box") and a home of its own here ("pc"): path
    mapping, the identity check, Bring Here and Send Back (the attempt, the
    idle block, the version blocker, a conflict kept twice, unmark after a
    failure, Release), names Windows cannot hold, line endings, modes, safe
    names on the way back and git's settings (AHT_AS_WINDOWS makes this
    machine count as Windows for those, and for nothing else)."""
    fx = []
    base7 = Path(os.path.realpath(sb)) / "p7"
    box, pc = base7 / "box", base7 / "pc"
    bhome, phome = box / "home", pc / "home"
    (bhome / ".claude" / "projects").mkdir(parents=True)
    phome.mkdir(parents=True)
    tlog = base7 / "terminal.log"
    penv = dict(env, **henv, HOME=str(phome), AHT_HOME=str(phome / ".aht"),
                AHT_MACHINE_NAME="pc", AHT_REMOTE_MACHINE_NAME="box",
                AHT_TERMINAL_LOG=str(tlog), AHT_NOTIFY_LOG=str(base7 / "notify.log"),
                AHT_NO_SEARCH_INDEX="1", AHT_ITERM_TABS=str(base7 / "no-tabs.json"))
    (base7 / "no-tabs.json").write_text("{}")
    penv.pop("AHT_ROOTS", None)
    penv.pop("AHT_AS_WINDOWS", None)
    for k in [k for k in penv if k.startswith("AHT_ROOT_")]:
        penv[k] = str(pc / "tools" / k[9:].lower())
        Path(penv[k]).mkdir(parents=True, exist_ok=True)
    pclaude = Path(penv["AHT_ROOT_CLAUDE"])
    (pclaude.parent.parent / ".claude.json").write_text("{}")   # beside its ~/.claude
    benv = dict(penv, HOME=str(bhome), AHT_HOME=str(bhome / ".aht"),
                AHT_ROOT_CLAUDE=str(bhome / ".claude" / "projects"), AHT_MACHINE_NAME="box")
    def praw(*a, **extra):
        return subprocess.run([PY, LAUNCH, *a], env=dict(penv, **extra), capture_output=True,
                              text=True)
    def prun(*a, **extra):
        return J(praw(*a, **extra))
    def brun(*a, **extra):
        return subprocess.run([PY, LAUNCH, *a], env=dict(benv, **extra), capture_output=True,
                              text=True)
    def breg():
        return json.loads((bhome / ".aht" / "registry.json").read_text())["projects"]
    def copies():
        try:
            return json.loads((phome / ".aht" / "remote" / "copies.json").read_text())
        except (OSError, ValueError):
            return {}
    def fx7(real, name, part=None):
        sample = json.loads((FIXTURES7 / name).read_text())
        return [f"{name}{m}" for m in same_shape(real, sample[part] if part else sample)]
    prun("config", "--set", "remotes=" + json.dumps({"box": {"root": str(box),
                                                             "paths": "home"}}))
    prun("config", "--set", "handover_keep_awake=false")

    # where a project goes: below the home folder there; outside: refused
    rem = None
    d = prun("remote", "paths", "box", "--json")
    ck(d.get("paths") == "home" and d.get("there_home") == "/home"
       and d.get("rules") == [{"here": str(phome), "there": "/home", "kind": "home"}],
       f"remote paths: below the home folder here, below /home on the test machine ({d})")
    d = prun("remote", "paths", "box", "--add", "/Volumes/work", "/home/work", "--json")
    fx += fx7(d, "remote_paths.json")
    ck(d.get("applied") and d.get("paths") == [["/Volumes/work", "/home/work"]]
       and [r["kind"] for r in d.get("rules", [])] == ["pair", "home"],
       f"remote paths --add: a pair, tried before the homes ({d.get('rules')})")
    d = prun("remote", "paths", "box", "--remove", "/Volumes/work", "--json")
    ck(d.get("applied") and d.get("paths") == "home", "remote paths --remove: back to home")

    # the project on box: registered by box's own aht, with a Claude history
    bproj = bhome / "code" / "shop"
    for rel, body in (("src/app.py", "print(1)\n"), ("README.md", "line one\nline two\n"),
                      ("docs/notes.txt", "a\nb\n"), ("bin/run.sh", "#!/bin/sh\necho run\n")):
        (bproj / rel).parent.mkdir(parents=True, exist_ok=True)
        (bproj / rel).write_text(body)
    os.chmod(bproj / "bin" / "run.sh", 0o755)
    brun("tag", str(bproj), "--apply")
    bstore = bhome / ".claude" / "projects" / enc(str(bproj))
    bstore.mkdir(parents=True)
    T1 = "".join(json.dumps(e) + "\n" for e in (
        {"type": "user", "cwd": str(bproj), "version": "9.9.9",
         "message": {"role": "user", "content": "refactor the checkout flow"}},
        {"type": "ai-title", "aiTitle": "Checkout flow refactor"}))
    (bstore / "s1.jsonl").write_text(T1)
    brun("tag", str(bproj), "--apply")
    uid = read_text_or_none(bproj / ".aht" / ".project-id")
    (bhome / ".claude.json").write_text(json.dumps(
        {"projects": {str(bproj): {"hasTrustDialogAccepted": True}}}))
    here = str(phome / "code" / "shop")

    d = prun("bring", "--from", "box", "--list", "--json")
    fx += fx7(d, "bring_list.json")
    row = next((p for p in d.get("projects") or [] if p["path"] == "/home/code/shop"), {})
    ck(row.get("can_bring") and row.get("here_path") == here and row.get("uuid") == uid
       and row.get("state") == "home" and (row.get("session") or {}).get("title")
       == "Checkout flow refactor",
       f"bring --list: box's projects, each with where it would go here ({row})")
    fx += fx7(prun("bring", "/home/code/shop", "--from", "box", "--json",
                   AHT_AS_WINDOWS="1"), "bring_dry.json")         # as a PC asks
    d = prun("bring", "/home/code/shop", "--from", "box", "--json")
    ck(not d.get("applied") and not d.get("blockers") and d.get("here_path") == here
       and d.get("there_path") == "/home/code/shop" and d.get("plan", {}).get("files") == 5
       and d.get("session", {}).get("id") == "s1" and not os.path.exists(here)
       and not (phome / ".aht" / "machine.json").exists(),
       f"bring dry run: what would come and where, nothing written ({d.get('plan') or d})")

    # the identity check here: another folder in the way
    (phome / "code" / "shop").mkdir(parents=True)
    (phome / "code" / "shop" / "mine.txt").write_text("mine\n")
    d = prun("bring", "/home/code/shop", "--from", "box", "--json")
    ck(any("holds another folder (1 item)" in b and "--here " in b
           for b in d.get("blockers", [])) and d.get("identity", {}).get("ok") is False
       and d["identity"].get("fix") == f"aht bring /home/code/shop --from box --here {here}-box",
       f"bring: a folder here that holds something else blocks ({d.get('blockers')})")
    shutil.rmtree(phome / "code" / "shop")

    # an idle session open there blocks, unless --allow-idle
    sessions = bhome / ".claude" / "sessions"
    sessions.mkdir(exist_ok=True)
    sleeper = subprocess.Popen(["sleep", "600"], cwd="/")
    (sessions / f"{sleeper.pid}.json").write_text(json.dumps(
        {"pid": sleeper.pid, "cwd": str(bproj), "status": "idle", "sessionId": "s1"}))
    d1 = prun("bring", "/home/code/shop", "--from", "box", "--json")
    d2 = prun("bring", "/home/code/shop", "--from", "box", "--allow-idle", "--json")
    ck(any("exit it first" in b and "--allow-idle" in b for b in d1.get("blockers", []))
       and not d2.get("blockers")
       and any("Send Back keeps both versions" in w for w in d2.get("warnings", [])),
       f"bring: an idle session there blocks, --allow-idle brings it anyway "
       f"({d1.get('blockers')}, {d2.get('warnings')})")
    sleeper.kill(); sleeper.wait()
    (sessions / f"{sleeper.pid}.json").unlink()

    # names a Windows PC cannot hold (this machine counted as Windows)
    (bproj / "aux.md").write_text("x\n")
    (bproj / "a:b.txt").write_text("x\n")
    d = prun("bring", "/home/code/shop", "--from", "box", "--json", AHT_AS_WINDOWS="1")
    fx += fx7(d, "handover_blocked_names.json")
    kinds = {r["kind"]: r["names"] for r in d.get("names") or []}
    ck(kinds.get("reserved") == [["aux.md"]] and kinds.get("windows_char") == [["a:b.txt"]]
       and any("cannot hold" in b and "handover_excludes" in b for b in d.get("blockers", []))
       and d.get("modes_lost") == ["bin/run.sh"],
       f"bring to a PC: aux.md and a:b.txt block, run.sh would lose its mark ({d.get('names')})")
    (bproj / "aux.md").unlink()
    (bproj / "a:b.txt").unlink()

    # cut off after the files came: box forgets the attempt again (unmark)
    d = prun("bring", "/home/code/shop", "--from", "box", "--apply", "--json",
             AHT_TEST_DROP="fetched")
    e = breg().get(uid) or {}
    ck(d.get("error") and not d.get("applied") and not e.get("handing") and not e.get("away")
       and not copies() and any("keeps the project" in w for w in d.get("warnings", [])),
       f"bring cut off: unmark there, nothing is marked anywhere ({d.get('error')}, "
       f"{d.get('warnings')})")

    # Bring Here, as a PC
    tlog.write_text("") if tlog.exists() else None
    d = prun("bring", "/home/code/shop", "--from", "box", "--apply", "--json",
             AHT_AS_WINDOWS="1")
    fx += fx7(d, "bring_apply.json")
    e = breg().get(uid) or {}
    a = e.get("away") or {}
    c = copies().get(here) or {}
    pstore = pclaude / enc(here)
    term = read_text_or_none(tlog) or ""
    ck(d.get("applied") and (Path(here) / "src" / "app.py").read_text() == "print(1)\n"
       and (pstore / "s1.jsonl").read_text() == T1
       and a.get("driven_by") == "there" and a.get("holder") == "pc"
       and a.get("remote_path") == here and a.get("attempt") == d.get("attempt")
       and not e.get("handing") and c.get("kind") == "brought" and c.get("from") == "box"
       and c.get("uuid") == uid,
       f"bring --apply: the project and its history here (under this path's key), box "
       f"records it as here, this machine notes the copy ({d.get('error') or a})")
    ck("claude" in term and "--resume s1" in term and "GIT_CONFIG_KEY_0=core.filemode" in term
       and d.get("opened") and any(json.loads(f.read_text()).get("kind") == "bring"
                                   for f in (Path(here) / ".aht" / "handover").glob("relay-*.json")),
       f"bring: the session opens here with git's settings for a PC, a relay of kind bring "
       f"({term.strip()[-160:]})")
    ck(json.loads((pclaude.parent.parent / ".claude.json").read_text()).get("projects", {})
       .get(here, {}).get("hasTrustDialogAccepted") is True,
       "bring: the folder trusted there is trusted here")
    bm = json.loads((bhome / ".aht" / "handover" / uid / "manifest.json").read_text())
    ck(bm.get("attempt") == d.get("attempt") and "src/app.py" in bm["here"]["project"]
       and bm.get("transcripts", {}).get("s1.jsonl", [0])[0] == len(T1.encode())
       and bm.get("modes", {}).get("project", {}).get("bin/run.sh") == 0o755,
       "box keeps the record of what left: the lists, the transcripts' checksums, the modes")
    hk = subprocess.run([PY, LAUNCH, "hook"], env=penv, capture_output=True, text=True,
                        input=json.dumps({"cwd": here})).stdout
    ck("brought here from “box”" in hk and "send it back when done" in hk,
       f"the hook tells a session here where the folder came from ({hk.strip()[-200:]})")
    brow = next((r for r in json.loads(brun("projects", "--json").stdout)["projects"]
                 if r["uuid"] == uid), {})
    prow = next((r for r in prun("projects", "--json").get("projects", [])
                 if r["real_path"] == here), {})
    fx += fx7(brow, "projects.json", "home") + fx7(prow, "projects.json", "brought")
    ck(brow.get("away_driven_by") == "there" and brow.get("away_holder") == "pc"
       and brow.get("away_path") == here
       and (prow.get("copy_of") or {}).get("kind") == "brought"
       and (prow.get("copy_of") or {}).get("remote") == "box",
       f"projects: box shows it on pc, brought there; pc shows a brought copy ({prow.get('copy_of')})")
    d = J(brun("reclaim", str(bproj), "--json"))
    ck(any("send it back from pc" in b for b in d.get("blockers", [])),
       f"box cannot take back what pc brought: Send Back there, or Release ({d.get('blockers')})")

    # work on both machines
    Path(here, "src", "app.py").write_text("print('pc')\n")
    (bproj / "src" / "app.py").write_text("print('box')\n")
    Path(here, "README.md").write_bytes(b"line one\r\nline two\r\n")       # endings only
    Path(here, "docs", "notes.txt").write_bytes(b"a\r\nb\r\nc\r\n")        # changed, flipped
    Path(here, "bin", "run.sh").write_text("#!/bin/sh\necho run 2\n")
    os.chmod(Path(here, "bin", "run.sh"), 0o644)                           # as a PC has it
    Path(here, "src", "new.py").write_text("new\n")
    with open(pstore / "s1.jsonl", "a") as fh:
        fh.write(json.dumps({"type": "user", "version": "9.9.9", "message": {
            "role": "user", "content": "done on pc"}}) + "\n")

    # Send Back: a copy from another attempt is refused
    cf = phome / ".aht" / "remote" / "copies.json"
    keep = cf.read_text()
    cc = json.loads(keep)
    cc[here]["attempt"] = "20200101-000000-dead"
    cf.write_text(json.dumps(cc))
    d = prun("send-back", here, "--json", AHT_AS_WINDOWS="1")
    ck(d.get("error") and "another handover" in d["error"] and not d.get("applied"),
       f"send-back: a copy from another attempt is refused ({d.get('error')})")
    cf.write_text(keep)

    # a newer Claude Code wrote here: blocked, unless --ignore-version
    with open(pstore / "s1.jsonl", "a") as fh:
        fh.write(json.dumps({"type": "assistant", "version": "99.0.0", "message": {
            "role": "assistant", "content": "ok"}}) + "\n")
    d1 = prun("send-back", here, "--json", AHT_AS_WINDOWS="1")
    d = prun("send-back", here, "--ignore-version", "--json", AHT_AS_WINDOWS="1")
    fx += fx7(d, "send_back_dry.json")
    ck(any("Claude Code 99.0.0 was used on pc, box has 9.9.9" in b for b in d1.get("blockers", []))
       and not d.get("blockers") and d.get("warnings"),
       f"send-back: a newer Claude Code blocks; --ignore-version lets it go ({d1.get('blockers')})")
    pl = d.get("plan") or {}
    ck(d.get("eol_only") == ["README.md"] and d.get("eol_kept") == ["docs/notes.txt"]
       and d.get("conflicts") == {"project": ["src/app.py"]}
       and pl.get("history", {}).get("take") == 1 and pl.get("project", {}).get("new", 0) >= 1
       and not d.get("applied"),
       f"send-back dry run: endings only stay there, a flipped file keeps box's style, a "
       f"change on both is kept twice ({d.get('eol_only')}, {d.get('eol_kept')}, "
       f"{d.get('conflicts')}, {pl})")
    d = prun("send-back", here, "--ignore-version", "--apply", "--json", AHT_AS_WINDOWS="1")
    fx += fx7(d, "send_back_apply.json")
    e = breg().get(uid) or {}
    day = time.strftime("%Y-%m-%d")
    twin = bproj / "src" / f"app (from pc {day}).py"
    ck(d.get("applied") and not e.get("away") and (e.get("returned") or {}).get("sent_back")
       and (bproj / "src" / "app.py").read_text() == "print('box')\n"
       and twin.is_file() and twin.read_text() == "print('pc')\n"
       and (bproj / "README.md").read_bytes() == b"line one\nline two\n"
       and (bproj / "docs" / "notes.txt").read_bytes() == b"a\nb\nc\n"
       and (bproj / "src" / "new.py").read_text() == "new\n"
       and "done on pc" in (bstore / "s1.jsonl").read_text()
       and (copies().get(here) or {}).get("kind") == "returned",
       f"send-back --apply: home places it, a change on both kept twice, line endings kept, "
       f"the conversation goes on there; the copy here is a returned one "
       f"({d.get('error') or d.get('done')})")
    ck(stat_mode(bproj / "bin" / "run.sh") == 0o755
       and "run 2" in (bproj / "bin" / "run.sh").read_text(),
       f"modes: run.sh comes back from a PC with its new content and keeps 0755 "
       f"({oct(stat_mode(bproj / 'bin' / 'run.sh'))})")
    ret = e.get("returned") or {}
    ck(ret.get("eol_only") == ["README.md"] and ret.get("eol_kept") == ["docs/notes.txt"]
       and d.get("set_aside") and Path(d["set_aside"]).is_dir(),
       f"returned: what stayed for its line endings, and the set-aside folder there ({ret})")

    # Release at home ends a bring that will not come back
    d = prun("bring", "/home/code/shop", "--from", "box", "--apply", "--no-open", "--json")
    d1 = J(brun("reclaim", str(bproj), "--release", "--json"))
    out1 = brun("reclaim", str(bproj), "--release").stdout
    d2 = J(brun("reclaim", str(bproj), "--release", "--apply", "--json"))
    d3 = prun("send-back", here, "--json")
    e = breg().get(uid) or {}
    ck(d.get("applied") and d1.get("remote") == "pc" and "stays on pc" in out1
       and d2.get("released") and not e.get("away")
       and d3.get("error") and "not away from box" in d3["error"],
       f"Release at home: the work on pc stays there, and Send Back is refused after "
       f"({d.get('error')}, {out1.strip()[-120:]}, {d3.get('error')})")

    # a session title with a key in it is masked there: in Bring Here's list,
    # its dry run and Send Back's answer
    KEY7 = "sk-" + "ant-" + "api03-" + "Zr4" * 12        # made up, built in pieces
    with open(bstore / "s1.jsonl", "a") as fh:
        fh.write(json.dumps({"type": "ai-title", "aiTitle": "Ship it with " + KEY7}) + "\n")
    dl = praw("bring", "--from", "box", "--list", "--json").stdout
    dd = praw("bring", "/home/code/shop", "--from", "box", "--json").stdout
    ck(KEY7 not in dl and KEY7 not in dd and "Ship it with [" in dl and "Ship it with [" in dd,
       f"a session title is masked there, for Bring Here's list and dry run ({dd[-200:]})")

    # the link drops once box noted the bring (mark-away): asked again, still
    # cut off, the run says so and notes nothing here; the same Bring Here
    # run again asks box, which answers that it was done, and finishes it
    # here without copying anything again
    d = prun("bring", "/home/code/shop", "--from", "box", "--apply", "--no-open", "--json",
             AHT_TEST_DROP="mark-away")
    a1 = ((breg().get(uid) or {}).get("away") or {}).get("attempt")
    ck(d.get("error") and "Run the same Bring Here again" in d["error"] and not d.get("applied")
       and a1 and (copies().get(here) or {}).get("attempt") != a1,
       f"bring cut off after box noted it: box has it as here, nothing noted here yet "
       f"({d.get('error')}, {a1})")
    d2 = prun("bring", "/home/code/shop", "--from", "box", "--json")
    d3 = prun("bring", "/home/code/shop", "--from", "box", "--apply", "--no-open", "--json")
    c = copies().get(here) or {}
    ck(d2.get("finish") == a1 and not d2.get("applied") and not d2.get("blockers")
       and d3.get("applied") and d3.get("attempt") == a1
       and any(f"already done for attempt {a1}" in w for w in d3.get("warnings", []))
       and c.get("kind") == "brought" and c.get("attempt") == a1
       and ((breg().get(uid) or {}).get("away") or {}).get("attempt") == a1
       and any(r["real_path"] == here and r.get("copy_of")
               for r in prun("projects", "--json").get("projects", [])),
       f"bring again: box answers that it was done, and this machine finishes its side "
       f"({d2.get('finish')}, {d3.get('error') or d3.get('warnings')})")
    d4 = prun("bring", "/home/code/shop", "--from", "box", "--apply", "--no-open", "--json")
    ck(not d4.get("applied") and any("it is here already" in b for b in d4.get("blockers", [])),
       f"bring once more: it is here already ({d4.get('blockers')})")
    # …and once the files went back (return-apply): asked again, box says it
    # has it back, and this machine finishes its side in the same run
    Path(here, "src", "dropped.py").write_text("after the drop\n")
    d = prun("send-back", here, "--apply", "--json", AHT_TEST_DROP="return-apply")
    e = breg().get(uid) or {}
    ret = e.get("returned") or {}
    ck(d.get("applied") and d.get("already") == f"already done for attempt {a1}"
       and not e.get("away") and ret.get("attempt") == a1 and ret.get("sent_back")
       and (bproj / "src" / "dropped.py").read_text() == "after the drop\n"
       and (copies().get(here) or {}).get("kind") == "returned"
       and KEY7 not in json.dumps(d) and "Ship it with [" in str(d.get("session_title")),
       f"send-back cut off after box placed the files: asked again, box says it is done; the "
       f"copy here is a returned one; the title came masked ({d.get('error') or d.get('already')})")
    # …and when that answer was lost too: the same Send Back run again
    cc = json.loads(cf.read_text())
    cc[here]["kind"] = "brought"
    cf.write_text(json.dumps(cc))
    d5 = prun("send-back", here, "--json")
    k5 = (copies().get(here) or {}).get("kind")
    d6 = prun("send-back", here, "--apply", "--json")
    ck(d5.get("already") and not d5.get("applied") and k5 == "brought"
       and d6.get("applied") and d6.get("already")
       and (copies().get(here) or {}).get("kind") == "returned"
       and (breg().get(uid) or {}).get("returned", {}).get("attempt") == a1,
       f"send-back again: box answers that it was done, nothing is sent, this machine notes "
       f"it ({d5.get('already')}, {d6.get('error') or d6.get('already')})")

    # Bring Here of a project with no Claude history there (both movers), and
    # what earlier Bring Heres set aside here is pruned as replaced/ is
    def stamp7(days):
        return time.strftime("%Y%m%d-%H%M%S", time.localtime(time.time() - days * 86400))
    nproj = bhome / "code" / "nohist"
    nproj.mkdir(parents=True)
    (nproj / "a.txt").write_text("a\n")
    brun("tag", str(nproj), "--apply")
    nuid = read_text_or_none(nproj / ".aht" / ".project-id")
    nhere = phome / "code" / "nohist"
    bdir = phome / ".aht" / "handover" / str(nuid) / "brought"
    olds = {days: stamp7(days) for days in (2, 31, 32, 33, 34, 35, 36, 37)}
    for name in olds.values():
        (bdir / name / "project").mkdir(parents=True)
        (bdir / name / "project" / "x.txt").write_text("x")
    d = prun("bring", "/home/code/nohist", "--from", "box", "--apply", "--no-open", "--json")
    left = sorted(p.name for p in bdir.iterdir()) if bdir.is_dir() else []
    ck(d.get("applied") and (nhere / "a.txt").read_text() == "a\n"
       and (d.get("fetched") or {}).get("history_bytes") == 0
       and not (pclaude / enc(str(nhere))).exists(),
       f"bring: a project with no Claude history there comes without one "
       f"({os.environ.get('AHT_TRANSFER')}: {d.get('error') or d.get('fetched')})")
    ck(all(olds[x] in left for x in (2, 31, 32, 33, 34))
       and not any(olds[x] in left for x in (35, 36, 37)),
       f"bring: brought/ keeps the newest 5 folders and every one younger than 30 days ({left})")
    J(brun("reclaim", str(nproj), "--release", "--apply", "--json"))

    # Hand Over from here to box below its home folder; Take Back as a PC
    projH = phome / "code" / "hand"
    (projH / "bin").mkdir(parents=True)
    (projH / "a.txt").write_text("one\ntwo\n")
    (projH / "desktop.ini").write_text("[x]\n")
    (projH / "Thumbs.db").write_text("x")
    (projH / "bin" / "run.sh").write_text("#!/bin/sh\n")
    os.chmod(projH / "bin" / "run.sh", 0o755)
    hstore = pclaude / enc(str(projH))
    hstore.mkdir(parents=True)
    (hstore / "s2.jsonl").write_text(json.dumps({"type": "user", "cwd": str(projH),
                                                 "version": "9.9.9", "message": {
                                                     "role": "user", "content": "hi"}}) + "\n")
    fh_dir = pclaude.parent / "file-history" / "s2"
    fh_dir.mkdir(parents=True)
    (fh_dir / "snap@v1").write_text("old\n")
    prun("tag", str(projH), "--apply")
    farH = box / "home" / "code" / "hand"
    d = prun("handover", str(projH), "--to", "box", "--json")
    ck(not d.get("blockers") and d.get("there_path") == "/home/code/hand"
       and d.get("here_path") == str(projH) and d.get("identity", {}).get("ok"),
       f"hand over: below box's home folder ({d.get('blockers') or d.get('there_path')})")
    d = prun("handover", str(projH), "--to", "box", "--apply", "--json")
    a = (prun("projects", "--json").get("projects") and next(
        (r for r in prun("projects", "--json")["projects"] if r["real_path"] == str(projH)), {}))
    rstoreH = bhome / ".claude" / "projects" / enc(str(farH))
    notes = list((bhome / ".aht" / "remote" / "run").glob("*/note.txt"))
    note = max(notes, key=lambda p: p.stat().st_mtime).read_text() if notes else ""
    ck(d.get("applied") and (farH / "a.txt").is_file() and not (farH / "desktop.ini").exists()
       and not (farH / "Thumbs.db").exists() and (rstoreH / "s2.jsonl").is_file()
       and not (bhome / ".claude" / "file-history" / "s2").exists()
       and a.get("away_path") == str(farH) and stat_mode(farH / "bin" / "run.sh") == 0o755,
       f"hand over: the history under the path there, no /rewind snapshots on another path, "
       f"Windows' own files stay ({d.get('error') or a.get('away_path')})")
    ck("the folder is at /home/code/hand here (it was " + str(projH) + " on pc)" in note,
       f"the arrival note names both paths ({note[:300]})")
    # done there: endings only, a name a PC cannot hold, and a path too long
    # for a PC without long paths
    (farH / "a.txt").write_bytes(b"one\r\ntwo\r\n")
    (farH / "a:b.txt").write_text("made there\n")
    longH = "deep/" + "d" * max(10, min(200, 262 - len(str(projH)) - 26)) \
        + "/notes about the trip.txt"
    (farH / longH).parent.mkdir(parents=True)
    (farH / longH).write_text("far\n")
    d = prun("reclaim", str(projH), "--stop", "--apply", "--json", AHT_AS_WINDOWS="1",
             AHT_SHORT_PATHS="1")
    un = d.get("unsafe_names") or [{}]
    ck(d.get("applied") and (projH / "a.txt").read_bytes() == b"one\ntwo\n"
       and d.get("eol_only") == ["a.txt"] and not (projH / "a:b.txt").exists()
       and un[0].get("there") == "a:b.txt" and un[0].get("kept_as", "").endswith(
           "kept-aside/a%3Ab.txt") and Path(un[0]["kept_as"]).read_text() == "made there\n",
       f"take back as a PC: endings only stay, a:b.txt is kept aside as a%3Ab.txt "
       f"({d.get('error') or d.get('blockers') or un})")
    lk = next((u for u in un if u.get("there") == longH), {})
    ck(lk.get("kept_as", "").endswith("kept-aside/1-notes about the trip.txt")
       and Path(lk["kept_as"]).read_text() == "far\n" and not (projH / longH).exists(),
       f"take back as a PC without long paths: a path too long here is kept aside under a "
       f"short name, its own name listed ({lk or un})")

    # names Windows cannot hold, with the probe's answer saying Windows there
    projW = phome / "code" / "win"
    projW.mkdir(parents=True)
    for n in ("aux.md", "a:b.txt", "trail.", "ok.txt"):
        (projW / n).write_text("x\n")
    os.symlink("ok.txt", projW / "lnk")
    fake = ("import json, sys, aht\n"
            "orig = aht.Remote.connect\n"
            "def connect(self, path=None, fs=False):\n"
            "    info = orig(self, path, fs)\n"
            "    info['system'] = 'Windows'\n"
            "    info['fs'] = dict(info.get('fs') or {}, symlinks=False)\n"
            "    return info\n"
            "aht.Remote.connect = connect\n"
            "sys.exit(aht.main(['handover', sys.argv[1], '--to', 'box', '--json']))\n")
    r = subprocess.run([PY, "-c", fake, str(projW)], capture_output=True, text=True,
                       env=dict(penv, PYTHONPATH=str(HERE.parent)))
    d = J(r)
    kinds = {x["kind"]: [n[0] for n in x["names"]] for x in d.get("names") or []}
    ck(kinds == {"windows_char": ["a:b.txt"], "trailing": ["trail."], "reserved": ["aux.md"],
                 "symlink": ["lnk"]}
       and any("cannot hold" in b for b in d.get("blockers", [])) and not d.get("applied"),
       f"name blockers when the probe says Windows: a:b.txt, trail., aux.md, a link "
       f"({kinds or d})")

    # outside the home folder: refused, with the rule that would help
    projO = base7 / "outside"
    projO.mkdir()
    (projO / "x.txt").write_text("x\n")
    d = prun("handover", str(projO), "--to", "box", "--json")
    ck(any("is outside yours" in b and "aht remote paths box --add" in b
           for b in d.get("blockers", [])),
       f"a project outside every mapped folder is refused ({d.get('blockers')})")

    # identity refusals on Hand Over: another folder there; box's own project
    projI = phome / "code" / "idt"
    projI.mkdir(parents=True)
    (projI / "x.txt").write_text("x\n")
    prun("tag", str(projI), "--apply")
    farI = bhome / "code" / "idt"
    (farI / ".aht").mkdir(parents=True)
    (farI / ".aht" / ".project-id").write_text("0" * 32)
    (farI / "theirs.txt").write_text("t\n")
    d1 = prun("handover", str(projI), "--to", "box", "--json")
    shutil.rmtree(farI)
    shutil.copytree(projI, farI)
    brun("tag", str(farI), "--apply")
    d2 = prun("handover", str(projI), "--to", "box", "--json")
    ck(any("on box, /home/code/idt holds another folder (2 items)" in b
           for b in d1.get("blockers", []))
       and (d1.get("identity") or {}).get("fix")
       == f"aht remote paths box --add {phome / 'code'} /home/code/pc"
       and any("is a live project of its own there" in b for b in d2.get("blockers", [])),
       f"identity: another folder there, or box's own live project, blocks a hand over "
       f"({d1.get('blockers')}, {d2.get('blockers')})")
    # …unless this machine's records say the project came home from that very
    # folder there: its `returned`, the lists of the last time both copies
    # agreed (there/box.json), or a record of what left
    iuid = read_text_or_none(projI / ".aht" / ".project-id")
    regp = phome / ".aht" / "registry.json"
    def set_returned(rec):
        rg = json.loads(regp.read_text())
        rg["projects"][iuid]["returned"] = rec
        regp.write_text(json.dumps(rg))
    own = lambda dd: any("is a live project of its own there" in b
                         for b in dd.get("blockers", []))
    set_returned({"from": "box", "at": "2026-10-20T10:00:00", "mode": "away",
                  "from_path": "/home/code/idt", "session": None})
    d3 = prun("handover", str(projI), "--to", "box", "--json")
    set_returned({"from": "lab", "at": "2026-10-20T10:00:00", "mode": "away",
                  "from_path": "/home/code/idt", "session": None})
    d4 = prun("handover", str(projI), "--to", "box", "--json")
    set_returned(None)
    thd = phome / ".aht" / "handover" / str(iuid) / "there"
    thd.mkdir(parents=True)
    (thd / "box.json").write_text(json.dumps({"v": 2, "kind": "take-back", "remote": "box",
                                              "there": {},
                                              "remote_path": str(box) + "/home/code/idt"}))
    d5 = prun("handover", str(projI), "--to", "box", "--json")
    (thd / "box.json").write_text(json.dumps({"v": 2, "kind": "sync", "remote": "box",
                                              "there": {},
                                              "remote_path": str(box) + "/home/code/idt"}))
    d6 = prun("handover", str(projI), "--to", "box", "--json")
    shutil.rmtree(thd)
    ck(not own(d3) and (d3.get("identity") or {}).get("ok")
       and any("it came back from there" in w for w in d3.get("warnings", []))
       and own(d4) and not own(d5) and own(d6),
       f"identity: box's aht lists it as its own, but it came back from that folder there "
       f"(returned, or there/box.json of a take-back): Hand Over goes into it; from another "
       f"machine, or after a sync only, it does not ({d3.get('blockers')}, "
       f"{d4.get('blockers')}, {d5.get('blockers')}, {d6.get('blockers')})")
    # what aht 0.13.0 left: the same path there, a `returned` without a mode
    # or the path there, named after the host; or only its record of what left
    projK = phome / "old13" / "k"
    projK.mkdir(parents=True)
    (projK / "x.txt").write_text("x\n")
    prun("tag", str(projK), "--apply")
    kuid = read_text_or_none(projK / ".aht" / ".project-id")
    prun("remote", "paths", "box", "--add", str(projK.parent), str(projK.parent))
    farK = Path(str(box) + str(projK))
    shutil.copytree(projK, farK)
    brun("tag", str(farK), "--apply")
    k1 = prun("handover", str(projK), "--to", "box", "--json")
    rg = json.loads(regp.read_text())
    rg["projects"][kuid]["returned"] = {
        "from": __import__("platform").node().split(".")[0], "left": "2026-10-01T09:00:00",
        "at": "2026-10-02T09:00:00", "session": None, "handed_over": None, "updated": 0,
        "new": 0, "deleted": 0, "conflicts": []}
    regp.write_text(json.dumps(rg))
    k2 = prun("handover", str(projK), "--to", "box", "--json")
    rg["projects"][kuid].pop("returned")
    regp.write_text(json.dumps(rg))
    khd = phome / ".aht" / "handover" / str(kuid)
    khd.mkdir(parents=True, exist_ok=True)
    (khd / "manifest-20261001-090000.json").write_text(json.dumps(
        {"uuid": kuid, "project": str(projK), "remote": "box", "at": "2026-10-01T09:00:00",
         "here": {}, "there": {}, "transcripts": {}}))
    k3 = prun("handover", str(projK), "--to", "box", "--json")
    prun("remote", "paths", "box", "--remove", str(projK.parent))
    ck(own(k1) and not own(k2) and not own(k3) and k2.get("there_path") == str(projK),
       f"identity: a copy aht 0.13.0 left at the same path there goes on with Hand Over after "
       f"the update ({k1.get('blockers')}, {k2.get('blockers')}, {k3.get('blockers')})")

    # a claude there that gives no version: blocked, no install planned
    projC = phome / "code" / "cver"
    projC.mkdir(parents=True)
    (projC / "x.txt").write_text("x\n")
    prun("tag", str(projC), "--apply")
    noversion = ("import sys, aht\n"
                 "orig = aht.Remote.connect\n"
                 "def connect(self, path=None, fs=False):\n"
                 "    info = orig(self, path, fs)\n"
                 "    info['claude'], info['claude_version'] = '/opt/x/claude', None\n"
                 "    return info\n"
                 "aht.Remote.connect = connect\n"
                 "sys.exit(aht.main(['handover', sys.argv[1], '--to', 'box', '--json']))\n")
    d = J(subprocess.run([PY, "-c", noversion, str(projC)], capture_output=True, text=True,
                         env=dict(penv, PYTHONPATH=str(HERE.parent))))
    ck(any("Claude Code on box did not answer `claude --version`" in b
           for b in d.get("blockers", []))
       and not (d.get("plan") or {}).get("install_claude"),
       f"a Claude Code there that gives no version blocks, rather than an install every time "
       f"({d.get('blockers')})")

    # a project a PC handed over: box sends it back only to a PC set up there
    # (one that answers; see [17h]), its copy row says where it came from
    projP = phome / "code" / "frompc"
    projP.mkdir(parents=True)
    (projP / "x.txt").write_text("x\n")
    prun("tag", str(projP), "--apply")
    d = prun("handover", str(projP), "--to", "box", "--apply", "--no-start", "--json",
             AHT_AS_WINDOWS="1")
    farP = bhome / "code" / "frompc"
    db = J(brun("send-back", str(farP), "--json"))
    crow = subprocess.run([PY, "-c", "import sys, json, aht; print(json.dumps("
                           "aht._copy_row(sys.argv[1])))", str(farP)], capture_output=True,
                          text=True, env=dict(benv, PYTHONPATH=str(HERE.parent))).stdout
    crow = json.loads(crow) if crow.strip().startswith("{") else {}
    ck(d.get("applied") and any("pc is not set up on this machine" in b and "OpenSSH Server" in b
                                and "or take it back on pc" in b
                                for b in db.get("blockers", []))
       and crow.get("system") == "Windows" and crow.get("kind") == "handover",
       f"send-back of what a PC handed over, the PC not set up here: add it (it needs OpenSSH "
       f"Server), or take it back on pc; its copy row names "
       f"the PC's system ({d.get('error') or db.get('blockers')}, {crow})")

    # git: a PC with autocrlf on hands over; .git/config stays as it is
    projG = phome / "code" / "gitp"
    projG.mkdir(parents=True)
    (projG / "f.txt").write_text("x\n")
    if shutil.which("git"):
        subprocess.run(["git", "init", "-q", str(projG)], capture_output=True)
        subprocess.run(["git", "-C", str(projG), "config", "core.autocrlf", "true"],
                       capture_output=True)
        gc = (projG / ".git" / "config").read_bytes()
        prun("tag", str(projG), "--apply")
        d = prun("handover", str(projG), "--to", "box", "--json", AHT_AS_WINDOWS="1")
        d2 = prun("handover", str(projG), "--to", "box", "--apply", "--json",
                  AHT_AS_WINDOWS="1")
        cmds = [p.read_text() for p in (bhome / ".aht" / "remote" / "run").glob("*/command.txt")]
        cmd = next((c for c in cmds if "/home/code/gitp" in c), "")
        ck(d.get("git", {}).get("suggest") == ["* text=auto", "*.sh text eol=lf",
                                               "*.bat text eol=crlf", "*.cmd text eol=crlf",
                                               "*.ps1 text eol=crlf"]
           and not (projG / ".gitattributes").exists() and d2.get("applied")
           and "GIT_CONFIG_KEY_0=core.autocrlf GIT_CONFIG_VALUE_0=true" in cmd
           and (projG / ".git" / "config").read_bytes() == gc
           and (box / "home" / "code" / "gitp" / ".git" / "config").read_bytes() == gc,
           f"git: the .gitattributes lines are suggested, never written; the session there "
           f"gets core.autocrlf through GIT_CONFIG_*; no .git/config is edited ({cmd[:200]})")
    else:
        print("  SKIP git is not installed: the git settings test needs it")
    ck(not fx, f"the phase-7 JSON keeps the shape of tests/fixtures/phase7 ({fx})")
    for w in (bhome / ".faketmux").glob("*.json"):   # the stand-in sessions
        rec = json.loads(w.read_text())
        if rec.get("alive"):
            try:
                os.kill(int(rec["pid"]), 15)
            except OSError:
                pass
