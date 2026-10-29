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

- **Badges for Antigravity and Mistral Vibe:** a folder where Antigravity (`agy`) or Mistral Vibe (`vibe`) worked now shows their disc too, a magenta ⌃ and an amber ∿, next to the agents aht relinks.
- **Settings:** *Where each agent keeps its history* now also lists Antigravity and Mistral Vibe, marked *only read*, so *Choose…* and *Reset All to Defaults* reach their folders too; so do `aht backends`, `aht status` and the trays' *Agent CLI locations*.
- **Fixes:** *Undo a Session* could compare with the older of two checkpoints taken in the same second; a warning could be logged twice when several aht processes met the same problem at once.
- **winget:** the README and the guide now say what winget installs: the zip, with `aht` on your PATH; run `aht install` after it, and `aht uninstall` before `winget uninstall havurgiray.aht`.

### Before you upgrade

- **Upgrading from a version before 0.14.0?** Read *Before you upgrade* in the [0.14.0 notes](https://github.com/havurgiray/agent-history-tether/releases/tag/v0.14.0) first: on Windows, with Scoop, and on a Mac with `&` or `<` in a path, there is one step to take.
- The new discs come with aht's next look at the agents' folders; `aht icons --refresh` draws them at once.

### Privacy policy

- For the new badges, aht looks at which folders Antigravity's conversations and Mistral Vibe's sessions ran in, from the files it already read for search and summaries, at most every ten minutes, and keeps in `registry.json` only which of the two have sessions in each project.  [PRIVACY.md](https://github.com/havurgiray/agent-history-tether/blob/master/PRIVACY.md) says so (effective 2026-10-29).

### For contributors

- The core test suite is now a set of units in `tests/core/`, each in a sandbox of its own, run side by side by `tests/core_test.py`: about 2 to 3 minutes instead of 18.  `python tests/core/<unit>.py` runs one; `tests/core_test.py --only 17b,16c` runs some.
