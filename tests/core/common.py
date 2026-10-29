"""What every core test unit shares: its own sandbox (made when this is
imported), ck() and the ways to run aht in it.  A unit is one file in
tests/core/ that runs alone (`python tests/core/16_handover_rsync.py`) and
ends with done(); tests/core_test.py runs them all at once."""
import hashlib, json, os, shutil, subprocess, sys, tempfile

# a Windows console or pipe in cp1252 cannot print every character a check
# names (an NFD name, ✓, →): print them escaped there rather than stop
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="backslashreplace")
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent      # tests/
sys.path.insert(0, str(HERE))                      # fake_*.py
CLI = str(HERE.parent / "aht.py")
# what run() and iso_run() start: aht from its compiled cache
LAUNCH = str(HERE / "aht_launch.py")
PY = os.environ.get("AHT_PY", sys.executable or "python3")
# by its full path: the stand-in tools of a far "machine" run it with that
# machine's own PATH, where a bare name such as python3.13 is not found
PY = shutil.which(PY) or PY

FAILS = []
PASSED = [0]
def ck(cond, msg):
    print(("  PASS " if cond else "  FAIL ") + msg)
    if cond:
        PASSED[0] += 1
    else:
        FAILS.append(msg)

# the handover test's stand-in machine keeps a history folder named after
# the project's path there, which holds the sandbox's path twice: a long
# TMPDIR makes that name longer than the 255 characters a name may have
# (and a socket's path longer than the 104 a Mac allows, 108 on Linux).
# On a Mac the sandbox then goes to the user's own temporary folder, which
# is short; elsewhere those tests are skipped and say why
def handover_name(sandbox):
    return 2 * len(os.path.realpath(sandbox)) + len("/box/roots/Hand Over")
def socket_fits(sandbox):
    return len(os.path.join(str(sandbox), "api.sock")) < 104
def short_enough(sandbox):
    return handover_name(sandbox) <= 255 and socket_fits(sandbox)
_tmp = tempfile.gettempdir()
if not short_enough(os.path.join(_tmp, "aht_core_12345678")) and sys.platform == "darwin":
    _short = subprocess.run(["getconf", "DARWIN_USER_TEMP_DIR"], capture_output=True,
                            text=True).stdout.strip()
    if _short and short_enough(os.path.join(_short, "aht_core_12345678")):
        print(f"(the sandbox is in {_short}: TMPDIR is too long for the handover test)")
        _tmp = _short
SANDBOXES = []         # every sandbox this unit made: done() removes them
def make_sandbox():
    """(sb, roots, tools, env, fakebin): a throwaway home for aht and every
    agent's store, HOME included, so nothing here reaches the real one."""
    sb = Path(tempfile.mkdtemp(prefix="aht_core_", dir=_tmp))
    SANDBOXES.append(sb)
    roots = sb / "roots"
    tools = sb / "tools"
    for d in ("claude", "gemini", "cursor", "opencode", "codex", "copilot",
              "kimi/sessions", "kimi/user-history", "kimi-code/sessions", "vibe", "agy"):
        (tools / d).mkdir(parents=True)
    (roots / "projA").mkdir(parents=True)
    (sb / "home").mkdir()
    env = dict(os.environ)
    env.update({
        "HOME": str(sb / "home"),
        "AHT_TEST_LAUNCHER": LAUNCH,    # aht starts itself from its compiled cache too
        # no detached index update: it would outlive the unit and write in its
        # sandbox after done() (`search` updates the index itself)
        "AHT_NO_SEARCH_INDEX": "1",
        "AHT_HOME": str(sb / ".aht"),
        "AHT_ROOTS": str(roots),
        "AHT_ROOT_CLAUDE": str(tools / "claude"),
        "AHT_ROOT_GEMINI": str(tools / "gemini"),
        "AHT_ROOT_CURSOR": str(tools / "cursor"),
        "AHT_ROOT_OPENCODE": str(tools / "opencode"),
        "AHT_ROOT_CODEX": str(tools / "codex"),
        "AHT_ROOT_COPILOT": str(tools / "copilot"),
        "AHT_ROOT_KIMI": str(tools / "kimi" / "sessions"),
        "AHT_ROOT_KIMI_CODE": str(tools / "kimi-code" / "sessions"),
        "AHT_ROOT_VIBE": str(tools / "vibe"),       # never $VIBE_HOME, never ~/.vibe
        "AHT_ROOT_AGY": str(tools / "agy"),         # never ~/.gemini/antigravity-cli
        "AHT_NO_ICONS": "1", "AHT_NO_NOTIFY": "1", "AHT_NO_BACKUP": "1",
        "AHT_NO_CHECKPOINT": "1",       # the checkpoint test turns it back on
    })
    env.pop("AHT_ASSUME", None)
    env.pop("AHT_TRANSFER", None)
    # stand-ins first on PATH: no test may reach the real launchd, systemd or
    # Task Scheduler (a watcher reload goes through them), nor keep this machine
    # awake (`remote check` tries caffeinate or systemd-inhibit there, and
    # GNOME's inhibitor through the session bus, which is none here)
    fakebin = sb / "fakebin"
    fakebin.mkdir()
    for _t in ("launchctl", "systemctl", "schtasks", "caffeinate", "systemd-inhibit",
               "gnome-session-inhibit"):
        (fakebin / _t).write_text(f"#!/bin/sh\necho \"{_t} $*\" >> '{fakebin / 'calls.log'}'\n")
        (fakebin / _t).chmod(0o755)
    env["PATH"] = str(fakebin) + os.pathsep + env.get("PATH", "")
    env["AHT_SESSION_BUS"] = str(sb / "no-session-bus")
    return sb, roots, tools, env, fakebin

# this unit's own sandbox: run() and iso_env() use it.  A unit that needs
# another one calls make_sandbox() and passes that env along itself
sb, roots, tools, env, FAKEBIN = make_sandbox()
os.environ["HOME"] = env["HOME"]       # aht imported here, and git, too
os.environ["AHT_TEST_LAUNCHER"] = LAUNCH
os.environ["AHT_NO_SEARCH_INDEX"] = "1"

def run(*a, **kw):
    e = dict(env); e.update(kw.pop("extra_env", {}))
    return subprocess.run([PY, LAUNCH, *a], env=e, capture_output=True, text=True)

def iso_env(name):
    """A sandbox of its own: HOME, AHT_HOME and every agent's store, and no
    AHT_ROOTS, so the watched folders follow HOME as they do for a user."""
    base = Path(os.path.realpath(sb)) / name
    e = dict(env, HOME=str(base / "home"), AHT_HOME=str(base / ".aht"))
    e.pop("AHT_ROOTS", None)
    for k in [k for k in e if k.startswith("AHT_ROOT_")]:
        (base / "tools" / k[9:].lower()).mkdir(parents=True, exist_ok=True)
        e[k] = str(base / "tools" / k[9:].lower())
    (base / "home").mkdir(parents=True, exist_ok=True)
    return e

def iso_run(e, *a, stdin=None):
    return subprocess.run([PY, LAUNCH, *a], env=e, input=stdin, capture_output=True, text=True)

enc = lambda p: __import__("re").sub(r"[^a-zA-Z0-9]", "-", p)
sha = lambda p: hashlib.sha256(p.encode()).hexdigest()
md5 = lambda p: hashlib.md5(p.encode()).hexdigest()

def mkstores(path):
    """Fake per-tool history for a project at `path` (realpath expected)."""
    (tools / "claude" / enc(path)).mkdir(exist_ok=True)
    (tools / "claude" / enc(path) / "s1.jsonl").write_text(
        json.dumps({"cwd": path}) + "\n"
        + json.dumps({"text": f"see {path}/src/main.py"}) + "\n")
    (tools / "gemini" / sha(path)).mkdir(exist_ok=True)
    (tools / "gemini" / sha(path) / "chat.json").write_text('{"g": 1}')
    (tools / "cursor" / md5(path)).mkdir(exist_ok=True)
    (tools / "cursor" / md5(path) / "store.db").write_text("c")
    (tools / "opencode" / enc(path)).mkdir(exist_ok=True)
    (tools / "opencode" / enc(path) / "session.json").write_text('{"o": 1}')
    day = tools / "codex" / "2026" / "08" / "29"
    day.mkdir(parents=True, exist_ok=True)
    (day / f"rollout-{abs(hash(path)) % 10**8}.jsonl").write_text(
        json.dumps({"type": "session_meta",
                    "payload": {"cwd": path, "id": "x"}}) + "\n"
        + json.dumps({"type": "turn", "text": "hi"}) + "\n")
    (tools / "copilot" / f"sess-{abs(hash(path)) % 10**8}.json").write_text(
        json.dumps({"cwd": path, "summary": "s"}))
    kd = tools / "kimi" / "sessions" / md5(path) / "sess-uuid-1"
    kd.mkdir(parents=True, exist_ok=True)
    (kd / "state.json").write_text('{"version": 1}')
    (kd / "wire.jsonl").write_text('{"k": 1}\n')
    (tools / "kimi" / "user-history" / (md5(path) + ".jsonl")).write_text(
        '{"h": 1}\n')


# the core itself, imported here in this unit's sandbox (as aht runs it)
os.environ["AHT_HOME"] = str(sb / ".aht")
if os.name == "nt":            # the core needs fcntl, which the Windows layer brings
    sys.path.insert(0, str(HERE.parent / "windows" / "src"))
    import win_fcntl
    sys.modules.setdefault("fcntl", win_fcntl)
sys.path.insert(0, str(HERE.parent))
import time, unicodedata
import aht as core

def read_text_or_none(p):
    try:
        return Path(p).read_text().strip()
    except OSError:
        return None

# the JSON the front-ends read: the suite's own output must keep every key of
# the samples in tests/fixtures/phase1 (the front-ends are built against them)
FIXTURES = HERE / "fixtures" / "phase1"
OPAQUE = {"remotes"}         # maps keyed by the user's own names
def same_shape(real, sample, where="") -> list:
    """Keys of `sample` missing from `real`, recursively."""
    if isinstance(sample, dict):
        if not isinstance(real, dict):
            return [where or "."]
        miss = []
        for k, v in sample.items():
            if k not in real:
                miss.append(f"{where}.{k}")
            elif v is not None and real[k] is not None and k not in OPAQUE:
                miss += same_shape(real[k], v, f"{where}.{k}")
        return miss
    if isinstance(sample, list) and sample and isinstance(real, list) and real:
        return same_shape(real[0], sample[0], where + "[0]")
    return []
FIXTURES2 = HERE / "fixtures" / "phase2"
FIXTURES6 = HERE / "fixtures" / "phase6"
def fixture_ok(real, name: str, folder: Path = None, keys=None) -> list:
    """`keys`: compare only those of the sample's (a sample of a whole
    `status`, say, of which a test looks at a part)."""
    if os.environ.get("AHT_FIXTURE_DUMP"):          # to make new samples from
        Path(os.environ["AHT_FIXTURE_DUMP"]).mkdir(parents=True, exist_ok=True)
        (Path(os.environ["AHT_FIXTURE_DUMP"]) / name).write_text(json.dumps(real, indent=2))
    try:
        sample = json.loads(((folder or FIXTURES) / name).read_text())
    except (OSError, ValueError) as e:
        return [f"{name}: {e}"]
    if keys:
        sample = {k: v for k, v in sample.items() if k in keys}
    return [f"{name}{m}" for m in same_shape(real, sample)]

FIXTURES7 = HERE / "fixtures" / "phase7"
FIXTURES7B = HERE / "fixtures" / "phase7b"

def stat_mode(p) -> int:
    return os.stat(p).st_mode & 0o777

def kkey(path):
    import re as _re
    norm = _re.sub(r"/+$", "", path.replace("\\", "/"))
    slug = _re.sub(r"^-+|-+$", "", _re.sub(r"[^a-z0-9._-]+", "-",
                                            norm.split("/")[-1].lower()))[:40]
    return f"wd_{slug}_{sha(norm)[:12]}"

from datetime import datetime, timezone
def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")
KEY = "sk-" + "ant-" + "api03-" + "Xq7" * 12            # a made-up key, built in pieces

def JS(*a, **kw):
    r = run(*a, **kw)
    try:
        return json.loads(r.stdout)
    except Exception:
        return {"unparsed": r.stdout[-300:] + r.stderr[-300:]}


def _remove(dirs):
    """Remove the sandboxes for good: aht's own detached work (the search
    index update that a reconcile or the hook starts) may still write there
    for a moment after the unit ends, and would make a folder again."""
    gone = 0
    for _ in range(40):                 # at most 10 s
        left = [d for d in dirs if os.path.lexists(d)]
        for d in left:
            shutil.rmtree(d, ignore_errors=True)
        gone = 0 if left else gone + 1
        if gone >= 4:                   # all gone for a whole second
            return
        time.sleep(0.25)


def _stopped(*_):
    """The runner stops a unit that ran too long, or all of them on Ctrl-C:
    its sandboxes go all the same."""
    _remove(SANDBOXES)
    os._exit(143)


if os.name != "nt":
    import signal
    signal.signal(signal.SIGTERM, _stopped)


def done():
    """Remove this unit's sandboxes, say how it went, and end."""
    _remove(SANDBOXES)
    print(f"\nUNIT RESULT: {'ALL PASS' if not FAILS else f'{len(FAILS)} FAIL'}"
          f" ({PASSED[0]} passed)")
    for f in FAILS:
        print("  -", f)
    sys.exit(1 if FAILS else 0)
