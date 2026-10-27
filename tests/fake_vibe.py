#!/usr/bin/env python3
"""A stand-in Mistral Vibe data folder for the tests, in the format of a real
session (Vibe 3.0.3): logs/session/unified/<id>/ with meta.json, CURRENT,
generations/<g>/{manifest,projection-state,checkpoint,runtime-state}.json,
chunks/<sha256>.json and journal/<n>.jsonl, all JSON canonical (sorted keys,
no spaces) and newline-ended, as Vibe writes them.

Seen in a real session: the layout, meta.json's fields, CURRENT, the
manifest, a projection whose history sits in chunks, the journal's records
(projection_delta appending the user's message, a reasoning entry and the
reply, with set_envelope; command_reserved, core_input, action_intent,
action_result, receipt_succeeded around them).  Not seen there: tool calls
(effect entries), the to-do tool, replace_entry, remove_entry,
projection_advanced, a history kept inline and a subagent's session; those
keep the program's description.

build(root, folder, other, marker) makes it: sessions OLD and NEW in
`folder` (NEW's second turn only in its journal), SUB (a subagent's, left
out) and ELSE in `other`.  `marker` goes into every file aht must never
read, into the journal's other records and into the reasoning entries."""
import hashlib, json, os, time
from pathlib import Path

OLD = "a0a0a0a0-0000-4000-8000-0000000000a1"     # history in two chunks
NEW = "b1b1b1b1-0000-4000-8000-0000000000b2"     # a turn kept inline, one in its journal
SUB = "c2c2c2c2-0000-4000-8000-0000000000c3"     # a subagent's: left out
ELSE = "d3d3d3d3-0000-4000-8000-0000000000d4"    # in another folder

def canon(v) -> bytes:
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()

def doc(path: Path, v) -> str:
    """A document as Vibe writes it -> its digest (of the bytes before the newline)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = canon(v)
    path.write_bytes(body + b"\n")
    return hashlib.sha256(body).hexdigest()

def iso(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + f".{int(t % 1 * 1e6):06d}+00:00"

def ms(t: float) -> int:
    return int(t * 1000)

def message(sid, role, text, t, turn, source=None, status="completed", n=1):
    e = {"content": [{"text": text, "type": "text"}], "createdAt": ms(t),
         "generationStatus": status, "id": f"{role}-{turn}-{n}", "inputEntryId": None,
         "relatedEntryId": None, "role": role, "sessionId": sid,
         "source": source or ("turn_start" if role == "user" else "harness"),
         "turnId": turn, "type": "message", "updatedAt": ms(t)}
    if role == "assistant":
        e["outcome"] = {"type": "committed"} if status == "completed" else None
    return e

def reasoning(sid, text, t, turn):
    return {"createdAt": ms(t), "generationStatus": "completed", "id": f"reasoning-{turn}-0",
            "inputEntryId": None, "outcome": {"type": "committed"}, "relatedEntryId": None,
            "sessionId": sid, "summary": [], "text": text, "turnId": turn,
            "type": "reasoning", "updatedAt": ms(t)}

def effect(sid, eid, tool, args, t, turn, running=False):
    return {"createdAt": ms(t), "detail": {"display": {"statusText": f"Running {tool}",
                                                       "summary": tool},
                                           "input": args, "kind": "tool", "toolName": tool},
            "generationStatus": "in_progress" if running else "completed",
            "id": f"effect-{eid}", "inputEntryId": None, "relatedEntryId": None,
            "sessionId": sid, "state": {"outputText": "", "status": "running"} if running
            else {"output": {"ok": True}, "outputText": "done", "status": "completed"},
            "title": tool, "turnId": turn, "type": "effect", "updatedAt": ms(t)}

def turn(sid, n, ask, reply, t, marker):
    k = f"turn-{sid[:8]}-{n}"
    return [message(sid, "user", ask, t, k),
            reasoning(sid, f"private reasoning {marker}", t + 2, k),
            message(sid, "assistant", reply, t + 3, k)]

def envelope(sid, t0, t1, parent=None):
    return {"activeCallbacks": [], "format": "harness.public-session-state/v1",
            "history": {"cursor": {"after": None, "before": None}, "entries": [],
                        "range": "latest"},
            "latestTurn": None,
            "session": {"createdAt": ms(t0), "id": sid, "parentSessionId": parent,
                        "preview": "", "rootSessionId": sid, "status": {"type": "idle"},
                        "title": None, "titleSource": "auto", "updatedAt": ms(t1)},
            "turnQueue": {"items": [], "maxItems": 32, "paused": False}}

def journal(path: Path, first: int, records, partial: bytes = b"") -> None:
    """Records as Vibe appends them: the payload first, then the header,
    and a digest of the line without it; each names the one before."""
    lines, prev = [], None
    for i, (typ, payload) in enumerate(records):
        head = {"previous_record_sha256": prev, "recovery_journal_record_version": 1,
                "sequence": first + i, "type": typ}
        bare = b'{"payload":' + canon(payload) + b"," + canon(head)[1:]
        prev = hashlib.sha256(bare).hexdigest()
        at = bare.index(b',"recovery_journal_record_version"')
        lines.append(bare[:at] + b',"record_sha256":"' + prev.encode() + b'"' + bare[at:] + b"\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(lines) + partial)

def store(root, sid, folder, entries, t0, t1, marker, parent=None, chunks=1, seq=8,
          records=(), partial=b"", title=None):
    """One session: `entries` in generation `seq` (in `chunks` chunk files,
    or inline when 0), `records` in the journal after it."""
    d = Path(root) / "logs" / "session" / "unified" / sid
    g = d / "generations" / f"{seq:016d}"
    env = envelope(sid, t0, t1, parent)
    hist = []
    if chunks:
        size = -(-len(entries) // chunks)
        for i in range(0, len(entries), size):
            body = canon(entries[i:i + size])
            h = hashlib.sha256(body).hexdigest()
            (d / "chunks").mkdir(parents=True, exist_ok=True)
            (d / "chunks" / f"{h}.json").write_bytes(body + b"\n")
            hist.append(h)
    else:
        env["history"]["entries"] = entries
    proj = doc(g / "projection-state.json", {"projection_state_version": 1, "session_id": sid,
                                             "snapshot": env, "snapshot_sequence": seq,
                                             "watermark": 2})
    # the model's own context and the runtime's state: never read
    ckp_chunk = canon([{"content": f"system prompt {marker}", "role": "system"}])
    ckp_hash = hashlib.sha256(ckp_chunk).hexdigest()
    (d / "chunks").mkdir(parents=True, exist_ok=True)
    (d / "chunks" / f"{ckp_hash}.json").write_bytes(ckp_chunk + b"\n")
    ckp = doc(g / "checkpoint.json", {"checkpoint_version": 1, "context": {"messages": []},
                                      "note": marker})
    run = doc(g / "runtime-state.json", {"runtime_state_version": 3, "session_id": sid,
                                         "session_metadata": {"cwd": folder, "note": marker},
                                         "snapshot_sequence": seq})
    man = doc(g / "manifest.json", {
        "checkpoint": {"checkpoint_version": 1, "chunks": [ckp_hash], "path": "checkpoint.json",
                       "sha256": ckp},
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t1)),
        "execution_state": "quiescent", "generation": f"{seq:016d}", "interop_export": None,
        "manifest_version": 1,
        "projection_state": {"chunks": hist if chunks else None, "path": "projection-state.json",
                             "sha256": proj},
        "recovery_journal_segment": {"first_sequence": seq + 1,
                                     "path": f"journal/{seq + 1:016d}.jsonl"},
        "runtime_state": {"chunks": None, "path": "runtime-state.json", "sha256": run},
        "session_id": sid, "snapshot_sequence": seq})
    doc(d / "CURRENT", {"generation": f"{seq:016d}", "manifest_sha256": man, "session_id": sid,
                        "snapshot_sequence": seq,
                        "store_format": "mistral.vibe.unified-session-store/v1",
                        "store_format_minor": 10})
    journal(d / "journal" / f"{seq + 1:016d}.jsonl", seq + 1, records, partial)
    (d / "meta.json").write_text(json.dumps({
        "session_id": sid, "parent_session_id": parent, "start_time": iso(t0),
        "end_time": iso(t1), "git_commit": None, "git_branch": None,
        "environment": {"working_directory": folder}, "origin_directory": folder,
        "username": "someone", "child_sessions": [], "loops": [], "title": title,
        "title_source": "auto", "bumped_at": iso(t0), "pinned_at": None, "archived_at": None,
        "unseen_at": None, "seen_at": None, "experiments": None,
        "config": {"active_model": "mistral-medium-3.5", "model_name": marker},
        "import_provenance": None, "created_worktree": None, "artifacts": []}, indent=2))
    (d / "scheduled-loops.json").write_text(json.dumps({"loops": [], "note": marker}))
    stamp = t1 + 1
    os.utime(d / "journal" / f"{seq + 1:016d}.jsonl", (stamp, stamp))
    return d

def delta(*ops, envelope_of=None):
    out = {"delta": list(ops), "watermark": 3}
    if envelope_of:
        out["delta"].append({"op": "set_envelope", "state": envelope_of})
    return out

def build(root, folder: str, other: str, marker: str):
    root = Path(root)
    t = time.time() - 900
    store(root, OLD, folder, turn(OLD, 1, "an older question", "An older answer.", t, marker)
          + turn(OLD, 2, "and one more", "One more answer.", t + 20, marker), t, t + 30,
          marker, chunks=2, title="Older work")
    # NEW: its first turn in the generation, kept inline; its second only in
    # the journal, as Vibe appends it while it works
    sid, k = NEW, f"turn-{NEW[:8]}-2"
    t2 = t + 300
    w = effect(sid, "w1", "file_system.write_file",
               {"path": "src/heron.py", "content": "tokens = []\n"}, t2 + 5, k, running=True)
    read = effect(sid, "r1", "file_system.read_file", {"path": "README.md"}, t2 + 4, k, True)
    todo = effect(sid, "t1", "vibe.todo", {"action": "write", "todos": [
        {"id": "1", "content": "read the parser", "status": "completed", "priority": "high"},
        {"id": "2", "content": "make it read tokens", "status": "in_progress",
         "priority": "high"},
        {"id": "3", "content": "add a test", "status": "pending", "priority": "medium"},
        {"id": "4", "content": "rewrite it in C", "status": "cancelled", "priority": "low"}]},
        t2 + 6, k)
    done = dict(w, generationStatus="completed",
                state={"output": {"bytes_written": 11}, "outputText": "", "status": "completed"})
    reply = message(sid, "assistant", "The heron parser reads tokens now.", t2 + 9, k)
    streaming = dict(reply, generationStatus="in_progress", outcome=None,
                     content=[{"text": "The heron", "type": "text"}])
    records = [
        ("command_reserved", {"client_command_id": "c1", "method": "session/turn/start",
                              "params": {"note": marker}}),
        ("core_input", {"input": {"command": {"text": f"make the heron parser {marker}"}}}),
        ("projection_delta", delta({"op": "append_entry", "entry": message(
            sid, "user", "make the heron parser read tokens", t2, k)},
            envelope_of=envelope(sid, t, t2))),
        ("action_intent", {"request": {"messages": [{"role": "system", "content": marker}]}}),
        ("projection_delta", delta({"op": "append_entry", "entry": reasoning(
            sid, f"private reasoning {marker}", t2 + 3, k)},
            {"op": "append_entry", "entry": read}, {"op": "append_entry", "entry": w})),
        ("action_result", {"result": {"stdout": marker}}),
        ("projection_delta", delta({"op": "replace_entry", "id": w["id"], "entry": done},
                                   {"op": "remove_entry", "id": read["id"]},
                                   {"op": "append_entry", "entry": effect(
                                       sid, "b1", "file_system.bash",
                                       {"command": "pytest -q", "timeout_seconds": 60},
                                       t2 + 7, k)},
                                   {"op": "append_entry", "entry": todo},
                                   {"op": "append_entry", "entry": message(
                                       sid, "user", f"context Vibe added {marker}", t2 + 8, k,
                                       source="harness", n=2)},
                                   {"op": "append_entry", "entry": streaming})),
        ("projection_delta", delta({"op": "replace_entry", "id": reply["id"], "entry": reply},
                                   envelope_of=envelope(sid, t, t2 + 9))),
        ("receipt_succeeded", {"client_command_id": "c1"}),
    ]
    half = b'{"payload":{"delta":[{"entry":{"type":"message","role":"user","content":[{"type":' \
           b'"text","text":"half written"}]},"op":"append_entry"}'
    store(root, NEW, folder, turn(NEW, 1, "look at the heron parser", "It reads characters.",
                                  t + 200, marker), t + 200, t2 + 9, marker, chunks=0, seq=12,
          records=records, partial=half, title="Heron tokens")
    store(root, SUB, folder, turn(SUB, 1, "a subagent's task", "Done.", t + 250, marker),
          t + 250, t + 260, marker, parent=NEW)
    store(root, ELSE, other, turn(ELSE, 1, "work elsewhere", "Elsewhere done.", t + 100, marker),
          t + 100, t + 110, marker)
    # what aht must never read: the data folder's own files, Vibe 2's sessions
    for name in ("config.toml", ".env", "whoami_cache.json", "vibehistory",
                 "trusted_folders.toml", "connector_bootstrap_cache.json",
                 "managed_config_cache.json", "model_catalog_cache.json",
                 "logs/vibe.log", "logs/vibe-rs.log"):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(f"signed in as someone {marker}\n")
    legacy = root / "logs" / "session" / "session_20261027_101010_e5e5e5e5"
    legacy.mkdir(parents=True)
    (legacy / "meta.json").write_text(json.dumps({
        "session_id": "e5e5e5e5-0000-4000-8000-0000000000e5", "start_time": iso(t),
        "end_time": iso(t), "environment": {"working_directory": folder}, "title": marker}))
    (legacy / "messages.jsonl").write_text(json.dumps({"role": "user", "content": marker}) + "\n")

def add_turn(root, folder: str, sid: str, ask: str, reply: str, t: float, marker: str,
             edit: str = None) -> None:
    """A session Vibe made in `folder` at `t`: one turn, an edit to the file
    `edit` (relative, as Vibe names it) on the way."""
    k = f"turn-{sid[:8]}-1"
    entries = turn(sid, 1, ask, reply, t, marker)
    if edit:
        entries.insert(2, effect(sid, "e1", "file_system.edit",
                                 {"file_path": edit, "old_string": "a", "new_string": "b"},
                                 t + 2, k))
    store(root, sid, folder, entries, t, t + 3, marker)
