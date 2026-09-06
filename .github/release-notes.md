### Downloads

| file | for |
|---|---|
| `aht-<version>-macos-universal.zip` | macOS 13+, Apple Silicon and Intel (`aht.app`: menu bar tray + core + watcher + badge tool) |
| `aht-<version>-windows-x64.zip` | Windows 11 on x64 (`aht.exe` + `aht-tray.exe`) |
| `aht-<version>-windows-arm64.zip` | Windows 11 on ARM (native build; the x64 one also runs there under emulation) |
| `SHA256SUMS.txt` | checksums of the above |

Package managers: `brew install --cask havurgiray/tap/aht` (macOS), `scoop install aht` (Windows, after adding the `havurgiray/scoop-bucket` bucket). Linux installs from the checkout (`linux/install.sh`).

**Unsigned builds.** The app is ad-hoc signed, so macOS blocks its first launch (downloaded or Homebrew-installed alike): allow it once under System Settings > Privacy & Security > Open Anyway, or run `xattr -dr com.apple.quarantine /Applications/aht.app`. Windows SmartScreen shows "unknown publisher" on first run: choose *More info > Run anyway*. The checksums above let you verify what you downloaded.

Every artifact was built and smoke-tested on the matching CI runner before publishing.
