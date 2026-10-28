#!/usr/bin/env python3
"""Installer for agent-history-tether on Linux.

Installs:
  • the tool into  ~/.aht/tools/agent-history-tether/
  • a `aht` command on your PATH  (~/.local/bin)
  • a background watcher as a systemd *user* unit  (falls back to an XDG
    autostart entry when systemd --user is unavailable)
  • the Claude Code SessionStart hook  (backs up settings.json first)

Idempotent: re-running it is always safe.  Nothing here needs root, and nothing
writes outside $HOME.  History under ~/.claude/projects is never touched.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import aht                       # noqa: E402  (installed next to us)

HOME = Path.home()
NAME = "agent-history-tether"
TOOLS = HOME / ".aht/tools" / NAME
SETTINGS = HOME / ".claude/settings.json"
UNIT_NAME = "aht-watcher.service"
UNIT_DIR = HOME / ".config/systemd/user"
UNIT = UNIT_DIR / UNIT_NAME
AUTOSTART = HOME / ".config/autostart/aht-watcher.desktop"
HOOK_TAIL = "aht.py hook"        # how is_our_hook (and uninstall) recognise our hook


def pick_python() -> str:
    """A stable interpreter for the service and the hook.  A distro python3 is
    preferred over whatever venv/conda happens to be active right now, because
    the service must keep working after you deactivate that environment."""
    for c in ("/usr/bin/python3", "/usr/local/bin/python3"):
        if os.access(c, os.X_OK):
            return c
    return shutil.which("python3") or sys.executable


PY = pick_python()
SCRIPT = TOOLS / "aht.py"
WATCHER = TOOLS / "watcher.py"
# a shell runs the hook: each path quoted, so a home folder with a space
# works (a plain path stays as it was)
HOOK_CMD = f"{shlex.quote(PY)} {shlex.quote(str(SCRIPT))} hook"


def is_our_hook(command: str) -> bool:
    """Whether a hook command is aht's, as this installer writes it now (its
    paths shell-quoted) or as older versions did (unquoted)."""
    return command.replace("'", "").endswith(HOOK_TAIL)


def desktop_arg(s) -> str:
    """One argument of an Exec= line, in double quotes so that a path with a
    space stays one argument.  The Desktop Entry spec reads Exec as a string
    first (\\\\ is one backslash, \\n a newline) and then applies its quoting
    rule (\\ " ` and $ take a backslash), so a literal $ is written \\\\$; a
    literal % is %%.  The same bytes as the tray's and the core's."""
    s = re.sub(r'([\\"`$])', r'\\\1', str(s))      # the Exec quoting rule: \ " ` $ get a backslash
    s = s.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t").replace("\r", "\\r")   # the string-value escapes
    return '"' + s.replace("%", "%%") + '"'                 # %% for a literal %


def exec_python(py) -> str:
    """The Python an Exec= line starts.  GLib looks for the program before it
    turns %% into %, so one whose path has a % never starts: then the same
    Python by a path without one, if there is one.  The tray and the core
    pick the same."""
    py = str(py)
    if "%" in py:
        for other in (os.path.realpath(py), shutil.which("python3")):
            if other and "%" not in other:
                return other
    return py


def unit_arg(s) -> str:
    """One argument of the unit's ExecStart=, quoted as systemd reads it: in
    double quotes with \\ and " escaped, a newline, tab and carriage return
    written \\n, \\t and \\r (systemd undoes C escapes there), and $ and %
    doubled (they start a variable and a specifier)."""
    s = str(s).replace("\\", "\\\\").replace('"', '\\"')
    s = s.replace("\n", "\\n").replace("\t", "\\t").replace("\r", "\\r")
    return '"' + s.replace("$", "$$").replace("%", "%%") + '"'


def have_systemd_user() -> bool:
    if not shutil.which("systemctl"):
        return False
    r = subprocess.run(["systemctl", "--user", "is-system-running"],
                       capture_output=True, text=True)
    # "degraded"/"starting"/"running" all mean a user manager is there;
    # "offline"/failure means there is none (containers, some minimal WMs).
    return r.returncode == 0 or "running" in r.stdout or "degraded" in r.stdout


def write_service() -> None:
    """Generate the systemd user unit (or the autostart fallback).
    The unit deliberately takes NO root arguments — the watcher reads
    ~/.claude/config.json itself, so changing roots never needs a rewrite
    of the unit, only a restart."""
    if have_systemd_user():
        UNIT_DIR.mkdir(parents=True, exist_ok=True)
        UNIT.write_text(f"""[Unit]
Description=aht - keep AI coding agents' histories tethered to project folders
Documentation=https://github.com/havurgiray/agent-history-tether
After=graphical-session.target
# a burst of filesystem events must never turn into a busy loop
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
ExecStart={unit_arg(PY)} {unit_arg(WATCHER)}
Restart=on-failure
RestartSec=10
Nice=10

[Install]
WantedBy=default.target
""")
    else:
        AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
        AUTOSTART.write_text(f"""[Desktop Entry]
Type=Application
Name=aht watcher
Comment=Keep Claude Code history tethered to project folders
Exec={desktop_arg(exec_python(PY))} {desktop_arg(WATCHER)}
X-GNOME-Autostart-enabled=true
NoDisplay=true
""")


def load_agent() -> None:
    """(Re)start the watcher.  Named to match the macOS installer so the shared
    core can call either one through the same interface."""
    if have_systemd_user():
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
        # the start limit counts these starts too, but a reload someone asked
        # for is not a crash loop: clear the count first, or a few reloads in
        # a minute would leave the watcher stopped
        subprocess.run(["systemctl", "--user", "reset-failed", UNIT_NAME],
                       capture_output=True)
        subprocess.run(["systemctl", "--user", "enable", "--now", UNIT_NAME],
                       capture_output=True)
        subprocess.run(["systemctl", "--user", "restart", UNIT_NAME], capture_output=True)
        r = subprocess.run(["systemctl", "--user", "is-active", UNIT_NAME],
                           capture_output=True, text=True)
        state = r.stdout.strip()
        print(f"✓ watcher service {state}" if state == "active"
              else f"⚠ watcher is '{state}' — check: journalctl --user -u {UNIT_NAME} -n 50")
    else:
        print(f"✓ autostart entry written to {AUTOSTART}")
        print("  (no systemd --user here — start it now with: "
              f"nohup {shlex.quote(PY)} {shlex.quote(str(WATCHER))} >/dev/null 2>&1 &)")


def _on_path(d: Path) -> bool:
    return str(d) in os.environ.get("PATH", "").split(os.pathsep)


def install_command() -> None:
    candidates = [HOME / ".local/bin", Path("/usr/local/bin"), HOME / "bin"]
    target = next((d for d in candidates
                   if d.is_dir() and os.access(d, os.W_OK) and _on_path(d)), None)
    note = ""
    if target is None:
        target = HOME / ".local/bin"
        target.mkdir(parents=True, exist_ok=True)
        if not _on_path(target):
            note = ("  ↳ add it to PATH:  echo 'export PATH=\"$HOME/.local/bin:$PATH\"'"
                    " >> ~/.bashrc   (or ~/.zshrc), then open a new terminal")
    wrapper = target / "aht"
    wrapper.write_text(f'#!/bin/sh\nexec {shlex.quote(PY)} {shlex.quote(str(SCRIPT))} "$@"\n')
    wrapper.chmod(0o755)
    print(f"✓ `aht` command installed at {wrapper}")
    if note:
        print(note)


def install_hook() -> None:
    s = {}
    if SETTINGS.exists():
        try:
            s = json.load(open(SETTINGS))
        except Exception:
            print("⚠ settings.json is not valid JSON — leaving it alone; "
                  "the hook was NOT installed")
            return
        shutil.copy2(SETTINGS, str(SETTINGS) + ".bak-aht")
    hooks = s.setdefault("hooks", {})
    groups = [g for g in hooks.get("SessionStart", [])
              if not any(is_our_hook(h.get("command", ""))
                         for h in g.get("hooks", []))]
    for matcher in ("startup", "resume", "fork"):   # fork: /branch, --fork-session
        groups.append({"matcher": matcher,
                       "hooks": [{"type": "command", "command": HOOK_CMD, "timeout": 10}]})
    hooks["SessionStart"] = groups
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS, "w") as fh:
        json.dump(s, fh, indent=2)
    print("✓ SessionStart hook registered (backup: settings.json.bak-aht)")


def check_inotify_budget(roots) -> None:
    try:
        mx = int(Path("/proc/sys/fs/inotify/max_user_watches").read_text().strip())
    except Exception:
        return
    n = sum(1 for r in roots for _ in aht.list_real_dirs([r]))
    if n > mx * 0.5:
        print(f"⚠ {n} directories under your roots vs max_user_watches={mx}.")
        print("  The watcher falls back to polling automatically, but you can raise it:")
        print("    echo 'fs.inotify.max_user_watches=524288' | "
              "sudo tee /etc/sysctl.d/99-inotify.conf && sudo sysctl --system")


def main() -> None:
    aht.ensure_config()
    roots = [r for r in aht.watch_roots_config() if Path(r).is_dir()]
    install_command()
    install_hook()
    # the watcher's unit (or autostart entry), unless watcher_owner is none
    # (then one left from before is stopped and removed)
    if aht.watcher_install(write_service, load_agent):
        check_inotify_budget(roots)
    print(f"\nInstalled at {TOOLS}. Watching roots: {roots or '(none exist yet)'}")
    print("Reconnect this machine's existing projects with:  aht adopt --apply")


if __name__ == "__main__":
    if not sys.platform.startswith("linux"):
        print(f"This installer is for Linux; on {sys.platform} use ../install.sh")
        sys.exit(1)
    main()
