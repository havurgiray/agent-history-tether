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
one file and places the rest.

A PC that answers (phase 9): `start` queues Continue here (the arrival
record, which `_arrival --json` lists) instead of a session, with the level's
flags and the note the handover named, which `_arrival --continue` starts
Claude Code with (once: again only with --again); `stop` and `close` say
"windows", the trust key has forward slashes.  Off Windows the
far end is told to answer as a PC (AHT_TEST_FAR_NT).  On Windows the lines a
Mac sends are also run the way Windows' ssh server runs them: as one
command line after `cmd.exe /c` (aht.exe, and aht's own copy written and
run with py -3 or python), and through PowerShell once."""
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


def pc_checks(cmd, env, tmp: Path, exe) -> None:
    """A PC that answers: the ops, then the command lines through cmd.exe."""
    if os.name != "nt":
        env = dict(env, AHT_TEST_FAR_NT="1")
    home = Path(env["HOME"])
    proj = tmp / "pc-project"
    proj.mkdir()
    name = "aht-pc-project-abc123"
    sid = "5d6e7f80-1111-4222-8333-444455556666"
    st, _ = ask(cmd, env, {"op": "start", "path": str(proj), "name": name, "session": sid,
                           "attempt": "20261028-120000-ab12", "from": "mac",
                           "title": "Checkout flow", "args": ["--permission-mode", "auto"],
                           "claude_sandbox": False,
                           "note": "[aht] This session was handed over from mac."})
    rec_f = home / ".aht" / "arrivals" / f"{name}.json"
    rec = json.loads(rec_f.read_text(encoding="utf-8")) if rec_f.is_file() else {}
    ck(st.get("ok") and st.get("started") is False and st.get("reason") == "windows"
       and st.get("arrival") == name and rec.get("text") == "pc-project came from mac"
       and rec.get("action") == "Continue here"
       and rec.get("argv") == ["_arrival", "--continue", name]
       and rec.get("resume") == ["resume-here", str(proj), "--session", sid],
       f"start on a PC: no session, Continue here queued ({st.get('reason')}, {rec.get('text')})")
    cli = [c for c in cmd[:-1]]                 # the same program, another command
    r = subprocess.run(cli + ["_arrival", "--json"], capture_output=True, env=env, timeout=120)
    try:
        listed = [a.get("name") for a in json.loads(r.stdout.decode("utf-8"))["arrivals"]]
    except (ValueError, KeyError):
        listed = r.stdout.decode("utf-8", "replace")[-300:] + r.stderr.decode("utf-8", "replace")[-300:]
    ck(listed == [name], f"_arrival --json lists it for the tray ({listed})")
    # Continue here: the level the handover named (never read again here),
    # the session, and a SessionStart hook that tells it the note
    term = tmp / "pc-term.log"
    cenv = dict(env, AHT_TERMINAL_LOG=str(term), AHT_CLAUDE="claude")
    def cont(*more):
        r = subprocess.run(cli + ["_arrival", "--continue", name, "--json", *more],
                           capture_output=True, env=cenv, timeout=120)
        try:
            return json.loads(r.stdout.decode("utf-8"))
        except ValueError:
            return {"unparsed": r.stdout.decode("utf-8", "replace")[-300:]
                    + r.stderr.decode("utf-8", "replace")[-300:]}
    c1 = cont()
    line = term.read_text(encoding="utf-8") if term.is_file() else ""
    run_d = home / ".aht" / "remote" / "run" / name
    try:
        hook = json.loads((run_d / "settings.json").read_text(encoding="utf-8"))[
            "hooks"]["SessionStart"][0]["hooks"][0]["command"]
    except (OSError, ValueError, KeyError, IndexError):
        hook = ""
    note = (run_d / "note.txt").read_text(encoding="utf-8") if (run_d / "note.txt").is_file() \
        else ""
    # cmd.exe's line quotes every word; Claude Code runs hooks through sh (Git
    # Bash on Windows), so the note is read with cat everywhere
    ck(c1.get("applied") and f"--permission-mode auto --resume {sid} --settings"
       in line.replace('"', "")
       and note == "[aht] This session was handed over from mac."
       and hook.startswith("cat "),
       f"Continue here: the level and the note the handover named ({c1}, {line[-200:]}, {hook})")
    c2, c3 = cont(), cont("--again")
    ck(not c2.get("applied") and "was already used" in (c2.get("error") or "")
       and c3.get("applied"),
       f"…once: a second one is refused, --again opens it ({c2.get('error')}, {c3})")
    sp, _ = ask(cmd, env, {"op": "stop", "path": str(proj), "name": name})
    cl, _ = ask(cmd, env, {"op": "close", "path": str(proj), "name": name})
    ck(sp.get("stopped") is False and sp.get("reason") == "windows"
       and cl.get("closed") is False and cl.get("reason") == "windows" and rec_f.is_file(),
       f"stop and close on a PC say windows; Continue here stays offered ({sp}, {cl})")
    (home / ".claude.json").write_text("{}", encoding="utf-8")
    tr, _ = ask(cmd, env, {"op": "trust", "path": "C:\\Users\\me\\code\\shop"})
    keys = list((json.loads((home / ".claude.json").read_text(encoding="utf-8"))
                 .get("projects") or {}))
    ck(tr.get("trust") == "carried over" and keys == ["C:/Users/me/code/shop"],
       f"trust on a PC: the key with forward slashes, as Claude Code writes it there ({keys})")
    pr, _ = ask(cmd, env, {"op": "prepare", "dirs": [], "copy_note": {
        "path": str(proj), "uuid": "0123456789abcdef0123456789abcdef", "from": "mac",
        "kind": "returned"}})
    ck(pr.get("ok") and not rec_f.exists(),
       "taken back (its copy note is no longer a handover's): the arrival is gone")
    if os.name == "nt":
        through_cmd(exe, env, tmp)

def through_cmd(exe, env, tmp: Path) -> None:
    """The lines as Windows' ssh server runs them: `cmd.exe /c <line>`, the
    line passed as it is (never re-quoted), the request on stdin."""
    sys.path.insert(0, str(REPO))
    import aht as core
    probe = json.dumps({"op": "probe"}).encode("utf-8") + b"\n"
    def run(line, data, shell="cmd"):
        if shell == "cmd":
            full = "cmd.exe /d /c " + line
        else:
            import base64
            full = ("powershell.exe -NoProfile -NonInteractive -EncodedCommand "
                    + base64.b64encode(line.encode("utf-16-le")).decode("ascii"))
        return subprocess.run(full, input=data, capture_output=True, env=env, timeout=300)
    def answer(r):
        i = r.stdout.rfind(MARK + b"{")
        return json.loads(r.stdout[i + len(MARK):].decode("utf-8")) if i >= 0 else {}
    # aht.exe (or, from source, an aht.cmd standing in for it) on the PATH
    bin_ = tmp / "pc-bin"
    bin_.mkdir()
    if exe:
        path = str(Path(exe).resolve().parent)
    else:
        (bin_ / "aht.cmd").write_text(
            f'@"{sys.executable}" "{REPO / "windows" / "src" / "aht_main.py"}" %*\r\n')
        path = str(bin_)
    env = dict(env, PATH=path + os.pathsep + env.get("PATH", ""))
    sbx = Path(os.path.realpath(tmp)) / "pc-sbx"     # long names: no RUNNER~1
    a = answer(run(core.nt_agent_line("aht"), probe))
    ck(a.get("ok") and a.get("system") == "Windows"
       and a.get("protocol", 0) >= core.PC_PROTOCOL and not core.pc_out_of_range(a),
       f"through cmd.exe: `aht _agent` answers, in range ({a.get('protocol')}, "
       f"{a.get('error')})")
    if core.nt_sandbox_ok(str(sbx)):
        a = answer(run(core.nt_agent_line("aht", str(sbx)), probe))
        ck(a.get("home") == str(sbx / "home"),
           f"through cmd.exe: `aht _agent --sandbox` keeps to the sandbox ({a.get('home')})")
    else:
        print(f"  SKIP the sandbox line: {sbx} is not a plain C:\\ folder")
    # aht's own copy, written and then run by the Python there
    def has_python(r):
        v = run(r + (" -3" if r == "py" else "") + " --version", b"")
        return v.returncode == 0 and b"Python 3" in v.stdout + v.stderr
    py = next((r for r in ("py", "python") if has_python(r)), None)
    if not py:
        print("  SKIP aht's own copy through cmd.exe: neither py nor python here")
        return
    cid = hashlib.sha256((REPO / "aht.py").read_bytes()).hexdigest()[:12]
    sb = str(sbx) if core.nt_sandbox_ok(str(sbx)) else ""
    copy = (Path(sb) / "home" if sb else Path(env["USERPROFILE"])) / ".aht" / "remote" / \
        f"aht-{cid}.py"
    w = run(core.nt_agent_line(py, sb, cid, write=".aht-new-cut"),
            (REPO / "aht.py").read_bytes()[:200_000])
    left = list(copy.parent.glob(".aht-new-*")) if copy.parent.is_dir() else []
    ck(b"aht-copy-cut-short" in w.stderr and not copy.exists() and not left,
       f"through cmd.exe: aht's copy cut short is not put in place "
       f"({w.stderr.decode('utf-8', 'replace')[-200:]})")
    w = run(core.nt_agent_line(py, sb, cid, write=".aht-new-smoke"), (REPO / "aht.py").read_bytes())
    ck(b"aht-copy-written" in w.stdout and copy.is_file()
       and copy.read_bytes() == (REPO / "aht.py").read_bytes(),
       f"through cmd.exe: {py} writes aht's copy from stdin, byte for byte "
       f"({w.stderr.decode('utf-8', 'replace')[-200:]})")
    a = answer(run(core.nt_agent_line(py, sb, cid), probe))
    ck(a.get("ok") and a.get("system") == "Windows" and a.get("core_id") == cid,
       f"through cmd.exe: {py} runs aht's copy as the far end, plain Python, no entry point "
       f"({a.get('core_id')}, {a.get('error')})")
    proj = tmp / "pc-project-2"
    proj.mkdir()
    pr = answer(run(core.nt_agent_line(py, sb, cid), json.dumps({
        "op": "prepare", "dirs": [], "copy_note": {
            "path": str(proj), "uuid": "0123456789abcdef0123456789abcdef", "from": "mac",
            "kind": "handover"}}).encode("utf-8")))
    ck(pr.get("ok"), f"…and takes aht's lock there without the entry point's fcntl "
                     f"({pr.get('error')})")
    r = run(core.nt_agent_line(py, sb, cid), probe, shell="powershell")
    a = answer(r)
    err = r.stderr.decode("utf-8", "replace")
    if a:
        ck(a.get("ok") and a.get("core_id") == cid, "through PowerShell: the same line answers")
    else:
        ck(not any(x in err for x in ("ParserError", "Unexpected token", "is not recognized")),
           f"through PowerShell: the same line parses (no answer: PowerShell kept stdin) "
           f"({err[-200:]})")

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
        pc_checks(cmd, env, tmp, exe)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\nAGENT SMOKE:", "ALL PASS" if not FAILS else f"{len(FAILS)} FAIL")
    for f in FAILS:
        print("  -", f)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
