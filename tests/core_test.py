#!/usr/bin/env python3
"""agent-history-tether core tests: every unit in tests/core/ at once.

Each unit is a file that runs alone in a sandbox of its own (`python
tests/core/16_handover_rsync.py`), so they run side by side, the slowest
first.  Each unit's output is printed whole when it ends, then the totals.

  --jobs N        how many at once (default: the number of CPUs)
  --only A,B      just these: a unit's name or the start of it, or a
                  section's number as it prints it (16c, [16c])
  --list          the units, their sections and how long each took last
  --transport     just aht's own copy, in test mode (the Windows CI job)
  --all           also the other suites (masker, Linux, Windows, far end)
"""
import argparse
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="backslashreplace")

HERE = Path(__file__).resolve().parent
UNITS = HERE / "core"
TIMES = HERE / ".unit-times.json"       # how long each unit took last (git-ignored)
OTHER = [("masker", HERE / "redact_test.py"),
         ("linux", HERE / "linux_test.py"),
         ("winbadge", HERE.parent / "windows" / "tests" / "winbadge_test.py"),
         ("aht_main", HERE.parent / "windows" / "tests" / "aht_main_test.py"),
         ("aht_tray", HERE.parent / "windows" / "tests" / "aht_tray_test.py"),
         ("agent_smoke", HERE.parent / "windows" / "tests" / "agent_smoke.py")]
_SECTION = re.compile(r'print\(f?"\\n\[(\w+)\]')


def units():
    """(name, path, sections) of every unit, in name order."""
    out = []
    for p in sorted(UNITS.glob("[0-9]*.py")):
        out.append((p.stem, p, _SECTION.findall(p.read_text(encoding="utf-8"))))
    return out


def chosen(only, every):
    keys = [k.strip().strip("[]") for k in only.split(",") if k.strip()]
    pick = [u for u in every if any(u[0] == k or u[0].startswith(k + "_")
                                    or k in u[2] for k in keys)]
    lost = [k for k in keys if not any(u[0] == k or u[0].startswith(k + "_") or k in u[2]
                                       for u in every)]
    return pick, lost


def load_times():
    try:
        return json.loads(TIMES.read_text())
    except (OSError, ValueError):
        return {}


LIVE = set()                            # the units running now (Ctrl-C ends them)


def _signal_group(p, sig):
    try:
        if os.name == "nt":
            p.kill()
        else:
            os.killpg(p.pid, sig)
    except OSError:
        pass


def stop(p, grace=5.0):
    """End a unit: asked first (it removes its sandboxes), then killed, with
    whatever it started in its process group."""
    _signal_group(p, signal.SIGTERM)
    try:
        p.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        pass
    _signal_group(p, signal.SIGKILL if os.name != "nt" else signal.SIGTERM)
    p.wait()


def run_one(name, path, py, timeout):
    """(name, exit code, output, seconds) of one unit or suite.  Its output
    goes to a file, and the unit's own end is awaited, not the end of its
    output: a process it left behind may still hold that open."""
    t0 = time.time()
    kw = {"start_new_session": True} if os.name != "nt" else {}
    with tempfile.TemporaryFile() as out:
        p = subprocess.Popen([py, str(path)], cwd=str(HERE), stdout=out,
                             stderr=subprocess.STDOUT,
                             env=dict(os.environ, PYTHONUNBUFFERED="1",
                                      PYTHONIOENCODING="utf-8"), **kw)
        LIVE.add(p)
        try:
            p.wait(timeout=timeout)
            rc = p.returncode
            if os.name != "nt":
                _signal_group(p, signal.SIGKILL)     # what it left running
        except subprocess.TimeoutExpired:
            stop(p)
            rc = 124
        finally:
            LIVE.discard(p)
        out.seek(0)
        text = out.read().decode("utf-8", "replace")
    if rc == 124:
        text += f"\n  FAIL {name} took longer than {timeout} s and was stopped\n"
    return name, rc, text, time.time() - t0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 2)
    ap.add_argument("--only", default="")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--transport", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--timeout", type=int, default=1800, help="seconds a unit may take")
    a = ap.parse_args()
    py = os.environ.get("AHT_PY", sys.executable or "python3")
    every = units()
    times = load_times()
    if a.list:
        for name, path, secs in every:
            last = f"{times[name]:6.1f} s" if name in times else "      ?"
            print(f"{last}  {name:34} {' '.join('[' + s + ']' for s in secs)}")
        return 0
    todo = every
    if a.transport:
        todo = [u for u in every if "transport" in u[0]]
    elif a.only:
        todo, lost = chosen(a.only, every)
        if lost:
            print(f"no unit or section named {', '.join(lost)} (see --list)")
            return 2
    jobs = [(n, p) for n, p, _s in todo]
    if a.all and not a.only and not a.transport:
        jobs += [(n, p) for n, p in OTHER]
    if not jobs:
        print("nothing to run (see --list)")
        return 2
    # the slowest first: the last run's times, else the biggest file first
    jobs.sort(key=lambda j: -(times.get(j[0]) or j[1].stat().st_size / 2000.0))
    print(f"{len(jobs)} unit(s), {min(a.jobs, len(jobs))} at once")
    lock = threading.Lock()
    results = []
    t0 = time.time()

    def go(job):
        r = run_one(job[0], job[1], py, a.timeout)
        with lock:
            name, rc, out, took = r
            passed = len(re.findall(r"(?m)^  PASS ", out))
            print(f"\n=== {name}: {'ok' if rc == 0 else f'FAILED (exit {rc})'}, "
                  f"{passed} passed, {took:.1f} s ===")
            print(out.rstrip("\n"), flush=True)
            results.append((name, rc, out, took, passed))
        return r

    ex = ThreadPoolExecutor(max_workers=max(1, a.jobs))
    try:
        list(ex.map(go, jobs))
    except KeyboardInterrupt:
        ex.shutdown(wait=False, cancel_futures=True)
        running = list(LIVE)
        for p in running:
            _signal_group(p, signal.SIGTERM)
        for p in running:
            stop(p)
        print(f"\nstopped: {len(running)} unit(s) that still ran were ended")
        return 130
    ex.shutdown()
    wall = time.time() - t0
    times.update({r[0]: round(r[3], 1) for r in results})
    try:
        TIMES.write_text(json.dumps(times, indent=1, sort_keys=True) + "\n")
    except OSError:
        pass

    bad = [r for r in results if r[1] != 0]
    passed = sum(r[4] for r in results)
    print("\n--- the slowest units ---")
    for name, rc, out, took, n in sorted(results, key=lambda r: -r[3])[:8]:
        print(f"{took:7.1f} s  {name}")
    print(f"\n{len(results)} unit(s), {passed} checks passed, {wall:.0f} s "
          f"({sum(r[3] for r in results):.0f} s of units, {min(a.jobs, len(jobs))} at once)")
    for name, rc, out, took, n in bad:
        fails = re.findall(r"(?m)^  FAIL (.*)$", out)
        if not fails:
            fails = [f"ended without its result (exit {rc}): "
                     + " | ".join(out.strip().splitlines()[-3:])]
        for f in fails:
            print(f"  - {name}: {f}")
    print("\nCORE RESULT:", "ALL PASS" if not bad else
          f"{sum(max(1, len(re.findall(r'(?m)^  FAIL ', r[2]))) for r in bad)} FAIL")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
