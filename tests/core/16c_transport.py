#!/usr/bin/env python3
"""[16c] aht's own copy: files move without rsync, with the same safety.

The Windows CI job runs only this unit (core_test.py --transport), on
Windows too: a folder stands in for the other machine (test mode)."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)

def transport_suite():
    """[16c] aht's own copy: files move without rsync, with the same safety.
    A folder stands in for the other machine (test mode: aht's _agent runs
    here, no sh), so this runs on Windows too; where /bin/sh runs, a
    stand-in ssh also cuts a copy off halfway, and lets one go quiet."""
    import io, time, unicodedata
    if os.name == "nt":
        sys.path.insert(0, str(HERE.parent / "windows" / "src"))
        import win_fcntl
        sys.modules.setdefault("fcntl", win_fcntl)
    sys.path.insert(0, str(HERE.parent))
    os.environ["AHT_HOME"] = str(sb / ".aht")
    import aht as core
    print("\n[16c] aht's own copy: files move without rsync, with the same safety")
    X = Path(os.path.realpath(sb)) / "xfer"
    here, far = X / "here", X / "far"
    rem = core.Remote("box", {"root": str(X / "box")})
    was_mode = os.environ.get("AHT_TRANSFER")
    os.environ["AHT_TRANSFER"] = "aht"
    links = True
    def digest(p):
        return hashlib.sha256(Path(p).read_bytes()).hexdigest()
    def same_tree(a, b):
        ma, mb = core.tree_manifest(str(a), []), core.tree_manifest(str(b), [])
        return (ma["files"] == mb["files"] and ma["dirs"] == mb["dirs"]
                and ma["modes"] == mb["modes"]
                and all(digest(Path(a) / (ma["raw"].get(k) or k))
                        == digest(Path(b) / (mb["raw"].get(k) or k))
                        for k, v in ma["files"].items() if v[0] != "l"))
    def files_in(d):
        d = Path(d)
        return sorted(p.relative_to(d).as_posix() for p in d.rglob("*")
                      if p.is_file()) if d.is_dir() else []
    try:
        info = rem.connect()
        ck({"pack", "unpack"} <= set(info.get("ops") or []),
           "probe: the far end names pack and unpack among its ops")
        # auto: rsync when this side has rsync 3, the other has rsync, and
        # neither is Windows
        del os.environ["AHT_TRANSFER"]
        try:
            picks = []
            for system, there in (("Linux", "/usr/bin/rsync"), ("Linux", None),
                                  ("Windows", "/usr/bin/rsync")):
                rem.info = dict(info, system=system, tools={"rsync": there})
                picks.append(rem.transfer())
            os.environ["AHT_TRANSFER"] = "rsync"
            forced = rem.transfer()
        finally:
            os.environ["AHT_TRANSFER"] = "aht"
            rem.info = info
        rs3 = bool(core.find_rsync()) and os.name != "nt"
        ck(picks == ["rsync" if rs3 else "aht", "aht", "aht"] and forced == "rsync",
           f"handover_transfer auto: rsync only with rsync 3 here, rsync there and no "
           f"Windows; a setting wins ({picks})")

        # a tree with what a project holds: an empty git folder, an executable,
        # a link, a name in a Mac's form, a file of several pieces, an empty file
        (here / ".git" / "refs" / "heads").mkdir(parents=True)
        (here / "sub" / "deep").mkdir(parents=True)
        (here / "a.txt").write_text("a1\n")
        (here / "sub" / "b.txt").write_text("b1\n")
        (here / "sub" / "deep" / "c.txt").write_text("c1\n")
        (here / "big.bin").write_bytes(os.urandom(2_500_000))
        (here / "empty").write_bytes(b"")
        (here / "run.sh").write_text("#!/bin/sh\n")
        if os.name != "nt":
            os.chmod(here / "run.sh", 0o755)
        (here / unicodedata.normalize("NFD", "Stürmer.txt")).write_text("umlaut\n")
        try:
            os.symlink("a.txt", here / "link")
        except OSError:
            links = False                   # Windows without the right to make links
        t0 = 280_000
        tail0 = os.urandom(t0)
        (here / "t.jsonl").write_bytes(tail0)
        r = rem.send(str(here), str(far), delete=True, aside=str(X / "aside1"))
        ck(r["ok"] and r["files"] == 8 and r["transfer"] == "aht" and same_tree(here, far)
           and (far / ".git" / "refs" / "heads").is_dir()
           and not (far / core.PARTIAL).exists() and not (X / "aside1").exists(),
           f"send: every file byte for byte, empty .git folders, the executable bit"
           f"{', the link' if links else ''}; nothing left in .aht-partial ({r})")

        # a dry run counts and sends nothing
        (here / "a.txt").write_bytes(b"a2, longer\n")    # bytes: no CRLF on Windows
        r = rem.send(str(here), str(far), delete=True, dry=True)
        ck(r["ok"] and r["files"] == 1 and r["bytes"] == len(b"a2, longer\n")
           and (far / "a.txt").read_text() == "a1\n",
           f"send, dry run: what would go, counted as rsync counts it ({r})")

        # what a send replaces or removes there is set aside there first
        os.unlink(here / "sub" / "b.txt")
        shutil.rmtree(here / "sub" / "deep")
        r = rem.send(str(here), str(far), delete=True, aside=str(X / "aside2"))
        ck(r["ok"] and r["deleted"] == 2 and same_tree(here, far)
           and (X / "aside2" / "a.txt").read_text() == "a1\n"
           and (X / "aside2" / "sub" / "b.txt").read_text() == "b1\n"
           and (X / "aside2" / "sub" / "deep" / "c.txt").read_text() == "c1\n"
           and not (far / "sub" / "deep").exists(),
           f"send: what it replaces or removes there is set aside, emptied folders go "
           f"({files_in(X / 'aside2')})")

        # a transcript that went on here: only its tail travels, nothing is set aside
        more = os.urandom(40_000)
        (here / "t.jsonl").write_bytes(tail0 + more)
        r = rem.send(str(here), str(far), delete=True, aside=str(X / "aside3"))
        ck(r["ok"] and r["files"] == 1 and r["sent"] < 60_000 and same_tree(here, far)
           and not (X / "aside3").exists(),
           f"a tail append: {r['sent']} bytes went for a {t0 + 40_000}-byte file, nothing "
           "set aside")
        # …and back: it went on over there
        more2 = os.urandom(30_000)
        (far / "t.jsonl").write_bytes(tail0 + more + more2)
        r = rem.fetch(str(far), str(here), entries=["t.jsonl"], aside=str(X / "aside4"))
        ck(r["ok"] and r["received"] < 50_000 and same_tree(here, far)
           and not (X / "aside4").exists(),
           f"…and back with fetch: {r['received']} bytes came for the tail")
        # a shorter file there that is not a prefix of ours is replaced whole
        (far / "t.jsonl").write_bytes(os.urandom(t0))
        r = rem.send(str(here), str(far), aside=str(X / "aside5"))
        ck(r["ok"] and r["sent"] > t0 and same_tree(here, far)
           and (X / "aside5" / "t.jsonl").stat().st_size == t0,
           "a shorter file there that is not the beginning of ours: replaced whole, set aside")

        # fetch: what it replaces here is set aside here; a file gone there is
        # skipped, as rsync skips one that vanished (no failure), and named
        (far / "a.txt").write_text("changed there\n")
        r = rem.fetch(str(far), str(here), entries=["a.txt", "gone.txt"],
                      aside=str(X / "aside6"))
        ck(r["ok"] and not r["problems"] and r["skipped"] == ["gone.txt"]
           and (here / "a.txt").read_text() == "changed there\n"
           and (X / "aside6" / "a.txt").read_text() == "a2, longer\n",
           f"fetch: replaced here with the old one set aside; a file gone there is "
           f"skipped, not a failure ({r['skipped']}, {r['error']})")
        # a folder here where a file comes: reported, and the folder (with
        # what changed only here) stays where it is, nothing set aside
        (far / "inway.txt").write_text("a file there\n")
        (here / "inway.txt").mkdir()
        (here / "inway.txt" / "mine.txt").write_text("changed only here\n")
        r = rem.fetch(str(far), str(here), entries=["inway.txt"], aside=str(X / "aside-inway"))
        ck(not r["ok"] and [(p["name"], p["error"]) for p in r["problems"]]
           == [("inway.txt", "a folder is in the way")]
           and (here / "inway.txt" / "mine.txt").read_text() == "changed only here\n"
           and not files_in(X / "aside-inway"),
           f"fetch: a folder here where a file comes is reported and stays, nothing set "
           f"aside ({r['error']}; {files_in(X / 'aside-inway')})")
        if (here / "inway.txt").is_dir():
            shutil.rmtree(here / "inway.txt")
        else:                               # (it was placed: the test failed)
            os.unlink(here / "inway.txt")
        os.unlink(far / "inway.txt")
        r = rem.fetch(str(far), str(here), entries=["a.txt"], add_only=True)
        ck(r["ok"] and r["files"] == 0, "fetch, add only: a file here is never written")

        # .aht/handover there is never removed by a send that protects it
        (far / ".aht" / "handover").mkdir(parents=True)
        (far / ".aht" / "handover" / "relay-x.md").write_text("left there\n")
        r = rem.send(str(here), str(far), delete=True, protect=(".aht/handover/",),
                     aside=str(X / "aside7"))
        ck(r["ok"] and (far / ".aht" / "handover" / "relay-x.md").is_file(),
           ".aht/handover there stays (protect)")
        # only some files and folders, as file-history and plans go
        fh_here, fh_far = X / "fh-here", X / "fh-far"
        for sid in ("s1", "s2"):
            (fh_here / sid).mkdir(parents=True)
            (fh_here / sid / "v1").write_text(sid)
        (fh_here / "plan.md").write_text("plan")
        (fh_here / "other.md").write_text("not this one")
        r = rem.send(str(fh_here), str(fh_far), only=["s1/", "plan.md", "missing.md"])
        ck(r["ok"] and files_in(fh_far) == ["plan.md", "s1/v1"],
           f"send only some sessions and plans ({files_in(fh_far)})")
        (fh_far / "s1" / "v2").write_text("made there")
        os.utime(fh_far / "plan.md", (time.time() + 60, time.time() + 60))
        (fh_far / "plan.md").write_text("newer there")
        (fh_here / "s1" / "v1").write_text("newer here")
        os.utime(fh_here / "s1" / "v1", (time.time() + 120, time.time() + 120))
        r = rem.fetch(str(fh_far), str(fh_here), only=["s1/", "plan.md"], update=True)
        ck(r["ok"] and (fh_here / "s1" / "v2").is_file()
           and (fh_here / "plan.md").read_text() == "newer there"
           and (fh_here / "s1" / "v1").read_text() == "newer here",
           "fetch only some, never over a newer file here (update)")

        # names: relative, no "..", no drive, no link on the way out
        tgt, outside = X / "safe", X / "outside"
        tgt.mkdir()
        outside.mkdir()
        sublink = False
        try:
            os.symlink(str(outside), tgt / "sub")
            sublink = True
        except OSError:
            pass
        src = X / "evil.txt"
        src.write_bytes(b"evil")
        # a drive, or a leading \, means something only where Windows places
        # the file: elsewhere "C:evil.txt" and "\\back.txt" are plain names
        names = ["../escaped.txt", "/abs.txt", "sub/x.txt", "C:evil.txt", "\\back.txt",
                 "ok.txt"]
        win = os.name == "nt"
        want = names[:2] + (names[2:3] if sublink else []) + (names[3:5] if win else [])
        ents = [{"name": n, "expect": None, "size": 4, "mtime": 1700000000} for n in names]
        stream = b"".join(b"".join(core._file_frames(i, str(src), 0, 4, True))
                          for i in range(len(ents))) + b"Z"
        res = core._place_entries(str(tgt), {"entries": ents, "compress": True},
                                  io.BytesIO(stream))
        refused = sorted(p["name"] for p in res["problems"])
        ck(refused == sorted(want)
           and (tgt / "ok.txt").read_bytes() == b"evil"
           and (win or ((tgt / "C:evil.txt").read_bytes() == b"evil"
                        and (tgt / "\\back.txt").read_bytes() == b"evil"))
           and not (X / "escaped.txt").exists() and not (outside / "x.txt").exists()
           and not Path("/abs.txt").exists(),
           f"names: ../x, an absolute one and a linked folder on the way are refused, "
           f"a drive and a leading \\ {'too' if win else 'only on Windows'}, each "
           f"reported; the rest is placed ({refused})")
        for n in ("C:evil.txt", "\\back.txt"):
            if not win and (tgt / n).exists():
                os.unlink(tgt / n)

        # expect: only what the plan saw is replaced or removed
        g = tgt / "g.txt"
        g.write_text("now")
        res = core._place_entries(str(tgt), {
            "entries": [{"name": "g.txt", "expect": [99, 0], "size": 4, "mtime": 1700000000}],
            "deletes": [{"name": "ok.txt", "expect": [99, 0]}], "compress": True,
            "aside": str(X / "aside8")},
            io.BytesIO(b"".join(core._file_frames(0, str(src), 0, 4, True)) + b"Z"))
        ck(len(res["problems"]) == 2 and g.read_text() == "now"
           and (tgt / "ok.txt").is_file() and not (X / "aside8").exists()
           and all("changed since" in p["error"] for p in res["problems"]),
           f"expect: a file that changed after the plan is neither replaced nor removed "
           f"({res['problems']})")
        # a file that cannot be replaced (on Windows: open in another program,
        # after aht tried 5 more times): the old one goes back, it is reported
        busy = tgt / "busy.txt"
        busy.write_text("old")
        bs = busy.stat()
        real_retry = core._retry
        def in_use(fn, *a):
            if fn is os.replace and str(a[-1]).endswith("busy.txt"):
                raise PermissionError(13, "in use (test)")
            return real_retry(fn, *a)
        core._retry = in_use
        try:
            res = core._place_entries(str(tgt), {
                "entries": [{"name": "busy.txt", "expect": [bs.st_size, int(bs.st_mtime)],
                             "size": 4, "mtime": 1700000000}],
                "compress": True, "aside": str(X / "aside10")},
                io.BytesIO(b"".join(core._file_frames(0, str(src), 0, 4, True)) + b"Z"))
        finally:
            core._retry = real_retry
        ck([p["name"] for p in res["problems"]] == ["busy.txt"]
           and "in use" in res["problems"][0]["error"] and busy.read_text() == "old"
           and not files_in(X / "aside10") and res["set_aside"] == 0,
           f"a file that cannot be replaced: reported, and the old one is back in place "
           f"({res['problems']})")
        stale = rem._far_tree(str(far), [])
        (far / "a.txt").write_text("changed there meanwhile\n")
        (here / "a.txt").write_text("and here\n")
        real_tree = core.Remote._far_tree
        core.Remote._far_tree = lambda self, *a, **k: stale
        try:
            r = rem.send(str(here), str(far), aside=str(X / "aside9"))
        finally:
            core.Remote._far_tree = real_tree
        ck(not r["ok"] and [p["name"] for p in r["problems"]] == ["a.txt"]
           and (far / "a.txt").read_text() == "changed there meanwhile\n",
           f"expect, end to end: a send leaves a file that changed there after its plan "
           f"({r['error']})")

        # a file gone, or shorter, by the time it is read (git's index.lock):
        # skipped, as rsync's "vanished" (exit 24) is no failure; named
        vh, vf = X / "van-here", X / "van-far"
        (vh / ".git").mkdir(parents=True)
        (vh / ".git" / "index.lock").write_text("lock")
        (vh / "keep.txt").write_text("keep\n")
        (vh / "shrinks.txt").write_bytes(b"x" * 5000)
        real_lt = core._local_tree
        def racing(root, names, only=None):
            m = real_lt(root, names, only)
            if root == str(vh):
                os.unlink(vh / ".git" / "index.lock")
                (vh / "shrinks.txt").write_bytes(b"x" * 100)
            return m
        core._local_tree = racing
        try:
            r = rem.send(str(vh), str(vf), delete=True)
        finally:
            core._local_tree = real_lt
        ck(r["ok"] and not r["problems"] and r["skipped"] == [".git/index.lock", "shrinks.txt"]
           and (vf / "keep.txt").read_text() == "keep\n"
           and not (vf / ".git" / "index.lock").exists() and not (vf / "shrinks.txt").exists()
           and not (vf / core.PARTIAL).exists(),
           f"send: a file gone or shorter when read is skipped, not a failure; the rest "
           f"arrives ({r['skipped']}, {r['error']})")

        # an I/O error partway through a file: that file is reported (an X
        # frame), the frames stay whole, the other files arrive
        import builtins, errno
        big = (here / "big.bin").read_bytes()
        class Flaky(io.BytesIO):
            def read(self, n=-1):
                if self.tell() >= core.PIECE:
                    raise OSError(errno.EIO, "Input/output error")
                return super().read(n)
        def flaky_open(path, mode="r", *a, **k):
            if mode == "rb" and str(path).endswith("big.bin"):
                return Flaky(big)
            return builtins.open(path, mode, *a, **k)
        core.open = flaky_open
        try:
            try:
                fr = list(core._file_frames(0, str(here / "big.bin"), 0, len(big), True))
                raised = ""
            except OSError as e:
                fr, raised = [], str(e)
            packed = io.BytesIO()
            try:
                core._agent_pack({"root": str(here), "compress": True,
                                  "entries": [{"src": "big.bin"}, {"src": "a.txt"}]},
                                 None, packed)
                praised = ""
            except OSError as e:
                praised = str(e)
        finally:
            del core.open
        ck(not raised and fr[:1] and fr[0][:1] == b"F" and fr[-1][:1] == b"X"
           and b"Input/output error" in fr[-1],
           f"a read error partway: an X frame after the pieces sent, no exception "
           f"({raised or [f[:1] for f in fr]})")
        got = packed.getvalue()
        tgt2 = X / "flaky-in"
        res = core._place_entries(str(tgt2), {
            "entries": [{"name": "big.bin", "expect": None}, {"name": "a.txt", "expect": None}],
            "compress": True}, io.BytesIO(got[got.find(core.BIN_MARK) + len(core.BIN_MARK):])) \
            if not praised else {"problems": [], "files": 0}
        ck(not praised and [p["name"] for p in res["problems"]] == ["big.bin"]
           and "Input/output error" in res["problems"][0]["error"]
           and (tgt2 / "a.txt").read_bytes() == (here / "a.txt").read_bytes()
           and not (tgt2 / "big.bin").exists(),
           f"pack: a read error partway is that file's problem, the frames stay whole, "
           f"the next file arrives ({praised or res['problems']})")
        # …and any failure while a send writes ends it at once, not after the
        # watchdog, with the error here
        wh, wf = X / "werr-here", X / "werr-far"
        wh.mkdir()
        (wh / "w.bin").write_bytes(os.urandom(300_000))
        real_ff = core._file_frames
        def broken(i, *a, **k):
            yield next(iter(real_ff(i, *a, **k)))
            raise OSError(errno.EIO, "Input/output error")
        core._file_frames = broken
        stall, core.STREAM_STALL = core.STREAM_STALL, 20
        t1 = time.time()
        try:
            rem.send(str(wh), str(wf))
            werr = ""
        except core.HandoverError as e:
            werr = str(e)
        finally:
            core._file_frames = real_ff
            core.STREAM_STALL = stall
        took = time.time() - t1
        ck(took < 10 and "Input/output error" in werr and "went quiet" not in werr,
           f"a send whose reading fails here ends at once ({took:.0f} s: {werr[:90]})")
        r = rem.send(str(wh), str(wf))
        ck(r["ok"] and same_tree(wh, wf), "…and the next send goes through")

        # memory bounds: a frame over its size, a piece that unpacks to more
        # than a piece, and too much around the frames are refused as a
        # broken link, with what was wrong
        import struct, zlib
        def refused(stream, comp=False):
            try:
                core._place_entries(str(X / "caps"), {
                    "entries": [{"name": "c.txt", "expect": None}], "compress": comp},
                    io.BytesIO(stream))
                return ""
            except ValueError as e:
                return str(e)
        meta = json.dumps({"size": 1, "pad": "m" * core.FRAME_META_MAX}).encode()
        bomb = zlib.compress(b"\0" * (8 << 20), 9)
        why = [refused(b"M" + struct.pack(">II", 0, len(meta)) + meta + b"Z"),
               refused(b"X" + struct.pack(">II", 0, 2049) + b"x" * 2049 + b"Z"),
               refused(b"S" + struct.pack(">II", 0, 2049) + b"x" * 2049 + b"Z"),
               refused(b"F" + struct.pack(">IQ", 0, len(bomb)) + bomb + b"Z", True)]
        ck(all("not aht's copy" in w for w in why) and "M frame" in why[0]
           and "X frame" in why[1] and "S frame" in why[2] and "unpacks to more" in why[3],
           f"an M frame over 64 KB, an X or S frame over 2 KB, a piece that unpacks to "
           f"more than 1 MB: refused ({why})")
        cap, core.TRAILER_MAX = core.TRAILER_MAX, 1000
        try:
            outs = []
            for f in (lambda q: q.rest(), lambda q: q.until(core.BIN_MARK)):
                try:
                    f(core._Pipe(io.BytesIO(b"y" * 5000)))
                    outs.append("")
                except ValueError as e:
                    outs.append(str(e))
            core.TRAILER_MAX = 40
            (wh / "w.bin").write_bytes(b"changed")
            try:
                rem.send(str(wh), str(wf))
                big_answer = ""
            except core.LinkError as e:
                big_answer = str(e)
        finally:
            core.TRAILER_MAX = cap
        ck(all("more than" in o for o in outs) and "dropped" in big_answer
           and "an answer of more than" in big_answer,
           f"what comes around the frames is held only up to a cap ({outs}; "
           f"{big_answer[-70:]})")

        # a Mac's NFD name: the file there is replaced under the name it has,
        # no twin appears; and the same coming back
        key = unicodedata.normalize("NFC", "Größe.txt")
        nh, nf = X / "nfd-here", X / "nfd-far"
        nh.mkdir()
        nf.mkdir()
        (nh / key).write_text("v2 from here\n")
        (nf / unicodedata.normalize("NFD", key)).write_text("v1\n")
        r = rem.send(str(nh), str(nf))
        there = [n for n in os.listdir(nf) if unicodedata.normalize("NFC", n) == key]
        ck(r["ok"] and len(there) == 1 and (nf / there[0]).read_text() == "v2 from here\n",
           f"an NFD name there is replaced under its own name, no twin ({there})")
        (nf / there[0]).write_text("v3 from there\n")
        r = rem.fetch(str(nf), str(nh), entries={key: there[0]})
        mine = [n for n in os.listdir(nh) if unicodedata.normalize("NFC", n) == key]
        ck(r["ok"] and len(mine) == 1 and (nh / mine[0]).read_text() == "v3 from there\n",
           f"…and back here, no twin ({mine})")

        # CRLF read as LF (the hash op's norm)
        (X / "crlf.txt").write_bytes(b"one\r\ntwo\r\n" * 70000 + b"\r")
        (X / "lf.txt").write_bytes(b"one\ntwo\n" * 70000 + b"\r")
        h = rem.agent("hash", norm=True, files=[{"key": "c", "path": str(X / "crlf.txt")},
                                                 {"key": "l", "path": str(X / "lf.txt")}])
        h0 = rem.agent("hash", files=[{"key": "c", "path": str(X / "crlf.txt")},
                                      {"key": "l", "path": str(X / "lf.txt")}])
        ck(h["hashes"]["c"] == h["hashes"]["l"] and h0["hashes"]["c"] != h0["hashes"]["l"],
           "hash with norm: line endings alone make no difference")

        # one copy into a folder at a time; a lock a copy that was cut off left goes
        lockd = far / core.PARTIAL
        lockd.mkdir()
        (lockd / ".lock").write_text(str(os.getpid()))
        (here / "a.txt").write_text("locked out\n")
        try:
            rem.send(str(here), str(far))
            busy = ""
        except core.HandoverError as e:
            busy = str(e)
        (lockd / ".lock").write_text("999999")
        (lockd / "7").write_bytes(b"half a file")
        r = rem.send(str(here), str(far))
        ck("another copy into" in busy and r["ok"] and not lockd.exists()
           and (far / "a.txt").read_text() == "locked out\n",
           f"a live copy's lock is respected; a dead one's lock and its leftovers go ({busy})")

        if os.name == "nt" or not os.path.exists("/bin/sh"):
            print("  SKIP the stand-in ssh needs /bin/sh")
            return
        # a stand-in ssh that cuts the copy off halfway: the rerun converges,
        # and every file replaced on the way is in one of the two set-asides
        fs = X / "fakessh"
        machine = fs / "127.0.0.1"
        (machine / "home").mkdir(parents=True)
        (machine / "path").write_text(f"{Path(PY).parent}:/usr/bin:/bin:/usr/sbin:/sbin")
        sshbin = X / "sshbin"
        sshbin.mkdir()
        (sshbin / "ssh").write_text(f'#!/bin/sh\nexec "{PY}" "{HERE / "fake_ssh.py"}" "$@"\n')
        (sshbin / "ssh").chmod(0o755)
        was_env = {k: os.environ.get(k) for k in ("PATH", "FAKE_SSH_DIR")}
        os.environ["PATH"] = str(sshbin) + os.pathsep + os.environ.get("PATH", "")
        os.environ["FAKE_SSH_DIR"] = str(fs)
        h2, f2 = X / "cut-here", X / "cut-far"
        h2.mkdir()
        f2.mkdir()
        old = {}
        for i in range(40):
            (h2 / f"f{i:02d}.bin").write_bytes(os.urandom(50_000))
            old[f"f{i:02d}.bin"] = os.urandom(30_000 + i)
            (f2 / f"f{i:02d}.bin").write_bytes(old[f"f{i:02d}.bin"])
        rc = core.Remote("cut", {"ssh": "far@127.0.0.1"})
        try:
            (machine / "die-after").write_text("700000")
            try:
                rc.send(str(h2), str(f2), delete=True, aside=str(X / "cut-aside1"))
                cut = ""
            except core.LinkError as e:
                cut = str(e)
            first = files_in(X / "cut-aside1")
            (machine / "die-after").unlink()
            r = rc.send(str(h2), str(f2), delete=True, aside=str(X / "cut-aside2"))
            second = files_in(X / "cut-aside2")
            kept = {}
            for d, names in ((X / "cut-aside1", first), (X / "cut-aside2", second)):
                for n in names:
                    kept[n] = (d / n).read_bytes()
            ck("dropped" in cut and 0 < len(first) < 40 and r["ok"] and same_tree(h2, f2)
               and kept == old and not (f2 / core.PARTIAL).exists(),
               f"a link cut after 700 KB: {len(first)} files placed, each replaced one set "
               f"aside; the rerun brings the rest and sets aside the other {len(second)}")

            # a link that goes quiet: the watchdog ends the copy
            for i in range(40):
                (h2 / f"f{i:02d}.bin").write_bytes(os.urandom(50_000))
            (machine / "hang-after").write_text("300000")
            stall, core.STREAM_STALL = core.STREAM_STALL, 2
            t1 = time.time()
            try:
                rc.send(str(h2), str(f2), aside=str(X / "cut-aside3"))
                quiet = ""
            except core.LinkError as e:
                quiet = str(e)
            finally:
                core.STREAM_STALL = stall
                (machine / "hang-after").unlink()
            took = time.time() - t1
            for _ in range(100):            # the far end sees its input end, and goes
                if not (f2 / core.PARTIAL).exists():
                    break
                time.sleep(0.1)
            ck("went quiet" in quiet and took < 30 and not (f2 / core.PARTIAL).exists(),
               f"a link that goes quiet is ended by the watchdog ({took:.0f} s: {quiet[:60]})")
        finally:
            for k, v in was_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    finally:
        if was_mode is None:
            os.environ.pop("AHT_TRANSFER", None)
        else:
            os.environ["AHT_TRANSFER"] = was_mode
        shutil.rmtree(X, ignore_errors=True)

transport_suite()

done()
