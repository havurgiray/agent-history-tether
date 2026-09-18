#!/usr/bin/env python3
"""Linux-layer tests that run on any POSIX box: the polling watcher relinks a
live rename (same code path the inotify backend hands off to), and the tray's
--check mode degrades cleanly without desktop deps."""
import hashlib, json, os, re, shutil, subprocess, sys, tempfile, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PY = os.environ.get("AHT_PY", sys.executable or "python3")
FAILS = []
def ck(c, m):
    print(("  PASS " if c else "  FAIL ") + m)
    if not c:
        FAILS.append(m)

sb = Path(tempfile.mkdtemp(prefix="aht_linux_"))
roots = sb / "roots"
(roots / "projA").mkdir(parents=True)
(sb / "claude").mkdir()
env = dict(os.environ)
env.update({"AHT_HOME": str(sb / ".aht"), "AHT_ROOTS": str(roots),
            "AHT_ROOT_CLAUDE": str(sb / "claude"),
            "AHT_NO_ICONS": "1", "AHT_NO_NOTIFY": "1", "AHT_NO_BACKUP": "1",
            "AHT_ASSUME": "Relink"})
for b in ("GEMINI", "CURSOR", "OPENCODE", "CODEX", "COPILOT", "KIMI",
          "KIMI_CODE"):
    env[f"AHT_ROOT_{b}"] = str(sb / "nope")

enc = lambda p: re.sub(r"[^a-zA-Z0-9]", "-", p)
projA = os.path.realpath(str(roots / "projA"))
(sb / "claude" / enc(projA)).mkdir()
(sb / "claude" / enc(projA) / "s1.jsonl").write_text("{}\n")
subprocess.run([PY, str(ROOT / "aht.py"), "tag", projA, "--apply"],
               env=env, capture_output=True)

print("\n[1] polling watcher relinks a live rename")
proc = subprocess.Popen([PY, str(ROOT / "linux" / "watcher.py"),
                         "--poll", "--poll-interval", "1", "--once",
                         "--no-startup-scan"],
                        env=env, stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT, text=True)
time.sleep(2.5)
shutil.move(projA, str(roots / "projB"))
projB = os.path.realpath(str(roots / "projB"))
try:
    proc.wait(timeout=60)
    ck(True, "watcher handled the batch and exited (--once)")
except subprocess.TimeoutExpired:
    proc.kill()
    ck(False, "watcher did not exit")
ck((sb / "claude" / enc(projB)).is_dir(), "claude store relinked by the watcher")

print("\n[2] tray --check degrades cleanly without desktop deps")
r = subprocess.run([PY, str(ROOT / "linux" / "tray.py"), "--check"],
                   env=env, capture_output=True, text=True)
ck(r.returncode in (0, 3),
   "tray --check exits 0 (deps present) or 3 (missing), got %d" % r.returncode)
ck("core" in r.stdout and "aht" in r.stdout, "check reports the core wiring")
ck((sb / ".aht" / "aht-icons" / "aht-tray.png").is_file(),
   "tray icons generated into the (fake) aht home")
if r.returncode == 3:
    ck("PyGObject" in r.stdout or "apt install" in r.stdout,
       "missing-deps message carries install hints")

shutil.rmtree(sb, ignore_errors=True)
print("\nLINUX RESULT:", "ALL PASS" if not FAILS else "%d FAIL" % len(FAILS))
for f in FAILS:
    print("  -", f)
sys.exit(1 if FAILS else 0)
