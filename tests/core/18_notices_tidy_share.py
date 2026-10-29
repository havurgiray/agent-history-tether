#!/usr/bin/env python3
"""[18] notices, tidy, changes, report, share, taking a key out."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)

import later_kit

# what earlier sections left: [16]'s stand-in machine "box", named in the
# config (a notice then names its machine; the handover below goes there),
# with its stand-in tools in sb/stubs; [17]'s project "Across" (projX,
# tagged) with its sessions (cstore, cline, T: c1 holds a key) and the
# sqlite3 it imported
import sqlite3
later_kit.box_set_up()
projX, T, cstore, cline = later_kit.across_made()

print("\n[18] notices, tidy, changes, report, share, taking a key out")
nlog = sb / "notices.log"
nenv = {"AHT_NOTIFY_LOG": str(nlog), "AHT_NO_SEARCH_INDEX": "1", "AHT_MACHINE_NAME": "mac"}
# once another machine is set up (the handover tests leave box), a notice
# names its machine, this one too
_cfg = json.loads((sb / ".aht" / "config.json").read_text()) \
    if (sb / ".aht" / "config.json").is_file() else {}
across = "Across on mac" if _cfg.get("remotes") else "Across"
rec = tools / "sessions"
rec.mkdir(exist_ok=True)
worker = subprocess.Popen(["sleep", "600"], cwd="/")
wrec = rec / f"{worker.pid}.json"
def say(status, waiting=None):
    wrec.write_text(json.dumps({"pid": worker.pid, "cwd": projX, "sessionId": "c1",
                                "status": status, **({"waitingFor": waiting} if waiting else {})}))
say("busy")
run("config", "--set", "notify_finished_minutes=0")
run("notices", extra_env=nenv)
say("waiting", "approve Bash")
run("notices", extra_env=nenv)
say("busy"); run("notices", extra_env=nenv)
say("idle"); run("notices", extra_env=nenv)
got = [json.loads(l) for l in nlog.read_text().splitlines()] if nlog.is_file() else []
ck([g["title"] for g in got] == [f"{across} waits for you", f"{across} is done"]
   and got[0]["message"] == "approve Bash",
   f"notices: waiting for you, then done — once each ({[g['title'] for g in got]})")
run("notices", extra_env=nenv)
ck(len(nlog.read_text().splitlines()) == 2, "notices: nothing new, nothing said")
# what a session waits for can quote a command with a key in it: masked where
# it is read, before it goes to another machine or the phone
say("busy"); run("notices", extra_env=nenv)
say("waiting", f"approve Bash: curl -H 'x-api-key: {KEY}' https://api.example.com")
run("notices", extra_env=nenv)
last = json.loads(nlog.read_text().splitlines()[-1])
ck(KEY not in nlog.read_text() and last["title"] == f"{across} waits for you"
   and last["message"].startswith("approve Bash: curl") and "sk-a…" in last["message"],
   f"notices: what a session waits for is masked ({last['message']})")
worker.kill(); worker.wait()
wrec.unlink()

# tidy: a tracked folder that is gone turns up under another name elsewhere
projG = os.path.realpath(str(roots / "Gone Away"))
os.makedirs(projG)
mkstores(projG)
run("tag", projG, "--apply")
uidG = Path(projG, ".aht", ".project-id").read_text().strip()
shutil.rmtree(projG)                         # gone, marker and all
found_again = os.path.realpath(str(roots / "elsewhere" / "Gone Away"))
os.makedirs(found_again)
d = JS("tidy", "--json")
gone = next((m for m in d.get("missing", []) if m["uuid"] == uidG), {})
ck([c["path"] for c in gone.get("candidates", [])] == [found_again],
   f"tidy: a gone folder, and where a folder of that name is now ({gone})")
r = JS("tidy", "--relink", uidG, "--to", found_again, "--apply", "--json")
reg = json.loads((sb / ".aht" / "registry.json").read_text())
ck(r.get("relinked") and reg["projects"][uidG]["real_path"] == found_again
   and (tools / "claude" / enc(found_again)).is_dir(),
   "tidy --relink: the project and its history follow to the folder found "
   f"({r}, {reg['projects'][uidG]['real_path']}, "
   f"{sorted(p.name for p in (tools / 'claude').iterdir() if 'Gone' in p.name)})")

# what a session changed, and putting one file back
projC = os.path.realpath(str(roots / "Changes"))
os.makedirs(projC)
Path(projC, "a.py").write_text("x = 2\n")
Path(projC, "new.py").write_text("made by the session\n")
cst = tools / "claude" / enc(projC)
cst.mkdir()
fh = tools / "file-history" / "s9"
fh.mkdir(parents=True)
(fh / "aaaa@v1").write_text("x = 1\n")
(cst / "s9.jsonl").write_text(
    json.dumps({"type": "user", "cwd": projC, "entrypoint": "cli",
                "message": {"role": "user", "content": "change a.py"}}) + "\n"
    + json.dumps({"type": "file-history-snapshot", "snapshot": {"trackedFileBackups": {
        "a.py": {"backupFileName": "aaaa@v1", "version": 1},
        "new.py": {"backupFileName": None, "version": 1}}}}) + "\n")
d = JS("changes", projC, "--json")
states = {f["name"]: f["state"] for f in d.get("files", [])}
diff = next((f["diff"] for f in d.get("files", []) if f["name"] == "a.py"), "")
ck(states == {"a.py": "changed", "new.py": "added"} and "-x = 1" in diff and "+x = 2" in diff,
   f"changes: before the session and now, per file ({states})")
r = JS("changes", projC, "--session", "s9", "--revert", projC + "/a.py", "--apply", "--json")
ck(Path(projC, "a.py").read_text() == "x = 1\n" and r.get("kept")
   and Path(r["kept"]).read_text() == "x = 2\n",
   "changes --revert: the file is back, what it held is kept aside")
from pathlib import PureWindowsPath as _PW
kw = core._kept_path(_PW(r"C:\Users\me\.aht\changes-backups\1"), _PW(r"C:\Users\me\proj\a.txt"))
ku = core._kept_path(_PW(r"C:\k"), _PW(r"\\server\share\proj\a.txt"))
ck(kw == _PW(r"C:\Users\me\.aht\changes-backups\1\Users\me\proj\a.txt")
   and ku == _PW(r"C:\k\proj\a.txt"),
   f"changes --revert on Windows: what was there is kept in the backup folder, not on "
   f"itself ({kw}, {ku})")

# the report and a statement of AI use
d = JS("report", "--json", "--by", "agent")
agents = sorted(r["key"] for r in d.get("rows", []))
ck("Claude Code" in agents and "Kimi Code" in agents
   and all(r["seconds"] >= 0 for r in d.get("rows", [])),
   f"report: time and sessions per agent ({agents})")
d = JS("report", "--project", projX, "--statement", "--json")
ck("Claude Code" in d.get("statement", "") and "Kimi Code" in d.get("statement", ""),
   "report --statement: a draft naming the agents used")

# share a session: no key, no e-mail address, no home folder, no local
# network address (IPv4, link-local, and IPv6 unique local and link-local)
home = str(Path.home())
lan = ["192.168.1.20", "169.254.10.20", "fd7a:115c:a1e0::5a1:2b3c", "fd12:3456:789a:1::1",
       "fe80::1c2b:3a4d:5e6f:7081%en0"]
(cstore / "c3.jsonl").write_text(cline(type="user", timestamp=iso(T + 500), message={
    "role": "user", "content": f"mail me at someone@example.org, file {home}/notes.txt, "
                               f"key {KEY}, on {', '.join(lan)}; std::fd12 and fdab3c1: stay"}))
d = JS("share", projX, "--session", "c3", "--format", "html", "--json")
page = d.get("text", "")
ck(d.get("turns") == 1 and KEY not in page and "someone@example.org" not in page
   and home not in page and "~/notes.txt" in page and "<!doctype html>" in page,
   "share: a clean page — no key, no e-mail address, no home folder")
import html as _html
md = JS("share", projX, "--session", "c3", "--json").get("text", "")
ck(not [a for a in lan for p in (page, md) if a.split("%")[0] in p]
   and md.count("[address]") == len(lan) and "std::fd12 and fdab3c1: stay" in md,
   f"share: no local network address, IPv6 ones too; text like one stays ({md[-300:]!r})")
ck(_html.escape(core.SHARE_NOTE) in page and core.SHARE_NOTE in md
   and "Keys and passwords aht recognises are masked" in md
   and "Look it through before you share it." in md and "local paths are removed" not in md,
   "share: the page says what aht takes out of it, and to look it through")

# taking a found key out of the histories
fp = next(f["fingerprint"] for f in JS("secrets", projX, "--json")["finds"]
          if f["kind"] == "Anthropic API key")
blocker = subprocess.Popen(["sleep", "600"], cwd="/")
(rec / f"{blocker.pid}.json").write_text(json.dumps({"pid": blocker.pid, "cwd": projX,
                                                     "status": "idle"}))
r = run("secrets", "--redact", fp, "--apply")
ck(r.returncode == 3 and KEY in (cstore / "c1.jsonl").read_text(),
   "a key is not taken out while a session is open in that project")
blocker.kill(); blocker.wait()
(rec / f"{blocker.pid}.json").unlink()
d = JS("secrets", "--redact", fp, "--apply", "--json")
kept = list(Path(d.get("kept", "/nonexistent")).rglob("c1.jsonl"))
ck(d.get("applied") and KEY not in (cstore / "c1.jsonl").read_text()
   and "[removed by aht]" in (cstore / "c1.jsonl").read_text()
   and all(json.loads(l) for l in (cstore / "c1.jsonl").read_text().splitlines())
   and kept and KEY in kept[0].read_text(),
   "secrets --redact: gone from the history, which stays valid; the original is kept")

# a long key leaves nothing of itself behind.  For every kind of key aht
# knows, one of full length and one twice as long, alone and where keys
# stand (a header, an assignment, JSON, a web address): no 12 characters of
# it in a row are left, and a known kind of key is named as such.  The keys
# are made up here, in pieces
import random, string
_rk = random.Random(26)
AN = string.ascii_letters + string.digits
def rk(n, al=AN):
    return "".join(_rk.choice(al) for _ in range(n))
def long_keys(x):
    """(kind, the text that holds the key, the part that must not be left) of
    every kind of key redact() knows, `x` times its usual length."""
    body = [rk(64, AN + "+/") for _ in range(25 * x)] + [rk(20, AN + "+/") + "=="]
    pem = ("-----BEGIN RSA PRIV" + "ATE KEY-----\n" + "\n".join(body)
           + "\n-----END RSA PRIV" + "ATE KEY-----")
    pw = rk(24 * x, AN + "!~")
    keys = [("Anthropic API key", "sk-" + "ant-" + "api03-" + rk(93 * x, AN + "_-") + "AA"),
            ("OpenAI API key", "sk-" + "proj-" + rk(156 * x, AN + "_-")),
            ("Groq API key", "gs" + "k_" + rk(52 * x)),
            ("GitHub token", "gh" + "p_" + rk(36 * x)),
            ("GitHub token", "github_" + "pat_" + rk(22 * x) + "_" + rk(59 * x)),
            ("AWS access key", "AK" + "IA" + rk(16 * x, string.ascii_uppercase + string.digits)),
            ("Google API key", "AI" + "za" + rk(35 * x, AN + "_-")),
            ("Slack token", "xo" + "xb-" + rk(12, string.digits) + "-"
             + rk(13, string.digits) + "-" + rk(24 * x)),
            ("Stripe key", "sk_" + "live_" + rk(99 * x)),
            ("Hugging Face token", "hf" + "_" + rk(34 * x)),
            ("npm token", "npm" + "_" + rk(36 * x)),
            ("Tailscale key", "tsk" + "ey-auth-" + rk(12 * x) + "CNTRL-" + rk(33 * x)),
            ("JSON web token", "ey" + "JhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.ey" + "J"
             + rk(200 * x, AN + "_-") + "." + rk(342 * x, AN + "_-")),
            ("password or token", rk(40 * x))]
    return [(k, v, v) for k, v in keys] + [
        ("private key", pem, "\n".join(body)),
        ("password in a web address", f"postgres://deploy:{pw}@db.corp.lan:5432/app", pw)]
PLACES = [("alone", "use {} for the deploy"),
          ("after x-api-key", "curl -H 'x-api-key: {}' https://api.example.com/v1"),
          ("after api_key=", "api_key={}"),
          ("after api_key=, more after it", "api_key={}&v2 was set"),
          ("after a bearer", 'curl -H "Authorization: Bearer {}" https://api.example.com'),
          ("inside JSON", None),
          ("in a web address", "https://api.example.com/v1/items?api_key={}&page=2"),
          ("in a web address's path", "https://hooks.example.com/services/{}/run")]
def kept_runs(text, secret):
    """The runs of 12 characters of `secret` that are still in `text`."""
    return sorted({p[i:i + 12] for p in secret.split("\n") for i in range(len(p) - 11)
                   if p[i:i + 12] in text})
GENERIC = ("password or token", "password in a web address")
bad = []
for x in (1, 2):
    for kind, key, secret in long_keys(x):
        for where, form in PLACES:
            if where.startswith("in a web address") and kind in (
                    "private key", "password in a web address"):
                continue                    # not something a web address holds
            if kind == "password or token" and where in ("alone", "in a web address's path"):
                continue                    # nothing there says a random word is a key
            text = form.format(key) if form else json.dumps({"env": {"API_KEY": key}})
            out = core.redact(text)
            left = kept_runs(out, secret)
            named = [kind] if kind not in GENERIC else GENERIC
            if left or not any(f"[{k}: " in out for k in named):
                bad.append(f"{kind}, {x}x as long, {where}: {left[:2]} in {out[:120]!r}")
ck(not bad, f"redact: nothing of a long key is left, and a known kind of key is named "
            f"({len(bad)}: {bad[:3]})")

# …and nothing of one is left anywhere aht writes what it read: the search
# index, a summary, a notice, the journal and a shared page
projL = os.path.realpath(str(roots / "Long Keys"))
os.makedirs(projL)
lstore = tools / "claude" / enc(projL)
lstore.mkdir()
lkeys = long_keys(2)
def across_400(kind, key):
    """A command in which `key` runs across character 400, where the text of
    a tool call is cut."""
    head = "deploy api_key=" if kind == "password or token" else "deploy --with "
    pad = max(1, 401 - len(key) - len(f"echo  && {head}"))
    return f"echo {'z' * pad} && {head}{key} --now"
lmsgs = [cline(type="ai-title", cwd=projL, aiTitle=f"zebra deploy with {lkeys[0][1]}")]
for i, (kind, key, _s) in enumerate(lkeys):
    lmsgs.append(cline(type="user", cwd=projL, timestamp=iso(T + 600 + i), message={
        "role": "user", "content": f"zebra {i}: curl -H 'Authorization: Bearer {key}' "
                                   "https://api.example.com"}))
    lmsgs.append(cline(type="assistant", cwd=projL, timestamp=iso(T + 601 + i), message={
        "role": "assistant", "content": [
            {"type": "text", "text": f"The zebra call works with api_key={key} now."},
            {"type": "tool_use", "name": "TodoWrite", "input": {"todos": [
                {"content": f"rotate {key}", "status": "pending"}]}},
            {"type": "tool_use", "name": "Bash", "input": {"command": across_400(kind, key)}}]}))
# the last answer asks a question right after a fenced private key
lpem = next(k for kind, k, _s in lkeys if kind == "private key")
lmsgs.append(cline(type="user", cwd=projL, timestamp=iso(T + 700), message={
    "role": "user", "content": "zebra: make me a deploy key"}))
lmsgs.append(cline(type="assistant", cwd=projL, timestamp=iso(T + 701), message={
    "role": "assistant", "content": [{"type": "text", "text": "I made a deploy key:\n\n```\n"
                                      + lpem + "\n```\nShall I put it on the server?"}]}))
(lstore / "L1.jsonl").write_text("".join(lmsgs))
# a second session, named with a key in its own title (/rename)
(lstore / "L2.jsonl").write_text(
    cline(type="user", cwd=projL, timestamp=iso(T + 500), message={
        "role": "user", "content": "zebra notes"})
    + json.dumps({"type": "custom-title", "customTitle": f"zebra notes {lkeys[3][1]}",
                  "sessionId": "L2"}) + "\n")
os.utime(lstore / "L2.jsonl", (T + 500, T + 500))      # L1 stays the latest session
run("tag", projL, "--apply")
JS("search", "zebra", "--json")
db = sqlite3.connect(str(sb / ".aht" / "search.db"))
written = {"the search index": "\n".join(
    [t for (t,) in db.execute("select text from msgs")]
    + [t for (t,) in db.execute("select title from sessions")])}
ltools = db.execute("select count(*) from msgs where text like 'Bash: echo z%'").fetchone()[0]
db.close()
written["a summary"] = "\n".join(core._brief_sections(
    core.session_digest(lstore / "L1.jsonl", projL)))
written["the journal"] = JS("journal", projL, "--json").get("markdown", "")
written["a shared page"] = JS("share", projL, "--session", "L1", "--format", "html",
                              "--json").get("text", "")
written["a shared page with the tools"] = JS("share", projL, "--session", "L1", "--tools",
                                             "--json").get("text", "")
lw = subprocess.Popen(["sleep", "600"], cwd="/")
lw2 = subprocess.Popen(["sleep", "600"], cwd="/")
lrec, lrec2 = rec / f"{lw.pid}.json", rec / f"{lw2.pid}.json"
lrec2.write_text(json.dumps({"pid": lw2.pid, "cwd": projL, "sessionId": "L2",
                             "status": "idle"}))
waits = "approve Bash: " + " && ".join(f"curl -H 'x-api-key: {k}'" for _k, k, _s in lkeys)
for status in ("busy", "waiting"):
    lrec.write_text(json.dumps({"pid": lw.pid, "cwd": projL, "sessionId": "L1",
                                "status": status, "name": f"zebra {lkeys[5][1]}",
                                **({"waitingFor": waits} if status == "waiting" else {})}))
    run("notices", extra_env=nenv)
written["a notice"] = json.loads(nlog.read_text().splitlines()[-1])["message"]
left = [f"{kind} in {where}" for where, text in written.items()
        for kind, _k, secret in lkeys if kept_runs(text, secret)]
unmasked = [where for where, text in written.items()
            if not any(f"[{kind}: " in text for kind, _k, _s in lkeys)]
ck(not left and not unmasked and written["a notice"].startswith("approve Bash")
   and ltools == len(lkeys),
   f"nothing of a long key is left in the search index (a tool's command cut at 400 "
   f"characters too), a summary, a notice, the journal or a shared page ({left[:4]}; "
   f"no key masked in: {unmasked}; {ltools} tool rows)")

# …nor where a session's title, name or last question is shown: the board,
# loose ends, a handover, the sessions list, What Changed, checkpoints, the
# checkup and a restart's plan, the tab names and a saved workspace
# (stand-in iTerm2 tabs, whose titles carry the sessions' names)
ltabs = sb / "long-keys-tabs.json"
ltabs.write_text(json.dumps({
    "/dev/ttysZ1": {"title": "Zebra", "override": True, "pane": 1, "panes": 1, "window": 1, "tab": 1},
    "/dev/ttysZ2": {"title": "", "override": False, "pane": 1, "panes": 1, "window": 1, "tab": 2}}))
lenv = {"AHT_ITERM_TABS": str(ltabs), "AHT_CLAUDE_VERSION": "9.9.9",
        "AHT_TTYS": json.dumps({str(lw.pid): "/dev/ttysZ1", str(lw2.pid): "/dev/ttysZ2"}),
        "AHT_TTY_PROCS": json.dumps({"/dev/ttysZ1": [[lw.pid, "claude --resume L1"]],
                                     "/dev/ttysZ2": [[lw2.pid, "claude"]]}),
        "AHT_CWDS": "{}"}
def mine(rows):
    return [r for r in rows if os.path.realpath(r.get("project") or "/") == projL]
shown = {}
# a saved workspace keeps each tab's title as it is (a restore gives it
# back), so it is saved while the tabs hold no key
wsh = sb / "long-keys-ws" / ".aht"
JS("workspace", "--save", "--json", extra_env=dict(lenv, AHT_HOME=str(wsh)))
shown["a saved workspace"] = [json.loads(f.read_text())
                              for f in (wsh / "workspaces").glob("*.json")]
# then the tabs carry the sessions' names: L2's tab the name it was renamed
# to (aht gives a tab that name), L1's the name asked for in aht's Rename…
# (the session takes it at its next prompt, the tab at once)
ltn = json.loads(ltabs.read_text())
ltn["/dev/ttysZ2"].update(title=f"zebra notes {lkeys[3][1]}", override=True)
ltabs.write_text(json.dumps(ltn))
lnext = f"next {lkeys[5][1]}"                    # an AWS access key: the name fits in 80
lren = JS("tab-names", "--rename", "L1", "--to", lnext, "--json", extra_env=lenv)
ck(lren.get("tab") == "" and json.loads(ltabs.read_text())["/dev/ttysZ1"]["title"] == lnext,
   f"the tabs hold the sessions' names with a key in each ({lren.get('tab')!r})")
b = JS("board", "--local", "--json", extra_env=lenv)
shown["the board"] = mine(b.get("machines", [{}])[0].get("sessions", []))
le = mine(JS("loose-ends", "--json").get("loose_ends", []))
shown["loose ends"] = le
lq = [i for r in le for i in r.get("items", []) if i["kind"] == "question"]
shown["the sessions list"] = mine(JS("sessions", "--json").get("sessions", []))
shown["a project's sessions"] = JS("sessions", projL, "--json").get("sessions", [])
shown["What Changed"] = JS("changes", projL, "--session", "L1", "--json")
JS("checkpoint", projL, "--session", "L1", "--json")
shown["checkpoints"] = JS("undo", projL, "--list", "--json").get("checkpoints", [])
shown["the checkup"] = mine(JS("checkup", "--json", extra_env=lenv).get("sessions", []))
shown["a restart's plan"] = JS("checkup", "--restart", str(lw.pid), "--json", extra_env=lenv)
shown["the tab names"] = mine(JS("tab-names", "--json", extra_env=lenv).get("sessions", []))
shown["the tab names to sync"] = mine(JS("tab-names", "--sync-all", "--json",
                                         extra_env=lenv).get("plan", []))
# the board shows a tab's title and a waiting name masked, as the name: a
# tab named after its session reads as that name (the Mac shows no "tab:"
# line for it)
lb = {r.get("session"): r for r in shown["the board"]}
ck("[AWS access key: " in str(lb.get("L1", {}).get("tab"))
   and "[AWS access key: " in str(lb.get("L1", {}).get("pending_title"))
   and "[GitHub token: " in str(lb.get("L2", {}).get("tab"))
   and lb.get("L2", {}).get("tab") == lb.get("L2", {}).get("title"),
   f"board: a tab's title and a waiting name are masked "
   f"({[(r.get('title'), r.get('tab'), r.get('pending_title')) for r in lb.values()]})")
run("tab-names", "--rename", "L1", "--to", "", extra_env=lenv)
remotes = JS("remote", "list", "--json").get("remotes") or {}
if "box" in remotes and (sb / "stubs" / "claude").exists():
    shown["a handover"] = JS("handover", projL, "--to", "box", "--json", extra_env={
        "AHT_REMOTE_PATH": str(sb / "stubs"), "AHT_CLAUDE": str(sb / "stubs" / "claude"),
        "AHT_NO_MIRROR": "1"})
else:
    print("  SKIP a handover's title: no stand-in machine (the handover test did not run)")
lw.kill(); lw.wait(); lw2.kill(); lw2.wait()
lrec.unlink(); lrec2.unlink()
shown = {k: json.dumps(v, ensure_ascii=False) for k, v in shown.items()}
left = [f"{kind} in {where}" for where, text in shown.items()
        for kind, _k, secret in lkeys if kept_runs(text, secret)]
unmasked = [where for where, text in shown.items()
            if not any(f"[{kind}: " in text for kind, _k, _s in lkeys)]
# a tab's title over 80 characters, a key across character 80: the sync
# plan shows the name it gives (the title cut at 80) masked whole
tkey = "gh" + "p_" + rk(36)
title = "deploy the release candidate to staging with token " + tkey
tplan = core._plan_shown([{"session": "s", "project": projL, "from": None,
                           "to": title[:80], "tab": title}])
if kept_runs(json.dumps(tplan), tkey) or "[GitHub token: " not in tplan[0]["to"] \
        or "tab" in tplan[0]:
    left.append(f"GitHub token in the sync plan's long tab title ({tplan})")
ck(not left and not unmasked and lq and "[private key: " in lq[0]["text"],
   f"nothing of a long key is left in a title, a session's name or a question shown "
   f"anywhere ({left[:4]}; no key masked in: {unmasked}; question: {lq})")

# a search index an older aht built can hold parts of keys: it is built anew
# once.  AHT_OLD_CORE names an older aht.py to build it with; without one,
# an index of this version is made to look like one from before
oe = iso_env("old-index")
ost = Path(oe["AHT_ROOT_CLAUDE"]) / enc(projL)
ost.mkdir(parents=True)
# a GitHub token of the usual length: cut by one character, it was too short
# for its own pattern
okind = "GitHub token"
okey = osecret = "gh" + "p_" + rk(36)
(ost / "o1.jsonl").write_text(cline(type="assistant", cwd=projL, timestamp=iso(T), message={
    "role": "assistant", "content": [
        {"type": "text", "text": "The okapi deploy runs."},
        {"type": "tool_use", "name": "Bash", "input": {"command": across_400(okind, okey)}}]}))
def oindex():
    db = sqlite3.connect(str(Path(oe["AHT_HOME"]) / "search.db"))
    try:
        return (db.execute("pragma user_version").fetchone()[0],
                "\n".join(t for (t,) in db.execute("select text from msgs")))
    finally:
        db.close()
def oleak():
    """An index of before: what an older aht stored for that command."""
    db = sqlite3.connect(str(Path(oe["AHT_HOME"]) / "search.db"))
    db.execute("pragma user_version = 0")
    db.execute("insert into msgs values (?,?,?,?,?,?,?)",
               ("Bash: " + across_400(okind, okey)[:400], "tool", "claude", "o1", projL, T,
                str(ost / "o1.jsonl")))
    db.commit()
    db.close()
old_core = os.environ.get("AHT_OLD_CORE")
if old_core:
    subprocess.run([PY, old_core, "search", "--update", "--quiet"], env=oe, capture_output=True)
else:
    iso_run(oe, "search", "--update", "--quiet")
    oleak()
before = oindex()
d = json.loads(iso_run(oe, "search", "--update", "--json").stdout or "{}")
after = oindex()
again = json.loads(iso_run(oe, "search", "--update", "--json").stdout or "{}")
hits = json.loads(iso_run(oe, "search", "okapi", "--json", "--no-update").stdout or "{}")
ck(kept_runs(before[1], osecret) and (d.get("index") or {}).get("rebuilt") is True
   and not kept_runs(after[1], osecret) and after[0] == core.SEARCH_FORMAT
   and "[GitHub token: " in after[1] and (again.get("index") or {}).get("rebuilt") is False
   and [r["session"] for r in hits.get("results", [])] == ["o1"],
   f"search: an index {'built by ' + old_core if old_core else 'of an older format'} is "
   f"built anew once, and the parts of a key in it are gone ({before[0]} -> {after[0]}, "
   f"{d.get('index')}, {again.get('index')})")
# a rebuild cut short: the index stays marked old, so the next run starts over
oleak()
cut = ("import aht\n"
       "def stop(*a, **k):\n"
       "    raise SystemExit(7)\n"
       "aht._note_session = stop\n"
       "aht.update_search_index()\n")
r = subprocess.run([PY, "-c", cut], env=dict(oe, PYTHONPATH=str(HERE.parent)),
                   capture_output=True, text=True)
mid = oindex()
d = json.loads(iso_run(oe, "search", "--update", "--json").stdout or "{}")
end = oindex()
ck(r.returncode == 7 and mid[0] == 0 and not kept_runs(mid[1], osecret)
   and (d.get("index") or {}).get("rebuilt") is True and end[0] == core.SEARCH_FORMAT
   and not kept_runs(end[1], osecret) and "[GitHub token: " in end[1],
   f"search: a rebuild cut short is done again by the next run ({r.returncode}, "
   f"{mid[0]}, {end[0]}, {d.get('index')})")
# the rebuild takes the old file away: that needs no room, and nothing of
# the old rows stays.  Where it cannot (Windows, while a search reads it;
# here the file refuses to go) its tables are dropped and vacuum clears the
# file.  Either way the index counts as updated at once, so the watcher and
# the hook start no other update while it builds
rebuild = ("import json, os, pathlib, sys, aht\n"
           "old = open(str(aht.search_db()), 'rb')\n"
           "real, asked = pathlib.Path.unlink, []\n"
           "def unlink(self, *a, **k):\n"
           "    asked.append(self.name)\n"
           "    if self.name == 'search.db' and sys.argv[1] == 'busy':\n"
           "        raise PermissionError(13, 'in use', str(self))\n"
           "    return real(self, *a, **k)\n"
           "pathlib.Path.unlink = unlink\n"
           "ages, listed = [], aht.list_sessions\n"
           "def spy(*a, **k):\n"
           "    ages.append(aht._search_age())\n"
           "    return listed(*a, **k)\n"
           "aht.list_sessions = spy\n"
           "st = aht.update_search_index()\n"
           "print(json.dumps({'rebuilt': st['rebuilt'], 'age': ages[0] if ages else None,\n"
           "                  'asked': [n for n in asked if n.startswith('search.db')],\n"
           "                  'gone': os.fstat(old.fileno()).st_nlink == 0}))\n")
odb = Path(oe["AHT_HOME"]) / "search.db"
for how in ("free", "busy"):
    oleak()
    was = kept_runs(odb.read_bytes().decode("latin-1"), osecret)
    r = subprocess.run([PY, "-c", rebuild, how], env=dict(oe, PYTHONPATH=str(HERE.parent)),
                       capture_output=True, text=True)
    try:
        got = json.loads(r.stdout)
    except ValueError:
        got = {"unparsed": r.stdout[-300:] + r.stderr[-300:]}
    now = oindex()
    hits = json.loads(iso_run(oe, "search", "okapi", "--json", "--no-update").stdout or "{}")
    ck(was and got.get("rebuilt") is True
       and got.get("age") is not None and 0 <= got["age"] < 600
       and got.get("asked") ==["search.db-journal", "search.db-wal", "search.db-shm",
                                "search.db"]
       and got.get("gone") is (how == "free")
       and not kept_runs(odb.read_bytes().decode("latin-1"), osecret)
       and now[0] == core.SEARCH_FORMAT
       and [x["session"] for x in hits.get("results", [])] == ["o1"],
       "search: the rebuild " + ("takes the old file away" if how == "free" else
                                 "drops and vacuums a file that cannot go")
       + f", nothing of the old rows is left, and it counts as updated at once ({got})")
# `aht search --rebuild` by hand, an index of the current format whose file
# cannot go: emptied the same way, nothing of the old rows is left
oleak()
db = sqlite3.connect(str(odb))
db.execute(f"pragma user_version = {core.SEARCH_FORMAT}")
db.commit()
db.close()
was = kept_runs(odb.read_bytes().decode("latin-1"), osecret)
by_hand = ("import pathlib, sys, aht\n"
           "old = open(str(aht.search_db()), 'rb')\n"
           "real = pathlib.Path.unlink\n"
           "def unlink(self, *a, **k):\n"
           "    if self.name == 'search.db':\n"
           "        raise PermissionError(13, 'in use', str(self))\n"
           "    return real(self, *a, **k)\n"
           "pathlib.Path.unlink = unlink\n"
           "sys.exit(aht.main(['search', '--rebuild', '--quiet', 'okapi', '--json']))\n")
r = subprocess.run([PY, "-c", by_hand], env=dict(oe, PYTHONPATH=str(HERE.parent)),
                   capture_output=True, text=True)
ck(was and r.returncode == 0 and not kept_runs(odb.read_bytes().decode("latin-1"), osecret)
   and oindex()[0] == core.SEARCH_FORMAT,
   f"search --rebuild: a file that cannot go is emptied, nothing of the old rows is left "
   f"({r.returncode}, {r.stderr[-200:]!r})")
# …and while an update holds the index, the watcher and the hook start no
# other one (it would only wait for the lock)
spawn = ("import fcntl, json, aht\n"
         "seen = []\n"
         "aht.subprocess.Popen = lambda argv, **kw: seen.append(argv[-3:])\n"
         "aht.aht_home().mkdir(parents=True, exist_ok=True)\n"
         "with open(str(aht.search_db()) + '.lock', 'w') as held:\n"
         "    fcntl.flock(held, fcntl.LOCK_EX)\n"
         "    aht._spawn_search_update()\n"
         "    busy = list(seen)\n"
         "aht._spawn_search_update()\n"
         "print(json.dumps({'busy': busy, 'free': seen}))\n")
se = iso_env("spawn-index")
se.pop("AHT_NO_SEARCH_INDEX", None)    # the update this checks (common.py turns it off)
r = subprocess.run([PY, "-c", spawn], env=dict(se, PYTHONPATH=str(HERE.parent)),
                   capture_output=True, text=True)
try:
    got = json.loads(r.stdout)
except ValueError:
    got = {"unparsed": r.stdout[-300:] + r.stderr[-300:]}
ck(got.get("busy") == [] and got.get("free") == [["search", "--update", "--quiet"]],
   f"search: no other update is started while one runs, one is when none runs ({got})")

done()
