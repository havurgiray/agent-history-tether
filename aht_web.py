#!/usr/bin/env python3
"""aht's window on Windows and Linux: a page the aht core serves to this
computer only, shown in an app window of the browser (Edge or Chrome with
--app, else the default browser).  The Mac has its own window (aht.app).

The page is a FRONT-END like the Mac app: every action runs one of the same
`aht … --json` commands, so the window, the tray, the terminal and the Mac
app can never disagree.

Who may use it: the server listens on 127.0.0.1 only, and on Linux it
refuses connections made by another account of this computer.  The browser
gets in with a one-time launch code (valid two minutes, used once), which
trades for a session cookie (HttpOnly, SameSite=Strict) and a key that comes
after # in the address the page is sent to (that part never reaches a
server, so other servers on 127.0.0.1, which get the cookie too, never see
it).  A browser that has a session keeps it when it opens another window.
Every API request needs the cookie, the key in the header X-AHT (which
a page of another site cannot send without a preflight this server never
answers), and Host and Origin naming this server.  Only the commands in
COMMANDS run.  A second `aht window` asks the running server for a fresh
launch code through a secret in ~/.aht/run/window.json, which only this user
can read.

    aht window              open the window (start the server if needed)
    aht window --no-open    serve, print the address to open
    aht window --selftest   start, check the doors and one command, stop
"""
import json
import os
import secrets
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import aht

IDLE_EXIT = 15 * 60                     # seconds without a request, then the server stops
LAUNCH_TTL = 120                        # seconds a launch code is good for
JOB_KEEP = 600                          # seconds a finished job's answer is kept

# the commands the window may run (Mac-only ones such as tab-names and
# workspace stay out; so do install, uninstall, hook and the far end of a
# handover)
COMMANDS = {
    "status", "config", "projects", "sessions", "search", "journal", "changes", "undo",
    "checkpoint", "rules", "secrets", "report", "share", "tidy", "loose-ends", "board",
    "remote", "handover", "reclaim", "mirror", "resume-here", "switch", "relays", "second-opinion",
    "night-shift", "backup", "restore", "icons", "backends", "adopt", "setup", "update",
    "getting-started", "doctor", "reconcile", "reload", "version", "notices", "limits",
    "logs", "checkup", "forget", "orphans", "prune", "guide", "bind", "autostart",
}


def _own_dirs() -> list:
    """Where aht's page and guide are: inside the exe (PyInstaller), then next
    to this file.  Never the current folder, which can be any project's."""
    frozen = getattr(sys, "_MEIPASS", None)
    return ([Path(frozen)] if frozen else []) + [Path(__file__).resolve().parent]


def web_dir() -> Path:
    for d in _own_dirs():
        if (d / "web").is_dir():
            return d / "web"
    return Path(__file__).resolve().parent / "web"


def guide_file() -> Path:
    for d in _own_dirs():
        if (d / "GUIDE.md").is_file():
            return d / "GUIDE.md"
    return Path(__file__).resolve().parent / "GUIDE.md"


def cli_prefix() -> list:
    """How to run the aht command from here: aht.exe (or aht_main.py) on
    Windows, which sets up the Windows layer first; aht.py elsewhere."""
    if os.name == "nt":
        try:
            import winlayer
            return winlayer.self_cmd()
        except ImportError:
            pass
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, str(Path(aht.__file__).resolve())]


def state_path() -> Path:
    return aht.aht_home() / "run" / "window.json"


def _private_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".new")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(data, fh)
    os.replace(tmp, path)


# ---- whose socket is it (Linux) ---------------------------------------------- #

PROC_TCP = ("/proc/net/tcp", "/proc/net/tcp6")


def _proc_addr(text: str) -> tuple:
    """'0100007F:1F90', as /proc/net/tcp writes it -> ('127.0.0.1', 8080)."""
    h, _, port = text.partition(":")
    raw = b"".join(struct.pack("=I", int(h[i:i + 8], 16)) for i in range(0, len(h), 8))
    host = socket.inet_ntop(socket.AF_INET if len(raw) == 4 else socket.AF_INET6, raw)
    if host.startswith("::ffff:") and "." in host:      # IPv4 through an IPv6 socket
        host = host[7:]
    return host, int(port, 16)


def socket_owners(local: tuple, remote: tuple = None) -> set:
    """The accounts (uids) whose TCP sockets sit at `local` and talk to
    `remote`, or listen at `local`'s port when `remote` is None.  Empty when
    /proc/net/tcp cannot be read (not Linux)."""
    uids = set()
    tail = ":%04X" % local[1]
    for name in PROC_TCP:
        try:
            with open(name) as fh:
                rows = fh.read().splitlines()[1:]
        except OSError:
            continue
        for row in rows:
            f = row.split()
            if len(f) < 8 or not f[1].endswith(tail) or f[3] == "06":   # TIME_WAIT: no owner
                continue
            try:
                if remote is None:
                    hit = f[3] == "0A"                                  # listening
                else:
                    hit = _proc_addr(f[1]) == tuple(local) and _proc_addr(f[2]) == tuple(remote)
                if hit:
                    uids.add(int(f[7]))
            except (ValueError, OSError, struct.error):
                continue
    return uids


def _others(uids: set) -> set:
    """The uids in `uids` that are not this user's."""
    return uids - {os.getuid()} if hasattr(os, "getuid") else set()


def peer_ok(client: tuple, port: int) -> bool:
    """False when another account of this computer made this connection: its
    end of it, `client`, belongs to another uid.  True when that cannot be
    told."""
    return not _others(socket_owners(client[:2], ("127.0.0.1", port)))


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int = 0):
        super().__init__(("127.0.0.1", port), Handler)
        self.port = self.server_address[1]
        self.control = secrets.token_urlsafe(32)        # for a second `aht window`
        self.launch = {}                                # launch code -> expiry
        self.sessions = {}                              # cookie let in -> its page's key
        self.jobs = {}                                  # id -> job
        self.last = time.time()
        self.lock = threading.Lock()
        self.prefix = cli_prefix()

    def verify_request(self, request, client_address) -> bool:
        # Linux: another account could read the launch code off the browser's
        # command line; its connections are closed unanswered
        return not sys.platform.startswith("linux") or peer_ok(client_address, self.port)

    def origin(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def new_launch(self) -> str:
        code = secrets.token_urlsafe(24)
        with self.lock:
            now = time.time()
            self.launch = {c: t for c, t in self.launch.items() if t > now}
            self.launch[code] = now + LAUNCH_TTL
        return code

    def url(self) -> str:
        return f"{self.origin()}/open?code={self.new_launch()}"

    def run(self, args: list, timeout: float = 600) -> dict:
        """One aht command -> {ok, code, out, err, json}."""
        try:
            r = subprocess.run(self.prefix + args, capture_output=True, text=True,
                               timeout=timeout, encoding="utf-8", errors="replace",
                               **_no_window())
            return _answer(r.returncode, r.stdout, r.stderr)
        except subprocess.TimeoutExpired:
            return _answer(124, "", f"aht {args[0]} took longer than {int(timeout)} s")
        except OSError as e:
            return _answer(127, "", str(e))

    def start(self, args: list, follow: str = None) -> str:
        jid = secrets.token_hex(8)
        job = {"args": args, "follow": follow, "done": False, "answer": None,
               "started": time.time()}

        def work():
            job["answer"] = self.run(args, timeout=6 * 3600)
            job["done"] = True
            job["ended"] = time.time()
            if follow:                                  # its progress is no longer asked for
                try:
                    os.unlink(follow)
                except OSError:
                    pass
        with self.lock:
            now = time.time()
            self.jobs = {k: j for k, j in self.jobs.items()
                         if not j["done"] or now - j.get("ended", now) < JOB_KEEP}
            self.jobs[jid] = job
        threading.Thread(target=work, daemon=True).start()
        return jid


def _no_window() -> dict:
    """On Windows, a command run from the window opens no console of its own."""
    return {"creationflags": 0x08000000} if os.name == "nt" else {}


def _answer(code: int, out: str, err: str) -> dict:
    parsed = None
    text = (out or "").strip()
    if text[:1] in "{[":
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
    return {"ok": code == 0, "code": code, "out": out[-200000:], "err": (err or "")[-20000:],
            "json": parsed}


TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
         ".ico": "image/x-icon"}

CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")


class Handler(BaseHTTPRequestHandler):
    server: Server
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *a):                     # quiet: aht's own log has what matters
        pass

    # ---- the doors ----

    def _host_ok(self) -> bool:
        return self.headers.get("Host") == f"127.0.0.1:{self.server.port}"

    def _origin_ok(self) -> bool:
        o = self.headers.get("Origin")
        return o is None or o == self.server.origin()

    def _cookie(self) -> str:
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "aht":
                return v
        return ""

    def _let_in(self) -> bool:
        return self._cookie() in self.server.sessions

    def _key_ok(self) -> bool:
        """The header X-AHT holds the key of this cookie's page."""
        want = self.server.sessions.get(self._cookie())
        given = (self.headers.get("X-AHT") or "").encode("utf-8", "replace")
        return bool(want) and secrets.compare_digest(given, want.encode("utf-8"))

    def _send(self, status: int, body: bytes, ctype: str = "application/json",
              extra: dict = None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        if ctype.startswith("text/html"):
            self.send_header("Content-Security-Policy", CSP)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, obj) -> None:
        self._send(status, json.dumps(obj).encode("utf-8"))

    def _deny(self, why: str) -> None:
        self._send(403, ("aht: " + why + "\nOpen the window from aht's tray icon, or run "
                         "`aht window`.\n").encode("utf-8"), "text/plain; charset=utf-8")

    # ---- GET ----

    def do_GET(self):
        if not self._host_ok():
            return self._deny("this address is not aht's")
        u = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path == "/open":
            code = (q.get("code") or [""])[0]
            with self.server.lock:
                ok = self.server.launch.pop(code, 0) > time.time()
            if not ok:
                return self._deny("this link was used already or is too old")
            # a browser let in before keeps its cookie and key: it has one
            # cookie for all its windows, so a new one would shut the others
            with self.server.lock:
                cookie = self._cookie()
                key = self.server.sessions.get(cookie)
                if not key:
                    cookie, key = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                    self.server.sessions[cookie] = key
            self.server.last = time.time()
            return self._send(302, b"", "text/plain", {
                "Location": "/#k=" + key,
                "Set-Cookie": f"aht={cookie}; HttpOnly; SameSite=Strict; Path=/"})
        if u.path == "/launch":                             # a second `aht window`
            given = (q.get("control") or [""])[0].encode("utf-8", "replace")
            if not secrets.compare_digest(given, self.server.control.encode("utf-8")):
                return self._deny("wrong key")
            self.server.last = time.time()
            return self._json(200, {"url": self.server.url()})
        if not self._let_in():
            return self._deny("not opened by aht")
        if u.path.startswith("/api/"):
            if not self._key_ok() or not self._origin_ok():
                return self._deny("not from aht's window")
            self.server.last = time.time()
            return self._api_get(u.path, q)
        self.server.last = time.time()
        name = "index.html" if u.path in ("/", "/index.html") else u.path.lstrip("/")
        f = (web_dir() / name).resolve()
        if web_dir().resolve() not in f.parents or not f.is_file():
            return self._send(404, b"not found", "text/plain")
        return self._send(200, f.read_bytes(), TYPES.get(f.suffix, "application/octet-stream"))

    def _api_get(self, path: str, q: dict):
        if path == "/api/ping":
            return self._json(200, {"ok": True, "version": aht.VERSION, "platform": sys.platform})
        if path == "/api/job":
            job = self.server.jobs.get((q.get("id") or [""])[0])
            if job is None:
                return self._json(404, {"error": "no such job"})
            progress = None
            if job.get("follow"):
                try:
                    progress = json.loads(Path(job["follow"]).read_text())
                except Exception:
                    progress = None
            return self._json(200, {"done": job["done"], "answer": job["answer"],
                                    "progress": progress})
        if path == "/api/guide":
            try:
                text = guide_file().read_text(encoding="utf-8")
            except OSError:
                text = "# aht guide\n\nThe guide is not next to this copy of aht."
            return self._json(200, {"text": text})
        return self._json(404, {"error": "unknown"})

    # ---- POST ----

    def do_POST(self):
        if not self._host_ok():
            return self._deny("this address is not aht's")
        if not self._let_in():
            return self._deny("not opened by aht")
        if not self._key_ok() or not self._origin_ok():
            return self._deny("not from aht's window")
        self.server.last = time.time()
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(min(n, 1 << 20)) or b"{}")
        except ValueError:
            return self._json(400, {"error": "not JSON"})
        path = urllib.parse.urlsplit(self.path).path
        if path in ("/api/run", "/api/start"):
            args = body.get("args")
            if not (isinstance(args, list) and args and all(isinstance(a, str) for a in args)):
                return self._json(400, {"error": "args: a list of strings"})
            if args[0] not in COMMANDS:
                return self._json(403, {"error": f"the window does not run `aht {args[0]}`"})
            if path == "/api/run":
                return self._json(200, self.server.run(args))
            follow = body.get("follow")
            if follow:
                follow = str(aht.aht_home() / "run" / ("window-" + secrets.token_hex(6) + ".json"))
                args = args + ["--status-file", follow]
            return self._json(200, {"job": self.server.start(args, follow)})
        if path == "/api/reveal":
            return self._json(200, {"ok": reveal(str(body.get("path") or ""))})
        if path == "/api/pick-folder":
            return self._json(200, pick_folder(str(body.get("prompt") or "")))
        if path == "/api/open-url":
            url = str(body.get("url") or "")
            if not url.startswith("https://"):
                return self._json(400, {"error": "only https links"})
            return self._json(200, {"ok": open_url(url)})
        return self._json(404, {"error": "unknown"})

    do_HEAD = do_GET


# ---- the desktop around the window ------------------------------------------ #

def reveal(path: str) -> bool:
    """Show a folder in Explorer or the file manager."""
    if not path or not os.path.exists(path):
        return False
    try:
        quiet = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                 "stderr": subprocess.DEVNULL}
        if os.name == "nt":
            subprocess.Popen(["explorer", path], **quiet)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path], **quiet)
        else:
            subprocess.Popen(["xdg-open", path], start_new_session=True, **quiet)
        return True
    except OSError:
        return False


def open_url(url: str) -> bool:
    import webbrowser
    try:
        return bool(webbrowser.open(url))
    except Exception:
        return False


def _raise_dialog(proc) -> None:
    """Windows: bring the folder chooser that `proc` shows in front of aht's
    window.  Windows lets a process take the front only while it starts or
    right after the user used it, and the click went to the browser, so the
    chooser opened behind the window.  For a moment the server shares the
    input of the window in front (the one just clicked), which lets it hand
    the front on.  When that fails, the chooser stays where Windows put it."""
    try:
        import ctypes
        from ctypes import wintypes
        u, k = ctypes.WinDLL("user32"), ctypes.WinDLL("kernel32")
        H, DW = wintypes.HWND, wintypes.DWORD
        EACH = ctypes.WINFUNCTYPE(wintypes.BOOL, H, wintypes.LPARAM)
        u.EnumWindows.argtypes = [EACH, wintypes.LPARAM]
        u.GetWindowThreadProcessId.argtypes = [H, ctypes.POINTER(DW)]
        u.GetWindowThreadProcessId.restype = DW
        u.IsWindowVisible.argtypes = [H]
        u.GetClassNameW.argtypes = [H, wintypes.LPWSTR, ctypes.c_int]
        u.GetForegroundWindow.restype = H
        u.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), H, wintypes.UINT,
                                   wintypes.UINT, wintypes.UINT]
        u.AttachThreadInput.argtypes = [DW, DW, wintypes.BOOL]
        u.BringWindowToTop.argtypes = [H]
        u.SetForegroundWindow.argtypes = [H]
        u.SetWindowPos.argtypes = [H, H, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, wintypes.UINT]
        k.GetCurrentThreadId.restype = DW
        found = []

        def each(hwnd, _):
            pid = DW()
            u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == proc.pid and u.IsWindowVisible(hwnd):
                name = ctypes.create_unicode_buffer(64)
                u.GetClassNameW(hwnd, name, 64)
                if name.value == "#32770":                  # a dialog box
                    found.append(hwnd)
                    return False
            return True
        each_cb = EACH(each)
        end = time.time() + 30                              # aht can be slow to start
        while not found and proc.poll() is None and time.time() < end:
            u.EnumWindows(each_cb, 0)
            if not found:
                time.sleep(0.1)
        if not found:
            return
        dlg, front = found[0], u.GetForegroundWindow()
        if front == dlg:
            return
        them = u.GetWindowThreadProcessId(front, None) if front else 0
        me = k.GetCurrentThreadId()
        u.PeekMessageW(ctypes.byref(wintypes.MSG()), None, 0, 0, 0)   # this thread gets a queue
        joined = bool(them) and them != me and bool(u.AttachThreadInput(me, them, True))
        try:
            u.BringWindowToTop(dlg)
            u.SetForegroundWindow(dlg)
        finally:
            if joined:
                u.AttachThreadInput(me, them, False)
        if u.GetForegroundWindow() != dlg:
            # not in front: then at least above the window
            keep = 0x0001 | 0x0002 | 0x0010                 # no resize, no move, no focus
            u.SetWindowPos(dlg, H(-1), 0, 0, 0, 0, keep)    # topmost
            u.SetWindowPos(dlg, H(-2), 0, 0, 0, 0, keep)    # and back, but above it
    except Exception:
        pass


# Windows: the shell's folder chooser (SHBrowseForFolder), a tree with a
# Folder: field to type or paste a path in (BIF_RETURNONLYFSDIRS, EDITBOX,
# VALIDATE, NEWDIALOGSTYLE).  aht shows it itself, in a process of its own
# (`aht _pick-folder`, which windows/src/aht_main.py hands to
# pick_folder_here), so the window's server can bring it to the front.  It
# gives the folder chosen in the tree when what was typed is no folder, so a
# callback hears of that.  It answers "+folder", "-" for Cancel, or "?what": a
# path that is no folder, or a place such as This PC.

def _typed_answer(typed: str, expand=None) -> str:
    """The chooser's answer for what was typed in its Folder: field: a path
    pasted in quotes, or with %VARIABLES% in it, is a folder too."""
    t = typed.strip().strip('"').strip()
    t = expand(t) if expand else t
    full = t.startswith("\\\\") or (len(t) > 2 and t[1] == ":" and t[2] in "\\/")
    return "+" + os.path.abspath(t) if full and os.path.isdir(t) else "?" + typed


def pick_folder_here(argv=None) -> int:
    """`aht _pick-folder` (Windows): show the folder chooser with the prompt
    in AHT_PROMPT (or the first argument) and write its answer to stdout."""
    import ctypes
    from ctypes import wintypes
    prompt = (argv or [""])[0] or os.environ.get("AHT_PROMPT") or "Choose a folder"
    sh, ole, k = ctypes.WinDLL("shell32"), ctypes.WinDLL("ole32"), ctypes.WinDLL("kernel32")
    BACK = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HWND, wintypes.UINT, wintypes.LPARAM,
                              wintypes.LPARAM)

    class Info(ctypes.Structure):                       # BROWSEINFOW
        _fields_ = [("owner", wintypes.HWND), ("root", ctypes.c_void_p),
                    ("name", wintypes.LPWSTR), ("title", wintypes.LPCWSTR),
                    ("flags", wintypes.UINT), ("back", BACK), ("param", wintypes.LPARAM),
                    ("image", ctypes.c_int)]
    sh.SHBrowseForFolderW.argtypes = [ctypes.POINTER(Info)]
    sh.SHBrowseForFolderW.restype = ctypes.c_void_p
    sh.SHGetPathFromIDListEx.argtypes = [ctypes.c_void_p, wintypes.LPWSTR, wintypes.DWORD,
                                         wintypes.DWORD]
    sh.SHGetNameFromIDList.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                       ctypes.POINTER(ctypes.c_void_p)]
    sh.SHGetNameFromIDList.restype = ctypes.c_long
    ole.OleInitialize.argtypes = [ctypes.c_void_p]
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    k.ExpandEnvironmentStringsW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    k.ExpandEnvironmentStringsW.restype = wintypes.DWORD
    typed = []

    def told(hwnd, msg, lparam, data):
        # what was typed in Folder: when it is no folder there
        # (BFFM_VALIDATEFAILEDW); the chooser closes
        if msg == 4 and lparam:
            typed.append(ctypes.wstring_at(lparam))
        return 0

    def expand(text):
        n = k.ExpandEnvironmentStringsW(text, None, 0)
        buf = ctypes.create_unicode_buffer(max(n, 1))
        return buf.value if n and k.ExpandEnvironmentStringsW(text, buf, n) else text
    back = BACK(told)                                   # kept alive while the chooser shows
    ole.OleInitialize(None)                             # the new dialog style needs OLE
    name = ctypes.create_unicode_buffer(260)
    info = Info(name=ctypes.cast(name, wintypes.LPWSTR), title=prompt, flags=0x71, back=back)
    p = sh.SHBrowseForFolderW(ctypes.byref(info))
    got = "-"
    if p:                                               # a folder on a disk, or a place such as This PC
        path = ctypes.create_unicode_buffer(32768)
        shown = ctypes.c_void_p()
        if sh.SHGetPathFromIDListEx(p, path, len(path), 0):
            got = "+" + path.value
        elif sh.SHGetNameFromIDList(p, 0, ctypes.byref(shown)) == 0 and shown.value:
            got = "?" + ctypes.wstring_at(shown.value)
            ole.CoTaskMemFree(shown)
        else:
            got = "?"
        ole.CoTaskMemFree(p)
    if typed:
        got = _typed_answer(typed[-1], expand)
    sys.stdout.buffer.write(got.encode("utf-8"))
    sys.stdout.flush()
    return 0


def _choosers(prompt: str, plat: str) -> list:
    """The folder choosers to try on a Mac or Linux: [(kind, command)]."""
    if plat == "darwin":
        return [("osascript", ["osascript", "-e", "on run argv",
                               "-e", "POSIX path of (choose folder with prompt (item 1 of argv))",
                               "-e", "end run", prompt or "Choose a folder"])]
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return []                                       # no screen to show one on (ssh)
    return [(c[0], c) for c in (
        ["zenity", "--file-selection", "--directory", "--title", prompt or "aht"],
        ["kdialog", "--getexistingdirectory", str(Path.home()), "--title", prompt or "aht"])
        if shutil.which(c[0])]


def _chooser_said(kind: str, code: int, out: str, err: str) -> dict:
    """A folder chooser's answer -> {"path", "chooser": whether it was shown,
    and "not_folder": what it gave when that is no folder}.  No path from a
    chooser that was shown is a Cancel."""
    out = (out or "").lstrip("\ufeff").rstrip("\r\n")
    none, cancel = {"path": "", "chooser": False}, {"path": "", "chooser": True}
    if kind == "windows":                               # pick_folder_here's answer
        if code != 0 or out[:1] not in ("+", "-", "?"):
            return none
        if out[0] != "+":
            return cancel if out[0] == "-" else dict(cancel, not_folder=out[1:])
        given = out[1:]
    elif kind == "osascript":                           # Cancel is error -128
        if code != 0:
            return cancel if "(-128)" in (err or "") else none
        given = out[:-1] if len(out) > 1 and out.endswith("/") else out
    else:                                               # zenity, kdialog: Cancel is 1
        if code == 1 and not any(w in (err or "").lower()
                                 for w in ("open display", "connect to display")):
            return cancel
        if code != 0:
            return none
        given = out
    return {"path": given, "chooser": True} if given and os.path.isdir(given) \
        else dict(cancel, not_folder=given)


def pick_folder(prompt: str, plat: str = None) -> dict:
    """The system's folder chooser -> {"path": the folder chosen or "",
    "chooser": whether one was shown, and "not_folder" when it gave what is
    no folder}.  Cancel ends it; only where no chooser could be shown does
    the window ask for the path as text."""
    plat = plat or sys.platform
    if plat == "win32":
        try:
            # aht itself (pick_folder_here), in a process of its own; the
            # prompt goes in through the environment, whatever it holds
            p = subprocess.Popen(cli_prefix() + ["_pick-folder"],
                                 env=dict(os.environ, AHT_PROMPT=prompt or "Choose a folder"),
                                 stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                                 errors="replace", **_no_window())
        except OSError:
            return {"path": "", "chooser": False}
        _raise_dialog(p)
        try:
            out, _ = p.communicate(timeout=600)
        except subprocess.TimeoutExpired:               # left open: as a Cancel
            p.kill()
            p.communicate()
            return {"path": "", "chooser": True}
        return _chooser_said("windows", p.returncode, out, "")
    for kind, cmd in _choosers(prompt, plat):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        except subprocess.TimeoutExpired:
            return {"path": "", "chooser": True}
        except OSError:
            continue
        said = _chooser_said(kind, r.returncode, r.stdout, r.stderr)
        if said["chooser"]:
            return said
    return {"path": "", "chooser": False}


def app_browser() -> list:
    """A browser that opens a page as an app window (no tabs, no address bar)."""
    if os.name == "nt":
        roots = [os.environ.get(k) for k in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
        for r in filter(None, roots):
            for rel in (r"Microsoft\Edge\Application\msedge.exe",
                        r"Google\Chrome\Application\chrome.exe"):
                p = Path(r) / rel
                if p.is_file():
                    return [str(p)]
        return []
    names = ["microsoft-edge", "microsoft-edge-stable", "google-chrome", "google-chrome-stable",
             "chromium", "chromium-browser", "brave-browser"]
    if sys.platform == "darwin":
        for app in ("Google Chrome", "Microsoft Edge", "Chromium", "Brave Browser"):
            p = Path("/Applications") / f"{app}.app" / "Contents" / "MacOS" / app
            if p.is_file():
                return [str(p)]
        return []
    for n in names:
        if shutil.which(n):
            return [shutil.which(n)]
    return []


def open_window(url: str) -> None:
    if os.environ.get("AHT_WINDOW_LOG"):                 # tests: note it, open nothing
        with open(os.environ["AHT_WINDOW_LOG"], "a") as fh:
            fh.write(url + "\n")
        return
    b = app_browser()
    if b:
        try:
            subprocess.Popen(b + [f"--app={url}", "--window-size=1180,800"],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL,
                             **({"start_new_session": True} if os.name != "nt" else _no_window()))
            return
        except OSError:
            pass
    open_url(url)


# ---- starting, finding, stopping --------------------------------------------- #

# loopback needs no proxy, whatever the environment says
DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def running() -> dict:
    """The server already running for this user, if one answers.  A
    window.json left behind names a port anything may listen on now: the
    control key goes there only while its server lives (on Linux: and the
    port is this user's), and only an answer that opens aht's own page is
    used."""
    try:
        st = json.loads(state_path().read_text())
        port = int(st["port"])
        if not aht._pid_alive(int(st["pid"])) or _others(socket_owners(("127.0.0.1", port))):
            return {}
        url = (f"http://127.0.0.1:{port}/launch?"
               + urllib.parse.urlencode({"control": st["control"]}))
        with DIRECT.open(url, timeout=3) as r:
            got = str(json.loads(r.read().decode())["url"])
        if not got.startswith(f"http://127.0.0.1:{port}/open?code="):
            return {}
        return {"url": got, "port": port}
    except Exception:
        return {}


def _sweep_job_files() -> None:
    """Progress files of jobs whose server stopped before they ended."""
    for f in (aht.aht_home() / "run").glob("window-*.json"):
        try:
            if time.time() - f.stat().st_mtime > 6 * 3600:
                f.unlink()
        except OSError:
            pass


def serve(open_it: bool = True, port: int = 0) -> int:
    old = running()
    if old:
        if open_it:
            open_window(old["url"])
        print(old["url"])
        return 0
    _sweep_job_files()
    # stopped at logout or from a terminal: window.json goes too (below); a
    # hang-up that is ignored (nohup) stays ignored
    for name in ("SIGTERM", "SIGHUP"):
        try:
            sig = getattr(signal, name)
            if name == "SIGHUP" and signal.getsignal(sig) is not signal.SIG_DFL:
                continue
            signal.signal(sig, lambda *a: sys.exit(0))
        except (AttributeError, ValueError, OSError):
            pass
    srv = Server(port)
    _private_write(state_path(), {"pid": os.getpid(), "port": srv.port, "control": srv.control,
                                  "started": time.time()})
    url = srv.url()
    print(url, flush=True)
    aht.log(f"WINDOW serving on 127.0.0.1:{srv.port}")
    if open_it:
        open_window(url)

    def idle():
        while True:
            time.sleep(30)
            busy = any(not j["done"] for j in srv.jobs.values())
            if not busy and time.time() - srv.last > IDLE_EXIT:
                srv.shutdown()
                return
    threading.Thread(target=idle, daemon=True).start()
    try:
        srv.serve_forever(poll_interval=0.5)
    finally:
        try:
            if json.loads(state_path().read_text()).get("pid") == os.getpid():
                state_path().unlink()
        except Exception:
            pass
    return 0


def selftest() -> int:
    """Start a server, knock on every door, run `aht version`, stop."""
    srv = Server(0)
    t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True)
    t.start()
    base = srv.origin()
    fails = []

    def call(path, headers=None, data=None, cookie=None):
        h = {"Host": f"127.0.0.1:{srv.port}"}
        h.update(headers or {})
        if cookie:
            h["Cookie"] = f"aht={cookie}"
        req = urllib.request.Request(base + path, headers=h, method="POST" if data else "GET",
                                     data=json.dumps(data).encode() if data else None)

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        opener = urllib.request.build_opener(NoRedirect, urllib.request.ProxyHandler({}))
        try:
            with opener.open(req, timeout=60) as r:
                return r.status, r.read(), r.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers

    def ck(ok, what):
        print(("  ok   " if ok else "  FAIL ") + what)
        if not ok:
            fails.append(what)

    ck(call("/")[0] == 403, "no cookie: the page stays shut")
    ck(call("/open?code=wrong")[0] == 403, "a wrong launch code is refused")
    url = srv.url()
    code = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["code"][0]
    st, _, hd = call("/open?code=" + code)
    cookie = (hd.get("Set-Cookie") or "").split(";")[0].partition("=")[2]
    where = hd.get("Location") or ""
    key = where.partition("#k=")[2]
    ck(st == 302 and cookie and "HttpOnly" in hd.get("Set-Cookie", ""),
       "the launch code opens the door once, with an HttpOnly cookie")
    ck(where.startswith("/#k=") and len(key) >= 32 and key != cookie,
       "the page's key comes after # in the address, where no server sees it")
    ck(call("/open?code=" + code)[0] == 403, "the same launch code does not work twice")
    st, body, hd = call("/", cookie=cookie)
    ck(st == 200 and b"<html" in body.lower() and "script-src 'self'" in
       (hd.get("Content-Security-Policy") or ""), "the page, with its content policy")
    ck(call("/api/ping", cookie=cookie)[0] == 403, "the API wants the X-AHT header")
    ck(call("/api/ping", {"X-AHT": "1"}, cookie=cookie)[0] == 403,
       "the cookie alone is not enough (other servers on 127.0.0.1 get it too)")
    ck(call("/api/ping", {"X-AHT": secrets.token_urlsafe(32)}, cookie=cookie)[0] == 403,
       "a wrong key is refused")
    ok = {"X-AHT": key}
    ck(call("/api/ping", ok, cookie=cookie)[0] == 200, "the page's key lets it in")
    ck(call("/api/ping", ok, cookie=secrets.token_urlsafe(32))[0] == 403,
       "the key without its cookie is refused")
    # more windows of the same browser: it sends the cookie it has
    again = []
    for _ in range(2):
        code = urllib.parse.parse_qs(urllib.parse.urlsplit(srv.url()).query)["code"][0]
        st, _, hd = call("/open?code=" + code, cookie=cookie)
        again.append(st == 302 and (hd.get("Location") or "").partition("#k=")[2] == key)
    ck(all(again) and call("/api/ping", ok, cookie=cookie)[0] == 200,
       "opening the window again keeps the first window's cookie and key")
    code = urllib.parse.parse_qs(urllib.parse.urlsplit(srv.url()).query)["code"][0]
    st, _, hd = call("/open?code=" + code, cookie=secrets.token_urlsafe(32))
    other = (hd.get("Set-Cookie") or "").split(";")[0].partition("=")[2]
    ck(st == 302 and other and other != cookie
       and (hd.get("Location") or "").partition("#k=")[2] not in ("", key),
       "a cookie aht does not know gets a session of its own")
    ck(call("/api/ping", dict(ok, Origin="https://evil.example"), cookie=cookie)[0] == 403,
       "a page of another site is refused")
    ck(call("/api/ping", dict(ok, Host="localhost.evil.example"), cookie=cookie)[0] == 403,
       "another host name is refused (DNS rebinding)")
    st, body, _ = call("/api/run", ok, {"args": ["install"]}, cookie)
    ck(st == 403, "a command outside the list is refused")
    st, body, _ = call("/api/run", ok, {"args": ["version"]}, cookie)
    ans = json.loads(body or b"{}")
    ck(st == 200 and ans.get("ok") and aht.VERSION in ans.get("out", ""),
       f"aht version runs through the window ({ans.get('out', '').strip()[:60]}"
       f"{ans.get('err', '').strip()[:200]})")
    st, body, _ = call("/api/guide", ok, cookie=cookie)
    ck(st == 200 and b"aht guide" in body, "the guide is there")
    for asset in ("app.js", "app.css"):
        ck(call("/" + asset, cookie=cookie)[0] == 200, f"{asset} is there")
    ck(call("/../aht.py", cookie=cookie)[0] in (403, 404), "nothing outside the page's folder")
    # a project's own web/ and GUIDE.md in the current folder are not aht's
    here = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "web").mkdir()
        (Path(tmp) / "web" / "index.html").write_text("<h1>not aht</h1>")
        (Path(tmp) / "GUIDE.md").write_text("# a project's own guide\n")
        os.chdir(tmp)
        try:
            page, guide = call("/", cookie=cookie)[1], call("/api/guide", ok, cookie=cookie)[1]
        finally:
            os.chdir(here)
        ck(b"not aht" not in page and b"app.js" in page and b"aht guide" in guide,
           "run from a folder with a web/ of its own, the window still shows aht's page")
        # a job's progress file goes when the job is done
        follow = Path(tmp) / "window-selftest.json"
        follow.write_text("{}")
        jid = srv.start(["version"], str(follow))
        for _ in range(600):
            if srv.jobs[jid]["done"]:
                break
            time.sleep(0.1)
        ck(srv.jobs[jid]["done"] and not follow.exists(), "a finished job leaves no progress file")
    # the folder chooser: a folder chosen, Cancel (the window asks nothing
    # more), none shown (it asks for the path as text) and what is no folder.
    # Windows' own is driven on a desktop (windows/tests/vm_desktop.ps1); its
    # answers are read here.  zenity, kdialog and osascript are stand-ins
    # that do what AHT_TEST_CHOOSER says.
    with tempfile.TemporaryDirectory() as tmp:
        cancel = {"path": "", "chooser": True}
        ck(_chooser_said("windows", 0, "+" + tmp, "") == {"path": tmp, "chooser": True}
           and _chooser_said("windows", 0, "-", "") == cancel
           and _chooser_said("windows", 0, "?C:\\nope", "") == dict(cancel, not_folder="C:\\nope")
           and _chooser_said("windows", 0, "?This PC", "") == dict(cancel, not_folder="This PC")
           and _chooser_said("windows", 1, "", "")["chooser"] is False,
           "Windows' chooser: a folder, Cancel, a path that is no folder, none shown")
        # Windows' chooser is aht itself in a process of its own (`aht
        # _pick-folder`), never PowerShell; when it cannot start, the window
        # asks for the path as text
        seen, real_popen = [], subprocess.Popen

        class Chooser:
            pid, returncode = 0, 0

            def __init__(self, cmd, **kw):
                seen.append((cmd, (kw.get("env") or {}).get("AHT_PROMPT")))
                if "fail" in seen[-1][1]:
                    raise OSError("cannot start")

            def poll(self):
                return 0

            def communicate(self, timeout=None):
                return "+" + tmp, ""
        try:
            subprocess.Popen = Chooser
            got = [pick_folder("aht selftest “$(x)”", "win32"), pick_folder("fail", "win32")]
        finally:
            subprocess.Popen = real_popen
        cmd = seen[0][0] if seen else []
        ck(got == [{"path": tmp, "chooser": True}, {"path": "", "chooser": False}]
           and cmd == cli_prefix() + ["_pick-folder"] and seen[0][1] == "aht selftest “$(x)”"
           and not any("powershell" in str(a).lower() for a in cmd),
           f"Windows' chooser runs as `aht _pick-folder`, no PowerShell ({cmd}, {got})")
        tq = '"' + tmp + '"'
        ck(_typed_answer("C:\\no\\such\\folder") == "?C:\\no\\such\\folder"
           and _typed_answer("Documents") == "?Documents"
           and _typed_answer(tq) == ("+" + os.path.abspath(tmp) if os.name == "nt" else "?" + tq)
           and _typed_answer("%X%", lambda t: t.replace("%X%", "C:\\gone")) == "?%X%",
           "what is typed in Windows' chooser: a missing or partial path is no folder")
        if os.name != "nt":
            pick, ran = Path(tmp) / "a folder", Path(tmp) / "ran"
            pick.mkdir()
            bins = {k: Path(tmp) / k for k in ("all", "kdialog", "none")}
            for name, gave, cancelled, failed in (
                    ("zenity", "", "exit 1", "echo 'cannot open display: ' >&2; exit 1"),
                    ("kdialog", "", "exit 1", "exit 134"),
                    ("osascript", "/", "echo 'execution error: User canceled. (-128)' >&2; exit 1",
                     "echo 'execution error: Not authorized. (-1743)' >&2; exit 1")):
                for b in ("all", name):
                    if b in bins:
                        bins[b].mkdir(exist_ok=True)
                        (bins[b] / name).write_text(
                            f'#!/bin/sh\necho {name} >> "$AHT_TEST_RAN"\ncase "$AHT_TEST_CHOOSER" in\n'
                            f'  pick) printf "%s{gave}\\n" "$AHT_TEST_PICK";;\n  cancel) {cancelled};;\n'
                            f'  fail) {failed};;\n  *) echo /no/such/folder;;\nesac\n')
                        (bins[b] / name).chmod(0o755)
            bins["none"].mkdir()
            keep = {k: os.environ.get(k) for k in ("PATH", "DISPLAY", "WAYLAND_DISPLAY", "AHT_TEST_CHOOSER",
                                                   "AHT_TEST_PICK", "AHT_TEST_RAN")}

            def chooser(mode, plat, b="all", display=":9", api=False):
                os.environ.update(PATH=str(bins[b]), DISPLAY=display, WAYLAND_DISPLAY="",
                                  AHT_TEST_CHOOSER=mode, AHT_TEST_PICK=str(pick), AHT_TEST_RAN=str(ran))
                try:
                    ran.write_text("")
                    if api:
                        st, body, _ = call("/api/pick-folder", ok, {"prompt": "aht selftest"}, cookie)
                        got = json.loads(body or b"{}") if st == 200 else {"status": st}
                    else:
                        got = pick_folder("aht selftest", plat)
                    return got, ran.read_text().split()
                finally:
                    for k, v in keep.items():
                        if v is None:
                            os.environ.pop(k, None)
                        else:
                            os.environ[k] = v
            picked = {"path": str(pick), "chooser": True}
            for plat, first in (("linux", "zenity"), ("darwin", "osascript")):
                got = [chooser(m, plat) for m in ("pick", "cancel", "fail", "nofolder")]
                ck(got[0] == (picked, [first]) and got[1] == (cancel, [first]),
                   f"{first}: the folder chosen; Cancel ends it, with no second box ({got[:2]})")
                ck(got[2][0] == {"path": "", "chooser": False}
                   and got[3][0] == dict(cancel, not_folder="/no/such/folder"),
                   f"{first}: none shown, so the window asks; what is no folder is told ({got[2:]})")
                got = chooser("pick", plat, "none")
                ck(got == ({"path": "", "chooser": False}, []), f"no {first}: none shown ({got})")
            got = [chooser(m, "linux", "kdialog") for m in ("pick", "cancel")]
            ck(got == [(picked, ["kdialog"]), (cancel, ["kdialog"])],
               f"kdialog where there is no zenity: chosen, cancelled ({got})")
            got = chooser("pick", "linux", display="")
            ck(got == ({"path": "", "chooser": False}, []),
               f"no screen (ssh): no chooser is started, the window asks ({got})")
            here_plat = "darwin" if sys.platform == "darwin" else "linux"
            got = [chooser(m, here_plat, api=True)[0] for m in ("pick", "cancel")]
            ck(got == [picked, cancel], f"/api/pick-folder answers with the path and the chooser ({got})")
    srv.shutdown()
    # Linux: connections another account makes are refused (read from
    # /proc/net/tcp; here from a made-up one)
    if hasattr(os, "getuid"):
        global PROC_TCP
        saved, me, them = PROC_TCP, os.getuid(), os.getuid() + 1

        def hexed(host, port):
            raw = socket.inet_pton(socket.AF_INET6 if ":" in host else socket.AF_INET, host)
            return "".join("%08X" % struct.unpack("=I", raw[i:i + 4])[0]
                           for i in range(0, len(raw), 4)) + ":%04X" % port

        def row(n, lo, rem, state, uid):
            return f"{n:4}: {hexed(*lo)} {hexed(*rem)} {state} 00000000:00000000 00:00000000 " \
                   f"00000000 {uid:5}        0 {1000 + n} 1 0000000000000000 20 4 30 10 -1\n"
        head = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when " \
               "retrnsmt   uid  timeout inode\n"
        srv_at = ("127.0.0.1", 8080)
        with tempfile.TemporaryDirectory() as tmp:
            t4, t6 = Path(tmp) / "tcp", Path(tmp) / "tcp6"
            t4.write_text(head + row(0, srv_at, ("0.0.0.0", 0), "0A", me)
                          + row(1, ("127.0.0.1", 50000), srv_at, "01", me)
                          + row(2, srv_at, ("127.0.0.1", 50000), "01", me)
                          + row(3, ("127.0.0.1", 50001), srv_at, "01", them)
                          + row(4, srv_at, ("127.0.0.1", 50001), "01", me)
                          + row(5, ("127.0.0.1", 50003), srv_at, "06", 0))
            t6.write_text(head + row(0, ("::ffff:127.0.0.1", 50002), ("::ffff:127.0.0.1", 8080),
                                     "01", them))
            try:
                PROC_TCP = (str(t4), str(t6))
                ck(peer_ok(("127.0.0.1", 50000), 8080), "a connection this user made is let in")
                ck(not peer_ok(("127.0.0.1", 50001), 8080),
                   "a connection another account made is refused")
                ck(not peer_ok(("127.0.0.1", 50002), 8080),
                   "also through an IPv6 socket")
                ck(peer_ok(("127.0.0.1", 50003), 8080) and peer_ok(("127.0.0.1", 50009), 8080),
                   "a connection whose owner cannot be told is let in")
                ck(socket_owners(srv_at) == {me}, "the port's listener is found")
                PROC_TCP = (str(Path(tmp) / "nothing"),)
                ck(peer_ok(("127.0.0.1", 50001), 8080), "without /proc/net/tcp, nothing is refused")
            finally:
                PROC_TCP = saved
    print(f"WINDOW SELFTEST {'OK' if not fails else 'FAIL'}")
    return 0 if not fails else 1


def main(args) -> int:
    if getattr(args, "selftest", False):
        return selftest()
    return serve(open_it=not args.no_open, port=args.port or 0)
