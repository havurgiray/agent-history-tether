# Privacy policy

**agent-history-tether (aht)** · effective 2026-10-23

This policy applies to every version of aht on macOS, Windows and Linux,
however it was installed: from source, from the release downloads, or
through Homebrew, Scoop or winget.  Some features below exist only in
newer versions or only on macOS; each one says so where it matters.

## In short

- **aht runs on your computer.**  It has no servers, no accounts, no
  telemetry, no analytics, no crash reports, no ads and no update checks.
  The author never receives any of your data.
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
  aht's hooks;
- on macOS with iTerm2: window and tab titles, tab colours and profiles,
  for session names and saved workspaces;
- only when you run `aht remote discover`: your `~/.ssh/config` and the
  list of your machines from Tailscale.

## What aht changes

**In the agents' histories:**

- **Relinking.**  When a project folder moves or is renamed, aht renames
  that project's history folder to match (Claude Code, Gemini, Cursor,
  OpenCode, Kimi) or rewrites the project path recorded inside its session
  files (Codex, Copilot).  By default it asks you first (`move_policy`,
  `copy_policy`).  Every file it rewrites is copied into its backups first.
  aht never deletes a history on its own; one whose folder is gone goes to
  the Trash only when you ask.
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

- aht's hooks in Claude Code's `~/.claude/settings.json`;
- starting at login: LaunchAgents in `~/Library/LaunchAgents` (macOS); an
  entry under `HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run`
  plus a copy of `aht.exe`, a one-line launcher script and an icon cache in
  `%LOCALAPPDATA%\aht` (Windows); a systemd user unit or an autostart entry
  in `~/.config` (Linux);
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
| `registry.json` (and `.bak`) | the projects aht tracks: an identifier, the folder's path, where each agent keeps that project's history, when it was last updated, and which machine a handed-over project is on | until you delete it, or `aht uninstall --purge` |
| `aht.log`, `aht.log.1` | what aht did and when: folder paths, project and session names, session identifiers, the notices it showed (for example "input needed" or "the agent finished after 4 minute(s)"), warnings and errors; no conversations | `aht.log` becomes `aht.log.1` at 5 MB, replacing the older one, so about 10 MB at most |
| `aht-watcher.log` | the background watcher's own output | not rotated; delete it any time |
| `backups/` | see [Backups](#backups) | the newest 10 snapshots per project; copies made before a rewrite, until you delete them |
| `search.db` | a search index: the text of messages (up to 4,000 characters each) with anything that looks like a key, token or password masked, plus session titles, agents, project paths and times | until you delete it; it is rebuilt when needed |
| `checkpoints/` | a copy of a project folder made when a Claude Code session starts (`checkpoints`, on by default), without `.git` and rebuilt folders, so `aht undo` can put it back | the newest 10 per project (`checkpoint_keep`) |
| `workspaces/` | macOS: saved iTerm2 layouts (windows, tab titles and colours, profiles, folders, session identifiers) | the newest 40 (`workspace_keep`) |
| `undo/`, `changes-backups/`, `redacted/`, `rules-backups/`, `handover/` | files aht set aside before replacing them at your request, and records of handovers | until you delete them |
| `opinions/`, `night-shift.json` | copies of a project for `aht second-opinion`, and planned night shifts | until you discard them |
| `run/` | short-lived state: notices already shown, open sessions, tab names | overwritten as aht runs |

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
   Claude Code there, downloaded from Anthropic.  With
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

These services are run by others, under their own terms and privacy
policies: Anthropic and the other agent providers, Apple, ntfy, Tailscale,
and whoever runs the machines you hand projects to.  The author has no
access to them and no control over them.

## Your controls

- **Settings.**  Everything below is set with `aht config --set key=value`,
  or in the macOS app's Settings:

  | Setting | What it controls |
  |---|---|
  | `move_policy`, `copy_policy`, `new_policy` | whether aht asks before relinking (moves and copies: asks by default) |
  | `backup_enabled`, `backup_interval_hours`, `backup_keep`, `backup_dir` | whether, how often, how many and where backups are kept |
  | `checkpoints`, `checkpoint_keep`, `checkpoint_excludes` | folder copies at session start |
  | `icons_enabled` | folder badges |
  | `tab_names`, `spotlight`, `workspace_keep` | session names from iTerm2 tabs, Spotlight entries, saved layouts (macOS) |
  | `notifications`, `notify_phone` | notices on this computer and on your phone |
  | `backends`, `watch_roots` | which agents and folders aht looks at |
  | `log_level` | how much aht writes to its log |

  The features that start an agent are off by default; the README's
  *What uses tokens* table lists them.
- **Pause.**  Every tray has *Pause Watching*.
- **Look.**  `aht projects`, `aht backup --list`, `aht logs` and
  `aht secrets` show what aht tracks, keeps and has found.

## Deleting your data

1. `aht uninstall` stops the watcher and removes aht's hooks and its
   start-at-login entries.  `--remove-icons` also clears the folder badges
   (on Linux, use the tray's *Clear all emblems*); `--purge` also removes
   the `.aht/.project-id` markers, the registry and the config.  It never
   touches the agents' histories.
2. Delete the `~/.aht` folder (Windows: `%USERPROFILE%\.aht`) to remove the
   backups, logs, search index, checkpoints and everything else aht kept,
   and the folder you set in `backup_dir`, if any.
3. Remove the app: drag `aht.app` to the Trash or
   `brew uninstall --cask aht` on macOS; on Windows `winget uninstall
   havurgiray.aht` or `scoop uninstall aht`, and the `%LOCALAPPDATA%\aht`
   folder.
4. If you used other machines: delete `~/.aht` there too, and any project
   copies you no longer want.

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
