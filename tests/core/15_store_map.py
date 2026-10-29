#!/usr/bin/env python3
"""[15] the store map follows reality after registration."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)

# what earlier sections left: [14]'s name for Kimi Code's store and its
# badge probe (kkey comes with common)
khome = tools / "kimi-code"
marks_probe = ("import sys; sys.path.insert(0, sys.argv[1]); import aht; "
               "print(aht.desired_marks(sys.argv[2], True))")

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
r = subprocess.run([PY, LAUNCH, "hook"], env=env, capture_output=True, text=True,
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
# Antigravity and Mistral Vibe are only read: their sessions in the folder
# show on its badge, and their stores never enter the store map
import fake_agy, fake_vibe
aroot = Path(env["AHT_ROOT_AGY"])
fake_agy.close_cleanly(fake_agy.build(aroot, late, "LATE-AGY"), aroot)
fake_vibe.build(env["AHT_ROOT_VIBE"], late, str(roots / "elsewhere"), "LATE-VIBE")
def late_entry():
    reg = json.loads((sb / ".aht" / "registry.json").read_text())
    return next(e for e in reg["projects"].values() if e["real_path"] == late)
r = run("reconcile", "--apply")
le = late_entry()
r = subprocess.run([PY, "-c", marks_probe, str(HERE.parent), late], env=env,
                   capture_output=True, text=True)
ck(le.get("read_agents") == ["agy", "vibe"] and sorted(le.get("stores") or {}) == ["codex", "kimi-code"]
   and "'agent:kimi', 'agent:agy', 'agent:vibe']" in r.stdout,
   f"Antigravity's and Vibe's sessions show on the badge, after the relinked agents, "
   f"and stay out of the store map ({le.get('read_agents')}, {r.stdout.strip()})")
shutil.rmtree(aroot)
aroot.mkdir()
r = run("icons", "--refresh")
ck(late_entry().get("read_agents") == ["vibe"],
   f"icons --refresh drops an agent only read whose sessions are gone ({late_entry().get('read_agents')})")
shutil.rmtree(Path(env["AHT_ROOT_VIBE"]))
Path(env["AHT_ROOT_VIBE"]).mkdir()
r = run("icons", "--refresh")
ck("read_agents" not in late_entry(), "and drops the field when none is left")
r = run("logs", "-n", "400")
ck("STORES " in r.stdout, "agent-list changes are logged")

done()
