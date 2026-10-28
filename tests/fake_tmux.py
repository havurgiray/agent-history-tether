#!/usr/bin/env python3
"""A stand-in for tmux (and byobu) in the handover tests.

A "window" is a JSON file under $HOME/.faketmux.  For Claude Code, starting
one starts an idle process and leaves the per-process record the CLI would
write, so aht sees an open session.  For another agent (aht's window.json
for the window names it), the window's line runs for real, in the
background, with its output going to $HOME/.faketmux/<name>.out: that is the
window's screen, and the file's time is the window's last activity
(#{window_activity}).  Keys sent to such a window are noted, one per line,
in $HOME/.faketmux/<name>.keys, which the stand-in agent reads (named in its
environment as FAKE_TMUX_KEYS), the way a real agent reads its terminal.
A test may set a window's "activity" in its JSON file to move its clock.

Nothing is ever deleted: a window that ended is marked as ended, and its
processes are stopped.  Every call is noted in $HOME/.faketmux/calls.log,
with the server (-L) it named and the folder its socket would be in
(TMUX_TMPDIR).  With $FAKE_TMUX_FAIL set, every call fails with that text
as its error (a tmux that does not answer properly); a window that is not
there gives tmux's own "can't find session"."""
import json, os, signal, subprocess, sys, time
from pathlib import Path

HOME = Path(os.environ["HOME"])
WINDOWS = HOME / ".faketmux"

def window(target):                 # "=name" names a session, "=name:" its pane
    return WINDOWS / (target.lstrip("=").rstrip(":") + ".json")

def load(target):
    try:
        return json.loads(window(target).read_text())
    except (OSError, ValueError):
        return {}

def alive(w):
    """A window lives while its process does (a real line: until its shell
    ended, a minute after the agent)."""
    if not w.get("alive"):
        return False
    try:
        os.kill(int(w["pid"]), 0)
        return True
    except (OSError, ValueError, KeyError):
        return False

def end(target):
    w = load(target)
    if w.get("alive"):
        try:
            if w.get("runs"):
                os.killpg(int(w["pid"]), signal.SIGTERM)
            else:
                os.kill(int(w["pid"]), 15)
        except OSError:
            pass
        window(target).write_text(json.dumps(dict(w, alive=False)))

def agent_of(name):
    """The agent aht's window.json names for this window (None: Claude Code)."""
    try:
        w = json.loads((HOME / ".aht" / "remote" / "run" / name / "window.json").read_text())
        return w.get("agent") if w.get("agent") != "claude" else None
    except (OSError, ValueError):
        return None

def activity(name, w):
    if w.get("activity") is not None:
        return int(w["activity"])
    try:
        return int((WINDOWS / f"{name}.out").stat().st_mtime)
    except OSError:
        return int(w.get("started") or time.time())

def fmt(text, name, w):
    return (text.replace("#{session_name}", name)
            .replace("#{window_activity}", str(activity(name, w)))
            .replace("#{session_activity}", str(activity(name, w)))
            .replace("#{pane_pid}", str(w.get("pid") or "")))

def main(argv):
    WINDOWS.mkdir(parents=True, exist_ok=True)
    socket = None
    if argv[:1] == ["-L"]:          # a server of its own, as a sandbox asks for
        socket, argv = argv[1], argv[2:]
    with open(WINDOWS / "calls.log", "a") as fh:
        fh.write(json.dumps({"socket": socket, "tmpdir": os.environ.get("TMUX_TMPDIR"),
                             "argv": argv}) + "\n")
    if os.environ.get("FAKE_TMUX_FAIL"):
        print(os.environ["FAKE_TMUX_FAIL"], file=sys.stderr)
        return 1
    cmd, rest = (argv[0], argv[1:]) if argv else ("", [])
    opts = {}
    i = 0
    line, words = "", []
    while i < len(rest):
        if rest[i] in ("-s", "-c", "-t", "-x", "-y", "-F"):
            opts[rest[i]] = rest[i + 1] if i + 1 < len(rest) else ""
            i += 2
            continue
        if not rest[i].startswith("-"):
            line = rest[i]
            words.append(rest[i])
        i += 1
    if cmd == "new-session":
        name = opts["-s"]
        agent = agent_of(name)
        if agent:
            # another agent: its line runs, and what it prints is the screen
            out = open(WINDOWS / f"{name}.out", "w")
            p = subprocess.Popen(["/bin/sh", "-c", line], cwd=opts.get("-c") or "/",
                                 stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                                 start_new_session=True,
                                 env=dict(os.environ, FAKE_TMUX_KEYS=str(WINDOWS / f"{name}.keys")))
            window(name).write_text(json.dumps(
                {"pid": p.pid, "alive": True, "runs": True, "agent": agent,
                 "path": opts.get("-c"), "command": line, "socket": socket,
                 "started": time.time()}))
            return 0
        p = subprocess.Popen(["sleep", "600"], cwd="/", stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        window(name).write_text(json.dumps(
            {"pid": p.pid, "alive": True, "path": opts.get("-c"), "command": line,
             "socket": socket, "started": time.time()}))
        rec = HOME / ".claude" / "sessions"
        rec.mkdir(parents=True, exist_ok=True)
        (rec / f"{p.pid}.json").write_text(json.dumps(
            {"pid": p.pid, "cwd": opts.get("-c"), "sessionId": "s1",
             "status": "idle", "kind": "interactive"}))
        return 0
    if cmd == "has-session":
        t = opts.get("-t", "")
        if alive(load(t)):
            return 0
        print(f"can't find session: {t.lstrip('=').rstrip(':')}", file=sys.stderr)
        return 1
    if cmd in ("display", "display-message"):
        t = opts.get("-t", "")
        w = load(t)
        if not alive(w):
            print(f"can't find session: {t.lstrip('=').rstrip(':')}", file=sys.stderr)
            return 1
        print(fmt(line, t.lstrip("=").rstrip(":"), w))
        return 0
    if cmd in ("list-sessions", "ls"):
        rows = []
        for f in sorted(WINDOWS.glob("*.json")):
            w = load("=" + f.stem)
            if alive(w):
                rows.append(fmt(opts.get("-F") or "#{session_name}: 1 windows", f.stem, w))
        if not rows:
            print("no server running", file=sys.stderr)
            return 1
        print("\n".join(rows))
        return 0
    if cmd == "capture-pane":
        t = opts.get("-t", "")
        name = t.lstrip("=").rstrip(":")
        w = load(t)
        if w.get("runs"):
            try:
                print((WINDOWS / f"{name}.out").read_text(errors="replace")[-4000:])
            except OSError:
                pass
            return 0
        print("fake screen")
        return 0
    if cmd == "send-keys":
        t = opts.get("-t", "")
        w = load(t)
        if w.get("runs"):           # the agent reads them, as from its terminal
            with open(WINDOWS / f"{t.lstrip('=').rstrip(':')}.keys", "a") as fh:
                fh.write("".join(k + "\n" for k in words))
            return 0
        end(t)                      # Claude Code: Ctrl-C ends the session
        return 0
    if cmd == "kill-session":
        end(opts.get("-t", ""))
        return 0
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
