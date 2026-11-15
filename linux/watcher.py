#!/usr/bin/env python3
"""
aht watcher for Linux — the counterpart of the macOS FSEvents watcher.

Watches the configured roots and tells aht when a tracked project was
renamed or moved, a copy or a project from elsewhere appeared, or a git
repository did.  It does not search: inotify names the folders that appear,
go or are renamed, aht.WatchJudge decides whether one of them matters (a
project, a folder above one, a marker's folder, a .git), and only then
    aht.py reconcile --quick --notify [--renamed OLD NEW] [--look DIR]
runs, without the walk of the roots.  Files being saved start nothing.  A
regular look every ten minutes starts aht's periodic work, and the roots are
walked once a day (and at the start), for what went unseen.

Two backends:
  • inotify  (default) — via ctypes, no third-party modules.  Recursive by
    walking the tree and adding one watch per directory, then adding watches for
    directories as they appear.
  • polling  (--poll, or automatic when the inotify watch budget is exhausted) —
    every few seconds it checks that each project is where the registry has
    it, and walks the roots with each regular look.  Slower to react but
    immune to inotify limits and works on network/fuse mounts.

Single-flight by construction: reconcile runs synchronously in the event loop,
so a prompt can never be stacked on top of another prompt.  Events that arrive
during a run stay queued in the kernel and are handled right after.
"""
import argparse
import ctypes
import ctypes.util
import errno
import os
import select
import struct
import subprocess
import sys
import time
from pathlib import Path

# --------------------------------------------------------------------------- #
# Locate and import the shared core (aht.py)
# --------------------------------------------------------------------------- #

def _find_core() -> Path:
    """aht.py lives next to us once installed; in a git checkout it is one
    directory up.  An explicit --aht always wins."""
    here = Path(__file__).resolve().parent
    for c in (here / "aht.py", here.parent / "aht.py",
              Path.home() / ".aht/tools/agent-history-tether/aht.py"):
        if c.is_file():
            return c
    raise SystemExit("watcher: cannot find aht.py (pass --aht /path/to/aht.py)")

CORE = None      # Path to aht.py, set in main()
aht = None      # the imported module

def _import_core(path: Path):
    global aht
    sys.path.insert(0, str(path.parent))
    import importlib
    aht = importlib.import_module(path.stem)
    return aht

def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] watcher: {msg}"
    print(line, flush=True)                      # journald / StandardOutPath
    try:
        aht.log(f"WATCHER {msg}")
    except Exception:
        pass

# --------------------------------------------------------------------------- #
# inotify via ctypes (stdlib only)
# --------------------------------------------------------------------------- #

IN_CREATE      = 0x00000100
IN_DELETE      = 0x00000200
IN_MOVED_FROM  = 0x00000040
IN_MOVED_TO    = 0x00000080
IN_MOVE_SELF   = 0x00000800
IN_DELETE_SELF = 0x00000400
IN_Q_OVERFLOW  = 0x00004000
IN_IGNORED     = 0x00008000
IN_ISDIR       = 0x40000000
IN_ONLYDIR     = 0x01000000
IN_EXCL_UNLINK = 0x04000000
IN_NONBLOCK    = 0x00000800          # O_NONBLOCK for inotify_init1

WATCH_MASK = (IN_CREATE | IN_DELETE | IN_MOVED_FROM | IN_MOVED_TO |
              IN_MOVE_SELF | IN_DELETE_SELF | IN_ONLYDIR | IN_EXCL_UNLINK)

_EVENT = struct.Struct("iIII")       # wd, mask, cookie, name_len


class Inotify:
    def __init__(self):
        lib = ctypes.util.find_library("c") or "libc.so.6"
        self.libc = ctypes.CDLL(lib, use_errno=True)
        self.libc.inotify_init1.argtypes = [ctypes.c_int]
        self.libc.inotify_init1.restype = ctypes.c_int
        self.libc.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p,
                                                ctypes.c_uint32]
        self.libc.inotify_add_watch.restype = ctypes.c_int
        self.libc.inotify_rm_watch.argtypes = [ctypes.c_int, ctypes.c_int]
        self.libc.inotify_rm_watch.restype = ctypes.c_int
        self.fd = self.libc.inotify_init1(IN_NONBLOCK)
        if self.fd < 0:
            raise OSError(ctypes.get_errno(), "inotify_init1 failed")
        self.wd_to_path = {}
        self.path_to_wd = {}

    def add(self, path: str) -> bool:
        """Add one directory watch.  Returns False when the kernel says no more
        watches are available (ENOSPC) — the caller falls back to polling."""
        if path in self.path_to_wd:
            return True
        wd = self.libc.inotify_add_watch(self.fd, os.fsencode(path), WATCH_MASK)
        if wd < 0:
            e = ctypes.get_errno()
            if e == errno.ENOSPC:
                raise OSError(errno.ENOSPC, "inotify watch limit reached")
            return False          # vanished / permission denied: not fatal
        self.wd_to_path[wd] = path
        self.path_to_wd[path] = wd
        return True

    def drop(self, wd: int) -> None:
        p = self.wd_to_path.pop(wd, None)
        if p is not None:
            self.path_to_wd.pop(p, None)

    def read_events(self):
        try:
            data = os.read(self.fd, 1 << 16)
        except BlockingIOError:
            return
        except OSError as e:
            if e.errno in (errno.EAGAIN, errno.EINTR):
                return
            raise
        pos, n = 0, len(data)
        while pos + _EVENT.size <= n:
            wd, mask, cookie, ln = _EVENT.unpack_from(data, pos)
            pos += _EVENT.size
            raw = data[pos:pos + ln]
            pos += ln
            name = raw.split(b"\0", 1)[0].decode("utf-8", "replace")
            yield wd, mask, cookie, name

    def close(self):
        try:
            os.close(self.fd)
        except Exception:
            pass


def walk_dirs(root: str, pruned: set):
    """Every directory under root that we want to watch (same pruning rules the
    scanner uses, so the watcher and the scanner agree on what 'inside' means)."""
    root = os.path.realpath(root)
    if not os.path.isdir(root):
        return
    yield root
    for dirpath, dirnames, _files in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(".") and d not in pruned]
        for d in dirnames:
            yield os.path.join(dirpath, d)


# --------------------------------------------------------------------------- #
# Reconcile driver
# --------------------------------------------------------------------------- #

class Runner:
    def __init__(self, core: Path, python: str, roots, extra_args):
        self.core, self.python, self.roots = core, python, roots
        self.extra = list(extra_args or [])
        self.runs = 0

    def run(self, extra=()) -> int:
        """Run reconcile synchronously.  Synchronous IS the single-flight
        guarantee: no second prompt can appear while this one is open.
        `extra`: reconcile's own options ("--quick", "--look", …); none: with
        the walk of the roots."""
        cmd = [self.python, str(self.core), "reconcile", "--notify"] + self.extra + list(extra)
        if self.roots:
            cmd += ["--roots"] + list(self.roots)
        self.runs += 1
        t0 = time.time()
        try:
            r = subprocess.run(cmd, capture_output=True, text=True)
        except Exception as e:
            log(f"reconcile failed to launch: {e}")
            return -1
        dt = time.time() - t0
        if r.returncode != 0:
            log(f"reconcile exited {r.returncode} in {dt:.1f}s: "
                f"{(r.stderr or '').strip()[:400]}")
        else:
            summary, quiet = "", False
            try:
                import json
                d = json.loads(r.stdout or "{}")
                bits = [f"{k}={len(d.get(k, []))}" for k in ("moves", "copies", "news")
                        if d.get(k)]
                summary = (" ".join(bits) or "nothing to do") \
                    + (" (with the walk)" if d.get("walked") else "")
                # a look that found nothing leaves no line
                quiet = not bits and not d.get("walked") \
                    and not os.environ.get("AHT_WATCHER_DEBUG")
            except Exception:
                summary = "ok"
            if not quiet:
                log(f"reconcile {summary} ({dt:.1f}s)")
        return r.returncode


# --------------------------------------------------------------------------- #
# Backends
# --------------------------------------------------------------------------- #

def run_poll(roots, runner, interval, once=False):
    """No inotify here: every `interval` seconds each project is checked to
    be where the registry has it, and the roots are walked with each regular
    look (a move is only found by that walk: this system does not say where
    a folder went)."""
    log(f"polling every {interval}s over {len(roots)} root(s)")
    judge = aht.WatchJudge()
    next_look = time.time() + aht.WATCH_LOOK_SECONDS
    while True:
        time.sleep(interval)
        a = judge.args()
        if a is not None or time.time() >= next_look:
            runner.run()                      # with the walk
            judge.ran()
            next_look = time.time() + aht.WATCH_LOOK_SECONDS
            if once:
                return 0


def run_inotify(roots, runner, debounce, max_watches, once=False):
    ino = Inotify()
    pruned = aht.prune_dirs()
    added, overflowed = 0, False
    try:
        for root in roots:
            for d in walk_dirs(root, pruned):
                if added >= max_watches:
                    overflowed = True
                    break
                if ino.add(d):
                    added += 1
            if overflowed:
                break
    except OSError as e:
        if e.errno == errno.ENOSPC:
            log("inotify watch limit reached (see /proc/sys/fs/inotify/"
                "max_user_watches) — falling back to polling")
            ino.close()
            return run_poll(roots, runner, max(10.0, debounce * 5), once)
        raise
    if overflowed:
        log(f"watch budget {max_watches} exhausted — falling back to polling")
        ino.close()
        return run_poll(roots, runner, max(10.0, debounce * 5), once)

    log(f"inotify watching {added} director(ies) under {len(roots)} root(s), "
        f"quiet moment {debounce}s")
    poller = select.poll()
    poller.register(ino.fd, select.POLLIN)
    judge = aht.WatchJudge(scan_new=True)
    deadline = first = None              # when the quiet moment ends
    moved_from = {}                      # cookie -> the folder as it was named
    next_look = time.time() + aht.WATCH_LOOK_SECONDS

    while True:
        due = next_look if deadline is None else min(deadline, next_look)
        events = poller.poll(max(0.0, due - time.time()) * 1000)
        now = time.time()
        if events:
            for wd, mask, cookie, name in ino.read_events():
                if mask & IN_Q_OVERFLOW:
                    log("inotify queue overflowed — the roots are walked")
                    judge.lost()
                    first = first or now
                    deadline = min(now + debounce, first + max(debounce, 1.5))
                    continue
                if mask & IN_IGNORED:
                    ino.drop(wd)
                    continue
                base = ino.wd_to_path.get(wd)
                if base is None:
                    continue
                path = os.path.join(base, name) if name else base
                if not mask & IN_ISDIR:
                    # files: only a marker or a .git file that appears matters
                    if not mask & (IN_CREATE | IN_MOVED_TO) or name != ".git":
                        if mask & (IN_MOVE_SELF | IN_DELETE_SELF):
                            first = first or now    # a watched folder went: is a project gone?
                            deadline = min(now + debounce, first + max(debounce, 1.5))
                        continue
                    judge.added(path)
                elif mask & IN_MOVED_FROM:
                    moved_from[cookie] = path
                elif mask & IN_MOVED_TO:
                    old = moved_from.pop(cookie, None)
                    if old:
                        judge.renamed(old, path)
                    else:
                        judge.added(path)           # it came from outside the roots
                elif mask & IN_CREATE:
                    judge.added(path)
                elif mask & IN_DELETE:
                    judge.removed(path)
                if mask & IN_ISDIR and (mask & (IN_CREATE | IN_MOVED_TO)):
                    # a directory appeared: watch it and everything under it
                    # (a renamed one: under its new name), otherwise a folder
                    # pasted in one shot would be invisible
                    if not name.startswith(".") and name not in pruned:
                        try:
                            for d in walk_dirs(path, pruned):
                                if len(ino.wd_to_path) >= max_watches:
                                    break
                                ino.add(d)
                        except OSError:
                            pass
                first = first or now
                deadline = min(now + debounce, first + max(debounce, 1.5))
            continue
        a = None
        if deadline is not None and now >= deadline:
            deadline = first = None
            moved_from.clear()           # what left the roots: the judge sees a project gone
            a = judge.args()
        if a is None and now >= next_look:
            a = ["--quick"]              # the regular look: aht's periodic work starts from it
        if a is not None:
            runner.run(a)
            judge.ran()
            next_look = time.time() + aht.WATCH_LOOK_SECONDS
            # the reconcile may have renamed folders; make sure their new
            # locations are watched too (not after a look that found
            # everything in place: that would walk the roots every time)
            try:
                for root in (roots if a != ["--quick"] else []):
                    for d in walk_dirs(root, pruned):
                        if len(ino.wd_to_path) >= max_watches:
                            break
                        ino.add(d)
            except OSError:
                pass
            if once:
                ino.close()
                return 0


# --------------------------------------------------------------------------- #

def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="aht-watcher",
        description="Watch project roots and relink Claude history on move/rename/copy.")
    ap.add_argument("roots", nargs="*",
                    help="directories to watch (default: the configured watch_roots)")
    ap.add_argument("--aht", help="path to aht.py (default: auto-detect)")
    ap.add_argument("--python", default=sys.executable or "python3",
                    help="interpreter used to run aht.py")
    ap.add_argument("--poll", action="store_true", help="force the polling backend")
    ap.add_argument("--poll-interval", type=float, default=15.0)
    ap.add_argument("--debounce", type=float, default=None,
                    help="seconds of quiet before reconciling (default: config)")
    ap.add_argument("--max-watches", type=int, default=8192,
                    help="inotify watch budget before falling back to polling")
    ap.add_argument("--no-startup-scan", action="store_true",
                    help="skip the reconcile that catches changes made while off")
    ap.add_argument("--once", action="store_true",
                    help="handle one batch and exit (used by the tests)")
    args = ap.parse_args(argv)

    global CORE
    CORE = Path(args.aht).expanduser().resolve() if args.aht else _find_core()
    _import_core(CORE)

    roots = [os.path.realpath(r) for r in (args.roots or aht.watch_roots_config())]
    missing = [r for r in roots if not os.path.isdir(r)]
    roots = [r for r in roots if os.path.isdir(r)]
    for m in missing:
        log(f"root does not exist, skipping: {m}")
    if not roots:
        log("no existing roots to watch — set them with: aht config "
            "--set watch_roots=~/code,~/Documents")
        return 2

    debounce = args.debounce
    if debounce is None:
        try:
            debounce = float(aht.cfg_get("debounce_seconds", 0.3))
        except Exception:
            debounce = 0.3

    runner = Runner(CORE, args.python, roots, [])
    log(f"starting (core={CORE}, python={args.python})")
    if not args.no_startup_scan:
        runner.run()          # catch anything that moved while we were not running

    try:
        if args.poll:
            return run_poll(roots, runner, args.poll_interval, args.once)
        if not sys.platform.startswith("linux"):
            log("not Linux — using the polling backend")
            return run_poll(roots, runner, args.poll_interval, args.once)
        return run_inotify(roots, runner, debounce, args.max_watches, args.once)
    except KeyboardInterrupt:
        log("stopped")
        return 0


if __name__ == "__main__":
    sys.exit(main())
