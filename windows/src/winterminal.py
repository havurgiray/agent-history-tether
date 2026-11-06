"""Windows Terminal as aht's terminal.

Which process runs in which pane comes from the processes themselves: every
pane's programs carry the pane's id in WT_SESSION, and that id survives Windows
Terminal bringing a pane back.  Windows and tabs come from UI Automation.

Windows Terminal's own files are only ever read, for tab colours and profiles.
Editing a pane's command there would stay: Windows Terminal saves what a pane
was started with, so every later start would resume that session again, even
one the user has ended.  So a session is resumed by typing into the pane's
shell, as a person would, and the pane's command stays the shell.

The parts that decide (arrange, assign, resume_line, wt_command) are plain
functions, tested on any system: windows/tests/winterminal_test.py.
"""
from __future__ import annotations

import base64
import ctypes
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from ctypes import wintypes as W
from pathlib import Path
from types import SimpleNamespace

import aht

CREATE_NO_WINDOW = 0x08000000
FILETIME_1970 = 116444736000000000      # 1970 in Windows' 100 ns since 1601
CONSOLE_HOSTS = ("openconsole.exe", "conhost.exe")
WAIT_PANES = 25                 # seconds to wait for panes to come back or open
POWERSHELLS = ("powershell", "pwsh")

# ---- what Windows can tell about a process --------------------------------- #


class _Entry(ctypes.Structure):          # PROCESSENTRY32W
    _fields_ = [("size", W.DWORD), ("usage", W.DWORD), ("pid", W.DWORD),
                ("heap", ctypes.c_void_p), ("mod", W.DWORD), ("threads", W.DWORD),
                ("ppid", W.DWORD), ("pri", W.LONG), ("flags", W.DWORD),
                ("exe", W.WCHAR * 260)]


_KERNEL = None


def _kernel():
    global _KERNEL
    if _KERNEL is None:
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenProcess.restype = W.HANDLE
        k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
        k.CloseHandle.argtypes = [W.HANDLE]
        k.CreateToolhelp32Snapshot.restype = W.HANDLE
        k.ReadProcessMemory.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                        ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
        k.GetProcessTimes.argtypes = [W.HANDLE] + [ctypes.POINTER(W.FILETIME)] * 4
        k.Process32FirstW.argtypes = [W.HANDLE, ctypes.POINTER(_Entry)]
        k.Process32NextW.argtypes = [W.HANDLE, ctypes.POINTER(_Entry)]
        _KERNEL = k
    return _KERNEL


def process_table() -> list:
    """[(pid, parent pid, exe name)] for every process."""
    k = _kernel()
    snap = k.CreateToolhelp32Snapshot(2, 0)     # TH32CS_SNAPPROCESS
    e, out = _Entry(), []
    e.size = ctypes.sizeof(_Entry)
    ok = k.Process32FirstW(snap, ctypes.byref(e))
    while ok:
        out.append((e.pid, e.ppid, e.exe))
        ok = k.Process32NextW(snap, ctypes.byref(e))
    k.CloseHandle(snap)
    return out


class _Process:
    """An open process, for reading what it was started with.  A process of a
    higher rank (an administrator's, for a normal aht) is out of reach: every
    answer is then None."""
    QUERY, READ = 0x1000, 0x0410        # limited query; query + VM read

    def __init__(self, pid: int, access: int):
        self.k = _kernel()
        self.h = self.k.OpenProcess(access, False, pid)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        if self.h:
            self.k.CloseHandle(self.h)

    def _nt(self, what: int, buf, size: int) -> bool:
        n = W.ULONG(0)
        return ctypes.WinDLL("ntdll").NtQueryInformationProcess(
            W.HANDLE(self.h), what, buf, size, ctypes.byref(n)) == 0

    def _read(self, addr: int, size: int) -> bytes:
        out, got = ctypes.create_string_buffer(size), ctypes.c_size_t(0)
        if not self.k.ReadProcessMemory(self.h, ctypes.c_void_p(addr), out, size,
                                        ctypes.byref(got)):
            raise OSError(ctypes.get_last_error())
        return out.raw[:got.value]

    def _params(self) -> int:
        """Where the process keeps its start-up parameters (64-bit layout)."""
        info = (ctypes.c_void_p * 6)()              # PROCESS_BASIC_INFORMATION
        if not self._nt(0, info, ctypes.sizeof(info)):
            raise OSError("no process information")
        return int.from_bytes(self._read(info[1] + 0x20, 8), "little")

    def cmdline(self):
        if not self.h:
            return None

        class Text(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ushort), ("most", ctypes.c_ushort),
                        ("buffer", ctypes.c_void_p)]
        buf = ctypes.create_string_buffer(65536)
        if not self._nt(60, buf, 65536):            # ProcessCommandLineInformation
            return None
        t = Text.from_buffer(buf)
        return ctypes.wstring_at(t.buffer, t.length // 2) if t.buffer else ""

    def env(self):
        if not self.h:
            return None
        try:
            params = self._params()
            where = int.from_bytes(self._read(params + 0x80, 8), "little")
            size = int.from_bytes(self._read(params + 0x3F0, 8), "little")
            text = self._read(where, min(size or 32768, 1 << 20)).decode("utf-16-le", "ignore")
        except OSError:
            return None
        return dict(p.split("=", 1) for p in text.split("\0") if "=" in p[1:])

    def cwd(self):
        if not self.h:
            return None
        try:
            raw = self._read(self._params() + 0x38, 16)     # CurrentDirectory.DosPath
            size = int.from_bytes(raw[:2], "little")
            text = self._read(int.from_bytes(raw[8:], "little"), size).decode("utf-16-le")
        except OSError:
            return None
        return folder_name(text)

    def born(self):
        if not self.h:
            return None
        times = [W.FILETIME() for _ in range(4)]
        if not self.k.GetProcessTimes(self.h, *[ctypes.byref(t) for t in times]):
            return None
        ft = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        return (ft - FILETIME_1970) / 1e7


def process_cmdline(pid: int) -> str:
    with _Process(pid, _Process.QUERY) as p:
        return p.cmdline() or ""


def process_pane(pid: int) -> str:
    """The Windows Terminal pane a process runs in; "" for none, or when it is
    out of reach.  Only this one value is kept: an environment can hold keys."""
    with _Process(pid, _Process.READ) as p:
        return ((p.env() or {}).get("WT_SESSION") or "").strip("{}").lower()


def process_born(pid: int):
    with _Process(pid, _Process.QUERY) as p:
        return p.born()


def process_cwds(pids) -> dict:
    out = {}
    for pid in pids:
        with _Process(int(pid), _Process.READ) as p:
            cwd = p.cwd()
        if cwd:
            out[int(pid)] = cwd
    return out


def folder_name(path: str) -> str:
    """Without the trailing backslash a process keeps, except on a drive's
    root: `C:` alone means the folder last used on that drive."""
    path = path.rstrip("\\")
    return path + "\\" if re.fullmatch(r"[A-Za-z]:", path) else path


def bare_command(line: str) -> str:
    """A command line with its program as a bare name, as the core compares
    them: `"C:\\x\\claude.exe" --resume 1` -> `claude --resume 1`."""
    line = (line or "").strip()
    if line.startswith('"'):
        prog, _, rest = line[1:].partition('"')
    else:
        prog, _, rest = line.partition(" ")
    name = re.sub(r"\.(exe|cmd|bat|com)$", "", prog.replace("/", "\\").rsplit("\\", 1)[-1],
                  flags=re.I)
    return (name + " " + rest.strip()).strip()


def live_panes(table: list = None) -> dict:
    """{pane id: {"pid", "exe", "born", "busy"}}: the program each open pane
    started with.  A pane out of reach (an administrator's) is not there."""
    table = process_table() if table is None else table
    kids = {}
    for pid, ppid, exe in table:
        kids.setdefault(ppid, []).append((pid, exe))
    out = {}
    for pid, _ppid, exe in table:
        if exe.lower() != "windowsterminal.exe":
            continue
        for child, name in kids.get(pid, []):
            if name.lower() in CONSOLE_HOSTS:
                continue
            pane = process_pane(child)
            if pane:
                out[pane] = {"pid": child, "exe": name, "born": process_born(child) or 0,
                             "busy": [n for _p, n in kids.get(child, [])
                                      if n.lower() not in CONSOLE_HOSTS]}
    return out


def _descendants(pid: int, kids: dict) -> list:
    out, todo = [], [pid]
    while todo and len(out) < 64:
        p = todo.pop(0)
        out.append(p)
        todo += [c for c, _n in kids.get(p, [])]
    return out


# ---- consoles: a process cannot leave its own, so a small helper does this ---- #

class _Info(ctypes.Structure):           # CONSOLE_SCREEN_BUFFER_INFO
    _fields_ = [("size", W._COORD), ("cursor", W._COORD), ("attributes", W.WORD),
                ("window", W.SMALL_RECT), ("most", W._COORD)]


def _cursor_line(k) -> str:
    """The text left of the cursor in the attached console."""
    k.CreateFileW.restype = W.HANDLE
    k.CreateFileW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, W.LPVOID, W.DWORD, W.DWORD, W.HANDLE]
    k.GetConsoleScreenBufferInfo.argtypes = [W.HANDLE, ctypes.POINTER(_Info)]
    k.ReadConsoleOutputCharacterW.argtypes = [W.HANDLE, W.LPWSTR, W.DWORD, W._COORD,
                                              ctypes.POINTER(W.DWORD)]
    k.CloseHandle.argtypes = [W.HANDLE]
    h = k.CreateFileW("CONOUT$", 0xC0000000, 3, None, 3, 0, None)
    if h in (None, W.HANDLE(-1).value):
        return ""
    info, n = _Info(), W.DWORD(0)
    text = ""
    if k.GetConsoleScreenBufferInfo(h, ctypes.byref(info)) and info.cursor.X > 0:
        buf = ctypes.create_unicode_buffer(info.cursor.X + 1)
        if k.ReadConsoleOutputCharacterW(h, buf, info.cursor.X, W._COORD(0, info.cursor.Y),
                                         ctypes.byref(n)):
            text = buf.value[:n.value]
    k.CloseHandle(h)
    return text


def _console_info(pid: int) -> dict:
    k, u = ctypes.WinDLL("kernel32", use_last_error=True), ctypes.WinDLL("user32")
    k.GetConsoleWindow.restype = W.HWND
    u.GetWindow.restype = W.HWND
    u.GetWindow.argtypes = [W.HWND, ctypes.c_uint]
    k.FreeConsole()
    if not k.AttachConsole(pid):
        return {"pid": pid, "why": ctypes.get_last_error()}
    title = ctypes.create_unicode_buffer(1024)
    k.GetConsoleTitleW(title, 1024)
    hwnd = k.GetConsoleWindow()
    owner = int(u.GetWindow(hwnd, 4) or 0) if hwnd else 0   # GW_OWNER: its terminal window
    line = _cursor_line(k)
    k.FreeConsole()
    return {"pid": pid, "title": title.value, "owner": owner, "console": int(hwnd or 0),
            "line": line}


VK_PACKET = 0xE7                # a character on its own, without a key behind it


def key_plan(text: str, scan) -> list:
    """(virtual key, control state, UTF-16 unit) for each key of `text`.
    `scan` is VkKeyScanW.  A character above U+FFFF is two units.  One this
    keyboard layout has no key for, or that takes more than Shift (AltGr),
    goes as VK_PACKET: holding AltGr down in the record would read as Ctrl+Alt."""
    raw, out = text.encode("utf-16-le", "surrogatepass"), []
    for i in range(0, len(raw), 2):
        unit = int.from_bytes(raw[i:i + 2], "little")
        if unit == 13:
            out.append((0x0D, 0, unit))
            continue
        k = -1 if 0xD800 <= unit <= 0xDFFF else scan(chr(unit))
        if k == -1 or (k >> 8) & 0xFE:
            out.append((VK_PACKET, 0, unit))
        else:
            out.append((k & 0xFF, 0x10 if (k >> 8) & 1 else 0, unit))    # 0x10: SHIFT_PRESSED
    return out


def _console_type(pid: int, text: str, gap: float = 0.0) -> dict:
    """Put keys into the console of `pid`: only that pane gets them, in
    whichever tab or window it is, with or without the keyboard."""
    class Key(ctypes.Structure):
        _fields_ = [("down", W.BOOL), ("repeat", W.WORD), ("vk", W.WORD), ("scan", W.WORD),
                    ("char", W.WCHAR), ("state", W.DWORD)]

    class Event(ctypes.Union):
        _fields_ = [("key", Key), ("pad", ctypes.c_byte * 16)]

    class Record(ctypes.Structure):
        _fields_ = [("type", W.WORD), ("event", Event)]
    k, u = ctypes.WinDLL("kernel32", use_last_error=True), ctypes.WinDLL("user32")
    k.CreateFileW.restype = W.HANDLE
    k.CreateFileW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, W.LPVOID, W.DWORD, W.DWORD, W.HANDLE]
    k.WriteConsoleInputW.argtypes = [W.HANDLE, ctypes.POINTER(Record), W.DWORD,
                                     ctypes.POINTER(W.DWORD)]
    k.CloseHandle.argtypes = [W.HANDLE]
    u.VkKeyScanW.argtypes = [W.WCHAR]
    u.VkKeyScanW.restype = ctypes.c_short
    k.FreeConsole()
    if not k.AttachConsole(pid):
        code = ctypes.get_last_error()
        return {"ok": False, "why": "access denied" if code == 5 else f"error {code}"}
    h = k.CreateFileW("CONIN$", 0xC0000000, 3, None, 3, 0, None)
    if h in (None, W.HANDLE(-1).value):
        k.FreeConsole()
        return {"ok": False, "why": "no console input"}
    done, n, keys = 0, W.DWORD(0), key_plan(text, u.VkKeyScanW)
    for vk, state, unit in keys:
        pair = (Record * 2)()
        for i, down in enumerate((1, 0)):
            pair[i].type = 1                                # KEY_EVENT
            key = pair[i].event.key
            key.down, key.repeat, key.vk = down, 1, vk
            key.scan, key.char, key.state = u.MapVirtualKeyW(vk, 0), chr(unit), state
        if k.WriteConsoleInputW(h, pair, 2, ctypes.byref(n)):
            done += 1
        if gap:
            time.sleep(gap)
    k.CloseHandle(h)
    k.FreeConsole()
    return {"ok": done == len(keys), "why": "" if done == len(keys) else "not all was typed"}


def _safely(fn, *args) -> dict:
    """One pane's trouble stays that pane's."""
    try:
        return fn(*args)
    except Exception as e:
        return {"ok": False, "why": aht.redact(str(e))[:200]}


def cmd_pane(argv) -> int:
    """`aht _pane`, for aht itself: a JSON request on stdin."""
    req = json.load(sys.stdin)
    out = {"info": {str(p): _safely(_console_info, int(p)) for p in req.get("info", [])},
           "typed": {str(t["pid"]): _safely(_console_type, int(t["pid"]), t["text"], t.get("gap", 0))
                     for t in req.get("type", [])}}
    print(json.dumps(out))
    return 0


def _ask_helper(req: dict) -> dict:
    import winlayer
    try:
        r = subprocess.run(winlayer.self_cmd("_pane"), input=json.dumps(req), capture_output=True,
                           text=True, encoding="utf-8", timeout=60, creationflags=CREATE_NO_WINDOW)
        return json.loads(r.stdout)
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        aht.warn(f"WORKSPACE no answer about panes: {aht.redact(str(e))[-200:]}")
        return {"info": {}, "typed": {}}


# ---- Windows and tabs, from UI Automation ------------------------------------ #

UIA_SELECT = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$A = [System.Windows.Automation.AutomationElement]
$tab = New-Object System.Windows.Automation.PropertyCondition($A::ControlTypeProperty, [System.Windows.Automation.ControlType]::TabItem)
$w = $A::FromHandle([IntPtr]%d)
$w.FindAll('Descendants', $tab).Item(%d).GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Select()
$p = $w.GetCurrentPattern([System.Windows.Automation.WindowPattern]::Pattern)
if ($p.Current.WindowVisualState -eq 'Minimized') { $p.SetWindowVisualState('Normal') }
try { $w.SetFocus() } catch { }
'ok'
"""

UIA_SCRIPT = r"""
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$A = [System.Windows.Automation.AutomationElement]
$win = New-Object System.Windows.Automation.PropertyCondition($A::ClassNameProperty, 'CASCADIA_HOSTING_WINDOW_CLASS')
$tab = New-Object System.Windows.Automation.PropertyCondition($A::ControlTypeProperty, [System.Windows.Automation.ControlType]::TabItem)
$out = @()
foreach ($w in $A::RootElement.FindAll('Children', $win)) {
  $tabs = @()
  foreach ($i in $w.FindAll('Descendants', $tab)) { $tabs += $i.Current.Name }
  $out += @{ hwnd = $w.Current.NativeWindowHandle; tabs = @($tabs) }
}
ConvertTo-Json -Depth 4 -Compress -InputObject @($out)
"""


def _powershell(script: str):
    # as one encoded argument: read from stdin, PowerShell takes line by line
    # and a block over several lines never runs
    code = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand",
                               code], capture_output=True, text=True, encoding="utf-8", timeout=30,
                              stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as e:
        return SimpleNamespace(returncode=1, stdout="", stderr=str(e))


def uia_windows() -> list:
    """[{"hwnd", "tabs": [name, ...]}] for the windows this user can see."""
    r = _powershell(UIA_SCRIPT)
    try:
        return json.loads(r.stdout)
    except ValueError:
        aht.warn(f"WORKSPACE no answer about windows: {(r.stderr or '').strip()[-200:]}")
        return []


# ---- Windows Terminal's own files: read only ---------------------------------- #

def state_folders(env=None) -> list:
    env = os.environ if env is None else env
    base = Path(env.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    pkg = base / "Packages"
    return [pkg / "Microsoft.WindowsTerminal_8wekyb3d8bbwe" / "LocalState",
            pkg / "Microsoft.WindowsTerminalPreview_8wekyb3d8bbwe" / "LocalState",
            base / "Microsoft" / "Windows Terminal"]


def saved_layouts(folders: list = None) -> list:
    """The windows Windows Terminal saved, from its newest state file.  Any
    surprise in there means none: they only add colours and profiles."""
    found = []
    for d in (state_folders() if folders is None else folders):
        for name in ("state.json", "elevated-state.json"):
            try:
                f = Path(d) / name
                data = json.loads(f.read_text(encoding="utf-8-sig"))
                if data.get("persistedWindowLayouts"):
                    found.append((f.stat().st_mtime, data["persistedWindowLayouts"]))
            except (OSError, ValueError, AttributeError):
                continue
    return max(found, key=lambda x: x[0])[1] if found else []


def saved_pane_ids(layouts: list) -> set:
    return {str(a.get("sessionId")).strip("{}").lower()
            for w in layouts if isinstance(w, dict) for a in w.get("tabLayout") or []
            if isinstance(a, dict) and a.get("sessionId")}


def profile_names(folders: list = None) -> set:
    """The names of the user's profiles: a tab showing one has no title of
    its own.  settings.json may hold comments, so this is not read as JSON."""
    out = set()
    for d in (state_folders() if folders is None else folders):
        try:
            text = (Path(d) / "settings.json").read_text(encoding="utf-8-sig")
        except OSError:
            continue
        out |= {m.lower() for m in re.findall(r'"name"\s*:\s*"([^"]+)"', text)}
    return out


def saves_windows(folders: list = None) -> bool:
    """Windows Terminal is set to bring its windows back when it starts."""
    for d in (state_folders() if folders is None else folders):
        try:
            text = (Path(d) / "settings.json").read_text(encoding="utf-8-sig")
        except OSError:
            continue
        if re.search(r'"firstWindowPreference"\s*:\s*"persistedWindowLayout"', text):
            return True
    return False


# ---- deciding: what is where, what goes where (no system calls) ---------------- #

# what programs put on a tab: a program, a folder, user@host, a command running
APP_TITLE = re.compile(r"^(windows powershell|powershell|command prompt|cmd|git bash|claude code"
                       r"|.*\.(exe|cmd)|.*[\\/].*|~.*|[\w.-]+@[\w.-]+.*|(mingw|msys|ucrt|clang)\d*:.*)$",
                       re.I)
# in lower case, as they are typed: "Go to market" is a name
APP_COMMAND = re.compile(r"^(npm|npx|yarn|pnpm|node|python\d?|py|pip|git|ssh|sudo|vim?|nvim|nano"
                         r"|emacs|htop|top|less|man|tail|watch|docker|kubectl|make|cargo|go)(\s.*)?$")


def clean_title(name: str) -> str:
    return re.sub(r"^administrator:\s*", "", (name or "").strip(), flags=re.I)


def shell_of(pane: dict) -> str:
    return re.sub(r"\.exe$", "", pane["exe"], flags=re.I).lower()


def own_title(name: str, profiles: set = frozenset()) -> str:
    """A tab's name when someone gave it one; "" when it is what a program or
    the profile put there (Claude's starts with its spinner or ✳)."""
    t = clean_title(name)
    if not t or APP_TITLE.match(t) or APP_COMMAND.match(t) or t.lower() in profiles \
            or not (t[0].isalnum() or t[0] in "_-("):
        return ""
    return t


def place(keys: list, titles: dict, names: list) -> dict:
    """{pane: tab index} for one window's panes, oldest first.  UI Automation
    tells a tab's name, not its panes, and a tab shows its active pane's
    title, which several tabs may share ("✳ Claude Code").  Panes open in tab
    order, so they are cut into runs, one run for each tab, so that as many
    tabs as can hold their name's pane.  A tab may have no pane (Settings); a
    run of several is a split, and a split takes the keyboard, so a tab
    mostly shows its newest pane.  A tab dragged elsewhere, or a split beside
    a renamed tab, can land a pane one tab off: nothing tells them apart.
    This says where to reopen a pane and which tab to show, never where to
    type: that goes by the pane's id."""
    if not names:
        return {k: 0 for k in keys}
    want = [clean_title(n) for n in names]
    have = [clean_title(titles.get(k)) for k in keys]
    n, m, best = len(keys), len(names), {}

    def plan(i: int, t: int):
        """(worth, end of tab t's run, ...) for panes from i on, tabs from t on."""
        if t == m - 1:
            return (_run_worth(have[i:], want[t]), n)
        if (i, t) not in best:
            options = ((_run_worth(have[i:j], want[t]) + plan(j, t + 1)[0], j)
                       for j in range(n, i - 1, -1))        # ties: the longer run first
            best[i, t] = max(options, key=lambda o: o[0])
        return best[i, t]
    where, i = {}, 0
    for t in range(m):
        j = plan(i, t)[1]
        where.update({k: t for k in keys[i:j]})
        i = j
    return where


def _run_worth(titles: list, name: str) -> float:
    if not titles:
        return 0.0
    newest = 0.05 if titles[-1] == name else 0.0
    return 1.0 + (2.0 if name in titles else 0.0) + newest - 0.01 * (len(titles) - 1)


def arrange(panes: dict, info: dict, wins: list, layouts: list, profiles: set = frozenset()) -> dict:
    """The core's view of the tabs: {pane id: {"title", "window", "tab", "pane",
    "profile", "color", "pane_id"}}.  Windows are numbered by their oldest
    pane, so the numbers stay as a window's z-order changes."""
    styles = {}
    for w in layouts:
        for a in (w.get("tabLayout") or []) if isinstance(w, dict) else []:
            if isinstance(a, dict) and a.get("tabTitle"):
                styles.setdefault(a["tabTitle"], a)
    groups = {}
    for k, p in panes.items():
        groups.setdefault((info.get(str(p["pid"])) or {}).get("owner") or 0, []).append(k)
    tabs = {int(w.get("hwnd") or 0): w.get("tabs") or [] for w in wins}
    rows = {}
    oldest = lambda g: min(panes[k]["born"] for k in g[1])       # noqa: E731
    for wi, (owner, keys) in enumerate(sorted(groups.items(), key=oldest), 1):
        keys.sort(key=lambda k: panes[k]["born"])
        names = tabs.get(owner) or []
        titles = {k: (info.get(str(panes[k]["pid"])) or {}).get("title") or "" for k in keys}
        where = place(keys, titles, names)
        count = {}
        for k in keys:
            t = where[k]
            count[t] = count.get(t, 0) + 1
            title = own_title(names[t], profiles) if t < len(names) else ""
            style = styles.get(title) or {}
            rows[k] = {"title": title, "window": wi, "tab": t + 1, "pane": count[t],
                       "profile": style.get("profile") or None,
                       "color": style.get("tabColor") or None, "pane_id": k}
    return rows


def _quote_powershell(a: str) -> str:
    # PowerShell also ends a quoted string at a curly quote, and reads a comma
    # as a list and @ as splatting
    if re.fullmatch(r"[\w+=:./\\-]+", a):
        return a
    return "'" + re.sub("(['\u2018\u2019\u201a\u201b])", r"\1\1", a) + "'"


def _quote_cmd(a: str) -> str:
    return a if re.fullmatch(r"[\w@+=:,./\\-]+", a) else '"' + a.replace('"', '""') + '"'


def resume_line(e: dict, shell: str):
    """What to type into a shell to get `e`'s session back: "" when it had
    none, None when aht does not know how to talk to that shell."""
    if e.get("agent") == "claude" and e.get("session"):
        cmd = ["claude"] + list(e.get("args") or []) + ["--resume", e["session"]]
    elif e.get("agent") == "kimi":
        cmd = ["kimi", "-c"]
    else:
        return ""
    cwd = e.get("cwd")
    if shell in POWERSHELLS:
        line = " ".join(_quote_powershell(a) for a in cmd)
        # a folder that cannot be entered stops it, as && does in the others
        return (f"Set-Location -LiteralPath {_quote_powershell(cwd)}; if ($?) {{ {line} }}"
                if cwd else line)
    if shell == "cmd":
        go = f"cd /d {_quote_cmd(cwd)} && " if cwd else ""
        return go + " ".join(_quote_cmd(a) for a in cmd)
    if shell in ("bash", "sh", "zsh"):
        go = f"cd {shlex.quote(cwd)} && " if cwd else ""
        return go + " ".join(shlex.quote(a) for a in cmd)
    return None


def at_prompt(line: str, shell: str) -> bool:
    """The text left of the cursor ends in a prompt, so nothing typed waits
    there and no program asks for input.  What aht types would else join a
    half-typed command, or answer a script.  A prompt it does not know means
    no: the session then opens in a new tab."""
    t = (line or "").rstrip()
    if t.endswith(">>"):                        # a continuation line
        return False
    return bool(t) and t[-1] in (">$#%❯➜λ»" if shell != "cmd" else ">")


def can_take(pane: dict, e: dict) -> bool:
    """A pane that came back and sits idle in a shell aht can type into."""
    return not pane["busy"] and resume_line(e, shell_of(pane)) is not None


def assign(plan: dict, live: dict, ready=lambda pane: True) -> tuple:
    """([(pane id, entry)], windows to open): an entry whose pane came back and
    can take it stays there; the rest open as new tabs, each saved window in
    a window of its own.  `ready`: this pane may be typed into now."""
    into, windows = [], []
    for win in plan.get("windows") or []:
        fresh = []
        for panes in win:
            rest = []
            for e in panes:
                p = live.get(str(e.get("pane_id") or "").lower())
                if p and can_take(p, e) and ready(p):
                    into.append((e["pane_id"].lower(), e))
                else:
                    rest.append(e)
            if rest:
                fresh.append(rest)
        if fresh:
            windows.append(fresh)
    return into, windows


def in_its_pane(pid: int, pane: dict, table: list, info: dict) -> bool:
    """The process really runs in that pane's shell.  WT_SESSION is inherited:
    a program started with Start-Process has it too, in a console of its own."""
    parent = next((q for p, q, _e in table if p == pid), None)
    consoles = [(info.get(str(p)) or {}).get("console") for p in (pid, pane["pid"])]
    return parent == pane["pid"] and bool(consoles[0]) and consoles[0] == consoles[1]


def _wt_text(s: str) -> str:
    return str(s).replace(";", "\\;")           # wt splits its arguments on ;


def wt_command(window: list, name: str) -> list:
    """The one `wt` command that opens a saved window's tabs: plain shells, so
    what a pane was started with never holds a session."""
    cmd = ["wt.exe", "-w", name]
    for ti, panes in enumerate(window):
        for pi, e in enumerate(panes):
            if ti or pi:
                cmd.append(";")
            cmd.append("split-pane" if pi else "new-tab")
            if pi:
                cmd.append("-V")
            if e.get("profile"):
                cmd += ["-p", _wt_text(e["profile"])]
            if e.get("title"):
                cmd += ["--title", _wt_text(e["title"]), "--suppressApplicationTitle"]
            if e.get("color"):
                cmd += ["--tabColor", e["color"]]
            if e.get("cwd"):
                cmd += ["-d", _wt_text(e["cwd"])]
    return cmd


def wait_for(look, enough=None, limit: float = WAIT_PANES, pause: float = 0.5,
             sleep=time.sleep, clock=time.monotonic) -> set:
    """Look at the panes until `enough(panes)` says so; without it, until they
    stop changing.  Right after a boot they take seconds to come, one by one,
    so "no change for a moment" is not enough when aht knows what to expect."""
    end, last, same = clock() + limit, None, 0
    while True:
        now = set(look())
        same = same + 1 if now and now == last else 0
        last = now
        if (enough(now) if enough else same >= 3) or clock() >= end:
            return now
        sleep(pause)


# ---- Windows Terminal as aht's terminal ---------------------------------------- #

class WindowsTerminal(aht.Terminal):
    """A pane's key is its id, WT_SESSION."""
    name = "Windows Terminal"

    def running(self) -> bool:
        return any(e.lower() == "windowsterminal.exe" for _p, _q, e in process_table())

    def started(self):
        born = [process_born(p) for p, _q, e in process_table()
                if e.lower() == "windowsterminal.exe"]
        born = [b for b in born if b]
        return min(born) if born else None

    def tabs(self, max_age: float = None) -> dict:
        panes = live_panes()
        if not panes:
            return {}
        info = _ask_helper({"info": [p["pid"] for p in panes.values()]})["info"]
        wins = uia_windows()
        if not info or not wins:        # a look that failed is not a layout
            return {}
        return arrange(panes, info, wins, saved_layouts(), profile_names())

    def pane_processes(self) -> dict:
        table = process_table()
        kids = {}
        for pid, ppid, exe in table:
            kids.setdefault(ppid, []).append((pid, exe))
        return {k: [(pid, bare_command(process_cmdline(pid)))
                    for pid in _descendants(p["pid"], kids)]
                for k, p in live_panes(table).items()}

    def steps(self, step) -> list:
        if not shutil.which("wt") and not shutil.which("wt.exe"):
            return []
        on = saves_windows()
        return [step("terminal_windows", on, "Windows Terminal brings its windows back",
                     "On: after a restart it opens your windows, splits, tab colours and old "
                     "screen text, and aht resumes each session in its own pane." if on else
                     "Off: Restore Workspace brings your sessions and titled tabs back in new "
                     "windows, without splits' sizes, tab colours or old screen text.",
                     "Windows Terminal → Settings → Startup → When Terminal starts → Open "
                     "windows from a previous session.", optional=True)]

    def pane_of_pids(self, pids) -> dict:
        return {p: k for p, k in ((p, process_pane(p)) for p in pids) if k}

    def last_tabs(self) -> dict:
        return live_panes()

    def go_to(self, key) -> str:
        panes = live_panes()
        if key not in panes:
            return "none"
        info = _ask_helper({"info": [p["pid"] for p in panes.values()]})["info"]
        rows = arrange(panes, info, uia_windows(), [])
        hwnd = (info.get(str(panes[key]["pid"])) or {}).get("owner")
        if not hwnd:
            return "none"
        r = _powershell(UIA_SELECT % (int(hwnd), rows[key]["tab"] - 1))
        # by what it printed: PowerShell writes its progress to stderr
        if r.stdout.strip() == "ok":
            return "ok"
        aht.warn(f"TABS could not go to a tab: {(r.stderr or '').strip()[-200:]}")
        return "none"

    def restart_line(self, row: dict, flags: list):
        table = process_table()
        pane = live_panes(table).get(row["tty"])
        if not pane:
            return None
        info = _ask_helper({"info": [row["pid"], pane["pid"]]})["info"]
        if not in_its_pane(row["pid"], pane, table, info):
            return None
        return resume_line({"agent": "claude", "session": row["session"], "cwd": row["project"],
                            "args": flags}, shell_of(pane)) or None

    def type_line(self, key, line: str) -> bool:
        pane = live_panes().get(key)
        if not pane or pane["busy"]:
            return False
        got = _ask_helper({"type": [{"pid": pane["pid"], "text": line + "\r"}]})["typed"]
        return bool((got.get(str(pane["pid"])) or {}).get("ok"))

    def start(self, saved: dict = None) -> tuple:
        if self.running():
            return False, ""
        if not shutil.which("wt.exe") and not shutil.which("wt"):
            return False, "Windows Terminal is not installed"
        layouts = saved_layouts() if saves_windows() else []
        if not layouts:
            return False, ""    # nothing to bring back: `wt` opens just what is asked
        # with a saved layout any `wt` command opens those windows too, so
        # they come first, and what is in them is not opened a second time
        subprocess.Popen(["wt.exe"], creationflags=CREATE_NO_WINDOW)
        ids = saved_pane_ids(layouts)
        wait_for(lambda: live_panes().keys(), (lambda now: ids <= now) if ids else None)
        return True, ""

    def open_plan(self, plan: dict, tabs: dict, started: bool, saved: dict = None) -> dict:
        live = live_panes()
        info = _ask_helper({"info": [p["pid"] for p in live.values()]})["info"]
        for p in live.values():
            p["line"] = (info.get(str(p["pid"])) or {}).get("line")
        # panes aht just brought back hold nothing yet; a pane open before
        # this may hold a half-typed line or a script's question
        ready = (lambda p: True) if started else (lambda p: at_prompt(p["line"], shell_of(p)))
        into, windows = assign(plan, live, ready)
        owners = {(i or {}).get("owner") for i in info.values()}
        jobs, why, opened = list(into), [], 0
        for i, window in enumerate(windows):
            before = set(live_panes())
            entries = [e for panes in window for e in panes]
            subprocess.Popen(wt_command(window, f"aht-{int(time.time())}-{i}"),
                             creationflags=CREATE_NO_WINDOW)
            wait_for(lambda: live_panes().keys(), lambda now: len(now - before) >= len(entries))
            now = live_panes()
            new = sorted((k for k in now if k not in before), key=lambda k: now[k]["born"])
            seen = _ask_helper({"info": [now[k]["pid"] for k in new]})["info"]
            # a tab someone opened meanwhile sits in a window that was there
            new = [k for k in new
                   if (seen.get(str(now[k]["pid"])) or {}).get("owner") not in owners]
            owners |= {(x or {}).get("owner") for x in seen.values()}
            if len(new) < len(entries):
                why.append(f"{len(entries) - len(new)} of the new tabs did not open")
            jobs += list(zip(new, entries))
        now, typing = live_panes(), []
        for k, e in jobs:                       # as it is now, not as it was
            pane = now.get(k)
            line = resume_line(e, shell_of(pane)) if pane else None
            if not pane or pane["busy"] or line is None:
                why.append(f"{e.get('name') or e.get('title') or e.get('session')}: "
                           "its tab was in use; open it again")
            elif line:
                typing.append({"pid": pane["pid"], "text": line + "\r"})
            else:
                opened += 1                     # a plain tab: there it is
        if typing:
            done = _ask_helper({"type": typing})["typed"]
            for t in typing:
                got = done.get(str(t["pid"])) or {}
                if got.get("ok"):
                    opened += 1
                else:
                    why.append(got.get("why") or "no answer from a tab")
        return {"opened": opened, "why": "; ".join(why)}


def activate() -> None:
    """Called once on Windows: aht's terminal, and the process questions the
    core asks with ps and lsof elsewhere."""
    import winlayer
    winlayer.COMMANDS["_pane"] = cmd_pane
    aht.TERMINAL = WindowsTerminal()
    aht._cmdline = process_cmdline
    aht._proc_started = process_born
    aht._cwds = process_cwds
    aht._SHELLS |= {"powershell", "pwsh", "cmd"}
