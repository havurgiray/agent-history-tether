#!/usr/bin/env python3
"""[24] the vault: Claude's history behind a password.  Set up, locked and
unlocked, a wrong password, aht standing down while locked, the password
changed, switched off again; with a stand-in keeper on any system, and with
real encrypted disk images on a Mac."""
from common import *  # noqa: F401,F403  (this unit's sandbox, ck, run, ...)

import signal

print("\n[24] the vault: Claude's history behind a password")


def tree(d):
    """Every file under d with its checksum; a link as where it points."""
    out = {}
    for root, dirs, files in os.walk(d):
        for n in dirs + files:
            p = Path(root) / n
            rel = str(p.relative_to(d))
            if p.is_symlink():
                out[rel] = "-> " + os.readlink(p)
            elif p.is_file():
                out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def vault_suite(name, keeper):
    """One whole life of a vault in a sandbox of its own."""
    base = Path(os.path.realpath(sb)) / name
    e = dict(env, HOME=str(base / "home"), AHT_HOME=str(base / ".aht"),
             AHT_ROOT_CLAUDE=str(base / "claude" / "projects"), AHT_VAULT_KEEPER=keeper,
             AHT_NO_BACKUP="1")
    e.pop("AHT_ROOTS", None)
    (base / "home").mkdir(parents=True)
    ch, ah = base / "claude", base / ".aht"
    secret = "the-words-nobody-else-may-read-" + name
    proj = ch / "projects" / "-w-paper"
    proj.mkdir(parents=True)
    (proj / "s1.jsonl").write_text(json.dumps({"cwd": "/w/paper", "text": secret}) + "\n")
    (proj / "memory").mkdir()
    (proj / "memory" / "MEMORY.md").write_text("- a note\n")
    os.symlink("s1.jsonl", proj / "latest")
    (ch / "history.jsonl").write_text(json.dumps({"display": secret}) + "\n")
    (ch / "settings.json").write_text("{}")
    (ch / "sessions").mkdir()
    (ah / "backups" / "u1").mkdir(parents=True)
    (ah / "backups" / "u1" / "one.snap").write_text(secret)
    (ah / "search.db").write_text("an index")
    (ah / "registry.json").write_text(json.dumps({"projects": {}}))
    before = {"claude": tree(ch), "backups": tree(ah / "backups")}

    def V(*a, stdin=None, **extra):
        r = subprocess.run([PY, LAUNCH, "vault", *a, "--json"], env=dict(e, **extra),
                           input=stdin or "", capture_output=True, text=True)
        try:
            return json.loads(r.stdout), r
        except ValueError:
            return {"unreadable": r.stdout[-300:] + r.stderr[-300:]}, r

    def A(*a, **extra):
        return subprocess.run([PY, LAUNCH, *a], env=dict(e, **extra), input="",
                              capture_output=True, text=True)

    def session(status="idle"):
        p = subprocess.Popen(["sleep", "600"], cwd="/", stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        (ch / "sessions" / f"{p.pid}.json").write_text(json.dumps(
            {"pid": p.pid, "cwd": "/w/paper", "sessionId": "s1", "status": status, "name": "paper"}))
        return p

    def end(p):
        p.kill()
        p.wait()
        (ch / "sessions" / f"{p.pid}.json").unlink(missing_ok=True)

    pw = "correct horse battery"
    try:
        d, _ = V()
        st = json.loads(A("status", "--json").stdout)
        ck(d.get("state") == "off" and st.get("vault", {}).get("state") == "off"
           and not (ah / "vault").exists(),
           f"{name}: off unless set up, and aht status says so ({d.get('state')})")
        d, _ = V("setup")
        ck(not d.get("applied") and [f["name"] for f in d.get("folders", [])]
           == ["claude", "backups", "private"] and d.get("bytes", 0) > 0
           and tree(ch) == before["claude"] and not (ah / "vault").exists(),
           f"{name}: setup, dry run: Claude's folder, the backups and aht's own; nothing changed "
           f"({d.get('blockers')})")
        p = session()
        d, _ = V("setup", "--apply", "--password-stdin", stdin=f"{pw}\n{pw}\n")
        ck(not d.get("applied") and "session(s) are open" in str(d.get("blockers"))
           and not (ah / "vault").exists(),
           f"{name}: setup waits while a Claude session is open ({d.get('blockers')})")
        end(p)
        d1, _ = V("setup", "--apply")
        d2, _ = V("setup", "--apply", "--password-stdin", stdin=f"{pw}\n{pw}x\n")
        d3, _ = V("setup", "--apply", "--password-stdin", stdin="short\nshort\n")
        ck("no password given" in str(d1.get("blockers")) and "differ" in str(d2.get("blockers"))
           and "8 characters" in str(d3.get("blockers")) and tree(ch) == before["claude"]
           and not (ah / "vault" / "vault.json").exists(),
           f"{name}: no password, two that differ, a short one: nothing happens "
           f"({d1.get('blockers')}, {d2.get('blockers')}, {d3.get('blockers')})")
        if keeper == "stand-in":
            d, r = V("setup", "--apply", "--password-stdin", stdin=f"{pw}\n{pw}\n",
                     AHT_VAULT_FAIL="backups")
            ck(not d.get("applied") and "every folder is as it was" in str(d.get("blockers"))
               and tree(ch) == before["claude"] and tree(ah / "backups") == before["backups"]
               and not (ah / "vault" / "vault.json").exists()
               and not list(base.glob("*.aht-plain-*")) and not list(ah.glob("*.aht-plain-*"))
               and not list(base.glob("*.aht-vault.*")) and not list(ah.glob("*.aht-vault.*")),
               f"{name}: a step that fails half way puts every folder back ({d.get('blockers')})")
            d, r = V("setup", "--apply", "--password-stdin", stdin=f"{pw}\n{pw}\n",
                     AHT_VAULT_CRASH="backups")
            cut, _ = V()
            r1 = A("projects", "--json")
            again, _ = V("setup", "--apply", "--password-stdin", stdin=f"{pw}\n{pw}\n")
            ck(r.returncode == 70 and cut.get("state") == "cut-short"
               and "cut short" in r1.stdout and r1.returncode == 3
               and "aht vault repair" in str(again.get("blockers"))
               and not (ah / "vault" / "vault.json").exists(),
               f"{name}: a setup cut short by a crash: aht stands down and names the way out "
               f"({r.returncode}, {cut.get('state')}, {again.get('blockers')})")
            d, _ = V("repair")
            ck(d.get("applied") and tree(ch) == before["claude"]
               and tree(ah / "backups") == before["backups"] and V()[0].get("state") == "off"
               and not list(base.glob("*.aht-plain-*")) and not list(ah.glob("*.aht-plain-*"))
               and not (ah / "vault").exists() and not list(base.glob("*.aht-vault.*"))
               and not list(ah.glob("*.aht-vault.*")) and A("projects", "--json").returncode == 0,
               f"{name}: repair puts every folder back as it was ({d.get('blockers')})")
        d, r = V("setup", "--apply", "--password-stdin", stdin=f"{pw}\n{pw}\n")
        state_text = (ah / "vault" / "vault.json").read_text() if d.get("applied") else ""
        plain = d.get("plain") or []
        ck(d.get("applied") and tree(ch) == before["claude"]
           and tree(ah / "backups") == before["backups"] and len(plain) == 2
           and all(os.path.isdir(x) for x in plain) and pw not in state_text
           and pw not in (read_text_or_none(ah / "aht.log") or ""),
           f"{name}: set up: every file is where it was, read back whole; the folders from "
           f"before stay beside them; the password is written nowhere ({d.get('blockers')}, "
           f"{r.stderr[-200:]})")
        ck((ah / "private" / "search.db").read_text() == "an index"
           and not (ah / "search.db").exists(),
           f"{name}: the search index moved into the vault")
        d, _ = V()
        ck(d.get("state") == "unlocked" and all(f["mounted"] for f in d["folders"])
           and len(d.get("plain", [])) == 2,
           f"{name}: status: unlocked, and the readable folders from before named ({d.get('state')})")
        r = A("uninstall")
        ck(r.returncode == 3 and "aht vault off --apply" in r.stdout,
           f"{name}: aht uninstall waits until the vault is off: Claude's folder is inside it "
           f"({r.stdout[:80]!r})")
        ok = A("projects", "--json")
        ck(ok.returncode == 0 and "locked" not in ok.stdout,
           f"{name}: unlocked, aht works as before ({ok.returncode})")

        p = session()
        d, _ = V("lock")
        ck(not d.get("applied") and "--end-sessions" in str(d.get("blockers"))
           and (proj / "s1.jsonl").is_file(),
           f"{name}: lock waits while a Claude session is open ({d.get('blockers')})")
        end(p)
        reg = (ah / "registry.json").read_bytes()
        d, _ = V("lock")
        locked_claude = sorted(x.name for x in ch.iterdir())
        try:
            (ch / "new.txt").write_text("x")
            wrote = True
        except OSError:
            wrote = False
        ck(d.get("applied") and locked_claude == ["LOCKED.txt"] and (not wrote or os.geteuid() == 0)
           and sorted(x.name for x in (ah / "backups").iterdir()) == ["LOCKED.txt"],
           f"{name}: locked: each folder is empty, read-only, with a note ({d.get('blockers')}, "
           f"{locked_claude})")
        d, _ = V()
        st = json.loads(A("status", "--json").stdout or "{}")
        ck(d.get("state") == "locked" and st.get("vault", {}).get("state") == "locked",
           f"{name}: status says locked, and aht status still answers ({d.get('state')})")
        r1 = A("projects", "--json")
        r2 = A("projects")
        r3 = A("hook")
        r4 = A("reconcile", "--quick")
        r5 = A("backup", "--auto")
        ck(r1.returncode == 3 and json.loads(r1.stdout).get("locked") is True
           and "aht vault unlock" in r2.stderr and r2.returncode == 3
           and (r3.returncode, r3.stdout, r3.stderr) == (0, "", "")
           and (r4.returncode, r4.stdout) == (0, "") and r5.returncode == 0
           and (ah / "registry.json").read_bytes() == reg
           and sorted(x.name for x in ch.iterdir()) == ["LOCKED.txt"],
           f"{name}: locked, aht stands down: a command says why, the hook and the watcher's "
           f"look say nothing, the registry is untouched ({r1.stdout[:60]}, {r2.stderr[:60]}, "
           f"{r3.returncode}, {r4.returncode}, {r5.returncode})")
        d, _ = V("finish", "--apply")
        ck(not d.get("applied") and "unlock the vault first" in str(d.get("blockers"))
           and all(os.path.isdir(x) for x in plain),
           f"{name}: finish, locked: the readable folders stay until it was unlocked once")
        d, _ = V("unlock", "--password-stdin", stdin="not the password\n")
        ck(not d.get("applied") and d.get("blockers") == ["wrong password"]
           and sorted(x.name for x in ch.iterdir()) == ["LOCKED.txt"],
           f"{name}: a wrong password opens nothing ({d.get('blockers')})")
        d, _ = V("unlock", "--password-stdin", stdin=pw + "\n")
        ck(d.get("applied") and len(d.get("opened", [])) == 3 and tree(ch) == before["claude"]
           and tree(ah / "backups") == before["backups"],
           f"{name}: the password unlocks it: every file is back ({d.get('blockers')})")
        (proj / "s2.jsonl").write_text("written while unlocked\n")
        after = tree(ch)

        new = "another password 9"
        d0, _ = V("password", "--password-stdin", stdin=f"{pw}\n{new}\n{new}\n")
        V("lock")
        d1, _ = V("password", "--password-stdin", stdin=f"nope nope\n{new}\n{new}\n")
        d2, _ = V("password", "--password-stdin", stdin=f"{pw}\n{new}\n{new}\n")
        d3, _ = V("unlock", "--password-stdin", stdin=pw + "\n")
        d4, _ = V("unlock", "--password-stdin", stdin=new + "\n")
        ck("lock it first" in str(d0.get("blockers")) and d1.get("blockers") == ["wrong password"]
           and d2.get("applied") and d3.get("blockers") == ["wrong password"]
           and d4.get("applied") and tree(ch) == after,
           f"{name}: the password changes while it is locked: the old one no longer opens it, "
           f"the new one does ({d0.get('blockers')}, {d1.get('blockers')}, {d2.get('blockers')}, "
           f"{d3.get('blockers')}, {d4.get('blockers')})")

        d1, _ = V("finish")
        d2, _ = V("finish", "--apply")
        ck(sorted(d1.get("plain", [])) == sorted(plain) and not d1.get("applied")
           and d2.get("applied") and not any(os.path.exists(x) for x in plain)
           and tree(ch) == after and V()[0].get("plain") == [],
           f"{name}: finish removes the readable folders from before, and nothing else "
           f"({d2.get('blockers')})")

        p = session("busy")
        d1, _ = V("lock", "--end-sessions")
        (ch / "sessions" / f"{p.pid}.json").write_text(json.dumps(
            {"pid": p.pid, "cwd": "/w/paper", "sessionId": "s1", "status": "idle", "name": "paper"}))
        d2, _ = V("lock", "--end-sessions")
        gone = p.poll() is not None or p.wait(timeout=5) is not None
        ck("working or waiting" in str(d1.get("blockers")) and d2.get("applied")
           and d2.get("ended") == ["paper"] and gone and V()[0].get("state") == "locked",
           f"{name}: lock --end-sessions: never a working session; an idle one ends, then it "
           f"locks ({d1.get('blockers')}, {d2})")
        V("unlock", "--password-stdin", stdin=new + "\n")
        (ch / "sessions" / f"{p.pid}.json").unlink(missing_ok=True)
        after = tree(ch)

        if keeper == "stand-in":
            d1, _ = V("lock", AHT_VAULT_BUSY="1")
            d2, _ = V("lock", "--force", AHT_VAULT_BUSY="1")
            ck(not d1.get("applied") and "still in use" in str(d1.get("blockers"))
               and d2.get("applied"),
               f"{name}: a folder a program still uses is not locked, and says so; --force "
               f"locks it ({d1.get('blockers')})")
            V("unlock", "--password-stdin", stdin=new + "\n")
        else:
            V("lock")
            images = list(base.glob("*.aht-vault.sparsebundle")) + list(ah.glob("*.aht-vault.sparsebundle"))
            band = b"".join(f.read_bytes() for i in images for f in i.rglob("*") if f.is_file())
            ck(len(images) == 3 and (base / "claude.aht-vault.sparsebundle").is_dir()
               and len(band) > 100_000 and secret.encode() not in band
               and b"correct horse" not in band and new.encode() not in band,
               f"{name}: locked, the images hold neither the words nor the password "
               f"({len(band)} bytes read)")
            V("unlock", "--password-stdin", stdin=new + "\n")

        d1, _ = V("off")
        V("lock")
        d2, _ = V("off", "--apply")
        V("unlock", "--password-stdin", stdin=new + "\n")
        d3, _ = V("off", "--apply")
        old = d3.get("old_images") or []
        ck(not d1.get("applied") and "unlock it first" in str(d2.get("blockers"))
           and d3.get("applied") and tree(ch) == after
           and tree(ah / "backups") == before["backups"]
           and (ah / "search.db").read_text() == "an index" and not (ah / "private").exists()
           and not os.path.ismount(ch) and V()[0].get("state") == "off" and len(old) == 3
           and all(os.path.exists(x) for x in old),
           f"{name}: off: plain folders again with every file, the index back; the images stay "
           f"for now ({d2.get('blockers')}, {d3.get('blockers')})")
        (ch / "after-off.txt").write_text("writable again")
        d, _ = V("finish", "--apply")
        r = A("uninstall")
        ck(d.get("applied") and not any(os.path.exists(x) for x in old)
           and not list(base.glob("*.aht-vault*")) and not list(ah.glob("*.aht-vault*"))
           and not (ah / "vault-removed.json").exists() and "a vault is set up" not in r.stdout,
           f"{name}: finish then removes the old images ({d.get('blockers')})")
    finally:                                # never leave an image mounted behind
        if keeper != "stand-in":
            for at in (ch, ah / "backups", ah / "private", ah / "vault" / "mnt-claude",
                       ah / "vault" / "mnt-backups", ah / "vault" / "mnt-private"):
                if os.path.ismount(at):
                    subprocess.run(["/usr/bin/hdiutil", "detach", str(at), "-force"],
                                   capture_output=True)
        for d in (ch, ah / "backups", ah / "private"):     # so the sandbox can be removed
            if d.is_dir():
                os.chmod(d, 0o700)


if os.name == "nt":
    print("  (skipped on Windows: the vault needs macOS for now, and its stand-in the "
          "folder modes of macOS and Linux)")
    r = run("vault", "setup", "--json")
    ck("needs macOS" in r.stdout, f"on Windows: setup says it needs macOS for now ({r.stdout[:120]})")
else:
    vault_suite("vault", "stand-in")
    if sys.platform == "darwin" and os.path.exists("/usr/bin/hdiutil") \
            and not os.environ.get("AHT_NO_HDIUTIL"):
        print("\n[24b] the vault, with real encrypted disk images (macOS)")
        vault_suite("mac", "hdiutil")
    else:
        print("  (real encrypted disk images are checked on a Mac only)")
        r = run("vault", "setup", "--json")
        ck(sys.platform == "darwin" or "needs macOS" in r.stdout,
           f"off a Mac: setup says it needs macOS for now ({r.stdout[:120]})")

done()
