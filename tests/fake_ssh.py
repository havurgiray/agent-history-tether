#!/usr/bin/env python3
"""A stand-in for ssh in the tests: "the other machine" is this one, with a
home folder of its own.

FAKE_SSH_DIR holds one folder per host name:
  <host>/home         that machine's own home (where a login starts)
  <host>/path         its PATH, one line
  <host>/env          more of its login environment, KEY=VALUE lines (optional)
  <host>/windows      present: it answers like cmd.exe on a Windows PC (or like
                      PowerShell when the file says "powershell").  The shell
                      check is answered; a sh script fails, the way those
                      shells fail on it, and leaves what they would leave:
                      cmd.exe folders named -p and $HOME in the home,
                      PowerShell the folders named in the home itself.  Any
                      other line is read as cmd.exe reads it: one with %, $ or
                      a backtick (which cmd or PowerShell would expand), or
                      with & | < > ^ outside quotes, is refused; the rest is
                      split into words by the C runtime's rules, and its
                      program runs if the PC has it:
  <host>/aht            aht.exe on its PATH: empty, this checkout's core
                        (`aht _agent …`); else the path of a stand-in script
  <host>/py, <host>/python   a Python there (the launcher, `py -3`, or
                        python): python3 here runs it
                      else "is not recognized" (in German with a file
                      <host>/lang that says "de": Windows in another language).
                      A program runs with the home as its folder and its
                      USERPROFILE, and AHT_TEST_FAR_NT=1 (aht's core then
                      answers as a PC's does)
  <host>/refuse       present: ssh itself fails there (exit 255) with the
                      file's line, such as "Permission denied (publickey)."
                      or "Host key verification failed."
  <host>/die-after    N: a call of aht's agent is cut off once N bytes went
                      either way (its input ends there, then ssh exits 255
                      and passes nothing more on)
  <host>/hang-after   N: as die-after, but the link goes quiet instead
  <host>/cut-input    N: once, the copy of aht written there (its input, the
                      core) is cut off after N bytes: the command gets those
                      and its input ends, its output goes nowhere, and ssh
                      exits 255 (the link dropped); the file is then removed
Every command it is given is noted in <host>/commands.log, one JSON string a
line.  A host without a folder cannot be reached (exit 255, as ssh)."""
import json, os, subprocess, sys, tempfile, threading, time
from pathlib import Path

# the options of OpenSSH's ssh that take a value
WITH_VALUE = set("BbcDEeFIiJLlmOoPpQRSWw")

def main(argv):
    i, show_config = 0, False
    while i < len(argv) and argv[i].startswith("-"):
        a = argv[i]
        if a == "-G":
            show_config = True
        if len(a) == 2 and a[1] in WITH_VALUE:
            i += 2
            continue
        i += 1
    if i >= len(argv):
        print("usage: ssh destination [command]", file=sys.stderr)
        return 255
    host = argv[i].rpartition("@")[2]
    if show_config:
        print(f"hostname {host}")
        return 0
    machine = Path(os.environ["FAKE_SSH_DIR"]) / host
    if not machine.is_dir():
        print(f"ssh: Could not resolve hostname {host}: nodename nor servname "
              "provided, or not known", file=sys.stderr)
        return 255
    cmd = " ".join(argv[i + 1:])
    with open(machine / "commands.log", "a") as fh:
        fh.write(json.dumps(cmd) + "\n")
    if (machine / "refuse").is_file():
        line = (machine / "refuse").read_text().strip()
        print(line if line.startswith("ssh:") or "verification" in line
              else f"{argv[i]}: {line}", file=sys.stderr)
        return 255
    home = machine / "home"
    if (machine / "cut-input").is_file() and ("cat > " in cmd or "stdin.buffer.read" in cmd):
        cut_input(machine)
    if (machine / "windows").exists():
        if (machine / "windows").read_text().strip() == "powershell":
            if cmd.strip() == "echo aht-os %OS% $env:OS":
                # Write-Output: each word on a line; %OS% is not expanded there
                sys.stdout.write("aht-os\r\n%OS%\r\nWindows_NT\r\n")
                return 0
            if "mkdir -p" in cmd:               # $HOME is the user's own home there
                (home / ".aht" / "remote").mkdir(parents=True, exist_ok=True)
                sys.stderr.write("The term 'cat' is not recognized as a name of a cmdlet, "
                                 "function, script file, or executable program.\r\n")
                return 1
            return windows_line(machine, home, cmd, powershell=True)
        if cmd.strip() == "echo aht-os %OS% $env:OS":
            sys.stdout.write("aht-os Windows_NT $env:OS\r\n")
            return 0
        if "mkdir -p" in cmd:
            (home / "-p").mkdir(exist_ok=True)
            (home / "$HOME").mkdir(exist_ok=True)
            sys.stderr.write("'cat' is not recognized as an internal or external command,\r\n"
                             "operable program or batch file.\r\n")
            return 1
        return windows_line(machine, home, cmd, powershell=False)
    # no agent of this computer's runs there (a test that wants some names
    # them in the machine's env file)
    env = {"HOME": str(home), "USER": "far", "LOGNAME": "far", "SHELL": "/bin/sh",
           "PATH": (machine / "path").read_text().strip(), "LANG": "en_US.UTF-8",
           "AHT_AGENT_PROCS": "[]"}
    if (machine / "env").is_file():
        for line in (machine / "env").read_text().splitlines():
            k, _, v = line.partition("=")
            if k:
                env[k] = v
    os.chdir(home)
    for kind in ("die-after", "hang-after"):
        if "_agent" in cmd and (machine / kind).is_file():
            return relay(cmd, env, int((machine / kind).read_text()), kind == "hang-after")
    os.execve("/bin/sh", ["sh", "-c", cmd], env)

def cut_input(machine):
    """<host>/cut-input: see the top.  In the child the command goes on with
    its input cut short; this process waits for it and drops the link."""
    data = sys.stdin.buffer.read()
    n = int((machine / "cut-input").read_text())
    cut = len(data) > n
    tf = tempfile.TemporaryFile()
    tf.write(data[:n] if cut else data)
    tf.flush()
    tf.seek(0)
    os.dup2(tf.fileno(), 0)
    if not cut:
        return
    (machine / "cut-input").unlink()
    sys.stdout.flush()
    sys.stderr.flush()
    pid = os.fork()
    if pid == 0:                            # the command there: nothing comes back
        dn = os.open(os.devnull, os.O_WRONLY)
        os.dup2(dn, 1)
        os.dup2(dn, 2)
        return
    os.waitpid(pid, 0)
    sys.stderr.write("Connection to far closed by remote host.\n")
    sys.stderr.flush()
    os._exit(255)

def win_split(line):
    """Words of a Windows command line, as the C runtime splits them
    (CommandLineToArgvW): quotes group, backslashes are literal unless they
    stand before a quote."""
    args, cur, inq, have, i = [], [], False, False, 0
    while i < len(line):
        c = line[i]
        if c == "\\":
            n = 0
            while i < len(line) and line[i] == "\\":
                n += 1
                i += 1
            if i < len(line) and line[i] == '"':
                cur.append("\\" * (n // 2))
                if n % 2:
                    cur.append('"')
                    i += 1
            else:
                cur.append("\\" * n)
            have = True
            continue
        if c == '"':
            inq, have = not inq, True
        elif c in " \t" and not inq:
            if have:
                args.append("".join(cur))
                cur, have = [], False
        else:
            cur.append(c)
            have = True
        i += 1
    if have:
        args.append("".join(cur))
    return args

def windows_line(machine, home, cmd, powershell):
    """Run a line as cmd.exe (or PowerShell) on the PC would: see the top."""
    words = win_split(cmd)
    prog, rest = (words[0].lower(), words[1:]) if words else ("", [])
    me = Path(__file__).resolve()
    argv = None
    if prog == "aht" and (machine / "aht").is_file():
        stand_in = (machine / "aht").read_text().strip()
        argv = [sys.executable, stand_in or str(me.parent.parent / "aht.py")] + rest
    elif prog == "py" and (machine / "py").is_file():
        argv = [sys.executable] + [a for a in rest if a != "-3"]
    elif prog == "python" and (machine / "python").is_file():
        argv = [sys.executable] + rest
    if argv is None:
        de = (machine / "lang").is_file() and (machine / "lang").read_text().strip() == "de"
        if de:
            sys.stderr.write((f"{prog} : Die Benennung \"{prog}\" wurde nicht als Name eines "
                              "Cmdlet, einer Funktion, einer Skriptdatei oder eines "
                              "ausführbaren Programms erkannt.\r\n") if powershell else
                             f"Der Befehl \"{prog}\" ist entweder falsch geschrieben oder\r\n"
                             "konnte nicht gefunden werden.\r\n")
        else:
            sys.stderr.write((f"{prog} : The term '{prog}' is not recognized as the name of "
                              "a cmdlet, function, script file, or operable program.\r\n")
                             if powershell else
                             f"'{prog}' is not recognized as an internal or external "
                             "command,\r\noperable program or batch file.\r\n")
        return 1
    bad = [c for c in "%$`" if c in cmd]
    outside, inq = [], False
    for c in cmd:
        if c == '"':
            inq = not inq
        elif not inq and c in "&|<>^":
            outside.append(c)
    if bad or outside or inq:
        sys.stderr.write(f"fake_ssh: this line is not read alike by cmd.exe and PowerShell "
                         f"({''.join(bad + outside) or 'an open quote'}): {cmd}\r\n")
        return 1
    env = {"HOME": str(home), "USERPROFILE": str(home), "USERNAME": "far",
           "PYTHONDONTWRITEBYTECODE": "1",
           "PATH": (machine / "path").read_text().strip() if (machine / "path").is_file()
           else os.environ.get("PATH", ""), "LANG": "en_US.UTF-8", "AHT_TEST_FAR_NT": "1",
           "AHT_AGENT_PROCS": "[]"}
    if (machine / "env").is_file():
        for l in (machine / "env").read_text().splitlines():
            k, _, v = l.partition("=")
            if k:
                env[k] = v
    os.chdir(home)
    os.execve(argv[0], argv, env)

def relay(cmd, env, limit, hang):
    """The command with its input and output passed on, until `limit` bytes
    went either way: then the link is cut (or goes quiet)."""
    p = subprocess.Popen(["/bin/sh", "-c", cmd], env=env, stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE)
    st = {"n": 0, "dead": False}
    lock = threading.Lock()
    def over(n):
        with lock:
            st["n"] += n
            if st["n"] > limit and not st["dead"]:
                st["dead"] = True
                return True
            return st["dead"]
    def cut():
        if hang:
            time.sleep(3600)
        try:
            p.stdin.close()             # the far end's input ends mid-way
        except OSError:
            pass
        try:
            p.wait(10)
        except subprocess.TimeoutExpired:
            p.kill()
        os._exit(255)
    def up():
        while True:
            b = sys.stdin.buffer.read1(1 << 16)
            if not b:
                break
            if over(len(b)):
                cut()
            p.stdin.write(b)
            p.stdin.flush()
        p.stdin.close()
    threading.Thread(target=up, daemon=True).start()
    while True:
        b = p.stdout.read1(1 << 16)
        if not b:
            break
        if over(len(b)):
            cut()
        sys.stdout.buffer.write(b)
        sys.stdout.buffer.flush()
    with lock:
        dead = st["dead"]
    if dead:
        time.sleep(3600)                # the cutting thread ends this process
    return p.wait()

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
