#!/usr/bin/env python3
"""[23] diagnostics: the warnings and errors, here and on the other machines;
the apps' own; a problem report that keeps names, addresses and keys out."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)

print("\n[23] diagnostics: the warnings and errors, here and on the other machines; "
      "the apps' own; a problem report that keeps names, addresses and keys out")
FIXTURES10 = HERE / "fixtures" / "phase10"

def phase10_suite():
    """This machine (mac), a test machine (box: a folder with its own home),
    a PC asked over "ssh" (fake_ssh: this checkout's core answers as aht.exe
    there), one with an older aht there and one that does not answer.  Each
    log holds a planted warning with a host, a user name, an address, a path
    under its home and a key.  No ssh, no real agent, no token."""
    fx = []
    base = Path(os.path.realpath(sb)) / "phase10"
    who = "ottoline"                        # the user name planted everywhere
    hm = base / who                         # this machine's home: it carries the name
    hm.mkdir(parents=True)
    key = "ghp_" + "R4nd0mT0k3nV4lu3Xy9Zq8Wp7Lm6Kj5Hg4Fd3"
    stubs = base / "stubs"
    stubs.mkdir()
    for a in ("claude", "kimi", "codex", "agy", "vibe"):
        (stubs / a).write_text(f'#!/bin/sh\n[ "$1" = "--version" ] && echo "1.2.{len(a)} ({a})"\n'
                               "exit 0\n")
        (stubs / a).chmod(0o755)
    sshbin = base / "sshbin"
    sshbin.mkdir()
    (sshbin / "ssh").write_text(f'#!/bin/sh\nexec "{PY}" "{HERE / "fake_ssh.py"}" "$@"\n')
    (sshbin / "ssh").chmod(0o755)
    fdir = base / "far"
    de = dict(env, HOME=str(hm), AHT_HOME=str(hm / ".aht"), USER=who, LOGNAME=who,
              USERNAME=who, AHT_MACHINE_NAME="mac", FAKE_SSH_DIR=str(fdir),
              PATH=str(sshbin) + os.pathsep + env["PATH"], AHT_NO_SEARCH_INDEX="1",
              AHT_NO_MIRROR="1", AHT_CLAUDE=str(stubs / "claude"),
              **{f"AHT_CLI_{a.upper()}": str(stubs / a)
                 for a in ("claude", "kimi", "codex", "agy", "vibe")})
    de.pop("AHT_ROOTS", None)
    def D(*a, **extra):
        return subprocess.run([PY, LAUNCH, *a], env=dict(de, **extra), capture_output=True,
                              text=True)
    def DJ(*a, **extra):
        r = D(*a, **extra)
        try:
            d = json.loads(r.stdout)
        except ValueError:
            d = {"unparsed": r.stdout[-600:] + r.stderr[-900:]}
        if isinstance(d, dict):
            d["_rc"] = r.returncode
        return d
    stamp = lambda ago: time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - ago))
    def plant(logf, ago, level, text):
        logf.parent.mkdir(parents=True, exist_ok=True)
        with open(logf, "a", encoding="utf-8") as fh:
            fh.write(f"[{stamp(ago)}] [{level:<5}] {text}\n")

    # the other machines: box (a folder), pc (fake_ssh, aht.exe there), old
    # (an aht.exe that knows no log-tail), gone (no answer)
    box = base / "box"
    bh = box / "home"
    plant(bh / ".aht" / "aht.log", 7200, "WARN", "BOX an old warning, before the hours asked")
    plant(bh / ".aht" / "aht.log", 300, "WARN",
          f"BOX the copy into {bh}/code/shop failed for {who}@203.0.113.77 (from "
          f"203.0.113.77) with {key}")
    plant(bh / ".aht" / "aht.log", 290, "INFO", "BOX an ordinary line")
    pc = fdir / "198.51.100.23"
    (pc / "home").mkdir(parents=True)
    (pc / "windows").write_text("")
    (pc / "aht").write_text("")
    (pc / "path").write_text(de["PATH"])
    (pc / "env").write_text("AHT_NO_ICONS=1\nAHT_NO_NOTIFY=1\nAHT_MACHINE_NAME=pc\n")
    plant(pc / "home" / ".aht" / "aht.log", 200, "ERROR",
          f"UNCAUGHT Traceback (most recent call last):\n"
          f'  File "{pc / "home"}\\aht.py", line 7, in <module>\n'
          f"OSError: [WinError 5] Access is denied: 'C:\\\\Users\\\\{who}\\\\code'")
    old = fdir / "198.51.100.24"
    (old / "home").mkdir(parents=True)
    (old / "windows").write_text("")
    (old / "aht").write_text(str(base / "old_aht.py"))
    (base / "old_aht.py").write_text(
        "import json, sys\nreq = json.loads(sys.stdin.readline() or '{}')\n"
        "print('\\n@@AHT@@' + json.dumps({'ok': False, 'error': 'unknown operation ' "
        "+ repr(req.get('op'))}))\n")
    (old / "path").write_text(de["PATH"])
    D("config", "--set", "remotes=" + json.dumps({
        "box": {"root": str(box)},
        "pc": {"ssh": f"{who}@198.51.100.23", "system": "Windows", "runner": "aht"},
        "old": {"ssh": f"{who}@198.51.100.24", "system": "Windows", "runner": "aht"},
        "gone": {"ssh": f"{who}@planthost.example"}}),
      "notify_phone=ntfy:quiet-heron-5521", "--no-reload")
    # this machine: a warning, an UNCAUGHT error with its traceback, an
    # info line and an old warning
    ml = hm / ".aht" / "aht.log"
    plant(ml, 7300, "WARN", "MAC an old warning")
    plant(ml, 100, "WARN", f"MAC not copied: {hm}/code/shop/a.py on planthost.example")
    plant(ml, 90, "INFO", "MAC an ordinary line")
    plant(ml, 80, "ERROR", "UNCAUGHT Traceback (most recent call last):\n"
          f'  File "{hm}/aht.py", line 9, in main\n'
          f"KeyError: 'real_path' (key {key})")
    before = (bh / ".aht" / "aht.log").read_bytes()
    # (the system's Python on a Mac keeps its byte code under ~/Library: not aht's)
    box_files = sorted(str(p.relative_to(box)) for p in box.rglob("*") if "Library" not in p.parts)

    # (1) logs --errors --everywhere: by time, each line with its machine
    d = DJ("logs", "--errors", "--everywhere", "--hours", "1", "--json")
    fx += fixture_ok(d, "logs_errors_everywhere.json", FIXTURES10)
    es = d.get("entries") or []
    ms = {m["machine"]: m for m in d.get("machines") or []}
    order = [(e["machine"], e["text"].split(" ")[0]) for e in es]
    ck(d.get("_rc") == 0 and order[:4] == [("box", "BOX"), ("pc", "UNCAUGHT"), ("mac", "MAC"),
                                           ("mac", "UNCAUGHT")]
       and all(es[i]["t"] <= es[i + 1]["t"] for i in range(len(es) - 1))
       and not any("old warning" in e["text"] or "ordinary" in e["text"] for e in es),
       f"logs --errors --everywhere: the last hour's warnings and errors of mac, box and "
       f"the PC, by time, each with its machine; info lines and older ones left out "
       f"({order}, {d.get('unparsed')})")
    far = " ".join(e["text"] for e in es if e["machine"] != "mac")
    ck(all(x not in far for x in (who, "203.0.113.77", key, str(bh), str(pc / "home")))
       and "[address]" in far and "~/code/shop" in far and "[GitHub token: ghp_" in far,
       f"what the other machines sent is masked: no user name, address, key or home "
       f"folder ({far[:400]})")
    tb = next((e["text"] for e in es if e["machine"] == "pc"), "")
    ck(tb.count("\n") == 2 and "Access is denied" in tb and "line 7" in tb,
       f"an UNCAUGHT error comes with its traceback ({tb!r})")
    ck(ms.get("box", {}).get("reachable") and ms.get("pc", {}).get("reachable")
       and ms.get("box", {}).get("lines") == 1
       and not ms.get("gone", {}).get("reachable")
       and "planthost" not in str(ms.get("gone")) and "[gone]" in str(ms["gone"].get("error"))
       and "older" in str(ms.get("old", {}).get("error"))
       and "update aht on old" in str(ms["old"].get("error")),
       f"a machine that does not answer is named with why, masked; an older aht there "
       f"says so ({ms.get('gone')}, {ms.get('old')})")
    now_files = sorted(str(p.relative_to(box)) for p in box.rglob("*") if "Library" not in p.parts)
    ck((bh / ".aht" / "aht.log").read_bytes() == before and now_files == box_files,
       f"log-tail is read only: the box's log and files stay as they were "
       f"({sorted(set(now_files) ^ set(box_files))})")
    r = D("logs", "--errors", "--everywhere", "--hours", "1")
    ck(r.returncode == 0 and "] [WARN ] box: BOX the copy into ~/code/shop" in r.stdout
       and "gone: no log from it — " in r.stdout and "    KeyError: 'real_path'" in r.stdout,
       f"…in words: one line each, the traceback indented, who did not answer "
       f"({r.stdout[-700:]})")
    r = D("logs", "--errors")
    ck(r.returncode == 0 and "MAC an old warning" in r.stdout and "INFO" not in r.stdout,
       "logs --errors without --everywhere or --hours: as before (the log's last lines)")

    # (2) the apps' own errors: masked, on one line, rate-limited
    r = D("_log", "--level", "warn", "--source", "mac-app", "--",
          f"-the sync button failed: {key}\nsecond line")
    lg = ml.read_text()
    ck(r.returncode == 0 and "[WARN ] APP mac-app: -the sync button failed: [GitHub token: "
       "ghp_…d3] ⏎ second line" in lg and key not in lg.split("APP mac-app")[1],
       "aht _log: the Mac app's error in the log, its key masked, on one line")
    for i in range(23):
        D("_log", "--source", "tray", "--", f"the tray failed, try {i}")
    D("_log", "--source", "tray", "--", "the tray failed, try 22")
    lg = ml.read_text()
    n_tray = lg.count("APP tray: the tray failed")
    ck(n_tray == 20 and lg.count("APP tray: 20 lines in a minute") == 1,
       f"aht _log: at most 20 lines a minute from one app, then one line that says so "
       f"({n_tray})")
    D("_log", "--source", "window", "--", "same thing")
    D("_log", "--source", "window", "--", "same thing")
    ck(ml.read_text().count("APP window: same thing") == 1,
       "aht _log: the same message again within seconds is counted, not logged")
    st = json.loads((hm / ".aht" / "run" / "app-log.json").read_text())
    ck(st["tray"]["held"] == 4 and st["window"]["held"] == 1,
       f"…what is held back is counted ({st})")
    r = D("_log", "--level", "info", "--source", "window", "--", "x")
    r2 = D("_log", "--source", "watcher", "--", "x")
    ck(r.returncode == 2 and r2.returncode == 2, "aht _log: only warn or error, only aht's apps")

    # (3) the far end's own uncaught errors keep their traceback
    rq = json.dumps({"op": "written-by", "files": [7]})
    subprocess.run([PY, LAUNCH, "_agent"], input=rq, env=dict(de, HOME=str(bh),
                   AHT_HOME=str(bh / ".aht")), capture_output=True, text=True)
    bl = (bh / ".aht" / "aht.log").read_text()
    ck("UNCAUGHT AGENT TypeError" in bl and "Traceback (most recent call last)" in bl,
       f"the far end logs what failed there with its traceback ({bl[-500:]})")
    (bh / ".aht" / "aht.log").write_bytes(before)

    # (4) report-problem: one file, nothing sent anywhere, no name, address or key
    reg = base / "code" / "shop"
    reg.mkdir(parents=True)
    D("tag", str(reg), "--apply")
    # what the apps pass: a file in aht's reports folder, which is not there yet
    rdir = hm / ".aht" / "reports"
    first = rdir / "problem-20261028-120000.txt"
    had = rdir.exists()
    d = DJ("report-problem", "--out", str(first), "--json")
    ck(not had and d.get("_rc") == 0 and d.get("path") == str(first.resolve())
       and first.is_file() and first.read_text().startswith("aht problem report")
       and stat_mode(rdir) & 0o077 == 0,
       f"report-problem --out <reports>/problem-<time>.txt --json: the folder is made (only "
       f"its owner's), the file is text ({d.get('unparsed') or d.get('path')})")
    d1 = DJ("report-problem", "--out", str(base / "for-the-bug") + os.sep)
    d2 = DJ("report-problem", "--out", str(base / "code"), "--json")
    inside = sorted(p.name for p in (base / "for-the-bug").iterdir()) \
        if (base / "for-the-bug").is_dir() else []
    ck(d1.get("_rc") == 0 and len(inside) == 1 and inside[0].startswith("problem-")
       and inside[0].endswith(".txt") and Path(d2.get("path") or "/").parent
       == (base / "code").resolve() and str(d2.get("path")).endswith(".json"),
       f"report-problem --out FOLDER/ (made) or an existing folder: problem-<time> inside "
       f"({inside}, {d2.get('path')})")
    d = DJ("report-problem", "--everywhere", "--hours", "1", "--out", str(base / "r.txt"),
           "--json")
    fx += fixture_ok(d, "report_problem.json", FIXTURES10)
    txt = (base / "r.txt").read_text() if (base / "r.txt").is_file() else ""
    planted = [who, "planthost", "198.51.100.23", "198.51.100.24", "203.0.113.77", key,
               str(hm), str(bh), "quiet-heron", __import__("platform").node()]
    leaks = [p for p in planted if p and p in txt]
    ck(d.get("_rc") == 0 and txt and not leaks,
       f"report-problem: no host, user name, address, home path, key or ntfy topic in the "
       f"file (leaked: {leaks})")
    ck(txt.startswith("aht problem report") and "Nothing was sent anywhere" in txt[:1200]
       and f"aht:       {core.VERSION} (protocol {core.AGENT_PROTOCOL}" in txt
       and "Python " in txt and "Claude Code    1.2.6 (claude)" in txt
       and "Mistral Vibe   1.2.4 (vibe)" in txt
       and '"notify_phone": "[hidden]"' in txt and '"ssh": "[hidden]"' in txt
       and "1 tracked (0 folder(s) missing)" in txt
       and "] [WARN ] box: BOX the copy into ~/code/shop" in txt
       and "] [ERROR] pc: UNCAUGHT" in txt and "] [WARN ] this machine: MAC not copied" in txt
       and "gone: no log from it — " in txt,
       f"report-problem: says first what it holds and that nothing is sent; aht, the "
       f"system, the agents, the settings, the counts, every machine's warnings "
       f"({txt[:300]!r} … {txt[-600:]!r})")
    ck(d.get("path") == str((base / "r.txt").resolve()) and d.get("bytes") == len(txt.encode())
       and d.get("errors") == len([l for l in txt.splitlines() if l.startswith("[2")])
       and sorted(m["machine"] for m in d.get("machines") or [])
       == ["box", "gone", "old", "pc", "this machine"],
       f"report-problem --json: path, bytes, machines, errors ({ {k: d.get(k) for k in ('path', 'bytes', 'errors')} })")
    ck(stat_mode(base / "r.txt") & 0o077 == 0, "the report is readable only by its owner")
    d = DJ("report-problem", "--json")
    rf = Path(d.get("path") or base / "none")
    try:
        rep = json.loads(rf.read_text())
    except (OSError, ValueError):
        rep = {}
    fx += fixture_ok(rep, "report_problem_file.json", FIXTURES10)
    ck(rf.parent == hm / ".aht" / "reports" and rf.name.startswith("problem-")
       and rf.suffix == ".json" and rep.get("about", "").startswith("aht's problem report")
       and rep.get("registry", {}).get("projects") == 1
       and not any(p in rf.read_text() for p in planted if p),
       f"report-problem --json: in ~/.aht/reports, as JSON, masked too ({rf}, {list(rep)[:6]})")
    for _ in range(6):
        D("report-problem")
    kept = sorted(p.name for p in (hm / ".aht" / "reports").iterdir())
    ck(len(kept) == 5 and all(k.startswith("problem-") for k in kept)
       and first.name not in kept and len(list((base / "for-the-bug").iterdir())) == 1
       and (base / "r.txt").is_file(),
       f"the newest 5 reports are kept in aht's reports folder; one written elsewhere "
       f"stays ({kept})")

    # (5) a silent catch now says what failed, once, and masks the error
    probe = ("import sys, os, time; sys.path.insert(0, sys.argv[1]); import aht\n"
             "p = aht.aht_home() / 'is-a-file'\np.parent.mkdir(parents=True, exist_ok=True)\n"
             "p.write_text('x')\naht.queue_notice(p / 'q.jsonl', {'a': 1})\n"
             "for _ in range(3): aht.warn_once('k', 'MANY the same cause')\n"
             f"print(aht._errmsg(OSError(13, 'denied with {key}')))\n")
    r = subprocess.run([PY, "-c", probe, str(HERE.parent)], env=de, capture_output=True,
                       text=True)
    lg = ml.read_text()
    ck("NOTICE not queued in q.jsonl: FileExistsError" in lg
       and lg.count("MANY the same cause") == 1 and key not in r.stdout
       and "[GitHub token" in r.stdout,
       f"a catch that went on without a word now warns, once per cause, the error masked "
       f"({r.stdout.strip()} {r.stderr.strip()[-300:]})")
    # (6) the fix round: one cause logged once an hour across processes, a
    # flood that cannot push an error out, the phone setting kept out, the
    # right machine named, no forged line
    print("  -- the fix round of phase 10")
    import concurrent.futures as _cf
    mark = lambda: ml.read_text(encoding="utf-8") if ml.is_file() else ""
    hook_line = "HOOK Claude Code's settings are not readable"
    (hm / ".claude").mkdir(exist_ok=True)
    (hm / ".claude" / "settings.json").write_text('{"hooks": {},}')    # a trailing comma
    wf = hm / ".aht" / "run" / "warned.json"
    wf.write_text(json.dumps({"old-key": time.time() - 7200, "ahead": time.time() + 99999}))
    n0 = mark().count(hook_line)
    many = ("import sys; sys.path.insert(0, sys.argv[1]); import aht\n"
            "aht.hook_installed(); aht.warn_once('backup-status', 'BACKUP many processes')\n")
    with _cf.ThreadPoolExecutor(16) as ex:
        rs = list(ex.map(lambda _i: subprocess.run([PY, "-c", many, str(HERE.parent)], env=de,
                                                   capture_output=True, text=True), range(40)))
        rs += list(ex.map(lambda _i: D("status", "--json"), range(4)))
    lg = mark()
    try:
        kept = json.loads(wf.read_text())
    except (OSError, ValueError):
        kept = {}
    ck(all(r.returncode == 0 for r in rs) and lg.count(hook_line) - n0 == 1
       and lg.count("BACKUP many processes") == 1
       and {"hook-settings", "backup-status"} <= set(kept) and not {"old-key", "ahead"} & set(kept),
       f"warn_once holds across processes: 40 processes and 4 `status --json` with a broken "
       f"settings.json log it once; ~/.aht/run/warned.json keeps the keys, old ones pruned "
       f"({lg.count(hook_line) - n0}, {lg.count('BACKUP many processes')}, {sorted(kept)}, "
       f"{[r.stderr[-200:] for r in rs if r.returncode][:1]})")
    kept["hook-settings"] = time.time() - 3601
    wf.write_text(json.dumps(kept))
    D("status", "--json")
    D("status", "--json")
    ck(mark().count(hook_line) - n0 == 2, "…an hour later it is logged once more")
    (hm / ".claude" / "settings.json").unlink()

    # a flood of one warning after an error: the error stays, the flood is one line
    plant(ml, 3000, "ERROR", "BACKUP failed for shop: OSError: [Errno 28] No space left on device")
    flood = [stamp(2999 - i * 5) for i in range(300)]
    with open(ml, "a", encoding="utf-8") as fh:
        for at in flood:
            fh.write(f"[{at}] [WARN ] HOOK the settings are not readable: "
                     f"JSONDecodeError: planted\n")
    since = flood[0][11:16] if flood[0][:10] == flood[-1][:10] else flood[0][:16]  # (midnight)
    d = DJ("logs", "--errors", "--hours", "1", "--json")
    ts = [e["text"] for e in d.get("entries") or []]
    hooks = [t for t in ts if "JSONDecodeError: planted" in t]
    ck(any(t.startswith("BACKUP failed for shop") for t in ts) and len(hooks) == 1
       and hooks[0].endswith(f"JSONDecodeError: planted (×300 since {since})"),
       f"logs --errors: 300 times the same warning are one line with a count, and the error "
       f"before them stays ({hooks}, {len(ts)} entries)")
    d = DJ("report-problem", "--hours", "1", "--out", str(base / "flood.txt"), "--json")
    txt = (base / "flood.txt").read_text() if (base / "flood.txt").is_file() else ""
    ck("] [ERROR] this machine: BACKUP failed for shop" in txt
       and txt.count("JSONDecodeError: planted") == 1 and "(×300 since " in txt,
       f"report-problem: the same ({d.get('errors')} warning(s) and error(s))")
    rq = subprocess.run([PY, LAUNCH, "_agent"], input=json.dumps({"op": "log-tail", "hours": 1}),
                        env=de, capture_output=True, text=True)
    try:
        far = json.loads(rq.stdout.split("@@AHT@@", 1)[1]).get("entries") or []
    except (IndexError, ValueError):
        far = []
    ck(any(e["text"].startswith("BACKUP failed for shop") for e in far)
       and sum("JSONDecodeError: planted" in e["text"] for e in far) == 1,
       f"log-tail (what another machine is sent): the same ({len(far)} entries)")

    # the phone setting stays out of the log and the report
    cfgf = hm / ".aht" / "config.json"
    cfg = json.loads(cfgf.read_text())
    cfg["notify_phone"] = "ntfy:http://ntfy.home.example/quiet-heron-5521"   # set by hand
    cfgf.write_text(json.dumps(cfg))
    r = D("notices", "--test", AHT_NOTIFY_LOG=str(base / "phone.log"))
    lg = mark()
    ck(r.returncode == 0 and "NOTICE not sent to the phone: the phone setting (notify_phone) "
       "is plain http" in lg and "ntfy.home.example" not in lg and "quiet-heron" not in lg,
       f"an http:// phone setting: the log names the setting, not its address ({lg[-300:]!r})")
    # what an older aht wrote, and a failure that names the server or the topic
    plant(ml, 40, "WARN", "NOTICE not sent to the phone: http://ntfy.home.example/quiet-heron-5521 "
          "is plain http, so the notices would cross the network unencrypted")
    plant(ml, 39, "WARN", "NOTICE to the phone failed: URLError: <urlopen error [Errno 8] "
          "ntfy.home.example: nodename nor servname provided> for topic quiet-heron-5521")
    DJ("report-problem", "--hours", "1", "--out", str(base / "phone.txt"))
    txt = (base / "phone.txt").read_text() if (base / "phone.txt").is_file() else ""
    ck(txt and "ntfy.home.example" not in txt and "quiet-heron" not in txt
       and "NOTICE not sent to the phone: [phone] is plain http" in txt
       and "[Errno 8] [phone]: nodename" in txt and "for topic [phone]" in txt,
       f"report-problem: the phone setting's address, server and topic read [phone] "
       f"({[l for l in txt.splitlines() if 'phone' in l][-3:]})")
    cfg["notify_phone"] = "imessage:+436601234567"
    cfgf.write_text(json.dumps(cfg))
    plant(ml, 38, "WARN", 'NOTICE to the phone failed: execution error: Messages got an error: '
          'Can’t get participant "+436601234567". (-1728)')
    if sys.platform == "darwin":
        # the iMessage route: osascript's own error names the number
        pbin = base / "phonebin"
        pbin.mkdir(exist_ok=True)
        (pbin / "osascript").write_text(
            '#!/bin/sh\necho "execution error: Messages got an error: Can’t get participant '
            '\\"$4\\". (-1728)" >&2\nexit 1\n')
        (pbin / "osascript").chmod(0o755)
        pe = dict(de, PATH=str(pbin) + os.pathsep + de["PATH"])
        pe.pop("AHT_NOTIFY_LOG", None)
        r = subprocess.run([PY, LAUNCH, "notices", "--test"], env=pe, capture_output=True, text=True)
        lg = mark()
        ck(r.returncode == 0 and "NOTICE to the phone failed: execution error: Messages got an "
           "error: Can’t get participant \"the phone setting\"" in lg
           and lg.count("+436601234567") == 1,
           f"iMessage that fails: the log names the setting, not the number "
           f"({[l for l in lg.splitlines() if 'to the phone failed' in l][-1:]})")
    DJ("report-problem", "--hours", "1", "--out", str(base / "phone2.txt"))
    txt = (base / "phone2.txt").read_text() if (base / "phone2.txt").is_file() else ""
    ck(txt and "436601234567" not in txt and 'participant "[phone]"' in txt,
       "report-problem: an iMessage number reads [phone]")
    cfg.pop("notify_phone")
    cfgf.write_text(json.dumps(cfg))

    # a machine set up whose home is at this one's path (two Macs, one account
    # name): this machine's paths read ~, whatever the hash seed of the run
    cfg = json.loads(cfgf.read_text())
    cfg["remotes"]["studio"] = {"ssh": "otto@studio.example", "home": str(hm) + "/"}
    cfg["remotes"]["studio2"] = {"ssh": "otto@studio2.example", "root": str(hm)}
    cfgf.write_text(json.dumps(cfg))
    plant(ml, 30, "WARN", f"MAC studio: not copied: {hm}/code/shop/b.py")
    bcfg = bh / ".aht" / "config.json"
    try:
        bc = json.loads(bcfg.read_text())
    except (OSError, ValueError):
        bc = {}
    bc["remotes"] = {"twin": {"ssh": "otto@twin.example", "home": str(bh)}}
    bcfg.parent.mkdir(parents=True, exist_ok=True)
    bcfg.write_text(json.dumps(bc))
    plant(bh / ".aht" / "aht.log", 30, "WARN", f"BOX twin: not copied: {bh}/code/x.py")
    seen_here, seen_far = set(), set()
    for seed in ("0", "1", "2", "3", "4", "5", "6", "7"):
        rf = base / f"seed-{seed}.json"
        DJ("report-problem", "--hours", "1", "--out", str(rf), PYTHONHASHSEED=seed)
        try:
            rep = json.loads(rf.read_text())
        except (OSError, ValueError):
            rep = {}
        seen_here |= {e["text"] for e in rep.get("problems") or []
                      if e["text"].startswith("MAC studio")}
        rq = subprocess.run([PY, LAUNCH, "_agent"], input=json.dumps({"op": "log-tail", "hours": 1}),
                            env=dict(de, HOME=str(bh), AHT_HOME=str(bh / ".aht"),
                                     PYTHONHASHSEED=seed), capture_output=True, text=True)
        try:
            far = json.loads(rq.stdout.split("@@AHT@@", 1)[1]).get("entries") or []
        except (IndexError, ValueError):
            far = []
        seen_far |= {e["text"] for e in far if e["text"].startswith("BOX twin")}
    ck(seen_here == {"MAC studio: not copied: ~/code/shop/b.py"}
       and seen_far == {"BOX twin: not copied: ~/code/x.py"},
       f"a machine whose home is at this one's path: this machine's paths read ~ under every "
       f"hash seed, here and in what the far end sends ({seen_here}, {seen_far})")
    cfg["remotes"].pop("studio")
    cfg["remotes"].pop("studio2")
    cfgf.write_text(json.dumps(cfg))
    bcfg.unlink()

    # no forged entry through a line break the log's readers split on
    now_s = time.strftime("%Y-%m-%d %H:%M:%S")
    for i, sep in enumerate((" ", " ", "\x85", "\r", "\x0b")):
        D("_log", "--source", "mac-app", "--", f"ok {i}{sep}[{now_s}] [ERROR] UNCAUGHT forged {i}")
    probe = ("import sys; sys.path.insert(0, sys.argv[1]); import aht\n"
             f"aht.warn('far said: ok\\u2028[{now_s}] [ERROR] UNCAUGHT forged w')\n"
             f"aht.error('UNCAUGHT Traceback (most recent call last):\\n  File \"x\", line 1\\n"
             f"ValueError: bad\\u2028[{now_s}] [ERROR] UNCAUGHT forged t')\n"
             f"aht.warn_once('forge', 'once: a\\x85[{now_s}] [ERROR] UNCAUGHT forged o')\n")
    subprocess.run([PY, "-c", probe, str(HERE.parent)], env=de, capture_output=True, text=True)
    d = DJ("logs", "--errors", "--hours", "1", "--json")
    ts = [e["text"] for e in d.get("entries") or []]
    r = D("logs", "--errors", "-n", "400")
    lg = mark()
    ck(not [t for t in ts if t.startswith("UNCAUGHT forged")]
       and all(f"APP mac-app: ok {i} ⏎ [{now_s}] [ERROR] UNCAUGHT forged {i}" in lg
               for i in range(5))
       and f"far said: ok ⏎ [{now_s}] [ERROR] UNCAUGHT forged w" in lg
       and f"\n  [{now_s}] [ERROR] UNCAUGHT forged t" in lg
       and not any(ln.split("] ", 2)[-1].startswith("UNCAUGHT forged")
                   for ln in r.stdout.splitlines()),
       f"a line break of any kind (U+2028, U+2029, U+0085, \\r, \\v) in an app's message, a far "
       f"end's answer or an error's message: one line, no forged entry "
       f"({[t for t in ts if 'forged' in t][:3]})")

    ck(not fx, f"the JSON keeps every key of the phase 10 samples ({fx})")

if os.name == "nt" or handover_name(sb) > 255:
    print("  SKIP diagnostics: its stand-ins need macOS or Linux and a short sandbox path")
else:
    phase10_suite()

done()
