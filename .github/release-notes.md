### Downloads

| file | for |
|---|---|
| `aht-<version>-macos-universal.zip` | macOS 13+, Apple Silicon and Intel (`aht.app`: menu bar tray + core + watcher + badge tool) |
| `aht-setup-<version>-windows-x64.exe` | **Windows 11 on x64: the installer** (for you only, no admin prompt; Start menu entry, Settings > Apps to remove it) |
| `aht-setup-<version>-windows-arm64.exe` | Windows 11 on ARM: the installer (native build) |
| `aht-<version>-windows-x64.zip` | Windows 11 on x64 without installing (`aht.exe`, `aht-tray.exe` and their `_internal` folder; run `aht install`) |
| `aht-<version>-windows-arm64.zip` | the same for Windows 11 on ARM |
| `SHA256SUMS.txt` | checksums of the above |

Package managers: `brew install --cask havurgiray/tap/aht` (macOS), `winget install havurgiray.aht` (Windows, the installer above), `scoop install aht` (Windows, after adding the `havurgiray/scoop-bucket` bucket). Linux installs from the checkout (`linux/install.sh`).

**Windows, if you used aht before 0.14.0:** Windows Security took the small script older versions started the watcher with at sign-in for malware and removed it, so the watcher may not have started at sign-in since.  0.14.0 starts it without any script; run the installer, or `aht install` once, to set it up again.

**Scoop:** run `aht install` once after `scoop update aht` to 0.14.0.  The hook and the sign-in entry then go through Scoop's `current` folder, so they keep working after later updates.

**Mac, a path with `&` or `<`:** a watched folder, a home folder or an app location whose path holds `&` or `<` now gives valid LaunchAgents (the watcher, the notices, start at login).  Before, launchd would not load them, so the watcher silently did not run.  After the upgrade, Settings > This Mac > *Reinstall or Update aht…* rewrites them (`aht install` in a terminal rewrites the watcher's and the notices').

**Linux:** the watcher's systemd unit now really applies its start limit: when the watcher keeps crashing and is started 5 times within 60 seconds, systemd stops restarting it, instead of trying every 10 seconds forever.  A restart you ask for (Restart Watcher, adding or removing a watched folder, `aht roots`, `aht reload`, setup, or resuming in the tray) clears that limit first: it never stops the watcher, and it starts a stopped one again at once.  `linux/install.sh` (or `aht reload`) rewrites the unit.  Start-at-login entries now also work for folder names with a newline or tab, and when the path to Python holds a `%` they start the same Python by a path without one.

**Linux, git folders:** the git mark is now aht's own emblem, a white disc with a dark "+", instead of the theme's link arrow, which made git folders look like links.  After the update the watcher puts it on every git folder once; `linux_git_emblem` still picks another emblem.  `aht uninstall --remove-icons` now also removes the emblem images aht drew.

**Windows, folder badges:** aht no longer keeps a badge it had to draw without Windows' own folder icon (for example the flat ∞ folder an older aht cached).  A folder whose badge shows such a plain drawn folder gets Windows' own on its next refresh (`aht icons --refresh`, or *Refresh all badges* in the tray) or its next badge change.  aht removes older versions' cache files in `%LOCALAPPDATA%\aht\icons` the first time it makes a badge.

**Removing a history** (`aht tidy --remove-history`, and *Remove…* in the Mac app's Tidy Up): on Windows a history now goes to the Recycle Bin, and only there.  When it cannot (the drive has no Recycle Bin, its bin removes files at once, or the history is bigger than the bin holds), aht changes nothing and says why; you can still delete it yourself.  A link in Claude's history folder (to a folder elsewhere) is listed but never removed: the Mac app's Tidy Up shows it as *Claude Code, a link to a folder elsewhere*, without *Remove…*.  A refused removal prints the name and why, never what it would have done.

**Options given twice** now add up: `aht setup --apply --adopt A --adopt B` takes on both, and `aht config --set backup_keep=20 --set notify_finished=false` sets both.  Before, only the last one counted.

**Choosing a folder in aht's window** (Windows and Linux): *Cancel* just closes the chooser.  On Windows you can type or paste a path into the chooser's *Folder:* field; a path with no folder behind it is reported, and nothing changes.

**New projects:** the *A new project is found* setting is gone.  aht takes on new projects as you work in them; an old config's `new_policy` and `--news` from old scripts are accepted and ignored.  A project you *Forget* now stays forgotten: the next scan does not take it on again, and setting up again lists it unticked.  It comes back with a new Claude Code session in its folder, `aht tag`, `aht adopt` (its question says you told aht to forget it), or by ticking it when you set up again.

**Privacy policy:** [PRIVACY.md](https://github.com/havurgiray/agent-history-tether/blob/main/PRIVACY.md) changed with this release.  aht can now look for new versions (off until you say yes; GitHub then sees your computer's address and which version you run), reads three of iTerm2's settings for *Getting started*, and on Windows and Linux serves aht's window to your own browser at 127.0.0.1 only.  The policy now also lists what a handover reads and changes in Claude Code's `~/.claude.json`, the copies aht keeps of Claude Code's `settings.json`, the files under `~/.aht/run` and the notices check's log, where a history you remove with `aht tidy` goes on each system, when aht reads `~/.ssh/config` and Tailscale's machine list (to list machines you could add, and to reach one you added), that aht's log records your other machines' names (and a Tailscale address it reached one by), that `registry.json` keeps the identifiers of projects you told aht to forget (and the git repositories and declined moves it already kept), `run/autostart.json`, your answer about starting the tray at login, how aht checks a Windows Recycle Bin before and after it moves a history there, the emblem images aht draws on Linux, and the temporary files PowerShell writes for the window's folder chooser on Windows.

**Unsigned builds.** The app is ad-hoc signed, so macOS blocks its first launch (downloaded or Homebrew-installed alike): allow it once under System Settings > Privacy & Security > Open Anyway, or run `xattr -dr com.apple.quarantine /Applications/aht.app`. Windows SmartScreen shows "unknown publisher" on first run: choose *More info > Run anyway*. The checksums above let you verify what you downloaded.

Every artifact was built and smoke-tested on the matching CI runner before publishing.
