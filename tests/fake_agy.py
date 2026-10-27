#!/usr/bin/env python3
"""A stand-in agy store for the tests, in the format of a real conversation
(agy 1.4): conversation_summaries.db in WAL mode, and per conversation
brain/<id>/.system_generated/logs/transcript.jsonl with the plan files beside
it.  Also cli.log and history.jsonl, which aht must never read.

Seen in a real conversation: the table and its columns, times as text
("2026-10-27 10:46:55.337183+00:00" in the database, "2026-10-27T10:46:51Z"
in a transcript), workspace_uris as a JSON list of file:// URIs, what was
typed wrapped in <USER_REQUEST> with agy's own blocks after it, a reply as
plain text, and SYSTEM_MESSAGE steps.  Not seen there: tool calls, a step's
thinking, the plan files and the long CORTEX_STEP_TYPE_ spelling of `type`;
those keep the program's description.

build(root, folder, marker) makes it and returns an open connection that
keeps the newest row in the WAL (close it with close_cleanly: agy, closed
cleanly, leaves no -wal); `marker` goes into the files aht must not read,
and into a step's thinking."""
import json, os, sqlite3, time
from datetime import datetime, timezone
from pathlib import Path

OLD = "a0a0a0a0-0000-4000-8000-000000000001"     # in the database file itself
NEW = "b1b1b1b1-0000-4000-8000-000000000002"     # only in the WAL
SUB = "c2c2c2c2-0000-4000-8000-000000000003"     # a subagent's: left out

# the table as agy 1.4 makes it
SCHEMA = ('CREATE TABLE `conversation_summaries` (`conversation_id` text,'
          '`title` text NOT NULL DEFAULT "",`preview` text NOT NULL DEFAULT "",'
          '`step_count` integer NOT NULL DEFAULT 0,`last_modified_time` datetime NOT NULL,'
          '`workspace_uris` text NOT NULL,`status` text NOT NULL DEFAULT "",'
          '`source` text NOT NULL DEFAULT "",`project_id` text NOT NULL DEFAULT "",'
          '`agent_name` text NOT NULL DEFAULT "",'
          '`parent_conversation_id` text NOT NULL DEFAULT "",'
          '`nesting_depth` integer NOT NULL DEFAULT 0,`battle_id` text NOT NULL DEFAULT "",'
          '`winning_conversation_id` text NOT NULL DEFAULT "",'
          '`not_fully_idle` numeric NOT NULL DEFAULT false,'
          '`killed` numeric NOT NULL DEFAULT false,`last_user_input_time` datetime NOT NULL,'
          '`last_user_input_step_index` integer NOT NULL DEFAULT -1,'
          '`app_data_dir` text NOT NULL DEFAULT "",`raw_summary` blob,'
          '`group_id` text NOT NULL DEFAULT "",PRIMARY KEY (`conversation_id`))')

def db_time(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f+00:00")

def step_time(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))

def transcript(folder: str, ask: str, marker: str, t: float) -> str:
    local = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t))
    steps = [
        {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "status": "DONE",
         "created_at": step_time(t),
         "content": f"<USER_REQUEST>\n{ask}\n</USER_REQUEST>\n<ADDITIONAL_METADATA>\n"
                    f"The current local time is: {local}+01:00.\n</ADDITIONAL_METADATA>\n"
                    "<USER_SETTINGS_CHANGE>\nThe user changed setting `Model Selection`."
                    "\n</USER_SETTINGS_CHANGE>"},
        {"step_index": 1, "source": "SYSTEM", "type": "SYSTEM_MESSAGE", "status": "DONE",
         "created_at": step_time(t),
         "content": "<SYSTEM_MESSAGE>\n[Notice] background tasks were stopped\n</SYSTEM_MESSAGE>"},
        {"step_index": 2, "source": "MODEL", "type": "CORTEX_STEP_TYPE_PLANNER_RESPONSE",
         "status": "DONE", "created_at": step_time(t + 5), "input_tokens": 6864,
         "output_tokens": 43, "thinking": f"private reasoning {marker}",
         "content": "The heron parser reads tokens now.",
         "tool_calls": [{"name": "write_to_file", "args": {
             "TargetFile": os.path.join(folder, "src", "heron.py"), "CodeContent": "x"}},
                        {"name": "run_command", "args": json.dumps(
                            {"CommandLine": "pytest -q", "Cwd": folder})}]},
    ]
    return "".join(json.dumps(s) + "\n" for s in steps)

def row(cid: str, title: str, t: float, uri: str, depth: int = 0, parent: str = "") -> tuple:
    return (cid, title, title, 3, db_time(t), json.dumps([uri]), "CASCADE_RUN_STATUS_IDLE",
            "default-cli-project", parent, depth, db_time(t - 4), "antigravity-cli")

INSERT = ("insert into conversation_summaries (conversation_id, title, preview, step_count, "
          "last_modified_time, workspace_uris, status, project_id, parent_conversation_id, "
          "nesting_depth, last_user_input_time, app_data_dir) values (?,?,?,?,?,?,?,?,?,?,?,?)")

def build(root, folder: str, marker: str):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    t = time.time() - 600
    for cid, ask in ((OLD, "an older question"), (NEW, "make the heron parser read tokens"),
                     (SUB, "a subagent's task")):
        logs = root / "brain" / cid / ".system_generated" / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "transcript.jsonl").write_text(transcript(folder, ask, marker, t))
    (root / "brain" / NEW / "task.md").write_text(
        "# Task\n\n- [x] read the parser\n- [/] make it read tokens\n- [ ] add a test\n")
    (root / "brain" / NEW / "implementation_plan.md").write_text(
        "# Plan\n\nThe heron parser gets a token reader.\n")
    (root / "cli.log").write_text(f"signed in as someone {marker}\n")
    (root / "history.jsonl").write_text(json.dumps({"display": f"typed {marker}",
                                                    "workspace": folder}) + "\n")
    uri = Path(folder).as_uri()
    con = sqlite3.connect(str(root / "conversation_summaries.db"))
    con.execute("pragma journal_mode=wal")
    con.execute("pragma wal_autocheckpoint=0")
    con.execute(SCHEMA)
    con.execute(INSERT, row(OLD, "An older conversation", t, uri))
    con.execute(INSERT, row(SUB, "A subagent", t, uri, depth=1, parent=OLD))
    con.commit()
    con.execute("pragma wal_checkpoint(truncate)")
    con.execute(INSERT, row(NEW, "Heron tokens", t + 5, uri))
    con.commit()
    return con

def close_cleanly(con, root):
    """Close the store the way agy leaves it when it exits: everything in
    the database file, still in WAL mode, and no -wal or -shm beside it
    (macOS's SQLite keeps them on close, so they are removed here)."""
    con.execute("pragma wal_checkpoint(truncate)").fetchall()
    con.close()
    for end in ("-wal", "-shm"):
        try:
            os.remove(str(Path(root) / "conversation_summaries.db") + end)
        except FileNotFoundError:
            pass
