#!/usr/bin/env python3
"""
aht platform layer for Windows — the counterpart of the macOS FSEvents
watcher + LaunchAgent and the Linux inotify watcher + systemd user unit.

The shared core (aht.py) is bundled VERBATIM; everything Windows-specific is
patched in over the same seams the core already defines for macOS and Linux:

    ask_dialog()             -> native MessageBox (Yes/No/Cancel, with timeout)
    notify_user()            -> toast notification via PowerShell (best-effort)
    apply_badge()            -> folder icons via desktop.ini (see winbadge.py)
    gui_dialogs_available()  -> True (user32 is always there)
    watcher_status()         -> HKCU Run entry + a named mutex
    _reload_watcher()        -> stop event + relaunch hidden
    hook_installed()         -> recognises the aht.exe hook command
    _default_watch_roots()   -> Desktop/Documents incl. OneDrive redirection

plus three Windows-only commands the core doesn't have:

    aht watch          run the folder watcher in the foreground
    aht install        self-install: autostart watcher + SessionStart hook
    aht uninstall      stop the automation (history is never touched)

fcntl is provided by win_fcntl (msvcrt byte-range locks) — registered in
sys.modules by aht_main.py before the core is imported.
"""
import argparse
import ctypes
import ctypes.wintypes as wintypes
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import aht

FROZEN = bool(getattr(sys, "frozen", False))

CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200

MUTEX_NAME = "Local\\aht-watcher"
TRAY_MUTEX_NAME = "Local\\aht-tray"        # one tray per sign-in
STOP_EVENT_NAME = "Local\\aht-watcher-stop"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "aht-watcher"
# the launcher older versions put in the logon entry; removed where found
VBS_NAME = "aht-watch.vbs"

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_user32 = ctypes.WinDLL("user32", use_last_error=True)

INVALID_HANDLE = wintypes.HANDLE(-1).value
INFINITE = 0xFFFFFFFF
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 0x102
WAIT_FAILED = 0xFFFFFFFF
ERROR_ALREADY_EXISTS = 183
SYNCHRONIZE = 0x00100000
EVENT_MODIFY_STATE = 0x0002
FILE_NOTIFY_CHANGE_FILE_NAME = 0x1
FILE_NOTIFY_CHANGE_DIR_NAME = 0x2

_kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.OpenMutexW.restype = wintypes.HANDLE
_kernel32.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL,
                                   wintypes.LPCWSTR]
_kernel32.CreateEventW.restype = wintypes.HANDLE
_kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.OpenEventW.restype = wintypes.HANDLE
_kernel32.SetEvent.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_kernel32.WaitForSingleObject.restype = wintypes.DWORD
_kernel32.WaitForMultipleObjects.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE),
                                             wintypes.BOOL, wintypes.DWORD]
_kernel32.WaitForMultipleObjects.restype = wintypes.DWORD
_kernel32.FindFirstChangeNotificationW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL,
                                                   wintypes.DWORD]
_kernel32.FindFirstChangeNotificationW.restype = wintypes.HANDLE
_kernel32.FindNextChangeNotification.argtypes = [wintypes.HANDLE]
_kernel32.FindNextChangeNotification.restype = wintypes.BOOL
_kernel32.FindCloseChangeNotification.argtypes = [wintypes.HANDLE]

try:
    _user32.MessageBoxTimeoutW.argtypes = [wintypes.HWND, wintypes.LPCWSTR,
                                           wintypes.LPCWSTR, wintypes.UINT,
                                           wintypes.WORD, wintypes.DWORD]
    _user32.MessageBoxTimeoutW.restype = ctypes.c_int
    _HAVE_MB_TIMEOUT = True
except AttributeError:
    _HAVE_MB_TIMEOUT = False
_user32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                wintypes.UINT]
_user32.MessageBoxW.restype = ctypes.c_int


# --------------------------------------------------------------------------- #
# Self-invocation (works both frozen and as a plain script)
# --------------------------------------------------------------------------- #

def self_cmd(*args) -> list:
    if FROZEN:
        exe = Path(sys.executable)
        if exe.stem.lower() != "aht":
            # running inside a companion exe (the tray): drive the CLI exe
            sibling = exe.with_name("aht.exe")
            if sibling.exists():
                return [str(sibling), *args]
        return [sys.executable, *args]
    return [sys.executable, str(Path(__file__).with_name("aht_main.py")), *args]


def self_cmdline(*args) -> str:
    return subprocess.list2cmdline(self_cmd(*args))


def app_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "aht"


def watcher_log_path() -> Path:
    return aht.aht_home() / "aht-watcher.log"


def enable_dpi_awareness() -> None:
    """Opt into per-monitor DPI awareness BEFORE any window or dialog exists.
    A PyInstaller exe is DPI-unaware by default, so on a scaled display
    (125%/150%…) Windows bitmap-stretches everything it draws — tray icon,
    menus, MessageBoxes all come out blurry.  Falls back through the older
    APIs on old builds; never raises."""
    try:
        _user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        _user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
        if _user32.SetProcessDpiAwarenessContext(
                ctypes.c_void_p(-4)):      # PER_MONITOR_AWARE_V2
            return
    except Exception:
        pass
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)   # PER_MONITOR_AWARE
        return
    except Exception:
        pass
    try:
        _user32.SetProcessDPIAware()
    except Exception:
        pass


def fix_streams() -> None:
    """A console exe launched with CREATE_NO_WINDOW (the hidden watcher) has no
    std handles at all — sys.stdout/stderr are None and the first print would
    crash.  Point them at the watcher log instead.  When a console IS attached,
    just force UTF-8 so the core's ✓/•/→ output survives cp1252 pipes."""
    logf = None
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            if logf is None:
                try:
                    watcher_log_path().parent.mkdir(parents=True, exist_ok=True)
                    logf = open(watcher_log_path(), "a", buffering=1,
                                encoding="utf-8", errors="replace")
                except Exception:
                    logf = open(os.devnull, "w")
            setattr(sys, name, logf)
        else:
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


# --------------------------------------------------------------------------- #
# Seam: dialogs
# --------------------------------------------------------------------------- #

MB_YESNOCANCEL = 0x00000003
MB_ICONQUESTION = 0x00000020
MB_SETFOREGROUND = 0x00010000
MB_TOPMOST = 0x00040000
IDYES, IDNO, IDCANCEL, IDTIMEOUT = 6, 7, 2, 32000


def _ask_windows(message, buttons, default, title, timeout):
    """`buttons` is always [decline, confirm].  MessageBox button captions can't
    be relabelled without a TaskDialog, so the mapping is spelled out in the
    text: Yes = confirm, No = decline, Cancel/close/timeout = "Later" (None),
    matching macOS where dismissing the osascript dialog changes nothing."""
    no, yes = buttons[0], buttons[-1]
    text = f"{message}\n\nYes = {yes}        No = {no}        Cancel = decide later"
    flags = MB_YESNOCANCEL | MB_ICONQUESTION | MB_SETFOREGROUND | MB_TOPMOST
    try:
        if _HAVE_MB_TIMEOUT:
            res = _user32.MessageBoxTimeoutW(None, text, title, flags, 0,
                                             int(max(1, timeout) * 1000))
        else:
            res = _user32.MessageBoxW(None, text, title, flags)
    except Exception:
        return None
    if res == IDYES:
        return yes
    if res == IDNO:
        return no
    return None                                  # cancel / closed / timed out


def ask_dialog(message, buttons, default, title="Agent Project History"):
    forced = os.environ.get("AHT_ASSUME")
    if forced:
        return forced if forced in buttons else None
    return _ask_windows(message, buttons, default, title, aht._dialog_timeout())


def gui_dialogs_available() -> bool:
    return True


# --------------------------------------------------------------------------- #
# Seam: notifications (toast via PowerShell; best-effort, never raises)
# --------------------------------------------------------------------------- #

_TOAST_PS = r"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$texts = $xml.GetElementsByTagName('text')
$texts.Item(0).AppendChild($xml.CreateTextNode($env:AHT_TOAST_TITLE)) | Out-Null
$texts.Item(1).AppendChild($xml.CreateTextNode($env:AHT_TOAST_MSG)) | Out-Null
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('aht').Show($toast)
"""


def notify_user(title, message, info=None):
    try:
        if os.environ.get("AHT_NO_NOTIFY") or not aht.cfg_get("notifications", True):
            return
        # while the tray runs it shows the notice as a balloon of its icon (a
        # toast from an app Windows does not know may never show); a click
        # on it opens aht's window
        run = aht.aht_home() / "run"
        try:
            tray = time.time() - (run / "tray-alive").stat().st_mtime < 60
        except OSError:
            tray = False
        if tray:
            with open(run / "tray-notices.jsonl", "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"title": title, "message": message,
                                     "info": info or {}, "at": time.time()}) + "\n")
            return
        env = dict(os.environ, AHT_TOAST_TITLE=title, AHT_TOAST_MSG=message)
        # title/message travel via env vars so no quoting can break the script
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                        "-WindowStyle", "Hidden", "-Command", _TOAST_PS],
                       capture_output=True, timeout=20, env=env,
                       creationflags=CREATE_NO_WINDOW)
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Seam: folder badges  (desktop.ini + composited .ico — see winbadge.py)
# --------------------------------------------------------------------------- #

def apply_badge(path, marks):
    """Same contract and guards as the core's: best-effort, never raises,
    honours AHT_NO_ICONS and the icons_enabled config."""
    if os.environ.get("AHT_NO_ICONS") or not aht.cfg_get("icons_enabled", True):
        return
    try:
        import winbadge
        winbadge.apply(path, marks)
    except Exception as e:
        aht.log(f"badge failed for {path}: {e}")


# --------------------------------------------------------------------------- #
# Seam: watcher status / reload  (HKCU Run entry + named mutex + stop event)
# --------------------------------------------------------------------------- #

def _run_key_get():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            v, _t = winreg.QueryValueEx(k, RUN_VALUE)
            return v
    except OSError:
        return None


def _run_key_set(cmdline: str) -> None:
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
        winreg.SetValueEx(k, RUN_VALUE, 0, winreg.REG_SZ, cmdline)


def _run_key_delete() -> None:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, RUN_VALUE)
    except OSError:
        pass


def watcher_running() -> bool:
    h = _kernel32.OpenMutexW(SYNCHRONIZE, False, MUTEX_NAME)
    if h:
        _kernel32.CloseHandle(h)
        return True
    return False


def stop_watcher(wait: float = 6.0) -> bool:
    """Signal the running watcher (if any) to exit; wait for the mutex to free."""
    h = _kernel32.OpenEventW(EVENT_MODIFY_STATE, False, STOP_EVENT_NAME)
    if h:
        _kernel32.SetEvent(h)
        _kernel32.CloseHandle(h)
    end = time.time() + wait
    while watcher_running():
        if time.time() >= end:
            return False
        time.sleep(0.2)
    return True


def start_watcher_hidden() -> None:
    try:
        logf = open(watcher_log_path(), "a", encoding="utf-8", errors="replace")
    except Exception:
        logf = subprocess.DEVNULL
    subprocess.Popen(self_cmd("watch"),
                     stdin=subprocess.DEVNULL, stdout=logf, stderr=logf,
                     creationflags=CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP,
                     close_fds=True)


def watcher_status() -> dict:
    st = {"platform": sys.platform, "owner": aht.cfg_get("watcher_owner", "agent"),
          "installed": False, "running": False, "kind": "logon-entry (HKCU Run)",
          "detail": ""}
    try:
        entry = _run_key_get()
        st["installed"] = entry is not None
        st["running"] = watcher_running()
        st["detail"] = entry or ""
    except Exception as e:
        st["detail"] = str(e)
    return st


def _reload_watcher() -> bool:
    """-> whether the watcher was restarted (the core reports it as
    setup's "watcher_reloaded")."""
    if aht.cfg_get("watcher_owner", "agent") == "none":
        print("watching is off (watcher_owner=none) — nothing to reload")
        return False
    stop_watcher()
    start_watcher_hidden()
    print("✓ watcher restarted with the current roots")
    return True


def hook_installed(event: str = "SessionStart") -> bool:
    s = Path.home() / ".claude" / "settings.json"
    try:
        data = json.loads(s.read_text(encoding="utf-8"))
        for group in data.get("hooks", {}).get(event, []):
            for h in group.get("hooks", []):
                if _is_our_hook(h.get("command", "")):
                    return True
    except Exception:
        pass
    return False


def _is_our_hook(cmd: str) -> bool:
    c = (cmd or "").strip().strip('"')
    return "aht.py hook" in c or ("aht" in c.lower() and c.endswith("hook"))


# --------------------------------------------------------------------------- #
# Seam: default roots (the path-shape fixes that used to live here were folded
# into the shared core itself — list_real_dirs depth counting and
# transcript_file_refs separator handling are separator-agnostic in aht.py)
# --------------------------------------------------------------------------- #

def _default_watch_roots():
    """Desktop + Documents like the other platforms, but Windows may have moved
    both under OneDrive (Known Folder redirection), and dev folders often live
    in ~/source (Visual Studio's default) — include whichever exist."""
    home = Path.home()
    cands = [home / "Desktop", home / "Documents"]
    try:
        for od in sorted(home.glob("OneDrive*")):
            if od.is_dir():
                cands += [od / "Desktop", od / "Documents"]
    except Exception:
        pass
    cands += [home / "source", home / "code", home / "src", home / "Projects",
              home / "projects", home / "dev", home / "workspace", home / "git"]
    roots, seen = [], set()
    for i, p in enumerate(cands):
        key = str(p).lower()
        if key in seen:
            continue
        if i < 2 or p.is_dir():       # Desktop/Documents always; extras if present
            seen.add(key)
            roots.append(str(p))
    return roots


# --------------------------------------------------------------------------- #
# The watcher  (FindFirstChangeNotificationW, watching each root's subtree)
# --------------------------------------------------------------------------- #

def _wlog(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] watcher: {msg}"
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        aht.log(f"WATCHER {msg}")
    except Exception:
        pass


class Runner:
    """Run reconcile synchronously.  Synchronous IS the single-flight
    guarantee: no second prompt can appear while one is open."""

    def __init__(self, roots):
        self.roots = list(roots)

    def run(self) -> int:
        cmd = self_cmd("reconcile", "--notify")
        if self.roots:
            cmd += ["--roots"] + self.roots
        t0 = time.time()
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               creationflags=CREATE_NO_WINDOW)
        except Exception as e:
            _wlog(f"reconcile failed to launch: {e}")
            return -1
        dt = time.time() - t0
        if r.returncode != 0:
            _wlog(f"reconcile exited {r.returncode} in {dt:.1f}s: "
                  f"{(r.stderr or '').strip()[:400]}")
        else:
            try:
                d = json.loads(r.stdout or "{}")
                bits = [f"{k}={len(d.get(k, []))}" for k in ("moves", "copies", "news")
                        if d.get(k)]
                _wlog(f"reconcile {' '.join(bits) or 'nothing to do'} ({dt:.1f}s)")
            except Exception:
                _wlog("reconcile ok")
        return r.returncode


def _marker_signature(roots):
    """Cheap fingerprint of 'which marker lives where' — any move, rename,
    copy, new project or deletion changes it (same as the Linux watcher)."""
    try:
        path_to_uuid, _ = aht.find_markers(list(roots))
    except Exception as e:
        _wlog(f"scan failed: {e}")
        return None
    return tuple(sorted(path_to_uuid.items()))


def _run_poll(roots, runner, interval, stop_h, once=False):
    _wlog(f"polling every {interval}s over {len(roots)} root(s)")
    sig = _marker_signature(roots)
    while True:
        if _kernel32.WaitForSingleObject(stop_h, int(interval * 1000)) == WAIT_OBJECT_0:
            _wlog("stopped")
            return 0
        new = _marker_signature(roots)
        if new is not None and new != sig:
            runner.run()
            if once:
                return 0
            sig = _marker_signature(roots)   # re-read: reconcile itself moves things


def _run_notify(roots, runner, debounce, stop_h, once=False):
    handles, watched = [], []
    for r in roots:
        h = _kernel32.FindFirstChangeNotificationW(
            r, True, FILE_NOTIFY_CHANGE_DIR_NAME | FILE_NOTIFY_CHANGE_FILE_NAME)
        if h and h != INVALID_HANDLE:
            handles.append(h)
            watched.append(r)
        else:
            _wlog(f"cannot watch {r} (error {ctypes.get_last_error()})")
    if not handles:
        return _run_poll(roots, runner, 15.0, stop_h, once)

    _wlog(f"watching {len(watched)} root(s) recursively, debounce {debounce}s")
    arr = (wintypes.HANDLE * (1 + len(handles)))(stop_h, *handles)
    deadline = None
    try:
        while True:
            timeout = INFINITE if deadline is None else \
                max(0, int((deadline - time.time()) * 1000))
            res = _kernel32.WaitForMultipleObjects(len(arr), arr, False, timeout)
            now = time.time()
            if res == WAIT_OBJECT_0:                       # stop event
                _wlog("stopped")
                return 0
            if WAIT_OBJECT_0 < res <= WAIT_OBJECT_0 + len(handles):
                idx = res - WAIT_OBJECT_0 - 1
                if not _kernel32.FindNextChangeNotification(handles[idx]):
                    _wlog(f"lost watch on {watched[idx]} — falling back to polling")
                    return _run_poll(roots, runner, 15.0, stop_h, once)
                deadline = now + debounce
                continue
            if res == WAIT_TIMEOUT:
                if deadline is not None and now >= deadline:
                    deadline = None
                    runner.run()
                    if once:
                        return 0
                continue
            _wlog(f"wait failed (error {ctypes.get_last_error()}) — polling instead")
            return _run_poll(roots, runner, 15.0, stop_h, once)
    finally:
        for h in handles:
            _kernel32.FindCloseChangeNotification(h)


def cmd_watch(argv) -> int:
    ap = argparse.ArgumentParser(
        prog="aht watch",
        description="Watch the project roots and relink agent histories on "
                    "move/rename/copy (runs until stopped).")
    ap.add_argument("roots", nargs="*",
                    help="directories to watch (default: the configured watch_roots)")
    ap.add_argument("--poll", action="store_true", help="force the polling backend")
    ap.add_argument("--poll-interval", type=float, default=15.0)
    ap.add_argument("--debounce", type=float, default=None,
                    help="seconds of quiet before reconciling (default: config)")
    ap.add_argument("--no-startup-scan", action="store_true",
                    help="skip the reconcile that catches changes made while off")
    ap.add_argument("--once", action="store_true",
                    help="handle one batch and exit (used by the tests)")
    args = ap.parse_args(argv)

    mutex = _kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        _wlog("another watcher is already running — exiting")
        return 0
    stop_h = _kernel32.CreateEventW(None, True, False, STOP_EVENT_NAME)

    roots = [os.path.realpath(r) for r in (args.roots or aht.watch_roots_config())]
    missing = [r for r in roots if not os.path.isdir(r)]
    roots = [r for r in roots if os.path.isdir(r)]
    for m in missing:
        _wlog(f"root does not exist, skipping: {m}")
    if not roots:
        _wlog("no existing roots to watch — set them with: aht config "
              "--set watch_roots=C:\\Users\\you\\code")
        return 2

    debounce = args.debounce
    if debounce is None:
        try:
            debounce = float(aht.cfg_get("debounce_seconds", 2.0))
        except Exception:
            debounce = 2.0

    runner = Runner(roots)
    _wlog(f"starting ({'frozen exe' if FROZEN else 'script'}: {sys.executable})")
    if not args.no_startup_scan:
        runner.run()          # catch anything that moved while we were not running

    try:
        if args.poll:
            return _run_poll(roots, runner, args.poll_interval, stop_h, args.once)
        return _run_notify(roots, runner, debounce, stop_h, args.once)
    except KeyboardInterrupt:
        _wlog("stopped")
        return 0
    finally:
        if mutex:
            _kernel32.CloseHandle(mutex)


# --------------------------------------------------------------------------- #
# install / uninstall
# --------------------------------------------------------------------------- #

SETTINGS = Path.home() / ".claude" / "settings.json"


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]


def aht_processes(in_dir: Path = None) -> list:
    """This user's other aht.exe and aht-tray.exe processes (the tray, the
    watcher, aht's window), only those started from `in_dir` when given:
    [(pid, exe path)].  Never this process or the aht ones that started it:
    Scoop's `aht` is an aht.exe too, and when it ends, the aht it started
    ends with it (so `aht uninstall` would stop halfway); the same for a
    Repair from the tray.  The walk up stops at the first program that is
    not aht: the parent PID of a process whose parent ended may since have
    gone to another one, such as the tray started at sign-in."""
    k = _kernel32
    k.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    k.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.OpenProcess.restype = wintypes.HANDLE
    k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                             wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    out, procs = [], []
    snap = k.CreateToolhelp32Snapshot(0x2, 0)                 # TH32CS_SNAPPROCESS
    if not snap or snap == INVALID_HANDLE:
        return out
    try:
        e = _PROCESSENTRY32W()
        e.dwSize = ctypes.sizeof(e)
        ok = k.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            procs.append((e.th32ProcessID, e.th32ParentProcessID, e.szExeFile.lower()))
            ok = k.Process32NextW(snap, ctypes.byref(e))
    finally:
        k.CloseHandle(snap)
    ours = ("aht.exe", "aht-tray.exe")
    parent = {pid: ppid for pid, ppid, _name in procs}
    image = {pid: name for pid, _ppid, name in procs}
    mine = {os.getpid()}
    pid = parent.get(os.getpid())
    while pid and pid not in mine and image.get(pid) in ours:   # its parent, theirs, …
        mine.add(pid)
        pid = parent.get(pid)
    for pid, _ppid, name in procs:
        if name not in ours or pid in mine:
            continue
        h = k.OpenProcess(0x1000, False, pid)                 # QUERY_LIMITED_INFORMATION
        if h:
            buf = ctypes.create_unicode_buffer(1024)
            n = wintypes.DWORD(1024)
            if k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                if in_dir is None or _same_dir(str(Path(buf.value).parent), in_dir):
                    out.append((pid, buf.value))
            k.CloseHandle(h)
    return out


def stop_aht_processes(in_dir: Path = None) -> int:
    """End the processes aht_processes() finds; how many there were."""
    k = _kernel32
    k.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    found = aht_processes(in_dir)
    for pid, _exe in found:
        h = k.OpenProcess(0x0001 | SYNCHRONIZE, False, pid)  # TERMINATE
        if h:
            k.TerminateProcess(h, 1)
            k.WaitForSingleObject(h, 3000)
            k.CloseHandle(h)
    return len(found)


def _copy_app(src_dir: Path, dst_dir: Path) -> None:
    """aht.exe, aht-tray.exe and the _internal folder they share."""
    for name in ("aht.exe", "aht-tray.exe"):
        if (src_dir / name).is_file():
            shutil.copy2(src_dir / name, dst_dir / name)
    if (src_dir / "_internal").is_dir():
        shutil.rmtree(dst_dir / "_internal", ignore_errors=True)   # an older version's
        shutil.copytree(src_dir / "_internal", dst_dir / "_internal", dirs_exist_ok=True)


def _install_binary(copy: bool) -> str:
    """Put a stable copy of aht in %LOCALAPPDATA%\\aht so the Run key and the
    hook keep working when the downloaded folder is moved or deleted.
    Returns the command path the autostart entry and hook should reference."""
    if not FROZEN:
        return ""                     # dev mode: reference the script via self_cmd
    if not copy:
        # the path it was started by: Scoop's ...\apps\aht\current stays
        # through `scoop update`, the version folder it leads to does not
        return os.path.abspath(sys.executable)
    src = Path(sys.executable).resolve()
    target = app_dir() / "aht.exe"
    if src == (target.resolve() if target.exists() else target):
        return str(target)
    app_dir().mkdir(parents=True, exist_ok=True)
    stop_watcher()                    # the old watcher may hold the target open,
    stop_aht_processes(app_dir())     # … and the tray or aht's window
    for attempt in range(10):
        try:
            _copy_app(src.parent, app_dir())
            break
        except OSError as e:
            if attempt == 9:
                print(f"⚠ could not copy aht to {app_dir()} ({e}) — "
                      f"using the current location instead")
                return str(src)
            time.sleep(0.5)
    print(f"✓ installed {app_dir()}")
    return str(target)


def installed_in_place() -> bool:
    """aht's installer or Scoop put this aht where it is, and it is used
    there (as with `install --here`): a copy in %LOCALAPPDATA%\\aht would
    outlive Settings > Apps > Uninstall and `scoop uninstall`."""
    if not FROZEN:
        return False
    exe = os.path.abspath(sys.executable)
    if any(Path(exe).parent.glob("unins*.exe")):
        return True
    scoop = (os.environ.get("SCOOP") or str(Path.home() / "scoop"),
             os.environ.get("SCOOP_GLOBAL")
             or os.path.join(os.environ.get("ProgramData") or "C:\\ProgramData", "scoop"))
    return any(os.path.normcase(exe).startswith(
        os.path.normcase(os.path.join(s, "apps", "aht", ""))) for s in scoop)


def _retire_old_copy(exe: str) -> None:
    """aht referenced where it is (its installer, `--here`): the copy an
    earlier `aht install` made in %LOCALAPPDATA%\\aht goes, so no old aht
    keeps running from there or answers `aht` in a terminal.  Its badge
    icon cache (icons\\) stays."""
    old = app_dir()
    if not exe or _same_dir(str(Path(exe).parent), old) or not (old / "aht.exe").is_file():
        return
    stop_watcher()
    stop_aht_processes(old)
    for name in ("aht.exe", "aht-tray.exe", VBS_NAME):
        try:
            (old / name).unlink()
        except OSError:
            pass
    shutil.rmtree(old / "_internal", ignore_errors=True)
    try:
        _user_path(old, add=False)
    except OSError:
        pass
    print(f"✓ removed the older copy in {old}")


def _put_on_path(exe: str, want: bool) -> None:
    """`aht` in a terminal: the folder of `exe` on this user's PATH, unless
    scoop or winget already put an aht there (or `want` is False)."""
    if not exe:
        return
    d = Path(exe).parent
    try:
        if not want:
            if _user_path(d, add=False):
                print(f"✓ {d} taken out of your PATH")
            return
        # not shutil.which: on Windows it also looks in the current folder,
        # which is this one when the installer runs us
        for x in os.environ.get("PATH", "").split(os.pathsep):
            if x and not _same_dir(x, d) and not _same_dir(x, app_dir()) and any(
                    os.path.isfile(os.path.join(os.path.expandvars(x), "aht" + ext))
                    for ext in (".exe", ".cmd", ".bat")):
                return
        if _user_path(d, add=True):
            print(f"✓ added {d} to your PATH: `aht` works in new terminals")
    except OSError as e:
        print(f"⚠ could not change your PATH: {e}")


def _same_dir(a: str, b: Path) -> bool:
    return os.path.normcase(os.path.expandvars(a).rstrip("\\")) == \
        os.path.normcase(str(b).rstrip("\\"))


def _user_path(d: Path, add: bool) -> bool:
    """Add `d` to (or take it out of) this user's PATH, the HKCU one, and
    tell running programs; new terminals see it.  True when it changed."""
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
        try:
            cur, kind = winreg.QueryValueEx(k, "Path")
        except OSError:
            cur, kind = "", winreg.REG_EXPAND_SZ
        parts = [x for x in cur.split(";") if x]
        has = any(_same_dir(x, d) for x in parts)
        if add == has:
            return False
        parts = parts + [str(d)] if add else [x for x in parts if not _same_dir(x, d)]
        winreg.SetValueEx(k, "Path", 0, kind, ";".join(parts))
    try:
        send = _user32.SendMessageTimeoutW
        send.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPCWSTR,
                         wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
        send(0xFFFF, 0x001A, 0, "Environment", 0x0002, 3000,      # WM_SETTINGCHANGE
             ctypes.byref(ctypes.c_size_t()))
    except Exception:
        pass
    return True


def _hook_cmdline(exe: str) -> str:
    if exe:
        return f'"{exe}" hook'
    return self_cmdline("hook")


def _watch_cmdline(exe: str) -> str:
    if exe:
        return f'"{exe}" watch'
    return self_cmdline("watch")


def install_hook(hook_cmd: str) -> None:
    s = {}
    if SETTINGS.exists():
        try:
            s = json.loads(SETTINGS.read_text(encoding="utf-8"))
        except Exception:
            print("⚠ settings.json is not valid JSON — leaving it alone; "
                  "the hook was NOT installed")
            return
        shutil.copy2(SETTINGS, str(SETTINGS) + ".bak-aht")
    hooks = s.setdefault("hooks", {})
    groups = [g for g in hooks.get("SessionStart", [])
              if not any(_is_our_hook(h.get("command", ""))
                         for h in g.get("hooks", []))]
    for matcher in ("startup", "resume", "fork"):   # fork: /branch, --fork-session
        groups.append({"matcher": matcher,
                       "hooks": [{"type": "command", "command": hook_cmd,
                                  "timeout": 10}]})
    hooks["SessionStart"] = groups
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(s, indent=2), encoding="utf-8")
    print("✓ SessionStart hook registered (backup: settings.json.bak-aht)")


def remove_hook() -> None:
    if not SETTINGS.exists():
        return
    try:
        s = json.loads(SETTINGS.read_text(encoding="utf-8"))
    except Exception:
        print("⚠ settings.json is not valid JSON — hook not removed")
        return
    hooks = s.get("hooks", {})
    groups = hooks.get("SessionStart", [])
    kept = [g for g in groups
            if not any(_is_our_hook(h.get("command", ""))
                       for h in g.get("hooks", []))]
    if len(kept) != len(groups):
        shutil.copy2(SETTINGS, str(SETTINGS) + ".bak-aht")
        if kept:
            hooks["SessionStart"] = kept
        else:
            hooks.pop("SessionStart", None)
        SETTINGS.write_text(json.dumps(s, indent=2), encoding="utf-8")
        print("✓ SessionStart hook removed")


def _watch_entry(exe: str) -> str:
    """The logon entry's command for the watcher alone.  A console exe started
    from a Run entry flashes a console window; aht-tray.exe is a windowed
    program, so `aht-tray.exe --watch` runs the watcher with nothing on
    screen.  No script in between: Windows Security takes a .vbs that starts
    a hidden program from a Run entry for malware."""
    tray = Path(exe).with_name("aht-tray.exe") if exe else None
    if tray and tray.is_file():
        return f'"{tray}" --watch'
    return _watch_cmdline(exe)


def _remove_old_launchers() -> None:
    for base in {app_dir(), Path(sys.executable).parent}:
        try:
            (base / VBS_NAME).unlink()
        except OSError:
            pass


def _write_autostart(exe: str) -> None:
    """Autostart at logon via an HKCU Run entry."""
    _run_key_set(_watch_entry(exe))
    _remove_old_launchers()
    print("✓ watcher registered to start at logon (HKCU Run)")


def is_tray_entry(entry) -> bool:
    """The logon entry starts the tray (which keeps the watcher running), not
    the watcher alone."""
    v = (entry or "").lower()
    return "aht-tray" in v and "--watch" not in v


def _keep_tray_entry(exe: str):
    """A logon entry that starts the tray stays one (whoever chose it: the
    installer, aht's window, the tray), now for this aht's tray; returns
    that tray, or None when the entry was not the tray's."""
    tray = Path(exe).with_name("aht-tray.exe") if exe else None
    if not (tray and tray.is_file() and is_tray_entry(_run_key_get())):
        return None
    _run_key_set(f'"{tray}"')
    _remove_old_launchers()
    print("✓ the tray still starts at logon (HKCU Run)")
    return tray


def tray_running() -> bool:
    h = _kernel32.OpenMutexW(SYNCHRONIZE, False, TRAY_MUTEX_NAME)
    if h:
        _kernel32.CloseHandle(h)
        return True
    return False


def _rewrite_old_entry() -> None:
    """An entry an older version wrote (wscript.exe + aht-watch.vbs) is
    rewritten the current way, so an upgrade alone gets rid of it."""
    if VBS_NAME not in (_run_key_get() or ""):
        return
    exe = app_dir() / "aht.exe"
    import contextlib, io
    with contextlib.redirect_stdout(io.StringIO()):
        _write_autostart(str(exe) if exe.is_file() else self_cmd()[0] if FROZEN else "")


def cmd_install(argv) -> int:
    ap = argparse.ArgumentParser(
        prog="aht install",
        description="Self-install: stable exe copy + logon watcher + "
                    "SessionStart hook.  Idempotent; never needs admin.")
    ap.add_argument("--no-watcher", action="store_true",
                    help="register only the SessionStart hook")
    ap.add_argument("--here", action="store_true",
                    help="reference aht where it is now instead of copying "
                         "it to %%LOCALAPPDATA%%\\aht (always so when aht's "
                         "installer or Scoop put it there)")
    ap.add_argument("--no-path", action="store_true",
                    help="do not put aht on your PATH")
    args = ap.parse_args(argv)

    aht.ensure_config()
    here = args.here or installed_in_place()
    exe = _install_binary(copy=not here)
    if here:
        _retire_old_copy(exe)
    _put_on_path(exe, want=not args.no_path)
    install_hook(_hook_cmdline(exe))
    if not args.no_watcher:
        tray = _keep_tray_entry(exe)
        if not tray:
            _write_autostart(exe)
        stop_watcher()
        if exe:
            logf = open(watcher_log_path(), "a", encoding="utf-8", errors="replace")
            subprocess.Popen([exe, "watch"], stdin=subprocess.DEVNULL,
                             stdout=logf, stderr=logf,
                             creationflags=CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP,
                             close_fds=True)
        else:
            start_watcher_hidden()
        time.sleep(0.5)
        print(f"✓ watcher {'running' if watcher_running() else 'started'} "
              f"(log: {watcher_log_path()})")
        if tray and not tray_running():
            # an upgrade stopped it (Scoop's, winget's), and nothing else
            # starts it again before the next sign-in
            subprocess.Popen([str(tray)], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=CREATE_NEW_PROCESS_GROUP, close_fds=True)
            print("✓ the tray started")
    roots = aht.watch_roots_config()
    print(f"\nWatching roots: {[r for r in roots if os.path.isdir(r)] or '(none exist yet)'}")
    print("Reconnect this machine's existing projects with:  aht adopt --apply")
    print("Check the install with:                           aht doctor")
    return 0


def cmd_uninstall(argv) -> int:
    ap = argparse.ArgumentParser(
        prog="aht uninstall",
        description="Stop the automation.  Conversation history is NEVER touched.")
    ap.add_argument("--purge", action="store_true",
                    help="also remove the registry and the .aht/.project-id "
                         "markers (history is still kept)")
    ap.add_argument("--remove-icons", action="store_true", dest="remove_icons",
                    help="also clear the folder badges this tool applied")
    args = ap.parse_args(argv)

    stopped = stop_watcher()
    print("✓ watcher stopped" if stopped else "• no watcher was running")
    if stop_aht_processes():
        print("✓ the tray and aht's window closed")
    _run_key_delete()
    _remove_old_launchers()
    print("✓ logon entry removed")
    remove_hook()
    for d in {str(app_dir()), str(Path(sys.executable).parent) if FROZEN else str(app_dir())}:
        try:
            if _user_path(Path(d), add=False):
                print(f"✓ {d} taken out of your PATH")
        except OSError:
            pass

    if args.remove_icons:
        import winbadge
        reg = aht.load_registry()
        targets = {e["real_path"] for e in reg.get("projects", {}).values()}
        targets |= set(reg.get("git_repos", []))
        n = 0
        for p in sorted(targets):
            if os.path.isdir(p):
                try:
                    winbadge.apply(p, [])
                    n += 1
                except Exception:
                    pass
        print(f"✓ cleared badges on {n} folder(s)")

    if args.purge:
        reg = aht.load_registry()
        for e in reg.get("projects", {}).values():
            try:
                (Path(e["real_path"]) / aht.MARKER_REL).unlink()
            except OSError:
                pass
        for p in (aht.registry_path(),
                  aht.registry_path().with_suffix(".json.bak"),
                  aht.config_path(), aht.lock_path()):
            try:
                Path(p).unlink()
            except OSError:
                pass
        print("✓ markers + registry removed (history kept)")
    print("\nAutomation removed. No agent's history was touched.")
    if FROZEN and aht.install_kind() == "installer":
        print("Remove the program in Settings > Apps > aht.")
    elif FROZEN:
        print(f"Delete the program by hand if you want it gone: {Path(sys.executable).parent}")
    return 0


# --------------------------------------------------------------------------- #
# Activation
# --------------------------------------------------------------------------- #

COMMANDS = {"watch": cmd_watch, "install": cmd_install, "uninstall": cmd_uninstall}

WIN_ABOUT_EXTRA = """
WINDOWS COMMANDS (this build):
  aht install               set up the logon watcher + SessionStart hook
  aht watch                 run the watcher in the foreground
  aht uninstall             stop the automation (history kept)
  aht-tray.exe              system tray companion (status + actions)
  aht-tray.exe --window     the tray, and aht's window (the Start menu's aht)

Installed at: %LOCALAPPDATA%\\Programs\\aht (the installer) or
              %LOCALAPPDATA%\\aht (`aht install` from the zip)
Data:  %USERPROFILE%\\.aht\\registry.json,  config.json
Logs:  %USERPROFILE%\\.aht\\aht.log,  aht-watcher.log
Badges: folders get per-agent discs / a git "+" icon via a hidden
        desktop.ini + .aht\\aht-badge.ico that travel with the folder;
        refresh with `aht icons --refresh`, remove with
        `aht uninstall --remove-icons`.
"""


def activate() -> None:
    """Patch the Windows implementations over the core's platform seams."""
    enable_dpi_awareness()
    fix_streams()
    aht.ask_dialog = ask_dialog
    aht.notify_user = notify_user
    aht.apply_badge = apply_badge
    aht.gui_dialogs_available = gui_dialogs_available
    aht.watcher_status = watcher_status
    aht._reload_watcher = _reload_watcher
    aht.hook_installed = hook_installed
    aht._default_watch_roots = _default_watch_roots
    try:
        _rewrite_old_entry()
    except Exception as e:
        aht.log(f"could not rewrite the old logon entry: {e}")
    aht.ABOUT = aht.ABOUT.rstrip("\n").rsplit("\nData:", 1)[0] \
        + "\n" + WIN_ABOUT_EXTRA
