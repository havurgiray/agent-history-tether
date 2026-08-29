#!/usr/bin/env python3
"""Portable installer for agent-history-tether (aht).
Compiles the binaries, generates the LaunchAgent plist with correct paths,
installs the `aht` command, registers the SessionStart hook (backing up
settings.json), and loads the watcher. Idempotent."""
import json, os, shutil, subprocess, sys
from pathlib import Path
import aht                       # sibling module: single source of truth for roots

HOME = Path.home()
NAME = "agent-history-tether"
TOOLS = HOME / ".aht/tools" / NAME
SETTINGS = HOME / ".claude/settings.json"
LA_DIR = HOME / "Library/LaunchAgents"
LABEL = "com.aht.watcher"
PLIST = LA_DIR / f"{LABEL}.plist"
PY = "/usr/bin/python3"
SCRIPT = TOOLS / "aht.py"
HOOK_CMD = f"{PY} {SCRIPT} hook"
HOOK_TAIL = "aht.py hook"           # how uninstall/idempotency recognises our hook

def compile_binaries():
    if not shutil.which("swiftc"):
        print("⚠ swiftc not found — install Xcode CLT: xcode-select --install"); sys.exit(1)
    for name, binname in (("badge_icon", "badge_icon"),
                          ("watcher", "watcher"), ("tray", "aht-tray")):
        src, out = TOOLS / f"{name}.swift", TOOLS / binname
        if src.exists() and (not out.exists() or out.stat().st_mtime < src.stat().st_mtime):
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
    candidates = [HOME/".npm-global/bin", Path("/usr/local/bin"), HOME/".local/bin", HOME/"bin"]
    target = next((d for d in candidates if d.is_dir() and os.access(d, os.W_OK) and _on_path(d)), None)
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

if __name__ == "__main__":
    compile_binaries()
    aht.ensure_config()          # create ~/.aht/config.json with defaults
    write_plist()
    install_command()
    install_hook()
    load_agent()
    print(f"\nInstalled at {TOOLS}. Watching roots: {watch_roots()}")
    print("Reconnect existing projects with:  aht adopt --apply")
    print(f"Menu bar tray (optional):          {TOOLS}/aht-tray &")
