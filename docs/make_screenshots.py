#!/usr/bin/env python3
"""Render the aht window from a made-up demo setup, for the README's
screenshots: no real project, session, machine, path or user name appears.

  docs/make_screenshots.py OUT_DIR [SANDBOX_DIR] [--app PATH/TO/aht-tray] [--dark]

--app: the aht-tray inside an aht.app (it carries the core); --dark renders
the dark appearance.  Then, for light and dark:
  sips -Z 1400 OUT_DIR/{projects,sessions,guide}.png --out docs/screenshots/mac-…[-dark].png
"""
import json, os, shutil, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

import tempfile
REPO = Path(__file__).resolve().parent.parent
APP = (sys.argv[sys.argv.index("--app") + 1] if "--app" in sys.argv
       else "/Applications/aht.app/Contents/MacOS/aht-tray")
args = [a for a in sys.argv[1:] if a not in ("--app", APP, "--dark")]
OUT = Path(args[0])
D = Path(os.path.realpath(args[1] if len(args) > 1 else tempfile.mkdtemp(prefix="aht-demo-")))
shutil.rmtree(D, ignore_errors=True)
home, roots = D / "Users" / "you", None
roots = home / "Projects"
claude = home / ".claude"
for p in (roots, claude / "projects", claude / "sessions", home / ".aht", D / "nope"):
    p.mkdir(parents=True)
(claude / "settings.json").write_text(json.dumps(
    {"remoteControlAtStartup": True, "autoContinueAtUsageLimit": True,
     "hooks": {e: [{"hooks": [{"type": "command", "command": "python3 aht.py hook"}]}]
               for e in ("SessionStart", "UserPromptSubmit")}}))
fake_ts = D / "tailscale"
fake_ts.write_text("#!/bin/sh\necho 'Tailscale is stopped.' >&2\nexit 1\n")
fake_ts.chmod(0o755)

env = dict(os.environ)
env.update({
    "HOME": str(home), "AHT_HOME": str(home / ".aht"), "AHT_ROOTS": str(roots),
    "AHT_ROOT_CLAUDE": str(claude / "projects"), "AHT_NO_NOTIFY": "1", "AHT_NO_ICONS": "1",
    "AHT_NO_BACKUP": "1", "AHT_NO_CHECKPOINT": "1", "AHT_TAILSCALE": str(fake_ts),
    "AHT_CLAUDE_VERSION": "2.1.286", "AHT_NO_MIRROR": "1", "AHT_MACHINE_NAME": "my-mac",
})
for b in ("GEMINI", "CURSOR", "OPENCODE", "CODEX", "COPILOT", "KIMI", "KIMI_CODE"):
    env[f"AHT_ROOT_{b}"] = str(D / "nope")

def aht(*a):
    return subprocess.run(["/usr/bin/python3", str(REPO / "aht.py"), *a], env=env,
                          capture_output=True, text=True)

def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat().replace("+00:00", "Z")

enc = lambda p: __import__("re").sub(r"[^a-zA-Z0-9]", "-", p)
now = time.time()
PROJECTS = [
    # folder, tab title, session title, last request, last answer, hours ago
    ("paper", "Paper", "Revise the related-work section",
     "tighten the related work and fix the two broken citations",
     "Both citations point to the published versions now, and the section is 180 words shorter.", 0.1),
    ("docs-site", "Site", "Deploy the documentation site",
     "deploy the docs site to the staging server",
     "The build passed. Shall I deploy it to staging now?", 0.3),
    ("thesis", "Thesis", "Chapter 4 figures",
     "redraw the chapter 4 figures with the new colour scheme",
     "All six figures are redrawn; the PDFs are in figures/ch4.", 2),
    ("benchmarks", "Bench", "Nightly benchmark run",
     "run the full benchmark suite and summarise the results",
     "Done: the median run time dropped by 12 % against last week.", 5),
    ("course-notes", None, "Week 6 exercises",
     "write three exercises on recursion for week 6",
     "Three exercises with solutions are in week6/exercises.md.", 30),
    ("budget-tool", None, "CSV import",
     "make the CSV import accept semicolons",
     "The import now detects the separator by itself.", 80),
]
sids = {}
for i, (folder, tab, title, ask, answer, hours) in enumerate(PROJECTS):
    real = roots / folder
    (real / "src").mkdir(parents=True)
    (real / "README.md").write_text(f"# {folder}\n")
    store = claude / "projects" / enc(str(real))
    store.mkdir()
    sid = f"{i + 1:08x}-0000-4000-8000-{i + 1:012x}"
    sids[folder] = sid
    t = now - hours * 3600
    lines = [
        {"type": "user", "cwd": str(real), "timestamp": iso(t - 600), "entrypoint": "cli",
         "message": {"role": "user", "content": ask}},
        {"type": "ai-title", "aiTitle": title},
        {"type": "assistant", "cwd": str(real), "timestamp": iso(t), "message": {
            "role": "assistant", "content": [{"type": "text", "text": answer}]}},
    ]
    if tab:
        lines.append({"type": "custom-title", "customTitle": tab, "sessionId": sid})
    (store / f"{sid}.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines))
    os.utime(store / f"{sid}.jsonl", (t, t))
    aht("tag", str(real), "--apply")

# four open sessions in four iTerm2 tabs: working, waiting, idle, and one
# started before Remote Control was on, on an older Claude Code
procs, tabs, ttys = [], {}, {}
OPEN = [("paper", "busy", None, True, "2.1.286"),
        ("docs-site", "waiting", "permission prompt", True, "2.1.286"),
        ("thesis", "idle", None, True, "2.1.286"),
        ("benchmarks", "idle", None, False, "2.1.280")]
for n, (folder, status, waiting, in_app, version) in enumerate(OPEN, 1):
    pr = subprocess.Popen(["sleep", "900"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(pr)
    rec = {"pid": pr.pid, "cwd": str(roots / folder), "sessionId": sids[folder],
           "status": status, "statusUpdatedAt": int((now - 60 * n) * 1000), "kind": "interactive",
           "version": version, **({"waitingFor": waiting} if waiting else {}),
           **({"bridgeSessionId": f"session_demo{n}"} if in_app else {})}
    (claude / "sessions" / f"{pr.pid}.json").write_text(json.dumps(rec))
    tty = f"/dev/ttys9{n}"
    ttys[str(pr.pid)] = tty
    title = next(p[1] for p in PROJECTS if p[0] == folder)
    tabs[tty] = {"title": title, "override": True, "pane": 1, "panes": 1, "window": 1, "tab": n}
(D / "tabs.json").write_text(json.dumps(tabs))
# the names came from the tabs (aht gave them), as they would on a real Mac
(home / ".aht" / "run").mkdir(parents=True, exist_ok=True)
(home / ".aht" / "run" / "tab-names.json").write_text(json.dumps(
    {sids[f]: {"names": [t], "tab": t, "at": now} for f, t, *_ in PROJECTS if t}))
env.update({"AHT_ITERM_TABS": str(D / "tabs.json"), "AHT_TTYS": json.dumps(ttys)})
aht("search", "--update")

# two saved iTerm2 layouts for Restore Workspace: tabs with colours, the four
# open sessions (skipped) and two that are not open now
COLORS = {"paper": "#eddd68", "docs-site": "#6fa1f1", "thesis": "#b990d4",
          "benchmarks": "#bcd660", "course-notes": "#ea7468", "budget-tool": "#ebaf5a"}
wsd = home / ".aht" / "workspaces"
wsd.mkdir(parents=True, exist_ok=True)
for name, hours, folders in (("20260930-091500", 30, PROJECTS),
                             ("20260929-171000", 52, PROJECTS[:4])):
    rows = [{"window": 1, "tab": n, "pane": 1, "title": p[1] or p[0].replace("-", " ").title(),
             "profile": "Default", "color": COLORS[p[0]], "cwd": str(roots / p[0]),
             "agent": "claude", "session": sids[p[0]], "args": [], "name": p[2]}
            for n, p in enumerate(folders, 1)]
    t = now - hours * 3600
    (wsd / f"{name}.json").write_text(json.dumps({"at": t - 3600, "seen": t, "host": "my-mac",
                                                  "tabs": rows}))

try:
    shutil.rmtree(OUT, ignore_errors=True)
    r = subprocess.run([APP, "--snapshot", str(OUT), "--select-first"]
                       + (["--dark"] if "--dark" in sys.argv else []), env=env,
                       capture_output=True, text=True, timeout=400)
    print(r.stdout[-400:], r.stderr[-400:])
finally:
    for pr in procs:
        pr.kill()
        pr.wait()
