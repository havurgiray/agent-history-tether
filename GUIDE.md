# aht guide

aht keeps the history of your AI coding agents connected to your project
folders: Claude Code, Kimi Code, Codex, Gemini CLI, Cursor, OpenCode and
Copilot. Once it does that, it can do more with those histories. It can
search them, continue a project in another agent, or hand a project over to
another machine of yours.

This guide shows aht on macOS, with its window. On Windows and Linux, aht's
window opens from the tray (**Open aht…**) or with `aht window`: the same
tabs and dialogs, without what needs macOS (iTerm2, Spotlight, Finder, the
session corner, chimes). See *On Windows and Linux*; the README's
*Platforms* table lists every feature per system.

This guide goes feature by feature, each with an example. Everything the
window does can also be done with the `aht` command in a terminal. Each
feature ends with its commands, each followed by what it does in plain
words. A command that changes something shows what it would do first; it
acts only with `--apply`.

## Where to find things

- **The ∞ in the menu bar.** A number next to it counts the sessions that
  wait for you. The menu shows the status (also a project where Claude
  stopped at its usage limit), **Open aht…**, **Guide**, **Search
  Sessions…**, **Sessions in the Corner** and **Chimes** (each on or off),
  **Find Moved Folders Now**, **Pause / Resume Watching** and **Quit**. The menu changes nothing on its own, so a stray click is
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

## Setting up

The first time you open aht, a welcome window sets it up. **Quick Setup**
does it in one step; **Choose Each Step** lets you decide everything.

> **Example.** You open aht for the first time. It found 14 projects with
> agent history in Desktop and Documents, and your agents' histories show
> that you also keep projects in ~/Developer. **Quick Setup** watches those
> three folders, takes on the 14 projects and starts aht at login.

- **Quick Setup** watches the folders where your projects are: Desktop and
  Documents, folders such as ~/Code or ~/Projects if you have them (spelled
  as they are on your disk), and any folder right under your home that your
  agents' histories point to. It takes on every project there that already
  has agent history, except one you told aht to forget (its page names
  those: *Leave out …: you told aht to forget it*), and later each new
  project as you work in it; when no project has history yet, its page
  says just that: *Take on new projects as you work in them*.
  The first time, it also asks before it relinks a folder that moved or
  was copied, badges project folders, backs up the histories once a day
  and starts at login; its page lists what it will do.
- **Start at login keeps your answer.** Once you said whether aht starts
  at login (the Windows installer asks; so do the switch in Settings and
  the tray's own), Quick Setup keeps that answer. When it stays off, its
  page says so, and a switch on that line (a box in aht's window) turns it
  on right there. *Choose Each Step*'s *A few more* page has the same
  switch.
- **Never offered:** ~/Library (on Windows AppData and scoop), hidden
  folders, and folders aht never looks into, such as `node_modules`,
  `build` or `venv`. Projects there are listed as *outside these*: they
  keep their history, but aht does not follow them when they move.
- **When aht is not installed on this Mac yet** (the first time, and also
  from **Run Setup Again…** or `aht://welcome`), setting up also installs
  the watcher, the Claude Code hooks and the `aht` command; `aht uninstall`
  undoes all of it.
- **Choose Each Step:** the folders to watch (tick them, or add one), which
  of the projects found to take on (one you told aht to forget is listed
  unticked, marked *you told aht to forget it*), what to do when a folder
  moves or is copied, and the extras: folder badges, backups, notices and
  start at login. New projects are taken on as you work in them; there is
  no setting for that.
- **Stay up to date:** both end with a step of their own that asks whether
  aht may tell you when a new version is out (**Yes, Tell Me** or **No
  Thanks**; see *New versions*).
- Nothing leaves your computer while aht sets up.
- At the end the window shows *Getting started*: what lets aht do more,
  such as iTerm2 and Remote Control.
- **Not Now**, or closing the welcome window, sets nothing up. The welcome
  then waits for the next version of the app; until then **Run Setup
  Again…** under Settings → This Mac opens it.
- To change any of it later: Settings (**Watched folders**, **When folders
  change** and the rest), or **Run Setup Again…** under Settings → This Mac.
  Run Setup Again (on a Mac also an `aht://setup` or `aht://welcome` link)
  starts from your current settings: it keeps your rules for folders that
  move, badges, backups and whether aht starts at login, and its page lists
  what it will apply. Only a first setup before you answered (on a Mac,
  also one that installs aht) switches start at login on by itself.

**In the terminal:**

- `aht setup` — show the folders aht would watch and the projects it found
  there that it does not track yet, marking one you told aht to forget
  (`--json` also lists the projects outside those folders, as `elsewhere`,
  and gives a forgotten one `"forgotten": true`).
- `aht setup --apply` — watch those folders and take on all those projects,
  except ones you told aht to forget.
- `aht setup --apply --roots ~/Desktop ~/Developer --adopt ~/Desktop/paper
  --moves apply --badges off` — choose: the folders to watch, the projects
  to take on (`--adopt` with nothing after it: none; a project you told aht
  to forget is taken on again when you name it here), what to do when a
  folder moves (`--copies` likewise), and the extras
  (`--backups`, `--notifications`, `--update-check`, each `on` or `off`).
  An option given twice adds up: `--adopt A --adopt B` is the same as
  `--adopt A B`.
- `aht adopt --only ~/Desktop/paper --apply` — take on one of the projects
  found.

## Getting started

aht keeps your histories connected on its own once it is set up. A few
steps let it do more on a Mac, mostly with iTerm2 and the Claude app on
your phone. The first time aht starts while a main step is still to do, it
opens its window with the list; after that the list is in **Settings →
Getting started** (**Show the Steps…**). Each step says whether it is done
and what it is for, with a button or a switch where aht can do it for you.

> **Example.** You install aht on a new Mac. The list says iTerm2 is not
> installed; **Get iTerm2…** opens its website. Once iTerm2 is there, the
> list shows two more steps: switch on iTerm2's Python API, and let aht
> control iTerm2 (**Ask Now**, then *OK*). You switch on **Start at login**
> and **Sessions in the corner** in the same list.

- **iTerm2.** aht works with any terminal, but session names from tab
  titles, **Go to Tab**, *Restore my workspace* and a click in the corner
  list that brings a session to the front need iTerm2 (free, from
  iterm2.com).
- **iTerm2's Python API** (iTerm2 → Settings → General → Magic → *Enable
  Python API*). Without it, each session still takes its tab's title, but
  a name you give a session does not reach its tab (see *Session names from
  your iTerm2 tabs*).
- **Permission to control iTerm2.** macOS asks once whether aht may control
  iTerm2. **Ask Now** asks right away; it opens iTerm2 first, since macOS
  asks only about an app that runs. If the answer was no, Go to Tab, clicks
  in the corner list and Restore Workspace do nothing: **Open Privacy
  Settings…** goes to System Settings → Privacy & Security → Automation,
  where you can allow it.
- **Start at login.** The corner list, the chimes and saving the iTerm2
  layout work only while the app runs. Once you said no to it (with a
  switch, or on Windows the installer's unticked box), the list shows it
  as optional (○), not as a step still to do.
- **Your sessions in the Claude app** (optional). Remote Control in Claude
  Code (`/config` → *Enable Remote Control for all sessions*) puts every
  session into the Claude app on your phone, under its tab's name.
- **Sessions in the corner** and **Chimes** (optional; off until you switch
  them on).
- **iTerm2's blue dot** (optional). iTerm2 puts a blue dot on every tab that
  printed something new. Once the corner list shows how each session is
  doing, the dot tells you little; for calmer tabs, turn off iTerm2 →
  Settings → Appearance → Tabs → *Show new-output indicator*.
- **Tab colours for Restore Workspace** (optional). aht reads tab colours
  from the window state iTerm2 keeps to bring its windows back. If iTerm2
  keeps none, restored tabs open without their colours.

aht reads these settings of iTerm2 and Claude Code but never changes them:
the steps there are yours to take.

**In the terminal:**

- `aht getting-started` — the same list: ✓ done, ✗ a main step still to do,
  ○ an optional one. `aht install` ends with it.
- `open aht://getting-started` — open the list in the app.

## On Windows and Linux

aht's window on Windows and Linux is a page that aht serves to your own
computer and shows in an app window of Edge or Chrome (or a tab of your
browser when neither is there). It has the Mac window's tabs — Projects,
Sessions, Search, Machines and Settings — and its dialogs: Show Sessions,
What Changed, Undo a Session, the journal, project rules, secrets, loose
ends, the report, Tidy Up, second opinion, the guide, the welcome window and
Getting started.

> **Example.** On Windows you click aht's icon in the taskbar's corner and
> choose **Open aht…**. A window opens with your projects; you select
> *paper*, then **More → Show Sessions…**, and **Continue** opens that
> session in a console window.

- **Only you get in:** the page is served at 127.0.0.1, so nothing outside
  this computer reaches it. The tray opens it with a code that works once.
  The code gives the page a cookie and a key of its own; the key comes
  after the `#` in the address, a part no server ever receives. A second
  window in the same browser uses the same cookie and key. Every request
  that runs a command or reads the guide needs both (the page's own files
  need only the cookie), so another website, or another server on this
  computer (which gets the cookie too), cannot use it. On Linux the server
  also refuses connections from other accounts of the computer. It runs
  only the aht commands the window needs, and serves only its own page,
  from where aht is installed.
- **It stops by itself** 15 minutes after its last window closed; an open
  window asks it once a minute, so it does not stop while you read. If it
  stopped anyway, for example after an upgrade, the window says so: open it
  again from aht's tray icon, or with `aht window`.
- **Continue** and **Switch Agent** open a console window on Windows, in
  the project's folder. On Linux they open the first terminal they find of
  x-terminal-emulator, gnome-terminal, kgx, konsole, xfce4-terminal, tilix,
  terminator, alacritty, kitty, foot and xterm. When none opens, the window
  says *No terminal window opened* and shows the line to run by hand (for
  Switch Agent, the summary is written already).
- **Choosing a folder:** **Add Folder…**, Tidy Up's **Choose Its
  Folder…** and **Choose…** under *Where each agent keeps its history*
  open the system's folder chooser. **Cancel** just closes it; nothing more
  is asked. On Windows the chooser is a tree with a *Folder:* field: type
  or paste a full path there (in quotes or with `%VARIABLES%` too, also a
  network path such as `\\server\share\…`) and press **OK**. Places that
  are not folders on a disk, such as This PC, Libraries or Network, cannot
  be chosen (**OK** greys out). A path with no folder behind it gets *That
  is not a folder: There is no folder at …*, and nothing changes. On Linux
  the chooser is zenity's or kdialog's. Only when no chooser can be shown
  (Linux without zenity or kdialog, or with no desktop) does the window ask
  you to type or paste the path.
- **Notices** come from the tray: a session that waits for you, a long one
  that is done, Claude's usage limit, a new version. On Windows a click on
  one opens the window.
- **Your other machines from Windows:** a PC asks your Mac and Linux
  machines what runs there, watches them, searches them, picks up their
  work and leaves notes on them, and keeps a copy of its backups on one
  of them. It also hands projects over to them and takes them back, keeps
  projects in sync with them, and brings their projects here and sends
  them back (see *A Windows PC with your other machines* and *Bring a
  project here, and send it back*). Nothing can be handed over to a PC.
- **Start at login:** Settings → This computer → *Start aht's tray at
  login* (on Windows the tray then also keeps the watcher running). On
  Linux the switch can be turned on only when the tray can run there: it
  needs PyGObject and an AppIndicator library. Until then *Getting started*
  lists the packages to install (and, on GNOME, the AppIndicator Support
  extension); an entry that is there already can still be switched off.
  On Linux, when the path to Python holds a `%`, the login entry starts
  the same Python by its real path, or `python3` on your PATH; when both
  have a `%`, nothing can start at login from that Python.
- **Getting started** lists what this computer still needs: start at
  login (optional once you said no to it); on Linux the tray's packages,
  notify-send for notices, and zenity or kdialog for questions (once one is
  installed that step is done, even when you look over ssh); Edge or Chrome
  to show the window as an app, and on Windows Windows Terminal (both
  optional).
- **Installing on Windows:** the installer from the releases page
  (`aht-setup-…-windows-x64.exe`, or `-arm64` on an ARM computer) asks no
  administrator password. It puts aht in your `AppData\Local\Programs\aht`,
  sets up the hook and the watcher, which starts at sign-in, offers to put
  `aht` on your PATH, and opens aht's window with the welcome. On the first
  install only, it asks whether to *Show aht's tray icon when I sign in*;
  the answer holds even over a tray entry that an earlier `aht install`
  from the zip left (unchecked, only the watcher starts at sign-in), and
  the welcome keeps it: unchecked, its Quick Setup shows the tray line
  unticked and says why, and ticking it there turns it on. An
  upgrade (the installer, **Upgrade**, Scoop, winget or `aht install`)
  keeps what you set later in Settings or the tray. Start menu → **aht**
  opens the window again. Settings → Apps → **aht** → *Uninstall* removes
  it and leaves your history as it is.
- **Installing on Linux:** from a checkout, `cd linux && ./install.sh`
  (the `install.py` at the top of the checkout is the Mac's); the tray is
  `python3 linux/tray.py`.

**In the terminal:**

- `aht window` — open aht's window (it starts the server when none runs).
- `aht window --no-open` — only serve it and print the address to open.
- `aht autostart on` — start aht's tray at login (`off` to stop; without
  either, say whether it does). `on` or `off` also counts as your answer,
  so the welcome keeps it, but only when the tray then starts at login, or
  not, as you asked. On a Mac it changes nothing (the app has the switch).

## A Windows PC with your other machines

From a Windows PC, aht can ask your Mac and Linux machines what runs
there, pick up their work, hand projects over to them and bring their
projects here. It uses Windows' own ssh. The PC always does the asking and
is never asked itself, so it needs no ssh server.

> **Example.** A long Claude Code session runs on your Linux box at home.
> On the PC at work you add it under **Machines → Add a Machine…** as
> homebox, `you@homebox`, and tick **Watch**. When the session there stops
> to ask you something, the tray shows *paper on homebox waits for you:
> approve Bash: make test*. The Sessions tab lists it too.

**Once, on the PC:**

1. **ssh.** Windows 10 and 11 have OpenSSH's client built in. If `ssh` is
   missing in PowerShell, add it: Settings → System → Optional features →
   *OpenSSH Client*.
2. **A key.** In PowerShell: `ssh-keygen -t ed25519`. Press Enter to keep
   the file name. A passphrase is up to you (see step 4).
3. **Put the key on the other machine.** Windows has no `ssh-copy-id`; in
   PowerShell, this does the same (it asks for your password there once):
   `type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh you@homebox "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"`
4. **A key with a passphrase needs ssh-agent,** which Windows ships
   switched off. In an administrator PowerShell: `Get-Service ssh-agent |
   Set-Service -StartupType Automatic; Start-Service ssh-agent`. Then, in a
   normal one: `ssh-add`. Or use a key without a passphrase. aht's ssh never
   asks for a passphrase, so a key that has one works only once ssh-agent
   holds it.
5. **Accept the machine's key once:** run `ssh you@homebox` in a terminal
   and answer *yes*. aht never accepts a key for you.

**Once, on the other machine:**

- **A Mac:** turn on Remote Login: System Settings → General → Sharing →
  *Remote Login*.
- **Linux:** an ssh server must run there. On Ubuntu or Debian: `sudo apt
  install openssh-server`, then `sudo systemctl enable --now ssh` (the
  service is `sshd` on Fedora and Arch).
- **Both:** aht's copy runs there with python3. Most Linux systems have
  it; on a Mac it comes with Apple's Command Line Tools (`xcode-select
  --install`).

Then add the machine (**Machines → Add a Machine…**, or `aht remote add`)
and press **Check…**. Its rows come in two groups:

- **For asking:** *reachable*, *key login without a prompt* and *python3
  there*. These are all a PC needs. Each one marked ✗ comes with its fix:
  the ssh-agent steps above when the key was not accepted, *Connect once
  in a terminal (`ssh you@homebox`) and accept the machine's key* when the
  PC does not know that machine yet, and *Turn on Remote Login on the Mac*
  when a Mac refuses the connection.
- **For handing over:** what a handover to that machine needs (tmux
  there, a writable folder, where projects go there) and what copies the
  files (*copies files with — aht's own copy*, always on a PC). Bring
  Here and Send Back need only the rows for asking, and aht installed on
  that machine.

**What a PC can do today:**

- add, check and remove your Mac and Linux machines; `aht remote
  discover` lists the ones on your Tailscale network (Windows machines
  there are left out, since they cannot be asked);
- see their open sessions in the Sessions tab;
- **Watch** a machine: the tray tells you when a session there waits for
  you or is done (see *Hand a project over to another machine*);
- search their sessions too, with **Also on my other machines** (see
  *Search every session*);
- **Pick Up** a project's work from them, and **Leave a Note** on them
  before you leave the PC (**Machines** under the project; see *Pick up on
  another machine*). Since no machine can ask the PC, the PC starts every
  exchange: Pick Up from the Mac when you sit down, and Leave a Note (or
  Hand Back) on the Mac before you go;
- keep a copy of its backups on one of them, and fetch backups from it
  (see below);
- **Hand Over** a project to one of them and take it back (**Take
  Back**), as a Mac does (see *Hand a project over to another machine*). **Open Session**
  opens a console window with `ssh -t` to the session there: Windows has
  no mosh. **Keep in sync** and the **Night Shift** work from the PC too;
- **Bring Here** a project of theirs, and send it back (**Send Back**)
  when you are done (see *Bring a project here, and send it back*). The PC starts both,
  so the Mac or Linux machine never has to reach the PC. The tray lists
  what came this way under **Projects brought here**.

The project usually sits at another path on the PC (`C:\Users\me\code\shop`
for `/Users/me/code/shop`): see *Across systems and folders*.

**Backups from a PC.** **Settings → Backups on another machine**: pick
one of your Mac or Linux machines. After each daily backup, aht adds the
new backups to a folder of this PC's own there, as on a Mac (see
*Backups, and bringing a session back*); **Copy Now** copies at once.
**Fetch Backups From…** lists every computer's folder of backups on that
machine, also those of your Macs and Linux machines, and **Fetch** adds
what is missing on the PC and replaces nothing. aht's own copy moves the
files, so the PC needs no rsync; the other machine needs only python3, as
for asking it.

> **Example.** Your office PC broke, and it kept its backups on homebox.
> On the new PC, add homebox, pick it under **Settings → Backups on
> another machine** and press **Fetch Backups From…**. The list shows
> *office-pc*, with its system, its last update, its projects and
> backups; **Fetch** brings them to the new PC. **Search** then finds the
> old sessions, and **Restore…** brings one back.

- A file another program holds open on the PC (or that Windows Security
  is reading) is tried again 5 times, 0.2 s apart. If it is still held,
  that one file is named as not fetched; the rest arrive.

**What it cannot do yet:**

- be asked by another machine. Adding a PC as a machine on a Mac or on
  Linux stops with *aht cannot ask a Windows machine yet*, and makes
  nothing on the PC. So a Mac cannot pick up work from the PC or leave a
  note on it, hand a project over to it, or take back a project the PC
  brought there: the PC sends it back. While the PC holds it, the
  project on the Mac says *On pc since 14:10 (brought there from pc).
  Send it back from pc.*, with **Release…** for a PC that is gone.

**In the terminal:**

- `aht remote add homebox you@homebox` — add the machine under the name
  homebox.
- `aht remote check homebox` — check it; the rows are grouped *for asking
  it* and *for handing projects over*.
- `aht remote watch homebox` — watch it.
- `aht board` — list the open sessions here and on your other machines.
- `aht search deploy --everywhere` — search here and on your other
  machines.
- `aht pickup $HOME\Desktop\paper --from homebox` — show what picking up
  paper's work from homebox would bring (in PowerShell); `--open codex
  --apply` writes the summary and opens Codex with it.
- `aht leave-note $HOME\Desktop\paper --on homebox --apply` — leave a
  summary of the work here in paper's folder on homebox.
- `aht config --set offsite_backup=homebox` — keep a copy of the backups
  on homebox; `aht backup --offsite` copies now.
- `aht backup --offsite-list` — list every computer's folder of backups on
  homebox; `aht backup --fetch-offsite --from office-pc` fetches that
  computer's backups to this PC.
- `aht handover $HOME\code\shop --to homebox` — show what handing shop
  over to homebox would send, and where it goes there; `--apply` does it.
- `aht bring --from homebox --list` — list the projects aht keeps on
  homebox; `aht bring /home/me/code/shop --from homebox` shows what
  bringing one here would do.
- `aht send-back $HOME\code\shop` — show what sending it back would
  change on homebox; `--apply` does it.

## New versions

aht can tell you when a new version is out, show what's new and upgrade
itself. Since that means asking GitHub, it is off until you say yes: in the
*Stay up to date* step of the setup, or later under Settings → This Mac →
*Tell me when a new version of aht is out*.

> **Example.** One morning a notice says *aht 0.14.0 is out*. A click
> shows what's new in 0.14.0. **Upgrade** opens a Terminal window that runs
> `brew upgrade --cask aht`, sets aht up again and opens the new version.

- **How:** once a day aht asks GitHub which release is the latest. GitHub
  sees your computer's address and which version of aht you run; nothing
  else is sent. With it off, aht asks only when you press **Check Now**.
  When GitHub cannot be reached, Check Now says *GitHub did not answer*,
  and why.
- **Upgrade** goes the way you installed aht: Homebrew on a Mac (`brew
  upgrade --cask aht`), Scoop on Windows (`scoop update aht`, then `aht
  install --here`), each in a terminal window. Installed with aht's Windows
  installer (or winget, which runs it), Upgrade downloads the new installer
  from GitHub, checks it against the release's checksums and runs it; aht
  starts again when it is done, and aht's window opens again if it was
  open. A copy downloaded from the releases page opens that page instead
  (**Open the Download Page**). On Linux, which installs from a checkout,
  the button opens the release page too, and the update says what to do:
  `git pull` in your copy of aht, then `linux/install.sh` again.
- The ∞ menu says *aht 0.14.0 is out* until you upgrade, and leads to the
  same page.

**In the terminal:**

- `aht update` — whether a newer version is known, from the last look.
- `aht update --now` — ask GitHub now.
- `aht update --upgrade` — upgrade the way aht was installed: Homebrew or
  Scoop in a terminal window, aht's Windows installer downloaded, checked
  and run; on Linux (a checkout) it says how to update and opens the
  release page; otherwise, a Mac checkout too, the download page opens.
- `aht config --set update_check=true` — look once a day.

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

Some spend tokens only when you ask for them, each time: **Switch Agent**
(the agent that goes on reads a summary, or a catch-up in its own session:
one turn), **Hand Back** to Codex, Kimi Code, Antigravity or Mistral Vibe
(one turn of that agent), **Hand Over** with a task (the session starts
on it) and **Pick Up** with **Open in** (the agent opened here reads the
summary from the other machine: one turn). Hand Back to Claude Code runs no
turn: the catch-up is in the session when it opens, and Claude reads it
with your next message. Writing a summary, **Summary Only**, `aht relays`,
a Pick Up that opens nothing and **Leave a Note** spend nothing (see
*Continue in another agent* and *Pick up on another machine*).

A handed-over project also puts one sentence into a new Claude session in
its folder, so the session knows the project is away, that a handover of it
did not finish yet, or that it has just come back or was released. In the
same way, a Claude session that another agent took the work over from gets
one line when you resume it yourself: who worked on the project since, and
where the summary is. After a Pick Up or a note, the next Claude session in
the folder on the machine the work came to gets one line, once, and a Claude
session that starts on the machine the work left gets one line while the
work is out (see *Pick up on another machine*).

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
- **Only the case changed** (`proj` renamed to `Proj`, on a Mac or Windows,
  where both name one folder): the folder keeps its history without a
  question, unless Settings say to leave moves alone. Claude Code's start
  hook does the same at the next session. A watched folder renamed only in
  case (`~/code` to `~/Code` in Finder) is fine too: aht looks into watched
  folders as they are spelled on disk, so its projects are not relinked
  back and forth.
- **Moved right after its first session**, before aht noted where Claude
  Code keeps its history: the next session in the new place still brings
  that history along.
- **Settings → When folders change** decides whether aht asks, relinks on
  its own, or leaves things alone.

**In the terminal:**

- `aht reconcile` — look for folders that moved or were copied and say what
  it would relink, without changing anything.
- `aht reconcile --notify` — act the way Settings say, asking where they
  say "Ask me", and track new projects (what **Find Moved Folders** does).
- `aht reconcile --apply` — act without asking: relink moved folders, give
  copies their own history, track new projects. Neither takes on a project
  you told aht to forget (see *Tidy up*).
- `aht reconcile --only ~/Desktop/paper-2026 --apply` — look at that folder
  only.
- `aht reconcile --notify --copies independent` — this once, treat copies
  differently from Settings (`--moves` works the same way).
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
- A "+" in the middle: a git repository. On Linux it is an emblem of its
  own, a white disc with a dark "+", that the file manager places next to
  the others.

**In the terminal:**

- `aht icons --refresh` — redraw the badges of every folder, for example
  after you turned a kind of badge off, or when a badge on Windows shows a
  plain drawn folder instead of Windows' own.

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
  adds the new backups to a folder of this computer's own there, named by
  a random id, so a lost or broken Mac does not take the histories with it.
  Copying only adds: a backup there goes only after aht removed it here,
  and at least 3 per project always stay. The copies aht makes before it
  rewrites a history go there too, and aht never removes those there.
  **Copy Now** copies at once.
- **Fetch Backups From…** (in the same group) brings backups back, for
  example on a new computer. It lists every computer's folder of backups on
  that machine, with its name, system (macOS, Linux or Windows), last
  update, projects, backups and size; this computer's own is marked, and so
  is one an older aht made. **Fetch** adds what is missing here (backups,
  and copies made before a rewrite) and replaces nothing: a backup that
  differs from one of the same name here arrives next to it
  under a new name (`<stamp>-from-<name>.zip`). Search then finds the
  sessions in them, and **Restore…** on a result brings one back. When a
  backup cannot be put in place, the others still arrive; `aht backup
  --fetch-offsite` names it with why (*not fetched: …*) and ends with exit
  code 1.
- **An older aht's folder** there (named after this computer, from before
  each computer got an id) becomes this computer's own only when every
  backup in it, and every copy made before a rewrite, is here too; one with
  nothing left in it is removed. Otherwise it stays as it is, listed as
  *older aht*, and **Copy Now** says so: **Fetch Backups From…** can bring
  its backups here.
- **On Windows too.** aht's own copy moves the backups, so a PC needs no
  rsync; it copies to and fetches from your Mac and Linux machines (see
  *A Windows PC with your other machines*).

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
- `aht backup --offsite-list` — list every computer's folder of backups on
  that machine.
- `aht backup --fetch-offsite` — on a new computer, bring backups back from
  that machine: this computer's own folder, or the only one there (with
  several, it asks for `--from`). It adds what is missing and never
  overwrites.
- `aht backup --fetch-offsite --from studio` — fetch from that computer's
  folder. `--from` takes an id first, then a folder's name (an older aht's
  folder is named after its computer), then a computer's name; a name that
  two computers share asks for the id. The window and the Mac app pass the
  id, or the folder for an older aht's row.

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
- What aht recognises as a key or a password (see *Secrets check*) is
  masked whole before it reaches the search index: in messages, in the
  commands, file paths and web addresses of tool calls, and in session
  titles.
- After an update from an earlier version, the index is built anew once,
  by itself, at its next update. A session whose history file is gone and
  that no history backup holds is then no longer found.
- **Also on my other machines:** tick it (it shows once you added a
  machine), and each of your other machines searches its own index too,
  all at once, with up to 20 seconds each. This computer's results come
  first; each one from another machine carries that machine's name, and
  offers no Resume or Restore, since those act here, but **Continue
  Here…**: it picks up that session's work from that machine into the
  project's folder here (see *Pick up on another machine*). That folder is
  the one aht tracks under the same name; when there is none, or more than
  one, you choose it. A line names each machine that could not be
  searched, and why: it was not reachable, or
  *no search index (aht is not installed there)*. *Also searched:* lists
  the others, with how many results each gave and when its index was last
  updated. aht builds no index there and changes none, and keeps nothing
  of what came back; what aht recognises as a key is masked there and
  again here.

**In the terminal:**

- `aht search deploy api` — find the sessions in which both "deploy" and
  "api" appear, in every project and agent.
- `aht search deploy api --everywhere` — the same here and on each of
  your other machines.
- `open "aht://search?q=deploy&everywhere=1"` — open the Mac app's search
  with *Also on my other machines* ticked.
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

**A machine that does not answer** (asleep, switched off, offline) keeps
its place in the list. Its sessions as they were when it last answered
are shown greyed, under *as of 11:40*, and the machine's line says since
when it has not answered. `aht board` prints *not answering since 11:40;
as of then:* over them.

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
- The agent's last message is masked whole before the question is picked
  out of it, so a key in it shows masked, and a private key as *[private
  key: BEGIN RSA PRIVATE KEY]*. Session titles are masked too.

**In the terminal:**

- `aht loose-ends` — list the projects of the last 30 days that have
  something left open.
- `aht loose-ends --days 7` — the same for the last week only.

## Know when a session needs you

aht checks the open sessions every 30 seconds, and tells you when one starts
**waiting for you** or **finishes** a piece of work that took a while. That
is every session here; on another machine, those of a machine you watch
(every 2 minutes) or that holds a project of yours (about once a minute).
See *Hand a project over to another machine*.

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
- **A handover cut off halfway** gets notices of its own: how it ended,
  and after an hour without an answer from the other machine, that you can
  release the project (see *Hand a project over to another machine*).
- **Every notice names its machine** once you added another one: *paper
  on homebox waits for you*, and a session here gets this computer's
  name.
- **Your phone gets each notice once:** when aht on the other machine
  sends that machine's notices to your phone itself, this computer leaves
  them out.
- What a session waits for is shown with the keys and passwords aht
  recognises masked (see *Secrets check*), here and on your phone. On
  another machine it is masked before it leaves that machine.
- **Sessions in the corner:** a small list in the screen's top-right
  corner shows every open Claude session on this Mac: **working** (blue),
  **waiting for you** (orange) or **done** (green), with how long it has
  been so, under the name the Claude app shows. The sessions working now
  come first, the one that started last on top; the rest follow by when
  they last worked. *Done* stays until you click that session there, which
  brings its iTerm2 tab to the front, or until it starts working again.
  When a click cannot do that (the session is not in an iTerm2 tab, or
  macOS does not let aht control iTerm2), a line in the list says why for
  a few seconds. Drag the
  list anywhere you like (it stays there); a double-click on its top line
  puts it back in the corner. Drag its left or right edge to make it wider
  or narrower (a name that does not fit ends in "…"), and its bottom edge
  to list more or fewer sessions; the rest show as "+n more", so it never
  needs to scroll. Turn it on or off in the aht menu (*Sessions in the
  Corner*) or in Settings → Notices; the × on the list turns it off too.
  It reads Claude Code's own records of its sessions every second and a
  half, so it needs no tokens and hardly any time.

**In the terminal:**

- `aht notices --test` — send a sample notice, to this Mac and to your phone
  if one is set.
- `aht limits` — list the sessions that stopped at Claude's usage limit in
  the last 12 hours, and when the limit resets.
- `aht limits --hours 48` — look back two days instead.

## Chimes when a session is done or waits for you

A short chime the moment a Claude session on this Mac finishes a piece of
work or starts waiting for you, so you hear it without looking. Each of
these has its own sound, and you choose it. The chimes are off until you
turn them on: Settings → Chimes, or **Chimes** in the aht menu.

> **Example.** Three sessions work on three projects while you read a
> paper. A *doorbell* means one needs an answer from you (a permission, a
> question); three notes going up mean one is done. The corner, or the
> number next to the ∞, shows which.

- **Waits for you** (Doorbell), **Is done** (Bloom) and **Hits the usage
  limit** (Ebb, when Claude stops at its usage limit) each have their own
  chime. A chime you pick
  plays at once, so you hear what you chose; ▶ plays it again.
- **Is done … after working at least** 30 seconds (from *any length* to 10
  minutes): a quick answer in the session you are typing in stays quiet.
- **aht's own chimes** are made by the app itself from notes of one scale,
  so two in a row never clash. Each is about as loud as the sounds of macOS
  at its loudest moment, so a short one is no louder than a long one:
  - *Bloom*: three notes going up (made for "done").
  - *Settle*: a falling fifth, calmer.
  - *Doorbell*: ding-dong (made for "waits for you").
  - *Tap*: two light wooden knocks.
  - *Ask*: two notes going up, like a question.
  - *Ebb*: three low notes going down (made for the usage limit).
  - *Drop*: a single water drop.

  The short ones, a fifth of a second each:
  - *Ebb1*, *Ebb2*, *Ebb3*: Ebb's notes, one each, from high to low.
  - *Felt*: one low note, like a piano with felt on its hammers.
  - *Hush*: a soft tone that swells and fades, with no strike at all.
  - *Pluck*: a soft plucked string.
  - *Bubble*: a low bubble, rising.
  - *Puff*: a short breath, no note; the quietest.

  Below them in the list are the sounds of macOS (Glass, Ping, Purr…) and
  any in your `~/Library/Sounds`. **Choose a File…** takes any short sound
  file, and **None** keeps that one quiet.
- **Volume** sets the chimes only, not your Mac; letting go of the slider
  plays one.
- **How it knows:** aht reads Claude Code's own records of its sessions
  every second and a half, as the corner does, so it needs no tokens. Only
  sessions you work in chime, not scripted ones (`claude -p`), and sessions
  that finish together make one chime. A session on another machine, and
  the usage limit, chime when their notice arrives, so those notices must
  be on (see *Know when a session needs you*). With chimes on, these
  notices make no sound of their own, so you hear one sound, not two.
- Only the Mac app plays chimes, and only while it runs.

**In the terminal:**

- `aht config --set chimes=true` — turn the chimes on.
- `aht config --set chime_done=Glass` — the chime for "done": one of aht's
  own (Bloom, Settle, Doorbell, Tap, Ask, Ebb, Drop, and the short Ebb1,
  Ebb2, Ebb3, Felt, Hush, Pluck, Bubble, Puff), a sound of macOS by its
  name, or the path of a sound file; `chime_done=` for none. The same for
  `chime_waiting` and `chime_limit`.
- `aht config --set chime_done_after=60` — chime "done" only after at least
  a minute of work.
- `aht config --set chime_volume=40` — quieter chimes (0 to 100).

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
  session. A resumed session gets nothing, as it has its own history, with
  one exception: a session another agent took the work over from, when you
  resume it yourself, learns what happened since (see *Continue in another
  agent*).
- The keys and passwords aht recognises are masked in the note (see
  *Secrets check*).
- Only Claude Code has a start hook, so only its new sessions get the note.

**In the terminal:**

- `aht config --set informed_sessions=true` — turn it on.
- `aht config --set informed_sessions=false` — turn it off again.

## A project's sessions

Every session in a project folder, so you can go back to any of them, not
only the latest. **Projects → More → Show Sessions…**

> **Example.** In *paper* you branched the session twice (`/branch` in
> Claude Code): once to try a shorter abstract, once to turn the related
> work into a table. Show Sessions lists the main session and, indented
> under it, the two branches, each with the time it branched. **Continue**
> on *Shorter abstract* opens that branch in a new terminal window, where
> it stopped.

- **Order:** the latest work first. A session counts as recent when it or
  one of its branches was used lately, so a branch you worked on today
  keeps the session it came from near the top.
- **Branches** sit under the session they came from, a branch of a branch
  one step further in. Each shows when it was branched and when it was
  last active; other sessions show when they started. A branch whose
  origin is gone (deleted, for example by Claude Code's clean-up of old
  sessions) is listed with the others and says so.
- **Open now:** a session that runs right now says *open now* and offers
  **Go to Tab** instead of Continue, so it is not opened twice.
- **Titles** are the names `/resume` shows: the one the session was given
  (`/rename`, or its tab's title), else Claude's own. The short code on the
  right is the start of the session's id; point at it to see it whole.
  With more than six sessions, a field filters them by title.
- Kimi Code and Codex sessions in the folder are listed too.
- While the project is handed over, take it back before you continue a
  session here.
- No tokens.

**In the terminal:**

- `aht sessions ~/Desktop/paper` — the same list, branches indented.
- `aht resume-here ~/Desktop/paper --session <id>` — continue that session
  in a new terminal window (add `--agent kimi` or `--agent codex` for
  theirs; `--print` only shows the command).

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

Hand a project's work from one agent to another without losing the thread,
and hand it back later. Claude Code, Codex, Kimi Code, Antigravity (the
`agy` command) and Mistral Vibe (the `vibe` command) can each take over;
**Switch Agent** lists the ones installed on this computer.

> **Example.** Claude Code tells you that you have reached your usage limit
> in the middle of a task. Select the project → **Switch Agent** →
> **Continue in Codex…**. The dialog asks how Codex goes on: in **a new
> session**, which first reads a summary of where the Claude session stood,
> or in **its own session**, the last one Codex had in this project, which
> reads only what happened since. You keep *a new session* and press
> **Switch**. Codex opens in a new window and tells you in two or three
> lines what it understood. Under the project it now says *Codex has had
> this project since 14:10, taken over from Claude Code*, with **Hand
> Back…**. When the limit has reset, you press it: your Claude session
> opens again where it stopped, and it learns what Codex did meanwhile: the
> exchanges, the files changed and the commits made.

- **The summary** goes into the project's `.aht/handover/`, which git
  ignores. It holds where things stood, the latest exchanges, the open
  to-dos, the files changed last, the state of git (branch, latest commit,
  what is not committed) and the files outside the project the session
  used, with the keys and passwords aht recognises masked (see *Secrets
  check*). It names the command that goes back to the earlier session,
  which stays as it was.
- **A new session or its own session.** A new session reads the whole
  summary. Its own session (that agent's latest one in this project) reads
  only what happened since it last worked here. When the agent has no
  session here yet, it goes on in a new one. Claude Code's own session
  hears the catch-up from aht's hook as it opens, once, as after Hand Back.
- **Summary Only**, in the same dialog, writes the summary and opens
  nothing; no agent runs. Start the agent yourself when it suits you, and
  ask it to read that file first. Since nothing started, who has the
  project stays as it was: the line under the project and Hand Back still
  go by the last real hand-off.
- **Hand Back** gives the work back to the agent it came from, in that
  agent's own session. While another agent has the work, it is also the
  first item under **Switch Agent**: *Hand Back to Claude Code (its own
  session)…*. That session reads a catch-up of what happened after it
  handed the work on: what the other agents asked and answered, the to-dos
  still open, the files changed since (from git, when the project is a
  repository) and the commits made since. When that session is gone, a new
  one reads the other agent's summary and the catch-up, and the dialog
  says so before anything happens. When aht cannot read what the other
  agent did (an agent it has no reader for, or a session it cannot make
  sense of), the dialog and the catch-up say so: *Antigravity had the
  project from 14:10; aht cannot read its work, so the files may differ:
  read them before editing.*
- **Passed on twice** (Claude Code → Codex → Kimi Code): Hand Back from Kimi
  goes to Codex, and Hand Back from Codex then goes to Claude Code. In the
  terminal, `--back --to claude` goes straight back to Claude Code, with a
  catch-up of both.
- **What it costs.** Writing a summary or a catch-up costs nothing: aht
  reads the histories itself. A new session reads the summary as its first
  turn; Codex, Kimi Code, Antigravity and Mistral Vibe read the catch-up in
  their own session the same way: one turn of that agent. Kimi reads it in
  a run of its own before its window opens, so the dialog waits a moment;
  when Kimi does not take the catch-up into its own session, a new Kimi
  session reads the full summary instead, and aht says so. **Hand Back to
  Claude Code, or Claude Code's own session, costs nothing until you
  type:** aht's Claude hook gives the session its catch-up (at most 2,000
  characters) as it opens, once, and Claude reads it with your next
  message. Without aht's hook, reading it is Claude's first turn. Summary
  Only spends nothing.
- **If you go back by hand.** When you resume the Claude session yourself
  instead of pressing Hand Back, aht's hook gives it one line: *[aht] Codex
  worked on this project after this session's last turn (14:10–16:40). The
  files may differ from what you remember: read them before editing.
  Summary: .aht/handover/relay-….md*. The catch-up itself comes with it only
  when *A new Claude session learns where the last one in its folder
  stopped* is on (Settings → Uses tokens; see *Every session starts
  informed*). Once you type in that session, the project counts as back
  with Claude, and the line under it goes.
- **Antigravity** opens in a new conversation (`agy -i`) or continues its
  own (`agy --conversation <id> -i`), with `--remote-control` when
  `handover_remote_control` is on. aht checks first that the conversation
  still exists: for an id it does not know, agy only warns and starts a
  new one.
- **Mistral Vibe** opens in a new session (`vibe "<what to read first>"`)
  or continues its own (`vibe --resume <id> "<what to read first>"`); aht
  checks first that the session is still in Vibe's data folder (`~/.vibe`,
  or `$VIBE_HOME`). aht reads the sessions of Vibe 3, not those an earlier
  Vibe left. Vibe reads a project's `AGENTS.md` only in a folder you
  trust in Vibe, and asks about a folder with such files the first time.
- **Checks first.** Not possible while a Claude session in the project is
  working or waiting for you. A Claude session open there but idle, or
  another agent open in the folder, gives a warning: don't type into both.
  On Windows aht can only tell that Codex, Kimi Code, Antigravity or
  Mistral Vibe runs on the PC, not in which folder, and says so. Codex's,
  Antigravity's and Mistral Vibe's background services are not counted as
  open. Hand Back waits while the Claude session it goes back to is still
  open in its window: exit that session and press Hand Back again (in a
  terminal, `aht switch <path> --back --brief-only` writes the catch-up for
  it to read; see below).
- When copies to undo a session are on (*Undo a whole session*), aht makes
  one before the other agent starts.
- When no terminal window can be opened, the summary is written all the
  same, and aht shows the line to run in a terminal yourself.
- **Going on by itself:** Claude Code has its own setting to continue a
  session by itself once the limit resets. Settings → Uses tokens → *When
  Claude's usage limit resets, the session continues by itself* switches it
  (it is Claude Code's setting, `autoContinueAtUsageLimit`, and it uses
  tokens, since the session works on). The notice and the Sessions tab then
  say *continues by itself then*.
- **At Claude's usage limit:** the project shows *Claude stopped at its
  usage limit; it resets 6:20pm*. With Settings → Uses tokens → *When
  Claude stops at its limit, offer to go on in* turned on (you pick Kimi
  Code, Codex, Antigravity or Mistral Vibe), a **Continue in Kimi Code…**
  button sits right next to it, and the notice says so too. aht spots the
  limit in the session's history; that costs nothing.

**In the terminal:**

- `aht limits --auto-continue on` — sessions go on by themselves when the
  limit resets (`off`: they wait for you).
- `aht switch ~/Desktop/paper --to codex` — say which session Codex would
  continue, and how, without starting anything.
- `aht switch ~/Desktop/paper --to codex --apply` — do it: write the summary
  and open a new Codex session on it (`--to claude`, `--to kimi`, `--to agy`
  and `--to vibe` work the same way).
- `aht switch ~/Desktop/paper --to codex --resume --apply` — Codex's own
  latest session in the project goes on, and reads only what happened
  since.
- `aht switch ~/Desktop/paper --to kimi --brief-only --apply` — Summary
  Only: write the summary, open nothing.
- `aht switch ~/Desktop/paper --to claude --session <id> --apply` — pass on
  that session's work rather than the latest one of another agent.
- `aht switch ~/Desktop/paper --back` — say which session the work would go
  back to, and what happened since; add `--apply` to hand it back.
- `aht switch ~/Desktop/paper --back --to claude --apply` — straight back to
  Claude Code, past the agents in between.
- `aht switch ~/Desktop/paper --back --brief-only --apply` — write the
  catch-up only and open nothing, for a session that is still open: tell
  it to read the file.
- `aht switch ~/Desktop/paper --to kimi --no-window --apply` — prepare
  everything and print the command, without opening a window. (Without
  `--no-window`, when no window opens, it ends with an error that holds the
  command.)
- `aht relays ~/Desktop/paper` — who handed the paper project's work to
  whom and when, newest first, and which hand-off is still open.
- `aht relays ~/Desktop/paper --show <id>` — print that hand-off's summary.

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
- The sheet shows each file's size and whether `CLAUDE.md` already brings
  in `AGENTS.md`.
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

A session as a page to share with a colleague, a student or a paper's
appendix.

> **Example.** A student asks how you set up the experiment scripts. **More
> → Share a Session…** saves the latest session as a web page: your messages
> and the agent's replies, with the keys and passwords aht recognises
> masked, and without e-mail addresses, local network addresses, your home
> folder's path or your user and computer names. The page says so under
> its title.

- Look through the page before you pass it on: masking is best effort.
  Names in the conversation itself, such as a repository, stay, and so do
  paths outside your home folder (an external disk, `/opt/…`) and a secret
  aht does not recognise (see *Secrets check*). With `--tools`, the
  commands and files of the tools are masked before they are shortened.

**In the terminal:**

- `aht share ~/Desktop/paper --format html --out session.html` — save the
  paper project's latest session as a web page.
- `aht share ~/Desktop/paper --format md` — print it as Markdown instead.
- `aht share ~/Desktop/paper --session <id> --agent kimi` — an earlier
  session, or one of another agent.
- `aht share ~/Desktop/paper --tools` — also list the tools the agent used.

## Secrets check

Lists what aht recognises as a key, a token or a password in the agents'
histories. Values are only ever shown masked.

> **Example.** Months ago you pasted an API key into a prompt. **Settings →
> Check All for Secrets…** lists it: the project, what it looks like
> ("Groq API key"), the masked value `gsk_…o8`, where it appeared (your
> message, a tool's output) and when. Replace that key where it was issued.

- For one project: **More → Check for Secrets**.
- **What it recognises:** keys of a known kind (Anthropic, OpenAI, Groq,
  GitHub, GitLab, AWS access keys, Google API keys and OAuth tokens, Slack,
  Stripe live keys, SendGrid, Hugging Face, npm, PyPI, age, Vault,
  DigitalOcean, Shopify, Docker Hub, Atlassian, Tailscale, JSON web tokens,
  the secret part of a Slack webhook address, the token in a Telegram bot
  address); `Bearer` tokens, `Basic` credentials and what follows
  `Authorization:` with any other scheme or none; the value given to a name
  that holds a password, a secret, a token or a key (`DB_PASSWORD=`,
  `AWS_SECRET_ACCESS_KEY=`, `SECRET_KEY=`, `JWT_SECRET=`, `client_secret`,
  `GITHUB_TOKEN=`, `x-api-key:`, `RAILS_MASTER_KEY=`, camelCase names such
  as `dbPassword`, `accessToken` and `SecretAccessKey`, in a `.env` file or
  an `export` line too, on any line of a tool's output) when the value looks
  generated; passwords on a command line (`--password X`, `--token X`,
  `mysql -pX`, `docker login -p X`, `curl -u user:X`) and in XML
  (`<password>X</password>`); and the password in a web or
  database address, whatever the host (`@localhost`, an IP address, a
  container's name such as `@db`, `[::1]`), also with an `@` in it or in
  Go's form (`user:…@tcp(host:3306)/db`), with the rest of the address left
  readable. Names that say they hold something else do not count:
  `TOKEN_URL`, `password_hash`, `token_type`, `max_tokens`,
  `accessTokenUrl`, `token_sha256`, and a page's or a request's token
  (`NextToken`, `nextPageToken`).
- **Private keys** are listed, masked and taken out from their BEGIN line
  to their END line, also inside JSON (and JSON inside JSON), in a Read
  tool's output with line numbers or with `>` or `#` before each line,
  encrypted ones, PGP
  private-key blocks and PuTTY `.ppk` files, and private keys in base64 (a
  kubeconfig's `client-key-data`, a Kubernetes `tls.key`), shown as
  *BEGIN RSA PRIVATE KEY (in base64)*. A guide or code that only names
  the BEGIN and END lines is left alone. A key the history holds twice
  (the Read tool's numbered copy and the file's text) is listed once, and
  a key of a known kind is not listed again as *password or token*.
- **Left alone:** placeholders and references to a secret store
  (`${DB_PASSWORD}`, `<token>`, `changeme`, `op://…`, `vault:…`),
  ordinary code that uses the words token, password, secret or auth
  (`token = tokenizer.encode(text)`, `password: Optional[str]`), names
  (`MAX_RETRIES`, `spring.datasource.password`), paths and web addresses,
  ARNs, fingerprints and hashes, test names (`test_auth.py::test_token`,
  `--- PASS:`) and plain words.
- **Not every secret:** masking is best effort, and aht does not try to
  guess at every shape a secret could have. A value with no name or form
  it knows stays in clear, and so can a short one, one after a name it
  does not know (`STRIPE_KEY`), a password with a quote or a space in it
  (masked only up to there), or one that does not look generated (small
  letters only, a word and digits, say). The privacy policy lists the
  known limits. Keep secrets out of agent chats.
- **`--redact` never breaks a history:** a place whose removal would leave
  a line of the history no longer valid JSON is left as it is, and aht
  says how many. So is a key in a Mistral Vibe session: Vibe checks every
  record of a session's store, and would no longer open one with a byte
  changed.
- aht never changes the agents' histories on its own. In everything it
  copies out of them it masks what it recognises, whole (a key of any
  length, up to 64 KB): the search index, journals, summaries, notices and
  what a session waits for, shared pages, Tidy Up's preview, What Changed,
  the notes for informed sessions, loose ends and second opinions,
  `aht limits`, and session titles and names and tab titles wherever aht
  lists them (the Sessions tab, loose ends, handovers, What Changed, Undo
  a Session, the tab names). It masks before it shortens a text, so a cut
  never leaves part of a key it recognises, also in the commands of tool
  calls. Names stay as they are only on this computer: in the session
  corner, the tab titles aht sets, aht's own files about tabs, the tab
  titles of saved layouts, and aht's log.
- A handover tells you when such values travel along with a project.
- **Take one out:** **Remove…** next to a find replaces it with
  `[removed by aht]` in every history file that holds it. The files are
  copied to `~/.aht/redacted` first, and it waits until no agent session is
  open in those projects. Backups still hold the old files, so replace the
  key where it was issued anyway. A new check then no longer lists it.

**In the terminal:**

- `aht secrets` — list what aht recognises as a key or password in every
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
- **On Windows and Linux** aht's window has no **Remove…** button yet:
  `aht tidy --remove-history` (below) moves such a history to the Recycle
  Bin on Windows, where *Restore* brings it back, and on Linux to the
  desktop's Trash, which your file manager restores from.
- **On Windows only to the Recycle Bin.** When a history cannot go there,
  aht changes nothing and says why, already in the dry run: the drive has
  no Recycle Bin (a network share, a `\\server\share` path, a `subst`
  drive), that drive's bin is set to remove files at once (*Don't move
  files to the Recycle Bin* in the bin's Properties, or the policy *Do not
  move deleted files to the Recycle Bin*), or the history is bigger than
  that bin holds. You can still delete it yourself. Should Windows delete
  one for good all the same, aht says *deleted for good, since it could
  not go to the Recycle Bin*.
- **A link** in Claude's history folder (a link or junction to a folder
  elsewhere) is listed and can be read (`aht tidy --show`), but it is not
  a history folder: aht leaves it alone. Tidy Up has no **Remove…** for it
  (on a Mac it reads *Claude Code, a link to a folder elsewhere*, with
  **Read…**, **Show in Finder** and **Choose Folder…**).
- **Forget sticks.** A forgotten project's folder, if it is still there,
  keeps its `.aht/.project-id`, but aht's scans no longer take it on again.
  It comes back when you take it on yourself: a new Claude Code session in
  that folder; `aht tag`; **Adopt This Mac's Projects…** or `aht adopt`
  (the question names up to three such folders, then *and N more*); ticking
  it when you set up again (**Run Setup Again** lists it unticked, marked
  *you told aht to forget it*, and Quick Setup leaves it out and says so);
  Tidy Up's **Reconnect** or **Choose Folder…** onto that folder
  (`aht bind`); `aht restore` into it; handing it over; or keeping it in
  sync. `aht forget --remove-marker` also deletes the marker.
- On a Mac and on Windows, histories are matched to their projects without
  regard to case, as the disk does: a tracked project's history is never
  listed as a history without its folder, and `aht tidy --remove-history`
  refuses it.
- Sessions you started in your home folder itself are not a project, so
  Tidy Up does not list them (nor do `aht doctor` and `aht orphans`).
- A folder listed twice, even under two spellings of its path (on a Mac or
  Windows, where `~/Code` and `~/code` are one folder), shows in `aht tidy`
  and `aht doctor`; `aht prune --apply` drops the extra entry.

**In the terminal:**

- `aht tidy` — list gone folders and histories without a folder, with
  suggestions (`--json` marks a link with `"link": true`).
- `aht tidy --relink <id> --to ~/Desktop/Projects/debug --apply` — connect
  a gone project's history to the folder where it is now.
- `aht forget --uuid <id> --apply` — stop tracking a folder you deleted on
  purpose; its history stays, and the next scan does not take it on again.
- `aht tidy --show=<name or id>` — a listed history as text to read (the
  name or the project id is in the `aht tidy` list).
- `aht tidy --remove-history=<name> --apply` — move a history without a
  folder to the Trash (on Windows to the Recycle Bin, and only there; see
  above). The name is one from the `aht tidy` list, written exactly as
  there, with `=`, because it begins with a dash. A link from that list
  gets *it is a link to a folder elsewhere, not a history folder: aht
  leaves it alone*; anything else, such as a path, another spelling or a
  file, gets *there is no such history*; `--show` also reads only a name
  or id from that list. Never one that a tracked project owns or an open
  session uses; the daily backups keep it as well. When aht refuses, it
  prints the name and why, never what it would have done.

## Hand a project over to another machine

Your laptop's connection is shaky (a train, a hotel), and a machine at home
has a stable one. Hand the project over, let it run there, and steer it from
the laptop or your phone.

**Once:**

1. **Machines → Add a machine.** Pick one that aht found on your Tailscale
   network or in `~/.ssh/config`, check the `user@host`, and press **Check
   and Add**. aht lists what that machine still lacks, each with the command
   that fixes it and a **Copy** button. aht looks for machines when you open
   the Machines tab (*Looking on your network and in ~/.ssh/config…*);
   **Look Again** looks once more, for example after you switched one on.
2. Nothing to create there: a machine added now gets each project at the
   same place below its own home folder, so `/Users/me/code/shop` here is
   `/home/me/code/shop` on a Linux box. To change where projects go, see
   *Across systems and folders*.

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
- **Same Claude Code everywhere:** the other machine gets this computer's
  exact version.
- **From any system:** a Mac, a Linux machine or a Windows PC hands
  projects over to a Mac or Linux machine and takes them back. The
  project may sit at another path there, and Claude Code's history is
  filed under that path (see *Across systems and folders*). A machine
  can also fetch a project itself and return it later: see *Bring a
  project here, and send it back*.
- **It stays awake while the agent works.** While the session there works
  or waits for you, aht keeps that machine from sleeping: `caffeinate` on
  a Mac; on Linux `systemd-inhibit`, or the GNOME desktop's own inhibitor
  (`gnome-session-inhibit`) where ssh sessions may not use it. It lets go
  when the session is idle, and stops when the session ends, after 24
  hours, or when you take the project back. A closed laptop lid still
  sleeps. **Check** shows whether it works there and with which tool
  (*stays awake while the agent works there*); on Linux, polkit may
  refuse `systemd-inhibit` over ssh, and where GNOME's inhibitor can not
  stand in either, the row says to stay logged in to that machine's GNOME
  desktop or to keep it from sleeping in its own power settings. `aht
  config --set handover_keep_awake=false` turns it off.
- **Watch:** tick **Watch** for a machine in the Machines tab, and aht asks
  it every 2 minutes for sessions that wait for you or are done, also
  when it holds no project of yours. A machine that holds one is asked
  about once a minute anyway. Each machine shows when aht last heard from
  it: *last heard 3 min ago*, or, once it has gone silent, *has not
  answered since 11:40* (on a Mac *not heard since 11:40*).
- **A machine that goes silent** while it holds a project gets one notice
  after 10 minutes: *homebox has not answered since 15:20. The work on
  paper there may have stopped (asleep, off or offline).* (to your phone
  too). When it answers again, one more says so, on this computer only. A
  watched machine that holds nothing gets no notice; the Machines tab
  says it.
- **Keep in sync:** tick it for a project, and aht copies it in the
  background every 30 minutes, so a handover only sends the last changes.
  It never overwrites work done in the copy there: it pauses and asks (see
  *Keep in sync looks first* below). A Release pauses it too (see below).
  A sync run checks each project again
  right before it sends it: one released, handed over or switched off
  while the run is under way is not sent, and the run lists it as
  *paused*, or as *skipped* with why (*Keep in sync is off for it now*).
- **Every project at once:** Machines → **Sync** → *Keep All Projects in
  Sync…*. aht first adds up what the first copy sends (projects inside
  another project travel with it; rebuilt folders such as `node_modules`
  stay behind) and asks. The first copy runs in the background and can
  take hours for tens of gigabytes; after that only changes travel. A
  paused project stays paused, and the question names it. Under each
  machine, aht's window says how many projects are kept in sync with it
  and which are paused (*4 projects kept in sync with box · 2 paused: api,
  web*); a click on a name opens that project. On a Mac, *2 paused* sits
  next to the **Sync** menu and shows them in Projects.
- **Nothing is lost:** whatever a transfer replaces is set aside first: in
  `~/.aht/handover/<project id>/replaced/` here, and in
  `~/.aht/remote/replaced/` on the other machine (Claude's checkpoints and
  plans too). The newest 5 of those folders and every one younger than 30
  days are kept.
- **What copies the files:** rsync, when this machine has rsync 3, the
  other machine has rsync, and neither is Windows; otherwise aht's own
  copy, which needs nothing on the other machine beyond python3. rsync is optional: it makes big changes
  faster. aht's own copy sends each file in pieces of at most 1 MB, checks
  it when it has arrived, and only then puts it in place; if that fails,
  the old file goes back. A file that only grew, such as a conversation
  that went on, sends just its new end. What it replaces or removes is set
  aside first, as above, on the machine that receives. It gives up two
  things against rsync: a big file changed in the middle is sent whole,
  where rsync sends only the changed parts; and a big file cut off halfway
  starts again next time, where rsync goes on from where it stopped. When
  the link drops, or nothing moves either way for 2 minutes, the copy
  ends: the files that arrived whole stay, and the next sync or handover
  sends the rest. While it copies, aht keeps the pieces in a
  folder `.aht-partial` inside the folder it copies into, and removes it
  at the end. **Check** says which one each machine gets (*copies files
  with — aht's own copy*); **Settings → Handover → Copies files with**
  chooses (`handover_transfer`).
- **Names whose case changed** there (`readme.md` → `README.md`) come back
  as renamed on a Mac, whose disk takes both for one name; the old one is
  set aside. Two names that differ only in case are both kept, one under
  the conflict name. Empty folders made there (a packed git repo's
  `refs`) come back too.
- **Summaries:** each handover and each switch of agent leaves a summary in
  the project's `.aht/handover/`; every hand-off that is still open and the
  newest 12 others are kept, of both kinds. A handover sends that folder
  along and never removes anything from it there; Keep in sync leaves it
  out.
- **A Windows PC** cannot be the other machine yet. **Check and Add**
  (`aht remote add`, `aht remote check`) stops with *aht cannot ask a
  Windows machine yet*, and nothing is made on the PC. A PC hands
  projects over to your Mac and Linux machines and brings theirs to
  itself, though: see *A Windows PC with your other machines*.

**Keep in sync looks first.** Before each sync, aht compares the copy on
the other machine with the list of that copy it kept after the last sync,
handover or take-back. So no clock matters. When the copy there was worked
on, the sync pauses, sends nothing, and the project asks what to do. A file
that was only touched does not pause it: when a file's size is the same on
both machines, aht compares its content on both.

> **Example.** You keep paper in sync with box. One evening you fix a typo
> in `README.md` on box itself and add `notes/box.md`. At the next sync,
> paper shows *Keep in sync with box is paused*: *The copy on box was
> changed since the last sync (1 changed and 1 new): README.md,
> notes/box.md. Nothing was sent; that work is still there.* (in aht's
> window *Keep in sync with box paused: the copy there was changed*). A
> notice says *Keep in sync paused: paper*. **Bring Them Here…** brings
> both files into this Mac's copy; then the sync runs, and the copy on box
> is the same as this one again.

- **Why a sync pauses:**
  - *the copy there was changed:* files there changed, new or removed
    since the last sync, or a conversation that went on there (a new
    conversation there does not count: a sync leaves it alone). The pause
    lists the files.
  - *it would remove many files there:* more than 200, or more than a
    quarter of the files there once there are at least 20. These are
    files gone here since the last sync.
  - *the folder there holds something else:* the first sync into a folder
    there that already has files and no project id, or another project's.
- **The answers.** Each pause offers only those that fit it.
  - **Bring Them Here…** works like Take Back on the copy: the same plan,
    the same question. What the changes replace here is set aside first,
    and a file changed on both machines is kept in both versions (yours
    stays, theirs goes next to it as `README (from box 2026-10-27).md`).
    Then the sync runs. Not while a session is open in the folder there.
    If it would remove many files here (more than 200, or a quarter of
    20 or more), it lists them and asks first
    (`aht reclaim <path> --allow-removals`). It never removes anything
    under `.aht/`, and it stops when the folder there is missing or empty.
  - **Replace Them…** sends this copy over the one there, once. What it
    replaces there (the work done there, or the other folder's files) is
    set aside on box first, in `~/.aht/remote/replaced/<project id>/`.
  - **Allow the Removals…** lets this one sync remove those files there.
    They are set aside there first. If they went missing here by mistake,
    get them back first (Undo a Session, or a backup).
  - **Stop Syncing** turns Keep in sync off. The copy there stays as it
    is, with the work done there.

  Each pause gives one notice, to your phone too with *Also send them to
  my phone*. Ticking **Keep in sync** off and on again ends the pause, but
  the next sync looks again, and pauses again while the copy there still
  differs.
- **Hand Over looks too.** When the copy there was changed since the last
  sync, handover or take-back, Hand Over stops and names what changed:
  *the copy on box was changed since 20:23 (1 changed: README.md) — bring
  them here first (aht reclaim /Users/me/Desktop/paper --apply), or pass
  --replace-there to set them aside there*. aht's window asks with
  **Bring Them Here…** and **Replace Them There…**; a Mac with **Bring
  Them Here…** and **Replace Them…**. Replacing sets that work aside on
  box before the handover.
- **Copies from elsewhere.** The other machine keeps a list of the folders
  that are copies of another machine's projects
  (`~/.aht/remote/copies.json` there): which project, which machine sent
  it, and since when. Where aht is installed on box:
  - Keep in sync for such a folder is refused, since one folder would be
    synced both ways: *Keep in sync was not turned on: this folder is a
    copy kept in sync from mac: syncing it from here too would sync one
    folder both ways. Keep it in sync from mac only, or turn Keep in sync
    off there first*. A folder handed over from mac is refused too (*it
    goes back to mac*). An old copy whose project went back home may be
    kept in sync.
  - **Keep All Projects in Sync…** leaves those folders out and names them
    (*Left out: 1 folder that is a copy of another machine's projects
    (api).*).
  - the project says where it came from: *Copy kept in sync from mac*,
    *Handed over from mac*, *Brought here from mac* (see *Bring a project
    here, and send it back*), or *A copy of a project that went back to
    mac*.
  - a Claude Code session that starts in the folder gets one line from
    aht's hook: *[aht] This folder is a copy kept in sync from “mac”;
    changes made here pause that sync.*

  Turning Keep in sync off on mac asks box to drop that folder from its
  list. A box that does not answer keeps it there, which only stops box
  from syncing that folder itself.
- **Names the other disk cannot hold apart**, such as `README.md` and
  `readme.md` for a Mac's disk, or one name in two Unicode forms, do not
  pause a sync. They are listed: `aht mirror --run --json` gives them
  under `names`, and the dry run of `--replace` or `--allow-removals` warns
  (*1 × two files whose names differ only in capitals, e.g. README.md /
  readme.md*).

**A handover cut off halfway.** When the link drops or this Mac sleeps
during a handover, aht cannot tell at once whether the session there
started. It asks that machine at its next check, within a few minutes, and
a notice says how it ended: *Handover of paper to homebox finished: the
session there runs (the link had dropped at 01:02)* (or *the copy there
was worked on*), and the project is on homebox as after any handover; or
*The handover of paper to homebox did not finish. The project stays here;
nothing runs there*. It counts as finished when anything happened there: a
session runs there, the copy there was worked on, *the conversation went
on there*, or *the session there started, and has ended since*. Only when
nothing happened there does it say *did not finish*. A handover that fails
before the session there starts says *did not finish* at once.

- **Meanwhile** the project shows a note, *Handover to homebox
  unfinished: checking…*, or *Handover to homebox did not finish* when
  homebox does not answer, with **Check Now** and **Release…** (aht's
  window says *under way* while the handover still runs). The list's
  *Where* says *handing over to homebox*, the ∞ menu lists the project,
  and **Continue Session**, **Switch Agent**, **Hand Over** and **Keep in
  sync** wait until it is settled. A click on the notice opens the
  project.
- **Check Now** asks homebox at once, then finishes the handover or undoes
  it.
- **Release…** lets the project count as here again, with its files here
  as they are. The copy on homebox is not touched, and the work done there
  stays there; Release asks first, and names what stays there, the files
  and the conversation: *The work done on homebox since 14:10 stays on
  homebox: 3 files and the conversation. It does not come here.* (on a
  Mac: *3 files and the conversation stay there*). It says *Nothing
  changed on homebox since 14:10, so nothing stays behind there* only when
  neither the project's files nor its conversation (Claude's history, its
  /rewind checkpoints and plans) changed there. After an hour without an
  answer, Release is the main button, and a notice says so once: *paper:
  handover unfinished: homebox has not answered since 14:10. To work on
  paper here, release it in aht; the work on homebox stays there.*
- **Release… for a handed-over project**, for a machine that is gone for
  good: on a Mac it sits next to **Take Back…**; in aht's window it is
  **More → Release from homebox…**, named as you added the machine. To
  bring the work done there home, use Take Back instead.
- **Release and Keep in sync:** releasing a project kept in sync with that
  machine pauses Keep in sync, so the next sync does not overwrite the copy
  left there. Release's question says so: in aht's window *Keep in sync
  with homebox will be paused, so the copy there stays as it is. You can
  turn it back on later.*, on a Mac *Release pauses Keep in sync with
  homebox, so the copy there stays as it is until you turn sync back on.*
  Its result says *Keep in sync with homebox is paused, so the copy there
  stays as it is.* The project then shows *Keep in sync with homebox is
  paused* with **Turn Sync Back On…**; the list says *sync paused* in aht's window (its switch
  reads *Keep in sync with homebox (paused)*) and *paused* in the Mac's
  *In sync* column. **Turn Sync Back On…** asks first. The next sync then
  looks at the copy there (see *Keep in sync looks first* above): when
  work was left there, it pauses again and asks, with **Bring Them Here…**
  and **Replace Them…**. Once aht has switched the sync back on, a note
  says *Kept in sync with
  homebox again; the next copy runs in the background.* If it could not,
  the note says *The sync was not turned back on:* and aht's reason (for
  example, that no other machine is set up yet). On a Mac, if the list
  still shows the sync paused afterwards, the note says *The sync with
  homebox did not come back on; see the log (Settings).*
  Unticking **Keep in sync** also ends the pause, and *Keep All Projects
  in Sync…* leaves a paused project paused.
- **Handing it over again** to that machine ends the pause by itself (so
  does a Take Back from it). Hand Over says so first: *the copy that
  Release left on homebox is replaced by this one (aht sets it aside there
  first); Keep in sync with homebox goes on again once the project is back
  here*. When work was left in that copy, Hand Over stops first and offers
  Bring Them Here or Replace Them (see *Hand Over looks too* above).
- **A session started here** while a handover is unfinished is warned.
  After a Release, the next session here is told once that the work done
  there did not come here.
- **Take Back refuses** when the saved list of what left belongs to another
  handover attempt, since it would count the wrong files as changed; it
  points to Release.
- **Removing a machine** that still holds a project is refused, and says
  why: take the project back first, or release it if that machine is gone
  for good.
- **On Linux** the tray shows these notices as *paper is on homebox:
  Handover of paper to homebox finished: …*, *paper stays here: The handover
  of paper to homebox did not finish. …*, and the one after an hour. With
  **Also send them to my phone** set, they reach your phone too.

**In the terminal:**

- `aht remote discover` — list the machines aht can find on your Tailscale
  network and in `~/.ssh/config`.
- `aht remote add homebox you@homebox` — add one under the name homebox.
- `aht remote check homebox` — check what that machine still lacks.
- `aht remote watch homebox` — watch homebox: hear when a session there
  waits for you or is done; `--off` stops. `aht remote` marks a watched
  machine *(watched)*.
- `aht handover ~/Desktop/paper` — show what would be sent and what stands
  in the way, without sending anything.
- `aht handover ~/Desktop/paper --apply --task "run the benchmark"` — hand
  the project over and start the session there on that task.
- `aht handover ~/Desktop/paper --session <id> --apply` — resume that
  session there instead of the latest.
- `aht handover ~/Desktop/paper --include ~/notes/paper.md --apply` — take
  a file or folder from outside the project along (remembered for the
  project). Take Back brings it back, also after a handover that finished
  once the link had dropped.
- `aht handover ~/Desktop/paper --no-start --apply` — send it without
  starting the session; `--attach` opens the session in this terminal right
  after.
- `aht handover ~/Desktop/paper --allow-processes --apply` — go ahead
  although another program (not an agent) runs in the folder; it stays
  behind.
- `aht attach ~/Desktop/paper` — open the session running on the other
  machine, in this terminal.
- `aht reclaim ~/Desktop/paper --apply` — take the project back: its files
  and history return to this Mac. For a handover cut off halfway it first
  asks the other machine what happened, also without `--apply` (that is
  **Check Now**).
- `aht reclaim ~/Desktop/paper --release` — say what releasing the project
  leaves on the other machine (*What stays there: 1 file and the
  conversation.*) and whether it pauses Keep in sync, without changing
  anything; `--apply` releases it: it counts as here again, its files here
  stay as they are, and the copy there is left alone.
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
  other machine, updated every 30 minutes. After a Release,
  `aht mirror ~/Desktop/paper --on --to homebox` turns the paused sync back
  on.
- `aht mirror ~/Desktop/paper --off` — stop that (also **Stop Syncing**:
  the copy there stays as it is); `aht mirror --run` syncs
  every kept copy now, and lists a paused one with why: *paused since the
  project was released; turn Keep in sync on again to send it*, or *paused:
  1 changed and 1 new in the copy on box — bring them here, replace them,
  or stop syncing*. `aht mirror` lists the kept copies, a paused one with
  *[paused: it was released]* or *[paused: the copy there was changed]*.
- `aht mirror ~/Desktop/paper --replace` — say what Replace Them would
  set aside in the copy there, without sending anything; `--apply` sends
  this copy over the one there, once, with theirs set aside there.
- `aht mirror ~/Desktop/paper --allow-removals` — say how many files the
  paused sync would remove there; `--apply` lets it, once, with those
  files set aside there.
- `aht reclaim ~/Desktop/paper --apply` — for a project that is here,
  **Bring Them Here**: the changes made in its copy there since the last
  sync, handover or take-back come here, then the sync runs. Without
  `--apply` it shows what would come.
- `aht handover ~/Desktop/paper --replace-there --apply` — hand over
  although the copy there was changed; that work is set aside there first.
- `aht mirror --all --on --to homebox` — show what keeping every project in
  sync with homebox would send; `--apply` does it. `aht mirror --all --off
  --apply` stops it for all of them.
- `aht remote default homebox` — make homebox the machine the window uses;
  `aht remote remove homebox` forgets it (while it holds a handed-over
  project it refuses, and names `aht reclaim … --release` for each);
  `aht remote check all` checks every machine.

## Bring a project here, and send it back

Hand Over starts on the machine that has the project. **Bring Here** starts
on the machine that will work on it: it fetches the project with Claude
Code's history, and the project's own machine (its home) notes that the
project is away. **Send Back**, on the same machine, returns the work. The
home never has to reach the machine that brought it, so a Windows PC can
bring a project from your Mac and send it back.

> **Example.** On the PC at work: **Projects → Bring Here → From mac…**
> lists the projects aht keeps on the Mac, each with where it would go:
> `/Users/me/code/shop  →  C:\Users\me\code\shop`. **Bring Here…** on shop
> shows 1,204 files (38.2 MB) and 4.1 MB of Claude history, that its
> session *Checkout flow refactor* opens here, and that 2 scripts lose
> their "executable" mark here and get it back on mac. **Bring Here**
> copies it and opens the session in a console window; nothing runs until
> you type. On the Mac, shop now says *On pc since 14:10 (brought there
> from pc). Send it back from pc.* In the evening, on the PC, **Send Back
> to mac…** shows *14 changed, 2 new, 1 removed here; 0 changed only on
> mac* and *3 files differ only in line endings: mac's stay*. **Send Back**
> puts your work into the Mac's copy.

- **What it needs:** aht installed on the project's home, at this version
  or newer, since that machine keeps the project's record. Otherwise
  Bring Here says *install aht on mac first*, or *update aht on mac first
  (and open it once)*. The home must be a Mac or a Linux machine; a
  project on a PC goes the other way, with Hand Over on the PC.
- **What stops it:**
  - a session working or waiting in the project there. An idle one stops
    it too, unless you press **Bring It Anyway** (`--allow-idle`): if
    anyone types into that session later, Send Back keeps both versions;
  - the project is away already, or the folder there is itself a copy of
    another machine's project (*bring it from there*);
  - an agent session open in the folder here;
  - the folder here holds something else, or names in the project that
    this computer cannot hold (see *Across systems and folders*);
  - too little free space here.
- **Where it goes here:** where the machine's path rule puts it (see
  *Across systems and folders*), or another folder you choose (**Another
  Folder…**, `--here`). When the folder here already holds files of this
  project, what came replaces them, and files there that did not come are
  set aside first, in `~/.aht/handover/<project id>/brought/`.
- **What comes:**
  - the project's files, without the rebuilt folders and
    `handover_excludes`, as in a handover;
  - Claude Code's history, filed under the folder's path here, the way
    Claude Code names it on this system (`C:\Users\me\code\shop` is
    `C--Users-me-code-shop`). The conversation files are not changed:
    Send Back checks that each one still begins as it left. Claude's
    memory for the project comes with them;
  - the plans of the project's sessions;
  - /rewind's snapshots only when the folder has the same path on both
    machines, since they name files by their full path. Otherwise the
    dry run says *not carried /rewind's snapshots (the path differs
    here)*;
  - Claude Code's trust in the folder, when the home trusted it and
    `handover_carry_trust` is on.
- **What stays there:** the histories of the other agents (Codex, Kimi
  Code, Antigravity and so on). The dry run names each: *Codex's history
  stays on mac*. The session here gets a summary instead, in the
  project's `.aht/handover/`: where it came from, both paths, the latest
  exchanges, open to-dos, and what did not come along.
- **The session opens here** in a new terminal window (a console window
  on Windows) with `claude --resume`; nothing runs until you type.
  `--no-open` opens none, and the result shows the line to run.
- **If it fails halfway,** before the home has noted that the project is
  here, aht tells the home to forget the attempt. What arrived here
  stays, and the next Bring Here sets it aside.
- **Send Back** runs where you brought the project. The home plans the
  way back against its record, as Take Back does, and puts the files in
  place:
  - a file changed on both machines is kept twice on the home, as
    `cart (from pc 2026-10-27).py` next to the home's; **Use the versions
    from here** (`--prefer here`) takes the ones from here and sets the
    home's aside;
  - whatever it replaces or removes is set aside on the home, in
    `~/.aht/handover/<project id>/replaced/`;
  - a conversation that does not continue the one that left is kept as
    two;
  - when a newer Claude Code wrote the history here than the home has, it
    stops (**Send Back Anyway…**, `--ignore-version`);
  - no agent session may be open in the folder here, nor in the project
    on the home, idle or not. On Windows aht also warns when an agent
    runs anywhere on the PC, since it cannot tell in which folder.

  The folder here stays as it is, as an old copy of the home's project.
- **Take Back at home** works too, when the home can reach the machine
  that brought the project (a Mac or Linux machine added there). A PC
  cannot be reached: the home shows *On pc since 14:10 (brought there
  from pc). Send it back from pc.* with **Release…**, for a PC that is
  gone.
- **A project handed over** to a Mac or Linux machine with aht installed
  can go back with Send Back on that machine too, when it can reach the
  machine that handed it over.
- **The hook says so.** A Claude session that starts in the brought
  folder hears *This folder was brought here from “mac” (where it is at
  /Users/me/code/shop); send it back when done (aht send-back).* One that
  starts in the project on the home is warned that it was brought to pc
  and is worked on there.
- **On a PC,** the tray's **Projects brought here** menu lists those
  projects; **shop — Send Back to mac…** opens aht's window with Send
  Back's plan. In aht's window and the Mac app, **Projects → Bring Here**
  lists your machines, and in the Machines tab each machine has **Bring
  Here…** (in aht's window **Bring a Project Here…**).

**In the terminal:**

- `aht bring --from mac --list` — list the projects aht keeps on mac, where
  each would go here, and why one cannot come.
- `aht bring /Users/me/code/shop --from mac` — show what bringing shop here
  would do, without changing anything; `--apply` brings it and opens its
  session.
- `aht bring /Users/me/code/shop --from mac --here C:\Users\me\code\shop-mac --apply`
  — bring it into another folder here.
- `aht bring /Users/me/code/shop --from mac --allow-idle --apply` — bring it
  although an idle session is open in it on mac.
- `aht bring /Users/me/code/shop --from mac --no-open --apply` — bring it
  without opening its session; the result shows the line to run.
- `aht send-back C:\Users\me\code\shop` — show what sending it back would
  change on mac; `--apply` sends it.
- `aht send-back C:\Users\me\code\shop --prefer here --apply` — for files
  changed on both machines, take the ones from here and set mac's aside
  there.
- `aht send-back C:\Users\me\code\shop --ignore-version --apply` — send it
  back although a newer Claude Code wrote its history here.
- `aht send-back C:\Users\me\code\shop --to mac` — name the machine, when
  aht here knows it by another name than the one it came from.

## Across systems and folders

Hand Over, Take Back, Bring Here and Send Back work between any of a Mac,
a Linux machine and a Windows PC (a PC starts each of them itself), also
when the project sits at another path on each machine. Nothing is lost on
the way: what follows says what aht does about paths, names, line endings,
executable marks and git.

**Where projects go.** Each machine you added has a rule:

- **The same place in the home folder** (`home`): the part below your home
  folder stays the same. `/Users/me/code/shop` here is
  `/home/me/code/shop` on a Linux box and `C:\Users\me\code\shop` on a PC.
  A machine you add now gets this rule.
- **The same paths** (`same`): a project keeps its exact path there. Only
  for machines with the same folders, the same user name on two Macs, say.
- **Folders that go somewhere else:** pairs of a folder here and a folder
  there, such as `D:\work` → `/Users/me/work`. They are tried first, the
  longest first, then the two home folders.
- A machine you set up before this version gets `same` when your home
  folder's path exists there, else `home` (always `home` when either side
  is Windows). aht writes that choice into its config the first time, so
  it does not change by itself.
- A project that went there keeps its folder there while its record
  lasts (handed over, brought, or kept in sync), whatever the rule says
  later.
- In aht's window, **Machines → Folders there → Change…** sets it, and the
  sheet of a refused move offers **Where Projects Go on mac…**. The Mac
  app shows the rule under each machine. `aht remote paths` sets it from a
  terminal; a change applies at once.

> **Example.** Your projects on the PC live in `D:\work`, outside your
> home folder. Hand Over stops: *aht moves projects between the home
> folders of your machines. D:\work\shop is outside yours. Tell aht where
> such projects go on mac:  aht remote paths mac --add D:\work
> /Users/me/work*. Run that line, or add the pair under **Where Projects
> Go on mac…**, and `D:\work\shop` goes to `/Users/me/work/shop`. Bring
> Here says the same the other way round, and also offers `--here`.

**The same project, not another folder.** Before anything moves, aht looks
at the folder the project would go into. It goes ahead when that folder is
missing or empty, or holds this very project (by the id in its
`.aht/.project-id`) as a copy. Otherwise it stops, and names a way past:

- *on box, /home/me/code/shop holds another folder (412 items). Move it
  away there, or choose another place:  aht remote paths box --add
  /Users/me/code /home/me/code/mac*;
- *here, C:\Users\me\code\shop holds another folder (12 items). Move it
  away, or bring it to another place:  aht bring /Users/me/code/shop
  --from mac --here C:\Users\me\code\shop-mac*;
- a folder there that is that machine's own live copy of this project is
  refused as well (*is a live project of its own there*), so an old copy
  on a PC is never handed over onto the Mac's project.

**Names the other system cannot hold.** Before a handover or a Bring Here,
aht checks every name against the disk that receives it. It tries that
disk rather than reading its settings: whether it ignores case, whether
your account may make links there, and on Windows whether long paths are
on. The dry run stops and lists up to 10 names of each kind:

| What | Checked when |
|---|---|
| two files whose names differ only in capitals | the receiving disk ignores case (usually a Mac's or a PC's) |
| two files with the same name in two Unicode forms | always |
| contains a character Windows does not allow (`< > : " \| ? *`, control characters, `\`) | the receiver is Windows |
| Windows would drop the trailing dot or space | the receiver is Windows |
| a name Windows reserves (CON, PRN, AUX, NUL, COM1–9, LPT1–9, with any extension, such as `aux.md`) | the receiver is Windows |
| the path would be too long on Windows (over 259 characters) | Windows without long paths |
| links cannot be created there for your account | the account there cannot make links (Windows without developer mode, say) |

Rename them on the machine that has them, or leave them out: **Leave Them
Out…** in aht's window adds them to `handover_excludes`, so no handover,
Bring Here, Send Back or Keep in sync moves a file or folder of that name,
in any project. Windows' own files (`desktop.ini`, `Thumbs.db`,
`$RECYCLE.BIN` and the like) never move, like a Mac's `.DS_Store`.

When a PC takes a project back, a file made there whose name Windows
cannot hold does not go into the project. It is kept aside under a safe
name (`a%3Ab.txt` for `a:b.txt`), in
`~/.aht/handover/<project id>/replaced/<time>/kept-aside/`, and listed:
*kept aside: 1 file whose name this machine cannot hold*.

**Line endings.** Tools on Windows often end lines with CRLF, tools on a
Mac or Linux with LF. Hand Over and Bring Here copy every file as it is.
On the way back (Take Back and Send Back), for a text file under 5 MB:

- one that changed there only in its line endings is not taken; the one
  at home stays. The plan lists it: *3 files differ only in line endings:
  mac's stay*;
- one that changed there and whose line endings flipped as a whole (all
  LF at home and all CRLF there, or the other way round) comes back with
  its changes and the line endings it left with: *1 file gets back the
  line endings it left mac with* (in aht's window *line endings kept as
  they were on mac*);
- one with mixed line endings, or a new file, comes back as it is. So
  does a binary file, or one of 5 MB or more.

When a git project crosses to or from Windows and has no
`.gitattributes`, the dry run says so and suggests these lines for one at
the top of the project, which keep each file's line endings steady:

```
* text=auto
*.sh text eol=lf
*.bat text eol=crlf
*.cmd text eol=crlf
*.ps1 text eol=crlf
```

aht never writes that file; add and commit it yourself if you want it.
aht's window has a **Copy** button for the lines.

**Executable marks.** Windows has no "executable" mark. aht notes which
files had it when the project left. Bring Here to a PC says how many
scripts lose it there (*2 scripts lose their "executable" mark here; they
get it back on mac*). When it comes back from the PC, a file that
replaces one at home keeps the home file's mark, and one that is no
longer at home gets back the mark it left with, so `bin/run.sh` is still
executable on the Mac after a round trip through a PC. Between Macs and Linux machines the marks travel
as they are.

**git.** A copied `.git` folder keeps the settings of the system it came
from. A session that aht starts (after a Hand Over, and after a Bring
Here) gets these in its environment, through `GIT_CONFIG_COUNT`,
`GIT_CONFIG_KEY_0` and `GIT_CONFIG_VALUE_0`:

- `core.filemode=false` when the machine that works on the project is a
  PC, so git does not see every file as changed;
- `core.autocrlf=true` when the project's home is a PC whose git converts
  line endings for it.

aht never edits `.git/config`, and this is not a setting. git that you
run yourself in another terminal does not get them; the dry run says what
to type there, for example *in your own terminal here:  git -c
core.filemode=false status*. Each git command takes the same `-c`.

**In the terminal:**

- `aht remote paths mac` — show where projects go on mac, rule by rule.
- `aht remote paths mac --home` — projects go to the same place below the
  home folder there.
- `aht remote paths mac --same` — projects keep their exact path there.
- `aht remote paths mac --add D:\work /Users/me/work` — projects in
  `D:\work` here go to `/Users/me/work` on mac; `aht remote paths mac
  --remove D:\work` drops that pair.

## Pick up on another machine

Go on with a project's work on another machine of yours, in any agent, and
give it back later. Only the context moves: a summary of the latest
session there, made and masked on that machine. git moves the files. Unlike
a handover, each machine keeps its own copy of the project, a clone of the
same repository for example, and the copies may sit at different paths.

> **Example.** In the evening you worked on paper with Claude Code on your
> Mac. In the morning, on the PC at work, you select paper → **Machines →
> Pick Up from mac…**. The sheet says where aht found paper on the mac
> (*found by its project id*), lists the latest sessions there and says what
> git still has to do, since the summary carries no files: *The two copies
> are at different commits (mac 817965a, here cbc07b5): bring them together
> with git before going on.* Below it is the summary: where things stood,
> the latest exchanges, the open to-dos and git. You run `git pull`, choose
> Codex under **Open in** and press **Open in Codex**. Codex opens and reads
> the summary first. Before you leave, **Machines → Hand Back to mac…**
> leaves a note in paper's folder on the mac. At home, paper shows *pc
> handed this project back at 17:30: Codex worked there from 09:10 to
> 17:20*. **Continue Session** opens your Claude session where it stopped,
> and it learns what Codex did on the PC.

- **The summary** goes into the project's `.aht/handover/` here, which git
  ignores. The other machine builds it from its own histories and masks
  there the keys and passwords aht recognises (aht masks it again here).
  It holds where things stood, the latest exchanges, the open to-dos, the
  files changed last and the state of git, and names the session it
  continues and how to go back to it there. Any agent can go on from any
  other: Claude Code, Codex, Kimi Code, Antigravity or Mistral Vibe.
- **Which session.** The latest one in that folder there; scripted
  `claude -p` runs do not count. The sheet lists the latest sessions there,
  marked *open there* or *working*, and a click picks another one. When a
  session there is working right now, aht warns that its latest turns may
  be missing from the summary.
- **How aht finds the folder there**, in this order:
  1. the project's id: in that machine's list of projects, or in the
     `.aht/.project-id` of a folder at the same path or the same place in
     the home folder there;
  2. the same git origin (compared without user name or password) and the
     same first commit, among the repositories in the folders aht watches
     there;
  3. the same path;
  4. the same place in the home folder (`~/code/paper` on both).

  The first of these that finds anything decides, and the sheet says which
  (*found by its git origin*). A folder found any other way than by its id
  could be another project: on a Mac you tick *This is the same project*
  first; aht's window says *check that it is the same project*.
- **Two folders, or none.** When the same way finds two folders (two clones
  of one repository, say), aht takes neither and lists both: *2 folders on
  box could be this project (by its git origin): /home/me/code/paper;
  /home/me/code/paper-copy*. Pick one. When aht finds none, type the
  folder's path there and press **Look There**. In the terminal,
  `--there PATH` names it.
- **git.** The summary moves no files. The sheet compares git on both
  machines and says what to do first: *On box: branch main, 1 commit not
  pushed, 1 file not committed. Commit and push there, then pull here.*, or
  that the two copies are at different commits, or that one folder holds
  no git repository. The same words head the summary, so the agent reads
  them too. aht never pulls, pushes or fetches for you.
- **Open in, or not.** **Open in Codex** (or the agent you choose among
  those installed here) writes the summary and starts that agent with it in
  a new terminal window. **Copy the Start Line** writes the summary, opens
  nothing and puts the line that starts the agent on the clipboard.
  **Cancel** (in aht's window, **Done**) writes nothing. Before an agent
  starts, the checks of *Continue in another agent* apply: not while a
  Claude session in the project here works or waits for you.
- **Back mode: the work comes back.** When the work went from here to that
  machine (you left a note on it, or it picked the work up from here), Pick
  Up from it brings the work back: the summary is a catch-up of what
  happened there since, and the session here that the work left from goes
  on (**Open Claude Code's Session** on a Mac). When that session is gone,
  a new session reads the full summary and the catch-up, and aht says so;
  another agent you open instead reads both too. The other way round,
  while work that came from box is here (you picked it up from box, or box
  left a note here), Leave a Note on box hands it back: a note for the
  session on box that the work came from, with only what happened here
  since. After a Pick Up from box, **Machines** offers it first, as **Hand
  Back to box…**. `--full` gives a full summary instead.
- **Leave a Note** (**Machines → Leave a Note on box…**) puts a summary of
  the latest work here into the project's folder on box before you go.
  Nothing runs there. aht only adds files there and never replaces one;
  when the note cannot be written there, nothing is kept here either.
- **When a note arrives** on a machine where aht is installed:
  - a notice says so, once: *pc left a note on paper* (*from Codex: “fix
    the login redirect”*), or *pc handed paper back* (*Codex worked
    09:10–17:20*). On the machine the work left from, it is *pc picked up
    paper* (*… work may go on there*). With *Also send them to my phone*
    set on that machine, the notice reaches your phone too.
  - the project shows the note: *pc left a note at 17:30: Codex worked
    there* (in aht's window, *A note from pc*), with **Read the Note…**
    and, when the note hands work back to a session here, **Continue
    Session** (in aht's window, **Continue That Session**). A Claude Code
    session gets its catch-up from aht's hook as it opens, once.
  - the next Claude Code session in the folder gets one line from aht's
    hook, once: *[aht] “pc” left a note about this project at 17:30 (Codex
    had worked on it there). If the user asks to continue that work, read
    .aht/handover/relay-….md first.* It reads the note only if you ask.
  - on the machine the work left from, a Claude session that starts in the
    folder while the work is out hears *[aht] This project was picked up on
    “pc” at 09:10 (Codex). Work may go on there: if the user asks to
    continue that work, check with them before changing anything here.*
- **A PC starts every exchange.** No machine can ask a Windows PC. So at
  the PC, Pick Up from the Mac; before you leave the PC, Leave a Note (or
  Hand Back) on the Mac. Aimed at a PC, both stop with *aht cannot ask a
  Windows machine yet. On the PC, use Pick Up or Leave a Note.*
- **What it costs.** Writing the summary costs nothing: aht reads the
  histories itself. **Open in** makes the agent read the summary as its
  first turn, which uses tokens (Kimi reads it in a run of its own before
  its window opens). When the work comes back to Claude Code's own session,
  aht's hook gives it the catch-up as it opens, and nothing runs until you
  type. The summary alone (Copy the Start Line, or `--apply` without
  `--open`) and Leave a Note spend nothing.
- **Both machines keep the record.** Each exchange leaves a small record
  next to its summary in the project's `.aht/handover/`, here and there:
  Pick Up leaves a copy of its record and its summary on the machine it
  picked up from. `aht relays` lists them (*Pick up*, *Note*).
- **What it needs:** the other machine added under **Machines** (see *Hand a
  project over to another machine*, or from a PC *A Windows PC with your
  other machines*), with its *For asking* rows in **Check** all ✓.

**In the terminal:**

- `aht pickup ~/Desktop/paper --from box` — say where paper is on box and
  how aht found it, which session there it would go on from, and what git
  still has to do; nothing is written.
- `aht pickup ~/Desktop/paper --from box --apply` — write the summary into
  paper's `.aht/handover/` here and leave a copy of it and its record on
  box; nothing opens.
- `aht pickup ~/Desktop/paper --from box --open codex --apply` — the same,
  then Codex opens here with the summary (one turn: uses tokens).
- `aht pickup ~/Desktop/paper --from box --session <id>` — go on from that
  session there; `--agent codex` goes on from Codex's latest one there.
- `aht pickup ~/Desktop/paper --from box --there /home/me/code/paper` — use
  that folder on box, when aht found none or two.
- `aht pickup ~/Desktop/paper --from box --full --apply` — a full summary,
  also when the work comes back.
- `aht leave-note ~/Desktop/paper --on box` — say what the note holds and
  where it would go on box; `--apply` leaves it. While work that came from
  box is here, it hands the work back; `--full` leaves a full summary
  instead, and `--there PATH` names the folder there.
- `aht relays ~/Desktop/paper` — every hand-off of the project, also those
  across machines.

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
- **Cancel** stops a planned night shift. A night shift that has started
  can be cancelled too, after a question (**Keep It** or **Cancel the
  Shift**): aht then does not take the project back in the morning, and it
  stays on the other machine until you take it back (**Take Back…**).

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
  you*, *named in aht*, *Claude's own title*) and the tab's title when it
  differs from the name. A key in a name or a tab's title shows masked
  there. **Rename…** gives a session a name of your choice and gives its
  tab that name too. It stays until you rename the tab, or until **Follow
  the Tab Again**. When the current name holds a masked key, **Rename…**
  starts with an empty field and shows that name greyed as a hint, so the
  masked text never becomes the name by accident.
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
  (add `&resume=1` for Kimi's own session),
  `aht://switch?path=~/Desktop/paper&back=1` (Hand Back),
  `aht://resume?path=~/Desktop/paper&session=<id>` and
  `aht://getting-started`.
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
  **Find Moved Folders**; **Bring Here** with *From box…* for each machine
  aht can ask (see *Bring a project here, and send it back*); **Look
  Back** with *Loose Ends…* and *Report…*;
  **Tidy Up (n)…** when something needs a decision (with **Choose
  Folder…**, **Reconnect**, **Forget** and, for a history without a folder
  that is not a link, **Remove…**).
- **The project list:** *Where* (here, handed over, handing over, missing,
  a session open, working or waiting for you), *In sync* (when the kept
  copy was last synced; *paused* while the project is handed over, after
  a Release, or while a sync waits for an answer), *Last used*,
  *Agents* (whose history it has).
- **Under the list, for the selected project:** **Hand Over…** or, while it
  is away, **Take Back…**, **Open Session** and **Release…**; while a
  handover is unfinished, a note with **Check Now** and **Release…** (see
  *Hand a project over to another machine*); for a project another
  machine brought there, *On pc since 14:10 (brought there from pc). Send
  it back from pc.* with **Release…**; for a project brought here,
  **Send Back to box…**; **Keep in sync**, and a note
  when a sync paused, with **Bring Them Here…**, **Replace Them…**,
  **Allow the Removals…** or **Stop Syncing** (see *Keep in sync looks
  first*);
  **Continue Session** (opens the latest session in a new terminal window);
  **Switch Agent**; **Machines**, once you added one, with *Pick Up from
  box…*, *Leave a Note on box…* and, while work picked up from box is
  here, *Hand Back to box…* (see *Pick up on another machine*); **More**,
  with *Show Sessions…*, *What Changed…*,
  *Undo a Session…*, *Journal*, *AI-Use Statement*, *Share a Session…*,
  *Project Rules…*, *Check for Secrets*, *Second Opinion…*, *Night Shift…*
  and *Show in Finder*. Notes about the project, such as the usage limit,
  appear below.
- **Sessions tab:** the open sessions here and on your other machines,
  with each Claude session's name and **Rename…**, **Go to Tab**, and for
  one worth a look **Restart in Its Tab…** or **End It…**; at the top
  **Restore Workspace…**, **Name Sessions After Their Tabs…** and
  **Refresh**.
- **Search tab:** the search over all sessions, and *Also on my other
  machines*; *Resume*, *Restore…* and *Show Project* on each result, and
  *Continue Here…* on one from another machine.
- **Machines tab:** the machines you added, with **Sync** (keep every
  project in sync with it, or stop) and how many of those syncs are
  paused, **Bring Here…**, **Check**, **Use for Handover** and
  **Remove…** (refused, with the reason, while the machine holds a
  project), and under each one **Watch**, when aht last heard from it,
  and where projects go there (in aht's window *Folders there* with
  **Change…**; see *Across systems and folders*);
  **Add Another…**; machines aht found on your
  Tailscale network or in `~/.ssh/config`, each with **Add…**, and **Look
  Again**.
- **Settings tab:** see *Settings* below.
- **The bottom line:** what aht is doing right now (with a progress bar for
  transfers) and its version.

## Settings

- **Getting started:** the main steps still to do, and **Show the Steps…**
  for the whole list (see *Getting started*).
- **Watched folders:** the folders aht watches; **Add Folder…** (the
  system's folder chooser; **Cancel** just closes it) and **Remove** (see
  *Setting up*). Before aht is installed on this Mac (the
  app alone, or Homebrew's `aht` before `aht install`), they still save the
  folders but no watcher follows them yet, and the app says so.
- **When folders change:** what to do when a folder moves or is copied:
  ask, relink automatically, or leave alone. New projects are always taken
  on as you work in them.
- **Histories:** notifications, automatic backups, **Back Up Now**,
  **Check All for Secrets…**
- **Notices:** waiting for you, done; also to your phone.
- **Chimes:** on or off; a chime each for waits for you, done and the usage
  limit; their volume.
- **The Claude app on your phone:** name sessions after their iTerm2 tabs;
  whether Remote Control is on for every session.
- **Safety nets (no tokens):** a copy of the folder at each session start,
  the usage-limit notice, Spotlight.
- **Restore my workspace:** how often the iTerm2 layout is saved, and how
  many are kept.
- **Uses tokens (off until you turn it on):** informed sessions, the offer
  of another agent at the usage limit, second opinions, the night shift.
- **Folder badges:** on or off, per kind; **Refresh All**, **Clear All…**
- **Handover:** reachable from the Claude app, compression, mosh, trust
  carried over; **Copies files with** (*rsync where both machines have it,
  else aht's own copy*, *rsync* or *aht's own copy*), with **Ask the
  Machines** and a line that says which one each machine gets.
- **Backups on another machine:** which machine keeps a copy; **Copy Now**;
  **Fetch Backups From…** (see *Backups, and bringing a session back*).
- **Where each agent keeps its history:** **Choose…** when aht did not find
  an agent's history folder itself; **Reset All to Defaults**.
- **This Mac:** **Start aht in the menu bar at login**; *Tell me when a new
  version of aht is out* and **Check Now** (see *New versions*); **Open
  session windows in** (iTerm or Terminal; automatic picks iTerm when it is
  installed); **Run Setup Again…** (the welcome window, see *Setting up*);
  **Adopt This Mac's Projects…** (tracks every folder that already has
  agent history; its question names up to three you told aht to forget,
  then *and N more*, since adopting takes them on again);
  **Reinstall or Update aht…** (sets aht up again from the app, for example
  after an update); **Restart Watcher** (before aht is installed it starts
  nothing and says the watcher is not installed yet); **Run Diagnostics**;
  **Open Log**; **Open Data Folder** (`~/.aht`); **Edit Config File**
  (every setting below, as text).

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
- A new project has no setting: aht always takes it on as you work in it.
  An older config's `new_policy` is ignored, and `aht config --set
  new_policy=…` says it is no longer used.
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
  same on Linux: how the emblems are set, and an emblem of your icon theme
  to use instead of aht's own (the git one's default is `aht-git`, aht's
  own "+").

**Backups**

- `backup_enabled` (on), `backup_interval_hours` (24), `backup_keep` (10) —
  the daily backup, how often, how many per project (copies on the other
  machine follow `backup_keep`, keeping at least 3).
- `backup_dir` (`~/.aht/backups`) — where they go.
- `offsite_backup` (none) — the machine that keeps a copy of them, in a
  folder of this computer's own.

**Handover**

- `remotes` and `default_remote` — your machines (also whether you watch
  each one, and where projects go there), set in the Machines tab or with
  `aht remote` (`aht remote paths` for where projects go).
- `mirror_interval_minutes` (30) — how often a kept copy is synced.
- `handover_excludes` (none) — more names that never travel (besides
  `node_modules`, `.venv` and the like).
- `handover_compress` (on) — compress what is sent.
- `handover_transfer` (auto) — what copies the files to and from your
  other machines: `auto` (rsync when this machine has rsync 3, the other
  has rsync, and neither is Windows; else aht's own copy), `rsync` or
  `aht` (aht's own copy). See *What copies the files* under *Hand a project over to
  another machine*.
- `handover_remote_control` (on) — a handed-over session is reachable from
  the Claude app; Antigravity, when you switch to it, starts with
  `--remote-control` too.
- `handover_carry_trust` (on) — a folder trusted here is trusted there.
- `handover_claude_args` (none) — extra options for the session over there.
- `handover_mosh` (on) — open a handed-over session with mosh when it gets
  through.
- `handover_keep_awake` (on) — the other machine does not sleep while the
  agent works there (a closed lid still does).
- `rsync_path` (the newest rsync found) — which rsync to use, when rsync
  copies the files.
- `terminal_app` (automatic: iTerm when installed, wherever it is, else
  Terminal) — the app that opens session windows; Settings → This Mac →
  *Open session windows in*. Another app name works only if that app runs
  the `.command` file aht hands it.
- `update_check` (off) — once a day, ask GitHub whether a new version of aht
  is out (see *New versions*); Settings → This Mac → *Tell me when a new
  version of aht is out*.

**Notices**

- `notify_waiting` (on), `notify_finished` (on), `notify_finished_minutes`
  (3) — a session waits for you; a piece of work that took at least that
  many minutes is done.
- `notify_phone` (none) — `imessage:<your number or Apple ID>` or
  `ntfy:<topic>`.
- `notify_limit` (on) — a session stopped at Claude's usage limit.
- `session_corner` (off) — the app lists the open Claude sessions in the
  screen's top-right corner (*Sessions in the corner*).
- `chimes` (off) — the app plays a chime when a session here is done or
  waits for you (*Chimes when a session is done or waits for you*).
- `chime_done` (Bloom), `chime_waiting` (Doorbell), `chime_limit` (Ebb) —
  which chime: one of aht's own, a sound of macOS by its name, or the path
  of a sound file; empty for none.
- `chime_done_after` (30) — "done" chimes only after at least that many
  seconds of work.
- `chime_volume` (70) — how loud the chimes are, 0 to 100.

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

- `informed_sessions` — a new session learns where the last one stopped; a
  session another agent took the work over from, resumed by hand, learns
  what happened since.
- Claude Code's own `autoContinueAtUsageLimit` (in its settings, switched
  with `aht limits --auto-continue on|off`) — a session goes on by itself
  when the usage limit resets.
- `limit_switch`, `limit_switch_to` (kimi) — at Claude's usage limit, offer
  to go on in that agent (`kimi`, `codex`, `agy` or `vibe`).
- `second_opinion` — the same task by two agents.
- `night_shift` — a handover with a task, on a timer.

## Only in the terminal

These commands have no button, because you need them rarely or they fix
things by hand. Those that change something show what they would do first
and act only with `--apply`; `install` and `uninstall` act at once.

- `aht tag ~/Desktop/paper --apply` — start tracking a folder now, instead
  of waiting for aht to find it.
- `aht adopt --apply` — track every folder under the watched folders that
  already has agent history (the window's *Adopt This Mac's Projects…*),
  also one you told aht to forget; the list marks those *(you told aht to
  forget it)*.
- `aht orphans` — list Claude histories that no tracked folder owns;
  `--match` suggests the folder each one belongs to.
- `aht suggest-matches --store <name>` — the likeliest folders for one such
  history.
- `aht bind --store <name> --to ~/Desktop/paper --apply` — connect that
  history to the folder.
- `aht prune --apply` — stop tracking folders that are gone (their histories
  stay) and drop entries listed twice.
- `aht forget ~/Desktop/paper --apply` — stop tracking a folder. It keeps
  its `.aht/.project-id`, but aht's scans no longer take it on again
  (*Tidy up* lists every way it comes back); `--remove-marker` also removes
  the marker.
- `aht roots` — the folders aht watches; `--add ~/code` and `--remove …`
  change them.
- `aht reload` — make the watcher read its settings again. On a Mac
  before aht is installed (aht.app before setup, Homebrew's `aht` before
  `aht install`), it changes no watcher, and neither do `aht roots
  --add`/`--remove`, `aht config --set watch_roots=…` or `aht setup --apply
  --roots …`: they say *the watcher is not installed yet — run 'aht
  install' to set it up*. The folders are saved all the same.
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
  `--remove-icons` also clears the badges (on Linux also aht's emblem
  images, and their icon cache when no other icons are left there; when
  others are, the cache is written again without aht's); `--purge` also
  removes aht's markers, list of projects and settings.
- `aht hook` — what Claude Code runs when a session starts and at each
  prompt; not for typing yourself.
- More options: `--roots ~/code ~/src` (for `adopt`, `orphans`,
  `suggest-matches`, `reconcile` and `icons`) looks in those folders instead
  of the watched ones; `--no-reload` (for `config` and `roots`) leaves the
  watcher running as it is; `aht search --update` only brings the search
  index up to date, `--no-update` searches without doing that first;
  `aht mirror --run --due` syncs only the copies that are due;
  `aht logs --lines 200` is the long form of `-n 200`.
- An option that takes several values adds up when you give it twice:
  `--adopt A --adopt B` is the same as `--adopt A B`, and
  `aht config --set backup_keep=20 --set notify_finished=false` sets
  both.
- Options such as `--json`, `--quiet`, `--status-file`, `backup --auto`,
  `second-opinion --run`, `night-shift --step` and `tab-names --refresh` are
  what the app and aht's background jobs use; `--json` gives any command's
  answer in a form scripts can read.

## Where things are

- `~/.aht/` holds aht's own data: `registry.json` (which folder is which
  project), `config.json`, `machine.json` (this computer's random id),
  `offsite.json` (which backups went to which machine), `backups/`,
  `search.db`, `aht.log`, `handover/`,
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
