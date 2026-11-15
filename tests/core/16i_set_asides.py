#!/usr/bin/env python3
"""[16i] set-aside copies that a newer file still holds whole: a copy goes
when the file now in place (or a later set-aside copy of it) begins with
every byte of it, which is a conversation that only grew; a rewritten file
and a removed one stay.  After each sync on the other machine (the stand-in
"box" of the handover suite), and all at once with `aht remote tidy`, on
that machine and on this one."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)
import handover_kit as kit

print("\n[16i] set-aside copies a newer file still holds whole")
base = Path(os.path.realpath(sb)) / "asides"
live_h, live_p = base.parent / "live-history", base.parent / "live-project"


def put(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


put(base / "20261101-100000" / "history" / "s.jsonl", "l1\n")
put(base / "20261102-100000" / "history" / "s.jsonl", "l1\nl2\n")
put(live_h / "s.jsonl", "l1\nl2\nl3\n")
put(base / "20261101-100000" / "history" / "r.jsonl", "old start\n")     # rewritten since
put(live_h / "r.jsonl", "new start\nmore\n")
put(base / "20261102-100000" / "project" / "notes.md", "a\n")
put(live_p / "notes.md", "a\nb\n")
put(base / "20261102-100000" / "project" / "gone.txt", "removed there\n")   # nothing newer
live = {"history": [str(live_h)], "project": [str(live_p)]}
dry = core.drop_contained_asides(base, live, apply=False)
ck(dry["files"] == 3 and dry["kept_bytes"] == len("old start\n") + len("removed there\n")
   and (base / "20261101-100000" / "history" / "s.jsonl").exists(),
   f"a dry run counts the copies a newer file begins with, and removes nothing ({dry})")
one = core.drop_contained_asides(base, live, only="20261102-100000", apply=False)
ck(one["files"] == 2, f"one transfer's folder alone ({one})")
got = core.drop_contained_asides(base, live)
left = sorted(p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file())
ck(got["files"] == 3 and left == ["20261101-100000/history/r.jsonl",
                                  "20261102-100000/project/gone.txt"]
   and not (base / "20261102-100000" / "history").exists(),
   f"the grown ones go; a rewritten one and a removed one stay; empty folders go ({left})")
put(base / "20261103-100000" / "history" / "t.jsonl", "t1\n")
put(base / "20261104-100000" / "history" / "t.jsonl", "t1\nt2\n")
core.drop_contained_asides(base, {})
ck(not (base / "20261103-100000").exists()
   and (base / "20261104-100000" / "history" / "t.jsonl").exists(),
   "a later set-aside copy that begins with it is enough; the later one stays")
put(base / "20261105-100000" / "project" / "readme.md", "r1\n")
put(live_p / "README.md", "r1\n")
core.drop_contained_asides(base, live)
ck((base / "20261105-100000" / "project" / "readme.md").exists(),
   "a name whose case changed stays set aside, also on a disk that ignores case")

# rsync where there is rsync 3 (its --backup set every grown conversation aside)
if kit.start("rsync") or kit.start("aht"):
    h = kit.setup()
    try:
        kit.configure(h)
        proj = os.path.realpath(str(roots / "Grown Talk"))
        os.makedirs(proj)
        Path(proj, "notes.md").write_text("n1\n")
        h.hrun("tag", proj, "--apply")
        uid = Path(proj, ".aht", ".project-id").read_text().strip()
        st = tools / "claude" / enc(proj)
        st.mkdir(parents=True, exist_ok=True)

        def line(i):
            return json.dumps({"type": "user", "sessionId": "s1", "cwd": proj,
                               "timestamp": f"2026-11-15T10:{i:02d}:00Z",
                               "message": {"role": "user", "content": f"step {i}"}}) + "\n"
        (st / "s1.jsonl").write_text(line(0))
        r1 = h.J(h.hrun("mirror", proj, "--on", "--run", "--json"))
        time.sleep(1.1)                         # the next sync's folder has a name of its own
        with open(st / "s1.jsonl", "a") as fh:
            fh.write(line(1))
        Path(proj, "notes.md").write_text("rewritten\n")
        h.hrun("mirror", "--run", "--json")
        rep = h.bhome / ".aht" / "remote" / "replaced" / uid
        kept = sorted(p.relative_to(rep).as_posix().split("/", 1)[1]
                      for p in rep.rglob("*") if p.is_file()) if rep.is_dir() else []
        far = h.bhome / ".claude" / "projects" / core._key_claude(str(h.box) + proj) / "s1.jsonl"
        ck(r1.get("mirrored", [{}])[0].get("status") == "synced" and far.is_file()
           and far.read_text().count("\n") == 2 and kept == ["project/notes.md"],
           f"a sync: the conversation that only grew is not kept aside there; the rewritten "
           f"file is ({kept})")

        # what an earlier aht left there: the conversation before it grew
        old = rep / "20200101-000000" / "history" / "s1.jsonl"
        put(old, far.read_text().splitlines(True)[0])
        only_there = rep / "20200101-000000" / "history" / "s9.jsonl"
        put(only_there, "only here\n")
        d = h.J(h.hrun("remote", "tidy", "box", "--json"))
        ck(d.get("ok") and d.get("files") == 1 and not d.get("applied") and old.exists(),
           f"remote tidy box: a dry run finds what a newer file there holds ({d})")
        d = h.J(h.hrun("remote", "tidy", "box", "--apply", "--json"))
        ck(d.get("files") == 1 and not old.exists() and only_there.exists()
           and any(rep.rglob("notes.md")),
           f"remote tidy box --apply: it goes there; the others stay ({d})")
        r = h.hrun("remote", "tidy", "box")
        ck(r.returncode == 0 and "no set-aside copy a newer file still holds" in r.stdout,
           f"…and says so in the terminal afterwards ({r.stdout.strip()})")

        # this machine: what a return set aside here
        lrep = sb / ".aht" / "handover" / uid / "replaced" / "20200101-000000" / "history"
        put(lrep / "s1.jsonl", line(0))
        d = h.J(h.hrun("remote", "tidy", "--json"))
        ck(d.get("files") == 1 and (lrep / "s1.jsonl").exists(),
           f"remote tidy: this computer's own set-aside copies, a dry run ({d})")
        h.hrun("remote", "tidy", "--apply", "--json")
        ck(not (lrep / "s1.jsonl").exists(), "remote tidy --apply: they go here too")
    finally:
        kit.stop_stand_ins(h.bhome)
done()
