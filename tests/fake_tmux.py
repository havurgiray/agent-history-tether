#!/usr/bin/env python3
"""A stand-in for tmux (and byobu) in the handover tests.

A "window" is a JSON file under $HOME/.faketmux; starting one also starts an
idle process and leaves the per-process record an agent CLI would write, so
aht sees an open session.  Nothing is ever deleted: a window that ended is
marked as ended, and its process is stopped."""
import json, os, subprocess, sys
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

def end(target):
    w = load(target)
    if w.get("alive"):
        try:
            os.kill(int(w["pid"]), 15)
        except OSError:
            pass
        window(target).write_text(json.dumps(dict(w, alive=False)))

def main(argv):
    WINDOWS.mkdir(parents=True, exist_ok=True)
    cmd, rest = (argv[0], argv[1:]) if argv else ("", [])
    opts = {}
    i = 0
    line = ""
    while i < len(rest):
        if rest[i] in ("-s", "-c", "-t", "-x", "-y"):
            opts[rest[i]] = rest[i + 1] if i + 1 < len(rest) else ""
            i += 2
            continue
        if not rest[i].startswith("-"):
            line = rest[i]
        i += 1
    if cmd == "new-session":
        p = subprocess.Popen(["sleep", "600"], cwd="/", stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        window(opts["-s"]).write_text(json.dumps(
            {"pid": p.pid, "alive": True, "path": opts.get("-c"), "command": line}))
        rec = HOME / ".claude" / "sessions"
        rec.mkdir(parents=True, exist_ok=True)
        (rec / f"{p.pid}.json").write_text(json.dumps(
            {"pid": p.pid, "cwd": opts.get("-c"), "sessionId": "s1",
             "status": "idle", "kind": "interactive"}))
        return 0
    if cmd == "has-session":
        return 0 if load(opts.get("-t", "")).get("alive") else 1
    if cmd == "capture-pane":
        print("fake screen")
        return 0
    if cmd in ("send-keys", "kill-session"):        # Ctrl-C ends the session
        end(opts.get("-t", ""))
        return 0
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
