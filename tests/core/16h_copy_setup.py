#!/usr/bin/env python3
"""[16h] your own Claude Code setup on another machine: what a handover's
check says the machine lacks (global CLAUDE.md, skills, agents, plugins, MCP
servers), `aht copy-setup` (a dry run, then the copy: what is missing goes,
what differs is set aside there first, what is only there stays, plugins are
installed with Claude Code's own command there, hooks, the status line and
MCP servers are left out), and nothing missing afterwards.  The other machine
is the stand-in "box" of the handover suite (handover_kit.py), files copied
with aht's own copying."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)
import handover_kit as kit

print("\n[16h] your own Claude Code setup on another machine")
if kit.start("aht"):
    h = kit.setup()
    try:
        kit.configure(h)
        here, there = tools, h.bhome / ".claude"
        (here / "CLAUDE.md").write_text("British spelling\n")
        for name, text in (("commit", "one"), ("same", "same")):
            (here / "skills" / name).mkdir(parents=True)
            (here / "skills" / name / "SKILL.md").write_text(text)
        (here / "agents").mkdir()
        (here / "agents" / "rev.md").write_text("an agent")
        (here / "settings.json").write_text(json.dumps({
            "enabledPlugins": {"tool@market": True, "off@market": False},
            "extraKnownMarketplaces": {"market": {"source": {"source": "github",
                                                             "repo": "me/market"}}},
            "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "/usr/bin/python3 /h/x.py run"}]}],
                      "SessionStart": [{"hooks": [{"type": "command",
                                                   "command": "/x/agent-history-tether/aht.py hook"}]}]},
            "statusLine": {"type": "command", "command": "x"}}))
        (sb / ".claude.json").write_text(json.dumps({"mcpServers": {"papers": {"command": "x"}}}))
        for name, text in (("same", "same"), ("commit", "older"), ("theirs", "keep")):
            (there / "skills" / name).mkdir(parents=True)
            (there / "skills" / name / "SKILL.md").write_text(text)
        proj = roots / "Setup Check"
        proj.mkdir()
        (proj / "notes.md").write_text("x")
        hd = h.J(h.hrun("handover", str(proj), "--to", "box", "--json"))
        note = next((w for w in hd.get("warnings", []) if "lacks your own Claude Code setup" in w), "")
        ck(note and "global CLAUDE.md" in note and "1 agent (rev.md)" in note
           and "skill commit as it is here" in note and "1 plugin (tool)" in note
           and "MCP server papers" in note and "aht copy-setup box" in note
           and "same" not in note.split("skill commit")[0],
           f"hand over, dry run: what box lacks of your own setup, and how to bring it ({note or hd})")
        d = h.J(h.hrun("copy-setup", "box", "--json"))
        ck(not d.get("applied") and d.get("claude_md") == "missing"
           and d.get("copy", {}).get("skills") == [] and d["replace"]["skills"] == ["commit"]
           and d["copy"]["agents"] == ["rev.md"] and d.get("plugins") == ["tool@market"]
           and d.get("marketplaces") == ["market"]
           and d["left_out"] == {"hooks": ["Stop: x.py"], "status_line": True, "mcp": ["papers"]}
           and not (there / "CLAUDE.md").exists(),
           f"copy-setup, dry run: what goes, what is replaced, the plugins, what stays out ({d})")
        d = h.J(h.hrun("copy-setup", "box", "--apply", "--json"))
        aside = list(h.box.glob("**/remote/aside/setup-*/skills/commit/SKILL.md"))
        ck(d.get("applied") and (there / "CLAUDE.md").read_text() == "British spelling\n"
           and (there / "skills" / "commit" / "SKILL.md").read_text() == "one"
           and (there / "skills" / "theirs" / "SKILL.md").read_text() == "keep"
           and (there / "agents" / "rev.md").read_text() == "an agent"
           and aside and aside[0].read_text() == "older"
           and [x.get("plugin") for x in d.get("plugin_results", []) if x.get("ok")] == ["tool@market"],
           f"copy-setup --apply: copied, the one it replaced set aside there, theirs kept, the "
           f"plugin installed there ({d}, {aside})")
        d = h.J(h.hrun("copy-setup", "box", "--json"))
        ck(d.get("claude_md") is None and not any(d["copy"].values())
           and not any(d["replace"].values()),
           f"copy-setup afterwards: nothing left to copy ({d})")
        r = h.hrun("copy-setup", "box")
        ck(r.returncode == 0 and "left out" in r.stdout and "MCP servers papers" in r.stdout,
           f"copy-setup in the terminal says what it leaves out ({r.stdout[-400:]})")
    finally:
        kit.stop_stand_ins(h.bhome)
done()
