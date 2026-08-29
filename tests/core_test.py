#!/usr/bin/env python3
"""agent-history-tether core tests: the multi-backend engine, end to end.

Every agent CLI's store is faked under a throwaway sandbox via the AHT_ROOT_*
env overrides, so the suite never touches real agent data and runs on any OS:
  tag -> move+reconcile (dir renames for claude/gemini/cursor/opencode, cwd
  rewrite for codex/copilot with mandatory pre-backup) -> copy duplication ->
  hook backstop -> conflict refusal -> backup/restore -> adoption.
"""
import hashlib, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CLI = str(HERE.parent / "aht.py")
PY = os.environ.get("AHT_PY", sys.executable or "python3")

FAILS = []
def ck(cond, msg):
    print(("  PASS " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)

sb = Path(tempfile.mkdtemp(prefix="aht_core_"))
roots = sb / "roots"
tools = sb / "tools"
for d in ("claude", "gemini", "cursor", "opencode", "codex", "copilot",
          "kimi/sessions", "kimi/user-history"):
    (tools / d).mkdir(parents=True)
(roots / "projA").mkdir(parents=True)

env = dict(os.environ)
env.update({
    "AHT_HOME": str(sb / ".aht"),
    "AHT_ROOTS": str(roots),
    "AHT_ROOT_CLAUDE": str(tools / "claude"),
    "AHT_ROOT_GEMINI": str(tools / "gemini"),
    "AHT_ROOT_CURSOR": str(tools / "cursor"),
    "AHT_ROOT_OPENCODE": str(tools / "opencode"),
    "AHT_ROOT_CODEX": str(tools / "codex"),
    "AHT_ROOT_COPILOT": str(tools / "copilot"),
    "AHT_ROOT_KIMI": str(tools / "kimi" / "sessions"),
    "AHT_NO_ICONS": "1", "AHT_NO_NOTIFY": "1", "AHT_NO_BACKUP": "1",
})
env.pop("AHT_ASSUME", None)

def run(*a, **kw):
    e = dict(env); e.update(kw.pop("extra_env", {}))
    return subprocess.run([PY, CLI, *a], env=e, capture_output=True, text=True)

enc = lambda p: __import__("re").sub(r"[^a-zA-Z0-9]", "-", p)
sha = lambda p: hashlib.sha256(p.encode()).hexdigest()
md5 = lambda p: hashlib.md5(p.encode()).hexdigest()

def mkstores(path):
    """Fake per-tool history for a project at `path` (realpath expected)."""
    (tools / "claude" / enc(path)).mkdir(exist_ok=True)
    (tools / "claude" / enc(path) / "s1.jsonl").write_text(
        json.dumps({"cwd": path}) + "\n"
        + json.dumps({"text": f"see {path}/src/main.py"}) + "\n")
    (tools / "gemini" / sha(path)).mkdir(exist_ok=True)
    (tools / "gemini" / sha(path) / "chat.json").write_text('{"g": 1}')
    (tools / "cursor" / md5(path)).mkdir(exist_ok=True)
    (tools / "cursor" / md5(path) / "store.db").write_text("c")
    (tools / "opencode" / enc(path)).mkdir(exist_ok=True)
    (tools / "opencode" / enc(path) / "session.json").write_text('{"o": 1}')
    day = tools / "codex" / "2026" / "08" / "29"
    day.mkdir(parents=True, exist_ok=True)
    (day / f"rollout-{abs(hash(path)) % 10**8}.jsonl").write_text(
        json.dumps({"type": "session_meta",
                    "payload": {"cwd": path, "id": "x"}}) + "\n"
        + json.dumps({"type": "turn", "text": "hi"}) + "\n")
    (tools / "copilot" / f"sess-{abs(hash(path)) % 10**8}.json").write_text(
        json.dumps({"cwd": path, "summary": "s"}))
    kd = tools / "kimi" / "sessions" / md5(path) / "sess-uuid-1"
    kd.mkdir(parents=True, exist_ok=True)
    (kd / "state.json").write_text('{"version": 1}')
    (kd / "wire.jsonl").write_text('{"k": 1}\n')
    (tools / "kimi" / "user-history" / (md5(path) + ".jsonl")).write_text(
        '{"h": 1}\n')

projA = os.path.realpath(str(roots / "projA"))
(Path(projA) / "src").mkdir()
(Path(projA) / "src" / "main.py").write_text("x")
mkstores(projA)

print("\n[1] tag detects every backend's store")
r = run("tag", projA, "--apply")
ck(r.returncode == 0 and "tagged:" in r.stdout, "tag applied")
for name in ("claude", "gemini", "cursor", "opencode", "kimi"):
    ck(name in r.stdout, f"store detected: {name}")
reg = json.loads((sb / ".aht" / "registry.json").read_text())
uid = list(reg["projects"])[0]
ck((Path(projA) / ".aht" / ".project-id").read_text().strip() == uid,
   "marker written and matches registry")

print("\n[2] move -> reconcile relinks every backend")
shutil.move(projA, str(roots / "projB"))
projB = os.path.realpath(str(roots / "projB"))
r = run("reconcile", "--apply")
d = json.loads(r.stdout)
ck(len(d["applied_moves"]) == 1, "one move applied")
st = d["applied_moves"][0]["stores"]
ck(st.get("claude") == "renamed", f"claude store renamed ({st.get('claude')})")
ck(st.get("gemini") == "renamed", f"gemini store renamed ({st.get('gemini')})")
ck(st.get("cursor") == "renamed", f"cursor store renamed ({st.get('cursor')})")
ck(st.get("opencode") == "renamed", "opencode store renamed")
ck(str(st.get("codex", "")).startswith("rewrote-"), f"codex cwd rewritten ({st.get('codex')})")
ck(str(st.get("copilot", "")).startswith("rewrote-"), "copilot cwd rewritten")
ck(st.get("kimi") == "renamed", "kimi sessions dir renamed")
ck((tools / "kimi" / "sessions" / md5(projB) / "sess-uuid-1" / "wire.jsonl").is_file(),
   "kimi sessions at new md5 key")
ck((tools / "kimi" / "user-history" / (md5(projB) + ".jsonl")).is_file()
   and not (tools / "kimi" / "user-history" / (md5(projA) + ".jsonl")).exists(),
   "kimi user-history companion renamed along")
ck((tools / "claude" / enc(projB)).is_dir(), "claude dir at new key")
ck((tools / "gemini" / sha(projB)).is_dir(), "gemini dir at new sha256 key")
ck((tools / "cursor" / md5(projB)).is_dir(), "cursor dir at new md5 key")
codex_files = list((tools / "codex").rglob("*.jsonl"))
ck(any(projB in f.read_text() for f in codex_files), "codex session points at new path")
ck(not any(projA in f.read_text() for f in codex_files), "old path gone from codex meta")
rewr = list((sb / ".aht" / "backups").rglob("rewrites/*/**/*.jsonl"))
ck(any(projA in f.read_text() for f in rewr),
   "pre-rewrite backup preserves the original codex session")

print("\n[3] copy -> fresh identity + duplicated dir stores")
shutil.copytree(projB, str(roots / "projC"))
projC = os.path.realpath(str(roots / "projC"))
r = run("reconcile", "--notify", extra_env={"AHT_ASSUME": "Duplicate"})
d = json.loads(r.stdout)
ck(len(d["applied_copies"]) == 1, "copy detected and resolved")
ck((tools / "claude" / enc(projC)).is_dir(), "claude history duplicated for the copy")
ck((tools / "gemini" / sha(projC)).is_dir(), "gemini history duplicated for the copy")
idA = (Path(projB) / ".aht" / ".project-id").read_text()
idC = (Path(projC) / ".aht" / ".project-id").read_text()
ck(idA != idC, "copy has a fresh uuid")

print("\n[4] hook backstop: transcript-authoritative claude + generic backends")
shutil.move(projB, str(roots / "projD"))
projD = os.path.realpath(str(roots / "projD"))
hook_in = json.dumps({"cwd": projD,
                      "transcript_path": str(tools / "claude" / enc(projD) / "t.jsonl")})
r = subprocess.run([PY, CLI, "hook"], env=env, input=hook_in,
                   capture_output=True, text=True)
ck(r.returncode == 0, "hook ran")
ck((tools / "claude" / enc(projD)).is_dir(), "hook relinked the claude store")
ck((tools / "gemini" / sha(projD)).is_dir(), "hook relinked the gemini store too")
reg = json.loads((sb / ".aht" / "registry.json").read_text())
ck(reg["projects"][uid]["real_path"] == projD, "registry re-pointed by the hook")

print("\n[5] conflict: an occupied target is refused, others proceed")
projE = os.path.realpath(str(roots / "projE"))
(tools / "claude" / enc(projE)).mkdir()          # squatter on the claude target
(tools / "claude" / enc(projE) / "other.jsonl").write_text("{}")
shutil.move(projD, projE)
r = run("reconcile", "--apply")
d = json.loads(r.stdout)
allm = d["applied_moves"] + d["conflicts"]
ck(len(allm) == 1, "move surfaced")
st = allm[0]["stores"]
ck(str(st.get("claude", "")).startswith("conflict"), "claude target refused (occupied)")
ck(st.get("gemini") == "renamed", "gemini still relinked")
ck((tools / "claude" / enc(projE) / "other.jsonl").is_file(),
   "squatter store untouched")

print("\n[6] backup + restore across backends")
r = run("backup", "--json")
d = json.loads(r.stdout)
ck(d["counts"].get("backed-up", 0) >= 1, "backup pass snapshots")
snapdirs = [p for p in (sb / ".aht" / "backups").iterdir()
            if p.is_dir() and list(p.glob("*.zip"))]
ck(len(snapdirs) >= 1, "zips written")
meta = json.loads(sorted((sb / ".aht" / "backups" / uid)
                         .glob("*.meta.json"))[-1].read_text())
ck("gemini" in meta["backends"] and "codex" in meta["backends"]
   and "kimi" in meta["backends"],
   f"snapshot spans backends ({meta['backends']})")
r = run("backup", "--json")
ck(json.loads(r.stdout)["counts"].get("unchanged", 0) >= 1, "unchanged skip")

# lose two stores + move, restore via the travelling marker
shutil.rmtree(tools / "gemini" / sha(projE), ignore_errors=True)
old_claude = tools / "claude" / enc(projE)
shutil.move(projE, str(roots / "projF"))
projF = os.path.realpath(str(roots / "projF"))
r = run("restore", projF, "--apply", "--json")
d = json.loads(r.stdout)
ck(d["status"] == "restored", "restore applied")
ck((tools / "gemini" / sha(projF)).is_dir(), "gemini store restored at NEW key")
shutil.rmtree(tools / "kimi" / "sessions" / md5(projF), ignore_errors=True)
(tools / "kimi" / "user-history" / (md5(projF) + ".jsonl")).unlink()
r2 = run("restore", projF, "--apply", "--json")
ck((tools / "kimi" / "sessions" / md5(projF)).is_dir()
   and (tools / "kimi" / "user-history" / (md5(projF) + ".jsonl")).is_file(),
   "kimi sessions + companion restored at NEW key")
ck((tools / "claude" / enc(projF)).is_dir(), "claude store restored at NEW key")
ck(d["cwd_rewrites"] >= 1, "restore re-pointed session cwd values")
codex_files = list((tools / "codex").rglob("*.jsonl"))
ck(any(projF in f.read_text() for f in codex_files),
   "live codex session re-pointed at the restored folder's new path")

print("\n[7] adoption after total registry loss (store-corroborated)")
os.remove(sb / ".aht" / "registry.json")
r = run("adopt", "--json")
d = json.loads(r.stdout)
ck(len(d["planned"]) >= 2, f"planned adoptions found ({len(d['planned'])})")
r = run("adopt", "--apply", "--json")
d = json.loads(r.stdout)
ck(len(d["adopted"]) >= 2, "adoption applied")
reg = json.loads((sb / ".aht" / "registry.json").read_text())
ck(any(e["real_path"] == projF for e in reg["projects"].values()),
   "moved+restored project re-adopted")

print("\n[7b] a codex-ONLY project (no marker, no dir store) is discovered")
(roots / "projY").mkdir()
projY = os.path.realpath(str(roots / "projY"))
day = tools / "codex" / "2026" / "08" / "30"
day.mkdir(parents=True, exist_ok=True)
(day / "rollout-only.jsonl").write_text(
    json.dumps({"type": "session_meta", "payload": {"cwd": projY}}) + "\n")
r = run("adopt", "--json")
d = json.loads(r.stdout)
hit = next((a for a in d["planned"] if a["real"] == projY), None)
ck(hit is not None and hit["stores"] == ["codex"],
   "session-store cwd sweep planned the codex-only folder")

print("\n[8] surfaces: keys / status / doctor / projects")
r = run("keys", projF)
d = json.loads(r.stdout)
ck(d["backends"]["gemini"]["keys"][0] == sha(projF), "keys shows gemini sha256")
ck(d["backends"]["claude"]["exists"], "keys shows claude store exists")
r = run("status", "--json")
d = json.loads(r.stdout)
ck(any(b["name"] == "codex" and b["available"] for b in d["backends"]),
   "status lists backend availability")
ck(run("doctor").returncode == 0, "doctor runs")
ck(run("projects").returncode == 0, "projects runs")

print("\n[9] a legacy .claude/.project-id marker is honoured")
(roots / "legacy").mkdir()
legacy = os.path.realpath(str(roots / "legacy"))
(Path(legacy) / ".claude").mkdir()
(Path(legacy) / ".claude" / ".project-id").write_text("deadbeef" * 4 + "\n")
r = run("adopt", "--json")
d = json.loads(r.stdout)
ck(any(a["real"] == legacy for a in d["planned"]),
   "folder with only a .claude marker is planned for adoption")

print("\n[10] per-agent badge marks: 1 / 2 / 4+ symbols, git independent")
snippet = (
    "import sys, json, os; sys.path.insert(0, %r); import aht\n"
    "print(json.dumps({\n"
    "  'one':  aht.desired_marks('x', {'claude': 'd'}),\n"
    "  'two':  aht.desired_marks('x', {'claude': 'd', 'codex': '@sessions'}),\n"
    "  'four': aht.desired_marks('x', {'claude': 'd', 'gemini': 'd',"
    " 'codex': '@sessions', 'cursor': 'd'}),\n"
    "  'none': aht.desired_marks('x', False),\n"
    "  'disc': len(aht.badge_disc_rgba(24, 'codex')),\n"
    "  'count_disc': len(aht.badge_disc_rgba(24, 5)),\n"
    "  'agents': aht.agents_of({'codex': '@sessions', 'claude': 'd',"
    " 'kimi': 'x'}),\n"
    "}))\n" % str(HERE.parent))
r = subprocess.run([PY, "-c", snippet], env=env, capture_output=True, text=True)
d = json.loads(r.stdout)
ck(d["one"] == ["agent:claude"], "single store -> one agent mark")
ck(d["two"] == ["agent:claude", "agent:codex"],
   "two stores -> two marks in stable backend order")
ck(len([m for m in d["four"] if m.startswith("agent:")]) == 4,
   "four stores -> four marks (renderers show the count)")
ck(d["none"] == [], "untethered non-git folder -> no marks")
ck(d["disc"] == 24 * 24 * 4 and d["count_disc"] == 24 * 24 * 4,
   "shared disc rasteriser produces agent and count art")
ck(d["agents"] == ["claude", "codex", "kimi"],
   "agents_of orders names stably (feeds the relink prompt)")
(roots / "projX").mkdir()
projX = os.path.realpath(str(roots / "projX"))
mkstores(projX)
run("tag", projX, "--apply")
reg = json.loads((sb / ".aht" / "registry.json").read_text())
entry = next(e for e in reg["projects"].values() if e["real_path"] == projX)
ck(entry.get("stores", {}).get("codex") == "@sessions",
   "file-backend presence cached in the registry for badge use")
ck(entry.get("stores", {}).get("gemini") == sha(projX),
   "dir-backend store names cached alongside")

print("\n[11] backend store locations are configurable (aht backends)")
custom = sb / "elsewhere" / "kimi-sessions"
custom.mkdir(parents=True)
env_noenv = dict(env)
env_noenv.pop("AHT_ROOT_KIMI")           # let the config layer take over
r = subprocess.run([PY, CLI, "backends", "--set-root", f"kimi={custom}",
                    "--json"], env=env_noenv, capture_output=True, text=True)
row = next(b for b in json.loads(r.stdout)["backends"] if b["name"] == "kimi")
ck(row["root"] == str(custom) and row["root_source"] == "config"
   and row["available"], "config override resolves + shows as [config]")
r = subprocess.run([PY, CLI, "backends", "--json"], env=env,
                   capture_output=True, text=True)
row = next(b for b in json.loads(r.stdout)["backends"] if b["name"] == "kimi")
ck(row["root_source"] == "env", "AHT_ROOT_* env still wins (test isolation)")
r = subprocess.run([PY, CLI, "backends", "--clear-root", "kimi", "--json"],
                   env=env_noenv, capture_output=True, text=True)
row = next(b for b in json.loads(r.stdout)["backends"] if b["name"] == "kimi")
ck(row["root_source"] == "default", "clear-root restores the default")
r = subprocess.run([PY, CLI, "backends", "--set-root", "nope=/x"],
                   env=env_noenv, capture_output=True, text=True)
ck(r.returncode == 2 and "unknown backend" in r.stderr,
   "unknown backend name is rejected")

shutil.rmtree(sb, ignore_errors=True)
print("\nCORE RESULT:", "ALL PASS" if not FAILS else f"{len(FAILS)} FAIL")
for f in FAILS:
    print("  -", f)
sys.exit(1 if FAILS else 0)
