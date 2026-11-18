### Downloads

| file | for |
|---|---|
| `aht-<version>-macos-universal.zip` | macOS 13+, Apple Silicon and Intel (`aht.app`: menu bar tray + core + watcher + badge tool) |
| `aht-setup-<version>-windows-x64.exe` | **Windows 11 on x64: the installer** (for you only, no admin prompt; Start menu entry, Settings > Apps to remove it) |
| `aht-setup-<version>-windows-arm64.exe` | Windows 11 on ARM: the installer (native build) |
| `aht-<version>-windows-x64.zip` | Windows 11 on x64 without installing (`aht.exe`, `aht-tray.exe` and their `_internal` folder; run `aht install`) |
| `aht-<version>-windows-arm64.zip` | the same for Windows 11 on ARM |
| `SHA256SUMS.txt` | checksums of the above |

Package managers: `brew install --cask havurgiray/tap/aht` (macOS), `winget install havurgiray.aht` (Windows, the zip above, then `aht install`), `scoop install aht` (Windows, after adding the `havurgiray/scoop-bucket` bucket). Linux installs from the checkout (`linux/install.sh`).

### In short

A round of fixes after a review of 0.17.1's new parts: Restart Workspace, Update Claude Code and Restore Workspace.

- **A restart never ends a session it cannot bring back (Mac and Windows).** Before aht ends a session it looks at its tab once more, and leaves the session running when the tab is not there. It resumes a session from the conversation's own folder, also when Claude had changed directory. If a session ended and aht then could not type into its tab, it says how to continue that one and leaves the others running. Only one restart or update runs at a time. On Windows the session that asks is left out, and a winget update ends no session it has no way to start again.
- **A session keeps exactly the options it had.** aht reads them from the session's own arguments. Before, a folder with a space in its name (`--add-dir`) came apart, and words of a first prompt could be taken for options.
- **Update Claude Code… says what it will do, and what it did.** The question names every open session that restarts if the update brings a newer version (before, only those already behind), and says that text typed but not sent is lost. A notice says how the update went as soon as it is through, a second one when the sessions have started again, and a message names each session that did not, with why and how to continue it.
- **Restart Workspace… and Update Claude Code… ask safely.** Cancel (No on Windows) is the default, a second click while the question is open does nothing, and the menu line shows that it is under way until it is through. A message names each session that did not restart.
- **Restore Workspace says why nothing opens.** With the terminal closed, a saved workspace of plain tabs without a title said "everything in it is open already". It now counts what is in it ("nothing left to open: 3 open already, 2 plain tabs without a title"), names a session that still runs outside the terminal, and puts the reason first in the sheet. The sheet in aht's window on Windows and Linux asks again when you come back to it. What a restore just opened no longer counts as open once the terminal was closed, and what it could not open can be opened again at once.
- **The workspace offered first has something to open.** When the newest saved one holds only plain tabs without a title (saved after the last session ended, say), the sheet now starts on the newest one with a session or a titled tab.
- **Save Now** in the Restore Workspace sheet says when nothing was saved, and why.
- **Windows:** the name box of **Branch…** could not be closed when it was opened twice, and Quit while it was open left the tray running without its icon. The notes over the corner's rows follow the rows, and a session name with an emoji is drawn in full. **End Process…** in aht's window says why a process did not end.
- **aht's window (Windows and Linux)** stays connected after the computer slept.

### Before you upgrade

- **Upgrading from a version before 0.17.0?** Read *Before you upgrade* in the [0.17.0 notes](https://github.com/havurgiray/agent-history-tether/releases/tag/v0.17.0) first (the Mac watcher asks for folder access once; backups move into the new store).
- **Update Claude Code… and Restart Workspace… end and resume your real sessions.** Both list what they will do and ask first; text typed into a session but not sent is lost.
- **How this was tested:** the core with its test suite, the Mac app with its self-test, the Windows parts with their tests on Windows 11 on ARM, where the name box and the notes over the rows were also run for real. The new questions and messages were not clicked through on a screen, on the Mac or on Windows. Tell us if something is off.

### Privacy policy

- aht reads the options a Claude session was started with from that session's own arguments as the system holds them (macOS: `sysctl`; Linux: `/proc`), where it read the list of running programs before. It keeps one more lock file in `~/.aht/run` (`claude-restart.lock`), and its note of what a restore just opened also says when the terminal started.

### For contributors

- `restart_older` and `update_claude` take `run/claude-restart.lock` and answer with the blocker "a restart or an update of Claude Code is already under way"; `Terminal.has_pane(key)` asks the terminal now; `open_plan` also returns `failed`, the entries that did not open.
- `aht update --claude --json` (dry run): `restart` lists every session that would restart, not only those on an older version.
- `tests/core/22b_update_claude.py` still fails checks on Windows that assume a POSIX process tree (the Windows CI job does not run it).
