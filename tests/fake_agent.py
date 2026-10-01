#!/usr/bin/env python3
"""A stand-in agent for the second-opinion tests: `fake_agent.py NAME -p TASK …`
works on the copy it runs in (appends a line to a.py; Kimi also leaves a
notes file) and answers the way the real CLI's print mode does."""
import json, sys

who, args = sys.argv[1], sys.argv[2:]
if who == "kimi" and ("-y" in args or "--yolo" in args):
    sys.exit("error: Cannot combine --prompt with --yolo.")     # as Kimi Code 2 says
task = args[args.index("-p") + 1]
with open("a.py", "a") as fh:
    fh.write(f"# {who} did: {task.splitlines()[0]}\n")
if who == "kimi":
    with open("notes.txt", "w") as fh:
        fh.write("what Kimi thought\n")
    print("Kimi: added a line and a notes file.")
else:
    print(json.dumps({"result": "Claude: added a line.", "total_cost_usd": 0.01,
                      "usage": {"input_tokens": 10, "output_tokens": 5}}))
