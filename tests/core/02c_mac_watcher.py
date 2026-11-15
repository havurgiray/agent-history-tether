#!/usr/bin/env python3
"""[2c] the Mac watcher (watcher.swift, built here): a project that is
renamed, or moved out of the watched folders, is relinked within a second or
two and with no walk; saving files inside a project starts nothing; a copy
and a new git repository are seen where they appear; a move you declined is
not brought up again with every change."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)
from first_sections import made_projA, tagged

print("\n[2c] the Mac watcher: no search, and no run for a saved file")
if sys.platform != "darwin" or not shutil.which("swiftc"):
    print("  SKIP the Mac watcher needs macOS and swiftc")
    done()
    sys.exit(0)

projA = made_projA()
uid = tagged(projA)
home = sb / ".aht"
exe = sb / "watcher"
b = subprocess.run(["swiftc", "-O", str(HERE.parent / "watcher.swift"), "-o", str(exe)],
                   capture_output=True, text=True)
ck(b.returncode == 0 and exe.is_file(), f"watcher.swift builds ({b.stderr[-300:]})")
run("reconcile", "--apply")                     # the day's walk is done
logf = sb / "watcher.log"


def reg():
    try:
        return json.loads((home / "registry.json").read_text())
    except ValueError:
        return {"projects": {}}


def runs():
    return [l for l in logf.read_text().splitlines() if l.startswith("[")] if logf.exists() else []


def until(cond, secs=8.0):
    t0 = time.time()
    while time.time() - t0 < secs:
        if cond():
            return time.time() - t0
        time.sleep(0.05)
    return None


def start(**more):
    e = dict(env, AHT_WATCHER_SCRIPT=LAUNCH, AHT_WATCHER_PYTHON=PY, AHT_WATCHER_DEBUG="1",
             AHT_WATCHER_TICK="3600", **more)
    out = open(logf, "a")
    p = subprocess.Popen([str(exe), os.path.realpath(str(roots))], env=e, stdout=out,
                         stderr=subprocess.STDOUT)
    out.close()
    return p


w = start(AHT_ASSUME="Relink")
try:
    ck(until(lambda: len(runs()) == 1) is not None and "the regular look" in runs()[0],
       f"at its start it looks once, by the ids ({runs()})")
    time.sleep(0.6)

    # files saved inside the project, and in a folder inside it
    os.makedirs(os.path.join(projA, "src"), exist_ok=True)
    for i in range(20):
        Path(projA, "src", f"f{i}.txt").write_text("x")
        Path(projA, f"g{i}.txt").write_text("x")
    time.sleep(1.5)
    ck(len(runs()) == 1, f"files saved inside a project start nothing ({runs()[1:]})")

    # renamed
    projB = os.path.realpath(str(roots / "projB"))
    os.rename(projA, projB)
    took = until(lambda: reg()["projects"].get(uid, {}).get("real_path") == projB)
    ck(took is not None and (tools / "claude" / enc(projB)).is_dir(),
       f"a renamed project is relinked ({'%.2f s' % took if took else 'not in 8 s'}; {runs()[-1:]})")
    until(lambda: "relinked" in "".join(runs()[-1:]))       # its line comes when the run ended
    last = runs()[-1] if runs() else ""
    ck("1 relinked" in last and "walk" not in last, f"…by its id, with no walk ({last})")

    # out of the watched folders
    out = Path(os.path.realpath(sb)) / "elsewhere"
    out.mkdir()
    projC = str(out / "projC")
    os.rename(projB, projC)
    took = until(lambda: reg()["projects"].get(uid, {}).get("real_path") == projC)
    ck(took is not None,
       f"moved out of the watched folders: found and relinked "
       f"({'%.2f s' % took if took else 'not in 8 s'})")
    os.rename(projC, projB)
    until(lambda: reg()["projects"].get(uid, {}).get("real_path") == projB)

    # a parent folder renamed
    os.makedirs(str(roots / "group"))
    os.rename(projB, str(roots / "group" / "projB"))
    until(lambda: reg()["projects"].get(uid, {}).get("real_path", "").endswith("group/projB"))
    os.rename(str(roots / "group"), str(roots / "group2"))
    projD = os.path.realpath(str(roots / "group2" / "projB"))
    took = until(lambda: reg()["projects"].get(uid, {}).get("real_path") == projD)
    ck(took is not None, f"a parent folder renamed: relinked "
                         f"({'%.2f s' % took if took else 'not in 8 s'})")

finally:
    w.terminate()
    w.wait()

w = start(AHT_ASSUME="Duplicate")
try:
    until(lambda: "the regular look" in "".join(runs()[-1:]))
    time.sleep(0.6)
    # a copy
    n = len(runs())
    copy = os.path.realpath(str(roots / "projCopy"))
    shutil.copytree(projD, copy)
    took = until(lambda: len(reg()["projects"]) == 2)
    ck(took is not None and (Path(copy) / ".aht" / ".project-id").read_text().strip() != uid,
       f"a copy is seen where its marker appeared, and gets its own id "
       f"({'%.2f s' % took if took else 'not in 8 s'}; {runs()[n:]})")

    # a new git repository; work inside it afterwards starts nothing
    gitty = os.path.realpath(str(roots / "gitty"))
    os.makedirs(os.path.join(gitty, ".git"))
    Path(gitty, ".git", "HEAD").write_text("ref: refs/heads/main\n")
    took = until(lambda: gitty in (reg().get("git_repos") or []))
    ck(took is not None, f"a new git repository is noted "
                         f"({'%.2f s' % took if took else 'not in 8 s'})")
    time.sleep(1.0)
    n = len(runs())
    for i in range(10):
        Path(gitty, ".git", f"obj{i}").write_text("x")
        Path(gitty, f"file{i}.txt").write_text("x")
    time.sleep(1.5)
    ck(len(runs()) == n, f"…and work in a known repository starts nothing ({runs()[n:]})")
finally:
    w.terminate()
    w.wait()

# a move you declined: asked once, not again with every change
w = start(AHT_ASSUME="Not now")
try:
    n = len(runs())
    until(lambda: len(runs()) > n and "the regular look" in runs()[-1])
    time.sleep(0.6)
    n = len(runs())
    projE = os.path.realpath(str(roots / "projE"))
    os.rename(projD, projE)
    until(lambda: len(runs()) > n)
    time.sleep(1.0)
    n1 = len(runs())
    for i in range(5):
        Path(os.path.realpath(str(roots)), f"loose{i}.txt").write_text("x")
        time.sleep(0.3)
    time.sleep(1.2)
    ck(n1 == n + 1 and len(runs()) == n1 and reg()["projects"][uid]["real_path"] == projD,
       f"a move you declined is asked about once, not again with every change "
       f"({runs()[n:]})")
finally:
    w.terminate()
    w.wait()

done()
