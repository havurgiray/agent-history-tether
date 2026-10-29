#!/usr/bin/env python3
"""[11] backend store locations are configurable (aht backends)."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)

print("\n[11] backend store locations are configurable (aht backends)")
custom = sb / "elsewhere" / "kimi-sessions"
custom.mkdir(parents=True)
env_noenv = dict(env)
env_noenv.pop("AHT_ROOT_KIMI")           # let the config layer take over
r = subprocess.run([PY, LAUNCH, "backends", "--set-root", f"kimi={custom}",
                    "--json"], env=env_noenv, capture_output=True, text=True)
row = next(b for b in json.loads(r.stdout)["backends"] if b["name"] == "kimi")
ck(row["root"] == str(custom) and row["root_source"] == "config"
   and row["available"], "config override resolves + shows as [config]")
r = subprocess.run([PY, LAUNCH, "backends", "--json"], env=env,
                   capture_output=True, text=True)
row = next(b for b in json.loads(r.stdout)["backends"] if b["name"] == "kimi")
ck(row["root_source"] == "env", "AHT_ROOT_* env still wins (test isolation)")
r = subprocess.run([PY, LAUNCH, "backends", "--clear-root", "kimi", "--json"],
                   env=env_noenv, capture_output=True, text=True)
row = next(b for b in json.loads(r.stdout)["backends"] if b["name"] == "kimi")
ck(row["root_source"] == "default", "clear-root restores the default")
r = subprocess.run([PY, LAUNCH, "backends", "--set-root", "nope=/x"],
                   env=env_noenv, capture_output=True, text=True)
ck(r.returncode == 2 and "unknown backend" in r.stderr,
   "unknown backend name is rejected")

# agy and Vibe: aht only reads them, but their data folder is set the same way
r = subprocess.run([PY, LAUNCH, "backends", "--json"], env=env,
                   capture_output=True, text=True)
rows = json.loads(r.stdout)["backends"]
ck(len(rows) == len(core.BACKENDS) + 2
   and [b["name"] for b in rows[-2:]] == ["agy", "vibe"]
   and all(b["relinks"] is False and b["kind"] == "read" for b in rows[-2:])
   and all(b["relinks"] is True for b in rows[:-2]),
   f"agy and Vibe are listed after the agents aht relinks, as only read "
   f"({[(b['name'], b.get('relinks')) for b in rows]})")
custom_agy = sb / "elsewhere" / "agy-data"
custom_agy.mkdir(parents=True)
env_noagy = dict(env)
env_noagy.pop("AHT_ROOT_AGY")
r = subprocess.run([PY, LAUNCH, "backends", "--set-root", f"agy={custom_agy}",
                    "--json"], env=env_noagy, capture_output=True, text=True)
row = next(b for b in json.loads(r.stdout)["backends"] if b["name"] == "agy")
ck(row["root"] == str(custom_agy) and row["root_source"] == "config"
   and row["available"], f"Choose… for agy points aht at its folder ({row})")
r = subprocess.run([PY, LAUNCH, "status", "--json"], env=env_noagy,
                   capture_output=True, text=True)
row = next(b for b in json.loads(r.stdout)["backends"] if b["name"] == "agy")
ck(row["root"] == str(custom_agy), "status (what the windows show) has the same row")
r = subprocess.run([PY, LAUNCH, "backends", "--clear-root",
                    *[b["name"] for b in rows], "--json"],
                   env=env_noagy, capture_output=True, text=True)
out = json.loads(r.stdout)
row = next(b for b in out["backends"] if b["name"] == "agy")
ck(row["root_source"] == "default" and "agy" in out["changed"],
   "Reset All to Defaults (every listed name) resets agy's folder too")

done()
