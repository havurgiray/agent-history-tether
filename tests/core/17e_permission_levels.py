#!/usr/bin/env python3
"""[17e] the permission level follows the work."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)

# what earlier sections left: until(), the wait helper [17c] defined (copied)
def until(cond, secs=10.0):
    end = time.time() + secs
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.1)
    return bool(cond())

print("\n[17e] the permission level follows the work")
# a sandbox of its own: stand-in agents that note their calls (Codex and Kimi
# write sessions the way the real ones do, Codex with a turn_context per
# turn), terminals noted in a log; box is a folder standing in for another
# machine (its core runs with a home of its own).  No agent runs, no token is
# spent and nothing reaches a real machine
FIXTURES7B = HERE / "fixtures" / "phase7b"
fx7b = []
ve = iso_env("perm")
vbase = Path(ve["HOME"]).parent
vstub = vbase / "stubs"
vstub.mkdir()
vclog, vcx, vkx, vtlog = (vbase / n for n in ("calls.log", "codex.log", "kimi.log",
                                               "terminal.log"))
(vstub / "claude").write_text(f'#!/bin/sh\necho "claude $*" >> "{vclog}"\n'
                              '[ "$1" = "--version" ] && echo "9.9.9 (Claude Code)"\nexit 0\n')
for name in ("agy", "vibe"):
    (vstub / name).write_text(f'#!/bin/sh\necho "{name} $*" >> "{vclog}"\n')
for name in ("codex", "kimi"):
    (vstub / name).write_text(f'#!/bin/sh\nexec "{PY}" "{HERE / f"fake_{name}.py"}" "$@"\n')
(vstub / "tmux").write_text(f'#!/bin/sh\nexec "{PY}" "{HERE / "fake_tmux.py"}" "$@"\n')
for _f in vstub.iterdir():
    _f.chmod(0o755)
(vbase / "no-tabs.json").write_text("{}")
ve.update({f"AHT_CLI_{n.upper()}": str(vstub / n) for n in ("claude", "codex", "kimi", "agy",
                                                            "vibe")})
ve.update(AHT_CLAUDE=str(vstub / "claude"), AHT_TERMINAL_LOG=str(vtlog),
          AHT_FAKE_CODEX_LOG=str(vcx), AHT_FAKE_KIMI_LOG=str(vkx), AHT_CORE_DIR=str(HERE.parent),
          AHT_ITERM_TABS=str(vbase / "no-tabs.json"), AHT_NO_SEARCH_INDEX="1",
          AHT_MACHINE_NAME="mac", AHT_REMOTE_MACHINE_NAME="box", AHT_REMOTE_PATH=str(vstub),
          AHT_CLAUDE_SANDBOX="1", AHT_AGENT_PROCS="[]", AHT_NO_MIRROR="1",
          AHT_CLAUDE_MANAGED_SETTINGS=str(vbase / "no-managed-settings.json"))
(Path(ve["HOME"]) / ".claude").mkdir()
(Path(ve["HOME"]) / ".claude" / "settings.json").write_text(json.dumps({"hooks": {
    "SessionStart": [{"hooks": [{"type": "command", "command": f"{PY} {CLI} hook"}]}]}}))
vuser = Path(ve["AHT_ROOT_CLAUDE"]).parent / "settings.json"     # Claude Code's own settings
def V(*a, **extra):
    r = subprocess.run([PY, LAUNCH, *a], env=dict(ve, **extra), capture_output=True, text=True)
    try:
        d = json.loads(r.stdout)
    except ValueError:
        d = {"unparsed": r.stdout[-400:] + r.stderr[-800:]}
    if isinstance(d, dict):
        d["_rc"] = r.returncode
    return d
def vlines():
    return vtlog.read_text().splitlines() if vtlog.is_file() else []
def vrun(line):
    """What the user's terminal does with a line aht opened."""
    subprocess.run(["/bin/sh", "-c", line], env=ve, capture_output=True, timeout=60)
def vlog(p):
    return [json.loads(l) for l in p.read_text().splitlines()] if p.is_file() else []
q = core.shell_quote

# (1) the pure parts: each agent's flags read, Codex's turn_context, the map
# both ways, never more power, the settings, the start lines of all five
vprobe = r'''
import sys, json, os
sys.path.insert(0, sys.argv[1]); import aht
out = {}
cases = [("claude", ["claude", "--dangerously-skip-permissions"]),
         ("claude", ["claude", "--permission-mode", "bypassPermissions"]),
         ("claude", ["claude", "--permission-mode=acceptEdits", "--model", "opus"]),
         ("claude", ["claude", "--permission-mode", "auto"]),
         ("claude", ["claude", "--permission-mode", "plan"]),
         ("claude", ["claude", "--permission-mode", "dontAsk"]),
         ("claude", ["claude", "--allow-dangerously-skip-permissions"]),
         ("claude", ["claude", "--resume", "x", "--", "--dangerously-skip-permissions"]),
         ("codex", ["codex", "--dangerously-bypass-approvals-and-sandbox"]),
         ("codex", ["codex", "--yolo", "resume", "x"]),
         ("codex", ["codex", "-a", "never", "-s", "workspace-write"]),
         ("codex", ["codex", "--ask-for-approval=never"]),
         ("codex", ["codex", "-a", "never", "-s", "danger-full-access"]),
         ("codex", ["codex", "-a", "never", "--sandbox", "read-only"]),
         ("codex", ["codex", "--full-auto"]),
         ("codex", ["codex", "-a", "on-request", "-s", "workspace-write"]),
         ("codex", ["codex", "-s", "danger-full-access"]),
         ("codex", ["codex", "-a", "on-request"]),
         ("codex", ["codex", "-c", "approval_policy=\"never\"", "-c", "sandbox_mode=danger-full-access"]),
         ("codex", ["codex", "resume", "x"]),
         ("kimi", ["kimi", "--auto", "-S", "s"]), ("kimi", ["kimi", "-y"]),
         ("kimi", ["kimi", "--yolo"]), ("kimi", ["kimi", "-S", "s"]),
         ("agy", ["agy", "--dangerously-skip-permissions"]), ("agy", ["agy", "--mode", "accept-edits"]),
         ("agy", ["agy", "--mode=auto"]), ("agy", ["agy", "--mode", "plan"]),
         ("vibe", ["vibe", "--auto-approve"]), ("vibe", ["vibe", "--yolo"]),
         ("vibe", ["vibe", "--smart-approve"]), ("vibe", ["vibe", "--agent", "accept-edits"]),
         ("vibe", ["vibe", "--agent=auto-approve"]), ("vibe", ["vibe", "--agent", "ask"]),
         ("vibe", ["vibe", "--resume", "x"])]
out["flags"] = [[a, " ".join(v[1:]), aht.flag_level(a, v)] for a, v in cases]
out["rollout"] = [[ap, sb, aht._codex_level(ap, sb, explicit=False)] for ap, sb in (
    ("never", "danger-full-access"), ("never", "workspace-write"), ("never", "read-only"),
    ("on-request", "workspace-write"), ("on-request", "danger-full-access"),
    ("untrusted", "read-only"), ("on-failure", "workspace-write"))]
srcs = [{"level": l, "sandbox": s, "from": "transcript"} for l in aht.PERM_LEVELS
        for s in ((False, True) if l == "never" else (False,))]
grid = {}
for ok in (True, False):
    for src in srcs:
        for t in aht.SWITCH_TARGETS:
            p = aht.perm_for(t, src, "the session you are leaving", sandbox_ok=ok)
            grid[f"{ok}|{src['level']}|{src['sandbox']}|{t}"] = p
out["grid"] = grid
out["more"] = [k for k, p in grid.items()
               if aht._perm_rank(p["level"], p["sandbox"]) > aht._perm_rank(
                   k.split("|")[1], k.split("|")[2] == "True")
               or aht.PERM_LEVELS.index((aht.flag_level(p["agent"], p["flags"]) or {"level": "ask"})["level"])
               > aht.PERM_LEVELS.index(p["level"])]
lines = {}
for t in aht.SWITCH_TARGETS:
    for lv in aht.PERM_LEVELS:
        p = aht.perm_for(t, {"level": lv, "from": "transcript"}, "x")
        lines[f"{t}|{lv}|new"] = aht.agent_start_line(t, "new", None, "read it", p["flags"])
        lines[f"{t}|{lv}|resume"] = aht.agent_start_line(t, "resume", "S1", "read it", p["flags"])
out["lines"] = lines
out["cli"] = {a: aht.agent_cli(a) for a in aht.SWITCH_TARGETS}
out["opinion"] = [aht._opinion_cmd("claude", "claude", "t", ["--dangerously-skip-permissions"]),
                  aht._opinion_cmd("kimi", "kimi", "t", ["--auto"])]
out["kimi_ok"] = [aht.kimi_reads_ok(aht.perm_for("kimi", {"level": lv, "sandbox": sb}, "x"))
                  for lv, sb in (("never", False), ("never", True), ("auto", False), ("ask", False))]
out["nosettings"] = aht._without_settings(["--dangerously-skip-permissions", "--settings", "{}",
                                           "--settings={}", "--model", "opus"])
refused = []
for v in ({"codex": {"edits": ["--dangerously-bypass-approvals-and-sandbox"]}},
          {"kimi": {"auto": ["--auto"]}}, {"claude": {"ask": "--permission-mode auto"}},
          {"nobody": {"never": []}}, {"codex": {"sometimes": []}}, {"vibe": {"never": ["x\n"]}}):
    try:
        aht.perm_flags_table(v, strict=True)
    except ValueError as e:
        refused.append(str(e))
out["refused"] = refused
out["kept"] = aht.perm_flags_table({"codex": {"never": ["-a", "never", "-s", "workspace-write"]},
                                    "claude": {"edits": "--permission-mode plan"},
                                    "kimi": {"auto": ["--auto"]}})
rec = {"v": 1, "id": "20261028-100000-abcd", "kind": "switch", "at": 1.0,
       "from": {"agent": "claude"}, "to": {"agent": "codex"}}
tf = os.path.join(os.environ["HOME"], "tail.jsonl")
with open(tf, "w") as fh:
    fh.write(json.dumps({"type": "user", "permissionMode": "acceptEdits"}) + "\n"
             + json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use",
                           "input": {"permissionMode": "bypassPermissions"}}]}}) + "\n")
out["tail"] = aht._last_record_with(tf, b'"permissionMode"',
                                    lambda x: isinstance(x.get("permissionMode"), str))
sbf = os.path.join(os.environ["AHT_HOME"], "run", "claude-sandbox.json")
out["sandbox_file"] = json.load(open(sbf)) if os.path.isfile(sbf) else None
# every way past agent_permission_flags the review found, refused
bypass = [("codex", ["-anever", "-sdanger-full-access"]), ("codex", ["-capproval_policy=never"]),
          ("codex", ["--approve-for-me"]), ("vibe", ["--agent", "ask", "--auto-approve"]),
          ("claude", ["--settings", '{"permissions":{"defaultMode":"bypassPermissions"}}']),
          ("codex", ["-a", "on-request", "-c", "approval_policy=never"]),
          ("claude", ["--model", "opus", "--permission-mode", "plan", "--dangerously-skip-permissions"])]
out["bypass"] = []
for a, fl in bypass:
    try:
        aht.perm_flags_table({a: {"ask": fl}}, strict=True)
        out["bypass"].append(None)
    except ValueError as e:
        out["bypass"].append(str(e))
out["bypass_kept"] = aht.perm_flags_table({a: {"ask": fl} for a, fl in bypass[:3]})
out["fine"] = aht.perm_flags_table({"codex": {"never": ["-anever", "-sworkspace-write"],
                                              "auto": ["-a", "on-request", "-m", "gpt-5"]},
                                    "claude": {"edits": ["--permission-mode", "acceptEdits",
                                                         "--model", "opus"]}}, strict=True)
out["most"] = [aht.flag_level(a, fl, most=True) for a, fl in bypass[:2]]
# words of a first prompt are no flags: reading stops at the first word that
# is neither an option nor an option's value; Codex's `resume <id>` is no prompt
out["prompt_words"] = [aht.flag_level(a, v) for a, v in (
    ("codex", ["codex", "fix", "it", "--dangerously-bypass-approvals-and-sandbox"]),
    ("codex", ["codex", "resume", "x", "-a", "never", "-s", "danger-full-access"]),
    ("codex", ["codex", "resume", "x", "fix", "--yolo"]),
    ("claude", ["claude", "--model", "opus", "fix", "the", "--dangerously-skip-permissions"]),
    ("claude", ["node", "/usr/local/bin/claude", "--add-dir", "a", "b",
                "--dangerously-skip-permissions"]),
    ("kimi", ["kimi", "-S", "s", "please", "--auto"]),
    ("vibe", ["vibe", "make", "it", "--auto-approve"]),
    ("agy", ["agy", "-i", "read", "it", "--dangerously-skip-permissions"]))]
# a restart keeps a session's own --settings (Claude's sandbox file)
out["restart"] = aht._claude_flags("claude --dangerously-skip-permissions --settings "
                                   "/h/.aht/run/claude-sandbox.json --resume s1")
out["safe"] = [aht._relay_safe(dict(rec, perm=p), rec["id"])["perm"] for p in (
    {"level": "never", "sandbox": True, "flags": ["-a", "never", "-s", "workspace-write"]},
    {"level": "god", "flags": []}, {"level": "auto", "flags": "x"}, None,
    {"level": "auto", "sandbox": True, "flags": ["--yolo"]})]
print(json.dumps(out))
'''
r = subprocess.run([PY, "-c", vprobe, str(HERE.parent)], env=ve, capture_output=True, text=True)
try:
    vp = json.loads(r.stdout)
except ValueError:
    vp = {}
    print("  probe:", r.stderr[-1500:])
want_flags = [("claude", "never"), ("claude", "never"), ("claude", "edits"), ("claude", "auto"),
              ("claude", "ask"), ("claude", "ask"), ("claude", None), ("claude", None),
              ("codex", "never"), ("codex", "never"), ("codex", "never*"), ("codex", "never*"),
              ("codex", "never"), ("codex", "ask"), ("codex", "edits"), ("codex", "edits"),
              ("codex", "auto"), ("codex", "ask"), ("codex", "never"), ("codex", None),
              ("kimi", "never"), ("kimi", "auto"), ("kimi", "auto"), ("kimi", None),
              ("agy", "never"), ("agy", "edits"), ("agy", "auto"), ("agy", "ask"),
              ("vibe", "never"), ("vibe", "never"), ("vibe", "auto"), ("vibe", "edits"),
              ("vibe", "never"), ("vibe", "ask"), ("vibe", None)]
got_flags = [(a, (g["level"] + ("*" if g.get("sandbox") else "")) if g else None)
             for a, _l, g in vp.get("flags") or []]
bad = [(f[1], w, g) for f, w, g in zip(vp.get("flags") or [], want_flags, got_flags) if w != g]
ck(len(got_flags) == len(want_flags) and not bad,
   f"each agent's flags read as a level: Claude's skip-permissions and modes (dontAsk refuses, "
   f"so it asks; a prompt after -- is no flag), Codex's bypass, approvals, sandbox, --full-auto "
   f"and -c, Kimi's --auto and --yolo, agy's modes, Vibe's approvals and agents ({bad})")
ck([tuple(x[:2]) + ((x[2] or {}).get("level"), (x[2] or {}).get("sandbox"))
    for x in vp.get("rollout") or []] == [
       ("never", "danger-full-access", "never", False), ("never", "workspace-write", "never", True),
       ("never", "read-only", "ask", False), ("on-request", "workspace-write", "ask", False),
       ("on-request", "danger-full-access", "auto", False), ("untrusted", "read-only", "ask", False),
       ("on-failure", "workspace-write", "ask", False)],
   f"Codex's turn_context: full bypass, never-ask in its sandbox; on request in the workspace "
   f"sandbox is also its own default, so it reads as ask ({vp.get('rollout')})")
g = vp.get("grid") or {}
gk = lambda ok, l, s, t: g.get(f"{ok}|{l}|{s}|{t}") or {}
ck(gk(True, "never", False, "codex").get("flags") == ["--dangerously-bypass-approvals-and-sandbox"]
   and gk(True, "never", True, "codex").get("flags") == ["-a", "never", "-s", "workspace-write"]
   and gk(True, "never", True, "codex").get("sandbox") is True
   and gk(True, "never", False, "claude").get("flags") == ["--dangerously-skip-permissions"]
   and gk(True, "never", True, "claude").get("flags", [])[:2] == ["--dangerously-skip-permissions",
                                                                 "--settings"]
   and gk(True, "never", True, "claude").get("flags", [""])[-1] == str(
       Path(ve["AHT_HOME"]) / "run" / "claude-sandbox.json")
   and vp.get("sandbox_file") == {"sandbox": {"enabled": True}}
   and gk(False, "never", True, "claude").get("level") == "auto"
   and gk(False, "never", True, "claude").get("flags") == ["--permission-mode", "auto"]
   and all(gk(ok, "never", True, t).get("level") == "auto" for ok in (True, False)
           for t in ("kimi", "agy", "vibe"))
   and gk(True, "never", False, "kimi").get("flags") == ["--auto"]
   and gk(True, "never", False, "agy").get("flags") == ["--dangerously-skip-permissions"]
   and gk(True, "never", False, "vibe").get("flags") == ["--auto-approve"]
   and gk(True, "auto", False, "codex").get("flags") == ["-a", "on-request"]
   and gk(True, "auto", False, "kimi").get("flags") == ["--yolo"]
   and gk(True, "edits", False, "codex").get("flags") == ["-a", "on-request", "-s", "workspace-write"]
   and gk(True, "edits", False, "kimi").get("level") == "ask"
   and "the next stricter level: it has no edits mode" in gk(True, "edits", False, "kimi").get("text", "")
   and gk(True, "edits", False, "vibe").get("flags") == ["--agent", "accept-edits"]
   and gk(True, "edits", False, "agy").get("flags") == ["--mode", "accept-edits"]
   and all(gk(True, "ask", False, t).get("flags") == [] for t in core.SWITCH_TARGETS),
   "the map: Claude's never → Codex's full bypass; inside Claude's sandbox → Codex's sandboxed "
   "never-ask; Codex's sandboxed never → Claude's skip-permissions with its sandbox (a settings "
   "file under ~/.aht, so ps keeps it whole) where it works, else auto; Kimi has no edits "
   "mode, so it asks; ask adds no flag")
ck(g and vp.get("more") == [],
   f"never more power: no next agent's level, nor its flags read back, is above the session's "
   f"({vp.get('more')})")
L = vp.get("lines") or {}
X = {a: q(p) for a, p in (vp.get("cli") or {}).items()}
ck(X and L.get("claude|never|new") == f"{X['claude']} --dangerously-skip-permissions 'read it'"
   and L.get("claude|edits|resume") == f"{X['claude']} --permission-mode acceptEdits --resume S1"
   and L.get("claude|ask|resume") == f"{X['claude']} --resume S1"
   and L.get("codex|never|resume") == f"{X['codex']} --dangerously-bypass-approvals-and-sandbox "
                                       "resume S1 'read it'"
   and L.get("codex|edits|new") == f"{X['codex']} -a on-request -s workspace-write 'read it'"
   and L.get("kimi|never|resume") == f"{X['kimi']} --auto -S S1"
   and L.get("kimi|auto|new") == f"{X['kimi']} --yolo -S <the new session>"
   and L.get("kimi|edits|resume") == f"{X['kimi']} -S S1"
   and L.get("agy|auto|resume", "").startswith(f"{X['agy']} --mode auto ")
   and "--conversation S1 -i 'read it'" in L.get("agy|auto|resume", "")
   and L.get("agy|never|new", "").startswith(f"{X['agy']} --dangerously-skip-permissions ")
   and L.get("vibe|never|resume") == f"{X['vibe']} --auto-approve --resume S1 'read it'"
   and L.get("vibe|auto|new") == f"{X['vibe']} --smart-approve 'read it'"
   and L.get("vibe|edits|new") == f"{X['vibe']} --agent accept-edits 'read it'"
   and len(L) == 40,
   f"the start lines of all five agents at each level: the flags right after the program "
   f"({ {k: v for k, v in L.items() if 'never' in k} })")
ck(vp.get("opinion") == [["claude", "-p", "t" + core.OPINION_NOTE, "--dangerously-skip-permissions",
                          "--output-format", "json"],
                         ["kimi", "-p", "t" + core.OPINION_NOTE, "--output-format", "text"]]
   and vp.get("kimi_ok") == [True, False, False, False]
   and vp.get("nosettings") == ["--dangerously-skip-permissions", "--model", "opus"],
   f"Claude's second-opinion run carries the level's flags; Kimi's run of its own takes none "
   f"(Kimi refuses --auto and --yolo with --prompt, and that run never asks), so it runs only at "
   f"never-ask without a sandbox; the far start keeps --settings out ({vp.get('opinion')}, "
   f"{vp.get('kimi_ok')})")
bp = vp.get("bypass") or []
ck(len(bp) == 7 and all(bp)
   and "-sdanger-full-access asks for never, more than ask" in bp[0] and "approval_policy=never asks for never" in bp[1]
   and "--approve-for-me is not a flag aht knows for Codex" in bp[2]
   and "mixes levels" in bp[3] and "may not hold permissions" in bp[4]
   and "asks for never" in bp[5] and "mixes levels" in bp[6]
   and vp.get("bypass_kept") == {}
   and [x and (x["level"], x["sandbox"]) for x in vp.get("most") or []] == [("never", False),
                                                                           ("never", False)]
   and vp.get("fine") == {"codex": {"never": ["-anever", "-sworkspace-write"],
                                    "auto": ["-a", "on-request", "-m", "gpt-5"]},
                          "claude": {"edits": ["--permission-mode", "acceptEdits", "--model", "opus"]}},
   f"agent_permission_flags: read as the most they could ask for (attached values, -c), only "
   f"known permission and harmless flags, no --settings with permissions, no mixed levels "
   f"({bp}, {vp.get('most')}, {vp.get('fine')})")
pw = [x and x["level"] for x in vp.get("prompt_words") or []]
ck(pw == [None, "never", None, None, "never", None, None, None]
   and vp.get("restart") == ["--dangerously-skip-permissions", "--settings",
                             "/h/.aht/run/claude-sandbox.json"],
   f"a command line's flags stop at its first prompt (codex resume <id> read on); a restart keeps "
   f"--settings ({pw}, {vp.get('restart')})")
ck(len(vp.get("refused") or []) == 6
   and "asks for never, more than edits" in (vp.get("refused") or [""])[0]
   and vp.get("kept") == {"codex": {"never": ["-a", "never", "-s", "workspace-write"]},
                          "claude": {"edits": ["--permission-mode", "plan"]}},
   f"agent_permission_flags: a stricter way is taken, more power is refused or left out "
   f"({vp.get('refused')}, {vp.get('kept')})")
ck((vp.get("tail") or {}).get("permissionMode") == "acceptEdits",
   f"the transcript's own permissionMode, not one inside a tool call ({vp.get('tail')})")
ck(vp.get("safe") == [{"level": "never", "sandbox": True,
                       "flags": ["-a", "never", "-s", "workspace-write"]}, None, None, None,
                      {"level": "auto", "sandbox": False, "flags": ["--yolo"]}],
   f"a relay record's perm is kept only as aht writes one ({vp.get('safe')})")

# (2) on this machine.  A Claude Code session started with
# --dangerously-skip-permissions (its transcript says bypassPermissions)
vpaper = os.path.realpath(str(Path(ve["HOME"]) / "code" / "vpaper"))
os.makedirs(vpaper + "/src")
Path(vpaper, "src", "app.py").write_text("old\n")
vgit = lambda *a: subprocess.run(["git", "-C", vpaper, "-c", "user.name=t", "-c",
                                  "user.email=t@example.org", "-c", "commit.gpgsign=false", *a],
                                 capture_output=True, text=True)
vgit("init", "-q", "-b", "main"); vgit("add", "-A"); vgit("commit", "-qm", "First commit")
vstore = Path(ve["AHT_ROOT_CLAUDE"]) / enc(vpaper)
vstore.mkdir(parents=True)
VS, VA, VL, VD, VO = (f"7e{n}00000-1111-4222-8333-444455556666" for n in "12345")
def vsession(sid, at, mode=None, said="fix the login redirect"):
    line = lambda **kw: json.dumps(dict({"cwd": vpaper, "entrypoint": "cli", "sessionId": sid},
                                        **kw)) + "\n"
    extra = {"permissionMode": mode} if mode else {}
    (vstore / f"{sid}.jsonl").write_text(
        line(type="user", timestamp=iso(at), message={"role": "user", "content": said}, **extra)
        + line(type="ai-title", aiTitle=said)
        + line(type="assistant", timestamp=iso(at + 30), message={"role": "assistant", "content": [
            {"type": "text", "text": "Done."}]}))
    os.utime(vstore / f"{sid}.jsonl", (at + 30, at + 30))
vT = time.time() - 7200
vsession(VS, vT, "bypassPermissions")
iso_run(ve, "tag", vpaper, "--apply")
d = V("switch", vpaper, "--to", "codex", "--json")
fx7b += fixture_ok(d, "switch_perm.json", FIXTURES7B)
p = d.get("perm") or {}
ck(d.get("_rc") == 0 and p.get("level") == "never" and p.get("from") == "transcript"
   and p.get("read") == "never" and p.get("agent") == "codex"
   and p.get("flags") == ["--dangerously-bypass-approvals-and-sandbox"]
   and p.get("text") == "Codex starts in never-ask mode, like the Claude Code session you are leaving"
   and (d.get("start_line") or "").startswith(f"{q(vstub / 'codex')} "
                                              "--dangerously-bypass-approvals-and-sandbox '"),
   f"switch, dry run: Codex would start with its full bypass, read from the transcript "
   f"({p}, {d.get('blockers') or d.get('unparsed') or d.get('start_line')})")
r = subprocess.run([PY, LAUNCH, "switch", vpaper, "--to", "codex"], env=ve, capture_output=True,
                   text=True)
ck("   level  Codex starts in never-ask mode, like the Claude Code session you are leaving"
   in r.stdout, f"… and says so in words ({r.stdout.strip()[-300:]})")
d = V("switch", vpaper, "--to", "codex", "--brief-only", "--apply", "--json")
ck(d.get("applied") and d.get("perm") is None,
   "Summary Only starts no agent, so it names no level")
d = V("switch", vpaper, "--to", "codex", "--apply", "--json")
vr1 = d.get("relay") or "?"
opened = (vlines() or [""])[-1]
rec1 = json.loads((Path(vpaper) / ".aht" / "handover" / f"relay-{vr1}.json").read_text()) \
    if (Path(vpaper) / ".aht" / "handover" / f"relay-{vr1}.json").is_file() else {}
ck(d.get("applied") and "--dangerously-bypass-approvals-and-sandbox" in opened
   and rec1.get("perm") == {"level": "never", "sandbox": False,
                            "flags": ["--dangerously-bypass-approvals-and-sandbox"]},
   f"switch --apply: the terminal line carries the flag; the relay records the level "
   f"({opened[-200:]}, {rec1.get('perm')})")
vrun(opened)
cx = (vlog(vcx) or [{}])[-1]
ck(cx.get("args", [""])[0] == "--dangerously-bypass-approvals-and-sandbox",
   f"Codex started with its full bypass ({cx.get('args', [])[:3]})")
row = next((x for x in V("relays", vpaper, "--json").get("relays", []) if x["id"] == vr1), {})
ck((row.get("perm") or {}).get("level") == "never", f"relays --json: each relay's level ({row})")
# Hand Back: Codex's turn_context agrees with the relay's level
d = V("switch", vpaper, "--back", "--json")
fx7b += fixture_ok(d, "switch_back_perm.json", FIXTURES7B)
p = d.get("perm") or {}
ck(d.get("_rc") == 0 and p.get("level") == "never" and p.get("from") == "relay"
   and p.get("flags") == ["--dangerously-skip-permissions"]
   and d.get("start_line") == f"{q(vstub / 'claude')} --dangerously-skip-permissions --resume {q(VS)}"
   and p.get("text") == "Claude Code starts in never-ask mode, like the Codex session you are leaving",
   f"hand back, dry run: Claude's own session goes on in never-ask mode ({p}, {d.get('start_line')})")
d = V("switch", vpaper, "--back", "--apply", "--json")
ck(d.get("applied") and (vlines() or [""])[-1] == f"cd {q(vpaper)} && {q(vstub / 'claude')} "
   f"--dangerously-skip-permissions --resume {q(VS)}",
   f"hand back --apply: `claude --dangerously-skip-permissions --resume …` opens "
   f"({d.get('error') or (vlines() or [''])[-1]})")
# auto: Codex on request reads as its own default, the relay keeps auto
vsession(VA, vT + 600, "auto", "make the parser faster")
d = V("switch", vpaper, "--to", "codex", "--session", VA, "--apply", "--json")
vrun((vlines() or [""])[-1])
ck(d.get("applied") and (d.get("perm") or {}).get("flags") == ["-a", "on-request"]
   and (vlog(vcx) or [{}])[-1].get("args", [])[:2] == ["-a", "on-request"],
   f"auto: Codex starts on request ({d.get('perm')})")
d = V("switch", vpaper, "--back", "--json")
p = d.get("perm") or {}
ck(p.get("level") == "auto" and p.get("from") == "relay"
   and p.get("flags") == ["--permission-mode", "auto"],
   f"hand back: Codex's turn_context (on request) agrees with the flags aht gave it, so the "
   f"relay's auto stands ({p})")
V("switch", vpaper, "--back", "--apply", "--json")
# Kimi: its run of its own (-p) never asks and takes no level flag (the stand-in
# refuses --auto and --yolo with -p, as Kimi does), so only at never-ask
n_k = len(vlog(vkx))
d = V("switch", vpaper, "--to", "kimi", "--session", VS, "--apply", "--json")
kx = vlog(vkx)[n_k:]
K1 = d.get("session") or "?"
ck(d.get("applied") and d.get("kimi_reads") is True and d.get("first_prompt") is None
   and kx and kx[0].get("args", [])[:1] == ["-p"]
   and not {"--auto", "--yolo", "-y"} & set(kx[0].get("args", []))
   and (vlines() or [""])[-1].endswith(f"{q(vstub / 'kimi')} --auto -S {q(K1)}"),
   f"never-ask: Kimi reads the summary in its own run, with no level flag, then opens with "
   f"--auto ({[x.get('args', [])[:2] for x in kx]}, {d.get('error')}, "
   f"{(vlines() or [''])[-1][-120:]})")
V("switch", vpaper, "--back", "--apply", "--json")
# below never-ask: no run of its own; Kimi opens and you paste the first prompt
n_k = len(vlog(vkx))
r = subprocess.run([PY, LAUNCH, "switch", vpaper, "--to", "kimi", "--session", VA], env=ve,
                   capture_output=True, text=True)
d = V("switch", vpaper, "--to", "kimi", "--session", VA, "--apply", "--json")
fx7b += fixture_ok(d, "switch_kimi_perm.json", FIXTURES7B)
fp = d.get("first_prompt") or ""
fpf = Path(vpaper, fp.split(" Read ")[-1].split(" first")[0]) if " Read " in fp else None
ck(d.get("applied") and d.get("kimi_reads") is False and len(vlog(vkx)) == n_k
   and (d.get("perm") or {}).get("level") == "auto" and (d.get("perm") or {}).get("flags") == ["--yolo"]
   and (vlines() or [""])[-1].endswith(f"&& {q(vstub / 'kimi')} --yolo")
   and fp.startswith("You are taking over this project from Claude Code. Read .aht/handover/relay-")
   and fpf is not None and fpf.is_file()
   and "   paste  Kimi reads the summary when you send it this (its run of its own never asks, "
       "more than auto mode):" in r.stdout
   and "\n          You are taking over this project from Claude Code. Read " in r.stdout,
   f"below never-ask (auto): no run of its own; `kimi --yolo` opens and the result carries the "
   f"first prompt to paste, which the text prints ({d.get('kimi_reads')}, {fp[:80]}, "
   f"{(vlines() or [''])[-1][-60:]}, {r.stdout[-400:]})")
V("switch", vpaper, "--back", "--apply", "--json")
# Hand Back to Kimi's own session, below never-ask: it opens and you paste the catch-up
d = V("switch", vpaper, "--to", "codex", "--session", K1, "--apply", "--json")
vrun((vlines() or [""])[-1])
V("config", "--set", "agent_permissions=max:auto")
n_k = len(vlog(vkx))
d = V("switch", vpaper, "--back", "--json")
d2 = V("switch", vpaper, "--back", "--apply", "--json")
V("config", "--unset", "agent_permissions")
ck(d.get("target") == "kimi" and d.get("kimi_reads") is False
   and (d.get("start_line") or "").endswith(f"{q(vstub / 'kimi')} --yolo -S {q(K1)}")
   and (d.get("first_prompt") or "").startswith("While you were away, other agents worked on "
                                                "this project. Read .aht/handover/relay-")
   and d2.get("applied") and d2.get("kimi_reads") is False and len(vlog(vkx)) == n_k
   and d2.get("session") == K1
   and (vlines() or [""])[-1].endswith(f"{q(vstub / 'kimi')} --yolo -S {q(K1)}"),
   f"hand back to Kimi below never-ask: its own session opens with --yolo, no run of its own, "
   f"the catch-up to paste ({d.get('start_line')}, {d.get('first_prompt')}, {d2.get('error')})")
# a running Claude session: its command line
sleeper = subprocess.Popen(["sleep", "600"], cwd="/")
vsess = Path(ve["AHT_ROOT_CLAUDE"]).parent / "sessions"
vsess.mkdir(exist_ok=True)
vsession(VL, vT + 900)
(vsess / f"{sleeper.pid}.json").write_text(json.dumps(
    {"pid": sleeper.pid, "cwd": vpaper, "status": "idle", "sessionId": VL}))
d = V("switch", vpaper, "--to", "agy", "--session", VL, "--json",
      AHT_CMDLINES=json.dumps({str(sleeper.pid): f"claude --permission-mode acceptEdits --resume {VL}"}))
p = d.get("perm") or {}
ck(p.get("level") == "edits" and p.get("from") == "command_line"
   and p.get("flags") == ["--mode", "accept-edits"]
   and (d.get("start_line") or "").startswith(f"{q(vstub / 'agy')} --mode accept-edits "),
   f"an open Claude session: its command line (acceptEdits) → agy's accept-edits ({p})")
sbx = str(Path(ve["AHT_HOME"]) / "run" / "claude-sandbox.json")
def vlive(line, mode=None):
    vsession(VL, vT + 900, mode)
    return V("switch", vpaper, "--to", "codex", "--session", VL, "--json",
             AHT_CMDLINES=json.dumps({str(sleeper.pid): line})).get("perm") or {}
p1 = vlive(f"claude --dangerously-skip-permissions --settings {sbx} --resume {VL}")
p2 = vlive(f"claude --dangerously-skip-permissions --resume {VL}", "acceptEdits")
vuser.write_text(json.dumps({"permissions": {"defaultMode": "bypassPermissions"}}))
p3 = vlive(f"claude --resume {VL}", "default")
p4 = vlive(f"claude --resume {VL}")
vuser.unlink()
p5 = vlive("claude fix the --dangerously-skip-permissions flag")
vsession(VL, vT + 900)
ck(os.path.isfile(sbx) and p1.get("level") == "never" and p1.get("sandbox") is True
   and p1.get("flags") == ["-a", "never", "-s", "workspace-write"],
   f"an open Claude session with aht's sandbox settings file (--settings PATH, whole in ps): "
   f"never-ask inside its sandbox → Codex's sandboxed never-ask ({p1})")
ck(p2.get("level") == "edits" and p2.get("from") == "transcript"
   and p3.get("level") == "ask" and p3.get("from") == "transcript"
   and p4.get("level") == "never" and p4.get("from") == "settings",
   f"an open session's command line or settings, no higher than its transcript's permissionMode; "
   f"the user's own settings count ({p2}, {p3}, {p4})")
ck(p5.get("level") == "ask" and not p5.get("flags"),
   f"words of a first prompt are no flags ({p5})")
sleeper.kill(); sleeper.wait()
(vsess / f"{sleeper.pid}.json").unlink()
# a running Codex: its command line, never-ask inside its sandbox
CXL = "c0dec0de-7e7e-4000-8000-000000000001"
cday = Path(ve["AHT_ROOT_CODEX"]) / "2026" / "10" / "28"
cday.mkdir(parents=True, exist_ok=True)
(cday / f"rollout-2026-10-28T09-00-00-{CXL}.jsonl").write_text("".join(json.dumps(e) + "\n" for e in (
    {"type": "session_meta", "timestamp": iso(vT + 1000), "payload": {"id": CXL, "cwd": vpaper}},
    {"type": "event_msg", "timestamp": iso(vT + 1000),
     "payload": {"type": "user_message", "message": "tidy app.py"}})))
procs = json.dumps([{"pid": 4242, "cwd": vpaper,
                     "args": f"codex -a never -s workspace-write resume {CXL}"}])
d = V("switch", vpaper, "--to", "claude", "--session", CXL, "--json", AHT_AGENT_PROCS=procs)
p = d.get("perm") or {}
d0 = V("switch", vpaper, "--to", "claude", "--session", CXL, "--json", AHT_AGENT_PROCS=procs,
       AHT_CLAUDE_SANDBOX="0")
p0 = d0.get("perm") or {}
ck(p.get("level") == "never" and p.get("sandbox") is True and p.get("from") == "command_line"
   and p.get("flags") == ["--dangerously-skip-permissions", "--settings", sbx]
   and "inside its sandbox, like the Codex session you are leaving" in p.get("text", "")
   and any("Codex is still open in this folder" in w for w in d.get("warnings", []))
   and p0.get("level") == "auto" and p0.get("flags") == ["--permission-mode", "auto"]
   and "the next stricter level: its sandbox does not work on this machine" in p0.get("text", ""),
   f"an open Codex in its sandbox (-a never -s workspace-write): Claude with its own sandbox, "
   f"or auto where that does not work ({p}, {p0})")
# … what its command line leaves out comes from its newest turn_context, and
# the lower of the two where they disagree
cxf = cday / f"rollout-2026-10-28T09-00-00-{CXL}.jsonl"
def cxlive(args, ap, sb):
    with open(cxf, "a") as fh:
        fh.write(json.dumps({"type": "turn_context", "timestamp": iso(vT + 1010), "payload": {
            "approval_policy": ap, "sandbox_policy": {"type": sb}}}) + "\n")
    return V("switch", vpaper, "--to", "claude", "--session", CXL, "--json",
             AHT_AGENT_PROCS=json.dumps([{"pid": 4242, "cwd": vpaper, "args": args}])
             ).get("perm") or {}
c1 = cxlive(f"codex -a never resume {CXL}", "never", "read-only")
c2 = cxlive(f"codex -a never -s workspace-write resume {CXL}", "on-request", "workspace-write")
c3 = cxlive(f"codex -a never resume {CXL}", "never", "danger-full-access")
c4 = cxlive(f"codex resume {CXL} fix it with --dangerously-bypass-approvals-and-sandbox",
            "on-request", "workspace-write")
ck(c1.get("read") == "ask" and c2.get("read") == "ask" and c3.get("read") == "never"
   and c3.get("flags") == ["--dangerously-skip-permissions"] and c4.get("read") == "ask",
   f"an open Codex: -a never with the sandbox from its turn_context (read-only: ask; full "
   f"access: never); a turn_context that disagrees: the lower; a prompt's words are no flags "
   f"({c1.get('read')}, {c2.get('read')}, {c3.get('read')}, {c4.get('read')})")
# Claude Code's own settings: the project's defaultMode
vsession(VD, vT + 1200)
Path(vpaper, ".claude").mkdir()
Path(vpaper, ".claude", "settings.json").write_text(json.dumps(
    {"permissions": {"defaultMode": "acceptEdits"}}))
d = V("switch", vpaper, "--to", "vibe", "--session", VD, "--json")
p = d.get("perm") or {}
ck(p.get("level") == "edits" and p.get("from") == "settings"
   and p.get("flags") == ["--agent", "accept-edits"],
   f"Claude Code's settings (defaultMode acceptEdits in the project) → Vibe's accept-edits ({p})")
Path(vpaper, ".claude", "settings.json").write_text(json.dumps(
    {"permissions": {"defaultMode": "bypassPermissions"}}))
Path(vpaper, ".claude", "settings.local.json").write_text(json.dumps(
    {"permissions": {"defaultMode": "auto"}}))
s1 = V("switch", vpaper, "--to", "vibe", "--session", VD, "--json").get("perm") or {}
vman = vbase / "managed-settings.json"
vman.write_text(json.dumps({"permissions": {"defaultMode": "bypassPermissions"}}))
s2 = V("switch", vpaper, "--to", "vibe", "--session", VD, "--json",
       AHT_CLAUDE_MANAGED_SETTINGS=str(vman)).get("perm") or {}
Path(vpaper, ".claude", "settings.local.json").write_text(json.dumps(
    {"permissions": {"defaultMode": "plan"}}))
vuser.write_text(json.dumps({"permissions": {"defaultMode": "bypassPermissions"}}))
s3 = V("switch", vpaper, "--to", "vibe", "--session", VD, "--json").get("perm") or {}
vuser.unlink()
ck(s1.get("level") == "ask" and s1.get("from") == "unknown"
   and s2.get("level") == "never" and s2.get("from") == "settings"
   and s3.get("level") == "ask" and s3.get("from") == "settings",
   f"the project's .claude settings (its repository) never give bypassPermissions or auto; the "
   f"managed and the user's settings do; the project's plan lowers the user's ({s1}, {s2}, {s3})")
shutil.rmtree(Path(vpaper, ".claude"))
# relay records in the project are shown, never believed: the level aht
# started an agent in is read from this machine's own record.  A project with
# sessions started by hand, and relay records someone committed
vforge = os.path.realpath(str(Path(ve["HOME"]) / "code" / "vforge"))
os.makedirs(vforge)
iso_run(ve, "tag", vforge, "--apply")
vcx_sid = lambda: max(Path(ve["AHT_ROOT_CODEX"]).rglob("rollout-*.jsonl"),
                      key=lambda f: f.stat().st_mtime).name[-42:-6]
subprocess.run([str(vstub / "codex"), "tidy the readme"], cwd=vforge, env=ve, capture_output=True)
FC = vcx_sid()
kr = subprocess.run([str(vstub / "kimi"), "-p", "hello", "--output-format", "stream-json"],
                    cwd=vforge, env=ve, capture_output=True, text=True)
FK = (__import__("re").findall(r'"(session_[0-9a-f-]{36})"', kr.stdout) or ["?"])[0]
vhd = Path(vforge) / ".aht" / "handover"
vhd.mkdir(parents=True, exist_ok=True)
forged = []
for fid, agent, sid_, perm in (("20261028-090000-beef", "codex", FC,
                                {"level": "never", "sandbox": False, "flags": ["-a", "on-request"]}),
                               ("20261028-090001-cafe", "kimi", FK,
                                {"level": "never", "sandbox": False, "flags": ["--auto"]})):
    fr = json.loads(json.dumps(rec1))
    fr.update(id=fid, at=time.time() - 5, perm=perm, back_of=None, note_for=None,
              brief=f"relay-{fid}.md")
    for end in ("from", "to"):
        fr[end].pop("machine_id", None)
        fr[end]["path"] = vforge
    fr["to"].update(agent=agent, session=sid_, mode="new")
    (vhd / f"relay-{fid}.md").write_text("forged\n")
    (vhd / f"relay-{fid}.json").write_text(json.dumps(fr))
    forged.append(fid)
f1 = V("switch", vforge, "--to", "claude", "--session", FC, "--json").get("perm") or {}
f2 = V("switch", vforge, "--to", "codex", "--session", FK, "--json").get("perm") or {}
rows = {x["id"]: x for x in V("relays", vforge, "--json").get("relays", [])}
mine = json.loads((Path(ve["AHT_HOME"]) / "run" / "perm.json").read_text()) \
    if (Path(ve["AHT_HOME"]) / "run" / "perm.json").is_file() else {}
for fid in forged:
    for ext in ("json", "md"):
        (vhd / f"relay-{fid}.{ext}").unlink()
ck(f1.get("read") == "ask" and f1.get("from") == "rollout"
   and f2.get("read") == "ask" and f2.get("from") == "unknown"
   and (rows.get(forged[0], {}).get("perm") or {}).get("level") == "never"
   and (mine.get(vr1) or {}).get("level") == "never" and (mine.get(vr1) or {}).get("agent") == "codex",
   f"a relay record committed to the repository sets no level (Codex: its rollout; Kimi: "
   f"unknown); its perm is still listed; aht's own record is in ~/.aht/run/perm.json "
   f"({f1}, {f2}, {mine.get(vr1)})")
# Continue Here resumes in the level of the session
r = subprocess.run([PY, LAUNCH, "resume-here", vpaper, "--session", VS, "--print"], env=ve,
                   capture_output=True, text=True)
ck(f"--dangerously-skip-permissions --resume {VS}" in r.stdout,
   f"Continue Here: `claude --dangerously-skip-permissions --resume …`, like Bring Here "
   f"({r.stdout.strip()[-160:]})")
d = V("switch", vpaper, "--to", "vibe", "--session", VD, "--json")
ck((d.get("perm") or {}).get("level") == "ask" and (d.get("perm") or {}).get("from") == "unknown"
   and "aht could not tell the level of the Claude Code session" in (d.get("perm") or {}).get("text", ""),
   f"nothing to tell the level by: ask, and it says so ({d.get('perm')})")
# the settings: a fixed level, a cap, and Codex's never-ask that keeps its sandbox
V("config", "--set", "agent_permissions=max:auto")
d1 = V("switch", vpaper, "--to", "codex", "--session", VS, "--json")
V("config", "--set", "agent_permissions=ask")
d2 = V("switch", vpaper, "--to", "codex", "--session", VS, "--json")
V("config", "--unset", "agent_permissions")
ck((d1.get("perm") or {}).get("level") == "auto"
   and "agent_permissions caps it there" in (d1.get("perm") or {}).get("text", "")
   and (d2.get("perm") or {}).get("level") == "ask" and (d2.get("perm") or {}).get("flags") == []
   and "as agent_permissions says" in (d2.get("perm") or {}).get("text", ""),
   f"agent_permissions: max:auto caps never at auto; ask starts every next agent asking "
   f"({d1.get('perm')}, {d2.get('perm')})")
r = subprocess.run([PY, LAUNCH, "config", "--set", 'agent_permission_flags={"codex": {"edits": '
                    '["--dangerously-bypass-approvals-and-sandbox"]}}'], env=ve,
                   capture_output=True, text=True)
r2 = subprocess.run([PY, LAUNCH, "config", "--set", "agent_permissions=sometimes"], env=ve,
                    capture_output=True, text=True)
ck(r.returncode == 2 and "more than edits" in r.stderr and r2.returncode == 2,
   f"config refuses flags that ask for more than their level, and a level it does not know "
   f"({r.stderr.strip()}, {r2.stderr.strip()})")
d = V("config", "--set", 'agent_permission_flags={"codex": {"never": ["-a", "never", "-s", '
      '"workspace-write"]}}', "--set", "agent_permissions=follow", "--json")
fx7b += fixture_ok(d, "settings_perm.json", FIXTURES7B, keys=("effective", "defaults"))
ck((d.get("effective") or {}).get("agent_permission_flags") == {
    "codex": {"never": ["-a", "never", "-s", "workspace-write"]}}
   and (d.get("defaults") or {}).get("agent_permissions") == "follow",
   f"config: agent_permission_flags holds Codex's never-ask that keeps its sandbox ({d.get('effective', {}).get('agent_permission_flags')})")
d = V("switch", vpaper, "--to", "codex", "--session", VS, "--json")
p = d.get("perm") or {}
ck(p.get("level") == "never" and p.get("flags") == ["-a", "never", "-s", "workspace-write"]
   and p.get("sandbox") is True and "never-ask mode inside its sandbox" in p.get("text", ""),
   f"… then Codex's never-ask keeps its sandbox ({p})")
V("config", "--unset", "agent_permission_flags", "--unset", "agent_permissions")
# the second opinion runs in the level of the project's latest session
V("config", "--set", "second_opinion=true")
vsession(VO, time.time(), "bypassPermissions", "second opinion please")    # the newest
n_k, n_c = len(vlog(vkx)), len(vclog.read_text()) if vclog.is_file() else 0
d = V("second-opinion", vpaper, "--task", "tidy the parser", "--json")
vo = d.get("id") or "?"
vmeta = Path(ve["AHT_HOME"]) / "opinions" / vo / "meta.json"
until(lambda: vmeta.is_file() and json.loads(vmeta.read_text()).get("finished"), 30)
oc = (vclog.read_text() if vclog.is_file() else "")[n_c:]
ok_ = vlog(vkx)[n_k:]
ck(d.get("applied") and (d.get("perms") or {}).get("claude", {}).get("level") == "never"
   and d.get("agents") == ["claude", "kimi"] and d.get("left_out") == {}
   and "--dangerously-skip-permissions --output-format json" in oc
   and ok_ and ok_[0].get("args", [])[:1] == ["-p"] and "--auto" not in ok_[0].get("args", [])
   and json.loads(vmeta.read_text()).get("perms", {}).get("kimi", {}).get("flags") == []
   and (json.loads(vmeta.read_text()).get("state", {}).get("kimi") or {}).get("state") == "done",
   f"second opinion at never-ask: Claude with skip-permissions, Kimi's run of its own with no "
   f"flag ({d.get('perms') and {a: x['flags'] for a, x in d['perms'].items()}}, {oc[-160:]!r}, "
   f"{[x.get('args', [])[:2] for x in ok_]})")
V("second-opinion", "--discard", vo)
# --dry-run: the level each would work in; nothing is copied or started
vops = Path(ve["AHT_HOME"]) / "opinions"
n_o = len(list(vops.iterdir())) if vops.is_dir() else 0
dd = V("second-opinion", vpaper, "--task", "tidy the parser", "--dry-run", "--json")
VQ = "7e600000-1111-4222-8333-444455556666"
vsession(VQ, time.time() + 60, "default", "an ask-mode session")       # now the newest
da = V("second-opinion", vpaper, "--task", "tidy the parser", "--dry-run", "--json")
fx7b += fixture_ok(da, "second_opinion_dry.json", FIXTURES7B)
r = subprocess.run([PY, LAUNCH, "second-opinion", vpaper, "--task", "tidy the parser", "--dry-run"],
                   env=ve, capture_output=True, text=True)
pc = (da.get("perms") or {}).get("claude") or {}
ck(dd.get("dry_run") is True and not dd.get("applied") and dd.get("agents") == ["claude", "kimi"]
   and set(dd.get("perms") or {}) == {"claude", "kimi"}
   and da.get("dry_run") is True and not da.get("applied") and da.get("agents") == ["claude"]
   and set(da.get("perms") or {}) == {"claude"} and "kimi" in (da.get("left_out") or {})
   and any("Kimi Code is left out: its unattended run never asks" in w
           for w in da.get("warnings") or [])
   and pc.get("level") == "edits" and pc.get("flags") == ["--permission-mode", "acceptEdits"]
   and pc.get("text", "").startswith("Claude Code edits its copy (edits mode); its commands "
                                     "follow")
   and "   left out  Kimi Code is left out" in r.stdout and "(dry run" in r.stdout
   and (len(list(vops.iterdir())) if vops.is_dir() else 0) == n_o,
   f"second-opinion --dry-run: each agent's level and who takes part; below never-ask Kimi is "
   f"left out and says why; Claude edits its own copy (acceptEdits) at ask ({dd.get('agents')}, "
   f"{da.get('agents')}, {da.get('left_out')}, {pc}, {r.stdout[-300:]})")
# … and run at ask: Claude edits its copy, Kimi does not start
n_k, n_c = len(vlog(vkx)), len(vclog.read_text()) if vclog.is_file() else 0
d = V("second-opinion", vpaper, "--task", "tidy the parser", "--json")
vo = d.get("id") or "?"
vmeta = vops / vo / "meta.json"
until(lambda: vmeta.is_file() and json.loads(vmeta.read_text()).get("finished"), 30)
oc = (vclog.read_text() if vclog.is_file() else "")[n_c:]
ck(d.get("applied") and d.get("agents") == ["claude"] and len(vlog(vkx)) == n_k
   and "--permission-mode acceptEdits --output-format json" in oc
   and json.loads(vmeta.read_text()).get("agents") == ["claude"],
   f"second opinion at ask: only Claude works, editing its copy; Kimi is left out "
   f"({d.get('agents')}, {d.get('warnings')}, {oc[-120:]!r})")
V("second-opinion", "--discard", vo)
V("config", "--set", "second_opinion=false")

# (3) across machines: box holds projects of its own (its core runs there)
vbox = vbase / "box"
bxhome = vbox / "home"
(bxhome / ".aht").mkdir(parents=True)
(bxhome / ".aht" / "config.json").write_text("{}")
(bxhome / ".claude" / "projects").mkdir(parents=True)
(bxhome / ".claude.json").write_text("{}")
bxenv = {k: v for k, v in ve.items() if not k.startswith("AHT_")}
bxenv.update(core._sandbox_env(str(bxhome)), AHT_MACHINE_NAME="box", AHT_NO_SEARCH_INDEX="1",
             AHT_ITERM_TABS=str(vbase / "no-tabs.json"), AHT_CLAUDE=str(vstub / "claude"))
def bxrun(*a):
    return subprocess.run([PY, LAUNCH, *a], env=bxenv, capture_output=True, text=True)
V("config", "--set", "remotes=" + json.dumps({"box": {"root": str(vbox), "paths": "home"}}))
V("config", "--set", "handover_keep_awake=false")
def bxclaude(folder, sid, mode, said):
    st = bxhome / ".claude" / "projects" / enc(str(folder))
    st.mkdir(parents=True, exist_ok=True)
    (st / f"{sid}.jsonl").write_text("".join(json.dumps(e) + "\n" for e in (
        {"type": "user", "cwd": str(folder), "sessionId": sid, "version": "9.9.9",
         "timestamp": iso(time.time() - 300), "permissionMode": mode, "entrypoint": "cli",
         "message": {"role": "user", "content": said}},
        {"type": "ai-title", "aiTitle": said})))
# Pick Up → Open in Codex: the level is read on box
hpick = Path(ve["HOME"]) / "code" / "vpick"
(hpick / "src").mkdir(parents=True)
(hpick / "src" / "a.py").write_text("a\n")
iso_run(ve, "tag", str(hpick), "--apply")
bpick = bxhome / "code" / "vpick"
(bpick / ".aht").mkdir(parents=True)
(bpick / ".aht" / ".project-id").write_text((hpick / ".aht" / ".project-id").read_text())
bxclaude(bpick, "b1", "bypassPermissions", "add the search page")
d = V("pickup", str(hpick), "--from", "box", "--open", "codex", "--json")
fx7b += fixture_ok(d, "pickup_perm.json", FIXTURES7B)
p = d.get("perm") or {}
ck(d.get("_rc") == 0 and p.get("level") == "never" and p.get("from") == "transcript"
   and (d.get("source") or {}).get("perm", {}).get("level") == "never"
   and p.get("text") == "Codex starts in never-ask mode, like the Claude Code session on box"
   and (d.get("start_line") or "").startswith(f"{q(vstub / 'codex')} "
                                              "--dangerously-bypass-approvals-and-sandbox "),
   f"pick up → open in Codex: the level read on box, Codex's full bypass here "
   f"({p}, {d.get('blockers') or d.get('error') or d.get('unparsed')})")
d0 = V("pickup", str(hpick), "--from", "box", "--json")
d = V("pickup", str(hpick), "--from", "box", "--open", "codex", "--apply", "--no-window", "--json")
prec = json.loads((hpick / ".aht" / "handover" / f"relay-{d.get('relay')}.json").read_text()) \
    if d.get("relay") else {}
ck(d0.get("perm") is None and d.get("applied")
   and "--dangerously-bypass-approvals-and-sandbox" in (d.get("command_line") or "")
   and (prec.get("perm") or {}).get("level") == "never",
   f"pick up: nothing opens, no level; --apply records it in the relay ({d.get('error')}, {prec.get('perm')})")
# Pick Up → Open in Kimi below never-ask: Kimi opens, you paste the first prompt
V("config", "--set", "agent_permissions=max:auto")
d = V("pickup", str(hpick), "--from", "box", "--open", "kimi", "--json")
r = subprocess.run([PY, LAUNCH, "pickup", str(hpick), "--from", "box", "--open", "kimi"], env=ve,
                   capture_output=True, text=True)
V("config", "--unset", "agent_permissions")
ck(d.get("kimi_reads") is False and d.get("start_line") == q(vstub / "kimi") + " --yolo"
   and (d.get("first_prompt") or "").startswith("You are taking over this project from Claude "
                                                "Code on box. Read .aht/handover/relay-")
   and "   paste  Kimi reads the summary when you send it this" in r.stdout,
   f"pick up → open in Kimi below never-ask: `kimi --yolo` and the first prompt to paste "
   f"({d.get('kimi_reads')}, {d.get('start_line')}, {d.get('first_prompt')}, "
   f"{d.get('blockers') or r.stdout[-200:]})")
# Bring Here: box's session started in acceptEdits goes on here in it
bshop = bxhome / "code" / "vshop"
(bshop / "src").mkdir(parents=True)
(bshop / "src" / "app.py").write_text("print(1)\n")
bxrun("tag", str(bshop), "--apply")
bxclaude(bshop, "s1", "acceptEdits", "refactor the checkout")
d = V("bring", "/home/code/vshop", "--from", "box", "--json")
fx7b += fixture_ok(d, "bring_perm.json", FIXTURES7B)
p = d.get("perm") or {}
ck(d.get("_rc") == 0 and p.get("level") == "edits" and p.get("from") == "transcript"
   and p.get("text") == "Claude Code starts in edits mode, like the session on box",
   f"bring, dry run: the session there started in acceptEdits ({p}, {d.get('blockers') or d.get('error')})")
n_t = len(vlines())
d = V("bring", "/home/code/vshop", "--from", "box", "--apply", "--json")
term = "\n".join(vlines()[n_t:])
ck(d.get("applied") and f"--permission-mode acceptEdits --resume s1" in term
   and "--permission-mode acceptEdits --resume s1" in (d.get("command_line") or ""),
   f"bring --apply: `claude --permission-mode acceptEdits --resume s1` opens here "
   f"({d.get('error') or term[-200:]})")
# Hand Over: never-ask inside Claude's sandbox goes on there in it, then the
# extra arguments
hhand = Path(ve["HOME"]) / "code" / "vhand"
(hhand / "src").mkdir(parents=True)
(hhand / "src" / "a.py").write_text("a\n")
hst = Path(ve["AHT_ROOT_CLAUDE"]) / enc(os.path.realpath(str(hhand)))
hst.mkdir(parents=True)
(hst / "h1.jsonl").write_text(json.dumps(
    {"type": "user", "cwd": os.path.realpath(str(hhand)), "sessionId": "h1", "version": "9.9.9",
     "entrypoint": "cli", "permissionMode": "bypassPermissions",
     "message": {"role": "user", "content": "hand it over"}}) + "\n")
iso_run(ve, "tag", str(hhand), "--apply")
vuser.write_text(json.dumps({"sandbox": {"enabled": True}}))
V("config", "--set", "night_shift=true")
dn = V("night-shift", str(hhand), "--task", "write the tests", "--start", "22:00", "--back",
       "07:00", "--to", "box", "--json")
V("config", "--set", "night_shift=false")
if os.name == "nt" or handover_name(sb) > 255:
    print("  SKIP Hand Over with the level: its stand-ins need macOS or Linux and a short "
          "sandbox path")
else:
    V("config", "--set", 'handover_claude_args=["--model", "opus"]')
    d = V("handover", str(hhand), "--to", "box", "--json")
    d0 = V("handover", str(hhand), "--to", "box", "--json", AHT_CLAUDE_SANDBOX="0")
    fx7b += fixture_ok(d, "handover_perm.json", FIXTURES7B)
    p, p0 = d.get("perm") or {}, d0.get("perm") or {}
    ck(not d.get("blockers") and p.get("level") == "never" and p.get("sandbox") is True
       and p.get("text") == "Claude Code on box starts in never-ask mode inside its sandbox, "
                            "like the session here"
       and p0.get("level") == "auto" and "its sandbox does not work there" in p0.get("text", "")
       and (dn.get("perm") or {}).get("level") == "never",
       f"hand over, dry run: never-ask inside Claude's sandbox there, or auto where that does not "
       f"work; the night shift's plan says it too ({p}, {p0}, {d.get('blockers')}, {dn.get('perm')})")
    d = V("handover", str(hhand), "--to", "box", "--apply", "--json")
    runs = list((bxhome / ".aht" / "remote" / "run").glob("*/command.txt"))
    cmd = runs[0].read_text() if runs else ""
    rset = json.loads((runs[0].parent / "settings.json").read_text()) if runs else {}
    ck(d.get("applied") and "--resume h1 --settings " in cmd
       and " --dangerously-skip-permissions --model opus " in cmd
       and cmd.count("--settings") == 1 and rset.get("sandbox") == {"enabled": True}
       and "SessionStart" in json.dumps(rset),
       f"hand over --apply: the session there starts with --dangerously-skip-permissions, then "
       f"handover_claude_args, Claude's sandbox in its settings file ({d.get('error') or cmd[:300]}, "
       f"{rset.get('sandbox')})")
    for w in (bxhome / ".faketmux").glob("*.json"):     # the stand-in sessions there
        rec = json.loads(w.read_text())
        if rec.get("alive"):
            try:
                os.kill(int(rec["pid"]), 15)
            except OSError:
                pass
    V("config", "--unset", "handover_claude_args")
vuser.unlink()
ck(not fx7b, f"the --json the front-ends read keeps every key of tests/fixtures/phase7b ({fx7b})")

done()
