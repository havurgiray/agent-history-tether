# aht guide

aht keeps the history of your AI coding agents connected to your project
folders: Claude Code, Kimi Code, Codex, Gemini CLI, Cursor, OpenCode and
Copilot. Once it does that, it can do more with those histories. It can
search them, continue a project in another agent, or hand a project over to
another machine of yours.

This guide shows aht on macOS, with its window. On Linux and Windows the
core works the same, and many features work from the `aht` command; the
README's *Platforms* table says which.

This guide goes feature by feature, each with an example. Everything the
window does can also be done with the `aht` command in a terminal. Each
feature ends with its commands, each followed by what it does in plain
words. A command that changes something shows what it would do first; it
acts only with `--apply`.

## Where to find things

- **The ∞ in the menu bar.** A number next to it counts the sessions that
  wait for you. The menu shows the status (also a project where Claude
  stopped at its usage limit), **Open aht…**, **Guide**, **Search
  Sessions…**, **Find Moved Folders Now**, **Pause / Resume Watching** and
  **Quit**. The menu changes nothing on its own, so a stray click is
  harmless.
- **From anywhere:** ⌃⌥⌘A opens the search. **In Finder**, right-click a
  project folder: under **Quick Actions** (or **Services**) are *aht: Show in
  aht*, *What Changed*, *Journal*, *Search This Project* and *Continue in
  Another Agent*.
- **The window** (∞ → Open aht…) has five tabs: **Projects**, **Sessions**,
  **Search**, **Machines** and **Settings**.
- **The ? buttons.** A **?** next to a feature opens this guide at its
  section. The **?** at the top of the window opens the whole guide, with
  every section in a list: also *All settings, one by one* and *Only in the
  terminal*, for what has no button.
- **In the Projects tab you select a project first, then press a button.**
  Anything that moves or changes files also asks before it starts.
- **Spotlight** finds your sessions by title, and **aht:// links** open
  parts of the window from the Shortcuts app or a script (see *Spotlight,
  Shortcuts and links*).

## What uses tokens

aht's own work never uses an agent's tokens: watching folders, badges,
backups, search, the Sessions tab, notices, loose ends, reports, the
journal, the secrets check, *What Changed*, *Undo a Session* and Spotlight
all run on this Mac without asking any model.

A few features make an agent read or work, and that counts against your
plan or API bill. They are **off until you turn them on**, in **Settings →
Uses tokens**, or when you first use them:

- **A new session learns where the last one stopped:** a few hundred tokens
  per new Claude Code session.
- **Offer another agent at the usage limit:** when you accept, the other
  agent reads a summary.
- **Second opinion:** two agents work on the same task.
- **Night shift:** the agent on your other machine works on your task.
- **Going on by itself after the usage limit** (Claude Code's own setting,
  switched in the same group): the session works on when the limit resets.

Two more spend tokens only when you ask for them, each time: **Switch
Agent** (the new agent reads a summary) and **Hand Over** with a task (the
session starts on it). A handed-over project also puts one sentence into a
new Claude session in its folder, so the session knows the project is away
or has just come back.

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
  Now**.
- **Settings → When folders change** decides whether aht asks, relinks on
  its own, or leaves things alone.

**In the terminal:**

- `aht reconcile` — look for folders that moved or were copied and say what
  it would relink, without changing anything.
- `aht reconcile --notify` — act the way Settings say, asking where they
  say "Ask me" (what **Find Moved Folders** does).
- `aht reconcile --apply` — act without asking: relink moved folders, give
  copies their own history, track new projects.
- `aht reconcile --only ~/Desktop/paper-2026 --apply` — look at that folder
  only.
- `aht reconcile --notify --copies independent` — this once, treat copies
  differently from Settings (`--moves` and `--news` work the same way).
- `aht reconcile --clear-declines` — forget the moves you said no to, so aht
  asks about them again.
- `aht projects` — list every folder aht tracks, with its agents and how
  much history it has.
- `aht status` — a short summary: how many projects, whether the watcher
  and the Claude hook are running.

## Folder badges

A folder that aht tracks shows small discs on its icon, one per agent that
has history there.

- Claude ✳ coral · Kimi ☾ violet · Codex ○ teal · Gemini ◆ blue ·
  Cursor ▲ black · OpenCode ■ orange · Copilot ▬ purple
- Four agents or more: one disc with the number.
- Grey ∞: tracked, but no agent has history there yet.
- Blue →: the project is handed over to another machine right now.
- A "+" in the middle: a git repository.

**In the terminal:**

- `aht icons --refresh` — redraw the badges of every folder, for example
  after you turned a kind of badge off.

## Backups, and bringing a session back

Every day aht zips each project's histories, of all agents, into
`~/.aht/backups` and keeps the ten newest per project.

> **Example.** Claude Code deletes sessions that were idle for 30 days. A
> session from two months ago is no longer in `/resume`. Search for a word
> you remember from it in the **Search** tab. The result says **deleted — in
> a backup**; press **Restore…**. It adds what is missing and changes nothing
> that is there, and the session can be resumed again.

- To stop Claude Code from deleting old sessions at all, set
  `"cleanupPeriodDays": 36500` in `~/.claude/settings.json`.
- **A second copy on another machine.** **Settings → Backups on another
  machine**: pick one of your machines, and after each daily backup aht
  copies the backups there too, so a lost or broken Mac does not take the
  histories with it.

**In the terminal:**

- `aht backup` — back up every project's histories now, instead of waiting
  for the daily run.
- `aht backup --list` — list the backups that are kept, per project.
- `aht restore ~/Desktop/paper` — show what the newest backup of the paper
  project would add back.
- `aht restore ~/Desktop/paper --apply` — add it back: sessions that are
  missing return, nothing that is there is changed.
- `aht restore ~/Desktop/paper --stamp 20260901-120000 --apply` — use that
  older backup instead (the stamps are in `aht backup --list`).
- `aht backup --project ~/Desktop/paper` — back up one project only.
- `aht backup --prune` — delete the backups beyond the number kept
  (`backup_keep`, 10).
- `aht backup --offsite` — copy the backups to your other machine now.
- `aht backup --fetch-offsite` — on a new Mac, bring the backups back from
  that machine.

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

**In the terminal:**

- `aht search deploy api` — find the sessions in which both "deploy" and
  "api" appear, in every project and agent.
- `aht search "rate limit" --agent kimi` — find that exact phrase, only in
  Kimi Code's sessions.
- `aht search migration --project ~/Desktop/paper` — search one project
  only.
- `aht search deploy --limit 50` — show up to 50 results (20 otherwise).
- `aht search --rebuild` — build the search index anew, for example after
  restoring many sessions.

## Sessions: what runs right now

The **Sessions** tab lists every open agent session on this Mac and on each
machine you added, with its state: **working**, **waiting for you** (and
for what), or **idle**, and under each Claude session its name (see
*Session names from your iTerm2 tabs*). The menu bar says how many are
waiting for you.

> **Example.** You start agents on three projects and go for lunch. Back,
> the Sessions tab shows *paper — waiting for you: approve Bash*; the other
> two are still working. You answer the one that waits.

**In the terminal:**

- **Go to Tab** brings the iTerm2 tab of that session to the front.
- **Open twice:** the same conversation runs in two processes, which both
  write to it. **End It…** closes one.
- **Working for hours, nothing written:** probably a leftover. **End It…**
- **Not in the Claude app:** it started before Remote Control was on for
  every session.
- **Older Claude Code:** it still runs the version it started with.
- **Restart in Its Tab…** ends such a session (when it is idle or stuck)
  and starts it again in the same tab, where it left off and with the
  options it had (permissions, model, effort, extra folders). It then runs
  the installed Claude Code and shows in the Claude app. Text typed into it
  but not sent is lost.
- Ending a session keeps its conversation: `claude --resume` continues it.
- A session stopped at **Claude's usage limit** says when the limit resets,
  and *continues by itself then* when Claude Code's own setting for that
  is on (see *Continue in another agent*).

**In the terminal:**

- `aht board` — list the open agent sessions on this Mac and on your other
  machines, and whether each one is working, waiting for you or idle.
- `aht board --local` — the same for this Mac only (quicker).
- `aht goto ~/Desktop/paper` — bring the tab of the paper project's
  session to the front (a session id or a process id works too).
- `aht checkup` — list the open Claude sessions worth a look, and why.
- `aht checkup --restart <pid> --apply` — end that session and start it
  again in its tab; `--close <pid> --apply` only ends it.

## Loose ends

Projects of the last 30 days with something left open: work not
committed, open to-do items, or a last session that ended by asking you
something or offering a next step. **Projects → Look Back → Loose Ends…**

> **Example.** Monday morning, Loose Ends lists three projects: *paper — ?
> Want me to draft the two mails to the co-authors?*, *site — 4 file(s) not
> committed*, and *thesis — → say the word and I'll rename the figures*.
> **Continue** opens that session in a new window, right where it stopped.

- Nothing is sent anywhere and no agent is asked: aht reads the end of each
  project's latest session and runs `git status`.

**In the terminal:**

- `aht loose-ends` — list the projects of the last 30 days that have
  something left open.
- `aht loose-ends --days 7` — the same for the last week only.

## Know when a session needs you

aht checks the open sessions every 30 seconds, here and on the machines you
added, and tells you when one starts **waiting for you** or **finishes** a
piece of work that took a while.

> **Example.** You hand a benchmark over to your machine at home and go into
> a meeting. Half an hour later a notice says *paper on homebox waits for
> you: approve Bash*. With **Also send them to my phone** set, it arrives on
> your phone too.

- **A click on a notice** brings the tab of that session to the front (a
  session on another machine opens the Sessions tab). The first time, macOS
  asks whether aht may show notifications; allow it. Without the aht app
  running, aht starts it briefly to show the notice, so a click never opens
  Script Editor.
- **Settings → Notices:** choose which notices you want. For the phone,
  enter `imessage:` followed by your own number or Apple ID (it arrives as a
  message to yourself), or `ntfy:` followed by a topic you follow in the
  free ntfy app. **Send a Test** shows how it looks.
- **Claude's usage limit:** when a session stops because the limit is
  reached, a notice says so, with the time it resets (Settings → Safety
  nets → *Tell me when Claude stops at its usage limit*).
- **Sessions in the corner:** a small list in the screen's top-right
  corner shows every open Claude session on this Mac: **working** (blue),
  **waiting for you** (orange) or **done** (green), with how long it has
  been so, under the name the Claude app shows. The sessions working now
  come first, the one that started last on top; the rest follow by when
  they last worked. *Done* stays until you click that session there, which
  brings its tab to the front, or until it starts working again. Turn it
  on or off in the aht menu (*Sessions in the Corner*) or in Settings →
  Notices; the × on the list turns it off too. It reads Claude Code's own
  records of its sessions every second and a half, so it needs no tokens
  and hardly any time.

**In the terminal:**

- `aht notices --test` — send a sample notice, to this Mac and to your phone
  if one is set.
- `aht limits` — list the sessions that stopped at Claude's usage limit in
  the last 12 hours, and when the limit resets.
- `aht limits --hours 48` — look back two days instead.

## Every session starts informed (uses tokens, off by default)

A new Claude Code session in a folder learns, in a few lines, where the
last session there stopped, whichever agent ran it: the last request, the
last answer, open to-dos and the files changed last.

> **Example.** Yesterday Kimi Code worked on the parser in `~/Desktop/paper`.
> Today you start Claude Code there and type "go on with the tests". Claude
> already knows that Kimi's last step was the lexer and that "write the
> tests" is still open.

- **Off until you turn it on** (Settings → Uses tokens), because those
  lines go into the session's context: a few hundred tokens per new
  session. A resumed session gets nothing; it has its own history.
- Keys and passwords are masked in the note, as everywhere aht writes.
- Only Claude Code has a start hook, so only its new sessions get the note.

**In the terminal:**

- `aht config --set informed_sessions=true` — turn it on.
- `aht config --set informed_sessions=false` — turn it off again.

## What did a session change?

Every file an agent edited in a Claude Code session, from how it looked
before the session touched it to how it looks now, line by line.

> **Example.** You let Claude refactor a module overnight. **More → What
> Changed…** lists the files it edited with lines added and removed; pick one
> to see the changes in red and green. One edit went wrong: **Put Back** that
> file as it was before the session. What it held a moment ago is kept in
> `~/.aht/changes-backups`.

- It uses Claude Code's own `/rewind` checkpoints, so it covers the files
  Claude edited with its tools; files changed by commands it ran are not in
  there.

**In the terminal:**

- `aht changes ~/Desktop/paper` — list the files the latest Claude Code
  session in the paper project edited.
- `aht changes ~/Desktop/paper --diff` — the same, with every changed line.
- `aht changes ~/Desktop/paper --session <id>` — an earlier session instead
  of the latest.
- `aht changes ~/Desktop/paper --all` — also the files outside the project
  that the session edited.
- `aht changes ~/Desktop/paper --revert ~/Desktop/paper/a.py --apply` — put
  `a.py` back as it was before the session; what it holds now is kept
  aside.

## Undo a whole session

When a Claude Code session starts, aht makes a copy of the project folder.
If the session goes wrong, put the whole folder back as it was, including
what the session's commands changed.

> **Example.** You let an agent "clean up the build scripts". It deleted two
> folders and rewrote a dozen files. **More → Undo a Session…** shows every
> file that differs from the copy at the start: changed, removed, made
> since. **Put Everything Back…** restores the folder. What it held a moment
> ago goes to `~/.aht/undo/`, so the undo can itself be undone.

- The copies are copy-on-write: they take no room until a file changes.
  The last 10 per project are kept, none older than 30 days.
- Left out, because they are rebuilt or have their own history:
  `node_modules`, `.venv`, `__pycache__` and the like, and `.git`.
- **Big folders.** A project with more than 20,000 files gets no copy.
  You can change that number in Settings → Safety nets; aht then tells you
  which projects are over it and which of their folders hold most files.
  You can also leave such folders out of the copies (for example
  `results` or `datasets`), so the rest of the project is covered.
- **Why a limit at all:** the copy of a big folder takes no room for the
  data, but it still costs. Measured on a Mac with a 98,000-file project:
  about 17 seconds of disk work at every session start (in the background),
  about 100 MB of file-system entries per kept copy, and about 5 seconds each
  to compare for an undo and to delete an old copy. With 10 copies kept,
  that is a million extra file entries for one project.
- Time Machine leaves the copies out. It would otherwise store each one in
  full.
- aht also makes one before another agent takes over (*Switch Agent*).
- Not while an agent is working in the project.
- Settings → Safety nets → *Copy the folder when a session starts*.

**In the terminal:**

- `aht undo ~/Desktop/paper` — show which files differ from the copy made
  when the latest session started, without changing anything.
- `aht undo ~/Desktop/paper --apply` — put the folder back as it was then.
- `aht undo ~/Desktop/paper --list` — list the copies kept of this folder,
  with the session each one belongs to.
- `aht undo ~/Desktop/paper --checkpoint <id> --apply` — go back to an older
  copy from that list instead.
- `aht undo ~/Desktop/paper --session <id> --apply` — undo everything since
  that session first started, however often it was resumed.
- `aht checkpoint ~/Desktop/paper` — make a copy now, for example before you
  try something risky by hand.
- `aht checkpoint --coverage` — count the files of every project and say
  which ones are over the limit, with their biggest folders.
- `aht checkpoint --coverage --max 100000` — the same for another limit, to
  try it before you change it.
- `aht config --set checkpoint_max_files=100000` — change the limit.
- `aht config --set checkpoint_excludes=results,datasets` — leave folders
  with these names out of the copies.
- `aht checkpoint --coverage --top 40` — list 40 projects instead of 15.

## Continue in another agent

Hand a project's work from one agent to another, without losing the thread.

> **Example.** Claude Code tells you that you have reached your usage limit
> in the middle of a task. Select the project → **Switch Agent** →
> **Continue in Kimi Code…** (or the button under the project, see below).
> aht writes a summary of where the Claude session stood (the latest
> exchanges, open to-dos, the files changed) into the project. Kimi reads it and opens in a new window, and tells you in
> two or three lines what it understood. Later, switch back the same way:
> Claude reads Kimi's summary.

- The earlier session stays as it was. The summary names the command that
  goes back to it.
- Not possible while an agent is still working in that project.
- Uses tokens: the new agent reads the summary. It happens only when you
  press the button.
- **Going on by itself:** Claude Code has its own setting to continue a
  session by itself once the limit resets. Settings → Uses tokens → *When
  Claude's usage limit resets, the session continues by itself* switches it
  (it is Claude Code's setting, `autoContinueAtUsageLimit`, and it uses
  tokens, since the session works on). The notice and the Sessions tab then
  say *continues by itself then*.
- **At Claude's usage limit:** the project shows *Claude stopped at its
  usage limit; it resets 6:20pm*. With Settings → Uses tokens → *When
  Claude stops at its limit, offer to go on in Kimi Code* turned on, a
  **Continue in Kimi Code…** button sits right next to it, and the notice
  says so too. aht spots the limit in the session's history; that costs
  nothing.

**In the terminal:**

- `aht limits --auto-continue on` — sessions go on by themselves when the
  limit resets (`off`: they wait for you).
- `aht switch ~/Desktop/paper --to kimi` — say which session Kimi Code
  would continue, without starting anything.
- `aht switch ~/Desktop/paper --to kimi --apply` — do it: write the summary
  and open Kimi Code on it (`--to claude` and `--to codex` work the same
  way).
- `aht switch ~/Desktop/paper --to claude --session <id> --apply` —
  continue that session rather than the latest one of the other agent.
- `aht switch ~/Desktop/paper --to kimi --no-window --apply` — prepare
  everything and print the command, without opening a window.

## A second opinion (uses tokens, off by default)

Give Claude Code and Kimi Code the same task, each in its own copy of the
project, and compare what they did before you keep one.

> **Example.** "Make the parser accept empty lines." **More → Second
> Opinion…**, type the task, **Start**. A few minutes later a notice says
> both are done. The sheet shows each agent's answer and its changes side by
> side: Claude changed one file, Kimi two and added a test. **Use Kimi
> Code's Changes…** brings Kimi's version into the project.

- **Off until you turn it on:** both agents work, so both use tokens.
  The first time you open it, aht asks.
- The project is not touched until you pick a version. If a file changed in
  the project meanwhile, aht does not overwrite it.
- Claude may edit files in its copy but not run commands. Kimi's
  non-interactive mode also runs commands it decides on (for example, it
  runs the code to check its change), so give it only tasks you would let
  it do in the project itself.
- **Remove the Copies…** clears a finished comparison.

**In the terminal:**

- `aht second-opinion ~/Desktop/paper --task "make the parser accept empty
  lines"` — start both agents on that task, each in its own copy.
- `aht second-opinion --list` — list the comparisons and whether each agent
  is still working.
- `aht second-opinion --show <id> --diff` — show each agent's answer and
  every line it changed.
- `aht second-opinion --take <id> --from kimi --apply` — bring Kimi Code's
  changes into the project.
- `aht second-opinion --discard <id>` — remove the two copies.
- `--agents claude,kimi` names the two agents; these two are the ones that
  work today, and they are the default.

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

**In the terminal:**

- `aht rules ~/Desktop/paper` — say which rules file each agent reads in
  the paper project.
- `aht rules ~/Desktop/paper --unify --apply` — make `AGENTS.md` the one set
  of rules, with `CLAUDE.md` pointing to it.
- `aht rules ~/Desktop/paper --unify --prefer both --apply` — when both
  files exist and differ: keep both texts, one after the other
  (`--prefer claude` or `--prefer agents` keeps only that file's).

## Project journal

A diary of a project, built from all agents' sessions: day by day, newest
first, what you asked, which files changed, and how each day ended.

> **Example.** You come back to a course project after three months.
> **More → Journal** shows what happened when, and in which agent. **Save
> in the Project and Open** keeps it as `.aht/journal/journal.md`, where
> git ignores it.

**In the terminal:**

- `aht journal ~/Desktop/paper --days 30` — print the paper project's
  journal for the last 30 days.
- `aht journal ~/Desktop/paper --write` — save it in the project as
  `.aht/journal/journal.md`.

## Reports and an AI-use statement

How much you worked with each agent, per project, per agent or per area of
work, and a draft of the paragraph that papers and theses now ask for.

> **Example.** Your timesheet asks how the week split between two employers.
> **Projects → Report…**, *This week*, *by area*: each area's hours and
> sessions. Areas are folders you name once, for example
> `aht config --set report_areas='{"Work A": "~/Desktop/Workspace/A", "Work B": "~/Desktop/Workspace/B"}'`.
>
> Submitting a paper: **More → AI-Use Statement** writes a draft such as
> "AI coding assistants were used in this work in September 2026: Claude Code
> (4 sessions, about 12 h of active use) … They were used for tasks such as
> …". Check it before you use it.

- **Session time** counts the stretches in which a session was active; a
  pause of more than 15 minutes is left out, and sessions that ran side by
  side add up.

**In the terminal:**

- `aht report --since week --by agent` — this week's sessions and hours,
  per agent (`--by project` or `--by area` to split it differently).
- `aht report --since 2026-09-01 --until 2026-09-30` — the same for a range
  of days.
- `aht report --project ~/Desktop/paper --statement` — write a draft AI-use
  statement for the paper project.

## Share a session

A session as a clean page for a colleague, a student or a paper's appendix.

> **Example.** A student asks how you set up the experiment scripts. **More
> → Share a Session…** saves the latest session as a web page: your messages
> and the agent's replies, without keys, passwords, e-mail addresses or
> your Mac's paths and names.

- Look through the page before you pass it on: names in the conversation
  itself, such as a repository, stay.
**In the terminal:**

- `aht share ~/Desktop/paper --format html --out session.html` — save the
  paper project's latest session as a clean web page.
- `aht share ~/Desktop/paper --format md` — print it as Markdown instead.
- `aht share ~/Desktop/paper --session <id> --agent kimi` — an earlier
  session, or one of another agent.
- `aht share ~/Desktop/paper --tools` — also list the tools the agent used.

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
- **Take one out:** **Remove…** next to a find replaces it with
  `[removed by aht]` in every history file that holds it. The files are
  copied to `~/.aht/redacted` first, and it waits until no agent session is
  open in those projects. Backups still hold the old files, so replace the
  key where it was issued anyway.

**In the terminal:**

- `aht secrets` — list what looks like a key or password in every
  project's histories, masked.
- `aht secrets ~/Desktop/paper` — the same for one project.
- `aht secrets --redact <fingerprint>` — say in how many places and history
  files one of those finds appears, without changing anything (the
  fingerprint is in the list).
- `aht secrets --redact <fingerprint> --apply` — replace it in every history
  file that holds it.

## Tidy up

Folders aht tracked that are gone, and histories no tracked folder owns,
with suggestions. **Projects → Tidy Up…** appears when there is something.

> **Example.** You moved `~/Desktop/debug` into a projects folder while aht
> was not running. Tidy Up lists it as *Folder gone* and suggests the folder
> of that name it found; **Reconnect** moves the history along. A folder you
> deleted on purpose: **Forget** stops tracking it; its history stays and
> can be restored later. A history whose folder is gone for good:
> **Remove…** moves it to the Trash, where *Put Back* still brings it back.

- Each entry says how many sessions it holds, how big it is, when it was
  last used and the title of its latest session. **Read…** shows its
  conversations as text (the last 40 messages of each session, keys
  masked), so you can decide; **Show in Finder** opens the history's own
  folder.

**In the terminal:**

- `aht tidy` — list gone folders and histories without a folder, with
  suggestions.
- `aht tidy --relink <id> --to ~/Desktop/Projects/debug --apply` — connect
  a gone project's history to the folder where it is now.
- `aht forget --uuid <id> --apply` — stop tracking a folder you deleted on
  purpose; its history stays.
- `aht tidy --show=<name or id>` — a listed history as text to read (the
  name or the project id is in the `aht tidy` list).
- `aht tidy --remove-history=<name> --apply` — move a history without a
  folder to the Trash (the name is in the `aht tidy` list; write it with
  `=`, because it begins with a dash). Never one that a tracked project owns
  or an open session uses; the daily backups keep it as well.

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
- **Every project at once:** Machines → **Sync** → *Keep All Projects in
  Sync…*. aht first adds up what the first copy sends (projects inside
  another project travel with it; rebuilt folders such as `node_modules`
  stay behind) and asks. The first copy runs in the background and can
  take hours for tens of gigabytes; after that only changes travel.
- **Nothing is lost:** whatever a transfer replaces is set aside first, in
  `~/.aht/handover/<project id>/replaced/`.

**In the terminal:**

- `aht remote discover` — list the machines aht can find on your Tailscale
  network and in `~/.ssh/config`.
- `aht remote add homebox you@homebox` — add one under the name homebox.
- `aht remote check homebox` — check what that machine still lacks.
- `aht handover ~/Desktop/paper` — show what would be sent and what stands
  in the way, without sending anything.
- `aht handover ~/Desktop/paper --apply --task "run the benchmark"` — hand
  the project over and start the session there on that task.
- `aht handover ~/Desktop/paper --session <id> --apply` — resume that
  session there instead of the latest.
- `aht handover ~/Desktop/paper --include ~/notes/paper.md --apply` — take
  a file or folder from outside the project along (remembered for the
  project).
- `aht handover ~/Desktop/paper --no-start --apply` — send it without
  starting the session; `--attach` opens the session in this terminal right
  after.
- `aht handover ~/Desktop/paper --allow-processes --apply` — go ahead
  although another program (not an agent) runs in the folder; it stays
  behind.
- `aht attach ~/Desktop/paper` — open the session running on the other
  machine, in this terminal.
- `aht reclaim ~/Desktop/paper --apply` — take the project back: its files
  and history return to this Mac.
- `aht reclaim ~/Desktop/paper --stop --apply` — end the session over there
  first, if it is idle.
- `aht reclaim ~/Desktop/paper --prefer there --apply` — for files changed on
  both machines, take theirs and keep ours aside (the default, `here`, is
  the other way round).
- `aht reclaim ~/Desktop/paper --ignore-version --apply` — take it back even
  though the other machine's Claude Code is newer.
- `aht attach ~/Desktop/paper --window` — open the session over there in a
  new terminal window; `--print` only shows the command.
- `aht resume-here ~/Desktop/paper` — continue the project's latest session
  in a new terminal window here; `--handed-over` picks the session the last
  handover sent, `--session <id>` any other.
- `aht mirror ~/Desktop/paper --on` — keep a copy of the project on the
  other machine, updated every 30 minutes.
- `aht mirror ~/Desktop/paper --off` — stop that; `aht mirror --run` syncs
  every kept copy now.
- `aht mirror --all --on --to homebox` — show what keeping every project in
  sync with homebox would send; `--apply` does it. `aht mirror --all --off
  --apply` stops it for all of them.
- `aht remote default homebox` — make homebox the machine the window uses;
  `aht remote remove homebox` forgets it; `aht remote check all` checks every
  machine.

## The night shift (uses tokens, off by default)

Plan a handover with a task for the evening, and aht takes the project back
in the morning.

> **Example.** At 6 pm: **More → Night Shift…**, task "run the full
> benchmark and write the results into RESULTS.md", start 22:00, take back
> 07:00, **Plan It**. At ten the project goes to homebox and the session
> starts on the task. At seven aht takes it back as soon as the session
> there is done; a notice tells you it is back. **What Changed** and the
> journal show what happened overnight.

- **Off until you turn it on:** the agent on the other machine works on
  your task, which uses your tokens.
- This Mac has to be awake at both times (a Mac asleep at the start time
  skips that night shift and tells you). If the session is still working
  at the take-back time, aht waits and tries again every five minutes.
- **Cancel** stops a planned night shift; one that has started stays on the
  other machine until you take it back.

**In the terminal:**

- `aht night-shift ~/Desktop/paper --task "run the full benchmark" --start
  22:00 --back 07:00 --apply` — hand the paper project over at ten tonight
  with that task, and take it back from seven in the morning.
- `aht night-shift --list` — list the planned and past night shifts.
- `aht night-shift --cancel <id>` — cancel one.

## Restore my workspace

Your iTerm2 windows and tabs, their titles, colours and the Claude sessions
in them, back after a restart or a macOS update, each session where it left
off.

> **Example.** You work with a dozen titled tabs: *Paper*, *Server*,
> *Slides* … macOS restarts for an update. Afterwards: Sessions tab →
> **Restore Workspace…**. aht offers the workspace as it was before iTerm2
> last started, and lists what it opens. **Open Them**: a window with the
> same tabs, titled and coloured as before, each resuming its session with
> the options it was started with. iTerm2 does not need to be open first.

- **Saving is automatic.** While the aht app runs and iTerm2 is open, aht
  looks at the layout every 10 minutes, and also when a session gets a
  prompt. A layout that did not change is not saved again; its "last seen"
  time moves on. **Save Now** in the same sheet keeps it at once. The last
  40 layouts are kept; click one on the left to see what it would open.
  Settings → Restore my workspace changes both numbers.
- **What opens:** every Claude session that is not open now (resumed by its
  id, with the options it had — permissions, model, effort, extra folders,
  never a first prompt again), Kimi Code with its last session in that
  folder, and every titled tab with its folder. Untitled plain tabs, tabs
  open now and folders that are gone are skipped.
- **Tab titles:** iTerm2 does not let a script set the title you set with
  *Edit Tab Title*, so aht sets it the way a program does and keeps Claude
  Code from writing over it in those tabs. Session names stay as they were.
- **Tab colours and profiles:** each tab opens with the iTerm2 profile it
  had (the default one if that profile is gone) and its tab colour. A
  script cannot ask iTerm2 for a tab's colour, so aht reads it from
  iTerm2's own saved window state, which iTerm2 writes every few minutes:
  a colour you set just now is in the next save after that.
- **iTerm2 closed?** Open Them starts it, waits until it is ready, and puts
  the first tab into the empty window iTerm2 opens as it starts. Tabs that
  iTerm2 brought back by itself are not opened twice, and neither are tabs
  from a second click on Open Them.
- The first time, macOS asks whether aht may control iTerm2; allow it.

**In the terminal:**

- `aht workspace` — list the saved layouts, with their tabs and sessions.
- `aht workspace --save` — save the layout now.
- `aht workspace --save --auto` — save it if `workspace_save_minutes` have
  passed since the last time (what the app does every minute).
- `aht workspace --restore` — show what opening the layout from before
  iTerm2 last started would open; `--apply` opens it.
- `aht workspace --restore <id> --apply` — open an older layout from the
  list.

## Session names from your iTerm2 tabs

You name your iTerm2 tabs; aht gives each Claude Code session its tab's
title as its name. The name shows in the Claude app on your phone, in
`/resume` and in the session's prompt bar, so you recognise a session at a
glance when you steer it from the phone.

> **Example.** Your tabs are called *Paper*, *Server* and *Slides*. On the
> phone, the Claude app lists three sessions called Paper, Server and
> Slides instead of "myhost-graceful-unicorn" and friends. You rename the
> *Paper* tab to *Paper review*; after your next message in that session,
> the app says *Paper review* too.

- **When:** a session gets the name when it starts. After you rename a
  tab, the session follows at your next prompt (from the Mac or the phone):
  aht looks at that tab right then, which takes about a fifth of a second.
- **Two sessions, one title:** a second open session under the same tab
  title (another tab, a split pane, the original next to its branch)
  becomes *Paper · 2*. A branch (`/branch`) that is open next to its
  original becomes *Paper ⑂ 2*.
- **The latest name wins, both ways:** rename the tab and the session
  follows. Rename the session yourself (`/rename`, in the Claude app, or
  **Rename…** in the Sessions tab) and its tab takes the name: at once from
  aht's window, otherwise at the session's next prompt. If both were renamed
  since that session's last prompt, the tab's title wins.
- **For the tab to take a name, switch on iTerm2's Python API:** iTerm2 →
  Settings → General → Magic → *Enable Python API*. iTerm2 lets no script
  change a title you gave a tab; its Python API can, the same way *Edit Tab
  Title* does. aht asks iTerm2 for a one-time key each time (over
  AppleScript, which aht may use already), so you won't see a prompt. With
  the API off, the tab keeps its title and the session its name; the
  Sessions tab and Settings say so. A tab that holds more than one session
  (split panes) keeps its title, since that title would name them all.
- **Handed over:** on your other machine a session is called
  *Paper @ homebox*, so you can tell it from one on this Mac.
- **See and change the names** in the **Sessions** tab: under each Claude
  session its name, where the name came from (*from its tab*, *named by
  you*, *named in aht*, *Claude's own title*) and the tab's title.
  **Rename…** gives a session a name of your choice and gives its tab that
  name too. It stays until you rename the tab, or until **Follow the Tab
  Again**.
- **Name Sessions After Their Tabs…** (Sessions tab, when iTerm2 is
  installed) gives every open session its tab's title at once, also the ones
  you named yourself. It shows the list of changes first.
- **When a new name arrives:** Claude Code takes a name from outside only
  through its hooks, so a name set in aht arrives with the session's next
  prompt, from the Mac or the phone. Until then the Sessions tab shows it as
  *→ “name” at its next prompt*.
- The first time aht asks iTerm2 for its tabs from the window, macOS asks
  whether aht may control iTerm2; say OK, it only reads the tab titles.
- Only a title you set on the tab counts (double-click the tab, or *Edit
  Tab Title*), not what a program writes into it. A tab without one leaves
  the session's name alone.
- For the sessions to be in the app at all, turn on Remote Control for all
  sessions in Claude Code: `/config` → *Enable Remote Control for all
  sessions*. Sessions that were open before you updated aht take the names
  once you start or resume them again.
- No tokens: the name is not part of the conversation.
- Settings → The Claude app on your phone → *Name each Claude session after
  its iTerm2 tab*.

**In the terminal:**

- `aht tab-names` — list the open Claude sessions with their tab's title,
  their name, where the name came from, and whether they are in the Claude
  app (`--fresh` asks iTerm2 now instead of using its last look).
- `aht tab-names --rename <session id> --to "Paper review"` — give an open
  session that name, at its next prompt, and its tab right away; `--to ""`
  lets it follow its tab again.
- `aht tab-names --sync-all` — show which sessions would take their tab's
  title; `--apply` does it, at each one's next prompt.
- `aht config --set tab_names=false` — stop naming sessions after their
  tabs.

## Spotlight, Shortcuts and links

- **Spotlight:** press ⌘Space and type part of a session's title, such as
  "parser". The session shows up with its agent and project; pick it, and
  aht offers to continue it in a new terminal window. Only titles, project
  names and dates go into the index, and it stays on this Mac. Settings →
  Safety nets → *Show sessions in Spotlight*.
- **Links:** `aht://…` opens a part of the window. In the Shortcuts app, use
  the *Open URLs* action; in a script, `open "aht://…"`. A link opens a
  sheet or a question; whatever starts an agent or changes files asks you
  first.
- The links: `aht://search?q=parser`, `aht://sessions`, `aht://loose-ends`,
  `aht://report`, `aht://project?path=~/Desktop/paper` (and in the same form
  `changes`, `journal` and `undo`), `aht://switch?path=~/Desktop/paper&to=kimi`
  and `aht://resume?path=~/Desktop/paper&session=<id>`.
- For everything else, the Shortcuts action *Run Shell Script* can call the
  `aht` command.

**In the terminal:**

- `open "aht://search?q=parser"` — open the window's search with that word.
- `aht sessions` — list every session aht knows, newest first, with its
  title (what Spotlight gets).
- `aht sessions --limit 50` — only the newest 50.

## The window at a glance

Every part of the window, and where this guide explains it. A **?** next to
a part opens its section; the **?** at the top opens the whole guide.

- **Projects tab, top row:** a search field over the project list; the
  machine projects are handed over to (a menu when you added several);
  **Sync Now** (copies every project you keep in sync to that machine now);
  **Find Moved Folders**; **Look Back** with *Loose Ends…* and *Report…*;
  **Tidy Up (n)…** when something needs a decision (with **Choose
  Folder…**, **Reconnect**, **Forget** and, for a history without a folder,
  **Remove…**).
- **The project list:** *Where* (here, handed over, missing, a session open,
  working or waiting for you), *In sync* (when the kept copy was last
  synced), *Last used*, *Agents* (whose history it has).
- **Under the list, for the selected project:** **Hand Over…** or, while it
  is away, **Take Back…** and **Open Session**; **Keep in sync**;
  **Continue Session** (opens the latest session in a new terminal window);
  **Switch Agent**; **More**, with *What Changed…*, *Undo a Session…*,
  *Journal*, *AI-Use Statement*, *Share a Session…*, *Project Rules…*,
  *Check for Secrets*, *Second Opinion…*, *Night Shift…* and *Show in
  Finder*. Notes about the project, such as the usage limit, appear below.
- **Sessions tab:** the open sessions here and on your other machines,
  with each Claude session's name and **Rename…**, **Go to Tab**, and for
  one worth a look **Restart in Its Tab…** or **End It…**; at the top
  **Restore Workspace…**, **Name Sessions After Their Tabs…** and
  **Refresh**.
- **Search tab:** the search over all sessions; *Resume*, *Restore…* and
  *Show Project* on each result.
- **Machines tab:** the machines you added, with **Sync** (keep every
  project in sync with it, or stop), **Check**, **Use for Handover** and
  **Remove…**; **Add Another…**; machines aht found on your
  Tailscale network or in `~/.ssh/config`, each with **Add…**.
- **Settings tab:** see *Settings* below.
- **The bottom line:** what aht is doing right now (with a progress bar for
  transfers) and its version.

## Settings

- **When folders change:** ask, relink automatically, or leave alone.
- **Histories:** notifications, automatic backups, **Back Up Now**,
  **Check All for Secrets…**
- **Notices:** waiting for you, done; also to your phone.
- **The Claude app on your phone:** name sessions after their iTerm2 tabs;
  whether Remote Control is on for every session.
- **Safety nets (no tokens):** a copy of the folder at each session start,
  the usage-limit notice, Spotlight.
- **Uses tokens (off until you turn it on):** informed sessions, the offer
  of another agent at the usage limit, second opinions, the night shift.
- **Folder badges:** on or off, per kind; **Refresh All**, **Clear All…**
- **Handover:** reachable from the Claude app, compression, mosh, trust
  carried over.
- **Backups on another machine:** which machine keeps a copy; **Copy Now**.
- **Where each agent keeps its history:** **Choose…** when aht did not find
  an agent's history folder itself; **Reset All to Defaults**.
- **This Mac:** **Start aht in the menu bar at login**; **Open session
  windows in** (iTerm or Terminal; automatic picks iTerm when it is
  installed); **Adopt This Mac's
  Projects…** (tracks every folder that already has agent history);
  **Reinstall or Update aht…** (sets aht up again from the app, for example
  after an update); **Restart Watcher**; **Run Diagnostics**; **Open Log**;
  **Open Data Folder** (`~/.aht`); **Edit Config File** (every setting
  below, as text).

**In the terminal:**

- `aht config` — list every setting and its value.
- `aht config --set notify_finished=false` — change one.
- `aht config --unset notify_finished` — go back to the default.
- `aht config --reset` — every setting back to its default.

## All settings, one by one

Every setting, its default, and what it does. The window sets most of them;
all of them can be set with `aht config --set name=value` and put back with
`aht config --unset name`.

**When folders change**

- `move_policy` (ask) — a tracked folder moved: `ask`, `apply` (relink),
  `decline` (never, and remember), `ignore`.
- `copy_policy` (ask) — a folder was copied: `ask`, `duplicate` (the copy
  gets its own copy of the history), `independent` (a fresh start), `ignore`.
- `new_policy` (apply) — a new project turned up: `apply` (track it), `ask`,
  `ignore`.
- `watch_roots` (Desktop, Documents and the usual project folders) — the
  folders aht watches; change them with `aht roots`.
- `scan_max_depth` (7) — how many folder levels below a watched folder aht
  looks for projects.
- `extra_prune_dirs` (none) — folder names aht never looks into.
- `debounce_seconds` (2) — how long the watcher waits after a change on disk
  before it looks.
- `dialog_timeout` (180) — seconds a question waits for your answer; no
  answer means nothing changes.
- `notifications` (on) — notices about relinks, copies and backups.
- `watcher_owner` (agent) — `agent`: the watcher runs as a LaunchAgent;
  `none`: no watcher, only the Claude hook notices moves.
- `log_level` (info) — how much goes into the log: `debug`, `info`, `warn`,
  `error`.

**Agents**

- `backends` (all) — which agents' histories aht looks after.
- `backend_roots` (none) — where an agent keeps its history, when aht did
  not find it itself (`aht backends --set-root`, or Settings → Where each
  agent keeps its history).

**Folder badges**

- `icons_enabled` (on), `icons_agent` (on), `icons_git` (on) — badges at
  all, the agent discs, the git "+".
- `linux_emblem_method`, `linux_agent_emblem`, `linux_git_emblem` — the
  same on Linux.

**Backups**

- `backup_enabled` (on), `backup_interval_hours` (24), `backup_keep` (10) —
  the daily backup, how often, how many per project.
- `backup_dir` (`~/.aht/backups`) — where they go.
- `offsite_backup` (none) — the machine that keeps a copy of them.

**Handover**

- `remotes` and `default_remote` — your machines, set in the Machines tab
  or with `aht remote`.
- `mirror_interval_minutes` (30) — how often a kept copy is synced.
- `handover_excludes` (none) — more names that never travel (besides
  `node_modules`, `.venv` and the like).
- `handover_compress` (on) — compress what is sent.
- `handover_remote_control` (on) — a handed-over session is reachable from
  the Claude app.
- `handover_carry_trust` (on) — a folder trusted here is trusted there.
- `handover_claude_args` (none) — extra options for the session over there.
- `handover_mosh` (on) — open a handed-over session with mosh when it gets
  through.
- `rsync_path` (the newest rsync found) — which rsync to use.
- `terminal_app` (automatic: iTerm when installed, wherever it is, else
  Terminal) — the app that opens session windows; Settings → This Mac →
  *Open session windows in*. Another app name works only if that app runs
  the `.command` file aht hands it.

**Notices**

- `notify_waiting` (on), `notify_finished` (on), `notify_finished_minutes`
  (3) — a session waits for you; a piece of work that took at least that
  many minutes is done.
- `notify_phone` (none) — `imessage:<your number or Apple ID>` or
  `ntfy:<topic>`.
- `notify_limit` (on) — a session stopped at Claude's usage limit.
- `session_corner` (off) — the app lists the open Claude sessions in the
  screen's top-right corner (*Sessions in the corner*).

**Search, reports, the Mac**

- `report_areas` (none) — named folders for *Report → by area*, as
  `{"Work": "~/Desktop/Work"}`.
- `hotkey` (ctrl+opt+cmd+a) — the shortcut that opens the search.
- `spotlight` (on) — session titles in Spotlight.
- `tab_names` (on) — name each Claude session after its iTerm2 tab.
- `workspace_save_minutes` (10), `workspace_keep` (40) — how often the app
  saves the iTerm2 layout for *Restore my workspace* (0: only when a
  session gets a prompt), and how many layouts are kept.

**Before and after a session**

- `checkpoints` (on), `checkpoint_keep` (10) — a copy of the folder when a
  session starts; how many per project.
- `checkpoint_max_files` (20000) — bigger projects get no copy.
- `checkpoint_excludes` (none) — folder names left out of the copies.

**Use tokens: off until you turn them on**

- `informed_sessions` — a new session learns where the last one stopped.
- Claude Code's own `autoContinueAtUsageLimit` (in its settings, switched
  with `aht limits --auto-continue on|off`) — a session goes on by itself
  when the usage limit resets.
- `limit_switch`, `limit_switch_to` (kimi) — at Claude's usage limit, offer
  to go on in that agent.
- `second_opinion` — the same task by two agents.
- `night_shift` — a handover with a task, on a timer.

## Only in the terminal

These commands have no button, because you need them rarely or they fix
things by hand. Those that change something show what they would do first
and act only with `--apply`; `install` and `uninstall` act at once.

- `aht tag ~/Desktop/paper --apply` — start tracking a folder now, instead
  of waiting for aht to find it.
- `aht adopt --apply` — track every folder under the watched folders that
  already has agent history (the window's *Adopt This Mac's Projects…*).
- `aht orphans` — list Claude histories that no tracked folder owns;
  `--match` suggests the folder each one belongs to.
- `aht suggest-matches --store <name>` — the likeliest folders for one such
  history.
- `aht bind --store <name> --to ~/Desktop/paper --apply` — connect that
  history to the folder.
- `aht prune --apply` — stop tracking folders that are gone (their histories
  stay) and drop entries listed twice.
- `aht forget ~/Desktop/paper --apply` — stop tracking a folder;
  `--remove-marker` also removes its `.aht/.project-id`.
- `aht roots` — the folders aht watches; `--add ~/code` and `--remove …`
  change them.
- `aht reload` — make the watcher read its settings again.
- `aht backends` — where each agent keeps its history on this Mac;
  `--set-root claude=/path` and `--clear-root claude` change it.
- `aht keys ~/Desktop/paper` — under which name each agent files the
  history of that folder.
- `aht encode ~/Desktop/paper` — the folder name Claude Code uses for that
  path.
- `aht version` — the version of aht.
- `aht install` — set aht up on this Mac: the watcher, the notices, the
  Claude hooks and the `aht` command; `--src` installs from another folder
  (the app uses this).
- `aht uninstall` — remove all of that again; histories are never touched.
  `--remove-icons` also clears the badges; `--purge` also removes aht's
  markers, list of projects and settings.
- `aht hook` — what Claude Code runs when a session starts and at each
  prompt; not for typing yourself.
- More options: `--roots ~/code ~/src` (for `adopt`, `orphans`,
  `suggest-matches`, `reconcile` and `icons`) looks in those folders instead
  of the watched ones; `--no-reload` (for `config` and `roots`) leaves the
  watcher running as it is; `aht search --update` only brings the search
  index up to date, `--no-update` searches without doing that first;
  `aht mirror --run --due` syncs only the copies that are due;
  `aht logs --lines 200` is the long form of `-n 200`.
- Options such as `--json`, `--quiet`, `--status-file`, `backup --auto`,
  `second-opinion --run`, `night-shift --step` and `tab-names --refresh` are
  what the app and aht's background jobs use; `--json` gives any command's
  answer in a form scripts can read.

## Where things are

- `~/.aht/` holds aht's own data: `registry.json` (which folder is which
  project), `config.json`, `backups/`, `search.db`, `aht.log`, `handover/`,
  `rules-backups/`, `changes-backups/`, `redacted/`, `checkpoints/` (the
  copies to undo a session with), `undo/` (what an undo set aside),
  `opinions/` (second opinions) and `night-shift.json`.
- Inside each project, `.aht/.project-id` is the folder's identity; it
  travels with the folder when you move or copy it. `.aht/handover/` and
  `.aht/journal/` hold summaries and journals; git ignores both.

## When something looks wrong

- **Settings → Run Diagnostics** checks every part.
- macOS says *"badge_icon" Not Opened*: run `aht install` once.
- A machine shows as not reachable: is it switched on, and is Tailscale
  connected on this Mac? When only its name stops working, aht reaches it
  at its Tailscale address by itself.
- The log: **Settings → Open Log**.

**In the terminal:**

- `aht doctor` — check every part of aht and say what is wrong.
- `aht install` — set aht up again on this Mac (watcher, Claude hook,
  command).
- `aht logs --errors` — show the recent warnings and errors.
- `aht logs -n 200` — the last 200 lines of the log; `--watcher` adds the
  watcher's own log.
- `aht guide` — this guide, in the terminal.
- `aht guide --path` — where this guide's file is.
