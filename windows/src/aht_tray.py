#!/usr/bin/env python3
"""
aht-tray — the Windows system-tray companion of aht.exe, the
counterpart of the macOS menu bar app.  Pure ctypes Win32 (Shell_NotifyIcon +
popup menus), no third-party dependencies.

The tray is a FRONT-END only: every action goes through the same shared core /
config / registry as the CLI and the hidden watcher, so the GUI, the terminal
and the background service can never disagree.  Watching itself stays in the
separate hidden watcher process; the tray starts it if needed and can
pause/resume it via its named stop event.

Menu parity with the macOS menu bar app: status (tracked/missing/orphans/
hook), reconcile now, pause/resume, recent projects, adopt (dry-run +
confirmation first, like macOS), a Settings submenu for every shared policy
(move/copy/new, notifications), a Badges submenu (toggles, refresh, clear),
diagnostics, log access, autostart toggle.  The macOS app's full windows
(Projects browser, Orphan matcher, Preferences panes) have no menu
equivalent — those flows live in the CLI (`aht projects`,
`aht orphans --match`, `aht config`).

Shared settings are written through the same Lock + config file as
`aht config --set`, never through a private store.

--selftest exercises everything that can run headless (imports, icon
rasteriser, sibling-exe resolution, full menu construction) and exits 0/1 —
used by the wine smoke test, where no tray area exists.
"""
import ctypes
import ctypes.wintypes as wintypes
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

if os.name == "nt":
    import win_fcntl
    sys.modules.setdefault("fcntl", win_fcntl)
else:
    print("aht-tray is Windows-only", file=sys.stderr)
    sys.exit(2)

if not getattr(sys, "frozen", False):
    # running from source: the shared core lives two levels up, at the repo root
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import aht      # noqa: E402
import winlayer  # noqa: E402

FROZEN = bool(getattr(sys, "frozen", False))

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# ---- Win32 plumbing --------------------------------------------------------

WM_NULL, WM_DESTROY, WM_TIMER, WM_APP = 0x0, 0x2, 0x113, 0x8000
WM_LBUTTONUP, WM_RBUTTONUP = 0x202, 0x205
WM_TRAY = WM_APP + 1
MF_STRING, MF_GRAYED, MF_CHECKED, MF_POPUP, MF_SEPARATOR = 0x0, 0x1, 0x8, 0x10, 0x800
TPM_RIGHTBUTTON, TPM_NONOTIFY, TPM_RETURNCMD = 0x2, 0x80, 0x100
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x1, 0x2, 0x4, 0x10
NIIF_INFO = 0x1
MB_OK, MB_YESNO, MB_ICONINFORMATION, MB_ICONQUESTION = 0x0, 0x4, 0x40, 0x20
MB_SETFOREGROUND, MB_TOPMOST = 0x10000, 0x40000
IDYES = 6
ERROR_ALREADY_EXISTS = 183

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", ctypes.c_void_p), ("hbrBackground", ctypes.c_void_p),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR)]


class ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD),
                ("yHotspot", wintypes.DWORD), ("hbmMask", wintypes.HBITMAP),
                ("hbmColor", wintypes.HBITMAP)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
                ("uID", wintypes.UINT), ("uFlags", wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD),
                ("dwStateMask", wintypes.DWORD), ("szInfo", wintypes.WCHAR * 256),
                ("uVersion", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64),
                ("dwInfoFlags", wintypes.DWORD), ("guidItem", ctypes.c_byte * 16),
                ("hBalloonIcon", wintypes.HICON)]


user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                  wintypes.WPARAM, wintypes.LPARAM]
user32.CreateWindowExW.restype = wintypes.HWND
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT,
                               ctypes.c_size_t, wintypes.LPCWSTR]
user32.CreatePopupMenu.restype = wintypes.HMENU
user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                  ctypes.c_void_p]
user32.TrackPopupMenu.restype = ctypes.c_int
user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT,
                            ctypes.c_void_p]
user32.CreateIconIndirect.restype = wintypes.HICON
gdi32.CreateBitmap.argtypes = [ctypes.c_int, ctypes.c_int, wintypes.UINT,
                               wintypes.UINT, ctypes.c_void_p]
gdi32.CreateBitmap.restype = wintypes.HBITMAP
shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD,
                                      ctypes.POINTER(NOTIFYICONDATAW)]
shell32.Shell_NotifyIconW.restype = wintypes.BOOL

CORAL = (217, 119, 87)          # the tray mark when watching
GRAY = (140, 140, 140)          # paused


def mark_pixels(s, rgb):
    from winbadge import infinity_overlay
    return infinity_overlay(s, rgb=rgb)


SM_CXSMICON = 49


def tray_icon_size():
    """The size the notification area actually wants at the current DPI
    (16 at 100%, 24 at 150%, …).  Drawing at exactly this size — instead of
    handing Windows a 32px icon to squeeze — is what keeps the loop crisp.
    Only meaningful once the process is DPI-aware (winlayer.activate())."""
    try:
        s = int(user32.GetSystemMetrics(SM_CXSMICON))
        if 16 <= s <= 256:
            return s
    except Exception:
        pass
    return 16


def make_icon(rgb, size=None):
    s = size or tray_icon_size()
    px = bytes(mark_pixels(s, rgb))
    color = gdi32.CreateBitmap(s, s, 1, 32, px)
    mask = gdi32.CreateBitmap(s, s, 1, 1, None)
    ii = ICONINFO(True, 0, 0, mask, color)
    hicon = user32.CreateIconIndirect(ctypes.byref(ii))
    gdi32.DeleteObject(color)
    gdi32.DeleteObject(mask)
    return hicon


# ---- tray state ------------------------------------------------------------

HWND = None
ICONS = {}
LAST_STATE = None


def _nid(flags=0):
    nid = NOTIFYICONDATAW()
    nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
    nid.hWnd = HWND
    nid.uID = 1
    nid.uFlags = flags
    return nid


def tray_add():
    nid = _nid(NIF_MESSAGE | NIF_ICON | NIF_TIP)
    nid.uCallbackMessage = WM_TRAY
    running = winlayer.watcher_running()
    nid.hIcon = ICONS[running]
    nid.szTip = _tip(running)
    shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))


def _tip(running):
    try:
        n = len(aht.load_registry().get("projects", {}))
    except Exception:
        n = 0
    return (f"aht — watching ({n} project(s))" if running
            else "aht — paused")[:127]


def refresh(force=False):
    global LAST_STATE
    running = winlayer.watcher_running()
    if not force and running == LAST_STATE:
        return
    LAST_STATE = running
    nid = _nid(NIF_ICON | NIF_TIP)
    nid.hIcon = ICONS[running]
    nid.szTip = _tip(running)
    shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))


def balloon(title, msg):
    nid = _nid(NIF_INFO)
    nid.szInfo = str(msg)[:255]
    nid.szInfoTitle = str(title)[:63]
    nid.dwInfoFlags = NIIF_INFO
    shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))


def msgbox(title, text, flags=MB_OK | MB_ICONINFORMATION):
    return winlayer._user32.MessageBoxW(
        None, text, title, flags | MB_SETFOREGROUND | MB_TOPMOST)


def _run_cli(*args):
    return subprocess.run(winlayer.self_cmd(*args), capture_output=True,
                          text=True, creationflags=winlayer.CREATE_NO_WINDOW)


def _in_thread(fn):
    threading.Thread(target=fn, daemon=True).start()


def _set_shared(key, value):
    """Write one shared config key through the same lock + file the CLI uses."""
    with aht.Lock():
        cfg = aht.load_config()
        cfg[key] = value
        aht.save_config(cfg)


# ---- actions ---------------------------------------------------------------

def act_reconcile():
    def work():
        r = _run_cli("reconcile", "--notify")
        try:
            d = json.loads(r.stdout or "{}")
            am = len(d.get("applied_moves", []))
            ac = len(d.get("applied_copies", []))
            if am or ac:
                msg = f"{am} project(s) relinked, {ac} histor(ies) copied"
            elif d.get("moves") or d.get("copies"):
                msg = "Changes were found — answered via dialog or deferred"
            else:
                msg = "Nothing to do — every history is in place"
        except Exception:
            msg = ("Reconcile finished" if r.returncode == 0
                   else f"Reconcile failed (exit {r.returncode})")
        balloon("Reconcile", msg)
        refresh(force=True)
    _in_thread(work)


def act_toggle_watch():
    if winlayer.watcher_running():
        winlayer.stop_watcher()
        balloon("Watcher paused", "Folder moves are not being watched. "
                "The SessionStart hook still relinks projects you open.")
    else:
        winlayer.start_watcher_hidden()
        balloon("Watcher", "Watching resumed")
    refresh(force=True)


def act_adopt():
    """Dry-run first, then confirm — same flow as the macOS app."""
    def work():
        r = _run_cli("adopt", "--json")
        try:
            d = json.loads(r.stdout or "{}")
        except Exception:
            msgbox("Adopt", "Could not scan for existing projects:\n"
                   + (r.stderr or r.stdout or f"exit {r.returncode}")[:800])
            return
        planned = len(d.get("planned", []))
        already = int(d.get("already", 0))
        orphans = int(d.get("orphans_claude", 0))
        if not planned:
            msgbox("Nothing to adopt",
                   f"{already} project(s) are already tracked.\n"
                   f"{orphans} history folder(s) have no matching project — "
                   "reconnect those with:  aht orphans --match")
            return
        text = (f"Start tracking {planned} existing project(s)?\n\n"
                "Each folder gets a small marker file (.aht\\.project-id) "
                "and a registry entry, so its histories follow it from now on.\n"
                "Nothing is moved, renamed or deleted.")
        if msgbox("Adopt existing projects",
                  text, MB_YESNO | MB_ICONQUESTION) != IDYES:
            return
        r2 = _run_cli("adopt", "--apply", "--json")
        ok = r2.returncode == 0
        balloon("Adopt", f"{planned} project(s) are now tracked" if ok
                else f"Adopt failed (exit {r2.returncode})")
        refresh(force=True)
    _in_thread(work)


def act_editcfg():
    aht.ensure_config()
    subprocess.Popen(["notepad.exe", str(aht.config_path())])
    balloon("Config", "After saving, use 'Restart watcher' to apply the change")


def act_restart():
    def work():
        winlayer.stop_watcher()
        winlayer.start_watcher_hidden()
        balloon("Watcher", "Restarted with the current config")
        refresh(force=True)
    _in_thread(work)


def act_opendata():
    try:
        os.startfile(str(aht.aht_home()))
    except Exception:
        pass


def act_openlog():
    p = aht.log_path()
    if p.is_file():
        try:
            os.startfile(str(p))
            return
        except Exception:
            pass
    balloon("Log", "No log entries yet")


def act_doctor():
    def work():
        r = _run_cli("doctor")
        msgbox("Diagnostics", (r.stdout or r.stderr
                               or f"doctor failed (exit {r.returncode})")[:2000])
    _in_thread(work)


def act_refresh_badges():
    def work():
        r = _run_cli("icons", "--refresh")
        balloon("Folder badges",
                (r.stdout or "").strip().splitlines()[-1]
                if r.returncode == 0 and r.stdout else
                ("Refreshed" if r.returncode == 0
                 else f"Refresh failed (exit {r.returncode})"))
    _in_thread(work)


def act_clear_badges():
    if msgbox("Clear every folder badge?",
              "This removes the custom icon from tracked project folders and "
              "git repos under your watched folders.\nYour history and your "
              "projects are not affected, and badges come back if you "
              "re-enable them.", MB_YESNO | MB_ICONQUESTION) != IDYES:
        return

    def work():
        # same trick as the macOS app: refresh once with every mark disabled
        saved = {k: aht.cfg_get(k, True)
                 for k in ("icons_enabled", "icons_agent", "icons_git")}
        _set_shared("icons_enabled", True)
        _set_shared("icons_agent", False)
        _set_shared("icons_git", False)
        try:
            _run_cli("icons", "--refresh")
        finally:
            for k, v in saved.items():
                _set_shared(k, bool(v))
        balloon("Folder badges", "Cleared")
    _in_thread(work)


def act_backup_now():
    def work():
        r = _run_cli("backup", "--json")
        try:
            d = json.loads(r.stdout or "{}")
            counts = d.get("counts", {})
            msg = (", ".join(f"{v} {k}" for k, v in sorted(counts.items()))
                   or "nothing to back up")
        except Exception:
            msg = ("Backup finished" if r.returncode == 0
                   else f"Backup failed (exit {r.returncode})")
        balloon("History backup", msg)
    _in_thread(work)


BIF_RETURNONLYFSDIRS, BIF_NEWDIALOGSTYLE = 0x0001, 0x0040


class BROWSEINFOW(ctypes.Structure):
    _fields_ = [("hwndOwner", wintypes.HWND), ("pidlRoot", ctypes.c_void_p),
                ("pszDisplayName", wintypes.LPWSTR),
                ("lpszTitle", wintypes.LPCWSTR), ("ulFlags", wintypes.UINT),
                ("lpfn", ctypes.c_void_p), ("lParam", wintypes.LPARAM),
                ("iImage", ctypes.c_int)]


def _browse_folder(title):
    """Native folder picker (used by the Agent CLI locations page)."""
    try:
        ctypes.WinDLL("ole32").CoInitialize(None)
    except Exception:
        pass
    disp = ctypes.create_unicode_buffer(260)
    bi = BROWSEINFOW(HWND, None, ctypes.cast(disp, wintypes.LPWSTR), title,
                     BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE, None, 0, 0)
    shell32.SHBrowseForFolderW.restype = ctypes.c_void_p
    pidl = shell32.SHBrowseForFolderW(ctypes.byref(bi))
    if not pidl:
        return None
    buf = ctypes.create_unicode_buffer(260)
    ok = shell32.SHGetPathFromIDListW(ctypes.c_void_p(pidl), buf)
    try:
        ctypes.WinDLL("ole32").CoTaskMemFree(ctypes.c_void_p(pidl))
    except Exception:
        pass
    return buf.value if ok and buf.value else None


def _pick_backend_root(name):
    def go():
        path = _browse_folder(f"Choose the {name} history store folder")
        if not path:
            return
        def work():
            r = _run_cli("backends", "--set-root", f"{name}={path}")
            balloon("Agent CLI locations",
                    f"{name} → {path}" if r.returncode == 0
                    else f"failed (exit {r.returncode})")
        _in_thread(work)
    return go


def act_reset_backend_roots():
    if msgbox("Reset every agent CLI location to its default?",
              "Only the store paths aht looks at are reset — no history is "
              "touched.", MB_YESNO | MB_ICONQUESTION) != IDYES:
        return
    def work():
        names = [b["name"] for b in aht.backend_status()]
        _run_cli("backends", "--clear-root", *names)
        balloon("Agent CLI locations", "Reset to defaults")
    _in_thread(work)


def act_repair():
    def work():
        r = _run_cli("install")
        balloon("Install", "Repair finished" if r.returncode == 0
                else f"Repair failed (exit {r.returncode})")
        refresh(force=True)
    _in_thread(work)


def logon_is_tray():
    v = winlayer._run_key_get() or ""
    return "aht-tray" in v.lower()


def act_toggle_logon():
    if logon_is_tray():
        exe = winlayer.self_cmd()[0] if FROZEN else ""
        winlayer._write_autostart(exe)
        balloon("Autostart", "The hidden watcher starts at logon (tray does not)")
    else:
        if FROZEN:
            winlayer._run_key_set(f'"{sys.executable}"')
        else:
            winlayer._run_key_set(subprocess.list2cmdline(
                [sys.executable, str(Path(__file__).resolve())]))
        balloon("Autostart", "The tray starts at logon "
                "(and keeps the watcher running)")


def act_about():
    text = (f"aht {aht.VERSION} — agent-history-tether\n\n"
            "Keeps every AI coding agent's per-project history connected\n"
            "to its folder when you move, rename, copy or nest that folder.\n\n"
            "This tray, the aht.exe CLI and the hidden watcher all drive\n"
            "the same core, registry and config — they can never disagree.\n\n"
            f"Data:  {aht.aht_home()}\n"
            "History is never deleted or overwritten.")
    msgbox("About aht", text)


def act_quit():
    nid = _nid()
    shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
    user32.PostQuitMessage(0)


def _reveal(path):
    def go():
        if os.path.isdir(path):
            subprocess.Popen(["explorer", "/select,", path])
        else:
            balloon("That folder is gone",
                    "Its history is safe — reconnect it with:  "
                    "aht orphans --match")
    return go


def _policy_setter(key, value, label):
    def go():
        _set_shared(key, value)
        balloon("Settings", label)
    return go


def _toggle_setter(key, default, label):
    def go():
        new = not aht.cfg_get(key, default)
        _set_shared(key, new)
        balloon("Settings", f"{label}: {'on' if new else 'off'}")
    return go


# ---- the menu --------------------------------------------------------------

MOVE_CHOICES = [("ask", "Ask me"), ("apply", "Relink automatically"),
                ("decline", "Never relink (remember the no)"),
                ("ignore", "Do nothing")]
COPY_CHOICES = [("ask", "Ask me"), ("duplicate", "Duplicate the history"),
                ("independent", "Fresh identity, no history"),
                ("ignore", "Do nothing")]
NEW_CHOICES = [("apply", "Start tracking it"), ("ignore", "Leave it alone")]


def build_menu():
    """Construct the full menu from live state.  Returns (hmenu, {id: fn}).
    Rebuilt on every open, so counts are never stale (same as macOS)."""
    running = winlayer.watcher_running()
    reg = aht.load_registry()
    projects = reg.get("projects", {})
    n = len(projects)
    missing = sum(1 for e in projects.values()
                  if not os.path.isdir(e["real_path"]))
    try:
        owned = aht.registered_history_dirs(reg)
        orphans = sum(1 for d in aht._iter_history_dirs()
                      if d.name not in owned)
    except Exception:
        orphans = 0
    hook = winlayer.hook_installed()

    actions = {}
    counter = [0]

    def add(menu, text, cb=None, checked=False):
        flags = MF_STRING | (MF_CHECKED if checked else 0)
        if cb is None:
            user32.AppendMenuW(menu, flags | MF_GRAYED, 0, text)
        else:
            counter[0] += 1
            actions[counter[0]] = cb
            user32.AppendMenuW(menu, flags, counter[0], text)

    def sep(menu):
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)

    def submenu(parent, text):
        m = user32.CreatePopupMenu()
        user32.AppendMenuW(parent, MF_POPUP | MF_STRING, m, text)
        return m

    root = user32.CreatePopupMenu()

    add(root, f"aht {aht.VERSION} — "
              f"{'watching' if running else 'PAUSED'}")
    line = f"{n} tracked project(s)"
    if missing:
        line += f" · {missing} missing"
    if orphans:
        line += f" · {orphans} orphan histor{'y' if orphans == 1 else 'ies'}"
    if not hook:
        line += " · hook MISSING"
    add(root, line)
    sep(root)

    add(root, "Reconcile now", act_reconcile)
    add(root, "Pause watching" if running else "Resume watching",
        act_toggle_watch)
    sep(root)

    recent = submenu(root, "Recent projects")
    rows = sorted(projects.values(),
                  key=lambda e: e.get("updated_at") or "", reverse=True)[:10]
    if not rows:
        add(recent, "No tracked projects yet")
    for e in rows:
        p = e["real_path"]
        name = os.path.basename(p) or p
        if not os.path.isdir(p):
            name += "  (missing)"
        add(recent, name, _reveal(p))

    add(root, "Adopt this PC's projects…", act_adopt)
    sep(root)

    settings = submenu(root, "Settings")
    for key, choices, title, default in (
            ("move_policy", MOVE_CHOICES, "When a folder moves", "ask"),
            ("copy_policy", COPY_CHOICES, "When a folder is copied", "ask"),
            ("new_policy", NEW_CHOICES, "When a new project is found", "apply")):
        cur = aht.cfg_get(key, default)
        m = submenu(settings, title)
        for val, label in choices:
            add(m, label, _policy_setter(key, val, f"{title}: {label}"),
                checked=(cur == val))
    add(settings, "Notifications",
        _toggle_setter("notifications", True, "Notifications"),
        checked=bool(aht.cfg_get("notifications", True)))
    add(settings, "Auto-backup histories",
        _toggle_setter("backup_enabled", True, "Auto-backup histories"),
        checked=bool(aht.cfg_get("backup_enabled", True)))
    add(settings, "Back up histories now", act_backup_now)
    sep(settings)
    locations = submenu(settings, "Agent CLI locations")
    for b in aht.backend_status():
        title = f"{b['name']} — {'found' if b['available'] else 'NOT FOUND'}"
        if b.get("root_source", "default") != "default":
            title += f"  [{b['root_source']}]"
        add(locations, title, _pick_backend_root(b["name"]))
    sep(locations)
    add(locations, "Reset all to defaults", act_reset_backend_roots)
    add(settings, "Edit config file (Notepad)", act_editcfg)
    add(settings, "Restart watcher (apply config)", act_restart)

    badges = submenu(root, "Folder badges")
    add(badges, "Badge folders",
        _toggle_setter("icons_enabled", True, "Folder badges"),
        checked=bool(aht.cfg_get("icons_enabled", True)))
    add(badges, "Agent symbols",
        _toggle_setter("icons_agent", True, "Agent symbols"),
        checked=bool(aht.cfg_get("icons_agent", True)))
    add(badges, "Git “+”",
        _toggle_setter("icons_git", True, "Git “+”"),
        checked=bool(aht.cfg_get("icons_git", True)))
    sep(badges)
    add(badges, "Refresh all badges", act_refresh_badges)
    add(badges, "Clear all badges…", act_clear_badges)
    sep(root)

    add(root, "Run diagnostics", act_doctor)
    add(root, "Open data folder (.claude)", act_opendata)
    add(root, "Open log", act_openlog)
    if not hook:
        add(root, "Repair install (hook + watcher)", act_repair)
    sep(root)

    add(root, "Start tray at logon", act_toggle_logon,
        checked=logon_is_tray())
    add(root, "About aht", act_about)
    sep(root)

    add(root, "Quit tray (watcher keeps running)" if running else "Quit tray",
        act_quit)

    return root, actions


def show_menu():
    root, actions = build_menu()
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    user32.SetForegroundWindow(HWND)
    cmd = user32.TrackPopupMenu(
        root, TPM_RETURNCMD | TPM_RIGHTBUTTON | TPM_NONOTIFY,
        pt.x, pt.y, 0, HWND, None)
    user32.PostMessageW(HWND, WM_NULL, 0, 0)
    user32.DestroyMenu(root)                   # destroys submenus recursively
    actions.get(cmd, lambda: None)()


WM_TASKBARCREATED = user32.RegisterWindowMessageW("TaskbarCreated")


def wnd_proc(hwnd, msg, wparam, lparam):
    if msg == WM_TRAY:
        if lparam in (WM_RBUTTONUP, WM_LBUTTONUP):
            show_menu()
        return 0
    if msg == WM_TIMER:
        refresh()
        return 0
    if msg == WM_TASKBARCREATED:        # explorer restarted: re-add the icon
        tray_add()
        refresh(force=True)
        return 0
    if msg == WM_DESTROY:
        nid = _nid()
        shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
        user32.PostQuitMessage(0)
        return 0
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


# ---- entry -----------------------------------------------------------------

def selftest():
    """Everything that can run without a tray area: bundling, seams, icon
    rasteriser, sibling-exe resolution, registry/status reads, and a full
    menu construction pass (validates every item + handler wiring)."""
    try:
        winlayer.activate()
        assert aht.VERSION
        for rgb in (CORAL, GRAY):
            px = mark_pixels(32, rgb)
            assert len(px) == 32 * 32 * 4 and any(px)
        cmd = winlayer.self_cmd("version")
        assert cmd and cmd[0]
        aht.load_registry()
        winlayer.watcher_running()
        winlayer.hook_installed()
        assert ctypes.sizeof(NOTIFYICONDATAW) > 900   # W-struct, not truncated
        root, actions = build_menu()
        assert root and len(actions) >= 20, f"menu too small: {len(actions)}"
        user32.DestroyMenu(root)
        try:
            print("TRAY SELFTEST OK", cmd, f"{len(actions)} menu action(s)")
        except Exception:
            pass
        return 0
    except Exception as e:
        try:
            print(f"TRAY SELFTEST FAIL: {e!r}", file=sys.stderr)
        except Exception:
            pass
        return 1


def main():
    if "--selftest" in sys.argv[1:]:
        return selftest()
    winlayer.activate()

    # single instance
    kernel32.CreateMutexW(None, False, "Local\\aht-tray")
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        return 0

    # the tray's promise is "protection is on while I'm in the tray"
    if not winlayer.watcher_running():
        winlayer.start_watcher_hidden()

    global HWND, ICONS
    ICONS = {True: make_icon(CORAL), False: make_icon(GRAY)}

    hinst = kernel32.GetModuleHandleW(None)
    proc = WNDPROC(wnd_proc)                      # keep a reference alive
    wc = WNDCLASSW()
    wc.lpfnWndProc = proc
    wc.hInstance = hinst
    wc.lpszClassName = "aht_tray_wnd"
    if not user32.RegisterClassW(ctypes.byref(wc)):
        return 1
    HWND = user32.CreateWindowExW(0, wc.lpszClassName, "aht-tray",
                                  0, 0, 0, 0, 0, None, None, hinst, None)
    if not HWND:
        return 1

    tray_add()
    refresh(force=True)
    user32.SetTimer(HWND, 1, 15000, None)         # keep icon in sync

    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
