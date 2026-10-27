#!/usr/bin/env python3
"""Linux-layer tests that run on any POSIX box: the polling watcher relinks a
live rename (same code path the inotify backend hands off to), the tray's
--check mode degrades cleanly without desktop deps, the start-at-login entry
that the tray, the core and the installer write reads back as the same paths
(a newline or a tab in them included, and Python by a path without a % when
its own has one), the installer quotes the watcher unit and the hook (and
finds the hook entries older versions wrote) and puts the unit's start limit
where systemd reads it, a reload and the tray's resume clear that limit
before they start the watcher, and the uninstaller takes `aht uninstall`'s
flags (with --remove-icons it removes the emblem images aht drew, and the
icon cache with the last icon there), and the tray's notices say what became
of a handover cut off halfway (finished, undone, or Release offered after an
hour without an answer) and mask a key in what a session waits for, and
vm_check.sh copies no DEVNOTES file to the machine it checks, works there in
a folder of its own in /tmp (not in the home folder) and removes it at the
end."""
import hashlib, json, os, re, shlex, shutil, subprocess, sys, tempfile, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PY = os.environ.get("AHT_PY", sys.executable or "python3")
FAILS = []
def ck(c, m):
    print(("  PASS " if c else "  FAIL ") + m)
    if not c:
        FAILS.append(m)

ESC = {"s": " ", "n": "\n", "t": "\t", "r": "\r", "\\": "\\"}
def exec_argv(v):
    """An Exec= value as a desktop (GLib) reads it: a string value first, whose
    only escapes are \\s \\n \\t \\r and \\\\ (anything else makes the entry
    unreadable), then the quoting rule inside "..." (\\ " ` and $ after a
    backslash); %% is a literal %."""
    def esc(m):
        if m.group(1) not in ESC:
            raise ValueError("not a key-file escape: \\" + m.group(1))
        return ESC[m.group(1)]
    v = re.sub(r"\\(.?)", esc, v)
    return [(re.sub(r'\\([\\"`$])', r"\1", m.group(1)) if m.group(1) is not None
             else m.group(2)).replace("%%", "%")
            for m in re.finditer(r'"((?:[^"\\]|\\.)*)"|(\S+)', v)]

CESC = {"a": "\a", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v",
        "s": " ", "\\": "\\", '"': '"', "'": "'"}
def unit_argv(v):
    """An ExecStart= value as systemd reads the words install.py writes:
    each in double quotes, whose C escapes (systemd.syntax(7): \\n, \\t,
    \\\\, \\" and the like) are undone first, then $$ for $ and %% for %."""
    if not re.fullmatch(r'(?:"(?:[^"\\]|\\.)*" ?)+', v):
        return None
    def esc(m):
        if m.group(1) not in CESC:
            raise ValueError("not a C escape: \\" + m.group(1))
        return CESC[m.group(1)]
    return [re.sub(r"\\(.)", esc, w).replace("$$", "$").replace("%%", "%")
            for w in re.findall(r'"((?:[^"\\]|\\.)*)"', v)]

def sections(text):
    """The keys of a unit file, by section."""
    out, cur = {}, None
    for l in text.splitlines():
        m = re.fullmatch(r"\[(.+)\]", l.strip())
        if m:
            cur = out.setdefault(m.group(1), [])
        elif cur is not None and "=" in l and not l.lstrip().startswith(("#", ";")):
            cur.append(l.split("=", 1)[0].strip())
    return out

sb = Path(tempfile.mkdtemp(prefix="aht_linux_"))
roots = sb / "roots"
(roots / "projA").mkdir(parents=True)
(sb / "claude").mkdir()
(sb / "home").mkdir()
env = dict(os.environ)
env.update({"HOME": str(sb / "home"),        # nothing here may touch the real home
            "AHT_HOME": str(sb / ".aht"), "AHT_ROOTS": str(roots),
            "AHT_ROOT_CLAUDE": str(sb / "claude"),
            "AHT_NO_ICONS": "1", "AHT_NO_NOTIFY": "1", "AHT_NO_BACKUP": "1",
            "AHT_ASSUME": "Relink",
            # the watcher's detached search update would write into the
            # sandbox after it is removed
            "AHT_NO_SEARCH_INDEX": "1"})
for b in ("GEMINI", "CURSOR", "OPENCODE", "CODEX", "COPILOT", "KIMI",
          "KIMI_CODE", "VIBE"):
    env[f"AHT_ROOT_{b}"] = str(sb / "nope")

enc = lambda p: re.sub(r"[^a-zA-Z0-9]", "-", p)
projA = os.path.realpath(str(roots / "projA"))
(sb / "claude" / enc(projA)).mkdir()
(sb / "claude" / enc(projA) / "s1.jsonl").write_text("{}\n")
subprocess.run([PY, str(ROOT / "aht.py"), "tag", projA, "--apply"],
               env=env, capture_output=True)

print("\n[1] polling watcher relinks a live rename")
proc = subprocess.Popen([PY, str(ROOT / "linux" / "watcher.py"),
                         "--poll", "--poll-interval", "1", "--once",
                         "--no-startup-scan"],
                        env=env, stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT, text=True)
time.sleep(2.5)
shutil.move(projA, str(roots / "projB"))
projB = os.path.realpath(str(roots / "projB"))
try:
    proc.wait(timeout=60)
    ck(True, "watcher handled the batch and exited (--once)")
except subprocess.TimeoutExpired:
    proc.kill()
    ck(False, "watcher did not exit")
ck((sb / "claude" / enc(projB)).is_dir(), "claude store relinked by the watcher")

print("\n[2] tray --check degrades cleanly without desktop deps")
r = subprocess.run([PY, str(ROOT / "linux" / "tray.py"), "--check"],
                   env=env, capture_output=True, text=True)
ck(r.returncode in (0, 3),
   "tray --check exits 0 (deps present) or 3 (missing), got %d" % r.returncode)
ck("core" in r.stdout and "aht" in r.stdout, "check reports the core wiring")
ck((sb / ".aht" / "aht-icons" / "aht-tray.png").is_file(),
   "tray icons generated into the (fake) aht home")
if r.returncode == 3:
    ck("PyGObject" in r.stdout or "apt install" in r.stdout,
       "missing-deps message carries install hints")

print("\n[3] the start-at-login entry keeps an odd path whole")
odd = '/home/Ann Lee/a"b$c`d\\e%f\ng\th'
r = subprocess.run([PY, "-c", "import sys; sys.path.insert(0, sys.argv[1]); import tray; "
                    "print(tray.desktop_arg(sys.argv[2])); print(tray.autostart_entry())",
                    str(ROOT / "linux"), odd], env=env, capture_output=True, text=True)
lines = r.stdout.splitlines()
# the file holds "/home/Ann Lee/a\\"b\\$c\\`d\\\\e%%f\ng\th": the Exec quoting
# rule, then the string escapes a reader undoes first (so \\$ is a literal $,
# and the newline and the tab stay on the line)
ck(lines[:1] == ['"/home/Ann Lee/a\\\\"b\\\\$c\\\\`d\\\\\\\\e%%f\\ng\\th"'],
   "an Exec= argument is quoted as the Desktop Entry spec asks")
try:
    back = exec_argv(lines[0]) if lines else None
except ValueError:
    back = None
ck(back == [odd], "the argument reads back as the same path")
tail = ' "%s"' % (ROOT / "linux" / "tray.py")
ck(any(l.startswith('Exec="') and l.endswith(tail) for l in lines),
   "the tray's entry quotes both paths")
# the core's `aht autostart on` rewrites an entry whose text differs, so the
# tray's menu item and the core must write the same bytes to the same file
auto = sb / "autostart"
aenv = dict(env, AHT_AUTOSTART_DIR=str(auto))
r = subprocess.run([PY, str(ROOT / "aht.py"), "autostart", "on", "--json"],
                   env=aenv, capture_output=True, text=True)
core_text = (auto / "aht-tray.desktop").read_text() if (auto / "aht-tray.desktop").is_file() else ""
r2 = subprocess.run([PY, "-c", "import sys; sys.path.insert(0, sys.argv[1]); import tray; "
                     "sys.stdout.write(str(tray.AUTOSTART) + '\\n' + tray.autostart_entry())",
                     str(ROOT / "linux")], env=aenv, capture_output=True, text=True)
where, _, tray_text = r2.stdout.partition("\n")
ck(core_text and core_text == tray_text,
   "the core and the tray write the same start-at-login entry")
ck(where == str(auto / "aht-tray.desktop"), "the tray uses the core's autostart file")
subprocess.run([PY, str(ROOT / "aht.py"), "autostart", "off"], env=aenv, capture_output=True)
ck(not (auto / "aht-tray.desktop").exists(), "autostart off removes the entry")
# the tray's own switch answers the tray-at-login question as `aht autostart
# on|off` does, so aht's welcome keeps that answer
(sb / ".aht" / "run" / "autostart.json").unlink(missing_ok=True)
r = subprocess.run([PY, "-c", "import json, sys; sys.path.insert(0, sys.argv[1]); import tray\n"
                    "tray.notify = lambda *a: None\n"
                    "class Shown:\n"
                    "    def refresh(self): pass\n"
                    "out = []\n"
                    "for _ in range(2):\n"
                    "    tray.Tray.act_toggle_autostart(Shown(), None)\n"
                    "    a = tray.aht.tray_autostart()\n"
                    "    out.append([tray.AUTOSTART.is_file(), a['on'], a['answered']])\n"
                    "print(json.dumps(out))", str(ROOT / "linux")],
                   env=aenv, capture_output=True, text=True)
try:
    switched = json.loads(r.stdout.splitlines()[-1])
except (ValueError, IndexError):
    switched = r.stderr[-400:]
ck(switched == [[True, True, True], [False, False, True]],
   f"the tray's start-at-login switch counts as the answer ({switched})")

# installed under a home whose name has every character the quoting is
# about, with Python reached through a folder of the same kind (but no %,
# see below): the tray, the core and the installer write the same entry,
# and it reads back as the real paths
home = sb / 'Ann Lee $HOME q"b`c\\d 50%off new\nline\ttab'
tools = home / ".aht" / "tools" / "agent-history-tether"
tools.mkdir(parents=True)
shutil.copy2(ROOT / "aht.py", tools / "aht.py")
for f in ("tray.py", "install.py", "uninstall.py"):
    shutil.copy2(ROOT / "linux" / f, tools / f)
real_py = subprocess.run([PY, "-c", "import sys; print(sys.executable)"],
                         capture_output=True, text=True).stdout.strip()
(sb / 'py thon $PATH q"b`c\\d new\nline\ttab').mkdir()
odd_py = sb / 'py thon $PATH q"b`c\\d new\nline\ttab' / "python3"
os.symlink(real_py, odd_py)
oenv = dict(env, HOME=str(home), AHT_AUTOSTART_DIR=str(sb / "autostart-odd"))
r = subprocess.run([str(odd_py), str(tools / "aht.py"), "autostart", "on", "--json"],
                   env=oenv, capture_output=True, text=True)
f = sb / "autostart-odd" / "aht-tray.desktop"
core_text = f.read_text() if f.is_file() else ""
r2 = subprocess.run([str(odd_py), "-c",
                     "import json, sys; sys.path.insert(0, sys.argv[1]); import tray, install; "
                     "print(json.dumps([sys.executable, tray.autostart_entry(), "
                     "install.desktop_arg(sys.argv[2]) == tray.desktop_arg(sys.argv[2]) and "
                     "install.exec_python(sys.executable) == tray.exec_python(sys.executable)]))",
                     str(tools), odd], env=oenv, capture_output=True, text=True)
try:
    exe, tray_text, same_arg = json.loads(r2.stdout)
except ValueError:
    exe, tray_text, same_arg = "", "", False
    print(r2.stderr[-600:])
ck(same_arg, "install.py quotes an Exec= argument and picks its Python as the tray does")
ck(core_text and core_text == tray_text,
   "the core and the tray write the same entry for odd paths")
execl = next((l[5:] for l in tray_text.splitlines() if l.startswith("Exec=")), "")
try:
    back = exec_argv(execl)
except ValueError:
    back = None
ck(back == [exe, os.path.realpath(tools / "tray.py")],
   "the entry reads back as the real Python and tray paths")
# where Python has GLib (a Linux desktop), the real reader must agree
gi_read = ("import json, sys\n"
           "try:\n"
           "    import gi\n"
           "    gi.require_version('Gio', '2.0')\n"
           "    from gi.repository import Gio, GLib\n"
           "except (ImportError, ValueError, AttributeError):\n"
           "    sys.exit(3)\n"
           "info = Gio.DesktopAppInfo.new_from_filename(sys.argv[1])\n"
           "c = info.get_commandline() if info else None\n"
           "print(json.dumps(GLib.shell_parse_argv(c)[1] if c else None))\n")
if tray_text:
    (sb / "odd.desktop").write_text(tray_text)
    r = subprocess.run([PY, "-c", gi_read, str(sb / "odd.desktop")],
                       env=env, capture_output=True, text=True)
    if r.returncode == 3:
        print("  skip GLib's reading (no PyGObject here)")
    else:
        # GLib expands %% to % only when it launches the command
        ck(r.stdout.strip() and json.loads(r.stdout) ==
           [exe.replace("%", "%%"), os.path.realpath(tools / "tray.py").replace("%", "%%")],
           "GLib reads the entry back as the same paths")

# a % in Python's own path: GLib looks for the program before it turns %%
# into %, so it would never start; the entry names the same Python by its
# real path instead, and the core and the tray still agree
(sb / "py 50%off").mkdir()
pct_py = sb / "py 50%off" / "python3"
os.symlink(real_py, pct_py)
penv = dict(oenv, AHT_AUTOSTART_DIR=str(sb / "autostart-pct"))
r = subprocess.run([str(pct_py), str(tools / "aht.py"), "autostart", "on", "--json"],
                   env=penv, capture_output=True, text=True)
f = sb / "autostart-pct" / "aht-tray.desktop"
core_text = f.read_text() if f.is_file() else ""
r2 = subprocess.run([str(pct_py), "-c", "import sys; sys.path.insert(0, sys.argv[1]); import tray; "
                     "sys.stdout.write(tray.autostart_entry())",
                     str(tools)], env=penv, capture_output=True, text=True)
ck(core_text and core_text == r2.stdout,
   "the core and the tray write the same entry when Python's path has a %")
execl = next((l[5:] for l in r2.stdout.splitlines() if l.startswith("Exec=")), "")
try:
    back = exec_argv(execl)
except ValueError:
    back = None
# (some Pythons, such as Homebrew's framework builds, already report a path
# of their own without the link's % as sys.executable; either will do)
ck(back and len(back) == 2 and "%" not in back[0]
   and os.path.realpath(back[0]) == os.path.realpath(pct_py)
   and back[1] == os.path.realpath(tools / "tray.py"),
   f"the entry starts the same Python by a path without a %, its real path ({back})")
# when even that has a %, the python3 on PATH; with none, the path as it was
(sb / "which").mkdir()
os.symlink(real_py, sb / "which" / "python3")
(sb / "only 5%").mkdir()
os.symlink(real_py, sb / "only 5%" / "python3")
nowhere = str(sb / "gone 50%off" / "python3")
r = subprocess.run([PY, "-c",
                    "import json, os, sys; sys.path.insert(0, sys.argv[1]); import tray, install\n"
                    "out = []\n"
                    "for path in sys.argv[3:]:\n"
                    "    os.environ['PATH'] = path\n"
                    "    out.append([f(sys.argv[2]) for f in (tray.exec_python, install.exec_python)])\n"
                    "print(json.dumps(out))",
                    str(tools), nowhere, str(sb / "which"), str(sb / "only 5%")],
                   env=oenv, capture_output=True, text=True)
try:
    picked = json.loads(r.stdout)
except ValueError:
    picked = None
    print(r.stderr[-600:])
ck(picked == [[str(sb / "which" / "python3")] * 2, [nowhere] * 2],
   "with no other way, the python3 on PATH, else Python's own path")

print("\n[4] the uninstaller takes the flags `aht uninstall` passes")
# --help only: it stops and removes nothing
r = subprocess.run([PY, str(ROOT / "linux" / "uninstall.py"), "--help"],
                   env=env, capture_output=True, text=True)
ck(r.returncode == 0 and all(f in r.stdout for f in ("--remove-icons", "--remove-emblems",
                                                       "--purge")),
   "uninstall.py knows --remove-icons, --remove-emblems and --purge")
# with --remove-icons it also removes the emblem images the core drew and
# their stamp (a new install draws them again); other icons there stay.  A
# stand-in gtk-update-icon-cache writes the icon cache as the real one does
# on a Linux desktop (the cache numbers its calls): the cache is written
# again while other icons are left, and goes with the last of them
icons_bin = sb / "bin-icons"
icons_bin.mkdir()
(icons_bin / "gtk-update-icon-cache").write_text(
    '#!/bin/sh\nfor a; do last="$a"; done\necho "$*" >> "%s"\n'
    'wc -l < "%s" | tr -d " " > "$last/icon-theme.cache"\n'
    % (sb / "icon-cache.log", sb / "icon-cache.log"))
(icons_bin / "gtk-update-icon-cache").chmod(0o755)
xenv = dict(env, XDG_DATA_HOME=str(sb / "xdg-data"),
            PATH=str(icons_bin) + os.pathsep + env.get("PATH", ""))
r = subprocess.run([PY, "-c",
                    "import json, sys; sys.path[:0] = sys.argv[1:3]; import aht, uninstall\n"
                    "base = aht._xdg_data() / 'icons' / 'hicolor'\n"
                    "names = lambda: sorted(str(p.relative_to(base)) for p in base.rglob('*') if p.is_file())\n"
                    "mine = [base / '24x24' / 'emblems' / 'emblem-mine.png',\n"
                    "        base / '48x48' / 'emblems' / 'aht-gitx.png']\n"
                    "ok = aht._ensure_linux_emblems()\n"
                    "for f in mine: f.write_bytes(b'x')\n"
                    "made = names(); uninstall.remove_emblem_files(); left = names()\n"
                    "cache = (base / 'icon-theme.cache').read_text().strip()\n"
                    "again = aht._ensure_linux_emblems()\n"
                    "for f in mine: f.unlink()\n"
                    "uninstall.remove_emblem_files()\n"
                    "print(json.dumps([ok and again, made, left, cache, names()]))",
                    str(ROOT / "linux"), str(ROOT)],     # linux's uninstall.py, not the Mac's
                   env=xenv, capture_output=True, text=True)
try:
    ok, made, left, cache, gone = json.loads(r.stdout.splitlines()[-1])
except (ValueError, IndexError):
    ok, made, left, cache, gone = False, [], r.stderr[-400:], None, None
calls = ((sb / "icon-cache.log").read_text().splitlines()
         if (sb / "icon-cache.log").is_file() else [])
ck(shutil.which("gtk-update-icon-cache", path=xenv["PATH"]) == str(icons_bin / "gtk-update-icon-cache"),
   "the stand-in gtk-update-icon-cache comes first on PATH")
ck(ok and "24x24/emblems/aht-git.png" in made and "48x48/emblems/aht-agent-claude.png" in made
   and any(n.startswith(".aht-emblems-v") for n in made) and "icon-theme.cache" in made
   and left == ["24x24/emblems/emblem-mine.png", "48x48/emblems/aht-gitx.png", "icon-theme.cache"],
   f"--remove-icons removes the emblem images aht drew and their stamp, nothing else ({left})")
ck(cache == "2", f"the icon cache is written again while other icons are left ({cache})")
ck(gone == [] and len(calls) == 3,
   f"the icon cache goes with the last icon there ({gone}, {len(calls)} call(s))")

print("\n[5] the installer quotes the watcher unit and the hook")
# under the same odd home; stand-ins for systemctl (it says a user manager
# runs, so the unit is written), launchctl and schtasks come first on PATH
fake = sb / "bin"
fake.mkdir()
for name in ("systemctl", "launchctl", "schtasks"):
    (fake / name).write_text('#!/bin/sh\necho "%s $*" >> "%s"\n'
                             'case "$*" in *is-system-running*) echo running;; esac\n'
                             % (name, sb / "fake.log"))
    (fake / name).chmod(0o755)
ienv = dict(oenv, PATH=str(fake) + os.pathsep + env.get("PATH", ""))
if shutil.which("systemctl", path=ienv["PATH"]) != str(fake / "systemctl"):
    ck(False, "the stand-in systemctl comes first on PATH")
else:
    hook = lambda c: [{"type": "command", "command": c, "timeout": 10}]
    old = "/usr/bin/python3 %s hook" % (tools / "aht.py")       # as older versions wrote it
    (home / ".claude").mkdir()
    (home / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"SessionStart": [
        {"matcher": "startup", "hooks": hook(old)}, {"matcher": "resume", "hooks": hook(old)},
        {"matcher": "startup", "hooks": hook("echo mine")}]}}))
    r = subprocess.run([str(odd_py), "-c",
                        "import json, sys; sys.path.insert(0, sys.argv[1]); import install, uninstall\n"
                        "s = lambda: json.load(open(install.SETTINGS))['hooks']['SessionStart']\n"
                        "install.write_service(); install.install_hook(); once = s()\n"
                        "install.install_hook(); twice = s()\n"
                        "uninstall.remove_hook(); gone = s()\n"
                        "install.have_systemd_user = lambda: False; install.write_service()\n"
                        "print(json.dumps([install.PY, str(install.SCRIPT), str(install.WATCHER),\n"
                        "                  install.HOOK_CMD, install.UNIT.read_text(), once, twice, gone,\n"
                        "                  install.AUTOSTART.read_text(), install.exec_python(install.PY)]))",
                        str(tools)], env=ienv, capture_output=True, text=True)
    try:
        (ipy, script, watcher, cmd, unit, once, twice, gone,
         entry, epy) = json.loads(r.stdout.splitlines()[-1])
    except (ValueError, IndexError):
        ipy = script = watcher = cmd = unit = entry = epy = ""
        once = twice = gone = []
        print(r.stdout[-600:], r.stderr[-600:])
    execs = next((l[10:] for l in unit.splitlines() if l.startswith("ExecStart=")), "")
    try:
        back = unit_argv(execs)
    except ValueError:
        back = None
    ck(back == [ipy, watcher], "the unit's ExecStart reads back as the real paths")
    keys = sections(unit)
    ck({"StartLimitIntervalSec", "StartLimitBurst"} <= set(keys.get("Unit", []))
       and not [k for k in keys.get("Service", []) if k.startswith("StartLimit")],
       "the unit's start limit is in [Unit], where systemd reads it")
    # without a user manager, an autostart entry starts the watcher instead
    execl = next((l[5:] for l in entry.splitlines() if l.startswith("Exec=")), "")
    try:
        back = exec_argv(execl)
    except ValueError:
        back = None
    ck(back == [epy, watcher], "the watcher's autostart entry reads back as the real paths")
    try:
        words = shlex.split(cmd)
    except ValueError:                       # an unquoted " in the home's name
        words = None
    ck(words == [ipy, script, "hook"], "the hook command is shell-quoted")
    ours = lambda groups: [g.get("matcher") for g in groups
                           if any(h["command"] == cmd for h in g["hooks"])]
    mine = lambda groups: sum(h["command"] == "echo mine" for g in groups for h in g["hooks"])
    ck(sorted(ours(once)) == ["fork", "resume", "startup"] and len(once) == 4 and mine(once) == 1,
       "the hook entries an older version wrote are replaced, others kept")
    ck(twice == once, "installing again finds its own (quoted) entries")
    ck(gone and not ours(gone) and mine(gone) == 1 and len(gone) == 1,
       "the uninstaller removes the quoted entries, others kept")
    log = (sb / "fake.log").read_text() if (sb / "fake.log").is_file() else ""
    ck("is-system-running" in log and "enable" not in log, "only the stand-in systemctl was asked")

    # the unit's start limit counts every start, so a reload clears it before
    # it starts the watcher (the limit is for crash loops), and the tray's
    # resume does the same; its pause only stops the watcher
    (sb / "fake.log").unlink(missing_ok=True)
    r = subprocess.run([str(odd_py), "-c",
                        "import sys; sys.path.insert(0, sys.argv[1]); import install, tray\n"
                        "install.load_agent()\n"
                        "with open(sys.argv[2], 'a') as fh: fh.write('--\\n')\n"
                        "tray.watcher_set(False); tray.watcher_set(True)",
                        str(tools), str(sb / "fake.log")], env=ienv, capture_output=True, text=True)
    log = (sb / "fake.log").read_text() if (sb / "fake.log").is_file() else ""
    by_reload, _, by_tray = log.partition("--\n")
    asked = lambda part: [l.replace("systemctl --user ", "", 1) for l in part.splitlines()]
    u = "aht-watcher.service"
    ck(asked(by_reload) == ["is-system-running", "daemon-reload", "reset-failed " + u,
                            "enable --now " + u, "restart " + u, "is-active " + u],
       f"a reload clears the start limit before it starts the watcher ({asked(by_reload)})")
    ck(asked(by_tray) == ["stop " + u, "reset-failed " + u, "start " + u],
       f"the tray's resume clears it too, its pause only stops ({asked(by_tray)})")

print("\n[6] the tray shows what became of a handover cut off halfway")
# every 30 s the tray asks the core (`aht notices --quiet`), which shows what
# it finds with notify-send when there is a screen: on Linux a stand-in
# notify-send, elsewhere AHT_NOTIFY_LOG notes it.  Three projects
# were being handed over to "box" (a folder stands in for it) when the link
# dropped ten minutes ago: on api the session there runs, on web nothing
# ran, and docs went to a machine that has not answered for over an hour
LINUX = sys.platform.startswith("linux")
nb = Path(os.path.realpath(str(sb))) / "notices"
box = nb / "box"
for d in (nb / "home", nb / "claude", nb / "roots", nb / "bin",
          box / "home" / ".claude" / "sessions"):
    d.mkdir(parents=True)
(nb / "bin" / "notify-send").write_text(   # one line per notice, its words between tabs
    '#!/bin/sh\nfor a; do printf "%%s\\t" "$a"; done >> "%s"\necho >> "%s"\n'
    % (nb / "notify-send.log", nb / "notify-send.log"))
(nb / "bin" / "osascript").write_text("#!/bin/sh\nexit 0\n")      # never a Mac notice
for f in (nb / "bin").iterdir():
    f.chmod(0o755)
nenv = dict(env, HOME=str(nb / "home"), AHT_HOME=str(nb / ".aht"),
            AHT_ROOTS=str(nb / "roots"), AHT_ROOT_CLAUDE=str(nb / "claude"),
            PATH=str(nb / "bin") + os.pathsep + env.get("PATH", ""))
if LINUX:
    nenv.pop("AHT_NO_NOTIFY", None)
    nenv.pop("WAYLAND_DISPLAY", None)
    nenv["DISPLAY"] = ":0"
else:
    nenv["AHT_NOTIFY_LOG"] = str(nb / "notices.jsonl")

def shown():
    """(title, message) of each notice shown so far."""
    if LINUX:
        f = nb / "notify-send.log"
        rows = [l.split("\t") for l in (f.read_text(encoding="utf-8").splitlines()
                                         if f.is_file() else [])]
        return [(r[2], r[3]) for r in rows if r[:2] == ["-a", "aht"] and len(r) > 3]
    f = nb / "notices.jsonl"
    return [(n["title"], n["message"]) for n in
            (json.loads(l) for l in (f.read_text(encoding="utf-8").splitlines()
                                     if f.is_file() else []))]

def tray_tick(**more):
    """The tray's notices timer, once, as it runs it."""
    r = subprocess.run([PY, "-c",
                        "import sys; sys.path.insert(0, sys.argv[1]); import tray\n"
                        "class Shown:\n"
                        "    noticing = False\n"
                        "    def in_thread(self, fn): fn()\n"
                        "tray.Tray._notices(Shown())",
                        str(ROOT / "linux")], env=dict(nenv, **more),
                       capture_output=True, text=True)
    if r.returncode:
        print(r.stderr[-600:])

def project_rows():
    r = subprocess.run([PY, str(ROOT / "aht.py"), "projects", "--json"],
                       env=nenv, capture_output=True, text=True)
    try:
        return {os.path.basename(p["real_path"]): p for p in json.loads(r.stdout)["projects"]}
    except (ValueError, KeyError):
        print(r.stdout[-400:], r.stderr[-400:])
        return {}

# the record a handover writes before anything travels; for api also the
# record of what left, the copy there and a session open in it (this test's
# own process stands in for it)
HANDING = (
    "import json, os, sys, time\n"
    "sys.path.insert(0, sys.argv[1]); import aht\n"
    "box, pid, how = sys.argv[2], int(sys.argv[3]), json.loads(sys.argv[4])\n"
    "now = time.time()\n"
    "for p, kind in how.items():\n"
    "    uid = aht.read_marker(p)\n"
    "    h = {'v': 2, 'attempt': '20261026-010000-' + os.urandom(2).hex(), 'remote': 'box',\n"
    "         'holder': 'box', 'host': 'box', 'driven_by': 'here', 'path': p,\n"
    "         'remote_path': box + p, 'since': aht._now(), 'agent': 'claude',\n"
    "         'step': 'starting', 'at': now - 600}\n"
    "    if kind == 'runs':\n"
    "        hd = aht.handover_dir(uid); hd.mkdir(parents=True, exist_ok=True)\n"
    "        (hd / 'manifest.json').write_text(json.dumps({'v': 2, 'attempt': h['attempt']}))\n"
    "        os.makedirs(box + p)\n"
    "        with open(box + '/home/.claude/sessions/%d.json' % pid, 'w') as fh:\n"
    "            json.dump({'pid': pid, 'cwd': box + p, 'status': 'busy', 'sessionId': 's1'}, fh)\n"
    "    if kind == 'silent':\n"
    "        h.update(unreachable_since=now - 3700, checked_at=now - 120, error='no answer')\n"
    "    if kind == 'told':\n"
    "        h = dict(aht.load_registry()['projects'][uid]['handing'], checked_at=now - 120)\n"
    "    aht._update_entry(uid, handing=h)\n")

def handing(**how):
    paths = {os.path.realpath(str(nb / "roots" / n)): k for n, k in how.items()}
    r = subprocess.run([PY, "-c", HANDING, str(ROOT), str(box), str(os.getpid()),
                        json.dumps(paths)], env=nenv, capture_output=True, text=True)
    if r.returncode:
        print(r.stderr[-600:])

subprocess.run([PY, str(ROOT / "aht.py"), "config", "--set",
                "remotes=" + json.dumps({"box": {"root": str(box)}})],
               env=nenv, capture_output=True)
for n in ("api", "web", "docs"):
    (nb / "roots" / n).mkdir()
    subprocess.run([PY, str(ROOT / "aht.py"), "tag", str(nb / "roots" / n), "--apply"],
                   env=nenv, capture_output=True)
if LINUX and shutil.which("notify-send", path=nenv["PATH"]) != str(nb / "bin" / "notify-send"):
    ck(False, "the stand-in notify-send comes first on PATH")
else:
    handing(api="runs", web="none")
    tray_tick()
    got = shown()
    clock = r"(\d{4}-\d\d-\d\d )?\d\d:\d\d"
    ck(any(t == "api is on box" and re.fullmatch(
               r"Handover of api to box finished: the session there runs "
               r"\(the link had dropped at %s\)" % clock, m) for t, m in got),
       f"a handover whose session runs there is finished, and the tray says so ({got})")
    ck(("web stays here", "The handover of web to box did not finish. "
        "The project stays here; nothing runs there") in got,
       "a handover that started nothing there is undone, and the tray says so")
    rows = project_rows()
    ck(rows.get("api", {}).get("away_remote") == "box" and not rows["api"].get("handing")
       and rows.get("web") and not rows["web"].get("away") and not rows["web"].get("handing"),
       "api is now on box, web stays here; neither handover is unfinished")

    # the machine docs went to does not answer (the link drops after its
    # probe): after an hour, once, the tray offers Release
    n0 = len(shown())
    handing(docs="silent")
    tray_tick(AHT_TEST_DROP="probe")
    got = shown()[n0:]
    ck(any(t == "docs: handover unfinished" and re.fullmatch(
               r"box has not answered since %s\. To work on docs here, release it in aht; "
               r"the work on box stays there\." % clock, m) for t, m in got),
       f"no answer for an hour: the tray offers Release ({got})")
    h = project_rows().get("docs", {}).get("handing") or {}
    ck(h.get("state") == "unreachable" and h.get("release") is True,
       f"the project row offers Release too ({h})")
    handing(docs="told")
    tray_tick(AHT_TEST_DROP="probe")
    ck(not [n for n in shown()[n0:] if n[0].startswith("docs")][1:],
       "the tray says it once, not at every check")

    # what a waiting session waits for may quote a key: the tray shows it
    # masked (this test's own process stands in for the session)
    key = "gh" + "p_" + "Zq7" * 12                 # built from pieces: no key in this file
    srec = nb / "sessions" / ("%d.json" % os.getpid())
    srec.parent.mkdir(exist_ok=True)
    for status, waiting in (("busy", None),
                            ("waiting", "curl -H 'Authorization: token %s'" % key)):
        srec.write_text(json.dumps(dict({"pid": os.getpid(), "sessionId": "w1", "status": status,
                                         "cwd": os.path.realpath(str(nb / "roots" / "web"))},
                                        **({"waitingFor": waiting} if waiting else {}))))
        tray_tick()
    got = [m for t, m in shown() if t == "web waits for you"]
    ck(len(got) == 1 and key not in got[0] and "[GitHub token: " in got[0],
       f"a session that waits for you: what it waits for is masked ({got})")

print("\n[7] vm_check.sh works in a folder of its own in /tmp there, copies no DEVNOTES "
      "file and leaves no copy behind")
# a checkout of its own (DEVNOTES files at the top and further down) and
# stand-ins for ssh and scp that run each command here, in a "far" home
# whose /tmp is far/tmp (the far machine's /tmp in what they are given and
# what they answer); after each command the stand-in ssh notes what that
# /tmp holds
vc = Path(os.path.realpath(str(sb))) / "vmcheck"
repo, far, vbin = vc / "repo", vc / "far", vc / "bin"
for d in (repo / "linux" / "tests", repo / "tests", repo / "docs", far / "tmp", vbin):
    d.mkdir(parents=True)
shutil.copy2(str(ROOT / "linux" / "tests" / "vm_check.sh"), str(repo / "linux" / "tests"))
(repo / "README.md").write_text("# demo\n")
for n in ("DEVNOTES.md", "DEVNOTES-notes.md", "docs/DEVNOTES-old.md"):
    (repo / n).write_text("private notes\n")
(repo / "tests" / "vm_report.py").write_text("")         # the report is not checked here
q = {"far": shlex.quote(str(far)), "log": shlex.quote(str(vc / "far.log"))}
(vbin / "ssh").write_text(
    "#!/bin/bash\n"
    "set -o pipefail\n"
    'while [ $# -gt 0 ]; do case "$1" in -o|-i) shift 2;; -*) shift;; *) break;; esac; done\n'
    "shift\n"                                            # the host
    "F=%(far)s\n"
    'c=$(printf "%%s" "$*" | sed "s#/tmp/#$F/tmp/#g")\n'
    'cd "$F" && HOME="$F" bash -c "$c" | sed "s#$F/tmp/#/tmp/#g"; s=$?\n'
    '(cd "$F/tmp" && find . -type f 2>/dev/null; echo --) >> %(log)s\n'
    "exit $s\n" % q)
(vbin / "scp").write_text(
    '#!/bin/bash\n[ "$1" = -q ] && shift\nF=%(far)s\n'
    'cd "$F" && cp $(printf "%%s" "${1#*:}" | sed "s#^/tmp/#$F/tmp/#") "$2"\n' % q)
for f in vbin.iterdir():
    f.chmod(0o755)
venv = dict(env, PATH=str(vbin) + os.pathsep + env.get("PATH", ""))
if [shutil.which(c, path=venv["PATH"]) for c in ("ssh", "scp")] != [str(vbin / "ssh"), str(vbin / "scp")]:
    ck(False, "the stand-in ssh and scp come first on PATH")
else:
    def vm_check(*more):
        (vc / "far.log").write_text("")
        r = subprocess.run(["bash", str(repo / "linux" / "tests" / "vm_check.sh"), "box",
                            "--no-suites", "--out", str(vc / "out")] + list(more),
                           env=venv, capture_output=True, text=True, timeout=120)
        return r, (vc / "far.log").read_text().splitlines()
    def copies():
        return sorted((far / "tmp").glob("aht-sbx-check.*"))
    r, held = vm_check()
    made = {l.split("/")[1] for l in held if l.startswith("./aht-sbx-check.")}
    ck(len(made) == 1 and re.fullmatch(r"aht-sbx-check\.[A-Za-z0-9]{6}", min(made))
       and {f"./{min(made)}/README.md", f"./{min(made)}/linux/tests/vm_check.sh"} <= set(held),
       f"the checkout is copied into a folder of its own in /tmp there ({sorted(made)} "
       f"{r.stdout[-300:]}{r.stderr[-300:]})")
    ck(not [l for l in held if "DEVNOTES" in l],
       f"no DEVNOTES file goes there ({[l for l in held if 'DEVNOTES' in l]})")
    ck(r.returncode == 0 and not copies() and os.listdir(str(far)) == ["tmp"],
       f"the copy there is gone at the end, and nothing went into the home folder there "
       f"({copies()}, {os.listdir(str(far))}, {r.returncode})")
    r, _held = vm_check("--keep")
    kept = copies()
    ck(len(kept) == 1 and (kept[0] / "README.md").is_file()
       and f"/tmp/{kept[0].name}" in r.stdout,
       f"--keep leaves the copy there and says where ({kept}, {r.stdout[-200:]!r})")

shutil.rmtree(sb, ignore_errors=True)
print("\nLINUX RESULT:", "ALL PASS" if not FAILS else "%d FAIL" % len(FAILS))
for f in FAILS:
    print("  -", f)
sys.exit(1 if FAILS else 0)
