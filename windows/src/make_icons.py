#!/usr/bin/env python3
"""Generate app.ico (the agent sparkle) for the exes' embedded icon.
Runs on the BUILD HOST (any OS) — uses only winbadge's pure-Python
rasterisers.  build.sh / build_windows.bat call this before PyInstaller."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from winbadge import ico_bytes, sparkle_overlay  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else "app.ico")
images = {s: sparkle_overlay(s, cx=0.5, cy=0.5, scale=0.94)
          for s in (16, 32, 48, 256)}
out.write_bytes(ico_bytes(images))
print(f"wrote {out}")
