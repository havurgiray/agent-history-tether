#!/usr/bin/env python3
"""A stand-in for ssh in the tests: "the other machine" is this one, with a
home folder of its own.

FAKE_SSH_DIR holds one folder per host name:
  <host>/home         that machine's own home (where a login starts)
  <host>/path         its PATH, one line
  <host>/env          more of its login environment, KEY=VALUE lines (optional)
  <host>/windows      present: it answers like cmd.exe on a Windows PC (or like
                      PowerShell when the file says "powershell").  The shell
                      check is answered; any other command fails, the way those
                      shells fail on aht's sh scripts, and leaves what they
                      would leave: cmd.exe folders named -p and $HOME in the
                      home, PowerShell the folders named in the home itself
  <host>/refuse       present: ssh itself fails there (exit 255) with the
                      file's line, such as "Permission denied (publickey)."
                      or "Host key verification failed."
  <host>/die-after    N: a call of aht's agent is cut off once N bytes went
                      either way (its input ends there, then ssh exits 255
                      and passes nothing more on)
  <host>/hang-after   N: as die-after, but the link goes quiet instead
Every command it is given is noted in <host>/commands.log, one JSON string a
line.  A host without a folder cannot be reached (exit 255, as ssh)."""
import json, os, subprocess, sys, threading, time
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
        if cmd.strip() == "echo aht-os %OS% $env:OS":
            sys.stdout.write("aht-os Windows_NT $env:OS\r\n")
            return 0
        if "mkdir -p" in cmd:
            (home / "-p").mkdir(exist_ok=True)
            (home / "$HOME").mkdir(exist_ok=True)
        sys.stderr.write("'cat' is not recognized as an internal or external command,\r\n"
                         "operable program or batch file.\r\n")
        return 1
    env = {"HOME": str(home), "USER": "far", "LOGNAME": "far", "SHELL": "/bin/sh",
           "PATH": (machine / "path").read_text().strip(), "LANG": "en_US.UTF-8"}
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
