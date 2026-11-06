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

- **Restore Workspace on Windows:** the Sessions tab now has **Restore Workspace…** for Windows Terminal. While aht's tray runs it saves your windows, tabs and the sessions in them; after a restart it brings them back, each session where it left off, with the options it had. With Windows Terminal's *Open windows from a previous session* on, you also get your splits, tab colours and old screen text back. See *Restore my workspace* in the guide.
- **Go to Tab and Restart in Its Tab on Windows:** both are in the Sessions tab now, for sessions in Windows Terminal.
- **Restore Workspace on the Mac:** a session reopens in its conversation's own folder, even when Claude had moved to another folder or the folder was renamed since. Before, such a session could fail to resume. aht also no longer saves a half-opened layout in the minutes after a restore.
- **Saved layouts thin out with age:** all from the last two hours, then one an hour for a day, one a day for a week, one a week for a month and one a month for a year, keeping the fullest of each. This replaces keeping a fixed number.
- **Fix on Windows:** a closed session whose process number was reused could look open.

### Before you upgrade

- **Upgrading from a version before 0.14.0?** Read *Before you upgrade* in the [0.14.0 notes](https://github.com/havurgiray/agent-history-tether/releases/tag/v0.14.0) first: on Windows, with Scoop, and on a Mac with `&` or `<` in a path, there is one step to take.
- The setting `workspace_keep` is gone: aht tells you so if you set it. The first new save thins out the layouts you already have.
- **Windows:** Restore Workspace needs Windows Terminal. So far it has been tried on Windows 11 on ARM. The x64 build is built and tested the same way, but the feature has not been tried on an x64 PC yet: tell us if something is off. Tabs run as administrator are out of aht's reach unless aht runs as administrator too.
- On Windows, session names from tab titles remain Mac-only, and Go to Tab can land one tab off after you drag tabs around.

### Privacy policy

- On Windows, aht now reads window and tab titles through UI Automation, and each pane's id, title, folder and the command lines of the programs in it, for saved workspaces. From a program's environment it keeps only the pane id. It reads Windows Terminal's `state.json`, `elevated-state.json` and `settings.json`, never the files with your screen text, and it changes none of them. To bring a session back it types the command into that pane.
- Saved layouts now exist on Windows too, and their retention changed to the thinning above.

### For contributors

- Terminals now plug in like agents: the workspace code asks a small `Terminal` class in `aht.py`, iTerm2 is one subclass, and Windows Terminal another in `windows/src/winterminal.py`.
- `windows/tests/winterminal_test.py` runs on any system; `windows/tests/vm_terminal.py` drives a real Windows Terminal with real sessions, from source or a built `aht.exe`.
- On a busy machine run the suite with `--jobs 4`: two timing checks can fail when every core is taken.
