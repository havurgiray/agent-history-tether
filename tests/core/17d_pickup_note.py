#!/usr/bin/env python3
"""[17d] across machines: Pick Up and Leave a Note."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)

# what earlier sections left: [17b]'s made-up key
KEY_A = "sk-" + "ant-" + "api03-" + "Pq4w" * 9          # made-up keys, built in pieces

print("\n[17d] across machines: Pick Up and Leave a Note")
# box is a folder that stands in for another machine (aht's core runs there
# with a home of its own, and calls itself "box"); it holds the project at
# another path than here, with a git upstream (a bare repository in box), a
# Claude session that holds a key, and a Codex rollout.  No agent runs and no
# ssh reaches a real machine: start lines go to a log
FIXTURES4 = HERE / "fixtures" / "phase4"
fx4 = []
pe = iso_env("pickup")
pbase = Path(pe["HOME"]).parent
pbox = pbase / "box"
bhome = pbox / "home"
(bhome / ".aht").mkdir(parents=True)
(bhome / ".aht" / "config.json").write_text("{}")          # aht is installed on box
pstub = pbase / "stubs"
pstub.mkdir()
pcalls, ptlog = pbase / "calls.log", pbase / "terminal.log"
(pstub / "codex").write_text(f'#!/bin/sh\necho "codex $*" >> "{pcalls}"\n')
(pstub / "ssh").write_text(f'#!/bin/sh\nexec "{PY}" "{HERE / "fake_ssh.py"}" "$@"\n')
for _f in pstub.iterdir():
    _f.chmod(0o755)
(pbase / "far").mkdir()                                     # no machine answers there
(pbase / "no-tabs.json").write_text("{}")
pe.update(AHT_MACHINE_NAME="mac", AHT_REMOTE_MACHINE_NAME="box",
          AHT_CLI_CODEX=str(pstub / "codex"), AHT_TERMINAL_LOG=str(ptlog),
          AHT_NO_SEARCH_INDEX="1", AHT_ITERM_TABS=str(pbase / "no-tabs.json"),
          FAKE_SSH_DIR=str(pbase / "far"), GIT_CONFIG_NOSYSTEM="1",
          PATH=str(pstub) + os.pathsep + pe["PATH"])
# box's own aht, for its hook and its notices: its home, its name
benv = {k: v for k, v in pe.items() if not k.startswith("AHT_")}
benv.update(core._sandbox_env(str(bhome)), AHT_MACHINE_NAME="box", AHT_NO_SEARCH_INDEX="1",
            AHT_ITERM_TABS=str(pbase / "no-tabs.json"),
            AHT_NOTIFY_LOG=str(pbase / "box-notices.log"))
def P(*a, **extra):
    r = subprocess.run([PY, LAUNCH, *a], env=dict(pe, **extra), capture_output=True, text=True)
    try:
        d = json.loads(r.stdout)
    except ValueError:
        d = {"unparsed": r.stdout[-400:] + r.stderr[-800:]}
    if isinstance(d, dict):
        d["_rc"] = r.returncode
    return d
def box_hook(cwd, sid, source="startup"):
    return subprocess.run([PY, LAUNCH, "hook"], env=benv, capture_output=True, text=True,
                          input=json.dumps({"cwd": cwd, "session_id": sid,
                                            "source": source})).stdout
def here_hook(cwd, sid, source="resume"):
    return subprocess.run([PY, LAUNCH, "hook"], env=pe, capture_output=True, text=True,
                          input=json.dumps({"cwd": cwd, "session_id": sid,
                                            "source": source})).stdout
def box_op(req):
    """One operation of box's core, as another machine asks it."""
    r = subprocess.run([PY, LAUNCH, "_agent"], env=benv, capture_output=True, text=True,
                       input=json.dumps(req))
    i = r.stdout.rfind(core.AGENT_MARK)
    return json.loads(r.stdout[i + len(core.AGENT_MARK):]) if i >= 0 else {"unparsed": r.stderr}
def pgit(cwd, *a):
    return subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c",
                           "user.email=t@example.org", "-c", "commit.gpgsign=false",
                           "-c", "init.defaultBranch=main", *a],
                          capture_output=True, text=True, env=pe)
def files_in(d):
    return sorted(p.name for p in Path(d).glob("relay-*")) if Path(d).is_dir() else []

bare = bhome / "git" / "paper.git"
bare.parent.mkdir(parents=True)
pgit(bare.parent, "init", "-q", "--bare", str(bare))
bpaper = bhome / "code" / "paper"
bpaper.parent.mkdir(parents=True)
pgit(bpaper.parent, "clone", "-q", str(bare), str(bpaper))
(bpaper / "app.py").write_text("print('hello')\n")
pgit(bpaper, "add", "-A"); pgit(bpaper, "commit", "-qm", "First commit"); pgit(bpaper, "push", "-q")
hpaper = Path(pe["HOME"]) / "code" / "paper"
hpaper.parent.mkdir(parents=True)
pgit(hpaper.parent, "clone", "-q", str(bare), str(hpaper))
(bpaper / "login.py").write_text("redirect = '/home'\n")         # 1 commit not pushed
pgit(bpaper, "add", "-A"); pgit(bpaper, "commit", "-qm", "Fix the login redirect")
(bpaper / "app.py").write_text("print('hello, world')\n")        # 1 file not committed
bp, hp = os.path.realpath(str(bpaper)), os.path.realpath(str(hpaper))
T4 = time.time() - 3600
SB = "0f3a9c2e-1111-4222-8333-444455556666"         # box's Claude session
SH = "5e5e5e5e-1111-4222-8333-444455556666"         # this Mac's Claude session
CX = "c0dec0de-0000-4000-8000-000000000001"         # box's Codex session
bstore = bhome / ".claude" / "projects" / enc(bp)
bstore.mkdir(parents=True)
def cl4(sid, cwd, **kw):
    return json.dumps(dict({"cwd": cwd, "entrypoint": "cli", "sessionId": sid}, **kw)) + "\n"
(bstore / f"{SB}.jsonl").write_text(
    cl4(SB, bp, type="user", timestamp=iso(T4), message={
        "role": "user", "content": f"heron: fix the login redirect, the key is {KEY_A}"})
    + cl4(SB, bp, type="ai-title", aiTitle="fix the login redirect")
    + cl4(SB, bp, type="assistant", timestamp=iso(T4 + 60), message={
        "role": "assistant", "content": [{"type": "text", "text": "login.py now redirects."}]}))
cday = bhome / ".codex" / "sessions" / "2026" / "10" / "27"
cday.mkdir(parents=True)
crol = cday / f"rollout-2026-10-27T10-00-00-{CX}.jsonl"
crol.write_text("".join(json.dumps(e) + "\n" for e in (
    {"type": "session_meta", "timestamp": iso(T4 - 600), "payload": {"id": CX, "cwd": bp}},
    {"type": "event_msg", "timestamp": iso(T4 - 600),
     "payload": {"type": "user_message", "message": "tidy app.py"}},
    {"type": "event_msg", "timestamp": iso(T4 - 590),
     "payload": {"type": "agent_message", "message": "app.py is tidy."}})))
os.utime(crol, (T4 - 590, T4 - 590))
hstore = Path(pe["AHT_ROOT_CLAUDE"]) / enc(hp)
hstore.mkdir(parents=True)
(hstore / f"{SH}.jsonl").write_text(
    cl4(SH, hp, type="user", timestamp=iso(T4 - 7200),
        message={"role": "user", "content": "add a login page"})
    + cl4(SH, hp, type="ai-title", aiTitle="add a login page")
    + cl4(SH, hp, type="assistant", timestamp=iso(T4 - 7100), message={
        "role": "assistant", "content": [{"type": "text", "text": "The login page is there."}]}))
os.utime(hstore / f"{SH}.jsonl", (T4 - 7100, T4 - 7100))
P("config", "--set", "remotes=" + json.dumps({
    "box": {"root": str(pbox)}, "lab": {"ssh": "me@127.0.0.7"},
    "pc": {"ssh": "me@127.0.0.9", "system": "Windows"}}), "--json")
subprocess.run([PY, LAUNCH, "tag", hp, "--apply"], env=pe, capture_output=True)
uid4 = (hpaper / ".aht" / ".project-id").read_text().strip()
(bpaper / ".aht").mkdir()
(bpaper / ".aht" / ".project-id").write_text(uid4 + "\n")     # as a copy of the folder has it
hrel, brel = hpaper / ".aht" / "handover", bpaper / ".aht" / "handover"

# found by its id; the summary made (and masked) there, with the git warning
d = P("pickup", hp, "--from", "box", "--json")
fx4 += fixture_ok(d, "pickup.json", FIXTURES4)
text = d.get("brief") or ""
want_warn = ("On box: branch main, 1 commit not pushed, 1 file not committed. Commit and push "
             "there, then pull here.")
ck(d["_rc"] == 0 and d.get("match", {}).get("how") == "id" and d["match"].get("path") == bp
   and (d.get("source") or {}).get("session") == SB and d.get("mode") == "new"
   and d.get("brief_kind") == "full" and (d.get("git") or {}).get("warning") == want_warn
   and want_warn in d.get("warnings", []),
   f"pick up: box's folder found by the project's id, at another path; the git warning "
   f"({d.get('match')}, {(d.get('git') or {}).get('warning')}, {d.get('blockers') or d.get('error')})")
ck(text.startswith("# Pick up: paper") and "- Folder on box: `" + bp + "`; on mac: `" + hp + "`" in text
   and all(h in text for h in ("## Before going on", "## The latest exchanges", "## Git",
                               "heron: fix the login redirect", "1 commit(s) not pushed"))
   and KEY_A not in json.dumps(d) and "[Anthropic API key" in text
   and f"aht leave-note {hp} --on box" in text,
   f"the summary has its sections, the git warning and the way back; the key is masked "
   f"over there ({text[:600]!r})")
rows4 = {s["agent"]: s for s in d.get("sessions") or []}
ck(set(rows4) == {"claude", "codex"} and rows4["codex"]["id"] == CX
   and rows4["claude"].get("state") == "closed" and not files_in(hrel) and not files_in(brel),
   f"the latest sessions there, Claude Code's and Codex's; a dry run writes nothing "
   f"({d.get('sessions')}, {files_in(hrel)}, {files_in(brel)})")
d = P("pickup", hp, "--from", "box", "--agent", "codex", "--json")
d2 = P("pickup", hp, "--from", "box", "--session", CX, "--json")
ck((d.get("source") or {}).get("session") == CX and (d2.get("source") or {}).get("session") == CX
   and "tidy app.py" in (d.get("brief") or ""),
   f"--agent codex and --session pick Codex's session there ({d.get('source')}, {d2.get('source')})")
# without the marker: by its git origin; without that either: by its place
# below the home folder; two clones with the same origin: both listed, none taken
(bpaper / ".aht" / ".project-id").unlink()
d = P("pickup", hp, "--from", "box", "--json")
ck(d["_rc"] == 0 and d.get("match", {}).get("how") == "origin" and d["match"].get("path") == bp,
   f"pick up: without the marker, found by its git origin ({d.get('match')}, {d.get('blockers')})")
pgit(bpaper, "remote", "remove", "origin")
d = P("pickup", hp, "--from", "box", "--json")
ck(d["_rc"] == 0 and d.get("match", {}).get("how") == "home" and d["match"].get("path") == bp,
   f"… and without the origin, by the same place below the home folder ({d.get('match')})")
pgit(bpaper, "remote", "add", "origin", str(bare))
pgit(bpaper, "fetch", "-q", "origin")
pgit(bpaper, "branch", "-q", "-u", "origin/main", "main")
b2 = bhome / "code" / "paper-copy"
pgit(b2.parent, "clone", "-q", str(bare), str(b2))
d = P("pickup", hp, "--from", "box", "--json")
fx4 += fixture_ok(d, "pickup_blocked.json", FIXTURES4)
cands = sorted(c["path"] for c in d.get("match", {}).get("candidates") or [])
ck(d["_rc"] == 3 and d["match"].get("path") is None and d["match"].get("how") == "origin"
   and cands == sorted([bp, os.path.realpath(str(b2))])
   and any(bp in b and "--there" in b for b in d.get("blockers", [])) and not d.get("brief"),
   f"two folders with the same origin: it blocks and lists both ({d.get('blockers')})")
d = P("pickup", hp, "--from", "box", "--there", bp, "--json")
ck(d["_rc"] == 0 and d.get("match", {}).get("how") == "there" and d["match"].get("path") == bp,
   f"--there names the folder ({d.get('match')}, {d.get('blockers')})")
shutil.rmtree(b2)
(bpaper / ".aht" / ".project-id").write_text(uid4 + "\n")

# --apply writes the summary and the relay here and leaves a copy there
d = P("pickup", hp, "--from", "box", "--apply", "--json")
p1 = d.get("relay") or "?"
ck(d.get("applied") and d.get("brief") == str(hrel / f"relay-{p1}.md")
   and files_in(hrel) == [f"relay-{p1}.json", f"relay-{p1}.md"]
   and files_in(brel) == [f"relay-{p1}.json", f"relay-{p1}.md"]
   and (hrel / f"relay-{p1}.json").read_bytes() == (brel / f"relay-{p1}.json").read_bytes()
   and (hrel / f"relay-{p1}.md").read_bytes() == (brel / f"relay-{p1}.md").read_bytes()
   and d.get("opened") is None and not ptlog.exists(),
   f"pick up --apply: the summary and the relay here, the same copy left there; nothing opens "
   f"({d.get('error') or d.get('warnings')}, {files_in(hrel)}, {files_in(brel)})")
row4 = next((p for p in P("projects", "--json").get("projects", []) if p["real_path"] == hp), {})
fx4 += fixture_ok(row4, "projects.json", FIXTURES4)
inc = (row4.get("relay") or {}).get("incoming") or {}
ck((row4.get("relay") or {}).get("id") == p1 and row4["relay"].get("machine") == "box"
   and row4["relay"].get("remote") == "box" and row4["relay"].get("arrived") is True
   and inc.get("kind") == "pickup" and inc.get("machine") == "box" and inc.get("agent") == "claude"
   and inc.get("brief") == str(hrel / f"relay-{p1}.md"),
   f"projects: the row says the work came here from box ({row4.get('relay')})")
out = here_hook(hp, "a-new-session", "startup")
out2 = here_hook(hp, "another-new-session", "startup")
ck(f"This project's work was picked up here from “box” at " in out
   and f"If the user asks to continue that work, read .aht/handover/relay-{p1}.md first." in out
   and "picked up here" not in out2,
   f"here, the hook tells a new session once: read the summary only if the user asks "
   f"({out!r}, {out2!r})")
d = P("switch", hp, "--back", "--json")
ck(d["_rc"] == 3 and any("between machines" in b for b in d.get("blockers", [])),
   f"Hand Back on one machine does not answer work that came from another ({d.get('blockers')})")
# --open codex: the start line goes to the terminal (here a log); no agent runs
d0 = P("pickup", hp, "--from", "box", "--open", "codex", "--json")
d = P("pickup", hp, "--from", "box", "--open", "codex", "--apply", "--json")
p2 = d.get("relay") or "?"
tl = ptlog.read_text() if ptlog.exists() else ""
ck("You are taking over this project from Claude Code on box" in (d0.get("start_line") or "")
   and d.get("applied") and d.get("opened") == "codex" and str(pstub / "codex") in tl
   and f".aht/handover/relay-{p2}.md" in tl and tl.startswith(f"cd {hp} && ")
   and not pcalls.exists(),
   f"--open codex: the start line opens Codex with the summary, nothing else runs "
   f"({d.get('error')}, {tl[-300:]!r})")
# box's hook: the work was picked up on this Mac
out = box_hook(bp, "box-new-session")
ck(f"This project was picked up on “mac” at " in out and "(Codex)" in out,
   f"box's hook: the work was picked up on mac ({out!r})")

# Leave a Note: the first one hands back what came from box (a catch-up, for
# box's own session); the second is a full summary; two files there
d = P("leave-note", hp, "--on", "box", "--apply", "--json")
n1 = d.get("relay") or "?"
ck(d.get("applied") and d.get("mode") == "back" and d.get("back_of") == p2
   and (d.get("note_for") or {}).get("session") == SB and d.get("brief_kind") == "catchup"
   and (brel / f"relay-{p1}.closed").is_file() and (brel / f"relay-{p2}.closed").is_file()
   and (hrel / f"relay-{p1}.closed").is_file(),
   f"leave a note: it hands the work back, for box's own session, and closes the pickups on "
   f"both machines ({d.get('error') or d.get('blockers')}, {d.get('note_for')})")
d = P("leave-note", hp, "--on", "box", "--json")
fx4 += fixture_ok(d, "leave_note.json", FIXTURES4)
d = P("leave-note", hp, "--on", "box", "--apply", "--json")
n2 = d.get("relay") or "?"
notes = sorted(f for f in files_in(brel) if f.endswith(".json")
               and json.loads((brel / f).read_text()).get("kind") == "note")
ck(d.get("applied") and d.get("mode") == "new" and d.get("note_for") is None
   and notes == sorted([f"relay-{n1}.json", f"relay-{n2}.json"])
   and (brel / f"relay-{n2}.md").is_file()
   and d.get("there_file") == f"{bp}/.aht/handover/relay-{n2}.md"
   and "# Note: paper" in (brel / f"relay-{n2}.md").read_text()
   and "add a login page" in (brel / f"relay-{n2}.md").read_text(),
   f"leave-note twice gives two notes there, the second a full summary ({notes})")
out = box_hook(bp, "box-session-2")
out2 = box_hook(bp, "box-session-3")
said = (f"[aht] “mac” left a note about this project at ")
ck(out.count(said) == 1 and f"read .aht/handover/relay-{n2}.md first" in out
   and "If the user asks to continue that work" in out and said not in out2,
   f"box's hook prints the note line once ({out!r}, {out2!r})")
out = box_hook(bp, SB, "resume")
ck(out.startswith("[aht] ") and f"The full summary: .aht/handover/relay-{n1}.md" in out,
   f"box's own session hears what came back to it ({out[:300]!r})")
n1_text = (brel / f"relay-{n1}.md").read_text()
ck("\nBefore going on: The two copies are at different commits (mac " in out
   and "## Before going on\n\n- The two copies are at different commits (mac " in n1_text
   and ", here " in n1_text.split("## Before going on", 1)[-1].split("\n## ", 1)[0],
   f"the hook's note keeps the note's git warning, as box reads it ({out!r})")
# the note's git warning is written for its reader there; here's stays as it was
(hpaper / "app.py").write_text("print('a draft')\n")
d = P("leave-note", hp, "--on", "box", "--json")
pgit(hpaper, "checkout", "-q", "app.py")
mine_ = "Here: branch main, 1 file not committed. Commit and push here, then pull on box."
theirs = "On mac: branch main, 1 file not committed. Commit and push there, then pull here."
ck((d.get("git") or {}).get("warning") == mine_ and mine_ in d.get("warnings", [])
   and f"## Before going on\n\n- {theirs}\n" in (d.get("brief") or "")
   and "Commit and push here" not in (d.get("brief") or ""),
   f"the note's git warning reads from box's side and names mac; the dry run here keeps "
   f"its own ({(d.get('git') or {}).get('warning')!r}, {(d.get('brief') or '')[:700]!r})")
got = subprocess.run([PY, LAUNCH, "notices", "--json"], env=benv, capture_output=True, text=True)
titles = sorted(n["title"] for n in json.loads(got.stdout).get("notices") or [])
again = subprocess.run([PY, LAUNCH, "notices", "--json"], env=benv, capture_output=True, text=True)
ck(titles == ["mac handed paper back", "mac left a note on paper", "mac picked up paper",
              "mac picked up paper"]
   and not [n for n in json.loads(again.stdout).get("notices") or [] if n["kind"] == "incoming"],
   f"box's notices: one for each relay left there, once ({titles})")

# the work comes back: Pick Up from box now is a catch-up of what happened
# there since the note, for this Mac's own session
time.sleep(1.1)
with open(bstore / f"{SB}.jsonl", "a") as fh:
    t = time.time() + 1
    fh.write(cl4(SB, bp, type="user", timestamp=iso(t), message={
        "role": "user", "content": "pelican: now the logout redirect"})
        + cl4(SB, bp, type="assistant", timestamp=iso(t + 1), message={
            "role": "assistant", "content": [{"type": "text", "text": "logout.py too."}]}))
d = P("pickup", hp, "--from", "box", "--json")
fx4 += fixture_ok(d, "pickup_back.json", FIXTURES4)
text = d.get("brief") or ""
ck(d.get("mode") == "back" and d.get("back_of") == n2 and d.get("brief_kind") == "catchup"
   and (d.get("note_for") or {}).get("session") == SH and d.get("target") == "claude"
   and "pelican: now the logout redirect" in text and "heron" not in text
   and "worked on box" in text and want_warn in text,
   f"back mode: only the exchanges after the note, for this Mac's session ({text[:700]!r})")
d = P("pickup", hp, "--from", "box", "--apply", "--json")
p3 = d.get("relay") or "?"
row4 = next((p for p in P("projects", "--json").get("projects", []) if p["real_path"] == hp), {})
inc = (row4.get("relay") or {}).get("incoming") or {}
out = here_hook(hp, SH)
row5 = next((p for p in P("projects", "--json").get("projects", []) if p["real_path"] == hp), {})
ck(d.get("applied") and (hrel / f"relay-{n2}.closed").is_file()
   and (brel / f"relay-{n2}.closed").is_file()
   and inc.get("kind") == "back" and (inc.get("note_for") or {}).get("session") == SH
   and inc.get("worked_from") and row4["relay"].get("open") is False
   and "worked on box" in out and row5.get("relay") is None,
   f"… which closes the note on both machines; the row shows it until this Mac's session "
   f"heard it from the hook ({row4.get('relay')}, {out[:200]!r}, {row5.get('relay')})")
ck(f"\nBefore going on: {want_warn}\nThe full summary: .aht/handover/relay-{p3}.md" in out,
   f"the hook's catch-up keeps the git warning of what came back from box ({out!r})")

# relay-note only adds relay files, into the folder the caller found
box_op_req = {"op": "relay-note", "path": bp, "project_id": uid4, "side": "to"}
new_id = "20990101-000000-abcd"
refused = [box_op(dict(box_op_req, files={"../x": "a"})),
           box_op(dict(box_op_req, files={f"relay-{n2}.md": "again"})),
           box_op(dict(box_op_req, project_id="0" * 32, files={f"relay-{new_id}.md": "x"})),
           box_op(dict(box_op_req, files={f"relay-{new_id}.md": "x" * (300 * 1024)})),
           box_op(dict(box_op_req, path=str(bhome / "code" / "nope"),
                       files={f"relay-{new_id}.md": "x"})),
           box_op(dict(box_op_req, files={"notes.txt": "x"}))]
errs = [r.get("error") or "" for r in refused]
ck(all(r.get("ok") is False for r in refused) and "plain file name" in errs[0]
   and "is there already" in errs[1] and "project id differs" in errs[2] and "over 200 KB" in errs[3]
   and "no folder" in errs[4] and "not a relay file" in errs[5]
   and not (brel / f"relay-{new_id}.md").exists()
   and (brel / f"relay-{n2}.md").read_text() != "again",
   f"relay-note refuses ../x, an existing name, another project, 300 KB, a missing folder and "
   f"other names ({errs})")
ok = box_op(dict(box_op_req, files={f"relay-{new_id}.md": "a note", f"relay-{n2}.closed": "{}"}))
ck(ok.get("ok") and ok.get("written") == [f"relay-{new_id}.md"],
   f"… and adds a new file; a marker that is there already stands ({ok})")

# a machine that does not answer, and a Windows PC, which is never asked
d = P("pickup", hp, "--from", "lab", "--json")
ck(d["_rc"] == 1 and d.get("applied") is False and "cannot reach lab" in (d.get("error") or ""),
   f"pickup from a machine that does not answer fails cleanly ({d.get('error')})")
d = P("leave-note", hp, "--on", "pc", "--json")
ck(core.WINDOWS_FAR.startswith("A Windows PC does this from its own side: on the PC, use Pick "
                               "Up or Leave a Note.")
   and d["_rc"] == 1 and d.get("error") == core.WINDOWS_FAR,
   f"a Windows PC does Pick Up and Leave a Note from its own side ({d.get('error')})")

# an arrival noted while the notices run is told once, by the next run
inc6 = pbase / "inc6"
(inc6 / "run").mkdir(parents=True)
TN = time.time()
(inc6 / "run" / "incoming.jsonl").write_text(json.dumps({
    "at": TN, "relay": "20261027-120000-abcd", "kind": "note", "side": "to", "back": False,
    "path": "/x/paper", "name": "paper", "machine": "box", "agent": "claude"}) + "\n")
probe6 = ("import sys, json; sys.path.insert(0, sys.argv[1]); import aht\n"
          "T = float(sys.argv[2])\n"
          "print(json.dumps([len(aht._incoming_notices(T - 30, T - 1)),\n"
          "                  len(aht._incoming_notices(T - 1, T + 30))]))")
r = subprocess.run([PY, "-c", probe6, str(HERE.parent), repr(TN)],
                   env=dict(pe, AHT_HOME=str(inc6)), capture_output=True, text=True)
ck(r.stdout.strip() == "[0, 1]",
   f"an arrival a moment after the notices' `now` is told once, by the next run "
   f"({r.stdout.strip() or r.stderr[-300:]})")

# a project whose two folders have nothing in common (not the name, the place,
# the id or a git origin), as from a PC to a Mac: what was found once is kept
hT = os.path.realpath(str(Path(pe["HOME"]) / "work" / "thesis-mac"))
bT = os.path.realpath(str(pbase / "srv" / "Drafts" / "thesis-box"))
os.makedirs(hT)
os.makedirs(bT)
SH2 = "7a7a7a7a-1111-4222-8333-444455556666"
SB2 = "8b8b8b8b-1111-4222-8333-444455556666"
(Path(pe["AHT_ROOT_CLAUDE"]) / enc(hT)).mkdir(parents=True)
(Path(pe["AHT_ROOT_CLAUDE"]) / enc(hT) / f"{SH2}.jsonl").write_text(
    cl4(SH2, hT, type="user", timestamp=iso(T4 - 3000),
        message={"role": "user", "content": "osprey: outline chapter two"})
    + cl4(SH2, hT, type="assistant", timestamp=iso(T4 - 2990), message={
        "role": "assistant", "content": [{"type": "text", "text": "Chapter two is outlined."}]}))
os.utime(Path(pe["AHT_ROOT_CLAUDE"]) / enc(hT) / f"{SH2}.jsonl", (T4 - 2990, T4 - 2990))
(bhome / ".claude" / "projects" / enc(bT)).mkdir(parents=True)
(bhome / ".claude" / "projects" / enc(bT) / f"{SB2}.jsonl").write_text(
    cl4(SB2, bT, type="user", timestamp=iso(T4 - 1000),
        message={"role": "user", "content": "kestrel: write the abstract"})
    + cl4(SB2, bT, type="assistant", timestamp=iso(T4 - 990), message={
        "role": "assistant", "content": [{"type": "text", "text": "The abstract is written."}]}))
subprocess.run([PY, LAUNCH, "tag", hT, "--apply"], env=pe, capture_output=True)
hTrel, bTrel = Path(hT, ".aht", "handover"), Path(bT, ".aht", "handover")
def trow():
    return next((p for p in P("projects", "--json").get("projects", [])
                 if p["real_path"] == hT), {})
d = P("pickup", hT, "--from", "box", "--json")
t1 = P("pickup", hT, "--from", "box", "--there", bT, "--apply", "--json").get("relay") or "?"
ck(d["_rc"] == 3 and (hTrel / f"relay-{t1}.json").is_file()
   and (bTrel / f"relay-{t1}.json").is_file(),
   f"the folder there is found only with --there ({d.get('blockers')}, {files_in(hTrel)})")
# a switch to Codex here since: the row's relay is the switch, and
# `pickup_from` still says where the work came from
sw = P("switch", hT, "--to", "codex", "--apply", "--no-window", "--json").get("relay") or "?"
rowT = trow()
t1at = json.loads((hTrel / f"relay-{t1}.json").read_text())["at"]
ck((rowT.get("relay") or {}).get("id") == sw
   and rowT.get("pickup_from") == {"machine": "box", "remote": "box", "relay": t1, "at": t1at,
                                   "agent": "claude", "session": SB2},
   f"projects: pickup_from names the pickup from box whatever the row's relay is "
   f"({rowT.get('relay')}, {rowT.get('pickup_from')})")
# Leave a Note goes back to the folder the pickup recorded, without --there
d = P("leave-note", hT, "--on", "box", "--json")
said = subprocess.run([PY, LAUNCH, "leave-note", hT, "--on", "box"], env=pe, capture_output=True,
                      text=True).stdout
ck(d["_rc"] == 0 and d.get("match") == {"path": bT, "how": "relay",
                                         "candidates": [{"path": bT, "how": "relay"}]}
   and d.get("mode") == "back" and d.get("back_of") == t1
   and f"on     box: {bT} (where the work came from)" in said,
   f"leave-note: the folder there is the one the pickup recorded ({d.get('match')}, "
   f"{d.get('blockers') or d.get('error') or d.get('unparsed')})")
d = P("leave-note", hT, "--on", "box", "--apply", "--json")
nT = d.get("relay") or "?"
ck(d.get("applied") and d.get("brief_kind") == "catchup"
   and (hTrel / f"relay-{t1}.closed").is_file() and (bTrel / f"relay-{t1}.closed").is_file()
   and (bTrel / f"relay-{nT}.md").is_file() and d.get("there_file", "").startswith(bT + "/")
   and trow().get("pickup_from") is None,
   f"… and hands the work back there, closing the pickup on both machines "
   f"({d.get('error') or d.get('blockers')}, {files_in(bTrel)})")
# --full changes only the summary: the work still goes back, and closes
t2 = P("pickup", hT, "--from", "box", "--there", bT, "--apply", "--json").get("relay") or "?"
d = P("leave-note", hT, "--on", "box", "--full", "--apply", "--json")
nT2 = d.get("relay") or "?"
text = (bTrel / f"relay-{nT2}.md").read_text() if (bTrel / f"relay-{nT2}.md").is_file() else ""
ck(d.get("applied") and d.get("mode") == "back" and d.get("back_of") == t2
   and d.get("brief_kind") == "full" and (d.get("note_for") or {}).get("session") == SB2
   and (hTrel / f"relay-{t2}.closed").is_file() and (bTrel / f"relay-{t2}.closed").is_file()
   and text.startswith("# Note: thesis-mac") and "osprey: outline chapter two" in text,
   f"leave-note --full: a full summary that still hands the work back and closes the pickup "
   f"on both machines ({d.get('mode')}, {d.get('brief_kind')}, {d.get('error')}, {text[:300]!r})")
nT3 = P("leave-note", hT, "--on", "box", "--there", bT, "--apply", "--json").get("relay") or "?"
d = P("pickup", hT, "--from", "box", "--there", bT, "--full", "--json")
ck(d.get("mode") == "back" and d.get("back_of") == nT3 and d.get("brief_kind") == "full"
   and (d.get("brief") or "").startswith("# Pick up: thesis-box")
   and "kestrel: write the abstract" in (d.get("brief") or ""),
   f"pickup --full: still the work coming back, with a full summary "
   f"({d.get('mode')}, {d.get('back_of')}, {d.get('brief_kind')})")
# back mode opened in another agent (here a new Codex session): it read the
# summary as its first turn, so the relay is told and hides no other
d = P("pickup", hT, "--from", "box", "--there", bT, "--open", "codex", "--apply",
      "--no-window", "--json")
t3 = d.get("relay") or "?"
rowT = trow()
ck(d.get("applied") and d.get("mode") == "back" and d.get("back_of") == nT3
   and d.get("target") == "codex" and d.get("fallback") and (hTrel / f"relay-{t3}.told").is_file()
   and (rowT.get("relay") or {}).get("id") == sw,
   f"a back-mode pickup opened in Codex is told; the row's relay is the switch again "
   f"({d.get('error') or d.get('blockers')}, {files_in(hTrel)}, {rowT.get('relay')})")

# Keep in sync leaves .aht/handover out, both ways: a note left in the copy
# there stays, and the relays here are not sent
syn = os.path.realpath(str(Path(pe["HOME"]) / "code" / "synced"))
os.makedirs(syn + "/.aht/handover")
Path(syn, "a.txt").write_text("a")
Path(syn, ".aht", "handover", "relay-20990101-000000-0002.md").write_text("here's own")
subprocess.run([PY, LAUNCH, "tag", syn, "--apply"], env=pe, capture_output=True)
copy = Path(str(pbox) + syn)
(copy / ".aht" / "handover").mkdir(parents=True)
(copy / ".aht" / "handover" / "relay-20990101-000000-0001.md").write_text("left there")
(copy / "stale.txt").write_text("gone soon")
# this project's own copy (its id), as an earlier sync left it: no other folder
(copy / ".aht" / ".project-id").write_text(Path(syn, ".aht", ".project-id").read_text())
if core.find_rsync() and short_enough(sb):
    d = P("mirror", syn, "--on", "--to", "box", "--run", "--json")
    ck((copy / "a.txt").is_file() and not (copy / "stale.txt").exists()
       and (copy / ".aht" / "handover" / "relay-20990101-000000-0001.md").read_text() == "left there"
       and not (copy / ".aht" / "handover" / "relay-20990101-000000-0002.md").exists(),
       f"a sync leaves .aht/handover there alone and sends none from here ({d})")
else:
    print("  (skipped: the sync needs rsync 3 and a short sandbox path)")
ck(not fx4, f"the phase-4 JSON keeps the shape of tests/fixtures/phase4 ({fx4})")

done()
