#!/usr/bin/env python3
"""[16b] nothing lost on the way: the plumbing under handover (any system)."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)

print("\n[16b] nothing lost on the way: the plumbing under handover (any system)")
ck(all(core._is_abs(p) for p in ("/x", "C:\\x", "C:/x", "\\\\server\\x", "c:\\"))
   and not any(core._is_abs(p) for p in ("x", "./x", "C:x", "", None)),
   "absolute paths of all three systems are told apart")
ck(core._inside("C:\\Users\\Me\\x\\a.py", "c:/users/me/x")
   and not core._inside("C:\\Users\\Me\\xy", "C:\\Users\\Me\\x")
   and core._inside("/a/b", "/a") and not core._inside("/A/b", "/a"),
   "inside a folder: either separator and any case on a drive, exact elsewhere")

# manifests: "/" keys, every folder (an empty one too), the executable bit
mt = sb / "manifest-tree"
(mt / ".git" / "refs" / "heads").mkdir(parents=True)
(mt / "bin").mkdir()
(mt / "bin" / "run.sh").write_text("#!/bin/sh\n")
os.chmod(mt / "bin" / "run.sh", 0o755)
(mt / "a.txt").write_text("a")
(mt / unicodedata.normalize("NFC", "é.txt")).write_text("one")
(mt / unicodedata.normalize("NFD", "é.txt")).write_text("two")
# a disk that keeps both Unicode forms apart (Linux) holds two names here
both = len([n for n in os.listdir(mt)
            if unicodedata.normalize("NFC", n) == unicodedata.normalize("NFC", "é.txt")]) == 2
m = core.tree_manifest(str(mt), [])
ck(".git/refs/heads" in m["dirs"] and "bin/run.sh" in m["files"]
   and m["modes"].get("bin/run.sh") == 0o755 and "a.txt" not in m["modes"]
   and (list(m["twins"]) == [unicodedata.normalize("NFC", "é.txt")] if both
        else m["twins"] == {}),
   f"manifest: folders (empty ones too), executable marks, twin names ({m['dirs']}, "
   f"{m['modes']}, {m['twins']})")

# set-asides: the newest 5, and everything younger than 30 days (faked times)
def aside_names(base):
    return sorted(p.name for p in base.iterdir())
def stamp(days):
    return time.strftime("%Y%m%d-%H%M%S", time.localtime(time.time() - days * 86400))
sa = sb / "aside-a"
for days in (31, 32, 33, 34, 35, 36, 37, 1, 2):
    (sa / stamp(days) / "project").mkdir(parents=True)
    (sa / stamp(days) / "project" / "x.txt").write_text(str(days))
n = core.prune_set_asides(sa)
ck(n == 4 and aside_names(sa) == sorted(stamp(d) for d in (1, 2, 31, 32, 33)),
   f"set-asides: the newest 5 stay ({aside_names(sa)})")
sb2 = sb / "aside-b"
for days in (40, 41, 42) + tuple(range(1, 9)):
    (sb2 / stamp(days)).mkdir(parents=True)
core.prune_set_asides(sb2)
ck(aside_names(sb2) == sorted(stamp(d) for d in range(1, 9)),
   "set-asides: everything younger than 30 days stays, however many")

# one prune for a project's .aht/handover: a handover's summary no longer
# deletes a switch's, and the other way round
rh = sb / "relays" / ".aht" / "handover"
rh.mkdir(parents=True)
for i in range(10):
    (rh / f"202601{10 + i}-1200-to-box.md").write_text("handover")
    (rh / f"202601{10 + i}-1300-to-codex.md").write_text("switch")
(rh / "relay-20250101-000000-aaaa.json").write_text("{}")         # open: it stays
for x in (".json", ".md", ".closed"):
    (rh / f"relay-20250102-000000-bbbb{x}").write_text("{}")      # closed and old
core.prune_relays(rh)
left = sorted(p.name for p in rh.iterdir())
ck(len([n for n in left if n.endswith(".md") and "-to-" in n]) == 12
   and any(n.endswith("-to-box.md") for n in left)
   and any(n.endswith("-to-codex.md") for n in left)
   and "relay-20250101-000000-aaaa.json" in left
   and not any("bbbb" in n for n in left),
   f"prune_relays: open relays stay, the newest 12 closed ones of either kind ({len(left)})")

# a take-back on a disk that ignores case: two names of one case group never
# land on one file; the one that would is kept next to it (any system:
# AHT_CASELESS makes a Linux disk act so)
class CaseRem:
    def __init__(self, files):
        self.files = files
    def spec(self, p):
        return p
    def fetch(self, src, dst, entries=None, aside=None, **kw):
        for n in entries.values():
            t = Path(dst) / n
            if aside and t.exists():
                core._set_aside(t, Path(aside), n)
            t.parent.mkdir(parents=True, exist_ok=True)
            t.write_bytes(self.files[n])
        return {"ok": True}
ct = sb / "case-tree"
ct.mkdir()
(ct / "Notes.txt").write_text("ours\n")
os.environ["AHT_CASELESS"] = "1"
try:
    done = core._pull_tree(CaseRem({"notes.txt": b"theirs\n", "Two.md": b"2\n",
                                    "two.md": b"two\n"}),
                           {"take": [], "new": ["notes.txt", "Two.md", "two.md"],
                            "delete": [], "conflict": [], "kept": []},
                           "/far", str(ct), {}, sb / "case-aside" / "x", "box", False, [],
                           False, here_keys={"Notes.txt": [5, 0]})
finally:
    del os.environ["AHT_CASELESS"]
day = time.strftime("%Y-%m-%d")
got = sorted(os.listdir(ct))
ck((ct / "Notes.txt").read_text() == "ours\n"
   and (ct / f"notes (from box {day}).txt").read_text() == "theirs\n"
   and (ct / "Two.md").read_text() == "2\n"
   and (ct / f"two (from box {day}).md").read_text() == "two\n"
   and sorted(c["file"] for c in done["conflicts"]) == ["notes.txt", "two.md"],
   f"case groups: a clash is kept next to the file that stays ({got})")

# how aht runs itself in the background (the mirror, the offsite copy, the
# night shift): in the Windows exes, aht.exe, also from the tray's own exe
exes = sb / "exes"
exes.mkdir()
(exes / "aht-tray.exe").write_text("")
was = (getattr(sys, "frozen", None), sys.executable)
try:
    sys.frozen, sys.executable = True, str(exes / "aht-tray.exe")
    lone = core._aht_argv()
    (exes / "aht.exe").write_text("")
    tray, cli = core._aht_argv(), None
    sys.executable = str(exes / "aht.exe")
    cli = core._aht_argv()
finally:
    if was[0] is None:
        del sys.frozen
    else:
        sys.frozen = was[0]
    sys.executable = was[1]
# as aht runs itself for a user: without the tests' own launcher
_launch = os.environ.pop("AHT_TEST_LAUNCHER", None)
here_argv = core._aht_argv()
if _launch:
    os.environ["AHT_TEST_LAUNCHER"] = _launch
ck(lone == [str(exes / "aht-tray.exe")] and tray == [str(exes / "aht.exe")]
   and cli == [str(exes / "aht.exe")] and here_argv[1:] == [str(Path(CLI).resolve())],
   f"aht runs itself: aht.exe from the tray's exe, this file from a checkout "
   f"({lone}, {tray}, {cli}, {here_argv})")

# this install's id: made once, kept out of the config; the core's own id
ie = iso_env("machine-id")
r1 = iso_run(ie, "_core", "--id").stdout.strip()
ck(r1 == hashlib.sha256(Path(CLI).read_bytes()).hexdigest()[:12],
   f"_core --id: the core's checksum names its copy elsewhere ({r1})")
mprobe = "import aht; print(aht.machine_id(), aht.machine_id(create=True), aht.machine_id(create=True))"
out = subprocess.run([PY, "-c", mprobe], env=dict(ie, PYTHONPATH=str(HERE.parent)),
                     capture_output=True, text=True).stdout.split()
mj = json.loads((Path(ie["AHT_HOME"]) / "machine.json").read_text())
ctext = read_text_or_none(Path(ie["AHT_HOME"]) / "config.json") or ""
ck(out[:1] == ["None"] and len(out) == 3 and out[1] == out[2] == mj["id"]
   and len(mj["id"]) == 12 and {"id", "name", "created"} <= set(mj) and mj["id"] not in ctext,
   f"machine id: made only when asked, then always the same, not in the config ({out})")

# Keep in sync sends what the registry says when it sends, not what it said
# when the run began: a project released meanwhile (its sync paused) or
# handed over meanwhile is not sent (stand-ins for the machine and the
# sending, so any system)
re_ = iso_env("mirror-race")
race = """
import json, os, sys
import aht
S = sys.argv[1]
aht.save_config(dict(aht.load_config(), remotes={"box": {"root": os.path.join(S, "box")}}))
reg, uids = aht.load_registry(), {}
for n in ("A-first", "X-released", "Y-handed"):
    p = os.path.realpath(os.path.join(S, n))
    os.makedirs(p, exist_ok=True)
    uids[n] = aht.new_uuid()
    aht._register(reg, uids[n], p)
    reg["projects"][uids[n]]["mirror"] = {"enabled": True, "remote": "box"}
aht.save_registry(reg)
sent = []
def connect(self, path=None, **kw):
    self.info = {"sessions": [], "processes": [], "path_writable": True,
                 "claude_home": os.path.join(S, "box", "home", ".claude")}
    return self.info
def push(rem, uid, entry, **kw):
    sent.append(os.path.basename(entry["real_path"]))
    if uid == uids["A-first"]:          # while A is sent, X is released, Y handed over
        with aht.Lock():
            r = aht.load_registry()
            r["projects"][uids["X-released"]]["mirror"]["paused"] = {
                "reason": "released", "at": aht._now(), "remote": "box"}
            r["projects"][uids["Y-handed"]]["away"] = {"remote": "box", "since": aht._now()}
            aht.save_registry(r)
    return {"project": {}, "history": {}, "extras": []}
aht.Remote.connect = connect
aht.push_project = push
rows = aht.mirror_pass()
x = aht.load_registry()["projects"][uids["X-released"]]["mirror"]
print(json.dumps({"sent": sent, "rows": {os.path.basename(r["project"]): r["status"]
                                         for r in rows},
                  "paused": bool(x.get("paused")), "tried": "tried_at" in x}))
"""
r = subprocess.run([PY, "-c", race, str(Path(re_["HOME"]).parent)],
                   env=dict(re_, PYTHONPATH=str(HERE.parent)), capture_output=True, text=True)
try:
    got = json.loads(r.stdout)
except ValueError:
    got = {"error": r.stdout[-300:] + r.stderr[-300:]}
ck(got.get("sent") == ["A-first"]
   and got.get("rows") == {"A-first": "synced", "X-released": "paused", "Y-handed": "skipped"}
   and got.get("paused") is True and got.get("tried") is False,
   f"Keep in sync: a project released or handed over during a run is not sent ({got})")

# ([16b] names a result `done`: the unit's own done() again)
from common import done  # noqa: E402

done()
