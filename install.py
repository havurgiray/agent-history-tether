#!/usr/bin/env python3
"""Portable installer for agent-history-tether (aht) on macOS.
Stages the tool into ~/.aht/tools/agent-history-tether/ — from a checkout, or
from aht.app's Resources folder with its prebuilt binaries — compiles whatever
binary is still missing (swiftc), generates the LaunchAgent plist with correct
paths, installs the `aht` command, registers the SessionStart hook (backing up
settings.json), and loads the watcher.  Idempotent."""
import argparse, json, os, shutil, signal, subprocess, sys
from pathlib import Path

HOME = Path.home()
NAME = "agent-history-tether"
TOOLS = HOME / ".aht/tools" / NAME
SETTINGS = HOME / ".claude/settings.json"
LA_DIR = HOME / "Library/LaunchAgents"
LABEL = "com.aht.watcher"
TRAY_LABEL = "com.aht.tray"
PLIST = LA_DIR / f"{LABEL}.plist"
TRAY_PLIST = LA_DIR / f"{TRAY_LABEL}.plist"
PY = "/usr/bin/python3"
SCRIPT = TOOLS / "aht.py"
HOOK_CMD = f"{PY} {SCRIPT} hook"
HOOK_TAIL = "aht.py hook"           # how uninstall/idempotency recognises our hook

SOURCES = ("aht.py", "install.py", "uninstall.py", "badge_icon.swift",
           "watcher.swift", "README.md", "LICENSE")
BINARIES = {"badge_icon": "badge_icon.swift", "watcher": "watcher.swift",
            "aht-tray": "tray.swift"}
COMMAND_DIRS = [HOME/".npm-global/bin", Path("/usr/local/bin"), HOME/".local/bin", HOME/"bin"]

ap = argparse.ArgumentParser(description="install agent-history-tether on this Mac")
ap.add_argument("--src", help="folder to install from: a checkout or "
                "aht.app/Contents/Resources (default: this script's folder)")
ap.add_argument("--keep-pid", type=int, help="(aht.app) pid of the running tray, "
                "so any other tray process is stopped")
ap.add_argument("--tray-exe", help="(aht.app) executable the tray autostart "
                "entry should launch from now on")
ARGS = ap.parse_args()
SRC = Path(ARGS.src or Path(__file__).resolve().parent).resolve()
FROM_APP = ARGS.tray_exe is not None or ".app/Contents/Resources" in str(SRC)
sys.path.insert(0, str(SRC))
import aht                       # noqa: E402  the core: single source of truth for roots

def stage_files():
    """Copy the tool into TOOLS: the sources always, and the prebuilt binaries
    when SRC carries them (aht.app does).  Returns the names copied prebuilt."""
    TOOLS.mkdir(parents=True, exist_ok=True)
    if SRC == TOOLS.resolve():
        return set()             # `aht install` re-run from the installed copy: repair in place
    for f in SOURCES:
        if (SRC / f).is_file():
            shutil.copy2(SRC / f, TOOLS / f)
    tray_src = next((c for c in (SRC / "macos/tray.swift", SRC / "tray.swift")
                     if c.is_file()), None)
    if tray_src:
        shutil.copy2(tray_src, TOOLS / "tray.swift")
    prebuilt = set()
    for name in BINARIES:
        if name == "aht-tray" and FROM_APP:
            continue             # the app itself is the tray
        b = SRC / name
        if b.is_file() and os.access(b, os.X_OK):
            shutil.copy2(b, TOOLS / name)
            (TOOLS / name).chmod(0o755)
            prebuilt.add(name)
    if FROM_APP:
        # a stale standalone tray next to the core would be a second tray
        for f in ("aht-tray", "tray.swift"):
            try:
                (TOOLS / f).unlink()
            except FileNotFoundError:
                pass
    return prebuilt

def compile_binaries(prebuilt):
    for binname, srcname in BINARIES.items():
        if binname in prebuilt or (binname == "aht-tray" and FROM_APP):
            continue
        src, out = TOOLS / srcname, TOOLS / binname
        if not src.exists() or (out.exists() and out.stat().st_mtime >= src.stat().st_mtime):
            continue
        if not shutil.which("swiftc"):
            print(f"⚠ {binname} is not built and swiftc is missing — install the Xcode "
                  "Command Line Tools (xcode-select --install) or use aht.app")
            if binname != "aht-tray":
                sys.exit(1)
            continue
        print(f"compiling {binname}…")
        subprocess.run(["swiftc", str(src), "-o", str(out)], check=True)

def watch_roots():
    # roots come from ~/.aht/config.json (via aht); the plist only lists
    # dirs that currently exist, since FSEvents needs existing paths.
    return [r for r in aht.watch_roots_config() if Path(r).is_dir()]

def write_plist():
    LA_DIR.mkdir(parents=True, exist_ok=True)
    roots = "".join(f"        <string>{r}</string>\n" for r in watch_roots())
    PLIST.write_text(f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>{LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{TOOLS}/watcher</string>
{roots}    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>ProcessType</key><string>Background</string>
    <key>StandardOutPath</key><string>{HOME}/.aht/aht-watcher.log</string>
    <key>StandardErrorPath</key><string>{HOME}/.aht/aht-watcher.err</string>
</dict>
</plist>
''')

def _on_path(d):
    return str(d) in os.environ.get("PATH", "").split(os.pathsep)

def install_command():
    """Install the short `aht` wrapper onto the user's PATH (portable)."""
    found = shutil.which("aht")
    if found and Path(found).parent not in COMMAND_DIRS:
        # e.g. Homebrew's link to the app's own launcher: leave it in charge
        print(f"✓ `aht` command already on PATH at {found} (kept)")
        return
    target = next((d for d in COMMAND_DIRS if d.is_dir() and os.access(d, os.W_OK)
                   and _on_path(d)), None)
    note = ""
    if target is None:
        target = HOME/".local/bin"; target.mkdir(parents=True, exist_ok=True)
        if not _on_path(target):
            note = ('  ↳ add it to PATH:  echo \'export PATH="$HOME/.local/bin:$PATH"\' '
                    '>> ~/.zshrc  (then open a new terminal)')
    wrapper = target / "aht"
    wrapper.write_text(f'#!/bin/bash\nexec {PY} "{SCRIPT}" "$@"\n')
    wrapper.chmod(0o755)
    print(f"✓ `aht` command installed at {wrapper}")
    if note:
        print(note)

def install_hook():
    s = json.load(open(SETTINGS)) if SETTINGS.exists() else {}
    if SETTINGS.exists():
        shutil.copy2(SETTINGS, str(SETTINGS) + ".bak-aht")
    hooks = s.setdefault("hooks", {})
    groups = [g for g in hooks.get("SessionStart", [])
              if not any(h.get("command", "").endswith(HOOK_TAIL) for h in g.get("hooks", []))]
    for matcher in ("startup", "resume"):
        groups.append({"matcher": matcher,
                       "hooks": [{"type": "command", "command": HOOK_CMD, "timeout": 10}]})
    hooks["SessionStart"] = groups
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS, "w") as fh:
        json.dump(s, fh, indent=2)
    print("✓ SessionStart hook registered (backup: settings.json.bak-aht)")

def load_agent():
    uid = os.getuid()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{LABEL}"], capture_output=True)
    r = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(PLIST)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        subprocess.run(["launchctl", "load", "-w", str(PLIST)], capture_output=True)
    v = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
    print("✓ watcher LaunchAgent running" if LABEL in v.stdout
          else f"⚠ plist at {PLIST}; load in your GUI session: launchctl load -w {PLIST}")

def stop_other_trays():
    """The app is the tray now: stop any standalone aht-tray still running."""
    r = subprocess.run(["pgrep", "-x", "aht-tray"], capture_output=True, text=True)
    for pid in (int(p) for p in r.stdout.split() if p.isdigit()):
        if pid != ARGS.keep_pid:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass

def retarget_tray_autostart():
    """An existing 'start at login' entry keeps working after the tray moved
    into the app bundle."""
    if not (ARGS.tray_exe and TRAY_PLIST.exists()):
        return
    TRAY_PLIST.write_text(f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
    <key>Label</key><string>{TRAY_LABEL}</string>
    <key>ProgramArguments</key><array><string>{ARGS.tray_exe}</string></array>
    <key>RunAtLoad</key><true/>
</dict></plist>
''')
    print("✓ tray autostart now launches the app")

if __name__ == "__main__":
    prebuilt = stage_files()
    compile_binaries(prebuilt)
    aht.ensure_config()          # create ~/.aht/config.json with defaults
    write_plist()
    install_command()
    install_hook()
    load_agent()
    if FROM_APP:
        stop_other_trays()
        retarget_tray_autostart()
    print(f"\nInstalled at {TOOLS}. Watching roots: {watch_roots()}")
    print("Reconnect existing projects with:  aht adopt --apply")
    if not FROM_APP:
        print(f"Menu bar tray (optional):          {TOOLS}/aht-tray &")
