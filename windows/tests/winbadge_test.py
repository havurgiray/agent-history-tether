#!/usr/bin/env python3
"""The Windows folder badge's icon cache, on any OS (winbadge.py imports
anywhere; only its Win32 calls need Windows): a badge that had to use the
drawn stand-in folder for any size is kept neither on disk nor in memory,
one made with the real folder is, and the cache files of an older version
are not read and are removed (a newer version's and other files stay).
On Windows also: a folder whose badge was drawn with the stand-in gets the
real one on its next refresh.  Everything goes to a throwaway folder
(LOCALAPPDATA and AHT_HOME point into it).

    python windows/tests/winbadge_test.py
"""
import os
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

    if os.name == "nt":
        # a folder badged where only the drawn folder could be had (e.g. under
        # an older aht that cached it) gets the real one on its next refresh
        fresh()
        proj = T / "proj"
        proj.mkdir()
        winbadge.system_folder_bgra = lambda s: None
        ck(winbadge.apply(proj, ["agent:claude"]) == "badged", "apply badges a folder")
        ico = proj / ".aht" / "aht-badge.ico"
        before = ico.read_bytes()
        ck(not ICONS.exists() or not any(ICONS.iterdir()), "the drawn badge is not cached")
        winbadge.system_folder_bgra = real
        ok = all(real(s) is not None for s in winbadge.SIZES)
        print(f"  (this session {'can' if ok else 'cannot'} read the system folder icon)")
        if not ok:
            winbadge.system_folder_bgra = stand_in
        ck(winbadge.apply(proj, ["agent:claude"]) == "badged" and ico.read_bytes() != before
           and ico.read_bytes() == winbadge.badge_ico_bytes(["agent:claude"]),
           "the next refresh replaces it with the real folder")
        ck("aht-badge.ico" in (proj / "desktop.ini").read_text(encoding="utf-8", errors="replace"),
           "desktop.ini still points at it")
        winbadge.apply(proj, [])
        ck(not ico.exists() and not (proj / "desktop.ini").exists(), "and clearing it removes both")
finally:
    winbadge.system_folder_bgra = real
    if os.name == "nt":
        for p in (T / "proj", T / "proj" / "desktop.ini"):
            try:
                winbadge._set_attrs(p, winbadge.FILE_ATTRIBUTE_NORMAL)
            except Exception:
                pass
    shutil.rmtree(T, ignore_errors=True)

print("\nWINBADGE RESULT:", "ALL PASS" if not FAILS else "%d FAIL" % len(FAILS))
for f in FAILS:
    print("  -", f)
sys.exit(1 if FAILS else 0)
