#!/usr/bin/env python3
"""[17] across agents: search, secrets, journal, rules, switch, board."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)

print("\n[17] across agents: search, secrets, journal, rules, switch, board")
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
probe = ("import sys, json; sys.path.insert(0, sys.argv[1]); import aht; "
         "print(json.dumps(sorted(s['agent'] for s in aht.list_sessions(sys.argv[2]))))")
r = subprocess.run([PY, "-c", probe, str(HERE.parent), projX], env=env,
                   capture_output=True, text=True)
ck(r.stdout.strip() == '["claude", "codex", "kimi"]',
   f"sessions of Claude, Kimi and Codex are read ({r.stdout.strip() or r.stderr[-200:]})")

d = JS("search", "walrus", "--json")
hit = (d.get("results") or [{}])[0]
ck(hit.get("agent") == "kimi" and hit.get("title") == "Walrus work" and hit.get("live")
   and "-S session_k1" in (hit.get("resume") or ""),
   f"search finds a Kimi session and how to resume it ({hit or d})")
d = JS("search", "heron", "--agent", "codex", "--json", "--no-update")
ck([r["agent"] for r in d.get("results", [])] == ["codex"], "search: by agent")
d = JS("search", "pelican", "--json", "--no-update")
snips = " ".join(h["snippet"] for r in d.get("results", []) for h in r["hits"])
ck(d.get("results") and d["results"][0]["title"] == "Pelican deploy"
   and "Xq7Xq7Xq7Xq7" not in snips and KEY not in snips,
   "search: a key in a prompt is masked in the index")
import sqlite3
db = sqlite3.connect(str(sb / ".aht" / "search.db"))
ck(not any(KEY in t for (t,) in db.execute("select text from msgs")),
   "the index file holds no key")
db.close()
run("backup")
(cstore / "c1.jsonl").unlink()
d = JS("search", "pelican", "--json")
hit = (d.get("results") or [{}])[0]
ck(hit.get("live") is False and (hit.get("restore") or {}).get("stamp")
   and hit["restore"]["project"] == projX,
   f"a session deleted since is still found, with the backup to restore it ({hit})")
r = run("restore", projX, "--uuid", hit["restore"]["uuid"], "--stamp",
        hit["restore"]["stamp"], "--apply")
ck((cstore / "c1.jsonl").is_file(), "…and that restore brings it back")

d = JS("secrets", projX, "--json")
kinds = sorted({f["kind"] for f in d.get("finds", [])})
ck(kinds == ["Anthropic API key"] and d["finds"][0]["where"] == "your message"
   and KEY not in json.dumps(d) and d["finds"][0]["masked"].startswith("sk-a"),
   f"secrets: the key is found, where it is, only masked ({d.get('finds') or d})")
junk = projX + "/app.py"
(cstore / "c2.jsonl").write_text(
    cline(type="assistant", timestamp=iso(T + 99), message={"role": "assistant", "content": [
        {"type": "text", "text": "use settings.api_key = config.api_key_value and "
                                 "password=${DB_PASSWORD}, secret: round-robin-2023, "
                                 "passwd = Xk29!" + "aa8Qz3"}]}))
d = JS("secrets", projX, "--json")
found = sorted(f["masked"] for f in d.get("finds", []) if f["session"] == "c2")
ck(found == ["Xk29…z3"], f"secrets: code, placeholders and words are not reported ({found})")
(cstore / "c2.jsonl").unlink()

d = JS("journal", projX, "--json")
md = d.get("markdown", "")
ck(d.get("days") == 2 and "tidy the walrus module" in md and "Changed: `walrus.py`" in md
   and "Claude Code · Pelican deploy" in md and "Kimi Code · Walrus work" in md
   and KEY not in md and "[Anthropic API key:" in md
   and md.index("Kimi Code") < md.index("Claude Code"),
   "journal: every agent, newest day first, files changed, keys masked")
d = JS("journal", projX, "--write", "--json")
ck(Path(projX, ".aht", "journal", "journal.md").is_file()
   and Path(projX, ".aht", "journal", ".gitignore").read_text().strip() == "*",
   "journal --write: saved where git ignores it")

Path(projX, "CLAUDE.md").write_text("Use tabs.\n")
d = JS("rules", projX, "--json")
ck(d.get("state") == "claude-only", "rules: only CLAUDE.md is seen")
run("rules", projX, "--unify", "--apply")
ck(Path(projX, "CLAUDE.md").read_text() == "@AGENTS.md\n"
   and Path(projX, "AGENTS.md").read_text() == "Use tabs.\n"
   and JS("rules", projX, "--json").get("state") == "one",
   "rules --unify: AGENTS.md holds them, CLAUDE.md imports it")
Path(projX, "CLAUDE.md").write_text("Answer briefly.\n")
r = run("rules", projX, "--unify", "--apply")
ck(r.returncode == 3 and Path(projX, "CLAUDE.md").read_text() == "Answer briefly.\n",
   "rules: two different files are not merged without a choice")
run("rules", projX, "--unify", "--prefer", "both", "--apply")
agents_md = Path(projX, "AGENTS.md").read_text()
kept = list((sb / ".aht" / "rules-backups").rglob("CLAUDE.md"))
ck("Use tabs." in agents_md and "Answer briefly." in agents_md
   and Path(projX, "CLAUDE.md").read_text() == "@AGENTS.md\n" and len(kept) == 2,
   "rules --prefer both: nothing lost, each earlier file kept")

tlog = sb / "terminal.log"
klog = sb / "kimi.log"
fk = sb / "stubs2"
fk.mkdir()
(fk / "kimi").write_text(f'#!/bin/sh\nexec "{PY}" "{HERE / "fake_kimi.py"}" "$@"\n')
(fk / "claude").write_text('#!/bin/sh\necho "9.9.9 (Claude Code)"\n')
for s in fk.iterdir():
    s.chmod(0o755)
senv = {"AHT_TERMINAL_LOG": str(tlog), "AHT_FAKE_KIMI_LOG": str(klog),
        "AHT_CORE_DIR": str(HERE.parent), "AHT_CLI_KIMI": str(fk / "kimi"),
        "AHT_CLAUDE": str(fk / "claude"), "AHT_NO_SEARCH_INDEX": "1"}
tsx = sb / "stubs2" / "tailscale"
tsx.write_text("#!/bin/sh\ncat <<'JSON'\n" + json.dumps({"Peer": {"a": {
    "HostName": "aht-test-homebox", "DNSName": "aht-test-homebox.example.ts.net.", "OS": "linux",
    "Online": True, "TailscaleIPs": ["100.64.0.7", "fd7a::7"]}}}) + "\nJSON\n")
tsx.chmod(0o755)
probe = ("import sys, json; sys.path.insert(0, sys.argv[1]); import aht; "
         "r = aht.Remote('hb', {'ssh': 'me@aht-test-homebox'}); "
         "r2 = aht.Remote('ok', {'ssh': 'me@localhost'}); "
         "print(json.dumps([list(r.route()), r.ssh_opts()[-2:], list(r2.route())]))")
r = subprocess.run([PY, "-c", probe, str(HERE.parent)], capture_output=True, text=True,
                   env=dict(env, AHT_TAILSCALE=str(tsx)))
got = json.loads(r.stdout) if r.stdout.strip() else None
ck(got == [["me@100.64.0.7", "aht-test-homebox"], ["-o", "HostKeyAlias=aht-test-homebox"],
           ["me@localhost", None]],
   f"a machine whose name does not resolve is reached at its Tailscale address, "
   f"its host key checked under the name ({got or r.stderr[-200:]})")

d = JS("switch", projX, "--to", "claude", "--json", extra_env=senv)
ck(d.get("source", {}).get("agent") == "kimi" and not d.get("applied"),
   f"switch picks the latest session of another agent ({d.get('source') or d})")
rec = tools / "sessions"
rec.mkdir(exist_ok=True)
waiter = subprocess.Popen(["sleep", "600"], cwd="/")
(rec / f"{waiter.pid}.json").write_text(json.dumps(
    {"pid": waiter.pid, "cwd": projX, "status": "waiting", "waitingFor": "approve Bash"}))
d = JS("switch", projX, "--to", "kimi", "--apply", "--json", extra_env=senv)
ck(not d.get("applied") and any("WAITING for you (approve Bash)" in b
                                for b in d.get("blockers", [])),
   "a session waiting for you blocks a switch")
b = JS("board", "--local", "--json")
row = next((s for s in b["machines"][0]["sessions"] if s["project"] == projX), {})
ck(row.get("status") == "waiting for you" and row.get("waiting_for") == "approve Bash",
   f"board: a session waiting for you, and for what ({row})")
waiter.kill(); waiter.wait()
# Kimi reads the summary in a run of its own only in never-ask mode (that run
# never asks): here the user's own agent_permissions sets it
run("config", "--set", "agent_permissions=never")
d = JS("switch", projX, "--to", "kimi", "--apply", "--json", extra_env=senv)
run("config", "--unset", "agent_permissions")
calls = [json.loads(l) for l in klog.read_text().splitlines()] if klog.is_file() else []
opened = tlog.read_text() if tlog.is_file() else ""
ck(d.get("applied") and d.get("session", "").startswith("session_")
   and f"-S {d['session']}" in opened and calls and calls[-1]["cwd"] == projX
   and "Where things stood" not in calls[-1]["args"][1] and "tidy the walrus" not in ""
   and "pelican" in calls[-1]["args"][1] and KEY not in calls[-1]["args"][1],
   f"switch to Kimi: it reads the summary first, then that session opens "
   f"({d.get('error') or d.get('blockers') or opened[-120:]})")
d = JS("switch", projX, "--to", "claude", "--apply", "--json", extra_env=senv)
opened = tlog.read_text().splitlines()[-1] if tlog.is_file() else ""
brief = d.get("brief") or ""
ck(d.get("applied") and str(fk / "claude") in opened and os.path.basename(brief) in opened
   and d["source"]["agent"] == "kimi" and Path(brief).is_file()
   and Path(projX, ".aht", "handover", ".gitignore").is_file(),
   "switch back to Claude: it opens with the summary to read")
r = run("switch", projX, "--to", "claude", "--apply", "--json",
        extra_env=dict(senv, AHT_TERMINAL_LOG="", AHT_NO_TERMINAL="1"))
try:
    d = json.loads(r.stdout)
except ValueError:
    d = {}
ck(d and not d.get("applied") and "Run this in a terminal" in d.get("error", "")
   and d.get("command_line") and d["command_line"] in d["error"]
   and d["command_line"].startswith(f"cd {core.shell_quote(projX)} && "),
   f"switch with no terminal: not applied, the line to run by hand in the error, the JSON "
   f"alone on stdout ({r.stdout[:300]})")
# Continue: the session id goes on a command line, so only a plain one is taken
r = run("resume-here", projX, "--session", "x&calc", "--print", extra_env=senv)
ck(r.returncode == 2 and "not a session id" in r.stderr and not r.stdout,
   f"resume-here: a session id with other characters is refused ({r.stdout} {r.stderr})")
r = run("resume-here", projX, "--session", "ab-12.c_d", extra_env=senv)
opened = tlog.read_text().splitlines()[-1] if tlog.is_file() else ""
ck(r.returncode == 0 and opened == f"cd {core.shell_quote(projX)} && exec "
   f"{core.shell_quote(fk / 'claude')} --resume ab-12.c_d",
   f"resume-here: in the project's folder, the session named ({opened})")
# Windows: each word in double quotes, so cmd.exe runs nothing from a folder's name
_osname = core.os.name
try:
    core.os.name = "nt"
    wq = [core.shell_quote(r"C:\Users\me\R&D"), core.shell_quote('a"b|c'),
          core.cd_then(r"C:\x^y (1)")]
finally:
    core.os.name = _osname
ck(wq == ['"C:\\Users\\me\\R&D"', '"ab|c"', 'cd /d "C:\\x^y (1)" && '],
   f"Windows: a word for cmd.exe is always in double quotes ({wq})")

done()
