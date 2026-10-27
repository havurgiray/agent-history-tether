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
Every command it is given is noted in <host>/commands.log, one JSON string a
line.  A host without a folder cannot be reached (exit 255, as ssh)."""
import json, os, sys
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
    os.execve("/bin/sh", ["sh", "-c", cmd], env)

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
