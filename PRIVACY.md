# Privacy policy

**agent-history-tether (aht)** · effective 2026-10-26

This policy applies to every version of aht on macOS, Windows and Linux,
however it was installed: from source, from the release downloads, or
through Homebrew, Scoop or winget.  Some features below exist only in
newer versions or only on macOS; each one says so where it matters.

## In short

- **aht runs on your computer.**  It has no servers, no accounts, no
  telemetry, no analytics, no crash reports and no ads, and it looks for
  new versions only if you turn that on.  The author never receives any of
  your data.
- **With its default settings, aht makes no network connections.**  It
  sends data only through features you set up yourself (see
  [What can leave your device](#what-can-leave-your-device)), and only to
  the machines and services you choose.  Version 0.9.0, the first version
  submitted to winget, contains no networking code at all.
- **aht reads your AI coding agents' conversation histories** on your
  computer.  It changes them to keep them linked to your project folders
  and, on macOS, to record session names; anything else only when you
  ask.  Before it rewrites a history file, it copies it into its backups.
- **Its own files live in `~/.aht`** (on Windows `%USERPROFILE%\.aht`):
  settings, the list of projects it tracks, logs, backups of the histories
  and a search index.  Uninstalling leaves the backups and logs there;
  deleting that folder removes them (see [Deleting your data](#deleting-your-data)).

## Who is responsible for your data

aht is free software written by Giray Havur and published under the GNU
Affero General Public License, version 3 or later.  The author does not
run a service, and does not collect, receive, store, sell or share any
data from the people who use aht.  Everything below happens on your own
computer, or on machines and services you set up, and stays under your
control.

## What aht reads

**The agents' conversation histories**, where each agent keeps them (the
paths are for macOS and Linux; on Windows they are the matching folders in
your user profile):

| Agent | Where |
|---|---|
| Claude Code | `~/.claude/projects/`, and `~/.claude/sessions/` for which sessions are open and what they are doing |
| Codex | `~/.codex/sessions/` |
| Gemini CLI | `~/.gemini/tmp/` |
| Cursor Agent CLI | `~/.cursor/chats/` |
| OpenCode | `$XDG_DATA_HOME/opencode/` |
| GitHub Copilot CLI | `~/.copilot/history-session-state/` |
| Kimi Code | `~/.kimi/sessions/` and `~/.kimi/user-history/` |

These histories can contain anything you or an agent wrote: code, file
contents, command output, and personal information or secrets.  You can
switch agents off (`backends`) or point aht at other folders
(`backend_roots`).

**Also:**

- the folders under the roots it watches (`watch_roots`): their names and
  paths, to notice moves, copies and renames, and their git status for the
  folder badges and `aht loose-ends`;
- Claude Code's settings file `~/.claude/settings.json`, to add and remove
  aht's hooks, and to show whether Remote Control and going on after the
  usage limit are on;
- during a handover: whether Claude Code trusts the project folder, from
  its `~/.claude.json`;
- on macOS with iTerm2: window and tab titles, tab colours and profiles,
  for session names and saved workspaces, and three of iTerm2's settings
  (whether its Python API and its new-output indicator are on, and whether
  it keeps window state) for *Getting started*.  aht never changes
  iTerm2's settings;
- to list machines you could add, only when you run `aht remote discover`,
  or open the Machines tab in the Mac app (or press *Look Again* there):
  your `~/.ssh/config` and the list of your machines from Tailscale.  The
  Mac app keeps the last answer while it runs;
- to reach a machine you added: its ssh settings (`ssh -G`, which reads
  your `~/.ssh/config`, as ssh itself does each time aht connects), and,
  when that machine's name does not resolve, its address from Tailscale's
  list of your machines.  This happens whenever aht connects to it, for
  example to check it, hand a project over or show its sessions.  Nothing
  of either is sent.  aht's log (`aht.log`) records the machine's name and,
  when aht reached it by its Tailscale address, that address; both stay on
  this computer.

## What aht changes

**In the agents' histories:**

- **Relinking.**  When a project folder moves or is renamed, aht renames
  that project's history folder to match (Claude Code, Gemini, Cursor,
  OpenCode, Kimi) or rewrites the project path recorded inside its session
  files (Codex, Copilot).  By default it asks you first (`move_policy`,
  `copy_policy`).  Every file it rewrites is copied into its backups first.
  aht never deletes a history on its own; one whose folder is gone goes to
  the Trash only when you ask (`aht tidy --remove-history`): Finder's Trash
  on macOS, the Recycle Bin on Windows, and on Linux the desktop's Trash in
  `~/.local/share/Trash` (through `gio trash` when it is installed), whose
  `info/<name>.trashinfo` records the history's original path and when it
  was moved there.  It can be restored from there.  On Windows aht only
  moves a history to the Recycle Bin: when it cannot go there (the drive
  has no Recycle Bin, that drive's bin is set to remove files at once, or
  the history is bigger than that bin holds), aht changes nothing and says
  why.  To tell, it reads that drive's Recycle Bin settings and the policy
  *Do not move deleted files to the Recycle Bin* from the registry, and
  the drive's size.  Afterwards it counts the items in that bin and reads
  the bin's own records of where its new items came from, to see that the
  history arrived; should Windows have deleted it for good, aht says so.
- **Session names** (Claude Code on macOS; `tab_names`, on by default):
  aht records the session's name, the title of its iTerm2 tab, in the
  session's history, as Claude Code's `/rename` does.
- **Only when you ask:** restoring a backup (adds missing files, never
  overwrites), taking a found secret out of the histories
  (`aht secrets --redact`, copies kept first), and relinking a history to
  another folder (`aht tidy --relink`).

**In your project folders:**

- `.aht/.project-id`, a random identifier that lets aht recognise the
  folder after it moves;
- folder badges (`icons_enabled`): a custom folder icon stored inside the
  folder on macOS, `desktop.ini` and `.aht\aht-badge.ico` on Windows, an
  emblem on Linux;
- only when you use the feature: handover summaries in `.aht/handover/`
  and journals in `.aht/journal/` (both carry their own `.gitignore`), the
  project's instruction files with `aht rules --unify --apply`, and files
  put back with `aht undo --apply` or `aht changes --revert --apply`.
  Whatever these replace is set aside in `~/.aht` first.

**Elsewhere on your computer:**

- aht's hooks in Claude Code's `~/.claude/settings.json`, and Claude Code's
  own setting for going on after the usage limit when you switch it in aht.
  Before it changes that file, aht copies it to `settings.json.bak-aht`
  next to it (`settings.json.bak-aht-uninstall` when the Mac or Linux
  uninstaller removes the hooks); the copies stay until you delete them;
- starting at login: LaunchAgents in `~/Library/LaunchAgents` (macOS); an
  entry under `HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run`
  (Windows); a systemd user unit or an autostart entry in `~/.config`
  (Linux);
- on Windows, the program itself: in `%LOCALAPPDATA%\Programs\aht` with a
  Start menu entry and an entry under Settings → Apps when the installer
  put it there, or in `%LOCALAPPDATA%\aht` when `aht install` copied it from
  the zip; an icon cache for the badges in `%LOCALAPPDATA%\aht\icons`
  (aht removes the files an older version cached there); and that folder
  on your user `PATH` unless a package manager already put `aht` there;
- on Linux, the emblem images for the folder badges in
  `~/.local/share/icons/hicolor` (`24x24/emblems` and `48x48/emblems`, with
  a stamp file, and that folder's icon cache when `gtk-update-icon-cache`
  is installed); `aht uninstall --remove-icons` removes the images;
- the `aht` command (macOS and Linux);
- on macOS: Spotlight entries for your session titles (`spotlight`, on by
  default) and Time Machine exclusions for aht's folder copies.

## What aht keeps in its own folder

All of this stays on your computer, in `~/.aht` (Windows:
`%USERPROFILE%\.aht`), readable by your user account.  aht does not
encrypt it.

| What | What it holds | How long it is kept |
|---|---|---|
| `config.json` | your settings | until you delete it, or `aht uninstall --purge` |
| `registry.json` (and `.bak`) | the projects aht tracks: an identifier, the folder's path, where each agent keeps that project's history, when it was last updated, and which machine a handed-over project is on; also the identifiers of projects you told aht to forget, with when you did (no paths), so that a scan does not take them on again; where a move you said no to went, so that aht does not ask again; the paths of the git repositories in the watched folders, for the git badge, and when aht last looked; on Linux, which version of aht's emblems the git folders have | until you delete it, or `aht uninstall --purge` |
| `aht.log`, `aht.log.1` | what aht did and when: folder paths, project and session names, session identifiers, the names of your other machines (and, when aht reached one by its Tailscale address, that address), the notices it showed (for example "input needed" or "the agent finished after 4 minute(s)"), warnings and errors; no conversations | `aht.log` becomes `aht.log.1` at 5 MB, replacing the older one, so about 10 MB at most |
| `aht-watcher.log` (macOS, Windows), `aht-watcher.err` and `aht-notices.err` (macOS) | the background watcher's and the notices check's own output, including any errors, which can name project folders; on Linux the watcher's goes to your user journal instead (`journalctl --user -u aht-watcher`) | not rotated; delete them any time |
| `backups/` | see [Backups](#backups) | the newest 10 snapshots per project; copies made before a rewrite, until you delete them |
| `search.db` | a search index: the text of messages (up to 4,000 characters each) with anything that looks like a key, token or password masked, plus session titles, agents, project paths and times | until you delete it; it is rebuilt when needed |
| `checkpoints/` | a copy of a project folder made when a Claude Code session starts (`checkpoints`, on by default), without `.git` and rebuilt folders, so `aht undo` can put it back | the newest 10 per project (`checkpoint_keep`) |
| `workspaces/` | macOS: saved iTerm2 layouts (windows, tab titles and colours, profiles, folders, session identifiers) | the newest 40 (`workspace_keep`) |
| `undo/`, `changes-backups/`, `redacted/`, `rules-backups/`, `handover/` | files aht set aside before replacing them at your request, and records of handovers | until you delete them |
| `opinions/`, `night-shift.json` | copies of a project for `aht second-opinion`, and planned night shifts | until you discard them |
| `run/` | short-lived state: notices already shown, open sessions, tab names, when setup ran, the last answer about new versions (version number and release notes) | overwritten as aht runs |
| `run/autostart.json` | that you answered whether aht's tray starts at login: the answer (on or off) and when.  Written only when your answer took effect, that is when the tray then starts at login, or not, as you chose: by `aht autostart on` or `off` (on a Mac the command itself changes nothing, since the app has the switch), the Windows installer's first install, the start-at-login switches in aht's window, the Mac app and the trays, and the welcome when setting up changes whether aht starts at login (a first setup that turns it on counts); the welcome then keeps that answer | rewritten at your next answer |
| `run/window.json` | Windows and Linux: the process id and port of aht's window server, and the key a second `aht window` uses to reach it | removed when the server stops (on Linux also when it is stopped at logout) |
| `run/window-<id>.json` | Windows and Linux: the progress of a handover or a take-back started in aht's window | deleted when the job ends; one left behind is removed after 6 hours, the next time the window starts |
| `run/aht-setup-<version>-windows-<arch>.exe` | Windows, installed with aht's installer: the installer *Upgrade* downloaded | the latest only: earlier ones are deleted before the next upgrade downloads a new one |
| `run/tray-check.json` | Linux: whether the tray can run here (`tray.py --check` passed or not), with the tray's path and modification time, the Python that runs it, and when it was checked | rewritten when one of those changes; a "no" is checked again after a minute |
| `aht-icons/` | Linux: the tray's two icons, written by the tray and by `tray.py --check` | rewritten each time the tray starts or is checked |
| `tools/agent-history-tether/` | macOS and Linux: aht's own program files (the core, the watcher, the installers, the guide and that system's helpers: the badge tool on macOS, the tray and aht's window on Linux) | until you delete it; on Linux `aht uninstall --purge` removes it |

### Backups

- **Contents.**  One ZIP file per project per snapshot, holding copies of
  that project's history files from every agent aht watches: the complete
  conversations, as the agents store them, including anything sensitive
  they contain.  A small `.meta.json` file next to each ZIP lists what is
  inside.  Files aht is about to rewrite while relinking are copied to
  `rewrites/` in the same folder.
- **Location.**  `~/.aht/backups/<project identifier>/`, or the folder you
  set in `backup_dir`.
- **When.**  At most once every 24 hours (`backup_interval_hours`), and
  only when the project's histories changed since the last snapshot.
- **Retention.**  The newest 10 snapshots per project are kept
  (`backup_keep`); older ones are deleted automatically.  The copies in
  `rewrites/` are kept until you delete them.
- **After uninstalling.**  Backups stay until you delete them, so that
  removing aht never costs you a history.  `backup_enabled = false` stops
  new backups.

**aht's window on Windows and Linux** is a page that aht serves to your
own browser from a small web server at `127.0.0.1`, which nothing outside
your computer can reach.  It serves only its own page and guide, from the
folder aht is installed in (never from the folder it was started in), and
loads nothing from the internet.  It opens only through the tray or
`aht window`, with a code that works once.  That code gives the page a
cookie and a key of its own; the key comes after `#` in the address, a part
no server ever receives, and the page keeps it in the browser's session
storage so that a reload works.  A second window in the same browser uses
the same cookie and key; a browser without a cookie aht knows gets new
ones.  Every request that runs a command or reads anything through the
window (the guide, a job's progress) needs both; the page's own files (its
HTML, script and style sheet) need only the cookie.  So other servers on
`127.0.0.1`, which receive the cookie too, can neither run anything nor
read anything but those files.  On Linux the server also refuses
connections made by another account of this computer.  Windows has no such
check; there, an account without administrator rights cannot read another
account's command lines, where the launch code appears.  The server stops
15 minutes after its last window closed (an open window asks it once a
minute).  On Windows, the window's folder chooser is a few lines of C# that
PowerShell compiles each time the chooser opens; PowerShell writes
temporary files for that in `%TEMP%` and removes them.  Nothing is sent
anywhere.

## What can leave your device

aht itself never sends anything to the author or to any server the author
runs.  With its default settings it makes no network connections.  The
features below send data, and only after you set them up.

1. **Your other machines** (handover, `aht mirror`, `offsite_backup`,
   `aht night-shift`, and the session list and notices for those machines;
   macOS and Linux).  aht connects over SSH, or mosh if both machines have
   it, to the machines you add with `aht remote add`.  It sends the project
   folder, its agent history, Claude Code's checkpoints for it and a
   readable handover summary; with `offsite_backup`, copies of the backups
   go to `~/.aht/offsite/` on that machine.  aht also puts a copy of itself
   in `~/.aht/remote/` there, and installs this computer's version of
   Claude Code there, downloaded from Anthropic.  When Claude Code trusts
   the project folder here, a handover with `handover_carry_trust` (on by
   default) marks it as trusted in Claude Code's `~/.claude.json` there,
   keeping a copy of that file as `~/.claude.json.bak-aht`.  When your home
   folder's path differs between the two machines, aht links `.claude`
   under this computer's home path there to that machine's `~/.claude`,
   since the history names that path.  With
   `handover_remote_control` (on by default for handovers), the session on
   that machine can be reached from the Claude app through Claude Code's
   Remote Control.  Copies on those machines stay there until you remove
   them.
2. **Notices on your phone** (`notify_phone`, off by default).  Each
   notice's title and text, meaning a project or session name and a short
   status such as "input needed", go either through Apple's Messages app as
   an iMessage to the address you give, or to the ntfy server you name
   (ntfy.sh unless you give your own URL).  Anyone who knows an ntfy.sh
   topic's name can read it, so choose a name that is hard to guess, or use
   your own server.
3. **Features that start an AI agent**, all off until you turn them on or
   ask for them: informed sessions, going on in another agent at Claude's
   usage limit, second opinion, night shift, switching agents, and a
   handover with a task.  aht hands the agent a summary of earlier sessions
   (with keys masked) or your task, and the agent sends it to its provider
   under your account, as it does with anything you type into it.
4. **What an agent does with its own files.**  The session names aht
   records become part of the agent's history.  An agent may sync that
   history; Claude Code, for example, shows session names in the Claude app
   through Remote Control.
5. **Files you choose to send.**  `aht share` and `aht journal --write`
   write pages and journals to your disk; they leave your computer only if
   you send them.
6. **Looking for new versions** (`update_check`, off by default; also once
   each time you press *Check Now* or run `aht update --now`).  Once a day
   aht asks GitHub's public API (`api.github.com`) which release of aht is
   the latest.  GitHub receives your computer's IP address, the time, and
   the text `aht/<version>` naming the version you run; aht sends nothing
   else and uses no account.  *Upgrade* then runs your package manager
   (Homebrew or Scoop), which downloads the new version from GitHub.
   Installed with aht's Windows installer (or winget), *Upgrade* downloads
   the new installer and the release's checksum file from GitHub
   (`github.com`, which sees the same as above), checks the one against the
   other and runs the installer; only the latest download is kept in
   `~/.aht/run`.  A downloaded copy and a checkout (every Linux install)
   open the release page in your browser instead; aht opens only `https`
   addresses.

These services are run by others, under their own terms and privacy
policies: Anthropic and the other agent providers, Apple, ntfy, Tailscale,
GitHub and the package managers, and whoever runs the machines you hand
projects to.  The author has no
access to them and no control over them.

## Your controls

- **Settings.**  Everything below is set with `aht config --set key=value`,
  or in the Settings of the Mac app or of aht's window:

  | Setting | What it controls |
  |---|---|
  | `move_policy`, `copy_policy` | whether aht asks before relinking (moves and copies: asks by default) |
  | `backup_enabled`, `backup_interval_hours`, `backup_keep`, `backup_dir` | whether, how often, how many and where backups are kept |
  | `checkpoints`, `checkpoint_keep`, `checkpoint_excludes` | folder copies at session start |
  | `icons_enabled` | folder badges |
  | `tab_names`, `spotlight`, `workspace_keep` | session names from iTerm2 tabs, Spotlight entries, saved layouts (macOS) |
  | `handover_carry_trust` | whether a handover marks the folder as trusted in Claude Code on the other machine (on by default) |
  | `notifications`, `notify_phone` | notices on this computer and on your phone |
  | `backends`, `watch_roots` | which agents and folders aht looks at |
  | `log_level` | how much aht writes to its log |
  | `update_check` | whether aht asks GitHub once a day for the latest version (off by default) |

  The features that start an agent are off by default; the README's
  *What uses tokens* table lists them.
- **Pause.**  Every tray has *Pause Watching*.
- **Look.**  `aht projects`, `aht backup --list`, `aht logs` and
  `aht secrets` show what aht tracks, keeps and has found.

## Deleting your data

1. `aht uninstall` stops the watcher and removes aht's hooks, its
   start-at-login entries and, on Windows, the PATH entry aht added.
   `--remove-icons` also clears the folder badges (on Linux also the emblem
   images aht drew); `--purge` also removes the `.aht/.project-id` markers,
   the registry and the config.  It never touches the agents' histories.
2. Delete the `~/.aht` folder (Windows: `%USERPROFILE%\.aht`) to remove the
   backups, logs, search index, checkpoints and everything else aht kept,
   and the folder you set in `backup_dir`, if any.  The copies of Claude
   Code's settings file that aht kept lie next to it:
   `~/.claude/settings.json.bak-aht` and `settings.json.bak-aht-uninstall`;
   delete them too.
3. Remove the app: drag `aht.app` to the Trash or
   `brew uninstall --cask aht` on macOS; on Windows Settings → Apps → aht
   → *Uninstall* (it runs `aht uninstall` first), `winget uninstall
   havurgiray.aht` or `scoop uninstall aht`, and the `%LOCALAPPDATA%\aht`
   folder.
4. If you used other machines: delete `~/.aht` there too, any project
   copies you no longer want, and `~/.claude.json.bak-aht` if a handover
   left one.

## Security

aht's files are protected only by your user account, like the agents' own
histories.  aht masks keys, tokens and passwords in the search index,
journals and summaries it writes, but backups and checkpoints are exact
copies and contain whatever the originals contain.  Disk encryption
(FileVault, BitLocker, LUKS) protects them if your computer is lost.

## No warranty

aht is provided "as is", without warranty of any kind, under the terms of
its [license](LICENSE) (see its sections 15 and 16).  Keep your own
backups of anything important.  This policy describes what the software
does; it does not change the license.

## Changes to this policy

Changes are made in this file, and its history in the repository keeps
every earlier version.  Releases that change what aht reads, keeps or
sends say so in their release notes.

## Contact

Questions about this policy: open an issue at
<https://github.com/havurgiray/agent-history-tether/issues>.  Please do not
put histories, keys or other personal data in an issue.
