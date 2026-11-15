#!/usr/bin/env python3
"""[2b] a moved project is found by its folder's id, without a walk of the
watched folders (reconcile --quick, what the watchers run): renamed, moved
out of the watched folders, in the Trash and back; a copy and a new git
repository where the watcher says one appeared (--look); what a watcher saw
renamed (--renamed), where the file system answers no such question; the
walk once a day; the list the watchers read (run/watch.json)."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)
from first_sections import made_projA, tagged

projA = made_projA()
uid = tagged(projA)

print("\n[2b] a moved project is found by its folder's id, without a walk")
sys.path.insert(0, str(HERE.parent))
import aht as core
home = sb / ".aht"


def reg():
    return json.loads((home / "registry.json").read_text())


def watch():
    return json.loads((home / "run" / "watch.json").read_text())


def J(*a, **k):
    return json.loads(run(*a, **k).stdout)


fid = reg()["projects"][uid].get("fid") or {}
has_ids = core.path_of_id(fid) is not None      # macOS and Windows: the file system answers
ck(fid.get("ino") == os.stat(projA).st_ino and os.path.isdir(fid.get("vol", "")),
   f"a tracked project's folder id is noted with it ({fid})")
w = watch()["projects"]
ck(len(w) == 1 and w[0]["path"] == projA and w[0]["ino"] == fid.get("ino") and w[0]["here"],
   f"the watchers' list names it, its id, and that it is there ({w})")
if has_ids:
    ck(os.path.realpath(core.path_of_id(fid)) == projA, "the id leads to the folder")

J("reconcile", "--apply")                       # the day's walk is done
ck(reg().get("full_scan_at"), "a walk notes when it ran")

# renamed, and moved out of the watched folders: no walk finds that one
out = Path(os.path.realpath(sb)) / "outside" / "deeper"
out.mkdir(parents=True)
projQ = str(out / "projQ")
shutil.move(projA, projQ)
if has_ids:
    d = J("reconcile", "--quick", "--apply")
    ck(d["walked"] is False and len(d["applied_moves"]) == 1
       and os.path.realpath(d["applied_moves"][0]["to"]) == projQ
       and reg()["projects"][uid]["real_path"] == projQ
       and (tools / "claude" / enc(projQ)).is_dir(),
       f"--quick: found outside the watched folders by its id, and relinked "
       f"({d['applied_moves']})")
    ck(watch()["projects"][0]["path"] == projQ, "…and the watchers' list follows")
    # a parent folder renamed
    shutil.move(str(out.parent), str(out.parent.parent / "outside2"))
    projQ = str(out.parent.parent / "outside2" / "deeper" / "projQ")
    d = J("reconcile", "--quick", "--apply")
    ck(len(d["applied_moves"]) == 1 and reg()["projects"][uid]["real_path"] == projQ,
       f"--quick: a parent folder renamed ({d['applied_moves']})")
    # the Trash is no new home; back out of it, nothing changed
    trash = Path(os.path.realpath(sb)) / ".Trash"
    trash.mkdir()
    shutil.move(projQ, str(trash / "projQ"))
    d = J("reconcile", "--quick", "--apply")
    ck(not d["applied_moves"] and [m["uuid"] for m in d["missing"]] == [uid]
       and reg()["projects"][uid]["real_path"] == projQ and not watch()["projects"][0]["here"],
       f"--quick: in the Trash it is missing, not moved ({d['applied_moves']}, {d['missing']})")
    shutil.move(str(trash / "projQ"), projQ)
    d = J("reconcile", "--quick", "--apply")
    ck(not d["applied_moves"] and not d["missing"] and watch()["projects"][0]["here"],
       "…and back from the Trash it is where it was")
    # a plain reconcile asks by id too
    projR = str(out.parent.parent / "outside2" / "projR")
    shutil.move(projQ, projR)
    d = J("reconcile", "--apply")
    ck(d["walked"] is True and len(d["applied_moves"]) == 1
       and reg()["projects"][uid]["real_path"] == projR,
       "a reconcile with its walk finds it by id as well")
    projQ = projR
else:
    print("  (no question by id on this system: the watcher's --renamed is what finds a move)")
    d = J("reconcile", "--quick", "--apply", "--renamed", projA, projQ)
    ck(len(d["applied_moves"]) == 1 and reg()["projects"][uid]["real_path"] == projQ,
       f"--quick --renamed: the folder the watcher saw renamed ({d['applied_moves']})")

# what a watcher saw renamed, with no id to ask by: the folder, then a parent
noid = {"AHT_NO_FOLDER_IDS": "1"}
back = roots / "back" / "projS"
back.parent.mkdir()
shutil.move(projQ, str(back))
projS = os.path.realpath(str(back))
d = J("reconcile", "--quick", "--apply", extra_env=noid)
ck(not d["applied_moves"] and [m["uuid"] for m in d["missing"]] == [uid],
   "--quick with no id and no word from the watcher: it only looks where it was")
d = J("reconcile", "--quick", "--apply", "--renamed", projQ, projS, extra_env=noid)
ck(len(d["applied_moves"]) == 1 and reg()["projects"][uid]["real_path"] == projS,
   f"--quick --renamed OLD NEW: relinked ({d['applied_moves']})")
shutil.move(str(roots / "back"), str(roots / "back2"))
projT = os.path.realpath(str(roots / "back2" / "projS"))
d = J("reconcile", "--quick", "--apply", "--renamed", os.path.realpath(str(roots / "back")),
      os.path.realpath(str(roots / "back2")), extra_env=noid)
ck(len(d["applied_moves"]) == 1 and reg()["projects"][uid]["real_path"] == projT,
   f"--quick --renamed: a parent folder, and the project inside moved along "
   f"({d['applied_moves']})")

# a copy: seen where the watcher says a marker appeared
copy = os.path.realpath(str(roots / "projCopy"))
shutil.copytree(projT, copy)
d = J("reconcile", "--quick", "--notify", extra_env={"AHT_ASSUME": "Duplicate"})
ck(not d["copies"] and not d["applied_copies"], "--quick: a copy nobody pointed at is not looked for")
d = J("reconcile", "--quick", "--notify", "--look", copy, extra_env={"AHT_ASSUME": "Duplicate"})
ck(len(d["applied_copies"]) == 1
   and (Path(copy) / ".aht" / ".project-id").read_text().strip() != uid,
   f"--quick --look: the copy gets an id of its own ({d['applied_copies']})")
ck(sorted(p["path"] for p in watch()["projects"]) == sorted([projT, copy]),
   "…and the watchers' list has both")

# a new git repository, where the watcher says a .git appeared
gitty = os.path.realpath(str(roots / "gitty"))
os.makedirs(os.path.join(gitty, ".git"))
inner = os.path.join(gitty, "vendor", "lib")
os.makedirs(os.path.join(inner, ".git"))
hidden = os.path.realpath(str(roots / ".cache" / "repo"))
os.makedirs(os.path.join(hidden, ".git"))
J("reconcile", "--quick", "--notify", "--look", gitty, inner, hidden)
repos = reg().get("git_repos") or []
ck(gitty in repos and inner not in repos and hidden not in repos and gitty in watch()["git"],
   f"--quick --look: a new git repository is noted; one inside it and a hidden one are not, "
   f"as in the walk ({[os.path.basename(r) for r in repos]})")
shutil.rmtree(os.path.join(gitty, ".git"))
J("reconcile", "--quick", "--notify", "--look", gitty)
ck(gitty not in (reg().get("git_repos") or []), "…and one whose .git went is dropped")

# what the Windows and the Linux watcher decide by (the Mac's does it in Swift)
os.environ.update({k: env[k] for k in env if k.startswith("AHT_")})
j = core.WatchJudge()
ck(j.args() is None, "the watchers' judge: nothing changed, nothing to run")
for d in ("build", "node_modules"):
    j.added(os.path.join(projT, d))
j.removed(os.path.join(projT, "old"))
ck(j.args() is None, "…folders made and removed inside a project start nothing")
copy2 = os.path.realpath(str(roots / "projCopy2"))
shutil.copytree(projT, copy2)
j.added(copy2)
j.added(os.path.join(copy2, ".aht"))
j.added(os.path.join(projT, ".aht"))            # a project it has: aht's own folder there
ck(j.args() == ["--quick", "--look", copy2],
   "…a marker's folder in a folder it does not have: a look there")
shutil.rmtree(copy2)
newgit = os.path.realpath(str(roots / "newgit"))
os.makedirs(os.path.join(newgit, ".git"))
j.added(os.path.join(newgit, ".git"))
ck(j.args() == ["--quick", "--look", newgit], "…a .git in a folder not known as a repository")
shutil.rmtree(newgit)
projU = os.path.realpath(str(roots / "projU"))
os.rename(projT, projU)
j.renamed(projT, projU)
a = j.args()
ck(a == ["--quick", "--renamed", projT, projU], f"…a project renamed: what was renamed ({a})")
J("reconcile", "--apply", *a)
j.ran()
ck(reg()["projects"][uid]["real_path"] == projU and j.args() is None,
   "…and once aht looked, nothing is left to run")
other = os.path.realpath(str(roots / "plain"))
os.makedirs(other)
j.renamed(other, other + "2")
os.rename(other, other + "2")
ck(j.args() is None, "…a folder renamed that holds no project starts nothing")
os.rename(projU, projT)                         # moved with no word of it (across folders)
a = j.args()
ck(a == ["--quick"], f"…a project that is not where it was, with no word of it: a look ({a})")
J("reconcile", "--apply", "--quick", "--renamed", projU, projT)
j.ran()
j.lost()
ck(j.args() == [], "…changes that went unseen: a reconcile with its walk")
if not has_ids:
    j2 = core.WatchJudge(scan_new=True)
    grp = os.path.realpath(str(roots / "pasted"))
    shutil.copytree(projT, os.path.join(grp, "inner"))
    j2.added(grp)                               # its inside was written before it was watched
    ck(j2.args() == ["--quick", "--look", os.path.join(grp, "inner")],
       "…Linux: a folder that appeared is looked through for markers")
    shutil.rmtree(grp)

# the walk, once a day
r0 = reg()
stray = os.path.realpath(str(roots / "projStray"))
shutil.copytree(projT, stray)
d = J("reconcile", "--quick", "--notify", extra_env={"AHT_ASSUME": "Skip"})
ck(d["walked"] is False and not d["copies"], "--quick within the day: no walk")
r0 = reg()
r0["full_scan_at"] = time.time() - core.FULL_SCAN_INTERVAL - 60
(home / "registry.json").write_text(json.dumps(r0))
d = J("reconcile", "--quick", "--notify", extra_env={"AHT_ASSUME": "Skip"})
ck(d["walked"] is True and [c["copy_path"] for c in d["copies"]] == [stray]
   and time.time() - reg()["full_scan_at"] < 60,
   f"--quick after a day: it walks once, and finds what nobody pointed at ({d['copies']})")

done()
