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

shutil.rmtree(sb, ignore_errors=True)
print("\nCORE RESULT:", "ALL PASS" if not FAILS else f"{len(FAILS)} FAIL")
for f in FAILS:
    print("  -", f)
sys.exit(1 if FAILS else 0)
