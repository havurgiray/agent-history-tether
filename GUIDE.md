# aht guide

aht keeps the history of your AI coding agents connected to your project
folders: Claude Code, Kimi Code, Codex, Gemini CLI, Cursor, OpenCode and
Copilot. Once it does that, it can do more with those histories. It can
search them, continue a project in another agent, or hand a project over to
another machine of yours.

This guide goes feature by feature, each with an example. Everything the
window does can also be done with the `aht` command in a terminal; the
command is given with each feature.

## Where to find things

- **The ∞ in the menu bar.** Status at a glance, **Open aht…**, **Guide**,
  **Find Moved Folders Now**, **Pause / Resume Watching** and **Quit**. The
  menu changes nothing on its own, so a stray click is harmless.
- **The window** (∞ → Open aht…) has five tabs: **Projects**, **Sessions**,
  **Search**, **Machines** and **Settings**.
- **In the Projects tab you select a project first, then press a button.**
  Anything that moves or changes files also asks before it starts.

## Folders that move keep their history

Agents file their history under the folder's path. Rename or move a folder,
and the agent starts empty there. aht notices and moves the history along.

> **Example.** You rename `~/Desktop/paper` to `~/Desktop/paper-2026`.
> A dialog asks whether to relink the agent histories; choose **Relink**.
> Open Claude Code in the renamed folder, and `/resume` lists every earlier
> session.

- **Copies:** when you copy a project folder, aht asks whether the copy gets
  its own copy of the history (**Duplicate**) or starts fresh.
- **Missed a move** because aht was not running? ∞ → **Find Moved Folders
  Now**, or `aht reconcile --apply`.
- **Settings → When folders change** decides whether aht asks, relinks on
  its own, or leaves things alone.

## Folder badges

A folder that aht tracks shows small discs on its icon, one per agent that
has history there.

- Claude ✳ coral · Kimi ☾ violet · Codex ○ teal · Gemini ◆ blue ·
  Cursor ▲ black · OpenCode ■ orange · Copilot ▬ purple
- Four agents or more: one disc with the number.
- Grey ∞: tracked, but no agent has history there yet.
- Blue →: the project is handed over to another machine right now.
- A "+" in the middle: a git repository.

## Backups, and bringing a session back

Every day aht zips each project's histories, of all agents, into
`~/.aht/backups` and keeps the ten newest per project.

> **Example.** Claude Code deletes sessions that were idle for 30 days. A
> session from two months ago is no longer in `/resume`. Search for a word
> you remember from it in the **Search** tab. The result says **deleted — in
> a backup**; press **Restore…**. It adds what is missing and changes nothing
> that is there, and the session can be resumed again.

- Command: `aht restore ~/Desktop/paper --apply`
- To stop Claude Code from deleting old sessions at all, set
  `"cleanupPeriodDays": 36500` in `~/.claude/settings.json`.

## Search every session

One search over every session of every agent and project, including sessions
that were deleted since and live on only in a backup.

> **Example.** "Where did we decide how to deploy the API?" Type
> `deploy api` in the **Search** tab. Each result shows the project, the
> agent, when it was, and the matching lines with your words in bold.
> **Resume** opens that session in a new Terminal window; **Show Project**
> jumps to the project.

- Every word has to appear. Put "a phrase" in quotes. The last word may be
  the start of a word: `deplo` also finds deploy and deployment.
- Keys and passwords never reach the search index; they are masked first.
- Commands:

```
aht search deploy api
aht search "rate limit" --agent kimi
aht search migration --project ~/Desktop/paper
```

## Sessions: what runs right now

The **Sessions** tab lists every open agent session on this Mac and on each
machine you added, with its state: **working**, **waiting for you** (and
for what), or **idle**. The menu bar says how many are waiting for you.

> **Example.** You start agents on three projects and go for lunch. Back,
> the Sessions tab shows *paper — waiting for you: approve Bash*; the other
> two are still working. You answer the one that waits.

- Command: `aht board`

## Continue in another agent

Hand a project's work from one agent to another, without losing the thread.

> **Example.** Claude Code tells you that you have reached your usage limit
> in the middle of a task. Select the project → **Switch Agent** →
> **Continue in Kimi Code…**. aht writes a summary of where the Claude
> session stood (the latest exchanges, open to-dos, the files changed) into
> the project. Kimi reads it and opens in a new window, and tells you in
> two or three lines what it understood. Later, switch back the same way:
> Claude reads Kimi's summary.

- The earlier session stays as it was. The summary names the command that
  goes back to it.
- Not possible while an agent is still working in that project.
- Command: `aht switch ~/Desktop/paper --to kimi --apply` (or `--to claude`,
  `--to codex`)

## One set of project rules

Claude Code reads `CLAUDE.md`; Kimi Code and Codex read `AGENTS.md`. Rules
written for one agent are invisible to the others.

> **Example.** Your project has a `CLAUDE.md` that says "use British
> spelling; run the tests with pytest". **More → Project Rules…** says:
> *only CLAUDE.md: Kimi, Codex and the others see no project rules*. Press
> **Make AGENTS.md the One Set of Rules**. The rules move to `AGENTS.md`,
> and `CLAUDE.md` keeps a single line, `@AGENTS.md`, which is how Claude
> Code includes another file. From then on every agent follows the same
> rules, and you edit only `AGENTS.md`.

- When both files exist and say different things, you choose: keep
  CLAUDE.md's, keep AGENTS.md's, or keep both (one after the other).
- The earlier files are kept in `~/.aht/rules-backups`.
- Command: `aht rules ~/Desktop/paper --unify --apply`

## Project journal

A diary of a project, built from all agents' sessions: day by day, newest
first, what you asked, which files changed, and how each day ended.

> **Example.** You come back to a course project after three months.
> **More → Journal** shows what happened when, and in which agent. **Save
> in the Project and Open** keeps it as `.aht/journal/journal.md`, where
> git ignores it.

- Command: `aht journal ~/Desktop/paper --days 30`

## Secrets check

Lists what looks like a key, a token or a password in the agents'
histories. Values are only ever shown masked.

> **Example.** Months ago you pasted an API key into a prompt. **Settings →
> Check All for Secrets…** lists it: the project, what it looks like
> ("Groq API key"), the masked value `gsk_…o8`, where it appeared (your
> message, a tool's output) and when. Replace that key where it was issued.

- For one project: **More → Check for Secrets**.
- aht never changes the agents' histories. It masks such values in
  everything it writes itself: the search index, journals and summaries.
- A handover tells you when such values travel along with a project.
- Command: `aht secrets`, or `aht secrets ~/Desktop/paper`

## Hand a project over to another machine

Your laptop's connection is shaky (a train, a hotel), and a machine at home
has a stable one. Hand the project over, let it run there, and steer it from
the laptop or your phone.

**Once:**

1. **Machines → Add a machine.** Pick one that aht found on your Tailscale
   network or in `~/.ssh/config`, check the `user@host`, and press **Check
   and Add**. aht lists what that machine still lacks, each with the command
   that fixes it and a **Copy** button.
2. On that machine, create your home folder's path once, because a project
   keeps its exact path there:
   `sudo mkdir -p /Users/you && sudo chown $USER /Users/you`

> **Example.** Before you leave, select the paper project → **Hand Over to
> homebox…**. The dialog shows what will be sent. Optionally type a task,
> such as "run the full benchmark and summarise the results", and the
> session starts on it right away. On the train, **Open Session** connects
> to it; with mosh installed on both machines the connection survives
> network changes. Or follow it in the Claude app on your phone and answer
> its questions there.
>
> Back home, **Take Back…** brings the files and the history back. A file
> changed on both machines is kept in both versions, for example
> `notes (from homebox 2026-09-30).md`. Then **Continue the Session**.

- **Nothing moves while something runs:** while an agent works or waits for
  you in the project, or another program runs in the folder, the handover
  waits.
- **Same Claude Code everywhere:** the other machine gets this Mac's exact
  version.
- **Keep in sync:** tick it for a project, and aht copies it in the
  background every 30 minutes, so a handover only sends the last changes.
- **Nothing is lost:** whatever a transfer replaces is set aside first, in
  `~/.aht/handover/<project id>/replaced/`.
- Commands:

```
aht handover ~/Desktop/paper --apply --task "run the benchmark"
aht attach ~/Desktop/paper
aht reclaim ~/Desktop/paper --apply
aht mirror ~/Desktop/paper --on
```

## Settings

- **When folders change:** ask, relink automatically, or leave alone.
- **Histories:** notifications, automatic backups, **Back Up Now**,
  **Check All for Secrets…**
- **Folder badges:** on or off, per kind; **Refresh All**, **Clear All…**
- **Handover:** reachable from the Claude app, compression, mosh, trust
  carried over.
- **Where each agent keeps its history:** point aht at an agent it did not
  find by itself.
- **This Mac:** start aht at login, adopt this Mac's projects, restart the
  watcher, diagnostics, the log.

## Where things are

- `~/.aht/` holds aht's own data: `registry.json` (which folder is which
  project), `config.json`, `backups/`, `search.db`, `aht.log`, `handover/`,
  `rules-backups/`.
- Inside each project, `.aht/.project-id` is the folder's identity; it
  travels with the folder when you move or copy it. `.aht/handover/` and
  `.aht/journal/` hold summaries and journals; git ignores both.

## When something looks wrong

- **Settings → Run Diagnostics** (or `aht doctor`) checks every part.
- macOS says *"badge_icon" Not Opened*: run `aht install` once.
- A machine shows as not reachable: is it switched on, and is Tailscale
  connected on this Mac? When only its name stops working, aht reaches it
  at its Tailscale address by itself.
- The log: **Settings → Open Log**, or `aht logs --errors`.
