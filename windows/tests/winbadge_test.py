#!/usr/bin/env python3
"""The Windows folder badge's icon cache, on any OS (winbadge.py imports
anywhere; only its Win32 calls need Windows): a badge that had to use the
drawn stand-in folder for any size is kept neither on disk nor in memory,
one made with the real folder is, and the cache files of an older version
are not read and are removed (a newer version's and other files stay).
The badge file in a folder is named after its picture: a new picture gets
a new name, desktop.ini points at it and the old file goes, also the fixed
name older versions wrote; someone else's icon is left alone (off Windows
with stand-ins for the file attributes).  The line goes in through the
shell (with stand-ins for it here): when the shell fails or writes more
than that line, aht writes desktop.ini itself.  On Windows also: a folder
whose badge was drawn with the stand-in gets the real one on its next
refresh, through the real shell call.
Everything goes to a throwaway folder (LOCALAPPDATA and AHT_HOME point
into it).

    python windows/tests/winbadge_test.py
"""
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "windows" / "src"))
sys.path.insert(0, str(ROOT))
if os.name == "nt":
    import win_fcntl
    sys.modules.setdefault("fcntl", win_fcntl)

T = Path(tempfile.mkdtemp(prefix="aht-winbadge-test-"))
os.environ["LOCALAPPDATA"] = str(T / "localappdata")
os.environ["AHT_HOME"] = str(T / "home" / ".aht")
import winbadge  # noqa: E402

FAILS = []
def ck(c, m):
    print(("  PASS " if c else "  FAIL ") + m)
    if not c:
        FAILS.append(m)

ICONS = T / "localappdata" / "aht" / "icons"
V = winbadge.CACHE_VERSION
real = winbadge.system_folder_bgra

def stand_in(s):                    # a "system" folder unlike the drawn one
    return bytearray(bytes((40, 90, 160, 255)) * (s * s))

def fresh():
    winbadge._MEM_CACHE.clear()
    winbadge._OLD_CACHE_GONE = False
    shutil.rmtree(ICONS, ignore_errors=True)

try:
    # the cache of the version before, as an aht that cached a drawn folder left it
    ICONS.mkdir(parents=True)
    (ICONS / f"badge-agents-claude-v{V - 1}.ico").write_bytes(b"stale")
    (ICONS / "badge-count4-v1.ico").write_bytes(b"older")
    (ICONS / f"badge-agents-aht-v{V + 1}.ico").write_bytes(b"newer")
    (ICONS / "notes.txt").write_text("not ours")

    # one size the system icon could not give (the VM's cache had that mix)
    winbadge.system_folder_bgra = lambda s: None if s == 48 else stand_in(s)
    drawn = winbadge.badge_ico_bytes(["agent:claude"])
    ck(drawn != b"stale", "a cache file of an older version is not read")
    ck(not (ICONS / f"badge-agents-claude-v{V}.ico").exists(),
       "a badge with the drawn folder in one size is not cached on disk")
    ck(not winbadge._MEM_CACHE, "nor in memory")
    left = sorted(p.name for p in ICONS.iterdir())
    ck(left == sorted([f"badge-agents-aht-v{V + 1}.ico", "notes.txt"]),
       f"older versions' files go, a newer one's and other files stay ({left})")

    winbadge.system_folder_bgra = stand_in
    good = winbadge.badge_ico_bytes(["agent:claude"])
    ck(good != drawn, "the next badge of that kind tries the real folder again")
    cf = ICONS / f"badge-agents-claude-v{V}.ico"
    ck(cf.is_file() and cf.read_bytes() == good, "one made with the real folder is cached on disk")
    ck(winbadge._MEM_CACHE.get("agents-claude") == good, "and in memory")

    winbadge.system_folder_bgra = lambda s: None
    ck(winbadge.badge_ico_bytes(["agent:claude"]) == good, "a cached real badge is used")
    winbadge._MEM_CACHE.clear()
    ck(winbadge.badge_ico_bytes(["agent:claude"]) == good, "also from disk")

    # ---- the badge file's name follows its picture ----
    fresh()
    winbadge.system_folder_bgra = stand_in
    refreshed = []
    if os.name != "nt":                 # no file attributes, no Explorer here
        attrs = {}
        winbadge._get_attrs = lambda p: attrs.get(str(p), 0)
        winbadge._set_attrs = lambda p, a: attrs.__setitem__(str(p), a)
        winbadge._shell_refresh = lambda p: refreshed.append(str(p))
    else:
        shell = winbadge._shell_refresh
        winbadge._shell_refresh = lambda p: (refreshed.append(str(p)), shell(p))
    def ini_of(p):
        return winbadge._read_ini(p / "desktop.ini")[0]
    def ours(p):
        return [ln.strip() for ln in ini_of(p).splitlines() if winbadge._is_ours(ln)]
    def badges(p):
        return sorted(n for n in os.listdir(p / ".aht") if n.startswith("aht-badge"))

    old = T / "old"                     # as an older aht left it: the fixed name
    (old / ".aht").mkdir(parents=True)
    (old / ".aht" / ".project-id").write_text("x")
    (old / ".aht" / "aht-badge.ico").write_bytes(b"old picture")
    (old / "desktop.ini").write_bytes(b"[.ShellClassInfo]\r\nIconResource=.aht\\aht-badge.ico,0\r\n"
                                      b"[ViewState]\r\nMode=4\r\n")
    one = winbadge.badge_ico_bytes(["agent:claude"])
    name1 = winbadge.badge_name(one)
    ck(re.fullmatch(r"aht-badge-[0-9a-f]{8}\.ico", name1) is not None, f"the name holds a checksum ({name1})")
    ck(winbadge.apply(old, ["agent:claude"]) == "badged", "a folder with the old fixed name is badged")
    ck(badges(old) == [name1], f"the file has the new name and the old one is gone ({badges(old)})")
    ck((old / ".aht" / name1).read_bytes() == one, "it holds the picture")
    ck(ours(old) == [f"IconResource=.aht\\{name1},0"], f"desktop.ini points at it, once ({ours(old)})")
    ck("[ViewState]" in ini_of(old) and "Mode=4" in ini_of(old), "the rest of desktop.ini stays")
    ck(str(old) in refreshed, "Explorer is told the folder changed")

    stamp = (old / ".aht" / name1).stat().st_mtime_ns
    text = ini_of(old)
    winbadge.apply(old, ["agent:claude"])
    ck(badges(old) == [name1] and (old / ".aht" / name1).stat().st_mtime_ns == stamp
       and ini_of(old) == text, "the same picture again changes nothing")

    two = winbadge.badge_ico_bytes(["agent:claude", "git"])
    name2 = winbadge.badge_name(two)
    winbadge.apply(old, ["agent:claude", "git"])
    ck(name2 != name1 and badges(old) == [name2], f"a new picture gets a new name, the old file goes ({badges(old)})")
    ck(ours(old) == [f"IconResource=.aht\\{name2},0"], "desktop.ini points at the new one")

    winbadge.apply(old, [])
    ck(badges(old) == [], "clearing removes the badge file")
    ck(ours(old) == [] and "Mode=4" in ini_of(old), "and our line; the rest of desktop.ini stays")
    ck((old / ".aht" / ".project-id").is_file(), "the project's marker stays")

    gone = T / "gone"                   # cleared under the old fixed name
    (gone / ".aht").mkdir(parents=True)
    (gone / ".aht" / "aht-badge.ico").write_bytes(b"old picture")
    (gone / "desktop.ini").write_bytes(b"[.ShellClassInfo]\r\nIconResource=.aht\\aht-badge.ico,0\r\n")
    ck(winbadge.apply(gone, []) == "cleared" and not (gone / "desktop.ini").exists()
       and not (gone / ".aht").exists(), "clearing an old-style badge removes desktop.ini, the file and the empty .aht")

    theirs = T / "theirs"               # someone else's icon
    theirs.mkdir()
    custom = b"[.ShellClassInfo]\r\nIconResource=C:\\icons\\mine.ico,0\r\n"
    (theirs / "desktop.ini").write_bytes(custom)
    ck(winbadge.apply(theirs, ["agent:claude"]) == "foreign-icon-kept"
       and (theirs / "desktop.ini").read_bytes() == custom and not (theirs / ".aht").exists(),
       "someone else's icon is left alone, and no badge file is written")

    # ---- the line goes in through the shell (SHGetSetFolderCustomSettings),
    # with a stand-in for it: one that writes it as the shell does, one that
    # writes more than the line, one that fails ----
    set_icon = winbadge._shell_set_icon
    calls = []
    def shell_like(p, icon, extra=()):  # the line at the end of its section
        ini = Path(p) / "desktop.ini"
        lines = [ln for ln in winbadge._read_ini(ini)[0].splitlines()
                 if not ln.lower().startswith("iconresource=")]
        if "[.ShellClassInfo]" not in lines:
            lines.append("[.ShellClassInfo]")
        i = lines.index("[.ShellClassInfo]") + 1
        while i < len(lines) and not lines[i].startswith("["):
            i += 1
        lines[i:i] = [f"IconResource={icon},0", *extra]
        winbadge._write_ini(ini, "\r\n".join(lines) + "\r\n", "utf-8")
        calls.append(icon)
        return True
    via = T / "via"
    (via / ".aht").mkdir(parents=True)
    (via / ".aht" / "aht-badge.ico").write_bytes(b"old picture")
    (via / "desktop.ini").write_bytes(b"[.ShellClassInfo]\r\nIconResource=.aht\\aht-badge.ico,0\r\n"
                                      b"ConfirmFileOp=0\r\n[ViewState]\r\nMode=4\r\n")
    winbadge._shell_set_icon = shell_like
    ck(winbadge.apply(via, ["agent:claude"]) == "badged" and calls == [f".aht\\{name1}"],
       f"the shell is asked to point the folder at the new file ({calls})")
    ck(ours(via) == [f"IconResource=.aht\\{name1},0"] and badges(via) == [name1],
       "desktop.ini points at it, once, and the old file is gone")
    ck("ConfirmFileOp=0" in ini_of(via) and "Mode=4" in ini_of(via), "the rest of desktop.ini stays")
    text = ini_of(via)
    winbadge.apply(via, ["agent:claude"])
    ck(len(calls) == 1 and ini_of(via) == text,
       "the same picture again asks the shell for nothing (its line need not be first)")
    winbadge._shell_set_icon = lambda p, icon: shell_like(p, icon, ("IconFile=" + icon, "IconIndex=0"))
    winbadge.apply(via, ["agent:claude", "git"])
    ck(ours(via) == [f"IconResource=.aht\\{name2},0"] and "iconfile" not in ini_of(via).lower()
       and "Mode=4" in ini_of(via),
       "a shell that writes more than the line: aht writes desktop.ini itself")
    ck(winbadge.apply(via, ["agent:claude", "git"]) == "badged", "and the folder is still ours next time")
    winbadge._shell_set_icon = lambda p, icon: False
    ck(winbadge.apply(via, ["agent:claude"]) == "badged" and ours(via) == [f"IconResource=.aht\\{name1},0"]
       and badges(via) == [name1], "a shell that fails: aht writes desktop.ini itself")
    winbadge.apply(via, [])
    ck(ours(via) == [] and not (via / ".aht").exists() and "ConfirmFileOp=0" in ini_of(via),
       "clearing leaves the rest of desktop.ini")
    winbadge._shell_set_icon = set_icon

    if os.name == "nt":
        # a folder badged where only the drawn folder could be had (e.g. under
        # an older aht that cached it) gets the real one on its next refresh
        fresh()
        proj = T / "proj"
        proj.mkdir()
        winbadge.system_folder_bgra = lambda s: None
        ck(winbadge.apply(proj, ["agent:claude"]) == "badged", "apply badges a folder")
        drawn_ico = proj / ".aht" / badges(proj)[0]
        ck(not ICONS.exists() or not any(ICONS.iterdir()), "the drawn badge is not cached")
        winbadge.system_folder_bgra = real
        ok = all(real(s) is not None for s in winbadge.SIZES)
        print(f"  (this session {'can' if ok else 'cannot'} read the system folder icon)")
        if not ok:
            winbadge.system_folder_bgra = stand_in
        good = winbadge.badge_ico_bytes(["agent:claude"])
        ico = proj / ".aht" / winbadge.badge_name(good)
        said = []
        winbadge._shell_set_icon = lambda p, icon: said.append(set_icon(p, icon)) or said[-1]
        ck(winbadge.apply(proj, ["agent:claude"]) == "badged" and ico.is_file()
           and ico.read_bytes() == good and not drawn_ico.exists(),
           "the next refresh replaces it with the real folder, under a new name")
        winbadge._shell_set_icon = set_icon
        ck(said == [True], f"the shell wrote the line, so an open window shows it at once ({said})")
        ck(ours(proj) == [f"IconResource=.aht\\{ico.name},0"], "desktop.ini points at it")
        ck(winbadge._get_attrs(proj) & winbadge.FILE_ATTRIBUTE_READONLY, "the folder is marked customised")
        winbadge.apply(proj, [])
        ck(not ico.exists() and not (proj / "desktop.ini").exists(), "and clearing it removes both")
finally:
    winbadge.system_folder_bgra = real
    if os.name == "nt":
        for p in (T / d / f for d in ("proj", "old", "gone", "theirs", "via") for f in ("", "desktop.ini")):
            try:
                winbadge._set_attrs(p, winbadge.FILE_ATTRIBUTE_NORMAL)
            except Exception:
                pass
    shutil.rmtree(T, ignore_errors=True)

print("\nWINBADGE RESULT:", "ALL PASS" if not FAILS else "%d FAIL" % len(FAILS))
for f in FAILS:
    print("  -", f)
sys.exit(1 if FAILS else 0)
