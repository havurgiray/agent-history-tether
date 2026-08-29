#!/usr/bin/env python3
"""Uninstall aht's Linux automation.

Default: stop and remove the watcher service + the SessionStart hook + the
`aht` command.  Your Claude history under ~/.claude/projects is NEVER
touched, and neither are the folder markers or the registry unless you ask.

  python3 uninstall.py                  stop the automation, keep the data
  python3 uninstall.py --remove-emblems also clear the file-manager emblems
  python3 uninstall.py --purge          also remove markers + registry + config
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

HOME = Path.home()
NAME = "agent-history-tether"
TOOLS = HOME / ".aht/tools" / NAME
SETTINGS = HOME / ".claude/settings.json"
UNIT_NAME = "aht-watcher.service"
UNIT = HOME / ".config/systemd/user" / UNIT_NAME
AUTOSTART = HOME / ".config/autostart/aht-watcher.desktop"
TRAY_AUTOSTART = HOME / ".config/autostart/aht-tray.desktop"
HOOK_TAIL = "aht.py hook"


def stop_service():
    if shutil.which("systemctl"):
        subprocess.run(["systemctl", "--user", "disable", "--now", UNIT_NAME],
                       capture_output=True)
    if UNIT.exists():
        UNIT.unlink()
        if shutil.which("systemctl"):
            subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
        print("✓ systemd user unit removed")
    if AUTOSTART.exists():
        AUTOSTART.unlink()
        print("✓ autostart entry removed")
    if TRAY_AUTOSTART.exists():
        TRAY_AUTOSTART.unlink()
        print("✓ tray autostart entry removed")
    subprocess.run(["pkill", "-f", "aht.*watcher.py"], capture_output=True)
    subprocess.run(["pkill", "-f", "aht.*tray.py"], capture_output=True)


def remove_hook():
    if not SETTINGS.exists():
        return
    try:
        s = json.load(open(SETTINGS))
    except Exception:
        print("⚠ settings.json is not valid JSON — left untouched")
        return
    shutil.copy2(SETTINGS, str(SETTINGS) + ".bak-aht-uninstall")
    groups = []
    for g in s.get("hooks", {}).get("SessionStart", []):
        keep = [h for h in g.get("hooks", [])
                if not h.get("command", "").endswith(HOOK_TAIL)]
        if keep:
            g["hooks"] = keep
            groups.append(g)
    if "hooks" in s:
        if groups:
            s["hooks"]["SessionStart"] = groups
        else:
            s["hooks"].pop("SessionStart", None)
        if not s["hooks"]:
            s.pop("hooks")
    json.dump(s, open(SETTINGS, "w"), indent=2)
    print("✓ SessionStart hook removed (backup: settings.json.bak-aht-uninstall)")


def remove_command():
    for d in (HOME / ".local/bin", Path("/usr/local/bin"), HOME / "bin"):
        w = d / "aht"
        try:
            if w.is_file() and "aht.py" in w.read_text():
                w.unlink()
                print(f"✓ removed {w}")
        except Exception:
            pass


def load_core():
    for c in (TOOLS / "aht.py", Path(__file__).resolve().parent.parent / "aht.py",
              Path(__file__).resolve().parent / "aht.py"):
        if c.is_file():
            sys.path.insert(0, str(c.parent))
            import importlib
            return importlib.import_module("aht")
    return None


def clear_emblems(aht):
    n = 0
    reg = aht.load_registry()
    for e in reg.get("projects", {}).values():
        if Path(e["real_path"]).is_dir():
            aht.apply_badge(e["real_path"], [])
            n += 1
    print(f"✓ cleared emblems on {n} folder(s)")


def purge(aht):
    reg = aht.load_registry()
    n = 0
    for e in reg.get("projects", {}).values():
        m = Path(e["real_path"]) / aht.MARKER_REL
        try:
            if m.is_file():
                m.unlink()
                n += 1
                d = m.parent
                if d.is_dir() and not any(d.iterdir()):
                    d.rmdir()
        except Exception:
            pass
    print(f"✓ removed {n} folder marker(s)")
    for p in (aht.registry_path(), aht.config_path(),
              aht.registry_path().with_suffix(".json.bak")):
        if p.exists():
            p.unlink()
            print(f"✓ removed {p}")
    print("  (history under ~/.claude/projects was NOT touched)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--remove-emblems", action="store_true", dest="emblems")
    ap.add_argument("--purge", action="store_true",
                    help="also remove markers, registry and config")
    a = ap.parse_args()
    stop_service()
    remove_hook()
    remove_command()
    core = load_core()
    if core and a.emblems:
        clear_emblems(core)
    if core and a.purge:
        purge(core)
    if TOOLS.is_dir() and a.purge:
        shutil.rmtree(TOOLS, ignore_errors=True)
        print(f"✓ removed {TOOLS}")
    print("\nDone. Your Claude history under ~/.claude/projects is untouched.")
