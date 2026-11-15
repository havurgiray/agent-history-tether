#!/usr/bin/env python3
"""[6b] the backup store: a picture inside a conversation kept once, a
conversation that only grew adding only what is new, a rewritten file, every
file read back byte for byte, a damaged piece found, the tiers (all from two
days, then one a day, a week, a month), the clean-up of unused pieces, old
zips moved in (each file compared before the zip goes), and the sessions a
backup holds."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)
import base64
import zipfile

print("\n[6b] the backup store")
proj = roots / "Store Check"
proj.mkdir()
r = run("tag", str(proj), "--apply")
uid = (proj / ".aht" / ".project-id").read_text().strip()
store = tools / "claude" / enc(os.path.realpath(str(proj)))
store.mkdir(parents=True, exist_ok=True)
pic = os.urandom(30000)                         # a "picture": nothing to compress
b64 = base64.b64encode(pic).decode()
line = lambda **k: json.dumps(k, separators=(",", ":")) + "\n"   # noqa: E731
conv = store / "s1.jsonl"
conv.write_text(
    line(type="custom-title", customTitle="Pictures", sessionId="s1")
    + line(type="user", timestamp="2026-11-01T10:00:00Z",
           message={"role": "user", "content": [{"type": "image", "source": {
               "type": "base64", "media_type": "image/jpeg", "data": b64}}]})
    + line(type="user", timestamp="2026-11-01T10:01:00Z", toolUseResult={"file": {"base64": b64}})
    + "".join(line(type="assistant", timestamp="2026-11-01T10:02:00Z",
                   message={"role": "assistant", "content": f"thinking about it, step {i}"})
              for i in range(300)))
(store / "notes.txt").write_text("a plain file\n" * 100)
bk = sb / ".aht" / "backups"
d1 = JS("backup", "--project", str(proj), "--json")
objs = lambda: sorted(p for p in (bk / "objects").rglob("*") if p.is_file())   # noqa: E731
first = objs()
pics = [p for p in first if p.stat().st_size == len(pic)]
snap1 = sorted((bk / uid).glob("*.snap"))
ck(d1.get("counts", {}).get("backed-up") == 1 and len(snap1) == 1 and len(pics) == 1,
   f"a picture held twice in a conversation is kept once, as the picture ({len(pics)}, {d1.get('counts')})")
meta1 = json.loads(snap1[0].with_suffix(".meta.json").read_text())
ck(meta1.get("format") == "store" and meta1.get("sessions") == 1
   and meta1["added_bytes"] < len(pic) + conv.stat().st_size // 3,
   f"the snapshot takes about the picture and the packed text ({meta1.get('added_bytes')} of "
   f"{conv.stat().st_size + 1300} bytes)")

# grows: only what is new; the same picture again adds nothing
time.sleep(1.1)
with open(conv, "a") as fh:
    fh.write(line(type="user", timestamp="2026-11-02T09:00:00Z", toolUseResult={"file": {"base64": b64}}))
    fh.write(line(type="assistant", timestamp="2026-11-02T09:01:00Z",
                  message={"role": "assistant", "content": "one more answer"}))
d2 = JS("backup", "--project", str(proj), "--json")
snaps = sorted((bk / uid).glob("*.snap"))
meta2 = json.loads(snaps[-1].with_suffix(".meta.json").read_text())
ck(len(snaps) == 2 and len([p for p in objs() if p.stat().st_size == len(pic)]) == 1
   and meta2["added_bytes"] < 2000,
   f"a conversation that grew adds only what is new; the picture again adds nothing "
   f"({meta2.get('added_bytes')} bytes)")

# everything reads back exactly: a restore into an empty store
want = {f.name: f.read_bytes() for f in store.iterdir() if f.is_file()}
shutil.rmtree(store)
d3 = JS("restore", str(proj), "--apply", "--json")
got = {f.name: f.read_bytes() for f in store.iterdir() if f.is_file()} if store.is_dir() else {}
ck(d3.get("status") == "restored" and got == want,
   f"restored byte for byte ({sorted(got)} vs {sorted(want)})")
v = JS("backup", "--verify", "--json")
ck(v.get("snapshots", 0) >= 2 and not v.get("problems"), f"verify: every file reads back ({v})")

# a rewritten file (not grown) is kept whole again, and still reads back
time.sleep(1.1)
conv.write_text(line(type="user", timestamp="2026-11-03T08:00:00Z",
                     message={"role": "user", "content": "started over"}))
JS("backup", "--project", str(proj), "--json")
snaps = sorted((bk / uid).glob("*.snap"))
data = run("backup", "--show", str(proj), "--json")
rows = json.loads(data.stdout).get("sessions", [])
ck(len(snaps) == 3 and rows and rows[0]["session"] == "s1" and rows[0]["title"] is None
   and rows[0]["updated"],
   f"a rewritten file is kept whole again; --show lists the sessions of a backup ({rows})")
old = json.loads(run("backup", "--show", str(proj), "--stamp", snaps[0].stem, "--json").stdout)
ck([r["title"] for r in old.get("sessions", [])] == ["Pictures"],
   f"--show --stamp: an older backup's sessions, with their titles ({old.get('sessions')})")

# a damaged piece is found, not handed back
pick = pics[0]
was = pick.read_bytes()
pick.write_bytes(b"x" + was[1:])
v = JS("backup", "--verify", "--json")
ck(v.get("problems") and "damaged" in " ".join(v["problems"]),
   f"verify: a damaged piece is reported ({v.get('problems')})")
pick.write_bytes(was)

# the tiers: all from two days, then one a day, a week, a month; the newest always
sys.path.insert(0, str(HERE.parent))
import aht as _core
now = time.time()
fake = [{"stamp": f"s{i}", "t": now - age} for i, age in enumerate(
    [400 * 86400, 200 * 86400, 199.9 * 86400, 60 * 86400, 59.9 * 86400, 10 * 86400,
     9.95 * 86400, 3 * 86400, 1.5 * 86400, 3600, 60])]
gone = [s["stamp"] for s in _core.thin_snapshots(fake, now)]
ck(gone == ["s0", "s1", "s3", "s5"],
   f"tiers: older than a year goes, one per month/week/day stays ({gone})")
ck(_core.thin_snapshots([{"stamp": "old", "t": now - 900 * 86400}], now) == [],
   "tiers: the newest backup always stays, however old")

# unused pieces go (not before an hour unless asked), the used ones stay
snaps[0].unlink()
snaps[0].with_suffix(".meta.json").unlink()
g0 = _core.store_gc(bk, grace=0)
ck(g0.get("removed") == 0 and pick.exists(),
   f"clean-up: a piece a later snapshot still uses stays ({g0})")
snaps[1].unlink()
snaps[1].with_suffix(".meta.json").unlink()
g = _core.store_gc(bk, grace=0)
ck(g.get("removed", 0) >= 2 and not pick.exists(),
   f"clean-up: once no snapshot uses them, the picture and the old text go ({g})")
v = JS("backup", "--verify", "--json")
ck(not v.get("problems"), f"…and the rest still reads back ({v})")

# an older backup as a zip moves in; the zip goes only after every file matched
zdir = bk / uid
zp = zdir / "20200101-000000.zip"
with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as zf:
    zf.writestr("claude/z1.jsonl", line(type="custom-title", customTitle="From a zip")
                + line(type="user", toolUseResult={"file": {"base64": b64}}))
zp.with_suffix(".meta.json").write_text(json.dumps({"uuid": uid, "stamp": zp.stem,
                                                    "real_path": str(proj), "sig": "x"}))
dry = JS("backup", "--migrate", "--json")
ck(dry.get("zips") == 1 and zp.exists() and not dry.get("applied"),
   f"--migrate: a dry run counts the zips ({dry})")
# not while an automatic pass runs (it may thin the zips out, and its new
# pieces are in no list yet)
import fcntl
(sb / ".aht" / "run").mkdir(parents=True, exist_ok=True)
held = open(sb / ".aht" / "run" / "backup-auto.lock", "a")
fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
busy = run("backup", "--migrate", "--apply", "--json")
held.close()
ck(busy.returncode == 1 and "a backup runs right now" in busy.stderr and zp.exists(),
   f"--migrate --apply: not while an automatic backup runs ({busy.stderr[-200:]})")
m = JS("backup", "--migrate", "--apply", "--json")
ck(m.get("migrated") == 1 and not zp.exists() and zp.with_suffix(".snap").exists()
   and not m.get("problems"),
   f"--migrate --apply: the zip is a snapshot of the store now ({m})")
z1 = json.loads(run("backup", "--show", str(proj), "--stamp", "20200101-000000",
                    "--json").stdout).get("sessions", [])
ck([r["title"] for r in z1] == ["From a zip"], f"…and reads back as it was ({z1})")

# a new project from a backup: its conversations, Claude Code's under new
# session ids and in the new folder; with --with-files, the files from then
ck_snaps = sorted((bk / uid).glob("*.snap"))
pick = next(p_.stem for p_ in ck_snaps if p_.stem != "20200101-000000")
fresh = roots / "From Backup"
dry = JS("restore", str(proj), "--stamp", "20200101-000000", "--into", str(fresh), "--json")
ck(not dry.get("applied") and dry.get("sessions") == 1 and not fresh.exists(),
   f"restore --into: a dry run says what the new project gets ({dry})")
made = JS("restore", str(proj), "--stamp", "20200101-000000", "--into", str(fresh), "--apply",
          "--json")
nid = made.get("session_ids", {}).get("z1")
nstore = tools / "claude" / enc(os.path.realpath(str(fresh)))
copied = (nstore / f"{nid}.jsonl").read_bytes() if nid and (nstore / f"{nid}.jsonl").is_file() else b""
ck(made.get("applied") and nid and nid != "z1" and b'"From a zip"' in copied
   and (fresh / ".aht" / ".project-id").read_text().strip() == made.get("new_uuid")
   and made["new_uuid"] != uid,
   f"restore --into --apply: a new project with its own id; the session under a new id "
   f"({made.get('session_ids')}, {sorted(p_.name for p_ in nstore.iterdir()) if nstore.is_dir() else None})")
r = run("restore", str(proj), "--stamp", pick, "--into", str(roots / "With Files"),
        "--with-files")
ck(r.returncode == 3 and "no copy of the project's files" in r.stdout,
   f"restore --into --with-files: without a copy of the files from then, it says so "
   f"({r.stdout[-300:]})")
cpd = sb / ".aht" / "checkpoints" / uid / "20200101-000000-aaaaaaaa"
(cpd / "files").mkdir(parents=True)
(cpd / "files" / "notes.md").write_text("then\n")
(cpd / "files" / ".aht").mkdir()
(cpd / "files" / ".aht" / ".project-id").write_text(uid)
(cpd / "meta.json").write_text(json.dumps({"ok": True, "at": time.mktime(time.strptime(
    "20200101-000000", "%Y%m%d-%H%M%S")) - 3600,
                                           "files": 1, "session": "z1"}))
wf = roots / "With Files"
made2 = JS("restore", str(proj), "--stamp", "20200101-000000", "--into", str(wf),
           "--with-files", "--apply", "--json")
ck(made2.get("applied") and (wf / "notes.md").read_text() == "then\n"
   and (wf / ".aht" / ".project-id").read_text().strip() != uid,
   f"restore --into --with-files --apply: the files from then, under a project id of its own "
   f"({made2.get('files_from')})")

# a machine that updated aht: its automatic pass moves the zips in by itself
zq = zdir / "20200102-000000.zip"
with zipfile.ZipFile(zq, "w", zipfile.ZIP_DEFLATED) as zf:
    zf.writestr("claude/z2.jsonl", line(type="custom-title", customTitle="Moved by itself"))
zq.with_suffix(".meta.json").write_text(json.dumps({"uuid": uid, "stamp": zq.stem,
                                                    "real_path": str(proj), "sig": "y"}))
(bk / ".last-run").unlink(missing_ok=True)
au = JS("backup", "--auto", "--json", extra_env={"AHT_NO_BACKUP": ""})
ck(au.get("ran") and au.get("zips_moved") == 1 and not zq.exists()
   and zq.with_suffix(".snap").exists(),
   f"backup --auto: a zip left by an earlier aht moves into the store by itself "
   f"({ {k: v for k, v in au.items() if k != 'results'} })")
done()
