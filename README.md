![agent-history-tether: move the project, keep the agent memory](docs/banner.jpg)

# agent-history-tether  (`aht`)

> **Move a project folder and your AI coding agents forget everything about
> it.**  Claude Code, Codex, Gemini, Cursor and friends each keep per-project
> conversation history keyed to the folder's *absolute path* — as an encoded
> directory name, a path hash, or a cwd recorded inside session files.  Rename,
> move, nest or copy the folder and the agent silently starts from zero; the
> history is still on disk, but orphaned, with no built-in way to reattach it.
>
> **aht fixes that for all of them at once.**  One tiny identity marker travels
> with each folder; one background watcher (plus Claude Code's SessionStart
> hook as a backstop) notices moves, renames and copies and re-links every
> agent's history — asking first, by default.  It also auto-backs-up all
> histories, restores them wherever a folder ends up, and badges managed
> folders.  History is never deleted or overwritten.

**New to aht?** The [guide](GUIDE.md) walks through every feature with an example, and lists every setting and every command, with what each does in plain words. It is also in the app (∞ → **Guide**, and a **?** next to each feature opens its section) and in the terminal (`aht guide`).

## The Mac app

On macOS, aht is an app: an ∞ in the menu bar and a window.  On Linux and
Windows it is a tray, aht's window (*Open aht…* in the tray) and the `aht`
command (see *Platforms*).

<p>
<picture><source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/mac-projects-dark.png"><img src="docs/screenshots/mac-projects.png" width="49%" alt="The Projects tab: every tracked folder, where it is, when it was last used, and the actions for the selected one"></picture>
<picture><source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/mac-sessions-dark.png"><img src="docs/screenshots/mac-sessions.png" width="49%" alt="The Sessions tab: open sessions with their names, Go to Tab, and Restart in Its Tab for one outside the Claude app"></picture>
</p>

- **Projects** — every tracked folder: here or handed over, a session
  working or waiting for you, last used, which agents have history there.
  Select one to hand it over, keep it in sync, continue its session or
  switch agent; **More** has Show Sessions (every session, branches under
  the one they came from), What Changed, Undo a Session, Journal,
  AI-Use Statement, Share, Project Rules, Secrets, Second Opinion and Night
  Shift.  **Look Back** has Loose Ends and the Report; **Tidy Up** appears
  when something needs a decision.
- **Sessions** — the open sessions here and on your other machines, each
  with the name the Claude app shows (taken from its iTerm2 tab), **Go to
  Tab**, and **Restart in Its Tab** for one that is outside the Claude app
  or on an older Claude Code; **Restore Workspace** brings the iTerm2 tabs
  and their sessions back after a restart.
- **Search**, **Machines** and **Settings** tabs; Finder Quick Actions,
  ⌃⌥⌘A, Spotlight, `aht://` links and notices you can click.
- A **?** next to every feature opens the [guide](GUIDE.md) at its section:

<p><picture><source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/mac-guide-dark.png"><img src="docs/screenshots/mac-guide.png" width="70%" alt="The guide window: every topic on the left, the selected one on the right"></picture></p>

*The screenshots show made-up projects, in your page's light or dark look;
`docs/make_screenshots.py` renders them again.*

## Supported agents

| backend | agent CLI | storage model | relink | confidence |
|---|---|---|---|---|
| `claude` | Claude Code | `~/.claude/projects/<encoded-path>` | rename dir | **verified** (+ SessionStart hook backstop) |
| `gemini` | Gemini CLI | `~/.gemini/tmp/<sha256(path)>` | rename dir | high |
| `cursor` | Cursor Agent CLI | `~/.cursor/chats/<hash(path)>` | rename dir | best-effort |
| `opencode` | OpenCode | `$XDG_DATA_HOME/opencode/project/<enc>` | rename dir | best-effort |
| `codex` | OpenAI Codex CLI | `~/.codex/sessions/**/*.jsonl` (cwd inside) | rewrite cwd, **backup-first** | high (layout confirmed on a real install) |
| `copilot` | GitHub Copilot CLI | `~/.copilot/history-session-state/**` | rewrite cwd, **backup-first** | best-effort |
| `kimi-code` | Kimi Code 2.x | `~/.kimi-code/sessions/wd_<slug>_<sha256[:12]>` (+ prompt-history and file-history companions; the path is also recorded in each session's `state.json` and in the workspace catalog) | rename bucket + companions, re-point `cwd`, **backup-first** | **verified** (key function ported from the CLI's own source, layout mapped from a real install) |
| `kimi` | Kimi CLI 1.x | `~/.kimi/sessions/<md5(path)>` (+ `user-history/<md5>.jsonl` companion) | rename dir + companion | **verified** (mapped from a real install; kept for machines the 2.x migration has not reached) |

**Why "best-effort" is still safe:** dir-rename backends are *self-verifying* —
aht only acts when `key(old_path)` names a directory that actually exists,
which proves the key formula matches that tool's reality; otherwise it does
nothing.  Metadata-rewrite backends copy every file they are about to touch
into the backup store first.  Disable any backend with
`aht config --set backends=claude,gemini,…`.

Two backends can serve one agent: Kimi changed its store layout between
1.x and 2.x, so `kimi` and `kimi-code` both count as *Kimi* on badges and in
prompts.  For Kimi Code, aht renames the session bucket (that is how the
CLI finds sessions), re-points the `cwd` a resumed session would run in,
renames the workspace's catalog entry, and appends to the CLI's session log
instead of rewriting it.  Transcripts are never edited, and workspace
*trust* is deliberately not carried to the new location — Kimi asks again.

## Platforms

aht runs on macOS, Linux and Windows.  The core — keeping every agent's
history with its folder through moves and copies, backups, restore, badges,
the tray — works on all three.  On a Mac the window is the app; on Windows
and Linux it is **aht's window**, which the tray opens (*Open aht…*, or
`aht window`): a page aht serves to your own computer only, shown in an app
window of Edge or Chrome, with the same tabs and dialogs.  What needs macOS
(iTerm2, Spotlight, Finder, APFS copy-on-write) stays there.

| feature | macOS | Linux | Windows |
|---|---|---|---|
| Moves, copies and relinks; backups and restore; badges; the tray | ✓ | ✓ | ✓ |
| The Claude Code hook (relinks when a session starts) | ✓ | ✓ | ✓ |
| The window: projects, sessions, search, settings, the guide | ✓ (the app) | ✓ (aht's window) | ✓ (aht's window) |
| Welcome and setup, Getting started, new versions (opt-in) | ✓ | ✓ | ✓ |
| Search, journal, report and AI-use statement, share, secrets check, project rules, loose ends, tidy, show sessions | ✓ | ✓ | ✓ |
| Switch agent and hand back, second opinion, informed sessions (use tokens; off by default) | ✓ | ✓ | ✓, not yet tried on Windows |
| Ask your other machines: add and check them, Watch, their sessions and notices, search everywhere | ✓ (also a PC that answers) | ✓ (also a PC that answers) | ✓ (asks Mac and Linux machines, over Windows' own ssh) |
| Pick Up and Leave a Note: a project's context moves between machines, git moves the files | ✓ | ✓ | ✓ (the PC starts every exchange, with Mac and Linux machines) |
| Be asked by your other machines | ✓ | ✓ | optional, with OpenSSH Server on the PC (a PC that answers): Hand Over, Take Back, Watch, its sessions, search; without it a PC only asks, and needs no ssh server |
| Backups on another machine: copy them there, fetch them back | ✓ | ✓ | ✓ (to and from Mac and Linux machines) |
| Hand Over and Take Back, keep in sync, night shift | ✓ | ✓ | ✓ (to Mac and Linux machines) |
| Hand Over to a PC and Take Back from it (no session starts on the PC: its tray offers *Continue here* until you use it, which opens Claude Code in the session handed over, in the permission level the handover named and told that it changed machines) | ✓ | ✓ | the PC receives it (aht there answers, or aht's own copy with its Python 3) |
| Bring Here and Send Back (the machine that gets the work starts it) | ✓ | ✓ | ✓ (from Mac and Linux machines) |
| Hand Over or Bring Here into Codex, Kimi Code, Antigravity or Mistral Vibe there (uses tokens: that agent reads a summary), its state on the board, and a catch-up for Claude Code on the way back | ✓ | ✓ | ✓ (Hand Over to Mac and Linux machines; Bring Here into an agent on the PC), not yet tried on Windows |
| Projects at other paths on each machine; names, line endings, executable marks and git across systems | ✓ | ✓ | ✓ |
| Stay awake while a handed-over agent works there (a closed lid still sleeps) | ✓ (`caffeinate`) | ✓ (`systemd-inhibit`, or the GNOME desktop's own inhibitor (`gnome-session-inhibit`) where ssh sessions may not use it) | — |
| Notices (waiting for you, done, usage limit, new version) | every 30 s; a click goes to the session | every 30 s while the tray runs | every 30 s while the tray runs; a click opens the window |
| Undo a session (a copy of the folder when a session starts) | on: copy-on-write copies cost no room | off: real copies up to 100 MB once `checkpoints=true` | as Linux |
| Session names from iTerm2 tabs, Go to Tab, workspace restore, restart in its tab | ✓ (iTerm2) | — | — |
| The session corner, chimes, Spotlight, `aht://` links, Finder Quick Actions, search shortcut | ✓ | — | — |

A Windows PC asks; it needs no ssh server for that.  From a PC, aht adds
and checks your Mac and Linux machines, watches them, shows their
sessions, searches them, picks up their work, leaves notes on them and
keeps a copy of its backups on one of them.  It also hands projects over
to them and takes them back, and brings their projects to the PC and
sends them back.  The guide's *A Windows PC with your other machines* says
how to set up the keys.  Optionally the PC answers too, with OpenSSH
Server on it: then a Mac or Linux machine hands projects over to the PC
(no session starts there; its tray offers *Continue here*, once, which
opens Claude Code in the session handed over, in the permission level the
handover named, never more), takes them
back, watches it and searches it.  The guide's *A Windows PC that
answers* says how to set it up safely (key login only, a firewall rule
for Tailscale or your own network).

CI runs the whole test suite on Linux and macOS for every push, including
aht's window (its doors, its page and a command through it), and on real
Windows it smoke-tests the exe: moves and relinks, the watcher, backups,
search, journal, report, share, secrets, rules, loose ends, undo, tidy,
setup and the window; it also runs aht's own file copy there, from source
and with the exe as the far end, on x64 and ARM64.  The window's pages
were tried in a browser on a Mac and on Windows 11; on Linux, `linux/tests/vm_check.sh` checks its server
on a real machine.

## Install

**Prebuilt** — from the
[releases page](https://github.com/havurgiray/agent-history-tether/releases)
or a package manager:

| platform | how |
|---|---|
| **macOS 13+** (Apple Silicon and Intel) | `brew install --cask havurgiray/tap/aht` then `aht install` — or download `aht-<version>-macos-universal.zip`, drag `aht.app` to Applications, open it and choose *Quick Setup* in the welcome window (*Not Now* or closing it waits for the next version of the app; Settings → This Mac → *Run Setup Again…* has it meanwhile; first launch: see the note on unsigned builds below).  The app **is** the menu bar tray (look for the ∞ icon) and carries the core, the FSEvents watcher and the badge tool prebuilt, so no compiler is needed |
| **Windows 11** (x64 and ARM64) | download and run `aht-setup-<version>-windows-<x64\|arm64>.exe`: it installs aht for you (no admin prompt), sets up the hook and the watcher (which starts at sign-in), puts `aht` on your PATH, asks whether to show the tray when you sign in (on the first install only, and the answer holds, also in the welcome's Quick Setup and over a tray entry an earlier `aht install` from the zip left: unchecked, only the watcher starts at sign-in, until you tick it in the welcome or turn it on later; an upgrade keeps what you set later), starts the tray and opens aht's window; Start menu → *aht* opens it again, Settings → Apps removes it (your history stays) — or `winget install havurgiray.aht` (the same installer) — or `scoop bucket add havurgiray https://github.com/havurgiray/scoop-bucket` then `scoop install aht`, or the zip for your CPU, then `aht install` |
| **Linux** | from a checkout: `cd linux && ./install.sh` (systemd user watcher + hook + `aht`); tray: `python3 linux/tray.py` (needs PyGObject + AppIndicator; GNOME also needs the AppIndicator shell extension) |

**On a Mac, aht works best with [iTerm2](https://iterm2.com):** session
names from tab titles, Go to Tab, Restore Workspace and clicks in the
session corner need it.  After installing, the app lists what is left to
switch on, with a button or a switch for each step (Settings → *Getting
started*; `aht getting-started` in a terminal, which `aht install` also
prints).

**From source** (needs Python 3.9+): clone the repo, then `./install.sh` on
macOS (compiles the Swift watcher, badge tool and tray — needs the Xcode
Command Line Tools), `cd linux && ./install.sh` on Linux (the `install.py`
at the top of the repo is the Mac's and stops elsewhere; `aht install` from
a Linux checkout runs `linux/install.sh`), or build the exes on Windows
(`windows\build_windows.bat`, which also builds the installer when Inno
Setup 6 is there; or `windows/build.sh` via Docker+Wine from macOS/Linux)
and run `aht.exe install`.

> **Unsigned builds.**  The macOS app is ad-hoc signed (no Apple Developer
> ID yet), so Gatekeeper blocks the first launch of a downloaded *or*
> Homebrew-installed copy ("Apple could not verify…"): allow it once under
> *System Settings ▸ Privacy & Security ▸ Open Anyway*, or clear the flag
> with `xattr -dr com.apple.quarantine /Applications/aht.app`.  (macOS also
> stamps that flag on the helper copies the app installs under `~/.aht`;
> the installer clears it from those copies, and `aht doctor` checks that
> the badge tool really runs.)  After an upgrade, run `aht install` again so
> the watcher and the hook use the new core.  The Windows
> exes are unsigned, so SmartScreen shows "unknown publisher" on first run
> (*More info ▸ Run anyway*).  Every release ships `SHA256SUMS.txt`, and
> every artifact is built and smoke-tested on GitHub's runners for its exact
> platform before it is published.

Then, everywhere:

```sh
aht adopt --apply     # tether this machine's existing projects (store-corroborated, add-only)
aht status            # which agents were detected, what's tracked
aht doctor            # check every piece
```

> **Already using another folder-tethering tool?**  Run only ONE watcher/hook
> set at a time, or you'll get doubled prompts.  Legacy `.claude/.project-id`
> markers are read automatically, so previously tagged folders carry straight
> over via `aht adopt --apply`.

## Pause or uninstall

**Pause watching** (temporary — no uninstall needed): every tray has *Pause
Watching*; resume the same way.  While paused, the Claude SessionStart hook
still protects any project you open.

**Uninstall** removes the watcher, the hook, the tray autostart and the `aht`
command.  No agent's history is EVER touched by uninstalling:

| platform | command |
|---|---|
| macOS | `aht uninstall` (or `./uninstall.sh` from a checkout); then drag `aht.app` to the Trash, or `brew uninstall --cask aht` |
| Linux | `aht uninstall` (or `cd linux && ./uninstall.sh` from a checkout) |
| Windows | installed with the installer or winget: Settings → Apps → aht → *Uninstall* (it runs `aht uninstall` first), or `winget uninstall havurgiray.aht`; Scoop: `aht uninstall`, then `scoop uninstall aht`; the zip: `aht uninstall` |

Optional flags (every platform):

- `--remove-icons` — also clear the folder badges aht applied (on Linux
  also the emblem images aht drew in `~/.local/share/icons/hicolor`)
- `--purge` — also remove the `.aht/.project-id` markers and aht's own
  registry/config under `~/.aht` (every agent's history still stays intact)

Leftovers by design: the histories themselves, backups under `~/.aht/backups`
(delete by hand if unwanted), and on Windows after a zip install the exe
folder (delete it yourself — a running exe can't remove itself).
[PRIVACY.md](PRIVACY.md#deleting-your-data) lists everything else aht kept.

## How it works

- **Marker**: `.aht/.project-id` (a UUID) travels with the folder on
  move/copy — that's the identity every backend's history is tethered to.
- **Registry**: `~/.aht/registry.json` maps `uuid → {real_path, per-backend
  stores}`.
- **Watcher**: FSEvents (macOS) / inotify+polling (Linux) /
  `FindFirstChangeNotificationW` (Windows) over the configured roots; on a
  debounced change it detects moves/renames/copies and asks to relink
  (policies configurable: ask / auto / never / ignore).
- **Hook**: Claude Code is the only agent CLI with hooks, so its SessionStart
  hook doubles as the guaranteed backstop — opening Claude in a moved folder
  relinks *every* backend, even moves the watcher missed.
- **Backups**: every project's histories (all backends, one zip) are
  auto-snapshotted (`backup_enabled`, `backup_interval_hours`, `backup_keep`,
  `backup_dir`); `aht restore <folder> --apply` reconnects a folder to a
  snapshot wherever it now lives — via its marker, or evidence-ranked matching
  when even the marker is gone.  Restored Codex/Copilot sessions get their cwd
  re-pointed at the new path.
- **Badges — one symbol per agent**: a folder opened in several CLIs shows
  which ones.  Each agent gets a white-ringed disc in its own color with a
  distinct glyph — claude coral ✳, gemini blue ◆, codex teal ○, cursor black
  ▲, opencode orange ■, copilot purple ▬, kimi violet ☾.  A tethered folder
  no agent has history in yet shows a grey ∞ instead.  Badges follow reality:
  the agent list is re-checked on every watcher pass, Claude session start
  and `aht icons --refresh`, so an agent first used long after a folder was
  tethered still gets its disc.  **1 agent** → one
  full-size disc (lower right); **2** → two smaller, side by side; **3** →
  three smaller still; **4 or more** → a single slate disc showing the
  *count*.  The git "+" (center on macOS and Windows) is independent and
  unaffected.  Rendered as composited folder icons on macOS/Windows (the
  icon files live inside the folder, so they travel with it) and as
  generated emblems on Linux (installed into the user icon theme; ≤3 agent
  emblems, a count emblem for 4+, and for git aht's own `aht-git` emblem, a
  white disc with a dark "+", which the file manager places like the
  others — KDE's `.directory` fallback can show only one icon).

## Handover: continue on another machine

Hand a project to another machine of yours — say an always-on box at home —
keep working on it there over ssh or from your phone, and take it back later.
The files, the agent's history and the session itself move; nothing is
installed on the other machine but what it needs anyway (python3, tmux or
byobu, the agent CLI); rsync 3 is optional: it makes big changes faster.
Claude Code resumes its own session there; with `--agent`, Codex, Kimi
Code, Antigravity or Mistral Vibe starts there instead and reads a summary
as its first turn (one turn: uses tokens).  It works between any of macOS, Linux and
Windows: a Mac, a Linux machine or a PC hands projects over to a Mac or
Linux machine.  The other way round, **Bring Here** runs on the machine
that gets the work: it fetches a project with Claude Code's history, and
**Send Back** returns it, so a PC can work on a Mac's project.  aht cannot
ask a Windows PC yet (`aht remote add` and `aht remote check` stop after
one harmless `echo` there, and make nothing on it), so nothing is handed
over to a PC.

```sh
aht remote discover                      # machines of your network that qualify
aht remote add homebox you@homebox       # ssh must work without a prompt
aht remote check                         # what it still lacks, with the fix
aht remote paths homebox                 # where projects go there
aht mirror ~/Desktop/paper --on          # optional: keep its copy there warm
aht handover ~/Desktop/paper             # dry run: what would travel
aht handover ~/Desktop/paper --apply     # send it, resume the session there
aht handover ~/Desktop/paper --agent codex --apply   # or go on in Codex there
aht attach ~/Desktop/paper               # open that session (--peek: its last lines)
aht reclaim ~/Desktop/paper --apply      # bring files and history back

# on the machine that gets the work (a PC, say)
aht bring --from mac --list              # the projects aht keeps on mac
aht bring /Users/me/code/shop --from mac --apply   # fetch one, open its session here
aht send-back C:\Users\me\code\shop --apply        # return the work to mac
```

On macOS the same is in the app's window (**∞ ▸ Open aht…**): pick a project
in the list, then *Hand Over*, *Take Back*, *Open Session* or *Keep in sync*;
the list shows where each project is, when it was synced and whether an agent
session is open in it, and a transfer shows its progress.

- **Any number of machines.**  `aht remote discover` lists the computers of
  your Tailscale network and the hosts in `~/.ssh/config`; add as many as you
  like, pick one per handover with `--to <name>` (the tray: *Machine*), and
  `aht remote default <name>` sets the one used when none is named.  A
  project remembers where it went, so taking it back needs no name.
- **Another agent there** (`--agent codex|kimi|agy|vibe`, for Hand Over and
  Bring Here): Claude Code's history travels as always, the other agent's
  never does; a new session of it reads the summary aht made here (one
  turn: uses tokens), in the permission level of the session it continues.
  Its state comes from its tmux window: *working* while it wrote output
  in the last 15 s, *quiet for 6 min*, *exited*; a notice says when it
  *went quiet*.  `reclaim --stop` ends it only after 2 minutes without
  output and once its own message ends its turn, by its quit keys
  (Ctrl-C twice; Ctrl-D for Kimi Code).  On the way back, a catch-up of
  what it did, made and masked there, goes to the Claude Code session that
  left, which hears it from aht's hook when you resume it.
- **Bring Here and Send Back** need aht installed on the project's home,
  which keeps the record that the project is away and plans the way back
  (the same three-way plan as Take Back; what it replaces is set aside
  there).  Other agents' histories stay home; the session gets a summary.
  On a PC the tray's *Projects brought here* offers Send Back.
- **Where projects go** (`aht remote paths <machine>`): at the same place
  below the home folder there (`home`, what a machine added now gets:
  `/Users/me/code/shop` is `C:\Users\me\code\shop` on a PC), at the same
  paths (`same`), or by pairs of folders you add (`--add D:\work
  /Users/me/work`), tried first.  Claude Code's history is filed under the
  folder's path there; /rewind's snapshots go only when the path is the
  same.  A project outside every mapped folder is refused, with the
  `--add` line that fixes it; so is a folder there that holds something
  else.  With `same`, the path must exist there as a real folder, not a
  link: on Linux, create it once with `sudo mkdir -p /Users/you && sudo
  chown $USER /Users/you` (on a machine other people use too, add `chmod
  700 /Users/you`; `aht remote check` tells you when that is missing).
- **Across systems.**  Names the receiving disk cannot hold (Windows'
  reserved names and characters, two names that differ only in case) stop
  the dry run, which lists them; rename them or add them to
  `handover_excludes`.  On the way back, a file that changed only in its
  line endings is not taken, and one whose line endings flipped as a whole
  gets back the ones it left with; a git project without `.gitattributes`
  gets suggested lines for one (aht never writes it).  Executable marks
  survive a round trip through a PC.  A session aht starts gets
  `core.filemode=false` (on a PC) through `GIT_CONFIG_*` in its
  environment; `.git/config` is never edited.
- **Nothing moves while something runs.**  An open agent session blocks the
  transfer, working or idle, and no flag overrides that: exit it first.  So
  does a background shell the session started, or any other program whose
  working directory is inside the project (`--allow-processes` leaves those
  behind).  On the way back the same holds for the other machine;
  `reclaim --stop` ends a session there only if it is idle.
- **Keep in Sync** copies a project in the background (every
  `mirror_interval_minutes`) while the connection is good, so the handover
  itself only sends the last changes.  Transfers are compressed
  (`handover_compress`).
  It looks before it overwrites: it compares the copy there with its list
  from the last sync, and pauses, sending nothing, when that copy was
  worked on (a file only touched does not count), when it would remove
  more than 200 files there (or more than a quarter of at least 20), or
  when a first sync would go into a folder that holds something else.
  The project then offers *Bring Them Here* (Take Back on the copy: a file
  changed on both sides keeps both versions), *Replace Them* (`aht mirror
  <folder> --replace`; theirs are set aside there), *Allow the Removals*
  (`--allow-removals`) or *Stop Syncing* (`--off`).  Hand Over blocks over a changed copy the
  same way (`--replace-there` goes past it).  The machine that holds the
  copies notes them in `~/.aht/remote/copies.json`, so its own aht will
  not keep such a folder in sync too, and *Keep All Projects in Sync*
  leaves it out.
- **What travels**: the folder, the history store, the `/rewind` checkpoints
  (on an unchanged path) and, with `--include <path>`, files and folders
  outside the project (remembered per project; Take Back brings them back, also after a
  handover that was cut off).  **What stays**: `node_modules`, `.venv`,
  `__pycache__` and the like (rebuilt per machine), Finder's icon files,
  temporary files, running processes.
- **What the session knew travels in readable form too.**  A summary is
  written to `.aht/handover/` — the last compaction, the latest exchanges,
  open to-dos, the files it changed, the outside files it used — and the
  resumed session is told on arrival that it changed machines, what did not
  come along and where that summary is.  That folder carries its own
  `.gitignore`, so excerpts of a conversation never land in a commit.
- **The way back is three-way.**  Changes made there arrive; what changed
  only here stays; what changed on *both* sides is kept in both versions
  (`--prefer there` takes the other machine's instead).  Whatever a transfer
  replaces or removes is set aside first: here in
  `~/.aht/handover/<id>/replaced/`, there in `~/.aht/remote/replaced/`
  (Claude's checkpoints and plans too); the newest 5 of those folders and
  every one younger than 30 days are kept.  A transcript only comes back if
  it *continues* the one that left.  A name whose case changed there
  (`readme.md` → `README.md`) comes back also to a disk that ignores case,
  as a Mac's usually does, with the old one set aside; two names that
  differ only in case are both kept, one under the conflict name; and empty
  folders made there (a packed git repo's `refs`) come back too.
- **What copies the files** (`handover_transfer`): rsync when this machine
  has rsync 3, the other has rsync, and neither is Windows; otherwise
  aht's own copy, which runs over the same ssh with nothing but python3
  on the other machine.  It
  sends each file in pieces of at most 1 MB, checks it on arrival and only
  then puts it in place (a failed replace puts the old file back); a file
  that only grew sends just its new end; what it replaces or removes is
  set aside as above.  Against rsync it gives up the delta inside a big
  changed file and resuming a half-sent one.  `aht remote check` says
  which one each machine gets; `rsync` or `aht` forces one.
- **A handover cut off halfway** (the link drops, this computer sleeps):
  aht notes the attempt before anything travels, and at its next check asks
  the other machine what happened — *Handover of api to box finished: the
  session there runs (the link had dropped at 01:02)*, or *The handover of
  api to box did not finish. The project stays here; nothing runs there*.
  It counts as finished when a session runs there, the copy there changed,
  the conversation went on there, or this attempt's session started there
  and has ended since; *did not finish* only when nothing happened there.
  Take Back refuses a record of what left that belongs to another attempt.
- **Release** — `aht reclaim <folder> --release` (dry run first, then
  `--apply`) lets a project count as here again when the other machine is
  gone or does not answer: the files here stay as they are, the copy there
  is left alone, and the work done there does not come here.  The dry run
  names what stays there (*What stays there: 3 files and the
  conversation*).  aht offers it after an hour without an answer, and
  `aht remote remove` names it for the projects a machine still holds.
  When the project is kept in sync with that machine, Release pauses Keep
  in sync, so no sync replaces the copy left there.  It stays paused until
  you turn it on again (`aht mirror <folder> --on --to box`, or *Turn Sync
  Back On…*; the next sync then looks at the copy there first); a later
  Hand Over to that machine also ends the pause (it sets the released copy
  aside there first, with `--replace-there` when work was left in it), as
  does a Take Back from it.
- **Which session goes on.**  The one you worked in last, picked the way
  `claude --continue` picks it (scripted `claude -p` runs and `/loop`
  sessions do not count) — in both directions.  If that is not the session
  you handed over, because you branched or began another one over there,
  aht says so and offers both (`aht resume-here --handed-over`).
  `handover --session <id>` names one yourself.
- **Same agent version on both sides.**  The handover installs this
  machine's Claude Code version over there and keeps it from updating
  itself.  The way back is refused if the other machine — or anything that
  wrote into the returning history — used a newer version than this machine
  has: update here first (`--ignore-version` overrides).
- **A connection that survives the road.**  With mosh on both machines and
  its UDP ports open, `aht attach` uses it: the terminal stays connected
  through network changes and sleep.  aht tests the path once per machine
  (`aht remote check` tests again) and uses ssh when it is blocked.
- The folder shows a blue → badge while it is away, and a session started in
  it meanwhile is warned, also while a handover of it is unfinished; after a
  Release the next session is told once that the work done there did not
  come here.  With `handover_remote_control` (default on) the
  session there is reachable from the Claude app, including permission
  prompts.

## Across agents

aht reads the sessions of Claude Code, Kimi Code, Codex, Antigravity
(`agy`) and Mistral Vibe (`vibe`), so it can work across them.  On macOS
all of this is in the app's window; the commands behave the same.

- **Search everything** — `aht search <words>` (the window's *Search* tab)
  looks through every session of every agent and project, including
  sessions that were deleted since and live on only in a history backup; a
  hit offers to resume it, or to restore it first.  The index
  (`~/.aht/search.db`) keeps itself up to date.  What aht recognises as a
  key, a token or a password (see *Secrets check*) is masked whole before
  it is stored: in messages, in the commands, file paths and web addresses
  of tool calls, and in session titles.
- **Session board** — `aht board` (the *Sessions* tab) shows every open
  agent session on this Mac and on each machine set up for handover:
  working, waiting for you (and for what), or idle.  The menu bar counts
  the sessions waiting for you.
- **Switch agent and hand back** — `aht switch <folder> --to
  claude|codex|kimi|agy|vibe --apply` continues a project's work in another
  agent: aht writes a summary of the latest session of another agent into
  `.aht/handover/` (where things stood, the latest exchanges, open to-dos,
  files changed, git), and a new session of that agent reads it first, in a
  window of its own.  `--resume` goes on in that agent's own latest session
  in the folder instead, which reads only a catch-up of what happened
  since; `--brief-only` (*Summary Only*) writes the summary and opens
  nothing, so who has the project stays as it was.  `aht switch <folder>
  --back --apply` hands the work back into the session it came from, with
  a catch-up: the other agents' exchanges since, the to-dos still open, the
  files changed (`git diff` against the commit the project was at when it
  was handed on) and the commits made since; when that session is gone, a
  new one reads the full summary and the catch-up.  The earlier session
  stays as it was.  Each hand-off leaves a record next to its summary, and
  `aht relays <folder>` lists who handed the work to whom and when.
- **Hand over with a task** — `aht handover <folder> --apply --task "…"`
  (a field in the window's handover dialog): the session starts working on
  it the moment it has resumed on the other machine.
- **One set of project rules** — `aht rules <folder>` tells which
  instruction file each agent follows; `--unify --apply` makes `AGENTS.md`
  the one set of rules and reduces `CLAUDE.md` to `@AGENTS.md`, the import
  Claude Code documents for exactly this.  Two different files are merged
  only with `--prefer claude|agents|both`, and the earlier files are kept in
  `~/.aht/rules-backups/`.
- **Project journal** — `aht journal <folder>` builds a dated diary from all
  agents' sessions: what was asked, which files changed, how each day ended.
  `--write` keeps it as `.aht/journal/journal.md`.
- **Secrets check** — `aht secrets [folder]` lists what aht recognises as a
  key, a token or a password in the agents' histories, masked, with where
  and when it appeared.  A handover says how many travel with the project.
  aht never changes the histories themselves.  What it recognises:
  - keys of a known kind: Anthropic, OpenAI, Groq, GitHub, GitLab, AWS
    access keys, Google API keys and OAuth tokens, Slack, Stripe live keys,
    SendGrid, Hugging Face, npm, PyPI, age, Vault, DigitalOcean, Shopify,
    Docker Hub, Atlassian and Tailscale keys, JSON web tokens, the secret
    part of a Slack webhook address and the token in a Telegram bot
    address;
  - private keys (PEM, also encrypted, PGP and PuTTY `.ppk`), also inside
    JSON, in a Read tool's numbered output or with `>` or `#` before each
    line, from their BEGIN line to their END line (a guide or code that
    only names the BEGIN and END lines is left alone), and private keys in
    base64 (a kubeconfig's `client-key-data`, a Kubernetes `tls.key`);
  - `Bearer` tokens, `Basic` credentials, and what follows
    `Authorization:` with any other scheme or none (16 characters or
    more);
  - the value given to a name that holds a password, a secret, a token or
    a key (`DB_PASSWORD=`, `AWS_SECRET_ACCESS_KEY=`, `client_secret`,
    `export GITHUB_TOKEN=`, `x-api-key:`, `RAILS_MASTER_KEY=`, `*_PAT=`,
    and camelCase names such as `dbPassword`, `accessToken` and
    `SecretAccessKey`), in a `.env` file, YAML or JSON, on any line of a
    tool's output and in JSON inside JSON, when the value looks generated.
    Not after a name with a word that says it holds something else
    (`TOKEN_URL`, `password_hash`, `token_type`, `max_tokens`,
    `accessTokenUrl`, `token_sha256`) or a page's or a request's token
    (`NextToken`, `nextPageToken`);
  - a password on a command line (`--password X`, `--token X`,
    `--with-token X`, `--api-key X`, `mysql -pX`, `docker login -p X`,
    `sshpass -p X`, `redis-cli -a X`, `curl -u user:X`) and in XML
    (`<password>X</password>`, `key="…Password" value="X"`);
  - the password in a web or database address, whatever the host
    (`postgres://app:…@db:5432`, also with an `@` in the password, and
    Go's `user:…@tcp(host:3306)/db`); the rest of the address stays
    readable.

  It leaves alone placeholders and references to a secret store
  (`${DB_PASSWORD}`, `<token>`, `changeme`, `op://…`, `vault:…`), code and
  format strings (`tokenizer.encode(text)`, `password: Optional[str]`, a
  cut `{name`), names (`MAX_RETRIES`, `spring.datasource.password`), paths
  and web addresses (`/etc/ssl/private/…`, `config/service-account.json`),
  ARNs, fingerprints and hashes, a port or an image's tag, test names
  (`test_auth.py::test_token`, `--- PASS:`) and words.  Masking is best
  effort, and aht does not try to guess at every shape a secret could
  have: a value with no name or form it knows stays in clear, and so can a
  value under 8 characters, one after a name it does not know
  (`STRIPE_KEY`), a password with a quote or a space in it (masked only up
  to there), or one that does not look generated (small letters only, a
  word and digits, words joined by `-`).  PRIVACY.md lists the rules and
  the known limits.  So keep secrets out of agent chats.

  Wherever aht copies text out of a history, it masks what it recognises
  whole (a key of any length, up to 64 KB), and it masks before it shortens
  a text, so a cut never leaves part of one: the search index, journals,
  handover, switch and hand-back summaries (those folders also carry a `.gitignore`),
  notices and what a session waits for, shared session pages (also the
  tools they list), Tidy Up's preview, What Changed, the notes for informed
  sessions, loose ends and second opinions, `aht limits`, and session
  titles and names, tab titles and names waiting for a session's next
  prompt wherever aht lists them (the session board, also what other
  machines receive, loose ends, a handover and Take Back, What Changed,
  `aht undo --list`, `aht checkup`, `aht sessions`, reports,
  `aht tab-names` and its sync plan, saved workspaces).  On this computer
  only, names and tab titles stay as they are where aht needs them so: the
  session corner, the iTerm2 tab titles aht sets, its files about tabs in
  `~/.aht/run` (`tab-names.json`, `iterm-tabs.json`), the tab titles of
  saved workspaces and `aht.log`.

- **Notices** — `aht notices` (run every 30 seconds by a LaunchAgent) tells
  you when a session, here or on another machine, starts waiting for you or
  finishes a long piece of work; optionally also on the phone
  (`notify_phone = imessage:<you>` or `ntfy:<topic>`).  With
  `session_corner` on, the app also lists this Mac's open Claude sessions
  in the screen's top-right corner: working, waiting for you, or done
  (until you click it, which goes to its tab, or it works again).  With
  `chimes` on, the app plays a short chime the moment one of them is done
  or waits for you: aht's own chimes (made by the app, no sound files), a
  macOS sound or a file of yours, one for each.
- **What changed** — `aht changes <folder> [--diff]`: every file a Claude
  Code session edited, before and now, from Claude's own checkpoints;
  `--revert <file> --apply` puts one back (the current one is kept aside).
- **Report and AI-use statement** — `aht report --since week --by
  project|agent|area` (areas: `report_areas` in the config); `--project …
  --statement` drafts a disclosure of AI use for a paper or a course.
- **Share** — `aht share <folder> --format html`: a session as a page with
  keys masked (what aht recognises; see *Secrets check*), and without
  e-mail addresses, local network addresses (private and link-local IPv4
  and IPv6 ones, Tailscale's too), your home folder's path or your user and
  computer names.  Paths outside your home folder (an external disk,
  `/opt/…`) stay, and masking is best effort, so the page says under its
  title to look it through before you share it.
- **Tidy up** — `aht tidy`: gone folders and histories without a folder,
  with suggestions; `--relink <id> --to <folder> --apply`, or
  `--remove-history=<name> --apply` to move such a history to the Trash
  (the Recycle Bin on Windows), where it can be restored.  On Windows it
  goes only to the Recycle Bin: when it cannot go there (the drive has no
  bin, the bin deletes at once, or it is too big for the bin), aht changes
  nothing and says why.  The name must be one from the `aht tidy` list,
  written exactly as there; a link there (to a folder elsewhere) is listed
  but never removed.
- **Backups elsewhere** — `offsite_backup = <machine>` copies the history
  backups there after each daily pass, into a folder of this computer's own
  named by a random id.  Copying only adds: a backup there goes only after
  this computer pruned it, and at least 3 per project stay.  The copies
  made before a rewrite go there too, and aht never removes those there.
  `aht backup --offsite-list` lists every computer's folder there;
  `aht backup --fetch-offsite [--from ID|NAME]` brings backups (and those
  copies) back, on a new computer too, adding what is missing and never
  overwriting.
- **Taking a key out** — `aht secrets --redact <fingerprint> --apply`
  replaces one found secret in every history file (copies kept first; not
  while a session is open there).  A private key goes as its header, its
  lines of key and its END line, and nothing around it; it is listed once
  even when the history holds it twice (the Read tool's numbered copy and
  the file's text), and a new scan then no longer finds it.
- **Finder and a shortcut** — right-click a project folder for aht's
  Quick Actions; ⌃⌥⌘A (`hotkey`) opens the search from anywhere.

### The permission level follows the work

When you start a session in a mode that does not ask (Claude Code's
`--dangerously-skip-permissions`, Codex's full bypass) or asks less, the
agent that continues the work starts in its own equivalent: Switch, Hand
Back, Pick Up → Open in, Bring Here, Hand Over and the night shift, on this
machine and across machines.  **aht never raises the level on its own; it
carries the level you chose to the next agent, on this machine and across
machines; restarts keep a session's own flags.**  The next agent never gets
more power than the session it continues: where it has no exact match, it
starts in the next stricter level, and every dialog, dry run and text
output says which (*Codex starts in never-ask mode, like the Claude Code
session you are leaving*).  `--json` of `switch`, `pickup`, `bring` and
`handover`, dry runs included, carries `perm: {level, from, flags, read,
sandbox, agent, text}`; `switch` and `pickup` also carry `kimi_reads` and
`first_prompt` (Kimi Code, below).  *Continue Here* (`aht resume-here`)
reopens a Claude Code session in its level too.  **Only levels you set
yourself raise what the next agent gets** (your own command line, your
user or managed Claude Code settings, aht's own settings, or a level aht
recorded on this machine); anything from a repository or another machine
is not trusted for that.

| level | Claude Code | Codex | Kimi Code | Antigravity | Mistral Vibe |
|---|---|---|---|---|---|
| `ask` (each agent's default) | — | — | — | — | — |
| `edits` (edits run, commands ask) | `--permission-mode acceptEdits` | `-a on-request -s workspace-write` | — (it asks) | `--mode accept-edits` | `--agent accept-edits` |
| `auto` (routine runs, risky asks) | `--permission-mode auto` | `-a on-request` | `--yolo` | `--mode auto` | `--smart-approve` |
| `never` (never asks) | `--dangerously-skip-permissions` | `--dangerously-bypass-approvals-and-sandbox` | `--auto` | `--dangerously-skip-permissions` | `--auto-approve` |

- **How aht tells the level** of the session the work comes from: an open
  session's command line (its options up to the first prompt, whose words
  are no flags), no higher than what the session itself noted, and for
  Codex with what the command line leaves out filled from its newest
  `turn_context`; else what the session itself noted (Codex's
  `turn_context`: its approval policy and sandbox; Claude Code's
  `permissionMode` on its prompts); else the level aht started it in, kept
  on this machine in `~/.aht/run/perm.json` (so Hand Back keeps it; the
  relay record's `perm` in the project is only shown, never believed);
  else Claude Code's `permissions.defaultMode` in its settings: your user
  settings, the managed settings and a `--settings` on the session's
  command line.  The project's `.claude/settings.json` and
  `settings.local.json` count only for `acceptEdits`, `plan` or `default`
  (Claude Code itself takes bypass mode only from the user's, managed or
  command-line settings).  Unknown means `ask`.  Codex asking on request
  in its workspace sandbox is also what it does on its own in a trusted
  folder, so that reads as `ask` unless its command line or aht's record
  says more.  Claude Code's `dontAsk` refuses what was not allowed in
  advance, so it counts as `ask`.
- **By what the agent can actually do.** Claude Code's skip-permissions
  goes on as Codex's full bypass.  A never-ask Claude session inside Claude
  Code's own sandbox (`sandbox.enabled`) goes on as Codex's never-ask that
  keeps its sandbox (`-a never -s workspace-write`); that Codex session goes
  on in Claude Code as skip-permissions together with Claude's sandbox
  (`--settings ~/.aht/run/claude-sandbox.json`, a file aht writes, so a
  restart keeps it) where the sandbox works (macOS; Linux with
  bubblewrap), else in `auto`.  Kimi Code, Antigravity
  and Mistral Vibe have no such sandbox, so they go on in `auto` then.  At
  `ask` aht adds no flag, so an agent starts as its own settings say.
- **Kimi Code reads its summary in a run of its own (`-p`) only in
  never-ask mode:** Kimi takes no level flag together with `--prompt`, and
  that run never asks.  Below never-ask, Switch, Hand Back and Pick Up →
  Open in Kimi open Kimi's own session with the level's flag and no such
  run: the text output prints the one line to paste as your first message
  (`--json`: `kimi_reads: false` and `first_prompt`).
- **A second opinion** works in a throwaway copy of the project, so Claude
  Code may edit that copy at any level (`--permission-mode acceptEdits` at
  `ask`); its commands follow the level, never above it.  Kimi Code takes
  part only in never-ask mode (its unattended run never asks); below it,
  Kimi is left out with a warning that says why.  `aht second-opinion
  <folder> --task "…" --dry-run --json` shows each agent's `perms`,
  `agents` and `left_out` without starting anything.
- **Settings** (in the window and the Mac app: Settings → Permissions):
  `agent_permissions` is `follow` (the default), a fixed
  level (`ask` … `never`: your own choice for every next agent), or a cap
  (`max:auto`).  `agent_permission_flags` replaces aht's own flags per
  agent and level, e.g. Codex's never-ask that keeps its sandbox:
  `aht config --set 'agent_permission_flags={"codex": {"never": ["-a",
  "never", "-s", "workspace-write"]}}'`.  aht refuses flags there that
  could ask for more than their level (read the most permissive way:
  `-anever`, `-c approval_policy=never` and the like), flags it does not
  know as permission or harmless flags (such as Codex's `--profile`), a
  Claude Code `--settings` that holds permissions or a sandbox, and two
  permission flags that ask for different levels.  `handover_claude_args`
  is still added after the level's flags.

## Before and after a session

- **Undo a whole session** — when a Claude Code session starts (and before
  another agent takes over), aht makes a copy-on-write copy of the project
  folder in `~/.aht/checkpoints/` (APFS clones: no room taken until a file
  changes; the last 10 per project; rebuilt folders and `.git` left out).
  `aht undo <folder>` shows what differs; `--apply` puts the folder back,
  including what the session's commands changed; what was there goes to
  `~/.aht/undo/` first.  `checkpoints = false` turns it off.  A project
  over `checkpoint_max_files` (20,000) gets no copy: a copy of 98,000 files
  measured 17 s of disk work per session start and ~100 MB of file-system
  entries per kept copy.  `aht checkpoint --coverage [--max N]` lists who is
  cut off and their biggest folders; `checkpoint_excludes` leaves folders
  out.  Time Machine is told to skip the copies (it would store them in
  full).
- **Claude's usage limit** — aht spots a session that stopped at the limit
  in its transcript (no tokens), says so in a notice with the reset time
  (`notify_limit`), and marks the project.  `aht limits` lists them.  With
  `limit_switch = true` it also offers to go on in `limit_switch_to` (Kimi
  Code by default; Codex, Antigravity or Mistral Vibe) — that agent's
  tokens are used when you accept.
- **Informed sessions** — with `informed_sessions = true`, a new Claude Code
  session learns in a few lines where the last session in its folder
  stopped, whichever agent ran it (last request and answer, open to-dos,
  files changed; keys masked).  A session another agent took the work over
  from, resumed by hand, learns instead what happened since.
- **Loose ends** — `aht loose-ends`: projects of the last 30 days with work
  not committed, open to-do items, or a last session that ended on a
  question or an offer.
- **Second opinion** — `aht second-opinion <folder> --task "…"` runs Claude
  Code and Kimi Code on the same task, each in its own copy; `--show <id>`
  compares answers and changes, `--take <id> --from kimi --apply` brings one
  into the project (refused for files changed there meanwhile); `--dry-run`
  says the level each would work in and starts nothing.  Claude edits its
  copy at any level, its commands follow the level; Kimi takes part only in
  never-ask mode.  Needs `second_opinion = true`.
- **Night shift** — `aht night-shift <folder> --task "…" --start 22:00
  --back 07:00 --apply`: a handover with a task at the start time, taken
  back when the session is done after the end time (the notices agent keeps
  the clock; the Mac has to be awake).  Needs `night_shift = true`.
- **Session names from iTerm2 tabs** — `tab_names` (on): a Claude Code
  session is named after its iTerm2 tab's own title, which is what the
  Claude app (Remote Control), `/resume` and the prompt bar show.  Set by
  the SessionStart hook and, after a tab is renamed, at the next prompt
  (a UserPromptSubmit hook that asks iTerm2 for that one tab, about 0.2 s).
  Clashes among open sessions become `Paper · 2`, branches `Paper ⑂ 2`; a
  handed-over session is `Paper @ <machine>`.  The latest name wins both
  ways: a session renamed with `/rename`, in the app or in aht's window
  gives its tab the name, through iTerm2's Python API (switch it on in
  iTerm2 → Settings → General → Magic; with it off, the tab keeps its
  title).  `aht tab-names` lists them.
- **Workspace** — `aht workspace`: iTerm2's windows, tabs, titles, tab
  colours, profiles and the sessions in them are saved while you work
  (every `workspace_save_minutes` by the app, and on the prompt hook's
  background refresh; the last `workspace_keep` are kept);
  `--restore [--apply]` opens the layout from before iTerm2 last started
  again, starting iTerm2 if needed, each session resumed by id with its
  options.
- **Go to a tab, and a checkup** — `aht goto <project|session|pid>` brings a
  session's iTerm2 tab to the front; `aht checkup` marks sessions open
  twice, stuck, outside the Claude app or on an older Claude Code, and
  `--restart <pid> --apply` starts one again in its tab (`--close` ends it).
  A click on an aht notice goes to the session's tab (the app posts the
  notices; macOS used to attribute them to Script Editor).
- **Spotlight and links** — the app puts session titles into Spotlight
  (`spotlight`), and `aht://search?q=…`, `aht://loose-ends`,
  `aht://undo?path=…` and more open the window from the Shortcuts app or a
  script (see the guide); whatever starts an agent or changes files asks
  first.  `aht sessions --json` lists every session with its title.

### What uses tokens

aht's own work runs locally and never asks a model.  These are the only
features that make an agent read or work:

| Feature | What spends tokens | Default |
|---|---|---|
| Informed sessions (`informed_sessions`) | a few hundred tokens of context per new Claude Code session | off |
| Another agent at the usage limit (`limit_switch`) | the other agent reads a summary, when you accept | off |
| Second opinion (`second_opinion`) | both agents work on the task | off, and only when you press Start |
| Night shift (`night_shift`) | the agent on the other machine works on the task | off, and only the shifts you plan |
| Switch agent | the agent that goes on reads the summary (a new session) or the catch-up (its own session): one turn; Claude Code's own session gets its catch-up as with Hand back to Claude Code | only when you ask |
| Hand back to Codex, Kimi Code, Antigravity or Mistral Vibe | that agent reads the catch-up: one turn | only when you ask |
| Hand back to Claude Code | no turn: aht's hook puts the catch-up (at most 2,000 characters) into the session as it opens, and it goes with your next message; without the hook, reading it is the first turn | only when you ask |
| Pick Up → Open in | the agent opened here reads the summary made on the other machine: one turn; when the work comes back to Claude Code's own session, it gets its catch-up as with Hand back to Claude Code | only when you ask |
| Hand over with a task | the resumed session starts on the task | only when you give a task |
| Hand Over or Bring Here into Codex, Kimi Code, Antigravity or Mistral Vibe (`--agent`) | that agent reads the summary as its first turn, there or here: one turn; on the way back Claude Code's own session gets its catch-up as with Hand back to Claude Code | only when you ask |
| Handover note | one sentence in a new Claude session while its project is away, half handed over, or just came back or was released | part of handover |
| Hand-off note | one line in a Claude session another agent took the work over from, when you resume it yourself (the catch-up itself only with `informed_sessions`) | part of switch |
| Pick Up and note line | one line, once, in the next Claude session in the project on the machine the work came to; one line in a Claude session that starts on the machine it left, while it is out | part of Pick Up and Leave a Note |

Everything else — watching, relinking, badges, backups, search, the
session board, notices, loose ends, reports, journals, the secrets check,
what changed, undo, Spotlight, and writing summaries and catch-ups
(*Summary Only*, `aht switch --brief-only`, `aht relays`, a Pick Up that
opens nothing, and Leave a Note) — uses none.

Development is macOS-first: the window and these features are built and
tested on macOS; what reaches Linux and Windows is in *Platforms* above.

## Settings

One shared config (`~/.aht/config.json`) read by the CLI, the watchers, the
hook and all three trays — set with `aht config --set k=v`:

`watch_roots`, `backends`, `backend_roots` (where each CLI's store lives,
for installs not found automatically — set with `aht backends --set-root
name=/path`, or point-and-click via every tray's *Settings ▸ Agent CLI
Locations* page), `move_policy`, `copy_policy`,
`notifications`, `icons_enabled` / `icons_agent` / `icons_git`,
`debounce_seconds`, `scan_max_depth`, `extra_prune_dirs`, `dialog_timeout`,
`watcher_owner`, `log_level`, `backup_enabled` / `backup_interval_hours` / `backup_keep` /
`backup_dir`, `linux_emblem_method` / `linux_agent_emblem` / `linux_git_emblem`;
for handover: `remotes` / `default_remote` (managed by `aht remote`),
`mirror_interval_minutes`, `handover_excludes`, `handover_compress`,
`handover_transfer`, `handover_remote_control`, `handover_carry_trust`,
`handover_claude_args`, `handover_mosh`, `handover_keep_awake`, `rsync_path`, `terminal_app`;
the permission level the next agent starts in (see *The permission level
follows the work*): `agent_permissions`, `agent_permission_flags`;
notices and reports:
`notify_waiting`, `notify_finished`, `notify_finished_minutes`,
`notify_phone`, `notify_limit`, `session_corner`, `chimes` /
`chime_done` / `chime_waiting` / `chime_limit` / `chime_done_after` /
`chime_volume`, `offsite_backup`,
`report_areas`, `hotkey`;
before and after a session: `checkpoints`, `checkpoint_keep`,
`checkpoint_max_files`, `checkpoint_excludes`, `spotlight`, `tab_names`,
`workspace_save_minutes`, `workspace_keep`, and — off by default because
they use tokens — `informed_sessions`, `limit_switch` / `limit_switch_to`,
`second_opinion`, `night_shift`.

Every platform has a tray, shown as an ∞ icon in the bar: `aht.app` (or the
tray compiled by `install.sh`) on macOS, `aht-tray.exe` on Windows,
`linux/tray.py` on Linux.  On Windows and Linux its menu holds everything
(status, reconcile now, pause/resume watching, recent projects, adopt with
confirmation, the policy / notification / backup switches, badge controls,
diagnostics, autostart toggle).  On macOS the menu is kept short — status,
*Open aht…*, *Find Moved Folders Now*, *Pause/Resume Watching*, *Quit* — and
the rest lives in a window with five tabs, **Projects**, **Sessions**,
**Search**, **Machines** and **Settings**, where nothing happens by a stray
click: a row is selected first, a button pressed second.

## Safety invariants

1. History is **never deleted or overwritten** on aht's own initiative (a
   history without a folder goes to the Trash only when you ask) — dir renames refuse occupied
   targets (surfaced as conflicts, never merged; an *empty* directory left
   behind by a tool holds no history and does not count as occupied); metadata rewrites are
   preceded by a mandatory backup copy; restores only add missing files.
2. Adoption is **add-only** and store-corroborated (a backend's store must
   provably exist for the folder's exact path).
3. All registry writes happen under one lock, never held across a dialog;
   folder swaps resolve via two-phase staging per backend.
4. A prompt that cannot be shown (headless) always means **change nothing**.
5. A project is **never transferred while something runs in it**, a
   transcript only returns as a continuation of what left, and a transfer
   sets aside what it replaces.
6. **Nothing spends an agent's tokens unless you turned it on or asked for
   it**, and nothing that starts an agent or changes files runs from a link
   or a notice without a question first.
7. **aht never raises an agent's permission level on its own**: the agent
   that continues the work starts in the level of the session it continues,
   or a stricter one, unless you set a fixed `agent_permissions` level (see
   *The permission level follows the work*).

## Commands

`status` · `doctor` · `adopt` · `reconcile` · `projects` · `orphans --match` ·
`suggest-matches` · `bind` · `prune` · `forget` · `backup` / `backup --list` /
`restore` · `backends [--set-root]` ·
`config` · `roots` / `reload` · `icons --refresh` · `logs [--errors]`
(leveled `[WARN]`/`[ERROR]` lines, size-rotated at `~/.aht/aht.log`) ·
`tag` · `keys <path>`
(each backend's store key for a path) · `encode` · `hook` · `version` ·
`remote` (also `remote paths`) · `mirror` · `handover` · `attach` ·
`reclaim` · `bring` · `send-back` · `resume-here` ·
`search` · `board` · `switch` · `relays` · `pickup` · `leave-note` ·
`journal` · `rules` · `secrets` · `notices` ·
`changes` · `report` · `share` · `tidy` · `limits` · `checkpoint` · `undo` ·
`loose-ends` · `second-opinion` · `night-shift` · `sessions` · `tab-names` ·
`workspace` · `goto` · `checkup` · `getting-started` · `setup` · `update` ·
`window` · `autostart` · `guide`.
Run `aht` with no arguments for the full help screen; every `--json` output is
a stable machine interface (it's what the trays use).

## Tests

```sh
tests/run_tests.sh        # multi-backend core + the masker + Linux layer + Windows badge cache and entry point (any OS, fake stores)
windows/build.sh          # builds the exes, then runs the smoke suites under wine
macos/build_app.sh --test # builds aht.app, then runs the tray's headless selftest
windows/tests/vm_check.sh USER@HOST [-i KEY] [--installer]   # a real Windows machine over ssh
linux/tests/vm_check.sh HOST [--out DIR] [--no-suites] [--keep]   # a real Linux machine over ssh
```

`tests/redact_test.py` checks the masker: every kind of key it knows, at
its usual length and longer, in the places keys stand, masked whole; the
shapes a name=value misses (names on later lines, camelCase, quotes,
flags, XML, keys in base64, Go's addresses), as text and as a history's
raw line, with 39 ordinary lines of the same shapes beside them; what an
earlier masker missed or read as a key, and lines that once made it slow
(each masked in under a second); 90 ordinary lines of code and prose and
71 lines the masker once read as keys (among them a guide and code that
name a private key's BEGIN and END lines), all left as they are; and in
histories, that `aht secrets` lists each find once, `--redact --apply`
takes out only the find, and a place whose removal would break the
history's JSON is left as it was.  Its keys are made up at run time, in pieces.  With
`AHT_BEFORE=<an older aht.py>` it also compares what both versions find in
this repository and in Python's standard library (every difference must
match a rule that says why), and how long they take: it fails when masking
takes more than 1.5 times as long.  (Measured on a Mac: on a 50 MB history
this version takes about 1.5 times as long as 0.13.0, on prose about the same.)

`windows/build.sh` and the Windows CI job run three smoke scripts against
the exes (`windows/tests/wine_smoke.sh`, `wine_watch_smoke.sh`,
`features_smoke.sh`); each works in a folder under `/tmp`, or under
`AHT_SMOKE_DIR` when it is set.  `features_smoke.sh` also checks that
`aht.exe _core --id` names the checkout's own `aht.py` and that `aht.exe
_agent` answers a probe.  `windows/tests/aht_main_test.py` checks where
aht.exe's entry point sends each command.

`windows/tests/vm_check.sh` copies the checkout to a Windows machine
(OpenSSH Server with key login, Python 3.12 and Git for Windows there,
someone logged in at the desktop; the copy leaves out the DEVNOTES files),
builds both exes, runs the smoke suites natively and the badge-cache and
entry-point suites (`winbadge_test.py`, `aht_main_test.py`) from source,
then drives the desktop (leave the machine alone for about four minutes):
the tray and its menu, aht's window (and that its API refuses calls without
the window's key), setup, the folder picker (a real click on *Add Folder…*
in the window, on a server about 110 s old; the chooser must come up in
front, be aht's own `aht.exe _pick-folder` with no PowerShell under it or
the server, and the folder chosen in it, Music,
must show in the welcome's list; **Cancel** in the chooser must ask nothing
more and leave the page usable; a path put into the chooser's *Folder:*
field must show in the welcome's list too), Continue's console (checked by
the folder it runs in, and closed afterwards), notices and a click on one,
Show in Explorer and start at login.  It keeps the display awake while it
runs, and before the tray's menu and before the notice checks it closes
any notice still on screen; one that stays up is reported as a failed
check.  The notice-click check waits up to 30 s for the notice and clicks
on its text, only when the notice itself is what lies under that point.  Its PowerShell runs in a console
that never shows (`conhost.exe --headless`), so no empty console window
sits in front.  It brings back a report with screenshots and uses a
throwaway aht home.  The machine's own aht tray and
watcher, if they run, stop for the desktop check and start again after it,
and the login entry is put back as it was.  `--installer` also builds aht's
installer there (installing Inno Setup 6 when it is missing) and runs it for
real: it first removes an aht that aht's installer put there before
(silently, so the first install is a real one), installs aht, checks the
hook, the sign-in entry, PATH, the Start menu and the Apps list, upgrades
over it twice (start at login on, then off: each must stay as set), and
removes aht again.  Then it installs once more as a first install with the
tray box unchecked, over a tray entry an earlier `aht install` left, checks
that only the watcher starts at sign-in, and removes aht again (an aht
installed there before is gone afterwards). After each first install it also
checks that aht recorded the tray box's answer, and at the end it puts
`~/.aht/run/autostart.json` back as it was.  Its copy, `~\aht-check` on
that machine, stays there after the run, since `--no-build` reuses the
exes built in it; the script's header gives the command that removes it.

`linux/tests/vm_check.sh` does the same for a Linux machine: like the
Windows check, its copy leaves out the DEVNOTES files.  It works in a new
folder of its own there, made by `mktemp -d /tmp/aht-sbx-check.XXXXXX`
(outside the home folder, so the desktop's file indexer never sees it),
and removes that folder at the end, also when a run stops early (`--keep`
leaves it there for a look and prints its path).  It runs the
suites there, then the desktop on an invisible screen of its own (the
tray, aht's window server, setup, the folder picker and its **Cancel**,
which must ask nothing more and leave no chooser, Continue's terminal,
notices, Show in Files, start at login, and that nothing crashed).  Show in
Files waits until README.md shows in the Files window before it takes the
screenshot, and fails if it never does.  "Nothing crashed" looks for new
reports in `/var/crash` and also reads apport's log (`/var/log/apport.log`,
readable by the `adm` group), where apport notes every crash, even one it
writes no report for.  The machine needs the packages the script lists
(Xvfb, a window manager, a tray, xdotool, zenity, gir1.2-atspi-2.0 for
AT-SPI, a terminal and a few more); it names any that are missing.  The
desktop part runs with a throwaway home (HOME with its XDG config, data,
cache and state folders, the autostart folder and aht's home) and a
stand-in `systemctl`, so the desktop someone is logged in to, their home
(autostart entries, settings, recent files, caches), their systemd user
services and the machine's own `~/.aht` are not touched; a check, "the
logged-in user's home was not touched", confirms that their autostart
entries and systemd user units are as they were (changes elsewhere in
`~/.config`, which a logged-in desktop makes all the time, do not count).
At the end it stops what
its private session bus started (the file indexer, gvfs, the accessibility
bus), so nothing it started is left running.

The suites fake every agent's store via `AHT_ROOT_*` env overrides, so they
never touch real agent data; the handover tests use a folder that stands in
for the other machine, and a stand-in `ssh` (`tests/fake_ssh.py`) that can
also answer like a Windows PC.  The handover suite runs once with rsync and
once with aht's own copy (only the latter where rsync 3 is missing);
`tests/core_test.py --transport` runs just aht's own copy, also on Windows,
and `windows/tests/agent_smoke.py` feeds aht's far end (`aht _agent`, from
source or the exe) its copy requests on stdin, with no ssh.
Switching agents runs against stand-in agents (`AHT_CLI_<AGENT>`):
`tests/fake_codex.py` and `tests/fake_kimi.py` write sessions the way the
real CLIs do, Claude Code, Antigravity and Mistral Vibe are stubs that only
note their calls, terminals go to a log (`AHT_TERMINAL_LOG`), and
`tests/fake_agy.py` and `tests/fake_vibe.py` build stand-in Antigravity and
Vibe stores, so no test opens a window or spends a token.  Another agent
on the other machine runs against `tests/fake_tmux.py`, which runs that
agent's window line for real (its output is the window's screen and
activity, keys sent to it go to a file the stand-in Codex reads), so the
board, "went quiet", `--stop` and the catch-up are tested without tmux or
a real agent.  GitHub Actions runs the core suites (Linux and
macOS, Python 3.9 and 3.12), builds the app bundle, and builds and
smoke-tests the Windows exes, the badge cache and the installer (x64 and ARM64) natively on every push; tagging `vX.Y.Z` builds
the release artifacts (Windows installers and zips for x64 and ARM64, the universal
macOS app) and publishes them with checksums.  Honest limits: the
Cursor/OpenCode/Copilot layouts are implemented from best-effort knowledge and
self-verify at runtime (they no-op rather than guess); Antigravity's reader
was checked against one short real conversation (its tool calls and plan
files follow agy's documented format), Mistral Vibe's against one short real
session of two turns (its tool calls and to-dos follow Vibe's own source);
the Linux tray needs a real desktop for full exercise.

## Privacy

aht runs on your computer and sends the author nothing; with its default
settings it makes no network connections.  [PRIVACY.md](PRIVACY.md) lists
what it reads, changes and keeps, what can leave your device once you set
it up, and how to delete all of it.

## License

Copyright (C) 2026 Giray Havur

This program is free software: you can redistribute it and/or modify it
under the terms of the [GNU Affero General Public License](LICENSE) as
published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version.  It is distributed in
the hope that it will be useful, but WITHOUT ANY WARRANTY; without even
the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR
PURPOSE.  See the [license text](LICENSE) for details.

**Commercial licensing available — contact me.**  If the AGPL terms do
not fit how your organization wants to use or redistribute aht, write to
[havurgiray@gmail.com](mailto:havurgiray@gmail.com) for a commercial
license.
