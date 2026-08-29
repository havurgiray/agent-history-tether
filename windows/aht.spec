# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the standalone Windows binaries (one-file, x64):
#   aht.exe        the CLI + watcher + hook (console)
#   aht-tray.exe   the system-tray companion (windowed, no console)
#
# The ('X utf8', ...) interpreter option turns on Python's UTF-8 mode so every
# unqualified open() reads/writes UTF-8 — matching Claude Code's transcripts
# and settings.json instead of the machine's ANSI code page.

import os

# the shared core (aht.py) is bundled straight from the repo root — there is
# no per-platform copy that could drift
COMMON = dict(
    pathex=[os.path.join(SPECPATH, 'src'), os.path.join(SPECPATH, os.pardir)],
    binaries=[],
    datas=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter', 'unittest', 'pydoc', 'doctest', 'test',
              'xmlrpc', 'sqlite3', 'lzma', 'bz2', 'curses'],
    noarchive=False,
)

a = Analysis(
    [os.path.join(SPECPATH, 'src', 'aht_main.py')],
    hiddenimports=['winlayer', 'win_fcntl', 'winbadge'],
    **COMMON,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [('X utf8', None, 'OPTION')],
    name='aht',
    icon='app.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
)

tray_a = Analysis(
    [os.path.join(SPECPATH, 'src', 'aht_tray.py')],
    hiddenimports=['winlayer', 'win_fcntl', 'winbadge'],
    **COMMON,
)
tray_pyz = PYZ(tray_a.pure)

tray_exe = EXE(
    tray_pyz,
    tray_a.scripts,
    tray_a.binaries,
    tray_a.datas,
    [('X utf8', None, 'OPTION')],
    name='aht-tray',
    icon='app.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
)
