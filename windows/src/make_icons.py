#!/usr/bin/env python3
"""Generate app.ico (the aht loop on a slate disc) for the exes' embedded icon.
Runs on the BUILD HOST (any OS) — uses only the core's pure-Python
rasteriser.  build.sh / build_windows.bat call this before PyInstaller."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))          # the shared core, aht.py
from winbadge import ico_bytes, infinity_overlay  # noqa: E402
import aht  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else "app.ico")
images = {s: infinity_overlay(s, rgb=(255, 255, 255), bg=aht.APP_ICON_RGB,
                              span=0.34, thickness=0.058)
          for s in (16, 32, 48, 256)}
out.write_bytes(ico_bytes(images))
print(f"wrote {out}")
