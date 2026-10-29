"""What the first sections of tests/core_test.py ([1] to [6]) leave in the
sandbox, rebuilt for a unit that needs it.  Each function is one section's
setup code, copied as it is there, without its checks; a unit calls only the
ones its own checks need, in the original order (an earlier step feeds the
next).  Not a unit: its name starts with no digit."""
from common import *  # noqa: F401,F403  (this unit's sandbox, run, mkstores, ...)


def made_projA():
    """The shared setup before [1]: projA, with a file and every agent's store."""
    projA = os.path.realpath(str(roots / "projA"))
    (Path(projA) / "src").mkdir()
    (Path(projA) / "src" / "main.py").write_text("x")
    mkstores(projA)
    return projA


def tagged(projA):
    """[1]: projA tagged -> its uuid (the registry's only project)."""
    run("tag", projA, "--apply")
    reg = json.loads((sb / ".aht" / "registry.json").read_text())
    return list(reg["projects"])[0]


def moved_to_projB(projA):
    """[2]: projA moved to projB, the move reconciled -> projB."""
    shutil.move(projA, str(roots / "projB"))
    projB = os.path.realpath(str(roots / "projB"))
    run("reconcile", "--apply")
    return projB


def copied_to_projC(projB):
    """[3]: projB copied to projC, the copy duplicated -> projC."""
    shutil.copytree(projB, str(roots / "projC"))
    projC = os.path.realpath(str(roots / "projC"))
    run("reconcile", "--notify", extra_env={"AHT_ASSUME": "Duplicate"})
    return projC


def parent_copied(projC):
    """[3b]: projC copied inside a parent folder, duplicated -> box/projC."""
    (roots / "box").mkdir()
    shutil.copytree(projC, str(roots / "box" / "projC"))
    run("reconcile", "--notify", extra_env={"AHT_ASSUME": "Duplicate"})
    return os.path.realpath(str(roots / "box" / "projC"))


def hooked_to_projD(projB):
    """[4]: projB moved to projD, relinked by the hook -> projD."""
    shutil.move(projB, str(roots / "projD"))
    projD = os.path.realpath(str(roots / "projD"))
    hook_in = json.dumps({"cwd": projD,
                          "transcript_path": str(tools / "claude" / enc(projD) / "t.jsonl")})
    subprocess.run([PY, LAUNCH, "hook"], env=env, input=hook_in,
                   capture_output=True, text=True)
    return projD


def conflict_projE(projD):
    """[5]: projD moved to projE, whose claude store is taken: the conflict
    is refused (and logged), the rest relinked -> projE."""
    projE = os.path.realpath(str(roots / "projE"))
    (tools / "claude" / enc(projE)).mkdir()          # squatter on the claude target
    (tools / "claude" / enc(projE) / "other.jsonl").write_text("{}")
    shutil.move(projD, projE)
    run("reconcile", "--apply")
    return projE


def restored_projF(projE):
    """[6]: backed up twice, two stores lost, moved to projF and restored
    there (twice, the second for kimi) -> projF."""
    run("backup", "--json")
    run("backup", "--json")
    # lose two stores + move, restore via the travelling marker
    shutil.rmtree(tools / "gemini" / sha(projE), ignore_errors=True)
    shutil.move(projE, str(roots / "projF"))
    projF = os.path.realpath(str(roots / "projF"))
    run("restore", projF, "--apply", "--json")
    shutil.rmtree(tools / "kimi" / "sessions" / md5(projF), ignore_errors=True)
    (tools / "kimi" / "user-history" / (md5(projF) + ".jsonl")).unlink()
    run("restore", projF, "--apply", "--json")
    return projF
