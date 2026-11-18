#!/usr/bin/env python3
"""[22b] a new Claude Code, and the open sessions moved onto it: how each
kind of install is updated (Homebrew cask or formula, winget, npm, Claude
Code's own installer); restarting the sessions on an older version, idle
ones now and working ones once their task is over, never the one asking, a
background one or a tab that parked its conversation; with winget every
session ends first, the update runs, and each comes back in its tab."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)

sys.path.insert(0, str(HERE.parent))
import aht as core

print("\n[22b] update Claude Code and restart the sessions on it")
H = str(Path.home())
for path, how, cmd_tail, running in (
        ("/opt/homebrew/Caskroom/claude-code@latest/2.1.325/claude", "Homebrew",
         ["upgrade", "--cask", "claude-code@latest"], True),
        ("/opt/homebrew/Caskroom/claude-code/2.1.300/claude", "Homebrew",
         ["upgrade", "--cask", "claude-code"], True),
        ("/usr/local/Cellar/claude-code/2.1.3/bin/claude", "Homebrew", ["upgrade", "claude-code"], True),
        ("C:\\Users\\me\\AppData\\Local\\Microsoft\\WinGet\\Packages\\"
         "Anthropic.ClaudeCode_Microsoft.Winget.Source_8wekyb3d8bbwe\\claude.exe", "winget",
         ["upgrade", "--id", "Anthropic.ClaudeCode"], False),
        (H + "/.npm-global/lib/node_modules/@anthropic-ai/claude-code/cli.js", "npm",
         ["install", "-g", "@anthropic-ai/claude-code@latest"], True),
        (H + "/.local/share/claude/versions/2.1.325", "its own installer", ["update"], True)):
    core.find_claude = lambda *a, _p=path, **k: _p
    u = core.claude_updater()
    got = u["command"] or []
    ck(u["how"] == how and got[1:1 + len(cmd_tail)] == cmd_tail and u["while_running"] == running,
       f"{how}: {' '.join(got[1:4])} …, {'while sessions run' if running else 'once they ended'}")
core.find_claude = lambda *a, **k: "/usr/bin/claude"
u = core.claude_updater()
ck(u["command"] is None and "package manager" in u["why"],
   f"a system package: aht says how, and runs nothing ({u['why']})")
core.find_claude = lambda *a, **k: "/srv/odd/place/claude"
u = core.claude_updater()
ck(u["command"] is None and "does not know" in u["why"], "an install aht does not know: nothing runs")

# ---- the sessions, as stand-ins -------------------------------------------- #
records, rows = {}, []


def row(pid, name, status="idle", version="2.1.300", tab=True, **rec):
    records[pid] = dict({"pid": pid, "sessionId": f"s{pid}", "status": status, "version": version,
                         "kind": "interactive", "statusUpdatedAt": 0}, **rec)
    rows.append({"pid": pid, "session": f"s{pid}", "project": f"/w/{name}", "name": name,
                 "status": status, "issues": ["older"] if version != "2.1.325" else [],
                 "tty": f"tty{pid}" if tab else None, "in_terminal": tab, "version": version})


row(1, "idle-old")
row(2, "busy-old", status="busy")
row(3, "current", version="2.1.325")
row(4, "me")
row(5, "no-tab", tab=False)
row(6, "parked", parkedJobId="j9")
records[7] = {"pid": 7, "kind": "bg", "jobId": "j9", "status": "busy"}
polls = {2: ["busy", "busy", "idle"]}
acts = []


class Term:
    name = "Stand-in"

    def restart_line(self, r, flags):
        return f"claude --resume s{r['pid']}"

    def type_line(self, key, line):
        acts.append(("typed", key, line))
        return True


def settled(pid):
    seq = polls.get(pid)
    return seq.pop(0) if seq else ("gone" if ("closed", pid) in acts else "idle")


def restart_session(pid, apply=False):
    acts.append(("restarted", pid))
    return {"applied": True, "blockers": []}


def close_session(pid, apply=False):
    acts.append(("closed", pid))
    return {"applied": True, "blockers": []}


stand = {"session_checkup": lambda: [dict(r) for r in rows],
         "running_sessions": lambda: [{"pid": p} for p in records],
         "_session_record": lambda pid: records.get(pid, {}),
         "_settled": settled, "restart_session": restart_session, "close_session": close_session,
         "_my_ancestors": lambda: {4}, "terminal": lambda: Term(),
         "installed_claude_version": lambda: "2.1.325", "_cmdline": lambda pid: "claude",
         "notify_user": lambda *a, **k: None}
kept = {k: getattr(core, k) for k in stand}
sleep_was = core.time.sleep
for k, v in stand.items():
    setattr(core, k, v)
core.time.sleep = lambda s: None
try:
    plan = core.restart_older(apply=False)
    why = {x["session"]: x["why"] for x in plan["left_out"]}
    ck(plan["now"] == ["idle-old"] and plan["after"] == ["busy-old"] and "current" not in str(plan)
       and "asking" in why.get("me", "") and "no tab" not in why.get("no-tab", "x")
       and "not in a tab" in why.get("no-tab", "") and "background" in why.get("parked", ""),
       f"restart, dry run: the old idle one now, the busy one later; the current one, the one "
       f"asking, one in no tab and a tab that parked its conversation are left ({plan})")
    every = core.restart_older(apply=False, every=True)
    ck("current" in every["now"] + every["after"] and "idle-old" in every["now"]
       and {x["session"] for x in every["left_out"]} == set(why),
       f"restart, every session (the corner's Restart Workspace): the current one too, the "
       f"same ones left ({every})")
    got = core.restart_older(apply=True)
    ck(got["restarted"] == ["idle-old", "busy-old"] and [d for d in acts if d[0] == "restarted"]
       == [("restarted", 1), ("restarted", 2)] and not polls[2],
       f"…acts: the idle one at once, the busy one once it was idle ({got['restarted']})")

    # the update: Homebrew, while the sessions run, then the restarts
    acts.clear()
    polls[2] = ["busy", "idle"]
    marker = Path(os.path.realpath(sb)) / "updated"
    up = {"how": "Homebrew", "why": "", "path": "x", "while_running": True,
          "command": [sys.executable, "-c", f"open({str(marker)!r}, 'w').write('ran')"]}
    core.claude_updater = lambda: dict(up)
    d = core.update_claude(apply=False)
    ck(not d["applied"] and not marker.exists() and d["restart"]["now"] == ["idle-old"],
       f"update, dry run: what it would run, and which sessions follow ({d['command'][:1]}, "
       f"{d['restart']['now']})")
    d = core.update_claude(apply=True)
    ck(marker.exists() and d["restart"]["restarted"] == ["idle-old", "busy-old"]
       and acts[0] == ("restarted", 1),
       f"…with Homebrew: the update runs, then the old sessions restart ({d['restart']['restarted']})")

    # winget: every session in a tab ends first, the update, then each comes back
    marker.unlink()
    acts.clear()
    polls[2] = ["busy", "idle"]
    up.update(how="winget", while_running=False)
    d = core.update_claude(apply=False)
    ck(d["blockers"] and "parked" in d["blockers"][0] and "end them first" in d["blockers"][0]
       and "the session asking" in d["blockers"][0],
       f"winget: sessions aht cannot end and resume, the one asking among them, stop it, and it "
       f"says which ({d['blockers']})")
    # from the tray or a terminal of its own: no session asks
    rows[:] = [r for r in rows if r["name"] not in ("no-tab", "parked", "me")]
    d = core.update_claude(apply=False, wait=False)
    ck(d["blockers"] and "busy-old" in d["blockers"][0],
       f"…a working session and no waiting: nothing happens ({d['blockers']})")
    order = []
    up["command"] = [sys.executable, "-c", f"open({str(marker)!r}, 'w').write('ran')"]
    d = core.update_claude(apply=True)
    typed = [x[1] for x in acts if x[0] == "typed"]
    closed = [x[1] for x in acts if x[0] == "closed"]
    ck(marker.exists() and sorted(closed) == [1, 2, 3] and sorted(typed) == ["tty1", "tty2", "tty3"]
       and acts.index(("closed", 2)) < acts.index(next(x for x in acts if x[0] == "typed")),
       f"…winget: every session ended (the busy one once idle), updated, each typed back in its tab "
       f"({closed}, {typed})")

    # a session that works past the wait: no update, those ended come back
    marker.unlink()
    acts.clear()
    polls[2] = ["busy"] * 50
    core.RESTART_WAIT_HOURS = 0
    d = core.update_claude(apply=True)
    ck(not marker.exists() and any("is still working, so nothing was updated" in w for w in d["warnings"])
       and ("closed", 2) not in acts and sorted(x[1] for x in acts if x[0] == "typed")
       == ["tty1", "tty3"],
       f"…one still works: nothing updated, none ended mid-task, those ended are back "
       f"({d['warnings']})")
finally:
    for k, v in kept.items():
        setattr(core, k, v)
    core.time.sleep = sleep_was

r = run("update", "--claude", "--json", extra_env={"AHT_CLAUDE": "/srv/odd/place/claude"})
d = json.loads(r.stdout or "{}")
ck(r.returncode == 1 and d.get("blockers") and not d.get("applied"),
   f"aht update --claude: an install it does not know is said, nothing runs ({d.get('blockers')})")
r = run("checkup", "--restart-older", "--json")
d = json.loads(r.stdout or "{}")
ck(r.returncode == 0 and d.get("applied") is False and d.get("now") == [],
   f"aht checkup --restart-older: a dry run with no open session ({ {k: d.get(k) for k in ('now', 'after')} })")
done()
