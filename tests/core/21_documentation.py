#!/usr/bin/env python3
"""[21] the documentation covers everything."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)

print("\n[21] the documentation covers everything")
import re as _re
guide = (HERE.parent / "GUIDE.md").read_text()
heads = [l[3:].strip().lower() for l in guide.splitlines() if l.startswith("## ")]
swift = (HERE.parent / "macos" / "tray.swift").read_text()
topics = set(_re.findall(r'HelpButton\("([^"]+)"\)', swift)) \
    | set(_re.findall(r'headed\([^\n]*?, "([^"]+)"\)', swift)) \
    | set(_re.findall(r'topic: "([^"]+)"', swift))
lost = sorted(t for t in topics if not any(h.startswith(t.lower()) for h in heads))
ck(topics and not lost, f"every ? in the window opens a section of the guide ({lost})")
sys.path.insert(0, str(HERE.parent))
import aht as _core
subs = [a for a in _core.build_parser()._actions
        if a.__class__.__name__ == "_SubParsersAction"][0].choices
ck(not [n for n in subs if not n.startswith("_") and f"aht {n}" not in guide],
   "every command is in the guide")
loose = _re.findall(r'"--(store|task|rename|relink|remove-history|show|to)", '
                   r'(?:t\.key|task|sid|dst|j\[|name)', swift)
ck(not loose, f"the window glues values to their options, so a value may begin with a dash ({loose})")
r = run("bind", "--store=-Users-nobody-gone", "--to=/nonexistent")
ck("expected one argument" not in r.stderr, "bind --store=<name beginning with a dash> is read right")
ck(not [k for k in _core.CONFIG_DEFAULTS if f"`{k}`" not in guide],
   f"every setting is in the guide ({[k for k in _core.CONFIG_DEFAULTS if f'`{k}`' not in guide]})")

# a project's sessions: newest work first, each branch under its origin
from datetime import datetime as _dt, timezone as _tz
projS = os.path.realpath(str(roots / "projS"))
os.makedirs(projS)
stS = tools / "claude" / enc(projS)
stS.mkdir()
cl = lambda **k: json.dumps(k, separators=(",", ":")) + "\n"
utc = lambda *a: _dt(*a, tzinfo=_tz.utc).timestamp()
sidS = {c: f"{c * 8}-0000-4000-8000-000000000001" for c in "abcde"}
def sess(c, lines, when):
    f = stS / f"{sidS[c]}.jsonl"
    f.write_text("".join(lines))
    os.utime(f, (when, when))
def copied(c):                  # what /branch copies of session c
    return [cl(**dict(json.loads(x), forkedFrom={"sessionId": sidS[c], "messageUuid": "m"}))
            for x in (stS / f"{sidS[c]}.jsonl").read_text().splitlines()]
own = lambda title, when: [cl(type="custom-title", customTitle=title),
                           cl(type="user", timestamp=when, message={"role": "user", "content": "go"})]
sess("a", [cl(type="user", timestamp="2026-10-01T10:00:00Z", message={"role": "user", "content": "start"}),
           cl(type="ai-title", aiTitle="Main")], utc(2026, 10, 1, 12))
sess("b", copied("a") + own("Side", "2026-10-02T09:00:00Z"), utc(2026, 10, 2, 12))
sess("c", copied("b") + own("Side of side", "2026-10-03T08:00:00Z"), utc(2026, 10, 3, 12))
sess("d", [cl(type="user", timestamp="2026-09-20T10:00:00Z", message={"role": "user", "content": "old"},
              forkedFrom={"sessionId": "ffffffff-0000-4000-8000-000000000009", "messageUuid": "m"})]
     + own("Orphan", "2026-10-04T08:00:00Z"), utc(2026, 10, 4, 12))
sess("e", [cl(type="user", timestamp="2026-09-30T08:00:00Z", message={"role": "user", "content":
           '"forkedFrom":{"sessionId":"' + sidS["a"] + '"} only quoted here'}),
           cl(type="ai-title", aiTitle="Mentions it")], utc(2026, 9, 30, 12))
rowsS = JS("sessions", projS, "--json").get("sessions", [])
byS = {r["id"][0]: r for r in rowsS}
ck([(r["id"][0], r["depth"]) for r in rowsS] == [("d", 0), ("a", 0), ("b", 1), ("c", 2), ("e", 0)],
   f"sessions of a project: newest work first, branches under their origin "
   f"({[(r['id'][0], r['depth']) for r in rowsS]})")
ck(byS["b"]["parent"] == sidS["a"] and byS["c"]["parent"] == sidS["b"]
   and byS["b"]["title"] == "Side"
   and byS["b"]["branched"] == utc(2026, 10, 2, 9)
   and byS["d"]["parent_gone"] and byS["d"]["branched"] and not byS["e"]["branched"],
   f"sessions: a branch knows its origin and when it branched; words in a message make no "
   f"branch ({ {k: (v['parent'] and v['parent'][0], v['branched'], v['parent_gone']) for k, v in byS.items()} })")
r = run("sessions", projS)
ck(r.returncode == 0 and "    ⑂ Side" in r.stdout and "        ⑂ Side of side" in r.stdout
   and "5 session(s)" in r.stdout and "3 of them branches" in r.stdout,
   "sessions of a project in the terminal: branches indented under their origin")
sidS["f"] = "ffffffff-0000-4000-8000-000000000001"
sess("f", [cl(type="user", timestamp="2026-10-05T08:00:00Z",
              message={"role": "user", "content": "picture " + "A" * 1_200_000},
              forkedFrom={"sessionId": sidS["a"], "messageUuid": "m"})]
     + own("Big picture", "2026-10-05T09:00:00Z"), utc(2026, 10, 5, 12))
rowF = next((r for r in JS("sessions", projS, "--json").get("sessions", [])
             if r["id"] == sidS["f"]), {})
ck(rowF.get("parent") == sidS["a"] and rowF.get("depth") == 1
   and rowF.get("branched") == utc(2026, 10, 5, 9),
   f"sessions: a branch whose first copied entry is over 1 MB (a pasted picture) is still "
   f"a branch ({ {k: rowF.get(k) for k in ('parent', 'depth', 'branched')} })")
(stS / f"{sidS['f']}.jsonl").unlink()

# first-time setup: folders to watch, projects found, the answers kept
projU = os.path.realpath(str(roots / "projU"))
os.makedirs(projU)
mkstores(projU)
projO = os.path.realpath(str(sb / "elsewhere" / "projO"))
os.makedirs(projO)
(tools / "claude" / enc(projO)).mkdir()
(tools / "claude" / enc(projO) / "o1.jsonl").write_text(json.dumps({"cwd": projO}) + "\n")
plan = JS("setup", "--json")
ck(any(r["path"] == os.path.realpath(str(roots)) and r["chosen"] and r["watched"]
       for r in plan.get("roots", []))
   and projU in [x["path"] for x in plan.get("projects", [])]
   and "Claude Code" in next(x["agents"] for x in plan["projects"] if x["path"] == projU)
   and projO in plan.get("elsewhere", []) and plan.get("done") is False,
   f"setup: the watched folder, a project there not yet tracked, one elsewhere ({plan})")
# a HOME of its own as well: should the watched folders change, the reload
# writes the watcher's LaunchAgent (or unit) under HOME, never the real one
safe_home = {"HOME": str(sb / "setup-home")}
(sb / "setup-home").mkdir()
sw = JS("setup", "--apply", "--adopt", projU, "--moves", "apply", "--badges", "off",
        "--update-check", "on", "--json", extra_env=safe_home)
cfgS = JS("config", "--json").get("explicit", {})
plan2 = JS("setup", "--json")
ck(sw.get("adopted") == [projU] and cfgS.get("move_policy") == "apply"
   and cfgS.get("icons_enabled") is False and cfgS.get("update_check") is True
   and plan2.get("done") is True and projU not in [x["path"] for x in plan2["projects"]]
   and os.path.isfile(os.path.join(projU, ".aht", ".project-id")),
   f"setup --apply: takes on the chosen project and keeps the answers ({sw}, {cfgS})")
sw = JS("setup", "--apply", "--roots", str(roots), str(sb / "elsewhere"), "--adopt", "--json",
        extra_env=safe_home)
ck(JS("config", "--json").get("explicit", {}).get("watch_roots")
   == [os.path.realpath(str(roots)), os.path.realpath(str(sb / "elsewhere"))]
   and sw.get("adopted") == [], "setup --apply --roots: the chosen folders are watched; "
   "--adopt with nothing takes on none")
for k in ("watch_roots", "move_policy", "icons_enabled", "update_check"):
    run("config", "--unset", k)

# new_policy is gone: aht always takes on a new project.  An old config's
# value is ignored and not shown, an old script's --set or --news does not
# fail, and no JSON carries it
ne = iso_env("newpolicy")
ncode = Path(ne["HOME"]) / "code"
fresh = ncode / "fresh"
(fresh / ".aht").mkdir(parents=True)
fuid = "0f0f0f0f-1111-4222-8333-444444444444"
(fresh / ".aht" / ".project-id").write_text(fuid + "\n")
fresh = os.path.realpath(str(fresh))
Path(ne["AHT_HOME"]).mkdir(parents=True)
(Path(ne["AHT_HOME"]) / "config.json").write_text(json.dumps({"new_policy": "ignore"}))
def njs(*a, stdin=None):
    try:
        return json.loads(iso_run(ne, *a, stdin=stdin).stdout)
    except ValueError:
        return {}
def nprojects():
    return [p["real_path"] for p in njs("projects", "--json").get("projects", [])]
rset = iso_run(ne, "config", "--set", "new_policy=ask", "--json")
ncfg = njs("config", "--json")
dry = njs("reconcile", "--roots", str(ncode))
after_dry = nprojects()
rec = njs("reconcile", "--notify", "--news", "ignore", "--roots", str(ncode))
rsetup = iso_run(ne, "setup", "--apply", "--news", "ask", "--adopt", "--json")
ck(rset.returncode == 0 and "new_policy is no longer used" in rset.stderr
   and "new_policy" not in ncfg.get("effective", {}) and "new_policy" not in ncfg.get("explicit", {})
   and "new_policy" not in ncfg.get("defaults", {})
   and [n["path"] for n in dry.get("news", [])] == [fresh] and after_dry == []
   and rec.get("applied") and nprojects() == [fresh]
   and "news" not in rec.get("policies", {}) and rsetup.returncode == 0
   and "news" not in json.loads(rsetup.stdout or "{}").get("policies", {"news": 1})
   and "news" not in njs("setup", "--json").get("policies", {"news": 1})
   and "news" not in njs("status", "--json").get("policies", {"news": 1})
   and "--news" not in iso_run(ne, "setup", "--help").stdout
   and "--news" not in iso_run(ne, "reconcile", "--help").stdout,
   f"new projects: always taken on; new_policy and --news are ignored, not shown "
   f"({rset.returncode} {rset.stderr.strip()!r}, {rec.get('policies')}, {after_dry})")
# Forget sticks: the folder keeps its marker (the front-ends do not remove
# it), and the next scan leaves it alone; a session there takes it on again
iso_run(ne, "forget", "--uuid", fuid, "--apply")
r1 = njs("reconcile", "--notify", "--roots", str(ncode))
r2 = njs("reconcile", "--apply", "--roots", str(ncode))
gone_after = nprojects()
iso_run(ne, "hook", stdin=json.dumps({"cwd": fresh}))
nreg = json.loads((Path(ne["AHT_HOME"]) / "registry.json").read_text())
ck(gone_after == [] and r1.get("news") == [] and r2.get("news") == []
   and (Path(fresh) / ".aht" / ".project-id").is_file()
   and nprojects() == [fresh] and fuid not in (nreg.get("forgotten") or {}),
   f"forget: the scan does not take a forgotten folder on again; a session there does "
   f"({gone_after}, {r1.get('news')}, {nprojects()})")
# setting up again offers a forgotten project, marked and not ticked: only
# ticking it (--adopt) takes it on again, not a setup that takes on all
iso_run(ne, "forget", "--uuid", fuid, "--apply")
srow = next((p for p in njs("setup", "--json").get("projects", []) if p["path"] == fresh), {})
# adopt still takes it on (a way back), but says which one it is first
aplan = njs("adopt", "--json").get("planned", [])
arow = next((a for a in aplan if a["real"] == fresh), {})
atext = iso_run(ne, "adopt").stdout
ck(arow.get("forgotten") is True and all(a.get("forgotten") is False for a in aplan if a is not arow)
   and "(you told aht to forget it)" in atext
   and core.forgotten_note([arow])
   == f"You told aht to forget {core.tilde_path(fresh)}: adopting takes it on again."
   and core.forgotten_note([{"forgotten": True}, {"forgotten": False}, {"forgotten": True}])
   == "You told aht to forget 2 of them: adopting takes them on again."
   and core.forgotten_note([{"forgotten": False}]) == "",
   f"adopt: a forgotten project is marked, so the question before it can say so ({aplan})")
sall = njs("setup", "--apply", "--json")
after_all = nprojects()
other = ncode / "other"
(other / ".aht").mkdir(parents=True)
(other / ".aht" / ".project-id").write_text("0f0f0f0f-5555-4666-8777-888888888888\n")
other = os.path.realpath(str(other))
stext = iso_run(ne, "setup").stdout
s2 = njs("setup", "--apply", "--adopt", fresh, "--adopt", other, "--json")
ck(srow.get("forgotten") is True and sall.get("adopted") == [] and after_all == []
   and "you told aht to forget it" in stext
   and sorted(s2.get("adopted", [])) == sorted([fresh, other])
   and sorted(nprojects()) == sorted([fresh, other]),
   f"setup: a forgotten project is offered unticked; --adopt A --adopt B takes on both "
   f"({srow}, {sall.get('adopted')}, {s2.get('adopted')})")
# every list option adds up when given twice
import argparse as _ap
lists = [f"{n} {o.option_strings[0]}"
         for a in core.build_parser()._actions if isinstance(a, _ap._SubParsersAction)
         for n, sp in a.choices.items() for o in sp._actions
         if o.option_strings and o.nargs in ("*", "+") and not isinstance(o, _ap._ExtendAction)]
iso_run(ne, "config", "--set", "chimes=true", "--set", "session_corner=true", "--no-reload")
nexp = njs("config", "--json").get("explicit", {})
ck(not lists and nexp.get("chimes") is True and nexp.get("session_corner") is True,
   f"a list option given twice adds up (config --set a --set b) ({lists}, {nexp})")

# the folders to watch as they are spelled on disk (a Mac ignores case, so
# ~/code also opens ~/Code), none of the system's own, and setup's JSON alone
# on stdout when the watcher reloads
ce = iso_env("casehome")
ch = Path(ce["HOME"])
for d in ("Desktop", "Documents", "Code/app", "AppData/Local/Temp/try"):
    (ch / d).mkdir(parents=True)
capp, ctry = str(ch / "Code" / "app"), str(ch / "AppData" / "Local" / "Temp" / "try")
cst = Path(ce["AHT_ROOT_CLAUDE"])
for p in (capp, ctry, str(ch)):        # the last: a session started in the home folder
    (cst / enc(p)).mkdir()
    (cst / enc(p) / "s1.jsonl").write_text(json.dumps({"cwd": p}) + "\n")
iso_run(ce, "config", "--set", "watcher_owner=none", "--no-reload")
def cjs(*a, **kw):
    try:
        return json.loads(iso_run(ce, *a, **kw).stdout)
    except ValueError:
        return {}
plan = cjs("setup", "--json")
byr = {r["path"]: r for r in plan.get("roots", [])}
ck(byr.get(str(ch / "Code"), {}).get("projects") == 1 and str(ch / "code") not in byr
   and plan.get("elsewhere") == [ctry] and not [r for r in byr if "AppData" in r],
   f"setup: ~/Code as spelled on disk, ~/AppData never offered ({sorted(byr)}, "
   f"{plan.get('elsewhere')})")
blind = os.path.isdir(str(ch / "code"))
r = iso_run(ce, "setup", "--apply", "--json", "--roots", str(ch / "Desktop"),
            str(ch / ("code" if blind else "Code")))
try:
    sj = json.loads(r.stdout)
except ValueError:
    sj = {}
ck(r.returncode == 0 and sj.get("adopted") == [capp] and sj.get("watcher_reloaded") is False
   and sj.get("roots") == [str(ch / "Desktop"), str(ch / "Code")]
   and "nothing to reload" in r.stderr,
   f"setup --apply --json: other folders, the reload's words on stderr, the JSON alone "
   f"on stdout ({r.stdout[:300]} | {r.stderr[-300:]})")
r = iso_run(ce, "hook", stdin=json.dumps({"cwd": capp, "transcript_path":
                                          str(cst / enc(capp) / "t.jsonl")}))
creg = json.loads((Path(ce["AHT_HOME"]) / "registry.json").read_text())["projects"]
ck(r.returncode == 0 and [e["real_path"] for e in creg.values()] == [capp],
   f"hook: a project taken on under ~/Code keeps its one identity ({creg})")
corph = [o["store"] for o in cjs("orphans", "--json").get("orphans", [])]
cdoc = {c["check"]: c for c in cjs("doctor", "--json").get("checks", [])}
ctidy = [o["store"] for o in cjs("tidy", "--json").get("orphans", [])]
ck(corph == [enc(ctry)] and ctidy == [enc(ctry)]
   and cdoc.get("no orphan claude stores", {}).get("detail") == "1 orphan(s)"
   and cjs("status", "--json").get("orphan_claude_stores") == 1,
   f"the home folder's own history is no orphan ({corph}, {ctidy})")
if blind:
    # a watched folder typed in another case (the watcher's folders after a
    # case-only rename in Finder, AHT_ROOTS, --roots) finds ~/Code/app where
    # it is: no move, so the hook does not relink it back every time
    def cjson(r):
        try:
            return json.loads(r.stdout)
        except ValueError:
            return {}
    lenv = dict(ce, AHT_ROOTS=str(ch / "code"))
    rc1 = cjson(iso_run(ce, "reconcile", "--apply", "--roots", str(ch / "code"),
                        str(ch / "Code")))
    rc2 = cjson(iso_run(lenv, "reconcile", "--apply"))
    wr = cjson(iso_run(lenv, "config", "--json")).get("effective", {}).get("watch_roots")
    creg = json.loads((Path(ce["AHT_HOME"]) / "registry.json").read_text())["projects"]
    ck(all(x.get("applied") and x.get("respelled") == [] and x.get("moves") == []
           and x.get("copies") == [] for x in (rc1, rc2))
       and [e["real_path"] for e in creg.values()] == [capp] and wr == [str(ch / "Code")],
       f"reconcile: a watched folder spelled otherwise than on disk moves nothing "
       f"({rc1.get('respelled')}, {rc2.get('respelled')}, {wr}, {creg})")
    # Windows records C:\code\App's history as ...-code-App while the folder
    # on disk is still ...-code-app: the project's own history, no orphan
    cown = enc(capp)
    calt = cown.replace("-Code-", "-code-")
    ctr = Path(ce["HOME"]).parent / "trash"
    os.rename(cst / cown, cst / calt)
    try:
        corph = [o["store"] for o in cjs("orphans", "--json").get("orphans", [])]
        ctidy = [o["store"] for o in cjs("tidy", "--json").get("orphans", [])]
        r = iso_run(dict(ce, AHT_TRASH=str(ctr)), "tidy", "--remove-history=" + calt, "--apply")
        # and where the names are compared by case, the same folder is still refused
        probe = ("import sys, json; sys.path.insert(0, sys.argv[1]); import aht; "
                 "aht.CASE_BLIND = False; "
                 "print(json.dumps(aht.remove_orphan_history(sys.argv[2], apply=True)))")
        pr = subprocess.run([PY, "-c", probe, str(HERE.parent), calt], capture_output=True,
                            text=True, env=dict(ce, AHT_TRASH=str(ctr)))
        try:
            pj = json.loads(pr.stdout)
        except ValueError:
            pj = {}
        ck(corph == [enc(ctry)] and ctidy == [enc(ctry)] and r.returncode == 3
           and pj.get("applied") is False and pj.get("blockers") and (cst / calt).is_dir()
           and not ctr.exists(),
           f"orphans, tidy: a store spelled on disk in another case is still the project's, "
           f"and never goes to the Trash ({corph}, {ctidy}, {r.returncode}, {pj})")
    finally:
        for c in (cst / calt, ctr / calt):  # (out of the stand-in Trash, should it be there)
            if c.is_dir():
                os.rename(c, cst / cown)
                break
# a drive without file ids (some Windows ones give every file id 0 on one
# volume): a copy is not the folder it was copied from, so the hook does not
# take it for a move; the same path is still the same folder
nid = Path(os.path.realpath(sb)) / "noid"
(nid / "proj").mkdir(parents=True)
(nid / "proj-copy").mkdir()
_stat = os.stat
def _noid_stat(p, *a, **kw):
    st = _stat(p, *a, **kw)
    return os.stat_result((st.st_mode, 0, 7) + tuple(st)[3:10])
os.stat = _noid_stat
try:
    nsame = [core._same_folder(str(nid / "proj"), str(nid / "proj-copy")),
             core._same_folder(str(nid / "proj"), str(nid / "proj") + os.sep + "."),
             core._folder_key(str(nid / "proj")) == core._folder_key(str(nid / "proj-copy"))]
finally:
    os.stat = _stat
ck(nsame == [False, True, False] and core._same_folder(str(nid / "proj"), str(nid / "proj"))
   and not core._same_folder(str(nid / "proj"), str(nid / "proj-copy")),
   f"no file ids: a copy is another folder, as _folder_key says ({nsame})")
if sys.platform == "darwin":            # a real reload, against the stand-in launchctl
    if shutil.which("launchctl", path=ce["PATH"]) != str(FAKEBIN / "launchctl"):
        ck(False, f"the stand-in launchctl comes first ({shutil.which('launchctl', path=ce['PATH'])})")
    else:
        iso_run(ce, "config", "--unset", "watcher_owner")
        # aht.app or Homebrew's aht before `aht install`: no watcher to restart,
        # so no LaunchAgent for one
        plist = ch / "Library" / "LaunchAgents" / "com.aht.watcher.plist"
        log0 = (FAKEBIN / "calls.log").read_text() if (FAKEBIN / "calls.log").is_file() else ""
        r = iso_run(ce, "reload")
        calls = (FAKEBIN / "calls.log").read_text() if (FAKEBIN / "calls.log").is_file() else ""
        ck(r.returncode == 0 and "not installed yet" in r.stdout and "aht install" in r.stdout
           and not plist.exists() and calls == log0,
           f"reload: a watcher that is not installed is not started ({r.stdout.strip()})")
        # the app's Quick Setup: new folders, and still no LaunchAgent; the
        # reason on stderr, the JSON alone on stdout
        r = iso_run(ce, "setup", "--apply", "--json", "--roots", str(ch / "Desktop"),
                    str(ch / "Documents"), str(ch / "Code"))
        calls = (FAKEBIN / "calls.log").read_text() if (FAKEBIN / "calls.log").is_file() else ""
        try:
            sj = json.loads(r.stdout)
        except ValueError:
            sj = {}
        ck(r.returncode == 0 and sj.get("watcher_reloaded") is False and not plist.exists()
           and calls == log0 and "not installed yet" in r.stderr,
           f"setup --apply --json: no watcher installed, so none is started "
           f"({r.stdout[:200]} | {r.stderr[-300:]})")
        # back to the folders before, so the setup below changes them again
        iso_run(ce, "config", "--set", "watch_roots=" + json.dumps([str(ch / "Desktop"),
                                                                    str(ch / "Code")]),
                "--no-reload")
        cw = ch / ".aht" / "tools" / "agent-history-tether" / "watcher"
        cw.parent.mkdir(parents=True)
        cw.write_text("#!/bin/sh\n")            # stands in for the installed watcher
        r = iso_run(ce, "setup", "--apply", "--json", "--roots", str(ch / "Desktop"),
                    str(ch / "Documents"), str(ch / "Code"))
        calls =(FAKEBIN / "calls.log").read_text() if (FAKEBIN / "calls.log").is_file() else ""
        try:
            sj = json.loads(r.stdout)
        except ValueError:
            sj = {}
        ck(r.returncode == 0 and sj.get("watcher_reloaded") is True and plist.is_file()
           and str(ch / "Documents") in plist.read_text() and "bootstrap" in calls,
           f"setup --apply --json: the watcher restarts with the new folders "
           f"({r.stdout[:200]} | {r.stderr[-300:]})")
        # Settings > Watched folders in the app: config --set, with JSON
        r = iso_run(ce, "config", "--json", "--set",
                    "watch_roots=" + json.dumps([str(ch / "Desktop"), str(ch / "Code")]))
        try:
            cj = json.loads(r.stdout)
        except ValueError:
            cj = {}
        ck(r.returncode == 0 and cj.get("effective", {}).get("watch_roots")
           == [str(ch / "Desktop"), str(ch / "Code")]
           and str(ch / "Documents") not in plist.read_text()
           and "reloaded" in r.stderr,
           f"config --set watch_roots --json: the watcher restarts, the JSON alone on "
           f"stdout ({r.stdout[:200]} | {r.stderr[-300:]})")
        iso_run(ce, "config", "--set", "watcher_owner=none", "--no-reload")

if sys.platform == "darwin":
    # the Mac installer under a home whose name has a space, a $, a backtick
    # and a quote: the hook and the `aht` command quote their paths, an older
    # unquoted hook entry is replaced, a second install finds its own (quoted)
    # entries and the uninstaller removes them, keeping other tools' hooks.
    # Only install_hook, install_command (into a folder of the sandbox) and
    # remove_hook run: nothing that reaches launchd
    he = iso_env("odd home $HOME q`b'c")
    hh = Path(he["HOME"])
    htools = hh / ".aht" / "tools" / "agent-history-tether"
    htools.mkdir(parents=True)
    shutil.copy2(CLI, htools / "aht.py")
    (hh / "bin").mkdir()
    hk = lambda c: [{"type": "command", "command": c, "timeout": 10}]
    hold = "/usr/bin/python3 %s hook" % (htools / "aht.py")     # as older versions wrote it
    (hh / ".claude").mkdir()
    (hh / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"SessionStart": [
        {"matcher": "startup", "hooks": hk(hold)}, {"matcher": "resume", "hooks": hk(hold)},
        {"matcher": "startup", "hooks": hk("echo mine")}]}}))
    probe = ("import json, os, sys; sys.path.insert(0, sys.argv[1]); import install, uninstall\n"
             "s = lambda: json.load(open(install.SETTINGS))['hooks']['SessionStart']\n"
             "install.install_hook(); once = s()\n"
             "install.install_hook(); twice = s()\n"
             "uninstall.remove_hook(); gone = s()\n"
             "install.COMMAND_DIRS = [install.HOME / 'bin']\n"
             "os.environ['PATH'] = str(install.HOME / 'bin') + os.pathsep + '/usr/bin:/bin'\n"
             "install.install_command()\n"
             "print(json.dumps([install.PY, str(install.SCRIPT), install.HOOK_CMD, once, twice, gone]))")
    r = subprocess.run([PY, "-c", probe, str(HERE.parent)], env=he, capture_output=True, text=True)
    try:
        hpy, hscript, hcmd, once, twice, gone = json.loads(r.stdout.splitlines()[-1])
    except (ValueError, IndexError):
        hpy = hscript = hcmd = ""
        once = twice = gone = []
        print(r.stdout[-600:], r.stderr[-600:])
    import shlex
    try:
        words = shlex.split(hcmd)
    except ValueError:
        words = None
    ck(words == [hpy, hscript, "hook"] and hscript == str(htools / "aht.py"),
       f"install.py: the hook command is shell-quoted ({hcmd})")
    ours = lambda groups: [g.get("matcher") for g in groups
                           if any(h["command"] == hcmd for h in g["hooks"])]
    mine = lambda groups: sum(h["command"] == "echo mine" for g in groups for h in g["hooks"])
    ck(sorted(ours(once)) == ["fork", "resume", "startup"] and len(once) == 4 and mine(once) == 1,
       f"install.py: the hook entries an older version wrote are replaced, others kept ({once})")
    ck(twice == once, "install.py: installing again finds its own (quoted) entries")
    ck(gone and not ours(gone) and mine(gone) == 1 and len(gone) == 1,
       f"uninstall.py: the quoted entries go, others stay ({gone})")
    w = subprocess.run(["/bin/bash", str(hh / "bin" / "aht"), "version"], env=he,
                       capture_output=True, text=True)
    ck(w.returncode == 0 and w.stdout.strip(),
       f"install.py: the `aht` command runs aht from that home ({w.stdout.strip()} {w.stderr[-300:]})")

    # the three plists install.py writes, under a home and a watched folder
    # with a & and a <: every value escaped, so launchd can read them.  Only
    # the writers run (a stand-in watcher program lets write_plist start),
    # nothing that reaches launchd
    pe = iso_env("plist & <home>")
    ph = Path(pe["HOME"])
    proot = ph / "R&D <x>"
    proot.mkdir()
    Path(pe["AHT_HOME"]).mkdir(parents=True, exist_ok=True)
    (Path(pe["AHT_HOME"]) / "config.json").write_text(json.dumps({"watch_roots": [str(proot)]}))
    ptools = ph / ".aht" / "tools" / "agent-history-tether"
    ptools.mkdir(parents=True)
    (ptools / "watcher").write_text("#!/bin/sh\n")
    pexe = str(ph / "Tools & <Apps>" / "aht.app" / "Contents" / "MacOS" / "aht-tray")
    probe = ("import json, sys; sys.path.insert(0, sys.argv[1]); import install\n"
             "install.write_plist(); install.write_notices_plist()\n"
             "install.TRAY_PLIST.write_text('placeholder')\n"
             "install.ARGS.tray_exe = sys.argv[2]; install.retarget_tray_autostart()\n"
             "print(json.dumps([str(p) for p in (install.PLIST, install.NOTICES_PLIST, "
             "install.TRAY_PLIST)] + [install.PY, str(install.SCRIPT)]))")
    r = subprocess.run([PY, "-c", probe, str(HERE.parent), pexe], env=pe,
                       capture_output=True, text=True)
    try:
        pl, pn, pt, ppy, pscript = json.loads(r.stdout.splitlines()[-1])
        want = {pl: [str(ptools / "watcher"), str(proot)],
                pn: [ppy, pscript, "notices", "--quiet"], pt: [pexe]}
    except (ValueError, IndexError):
        want = {}
        print(r.stdout[-600:], r.stderr[-600:])
    import plistlib
    pbad = []
    for f, wargs in want.items():
        lint = subprocess.run(["/usr/bin/plutil", "-lint", f], capture_output=True, text=True)
        try:
            pd = plistlib.loads(Path(f).read_bytes())
        except Exception as ex:                 # what launchd would not read either
            pd = {"error": str(ex)}
        logs = [pd[k] for k in ("StandardOutPath", "StandardErrorPath") if k in pd]
        if lint.returncode != 0 or pd.get("ProgramArguments") != wargs \
                or not all(x.startswith(str(ph) + "/") for x in logs):
            pbad.append((Path(f).name, (lint.stdout + lint.stderr).strip()[-200:], pd))
    ck(len(want) == 3 and not pbad,
       f"install.py: the plists are valid and read back as written with & and < in the "
       f"paths ({pbad or r.stderr[-300:]})")

# a new version: GitHub asked only when on (or --now), told once, upgraded the
# way aht was installed
rel = sb / "release.json"
rel.write_text(json.dumps({"tag_name": "v99.0.0", "body": "## What's new\n- more",
                           "html_url": "https://example.invalid/r",
                           "published_at": "2026-11-01T00:00:00Z"}))
uenv = {"AHT_UPDATE_URL": rel.as_uri(), "AHT_INSTALL_KIND": "brew",
        "AHT_TERMINAL_LOG": str(sb / "term-up.log")}
u = JS("update", "--json", extra_env=uenv)
ck(u.get("enabled") is False and u.get("latest") is None and not u.get("checked"),
   f"update: off by default, and GitHub is not asked ({u})")
u = JS("update", "--now", "--json", extra_env=uenv)
ck(u.get("newer") and u.get("latest") == "99.0.0" and "more" in u.get("notes", "")
   and str(u.get("upgrade")).startswith("brew upgrade --cask aht"),
   f"update --now: the latest release, its notes and how to upgrade ({u})")
ck(JS("status", "--json", extra_env=uenv).get("update", {}).get("latest") == "99.0.0",
   "update: the status carries what is known, without asking again")
run("config", "--set", "update_check=true")
n1 = JS("notices", "--json", extra_env=uenv).get("notices", [])
n2 = JS("notices", "--json", extra_env=uenv).get("notices", [])
ck([x["title"] for x in n1 if x["kind"] == "update"] == ["aht 99.0.0 is out"]
   and not [x for x in n2 if x["kind"] == "update"], "update: one notice per new version")
r = run("update", "--upgrade", extra_env=uenv)
ck("brew upgrade --cask aht" in (sb / "term-up.log").read_text(),
   "update --upgrade: the Homebrew upgrade runs in a terminal window")
olog = sb / "opened-pages.log"
r = run("update", "--upgrade", extra_env=dict(uenv, AHT_INSTALL_KIND="source",
                                               AHT_OPEN_LOG=str(olog)))
opened = olog.read_text() if olog.is_file() else ""
ck(r.returncode == 0 and "git pull, then run " in r.stdout and "install.sh again" in r.stdout
   and opened == "https://example.invalid/r\n",
   f"update --upgrade from a checkout: the download page opens, and the step after "
   f"git pull is named ({r.stdout.strip()}, {opened!r})")
rel.write_text(json.dumps({"tag_name": "v99.0.0", "html_url": "file:///etc/passwd"}))
r = run("update", "--upgrade", extra_env=dict(uenv, AHT_INSTALL_KIND="download",
                                               AHT_OPEN_LOG=str(olog)))
ck(r.returncode == 0 and (olog.read_text() if olog.is_file() else "")
   == opened + core.RELEASES_PAGE + "\n" and "file:" not in r.stdout,
   f"update --upgrade: only an https page is opened, else aht's releases page "
   f"({r.stdout.strip()})")
rel.write_text(json.dumps({"tag_name": "v99.0.0", "body": "## What's new\n- more",
                           "html_url": "https://example.invalid/r",
                           "published_at": "2026-11-01T00:00:00Z"}))
run("update", "--now", extra_env=uenv)
run("config", "--unset", "update_check")

# installed with aht's Windows installer: Upgrade downloads the new one,
# checks it against the release's SHA256SUMS.txt and runs it
dl = sb / "dl" / "v99.0.0"
dl.mkdir(parents=True)
iname = core.installer_asset("99.0.0")
ran = sb / "installer-ran.txt"
stub = f"#!/bin/sh\necho \"$@\" > '{ran}'\n".encode()
(dl / iname).write_bytes(stub)
(dl / "SHA256SUMS.txt").write_text(f"{hashlib.sha256(stub).hexdigest()}  {iname}\n")
ienv = dict(uenv, AHT_INSTALL_KIND="installer", AHT_RELEASES_DOWNLOAD=(sb / "dl").as_uri())
u = JS("update", "--json", extra_env=ienv)
ck(u.get("installer") == iname and not u.get("upgrade") and iname.startswith("aht-setup-99.0.0-windows-"),
   f"update: installed by the installer, the new installer is the way up ({u.get('installer')})")
old_setup = sb / ".aht" / "run" / "aht-setup-98.0.0-windows-x64.exe"
old_setup.parent.mkdir(parents=True, exist_ok=True)
old_setup.write_bytes(b"an earlier upgrade's")
r = run("update", "--upgrade", extra_env=ienv)
for _ in range(50):
    if ran.exists() and ran.read_text().strip():
        break
    time.sleep(0.1)
args_ran = ran.read_text() if ran.exists() else ""
ck(r.returncode == 0 and "/SILENT" in args_ran and "/OPENWINDOW" not in args_ran
   and not old_setup.exists(),
   f"update --upgrade: the installer is downloaded, checked and run; an earlier one is "
   f"deleted ({r.stdout.strip()})")
ran.unlink(missing_ok=True)
wjson = sb / ".aht" / "run" / "window.json"
wjson.write_text(json.dumps({"pid": os.getpid(), "port": 9, "control": "x"}))
r = run("update", "--upgrade", extra_env=ienv)
for _ in range(50):
    if ran.exists() and ran.read_text().strip():
        break
    time.sleep(0.1)
args_ran = ran.read_text() if ran.exists() else ""
wjson.unlink()
ck(r.returncode == 0 and "/OPENWINDOW=1" in args_ran,
   f"update --upgrade from aht's window: the installer opens it again ({args_ran.strip()})")
ran.unlink(missing_ok=True)
(dl / "SHA256SUMS.txt").write_text(f"{'0' * 64}  {iname}\n")
r = run("update", "--upgrade", extra_env=ienv)
time.sleep(0.5)
ck(r.returncode == 1 and "does not match" in r.stdout and not ran.exists(),
   f"update --upgrade: an installer that does not match its checksum is not run ({r.stdout.strip()})")

# aht's window (Windows and Linux): the doors, the page, one command
r = run("window", "--selftest")
ck(r.returncode == 0 and "WINDOW SELFTEST OK" in r.stdout,
   f"the window lets in only its own page and runs a command ({r.stdout[-600:]} {r.stderr[-300:]})")
ui = (HERE.parent / "web" / "app.js").read_text()
import aht_web as _web
sent = set(_re.findall(r'(?:run\(\[|J\(|job\(\[|dryRun\(\[)"([a-z-]+)"', ui))
ck(sent and not sent - _web.COMMANDS,
   f"every command the window sends is on its list ({sorted(sent - _web.COMMANDS)})")
ck("--news" not in ui and "new_policy" not in ui,
   "the window no longer offers or sends the new-project choice")
fronts = [HERE.parent / n for n in ("macos/tray.swift", "linux/tray.py", "windows/src/aht_tray.py")]
still = [f.name for f in fronts if f.is_file()
         and any(w in f.read_text(encoding="utf-8") for w in ("new_policy", '"--news"'))]
ck(not still, f"no tray offers or sends the new-project choice either ({still})")
wtopics = set(_re.findall(r'helpBtn\("([^"]+)"\)', ui)) | set(_re.findall(r'openGuide\("([^"]+)"\)', ui)) \
    | set(_re.findall(r'sheet\([^\n]*?, "([^"]+)"(?:, \d+)?\)', ui))
wlost = sorted(t for t in wtopics if not any(h.startswith(t.lower()) for h in heads))
ck(wtopics and not wlost, f"every ? in aht's window opens a section of the guide ({wlost})")
ck(".innerHTML" not in ui and "insertAdjacentHTML" not in ui and "eval(" not in ui,
   "the window turns no text into HTML")
# the folder chooser: Cancel ends it; only when the server says no chooser
# could be shown does the page ask for the path as text
pf = _re.search(r"async function pickFolder\(.*?\n\}\n", ui, _re.S)
pf = pf.group(0) if pf else ""
gate = _re.search(r"if \(r\.chooser === false\) \{(.*?)\n  \}", pf, _re.S)
ck("/api/pick-folder" in pf and ui.count("window.prompt(") == 1
   and gate is not None and "window.prompt(" in gate.group(1),
   "the window asks for a folder's path as text only when no chooser could be shown")
# the keys the front-ends read are the ones the core sends: "link" on tidy's
# orphans, "forgotten" on setup's (and adopt's) projects
core_src = (HERE.parent / "aht.py").read_text(encoding="utf-8")
ck('"link": _is_link(' in core_src and '"forgotten": bool(' in core_src
   and 'a["forgotten"] = bool(' in core_src
   and 'o["link"]' in swift and '$0["forgotten"]' in swift
   and "p.forgotten" in ui and "a.forgotten" in ui,
   "the window and the Mac app read \"link\" and \"forgotten\" by the names the core sends")
# …and Release's: "mirror_paused" on projects' rows, "pauses_sync" and
# would_lose's "history" on reclaim --release, "ends_pause" on handover
ck('"mirror_paused": (e.get("mirror")' in core_src and 'pauses_sync=synced(' in core_src
   and 'would_lose={"files": None, "history": None' in core_src
   and 'return {"files": files, "history": history}' in core_src
   and 'out["ends_pause"] = rem.name' in core_src
   and "p.mirror_paused" in ui and "plan.pauses_sync" in ui and "d.pauses_sync" in ui
   and "lose.history" in ui
   and 'd["mirror_paused"]' in swift and 'plan["pauses_sync"]' in swift
   and 'lose["history"]' in swift,
   "the window and the Mac app read Release's paused sync and what stays there by the "
   "names the core sends")
ck(_re.search(r'\bSYSTEMS\s*=\s*\{[^}]*\bDarwin:\s*"macOS"', ui) and "SYSTEMS[f.system]" in ui,
   "the window says macOS where the core says Darwin")
# Getting started on Windows and Linux, and the tray at login on Linux
gs = JS("getting-started", "--json", extra_env={"AHT_STEPS": "linux", "AHT_AUTOSTART_DIR": str(sb / "autostart")})
ck([x["id"] for x in gs.get("steps", [])][:1] in (["login"], ["notify_send"])
   and "update_check" in [x["id"] for x in gs.get("steps", [])],
   f"getting started on Linux: notices, questions, the window, new versions ({[x['id'] for x in gs.get('steps', [])]})")
aenv = {"AHT_AUTOSTART_DIR": str(sb / "autostart")}
a0 = JS("autostart", "--json", extra_env=aenv)
a1 = JS("autostart", "on", "--json", extra_env=aenv)
a2 = JS("autostart", "--json", extra_env=aenv)
execl = next((l for l in (sb / "autostart" / "aht-tray.desktop").read_text().splitlines()
              if l.startswith("Exec=")), "")
a3 = JS("autostart", "off", "--json", extra_env=aenv)
ck(a1.get("on") and a2.get("on") and not a3.get("on")
   and not (sb / "autostart" / "aht-tray.desktop").exists(),
   f"autostart: the tray's login entry on and off ({a1}, {a2}, {a3})")
# the Windows installer's answer (it runs `autostart on` or `off`) is kept,
# so the welcome's Quick Setup does not turn the tray on against it
ck(a0.get("answered") is False and all(a.get("answered") is True for a in (a1, a2, a3))
   and JS("status", "--json").get("autostart", {}).get("answered") is True
   and (sb / ".aht" / "run" / "autostart.json").is_file(),
   f"autostart: on or off counts as the answer to the tray-at-login question "
   f"({a0}, {a3})")
# an `on` or `off` that changed nothing is no answer: a terminal's `on` on a
# Mac, where the app has the switch, or on Windows without the tray program
probe = ("import sys, json; sys.path.insert(0, sys.argv[1]); import aht; "
         "aht._tray_autostart = lambda on=None: {'supported': False, 'on': False}; "
         "a = aht.tray_autostart(True); "
         "aht._tray_autostart = lambda on=None: {'supported': True, 'on': True}; "
         "b = aht.tray_autostart(True); "
         "print(json.dumps([a, b, json.loads(aht._autostart_answer_path().read_text())]))")
ae = iso_env("autostart-noop")
r = subprocess.run([PY, "-c", probe, str(HERE.parent)], env=ae, capture_output=True, text=True)
try:
    an = json.loads(r.stdout)
except ValueError:
    an = [{}, {}, {}, r.stderr[-300:]]
ck(an[0].get("answered") is False and an[1].get("answered") is True and an[2].get("on") is True,
   f"autostart: an on that changed nothing is not kept as the answer ({an})")
if sys.platform == "darwin":
    me = iso_env("autostart-mac")
    la = Path(me["HOME"]) / "la"
    la.mkdir()
    me["AHT_LAUNCH_AGENTS"] = str(la)
    m1 = json.loads(iso_run(me, "autostart", "on", "--json").stdout or "{}")
    (la / "com.aht.tray.plist").write_text("<plist/>")      # what the app's switch writes
    m2 = json.loads(iso_run(me, "autostart", "on", "--json").stdout or "{}")
    ck(m1.get("answered") is False and m2.get("answered") is True and m2.get("on") is True,
       f"autostart on a Mac: a terminal's on changes nothing and is no answer; the app's "
       f"switch is ({m1}, {m2})")
# Getting started: once the user said no, the tray at login is a choice
# (optional), not a step left
probe = ("import sys, json; sys.path.insert(0, sys.argv[1]); import aht; "
         "s = lambda: next(x for x in aht.getting_started(iterm=False) if x['id'] == 'login'); "
         "a = s(); aht.note_autostart_answer(False); print(json.dumps([a, s()]))")
said = {}
for kind in ("mac", "linux") if os.name != "nt" else ("mac",):
    ge = dict(iso_env("said-no-" + kind), AHT_STEPS=kind)
    ge.update(AHT_LAUNCH_AGENTS=str(Path(ge["HOME"]) / "la"),
              AHT_AUTOSTART_DIR=str(Path(ge["HOME"]) / "autostart"))
    r = subprocess.run([PY, "-c", probe, str(HERE.parent)], env=ge, capture_output=True, text=True)
    try:
        said[kind] = [(x["ok"], x["optional"]) for x in json.loads(r.stdout)]
    except ValueError:
        said[kind] = r.stderr[-300:]
ck(all(v == [(False, False), (False, True)] for v in said.values()),
   f"getting started: the tray at login is optional once the user said no ({said})")
ck(_re.fullmatch(r'Exec="[^"]+" "[^"]+tray\.py"', execl) is not None,
   f"autostart: both words of Exec quoted, so a space in a path does no harm ({execl})")
# the Desktop Entry spec's two layers: a reader undoes the string escapes
# first (\s \n \t \r \\; any other is an error), then the quoting rule
# (\" \` \$ \\ inside quotes); %% is a literal %
def exec_args(v):
    v = _re.sub(r"\\(.)", lambda m: {"s": " ", "n": "\n", "t": "\t", "r": "\r",
                                     "\\": "\\"}.get(m.group(1), "\0"), v)
    return [_re.sub(r'\\([\\"`$])', r"\1", a).replace("%%", "%")
            for a in _re.findall(r'"((?:[^"\\]|\\.)*)"', v)]
odd = 'a"b$c`d\\e f%g'
odd2 = "/x/new\nline/a\tb/c\rd/tray.py"
ck(core.desktop_arg(odd) == r'"a\\"b\\$c\\`d\\\\e f%%g"'
   and exec_args(core.desktop_arg("/x/py thon") + " " + core.desktop_arg(odd))
   == ["/x/py thon", odd],
   f"autostart: Exec= escaped for both layers, so a $ \" ` \\ or % in a path reads back "
   f"({core.desktop_arg(odd)})")
ck(core.desktop_arg(odd2) == r'"/x/new\nline/a\tb/c\rd/tray.py"'
   and exec_args(core.desktop_arg(odd2)) == [odd2],
   f"autostart: a newline, tab or carriage return in a path stays on the Exec= line "
   f"({core.desktop_arg(odd2)})")
# GLib looks for the program before it turns %% into %: an interpreter whose
# path holds a % is written by a path to the same Python without one
pct = sb / "py 50%off"
pct.mkdir()
real_py = os.path.realpath(sys.executable)
odd_py = ["/x/new\nline/python3", "/x/a\tb/python3", "/x/py 50%off/python3",
          "/x/cr\rhere/python3"]
try:
    os.symlink(real_py, pct / "python3")
except OSError:                         # Windows without the right to make links
    print("  SKIP a % in the interpreter's path: no symlink here")
else:
    pct_py = str(pct / "python3")
    odd_py.append(pct_py)
    ck("%" not in real_py and core.exec_python(pct_py) == real_py
       and core.exec_python("/x/py thon/python3") == "/x/py thon/python3",
       f"autostart: a % in the interpreter's path: its real path starts instead "
       f"({core.exec_python(pct_py)})")
import ast as _ast
agree = {}
for src in ("linux/tray.py", "linux/install.py"):
    fns = [n for n in _ast.parse((HERE.parent / src).read_text(encoding="utf-8")).body
           if isinstance(n, _ast.FunctionDef) and n.name in ("desktop_arg", "exec_python")]
    ns = {"re": _re, "Path": Path, "aht": core, "os": os, "shutil": shutil, "sys": sys}
    try:
        exec(compile(_ast.Module(body=fns, type_ignores=[]), src, "exec"), ns)
        agree[src] = all(ns["desktop_arg"](x) == core.desktop_arg(x)
                         for x in [odd, odd2, "/x/py thon", "/home/j$doe/tray.py",
                                   "/x/50%off"] + odd_py) \
            and all(ns["desktop_arg"](ns["exec_python"](x))
                    == core.desktop_arg(core.exec_python(x)) for x in odd_py)
    except Exception as e:
        agree[src] = repr(e)
ck(all(v is True for v in agree.values()),
   f"autostart: the core, the tray and the Linux installer write the same Exec=, also for "
   f"a newline, tab or % in the interpreter's path ({agree})")
# the tray at login counts only where the tray can run (PyGObject and an
# AppIndicator library); questions in a window need zenity, not a screen now
zb = sb / "zbin"
zb.mkdir()
(zb / "zenity").write_text("#!/bin/sh\nexit 0\n")
(zb / "zenity").chmod(0o755)
genv = dict(aenv, AHT_STEPS="linux", DISPLAY="", WAYLAND_DISPLAY="",
            PATH=str(zb) + os.pathsep + env["PATH"])
gst = {x["id"]: x for x in JS("getting-started", "--json", extra_env=genv).get("steps", [])}
runs = a2.get("runs")
login = gst.get("login", {})
ck(runs is not None and a2.get("supported") == bool(runs or a2.get("on"))
   and (login.get("ok") is False and "python3-gi" in login.get("how", "") if runs is False
        else "python3-gi" not in login.get("how", "")),
   f"getting started on Linux: the tray at login is done only where the tray runs ({a2}, {login})")
dl = gst.get("dialogs", {})
ck(dl.get("ok") is True and "desktop session" in dl.get("text", "") and not dl.get("how"),
   f"getting started on Linux: zenity there but no screen (ssh) is no missing program ({dl})")
ck(run("setup", "--dismiss").returncode == 0 and JS("status", "--json").get("setup_dismissed") is True,
   "setup --dismiss: the window does not offer the setup again")

run("config", "--set", "terminal_app=Terminal")
probe = "import sys; sys.path.insert(0, sys.argv[1]); import aht; print(aht.terminal_choice())"
r = subprocess.run([PY, "-c", probe, str(HERE.parent)], env=env, capture_output=True, text=True)
ck(r.stdout.strip() == "Terminal", f"terminal_app: the chosen terminal is used ({r.stdout.strip()})")
run("config", "--unset", "terminal_app")

# the front-ends call into the core by name; a name the core does not have
# fails only on that platform, at run time (Windows uninstall did)
import ast
missing = set()
for src in ("windows/src/winlayer.py", "windows/src/aht_tray.py", "windows/src/winbadge.py",
            "windows/src/aht_main.py", "windows/src/make_icons.py", "linux/tray.py",
            "linux/watcher.py", "linux/install.py", "linux/uninstall.py", "install.py",
            "aht_web.py", "tests/fake_kimi.py"):
    tree = ast.parse((HERE.parent / src).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                and node.value.id in ("aht", "_core") and isinstance(node.ctx, ast.Load)
                and not hasattr(core, node.attr)):
            missing.add(f"{src}: aht.{node.attr}")
ck(not missing, f"every core name the front-ends use exists ({sorted(missing)})")
# and the other way: what the core and the Windows tray call in the Windows
# layer (only run there)
wl = ast.parse((HERE.parent / "windows/src/winlayer.py").read_text(encoding="utf-8"))
have = {n.name for n in wl.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))} | {
    t.id for n in wl.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
used = set()
for src in ("aht.py", "aht_web.py", "windows/src/aht_tray.py", "windows/src/aht_main.py"):
    for node in ast.walk(ast.parse((HERE.parent / src).read_text(encoding="utf-8"))):
        if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                and node.value.id == "winlayer" and isinstance(node.ctx, ast.Load)):
            used.add(node.attr)
ck(used and not used - have,
   f"every Windows-layer name the core and the tray use exists ({sorted(used - have)})")

done()
