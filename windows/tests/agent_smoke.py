#!/usr/bin/env python3
"""aht's far end, asked directly: `aht _agent` gets the ops probe, manifest,
pack and unpack on stdin, with no ssh, and its answers are checked here with
an encoder and a parser of the frames of its own (so the wire format is
checked, not only the core against itself).

    python windows/tests/agent_smoke.py                 # from source
    python windows/tests/agent_smoke.py path/to/aht.exe # the built exe

From source it runs windows/src/aht_main.py, as the exe does.  Everything
happens in a throwaway home.  On Windows it also holds a target file open
during an unpack: aht tries again 5 times, 0.2 s apart, then reports that
one file and places the rest."""
import hashlib, json, os, shutil, struct, subprocess, sys, tempfile, time, zlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MARK = b"@@AHT@@"
BIN = b"\n" + MARK + b"BIN\n"
FAILS = []


def ck(cond, msg):
    print(("  PASS " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def far_env(home: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("AHT_")}
    env.update(HOME=str(home), USERPROFILE=str(home), AHT_HOME=str(home / ".aht"),
               AHT_ROOT_CLAUDE=str(home / ".claude" / "projects"), AHT_NO_ICONS="1",
               AHT_NO_NOTIFY="1", AHT_NO_BACKUP="1", AHT_NO_MIRROR="1",
               PYTHONIOENCODING="utf-8")
    (home / ".aht").mkdir(parents=True, exist_ok=True)
    (home / ".claude" / "projects").mkdir(parents=True, exist_ok=True)
    return env


def ask(argv, env, req: dict, frames: bytes = b"") -> tuple:
    """(answer, what came before it): one request line, then frames."""
    data = json.dumps(req).encode("utf-8") + b"\n" + frames
    r = subprocess.run(argv, input=data, capture_output=True, env=env, timeout=300)
    i = r.stdout.rfind(MARK + b"{")
    if i < 0:
        raise SystemExit(f"no answer to {req['op']} (exit {r.returncode}): "
                         + (r.stderr or r.stdout).decode("utf-8", "replace")[-600:])
    return json.loads(r.stdout[i + len(MARK):].decode("utf-8")), r.stdout[:i]


def read_frames(raw: bytes, compressed: bool) -> dict:
    """{index: {"meta", "data", "ok", "error", "skipped"}} from pack's output."""
    j = raw.find(BIN)
    if j < 0:
        raise SystemExit("pack sent no BIN mark")
    pos, out = j + len(BIN), {}
    def take(n):
        nonlocal pos
        if pos + n > len(raw):
            raise SystemExit("pack's frames end early")
        b = raw[pos:pos + n]
        pos += n
        return b
    while True:
        kind = take(1)
        if kind == b"Z":
            return out
        if kind == b"M":
            i, n = struct.unpack(">II", take(8))
            out.setdefault(i, {"data": b""})["meta"] = json.loads(take(n))
        elif kind == b"F":
            i, n = struct.unpack(">IQ", take(12))
            piece = take(n)
            out.setdefault(i, {"data": b""})["data"] += zlib.decompress(piece) \
                if compressed else piece
        elif kind == b"E":
            (i,) = struct.unpack(">I", take(4))
            d = take(32)
            f = out.setdefault(i, {"data": b""})
            f["ok"] = hashlib.sha256(f["data"]).digest() == d
        elif kind in (b"X", b"S"):          # could not be read; gone, or shorter
            i, n = struct.unpack(">II", take(8))
            out.setdefault(i, {"data": b""})["error" if kind == b"X" else "skipped"] = \
                take(n).decode("utf-8")
        else:
            raise SystemExit(f"pack sent an unknown frame {kind!r}")


def frames_of(files: list, compressed: bool) -> bytes:
    """unpack's input: each file as F pieces of at most 1 MB, then E; then Z."""
    out = []
    for i, data in enumerate(files):
        for k in range(0, len(data), 1 << 20):
            piece = data[k:k + (1 << 20)]
            piece = zlib.compress(piece, 1) if compressed else piece
            out.append(b"F" + struct.pack(">IQ", i, len(piece)) + piece)
        out.append(b"E" + struct.pack(">I", i) + hashlib.sha256(data).digest())
    return b"".join(out) + b"Z"


def main(argv) -> int:
    exe = argv[0] if argv else None
    cmd = [exe, "_agent"] if exe else \
        [sys.executable, str(REPO / "windows" / "src" / "aht_main.py"), "_agent"]
    print(f"aht's far end: {' '.join(cmd)}")
    tmp = Path(tempfile.mkdtemp(prefix="aht-agent-smoke-"))
    try:
        env = far_env(tmp / "home")

        info, _ = ask(cmd, env, {"op": "probe"})
        ck(info.get("ok") and info.get("protocol", 0) >= 2
           and {"probe", "manifest", "pack", "unpack", "hash"} <= set(info.get("ops") or [])
           and info.get("machine_id") is None,
           f"probe: protocol {info.get('protocol')} on {info.get('system')}, the copy's "
           "ops named, no machine id made")

        # every byte value (CR, LF, Ctrl-Z, NUL), a big file, a name beyond ASCII,
        # an empty file and an empty folder
        src = tmp / "src"
        (src / "sub" / "empty").mkdir(parents=True)
        files = {"bytes.bin": bytes(range(256)) * 300 + b"\r\n\x1a\r",
                 "big.bin": os.urandom(2_600_000),
                 "sub/Größe.txt": "ä\r\nö\n".encode("utf-8"),
                 "empty.txt": b""}
        for k, data in files.items():
            (src / k).write_bytes(data)
        m, _ = ask(cmd, env, {"op": "manifest", "trees": {"t": {"path": str(src), "skip": []}}})
        t = m.get("trees", {}).get("t", {})
        ck(m.get("ok") and sorted(t.get("files") or {}) == sorted(files)
           and all(t["files"][k][0] == len(v) for k, v in files.items())
           and "sub/empty" in (t.get("dirs") or []),
           f"manifest: keys with /, sizes, the empty folder ({sorted(t.get('files') or {})})")

        # pack: the files as frames after the BIN mark; one that is not there is
        # skipped in its own frame (S: rsync's "vanished", no failure)
        keys = sorted(files)
        for comp in (True, False):
            res, raw = ask(cmd, env, {"op": "pack", "root": str(src), "compress": comp,
                                      "entries": [{"src": k} for k in keys]
                                      + [{"src": "missing.txt"}]})
            got = read_frames(raw + MARK, comp) if res.get("ok") else {}
            ck(res.get("ok") and all(got.get(i, {}).get("ok")
                                     and got[i]["data"] == files[k]
                                     and got[i]["meta"]["size"] == len(files[k])
                                     for i, k in enumerate(keys))
               and "skipped" in got.get(len(keys), {})
               and "error" not in got.get(len(keys), {}),
               f"pack{' (compressed)' if comp else ''}: every file byte for byte, digest "
               "checked; a missing one skipped")
        # a prefix the far end has: only the rest comes
        head = files["big.bin"][:300_000]
        res, raw = ask(cmd, env, {"op": "pack", "root": str(src), "compress": False,
                                  "entries": [{"src": "big.bin", "prefix": [
                                      len(head), hashlib.sha256(head).hexdigest()]}]})
        got = read_frames(raw + MARK, False).get(0, {})
        ck(got.get("meta", {}).get("append_from") == len(head)
           and got.get("data") == files["big.bin"][len(head):],
           "pack with a prefix: only the tail travels")

        # unpack: files, folders, the old one set aside, the plan's guard
        dst, aside = tmp / "dst", tmp / "aside"
        ents = [{"name": k, "expect": None, "size": len(files[k]), "mtime": 1700000000}
                for k in keys]
        res, _ = ask(cmd, env, {"op": "unpack", "root": str(dst), "compress": True,
                                "aside": str(aside), "entries": ents,
                                "dirs": ["sub/empty"]},
                     frames_of([files[k] for k in keys], True))
        ck(res.get("ok") and res.get("files") == len(keys) and not res.get("problems")
           and all((dst / k).read_bytes() == files[k] for k in keys)
           and int((dst / "big.bin").stat().st_mtime) == 1700000000
           and (dst / "sub" / "empty").is_dir() and not (dst / ".aht-partial").exists(),
           f"unpack: every file byte for byte, its time, the empty folder ({res.get('problems')})")
        new = b"replaced\r\n"
        st = (dst / "bytes.bin").stat()
        res, _ = ask(cmd, env, {"op": "unpack", "root": str(dst), "compress": False,
                                "aside": str(aside), "entries": [
                                    {"name": "bytes.bin", "expect": [st.st_size, int(st.st_mtime)],
                                     "size": len(new), "mtime": 1700000001},
                                    {"name": "empty.txt", "expect": [99, 0], "size": len(new),
                                     "mtime": 1700000001},
                                    {"name": "../out.txt", "expect": None, "size": len(new),
                                     "mtime": 1700000001}]},
                     frames_of([new, new, new], False))
        probs = {p["name"]: p["error"] for p in res.get("problems") or []}
        ck(res.get("ok") and (dst / "bytes.bin").read_bytes() == new
           and (aside / "bytes.bin").read_bytes() == files["bytes.bin"]
           and (dst / "empty.txt").read_bytes() == b"" and "changed since" in probs.get("empty.txt", "")
           and "../out.txt" in probs and not (tmp / "out.txt").exists(),
           f"unpack: the replaced file set aside; one that changed since the plan, and "
           f"../x, refused ({sorted(probs)})")

        # what the near end sends is bounded too: a piece that unpacks to more
        # than 1 MB, or an X frame over 2 KB, is refused, nothing is placed
        bomb = zlib.compress(b"\0" * (8 << 20), 9)
        why = []
        for comp, fr in ((True, b"F" + struct.pack(">IQ", 0, len(bomb)) + bomb + b"Z"),
                         (False, b"X" + struct.pack(">II", 0, 4096) + b"x" * 4096 + b"Z")):
            res, _ = ask(cmd, env, {"op": "unpack", "root": str(tmp / "bounded"),
                                    "compress": comp, "entries": [
                                        {"name": "b.bin", "expect": None, "size": 8 << 20,
                                         "mtime": 1700000000}]}, fr)
            why.append(res.get("error") or "")
        ck("unpacks to more than" in why[0] and "X frame" in why[1]
           and not (tmp / "bounded" / "b.bin").exists(),
           f"unpack: a piece that unpacks to more than 1 MB, an X frame over 2 KB: "
           f"refused ({why})")

        if os.name == "nt":
            # a target another program holds open: tried again, then reported;
            # the other file is placed
            held = dst / "held.txt"
            held.write_bytes(b"open elsewhere")
            hs = held.stat()
            with open(held, "rb"):
                t0 = time.time()
                res, _ = ask(cmd, env, {"op": "unpack", "root": str(dst), "compress": False,
                                        "aside": str(aside), "entries": [
                                            {"name": "held.txt",
                                             "expect": [hs.st_size, int(hs.st_mtime)],
                                             "size": len(new), "mtime": 1700000002},
                                            {"name": "free.txt", "expect": None,
                                             "size": len(new), "mtime": 1700000002}]},
                             frames_of([new, new], False))
                took = time.time() - t0
            probs = {p["name"]: p["error"] for p in res.get("problems") or []}
            logf = tmp / "home" / ".aht" / "aht.log"
            tries = logf.read_text(encoding="utf-8", errors="replace").count("trying again") \
                if logf.is_file() else 0
            ck(res.get("ok") and "in use" in probs.get("held.txt", "") and tries == 5
               and took >= 1.0 and (dst / "free.txt").read_bytes() == new
               and held.read_bytes() == b"open elsewhere",
               f"a file held open: 5 tries in {took:.1f} s, then reported "
               f"({probs.get('held.txt')}); the rest is placed")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\nAGENT SMOKE:", "ALL PASS" if not FAILS else f"{len(FAILS)} FAIL")
    for f in FAILS:
        print("  -", f)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
