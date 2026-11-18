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

- **Restart Workspace… now closes the terminal and opens everything again (Mac and Windows).** The line in the session corner's right-click menu saves the workspace, ends every Claude session in a tab, closes iTerm2 (on Windows, Windows Terminal), starts it again and opens the same windows and tabs. Each session comes back in its tab, where it left off and with the options it had, on the Claude Code installed now. Plain tabs come back too, empty, in their folders and with their titles. Before, it restarted each session inside its tab and left the terminal open; that is still there as `aht checkup --restart-older --all --apply`, and **Update Claude Code…** still works that way.
- **It asks first, and says what does not come back.** The question names the sessions, those working now (their task stops; they resume from the conversation so far), how many plain tabs come back empty, and every other program that runs in a tab (a server, `ssh`): those end and do not start again. Cancel (No on Windows) is the default.
- **Two safeguards.** It does not run from a tab of the terminal it would close. If the terminal does not close, the sessions that ended are opened again in it, and a message says so.
- From a terminal: `aht workspace --restart` shows what it would do, `--apply` does it.

### Before you upgrade

- **Upgrading from a version before 0.17.0?** Read *Before you upgrade* in the [0.17.0 notes](https://github.com/havurgiray/agent-history-tether/releases/tag/v0.17.0) first (the Mac watcher asks for folder access once; backups move into the new store).
- **Restart Workspace… closes your terminal.** Text typed but not sent is lost, and so is the text the tabs show. Whatever runs in a tab besides Claude ends. On a Mac, iTerm2 may ask once more whether to quit: say yes there.
- **How this was tested:** on Windows 11 on ARM for real, with two windows, a titled tab, plain tabs and a running program, but without Claude sessions in that run (resuming them is the restore that 0.16 brought). On the Mac only with stand-ins: the real quit and start of iTerm2 was not run, and the new question was not clicked through on either system. Try it first at a moment when losing the terminal's state would not hurt, and tell us if something is off.

### Privacy policy

- For **Restart Workspace…** aht reads whether iTerm2 is set to ask before it quits. Once you say yes, it quits iTerm2 and starts it again (on Windows, it closes Windows Terminal the way Windows does at a sign-out). It changes no setting of either.

### For contributors

- `restart_workspace(apply)` in the core; `Terminal.quit()`, `holds_me()` and `asks_before_quit()` for each terminal; `restore_workspace(..., plain=True, ended=…)` also opens the plain tabs without a title and takes the sessions just ended as not open.
- `aht workspace --restart --json`: `sessions`, `working`, `tabs`, `plain`, `ending`, `asks`; with `--apply` also `opened`, `of`, `workspace`.
