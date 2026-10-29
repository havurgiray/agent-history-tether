#!/usr/bin/env python3
"""[17h] after phase 9: a PC that answers receives more; masked texts; ntfy over
https; queues that stay small; watcher_owner none; the home's version; the
effective checkpoint setting."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)

print("\n[17h] after phase 9: a PC that answers receives more; masked texts; ntfy over https; "
      "queues that stay small; watcher_owner none; the home's version; the effective "
      "checkpoint setting")
FIXTURES9B = HERE / "fixtures" / "phase9b"

def phase9b_suite():
    """Follow-ups to phase 9.  Machines are folders here (test mode): mac,
    box (a Mac or Linux machine, with a stand-in tmux), and pc and pc2,
    test machines with `system: "Windows"` (their cores answer as a PC's
    do: no session starts there).  Each machine's own aht runs with that
    folder's home.  No ssh, no real agent, no token."""
    import shlex, signal as _sig
    fx = []
    base = Path(os.path.realpath(sb)) / "p9b"
    stubs = base / "stubs"
    stubs.mkdir(parents=True)
    fake = f'#!/bin/sh\nexec "{PY}" "{HERE / "fake_tmux.py"}" "$@"\n'
    (stubs / "tmux").write_text(fake)
    (stubs / "claude").write_text('#!/bin/sh\n[ "$1" = "--version" ] && '
                                  'echo "9.9.9 (Claude Code)"\nexit 0\n')
    for f in stubs.iterdir():
        f.chmod(0o755)
    (base / "no-tabs.json").write_text("{}")
    roots_ = {n: base / n for n in ("mac", "mac2", "box", "pc", "pc2")}

    def menv(name, **kw):
        """A machine's own aht: its home is <root>/home, as the far end's is
        when another machine asks it."""
        h = roots_[name] / "home"
        (h / ".claude" / "projects").mkdir(parents=True, exist_ok=True)
        e = {k: v for k, v in env.items() if not k.startswith("AHT_ROOT")}
        e.pop("AHT_ROOTS", None)
        e.update(HOME=str(h), AHT_HOME=str(h / ".aht"),
                 AHT_ROOT_CLAUDE=str(h / ".claude" / "projects"), AHT_MACHINE_NAME=name,
                 AHT_CLAUDE=str(stubs / "claude"), AHT_REMOTE_PATH=str(stubs),
                 AHT_NO_MIRROR="1", AHT_NO_SEARCH_INDEX="1", AHT_AGENT_PROCS="[]",
                 AHT_REMOTE_AGENT_PROCS="[]", AHT_ITERM_TABS=str(base / "no-tabs.json"),
                 AHT_NOTIFY_LOG=str(base / f"{name}-notices.log"),
                 AHT_TERMINAL_LOG=str(base / f"{name}-terminal.log"),
                 AHT_CLAUDE_MANAGED_SETTINGS=str(base / "no-managed-settings.json"))
        for k in ("GEMINI", "CURSOR", "OPENCODE", "CODEX", "COPILOT", "KIMI", "KIMI_CODE",
                  "VIBE", "AGY"):
            (roots_[name] / "tools" / k.lower()).mkdir(parents=True, exist_ok=True)
            e[f"AHT_ROOT_{k}"] = str(roots_[name] / "tools" / k.lower())
        e.update(kw)
        return e
    envs = {"mac": menv("mac", AHT_REMOTE_MACHINE_NAME="pc"),
            "mac2": menv("mac2", AHT_REMOTE_MACHINE_NAME="pc"),
            "box": menv("box", AHT_REMOTE_MACHINE_NAME="pc"),
            # the PC's own runs: Windows for names, line endings and git
            "pc": menv("pc", AHT_AS_WINDOWS="1", AHT_REMOTE_MACHINE_NAME="pc2"),
            "pc2": menv("pc2")}

    def raw(m, *a, **extra):
        return subprocess.run([PY, LAUNCH, *a], env=dict(envs[m], **extra),
                              capture_output=True, text=True)
    def J(m, *a, **extra):
        r = raw(m, *a, **extra)
        try:
            d = json.loads(r.stdout)
        except ValueError:
            d = {"unparsed": r.stdout[-600:] + r.stderr[-900:]}
        if isinstance(d, dict):
            d["_rc"] = r.returncode
        return d
    def home(m):
        return roots_[m] / "home"
    def reg(m):
        try:
            return json.loads((home(m) / ".aht" / "registry.json").read_text())["projects"]
        except (OSError, ValueError, KeyError):
            return {}
    def copies(m):
        try:
            return json.loads((home(m) / ".aht" / "remote" / "copies.json").read_text())
        except (OSError, ValueError):
            return {}
    def project(m, name, files):
        p = home(m) / "code" / name
        for rel, body in files.items():
            (p / rel).parent.mkdir(parents=True, exist_ok=True)
            (p / rel).write_text(body)
        p = os.path.realpath(p)
        raw(m, "tag", p, "--apply")
        return p
    def session(m, real, sid, text="refactor the checkout"):
        st = home(m) / ".claude" / "projects" / enc(real)
        st.mkdir(parents=True, exist_ok=True)
        (st / f"{sid}.jsonl").write_text("".join(json.dumps(e) + "\n" for e in (
            {"type": "user", "cwd": real, "sessionId": sid, "version": "9.9.9",
             "entrypoint": "cli", "timestamp": iso(time.time() - 600),
             "message": {"role": "user", "content": text}},
            {"type": "ai-title", "aiTitle": "Checkout flow"})))
        return st
    PC = {"root": str(roots_["pc"]), "system": "Windows"}
    for m in ("mac", "box"):
        J(m, "config", "--set", "remotes=" + json.dumps(
            {"pc": PC, "box": {"root": str(roots_["box"])}}))
        J(m, "config", "--set", "handover_keep_awake=false")
    J("mac2", "config", "--set", "remotes=" + json.dumps({"pc": PC}))
    J("pc", "config", "--set", "remotes=" + json.dumps(
        {"pc2": {"root": str(roots_["pc2"]), "system": "Windows"},
         "box": {"root": str(roots_["box"])}}))
    J("pc", "config", "--set", "handover_keep_awake=false")
    TOKEN = "ghp_" + "Q7d9Lm2Xv8Kp4Rt6Wz1Yb3Nc5Hf0Js2Ae4Gu"

    # ---- (1) the task and the Remote Control name leave masked ---------------
    paper = project("mac", "paper", {"draft.md": "x\n"})
    S1 = "7a1b2c3d-1111-4222-8333-444455556666"
    session("mac", paper, S1)
    tabs = home("mac") / ".aht" / "run" / "tab-names.json"
    tabs.parent.mkdir(parents=True, exist_ok=True)
    tabs.write_text(json.dumps({S1: {"names": [f"Deploy {TOKEN}"], "tab": f"Deploy {TOKEN}",
                                     "at": time.time()}}))
    d = J("mac", "handover", paper, "--to", "box", "--apply", "--json",
          "--task", f"push the release with {TOKEN} and tell me",
          AHT_REMOTE_MACHINE_NAME="box")
    win = (d.get("away") or {}).get("window") or "none"
    wf = home("box") / ".faketmux" / f"{win}.json"
    line = json.loads(wf.read_text()).get("command", "") if wf.is_file() else ""
    far_paper = str(roots_["box"]) + paper
    briefs = "".join(p.read_text() for p in Path(far_paper, ".aht", "handover").glob("*.md")) \
        if Path(far_paper, ".aht", "handover").is_dir() else ""
    cmd_txt = "".join(p.read_text() for p in
                      (home("box") / ".aht" / "remote" / "run").glob("*/command.txt"))
    away = next((e.get("away") for e in reg("mac").values() if e.get("real_path") == paper),
                None) or {}
    names = (json.loads(tabs.read_text()).get(S1) or {}).get("names") or []
    ck(d.get("applied") and line and TOKEN not in line + cmd_txt + briefs
       and TOKEN not in json.dumps(away) and TOKEN not in str(d.get("task"))
       and "[GitHub token: ghp_…Gu]" in str(d.get("task"))
       and "--remote-control 'Deploy [GitHub token: ghp_…Gu] @ box'" in line
       and "-- 'push the release with [GitHub token: ghp_…Gu] and tell me'" in line
       and "[GitHub token: ghp_…Gu]" in briefs
       and names[-1:] == ["Deploy [GitHub token: ghp_…Gu] @ box"],
       f"handover --task and the Remote Control name: masked before they leave (the first "
       f"prompt, the summary there, the window's line, the away record here) "
       f"({d.get('error') or d.get('blockers')}, {line[-260:]}, {away.get('task')})")
    for w in (home("box") / ".faketmux").glob("*.json"):   # the stand-in session
        try:
            os.kill(int(json.loads(w.read_text()).get("pid") or 0), _sig.SIGTERM)
        except (OSError, ValueError, TypeError):
            pass

    # ---- (2) ntfy only over https (or to this computer) ----------------------
    bad = ["ntfy:http://ntfy.example.org/aht", "ntfy:HTTP://ntfy.example.org/x",
           "ntfy:http://localhost@ntfy.example.org/x", "ntfy:http://127.0.0.1.example.org/x"]
    good = ["ntfy:https://ntfy.example.org/aht", "ntfy:my-topic", "ntfy:http://localhost:8080/t",
            "ntfy:http://127.0.0.1/t", "ntfy:http://[::1]:2586/t", "imessage:+15550100"]
    rb = [raw("mac", "config", "--set", f"notify_phone={v}") for v in bad]
    cfg = json.loads((home("mac") / ".aht" / "config.json").read_text())
    rg = [raw("mac", "config", "--set", f"notify_phone={v}").returncode for v in good]
    ck(all(r.returncode == 2 and "plain http" in r.stderr and "unencrypted" in r.stderr
           for r in rb) and "notify_phone" not in cfg and rg == [0] * len(good),
       f"config --set notify_phone: plain http to another machine refused (exit 2, why), "
       f"https, a topic and a server on this computer taken "
       f"({[r.returncode for r in rb]}, {rb[0].stderr.strip()[:160]}, {rg})")
    cfg = json.loads((home("mac") / ".aht" / "config.json").read_text())
    cfg["notify_phone"] = bad[0]            # set before aht refused it, or by hand
    (home("mac") / ".aht" / "config.json").write_text(json.dumps(cfg))
    nl = base / "mac-notices.log"
    if nl.is_file():
        nl.unlink()
    r = raw("mac", "notices", "--test")
    sent = [json.loads(l) for l in nl.read_text().splitlines()] if nl.is_file() else []
    lg = (home("mac") / ".aht" / "aht.log").read_text() \
        if (home("mac") / ".aht" / "aht.log").is_file() else ""
    ck(sent and all(s.get("phone") == "" and "plain http" in (s.get("refused") or "")
                    for s in sent)
       and "NOTICE not sent to the phone: the phone setting (notify_phone) is plain http" in lg
       and "ntfy.example.org" not in lg and "not to ntfy:http://ntfy.example.org/aht" in r.stdout,
       f"an http:// value already set: nothing goes to the phone, the log warns (naming the "
       f"setting, not its address) "
       f"({sent}, {r.stdout.strip()[-200:]})")
    J("mac", "config", "--unset", "notify_phone")

    # ---- (3) the queues to the Mac app and the Windows tray stay small -------
    q = base / "queue" / "tray-notices.jsonl"
    q.parent.mkdir(parents=True)
    def queue(rec):                         # the core's writer (or, without it, an append)
        w = getattr(core, "queue_notice", None)
        if w:
            return w(q, rec)
        with open(q, "a") as fh:
            fh.write(json.dumps(rec) + "\n")
    for i in range(500):
        queue({"title": f"n{i}", "message": "m", "info": {}, "at": i})
    full = q.read_text().splitlines()
    off0 = q.stat().st_size                  # a reader that showed them all
    queue({"title": "fresh", "message": "m", "info": {}, "at": 9e9})
    size = q.stat().st_size
    def reader_reads(offset):
        """As the tray and the app read: from where they stopped, or from the
        top when the file got smaller (it was started anew)."""
        size = q.stat().st_size
        if size < offset:
            offset = 0
        with open(q, "rb") as fh:
            fh.seek(offset)
            got = [json.loads(l)["title"] for l in fh.read().decode().splitlines() if l]
        return got, size
    got1, offset = reader_reads(off0)
    queue({"title": "next", "message": "m", "info": {}, "at": 9e9 + 1})
    got2, offset = reader_reads(offset)
    ck(len(full) == getattr(core, "NOTICE_QUEUE_MAX", 0) == 500 and size < off0
       and got1 == ["fresh"] and got2 == ["next"]
       and len(q.read_text().splitlines()) == 2,
       f"a notice queue at 500 lines starts over with the new one: a reader that went "
       f"by offset sees exactly the new notice, then the next ({len(full)}, {got1}, {got2})")
    if sys.platform == "darwin":
        aq = home("mac") / ".aht" / "run" / "app-notices.jsonl"
        aq.parent.mkdir(parents=True, exist_ok=True)
        aq.write_text("".join(json.dumps({"title": f"old{i}", "message": "m", "info": {},
                                          "at": i}) + "\n" for i in range(500)))
        (aq.parent / "app-alive").touch()       # the app runs: it shows the notices
        ne = dict(envs["mac"])
        ne.pop("AHT_NO_NOTIFY", None)
        ne.pop("AHT_NOTIFY_LOG", None)
        r = subprocess.run([PY, "-c", "import sys; sys.path.insert(0, sys.argv[1]); import aht; "
                            "aht.notify_user('shop is on box', 'Continue there', {'k': 1})",
                            str(HERE.parent)], env=ne, capture_output=True, text=True)
        lines_ = aq.read_text().splitlines()
        ck(r.returncode == 0 and len(lines_) == 1
           and json.loads(lines_[0])["title"] == "shop is on box",
           f"the Mac app's queue (app-notices.jsonl) the same: 500 old lines, then the new "
           f"notice alone ({len(lines_)} line(s), {r.stderr[-200:]})")
    stf = home("mac") / ".aht" / "run" / "stage-12345.json"
    staged = project("mac", "staged", {"a.txt": "a\n"})
    d = J("mac", "handover", staged, "--to", "pc", "--json", "--status-file", str(stf))
    d2 = J("mac", "reclaim", staged, "--json", "--status-file", str(stf))
    ck(d.get("pc") is True and "this project is not handed over" in str(d2.get("blockers"))
       and not stf.exists() and not Path(str(stf) + ".new").exists(),
       f"a --status-file (the Mac app's stage-*.json) is gone when its command ends, also "
       f"one that stops early ({sorted(p.name for p in stf.parent.glob('stage-*'))}, "
       f"{d.get('blockers') or d.get('error')})")

    # ---- (4) watcher_owner=none: no watcher, and a running one stops ---------
    wh = home("mac2")
    tools_dir = wh / ".aht" / "tools" / "agent-history-tether"
    tools_dir.mkdir(parents=True, exist_ok=True)
    clog = FAKEBIN / "calls.log"
    def start_watcher():
        if sys.platform == "darwin":            # the Mac's watcher: a program of its own
            prog = tools_dir / "watcher"
            prog.write_text("#!/bin/sh\ntrap 'kill $p 2>/dev/null; exit 0' TERM\n"
                            "sleep 600 & p=$!\nwait $p\n")
            prog.chmod(0o755)
            return subprocess.Popen([str(prog)], cwd="/")
        prog = tools_dir / "watcher.py"         # Linux's is a script its Python runs
        prog.write_text("import time\ntime.sleep(600)\n")
        return subprocess.Popen([PY, str(prog)], cwd="/")
    def ended(p, secs=8):
        t0 = time.time()
        while time.time() - t0 < secs:
            if p.poll() is not None:
                return True
            time.sleep(0.1)
        return False
    if sys.platform == "darwin":
        reg_file = wh / "Library" / "LaunchAgents" / "com.aht.watcher.plist"
    else:
        reg_file = wh / ".config" / "systemd" / "user" / "aht-watcher.service"
    reg_file.parent.mkdir(parents=True, exist_ok=True)
    reg_file.write_text("the watcher's registration\n")
    w = start_watcher()
    prog_path = str(tools_dir / ("watcher" if sys.platform == "darwin" else "watcher.py"))
    decoy = subprocess.Popen(["tail", "-f", prog_path], cwd="/", stdout=subprocess.DEVNULL)
    before = clog.read_text() if clog.is_file() else ""
    try:
        r = raw("mac2", "config", "--set", "watcher_owner=none")
        gone = ended(w)
        calls = (clog.read_text() if clog.is_file() else "")[len(before):]
        ck(r.returncode == 0 and gone and decoy.poll() is None and not reg_file.exists()
           and (f"launchctl bootout gui/{os.getuid()}/com.aht.watcher" in calls
                if sys.platform == "darwin" else
                "systemctl --user disable --now aht-watcher.service" in calls)
           and "watching is off" in r.stdout,
           f"config --set watcher_owner=none: the running watcher ends (its own pid, by its "
           f"command line), its registration goes, a program that only names it stays "
           f"({r.returncode}, {gone}, {reg_file.exists()}, {calls.strip()[-200:]}, "
           f"{r.stdout.strip()[-300:]})")
        r = raw("mac2", "config", "--set", "watcher_owner=sometimes")
        ck(r.returncode == 2 and "watcher_owner expects agent" in r.stderr,
           f"watcher_owner takes agent or none ({r.stderr.strip()})")
        # the installer: with none it neither writes nor loads the watcher,
        # and stops one left running; with agent it does both
        w = start_watcher()
        inst = HERE.parent / ("install.py" if sys.platform == "darwin" else
                              os.path.join("linux", "install.py"))
        steps = ("stage_files compile_binaries write_notices_plist install_command install_hook "
                 "unquarantine load_notices write_plist load_agent write_service "
                 "check_inotify_budget").split()
        probe = ("import sys, json, importlib.util\n"
                 "sys.argv = [sys.argv[1]] + sys.argv[3:]\n"
                 "spec = importlib.util.spec_from_file_location('aht_installer', sys.argv[0])\n"
                 "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
                 "calls = []\n"
                 f"for n in {steps!r}:\n"
                 "    if hasattr(m, n):\n"
                 "        setattr(m, n, (lambda n: lambda *a, **k: calls.append(n) or [])(n))\n"
                 "m.aht.cmd_getting_started = lambda a: 0\n"
                 "m.main()\n"
                 "print('CALLS ' + json.dumps(calls))\n")
        ie = dict(envs["mac2"], PYTHONPATH=str(HERE.parent))
        r1 = subprocess.run([PY, "-c", probe, str(inst), "x"], env=ie, capture_output=True,
                            text=True)
        gone = ended(w)
        J("mac2", "config", "--set", "watcher_owner=agent", "--no-reload")
        r2 = subprocess.run([PY, "-c", probe, str(inst), "x"], env=ie, capture_output=True,
                            text=True)
        c1 = json.loads(r1.stdout.split("CALLS ", 1)[1]) if "CALLS " in r1.stdout else None
        c2 = json.loads(r2.stdout.split("CALLS ", 1)[1]) if "CALLS " in r2.stdout else None
        wsteps = (["write_plist", "load_agent"] if sys.platform == "darwin"
                  else ["write_service", "load_agent"])
        ck(c1 is not None and not set(wsteps) & set(c1) and gone
           and "no watcher (watcher_owner=none)" in r1.stdout
           and c2 is not None and [c for c in c2 if c in wsteps] == wsteps,
           f"aht install with watcher_owner=none: no watcher is written or started, the one "
           f"running stops; with agent it is ({c1}, {gone}, {c2}, "
           f"{(r1.stderr or r2.stderr).strip()[-300:]})")
    finally:
        for p in (w, decoy):                # SIGTERM: the stand-in ends its sleep too
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(10)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()

    # ---- (5) Keep in sync to a PC: the guards and pauses of any machine ------
    shop = project("mac", "shop", dict({"src/app.py": "old\n"},
                                       **{f"data/d{i:02}.txt": f"{i}\n" for i in range(24)}))
    far = str(roots_["pc"]) + shop
    r = raw("mac", "mirror", shop, "--on", "--to", "pc")
    d = J("mac", "mirror", shop, "--run", "--json")
    row = (d.get("mirrored") or [{}])[0]
    cp = copies("pc").get(far) or {}
    ck(r.returncode == 0 and row.get("status") == "synced"
       and Path(far, "src", "app.py").read_text() == "old\n"
       and len(list(Path(far, "data").iterdir())) == 24
       and cp.get("kind") == "sync" and cp.get("from") == "mac",
       f"Keep in sync to a PC: the copy goes there with aht's own copy, the PC notes it as "
       f"a copy kept in sync from mac ({row.get('reason') or row.get('status')}, {cp})")
    time.sleep(1.1)
    Path(far, "src", "app.py").write_text("changed on the pc\n")
    d = J("mac", "mirror", shop, "--run", "--json")
    row = (d.get("mirrored") or [{}])[0]
    p = row.get("paused") or {}
    notes = [json.loads(l) for l in (base / "mac-notices.log").read_text().splitlines()] \
        if (base / "mac-notices.log").is_file() else []
    ck(row.get("status") == "paused" and p.get("reason") == "changed"
       and p.get("files") == ["src/app.py"] and p.get("remote") == "pc"
       and Path(far, "src", "app.py").read_text() == "changed on the pc\n"
       and any(n.get("title") == "Keep in sync paused: shop" for n in notes),
       f"…a file changed on the PC pauses the sync: nothing is sent, a notice says so "
       f"({row.get('reason')})")
    dd = J("mac", "reclaim", shop, "--json")
    da = J("mac", "reclaim", shop, "--apply", "--json")
    d = J("mac", "mirror", shop, "--run", "--json")
    row = (d.get("mirrored") or [{}])[0]
    ck(dd.get("mode") == "copy" and ((dd.get("plan") or {}).get("project") or {}).get("take") == 1
       and da.get("applied") and Path(shop, "src", "app.py").read_text() == "changed on the pc\n"
       and row.get("status") == "synced",
       f"…Bring Them Here takes the PC's change, and the sync goes on "
       f"({dd.get('blockers') or dd.get('error')}, {da.get('error')}, {row.get('reason')})")
    for i in range(10):
        os.unlink(os.path.join(shop, "data", f"d{i:02}.txt"))
    d = J("mac", "mirror", shop, "--run", "--json")
    row = (d.get("mirrored") or [{}])[0]
    d2 = J("mac", "mirror", shop, "--allow-removals", "--apply", "--json")
    ck(row.get("status") == "paused" and (row.get("paused") or {}).get("reason") == "removals"
       and d2.get("applied") and len(list(Path(far, "data").iterdir())) == 14,
       f"…removing many files pauses it too, until the removals are allowed "
       f"({row.get('reason')}, {d2.get('error') or d2.get('blockers')})")
    Path(shop, "aux.md").write_text("notes\n")
    Path(shop, "src", "app.py").write_text("newer here\n")
    d = J("mac", "mirror", shop, "--run", "--json")
    row = (d.get("mirrored") or [{}])[0]
    ck(row.get("status") == "skipped" and "cannot hold" in (row.get("reason") or "")
       and "aux.md" in (row.get("reason") or "") and not Path(far, "aux.md").exists()
       and Path(far, "src", "app.py").read_text() == "changed on the pc\n",
       f"…a name the PC cannot hold (aux.md): nothing is sent, as a handover sends nothing "
       f"({row.get('status')}, {row.get('reason')})")
    os.unlink(os.path.join(shop, "aux.md"))
    d = J("mac", "mirror", shop, "--run", "--json")
    ck((d.get("mirrored") or [{}])[0].get("status") == "synced"
       and Path(far, "src", "app.py").read_text() == "newer here\n",
       "…renamed here, the next sync sends it")
    other = project("mac", "other", {"a.txt": "a\n"})
    Path(str(roots_["pc"]) + other).mkdir(parents=True)
    Path(str(roots_["pc"]) + other, "theirs.txt").write_text("the PC's own\n")
    raw("mac", "mirror", other, "--on", "--to", "pc")
    d = J("mac", "mirror", other, "--run", "--json")
    row = (d.get("mirrored") or [{}])[0]
    ck(row.get("status") == "paused" and (row.get("paused") or {}).get("reason") == "other-folder"
       and not Path(str(roots_["pc"]) + other, "a.txt").exists(),
       f"…a first sync into a folder on the PC that holds other files pauses "
       f"({row.get('reason')})")

    # ---- (6) backups kept on a PC, and fetched back --------------------------
    bk = home("mac") / ".aht" / "backups" / "0123456789ab"
    bk.mkdir(parents=True)
    zipb = b"PK\x05\x06" + bytes(18) + b"made on mac"
    (bk / "20261028-120000.zip").write_bytes(zipb)
    (bk / "20261028-120000.meta.json").write_text('{"project": "shop"}')
    J("mac", "config", "--set", "offsite_backup=pc")
    d = J("mac", "backup", "--offsite", "--json")
    mid = d.get("folder") or "none"
    there = home("pc") / ".aht" / "offsite" / mid / "backups" / "0123456789ab"
    lst = J("mac", "backup", "--offsite-list", "--json")
    row = next((f for f in lst.get("folders") or [] if f.get("id") == mid), {})
    ck(d.get("_rc") == 0 and (d.get("files") or 0) >= 1 and d.get("machine") == "pc"
       and (there / "20261028-120000.zip").read_bytes() == zipb
       and row.get("name") == "mac" and row.get("files") == d.get("files"),
       f"backups kept on a PC: copied there byte for byte, listed by computer "
       f"({d.get('error') or d.get('unparsed') or d}, {row})")
    fx += fixture_ok(d, "backup_offsite.json")
    J("mac2", "config", "--set", "offsite_backup=pc")
    d = J("mac2", "backup", "--fetch-offsite", "--json")
    got = home("mac2") / ".aht" / "backups" / "0123456789ab" / "20261028-120000.zip"
    ck(d.get("_rc") == 0 and d.get("files") == row.get("files")
       and (d.get("from") or {}).get("name") == "mac" and got.is_file()
       and got.read_bytes() == zipb,
       f"…and fetched back from the PC on another computer ({d.get('error') or d})")
    fx += fixture_ok(d, "backup_fetch_offsite.json")

    # ---- (7) a PC hands a project over to another PC that answers ------------
    notes_p = project("pc", "notes", {"todo.txt": "one\n"})
    S2 = "8b2c3d4e-1111-4222-8333-444455556666"
    session("pc", notes_p, S2, "plan the week")
    (home("pc") / ".claude.json").write_text(json.dumps(
        {"projects": {notes_p: {"hasTrustDialogAccepted": True}}}))
    (home("pc2") / ".claude.json").write_text("{}")
    far2 = str(roots_["pc2"]) + notes_p
    dd = J("pc", "handover", notes_p, "--to", "pc2", "--json")
    d = J("pc", "handover", notes_p, "--to", "pc2", "--apply", "--json")
    w2 = (d.get("away") or {}).get("window") or "none"
    arr = home("pc2") / ".aht" / "arrivals" / f"{w2}.json"
    rec = json.loads(arr.read_text()) if arr.is_file() else {}
    tj = json.loads((home("pc2") / ".claude.json").read_text()).get("projects") or {}
    a2 = J("pc2", "_arrival", "--json")
    ck(dd.get("pc") is True and not dd.get("blockers") and d.get("applied")
       and d.get("started") is False and d.get("start_reason") == "windows"
       and Path(far2, "todo.txt").read_text() == "one\n"
       and rec.get("from") == "pc" and rec.get("session") == S2
       and (tj.get(far2) or {}).get("hasTrustDialogAccepted") is True
       and [x.get("name") for x in a2.get("arrivals") or []] == [w2],
       f"a PC hands a project over to another PC: the files there, no session starts, the "
       f"other PC's tray offers Continue here, the trust goes along "
       f"({dd.get('blockers') or d.get('error') or d.get('blockers')}, {rec.get('text')})")
    Path(far2, "todo.txt").write_text("one\ntwo\n")
    d = J("pc", "reclaim", notes_p, "--apply", "--json")
    ck(d.get("applied") and Path(notes_p, "todo.txt").read_text() == "one\ntwo\n"
       and not arr.exists(),
       f"…and takes it back: the work comes, the arrival there is gone ({d.get('error')})")
    ck(core.map_path("C:\\Users\\ann\\code\\notes", "home", "C:\\Users\\ann", "D:\\Users\\bo",
                     "Windows", "Windows") == "D:\\Users\\bo\\code\\notes",
       "between two PCs a project goes below the other PC's home folder")

    # ---- (8) Send Back to a PC that handed a project over ---------------------
    frompc = project("pc", "frompc", {"x.txt": "x\n", "keep.txt": "keep\n"})
    d = J("pc", "handover", frompc, "--to", "box", "--apply", "--no-start", "--json",
          AHT_REMOTE_MACHINE_NAME="box")
    farP = str(roots_["box"]) + frompc
    J("box", "config", "--set", "remotes=" + json.dumps({"box2": {"root": str(base / "x")}}))
    d0 = J("box", "send-back", farP, "--json")
    J("box", "config", "--set", "remotes=" + json.dumps({"pc": PC}))
    Path(farP, "x.txt").write_text("x, edited on box\n")
    Path(farP, "new.txt").write_text("made on box\n")
    # (item 5) the home's aht: protocol 2 is not enough, nor one without an op
    mark = home("pc") / ".aht" / "install.json"
    mark.write_text(json.dumps({"version": "0.13.0", "protocol": 2}))
    d1 = J("box", "send-back", farP, "--json")
    mark.write_text(json.dumps({"version": "0.13.9", "protocol": 3, "ops": [
        o for o in getattr(core, "HOME_OPS", ("probe",)) if o != "return-plan"]}))
    d2 = J("box", "send-back", farP, "--json")
    J("pc", "status", "--json")                 # the PC's own aht notes its version again
    d3 = J("box", "send-back", farP, "--json")
    d4 = J("box", "send-back", farP, "--apply", "--json")
    e = next((x for x in reg("pc").values() if x.get("real_path") == frompc), {})
    ck(d.get("applied") and any("pc is not set up on this machine" in b
                                and "OpenSSH Server" in b for b in d0.get("blockers") or [])
       and not d3.get("blockers") and (d3.get("plan") or {}).get("project", {}).get("take") == 1
       and d4.get("applied") and Path(frompc, "x.txt").read_text() == "x, edited on box\n"
       and Path(frompc, "new.txt").read_text() == "made on box\n"
       and not e.get("away") and (copies("box").get(farP) or {}).get("kind") == "returned",
       f"Send Back of what a PC handed over: to the PC, when it answers and is set up here "
       f"(else: add it, it needs OpenSSH Server); the PC has its project again "
       f"({d0.get('blockers')}, {d3.get('blockers') or d3.get('error')}, {d4.get('error')})")
    fx += fixture_ok(d3, "send_back_dry.json", FIXTURES7)
    b1 = " ".join(d1.get("blockers") or [])
    b2 = " ".join(d2.get("blockers") or [])
    ck(b1.startswith(f"update aht on pc first: Bring Here and Send Back need aht {core.VERSION} "
                     "or newer there") and "protocol 2" in b1
       and "update aht on pc first" in b2 and "without return-plan" in b2,
       f"the home's aht at protocol 2, or without an op Send Back uses: update aht on pc "
       f"first ({b1}; {b2})")
    # Bring Here asks the same of the home (box's aht at protocol 2)
    J("box", "status", "--json")
    (home("box") / ".aht" / "install.json").write_text(
        json.dumps({"version": "0.13.0", "protocol": 2}))
    d = J("pc", "bring", "--from", "box", "--list", "--json", AHT_REMOTE_MACHINE_NAME="box")
    ck(any(b.startswith("update aht on box first: Bring Here and Send Back need aht")
           for b in d.get("blockers") or []),
       f"bring --list from a home at protocol 2: update aht on box first ({d.get('blockers')})")

    # ---- (9) status --json: the setting the core uses, default included ------
    se = dict(envs["mac2"])
    se.pop("AHT_NO_CHECKPOINT", None)
    s0 = json.loads(subprocess.run([PY, LAUNCH, "status", "--json"], env=se, capture_output=True,
                                   text=True).stdout or "{}")
    fx += fixture_ok(s0, "status_effective.json", FIXTURES9B)
    probe = ("import sys, json, io, contextlib, argparse; sys.path.insert(0, sys.argv[1]); "
             "import aht; aht.IS_MAC = False; b = io.StringIO()\n"
             "with contextlib.redirect_stdout(b): aht.cmd_status(argparse.Namespace(json=True))\n"
             "print(json.dumps(json.loads(b.getvalue())['effective']))")
    nm0 = subprocess.run([PY, "-c", probe, str(HERE.parent)], env=se, capture_output=True,
                         text=True).stdout.strip()
    subprocess.run([PY, LAUNCH, "config", "--set", "checkpoints=true"], env=se, capture_output=True)
    nm1 = subprocess.run([PY, "-c", probe, str(HERE.parent)], env=se, capture_output=True,
                         text=True).stdout.strip()
    subprocess.run([PY, LAUNCH, "config", "--set", "checkpoints=false"], env=se, capture_output=True)
    s2 = json.loads(subprocess.run([PY, LAUNCH, "status", "--json"], env=se, capture_output=True,
                                   text=True).stdout or "{}")
    ck((s0.get("effective") or {}).get("checkpoint_on_start") is (sys.platform == "darwin")
       and nm0 == '{"checkpoint_on_start": false}' and nm1 == '{"checkpoint_on_start": true}'
       and (s2.get("effective") or {}).get("checkpoint_on_start") is False,
       f"status --json effective.checkpoint_on_start: what the core uses — on by default "
       f"on a Mac only, off by default on Windows and Linux, the setting once chosen "
       f"({s0.get('effective')}, {nm0}, {nm1}, {s2.get('effective')})")
    ck(not fx, f"the JSON keeps every key of the samples ({fx})")

if os.name == "nt" or handover_name(sb) > 255:
    print("  SKIP after phase 9: its stand-ins need macOS or Linux and a short sandbox path")
else:
    phase9b_suite()

done()
