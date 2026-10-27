#!/usr/bin/env python3
"""
Folder badges for Windows — the counterpart of the macOS `badge_icon` binary
and the Linux GIO/KDE emblems.

Mechanism: Explorer shows a custom icon for a folder that carries a hidden
`desktop.ini` whose [.ShellClassInfo] IconResource points at an .ico file,
provided the folder has its read-only attribute set (Windows' standard
"this folder is customised" marker — it does not make the folder read-only
for actual file operations).  The .ico is written INSIDE the folder at
`.aht\\aht-badge-<8 hex>.ico` and referenced RELATIVELY, so the badge
travels with the folder on move/copy exactly like the macOS icon file does.
The name carries a checksum of the picture: Explorer keeps the picture of
an icon file it has drawn, so a changed badge gets a new name, which it
draws afresh, and the old file goes.  Older versions wrote the fixed name
`.aht\\aht-badge.ico`; such a desktop.ini line and file are still ours.
The line is written through the shell (SHGetSetFolderCustomSettings, as
the folder's Customize tab does), which also makes Explorer drop what it
has cached of desktop.ini: after a plain file write an open window keeps
the old line, and once the old file is gone shows a plain folder.

The icon itself is the real system folder icon (resolved via
SHGetStockIconInfo and extracted at several sizes with PrivateExtractIconsW)
composited with a coral agent sparkle (lower-right) and/or a dark git "+"
(centre).  If the system icon cannot be extracted (unusual setups, wine),
a drawn fallback folder is used so badging never hard-fails; such a badge
is never cached, so the next one made where the system icon can be read
gets the real folder, and the folder's copy is replaced on its next refresh.

Safety: a desktop.ini that already sets someone ELSE's icon (a user's custom
IconResource/IconFile, OneDrive's, …) is left completely alone, and removal
only ever deletes lines/files this module wrote.  Badges are cosmetic —
a failure here must never affect history tethering (callers wrap us).

Everything above module level is POSIX-import-safe (the build host generates
the app icon with the same rasterisers); the Win32 calls live inside
functions and only run on Windows.
"""
import hashlib
import os
import re
import struct
import sys
from pathlib import Path

CORAL = (217, 119, 87)          # the agent sparkle
INK = (28, 26, 25)              # the git "+"
SIZES = (16, 32, 48, 256)
# the badge file in a folder's .aht: aht-badge-<8 hex>.ico, or the fixed
# name older versions wrote
BADGE_FILE = re.compile(r"aht-badge(-[0-9a-f]{8})?\.ico", re.I)
CACHE_VERSION = 5                # 5: no cached badge has a drawn folder

FILE_ATTRIBUTE_READONLY = 0x01
FILE_ATTRIBUTE_HIDDEN = 0x02
FILE_ATTRIBUTE_SYSTEM = 0x04
FILE_ATTRIBUTE_NORMAL = 0x80
FCSM_ICONFILE = 0x10             # SHGetSetFolderCustomSettings: the icon
FCS_FORCEWRITE = 0x02


def _clamp01(v):
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)


# --------------------------------------------------------------------------- #
# Rasterisers (pure Python, straight-alpha BGRA, top-down)
# --------------------------------------------------------------------------- #

def sparkle_overlay(s, cx=0.72, cy=0.70, scale=0.46, rgb=CORAL):
    """Four-point sparkle in an s×s buffer, centred at (cx,cy)·s, spanning
    scale·s.  Same shape maths as the tray icon, expressed in that icon's
    32-px space so the anti-aliasing width stays ~2 real pixels at any size."""
    buf = bytearray(s * s * 4)
    k = 32.0 / (s * scale)              # real px  -> 32-space
    aa = (s * scale) / 32.0             # 32-space -> real px
    for y in range(s):
        dy = abs(y - cy * s) * k
        for x in range(s):
            dx = abs(x - cx * s) * k
            a = _clamp01(min((14.0 - (dx + dy)) / 2.0,
                             (6.5 - dx * dy) / 3.0) * aa)
            if a > 0.0:
                i = (y * s + x) * 4
                buf[i] = rgb[2]
                buf[i + 1] = rgb[1]
                buf[i + 2] = rgb[0]
                buf[i + 3] = int(a * 255)
    return buf


def rgba_to_bgra(buf):
    out = bytearray(buf)
    out[0::4], out[2::4] = buf[2::4], buf[0::4]
    return out


def infinity_overlay(s, rgb=CORAL, bg=None, **kw):
    """The aht mark (an infinity loop) as straight-alpha BGRA, rendered by
    the core's shared rasteriser so every platform draws the same shape."""
    import aht
    return rgba_to_bgra(aht.infinity_rgba(s, rgb, bg=bg, **kw))


def plus_overlay(s, cx=0.46, cy=0.60, scale=0.32, rgb=INK):
    """A bold "+" centred at (cx,cy)·s (the visual centre of the folder body)."""
    buf = bytearray(s * s * 4)
    half_len = s * scale / 2.0
    half_thick = half_len * 0.30
    for y in range(s):
        dy = abs(y - cy * s)
        for x in range(s):
            dx = abs(x - cx * s)
            a = max(_clamp01(min(half_thick - dy, half_len - dx) + 0.5),
                    _clamp01(min(half_thick - dx, half_len - dy) + 0.5))
            if a > 0.0:
                i = (y * s + x) * 4
                buf[i] = rgb[2]
                buf[i + 1] = rgb[1]
                buf[i + 2] = rgb[0]
                buf[i + 3] = int(a * 255)
    return buf


def folder_fallback(s):
    """A plain drawn folder (tab + body), used only when the real system
    folder icon cannot be extracted."""
    buf = bytearray(s * s * 4)

    def rect(x0, y0, x1, y1, rgb):
        for y in range(max(0, int(y0 * s)), min(s, int(y1 * s))):
            for x in range(max(0, int(x0 * s)), min(s, int(x1 * s))):
                i = (y * s + x) * 4
                buf[i] = rgb[2]
                buf[i + 1] = rgb[1]
                buf[i + 2] = rgb[0]
                buf[i + 3] = 255

    rect(0.06, 0.22, 0.46, 0.40, (230, 175, 80))     # tab
    rect(0.06, 0.32, 0.94, 0.88, (250, 205, 110))    # body
    return buf


def composite(base, overlay, s):
    """Straight-alpha OVER, in place on `base`."""
    for i in range(0, s * s * 4, 4):
        am = overlay[i + 3]
        if not am:
            continue
        ab = base[i + 3]
        am_f = am / 255.0
        ao = am_f + (ab / 255.0) * (1.0 - am_f)
        if ao <= 0.0:
            continue
        for c in range(3):
            base[i + c] = int((overlay[i + c] * am_f
                               + base[i + c] * (ab / 255.0) * (1.0 - am_f)) / ao)
        base[i + 3] = int(ao * 255)
    return base


# --------------------------------------------------------------------------- #
# ICO encoding
# --------------------------------------------------------------------------- #

def ico_bytes(images):
    """images: {size: straight-alpha BGRA top-down}  ->  .ico file bytes."""
    entries, body = [], b""
    offset = 6 + 16 * len(images)
    for s in sorted(images):
        px = bytes(images[s])
        rows = [px[y * s * 4:(y + 1) * s * 4] for y in range(s)]
        pix = b"".join(reversed(rows))                     # BMP is bottom-up
        mask = (b"\x00" * (((s + 31) // 32) * 4)) * s      # 1bpp AND mask
        header = struct.pack("<IiiHHIIiiII", 40, s, s * 2, 1, 32, 0,
                             len(pix) + len(mask), 0, 0, 0, 0)
        img = header + pix + mask
        entries.append(struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0,
                                   1, 32, len(img), offset))
        offset += len(img)
        body += img
    return struct.pack("<HHH", 0, 1, len(images)) + b"".join(entries) + body


# --------------------------------------------------------------------------- #
# The real system folder icon (Windows only; returns None on any failure)
# --------------------------------------------------------------------------- #

def system_folder_bgra(s):
    if os.name != "nt":
        return None
    try:
        import ctypes
        import ctypes.wintypes as wt
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

        class SHSTOCKICONINFO(ctypes.Structure):
            _fields_ = [("cbSize", wt.DWORD), ("hIcon", wt.HICON),
                        ("iSysImageIndex", ctypes.c_int), ("iIcon", ctypes.c_int),
                        ("szPath", wt.WCHAR * 260)]

        class ICONINFO(ctypes.Structure):
            _fields_ = [("fIcon", wt.BOOL), ("xHotspot", wt.DWORD),
                        ("yHotspot", wt.DWORD), ("hbmMask", wt.HBITMAP),
                        ("hbmColor", wt.HBITMAP)]

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wt.DWORD), ("biWidth", ctypes.c_long),
                        ("biHeight", ctypes.c_long), ("biPlanes", wt.WORD),
                        ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                        ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                        ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wt.DWORD),
                        ("biClrImportant", wt.DWORD)]

        # handles are 64-bit: undeclared, ctypes would pass and return them
        # as 32-bit ints (a cut-off HDC, and this whole function failing)
        shell32.SHGetStockIconInfo.argtypes = [ctypes.c_int, wt.UINT,
                                               ctypes.POINTER(SHSTOCKICONINFO)]
        shell32.SHGetStockIconInfo.restype = ctypes.c_long
        user32.GetIconInfo.argtypes = [wt.HICON, ctypes.POINTER(ICONINFO)]
        user32.GetIconInfo.restype = wt.BOOL
        user32.GetDC.argtypes = [wt.HWND]
        user32.GetDC.restype = wt.HDC
        user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
        user32.ReleaseDC.restype = ctypes.c_int
        user32.DestroyIcon.argtypes = [wt.HICON]
        user32.DestroyIcon.restype = wt.BOOL
        gdi32.GetDIBits.argtypes = [wt.HDC, wt.HBITMAP, wt.UINT, wt.UINT, ctypes.c_void_p,
                                    ctypes.c_void_p, wt.UINT]
        gdi32.GetDIBits.restype = ctypes.c_int
        gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
        gdi32.DeleteObject.restype = wt.BOOL

        info = SHSTOCKICONINFO()
        info.cbSize = ctypes.sizeof(info)
        SIID_FOLDER, SHGSI_ICONLOCATION = 3, 0
        if shell32.SHGetStockIconInfo(SIID_FOLDER, SHGSI_ICONLOCATION,
                                      ctypes.byref(info)) != 0:
            return None

        hicon = wt.HICON()
        iid = wt.UINT()
        user32.PrivateExtractIconsW.argtypes = [
            wt.LPCWSTR, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.POINTER(wt.HICON), ctypes.POINTER(wt.UINT),
            wt.UINT, wt.UINT]
        n = user32.PrivateExtractIconsW(info.szPath, info.iIcon, s, s,
                                        ctypes.byref(hicon),
                                        ctypes.byref(iid), 1, 0)
        if n < 1 or not hicon:
            return None
        try:
            ii = ICONINFO()
            if not user32.GetIconInfo(hicon, ctypes.byref(ii)):
                return None
            try:
                if not ii.hbmColor:
                    return None
                bmi = BITMAPINFOHEADER(40, s, -s, 1, 32, 0, 0, 0, 0, 0, 0)
                buf = ctypes.create_string_buffer(s * s * 4)
                hdc = user32.GetDC(None)
                try:
                    ok = gdi32.GetDIBits(hdc, ii.hbmColor, 0, s, buf,
                                         ctypes.byref(bmi), 0)
                finally:
                    user32.ReleaseDC(None, hdc)
                if not ok:
                    return None
                out = bytearray(buf.raw)
                if not any(out[3::4]):       # legacy mask-only icon: no alpha
                    return None
                return out
            finally:
                if ii.hbmColor:
                    gdi32.DeleteObject(ii.hbmColor)
                if ii.hbmMask:
                    gdi32.DeleteObject(ii.hbmMask)
        finally:
            user32.DestroyIcon(hicon)
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Badge icon assembly (memory + disk cached; identical for every folder)
# --------------------------------------------------------------------------- #

_MEM_CACHE = {}
_OLD_CACHE_GONE = False


def _cache_file(key):
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        return None
    return Path(base) / "aht" / "icons" / f"badge-{key}-v{CACHE_VERSION}.ico"


def _drop_old_cache(folder) -> None:
    """Badges an older aht cached (a lower CACHE_VERSION) are never read
    again: remove them, once per run.  Only files named as _cache_file names
    them; a newer aht's, and one still open elsewhere, stay."""
    global _OLD_CACHE_GONE
    if _OLD_CACHE_GONE:
        return
    _OLD_CACHE_GONE = True
    try:
        names = os.listdir(folder)
    except OSError:
        return
    for name in names:
        m = re.fullmatch(r"badge-.+-v(\d+)\.ico", name)
        if m and int(m.group(1)) < CACHE_VERSION:
            try:
                os.unlink(os.path.join(folder, name))
            except OSError:
                pass


def _blit_rgba(base, s, tile, d, cx, cy):
    """Straight-alpha OVER of a d×d RGBA tile centred at (cx,cy)·s onto the
    s×s BGRA base."""
    x0 = int(cx * s - d / 2)
    y0 = int(cy * s - d / 2)
    for ty in range(d):
        y = y0 + ty
        if not 0 <= y < s:
            continue
        for tx in range(d):
            x = x0 + tx
            if not 0 <= x < s:
                continue
            j = (ty * d + tx) * 4
            am = tile[j + 3]
            if not am:
                continue
            i = (y * s + x) * 4
            ab = base[i + 3]
            am_f = am / 255.0
            ao = am_f + (ab / 255.0) * (1.0 - am_f)
            if ao <= 0.0:
                continue
            # tile is RGBA, base is BGRA
            for bc, tc in ((0, 2), (1, 1), (2, 0)):
                base[i + bc] = int((tile[j + tc] * am_f
                                    + base[i + bc] * (ab / 255.0)
                                    * (1.0 - am_f)) / ao)
            base[i + 3] = int(ao * 255)


# layout of the agent discs in the lower-right band: (diameter, centres…)
_AGENT_LAYOUT = {
    1: (0.345, [(0.7775, 0.7775)]),
    2: (0.26,  [(0.55, 0.80), (0.83, 0.80)]),
    3: (0.205, [(0.4075, 0.815), (0.6325, 0.815), (0.8575, 0.815)]),
}


def _agent_names(marks):
    return [m.split(":", 1)[1] for m in marks if str(m).startswith("agent:")]


def badge_ico_bytes(marks):
    agents = _agent_names(marks)
    key = ("agents-" + "+".join(agents) if len(agents) <= 3
           else f"count{len(agents)}") + ("-git" if "git" in marks else "")
    if key in _MEM_CACHE:
        return _MEM_CACHE[key]
    cf = _cache_file(key)
    if cf is not None:
        _drop_old_cache(cf.parent)
        if cf.is_file():
            data = cf.read_bytes()
            _MEM_CACHE[key] = data
            return data
    import aht as _core
    images = {}
    drawn = False                   # a size has the drawn folder
    for s in SIZES:
        base = system_folder_bgra(s)
        if base is None:
            base = folder_fallback(s)
            drawn = True
        if "git" in marks:
            composite(base, plus_overlay(s), s)
        if agents:
            if len(agents) <= 3:
                scale, centres = _AGENT_LAYOUT[len(agents)]
                for name, (cx, cy) in zip(agents, centres):
                    d = max(4, int(s * scale))
                    _blit_rgba(base, s, _core.badge_disc_rgba(d, name),
                               d, cx, cy)
            else:
                d = max(4, int(s * 0.345))
                _blit_rgba(base, s, _core.badge_disc_rgba(d, len(agents)),
                           d, 0.7775, 0.7775)
        images[s] = base
    data = ico_bytes(images)
    if drawn:
        # kept nowhere: the next badge of this kind tries the real folder again
        return data
    _MEM_CACHE[key] = data
    if cf is not None:
        try:
            cf.parent.mkdir(parents=True, exist_ok=True)
            cf.write_bytes(data)
        except OSError:
            pass
    return data


# --------------------------------------------------------------------------- #
# desktop.ini editing (merge-only, never clobbers foreign customisation)
# --------------------------------------------------------------------------- #

def _read_ini(p: Path):
    """-> (text, codec).  Missing file reads as ('', 'utf-8')."""
    try:
        raw = p.read_bytes()
    except OSError:
        return "", "utf-8"
    for codec, bom in (("utf-16", b"\xff\xfe"), ("utf-16", b"\xfe\xff"),
                       ("utf-8-sig", b"\xef\xbb\xbf")):
        if raw.startswith(bom):
            return raw.decode(codec, "replace"), codec
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return raw.decode("cp1252", "replace"), "cp1252"


def badge_name(data: bytes) -> str:
    """The badge file's name: it changes whenever the picture does."""
    return f"aht-badge-{hashlib.sha256(data).hexdigest()[:8]}.ico"


def icon_line(name: str) -> str:
    return f"IconResource=.aht\\{name},0"


def _is_ours(line: str) -> bool:
    low = line.strip().lower()
    return low.startswith("iconresource=") and bool(BADGE_FILE.search(low))


def _foreign_icon(text: str) -> bool:
    """desktop.ini already sets someone else's icon."""
    in_sec = False
    for ln in text.splitlines():
        st = ln.strip()
        low = st.lower()
        if st.startswith("["):
            in_sec = (low == "[.shellclassinfo]")
            continue
        if in_sec and not _is_ours(ln) and \
                (low.startswith("iconresource=") or low.startswith("iconfile=")):
            return True
    return False


def _merge_icon(text: str, name: str):
    """Insert/replace our IconResource under [.ShellClassInfo], pointing at
    the badge file `name`.  Returns None when the folder already has
    someone else's icon."""
    if _foreign_icon(text):
        return None
    lines = [ln for ln in text.splitlines() if not _is_ours(ln)]
    idx = next((i for i, ln in enumerate(lines)
                if ln.strip().lower() == "[.shellclassinfo]"), None)
    if idx is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines += ["[.ShellClassInfo]", icon_line(name)]
    else:
        lines.insert(idx + 1, icon_line(name))
    return "\r\n".join(lines) + "\r\n"


def _sections(text: str):
    """desktop.ini as {section: its lines}, to compare two of them: the
    order of the lines in a section, case and blank lines aside."""
    out, sec = {}, ""
    for ln in text.splitlines():
        st = ln.strip().lower()
        if st.startswith("["):
            sec = st
            out.setdefault(sec, [])
        elif st:
            out.setdefault(sec, []).append(st)
    return {k: sorted(v) for k, v in out.items()}


def _remove_icon(text: str):
    """Drop our line (and a then-empty [.ShellClassInfo] header).
    None = nothing of ours found; '' = file is now empty, delete it."""
    lines = text.splitlines()
    kept = [ln for ln in lines if not _is_ours(ln)]
    if kept == lines:
        return None
    out, i = [], 0
    while i < len(kept):
        ln = kept[i]
        if ln.strip().lower() == "[.shellclassinfo]":
            j = i + 1
            while j < len(kept) and not kept[j].strip():
                j += 1
            if j >= len(kept) or kept[j].strip().startswith("["):
                i = j                      # header owns nothing any more
                continue
        out.append(ln)
        i += 1
    if not any(ln.strip() for ln in out):
        return ""
    return "\r\n".join(out).rstrip("\r\n") + "\r\n"


# --------------------------------------------------------------------------- #
# Attribute plumbing + the public entry point
# --------------------------------------------------------------------------- #

def _k32():
    import ctypes
    return ctypes.WinDLL("kernel32", use_last_error=True)


def _get_attrs(p) -> int:
    a = _k32().GetFileAttributesW(str(p))
    return 0 if a == 0xFFFFFFFF else a


def _set_attrs(p, attrs) -> None:
    _k32().SetFileAttributesW(str(p), attrs)


def _write_ini(p: Path, text: str, codec: str) -> None:
    """Hidden+system files refuse a plain overwrite, so drop the attributes,
    write, then mark hidden+system again (Explorer's own convention)."""
    if p.exists():
        _set_attrs(p, FILE_ATTRIBUTE_NORMAL)
    p.write_bytes(text.encode("utf-8" if codec == "cp1252" and
                              text.isascii() else codec))
    _set_attrs(p, FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM)


def _shell_refresh(path) -> None:
    try:
        import ctypes
        SHCNE_UPDATEITEM, SHCNF_PATHW = 0x2000, 0x0005
        ctypes.WinDLL("shell32").SHChangeNotify(
            SHCNE_UPDATEITEM, SHCNF_PATHW, ctypes.c_wchar_p(str(path)), None)
    except Exception:
        pass


def _shell_set_icon(path, icon: str) -> bool:
    """Point the folder's icon at `icon` (relative to the folder) through
    SHGetSetFolderCustomSettings, as the folder's Customize tab does: it
    writes the IconResource line, marks the folder customised and makes
    Explorer drop what it has cached of desktop.ini, which a plain write of
    the file does not.  False when that did not work (and off Windows)."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        import ctypes.wintypes as wt

        class SHFOLDERCUSTOMSETTINGS(ctypes.Structure):
            _fields_ = [("dwSize", wt.DWORD), ("dwMask", wt.DWORD),
                        ("pvid", ctypes.c_void_p),
                        ("pszWebViewTemplate", wt.LPWSTR),
                        ("cchWebViewTemplate", wt.DWORD),
                        ("pszWebViewTemplateVersion", wt.LPWSTR),
                        ("pszInfoTip", wt.LPWSTR), ("cchInfoTip", wt.DWORD),
                        ("pclsid", ctypes.c_void_p), ("dwFlags", wt.DWORD),
                        ("pszIconFile", wt.LPWSTR), ("cchIconFile", wt.DWORD),
                        ("iIconIndex", ctypes.c_int),
                        ("pszLogo", wt.LPWSTR), ("cchLogo", wt.DWORD)]

        fn = ctypes.WinDLL("shell32").SHGetSetFolderCustomSettings
        fn.argtypes = [ctypes.POINTER(SHFOLDERCUSTOMSETTINGS), wt.LPCWSTR,
                       wt.DWORD]
        fn.restype = ctypes.c_long
        fcs = SHFOLDERCUSTOMSETTINGS()
        fcs.dwSize = ctypes.sizeof(fcs)
        fcs.dwMask = FCSM_ICONFILE
        fcs.pszIconFile = icon
        fcs.cchIconFile = len(icon) + 1
        fcs.iIconIndex = 0
        return fn(ctypes.byref(fcs), str(path), FCS_FORCEWRITE) >= 0
    except Exception:
        return False


def _drop_badges(folder: Path, keep: str = None) -> None:
    """Remove the badge files in `folder` (.aht), all but `keep`: those of
    earlier pictures and the fixed name older versions wrote."""
    try:
        names = os.listdir(folder)
    except OSError:
        return
    for name in names:
        if name != keep and BADGE_FILE.fullmatch(name):
            try:
                os.unlink(folder / name)
            except OSError:
                pass


def apply(path, marks) -> str:
    """Set or clear the badge on one folder.  Returns a status string."""
    path = Path(path)
    if not path.is_dir():
        return "no-folder"
    ini = path / "desktop.ini"
    dot = path / ".aht"

    if not marks:
        text, codec = _read_ini(ini)
        res = _remove_icon(text) if text else None
        if res == "":
            _set_attrs(ini, FILE_ATTRIBUTE_NORMAL)
            try:
                ini.unlink()
            except OSError:
                pass
            # only un-mark the folder once no desktop.ini needs it any more
            a = _get_attrs(path)
            if a & FILE_ATTRIBUTE_READONLY:
                _set_attrs(path, a & ~FILE_ATTRIBUTE_READONLY)
        elif res is not None:
            _write_ini(ini, res, codec)
        _drop_badges(dot)
        try:
            dot.rmdir()                    # only succeeds if nothing else lives there
        except OSError:
            pass
        _shell_refresh(path)
        return "cleared"

    text, codec = _read_ini(ini)
    if _foreign_icon(text):
        return "foreign-icon-kept"         # never clobber a custom icon
    data = badge_ico_bytes(marks)
    name = badge_name(data)
    merged = _merge_icon(text, name)
    ico = dot / name
    dot.mkdir(parents=True, exist_ok=True)
    # a new picture gets a new name: Explorer draws a file it has not seen
    # afresh, where it would keep showing what it drew of the old one.  The
    # file first, then desktop.ini points at it, then the old one goes
    if not ico.is_file() or ico.read_bytes() != data:
        ico.write_bytes(data)
    if _sections(merged) != _sections(text):
        # through the shell, so an open window draws the new file at once.
        # Our own write when that fails or leaves anything but what we
        # meant (an IconFile= line would read as someone else's next time)
        if not (_shell_set_icon(path, f".aht\\{name}")
                and _sections(_read_ini(ini)[0]) == _sections(merged)):
            _write_ini(ini, merged, codec)
    _drop_badges(dot, keep=name)
    a = _get_attrs(path)
    if not a & FILE_ATTRIBUTE_READONLY:
        _set_attrs(path, a | FILE_ATTRIBUTE_READONLY)
    _shell_refresh(path)
    return "badged"
