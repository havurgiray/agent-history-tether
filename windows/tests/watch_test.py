#!/usr/bin/env python3
"""The Windows watcher for real, from source, in a throwaway aht home: a
project that is renamed, moved to another folder or whose parent is renamed
is relinked within a second or two and with no walk; folders made inside a
project start nothing; a copy is seen where its marker appears.

    python windows\\tests\\watch_test.py

Windows only (ReadDirectoryChangesW, and the folder ids NTFS keeps)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

if os.name != "nt":
    print("SKIP: the Windows watcher needs Windows")
    sys.exit(0)

REPO = Path(__file__).resolve().parents[2]
SB = Path(tempfile.mkdtemp(prefix="aht_watch_"))
home, roots, tools = SB / "home" / ".aht", SB / "roots", SB / "tools"
for d in (home, roots, tools / "claude"):
    d.mkdir(parents=True)
env = dict(os.environ, HOME=str(SB / "home"), USERPROFILE=str(SB / "home"), AHT_HOME=str(home),
           AHT_ROOTS=str(roots), AHT_ROOT_CLAUDE=str(tools / "claude"),
           AHT_NO_SEARCH_INDEX="1", AHT_NO_ICONS="1", AHT_NO_NOTIFY="1", AHT_NO_BACKUP="1",
           AHT_NO_MIRROR="1", AHT_NO_CHECKPOINT="1", AHT_WATCHER_DEBUG="1")
for k in ("GEMINI", "CURSOR", "OPENCODE", "CODEX", "COPILOT", "KIMI", "KIMI_CODE", "VIBE", "AGY"):
    (tools / k.lower()).mkdir()
    env["AHT_ROOT_" + k] = str(tools / k.lower())
MAIN = [sys.executable, str(REPO / "windows" / "src" / "aht_main.py")]
failed = 0


def ck(cond, msg):
    global failed
    failed += 0 if cond else 1
    print(("  PASS " if cond else "  FAIL ") + msg, flush=True)


def aht(*a):
    return subprocess.run(MAIN + list(a), env=env, capture_output=True, text=True,
                          creationflags=0x08000000)


def reg():
    try:
        return json.loads((home / "registry.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"projects": {}}


def runs():
    try:
        return [l for l in (home / "aht.log").read_text(encoding="utf-8", errors="replace")
                .splitlines() if "WATCHER reconcile" in l]
    except OSError:
        return []


def until(cond, secs=10.0):
    t0 = time.time()
    while time.time() - t0 < secs:
        if cond():
            return time.time() - t0
        time.sleep(0.05)
    return None


def took(t):
    return "%.2f s" % t if t is not None else "not in 10 s"


proj = roots / "projA"
(proj / "src").mkdir(parents=True)
(proj / "notes.md").write_text("x", encoding="utf-8")
r = aht("tag", str(proj), "--apply")
uid = (proj / ".aht" / ".project-id").read_text(encoding="utf-8").strip()
aht("config", "--set", "move_policy=apply", "copy_policy=duplicate")
aht("reconcile", "--apply")                     # the day's walk is done
e = reg()["projects"].get(uid, {})
ck(bool((e.get("fid") or {}).get("ino")), f"the project's folder id is noted ({e.get('fid')})")

w = subprocess.Popen(MAIN + ["watch", str(roots), "--no-startup-scan"], env=env,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=0x08000000)
try:
    time.sleep(2.0)
    ck(w.poll() is None, "the watcher runs")

    # folders made and removed inside the project, files saved
    n = len(runs())
    for i in range(40):
        (proj / "build" / f"d{i}").mkdir(parents=True)
        (proj / "build" / f"d{i}" / "f.txt").write_text("x", encoding="utf-8")
    shutil.rmtree(proj / "build")
    time.sleep(2.0)
    ck(len(runs()) == n, f"folders made inside a project start nothing ({runs()[n:]})")

    def at(p):
        return lambda: os.path.normcase(reg()["projects"].get(uid, {}).get("real_path", "")) \
            == os.path.normcase(str(p))

    projB = roots / "projB"
    os.rename(proj, projB)
    t = until(at(projB))
    ck(t is not None, f"a renamed project is relinked ({took(t)})")
    time.sleep(1.0)
    last = (runs() or [""])[-1]
    ck("moves=1" in last and "walk" not in last, f"…with no walk ({last[-70:]})")

    (roots / "group").mkdir()
    projC = roots / "group" / "projB"
    os.rename(projB, projC)                     # to another folder: no rename is told
    t = until(at(projC))
    ck(t is not None, f"moved to another folder: relinked, found by its id ({took(t)})")
    time.sleep(1.0)

    os.rename(roots / "group", roots / "group2")
    projD = roots / "group2" / "projB"
    t = until(at(projD))
    ck(t is not None, f"a parent folder renamed: relinked ({took(t)})")
    time.sleep(1.0)

    out = SB / "outside"
    out.mkdir()
    projE = out / "projE"
    os.rename(projD, projE)                     # out of the watched folders
    t = until(at(projE))
    ck(t is not None, f"moved out of the watched folders: relinked ({took(t)})")
    time.sleep(1.0)

    copy = roots / "projCopy"
    shutil.copytree(projE, copy)
    t = until(lambda: len(reg()["projects"]) == 2)
    ck(t is not None and (copy / ".aht" / ".project-id").read_text(encoding="utf-8").strip() != uid,
       f"a copy is seen where its marker appeared, and gets its own id ({took(t)})")

    os.rename(projE, projE.with_name("PROJe"))  # only the case
    t = until(lambda: reg()["projects"].get(uid, {}).get("real_path", "").endswith("PROJe"))
    ck(t is not None, f"renamed by case only: followed ({took(t)})")
finally:
    w.terminate()
    w.wait()
    time.sleep(0.5)
    shutil.rmtree(SB, ignore_errors=True)

print(f"\nWATCH RESULT: {'ALL PASS' if not failed else f'{failed} FAILED'}")
sys.exit(1 if failed else 0)
