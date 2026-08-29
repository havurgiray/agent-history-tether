#!/usr/bin/env python3
"""aht for Windows — entry point.

Keeps the shared core (aht.py) byte-identical to the macOS/Linux original:
  1. registers win_fcntl as `fcntl` BEFORE the core is imported (Windows has
     no stdlib fcntl; the shim maps flock onto msvcrt byte-range locks)
  2. imports the core, then lets winlayer patch the platform seams
  3. routes the Windows-only subcommands (watch / install / uninstall) to the
     layer and everything else straight into the core's own CLI
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


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if os.name == "nt":
        import winlayer
        winlayer.activate()
        if argv and argv[0] in winlayer.COMMANDS:
            return winlayer.COMMANDS[argv[0]](argv[1:])
    elif argv and argv[0] in WIN_COMMANDS:
        print(f"'{argv[0]}' is Windows-only in this build; on {sys.platform} "
              f"use the installers in the aht repo", file=sys.stderr)
        return 2
    return aht.main(argv)


if __name__ == "__main__":
    sys.exit(main() or 0)
