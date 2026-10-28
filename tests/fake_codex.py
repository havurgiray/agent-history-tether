#!/usr/bin/env python3
"""A stand-in for the Codex CLI in the tests.

`codex PROMPT` starts a session: a rollout file in the (fake) store
$AHT_ROOT_CODEX, for the current folder, in the format Codex 0.164 writes.
`codex resume ID PROMPT` adds a turn to that session's rollout.  Each turn
works the way the summaries read it: a patch (apply_patch), a plan
(update_plan) and an answer.  As in a real rollout, what the user and the
agent said is there twice (an `item_completed` event, and a `response_item`
message for the model), among Codex's own instructions and the environment
(developer and environment messages) that aht must not read, and so is
encrypted reasoning.  Each turn starts with a `turn_context` that holds
the approval policy and sandbox the command line asked for (Codex's own
default: on request, in the workspace sandbox), which aht reads for the
permission level.  Every call is appended to $AHT_FAKE_CODEX_LOG;
$AHT_FAKE_CODEX_PATCH names the file the patch changes (default
src/app.py)."""
import json, os, sys, time, uuid
from datetime import datetime, timezone
from pathlib import Path

args = sys.argv[1:]
with open(os.environ["AHT_FAKE_CODEX_LOG"], "a") as fh:
    fh.write(json.dumps({"cwd": os.getcwd(), "args": args}) + "\n")
root = Path(os.environ["AHT_ROOT_CODEX"])
# Codex's own options come before its subcommand or first prompt
flags, i = [], 0
while i < len(args) and args[i].startswith("-") and args[i] != "-":
    takes = args[i] in ("-a", "--ask-for-approval", "-s", "--sandbox", "-c", "--config",
                        "-m", "--model")
    flags += args[i:i + 2] if takes else args[i:i + 1]
    i += 2 if takes else 1
args = args[i:]
approval, sandbox = "on-request", "workspace-write"
for j, f in enumerate(flags):
    val = flags[j + 1] if j + 1 < len(flags) else ""
    if f in ("--dangerously-bypass-approvals-and-sandbox", "--yolo"):
        approval, sandbox = "never", "danger-full-access"
    elif f in ("-a", "--ask-for-approval"):
        approval = val
    elif f in ("-s", "--sandbox"):
        sandbox = val

def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat().replace("+00:00", "Z")

def turn(sid, prompt, t):
    target = os.environ.get("AHT_FAKE_CODEX_PATCH", "src/app.py")
    patch = (f"*** Begin Patch\n*** Update File: {target}\n@@\n-old\n+new\n"
             "*** Add File: src/notes.md\n+notes\n*** End Patch\n")
    plan = {"plan": [{"step": "add a test for it", "status": "pending"},
                     {"step": "fix the parser", "status": "completed"}]}
    answer = "The parser is fixed; a test is still to do."
    tid = str(uuid.uuid4())
    def rec(dt, typ, payload):
        return {"timestamp": iso(t + dt), "type": typ, "payload": payload}
    def said(dt, kind, text):        # what the user or the agent said, as an event
        return rec(dt, "event_msg", {"type": "item_completed", "thread_id": sid, "turn_id": tid,
                                     "item": {"type": kind, "id": str(uuid.uuid4()), "content": [
                                         {"type": "text" if kind == "UserMessage" else "Text",
                                          "text": text}]}})
    def message(dt, role, kind, text):    # … and as the model reads it
        return rec(dt, "response_item", {"type": "message", "role": role,
                                         "content": [{"type": kind, "text": text}]})
    return [rec(0, "event_msg", {"type": "task_started", "turn_id": tid}),
            rec(0, "turn_context", {"cwd": os.getcwd(), "approval_policy": approval,
                                    "sandbox_policy": {"type": sandbox},
                                    "model": "gpt-5-codex", "summary": "auto"}),
            message(0, "developer", "input_text",
                    "<permissions instructions>\nNEVER-READ-INSTRUCTIONS\n</permissions instructions>"),
            message(0, "user", "input_text",
                    f"<environment_context>\n  <cwd>{os.getcwd()}</cwd>\n</environment_context>"),
            message(0, "user", "input_text", prompt),
            said(0, "UserMessage", prompt),
            rec(1, "response_item", {"type": "reasoning", "encrypted_content": "NEVER-READ-REASONING"}),
            rec(1, "response_item", {"type": "custom_tool_call", "name": "apply_patch",
                                     "input": patch}),
            rec(2, "response_item", {"type": "function_call", "name": "update_plan",
                                     "arguments": json.dumps(plan)}),
            said(3, "AgentMessage", answer),
            message(3, "assistant", "output_text", answer),
            rec(3, "event_msg", {"type": "task_complete", "turn_id": tid,
                                 "last_agent_message": answer})]

now = time.time()
if args[:1] == ["resume"]:
    sid, prompt = args[1], (args[2] if len(args) > 2 else "")
    f = next(root.rglob(f"rollout-*{sid}.jsonl"))
    with open(f, "a") as fh:
        fh.write("".join(json.dumps(e) + "\n" for e in turn(sid, prompt, now)))
else:
    sid = str(uuid.uuid4())
    day = root / time.strftime("%Y/%m/%d")
    day.mkdir(parents=True, exist_ok=True)
    meta = {"timestamp": iso(now), "type": "session_meta",
            "payload": {"session_id": sid, "id": sid, "timestamp": iso(now),
                        "cwd": os.path.realpath(os.getcwd()), "originator": "codex_exec",
                        "cli_version": "0.164.0", "source": "exec"}}
    (day / f"rollout-{time.strftime('%Y-%m-%dT%H-%M-%S')}-{sid}.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in [meta] + turn(sid, args[0] if args else "", now)))
print(sid)
