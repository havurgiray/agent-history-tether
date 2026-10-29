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

done()
