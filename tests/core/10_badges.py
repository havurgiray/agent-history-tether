#!/usr/bin/env python3
"""[10] per-agent badge marks: 1 / 2 / 4+ symbols, git independent."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)

print("\n[10] per-agent badge marks: 1 / 2 / 4+ symbols, git independent")
snippet = (
    "import sys, json, os; sys.path.insert(0, %r); import aht\n"
    "print(json.dumps({\n"
    "  'one':  aht.desired_marks('x', {'claude': 'd'}),\n"
    "  'two':  aht.desired_marks('x', {'claude': 'd', 'codex': '@sessions'}),\n"
    "  'four': aht.desired_marks('x', {'claude': 'd', 'gemini': 'd',"
    " 'codex': '@sessions', 'cursor': 'd'}),\n"
    "  'none': aht.desired_marks('x', False),\n"
    "  'disc': len(aht.badge_disc_rgba(24, 'codex')),\n"
    "  'count_disc': len(aht.badge_disc_rgba(24, 5)),\n"
    "  'read_art': [aht.badge_disc_rgba(24, n) != aht.badge_disc_rgba(24, 'aht')"
    " for n in aht.READ_AGENTS],\n"
    "  'art': {n: [list(c), g] for n, (c, g) in aht.AGENT_BADGES.items()},\n"
    "  'agents': aht.agents_of({'codex': '@sessions', 'claude': 'd',"
    " 'kimi': 'x'}),\n"
    "}))\n" % str(HERE.parent))
r = subprocess.run([PY, "-c", snippet], env=env, capture_output=True, text=True)
d = json.loads(r.stdout)
ck(d["one"] == ["agent:claude"], "single store -> one agent mark")
ck(d["two"] == ["agent:claude", "agent:codex"],
   "two stores -> two marks in stable backend order")
ck(len([m for m in d["four"] if m.startswith("agent:")]) == 4,
   "four stores -> four marks (renderers show the count)")
ck(d["none"] == [], "untethered non-git folder -> no marks")
ck(d["disc"] == 24 * 24 * 4 and d["count_disc"] == 24 * 24 * 4,
   "shared disc rasteriser produces agent and count art")
ck(d["agents"] == ["claude", "codex", "kimi"],
   "agents_of orders names stably (feeds the relink prompt)")
ck(d["read_art"] == [True, True],
   "Antigravity and Mistral Vibe have discs of their own, not the neutral one")
# the Mac's badge tool draws the same colours and symbols as the core
import re as _re
swift = (HERE.parent / "badge_icon.swift").read_text()
mac = {n: [[round(float(v)) for v in c], None] for n, *c in _re.findall(
    r'"(\w+)":\s*\(\s*([\d.]+)/255\.0,\s*([\d.]+)/255\.0,\s*([\d.]+)/255\.0\)', swift)}
for n, g in _re.findall(r'case "(\w+)": return "(\w+)"', swift):
    mac.setdefault(n, [None, None])[1] = g
core_art = {n: v for n, v in d["art"].items() if n != "aht"}
ck(all(mac.get(n) == v for n, v in core_art.items()),
   f"badge_icon.swift draws every agent as the core does "
   f"({[n for n, v in core_art.items() if mac.get(n) != v]})")
# Linux: the git "+" is aht's own emblem, made with the agents' (the theme's
# link emblem made every git folder look like a link), unless the config
# names another
snippet = (
    "import sys, json, subprocess; sys.path.insert(0, sys.argv[1]); import aht\n"
    "calls = []\n"
    "aht._have = lambda c: c == 'gio'\n"
    "aht.subprocess.run = lambda cmd, **k: calls.append(cmd[6:]) or "
    "subprocess.CompletedProcess(cmd, 0)\n"
    "aht._badge_linux('x', ['git']); aht._badge_linux('x', ['agent:claude', 'git'])\n"
    "aht.save_config(dict(aht.load_config(), linux_git_emblem='emblem-default'))\n"
    "aht._badge_linux('x', ['git'])\n"
    "em = aht._xdg_data() / 'icons' / 'hicolor'\n"
    "png = [(em / f'{s}x{s}' / 'emblems' / 'aht-git.png').read_bytes() for s in (24, 48)]\n"
    "print(json.dumps({'calls': calls, 'sizes': [int.from_bytes(p[16:20], 'big') for p in png],\n"
    "  'png': all(p[:8] == b'\\x89PNG\\r\\n\\x1a\\n' for p in png),\n"
    "  'stamp': (em / f'.aht-emblems-v{aht.EMBLEM_VERSION}').is_file()}))\n")
ee = iso_env("emblems")
ee["XDG_DATA_HOME"] = str(Path(ee["HOME"]) / "xdg")
r = subprocess.run([PY, "-c", snippet, str(HERE.parent)], env=ee, capture_output=True, text=True)
try:
    d = json.loads(r.stdout)
except ValueError:
    d = {"error": r.stderr[-400:]}
ck(d.get("calls") == [["aht-git"], ["aht-agent-claude", "aht-git"], ["emblem-default"]]
   and d.get("sizes") == [24, 48] and d.get("png") and d.get("stamp"),
   f"Linux: the git badge is aht's own \"+\" emblem, unless the config names one ({d})")
(roots / "projX").mkdir()
projX = os.path.realpath(str(roots / "projX"))
mkstores(projX)
run("tag", projX, "--apply")
reg = json.loads((sb / ".aht" / "registry.json").read_text())
entry = next(e for e in reg["projects"].values() if e["real_path"] == projX)
ck(entry.get("stores", {}).get("codex") == "@sessions",
   "file-backend presence cached in the registry for badge use")
ck(entry.get("stores", {}).get("gemini") == sha(projX),
   "dir-backend store names cached alongside")

done()
