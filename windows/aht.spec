# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the Windows binaries, one folder (dist\aht) for both:
#   aht.exe        the CLI + watcher + hook (console)
#   aht-tray.exe   the system-tray companion (windowed, no console)
#   _internal\     Python and the libraries, shared by the two
#
# One folder, not one file: a one-file exe unpacks itself into %TEMP% on
# every run (half a second per hook call), leaves that copy behind whenever
# it is killed (the watcher at every shutdown), and self-unpacking exes are
# what antivirus heuristics flag.
#
# The ('X utf8', ...) interpreter option turns on Python's UTF-8 mode so every
# unqualified open() reads/writes UTF-8 — matching Claude Code's transcripts
# and settings.json instead of the machine's ANSI code page.

import os
import re

from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct,
                                                 StringTable, VarFileInfo, VarStruct, VSVersionInfo)

# the version and a description in each exe: Windows shows the description as
# the sender of the tray's notices and in Task Manager
with open(os.path.join(SPECPATH, os.pardir, 'aht.py'), encoding='utf-8') as fh:
    VERSION = re.search(r'^VERSION = "([0-9.]+)"', fh.read(), re.M).group(1)
NUMS = tuple(int(x) for x in (VERSION.split('.') + ['0', '0', '0'])[:4])


def version_info(description, name):
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=NUMS, prodvers=NUMS),
        kids=[StringFileInfo([StringTable('040904B0', [
                  StringStruct('CompanyName', 'aht (agent-history-tether)'),
                  StringStruct('FileDescription', description),
                  StringStruct('FileVersion', VERSION),
                  StringStruct('InternalName', name),
                  StringStruct('OriginalFilename', name + '.exe'),
                  StringStruct('ProductName', 'aht'),
                  StringStruct('ProductVersion', VERSION),
                  StringStruct('LegalCopyright', 'GNU AGPL-3.0-or-later')])]),
              VarFileInfo([VarStruct('Translation', [0x0409, 1200])])])

# the shared core (aht.py) is bundled straight from the repo root — there is
# no per-platform copy that could drift
COMMON = dict(
    pathex=[os.path.join(SPECPATH, 'src'), os.path.join(SPECPATH, os.pardir)],
    binaries=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter', 'unittest', 'pydoc', 'doctest', 'test',
              'xmlrpc', 'lzma', 'bz2', 'curses'],   # sqlite3 stays: search needs it
    noarchive=False,
)

# aht.exe also serves aht's window (`aht window`, aht_web.py): its page and
# the guide travel inside the exe
a = Analysis(
    [os.path.join(SPECPATH, 'src', 'aht_main.py')],
    hiddenimports=['winlayer', 'win_fcntl', 'winbadge', 'aht_web'],
    datas=[(os.path.join(SPECPATH, os.pardir, 'web'), 'web'),
           (os.path.join(SPECPATH, os.pardir, 'GUIDE.md'), '.')],
    **COMMON,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [('X utf8', None, 'OPTION')],
    exclude_binaries=True,
    name='aht',
    icon='app.ico',
    version=version_info('aht', 'aht'),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)

tray_a = Analysis(
    [os.path.join(SPECPATH, 'src', 'aht_tray.py')],
    hiddenimports=['winlayer', 'win_fcntl', 'winbadge'],
    datas=[],
    **COMMON,
)
tray_pyz = PYZ(tray_a.pure)

tray_exe = EXE(
    tray_pyz,
    tray_a.scripts,
    [('X utf8', None, 'OPTION')],
    exclude_binaries=True,
    name='aht-tray',
    icon='app.ico',
    version=version_info('aht', 'aht-tray'),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)

# both exes in one folder, over one _internal\
coll = COLLECT(
    exe, a.binaries, a.datas,
    tray_exe, tray_a.binaries, tray_a.datas,
    strip=False,
    upx=False,
    name='aht',
)
