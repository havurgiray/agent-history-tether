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

## Supported agents

| backend | agent CLI | storage model | relink | confidence |
|---|---|---|---|---|
| `claude` | Claude Code | `~/.claude/projects/<encoded-path>` | rename dir | **verified** (+ SessionStart hook backstop) |
| `gemini` | Gemini CLI | `~/.gemini/tmp/<sha256(path)>` | rename dir | high |
| `cursor` | Cursor Agent CLI | `~/.cursor/chats/<hash(path)>` | rename dir | best-effort |
| `opencode` | OpenCode | `$XDG_DATA_HOME/opencode/project/<enc>` | rename dir | best-effort |
| `codex` | OpenAI Codex CLI | `~/.codex/sessions/**/*.jsonl` (cwd inside) | rewrite cwd, **backup-first** | high (layout confirmed on a real install) |
| `copilot` | GitHub Copilot CLI | `~/.copilot/history-session-state/**` | rewrite cwd, **backup-first** | best-effort |
| `kimi` | Kimi Code | `~/.kimi/sessions/<md5(path)>` (+ `user-history/<md5>.jsonl` companion) | rename dir + companion | **verified** (mapped from a real install) |

**Why "best-effort" is still safe:** dir-rename backends are *self-verifying* —
aht only acts when `key(old_path)` names a directory that actually exists,
which proves the key formula matches that tool's reality; otherwise it does
nothing.  Metadata-rewrite backends copy every file they are about to touch
into the backup store first.  Disable any backend with
`aht config --set backends=claude,gemini,…`.

## Install

| platform | how |
|---|---|
| **macOS** (terminal + menu bar tray) | `./install.sh` — compiles the FSEvents watcher, badge tool and tray (needs Xcode CLT), registers the LaunchAgent + Claude hook, installs `aht` |
| **Linux** (terminal + optional tray) | `cd linux && ./install.sh` — systemd user watcher + hook + `aht`; tray: `python3 linux/tray.py` (needs PyGObject + AppIndicator; GNOME also needs the AppIndicator shell extension) |
| **Windows 11** (exe + tray) | build `aht.exe` + `aht-tray.exe` (`cd windows && ./build.sh` via Docker+Wine, or `build_windows.bat` on Windows), then `aht.exe install` |

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
  ▲, opencode orange ■, copilot purple ▬, kimi violet ☾.  **1 agent** → one
  full-size disc (lower right); **2** → two smaller, side by side; **3** →
  three smaller still; **4 or more** → a single slate disc showing the
  *count*.  The git "+" (center) is independent and unaffected.  Rendered as
  composited folder icons on macOS/Windows (the icon files live inside the
  folder, so they travel with it) and as generated per-agent emblems on Linux
  (installed into the user icon theme; ≤3 emblems, a count emblem for 4+ —
  KDE's `.directory` fallback can show only one icon).

## Settings

One shared config (`~/.aht/config.json`) read by the CLI, the watchers, the
hook and all three trays — set with `aht config --set k=v`:

`watch_roots`, `backends`, `backend_roots` (where each CLI's store lives,
for installs not found automatically — set with `aht backends --set-root
name=/path`, or point-and-click via every tray's *Settings ▸ Agent CLI
Locations* page), `move_policy`, `copy_policy`, `new_policy`,
`notifications`, `icons_enabled` / `icons_agent` / `icons_git`,
`debounce_seconds`, `scan_max_depth`, `extra_prune_dirs`, `dialog_timeout`,
`watcher_owner`, `backup_enabled` / `backup_interval_hours` / `backup_keep` /
`backup_dir`, `linux_emblem_method` / `linux_agent_emblem` / `linux_git_emblem`.

Every platform has a tray with the same menu (status, reconcile now,
pause/resume watching, recent projects, adopt with confirmation, the policy /
notification / backup switches, badge controls, diagnostics, autostart
toggle): the compiled menu-bar tray on macOS, `aht-tray.exe` on Windows,
`linux/tray.py` on Linux.

## Safety invariants

1. History is **never deleted or overwritten** — dir renames refuse occupied
   targets (surfaced as conflicts, never merged); metadata rewrites are
   preceded by a mandatory backup copy; restores only add missing files.
2. Adoption is **add-only** and store-corroborated (a backend's store must
   provably exist for the folder's exact path).
3. All registry writes happen under one lock, never held across a dialog;
   folder swaps resolve via two-phase staging per backend.
4. A prompt that cannot be shown (headless) always means **change nothing**.

## Commands

`status` · `doctor` · `adopt` · `reconcile` · `projects` · `orphans --match` ·
`bind` · `prune` · `forget` · `backup` / `backup --list` / `restore` ·
`config` · `roots` / `reload` · `icons --refresh` · `tag` · `keys <path>`
(each backend's store key for a path) · `encode` · `hook` · `version`.
Run `aht` with no arguments for the full help screen; every `--json` output is
a stable machine interface (it's what the trays use).

## Tests

```sh
tests/run_tests.sh        # multi-backend core + Linux layer (any OS, fake stores)
windows/build.sh          # builds the exes, then runs the wine smoke suites
```

The suites fake every agent's store via `AHT_ROOT_*` env overrides, so they
never touch real agent data.  Honest limits: the Cursor/OpenCode/Copilot
layouts are implemented from best-effort knowledge and self-verify at runtime
(they no-op rather than guess); the tray UIs need a real
desktop of each OS for full exercise.
