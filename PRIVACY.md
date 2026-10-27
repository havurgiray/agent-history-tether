# Privacy policy

**agent-history-tether (aht)** · effective 2026-10-27

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
| Codex | `~/.codex/sessions/` (what you asked and Codex answered comes from its events, not from the copies it keeps for the model with its own instructions and your environment around them); from these also, for summaries and catch-ups, the files a patch changed (`apply_patch`) and the open steps of its plan (`update_plan`), never its encrypted reasoning.  When aht writes such a summary or checks a switch, it also reads a copy of `~/.codex/state_5.sqlite` (with its `-wal` and `-shm` files, copied into `~/.aht/run/` and deleted right after; aht opens only the copy), only to count the sessions in that project that Codex keeps there without a session file aht can read |
| Gemini CLI | `~/.gemini/tmp/` |
| Cursor Agent CLI | `~/.cursor/chats/` |
| OpenCode | `$XDG_DATA_HOME/opencode/` |
| GitHub Copilot CLI | `~/.copilot/history-session-state/` |
| Kimi Code | in `~/.kimi-code/` (or `$KIMI_CODE_HOME`): `sessions/`, and for each project its prompt history (`user-history/`), `file-history/`, `workspaces.json` and `session_index.jsonl`; for the older Kimi CLI 1.x, `~/.kimi/sessions/` and `~/.kimi/user-history/` |
| Antigravity (`agy`) | in its data folder (`~/.gemini/antigravity-cli/`): a copy of `conversation_summaries.db`, taken into `~/.aht/run/` (aht opens only the copy) and deleted right after, to find the conversations in your projects; for such a conversation its transcript (what you asked, its replies and its tool calls, never the agent's thinking) and its plan files (`task.md`, `implementation_plan.md`, `walkthrough.md`).  aht also starts the `agy` command when you switch a project to it.  aht never reads `cli.log` (it names the account signed in), `history.jsonl` (the prompts you typed), `implicit/` or `settings.json` |
| Mistral Vibe (`vibe`) | in its data folder (`~/.vibe/`, or `$VIBE_HOME`), only the sessions in `logs/session/unified/`.  For each session: its `meta.json`, of which aht uses the session's id, folder, title, last time and whether a subagent made it (the file also holds your user name and the model's name, which aht does not use), and `CURRENT`, which names the session's latest generation; then that generation's `manifest.json`, its `projection-state.json` and the files in `chunks/` that this names, and the session's journal (`journal/<number>.jsonl`): what you asked, its replies and its tool calls (for the secrets check also their output), never the agent's reasoning.  Of the journal aht takes only the records that change that history: for each other record (such as what was sent to the model) it looks only at the type at the end of the line and passes over it.  aht also starts the `vibe` command when you switch a project to it.  aht never reads `checkpoint.json` (the model's own context), `runtime-state.json`, `scheduled-loops.json`, the sessions an earlier Vibe left (`logs/session/session_*`), or the data folder's other files: `config.toml`, `.env`, `whoami_cache.json`, `vibehistory` (the prompts you typed), `trusted_folders.toml`, its caches (connectors, experiments, managed settings, models) and its logs (`logs/vibe.log`, `logs/vibe-rs.log`) |

These histories can contain anything you or an agent wrote: code, file
contents, command output, and personal information or secrets.  You can
switch agents off (`backends`) or point aht at other folders
(`backend_roots`).

**Also:**

- the folders under the roots it watches (`watch_roots`): their names and
  paths, to notice moves, copies and renames, and their git status for the
  folder badges and `aht loose-ends`;
- for a switch's summary and its catch-up, the project's git state: its
  branch, latest commits and their subjects, how far it is ahead of or
  behind its upstream, and which files are not committed or changed since
  a commit.  aht never fetches, and masks the subjects and file names;
- which agent programs run, for the Sessions tab and before a switch: on
  macOS and Linux, the list of running programs with their command lines
  (`ps`), to find the agents among them, and the folder each agent runs in
  (`lsof` or `/proc`); on Windows, before a switch, the names of the
  running programs (`tasklist`), of which aht keeps only whether Codex,
  Kimi Code, Antigravity or Mistral Vibe is among them;
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
  folder on macOS, `desktop.ini` and `.aht\aht-badge-<8 hex>.ico` on
  Windows, an emblem on Linux.  On Windows the file's name follows the
  picture: a changed badge gets a new file, and the old one (also the
  `.aht\aht-badge.ico` that older versions wrote) is removed;
- only when you use the feature: journals in `.aht/journal/`, the
  project's instruction files with `aht rules --unify --apply`, and files
  put back with `aht undo --apply` or `aht changes --revert --apply`.
  Whatever these replace is set aside in `~/.aht` first;
- only when you hand a project over or switch agents, in `.aht/handover/`:
  a handover's summary, and for each switch and Hand Back a record of who
  handed the work to whom, `relay-<id>.json` (this computer's name, its
  random id from `machine.json` and its system; the project's path and
  identifier; the two agents, their session ids and the session's title,
  masked; when; and the git branch, the latest commit, and how many files
  were not committed and commits not pushed), its summary `relay-<id>.md`
  (exchanges, to-dos, file names, git state and commit subjects, with keys
  masked), and later small markers: `relay-<id>.closed` (what answered it,
  and when) and `relay-<id>.told` (the session told of it, and when).
  Every hand-off still open and the newest 12 others are kept.  Like
  `.aht/journal/`, the folder carries its own `.gitignore`, so git leaves
  it out.  A record that came with the folder all the same (a repository
  that committed one) is read only as aht writes them: a machine's name of
  letters, digits, spaces and `. _ -`, agents aht knows, times as numbers,
  titles masked; nothing else in it reaches a Claude session;
- during a take-back that brings files back, aht briefly makes and removes
  a `.aht-case-…` file in the project folder (and in its Claude Code
  history folder), to learn whether the disk takes `readme.md` and
  `README.md` for one name.

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
  is installed); `aht uninstall --remove-icons` removes the images, and
  that icon cache too when aht's were the last icons there (when others
  remain, it writes the cache again without aht's);
- the `aht` command (macOS and Linux);
- on macOS: Spotlight entries for your session titles (`spotlight`, on by
  default) and Time Machine exclusions for aht's folder copies.

## What aht keeps in its own folder

All of this stays on your computer, in `~/.aht` (Windows:
`%USERPROFILE%\.aht`), readable by your user account.  aht does not
encrypt it.

| What | What it holds | How long it is kept |
|---|---|---|
| `config.json` | your settings, also the machines you added and each one's system (`remotes.<name>.system`) | until you delete it, or `aht uninstall --purge` |
| `machine.json` | a random identifier of this computer (12 hex digits), its name and when the file was made; made the first time aht copies backups to another machine, where it names this computer's folder, or writes a record of a switch into a project (which names this computer by it).  Not in `config.json`, so a copied config does not clone it | until you delete it |
| `offsite.json` | which backups were sent to which machine (`offsite_backup`), when the last copy ran and how much it sent, and from which computer's folder backups were last fetched; it replaces `run/offsite.json`, which older versions wrote and aht removes | rewritten at each copy and fetch |
| `registry.json` (and `.bak`) | the projects aht tracks: an identifier, the folder's path, where each agent keeps that project's history, and when it was last updated; for handovers: which machine a project is on or is being handed to (its name in aht, its host name, its system and its aht's random id), since when, the session handed over and the one that came back, a task you gave it, the files and folders outside the project you take along (`--include`), which projects are kept in sync and with which machine (and, when a release paused that, why, when and for which machine), and how the last take-back or release went (how many files changed, and the names of those kept in both versions); also the identifiers of projects you told aht to forget, with when you did (no paths), so that a scan does not take them on again; where a move you said no to went, so that aht does not ask again; the paths of the git repositories in the watched folders, for the git badge, and when aht last looked; on Linux, which version of aht's emblems the git folders have | until you delete it, or `aht uninstall --purge` |
| `aht.log`, `aht.log.1` | what aht did and when: folder paths, project and session names and the iTerm2 tab titles aht set (as they are, not masked), session identifiers, the names of your other machines (and, when aht reached one by its Tailscale address, that address), the notices it showed (for example "input needed" or "the agent finished after 4 minute(s)"), warnings and errors; no conversations | `aht.log` becomes `aht.log.1` at 5 MB, replacing the older one, so about 10 MB at most |
| `aht-watcher.log` (macOS, Windows), `aht-watcher.err` and `aht-notices.err` (macOS) | the background watcher's and the notices check's own output, including any errors, which can name project folders; on Linux the watcher's goes to your user journal instead (`journalctl --user -u aht-watcher`) | not rotated; delete them any time |
| `backups/` | see [Backups](#backups) | the newest 10 snapshots per project; copies made before a rewrite, until you delete them |
| `search.db` | a search index: the text of messages (up to 4,000 characters each), what each tool call worked on (its command, file path, web address or search, up to 400 characters) and session titles, with what aht recognises as a key, token or password masked whole before any of it is cut (see [Security](#security)), plus agents, project paths and times | until you delete it; it is rebuilt when needed.  An index made by an earlier version of aht is built anew once, at its first update, and nothing of its old rows stays in the file; a session whose history file is gone and that no history backup holds is then no longer in it |
| `checkpoints/` | a copy of a project folder made when a Claude Code session starts (`checkpoints`, on by default), without `.git` and rebuilt folders, so `aht undo` can put it back | the newest 10 per project (`checkpoint_keep`) |
| `workspaces/` | macOS: saved iTerm2 layouts (this computer's name; windows, tab titles and colours, profiles, folders, which agent runs in each pane, session identifiers, each Claude session's name, with keys masked, and the options it was started with that it keeps when it starts again: permission mode or skipping permissions, model, effort, extra folders, `--agent`, `--chrome` or `--no-chrome`, and `--verbose`, never a first prompt; the tab titles are kept as iTerm2 has them, so that restoring a layout sets them back) | the newest 40 (`workspace_keep`) |
| `undo/`, `changes-backups/`, `redacted/`, `rules-backups/` | files aht set aside before replacing them at your request | until you delete them |
| `handover/<project id>/` | for a project handed over: the list of its files and folders on both machines when it left (names, sizes, times, which files are executable, and checksums of its conversation files), and in `replaced/` what a take-back replaced or removed here | the list until the project is back or released, then the newest 5 earlier lists; in `replaced/` the newest 5 folders and every one younger than 30 days |
| `opinions/`, `night-shift.json` | copies of a project for `aht second-opinion`, and planned night shifts | until you discard them |
| `run/` | short-lived state: notices already shown, open sessions, the names aht gave sessions (`tab-names.json`) and the iTerm2 tabs it last saw, with their titles (`iterm-tabs.json`), both as they are, not masked, since aht compares names with tab titles, when setup ran, the last answer about new versions (version number and release notes), backups on their way in while a fetch runs, and for a moment a copy of another program's database aht reads (Codex's `state_5.sqlite`), deleted right after | overwritten as aht runs |
| `run/autostart.json` | that you answered whether aht's tray starts at login: the answer (on or off) and when.  Written only when your answer took effect, that is when the tray then starts at login, or not, as you chose: by `aht autostart on` or `off` (on a Mac the command itself changes nothing, since the app has the switch), the Windows installer's first install, the start-at-login switches in aht's window, the Mac app and the trays, and the welcome, when setting up changes whether aht starts at login or you changed its switch: so a first setup's no counts even when the tray did not start at login anyway (on a Mac too, where *Getting started* then marks the login step optional); the welcome then keeps that answer | rewritten at your next answer |
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
  `rewrites/` are kept until you delete them.  The copies on another
  machine (`offsite_backup`) follow `backup_keep`, keeping at least 3 per
  project; the copies of `rewrites/` there are never removed by aht (see
  [What can leave your device](#what-can-leave-your-device)).
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
minute).  On Windows, the window's folder chooser is Windows' own folder
dialog, which aht shows itself in a second aht process (`aht.exe
_pick-folder`): no PowerShell, no compiled code and no temporary files in
`%TEMP%`.  Nothing is sent anywhere.

## What can leave your device

aht itself never sends anything to the author or to any server the author
runs.  With its default settings it makes no network connections.  The
features below send data, and only after you set them up.

1. **Your other machines** (handover, `aht mirror`, `offsite_backup` and
   fetching backups, `aht night-shift`, and the session list and notices
   for those machines; macOS and Linux).  aht connects over SSH, or mosh if
   both machines have it, to the machines you add with `aht remote add`.
   Before its first command to a new machine, `aht remote add` and `aht
   remote check` ask which system answers there (`echo aht-os %OS%
   $env:OS`); aht cannot ask a Windows PC yet, so for one it stops right
   there and makes nothing on it.  The machine's system is kept in
   `config.json` (`remotes.<name>.system`).  aht sends the project folder,
   its agent history, Claude Code's checkpoints and plans for it and a
   readable handover summary.  The project's `.aht/handover/` (summaries
   and records of who handed the work to whom) goes with a handover, which
   never removes anything from it there; Keep in sync leaves it out.  aht
   also puts a copy of itself there,
   `~/.aht/remote/aht-<checksum>.py`, named after its checksum: the newest
   3 are kept, and the `~/.aht/remote/aht.py` that older versions put there
   is removed.  It installs this computer's version of Claude Code there,
   downloaded from Anthropic.  To learn whether a folder can be written
   there, aht briefly makes and removes a `.aht-write-test-…` file in the
   project folder there, and, when it checks the machine, in the path of
   this computer's home folder there (or in the nearest existing parent of
   either).  When Claude
   Code trusts the project folder here, a handover with
   `handover_carry_trust` (on by default) marks it as trusted in Claude
   Code's `~/.claude.json` there, keeping a copy of that file as
   `~/.claude.json.bak-aht`.  When your home folder's path differs between
   the two machines, aht links `.claude` under this computer's home path
   there to that machine's `~/.claude`, since the history names that path.
   With `handover_remote_control` (on by default for handovers), the
   session on that machine can be reached from the Claude app through
   Claude Code's Remote Control.  Whatever a handover or a sync replaces or removes there
   (also Claude Code's checkpoints and plans) is set aside first, in
   `~/.aht/remote/replaced/` there; for each project the newest 5 of those
   folders and every one younger than 30 days are kept.  To start the
   session there, aht writes a few small files in
   `~/.aht/remote/run/aht-<project name>-<6 characters of its id>/` there:
   the note the session reads first, its settings, the command it runs
   (with your task, if you gave one), and when this handover's session was
   started (so that aht can tell later, should the link drop, whether it
   started).  What a session there waits
   for (the "waiting for" text) is masked before it leaves that machine.
   Copies on those machines stay there until you remove them.

   **Backups there** (`offsite_backup`): copies of the backups go into
   `~/.aht/offsite/<a random id of this computer>/` on that machine, with
   a `machine.json` naming this computer (its id, name and system, and
   when it last copied).  The copies aht made before it rewrote a history
   (`backups/<project id>/rewrites/`) go there too.  aht only adds there,
   and removes a backup there only after this computer pruned it here,
   keeping at least 3 per project; it never removes the copies made
   before a rewrite there.  A folder that an older aht named after this
   computer is taken over only when everything in it (its backups and
   copies made before a rewrite) is here too: they move into this
   computer's folder (one that is there already, with the same size, is
   deleted), and the older folder is removed once nothing is left in it;
   otherwise it stays as it is.  Fetching backups (*Fetch Backups From…*,
   `aht backup --fetch-offsite`) reads the list of folders there (each
   computer's name and system, its last update, how many projects and
   backups, their size) and copies the backups and the copies made before
   a rewrite that are missing here from one of them into this computer's
   backups (`~/.aht/backups`, or `backup_dir`); it never replaces a file
   here.
2. **Notices on your phone** (`notify_phone`, off by default).  Each
   notice's title and text, meaning a project or session name and a short
   status such as "input needed" (what a session waits for, with keys
   masked as under [Security](#security)), go either through Apple's
   Messages app as an iMessage to the address you give, or to the ntfy
   server you name (ntfy.sh unless you give your own URL).  Anyone who knows an ntfy.sh
   topic's name can read it, so choose a name that is hard to guess, or use
   your own server.  The notices about a handover that was cut off (it
   finished, it did not finish, or the other machine has not answered for
   an hour) go there too, and name the project and the machine.
3. **Features that start an AI agent**, all off until you turn them on or
   ask for them: informed sessions, going on in another agent at Claude's
   usage limit, second opinion, night shift, switching agents and handing
   the work back (to Claude Code, Codex, Kimi Code, Antigravity or Mistral
   Vibe), and a handover with a task.  aht hands the agent a summary of
   earlier sessions or a catch-up of what happened since (with keys masked
   as under [Security](#security)), or your task, and the agent sends it to
   its provider under your account, as it does with anything you type into
   it.
   Codex, Kimi Code, Antigravity and Mistral Vibe read it as their first
   turn (aht runs Kimi's itself, `kimi -p`); a Claude Code session handed
   the work back, or switched to as Claude Code's own session, gets its
   catch-up through aht's hook, at most 2,000 characters, once.
   After a switch, the hook also adds one line to the Claude session that
   handed the work on, when you resume it yourself: which agent worked on
   the project since, when, and where the summary is; the catch-up itself
   only with informed sessions on.  These go to Anthropic with your next
   message in that session.
4. **What an agent does with its own files.**  The session names aht
   records become part of the agent's history.  An agent may sync that
   history; Claude Code, for example, shows session names in the Claude app
   through Remote Control.
5. **Files you choose to send.**  `aht share` and `aht journal --write`
   write pages and journals to your disk; they leave your computer only if
   you send them.  A shared page has the keys and passwords aht recognises
   masked (as under [Security](#security)), and its e-mail addresses,
   local network addresses (10/8, 172.16/12, 192.168/16, 100.64/10 as
   Tailscale uses, 169.254/16, and the IPv6 ones in fd00::/8 and
   fe80::/10), your home folder's path and your user and computer names
   removed.  Paths outside your home folder (an external disk, `/opt/…`)
   stay, and masking is best effort, so the page says under its title to
   look it through before you share it.
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
  | `offsite_backup` | which of your machines keeps a copy of the backups (none by default) |
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
   delete them too.  Summaries, records of who handed the work to whom and
   journals stay in your projects' `.aht/handover/` and `.aht/journal/`
   folders until you delete those folders.
3. Remove the app: drag `aht.app` to the Trash or
   `brew uninstall --cask aht` on macOS; on Windows Settings → Apps → aht
   → *Uninstall* (it runs `aht uninstall` first), `winget uninstall
   havurgiray.aht` or `scoop uninstall aht`, and the `%LOCALAPPDATA%\aht`
   folder.
4. If you used other machines: delete `~/.aht` there too (it holds this
   computer's backups in `~/.aht/offsite/<id>/` and the copies of aht in
   `~/.aht/remote/aht-*.py`), any project copies you no longer want, and
   `~/.claude.json.bak-aht` if a handover left one.  Here, deleting
   `~/.aht` also removes `machine.json` and `offsite.json`.

## Security

aht's files are protected only by your user account, like the agents' own
histories.

**What aht masks.**  Wherever aht copies text out of a history, it masks
what it recognises as a key, a token or a password.  This is best effort:
aht works from the forms and names below, and it cannot recognise every
secret (see *Known limits*).

- keys of a known kind: Anthropic, OpenAI, Groq, GitHub, GitLab (`glpat-`,
  `glrt-`, `gldt-`, `glptt-`), AWS access keys, Google API keys and OAuth
  tokens (`ya29.…`), Slack tokens, Stripe live keys, SendGrid, Hugging
  Face, npm and PyPI tokens, age secret keys, Vault (`hvs.`), DigitalOcean
  (`dop_v1_`), Shopify, Docker Hub (`dckr_pat_`), Atlassian (`ATATT3…`)
  and Tailscale keys, JSON web tokens, the secret part of a Slack webhook
  address, and the token in a Telegram bot address
  (`api.telegram.org/bot…`);
- private keys: PEM (also encrypted, with `Proc-Type` and `DEK-Info`
  lines), PGP private-key blocks and PuTTY `.ppk` files, also inside JSON
  (and JSON inside JSON), in a Read tool's output with line numbers, or
  with `>`, `#` or `//` before each line.  A key is masked from its BEGIN
  line to its END line, and nothing after it; a guide or code that names
  the BEGIN and END lines with no key between them (32 characters of key
  or more) stays as it is.  A key cut off before its END line is masked to
  the end of the text that holds it.  A private key in base64 (a
  kubeconfig's `client-key-data`, a Kubernetes `tls.key`, the output of
  `base64`, also in lines of 76) is masked too;
- `Bearer` tokens (16 characters or more), `Basic` credentials, and what
  follows `Authorization:` with any other scheme or none (16 characters or
  more);
- the value given to a name that holds a password, a secret, a token or a
  key: a name with a word (its words are split at `_`, `.`, `-` and at
  capitals: `dbPassword`, `SecretAccessKey`) that ends in password,
  passwd, passphrase, pwd, secret, token or credential(s) (`PGPASSWORD`,
  `GITHUB_TOKEN`, `clientSecret`), that is pass, auth or pat, or that is
  key after api, access, private, secret, client, app, master,
  encryption, signing, hmac, jwt, account or shared (`API_KEY`, `apiKey`,
  `SECRETKEY`, `RAILS_MASTER_KEY`, `x-api-key`).  This also holds in a
  `.env` file, an `export` line, YAML or JSON, on any line of a tool's
  output and in JSON inside JSON.  A name does not count when a word after
  that one says it holds something else, such as an id, a URL, a host, a
  name, a type, a hash, a count, a length, a path, a file, a digest, a
  fingerprint, a version or a scope (`TOKEN_URL`, `password_hash`,
  `token_type`, `accessTokenUrl`, `token_sha256`), when a word before it
  says it is a page's or a request's token (`NextToken`, `nextPageToken`,
  `ContinuationToken`, `IdempotencyToken`), when it stands before `::`
  (`test_auth.py::test_token`, `auth::verify`), or when it is a style
  sheet's class (`.x-token:hover`).  The value must have 8 or more
  characters and look generated: not a placeholder or a reference to a
  secret store (`${DB_PASSWORD}`, `<token>`, `changeme`, `%{X}`, `op://…`,
  `vault:…`), not code (a call, an index or a chain of names:
  `tokenizer.encode(text)`, `req.body.password`), not a name made of words
  (`MAX_RETRIES`, `refreshToken`, `my-app-secrets`), a version or an
  image's tag, not a path or a web address with no generated part, and
  not words of a language other than English.  A value of 16 characters or
  fewer counts when it mixes three kinds of character (small letters,
  capitals, digits, other signs); a longer one when it is random enough.
  A value in quotes ends at the same quote, a space or a backslash; one
  without quotes at a space, a quote, a backslash, `,`, `;`, `<`, `>`, a
  backtick or `=` (base64's `=` at its end stays with it), and at an `&`
  before another parameter (`&page=2`);
- where no name stands before the value: `--password`, `--token`,
  `--secret`, `--with-token`, `--auth-token`, `--access-token` and
  `--api-key` (also `--pass` and `--passwd`) followed by a value;
  `mysql -pX` (also `mysqldump`, `mysqladmin`, `mariadb`); `-p` or
  `--password` after `docker login` or `twine`; `sshpass -p`;
  `redis-cli -a`; the password in `curl -u user:password`; XML
  `<password>…</password>` (also `pass`, `passwd`, `secret`, `token`);
  and settings written `key="…Password" value="…"` (also a name that ends
  in Secret, Token or Key).  The value must look generated, as above;
- the password in a web or database address (`postgres://app:…@db:5432`),
  whatever the host (a name, a container's name, an IPv4 or `[IPv6]`
  address), with or without a user name, also when percent-encoded or
  when it holds an `@`, and in Go's form (`user:…@tcp(host:3306)/db`),
  unless it is too plain (`postgres:postgres`) or a placeholder.  The rest
  of the address stays readable.

It masks each find whole, however long (up to 64 KB), and it masks before
it shortens a text, so a cut never leaves part of one.  A masked value
keeps its kind and at most its first four and last two characters
(`[Groq API key: gsk_…o8]`); a private key keeps only what kind it is
(`BEGIN RSA PRIVATE KEY`, or `BEGIN RSA PRIVATE KEY (in base64)`).

**Known limits.**  aht cannot recognise every secret, and it does not
try to guess at every shape one could have.  These stay in clear: a value
with no name and no form aht knows (a token of no known kind pasted alone
into a message); a value after a name it does not know (`STRIPE_KEY`,
`stripeKey`); a value under 8 characters, or one that does not look
generated (small letters only, a word and digits such as `Summer2024`, a
short one of only two kinds of character, words joined by `-` as a
passphrase generator makes them); a password with a quote, a space or a
backslash in it, which is masked only up to that character, and not at
all when fewer than 8 characters come before it (a value without quotes
likewise ends at `,`, `;` or `=`); a password that starts with a bracket, `=` or `:`,
or with a word and a bracket (`Word(…`), which reads as code; a value
that is a path or a file's name; in `aht secrets`, a value on the line
after its name (what aht shows masks it); a cookie; a private key seen
only from its middle (its end, a part a Read tool showed from an offset
or a diff showed), or as the lines a diff removes; a password in a base64
Docker config (`.dockerconfigjson`); a web address with a password,
percent-encoded inside another web address; and a secret split across
lines or messages.  Some code and names that look generated may be masked
although they are none.  Secrets are best kept out of agent chats.
`aht secrets` lists what aht recognises in the histories, and
`aht secrets --redact` takes it out (a private key from its BEGIN line to
its END line, and nothing around it); a place whose removal would leave a
history's line, or the whole file, no longer valid JSON is left as it is,
and aht says so.  So is a find in a Mistral Vibe session: Vibe checks every
record of a session's store, and would no longer open one with a byte
changed.

**Where.**  The search index (messages; what tool calls worked on: their
commands, file paths and web addresses; session titles), handover, switch
and hand-back summaries (also the commit subjects and file names in them),
the records of who handed the work to whom (session titles), the notes
aht's hook adds about them, `aht relays --show`, journals, notices (also those sent to your phone) and
what a session waits for (masked before it leaves another machine),
shared session pages (also the tools they list), Tidy Up's preview of a
history, What Changed, the notes for informed sessions, loose ends and
second opinions, `aht limits` (the usage-limit text), and session titles
and names, tab titles and names waiting for a session's next prompt
wherever aht lists them or sends them on: the session board (also what
other machines receive, and other machines' boards), Show Sessions and
Spotlight, reports, loose ends, a handover's dry run and result, Take
Back, What Changed, `aht undo --list`, `aht checkup` (also the plan of
`--restart`), `aht tab-names` (its list, `--json` and its sync plan), and
the session names in saved workspaces.

On this computer only, session names and tab titles stay as they are: in
the Mac app's session corner, in the iTerm2 tab titles aht sets from a
session's name, in `run/tab-names.json` and `run/iterm-tabs.json`, in the
tab titles of saved workspaces (restoring a layout sets them back), and in
`aht.log`.

Backups and checkpoints, though, are exact copies and contain whatever
the originals contain.  Disk encryption (FileVault, BitLocker, LUKS)
protects them if your computer is lost.

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
