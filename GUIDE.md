# aht guide

aht keeps the history of your AI coding agents connected to your project
folders: Claude Code, Kimi Code, Codex, Gemini CLI, Cursor, OpenCode and
Copilot. Once it does that, it can search those histories, continue a
project in another agent, or hand a project over to another machine of
yours.

This guide shows aht on macOS, with its window. On Windows and Linux the
window opens from the tray (**Open aht…**) or with `aht window`: the same
tabs and dialogs, without what needs macOS (iTerm2, Spotlight, Finder, the
session corner, chimes). See *On Windows and Linux*; the README's
*Platforms* table lists every feature per system.

Each feature comes with an example and ends with its commands, each
followed by what it does. Everything the window does can also be done with
the `aht` command. A command that changes something shows what it would do
first, and acts only with `--apply`.

## Where to find things

- **The ∞ in the menu bar.** The number next to it counts the sessions
  that wait for you. The menu shows the status (also a project where
  Claude stopped at its usage limit), **Open aht…**, **Guide**, **Search
  Sessions…**, **Sessions in the Corner** and **Chimes** (each on or off),
  **Find Moved Folders Now**, **Pause / Resume Watching** and **Quit**. It
  changes nothing on its own, so a stray click is harmless.
- **From anywhere:** ⌃⌥⌘A opens the search. **In Finder**, right-click a
  project folder: under **Quick Actions** (or **Services**) are *aht: Show
  in aht*, *What Changed*, *Journal*, *Search This Project* and *Continue
  in Another Agent*.
- **The window** (∞ → Open aht…) has five tabs: **Projects**, **Sessions**,
  **Search**, **Machines** and **Settings**. In the Projects tab you select
  a project first, then press a button. Anything that moves or changes
  files asks before it starts.
- **The ? buttons** open this guide at the feature's section. The **?** at
  the top of the window opens the whole guide, with every section in a
  list, also *All settings, one by one* and *Only in the terminal* for
  what has no button.
- **Spotlight** finds your sessions by title, and **aht:// links** open
  parts of the window from the Shortcuts app or a script (see *Spotlight,
  Shortcuts and links*).

## Setting up

The first time you open aht, a welcome window sets it up. **Quick Setup**
does it in one step; **Choose Each Step** lets you decide everything.
Nothing leaves your computer while aht sets up.

> **Example.** You open aht for the first time. It found 14 projects with
> agent history in Desktop and Documents, and your agents' histories show
> that you also keep projects in ~/Developer. **Quick Setup** watches those
> three folders, takes on the 14 projects and starts aht at login.

- **Quick Setup** watches the folders where your projects are: Desktop and
  Documents, folders such as ~/Code or ~/Projects if you have them, and any
  folder right under your home that your agents' histories point to. It
  takes on every project there that already has agent history, except one
  you told aht to forget, and later each new project as you work in it.
  The first time, it also asks before it relinks a folder that moved or
  was copied, badges project folders, backs up the histories once a day
  and starts at login; its page lists what it will do.
- **Choose Each Step:** the folders to watch (tick them, or add one), which
  of the projects found to take on (one you told aht to forget is listed
  unticked, marked *you told aht to forget it*), what to do when a folder
  moves or is copied, and the extras: folder badges, backups, notices and
  start at login.
- **Start at login keeps your answer.** Once you said whether aht starts at
  login (the Windows installer asks; so do the switch in Settings and the
  tray's own), setting up keeps that answer. When it stays off, Quick
  Setup's page says so, with a switch (a box in aht's window) that turns it
  on right there; *Choose Each Step*'s *A few more* page has the same
  switch. Only a first setup before you answered (on a Mac, also one that
  installs aht) turns it on by itself.
- **Stay up to date:** both end with a step that asks whether aht may tell
  you when a new version is out (**Yes, Tell Me** or **No Thanks**; see
  *New versions*).
- **Never offered:** ~/Library (on Windows AppData and scoop), hidden
  folders, and folders aht never looks into, such as `node_modules`,
  `build` or `venv`. Projects there are listed as *outside these*: they
  keep their history, but aht does not follow them when they move.
- **When aht is not installed on this Mac yet** (the first time, and from
  **Run Setup Again…** or `aht://welcome`), setting up also installs the
  watcher, the Claude Code hooks and the `aht` command; `aht uninstall`
  undoes all of it.
- At the end the window shows *Getting started*.
- **Not Now**, or closing the welcome window, sets nothing up; the
  welcome then waits for the next version (**Run Setup Again…** opens it
  sooner).
- **To change it later:** Settings (**Watched folders**, **When folders
  change** and the rest), or **Run Setup Again…** (on a Mac also an
  `aht://setup` link). It starts from your current settings, keeps your
  rules for folders that move, badges, backups and start at login, and
  lists what it will apply.

**In the terminal:**

- `aht setup` — show the folders aht would watch and the projects there
  that it does not track yet, marking one you told aht to forget (`--json`
  also lists the projects outside those folders, as `elsewhere`, and gives
  a forgotten one `"forgotten": true`).
- `aht setup --apply` — watch those folders and take on those projects,
  except ones you told aht to forget.
- `aht setup --apply --roots ~/Desktop ~/Developer --adopt ~/Desktop/paper
  --moves apply --badges off` — choose the folders to watch, the projects
  to take on (`--adopt` with nothing after it: none; naming a project you
  told aht to forget takes it on again), what to do when a folder moves
  (`--copies` likewise), and the extras (`--backups`, `--notifications`,
  `--update-check`, each `on` or `off`).
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
  list need iTerm2 (free, from iterm2.com).
- **iTerm2's Python API** (iTerm2 → Settings → General → Magic → *Enable
  Python API*). Without it, a session still takes its tab's title, but a
  name you give a session does not reach its tab.
- **Permission to control iTerm2.** macOS asks once whether aht may
  control iTerm2. **Ask Now** asks right away (it opens iTerm2 first,
  since macOS asks only about an app that runs). If the answer was no, Go
  to Tab, clicks in the corner list and Restore Workspace do nothing:
  **Open Privacy Settings…** goes to System Settings → Privacy & Security →
  Automation, where you can allow it.
- **Start at login.** The corner list, the chimes and saving the iTerm2
  layout work only while the app runs. Once you said no to it, the list
  shows it as optional (○), not as a step still to do.
- **Your sessions in the Claude app** (optional): Remote Control in Claude
  Code (`/config` → *Enable Remote Control for all sessions*) puts every
  session into the Claude app on your phone, under its tab's name.
- **Sessions in the corner** and **Chimes** (optional; off until you switch
  them on).
- **iTerm2's blue dot** (optional). Once the corner list shows how each
  session is doing, the dot on every tab that printed something new tells
  you little; for calmer tabs, turn off iTerm2 → Settings → Appearance →
  Tabs → *Show new-output indicator*.
- **Tab colours for Restore Workspace** (optional) come from the window
  state iTerm2 keeps to bring its windows back; without it, restored tabs
  open without their colours.

aht reads these settings of iTerm2 and Claude Code but never changes them.

**In the terminal:**

- `aht getting-started` — the same list: ✓ done, ✗ a main step still to do,
  ○ an optional one. `aht install` ends with it.
- `open aht://getting-started` — open the list in the app.

## On Windows and Linux

aht's window on Windows and Linux is a page that aht serves to your own
computer and shows in an app window of Edge or Chrome (or a tab of your
browser when neither is there). It has the Mac window's tabs (Projects,
Sessions, Search, Machines and Settings) and its dialogs, the guide, the
welcome window and Getting started.

> **Example.** On Windows you click aht's icon in the taskbar's corner and
> choose **Open aht…**. A window opens with your projects; you select
> *paper*, then **More → Show Sessions…**, and **Continue** opens that
> session in a console window.

- **Only you get in:** the page is served at 127.0.0.1, so nothing outside
  this computer reaches it. The tray opens it with a code that works once
  and gives the page a cookie and a key of its own, which every request
  that runs a command needs, so another website, or another server on
  this computer, cannot use it. On Linux the server also refuses other
  accounts. It runs only the aht commands the window needs.
- **It stops by itself** 15 minutes after its last window closed (an open
  window keeps it going). If it stopped anyway, for example after an
  upgrade, the window says so: open it again from the tray, or with `aht
  window`.
- **Continue** and **Switch Agent** open a console window on Windows, in
  the project's folder. On Linux they open the first terminal they find of
  x-terminal-emulator, gnome-terminal, kgx, konsole, xfce4-terminal, tilix,
  terminator, alacritty, kitty, foot and xterm. When none opens, the
  window says *No terminal window opened* and shows the line to run by
  hand.
- **Choosing a folder** opens the system's folder chooser. On Windows it
  has a *Folder:* field for a typed or pasted path (also in quotes, with
  `%VARIABLES%`, or a network path such as `\\server\share\…`); This PC,
  Libraries or Network cannot be chosen. On Linux the chooser is zenity's
  or kdialog's; with neither, the window asks you to type the path.
- **Notices** come from the tray: a session that waits for you, a long one
  that is done, Claude's usage limit, a new version, a project that came to
  this PC. On Windows a click on one opens the window; a click on *shop
  came from mac* is Continue here (see *A Windows PC that answers*).
- **Where the window differs from the Mac's:** the Projects tab has no
  machine menu, **Sync Now**, **Find Moved Folders** (the tray's
  **Reconcile now** does that) or *In sync* column; **Peek…** with **Open
  Its Window** stands in for Open Session, and **Release from box…** is
  under **More**. The Sessions tab has **Refresh** and **End Process…**
  only. A search
  result offers **Continue**, no Show Project. Tidy Up offers **Choose Its
  Folder…**, **That's It** and **Forget…**; reading or removing a history
  is done in the terminal (`aht tidy --show`, `--remove-history`).
  Settings has *This computer* instead of *This Mac*, and no Chimes, *The
  Claude app on your phone* or *Restore my workspace*.
- **Your other machines:** a PC asks your Mac and Linux machines, picks up
  their work, hands projects over to them and brings theirs here (see *A
  Windows PC with your other machines*). With an ssh server on the PC,
  they can hand projects over to it too (see *A Windows PC that answers*).
- **Start at login:** Settings → This computer → *Start aht's tray at
  login* (on Windows the tray then also keeps the watcher running). On
  Linux the switch can be turned on only when the tray can run: it needs
  PyGObject and an AppIndicator library, and until then *Getting started*
  lists the packages (and, on GNOME, the AppIndicator Support extension).
  When the path to Python holds a `%`, the login entry starts that
  Python by its real path, or `python3` on your PATH.
- **Getting started** lists what this computer still needs: start at
  login (optional once you said no to it); on Linux the tray's packages,
  notify-send for notices, and zenity, kdialog or yad for questions; and,
  all optional, Edge or Chrome to show the window as an app, on Windows
  Windows Terminal, your sessions in the Claude app, and new versions.
- **Installing on Windows:** the installer from the releases page
  (`aht-setup-…-windows-x64.exe`, or `-arm64` on an ARM computer) asks no
  administrator password. It puts aht in your `AppData\Local\Programs\aht`,
  sets up the hook and the watcher, which starts at sign-in, offers to put
  `aht` on your PATH, and opens aht's window with the welcome. On the
  first install only, it asks whether to *Show aht's tray icon when I sign
  in*. An upgrade (the installer, **Upgrade**, Scoop, winget or `aht
  install`) keeps what you set. Start menu → **aht** opens the window
  again. Settings → Apps → **aht** → *Uninstall* removes it and leaves
  your history as it is.
- **Installing on Linux:** from a checkout, `cd linux && ./install.sh`
  (the `install.py` at the top of the checkout is the Mac's); the tray is
  `python3 linux/tray.py`.

**In the terminal:**

- `aht window` — open aht's window (it starts the server when none runs).
- `aht window --no-open` — only serve it and print the address to open.
- `aht autostart on` — start aht's tray at login (`off` to stop; without
  either, say whether it does). This also counts as your answer for the
  welcome. On a Mac it changes nothing (the app has the switch).

## A Windows PC with your other machines

From a Windows PC, aht can ask your Mac and Linux machines what runs
there, pick up their work, hand projects over to them and bring their
projects here. It uses Windows' own ssh. For all of this the PC does the
asking, so it needs no ssh server. To let a Mac or Linux machine hand
projects over to the PC as well, see *A Windows PC that answers*.

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
   switched off, since aht's ssh never asks for a passphrase. In an
   administrator PowerShell: `Get-Service ssh-agent | Set-Service
   -StartupType Automatic; Start-Service ssh-agent`. Then, in a normal
   one: `ssh-add`. Or use a key without a passphrase.
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
  there*. Each one marked ✗ comes with its fix: the ssh-agent steps above
  when the key was not accepted, *Connect once in a terminal (`ssh
  you@homebox`) and accept the machine's key* when the PC does not know
  that machine yet, and *Turn on Remote Login on the Mac* when a Mac
  refuses the connection.
- **For handing over:** what a handover to that machine needs (tmux,
  Claude Code, your home folder or where projects go there, staying awake)
  and what copies the files (from a PC always *aht's own copy*). Bring
  Here and Send Back need only the rows for asking, and aht installed on
  that machine.

**What a PC can do with them:**

- add, check and remove them; `aht remote discover` lists the machines on
  your Tailscale network;
- see their open sessions in the Sessions tab, **Watch** them (the tray
  tells you when a session there waits for you or is done), and search
  their sessions too (**Also on my other machines**; see *Search every
  session*);
- **Pick Up** a project's work from them, and **Leave a Note** on them
  before you leave the PC (**Machines** under the project; see *Pick up on
  another machine*);
- **Hand Over** a project to one of them and **Take Back** it, as a Mac
  does (see *Hand a project over to another machine*). **Peek…**, then
  **Open Its Window**, opens a console window with `ssh -t` to the session
  there (Windows has no mosh). **Keep in sync** and the **Night Shift**
  work from the PC too;
- **Bring Here** a project of theirs and **Send Back** it when you are done
  (see *Bring a project here, and send it back*). The tray lists what came
  this way under **Projects brought here**;
- keep a copy of its backups on one of them, and fetch backups from it
  (see *Backups, and bringing a session back*). aht's own copy moves the
  files, so the PC needs no rsync.

Pick Up, Leave a Note, Bring Here and Send Back always start on the PC:
no machine picks up work from a PC, leaves a note on it or brings a
project from it. While the PC holds a project it brought, the project at
home says *On pc since 14:10 (brought there from pc). Send it back from
pc.*, with **Release…** for a PC that is gone. A PC that answers also
takes Hand Over and Take Back from them, and then a project it brought can
be taken back at home too (*… or take it back here*); it also takes Keep
in sync and their backups, a Send Back of what it handed over, and
projects handed over from another PC (see *A Windows PC that answers*).

The project usually sits at another path on the PC (`C:\Users\me\code\shop`
for `/Users/me/code/shop`): see *Across systems and folders*.

> **Example.** Your office PC broke, and it kept its backups on homebox.
> On the new PC, add homebox, pick it under **Settings → Backups on
> another machine** and press **Fetch Backups From…**. The list shows
> *office-pc*, with its system, its last update, its projects and
> backups; **Fetch** brings them to the new PC. **Search** then finds the
> old sessions, and **Restore…** brings one back. A file another program
> holds open on the PC (or that Windows Security is reading) is tried
> again 5 times, 0.2 s apart; if it is still held, that one file is named
> as not fetched, and the rest arrive.

**In the terminal (in PowerShell):** the commands of the sections linked
above, with Windows paths, for example:

- `aht remote add homebox you@homebox`, then `aht remote check homebox`.
- `aht pickup $HOME\Desktop\paper --from homebox` — show what picking up
  paper's work from homebox would bring; `aht leave-note
  $HOME\Desktop\paper --on homebox --apply` leaves a note there.
- `aht handover $HOME\code\shop --to homebox --apply` — hand shop over;
  `aht bring --from homebox --list` lists what could come here; `aht
  send-back $HOME\code\shop --apply` returns a project brought here.
- `aht backup --fetch-offsite --from office-pc` — fetch that computer's
  backups to this PC.

## A Windows PC that answers

Optional. With an ssh server on the PC, your Mac or Linux machine can
hand a project over to the PC and take it back, keep projects in sync
with it, keep its backups there, send back a project the PC handed over,
watch the PC, list its sessions and search them. Another PC can hand
projects over to it too. Without one, the PC still does everything in the
section above.

> **Example.** You leave the Mac for the PC in the other room. On the
> Mac, **Hand Over…** sends shop to pc. No session starts on the PC: its
> tray says *shop came from mac — Continue here*. Click it, and Claude
> Code opens in a console on the PC, in the session you left on the Mac.
> Nothing runs until you type. Back at the Mac, **Take Back** brings
> home what you did on the PC.

- **Hand Over to the PC.** The files, Claude Code's history and the
  handover summary go to the PC with aht's own copy (no rsync). No session
  starts there. The PC's tray offers **Continue here** once as a notice
  and then in its menu, until you use it (or remove it under **Dismiss**)
  or the project leaves; after `--no-start` it offers nothing. Continue
  here opens Claude Code in a console, in the session that was handed
  over, in the permission level the handover named (never more), and the
  session is told that it changed machines.
- **Continue here works once,** since that session may still be open.
  Run again (`aht _arrival --continue <name>` on the PC), it says it was
  used already; `--again` opens it once more anyway.
- **Take Back from the PC**, as from any machine: what changed on the PC
  comes back, and the PC drops its Continue here. Or, with the Mac added on
  the PC, **Send Back to mac…** there returns it (see *Bring a project
  here, and send it back*).
- **Keep in sync with the PC**, as with any machine (see *Keep in sync
  looks first*): aht's own copy moves the files, the PC notes the folder
  as a copy kept in sync, and the sync pauses when the copy on the PC was
  changed, when it would remove many files there, or when the folder there
  holds something else; **Bring Them Here…** takes the PC's changes. A name
  Windows cannot hold (`aux.md`, `a:b.txt`) stops a sync before anything
  is sent.
- **Backups kept on the PC:** pick it under **Settings → Backups on
  another machine**. Each computer's backups go into a folder of its own
  in `~\.aht\offsite\` on the PC, and **Fetch Backups From…** brings them
  back, also on a new computer.
- **Send Back to the PC:** a project the PC handed over to your Mac (or a
  Linux machine) goes back with **Send Back** on that machine, as to any
  machine, once the PC is added there; the PC plans the way back against
  its record and keeps both versions of a file changed on both sides.
- **From one PC to another:** a PC hands a project over to another PC that
  answers, and takes it back, as a Mac does: the files go with aht's own
  copy, the other PC's tray offers Continue here.
- **Watch** the PC, see its open sessions in the Sessions tab, and
  **search** its sessions (**Also on my other machines**).
- **Claude Code** must be installed on the PC. If its version differs from
  this machine's, the first handover runs `claude install <version>`
  there.
- **Not on a PC:** no session starts by itself, so a handover's task waits
  in the summary until you continue. `--agent` (Codex, Kimi Code,
  Antigravity, Mistral Vibe) and the night shift go to Mac and Linux
  machines only. aht never ends a session on the PC (`--stop` does not),
  so exit it there before you take the project back. **Open Session** has
  nothing to open. Pick Up, Leave a Note and Bring Here with a PC still
  start on the PC; Send Back starts there too, or, for a project the PC
  handed over, on the machine that has it.

**What answers on the PC:** aht installed there, at least as new as this
release, or else aht's own copy with the PC's Python 3 (`py`, or
`python`). With neither, adding the PC stops with *install aht on pc* (or
*update aht on pc*) and makes nothing there. Install aht on the PC in any
case: its tray is what offers Continue here.

**Once, on the PC** (the commands in an administrator PowerShell, the
files in an administrator Notepad):

1. **OpenSSH Server.** Settings → System → Optional features → View
   features → *OpenSSH Server* → Add. Then: `Start-Service sshd;
   Set-Service sshd -StartupType Automatic`.
2. **Your key.** On the Mac, show your public key: `cat
   ~/.ssh/id_ed25519.pub` (make one with `ssh-keygen -t ed25519` if there
   is none). On the PC, paste that one line into a file:
   - a standard account: `C:\Users\<you>\.ssh\authorized_keys`;
   - an account in the Administrators group: Windows reads only
     `C:\ProgramData\ssh\administrators_authorized_keys`, never the
     file in your own folder. Then let only Administrators and SYSTEM
     read it:
     `icacls C:\ProgramData\ssh\administrators_authorized_keys
     /inheritance:r /grant "Administrators:F" /grant "SYSTEM:F"`.
3. **Try it from the Mac:** `ssh <you>@pc`. It must log in without a
   password; answer *yes* to the machine's key once (aht never accepts a
   key for you). Type `exit`.
4. **Passwords off.** Once step 3 works, open
   `C:\ProgramData\ssh\sshd_config` and set
   `PasswordAuthentication no` (remove the `#` in front). Save, then:
   `Restart-Service sshd`. From now on only your key logs in.
5. **The firewall.** The OpenSSH Server feature opens port 22 to every
   network. Let it answer only on your Tailscale network, or only on your
   own local network, one of:
   - `Set-NetFirewallRule -Name OpenSSH-Server-In-TCP -InterfaceAlias
     Tailscale` (only over Tailscale);
   - `Set-NetFirewallRule -Name OpenSSH-Server-In-TCP -RemoteAddress
     LocalSubnet` (only from your own network).
   `Get-NetFirewallRule -Name OpenSSH-Server-In-TCP |
   Get-NetFirewallAddressFilter` shows what it lets in.
6. **Never change the network's profile.** Leave Windows' network as it
   is (Public stays Public). The scoped rule is all ssh needs; making a
   network Private opens more than ssh.
7. **aht, or Python.** Install aht on the PC (its tray offers Continue
   here), or at least Python 3: `winget install Python.Python.3.12`.
8. **Leave ssh's shell as it is.** Windows' ssh server runs commands in
   cmd.exe. aht's command line reads the same in PowerShell, but cmd.exe
   is the one it is tried with.

Then add the PC on the Mac (**Machines → Add Another…**, then **Check and
Add**; on Linux, **Add a Machine…** in aht's window). A PC has its own
check rows: *aht answers there*, *Claude Code there*, *aht installed there
(its tray offers Continue here)*, *no session starts there* and where
projects go there (see *Across systems and folders*); none for tmux,
keeping awake or mosh. `aht remote discover` lists the PC when it is on
your Tailscale network.

What aht reads and writes on the PC is in PRIVACY.md (*A PC that
answers*).

**In the terminal (on the Mac):**

- `aht remote add pc you@pc` — add the PC; it says what answers there.
  `aht remote check pc` checks it.
- `aht handover ~/code/shop --to pc` — show what handing shop over to
  the PC would send, and where it goes there; `--apply` does it.
- `aht reclaim ~/code/shop --apply` — take it back.
- `aht mirror ~/code/shop --on --to pc` — keep shop in sync with the PC;
  `aht mirror ~/code/shop --run` syncs now.
- `aht config --set offsite_backup=pc` — keep a copy of the backups on the
  PC; `aht backup --offsite` copies now.
- `aht send-back ~/code/notes --apply` — return a project the PC handed
  over to this Mac.

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
  install --here`), each in a terminal window. With aht's Windows
  installer (or winget, which runs it), Upgrade downloads the new
  installer from GitHub, checks it against the release's checksums and
  runs it; aht starts again when it is done, and its window opens again
  if it was open. A copy downloaded from the releases page opens that page
  instead (**Open the Download Page**). On Linux, which installs from a
  checkout, the button opens the release page too, and the update says
  what to do: `git pull` in your copy of aht, then `linux/install.sh`
  again.
- The ∞ menu says *aht 0.14.0 is out* until you upgrade, and leads to the
  same page.

**In the terminal:**

- `aht update` — whether a newer version is known, from the last look.
- `aht update --now` — ask GitHub now.
- `aht update --upgrade` — upgrade the way aht was installed, as above
  (a Mac checkout opens the download page).
- `aht config --set update_check=true` — look once a day.

## What uses tokens

aht's own work never uses an agent's tokens: watching folders, badges,
backups, search, the Sessions tab, notices, loose ends, reports, the
journal, the secrets check, *What Changed*, *Undo a Session* and Spotlight
all run on this computer without asking any model.

A few features make an agent read or work, and that counts against your
plan or API bill. They are **off until you turn them on**, in **Settings →
Uses tokens**, or when you first use them:

- **A new session learns where the last one stopped:** a few hundred tokens
  per new Claude Code session.
- **Offer another agent at the usage limit:** when you accept, the other
  agent reads a summary.
- **Second opinion:** two agents work on the same task.
- **Night shift:** the agent on your other machine works on your task.
- **Going on by itself after the usage limit** (Claude Code's own setting;
  the Mac app switches it in the same group, elsewhere `aht limits
  --auto-continue on`): the session works on when the limit resets.

Some spend tokens each time you use them, usually one turn of the agent
that goes on, which reads a summary or a catch-up first: **Switch Agent**,
**Hand Back** to Codex, Kimi Code, Antigravity or Mistral Vibe, **Pick
Up** with **Open in**, and **Hand Over** or **Bring Here** into one of
those four. **Hand Over** with a task starts the session on that task (on
a PC nothing runs until you type). Going on in Claude Code's own session
(Hand Back, or Switch Agent to *its own session*) runs no turn: the
catch-up is in the session when it opens, and Claude reads it with your
next message. Writing a summary, **Summary
Only**, `aht relays`, a Pick Up that opens nothing and **Leave a Note**
spend nothing, except that Kimi Code in never-ask mode reads its summary
even for **Copy the Start Line** (see *The permission level follows the
work*).

A few things put one line into a new Claude session in the project's
folder, without a turn of their own: a project that is handed over, whose
handover did not finish, or that just came back or was released; a
session another agent took the work over from, when you resume it
yourself; and a folder whose work was picked up elsewhere or that got a
note (see *Pick up on another machine*).

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
  Now** (on Windows and Linux, the tray's **Reconcile now**).
- **Only the case changed** (`proj` renamed to `Proj`, on a Mac or Windows,
  where both name one folder): the folder keeps its history without a
  question, unless Settings say to leave moves alone; Claude Code's start
  hook does the same at the next session. A watched folder renamed only in
  case (`~/code` to `~/Code`) is fine too: aht looks into watched folders
  as they are spelled on disk.
- **Moved right after its first session**, before aht noted where Claude
  Code keeps its history: the next session in the new place still brings
  that history along.
- **Settings → When folders change** decides whether aht asks, relinks on
  its own, or leaves things alone. New projects are always taken on as you
  work in them.
- **The watcher** is what notices a move as it happens: it runs in the
  background from login and relinks the histories of a folder you moved or
  renamed at once, for every agent, so your sessions follow the folder.
  Without it (`watcher_owner` set to `none`), only Claude Code's start
  hook relinks, when a session starts in the moved folder, and **Find
  Moved Folders Now** catches up on the rest.

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
- Settings → **Folder badges** turns each kind on or off, with **Refresh
  All** and **Clear All…**.

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
  a random id, so a lost or broken computer does not take the histories
  with it. Copying only adds: a backup there goes only after aht removed it
  here, and at least 3 per project always stay. The copies aht makes
  before it rewrites a history go there too, and aht never removes those
  there. **Copy Now** copies at once. A Windows PC copies with aht's own
  copy, so it needs no rsync (see *A Windows PC with your other machines*),
  and a PC that answers can keep the backups of your Mac and Linux
  machines too (see *A Windows PC that answers*).
- **Fetch Backups From…** (in the same group) brings backups back, for
  example on a new computer. It lists every computer's folder of backups on
  that machine, with its name, system, last update, projects, backups and
  size; this computer's own is marked, and so is one an older aht made.
  **Fetch** adds what is missing here and replaces nothing: a backup that
  differs from one of the same name here arrives next to it as
  `<stamp>-from-<name>.zip`. Search then finds the sessions in them, and
  **Restore…** on a result brings one back. When a backup cannot be put
  in place, the others still arrive, and aht names it with why.
- **An older aht's folder** there (named after this computer) becomes
  this computer's own only when everything in it is here too. Otherwise it
  stays, listed as *older aht*, and **Fetch Backups From…** can bring its
  backups here.

**In the terminal:**

- `aht backup` — back up every project's histories now, instead of waiting
  for the daily run (also **Back Up Now** in Settings → Histories);
  `--project ~/Desktop/paper` or `--uuid <id>` backs up one project only.
- `aht backup --list` — list the backups that are kept, per project.
- `aht backup --prune` — delete the backups beyond the number kept
  (`backup_keep`, 10).
- `aht restore ~/Desktop/paper` — say which backup of the paper project
  it would use (the newest); `--apply` adds it back: sessions that are
  missing return, nothing that is there is changed.
- `aht restore ~/Desktop/paper --uuid <id> --apply` — restore a project's
  backups into a folder that lost its marker (`aht restore` suggests the
  id; `aht search` prints this line for a session only a backup holds).
- `aht restore ~/Desktop/paper --stamp 20260901-120000 --apply` — use that
  older backup instead (the stamps are in `aht backup --list`).
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
  two computers share asks for the id.

## Search every session

One search over every session of Claude Code, Kimi Code, Codex,
Antigravity and Mistral Vibe, in every project, including sessions that
were deleted since and live on only in a backup.

> **Example.** "Where did we decide how to deploy the API?" Type
> `deploy api` in the **Search** tab. Each result shows the project, the
> agent, when it was, and the matching lines with your words in bold.
> **Resume** opens that session in a new Terminal window; **Show Project**
> jumps to the project.

- Every word has to appear. Put "a phrase" in quotes. The last word may be
  the start of a word: `deplo` also finds deploy and deployment.
- What aht recognises as a key or a password (see *Secrets check*) is
  masked whole before it reaches the search index, also in tool calls and
  session titles.
- After an update from an earlier version, the index is built anew once,
  by itself. A session whose history file is gone and that no backup holds
  is then no longer found.
- **Also on my other machines:** tick it (it shows once you added a
  machine), and each of your other machines searches its own index too,
  all at once, with up to 20 seconds each. This computer's results come
  first; each one from another machine carries that machine's name and
  offers, instead of Resume and Restore, **Continue Here…**: it picks up
  that session's work into the project's folder here (see *Pick up on
  another machine*), the folder aht tracks under the same name, or one you
  choose. A line names each machine that could not be searched, and why
  (not reachable, or *no search index (aht is not installed there)*);
  *Also searched:* lists the others, with how many results each gave and
  when its index was last updated. A result from a Windows PC says
  *Continue it on pc* instead, since the PC starts a Pick Up itself. aht
  builds no index there, changes none, and keeps nothing of what came
  back; keys are masked there and again here.

**In the terminal:**

- `aht search deploy api` — find the sessions in which both "deploy" and
  "api" appear, in every project.
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

The **Sessions** tab lists every open agent session on this computer and on
each machine you added, with its state: **working**, **waiting for you**
(and for what), or **idle**, and under each Claude session its name (see
*Session names from your iTerm2 tabs*). The menu bar says how many are
waiting for you.

> **Example.** You start agents on three projects and go for lunch. Back,
> the Sessions tab shows *paper — waiting for you: approve Bash*; the other
> two are still working. You answer the one that waits.

- **Go to Tab** brings the iTerm2 tab of that session to the front. On
  Windows and Linux the window offers **End Process…** on each Claude
  session here instead of the buttons below.
- **Worth a look**, each with a reason: a session **open twice** (the same
  conversation runs in two processes, which both write to it; **End It…**
  closes one); one **working for hours with nothing written** (probably a
  leftover; **End It…**); one **not in the Claude app** (it started before
  Remote Control was on for every session); one on an **older Claude
  Code** (it still runs the version it started with).
- **Restart in Its Tab…** ends such a session (when it is idle or stuck)
  and starts it again in the same tab, where it left off and with the
  options it had (permissions, model, effort, extra folders). It then runs
  the installed Claude Code and shows in the Claude app. Text typed into
  it but not sent is lost.
- Ending a session keeps its conversation: `claude --resume` continues it.
- A session stopped at **Claude's usage limit** says when the limit
  resets, and *continues by itself then* when Claude Code's own setting
  for that is on (see *Continue in another agent*).
- **Another agent in a handover's window** (see *Another agent on the other
  machine*) shows **working** while its window wrote output in the last 15
  seconds, then **quiet for 6 min**, and **exited** once it ended. aht
  cannot tell whether a quiet agent is done or waits for your answer.
- **A machine that does not answer** (asleep, switched off, offline) keeps
  its place in the list. Its sessions show greyed as they were when it
  last answered (*as of 11:40*), and its line says since when it has not
  answered.

**In the terminal:**

- `aht board` — list the open agent sessions on this computer and on your
  other machines, and whether each one is working, waiting for you or
  idle; `--local` only this computer's (quicker).
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
- Keys in the agent's last message and in session titles show masked (a
  private key as *[private key: BEGIN RSA PRIVATE KEY]*).

**In the terminal:**

- `aht loose-ends` — list the projects of the last 30 days that have
  something left open.
- `aht loose-ends --days 7` — the same for the last week only.

## Know when a session needs you

aht checks the open sessions every 30 seconds, and tells you when one starts
**waiting for you** or **finishes** a piece of work that took at least 3
minutes (`notify_finished_minutes`). That is every session here; on
another machine, those of a machine you watch (every 2 minutes) or that
holds a project of yours (about once a minute).

> **Example.** You hand a benchmark over to your machine at home and go into
> a meeting. Half an hour later a notice says *paper on homebox waits for
> you: approve Bash*. With **Also send them to my phone** set, it arrives on
> your phone too.

- **A click on a notice** brings the tab of that session to the front (a
  session on another machine opens the Sessions tab). The first time,
  macOS asks whether aht may show notifications; allow it. Without the aht
  app running, aht starts it briefly to show the notice.
- **Settings → Notices:** choose which notices you want. For the phone,
  enter `imessage:` followed by your own number or Apple ID (it arrives as
  a message to yourself), or `ntfy:` followed by a topic you follow in the
  free ntfy app (or your own ntfy server's address). **Send a Test** shows
  how it looks.
- **Only encrypted:** an ntfy server's address must start with `https://`,
  since a notice names your projects, sessions and machines. aht refuses
  `http://` (*… is plain http, so the notices would cross the network
  unencrypted*), except for a server on this very computer (`localhost`,
  `127.0.0.1` or `[::1]`). An `http://` address set before aht refused it
  gets no notices; the log says why, and **Send a Test** too.
- **Claude's usage limit:** when a session stops because the limit is
  reached, a notice says so, with the time it resets (Settings → Safety
  nets → *Tell me when Claude stops at its usage limit*).
- **Another agent on another machine** (see *Another agent on the other
  machine*) gives *api on box went quiet — Codex: done, or it waits for
  you* once its window wrote nothing for a minute after working, or *Codex
  ended*. It follows **When a long piece of work is done**
  (`notify_finished`).
- **Handovers, syncs and notes** have notices of their own: a handover cut
  off halfway, a machine that went silent while it holds a project, a
  paused Keep in sync, a note or a pick-up (see *Hand a project over to
  another machine* and *Pick up on another machine*).
- **Every notice names its machine** once you added another one: *paper on
  homebox waits for you*, and a session here gets this computer's name.
- **Your phone gets each notice once:** when aht on the other machine
  sends that machine's notices to your phone itself, this computer leaves
  them out.
- What a session waits for shows with keys and passwords masked (see
  *Secrets check*), here and on your phone; on another machine it is
  masked before it leaves that machine.
- **Sessions in the corner:** a small list in the screen's top-right
  corner shows every open Claude session on this Mac: **working** (blue),
  **waiting for you** (orange) or **done** (green), with how long it has
  been so, under the name the Claude app shows. The sessions working now
  come first, the one that started last on top; the rest follow by when
  they last worked. *Done* stays until you click that session, which
  brings its iTerm2 tab to the front, or until it works again. Drag the
  list, or its edges, to move or resize it (a double-click on its top line
  puts it back); sessions that do not fit show as "+n more". Turn it on or
  off in the aht menu (*Sessions in the Corner*), in Settings → Notices,
  or with its ×. It reads Claude Code's own records of its sessions every
  second and a half, so it needs no tokens.

**In the terminal:**

- `aht notices --test` — send a sample notice, to this computer and to your
  phone if one is set.
- `aht limits` — list the sessions that stopped at Claude's usage limit in
  the last 12 hours, and when the limit resets; `--hours 48` looks back
  two days.

## Chimes when a session is done or waits for you

A short chime the moment a Claude session on this Mac finishes a piece of
work or starts waiting for you, so you hear it without looking. Each has its
own sound, and you choose it. The chimes are off until you turn them on:
Settings → Chimes, or **Chimes** in the aht menu.

> **Example.** Three sessions work on three projects while you read a
> paper. A *doorbell* means one needs an answer from you (a permission, a
> question); three notes going up mean one is done. The corner, or the
> number next to the ∞, shows which.

- **Waits for you** (Doorbell), **Is done** (Bloom) and **Hits the usage
  limit** (Ebb) each have their own chime. A chime you pick plays at once;
  ▶ plays it again.
- **Is done … after working at least** 30 seconds (from *any length* to 10
  minutes): a quick answer in the session you are typing in stays quiet.
- **aht's own chimes** are made from notes of one scale, so two in a row
  never clash, and each is about as loud as the sounds of macOS:
  - *Bloom*: three notes going up (made for "done").
  - *Settle*: a falling fifth, calmer.
  - *Doorbell*: ding-dong (made for "waits for you").
  - *Tap*: two light wooden knocks.
  - *Ask*: two notes going up, like a question.
  - *Ebb*: three low notes going down (made for the usage limit).
  - *Drop*: a single water drop.
  - The short ones, a fifth of a second each: *Ebb1*, *Ebb2*, *Ebb3*
    (Ebb's notes, from high to low), *Felt* (one low note, like a piano
    with felt on its hammers), *Hush* (a soft tone that swells and fades),
    *Pluck* (a soft plucked string), *Bubble* (a low bubble, rising) and
    *Puff* (a short breath, no note; the quietest).

  Below them in the list are the sounds of macOS (Glass, Ping, Purr…) and
  any in your `~/Library/Sounds`. **Choose a File…** takes any short sound
  file, and **None** keeps that one quiet.
- **Volume** sets the chimes only, not your Mac; letting go of the slider
  plays one.
- **How it knows:** as the corner does, so it needs no tokens. Only
  sessions you work in chime, not scripted ones (`claude -p`), and
  sessions that finish together make one chime. A session on another
  machine, and the usage limit, chime when their notice arrives (those
  notices then make no sound of their own).
- Only the Mac app plays chimes, and only while it runs.

**In the terminal:**

- `aht config --set chimes=true` — turn the chimes on.
- `aht config --set chime_done=Glass` — the chime for "done": one of aht's
  own, a sound of macOS by its name, or the path of a sound file;
  `chime_done=` for none. The same for `chime_waiting` and `chime_limit`.
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
  session. A resumed session gets nothing, as it has its own history,
  except a session another agent took the work over from: resumed by
  hand, it learns what happened since (see *Continue in another agent*).
- Keys and passwords in the note are masked (see *Secrets check*).
- Only Claude Code has a start hook, so only its new sessions get the note.

**In the terminal:**

- `aht config --set informed_sessions=true` — turn it on (`false` turns it
  off again).

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
  origin is gone (for example after Claude Code's clean-up of old
  sessions) is listed with the others and says so.
- **Open now:** a session that runs right now says *open now* and offers
  **Go to Tab** instead of Continue, so it is not opened twice.
- **Titles** are the names `/resume` shows: the one the session was given
  (`/rename`, or its tab's title), else Claude's own. The short code on the
  right is the start of the session's id; point at it to see it whole.
  With more than six sessions, a field filters them by title.
- Kimi Code, Codex, Antigravity and Mistral Vibe sessions in the folder
  are listed too.
- While the project is handed over, take it back before you continue a
  session here.

**In the terminal:**

- `aht sessions ~/Desktop/paper` — the same list, branches indented.
- `aht resume-here ~/Desktop/paper --session <id>` — continue that session
  in a new terminal window (`--agent kimi`, `codex`, `agy` or `vibe` for
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
  there (*Undo a whole session* covers those).

**In the terminal:**

- `aht changes ~/Desktop/paper` — list the files the latest Claude Code
  session in the paper project edited; `--diff` adds every changed line.
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
> since; **Back to** picks an older copy. **Put Everything Back…**
> restores the folder. What it held a moment ago goes to `~/.aht/undo/`,
> so the undo can itself be undone.

- **On a Mac** the copies are copy-on-write: they take no room until a
  file changes, and Time Machine leaves them out. **On Windows and Linux**
  they are real copies, made only of folders up to 100 MB, so they are off
  until you turn them on. The last 10 per project are kept, none older
  than 30 days.
- Left out, because they are rebuilt or have their own history:
  `node_modules`, `.venv`, `__pycache__` and the like, and `.git`.
- **Big folders.** A project with more than 20,000 files gets no copy. You
  can change that number in Settings → Safety nets; aht then tells you
  which projects are over it and which of their folders hold most files.
  You can also leave such folders out of the copies (for example `results`
  or `datasets`), so the rest of the project is covered.
- **Why a limit at all:** even a copy that takes no room for the data
  costs. For a 98,000-file project on a Mac: about 17 seconds of disk work
  at every session start, about 100 MB of file-system entries per kept
  copy, and about 5 seconds to compare or delete one.
- aht also makes one before another agent takes over (*Switch Agent*).
- Not while an agent is working in the project.
- Settings → Safety nets → *Copy the folder when a session starts*.

**In the terminal:**

- `aht undo ~/Desktop/paper` — show which files differ from the copy made
  when the latest session started, without changing anything; `--diff`
  shows every changed line.
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
  which ones are over the limit, with their biggest folders; `--max
  100000` tries another limit, `--top 40` lists 40 projects instead of 15.
- `aht config --set checkpoint_max_files=100000` — change the limit.
- `aht config --set checkpoint_excludes=results,datasets` — leave folders
  with these names out of the copies.

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
> this project since 14:10*, with **Hand Back…**. When the limit has
> reset, you press it: your Claude session opens again where it stopped,
> and it learns what Codex did meanwhile.

- **The summary** goes into the project's `.aht/handover/`, which git
  ignores. It holds where things stood, the latest exchanges, the open
  to-dos, the files changed last, the state of git (branch, latest commit,
  what is not committed) and the files outside the project the session
  used, with keys and passwords masked (see *Secrets check*). It names the
  command that goes back to the earlier session, which stays as it was.
- **A new session or its own session.** A new session reads the whole
  summary. Its own session (that agent's latest one in this project) reads
  only what happened since it last worked here; when the agent has no
  session here yet, it goes on in a new one.
- **Summary Only**, in the same dialog, writes the summary and opens
  nothing. Start the agent yourself when it suits you, and ask it to read
  that file first. Since nothing started, who has the project stays as it
  was.
- **Hand Back** gives the work back to the agent it came from, in that
  agent's own session (also the first item under **Switch Agent** while
  another agent has the work). That session reads a catch-up of what
  happened since it handed the work on: what the other agents asked and
  answered, the to-dos still open, the files changed and the commits made
  since. When that session is gone, a new one reads the other agent's
  summary and the catch-up, and the dialog says so first. When aht cannot
  read what the other agent did, the dialog and the catch-up say that the
  files may differ.
- **Passed on twice** (Claude Code → Codex → Kimi Code): Hand Back from
  Kimi goes to Codex, and Hand Back from Codex then goes to Claude Code. In
  the terminal, `--back --to claude` goes straight back to Claude Code,
  with a catch-up of both.
- **What it costs** (see *What uses tokens*): writing a summary or a
  catch-up costs nothing; the agent that goes on reads it as one turn.
  Claude Code's own session costs nothing until you type: aht's Claude
  hook gives it the catch-up (at most 2,000 characters) as it opens, once,
  and Claude reads it with your next message. How Kimi Code reads depends
  on the level (see *The permission level follows the work*); when Kimi
  does not take the catch-up into its own session, a new Kimi session
  reads the full summary instead, and aht says so.
- **If you go back by hand.** When you resume the Claude session yourself
  instead of pressing Hand Back, aht's hook tells it in one line which
  agent worked on the project since, that the files may differ, and where
  the summary is; the catch-up itself comes with it only when informed
  sessions are on (see *Every session starts informed*). Once you type in
  that session, the project counts as back with Claude.
- **Antigravity** opens in a new conversation (`agy -i`) or continues its
  own (`agy --conversation <id> -i`, once aht checked that it still
  exists), with `--remote-control` when `handover_remote_control` is on.
- **Mistral Vibe** opens in a new session (`vibe "<what to read first>"`)
  or continues its own (`vibe --resume <id> …`, once aht checked that it
  is still in `~/.vibe` or `$VIBE_HOME`). aht reads the sessions of Vibe
  3. Vibe reads a project's `AGENTS.md` only in a folder you trust in
  Vibe.
- **Checks first.** Not while a Claude session in the project is working
  or waiting for you. A Claude session open there but idle, or another
  agent open in the folder, gives a warning: don't type into both (on
  Windows aht can tell only that such an agent runs, not in which folder).
  Hand Back waits while the Claude session it goes back to is still open:
  exit it and press Hand Back again (or write the catch-up for it with
  `--back --brief-only`, below).
- When copies to undo a session are on (*Undo a whole session*), aht makes
  one before the other agent starts.
- When no terminal window can be opened, the summary is written all the
  same, and aht shows the line to run yourself.
- **At Claude's usage limit** the project shows *Claude stopped at its
  usage limit; it resets 6:20pm*. With Settings → Uses tokens → *When
  Claude stops at its limit, offer to go on in* turned on (you pick Kimi
  Code, Codex, Antigravity or Mistral Vibe), a **Continue in Kimi Code…**
  button sits right next to it, and the notice says so too. aht spots the
  limit in the session's history, which costs nothing.
- **Going on by itself:** in the Mac app, Settings → Uses tokens → *When
  Claude's usage limit resets, the session continues by itself* switches
  Claude Code's own setting `autoContinueAtUsageLimit`; elsewhere, `aht
  limits --auto-continue on`. It uses tokens, since the session works on.
  The notice then says *continues by itself then*.

**In the terminal:**

- `aht switch ~/Desktop/paper --to codex` — say which session Codex would
  continue, and how, without starting anything.
- `aht switch ~/Desktop/paper --to codex --apply` — write the summary and
  open a new Codex session on it (`--to claude`, `--to kimi`, `--to agy`
  and `--to vibe` work the same way).
- `aht switch ~/Desktop/paper --to codex --resume --apply` — Codex's own
  latest session in the project goes on, and reads only what happened
  since.
- `aht switch ~/Desktop/paper --to kimi --brief-only --apply` — Summary
  Only: write the summary, open nothing.
- `aht switch ~/Desktop/paper --to claude --session <id> --apply` — pass on
  that session's work rather than the latest one of another agent.
- `aht switch ~/Desktop/paper --back` — say which session the work would go
  back to, and what happened since; add `--apply` to hand it back, or `--to
  claude --apply` to go straight back to Claude Code.
- `aht switch ~/Desktop/paper --back --brief-only --apply` — write the
  catch-up only and open nothing, for a session that is still open: tell
  it to read the file.
- `aht switch ~/Desktop/paper --to kimi --no-window --apply` — prepare
  everything and print the command, without opening a window. (Without
  `--no-window`, when no window opens, it ends with an error that holds the
  command.)
- `aht relays ~/Desktop/paper` — who handed the paper project's work to
  whom and when, newest first, and which hand-off is still open; `--show
  <id>` prints that hand-off's summary.
- `aht limits --auto-continue on` — sessions go on by themselves when the
  limit resets (`off`: they wait for you).

## The permission level follows the work

If you started a session in a mode that does not ask for permission
(Claude Code's `--dangerously-skip-permissions`, Codex's full bypass), or
asks less, the agent that continues the work starts in its own equivalent.
That holds for Switch Agent, Hand Back, Pick Up → Open in, Bring Here, Hand
Over and the night shift, on this computer and across machines.

**aht never raises the level on its own.** The next agent never gets more
power than the session it continues, and only levels you set yourself
raise what it gets: your own command line, your user or managed Claude
Code settings, aht's own settings, or a level aht recorded on this
computer. Nothing in a project's repository does. Restarts keep a
session's own flags.

> **Example.** You run Claude Code with `--dangerously-skip-permissions`
> and it stops at its usage limit. You press **Continue in Codex…**; the
> dialog says *Codex starts in never-ask mode, like the Claude Code session
> you are leaving*, and Codex opens with
> `--dangerously-bypass-approvals-and-sandbox`. Later **Hand Back** opens
> your Claude session again with `--dangerously-skip-permissions`.

**The levels**, in aht's words, and each agent's flags for them:

| level | Claude Code | Codex | Kimi Code | Antigravity | Mistral Vibe |
|---|---|---|---|---|---|
| ask (each agent's default) | — | — | — | — | — |
| edits (edits run, commands ask) | `--permission-mode acceptEdits` | `-a on-request -s workspace-write` | — (it asks) | `--mode accept-edits` | `--agent accept-edits` |
| auto (routine runs, risky asks) | `--permission-mode auto` | `-a on-request` | `--yolo` | `--mode auto` | `--smart-approve` |
| never (never asks) | `--dangerously-skip-permissions` | `--dangerously-bypass-approvals-and-sandbox` | `--auto` | `--dangerously-skip-permissions` | `--auto-approve` |

- **How aht knows the level.** For a session that is open: its command
  line up to its first prompt, never higher than what the session itself
  notes. For one that ended: what the session noted itself (Codex's
  approval policy and sandbox; the permission mode Claude Code notes on
  each prompt); else the level aht started it in, kept on this computer
  (`~/.aht/run/perm.json`); the record in the project is shown but not
  believed, since anyone who can write the repository can write it. Else,
  for Claude Code, `permissions.defaultMode` in your own or the managed
  settings, or a `--settings` on its command line; the project's
  `.claude/settings.json` and `settings.local.json` count only for
  `acceptEdits`, `plan`, `default` or `dontAsk`, as in Claude Code
  itself. When nothing tells, the next agent asks, and the dialog says so.
  For Pick Up and Bring Here, the other machine reads the level of its
  session there.
- **No exact match: the next stricter level.** Kimi Code has no edits-only
  mode, so after an edits-mode session it asks, and the dialog says why:
  *Kimi Code starts in ask mode, the next stricter level: it has no edits
  mode*.
- **By what an agent can actually do.** Claude Code's skip-permissions is
  closest to Codex's full bypass, so one goes on as the other. A never-ask
  Claude session inside Claude Code's own sandbox (`sandbox.enabled` in its
  settings) goes on as Codex's never-ask that keeps Codex's sandbox (`-a
  never -s workspace-write`). Such a Codex session goes on in Claude Code
  as skip-permissions together with Claude's sandbox, on macOS and on Linux
  with bubblewrap; elsewhere in auto. Kimi Code, Antigravity and Mistral
  Vibe have no such sandbox, so they go on in auto then. aht turns
  Claude's sandbox on with a settings file of its own
  (`~/.aht/run/claude-sandbox.json`), so a restart keeps it.
- **Codex's never-ask.** By default a never-ask session goes on in Codex
  with its full bypass. Settings → Permissions → *Codex's never-ask mode*
  offers **Never ask, keep Codex's sandbox** instead (`-a never -s
  workspace-write`): Codex then never asks, but writes only inside the
  project.
- **Your own level.** Settings → Permissions → *The next agent starts in*:
  **Follow the session** (the default, `agent_permissions = follow`), a
  fixed level (**Always: ask mode** … **Always: never-ask mode**: your
  choice, even above the session's level), or a cap (**At most: auto
  mode**, `max:auto`). `agent_permission_flags` replaces aht's flags for
  one agent and level (see *All settings, one by one*); aht refuses flags
  that could ask for more than their level (read the most permissive way),
  flags it does not know, a Claude Code `--settings` that holds
  permissions or a sandbox, and flags that ask for different levels.
- **At ask, aht adds no flag**, so an agent starts as its own settings say.
- **Hand Over** starts the session there with the level's flags, then
  `handover_claude_args`; inside Claude's sandbox, its settings file there
  turns the sandbox on. **Continue Session** reopens a Claude Code session
  in its level too.
- **Kimi Code** reads its summary in a run of its own (`kimi -p`) only in
  never-ask mode, since Kimi takes no level flag in that run and never
  asks; the dialog waits a moment for it before Kimi's window opens. Below
  never-ask, Switch, Hand Back, Pick Up → Open in, Hand Over and Bring
  Here open Kimi in its level without that run, and aht shows the one line
  to paste as your first message (`--json`: `kimi_reads: false` and
  `first_prompt`).
- **A second opinion** works in a throwaway copy, so Claude Code may edit
  that copy at any level; its commands follow the level, never above it.
  Kimi Code takes part only in never-ask mode (see *A second opinion*).

**In the terminal:** `aht switch ~/Desktop/paper --to codex` (a dry run)
says the level in its `level` line; `--json` adds `perm` with `level`,
`from` (`command_line`, `rollout`, `transcript`, `settings`, `relay` or
`unknown`), `read` (the session's own level), `flags`, `sandbox` and
`text`. So do `aht pickup … --open`, `aht bring`, `aht handover` and the
night shift's plan. `aht second-opinion … --dry-run --json` gives each
agent's level (`perms`), who takes part (`agents`) and who is left out and
why (`left_out`), and starts nothing.

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
- The project is not touched until you pick a version. If a file changed
  in the project meanwhile, aht brings in nothing and names those files.
- Claude may edit files in its copy at any level; its commands follow the
  level of the project's latest session, never above it (at ask it cannot
  run them, since nobody is there to say yes). Kimi's non-interactive mode
  never asks and runs commands it decides on, so Kimi takes part only when
  that session runs in never-ask mode; otherwise aht leaves Kimi out, says
  why, and Claude works alone.
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
- `--agents claude,kimi` names the two agents; these two are the default
  and the only ones that work today.
- `--dry-run` (with `--json`) shows the level each agent would work in and
  whether Kimi takes part, without copying or starting anything.

## One set of project rules

Claude Code reads `CLAUDE.md` (and `AGENTS.md` only when there is no
`CLAUDE.md`); Kimi Code, Codex and the others read `AGENTS.md`. Rules
written in `CLAUDE.md` are invisible to the others.

> **Example.** Your project has a `CLAUDE.md` that says "use British
> spelling; run the tests with pytest". **More → Project Rules…** says:
> *only CLAUDE.md: Claude follows it; Kimi, Codex and the others see no
> project rules*. Press **Make AGENTS.md the One Set of Rules** (in aht's
> window **Make One Set**). The rules move to `AGENTS.md`, and `CLAUDE.md`
> keeps a single line, `@AGENTS.md`, which is how Claude Code includes
> another file. From then on every agent follows the same
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
> **Projects → Look Back → Report…**, *This week*, *by area*: each area's
> hours and sessions. Areas are folders you name once, for example
> `aht config --set report_areas='{"Work A": "~/Desktop/Workspace/A", "Work B": "~/Desktop/Workspace/B"}'`.
>
> Submitting a paper: **More → AI-Use Statement** writes a draft such as
> "AI coding assistants were used in this work in September 2026: Claude Code
> (4 sessions, about 12 h of active use) … They were used for tasks such as
> …. All output of these tools was reviewed, and the author takes full
> responsibility for the content." Check it before you use it.

- **Session time** counts the stretches in which a session was active; a
  pause counts for at most 15 minutes, and sessions that ran side by side
  add up.

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
> and the agent's replies, with keys and passwords masked, and without
> e-mail addresses, local network addresses, your home folder's path or
> your user and computer names. The page says so under its title.

- Look through the page before you pass it on: masking is best effort.
  Names in the conversation itself, such as a repository, stay, and so do
  paths outside your home folder (an external disk, `/opt/…`) and a secret
  aht does not recognise (see *Secrets check*).

**In the terminal:**

- `aht share ~/Desktop/paper --format html --out session.html` — save the
  paper project's latest session as a web page.
- `aht share ~/Desktop/paper --format md` — print it as Markdown instead.
- `aht share ~/Desktop/paper --session <id> --agent kimi` — an earlier
  session, or one of another agent.
- `aht share ~/Desktop/paper --tools` — also list the tools the agent used
  (their commands and files masked before they are shortened).

## Secrets check

Lists what aht recognises as a key, a token or a password in the
histories of Claude Code, Kimi Code, Codex, Antigravity and Mistral Vibe.
Values are only ever shown masked.

> **Example.** Months ago you pasted an API key into a prompt. **Settings →
> Check All for Secrets…** lists it: the project, what it looks like
> ("Groq API key"), the masked value `gsk_…o8`, where it appeared (your
> message, a tool's output) and when. Replace that key where it was issued.

- For one project: **More → Check for Secrets**.
- **What it recognises:**
  - keys of a known kind: Anthropic, OpenAI, Groq, GitHub, GitLab, AWS
    access keys, Google API keys and OAuth tokens, Slack, Stripe live keys,
    SendGrid, Hugging Face, npm, PyPI, age, Vault, DigitalOcean, Shopify,
    Docker Hub, Atlassian, Tailscale, JSON web tokens, the secret part of a
    Slack webhook address, the token in a Telegram bot address;
  - `Bearer` tokens, `Basic` credentials and whatever follows
    `Authorization:`;
  - a generated-looking value given to a name that holds a password, a
    secret, a token or a key (`DB_PASSWORD=`, `AWS_SECRET_ACCESS_KEY=`,
    `JWT_SECRET=`, `client_secret`, `GITHUB_TOKEN=`, `x-api-key:`,
    `dbPassword`, `accessToken`), also in a `.env` file, an `export` line
    or a tool's output;
  - passwords on a command line (`--password X`, `--token X`, `mysql -pX`,
    `docker login -p X`, `curl -u user:X`) and in XML
    (`<password>X</password>`);
  - the password in a web or database address, whatever the host (also
    Go's `user:…@tcp(host:3306)/db`), with the rest of the address left
    readable;
  - private keys, from their BEGIN line to their END line, also inside
    JSON, in a Read tool's numbered output, encrypted ones, PGP and PuTTY
    `.ppk` keys, and keys in base64 (a kubeconfig's `client-key-data`, a
    Kubernetes `tls.key`), shown as *BEGIN RSA PRIVATE KEY (in base64)*. A
    key the history holds twice is listed once.
- **Left alone:** names that say they hold something else (`TOKEN_URL`,
  `password_hash`, `max_tokens`, `nextPageToken`), placeholders and
  references to a secret store (`${DB_PASSWORD}`, `<token>`, `changeme`,
  `op://…`, `vault:…`), ordinary code that uses the words token, password,
  secret or auth, paths and web addresses, ARNs, fingerprints and hashes,
  test names and plain words. A guide or code that only names a private
  key's BEGIN and END lines is left alone too.
- **Not every secret:** masking is best effort. A value with no name or
  form aht knows stays in clear, and so can a short one, one after a name
  it does not know (`STRIPE_KEY`), a password with a quote or a space in it
  (masked only up to there), or one that does not look generated. The
  privacy policy lists the known limits. Keep secrets out of agent chats.
- **Masked everywhere aht copies:** aht never changes the agents'
  histories on its own, and in everything it copies out of them (the
  search index, summaries, notices, journals, shared pages and every list
  of sessions) it masks what it recognises, whole, before it shortens a
  text. Session names stay as they are only where they stay on this
  computer: the session corner, tab titles, saved layouts and aht's own
  files and log.
- A handover tells you when such values travel along with a project.
- **Take one out:** **Remove…** next to a find replaces it with
  `[removed by aht]` in every history file that holds it. The files are
  copied to `~/.aht/redacted` first. While an agent session is open in
  those projects, aht changes nothing and says so. Backups still hold the
  old files, so replace the key where it was issued anyway. A place whose
  removal would leave a line of the history no longer valid JSON is left
  as it is, and aht says how many; so is a key in a Mistral Vibe session,
  which Vibe would no longer open with a byte changed.

**In the terminal:**

- `aht secrets` — list what aht recognises as a key or password in every
  project's histories, masked; `aht secrets ~/Desktop/paper` one project.
- `aht secrets --redact <fingerprint>` — say in how many places and history
  files one of those finds appears, without changing anything (the
  fingerprint is in the list); `--apply` replaces it in every history file
  that holds it.

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
  conversations as text (the last 40 messages of each of the 10 newest
  sessions, keys masked), so you can decide; **Show in Finder** opens the
  history's own folder; **Choose Folder…** connects it to a folder you
  pick.
- **On Windows and Linux** the window offers **Choose Its Folder…**,
  **That's It** (Reconnect) and **Forget…**; read a history with `aht tidy
  --show`, and remove one with `aht tidy --remove-history` (below), which
  moves it to the Recycle Bin on Windows and to the desktop's Trash on
  Linux.
- **On Windows only to the Recycle Bin.** When a history cannot go there
  (a network share, a `subst` drive, a bin set to remove files at once, or
  a history bigger than the bin), aht changes nothing and says why,
  already in the dry run.
- **A link** in Claude's history folder (to a folder elsewhere) is listed
  and can be read, but aht leaves it alone: Tidy Up has no **Remove…** for
  it.
- **Forget sticks.** A forgotten project's folder keeps its
  `.aht/.project-id`, but aht's scans no longer take it on again. It comes
  back when you take it on yourself: a new Claude Code session in that
  folder; `aht tag`; **Adopt This Mac's Projects…** or `aht adopt`; ticking
  it when you set up again; Tidy Up's **Reconnect** or **Choose Folder…**
  onto that folder (`aht bind`); `aht restore` into it; handing it over;
  or keeping it in sync. `aht forget --remove-marker` also deletes the
  marker.
- On a Mac and on Windows, histories are matched to their projects without
  regard to case, as the disk does, so a tracked project's history is
  never listed as one without its folder.
- Sessions you started in your home folder itself are not a project, so
  Tidy Up does not list them (nor do `aht doctor` and `aht orphans`).
- A folder listed twice, even under two spellings of its path, shows in
  `aht tidy` and `aht doctor`; `aht prune --apply` drops the extra entry.

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
  folder to the Trash (on Windows to the Recycle Bin, and only there). The
  name is one from the `aht tidy` list, written exactly as there, with
  `=`, because it begins with a dash; anything else (a path, another
  spelling, a link) is refused, and so is a history a tracked project owns
  or an open session uses. When aht refuses, it prints the name and why.
  The daily backups keep the history as well.

## Hand a project over to another machine

Your laptop's connection is shaky (a train, a hotel), and a machine at home
has a stable one. Hand the project over, let it run there, and steer it from
the laptop or your phone.

**Once:** add the machine. On a Mac, the Machines tab lists the machines
aht found on your Tailscale network or in `~/.ssh/config` (**Look Again**
looks once more): press **Add…** next to one, or **Add Another…**, check
the `user@host`, and press **Check and Add**. In aht's window: **Add a
Machine…**, a name and the `user@host`, **Add**. aht lists what that
machine still lacks, each with the command that fixes it and a **Copy**
button. Nothing needs creating there: each project goes to the same place
below that machine's home folder (`/Users/me/code/shop` here is
`/home/me/code/shop` on a Linux box; see *Across systems and folders*).

> **Example.** Before you leave, select the paper project → **Hand Over to
> homebox…**. The dialog shows what will be sent. Optionally type a task,
> such as "run the full benchmark and summarise the results", and the
> session starts on it right away. On the train, **Open Session** (on a
> Mac; elsewhere **Peek…** → **Open Its Window**) connects to it; with mosh
> on both machines the connection survives network changes. Or follow it
> in the Claude app on your phone and answer its questions there.
>
> Back home, **Take Back…** brings the files and the history back. A file
> changed on both machines is kept in both versions, for example
> `notes (from homebox 2026-09-30).md`. Then **Continue Session**.

- **Nothing moves while something runs:** while an agent works or waits for
  you in the project, or another program runs in the folder, the handover
  waits.
- **Same Claude Code everywhere:** the other machine gets this computer's
  exact version.
- **Between systems:** a Mac, a Linux machine or a Windows PC hands
  projects over to a Mac or Linux machine and takes them back; a Mac, a
  Linux machine or another PC also to a PC that answers (see *A Windows PC
  that answers*). The project may sit at another path there (see *Across
  systems and folders*). A machine can also fetch a project itself (see
  *Bring a project here, and send it back*).
- **It stays awake while the agent works** or waits for you there:
  `caffeinate` on a Mac, `systemd-inhibit` or GNOME's
  `gnome-session-inhibit` on Linux. It lets go when the session is idle
  or ends, when you take the project back, and after 24 hours. A closed
  laptop lid still
  sleeps, and a PC is never kept awake. **Check** shows whether it works
  there, and what to do when it does not; `handover_keep_awake` turns it
  off.
- **Watch:** tick **Watch** for a machine in the Machines tab, and aht asks
  it every 2 minutes for sessions that wait for you or are done (one that
  holds a project of yours is asked about once a minute anyway). Each
  machine shows when aht last heard from it.
- **A machine that goes silent** while it holds a project gets one notice
  after 10 minutes (*homebox has not answered since 15:20. The work on
  paper there may have stopped*), and one more when it answers again.
- **Keep in sync:** tick it for a project, and aht copies it in the
  background every 30 minutes, so a handover only sends the last changes.
  It never overwrites work done in the copy there: it pauses and asks (see
  *Keep in sync looks first*). A project released, handed over or switched
  off while a sync runs is not sent.
- **Every project at once:** Machines → **Sync** → *Keep All Projects in
  Sync…*. aht first adds up what the first copy sends (projects inside
  another project travel with it; rebuilt folders such as `node_modules`
  stay behind) and asks. The first copy can take hours for tens of
  gigabytes; after that only changes travel. Under each machine the window
  says how many projects are kept in sync with it, and which are paused.
- **Nothing is lost:** whatever a transfer replaces is set aside first, in
  `~/.aht/handover/<project id>/replaced/` here and
  `~/.aht/remote/replaced/` on the other machine. The newest 5 of those
  folders and every one younger than 30 days are kept.
- **What copies the files:** rsync, when this machine has rsync 3, the
  other has rsync, and neither is Windows; otherwise aht's own copy, which
  needs nothing there beyond python3 (on a PC: aht, or Python 3). aht's own
  copy sends each file in pieces of at most 1 MB, checks it, and only then
  puts it in place; a file that only grew sends just its new end. Unlike
  rsync, it sends a big file changed in the middle whole, and starts a big
  file cut off halfway again. When the link drops, or nothing moves for 2
  minutes, the copy ends; the files that arrived whole stay, and the next
  sync or handover sends the rest. **Check** says which one each machine
  gets; **Settings → Handover → Copies files with** chooses
  (`handover_transfer`).
- **Names whose case changed** there (`readme.md` → `README.md`) come back
  renamed on a Mac; two names that differ only in case are both kept, one
  under the conflict name. Empty folders made there come back too.
- **Summaries:** each handover and each switch of agent leaves a summary in
  the project's `.aht/handover/`; every hand-off still open and the newest
  12 others are kept. A handover sends that folder along; Keep in sync
  leaves it out.

**Keep in sync looks first.** Before each sync, aht compares the copy on
the other machine with the list of that copy it kept after the last sync,
handover or take-back, so no clock matters. When the copy there was worked
on, the sync pauses, sends nothing, and the project asks what to do. A file
that was only touched does not pause it.

> **Example.** You keep paper in sync with box. One evening you fix a typo
> in `README.md` on box itself and add `notes/box.md`. At the next sync, a
> notice says *Keep in sync paused: paper*, and paper shows *The copy on
> box was changed since the last sync (1 changed and 1 new): README.md,
> notes/box.md. Nothing was sent.* **Bring Them Here…** brings both files
> into this Mac's copy; then the sync runs.

- **Why a sync pauses:** *the copy there was changed* (files changed, new
  or removed there, or a conversation that went on there; a new one does
  not count); *it would remove many files there* (more than 200, or more
  than a quarter of 20 or more); *the folder there holds something else*
  (a first sync into a folder with files and no project id, or another
  project's).
- **The answers,** each where it fits:
  - **Bring Them Here…** works like Take Back on the copy: what the changes
    replace here is set aside first, and a file changed on both machines
    is kept in both versions. Then the sync runs. Not while a session is
    open there. If it would remove many files here, it lists them and asks
    first (`aht reclaim <path> --allow-removals`). It never removes
    anything under `.aht/`.
  - **Replace Them…** sends this copy over the one there, once, setting
    theirs aside on box first.
  - **Allow the Removals…** lets this one sync remove those files there,
    set aside there first. If they went missing here by mistake, get them
    back first (Undo a Session, or a backup).
  - **Stop Syncing** turns Keep in sync off; the copy there stays as it is.

  Ticking **Keep in sync** off and on ends a pause, but the next sync looks
  again.
- **Hand Over looks too.** When the copy there was changed since the last
  sync, handover or take-back, Hand Over stops and names what changed,
  with **Bring Them Here…** and **Replace Them There…** (on a Mac
  **Replace Them…**; in the terminal `--replace-there`).
- **Copies from elsewhere.** The other machine keeps a list of the folders
  that are copies of another machine's projects
  (`~/.aht/remote/copies.json` there). Where aht is installed on box, Keep
  in sync for such a folder is refused there, since one folder would be
  synced both ways, and *Keep All Projects in Sync…* leaves those out; the
  project says where it came from (*Copy kept in sync from mac*, *Handed
  over from mac*, *Brought here from mac*); and a Claude Code session that
  starts in it is told that changes made there pause that sync. Turning
  Keep in sync off on mac asks box to drop the folder from its list.
- **Names the other disk cannot hold apart**, such as `README.md` and
  `readme.md` for a Mac's disk, do not pause a sync. They are listed
  (`aht mirror --run --json` gives them under `names`).
- **Names the other disk cannot hold at all** (on a Windows PC: `aux.md`,
  `a:b.txt`, a name ending in a dot or a space, a path too long; links
  the account there cannot make) stop a sync before anything is sent, as
  they stop a handover: *1 name pc cannot hold (a name Windows reserves:
  aux.md) — rename it here, or add it to handover_excludes*.

**A handover cut off halfway.** When the link drops or this computer
sleeps during a handover, aht asks that machine at its next check, within a
few minutes, and a notice says how it ended: *finished: the session there
runs* (to a PC: *Continue here waits there*), and the project is there as
after any handover; or *did not finish. The project stays here; nothing
runs there*. It counts as finished when anything happened there: a
session runs or ran there, the copy was worked on, or the conversation
went on.

- **Meanwhile** the project shows *Handover to homebox unfinished:
  checking…* with **Check Now** (ask at once) and **Release…**;
  **Continue Session**, **Switch Agent**, **Hand Over** and **Keep in
  sync** wait until it is settled. A session started here meanwhile is
  warned.
- **Release…** lets the project count as here again, with its files here
  as they are. The copy on homebox is not touched, and the work done there
  stays there; Release names it first (*3 files and the conversation*).
  After an hour without an answer, Release is the main button, and a
  notice says so once. After a Release, the next session here is told once
  that the work done there did not come here.
- **Release for a handed-over project**, for a machine that is gone for
  good: on a Mac next to **Take Back…**, in aht's window **More → Release
  from homebox…**.
- **Release and Keep in sync:** releasing pauses Keep in sync with that
  machine, so the next sync does not overwrite the copy left there. The
  project then shows **Turn Sync Back On…**; the next sync looks at the
  copy there first. Handing the project over to that machine again, or a
  Take Back from it, also ends the pause (the copy there is set aside
  first).
- **Take Back refuses** when the saved list of what left belongs to another
  handover attempt; it points to Release. **Removing a machine** that
  still holds a project is refused too: take the project back first, or
  release it.

**In the terminal:**

- `aht remote discover` — list the machines on your Tailscale network and
  in `~/.ssh/config`.
- `aht remote add homebox you@homebox` — add one; `aht remote check
  homebox` says what it lacks (`all`: every machine).
- `aht remote` — list your machines; `aht remote watch homebox` watches
  one (`--off` stops); `aht remote default homebox` makes it the one the
  window uses; `aht remote remove homebox` forgets it.
- `aht handover ~/Desktop/paper` — show what would be sent and what stands
  in the way; `--to homebox` names the machine, `--apply` does it.
- `aht handover ~/Desktop/paper --apply --task "run the benchmark"` — hand
  it over and start the session there on that task (`--session <id>`:
  resume that session instead of the latest). A key, token or password in
  the task is masked before it leaves, as everywhere else.
- `aht handover ~/Desktop/paper --include ~/notes/paper.md --apply` — take
  a file or folder from outside the project along (remembered; Take Back
  brings it back).
- `aht handover ~/Desktop/paper --no-start --apply` — send it without
  starting the session; `--attach` opens the session in this terminal
  right after; `--allow-processes` goes ahead although another program
  runs in the folder; `--replace-there` although the copy there was
  changed.
- `aht attach ~/Desktop/paper` — open the session there in this terminal
  (`--window`: a new window; `--print`: only show the command).
- `aht reclaim ~/Desktop/paper --apply` — take the project back. For a
  handover cut off halfway it first asks what happened there (that is
  **Check Now**). For a project here that is kept in sync, it is **Bring
  Them Here** (`--from box`: whose copy).
- `aht reclaim ~/Desktop/paper --release` — say what releasing leaves
  there; `--apply` releases it.
- `aht reclaim ~/Desktop/paper --stop --apply` — end the session there
  first, if it is idle (never on a PC). `--prefer there` takes their
  version of files changed on both machines; `--ignore-version` takes it
  back although Claude Code there is newer; `--allow-processes` although
  other programs still run in the folder there.
- `aht resume-here ~/Desktop/paper` — continue the latest session in a new
  terminal window here (`--handed-over`: the one the last handover sent).
- `aht mirror ~/Desktop/paper --on` — keep the project in sync (`--to
  homebox` names the machine, and turns a paused sync back on); `--off`
  stops. `aht mirror` lists the kept copies and why one is paused; `aht
  mirror --run` syncs them now.
- `aht mirror ~/Desktop/paper --replace` or `--allow-removals` — say what
  Replace Them or Allow the Removals would do; `--apply` does it, once.
- `aht mirror --all --on --to homebox --apply` — keep every project in sync
  with homebox (`--all --off --apply` stops it for all).

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
  or newer, since that machine keeps the project's record and answers what
  Bring Here and Send Back ask it. Otherwise Bring Here says *install aht
  on mac first*, or *update aht on mac first: Bring Here and Send Back need
  aht <this version> or newer there …; then open it once*. The home must
  be a Mac or a Linux machine; a project on a PC goes the other way, with
  Hand Over on the PC.
- **What stops it:**
  - a session working or waiting in the project there. An idle one stops
    it too, unless you bring it anyway (**Bring It Anyway**; on a Mac the
    box *Bring it anyway; the idle session there stays open*;
    `--allow-idle`): if anyone types into that session later, Send Back
    keeps both versions;
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
  - Claude Code's history, filed under the folder's path here, with
    Claude's memory for the project and the plans of its sessions. The
    conversation files are not changed: Send Back checks that each one
    still begins as it left;
  - /rewind's snapshots only when the folder has the same path on both
    machines, since they name files by their full path (the dry run says
    when they stay behind);
  - Claude Code's trust in the folder, when the home trusted it and
    `handover_carry_trust` is on.
- **What stays there:** the histories of the other agents; the dry run
  names each. The session here gets a summary in `.aht/handover/` instead.
- **The session opens here** in a new terminal window with `claude
  --resume`; nothing runs until you type.
- **If it fails halfway,** aht tells the home to forget the attempt; the
  next Bring Here sets aside what arrived.
- **Send Back** runs where you brought the project. The home plans the
  way back against its record, as Take Back does, and puts the files in
  place:
  - a file changed on both machines is kept twice on the home, as
    `cart (from pc 2026-10-27).py` next to the home's (**Use the versions
    from here**, `--prefer here`, does it the other way round);
  - whatever it replaces or removes is set aside on the home;
  - a conversation that does not continue the one that left is kept as
    two;
  - when a newer Claude Code wrote the history here than the home has, it
    stops (**Send Back Anyway…**, `--ignore-version`);
  - no agent session may be open in the folder here, nor in the project
    on the home.

  The folder here stays, as an old copy of the home's project.
- **Take Back at home** works too, when the home can reach the machine
  that brought the project: a Mac or Linux machine added there, or a PC
  that answers and was added there before it brought the project. The home
  then says *… Send it back from pc, or take it back here.* Otherwise
  **Release…** is there for a machine that is gone.
- **A project handed over** to a machine with aht installed (also a PC
  that answers) can go back with Send Back on that machine too, when it
  can reach the machine that handed it over. That includes a PC that
  handed it over, once the PC answers (OpenSSH Server, see *A Windows PC
  that answers*) and is added on that machine; otherwise take it back on
  the PC.
- **The hook says so.** A Claude session that starts in the brought folder
  is told where it came from and to send it back when done; one that
  starts in the project on the home is warned that it is worked on
  elsewhere.
- **Where to find it:** **Projects → Bring Here** lists your machines, and
  in the Machines tab each machine has **Bring Here…** (in aht's window
  **Bring a Project Here…**). On a PC, the tray's **Projects brought
  here** menu lists those projects; **shop — Send Back to mac…** opens
  aht's window with Send Back's plan.

**In the terminal:**

- `aht bring --from mac --list` — list the projects aht keeps on mac, where
  each would go here, and why one cannot come.
- `aht bring /Users/me/code/shop --from mac` — show what bringing shop here
  would do, without changing anything; `--apply` brings it and opens its
  session. `--here C:\Users\me\code\shop-mac` brings it into another
  folder here, `--allow-idle` although an idle session is open in it on
  mac, `--no-open` without opening its session.
- `aht send-back C:\Users\me\code\shop` — show what sending it back would
  change on mac; `--apply` sends it. `--prefer here` and
  `--ignore-version` as above; `--allow-processes` although an agent is
  still open here; `--to mac` names the machine when aht here knows it by
  another name.

## Another agent on the other machine

Hand Over and Bring Here can go on in **Codex**, **Kimi Code**,
**Antigravity** (agy) or **Mistral Vibe** instead of Claude Code. The files
and Claude Code's history travel as always. The other agent starts a new
session there, and its first turn is to read a summary of where the work
stood. That turn **uses tokens**: the dialog says so next to the choice.
When the project comes back, the Claude Code session that left learns what
the other agent did. Not with a Windows PC: a handover to a PC goes on in
Claude Code only (its tray offers Continue here).

> **Example.** Claude Code is near its usage limit on api, and your Linux
> box has Codex. **Hand Over to box…**, **Agent there: Codex**. The dialog
> says *Codex starts on box and reads the summary as its first turn: that
> uses tokens* and *Codex on box starts in never-ask mode, like the session
> here*. On box, Codex reads the summary and says in two or three lines
> what it understood. **Sessions** shows *Codex — working* on box, later
> *quiet for 6 min*, and a notice says *api on box went quiet*. Back at
> the Mac, **Take Back…** ends Codex there, brings the files back, and
> leaves a catch-up for your Claude Code session: resume it, and it learns
> what Codex did on box.

- **The summary** is made here, with keys masked, and travels in the
  project's `.aht/handover/`, as for *Continue in another agent*. The
  agent's own history stays on the machine where it ran; only Claude
  Code's travels.
- **The level** the agent starts in follows the session it continues (see
  *The permission level follows the work*). The dry run shows the whole
  start line.
- **Kimi Code** in never-ask mode reads the summary in a run of its own
  first (`kimi -p`), and its window opens that session. With a task, Kimi
  works on it in that same run, and its window opens once that turn has
  ended (Hand Over waits for it, up to 10 minutes). Below never-ask, Kimi
  opens without reading the summary, and the dialog gives you the first
  prompt to paste (with the task in it, if you gave one). `aht bring
  --agent kimi --no-open` runs no such run either: it prints the line
  that opens Kimi and the first prompt to paste.
- **Its state** comes from its window (see *Sessions: what runs right
  now*; a spinner counts as output), or **tmux did not answer**. aht reads
  no screen for it; **Peek** (`aht attach --peek`) shows the window's last
  lines, keys masked, when you ask. Only while a Hand Over starts the agent
  does aht look at the last 14 lines for a few seconds, to see whether it
  started or asks something.
- **Staying awake:** the machine there stays awake while the window wrote
  output in the last 10 minutes.
- **Taking it back** waits while the agent runs there: *Codex still runs
  in its window on box (working)*. Exit it there, or let aht end it:
  **Take Back…** asks for that (`aht reclaim --stop`), by these rules:
  - it ends the agent only when its window wrote nothing for 2 minutes
    **and** the agent's own message is the last thing in its session, so
    its turn has ended. Then it types the agent's quit keys into its
    window (Ctrl-C twice for Codex, agy and Vibe, Ctrl-D for Kimi Code),
    up to three times, and the window closes once the agent has exited;
  - otherwise, or when aht cannot find its session or tmux there does not
    answer, it says why and ends nothing (*Codex on box has been quiet for
    only 1 min — wait, or end it yourself*);
  - it cannot tell whether a quiet agent asked you something (one that
    ended its turn with a question is ended too), and the quit keys drop
    what you typed into its prompt and did not send;
  - an agent that ignores its keys stays, and aht says so. The quit keys
    are aht's best knowledge of each agent, not yet confirmed for every
    version.
- **On the way back** (Take Back, or Send Back from there) box makes a
  catch-up of what happened there since, masked there, for the Claude
  Code session that left; aht's hook gives it to that session as you
  resume it, as after Hand Back. When box cannot give one, the note says
  that the files may differ.
- **Bring Here into another agent** opens that agent here in a new
  terminal window with the summary of the session there, in that session's
  level. Send Back brings the catch-up home. It waits while that agent is
  still open in the folder: *Codex is still open in this project here (pid
  4242) — exit it first*; `aht send-back <path> --allow-processes --apply`
  sends it back anyway, and what the agent does after that stays here.

**In the terminal:**

- `aht handover ~/code/api --to box --agent codex` — show what would
  travel, the start line there and its token line; `--apply` hands it over
  and starts Codex there. `--agent kimi`, `agy` or `vibe` likewise.
- `aht handover ~/code/api --agent codex --task "add the tests" --apply` —
  Codex reads the summary, then works on that task.
- `aht attach ~/code/api --peek` — print the last screen lines of the
  session there and its state (*quiet for 6 min*); `--lines 40` shows
  more, `--json` gives them as JSON.
- `aht reclaim ~/code/api --stop` — say whether `--stop` would end the
  agent there now, and why not; `--apply` ends it, then takes the project
  back with the catch-up.
- `aht bring /home/me/code/shop --from box --agent codex --apply` — bring
  shop here and open Codex on it with the summary.
- `aht board` — the agent's state on box: *Codex quiet for 6 min*.

## Across systems and folders

Hand Over, Take Back, Bring Here and Send Back work between a Mac, a Linux
machine and a Windows PC (a PC starts Bring Here and Send Back itself; a
PC that answers also takes Hand Over, Take Back and Send Back, and Keep in
sync), also when the project
sits at another path on each machine. This section says what aht does
about paths, names, line endings, executable marks and git, so nothing is
lost on the way.

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
- A machine set up before this version gets `same` when your home
  folder's path exists there, else `home` (always `home` with Windows),
  written into its config once.
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

*on box, /home/me/code/shop holds another folder (412 items). Move it
away there, or choose another place:  aht remote paths box --add
/Users/me/code /home/me/code/mac* (Bring Here offers `--here`). A folder
there that is that machine's own live copy of this project is refused as
well, so an old copy on a PC is never handed over onto the Mac's
project.

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
cannot hold is kept aside under a safe name (`a%3Ab.txt` for `a:b.txt`)
in `~/.aht/handover/<project id>/replaced/<time>/kept-aside/`, and
listed.

**Line endings.** Tools on Windows often end lines with CRLF, tools on a
Mac or Linux with LF. Hand Over and Bring Here copy every file as it is.
On the way back (Take Back and Send Back), for a text file under 5 MB:

- one that changed there only in its line endings is not taken; the one
  at home stays (*3 files differ only in line endings: mac's stay*);
- one that changed there and whose line endings flipped as a whole (all
  LF at home and all CRLF there, or the other way round) comes back with
  its changes and the line endings it left with (*1 file gets back the
  line endings it left mac with*);
- one with mixed line endings, or a new file, comes back as it is. So
  does a binary file, or one of 5 MB or more.

When a git project crosses to or from Windows and has no
`.gitattributes`, the dry run says so and suggests these lines for one at
the top of the project, which keep each file's line endings steady (aht's
window has a **Copy** button for them):

```
* text=auto
*.sh text eol=lf
*.bat text eol=crlf
*.cmd text eol=crlf
*.ps1 text eol=crlf
```

aht never writes that file; add and commit it yourself if you want it.

**Executable marks.** Windows has no "executable" mark. aht notes which
files had it when the project left, and Bring Here to a PC says how many
scripts lose it there. When it comes back from the PC, a file that
replaces one at home keeps the home file's mark, and one that is no
longer at home gets back the mark it left with, so `bin/run.sh` is still
executable on the Mac after a round trip through a PC. Between Macs and
Linux machines the marks travel as they are.

**git.** A copied `.git` folder keeps the settings of the system it came
from. A session that aht starts (after a Hand Over, and after a Bring
Here) gets these in its environment (through `GIT_CONFIG_COUNT` and
`GIT_CONFIG_KEY_0`/`GIT_CONFIG_VALUE_0`):

- `core.filemode=false` when the machine that works on the project is a
  PC, so git does not see every file as changed;
- `core.autocrlf=true` when the project's home is a PC whose git converts
  line endings for it.

aht never edits `.git/config`, and this is not a setting. git that you
run yourself in another terminal does not get them; the dry run says what
to type there, for example *in your own terminal here:  git -c
core.filemode=false status*.

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
> git still has to do: *The two copies are at different commits (mac
> 817965a, here cbc07b5): bring them together with git before going on.*
> Below it is the summary. You run `git pull`, choose Codex under **Open
> in** and press **Open in Codex**. Codex opens and reads the summary
> first. Before you leave, **Machines → Hand Back to mac…** leaves a note
> in paper's folder on the mac. At home, paper shows *pc handed this
> project back at 17:30: Codex worked there from 09:10 to 17:20*.
> **Continue Session** opens your Claude session where it stopped, and it
> learns what Codex did on the PC.

- **The summary** goes into the project's `.aht/handover/` here, which git
  ignores. The other machine builds it from its own histories and masks
  keys there (aht masks it again here). It holds what a summary for
  *Continue in another agent* holds, and names the session it continues.
  Any agent can go on from any other.
- **Which session:** the latest one in that folder there (scripted `claude
  -p` runs do not count). The sheet lists the latest sessions, marked
  *open there* or *working*, and a click picks another one. When one is
  working right now, aht warns that its latest turns may be missing.
- **How aht finds the folder there.** When the work comes back, first the
  folder it came from. Otherwise, in this order, the first that finds
  anything decides, and the sheet says which:
  1. the project's id: in that machine's list of projects, or in the
     `.aht/.project-id` of a folder at the same path or the same place in
     the home folder there;
  2. the same git origin (compared without user name or password) and the
     same first commit, among the repositories in the folders aht watches
     there;
  3. the same path;
  4. the same place in the home folder (`~/code/paper` on both).

  A folder found any other way than by its id could be another project:
  you confirm first (*This is the same project*). When one way finds two
  folders (two clones, say), aht lists both and you pick one. When it
  finds none, type the folder's path there and press **Look There**
  (`--there PATH`).
- **git.** The sheet compares git on both machines and says what to do
  first (*On box: branch main, 1 commit not pushed, 1 file not committed.
  Commit and push there, then pull here.*). The same words head the
  summary, so the agent reads them too. aht never pulls, pushes or fetches
  for you.
- **Open in, or not.** **Open in Codex** (or the agent you choose among
  those installed here) writes the summary and starts that agent with it in
  a new terminal window, after the checks of *Continue in another agent*.
  **Copy the Start Line** writes the summary, opens nothing and puts the
  line that starts the agent on the clipboard. **Cancel** (in aht's
  window, **Done**) writes nothing.
- **Back mode: the work comes back.** When the work went from here to that
  machine (you left a note on it, or it picked the work up from here), Pick
  Up from it brings the work back: a catch-up of what happened there
  since, for the session here that the work left from (**Open Claude
  Code's Session** on a Mac). When that session is gone, a new one reads
  the full summary and the catch-up. The other way round, while work that
  came from box is here, Leave a Note on box hands it back, with only what
  happened here since; **Machines** then offers it first, as **Hand Back
  to box…**. `--full` gives a full summary instead.
- **Leave a Note** (**Machines → Leave a Note on box…**) puts a summary of
  the latest work here into the project's folder on box before you go.
  Nothing runs there. aht only adds files there and never replaces one.
- **When a note arrives** on a machine where aht is installed, a notice
  says so once (*pc left a note on paper*, *pc handed paper back*, or, on
  the machine the work left from, *pc picked up paper*), also on your
  phone when that machine sends notices there. The project shows the note,
  with **Read the Note…** and, when it hands work back to a session here,
  **Continue Session** (in aht's window, **Continue That Session**). The
  next Claude Code session in the folder gets one line from aht's hook,
  once, pointing to the note, which it reads only if you ask; on the
  machine the work left from, a session that starts while the work is out
  is told that work may go on elsewhere.
- **A PC starts Pick Up and Leave a Note itself,** also a PC that answers:
  at the PC, Pick Up from the Mac; before you leave the PC, Leave a Note
  (or Hand Back) on the Mac. **Machines** lists no PC; in the terminal,
  aimed at a PC, both stop with *A Windows PC does this from its own side*.
- **What it costs.** Writing the summary costs nothing. **Open in** makes
  the agent read it as its first turn, which uses tokens, except when the
  work comes back to Claude Code's own session: aht's hook gives it the
  catch-up as it opens. The summary alone and Leave a Note spend nothing;
  only Kimi Code in never-ask mode reads its summary even for **Copy the
  Start Line** (see *The permission level follows the work*).
- **Both machines keep the record:** each exchange leaves a small record
  next to its summary in `.aht/handover/`, here and there; `aht relays`
  lists them.
- **What it needs:** the other machine added under **Machines**, with its
  *For asking* rows in **Check** all ✓.

**In the terminal:**

- `aht pickup ~/Desktop/paper --from box` — say where paper is on box and
  how aht found it, which session it would go on from, and what git still
  has to do; nothing is written.
- `aht pickup ~/Desktop/paper --from box --apply` — write the summary here
  and leave a copy of it and its record on box; nothing opens.
- `aht pickup ~/Desktop/paper --from box --open codex --apply` — then open
  Codex here with the summary (one turn: uses tokens); `--no-window`
  prints the line to run instead (what **Copy the Start Line** does).
- `aht pickup ~/Desktop/paper --from box --session <id>` — go on from that
  session there; `--agent codex` from Codex's latest one; `--there
  /home/me/code/paper` names the folder there; `--full` gives a full
  summary also when the work comes back.
- `aht leave-note ~/Desktop/paper --on box` — say what the note holds and
  where it would go; `--apply` leaves it (`--full` and `--there` as
  above).
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

- **Off until you turn it on** (Settings → Uses tokens, or the first time
  you open it): the agent on the other machine works on your task, which
  uses your tokens. It always goes on in Claude Code.
- **Where it goes:** the machine Hand Over goes to, or another one you
  name (`--to`). Only a Mac or Linux machine: no session starts on a PC.
- This computer has to be awake at both times. If it wakes more than an
  hour after the start time, aht skips that night shift and tells you. If
  the session is still working at the take-back time, aht waits and tries
  again every five minutes.
- **Cancel** stops a planned night shift. A night shift that has started
  can be cancelled too, after a question (**Keep It** or **Cancel the
  Shift**): aht then does not take the project back in the morning, and it
  stays on the other machine until you take it back (**Take Back…**).

**In the terminal:**

- `aht night-shift ~/Desktop/paper --task "run the full benchmark" --start
  22:00 --back 07:00 --apply` — hand the paper project over at ten tonight
  with that task, and take it back from seven in the morning (`--start`
  defaults to now, `--back` to 07:00; `--to homebox` names the machine;
  without `--apply`, show the plan and its level).
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
  had (the default one if that profile is gone) and its tab colour, which
  aht reads from iTerm2's own saved window state. iTerm2 writes that every
  few minutes, so a colour you set just now is in the next save after
  that.
- **iTerm2 closed?** Open Them starts it, waits until it is ready, and puts
  the first tab into the empty window iTerm2 opens as it starts. Tabs that
  iTerm2 brought back by itself are not opened twice, and neither are tabs
  from a second click on Open Them. aht needs permission to control
  iTerm2 (see *Getting started*).

**In the terminal:**

- `aht workspace` — list the saved layouts, with their tabs and sessions.
- `aht workspace --save` — save the layout now; `--save --auto` saves it
  only if `workspace_save_minutes` have passed since the last time (what
  the app does every minute).
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
  tab, the session follows at your next prompt (from the Mac or the
  phone): Claude Code takes a name from outside only through its hooks.
  Until then the Sessions tab shows *→ “name” at its next prompt*.
- **Two sessions, one title:** a second open session under the same tab
  title (another tab, a split pane, the original next to its branch)
  becomes *Paper · 2*. A branch (`/branch`) that is open next to its
  original becomes *Paper ⑂ 2*.
- **The latest name wins, both ways:** rename the tab and the session
  follows. Rename the session yourself (`/rename`, in the Claude app, or
  **Rename…** in the Sessions tab) and its tab takes the name: at once from
  aht's window, otherwise at the session's next prompt. If both were
  renamed since that session's last prompt, the tab's title wins.
- **For the tab to take a name, switch on iTerm2's Python API** (see
  *Getting started*): iTerm2 lets no script change a title you gave a tab,
  but its Python API can, without a prompt. With the API off, the tab
  keeps its title and the session its name. A tab that holds more than
  one session (split panes) keeps its title.
- **Handed over:** on your other machine a session is called *Paper @
  homebox*, so you can tell it from one on this Mac.
- **See and change the names** in the **Sessions** tab: under each Claude
  session its name, where the name came from (*from its tab*, *named by
  you*, *named in aht*, *Claude's own title*) and the tab's title when it
  differs. A key in a name or a tab's title shows masked there, and
  **Rename…** then starts with an empty field, so the masked text never
  becomes the name by accident. A name you give stays until you rename the
  tab, or until **Follow the Tab Again**.
- **Name Sessions After Their Tabs…** (Sessions tab, when iTerm2 is
  installed) gives every open session its tab's title at once, also the
  ones you named yourself. It shows the list of changes first.
- Only a title you set on the tab counts (double-click the tab, or *Edit
  Tab Title*), not what a program writes into it. A tab without one leaves
  the session's name alone.
- For the sessions to be in the app at all, turn on Remote Control for
  all sessions in Claude Code (see *Getting started*).
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
- The links: `aht://search?q=parser` (add `&everywhere=1` to search your
  other machines too), `aht://sessions`, `aht://loose-ends`,
  `aht://report`, `aht://project?path=~/Desktop/paper` (and in the same
  form `changes`, `journal` and `undo`),
  `aht://switch?path=~/Desktop/paper&to=kimi` (add `&resume=1` for that
  agent's own session), `aht://switch?path=~/Desktop/paper&back=1` (Hand
  Back; `&to=claude` straight back to Claude Code),
  `aht://resume?path=~/Desktop/paper&session=<id>` (add `&agent=codex`
  for another agent's session), `aht://getting-started`, `aht://welcome`
  (or `setup`) and `aht://update`.
- For everything else, the Shortcuts action *Run Shell Script* can call the
  `aht` command.

**In the terminal:**

- `open "aht://search?q=parser"` — open the window's search with that word.
- `aht sessions` — list every session aht knows, newest first, with its
  title (what Spotlight gets); `--limit 50` only the newest 50.

## The window at a glance

Every part of the Mac window, and where this guide explains it. A **?**
next to a part opens its section; the **?** at the top opens the whole
guide. How aht's window on Windows and Linux differs is in *On Windows and
Linux*.

- **Projects tab, top row:** a search field over the project list; the
  machine projects are handed over to (a menu when you added several);
  **Sync Now** (copies every project you keep in sync to its machine now);
  **Find Moved Folders**; **Bring Here** with *From box…* for each machine
  aht can ask; **Look Back** with *Loose Ends…* and *Report…*; **Tidy Up
  (n)…** when something needs a decision.
- **The project list:** *Where* (here, handed over, handing over, missing,
  a session open, working or waiting for you), *In sync* (when the kept
  copy was last synced; *paused* while the project is handed over, after
  a Release, or while a sync waits for an answer), *Last used*, *Agents*
  (whose history it has).
- **Under the list, for the selected project:** **Hand Over…** or, while it
  is away, **Take Back…**, **Open Session**, **Peek…** and **Release…**; a
  note with **Check Now** and **Release…** while a handover is unfinished;
  **Send Back to box…** for a project brought here; **Keep in sync**, and a
  note when a sync paused; **Continue Session** (the latest session in a
  new terminal window); **Switch Agent**; **Machines**, once
  you added one, with *Pick Up from box…*, *Leave a Note on box…* and,
  while work picked up from box is here, *Hand Back to box…*; **More**,
  with *Show Sessions…*, *What Changed…*, *Undo a Session…*, *Journal*,
  *AI-Use Statement*, *Share a Session…*, *Project Rules…*, *Check for
  Secrets*, *Second Opinion…*, *Night Shift…* and *Show in Finder*. Notes
  about the project, such as the usage limit, appear below.
- **Sessions tab:** the open sessions here and on your other machines,
  with each Claude session's name and **Rename…**, **Go to Tab**, and for
  one worth a look **Restart in Its Tab…** or **End It…**; at the top
  **Restore Workspace…** and **Name Sessions After Their Tabs…** (when
  iTerm2 is installed) and **Refresh**.
- **Search tab:** the search over all sessions, and *Also on my other
  machines*; **Resume**, **Restore…** and **Show Project** on each result,
  and **Continue Here…** on one from another machine.
- **Machines tab:** the machines you added, with **Sync** (keep every
  project in sync with it, or stop) and how many of those syncs are
  paused, **Bring Here…**, **Check**, **Use for Handover** and **Remove…**
  (refused, with the reason, while the machine holds a project); under
  each one **Watch**, when aht last heard from it, and where projects go
  there. Below them **Add Another…**, and the machines aht found on your
  Tailscale network or in `~/.ssh/config`, each with **Add…**, and **Look
  Again**.
- **Settings tab:** see *Settings*.
- **The bottom line:** what aht is doing right now (with a progress bar for
  transfers) and its version.

## Settings

The groups of the Settings tab. In aht's window on Windows and Linux,
*This Mac* is *This computer*, and Chimes, *The Claude app on your phone*,
*Restore my workspace* and the Spotlight switch are not there.

- **Getting started:** the main steps still to do, and **Show the Steps…**
  for the whole list (see *Getting started*).
- **Watched folders:** the folders aht watches; **Add Folder…** and
  **Remove** (see *Setting up*). Before aht is installed on this Mac (the
  app alone, or Homebrew's `aht` before `aht install`), they still save the
  folders but no watcher follows them yet, and the app says so.
- **When folders change:** what to do when a folder moves or is copied:
  ask, relink automatically, or leave alone.
- **Histories:** notifications, automatic backups, **Back Up Now**,
  **Check All for Secrets…**
- **Notices:** waiting for you, a long piece of work done; also to your
  phone; the sessions in the corner.
- **Chimes:** on or off; a chime each for waits for you, done and the usage
  limit; their volume.
- **The Claude app on your phone:** name sessions after their iTerm2 tabs;
  whether Remote Control is on for every session.
- **Safety nets (no tokens):** a copy of the folder at each session start,
  the usage-limit notice, Spotlight.
- **Restore my workspace:** how often the iTerm2 layout is saved, and how
  many are kept.
- **Uses tokens (off until you turn it on):** informed sessions, the offer
  of another agent at the usage limit, going on by itself when the limit
  resets (Mac), second opinions, the night shift.
- **Permissions:** *The next agent starts in* (follow the session, a fixed
  level, or at most one) and *Codex's never-ask mode* (see *The permission
  level follows the work*).
- **Backups on another machine:** which machine keeps a copy; **Copy Now**;
  **Fetch Backups From…** (see *Backups, and bringing a session back*).
- **Folder badges:** on or off, per kind; **Refresh All**, **Clear All…**
- **Handover:** reachable from the Claude app, compression, mosh, trust
  carried over; **Copies files with** (*rsync where both machines have it,
  else aht's own copy*, *rsync* or *aht's own copy*), with **Ask the
  Machines** and a line that says which one each machine gets.
- **Where each agent keeps its history:** **Choose…** when aht did not find
  an agent's history folder itself; **Reset All to Defaults**.
- **This Mac:** **Start aht in the menu bar at login**; *Tell me when a new
  version of aht is out* and **Check Now** (see *New versions*); **Open
  session windows in** (iTerm or Terminal; automatic picks iTerm when it is
  installed); **Run Setup Again…** (see *Setting up*); **Adopt This Mac's
  Projects…** (`aht adopt`; its question names the projects you told aht
  to forget, since adopting takes them on again); **Reinstall or Update
  aht…**; **Restart Watcher**; **Run Diagnostics**; **Open Log**; **Open
  Data Folder** (`~/.aht`); **Edit Config File** (the settings you
  changed, as text; one not there has its default).

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
- `watcher_owner` (agent) — `agent`: the watcher runs on its own (a
  LaunchAgent on a Mac, a systemd user service or autostart entry on
  Linux, a sign-in entry on Windows). It notices when you move or rename
  a project folder and relinks its histories right away, for every agent,
  so your sessions follow the folder. `none`: no watcher. On a Mac and on
  Linux, setting it stops the watcher that runs (and removes what starts
  it at login), and `aht install` then sets up none; a moved folder is
  relinked only when a Claude Code session starts in it (the Claude hook),
  or when you look with **Find Moved Folders Now** (`aht reconcile`).
  Back to `agent` (`aht config --set watcher_owner=agent`, or `aht
  install`) starts it again.
- `log_level` (info) — how much goes into the log: `debug`, `info`, `warn`,
  `error`.

**Agents**

- `backends` (all) — which agents' histories aht looks after.
- `backend_roots` (none) — where an agent keeps its history, when aht did
  not find it itself (`aht backends --set-root`, or Settings → Where each
  agent keeps its history).

**The permission level** (see *The permission level follows the work*)

- `agent_permissions` (follow) — the level the next agent starts in:
  `follow` (the level of the session it continues), a fixed level (`ask`,
  `edits`, `auto`, `never`), or a cap (`max:auto`).
- `agent_permission_flags` (none) — per agent and level, the flags that
  replace aht's own, as `{"codex": {"never": ["-a", "never", "-s",
  "workspace-write"]}}` (Codex's never-ask that keeps its sandbox); flags
  that ask for more than their level are refused.

**Folder badges**

- `icons_enabled` (on), `icons_agent` (on), `icons_git` (on) — badges at
  all, the agent discs, the git "+".
- `linux_emblem_method` (auto), `linux_agent_emblem`, `linux_git_emblem` —
  the same on Linux: how the emblems are set, and an emblem of your icon
  theme to use instead of aht's own (the git one's default is `aht-git`,
  aht's own "+").

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
- `handover_transfer` (auto) — what copies the files: `auto` (rsync when
  this machine has rsync 3, the other has rsync, and neither is Windows;
  else aht's own copy), `rsync` or `aht` (see *What copies the files*
  under *Hand a project over to another machine*).
- `handover_remote_control` (on) — a handed-over session is reachable from
  the Claude app, named after its tab and the machine (a key in that name
  is masked); Antigravity, when you switch to it, starts with
  `--remote-control` too.
- `handover_carry_trust` (on) — a folder trusted here is trusted there.
- `handover_claude_args` (none) — extra options for the session over there,
  after the flags of its permission level.
- `handover_mosh` (on) — open a handed-over session with mosh when it gets
  through.
- `handover_keep_awake` (on) — the other machine does not sleep while the
  agent works there (a closed lid still does).
- `rsync_path` (the newest rsync found) — which rsync to use, when rsync
  copies the files.

**Notices**

- `notify_waiting` (on), `notify_finished` (on), `notify_finished_minutes`
  (3) — a session waits for you; a piece of work that took at least that
  many minutes is done.
- `notify_phone` (none) — `imessage:<your number or Apple ID>` or
  `ntfy:<topic>` (or `ntfy:https://<your server>/<topic>`; `http://` only
  for a server on this computer).
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

**Search, reports, this computer**

- `report_areas` (none) — named folders for *Report → by area*, as
  `{"Work": "~/Desktop/Work"}`.
- `hotkey` (ctrl+opt+cmd+a) — the shortcut that opens the search.
- `spotlight` (on) — session titles in Spotlight.
- `tab_names` (on) — name each Claude session after its iTerm2 tab.
- `workspace_save_minutes` (10), `workspace_keep` (40) — how often the app
  saves the iTerm2 layout for *Restore my workspace* (it also saves when a
  session gets a prompt, while `tab_names` is on; 0 saves only then), and
  how many layouts are kept.
- `terminal_app` (automatic: iTerm when installed, else Terminal) — on a
  Mac, the app that opens session windows; Settings → This Mac → *Open
  session windows in*. Another app name works only if that app runs the
  `.command` file aht hands it.
- `update_check` (off) — once a day, ask GitHub whether a new version of aht
  is out (see *New versions*).

**Before and after a session**

- `checkpoints` (on; off on Windows and Linux), `checkpoint_keep` (10) — a
  copy of the folder when a session starts; how many per project.
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
and act only with `--apply`; `install`, `uninstall`, `config`, `roots`,
`reload` and `backends` act at once.

- `aht tag ~/Desktop/paper --apply` — start tracking a folder now, instead
  of waiting for aht to find it.
- `aht adopt --apply` — track every folder under the watched folders that
  already has agent history (the window's *Adopt This Mac's Projects…*),
  also one you told aht to forget; the list marks those *(you told aht to
  forget it)*.
- `aht orphans` — list Claude histories that no tracked folder owns;
  `--match` suggests the folder each one belongs to.
- `aht suggest-matches --store <name>` — the likeliest folders for one such
  history (`--limit` how many, 8 otherwise; also for `orphans`).
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
- `aht reload` — make the watcher read its settings again. Before aht is
  installed on a Mac (the app before setup, Homebrew's `aht` before `aht
  install`), it and the commands that change the watched folders save
  what you set, and say *the watcher is not installed yet*.
- `aht backends` — where each agent keeps its history on this computer;
  `--set-root claude=/path` and `--clear-root claude` change it.
- `aht keys ~/Desktop/paper` — under which name each agent files the
  history of that folder.
- `aht encode ~/Desktop/paper` — the folder name Claude Code uses for that
  path.
- `aht version` — the version of aht.
- `aht install` — set aht up on this computer: the watcher (none when
  `watcher_owner` is `none`; one left running then stops), the notices,
  the Claude hooks and the `aht` command; `--src` installs from another
  folder (the app uses this).
- `aht uninstall` — remove all of that again; histories are never touched.
  `--remove-icons` also clears the badges (on Linux also aht's emblem
  images, and their icon cache when no other icons are left there);
  `--purge` also removes aht's markers, list of projects and settings.
- `aht hook` — what Claude Code runs when a session starts and at each
  prompt; not for typing yourself.
- `aht window --port 8765` — serve aht's window on that port instead of a
  free one; `--selftest` checks the window's server.
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
- Options such as `--quiet`, `--status-file`, `backup --auto`, `setup
  --dismiss` (the welcome's Not Now), `checkpoint --session`/`--agent`
  (what the hook passes), `second-opinion --run`, `night-shift --step` and
  `tab-names --refresh` are what the app and aht's background jobs use;
  `--json` gives any command's answer in a form scripts can read.

## Where things are

- `~/.aht/` holds aht's own data: `registry.json` (which folder is which
  project), `config.json` (the settings you changed), `machine.json` (this
  computer's random id), `offsite.json` (which backups went to which
  machine), `backups/`, `search.db`, `aht.log` and `aht-watcher.log`,
  `handover/`, `rules-backups/`, `changes-backups/`, `redacted/`,
  `checkpoints/` (the copies to undo a session with), `undo/` (what an
  undo set aside), `opinions/` (second opinions), `night-shift.json`,
  `workspaces/` (saved iTerm2 layouts), `run/` (what aht keeps while it
  runs, such as `perm.json` with the levels it started sessions in),
  `remote/` (what another machine sent here: copies, sessions, and
  `copies.json`), `offsite/` (backups other computers keep here),
  `arrivals/` (a PC's *Continue here*) and `tools/` (the installed copy
  of aht).
- Inside each project, `.aht/.project-id` is the folder's identity; it
  travels with the folder when you move or copy it. `.aht/handover/` and
  `.aht/journal/` hold summaries and journals; git ignores both.

## When something looks wrong

- **Settings → Run Diagnostics** checks every part.
- macOS says *"badge_icon" Not Opened*: run `aht install` once.
- A machine shows as not reachable: is it switched on, and is Tailscale
  connected here? When only its name stops working, aht reaches it at its
  Tailscale address by itself.
- The log: **Settings → Open Log**.

**In the terminal:**

- `aht doctor` — check every part of aht and say what is wrong.
- `aht install` — set aht up again (watcher, Claude hook, command).
- `aht logs --errors` — show the recent warnings and errors.
- `aht logs -n 200` — the last 200 lines of the log; `--watcher` adds the
  watcher's own log.
- `aht guide` — this guide, in the terminal; `--path` says where its file
  is.
