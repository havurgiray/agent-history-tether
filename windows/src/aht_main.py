#!/usr/bin/env python3
"""aht for Windows — entry point.

Keeps the shared core (aht.py) byte-identical to the macOS/Linux original:
  1. registers win_fcntl as `fcntl` BEFORE the core is imported (Windows has
     no stdlib fcntl; the shim maps flock onto msvcrt byte-range locks)
  2. imports the core, then lets winlayer patch the platform seams
  3. routes the Windows-only subcommands (watch / install / uninstall) to the
     layer and everything else straight into the core's own CLI

Two hidden commands skip the layer: `_agent` (the far end of a handover,
JSON in and out) and `_core` (the core's checksum) answer another aht, not
a person, so they set up nothing for this desktop.  `_pick-folder` shows
the folder chooser for aht's window, in a process of its own
(aht_web.pick_folder_here).
"""
import os
import sys
from pathlib import Path

if os.name == "nt":
    import win_fcntl
    sys.modules.setdefault("fcntl", win_fcntl)

if not getattr(sys, "frozen", False):
    # running from source: the shared core lives two levels up, at the repo root
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import aht  # noqa: E402

WIN_COMMANDS = ("watch", "install", "uninstall")
BARE_COMMANDS = ("_agent", "_core")     # no Windows layer: answers for another aht


def pick_folder(argv) -> int:
    """`aht _pick-folder`: the folder chooser, for aht's window.  Its own
    process, so the window's server can bring the dialog to the front."""
    if os.name == "nt":
        import winlayer
        winlayer.enable_dpi_awareness()       # a sharp dialog on a scaled display
    import aht_web
    return aht_web.pick_folder_here(argv) or 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else ""
    if cmd == "_pick-folder":
        return pick_folder(argv[1:])
    if os.name == "nt":
        if cmd not in BARE_COMMANDS:
            import winlayer
            winlayer.activate()
            if cmd in winlayer.COMMANDS:
                return winlayer.COMMANDS[cmd](argv[1:])
    elif cmd in WIN_COMMANDS:
        print(f"'{cmd}' is Windows-only in this build; on {sys.platform} "
              f"use the installers in the aht repo", file=sys.stderr)
        return 2
    return aht.main(argv)


if __name__ == "__main__":
    sys.exit(main() or 0)
