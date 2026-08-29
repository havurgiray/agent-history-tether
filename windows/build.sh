#!/bin/sh
# Build the standalone Windows aht.exe + aht-tray.exe from
# macOS/Linux via Docker + Wine (PyInstaller cannot cross-compile, so it runs
# inside a Windows-Python-under-wine container), then smoke-test under wine.
#
#   ./build.sh              build + smoke tests
#   ./build.sh --no-test    build only
#
# The whole REPO is mounted so the spec bundles the shared core (../aht.py)
# directly — there is no per-platform copy of the core to drift.
# On an Apple Silicon Mac the amd64 image runs under Rosetta/QEMU — slower,
# but the produced exe is exactly the same x86-64 binary.
set -e
cd "$(dirname "$0")"
REPO="$(cd .. && pwd)"

python3 src/make_icons.py app.ico

IMAGE="${IMAGE:-tobix/pywine:3.12}"

echo "== building with $IMAGE =="
docker run --rm --platform linux/amd64 -v "$REPO":/repo -w /repo/windows "$IMAGE" sh -c '
  set -e
  export WINEDEBUG=-all
  wine python -m pip install --quiet --disable-pip-version-check \
      --no-warn-script-location "pyinstaller==6.*"
  wine python -m PyInstaller --clean -y --distpath dist --workpath /tmp/pyi \
      aht.spec
'

cp dist/aht.exe aht.exe
cp dist/aht-tray.exe aht-tray.exe
echo "built: $PWD/aht.exe + aht-tray.exe"

if [ "$1" != "--no-test" ]; then
  echo "== smoke test (wine) =="
  docker run --rm --platform linux/amd64 -v "$REPO":/repo -w /repo/windows "$IMAGE" \
    sh tests/wine_smoke.sh /repo/windows/aht.exe
  echo "== watcher smoke test (wine) =="
  docker run --rm --platform linux/amd64 -v "$REPO":/repo -w /repo/windows "$IMAGE" \
    sh tests/wine_watch_smoke.sh /repo/windows/aht.exe
fi
