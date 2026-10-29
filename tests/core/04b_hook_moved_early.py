#!/usr/bin/env python3
"""[4b] hook backstop: moved after its first session, before its store was recorded."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)

print("\n[4b] hook backstop: moved after its first session, before its store was recorded")
he = iso_env("hookmove")
hst = Path(he["AHT_ROOT_CLAUDE"])
hold = os.path.realpath(he["HOME"]) + os.sep + "app"     # outside every watched folder
os.makedirs(hold)
hk = lambda cwd: iso_run(he, "hook", stdin=json.dumps(
    {"cwd": cwd, "source": "startup", "transcript_path": str(hst / enc(cwd) / "t1.jsonl")}))
hk(hold)                                # Claude writes its store only after this
(hst / enc(hold)).mkdir()
(hst / enc(hold) / "t1.jsonl").write_text(json.dumps({"cwd": hold}) + "\n")
hnew = hold + "-renamed"
os.rename(hold, hnew)
r = hk(hnew)
hreg = json.loads((Path(he["AHT_HOME"]) / "registry.json").read_text())["projects"]
ck(r.returncode == 0 and (hst / enc(hnew) / "t1.jsonl").is_file()
   and not (hst / enc(hold)).exists()
   and [(e["real_path"], (e.get("stores") or {}).get("claude")) for e in hreg.values()]
   == [(hnew, enc(hnew))],
   f"hook: the history follows a folder moved before its store was recorded ({hreg})")

done()
