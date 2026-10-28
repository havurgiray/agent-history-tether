# Privacy policy

**agent-history-tether (aht)** · effective 2026-10-28

This policy applies to every version of aht on macOS, Windows and Linux,
however it was installed: from source, from the release downloads, or
through Homebrew, Scoop or winget.  Some features below exist only in
newer versions or only on some systems; each one says so where it
matters.

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
  and to name Claude Code sessions; anything else only when you ask.  Before it rewrites a history file, it copies it into its backups.
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

### The agents' histories

Each agent keeps them in its own folder (the paths are for macOS and
Linux; on Windows they are the matching folders in your user profile):

| Agent | What aht reads | What aht does not read or use |
|---|---|---|
| Claude Code | `~/.claude/projects/` (the conversations), `~/.claude/sessions/` (which sessions are open and what they are doing), and for a handover, a sync or a Bring Here the project's plans (`~/.claude/plans/`) and /rewind snapshots (`~/.claude/file-history/`) | |
| Codex | `~/.codex/sessions/`: what you asked and Codex answered, from its events; its tool calls (their names and arguments), from which summaries also take the files a patch changed (`apply_patch`) and the open steps of its plan (`update_plan`).  When aht writes a summary or checks a switch, also a copy of `~/.codex/state_5.sqlite` (with its `-wal` and `-shm` files, copied into `~/.aht/run/` and deleted right after; aht opens only the copy), only to count the project's sessions that Codex keeps there without a session file | the copies of the conversation Codex keeps as the model's input and output, among its own instructions and your environment, and its encrypted reasoning (except for the secrets check, below) |
| Gemini CLI | `~/.gemini/tmp/` | |
| Cursor Agent CLI | `~/.cursor/chats/` | |
| OpenCode | `$XDG_DATA_HOME/opencode/project/` | |
| GitHub Copilot CLI | `~/.copilot/history-session-state/` | |
| Kimi Code | in `~/.kimi-code/` (or `$KIMI_CODE_HOME`): `sessions/` (with each session's `state.json`), and for each project its prompt history (`user-history/`), `file-history/`, `workspaces.json` and `session_index.jsonl`; for the older Kimi CLI 1.x, `~/.kimi/sessions/` and `~/.kimi/user-history/` | `workspace-trust/` |
| Antigravity (`agy`) | in `~/.gemini/antigravity-cli/`: a copy of `conversation_summaries.db`, taken into `~/.aht/run/` (aht opens only the copy) and deleted right after, to find the conversations in your projects; for those, the transcript (what you asked, its replies and its tool calls) and the plan files (`task.md`, `implementation_plan.md`, `walkthrough.md`) | the agent's thinking (except for the secrets check, below); `cli.log` (it names the account signed in), `history.jsonl` (the prompts you typed), `implicit/` and `settings.json` |
| Mistral Vibe (`vibe`) | in `~/.vibe/` (or `$VIBE_HOME`), only the sessions in `logs/session/unified/`.  For each: `meta.json`, of which aht uses the session's id, folder, title, last time and whether a subagent made it; `CURRENT`, which names the latest generation; that generation's `manifest.json`, `projection-state.json` and the files in `chunks/` it names; and the journal (`journal/<number>.jsonl`): what you asked, its replies and its tool calls (for the secrets check also their output).  Of the journal's other records (such as what was sent to the model) aht reads only the type at the end of the line | the user name and model name in `meta.json`; the agent's reasoning; `checkpoint.json` (the model's own context), `runtime-state.json`, `scheduled-loops.json`, the sessions an earlier Vibe left (`logs/session/session_*`), and the data folder's other files: `config.toml`, `.env`, `whoami_cache.json`, `vibehistory` (the prompts you typed), `trusted_folders.toml`, its caches and its logs |

These histories can contain anything you or an agent wrote: code, file
contents, command output, and personal information or secrets.  The
secrets check (`aht secrets`, and before each handover, which warns of
what it finds) reads each history file whole, as it is on disk: for
Codex and Antigravity that includes the parts the table says aht does not
use.  You can switch agents off (`backends`) or point aht at other
folders (`backend_roots`).

### Also

- **Your folders.**  The folders under the roots it watches
  (`watch_roots`): their names and paths, to notice moves, copies and
  renames, and whether each is a git repository, for the badges.
  Checkpoints copy a project folder when a Claude Code session starts;
  `aht rules` reads the project's instruction files (`AGENTS.md`,
  `CLAUDE.md`, `GEMINI.md`).
- **Git state.**  For summaries and catch-ups (a switch, Hand Back, a
  handover, Pick Up, Leave a Note, informed sessions) and for `aht
  loose-ends`: the project's branch, latest commits and their subjects,
  how far it is ahead of or behind its upstream, and which files are not
  committed or changed since a commit; for Pick Up also its origin's
  address and first commit.  aht never fetches, and masks the subjects
  and file names it passes on.
- **Running programs.**  On macOS and Linux: the list of running programs
  with their command lines (`ps`), to find the agents and, for saved
  workspaces, what runs in each terminal tab, and the folder each one runs
  in (`lsof` or `/proc`).  Before a handover, a take-back, Bring Here, Send
  Back, `aht undo` or a second opinion, the name and folder of every
  program of yours that runs inside the project, to warn you of them.  On
  Windows, before a switch or a Send Back, the names of the running
  programs (`tasklist`), of which aht keeps only whether Codex, Kimi Code,
  Antigravity or Mistral Vibe is among them.  The Mac app's session corner
  and chimes, when on, read Claude Code's records of its open sessions
  every second and a half, and the end of each one's conversation file for
  its name.
- **Claude Code's settings** (`~/.claude/settings.json`): to add and
  remove aht's hooks, and to show whether Remote Control and going on
  after the usage limit are on.
- **Permission levels.**  So that the agent that continues a session's
  work starts in the same level (a switch, Hand Back, Pick Up, Bring Here,
  a handover, the night shift and a second opinion): the command line of
  that session's own process, of which aht uses only the permission flags;
  Codex's `turn_context` records in that session's rollout, of which it
  uses only the approval policy and the sandbox; the `permissionMode`
  Claude Code notes on that session's prompts; and from Claude Code's
  settings (`~/.claude/settings.json`, the project's `.claude/settings.json`
  and `.claude/settings.local.json`, Claude Code's managed settings file,
  and a file or text a session's `--settings` names) only
  `permissions.defaultMode` and `sandbox.enabled`.  None of this is kept,
  other than the level in a hand-off's record and in `~/.aht/run/perm.json`.
- **Trust.**  During a handover or a Bring Here: whether Claude Code
  trusts the project folder, from `~/.claude.json` on the machine the
  project leaves.
- **Crossing systems.**  Before a project moves between machines (a
  handover, a take-back, Bring Here, Send Back): whether it is a git
  repository with a `.gitattributes` file, to suggest one when it crosses
  to or from Windows; on Windows, before a handover or a sync, whether git
  converts line endings in it (`git config core.autocrlf`).
- **iTerm2** (macOS): window and tab titles, profiles, and the folder and
  program in each tab, for session names and saved workspaces; tab colours
  from iTerm2's saved window state (`restorable-state.sqlite`, opened read
  only: never the screen contents it also holds), with whether macOS is in
  dark mode; and for *Getting started*, whether iTerm2's Python API and
  its new-output indicator are on and whether that saved state exists.
  aht never changes iTerm2's settings.
- **Machines you could add,** only when you run `aht remote discover`, or
  open the Machines tab in the Mac app (or press *Look Again* there): your
  `~/.ssh/config` and the list of your machines from Tailscale.  The Mac
  app keeps the last answer while it runs.
- **Reaching a machine you added:** its ssh settings (`ssh -G`, which
  reads your `~/.ssh/config`, as ssh itself does each time aht connects),
  and, when that machine's name does not resolve, its address from
  Tailscale's list of your machines.  Nothing of either is sent.  `aht.log`
  records the machine's name and, when aht reached it by its Tailscale
  address, that address; both stay on this computer.

## What aht changes

### In the agents' histories

- **Relinking.**  When a project folder moves or is renamed, aht renames
  that project's history folder to match (Claude Code, Gemini, Cursor,
  OpenCode, Kimi) or rewrites the project path recorded inside its session
  files (Codex, Copilot).  For Kimi Code it also renames the project's
  prompt history and `file-history/` entry, rewrites the folder in each
  session's `state.json` and in `workspaces.json`, and adds lines to
  `session_index.jsonl` and small files to `sessions/.index-dirty/`, so
  that Kimi reads them again; it never edits Kimi's transcripts.  When a
  folder is copied and you keep the copy's history (`copy_policy`), aht
  copies the history folders (Claude Code, Gemini, Cursor, OpenCode,
  Kimi; Kimi's copies get new session ids).  By default it asks you first
  (`move_policy`, `copy_policy`).  Every file it rewrites is copied into
  its backups first.
- **Never deleted.**  aht never deletes a history on its own.  One whose
  folder is gone goes to the Trash only when you ask (`aht tidy
  --remove-history`), and can be restored from there: Finder's Trash on
  macOS; on Linux the desktop's Trash in `~/.local/share/Trash` (through
  `gio trash` when it is installed), whose `info/<name>.trashinfo` records
  the history's original path and when it was moved; on Windows the
  Recycle Bin only.  When a history cannot go there (the drive has no
  Recycle Bin, that drive's bin removes files at once, or the history is
  bigger than the bin holds), aht changes nothing and says why.  To tell,
  it reads that drive's Recycle Bin settings and the policy *Do not move
  deleted files to the Recycle Bin* from the registry, and the drive's
  size; afterwards it counts the items in that bin and reads the bin's
  own records of where its new items came from, to see that the history
  arrived (should Windows have deleted it for good, aht says so).
- **Session names.**  aht's hook hands Claude Code a session's name, and
  Claude Code records it in the session's history, as its `/rename` does:
  on macOS the title of its iTerm2 tab (`tab_names`, on by default), and
  on any system a name you give it in aht's window or with `aht tab-names
  --rename`.
- **Only when you ask:** restoring a backup (adds missing files, never
  overwrites), taking a found secret out of the histories of Claude Code,
  Codex, Kimi Code and Antigravity (`aht secrets --redact`, copies kept
  first; Mistral Vibe's are left as they are), and relinking a history to
  another folder (`aht tidy --relink`).

### In your project folders

- `.aht/.project-id`, a random id that lets aht recognise the folder after
  it moves.
- Folder badges (`icons_enabled`): a custom folder icon stored inside the
  folder on macOS, `desktop.ini` and `.aht\aht-badge-<8 hex>.ico` on
  Windows, an emblem on Linux.  On Windows a changed badge gets a new
  file, and the old one (also the `.aht\aht-badge.ico` older versions
  wrote) is removed.
- Only when you use the feature: journals in `.aht/journal/`, the
  project's instruction files with `aht rules --unify --apply`, and files
  put back with `aht undo --apply` or `aht changes --revert --apply`.
  Whatever these replace is set aside in `~/.aht` first.
- **`.aht/handover/`**, only when you hand a project over, bring one
  here, switch agents, or pick up work or leave a note across machines:
  - a handover's summary (`<time>-to-<machine>.md`: the session's title
    and id, the folders on both machines, your task as you wrote it, the
    exchanges, to-dos, file names, git state and commit subjects, with
    keys masked, and the files outside the project the session used);
  - for a handover of a Claude Code session, a copy of that session's
    scratch folder (Claude Code's `scratchpad` under `/tmp`), when it holds
    100 MB or less, in `scratch/<session id>/`; the next handover replaces
    it;
  - for each switch, Hand Back, Pick Up, note, Bring Here, Hand Over into
    another agent, and each catch-up a Take Back or Send Back brings from
    another agent, a record of who handed the work to whom
    (`relay-<id>.json`) and its summary (`relay-<id>.md`: exchanges,
    to-dos, file names, git state and commit subjects, keys masked).  The
    record holds this computer's name, its random id from `machine.json`
    and its system; for a Pick Up, a note, a Bring Here, a Hand Over into
    another agent or such a catch-up also the other machine's name, its
    random id (when known), its system and the project's path there; the
    project's path and id; the two agents, their session ids and the
    session's title, masked; when; the git branch, the latest commit, and
    how many files were not committed and commits not pushed; and the
    permission level aht started the receiving agent in (`perm`: `ask`,
    `edits`, `auto` or `never`, whether inside a sandbox, and the flags);
  - later, small markers: `relay-<id>.closed` (what answered it, and when)
    and `relay-<id>.told` (the session told of it, and when).

  Every hand-off still open and the newest 12 others are kept.  Your
  other machines add the same files to a project here when they pick its
  work up from this computer or leave a note here, and this computer adds
  them to the project's folder there.  Like `.aht/journal/`, the folder
  carries its own `.gitignore`, so git leaves it out.  A record that came
  with the folder all the same (a repository that committed one) is read
  only as aht writes them: a machine's name of letters, digits, spaces and
  `. _ -`, agents aht knows, times as numbers, titles masked; nothing else
  in it reaches a Claude session.
- **Brief probes.**  To learn whether the disk takes `readme.md` and
  `README.md` for one name, aht briefly makes and removes a `.aht-case-…`
  file: during a take-back that brings files back (in the project folder
  and its Claude Code history folder), in the project folder before a
  Send Back is planned on the project's home, and before a Bring Here in
  the folder the project goes into (or the nearest folder above it that
  exists).  On Windows, for a take-back or a Bring Here, it also briefly
  makes and removes a `.aht-link-…` link there, to learn whether your
  account may make links, and reads from the registry whether Windows
  allows long paths (`LongPathsEnabled`).
- **Line endings.**  When a take-back or a Send Back gives a changed file
  back the line endings it left with, aht writes the new version next to
  it as `<name>.aht-eol-…`, then puts it in the file's place, keeping its
  time and mode.
- **Never `.git/config`.**  A session that aht starts after a handover or
  a Bring Here gets git settings in its environment instead
  (`GIT_CONFIG_COUNT`, `GIT_CONFIG_KEY_…`, `GIT_CONFIG_VALUE_…`:
  `core.filemode=false` on a PC, `core.autocrlf=true` when the project
  comes from a PC whose git converts line endings).  For a project that
  crosses to or from Windows without a `.gitattributes`, aht only
  suggests lines for one; it never writes that file.
- **aht's own copy** (`handover_transfer`; used where rsync is not): while
  it brings files into a folder, on this computer or on your other machine
  (a project folder, Claude Code's history, checkpoints and plans for it,
  the folder of a file taken along with `--include`, the backups), it
  keeps the pieces of the files under way in a `.aht-partial` folder
  inside that folder, with a small lock file that holds the number of its
  process.  aht removes that folder when the copy ends; one left by a copy
  that was stopped is emptied by the next copy into that folder and
  removed at its end.  It never travels.

### Elsewhere on your computer

- **Claude Code's settings** (`~/.claude/settings.json`): aht's hooks, and
  Claude Code's own setting for going on after the usage limit when you
  switch it in aht.  Before it changes that file, aht copies it to
  `settings.json.bak-aht` next to it (`settings.json.bak-aht-uninstall`
  when the Mac or Linux uninstaller removes the hooks); the copies stay
  until you delete them.
- **Starting at login:** LaunchAgents in `~/Library/LaunchAgents` (macOS);
  an entry under
  `HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run`
  (Windows); a systemd user unit or an autostart entry in `~/.config`
  (Linux).
- **The program:** the `aht` command (macOS and Linux).  On Windows, the
  program in `%LOCALAPPDATA%\Programs\aht` with a Start menu entry and an
  entry under Settings → Apps when the installer put it there, or in
  `%LOCALAPPDATA%\aht` when `aht install` copied it from the zip; an icon
  cache for the badges in `%LOCALAPPDATA%\aht\icons` (aht removes the
  files an older version cached there); and that folder on your user
  `PATH` unless a package manager already put `aht` there.
- **Linux badges:** the emblem images in `~/.local/share/icons/hicolor`
  (`24x24/emblems` and `48x48/emblems`, with a stamp file, and that
  folder's icon cache when `gtk-update-icon-cache` is installed);
  `aht uninstall --remove-icons` removes the images, and that icon cache
  too when aht's were the last icons there (when others remain, it writes
  the cache again without aht's).
- **macOS:** Spotlight entries for your session titles (`spotlight`, on by
  default: up to 800 sessions, each with its agent, its project folder's
  name and when it last ran), Time Machine exclusions for aht's folder
  copies (checkpoints and second opinions), and the Mac app's preferences
  (`~/Library/Preferences/com.aht.app.plist`: its windows' places and
  sizes, the session corner's place and size, whether *Also on my other
  machines* stays ticked, which welcome screens you saw, and the versions
  of setup and of updates you declined).
- **Only when you bring a project here** (`aht bring`): the project's
  folder, its Claude Code history (filed under the folder's path here),
  the plans of its sessions and, when the folder has the same path on
  both machines, their /rewind snapshots, in Claude Code's folder; and,
  when Claude Code trusted the folder on the machine it came from and
  `handover_carry_trust` is on, that trust in Claude Code's
  `~/.claude.json` here (on Windows under the folder's path written with
  forward slashes), with a copy of that file kept as
  `~/.claude.json.bak-aht`.  aht changes `~/.claude.json` only while no
  agent session is open on this computer.

## What aht keeps in its own folder

All of this stays on your computer, in `~/.aht` (Windows:
`%USERPROFILE%\.aht`), readable by your user account.  aht does not
encrypt it.

| File or folder | What it holds | How long it is kept |
|---|---|---|
| `config.json` | your settings; for each machine you added, its system, whether you watch it, your home folder's path there, where projects go there (`paths`: `same`, `home`, or pairs of folders), aht's random id there (so a project brought from there goes back to the right machine), whether mosh's traffic gets through (`udp`), and for a Windows PC that answers, what answers there (`runner`: `aht`, `py` or `python`) or why it does not (`answers_why`) | until you delete it, or `aht uninstall --purge` |
| `machine.json` | a random id of this computer (12 hex digits), its name, and when the file was made.  Made the first time aht has to name this computer to another machine or in a project's record (backups copied, a project synced, handed over, taken back or brought here, a hand-off recorded).  Kept out of `config.json`, so a copied config does not clone it | until you delete it |
| `install.json` | the version of aht installed here and the protocol number it speaks with your other machines.  Written by aht's own commands here, never by the copy another machine runs here.  A machine that asks this one learns them, to tell whether this one keeps the records Bring Here and Send Back need | rewritten when aht is updated |
| `offsite.json` | which backups went to which machine (`offsite_backup`), when the last copy ran and how much it sent, and from which computer's folder backups were last fetched (older versions kept this in `run/offsite.json`, which aht removes) | rewritten at each copy and fetch |
| `registry.json` (and `.bak`) | the projects aht tracks (see [below](#the-registry)) | until you delete it, or `aht uninstall --purge` |
| `aht.log`, `aht.log.1` | what aht did and when: folder paths, project and session names and the iTerm2 tab titles aht set (as they are, not masked), session ids, your other machines' names (and the Tailscale address aht reached one by), the notices it showed, warnings and errors; no conversations | `aht.log` becomes `aht.log.1` at 5 MB, replacing the older one: about 10 MB at most |
| `aht-watcher.log` (macOS, Windows), `aht-watcher.err` and `aht-notices.err` (macOS) | the background watcher's and the notices check's own output and errors, which can name project folders; on Linux this goes to your user journal (`journalctl --user -u aht-watcher`) | not rotated; delete them any time |
| `backups/` | see [Backups](#backups) | the newest 10 snapshots per project |
| `search.db` | a search index: the text of messages (up to 4,000 characters each), what each tool call worked on (its command, file path, web address or search, up to 400 characters) and session titles, with keys masked whole before anything is cut (see [Security](#security)), plus agents, project paths and times | until you delete it; rebuilt when needed.  An index made by an earlier version is built anew once, keeping none of its old rows; a session whose history file is gone and that no backup holds then drops out |
| `checkpoints/` | a copy of a project folder made when a Claude Code session starts (`checkpoints`: on by default on macOS, where the copies take no room, off elsewhere), without `.git` and rebuilt folders, so `aht undo` can put it back | the newest 10 per project (`checkpoint_keep`), none older than 30 days |
| `workspaces/` | macOS: saved iTerm2 layouts: this computer's name; windows, tab titles and colours, profiles, folders, which agent runs in each pane, session ids, each Claude session's name (keys masked), and the options it was started with that it keeps when it starts again (permission mode or skipping permissions, model, effort, extra folders, `--agent`, `--chrome` or `--no-chrome`, `--verbose`; never a first prompt).  Tab titles are kept as iTerm2 has them, so that restoring a layout sets them back | the newest 40 (`workspace_keep`) |
| `undo/`, `changes-backups/`, `redacted/`, `rules-backups/` | files aht set aside before replacing them at your request | until you delete them |
| `handover/<project id>/` | the lists and set-asides of handovers, syncs and returns (see [below](#handovers-and-syncs)) | see below |
| `remote/copies.json` | the folders on this computer that are copies of another machine's projects: for each, the kind of copy (`sync`, `handover`, `brought`, `returned`), the project's id, the machine it came from (its name and aht's random id there), the project's path and system there, whether git converts line endings there (`autocrlf`), the attempt it came with, and since when.  Written when you bring a project here, and when another machine syncs a project here or hands one over to this computer | until you delete it; a later copy into the same folder replaces that folder's note |
| `remote/run/`, `remote/replaced/`, `remote/aht-*.py`, `offsite/`, `arrivals/` | what another machine of yours writes here when it hands a project to this computer, syncs one here or keeps its backups here (see [Your other machines](#1-your-other-machines)) | as described there |
| `opinions/` | copies of a project for `aht second-opinion`, with the task and each agent's output | until you discard them |
| `night-shift.json` | the night shifts you planned: the project's path, the task, the machine, the times, and what happened (a cancelled one stays, marked so) | until you delete it; when you plan a new one, those that ended more than 30 days ago are dropped |
| `run/` | short-lived state (see [below](#short-lived-state)) | overwritten as aht runs |
| `aht-icons/` | Linux: the tray's two icons, written by the tray and by `tray.py --check` | rewritten each time the tray starts or is checked |
| `tools/agent-history-tether/` | macOS and Linux: aht's own program files (the core, the watcher, the installers, the guide and that system's helpers: the badge tool on macOS, the tray and aht's window on Linux) | until you delete it; on Linux `aht uninstall --purge` removes it |

### The registry

`registry.json` holds, for each project aht tracks:

- an id, the folder's path, where each agent keeps that project's
  history, and when it was last updated;
- for a project on another machine or on its way there: which machine
  (its name in aht, its host name, its system and aht's random id there),
  the folder's path there, whether this computer handed it over or that
  machine brought it there itself (Bring Here), since when, the session
  handed over and the one that came back, which agent goes on there and
  the window it runs in, a task you gave it, and the files and folders
  outside the project you take along (`--include`);
- which projects are kept in sync, with which machine and at which path
  there; when a release or a sync paused that, why, when and for which
  machine, and for a sync's pause how many files were changed, new or
  removed there with the names of up to 50 of them (or, for a folder
  there that held something else, the names of up to 50 of its files and
  its project id, if any); names the disk there cannot hold apart (up to
  10 groups of each kind);
- how the last take-back, Send Back or release went: how many files
  changed, the names of those kept in both versions, the folder's path on
  the other machine, for a Send Back its attempt's id, which other agent
  worked there and its catch-up's record id, the names of files that
  differed only in line endings or got back the line endings they left
  with, and of files kept aside under a safe name.

It also holds the ids of projects you told aht to forget, with when (no
paths), so a scan does not take them on again; where a move you said no
to went, so aht does not ask again; the paths of the git repositories in
the watched folders and when aht last looked, for the git badge; and on
Linux, which version of aht's emblems the git folders have.

### Handovers and syncs

`handover/<project id>/` holds, for a project handed over, kept in sync,
or brought to another machine with Bring Here:

| What | Kept |
|---|---|
| `manifest.json`: the list of the project's files and folders on both machines when it left (names, sizes, times, which files are executable, and checksums of its conversation files) | until the project is back or released, then the newest 5 earlier lists |
| `there/<machine>.json` (an older `there.json` is read the same way): the lists of the project's files and folders, of its Claude Code history and of what you took along with `--include`, on both machines (names, sizes, times, link targets, and checksums of the files there up to 64 MB each) as they were after the last sync, handover or take-back with that machine, with that machine's name and the folder's path there.  The next sync, Hand Over and *Bring Them Here* compare the copy there with it | until the next sync, handover or take-back with that machine replaces it |
| `replaced/<time>/`: what a take-back (also *Bring Them Here*) or a Send Back from another machine replaced or removed here; in `kept-aside/` files a take-back brought whose names this computer cannot hold, under safe names (`a%3Ab.txt`), or under a short name of one part when their path would be too long (`0-notes.txt`) | the newest 5 folders and every one younger than 30 days |
| `brought/`: for a project brought here, what was in the folder here before and was replaced, or did not belong to the project | the newest 5 folders and every one younger than 30 days |
| `incoming-…/`: the files of a Send Back on their way in | until the Send Back ends |

### Short-lived state

`run/` holds state aht overwrites as it runs:

- `notices.json`: the notices already shown (which sessions were working
  or waiting, on which machine), when each of your other machines was last
  asked and since when one that holds a project of yours has not answered,
  and which usage-limit stops and new versions were already told;
- `tab-names.json` (the names aht gave sessions, the newest 500) and `iterm-tabs.json`
  (the iTerm2 tabs it last saw, with their titles), both as they are, not
  masked, since aht compares names with tab titles;
- `setup.json` and `setup-later`: when setup ran, or that you chose *Not
  Now*; `update.json`: the last answer about new versions (version
  number, release notes, their page, when);
- `claude-version.json`: Claude Code's version and where it is;
- `app-alive` (macOS) and `tray-alive` (Windows): that the Mac app or the
  tray runs, so that it shows aht's notices;
- macOS: the session corner's marks (`corner.json`: each open session's
  id, its last state, and when it finished), the time of the last layout
  save (`workspace-autosave`), the tabs and titles a restore just opened
  (`workspace-opened.json`), and for a terminal window aht opens, the
  command it runs (`<name>.command`: the folder and the command);
- lock files (`mirror.lock`, `workspace-restore.lock`, and `.lock` and,
  on Linux, `.aht-tray.lock` in `~/.aht` itself), backups on their way in
  while a fetch runs (`offsite-in-…`), and for a moment a copy of another
  program's database aht reads (Codex's `state_5.sqlite`, Antigravity's
  `conversation_summaries.db`), deleted right after.

These files in `run/` are kept longer:

| File | What it holds | How long it is kept |
|---|---|---|
| `app-notices.jsonl` (macOS), `tray-notices.jsonl` (Windows) | each notice handed to the Mac app or the Windows tray to show: its title and text, with what a click on it opens (the project's path, a session's id and process, a machine's name, a hand-off's id) and when | until you delete it: aht only adds to it |
| `stage-<number>.json` (macOS) | the Mac app's view of a job's progress (its stage and percentage) | until you delete them |
| `perm.json` | the permission level aht started an agent in at each hand-off on this computer (Switch, Hand Back, Pick Up → *Open in*, Bring Here): the hand-off's id, the agent, the project's path, the session id when known, the level, whether inside a sandbox, the flags, and when.  aht reads the level a Hand Back continues in only from here, never from the record in the project | the newest 400 |
| `claude-sandbox.json` | the settings that turn Claude Code's sandbox on (`{"sandbox": {"enabled": true}}`), which aht names with `--settings` when it starts Claude Code in never-ask mode inside its sandbox | rewritten when missing or changed |
| `board.json` | for each of your other machines, when it last answered and the sessions it had open then: agent, project folder (the path there), process and session ids, state and since when, and the name, title and what it waits for, masked as that machine sent them | rewritten each time one answers; a machine you remove, or add again under the same name, is dropped at once |
| `incoming.jsonl` | what your other machines left in this computer's projects through Pick Up and Leave a Note, one line each: when, the record's id and kind, whether the work left from here or came here and whether it came back, the project's path and folder name, the other machine's name (as it names itself), the agent that worked and its session's title (masked), and when that work began and ended.  The notices tell of each new line once; the hook and the window use it to tell that aht itself put a record there | the newest 300 lines |
| `autostart.json` | that you answered whether aht's tray starts at login: the answer and when.  Written only when your answer took effect (`aht autostart on` or `off`, the Windows installer's first install, the start-at-login switches in aht's window, the Mac app and the trays, the welcome), so a first setup's *no* counts even when the tray did not start at login anyway.  On a Mac the command itself changes nothing, since the app has the switch, and *Getting started* then marks the login step optional | rewritten at your next answer |
| `window.json` | Windows and Linux: the process id and port of aht's window server, when it started, and the key a second `aht window` uses to reach it | removed when the server stops (on Linux also at logout); one left by a server that was ended at once is replaced by the next `aht window` |
| `window-<id>.json` | Windows and Linux: the progress of a job started in aht's window (a handover, a take-back, Keep in sync, Bring Here, Send Back) | deleted when the job ends; one left behind is removed after 6 hours, when the window next starts |
| `aht-setup-<version>-windows-<arch>.exe` | Windows, installed with aht's installer: the installer *Upgrade* downloaded | the latest only |
| `tray-check.json` | Linux: whether the tray can run here, with the tray's path and modification time, the Python that runs it, and when it was checked | rewritten when one of those changes; a "no" is checked again after a minute |

### Backups

- **Contents.**  One ZIP file per project per snapshot, holding copies of
  that project's history files from every agent aht watches: the complete
  conversations, as the agents store them, including anything sensitive
  they contain.  A small `.meta.json` file next to each ZIP lists what is
  inside.  Files aht is about to rewrite while relinking are copied to
  `rewrites/` in the same folder.
- **Location.**  `~/.aht/backups/<project id>/`, or the folder you set in
  `backup_dir`.
- **When.**  At most once every 24 hours (`backup_interval_hours`), and
  only when the project's histories changed since the last snapshot.
- **Retention.**  The newest 10 snapshots per project (`backup_keep`);
  older ones are deleted automatically.  The copies in `rewrites/` are
  kept until you delete them.  For the copies on another machine
  (`offsite_backup`) see [Backups there](#backups-there).
- **After uninstalling.**  Backups stay until you delete them, so that
  removing aht never costs you a history.  `backup_enabled = false` stops
  new backups.

### aht's window on Windows and Linux

aht's window is a page that aht serves to your own browser from a small
web server at `127.0.0.1`, which nothing outside your computer can reach.
It serves only its own page and guide, from the folder aht is installed
in (never from the folder it was started in), and loads nothing from the
internet.  It opens only through the tray or `aht window`, with a code
that works once.  That code gives the page a cookie and a key of its own;
the key comes after `#` in the address, a part no server ever receives,
and the page keeps it in the browser's session storage so that a reload
works.  A second window in the same browser uses the same cookie and key;
a browser without a cookie aht knows gets new ones.  Every request that
runs a command or reads anything through the window (the guide, a job's
progress) needs both; the page's own files (its HTML, script and style
sheet) need only the cookie.  So other servers on `127.0.0.1`, which
receive the cookie too, can neither run anything nor read anything but
those files.  A launch code is good for 2 minutes.  On Linux the server
also refuses connections made by another account of this computer (it
reads `/proc/net/tcp` to tell whose they are).  Windows has no such
check; there, an account without administrator rights cannot read
another account's command lines, where the launch code appears.  The
server stops once nothing has asked it anything for 15 minutes (an open
window asks once a minute) and no command it started still runs.  It
notes in `aht.log` the port it serves on.  aht opens the page as an app
window of Edge or Chrome (or else in your default browser), in your usual
browser profile, so that browser keeps the page's cookie and may keep its
address in its history.

The folder chooser is Windows' own folder dialog, which aht shows itself
in a second aht process (`aht.exe _pick-folder`: no PowerShell, no
compiled code and no temporary files in `%TEMP%`), or on Linux zenity or
kdialog.  The window opens a folder in Explorer or your file manager, and
`https` links (in the guide, a release page) in your browser, when you
click them.  Nothing is sent anywhere.

## What can leave your device

aht itself never sends anything to the author or to any server the author
runs.  With its default settings it makes no network connections.  The
features below send data, and only after you set them up.

### 1. Your other machines

**Which features.**  Handover and take-back, Bring Here and Send Back,
Keep in sync (`aht mirror`, also in the background every 30 minutes),
`offsite_backup` and fetching backups, `aht night-shift`, Pick Up and
Leave a Note, and the session list, notices, Watch and search for those
machines.  They work between macOS, Windows and Linux, over SSH (or mosh,
when both machines have it) to the machines you add with `aht remote
add`.  When both machines have mosh, aht sends one small UDP message
(`aht-ping`, to port 60999 or 60998) that the machine answers, once per
machine and again at each `aht remote check`, to learn whether mosh's
traffic gets through.

A Windows PC asks your other machines: it hands projects over to them
and takes them back, keeps projects in sync with them, brings their
projects to itself and sends them back, asks for their sessions,
notices, Watch and search, picks up their work and leaves notes on them,
and copies its backups to one of them and fetches backups from it.  Only
when you set up an SSH server on the PC is it asked itself (see [A PC
that answers](#a-pc-that-answers)).

**Connecting.**  Before its first command to a new machine, `aht remote
add` and `aht remote check` ask which system answers there (`echo aht-os
%OS% $env:OS`).  To a Windows PC aht then sends no shell script: it runs
its far end with one command line that cmd.exe and PowerShell read
alike, through aht installed there (`aht _agent`) or else through its own
copy with the PC's Python (`py -3` or `python`).  When neither answers,
it stops there (a copy the PC's Python wrote but could not run stays in
`~\.aht\remote\`).  The machine's system is kept in `config.json`, and so
are, once aht has asked, the path of your home folder there, aht's random
id there, and on a PC what answers there or why nothing does.  Where a
project goes there follows `remotes.<name>.paths` (`aht remote paths`):
the same path, the same place below the home folder there, or folders
you name; for a machine set up before this rule existed, aht once looks
whether this computer's home folder path exists there.

**What the machine tells aht each time it connects** (to check it, hand
a project over, take it back, sync it, and so on): its host name and
system, your home folder's path there, the versions of Python, aht (and
the protocol it speaks) and Claude Code, where Claude Code's folder and
command are and where the Codex, Kimi Code, Antigravity and Mistral Vibe
commands are, which of rsync, tmux, byobu, mosh-server, curl, a package
manager and ufw it has, whether a Tailscale network interface is there,
whether Claude Code is signed in (only whether its credentials file is
there, never its content; not asked of a Mac), how many Claude Code
sessions are open, aht's random id there, and whether Claude Code's
sandbox and a keep-awake tool work there.  For the project's folder
there: whether it exists and can be written, whether other accounts may
read it, its real path, the free space, its project id, how many entries
it holds, whether aht there counts it as a copy of another machine's
project, as its own project or neither, how the disk treats names (case,
links, long paths), and the sessions (names and what they wait for,
masked) and other programs that run in it.

**What a handover or a sync sends.**  The project folder, its Claude Code
history, the plans of its sessions and, when the folder has the same path
on both machines, their /rewind snapshots, the files and folders you take
along (`--include`), and, for a handover, a readable summary.  The
project's `.aht/handover/` (summaries, records of who handed the work to
whom, and the copy of the session's scratch folder) goes with a handover,
which never removes anything from it there; Keep in sync leaves it out.
Before a handover, aht runs the secrets check over the project's
histories and warns you of what it finds, since those travel too.  When
Claude Code there is another version than here, aht installs this
computer's version there, downloaded from Anthropic (`curl` with Claude
Code's install script; on a PC, `claude install <version>`, Claude Code's
own installer).

**What aht writes there:**

| There | What | How long it is kept |
|---|---|---|
| the project folder, its Claude Code history, plans and /rewind snapshots, what you took along | what was sent | until you remove them |
| `~/.aht/remote/aht-<checksum>.py` | aht's copy of itself, named after its checksum; a copy that did not arrive whole is removed, never put in place (on a PC its checksum is checked before it is written).  The `~/.aht/remote/aht.py` older versions put there is removed | the newest 3 |
| `~/.aht/remote/replaced/<project id>/` | what a handover or a sync replaced or removed there (also Claude Code's checkpoints and plans, and what you took along) | for each project, the newest 5 folders and every one younger than 30 days |
| `~/.aht/remote/copies.json` | a note that the folder is a copy of a project of this computer: the folder's path there, the project's id, this computer's name and random id (from `machine.json`), the project's path here, this computer's system and, on Windows, whether git converts line endings in the project here, the kind of copy (kept in sync, handed over, or an old copy whose project went back here), since when, and for a handover its attempt's id.  A take-back changes the kind; turning Keep in sync off asks that machine to drop the note | until you delete it |
| `~/.aht/remote/run/aht-<project name>-<6 characters>/` | the files that start the session there (see below) | `window.json` and `exited` until aht closes the window; the rest until you delete them |
| `~/.claude.json` and `~/.claude.json.bak-aht` | with `handover_carry_trust` (on by default), when Claude Code trusts the project folder here: that trust there, and a copy of the file as it was | until you delete them |
| `~/.claude` under this computer's home path | when a project keeps its exact path there but your home folder's path differs, a link to that machine's `~/.claude`, since the history names that path | until you delete it |
| `~/.aht/aht.log` | lines about what aht's copy did there, each naming the project's path: a Bring Here or Send Back, a note left, on a PC each arrival offered and withdrawn, and the keep-awake helper's line when no tool would keep the machine awake | as aht's log there |
| `.aht-write-test-…`, `.aht-case-…`, `.aht-link-…` | brief probes: whether a folder can be written (in the project folder there, and when aht checks the machine, in the path of this computer's home folder there, or the nearest existing parent of either); whether the disk takes `readme.md` and `README.md` for one name (in the folder that holds the project there, before a handover); on a PC, whether your account may make links, with whether Windows allows long paths (`LongPathsEnabled`) read from the registry | removed at once |

The copy of this computer's backups there is under
[Backups there](#backups-there).  aht writes `copies.json` there in one
place only, for those steps.  When aht is installed on that machine, it
reads the file there: to say where such a folder came from (in its
window, and in one line its hook adds to a Claude session that starts in
the folder), to refuse to keep such a folder in sync from there too, and
to leave it out of *Keep All Projects in Sync*.

**Starting the session there** (a Mac or Linux machine).  In its
`~/.aht/remote/run/…/` folder aht writes the note the session reads first
(machine names, systems, folder paths, the summary's path, the files
outside the project that did not come along); its settings (a hook that
shows that note, and Claude Code's sandbox turned on when the session here
ran in it); `command.txt`, the line the session runs: the flags of the
permission level the session here runs in, `handover_claude_args`, the
name it shows in Remote Control (its iTerm2 tab's title and the machine's
name, as they are), your task as you wrote it, if you gave one, and git
settings for its environment (`core.autocrlf=true` when the project comes
from a PC whose git converts line endings; never in the project's
`.git/config`); when this attempt's session started, so that aht can tell
later, should the link drop, whether it started; `window.json` (the
agent, the project's path there, the session's id, when it started, the
ids of the hand-off and of this attempt, the permission level and the
keys that end that agent); and once the agent ends, `exited` (its exit
status and the time), which the window's own command line writes.  With
`handover_remote_control` (on by default), the session can be reached
from the Claude app through Claude Code's Remote Control.

A handover into another agent (`--agent`: Codex, Kimi Code, Antigravity
or Mistral Vibe) starts that agent there instead, with a first prompt that
points to the summary in the project's `.aht/handover/` (made and masked
here, and sent with the project); Antigravity also with its
`--remote-control` while `handover_remote_control` is on.  At never-ask
level aht first runs `kimi -p` there with the summary (and your task, if
you gave one) and Kimi's window opens that session; below it, Kimi opens
and you paste the first prompt.

**Keeping it awake** (`handover_keep_awake`, on by default).  While the
agent works there, a helper of aht's next to the session holds
`caffeinate` (macOS), or on Linux `systemd-inhibit`, or the GNOME
desktop's own inhibitor (`gnome-session-inhibit`) where ssh sessions may
not use it, while a session in the project works or waits for you, or
while another agent's window there wrote output in the last 10 minutes;
it lets go when that is idle.  A closed lid still sleeps.  The GNOME one
is asked through your own desktop session's bus there
(`/run/user/<your uid>/bus`) and holds off suspend only: the screen still
locks.  The helper notes its process id, the project's path and when it
started in `awake.pid` in the same folder, and ends when it finds no
session in the project three times in a row (it looks every 30 seconds),
after 24 hours, or when aht ends the session or closes its window there.
On Linux, `systemd-inhibit --list` there shows it, with aht as who and the
project's path as why (`gnome-session-inhibit --list` for the GNOME one).
The helper tries the tools for a moment when it starts and keeps the
first that works; should every tool be refused (polkit may refuse
`systemd-inhibit` over SSH) or end by itself, it writes a line naming the
project's path into aht's log there.  `aht remote check` tries them there
for a moment too.

#### A PC that answers

Only when you set up an SSH server on a Windows PC and add it on another
machine.  That machine then hands projects over to it and takes them
back, watches it and searches it; nothing in aht stops it from also
keeping a project in sync there or keeping its backups there
(`offsite_backup`).  It does not bring projects from a PC or send them
back there, plan night shifts with it, pick up its work or leave notes on
it, or attach to it.  What goes there and what is read from it are as for
any machine, with these differences:

- aht's own copy, `~\.aht\remote\aht-<checksum>.py`, is put there only
  when aht is not installed on the PC (or is older), written by the PC's
  Python from what aht sends on the connection.
- A project's path never matches there, so its /rewind snapshots do not
  go.  The trust in `~\.claude.json` is kept with forward slashes, as
  Claude Code writes it there.
- No session starts there and nothing is kept awake: there is no
  `window.json`, no command and no keep-awake helper, and aht never types
  into a session on the PC or ends one.  It writes when the handover
  reached the PC (`~\.aht\remote\run\<window name>\attempt-<id>`), next to
  it the note Continue here's session reads first (`note.txt`) and its
  settings (`settings.json`: a hook that shows that note, with Claude
  Code's sandbox turned on when the session here ran in it).  The
  session's title and your task are sent as they are and masked there.
- A record waits for you, `~\.aht\arrivals\<window name>.json`: the
  project's path on the PC and its folder name, this computer's name and
  random id, the agent (Claude Code), the id of the session handed over
  and its title (masked, at most 120 characters), your task, if you gave
  one (masked, at most 400 characters), the attempt's id, when, the words
  the tray shows (*shop came from mac*, *Continue here*), what Continue
  here runs (`aht _arrival --continue <name>`) and the line to resume the
  session by hand, the flags it starts Claude Code with (the permission
  level the handover named, and `handover_claude_args`), whether inside
  Claude Code's sandbox, where the note is, and when the PC's notices
  announced it and when you continued.
- aht on the PC reads it: its notices announce it once (on your phone
  too, when the PC sends its notices there), its tray offers Continue
  here until you use it (or dismiss it) or the project leaves, and
  Continue here opens Claude Code in a console there, in that level and
  with that note; nothing runs until you type.  A second Continue here is
  refused (that session may still be open) unless you add `--again`.  The
  record goes when the project is taken back (or its folder is gone, or
  you dismiss it); the note and the settings stay in their folder.

#### What aht reads from your other machines

All of it travels over your SSH connection, and only for the features
you use.

- *Open sessions:* while you look at the Sessions tab (in the Mac app also
  when you open the Machines tab), when you run `aht board`, and for the
  notices: every 2 minutes for a machine you watch (the *Watch* switch,
  `aht remote watch`; off for every machine until you switch it on), and
  about once a minute while a machine holds a project of yours or a
  handover or night shift with it is under way.  For each open session,
  of any agent: its agent, project folder, process and session ids, its
  state and since when, what it waits for, and its name and title; for
  the Sessions tab also its iTerm2 tab's title and a name waiting to be
  set, whether it runs in iTerm2 or in the background, what aht's checkup
  finds wrong with it and whether it could be restarted, its and the
  installed Claude Code version, and when a usage limit it stopped at
  resets.  Names, titles, tab titles and what a session waits for are
  masked before they leave that machine.  With them comes whether aht
  there sends that machine's notices to your phone itself (yes or no;
  nothing about where to), so that this computer does not send them a
  second time.
- *The window another agent runs in there* (a handover with `--agent`):
  with the session list, when that window last wrote output (tmux's
  `#{window_activity}`, a time), whether it is open, and its `window.json`
  and `exited`.  That gives its state: *working*, *quiet for 6 min* or
  *exited* (or *tmux did not answer*).  aht does not read what the window
  shows for that, nor what the agent says.
- *Screen lines,* twice only.  When a Hand Over starts the session there
  (Claude Code or another agent), that machine reads the window's last
  screen lines, at most 14, for up to 12 seconds, to see whether the agent
  started or asks something (whether you trust the folder, or that it
  ended at once); it masks them there and sends them here with the
  handover's answer, where they are in `aht handover --json` (`screen`)
  and are not kept.  And `aht attach --peek` (when you ask) reads the
  window's last screen lines there, at most 200, masks them there and
  shows them here without keeping them, with the window's state and the
  sessions and programs running in the folder.
- *Ending a session there* (Take Back with `--stop`): an idle Claude Code
  session gets Ctrl-C twice, up to four times within 30 seconds, and its
  window is then closed; never typed text, and a working session is left
  alone.  For another agent, that machine first reads the newest messages
  of that agent's own session there, to tell whether its turn ended (only
  the answer comes here), and aht then types that agent's quit keys into
  its window (Ctrl-C twice, or Ctrl-D for Kimi Code).  A new start under
  the same window name ends an earlier one.
- *What another agent did there, on the way back:* Take Back of a project
  handed over into another agent asks that machine for a catch-up of what
  happened in the project there since it left, made there from the
  agents' histories and masked there, as for Pick Up (sent: the machine's
  name, the project's path here, the Claude Code session that left, and
  when it left).  aht keeps it here as a record and summary in the
  project's `.aht/handover/`, and its hook gives it once to that Claude
  Code session when you resume it.  Send Back of such a project makes the
  same catch-up on the machine that sends it and sends it home, where aht
  writes it into the project's `.aht/handover/`.
- *Search excerpts:* when you tick *Also on my other machines* or run
  `aht search --everywhere`, aht sends your search words (and the agent,
  project and number of results you chose), and each machine searches its
  own index (`~/.aht/search.db` there), opened read only: aht neither
  builds an index there nor changes one.  For each session found it sends
  the agent, the session's id and title, its project folder and where its
  history is there (a file, or a backup's ZIP file), its times, whether it
  is open, its rank and up to three excerpts with who said them, masked
  there and again here, and when that index was last brought up to date.
  Nothing of it is kept here.
- *Pick Up and Leave a Note* (`aht pickup`, `aht leave-note`), when you
  open either for a project:
  - *Sent, so that machine can find its copy:* the project's id, its git
    origin without any user name or password in it, its first commit, its
    path and its path below your home folder, the name you gave that
    machine in aht, this computer's clock, and the earlier exchanges with
    that machine that the work may come back on (their ids and times, that
    machine's name and id, the agents, session ids, latest commit and
    branch name (masked), and how many files were not committed and
    commits not pushed).  For Leave a Note also the folder there the work
    came from, which that machine then takes as it is, when it is still
    there; for Pick Up also this computer's name and system, the project's
    path here and the agent you open it in.
  - *How it looks:* in its own list of projects and in the
    `.aht/.project-id` of folders at those paths, and only when that finds
    nothing, among the git repositories in the folders it watches (their
    origin and first commit; up to 400 repositories, for at most 6
    seconds).  Only the folders that match come back.
  - *Answered:* the folder's path and how it was found; that machine's
    name, random id, system, home folder path and clock; its latest
    sessions (agent, id, title, when, and whether one is open or working,
    from the programs running there); its git state (branch, upstream,
    how far ahead or behind, the latest commit and its subject, up to 30
    names of files not committed, and how many are untracked); and its
    records of who handed the work to whom (ids, kinds, times and machine
    names).  For Pick Up also the permission level the chosen session runs
    in (the level, whether inside a sandbox, and where that machine read
    it, as under [What aht reads](#what-aht-reads)), and a summary of that
    session, or, when the work comes back, a catch-up of what happened
    there since, made there from the agents' histories the way aht makes
    one here.
  - Titles, commit subjects, file names and summaries are masked there (as
    under [Security](#security)), and the summary again here.
- *File lists of a project's copy:* before each sync, when Hand Over
  checks a copy that was synced or handed over before, and for a
  take-back (also *Bring Them Here*), that machine sends the list of the
  project's files and folders there, of its Claude Code history there and
  of what you took along: names, sizes, modification times, link targets
  and which files are executable.  It also sends SHA-256 checksums of
  some files: those whose size is the same on both machines, so that a
  file that was only touched does not count as changed; after each sync,
  handover and take-back, every file there up to 64 MB that is new or
  changed since the last list; and, for a take-back, the conversation
  files that went on there, to check that each continues the one that
  left.  A take-back also reads there, for some text files, their size,
  their line-ending style and SHA-256 checksums of each as it is and with
  its line endings read as LF, and the Claude Code versions that wrote
  each conversation.
- *For aht's own copy* (where rsync does not copy the files, see
  `handover_transfer`): before it sends files there, that machine sends
  the list of the folder they go into (names, sizes, modification times,
  link targets and which files are executable), so that only what differs
  travels; a take-back reads the same of the project's Claude Code
  checkpoints and plans there.  For a file of at least 256 KB that is
  shorter on one side, such as a conversation that went on, the side that
  has the shorter one gives a SHA-256 checksum of it, and the other side
  checks whether its own file begins with the same bytes; then only the
  new end travels.  Nothing of this is kept.  rsync compares the same
  over its own connection.
- aht keeps only the last session list of each machine, and when that
  machine last answered, in `~/.aht/run/board.json`; the file lists from
  the last sync, handover or take-back of each project with each machine,
  in `~/.aht/handover/<project id>/there/<machine>.json`; and the summary
  you picked up, with its record, in the project's `.aht/handover/` here
  (with `--apply`: *Open in* or *Copy the Start Line*; a look that writes
  nothing keeps nothing).

#### Bring Here and Send Back

`aht bring` and `aht send-back`, only when you ask, and only with a Mac
or Linux machine where aht is installed, since that machine (the
project's home) keeps the project's record.

- *The list of projects there* (`aht bring --from <machine> --list`,
  *Bring Here → From …*): for each project aht keeps there, its path, name
  and id, whether it is there, away (on which machine and since when),
  being handed over, or a copy of another machine's project (that
  machine's name), whether a session is open in it (working, waiting or
  idle), and its latest Claude Code session: its id, its title, masked
  there, and when it was last written.  With it come that machine's name,
  random id, system, home folder path and clock, and whether aht is
  installed there (its version and protocol number, from
  `~/.aht/install.json` there).
- *For the project you pick:* the sessions and other programs running in
  it there (process ids, names, state), its latest Claude Code session's
  id and title (the title masked there) and the permission level it runs
  in (as for Pick Up), how many sessions it has and their ids, the path of
  its Claude Code history there and the names of its sessions' plans,
  Claude Code's version there, whether Claude Code trusts the folder
  there, which other agents keep a history of it, and the lists of the
  project's files and folders and of its Claude Code history (names,
  sizes, times, link targets, which files are executable).
- *Then, with `--apply`, the files:* the project's files, its Claude Code
  history, the plans of its sessions and, when the folder has the same
  path on both machines, their /rewind snapshots.  The other agents'
  histories stay there.
- *What Bring Here tells that machine:* this computer's name, random id
  (from `machine.json`, made then if missing), system and host name, the
  folder's path here, and an id of this attempt; once the copy is
  complete, the lists of the project's files and folders on both
  machines.  That machine notes in its `registry.json` that the project is
  here (all of the above, since when, and the session), keeps the lists,
  with checksums of the conversation files it holds, as the record of
  what left (`~/.aht/handover/<project id>/manifest.json` there), and
  notes the bring in its log.  When the copy fails before that, aht asks
  it to drop the record again; when the link drops just after, aht asks
  it again (then, or when you run the same Bring Here again), and it
  answers that it noted it, changing nothing.
- *What Send Back sends there:* the lists of the project's files and
  folders and of its Claude Code history here, this computer's name,
  random id, system and the folder's path here, the attempt it came with,
  and what that machine asks for to plan the way back: a SHA-256 checksum
  of the beginning of each conversation file that left (to check that it
  continues), for some text files their size, a SHA-256 checksum of each
  as it is and with its line endings read as LF, and their line-ending
  style, the Claude Code versions that wrote the conversations here, and
  this computer's Claude Code version.  That machine answers with its
  plan (file names), the sessions and programs running in the project
  there, and what stands in the way.  With `--apply` aht sends the files
  of that plan, the plans of the project's sessions and, on an unchanged
  path, their /rewind snapshots.
- *What Send Back writes there:* that machine puts the files in place,
  sets aside what they replace or remove in
  `~/.aht/handover/<project id>/replaced/` there (the newest 5 of those
  folders and every one younger than 30 days are kept), keeps both
  versions of a file changed on both machines (`notes (from pc
  2026-10-27).md`), marks the open hand-off records in the project's
  `.aht/handover/` there as closed, notes in its `registry.json` how the
  return went (as under [The registry](#the-registry)), keeps the lists of
  both copies in its `there/<machine>.json` when it knows this computer by
  a name, and shows a notice there.  It answers with what it did, where it
  set files aside, and the latest session's id and title (the title masked
  there).  Asked again for the same attempt (when the link dropped before
  this computer heard the answer), it answers that it is done, with the
  same record, and changes nothing.

#### What Pick Up and Leave a Note write there

Leave a Note writes its summary (`relay-<id>.md`) and its record
(`relay-<id>.json`, as under [What aht changes](#in-your-project-folders))
into the project's `.aht/handover/` on that machine; Pick Up with
`--apply` leaves a copy of its record and of the summary it took there.
When they answer earlier exchanges, they also leave small
`relay-<id>.closed` markers there.  aht only adds there: it creates each
file only when no file of that name is there (a marker that is there
already stands), never replaces or removes one, takes only files named as
aht names them, at most 200 KB each, and writes only into the folder it
found, while that folder has the project id it had then.  The folder gets
its own `.gitignore` when it has none, so git leaves it out.  When aht is
installed on that machine, it also adds a line to `~/.aht/run/incoming.jsonl`
there (see [Short-lived state](#short-lived-state)), so that machine's
notices and its Claude hook tell of it.  When Leave a Note cannot write
there, it removes its record and summary here too.  Nothing runs there,
and no agent starts.

#### Backups there

With `offsite_backup`, copies of the backups go into
`~/.aht/offsite/<a random id of this computer>/` on that machine, with a
`machine.json` naming this computer (its id, name and system, and when it
last copied).  The copies aht made before it rewrote a history
(`backups/<project id>/rewrites/`) go there too.  aht only adds there,
and removes a backup there only after this computer pruned it here (so
the copies there follow `backup_keep`), keeping at least 3 per project;
it never removes the copies made before a rewrite there.  A folder that an older
aht named after this computer is taken over only when everything in it
is here too: its files move into this computer's folder (one that is
there already, with the same size, is deleted), and the older folder is
removed once nothing is left in it; otherwise it stays as it is.
Fetching backups (*Fetch Backups From…*, `aht backup --fetch-offsite`)
reads the list of folders there (each computer's name and system, its
last update, how many projects and backups, their size) and copies the
backups and the copies made before a rewrite that are missing here from
one of them into this computer's backups (`~/.aht/backups`, or
`backup_dir`); it never replaces a file here.

Copies on your other machines stay there until you remove them (see
[Deleting your data](#deleting-your-data)).

### 2. Notices on your phone

With `notify_phone` (off by default), each notice's title and text,
meaning a project or session name and a short status such as "input
needed" (what a session waits for, with keys masked as under
[Security](#security)), go either through Apple's Messages app as an
iMessage to the address you give (macOS), or to the ntfy server you name
(ntfy.sh unless you give your own address).  Anyone who knows an ntfy.sh
topic's name can read it, so choose a name that is hard to guess, or use
your own server; a server address that starts with `http://` gets the
notices unencrypted.

Once you have added another machine, every notice names the machine it
is about: another machine by the name you gave it in aht, this computer
by its own name ("api on box waits for you").  A notice about a session
on another machine goes to your phone only when aht there does not send
that machine's notices to your phone itself.  These notices also go to
the phone:

- when another machine leaves a note in one of this computer's projects,
  hands work back to it, or picks work up from it: that machine's own
  name, the project's folder name, the agent and the session's title,
  masked ("pc left a note on paper: from Codex: “fix the login
  redirect”");
- when a machine that holds a project of yours has not answered for 10
  minutes: one notice naming the projects there ("box has not answered
  since 15:20. The work on api there may have stopped (asleep, off or
  offline)."); the one that says it answers again stays on this computer;
- about a handover that was cut off (it finished, it did not finish, or
  the other machine has not answered for an hour), naming the project and
  the machine;
- when Keep in sync pauses: the project and the machine, and how many
  files were changed there or would be removed ("Keep in sync paused:
  api");
- on a PC that answers, when a handed-over project arrives.

### 3. Features that start an AI agent

All are off until you turn them on or ask for them: informed sessions,
going on in another agent at Claude's usage limit, second opinion, night
shift, switching agents and handing the work back (to Claude Code, Codex,
Kimi Code, Antigravity or Mistral Vibe), Pick Up with *Open in* (the agent
opened here reads the summary from the other machine), Hand Over or Bring
Here into another agent (Codex, Kimi Code, Antigravity or Mistral Vibe
reads the summary as its first turn, there or here), and a handover with
a task.  aht starts the agent's own command (`claude`, `codex`, `kimi`,
`agy`, `vibe`) and hands it a summary of earlier sessions, a catch-up of
what happened since (with keys masked as under [Security](#security)), or
your task; the agent sends it to its provider under your account, as it
does with anything you type into it.  A second opinion's runs leave new
histories of their own for the copies in `~/.aht/opinions/`.

- A new session of any agent reads its summary as its first turn (aht
  runs Kimi's itself, `kimi -p`, at never-ask level).
- A Claude Code session handed the work back, switched to as Claude
  Code's own session, or resumed after a Take Back or Send Back of a
  project another agent worked on, gets its catch-up through aht's hook,
  at most 2,000 characters, once.
- **Lines aht's hook adds to a Claude session** (they go to Anthropic with
  your next message in that session):
  - after a switch, one line in the Claude session that handed the work on,
    when you resume it yourself: which agent worked on the project since,
    when, and where the summary is (the catch-up itself only with
    informed sessions on);
  - after Pick Up or Leave a Note, one line, once, in the next Claude
    session in the project on the machine the work came to (which machine
    it came from, when, which agent worked there, and where the summary
    is), and one line in a Claude session that starts on the machine the
    work left while it is out (which machine has it, since when, and in
    which agent).  A note that hands work back, or a Pick Up that brings
    it back to Claude Code's own session, gives that session its
    catch-up, at most 2,000 characters, once;
  - in a folder that `~/.aht/remote/copies.json` names as a copy of
    another machine's project, one line in each Claude session that
    starts there: that machine's name, and whether the copy is kept in
    sync from it, was handed over from it or brought here from it (then
    also the folder's path on that machine, when it differs), or is an
    old copy of a project that went back to it;
  - in a project that is away, handed over or brought to another machine,
    a warning in each Claude session that starts in it here (which
    machine has it, at which path there when it differs, and since when);
    and in a project that came back, was released, or whose handover did
    not finish, a line that says so (with how many files came back
    updated, new or removed, and up to 8 names of files kept in both
    versions);
  - on the machine a project was handed to, the session that resumes
    there reads the handover's note first (through a hook in the settings
    aht starts it with).

  On another machine, aht installed there adds these lines.
- Switching on Claude Code's own setting for going on after the usage
  limit (in aht) lets Claude Code continue a session by itself when the
  limit resets.

### 4. What an agent does with its own files

The session names aht gives Claude Code become part of its history.  An
agent may sync that history; Claude Code, for example, shows session
names in the Claude app through Remote Control, and a handed-over session
is named there after its tab and the machine.  aht starts Antigravity
with its `--remote-control` option while `handover_remote_control` is on;
what that makes reachable, and through which service, is up to
Antigravity.

### 5. Files you choose to send

`aht share` and `aht journal --write` write pages and journals to your
disk; they leave your computer only if you send them.  A shared page has
the keys and passwords aht recognises masked (as under
[Security](#security)), and its e-mail addresses, local network addresses
(10/8, 172.16/12, 192.168/16, 100.64/10 as Tailscale uses, 169.254/16,
and the IPv6 ones in fd00::/8 and fe80::/10), your home folder's path and
your user and computer names removed.  Paths outside your home folder (an
external disk, `/opt/…`) stay, and masking is best effort, so the page
says under its title to look it through before you share it.

### 6. Looking for new versions

With `update_check` (off by default), aht asks GitHub's public API
(`api.github.com`) once a day which release of aht is the latest; it also
asks once each time you press *Check Now* or run `aht update --now` or
`--upgrade`.  GitHub receives your computer's IP address, the time, and the text
`aht/<version>` naming the version you run; aht sends nothing else and
uses no account.  *Upgrade* then runs your package manager (Homebrew,
Scoop, or winget for an install winget made from the zip), which
downloads the new version from GitHub.  Installed with aht's Windows
installer (as winget now installs it), *Upgrade* downloads the new
installer and the release's checksum file from GitHub (`github.com`,
which sees the same as above), checks the one against the other and runs
the installer; only the latest download is kept in `~/.aht/run`.  A
downloaded copy and a checkout (every Linux install) open the release
page in your browser instead; aht opens only `https` addresses.

### Services run by others

These services are run by others, under their own terms and privacy
policies: Anthropic and the other agent providers, Apple, ntfy,
Tailscale, GitHub and the package managers, and whoever runs the machines
you hand projects to.  The author has no access to them and no control
over them.

## Your controls

- **Settings.**  Each of these is set with `aht config --set key=value`;
  most are also in the Settings of the Mac app or of aht's window:

  | Setting | What it controls |
  |---|---|
  | `move_policy`, `copy_policy` | whether aht asks before relinking (moves and copies: asks by default) |
  | `backup_enabled`, `backup_interval_hours`, `backup_keep`, `backup_dir` | whether, how often, how many and where backups are kept |
  | `offsite_backup` | which of your machines keeps a copy of the backups (none by default) |
  | `checkpoints`, `checkpoint_keep`, `checkpoint_excludes` | folder copies at session start |
  | `icons_enabled`, `icons_agent`, `icons_git` | folder badges, for the projects aht tracks and for git folders |
  | `tab_names`, `spotlight`, `workspace_save_minutes`, `workspace_keep` | session names from iTerm2 tabs, Spotlight entries, saved layouts (macOS) |
  | `session_corner`, `chimes` | the Mac app's list of open sessions and its sounds (both off by default) |
  | `backends`, `backend_roots`, `watch_roots` | which agents and folders aht looks at, and where each agent keeps its history |
  | `notifications`, `notify_waiting`, `notify_finished`, `notify_limit` | notices on this computer, and which kinds |
  | `notify_phone` | notices on your phone: `imessage:<phone or Apple ID>` (macOS) or `ntfy:<topic or server address>` (off by default) |
  | `remotes.<name>.watch` (*Watch*, `aht remote watch`) | whether aht asks a machine for its sessions every 2 minutes (off for every machine) |
  | `handover_carry_trust` | whether a handover marks the folder as trusted in Claude Code on the other machine, and a Bring Here on this computer (on by default) |
  | `handover_remote_control`, `handover_keep_awake` | whether a session handed over can be reached through Claude Code's Remote Control (and Antigravity is started with `--remote-control`), and whether a handover keeps that machine awake (both on by default; the second only with `aht config`) |
  | `handover_transfer`, `handover_mosh`, `handover_excludes` | what copies the files (rsync or aht's own copy), whether aht uses mosh, and names that never travel |
  | `agent_permissions`, `agent_permission_flags` | the permission level the next agent starts in |
  | `log_level` | how much aht writes to its log |
  | `update_check` | whether aht asks GitHub once a day for the latest version (off by default) |

  The features that start an agent are off by default; the README's
  *What uses tokens* table lists them.  Whether the tray or the Mac app
  starts at login is a switch in each of them and in aht's window.
- **Pause.**  Every tray has *Pause Watching*.
- **Look.**  `aht projects`, `aht backup --list`, `aht logs` and
  `aht secrets` show what aht tracks, keeps and has found.

## Deleting your data

1. `aht uninstall` stops the watcher and removes aht's hooks, its
   start-at-login entries, the `aht` command (macOS and Linux) and, on
   Windows, the PATH entry aht added.  `--remove-icons` also clears the
   folder badges (on Linux also the emblem images aht drew); `--purge`
   also removes the `.aht/.project-id` markers, the registry and the
   config (on Linux also aht's program files in `~/.aht/tools`).  It never
   touches the agents' histories.
2. Delete the `~/.aht` folder (Windows: `%USERPROFILE%\.aht`) to remove
   the backups, logs, search index, checkpoints, `machine.json` and
   everything else aht kept, and the folder you set in `backup_dir`, if
   any.  The copies of Claude Code's settings file that aht kept lie next
   to it: `~/.claude/settings.json.bak-aht` and
   `settings.json.bak-aht-uninstall`; delete them too, and
   `~/.claude.json.bak-aht` if a Bring Here left one.  Projects you
   brought here stay where they are, with their Claude Code history, until
   you delete them.  Summaries, records of who handed the work to whom,
   copies of session scratch folders and journals stay in your projects'
   `.aht/handover/` and `.aht/journal/` folders until you delete those
   folders.
3. Remove the app: on macOS, turn *Spotlight* off in the app first (that
   removes its entries), then drag `aht.app` to the Trash or run
   `brew uninstall --cask aht`; the app's preferences go with
   `defaults delete com.aht.app`.  On Windows, Settings → Apps → aht →
   *Uninstall* (it runs `aht uninstall` first), `winget uninstall
   havurgiray.aht` or `scoop uninstall aht`, and the `%LOCALAPPDATA%\aht`
   folder.
4. If you used other machines: delete `~/.aht` there too (or, where aht
   is installed and keeps that machine's own data in it, the parts that
   concern this computer: this computer's backups in
   `~/.aht/offsite/<id>/`, everything in `~/.aht/remote/` (the copies of
   aht, the files that started sessions, what handovers set aside, the
   list of folders that are copies of your projects), and on a PC the
   arrival records in `~/.aht/arrivals/`).  Delete any project copies you
   no longer want, with their Claude Code history, plans and snapshots
   there, the summaries and records in those projects' `.aht/handover/`,
   `~/.claude.json.bak-aht` if a handover left one, and the `.claude`
   link aht made under this computer's home path there, if any.  aht
   there also names this computer, in its `registry.json` and
   `~/.aht/handover/`, for each project this computer brought from there
   or sent back.

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
and hand-back summaries (also the commit subjects and file names in
them), the records of who handed the work to whom (session titles), a
PC's arrival records (the session's title and your task), the notes aht's
hook adds about them, `aht relays --show`, journals, notices (also those
sent to your phone) and what a session waits for (masked before it leaves
another machine), the screen lines a handover's start and `aht attach
--peek` read on another machine (masked there), shared session pages
(also the tools they list), Tidy Up's preview of a history, What Changed,
the notes for informed sessions, loose ends and second opinions, `aht
limits` (the usage-limit text), and session titles and names, tab titles
and names waiting for a session's next prompt wherever aht lists them or
sends them on: the session board (also what other machines receive, and
other machines' boards), Show Sessions and Spotlight, reports, loose
ends, a handover's dry run and result, Take Back, What Changed, `aht undo
--list`, `aht checkup` (also the plan of `--restart`), `aht tab-names`
(its list, `--json` and its sync plan), and the session names in saved
workspaces.

**Not masked.**  On this computer, session names and tab titles stay as
they are: in the Mac app's session corner, in the iTerm2 tab titles aht
sets from a session's name, in `run/tab-names.json` and
`run/iterm-tabs.json`, in the tab titles of saved workspaces (restoring a
layout sets them back), and in `aht.log`.  The task you give a handover is
sent and kept as you wrote it (in the summary, the command that starts
the session there, and the first prompt), except in a PC's arrival
record; so is the name a handed-over session shows in Remote Control
(its tab's title).  Folder paths are never masked.

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
