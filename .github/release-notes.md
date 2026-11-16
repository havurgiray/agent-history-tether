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

- **Moves are seen in about half a second, without searching your folders.** aht notes the number each project folder has on its disk, and the disk says where that folder is now. The watcher no longer walks Desktop and Documents after every saved file: on a Mac it acts only when a project moved, a copy or a new git repository appeared, or a folder came in from elsewhere. A rename was followed in 0.5 s on a Mac and Windows and 0.9 s on Linux, where before it took 4 to 6 seconds; a project moved out of the watched folders is found too. The folders are still walked when the watcher starts and once a day.
- **Backups take a fraction of the space.** A backup now keeps only what is new since the one before, in a store shared by all backups, with each picture kept once. On one Mac, 19.1 GB of backups became 3.0 GB. They are kept all from two days, then one a day for two weeks, one a week for three months and one a month for a year, and made every 6 hours instead of once a day.
- **Backups… (Projects → More):** see each backup of a project, its sessions, restore one, or start a new project from it, with or without the files from then. **Back Up This Project Now** and **Backups of This Project…** are also in the session corner's right-click menu.
- **The session corner on Windows:** the open Claude sessions in a small list above the taskbar, as on the Mac: which one works, waits for you or is done; a click goes to its tab.
- **Right-click a session in the corner (Mac and Windows):** **Branch…** opens a copy of the conversation in a new tab next to it; **Send to <machine>…** ends the session here and hands its project over, in the same tab, which then shows the session running there. Both are also in the Sessions tab and on the command line (`aht branch`, `aht send`).
- **Handovers say how far they are:** how much went of how much, and the time left, in the corner and the window, also while Claude Code installs on the other machine.
- **Copy My Claude Setup** (Machines tab, `aht copy-setup`): your global `CLAUDE.md`, skills, agents, commands, output styles and plugins go to another machine; hooks, the status line and MCP servers are listed, not copied.
- **Keep in sync and handovers leave less behind on the other machine:** a copy set aside there that the newer file still begins with (a conversation that only grew) is dropped. **Free Up Space…** (Machines tab, `aht remote tidy`) does the same for what earlier versions left; on one machine that freed 19.5 GB.
- **Fix: Keep in sync between a Mac and Linux failed for a project with an emoji in a file name.** Such a project now goes by aht's own copy, and a sync whose files partly fail still sends the conversations.
- **Fix on the Mac:** Restore Workspace resumes sessions in the tabs iTerm2 brought back itself, instead of opening a second window.
- **Fix:** many sessions starting at once (after Restore Workspace) started one backup pass each.
- Claude Code's background sessions (`claude --bg`) are not in the corner: no tab shows them. A tab whose conversation went on in the background shows that conversation's state.

### Before you upgrade

- **Upgrading from a version before 0.14.0?** Read *Before you upgrade* in the [0.14.0 notes](https://github.com/havurgiray/agent-history-tether/releases/tag/v0.14.0) first.
- **Mac: allow the watcher once.** It is a new program, so macOS asks again whether it may see your Desktop and Documents folders. Until you click Allow it waits, and moves are not seen.
- **Backups move into the store by themselves**, a few minutes at a time during the automatic backup; each old ZIP is read back before it goes, and one waits while the disk has less free than twice its size and 1 GB. `aht backup --migrate --apply` moves them all at once.
- The setting `backup_keep` is gone (aht tells you so if you set it); the thinning above replaces it. `backup_interval_hours` is 6 now, and `debounce_seconds` 0.3.
- **Windows:** the corner, Branch, Send and the new watcher were tried on Windows 11 on ARM. The x64 build is built and tested the same way, but not tried on an x64 PC yet: tell us if something is off.

### Privacy policy

- The registry keeps, for each project, the number its folder has on its disk and which disk that is; `run/watch.json` lists that for the watcher.
- Backups are kept as pieces named by their checksum (`objects/`) and snapshot lists (`.snap`), with the new thinning above.
- The session corner (now also on Windows) reads aht's list of the projects handed over; Branch reads the session's command line. New files in `run/`: `transfer-<project>.json` while a handover runs, `claude-installs.json`, `store-size.json`, and on Windows `corner.json` and `corner-place.json`. Copy My Claude Setup reads the names and checksums of your Claude Code setup files here and on the other machine.

### For contributors

- `aht reconcile --quick` (the watchers): no walk; `--look`, `--scan` and `--renamed` name what changed. `WatchJudge` in `aht.py` decides for the Windows and Linux watchers; the Mac watcher does the same in Swift.
- New test units: `02b` (finding by id, the judge), `02c` (the Mac watcher, built from source), `06b` (the backup store), `16i` (set-aside copies); `windows/tests/watch_test.py` runs the Windows watcher for real.
