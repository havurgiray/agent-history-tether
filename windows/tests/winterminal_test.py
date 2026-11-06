#!/usr/bin/env python3
"""Windows Terminal as aht's terminal, on any OS: the parts that decide what is
where and what goes where are plain functions (winterminal.py imports
anywhere; only its Win32 calls need Windows).  What it does on a real Windows
Terminal is in windows/tests/vm_terminal.py."""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "windows" / "src"))
sys.path.insert(0, str(ROOT))
import aht  # noqa: E402
import winterminal as W  # noqa: E402

failed = 0


def ck(name, ok, detail=""):
    global failed
    print(("  PASS " if ok else "  FAIL ") + name + (f" ({detail})" if detail and not ok else ""))
    failed += 0 if ok else 1


print("\n[command lines]")
ck("a plain Windows path keeps its backslashes",
   aht._windows_argv(r"claude --settings C:\Users\me\hooks.json") ==
   ["claude", "--settings", r"C:\Users\me\hooks.json"])
ck("a quoted program and a quoted folder with a space",
   aht._windows_argv(r'"C:\Program Files\x\claude.exe" --add-dir "C:\a b\c"') ==
   [r"C:\Program Files\x\claude.exe", "--add-dir", r"C:\a b\c"])
ck("backslashes before a quote halve; an odd one keeps the quote",
   aht._windows_argv(r'a "b\\" c\"d') == ["a", "b\\", 'c"d'])
ck("an empty quoted argument stays", aht._windows_argv('a "" b') == ["a", "", "b"])
was = aht._argv
aht._argv = aht._windows_argv
ck("the options a session keeps, read from a Windows command line",
   aht._claude_flags(r'"C:\x\claude.exe" --settings C:\Users\me\h.json --resume abc --model haiku') ==
   ["--settings", r"C:\Users\me\h.json", "--model", "haiku"])
aht._argv = was
ck("a folder loses its trailing backslash", W.folder_name("C:\\Users\\me\\") == "C:\\Users\\me")
ck("…but a drive's root keeps it", W.folder_name("C:\\") == "C:\\")
ck("a program's bare name", W.bare_command(r'"C:\x y\claude.exe" --resume 1') == "claude --resume 1")
ck("…without quotes", W.bare_command(r"C:\Windows\System32\cmd.exe /k") == "cmd /k")
ck("…and alone", W.bare_command("powershell") == "powershell")

print("\n[a stale session record]")
with tempfile.TemporaryDirectory() as td:
    d = Path(td) / "sessions"
    d.mkdir()
    made = 134384096768089058                   # as Claude Code writes it on Windows
    made_s = (made - W.FILETIME_1970) / 1e7
    (d / "4242.json").write_text(json.dumps({"pid": 4242, "sessionId": "s1", "cwd": "C:\\x",
                                             "procStart": str(made)}))
    alive, started = aht._pid_alive, aht._proc_started
    aht._pid_alive = lambda pid: True
    aht._proc_started = lambda pid: made_s
    ck("the process that wrote it: the session is open",
       [s["session"] for s in aht.running_sessions(home=Path(td))] == ["s1"])
    aht._proc_started = lambda pid: made_s + 3600
    ck("the same number on a newer process: it is not", aht.running_sessions(home=Path(td)) == [])
    aht._proc_started = lambda pid: None
    ck("no start time known: in doubt it stands", len(aht.running_sessions(home=Path(td))) == 1)
    aht._pid_alive, aht._proc_started = alive, started

print("\n[Windows Terminal's files, read only]")
with tempfile.TemporaryDirectory() as td:
    f = Path(td)
    ck("no file: no layouts", W.saved_layouts([f]) == [])
    (f / "state.json").write_text("not json")
    ck("a broken file: no layouts, no error", W.saved_layouts([f]) == [])
    layouts = [{"tabLayout": [{"action": "newTab", "tabTitle": "Paper", "tabColor": "#FF8000",
                               "sessionId": "{ABC-1}"},
                              {"action": "splitPane", "sessionId": "{def-2}"},
                              {"action": "focusPane"}]}]
    (f / "state.json").write_text(json.dumps({"persistedWindowLayouts": layouts}))
    ck("its windows", W.saved_layouts([f]) == layouts)
    ck("pane ids, lower case without braces", W.saved_pane_ids(layouts) == {"abc-1", "def-2"})
    (f / "settings.json").write_text('{\n // a comment\n "firstWindowPreference": '
                                     '"persistedWindowLayout",\n "profiles": {"list": ['
                                     '{"name": "Ubuntu"}, {"name": "Dev Box"}]}\n}')
    ck("the setting is read from a file with comments", W.saves_windows([f]) is True)
    ck("profile names", W.profile_names([f]) == {"ubuntu", "dev box"})
    (f / "settings.json").write_text("{}")
    ck("the setting off", W.saves_windows([f]) is False)

print("\n[titles]")
for name, want in (("Paper", "Paper"), ("Administrator: Paper", "Paper"), ("Windows PowerShell", ""),
                   ("Administrator: Windows PowerShell", ""), ("✳ Claude Code", ""),
                   ("⠐ fixing the login", ""), (r"C:\WINDOWS\system32\cmd.exe", ""), ("", ""),
                   ("Dev Box", "")):
    ck(f"{name!r} -> {want!r}", W.own_title(name, {"dev box"}) == want)

print("\n[what is where]")
ck("a tab shows its pane's title",
   W.place(["a", "b"], {"a": "One", "b": "Two"}, ["One", "Two"]) == {"a": 0, "b": 1})
ck("a renamed tab takes the pane left over",
   W.place(["a", "b"], {"a": "✳ Claude Code", "b": "Two"}, ["Paper", "Two"]) == {"a": 0, "b": 1})
ck("the other pane of a split joins the pane before it (active one first in the tab)",
   W.place(["a", "b", "c"], {"a": "One", "b": "x", "c": "Three"}, ["One", "Three"]) ==
   {"a": 0, "b": 0, "c": 1})
ck("…and the first pane of a split whose second is active",
   W.place(["a", "b", "c"], {"a": "x", "b": "Two", "c": "Three"}, ["Two", "Three"]) ==
   {"a": 0, "b": 0, "c": 1})
ck("tabs sharing a program's title keep their order (the first has a split, its other pane active)",
   W.place(["a", "b", "c", "d"], {"a": "✳ CC", "b": "PS", "c": "✳ CC", "d": "Plain"},
           ["PS", "✳ CC", "Plain"]) == {"a": 0, "b": 0, "c": 1, "d": 2})
ck("a named first tab with a split, then one sharing a title",
   W.place(["a", "b", "c", "d"], {"a": "✳ CC", "b": "PS", "c": "✳ CC", "d": "Plain"},
           ["Paper", "✳ CC", "Plain"]) == {"a": 0, "b": 0, "c": 1, "d": 2})
ck("the Settings tab has no pane",
   W.place(["a", "b"], {"a": "One", "b": "Two"}, ["One", "Settings", "Two"]) == {"a": 0, "b": 2})
ck("no tabs known: all in the first", W.place(["a", "b"], {}, []) == {"a": 0, "b": 0})
ck("twenty panes in twenty tabs take no time",
   len(set(W.place([str(i) for i in range(20)], {str(i): "T" for i in range(20)}, ["T"] * 20).values())) == 20)
ck("two tabs with one title, oldest pane first",
   W.place(["a", "b"], {"a": "PS", "b": "PS"}, ["PS", "PS"]) == {"a": 0, "b": 1})
panes = {"p3": {"pid": 3, "born": 30}, "p1": {"pid": 1, "born": 10}, "p2": {"pid": 2, "born": 20},
         "p4": {"pid": 4, "born": 5}}
info = {"1": {"title": "✳ Claude Code", "owner": 100}, "2": {"title": "Plain", "owner": 100},
        "3": {"title": "x", "owner": 100}, "4": {"title": "Other", "owner": 200}}
wins = [{"hwnd": 100, "tabs": ["Paper", "Plain"]}, {"hwnd": 200, "tabs": ["Other"]}]
rows = W.arrange(panes, info, wins, layouts)
ck("windows number by their oldest pane, whichever is in front",
   rows["p4"]["window"] == 1 and rows["p1"]["window"] == 2)
ck("tab and pane numbers", (rows["p1"]["tab"], rows["p1"]["pane"]) == (1, 1) and
   (rows["p2"]["tab"], rows["p2"]["pane"]) == (2, 1) and (rows["p3"]["tab"], rows["p3"]["pane"]) == (2, 2))
ck("a named tab's colour comes from the saved layout",
   rows["p1"]["title"] == "Paper" and rows["p1"]["color"] == "#FF8000")
ck("every row names its pane", all(rows[k]["pane_id"] == k for k in rows))
ck("a window UI Automation did not see keeps its panes",
   W.arrange({"a": {"pid": 9, "born": 1}}, {}, [], [])["a"]["tab"] == 1)

print("\n[what goes where]")
sess = {"agent": "claude", "session": "s1", "cwd": r"C:\My Work", "args": ["--model", "haiku"]}
ck("PowerShell",
   W.resume_line(sess, "powershell") ==
   r"Set-Location -LiteralPath 'C:\My Work'; claude --model haiku --resume s1")
ck("cmd", W.resume_line(sess, "cmd") == r'cd /d "C:\My Work" && claude --model haiku --resume s1')
ck("Git Bash", W.resume_line(sess, "bash") == "cd 'C:\\My Work' && claude --model haiku --resume s1")
ck("a quote in a folder, PowerShell",
   "'C:\\it''s'" in W.resume_line(dict(sess, cwd="C:\\it's"), "pwsh"))
ck("Kimi", W.resume_line({"agent": "kimi", "cwd": "C:\\x"}, "pwsh").endswith("kimi -c"))
ck("a plain tab: nothing to type", W.resume_line({"cwd": "C:\\x"}, "pwsh") == "")
ck("a shell aht does not know: said so, not guessed", W.resume_line(sess, "nu") is None)
a = {"pane_id": "AA", "session": "1"}
b = {"pane_id": "bb", "session": "2"}
c = {"session": "3"}
into, fresh = W.assign({"windows": [[[a], [b, c]]]}, {"aa": {"busy": []}, "bb": {"busy": ["node.exe"]}})
ck("a pane that came back and is idle takes its session", into == [("aa", a)])
ck("a busy pane is never typed into: its session opens anew", fresh == [[[b, c]]])
ck("a window with nothing to open is no window",
   W.assign({"windows": [[[a]]]}, {"aa": {"busy": []}})[1] == [])
cmd = W.wt_command([[{"title": "A;B", "color": "#ff8000", "cwd": r"C:\x", "profile": "Dev"},
                     {"cwd": r"C:\y"}], [{"cwd": "C:\\z"}]], "w1")
ck("one command for a window: tab, split, tab",
   cmd == ["wt.exe", "-w", "w1", "new-tab", "-p", "Dev", "--title", "A\;B",
           "--suppressApplicationTitle", "--tabColor", "#ff8000", "-d", r"C:\x",
           ";", "split-pane", "-V", "-d", r"C:\y", ";", "new-tab", "-d", "C:\\z"])
ck("no pane is ever started with a session in its command", "claude" not in " ".join(cmd))

print("\n[waiting for panes]")
looks = iter([{"a"}, {"a"}, {"a"}, {"a"}, {"a", "b"}, {"a", "b", "c"}])
t = {"now": 0.0}


def tick(s):
    t["now"] += s


got = W.wait_for(lambda: next(looks), lambda now: {"a", "b", "c"} <= now, sleep=tick,
                 clock=lambda: t["now"])
ck("no change for a while is not the end when it knows what to expect", got == {"a", "b", "c"})
got = W.wait_for(lambda: {"a"}, lambda now: "z" in now, limit=3, sleep=tick, clock=lambda: t["now"])
ck("a pane that never comes: it gives up", got == {"a"})
looks = iter([set(), {"a"}, {"a", "b"}, {"a", "b"}, {"a", "b"}, {"a", "b"}, {"x"}])
ck("nothing to expect: until the panes stop changing",
   W.wait_for(lambda: next(looks), sleep=tick, clock=lambda: t["now"]) == {"a", "b"})

print("\n[the terminal]")
ck("Windows Terminal is a Terminal", issubclass(W.WindowsTerminal, aht.Terminal))
ck("no terminal here, by default, opens nothing", aht.Terminal().running() is False)
print("\nWINTERMINAL RESULT: " + ("ALL PASS" if not failed else f"{failed} FAILED"))
sys.exit(1 if failed else 0)
