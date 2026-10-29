#!/usr/bin/env python3
"""[14] Kimi Code 2.x: bucket key, relink, copy, restore."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)

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

done()
