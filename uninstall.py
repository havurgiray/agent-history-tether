#!/usr/bin/env python3
"""Uninstall agent-history-tether (watcher + hook + `aht` command).
By default leaves history, registry, markers and folder icons intact (only stops
the automation). Pass --remove-icons to also clear badges from registered folders.
Pass --purge to additionally remove markers + registry (history is NEVER touched)."""
import json, os, shutil, subprocess, sys
from pathlib import Path

HOME = Path.home()
NAME = "agent-history-tether"
TOOLS = HOME / ".aht/tools" / NAME
SETTINGS = HOME / ".claude/settings.json"
LABEL = "com.aht.watcher"
PLIST = HOME / "Library/LaunchAgents" / f"{LABEL}.plist"
REG = HOME / ".aht/registry.json"
CONFIG = HOME / ".aht/config.json"
HOOK_TAIL = "aht.py hook"

def remove_hook():
    """Remove OUR hook and nothing else.  Hooks are grouped by matcher, and a
    group can hold other tools' hooks too — so filter hook-by-hook and only drop
    a group once it is empty."""
    if not SETTINGS.exists():
        return
    try:
        s = json.load(open(SETTINGS))
    except Exception:
        print("⚠ settings.json is not valid JSON — left untouched, hook NOT removed")
        return
    shutil.copy2(SETTINGS, str(SETTINGS) + ".bak-aht-uninstall")
    kept = []
    for g in s.get("hooks", {}).get("SessionStart", []):
        survivors = [h for h in g.get("hooks", [])
                     if not h.get("command", "").endswith(HOOK_TAIL)]
        if survivors:
            g["hooks"] = survivors
            kept.append(g)
    if "hooks" in s and "SessionStart" in s["hooks"]:
        if kept:
            s["hooks"]["SessionStart"] = kept
        else:
            del s["hooks"]["SessionStart"]
            if not s["hooks"]:
                del s["hooks"]
    with open(SETTINGS, "w") as fh:
        json.dump(s, fh, indent=2)
    print("✓ SessionStart hook removed (backup: settings.json.bak-aht-uninstall)")

def quit_app():
    """Stop the tray so it cannot re-create state we are about to remove."""
    subprocess.run(["pkill", "-x", "aht-tray"], capture_output=True)

def remove_agent():
    uid = os.getuid()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{LABEL}"], capture_output=True)
    subprocess.run(["launchctl", "unload", str(PLIST)], capture_output=True)
    if PLIST.exists():
        PLIST.unlink()
    print("✓ watcher LaunchAgent unloaded and removed")

def remove_command():
    for d in (HOME/".npm-global/bin", Path("/usr/local/bin"), HOME/".local/bin"):
        w = d / "aht"
        if w.exists():
            w.unlink()
            print(f"✓ removed `aht` command at {w}")

def registered_paths():
    try:
        return [e["real_path"] for e in json.load(open(REG))["projects"].values()]
    except Exception:
        return []

def remove_icons():
    badge = TOOLS / "badge_icon"
    n = 0
    for p in registered_paths():
        if os.path.isdir(p):
            subprocess.run([str(badge), "clear", p], capture_output=True); n += 1
    print(f"✓ cleared badges from {n} folder(s)")

def purge_markers():
    for p in registered_paths():
        mp = Path(p) / ".aht" / ".project-id"
        try:
            if mp.exists():
                mp.unlink()
        except Exception:
            pass
    for p in (REG, CONFIG, REG.with_suffix(".json.bak")):
        if p.exists():
            p.unlink()
            print(f"✓ removed {p}")
    print("✓ removed markers + registry + config "
          "(the agent CLIs' history stores are untouched)")

if __name__ == "__main__":
    quit_app()
    remove_hook()
    remove_agent()
    remove_command()
    if "--remove-icons" in sys.argv:
        remove_icons()
    if "--purge" in sys.argv:
        purge_markers()
    print("\nAutomation removed. Your Claude history under ~/.claude/projects is untouched.")
    print("Manage background items under System Settings ▸ General ▸ Login Items & Extensions.")
