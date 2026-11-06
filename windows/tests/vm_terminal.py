#!/usr/bin/env python3
"""Restore Workspace on a real Windows Terminal, as a normal user, with real
Claude Code sessions.  Run it in the desktop session of a test machine (a
scheduled task with /IT), never on a machine in use: it closes every Windows
Terminal window.  It puts Windows Terminal's files back afterwards.

    vm_terminal.py <folder Claude trusts> <folder for the results>

Each session costs one very short prompt on the cheapest model.
"""
import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(HERE.parent.parent))
import win_fcntl  # noqa: E402
sys.modules.setdefault("fcntl", win_fcntl)
import winterminal as W  # noqa: E402
import winlayer  # noqa: E402

DEMO, OUT = Path(sys.argv[1]), Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)
HOME = Path.home()
TEMP = Path(tempfile.mkdtemp(prefix="aht-vmterm-"))
ENV = dict(os.environ, AHT_HOME=str(TEMP / "aht"))
ST = next(d for d in W.state_folders() if (d / "settings.json").is_file())
SAVE = TEMP / "wt-files"
NOWIN = W.CREATE_NO_WINDOW
RECORDS = HOME / ".claude" / "sessions"
u = ctypes.WinDLL("user32")
failed = 0
out = open(OUT / "vm_terminal.txt", "w", encoding="utf-8", buffering=1)


def say(line):
    out.write(line + "\n")


def ck(name, ok, detail=""):
    global failed
    say(("  PASS " if ok else "  FAIL ") + name + (f" ({str(detail)[:400]})" if not ok and detail != "" else ""))
    failed += 0 if ok else 1


def shot(name):
    ps = ("Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
          "$b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds; "
          "$m=New-Object System.Drawing.Bitmap $b.Width,$b.Height; "
          "$g=[System.Drawing.Graphics]::FromImage($m); "
          "$g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size); "
          f"$m.Save('{OUT / (name + '.png')}')")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], creationflags=NOWIN)


def cli(*args, timeout=180):
    r = subprocess.run([sys.executable, str(SRC / "aht_main.py"), *args], env=ENV, text=True,
                       capture_output=True, timeout=timeout, encoding="utf-8", creationflags=NOWIN)
    return r.stdout or "", r.stderr or ""


def js(*args, timeout=180):
    o, e = cli(*args, "--json", timeout=timeout)
    try:
        return json.loads(o)
    except ValueError:
        return {"bad": (o + e)[-500:]}


def type_keys(pid, text, gap=0.0):
    return W._ask_helper({"type": [{"pid": pid, "text": text, "gap": gap}]})["typed"].get(str(pid), {})


def sessions_now():
    """{session: Claude pid} for the Claude processes alive now."""
    alive = {p for p, _q, e in W.process_table() if e.lower() == "claude.exe"}
    got = {}
    for f in RECORDS.glob("*.json"):
        try:
            j = json.loads(f.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        if int(j.get("pid") or 0) in alive:
            got[j.get("sessionId")] = int(j["pid"])
    return got


def wait_sessions(ids, sec=40):
    end = time.time() + sec
    while time.time() < end:
        now = sessions_now()
        if all(i in now for i in ids):
            return now
        time.sleep(0.5)
    return sessions_now()


def hidden():
    found, buf = [], ctypes.create_unicode_buffer(256)
    proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def cb(h, _):
        u.GetClassNameW(ctypes.c_void_p(h), buf, 256)
        if buf.value.startswith("Windows Terminal"):
            found.append(h)
        return True
    u.EnumWindows(proc(cb), None)
    return found


def shutdown_message():
    """What Windows sends at a restart; real ones are checked by hand."""
    for h in hidden():
        u.PostMessageW(ctypes.c_void_p(h), 0x0016, ctypes.c_void_p(1), None)
    end = time.time() + 15
    while time.time() < end and any(e.lower() == "windowsterminal.exe" for _p, _q, e in W.process_table()):
        time.sleep(0.2)


def kill_all():
    for pid, _q, e in W.process_table():
        if e.lower() in ("windowsterminal.exe", "claude.exe"):
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, creationflags=NOWIN)
    time.sleep(2)


def end_session(pid):
    type_keys(pid, "/exit", 0.03)
    time.sleep(0.6)
    type_keys(pid, "\r")
    end = time.time() + 12
    while time.time() < end:
        if pid not in {p for p, _q, e in W.process_table() if e.lower() == "claude.exe"}:
            return True
        time.sleep(0.3)
    return False


def first_session():
    r = subprocess.run(["claude", "-p", "Reply with the single word ok", "--model", "haiku",
                        "--output-format", "json"], cwd=DEMO, capture_output=True, text=True,
                       timeout=120, creationflags=NOWIN, stdin=subprocess.DEVNULL)
    return json.loads(r.stdout)["session_id"]


def saved_commands():
    return [a.get("commandline") or "" for w in W.saved_layouts([ST]) for a in w.get("tabLayout", [])]


def main():
    SAVE.mkdir()
    for p in ST.iterdir():
        shutil.copy2(p, SAVE / p.name)
    cfg = json.loads((ST / "settings.json").read_text(encoding="utf-8-sig"))
    cfg["firstWindowPreference"] = "persistedWindowLayout"
    (ST / "settings.json").write_text(json.dumps(cfg, indent=4), encoding="utf-8")
    ck("this test has no administrator rights", not ctypes.windll.shell32.IsUserAnAdmin())
    s1, s2 = first_session(), first_session()

    say("\n[saving a real layout]")
    subprocess.Popen(f'wt.exe -w t1 new-tab --title Paper --suppressApplicationTitle --tabColor "#ff8000" '
                     f'-d "{DEMO}" ; new-tab -d "{DEMO}" ; split-pane -V -d C:\\ ; '
                     f'new-tab --title Plain -d C:\\')
    time.sleep(7)
    subprocess.Popen('wt.exe -w t2 new-tab --title Notes -d C:\\Windows')
    W.wait_for(lambda: W.live_panes().keys(), lambda now: len(now) >= 5)
    time.sleep(2)
    panes = sorted(W.live_panes().items(), key=lambda kv: kv[1]["born"])
    ck("five panes, each found by its id", len(panes) == 5, panes)
    p_paper, p_second, p_split, p_plain, p_notes = [k for k, _v in panes]
    live = dict(panes)
    type_keys(live[p_paper]["pid"], f"claude --model haiku --resume {s1}\r")
    type_keys(live[p_second]["pid"], f"claude --resume {s2}\r")
    now = wait_sessions([s1, s2])
    ck("two sessions started by typing", s1 in now and s2 in now, now)
    time.sleep(3)
    wins = W.uia_windows()
    ck("UI Automation sees both windows and their tabs",
       sorted(len(x.get("tabs") or []) for x in wins) == [1, 3], wins)
    res = js("workspace", "--save")
    ck("saved", res.get("saved"), res)
    w = json.loads(Path(res["saved"]).read_text(encoding="utf-8"))
    (OUT / "layout.json").write_text(json.dumps(w, indent=1), encoding="utf-8")
    rows = {e.get("pane_id"): e for e in w["tabs"]}
    ck("every pane is in it", set(rows) == set(live), sorted(rows))
    ck("two windows", len({e["window"] for e in w["tabs"]}) == 2)
    # which of two neighbouring tabs holds a split beside a named tab cannot be
    # told from outside; the count of tabs can
    ck("three tabs in its window, one of them with a split",
       len({e["tab"] for e in w["tabs"] if e["window"] == rows[p_paper]["window"]}) == 3 and
       rows[p_plain]["pane"] == 1 and rows[p_split]["tab"] <= 2,
       [(e["window"], e["tab"], e["pane"], e["title"]) for e in w["tabs"]])
    ck("the session in its pane", rows[p_paper].get("session") == s1 and rows[p_second].get("session") == s2,
       rows[p_paper])
    ck("the conversation's folder", rows[p_paper].get("cwd") == str(DEMO), rows[p_paper].get("cwd"))
    ck("a named tab with a session keeps its name", rows[p_paper].get("title") == "Paper", rows[p_paper])
    ck("its options", rows[p_paper].get("args") == ["--model", "haiku"], rows[p_paper].get("args"))
    ck("plain tabs keep their titles", rows[p_plain].get("title") == "Plain" and rows[p_notes].get("title") == "Notes",
       (rows[p_plain].get("title"), rows[p_notes].get("title")))
    lid = Path(res["saved"]).stem
    dry = js("workspace", "--restore", lid)
    ck("with everything open there is nothing to open", "everything in it is open already" in dry.get("blockers", []), dry)
    auto = js("workspace", "--save", "--auto")
    ck("the tray's minute: saved at most once in its time", "saved" in auto, auto)
    st = js("status")
    ck("the window is told the terminal", st.get("terminal") == "Windows Terminal", st.get("terminal"))
    step = next((x for x in js("getting-started").get("steps", []) if x.get("id") == "terminal_windows"), None)
    ck("Getting started says Windows Terminal brings its windows back", step and step.get("ok") is True, step)
    shot("1-open")

    say("\n[a restart: Windows Terminal closed, Open Them]")
    shutdown_message()
    end = time.time() + 20                      # they end a moment after their terminal
    while time.time() < end and sessions_now():
        time.sleep(0.3)
    ck("Claude ended with the restart", not sessions_now(), sessions_now())
    t0 = time.time()
    res = js("workspace", "--restore", lid, "--apply")
    ck("restored", res.get("applied") is True, res)
    now = wait_sessions([s1, s2])
    ck("both sessions are back", s1 in now and s2 in now, now)
    say(f"  ({time.time() - t0:.1f} s from Open Them)")
    back = W.live_panes()
    ck("in their own panes, with no pane more", set(back) == set(live), sorted(back))
    if s1 in now:
        ck("the session has its options again", "--model haiku" in W.process_cmdline(now[s1]),
           W.process_cmdline(now[s1]))
        ck("the first session's pane", W.process_pane(now[s1]) == p_paper)
    time.sleep(3)
    shot("2-restored")
    res = js("workspace", "--restore", lid, "--apply")
    ck("a second click opens nothing", res.get("applied") is False and res.get("blockers"), res)
    ck("…and no pane more", set(W.live_panes()) == set(live))

    say("\n[sessions ended, Windows Terminal still open]")
    now = sessions_now()
    ck("/exit typed into each session", all(end_session(now[s]) for s in (s1, s2) if s in now))
    (TEMP / "aht" / "run" / "workspace-opened.json").unlink(missing_ok=True)
    res = js("workspace", "--restore", lid, "--apply")
    ck("restored", res.get("applied") is True, res)
    now = wait_sessions([s1, s2])
    ck("both sessions are back, in the panes open now", s1 in now and s2 in now, now)
    ck("no pane more", set(W.live_panes()) == set(live))

    say("\n[Go to Tab, Restart in Its Tab]")
    now = sessions_now()
    got = js("goto", str(now[s2]))
    ck("Go to Tab", got.get("ok") is True, got)
    time.sleep(1)
    shot("3-go-to-tab")
    old = now[s2]
    res = js("checkup", "--restart", str(old), "--apply")
    ck("restarted", res.get("applied") is True, res)
    end = time.time() + 30
    while time.time() < end and sessions_now().get(s2) in (None, old):
        time.sleep(0.5)
    fresh = sessions_now().get(s2)
    ck("the session runs in a new process", fresh not in (None, old), sessions_now())
    if fresh:
        ck("in the same pane", W.process_pane(fresh) == p_second, W.process_pane(fresh))

    say("\n[nothing stays behind in a pane]")
    now = sessions_now()
    for s in (s1, s2):
        if s in now:
            end_session(now[s])
    time.sleep(1)
    shutdown_message()
    ck("what Windows Terminal saved runs no session",
       not any("claude" in c.lower() for c in saved_commands()), saved_commands())
    subprocess.Popen("wt.exe")
    W.wait_for(lambda: W.live_panes().keys())
    time.sleep(6)
    ck("it starts again without bringing a session back by itself", not sessions_now(), sessions_now())
    shutdown_message()

    say("\n[Windows Terminal's file lost: from aht's layout alone]")
    for p in ST.glob("buffer_*.txt"):
        p.unlink()
    shutil.copy2(SAVE / "state.json", ST / "state.json")
    (TEMP / "aht" / "run" / "workspace-opened.json").unlink(missing_ok=True)
    res = js("workspace", "--restore", lid, "--apply")
    ck("restored", res.get("applied") is True, res)
    now = wait_sessions([s1, s2])
    ck("both sessions are back, in new panes", s1 in now and s2 in now, now)
    time.sleep(3)
    shot("4-from-layout")
    res2 = js("workspace", "--save")
    w2 = json.loads(Path(res2["saved"]).read_text(encoding="utf-8")) if res2.get("saved") else {"tabs": []}
    titles = sorted(e.get("title") or "" for e in w2["tabs"])
    ck("the titled tabs are there", {"Notes", "Paper", "Plain"} <= set(titles), titles)
    ck("two windows again", len({e["window"] for e in w2["tabs"]}) == 2,
       [(e["window"], e["tab"], e["title"]) for e in w2["tabs"]])
    shutdown_message()
    ck("these panes hold no session either", not any("claude" in c.lower() for c in saved_commands()),
       saved_commands())


try:
    main()
except Exception:
    ck("ran to the end", False, traceback.format_exc()[-900:])
finally:
    kill_all()
    for p in ST.glob("buffer_*.txt"):
        p.unlink()
    for name in ("settings.json", "state.json"):    # elevated-state.json: for administrators
        if (SAVE / name).is_file():
            shutil.copy2(SAVE / name, ST / name)
    shutil.rmtree(TEMP, ignore_errors=True)
    say("\nVM TERMINAL RESULT: " + ("ALL PASS" if not failed else f"{failed} FAILED"))
    out.close()
