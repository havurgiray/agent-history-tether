#!/usr/bin/env python3
"""[16g] handover between all three systems: the rules (any system)."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)

def phase7_pure():
    """[16g] across systems, pure parts (any system): where a project goes on
    another machine (map_path, ntpath and posixpath), names a disk cannot
    hold, safe names, the trust key, git's settings, line endings, the
    identity check and the plan of a way back (return_plan)."""
    print("\n[16g] handover between all three systems: the rules (any system)")
    mp = core.map_path
    ck(mp("/Users/me/code/shop", "home", "/Users/me", "/home/me", "Darwin", "Linux")
       == "/home/me/code/shop"
       and mp("/home/me/code/shop", "home", "/Users/me", "/home/me", "Darwin", "Linux",
              back=True) == "/Users/me/code/shop"
       and mp("/Users/me", "home", "/Users/me", "/home/me", "Darwin", "Linux") == "/home/me",
       "map_path: below the home folder here, below the home folder there, both ways")
    ck(mp("/Users/me/code/shop", "home", "/Users/me", "C:\\Users\\me", "Darwin", "Windows")
       == "C:\\Users\\me\\code\\shop"
       and mp("C:\\Users\\me\\code\\shop", "home", "/Users/me", "C:\\Users\\me", "Darwin",
              "Windows", back=True) == "/Users/me/code/shop"
       and mp("c:/users/ME/code/shop", "home", "/Users/me", "C:\\Users\\me", "Darwin",
              "Windows", back=True) == "/Users/me/code/shop"
       and mp("C:\\Users\\me\\x", "home", "C:\\Users\\me", "/home/me", "Windows", "Linux")
       == "/home/me/x",
       "map_path: a Mac computes a PC's path (ntpath) and back; a drive's names ignore case")
    pairs = [["D:\\work", "/Users/me/work"], ["D:\\work\\big", "/Volumes/big"]]
    ck(mp("D:\\work\\big\\a", pairs, "C:\\Users\\me", "/Users/me", "Windows", "Darwin")
       == "/Volumes/big/a"
       and mp("D:\\work\\shop", pairs, "C:\\Users\\me", "/Users/me", "Windows", "Darwin")
       == "/Users/me/work/shop"
       and mp("C:\\Users\\me\\x", pairs, "C:\\Users\\me", "/Users/me", "Windows", "Darwin")
       == "/Users/me/x"
       and mp("E:\\x", pairs, "C:\\Users\\me", "/Users/me", "Windows", "Darwin") is None
       and mp("/Users/me/work/shop", pairs, "C:\\Users\\me", "/Users/me", "Windows", "Darwin",
              back=True) == "D:\\work\\shop",
       "map_path: pairs tried longest first, then the two homes; outside every rule: None")
    ck(mp("/a/b", "same", "/Users/me", "/home/me", "Darwin", "Linux") == "/a/b"
       and mp("/a/b", "same", "/Users/me", "C:\\Users\\me", "Darwin", "Windows") is None
       and mp("/Users/me/../etc", "home", "/Users/me", "/home/me") is None
       and mp("/Users/meow/x", "home", "/Users/me", "/home/me") is None,
       "map_path: same keeps the path (never across systems); no .., no look-alike prefix")
    # a part that is a path of its own where it goes (a\..\x, a drive, x:y)
    # would land outside the folder it maps to: refused, both ways
    ck(mp("/Users/me/a\\..\\..\\..\\Windows\\Temp\\x", "home", "/Users/me", "C:\\Users\\me",
          "Darwin", "Windows") is None
       and mp("/Users/me/D:", "home", "/Users/me", "C:\\Users\\me", "Darwin", "Windows") is None
       and mp("/Users/me/x:y", "home", "/Users/me", "C:\\Users\\me", "Darwin", "Windows") is None
       and mp("/Users/me/work/D:", pairs, "C:\\Users\\me", "/Users/me", "Windows", "Darwin",
              back=True) is None
       and mp("/home/me/a\\..\\..\\Windows", "home", "C:\\Users\\me", "/home/me", "Windows",
              "Linux", back=True) is None
       and mp("/home/me/E:", "home", "C:\\Users\\me", "/home/me", "Windows", "Linux",
              back=True) is None
       and mp("/home/me/a\\b", "home", "/Users/me", "/home/me", "Darwin", "Linux",
              back=True) == "/Users/me/a\\b"
       and mp("/Users/me/x:y", "home", "/Users/me", "/home/me", "Darwin", "Linux") == "/home/me/x:y"
       and mp("/Users/me/work/shop", [["D:", "/Users/me/work"]], "C:\\Users\\me", "/Users/me",
              "Windows", "Darwin", back=True) == "D:\\shop"
       and mp("/Users/me/code/a b", "home", "/Users/me", "C:\\Users\\me", "Darwin", "Windows")
       == "C:\\Users\\me\\code\\a b",
       "map_path: a part with a separator of the other side, a drive or a colon is refused, to "
       "a PC and back from one; a backslash between a Mac and Linux is a name's own")
    # names a disk cannot hold
    m = {"files": {k: [1, 1] for k in ("aux.md", "Aux.MD.txt", "a:b.txt", "COM1", "x.",
                                       "y ", "fine/auxiliary.md", "ok.txt", "q?.md")},
         "raw": {}, "dirs": ["fine"], "modes": {}, "twins": {}}
    m["files"]["lnk"] = ["l", "target"]
    rows = {r["kind"]: r for r in core.name_problems(m, {"system": "Windows",
                                                         "symlinks": False})}
    names = lambda k: sorted(x[0] for x in (rows.get(k) or {}).get("names", []))
    ck(names("reserved") == ["Aux.MD.txt", "COM1", "aux.md"]
       and names("windows_char") == ["a:b.txt", "q?.md"] and names("trailing") == ["x.", "y "]
       and names("symlink") == ["lnk"] and "fine/auxiliary.md" not in str(rows)
       and rows["reserved"]["text"] == "a name Windows reserves",
       f"names Windows cannot hold: reserved, characters, a trailing dot or space, links ({rows})")
    longp = {"files": {"d/" + "n" * 240 + ".txt": [1, 1]}, "raw": {}, "dirs": ["d"]}
    ck([r["kind"] for r in core.name_problems(longp, {"system": "Windows",
                                                       "long_paths": False},
                                              root="C:\\Users\\me\\code\\shop")]
       == ["long_path"]
       and not core.name_problems(longp, {"system": "Windows", "long_paths": True},
                                  root="C:\\Users\\me\\code\\shop")
       and not core.name_problems(m, {"system": "Linux", "case_sensitive": True}),
       "a path over 259 characters only where Windows lacks long paths; Linux holds them all")
    ck(core._safe_name("a:b.txt") == "a%3Ab.txt" and core._safe_name("aux.md") == "%61ux.md"
       and core._safe_name("d/x.") == "d/x%2E" and core._safe_name("50%.md") == "50%25.md"
       and core._cannot_hold(core._safe_name("q?/aux.md"), {"system": "Windows"}) is None,
       "safe names: reversible, and Windows holds every one")
    ck(core._trust_key("C:\\Users\\me\\x") == "C:/Users/me/x"
       and core._key_claude("C:\\Users\\me\\x") == "C--Users-me-x"
       and (os.name == "nt" or core._trust_key("/home/me/x") == "/home/me/x"),
       "Windows: the trust key with forward slashes, the history under C--Users-me-x")
    gs = core.git_settings
    ck(gs("Windows", "Darwin", False) == {"core.filemode": "false"}
       and gs("Linux", "Windows", True) == {"core.autocrlf": "true"}
       and gs("Linux", "Windows", False) == {} and gs("Darwin", "Linux", True) == {}
       and core.git_env_vars({"core.filemode": "false"}) == {
           "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.filemode",
           "GIT_CONFIG_VALUE_0": "false"},
       "git's settings for sessions aht starts: filemode off on a Windows holder, autocrlf "
       "from a Windows home that has it on; as GIT_CONFIG_* variables")
    ck(core.can_send_projects() and {"desktop.ini", "Thumbs.db", "ehthumbs.db", "aht-badge.ico",
                                     "$RECYCLE.BIN", "System Volume Information"}
       <= set(core.HANDOVER_SKIP),
       "projects move from every system; Windows' own files stay behind")
    # line endings
    ed = sb / "eol"
    ed.mkdir(exist_ok=True)
    (ed / "lf").write_bytes(b"a\nb\n")
    (ed / "crlf").write_bytes(b"a\r\nb\r\n")
    (ed / "mixed").write_bytes(b"a\r\nb\n")
    (ed / "bin").write_bytes(b"a\0\r\n")
    f = {n: core.eol_facts(ed / n) for n in ("lf", "crlf", "mixed", "bin")}
    ck(f["lf"]["style"] == "lf" and f["crlf"]["style"] == "crlf" and f["mixed"]["style"] == "mixed"
       and f["bin"]["style"] == "binary" and f["lf"]["norm"] == f["crlf"]["norm"]
       and f["lf"]["raw"] != f["crlf"]["raw"],
       "line endings: a file's style, and its checksum with CRLF read as LF")
    os.utime(ed / "crlf", (1_000_000_000, 1_000_000_000))
    ck(core.restyle(str(ed / "crlf"), "lf") and (ed / "crlf").read_bytes() == b"a\nb\n"
       and int(os.stat(ed / "crlf").st_mtime) == 1_000_000_000
       and core.restyle(str(ed / "lf"), "crlf") and (ed / "lf").read_bytes() == b"a\r\nb\r\n",
       "a file gets back the line endings it left with, its time kept")
    # the same project there, or nothing
    ic = core.identity_check
    rows = [ic({"path_exists": False}, "u1", "on box", "/x", "fix")[1],
            ic({"path_exists": True, "path_entries": 0}, "u1", "on box", "/x", "fix")[1],
            ic({"path_exists": True, "path_entries": 4, "path_marker": "u1",
                "path_owner": "copy"}, "u1", "on box", "/x", "fix")[1],
            ic({"path_exists": True, "path_entries": 4, "path_marker": "u2",
                "path_owner": "none"}, "u1", "on box", "/x", "fix")[1],
            ic({"path_exists": True, "path_entries": 4, "path_marker": "u1",
                "path_owner": "own"}, "u1", "on box", "/x", "fix")[1],
            ic({"path_exists": True, "path_entries": 4, "path_marker": None,
                "path_owner": "none"}, "u1", "on box", "/x", "fix")[1]]
    ck(rows[:3] == [None, None, None] and "holds another folder (4 items)" in rows[3]
       and "live project of its own" in rows[4] and "holds another folder" in rows[5],
       f"identity: a missing or empty folder, or this project's copy; never another folder, "
       f"nor that machine's own live project ({rows[3:]})")
    # the plan of a way back
    base = {"here": {"project": {"a.txt": [2, 1], "b.txt": [2, 1], "c.txt": [2, 1],
                                 ".aht/.project-id": [3, 1], "gone.txt": [1, 1]},
                     "history": {"s1.jsonl": [10, 1]}},
            "there": {"project": {"a.txt": [2, 1], "b.txt": [2, 1], "c.txt": [2, 1],
                                  ".aht/.project-id": [3, 1], "gone.txt": [1, 1]},
                      "history": {"s1.jsonl": [10, 1]}},
            "transcripts": {"s1.jsonl": [10, "h"]}}
    ours = {"project": {"files": dict(base["here"]["project"], **{"c.txt": [3, 2]})},
            "history": {"files": {"s1.jsonl": [10, 1]}}}
    theirs = {"project": {"files": {"a.txt": [4, 2], "b.txt": [4, 2], "c.txt": [4, 2],
                                    "new:x.txt": [1, 2], "ok.txt": [1, 2]},
                          "raw": {}},
              "history": {"files": {"s1.jsonl": [20, 2]}, "raw": {}}}
    need = core.return_needs(base, ours, theirs)
    eol = {"a.txt": {"here": {"raw": "1", "norm": "n", "style": "lf"},
                     "there": {"raw": "2", "norm": "n", "style": "crlf"}},
           "b.txt": {"here": {"raw": "1", "norm": "n", "style": "lf"},
                     "there": {"raw": "3", "norm": "m", "style": "crlf"}}}
    win = {"system": "Windows"}
    rp = core.return_plan(base, ours, theirs, prefix_ok={"s1.jsonl": False},
                          written_by={"s1.jsonl": "2.0.0"}, here_claude="2.0.0", eol=eol,
                          here_facts=win, here_root="C:\\p")
    ck(need == {"prefix": {"s1.jsonl": 10}, "written_by": {"s1.jsonl": 10},
                "eol": ["a.txt", "b.txt", "c.txt"]}
       and rp["eol_only"] == ["a.txt"] and rp["eol_keep"] == {"b.txt": "lf"}
       and rp["project"]["take"] == ["b.txt"] and rp["project"]["conflict"] == ["c.txt"]
       and rp["history"]["conflict"] == ["s1.jsonl"] and not rp["history"]["take"]
       and [u["kept_as"] for u in rp["unsafe"]] == ["new%3Ax.txt"]
       and rp["project"]["new"] == ["ok.txt"]
       and rp["project"]["delete"] == ["gone.txt"] and not rp["blockers"],
       f"return_plan: endings only stay, a flipped file keeps its style, a transcript that does "
       f"not continue is kept twice, names this disk cannot hold go aside, .aht/ stays ({rp})")
    rp2 = core.return_plan(base, ours, theirs, prefix_ok={"s1.jsonl": True},
                           written_by={"s1.jsonl": "2.1.0"}, here_claude="2.0.0",
                           prefer="there", there_name="pc", home_name="mac")
    rp3 = core.return_plan(base, ours, theirs, prefix_ok={"s1.jsonl": True},
                           written_by={"s1.jsonl": "2.1.0"}, here_claude="2.0.0",
                           ignore_version=True)
    ck(rp2["history"]["take"] == ["s1.jsonl"] and "c.txt" in rp2["project"]["take"]
       and rp2["conflicts"] == {"project": ["c.txt"]}
       and rp2["blockers"] == ["Claude Code 2.1.0 was used on pc, mac has 2.0.0: an older "
                               "version may not read the newer history — update Claude Code "
                               "on mac first (or pass --ignore-version)"]
       and not rp3["blockers"] and rp3["warnings"],
       "return_plan: a continued transcript comes; a newer Claude Code blocks unless "
       "--ignore-version; --prefer there takes theirs")
    ck(core.plan_id(rp, ours, theirs) == core.plan_id(core.return_plan(
           base, ours, theirs, prefix_ok={"s1.jsonl": False}, written_by={"s1.jsonl": "2.0.0"},
           here_claude="2.0.0", eol=eol, here_facts=win, here_root="C:\\p"), ours, theirs)
       and core.plan_id(rp, ours, theirs) != core.plan_id(rp2, ours, theirs),
       "a plan's id: the same inputs, the same plan; another plan, another id")
    # a take-back on a PC without long paths: a file whose path is too long
    # here is as long below kept-aside/, so it is kept under a short name of
    # one part, and the take-back never stops over such files
    longk = "deep/" + "d" * 120 + "/notes about the trip.txt"
    lroot = "C:\\Users\\me\\code\\" + "p" * 130
    rpl = core.return_plan(
        {"here": {"project": {}, "history": {}}, "there": {"project": {}, "history": {}}},
        {"project": {"files": {}}, "history": {"files": {}}},
        {"project": {"files": {longk: [5, 2], "a:b.txt": [1, 2]}, "raw": {}},
         "history": {"files": {}, "raw": {}}},
        prefix_ok={}, written_by={}, here_claude=None,
        here_facts={"system": "Windows", "long_paths": False}, here_root=lroot)
    ck([(u["there"], u["kept_as"]) for u in rpl["unsafe"]]
       == [("a:b.txt", "a%3Ab.txt"), (longk, "1-notes about the trip.txt")]
       and core._flat_aside("d/" + "n" * 200 + ".txt", 3) == "3-" + "n" * 37 + ".txt"
       and core._flat_aside("x/aux.", 0) == "0-aux%2E",
       f"kept aside on a PC: a path too long there gets a short name of one part, the list "
       f"names the file as it was ({rpl['unsafe']})")
    class Kept:                     # the far end: names come, kept-aside files do not
        def __init__(self):
            self.renamed = None
        def fetch(self, src, dst, entries=None, aside=None, rename=None, **kw):
            if rename:
                self.renamed = dict(rename)
                return {"ok": False, "error": "File name too long", "problems": []}
            for k in entries:
                t = Path(dst) / k
                t.parent.mkdir(parents=True, exist_ok=True)
                t.write_text("x")
            return {"ok": True}
    kt = sb / "kept-tree"
    kt.mkdir()
    kr = Kept()
    try:
        kd = core._pull_tree(kr, {"take": [], "new": ["ok.txt"], "delete": [], "conflict": [],
                                  "kept": []}, "/far", str(kt), {}, sb / "kept-x" / "project",
                             "box", False, [], False,
                             unsafe=[{"key": longk, "there": longk,
                                      "kept_as": "0-notes about the trip.txt"}])
    except core.HandoverError as x:
        kd = {"raised": str(x)}
    ck((kt / "ok.txt").is_file() and kd.get("unsafe") == []
       and kd.get("unsafe_failed") == [{"there": longk, "key": longk,
                                        "error": "File name too long"}],
       f"a take-back goes on when files kept aside do not come: they are named ({kd})")
    deep = sb / ("a" * 120) / ("b" * 120) / "project"
    os.environ.update(AHT_AS_WINDOWS="1", AHT_SHORT_PATHS="1")
    try:
        kr2 = Kept()
        core._pull_tree(kr2, {"take": [], "new": [], "delete": [], "conflict": [], "kept": []},
                        "/far", str(kt), {}, deep, "box", False, [], False,
                        unsafe=[{"key": "x/a:b.txt", "there": "x/a:b.txt",
                                 "kept_as": "x/a%3Ab.txt"}])
    except core.HandoverError:
        pass
    finally:
        del os.environ["AHT_AS_WINDOWS"], os.environ["AHT_SHORT_PATHS"]
    ck(kr2.renamed == {"x/a:b.txt": "0-a%3Ab.txt"},
       f"kept aside where even the safe name's path is too long: a short name ({kr2.renamed})")
    # the line to continue a session, as a PC's cmd.exe runs it
    env8 = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.filemode",
            "GIT_CONFIG_VALUE_0": "false"}
    ck(core.env_prefix(env8, nt=True) == 'set "GIT_CONFIG_COUNT=1" && set "GIT_CONFIG_KEY_0='
       'core.filemode" && set "GIT_CONFIG_VALUE_0=false" && '
       and core.env_prefix(env8, nt=False) == "export GIT_CONFIG_COUNT=1; export "
       "GIT_CONFIG_KEY_0=core.filemode; export GIT_CONFIG_VALUE_0=false; "
       and core.env_prefix({}, nt=True) == "" and core.env_prefix({"bad name": "x"}) == "",
       "the continue line: set \"K=V\" && for cmd.exe on a PC, export in sh")

phase7_pure()

done()
