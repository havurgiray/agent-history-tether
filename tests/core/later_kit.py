"""What [16] to [20] of tests/core_test.py leave in the sandbox that the
later sections read, rebuilt for a unit that needs it ([18], [19], [20],
[22]).  Each function is the earlier section's own setup code, copied as it
is there, without its checks; a unit calls only the ones its checks need.
Not a unit: its name starts with no digit."""
from common import *  # noqa: F401,F403  (this unit's sandbox, run, enc, iso, KEY, ...)


def across_made():
    """[17]: the project "Across" (projX) with a Claude Code session that
    holds a key (c1, "Pelican deploy"), a Kimi Code session and a Codex one,
    tagged -> (projX, T, cstore, cline)."""
    projX = os.path.realpath(str(roots / "Across"))
    os.makedirs(projX)
    Path(projX, "app.py").write_text("print('hi')\n")
    # noon three days ago: the sessions below sit seconds apart on two days,
    # and the journal counts days, so no offset may cross a midnight
    T = time.mktime(time.localtime(time.time() - 3 * 86400)[:3] + (12, 0, 0, 0, 0, -1))
    cstore = tools / "claude" / enc(projX)
    cstore.mkdir()
    def cline(**kw):
        return json.dumps(dict({"cwd": projX, "entrypoint": "cli"}, **kw)) + "\n"
    (cstore / "c1.jsonl").write_text(
        cline(type="user", timestamp=iso(T), message={"role": "user", "content":
              f"deploy the pelican service, the key is {KEY}"})
        + cline(type="ai-title", aiTitle="Pelican deploy")
        + cline(type="assistant", timestamp=iso(T + 60), message={"role": "assistant", "content": [
            {"type": "text", "text": "The pelican service runs now."},
            {"type": "tool_use", "name": "Edit", "input": {"file_path": projX + "/app.py"}}]}))
    ksd = tools / "kimi-code" / "sessions" / kkey(projX) / "session_k1"
    (ksd / "agents" / "main").mkdir(parents=True)
    (ksd / "state.json").write_text(json.dumps({"id": "session_k1", "cwd": projX, "title":
                                                "Walrus work", "updatedAt": int((T + 86400) * 1000)}))
    (ksd / "agents" / "main" / "wire.jsonl").write_text("".join(json.dumps(e) + "\n" for e in (
        {"type": "turn.prompt", "input": [{"type": "text", "text": "tidy the walrus module"}],
         "origin": {"kind": "user"}, "time": int((T + 86400) * 1000)},
        {"type": "context.append_loop_event", "time": int((T + 86460) * 1000),
         "event": {"type": "content.part", "part": {"type": "text", "text": "The walrus module is tidy."}}},
        {"type": "context.append_loop_event", "time": int((T + 86470) * 1000),
         "event": {"type": "tool.call", "name": "Write", "args": {"file_path": projX + "/walrus.py"}}})))
    day = tools / "codex" / "2026" / "09" / "27"
    day.mkdir(parents=True, exist_ok=True)
    (day / "rollout-across.jsonl").write_text("".join(json.dumps(e) + "\n" for e in (
        {"type": "session_meta", "timestamp": iso(T), "payload": {"id": "cx1", "cwd": projX}},
        {"type": "event_msg", "timestamp": iso(T + 5), "payload": {"type": "user_message",
                                                                   "message": "explain the heron parser"}},
        {"type": "event_msg", "timestamp": iso(T + 9), "payload": {"type": "agent_message",
                                                                   "message": "The heron parser reads tokens."}})))
    os.utime(day / "rollout-across.jsonl", (T + 9, T + 9))
    run("tag", projX, "--apply")
    return projX, T, cstore, cline


def box_set_up():
    """[16] handover_suite's first lines: the stand-in machine "box" (a
    folder with a home of its own), the stand-in tools in sb/stubs, box
    named in the config (as phase5_suite left it) and no keep-awake ->
    (box, stubs, henv)."""
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
    hrun("config", "--set", "remotes=" + json.dumps({"box": {"root": str(box)}}))
    # the stand-in machines are this one: nothing here may keep it awake, and
    # no helper may outlive the test ([17c] tests the keep-awake helper)
    hrun("config", "--set", "handover_keep_awake=false")
    return box, stubs, henv
