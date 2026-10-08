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
          "kimi/sessions", "kimi/user-history", "kimi-code/sessions"):
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
    "AHT_ROOT_KIMI_CODE": str(tools / "kimi-code" / "sessions"),
    "AHT_NO_ICONS": "1", "AHT_NO_NOTIFY": "1", "AHT_NO_BACKUP": "1",
    "AHT_NO_CHECKPOINT": "1",       # the checkpoint test turns it back on
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

print("\n[3b] copying a PARENT folder duplicates the nested project too")
(roots / "box").mkdir()
shutil.copytree(projC, str(roots / "box" / "projC"))
r = run("reconcile", "--notify", extra_env={"AHT_ASSUME": "Duplicate"})
d = json.loads(r.stdout)
nested = os.path.realpath(str(roots / "box" / "projC"))
ck(any(c["copy_path"] == nested for c in d["applied_copies"]),
   "nested copy inside a pasted parent was detected")
ck((tools / "claude" / enc(nested)).is_dir(),
   "nested copy got its own claude store at its own key")
ck((Path(nested) / ".aht" / ".project-id").read_text()
   != (Path(projC) / ".aht" / ".project-id").read_text(),
   "nested copy has a fresh uuid")

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

print("\n[12] leveled logging: warnings/errors are tagged, filterable, counted")
r = run("logs", "--errors")
ck("[ERROR" in r.stdout and "CONFLICT" in r.stdout,
   "the [5] conflict was logged with an [ERROR] tag")
ck("[INFO" not in r.stdout, "--errors filters info lines out")
r = run("logs", "-n", "5")
ck(r.returncode == 0 and r.stdout.strip(), "plain logs tail works")
r = run("config", "--set", "log_level=nope", "--no-reload")
ck(r.returncode == 2 and "log_level" in r.stderr, "bad log_level rejected")
r = run("doctor")
ck("warnings/errors logged in the last 24h" in r.stdout,
   "doctor surfaces the recent-problems check")
r = run("status", "--json")
ck(json.loads(r.stdout)["log"]["recent_problems"] >= 1,
   "status counts recent problems")

print("\n[13] shared artwork (the infinity mark) + install/uninstall entry points")
probe = r"""
import sys; sys.path.insert(0, sys.argv[1]); import aht
d = 24
b = aht.infinity_rgba(d, (10, 20, 30))
a = [b[i * 4 + 3] for i in range(d * d)]
row = lambda y: a[y * d:(y + 1) * d]
mid = row(11)
mirror = max(abs(p - q) for p, q in zip(mid, mid[::-1]))
flip = max(abs(p - q) for p, q in zip(row(11), row(12)))
print("size", len(b) == d * d * 4)
print("solid", max(a) == 255)
print("crossing", mid[11] > 0 and mid[12] > 0)
print("tips", mid[1] > 0 and mid[22] > 0)
print("hollow-lobes", mid[6] == 0 and mid[17] == 0)
print("corners", a[0] == 0 and a[d - 1] == 0 and a[d * d - 1] == 0)
print("symmetric", mirror <= 2 and flip <= 2)
print("color", b[(11 * d + 11) * 4] == 10 and b[(11 * d + 11) * 4 + 2] == 30)
p = aht.app_icon_png(32)
print("png", p[:8] == b"\x89PNG\r\n\x1a\n")
"""
r = subprocess.run([PY, "-c", probe, str(HERE.parent)], capture_output=True, text=True)
ck(r.returncode == 0 and "False" not in r.stdout,
   "infinity mark: solid symmetric loop, hollow lobes, transparent corners"
   + ("" if r.returncode == 0 else f" ({r.stderr.strip()[-200:]})"))
for line in r.stdout.split("\n"):
    if "False" in line:
        print("        failed check:", line)
r = run("install", "--help")
ck(r.returncode == 0 and "--src" in r.stdout, "aht install --help (no side effects)")
r = run("uninstall", "--help")
ck(r.returncode == 0 and "--purge" in r.stdout, "aht uninstall --help")

print("\n[14] Kimi Code 2.x: bucket key, relink, copy, restore")
probe = r"""
import sys; sys.path.insert(0, sys.argv[1]); import aht
k = aht._key_kimicode
print("real-vector", k("/private/tmp") == "wd_tmp_11fe14a563f7")
print("trailing-slash", k("/private/tmp/") == k("/private/tmp"))
print("backslashes", k("C:\\Users\\me\\My Proj") == k("C:/Users/me/My Proj"))
print("slug-space-caps", k("/x/My Kimi Proj").startswith("wd_my-kimi-proj_"))
print("slug-keeps-dot-dash-underscore", k("/x/a.b-c_d").startswith("wd_a.b-c_d_"))
print("slug-40-cap", k("/x/" + "a" * 60).split("_")[1] == "a" * 40)
print("slug-trim-after-cap", k("/x/" + "a" * 39 + "-bcd").split("_")[1] == "a" * 39)
print("slug-fallback", k("/x/!!!").startswith("wd_workspace_"))
print("hash-len", len(k("/x/y").rsplit("_", 1)[1]) == 12)
"""
r = subprocess.run([PY, "-c", probe, str(HERE.parent)], capture_output=True, text=True)
ck(r.returncode == 0 and "False" not in r.stdout,
   "bucket key matches the CLI's encodeWorkDirKey (real vector + slug rules)"
   + ("" if r.returncode == 0 else f" ({r.stderr.strip()[-200:]})"))
for line in r.stdout.split("\n"):
    if "False" in line:
        print("        failed check:", line)

def kkey(path):
    import re as _re
    norm = _re.sub(r"/+$", "", path.replace("\\", "/"))
    slug = _re.sub(r"^-+|-+$", "", _re.sub(r"[^a-z0-9._-]+", "-",
                                            norm.split("/")[-1].lower()))[:40]
    return f"wd_{slug}_{sha(norm)[:12]}"

khome = tools / "kimi-code"
for d in ("sessions/.index-dirty", "user-history", "file-history", "workspace-trust"):
    (khome / d).mkdir(parents=True, exist_ok=True)
# a quote in the name: inside state.json the path is JSON-escaped, exactly
# like every Windows path (doubled backslashes) is
kname = 'My "Kimi" Proj' if os.name != "nt" else "My Kimi Proj"
(roots / kname).mkdir()
projK = os.path.realpath(str(roots / kname))
SID = "session_11111111-2222-3333-4444-555555555555"
bucket = khome / "sessions" / kkey(projK)
(bucket / SID / "agents" / "main").mkdir(parents=True)
state0 = ('{"version":3,"id":"%s","cwd":%s,"title":"t  x","agents":{"main":{}},'
          '"archived":false}' % (SID, json.dumps(projK)))
(bucket / SID / "state.json").write_text(state0)
wire0 = json.dumps({"type": "msg", "text": f"ran ls in {projK}/src"}) + "\n"
(bucket / SID / "agents" / "main" / "wire.jsonl").write_text(wire0)
(khome / "user-history" / (md5(projK) + ".jsonl")).write_text('{"h":1}\n')
(khome / "file-history" / bucket.name).write_text(
    json.dumps({"sessions": [{"id": SID, "touchedAt": 1}]}))
(khome / "workspace-trust" / bucket.name).write_text(
    json.dumps({"root": projK, "trustedAt": 1}))
other = {"root": "/somewhere/else", "name": "else", "created_at": "c",
         "last_opened_at": "o"}
(khome / "workspaces.json").write_text(json.dumps(
    {"version": 1, "workspaces": {
        "wd_else_000000000000": other,
        bucket.name: {"root": projK, "name": kname, "created_at": "c",
                      "last_opened_at": "o"}},
     "deleted_workspace_ids": []}, separators=(",", ":")))
idx0 = json.dumps({"sessionId": SID, "sessionDir": str(bucket / SID),
                   "workDir": projK}, separators=(",", ":"))
(khome / "session_index.jsonl").write_text(idx0)          # no trailing newline

r = run("tag", projK, "--apply")
ck("kimi-code" in r.stdout, "tag detects the kimi-code bucket")
marks_probe = ("import sys; sys.path.insert(0, sys.argv[1]); import aht; "
               "print(aht.desired_marks(sys.argv[2], True))")
r = subprocess.run([PY, "-c", marks_probe, str(HERE.parent), projK], env=env,
                   capture_output=True, text=True)
ck("'agent:kimi'" in r.stdout and "kimi-code" not in r.stdout,
   f"the badge shows the AGENT (kimi), not the backend name ({r.stdout.strip()})")

shutil.move(projK, str(roots / "Kimi Moved"))
projK2 = os.path.realpath(str(roots / "Kimi Moved"))
(khome / "sessions" / kkey(projK2)).mkdir()          # an EMPTY placeholder bucket
r = run("reconcile", "--apply")
d = json.loads(r.stdout)
mv = [m for m in d["applied_moves"] if m["to"] == projK2]
ck(len(mv) == 1 and mv[0]["stores"].get("kimi-code") == "renamed",
   "bucket renamed (an empty placeholder at the target is not a conflict)")
b2 = khome / "sessions" / kkey(projK2)
ck((b2 / SID / "state.json").is_file() and not bucket.exists(),
   "sessions live under the new path's bucket")
ck((b2 / SID / "state.json").read_text()
   == state0.replace(json.dumps(projK), json.dumps(projK2)),
   "state.json: only the cwd value changed, every other byte kept")
ck((b2 / SID / "agents" / "main" / "wire.jsonl").read_text() == wire0,
   "the transcript is never edited")
ck((khome / "user-history" / (md5(projK2) + ".jsonl")).is_file()
   and not (khome / "user-history" / (md5(projK) + ".jsonl")).exists(),
   "prompt history renamed to md5(new path)")
ck((khome / "file-history" / b2.name).is_file()
   and not (khome / "file-history" / bucket.name).exists(),
   "file-history ledger follows the bucket")
ck((khome / "workspace-trust" / bucket.name).is_file()
   and not (khome / "workspace-trust" / b2.name).exists(),
   "workspace trust is NOT carried to the new location")
cat = json.loads((khome / "workspaces.json").read_text())["workspaces"]
ck(list(cat) == ["wd_else_000000000000", b2.name]
   and cat[b2.name]["root"] == projK2 and cat[b2.name]["name"] == "Kimi Moved"
   and cat["wd_else_000000000000"] == other,
   "workspace catalog: entry renamed in place, others untouched")
lines = (khome / "session_index.jsonl").read_text().split("\n")
ck(lines[0] == idx0 and json.loads(lines[1]) == {
       "sessionId": SID, "sessionDir": str(b2 / SID), "workDir": projK2},
   "session index: old line kept, corrected line APPENDED")
ck(any(f.name.startswith(SID + ".")
       for f in (khome / "sessions" / ".index-dirty").iterdir()),
   "dirty mark left so the CLI re-reads the session")
saved = list((sb / ".aht" / "backups").rglob("rewrites/kimi-code-*/**/state.json"))
ck(any(f.read_text() == state0 for f in saved)
   and list((sb / ".aht" / "backups").rglob("rewrites/kimi-code-*/workspaces.json")),
   "originals were backed up before anything was rewritten")

shutil.copytree(projK2, str(roots / "Kimi Copy"))
projK3 = os.path.realpath(str(roots / "Kimi Copy"))
r = run("reconcile", "--notify", extra_env={"AHT_ASSUME": "Duplicate"})
b3 = khome / "sessions" / kkey(projK3)
copied = [x for x in b3.iterdir() if x.is_dir()] if b3.is_dir() else []
ck(len(copied) == 1 and copied[0].name != SID
   and copied[0].name.startswith("session_"),
   "the duplicate's session has an id of its own")
cst = json.loads((copied[0] / "state.json").read_text()) if copied else {}
ck(cst.get("id") == (copied[0].name if copied else None)
   and cst.get("cwd") == projK3, "duplicate state.json: own id, own cwd")
ck(json.loads((b2 / SID / "state.json").read_text())["cwd"] == projK2
   and (b2 / SID).is_dir(), "the original is untouched by the copy")
ck((khome / "user-history" / (md5(projK3) + ".jsonl")).is_file()
   and not (khome / "file-history" / b3.name).exists(),
   "prompt history duplicated; the original's retention ledger is not shared")

r = run("backup", "--json")
shutil.rmtree(b2)
(khome / "user-history" / (md5(projK2) + ".jsonl")).unlink()
shutil.move(projK2, str(roots / "Kimi Restored"))
projK4 = os.path.realpath(str(roots / "Kimi Restored"))
r = run("restore", projK4, "--apply", "--json")
b4 = khome / "sessions" / kkey(projK4)
ck(json.loads(r.stdout).get("status") == "restored"
   and (b4 / SID / "agents" / "main" / "wire.jsonl").read_text() == wire0,
   "restore lands the sessions in the NEW path's bucket")
ck(json.loads((b4 / SID / "state.json").read_text())["cwd"] == projK4
   and (khome / "user-history" / (md5(projK4) + ".jsonl")).is_file()
   and (khome / "file-history" / b4.name).is_file(),
   "restored state.json cwd re-pointed; companions restored under new keys")

print("\n[15] the store map follows reality after registration")
(roots / "late").mkdir()
late = os.path.realpath(str(roots / "late"))
(tools / "kimi" / "sessions" / md5(late)).mkdir()       # empty dir = no history
r = run("tag", late, "--apply")
ck("(none yet)" in r.stdout, "an EMPTY store directory is not history")
def stores_of(path):
    reg = json.loads((sb / ".aht" / "registry.json").read_text())
    return next((e.get("stores") or {} for e in reg["projects"].values()
                 if e["real_path"] == path), None)
ck(stores_of(late) == {}, "registered with an empty store map")
(tools / "claude" / enc(late)).mkdir()
(tools / "claude" / enc(late) / "s.jsonl").write_text('{"cwd":"x"}\n')
r = subprocess.run([PY, CLI, "hook"], env=env, capture_output=True, text=True,
                   input=json.dumps({"cwd": late}))
ck(sorted(stores_of(late)) == ["claude"],
   "hook: a session in a known folder refreshes its store map")
lb = khome / "sessions" / kkey(late) / "session_late"
lb.mkdir(parents=True)
(lb / "state.json").write_text('{"id":"session_late","cwd":%s}' % json.dumps(late))
day = tools / "codex" / "2026" / "09" / "18"
day.mkdir(parents=True, exist_ok=True)
(day / "rollout-late.jsonl").write_text(json.dumps(
    {"type": "session_meta", "payload": {"cwd": late, "id": "y"}}) + "\n")
r = run("reconcile", "--apply")
ck(sorted(stores_of(late)) == ["claude", "codex", "kimi-code"],
   f"reconcile picks up agents used after registration ({sorted(stores_of(late))})")
r = subprocess.run([PY, "-c", marks_probe, str(HERE.parent), late], env=env,
                   capture_output=True, text=True)
ck(all(m in r.stdout for m in ("agent:claude", "agent:codex", "agent:kimi")),
   f"badge marks follow ({r.stdout.strip()})")
shutil.rmtree(tools / "claude" / enc(late))
r = run("icons", "--refresh")
ck(sorted(stores_of(late)) == ["codex", "kimi-code"],
   "icons --refresh drops a store that no longer exists")
r = run("logs", "-n", "400")
ck("STORES " in r.stdout, "agent-list changes are logged")

print("\n[16] handover: on to another machine, and back")
sys.path.insert(0, str(HERE.parent))
os.environ["AHT_HOME"] = str(sb / ".aht")
import time, unicodedata
import aht as core

def read_text_or_none(p):
    try:
        return Path(p).read_text().strip()
    except OSError:
        return None

def handover_suite():
    box = Path(os.path.realpath(sb)) / "box"    # a folder standing in for the machine
    bhome = box / "home"
    (bhome / ".claude").mkdir(parents=True)
    (bhome / ".claude.json").write_text("{}")
    stubs = sb / "stubs"
    stubs.mkdir()
    fake = f'#!/bin/sh\nexec "{PY}" "{HERE / "fake_tmux.py"}" "$@"\n'
    (stubs / "tmux").write_text(fake)
    (stubs / "byobu").write_text(fake)
    (stubs / "claude").write_text('#!/bin/sh\necho "9.9.9 (Claude Code)"\n')
    for s in stubs.iterdir():
        s.chmod(0o755)
    henv = {"AHT_REMOTE_PATH": str(stubs), "AHT_CLAUDE": str(stubs / "claude"),
            "AHT_NO_MIRROR": "1"}
    def hrun(*a):
        return run(*a, extra_env=henv)
    def J(r):
        try:
            return json.loads(r.stdout)
        except Exception:
            return {"unparsed": r.stdout[-400:] + r.stderr[-400:]}
    def hook(path):
        return subprocess.run([PY, CLI, "hook"], env=dict(env, **henv),
                              capture_output=True, text=True,
                              input=json.dumps({"cwd": path})).stdout
    def project_row(path):
        return next(p for p in J(hrun("projects", "--json"))["projects"]
                    if p["real_path"] == path)
    def open_there():
        return core.running_sessions(home=bhome / ".claude")

    r = hrun("config", "--set", "remotes=" + json.dumps({"box": {"root": str(box)}}))
    ck(r.returncode == 0, "a machine can be named in the config")

    projH = os.path.realpath(str(roots / "Hand Over"))
    os.makedirs(projH + "/sub")
    os.makedirs(projH + "/node_modules/pkg")
    nfd = unicodedata.normalize("NFD", "Stürmer.txt")
    for rel, body in (("a.txt", "a1\n"), ("sub/b.txt", "b1\n"), ("c.txt", "c1\n"),
                      ("d.txt", "d1\n"), (nfd, "umlaut\n"), ("Icon\r", ""),
                      ("node_modules/pkg/x.js", "x\n")):
        Path(projH, rel).write_text(body)
    hstore = tools / "claude" / enc(projH)
    (hstore / "memory").mkdir(parents=True)
    (hstore / "memory" / "MEMORY.md").write_text("- note\n")
    outside = str(Path.home() / "elsewhere" / "notes.md")
    T0 = "".join(json.dumps(e) + "\n" for e in (
        {"type": "user", "cwd": projH, "version": "9.9.9",
         "message": {"role": "user", "content": "first question"}},
        {"type": "user", "isCompactSummary": True,
         "message": {"role": "user", "content": "SUMMARY: the parser is half done"}},
        {"type": "ai-title", "aiTitle": "Parser work"},
        {"type": "user", "message": {"role": "user", "content": "now fix the lexer"}},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "The lexer is fixed."},
            {"type": "tool_use", "name": "Edit", "input": {"file_path": projH + "/a.txt"}},
            {"type": "tool_use", "name": "Read", "input": {"file_path": outside}},
            {"type": "tool_use", "name": "TodoWrite", "input": {"todos": [
                {"content": "write the tests", "status": "pending"},
                {"content": "publish it", "status": "completed"}]}}]}}))
    (hstore / "s1.jsonl").write_text(T0)
    (sb / ".claude.json").write_text(json.dumps(
        {"projects": {projH: {"hasTrustDialogAccepted": True}}}))
    hrun("tag", projH, "--apply")
    rproj = str(box) + projH
    rstore = bhome / ".claude" / "projects" / enc(rproj)

    d = J(hrun("handover", projH, "--json"))
    ck(d.get("applied") is False and not d.get("blockers")
       and d.get("plan", {}).get("files") == 6 and not os.path.exists(rproj),
       f"dry run: what would travel is counted, nothing is sent ({d.get('plan') or d})")
    ck(d.get("outside_not_carried") == [outside] and d.get("title") == "Parser work",
       "dry run names the session and the outside files that stay behind")

    # SAFETY (1): an open session blocks, working or idle
    sess_dir = tools / "sessions"
    sess_dir.mkdir(exist_ok=True)
    sleeper = subprocess.Popen(["sleep", "600"], cwd="/")
    rec = sess_dir / f"{sleeper.pid}.json"
    rec.write_text(json.dumps({"pid": sleeper.pid, "cwd": projH, "status": "busy",
                               "sessionId": "s1", "name": "parser"}))
    r = hrun("handover", projH, "--apply", "--json")
    d = J(r)
    ck(r.returncode == 3 and not d.get("applied") and not os.path.exists(rproj)
       and any("WORKING" in b for b in d.get("blockers", [])),
       "a WORKING session blocks the handover; nothing leaves")
    rec.write_text(json.dumps({"pid": sleeper.pid, "cwd": projH, "status": "idle",
                               "sessionId": "s1"}))
    d = J(hrun("handover", projH, "--apply", "--json", "--allow-processes"))
    ck(not d.get("applied") and any("exit it first" in b for b in d.get("blockers", []))
       and not os.path.exists(rproj),
       "an open idle session blocks too, and no flag overrides that")
    sleeper.kill(); sleeper.wait()
    ck(core.running_sessions(inside=projH, home=tools) == [],
       "the record a finished session left behind does not block")
    worker = subprocess.Popen(["sleep", "600"], cwd=projH)
    d = J(hrun("handover", projH, "--apply", "--json"))
    ck(not d.get("applied") and any("still running in this folder" in b
                                    for b in d.get("blockers", [])),
       "a program running in the folder blocks")
    worker.kill(); worker.wait()

    r = hrun("handover", projH, "--apply", "--json")
    d = J(r)
    ck(r.returncode == 0 and d.get("applied") and d.get("started"),
       "handover applied and the session started over there "
       f"({d.get('error') or d.get('blockers') or d.get('unparsed') or 'ok'})")
    got = sorted(str(p.relative_to(rproj)) for p in Path(rproj).rglob("*") if p.is_file())
    ck("a.txt" in got and "sub/b.txt" in got and nfd in got
       and not any("node_modules" in g or g.startswith("Icon") for g in got),
       "the project arrived; per-machine folders and the icon file stayed")
    ck((rstore / "s1.jsonl").is_file() and (rstore / "s1.jsonl").read_text() == T0
       and (rstore / "memory" / "MEMORY.md").is_file(),
       "the history arrived under the key of the path over there")
    brief = sorted(Path(projH, ".aht", "handover").glob("*-to-*.md"))
    btxt = brief[-1].read_text() if brief else ""
    ck("SUMMARY: the parser is half done" in btxt and "now fix the lexer" in btxt
       and "The lexer is fixed." in btxt and "write the tests" in btxt
       and "publish it" not in btxt and outside in btxt
       and "first question" not in btxt,
       "readable summary: last compaction, latest exchange, open to-dos, "
       "outside files")
    ck(Path(projH, ".aht", "handover", ".gitignore").read_text().strip() == "*",
       "git is told to ignore the summaries: they quote the conversation")
    win = (d.get("away") or {}).get("window", "?")
    rrun = bhome / ".aht" / "remote" / "run" / win
    note = (rrun / "note.txt").read_text() if rrun.is_dir() else ""
    sett = (rrun / "settings.json").read_text() if rrun.is_dir() else ""
    ck("handed over" in note and outside in note and "note.txt" in sett
       and "SessionStart" in sett,
       "the resumed session is told on arrival what changed around it")
    wfile = bhome / ".faketmux" / f"{win}.json"
    line = json.loads(wfile.read_text())["command"] if wfile.is_file() else ""
    ck("--resume s1" in line and "--settings" in line
       and "--remote-control 'Hand Over'" in line,
       "it resumes the newest session, reachable from the phone")
    trust = json.loads((bhome / ".claude.json").read_text()).get("projects", {})
    ck(trust.get(rproj, {}).get("hasTrustDialogAccepted") is True
       and d.get("trust") == "carried over", "the folder's trust is carried over")
    r = subprocess.run([PY, "-c", marks_probe, str(HERE.parent), projH], env=env,
                       capture_output=True, text=True)
    ck(project_row(projH)["away"] and "agent:away" in r.stdout
       and "agent:claude" not in r.stdout, "the folder is marked as away")
    d = J(hrun("handover", projH, "--apply", "--json"))
    ck(any("already handed over" in b for b in d.get("blockers", [])),
       "a project that is away cannot be handed over again")
    warned = hook(projH)
    ck("WARNING" in warned and "handed over" in warned and project_row(projH)["away"],
       "a session started here meanwhile is warned; the record survives the hook")

    # work over there, and some here
    time.sleep(1.1)
    Path(rproj, "a.txt").write_text("a2 from the box\n")
    Path(rproj, "new.txt").write_text("born there\n")
    Path(rproj, "sub/b.txt").unlink()
    Path(rproj, "c.txt").write_text("c2 THERE\n")
    Path(projH, "c.txt").write_text("c2 HERE\n")
    Path(projH, "d.txt").write_text("d2 here only\n")
    T1 = T0 + json.dumps({"type": "user", "message": {"content": "continued there"}}) + "\n"
    (rstore / "s1.jsonl").write_text(T1)
    (rstore / "s2.jsonl").write_text('{"type":"user"}\n')

    live = open_there()
    srec = bhome / ".claude" / "sessions" / f"{live[0]['pid']}.json" if live else None
    ck(len(live) == 1, "one session is open over there")
    state = json.loads(srec.read_text())
    srec.write_text(json.dumps(dict(state, status="busy")))
    r = hrun("reclaim", projH, "--apply", "--stop", "--json")
    d = J(r)
    ck(r.returncode == 3 and not d.get("applied") and len(open_there()) == 1
       and any("WORKING" in b for b in d.get("blockers", []))
       and Path(projH, "a.txt").read_text() == "a1\n",
       "a session WORKING over there blocks the way back, --stop or not")
    srec.write_text(json.dumps(dict(state, status="idle")))
    d = J(hrun("reclaim", projH, "--apply", "--json"))
    ck(not d.get("applied") and any("--stop" in b for b in d.get("blockers", [])),
       "an idle session there blocks until it is ended")
    d = J(hrun("reclaim", projH, "--stop", "--json"))
    ck(not d.get("applied") and d.get("would_stop") and len(open_there()) == 1
       and d.get("plan", {}).get("project") == {"take": 1, "new": 1, "delete": 1,
                                                "conflict": 1, "kept": 1},
       f"dry run: the plan; the session is left alone ({d.get('plan') or d})")
    r = hrun("reclaim", projH, "--apply", "--stop", "--json")
    d = J(r)
    ck(r.returncode == 0 and d.get("applied") and d.get("stopped")
       and open_there() == [],
       "reclaim applied after ending the idle session "
       f"({d.get('error') or d.get('blockers') or d.get('unparsed') or 'ok'})")
    ck(Path(projH, "a.txt").read_text() == "a2 from the box\n"
       and Path(projH, "new.txt").is_file()
       and not Path(projH, "sub/b.txt").exists()
       and Path(projH, "d.txt").read_text() == "d2 here only\n",
       "changes made there arrived; what changed only here stayed")
    both = [p.name for p in Path(projH).glob("c (from *).txt")]
    ck(Path(projH, "c.txt").read_text() == "c2 HERE\n" and len(both) == 1
       and Path(projH, both[0]).read_text() == "c2 THERE\n",
       "changed on both sides: both versions are kept")
    aside = Path(d.get("set_aside") or "/nonexistent")
    ck((aside / "project" / "a.txt").is_file()
       and (aside / "project" / "a.txt").read_text() == "a1\n"
       and (aside / "project" / "sub" / "b.txt").is_file(),
       "SAFETY (3): what was replaced or removed is set aside, not lost")
    ck((hstore / "s1.jsonl").read_text() == T1 and (hstore / "s2.jsonl").is_file(),
       "the transcript came back continued, new sessions with it")
    ck(Path(projH, "Icon\r").exists() and Path(projH, "node_modules/pkg/x.js").exists(),
       "what never travelled is untouched")
    ck(project_row(projH)["away"] is None, "the project is no longer away")
    told, again = hook(projH), hook(projH)
    ck("is back on" in told and bool(both) and both[0] in told and again.strip() == "",
       "the next session here is told once what came back")

    # SAFETY (2): a transcript that is not a continuation never replaces ours
    d = J(hrun("handover", projH, "--apply", "--no-start", "--json"))
    ck(d.get("applied") and "started" not in d,
       "a second handover, transfer only "
       f"({d.get('error') or d.get('blockers') or d.get('unparsed') or 'ok'})")
    time.sleep(1.1)
    (rstore / "s1.jsonl").write_text("REWRITTEN" + T1[9:] + "more\n")
    d = J(hrun("reclaim", projH, "--apply", "--json"))
    odd = list(hstore.glob("s1.jsonl.aht-conflict-*"))
    ck(d.get("applied") and (hstore / "s1.jsonl").read_text() == T1 and len(odd) == 1
       and odd[0].read_text().startswith("REWRITTEN"),
       "a rewritten transcript is kept aside; ours stays as it was "
       f"({d.get('error') or d.get('blockers') or d.get('unparsed') or d.get('plan')}, "
       f"{[p.name for p in hstore.iterdir()]})")

    # mirror: the warm copy
    projM = os.path.realpath(str(roots / "mirrored"))
    os.makedirs(projM)
    Path(projM, "keep.txt").write_text("k\n")
    Path(projM, "gone.txt").write_text("g\n")
    r = hrun("mirror", projM, "--on", "--run", "--json")
    rm = str(box) + projM
    ck(J(r).get("mirrored", [{}])[0].get("status") == "synced"
       and Path(rm, "gone.txt").is_file(), "mirror: the copy over there is made")
    Path(projM, "gone.txt").unlink()
    Path(projM, "keep.txt").write_text("k2\n")
    hrun("mirror", "--run", "--json")
    kept = list((bhome / ".aht" / "remote" / "replaced").rglob("gone.txt"))
    ck(Path(rm, "keep.txt").read_text() == "k2\n" and not Path(rm, "gone.txt").exists()
       and len(kept) == 1,
       "mirror: it follows changes; what it removes there is set aside")
    ck(J(hrun("mirror", "--run", "--due", "--json")).get("mirrored") == [],
       "mirror: nothing is due right after a sync")
    os.makedirs(rm + "/busy")
    other = subprocess.Popen(["sleep", "600"], cwd=rm + "/busy")
    rows = J(hrun("mirror", "--run", "--json")).get("mirrored", [{}])
    ck(rows[0].get("status") == "skipped",
       "mirror: it stays out while something runs in the copy")
    other.kill(); other.wait()
    hook(projM)
    ck(project_row(projM)["mirror"] == "box", "the mirror setting survives the hook")

    # the history must stay readable where it returns to
    newer = stubs / "claude-newer"
    newer.write_text('#!/bin/sh\necho "9.9.10 (Claude Code)"\n')
    newer.chmod(0o755)
    J(hrun("handover", projH, "--apply", "--no-start", "--json"))
    time.sleep(1.1)
    Path(rproj, "a.txt").write_text("a3\n")
    r = run("reclaim", projH, "--apply", "--json",
            extra_env=dict(henv, AHT_REMOTE_CLAUDE=str(newer)))
    d = J(r)
    ck(r.returncode == 3 and not d.get("applied")
       and any("9.9.10" in b and "update" in b for b in d.get("blockers", []))
       and Path(projH, "a.txt").read_text() != "a3\n",
       "a newer agent CLI over there blocks the way back")
    now = (rstore / "s1.jsonl").read_text()
    (rstore / "s1.jsonl").write_text(now + json.dumps(
        {"type": "user", "version": "9.10.0", "message": {"content": "later"}}) + "\n")
    d = J(hrun("reclaim", projH, "--apply", "--json"))
    ck(not d.get("applied") and d.get("claude", {}).get("wrote_the_history") == "9.10.0"
       and any("9.10.0" in b for b in d.get("blockers", [])),
       "so does a history that a newer version wrote into")
    d = J(hrun("reclaim", projH, "--apply", "--ignore-version", "--json"))
    ck(d.get("applied") and any("9.10.0" in w for w in d.get("warnings", []))
       and Path(projH, "a.txt").read_text() == "a3\n",
       "--ignore-version takes it back anyway, with a warning")

    # which session goes on: the one used last, as `claude --continue` picks
    projS = os.path.realpath(str(roots / "sessions"))
    os.makedirs(projS)
    Path(projS, "f.txt").write_text("f\n")
    sstore = tools / "claude" / enc(projS)
    sstore.mkdir()
    def transcript(name, entry, *prompts, title=None, where=sstore, age=0):
        rows = [{"type": "user", "entrypoint": entry, "cwd": projS,
                 "message": {"role": "user", "content": p}} for p in prompts]
        if title:
            rows.append({"type": "ai-title", "aiTitle": title})
        f = Path(where) / f"{name}.jsonl"
        f.write_text("".join(json.dumps(r) + "\n" for r in rows))
        stamp = time.time() - age
        os.utime(f, (stamp, stamp))
    transcript("main", "cli", "the real work", title="Main thread", age=300)
    transcript("cron", "sdk-cli", "a nightly scripted run", age=200)
    transcript("loop", "cli", "/loop check the build", age=100)
    ck(core._sessions_of(sstore)[0] == "loop" and core.latest_session(sstore) == "main",
       "scripted runs and /loop sessions are passed over, however recent")
    hrun("tag", projS, "--apply")
    d = J(hrun("handover", projS, "--apply", "--no-start", "--json"))
    ck(d.get("applied") and d.get("session") == "main" and d.get("sessions") == 3,
       "handover goes on with the session last worked in")
    rs = bhome / ".claude" / "projects" / enc(str(box) + projS)
    time.sleep(1.1)
    transcript("main", "cli", "the real work", "a bit more there", title="Main thread",
               where=rs, age=50)
    transcript("branch", "cli", "the real work", "a bit more there", "after the branch",
               title="Main thread (branch)", where=rs)
    d = J(hrun("reclaim", projS, "--apply", "--json"))
    ck(d.get("applied") and d.get("session") == "branch"
       and d.get("session_title") == "Main thread (branch)"
       and d.get("handed_over_session") == "main"
       and d.get("handed_over_title") == "Main thread",
       "back from a branch made there: the branch goes on, the sent one is named")
    r1 = hrun("resume-here", projS, "--print").stdout
    r2 = hrun("resume-here", projS, "--handed-over", "--print").stdout
    ck("--resume branch" in r1 and "--resume main" in r2,
       "resume-here opens the latest; --handed-over the one that was sent")
    sf = sb / "stage.json"
    d = J(hrun("handover", projM, "--apply", "--no-start", "--json",
               "--status-file", str(sf)))
    stage = json.loads(sf.read_text()) if sf.is_file() else {}
    ck(d.get("applied") and "sending" in stage.get("stage", "")
       and "percent" in stage,
       f"--status-file tells a front-end where the transfer stands ({stage})")
    d = J(hrun("reclaim", projM, "--apply", "--json"))
    ck(d.get("applied") and d.get("handed_over_session") is None,
       "no second session is offered when the work stayed in the one sent")
    row = project_row(projM)
    ck(row["mirror"] == "box" and row["mirror_synced_at"] and row["away_since"] is None,
       "the project list tells when a project was synced last")
    sitter = subprocess.Popen(["sleep", "600"], cwd="/")
    (tools / "sessions" / f"{sitter.pid}.json").write_text(json.dumps(
        {"pid": sitter.pid, "cwd": projM, "status": "busy"}))
    ck(project_row(projM)["open"] == "working" and project_row(projS)["open"] is None
       and project_row(projH)["agents"] == ["claude"],
       "the project list tells where an agent session is open")
    sitter.kill(); sitter.wait()

    # a path the registry lists twice: the folder's own marker decides
    regf = sb / ".aht" / "registry.json"
    reg = json.loads(regf.read_text())
    mine = next(u for u, e in reg["projects"].items() if e["real_path"] == projS)
    reg["projects"] = {"0" * 32: {"real_path": projS, "stores": {},
                                  "updated_at": "2020-01-01T00:00:00"},
                       **reg["projects"]}
    regf.write_text(json.dumps(reg))
    d = J(hrun("handover", projS, "--apply", "--no-start", "--json"))
    reg = json.loads(regf.read_text())
    ck(d.get("applied") and reg["projects"][mine].get("away")
       and not reg["projects"]["0" * 32].get("away"),
       "a path listed twice: the entry the folder's marker names is used")
    J(hrun("reclaim", projS, "--apply", "--json"))
    dr = J(hrun("doctor", "--json"))
    twice = next(c for c in dr["checks"] if c["check"] == "no folder is listed twice")
    d = J(hrun("prune", "--json"))
    ck(not twice["ok"] and [x["uuid"] for x in d["doubles"]] == ["0" * 32]
       and d["doubles"][0]["owner"] == mine,
       "doctor and prune name the stale one of two entries for a folder")
    d = J(hrun("prune", "--apply", "--json"))
    reg = json.loads(regf.read_text())
    ck("0" * 32 not in reg["projects"] and mine in reg["projects"]
       and read_text_or_none(Path(projS) / ".aht" / ".project-id") == mine,
       "prune drops it; the folder's own entry and its marker stay")

    # any number of machines
    box2 = Path(os.path.realpath(sb)) / "box2"
    (box2 / "home" / ".claude").mkdir(parents=True)
    hrun("config", "--set", "remotes=" + json.dumps(
        {"box": {"root": str(box)}, "box2": {"root": str(box2)}}))
    ck(J(hrun("status", "--json"))["handover"]["default_remote"] == "box"
       and sorted(J(hrun("remote", "list", "--json"))["remotes"]) == ["box", "box2"],
       "several machines; the first one stays the default")
    d = J(hrun("handover", projM, "--to", "box2", "--apply", "--no-start", "--json"))
    ck(d.get("applied") and Path(str(box2) + projM, "keep.txt").is_file()
       and project_row(projM)["away_remote"] == "box2",
       "--to hands a project to the machine named")
    r = hrun("remote", "remove", "box2")
    ck(r.returncode == 3 and "box2" in J(hrun("remote", "list", "--json"))["remotes"],
       "a machine that holds a project cannot be removed")
    d = J(hrun("reclaim", projM, "--apply", "--json"))
    r = hrun("remote", "remove", "box2")
    ck(d.get("applied") and r.returncode == 0
       and sorted(J(hrun("remote", "list", "--json"))["remotes"]) == ["box"],
       "once the project is back it can")
    ts = stubs / "tailscale"
    ts.write_text("#!/bin/sh\ncat <<'JSON'\n" + json.dumps({"Peer": {
        "a": {"HostName": "x", "DNSName": "homebox.net.ts.net.", "OS": "linux",
              "Online": True},
        "b": {"HostName": "phone", "DNSName": "phone.net.ts.net.", "OS": "iOS",
              "Online": True},
        "c": {"HostName": "old", "DNSName": "attic.net.ts.net.", "OS": "macOS",
              "Online": False}}}) + "\nJSON\n")
    ts.chmod(0o755)
    found = J(run("remote", "discover", "--json",
                  extra_env=dict(henv, AHT_TAILSCALE=str(ts)))).get("machines", [])
    names = [m["name"] for m in found if m["via"] == "tailscale"]
    ck(names == ["homebox", "attic"],
       f"discover: computers of the network, reachable ones first, no phones ({names})")
    ts.write_text("#!/bin/sh\necho 'Tailscale is stopped.' >&2\nexit 1\n")
    before = run("logs", "--errors", "-n", "400").stdout.count("discover")
    for _ in range(3):
        d = J(run("remote", "discover", "--json",
                  extra_env=dict(henv, AHT_TAILSCALE=str(ts))))
    after = run("logs", "--errors", "-n", "400").stdout.count("discover")
    ck(not [m for m in d.get("machines", []) if m["via"] == "tailscale"]
       and any("Tailscale is stopped" in n for n in d.get("notes", []))
       and after == before,
       "discover: a stopped Tailscale is told to the asker, not written to the log")

    # the history backups kept on the other machine too
    hrun("config", "--set", "offsite_backup=box")
    bdir = sb / ".aht" / "backups" / "u1"
    bdir.mkdir(parents=True, exist_ok=True)
    (bdir / "20260101-000000.zip").write_bytes(b"zip")
    d = J(hrun("backup", "--offsite", "--json"))
    copies = list((bhome / ".aht" / "offsite").rglob("20260101-000000.zip"))
    ck(d.get("machine") == "box" and len(copies) == 1,
       f"backups are copied to the other machine ({d})")
    (bdir / "20260101-000000.zip").unlink()
    d = J(hrun("backup", "--fetch-offsite", "--json"))
    ck((bdir / "20260101-000000.zip").read_bytes() == b"zip",
       "…and fetched back from it on a new Mac")
    hrun("config", "--unset", "offsite_backup")

    # hand over with a task: the session starts on it at once
    d = J(hrun("handover", projM, "--apply", "--json",
               "--task", "-- run the benchmark overnight"))
    win = (d.get("away") or {}).get("window", "?")
    wfile = bhome / ".faketmux" / f"{win}.json"
    line = json.loads(wfile.read_text())["command"] if wfile.is_file() else ""
    brief = sorted(Path(projM, ".aht", "handover").glob("*-to-*.md"))
    ck(d.get("applied") and "-- '-- run the benchmark overnight'" in line
       and "run the benchmark overnight" in brief[-1].read_text()
       and project_row(projM)["away"],
       "--task: the resumed session starts on it; the summary records it")
    boards = J(hrun("board", "--json")).get("machines", [])
    there = next((b for b in boards if b["machine"] == "box"), {})
    row = next((s for s in there.get("sessions", []) if s.get("project") == str(box) + projM), {})
    ck(there.get("reachable") and row.get("status") == "idle",
       f"board: the other machine's open sessions are listed ({there.get('error') or row})")
    J(hrun("reclaim", projM, "--apply", "--stop", "--json"))

    # the night shift: a handover with a task on a timer, and back again
    jobs_file = sb / ".aht" / "night-shift.json"
    r = hrun("night-shift", projM, "--task", "tidy the logs", "--to", "box", "--apply")
    ck(r.returncode == 3 and "tokens" in r.stdout and not jobs_file.exists(),
       "night shift: off until turned on, because it uses tokens")
    hrun("config", "--set", "night_shift=true")
    def job_state(want, secs=90):
        for _ in range(secs * 4):
            j = json.loads(jobs_file.read_text())[-1]
            if j["state"] == want:
                break
            time.sleep(0.25)
        return j
    d = J(hrun("night-shift", projM, "--task", "tidy the logs", "--to", "box",
               "--back", "07:00", "--apply", "--json"))
    j = job_state("started")
    ck(d.get("applied") and j["state"] == "started" and project_row(projM)["away"],
       f"night shift: handed over with the task when it starts ({j.get('log')})")
    jobs = json.loads(jobs_file.read_text())
    jobs[-1]["back_at"] = time.time() - 1
    jobs_file.write_text(json.dumps(jobs))
    hrun("notices")
    j = job_state("back")
    ck(j["state"] == "back" and not project_row(projM)["away"],
       f"night shift: taken back when it ends ({j.get('log')})")
    hrun("config", "--unset", "night_shift")

    # every project in sync with one machine at once
    d = J(hrun("mirror", "--all", "--on", "--to", "box", "--json"))
    names = [r["project"] for r in d.get("projects", [])]
    ck(names and d.get("bytes", 0) > 0 and not d.get("applied")
       and not any(n != m and n.startswith(m + "/") for n in names for m in names),
       f"mirror --all: every project, sizes added up, nested ones carried by their parent ({len(names)})")
    J(hrun("mirror", "--all", "--on", "--to", "box", "--apply", "--json"))
    rows = J(hrun("projects", "--json"))["projects"]
    ck(all(r["mirror"] == "box" for r in rows if r["real_path"] in names),
       "mirror --all --apply: each of them is kept in sync")
    J(hrun("mirror", "--all", "--off", "--apply", "--json"))
    rows = J(hrun("projects", "--json"))["projects"]
    ck(not [r for r in rows if r["mirror"]], "mirror --all --off: none any more")

    for w in (bhome / ".faketmux").glob("*.json"):   # the stand-in sessions
        rec = json.loads(w.read_text())
        if rec.get("alive"):
            try:
                os.kill(int(rec["pid"]), 15)
            except OSError:
                pass

if os.name == "nt" or not core.find_rsync():
    print("  SKIP needs rsync 3 (macOS: brew install rsync)")
else:
    handover_suite()

print("\n[17] across agents: search, secrets, journal, rules, switch, board")
from datetime import datetime, timezone
def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")
KEY = "sk-" + "ant-" + "api03-" + "Xq7" * 12            # a made-up key, built in pieces
projX = os.path.realpath(str(roots / "Across"))
os.makedirs(projX)
Path(projX, "app.py").write_text("print('hi')\n")
T = time.time() - 3 * 86400
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

def JS(*a, **kw):
    r = run(*a, **kw)
    try:
        return json.loads(r.stdout)
    except Exception:
        return {"unparsed": r.stdout[-300:] + r.stderr[-300:]}
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
                                 "passwd = Xk29!aa8Qz3"}]}))
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
d = JS("switch", projX, "--to", "kimi", "--apply", "--json", extra_env=senv)
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

print("\n[18] notices, tidy, changes, report, share, taking a key out")
nlog = sb / "notices.log"
nenv = {"AHT_NOTIFY_LOG": str(nlog), "AHT_NO_SEARCH_INDEX": "1"}
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
ck([g["title"] for g in got] == ["Across waits for you", "Across is done"]
   and got[0]["message"] == "approve Bash",
   f"notices: waiting for you, then done — once each ({[g['title'] for g in got]})")
run("notices", extra_env=nenv)
ck(len(nlog.read_text().splitlines()) == 2, "notices: nothing new, nothing said")
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

# the report and a statement of AI use
d = JS("report", "--json", "--by", "agent")
agents = sorted(r["key"] for r in d.get("rows", []))
ck("Claude Code" in agents and "Kimi Code" in agents
   and all(r["seconds"] >= 0 for r in d.get("rows", [])),
   f"report: time and sessions per agent ({agents})")
d = JS("report", "--project", projX, "--statement", "--json")
ck("Claude Code" in d.get("statement", "") and "Kimi Code" in d.get("statement", ""),
   "report --statement: a draft naming the agents used")

# share a session: no key, no e-mail address, no home folder
home = str(Path.home())
(cstore / "c3.jsonl").write_text(cline(type="user", timestamp=iso(T + 500), message={
    "role": "user", "content": f"mail me at someone@example.org, file {home}/notes.txt, "
                               f"key {KEY}"}))
d = JS("share", projX, "--session", "c3", "--format", "html", "--json")
page = d.get("text", "")
ck(d.get("turns") == 1 and KEY not in page and "someone@example.org" not in page
   and home not in page and "~/notes.txt" in page and "<!doctype html>" in page,
   "share: a clean page — no key, no e-mail address, no home folder")

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

print("\n[19] before and after a session: informed, usage limit, undo, loose ends, "
      "second opinion")
import time
# every session starts informed: only when turned on, since it costs tokens
def hook_out(payload, **extra):
    return subprocess.run([PY, CLI, "hook"], env=dict(env, **extra), capture_output=True,
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
        "AHT_NO_SEARCH_INDEX": "1"}
run("config", "--set", "limit_switch=true")
nlog.write_text("")
run("notices", extra_env=kenv)
run("notices", extra_env=kenv)
got = [json.loads(l) for l in nlog.read_text().splitlines()]
ck([g["title"] for g in got] == ["Limited: Claude's usage limit"]
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
d = JS("second-opinion", projO, "--task", "add a line", "--json", extra_env=wrap)
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

print("\n[20] a session carries its iTerm2 tab's title (what the Claude app shows)")
tabs_file = sb / "iterm-tabs.json"
tabs_file.write_text(json.dumps({"/dev/ttysT1": {"title": "Paper", "pane": 1, "panes": 1},
                                 "/dev/ttysT2": {"title": "Paper", "pane": 1, "panes": 1}}))
tstore = tools / "claude" / enc(projX)
def title_line(t, sid):
    return json.dumps({"type": "custom-title", "customTitle": t, "sessionId": sid}) + "\n"
def fake_claude(sid, title=None):
    """A stand-in Claude process: a live pid with a session record and a transcript."""
    proc = subprocess.Popen(["sleep", "600"], cwd="/", stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    (rec / f"{proc.pid}.json").write_text(json.dumps({"pid": proc.pid, "cwd": projX,
                                                      "sessionId": sid, "status": "idle"}))
    (tstore / f"{sid}.jsonl").write_text(title_line(title, sid) if title else "")
    return proc
def tab_hook(event, sid, tty, pid, **extra):
    payload = {"hook_event_name": event, "session_id": sid, "cwd": projX,
               "transcript_path": str(tstore / f"{sid}.jsonl"), "source": "startup"}
    out = hook_out(payload, AHT_ITERM_TABS=str(tabs_file), AHT_TTY=tty,
                   AHT_CLAUDE_PID=str(pid), **extra).strip()
    try:
        return json.loads(out)["hookSpecificOutput"].get("sessionTitle")
    except Exception:
        return out or None
a = fake_claude("t1")
ck(tab_hook("SessionStart", "t1", "/dev/ttysT1", a.pid) == "Paper",
   "tab names: a new session takes its tab's title")
with open(tstore / "t1.jsonl", "a") as fh:
    fh.write(title_line("Paper", "t1"))
ck(tab_hook("UserPromptSubmit", "t1", "/dev/ttysT1", a.pid) is None,
   "tab names: nothing said while the name is right")
tabs_file.write_text(json.dumps({"/dev/ttysT1": {"title": "Paper v2", "pane": 1, "panes": 1},
                                 "/dev/ttysT2": {"title": "Paper v2", "pane": 1, "panes": 1}}))
ck(tab_hook("UserPromptSubmit", "t1", "/dev/ttysT1", a.pid) == "Paper v2",
   "tab names: a renamed tab renames the session at the next prompt")
with open(tstore / "t1.jsonl", "a") as fh:
    fh.write(title_line("Paper v2", "t1"))
b = fake_claude("t2")
ck(tab_hook("SessionStart", "t2", "/dev/ttysT2", b.pid) == "Paper v2 · 2",
   "tab names: a second open session with that title gets “· 2”")
c = fake_claude("t3")
(tstore / "t3.jsonl").write_text(json.dumps({"type": "user", "forkedFrom": {"sessionId": "t1"},
                                             "message": {"role": "user", "content": "x"}})
                                 + "\n" + title_line("Paper v2", "t3"))
ck(tab_hook("UserPromptSubmit", "t3", "/dev/ttysT2", c.pid) == "Paper v2 ⑂ 2",
   "tab names: a branch that inherited the name becomes “⑂ 2”")
d_ = fake_claude("t4", title="My own name")
ck(tab_hook("UserPromptSubmit", "t4", "/dev/ttysT1", d_.pid) is None,
   "tab names: a name the user gave the session stays")
tabs_file.write_text(json.dumps({"/dev/ttysT1": {"title": "Paper v3", "pane": 1, "panes": 1},
                                 "/dev/ttysT2": {"title": "Paper v2", "pane": 1, "panes": 1}}))
ck(tab_hook("UserPromptSubmit", "t4", "/dev/ttysT1", d_.pid) == "Paper v3",
   "tab names: renaming the tab afterwards wins over the name given before")
with open(tstore / "t4.jsonl", "a") as fh:
    fh.write(title_line("Paper v3", "t4"))
live = sb / "iterm-live.json"
live.write_text(json.dumps({"/dev/ttysT1": {"title": "Paper v4", "pane": 1, "panes": 1}}))
ck(tab_hook("UserPromptSubmit", "t4", "/dev/ttysT1", d_.pid, AHT_ITERM_LIVE=str(live))
   == "Paper v4",
   "tab names: the tab is looked at as it is now, not as aht last saw all tabs")
with open(tstore / "t4.jsonl", "a") as fh:
    fh.write(title_line("Paper v4", "t4") + title_line("Mine again", "t4"))
ck(tab_hook("UserPromptSubmit", "t4", "/dev/ttysT1", d_.pid, AHT_ITERM_LIVE=str(live)) is None,
   "tab names: a name given after the tab's rename stays")
# a long session: its name is found further back than the last part
with open(tstore / "t4.jsonl", "a") as fh:
    filler = json.dumps({"type": "assistant", "message": {"role": "assistant",
                                                         "content": "x" * 4000}}) + "\n"
    fh.write(filler * 100)
ck(tab_hook("UserPromptSubmit", "t4", "/dev/ttysT1", d_.pid, AHT_ITERM_LIVE=str(live)) is None,
   "tab names: in a long session the name it has is still found, so it stays")
tabs_file.write_text(json.dumps({"/dev/ttysT1": {"title": "Paper v2", "pane": 1, "panes": 1},
                                 "/dev/ttysT2": {"title": "Paper v2", "pane": 1, "panes": 1}}))
run("config", "--set", "tab_names=false")
e_ = fake_claude("t5")
ck(tab_hook("SessionStart", "t5", "/dev/ttysT1", e_.pid) is None,
   "tab names: off in the settings, nothing happens")
run("config", "--unset", "tab_names")
run("config", "--set", "informed_sessions=true")
f_ = fake_claude("t6")
raw = hook_out({"hook_event_name": "SessionStart", "session_id": "t6", "cwd": projX,
                "transcript_path": str(tstore / "t6.jsonl"), "source": "startup"},
               AHT_ITERM_TABS=str(tabs_file), AHT_TTY="/dev/ttysT1", AHT_CLAUDE_PID=str(f_.pid))
try:
    hso = json.loads(raw)["hookSpecificOutput"]
except Exception:
    hso = {}
ck(hso.get("sessionTitle", "").startswith("Paper v2")
   and "[aht] The latest earlier session" in hso.get("additionalContext", ""),
   f"tab names: the start notes travel with the name, as JSON ({raw[:120]!r})")
run("config", "--unset", "informed_sessions")
probe = ("import sys, json; sys.path.insert(0, sys.argv[1]); import aht; "
         "print(aht.handover_session_name('t1', '/x/Paper', 'homebox')); "
         "print(aht.handover_session_name('nobody', '/x/Paper', 'homebox'))")
r = subprocess.run([PY, "-c", probe, str(HERE.parent)], env=env, capture_output=True, text=True)
ck(r.stdout.split() == ["Paper", "v2", "@", "homebox", "Paper"],
   f"handover: the session there is “<tab title> @ <machine>” ({r.stdout.strip() or r.stderr[-200:]})")
# a name set in aht's window: at the next prompt, and it stays until handed back
run("tab-names", "--rename", "t1", "--to", "Budget work")
ck(tab_hook("UserPromptSubmit", "t1", "/dev/ttysT1", a.pid) == "Budget work",
   "rename: the name set in aht arrives at the session's next prompt")
with open(tstore / "t1.jsonl", "a") as fh:
    fh.write(title_line("Budget work", "t1"))
ck(tab_hook("UserPromptSubmit", "t1", "/dev/ttysT1", a.pid) is None,
   "rename: it stays, whatever the tab is called")
run("tab-names", "--rename", "t1", "--to", "")
ck(str(tab_hook("UserPromptSubmit", "t1", "/dev/ttysT1", a.pid)).startswith("Paper v2"),
   "rename: following the tab again brings the tab's title back")

# the other way round: a session renamed gives its tab the name (the latest act wins)
live2 = sb / "iterm-live2.json"
def tab_now(**kw):
    t = json.loads(live2.read_text())
    if kw:
        t["/dev/ttysT3"].update(kw)
        live2.write_text(json.dumps(t))
    return t["/dev/ttysT3"]["title"]
live2.write_text(json.dumps({"/dev/ttysT3": {"title": "Thesis", "override": True,
                                             "panes": 1, "id": "7"}}))
k_ = fake_claude("t9")
L = {"AHT_ITERM_LIVE": str(live2)}
def say(t):
    with open(tstore / "t9.jsonl", "a") as fh:
        fh.write(title_line(t, "t9"))
ck(tab_hook("SessionStart", "t9", "/dev/ttysT3", k_.pid, **L) == "Thesis",
   "tab names: a session in a third tab takes its title")
say("Thesis")
tab_hook("UserPromptSubmit", "t9", "/dev/ttysT3", k_.pid, **L)
say("Chapter 2")                                            # /rename
ck(tab_hook("UserPromptSubmit", "t9", "/dev/ttysT3", k_.pid, **L) is None
   and tab_now() == "Chapter 2",
   "tab names: a session renamed with /rename gives its tab the name")
say("Chapter 3")
ck(tab_hook("UserPromptSubmit", "t9", "/dev/ttysT3", k_.pid, AHT_ITERM_API_OFF="1", **L) is None
   and tab_now() == "Chapter 2"
   and tab_hook("UserPromptSubmit", "t9", "/dev/ttysT3", k_.pid, AHT_ITERM_API_OFF="1",
                **L) is None,
   "tab names: with iTerm2's Python API off the tab keeps its title, the session its name")
say("Chapter 4")
tab_now(title="Thesis final")
ck(tab_hook("UserPromptSubmit", "t9", "/dev/ttysT3", k_.pid, **L) == "Thesis final",
   "tab names: both renamed since the last look: the tab wins")
ck(tab_hook("UserPromptSubmit", "t9", "/dev/ttysT3", k_.pid, **L) is None
   and tab_now() == "Thesis final",
   "tab names: the name aht gave, not taken yet, is not mistaken for a rename")
say("Thesis final")
T = {"AHT_ITERM_TABS": str(tabs_file), "AHT_ITERM_LIVE": str(live2),
     "AHT_TTYS": json.dumps({str(k_.pid): "/dev/ttysT3"})}
d = JS("tab-names", "--rename", "t9", "--to", "Defence", "--json", extra_env=T)
ck(d.get("tab") == "" and tab_now() == "Defence",
   f"rename: aht's Rename… gives the tab the name right away ({d})")
ck(tab_hook("UserPromptSubmit", "t9", "/dev/ttysT3", k_.pid, **L) == "Defence",
   "rename: … and the session at its next prompt")
say("Defence")
tab_now(title="Viva")
ck(tab_hook("UserPromptSubmit", "t9", "/dev/ttysT3", k_.pid, **L) == "Viva",
   "rename: renaming the tab afterwards wins over a name set in aht")
say("Viva")
tab_now(panes=2)
d = JS("tab-names", "--rename", "t9", "--to", "Two panes", "--json", extra_env=T)
ck(d.get("tab") == "panes" and tab_now() == "Viva",
   "rename: a tab holding two sessions keeps its title (it would name both)")
r = run("tab-names", "--rename", "t9", "--to", "Off", extra_env=dict(T, AHT_ITERM_API_OFF="1"))
ck("Enable Python API" in r.stdout, f"rename: says how to let the tab take names ({r.stdout!r})")
run("tab-names", "--rename", "t9", "--to", "")

# aht speaks iTerm2's Python API itself: a WebSocket on a Unix socket, protobuf in it
import socket as _so, threading as _th
def pb_varint(n):
    out = bytearray()
    while True:
        b, n = n & 0x7F, n >> 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)
def pb_len(num, b):
    b = b.encode() if isinstance(b, str) else b
    return pb_varint(num << 3 | 2) + pb_varint(len(b)) + b
def pb_read(buf):
    out, i = {}, 0
    def vi():
        nonlocal i
        n = s_ = 0
        while True:
            c_ = buf[i]; i += 1
            n |= (c_ & 0x7F) << s_; s_ += 7
            if not c_ & 0x80:
                return n
    while i < len(buf):
        key = vi(); w = key & 7
        if w == 0:
            v = vi()
        elif w == 1:
            v = buf[i:i + 8]; i += 8
        else:
            n = vi(); v = buf[i:i + n]; i += n
        out.setdefault(key >> 3, []).append(v)
    return out
def fake_iterm(path, answer, seen):
    srv = _so.socket(_so.AF_UNIX, _so.SOCK_STREAM)
    srv.bind(str(path)); srv.listen(1)
    def serve():
        conn, _ = srv.accept()
        f = conn.makefile("rb")
        head = b""
        while not head.endswith(b"\r\n\r\n"):
            head += f.readline()
        seen["head"] = head.decode()
        conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                     b"Connection: Upgrade\r\nSec-WebSocket-Protocol: api.iterm2.com\r\n\r\n")
        b0, b1 = f.read(2)
        mask, n = f.read(4), b1 & 0x7F
        seen["masked"] = bool(b1 & 0x80)
        seen["req"] = bytes(c_ ^ mask[i % 4] for i, c_ in enumerate(f.read(n)))
        conn.sendall(b"\x89\x00")                               # a ping first
        seen["pong"] = f.read(6)[:1] == b"\x8a"
        conn.sendall(bytes([0x82, len(answer)]) + answer)
        try:
            f.read(8)
        except OSError:
            pass
        conn.close(); srv.close()
    t = _th.Thread(target=serve, daemon=True); t.start()
    return t
api_sock = sb / "api.sock"
seen = {}
ok_answer = pb_varint(1 << 3) + pb_varint(1) + pb_len(132, pb_len(2, pb_len(1, "null")))
th = fake_iterm(api_sock, ok_answer, seen)
tab_now(panes=1)
probe = ("import sys; sys.path.insert(0, sys.argv[1]); import aht; "
         "print(repr(aht.set_tab_title('/dev/ttysT3', sys.argv[2])))")
api_env = dict(env, AHT_ITERM_API=str(api_sock), AHT_ITERM_API_KEY="cookie1 key1",
               AHT_ITERM_TABS=str(tabs_file), AHT_ITERM_LIVE=str(live2))
r = subprocess.run([PY, "-c", probe, str(HERE.parent), 'A "b" \\(x) ⑂'], env=api_env,
                   capture_output=True, text=True, timeout=30)
th.join(10)
req = pb_read(seen.get("req", b""))
inv = pb_read(req.get(132, [b""])[0])
ck(r.stdout.strip() == "''" and seen.get("masked") and seen.get("pong")
   and "x-iterm2-cookie: cookie1" in seen.get("head", "")
   and "x-iterm2-key: key1" in seen.get("head", "")
   and "Sec-WebSocket-Protocol: api.iterm2.com" in seen.get("head", "")
   and req.get(1) == [1] and pb_read(inv.get(7, [b""])[0]).get(1) == [b"7"]
   and inv.get(5, [b""])[0].decode() == 'iterm2.set_title(title: "A “b” \\\\\\\\(x) ⑂")',
   f"iTerm2 API: the tab's title set as Edit Tab Title does ({r.stdout.strip()} "
   f"{r.stderr[-300:]} {inv})")
api_sock.unlink()
seen = {}
bad = pb_varint(1 << 3) + pb_varint(1) + pb_len(132, pb_len(1, pb_varint(1 << 3) + pb_varint(4)
                                                          + pb_len(2, "no such tab")))
th = fake_iterm(api_sock, bad, seen)
r = subprocess.run([PY, "-c", probe, str(HERE.parent), "X"], env=api_env,
                   capture_output=True, text=True, timeout=30)
th.join(10)
ck("no such tab" in r.stdout, f"iTerm2 API: its refusal is reported ({r.stdout.strip()})")
api_sock.unlink()
r = subprocess.run([PY, "-c", probe, str(HERE.parent), "X"], env=api_env,
                   capture_output=True, text=True, timeout=30)
ck(r.stdout.strip() == "'api-off'", f"iTerm2 API: switched off, said so ({r.stdout.strip()})")
for pr in (a, b, c, d_, e_, f_, k_):
    pr.kill(); pr.wait()
    (rec / f"{pr.pid}.json").unlink()

# name every open session after its tab, also one named otherwise
tabs_file.write_text(json.dumps({"/dev/ttysT1": {"title": "Alpha", "pane": 1, "panes": 1},
                                 "/dev/ttysT2": {"title": "Alpha", "pane": 1, "panes": 1}}))
g = fake_claude("t7", title="Draft")
h = fake_claude("t8")
tenv = {"AHT_ITERM_TABS": str(tabs_file),
        "AHT_TTYS": json.dumps({str(g.pid): "/dev/ttysT1", str(h.pid): "/dev/ttysT2"})}
d = JS("tab-names", "--sync-all", "--json", extra_env=tenv)
plan = sorted((x["from"] or "", x["to"]) for x in d.get("plan", []))
ck(plan == [("", "Alpha · 2"), ("Draft", "Alpha")] and not d.get("applied"),
   f"sync all: every session with a tab title takes it, a clash gets “· 2” ({plan})")
rows = {r["session"]: r for r in JS("tab-names", "--json", extra_env=tenv).get("sessions", [])}
ck(rows.get("t7", {}).get("origin") == "yours" and rows["t7"].get("tab") == "Alpha",
   f"tab names: the list says where each name came from ({rows.get('t7')})")
JS("tab-names", "--sync-all", "--apply", "--json", extra_env=tenv)
ck(tab_hook("UserPromptSubmit", "t7", "/dev/ttysT1", g.pid) == "Alpha",
   "sync all: applied at the next prompt, also over a name the user gave")
for pr in (g, h):
    pr.kill(); pr.wait()
    (rec / f"{pr.pid}.json").unlink()

print("\n[22] workspace, go to a tab, a checkup of open sessions, tidy, the usage limit")
ilog = sb / "iterm.log"
def ilines():
    return [json.loads(l) for l in ilog.read_text().splitlines()] if ilog.is_file() else []
tabs_file.write_text(json.dumps({
    "/dev/ttysW1": {"title": "Paper", "override": True, "pane": 1, "panes": 1, "window": 1, "tab": 1},
    "/dev/ttysW2": {"title": "Notes", "override": True, "pane": 1, "panes": 1, "window": 1, "tab": 2},
    "/dev/ttysW3": {"title": "", "override": False, "pane": 1, "panes": 1, "window": 1, "tab": 3}}))
p1 = fake_claude("w1", title="Paper")
shell = subprocess.Popen(["sleep", "600"], cwd="/", stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
started = "claude --dangerously-skip-permissions --model opus --resume old1 fix-it"
wenv = {"AHT_ITERM_LOG": str(ilog), "AHT_ITERM_TABS": str(tabs_file),
        "AHT_TTYS": json.dumps({str(p1.pid): "/dev/ttysW1"}),
        "AHT_TTY_PROCS": json.dumps({"/dev/ttysW1": [[p1.pid, started]],
                                     "/dev/ttysW2": [[shell.pid, "-zsh"]], "/dev/ttysW3": []}),
        "AHT_CWDS": json.dumps({str(shell.pid): projX}),
        "AHT_CMDLINES": json.dumps({str(p1.pid): started}), "AHT_CLAUDE_VERSION": "9.9.9"}
JS("workspace", "--save", "--json", extra_env=wenv)
JS("workspace", "--save", "--json", extra_env=wenv)
ws = JS("workspace", "--json", extra_env=wenv).get("workspaces", [])
snap = json.loads(next((sb / ".aht" / "workspaces").glob("*.json")).read_text())
e1 = next((e for e in snap["tabs"] if e["title"] == "Paper"), {})
e2 = next((e for e in snap["tabs"] if e["title"] == "Notes"), {})
ck(len(ws) == 1 and ws[0]["tabs"] == 3 and ws[0]["sessions"] == 1
   and e1.get("session") == "w1" and e1.get("args") == ["--dangerously-skip-permissions",
                                                        "--model", "opus"]
   and e2.get("cwd") == projX and e2.get("agent") is None,
   f"workspace: tabs, titles, folders and sessions kept; the same layout once ({ws}, {e1})")
r = run("workspace", "--restore", extra_env=wenv)
ck(r.returncode == 3 and "its session is open" in r.stdout and "that title is open" in r.stdout,
   "workspace: what is open now is skipped")
p1.kill(); p1.wait()
(rec / f"{p1.pid}.json").unlink()
tabs_file.write_text(json.dumps({"/dev/ttysW3": {"title": "", "override": False, "pane": 1,
                                                 "panes": 1, "window": 1, "tab": 1}}))
d = JS("workspace", "--restore", "--apply", "--json", extra_env=wenv)
script = next((x["script"] for x in ilines() if x.get("what") == "restore"), "")
ck(d.get("applied") and d["plan"]["opens"] == 2 and "--resume w1" in script
   and "--model opus" in script and "fix-it" not in script and "old1" not in script
   and "user.ahtTitle" in script and "Notes" in script
   and "CLAUDE_CODE_DISABLE_TERMINAL_TITLE=1" in script,
   f"workspace: opened again, each session resumed with its options, tabs titled ({d.get('plan')})")

# a second click right away opens nothing twice (a session takes a while to start)
d2 = JS("workspace", "--restore", "--apply", "--json", extra_env=wenv)
ck(not d2.get("applied") and "everything in it is open already" in (d2.get("blockers") or [])
   and sum(1 for x in ilines() if x.get("what") == "restore") == 1,
   f"workspace: a second Open Them right away opens nothing twice ({d2.get('blockers')})")
(sb / ".aht" / "run" / "workspace-opened.json").unlink()

# tab colours come from iTerm2's saved window state, profiles from iTerm2
import plistlib, sqlite3 as _sq
def keyed(obj):
    """An NSKeyedArchiver plist, as iTerm2 writes its saved sessions."""
    objs = ["$null"]
    def enc(o):
        if isinstance(o, dict):
            i = len(objs)
            objs.append(None)
            ks = [enc(k) for k in o]
            vs = [enc(v) for v in o.values()]
            objs[i] = {"NS.keys": ks, "NS.objects": vs, "$class": plistlib.UID(0)}
            return plistlib.UID(i)
        objs.append(o)
        return plistlib.UID(len(objs) - 1)
    root = enc(obj)
    return plistlib.dumps({"$archiver": "NSKeyedArchiver", "$version": 100000,
                           "$top": {"root": root}, "$objects": objs}, fmt=plistlib.FMT_BINARY)
orange = {"Red Component": 1.0, "Green Component": 0.5, "Blue Component": 0.0,
          "Color Space": "sRGB"}
state = sb / "iterm-state.sqlite"
db = _sq.connect(str(state))
db.execute("CREATE TABLE Node (key text not null, identifier text not null, "
           "parent integer not null, data blob)")
for key, blob in (
        ("Session", keyed({"TTY": "/dev/ttysW2", "Bookmark": {
            "Use Separate Colors for Light and Dark Mode": True,
            "Use Tab Color (Light)": True, "Tab Color (Light)": orange,
            "Use Tab Color (Dark)": True, "Tab Color (Dark)": orange}})),
        ("Session", keyed({"TTY": "/dev/ttysW1", "Bookmark": {
            "Use Tab Color": False, "Tab Color": orange}})),
        ("Session", b"not a plist at all, Tab Color"),
        ("Screen State", keyed({"TTY": "/dev/ttysW1"}))):
    db.execute("INSERT INTO Node VALUES (?, '', 0, ?)", (key, blob))
db.commit()
db.close()
tabs_file.write_text(json.dumps({
    "/dev/ttysW1": {"title": "Paper", "override": True, "pane": 1, "panes": 1, "window": 1,
                    "tab": 1, "profile": "Work"},
    "/dev/ttysW2": {"title": "Notes", "override": True, "pane": 1, "panes": 1, "window": 1,
                    "tab": 2, "profile": "Default"}}))
cenv = dict(wenv, AHT_ITERM_STATE=str(state),
            AHT_TTY_PROCS=json.dumps({"/dev/ttysW1": [[shell.pid, "-zsh"]],
                                      "/dev/ttysW2": [[shell.pid, "-zsh"]]}))
newest = Path(JS("workspace", "--save", "--json", extra_env=cenv).get("saved") or "missing")
snap2 = json.loads(newest.read_text())
c1 = next((e for e in snap2["tabs"] if e["title"] == "Paper"), {})
c2 = next((e for e in snap2["tabs"] if e["title"] == "Notes"), {})
ck(c2.get("color") == "#ff8000" and c1.get("color") is None and c1.get("profile") == "Work",
   f"workspace: each tab's colour and profile are kept ({c1}, {c2})")
tabs_file.write_text(json.dumps({"/dev/ttysW3": {"title": "", "override": False, "pane": 1,
                                                 "panes": 1, "window": 1, "tab": 1}}))
d = JS("workspace", "--restore", newest.stem, "--apply", "--json",
       extra_env=dict(cenv, AHT_ITERM_STARTED="1",
                      AHT_TTY_PROCS=json.dumps({"/dev/ttysW3": [[shell.pid, "-zsh"]]})))
script = [x["script"] for x in ilines() if x.get("what") == "restore"][-1]
ck(d.get("applied") and "set w to current window" in script
   and 'create tab with profile "Default"' in script and "create tab with default profile" in script
   and "bg;red;brightness;255" in script and "bg;green;brightness;128" in script
   and "bg;blue;brightness;0" in script and script.count("brightness") == 3
   and script.count("; clear") == 2,
   "workspace: tabs open with their profile and colour, in the window iTerm2 opened as it started")
(sb / ".aht" / "run" / "workspace-opened.json").unlink()

# saved every few minutes by the app, the last workspace_keep kept
run("config", "--set", "workspace_keep=2", "--no-reload")
a1 = JS("workspace", "--save", "--auto", "--json", extra_env=cenv)
a2 = JS("workspace", "--save", "--auto", "--json", extra_env=cenv)
run("config", "--set", "workspace_save_minutes=0", "--no-reload")
a3 = JS("workspace", "--save", "--auto", "--json", extra_env=cenv)
kept = len(list((sb / ".aht" / "workspaces").glob("*.json")))
ck(a1.get("saved") and not a2.get("saved") and "ago" in str(a2.get("skipped"))
   and a3.get("skipped") == "off" and kept == 2,
   f"workspace: saved on a timer, not more often, and only the last 2 kept ({a1}, {a2}, {a3}, {kept})")
run("config", "--unset", "workspace_keep")
run("config", "--unset", "workspace_save_minutes")

# go to a session's tab; a background session has none
p2 = fake_claude("w2")
genv = dict(wenv, AHT_TTYS=json.dumps({str(p2.pid): "/dev/ttysW3"}))
r = run("goto", str(p2.pid), extra_env=genv)
ck(r.returncode == 0 and {"tty": "/dev/ttysW3", "what": "goto", "text": ""} in ilines(),
   "goto: the session's tab is brought to the front")
r = run("goto", "w2", extra_env=dict(wenv, AHT_TTYS="{}"))
ck(r.returncode == 1 and "background" in r.stderr, "goto: a background session has no tab")

# the checkup: open twice, stuck, outside the app, older Claude Code
(tools / "settings.json").write_text(json.dumps({"remoteControlAtStartup": True}))
old = int((time.time() - 5 * 3600) * 1000)
p3 = fake_claude("w3")
p4 = subprocess.Popen(["sleep", "600"], cwd="/", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
(rec / f"{p3.pid}.json").write_text(json.dumps({"pid": p3.pid, "cwd": projX, "sessionId": "w3",
    "status": "busy", "statusUpdatedAt": old, "version": "1.0.0", "kind": "interactive"}))
(rec / f"{p4.pid}.json").write_text(json.dumps({"pid": p4.pid, "cwd": projX, "sessionId": "w3",
    "status": "idle", "version": "9.9.9", "kind": "interactive", "bridgeSessionId": "b1"}))
os.utime(tstore / "w3.jsonl", (time.time() - 5 * 3600, time.time() - 5 * 3600))
cenv = dict(wenv, AHT_TTYS=json.dumps({str(p3.pid): "/dev/ttysW3", str(p2.pid): "/dev/ttysW3"}),
            AHT_CMDLINES=json.dumps({str(p3.pid): "claude --model sonnet --resume w3"}))
rows = {r["pid"]: r for r in JS("checkup", "--json", extra_env=cenv).get("sessions", [])}
i3, i4 = rows.get(p3.pid, {}).get("issues", []), rows.get(p4.pid, {}).get("issues", [])
ck(sorted(i3) == ["older", "outside the app", "stuck", "twice"] and i4 == ["twice"]
   and rows[p3.pid]["can_restart"],
   f"checkup: open twice, stuck, outside the app, older ({i3}, {i4})")
d = JS("checkup", "--restart", str(p3.pid), "--apply", "--json", extra_env=cenv)
typed = [x for x in ilines() if x.get("what") == "write"]
ck(d.get("applied") and p3.wait(timeout=5) is not None and typed
   and typed[-1]["tty"] == "/dev/ttysW3" and "--model sonnet --resume w3" in typed[-1]["text"],
   f"checkup --restart: ended, then started again in its tab with its options ({d})")
d = JS("checkup", "--close", str(p4.pid), "--apply", "--json", extra_env=cenv)
ck(d.get("applied") and p4.wait(timeout=5) is not None,
   "checkup --close: the process ends; its conversation stays")
for pr in (p2, shell):
    pr.kill(); pr.wait()
for f in rec.glob("*.json"):
    f.unlink()

# tidy: a history without a folder goes to the Trash, only when asked
orphan = tools / "claude" / "-gone-forever"
orphan.mkdir()
(orphan / "o1.jsonl").write_text(json.dumps({"type": "user", "cwd": "/gone/forever",
                                             "message": {"role": "user", "content": "x"}}) + "\n")
trash = sb / "trash"
d = JS("tidy", "--show=-gone-forever", "--json")
row = next((o for o in JS("tidy", "--json").get("orphans", []) if o["store"] == "-gone-forever"), {})
ck("# History of /gone/forever" in d.get("markdown", "") and "**You:** x" in d["markdown"]
   and row.get("sessions") == 1 and row.get("bytes", 0) > 0 and row.get("last"),
   f"tidy --show: a history to read before deciding, with its size and last use ({row})")
r = run("tidy", "--remove-history=-gone-forever", extra_env={"AHT_TRASH": str(trash)})
ck(r.returncode == 0 and orphan.is_dir(), "tidy --remove-history: a dry run first")
d = JS("tidy", "--remove-history=-gone-forever", "--apply", "--json",
       extra_env={"AHT_TRASH": str(trash)})
ck(d.get("applied") and not orphan.exists() and (trash / "-gone-forever" / "o1.jsonl").is_file(),
   "tidy --remove-history: moved to the Trash")
r = run("tidy", "--remove-history=" + enc(projX), "--apply", extra_env={"AHT_TRASH": str(trash)})
ck(r.returncode == 3 and (tools / "claude" / enc(projX)).is_dir(),
   "tidy --remove-history: never a history a tracked project owns")

# Claude Code's own continue-after-the-limit, switched from aht
run("limits", "--auto-continue", "on")
st = json.loads((tools / "settings.json").read_text())
ck(st.get("autoContinueAtUsageLimit") is True and st.get("remoteControlAtStartup") is True
   and JS("limits", "--json").get("auto_continue") is True,
   "limits --auto-continue: Claude Code's setting, the others left as they were")

print("\n[21] the documentation covers everything")
import re as _re
guide = (HERE.parent / "GUIDE.md").read_text()
heads = [l[3:].strip().lower() for l in guide.splitlines() if l.startswith("## ")]
swift = (HERE.parent / "macos" / "tray.swift").read_text()
topics = set(_re.findall(r'HelpButton\("([^"]+)"\)', swift)) \
    | set(_re.findall(r'headed\([^\n]*?, "([^"]+)"\)', swift)) \
    | set(_re.findall(r'topic: "([^"]+)"', swift))
lost = sorted(t for t in topics if not any(h.startswith(t.lower()) for h in heads))
ck(topics and not lost, f"every ? in the window opens a section of the guide ({lost})")
sys.path.insert(0, str(HERE.parent))
import aht as _core
subs = [a for a in _core.build_parser()._actions
        if a.__class__.__name__ == "_SubParsersAction"][0].choices
ck(not [n for n in subs if not n.startswith("_") and f"aht {n}" not in guide],
   "every command is in the guide")
loose = _re.findall(r'"--(store|task|rename|relink|remove-history|show|to)", '
                   r'(?:t\.key|task|sid|dst|j\[|name)', swift)
ck(not loose, f"the window glues values to their options, so a value may begin with a dash ({loose})")
r = run("bind", "--store=-Users-nobody-gone", "--to=/nonexistent")
ck("expected one argument" not in r.stderr, "bind --store=<name beginning with a dash> is read right")
ck(not [k for k in _core.CONFIG_DEFAULTS if f"`{k}`" not in guide],
   f"every setting is in the guide ({[k for k in _core.CONFIG_DEFAULTS if f'`{k}`' not in guide]})")

run("config", "--set", "terminal_app=Terminal")
probe = "import sys; sys.path.insert(0, sys.argv[1]); import aht; print(aht.terminal_choice())"
r = subprocess.run([PY, "-c", probe, str(HERE.parent)], env=env, capture_output=True, text=True)
ck(r.stdout.strip() == "Terminal", f"terminal_app: the chosen terminal is used ({r.stdout.strip()})")
run("config", "--unset", "terminal_app")

shutil.rmtree(sb, ignore_errors=True)
print("\nCORE RESULT:", "ALL PASS" if not FAILS else f"{len(FAILS)} FAIL")
for f in FAILS:
    print("  -", f)
sys.exit(1 if FAILS else 0)
