#!/usr/bin/env python3
"""[13] shared artwork (the infinity mark) + install/uninstall entry points."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)

print("\n[13] shared artwork (the infinity mark) + install/uninstall entry points")
probe = r"""
import sys; sys.path.insert(0, sys.argv[1]); import aht
d = 24
b = aht.infinity_rgba(d, (10, 20, 30))
a = [b[i * 4 + 3] for i in range(d * d)]
row = lambda y: a[y * d:(y + 1) * d]
mid = row(11)
mirror = max(abs(p - q) for p, q in zip(mid, mid[::-1]))
flip = max(abs(p - q) for p, q in zip(row(11), row(12)))
print("size", len(b) == d * d * 4)
print("solid", max(a) == 255)
print("crossing", mid[11] > 0 and mid[12] > 0)
print("tips", mid[1] > 0 and mid[22] > 0)
print("hollow-lobes", mid[6] == 0 and mid[17] == 0)
print("corners", a[0] == 0 and a[d - 1] == 0 and a[d * d - 1] == 0)
print("symmetric", mirror <= 2 and flip <= 2)
print("color", b[(11 * d + 11) * 4] == 10 and b[(11 * d + 11) * 4 + 2] == 30)
p = aht.app_icon_png(32)
print("png", p[:8] == b"\x89PNG\r\n\x1a\n")
"""
r = subprocess.run([PY, "-c", probe, str(HERE.parent)], capture_output=True, text=True)
ck(r.returncode == 0 and "False" not in r.stdout,
   "infinity mark: solid symmetric loop, hollow lobes, transparent corners"
   + ("" if r.returncode == 0 else f" ({r.stderr.strip()[-200:]})"))
for line in r.stdout.split("\n"):
    if "False" in line:
        print("        failed check:", line)
r = run("install", "--help")
ck(r.returncode == 0 and "--src" in r.stdout, "aht install --help (no side effects)")
r = run("uninstall", "--help")
ck(r.returncode == 0 and "--purge" in r.stdout, "aht uninstall --help")
# on Linux a checkout's install.py is the Mac one: linux/ first, and the one
# next to aht.py only in the installed tools dir
probe = ("import sys; sys.path.insert(0, sys.argv[1]); import aht; aht.IS_LINUX = True; "
         "print(aht._installer_script('install'), aht._installer_script('uninstall'))")
for nm in ("agent-history-tether", "elsewhere"):
    (sb / "inst" / nm).mkdir(parents=True)
    shutil.copy2(CLI, sb / "inst" / nm / "aht.py")
    for f in ("install.py", "uninstall.py"):
        (sb / "inst" / nm / f).write_text("")
got = [subprocess.run([PY, "-c", probe, str(d)], env=env, capture_output=True,
                      text=True).stdout.split()
       for d in (HERE.parent, sb / "inst" / "agent-history-tether", sb / "inst" / "elsewhere")]
want = [[str((HERE.parent / "linux" / f).resolve()) for f in ("install.py", "uninstall.py")],
        [str((sb / "inst" / "agent-history-tether" / f).resolve())
         for f in ("install.py", "uninstall.py")], ["None", "None"]]
ck(got == want, f"Linux installer: linux/ in a checkout, the tools dir's own, no other ({got})")

done()
