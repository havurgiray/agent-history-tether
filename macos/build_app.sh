#!/bin/bash
# Build aht.app — the menu bar tray as a redistributable macOS app bundle that
# carries the core (aht.py), the FSEvents watcher and the badge tool prebuilt,
# so a Mac without a compiler can install aht from the app's own menu.
#
#   ./build_app.sh               universal (arm64 + x86_64) into ./build/aht.app + zip
#   ./build_app.sh --host-only   this Mac's architecture only (faster)
#   ./build_app.sh --test        build, then run the tray's headless selftest
#
# Needs only the Xcode Command Line Tools (swiftc) and /usr/bin/python3.
set -euo pipefail
cd "$(dirname "$0")"
REPO="$(cd .. && pwd)"

VERSION="$(sed -n 's/^VERSION = "\(.*\)"/\1/p' "$REPO/aht.py")"
APP_NAME="aht"
EXEC_NAME="aht-tray"                # uninstall.py and the trays look for this name
BUNDLE_ID="com.aht.app"
MIN_MACOS="13.0"
OUT="build"
APP="$OUT/$APP_NAME.app"
RES="$APP/Contents/Resources"
ZIP="$OUT/aht-$VERSION-macos-universal.zip"

HOST_ONLY=0
TEST_AFTER=0
for a in "$@"; do
  case "$a" in
    --host-only) HOST_ONLY=1; ZIP="$OUT/aht-$VERSION-macos-$(uname -m).zip" ;;
    --test) TEST_AFTER=1 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "unknown option: $a"; exit 2 ;;
  esac
done

command -v swiftc >/dev/null 2>&1 || {
  echo "swiftc not found. Install the Xcode Command Line Tools:  xcode-select --install"
  exit 1; }
[ -n "$VERSION" ] || { echo "could not read VERSION from aht.py"; exit 1; }

echo "▸ cleaning"
rm -rf "$OUT"
mkdir -p "$APP/Contents/MacOS" "$RES/bin"

HOST_ARCH="$(uname -m)"
build() {                           # $1 = swift source, $2 = output binary
  local src="$1" out="$2"
  if [ "$HOST_ONLY" = "1" ]; then
    swiftc -O -target "$HOST_ARCH-apple-macos$MIN_MACOS" "$src" -o "$out"
  else
    swiftc -O -target "arm64-apple-macos$MIN_MACOS" "$src" -o "$out.arm64"
    swiftc -O -target "x86_64-apple-macos$MIN_MACOS" "$src" -o "$out.x86_64"
    lipo -create -output "$out" "$out.arm64" "$out.x86_64"
    rm -f "$out.arm64" "$out.x86_64"
  fi
  chmod +x "$out"
}

echo "▸ compiling ($([ "$HOST_ONLY" = "1" ] && echo "$HOST_ARCH" || echo "universal: arm64 + x86_64"))"
build tray.swift "$APP/Contents/MacOS/$EXEC_NAME"
build "$REPO/watcher.swift" "$RES/watcher"
build "$REPO/badge_icon.swift" "$RES/badge_icon"

echo "▸ bundling the core and the installers"
# install.py can also rebuild from these sources should a binary ever go missing
for f in aht.py install.py uninstall.py badge_icon.swift watcher.swift README.md LICENSE; do
  cp "$REPO/$f" "$RES/$f"
done
cp tray.swift "$RES/tray.swift"

# the `aht` command for a Homebrew/cask install (linked into the brew bin dir):
# runs the installed core when there is one, so the CLI, the hook and the
# watcher share a single copy; before `aht install`, the bundled one.
cat > "$RES/bin/aht" <<'SH'
#!/bin/bash
SELF="${BASH_SOURCE[0]}"
while [ -L "$SELF" ]; do
  DIR="$(cd "$(dirname "$SELF")" && pwd)"
  SELF="$(readlink "$SELF")"
  case "$SELF" in /*) ;; *) SELF="$DIR/$SELF" ;; esac
done
RES="$(cd "$(dirname "$SELF")/.." && pwd)"
export AHT_BUNDLE_RESOURCES="$RES"
CORE="$HOME/.aht/tools/agent-history-tether/aht.py"
[ -f "$CORE" ] || CORE="$RES/aht.py"
exec /usr/bin/python3 "$CORE" "$@"
SH
chmod +x "$RES/bin/aht"

echo "▸ rendering the app icon"
ICONSET="$OUT/AppIcon.iconset"
mkdir -p "$ICONSET"
/usr/bin/python3 - "$REPO" "$ICONSET" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
import aht
out = sys.argv[2]
for s in (16, 32, 64, 128, 256, 512, 1024):
    png = aht.app_icon_png(s)
    names = [f"icon_{s}x{s}.png"] if s != 1024 else []
    if s >= 32:
        names.append(f"icon_{s // 2}x{s // 2}@2x.png")
    for n in names:
        open(f"{out}/{n}", "wb").write(png)
PY
iconutil -c icns "$ICONSET" -o "$RES/AppIcon.icns"
rm -rf "$ICONSET"

echo "▸ writing Info.plist"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>$APP_NAME</string>
    <key>CFBundleDisplayName</key><string>agent-history-tether</string>
    <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
    <key>CFBundleExecutable</key><string>$EXEC_NAME</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>$VERSION</string>
    <key>CFBundleVersion</key><string>$VERSION</string>
    <key>CFBundleIconFile</key><string>AppIcon</string>
    <key>LSMinimumSystemVersion</key><string>$MIN_MACOS</string>
    <key>LSUIElement</key><true/>
    <key>NSHighResolutionCapable</key><true/>
    <key>NSHumanReadableCopyright</key><string>Copyright (C) 2026 Giray Havur. AGPL-3.0-or-later.</string>
    <key>NSDesktopFolderUsageDescription</key>
    <string>aht watches your project folders so each project's agent histories follow it when you move or rename the folder.</string>
    <key>NSDocumentsFolderUsageDescription</key>
    <string>aht watches your project folders so each project's agent histories follow it when you move or rename the folder.</string>
</dict>
</plist>
PLIST

echo "▸ signing (ad-hoc)"
# Ad-hoc: enough for Apple Silicon to run the binaries and for Homebrew's
# --no-quarantine installs; a downloaded copy still meets Gatekeeper until a
# Developer ID signs and notarizes it (see the README).
for bin in "$RES/watcher" "$RES/badge_icon" "$APP/Contents/MacOS/$EXEC_NAME"; do
  codesign --force --sign - --timestamp=none "$bin" >/dev/null 2>&1
done
codesign --force --sign - --timestamp=none "$APP" >/dev/null 2>&1 \
  && echo "  ok" || echo "  ⚠ ad-hoc signing failed (the app still runs)"

echo "▸ zipping"
ditto -c -k --keepParent "$APP" "$ZIP"

echo
echo "✅ built $APP  ($VERSION)"
echo "   archive:  $ZIP"

if [ "$TEST_AFTER" = "1" ]; then
  echo
  echo "▸ selftest (headless)"
  "$APP/Contents/MacOS/$EXEC_NAME" --selftest
  "$RES/bin/aht" version
  "$RES/badge_icon" preview "$OUT/badge-preview.png" git agent:claude agent:kimi >/dev/null \
    && echo "badge tool OK" || echo "⚠ badge tool preview failed"
fi
