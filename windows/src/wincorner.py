#!/usr/bin/env python3
"""
The session corner on Windows: a small list of the open Claude sessions in a
corner of the screen, as the Mac app has it (macos/tray.swift, CornerModel and
CornerPanel): working (blue), waiting for you (orange) or done (green), with
how long it has been so, under the name the Claude app shows.  A click brings
the session's Windows Terminal tab to the front.  A right-click offers Go to
Tab, Branch… (a branch of the session in a new tab) and Send to <machine>…;
on a session handed over to another machine, Open Session and Take Back….

`Model` is plain Python and runs anywhere (windows/tests/wincorner_test.py):
it reads Claude Code's own records of its sessions (<claude home>/sessions/
<pid>.json) every second and a half, and a session's title from the end of its
conversation file.  `Corner` is the window: Win32 through ctypes, run by the
tray (aht_tray.py) on its own thread, drawn with GDI, never activated by a
click, so the window you type in keeps the keyboard.
"""
import ctypes
import json
import ntpath
import os
import threading
import time
from pathlib import Path

import aht

WORKING = ("busy", "shell")
STATE_FILE = "corner.json"          # in aht's run folder, as on the Mac
PLACE_FILE = "corner-place.json"    # where you put the list, its width and length


def age(s: float) -> str:
    return ("now" if s < 60 else f"{int(s // 60)}m" if s < 3600 else
            f"{int(s // 3600)}h" if s < 86400 else f"{int(s // 86400)}d")


def _last_of(data: bytes, kind: str, field: str):
    """The `field` of the last line of type `kind` in a piece of a JSONL file."""
    mark = b'"' + kind.encode() + b'"'
    upper = len(data)
    for _ in range(20):
        at = data.rfind(mark, 0, upper)
        if at < 0:
            return None
        start = data.rfind(b"\n", 0, at) + 1
        end = data.find(b"\n", at)
        end = len(data) if end < 0 else end
        try:
            j = json.loads(data[start:end])
        except ValueError:
            j = None
        if isinstance(j, dict) and j.get("type") == kind and isinstance(j.get(field), str) \
                and j[field]:
            return j[field]
        upper = start
    return None


class Row:
    """One line of the list: a session open here (kind "here") or one handed
    over to another machine (kind "away")."""
    __slots__ = ("id", "pid", "name", "project", "state", "age", "recent", "kind", "machine",
                 "can_open", "status", "transfer")

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))

    def __eq__(self, other):
        return isinstance(other, Row) and all(getattr(self, k) == getattr(other, k)
                                              for k in self.__slots__)

    def __repr__(self):
        return f"Row({self.name!r}, {self.state}, {self.age})"


class Model:
    """The sessions, as the corner lists them.  A session that goes from
    working to idle is "done" until you click it or it works again; the marks
    are kept in a file, so they outlast the tray restarting."""

    def __init__(self, claude_home, run_dir, records=None, clock=time.time, moving=None):
        self.moving = moving or aht.transfers      # handovers and take-backs running now
        self.away_stale = False         # one ended: the tray lists the handed-over ones again
        self.moved = set()
        self.sessions = Path(claude_home) / "sessions"
        self.projects = Path(claude_home) / "projects"
        self.state_file = Path(run_dir) / STATE_FILE
        self.records = records or self._records
        self.clock = clock
        self.rows = []
        self.away = []              # aht.corner_away(), as the tray last asked
        self.machines = []          # the machines set up here, for Send to
        self.note = None            # why a click went nowhere, for a few seconds
        self.note_until = 0.0
        self.last, self.done, self.run_since = {}, {}, {}
        self.by_pid, self.titles = {}, {}
        try:
            j = json.loads(self.state_file.read_text(encoding="utf-8"))
            self.last = {k: v for k, v in (j.get("last") or {}).items() if isinstance(v, str)}
            self.done = {k: float(v) for k, v in (j.get("done") or {}).items()}
        except (OSError, ValueError, TypeError, AttributeError):
            pass

    def _records(self):
        """[(pid, record or None)] for the records whose process runs: None
        when it was caught mid-write."""
        out = []
        try:
            files = list(self.sessions.glob("*.json"))
        except OSError:
            return out
        for f in files:
            try:
                pid = int(f.stem)
            except ValueError:
                continue
            try:
                rec = json.loads(f.read_text(encoding="utf-8-sig"))
                rec = rec if isinstance(rec, dict) else None
            except (OSError, ValueError):
                rec = None
            if aht.session_record_live(pid, rec or {}):
                out.append((pid, rec))
        return out

    def _track(self, key, st, at, now):
        """(state, since) of one session, keeping its marks."""
        working, was = st in WORKING, self.last.get(key) in WORKING
        if working:
            self.done.pop(key, None)
            if not was or key not in self.run_since:
                self.run_since[key] = at
        else:
            self.run_since.pop(key, None)
            if st == "idle" and was:
                self.done[key] = now
        state = ("waiting" if st == "waiting" else "working" if working else
                 "done" if key in self.done else "idle")
        since = (self.run_since.get(key, at) if working else
                 self.done.get(key, at) if state == "done" else at)
        return state, since

    def poll(self) -> bool:
        """Look again; whether the rows changed."""
        now = self.clock()
        status, found = {}, {}
        for pid, rec in self.records():
            if not rec or not isinstance(rec.get("sessionId"), str):
                old = self.by_pid.get(pid)                  # caught mid-write: as it was
                if old:
                    found[pid] = old
                    status[old[0].id] = old[1]
                continue
            sid = rec["sessionId"]
            st = str(rec.get("status") or "idle")
            at = rec.get("statusUpdatedAt")
            at = float(at) / 1000 if isinstance(at, (int, float)) and not isinstance(at, bool) \
                else now
            state, since = self._track(sid, st, at, now)
            status[sid] = st
            cwd = str(rec.get("cwd") or "")
            own = rec.get("name").strip() if isinstance(rec.get("name"), str) else ""
            custom, auto = self._title(sid, cwd)
            name = (custom or (own if rec.get("nameSource") == "user" and own else None)
                    or auto or own or ntpath.basename(cwd.rstrip("\\/")) or "session")
            found[pid] = (Row(id=sid, pid=pid, name=name, project=cwd, state=state,
                              age="" if state == "idle" else age(now - since),
                              recent=1e12 + since if state == "working" else since,
                              kind="here", machine=None, can_open=True, status=st), st)
        self.by_pid = found
        one = {}                                            # one row per session
        for row, _st in found.values():
            if row.id not in one or one[row.id].pid < row.pid:
                one[row.id] = row
        for a in self.away:
            key = a["id"]
            if key in one:
                continue
            st = {"working": "busy", "waiting": "waiting", "idle": "idle"}.get(a.get("state"))
            at = a.get("since") if isinstance(a.get("since"), (int, float)) else None
            if st is None:                                  # not heard lately
                status[key] = self.last.get(key) or "unknown"
                state, since = "unknown", at
            else:
                state, since = self._track(key, st, at or now, now)
                status[key] = st
            one[key] = Row(id=key, pid=0, name=a.get("name") or "session",
                           project=a.get("project") or "", state=state,
                           age="" if state in ("idle", "unknown") or since is None
                           else age(now - since),
                           recent=(1e12 + since if state == "working" else since) or 0.0,
                           kind="away", machine=a.get("machine"),
                           can_open=bool(a.get("can_open")), status=st or "unknown")
        # a handover or take-back under way: on the session's row, or a row
        # of its own while the session is on its way there
        moving = [t for t in (self.moving() or []) if isinstance(t, dict)]
        keys = {str(t.get("uuid") or t.get("project")) for t in moving}
        if keys != self.moved:
            self.away_stale = self.away_stale or bool(self.moved - keys)
            self.moved = keys
        for t in moving:
            proj = os.path.normcase(os.path.realpath(str(t.get("project") or "")))
            row = next((r for r in one.values()
                        if r.kind == "away" and r.project
                        and os.path.normcase(os.path.realpath(r.project)) == proj), None)
            if row is None:
                sid = t.get("session")
                key = "away:" + str(sid or t.get("uuid"))
                custom, auto = self._title(sid, str(t.get("project") or "")) if sid else (None, None)
                row = one[key] = Row(
                    id=key, pid=0, name=custom or auto
                    or ntpath.basename(str(t.get("project") or "").rstrip("\\/")) or "session",
                    project=str(t.get("project") or ""), state="moving", age="",
                    recent=1e12 + float(t.get("started") or now), kind="away",
                    machine=t.get("remote") or "?", can_open=False, status="moving")
            row.transfer = {k: t.get(k) for k in ("kind", "stage", "percent", "done_bytes",
                                                  "total_bytes", "eta")}
        self.done = {k: v for k, v in self.done.items() if k in status}
        if status != self.last:
            self.last = status
            self.save()
        rows = sorted(one.values(), key=lambda r: (-r.recent, r.name.lower(), r.pid))
        changed = rows != self.rows
        self.rows = rows
        if self.note and now >= self.note_until:
            self.note = None
            changed = True
        return changed

    def _title(self, sid, cwd):
        """(custom, automatic) title from the session's conversation file: the
        last one a rename, the app or aht's hook set, and Claude's own.  Only
        what was added since the last look is read; the first look reads up
        to 8 MB."""
        for c in dict.fromkeys(x for x in (cwd, os.path.realpath(cwd) if cwd else "") if x):
            path = self.projects / aht._key_claude(c) / f"{sid}.jsonl"
            try:
                size = path.stat().st_size
            except OSError:
                continue
            end, custom, auto = self.titles.get(str(path), (0, "", ""))
            if size < end:                                  # written anew
                end, custom, auto = 0, "", ""
            if size > end:
                start = end if end else max(0, size - (8 << 20))
                try:
                    with open(path, "rb") as fh:
                        fh.seek(start)
                        data = fh.read(size - start)
                except OSError:
                    return None, None
                custom = _last_of(data, "custom-title", "customTitle") or custom
                auto = _last_of(data, "ai-title", "aiTitle") or auto
                nl = data.rfind(b"\n")
                if nl >= 0:                                 # a line half written: again
                    end = start + nl + 1
                self.titles[str(path)] = (end, custom, auto)
            return custom or None, auto or None
        return None, None

    def say(self, text: str, secs: float = 8):
        self.note, self.note_until = text, self.clock() + secs

    def seen(self, key):
        """You looked at it: it is no longer "done"."""
        if self.done.pop(key, None) is not None:
            self.save()

    def summary(self) -> str:
        n = lambda s: sum(1 for r in self.rows if r.state == s)     # noqa: E731
        parts = [f"{n(s)} {w}" for s, w in (("waiting", "waiting"), ("done", "done"),
                                             ("working", "working")) if n(s)]
        moving = sum(1 for r in self.rows if r.transfer)
        if moving:
            parts.append(f"{moving} on the way")
        if not self.rows:
            return "No Claude session open"
        return " · ".join(parts) if parts else f"{len(self.rows)} open, all idle"

    def save(self):
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_file.with_name(self.state_file.name + ".new")
            tmp.write_text(json.dumps({"last": self.last, "done": self.done}), encoding="utf-8")
            os.replace(tmp, self.state_file)
        except OSError as e:
            aht.warn(f"CORNER the session corner's marks were not saved: {e}")


def left_text(eta) -> str:
    return ("under a minute left" if eta < 60 else f"{round(eta / 60)} min left"
            if eta < 3600 else f"{eta // 3600} h {eta % 3600 // 60} min left")


def transfer_text(t: dict) -> str:
    """The second line of a session on its way (its arrow says which way):
    how much went, of how much, and how long it still takes; before any
    data moves, the stage."""
    done, total, eta = t.get("done_bytes"), t.get("total_bytes"), t.get("eta")
    if done is None:
        st = str(t.get("stage") or "").strip()
        return (st[:1].upper() + st[1:]) if st else (
            "Taking back …" if t.get("kind") == "reclaim" else "Sending …")
    out = aht._human(done) + (f" of {aht._human(total)}" if total else "")
    return out + (" · " + left_text(int(eta)) if isinstance(eta, (int, float)) else "")


def right_text(r: Row) -> str:
    """What the list shows at the right of a session."""
    if r.transfer:
        pct = r.transfer.get("percent")
        arrow = "←" if r.transfer.get("kind") == "reclaim" else "→"
        return f"{arrow} {r.machine}" + (f" {pct}%" if isinstance(pct, int) else "")
    t = ("waits " + r.age if r.state == "waiting" and r.age else r.age or "")
    if r.kind == "away":
        return f"→ {r.machine}" + (f" {t}" if t else " ?" if r.state == "unknown" else "")
    return t


def tip_text(r: Row) -> str:
    """The note that shows over a session."""
    if r.transfer:
        where = ("from " if r.transfer.get("kind") == "reclaim" else "to ") + str(r.machine)
        verb = "Taking back" if r.transfer.get("kind") == "reclaim" else "Sending"
        return f"{r.name}\n{r.project}\n{verb} {where}: {transfer_text(r.transfer)}."
    if r.kind == "away":
        how = ("not heard from lately" if r.state == "unknown" else
               {"working": "working", "waiting": "waiting for you", "done": "done",
                "idle": "idle"}.get(r.state, r.state))
        return (f"{r.name}\n{r.project}\nOn {r.machine}: {how}.\n"
                + ("A click opens it; right-click for Take Back." if r.can_open else
                   "Right-click for Take Back."))
    return (f"{r.name}\n{r.project}\n"
            + ("Done. A click goes to its tab and clears the mark." if r.state == "done"
               else "A click goes to its tab; right-click for more."))


def menu_items(r: Row, machines: list) -> list:
    """The right-click menu of a session: [(label, action or None for grayed,
    is default)], "-" for a line between.  Actions: "goto", "branch",
    "send:<machine>", "open", "take-back", "hide"."""
    if r.transfer:
        return [("Open Session (once it is there)" if r.transfer.get("kind") != "reclaim"
                 else "Go to Tab (once it is back)", None, False), "-",
                ("Hide the List", "hide", False)]
    if r.kind == "away":
        return [("Open Session", "open" if r.can_open else None, True),
                ("Take Back…", "take-back", False), "-", ("Hide the List", "hide", False)]
    busy = r.status in WORKING or r.status == "waiting"
    later = " (once it has finished)" if r.status in WORKING else \
        " (answer it first)" if r.status == "waiting" else ""
    out = [("Go to Tab", "goto", True), ("Branch…" + later, None if busy else "branch", False)]
    if machines:
        out.append("-")
        out += [(f"Send to {m}…" + later, None if busy else "send:" + m, False) for m in machines]
    else:
        out.append(("Send to Another Machine (add one in aht's window first)", None, False))
    return out + ["-", ("Hide the List", "hide", False)]


def send_question(res: dict) -> str:
    """What the confirmation of Send to <machine> says."""
    h = res.get("handover") or {}
    to = res.get("to")
    there = h.get("there_path") or "the same place"
    lines = [f"Send “{res.get('label')}” to {to}?", "",
             f"The session ends here, and its project folder ({res.get('project')}) "
             f"and its history go to {to}, to {there}."]
    if h.get("pc"):
        lines.append(f"{to} is a PC: no session starts there; its tray offers Continue here.")
    else:
        lines.append(f"The session goes on there, and this tab connects to it. On {to} it "
                     "keeps working when this computer sleeps or loses its connection.")
    lines += ["", "Bring it back later with Take Back… (right-click it in this list, or in "
              "aht's window)."]
    for w in res.get("warnings") or []:
        lines += ["", "Note: " + w]
    return "\n".join(lines)


# ---- the window ---------------------------------------------------------------- #

PAD, HEAD, ROW, MORE, ICON_W, GAP, INSET = 5, 20, 22, 18, 14, 7, 6
TLINE = 18                          # a session on its way: its second line and bar
EDGE = 6
LEFT, RIGHT, TOP, BOTTOM = 1, 2, 4, 8
AWAY_RGB = (37, 99, 235)            # the folder badge's "handed over" blue

THEMES = {
    False: {"bg": (249, 249, 249), "fg": (27, 27, 27), "dim": (96, 96, 96),
            "working": (0, 103, 192), "waiting": (214, 110, 0), "done": (16, 124, 16),
            "away": AWAY_RGB},
    True: {"bg": (43, 43, 43), "fg": (255, 255, 255), "dim": (170, 170, 170),
           "working": (96, 205, 255), "waiting": (255, 165, 60), "done": (108, 203, 95),
           "away": (120, 160, 255)},
}

# Segoe Fluent Icons (Windows 11), else Segoe MDL2 Assets (Windows 10)
GLYPH = {"working": "", "done": "", "idle": "", "unknown": "",
         "circle": "", "bang": "", "close": "",
         "send": "\uE898", "back": "\uE896"}


def blend(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def rgb(c):
    return c[0] | c[1] << 8 | c[2] << 16


if os.name == "nt":
    from ctypes import wintypes as W

    _u = ctypes.WinDLL("user32", use_last_error=True)
    _g = ctypes.WinDLL("gdi32", use_last_error=True)
    _k = ctypes.WinDLL("kernel32", use_last_error=True)
    try:
        _dwm = ctypes.WinDLL("dwmapi")
    except OSError:
        _dwm = None
    try:
        _cc = ctypes.WinDLL("comctl32")
    except OSError:
        _cc = None

    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
    H = ctypes.c_void_p

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [("style", W.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                    ("cbWndExtra", ctypes.c_int), ("hInstance", H), ("hIcon", H),
                    ("hCursor", H), ("hbrBackground", H), ("lpszMenuName", W.LPCWSTR),
                    ("lpszClassName", W.LPCWSTR)]

    class PAINTSTRUCT(ctypes.Structure):
        _fields_ = [("hdc", H), ("fErase", W.BOOL), ("rcPaint", W.RECT),
                    ("fRestore", W.BOOL), ("fIncUpdate", W.BOOL), ("rgbReserved", ctypes.c_byte * 32)]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", W.DWORD), ("rcMonitor", W.RECT), ("rcWork", W.RECT),
                    ("dwFlags", W.DWORD)]

    class TRACKMOUSEEVENT(ctypes.Structure):
        _fields_ = [("cbSize", W.DWORD), ("dwFlags", W.DWORD), ("hwndTrack", H),
                    ("dwHoverTime", W.DWORD)]

    class TOOLINFOW(ctypes.Structure):          # the size every comctl32 takes
        _fields_ = [("cbSize", W.UINT), ("uFlags", W.UINT), ("hwnd", H), ("uId", ctypes.c_size_t),
                    ("rect", W.RECT), ("hinst", H), ("lpszText", ctypes.c_wchar_p),
                    ("lParam", W.LPARAM)]

    class SIZE(ctypes.Structure):
        _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]

    for fn, res, args in (
            ("CreateWindowExW", H, [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_int, H, H, H, H]),
            ("DefWindowProcW", LRESULT, [H, W.UINT, W.WPARAM, W.LPARAM]),
            ("RegisterClassW", W.ATOM, [ctypes.POINTER(WNDCLASSW)]),
            ("BeginPaint", H, [H, ctypes.POINTER(PAINTSTRUCT)]),
            ("EndPaint", W.BOOL, [H, ctypes.POINTER(PAINTSTRUCT)]),
            ("GetDC", H, [H]), ("ReleaseDC", ctypes.c_int, [H, H]),
            ("FillRect", ctypes.c_int, [H, ctypes.POINTER(W.RECT), H]),
            ("DrawTextW", ctypes.c_int, [H, W.LPCWSTR, ctypes.c_int, ctypes.POINTER(W.RECT), W.UINT]),
            ("SetWindowPos", W.BOOL, [H, H, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                      W.UINT]),
            ("ShowWindow", W.BOOL, [H, ctypes.c_int]),
            ("InvalidateRect", W.BOOL, [H, ctypes.c_void_p, W.BOOL]),
            ("SetTimer", ctypes.c_size_t, [H, ctypes.c_size_t, W.UINT, ctypes.c_void_p]),
            ("KillTimer", W.BOOL, [H, ctypes.c_size_t]),
            ("GetCursorPos", W.BOOL, [ctypes.POINTER(W.POINT)]),
            ("GetWindowRect", W.BOOL, [H, ctypes.POINTER(W.RECT)]),
            ("SetCapture", H, [H]), ("ReleaseCapture", W.BOOL, []), ("GetCapture", H, []),
            ("LoadCursorW", H, [H, ctypes.c_void_p]), ("SetCursor", H, [H]),
            ("TrackMouseEvent", W.BOOL, [ctypes.POINTER(TRACKMOUSEEVENT)]),
            ("MonitorFromPoint", H, [W.POINT, W.DWORD]),
            ("MonitorFromWindow", H, [H, W.DWORD]),
            ("GetMonitorInfoW", W.BOOL, [H, ctypes.POINTER(MONITORINFO)]),
            ("CreatePopupMenu", H, []), ("DestroyMenu", W.BOOL, [H]),
            ("AppendMenuW", W.BOOL, [H, W.UINT, ctypes.c_size_t, W.LPCWSTR]),
            ("SetMenuDefaultItem", W.BOOL, [H, W.UINT, W.UINT]),
            ("TrackPopupMenu", ctypes.c_int, [H, W.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                              H, ctypes.c_void_p]),
            ("SetForegroundWindow", W.BOOL, [H]), ("PostMessageW", W.BOOL, [H, W.UINT, W.WPARAM, W.LPARAM]),
            ("SendMessageW", LRESULT, [H, W.UINT, W.WPARAM, W.LPARAM]),
            ("GetSystemMetrics", ctypes.c_int, [ctypes.c_int]),
            ("IsWindowVisible", W.BOOL, [H]), ("DestroyWindow", W.BOOL, [H]),
            ("ScreenToClient", W.BOOL, [H, ctypes.POINTER(W.POINT)]),
            ("AllowSetForegroundWindow", W.BOOL, [W.DWORD]),
            ("GetMessageW", W.BOOL, [ctypes.POINTER(W.MSG), H, W.UINT, W.UINT]),
            ("TranslateMessage", W.BOOL, [ctypes.POINTER(W.MSG)]),
            ("DispatchMessageW", LRESULT, [ctypes.POINTER(W.MSG)]),
            ("IsDialogMessageW", W.BOOL, [H, ctypes.POINTER(W.MSG)]),
            ("EnableWindow", W.BOOL, [H, W.BOOL]), ("SetFocus", H, [H]),
            ("GetWindowTextW", ctypes.c_int, [H, W.LPWSTR, ctypes.c_int]),
            ("GetWindowTextLengthW", ctypes.c_int, [H]),
            ("IsWindow", W.BOOL, [H])):
        f = getattr(_u, fn)
        f.restype, f.argtypes = res, args
    try:
        _u.GetDpiForWindow.restype, _u.GetDpiForWindow.argtypes = W.UINT, [H]
    except AttributeError:
        pass
    for fn, res, args in (
            ("CreateCompatibleDC", H, [H]), ("CreateCompatibleBitmap", H, [H, ctypes.c_int, ctypes.c_int]),
            ("SelectObject", H, [H, H]), ("DeleteObject", W.BOOL, [H]), ("DeleteDC", W.BOOL, [H]),
            ("BitBlt", W.BOOL, [H, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, H,
                                ctypes.c_int, ctypes.c_int, W.DWORD]),
            ("CreateSolidBrush", H, [W.COLORREF]), ("SetTextColor", W.COLORREF, [H, W.COLORREF]),
            ("SetBkMode", ctypes.c_int, [H, ctypes.c_int]),
            ("CreateFontW", H, [ctypes.c_int] * 5 + [W.DWORD] * 8 + [W.LPCWSTR]),
            ("GetTextFaceW", ctypes.c_int, [H, ctypes.c_int, W.LPWSTR]),
            ("GetTextExtentPoint32W", W.BOOL, [H, W.LPCWSTR, ctypes.c_int, ctypes.POINTER(SIZE)]),
            ("RoundRect", W.BOOL, [H] + [ctypes.c_int] * 6),
            ("GetStockObject", H, [ctypes.c_int]),
            ("CreateDIBSection", H, [H, ctypes.c_void_p, W.UINT, ctypes.POINTER(ctypes.c_void_p),
                                     H, W.DWORD])):
        f = getattr(_g, fn)
        f.restype, f.argtypes = res, args
    _k.GetModuleHandleW.restype, _k.GetModuleHandleW.argtypes = H, [W.LPCWSTR]


WM_DESTROY, WM_PAINT, WM_CLOSE, WM_ERASEBKGND = 0x2, 0xF, 0x10, 0x14
WM_SETTINGCHANGE, WM_SETCURSOR, WM_MOUSEACTIVATE = 0x1A, 0x20, 0x21
WM_DISPLAYCHANGE, WM_NOTIFY, WM_COMMAND, WM_TIMER = 0x7E, 0x4E, 0x111, 0x113
WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_LBUTTONDBLCLK = 0x200, 0x201, 0x202, 0x203
WM_RBUTTONUP, WM_CAPTURECHANGED, WM_MOUSELEAVE, WM_DPICHANGED = 0x205, 0x215, 0x2A3, 0x2E0
WM_SETFONT, WM_APP, WM_USER = 0x30, 0x8000, 0x400
WM_RUN = WM_APP + 3                         # run what a thread handed over
MA_NOACTIVATE, HTCLIENT = 3, 1
WS_POPUP, WS_VISIBLE, WS_CHILD, WS_TABSTOP = 0x80000000, 0x10000000, 0x40000000, 0x10000
WS_CAPTION, WS_SYSMENU, WS_BORDER = 0xC00000, 0x80000, 0x800000
WS_EX_TOPMOST, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x8, 0x80, 0x08000000
WS_EX_DLGMODALFRAME, WS_EX_CLIENTEDGE = 0x1, 0x200
CS_DBLCLKS, CS_DROPSHADOW = 0x8, 0x20000
SWP_NOZORDER, SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x4, 0x10, 0x40
SW_HIDE, SW_SHOWNOACTIVATE = 0, 4
HWND_TOPMOST = -1
DT_LEFT, DT_RIGHT, DT_VCENTER, DT_SINGLELINE, DT_END_ELLIPSIS = 0x0, 0x2, 0x4, 0x20, 0x8000
DT_NOPREFIX, DT_WORDBREAK, DT_CALCRECT, DT_CENTER = 0x800, 0x10, 0x400, 0x1
TRANSPARENT, NULL_PEN, SRCCOPY = 1, 8, 0x00CC0020
IDC_ARROW, IDC_SIZENWSE, IDC_SIZENESW, IDC_SIZEWE, IDC_SIZENS = 32512, 32642, 32643, 32644, 32645
TME_LEAVE = 0x2
MONITOR_DEFAULTTONEAREST, MONITOR_DEFAULTTOPRIMARY = 2, 1
MF_STRING, MF_GRAYED, MF_SEPARATOR = 0x0, 0x1, 0x800
TPM_RIGHTBUTTON, TPM_RETURNCMD, TPM_NONOTIFY = 0x2, 0x100, 0x80
SM_CXDRAG, SM_CYDRAG = 68, 69
TTM_ADDTOOLW, TTM_DELTOOLW, TTM_SETMAXTIPWIDTH, TTM_ACTIVATE = WM_USER + 50, WM_USER + 51, \
    WM_USER + 24, WM_USER + 1
TTS_ALWAYSTIP, TTS_NOPREFIX, TTF_SUBCLASS = 0x1, 0x2, 0x10
ES_AUTOHSCROLL, BS_DEFPUSHBUTTON, BS_PUSHBUTTON = 0x80, 0x1, 0x0
EM_SETSEL = 0xB1
IDOK, IDCANCEL = 1, 2
DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND = 33, 2


def _lo(v):
    return ctypes.c_short(v & 0xFFFF).value


def _hi(v):
    return ctypes.c_short((v >> 16) & 0xFFFF).value


def dark_mode() -> bool:
    """Windows' "app mode" is dark."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows"
                            r"\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


class Painter:
    """Fonts and drawing at one DPI and theme."""

    def __init__(self, dpi: int, dark: bool):
        self.dpi, self.dark, self.t = dpi, dark, THEMES[dark]
        s = dpi / 96
        self.s = s

        def font(px, weight=400, face="Segoe UI"):
            return _g.CreateFontW(-round(px * s), 0, 0, 0, weight, 0, 0, 0, 1, 0, 0, 5, 0, face)
        self.text = font(12)
        self.bold = font(12, 600)
        self.small = font(11)
        self.head = font(11, 600)
        self.icons = font(12, 400, "Segoe Fluent Icons")
        self.x = font(8, 400, "Segoe Fluent Icons")
        dc = _u.GetDC(None)
        old = _g.SelectObject(dc, self.icons)
        face = ctypes.create_unicode_buffer(64)
        _g.GetTextFaceW(dc, 64, face)
        _g.SelectObject(dc, old)
        _u.ReleaseDC(None, dc)
        if face.value != "Segoe Fluent Icons":             # Windows 10
            for f in (self.icons, self.x):
                _g.DeleteObject(f)
            self.icons = font(12, 400, "Segoe MDL2 Assets")
            self.x = font(8, 400, "Segoe MDL2 Assets")

    def px(self, v):
        return round(v * self.s)

    def close(self):
        for f in (self.text, self.bold, self.small, self.head, self.icons, self.x):
            _g.DeleteObject(f)

    def measure(self, dc, font, text) -> int:
        old = _g.SelectObject(dc, font)
        sz = SIZE()
        _g.GetTextExtentPoint32W(dc, text, len(text), ctypes.byref(sz))
        _g.SelectObject(dc, old)
        return sz.cx

    def fill(self, dc, rect, color, radius=0):
        b = _g.CreateSolidBrush(rgb(color))
        if radius:
            oldb, oldp = _g.SelectObject(dc, b), _g.SelectObject(dc, _g.GetStockObject(NULL_PEN))
            _g.RoundRect(dc, rect[0], rect[1], rect[2] + 1, rect[3] + 1, radius * 2, radius * 2)
            _g.SelectObject(dc, oldb)
            _g.SelectObject(dc, oldp)
        else:
            _u.FillRect(dc, ctypes.byref(W.RECT(*rect)), b)
        _g.DeleteObject(b)

    def write(self, dc, font, text, rect, color, flags):
        old = _g.SelectObject(dc, font)
        _g.SetTextColor(dc, rgb(color))
        r = W.RECT(*rect)
        _u.DrawTextW(dc, text, len(text), ctypes.byref(r), flags | DT_NOPREFIX)
        _g.SelectObject(dc, old)

    def wrapped_height(self, dc, font, text, width) -> int:
        old = _g.SelectObject(dc, font)
        r = W.RECT(0, 0, width, 0)
        _u.DrawTextW(dc, text, len(text), ctypes.byref(r), DT_WORDBREAK | DT_CALCRECT | DT_NOPREFIX)
        _g.SelectObject(dc, old)
        return r.bottom


def layout(m: Model, width_px: int, most: int, p: "Painter", dc) -> dict:
    """Where everything goes, in pixels: {"size", "head", "close", "note",
    "rows": [(row, rect)], "more"}."""
    pad, head = p.px(PAD), p.px(HEAD)
    y = pad
    out = {"head": (pad, y, width_px - pad, y + head)}
    cx = p.px(14)
    out["close"] = (width_px - pad - cx - p.px(2), y + (head - cx) // 2, width_px - pad - p.px(2),
                    y + (head - cx) // 2 + cx)
    y += head
    if m.note:
        h = p.wrapped_height(dc, p.small, m.note, width_px - 2 * (pad + p.px(INSET)))
        out["note"] = (pad + p.px(INSET), y, width_px - pad - p.px(INSET), y + h)
        y += h + p.px(3)
    rows = []
    for r in m.rows[:max(0, most)]:
        h = p.px(ROW + (TLINE if r.transfer else 0))
        rows.append((r, (pad, y, width_px - pad, y + h)))
        y += h
    out["rows"] = rows
    if len(m.rows) > most:
        out["more"] = (pad + p.px(INSET), y, width_px - pad, y + p.px(MORE))
        y += p.px(MORE)
    out["size"] = (width_px, y + pad)
    return out


def paint(dc, m: Model, lay: dict, p: "Painter", hover=None, hover_close=False):
    t = p.t
    w, h = lay["size"]
    p.fill(dc, (0, 0, w, h), blend(t["bg"], t["fg"], 0.16))     # a hairline edge, then the list
    p.fill(dc, (1, 1, w - 1, h - 1), t["bg"])
    _g.SetBkMode(dc, TRANSPARENT)
    x0, y0, x1, y1 = lay["head"]
    ix = x0 + p.px(INSET)
    p.write(dc, p.head, "∞", (ix, y0, ix + p.px(14), y1), t["dim"], DT_SINGLELINE | DT_VCENTER)
    cx0 = lay["close"][0]
    p.write(dc, p.small, m.summary(), (ix + p.px(14), y0, cx0 - p.px(6), y1), t["dim"],
            DT_SINGLELINE | DT_VCENTER | DT_END_ELLIPSIS)
    if hover_close:
        p.fill(dc, lay["close"], blend(t["bg"], t["fg"], 0.12), p.px(3))
    p.write(dc, p.x, GLYPH["close"], lay["close"], t["dim"], DT_SINGLELINE | DT_VCENTER | DT_CENTER)
    if "note" in lay:
        p.write(dc, p.small, m.note, lay["note"], t["waiting"], DT_WORDBREAK)
    for r, (a, b, c, d) in lay["rows"]:
        bg = (blend(t["bg"], t["fg"], 0.09) if hover == r.id else
              blend(t["bg"], t["done"], 0.13) if r.state == "done" else
              blend(t["bg"], t["waiting"], 0.13) if r.state == "waiting" else None)
        if bg:
            p.fill(dc, (a, b, c, d), bg, p.px(5))
        ix = a + p.px(INSET)
        if r.transfer:                          # the second line and the bar
            line2 = (ix + p.px(ICON_W + GAP), b + p.px(ROW) - p.px(3), c - p.px(INSET),
                     d - p.px(5))
            p.write(dc, p.small, transfer_text(r.transfer), line2, t["dim"],
                    DT_SINGLELINE | DT_VCENTER | DT_END_ELLIPSIS)
            bar = (line2[0], d - p.px(4), line2[2], d - p.px(2))
            p.fill(dc, bar, blend(t["bg"], t["fg"], 0.12))
            pct = r.transfer.get("percent")
            if isinstance(pct, int) and pct > 0:
                p.fill(dc, (bar[0], bar[1], bar[0] + (bar[2] - bar[0]) * min(pct, 100) // 100,
                            bar[3]), t["away"])
            d = b + p.px(ROW)
        icon = (ix, b, ix + p.px(ICON_W), d)
        flags = DT_SINGLELINE | DT_VCENTER | DT_CENTER
        if r.transfer:
            p.write(dc, p.icons, GLYPH["back" if r.transfer.get("kind") == "reclaim" else "send"],
                    icon, t["away"], flags)
        elif r.state == "waiting":
            p.write(dc, p.icons, GLYPH["circle"], icon, t["waiting"], flags)
            p.write(dc, p.icons, GLYPH["bang"], icon, t["bg"], flags)
        else:
            colour = {"working": t["working"], "done": t["done"]}.get(r.state, t["dim"])
            p.write(dc, p.icons, GLYPH.get(r.state, GLYPH["idle"]), icon, colour, flags)
        right = right_text(r)
        rw = p.measure(dc, p.small, right) if right else 0
        rx = c - p.px(INSET)
        if right:
            p.write(dc, p.small, right, (rx - rw, b, rx, d),
                    t["away"] if r.kind == "away" else t["dim"], DT_SINGLELINE | DT_VCENTER)
        nx = ix + p.px(ICON_W + GAP)
        p.write(dc, p.bold if r.state in ("done", "waiting") else p.text, r.name,
                (nx, b, rx - rw - (p.px(6) if right else 0), d),
                t["dim"] if r.state in ("idle", "unknown") and not r.transfer else t["fg"],
                DT_SINGLELINE | DT_VCENTER | DT_END_ELLIPSIS)
    if "more" in lay:
        p.write(dc, p.small, f"+{len(m.rows) - len(lay['rows'])} more", lay["more"], t["dim"],
                DT_SINGLELINE | DT_VCENTER)


def snapshot(m: Model, path: str, dark: bool = False, width: int = 260, most: int = 12,
             dpi: int = 96) -> tuple:
    """Draw the list into a picture file (BMP), as it would show: for tests
    and the tray's selftest.  -> its size."""
    p = Painter(dpi, dark)
    screen = _u.GetDC(None)
    dc = _g.CreateCompatibleDC(screen)
    lay = layout(m, p.px(width), most, p, dc)
    w, h = lay["size"]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", W.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                    ("biPlanes", W.WORD), ("biBitCount", W.WORD), ("biCompression", W.DWORD),
                    ("biSizeImage", W.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                    ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", W.DWORD),
                    ("biClrImportant", W.DWORD)]
    bi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, h, 1, 32, 0, w * h * 4, 0, 0, 0, 0)
    bits = ctypes.c_void_p()
    bmp = _g.CreateDIBSection(dc, ctypes.byref(bi), 0, ctypes.byref(bits), None, 0)
    old = _g.SelectObject(dc, bmp)
    paint(dc, m, lay, p)
    data = ctypes.string_at(bits, w * h * 4)
    _g.SelectObject(dc, old)
    _g.DeleteObject(bmp)
    _g.DeleteDC(dc)
    _u.ReleaseDC(None, screen)
    p.close()
    import struct
    head = struct.pack("<2sIHHI", b"BM", 54 + len(data), 0, 0, 54) + bytes(bi)
    Path(path).write_bytes(head + data)
    return w, h


class Corner:
    """The list's window.  `hooks`: what the tray lends it — open_window(path,
    do), switch_off(), ask(title, text) -> bool, tell(title, text),
    note(what, exc) for its log."""

    def __init__(self, model: Model, hooks: dict, run_dir):
        self.m, self.hooks = model, hooks
        self.place_file = Path(run_dir) / PLACE_FILE
        self.hwnd = None
        self.tip = None
        self.tips = []
        self.p = None
        self.lay = None
        self.hover = None
        self.hover_close = False
        self.tracking = False
        self.held = None
        self.queue = []
        self.lock = threading.Lock()
        self.width, self.most, self.spot = 260, 12, None
        try:
            j = json.loads(self.place_file.read_text(encoding="utf-8"))
            self.width = max(150, min(720, int(j.get("width") or 260)))
            self.most = max(0, int(j["rows"])) if j.get("rows") is not None else 12
            if isinstance(j.get("x"), int) and isinstance(j.get("y"), int):
                self.spot = (j["x"], j["y"])
        except (OSError, ValueError, TypeError):
            pass
        self._proc = WNDPROC(self._wndproc)

    # -- life ---------------------------------------------------------------
    def create(self):
        hinst = _k.GetModuleHandleW(None)
        wc = WNDCLASSW()
        wc.style = CS_DBLCLKS | CS_DROPSHADOW
        wc.lpfnWndProc = self._proc
        wc.hInstance = hinst
        wc.hCursor = _u.LoadCursorW(None, ctypes.c_void_p(IDC_ARROW))
        wc.lpszClassName = "aht_corner_wnd"
        _u.RegisterClassW(ctypes.byref(wc))
        self.hwnd = _u.CreateWindowExW(WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
                                       "aht_corner_wnd", "aht sessions", WS_POPUP,
                                       0, 0, 10, 10, None, None, hinst, None)
        if not self.hwnd:
            raise OSError(f"no window for the session corner (error {ctypes.get_last_error()})")
        if _dwm:
            pref = ctypes.c_int(DWMWCP_ROUND)
            _dwm.DwmSetWindowAttribute(ctypes.c_void_p(self.hwnd), DWMWA_WINDOW_CORNER_PREFERENCE,
                                       ctypes.byref(pref), 4)
        self._painter()
        if _cc:
            self.tip = _u.CreateWindowExW(WS_EX_TOPMOST, "tooltips_class32", None,
                                          WS_POPUP | TTS_ALWAYSTIP | TTS_NOPREFIX,
                                          0, 0, 0, 0, self.hwnd, None, hinst, None)
            if self.tip:
                _u.SendMessageW(self.tip, TTM_SETMAXTIPWIDTH, 0, 480)

    def shown(self) -> bool:
        return bool(self.hwnd) and bool(_u.IsWindowVisible(self.hwnd))

    def show(self):
        if not self.hwnd:
            self.create()
        self.m.poll()
        self.place(force=True)
        _u.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
        _u.SetWindowPos(self.hwnd, ctypes.c_void_p(HWND_TOPMOST), 0, 0, 0, 0,
                        0x1 | 0x2 | SWP_NOACTIVATE)          # NOSIZE | NOMOVE
        _u.SetTimer(self.hwnd, 1, 1500, None)

    def hide(self):
        if self.hwnd:
            _u.KillTimer(self.hwnd, 1)
            _u.ShowWindow(self.hwnd, SW_HIDE)

    def post(self, fn):
        """Run `fn` on the window's thread (from another thread)."""
        with self.lock:
            self.queue.append(fn)
        if self.hwnd:
            _u.PostMessageW(self.hwnd, WM_RUN, 0, 0)

    def _painter(self):
        dpi = 96
        try:
            dpi = _u.GetDpiForWindow(self.hwnd) or 96
        except Exception:
            pass
        if self.p:
            self.p.close()
        self.p = Painter(dpi, dark_mode())

    # -- where it goes ------------------------------------------------------
    def _work_area(self, point=None):
        if point is None:
            mon = _u.MonitorFromPoint(W.POINT(0, 0), MONITOR_DEFAULTTOPRIMARY)
        else:
            mon = _u.MonitorFromPoint(W.POINT(*point), MONITOR_DEFAULTTONEAREST)
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        _u.GetMonitorInfoW(mon, ctypes.byref(mi))
        return mi.rcWork

    def _layout(self):
        dc = _u.GetDC(self.hwnd)
        try:
            self.lay = layout(self.m, self.p.px(self.width), self.most, self.p, dc)
        finally:
            _u.ReleaseDC(self.hwnd, dc)
        return self.lay

    def place(self, force=False):
        """Where you put it, else the bottom right of the main screen, above
        the taskbar; it stays on its screen."""
        if self.held and self.held["moving"]:
            return
        old = self.lay["size"] if self.lay else None
        w, h = self._layout()["size"]
        if not force and old == (w, h):
            _u.InvalidateRect(self.hwnd, None, False)
            return
        if self.spot:
            wa = self._work_area(self.spot)
            x = min(max(self.spot[0], wa.left), wa.right - w)
            y = min(max(self.spot[1], wa.top), wa.bottom - h)
        else:
            wa = self._work_area()
            x, y = wa.right - w - self.p.px(10), wa.bottom - h - self.p.px(10)
        _u.SetWindowPos(self.hwnd, ctypes.c_void_p(HWND_TOPMOST), x, y, w, h, SWP_NOACTIVATE)
        _u.InvalidateRect(self.hwnd, None, False)
        self._tips()

    def _save_place(self):
        try:
            self.place_file.parent.mkdir(parents=True, exist_ok=True)
            self.place_file.write_text(json.dumps({
                "x": self.spot[0] if self.spot else None, "y": self.spot[1] if self.spot else None,
                "width": self.width, "rows": self.most}), encoding="utf-8")
        except OSError as e:
            aht.warn(f"CORNER where the list goes was not saved: {e}")

    def _edges(self, x, y) -> int:
        """What a press at (x, y) takes hold of: its sides change its width;
        the edge away from where it sits (its top in the corner, else its
        bottom) how many sessions it lists; anywhere else moves it."""
        if not self.lay:
            return 0
        w, h = self.lay["size"]
        e, edge = 0, self.p.px(EDGE)
        if x < edge:
            e |= LEFT
        elif x >= w - edge:
            e |= RIGHT
        if self.spot is None and y < edge:
            e |= TOP
        elif self.spot is not None and y >= h - edge:
            e |= BOTTOM
        return e

    def _tips(self):
        """A note over each session, the top line and the ×."""
        if not self.tip or not self.lay:
            return
        for i in range(len(self.tips)):
            ti = TOOLINFOW(ctypes.sizeof(TOOLINFOW), 0, self.hwnd, i + 1)
            _u.SendMessageW(self.tip, TTM_DELTOOLW, 0, ctypes.addressof(ti))
        corner = "its top" if self.spot is None else "its bottom"
        items = [(self.lay["close"], "Hide the list (the aht tray menu brings it back)"),
                 (self.lay["head"], "Drag the list anywhere, its sides to change its width, "
                                    f"or {corner} to list more or fewer sessions; double-click "
                                    "this line to put it back in the corner")]
        items += [(rect, tip_text(r)) for r, rect in self.lay["rows"]]
        self.tips = []
        for i, (rect, text) in enumerate(items):
            buf = ctypes.create_unicode_buffer(text)
            self.tips.append(buf)
            ti = TOOLINFOW(ctypes.sizeof(TOOLINFOW), TTF_SUBCLASS, self.hwnd, i + 1, W.RECT(*rect),
                           None, ctypes.cast(buf, ctypes.c_wchar_p), 0)
            _u.SendMessageW(self.tip, TTM_ADDTOOLW, 0, ctypes.addressof(ti))

    # -- what happens -------------------------------------------------------
    def tick(self):
        if self.m.poll():
            self.place()

    def _row_at(self, x, y):
        for r, (a, b, c, d) in (self.lay or {}).get("rows", []):
            if a <= x < c and b <= y < d:
                return r
        return None

    def _in(self, rect, x, y):
        return rect[0] <= x < rect[2] and rect[1] <= y < rect[3]

    def click(self, x, y):
        if not self.lay:
            return
        if self._in(self.lay["close"], x, y):
            self.hooks["switch_off"]()
            return
        r = self._row_at(x, y)
        if r:
            self.act(r, "open" if r.kind == "away" else "goto")

    def act(self, r: Row, what: str):
        """Do one thing to a session; what goes wrong shows under the top line."""
        if what == "hide":
            self.hooks["switch_off"]()
            return
        if what == "take-back":
            self.hooks["open_window"](r.project, "take-back")
            return
        self.m.seen(r.id)
        self.tick()
        try:
            _u.AllowSetForegroundWindow(0xFFFFFFFF)      # what aht starts may come forward
        except Exception:
            pass
        if what == "goto":
            self._aside(r, lambda: aht.goto_session(str(r.pid)))
        elif what == "open":
            self._aside(r, lambda: aht.open_away(r.project))
        elif what == "branch":
            dry = aht.branch_session(str(r.pid))
            if dry["blockers"]:
                self.say(f"{r.name}: {dry['blockers'][0]}")
                return
            name = ask_text(self.hwnd, f"Branch “{r.name}”",
                            "The branch opens in a new tab with the conversation so far; "
                            "this session goes on as it is. Name of the new branch:",
                            dry["name"], "Branch", self.p.s if self.p else 1)
            if name is None:
                return
            self._aside(r, lambda: aht.branch_session(str(r.pid), name, apply=True))
        elif what.startswith("send:"):
            self.send(r, what[5:])

    def send(self, r: Row, to: str):
        self.say(f"Checking {to} for “{r.name}”…", 300)
        self.place()

        def look():
            try:
                res = aht.send_session(str(r.pid), to)
            except Exception as e:
                self.hooks["note"]("the corner's Send to failed", e)
                res = {"blockers": [f"{type(e).__name__}: {e}"]}
            self.post(lambda: self._send_answer(r, to, res))
        threading.Thread(target=look, daemon=True).start()

    def _send_answer(self, r, to, res):
        self.m.note = None
        self.place()
        if res.get("blockers"):
            self.hooks["tell"](f"“{r.name}” cannot go to {to} now",
                               "\n\n".join(res["blockers"]))
            return
        if not self.hooks["ask"](f"Send to {to}", send_question(res)):
            return
        self._aside(r, lambda: aht.send_session(str(r.pid), to, apply=True))

    def _aside(self, r, fn):
        """`fn` on a thread of its own; its "why" or first blocker, if any,
        under the top line."""
        def go():
            try:
                res = fn() or {}
            except Exception as e:
                self.hooks["note"]("the session corner's action failed", e)
                res = {"why": f"{type(e).__name__}: {e}"}
            why = None
            if res.get("ok") is False:
                why = res.get("why") or "that did not work"
            elif res.get("blockers"):
                why = res["blockers"][0]
            if why:
                self.post(lambda: self.say(f"{r.name}: {why}"))
        threading.Thread(target=go, daemon=True).start()

    def say(self, text, secs=8):
        self.m.say(text, secs)
        self.place()

    def menu(self, r: Row):
        items = menu_items(r, self.m.machines)
        h = _u.CreatePopupMenu()
        acts, default = {}, None
        for i, it in enumerate(items, 1):
            if it == "-":
                _u.AppendMenuW(h, MF_SEPARATOR, 0, None)
                continue
            label, act, is_default = it
            _u.AppendMenuW(h, MF_STRING | (0 if act else MF_GRAYED), i, label)
            acts[i] = act
            if is_default and act:
                default = i
        if default:
            _u.SetMenuDefaultItem(h, default, 0)
        pt = W.POINT()
        _u.GetCursorPos(ctypes.byref(pt))
        _u.SetForegroundWindow(self.hwnd)
        cmd = _u.TrackPopupMenu(h, TPM_RETURNCMD | TPM_RIGHTBUTTON | TPM_NONOTIFY, pt.x, pt.y, 0,
                                self.hwnd, None)
        _u.PostMessageW(self.hwnd, 0, 0, 0)
        _u.DestroyMenu(h)
        if acts.get(cmd):
            self.act(r, acts[cmd])

    def _cursor_at(self, x, y):
        e = self._edges(x, y)
        cur = (IDC_SIZENWSE if e in (TOP | LEFT, BOTTOM | RIGHT) else
               IDC_SIZENESW if e in (TOP | RIGHT, BOTTOM | LEFT) else
               IDC_SIZEWE if e & (LEFT | RIGHT) else IDC_SIZENS if e else IDC_ARROW)
        _u.SetCursor(_u.LoadCursorW(None, ctypes.c_void_p(cur)))

    def _press(self, x, y):
        pt = W.POINT()
        _u.GetCursorPos(ctypes.byref(pt))
        r = W.RECT()
        _u.GetWindowRect(self.hwnd, ctypes.byref(r))
        self.held = {"mouse": (pt.x, pt.y), "rect": (r.left, r.top, r.right, r.bottom),
                     "edges": self._edges(x, y), "width": self.width, "most": self.most,
                     "shown": min(self.most, len(self.m.rows)), "moved": False,
                     "moving": False, "at": (x, y)}
        _u.SetCapture(self.hwnd)

    def _drag(self):
        h = self.held
        pt = W.POINT()
        _u.GetCursorPos(ctypes.byref(pt))
        dx, dy = pt.x - h["mouse"][0], pt.y - h["mouse"][1]
        if not h["edges"]:
            if not h["moved"] and abs(dx) < _u.GetSystemMetrics(SM_CXDRAG) \
                    and abs(dy) < _u.GetSystemMetrics(SM_CYDRAG):
                return
            h["moved"] = h["moving"] = True
            _u.SetWindowPos(self.hwnd, None, h["rect"][0] + dx, h["rect"][1] + dy, 0, 0,
                            0x1 | SWP_NOZORDER | SWP_NOACTIVATE)
            return
        h["moved"] = True
        e = h["edges"]
        if e & (LEFT | RIGHT):
            wa = self._work_area((pt.x, pt.y))
            room = (wa.right - wa.left) / self.p.s - 20
            want = h["width"] + (-dx if e & LEFT else dx) / self.p.s
            self.width = round(max(150, min(want, 720, room)))
            if e & RIGHT:                                   # the left side stays
                self.spot = (h["rect"][0], h["rect"][1])
            elif self.spot is not None:
                self.spot = (h["rect"][2] - self.p.px(self.width), h["rect"][1])
        if e & (TOP | BOTTOM):
            n = max(0, h["shown"] + round((-dy if e & TOP else dy) / self.p.px(ROW)))
            self.most = n if n < len(self.m.rows) else max(len(self.m.rows), h["most"])
        self.place(force=True)

    def _let_go(self, x, y):
        h, self.held = self.held, None
        _u.ReleaseCapture()
        if not h:
            return
        if not h["moved"]:
            self.click(x, y)
        elif not h["edges"]:
            r = W.RECT()
            _u.GetWindowRect(self.hwnd, ctypes.byref(r))
            self.spot = (r.left, r.top)
            self._save_place()
            self.place(force=True)
        else:
            self._save_place()

    def _hover(self, x, y):
        row = self._row_at(x, y)
        key = row.id if row else None
        on_x = bool(self.lay) and self._in(self.lay["close"], x, y)
        if key != self.hover or on_x != self.hover_close:
            self.hover, self.hover_close = key, on_x
            _u.InvalidateRect(self.hwnd, None, False)
        if not self.tracking:
            tme = TRACKMOUSEEVENT(ctypes.sizeof(TRACKMOUSEEVENT), TME_LEAVE, self.hwnd, 0)
            self.tracking = bool(_u.TrackMouseEvent(ctypes.byref(tme)))

    def _paint(self):
        ps = PAINTSTRUCT()
        dc = _u.BeginPaint(self.hwnd, ctypes.byref(ps))
        try:
            lay = self.lay or self._layout()
            w, h = lay["size"]
            mem = _g.CreateCompatibleDC(dc)
            bmp = _g.CreateCompatibleBitmap(dc, w, h)
            old = _g.SelectObject(mem, bmp)
            paint(mem, self.m, lay, self.p, self.hover, self.hover_close)
            _g.BitBlt(dc, 0, 0, w, h, mem, 0, 0, SRCCOPY)
            _g.SelectObject(mem, old)
            _g.DeleteObject(bmp)
            _g.DeleteDC(mem)
        finally:
            _u.EndPaint(self.hwnd, ctypes.byref(ps))

    def _wndproc(self, hwnd, msg, wp, lp):
        try:
            if msg == WM_MOUSEACTIVATE:
                return MA_NOACTIVATE
            if msg == WM_ERASEBKGND:
                return 1
            if msg == WM_PAINT:
                self._paint()
                return 0
            if msg == WM_SETCURSOR and (lp & 0xFFFF) == HTCLIENT and not self.held:
                pt = W.POINT()
                _u.GetCursorPos(ctypes.byref(pt))
                _u.ScreenToClient(hwnd, ctypes.byref(pt))
                self._cursor_at(pt.x, pt.y)
                return 1
            if msg == WM_LBUTTONDOWN:
                self._press(_lo(lp), _hi(lp))
                return 0
            if msg == WM_MOUSEMOVE:
                if self.held:
                    self._drag()
                else:
                    self._hover(_lo(lp), _hi(lp))
                return 0
            if msg == WM_LBUTTONUP:
                self._let_go(_lo(lp), _hi(lp))
                return 0
            if msg == WM_CAPTURECHANGED:
                if self.held and self.held["moved"]:
                    self._let_go(-1, -1)
                self.held = None
                return 0
            if msg == WM_LBUTTONDBLCLK:
                x, y = _lo(lp), _hi(lp)
                if self.lay and self._in(self.lay["head"], x, y) \
                        and not self._in(self.lay["close"], x, y):
                    self.spot = None                    # back to the corner
                    self._save_place()
                    self.place(force=True)
                return 0
            if msg == WM_RBUTTONUP:
                r = self._row_at(_lo(lp), _hi(lp))
                if r:
                    self.menu(r)
                return 0
            if msg == WM_MOUSELEAVE:
                self.tracking = False
                if self.hover or self.hover_close:
                    self.hover, self.hover_close = None, False
                    _u.InvalidateRect(hwnd, None, False)
                return 0
            if msg == WM_TIMER:
                self.tick()
                return 0
            if msg == WM_RUN:
                with self.lock:
                    todo, self.queue = self.queue, []
                for fn in todo:
                    fn()
                return 0
            if msg in (WM_DPICHANGED, WM_SETTINGCHANGE, WM_DISPLAYCHANGE):
                self._painter()
                self.place(force=True)
                return 0
            if msg == WM_CLOSE:
                self.hooks["switch_off"]()
                return 0
        except Exception as e:                  # the list stays; the log has it
            self.hooks["note"](f"the session corner (message {msg:#x})", e)
            return 0
        return _u.DefWindowProcW(hwnd, msg, wp, lp)


def ask_text(owner, title: str, prompt: str, value: str, ok: str, s: float = 1.0):
    """A small window that asks for one line of text: what was typed, or None
    for Cancel."""
    hinst = _k.GetModuleHandleW(None)
    got = {"text": None, "done": False}
    ctl = {}

    def proc(hwnd, msg, wp, lp):
        if msg == WM_COMMAND and (wp & 0xFFFF) in (IDOK, IDCANCEL):
            if (wp & 0xFFFF) == IDOK:
                n = _u.GetWindowTextLengthW(ctl["edit"])
                buf = ctypes.create_unicode_buffer(n + 1)
                _u.GetWindowTextW(ctl["edit"], buf, n + 1)
                got["text"] = buf.value.strip() or None
            got["done"] = True
            return 0
        if msg == WM_CLOSE:
            got["done"] = True
            return 0
        return _u.DefWindowProcW(hwnd, msg, wp, lp)

    wproc = WNDPROC(proc)
    wc = WNDCLASSW()
    wc.lpfnWndProc = wproc
    wc.hInstance = hinst
    wc.hCursor = _u.LoadCursorW(None, ctypes.c_void_p(IDC_ARROW))
    wc.hbrBackground = ctypes.c_void_p(16)          # COLOR_BTNFACE + 1
    wc.lpszClassName = "aht_corner_ask"
    _u.RegisterClassW(ctypes.byref(wc))
    px = lambda v: round(v * s)                     # noqa: E731
    w, h = px(420), px(170)
    wa = W.RECT()
    pt = W.POINT()
    _u.GetCursorPos(ctypes.byref(pt))
    mon = _u.MonitorFromPoint(pt, MONITOR_DEFAULTTONEAREST)
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    _u.GetMonitorInfoW(mon, ctypes.byref(mi))
    wa = mi.rcWork
    x, y = (wa.left + wa.right - w) // 2, (wa.top + wa.bottom - h) // 2
    dlg = _u.CreateWindowExW(WS_EX_DLGMODALFRAME | WS_EX_TOPMOST, "aht_corner_ask", title,
                             WS_POPUP | WS_CAPTION | WS_SYSMENU, x, y, w, h, None, None, hinst, None)
    font = _g.CreateFontW(-px(12), 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, "Segoe UI")
    m = px(14)
    cw = w - 2 * m - px(6)
    ctl["text"] = _u.CreateWindowExW(0, "STATIC", prompt, WS_CHILD | WS_VISIBLE, m, m, cw, px(44),
                                     dlg, None, hinst, None)
    ctl["edit"] = _u.CreateWindowExW(WS_EX_CLIENTEDGE, "EDIT", value,
                                     WS_CHILD | WS_VISIBLE | WS_TABSTOP | ES_AUTOHSCROLL,
                                     m, m + px(50), cw, px(24), dlg, None, hinst, None)
    bw, bh = px(88), px(26)
    by = m + px(86)
    ctl["ok"] = _u.CreateWindowExW(0, "BUTTON", ok, WS_CHILD | WS_VISIBLE | WS_TABSTOP |
                                   BS_DEFPUSHBUTTON, m + cw - 2 * bw - px(8), by, bw, bh, dlg,
                                   ctypes.c_void_p(IDOK), hinst, None)
    ctl["cancel"] = _u.CreateWindowExW(0, "BUTTON", "Cancel", WS_CHILD | WS_VISIBLE | WS_TABSTOP |
                                       BS_PUSHBUTTON, m + cw - bw, by, bw, bh, dlg,
                                       ctypes.c_void_p(IDCANCEL), hinst, None)
    for c in ctl.values():
        _u.SendMessageW(c, WM_SETFONT, font or 0, 1)
    _u.ShowWindow(dlg, 5)
    _u.SetForegroundWindow(dlg)
    _u.SetFocus(ctl["edit"])
    _u.SendMessageW(ctl["edit"], EM_SETSEL, 0, -1)
    msg = W.MSG()
    while not got["done"] and _u.IsWindow(dlg) and _u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        if not _u.IsDialogMessageW(dlg, ctypes.byref(msg)):
            _u.TranslateMessage(ctypes.byref(msg))
            _u.DispatchMessageW(ctypes.byref(msg))
    if _u.IsWindow(dlg):
        _u.DestroyWindow(dlg)
    if font:
        _g.DeleteObject(font)
    return got["text"]
