#!/usr/bin/env python3
"""
The session corner on Windows: a small list of the open Claude sessions in a
corner of the screen, as the Mac app has it (macos/tray.swift, CornerModel and
CornerPanel): working (blue), waiting for you (orange) or done (green), with
how long it has been so, under the name the Claude app shows.  A click brings
the session's Windows Terminal tab to the front.  A right-click offers Go to
Tab, Branch… (a branch of the session in a new tab) and Send to <machine>…;
on a session handed over to another machine, Open Session and Take Back….
Every right-click, also one beside the sessions, offers Save Workspace Now,
Restore Workspace… and Restart Workspace….

`Model` is plain Python and runs anywhere (windows/tests/wincorner_test.py):
it reads Claude Code's own records of its sessions (<claude home>/sessions/
<pid>.json) every second and a half, and a session's title from the end of its
conversation file.  `Corner` is the window: Win32 through ctypes, run by the
tray (aht_tray.py) on its own thread, drawn with GDI, never activated by a
click, so the window you type in keeps the keyboard.
"""
import ctypes
import json
import ntpath
import os
import threading
import time
from pathlib import Path

import aht

WORKING = ("busy", "shell")
STATE_FILE = "corner.json"          # in aht's run folder, as on the Mac
PLACE_FILE = "corner-place.json"    # where you put the list, its width and length


def age(s: float) -> str:
    return ("now" if s < 60 else f"{int(s // 60)}m" if s < 3600 else
            f"{int(s // 3600)}h" if s < 86400 else f"{int(s // 86400)}d")


def _last_of(data: bytes, kind: str, field: str):
    """The `field` of the last line of type `kind` in a piece of a JSONL file."""
    mark = b'"' + kind.encode() + b'"'
    upper = len(data)
    for _ in range(20):
        at = data.rfind(mark, 0, upper)
        if at < 0:
            return None
        start = data.rfind(b"\n", 0, at) + 1
        end = data.find(b"\n", at)
        end = len(data) if end < 0 else end
        try:
            j = json.loads(data[start:end])
        except ValueError:
            j = None
        if isinstance(j, dict) and j.get("type") == kind and isinstance(j.get(field), str) \
                and j[field]:
            return j[field]
        upper = start
    return None


class Row:
    """One line of the list: a session open here (kind "here") or one handed
    over to another machine (kind "away")."""
    __slots__ = ("id", "pid", "name", "project", "state", "age", "recent", "kind", "machine",
                 "can_open", "status", "transfer")

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))

    def __eq__(self, other):
        return isinstance(other, Row) and all(getattr(self, k) == getattr(other, k)
                                              for k in self.__slots__)

    def __repr__(self):
        return f"Row({self.name!r}, {self.state}, {self.age})"


class Model:
    """The sessions, as the corner lists them.  A session that goes from
    working to idle is "done" until you click it or it works again; the marks
    are kept in a file, so they outlast the tray restarting."""

    def __init__(self, claude_home, run_dir, records=None, clock=time.time, moving=None):
        self.moving = moving or aht.transfers      # handovers and take-backs running now
        self.away_stale = False         # one ended: the tray lists the handed-over ones again
        self.moved = set()
        self.sessions = Path(claude_home) / "sessions"
        self.projects = Path(claude_home) / "projects"
        self.state_file = Path(run_dir) / STATE_FILE
        self.records = records or self._records
        self.clock = clock
        self.rows = []
        self.away = []              # aht.corner_away(), as the tray last asked
        self.machines = []          # the machines set up here, for Send to
        self.note = None            # why a click went nowhere, for a few seconds
        self.note_until = 0.0
        self.last, self.done, self.run_since = {}, {}, {}
        self.by_pid, self.titles = {}, {}
        try:
            j = json.loads(self.state_file.read_text(encoding="utf-8"))
            self.last = {k: v for k, v in (j.get("last") or {}).items() if isinstance(v, str)}
            self.done = {k: float(v) for k, v in (j.get("done") or {}).items()}
        except (OSError, ValueError, TypeError, AttributeError):
            pass

    def _records(self):
        """[(pid, record or None)] for the records whose process runs: None
        when it was caught mid-write."""
        out = []
        try:
            files = list(self.sessions.glob("*.json"))
        except OSError:
            return out
        for f in files:
            try:
                pid = int(f.stem)
            except ValueError:
                continue
            try:
                rec = json.loads(f.read_text(encoding="utf-8-sig"))
                rec = rec if isinstance(rec, dict) else None
            except (OSError, ValueError):
                rec = None
            if aht.session_record_live(pid, rec or {}):
                out.append((pid, rec))
        return out

    def _track(self, key, st, at, now):
        """(state, since) of one session, keeping its marks."""
        working, was = st in WORKING, self.last.get(key) in WORKING
        if working:
            self.done.pop(key, None)
            if not was or key not in self.run_since:
                self.run_since[key] = at
        else:
            self.run_since.pop(key, None)
            if st == "idle" and was:
                self.done[key] = now
        state = ("waiting" if st == "waiting" else "working" if working else
                 "done" if key in self.done else "idle")
        since = (self.run_since.get(key, at) if working else
                 self.done.get(key, at) if state == "done" else at)
        return state, since

    def poll(self) -> bool:
        """Look again; whether the rows changed."""
        now = self.clock()
        status, found = {}, {}
        recs, jobs = [], {}
        for pid, rec in self.records():
            if not rec or not isinstance(rec.get("sessionId"), str):
                old = self.by_pid.get(pid)                  # caught mid-write: as it was
                if old:
                    found[pid] = old
                    status[old[0].id] = old[1]
                continue
            # a background session (Claude Code's `--bg`, or one a tab parked)
            # has no row: no tab to go to.  A tab that parked its conversation
            # shows that conversation's state: its own stopped when it did
            if rec.get("kind") == "bg":
                if isinstance(rec.get("jobId"), str):
                    jobs[rec["jobId"]] = rec
                continue
            recs.append((pid, rec))
        for pid, rec in recs:
            job = jobs.get(rec.get("parkedJobId")) if isinstance(rec.get("parkedJobId"), str) else None
            if job:
                rec = dict(rec, status=job.get("status"), statusUpdatedAt=job.get("statusUpdatedAt"))
            sid = rec["sessionId"]
            st = str(rec.get("status") or "idle")
            at = rec.get("statusUpdatedAt")
            at = float(at) / 1000 if isinstance(at, (int, float)) and not isinstance(at, bool) \
                else now
            state, since = self._track(sid, st, at, now)
            status[sid] = st
            cwd = str(rec.get("cwd") or "")
            own = rec.get("name").strip() if isinstance(rec.get("name"), str) else ""
            custom, auto = self._title(sid, cwd)
            name = (custom or (own if rec.get("nameSource") == "user" and own else None)
                    or auto or own or ntpath.basename(cwd.rstrip("\\/")) or "session")
            found[pid] = (Row(id=sid, pid=pid, name=name, project=cwd, state=state,
                              age="" if state == "idle" else age(now - since),
                              recent=1e12 + since if state == "working" else since,
                              kind="here", machine=None, can_open=True, status=st), st)
        self.by_pid = found
        one = {}                                            # one row per session
        for row, _st in found.values():
            if row.id not in one or one[row.id].pid < row.pid:
                one[row.id] = row
        for a in self.away:
            key = a["id"]
            if key in one:
                continue
            st = {"working": "busy", "waiting": "waiting", "idle": "idle"}.get(a.get("state"))
            at = a.get("since") if isinstance(a.get("since"), (int, float)) else None
            if st is None:                                  # not heard lately
                status[key] = self.last.get(key) or "unknown"
                state, since = "unknown", at
            else:
                state, since = self._track(key, st, at or now, now)
                status[key] = st
            one[key] = Row(id=key, pid=0, name=a.get("name") or "session",
                           project=a.get("project") or "", state=state,
                           age="" if state in ("idle", "unknown") or since is None
                           else age(now - since),
                           recent=(1e12 + since if state == "working" else since) or 0.0,
                           kind="away", machine=a.get("machine"),
                           can_open=bool(a.get("can_open")), status=st or "unknown")
        # a handover or take-back under way: on the session's row, or a row
        # of its own while the session is on its way there
        moving = [t for t in (self.moving() or []) if isinstance(t, dict)]
        keys = {str(t.get("uuid") or t.get("project")) for t in moving}
        if keys != self.moved:
            self.away_stale = self.away_stale or bool(self.moved - keys)
            self.moved = keys
        for t in moving:
            proj = os.path.normcase(os.path.realpath(str(t.get("project") or "")))
            row = next((r for r in one.values()
                        if r.kind == "away" and r.project
                        and os.path.normcase(os.path.realpath(r.project)) == proj), None)
            if row is None:
                sid = t.get("session")
                key = "away:" + str(sid or t.get("uuid"))
                custom, auto = self._title(sid, str(t.get("project") or "")) if sid else (None, None)
                row = one[key] = Row(
                    id=key, pid=0, name=custom or auto
                    or ntpath.basename(str(t.get("project") or "").rstrip("\\/")) or "session",
                    project=str(t.get("project") or ""), state="moving", age="",
                    recent=1e12 + float(t.get("started") or now), kind="away",
                    machine=t.get("remote") or "?", can_open=False, status="moving")
            row.transfer = {k: t.get(k) for k in ("kind", "stage", "percent", "done_bytes",
                                                  "total_bytes", "eta", "over")}
        self.done = {k: v for k, v in self.done.items() if k in status}
        if status != self.last:
            self.last = status
            self.save()
        rows = sorted(one.values(), key=lambda r: (-r.recent, r.name.lower(), r.pid))
        changed = rows != self.rows
        self.rows = rows
        if self.note and now >= self.note_until:
            self.note = None
            changed = True
        return changed

    def _title(self, sid, cwd):
        """(custom, automatic) title from the session's conversation file: the
        last one a rename, the app or aht's hook set, and Claude's own.  Only
        what was added since the last look is read; the first look reads up
        to 8 MB."""
        for c in dict.fromkeys(x for x in (cwd, os.path.realpath(cwd) if cwd else "") if x):
            path = self.projects / aht._key_claude(c) / f"{sid}.jsonl"
            try:
                size = path.stat().st_size
            except OSError:
                continue
            end, custom, auto = self.titles.get(str(path), (0, "", ""))
            if size < end:                                  # written anew
                end, custom, auto = 0, "", ""
            if size > end:
                start = end if end else max(0, size - (8 << 20))
                try:
                    with open(path, "rb") as fh:
                        fh.seek(start)
                        data = fh.read(size - start)
                except OSError:
                    return None, None
                custom = _last_of(data, "custom-title", "customTitle") or custom
                auto = _last_of(data, "ai-title", "aiTitle") or auto
                nl = data.rfind(b"\n")
                if nl >= 0:                                 # a line half written: again
                    end = start + nl + 1
                self.titles[str(path)] = (end, custom, auto)
            return custom or None, auto or None
        return None, None

    def say(self, text: str, secs: float = 8):
        self.note, self.note_until = text, self.clock() + secs

    def seen(self, key):
        """You looked at it: it is no longer "done"."""
        if self.done.pop(key, None) is not None:
            self.save()

    def summary(self) -> str:
        n = lambda s: sum(1 for r in self.rows if r.state == s)     # noqa: E731
        parts = [f"{n(s)} {w}" for s, w in (("waiting", "waiting"), ("done", "done"),
                                             ("working", "working")) if n(s)]
        moving = sum(1 for r in self.rows if r.transfer)
        if moving:
            parts.append(f"{moving} on the way")
        if not self.rows:
            return "No Claude session open"
        return " · ".join(parts) if parts else f"{len(self.rows)} open, all idle"

    def save(self):
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_file.with_name(self.state_file.name + ".new")
            tmp.write_text(json.dumps({"last": self.last, "done": self.done}), encoding="utf-8")
            os.replace(tmp, self.state_file)
        except OSError as e:
            aht.warn(f"CORNER the session corner's marks were not saved: {e}")


def left_text(eta) -> str:
    return ("under a minute left" if eta < 60 else f"{round(eta / 60)} min left"
            if eta < 3600 else f"{eta // 3600} h {eta % 3600 // 60} min left")


def transfer_text(t: dict) -> str:
    """The second line of a session on its way (its arrow says which way):
    how much went, of how much, and how long it still takes; before any
    data moves, the stage."""
    done, total, eta = t.get("done_bytes"), t.get("total_bytes"), t.get("eta")
    if done is None:                    # a step that only takes time (an install there)
        st = str(t.get("stage") or "").strip()
        out = (st[:1].upper() + st[1:]) if st else (
            "Taking back …" if t.get("kind") == "reclaim" else "Sending …")
        if t.get("over"):
            return out + " · taking longer than before"
        return out + (" · " + left_text(int(eta)) if isinstance(eta, (int, float)) else "")
    out = aht._human(done) + (f" of {aht._human(total)}" if total else "")
    return out + (" · " + left_text(int(eta)) if isinstance(eta, (int, float)) else "")


def right_text(r: Row) -> str:
    """What the list shows at the right of a session."""
    if r.transfer:
        pct = r.transfer.get("percent")
        arrow = "←" if r.transfer.get("kind") == "reclaim" else "→"
        return f"{arrow} {r.machine}" + (f" {pct}%" if isinstance(pct, int) else "")
    t = ("waits " + r.age if r.state == "waiting" and r.age else r.age or "")
    if r.kind == "away":
        return f"→ {r.machine}" + (f" {t}" if t else " ?" if r.state == "unknown" else "")
    return t


def tip_text(r: Row) -> str:
    """The note that shows over a session."""
    if r.transfer:
        where = ("from " if r.transfer.get("kind") == "reclaim" else "to ") + str(r.machine)
        verb = "Taking back" if r.transfer.get("kind") == "reclaim" else "Sending"
        return f"{r.name}\n{r.project}\n{verb} {where}: {transfer_text(r.transfer)}."
    if r.kind == "away":
        how = ("not heard from lately" if r.state == "unknown" else
               {"working": "working", "waiting": "waiting for you", "done": "done",
                "idle": "idle"}.get(r.state, r.state))
        return (f"{r.name}\n{r.project}\nOn {r.machine}: {how}.\n"
                + ("A click opens it; right-click for Take Back." if r.can_open else
                   "Right-click for Take Back."))
    return (f"{r.name}\n{r.project}\n"
            + ("Done. A click goes to its tab and clears the mark." if r.state == "done"
               else "A click goes to its tab; right-click for more."))


def list_items(restarting: bool = False) -> list:
    """What every right-click on the list ends with, and all that one beside
    the sessions offers, for the workspace (the terminal's tabs with their
    sessions): saved now, a saved one opened again, the terminal closed and
    the workspace opened again; and the list hidden.  `restarting`: a restart,
    its look ahead or its question is under way, so it is not offered a second
    time."""
    return [("Save Workspace Now", "save-workspace", False),
            ("Restore Workspace…", "workspaces", False),
            ("Restart Workspace (under way)", None, False) if restarting else
            ("Restart Workspace…", "restart-workspace", False), "-",
            ("Hide the List", "hide", False)]


def menu_items(r: Row, machines: list, restarting: bool = False) -> list:
    """The right-click menu of a session: [(label, action or None for grayed,
    is default)], "-" for a line between.  Actions: "goto", "branch",
    "backup-now", "backups", "send:<machine>", "open", "take-back", then
    list_items()'s "save-workspace", "workspaces", "restart-workspace", "hide"."""
    rest = list_items(restarting)
    if r.transfer:
        return [("Open Session (once it is there)" if r.transfer.get("kind") != "reclaim"
                 else "Go to Tab (once it is back)", None, False), "-"] + rest
    if r.kind == "away":
        return [("Open Session", "open" if r.can_open else None, True),
                ("Take Back…", "take-back", False), "-"] + rest
    busy = r.status in WORKING or r.status == "waiting"
    later = " (once it has finished)" if r.status in WORKING else \
        " (answer it first)" if r.status == "waiting" else ""
    out = [("Go to Tab", "goto", True), ("Branch…" + later, None if busy else "branch", False),
           "-", ("Back Up This Project Now", "backup-now", False),
           ("Backups of This Project…", "backups", False)]
    out.append("-")                     # sending is not a backup: a group of its own
    if machines:
        out += [(f"Send to {m}…" + later, None if busy else "send:" + m, False) for m in machines]
    else:
        out.append(("Send to Another Machine (add one in the Machines tab first)", None, False))
    return out + ["-"] + rest


def _count(n: int, what: str) -> str:
    return f"{n} {what}{'' if n == 1 else 's'}"


def restart_question(plan: dict) -> str:
    """What the confirmation of Restart Workspace… says, from the dry run of
    `aht.restart_workspace()`: the terminal closes and the workspace opens
    again, so it names what comes back and what does not."""
    term = plan.get("terminal") or "the terminal"
    out = [f"Close {term} and open the workspace again?",
           f"aht saves the workspace, ends every Claude session, closes {term} and starts it "
           "again with the same windows and tabs. Each session comes back in its tab, where it "
           "left off, with the options it had. Anything typed but not sent is lost, and so is "
           "the text the tabs show now."]
    if plan.get("sessions"):
        out.append("Sessions: " + ", ".join(str(x) for x in plan["sessions"]))
    if plan.get("working"):
        out.append("Working now, their task stops: " + ", ".join(str(x) for x in plan["working"]))
    plain = int(plan.get("plain") or 0)
    if plain > 0:
        out.append("1 plain tab comes back empty, in its folder." if plain == 1 else
                   f"{plain} plain tabs come back empty, in their folders.")
    ending = [str(x) for x in plan.get("ending") or []]
    if ending:
        # a long list would push the buttons off the screen: the first few, then how many more
        out.append("Ends and does not come back: " + "; ".join(ending[:6])
                   + (f" and {len(ending) - 6} more" if len(ending) > 6 else ""))
    if plan.get("asks"):
        out.append(f"{term} asks once more whether to quit: say yes there.")
    out.append(f"Yes closes {term} and opens the workspace again. No leaves everything as it is.")
    return "\n\n".join(out)


def _left_out(plan: dict) -> str:
    """The sessions a restart leaves as they are, each with why."""
    return "; ".join(f"{x.get('session')} ({x.get('why')})" for x in plan.get("left_out") or [])


NOT_RESTARTED = "Workspace not restarted"


def not_restarted(plan) -> str:
    """Restart Workspace… cannot ask its question: why, under the top line
    (the terminal is not open, say, or aht answered nothing)."""
    if not plan or not isinstance(plan, dict) or not plan.get("blockers"):
        return NOT_RESTARTED + ": aht gave no answer"
    return f"{NOT_RESTARTED}: {plan['blockers'][0]}"


def restarted_text(res) -> str:
    """What Restart Workspace says under the top line once it is through:
    how many tabs opened again, of how many (restart_trouble() has what did
    not come back)."""
    if not res or not isinstance(res, dict):
        return NOT_RESTARTED + ": aht gave no answer"
    blockers = res.get("blockers") or []
    opened, of = int(res.get("opened") or 0), int(res.get("of") or 0)
    if opened > 0 and opened == of and not blockers:
        return f"Workspace restarted: {opened} opened again"
    if opened > 0:
        return f"Workspace restarted: {opened} of {of} opened again"
    return f"{NOT_RESTARTED}: {blockers[0] if blockers else 'nothing opened'}"


def _sentence(text) -> str:
    """A blocker as a sentence of its own in a message: a capital first and a
    full stop last.  A first word that has a capital in it (iTerm2, a
    RuntimeError) or is aht's own name stays as it is written."""
    s = str(text).strip()
    first = s.split(None, 1)[0] if s else ""
    own = first.rstrip(".,:;!?") == "aht" or first.startswith(("aht'", "aht’"))
    if first and not own and first == first.lower():
        s = s[0].upper() + s[1:]
    return s + ("" if not s or s[-1] in ".!?…" else ".")


def restart_trouble(res):
    """What went wrong in Restart Workspace, from what `aht.restart_workspace(
    apply=True)` answered: (title, text) for a message, or None when nothing
    did.  The terminal was closed by then, so it says whether anything came
    back."""
    if not res or not isinstance(res, dict):
        return NOT_RESTARTED, NO_ANSWER
    blockers = res.get("blockers") or []
    if not blockers:
        return None
    title = "Not everything came back" if int(res.get("opened") or 0) > 0 else NOT_RESTARTED
    return title, "\n\n".join(_sentence(b) for b in blockers)


def restart_problems(res: dict):
    """The sessions a restart in their tabs (the one after an update of Claude
    Code) did not restart, each with why, a paragraph each; None when every
    one restarted."""
    out = [f"{x.get('session')}: {x.get('why')}" for x in res.get("failed") or []]
    out += [f"{name}: it was still working, so aht left it as it is"
            for name in res.get("not_waited") or []]
    return "\n\n".join(out) or None


NOT_UPDATED = "Claude Code was not updated"
NO_ANSWER = "aht gave no answer — see the log (Settings)."


def update_refusal(plan):
    """Why Update Claude Code… cannot ask its question, from what `aht update
    --claude --json` answered (None when it printed nothing a program can
    read); None when it can ask."""
    if not plan or not isinstance(plan, dict):
        return NO_ANSWER
    if plan.get("blockers"):
        return "\n\n".join(str(b) for b in plan["blockers"])
    return None if plan.get("command") else NO_ANSWER


def update_question(plan: dict) -> str:
    """What the confirmation of Update Claude Code… says, from the dry run of
    `aht update --claude`.  Its buttons are Yes and No."""
    how = plan.get("how") or "its installer"
    r = plan.get("restart") or {}
    out = ["aht updates Claude Code " + (f"{plan['before']} " if plan.get("before") else "")
           + f"with {how}, the way it was installed."]
    if plan.get("while_running") is False:
        # an installer's name stays as it is written (winget); the stand-in starts the sentence
        out.append(f"{how if plan.get('how') else 'Its installer'} cannot replace "
                   "Claude Code while it runs, so every open Claude session ends first, once it "
                   "is idle, and starts again in its tab after the update, where it left off, "
                   "with the options it had. Anything typed into a session but not sent is lost.")
    else:
        out.append("If that brings a newer version, every open Claude session ends and starts "
                   "again in its tab, where it left off, with the options it had: an idle one "
                   "at once, a working one once it is idle. Anything typed into a session but "
                   "not sent is lost.")
    names = list(r.get("now") or []) + list(r.get("after") or [])
    if names:
        out.append("Sessions: " + ", ".join(str(x) for x in names))
    left = _left_out(r)
    if left:
        out.append("Left as they are: " + left)
    out += ["A notice says when it is done.", "Yes updates. No changes nothing."]
    return "\n\n".join(out)


def update_problems(res):
    """What went wrong in `aht update --claude --apply`, from what it
    answered: (title, text) for a message, or None when nothing did (the
    core's notice then says it is done)."""
    if not res or not isinstance(res, dict):
        return NOT_UPDATED, NO_ANSWER
    lines = [str(x) for x in (res.get("blockers") or []) + (res.get("warnings") or [])]
    restart = res.get("restart")
    left = restart_problems(restart if isinstance(restart, dict) else {})
    if left:
        lines.append(left)
    if not lines:
        return None
    title = (f"Claude Code updated to {res['after']}" if res.get("after") else "Claude Code updated") \
        if res.get("updated") is True else NOT_UPDATED
    return title, "\n\n".join(lines)


def saved_text(res: dict) -> str:
    """What Save Workspace Now says under the top line."""
    if not res.get("saved"):
        return "Workspace not saved: " + (res.get("why") or "nothing to save")
    return (f"Workspace saved: {_count(int(res.get('tabs') or 0), 'tab')}, "
            f"{_count(int(res.get('sessions') or 0), 'session')}")


def send_question(res: dict) -> str:
    """What the confirmation of Send to <machine> says."""
    h = res.get("handover") or {}
    to = res.get("to")
    there = h.get("there_path") or "the same place"
    lines = [f"Send “{res.get('label')}” to {to}?", "",
             f"The session ends here, and its project folder ({res.get('project')}) "
             f"and its history go to {to}, to {there}."]
    if h.get("pc"):
        lines.append(f"{to} is a PC: no session starts there; its tray offers Continue here.")
    else:
        lines.append(f"The session goes on there, and this tab connects to it. On {to} it "
                     "keeps working when this computer sleeps or loses its connection.")
    lines += ["", "Bring it back later with Take Back… (right-click it in this list, or in "
              "aht's window)."]
    for w in res.get("warnings") or []:
        lines += ["", "Note: " + w]
    return "\n".join(lines)


# ---- the window ---------------------------------------------------------------- #

PAD, HEAD, ROW, MORE, ICON_W, GAP, INSET = 5, 20, 22, 18, 14, 7, 6
TLINE = 18                          # a session on its way: its second line and bar
EDGE = 6
LEFT, RIGHT, TOP, BOTTOM = 1, 2, 4, 8
AWAY_RGB = (37, 99, 235)            # the folder badge's "handed over" blue

THEMES = {
    False: {"bg": (249, 249, 249), "fg": (27, 27, 27), "dim": (96, 96, 96),
            "working": (0, 103, 192), "waiting": (214, 110, 0), "done": (16, 124, 16),
            "away": AWAY_RGB},
    True: {"bg": (43, 43, 43), "fg": (255, 255, 255), "dim": (170, 170, 170),
           "working": (96, 205, 255), "waiting": (255, 165, 60), "done": (108, 203, 95),
           "away": (120, 160, 255)},
}

# Segoe Fluent Icons (Windows 11), else Segoe MDL2 Assets (Windows 10)
GLYPH = {"working": "", "done": "", "idle": "", "unknown": "",
         "circle": "", "bang": "", "close": "",
         "send": "\uE898", "back": "\uE896"}


def blend(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def rgb(c):
    return c[0] | c[1] << 8 | c[2] << 16


if os.name == "nt":
    from ctypes import wintypes as W

    _u = ctypes.WinDLL("user32", use_last_error=True)
    _g = ctypes.WinDLL("gdi32", use_last_error=True)
    _k = ctypes.WinDLL("kernel32", use_last_error=True)
    try:
        _dwm = ctypes.WinDLL("dwmapi")
    except OSError:
        _dwm = None
    try:
        _cc = ctypes.WinDLL("comctl32")
    except OSError:
        _cc = None

    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
    H = ctypes.c_void_p

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [("style", W.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                    ("cbWndExtra", ctypes.c_int), ("hInstance", H), ("hIcon", H),
                    ("hCursor", H), ("hbrBackground", H), ("lpszMenuName", W.LPCWSTR),
                    ("lpszClassName", W.LPCWSTR)]

    class PAINTSTRUCT(ctypes.Structure):
        _fields_ = [("hdc", H), ("fErase", W.BOOL), ("rcPaint", W.RECT),
                    ("fRestore", W.BOOL), ("fIncUpdate", W.BOOL), ("rgbReserved", ctypes.c_byte * 32)]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", W.DWORD), ("rcMonitor", W.RECT), ("rcWork", W.RECT),
                    ("dwFlags", W.DWORD)]

    class TRACKMOUSEEVENT(ctypes.Structure):
        _fields_ = [("cbSize", W.DWORD), ("dwFlags", W.DWORD), ("hwndTrack", H),
                    ("dwHoverTime", W.DWORD)]

    class TOOLINFOW(ctypes.Structure):          # the size every comctl32 takes
        _fields_ = [("cbSize", W.UINT), ("uFlags", W.UINT), ("hwnd", H), ("uId", ctypes.c_size_t),
                    ("rect", W.RECT), ("hinst", H), ("lpszText", ctypes.c_wchar_p),
                    ("lParam", W.LPARAM)]

    class SIZE(ctypes.Structure):
        _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]

    for fn, res, args in (
            ("CreateWindowExW", H, [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_int, H, H, H, H]),
            ("DefWindowProcW", LRESULT, [H, W.UINT, W.WPARAM, W.LPARAM]),
            ("RegisterClassW", W.ATOM, [ctypes.POINTER(WNDCLASSW)]),
            ("BeginPaint", H, [H, ctypes.POINTER(PAINTSTRUCT)]),
            ("EndPaint", W.BOOL, [H, ctypes.POINTER(PAINTSTRUCT)]),
            ("GetDC", H, [H]), ("ReleaseDC", ctypes.c_int, [H, H]),
            ("FillRect", ctypes.c_int, [H, ctypes.POINTER(W.RECT), H]),
            ("DrawTextW", ctypes.c_int, [H, W.LPCWSTR, ctypes.c_int, ctypes.POINTER(W.RECT), W.UINT]),
            ("SetWindowPos", W.BOOL, [H, H, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                      W.UINT]),
            ("ShowWindow", W.BOOL, [H, ctypes.c_int]),
            ("InvalidateRect", W.BOOL, [H, ctypes.c_void_p, W.BOOL]),
            ("SetTimer", ctypes.c_size_t, [H, ctypes.c_size_t, W.UINT, ctypes.c_void_p]),
            ("KillTimer", W.BOOL, [H, ctypes.c_size_t]),
            ("GetCursorPos", W.BOOL, [ctypes.POINTER(W.POINT)]),
            ("GetWindowRect", W.BOOL, [H, ctypes.POINTER(W.RECT)]),
            ("SetCapture", H, [H]), ("ReleaseCapture", W.BOOL, []), ("GetCapture", H, []),
            ("LoadCursorW", H, [H, ctypes.c_void_p]), ("SetCursor", H, [H]),
            ("TrackMouseEvent", W.BOOL, [ctypes.POINTER(TRACKMOUSEEVENT)]),
            ("MonitorFromPoint", H, [W.POINT, W.DWORD]),
            ("MonitorFromWindow", H, [H, W.DWORD]),
            ("GetMonitorInfoW", W.BOOL, [H, ctypes.POINTER(MONITORINFO)]),
            ("CreatePopupMenu", H, []), ("DestroyMenu", W.BOOL, [H]),
            ("AppendMenuW", W.BOOL, [H, W.UINT, ctypes.c_size_t, W.LPCWSTR]),
            ("SetMenuDefaultItem", W.BOOL, [H, W.UINT, W.UINT]),
            ("TrackPopupMenu", ctypes.c_int, [H, W.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                              H, ctypes.c_void_p]),
            ("SetForegroundWindow", W.BOOL, [H]), ("PostMessageW", W.BOOL, [H, W.UINT, W.WPARAM, W.LPARAM]),
            ("SendMessageW", LRESULT, [H, W.UINT, W.WPARAM, W.LPARAM]),
            ("GetSystemMetrics", ctypes.c_int, [ctypes.c_int]),
            ("IsWindowVisible", W.BOOL, [H]), ("DestroyWindow", W.BOOL, [H]),
            ("ScreenToClient", W.BOOL, [H, ctypes.POINTER(W.POINT)]),
            ("AllowSetForegroundWindow", W.BOOL, [W.DWORD]),
            ("GetMessageW", W.BOOL, [ctypes.POINTER(W.MSG), H, W.UINT, W.UINT]),
            ("TranslateMessage", W.BOOL, [ctypes.POINTER(W.MSG)]),
            ("DispatchMessageW", LRESULT, [ctypes.POINTER(W.MSG)]),
            ("IsDialogMessageW", W.BOOL, [H, ctypes.POINTER(W.MSG)]),
            ("EnableWindow", W.BOOL, [H, W.BOOL]), ("SetFocus", H, [H]),
            ("GetWindowTextW", ctypes.c_int, [H, W.LPWSTR, ctypes.c_int]),
            ("GetWindowTextLengthW", ctypes.c_int, [H]),
            ("IsWindow", W.BOOL, [H]), ("PostQuitMessage", None, [ctypes.c_int])):
        f = getattr(_u, fn)
        f.restype, f.argtypes = res, args
    try:
        _u.GetDpiForWindow.restype, _u.GetDpiForWindow.argtypes = W.UINT, [H]
    except AttributeError:
        pass
    for fn, res, args in (
            ("CreateCompatibleDC", H, [H]), ("CreateCompatibleBitmap", H, [H, ctypes.c_int, ctypes.c_int]),
            ("SelectObject", H, [H, H]), ("DeleteObject", W.BOOL, [H]), ("DeleteDC", W.BOOL, [H]),
            ("BitBlt", W.BOOL, [H, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, H,
                                ctypes.c_int, ctypes.c_int, W.DWORD]),
            ("CreateSolidBrush", H, [W.COLORREF]), ("SetTextColor", W.COLORREF, [H, W.COLORREF]),
            ("SetBkMode", ctypes.c_int, [H, ctypes.c_int]),
            ("CreateFontW", H, [ctypes.c_int] * 5 + [W.DWORD] * 8 + [W.LPCWSTR]),
            ("GetTextFaceW", ctypes.c_int, [H, ctypes.c_int, W.LPWSTR]),
            ("GetTextExtentPoint32W", W.BOOL, [H, W.LPCWSTR, ctypes.c_int, ctypes.POINTER(SIZE)]),
            ("RoundRect", W.BOOL, [H] + [ctypes.c_int] * 6),
            ("GetStockObject", H, [ctypes.c_int]),
            ("CreateDIBSection", H, [H, ctypes.c_void_p, W.UINT, ctypes.POINTER(ctypes.c_void_p),
                                     H, W.DWORD])):
        f = getattr(_g, fn)
        f.restype, f.argtypes = res, args
    _k.GetModuleHandleW.restype, _k.GetModuleHandleW.argtypes = H, [W.LPCWSTR]


WM_DESTROY, WM_PAINT, WM_CLOSE, WM_ERASEBKGND = 0x2, 0xF, 0x10, 0x14
WM_SETTINGCHANGE, WM_SETCURSOR, WM_MOUSEACTIVATE = 0x1A, 0x20, 0x21
WM_DISPLAYCHANGE, WM_NOTIFY, WM_COMMAND, WM_TIMER = 0x7E, 0x4E, 0x111, 0x113
WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_LBUTTONDBLCLK = 0x200, 0x201, 0x202, 0x203
WM_RBUTTONUP, WM_CAPTURECHANGED, WM_MOUSELEAVE, WM_DPICHANGED = 0x205, 0x215, 0x2A3, 0x2E0
WM_SETFONT, WM_APP, WM_USER = 0x30, 0x8000, 0x400
WM_RUN = WM_APP + 3                         # run what a thread handed over
MA_NOACTIVATE, HTCLIENT = 3, 1
WS_POPUP, WS_VISIBLE, WS_CHILD, WS_TABSTOP = 0x80000000, 0x10000000, 0x40000000, 0x10000
WS_CAPTION, WS_SYSMENU, WS_BORDER = 0xC00000, 0x80000, 0x800000
WS_EX_TOPMOST, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x8, 0x80, 0x08000000
WS_EX_DLGMODALFRAME, WS_EX_CLIENTEDGE = 0x1, 0x200
CS_DBLCLKS, CS_DROPSHADOW = 0x8, 0x20000
SWP_NOZORDER, SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x4, 0x10, 0x40
SW_HIDE, SW_SHOWNOACTIVATE = 0, 4
HWND_TOPMOST = -1
DT_LEFT, DT_RIGHT, DT_VCENTER, DT_SINGLELINE, DT_END_ELLIPSIS = 0x0, 0x2, 0x4, 0x20, 0x8000
DT_NOPREFIX, DT_WORDBREAK, DT_CALCRECT, DT_CENTER = 0x800, 0x10, 0x400, 0x1
TRANSPARENT, NULL_PEN, SRCCOPY = 1, 8, 0x00CC0020
IDC_ARROW, IDC_SIZENWSE, IDC_SIZENESW, IDC_SIZEWE, IDC_SIZENS = 32512, 32642, 32643, 32644, 32645
TME_LEAVE = 0x2
MONITOR_DEFAULTTONEAREST, MONITOR_DEFAULTTOPRIMARY = 2, 1
MF_STRING, MF_GRAYED, MF_SEPARATOR = 0x0, 0x1, 0x800
TPM_RIGHTBUTTON, TPM_RETURNCMD, TPM_NONOTIFY = 0x2, 0x100, 0x80
SM_CXDRAG, SM_CYDRAG = 68, 69
TTM_ADDTOOLW, TTM_DELTOOLW, TTM_SETMAXTIPWIDTH, TTM_ACTIVATE = WM_USER + 50, WM_USER + 51, \
    WM_USER + 24, WM_USER + 1
TTM_NEWTOOLRECTW, TTM_UPDATETIPTEXTW = WM_USER + 52, WM_USER + 57
TTS_ALWAYSTIP, TTS_NOPREFIX, TTF_SUBCLASS = 0x1, 0x2, 0x10
ES_AUTOHSCROLL, BS_DEFPUSHBUTTON, BS_PUSHBUTTON = 0x80, 0x1, 0x0
EM_SETSEL = 0xB1
IDOK, IDCANCEL = 1, 2
DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND = 33, 2


def _lo(v):
    return ctypes.c_short(v & 0xFFFF).value


def _hi(v):
    return ctypes.c_short((v >> 16) & 0xFFFF).value


def dark_mode() -> bool:
    """Windows' "app mode" is dark."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows"
                            r"\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


class Painter:
    """Fonts and drawing at one DPI and theme."""

    def __init__(self, dpi: int, dark: bool):
        self.dpi, self.dark, self.t = dpi, dark, THEMES[dark]
        s = dpi / 96
        self.s = s

        def font(px, weight=400, face="Segoe UI"):
            return _g.CreateFontW(-round(px * s), 0, 0, 0, weight, 0, 0, 0, 1, 0, 0, 5, 0, face)
        self.text = font(12)
        self.bold = font(12, 600)
        self.small = font(11)
        self.head = font(11, 600)
        self.icons = font(12, 400, "Segoe Fluent Icons")
        self.x = font(8, 400, "Segoe Fluent Icons")
        dc = _u.GetDC(None)
        old = _g.SelectObject(dc, self.icons)
        face = ctypes.create_unicode_buffer(64)
        _g.GetTextFaceW(dc, 64, face)
        _g.SelectObject(dc, old)
        _u.ReleaseDC(None, dc)
        if face.value != "Segoe Fluent Icons":             # Windows 10
            for f in (self.icons, self.x):
                _g.DeleteObject(f)
            self.icons = font(12, 400, "Segoe MDL2 Assets")
            self.x = font(8, 400, "Segoe MDL2 Assets")

    def px(self, v):
        return round(v * self.s)

    def close(self):
        for f in (self.text, self.bold, self.small, self.head, self.icons, self.x):
            _g.DeleteObject(f)

    # Windows counts a text in UTF-16 units, Python in characters: an emoji is
    # two units, so len(text) would leave the last letter of its name out.
    # DrawTextW takes -1 (up to the text's end); the measure takes the units
    def measure(self, dc, font, text) -> int:
        old = _g.SelectObject(dc, font)
        sz = SIZE()
        _g.GetTextExtentPoint32W(dc, text, len(text.encode("utf-16-le")) // 2, ctypes.byref(sz))
        _g.SelectObject(dc, old)
        return sz.cx

    def fill(self, dc, rect, color, radius=0):
        b = _g.CreateSolidBrush(rgb(color))
        if radius:
            oldb, oldp = _g.SelectObject(dc, b), _g.SelectObject(dc, _g.GetStockObject(NULL_PEN))
            _g.RoundRect(dc, rect[0], rect[1], rect[2] + 1, rect[3] + 1, radius * 2, radius * 2)
            _g.SelectObject(dc, oldb)
            _g.SelectObject(dc, oldp)
        else:
            _u.FillRect(dc, ctypes.byref(W.RECT(*rect)), b)
        _g.DeleteObject(b)

    def write(self, dc, font, text, rect, color, flags):
        old = _g.SelectObject(dc, font)
        _g.SetTextColor(dc, rgb(color))
        r = W.RECT(*rect)
        _u.DrawTextW(dc, text, -1, ctypes.byref(r), flags | DT_NOPREFIX)
        _g.SelectObject(dc, old)

    def wrapped_height(self, dc, font, text, width) -> int:
        old = _g.SelectObject(dc, font)
        r = W.RECT(0, 0, width, 0)
        _u.DrawTextW(dc, text, -1, ctypes.byref(r), DT_WORDBREAK | DT_CALCRECT | DT_NOPREFIX)
        _g.SelectObject(dc, old)
        return r.bottom


def layout(m: Model, width_px: int, most: int, p: "Painter", dc) -> dict:
    """Where everything goes, in pixels: {"size", "head", "close", "note",
    "rows": [(row, rect)], "more"}."""
    pad, head = p.px(PAD), p.px(HEAD)
    y = pad
    out = {"head": (pad, y, width_px - pad, y + head)}
    cx = p.px(14)
    out["close"] = (width_px - pad - cx - p.px(2), y + (head - cx) // 2, width_px - pad - p.px(2),
                    y + (head - cx) // 2 + cx)
    y += head
    if m.note:
        h = p.wrapped_height(dc, p.small, m.note, width_px - 2 * (pad + p.px(INSET)))
        out["note"] = (pad + p.px(INSET), y, width_px - pad - p.px(INSET), y + h)
        y += h + p.px(3)
    rows = []
    for r in m.rows[:max(0, most)]:
        h = p.px(ROW + (TLINE if r.transfer else 0))
        rows.append((r, (pad, y, width_px - pad, y + h)))
        y += h
    out["rows"] = rows
    if len(m.rows) > most:
        out["more"] = (pad + p.px(INSET), y, width_px - pad, y + p.px(MORE))
        y += p.px(MORE)
    out["size"] = (width_px, y + pad)
    return out


def paint(dc, m: Model, lay: dict, p: "Painter", hover=None, hover_close=False):
    t = p.t
    w, h = lay["size"]
    p.fill(dc, (0, 0, w, h), blend(t["bg"], t["fg"], 0.16))     # a hairline edge, then the list
    p.fill(dc, (1, 1, w - 1, h - 1), t["bg"])
    _g.SetBkMode(dc, TRANSPARENT)
    x0, y0, x1, y1 = lay["head"]
    ix = x0 + p.px(INSET)
    p.write(dc, p.head, "∞", (ix, y0, ix + p.px(14), y1), t["dim"], DT_SINGLELINE | DT_VCENTER)
    cx0 = lay["close"][0]
    p.write(dc, p.small, m.summary(), (ix + p.px(14), y0, cx0 - p.px(6), y1), t["dim"],
            DT_SINGLELINE | DT_VCENTER | DT_END_ELLIPSIS)
    if hover_close:
        p.fill(dc, lay["close"], blend(t["bg"], t["fg"], 0.12), p.px(3))
    p.write(dc, p.x, GLYPH["close"], lay["close"], t["dim"], DT_SINGLELINE | DT_VCENTER | DT_CENTER)
    if "note" in lay:
        p.write(dc, p.small, m.note, lay["note"], t["waiting"], DT_WORDBREAK)
    for r, (a, b, c, d) in lay["rows"]:
        bg = (blend(t["bg"], t["fg"], 0.09) if hover == r.id else
              blend(t["bg"], t["done"], 0.13) if r.state == "done" else
              blend(t["bg"], t["waiting"], 0.13) if r.state == "waiting" else None)
        if bg:
            p.fill(dc, (a, b, c, d), bg, p.px(5))
        ix = a + p.px(INSET)
        if r.transfer:                          # the second line and the bar
            line2 = (ix + p.px(ICON_W + GAP), b + p.px(ROW) - p.px(3), c - p.px(INSET),
                     d - p.px(5))
            p.write(dc, p.small, transfer_text(r.transfer), line2, t["dim"],
                    DT_SINGLELINE | DT_VCENTER | DT_END_ELLIPSIS)
            bar = (line2[0], d - p.px(4), line2[2], d - p.px(2))
            p.fill(dc, bar, blend(t["bg"], t["fg"], 0.12))
            pct = r.transfer.get("percent")
            if isinstance(pct, int) and pct > 0:
                p.fill(dc, (bar[0], bar[1], bar[0] + (bar[2] - bar[0]) * min(pct, 100) // 100,
                            bar[3]), t["away"])
            d = b + p.px(ROW)
        icon = (ix, b, ix + p.px(ICON_W), d)
        flags = DT_SINGLELINE | DT_VCENTER | DT_CENTER
        if r.transfer:
            p.write(dc, p.icons, GLYPH["back" if r.transfer.get("kind") == "reclaim" else "send"],
                    icon, t["away"], flags)
        elif r.state == "waiting":
            p.write(dc, p.icons, GLYPH["circle"], icon, t["waiting"], flags)
            p.write(dc, p.icons, GLYPH["bang"], icon, t["bg"], flags)
        else:
            colour = {"working": t["working"], "done": t["done"]}.get(r.state, t["dim"])
            p.write(dc, p.icons, GLYPH.get(r.state, GLYPH["idle"]), icon, colour, flags)
        right = right_text(r)
        rw = p.measure(dc, p.small, right) if right else 0
        rx = c - p.px(INSET)
        if right:
            p.write(dc, p.small, right, (rx - rw, b, rx, d),
                    t["away"] if r.kind == "away" else t["dim"], DT_SINGLELINE | DT_VCENTER)
        nx = ix + p.px(ICON_W + GAP)
        p.write(dc, p.bold if r.state in ("done", "waiting") else p.text, r.name,
                (nx, b, rx - rw - (p.px(6) if right else 0), d),
                t["dim"] if r.state in ("idle", "unknown") and not r.transfer else t["fg"],
                DT_SINGLELINE | DT_VCENTER | DT_END_ELLIPSIS)
    if "more" in lay:
        p.write(dc, p.small, f"+{len(m.rows) - len(lay['rows'])} more", lay["more"], t["dim"],
                DT_SINGLELINE | DT_VCENTER)


def snapshot(m: Model, path: str, dark: bool = False, width: int = 260, most: int = 12,
             dpi: int = 96) -> tuple:
    """Draw the list into a picture file (BMP), as it would show: for tests
    and the tray's selftest.  -> its size."""
    p = Painter(dpi, dark)
    screen = _u.GetDC(None)
    dc = _g.CreateCompatibleDC(screen)
    lay = layout(m, p.px(width), most, p, dc)
    w, h = lay["size"]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", W.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                    ("biPlanes", W.WORD), ("biBitCount", W.WORD), ("biCompression", W.DWORD),
                    ("biSizeImage", W.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                    ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", W.DWORD),
                    ("biClrImportant", W.DWORD)]
    bi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, h, 1, 32, 0, w * h * 4, 0, 0, 0, 0)
    bits = ctypes.c_void_p()
    bmp = _g.CreateDIBSection(dc, ctypes.byref(bi), 0, ctypes.byref(bits), None, 0)
    old = _g.SelectObject(dc, bmp)
    paint(dc, m, lay, p)
    data = ctypes.string_at(bits, w * h * 4)
    _g.SelectObject(dc, old)
    _g.DeleteObject(bmp)
    _g.DeleteDC(dc)
    _u.ReleaseDC(None, screen)
    p.close()
    import struct
    head = struct.pack("<2sIHHI", b"BM", 54 + len(data), 0, 0, 54) + bytes(bi)
    Path(path).write_bytes(head + data)
    return w, h


class Corner:
    """The list's window.  `hooks`: what the tray lends it — open_window(path,
    do), switch_off(), ask(title, text, no_default=False) -> bool (Yes or No;
    No is the button Enter presses when no_default), tell(title, text),
    note(what, exc) for its log (exc None: `what` alone)."""

    def __init__(self, model: Model, hooks: dict, run_dir):
        self.m, self.hooks = model, hooks
        self.place_file = Path(run_dir) / PLACE_FILE
        self.hwnd = None
        self.tip = None
        self.tips = []
        self.p = None
        self.lay = None
        self.hover = None
        self.hover_close = False
        self.tracking = False
        self.held = None
        self.restarting = False         # Restart Workspace under way
        self.restart_note = None        # … and what the list says of it until it is through
        # the actions whose look ahead or question is open: "restart",
        # ("branch", pid), ("send", pid).  A second click on one does nothing
        self.looking = set()
        self.queue = []
        self.lock = threading.Lock()
        self.width, self.most, self.spot = 260, 12, None
        try:
            j = json.loads(self.place_file.read_text(encoding="utf-8"))
            self.width = max(150, min(720, int(j.get("width") or 260)))
            self.most = max(0, int(j["rows"])) if j.get("rows") is not None else 12
            if isinstance(j.get("x"), int) and isinstance(j.get("y"), int):
                self.spot = (j["x"], j["y"])
        except (OSError, ValueError, TypeError):
            pass
        self._proc = WNDPROC(self._wndproc)

    # -- life ---------------------------------------------------------------
    def create(self):
        hinst = _k.GetModuleHandleW(None)
        wc = WNDCLASSW()
        wc.style = CS_DBLCLKS | CS_DROPSHADOW
        wc.lpfnWndProc = self._proc
        wc.hInstance = hinst
        wc.hCursor = _u.LoadCursorW(None, ctypes.c_void_p(IDC_ARROW))
        wc.lpszClassName = "aht_corner_wnd"
        _u.RegisterClassW(ctypes.byref(wc))
        self.hwnd = _u.CreateWindowExW(WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
                                       "aht_corner_wnd", "aht sessions", WS_POPUP,
                                       0, 0, 10, 10, None, None, hinst, None)
        if not self.hwnd:
            raise OSError(f"no window for the session corner (error {ctypes.get_last_error()})")
        if _dwm:
            pref = ctypes.c_int(DWMWCP_ROUND)
            _dwm.DwmSetWindowAttribute(ctypes.c_void_p(self.hwnd), DWMWA_WINDOW_CORNER_PREFERENCE,
                                       ctypes.byref(pref), 4)
        self._painter()
        if _cc:
            self.tip = _u.CreateWindowExW(WS_EX_TOPMOST, "tooltips_class32", None,
                                          WS_POPUP | TTS_ALWAYSTIP | TTS_NOPREFIX,
                                          0, 0, 0, 0, self.hwnd, None, hinst, None)
            if self.tip:
                _u.SendMessageW(self.tip, TTM_SETMAXTIPWIDTH, 0, 480)

    def shown(self) -> bool:
        return bool(self.hwnd) and bool(_u.IsWindowVisible(self.hwnd))

    def show(self):
        if not self.hwnd:
            self.create()
        self.m.poll()
        self.place(force=True)
        _u.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
        _u.SetWindowPos(self.hwnd, ctypes.c_void_p(HWND_TOPMOST), 0, 0, 0, 0,
                        0x1 | 0x2 | SWP_NOACTIVATE)          # NOSIZE | NOMOVE
        _u.SetTimer(self.hwnd, 1, 1500, None)

    def hide(self):
        if self.hwnd:
            _u.KillTimer(self.hwnd, 1)
            _u.ShowWindow(self.hwnd, SW_HIDE)

    def post(self, fn):
        """Run `fn` on the window's thread (from another thread)."""
        with self.lock:
            self.queue.append(fn)
        if self.hwnd:
            _u.PostMessageW(self.hwnd, WM_RUN, 0, 0)

    def _painter(self):
        dpi = 96
        try:
            dpi = _u.GetDpiForWindow(self.hwnd) or 96
        except Exception:
            pass
        if self.p:
            self.p.close()
        self.p = Painter(dpi, dark_mode())

    # -- where it goes ------------------------------------------------------
    def _work_area(self, point=None):
        if point is None:
            mon = _u.MonitorFromPoint(W.POINT(0, 0), MONITOR_DEFAULTTOPRIMARY)
        else:
            mon = _u.MonitorFromPoint(W.POINT(*point), MONITOR_DEFAULTTONEAREST)
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        _u.GetMonitorInfoW(mon, ctypes.byref(mi))
        return mi.rcWork

    def _layout(self):
        dc = _u.GetDC(self.hwnd)
        try:
            self.lay = layout(self.m, self.p.px(self.width), self.most, self.p, dc)
        finally:
            _u.ReleaseDC(self.hwnd, dc)
        return self.lay

    def place(self, force=False):
        """Where you put it, else the bottom right of the main screen, above
        the taskbar; it stays on its screen."""
        if self.held and self.held["moving"]:
            return
        old = self.lay["size"] if self.lay else None
        w, h = self._layout()["size"]
        if not force and old == (w, h):
            _u.InvalidateRect(self.hwnd, None, False)
            self._tips()                # the same size, yet other rows: reordered, renamed
            return
        if self.spot:
            wa = self._work_area(self.spot)
            x = min(max(self.spot[0], wa.left), wa.right - w)
            y = min(max(self.spot[1], wa.top), wa.bottom - h)
        else:
            wa = self._work_area()
            x, y = wa.right - w - self.p.px(10), wa.bottom - h - self.p.px(10)
        _u.SetWindowPos(self.hwnd, ctypes.c_void_p(HWND_TOPMOST), x, y, w, h, SWP_NOACTIVATE)
        _u.InvalidateRect(self.hwnd, None, False)
        self._tips()

    def _save_place(self):
        try:
            self.place_file.parent.mkdir(parents=True, exist_ok=True)
            self.place_file.write_text(json.dumps({
                "x": self.spot[0] if self.spot else None, "y": self.spot[1] if self.spot else None,
                "width": self.width, "rows": self.most}), encoding="utf-8")
        except OSError as e:
            aht.warn(f"CORNER where the list goes was not saved: {e}")

    def _edges(self, x, y) -> int:
        """What a press at (x, y) takes hold of: its sides change its width;
        the edge away from where it sits (its top in the corner, else its
        bottom) how many sessions it lists; anywhere else moves it."""
        if not self.lay:
            return 0
        w, h = self.lay["size"]
        e, edge = 0, self.p.px(EDGE)
        if x < edge:
            e |= LEFT
        elif x >= w - edge:
            e |= RIGHT
        if self.spot is None and y < edge:
            e |= TOP
        elif self.spot is not None and y >= h - edge:
            e |= BOTTOM
        return e

    def _tips(self):
        """A note over each session, the top line and the ×.  Only what
        changed is told to the tooltip, in place: a note that shows stays
        up, and follows its session's text."""
        if not self.tip or not self.lay:
            return
        corner = "its top" if self.spot is None else "its bottom"
        items = [(self.lay["close"], "Hide the list (the aht tray menu brings it back)"),
                 (self.lay["head"], "Drag the list anywhere, its sides to change its width, "
                                    f"or {corner} to list more or fewer sessions; double-click "
                                    "this line to put it back in the corner; right-click "
                                    "to save, restore or restart the workspace")]
        items += [(tuple(rect), tip_text(r)) for r, rect in self.lay["rows"]]
        was = self.tips
        if items == was:
            return
        for i, (rect, text) in enumerate(items):
            old = was[i] if i < len(was) else None
            if old == (rect, text):
                continue
            buf = ctypes.create_unicode_buffer(text)
            ti = TOOLINFOW(ctypes.sizeof(TOOLINFOW), TTF_SUBCLASS, self.hwnd, i + 1, W.RECT(*rect),
                           None, ctypes.cast(buf, ctypes.c_wchar_p), 0)
            if old is None:
                _u.SendMessageW(self.tip, TTM_ADDTOOLW, 0, ctypes.addressof(ti))
                continue
            if old[1] != text:
                _u.SendMessageW(self.tip, TTM_UPDATETIPTEXTW, 0, ctypes.addressof(ti))
            if old[0] != rect:
                _u.SendMessageW(self.tip, TTM_NEWTOOLRECTW, 0, ctypes.addressof(ti))
        for i in range(len(items), len(was)):
            ti = TOOLINFOW(ctypes.sizeof(TOOLINFOW), 0, self.hwnd, i + 1)
            _u.SendMessageW(self.tip, TTM_DELTOOLW, 0, ctypes.addressof(ti))
        self.tips = items

    # -- what happens -------------------------------------------------------
    def tick(self):
        changed = self.m.poll()
        if self.restart_note and not self.m.note:
            # another note took its place and went: the restart's stays until it is through
            self.m.say(self.restart_note, float("inf"))
            changed = True
        if changed:
            self.place()

    def _row_at(self, x, y):
        for r, (a, b, c, d) in (self.lay or {}).get("rows", []):
            if a <= x < c and b <= y < d:
                return r
        return None

    def _in(self, rect, x, y):
        return rect[0] <= x < rect[2] and rect[1] <= y < rect[3]

    def click(self, x, y):
        if not self.lay:
            return
        if self._in(self.lay["close"], x, y):
            self.hooks["switch_off"]()
            return
        r = self._row_at(x, y)
        if r:
            self.act(r, "open" if r.kind == "away" else "goto")

    def act(self, r, what: str):
        """Do one thing to a session (`r` is None for what is about the whole
        list); what goes wrong shows under the top line."""
        if what == "hide":
            self.hooks["switch_off"]()
            return
        if what == "workspaces":
            self.hooks["open_window"](None, "workspaces")
            return
        if what == "save-workspace":
            self.save_workspace()
            return
        if what == "restart-workspace":
            self.restart_workspace()
            return
        if what == "take-back":
            self.hooks["open_window"](r.project, "take-back")
            return
        if what == "backups":
            _uid, root = aht.project_holding(r.project)
            if root:
                self.hooks["open_window"](root, "backups")
            else:
                self.say(f"{r.name}: its folder is in no project aht tracks")
            return
        if what == "backup-now":
            self.backup_now(r)
            return
        self.m.seen(r.id)
        self.tick()
        try:
            _u.AllowSetForegroundWindow(0xFFFFFFFF)      # what aht starts may come forward
        except Exception:
            pass
        if what == "goto":
            self._aside(r, lambda: aht.goto_session(str(r.pid)))
        elif what == "open":
            self._aside(r, lambda: aht.open_away(r.project))
        elif what == "branch":
            self.branch(r)
        elif what.startswith("send:"):
            self.send(r, what[5:])

    def _ahead(self, key, note, secs, look, answer, what):
        """An action's look ahead: `look()` aside (it asks the terminal or
        another machine), `note` under the top line meanwhile, then
        `answer(what it found)` on the window's thread.  `key` is in
        self.looking until `answer` returns, so a second click while the look
        ahead runs or its question is open does nothing: no second question."""
        if key in self.looking:
            return
        self.looking.add(key)

        def over(res):
            try:
                self._unsay(note)
                answer(res)
            finally:
                self.looking.discard(key)

        def run():
            try:
                res = look()
            except Exception as e:
                self.hooks["note"](what, e)
                res = {"blockers": [f"{type(e).__name__}: {e}"]}
            self.post(lambda: over(res))
        try:
            self.say(note, secs)
            threading.Thread(target=run, daemon=True).start()
        except Exception:
            self.looking.discard(key)
            raise

    def _unsay(self, note):
        """Take a note away, if it still is the one that shows (another
        action's may have taken its place)."""
        if self.m.note == note:
            self.m.note = None
            self.place()

    def branch(self, r: Row):
        """Branch…: its look ahead asks the terminal (PowerShell), so it runs
        aside; the name box then opens on the window's thread.  One name box
        at a time: with one open, that one comes to the front."""
        if ask_front():
            return
        self._ahead(("branch", r.pid), f"Getting “{r.name}” ready to branch…", 60,
                    lambda: aht.branch_session(str(r.pid)),
                    lambda dry: self._branch_name(r, dry), "the corner's Branch failed")

    def _branch_name(self, r: Row, dry: dict):
        if dry.get("blockers"):
            self.say(f"{r.name}: {dry['blockers'][0]}")
            return
        name = ask_text(self.hwnd, f"Branch “{r.name}”",
                        "The branch opens in a new tab with the conversation so far; "
                        "this session goes on as it is. Name of the new branch:",
                        dry["name"], "Branch", self.p.s if self.p else 1)
        if name is None:
            return
        self._aside(r, lambda: aht.branch_session(str(r.pid), name, apply=True))

    def restart_workspace(self):
        """Restart Workspace…: the look ahead aside (it asks the terminal),
        then the question, then aht saves the workspace, closes the terminal
        and opens it again with every tab.  The tray is no tab of the
        terminal, so its thread lives through that."""
        if self.restarting:
            return
        self._ahead("restart", "Looking at the workspace…", 60,
                    aht.restart_workspace, self._restart_answer,
                    "the corner's Restart Workspace failed")

    def _restart_answer(self, plan: dict):
        if not plan or not isinstance(plan, dict) or plan.get("blockers"):
            self.say(not_restarted(plan))
            return
        if self.restarting:
            return
        yes = self.hooks["ask"]("Restart Workspace", restart_question(plan), no_default=True)
        # the question's own loop runs what else was handed to this thread:
        # look again now that it is answered
        if not yes or self.restarting:
            return
        self.restarting = True
        # it stays until the result: closing and opening the terminal can take a minute
        self.restart_note = ("Restarting the workspace: closing "
                             + (plan.get("terminal") or "the terminal") + "…")
        self.say(self.restart_note, float("inf"))

        def go():
            try:
                res = aht.restart_workspace(apply=True)
            except Exception as e:
                self.hooks["note"]("the corner's Restart Workspace failed", e)
                res = {"blockers": [f"{type(e).__name__}: {e}"]}
            self.post(lambda: self._restarted(res))
        try:
            threading.Thread(target=go, daemon=True).start()
        except Exception:
            self._restarted({"blockers": ["the restart could not start"]})
            raise

    def _restarted(self, res: dict):
        """Restart Workspace is through: how many tabs opened again under the
        top line; what did not come back, and why, in a message and in the
        log."""
        self.restarting, self.restart_note = False, None
        self.say(restarted_text(res), 20)
        bad = restart_trouble(res)
        if bad:
            self.hooks["note"](f"Restart Workspace: {bad[0]}: " + bad[1].replace("\n\n", " "), None)
            self.hooks["tell"](*bad)

    def save_workspace(self):
        """Save Workspace Now: how much it holds, under the top line."""
        self.say("Saving the workspace…", 60)

        def go():
            try:
                res = aht.save_workspace_now()
            except Exception as e:
                self.hooks["note"]("the corner's Save Workspace failed", e)
                res = {"saved": None, "why": f"{type(e).__name__}: {e}"}
            self.post(lambda: self.say(saved_text(res)))
        threading.Thread(target=go, daemon=True).start()

    def backup_now(self, r: Row):
        """Back Up This Project Now: what it took, under the top line."""
        self.say(f"Backing up “{r.name}”…", 120)

        def go():
            uid, _root = aht.project_holding(r.project)
            if not uid:
                said = "its folder is in no project aht tracks"
            else:
                try:
                    x = (aht.backup_pass(only_uid=uid) or [{}])[0]
                except Exception as e:
                    self.hooks["note"]("the corner's backup failed", e)
                    x = {"status": "failed", "error": f"{type(e).__name__}: {e}"}
                said = ({"backed-up": f"backed up; it took {aht._human(x.get('added_bytes') or 0)}",
                         "unchanged": "nothing changed since its last backup",
                         "no-history": "no conversations to back up yet"}
                        .get(x.get("status")) or f"not backed up: {x.get('error') or 'see the log'}")
            self.post(lambda: self.say(f"{r.name}: {said}"))
        threading.Thread(target=go, daemon=True).start()

    def send(self, r: Row, to: str):
        self._ahead(("send", r.pid), f"Checking {to} for “{r.name}”…", 300,
                    lambda: aht.send_session(str(r.pid), to),
                    lambda res: self._send_answer(r, to, res), "the corner's Send to failed")

    def _send_answer(self, r, to, res):
        if res.get("blockers"):
            self.hooks["tell"](f"“{r.name}” cannot go to {to} now",
                               "\n\n".join(res["blockers"]))
            return
        if not self.hooks["ask"](f"Send to {to}", send_question(res)):
            return
        self._aside(r, lambda: aht.send_session(str(r.pid), to, apply=True))

    def _aside(self, r, fn):
        """`fn` on a thread of its own; its "why" or first blocker, if any,
        under the top line."""
        def go():
            try:
                res = fn() or {}
            except Exception as e:
                self.hooks["note"]("the session corner's action failed", e)
                res = {"why": f"{type(e).__name__}: {e}"}
            why = None
            if res.get("ok") is False:
                why = res.get("why") or "that did not work"
            elif res.get("blockers"):
                why = res["blockers"][0]
            if why:
                self.post(lambda: self.say(f"{r.name}: {why}"))
        threading.Thread(target=go, daemon=True).start()

    def say(self, text, secs=8):
        self.m.say(text, secs)
        self.place()

    def items(self, r=None) -> list:
        """What the right-click menu holds: a session's, or (r None) the
        list's own.  Restart Workspace is not offered while one runs, or
        while its look ahead or its question is open."""
        busy = self.restarting or "restart" in self.looking
        return menu_items(r, self.m.machines, busy) if r else list_items(busy)

    def menu(self, r=None):
        """The right-click menu: a session's, or (r None) the list's own."""
        items = self.items(r)
        h = _u.CreatePopupMenu()
        acts, default = {}, None
        for i, it in enumerate(items, 1):
            if it == "-":
                _u.AppendMenuW(h, MF_SEPARATOR, 0, None)
                continue
            label, act, is_default = it
            _u.AppendMenuW(h, MF_STRING | (0 if act else MF_GRAYED), i, label)
            acts[i] = act
            if is_default and act:
                default = i
        if default:
            _u.SetMenuDefaultItem(h, default, 0)
        pt = W.POINT()
        _u.GetCursorPos(ctypes.byref(pt))
        _u.SetForegroundWindow(self.hwnd)
        cmd = _u.TrackPopupMenu(h, TPM_RETURNCMD | TPM_RIGHTBUTTON | TPM_NONOTIFY, pt.x, pt.y, 0,
                                self.hwnd, None)
        _u.PostMessageW(self.hwnd, 0, 0, 0)
        _u.DestroyMenu(h)
        if acts.get(cmd):
            self.act(r, acts[cmd])

    def _cursor_at(self, x, y):
        e = self._edges(x, y)
        cur = (IDC_SIZENWSE if e in (TOP | LEFT, BOTTOM | RIGHT) else
               IDC_SIZENESW if e in (TOP | RIGHT, BOTTOM | LEFT) else
               IDC_SIZEWE if e & (LEFT | RIGHT) else IDC_SIZENS if e else IDC_ARROW)
        _u.SetCursor(_u.LoadCursorW(None, ctypes.c_void_p(cur)))

    def _press(self, x, y):
        pt = W.POINT()
        _u.GetCursorPos(ctypes.byref(pt))
        r = W.RECT()
        _u.GetWindowRect(self.hwnd, ctypes.byref(r))
        self.held = {"mouse": (pt.x, pt.y), "rect": (r.left, r.top, r.right, r.bottom),
                     "edges": self._edges(x, y), "width": self.width, "most": self.most,
                     "shown": min(self.most, len(self.m.rows)), "moved": False,
                     "moving": False, "at": (x, y)}
        _u.SetCapture(self.hwnd)

    def _drag(self):
        h = self.held
        pt = W.POINT()
        _u.GetCursorPos(ctypes.byref(pt))
        dx, dy = pt.x - h["mouse"][0], pt.y - h["mouse"][1]
        if not h["edges"]:
            if not h["moved"] and abs(dx) < _u.GetSystemMetrics(SM_CXDRAG) \
                    and abs(dy) < _u.GetSystemMetrics(SM_CYDRAG):
                return
            h["moved"] = h["moving"] = True
            _u.SetWindowPos(self.hwnd, None, h["rect"][0] + dx, h["rect"][1] + dy, 0, 0,
                            0x1 | SWP_NOZORDER | SWP_NOACTIVATE)
            return
        h["moved"] = True
        e = h["edges"]
        if e & (LEFT | RIGHT):
            wa = self._work_area((pt.x, pt.y))
            room = (wa.right - wa.left) / self.p.s - 20
            want = h["width"] + (-dx if e & LEFT else dx) / self.p.s
            self.width = round(max(150, min(want, 720, room)))
            if e & RIGHT:                                   # the left side stays
                self.spot = (h["rect"][0], h["rect"][1])
            elif self.spot is not None:
                self.spot = (h["rect"][2] - self.p.px(self.width), h["rect"][1])
        if e & (TOP | BOTTOM):
            n = max(0, h["shown"] + round((-dy if e & TOP else dy) / self.p.px(ROW)))
            self.most = n if n < len(self.m.rows) else max(len(self.m.rows), h["most"])
        self.place(force=True)

    def _let_go(self, x, y):
        h, self.held = self.held, None
        _u.ReleaseCapture()
        if not h:
            return
        if not h["moved"]:
            self.click(x, y)
        elif not h["edges"]:
            r = W.RECT()
            _u.GetWindowRect(self.hwnd, ctypes.byref(r))
            self.spot = (r.left, r.top)
            self._save_place()
            self.place(force=True)
        else:
            self._save_place()

    def _hover(self, x, y):
        row = self._row_at(x, y)
        key = row.id if row else None
        on_x = bool(self.lay) and self._in(self.lay["close"], x, y)
        if key != self.hover or on_x != self.hover_close:
            self.hover, self.hover_close = key, on_x
            _u.InvalidateRect(self.hwnd, None, False)
        if not self.tracking:
            tme = TRACKMOUSEEVENT(ctypes.sizeof(TRACKMOUSEEVENT), TME_LEAVE, self.hwnd, 0)
            self.tracking = bool(_u.TrackMouseEvent(ctypes.byref(tme)))

    def _paint(self):
        ps = PAINTSTRUCT()
        dc = _u.BeginPaint(self.hwnd, ctypes.byref(ps))
        try:
            lay = self.lay or self._layout()
            w, h = lay["size"]
            mem = _g.CreateCompatibleDC(dc)
            bmp = _g.CreateCompatibleBitmap(dc, w, h)
            old = _g.SelectObject(mem, bmp)
            paint(mem, self.m, lay, self.p, self.hover, self.hover_close)
            _g.BitBlt(dc, 0, 0, w, h, mem, 0, 0, SRCCOPY)
            _g.SelectObject(mem, old)
            _g.DeleteObject(bmp)
            _g.DeleteDC(mem)
        finally:
            _u.EndPaint(self.hwnd, ctypes.byref(ps))

    def _wndproc(self, hwnd, msg, wp, lp):
        try:
            if msg == WM_MOUSEACTIVATE:
                return MA_NOACTIVATE
            if msg == WM_ERASEBKGND:
                return 1
            if msg == WM_PAINT:
                self._paint()
                return 0
            if msg == WM_SETCURSOR and (lp & 0xFFFF) == HTCLIENT and not self.held:
                pt = W.POINT()
                _u.GetCursorPos(ctypes.byref(pt))
                _u.ScreenToClient(hwnd, ctypes.byref(pt))
                self._cursor_at(pt.x, pt.y)
                return 1
            if msg == WM_LBUTTONDOWN:
                self._press(_lo(lp), _hi(lp))
                return 0
            if msg == WM_MOUSEMOVE:
                if self.held:
                    self._drag()
                else:
                    self._hover(_lo(lp), _hi(lp))
                return 0
            if msg == WM_LBUTTONUP:
                self._let_go(_lo(lp), _hi(lp))
                return 0
            if msg == WM_CAPTURECHANGED:
                if self.held and self.held["moved"]:
                    self._let_go(-1, -1)
                self.held = None
                return 0
            if msg == WM_LBUTTONDBLCLK:
                x, y = _lo(lp), _hi(lp)
                if self.lay and self._in(self.lay["head"], x, y) \
                        and not self._in(self.lay["close"], x, y):
                    self.spot = None                    # back to the corner
                    self._save_place()
                    self.place(force=True)
                return 0
            if msg == WM_RBUTTONUP:                 # beside the sessions: the list's own menu
                self.menu(self._row_at(_lo(lp), _hi(lp)))
                return 0
            if msg == WM_MOUSELEAVE:
                self.tracking = False
                if self.hover or self.hover_close:
                    self.hover, self.hover_close = None, False
                    _u.InvalidateRect(hwnd, None, False)
                return 0
            if msg == WM_TIMER:
                self.tick()
                return 0
            if msg == WM_RUN:
                with self.lock:
                    todo, self.queue = self.queue, []
                for fn in todo:
                    try:
                        fn()
                    except Exception as e:      # the rest still runs: it may end a look ahead
                        self.hooks["note"]("the session corner's handed-over work", e)
                return 0
            if msg in (WM_DPICHANGED, WM_SETTINGCHANGE, WM_DISPLAYCHANGE):
                self._painter()
                self.place(force=True)
                return 0
            if msg == WM_CLOSE:
                self.hooks["switch_off"]()
                return 0
        except Exception as e:                  # the list stays; the log has it
            self.hooks["note"](f"the session corner (message {msg:#x})", e)
            return 0
        return _u.DefWindowProcW(hwnd, msg, wp, lp)


ASK_CLASS = "aht_corner_ask"
_asking = {}            # the name box that is open: {its window: what it holds}
_ask_proc = None        # its window procedure: made once, kept as long as the tray runs


def _ask_wndproc(hwnd, msg, wp, lp):
    """Every name box's window procedure.  The class is registered once, so
    it must not be one call's own: what a box holds is found by its window."""
    st = _asking.get(hwnd)
    if st is not None:
        if msg == WM_COMMAND and (wp & 0xFFFF) in (IDOK, IDCANCEL):
            if (wp & 0xFFFF) == IDOK:
                n = _u.GetWindowTextLengthW(st["edit"])
                buf = ctypes.create_unicode_buffer(n + 1)
                _u.GetWindowTextW(st["edit"], buf, n + 1)
                st["text"] = buf.value.strip() or None
            st["done"] = True
            return 0
        if msg == WM_CLOSE:
            st["done"] = True
            return 0
    return _u.DefWindowProcW(hwnd, msg, wp, lp)


def ask_front() -> bool:
    """Whether a name box is open; it then comes to the front."""
    for hwnd in list(_asking):
        _u.SetForegroundWindow(hwnd)
        return True
    return False


def ask_text(owner, title: str, prompt: str, value: str, ok: str, s: float = 1.0):
    """A small window that asks for one line of text: what was typed, or None
    for Cancel.  One at a time: while one is open a second call brings that
    one to the front and returns None."""
    global _ask_proc
    if ask_front():
        return None
    hinst = _k.GetModuleHandleW(None)
    if _ask_proc is None:
        _ask_proc = WNDPROC(_ask_wndproc)
        wc = WNDCLASSW()
        wc.lpfnWndProc = _ask_proc
        wc.hInstance = hinst
        wc.hCursor = _u.LoadCursorW(None, ctypes.c_void_p(IDC_ARROW))
        wc.hbrBackground = ctypes.c_void_p(16)      # COLOR_BTNFACE + 1
        wc.lpszClassName = ASK_CLASS
        _u.RegisterClassW(ctypes.byref(wc))
    px = lambda v: round(v * s)                     # noqa: E731
    w, h = px(420), px(170)
    pt = W.POINT()
    _u.GetCursorPos(ctypes.byref(pt))
    mon = _u.MonitorFromPoint(pt, MONITOR_DEFAULTTONEAREST)
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    _u.GetMonitorInfoW(mon, ctypes.byref(mi))
    wa = mi.rcWork
    x, y = (wa.left + wa.right - w) // 2, (wa.top + wa.bottom - h) // 2
    dlg = _u.CreateWindowExW(WS_EX_DLGMODALFRAME | WS_EX_TOPMOST, ASK_CLASS, title,
                             WS_POPUP | WS_CAPTION | WS_SYSMENU, x, y, w, h, None, None, hinst, None)
    if not dlg:
        aht.warn(f"CORNER the name box did not open (error {ctypes.get_last_error()})")
        return None
    st = _asking[dlg] = {"text": None, "done": False, "edit": None}
    font = _g.CreateFontW(-px(12), 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, "Segoe UI")
    quit_code = None
    try:
        m = px(14)
        cw = w - 2 * m - px(6)
        ctl = [_u.CreateWindowExW(0, "STATIC", prompt, WS_CHILD | WS_VISIBLE, m, m, cw, px(44),
                                  dlg, None, hinst, None)]
        st["edit"] = _u.CreateWindowExW(WS_EX_CLIENTEDGE, "EDIT", value,
                                        WS_CHILD | WS_VISIBLE | WS_TABSTOP | ES_AUTOHSCROLL,
                                        m, m + px(50), cw, px(24), dlg, None, hinst, None)
        bw, bh = px(88), px(26)
        by = m + px(86)
        ctl += [st["edit"],
                _u.CreateWindowExW(0, "BUTTON", ok, WS_CHILD | WS_VISIBLE | WS_TABSTOP |
                                   BS_DEFPUSHBUTTON, m + cw - 2 * bw - px(8), by, bw, bh, dlg,
                                   ctypes.c_void_p(IDOK), hinst, None),
                _u.CreateWindowExW(0, "BUTTON", "Cancel", WS_CHILD | WS_VISIBLE | WS_TABSTOP |
                                   BS_PUSHBUTTON, m + cw - bw, by, bw, bh, dlg,
                                   ctypes.c_void_p(IDCANCEL), hinst, None)]
        for c in ctl:
            _u.SendMessageW(c, WM_SETFONT, font or 0, 1)
        _u.ShowWindow(dlg, 5)
        _u.SetForegroundWindow(dlg)
        _u.SetFocus(st["edit"])
        _u.SendMessageW(st["edit"], EM_SETSEL, 0, -1)
        msg = W.MSG()
        while not st["done"] and _u.IsWindow(dlg):
            got = _u.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if got == 0:                    # the tray was told to quit while the box is open
                quit_code = int(msg.wParam) & 0x7FFFFFFF
                break
            if got < 0:
                break
            if not _u.IsDialogMessageW(dlg, ctypes.byref(msg)):
                _u.TranslateMessage(ctypes.byref(msg))
                _u.DispatchMessageW(ctypes.byref(msg))
    finally:
        _asking.pop(dlg, None)
        if _u.IsWindow(dlg):
            _u.DestroyWindow(dlg)
        if font:
            _g.DeleteObject(font)
        if quit_code is not None:
            # this loop took the quit that was meant for the tray's own: hand
            # it on, or the tray would stay, with no icon
            _u.PostQuitMessage(quit_code)
    return st["text"]
