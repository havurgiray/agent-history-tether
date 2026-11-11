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

- **Fix on Windows: resuming a session on a keyboard with AltGr.** On a German keyboard, and on others where `\` `{` `}` `[` `]` `@` `~` or `|` take AltGr, the line that Restore Workspace and Restart in Its Tab type into a Windows PowerShell tab lost those characters. PowerShell then answered *Missing statement block after "if"* and the session did not come back. aht now types them so that PowerShell keeps them. Tabs running cmd were not affected.

Everything else is as in 0.16.0: see its [notes](https://github.com/havurgiray/agent-history-tether/releases/tag/v0.16.0) for what is new there and what to know before you upgrade.

### For contributors

- `key_plan` in `windows/src/winterminal.py` now sends a character that takes AltGr, or that the keyboard layout has no key for, as a key record with virtual key 0. It used VK_PACKET records, and PSReadLine 2.0, the line editor of Windows PowerShell 5.1, drops every one of them.
