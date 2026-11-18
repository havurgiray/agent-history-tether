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

- **Update Claude Code from aht (Mac and Windows):** the ∞ menu and the Windows tray have **Update Claude Code…** (`aht update --claude`). aht updates it the way it was installed (Homebrew, winget, npm or its own installer), then starts the open sessions again on the new version, each in its own tab, where it left off and with the options it had: an idle session at once, a working one when its task is over. winget cannot replace Claude Code while it runs, so there every session ends first. `aht checkup --restart-older` does only the restart.
- **Save, restore or restart the workspace from the corner list (Mac and Windows):** every right-click on the session corner, on a session, beside the sessions or on the top line when none is open, now ends with **Save Workspace Now**, **Restore Workspace…** and **Restart Workspace…**. Save says how many tabs and sessions it kept. Restore opens aht's window on the saved workspaces. Restart starts every open Claude session again in its tab; it lists first which restart at once, which once their task is over and which stay as they are, then asks.
- **Fix (aht's window on Windows and Linux):** the Sessions tab showed its top line twice while the list loaded.
- **Vault: Claude's history behind a password (Mac, off unless you set it up):** `aht vault setup --apply` moves Claude Code's folder, aht's backups of the histories and the search index into encrypted disk images (AES-256, made by macOS) that only your password opens, and shows each image in its folder's old place, so nothing else changes. Locked, nobody reads them: not another account, not an administrator, not someone with a copy of the disk. The ∞ menu then has **Lock Claude's History…** (it offers to save the workspace and end the open sessions) and **Unlock Claude's History…** (then Restore Workspace brings the sessions back). While it is unlocked the files are as readable as before, so lock it when you leave; a restart always locks it. The guide's *Lock Claude's history behind a password* says what it does not cover.

### Before you upgrade

- **Upgrading from a version before 0.17.0?** Read *Before you upgrade* in the [0.17.0 notes](https://github.com/havurgiray/agent-history-tether/releases/tag/v0.17.0) first (the Mac watcher asks for folder access once; backups move into the new store).
- **Update Claude Code… and Restart Workspace… end and resume your real sessions.** Both list what they will do and ask first; text typed into a session but not sent is lost. They were tested with stand-in sessions on a Mac, and the corner's new menu lines with real clicks on Windows 11 on ARM; on the Mac the menu was not clicked through yet. Tell us if something is off.
- **The vault is new.** Setup deletes nothing: the folders as they were stay beside the new ones (readable) until you run `aht vault finish --apply`, so try it, lock and unlock once, and only then finish. There is no way in without the password; aht cannot reset it. It was tested with real encrypted images in test folders, not yet on a real `~/.claude` in daily use.

### Privacy policy

- **Update Claude Code…** runs what Claude Code was installed with (Homebrew, winget, npm or its own updater), which download from where they always do; aht sends nothing itself, and notes in its log which way it updated, the versions and how many sessions it started again.
- **The vault** (macOS, only once you set it up): the images lie beside their folders (`~/.claude.aht-vault.sparsebundle`, two more in `~/.aht`); `~/.aht/vault/vault.json` lists the folders, never the password, which aht hands to `hdiutil` on its standard input and keeps nowhere. The search index moves to `~/.aht/private/`. *Security* says what stays outside the vault.

### For contributors

- `aht workspace --save --json` also says how many tabs and sessions the layout holds (`save_workspace_now()` in the core); `AHT_WINDOW_DO=workspaces` opens aht's window on Restore Workspace without a project.
- `tests/core/22b_update_claude.py` is new; on Windows it still fails checks that assume a POSIX process tree (the Windows CI job does not run it).
- `tests/core/24_vault.py` is new: a whole life of a vault with a stand-in keeper on any system (`AHT_VAULT_KEEPER=stand-in`, not encrypted), and with real `hdiutil` images on a Mac (`AHT_NO_HDIUTIL=1` skips that).
