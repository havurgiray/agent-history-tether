#!/usr/bin/env python3
"""A stand-in for the Kimi Code CLI in the tests.

`kimi -p PROMPT …` starts a session in the (fake) store for the current
folder, keeps the prompt as its first message and prints the session id the
way the real CLI's stream-json output carries it.  Every call is appended to
$AHT_FAKE_KIMI_LOG."""
import json, os, sys, time, uuid
from pathlib import Path

sys.path.insert(0, os.environ["AHT_CORE_DIR"])
import aht  # noqa: E402  the core's own key function for the store bucket

args = sys.argv[1:]
with open(os.environ["AHT_FAKE_KIMI_LOG"], "a") as fh:
    fh.write(json.dumps({"cwd": os.getcwd(), "args": args}) + "\n")
if "-p" in args:
    prompt = args[args.index("-p") + 1]
    sid = f"session_{uuid.uuid4()}"
    real = os.path.realpath(os.getcwd())
    sd = Path(os.environ["AHT_ROOT_KIMI_CODE"]) / aht._key_kimicode(real) / sid
    (sd / "agents" / "main").mkdir(parents=True)
    now = int(time.time() * 1000)
    (sd / "state.json").write_text(json.dumps({"id": sid, "cwd": real, "createdAt": now,
                                               "updatedAt": now, "title": "taken over"}))
    (sd / "agents" / "main" / "wire.jsonl").write_text(json.dumps(
        {"type": "turn.prompt", "input": [{"type": "text", "text": prompt}],
         "origin": {"kind": "user"}, "time": now}) + "\n")
    print(json.dumps({"type": "session", "sessionId": sid}))
    print(json.dumps({"type": "text", "text": "Understood."}))
