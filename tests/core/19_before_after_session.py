#!/usr/bin/env python3
"""[19] before and after a session: informed, usage limit, undo, loose ends,
second opinion."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)

import later_kit

# what earlier sections left: [16]'s stand-in machine "box", named in the
# config (a notice then names its machine); [17]'s project "Across" (projX,
# tagged, its session "Pelican deploy"); [18]'s session c3 there, the latest
# (a request with an e-mail address, a home path and a key), its notices
# log (nlog), the folder of open sessions (rec) and `across`
later_kit.box_set_up()
projX, T, cstore, cline = later_kit.across_made()
nlog = sb / "notices.log"
_cfg = json.loads((sb / ".aht" / "config.json").read_text()) \
    if (sb / ".aht" / "config.json").is_file() else {}
across = "Across on mac" if _cfg.get("remotes") else "Across"
rec = tools / "sessions"
rec.mkdir(exist_ok=True)
home = str(Path.home())
lan = ["192.168.1.20", "169.254.10.20", "fd7a:115c:a1e0::5a1:2b3c", "fd12:3456:789a:1::1",
       "fe80::1c2b:3a4d:5e6f:7081%en0"]
(cstore / "c3.jsonl").write_text(cline(type="user", timestamp=iso(T + 500), message={
    "role": "user", "content": f"mail me at someone@example.org, file {home}/notes.txt, "
                               f"key {KEY}, on {', '.join(lan)}; std::fd12 and fdab3c1: stay"}))

print("\n[19] before and after a session: informed, usage limit, undo, loose ends, "
      "second opinion")
import time
# every session starts informed: only when turned on, since it costs tokens
def hook_out(payload, **extra):
    return subprocess.run([PY, LAUNCH, "hook"], env=dict(env, **extra), capture_output=True,
                          text=True, input=json.dumps(payload)).stdout
out = hook_out({"cwd": projX, "session_id": "new1", "source": "startup"})
ck("[aht] The latest" not in out, "informed sessions: off by default (the note costs tokens)")
run("config", "--set", "informed_sessions=true")
out = hook_out({"cwd": projX, "session_id": "new1", "source": "startup"})
ck("[aht] The latest earlier session" in out and "mail me at" in out and KEY not in out
   and "someone@example.org" in out and len(out) < 2000,
   f"informed sessions: where the last session stopped, short, no key ({out[:160]!r})")
out = hook_out({"cwd": projX, "session_id": "c1", "source": "resume"})
ck("[aht] The latest" not in out, "informed sessions: nothing added when a session is resumed")
run("config", "--unset", "informed_sessions")

# Claude's usage limit: seen in the transcript, said once, the other agent offered
projL = os.path.realpath(str(roots / "Limited"))
os.makedirs(projL)
lstore = tools / "claude" / enc(projL)
lstore.mkdir()
soon = time.localtime(time.time() + 7200)
resets = f"{soon.tm_hour % 12 or 12}:{soon.tm_min:02d}{'pm' if soon.tm_hour >= 12 else 'am'}"
(lstore / "l1.jsonl").write_text(
    json.dumps({"type": "user", "cwd": projL, "timestamp": iso(time.time() - 300),
                "message": {"role": "user", "content": "go on"}}) + "\n"
    + json.dumps({"type": "assistant", "cwd": projL, "timestamp": iso(time.time() - 290),
                  "isApiErrorMessage": True, "error": "rate_limit", "apiErrorStatus": 429,
                  "message": {"role": "assistant", "model": "<synthetic>", "content": [
                      {"type": "text", "text": f"You've hit your session limit · resets "
                                               f"{resets} (Europe/Lisbon)"}]}}) + "\n")
run("tag", projL, "--apply")
d = JS("limits", "--json")
hit = next((h for h in d.get("limits", []) if h.get("session") == "l1"), {})
ck(hit.get("resets", "").startswith(resets) and hit.get("over") is False
   and d.get("switch_to") is None,
   f"usage limit: found at the end of the transcript, with its reset time ({hit or d})")
kenv = {"AHT_CLI_KIMI": sys.executable, "AHT_NOTIFY_LOG": str(nlog),
        "AHT_NO_SEARCH_INDEX": "1", "AHT_MACHINE_NAME": "mac"}
run("config", "--set", "limit_switch=true")
nlog.write_text("")
run("notices", extra_env=kenv)
run("notices", extra_env=kenv)
got = [json.loads(l) for l in nlog.read_text().splitlines()]
ck([g["title"] for g in got] == [("Limited on mac" if across != "Across" else "Limited")
                                  + ": Claude's usage limit"]
   and "go on in Kimi Code" in got[0]["message"],
   f"usage limit: said once, with the agent to go on in ({got})")
row = next(p for p in JS("projects", "--json", extra_env=kenv)["projects"]
           if p["real_path"] == projL)
ck((row.get("limit") or {}).get("session") == "l1", "usage limit: shown on the project")
run("config", "--unset", "limit_switch")
with open(lstore / "l1.jsonl", "a") as fh:
    fh.write(json.dumps({"type": "user", "message": {"role": "user", "content": "go on"}}) + "\n")
ck(not [h for h in JS("limits", "--json").get("limits", []) if h["session"] == "l1"],
   "usage limit: gone once the session goes on")

# a copy of the folder when a session starts, and the whole session undone
projK = os.path.realpath(str(roots / "Checkpointed"))
os.makedirs(projK + "/src")
os.makedirs(projK + "/node_modules/big")
Path(projK, "src", "a.py").write_text("a = 1\n")
Path(projK, "b.txt").write_text("keep me\n")
Path(projK, "node_modules", "big", "x.js").write_text("x\n")
run("tag", projK, "--apply")
uidK = Path(projK, ".aht", ".project-id").read_text().strip()
run("config", "--set", "checkpoints=true")     # on by itself only on macOS
hook_out({"cwd": projK, "session_id": "k1", "source": "startup"}, AHT_NO_CHECKPOINT="")
cpdir = sb / ".aht" / "checkpoints" / uidK
for _ in range(80):
    if list(cpdir.glob("*/meta.json")):
        break
    time.sleep(0.25)
cp = next(iter(cpdir.glob("*")), None)
ck(cp is not None and (cp / "files" / "src" / "a.py").read_text() == "a = 1\n"
   and not (cp / "files" / "node_modules").exists(),
   "checkpoint: the folder is copied when a session starts (not what is rebuilt)")
Path(projK, "src", "a.py").write_text("a = 2  # the session changed it\n")
Path(projK, "b.txt").unlink()
Path(projK, "made.txt").write_text("the session made it\n")
d = JS("undo", projK, "--json")
ck((d.get("changed"), d.get("added"), d.get("removed")) == (1, 1, 1) and not d.get("applied"),
   f"undo: what changed since the session started ({d.get('files')})")
blocker = subprocess.Popen(["sleep", "600"], cwd="/")
(rec / f"{blocker.pid}.json").write_text(json.dumps({"pid": blocker.pid, "cwd": projK,
                                                     "status": "busy"}))
r = run("undo", projK, "--apply")
ck(r.returncode == 3 and Path(projK, "made.txt").exists(),
   "undo: refused while a session works in the folder")
blocker.kill(); blocker.wait()
(rec / f"{blocker.pid}.json").unlink()
d = JS("undo", projK, "--apply", "--json")
kept = Path(d.get("kept", "/nonexistent"))
ck(d.get("applied") and Path(projK, "src", "a.py").read_text() == "a = 1\n"
   and Path(projK, "b.txt").read_text() == "keep me\n" and not Path(projK, "made.txt").exists()
   and (kept / "made.txt").is_file() and "changed it" in (kept / "src" / "a.py").read_text(),
   "undo: the folder is as it was; what it held is set aside")

# which projects are too big for a copy, and folders left out of the copies
os.makedirs(projK + "/results")
for i in range(30):
    Path(projK, "results", f"r{i}.csv").write_text("1\n")
cov = JS("checkpoint", "--coverage", "--max", "20", "--json")
rowK = next((r for r in cov.get("projects", []) if r["project"] == projK), {})
ck(rowK.get("over") and rowK["biggest"][0] == {"name": "results", "files": 30}
   and projK in [r["project"] for r in cov.get("over", [])],
   f"coverage: a project over the limit, with its biggest folder ({rowK})")
run("config", "--set", "checkpoint_excludes=results")
cov = JS("checkpoint", "--coverage", "--max", "20", "--json")
rowK = next((r for r in cov.get("projects", []) if r["project"] == projK), {})
d = JS("checkpoint", projK, "--json")
ck(rowK.get("over") is False and d.get("files") == 2 and d.get("skip", [])[-1] == "results",
   f"checkpoint_excludes: the folder stays out, the project is covered again ({rowK}, {d.get('files')})")
run("config", "--unset", "checkpoint_excludes")
dd = JS("undo", projK, "--json")
ck(dd.get("added") == 0 and dd.get("changed") == 0,
   "undo compares with the names left out when the copy was made, not today's")
# two copies in the same second: the newest is the one taken last, whatever
# their names say (an undo compares with it)
ckey = core.checkpoints_root() / core._project_key(os.path.realpath(projK))
for name, at in (("20261029-120000-zzzz", 100.0), ("20261029-120000-aaaa", 200.0)):
    (ckey / name / "files").mkdir(parents=True)
    (ckey / name / "meta.json").write_text(json.dumps({"at": at, "files": 0}))
order = [c["id"] for c in core.list_checkpoints(projK) if c["id"].startswith("20261029-120000-")]
ck(order == ["20261029-120000-aaaa", "20261029-120000-zzzz"],
   f"checkpoints taken in the same second: the one taken last comes first ({order})")
for name in ("20261029-120000-zzzz", "20261029-120000-aaaa"):
    shutil.rmtree(ckey / name)
shutil.rmtree(projK + "/results")

# loose ends: work not committed, and a session that ended on a question
kst = tools / "claude" / enc(projK)
kst.mkdir(exist_ok=True)
(kst / "k1.jsonl").write_text(
    json.dumps({"type": "user", "cwd": projK, "message": {"role": "user", "content": "fix it"}})
    + "\n" + json.dumps({"type": "assistant", "cwd": projK, "message": {"role": "assistant",
          "content": [{"type": "text", "text": "Fixed the parser.\n\nShall I also update "
                                               "the docs for the new option?"}]}}) + "\n")
has_git = shutil.which("git") is not None
if has_git:
    subprocess.run(["git", "init", "-q", projK], capture_output=True)
row = next((r for r in JS("loose-ends", "--json").get("loose_ends", [])
            if r["project"] == projK), {})
kinds = sorted(i["kind"] for i in row.get("items", []))
ck(kinds == (["question", "uncommitted"] if has_git else ["question"])
   and any("update the docs" in i["text"] for i in row["items"]),
   f"loose ends: files not committed and the question left open ({row})")

# a second opinion: the same task by two agents, each in its own copy
projO = os.path.realpath(str(roots / "Opinion"))
os.makedirs(projO)
Path(projO, "a.py").write_text("a = 1\n")
wrap = {}
for who in ("claude", "kimi"):
    w = sb / f"agent-{who}"
    w.write_text(f'#!/bin/sh\nexec "{PY}" "{HERE / "fake_agent.py"}" {who} "$@"\n')
    w.chmod(0o755)
    wrap[f"AHT_CLI_{who.upper()}"] = str(w)
r = run("second-opinion", projO, "--task", "add a line", extra_env=wrap)
ck(r.returncode == 3 and "tokens" in r.stdout,
   "second opinion: off until turned on, because it uses both agents' tokens")
run("config", "--set", "second_opinion=true")
# Kimi takes part only in never-ask mode (its run never asks): the user's own
# agent_permissions sets it here
run("config", "--set", "agent_permissions=never")
d = JS("second-opinion", projO, "--task", "add a line", "--json", extra_env=wrap)
run("config", "--unset", "agent_permissions")
rid = d.get("id", "?")
for _ in range(120):
    sh_ = JS("second-opinion", "--show", rid, "--json", extra_env=wrap)
    if all(r.get("state") in ("done", "failed") for r in sh_.get("results", {}).values()):
        break
    time.sleep(0.25)
res = sh_.get("results", {})
files = {a: sorted((f["state"], f["name"]) for f in r.get("files", [])) for a, r in res.items()}
ck(d.get("applied") and files == {"claude": [("changed", "a.py")],
                                  "kimi": [("added", "notes.txt"), ("changed", "a.py")]}
   and "Claude: added a line." in res.get("claude", {}).get("answer", "")
   and Path(projO, "a.py").read_text() == "a = 1\n",
   f"second opinion: both worked in copies; the project is untouched ({files})")
Path(projO, "a.py").write_text("a = 1  # changed meanwhile\n")
r = run("second-opinion", "--take", rid, "--from", "kimi", "--apply", extra_env=wrap)
ck(r.returncode == 3 and "since the copies were made" in r.stdout,
   "second opinion: not taken over a file changed in the project meanwhile")
Path(projO, "a.py").write_text("a = 1\n")
d = JS("second-opinion", "--take", rid, "--from", "kimi", "--apply", "--json", extra_env=wrap)
ck(d.get("applied") and "kimi did" in Path(projO, "a.py").read_text()
   and Path(projO, "notes.txt").is_file() and Path(d["kept"], "a.py").is_file(),
   "second opinion: one agent's changes brought in; the old files set aside")
run("second-opinion", "--discard", rid)
ck(not (sb / ".aht" / "opinions" / rid).exists(), "second opinion: the copies can be removed")
run("config", "--unset", "second_opinion")

d = JS("sessions", "--json")
ck(any(s.get("title") == "Pelican deploy" for s in d.get("sessions", [])),
   "sessions: every session with its title, for Spotlight")

done()
