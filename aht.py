#!/usr/bin/env python3
"""
agent-history-tether (aht): keep every AI coding agent's per-project history
connected to its project folder when the folder is moved, renamed, copied or
nested — one watcher, one identity marker, many agent CLIs.

CROSS-PLATFORM: this file is the shared core for macOS, Linux and Windows.
Platform specifics are isolated behind seams — ask_dialog(), apply_badge(),
watcher_status()/_reload_watcher() — patched by ./linux, ./macos and ./windows.

BACKENDS: each supported agent CLI is a backend describing where it stores
per-project history and how that storage is keyed:

  dir-rename family (storage dir named by a function of the project path;
  relink = rename the dir; SELF-VERIFYING: we only act when key(old_path)
  names an existing dir, which proves the key function matches reality):
    claude    Claude Code          ~/.claude/projects/<non-alnum -> "-">   verified
    gemini    Gemini CLI           ~/.gemini/tmp/<sha256(path)>            high
    cursor    Cursor Agent CLI     ~/.cursor/chats/<md5|sha256(path)>      best-effort
    opencode  OpenCode             $XDG_DATA_HOME/opencode/project/<enc>   best-effort

  metadata-rewrite family (sessions live in a global store with the project
  cwd recorded inside; relink = rewrite those cwd values; the touched files
  are ALWAYS copied into the backup store first):
    codex     OpenAI Codex CLI     ~/.codex/sessions/**/*.jsonl            high
    copilot   GitHub Copilot CLI   ~/.copilot/history-session-state/**     best-effort

    kimi      Kimi Code            ~/.kimi/sessions/<md5(path)>         verified
              (+ companion ~/.kimi/user-history/<md5>.jsonl, renamed along)

SAFETY invariants (inherited, kept):
  (1) History is NEVER deleted; dir renames never merge into an occupied
      target; metadata rewrites are preceded by a mandatory backup copy.
  (2) Adoption is ADD-ONLY and store-corroborated.
  (3) Registry writes happen under one lock, never held across a dialog;
      cyclic renames resolve via two-phase staging per backend.
"""

from __future__ import annotations   # 3.9-safe

import fnmatch
import hashlib
import os
import re
import shlex
import stat
import sys
import json
import uuid as _uuid
import shutil
import fcntl
import time
import argparse
import platform
import subprocess
import unicodedata
from pathlib import Path

VERSION = "0.13.0"

IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

# --------------------------------------------------------------------------- #
# Locations (all overridable via env for isolated testing)
# --------------------------------------------------------------------------- #

def aht_home() -> Path:
    return Path(os.environ.get("AHT_HOME", str(Path.home() / ".aht"))).expanduser()

def registry_path() -> Path:
    return aht_home() / "registry.json"

def log_path() -> Path:
    return aht_home() / "aht.log"

def lock_path() -> Path:
    return aht_home() / ".lock"

def config_path() -> Path:
    return aht_home() / "config.json"

def _default_watch_roots() -> list:
    home = Path.home()
    roots = [str(home / "Desktop"), str(home / "Documents")]
    extra = [home / "code", home / "src", home / "source", home / "Projects",
             home / "projects", home / "dev", home / "workspace", home / "git"]
    roots += [_disk_case(str(p)) for p in extra if p.is_dir()]
    return _distinct_dirs(roots)

# a Mac and Windows ignore case: ~/code opens ~/Code there
CASE_BLIND = IS_MAC or os.name == "nt"

def _disk_case(p: str) -> str:
    """`p` spelled as it is on disk.  Where case does not matter ~/code also
    opens ~/Code, and realpath keeps the case it was given; the agents record
    the name as it is on disk, so a path spelled otherwise names no project."""
    if not CASE_BLIND or not os.path.isdir(p):
        return p
    parts = Path(p).parts
    try:
        cur = Path(parts[0])
        for name in parts[1:]:
            names = os.listdir(cur)
            if name not in names:
                name = next((n for n in names if n.casefold() == name.casefold()), name)
            cur = cur / name
        return str(cur)
    except (OSError, IndexError):
        return p

def _folder_key(p: str):
    """What tells folders apart: the file system's own id where there is
    one, so two spellings of one folder are one folder."""
    try:
        st = os.stat(p)
        return (st.st_dev, st.st_ino) if st.st_ino else os.path.normcase(os.path.realpath(p))
    except OSError:
        return p

def _same_folder(a: str, b: str) -> bool:
    """One folder under two spellings.  The file ids say so only where the
    file system has them: some Windows drives give every file id 0, and
    then the paths are compared, as _folder_key does."""
    try:
        s1, s2 = os.stat(a), os.stat(b)
    except OSError:
        return False
    if s1.st_ino and s2.st_ino:
        return s1.st_ino == s2.st_ino and s1.st_dev == s2.st_dev
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))

def _distinct_dirs(paths: list) -> list:
    """Each folder once: on a Mac or Windows ~/Projects and ~/projects are one
    folder, which only the file system can tell."""
    seen, out = set(), []
    for p in paths:
        key = _folder_key(p)
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out

def _expand(p: str) -> str:
    return str(Path(os.path.expanduser(os.path.expandvars(p))))

CONFIG_DEFAULTS = {
    "watch_roots":      None,        # None -> _default_watch_roots()
    "backends":         None,        # None -> every backend; else list of names
    "backend_roots":    None,        # None -> defaults; else {name: store_path}
                                     #   (for a CLI whose store was not found
                                     #    automatically — set via `aht backends`)
    "move_policy":      "ask",       # ask | apply | decline | ignore
    "copy_policy":      "ask",       # ask | duplicate | independent | ignore
    "notifications":    True,
    "icons_enabled":    True,
    "icons_agent":      True,        # badge tethered projects
    "icons_git":        True,        # badge git repos under the watched roots
    "debounce_seconds": 2.0,
    "scan_max_depth":   7,
    "extra_prune_dirs": [],
    "dialog_timeout":   180,
    "log_level":        "info",      # debug | info | warn | error
    "watcher_owner":    "agent",     # agent (LaunchAgent/systemd/RunKey) | none
    "backup_enabled":   True,
    "backup_interval_hours": 24.0,
    "backup_keep":      10,          # per project; the copies on the other machine
                                     #   follow it, keeping at least 3
    "backup_dir":       None,        # None -> <aht_home>/backups
    "linux_emblem_method": "auto",   # auto | gio | kde | both | none
    "linux_agent_emblem": "emblem-favorite",
    "linux_git_emblem":   "aht-git",     # aht's own "+", drawn like the agent emblems
    # handover: run a project on another machine of yours (see `aht remote`)
    "remotes":          None,        # {name: {"ssh": "user@host", "system": "Linux"}}
                                     #   (tests on a real machine: "sandbox": a
                                     #   folder there that holds everything)
    "default_remote":   None,
    "mirror_interval_minutes": 30,   # background sync of mirrored projects
    "handover_excludes": [],         # extra names that never travel
    "handover_compress": True,       # rsync -z: histories and code are text
    "handover_remote_control": True, # reachable from the Claude app
    "handover_carry_trust": True,    # a folder trusted here is trusted there
    "handover_claude_args": [],      # extra arguments for the resumed session
    "handover_mosh":    True,        # attach with mosh when both sides have it
    "rsync_path":       None,        # None -> the newest rsync found
    # notices: a session that waits for you, or finished a long piece of work
    "notify_waiting":   True,
    "notify_finished":  True,
    "notify_finished_minutes": 3,
    "notify_phone":     None,        # "imessage:<phone or Apple ID>" | "ntfy:<topic>"
    "offsite_backup":   None,        # a machine that keeps a copy of the backups
    "report_areas":     None,        # {"Work": "~/Desktop/Workspace/Work", …}
    "hotkey":           "ctrl+opt+cmd+a",   # opens the search from anywhere
    "terminal_app":     None,        # macOS: app that opens a session window
    "update_check":     False,       # once a day, ask GitHub for the latest
                                     #   release (off until turned on)
    # before and after a session.  USES TOKENS = off until turned on
    "informed_sessions": False,      # USES TOKENS: a new session learns where the
                                     #   last one in its folder stopped
    "notify_limit":     True,        # say so when Claude hits its usage limit
    "limit_switch":     False,       # USES TOKENS: offer to go on in another agent
    "limit_switch_to":  "kimi",      #   … this one
    "checkpoints":      True,        # a copy of the folder when a session starts
    "checkpoint_keep":  10,          #   per project
    "checkpoint_max_files": 20000,   #   bigger folders get none (see `aht
                                     #   checkpoint --coverage`)
    "checkpoint_excludes": [],       #   extra names left out of the copies
    "second_opinion":   False,       # USES TOKENS: one task, two agents, compared
    "night_shift":      False,       # USES TOKENS: a handover with a task, on a timer
    "spotlight":        True,        # session titles in Spotlight (the app)
    "tab_names":        True,        # a Claude session is named after its iTerm2
                                     #   tab (what the Claude app shows)
    "workspace_save_minutes": 10,    # the app saves the iTerm2 layout this often
                                     #   (0: only when a session gets a prompt)
    "workspace_keep":   40,          #   the last this many layouts are kept
    "session_corner":   False,       # the app lists the open Claude sessions in
                                     #   the screen's top-right corner
    "chimes":           False,       # the app chimes when a session here is done
                                     #   or waits for you
    "chime_done":       "Bloom",     #   aht's own chime, a macOS sound's name or
    "chime_waiting":    "Doorbell",  #   a sound file; "" = none
    "chime_limit":      "Ebb",       #   (with the usage-limit notice)
    "chime_done_after": 30,          #   "done" after work of this many seconds
    "chime_volume":     70,          #   0-100
}

POLICY_CHOICES = {
    "moves":  ("ask", "apply", "decline", "ignore"),
    "copies": ("ask", "duplicate", "independent", "ignore"),
}

# settings aht no longer has: an old config may still hold them, and they
# are ignored and not shown; `config --set` says why and goes on
RETIRED_KEYS = {"new_policy": "aht always takes on a new project"}

def cfg_get(key, default=None):
    cfg = load_config()
    if key in cfg and cfg[key] is not None:
        return cfg[key]
    if CONFIG_DEFAULTS.get(key) is not None:
        return CONFIG_DEFAULTS[key]
    return default

def _coerce(key: str, raw: str):
    d = CONFIG_DEFAULTS.get(key)
    if isinstance(d, bool):
        low = raw.strip().lower()
        if low in ("1", "true", "yes", "on"):
            return True
        if low in ("0", "false", "no", "off"):
            return False
        raise ValueError(f"{key} expects a boolean, got {raw!r}")
    if isinstance(d, float):
        return float(raw)
    if key == "chime_volume":
        return max(0, min(100, int(raw)))
    if isinstance(d, int) and not isinstance(d, bool):
        return int(raw)
    if key == "log_level":
        v = raw.strip().lower()
        if v not in LOG_LEVELS:
            raise ValueError(f"log_level expects one of {sorted(LOG_LEVELS)}")
        return v
    if key == "limit_switch_to":
        v = raw.strip().lower()
        if v not in SWITCH_TARGETS or v == "claude":
            raise ValueError("limit_switch_to expects one of "
                             f"{[t for t in SWITCH_TARGETS if t != 'claude']}")
        return v
    if key == "report_areas":
        try:
            obj = json.loads(raw)
            if not isinstance(obj, dict):
                raise ValueError("expects a JSON object")
        except Exception as e:
            raise ValueError(f'{key}: {e} — e.g. {{"Work": "~/Desktop/Work"}}')
        return {str(k): _expand(str(v)) for k, v in obj.items()}
    if key == "remotes":
        try:
            obj = json.loads(raw)
            if not isinstance(obj, dict) or not all(
                    isinstance(v, dict) for v in obj.values()):
                raise ValueError("expects a JSON object of objects")
        except Exception as e:
            raise ValueError(f"{key}: {e} — prefer `aht remote add <name> "
                             f"<user@host>`")
        return obj
    if key == "backend_roots":
        try:
            obj = json.loads(raw)
            if not isinstance(obj, dict):
                raise ValueError("expects a JSON object")
        except Exception as e:
            raise ValueError(f"{key}: {e} — prefer `aht backends --set-root "
                             f"name=/path`")
        bad = [k for k in obj if k not in BACKEND_NAMES + [AGY_STORE.name]]
        if bad:
            raise ValueError(f"unknown backend(s) {bad}")
        return {k: _expand(str(v)) for k, v in obj.items()}
    if isinstance(d, list) or key in ("watch_roots", "backends"):
        raw = raw.strip()
        if raw.startswith("["):
            try:
                parts = [str(x) for x in json.loads(raw)]
            except Exception as e:
                raise ValueError(f"{key}: invalid JSON list ({e})")
        else:
            parts = [x.strip() for x in raw.split(",")]
        parts = [p for p in parts if p]
        if key == "watch_roots":
            return [_expand(p) for p in parts]
        if key == "backends":
            bad = [p for p in parts if p not in BACKEND_NAMES]
            if bad:
                raise ValueError(f"unknown backend(s) {bad}; "
                                 f"known: {', '.join(BACKEND_NAMES)}")
        return parts
    return raw

_CONFIG_CACHE = {"path": None, "mtime": None, "data": {}}

def load_config() -> dict:
    p = config_path()
    try:
        mtime = p.stat().st_mtime
    except OSError:
        _CONFIG_CACHE.update(path=str(p), mtime=None, data={})
        return {}
    c = _CONFIG_CACHE
    if c["path"] == str(p) and c["mtime"] == mtime:
        return c["data"]
    try:
        with open(p) as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("config is not a JSON object")
        for k in RETIRED_KEYS:
            data.pop(k, None)
    except Exception as e:
        warn(f"config load failed ({e}); using defaults")
        data = {}
    _CONFIG_CACHE.update(path=str(p), mtime=mtime, data=data)
    return data

def save_config(cfg: dict) -> None:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    with open(tmp, "w") as fh:
        json.dump(cfg, fh, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, p)
    _CONFIG_CACHE.update(path=None, mtime=None, data={})

def ensure_config() -> dict:
    cfg = load_config()
    if "watch_roots" not in cfg:
        cfg["watch_roots"] = _default_watch_roots()
        save_config(cfg)
    return cfg

def watch_roots_config() -> list:
    env = os.environ.get("AHT_ROOTS")
    if env:                         # each once, spelled as on disk, as below
        return _distinct_dirs([_disk_case(os.path.realpath(_expand(p)))
                               for p in env.split(os.pathsep) if p])
    roots = load_config().get("watch_roots")
    if roots:                       # each once, spelled as on disk
        return _distinct_dirs([_disk_case(_expand(r)) for r in roots if r])
    return _default_watch_roots()

def default_roots() -> list:
    return watch_roots_config()

MARKER_REL = os.path.join(".aht", ".project-id")
LEGACY_MARKER_REL = os.path.join(".claude", ".project-id")   # older marker form
STAGING_PREFIX = ".aht-staging-"
GIT_SCAN_INTERVAL = 60.0

PRUNE_DIRS = {
    ".git", "node_modules", ".venv", "venv", "env", "__pycache__",
    ".Trash", "Library", ".npm", ".cache", ".cargo", ".rustup",
    "DerivedData", ".gradle", ".idea", ".vscode", "Pods",
    "site-packages", ".mypy_cache", ".pytest_cache", ".next", "dist",
    "build", ".terraform",
}

def prune_dirs() -> set:
    try:
        extra = cfg_get("extra_prune_dirs") or []
        return PRUNE_DIRS | {str(x) for x in extra}
    except Exception:
        return PRUNE_DIRS

# --------------------------------------------------------------------------- #
# Small utilities
# --------------------------------------------------------------------------- #

LOG_LEVELS = {"debug": 10, "info": 20, "warn": 30, "error": 40}
LOG_MAX_BYTES = 5_000_000            # rotate to aht.log.1 beyond this

def log(msg: str, level: str = "info") -> None:
    """Leveled, size-rotated logging.  The threshold comes from the config
    CACHE only (never a fresh load) so a broken config can't recurse."""
    try:
        threshold = str(_CONFIG_CACHE["data"].get("log_level", "info"))
        if LOG_LEVELS.get(level, 20) < LOG_LEVELS.get(threshold, 20):
            return
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        aht_home().mkdir(parents=True, exist_ok=True)
        p = log_path()
        try:
            if p.stat().st_size > LOG_MAX_BYTES:
                os.replace(p, p.with_suffix(".log.1"))
        except OSError:
            pass
        with open(p, "a") as fh:
            fh.write(f"[{ts}] [{level.upper():<5}] {msg}\n")
    except Exception:
        pass

def warn(msg: str) -> None:
    log(msg, "warn")

def error(msg: str) -> None:
    log(msg, "error")

def new_uuid() -> str:
    return _uuid.uuid4().hex

def _as_literal(s: str) -> str:
    s = s.replace("\\", "\\\\").replace('"', '\\"')
    s = s.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return '"' + s + '"'

def _dialog_timeout() -> int:
    try:
        return int(cfg_get("dialog_timeout", 180))
    except Exception:
        return 180

# --------------------------------------------------------------------------- #
# Backends: where each agent CLI keeps per-project history, and how it's keyed
# --------------------------------------------------------------------------- #

def _key_claude(p: str) -> str:
    """Claude Code's cwd -> dirname encoding, verified against the CLI."""
    return re.sub(r"[^a-zA-Z0-9]", "-", p)

def _key_sha256(p: str) -> str:
    return hashlib.sha256(p.encode("utf-8")).hexdigest()

def _key_md5(p: str) -> str:
    return hashlib.md5(p.encode("utf-8")).hexdigest()

def _key_dash(p: str) -> str:
    return p.replace(os.sep, "-")

def _kimi_slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9._-]+", "-", name.lower())
    s = re.sub(r"^-+|-+$", "", s)[:40]
    s = re.sub(r"^-+|-+$", "", s)
    return "workspace" if s in ("", ".", "..") else s

def _key_kimicode(p: str) -> str:
    """Kimi Code 2.x workspace bucket, `wd_<slug>_<sha256[:12]>` — a port of
    encodeWorkDirKey() in the CLI's own source (workdir-slug.ts): the path is
    slash-normalised, the leaf is slugified (40 chars max) and the hash covers
    the whole normalised path."""
    norm = re.sub(r"/+$", "", p.replace("\\", "/"))
    return "wd_%s_%s" % (_kimi_slug(norm.split("/")[-1]),
                         hashlib.sha256(norm.encode("utf-8")).hexdigest()[:12])

def _xdg_data() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME",
                               str(Path.home() / ".local" / "share")))

def _swap_json_path_values(text: str, keys: tuple, old: str, new: str) -> tuple:
    """Re-point string values of the given JSON keys from `old` to `new`
    (exact, or `old` as a path prefix) by editing ONLY those values in the raw
    text, so every other byte of the file stays as the tool wrote it."""
    old_in = json.dumps(old, ensure_ascii=False)[1:-1]
    new_in = json.dumps(new, ensure_ascii=False)[1:-1]
    pat = re.compile(r'("(?:%s)"\s*:\s*")%s(?=["/]|\\\\)'
                     % ("|".join(re.escape(k) for k in keys), re.escape(old_in)))
    return pat.subn(lambda m: m.group(1) + new_in, text)

class Backend:
    kind = "stub"

    def __init__(self, name, label, confidence, root_default, note="",
                 agent=None):
        self.name = name
        self.label = label
        self.confidence = confidence
        self._root_default = root_default
        self.note = note
        # the agent a store belongs to — what the badges and prompts show; two
        # backends can serve one agent (a CLI that changed its store layout)
        self.agent = agent or name

    def _env_key(self) -> str:
        return "AHT_ROOT_" + self.name.upper().replace("-", "_")

    def root(self) -> Path:
        env = os.environ.get(self._env_key())
        if env:
            return Path(env).expanduser()
        try:
            cfg = cfg_get("backend_roots") or {}
            if cfg.get(self.name):
                return Path(_expand(str(cfg[self.name])))
        except Exception:
            pass
        return Path(self._root_default() if callable(self._root_default)
                    else self._root_default).expanduser()

    def root_source(self) -> str:
        if os.environ.get(self._env_key()):
            return "env"
        try:
            if (cfg_get("backend_roots") or {}).get(self.name):
                return "config"
        except Exception:
            pass
        return "default"

    def available(self) -> bool:
        return self.root().is_dir()

class DirBackend(Backend):
    """Storage dir named by key(path); relink = rename.  Self-verifying: we
    only act when key(old_path) names an existing dir.  Some tools keep a
    sibling per-project file keyed the same way (kimi: user-history/<key>.jsonl)
    — declared as a companion so relink/copy/backup carry it along."""
    kind = "dir"

    def __init__(self, name, label, confidence, root_default, keys,
                 companion_subdir=None, **kw):
        super().__init__(name, label, confidence, root_default, **kw)
        self.keys = keys
        self._companion = companion_subdir      # (sibling_dir, suffix) or None

    def companions(self, key: str, real_path: str, for_copy: bool = False) -> list:
        """[(tag, path)] sibling files that belong to the store `key` of the
        project at `real_path`.  The tag names the file inside a backup zip
        (`<backend>/__aht_companion__<tag>`), so it must stay stable.
        `for_copy` leaves out files that must not be shared by a duplicate."""
        if not self._companion:
            return []
        sub, suffix = self._companion
        return [(suffix, self.root().parent / sub / (key + suffix))]

    def find(self, real_path: str):
        """-> (key_index, existing_store_dir) or None.  An EMPTY directory is
        not a store: tools leave those behind, and they hold no history."""
        if not self.available():
            return None
        for i, k in enumerate(self.keys):
            d = self.root() / k(real_path)
            if d.is_dir() and _dir_has_entries(d):
                return i, d
        return None

    # seams for stores that also record the project path INSIDE their files;
    # each returns a short note for the log (or "")
    def after_relink(self, uid, old_real, new_real, old_key, new_dir) -> str:
        return ""

    def after_copy(self, uid, src_real, new_real, new_dir) -> str:
        return ""

    def after_restore(self, uid, old_real, new_real, new_dir, added) -> str:
        return ""

def _dir_has_entries(d: Path) -> bool:
    try:
        with os.scandir(d) as it:
            return next(it, None) is not None
    except OSError:
        return False

class KimiCodeBackend(DirBackend):
    """Kimi Code 2.x (`~/.kimi-code`, or $KIMI_CODE_HOME).  Sessions live in
    `sessions/wd_<slug>_<hash12>/<session>/` and the session picker finds them
    purely by that bucket name, so the rename is what reconnects a moved
    project.  Around it the CLI also keeps, per project:
      user-history/<md5(cwd)>.jsonl   prompt history        -> companion
      file-history/<bucket>           retention ledger      -> companion
      <session>/state.json  "cwd"     the dir a RESUMED session runs in
      workspaces.json                 catalog: bucket -> {root, name}
      session_index.jsonl             append-only {sessionId, sessionDir, workDir}
      sessions/.index-dirty/          journal that makes the CLI re-read a session
    Transcripts (wire.jsonl) mention paths too but are history: never edited.
    workspace-trust/ is a security decision about a location: never carried."""

    PATH_KEYS = ("cwd",)

    def home(self) -> Path:
        return self.root().parent

    def companions(self, key: str, real_path: str, for_copy: bool = False) -> list:
        h = self.home()
        out = [(".jsonl", h / "user-history" / (_key_md5(real_path) + ".jsonl"))]
        if not for_copy:
            # the ledger names the ORIGINAL's session ids: a duplicate has its own
            out.append((".file-history", h / "file-history" / key))
        return out

    def _sessions(self, bucket: Path) -> list:
        try:
            return sorted(d for d in bucket.iterdir()
                          if d.is_dir() and (d / "state.json").is_file())
        except OSError:
            return []

    def _repoint_state(self, state: Path, old: str, new: str) -> int:
        text = state.read_text(encoding="utf-8")
        text2, n = _swap_json_path_values(text, self.PATH_KEYS, old, new)
        if n:
            tmp = Path(str(state) + ".aht-tmp")
            tmp.write_text(text2, encoding="utf-8")
            os.replace(tmp, state)
        return n

    def _announce(self, sessions: list, work_dir: str) -> None:
        """Tell the CLI about sessions at a new place the way it tells itself:
        append to its session log (never rewritten — the CLI compacts stale
        lines on its own) and leave a dirty mark so its index re-reads them."""
        if not sessions:
            return
        idx = self.home() / "session_index.jsonl"
        try:
            if idx.is_file():
                lines = "".join(json.dumps(
                    {"sessionId": s.name, "sessionDir": str(s), "workDir": work_dir},
                    ensure_ascii=False, separators=(",", ":")) + "\n"
                    for s in sessions)
                with open(idx, "rb") as fh:
                    fh.seek(0, os.SEEK_END)
                    if fh.tell():
                        fh.seek(-1, os.SEEK_END)
                        if fh.read(1) != b"\n":
                            lines = "\n" + lines
                with open(idx, "a", encoding="utf-8") as fh:
                    fh.write(lines)
        except OSError as e:
            warn(f"[{self.name}] session index not updated: {e}")
        dirty = self.root() / ".index-dirty"
        if dirty.is_dir():
            ms = int(time.time() * 1000)
            for s in sessions:
                try:
                    (dirty / f"{s.name}.{ms}").touch()
                except OSError:
                    pass

    def _recatalog(self, old_real, new_real, old_key, new_key, bdir) -> bool:
        """Rename the project's entry in workspaces.json.  Only when the file
        is exactly the shape we know and the old entry points at old_real."""
        cat = self.home() / "workspaces.json"
        try:
            data = json.loads(cat.read_text(encoding="utf-8"))
            ws = data["workspaces"]
            if data.get("version") != 1 or new_key in ws \
                    or ws[old_key]["root"] != old_real:
                return False
        except (OSError, ValueError, KeyError, TypeError):
            return False
        bdir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cat, bdir / cat.name)
        entry = dict(ws[old_key], root=new_real)
        if entry.get("name") == os.path.basename(old_real):
            entry["name"] = os.path.basename(new_real)
        data["workspaces"] = {(new_key if k == old_key else k):
                              (entry if k == old_key else v) for k, v in ws.items()}
        tmp = Path(str(cat) + ".aht-tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                       encoding="utf-8")
        os.replace(tmp, cat)
        return True

    def after_relink(self, uid, old_real, new_real, old_key, new_dir) -> str:
        sessions = self._sessions(new_dir)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        bdir = backups_root() / uid / "rewrites" / f"{self.name}-{stamp}"
        n = 0
        # as the path appears INSIDE a JSON file (backslashes, quotes escaped)
        needle = json.dumps(old_real, ensure_ascii=False)[1:-1]
        for s in sessions:
            st = s / "state.json"
            try:
                if needle not in st.read_text(encoding="utf-8"):
                    continue
                dst = bdir / new_dir.name / s.name / st.name
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(st, dst)               # mandatory pre-rewrite backup
                n += self._repoint_state(st, old_real, new_real)
            except Exception as e:
                error(f"MOVE [{self.name}] cwd not re-pointed in {st}: {e}")
        cataloged = False
        try:
            cataloged = self._recatalog(old_real, new_real, old_key,
                                        new_dir.name, bdir)
        except Exception as e:
            warn(f"MOVE [{self.name}] workspace catalog left as is: {e}")
        self._announce(sessions, new_real)
        return (f"{len(sessions)} session(s), {n} cwd value(s) re-pointed"
                + (", catalog entry renamed" if cataloged else ""))

    def _fresh_id(self, session: Path) -> Path:
        """Give a session (a copy we just made) an id of its own."""
        nid = "session_" + str(_uuid.uuid4())
        st = session / "state.json"
        text = st.read_text(encoding="utf-8")
        text = re.sub(r'("id"\s*:\s*")%s(")' % re.escape(session.name),
                      lambda m: m.group(1) + nid + m.group(2), text, count=1)
        st.write_text(text, encoding="utf-8")
        tgt = session.parent / nid
        os.rename(str(session), str(tgt))
        return tgt

    def _id_taken_elsewhere(self, session: Path) -> bool:
        try:
            return any((b / session.name).is_dir() for b in self.root().iterdir()
                       if b.is_dir() and b != session.parent
                       and not b.name.startswith("."))
        except OSError:
            return False

    def after_copy(self, uid, src_real, new_real, new_dir) -> str:
        """The CLI indexes sessions by id across ALL buckets, so a duplicate
        keeps its content but gets ids of its own — the original stays the
        sole owner of the ids it had."""
        fresh = []
        for s in self._sessions(new_dir):
            try:
                self._repoint_state(s / "state.json", src_real, new_real)
                fresh.append(self._fresh_id(s))
            except Exception as e:
                warn(f"COPY [{self.name}] session {s.name} left as copied: {e}")
        self._announce(fresh, new_real)
        return f"{len(fresh)} session(s) duplicated under fresh ids"

    def after_restore(self, uid, old_real, new_real, new_dir, added) -> str:
        states = [f for f in added
                  if f.name == "state.json" and f.parent.parent == new_dir]
        n, sessions = 0, []
        for st in states:
            s = st.parent
            try:
                if old_real and old_real != new_real:
                    n += self._repoint_state(st, old_real, new_real)
                if self._id_taken_elsewhere(s):     # restored beside a live original
                    s = self._fresh_id(s)
            except Exception as e:
                warn(f"RESTORE [{self.name}] {st}: {e}")
            sessions.append(s)
        self._announce(sessions, new_real)
        return f"{len(sessions)} session(s), {n} cwd value(s) re-pointed"

class FilesBackend(Backend):
    """Sessions in a global store with the project cwd embedded; relink =
    rewrite cwd values (after a mandatory backup copy of the touched files)."""
    kind = "files"
    CWD_KEYS = ("cwd", "workdir", "working_directory", "workspace_path",
                "project_root", "workspace")

    def __init__(self, name, label, confidence, root_default, patterns):
        super().__init__(name, label, confidence, root_default)
        self.patterns = patterns

    def scan(self, real_path: str) -> list:
        """Files that reference real_path as a cwd (cheap substring pre-filter,
        so a big session store is not JSON-parsed wholesale)."""
        if not self.available():
            return []
        needles = {real_path, json.dumps(real_path)[1:-1]}
        hits, seen = [], set()
        for pat in self.patterns:
            for f in self.root().rglob(pat):
                if str(f) in seen or not f.is_file():
                    continue
                seen.add(str(f))
                try:
                    if f.stat().st_size > 50_000_000:
                        continue
                    txt = f.read_text(errors="replace")
                except OSError:
                    continue
                if any(n in txt for n in needles):
                    hits.append(f)
        return hits

    def collect_cwds(self) -> set:
        """Every project cwd this tool's session store records — ONE pass over
        the store (used by adopt, so a project used only with this tool is
        still discovered)."""
        out = set()
        if not self.available():
            return out
        seen = set()
        for pat in self.patterns:
            for f in self.root().rglob(pat):
                if str(f) in seen or not f.is_file():
                    continue
                seen.add(str(f))
                try:
                    if f.stat().st_size > 50_000_000:
                        continue
                    with open(f, "r", errors="replace") as fh:
                        for i, line in enumerate(fh):
                            m = _CWD_RE.search(line)
                            if m:
                                out.add(_unescape_json_str(m.group(1)))
                                break          # the session meta carries the cwd
                            if i > 50:
                                break
                except OSError:
                    continue
        return out

    def _swap(self, obj, old, new):
        changed = 0
        if isinstance(obj, dict):
            for k, v in list(obj.items()):
                if isinstance(v, str) and k in self.CWD_KEYS:
                    if v == old:
                        obj[k] = new
                        changed += 1
                    elif v.startswith(old + os.sep):
                        obj[k] = new + v[len(old):]
                        changed += 1
                else:
                    changed += self._swap(v, old, new)
        elif isinstance(obj, list):
            for v in obj:
                changed += self._swap(v, old, new)
        return changed

    def rewrite_file(self, f: Path, old: str, new: str) -> int:
        """Rewrite cwd-ish values old->new.  Only lines that actually change
        are re-serialised; everything else stays byte-identical."""
        changed = 0
        if f.suffix == ".jsonl":
            out_lines = []
            with open(f, "r", errors="replace") as fh:
                for line in fh:
                    stripped = line.rstrip("\n")
                    try:
                        obj = json.loads(stripped)
                    except Exception:
                        out_lines.append(line)
                        continue
                    n = self._swap(obj, old, new)
                    if n:
                        changed += n
                        out_lines.append(json.dumps(
                            obj, ensure_ascii=False,
                            separators=(",", ":")) + "\n")
                    else:
                        out_lines.append(line)
            if changed:
                tmp = Path(str(f) + ".aht-tmp")
                tmp.write_text("".join(out_lines))
                os.replace(tmp, f)
        else:
            try:
                obj = json.loads(f.read_text(errors="replace"))
            except Exception:
                return 0
            changed = self._swap(obj, old, new)
            if changed:
                tmp = Path(str(f) + ".aht-tmp")
                tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2))
                os.replace(tmp, f)
        return changed

BACKENDS = [
    DirBackend("claude", "Claude Code", "verified",
               lambda: Path.home() / ".claude" / "projects", [_key_claude]),
    DirBackend("gemini", "Gemini CLI", "high",
               lambda: Path.home() / ".gemini" / "tmp", [_key_sha256]),
    DirBackend("cursor", "Cursor Agent CLI", "best-effort",
               lambda: Path.home() / ".cursor" / "chats",
               [_key_md5, _key_sha256]),
    DirBackend("opencode", "OpenCode", "best-effort",
               lambda: _xdg_data() / "opencode" / "project",
               [_key_claude, _key_dash]),
    FilesBackend("codex", "OpenAI Codex CLI", "high",
                 lambda: Path.home() / ".codex" / "sessions", ["*.jsonl"]),
    FilesBackend("copilot", "GitHub Copilot CLI", "best-effort",
                 lambda: Path.home() / ".copilot" / "history-session-state",
                 ["*.json", "*.jsonl"]),
    KimiCodeBackend("kimi-code", "Kimi Code", "verified",
                    lambda: Path(os.environ.get("KIMI_CODE_HOME")
                                 or Path.home() / ".kimi-code") / "sessions",
                    [_key_kimicode], agent="kimi"),
    # the 1.x CLI's layout; the 2.x migration copies it and leaves it behind
    DirBackend("kimi", "Kimi CLI 1.x", "verified",
               lambda: Path.home() / ".kimi" / "sessions", [_key_md5],
               companion_subdir=("user-history", ".jsonl")),
]
BACKEND_NAMES = [b.name for b in BACKENDS]
BY_NAME = {b.name: b for b in BACKENDS}

def enabled_backends() -> list:
    names = cfg_get("backends") or BACKEND_NAMES
    return [b for b in BACKENDS if b.name in names and b.kind != "stub"]

def agents_of(stores: dict) -> list:
    """The agents a project has history with, in stable backend order —
    what the relink prompt shows and what the badges draw."""
    out = []
    for n in BACKEND_NAMES:
        if n in (stores or {}) and BY_NAME[n].agent not in out:
            out.append(BY_NAME[n].agent)
    return out

def claude_backend() -> DirBackend:
    return BY_NAME["claude"]

FILE_STORE_SENTINEL = "@sessions"

def detect_stores(real_path: str, include_files: bool = False) -> dict:
    """{backend_name: store_dirname} for every dir backend with an existing
    store for this path (self-verified by construction).  With include_files,
    metadata-family backends are scanned too (recorded as '@sessions') —
    that scan reads the tool's whole session store, so it is reserved for
    registration-time paths, never for per-directory sweeps."""
    out = {}
    for b in enabled_backends():
        if b.kind == "dir":
            hit = b.find(real_path)
            if hit:
                out[b.name] = hit[1].name
        elif b.kind == "files" and include_files:
            try:
                if b.scan(real_path):
                    out[b.name] = FILE_STORE_SENTINEL
            except Exception:
                pass
    return out

STORES_SCAN_INTERVAL = 600      # s between sweeps of the cwd-keyed session stores

def current_stores(entry: dict, real_path: str, cwds: dict = None) -> dict:
    """What a project's store map should be NOW.  Dir backends are looked up
    live (a few stats); a recorded store that is not under today's key but
    still exists is kept (a conflicted move leaves one like that).  The
    cwd-keyed backends cost a sweep of their whole store, so they are only
    re-evaluated when the caller did that sweep once (`cwds`: name -> set of
    recorded cwds) and otherwise carried over as recorded."""
    cached = (entry or {}).get("stores") or {}
    out = {}
    for b in enabled_backends():
        if b.kind == "dir":
            hit = b.find(real_path)
            rec = cached.get(b.name)
            if hit:
                out[b.name] = hit[1].name
            elif rec and b.available() and (b.root() / rec).is_dir() \
                    and _dir_has_entries(b.root() / rec):
                out[b.name] = rec
        elif b.kind == "files":
            if cwds is not None and b.name in cwds:
                pre = real_path + os.sep
                if any(c == real_path or c.startswith(pre) for c in cwds[b.name]):
                    out[b.name] = FILE_STORE_SENTINEL
            elif b.name in cached:
                out[b.name] = cached[b.name]
    return out

def refresh_stores(reg: dict, only_paths=None, include_files: bool = False) -> list:
    """Bring every project's recorded store map up to date (agents get used in
    a folder long after it was registered).  Returns the folders whose AGENT
    list changed — the ones whose badge is now wrong.  Caller holds the lock
    and saves the registry when the result (or reg['_dirty']) says so."""
    cwds = None
    if include_files:
        cwds = {b.name: b.collect_cwds() for b in enabled_backends()
                if b.kind == "files" and b.available()}
    want = {os.path.realpath(p) for p in only_paths} if only_paths else None
    rebadge = []
    for entry in reg.get("projects", {}).values():
        real = os.path.realpath(entry.get("real_path") or "")
        if (want is not None and real not in want) or not os.path.isdir(real):
            continue
        old = entry.get("stores") or {}
        new = current_stores(entry, real, cwds)
        if new != old:
            entry["stores"] = new
            reg["_dirty"] = True
            if agents_of(new) != agents_of(old):
                rebadge.append(real)
                log(f"STORES {real}: {agents_of(old) or 'none'} -> "
                    f"{agents_of(new) or 'none'}")
    return rebadge

# --------------------------------------------------------------------------- #
# Platform seams: dialogs / notifications  (macOS + Linux here; Windows layer
# patches these over — see windows/src/winlayer.py)
# --------------------------------------------------------------------------- #

def _ask_macos(message, buttons, default, title, timeout):
    btns = "{" + ", ".join(_as_literal(b) for b in buttons) + "}"
    script = ("display dialog %s with title %s buttons %s default button %s with icon note"
              % (_as_literal(message), _as_literal(title), btns, _as_literal(default)))
    try:
        out = subprocess.run(["osascript", "-e", script],
                             capture_output=True, text=True, timeout=timeout)
    except Exception:
        return None
    if out.returncode != 0:
        return None
    for tok in out.stdout.strip().split(","):
        tok = tok.strip()
        if tok.startswith("button returned:"):
            return tok.split(":", 1)[1]
    return None

def _have(cmd: str) -> bool:
    return shutil.which(cmd) is not None

def _linux_has_display() -> bool:
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))

LATER_LABEL = "Later"

def _ask_linux(message, buttons, default, title, timeout):
    if not _linux_has_display():
        return None
    no, yes = buttons[0], buttons[-1]
    try:
        if _have("zenity"):
            r = subprocess.run(
                ["zenity", "--question", "--title", title, "--text", message,
                 "--ok-label", yes, "--cancel-label", LATER_LABEL,
                 "--extra-button", no, "--no-markup", "--width", "460"],
                capture_output=True, text=True, timeout=timeout)
            if r.returncode == 0:
                return yes
            return no if r.stdout.strip() == no else None
        if _have("kdialog"):
            r = subprocess.run(
                ["kdialog", "--title", title, "--yes-label", yes,
                 "--no-label", no, "--cancel-label", LATER_LABEL,
                 "--warningyesnocancel", message],
                capture_output=True, text=True, timeout=timeout)
            if r.returncode == 0:
                return yes
            if r.returncode == 1:
                return no
            return None
        if _have("yad"):
            r = subprocess.run(
                ["yad", "--question", "--title", title, "--text", message,
                 "--button", f"{yes}:0", "--button", f"{no}:2",
                 "--button", f"{LATER_LABEL}:1"],
                capture_output=True, text=True, timeout=timeout)
            if r.returncode == 0:
                return yes
            if r.returncode == 2:
                return no
            return None
    except Exception:
        return None
    return None

def _ask_terminal(message, buttons, default, title):
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return None
    opts = "/".join(b + ("*" if b == default else "") for b in buttons + [LATER_LABEL])
    try:
        print(f"\n{title}\n{message}\n[{opts}]  (* = default, Enter to accept, "
              f"{LATER_LABEL} = decide next time)")
        ans = input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if not ans:
        return default
    for b in buttons:
        if b.lower().startswith(ans.lower()):
            return b
    return None

def gui_dialogs_available() -> bool:
    if IS_MAC:
        return _have("osascript")
    if IS_LINUX:
        return _linux_has_display() and any(_have(c) for c in ("zenity", "kdialog", "yad"))
    return False

def ask_dialog(message: str, buttons: list, default: str,
               title: str = "Agent Project History") -> str | None:
    forced = os.environ.get("AHT_ASSUME")
    if forced:
        return forced if forced in buttons else None
    timeout = _dialog_timeout()
    if gui_dialogs_available():
        if IS_MAC:
            return _ask_macos(message, buttons, default, title, timeout)
        return _ask_linux(message, buttons, default, title, timeout)
    return _ask_terminal(message, buttons, default, title)

def _app_binary():
    """The aht app's own executable: a notice it posts is aht's, so a click
    on it opens aht (one posted through AppleScript opens Script Editor)."""
    for d in ("/Applications", str(Path.home() / "Applications")):
        exe = Path(d) / "aht.app" / "Contents" / "MacOS" / "aht-tray"
        if exe.is_file():
            return exe
    return None

def notify_user(title: str, message: str, info: dict = None) -> None:
    try:
        if os.environ.get("AHT_NO_NOTIFY") or not cfg_get("notifications", True):
            return
        if IS_MAC and app_running():            # the app shows it, and handles a click
            q = aht_home() / "run" / "app-notices.jsonl"
            with open(q, "a") as fh:
                fh.write(json.dumps({"title": title, "message": message, "info": info or {},
                                     "at": time.time()}) + "\n")
            return
        exe = _app_binary() if IS_MAC else None
        if exe:
            r = subprocess.run([str(exe), "--notify", title, message, json.dumps(info or {})],
                               capture_output=True, timeout=15, cwd="/")
            if r.returncode == 0:
                return
        if IS_MAC and _have("osascript"):
            subprocess.run(["osascript", "-e",
                            "display notification %s with title %s"
                            % (_as_literal(message), _as_literal(title))],
                           capture_output=True, timeout=15)
        elif IS_LINUX and _have("notify-send") and _linux_has_display():
            subprocess.run(["notify-send", "-a", "aht", title, message],
                           capture_output=True, timeout=15)
    except Exception:
        pass

class Lock:
    def __init__(self, timeout=None):
        self.fh = None
        self.timeout = timeout
    def __enter__(self):
        aht_home().mkdir(parents=True, exist_ok=True)
        self.fh = open(lock_path(), "w")
        if self.timeout is None:
            fcntl.flock(self.fh, fcntl.LOCK_EX)
        else:
            end = time.time() + self.timeout
            while True:
                try:
                    fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.time() >= end:
                        self.fh.close(); self.fh = None
                        raise TimeoutError("could not acquire lock")
                    time.sleep(0.1)
        return self
    def __exit__(self, *a):
        if self.fh:
            try:
                fcntl.flock(self.fh, fcntl.LOCK_UN)
                self.fh.close()
            except Exception:
                pass

# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #

def load_registry() -> dict:
    p = registry_path()
    if not p.exists():
        return {"version": 2, "projects": {}, "declined_moves": {}}
    try:
        with open(p) as fh:
            data = json.load(fh)
        data.setdefault("version", 2)
        data.setdefault("projects", {})
        data.setdefault("declined_moves", {})
        return data
    except Exception as e:
        warn(f"registry load failed ({e}); starting fresh but keeping old file")
        return {"version": 2, "projects": {}, "declined_moves": {}}

def save_registry(reg: dict) -> None:
    p = registry_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        try:
            shutil.copy2(p, p.with_suffix(".json.bak"))
        except Exception:
            pass
    reg.pop("_dirty", None)
    tmp = p.with_suffix(".json.tmp")
    with open(tmp, "w") as fh:
        json.dump(reg, fh, indent=2, sort_keys=True)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, p)

REGISTRY_KEEP = ("mirror", "away", "handing", "returned", "extras")   # handover's records

def _register(reg: dict, uid: str, real_path: str, stores=None) -> None:
    prev = reg["projects"].get(uid) or {}
    (reg.get("forgotten") or {}).pop(uid, None)     # taken on again
    reg["projects"][uid] = {
        "real_path": real_path,
        "stores": stores if stores is not None
        else detect_stores(real_path, include_files=True),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    reg["projects"][uid].update({k: prev[k] for k in REGISTRY_KEEP if k in prev})

# claude-store helpers (used by the trays and orphan logic; the
# "history dirs" concept is the claude backend's store root)
def _iter_history_dirs():
    pdir = claude_backend().root()
    if not pdir.is_dir():
        return
    for d in sorted(pdir.iterdir()):
        if d.is_dir() and not d.name.startswith(STAGING_PREFIX):
            yield d

def _fold_name(n: str) -> str:
    """A file name as the file system compares it (a Mac and Windows ignore case)."""
    return n.casefold() if CASE_BLIND else n

def registered_history_dirs(reg: dict) -> set:
    return {(e.get("stores") or {}).get("claude")
            for e in reg["projects"].values()
            if (e.get("stores") or {}).get("claude")}

def orphan_history_dirs(reg: dict) -> list:
    """Claude stores no tracked folder owns.  The home folder's own store is
    not one: the hook never tracks the home folder, it is no project.  Names
    compare as the file system compares them: where case does not matter, a
    store recorded as ...-code-App is the folder ...-code-app on disk."""
    skip = {_fold_name(n) for n in registered_history_dirs(reg)}
    skip.add(_fold_name(_key_claude(os.path.realpath(str(Path.home())))))
    return [d for d in _iter_history_dirs() if _fold_name(d.name) not in skip]

# --------------------------------------------------------------------------- #
# Markers
# --------------------------------------------------------------------------- #

def read_marker(folder: str) -> str | None:
    for rel in (MARKER_REL, LEGACY_MARKER_REL):
        mp = Path(folder) / rel
        try:
            if mp.is_file():
                val = mp.read_text().strip()
                if val:
                    return val
        except Exception:
            pass
    return None

def write_marker(folder: str, uid: str) -> None:
    d = Path(folder) / ".aht"
    d.mkdir(parents=True, exist_ok=True)
    (d / ".project-id").write_text(uid + "\n")

# --------------------------------------------------------------------------- #
# Transcript introspection (claude backend: authoritative real paths)
# --------------------------------------------------------------------------- #

_CWD_RE = re.compile(r'"cwd"\s*:\s*"((?:[^"\\]|\\.)*)"')

def _unescape_json_str(s: str) -> str:
    try:
        return json.loads('"' + s + '"')
    except Exception:
        return s

def transcript_cwd(history_dir: Path) -> str | None:
    try:
        jsonls = sorted(history_dir.glob("*.jsonl"))
    except Exception:
        return None
    for f in jsonls:
        try:
            with open(f, "r", errors="replace") as fh:
                for _ in range(50):
                    line = fh.readline()
                    if not line:
                        break
                    m = _CWD_RE.search(line)
                    if m:
                        return _unescape_json_str(m.group(1))
        except Exception:
            continue
    return None

_SEG = r"(?:\\\\|/)"

def transcript_file_refs(history_dir, base: str, limit: int = 40) -> set:
    refs: set = set()
    if not base:
        return refs
    base = str(base).rstrip("/\\")
    variants = {base.replace("\\", "\\\\"), base.replace("\\", "/")}
    pat = re.compile("(?:" + "|".join(re.escape(v) for v in variants) + ")"
                     + _SEG + r'((?:[^\s"\\/]|' + _SEG + r"){1,200})")
    try:
        jsonls = sorted(Path(history_dir).glob("*.jsonl"))
    except Exception:
        return refs
    read_bytes = 0
    for f in jsonls:
        try:
            with open(f, "r", errors="replace") as fh:
                for line in fh:
                    read_bytes += len(line)
                    for m in pat.finditer(line):
                        rel = m.group(1).split('"')[0]
                        rel = rel.replace("\\\\", "/").strip("/")
                        if rel and ".." not in rel:
                            refs.add(rel)
                            if len(refs) >= limit:
                                return refs
                    if read_bytes > 5_000_000:
                        return refs
        except Exception:
            continue
    return refs

# --------------------------------------------------------------------------- #
# Filesystem scanning
# --------------------------------------------------------------------------- #

def find_markers(roots: list) -> tuple:
    path_to_uuid: dict = {}
    uuid_to_paths: dict = {}
    pruned = prune_dirs()
    for root in roots:
        # as spelled on disk: a Mac keeps the case a path is given in, and
        # ~/code/app found under a root typed ~/code is no move of ~/Code/app
        root = _disk_case(os.path.realpath(root))
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, _files in os.walk(root):
            uid = None
            for rel in (MARKER_REL, LEGACY_MARKER_REL):
                mp = os.path.join(dirpath, rel)
                if os.path.isfile(mp):
                    try:
                        uid = Path(mp).read_text().strip() or None
                    except Exception:
                        uid = None
                    if uid:
                        break
            if uid:
                rp = os.path.realpath(dirpath)
                if rp not in path_to_uuid:      # under two roots, one folder still
                    uuid_to_paths.setdefault(uid, []).append(rp)
                path_to_uuid[rp] = uid
            dirnames[:] = [d for d in dirnames
                           if not d.startswith(".") and d not in pruned]
    return path_to_uuid, uuid_to_paths

def list_real_dirs(roots: list, max_depth: int = None) -> list:
    if max_depth is None:
        max_depth = int(cfg_get("scan_max_depth", 7))
    out = []
    pruned = prune_dirs()
    for root in roots:
        root = _disk_case(os.path.realpath(root))
        if not os.path.isdir(root):
            continue
        base_depth = os.path.normpath(root).rstrip(os.sep).count(os.sep)
        for dirpath, dirnames, _files in os.walk(root):
            out.append(os.path.realpath(dirpath))
            depth = os.path.normpath(dirpath).rstrip(os.sep).count(os.sep) - base_depth
            if depth >= max_depth:
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames
                           if not d.startswith(".") and d not in pruned]
    return out

# --------------------------------------------------------------------------- #
# Icon badges  (agent sparkle + git "+")
# --------------------------------------------------------------------------- #

def is_git(path) -> bool:
    return (Path(path) / ".git").exists()

def _entry_for_path(path: str) -> dict:
    rp = os.path.realpath(path)
    projects = load_registry().get("projects", {})
    mine = projects.get(read_marker(rp) or "")      # the folder's own entry first
    if mine is not None and os.path.realpath(mine["real_path"]) == rp:
        return mine
    for e in projects.values():
        if os.path.realpath(e["real_path"]) == rp:
            return e
    return {}

def _stores_for_path(path: str) -> dict:
    return _entry_for_path(path).get("stores") or {}

def desired_marks(path, tethered) -> list:
    """Marks a folder should carry.  `tethered` is False/True (True = look the
    per-backend stores up in the registry) or the stores dict itself.

    Agent marks are PER BACKEND — 'agent:claude', 'agent:codex', … in stable
    BACKENDS order — so the renderers can show one symbol, 2–3 smaller ones
    side by side, or a count disc for 4+.  The git '+' is independent."""
    marks = []
    if is_git(path) and cfg_get("icons_git", True):
        marks.append("git")
    if tethered and cfg_get("icons_agent", True):
        entry = _entry_for_path(path)
        stores = tethered if isinstance(tethered, dict) else entry.get("stores") or {}
        agents = agents_of(stores)
        if entry.get("away"):
            marks.append("agent:away")    # the live copy is on another machine
        elif agents:
            marks += ["agent:" + n for n in agents]
        else:
            marks.append("agent:aht")     # tethered, no history yet: neutral mark
    return marks

# ---- shared badge art: one colored disc per agent, count disc for 4+ ------ #
# The same spec drives all three renderers (macOS Swift, Windows winbadge,
# Linux generated emblems): white-ringed disc in the agent's color with a
# white inner glyph.  Disc color is the primary differentiator at tray sizes.

AGENT_BADGES = {
    "claude":   ((217, 119, 87),  "asterisk"),
    "gemini":   ((66, 133, 244),  "diamond"),
    "cursor":   ((26, 26, 26),    "triangle"),
    "opencode": ((249, 115, 22),  "square"),
    "codex":    ((16, 163, 127),  "ring"),
    "copilot":  ((110, 64, 201),  "bar"),
    "kimi":     ((124, 58, 237),  "crescent"),
    # tethered, but no agent has history here yet — deliberately unlike any
    # agent's mark, so a missing agent can never pass for a present one
    "aht":      ((124, 132, 142), "infinity"),
    # handed over: the work goes on elsewhere — shown INSTEAD of the agents
    "away":     ((37, 99, 235),   "arrow"),
}
COUNT_BADGE_RGB = (51, 58, 66)
# the git "+" on Linux, where a file manager shows emblems beside the folder,
# not drawn into it: the agents' disc turned round (white, its ring and "+"
# in the ink of the Mac and Windows "+"), so it passes for no agent
GIT_BADGE = ((255, 255, 255), "plus", (28, 26, 25))

_DIGITS = {
    "0": ("111", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"),
    "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"),
    "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"),
    "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"),
    "9": ("111", "101", "111", "001", "111"),
}

def _c01(v):
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)

def badge_disc_rgba(d: int, agent_or_count) -> bytearray:
    """d×d straight-alpha RGBA: a white-ringed disc for one agent (name), a
    slate count disc with the number drawn in (int, for 4+ agents), or the
    git "+" ("git", dark on white)."""
    ink = (255, 255, 255)           # the ring and the glyph
    if isinstance(agent_or_count, int):
        rgb, glyph = COUNT_BADGE_RGB, str(min(agent_or_count, 9))
    elif agent_or_count == "git":
        rgb, glyph, ink = GIT_BADGE
    else:
        rgb, glyph = AGENT_BADGES.get(str(agent_or_count), AGENT_BADGES["aht"])
    buf = bytearray(d * d * 4)
    c = (d - 1) / 2.0
    r_out = d * 0.5 - 0.5           # white halo edge
    r_in = d * 0.42                 # colored disc
    import math
    loop = _infinity_cov(d, 0.27, 0.06) if glyph == "infinity" else None
    for y in range(d):
        for x in range(d):
            dx, dy = x - c, y - c
            dist = (dx * dx + dy * dy) ** 0.5
            a = _c01(r_out - dist + 0.5)
            if a <= 0.0:
                continue
            if dist > r_in:
                col = ink                      # halo ring
            else:
                col = rgb
                g = 0.0
                if glyph == "asterisk":
                    for deg in (0.0, 60.0, 120.0):
                        rad = math.radians(deg)
                        perp = abs(dx * math.sin(rad) - dy * math.cos(rad))
                        along = abs(dx * math.cos(rad) + dy * math.sin(rad))
                        if along <= d * 0.30:
                            g = max(g, _c01(d * 0.065 - perp + 0.5))
                elif glyph == "ring":
                    g = _c01(d * 0.06 - abs(dist - d * 0.21) + 0.5)
                elif glyph == "diamond":
                    g = _c01(d * 0.26 - (abs(dx) + abs(dy)) + 0.5)
                elif glyph == "square":
                    g = _c01(d * 0.19 - max(abs(dx), abs(dy)) + 0.5)
                elif glyph == "plus":                   # arms whole pixels wide
                    arm, half = d * 0.25, d / 12.0
                    g = max(_c01(min(half - abs(dy), arm - abs(dx)) + 0.5),
                            _c01(min(half - abs(dx), arm - abs(dy)) + 0.5))
                elif glyph == "bar":
                    if abs(dx) <= d * 0.22:
                        g = _c01(d * 0.075 - abs(dy) + 0.5)
                elif glyph == "triangle":
                    ty = dy + d * 0.05
                    if -d * 0.26 <= ty <= d * 0.20:
                        half = (ty + d * 0.26) * 0.62
                        g = _c01((half - abs(dx)) * 0.9 + 0.5)
                elif glyph == "crescent":
                    d2 = ((dx - d * 0.10) ** 2 + (dy + d * 0.08) ** 2) ** 0.5
                    g = _c01(d * 0.24 - dist + 0.5) * _c01(d2 - d * 0.20 + 0.5)
                elif glyph == "arrow":                  # points right: gone out
                    if -d * 0.26 <= dx <= d * 0.04:     # shaft
                        g = _c01(d * 0.065 - abs(dy) + 0.5)
                    if d * 0.02 <= dx <= d * 0.28:      # head
                        g = max(g, _c01((d * 0.28 - dx) * 0.85 - abs(dy) + 0.5))
                elif loop is not None:
                    g = loop[y * d + x]
                elif glyph in _DIGITS:
                    rows = _DIGITS[glyph]
                    cell = d * 0.115
                    gx = int((dx + 1.5 * cell) // cell)
                    gy = int((dy + 2.5 * cell) // cell)
                    if 0 <= gy < 5 and 0 <= gx < 3 and rows[gy][gx] == "1":
                        g = 1.0
                if g > 0.0:
                    col = (int(col[0] + (ink[0] - col[0]) * g),
                           int(col[1] + (ink[1] - col[1]) * g),
                           int(col[2] + (ink[2] - col[2]) * g))
            i = (y * d + x) * 4
            buf[i], buf[i + 1], buf[i + 2] = col
            buf[i + 3] = int(a * 255)
    return buf

def _png_bytes(d: int, rgba) -> bytes:
    import struct
    import zlib
    raw = b"".join(b"\x00" + bytes(rgba[y * d * 4:(y + 1) * d * 4])
                   for y in range(d))
    def chunk(t, data):
        return (struct.pack(">I", len(data)) + t + data
                + struct.pack(">I", zlib.crc32(t + data)))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", d, d, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))

def infinity_rgba(d: int, rgb=(255, 255, 255), bg=None, span: float = 0.46,
                  thickness: float = 0.07) -> bytearray:
    """d×d straight-alpha RGBA of the aht mark: an infinity loop (a tether
    with no loose end) stroked in `rgb` — on a transparent ground for the
    tray icons, or on a filled disc of color `bg` for the app icons.  One
    renderer for the Windows/Linux trays and the release artwork, so every
    platform draws the same shape (the macOS menu bar uses the matching SF
    Symbol)."""
    cov = _infinity_cov(d, span, thickness)
    c = (d - 1) / 2.0
    buf = bytearray(d * d * 4)
    r_bg = d * 0.47
    for y in range(d):
        dy = y - c
        for x in range(d):
            j = y * d + x
            g = cov[j]
            ab = _c01(r_bg - ((x - c) ** 2 + dy * dy) ** 0.5 + 0.5) if bg else 0.0
            alpha = g + ab * (1.0 - g)
            if alpha <= 0.0:
                continue
            if ab > 0.0 and g < 1.0:                      # stroke over the disc
                col = tuple(int((rgb[i] * g + bg[i] * ab * (1.0 - g)) / alpha)
                            for i in range(3))
            else:
                col = rgb
            i4 = j * 4
            buf[i4], buf[i4 + 1], buf[i4 + 2] = col
            buf[i4 + 3] = int(alpha * 255 + 0.5)
    return buf

def _infinity_cov(d: int, span: float, thickness: float) -> list:
    """Per-pixel coverage (0..1) of an infinity loop centred in a d×d tile."""
    import math
    c = (d - 1) / 2.0
    a = d * span                     # lemniscate half-span
    w = max(0.9, d * thickness)      # stroke half-width
    ro, ri = w + 0.5, w - 0.5        # soft edge: solid inside ri, nothing past ro
    cov = [0.0] * (d * d)
    n = max(96, int(d * 6))          # curve samples, ~0.35 px apart
    for i in range(n):
        t = 2.0 * math.pi * i / n
        s, co = math.sin(t), math.cos(t)
        k = 1.0 + s * s
        px, py = c + a * co / k, c + a * s * co / k      # lemniscate of Bernoulli
        for y in range(max(0, int(py - ro)), min(d - 1, int(py + ro) + 1) + 1):
            dy = y - py
            oo = ro * ro - dy * dy
            if oo <= 0.0:
                continue
            row = y * d
            hx = oo ** 0.5
            xa = max(0, int(math.ceil(px - hx)))
            xb = min(d - 1, int(math.floor(px + hx)))
            ii = ri * ri - dy * dy
            if ii > 0.0:
                hi = ii ** 0.5
                xi0 = max(xa, int(math.ceil(px - hi)))
                xi1 = min(xb, int(math.floor(px + hi)))
            else:
                xi0, xi1 = xb + 1, xb
            if xi1 >= xi0:                                # solid core of the stroke
                cov[row + xi0:row + xi1 + 1] = [1.0] * (xi1 - xi0 + 1)
            for x in list(range(xa, xi0)) + list(range(xi1 + 1, xb + 1)):
                v = ro - ((x - px) ** 2 + dy * dy) ** 0.5
                if v > cov[row + x]:
                    cov[row + x] = 1.0 if v > 1.0 else v
    return cov

APP_ICON_RGB = (51, 58, 66)          # slate disc behind the white loop

def app_icon_png(d: int) -> bytes:
    """The release/app icon at d×d as PNG bytes."""
    return _png_bytes(d, infinity_rgba(d, (255, 255, 255), bg=APP_ICON_RGB,
                                       span=0.34, thickness=0.058))

EMBLEM_VERSION = 4

def _ensure_linux_emblems() -> bool:
    """Generate the per-agent, count and git "+" emblems into the user icon
    theme once.
    Best-effort: file managers that honour hicolor user emblems pick them up
    (a cache refresh / re-login may be needed the first time)."""
    base = _xdg_data() / "icons" / "hicolor"
    stamp = base / f".aht-emblems-v{EMBLEM_VERSION}"
    if stamp.exists():
        return True
    try:
        for sz in (24, 48):
            d = base / f"{sz}x{sz}" / "emblems"
            d.mkdir(parents=True, exist_ok=True)
            for name in AGENT_BADGES:
                (d / f"aht-agent-{name}.png").write_bytes(
                    _png_bytes(sz, badge_disc_rgba(sz, name)))
            for n in range(4, 10):
                (d / f"aht-agents-{n}.png").write_bytes(
                    _png_bytes(sz, badge_disc_rgba(sz, n)))
            (d / "aht-git.png").write_bytes(_png_bytes(sz, badge_disc_rgba(sz, "git")))
        stamp.write_text("ok\n")
        if _have("gtk-update-icon-cache"):
            subprocess.run(["gtk-update-icon-cache", "-f", "-t", str(base)],
                           capture_output=True, timeout=30)
        return True
    except Exception as e:
        warn(f"emblem generation failed: {e}")
        return False

def _badge_tool():
    return next((c for c in (Path(__file__).with_name("badge_icon"),
                             aht_home() / "tools/agent-history-tether/badge_icon")
                 if c.exists()), None)

_BADGE_TOOL_WARNED = False

def _badge_macos(path, marks) -> None:
    global _BADGE_TOOL_WARNED
    b = _badge_tool()
    if b is None:
        if not _BADGE_TOOL_WARNED:
            _BADGE_TOOL_WARNED = True
            warn("badge tool missing; folder badges are not applied — "
                 "run:  aht install")
        return
    cmd = [str(b), "set", str(path)] + list(marks) if marks \
        else [str(b), "clear", str(path)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        rc, err = r.returncode, (r.stderr or "").strip()
    except OSError as e:                # macOS refused to run it (Gatekeeper)
        rc, err = -1, str(e)
    if rc != 0 and not _BADGE_TOOL_WARNED:
        _BADGE_TOOL_WARNED = True       # once per run, not once per folder
        warn(f"badge tool failed (exit {rc}) on {path}: {err[:160]} — "
             f"if macOS blocked it, run:  aht install")

def _badge_linux(path, marks) -> None:
    method = cfg_get("linux_emblem_method", "auto")
    if method == "none":
        return
    agents = [m.split(":", 1)[1] for m in marks if m.startswith("agent:")]
    use_gio = method in ("auto", "gio", "both") and _have("gio")
    use_kde = method in ("kde", "both") or (
        method == "auto" and not use_gio and
        "kde" in (os.environ.get("XDG_CURRENT_DESKTOP", "") or "").lower())
    if use_gio:
        embs = []
        if agents:
            # an explicitly configured emblem overrides the generated set
            if "linux_agent_emblem" in load_config():
                embs.append(str(cfg_get("linux_agent_emblem")))
            elif _ensure_linux_emblems():
                if len(agents) <= 3:
                    embs += [f"aht-agent-{n}" for n in agents]
                else:
                    embs.append(f"aht-agents-{min(len(agents), 9)}")
            else:
                embs.append(str(cfg_get("linux_agent_emblem")))
        # aht's own "+", or the emblem the config names; none rather than
        # one that means something else, should aht's not be there
        if "git" in marks and ("linux_git_emblem" in load_config()
                               or _ensure_linux_emblems()):
            embs.append(str(cfg_get("linux_git_emblem")))
        if embs:
            subprocess.run(["gio", "set", "-t", "stringv", str(path),
                            "metadata::emblems"] + embs, capture_output=True, timeout=15)
        else:
            subprocess.run(["gio", "set", "-t", "unset", str(path),
                            "metadata::emblems"], capture_output=True, timeout=15)
    if use_kde:
        # KDE's .directory supports a single icon only — count can't be shown
        dotdir = Path(path) / ".directory"
        icon = "folder-favorites" if agents else None
        try:
            if icon:
                dotdir.write_text(f"[Desktop Entry]\nIcon={icon}\n")
            elif dotdir.is_file() and "Icon=folder-favorites" in dotdir.read_text():
                dotdir.unlink()
        except Exception:
            pass

def apply_badge(path, marks) -> None:
    if os.environ.get("AHT_NO_ICONS") or not cfg_get("icons_enabled", True):
        return
    try:
        if IS_MAC:
            _badge_macos(path, marks)
        elif IS_LINUX:
            _badge_linux(path, marks)
    except Exception as e:
        warn(f"badge failed for {path}: {e}")

def find_git_repos(roots: list) -> set:
    found = set()
    pruned = prune_dirs()
    for root in roots:
        root = _disk_case(os.path.realpath(root))
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, _files in os.walk(root):
            if os.path.exists(os.path.join(dirpath, ".git")):
                found.add(os.path.realpath(dirpath))
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames
                           if not d.startswith(".") and d not in pruned]
    return found

def tethered_paths(reg: dict) -> set:
    return {os.path.realpath(e["real_path"]) for e in reg["projects"].values()
            if os.path.isdir(e["real_path"])}

# --------------------------------------------------------------------------- #
# History auto-backup  (per-project snapshots across every backend)
# --------------------------------------------------------------------------- #

def backups_root() -> Path:
    d = cfg_get("backup_dir")
    return Path(_expand(str(d))) if d else aht_home() / "backups"

def _backup_stamp_file() -> Path:
    return backups_root() / ".last-run"

def backup_due() -> bool:
    try:
        age = time.time() - _backup_stamp_file().stat().st_mtime
    except OSError:
        return True
    try:
        hours = float(cfg_get("backup_interval_hours", 24.0))
    except Exception:
        hours = 24.0
    return age >= hours * 3600

def _touch_backup_stamp() -> None:
    try:
        backups_root().mkdir(parents=True, exist_ok=True)
        _backup_stamp_file().write_text(time.strftime("%Y-%m-%dT%H:%M:%S") + "\n")
    except OSError:
        pass

def _project_sources(entry: dict) -> list:
    """[(abs_file, arcname)] across every enabled backend, arc =
    '<backend>/<relative path>' so one zip snapshots the whole project."""
    out = []
    real = entry.get("real_path") or ""
    for b in enabled_backends():
        if b.kind == "dir":
            d = None
            rec = (entry.get("stores") or {}).get(b.name)
            if rec and (b.root() / rec).is_dir():
                d = b.root() / rec
            else:
                hit = b.find(real)
                if hit:
                    d = hit[1]
            if d is not None:
                for f in d.rglob("*"):
                    if f.is_file():
                        out.append((f, f"{b.name}/{f.relative_to(d)}"))
                for tag, comp in b.companions(d.name, real):
                    if comp.is_file():
                        out.append((comp, f"{b.name}/__aht_companion__{tag}"))
        elif b.kind == "files":
            for f in b.scan(real):
                out.append((f, f"{b.name}/{f.relative_to(b.root())}"))
    return out

def _sources_sig(sources: list) -> str:
    n, size, newest = 0, 0, 0
    for f, _arc in sources:
        try:
            st = f.stat()
        except OSError:
            continue
        n += 1
        size += st.st_size
        newest = max(newest, int(st.st_mtime))
    return f"{n}:{size}:{newest}"

def _snapshots(uid: str) -> list:
    d = backups_root() / uid
    out = []
    if not d.is_dir():
        return out
    for z in sorted(d.glob("*.zip")):
        meta = {"uuid": uid, "stamp": z.stem, "zip": str(z)}
        try:
            meta["zip_bytes"] = z.stat().st_size
        except OSError:
            meta["zip_bytes"] = 0
        try:
            meta.update(json.loads(z.with_suffix(".meta.json").read_text()))
        except Exception:
            pass
        out.append(meta)
    return out

def _prune_snapshots(uid: str) -> int:
    try:
        keep = max(1, int(cfg_get("backup_keep", 10)))
    except Exception:
        keep = 10
    snaps = _snapshots(uid)
    drop = snaps[:-keep] if len(snaps) > keep else []
    for m in drop:
        for p in (Path(m["zip"]), Path(m["zip"]).with_suffix(".meta.json")):
            try:
                p.unlink()
            except OSError:
                pass
    if drop:
        log(f"BACKUP pruned {len(drop)} old snapshot(s) for {uid}")
    return len(drop)

def _snapshot_project(uid: str, entry: dict) -> dict:
    import zipfile
    res = {"uuid": uid, "real_path": entry.get("real_path")}
    sources = _project_sources(entry)
    if not sources:
        res["status"] = "no-history"
        return res
    sig = _sources_sig(sources)
    snaps = _snapshots(uid)
    if snaps and snaps[-1].get("sig") == sig:
        res.update(status="unchanged", stamp=snaps[-1]["stamp"])
        return res
    d = backups_root() / uid
    d.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    z = d / f"{stamp}.zip"
    n = 2
    while z.exists():
        z = d / f"{stamp}-{n}.zip"
        n += 1
    tmp = Path(str(z) + ".tmp")
    total = 0
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        for f, arc in sources:
            try:
                zf.write(f, arc)
                total += f.stat().st_size
            except OSError:
                continue
    os.replace(tmp, z)
    refs = []
    chit = claude_backend().find(entry.get("real_path") or "")
    if chit:
        refs = sorted(transcript_file_refs(chit[1],
                                           entry.get("real_path") or "", limit=25))
    meta = {"uuid": uid, "stamp": z.stem,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "real_path": entry.get("real_path"),
            "stores": entry.get("stores") or {},
            "backends": sorted({a.split("/", 1)[0] for _f, a in sources}),
            "sig": sig, "files": len(sources), "bytes": total,
            "file_refs": refs}
    try:
        z.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2))
    except OSError:
        pass
    _prune_snapshots(uid)
    res.update(status="backed-up", stamp=z.stem, files=len(sources), bytes=total)
    log(f"BACKUP {entry.get('real_path')} -> {uid}/{z.name} "
        f"({len(sources)} file(s), backends {meta['backends']})")
    return res

def backup_pass(only_uid=None) -> list:
    reg = load_registry()
    results = []
    for uid, entry in sorted(reg.get("projects", {}).items()):
        if only_uid and uid != only_uid:
            continue
        try:
            results.append(_snapshot_project(uid, entry))
        except Exception as e:
            results.append({"uuid": uid, "status": "failed", "error": str(e)})
            error(f"BACKUP failed for {entry.get('real_path')}: {e}")
    _touch_backup_stamp()
    return results

def maybe_auto_backup() -> None:
    try:
        if os.environ.get("AHT_NO_BACKUP") or not cfg_get("backup_enabled", True):
            return
        if not backup_due():
            return
        done = sum(1 for r in backup_pass() if r["status"] == "backed-up")
        if done:
            log(f"BACKUP auto pass: {done} project(s) snapshotted")
            _spawn_offsite()
    except Exception as e:
        error(f"BACKUP auto pass failed: {e}")

def _spawn_auto_backup() -> None:
    try:
        if os.environ.get("AHT_NO_BACKUP") or not cfg_get("backup_enabled", True) \
                or not backup_due():
            return
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "backup", "--auto"]
        else:
            cmd = [sys.executable or "python3", str(Path(__file__).resolve()),
                   "backup", "--auto"]
        kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
              "stderr": subprocess.DEVNULL, "close_fds": True}
        if os.name == "nt":
            kw["creationflags"] = 0x08000200
        else:
            kw["start_new_session"] = True
        subprocess.Popen(cmd, **kw)
    except Exception:
        pass

def match_snapshots(folder: str, limit: int = 8) -> list:
    folder = os.path.realpath(folder)
    leaf = os.path.basename(folder)
    rows = []
    root = backups_root()
    if not root.is_dir():
        return rows
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        snaps = _snapshots(d.name)
        if not snaps:
            continue
        m = snaps[-1]
        score, reasons = 0.0, []
        orig = m.get("real_path") or ""
        if orig and os.path.basename(orig) == leaf:
            score += 1.0
            reasons.append("leaf-name")
        refs = m.get("file_refs") or []
        if refs:
            present = sum(
                1 for r in refs
                if os.path.exists(os.path.join(
                    folder, *str(r).replace("\\", "/").split("/"))))
            if present:
                score += 2.0 * present / len(refs)
                reasons.append(f"files {present}/{len(refs)}")
        if score > 0:
            rows.append({"uuid": d.name, "stamp": m["stamp"], "orig_path": orig,
                         "score": round(score, 3), "reasons": reasons,
                         "snapshots": len(snaps)})
    rows.sort(key=lambda r: -r["score"])
    return rows[:limit]

def _restore_snapshot(snap: dict, new_real: str) -> dict:
    """Extract a snapshot for a folder at its NEW location.  Dir backends land
    under key(new_real); file backends go back to their original place in the
    global store and then have their cwd rewritten to the new path.  Nothing
    is ever overwritten."""
    import zipfile
    added, skipped, rewrites = 0, 0, 0
    per_backend: dict = {}
    old_real = snap.get("real_path") or ""
    restored_files = []
    added_in_dirs: dict = {}
    with zipfile.ZipFile(snap["zip"]) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            arc = info.filename.replace("\\", "/")
            if "/" not in arc:
                skipped += 1
                continue
            bname, rel = arc.split("/", 1)
            b = BY_NAME.get(bname)
            if b is None or b.kind == "stub":
                skipped += 1
                continue
            if b.kind == "dir":
                if rel.startswith("__aht_companion__"):
                    dest = dict(b.companions(b.keys[0](new_real), new_real)).get(
                        rel[len("__aht_companion__"):])
                    if dest is None:
                        skipped += 1
                        continue
                else:
                    dest = b.root() / b.keys[0](new_real) / rel
            else:
                dest = b.root() / rel
            try:
                dr = (dest.parent).resolve()
            except OSError:
                skipped += 1
                continue
            guard = (b.root().parent if b.kind == "dir"
                     and rel.startswith("__aht_companion__") else b.root())
            if guard.resolve() not in list(dr.parents) + [dr]:
                skipped += 1
                continue
            if dest.exists():
                skipped += 1
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
            added += 1
            per_backend[bname] = per_backend.get(bname, 0) + 1
            if b.kind == "files":
                restored_files.append((b, dest))
            elif not rel.startswith("__aht_companion__"):
                added_in_dirs.setdefault(bname, []).append(dest)
    for bname, files in added_in_dirs.items():
        b = BY_NAME[bname]
        try:
            note = b.after_restore(snap.get("uuid", "unknown"), old_real, new_real,
                                   b.root() / b.keys[0](new_real), files)
            if note:
                log(f"RESTORE [{bname}] {note}")
        except Exception as e:
            warn(f"RESTORE [{bname}] follow-up failed: {e}")
    if old_real and old_real != new_real:
        # re-point cwd in the restored session files AND in any live session
        # files still referencing the snapshot-era path (the live ones are
        # copied into the backup store first, like every metadata rewrite)
        todo = {}
        for b, f in restored_files:
            todo.setdefault(b.name, (b, set()))[1].add(f)
        for b in enabled_backends():
            if b.kind != "files" or not b.available():
                continue
            live = b.scan(old_real)
            if not live:
                continue
            stamp = time.strftime("%Y%m%d-%H%M%S")
            bdir = (backups_root() / snap.get("uuid", "unknown") / "rewrites"
                    / f"{b.name}-restore-{stamp}")
            fresh = {f for _b, f in restored_files if _b.name == b.name}
            for f in live:
                if f in fresh:
                    continue
                try:
                    dst = bdir / f.relative_to(b.root())
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, dst)
                except Exception as e:
                    warn(f"RESTORE pre-rewrite backup failed {f}: {e}")
                    continue
                todo.setdefault(b.name, (b, set()))[1].add(f)
        for b, files in todo.values():
            for f in files:
                try:
                    rewrites += b.rewrite_file(f, old_real, new_real)
                except Exception as e:
                    warn(f"RESTORE rewrite failed {f}: {e}")
    return {"added": added, "existing_kept": skipped,
            "cwd_rewrites": rewrites, "per_backend": per_backend}

def backup_status() -> dict:
    root = backups_root()
    n_proj, n_zip, size = 0, 0, 0
    try:
        if root.is_dir():
            for d in root.iterdir():
                if d.is_dir():
                    zips = list(d.glob("*.zip"))
                    if zips:
                        n_proj += 1
                        n_zip += len(zips)
                        size += sum(z.stat().st_size for z in zips)
    except OSError:
        pass
    try:
        last = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(
            _backup_stamp_file().stat().st_mtime))
    except OSError:
        last = None
    return {"enabled": bool(cfg_get("backup_enabled", True)),
            "interval_hours": cfg_get("backup_interval_hours", 24.0),
            "keep": cfg_get("backup_keep", 10), "dir": str(root),
            "last_run": last, "projects": n_proj, "snapshots": n_zip,
            "bytes": size}

# --------------------------------------------------------------------------- #
# Safe store moves (never overwrite, never delete)
# --------------------------------------------------------------------------- #

def safe_merge(old: Path, new: Path) -> list:
    conflicts = []
    new.mkdir(parents=True, exist_ok=True)
    for item in list(old.iterdir()):
        target = new / item.name
        if not target.exists():
            shutil.move(str(item), str(target))
        elif item.is_dir() and target.is_dir():
            conflicts.extend(safe_merge(item, target))
        else:
            conflicts.append(str(item))
    try:
        if not any(old.iterdir()):
            old.rmdir()
    except Exception:
        pass
    return conflicts

def safe_relink(old_store: Path, new_store: Path) -> str:
    if not old_store.exists():
        return "no-history"
    if old_store.resolve() == new_store.resolve():
        return "same"
    if new_store.exists() and _same_folder(old_store, new_store):
        try:                        # one store, two spellings (a Mac ignores case):
            os.rename(str(old_store), str(new_store))   # take the new one, merge nothing
        except OSError:
            pass
        return "same"
    if not new_store.exists():
        new_store.parent.mkdir(parents=True, exist_ok=True)
        os.rename(str(old_store), str(new_store))
        return "renamed"
    conflicts = safe_merge(old_store, new_store)
    return "merged-with-conflicts" if conflicts else "merged"

def safe_copy_tree(src: Path, dst: Path) -> str:
    if not src.exists():
        return "no-history"
    if dst.exists():
        for item in src.rglob("*"):
            rel = item.relative_to(src)
            target = dst / rel
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            elif not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
        return "copy-merged"
    shutil.copytree(src, dst)
    return "copied"

# --------------------------------------------------------------------------- #
# Reconcile core: pure action computation + collision-safe application
# --------------------------------------------------------------------------- #

def compute_actions(reg: dict, uuid_to_paths: dict,
                    respect_declines: bool = True) -> tuple:
    declined = reg.get("declined_moves", {}) if respect_declines else {}
    # a project the user forgot keeps its marker: the scan leaves it alone
    forgotten = reg.get("forgotten") or {}
    moves, copies, news, missing = [], [], [], []
    for uid, paths in uuid_to_paths.items():
        entry = reg["projects"].get(uid)
        if entry is None:
            if uid not in forgotten:
                news += [{"uuid": uid, "path": p} for p in paths]
            continue
        old_path = entry["real_path"]
        if len(paths) == 1:
            p = paths[0]
            if os.path.realpath(p) != os.path.realpath(old_path):
                d = declined.get(uid)
                if d is not None and os.path.realpath(d) == os.path.realpath(p):
                    continue
                moves.append({"uuid": uid, "from": old_path, "to": p})
        else:
            originals = [p for p in paths
                         if os.path.realpath(p) == os.path.realpath(old_path)] \
                or [p for p in paths if _same_folder(p, old_path)]
            keep = originals[0] if originals else paths[0]
            for p in paths:
                if p == keep:
                    continue
                copies.append({"uuid": uid, "src": old_path, "copy_path": p})
    for uid, entry in reg["projects"].items():
        if uid not in uuid_to_paths:
            missing.append({"uuid": uid, "real_path": entry["real_path"]})
    return moves, copies, news, missing

def _apply_dir_moves(b: DirBackend, reg: dict, moves: list) -> None:
    root = b.root()
    plans = []
    for m in moves:
        entry = reg["projects"].get(m["uuid"]) or {}
        rec = (entry.get("stores") or {}).get(b.name)
        src, idx = None, 0
        if rec and (root / rec).is_dir():
            src = root / rec
            for i, k in enumerate(b.keys):
                if k(os.path.realpath(m["from"])) == rec:
                    idx = i
                    break
        else:
            hit = b.find(os.path.realpath(m["from"]))
            if hit:
                idx, src = hit
        if src is None:
            m["stores"][b.name] = "no-store"
            continue
        tgt = root / b.keys[idx](os.path.realpath(m["to"]))
        if src.name == tgt.name:
            m["stores"][b.name] = "same-name"
            continue
        plans.append((m, src, tgt))

    owner = {}
    for u, e in reg["projects"].items():
        nm = (e.get("stores") or {}).get(b.name)
        if nm:
            owner[nm] = u
    moving = {m["uuid"] for m, _s, _t in plans}
    tcount = {}
    for _m, _s, t in plans:
        tcount[t.name] = tcount.get(t.name, 0) + 1

    safe = []
    for m, src, tgt in plans:
        own = owner.get(tgt.name)
        if (tcount[tgt.name] > 1
                or (own is not None and own != m["uuid"] and own not in moving)
                or (own is None and tgt.exists() and not _same_folder(src, tgt)
                    and not (tgt.is_dir() and not _dir_has_entries(tgt)))):
            m["stores"][b.name] = "conflict-target-occupied"
            error(f"CONFLICT [{b.name}] {m['from']} -> {m['to']}: target "
                f"{tgt.name} occupied; store left intact")
        else:
            safe.append((m, src, tgt))

    staged = []
    for m, src, tgt in safe:
        tmp = root / (STAGING_PREFIX + m["uuid"][:12] + "-" + b.name)
        try:
            os.rename(str(src), str(tmp))
            staged.append((m, tmp, tgt, src))
        except OSError as e:
            m["stores"][b.name] = "stage-failed"
            error(f"MOVE [{b.name}] stage failed {src.name}: {e}")
    for m, tmp, tgt, orig in staged:
        try:
            if tgt.is_dir() and not _dir_has_entries(tgt):
                tgt.rmdir()              # an empty placeholder holds no history
            if tgt.exists():
                os.rename(str(tmp), str(orig))
                m["stores"][b.name] = "conflict-race-restored"
                continue
            os.rename(str(tmp), str(tgt))
            m["stores"][b.name] = "renamed"
            old_real = os.path.realpath(m["from"])
            new_real = os.path.realpath(m["to"])
            new_comps = dict(b.companions(tgt.name, new_real))
            for tag, comp_old in b.companions(orig.name, old_real):
                comp_new = new_comps.get(tag)
                if comp_new is None or not comp_old.is_file():
                    continue
                try:
                    if comp_new.exists():
                        log(f"MOVE [{b.name}] companion {comp_new.name} exists; "
                            f"kept both")
                    else:
                        comp_new.parent.mkdir(parents=True, exist_ok=True)
                        os.rename(str(comp_old), str(comp_new))
                except OSError as e:
                    warn(f"MOVE [{b.name}] companion rename failed: {e}")
            try:
                note = b.after_relink(m["uuid"], old_real, new_real, orig.name, tgt)
                if note:
                    log(f"MOVE [{b.name}] {tgt.name}: {note}")
            except Exception as e:
                error(f"MOVE [{b.name}] follow-up failed for {tgt.name}: {e}")
        except OSError as e:
            error(f"MOVE [{b.name}] place failed -> {tgt.name}: {e}")
            try:
                os.rename(str(tmp), str(orig))
            except OSError as e2:
                error(f"MOVE [{b.name}] restore FAILED: {e2} (kept at {tmp})")
            m["stores"][b.name] = "place-failed"

def _apply_file_moves(b: FilesBackend, reg: dict, moves: list) -> None:
    for m in moves:
        old = os.path.realpath(m["from"])
        new = os.path.realpath(m["to"])
        files = b.scan(old)
        if not files:
            m["stores"][b.name] = "no-sessions"
            continue
        # mandatory pre-rewrite backup of the exact files we are touching
        stamp = time.strftime("%Y%m%d-%H%M%S")
        bdir = backups_root() / m["uuid"] / "rewrites" / f"{b.name}-{stamp}"
        try:
            for f in files:
                dst = bdir / f.relative_to(b.root())
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dst)
        except Exception as e:
            m["stores"][b.name] = "backup-failed-skipped"
            error(f"MOVE [{b.name}] pre-rewrite backup failed ({e}); "
                f"sessions left untouched")
            continue
        n = 0
        for f in files:
            try:
                n += b.rewrite_file(f, old, new)
            except Exception as e:
                error(f"MOVE [{b.name}] rewrite failed {f}: {e}")
        m["stores"][b.name] = f"rewrote-{n}-values-in-{len(files)}-file(s)"
        log(f"MOVE [{b.name}] {old} -> {new}: rewrote {n} cwd value(s) "
            f"in {len(files)} file(s); originals backed up to {bdir}")

def apply_moves(reg: dict, moves: list) -> tuple:
    for m in moves:
        m["stores"] = {}
    for b in enabled_backends():
        try:
            if b.kind == "dir" and b.available():
                _apply_dir_moves(b, reg, moves)
            elif b.kind == "files" and b.available():
                _apply_file_moves(b, reg, moves)
        except Exception as e:
            error(f"MOVE backend {b.name} failed wholesale: {e}")
    applied, conflicts = [], []
    for m in moves:
        vals = list(m["stores"].values())
        acted = any(v == "renamed" or v == "same-name" or v.startswith("rewrote")
                    for v in vals)
        conflict = any(v.startswith("conflict") for v in vals)
        # store map for the registry: freshly detected for relinked backends,
        # but a CONFLICTED backend keeps its old (still valid, mis-keyed)
        # store — never claim the occupying stranger's dir as ours.
        entry_old = reg["projects"].get(m["uuid"]) or {}
        stores = detect_stores(os.path.realpath(m["to"]))
        for bname, stv in m["stores"].items():
            if str(stv).startswith("conflict") or stv in ("stage-failed",
                                                          "place-failed"):
                oldrec = (entry_old.get("stores") or {}).get(bname)
                b = BY_NAME.get(bname)
                if oldrec and b is not None and (b.root() / oldrec).is_dir():
                    stores[bname] = oldrec
                else:
                    stores.pop(bname, None)
        _register(reg, m["uuid"], m["to"], stores=stores)
        m["status"] = ("relinked-with-conflicts" if conflict and acted
                       else "conflict-skipped" if conflict
                       else "relinked" if acted else "path-updated")
        (conflicts if conflict else applied).append(m)
    return applied, conflicts

def apply_copies(reg: dict, copies: list, copy_history: bool = True) -> list:
    done = []
    for c in copies:
        try:
            nu = new_uuid()
            write_marker(c["copy_path"], nu)
            statuses = {}
            if copy_history:
                new_real = os.path.realpath(c["copy_path"])
                for b in enabled_backends():
                    if b.kind != "dir" or not b.available():
                        continue
                    hit = b.find(os.path.realpath(c["src"]))
                    if not hit:
                        continue
                    idx, src = hit
                    tgt = b.root() / b.keys[idx](new_real)
                    owner = {(e.get("stores") or {}).get(b.name): u
                             for u, e in reg["projects"].items()}
                    if tgt.name in owner and owner[tgt.name]:
                        statuses[b.name] = "target-owned-skip"
                        continue
                    fresh = not tgt.exists()
                    statuses[b.name] = safe_copy_tree(src, tgt)
                    src_real = os.path.realpath(c["src"])
                    tgt_comps = dict(b.companions(tgt.name, new_real, for_copy=True))
                    for tag, comp_src in b.companions(src.name, src_real,
                                                      for_copy=True):
                        comp_tgt = tgt_comps.get(tag)
                        if comp_tgt is None or not comp_src.is_file() \
                                or comp_tgt.exists():
                            continue
                        try:
                            comp_tgt.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(comp_src, comp_tgt)
                        except OSError:
                            pass
                    if fresh:
                        try:
                            note = b.after_copy(nu, src_real, new_real, tgt)
                            if note:
                                log(f"COPY [{b.name}] {tgt.name}: {note}")
                        except Exception as e:
                            warn(f"COPY [{b.name}] follow-up failed: {e}")
            _register(reg, nu, c["copy_path"])
            c["status"] = "duplicated" if copy_history else "claimed-no-history"
            c["stores"] = statuses
            c["new_uuid"] = nu
            log(f"COPY {c['copy_path']} ({c['status']}; {statuses})")
            done.append(c)
        except Exception as e:
            c["status"] = "failed"
            error(f"COPY failed {c['copy_path']}: {e}")
    return done

def apply_news(reg: dict, news: list) -> None:
    for n in news:
        _register(reg, n["uuid"], n["path"])
        log(f"NEW {n['path']} (stores: "
            f"{sorted((reg['projects'][n['uuid']].get('stores') or {}))})")

# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #

def cmd_encode(args):
    print(_key_claude(args.path))

def cmd_keys(args):
    real = os.path.realpath(args.path)
    rows = {}
    for b in BACKENDS:
        if b.kind == "dir":
            rows[b.name] = {"root": str(b.root()),
                            "keys": [k(real) for k in b.keys],
                            "exists": bool(b.find(real))}
        elif b.kind == "files":
            rows[b.name] = {"root": str(b.root()), "keyed_by": "embedded cwd"}
        else:
            rows[b.name] = {"root": str(b.root()), "note": b.note}
    print(json.dumps({"path": real, "backends": rows}, indent=2))

def cmd_tag(args):
    real = os.path.realpath(args.path)
    if not os.path.isdir(real):
        print(f"error: not a directory: {real}", file=sys.stderr)
        return 2
    with Lock():
        reg = load_registry()
        uid = read_marker(real) or new_uuid()
        if args.apply:
            write_marker(real, uid)
            _register(reg, uid, real)
            save_registry(reg)
    if args.apply:
        apply_badge(real, desired_marks(real, True))
    stores = detect_stores(real)
    print(f"{'tagged' if args.apply else 'would tag'}: {real}")
    print(f"   uuid={uid}  stores={sorted(stores) or '(none yet)'}")
    return 0

def plan_adoption(roots: list) -> tuple:
    """Store-corroborated adoption: a folder is planned when it carries a
    marker (current or legacy form) OR any backend provably has history for its
    exact path.  -> (planned [{real, uuid, stores}], how many are tracked
    already)."""
    reg = load_registry()
    known = {os.path.realpath(e["real_path"]) for e in reg["projects"].values()}
    path_to_uuid, _ = find_markers(roots)

    planned, already = [], 0
    for d in list_real_dirs(roots):
        rp = os.path.realpath(d)
        uid = path_to_uuid.get(rp)
        stores = detect_stores(rp)
        if rp in known and (uid is None or uid in reg["projects"]):
            already += 1 if (uid or stores) else 0
            continue
        if uid or stores:
            planned.append({"real": rp, "uuid": uid, "stores": sorted(stores)})

    # metadata-family discovery: one pass over each tool's session store maps
    # its recorded cwds to folders under the roots — a project used ONLY with
    # codex/copilot has no dir-keyed store to corroborate it otherwise
    planned_paths = {a["real"] for a in planned}
    rroots = [os.path.realpath(r) for r in roots]
    for b in enabled_backends():
        if b.kind != "files" or not b.available():
            continue
        try:
            cwds = b.collect_cwds()
        except Exception as e:
            warn(f"ADOPT {b.name} cwd sweep failed: {e}")
            continue
        for cwd in sorted(cwds):
            rp = os.path.realpath(cwd)
            if rp in known or rp in planned_paths or not os.path.isdir(rp):
                continue
            if not any(rp == rr or rp.startswith(rr + os.sep) for rr in rroots):
                continue
            planned.append({"real": rp, "uuid": path_to_uuid.get(rp),
                            "stores": [b.name]})
            planned_paths.add(rp)
    return planned, already

def apply_adoption(planned: list) -> list:
    """Track the planned folders (ADD-ONLY) -> what was adopted."""
    applied = []
    if not planned:
        return applied
    with Lock():
        reg = load_registry()
        for a in planned:
            uid = a["uuid"] or read_marker(a["real"]) or new_uuid()
            write_marker(a["real"], uid)
            _register(reg, uid, a["real"])
            applied.append({**a, "uuid": uid})
        save_registry(reg)
    for a in applied:
        apply_badge(a["real"], desired_marks(a["real"], True))
    return applied

def forgotten_note(planned: list) -> str:
    """For the trays' adopt question: which of the `adopt --json` planned
    folders the user told aht to forget, up to three by name, then "and N
    more" ("" when none)."""
    forgot = [a for a in planned if a.get("forgotten")]
    n, k = len(planned), len(forgot)
    if not k:
        return ""
    names = [tilde_path(str(a.get("real") or a.get("path") or "")) for a in forgot]
    if all(names):
        shown = names[:3]
        whom = (", ".join(shown[:-1]) + " and " + shown[-1] if len(shown) > 1 else shown[0]) \
            if k <= 3 else ", ".join(shown) + f" and {k - 3} more"
    else:                               # rows without a folder: counted
        whom = ("it" if n == 1 else "all of them" if k == n
                else "one of them" if k == 1 else f"{k} of them")
    return f"You told aht to forget {whom}: adopting takes {'it' if k == 1 else 'them'} on again."

def cmd_adopt(args):
    roots = args.roots or default_roots()
    planned, already = plan_adoption(roots)
    if args.only:
        only = {os.path.realpath(os.path.expanduser(p)) for p in args.only}
        planned = [a for a in planned if a["real"] in only]
    # adopt takes on a project the user told aht to forget, too (a way back);
    # it says which ones, so a front-end can say so before it asks
    forgot = load_registry().get("forgotten") or {}
    for a in planned:
        a["forgotten"] = bool(a["uuid"]) and a["uuid"] in forgot
    applied = apply_adoption(planned) if args.apply else []

    orphans_claude = len(orphan_history_dirs(load_registry()))

    result = {"applied": bool(args.apply), "planned": planned,
              "adopted": applied, "already": already,
              "orphans_claude": orphans_claude}
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{'APPLIED' if args.apply else 'DRY-RUN'} adoption over roots: {roots}\n")
        print(f"  planned : {len(planned)}")
        for a in planned:
            print(f"      + {a['real']}   [{', '.join(a['stores']) or 'marker only'}]"
                  + ("   (you told aht to forget it)" if a["forgotten"] else ""))
        print(f"  already tracked : {already}")
        print(f"  claude orphan histories (no matching folder) : {orphans_claude}")
        if orphans_claude:
            print("      match them with:  aht orphans --match")
        if args.apply:
            print(f"\n  APPLIED {len(applied)} adoption(s).")
    return 0

# ---- first-time setup: the folders to watch, the projects to take on -------- #

SETUP_SWITCHES = {"badges": "icons_enabled", "backups": "backup_enabled",
                  "notifications": "notifications", "update_check": "update_check"}

def tilde_path(p: str) -> str:
    home = str(Path.home())
    return "~" + p[len(home):] if p == home or p.startswith(home + os.sep) else p

def _setup_done_path() -> Path:
    return aht_home() / "run" / "setup.json"

def history_projects() -> list:
    """The folders the agents' histories say they worked in, those that still
    exist: Claude Code's stores and the session files of the agents that
    record their folder."""
    out = set()
    for d in _iter_history_dirs():
        cwd = transcript_cwd(d)
        if cwd and os.path.isdir(cwd):
            out.add(os.path.realpath(cwd))
    for b in enabled_backends():
        if b.kind != "files" or not b.available():
            continue
        try:
            out.update(os.path.realpath(c) for c in b.collect_cwds() if os.path.isdir(c))
        except Exception as e:
            warn(f"SETUP {b.name}: {e}")
    return sorted(out)

def setup_plan(roots: list = None) -> dict:
    """What a first-time setup offers: the folders to watch (the ones watched
    now, the usual ones, and wherever the histories say projects live), the
    projects found in the chosen ones, and the settings it asks about."""
    # where case does not matter, ~/code/app is inside ~/Code
    fold = (lambda p: os.path.normcase(p).casefold()) if CASE_BLIND else (lambda p: p)
    under = lambda p, r: fold(p) == fold(r) or fold(p).startswith(fold(r).rstrip(os.sep) + os.sep)
    home = os.path.realpath(str(Path.home()))
    now = [os.path.realpath(r) for r in default_roots()]
    chosen = [_disk_case(os.path.realpath(os.path.expanduser(r))) for r in roots] if roots else now
    found = history_projects()
    offer = _distinct_dirs(list(dict.fromkeys(now + chosen + [os.path.realpath(r)
                                                              for r in _default_watch_roots()])))
    # never offered: hidden folders, ones the scan skips, and where the system
    # and the package managers keep their files (~/Library, ~/AppData, ~/scoop)
    skip = {n.casefold() for n in prune_dirs() | {"Library", "AppData", "scoop"}}
    for p in found:                     # a folder right under home that holds projects
        if fold(p) == fold(home) or not under(p, home) or any(under(p, r) for r in offer):
            continue
        top = os.path.join(home, os.path.relpath(p, home).split(os.sep)[0])
        name = os.path.basename(top)
        try:                            # Windows: hidden or system by attribute
            hidden = getattr(os.stat(top), "st_file_attributes", 0) & 0x6
        except OSError:
            hidden = 0
        if not name.startswith(".") and name.casefold() not in skip and not hidden:
            offer = _distinct_dirs(offer + [top])
    planned, already = plan_adoption(chosen)
    # a project the user told aht to forget is offered, but not ticked
    forgot = load_registry().get("forgotten") or {}
    is_in = lambda r, rs: any(fold(r) == fold(x) for x in rs)
    return {"roots": [{"path": r, "watched": is_in(r, now), "chosen": is_in(r, chosen),
                       "projects": sum(under(p, r) for p in found), "exists": os.path.isdir(r)}
                      for r in offer],
            "projects": [{"path": a["real"], "agents": [BY_NAME[x].label if x in BY_NAME
                                                        else x for x in a["stores"]],
                          "forgotten": bool(a["uuid"]) and a["uuid"] in forgot}
                         for a in sorted(planned, key=lambda a: a["real"].lower())],
            "tracked": already, "elsewhere": [p for p in found
                                              if not any(under(p, r) for r in offer)
                                              and fold(p) != fold(home)],
            "policies": {"moves": cfg_get("move_policy"), "copies": cfg_get("copy_policy")},
            "switches": {k: bool(cfg_get(v)) for k, v in SETUP_SWITCHES.items()},
            "done": _setup_done_path().is_file()}

def cmd_setup(args):
    if args.dismiss:                    # "Not Now" in the window: do not offer it again
        f = aht_home() / "run" / "setup-later"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(str(time.time()))
        return 0
    if not args.apply:
        plan = setup_plan(args.roots)
        if args.json:
            print(json.dumps(plan, indent=2))
            return 0
        print("Folders to watch (✓ = chosen):")
        for r in plan["roots"]:
            print(f"  {'✓' if r['chosen'] else ' '} {tilde_path(r['path'])}"
                  f"   {r['projects']} project(s) with history"
                  + ("" if r["exists"] else "   (missing)"))
        print(f"Projects found there that aht does not track yet: {len(plan['projects'])}")
        for p in plan["projects"]:
            print(f"    + {tilde_path(p['path'])}   [{', '.join(p['agents'])}]"
                  + ("   (you told aht to forget it: only --adopt takes it on again)"
                     if p["forgotten"] else ""))
        print("Apply:  aht setup --apply [--roots FOLDER …] [--adopt PATH …] "
              "[--moves ask|apply|…] [--badges on|off] …")
        return 0
    roots = [_disk_case(os.path.realpath(os.path.expanduser(r))) for r in args.roots or []]
    with Lock():
        cfg = load_config()
        before = default_roots()
        if args.roots is not None:
            usual = [os.path.realpath(r) for r in _default_watch_roots()]
            if sorted(roots) == sorted(usual) and not cfg.get("watch_roots"):
                pass                    # the usual ones: they stay automatic
            else:
                cfg["watch_roots"] = roots
        for flag, key in (("moves", "move_policy"), ("copies", "copy_policy")):
            if getattr(args, flag):
                cfg[key] = getattr(args, flag)
        for flag, key in SETUP_SWITCHES.items():
            if getattr(args, flag) is not None:
                cfg[key] = getattr(args, flag) == "on"
        save_config(cfg)
    planned, _ = plan_adoption(default_roots())
    if args.adopt is not None and args.adopt:
        only = {os.path.realpath(os.path.expanduser(p)) for p in args.adopt}
        planned = [a for a in planned if a["real"] in only]
    elif args.adopt is not None:
        planned = []                    # --adopt with nothing: take on none
    else:                               # all, but not one the user told aht to forget
        forgot = load_registry().get("forgotten") or {}
        planned = [a for a in planned if not (a["uuid"] and a["uuid"] in forgot)]
    adopted = apply_adoption(planned)
    _setup_done_path().parent.mkdir(parents=True, exist_ok=True)
    _write_json(_setup_done_path(), {"at": time.time(), "version": VERSION})
    reloaded = False
    if default_roots() != before:       # with --json only the JSON goes to stdout
        reloaded = _reload_quietly(args.json)
    res = {"roots": default_roots(), "adopted": [a["real"] for a in adopted],
           "policies": {"moves": cfg_get("move_policy"), "copies": cfg_get("copy_policy")},
           "switches": {k: bool(cfg_get(v)) for k, v in SETUP_SWITCHES.items()},
           "watcher_reloaded": reloaded}
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print(f"watching: {', '.join(tilde_path(r) for r in res['roots'])}")
        print(f"took on {len(adopted)} project(s)")
    return 0

def score_candidates(store_dir: str, roots: list, limit: int = 8,
                     dirs: list = None) -> dict:
    hist = claude_backend().root() / store_dir
    orig = transcript_cwd(hist) if hist.is_dir() else None
    orig_leaf = os.path.basename(orig) if orig else None
    refs = transcript_file_refs(hist, orig) if orig else set()
    scored = []
    for d in (list_real_dirs(roots) if dirs is None else dirs):
        score, reasons = 0.0, []
        if orig_leaf and os.path.basename(d) == orig_leaf:
            score += 1.0
            reasons.append("leaf-name")
        if refs:
            present = sum(1 for r in refs if os.path.exists(os.path.join(d, r)))
            if present:
                score += 2.0 * (present / len(refs))
                reasons.append(f"files {present}/{len(refs)}")
        if _key_claude(d) == store_dir:
            score += 5.0
            reasons.append("exact-encode")
        if score > 0:
            scored.append({"path": d, "score": round(score, 3), "reasons": reasons})
    scored.sort(key=lambda x: -x["score"])
    return {"store": store_dir, "orig_path": orig, "orig_leaf": orig_leaf,
            "n_file_refs": len(refs), "candidates": scored[:limit]}

def cmd_suggest(args):
    roots = args.roots or default_roots()
    if not (claude_backend().root() / args.store).is_dir():
        print(json.dumps({"error": "no such claude store dir", "store": args.store}))
        return 2
    print(json.dumps(score_candidates(args.store, roots, args.limit), indent=2))
    return 0

def cmd_bind(args):
    """Bind an orphan claude store dir to a confirmed real folder (claude
    backend only — other dir backends key by hash, so their orphans cannot be
    matched from the outside; restore them from backups instead)."""
    real = os.path.realpath(args.to)
    if not os.path.isdir(real):
        print(f"error: not a directory: {real}", file=sys.stderr)
        return 2
    croot = claude_backend().root()
    old_store = croot / args.store
    new_name = _key_claude(real)
    with Lock():
        reg = load_registry()
        owner = {(e.get("stores") or {}).get("claude"): u
                 for u, e in reg["projects"].items()}
        target_owner = owner.get(new_name)
        uid = read_marker(real) or new_uuid()
        status = "registry-only"
        if new_name != args.store and (croot / new_name).exists() \
                and target_owner != uid:
            print(f"refusing: target store {new_name} already exists "
                  f"(another project or an orphan); not merging", file=sys.stderr)
            return 3
        if args.apply:
            if old_store.exists():
                status = safe_relink(old_store, croot / new_name)
            write_marker(real, uid)
            _register(reg, uid, real)
            save_registry(reg)
    if args.apply:
        apply_badge(real, desired_marks(real, True))
    print(f"{'bound' if args.apply else 'would bind'}: {args.store} -> {real}")
    print(f"   new store={new_name}  uuid={uid}  relink={status}")
    return 0

def resolve_policies(args) -> dict:
    """What reconcile does with moves and copies.  A new project is always
    taken on when it acts (--apply, --notify); --news is still accepted
    from old scripts and changes nothing."""
    if getattr(args, "apply", False):
        pol = {"moves": "apply", "copies": "duplicate"}
    elif getattr(args, "notify", False):
        pol = {"moves":  cfg_get("move_policy", "ask"),
               "copies": cfg_get("copy_policy", "ask")}
    else:
        pol = {"moves": "ignore", "copies": "ignore"}
    for k in ("moves", "copies"):
        v = getattr(args, k, None)
        if v:
            pol[k] = v
    for k, v in pol.items():
        if v not in POLICY_CHOICES[k]:
            raise SystemExit(f"invalid --{k}={v}; choose from {POLICY_CHOICES[k]}")
    return pol

def _selected(items: list, key: str, only: list) -> list:
    if not only:
        return items
    want = {_disk_case(os.path.realpath(p)) for p in only}   # the scan's spelling
    return [i for i in items if os.path.realpath(i[key]) in want]

def cmd_reconcile(args):
    # the watcher passes the roots its LaunchAgent was written with, which a
    # case-only rename in Finder leaves spelled the old way
    roots = _distinct_dirs([_disk_case(os.path.realpath(r))
                            for r in args.roots or default_roots()])
    pol = resolve_policies(args)
    only = getattr(args, "only", None) or []

    if getattr(args, "clear_declines", False):
        with Lock():
            reg = load_registry()
            n = len(reg.get("declined_moves", {}))
            reg["declined_moves"] = {}
            save_registry(reg)
        log(f"cleared {n} saved decline(s)")
    forced = pol["moves"] == "apply"

    with Lock():
        reg = load_registry()
        _, uuid_to_paths = find_markers(roots)
        moves, copies, news, missing = compute_actions(
            reg, uuid_to_paths, respect_declines=not forced)
    moves = _selected(moves, "to", only)
    copies = _selected(copies, "copy_path", only)
    news = _selected(news, "path", only)
    # the same folder under another spelling (a Mac ignores case: ~/code is
    # ~/Code) moved nowhere: relinked without asking, as the hook does
    respell = lambda ms: [m for m in ms if _same_folder(m["from"], m["to"])]
    respelled = respell(moves)
    moves = [m for m in moves if m not in respelled]
    do_respell = pol["moves"] != "ignore"

    def _stores_tag(uid, keyed_path):
        # stores are keyed by the path the project had when they were written,
        # so a moved folder's histories are still found under its OLD path
        agents = agents_of(current_stores(reg["projects"].get(uid),
                                          os.path.realpath(keyed_path)))
        return ", ".join(agents) if agents else "no history yet"

    asked = False
    if pol["moves"] == "ask" and moves:
        asked = True
        names = "\n".join("• %s  →  %s\n   histories: %s"
                          % (m["from"], m["to"], _stores_tag(m["uuid"], m["from"]))
                          for m in moves[:8])
        extra = "" if len(moves) <= 8 else "\n…and %d more" % (len(moves) - 8)
        ans = ask_dialog("%d tethered project(s) moved or renamed:\n\n%s%s\n\n"
                         "Relink the listed agent histories to the new location(s)?"
                         % (len(moves), names, extra),
                         ["Not now", "Relink"], "Relink")
        pol["moves"] = {"Relink": "apply", "Not now": "decline"}.get(ans, "ignore")
    if pol["copies"] == "ask" and copies:
        asked = True
        names = "\n".join("• %s\n   histories: %s"
                          % (c["copy_path"], _stores_tag(c["uuid"], c["src"]))
                          for c in copies[:8])
        extra = "" if len(copies) <= 8 else "\n…and %d more" % (len(copies) - 8)
        ans = ask_dialog("%d tethered project folder(s) were copied:\n\n%s%s\n\n"
                         "Duplicate the listed histories for the new copies?"
                         % (len(copies), names, extra),
                         ["Skip", "Duplicate"], "Duplicate")
        pol["copies"] = {"Duplicate": "duplicate", "Skip": "independent"}.get(ans, "ignore")

    do_moves = pol["moves"] == "apply"
    decline_moves = list(moves) if pol["moves"] == "decline" else []
    do_copies = pol["copies"] in ("duplicate", "independent")
    do_news = bool(args.apply) or getattr(args, "notify", False)

    conflicts, applied_moves, applied_copies = [], [], []
    if ((do_moves and moves) or (do_copies and copies)
            or (do_news and news) or decline_moves or (do_respell and respelled)):
        with Lock():
            reg = load_registry()
            _, uuid_to_paths = find_markers(roots)
            moves2, copies2, news2, missing = compute_actions(
                reg, uuid_to_paths, respect_declines=not forced)
            moves2 = _selected(moves2, "to", only)
            copies2 = _selected(copies2, "copy_path", only)
            news2 = _selected(news2, "path", only)
            same2 = respell(moves2)
            moves2 = [m for m in moves2 if m not in same2]
            same2 = same2 if do_respell else []
            declined = reg.setdefault("declined_moves", {})
            if do_moves or same2:
                applied_moves, conflicts = apply_moves(
                    reg, (moves2 if do_moves else []) + same2)
                for m in applied_moves:
                    declined.pop(m["uuid"], None)
            for m in decline_moves:
                declined[m["uuid"]] = os.path.realpath(m["to"])
            if do_copies:
                applied_copies = apply_copies(
                    reg, copies2, copy_history=(pol["copies"] == "duplicate"))
            if do_news:
                apply_news(reg, news2)
            for u in list(declined):
                if not any(os.path.realpath(p) == os.path.realpath(declined[u])
                           for p in uuid_to_paths.get(u, [])):
                    declined.pop(u, None)
            save_registry(reg)

    acted = bool(args.apply) or getattr(args, "notify", False)
    want_git_badges = cfg_get("icons_enabled", True) and cfg_get("icons_git", True)
    if acted and want_git_badges:
        changed_git = []
        with Lock():
            reg = load_registry()
            age = time.time() - float(reg.get("git_scan_at", 0) or 0)
            # Linux: new emblems (a version of aht's own "+") go on every git
            # folder once, not only on the ones that changed
            redo = IS_LINUX and reg.get("git_emblems") != EMBLEM_VERSION
            if bool(args.apply) or age > GIT_SCAN_INTERVAL or redo:
                tpaths = tethered_paths(reg)
                git_now = find_git_repos(roots)
                git_prev = set(reg.get("git_repos", []))
                changed_git = [(p, desired_marks(p, p in tpaths))
                               for p in ((git_now | git_prev) if redo else (git_now ^ git_prev))]
                reg["git_scan_at"] = time.time()
                if redo:
                    reg["git_emblems"] = EMBLEM_VERSION
                if git_now != git_prev:
                    reg["git_repos"] = sorted(git_now)
                save_registry(reg)
        for p, marks in changed_git:
            apply_badge(p, marks)

    if acted:
        rebadge = []
        with Lock():
            reg = load_registry()
            age = time.time() - float(reg.get("stores_scan_at", 0) or 0)
            sweep = bool(args.apply) or age > STORES_SCAN_INTERVAL
            rebadge = refresh_stores(reg, include_files=sweep)
            if sweep:
                reg["stores_scan_at"] = time.time()
            if sweep or reg.get("_dirty"):
                save_registry(reg)
        if cfg_get("icons_enabled", True):
            for p in rebadge:
                apply_badge(p, desired_marks(p, True))
        maybe_auto_backup()
        _spawn_mirror()
        _spawn_search_update()

    if applied_moves or applied_copies or conflicts:
        acted_backends = sorted(
            {b for m in applied_moves for b, s in m.get("stores", {}).items()
             if s in ("renamed", "same-name") or str(s).startswith("rewrote")},
            key=BACKEND_NAMES.index)
        bits = []
        if applied_moves:
            bits.append(f"{len(applied_moves)} relinked"
                        + (f" ({', '.join(acted_backends)})"
                           if acted_backends else ""))
        if applied_copies:
            bits.append(f"{len(applied_copies)} copied")
        if conflicts:
            bits.append(f"{len(conflicts)} store(s) NOT relinked "
                        f"(target occupied — see aht status)")
        notify_user("Agent project history", ", ".join(bits))

    print(json.dumps({"applied": acted, "policies": pol, "asked": asked,
                      "did_moves": do_moves, "did_copies": do_copies,
                      "copy_choice": pol["copies"],
                      "declined_moves": len(decline_moves),
                      "applied_moves": applied_moves,
                      "applied_copies": applied_copies,
                      "moves": moves, "copies": copies, "news": news,
                      "respelled": respelled,
                      "missing": missing, "conflicts": conflicts},
                     indent=2, default=str))
    return 0

def cmd_hook(args):
    """Claude Code SessionStart hook — the only agent CLI with hooks, so it
    doubles as the backstop for EVERY backend: on a detected move the claude
    store follows Claude's own transcript_path and the other backends are
    relinked by their key functions."""
    try:
        raw = sys.stdin.read()
    except Exception:
        raw = ""
    try:
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        data = {}
    cwd = os.path.realpath(data.get("cwd") or os.getcwd())
    if _inside(cwd, os.path.realpath(str(aht_home()))):
        return 0                    # a copy aht made (second opinion): not a project
    if data.get("hook_event_name") == "UserPromptSubmit":
        return _prompt_hook(data)   # every prompt: only the tab's name, and quickly
    tpath = data.get("transcript_path") or ""
    new_name = os.path.basename(os.path.dirname(tpath)) if tpath else ""
    if not new_name:
        new_name = _key_claude(cwd)
    croot = claude_backend().root()
    home = os.path.realpath(str(Path.home()))
    try:
        with Lock(timeout=5):
            reg = load_registry()
            uid = read_marker(cwd)
            if uid and uid in reg["projects"]:
                entry = reg["projects"][uid]
                old_real = os.path.realpath(entry["real_path"])
                if old_real != cwd:
                    # the old path still there is a copy, unless it is this
                    # very folder spelled otherwise (a Mac ignores case)
                    if os.path.isdir(old_real) and not _same_folder(old_real, cwd):
                        nu = new_uuid()
                        write_marker(cwd, nu)
                        _register(reg, nu, cwd)
                        save_registry(reg)
                        log(f"HOOK copy-detected, new id for {cwd}")
                    else:
                        old_store = (entry.get("stores") or {}).get("claude")
                        if not (old_store and (croot / old_store).is_dir()):
                            # not recorded yet (moved after its first session,
                            # before anything looked): it is under the old path
                            hit = claude_backend().find(old_real)
                            old_store = hit[1].name if hit else old_store
                        st = "no-old-store"
                        if old_store:
                            st = safe_relink(croot / old_store, croot / new_name)
                        m = {"uuid": uid, "from": old_real, "to": cwd,
                             "stores": {"claude": st}}
                        for b in enabled_backends():
                            if b.name == "claude":
                                continue
                            try:
                                if b.kind == "dir" and b.available():
                                    _apply_dir_moves(b, reg, [m])
                                elif b.kind == "files" and b.available():
                                    _apply_file_moves(b, reg, [m])
                            except Exception as e:
                                error(f"HOOK backend {b.name}: {e}")
                        _register(reg, uid, cwd)
                        save_registry(reg)
                        log(f"HOOK relink {entry['real_path']} -> {cwd} "
                            f"({m['stores']})")
                else:
                    rec = (entry.get("stores") or {}).get("claude")
                    if rec and rec != new_name:
                        st = safe_relink(croot / rec, croot / new_name)
                        _register(reg, uid, cwd)
                        save_registry(reg)
                        log(f"HOOK re-encode relink {cwd} ({st})")
            elif uid:
                _register(reg, uid, cwd)
                save_registry(reg)
                log(f"HOOK register-existing-marker {cwd}")
            else:
                if cwd != home:
                    nu = new_uuid()
                    write_marker(cwd, nu)
                    _register(reg, nu, cwd)
                    save_registry(reg)
                    log(f"HOOK tag-new {cwd}")
            # the store this session writes to, from Claude's own transcript
            # path, once Claude made it: its name need not be the path's key
            mine = reg["projects"].get(read_marker(cwd) or "")
            if mine is not None and tpath and not (mine.get("stores") or {}).get("claude") \
                    and _dir_has_entries(croot / new_name):
                mine.setdefault("stores", {})["claude"] = new_name
                reg["_dirty"] = True
            refresh_stores(reg, only_paths=[cwd])
            if reg.get("_dirty"):
                save_registry(reg)
    except TimeoutError:
        warn("HOOK lock timeout; will retry next session")
    except Exception as e:
        error(f"HOOK error: {e}")
    try:
        if cwd != home:
            apply_badge(cwd, desired_marks(cwd, True))
    except Exception:
        pass
    source = str(data.get("source") or "startup")
    sid = data.get("session_id")
    notes = [_hook_notes(cwd, sid if isinstance(sid, str) else None)]
    if source != "compact" and cwd != home:
        _spawn_checkpoint(cwd, sid, "claude")
    if source in ("startup", "clear", "resume") and cfg_get("informed_sessions", False):
        try:                        # USES TOKENS: only when the user turned it on
            notes.append(informed_note(cwd, current=sid, resumed=source == "resume"))
        except Exception as e:
            warn(f"HOOK informed note: {e}")
    notes = "\n\n".join(n for n in notes if n)
    try:
        title = tab_session_name(data, "SessionStart")
    except Exception as e:
        title = None
        warn(f"HOOK tab name: {e}")
    if title:                       # JSON, so Claude Code takes the name too
        out = {"hookEventName": "SessionStart", "sessionTitle": title}
        if notes:
            out["additionalContext"] = notes
        print(json.dumps({"hookSpecificOutput": out}))
    elif notes:
        print(notes)
    _spawn_auto_backup()
    _spawn_mirror()
    _spawn_search_update()
    return 0

# --------------------------------------------------------------------------- #
# Introspection commands
# --------------------------------------------------------------------------- #

MAC_LABEL = "com.aht.watcher"
LINUX_UNIT = "aht-watcher.service"

def launchagent_loaded() -> bool:
    try:
        r = subprocess.run(["launchctl", "list"], capture_output=True,
                           text=True, timeout=10)
    except Exception:
        return False
    for line in r.stdout.splitlines():
        if line.split("\t")[-1].strip() == MAC_LABEL:
            return True
    return False

def watcher_status() -> dict:
    st = {"platform": sys.platform, "owner": cfg_get("watcher_owner", "agent"),
          "installed": False, "running": False, "kind": None, "detail": ""}
    try:
        if IS_MAC:
            st["kind"] = "launchagent"
            plist = Path.home() / "Library/LaunchAgents" / f"{MAC_LABEL}.plist"
            st["installed"] = plist.is_file()
            st["running"] = launchagent_loaded()
        elif IS_LINUX:
            st["kind"] = "systemd-user"
            unit = Path.home() / ".config/systemd/user" / LINUX_UNIT
            st["installed"] = unit.is_file()
            if _have("systemctl"):
                r = subprocess.run(["systemctl", "--user", "is-active", LINUX_UNIT],
                                   capture_output=True, text=True, timeout=10)
                st["running"] = r.stdout.strip() == "active"
                st["detail"] = r.stdout.strip()
            if not st["installed"]:
                auto = Path.home() / ".config/autostart/aht-watcher.desktop"
                if auto.is_file():
                    st["kind"] = "xdg-autostart"
                    st["installed"] = True
    except Exception as e:
        st["detail"] = str(e)
    return st

def claude_remote_control() -> bool:
    """Whether Claude Code puts every session into the Claude app (/config →
    "Enable Remote Control for all sessions")."""
    try:
        return bool(json.loads((claude_home() / "settings.json").read_text())
                    .get("remoteControlAtStartup"))
    except Exception:
        return False

def hook_installed(event: str = "SessionStart") -> bool:
    s = Path.home() / ".claude/settings.json"
    try:
        data = json.loads(s.read_text())
        for group in data.get("hooks", {}).get(event, []):
            for h in group.get("hooks", []):
                c = h.get("command", "")
                if "aht.py" in c or "aht.exe" in c.lower():
                    return True
    except Exception:
        pass
    return False

def _hist_stats(entry: dict) -> dict:
    n, size, newest = 0, 0, 0.0
    for f, arc in _project_sources(entry):
        try:
            stt = f.stat()
        except OSError:
            continue
        size += stt.st_size
        newest = max(newest, stt.st_mtime)
        if f.suffix == ".jsonl":
            n += 1
    return {"sessions": n, "bytes": size,
            "last_activity": time.strftime("%Y-%m-%dT%H:%M:%S",
                                           time.localtime(newest))
                             if newest else None}

def backend_status() -> list:
    reg = load_registry()
    names = cfg_get("backends") or BACKEND_NAMES
    rows = []
    for b in BACKENDS:
        tracked = sum(1 for e in reg.get("projects", {}).values()
                      if (e.get("stores") or {}).get(b.name))
        rows.append({"name": b.name, "label": b.label, "kind": b.kind,
                     "confidence": b.confidence, "enabled": b.name in names,
                     "available": b.available(), "root": str(b.root()),
                     "root_source": b.root_source(),
                     "tracked_stores": tracked,
                     **({"note": b.note} if b.note else {})})
    return rows

def cmd_status(args):
    reg = load_registry()
    projects = reg.get("projects", {})
    alive = [u for u, e in projects.items() if os.path.isdir(e["real_path"])]
    orphan_dirs = [d.name for d in orphan_history_dirs(reg)]
    installed = [t for t in TERMINALS if app_installed(t)] if IS_MAC else []
    st = {
        "version": VERSION, "platform": sys.platform,
        "python": platform.python_version(),
        "aht_home": str(aht_home()),
        "registry": str(registry_path()),
        "tracked": len(projects), "tracked_alive": len(alive),
        "missing": len(projects) - len(alive),
        "orphan_claude_stores": len(orphan_dirs),
        "declined_moves": len(reg.get("declined_moves", {})),
        "watch_roots": default_roots(),
        "setup_done": _setup_done_path().is_file(),
        "setup_dismissed": (aht_home() / "run" / "setup-later").is_file(),
        "home": str(Path.home()),
        "autostart": tray_autostart(),
        "backends": backend_status(),
        "watcher": watcher_status(),
        "backups": backup_status(),
        "handover": handover_status(),
        "agent_clis": {n: agent_cli(n) for n in SWITCH_TARGETS},
        "log": {"path": str(log_path()),
                "recent_problems": recent_log_problems()},
        "hook_installed": hook_installed(),
        "prompt_hook_installed": hook_installed("UserPromptSubmit"),
        "claude_remote_control": claude_remote_control(),
        "iterm_api": iterm_api_on() if IS_MAC else None,
        "getting_started": getting_started("iTerm" in installed),
        "update": check_update(fetch=False),
        "claude_auto_continue": claude_auto_continue(),
        "terminals": {"installed": installed, "chosen": cfg_get("terminal_app"),
                      "used": terminal_choice()}
        if IS_MAC else {},
        "gui_dialogs": gui_dialogs_available(),
        "policies": {"moves": cfg_get("move_policy"),
                     "copies": cfg_get("copy_policy")},
    }
    if args.json:
        print(json.dumps(st, indent=2))
    else:
        w = st["watcher"]
        print(f"aht {VERSION}  ({sys.platform}, python {st['python']})")
        print(f"  tracked projects : {st['tracked']}  ({st['missing']} folder(s) missing)")
        print(f"  backends         :")
        for b in st["backends"]:
            mark = "✓" if b["available"] else "·"
            en = "" if b["enabled"] else "  [disabled]"
            print(f"      {mark} {b['name']:<9} {b['label']:<20} "
                  f"{b['kind']:<5} {b['confidence']:<11} "
                  f"{b['tracked_stores']} store(s){en}")
        print(f"  claude orphans   : {st['orphan_claude_stores']}   "
              f"(match with:  aht orphans --match)")
        bk = st["backups"]
        print(f"  history backups  : {'on' if bk['enabled'] else 'OFF'}   "
              f"{bk['snapshots']} snapshot(s) of {bk['projects']} project(s), "
              f"last run {bk['last_run'] or 'never'}")
        ho = st["handover"]
        if ho["remotes"]:
            print(f"  other machines   : {', '.join(sorted(ho['remotes']))}   "
                  f"{len(ho['away'])} project(s) handed over, "
                  f"{len(ho['mirrored'])} kept in sync")
        print(f"  watcher          : {w['kind']}  installed={w['installed']}  "
              f"running={w['running']}")
        print(f"  SessionStart hook: {'yes' if st['hook_installed'] else 'NO'} "
              f"(Claude Code — the only agent CLI with hooks)")
        print(f"  watched roots    : {', '.join(st['watch_roots'])}")
        gs = st["getting_started"]
        if gs:
            left = [g["title"] for g in gs if not g["ok"] and not g["optional"]]
            print(f"  getting started  : {sum(g['ok'] for g in gs)} of {len(gs)} done"
                  + (f"; to do: {', '.join(left)}" if left else "")
                  + "   (aht getting-started)")
        print(f"  policies         : moves={st['policies']['moves']} "
              f"copies={st['policies']['copies']}")
    return 0

def cmd_projects(args):
    reg = load_registry()
    out = []
    try:
        live = running_sessions()
    except Exception:
        live = []
    try:
        stops = [h for h in limit_stops(12) if not h["over"] and h.get("project")]
    except Exception:
        stops = []
    for uid, e in reg.get("projects", {}).items():
        row = {"uuid": uid, "real_path": e["real_path"],
               "exists": os.path.isdir(e["real_path"]),
               "stores": sorted((e.get("stores") or {})),
               "updated_at": e.get("updated_at"),
               "is_git": is_git(e["real_path"]) if os.path.isdir(e["real_path"]) else False,
               "away": (e.get("away") or {}).get("host"),
               "away_remote": (e.get("away") or {}).get("remote"),
               "away_since": (e.get("away") or {}).get("since"),
               "mirror": (e.get("mirror") or {}).get("remote")
               if (e.get("mirror") or {}).get("enabled") else None,
               "mirror_synced_at": (e.get("mirror") or {}).get("synced_at"),
               "mirror_status": (e.get("mirror") or {}).get("status"),
               # Keep in sync that sends nothing until it is turned on again:
               # {reason: "released", at, remote}
               "mirror_paused": (e.get("mirror") or {}).get("paused")
               if (e.get("mirror") or {}).get("enabled") else None,
               "handing": handing_row(e.get("handing"), uid),
               # an open hand-off to another agent: what Hand Back answers
               "relay": project_relay(e["real_path"]) if os.path.isdir(e["real_path"])
               else None,
               "agents": agents_of(e.get("stores") or {})}
        mine = [s["status"] for s in live
                if _inside(os.path.realpath(s["cwd"]), os.path.realpath(e["real_path"]))]
        # an open agent session: "waiting" (for you), "working" or "idle"
        row["open"] = None if not mine else (
            "waiting" if "waiting" in mine else
            "idle" if all(s == "idle" for s in mine) else "working")
        hit = next((h for h in stops if os.path.realpath(h["project"])
                    == os.path.realpath(e["real_path"])), None)
        row["limit"] = {k: hit.get(k) for k in ("session", "resets", "at", "until")} \
            if hit else None
        row.update(_hist_stats(e))
        out.append(row)
    out.sort(key=lambda r: r["real_path"].lower())
    if args.json:
        print(json.dumps({"projects": out, "limit_switch_to": limit_switch_target()},
                         indent=2))
    else:
        print(f"{len(out)} tethered project(s):")
        for r in out:
            flag = " " if r["exists"] else "!"
            print(f" {flag} {r['real_path']}"
                  + (f"   → handed over to {r['away']}" if r["away"] else "")
                  + (f"   (handover to {r['handing']['remote']} unfinished)"
                     if r["handing"] else ""))
            print(f"     [{', '.join(r['stores']) or 'no stores yet'}]  "
                  f"{r['sessions']} session(s), {r['bytes']/1024:.0f} KiB, "
                  f"last {r['last_activity'] or '—'}")
        if any(not r["exists"] for r in out):
            print("\n  ! = folder no longer at that path "
                  "(aht orphans --match, or aht prune --apply)")
    return 0

def cmd_orphans(args):
    """Claude store dirs no tracked folder owns (transcripts make them
    matchable).  Hash-keyed backends cannot be matched from outside — restore
    those from backups (aht restore) instead."""
    roots = args.roots or default_roots()
    reg = load_registry()
    dirs = list_real_dirs(roots) if args.match else None
    rows = []
    for d in orphan_history_dirs(reg):
        cwd = transcript_cwd(d)
        row = {"store": d.name, "orig_path": cwd,
               "orig_exists": bool(cwd) and os.path.isdir(cwd)}
        if args.match:
            sc = score_candidates(d.name, roots, args.limit, dirs=dirs)
            row["candidates"] = sc["candidates"]
        rows.append(row)
    if args.json:
        print(json.dumps({"orphans": rows}, indent=2))
    else:
        print(f"{len(rows)} orphan claude store dir(s):\n")
        for r in rows:
            print(f"  {r['store']}")
            print(f"     was: {r['orig_path'] or '(unknown)'}"
                  f"{'  [still there]' if r['orig_exists'] else ''}")
            for c in r.get("candidates", [])[:3]:
                print(f"       → {c['path']}   score {c['score']} "
                      f"({', '.join(c['reasons'])})")
            if r.get("candidates"):
                best = r["candidates"][0]
                print(f"     reconnect:  aht bind --store={r['store']} "
                      f"--to='{best['path']}' --apply")
            print()
    return 0

def stale_doubles(reg: dict) -> list:
    """Entries that list a folder ANOTHER entry owns — what is left when a
    folder was removed and made anew at the same path.  The folder's own
    marker names the owner; without that verdict nothing counts as stale."""
    by = {}                             # one folder, however it is spelled
    for u, e in reg.get("projects", {}).items():
        path = os.path.realpath(e["real_path"])
        by.setdefault(_folder_key(path), []).append((path, u))
    out = []
    for items in sorted(by.values()):
        path, ids = items[0][0], [u for _p, u in items]
        if len(ids) < 2 or not os.path.isdir(path):
            continue
        owner = read_marker(path)
        if owner in ids:
            out += [{"uuid": u, "real_path": p, "owner": owner,
                     "stores": sorted(reg["projects"][u].get("stores") or {})}
                    for p, u in items if u != owner and not reg["projects"][u].get("away")]
    return out

def cmd_prune(args):
    with Lock():
        reg = load_registry()
        gone = [{"uuid": u, "real_path": e["real_path"],
                 "stores": sorted(e.get("stores") or {})}
                for u, e in reg.get("projects", {}).items()
                if not os.path.isdir(e["real_path"])]
        twice = stale_doubles(reg)
        if args.apply and (gone or twice):
            for g in gone + twice:
                reg["projects"].pop(g["uuid"], None)
                reg.get("declined_moves", {}).pop(g["uuid"], None)
                log(f"PRUNE {g['real_path']} "
                    + ("(listed twice)" if g in twice else "(stores kept)"))
            save_registry(reg)
    result = {"applied": bool(args.apply), "pruned": gone, "doubles": twice,
              "remaining": len(load_registry().get("projects", {}))}
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{'PRUNED' if args.apply else 'WOULD PRUNE'} {len(gone) + len(twice)} "
              f"registry entr(ies); history stores are never deleted.")
        for g in gone:
            print(f"  - {g['real_path']}   [{', '.join(g['stores'])}]")
        for g in twice:
            print(f"  - {g['real_path']}   (listed twice; the folder's own entry stays)")
        if (gone or twice) and not args.apply:
            print("\n  run with --apply to remove these mappings")
    return 0

def cmd_forget(args):
    target = os.path.realpath(args.path) if args.path else None
    with Lock():
        reg = load_registry()
        hits = [(u, e) for u, e in reg.get("projects", {}).items()
                if (args.uuid and u == args.uuid)
                or (target and os.path.realpath(e["real_path"]) == target)]
        if not hits:
            print("no matching tethered project", file=sys.stderr)
            return 2
        if args.apply:
            for u, e in hits:
                reg["projects"].pop(u, None)
                reg.get("declined_moves", {}).pop(u, None)
                # its folder may still be somewhere with its marker: the
                # scan must not take it on again (a session there, tag or
                # adopt does)
                reg.setdefault("forgotten", {})[u] = time.strftime("%Y-%m-%dT%H:%M:%S")
                if args.remove_marker and os.path.isdir(e["real_path"]):
                    for rel in (MARKER_REL, LEGACY_MARKER_REL):
                        try:
                            (Path(e["real_path"]) / rel).unlink()
                        except Exception:
                            pass
                log(f"FORGET {e['real_path']}")
            save_registry(reg)
    for _u, e in hits:
        print(f"{'forgot' if args.apply else 'would forget'}: {e['real_path']}  "
              f"(history stores kept)")
    return 0

def cmd_config(args):
    if args.reset:
        with Lock():
            save_config({})
    changed = False
    with Lock():
        cfg = load_config()
        for kv in (args.set or []):
            if "=" not in kv:
                print(f"--set expects key=value, got {kv!r}", file=sys.stderr)
                return 2
            k, v = kv.split("=", 1)
            k = k.strip()
            if k in RETIRED_KEYS:       # an old script must not fail on it
                print(f"{k} is no longer used: {RETIRED_KEYS[k]}", file=sys.stderr)
                continue
            if k not in CONFIG_DEFAULTS:
                print(f"unknown key {k!r}; known: {', '.join(sorted(CONFIG_DEFAULTS))}",
                      file=sys.stderr)
                return 2
            try:
                cfg[k] = _coerce(k, v)
            except ValueError as e:
                print(str(e), file=sys.stderr)
                return 2
            changed = True
        for k in (args.unset or []):
            if cfg.pop(k.strip(), None) is not None:
                changed = True
        if changed:
            save_config(cfg)
    eff = dict(CONFIG_DEFAULTS)
    eff["watch_roots"] = default_roots()
    eff["backends"] = cfg_get("backends") or BACKEND_NAMES
    eff.update({k: v for k, v in load_config().items() if v is not None})
    eff["watch_roots"] = default_roots()    # each once, spelled as on disk
    if args.json:
        print(json.dumps({"path": str(config_path()), "effective": eff,
                          "explicit": load_config(), "defaults": CONFIG_DEFAULTS},
                         indent=2))
    else:
        print(f"config: {config_path()}")
        explicit = load_config()
        for k in sorted(eff):
            mark = "*" if k in explicit else " "
            print(f" {mark} {k} = {json.dumps(eff[k])}")
        print("\n  * = set explicitly; others are defaults")
    if changed and any(k.startswith("watch_roots") for k in (args.set or [])) \
            and not args.no_reload:
        _reload_quietly(args.json)
    return 0

def cmd_doctor(args):
    reg = load_registry()
    roots = default_roots()
    checks = []
    def ck(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": str(detail)})
    ck("aht home exists", aht_home().is_dir() or True, aht_home())
    ck("registry readable", registry_path().is_file() or not registry_path().exists(),
       registry_path())
    try:
        with Lock(timeout=5):
            ck("lock acquirable", True, lock_path())
    except Exception as e:
        ck("lock acquirable", False, e)
    ck("SessionStart hook registered (claude)", hook_installed())
    if IS_MAC and cfg_get("tab_names", True):
        ok = hook_installed("UserPromptSubmit")
        ck("UserPromptSubmit hook registered (sessions named after their tab)", ok,
           "" if ok else "run: aht install")
    w = watcher_status()
    if w["owner"] == "none":
        ck("a watcher is configured", False,
           "watching is off — only the claude hook is protecting you")
    else:
        ck("watcher installed", w["installed"], w["kind"])
        ck("watcher running", w["running"], w["detail"] or w["kind"])
    existing = [r for r in roots if os.path.isdir(r)]
    ck("watched roots exist", bool(existing), f"{len(existing)}/{len(roots)}: {roots}")
    ck("GUI dialogs available", gui_dialogs_available(),
       "prompts fall back to the configured policy without one")
    for b in backend_status():
        if b["enabled"]:
            ck(f"backend {b['name']} ({b['kind']}, {b['confidence']})",
               True, ("available, %d store(s) tracked" % b["tracked_stores"])
               if b["available"] else "tool not detected on this machine")
    if cfg_get("backup_enabled", True):
        try:
            backups_root().mkdir(parents=True, exist_ok=True)
            probe = backups_root() / ".doctor-probe"
            probe.write_text("ok")
            probe.unlink()
            ck("backup store writable", True, backups_root())
        except Exception as e:
            ck("backup store writable", False, e)
    if IS_MAC and cfg_get("icons_enabled", True) \
            and not os.environ.get("AHT_NO_ICONS"):
        tool = _badge_tool()
        ok, detail = False, "missing — run:  aht install"
        if tool is not None:
            import tempfile
            out = Path(tempfile.gettempdir()) / f"aht-badge-check-{os.getpid()}.png"
            try:
                r = subprocess.run([str(tool), "preview", str(out), "agent:aht"],
                                   capture_output=True, text=True, timeout=30)
                ok = r.returncode == 0 and out.is_file()
                detail = str(tool) if ok else (
                    f"exit {r.returncode} — macOS may have blocked it; run:  aht install")
            except OSError as e:
                detail = f"{e} — macOS may have blocked it; run:  aht install"
            finally:
                try:
                    out.unlink()
                except OSError:
                    pass
        ck("folder badge tool runs", ok, detail)
    if handover_supported() and remotes_config():
        rs = find_rsync()
        ck("handover: rsync 3 on this machine", bool(rs),
           rs.get("version") or "missing — on macOS:  brew install rsync")
    nprob = recent_log_problems()
    ck("no warnings/errors logged in the last 24h", nprob == 0,
       f"{nprob} — inspect with:  aht logs --errors")
    missing = [e["real_path"] for e in reg.get("projects", {}).values()
               if not os.path.isdir(e["real_path"])]
    ck("no missing project folders", not missing, f"{len(missing)} missing")
    twice = stale_doubles(reg)
    ck("no folder is listed twice", not twice,
       f"{len(twice)} — remove with:  aht prune --apply")
    orph = [d.name for d in orphan_history_dirs(reg)]
    ck("no orphan claude stores", not orph, f"{len(orph)} orphan(s)")
    if args.json:
        print(json.dumps({"checks": checks,
                          "ok": all(c["ok"] for c in checks)}, indent=2))
    else:
        for c in checks:
            print(f"  {'✓' if c['ok'] else '✗'} {c['check']}"
                  + (f"   — {c['detail']}" if c["detail"] else ""))
        bad = [c for c in checks if not c["ok"]]
        print(f"\n{len(checks)-len(bad)}/{len(checks)} checks passed")
    return 0

def cmd_backup(args):
    if args.offsite or args.fetch_offsite or args.offsite_list:
        try:
            st = offsite_list() if args.offsite_list else \
                offsite_fetch(args.offsite_from) if args.fetch_offsite else offsite_push()
        except HandoverError as e:
            if not args.quiet:
                print(str(e), file=sys.stderr)
            warn(f"OFFSITE {e}")
            return 1
        if args.json:
            print(json.dumps(st, indent=2))
        elif args.quiet:
            pass
        elif args.offsite_list:
            print(f"backups kept on {st['remote']}:" if st["folders"]
                  else f"{st['remote']} keeps no backups yet")
            for f in st["folders"]:
                print(f"   {f['name']:<20} {f['id'] or 'older aht':<14} "
                      f"{f['projects']} project(s), {f['files']} backup(s), "
                      f"{_human(f['bytes'])}, last {_clock(f['updated'])}"
                      + ("   (this computer)" if f["mine"] else ""))
        elif st["pulled"]:
            print(f"fetched from {st['machine']} ({st['from']['name']}): "
                  f"{st['files']} backup(s), {_human(st['bytes'])}")
            for k in st["renamed"]:
                print(f"   kept next to ours (another size): {k}")
        else:
            print(f"copied to {st['machine']}: {st['files']} backup(s), {_human(st['bytes'])}"
                  + (f"; {st['removed']} older one(s) removed there" if st["removed"] else ""))
            if st["legacy"]:
                print("   left alone there (an older aht's, not all of them are here): "
                      + ", ".join(st["legacy"]))
        return 0
    if args.list:
        reg = load_registry()
        rows = []
        root = backups_root()
        if root.is_dir():
            for d in sorted(p for p in root.iterdir() if p.is_dir()):
                snaps = _snapshots(d.name)
                if not snaps:
                    continue
                entry = reg.get("projects", {}).get(d.name)
                rows.append({"uuid": d.name,
                             "real_path": (entry or {}).get("real_path")
                             or snaps[-1].get("real_path"),
                             "tracked": entry is not None,
                             "snapshots": [{k: m.get(k) for k in
                                            ("stamp", "created_at", "backends",
                                             "files", "zip_bytes")}
                                           for m in snaps]})
        if args.json:
            print(json.dumps({"backup_root": str(root), "projects": rows},
                             indent=2))
        else:
            print(f"backup store: {root}")
            if not rows:
                print("  (no snapshots yet — run:  aht backup)")
            for r in rows:
                flag = " " if r["tracked"] else "?"
                print(f" {flag} {r['real_path'] or r['uuid']}")
                for s in r["snapshots"]:
                    print(f"     {s['stamp']}  "
                          f"[{', '.join(s.get('backends') or [])}]  "
                          f"{(s.get('zip_bytes') or 0)/1024:.0f} KiB")
            if any(not r["tracked"] for r in rows):
                print("\n  ? = project no longer tracked; reconnect with:  "
                      "aht restore <folder> --apply")
        return 0

    if args.prune:
        root = backups_root()
        n = 0
        if root.is_dir():
            for d in sorted(p for p in root.iterdir() if p.is_dir()):
                n += _prune_snapshots(d.name)
        print(f"pruned {n} snapshot(s)  (backup_keep={cfg_get('backup_keep', 10)})")
        return 0

    if args.auto:
        if os.environ.get("AHT_NO_BACKUP") or not cfg_get("backup_enabled", True):
            print(json.dumps({"ran": False, "reason": "disabled"}))
            return 0
        if not backup_due():
            print(json.dumps({"ran": False, "reason": "not-due"}))
            return 0

    only = None
    if args.uuid:
        only = args.uuid
    elif args.project:
        real = os.path.realpath(args.project)
        only = read_marker(real)
        if not only:
            print(f"error: no aht marker in {real}", file=sys.stderr)
            return 2

    results = backup_pass(only_uid=only)
    counts = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    if args.json:
        print(json.dumps({"ran": True, "counts": counts, "results": results},
                         indent=2))
    else:
        print(f"backed up {counts.get('backed-up', 0)} project(s)"
              + ("" if not counts else "  ("
                 + ", ".join(f"{v} {k}" for k, v in sorted(counts.items()))
                 + ")")
              + f"\n  store: {backups_root()}")
    return 0

def cmd_restore(args):
    real = os.path.realpath(args.path)
    if not os.path.isdir(real):
        print(f"error: not a directory: {real}", file=sys.stderr)
        return 2
    uid = args.uuid or read_marker(real)
    snaps = _snapshots(uid) if uid else []

    if not snaps:
        cands = match_snapshots(real)
        if args.json:
            print(json.dumps({"folder": real, "uuid": uid, "snapshots": 0,
                              "candidates": cands}, indent=2))
            return 1
        why = (f"no snapshots stored for its uuid {uid}" if uid
               else "it has no .aht/.project-id marker")
        print(f"cannot restore directly: {why}")
        if cands:
            print("\nbest-matching backed-up projects:")
            for c in cands:
                print(f"  score {c['score']:<5} {c['orig_path'] or c['uuid']}")
                print(f"        ({', '.join(c['reasons'])}; "
                      f"{c['snapshots']} snapshot(s); uuid {c['uuid']})")
            print(f"\nrestore the top match with:\n  aht restore "
                  f"\"{args.path}\" --uuid={cands[0]['uuid']} --apply")
        else:
            print(f"no stored snapshots match this folder  (store: {backups_root()})")
        return 1

    if args.stamp:
        snap = next((m for m in snaps if m["stamp"] == args.stamp), None)
        if snap is None:
            print(f"error: no snapshot {args.stamp}; have: "
                  + ", ".join(m["stamp"] for m in snaps), file=sys.stderr)
            return 2
    else:
        snap = snaps[-1]

    marker = read_marker(real)
    result = {"added": 0, "existing_kept": 0, "cwd_rewrites": 0,
              "per_backend": {}}
    if args.apply:
        result = _restore_snapshot(snap, real)
        with Lock():
            reg = load_registry()
            if not marker:
                write_marker(real, uid)
            _register(reg, marker or uid, real)
            save_registry(reg)
        apply_badge(real, desired_marks(real, True))
        log(f"RESTORE {uid}/{snap['stamp']} -> {real} ({result})")

    note = (f"folder already carries a different marker ({marker}); it was kept"
            if marker and marker != uid else None)
    out = {"status": "restored" if args.apply else "dry-run",
           "folder": real, "uuid": uid, "stamp": snap["stamp"],
           "from": snap.get("real_path"),
           "backends": snap.get("backends") or [], "note": note}
    out.update(result)
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print(f"{'restored' if args.apply else 'would restore'}: snapshot "
              f"{snap['stamp']} of {snap.get('real_path') or uid}  "
              f"[{', '.join(out['backends'])}]")
        if args.apply:
            print(f"   +{out['added']} file(s), {out['existing_kept']} already "
                  f"present, {out['cwd_rewrites']} session cwd value(s) "
                  f"re-pointed at the new path")
        else:
            print("   pass --apply to extract; existing files are never overwritten")
        if note:
            print(f"   note: {note}")
    return 0

def cmd_logs(args):
    """Show recent log lines; --errors filters to warnings + errors."""
    lines = []
    for f in (log_path().with_suffix(".log.1"), log_path()):
        try:
            lines += f.read_text(errors="replace").splitlines()
        except OSError:
            pass
    if args.watcher:
        try:
            lines += [f"[watcher-stream] {ln}" for ln in
                      (aht_home() / "aht-watcher.log")
                      .read_text(errors="replace").splitlines()[-args.lines:]]
        except OSError:
            pass
    if args.errors:
        lines = [ln for ln in lines if "[WARN " in ln or "[ERROR" in ln]
    out = lines[-args.lines:]
    if not out:
        print("no matching log lines" + (" — the log is clean" if args.errors
                                         else f" yet ({log_path()})"))
    for ln in out:
        print(ln)
    return 0

def recent_log_problems(hours: float = 24.0) -> int:
    """warn+error lines younger than `hours` (doctor + status surface this)."""
    cutoff = time.time() - hours * 3600
    n = 0
    for f in (log_path().with_suffix(".log.1"), log_path()):
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        for ln in text.splitlines():
            if "[WARN " not in ln and "[ERROR" not in ln:
                continue
            try:
                ts = time.mktime(time.strptime(ln[1:20], "%Y-%m-%d %H:%M:%S"))
                if ts >= cutoff:
                    n += 1
            except Exception:
                n += 1
    return n

def cmd_backends(args):
    """Where each agent CLI's history store lives — and how to point aht at it
    when a tool's store was not found automatically."""
    changed = []
    if args.set_root or args.clear_root:
        with Lock():
            cfg = load_config()
            roots_cfg = dict(cfg.get("backend_roots") or {})
            for kv in (args.set_root or []):
                if "=" not in kv:
                    print(f"--set-root expects name=/path, got {kv!r}",
                          file=sys.stderr)
                    return 2
                name, path = kv.split("=", 1)
                name = name.strip()
                if name not in BACKEND_NAMES + [AGY_STORE.name]:     # agy: its data folder
                    print(f"unknown backend {name!r}; known: "
                          f"{', '.join(BACKEND_NAMES + [AGY_STORE.name])}", file=sys.stderr)
                    return 2
                roots_cfg[name] = _expand(path)
                changed.append(name)
                if not os.path.isdir(roots_cfg[name]):
                    print(f"⚠ {roots_cfg[name]} does not exist (yet) — "
                          f"{name} will show unavailable until it does")
            for name in (args.clear_root or []):
                if roots_cfg.pop(name.strip(), None) is not None:
                    changed.append(name.strip())
            cfg["backend_roots"] = roots_cfg
            save_config(cfg)
    rows = backend_status()
    if args.json:
        print(json.dumps({"backends": rows, "changed": changed}, indent=2))
    else:
        for r in rows:
            mark = "✓" if r["available"] else "✗"
            src = "" if r["root_source"] == "default" else f"  [{r['root_source']}]"
            print(f"  {mark} {r['name']:<9} {r['root']}{src}")
            if not r["available"]:
                print(f"        not found — installed elsewhere?  "
                      f"aht backends --set-root {r['name']}=/path/to/store")
        if changed:
            print("\n  updated: " + ", ".join(sorted(set(changed))))
    return 0

def cmd_version(args):
    print(f"aht {VERSION} ({sys.platform}, python {platform.python_version()})")
    return 0

def _installer_script(name: str):
    """The platform installer shipped next to this core — in a checkout, in
    the installed tools dir, or in aht.app's Resources folder.  On Linux the
    one next to aht.py counts only in the tools dir: in a checkout that is
    the Mac installer, and the Linux one is in linux/."""
    here = Path(__file__).resolve().parent
    if not IS_LINUX:
        c = here / f"{name}.py"
        return c if c.is_file() else None
    for c, ok in ((here / "linux" / f"{name}.py", True),
                  (here / f"{name}.py", here.name == "agent-history-tether")):
        if ok and c.is_file():
            return c
    return None

def cmd_install(args):
    if not (IS_MAC or IS_LINUX):
        print("on Windows the installer is built into the exe:  aht.exe install")
        return 2
    script = _installer_script("install")
    if script is None:
        print("no installer found next to aht.py — run install.sh from a checkout")
        return 2
    cmd = [sys.executable, str(script)]
    if script.parent.name == "linux" and (script.parent / "install.sh").is_file():
        cmd = ["sh", str(script.parent / "install.sh")]   # a checkout: copy the files first
    # launched through aht.app's `aht` command: install from the bundle so the
    # watcher and hook get that (possibly newer) core and its prebuilt binaries
    src = args.src or os.environ.get("AHT_BUNDLE_RESOURCES")
    if not src and IS_MAC:
        src = _app_bundle_resources()
    if src and IS_MAC:
        cmd += ["--src", src]
    return subprocess.call(cmd)

def _app_bundle_resources():
    """An installed aht.app that is at least as new as this core: the place to
    (re)install from, since it carries the helpers prebuilt — a Mac without a
    compiler can then still repair a missing badge tool or watcher."""
    def ver(text):
        m = re.search(r'^VERSION = "([0-9.]+)"', text, re.M)
        return tuple(int(x) for x in m.group(1).split(".")) if m else ()
    for app in (Path("/Applications/aht.app"), Path.home() / "Applications/aht.app"):
        res = app / "Contents" / "Resources"
        try:
            if ver((res / "aht.py").read_text(encoding="utf-8")) >= ver(
                    f'VERSION = "{VERSION}"') and (res / "install.py").is_file():
                return str(res)
        except OSError:
            continue
    return None

def cmd_uninstall(args):
    if not (IS_MAC or IS_LINUX):
        print("on Windows the uninstaller is built into the exe:  aht.exe uninstall")
        return 2
    script = _installer_script("uninstall")
    if script is None:
        print("no uninstaller found next to aht.py — run uninstall.sh from a checkout")
        return 2
    flags = [f for f, on in (("--remove-icons", args.remove_icons),
                             ("--purge", args.purge)) if on]
    return subprocess.call([sys.executable, str(script)] + flags)

ABOUT = """\
agent-history-tether  (aht)

Keeps every AI coding agent's per-project history tethered to its project
folder when you move, rename, copy, or nest that folder — one watcher, one
marker, many agent CLIs — and badges managed folders.

BACKENDS (aht status shows which are active on this machine):
  claude    Claude Code           dir-rename, verified        + SessionStart hook
  gemini    Gemini CLI            dir-rename, high confidence
  cursor    Cursor Agent CLI      dir-rename, best-effort (self-verifying)
  opencode  OpenCode              dir-rename, best-effort (self-verifying)
  codex     OpenAI Codex CLI      cwd rewrite, backup-first
  copilot   GitHub Copilot CLI    cwd rewrite, best-effort, backup-first
  kimi-code Kimi Code 2.x         bucket rename + cwd re-point, verified
  kimi      Kimi CLI 1.x          dir-rename, verified (+ history file)

HOW:
  • a marker  .aht/.project-id  (a UUID) travels with each folder
    (legacy .claude/.project-id markers are read too)
  • a registry maps  uuid -> {real_path, per-backend stores}
  • a background watcher prompts to relink on move/rename/copy
  • the Claude Code SessionStart hook backstops every backend on session start
  • every project's histories are auto-backed-up across all backends

COMMANDS:
  aht guide                       every feature, with an example (also in the app)
  aht status | doctor             what is installed / tracked / wrong
  aht adopt --apply               tether this machine's existing projects
  aht reconcile                   read-only: what moved / was copied
  aht projects                    tethered projects + their stores
  aht orphans --match             claude histories with no folder
  aht bind --store=<name> --to=<path> --apply    reconnect a claude orphan
  aht backup / backup --list      snapshot / inspect (config: backup_*)
  aht restore <folder> --apply    reconnect a folder to a snapshot
  aht config --set k=v            settings (shared with every front-end)
  aht tag <folder> --apply        start tethering a folder
  aht keys <path>                 show each backend's key for a path
  aht backends                    store locations (--set-root when not found)
  aht logs [--errors]             recent log lines / just warnings + errors
  aht encode <path>               claude's dirname encoding for a path
  aht install | uninstall         set up / remove the watcher, hook and command

ACROSS AGENTS (Claude Code, Codex, Kimi Code, Antigravity):
  aht search <words>                    every session, also deleted ones in backups
  aht board                             open sessions here and on other machines
  aht switch <folder> --to kimi         continue the work in another agent
         [--resume | --brief-only]      … in its own session / only write the summary
  aht switch <folder> --back            hand it back into the first agent's own session
  aht relays <folder>                   who had the work when, with each summary
  aht journal <folder>                  a dated diary of the project
  aht rules <folder> [--unify]          one set of project rules for every agent
  aht secrets [folder]                  keys or passwords in the histories (masked)
  aht changes <folder> [--diff]         what the latest session changed in the files
  aht report [--since week] [--by agent]   time and sessions; --statement: AI-use text
  aht share <folder> --format html      a session as a page to share, keys masked
  aht tidy                              gone folders, histories without a folder
  aht notices --test                    how "waiting for you" notices arrive

HANDOVER (continue on another machine of yours, over ssh):
  aht remote discover                   machines of your network that qualify
  aht remote add <name> <user@host>     name a machine (as many as you like)
  aht remote check [name|all]           what it lacks, with the fix
  aht mirror <folder> --on              keep its copy there up to date
  aht handover <folder> --apply         send it and resume the session there
         [--task "…"]                   … and give it something to start on
  aht attach <folder>                   open that session
  aht reclaim <folder> --apply          bring files and history back

Data:  ~/.aht/  (registry.json, config.json, backups/, aht.log)
Docs:  README.md
"""

def cmd_guide(args):
    """The guide that ships with aht, with an example for each feature."""
    here = Path(__file__).resolve().parent
    for c in (here / "GUIDE.md", here.parent / "GUIDE.md"):
        if c.is_file():
            if args.path:
                print(c)
            else:
                print(c.read_text(encoding="utf-8"))
            return 0
    print("the guide was not found; it is GUIDE.md in "
          "https://github.com/havurgiray/agent-history-tether", file=sys.stderr)
    return 1

def cmd_about(_args):
    print(ABOUT)
    return 0

def _reload_watcher() -> bool:
    """Restart the watcher with the current roots, through the platform's
    installer.  -> whether it was restarted."""
    if cfg_get("watcher_owner", "agent") == "none":
        print("watching is off (watcher_owner=none) — nothing to reload")
        return False
    if IS_MAC and not (Path.home() / ".aht/tools/agent-history-tether/watcher").is_file():
        # aht.app or Homebrew's aht before `aht install`: no LaunchAgent may
        # start a watcher that is not there
        print("the watcher is not installed yet — run 'aht install' to set it up")
        return False
    here = Path(__file__).resolve().parent
    if IS_LINUX:                        # a checkout's install.py is the Mac one
        script = _installer_script("install")
        search = [script.parent] if script else []
    else:
        search = [here, here / "macos"]
    old = list(sys.path)
    try:
        for d in search:
            if (d / "install.py").is_file():
                sys.path.insert(0, str(d))
                try:
                    import importlib
                    install = importlib.import_module("install")
                    importlib.reload(install)
                    writer = getattr(install, "write_service", None) \
                        or install.write_plist
                    writer()
                    install.load_agent()
                    print("✓ watcher reloaded with the current roots")
                    return True
                finally:
                    sys.path[:] = old
        raise FileNotFoundError("install.py not found next to aht.py")
    except (Exception, SystemExit) as e:    # an installer may exit while it loads
        why = e if isinstance(e, Exception) else f"the installer stopped with {e.code}"
        print(f"⚠ could not reload the watcher ({why}); re-run the installer")
        return False

def _reload_quietly(json_out: bool) -> bool:
    """_reload_watcher for a command that prints JSON: what the reload says
    goes to stderr then, so the JSON is all there is on stdout."""
    import contextlib
    with contextlib.redirect_stdout(sys.stderr) if json_out else contextlib.nullcontext():
        return _reload_watcher() is not False

def cmd_roots(args):
    cfg = load_config()
    roots = cfg.get("watch_roots") or _default_watch_roots()
    changed = False
    for a in (args.add or []):
        e = _expand(a)
        if e not in roots:
            roots.append(e)
            changed = True
    for r in (args.remove or []):
        e = _expand(r)
        if e in roots:
            roots = [x for x in roots if x != e]
            changed = True
    if changed:
        cfg["watch_roots"] = roots
        save_config(cfg)
    print(f"watched roots  ({config_path()}):")
    for r in roots:
        print(f"  {r}" + ("" if os.path.isdir(r) else "   (does not exist yet)"))
    if changed:
        if args.no_reload:
            print("\nconfig updated — run 'aht reload' to apply it to the watcher.")
        else:
            print()
            _reload_watcher()
    return 0

def cmd_reload(args):
    _reload_watcher()
    return 0

def cmd_icons(args):
    roots = args.roots or default_roots()
    with Lock():
        reg = load_registry()
        tpaths = tethered_paths(reg)
        gpaths = find_git_repos(roots)
        if args.refresh:
            refresh_stores(reg, include_files=True)
            reg["stores_scan_at"] = time.time()
            reg["git_repos"] = sorted(gpaths)
            save_registry(reg)
        plan = [(p, desired_marks(p, p in tpaths)) for p in sorted(tpaths | gpaths)]
    both = tpaths & gpaths
    print(f"tethered projects: {len(tpaths)}   git repos under roots: "
          f"{len(gpaths)}   both: {len(both)}")
    if args.refresh:
        for p, marks in plan:
            apply_badge(p, marks)
        print(f"refreshed {len(plan)} folder icon(s).")
    else:
        print("(dry run — pass --refresh to apply the badges)")
    return 0

# --------------------------------------------------------------------------- #
# Handover: keep working on a project on another machine of yours, then take
# it back.  Everything is driven from THIS machine over ssh + rsync; the other
# machine needs python3, rsync, tmux (or byobu) and the agent CLI, nothing of
# aht installed.  The same absolute path is used on both sides, because agent
# CLIs key their history on it.
#
#   remote    a machine reachable over ssh, named in the config
#   mirror    a background one-way sync that keeps a project's copy warm there,
#             so a handover only has to send the last changes
#   handover  final sync, then the session is resumed there inside tmux/byobu
#   reclaim   files and history come back, three-way against what left
#
# SAFETY invariants:
#   (1) nothing is transferred while an agent session or another process is
#       running in the project on the side that gives it away;
#   (2) a transcript only comes back as a CONTINUATION of what left: the copy
#       that stayed behind must be an exact prefix of the returning one;
#   (3) whatever a sync replaces or removes is moved into a backup dir first.
# --------------------------------------------------------------------------- #

HANDOVER_SKIP = (
    # this machine's own metadata
    "Icon\r", ".DS_Store", "._*", ".Spotlight-V100", ".Trashes", ".fseventsd",
    ".aht-rsync-partial",
    # rebuilt per machine: one OS's binaries are useless on the other
    "node_modules", ".venv", "venv", "__pycache__", ".tox", ".mypy_cache",
    ".pytest_cache", ".next", "DerivedData", ".gradle",
)
IDLE_SHELLS = {"zsh", "bash", "sh", "fish", "dash", "ksh", "tcsh", "csh",
               "login", "tmux", "tmux: server", "tmux: client", "byobu",
               "screen", "sshd", "mosh-server"}
AGENT_MARK = "@@AHT@@"
SCRATCH_MAX_BYTES = 100 * 1024 * 1024

class HandoverError(Exception):
    pass

class LinkError(HandoverError):
    """The link dropped or the other machine went quiet: whether the last
    step happened there is not known."""

def can_send_projects() -> bool:
    """Projects can move between this machine and another: handover, take
    back, keep in sync, the night shift and the offsite copy."""
    return os.name != "nt" and not getattr(sys, "frozen", False)

def can_reach_machines() -> bool:
    """Other machines can be asked: their sessions, notices, search and
    backups.  For now the same as can_send_projects(); in the end only an ssh
    client is needed."""
    return can_send_projects()

handover_supported = can_send_projects      # the old name, for untouched callers

def handover_skip() -> list:
    extra = cfg_get("handover_excludes") or []
    return list(HANDOVER_SKIP) + [str(x) for x in extra if x]

def _skip_name(name: str, skip) -> bool:
    return any(fnmatch.fnmatchcase(name, pat) for pat in skip)

def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)

_DRIVE = re.compile(r"[A-Za-z]:(?:[\\/]|$)")

def _is_abs(p) -> bool:
    """An absolute path on any of the three systems: /x, C:\\x, C:/x, \\\\server\\x."""
    p = str(p or "")
    return p.startswith(("/", "\\\\")) or bool(_DRIVE.match(p))

def _inside(path: str, root: str) -> bool:
    path, root = _nfc(str(path)), _nfc(str(root))
    if _DRIVE.match(root) or root.startswith("\\\\"):
        # a Windows path: either separator, and a drive's names ignore case
        path, root = path.replace("\\", "/").casefold(), root.replace("\\", "/").casefold()
    path, root = path.rstrip("/"), root.rstrip("/")
    return path == root or path.startswith(root + "/")

def handover_dir(uid: str) -> Path:
    return aht_home() / "handover" / uid

def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")

def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")

def _human(n) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024

# ---- this install, and the copy of it that runs on the other machine ------- #

AGENT_PROTOCOL = 2      # what the far end speaks; its probe also names its ops

def _core_text() -> bytes:
    """The core's own bytes: what runs on the other machine.  In the Windows
    exe it travels as core/aht.py next to the program."""
    if getattr(sys, "frozen", False):
        p = Path(getattr(sys, "_MEIPASS", "") or ".") / "core" / "aht.py"
    else:
        p = Path(__file__).resolve()
    try:
        return p.read_bytes()
    except OSError:
        raise HandoverError("this build of aht lacks its own core (core/aht.py)")

_CORE_ID = []

def core_id() -> str:
    """The first 12 hex digits of the core's sha256: the far copy's name."""
    if not _CORE_ID:
        _CORE_ID.append(hashlib.sha256(_core_text()).hexdigest()[:12])
    return _CORE_ID[0]

def machine_path() -> Path:
    return aht_home() / "machine.json"

def machine_id(create: bool = False):
    """This install's own id: 12 random hex digits in ~/.aht/machine.json, not
    in config.json, so a copied config cannot clone it.  Only made when
    `create`: a copy of aht that another machine runs here never makes one."""
    try:
        d = json.loads(machine_path().read_text())
        if re.fullmatch(r"[0-9a-f]{12}", str(d.get("id") or "")):
            return d["id"]
    except (OSError, ValueError, AttributeError):
        pass
    if not create:
        return None
    d = {"id": os.urandom(6).hex(), "name": _here(), "created": _now()}
    p = machine_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(p, "x") as fh:            # two at once: the first one wins
            json.dump(d, fh, indent=1)
        return d["id"]
    except FileExistsError:
        mid = machine_id()
        if mid:
            return mid
    _write_json(p, d)                       # there, but unreadable
    return d["id"]

def _sandbox_env(home: str) -> dict:
    """The variables aht runs with on a test machine or in a sandbox: a home of
    its own with aht's state and Claude's store in it, no badges, notices,
    backups or syncs, and a tmux server of its own."""
    return {"HOME": home, "AHT_HOME": home + "/.aht",
            "AHT_ROOT_CLAUDE": home + "/.claude/projects",
            "AHT_NO_ICONS": "1", "AHT_NO_NOTIFY": "1", "AHT_NO_BACKUP": "1",
            "AHT_NO_MIRROR": "1", "AHT_TMUX_SOCKET": "aht-sbx"}

def _tmux_socket() -> list:
    s = os.environ.get("AHT_TMUX_SOCKET")
    return ["-L", s] if s else []

def _test_drop(step: str, where: str) -> None:
    """Tests: AHT_TEST_DROP=<step> cuts the link right after that step."""
    if os.environ.get("AHT_TEST_DROP") == step:
        raise LinkError(f"the link to {where} dropped after “{step}” (test)")

# ---- what is running in a folder ------------------------------------------ #

def claude_home() -> Path:
    return claude_backend().root().parent

def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        # on Windows signal 0 is CTRL_C_EVENT: ask the process table instead
        try:
            import ctypes
            k = ctypes.windll.kernel32
            h = k.OpenProcess(0x1000, False, int(pid))   # QUERY_LIMITED_INFORMATION
            if not h:
                return False
            code = ctypes.c_ulong()
            ok = k.GetExitCodeProcess(h, ctypes.byref(code))
            k.CloseHandle(h)
            return bool(ok) and code.value == 259          # STILL_ACTIVE
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False

def _proc_started(pid: int):
    try:
        r = subprocess.run(["ps", "-p", str(pid), "-o", "lstart="],
                           capture_output=True, text=True, timeout=10,
                           cwd="/", env={**os.environ, "LC_ALL": "C"})
        return time.mktime(time.strptime(" ".join(r.stdout.split()),
                                         "%a %b %d %H:%M:%S %Y"))
    except Exception:
        return None

def running_sessions(inside: str = None, home: Path = None) -> list:
    """Claude Code sessions open right now, from the CLI's own per-process
    records (<claude home>/sessions/<pid>.json).  A record counts unless its
    process is provably gone: in doubt, the session is running."""
    out = []
    inside = os.path.realpath(inside) if inside else None
    try:
        files = sorted(((home or claude_home()) / "sessions").glob("*.json"))
    except OSError:
        return out
    for f in files:
        try:
            rec = json.loads(f.read_text())
            pid = int(rec.get("pid") or f.stem)
        except Exception:
            continue
        if not _pid_alive(pid):
            continue
        try:                                # same pid, other process: stale
            born = time.mktime(time.strptime(" ".join(str(rec["procStart"]).split()),
                                             "%a %b %d %H:%M:%S %Y"))
            seen = _proc_started(pid)
            # the record's clock may be UTC and ours local: equal start times
            # differ by a whole number of quarter hours
            off = abs(seen - born) % 900 if seen is not None else 0
            if min(off, 900 - off) > 5:
                continue
        except Exception:
            pass
        cwd = str(rec.get("cwd") or "")
        if inside and not _inside(os.path.realpath(cwd), inside):
            continue
        wait, name = rec.get("waitingFor"), rec.get("name")
        out.append({"pid": pid, "cwd": cwd, "session": rec.get("sessionId"),
                    "status": str(rec.get("status") or "unknown"),
                    # it may quote a command with a key in it, and it goes
                    # on to other machines and the phone; so may a name
                    "waiting_for": redact(wait) if isinstance(wait, str) else None,
                    "since": _when(rec.get("statusUpdatedAt")),
                    "kind": rec.get("kind"),
                    "name": redact(name) if isinstance(name, str) else name})
    return out

def processes_inside(path: str) -> list:
    """This user's processes whose working directory is inside `path`: a dev
    server, a build, another agent CLI.  Shells that merely sit in the folder
    are left out."""
    if os.name == "nt":                 # no lsof and no /proc: nothing known
        return []
    me = {os.getpid(), os.getppid()}
    path = os.path.realpath(path)
    rows = []
    uid = os.getuid()
    if IS_LINUX:
        for d in os.listdir("/proc"):
            if not d.isdigit():
                continue
            try:
                if os.stat(f"/proc/{d}").st_uid != uid:
                    continue
                rows.append((int(d), Path(f"/proc/{d}/comm").read_text().strip(),
                             os.readlink(f"/proc/{d}/cwd")))
            except OSError:
                continue
    else:
        lsof = next((c for c in ("/usr/sbin/lsof", "/usr/bin/lsof")
                     if os.path.exists(c)), "lsof")
        try:
            # from "/": our own helper must not count as running in there
            r = subprocess.run([lsof, "-a", "-u", str(uid), "-d", "cwd", "-Fpcn"],
                               capture_output=True, text=True, timeout=60, cwd="/")
        except Exception:
            return []
        pid, name = None, ""
        for line in r.stdout.splitlines():
            if line.startswith("p"):
                pid, name = int(line[1:]), ""
            elif line.startswith("c"):
                name = line[1:]
            elif line.startswith("n") and pid is not None:
                rows.append((pid, name, line[1:]))
    out = []
    for pid, name, cwd in rows:
        if pid in me or name.lstrip("-") in IDLE_SHELLS:
            continue
        if _inside(cwd, path):
            out.append({"pid": pid, "name": name, "cwd": cwd})
    return out

def activity_in(path: str) -> dict:
    """{sessions, processes}: everything that stands in the way of giving the
    folder at `path` away."""
    sess = running_sessions(inside=path)
    own = {s["pid"] for s in sess}
    return {"sessions": sess,
            "processes": [p for p in processes_inside(path) if p["pid"] not in own]}

def _activity_blockers(act: dict, where: str) -> list:
    out = []
    for s in act.get("sessions") or []:
        busy = s.get("status") != "idle"
        if s.get("status") == "waiting":
            out.append(f"an agent session in this project {where} is WAITING for you"
                       + (f" ({s['waiting_for']})" if s.get("waiting_for") else "")
                       + f" (pid {s['pid']}) — answer it, let it finish, then exit it")
            continue
        out.append(f"an agent session is {'WORKING' if busy else 'open'} in this "
                   f"project {where} (pid {s['pid']}"
                   + (f", “{s['name']}”" if s.get("name") else "") + ") — "
                   + ("wait until it has finished, then exit it" if busy
                      else "exit it first (/exit)"))
    return out

# ---- manifests -------------------------------------------------------------- #

def _rel_key(p: str, root: str) -> tuple:
    """(key, name on disk) of `p` below `root`: the key always uses "/" and
    NFC, so a Mac's decomposed names and Windows' separators compare equal
    to Linux's."""
    rel = os.path.relpath(p, root)
    if os.sep != "/":
        rel = rel.replace(os.sep, "/")
    return _nfc(rel), rel

def tree_manifest(root: str, skip=None) -> dict:
    """{files: {key: [size, mtime] | ["l", target]}, raw: {key: name on disk},
    dirs: [key], modes: {key: mode}, twins: {key: [names]}} — `dirs` lists
    every folder, so an empty one (a git repo's refs/heads) is made again;
    `modes` the files with an executable bit (not on Windows); `twins` the
    names that are one key in two Unicode forms."""
    skip = list(handover_skip() if skip is None else skip)
    files, raw, dirs, modes, twins = {}, {}, [], {}, {}
    root = str(root)
    for dp, dns, fns in os.walk(root):
        keep = []
        for d in dns:
            if _skip_name(d, skip):
                continue
            if os.path.islink(os.path.join(dp, d)):
                fns.append(d)               # a linked folder travels as a link
            else:
                keep.append(d)
                dirs.append(_rel_key(os.path.join(dp, d), root)[0])
        dns[:] = keep
        for n in fns:
            if _skip_name(n, skip):
                continue
            p = os.path.join(dp, n)
            try:
                st = os.lstat(p)
            except OSError:
                continue
            if stat.S_ISLNK(st.st_mode):
                try:
                    val = ["l", os.readlink(p)]
                except OSError:
                    continue
            elif stat.S_ISREG(st.st_mode):
                val = [st.st_size, int(st.st_mtime)]
            else:
                continue
            key, rel = _rel_key(p, root)
            if key in files:
                twins.setdefault(key, [raw.get(key) or key]).append(rel)
            files[key] = val
            if key != rel:
                raw[key] = rel
            if os.name != "nt" and val[0] != "l" and st.st_mode & 0o111:
                modes[key] = stat.S_IMODE(st.st_mode)
    return {"files": files, "raw": raw, "dirs": sorted(dirs), "modes": modes,
            "twins": twins}

def file_sha256(path, limit: int = None) -> str:
    h = hashlib.sha256()
    left = limit
    with open(path, "rb") as fh:
        while left is None or left > 0:
            chunk = fh.read(1 << 20 if left is None else min(1 << 20, left))
            if not chunk:
                break
            h.update(chunk)
            if left is not None:
                left -= len(chunk)
    return h.hexdigest()

def three_way(left_here: dict, left_there: dict, here: dict, there: dict) -> dict:
    """What happens to every path when a tree comes back.  `left_here` /
    `left_there` are the two sides right after the handover, `here` / `there`
    the two sides now."""
    plan = {"take": [], "new": [], "delete": [], "conflict": [], "kept": []}
    for k in sorted(set(left_here) | set(left_there) | set(here) | set(there)):
        h, t = here.get(k), there.get(k)
        if t == left_there.get(k):          # untouched over there
            if h != left_here.get(k):
                plan["kept"].append(k)      # changed only here
            continue
        if h == t:
            continue                        # the same change on both sides
        if h == left_here.get(k):           # untouched here
            if t is None:
                plan["delete"].append(k)
            elif h is None:
                plan["new"].append(k)
            else:
                plan["take"].append(k)
        elif t is None:
            plan["kept"].append(k)          # removed there, changed here: ours stays
        elif h is None:
            plan["take"].append(k)          # removed here, changed there
        else:
            plan["conflict"].append(k)
    return plan

# ---- rsync ------------------------------------------------------------------ #

_RSYNC = {}

def find_rsync() -> dict:
    """{path, version, iconv} of the newest rsync on this machine.  macOS ships
    an old-protocol openrsync without --iconv; Homebrew's is preferred."""
    if _RSYNC:
        return _RSYNC
    best = None
    for c in [cfg_get("rsync_path"), "/opt/homebrew/bin/rsync",
              "/usr/local/bin/rsync", shutil.which("rsync"), "/usr/bin/rsync"]:
        if not c or not os.path.exists(str(c)):
            continue
        try:
            r = subprocess.run([str(c), "--version"], capture_output=True,
                               text=True, timeout=15)
        except Exception:
            continue
        m = re.search(r"rsync\s+version\s+(\d+)\.(\d+)(?:\.(\d+))?", r.stdout)
        if not m:
            continue                        # openrsync and friends
        ver = tuple(int(x or 0) for x in m.groups())
        caps = r.stdout.replace("\n", " ")
        info = {"path": str(c), "version": ".".join(map(str, ver)), "ver": ver,
                "iconv": bool(re.search(r"(?<!no )iconv", caps))}
        if best is None or info["ver"] > best["ver"]:
            best = info
    _RSYNC.update(best or {})
    return _RSYNC

def _ssh_opts() -> list:
    run = aht_home() / "run"
    try:
        run.mkdir(parents=True, exist_ok=True)
        os.chmod(run, 0o700)
    except OSError:
        pass
    opts = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
            "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=4"]
    # Windows' ssh stops with "getsockname failed: Not a socket" when any of
    # the Control options is set.  And a socket's path holds 104 bytes on a
    # Mac: with %C's 40 hex digits and the 17 characters ssh adds while it
    # makes one, a long aht folder would stop every connection
    if os.name == "nt" or len(str(run).encode("utf-8")) + 62 > 103:
        return opts
    return opts + ["-o", "ControlMaster=auto", "-o", f"ControlPath={run}/ssh-%C",
                   "-o", "ControlPersist=60"]

def _tailscale_exe():
    return os.environ.get("AHT_TAILSCALE") or find_tool("tailscale") or next(
        (c for c in ("/Applications/Tailscale.app/Contents/MacOS/Tailscale",)
         if os.path.exists(c)), None)

def tailscale_address(host: str):
    """The Tailscale address of a machine named `host`, from the network's own
    list — for when the name does not resolve (MagicDNS on macOS can stop
    answering after sleep or a network change while the tailnet works)."""
    ts = _tailscale_exe()
    if not ts:
        return None
    try:
        r = subprocess.run([ts, "status", "--json"], capture_output=True, text=True,
                           timeout=15, cwd="/", **_NO_WINDOW)
        peers = (json.loads(r.stdout).get("Peer") or {}).values()
    except Exception:
        return None
    h = host.lower().rstrip(".")
    for p in peers:
        names = {str(p.get("HostName") or "").lower(),
                 str(p.get("DNSName") or "").lower().rstrip(".")}
        names.add(next(iter(names - {""}), "").split(".")[0])
        if h in names or h == str(p.get("DNSName") or "").lower().split(".")[0]:
            ips = p.get("TailscaleIPs") or []
            return next((ip for ip in ips if ":" not in ip), ips[0] if ips else None)
    return None

def _resolves(host: str) -> bool:
    import socket
    try:
        socket.getaddrinfo(host, 22)
        return True
    except (OSError, UnicodeError):
        return False

_STAT_RE = {
    "files": re.compile(r"Number of regular files transferred:\s*([\d,.]+)"),
    "bytes": re.compile(r"Total transferred file size:\s*([\d,.]+)"),
    "sent": re.compile(r"Total bytes sent:\s*([\d,.]+)"),
    "received": re.compile(r"Total bytes received:\s*([\d,.]+)"),
    "deleted": re.compile(r"Number of deleted files:\s*([\d,.]+)"),
}

def _num(s: str) -> int:
    return int(re.sub(r"[^\d]", "", s) or 0)

# a program aht starts on Windows gets no console window of its own (an ssh
# run from the tray would flash one)
_NO_WINDOW = {"creationflags": 0x08000000} if os.name == "nt" else {}

WINDOWS_FAR = ("aht cannot ask a Windows machine yet. On the PC, use Bring Here, "
               "Pick Up or Leave a Note.")

def _decoded(r):
    """A finished run's output as text: bytes travel, UTF-8 is read here (a
    Windows console's code page would garble names)."""
    return subprocess.CompletedProcess(r.args, r.returncode,
                                       (r.stdout or b"").decode("utf-8", "replace"),
                                       (r.stderr or b"").decode("utf-8", "replace"))

# ---- a remote machine ------------------------------------------------------- #

class Remote:
    """One of the user's other machines.  `ssh` is the usual user@host; `root`
    (tests) makes a local directory stand in for the machine instead.  With
    `sandbox` (tests on a real machine) everything there happens inside that
    folder: its own home, aht, Claude store and tmux server, and the projects
    under it."""

    def __init__(self, name: str, spec: dict):
        self.name = name
        self.target = str(spec.get("ssh") or "")
        self.root = str(spec.get("root") or "").rstrip("/")
        self.sandbox = str(spec.get("sandbox") or "").rstrip("/") if self.target else ""
        self.system = spec.get("system")
        self.claude = spec.get("claude")
        self.info = {}
        self.on_percent = None          # called with rsync's percentage
        self._route = None              # (ssh target, host key alias) once known

    def route(self) -> tuple:
        """(user@address, alias): the name as given when it resolves; else the
        machine's Tailscale address, with its host key still checked under
        the name it is known by."""
        if self._route is None:
            self._route = (self.target, None)
            user, at, host = self.target.rpartition("@")
            try:
                g = subprocess.run(["ssh", "-G", host], capture_output=True, text=True,
                                   timeout=10, cwd="/", **_NO_WINDOW).stdout
                real = next((l.split(None, 1)[1] for l in g.splitlines()
                             if l.startswith("hostname ")), host)
            except Exception:
                real = host
            if host and not self.local and not _resolves(real):
                ip = tailscale_address(real) or tailscale_address(host)
                if ip:
                    self._route = (f"{user}@{ip}" if at else ip, host)
                    log(f"REMOTE {self.name}: {real} does not resolve; using its "
                        f"Tailscale address {ip}")
        return self._route

    @property
    def dest(self) -> str:
        return self.route()[0]

    def ssh_opts(self) -> list:
        alias = self.route()[1]
        return _ssh_opts() + (["-o", f"HostKeyAlias={alias}"] if alias else [])

    @property
    def local(self) -> bool:
        return bool(self.root) and not self.target

    def path(self, p: str) -> str:
        base = self.root if self.local else self.sandbox
        return base + p if base else p

    def spec(self, remote_abs: str) -> str:
        return remote_abs if self.local else f"{self.dest}:{remote_abs}"

    def _env(self) -> dict:
        e = {k: v for k, v in os.environ.items()
             if not k.startswith("AHT_") or k in ("AHT_CLAUDE", "AHT_ITERM_TABS")}
        e.update(_sandbox_env(self.root + "/home"))
        if os.name == "nt":
            e["USERPROFILE"] = e["HOME"]        # Windows' Path.home()
        if os.environ.get("AHT_REMOTE_PATH"):
            e["PATH"] = os.environ["AHT_REMOTE_PATH"] + os.pathsep + e.get("PATH", "")
        if os.environ.get("AHT_REMOTE_CLAUDE"):     # tests: another version there
            e["AHT_CLAUDE"] = os.environ["AHT_REMOTE_CLAUDE"]
        return e

    def _sandboxed(self, script: str) -> str:
        """`script` with the sandbox's variables set first, and its bin folder
        (stand-in agents) first on PATH.  Its tmux server's socket is inside
        it too (TMUX_TMPDIR), not in that machine's /tmp."""
        env = dict(_sandbox_env(self.sandbox + "/home"), TMUX_TMPDIR=self.sandbox + "/tmux")
        return ("export " + " ".join(f"{k}={shlex.quote(v)}" for k, v in env.items())
                + f" PATH={shlex.quote(self.sandbox + '/bin')}:\"$PATH\" && "
                + 'mkdir -p "$HOME" "$TMUX_TMPDIR" && ' + script)

    def sh(self, script: str, stdin=None, timeout: float = 120, raw: bool = False):
        """Run a sh script there.  `raw`: as it is, without the sandbox."""
        if self.system == "Windows" and not raw:
            raise HandoverError(WINDOWS_FAR)
        if isinstance(stdin, str):
            stdin = stdin.encode("utf-8")
        kw = {"input": stdin, "capture_output": True, "timeout": timeout, "cwd": "/",
              **_NO_WINDOW}
        try:
            if self.local:
                Path(self.root + "/home").mkdir(parents=True, exist_ok=True)
                r = subprocess.run(["/bin/sh", "-c", script], env=self._env(), **kw)
            else:
                if self.sandbox and not raw:
                    script = self._sandboxed(script)
                r = subprocess.run(["ssh"] + self.ssh_opts() + [self.dest, script], **kw)
        except subprocess.TimeoutExpired:
            raise LinkError(f"{self.name} did not answer within {timeout:.0f} s")
        r = _decoded(r)
        if r.returncode == 255:
            raise LinkError(f"cannot reach {self.name} ({self.target}): "
                            + ((r.stderr or "").strip().splitlines() or ["no answer"])[-1])
        return r

    def check_shell(self) -> None:
        """Before the first sh script to a machine: which shell answers there.
        `echo aht-os %OS% $env:OS` is harmless in sh, cmd.exe and PowerShell,
        and the two Windows shells name Windows_NT in it.  A Windows answer
        stops here, so nothing is made on a PC (cmd.exe would make folders
        named -p and $HOME)."""
        if self.local:
            return
        r = self.sh("echo aht-os %OS% $env:OS", timeout=60, raw=True)
        if "Windows_NT" in (r.stdout or ""):
            self.system = "Windows"
            raise HandoverError(WINDOWS_FAR)

    def push_agent(self) -> None:
        """The other side runs this very file, so both ends always agree.  It
        is named after its checksum and written under a name of its own
        first; the newest 3 stay, and the aht.py older versions used goes."""
        if self.local:
            return                          # a test machine runs the core itself
        cid, tmp = core_id(), f".aht-new-{os.urandom(4).hex()}"
        r = self.sh('d="$HOME/.aht/remote" && mkdir -p "$d" && chmod 700 "$d" && '
                    f'cat > "$d/{tmp}" && mv -f "$d/{tmp}" "$d/aht-{cid}.py" && '
                    'rm -f "$d/aht.py" "$d/aht.py.new" && cd "$d" && '
                    'ls -t aht-*.py | tail -n +4 | while read -r f; do rm -f "$f"; done',
                    stdin=_core_text())
        if r.returncode != 0:
            raise HandoverError(f"could not prepare {self.name}: "
                                + (r.stderr or "").strip()[-200:])

    def _run_local(self, data: bytes, timeout: float):
        """A test machine: the core itself with that machine's home, no sh."""
        Path(self.root + "/home").mkdir(parents=True, exist_ok=True)
        try:
            return _decoded(subprocess.run(_aht_argv() + ["_agent"], input=data,
                                           capture_output=True, timeout=timeout,
                                           cwd="/", env=self._env(), **_NO_WINDOW))
        except subprocess.TimeoutExpired:
            raise LinkError(f"{self.name} did not answer within {timeout:.0f} s")

    def agent(self, op: str, timeout: float = 120, **req) -> dict:
        """One operation there.  The copy of aht there is asked first; when it
        is not there yet ("can't open file"), it is sent and asked again."""
        req["op"] = op
        data = json.dumps(req).encode("utf-8")
        if self.local:
            r = self._run_local(data, timeout)
        else:
            line = f'exec python3 "$HOME/.aht/remote/aht-{core_id()}.py" _agent'
            r = self.sh(line, stdin=data, timeout=timeout)
            if r.returncode == 2 and "can't open file" in (r.stderr or ""):
                self.push_agent()
                r = self.sh(line, stdin=data, timeout=timeout)
        i = (r.stdout or "").rfind(AGENT_MARK)
        if i < 0:
            raise HandoverError(f"{self.name} gave no usable answer to “{op}”: "
                                + ((r.stderr or r.stdout or "").strip()[-300:]
                                   or "python3 missing?"))
        res = json.loads(r.stdout[i + len(AGENT_MARK):])
        _test_drop(op, self.name)
        if not res.get("ok"):
            raise HandoverError(f"{self.name}: {res.get('error') or op + ' failed'}")
        return res

    def connect(self, path: str = None) -> dict:
        self.info = self.agent("probe", path=self.path(path) if path else None,
                               claude=self.claude)
        return self.info

    def rsync(self, src: str, dst: str, *, delete: bool = False,
              backup_dir: str = None, skip=(), files_from: list = None,
              dry: bool = False, update: bool = False, include: list = None,
              progress: bool = False, add_only: bool = False, protect=()) -> dict:
        """One rsync run between this machine and the remote.  Paths ending in
        a slash are directories whose CONTENT is synced.  `add_only`: a file
        that is there already is never written.  `protect`: patterns of what
        a --delete never removes on the receiving side."""
        rs = find_rsync()
        if not rs:
            raise HandoverError("no usable rsync on this machine (version 3 or "
                                "newer is needed) — on macOS:  brew install rsync")
        cmd = [rs["path"], "-rlptD", "-s", "--timeout=120", "--stats",
               "--partial-dir=.aht-rsync-partial"]
        if cfg_get("handover_compress", True) and not self.local:
            cmd.append("-z")
        theirs = str(self.info.get("system") or "")
        if not self.local and theirs and IS_MAC != (theirs == "Darwin"):
            if not rs.get("iconv"):
                raise HandoverError(f"{rs['path']} cannot convert file names "
                                    "between macOS and Linux — brew install rsync")
            cmd.append("--iconv=utf-8-mac,utf-8" if IS_MAC else "--iconv=utf-8,utf-8-mac")
            if files_from is not None:
                # a list of names is read in THIS machine's form; rsync then
                # checks what arrives against it, after converting
                form = "NFD" if IS_MAC else "NFC"
                files_from = [unicodedata.normalize(form, f) for f in files_from]
                if rs["ver"] >= (3, 2, 5):  # Apple's NFD differs for rare characters
                    cmd.append("--trust-sender")
        if not self.local:
            cmd += ["-e", "ssh " + " ".join(shlex.quote(o) for o in self.ssh_opts())]
        if dry:
            cmd.append("-n")
        if update:
            cmd.append("--update")
        if add_only:
            cmd.append("--ignore-existing")
        if delete:
            cmd.append("--delete")
        if backup_dir:
            cmd += ["--backup", "--backup-dir=" + backup_dir]
        for pat in protect:
            cmd.append("--filter=P " + pat)
        for pat in include or []:
            cmd.append("--include=" + pat)
        if include:
            cmd.append("--exclude=*")
        for pat in skip:
            cmd.append("--exclude=" + pat)
        tmp = None
        if files_from is not None:
            import tempfile
            fd, tmp = tempfile.mkstemp(prefix="aht-files-")
            with os.fdopen(fd, "wb") as fh:
                fh.write(b"\0".join(f.encode("utf-8") for f in files_from) + b"\0")
            cmd += ["--from0", "--files-from=" + tmp]
        watch = (progress or self.on_percent) and not dry
        if watch:
            cmd.append("--info=progress2")
        cmd += [src, dst]
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                 stderr=None if progress else subprocess.PIPE,
                                 cwd="/")
            if watch:                       # follow it as it comes, keep it for the numbers
                got = []
                while True:
                    chunk = p.stdout.read1(4096)
                    if not chunk:
                        break
                    got.append(chunk)
                    done = re.findall(rb"(\d{1,3})%", chunk)
                    if done and self.on_percent:
                        self.on_percent(min(100, int(done[-1])))
                    if progress and b"Number of files" not in b"".join(got[-3:]):
                        sys.stderr.write(chunk.decode("utf-8", "replace"))
                        sys.stderr.flush()
                if progress:
                    sys.stderr.write("\n")
                text = b"".join(got)
                err = b"" if progress else (p.stderr.read() or b"")
                p.wait()
            else:
                text, err = p.communicate()
        finally:
            if tmp:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        text = text.decode("utf-8", "replace")
        res = {k: _num(m.group(1)) if (m := rx.search(text)) else 0
               for k, rx in _STAT_RE.items()}
        res["rc"] = p.returncode
        res["ok"] = p.returncode in (0, 24)     # 24: a file vanished meanwhile
        res["error"] = "" if res["ok"] else (
            (err or b"").decode("utf-8", "replace").strip()[-400:]
            or f"rsync exit {p.returncode}")
        return res

def remotes_config() -> dict:
    r = cfg_get("remotes") or {}
    return r if isinstance(r, dict) else {}

def get_remote(name: str = None) -> Remote:
    rs = remotes_config()
    if not rs:
        raise HandoverError("no other machine is set up yet — add one with:  "
                            "aht remote add <name> <user@host>")
    name = name or cfg_get("default_remote") or (next(iter(rs)) if len(rs) == 1 else None)
    if not name:
        raise HandoverError("several machines are set up; name one with --to "
                            f"({', '.join(sorted(rs))})")
    if name not in rs:
        raise HandoverError(f"unknown machine {name!r}; known: {', '.join(sorted(rs))}")
    return Remote(name, rs[name])

# ---- the agent side: operations the other machine runs for us --------------- #

def find_claude(hint: str = None, prefer_user: bool = False):
    if os.environ.get("AHT_CLAUDE"):            # tests: a stand-in CLI
        return os.environ["AHT_CLAUDE"]
    home = Path.home()
    user = [home / ".local/bin/claude"]
    rest = [shutil.which("claude"), "/opt/homebrew/bin/claude",
            home / ".npm-global/bin/claude", "/usr/local/bin/claude"]
    order = ([hint] if hint else []) + (user + rest if prefer_user else rest + user)
    for c in order:
        if c and os.path.exists(os.path.expanduser(str(c))):
            return os.path.expanduser(str(c))
    return None

def claude_version(exe: str):
    try:
        r = subprocess.run([exe, "--version"], capture_output=True, text=True,
                           timeout=30, cwd="/",
                           env={**os.environ, "DISABLE_AUTOUPDATER": "1"})
        m = re.search(r"(\d+\.\d+\.\d+)", r.stdout or "")
        return m.group(1) if m else None
    except Exception:
        return None

def _tmux(*args, timeout: float = 15):
    exe = shutil.which("tmux")
    if not exe:
        return None
    try:
        return subprocess.run([exe, *_tmux_socket(), *args], capture_output=True,
                              text=True, timeout=timeout, cwd="/")
    except Exception:
        return None

def _tmux_has(name: str) -> bool:
    r = _tmux("has-session", "-t", "=" + name)
    return bool(r) and r.returncode == 0

def _tmux_screen(name: str, lines: int = 14) -> list:
    r = _tmux("capture-pane", "-p", "-t", f"={name}:")      # a pane, not a session
    if not r or r.returncode != 0:
        return []
    return [l.rstrip() for l in r.stdout.splitlines() if l.strip()][-lines:]

def _quiet_value(fn):
    try:
        return fn()
    except Exception:
        return None

def _can_write(folder: str) -> bool:
    """Whether a file can be made in `folder`: tried, not asked, because macOS
    privacy rules can make os.access say yes and the write fail."""
    p = os.path.join(folder, f".aht-write-test-{os.getpid()}-{os.urandom(3).hex()}")
    try:
        with open(p, "x"):
            pass
    except OSError:
        return False
    try:
        os.unlink(p)
    except OSError:
        pass
    return True

def _agent_probe(req: dict) -> dict:
    path = req.get("path")
    exe = find_claude(req.get("claude"), prefer_user=True)
    info = {"ok": True, "host": platform.node().split(".")[0],
            "system": platform.system(), "home": str(Path.home()),
            "python": platform.python_version(), "version": VERSION,
            "claude_home": str(claude_home()), "claude": exe,
            "claude_version": claude_version(exe) if exe else None,
            "tools": {t: shutil.which(t) for t in
                      ("rsync", "byobu", "tmux", "mosh-server", "curl")},
            "packages": next((p for p in ("apt-get", "dnf", "pacman", "zypper", "brew")
                              if find_tool(p)), None),
            "firewall": "ufw" if find_tool("ufw") or os.path.exists("/usr/sbin/ufw")
            else None,
            "tailscale_if": os.path.exists("/sys/class/net/tailscale0"),
            "logged_in": (claude_home() / ".credentials.json").is_file()
            if not IS_MAC else None,     # macOS keeps the login in the keychain
            "sessions_open": len(running_sessions()),
            "protocol": AGENT_PROTOCOL, "ops": sorted(AGENT_OPS),
            "core_id": _quiet_value(core_id),
            "machine_id": machine_id(create=False)}
    if path:
        anc = Path(path)
        while not anc.exists() and anc != anc.parent:
            anc = anc.parent
        info["path_exists"] = os.path.isdir(path)
        info["path_base"] = str(anc)
        info["path_writable"] = _can_write(str(anc))
        try:
            info["path_open_to_others"] = bool(os.stat(path).st_mode & 0o077) \
                if os.path.isdir(path) else None
        except OSError:
            info["path_open_to_others"] = None
        info["path_real"] = os.path.realpath(path)
        try:
            info["free_bytes"] = shutil.disk_usage(str(anc)).free
        except OSError:
            pass
        info.update(activity_in(info["path_real"]) if info["path_exists"]
                    else {"sessions": [], "processes": []})
    return info

def _agent_manifest(req: dict) -> dict:
    out = {}
    for name, spec in (req.get("trees") or {}).items():
        out[name] = tree_manifest(spec["path"], spec.get("skip") or []) \
            if os.path.isdir(spec["path"]) else tree_manifest(os.devnull, [])
    return {"ok": True, "trees": out}

def _agent_hash(req: dict) -> dict:
    out = {}
    for f in req.get("files") or []:
        try:
            out[f["key"]] = file_sha256(f["path"], f.get("limit"))
        except OSError:
            out[f["key"]] = None
    return {"ok": True, "hashes": out}

def _agent_written_by(req: dict) -> dict:
    """The newest agent CLI version that wrote into each transcript, from
    `offset` on — the part that was added on this machine."""
    out = {}
    for f in req.get("files") or []:
        best = None
        try:
            with open(f["path"], "rb") as fh:
                fh.seek(int(f.get("offset") or 0))
                for line in fh:
                    if b'"version"' not in line:
                        continue
                    try:
                        v = json.loads(line).get("version")
                        v = tuple(int(x) for x in str(v).split("."))
                    except Exception:
                        continue
                    if len(v) == 3 and (best is None or v > best):
                        best = v
        except OSError:
            pass
        out[f["key"]] = ".".join(map(str, best)) if best else None
    return {"ok": True, "versions": out}

UDP_PROBE_PORTS = (60999, 60998)        # inside the range mosh uses

def _agent_udp_echo(req: dict) -> dict:
    """Answer one datagram: tells the caller whether mosh's UDP gets through."""
    import socket
    for port in UDP_PROBE_PORTS:
        s = socket.socket(socket.AF_INET6 if req.get("v6") else socket.AF_INET,
                          socket.SOCK_DGRAM)
        try:
            s.bind(("", port))
        except OSError:
            s.close()
            continue
        s.settimeout(float(req.get("wait") or 6))
        try:
            data, peer = s.recvfrom(64)
            if data == b"aht-ping":
                s.sendto(b"aht-pong", peer)
                return {"ok": True, "heard": True, "port": port}
        except OSError:
            pass
        finally:
            s.close()
        return {"ok": True, "heard": False, "port": port}
    return {"ok": True, "heard": False, "port": None}

def _agent_prepare(req: dict) -> dict:
    """Folders the sync writes into; and, when the two homes differ, the other
    machine's ~/.claude path made to resolve here, since the history names it."""
    notes = []
    for d in req.get("dirs") or []:
        os.makedirs(d, exist_ok=True)
    their = req.get("their_home")
    mine = str(Path.home())
    if their and os.path.realpath(their) != os.path.realpath(mine):
        link = Path(their) / ".claude"
        if Path(their).is_dir() and not link.exists() and not link.is_symlink() \
                and os.access(their, os.W_OK):
            try:
                os.symlink(str(claude_home()), str(link))
                notes.append(f"{link} now points at {claude_home()}")
            except OSError as e:
                notes.append(f"could not link {link}: {e}")
    return {"ok": True, "notes": notes}

def _claude_json() -> Path:
    return claude_home().parent / ".claude.json"

def _agent_trust(req: dict) -> dict:
    """The user already trusted this very folder on the machine it comes
    from; recorded here only while no agent CLI could overwrite the file."""
    cj = _claude_json()
    if not cj.is_file():
        return {"ok": True, "trust": "not set: the agent CLI was never set up here"}
    if running_sessions():
        return {"ok": True, "trust": "not set: an agent session is open here"}
    try:
        data = json.loads(cj.read_text())
        ent = data.setdefault("projects", {}).setdefault(req["path"], {})
    except Exception as e:
        return {"ok": True, "trust": f"not set: {cj.name} is unreadable ({e})"}
    if ent.get("hasTrustDialogAccepted"):
        return {"ok": True, "trust": "already trusted"}
    ent["hasTrustDialogAccepted"] = True
    shutil.copy2(cj, str(cj) + ".bak-aht")
    tmp = cj.with_name(cj.name + ".aht-new")
    with open(tmp, "w") as fh:
        json.dump(data, fh, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, cj)
    return {"ok": True, "trust": "carried over"}

def _agent_install_claude(req: dict) -> dict:
    ver = str(req.get("version") or "")
    if not re.fullmatch(r"\d+\.\d+\.\d+", ver):
        return {"ok": False, "error": f"not a version: {ver!r}"}
    r = subprocess.run(["/bin/sh", "-c",
                        f"curl -fsSL https://claude.ai/install.sh | bash -s {ver}"],
                       capture_output=True, text=True, timeout=900)
    exe = find_claude(None, prefer_user=True)
    got = claude_version(exe) if exe else None
    if got != ver:
        return {"ok": False, "error": f"installing Claude Code {ver} failed "
                f"(found {got}): {(r.stderr or r.stdout).strip()[-300:]}"}
    return {"ok": True, "claude": exe, "claude_version": got}

def _agent_start(req: dict) -> dict:
    path, name = req["path"], req["name"]
    # a tmux server of its own (a sandbox) is plain tmux: byobu picks its own
    mux = (None if _tmux_socket() else shutil.which("byobu")) or shutil.which("tmux")
    if not shutil.which("tmux"):
        return {"ok": False, "error": "tmux is not installed (byobu needs it too)"}
    if running_sessions(inside=path):
        return {"ok": False, "error": "an agent session is already open there"}
    if _tmux_has(name):
        _tmux("kill-session", "-t", "=" + name)
    run = aht_home() / "remote" / "run" / name
    run.mkdir(parents=True, exist_ok=True)
    (run / "note.txt").write_text(req.get("note") or "")
    (run / "settings.json").write_text(json.dumps({"hooks": {"SessionStart": [
        {"hooks": [{"type": "command", "timeout": 5,
                    "command": "cat " + shlex.quote(str(run / "note.txt"))}]}]}}))
    argv = [req["claude"]]
    if req.get("session"):
        argv += ["--resume", req["session"]]
    argv += ["--settings", str(run / "settings.json")]
    argv += [str(a) for a in req.get("args") or []]
    if req.get("remote_control"):
        argv += ["--remote-control", req["remote_control"]]
    if req.get("task"):
        argv += ["--", req["task"]]           # the first prompt: work starts at once
    line = ("cd %s && env DISABLE_AUTOUPDATER=1 %s; st=$?; cd /; "
            "printf '\\n[aht] the agent exited (%%s); this window closes in a minute\\n' "
            "\"$st\"; sleep 60"
            % (shlex.quote(path), " ".join(shlex.quote(a) for a in argv)))
    (run / "command.txt").write_text(line + "\n")
    new = _tmux_socket() + ["new-session", "-d", "-s", name, "-x", "200", "-y", "50",
                            "-c", path, line]
    r = subprocess.run([mux] + new, capture_output=True, text=True, timeout=60)
    if r.returncode != 0 and os.path.basename(mux) == "byobu":
        mux = shutil.which("tmux")
        r = subprocess.run([mux] + new, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        return {"ok": False, "error": "could not start the terminal session: "
                + (r.stderr or r.stdout).strip()[-200:]}
    # the trace of this attempt's start, for resolve_handing: the session
    # may end before anyone asks whether it started
    for old in run.glob("attempt-*"):
        try:
            old.unlink()
        except OSError:
            pass
    if re.fullmatch(r"[0-9A-Za-z-]{1,40}", str(req.get("attempt") or "")):
        (run / f"attempt-{req['attempt']}").write_text(_now() + "\n")
    started, attention, screen = False, None, []
    end = time.time() + float(req.get("wait") or 12)
    while time.time() < end:
        time.sleep(1.0)
        screen = _tmux_screen(name)
        text = " ".join(screen).lower()
        if running_sessions(inside=path):
            started = True
        if "trust this folder" in text or "trust the files" in text:
            attention = "it asks whether you trust the folder"
            break
        if "the agent exited" in text:
            attention = "the agent exited right away"
            break
        if started:
            break
    return {"ok": True, "mux": os.path.basename(mux), "name": name,
            "started": started, "attention": attention, "screen": screen}

def _agent_stop(req: dict) -> dict:
    """End an IDLE session the way its user would: Ctrl-C, never text typed
    into the prompt — so a half-written message can not be sent by accident.
    A working session is left alone."""
    path, name = req["path"], req["name"]
    end = time.time() + float(req.get("wait") or 30)
    pressed = 0
    while True:
        sess = running_sessions(inside=path)
        if not sess:
            break
        busy = [s for s in sess if s.get("status") != "idle"]
        if busy:
            return {"ok": True, "stopped": False, "reason": "working", "sessions": sess}
        if not _tmux_has(name):
            return {"ok": True, "stopped": False, "reason": "not-ours", "sessions": sess}
        if time.time() >= end or pressed >= 4:
            return {"ok": True, "stopped": False, "reason": "no-reaction", "sessions": sess}
        # the CLI exits on a second Ctrl-C that follows the first at once
        _tmux("send-keys", "-t", f"={name}:", "C-c")
        time.sleep(0.4)
        _tmux("send-keys", "-t", f"={name}:", "C-c")
        pressed += 1
        time.sleep(2.5)
    if _tmux_has(name):
        _tmux("kill-session", "-t", "=" + name)
    return {"ok": True, "stopped": True}

def _agent_close(req: dict) -> dict:
    """Close the window a handover opened, once no session is left in it."""
    if running_sessions(inside=req["path"]):
        return {"ok": True, "closed": False}
    had = _tmux_has(req["name"])
    if had:
        _tmux("kill-session", "-t", "=" + req["name"])
        time.sleep(0.5)
    return {"ok": True, "closed": had}

def _agent_peek(req: dict) -> dict:
    path, name = req["path"], req.get("name") or ""
    act = activity_in(path) if os.path.isdir(path) else {"sessions": [], "processes": []}
    return {"ok": True, "window": bool(name) and _tmux_has(name),
            "screen": _tmux_screen(name) if name else [], **act}

ASIDE_KEEP, ASIDE_DAYS = 5, 30      # set-aside folders: the newest 5, and every
                                    # one younger than 30 days

def _stamp_time(name: str, path=None):
    """When a folder named by _stamp() was made; else its mtime."""
    m = re.match(r"(\d{8}-\d{6})", name)
    if m:
        try:
            return time.mktime(time.strptime(m.group(1), "%Y%m%d-%H%M%S"))
        except ValueError:
            pass
    try:
        return os.stat(path).st_mtime if path else None
    except OSError:
        return None

def prune_set_asides(base, keep: int = ASIDE_KEEP, days: float = ASIDE_DAYS) -> int:
    """Drop what earlier transfers set aside in `base`, keeping the newest
    `keep` folders and every one younger than `days` days."""
    base = Path(base)
    if not base.is_dir():
        return 0
    rows = sorted((_stamp_time(d.name, d) or 0, d.name) for d in base.iterdir() if d.is_dir())
    old, n = time.time() - days * 86400, 0
    for t, name in rows[:-keep] if keep > 0 else rows:
        if t < old:
            shutil.rmtree(base / name, ignore_errors=True)
            n += 1
    return n

def _agent_prune(req: dict) -> dict:
    """Drop what earlier syncs set aside: see prune_set_asides."""
    return {"ok": True, "pruned": prune_set_asides(req["dir"],
                                                   int(req.get("keep") or ASIDE_KEEP))}

AGENT_OPS = {"probe": _agent_probe, "manifest": _agent_manifest,
             "hash": _agent_hash, "prepare": _agent_prepare,
             "trust": _agent_trust, "install-claude": _agent_install_claude,
             "start": _agent_start, "stop": _agent_stop, "peek": _agent_peek,
             "close": _agent_close, "written-by": _agent_written_by,
             "board": lambda req: _agent_board(req),
             "udp-echo": _agent_udp_echo,
             "prune": _agent_prune,
             "offsite-list": lambda req: _agent_offsite_list(req),
             "offsite-prune": lambda req: _agent_offsite_prune(req),
             "offsite-adopt": lambda req: _agent_offsite_adopt(req)}

def cmd_core(args):
    """`aht _core --id`: the id of the core this build carries (the name of
    its copy on other machines)."""
    try:
        print(core_id())
    except HandoverError as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0

def cmd_agent(args):
    try:
        req = json.loads(sys.stdin.read() or "{}")
        fn = AGENT_OPS.get(req.get("op"))
        res = fn(req) if fn else {"ok": False,
                                  "error": f"unknown operation {req.get('op')!r}"}
    except Exception as e:
        res = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        error(f"AGENT {e}")
    sys.stdout.write("\n" + AGENT_MARK + json.dumps(res) + "\n")
    return 0

# ---- what a session knew: carried in a readable form ------------------------ #

def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text") or "" for b in content or []
                     if isinstance(b, dict) and b.get("type") == "text")

def _clip(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[:n].rstrip() + " […]"

def _count_exchange(d: dict, text: str, t) -> None:
    """A digest's tally of the exchanges it read: how many, when the first
    and the last were, and each request's start (for one line each)."""
    d["count"] += 1
    d["first_t"] = d["first_t"] or t
    d["last_t"] = t or d["last_t"]
    d["requests"].append({"t": t, "text": text[:2000]})
    del d["requests"][:-50]

def _rel_to(path: str, root: str) -> str:
    """`path` (inside `root`) relative to it, spelt as the system that wrote
    it spells it: C:\\p\\src\\a.py in C:\\p is src\\a.py, on any system."""
    if _DRIVE.match(str(root)) or str(root).startswith("\\\\"):
        return str(path)[len(str(root).rstrip("/\\")):].lstrip("/\\") or "."
    return os.path.relpath(path, root)

def session_digest(jsonl, project: str, turns: int = 8, tail: int = None,
                   since: float = None) -> dict:
    """The state of one session, read from its transcript: title, the last
    compaction summary, the latest exchanges (each with its time), open
    to-dos, files it touched and the paths OUTSIDE the project it used.
    `tail`: read only the last that many bytes (quick, for a glance at where
    it stopped).  `since`: only the exchanges and files after that time; the
    to-dos as they stand at the end."""
    d = {"title": None, "summary": None, "exchanges": [], "todos": [],
         "touched": [], "outside": [], "version": None, "count": 0, "requests": [],
         "first_t": None, "last_t": None}
    cur = None
    tasks = {}                  # the task list tools (TaskCreate / TaskUpdate)
    home = str(Path.home())
    noise = (home + "/.claude", home + "/.aht", "/tmp/", "/private/", "/var/",
             "/dev/", "/proc/", "/usr/", "/opt/", "/System/", "/Library/", "/etc/",
             "/bin/", "/sbin/")
    try:
        fh = open(jsonl, "rb")
    except OSError:
        return d
    with fh:
        if tail:
            size = fh.seek(0, 2)
            fh.seek(max(0, size - tail))
            if size > tail:
                fh.readline()                   # a line cut in half
        for line in fh:
            try:
                e = json.loads(line)
            except Exception:
                continue
            if not isinstance(e, dict):
                continue
            t = e.get("type")
            if t in ("ai-title", "custom-title"):
                d["title"] = e.get("aiTitle") or e.get("customTitle") or d["title"]
            if e.get("version"):
                d["version"] = e["version"]
            m = e.get("message")
            if e.get("isSidechain") or not isinstance(m, dict):
                continue
            c = m.get("content")
            ts = _when(e.get("timestamp"))
            new = not since or (ts or 0) >= since
            if t == "user":
                if e.get("isCompactSummary"):
                    d["summary"], cur = _text_of(c), None
                    if not since:
                        d["exchanges"] = []
                    continue
                tur = e.get("toolUseResult")
                if isinstance(tur, dict) and isinstance(tur.get("task"), dict) \
                        and tur["task"].get("id") and tur["task"].get("subject"):
                    tasks[str(tur["task"]["id"])] = {"content": tur["task"]["subject"],
                                                     "status": "pending"}
                if e.get("isMeta") or tur is not None:
                    continue
                if isinstance(c, list) and any(isinstance(b, dict) and
                                               b.get("type") == "tool_result" for b in c):
                    continue
                txt = _text_of(c).strip()
                if not txt or txt.startswith("<"):      # reminders, notifications
                    continue
                cur = None
                if not new:
                    continue
                cur = {"you": txt, "agent": "", "t": ts}
                d["exchanges"].append(cur)
                del d["exchanges"][:-turns]
                _count_exchange(d, txt, ts)
            elif t == "assistant":
                txt = _text_of(c).strip()
                if txt and cur is None and tail and not since:  # its prompt lies before the tail
                    cur = {"you": "", "agent": "", "t": ts}
                    d["exchanges"].append(cur)
                if txt and cur is not None:
                    cur["agent"] = txt                  # a turn's last text wins
                    d["last_t"] = ts or d["last_t"]
                for b in c if isinstance(c, list) else []:
                    if not (isinstance(b, dict) and b.get("type") == "tool_use"):
                        continue
                    inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                    if b.get("name") == "TodoWrite" and isinstance(inp.get("todos"), list):
                        d["todos"] = inp["todos"]
                    elif b.get("name") == "TaskUpdate" and str(inp.get("taskId")) in tasks:
                        if inp.get("status"):
                            tasks[str(inp["taskId"])]["status"] = inp["status"]
                    fp = inp.get("file_path") or inp.get("notebook_path") or inp.get("path")
                    if not (isinstance(fp, str) and _is_abs(fp)) or not new:
                        continue
                    if _inside(fp, project):
                        if b.get("name") in ("Write", "Edit", "NotebookEdit"):
                            rel = _rel_to(fp, project)
                            if rel in d["touched"]:
                                d["touched"].remove(rel)
                            d["touched"].append(rel)
                    elif not fp.startswith(noise):
                        if fp in d["outside"]:
                            d["outside"].remove(fp)
                        d["outside"].append(fp)
    d["touched"] = d["touched"][-15:]
    d["outside"] = d["outside"][-15:]
    d["todos"] = [x for x in d["todos"] + list(tasks.values()) if isinstance(x, dict)
                  and x.get("status") not in ("completed", "deleted")]
    d["title"] = redact(str(d["title"])) if d["title"] else None     # it is shown and sent
    return d

RELAYS_KEEP = 12        # closed relays kept in a project's .aht/handover

def prune_relays(d) -> int:
    """One prune for a project's .aht/handover, whatever wrote there last:
    every open relay stays, and the newest RELAYS_KEEP closed ones.  A
    hand-back and a Summary Only open nothing, so they count as closed; so
    does a summary from before relays (`*-to-*.md`, a handover's or a
    switch's)."""
    d = Path(d)
    closed = []                     # (name to sort by, files that make it up)
    try:
        for f in d.glob("relay-*.json"):
            rid = f.name[len("relay-"):-len(".json")]
            done = (d / f"relay-{rid}.closed").is_file()
            if not done:
                try:
                    rec = json.loads(f.read_text(encoding="utf-8"))
                    done = rec.get("kind") == "back" or (rec.get("to") or {}).get("mode") \
                        == "brief-only"
                except (OSError, ValueError, AttributeError):
                    done = False
            if done:
                closed.append((rid, [d / f"relay-{rid}{x}"
                                     for x in (".json", ".md", ".closed", ".told")]))
        closed += [(f.name, [f]) for f in d.glob("*-to-*.md")]
    except OSError:
        return 0
    n = 0
    for _name, files in sorted(closed)[:-RELAYS_KEEP]:
        for f in files:
            try:
                f.unlink()
            except OSError:
                pass
        n += 1
    return n

def scratch_dir(real: str, sid: str):
    """Where the agent CLI keeps a session's own scratch files."""
    for tmp in ("/private/tmp", "/tmp"):
        p = Path(tmp) / f"claude-{getattr(os, 'getuid', lambda: 0)()}" / _key_claude(real) / sid / "scratchpad"
        if p.is_dir():
            return p
    return None

def write_brief(real: str, sid, dig: dict, here: str, there: str,
                there_system: str, carried: list, scratch: bool, task: str = None) -> tuple:
    """The readable summary that travels inside the project, and the short
    note the resumed session is told on arrival.  -> (file, note)"""
    out = Path(real) / ".aht" / "handover"
    out.mkdir(parents=True, exist_ok=True)
    # excerpts of a conversation must never end up in the project's repository
    (out / ".gitignore").write_text("*\n")
    when = time.strftime("%Y-%m-%d %H:%M")
    name = f"{time.strftime('%Y%m%d-%H%M')}-to-{there}.md"
    system = {"Darwin": "macOS", "Linux": "Linux"}
    mine = system.get(platform.system(), platform.system())
    theirs = system.get(there_system, there_system or "?")
    L = [f"# Handover: {os.path.basename(real)}", "",
         f"- From **{here}** ({mine}) to **{there}** ({theirs}), {when}",
         f"- Folder: `{real}` (the same path on both machines)"]
    if sid:
        L.append(f"- Session: {redact(dig.get('title') or 'untitled')} — `{sid}`"
                 + (f", Claude Code {dig['version']}" if dig.get("version") else ""))
        L.append(f"- Continue it with: `claude --resume {sid}`")
    if task:
        L += ["", "## The task it was given on arrival", "", task.strip()]
    L += _brief_sections(dig)
    missing = [p for p in dig.get("outside") or []
               if not any(_inside(p, c) for c in carried)]
    L += ["", "## What did not come along", "",
          "- Running processes: servers, builds, background shells.",
          "- Temporary files (`/tmp`, `/private/tmp`)."
          + (f" This session's scratch folder was copied to "
             f"`.aht/handover/scratch/{sid}/`." if scratch else ""),
          "- Folders that are rebuilt per machine: `node_modules`, `.venv`, "
          "`__pycache__` and the like."]
    if missing:
        L += ["- Files outside the project that this session used:"]
        L += [f"  - `{p}`" for p in missing]
    if carried:
        L += ["", "## Carried along besides the project", ""]
        L += [f"- `{p}`" for p in carried]
    (out / name).write_text("\n".join(L) + "\n", encoding="utf-8")
    prune_relays(out)
    note = [f"[aht] This session was handed over from “{here}” ({mine}) to "
            f"“{there}” ({theirs}) on {when}. The project folder and this "
            f"conversation's history came along; the folder's path is unchanged.",
            "Not carried: running processes, temporary files (/tmp, /private/tmp)"
            + (f" — a copy of this session's scratch folder is at "
               f".aht/handover/scratch/{sid}/" if scratch else "")
            + ", and folders rebuilt per machine (node_modules, .venv, …)."]
    if missing:
        note.append("Files outside the project that were used here and are NOT "
                    "on this machine: " + ", ".join(missing[:8])
                    + (" …" if len(missing) > 8 else "") + ".")
    if mine != theirs:
        note.append(f"Tools that exist only on {mine} are not available here.")
    note.append(f"A readable summary of where things stood: .aht/handover/{name}")
    if task:
        note.append("The user's next message is the task to work on now; the user may "
                    "be away and answers from the Claude app on the phone.")
    return out / name, "\n".join(note) + "\n"

# ---- registry bookkeeping ---------------------------------------------------- #

def _entry_for(reg: dict, real: str):
    """The registry entry of the folder at `real`.  A path can be listed
    twice (a folder that was removed and made anew): the entry the folder's
    own marker names is the one that counts."""
    mark = read_marker(real) if os.path.isdir(real) else None
    e = reg.get("projects", {}).get(mark) if mark else None
    if e is not None and os.path.realpath(e.get("real_path") or "") == real:
        return mark, e
    for uid, e in reg.get("projects", {}).items():
        if os.path.realpath(e.get("real_path") or "") == real:
            return uid, e
    return None, None

def _update_entry(uid: str, **fields) -> None:
    """Set (or, with None, drop) keys of one registry entry."""
    with Lock():
        reg = load_registry()
        e = reg["projects"].get(uid)
        if e is None:
            return
        for k, v in fields.items():
            if v is None:
                e.pop(k, None)
            else:
                e[k] = v
        save_registry(reg)

class Progress:
    """Where a transfer stands, for a front-end that shows it: the stage in
    words and the percentage rsync reports, rewritten into one small file."""
    def __init__(self, path=None, talk=False):
        self.path, self.talk = path, talk
        self.stage, self.pct, self.at = "", None, 0.0
    def say(self, msg: str) -> None:
        self.stage, self.pct = msg, None
        if self.talk:
            print(msg, flush=True)
        self._write(force=True)
    def percent(self, n: int) -> None:
        if n != self.pct:
            self.pct = n
            self._write()
    def _write(self, force=False) -> None:
        if not self.path or (not force and time.time() - self.at < 0.3):
            return
        self.at = time.time()
        try:
            tmp = str(self.path) + ".new"
            with open(tmp, "w") as fh:
                json.dump({"stage": self.stage, "percent": self.pct, "at": self.at}, fh)
            os.replace(tmp, self.path)
        except OSError:
            pass

class ProjectLock:
    """One transfer per project at a time (a mirror run and a handover)."""
    def __init__(self, uid: str):
        self.p = handover_dir(uid) / ".lock"
        self.fh = None
    def __enter__(self):
        self.p.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(self.p, "w")
        try:
            fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.fh.close()
            self.fh = None
            raise HandoverError("another transfer of this project is running")
        return self
    def __exit__(self, *a):
        if self.fh:
            try:
                fcntl.flock(self.fh, fcntl.LOCK_UN)
                self.fh.close()
            except Exception:
                pass

def _mux_name(real: str, uid: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", os.path.basename(real).lower()).strip("-")
    return f"aht-{slug[:20].strip('-') or 'project'}-{uid[:6]}"

def _here() -> str:
    if os.environ.get("AHT_MACHINE_NAME"):          # demos and tests
        return os.environ["AHT_MACHINE_NAME"]
    return platform.node().split(".")[0] or "this machine"

def find_tool(name: str):
    """A program by name — also where package managers put it, since a tray
    or a LaunchAgent runs with the system's bare PATH."""
    for c in (shutil.which(name), f"/opt/homebrew/bin/{name}",
              f"/usr/local/bin/{name}", str(Path.home() / ".local/bin" / name)):
        if c and os.path.exists(c):
            return c
    return None

def udp_reaches(rem: Remote) -> bool:
    """Does a datagram get to the machine and back?  mosh needs that; a
    firewall there often says no."""
    import socket, threading
    if rem.local:
        return False
    host = rem.dest.split("@")[-1]
    got = {}
    t = threading.Thread(target=lambda: got.update(
        _quiet(lambda: rem.agent("udp-echo", timeout=30, wait=6))), daemon=True)
    t.start()
    ok = False
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.4)
        end = time.time() + 7
        while time.time() < end and not ok:
            for port in UDP_PROBE_PORTS:
                try:
                    s.sendto(b"aht-ping", (host, port))
                except OSError:
                    continue
            try:
                ok = s.recvfrom(64)[0] == b"aht-pong"
            except OSError:
                pass
        s.close()
    except OSError:
        pass
    t.join(timeout=10)
    return ok

def _quiet(fn) -> dict:
    try:
        return fn() or {}
    except Exception:
        return {}

def mosh_usable(rem: Remote, test: bool = False) -> bool:
    """mosh on both sides AND its UDP path open — tested once per machine and
    remembered (`aht remote check` tests again)."""
    if rem.local or not cfg_get("handover_mosh", True) or not find_tool("mosh") \
            or not (rem.info.get("tools") or {}).get("mosh-server"):
        return False
    spec = remotes_config().get(rem.name) or {}
    if test or "udp" not in spec:
        ok = udp_reaches(rem)
        with Lock():
            cfg = load_config()
            rs = dict(cfg.get("remotes") or {})
            if rem.name in rs:
                rs[rem.name] = dict(rs[rem.name], udp=ok)
                cfg["remotes"] = rs
                save_config(cfg)
        return ok
    return bool(spec.get("udp"))

def attach_command(rem: Remote, mux: str, name: str) -> list:
    # a test machine or a sandbox has a tmux server of its own
    sock = ["-L", _sandbox_env("")["AHT_TMUX_SOCKET"]] if rem.local or rem.sandbox else []
    inner = [mux or "tmux", *sock, "attach", "-t", name]
    if rem.sandbox:                     # whose socket is inside the sandbox
        inner = ["env", "TMUX_TMPDIR=" + shlex.quote(rem.sandbox + "/tmux")] + inner
    if rem.local:
        return inner
    if mosh_usable(rem):
        alias = rem.route()[1]
        via = [f"--ssh=ssh -o HostKeyAlias={alias}"] if alias else []
        return [find_tool("mosh")] + via + [rem.dest, "--"] + inner   # survives network changes
    alias = rem.route()[1]
    return ["ssh", "-t"] + (["-o", f"HostKeyAlias={alias}"] if alias else []) + [rem.dest] + inner

# ---- pushing a project over -------------------------------------------------- #

def _store_of(real: str):
    hit = claude_backend().find(real)
    return hit[1] if hit else None

def _sessions_of(store) -> list:
    """Session ids of a store, newest first."""
    if not store:
        return []
    fs = [f for f in Path(store).glob("*.jsonl") if f.is_file()]
    return [f.stem for f in sorted(fs, key=lambda f: (f.stat().st_mtime, f.name),
                                   reverse=True)]

_ENTRY_RE = re.compile(rb'"entrypoint"\s*:\s*"([^"\\]{1,40})"')

def _is_scripted(jsonl) -> bool:
    """A session only `claude -p` or the Agent SDK ever wrote (entrypoint
    "sdk-…", never "cli"), or one that began with /loop — the ones Claude
    Code's own --continue passes over."""
    try:
        size = os.path.getsize(jsonl)
        with open(jsonl, "rb") as fh:
            head = fh.read(1 << 18)
            if size > (1 << 19):
                fh.seek(size - (1 << 18))
            tail = fh.read(1 << 18)
    except OSError:
        return False
    for line in head.split(b"\n"):
        if b'"type":"user"' not in line.replace(b" ", b""):
            continue
        try:
            e = json.loads(line)
        except Exception:
            continue
        if e.get("isMeta") or not isinstance(e.get("message"), dict):
            continue
        if _text_of(e["message"].get("content")).lstrip().startswith("/loop"):
            return True
        break
    kinds = {k.decode("utf-8", "replace") for k in _ENTRY_RE.findall(head + tail)}
    return bool(kinds) and all(k.startswith("sdk") for k in kinds)

def latest_session(store):
    """The session to go on with: the one written to last, as `claude
    --continue` would pick it.  Scripted runs only count when nothing else
    is there."""
    ids = _sessions_of(store)
    for s in ids:
        if not _is_scripted(Path(store) / f"{s}.jsonl"):
            return s
    return ids[0] if ids else None

def session_title(store, sid) -> str:
    if not (store and sid):
        return ""
    return session_digest(Path(store) / f"{sid}.jsonl", "/", turns=1).get("title") or ""

_SLUG_RE = re.compile(rb'"slug"\s*:\s*"([A-Za-z0-9._-]{1,120})"')

def _plans_of(store) -> list:
    """rsync patterns for the plan files this project's sessions wrote."""
    slugs = set()
    for f in Path(store).glob("*.jsonl") if store else []:
        try:
            with open(f, "rb") as fh:
                for line in fh:
                    if b'"slug"' in line:
                        slugs.update(m.decode() for m in _SLUG_RE.findall(line))
        except OSError:
            continue
    return [f"/{s}.md" for s in sorted(slugs)]

def _extras(entry: dict) -> list:
    return [p for p in (entry.get("extras") or []) if os.path.exists(p)]

def _check_extra(p: str) -> str:
    """'' if `p` may travel next to a project, else why not."""
    real = os.path.realpath(os.path.expanduser(p))
    home = os.path.realpath(str(Path.home()))
    if not os.path.exists(real):
        return "does not exist"
    if not _inside(real, home) or real == home:
        return "only files and folders inside your home folder can travel"
    for bad in (".claude", ".aht", ".ssh", ".gnupg", ".config", "Library"):
        if _inside(real, os.path.join(home, bad)):
            return f"~/{bad} holds this machine's own settings and keys"
    return ""

RELAYS_REL = "/.aht/handover/"     # a project's relays: notes left there stay there

def push_project(rem: Remote, uid: str, entry: dict, *, progress: bool = False,
                 dry: bool = False, sync: bool = False) -> dict:
    """Make the remote copy of a project and of its history equal to what is
    here.  What the sync replaces or removes over there is set aside first.
    The project's .aht/handover is never removed there: a handover sends
    what is here into it, and Keep in sync (`sync`) leaves it out."""
    real = os.path.realpath(entry["real_path"])
    rpath = rem.path(real)
    rhome, rclaude = rem.info["home"], rem.info["claude_home"]
    aside = f"{rhome}/.aht/remote/replaced/{uid}/{_stamp()}"
    res = {"project": {}, "history": {}, "extras": [], "aside": aside}
    store = _store_of(real)
    sids = _sessions_of(store)
    if not dry:
        rem.agent("prepare", dirs=[rpath, f"{rclaude}/projects", f"{rclaude}/file-history",
                                   f"{rclaude}/plans", os.path.dirname(aside)],
                  their_home=rem.path(str(Path.home())))
    res["project"] = rem.rsync(real + "/", rem.spec(rpath + "/"), delete=True,
                               backup_dir=aside + "/project",
                               skip=handover_skip() + ([RELAYS_REL] if sync else []),
                               protect=() if sync else (RELAYS_REL + "***",),
                               dry=dry, progress=progress)
    if not res["project"]["ok"]:
        raise HandoverError("sending the project failed: " + res["project"]["error"])
    if store:
        rkey = _key_claude(rpath)
        res["history"] = rem.rsync(str(store) + "/",
                                   rem.spec(f"{rclaude}/projects/{rkey}/"),
                                   backup_dir=aside + "/history", dry=dry)
        if not res["history"]["ok"]:
            raise HandoverError("sending the history failed: " + res["history"]["error"])
        side = [(claude_home() / "file-history", "file-history",
                 [f"/{s}/***" for s in sids
                  if (claude_home() / "file-history" / s).is_dir()]),
                (claude_home() / "plans", "plans",
                 _plans_of(store) if (claude_home() / "plans").is_dir() else [])]
        for src, sub, inc in side:
            if inc:
                r = rem.rsync(str(src) + "/", rem.spec(f"{rclaude}/{sub}/"),
                              include=inc, backup_dir=f"{aside}/{sub}", dry=dry)
                res["history"]["bytes"] = res["history"].get("bytes", 0) + r.get("bytes", 0)
    for p in _extras(entry):
        isdir = os.path.isdir(p)
        if not dry:
            rem.agent("prepare", dirs=[rem.path(p) if isdir
                                       else os.path.dirname(rem.path(p))])
        r = rem.rsync(p + ("/" if isdir else ""), rem.spec(rem.path(p) + ("/" if isdir else "")),
                      backup_dir=aside + "/extras", skip=handover_skip(),
                      dry=dry, progress=progress)
        res["extras"].append({"path": p, **r})
    if not dry:
        try:
            rem.agent("prune", dir=os.path.dirname(aside), keep=ASIDE_KEEP)
        except HandoverError:
            pass
    return res

# ---- mirror ------------------------------------------------------------------ #

def mirror_due(entry: dict, now: float = None) -> bool:
    m = entry.get("mirror") or {}
    if not m.get("enabled") or m.get("paused") or entry.get("away") or entry.get("handing"):
        return False
    try:
        every = float(cfg_get("mirror_interval_minutes", 30)) * 60
    except Exception:
        every = 1800.0
    last = max(float(m.get("synced_at") or 0), float(m.get("tried_at") or 0))
    return (now or time.time()) - last >= every

def _update_mirror(uid: str, **fields) -> None:
    """Set fields of a project's Keep in sync record as the registry has it
    now: a Release may have paused it meanwhile."""
    with Lock():
        reg = load_registry()
        e = reg["projects"].get(uid)
        if e is None:
            return
        e["mirror"] = dict(e.get("mirror") or {}, **fields)
        save_registry(reg)

def _paused_with(entry: dict, remote: str):
    """The pause Release put on Keep in sync with `remote`, if there is one."""
    m = (entry or {}).get("mirror") or {}
    p = m.get("paused")
    return p if p and remote and (p.get("remote") or m.get("remote")) == remote else None

def _end_pause(uid: str, remote: str) -> bool:
    """A handover to the machine Release paused Keep in sync with (or a Take
    Back from it) has finished: it sent this copy over the one the release
    left there, and what it replaced is set aside there, so the pause has
    done its job and the sync goes on once the project is here."""
    with Lock():
        reg = load_registry()
        e = reg["projects"].get(uid)
        if not _paused_with(e, remote):
            return False
        e["mirror"] = {k: v for k, v in e["mirror"].items() if k != "paused"}
        save_registry(reg)
    log(f"MIRROR pause with {remote} ends: {e['real_path']} went there again")
    return True

MIRROR_PAUSED = "paused since the project was released; turn Keep in sync on again to send it"

def _mirror_check(entry: dict, real: str) -> None:
    if entry.get("away"):
        raise HandoverError("handed over: the other machine holds the live copy")
    if entry.get("handing"):
        raise HandoverError("a handover of it has not finished")
    if not os.path.isdir(real):
        raise HandoverError("the folder is missing")

def mirror_project(uid: str, entry: dict, progress: bool = False) -> dict:
    real = os.path.realpath(entry["real_path"])
    m = {"tried_at": time.time()}
    row = {"project": real, "remote": (entry.get("mirror") or {}).get("remote")}
    try:
        _mirror_check(entry, real)
        with ProjectLock(uid):
            # the entry as the registry has it now, not as the pass read it
            # at its start: a handover, or a Release that paused this sync,
            # may have come in between (neither can while this lock is held)
            entry = load_registry().get("projects", {}).get(uid) or {}
            mm = entry.get("mirror") or {}
            if mm.get("paused"):
                return dict(row, status="paused", reason=MIRROR_PAUSED)
            if not mm.get("enabled"):
                return dict(row, status="skipped", reason="Keep in sync is off for it now")
            real = os.path.realpath(entry["real_path"])
            row.update(project=real, remote=mm.get("remote"))
            _mirror_check(entry, real)
            rem = get_remote(mm.get("remote"))
            rem.connect(real)
            row["remote"] = rem.name
            if rem.info.get("sessions") or rem.info.get("processes"):
                raise HandoverError(f"something is running in it on {rem.name}")
            if not rem.info.get("path_writable"):
                raise HandoverError(f"{rem.info.get('path_base')} is not writable "
                                    f"on {rem.name}")
            r = push_project(rem, uid, entry, progress=progress, sync=True)
        sent = r["project"].get("bytes", 0) + r["history"].get("bytes", 0) \
            + sum(x.get("bytes", 0) for x in r["extras"])
        m.update(synced_at=time.time(), status="ok", bytes=sent, path=real)
        row.update(status="synced", bytes=sent,
                   files=r["project"].get("files", 0) + r["history"].get("files", 0))
        log(f"MIRROR {real} -> {rem.name} ({row['files']} file(s), {_human(sent)})")
    except HandoverError as e:
        m["status"] = str(e)
        row.update(status="skipped", reason=str(e))
        warn(f"MIRROR {real}: {e}")
    _update_mirror(uid, **m)
    return row

def mirror_pass(only_due: bool = False, only: str = None, progress: bool = False) -> list:
    reg = load_registry()
    rows = []
    for uid, e in sorted(reg.get("projects", {}).items(),
                         key=lambda kv: kv[1].get("real_path") or ""):
        if not (e.get("mirror") or {}).get("enabled"):
            continue
        if only and os.path.realpath(e["real_path"]) != only:
            continue
        if only_due and not mirror_due(e):
            continue
        if e["mirror"].get("paused"):       # Release paused it: nothing goes there
            rows.append({"project": e["real_path"], "remote": e["mirror"].get("remote"),
                         "status": "paused", "reason": MIRROR_PAUSED})
            continue
        rows.append(mirror_project(uid, e, progress=progress))
    return rows

def _spawn_mirror() -> None:
    """From the watcher and the hook: sync what is due, detached, one run at
    a time."""
    try:
        if os.environ.get("AHT_NO_MIRROR") or not can_send_projects():
            return
        reg = load_registry()
        if not any(mirror_due(e) for e in reg.get("projects", {}).values()):
            return
        _spawn_aht(["mirror", "--run", "--due", "--quiet"])
    except Exception:
        pass

def mirror_all(on: bool, to: str = None, apply: bool = False) -> dict:
    """Switch "keep in sync" on (or off) for every tracked project at once.
    The plan says how much the first copy sends: everything that travels in
    a handover (rebuilt folders such as node_modules stay behind)."""
    res = {"on": on, "applied": False, "blockers": [], "projects": [], "bytes": 0}
    rem = None
    if on:
        try:
            rem = get_remote(to)
        except HandoverError as e:
            res["blockers"].append(str(e))
            return res
        res["remote"] = rem.name
    home = os.path.realpath(str(Path.home()))
    projects = load_registry().get("projects", {})
    tops = [e["real_path"] for e in projects.values() if os.path.isdir(e["real_path"])
            and os.path.realpath(e["real_path"]) != home]
    for uid, e in projects.items():
        real, m = e["real_path"], e.get("mirror") or {}
        if not os.path.isdir(real) or e.get("away") or e.get("handing") \
                or os.path.realpath(real) == home:
            continue
        if on and any(t != real and _inside(real, t) for t in tops):
            continue            # inside another project: that one's copy carries it
        if on and m.get("enabled") and m.get("remote") == rem.name:
            continue
        if not on and not m.get("enabled"):
            continue
        row = {"uuid": uid, "project": real}
        if on:
            files = tree_manifest(real)["files"]
            row.update(files=len(files),
                       bytes=sum(v[0] for v in files.values() if isinstance(v[0], int)))
            res["bytes"] += row["bytes"]
        res["projects"].append(row)
    res["projects"].sort(key=lambda r: -r.get("bytes", 0))
    if not res["projects"]:
        res["blockers"].append("every project is in sync already" if on
                               else "no project is kept in sync")
    if not apply or res["blockers"]:
        return res
    with Lock():
        reg = load_registry()
        for r in res["projects"]:
            e = reg["projects"].get(r["uuid"])
            if e is None:
                continue
            m = dict(e.get("mirror") or {})
            m["enabled"] = on
            m.pop("paused", None)
            if rem:
                m["remote"] = rem.name
            e["mirror"] = m
        save_registry(reg)
    log(f"MIRROR all {'on' if on else 'off'}: {len(res['projects'])} project(s)"
        + (f" to {rem.name}" if rem else ""))
    if on:
        _spawn_mirror()
    res["applied"] = True
    return res

def cmd_mirror(args):
    if not handover_supported():
        print("mirroring needs rsync and ssh; it is not available in this build")
        return 2
    if args.all:
        if not (args.on or args.off):
            print("with --all, say --on or --off", file=sys.stderr)
            return 2
        res = mirror_all(bool(args.on), args.to, args.apply)
        lines = []
        if res["projects"]:
            word = ("keeping in sync" if res["applied"] else "would keep in sync") if args.on \
                else ("stopped" if res["applied"] else "would stop")
            lines.append(f"{word}: {len(res['projects'])} project(s)"
                         + (f" with {res['remote']}, about {res['bytes'] / 1e9:.1f} GB "
                            "to send the first time" if args.on else ""))
            for r in res["projects"][:12]:
                lines.append(f"   {r.get('bytes', 0) / 1e6:>9,.0f} MB  {r['project']}"
                             if args.on else f"   {r['project']}")
            if len(res["projects"]) > 12:
                lines.append(f"   … and {len(res['projects']) - 12} more")
            if not args.apply:
                lines.append("(dry run — pass --apply to do it)")
        return _emit(args, res, lines)
    real = os.path.realpath(args.path) if args.path else None
    if args.on or args.off:
        if not real or not os.path.isdir(real) \
                or _inside(os.path.realpath(str(Path.home())), real):
            print("name the project folder to switch mirroring on or off", file=sys.stderr)
            return 2
        try:
            rem = get_remote(args.to) if args.on else None
        except HandoverError as e:
            print(str(e), file=sys.stderr)
            return 2
        with Lock():
            reg = load_registry()
            uid, entry = _entry_for(reg, real)
            if entry is None:
                uid = read_marker(real) or new_uuid()
                write_marker(real, uid)
                _register(reg, uid, real)
                entry = reg["projects"][uid]
            m = dict(entry.get("mirror") or {})
            m["enabled"] = bool(args.on)
            m.pop("paused", None)           # on again (or off): Release's pause ends
            if rem:
                m["remote"] = rem.name
            entry["mirror"] = m
            save_registry(reg)
        log(f"MIRROR {'on' if args.on else 'off'} {real}")
        if args.off or not args.run:
            print(f"mirroring {'on' if args.on else 'off'}: {real}"
                  + (f"  (to {rem.name}; the first sync runs in the background)"
                     if rem else ""))
            if args.on:
                _spawn_mirror()
            return 0
    if args.run:
        lock = aht_home() / "run"
        lock.mkdir(parents=True, exist_ok=True)
        fh = open(lock / "mirror.lock", "w")
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            if not args.quiet:
                print("a mirror run is already in progress")
            return 0
        rows = mirror_pass(only_due=args.due, only=real,
                           progress=sys.stderr.isatty() and not args.json and not args.quiet)
        if args.json:
            print(json.dumps({"mirrored": rows}, indent=2))
        elif not args.quiet:
            for r in rows:
                print(f"  {'✓' if r['status'] == 'synced' else '·'} {r['project']}  → "
                      f"{r.get('remote')}: "
                      + (f"{r['files']} file(s), {_human(r['bytes'])} sent"
                         if r["status"] == "synced" else r.get("reason", "")))
            if not rows:
                print("nothing to sync")
        return 0
    reg = load_registry()
    rows = [{"project": e["real_path"], **(e.get("mirror") or {}),
             "away": bool(e.get("away"))}
            for e in reg.get("projects", {}).values()
            if (e.get("mirror") or {}).get("enabled")
            and (not real or os.path.realpath(e["real_path"]) == real)]
    if args.json:
        print(json.dumps({"mirrors": rows}, indent=2))
    else:
        print(f"{len(rows)} project(s) kept in sync:")
        for r in sorted(rows, key=lambda r: r["project"].lower()):
            at = time.strftime("%Y-%m-%d %H:%M", time.localtime(r["synced_at"])) \
                if r.get("synced_at") else "never"
            print(f"   {r['project']}  → {r.get('remote')}   last sync {at}"
                  + ("" if r.get("status") in (None, "ok") else f"   ({r['status']})")
                  + ("   [handed over]" if r["away"] else "")
                  + ("   [paused: it was released]" if r.get("paused") else ""))
    return 0

# ---- handover ----------------------------------------------------------------- #

def _emit(args, out: dict, lines: list) -> int:
    """Print one command's result: JSON for the front-ends, text for people."""
    code = 3 if out.get("blockers") else (1 if out.get("error") else 0)
    if getattr(args, "json", False):
        print(json.dumps(out, indent=2, default=str))
        return code
    for l in lines:
        print(l)
    for w in out.get("warnings") or []:
        print(f"  ! {w}")
    for b in out.get("blockers") or []:
        print(f"  ✗ {b}")
    if out.get("error"):
        print(f"  ✗ {out['error']}")
    return code

HANDING_GRACE = 180         # s: a younger unfinished handover may still be under way
HANDING_RELEASE_AFTER = 3600    # s without an answer, then Release is offered
HANDING_ONLY = ("step", "at", "error", "checked_at", "unreachable_since", "told_release",
                "extras")

def _clock(v) -> str:
    """A time as people read it: "14:10" today, else "2026-10-25 14:10"."""
    t = _when(v)
    if not t:
        return str(v or "?")
    if time.strftime("%Y-%m-%d", time.localtime(t)) == time.strftime("%Y-%m-%d"):
        return time.strftime("%H:%M", time.localtime(t))
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t))

def _retire_manifest(hd: Path) -> None:
    """The record of what left, kept under its time once it is no longer the
    base of a way back (the newest few stay)."""
    try:
        if (hd / "manifest.json").is_file():
            (hd / "manifest.json").replace(hd / f"manifest-{_stamp()}-{os.urandom(2).hex()}.json")
        for old in sorted(hd.glob("manifest-*.json"))[:-5]:
            old.unlink()
    except OSError:
        pass

def _unfinished_text(h: dict, real: str) -> str:
    return (f"a handover of this project to {h.get('remote')} has not finished; aht "
            "asks that machine again within a few minutes — or release it to work "
            f"on it here:  aht reclaim {shlex.quote(real)} --release")

def handing_row(h: dict, uid: str = None):
    """`projects --json` "handing": the record and where it stands — "running"
    (the handover runs now), "checking" (aht asks the other machine at its
    next check), "unreachable" (it did not answer); `release`: Release is
    offered (no answer for an hour)."""
    if not h:
        return None
    row = {k: h.get(k) for k in ("attempt", "step", "remote", "holder", "host", "driven_by",
                                 "since", "error", "checked_at", "unreachable_since")}
    busy = False
    if uid:
        try:
            with ProjectLock(uid):
                pass
        except HandoverError:
            busy = True
    row["state"] = ("running" if busy else
                    "unreachable" if h.get("unreachable_since") else "checking")
    row["release"] = bool(h.get("unreachable_since")) and \
        time.time() - float(h["unreachable_since"]) >= HANDING_RELEASE_AFTER
    return row

def resolve_handing(uid: str, force: bool = False) -> list:
    """Finish or undo a handover that was cut off (the link dropped, this
    machine slept, aht was stopped).  The other machine says what happened:
    a session runs in the copy there, the copy or its conversation changed
    since the record of what left, or this attempt's session started there
    (and has ended since) → it is handed over; only when nothing at all
    happened there does the project stay here.  When that machine does not
    answer, the record stays, and after an hour Release is offered.
    Skipped while a transfer of the project runs; unless `force`, also for
    3 minutes after a step of an attempt that may still be under way, and
    for a minute after a machine did not answer.  -> the notices to show."""
    e = load_registry().get("projects", {}).get(uid) or {}
    h = e.get("handing")
    if not h or not can_send_projects():
        return []
    now = time.time()
    if not force:
        if not h.get("error") and now - float(h.get("at") or 0) < HANDING_GRACE:
            return []
        if h.get("unreachable_since") and now - float(h.get("checked_at") or 0) < 55:
            return []
    real = e["real_path"]
    name, there = os.path.basename(real) or real, h.get("remote") or "the other machine"
    hd = handover_dir(uid)
    try:
        lock = ProjectLock(uid).__enter__()
    except HandoverError:
        return []                           # a transfer of it runs right now
    try:
        try:
            base = json.loads((hd / "manifest.json").read_text())
        except Exception:
            base = {}
        if base.get("attempt") != h.get("attempt"):
            base = {}                       # no record of what left in this attempt
        try:
            rem = get_remote(h.get("remote"))
            info = rem.connect(real)
            runs = bool(info.get("sessions"))
            changed = talked = started = False
            if base and not runs:
                trees = {"project": {"path": rem.path(real), "skip": handover_skip()},
                         "history": {"path": f"{info['claude_home']}/projects/"
                                             f"{_key_claude(rem.path(real))}", "skip": []}}
                if h.get("window") and info.get("home"):
                    trees["run"] = {"path": f"{info['home']}/.aht/remote/run/{h['window']}",
                                    "skip": []}
                now_there = rem.agent("manifest", timeout=900, trees=trees)["trees"]
                was = base.get("there") or {}
                changed = now_there["project"]["files"] != was.get("project")
                talked = now_there["history"]["files"] != (was.get("history") or {})
                started = f"attempt-{h.get('attempt')}" in \
                    ((now_there.get("run") or {}).get("files") or {})
        except HandoverError as err:
            h2 = dict(h, checked_at=now, error=str(err),
                      unreachable_since=h.get("unreachable_since") or now)
            notes = []
            if now - h2["unreachable_since"] >= HANDING_RELEASE_AFTER and not h.get("told_release"):
                h2["told_release"] = True
                notes.append({"kind": "handover", "title": f"{name}: handover unfinished",
                              "message": f"{there} has not answered since "
                                         f"{_clock(h2['unreachable_since'])}. To work on "
                                         f"{name} here, release it in aht; the work on "
                                         f"{there} stays there.",
                              "info": {"kind": "handover", "project": real, "remote": there}})
            _update_entry(uid, handing=h2)
            return notes
        dropped = _clock(float(h.get("at") or now))
        if base and (runs or changed or talked or started):
            away = {k: v for k, v in h.items() if k not in HANDING_ONLY}
            _update_entry(uid, away=away, handing=None,
                          extras=h.get("extras") or e.get("extras"))
            _end_pause(uid, h.get("remote"))
            msg = (f"Handover of {name} to {there} finished: "
                   + ("the session there runs" if runs else
                      "the copy there was worked on" if changed else
                      "the conversation went on there" if talked else
                      "the session there started, and has ended since")
                   + f" (the link had dropped at {dropped})")
            title = f"{name} is on {there}"
            log(f"HANDOVER {real} -> {there}: finished after the link dropped")
        else:
            _update_entry(uid, handing=None)
            _retire_manifest(hd)
            msg = (f"The handover of {name} to {there} did not finish. The project stays "
                   "here; " + ("a session runs in the copy there, which aht does not follow"
                               if runs else "nothing runs there"))
            title = f"{name} stays here"
            log(f"HANDOVER {real} -> {there}: did not finish; the project stays here")
    finally:
        lock.__exit__(None, None, None)
    try:
        apply_badge(real, desired_marks(real, True))
    except Exception:
        pass
    return [{"kind": "handover", "title": title, "message": msg,
             "info": {"kind": "handover", "project": real, "remote": there}}]

def cmd_handover(args):
    out = {"command": "handover", "applied": False, "blockers": [], "warnings": []}
    lines = []
    if not handover_supported():
        out["blockers"].append("handover needs rsync and ssh; it is not available "
                               "in this build")
        return _emit(args, out, lines)
    real = os.path.realpath(args.path)
    out["project"] = real
    if not os.path.isdir(real):
        out["blockers"].append(f"not a folder: {real}")
        return _emit(args, out, lines)
    if _inside(os.path.realpath(str(Path.home())), real):
        out["blockers"].append("that is your home folder (or contains it), "
                               "not a project")
        return _emit(args, out, lines)
    talk = not args.json
    prog = Progress(args.status_file, talk)
    say = prog.say
    try:
        rem = get_remote(args.to)
        rem.on_percent = prog.percent
        out["remote"] = rem.name
        with Lock():
            reg = load_registry()
            uid, entry = _entry_for(reg, real)
            if entry is None and args.apply:
                uid = read_marker(real) or new_uuid()
                write_marker(real, uid)
                _register(reg, uid, real)
                entry = reg["projects"][uid]
                save_registry(reg)
        if (entry or {}).get("handing"):
            # an earlier attempt was cut off: finish it or undo it first
            out["warnings"] += [n["message"] for n in resolve_handing(uid, force=True)]
            entry = _entry_for(load_registry(), real)[1] or entry
        entry = dict(entry or {"real_path": real})
        uid = uid or "untracked"
        if entry.get("away"):
            a = entry["away"]
            out["blockers"].append(f"already handed over to {a.get('remote')} since "
                                   f"{a.get('since')} — take it back first:  aht reclaim")
            return _emit(args, out, lines)
        if entry.get("handing"):
            out["blockers"].append(_unfinished_text(entry["handing"], real))
            return _emit(args, out, lines)
        for p in args.include or []:
            why = _check_extra(p)
            if why:
                out["blockers"].append(f"{p}: {why}")
        extras = list(dict.fromkeys(
            list(entry.get("extras") or [])
            + [os.path.realpath(os.path.expanduser(p)) for p in args.include or []]))
        entry["extras"] = extras

        # (1) nothing may be running in it here
        act = activity_in(real)
        out["here"] = act
        out["blockers"] += _activity_blockers(act, "on this machine")
        if act["processes"] and not args.allow_processes:
            names = ", ".join(sorted({f"{p['name']} ({p['pid']})" for p in act["processes"]}))
            out["blockers"].append(f"still running in this folder: {names} — stop "
                                   "them, or pass --allow-processes to leave them behind")

        # (2) the other machine
        say(f"checking {rem.name} …")
        info = rem.connect(real)
        out["there"] = {k: info.get(k) for k in
                        ("host", "system", "home", "claude", "claude_version",
                         "path_exists", "path_writable", "free_bytes",
                         "sessions", "processes")}
        if info.get("path_real") and info["path_real"] != rem.path(real) \
                and info.get("path_exists"):
            out["blockers"].append(f"{real} is a link on {rem.name} (to "
                                   f"{info['path_real']}); the histories are keyed "
                                   "on the real path, so it must be a real folder")
        if not info.get("path_writable"):
            out["blockers"].append(
                f"{rem.name} cannot hold {real}: {info.get('path_base')} is not "
                f"writable there — create the folder once, e.g.  sudo mkdir -p "
                f"{str(Path.home())} && sudo chown $USER {str(Path.home())}")
        out["blockers"] += _activity_blockers(info, f"on {rem.name}")
        if info.get("processes"):
            out["blockers"].append(f"something is running in this folder on {rem.name}: "
                                   + ", ".join(sorted({p["name"] for p in info["processes"]})))
        tools = info.get("tools") or {}
        for t in ("rsync", "tmux"):
            if not tools.get(t) and not (t == "tmux" and args.no_start):
                out["blockers"].append(f"{t} is missing on {rem.name}")
        mine = find_claude()
        here_ver = claude_version(mine) if mine else None
        out["claude"] = {"here": here_ver, "there": info.get("claude_version")}
        install = None
        if not args.no_start:
            if not here_ver:
                out["warnings"].append("Claude Code was not found on this machine; "
                                       "the other side keeps its own version")
                if not info.get("claude"):
                    out["blockers"].append(f"Claude Code is not installed on {rem.name}")
            elif info.get("claude_version") != here_ver:
                install = here_ver
                if not tools.get("curl"):
                    out["blockers"].append(f"Claude Code {here_ver} is needed on "
                                           f"{rem.name} (it has "
                                           f"{info.get('claude_version') or 'none'}) and "
                                           "curl is missing there to install it")

        # (3) what would travel
        store = _store_of(real)
        sids = _sessions_of(store)
        sid = args.session or latest_session(store)
        if args.session and args.session not in sids:
            out["blockers"].append(f"no session {args.session} in this project")
        out["session"] = sid
        out["sessions"] = len(sids)
        dig = session_digest(Path(store) / f"{sid}.jsonl", real) if sid else \
            session_digest(os.devnull, real)
        out["title"] = dig.get("title")
        carried = list(extras)
        out["outside_not_carried"] = [p for p in dig["outside"]
                                      if not any(_inside(p, c) for c in carried)]
        out["task"] = args.task
        try:
            found = scan_secrets(real)
        except Exception:
            found = []
        if found:
            out["secrets"] = len(found)
            out["warnings"].append(f"{len(found)} thing(s) that look like a key, token or "
                                   "password are in this project's agent history and "
                                   "travel with it (aht secrets shows where)")
        if out["blockers"]:
            return _emit(args, out, lines)
        if not args.apply:
            plan = push_project(rem, uid, entry, dry=True)
            out["plan"] = {
                "files": plan["project"].get("files", 0),
                "bytes": plan["project"].get("bytes", 0),
                "history_bytes": plan["history"].get("bytes", 0),
                "extras": [{"path": x["path"], "bytes": x.get("bytes", 0)}
                           for x in plan["extras"]],
                "install_claude": install,
                "free_bytes": info.get("free_bytes")}
            need = out["plan"]["bytes"] + out["plan"]["history_bytes"]
            if info.get("free_bytes") is not None and need > info["free_bytes"]:
                out["blockers"].append(f"{rem.name} has {_human(info['free_bytes'])} "
                                       f"free, {_human(need)} are needed")
            lines += [f"would hand over:  {real}",
                      f"   to             {rem.name} ({info.get('host')}, "
                      f"{info.get('system')})",
                      f"   files to send  {out['plan']['files']} "
                      f"({_human(out['plan']['bytes'])}), history "
                      f"{_human(out['plan']['history_bytes'])}",
                      f"   session        {dig.get('title') or sid or 'none yet'}",
                      f"   Claude Code    {here_ver or '?'} here, "
                      f"{info.get('claude_version') or 'none'} there"
                      + (f" → {install} gets installed" if install else "")]
            if out["outside_not_carried"]:
                lines.append("   stays here     " + ", ".join(out["outside_not_carried"][:5])
                             + "   (carry with --include <path>)")
            if _paused_with(entry, rem.name):
                # Release left work there; this handover replaces it
                out["ends_pause"] = rem.name
                out["warnings"].append(
                    f"the copy that Release left on {rem.name} is replaced by this one "
                    f"(aht sets it aside there first); Keep in sync with {rem.name} "
                    "goes on again once the project is back here")
            lines.append("(dry run — pass --apply to do it)")
            return _emit(args, out, lines)

        # (4) do it.  The attempt is recorded before anything travels: should
        # the link drop or this machine sleep halfway, resolve_handing
        # finishes it or undoes it at the next check
        attempt = f"{_stamp()}-{os.urandom(2).hex()}"
        away = {"v": 2, "attempt": attempt, "remote": rem.name,
                "holder": info.get("host") or rem.name, "holder_id": info.get("machine_id"),
                "host": info.get("host"), "system": info.get("system"),
                "driven_by": "here", "path": real, "remote_path": rem.path(real),
                "since": _now(), "agent": "claude", "session": sid,
                "window": _mux_name(real, uid), "mux": "byobu" if tools.get("byobu") else "tmux",
                "relay": None, "task": args.task, "claude": here_ver, "transfer": "rsync"}
        if rem.sandbox:
            away["mux"] = "tmux"            # a tmux server of its own
        with ProjectLock(uid):
            hd = handover_dir(uid)
            _retire_manifest(hd)            # an earlier attempt's: never a base
            # what --include carries goes with the record: a handover that
            # resolve_handing finishes brings them back at Take Back too
            handing = dict(away, step="sending", at=time.time(),
                           **({"extras": extras} if extras else {}))
            _update_entry(uid, handing=handing)
            try:
                try:
                    _snapshot_project(uid, entry)
                except Exception as e:
                    out["warnings"].append(f"history backup failed: {e}")
                scratch = False
                if sid:
                    sdir = scratch_dir(real, sid)
                    keep = Path(real) / ".aht" / "handover" / "scratch"
                    shutil.rmtree(keep, ignore_errors=True)
                    keep.parent.mkdir(parents=True, exist_ok=True)
                    (keep.parent / ".gitignore").write_text("*\n")
                    if sdir and any(sdir.iterdir()) and sum(
                            f.stat().st_size for f in sdir.rglob("*") if f.is_file()) \
                            <= SCRATCH_MAX_BYTES:
                        shutil.copytree(sdir, keep / sid, symlinks=True)
                        scratch = True
                brief, note = write_brief(real, sid, dig, _here(), info.get("host") or rem.name,
                                          info.get("system"), carried, scratch, args.task)
                out["brief"] = str(brief)
                say(f"sending the project to {rem.name} …")
                sent = push_project(rem, uid, entry, progress=talk and sys.stderr.isatty())
                out["sent"] = {"files": sent["project"].get("files", 0),
                               "bytes": sent["project"].get("bytes", 0),
                               "history_bytes": sent["history"].get("bytes", 0),
                               "wire_bytes": sent["project"].get("sent", 0)
                               + sent["history"].get("sent", 0)}

                # what left, as seen on BOTH sides: the base of the way back
                rstore = f"{info['claude_home']}/projects/{_key_claude(rem.path(real))}"
                theirs = rem.agent("manifest", timeout=900, trees={
                    "project": {"path": rem.path(real), "skip": handover_skip()},
                    "history": {"path": rstore, "skip": []}})["trees"]
                ours = {"project": tree_manifest(real),
                        "history": tree_manifest(str(store), []) if store
                        else tree_manifest(os.devnull, [])}
                lost = sorted(set(ours["project"]["files"]) - set(theirs["project"]["files"]))
                if lost:
                    out["warnings"].append(f"{len(lost)} file(s) did not arrive, e.g. {lost[0]}")
                hashes = {k: [v[0], file_sha256(Path(store) / (ours["history"]["raw"].get(k) or k))]
                          for k, v in ours["history"]["files"].items()
                          if k.endswith(".jsonl") and isinstance(v[0], int)} if store else {}
                hd.mkdir(parents=True, exist_ok=True)
                _write_json(hd / "manifest.json", {
                    "v": 2, "attempt": attempt,
                    "uuid": uid, "project": real, "remote": rem.name, "at": _now(),
                    "here": {k: v["files"] for k, v in ours.items()},
                    "there": {k: v["files"] for k, v in theirs.items()},
                    "dirs": {"here": {k: v.get("dirs") or [] for k, v in ours.items()},
                             "there": {k: v.get("dirs") or [] for k, v in theirs.items()}},
                    "modes": {k: v.get("modes") or {} for k, v in ours.items()},
                    "transcripts": hashes})
                handing = dict(handing, step="recorded", at=time.time())
                _update_entry(uid, handing=handing)

                if install:
                    say(f"installing Claude Code {install} on {rem.name} …")
                    got = rem.agent("install-claude", timeout=1000, version=install)
                    info["claude"] = got["claude"]
                if not args.no_start:
                    trusted = False
                    try:
                        cj = json.loads(_claude_json().read_text())
                        trusted = bool((cj.get("projects") or {}).get(real, {})
                                       .get("hasTrustDialogAccepted"))
                    except Exception:
                        pass
                    if trusted and cfg_get("handover_carry_trust", True):
                        out["trust"] = rem.agent("trust", path=rem.path(real)).get("trust")
                    say(f"starting the session on {rem.name} …")
                    handing = dict(handing, step="starting", at=time.time())
                    _update_entry(uid, handing=handing)
                    st = rem.agent("start", timeout=90, path=rem.path(real), session=sid,
                                   name=away["window"], attempt=attempt,
                                   claude=info["claude"], note=note,
                                   args=list(cfg_get("handover_claude_args") or []),
                                   task=args.task,
                                   remote_control=handover_session_name(sid, real, rem.name)
                                   if cfg_get("handover_remote_control", True) else None)
                    away["mux"] = st.get("mux") or away["mux"]
                    out["started"] = st.get("started")
                    out["screen"] = st.get("screen")
                    if st.get("attention"):
                        out["warnings"].append(f"the session on {rem.name} needs you: "
                                               f"{st['attention']} — open it to answer")
                # one write: nothing ever sees the one record without the other
                _update_entry(uid, away=away, handing=None, extras=extras or None)
            except BaseException as e:
                if handing["step"] == "starting" and (isinstance(e, LinkError)
                                                      or not isinstance(e, HandoverError)):
                    # whether the session there started is not known: the
                    # record stays for resolve_handing
                    _update_entry(uid, handing=dict(handing, error=str(e) or type(e).__name__,
                                                    at=time.time()))
                    if isinstance(e, HandoverError):
                        raise HandoverError(
                            f"{e} — whether the session on {rem.name} started is not known "
                            "yet; aht asks again within a few minutes and tells you")
                    raise
                # nothing runs there: the project stays here
                _update_entry(uid, handing=None)
                _retire_manifest(hd)
                out["warnings"].append(f"The handover of {os.path.basename(real)} to "
                                       f"{rem.name} did not finish. The project stays "
                                       "here; nothing runs there")
                raise
        out["applied"] = True
        out["away"] = away
        out["attach"] = attach_command(rem, away["mux"], away["window"])
        if _end_pause(uid, rem.name):       # Release's: this copy went over that one
            out["ends_pause"] = rem.name
        log(f"HANDOVER {real} -> {rem.name} (session {sid}, "
            f"{_human(out['sent']['bytes'] + out['sent']['history_bytes'])})")
        apply_badge(real, desired_marks(real, True))
        notify_user("Handed over", f"{os.path.basename(real)} now runs on {rem.name}")
        lines += [f"handed over:  {real}  →  {rem.name}",
                  f"   sent      {out['sent']['files']} file(s), "
                  f"{_human(out['sent']['bytes'])}; history "
                  f"{_human(out['sent']['history_bytes'])}  "
                  f"({_human(out['sent']['wire_bytes'])} on the wire)",
                  f"   session   {dig.get('title') or sid or 'a new one'}",
                  f"   summary   {brief}",
                  "   open it   " + " ".join(shlex.quote(a) for a in out["attach"]),
                  "   back      aht reclaim " + shlex.quote(real) + " --apply"]
        if out.get("ends_pause"):
            lines.append(f"   Keep in sync with {rem.name} goes on again once you take it back "
                         "(the copy Release left there is set aside there)")
    except HandoverError as e:
        out["error"] = str(e)
        warn(f"HANDOVER {real}: {e}")
    code = _emit(args, out, lines)
    if out.get("applied") and args.attach and not args.json:
        os.execvp(out["attach"][0], out["attach"])
    return code

# ---- reclaim ------------------------------------------------------------------ #

def _conflict_name(rel: str, there: str, day: str) -> str:
    head, tail = os.path.split(rel)
    stem, ext = os.path.splitext(tail)
    return os.path.join(head, f"{stem} (from {there} {day}){ext}")

def _free_name(root: str, rel: str) -> str:
    """`rel`, or "name 2.ext", "name 3.ext" … when a file of that name is there."""
    stem, ext = os.path.splitext(rel)
    n, cand = 2, rel
    while os.path.lexists(os.path.join(root, cand)):
        cand, n = f"{stem} {n}{ext}", n + 1
    return cand

def _set_aside(path: Path, aside: Path, rel: str) -> None:
    dst = aside / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    os.replace(path, dst)

def _ignores_case(folder: str) -> bool:
    """Whether the disk under `folder` takes Readme and README for one name:
    tried, since a Mac's disk can be either (tests: AHT_CASELESS=1)."""
    if os.environ.get("AHT_CASELESS"):
        return True
    p = Path(folder) / f".aht-case-{os.urandom(3).hex()}"
    try:
        with open(p, "x"):
            pass
    except OSError:
        return CASE_BLIND
    try:
        return p.with_name(p.name.upper()).exists()
    finally:
        try:
            p.unlink()
        except OSError:
            pass

def _pull_tree(rem: Remote, plan: dict, src: str, dst: str, there_raw: dict,
               aside: Path, there: str, inert: bool, skip, progress: bool,
               here_keys=(), new_dirs=()) -> dict:
    """Carry out one three-way plan: set aside what was removed there, fetch
    what changed there (setting aside what it replaces), and keep both
    versions of what changed on both sides.  Removals go first, so a name
    whose case changed there (readme.md → README.md) arrives on a disk that
    ignores case, instead of being set aside right after.  On such a disk,
    two incoming names that differ only in case, or one that would land on a
    file here that stays, are kept next to it under the conflict name.
    `new_dirs`: folders made there (git's empty refs/heads) are made here."""
    done = {"updated": 0, "new": 0, "deleted": 0, "conflicts": [], "kept": len(plan["kept"])}
    name = lambda k: there_raw.get(k) or k
    gone = set(plan["delete"])
    for k in plan["delete"]:
        p = Path(dst) / k
        if p.exists() or p.is_symlink():
            _set_aside(p, aside, k)
            done["deleted"] += 1
    incoming, clash = plan["take"] + plan["new"], []
    if incoming and _ignores_case(dst):
        stays = {k.casefold(): k for k in here_keys if k not in gone}
        seen = {}
        for k in incoming:
            f = k.casefold()
            if stays.get(f, k) != k or seen.get(f, k) != k:
                clash.append(k)
            else:
                seen[f] = k
    fetch = [k for k in incoming if k not in clash]
    if fetch:
        aside.mkdir(parents=True, exist_ok=True)
        r = rem.rsync(rem.spec(src + "/"), dst + "/", files_from=[name(k) for k in fetch],
                      backup_dir=str(aside), skip=skip, progress=progress)
        if not r["ok"]:
            raise HandoverError("fetching the changes failed: " + r["error"])
        done["updated"] = len([k for k in plan["take"] if k not in clash])
        done["new"] = len([k for k in plan["new"] if k not in clash])
    for d in new_dirs:
        try:
            (Path(dst) / d).mkdir(parents=True, exist_ok=True)
        except OSError:
            pass                            # a file of that name here: it stays
    # each group in a folder of its own: two names of one case group would
    # land on one file there too
    groups = ([plan["conflict"]] if plan["conflict"] else []) + [[k] for k in clash]
    if groups:
        inc = aside.parent / (aside.name + "-incoming")
        day = time.strftime("%Y-%m-%d")
        for i, keys in enumerate(groups):
            box = inc / str(i)
            box.mkdir(parents=True, exist_ok=True)
            r = rem.rsync(rem.spec(src + "/"), str(box) + "/",
                          files_from=[name(k) for k in keys], skip=skip)
            if not r["ok"]:
                raise HandoverError("fetching the conflicting files failed: " + r["error"])
            for k in keys:
                got = next((c for c in (box / k, box / name(k)) if c.exists()), None)
                mine = Path(dst) / k
                if got is None:
                    continue
                if mine.is_file() and got.is_file() and \
                        file_sha256(mine) == file_sha256(got):
                    continue                    # the same on both sides
                rel = _free_name(dst, (k + f".aht-conflict-{there}-{_stamp()}") if inert
                                 else _conflict_name(k, there, day))
                (Path(dst) / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(got), str(Path(dst) / rel))
                done["conflicts"].append({"file": k, "their_version": rel,
                                          **({"case": True} if k in clash else {})})
        shutil.rmtree(inc, ignore_errors=True)
    return done

def _changed_there(uid: str, entry: dict) -> dict:
    """{files, history}: how many files of a handed-over project, and of its
    Claude history (with /rewind's file-history and the plans), changed on
    the other machine since it left; None each when that machine does not
    answer."""
    away, real = entry.get("away") or {}, entry["real_path"]
    store = _store_of(real)
    sids = _sessions_of(store)
    plans = [p[1:] for p in _plans_of(store)]
    try:
        base = json.loads((handover_dir(uid) / "manifest.json").read_text())
        if base.get("attempt") != away.get("attempt"):
            return {"files": None, "history": None}
        rem = get_remote(away.get("remote"))
        info = rem.connect()
        rclaude = info["claude_home"]
        trees = {"project": {"path": rem.path(real), "skip": handover_skip()},
                 "history": {"path": f"{rclaude}/projects/{_key_claude(rem.path(real))}",
                             "skip": []}}
        # file-history and plans were sent as they are here: what differs
        # there now was written there
        trees.update({f"file-history/{s}": {"path": f"{rclaude}/file-history/{s}", "skip": []}
                      for s in sids})
        if plans:
            trees["plans"] = {"path": f"{rclaude}/plans", "skip": []}
        now = rem.agent("manifest", timeout=300, trees=trees)["trees"]
    except (HandoverError, OSError, ValueError, KeyError):
        return {"files": None, "history": None}
    was = base.get("there") or {}
    differ = lambda a, b: sum(1 for k in set(a) | set(b) if a.get(k) != b.get(k))
    files = differ(was.get("project") or {}, now["project"]["files"])
    history = differ(was.get("history") or {}, now["history"]["files"])
    for s in sids:
        mine = claude_home() / "file-history" / s
        mine = tree_manifest(str(mine), [])["files"] if mine.is_dir() else {}
        history += sum(1 for k, v in now[f"file-history/{s}"]["files"].items()
                       if mine.get(k) != v)
    if plans:
        mine = tree_manifest(str(claude_home() / "plans"), [])["files"] \
            if (claude_home() / "plans").is_dir() else {}
        history += sum(1 for k in plans if k in now["plans"]["files"]
                       and now["plans"]["files"][k] != mine.get(k))
    return {"files": files, "history": history}

def _what_stays(lost: dict) -> str:
    """What Release leaves on the other machine, in words: "3 files and the
    conversation"; "" when nothing, or when that machine did not say."""
    what = []
    if lost.get("files"):
        what.append(f"{lost['files']} file" + ("s" if lost["files"] != 1 else ""))
    if lost.get("history"):
        what.append("the conversation")
    return " and ".join(what)

def _release(args, out: dict, lines: list, real: str) -> int:
    """Stop waiting for a project that was handed over, or half handed over:
    the files here stay as they are, the copy there is left alone, and the
    work done there does not come here.  For a machine that is gone, or a
    handover that cannot be finished."""
    uid, entry = _entry_for(load_registry(), real)
    rec = (entry or {}).get("away") or (entry or {}).get("handing")
    if not rec:
        out["blockers"].append("this project is not handed over")
        return _emit(args, out, lines)
    there = rec.get("remote") or rec.get("host") or "the other machine"
    since = rec.get("since")
    def synced(e):
        """The machine Keep in sync sends this project to, when it is the one
        released: its next sync would send this copy over the work left
        there, so Release pauses it until the user turns it on again."""
        m = e.get("mirror") or {}
        return m.get("remote") if m.get("enabled") and rec.get("remote") \
            and m.get("remote") == rec.get("remote") else None
    out.update(remote=there, released=False, pauses_sync=synced(entry),
               would_lose={"files": None, "history": None, "since": since})
    when = _clock(since)
    if not args.apply:
        if entry.get("away") and can_send_projects():
            out["would_lose"].update(_changed_there(uid, entry))
        what = _what_stays(out["would_lose"])
        lines += [f"would release:  {real}  (on {there} since {when})",
                  f"   The work done on {there} since {when} stays on {there}. "
                  "It does not come here." + (f" What stays there: {what}." if what else "")]
        if out["pauses_sync"]:
            lines.append(f"   Keep in sync with {out['pauses_sync']} will be paused, so the "
                         "copy there stays as it is.")
        lines.append("(dry run — pass --apply to do it)")
        return _emit(args, out, lines)
    try:
        with ProjectLock(uid):
            # one write: the record goes and the sync pauses together
            with Lock():
                reg = load_registry()
                e = reg["projects"].get(uid)
                if e is not None:
                    out["pauses_sync"] = synced(e)
                    if out["pauses_sync"]:
                        e["mirror"] = dict(e["mirror"], paused={
                            "reason": "released", "at": _now(), "remote": out["pauses_sync"]})
                    e.pop("away", None)
                    e.pop("handing", None)
                    e["returned"] = {
                        "from": rec.get("host") or there, "left": since, "at": _now(),
                        "released": True, "mode": "away", "session": rec.get("session"),
                        "handed_over": None, "updated": 0, "new": 0, "deleted": 0,
                        "conflicts": []}
                    save_registry(reg)
            _retire_manifest(handover_dir(uid))
    except HandoverError as e:
        out["error"] = str(e)
        return _emit(args, out, lines)
    out.update(applied=True, released=True)
    log(f"RELEASE {real} (on {there} since {since})"
        + (f"; keep in sync with {out['pauses_sync']} paused" if out["pauses_sync"] else ""))
    apply_badge(real, desired_marks(real, True))
    lines.append(f"released:  {real}  — it is yours here again; the copy on {there} "
                 "stays as it is")
    if out["pauses_sync"]:
        lines.append(f"   Keep in sync with {out['pauses_sync']} is paused, so the copy "
                     "there stays as it is.")
    return _emit(args, out, lines)

def cmd_reclaim(args):
    out = {"command": "reclaim", "applied": False, "blockers": [], "warnings": []}
    lines = []
    real = os.path.realpath(args.path)
    out["project"] = real
    if args.release:                    # only records here change: any build can
        return _release(args, out, lines, real)
    if not handover_supported():
        out["blockers"].append("handover needs rsync and ssh; it is not available "
                               "in this build")
        return _emit(args, out, lines)
    talk = not args.json
    prog = Progress(args.status_file, talk)
    say = prog.say
    try:
        reg = load_registry()
        uid, entry = _entry_for(reg, real)
        if (entry or {}).get("handing"):
            # cut off on the way there: finished or undone first (this is
            # also the window's "Check Now")
            out["checked"] = [n["message"] for n in resolve_handing(uid, force=True)]
            out["warnings"] += out["checked"]
            uid, entry = _entry_for(load_registry(), real)
        away = (entry or {}).get("away")
        if not away:
            out["blockers"].append(_unfinished_text(entry["handing"], real)
                                   if (entry or {}).get("handing")
                                   else "this project is not handed over")
            return _emit(args, out, lines)
        if os.path.realpath(away.get("path") or real) != real:
            out["blockers"].append(f"the folder was at {away['path']} when it was "
                                   "handed over; move it back there first")
            return _emit(args, out, lines)
        hd = handover_dir(uid)
        try:
            base = json.loads((hd / "manifest.json").read_text())
        except Exception as e:
            raise HandoverError(f"the record of what left is unreadable ({e})")
        if (base.get("attempt") or away.get("attempt")) \
                and base.get("attempt") != away.get("attempt"):
            # a list from another attempt would count the wrong files as changed
            raise HandoverError(
                "the record of what left belongs to another handover attempt "
                f"({base.get('attempt') or 'none'}, not {away.get('attempt') or 'none'}), "
                "so aht cannot tell what changed there. Release the project (aht reclaim "
                f"{shlex.quote(real)} --release) and bring over what you need by hand")
        rem = get_remote(away.get("remote"))
        rem.on_percent = prog.percent
        out["remote"] = rem.name
        there = away.get("host") or rem.name

        act = activity_in(real)
        out["here"] = act
        out["blockers"] += _activity_blockers(act, "on this machine")

        say(f"checking {rem.name} …")
        info = rem.connect(real)
        if not info["sessions"] and away.get("window") and \
                rem.agent("close", path=rem.path(real), name=away["window"]).get("closed"):
            info = rem.connect(real)        # the window it ran in is closed now
        if info["sessions"] and args.stop and \
                all(s.get("status") == "idle" for s in info["sessions"]):
            if args.apply:
                say(f"ending the idle session on {rem.name} …")
                st = rem.agent("stop", timeout=90, path=rem.path(real),
                               name=away.get("window") or "")
                out["stopped"] = st.get("stopped")
                if not st.get("stopped"):
                    out["warnings"].append({
                        "working": "the session started working again",
                        "not-ours": "the session there was not started by aht; "
                                    "exit it yourself",
                        "no-reaction": "the session did not react; exit it yourself",
                    }.get(st.get("reason"), "the session could not be ended"))
                info = rem.connect(real)
            else:
                out["would_stop"] = True
                info = dict(info, sessions=[])
        out["there"] = {"sessions": info.get("sessions"),
                        "processes": info.get("processes"),
                        "claude_version": info.get("claude_version")}
        blocked = _activity_blockers(info, f"on {rem.name}")
        if blocked and not args.stop and \
                all(s.get("status") == "idle" for s in info["sessions"]):
            blocked = [b + ", or pass --stop to end it from here" for b in blocked]
        out["blockers"] += blocked
        if info.get("processes") and not args.allow_processes:
            out["blockers"].append(
                f"still running in this folder on {rem.name}: "
                + ", ".join(sorted({f"{p['name']} ({p['pid']})" for p in info["processes"]}))
                + " — stop them, or pass --allow-processes to leave them behind")
        if out["blockers"]:
            return _emit(args, out, lines)

        # three-way, separately for the project and for the history
        store = _store_of(real) or (claude_backend().root() / _key_claude(real))
        rstore = f"{info['claude_home']}/projects/{_key_claude(rem.path(real))}"
        say("comparing both sides …")
        theirs = rem.agent("manifest", timeout=900, trees={
            "project": {"path": rem.path(real), "skip": handover_skip()},
            "history": {"path": rstore, "skip": []}})["trees"]
        ours = {"project": tree_manifest(real),
                "history": tree_manifest(str(store), []) if Path(store).is_dir()
                else tree_manifest(os.devnull, [])}
        plans = {t: three_way(base["here"].get(t) or {}, base["there"].get(t) or {},
                              ours[t]["files"], theirs[t]["files"])
                 for t in ("project", "history")}

        # a transcript must come back as a continuation of what left
        hp = plans["history"]
        check = [k for k in hp["take"] if k in (base.get("transcripts") or {})]
        if check:
            got = rem.agent("hash", timeout=600, files=[
                {"key": k, "path": f"{rstore}/{theirs['history']['raw'].get(k) or k}",
                 "limit": base["transcripts"][k][0]} for k in check])["hashes"]
            for k in check:
                if got.get(k) != base["transcripts"][k][1]:
                    hp["take"].remove(k)
                    hp["conflict"].append(k)
        # the history that returns must be readable here: neither the CLI over
        # there nor anything that wrote into these transcripts may be newer
        mine = find_claude()
        here_ver = claude_version(mine) if mine else None
        tv = lambda v: tuple(int(x) for x in str(v).split("."))
        back = [k for k in hp["take"] + hp["new"] + hp["conflict"] if k.endswith(".jsonl")]
        wrote = rem.agent("written-by", timeout=600, files=[
            {"key": k, "path": f"{rstore}/{theirs['history']['raw'].get(k) or k}",
             "offset": (base.get("transcripts") or {}).get(k, [0])[0]
             if k in hp["take"] else 0} for k in back])["versions"] if back else {}
        seen = [v for v in list(wrote.values()) + [info.get("claude_version")] if v]
        newest = max(seen, key=tv) if seen else None
        out["claude"] = {"here": here_ver, "there": info.get("claude_version"),
                         "wrote_the_history": newest}
        if here_ver and newest and tv(newest) > tv(here_ver):
            msg = (f"Claude Code {newest} was used on {rem.name}, this machine has "
                   f"{here_ver}: an older version may not read the newer history")
            if args.ignore_version:
                out["warnings"].append(msg)
            else:
                out["blockers"].append(msg + " — update Claude Code here first "
                                       "(or pass --ignore-version)")
                return _emit(args, out, lines)
        out["conflicts"] = {t: list(p["conflict"]) for t, p in plans.items()
                            if p["conflict"]}
        if args.prefer == "there":          # theirs win; ours are set aside
            for p in plans.values():
                p["take"] += p["conflict"]
                p["conflict"] = []
        out["plan"] = {t: {k: len(v) for k, v in p.items()} for t, p in plans.items()}
        changed = sum(len(p["take"]) + len(p["new"]) + len(p["delete"]) + len(p["conflict"])
                      for p in plans.values())
        pp = plans["project"]
        lines += [f"{'taking back' if args.apply else 'would take back'}:  {real}"
                  f"  ←  {rem.name}",
                  f"   project   {len(pp['take'])} changed, {len(pp['new'])} new, "
                  f"{len(pp['delete'])} removed there; {len(pp['kept'])} changed only here",
                  f"   history   {len(hp['take'])} continued, {len(hp['new'])} new file(s)"]
        for t, ks in out["conflicts"].items():
            for k in ks[:6]:
                lines.append(f"   ! changed on both sides ({t}): {k}   → "
                             + (f"the version from {rem.name} is taken, ours is set aside"
                                if args.prefer == "there"
                                else "ours stays, theirs is kept next to it"))
        if out["conflicts"] and not args.prefer:
            lines.append(f"     (--prefer there takes the versions from {rem.name} instead)")
        if not args.apply:
            if out.get("would_stop"):
                lines.append(f"   the idle session on {rem.name} would be ended first")
            lines.append("(dry run — pass --apply to do it)")
            return _emit(args, out, lines)

        with ProjectLock(uid):
            try:
                _snapshot_project(uid, entry)
            except Exception as e:
                out["warnings"].append(f"history backup failed: {e}")
            aside = hd / "replaced" / _stamp()
            say(f"fetching the changes from {rem.name} …")
            bdirs = base.get("dirs") or {}
            def made_there(t):                  # folders new there (empty ones too)
                was = set((bdirs.get("here") or {}).get(t) or []) \
                    | set((bdirs.get("there") or {}).get(t) or [])
                return sorted(set(theirs[t].get("dirs") or []) - was
                              - set(ours[t].get("dirs") or []))
            done = {"project": _pull_tree(rem, pp, rem.path(real), real,
                                          theirs["project"]["raw"], aside / "project",
                                          there, False, handover_skip(),
                                          talk and sys.stderr.isatty(),
                                          ours["project"]["files"], made_there("project"))}
            Path(store).mkdir(parents=True, exist_ok=True)
            done["history"] = _pull_tree(rem, hp, rstore, str(store),
                                         theirs["history"]["raw"], aside / "history",
                                         there, True, [], False,
                                         ours["history"]["files"], made_there("history"))
            sids = _sessions_of(store)
            for sub, inc in (("file-history", [f"/{s}/***" for s in sids]),
                             ("plans", _plans_of(store))):
                if inc:
                    (claude_home() / sub).mkdir(parents=True, exist_ok=True)
                    rem.rsync(rem.spec(f"{info['claude_home']}/{sub}/"),
                              str(claude_home() / sub) + "/", include=inc, update=True,
                              backup_dir=str(aside / sub))
            for p in _extras(entry):
                isdir = os.path.isdir(p)
                r = rem.rsync(rem.spec(rem.path(p) + ("/" if isdir else "")),
                              p + ("/" if isdir else ""), update=True,
                              backup_dir=str(aside / "extras" / os.path.basename(p)),
                              skip=handover_skip())
                if not r["ok"]:
                    out["warnings"].append(f"{p} did not come back: {r['error']}")
            out["done"] = done
            if aside.is_dir() and any(f.is_file() or f.is_symlink()
                                      for f in aside.rglob("*")):
                out["set_aside"] = str(aside)
            else:
                shutil.rmtree(aside, ignore_errors=True)
            pd = done["project"]
            # go on where the work stopped: that can be a branch, or a session
            # begun over there, not the one that was sent
            latest = latest_session(store) or away.get("session")
            handed = away.get("session") if away.get("session") != latest else None
            back = {"from": there, "left": away.get("since"), "at": _now(),
                    "session": latest, "handed_over": handed,
                    "updated": pd["updated"],
                    "new": pd["new"], "deleted": pd["deleted"],
                    "conflicts": [c["their_version"] for c in pd["conflicts"]]}
            _update_entry(uid, away=None, returned=back)
            _end_pause(uid, rem.name)       # the two copies agree again
            _retire_manifest(hd)
            prune_set_asides(hd / "replaced")
        out["applied"] = True
        out["session"] = latest
        out["session_title"] = session_title(store, latest)
        out["handed_over_session"] = handed
        out["handed_over_title"] = session_title(store, handed)
        log(f"RECLAIM {real} <- {rem.name} ({changed} change(s), "
            f"{sum(len(d['conflicts']) for d in done.values())} conflict(s))")
        apply_badge(real, desired_marks(real, True))
        notify_user("Taken back", f"{os.path.basename(real)} is on this machine again")
        for t, d in done.items():
            for c in d["conflicts"]:
                lines.append(f"   ! kept both ({t}): {c['file']}  +  {c['their_version']}")
        if out.get("set_aside"):
            lines.append(f"   replaced files are kept in {out['set_aside']}")
        if latest:
            lines.append(f"   continue with:  cd {shlex.quote(real)} && "
                         f"claude --resume {latest}")
        if handed:
            lines.append("      that is the session used last"
                         + (f" (“{out['session_title']}”)" if out["session_title"] else "")
                         + f"; the one you handed over:  claude --resume {handed}")
    except HandoverError as e:
        out["error"] = str(e)
        warn(f"RECLAIM {real}: {e}")
    return _emit(args, out, lines)

# ---- remotes, attaching, status ---------------------------------------------- #

def discover_machines(notes: list = None) -> list:
    """Machines that could be handed over to: the peers of this machine's
    Tailscale network and the hosts named in ~/.ssh/config.  What stood in
    the way goes into `notes` for whoever asked — not into the log: the trays
    ask every few seconds, and a stopped Tailscale is no fault of ours."""
    rows = {}
    notes = [] if notes is None else notes
    ts = _tailscale_exe()
    if ts:
        try:
            r = subprocess.run([ts, "status", "--json"], capture_output=True,
                               text=True, timeout=15, cwd="/", **_NO_WINDOW)
            if not (r.stdout or "").strip():
                raise ValueError(((r.stderr or "").strip().splitlines()
                                  or ["no answer"])[0])
            for p in (json.loads(r.stdout).get("Peer") or {}).values():
                system = str(p.get("OS") or "").lower()
                host = str(p.get("DNSName") or "").split(".")[0] or p.get("HostName")
                if host and system in ("linux", "macos", "freebsd"):
                    rows[host] = {"name": host, "host": host, "system": system,
                                  "online": bool(p.get("Online")), "via": "tailscale"}
        except Exception as e:
            notes.append(f"Tailscale gave no list of machines ({str(e)[:120]}) — "
                         "is it running?")
            log(f"REMOTE discover: tailscale gave no list ({e})", "debug")
    try:
        for line in (Path.home() / ".ssh" / "config").read_text().splitlines():
            m = re.match(r"\s*Host\s+(.+)", line, re.I)
            for h in m.group(1).split() if m else []:
                if not re.search(r"[*?!]", h) and h not in rows:
                    rows[h] = {"name": h, "host": h, "system": None,
                               "online": None, "via": "ssh config"}
    except OSError:
        pass
    known = {str(s.get("ssh") or "").split("@")[-1]: n
             for n, s in remotes_config().items()}
    for r in rows.values():
        r["added_as"] = known.get(r["host"])
    return sorted(rows.values(), key=lambda r: (not r["online"], r["name"].lower()))

_INSTALL = {"apt-get": "sudo apt install -y", "dnf": "sudo dnf install -y",
            "pacman": "sudo pacman -S --needed", "zypper": "sudo zypper install -y",
            "brew": "brew install"}

def remote_checks(rem: Remote, info: dict) -> list:
    """What a machine needs for a handover, each with the command that
    fixes it — to be run ON that machine."""
    tools = info.get("tools") or {}
    rs = find_rsync()
    mine = find_claude()
    home = str(Path.home())
    get = _INSTALL.get(info.get("packages") or "", "install")
    rows = []
    def ck(name, ok, detail, fix=None, needed=True):
        rows.append({"check": name, "ok": bool(ok), "detail": str(detail),
                     "needed": needed, **({"fix": fix} if fix and not ok else {})})
    ck("reachable", True, f"{info.get('host')} ({info.get('system')})")
    ck("rsync on this machine", rs, rs.get("version") or "missing",
       "here:  brew install rsync" if IS_MAC else "here:  install rsync 3")
    ck("rsync there", tools.get("rsync"), tools.get("rsync") or "missing",
       f"{get} rsync")
    ck("tmux there", tools.get("tmux"), tools.get("byobu") or tools.get("tmux")
       or "missing", f"{get} tmux")
    there = rem.agent("probe", path=rem.path(home))
    same = info.get("home") == home or bool(there.get("path_exists"))
    ck(f"{home} exists there", same, "projects keep their path" if same else "missing",
       f'sudo mkdir -p {shlex.quote(home)} && sudo chown "$USER" {shlex.quote(home)}')
    if same and info.get("home") != home:
        shut = not there.get("path_open_to_others")
        ck(f"only you can look into {home} there", shut,
           "yes" if shut else "other accounts on that machine can read your projects",
           f"chmod 700 {shlex.quote(home)}", needed=False)
    ck("Claude Code there", info.get("claude"),
       f"{info.get('claude_version') or 'missing'} "
       f"(here: {claude_version(mine) if mine else 'missing'})",
       "nothing to do: the first handover installs this machine's version"
       if tools.get("curl") else f"{get} curl")
    if info.get("logged_in") is not None:
        ck("Claude Code is logged in there", info["logged_in"],
           "yes" if info["logged_in"] else "no", "run once there:  claude")
    both = tools.get("mosh-server") and find_tool("mosh")
    ck("mosh (a connection that survives network changes)", both,
       "on both" if both else
       ("missing there" if not tools.get("mosh-server") else "missing here"),
       f"{get} mosh" if not tools.get("mosh-server")
       else ("here:  brew install mosh" if IS_MAC else "here:  install mosh"),
       needed=False)
    if both:
        open_ = mosh_usable(rem, test=True)
        where = "in on tailscale0 " if info.get("tailscale_if") else ""
        ck("mosh gets through (UDP 60000–61000)", open_,
           "yes" if open_ else "blocked on the way — ssh is used instead",
           f"sudo ufw allow {where}to any port 60000:61000 proto udp"
           if info.get("firewall") == "ufw"
           else "open UDP ports 60000–61000 in that machine's firewall",
           needed=False)
    return rows

def _remember_system(name: str, system) -> None:
    """remotes.<name>.system: what answered there (Darwin, Linux or Windows)."""
    if not system or (remotes_config().get(name) or {}).get("system") == system:
        return
    with Lock():
        cfg = load_config()
        rs = dict(cfg.get("remotes") or {})
        if name in rs:
            rs[name] = dict(rs[name], system=system)
            cfg["remotes"] = rs
            save_config(cfg)

def cmd_remote(args):
    if not can_reach_machines():
        print("handover needs rsync and ssh; it is not available in this build")
        return 2
    act = args.action or "list"
    if act == "discover":
        notes = []
        rows = discover_machines(notes)
        if args.json:
            print(json.dumps({"machines": rows, "notes": notes}, indent=2))
        else:
            for n in notes:
                print(f"  ! {n}")
            for r in rows:
                state = {True: "online", False: "offline", None: ""}[r["online"]]
                print(f"   {r['name']:<22} {r['system'] or '':<7} {state:<8} "
                      f"{r['via']}" + (f"   (added as {r['added_as']})"
                                       if r["added_as"] else ""))
            print("\nadd one with:  aht remote add <name> <user@host>"
                  if rows else "nothing found — add one with:  "
                  "aht remote add <name> <user@host>")
        return 0
    if act == "add":
        if not (args.name and args.target) or not re.fullmatch(r"[A-Za-z0-9_.-]+", args.name):
            print("usage: aht remote add <name> <user@host>", file=sys.stderr)
            return 2
        spec = {"ssh": args.target}
        if args.sandbox:
            # a test machine: from the first connect on, everything there
            # stays inside this folder, never in that machine's own ~/.aht
            if not args.sandbox.startswith("/"):
                print("--sandbox takes a full path on that machine", file=sys.stderr)
                return 2
            spec["sandbox"] = args.sandbox.rstrip("/")
        rem = Remote(args.name, spec)
        try:
            rem.check_shell()               # before any sh script goes there
            info = rem.connect()
        except HandoverError as e:
            print(f"✗ {e}", file=sys.stderr)
            return 1
        with Lock():
            cfg = load_config()
            rs = dict(cfg.get("remotes") or {})
            rs[args.name] = dict(spec, system=info.get("system"))
            cfg["remotes"] = rs
            cfg.setdefault("default_remote", args.name)
            save_config(cfg)
        print(f"✓ {args.name}: {info.get('host')} ({info.get('system')}), Claude Code "
              f"{info.get('claude_version') or 'not installed'}")
        return 0
    if act in ("remove", "default"):
        with Lock():
            cfg = load_config()
            rs = dict(cfg.get("remotes") or {})
            if args.name not in rs:
                print(f"unknown machine {args.name!r}", file=sys.stderr)
                return 2
            if act == "remove":
                held = [e["real_path"] for e in load_registry()["projects"].values()
                        if (e.get("away") or e.get("handing") or {}).get("remote")
                        == args.name]
                if held:
                    print(f"{args.name} still holds {len(held)} handed-over project(s). "
                          "Take them back first; or, when that machine is gone, release "
                          f"them (the work on {args.name} stays there):\n   "
                          + "\n   ".join(f"aht reclaim {shlex.quote(p)} --release"
                                         for p in held),
                          file=sys.stderr)
                    return 3
                rs.pop(args.name)
                cfg["remotes"] = rs
                if cfg.get("default_remote") == args.name:
                    cfg.pop("default_remote")
            else:
                cfg["default_remote"] = args.name
            save_config(cfg)
        print(f"{'removed' if act == 'remove' else 'default is now'}: {args.name}")
        return 0
    if act == "check":
        names = sorted(remotes_config()) if args.name in (None, "all") and \
            (args.name == "all" or not cfg_get("default_remote")) else [args.name]
        results, code = [], 0
        for n in names:
            rem = None
            try:
                rem = get_remote(n)
                if not rem.system:
                    rem.check_shell()       # set up before aht asked: ask once
                info = rem.connect()
                rows = remote_checks(rem, info)
                results.append({"remote": rem.name, "target": rem.target, "checks": rows,
                                "system": info.get("system"),
                                "ok": all(c["ok"] for c in rows if c["needed"])})
                _remember_system(rem.name, info.get("system"))
            except HandoverError as e:
                results.append({"remote": n, "ok": False, "error": str(e), "checks": [],
                                "system": rem.system if rem else None})
                if rem is not None and rem.system == "Windows":
                    _remember_system(rem.name, "Windows")
                code = 1
        if args.json:
            print(json.dumps({"ok": all(r["ok"] for r in results),
                              "machines": results}, indent=2))
            return code
        for r in results:
            print(f"{r['remote']}" + (f"   {r['target']}" if r.get("target") else ""))
            if r.get("error"):
                print(f"  ✗ {r['error']}")
            for c in r["checks"]:
                mark = "✓" if c["ok"] else ("✗" if c["needed"] else "·")
                print(f"  {mark} {c['check']}   — {c['detail']}")
                if c.get("fix"):
                    print(f"      → {c['fix']}")
        return code
    rs = remotes_config()
    if args.json:
        print(json.dumps({"remotes": rs, "default": cfg_get("default_remote")}, indent=2))
    else:
        for n, s in sorted(rs.items()):
            print(f" {'*' if n == cfg_get('default_remote') else ' '} {n}   {s.get('ssh')}")
        if not rs:
            print("no other machine yet — add one with:  aht remote add <name> <user@host>")
    return 0

def cmd_attach(args):
    """Open the handed-over session: in this terminal, or in a new window."""
    real = os.path.realpath(args.path)
    _uid, entry = _entry_for(load_registry(), real)
    away = (entry or {}).get("away")
    if not away:
        print("this project is not handed over", file=sys.stderr)
        return 2
    try:
        rem = get_remote(away.get("remote"))
        if find_tool("mosh"):
            rem.connect()
    except HandoverError as e:
        print(str(e), file=sys.stderr)
        return 1
    cmd = attach_command(rem, away.get("mux"), away.get("window"))
    if args.print:
        print(" ".join(shlex.quote(a) for a in cmd))
        return 0
    if args.window:
        return open_terminal(" ".join(shlex.quote(a) for a in cmd),
                             f"attach-{away.get('window')}")
    os.execvp(cmd[0], cmd)

TERMINALS = ("iTerm", "Terminal")         # apps that run a .command file they open

def app_installed(name: str) -> bool:
    """Whether macOS knows an app of that name, wherever it is installed
    (/Applications, ~/Applications, an external disk): asks LaunchServices."""
    if "AHT_APPS" in os.environ:                        # tests: a stand-in
        return name in os.environ["AHT_APPS"].split(",")
    if not IS_MAC:
        return False
    try:
        return subprocess.run(["open", "-Ra", name], capture_output=True, timeout=10,
                              cwd="/").returncode == 0
    except Exception:
        return False

def terminal_choice() -> str:
    """The app session windows open in: the one set in terminal_app, else
    iTerm when installed, else Terminal."""
    return cfg_get("terminal_app") or ("iTerm" if app_installed("iTerm") else "Terminal")

def open_terminal(command: str, name: str, cwd: str = None, echo: bool = True) -> int:
    """Run `command` in a new terminal window (the front-ends use this), in
    the folder `cwd` when one is given.  When no window opens, the line to
    run by hand is printed (echo False: the caller tells it) -> 1."""
    full = (cd_then(cwd) if cwd else "") + command
    run = aht_home() / "run"
    run.mkdir(parents=True, exist_ok=True)
    if os.environ.get("AHT_TERMINAL_LOG"):          # tests: note it, open nothing
        with open(os.environ["AHT_TERMINAL_LOG"], "a") as fh:
            fh.write(full + "\n")
        return 0
    if os.environ.get("AHT_NO_TERMINAL"):           # tests: a computer without one
        pass
    elif IS_MAC:
        f = run / (re.sub(r"[^A-Za-z0-9_.-]+", "-", name) + ".command")
        f.write_text("#!/bin/bash\n"
                     'export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"\n'
                     "clear\n" + full + "\n")
        os.chmod(f, 0o755)
        return subprocess.call(["open", "-a", terminal_choice(), str(f)])
    elif os.name == "nt":
        # a console of its own (Windows Terminal when it is the default
        # terminal) that starts in the folder: its path never goes through
        # cmd's parser, where & ^ or %…% in a folder's name would run.
        # /s /k "…": cmd drops the outer quotes and runs the rest as it is
        try:
            subprocess.Popen('cmd.exe /s /k "' + command + '"', cwd=cwd,
                             creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0x10))
            return 0
        except OSError:
            pass
    else:
        sh = ["/bin/sh", "-c", full]
        # how each one takes a command: the words after a flag, or (tilix) one
        # string it splits itself
        for term, argv in (("x-terminal-emulator", ["-e"] + sh), ("gnome-terminal", ["--"] + sh),
                           ("kgx", ["--"] + sh), ("konsole", ["-e"] + sh),
                           ("xfce4-terminal", ["-x"] + sh), ("tilix", ["-e", shlex.join(sh)]),
                           ("terminator", ["-x"] + sh), ("alacritty", ["-e"] + sh),
                           ("kitty", sh), ("foot", sh), ("xterm", ["-e"] + sh)):
            if _have(term):
                # detached from our output: a terminal that keeps it (Ubuntu's
                # x-terminal-emulator is gnome-terminal --wait) would hold up
                # whoever reads it, such as aht's window, until it is closed
                subprocess.Popen([term] + argv,
                                 start_new_session=True, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return 0
    if echo:
        print(full)
    return 1

_SESSION_ID = re.compile(r"[A-Za-z0-9._-]+")

def cmd_resume_here(args):
    """Continue a project's session in a new terminal window: the one used
    last, or (--handed-over) the one the last handover sent away."""
    real = os.path.realpath(args.path)
    _uid, entry = _entry_for(load_registry(), real)
    back = (entry or {}).get("returned") or {}
    other = args.agent and args.agent != "claude"
    if other and not args.session:
        print("name the session with --session", file=sys.stderr)
        return 2
    sid = args.session or latest_session(_store_of(real))
    if args.handed_over and not other:
        sid = back.get("handed_over") or back.get("session") or sid
    if sid and not _SESSION_ID.fullmatch(sid):         # it goes on a command line
        print(f"not a session id: {sid}", file=sys.stderr)
        return 2
    if other:
        line = resume_command(args.agent, sid)
    else:
        line = ("" if os.name == "nt" else "exec ") + shell_quote(find_claude() or "claude") \
            + (" --resume " + shell_quote(sid) if sid else "")
    if args.print:
        print(cd_then(real) + line)
        return 0
    return open_terminal(line, "resume-" + os.path.basename(real), cwd=real)

def handover_status() -> dict:
    reg = load_registry()
    away, mirrored = [], []
    for e in reg.get("projects", {}).values():
        if e.get("away"):
            away.append({"project": e["real_path"], **e["away"]})
        m = e.get("mirror") or {}
        if m.get("enabled"):
            mirrored.append({"project": e["real_path"], "remote": m.get("remote"),
                             "synced_at": m.get("synced_at"), "status": m.get("status"),
                             "paused": m.get("paused")})
    rs = find_rsync() if handover_supported() else {}
    rs_cfg = remotes_config()
    return {"supported": handover_supported(), "can_reach": can_reach_machines(),
            "remotes": rs_cfg,
            "default_remote": cfg_get("default_remote") if cfg_get("default_remote")
            in rs_cfg else (sorted(rs_cfg)[0] if rs_cfg else None),
            "rsync": rs.get("version"), "away": away, "mirrored": mirrored}

def _hook_notes(cwd: str, sid: str = None) -> str:
    """What a session that starts here must know about a handover, a hand-off
    to another agent, or a copy of the folder; the hook hands it to Claude
    Code, which adds it to the session's context."""
    notes = [_handover_note(cwd)]
    try:
        notes += _relay_notes(cwd, sid)
    except Exception as e:
        warn(f"HOOK relay note: {e}")
    notes.append(_copy_note(cwd))
    return "\n\n".join(n for n in notes if n)

def _relay_notes(cwd: str, sid) -> list:
    """What the relays of this folder tell a Claude session that starts:
    (1) the catch-up a Hand Back (or a switch to this session, --resume)
    left for this very session, once; (2) one line when this is the session
    another agent took the work over from, resumed by hand (the catch-up
    itself only with informed_sessions); (3) one line when the work went on
    on another machine."""
    rels = read_relays(cwd)
    if not rels:
        return []
    notes = []
    back = [r for r in rels if sid and r.get("note_for") == sid and r.get("told") is None]
    if back:
        notes.append(_catchup_note(cwd, back[0]))
        for r in back:
            _mark_relay(cwd, r["id"], "told", {"session": sid})
    opens = open_relays(cwd, rels)
    mine = next((r for r in opens if sid and r["from"].get("session") == sid
                 and _relay_here(r["from"])), None)
    if mine and not back:
        cd = catchup_digest(cwd, float(mine["at"]), exclude={("claude", sid)}, most=3)
        to = AGENT_NAMES[mine["to"]["agent"]]
        brief = f".aht/handover/relay-{mine['id']}.md"
        if cd["sessions"]:
            who = _names([x["agent"] for x in cd["sessions"]])
            notes.append(f"[aht] {who} worked on this project after this session's last turn "
                         f"({_span(cd['first_t'], cd['last_t'], '–')}). The files may differ "
                         f"from what you remember: read them before editing. Summary: {brief}")
        else:
            notes.append(f"[aht] This project was handed to {to} at {_clock(mine['at'])}, "
                         "after this session's last turn. The files may differ from what you "
                         f"remember: read them before editing. Summary: {brief}")
    there = next((r for r in opens if not _relay_here(r["to"]) and _known_from(r["from"])), None)
    if there:
        where = there["to"].get("machine") or "another machine"
        notes.append(f"[aht] This project was picked up on “{where}” at {_clock(there['at'])} "
                     f"({AGENT_NAMES[there['to']['agent']]}). Work may go on there: if the "
                     "user asks to continue that work, check with them before changing "
                     "anything here.")
    return notes

def _known_from(end: dict) -> bool:
    """Whether the machine a relay says the work left from is one aht knows:
    this one, or one a handover went to.  A record without a machine id
    cannot tell; it is taken (made safe by read_relays)."""
    mid = end.get("machine_id")
    if not mid or mid == machine_id():
        return True
    try:
        return mid in {(e.get("away") or {}).get("holder_id")
                       for e in load_registry().get("projects", {}).values()}
    except Exception:
        return False

def _catchup_note(cwd: str, r: dict) -> str:
    """A Hand Back's catch-up as the hook gives it: the head of its summary
    (who worked, files and commits since, what is open), at most
    HOOK_NOTE_MAX characters."""
    brief = f".aht/handover/relay-{r['id']}.md"
    try:
        text = (relay_dir(cwd) / f"relay-{r['id']}.md").read_text(encoding="utf-8")
    except OSError:
        text = ""
    head = text.split("\n## ", 1)[0].split("\n", 1)[-1].strip()     # without its title
    tail = f"\nThe full summary: {brief}"
    return "[aht] " + _clip(redact(head) or "Work went on here while this session was "
                            "away.", HOOK_NOTE_MAX - len(tail) - 8) + tail

def _copy_note(cwd: str) -> str:
    """When this folder is a copy aht keeps for another machine
    (~/.aht/remote/copies.json): one line about where it came from."""
    try:
        copies = json.loads((aht_home() / "remote" / "copies.json").read_text())
    except (OSError, ValueError):
        return ""
    c = next((v for k, v in (copies.items() if isinstance(copies, dict) else [])
              if isinstance(v, dict) and isinstance(k, str) and _same_dir(k, cwd)), None)
    if not c:
        return ""
    src = c.get("from") or "another machine"
    if c.get("kind") == "sync":
        return (f"[aht] This folder is a copy kept in sync from “{src}”; changes made here "
                "pause that sync.")
    if c.get("kind") in ("handover", "brought"):
        return f"[aht] This folder was handed over from “{src}”; send it back when done."
    return ""

def _handover_note(cwd: str) -> str:
    """The handover part of the hook's notes: away, unfinished, back."""
    try:
        reg = load_registry()
        uid, entry = _entry_for(reg, cwd)
        if not entry:
            return ""
        a, b, h = entry.get("away"), entry.get("returned"), entry.get("handing")
        if h and not a:
            return (f"[aht] WARNING: a handover of this project to “{h.get('host') or h.get('remote')}” "
                    f"began on {h.get('since')} and did not finish; aht is finding out "
                    "whether the session there runs. Changes made here now can collide "
                    "with work there. Tell the user before changing anything.")
        if a:
            notify_user("Project is handed over",
                        f"{os.path.basename(cwd)} runs on {a.get('host')} — "
                        "take it back before working here")
            return (f"[aht] WARNING: this project was handed over to “{a.get('host')}” on "
                    f"{a.get('since')} and is being worked on there. Changes made here "
                    "now can collide with that work. Tell the user before changing "
                    "anything, and suggest taking the project back first (aht reclaim).")
        if b and not b.get("told") and b.get("released"):
            _update_entry(uid, returned=dict(b, told=True))
            return (f"[aht] This project was handed over to “{b.get('from')}” on "
                    f"{b.get('left')} and released on {b.get('at')}: the work done "
                    "there since then did not come here.")
        if b and not b.get("told"):
            msg = (f"[aht] This project is back on “{_here()}”. It ran on "
                   f"“{b.get('from')}” from {b.get('left')} to {b.get('at')}; the "
                   f"changes made there were brought back ({b.get('updated', 0)} "
                   f"file(s) updated, {b.get('new', 0)} new, {b.get('deleted', 0)} "
                   "removed).")
            if b.get("conflicts"):
                msg += (" Changed on BOTH machines, so both versions were kept: "
                        + ", ".join(b["conflicts"][:8]) + ".")
            _update_entry(uid, returned=dict(b, told=True))
            return msg
    except Exception as e:
        warn(f"HOOK handover note: {e}")
    return ""

# --------------------------------------------------------------------------- #
# Across agents: every agent's sessions, read one way.  Search, the secrets
# check, the journal, switching agent and the session board build on it.
# Readable: Claude Code, Kimi Code 2.x, Codex and Antigravity (agy, behind
# AGY_READER); the other agents keep formats aht does not know yet.
# --------------------------------------------------------------------------- #

AGENT_NAMES = {"claude": "Claude Code", "kimi": "Kimi Code", "codex": "Codex",
               "agy": "Antigravity"}

def _when(v):
    """Seconds since 1970 from an ISO text or a (milli)second number."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit()):
        x = float(v)
        return x / 1000.0 if x > 1e11 else x
    if isinstance(v, str) and len(v) >= 19 and v[4:5] == "-":
        from datetime import datetime
        s = v.replace("Z", "+00:00")
        for cand in (s, re.sub(r"\.\d+", "", s)):
            try:
                return datetime.fromisoformat(cand).timestamp()
            except ValueError:
                continue
    return None

def _stat(p):
    try:
        return os.stat(p)
    except OSError:
        return None

def _target(inp: dict) -> str:
    """What a tool call worked on, for the index, shared pages and the
    journal: masked before it is cut, so a key the cut would split is
    masked whole."""
    for k in ("file_path", "notebook_path", "path", "TargetFile", "target_file",
              "AbsolutePath", "command", "CommandLine", "pattern", "url", "query"):
        v = inp.get(k)
        if isinstance(v, str) and v.strip():
            return _masked(v, 400)
    return ""

def _claude_events(e: dict):
    typ, t = e.get("type"), _when(e.get("timestamp"))
    if typ in ("ai-title", "custom-title"):
        title = e.get("customTitle") or e.get("aiTitle")
        if title:
            yield {"t": t, "role": "title", "text": redact(str(title))}
        return
    m = e.get("message")
    if e.get("isSidechain") or not isinstance(m, dict):
        return
    c = m.get("content")
    if typ == "user":
        if e.get("isCompactSummary"):
            yield {"t": t, "role": "summary", "text": _text_of(c).strip()}
            return
        if e.get("isMeta") or e.get("toolUseResult") is not None:
            return
        if isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "tool_result"
                                       for b in c):
            return
        txt = _text_of(c).strip()
        if txt and not txt.startswith("<"):         # reminders, command echoes
            yield {"t": t, "role": "user", "text": txt}
    elif typ == "assistant" and isinstance(c, list):
        for b in c:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text" and (b.get("text") or "").strip():
                yield {"t": t, "role": "agent", "text": b["text"].strip()}
            elif b.get("type") == "tool_use":
                inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                yield {"t": t, "role": "tool", "tool": b.get("name") or "",
                       "target": _target(inp), "input": inp}

def _kimi_events(e: dict):
    typ, t = e.get("type"), _when(e.get("time"))
    if typ == "turn.prompt":
        if ((e.get("origin") or {}).get("kind") or "user") != "user":
            return
        txt = "\n".join(b.get("text") or "" for b in e.get("input") or []
                        if isinstance(b, dict) and b.get("type") == "text").strip()
        if txt:
            yield {"t": t, "role": "user", "text": txt}
    elif typ == "context.append_loop_event":
        ev = e.get("event") or {}
        if ev.get("type") == "content.part":
            part = ev.get("part") or {}
            if part.get("type") == "text" and (part.get("text") or "").strip():
                yield {"t": t, "role": "agent", "text": part["text"].strip()}
        elif ev.get("type") == "tool.call":
            args = ev.get("args") if isinstance(ev.get("args"), dict) else {}
            yield {"t": t, "role": "tool", "tool": ev.get("name") or "",
                   "target": _target(args), "input": args}

# What the user and the agent said comes from Codex's events only: older
# versions write `user_message` / `agent_message`, 0.164 `item_completed`
# with a UserMessage or AgentMessage.  The `response_item` messages say it
# again, as the model's input and output, among Codex's own instructions and
# the environment: never read, so nothing is there twice.
_CODEX_SAID = {"user_message": "user", "agent_message": "agent",
               "UserMessage": "user", "AgentMessage": "agent"}
_CODEX_INJECTED = ("<environment_context>", "<user_instructions>", "# AGENTS.md instructions")

def _codex_events(e: dict):
    typ, t = e.get("type"), _when(e.get("timestamp"))
    p = e.get("payload") if isinstance(e.get("payload"), dict) else {}
    if typ == "event_msg" and p.get("type") in ("user_message", "agent_message", "item_completed"):
        if p["type"] == "item_completed":
            item = p.get("item") if isinstance(p.get("item"), dict) else {}
            role = _CODEX_SAID.get(item.get("type"))
            txt = "\n".join(c["text"] for c in item.get("content") or []
                            if isinstance(c, dict) and str(c.get("type")).lower() == "text"
                            and isinstance(c.get("text"), str)).strip()
        else:
            role, txt = _CODEX_SAID[p["type"]], str(p.get("message") or "").strip()
        if role and txt and not (role == "user" and txt.startswith(_CODEX_INJECTED)):
            yield {"t": t, "role": role, "text": txt}
    elif typ == "response_item" and p.get("type") in ("function_call", "custom_tool_call"):
        args = p.get("arguments") if p.get("arguments") is not None else p.get("input")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {"command": args}
        args = args if isinstance(args, dict) else {}
        cmd = args.get("command")
        if isinstance(cmd, list):
            args = dict(args, command=" ".join(map(str, cmd)))
        ev = {"t": t, "role": "tool", "tool": p.get("name") or "", "target": _target(args),
              "input": args}
        # a patch names the files it writes: apply_patch as a tool of its
        # own, or run through the shell
        patch = next((v for v in (args.get("command"), args.get("cmd"), args.get("input"))
                      if isinstance(v, str) and "*** Begin Patch" in v), None)
        if patch:
            ev.update(tool="apply_patch", files=_patch_files(patch, args.get("workdir")))
        yield ev

_PATCH_FILE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+?)\s*$|^\*\*\* Move to: (.+?)\s*$",
                         re.M)

def _patch_files(patch: str, workdir=None) -> list:
    """The files a Codex patch adds, changes or removes, as written in it:
    relative ones below `workdir` when the call names one."""
    out = []
    for m in _PATCH_FILE.finditer(patch):
        p = m.group(1) or m.group(2)
        if not _is_abs(p) and isinstance(workdir, str) and _is_abs(workdir):
            sep = "\\" if "\\" in workdir and "/" not in workdir else "/"
            p = workdir.rstrip("/\\") + sep + p
        if p not in out:
            out.append(p)
    return out

# ---- Antigravity (agy) ------------------------------------------------------ #
# agy keeps a SQLite file of conversation summaries and a transcript per
# conversation.  A real conversation (agy 1.4, on a Mac) confirmed the
# summaries table, the folder, title and time, and the transcript's user
# input and replies; tool calls, a step's thinking and the plan files were
# not in it and follow the program's description.  AGY_READER turns the
# reader off again if a later agy changes the format.  As a target of a
# switch agy works either way.  Never read: cli.log (it names the signed-in
# account), history.jsonl (the prompts typed), implicit/ and settings.json.

AGY_READER = True
_AGY_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")       # a conversation's id: a uuid
AGY_STORE = Backend("agy", "Antigravity CLI", "high",
                    lambda: Path.home() / ".gemini" / "antigravity-cli")

def agy_reader_on() -> bool:
    """Whether aht reads agy's own store: AGY_READER, or in the tests a
    stand-in store (AHT_TEST_AGY_READER)."""
    return AGY_READER or os.environ.get("AHT_TEST_AGY_READER") == "1"

def _sqlite_rows(db, table: str, cols) -> list:
    """Rows of one table of another program's SQLite file, as dicts of those
    of `cols` it has.  The file and its -wal and -shm are copied into
    ~/.aht/run and the copy is opened read-only: the program's own file is
    never opened, and what still sits in its WAL is read too.  [] when it
    cannot be read."""
    import sqlite3, tempfile
    db = Path(db)
    if not db.is_file():
        return []
    run = aht_home() / "run"
    run.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="sqlite-", dir=str(run))).resolve()
    con = None
    try:
        for end in ("", "-wal", "-shm"):
            if Path(str(db) + end).is_file():
                shutil.copyfile(str(db) + end, str(tmp / (db.name + end)))
        # a program that closed cleanly leaves a WAL-mode file without its
        # -wal, and SQLite cannot open such a copy with mode=ro alone: with
        # no WAL there is nothing more to read, so the copy opens immutable
        ro = "?mode=ro" if (tmp / (db.name + "-wal")).is_file() else "?mode=ro&immutable=1"
        con = sqlite3.connect((tmp / db.name).as_uri() + ro, uri=True, timeout=5)
        have = [r[1] for r in con.execute(f"pragma table_info({table})")]
        want = [c for c in cols if c in have]
        if not want:
            return []
        return [dict(zip(want, row))
                for row in con.execute(f"select {', '.join(want)} from {table}")]
    except Exception as e:
        warn(f"READ {db.name}: {e}")
        return []
    finally:
        if con is not None:
            con.close()
        shutil.rmtree(tmp, ignore_errors=True)

def _uri_path(u):
    """The folder a file:// URI names, on any system: file:///Users/me/x,
    file:///C:/x and file:///c%3A/x."""
    from urllib.parse import urlparse, unquote
    if not (isinstance(u, str) and u.startswith("file:")):
        return None
    p = unquote(urlparse(u).path)
    return (p[1:] if re.match(r"/[A-Za-z]:", p) else p) or None

def _seconds(v):
    """_when, also for a count of micro- or nanoseconds."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        while v > 1e11:
            v /= 1000.0
        return float(v) if v > 0 else None
    return _when(v)

def _same_dir(p: str, real: str) -> bool:
    if not _is_abs(p):
        return False
    p = p if _DRIVE.match(p) or p.startswith("\\\\") else os.path.realpath(p)
    return _inside(p, real) and _inside(real, p)

def agy_conversations(real: str = None) -> list:
    """agy's conversations (in the folder `real`) the way list_sessions gives
    sessions, from a copy of its conversation_summaries.db.  A subagent's
    conversation is left out.  agy may rewrite a transcript (compaction), so
    its rows say `rewrites`: the index reads them again from the start."""
    if not agy_reader_on():
        return []
    root = AGY_STORE.root()
    out = []
    for r in _sqlite_rows(root / "conversation_summaries.db", "conversation_summaries",
                          ("conversation_id", "title", "last_modified_time",
                           "workspace_uris", "nesting_depth")):
        cid = str(r.get("conversation_id") or "")
        try:
            depth = int(r.get("nesting_depth") or 0)
        except (TypeError, ValueError):
            depth = 0
        if not _AGY_ID.fullmatch(cid) or depth > 0:
            continue
        try:
            uris = json.loads(r.get("workspace_uris") or "[]")
        except (TypeError, ValueError):
            uris = []
        folders = [p for p in map(_uri_path, uris if isinstance(uris, list) else []) if p]
        if real and not any(_same_dir(p, real) for p in folders):
            continue
        f = root / "brain" / cid / ".system_generated" / "logs" / "transcript.jsonl"
        st = _stat(f)
        if st is None:
            continue
        title = r.get("title")
        out.append({"agent": "agy", "id": cid, "project": folders[0] if folders else None,
                    "file": str(f), "title": redact(str(title)) if title else None,
                    "updated": _seconds(r.get("last_modified_time")) or st.st_mtime,
                    "rewrites": True})
    return out

def agy_conversation_exists(cid: str) -> bool:
    """agy opens a NEW conversation for an id it does not know, without a
    word: so aht checks the id first."""
    return bool(agy_reader_on() and _AGY_ID.fullmatch(cid or "")
                and (AGY_STORE.root() / "brain" / cid).is_dir())

def _agy_text(c) -> str:
    """The text of a step: a string, or parts; a part that is thinking is
    never read."""
    if isinstance(c, str):
        return c
    parts = [c] if isinstance(c, dict) else c if isinstance(c, list) else []
    return "\n".join(str(p.get("text") or "") for p in parts
                     if isinstance(p, dict) and not p.get("thought")
                     and p.get("type") not in ("thinking", "thought"))

_AGY_REQUEST = re.compile(r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", re.S)

def _agy_events(e: dict):
    """One step of an agy transcript: what the user typed, the agent's reply
    and its tool calls.  `type` comes with and without its long prefix.
    agy wraps what was typed in <USER_REQUEST> and adds blocks of its own
    (the local time, a changed setting): only the request is the user's."""
    typ = str(e.get("type") or "").upper()
    if typ.startswith("CORTEX_STEP_TYPE_"):
        typ = typ[len("CORTEX_STEP_TYPE_"):]
    t = _seconds(e.get("created_at") or e.get("createdAt"))
    if typ == "USER_INPUT":
        txt = _agy_text(e.get("content")).strip()
        asked = _AGY_REQUEST.findall(txt)
        txt = "\n".join(asked).strip() if asked else txt
        if txt:
            yield {"t": t, "role": "user", "text": txt}
    elif typ == "PLANNER_RESPONSE":
        txt = _agy_text(e.get("content")).strip()
        if txt:
            yield {"t": t, "role": "agent", "text": txt}
        for c in e.get("tool_calls") or []:
            if not isinstance(c, dict):
                continue
            args = c.get("args") if c.get("args") is not None else c.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            args = args if isinstance(args, dict) else {}
            yield {"t": t, "role": "tool", "tool": str(c.get("name") or ""),
                   "target": _target(args), "input": args}

AGY_PLAN_FILES = ("walkthrough.md", "implementation_plan.md", "task.md")
_TASK_LINE = re.compile(r"^\s*[-*] \[( |/)\] (.+?)\s*$", re.M)

def agy_plans(cid: str) -> tuple:
    """(where things stood, open to-dos) from the plan files agy keeps with a
    conversation: its walkthrough, implementation plan and task list."""
    if not (agy_reader_on() and _AGY_ID.fullmatch(cid or "")):
        return None, []
    d = AGY_STORE.root() / "brain" / cid
    parts, todos = [], []
    for name in AGY_PLAN_FILES:
        try:
            text = (d / name).read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if text:
            parts.append(f"### {name}\n\n{text}")
        if name == "task.md":
            todos = [{"content": m.group(2),
                      "status": "in_progress" if m.group(1) == "/" else "pending"}
                     for m in _TASK_LINE.finditer(text)]
    return ("\n\n".join(parts) or None), todos

_EVENTS = {"claude": _claude_events, "kimi": _kimi_events, "codex": _codex_events,
           "agy": _agy_events}

def session_events(agent: str, src, start: int = 0):
    """(end, event) for each message of one session from byte `start` on;
    `src` is a path or an open binary file.  `end` is where the next read
    starts, so an index can pick up what was appended since."""
    parse = _EVENTS[agent]
    fh = open(src, "rb") if isinstance(src, (str, Path)) else src
    try:
        if start:
            fh.seek(start)
        pos = start
        for raw in fh:
            end = pos + len(raw)
            if not raw.endswith(b"\n"):
                break                        # still being written: next time
            pos = end
            try:
                e = json.loads(raw)
            except Exception:
                continue
            if isinstance(e, dict):
                for ev in parse(e):
                    yield end, ev
    finally:
        if isinstance(src, (str, Path)):
            fh.close()

def _store_owners() -> dict:
    owner = {}
    for e in load_registry().get("projects", {}).values():
        s = (e.get("stores") or {}).get("claude")
        if s:
            owner[s] = e["real_path"]
    return owner

def list_sessions(project: str = None, agents=None) -> list:
    """Every session aht can read, newest first:
    {agent, id, project, file, updated[, title, rewrites]}.  `project`
    narrows it to one folder."""
    want = set(agents or AGENT_NAMES)
    real = os.path.realpath(project) if project else None
    out = []
    if "claude" in want:
        root = claude_backend().root()
        if real:
            hit = claude_backend().find(real)
            stores = [(hit[1], real)] if hit else []
        else:
            owner = _store_owners()
            stores = [(d, owner.get(d.name)) for d in (sorted(root.iterdir())
                                                        if root.is_dir() else [])
                      if d.is_dir() and not d.name.startswith(STAGING_PREFIX)]
        for d, proj in stores:
            files = [f for f in d.glob("*.jsonl") if f.is_file()]
            if files and proj is None:
                proj = transcript_cwd(d)
            for f in files:
                st = _stat(f)
                if st:
                    out.append({"agent": "claude", "id": f.stem, "project": proj,
                                "file": str(f), "updated": st.st_mtime})
    b = BY_NAME.get("kimi-code")
    if "kimi" in want and b is not None and b.root().is_dir():
        root = b.root()
        buckets = [root / _key_kimicode(real)] if real else \
            [p for p in root.iterdir() if p.name.startswith("wd_")]
        for bk in buckets:
            for sd in (sorted(bk.iterdir()) if bk.is_dir() else []):
                wire = sd / "agents" / "main" / "wire.jsonl"
                st = _stat(wire)
                if not sd.name.startswith("session_") or st is None:
                    continue
                try:
                    state = json.loads((sd / "state.json").read_text())
                except Exception:
                    state = {}
                if real and os.path.realpath(state.get("cwd") or real) != real:
                    continue
                title = state.get("title")
                out.append({"agent": "kimi", "id": sd.name, "project": state.get("cwd"),
                            "file": str(wire), "title": redact(str(title)) if title else None,
                            "updated": _when(state.get("updatedAt")) or st.st_mtime})
    b = BY_NAME.get("codex")
    if "codex" in want and b is not None and b.available():
        files = b.scan(real) if real else sorted(b.root().rglob("rollout-*.jsonl"))
        for f in files:
            st = _stat(f)
            if st is None:
                continue
            meta = {}
            try:
                with open(f, "rb") as fh:
                    first = json.loads(fh.readline() or b"{}")
                if first.get("type") == "session_meta":
                    meta = first.get("payload") or {}
            except Exception:
                pass
            out.append({"agent": "codex", "id": meta.get("id") or Path(f).stem,
                        "project": meta.get("cwd"), "file": str(f), "updated": st.st_mtime})
    if "agy" in want:
        out += agy_conversations(real)
    out.sort(key=lambda s: s["updated"] or 0, reverse=True)
    return out

def shell_quote(s) -> str:
    """One word for this system's shell: cmd.exe on Windows, sh elsewhere.
    cmd.exe takes & | < > ^ as plain text only inside double quotes, and a
    Windows path cannot hold one."""
    return '"' + str(s).replace('"', "") + '"' if os.name == "nt" else shlex.quote(str(s))

def cd_then(project: str) -> str:
    return f"cd /d {shell_quote(project)} && " if os.name == "nt" \
        else f"cd {shell_quote(project)} && "

def resume_command(agent: str, sid: str, project: str = None) -> str:
    """The line that continues a session: in `project` (it goes there
    first), or with no project the line to run in the session's folder."""
    exe = agent_cli(agent) or agent
    args = {"claude": ["--resume", sid], "kimi": ["-S", sid], "codex": ["resume", sid],
            "agy": ["--conversation", sid]}[agent]
    return (cd_then(project) if project else "") + " ".join(shell_quote(a) for a in [exe] + args)

# ---- search -------------------------------------------------------------------- #

def search_db() -> Path:
    return aht_home() / "search.db"

_SEARCH_SCHEMA = """
create table if not exists files (path text primary key, size integer, mtime real,
    pos integer, agent text, session text);
create table if not exists sessions (key text primary key, agent text, session text,
    project text, title text, started real, updated real, live integer, source text);
create virtual table if not exists msgs using fts5(text, role unindexed,
    agent unindexed, session unindexed, project unindexed, t unindexed,
    file unindexed, tokenize = "unicode61 remove_diacritics 2");
"""
SEARCH_TEXT_MAX = 4000
# an index of an older format is built anew once.  2: tool calls and titles
# are masked whole (an index from before can hold parts of keys).  3: the
# masker's rules changed (rows it masked wrongly come back, more kinds go)
SEARCH_FORMAT = 3

def _open_search_db():
    import sqlite3
    aht_home().mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(search_db()), timeout=60)
    db.executescript(_SEARCH_SCHEMA)
    return db

def _index_events(db, agent, sid, project, file, events) -> tuple:
    """Put a run of session events into the index -> (end, title, first, last)."""
    end, title, first, last = None, None, None, None
    rows = []
    for end, ev in events:
        if ev.get("t"):
            first = first or ev["t"]
            last = ev["t"]
        if ev["role"] == "title":
            title = ev["text"]
            continue
        if ev["role"] == "tool":
            text = f"{ev.get('tool')}: {ev.get('target') or ''}".strip()
        else:
            text = ev.get("text") or ""
        text = _redact_head(text, SEARCH_TEXT_MAX)[:SEARCH_TEXT_MAX]   # the index holds no keys
        if text:
            rows.append((text[:SEARCH_TEXT_MAX], ev["role"], agent, sid, project or "",
                         ev.get("t"), file))
        if len(rows) >= 500:
            db.executemany("insert into msgs values (?,?,?,?,?,?,?)", rows)
            rows = []
    if rows:
        db.executemany("insert into msgs values (?,?,?,?,?,?,?)", rows)
    return end, title, first, last

def _note_session(db, agent, sid, project, title, first, last, live, source):
    key = f"{agent}:{sid}"
    old = db.execute("select title, started, updated from sessions where key = ?",
                     (key,)).fetchone()
    if old:
        title = title or old[0]
        first = min(x for x in (first, old[1]) if x) if (first or old[1]) else None
        last = max(x for x in (last, old[2]) if x) if (last or old[2]) else None
    db.execute("insert or replace into sessions values (?,?,?,?,?,?,?,?,?)",
               (key, agent, sid, project or "", redact(title or ""), first, last, live,
                source))

def update_search_index(progress=None) -> dict:
    """Bring the index up to date: what live sessions appended since the last
    run, sessions that are new, and sessions that now exist only in history
    backups.  A session whose file is gone stays searchable, except across
    a rebuild: an index of an older format is built anew from the files and
    backups there are."""
    import zipfile
    lock = open(str(search_db()) + ".lock", "w") if aht_home().is_dir() else None
    if lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
    db = _open_search_db()
    stats = {"sessions": 0, "files_read": 0, "from_backups": 0, "rebuilt": False}
    try:
        if db.execute("pragma user_version").fetchone()[0] < SEARCH_FORMAT:
            # marked done only at the end, so a run cut short starts over.
            # The old file goes: that needs no room, and nothing of the old
            # rows stays.  Where it cannot go (Windows, while a search reads
            # it) its tables are dropped and vacuum clears the file
            db.close()
            try:
                for end in ("-journal", "-wal", "-shm", ""):    # the database last
                    Path(str(search_db()) + end).unlink(missing_ok=True)
                db = _open_search_db()
            except OSError:
                db = _open_search_db()
                db.executescript("drop table if exists msgs; drop table if exists files; "
                                 "drop table if exists sessions;" + _SEARCH_SCHEMA)
                db.execute("vacuum")
            # updated now: the watcher and the hook start no other update
            # while this one builds it
            db.execute("insert or replace into files values (?,?,?,?,?,?)",
                       ("@updated", 0, time.time(), 0, "", ""))
            db.commit()
            stats["rebuilt"] = True
        live = list_sessions()
        live_keys = {f"{s['agent']}:{s['id']}" for s in live}
        known = {r[0]: r[1:] for r in db.execute("select path, size, mtime, pos from files")}
        todo = []
        for s in live:
            st = _stat(s["file"])
            if st is None:
                continue
            k = known.get(s["file"])
            if k and k[0] == st.st_size and abs(k[1] - st.st_mtime) < 1e-6:
                continue
            todo.append((s, st))
        for i, (s, st) in enumerate(todo):
            if progress:
                progress(i, len(todo))
            k = known.get(s["file"])
            start = k[2] if k and st.st_size >= k[0] and k[2] <= st.st_size \
                and not s.get("rewrites") else 0           # agy may rewrite its file
            if start == 0 and k:
                db.execute("delete from msgs where file = ?", (s["file"],))
            end, title, first, last = _index_events(
                db, s["agent"], s["id"], s.get("project"), s["file"],
                session_events(s["agent"], s["file"], start))
            _note_session(db, s["agent"], s["id"], s.get("project"),
                          title or s.get("title"), first, last or s["updated"], 1, s["file"])
            db.execute("insert or replace into files values (?,?,?,?,?,?)",
                       (s["file"], st.st_size, st.st_mtime, end or start, s["agent"], s["id"]))
            stats["files_read"] += 1
            db.commit()
        # sessions whose file is gone: still in the index, now marked so
        db.execute("create temp table if not exists live_now (key text primary key)")
        db.execute("delete from live_now")
        db.executemany("insert or ignore into live_now values (?)",
                       [(k,) for k in live_keys])
        gone = {r[0] for r in db.execute("select key from sessions where live = 1 and key "
                                         "not in (select key from live_now)")}
        db.execute("update sessions set live = 0 where live = 1 and key not in "
                   "(select key from live_now)")
        unplaced = gone | {r[0] for r in db.execute(
            "select key from sessions where live = 0 and source not like '%.zip'")}
        # what only the backups still hold (newest snapshot first)
        root = backups_root()
        have = {r[0] for r in db.execute("select key from sessions")} - unplaced
        owners = load_registry().get("projects", {})
        member = re.compile(r"^(claude)/([^/]+)\.jsonl$|"
                            r"^(kimi-code)/(session_[^/]+)/agents/main/wire\.jsonl$")
        for zp in sorted(root.glob("*/*.zip"), reverse=True) if root.is_dir() else []:
            st = _stat(zp)
            k = known.get(str(zp))
            if st is None or (k and abs(k[1] - st.st_mtime) < 1e-6 and not unplaced):
                continue
            uid = zp.parent.name
            try:
                meta = json.loads(zp.with_suffix(".meta.json").read_text())
            except Exception:
                meta = {}
            project = (owners.get(uid) or {}).get("real_path") or meta.get("real_path")
            try:
                zf = zipfile.ZipFile(zp)
            except Exception:
                continue
            with zf:
                for name in zf.namelist():
                    m = member.match(name)
                    if not m:
                        continue
                    agent = "claude" if m.group(1) else "kimi"
                    sid = m.group(2) or m.group(4)
                    key = f"{agent}:{sid}"
                    if key in have or key in live_keys:
                        continue
                    have.add(key)
                    if key in unplaced:          # its text is indexed; it needs a home
                        db.execute("update sessions set source = ? where key = ?",
                                   (str(zp), key))
                        unplaced.discard(key)
                        stats["from_backups"] += 1
                        continue
                    with zf.open(name) as fh:
                        _e, title, first, last = _index_events(
                            db, agent, sid, project, str(zp), session_events(agent, fh))
                    _note_session(db, agent, sid, project, title, first, last, 0, str(zp))
                    stats["from_backups"] += 1
            db.execute("insert or replace into files values (?,?,?,?,?,?)",
                       (str(zp), st.st_size, st.st_mtime, 0, "backup", uid))
            db.commit()
        stats["sessions"] = db.execute("select count(*) from sessions").fetchone()[0]
        db.execute("insert or replace into files values (?,?,?,?,?,?)",
                   ("@updated", 0, time.time(), 0, "", ""))
        db.execute(f"pragma user_version = {SEARCH_FORMAT}")
        db.commit()
    finally:
        db.close()
        if lock:
            fcntl.flock(lock, fcntl.LOCK_UN)
            lock.close()
    return stats

def _fts_query(q: str) -> str:
    """Words as the user typed them -> an FTS5 query: every word must occur,
    "quoted phrases" stay phrases, the last word may be the start of one."""
    parts = re.findall(r'"([^"]+)"|(\S+)', q)
    terms = []
    for i, (phrase, word) in enumerate(parts):
        w = (phrase or word).replace('"', '""')
        if not w.strip():
            continue
        last = i == len(parts) - 1 and not phrase
        terms.append(f'"{w}"' + ("*" if last and len(w) >= 2 else ""))
    return " ".join(terms)

HIT_OPEN, HIT_CLOSE = "\x02", "\x03"

def search_history(q: str, project: str = None, agent: str = None,
                   limit: int = 20) -> list:
    """Sessions matching `q`, best first, with the best places in them."""
    fq = _fts_query(q)
    if not fq or not search_db().exists():
        return []
    db = _open_search_db()
    try:
        sql = ("select session, agent, project, role, t, snippet(msgs, 0, ?, ?, '…', 14), "
               "bm25(msgs) from msgs where msgs match ?")
        args = [HIT_OPEN, HIT_CLOSE, fq]
        if project:
            sql += " and project = ?"
            args.append(os.path.realpath(project))
        if agent:
            sql += " and agent = ?"
            args.append(agent)
        sql += " order by bm25(msgs) limit 600"
        try:
            rows = db.execute(sql, args).fetchall()
        except Exception as e:
            raise ValueError(f"the search words could not be understood ({e})")
        found, order = {}, []
        for sid, ag, proj, role, t, snip, rank in rows:
            key = f"{ag}:{sid}"
            if key not in found:
                if len(order) >= limit:
                    continue
                found[key] = {"agent": ag, "session": sid, "project": proj or None,
                              "rank": rank, "hits": []}
                order.append(key)
            if len(found[key]["hits"]) < 3 and \
                    snip not in [h["snippet"] for h in found[key]["hits"]]:
                found[key]["hits"].append({"role": role, "t": t, "snippet": snip})
        out = []
        for key in order:
            r = found[key]
            meta = db.execute("select title, started, updated, live, source from sessions "
                              "where key = ?", (key,)).fetchone() or ("", None, None, 1, "")
            r.update(title=redact(meta[0]) if meta[0] else None, started=meta[1],
                     updated=meta[2], live=bool(meta[3]), source=meta[4])
            proj = r["project"]
            if r["live"] and proj and os.path.isdir(proj):
                r["resume"] = resume_command(r["agent"], r["session"], proj)
            elif not r["live"] and str(r["source"]).endswith(".zip"):
                zp = Path(r["source"])
                r["restore"] = {"uuid": zp.parent.name, "stamp": zp.stem,
                                "project": proj if proj and os.path.isdir(proj) else None}
            out.append(r)
        return out
    finally:
        db.close()

def _search_age() -> float:
    try:
        import sqlite3
        db = sqlite3.connect(str(search_db()))
        row = db.execute("select mtime from files where path = '@updated'").fetchone()
        db.close()
        return time.time() - (row[0] if row else 0)
    except Exception:
        return float("inf")

def _spawn_search_update() -> None:
    """From the watcher and the hook: keep the index fresh, detached."""
    try:
        if os.environ.get("AHT_NO_SEARCH_INDEX") or _search_age() < 600:
            return
        if aht_home().is_dir():
            # an update that runs now (a rebuild takes minutes) brings the
            # index up to date: no other one waits for it
            with open(str(search_db()) + ".lock", "a") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    return
                fcntl.flock(lock, fcntl.LOCK_UN)
        me = [sys.executable] if getattr(sys, "frozen", False) else \
            [sys.executable or "python3", str(Path(__file__).resolve())]
        subprocess.Popen(me + ["search", "--update", "--quiet"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True,
                         start_new_session=True, cwd="/")
    except Exception:
        pass

def _when_text(t) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t)) if t else "?"

def cmd_search(args):
    q = " ".join(args.words or []).strip()
    if args.rebuild:
        try:
            for end in ("-journal", "-wal", "-shm", ""):          # the database last
                Path(str(search_db()) + end).unlink(missing_ok=True)
        except OSError:
            # Windows, while a search reads it: an older format to the
            # update below, which then empties the file
            db = _open_search_db()
            db.execute("pragma user_version = 0")
            db.commit()
            db.close()
    if args.update or args.rebuild or not args.no_update:
        talk = sys.stderr.isatty() and not args.json and not args.quiet
        def progress(i, n):
            if talk and n > 20 and i % 10 == 0:
                sys.stderr.write(f"\rindexing {i}/{n} session file(s)…")
                sys.stderr.flush()
        stats = update_search_index(progress)
        if talk:
            sys.stderr.write("\r" + " " * 50 + "\r")
        if not q:
            if args.json:
                print(json.dumps({"index": stats}, indent=2))
            elif not args.quiet:
                print(f"index up to date: {stats['sessions']} session(s), "
                      f"{stats['files_read']} file(s) read now, "
                      f"{stats['from_backups']} only in backups")
            return 0
    if not q:
        print("usage: aht search <words…>   (\"a phrase\" in quotes; --project, --agent)",
              file=sys.stderr)
        return 2
    try:
        rows = search_history(q, args.project, args.agent, args.limit)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"query": q, "results": rows}, indent=2))
        return 0
    bold = ("\033[1m", "\033[0m") if sys.stdout.isatty() else ("[", "]")
    for r in rows:
        where = r["project"] or "?"
        print(f"{AGENT_NAMES.get(r['agent'], r['agent'])} · {_when_text(r['updated'])} · "
              f"{r['title'] or r['session']}")
        print(f"   {where}" + ("" if r["live"] else "   (deleted — it lives on in a backup)"))
        for h in r["hits"]:
            s = h["snippet"].replace("\n", " ").replace(HIT_OPEN, bold[0]).replace(HIT_CLOSE, bold[1])
            print(f"   {h['role']:>5}: {s}")
        if r.get("resume"):
            print(f"   → {r['resume']}")
        elif r.get("restore") and r["restore"]["project"]:
            rs = r["restore"]
            print(f"   → aht restore {shlex.quote(rs['project'])} --uuid {rs['uuid']} "
                  f"--stamp {rs['stamp']} --apply")
        print()
    if not rows:
        print("nothing found")
    return 0

# ---- secrets ------------------------------------------------------------------- #

_SPAN = 1 << 16                 # a find runs on for at most 64 KB

def _secret_patterns() -> list:
    """(kind, needles, pattern, generic, at).  A pattern only runs from its
    needles, so gigabytes of history take seconds: an `at` one starts at its
    needle, any other near it (160 bytes before to 480 after), and a find
    runs on from there for up to 64 KB.  A generic one finds its needles in
    the lower-cased text and keeps its value in a group whose name starts
    with v (its opening quote in q with the same ending, a name in n);
    _plausible decides.  Each pattern reads a text one way only, so no line
    makes it backtrack for long.  Built from pieces, so this file does not
    itself look like it holds a key."""
    k = lambda *parts: "".join(parts).encode()
    rx = lambda *parts: re.compile(k(*parts))
    pk = "PRIV" + "ATE KEY"
    # where a known kind of token starts: not inside a word, but after an
    # escaped line break or tab (a history's raw line)
    b = r"(?:(?<![A-Za-z0-9_])|(?<=\\[nrt]))"
    # in a JSON string: anything but its closing quote (an escaped one too)
    js = r"(?:[^\"\\]|\\[\s\S])"
    # a value: in quotes (escaped ones too: JSON inside JSON), up to the same
    # quote, a space or a backslash; without, up to a space, a quote, a
    # backslash, , ; < > ` or =, or an & a parameter follows (&page=2)
    value = lambda x: (
        r"(?:\\*(?P<q{0}>[\"']))?(?P<v{0}>(?(q{0})(?:(?!(?P=q{0}))[^\s\\])+"
        r"|(?:[^\s\"'\\,;<>`&=]|&(?![A-Za-z_][\w.\-]*=))+={{0,2}}))".format(x))
    op = r"\\*[\"']?\s*(?:=>|:=|=|:(?!:))\s*"                    # not ::
    # a name with a word in it that may say it holds a secret; _secret_name
    # reads the whole name (the part before the needle too)
    name = (r"(?P<n>(?i:pass(?:word|wd|phrase)?|pwd|secret|token|credentials?|auth|pat|key)"
            r"(?![a-z])[A-Za-z0-9_.\-]{0,60})")
    # where no name=value stands: Authorization with any scheme, a flag and
    # its value (--password X, --with-token X), an XML element or setting
    # (<password>X</password>, key="…Password" value="X")
    authz = (r"(?i:authorization\\*[\"']?\s*[:=]\s*\\*[\"']?"
             r"(?:(?!bearer\s|basic\s)[a-z][\w\-]{0,20}\s+)?(?P<va>[a-z0-9\-._~+/=]{16,}))")
    flag = (r"(?:(?<=--)(?i:pass(?:word|wd)?|token|secret)|(?<=--with-|--auth-)token"
            r"|(?<=--access-)token|(?<=--api-)key)\s+")
    xml = r"(?<=<)(?i:(?P<t>pass(?:word|wd)?|secret|token)>(?P<vx>[^<\s\"'\\]{8,})</(?P=t)>)"
    setting = (r"(?i:(?:pass(?:word|wd)?|secret|token|key)\\*\"\s+value=\\*\""
               r"(?P<vs>[^\s\"\\]{8,}))")
    return [
        ("Anthropic API key", [k("sk-", "ant-")], rx("sk-", "ant-", r"[A-Za-z0-9_\-]{20,}"),
         False, True),
        ("OpenAI API key", [k("sk-")], rx(r"sk-(?!", "ant-", r")(?:proj-|svcacct-)?",
                                          r"[A-Za-z0-9_\-]{32,}"), False, True),
        ("Groq API key", [k("gs", "k_")], rx(b, r"gs", r"k_[A-Za-z0-9]{40,}"), False, True),
        # (a short needle: fewer passes over the text, each a few ms)
        ("GitHub token", [k("g", "h"), k("github_", "pat_")],
         rx(r"(?:gh", r"[pousr]_[A-Za-z0-9]{36,}|github_", r"pat_[A-Za-z0-9_]{50,})"),
         False, True),
        ("GitLab token", [k("g", "l")],
         rx(b, r"gl(?:", r"pat|rt|dt|ptt)-[A-Za-z0-9_\-]{20,}"), False, True),
        ("AWS access key", [k("AK", "IA"), k("AS", "IA")],
         rx(b, r"(?:AK", r"IA|AS", r"IA)[0-9A-Z]{16,}\b"), False, True),
        ("Google API key", [k("AI", "za")], rx("AI", r"za[0-9A-Za-z_\-]{35,}"), False, True),
        ("Google OAuth token", [k("ya", "29.")], rx(b, r"ya", r"29\.[0-9A-Za-z_\-]{20,}"),
         False, True),
        ("Slack token", [k("xo", "x")], rx("xo", r"x[abprs]-[0-9A-Za-z\-]{10,}"), False, True),
        # a webhook's address names it; only its last part is the secret
        ("Slack webhook", [k("hooks.sl", "ack.com/services/")],
         rx(r"hooks\.sl", r"ack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/(?P<v>[A-Za-z0-9]{24})"),
         False, True),
        ("Stripe key", [k("sk_li", "ve_"), k("rk_li", "ve_")],
         rx(r"(?:sk|rk)_", r"live_[0-9A-Za-z]{20,}"), False, True),
        ("SendGrid key", [k("S", "G.")],
         rx(b, r"S", r"G\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{40,}"), False, True),
        ("Hugging Face token", [k("hf", "_")], rx(b, r"hf_", r"[A-Za-z0-9]{30,}"), False, True),
        ("npm token", [k("npm", "_")], rx(b, r"npm_", r"[A-Za-z0-9]{36,}\b"), False, True),
        ("PyPI token", [k("pypi-", "AgEI")], rx(b, r"pypi-", r"AgEI[A-Za-z0-9_\-]{50,}"),
         False, True),
        ("age key", [k("AGE-SEC", "RET-KEY-1")], rx(r"AGE-SEC", r"RET-KEY-1[0-9A-Z]{58}"),
         False, True),
        ("Vault token", [k("hv", "s.")], rx(b, r"hv", r"s\.[A-Za-z0-9_\-]{24,}"), False, True),
        ("DigitalOcean token", [k("dop", "_v1_")], rx(b, r"dop", r"_v1_[0-9a-f]{64}"),
         False, True),
        ("Shopify token", [k("sh", "p")], rx(b, r"sh", r"p(?:at|ss|ca|pa)_[0-9a-fA-F]{32}"),
         False, True),
        ("Docker Hub token", [k("dckr", "_pat_")], rx(b, r"dckr", r"_pat_[A-Za-z0-9_\-]{27,}"),
         False, True),
        ("Atlassian token", [k("ATA", "TT3")], rx(b, r"ATA", r"TT3[A-Za-z0-9_\-=]{100,}"),
         False, True),
        ("Telegram bot token", [k("api.tele", "gram.org/bot")],
         rx(r"api\.tele", r"gram\.org/bot\d+:(?P<v>[A-Za-z0-9_\-]{35})"), False, True),
        ("Tailscale key", [k("tsk", "ey-")], rx("tskey", r"-[A-Za-z0-9\-]{20,}"), False, True),
        # from its BEGIN line to its END line, whatever stands between (line
        # numbers, > or # before each line), but never past the end of a
        # JSON string; cut off before its END, to the end of the string
        ("private key", [k(pk)],
         rx(r"-*BEGIN (?P<t>(?:[A-Z0-9]+ ){0,3})", pk, r"(?P<b>(?: BLOCK)?)-----",
            r"(?:%s{0,%d}?-----END (?P=t)" % (js, _SPAN), pk, r"(?P=b)-----|%s*)" % js),
         False, False),
        # a PuTTY key file, to its Private-MAC line (cut off: as far as it goes)
        ("private key", [k("PuTTY-User-", "Key-File-")],
         rx(r"PuTTY-User-", r"Key-File-\d+: [^\s\"\\]+",
            r"(?:%s{0,%d}?Private-(?:MAC|Hash): [0-9A-Fa-f]+|%s*)" % (js, _SPAN, js)),
         False, True),
        # a key in base64 (kubeconfig's client-key-data, a secret's tls.key),
        # also wrapped (base64's lines of 76, each ending its line):
        # _plausible decodes its head
        ("private key", [k("LS0tLS1CRUdJ", "Ti")],
         rx(r"(?:(?<![A-Za-z0-9+/])|(?<=\\[nrt]))LS0tLS1CRUdJ", r"Ti[A-Za-z0-9+/]*={0,2}",
            r"(?:(?:\r?\n|\\+n)[A-Za-z0-9+/]{12,}={0,2}(?=\r?\n|\\+[nr]|[\"']|\Z))*"),
         False, True),
        # header and payload are enough: it runs on to its signature, if any
        ("JSON web token", [k("ey", "J")], rx(r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ",
                                              r"[A-Za-z0-9_\-]{10,}(?:\.[A-Za-z0-9_\-]*)?"),
         False, True),
        # any host: a name, one word (a container's), an IPv4 or [IPv6]
        # address; the password runs to the last @ a host follows
        ("password in a web address", [k(":/", "/")], rx(
            r"(?i)(?<=[a-z0-9])://[^\s:/@\"'\\]{0,64}:(?P<v>[^\s:/\"'\\<>]{4,})@",
            r"(?:\[[0-9a-f:.]+\]|[a-z0-9_][a-z0-9_.\-]*)"), True, True),
        # Go's form of it: user:password@tcp(host:3306)/db
        ("password in a web address", [k("@tc", "p("), k("@uni", "x(")], rx(
            r"(?i)(?:(?<![^\s\"'=:/\\])|(?<=\\[nrt]))[^\s:@/\"'\\]{1,64}:",
            r"(?P<v>[^\s\"'\\@]{4,})@(?:tcp|unix|udp)\("), True, False),
        ("password or token", [k("pa", "ss"), k("pw", "d"), k("sec", "ret"), k("tok", "en"),
                               k("au", "th"), k("credent", "ial"), k("ke", "y"), k("pa", "t")],
         rx(name, op, value(""), r"|", authz, r"|", xml, r"|", setting, r"|", flag, value("f"),
            r"|(?<=ssh)(?i:pass\s+-p)\s*", value("p")), True, True),
        ("password or token", [k("bear", "er")],
         rx(b, r"(?i:bear", r"er)\s+(?P<v>[A-Za-z0-9\-._~+/]{16,}=*)"), True, True),
        ("password or token", [k("bas", "ic")],
         rx(b, r"(?i:bas", r"ic)\s+(?P<v>(?:[A-Za-z0-9+/]{4}){3,}",
            r"(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?)(?![A-Za-z0-9+/=])"), True, True),
        # a password on a command line: mysql -pX, docker login and twine -p X,
        # redis-cli -a X, and in curl's -u or --user the part after the colon
        # (sshpass -p X: with the names above)
        ("password or token", [k("mys", "ql"), k("maria", "db"), k("docker", " login"),
                               k("twi", "ne"), k("redis", "-cli")],
         rx(r"(?i)(?:(?:mysql(?:dump|admin)?|mariadb)\b[^\n|;&]{0,200}?\s(?-i:-p)(?=\S)",
            r"|(?:docker login|twine)\b[^\n|;&]{0,200}?\s(?:-p\s*|--password(?:=|\s+))",
            r"|redis-cli\b[^\n|;&]{0,200}?\s-a\s+)", value("")), True, True),
        ("password or token", [k("cu", "rl")],
         rx(r"(?i)curl\b[^\n|;&]{0,300}?\s(?:-u\s*|--user(?:=|\s+))\\*[\"']?[^\s:\"'\\]{1,64}:",
            r"(?P<v>[^\s\"'\\]{4,})"), True, True),
    ]

# a placeholder by its whole shape (${DB_PASSWORD}, $(cat f), %(pw)s,
# %{DB_PASSWORD}, #{ENV[…]}, $env:X, $__file{…}, <token>, {{ secret }}), or
# by a part no key has (xxxx, ..., a %(name)s, your, example, os.environ)
_PLACEHOLDER = re.compile(r"(?i)^\$\{?\w+\}?$|^\$[{(]|^%\(?\w*\)?[sdr]$|^%\w+%$|^%\{|^#\{"
                          r"|^\$env:\w+$|^\$__\w+\{|^<[^>]*>$|^\{\{|x{4,}|\*{3,}|\.{3}|…"
                          r"|%\(\w+\)[sdr]|your|example|changeme|redacted|placeholder|dummy|sample"
                          r"|process\.env|os\.environ|getenv|env\(|secrets\.")
_TRAIL = re.compile(rb"(?:\.{3,}|\xe2\x80\xa6)+$")         # "..." or "…" after a value
_PEM64 = "LS0tLS1CRUdJ" + "Ti"                            # "-----BEGIN " in base64
# a name's word that says its value is a secret, or a key's (api_key,
# SecretAccessKey); words after it that say the value is something else
# (TOKEN_URL, password_hash), and words before it that say the same of
# a token (NextToken, nextPageToken, IdempotencyToken)
_SECRET_WORD = re.compile(r"(?:password|passwd|passphrase|pwd|secret|token|credentials?|apikey"
                          r"|(?:api|access|private|app|master|encryption|signing|hmac|jwt|account"
                          r"|shared|secret|client)key)$|^(?:pass|auth|pat)$")
_KEY_OF = {"api", "access", "private", "app", "master", "encryption", "signing", "hmac", "jwt",
           "account", "shared", "secret", "client"}
_NOT_AFTER = set("url uri urls endpoint host hostname server service provider issuer domain dir"
                 " file files path name names type kind id ids size len length lens count limit"
                 " max min ttl expiry expires expiration expire lifetime timeout age header"
                 " headers prefix suffix field fields regex pattern format usage used budget hash"
                 " hashed digest checksum fingerprint sha md5 number num idx index arn env var"
                 " version required reset hint label note policy rule rules scope scopes method"
                 " mode flow pool cache store manager callback redirect audience prompt".split())
_NOT_BEFORE = set("next page continuation pagination cursor idempotency sync resume request max"
                  " min num total input output completion reasoning".split())
_ROOT = re.compile(r"/(?:Applications|Library|System|Users|Volumes|app|bin|boot|data|dev|etc"
                   r"|home|lib|lib64|mnt|nix|opt|private|proc|root|run|sbin|snap|srv|sys|tmp"
                   r"|usr|var|workspaces?)(?:/|$)")
_CHAIN = re.compile(r"[!&*]*[A-Za-z_$][\w$]*(?:(?:\.|::|->|\?\.|!\.)[A-Za-z_$][\w$]*)+")
_CALL = re.compile(r"[!&*]*([A-Za-z_$][\w$]*)[(\[]")

def _entropy(s: str) -> float:
    import math
    n = len(s)
    return -sum(c / n * math.log2(c / n) for c in (s.count(x) for x in set(s)))

def _secret_name(name: str) -> bool:
    """A name that says its value is a secret (DB_PASSWORD, x-api-key,
    PGPASSWORD, SecretAccessKey, auth.pass), unless a word after that one
    or before it says otherwise (password_hash, NextToken)."""
    words = [w.lower() for w in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", name)]
    last = -1
    for i, w in enumerate(words):
        if _SECRET_WORD.search(w) or (w == "key" and i and words[i - 1] in _KEY_OF):
            last = i
    return (last >= 0 and not _NOT_AFTER & set(words[last + 1:])
            and not _NOT_BEFORE & set(words[:last]))

def _a_name(v: str) -> bool:
    """Reads as a name, not as something generated: its words three letters
    long or more on average, two runs of digits at most (base64Decode,
    MAX_RETRIES, oauth2-client; not x7Kp2QmZ9vB4nL8w)."""
    words = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])", v)
    return (bool(words) and sum(map(len, words)) >= 3 * len(words)
            and len(re.findall(r"\d+", v)) <= 2)

def _randomish(part: str) -> bool:
    """A part that looks generated: 8 characters or more, letters and
    digits, small and capital letters mixed or three digits or more."""
    return (len(part) >= 8 and any(c.isdigit() for c in part) and any(c.isalpha() for c in part)
            and ((any(c.islower() for c in part) and any(c.isupper() for c in part))
                 or sum(c.isdigit() for c in part) >= 3))

def _named(v: str) -> bool:
    """A name: a version or an image's tag (1.4.2-alpine3.18), or one name
    made of words (MAX_RETRIES, refreshToken, my-app-secrets), with vowels
    as words have them (not aiiLZXwsyyKeVkz); hex (a UUID) is not."""
    if re.fullmatch(r"v?\d+(?:\.\d+)+(?:[-+_.][0-9A-Za-z][0-9A-Za-z.\-]*)?", v):
        return True
    letters = [c for c in v.lower() if c.isalpha()]
    return (not re.fullmatch(r"[0-9a-fA-F\-]+", v)
            and bool(re.fullmatch(r"[A-Za-z_$][\w$.\-]*", v)) and _a_name(v)
            and sum(c in "aeiou" for c in letters) >= 0.3 * len(letters))

def _path(v: str) -> bool:
    """A path or a reference: from ~/, ./, ../ or a folder every system has
    (/etc/ssl/private/server.key); or with a / or a scheme (op://vault/item,
    vault:kv/db#password, config/service-account.json, a web address with
    no password) when no part of it looks generated."""
    if re.match(r"~/|\.\.?/", v) or _ROOT.match(v):
        return True
    if "/" not in v and not re.match(r"[a-z][a-z0-9+.\-]*:", v):
        return False
    return not any(_randomish(p) for p in re.split(r"[/:#?&=.@,]+", v))

def _code(v: str) -> bool:
    """Code: a value that starts with a bracket or =; a chain of names
    (req.body.password, SecretKey::from_slice) with no part that looks
    generated; a name called or indexed (hash(pw), useAuth()!)."""
    if v[0] in "([{)]}=:":
        return True
    m = _CHAIN.match(v)
    if m and not any(_randomish(p) for p in re.split(r"[^\w$]+", m.group())):
        return True
    m = _CALL.match(v)
    return bool(m) and _a_name(m.group(1))

def _text(v: str) -> bool:
    """Words, not a key: two letters or more of a language other than
    English (generated keys are ASCII), a tokenizer's piece of a word
    (ĠInternational, ▁the)."""
    return (sum(ord(c) > 127 and c.isalpha() for c in v) >= 2
            or bool(re.match(r"[ĠĊ▁][^\W\d_]", v)))

def _material(value: str) -> bool:
    """A private key's find holds key material, not only its BEGIN and END
    lines: 32 characters of base64 or more in a row, with a digit, + or /
    among them; in base64 itself, a key."""
    if value.startswith(_PEM64):
        import base64
        head = re.sub(r"[^A-Za-z0-9+/]", "", value)[:96]
        try:
            return ("PRIV" + "ATE KEY").encode() in base64.b64decode(head[:len(head) // 4 * 4])
        except ValueError:
            return False
    body = value.lstrip("-").split("-----", 1)[-1] if value.lstrip("-").startswith("BEGIN ") \
        else re.split(r"[\s\\]", value, 1)[-1]
    return any(re.search(r"[0-9+/]", r) for r in re.findall(r"[A-Za-z0-9+/=]{32,}", body))

def _plausible(kind: str, value: str, lead: str = None, rest: str = "") -> bool:
    """Whether a find is a secret.  A private key holds key material.  A
    value after a name: the name says it holds a secret, and the value is
    random, not a placeholder, a name, a path, code or words.  `lead` is a
    quote before the name (with its backslashes), `rest` the name up to the
    value; None when no name stands before the value."""
    if kind == "private key":
        return _material(value)
    if kind not in ("password or token", "password in a web address"):
        return True
    if lead is not None:
        nm = re.match(r"[A-Za-z0-9_.\-]*", rest).group()
        if nm.startswith(".") or not _secret_name(nm):
            return False        # not a secret's name, or a CSS class (.x-token:hover)
        if (lead and rest.endswith(lead) and not rest[:-len(lead)].endswith("\\")
                and lead[-1] not in rest[:-len(lead)]):
            return False        # "token="+t: that quote closes the string the name is in
    if "\\u" in value:                    # what JSON escapes (é in café) reads as itself
        value = re.sub(r"\\+u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), value)
    if len(set(value)) < 7 or _PLACEHOLDER.search(value):
        return False
    if kind == "password or token" and len(value) < 8:
        return False            # (token = 1*tchar, a grammar's rule)
    if kind == "password in a web address":
        return _entropy(value) >= 2.8
    if _named(value) or _path(value) or _code(value) or _text(value):
        return False
    # what people and tools generate is random; words and dates are not.  A
    # short value is too short for its entropy to say (12 characters reach
    # 3.5 only when no two are the same), so three kinds of character do
    if len(value) <= 16 and (any(c.islower() for c in value) + any(c.isupper() for c in value)
                             + any(c.isdigit() for c in value)
                             + any(not c.isalnum() and c not in "_-." for c in value)) >= 3:
        return True
    h = value.replace("-", "")
    if re.fullmatch(r"(?=.*\d)(?:(?=.*[a-f])[0-9a-f]{16,}|(?=.*[A-F])[0-9A-F]{16,})", h):
        return _entropy(h) >= 3.0       # hex (a UUID too): at most 4 bits a character, not 6
    return _entropy(value) >= 3.5

def _mask(value: str) -> str:
    if value.lstrip("-").startswith("BEGIN "):
        return value.lstrip("-").split("-----")[0]     # the header only: no key material
    if value.startswith("PuTTY-User-"):
        return value.split(":")[0]
    if value.startswith(_PEM64):
        import base64
        head = re.sub(r"[^A-Za-z0-9+/]", "", value)[:96]
        try:
            text = base64.b64decode(head[:len(head) // 4 * 4]).decode("ascii", "replace")
        except ValueError:
            text = ""
        return text.strip("-").split("-----")[0] + " (in base64)"
    return (value[:4] + "…" + value[-2:]) if len(value) > 10 else value[:2] + "…"

def _fingerprint(value: str) -> str:
    """What names a find: a private key by its lines alone, so the copy a
    Read tool shows with line numbers is the same find as the file's."""
    if value.lstrip("-").startswith(("BEGIN ", "PuTTY-User-", _PEM64)):
        value = re.sub(r"\d+(?:\t|\\+t|→|\\+u2192)|\\+[nrt]|\\+u2192|→|\s", "", value)
    return hashlib.sha256(value.encode()).hexdigest()[:16]

def _where_in(line: bytes, agent: str) -> tuple:
    """(when, what kind of message) of the transcript line holding a find."""
    try:
        e = json.loads(line)
    except Exception:
        return None, "history"
    if agent == "claude":
        t = _when(e.get("timestamp"))
        if e.get("toolUseResult") is not None:
            return t, "tool output"
        if e.get("type") == "user":
            return t, "your message"
        c = (e.get("message") or {}).get("content") if isinstance(e.get("message"), dict) else None
        if isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "tool_use" for b in c):
            return t, "command or file the agent wrote"
        return t, "agent reply"
    if agent == "kimi":
        ev = (e.get("event") or {}).get("type")
        return _when(e.get("time")), {"tool.call": "command or file the agent wrote",
                                      "tool.result": "tool output",
                                      "content.part": "agent reply"}.get(
            ev, "your message" if e.get("type") == "turn.prompt" else "history")
    return _when(e.get("timestamp")), "history"

_NAME_CH = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-"

def _trimmed(v: bytes) -> bytes:
    """A value without what ends the sentence or the code after it: "...",
    "…", a full stop, a closing bracket it did not open (f(token=X))."""
    v = _TRAIL.sub(b"", v)
    pair = {b")": b"(", b"]": b"[", b"}": b"{"}
    while v and (v[-1:] == b"." or (v[-1:] in pair and v.count(v[-1:]) > v.count(pair[v[-1:]]))):
        v = v[:-1]
    return v

def _scan_bytes(data: bytes, pats: list):
    """(kind, start, end, value) of every plausible find in one history file.
    A find inside one found before (a generic one inside a known kind of
    key, a key inside a longer one) is that one: not found twice, and a
    needle inside a find, or inside the last match of its own pattern, is
    not looked at again (so a run of needles costs no more than one)."""
    import bisect
    lower = None
    seen = set()
    starts, ends = [], []           # the known keys found, joined where they overlap
    def inside(a0, b0):
        j = bisect.bisect_right(starts, a0) - 1
        return j >= 0 and b0 <= ends[j]
    n = len(data)
    for kind, needles, rx, generic, at in pats:
        if generic and lower is None:
            lower = data.lower()                  # same length: offsets carry over
        hay = lower if generic else data          # needles in it, patterns on the text
        for nd in needles:
            i, done = hay.find(nd), 0
            while i >= 0:
                if i < done or inside(i, i + len(nd)):
                    i = hay.find(nd, i + len(nd))
                    continue
                if at:
                    m = rx.match(data, i, i + _SPAN)
                    found = [m] if m else ()
                else:                           # a long one runs on past the window
                    end = i + 480
                    found = [rx.match(data, m.start(), m.start() + _SPAN) or m if end < n else m
                             for m in rx.finditer(data, max(0, i - 160), end)]
                if found:
                    done = max([done] + [m.end() for m in found])
                for m in found:
                    g = next((g for g in m.re.groupindex if g[0] == "v" and m.start(g) >= 0),
                             None)
                    a0, b0 = m.span(g) if g else m.span()
                    ctx = ()
                    if generic:
                        q = "q" + g[1:] if g else ""
                        if not (q in m.re.groupindex and m.start(q) >= 0):
                            b0 = a0 + len(_trimmed(data[a0:b0]))    # not in quotes
                        if "n" in m.re.groupindex and m.start("n") >= 0:
                            # the whole name: back over its letters, up to an
                            # escaped line break or tab (\nDB_PASSWORD=); and a
                            # quote before it, with the backslashes before that
                            s = m.start("n")
                            while (s > 0 and m.start("n") - s < 60 and data[s - 1:s] in _NAME_CH
                                   and not (data[s - 2:s - 1] == b"\\" and data[s - 1:s] in b"nrt")):
                                s -= 1
                            c = s - 1 if data[s - 1:s] in (b'"', b"'") else s
                            while 0 < c < s and data[c - 1:c] == b"\\":
                                c -= 1
                            ctx = (data[c:s].decode("utf-8", "replace"),
                                   data[s:a0].decode("utf-8", "replace"))
                    span = (a0, b0)
                    if a0 == b0 or span in seen or inside(a0, b0):
                        continue
                    seen.add(span)
                    value = data[a0:b0].decode("utf-8", "replace")
                    if _plausible(kind, value, *ctx):
                        if not generic:
                            j = bisect.bisect_left(ends, a0)
                            k = bisect.bisect_right(starts, b0)
                            if j < k:
                                a0, b0 = min(a0, starts[j]), max(b0, ends[k - 1])
                            starts[j:k], ends[j:k] = [a0], [b0]
                            a0, b0 = span
                        yield kind, a0, b0, value
                i = hay.find(nd, i + len(nd))

_PATS = []

def redact(text: str) -> str:
    """`text` with every key, token or password in it masked — for whatever
    aht copies out of a history: the search index, the journal, summaries."""
    if not text:
        return text
    if not _PATS:
        _PATS.extend(_secret_patterns())
    data = text.encode("utf-8", "replace")
    generic = {kind for kind, _n, _rx, g, _at in _PATS if g}
    # finds that overlap are masked as one, from the first start to the last
    # end, so no part of a key stays; a known kind of key names it
    spans = []
    for a0, b0, kind in sorted((a0, -b0, kind) for kind, a0, b0, _v in _scan_bytes(data, _PATS)):
        b0 = -b0
        if spans and a0 < spans[-1][1]:
            last = spans[-1]
            last[1] = max(last[1], b0)
            if last[2] in generic and kind not in generic:
                last[2] = kind
        else:
            spans.append([a0, b0, kind])
    if not spans:
        return text
    out, pos = [], 0
    for a0, b0, kind in spans:
        value = data[a0:b0].decode("utf-8", "replace")
        out += [data[pos:a0], f"[{kind}: {_mask(value)}]".encode()]
        pos = b0
    out.append(data[pos:])
    return b"".join(out).decode("utf-8", "replace")

def _redact_head(text: str, n: int) -> str:
    """`text` with every key masked, for a caller that keeps only its first
    `n` characters: masked before the cut, so a key the cut would split is
    masked whole (only a text over a megabyte is cut first, well past `n`)."""
    text = text or ""
    return redact(text if len(text) <= 1 << 20 else text[:n + 4096])

def _masked(text: str, n: int) -> str:
    """_clip(text, n), every key in it masked first."""
    return _clip(_redact_head(text, n), n)

def scan_secrets(project: str = None, sessions: list = None) -> list:
    """Everything in the agents' histories that looks like a key, a token or
    a password.  Values are only ever returned masked."""
    pats = _secret_patterns()
    finds = {}
    for s in sessions if sessions is not None else list_sessions(project):
        try:
            data = Path(s["file"]).read_bytes()
        except OSError:
            continue
        for kind, a0, b0, value in _scan_bytes(data, pats):
            digest = _fingerprint(value)
            key = (s["agent"], s["id"], digest)
            if key in finds:
                finds[key]["times"] += 1
                continue
            a = data.rfind(b"\n", 0, a0) + 1
            b = data.find(b"\n", b0)
            t, where = _where_in(data[a:b if b >= 0 else len(data)], s["agent"])
            finds[key] = {"project": s.get("project"), "agent": s["agent"],
                          "session": s["id"], "kind": kind, "masked": _mask(value),
                          "fingerprint": digest, "where": where, "t": t, "times": 1}
    out = list(finds.values())
    out.sort(key=lambda f: (f["project"] or "", -(f["t"] or 0)))
    return out

def cmd_secrets(args):
    real = os.path.realpath(args.path) if args.path else None
    if real and not os.path.isdir(real):
        print(f"not a folder: {real}", file=sys.stderr)
        return 2
    if args.redact:
        res = redact_in_histories(args.redact, real, args.apply)
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            for b in res["blockers"]:
                print(f"  ✗ {b}")
            print(f"{'removed from' if res['applied'] else 'would remove from'} "
                  f"{res['places'] - res.get('left', 0)} place(s) in {res['files']} history file(s)"
                  + (f"; the originals are kept in {res['kept']}" if res.get("kept") else "")
                  + ("" if res["applied"] or res["blockers"] else
                     " (dry run — pass --apply to do it)"))
            if res.get("left"):
                print(f"{res['left']} place(s) left as they were: taking them out would have "
                      f"broken the history file")
            if res["applied"]:
                print("history backups and copies on other machines still hold it; "
                      "replace the key where it was issued")
        return 3 if res["blockers"] else 0
    talk = sys.stderr.isatty() and not args.json
    if talk:
        sys.stderr.write("reading the histories…\r")
    finds = scan_secrets(real)
    if talk:
        sys.stderr.write(" " * 30 + "\r")
    if args.json:
        print(json.dumps({"project": real, "finds": finds}, indent=2))
        return 0
    if not finds:
        print("nothing that looks like a key, a token or a password"
              + (" in this project's histories" if real else " in any history"))
        return 0
    last = None
    for f in finds:
        if f["project"] != last:
            last = f["project"]
            print(f"\n{last or '(folder unknown)'}")
        print(f"   {f['kind']:<26} {f['masked']:<12} {f['where']}, "
              f"{AGENT_NAMES.get(f['agent'], f['agent'])} {_when_text(f['t'])}"
              + (f"  ({f['times']}×)" if f["times"] > 1 else ""))
    print(f"\n{len(finds)} find(s).  They are in the agents' own history files; aht "
          "never changes those.  Replace a key that was exposed at its source.")
    return 0

# ---- journal ------------------------------------------------------------------- #

_CHANGE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit", "StrReplaceFile",
                 "WriteFile", "apply_patch", "write_to_file", "replace_file_content",
                 "multi_replace_file_content"}

def build_journal(project: str, days: int = None) -> dict:
    """A dated diary of a project from every agent's sessions: what was
    asked, which files changed, and how each day's work ended."""
    real = os.path.realpath(project)
    since = time.time() - days * 86400 if days else None
    per_day = {}
    for s in list_sessions(real):
        title = s.get("title")
        for _end, ev in session_events(s["agent"], s["file"]):
            if ev["role"] == "title":
                title = ev["text"]
                continue
            t = ev.get("t")
            if not t or (since and t < since):
                continue
            day = time.strftime("%Y-%m-%d", time.localtime(t))
            d = per_day.setdefault(day, {}).setdefault(
                (s["agent"], s["id"]), {"agent": s["agent"], "id": s["id"], "first": t,
                                        "last": t, "asked": [], "changed": [],
                                        "commands": 0, "outcome": ""})
            d["first"], d["last"] = min(d["first"], t), max(d["last"], t)
            if ev["role"] == "user":
                # masked whole before its first line is taken and cut
                line = (_redact_head(ev["text"].strip(), 200).splitlines() or [""])[0][:200]
                if line and line not in d["asked"]:
                    d["asked"].append(line)
            elif ev["role"] == "agent":
                d["outcome"] = ev["text"]
            elif ev["role"] == "tool":
                tgt = ev.get("target") or ""
                if ev.get("tool") in _CHANGE_TOOLS and _is_abs(tgt) and _inside(tgt, real):
                    rel = os.path.relpath(tgt, real)
                    if rel not in d["changed"]:
                        d["changed"].append(rel)
                elif ev.get("tool") in ("Bash", "Shell", "shell", "exec_command"):
                    d["commands"] += 1
        for day in per_day.values():
            if (s["agent"], s["id"]) in day:
                day[(s["agent"], s["id"])]["title"] = title
    name = os.path.basename(real)
    L = [f"# Journal: {name}", "",
         f"`{real}` — from the agents' own histories, {time.strftime('%Y-%m-%d %H:%M')}.",
         "Newest day first."]
    for day in sorted(per_day, reverse=True):
        L += ["", f"## {time.strftime('%A, %d %B %Y', time.strptime(day, '%Y-%m-%d'))}"]
        for d in sorted(per_day[day].values(), key=lambda d: d["first"]):
            span = (time.strftime("%H:%M", time.localtime(d["first"])) + "–"
                    + time.strftime("%H:%M", time.localtime(d["last"])))
            L += ["", f"### {span} · {AGENT_NAMES.get(d['agent'], d['agent'])} · "
                      f"{_masked(d.get('title') or d['id'], 90)}"]
            if d["asked"]:
                L += ["", "Asked:"] + [f"- {a}" for a in d["asked"][:12]]
                if len(d["asked"]) > 12:
                    L.append(f"- … and {len(d['asked']) - 12} more")
            if d["changed"]:
                L += ["", "Changed: " + ", ".join(f"`{c}`" for c in d["changed"][:20])
                      + (f" and {len(d['changed']) - 20} more" if len(d["changed"]) > 20 else "")]
            if d["commands"]:
                L += ["", f"Ran {d['commands']} command(s)."]
            if d["outcome"]:
                L += ["", "Where it ended: " + _masked(" ".join(d["outcome"].split()), 400)]
    if not per_day:
        L += ["", "No agent session of this project could be read."]
    return {"project": real, "days": len(per_day), "markdown": "\n".join(L) + "\n"}

def cmd_journal(args):
    real = os.path.realpath(args.path)
    if not os.path.isdir(real):
        print(f"not a folder: {real}", file=sys.stderr)
        return 2
    j = build_journal(real, args.days)
    if args.write:
        out = Path(real) / ".aht" / "journal"
        out.mkdir(parents=True, exist_ok=True)
        (out / ".gitignore").write_text("*\n")      # it quotes the conversations
        (out / "journal.md").write_text(j["markdown"], encoding="utf-8")
        j["file"] = str(out / "journal.md")
    if args.json:
        print(json.dumps(j, indent=2))
    elif args.write:
        print(f"written: {j['file']}  ({j['days']} day(s))")
    else:
        print(j["markdown"])
    return 0

# ---- one set of project rules -------------------------------------------------- #

CLAUDE_RULE_FILES = ("CLAUDE.md", ".claude/CLAUDE.md")
RULES_IMPORT = "@AGENTS.md"
RULES_READERS = {        # which instruction file each agent reads in a project
    "claude": "CLAUDE.md, .claude/CLAUDE.md or CLAUDE.local.md — AGENTS.md only when "
              "none of those exists",
    "kimi": "AGENTS.md", "codex": "AGENTS.md", "opencode": "AGENTS.md",
    "cursor": "AGENTS.md", "copilot": "AGENTS.md", "gemini": "GEMINI.md",
    "agy": "AGENTS.md and GEMINI.md, also .agents/rules/"}

def _imports_agents(text: str) -> bool:
    return any(l.strip() in (RULES_IMPORT, "@./AGENTS.md") for l in text.splitlines())

def rules_status(project: str) -> dict:
    real = os.path.realpath(project)
    files = {}
    for name in ("AGENTS.md",) + CLAUDE_RULE_FILES + ("CLAUDE.local.md", "GEMINI.md"):
        p = Path(real) / name
        if p.is_file():
            text = p.read_text(errors="replace")
            files[name] = {"bytes": len(text.encode()), "imports_agents": _imports_agents(text),
                           "sha": hashlib.sha256(text.strip().encode()).hexdigest()[:12]}
    claude_file = next((n for n in CLAUDE_RULE_FILES if n in files), None)
    agents = files.get("AGENTS.md")
    if not files:
        state, say = "none", "no instruction file: every agent starts without project rules"
    elif claude_file and not agents:
        state, say = "claude-only", (f"only {claude_file}: Claude follows it; Kimi, Codex and "
                                     "the others see no project rules")
    elif agents and not claude_file:
        state, say = "one", ("AGENTS.md is the one set of rules; Claude reads it too "
                             "(Claude Code 2.1.277 or later)")
    elif files[claude_file]["imports_agents"]:
        state, say = "one", (f"AGENTS.md is the one set of rules; {claude_file} brings it "
                             f"in with {RULES_IMPORT}")
    elif files[claude_file]["sha"] == agents["sha"]:
        state, say = "twins", (f"{claude_file} and AGENTS.md are copies of each other — "
                               "they drift apart as soon as one is edited")
    else:
        state, say = "split", (f"{claude_file} and AGENTS.md differ, and Claude reads only "
                               f"{claude_file}: the agents follow different rules")
    if "GEMINI.md" in files and not files["GEMINI.md"]["imports_agents"] and agents:
        say += "; GEMINI.md is separate"
    uid, entry = _entry_for(load_registry(), real)
    used = agents_of((entry or {}).get("stores") or {})
    return {"project": real, "files": files, "state": state, "summary": say,
            "claude_file": claude_file, "agents_used": used,
            "readers": {a: RULES_READERS[a] for a in RULES_READERS
                        if a in used or a in SWITCH_TARGETS}}

def unify_rules(project: str, prefer: str = None, apply: bool = False) -> dict:
    """Make AGENTS.md the one set of rules: Claude's file then only imports it.
    What each file held before is kept in ~/.aht/rules-backups first."""
    st = rules_status(project)
    real, files = st["project"], st["files"]
    cf = st["claude_file"]
    res = {"project": real, "state": st["state"], "applied": False, "changes": []}
    if st["state"] in ("none", "one"):
        res["nothing_to_do"] = True
        return res
    agents_p = Path(real) / "AGENTS.md"
    claude_p = Path(real) / cf
    claude_text = claude_p.read_text(errors="replace")
    agents_text = agents_p.read_text(errors="replace") if "AGENTS.md" in files else None
    if st["state"] == "split" and prefer not in ("claude", "agents", "both"):
        res["needs_choice"] = True
        res["choices"] = {"claude": f"keep what {cf} says", "agents": "keep what AGENTS.md says",
                          "both": f"keep both: {cf} is added to the end of AGENTS.md"}
        return res
    if agents_text is None or prefer == "claude":
        new_agents = claude_text
    elif prefer == "both":
        new_agents = (agents_text.rstrip() + f"\n\n## More rules (moved here from {cf})\n\n"
                      + claude_text.strip() + "\n")
    else:
        new_agents = agents_text
    new_claude = RULES_IMPORT + "\n"
    if new_agents != agents_text:
        res["changes"].append({"file": "AGENTS.md", "now": "the shared rules"
                               + (" (new)" if agents_text is None else "")})
    res["changes"].append({"file": cf, "now": f"only the line {RULES_IMPORT}"})
    if not apply:
        return res
    uid, _entry = _entry_for(load_registry(), real)
    base = aht_home() / "rules-backups" / (uid or _key_claude(real))
    keep, n = base / _stamp(), 2
    while keep.exists():                        # never write over an earlier backup
        keep, n = base / f"{_stamp()}-{n}", n + 1
    keep.mkdir(parents=True)
    for name in ("AGENTS.md", cf):
        src = Path(real) / name
        if src.is_file():
            (keep / name.replace("/", "_")).write_bytes(src.read_bytes())
    for p, text in ((agents_p, new_agents), (claude_p, new_claude)):
        tmp = p.with_name(p.name + ".aht-new")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, p)
    res.update(applied=True, backup=str(keep))
    log(f"RULES {real}: AGENTS.md is the one set of rules ({st['state']}, prefer={prefer})")
    return res

def cmd_rules(args):
    real = os.path.realpath(args.path)
    if not os.path.isdir(real):
        print(f"not a folder: {real}", file=sys.stderr)
        return 2
    if args.unify:
        res = unify_rules(real, args.prefer, args.apply)
        if args.json:
            print(json.dumps(res, indent=2))
            return 3 if res.get("needs_choice") else 0
        if res.get("nothing_to_do"):
            print("nothing to do: " + rules_status(real)["summary"])
            return 0
        if res.get("needs_choice"):
            print("CLAUDE.md and AGENTS.md say different things. Choose what the one set "
                  "of rules should hold:")
            for k, v in res["choices"].items():
                print(f"   --prefer {k:<7} {v}")
            return 3
        for c in res["changes"]:
            print(f"   {c['file']:<18} → {c['now']}")
        print("done; the old files are kept in " + res["backup"] if res["applied"]
              else "(dry run — pass --apply to do it)")
        return 0
    st = rules_status(real)
    if args.json:
        print(json.dumps(st, indent=2))
        return 0
    print(st["summary"])
    for name, f in st["files"].items():
        print(f"   {name:<18} {f['bytes']} bytes" + (f"  (imports {RULES_IMPORT})"
                                                     if f["imports_agents"] else ""))
    if st["state"] in ("claude-only", "twins", "split"):
        print("\nmake AGENTS.md the one set of rules:  aht rules "
              f"{shlex.quote(real)} --unify --apply")
    return 0

# ---- switch agent ---------------------------------------------------------------- #

SWITCH_TARGETS = ("claude", "kimi", "codex", "agy")

def agent_cli(agent: str):
    if os.environ.get(f"AHT_CLI_{agent.upper()}"):     # tests: a stand-in CLI
        return os.environ[f"AHT_CLI_{agent.upper()}"]
    if agent == "claude":
        return find_claude()
    if agent == "kimi":
        own = Path.home() / ".kimi-code/bin/kimi"
        return find_tool("kimi") or (str(own) if own.exists() else None)
    return find_tool(agent) if agent in ("codex", "agy") else None

def _note_file(seen: list, p: str) -> None:
    """Each file once, the most recent last."""
    if p in seen:
        seen.remove(p)
    seen.append(p)

def events_digest(s: dict, project: str, turns: int = 8, tail: int = None,
                  since: float = None) -> dict:
    """session_digest for any agent's session."""
    if s["agent"] == "claude":
        return session_digest(s["file"], project, turns, tail, since)
    d = {"title": s.get("title"), "summary": None, "exchanges": [], "todos": [],
         "touched": [], "outside": [], "version": None, "count": 0, "requests": [],
         "first_t": None, "last_t": None}
    cur = None
    home = str(Path.home())
    start = 0
    if tail:
        st = _stat(s["file"])
        start = max(0, st.st_size - tail) if st else 0
    for _end, ev in session_events(s["agent"], s["file"], start):
        new = not since or (ev.get("t") or 0) >= since
        if ev["role"] == "user":
            cur = None
            if new:
                cur = {"you": ev["text"], "agent": "", "t": ev.get("t")}
                d["exchanges"].append(cur)
                del d["exchanges"][:-turns]
                _count_exchange(d, ev["text"], ev.get("t"))
        elif ev["role"] == "agent" and cur is not None:
            cur["agent"] = ev["text"]
            d["last_t"] = ev.get("t") or d["last_t"]
        elif ev["role"] == "tool":
            inp = ev.get("input") or {}
            if ev.get("tool") in ("TodoList", "TodoWrite"):
                todos = inp.get("todos")
                if isinstance(todos, list):
                    d["todos"] = [x for x in todos if isinstance(x, dict)
                                  and x.get("status") not in ("completed", "done")]
            elif ev.get("tool") == "update_plan" and isinstance(inp.get("plan"), list):
                d["todos"] = [{"content": x.get("step"), "status": x.get("status")}
                              for x in inp["plan"] if isinstance(x, dict) and x.get("step")
                              and x.get("status") != "completed"]       # Codex's plan
            if not new:
                continue
            for f in ev.get("files") or [ev.get("target") or ""]:
                if not _is_abs(f):
                    if ev.get("files"):             # a patch's own name, in the project
                        _note_file(d["touched"], f)
                elif _inside(f, project):
                    if ev.get("tool") in _CHANGE_TOOLS:
                        _note_file(d["touched"], _rel_to(f, project))
                elif f.startswith(home) and not f.startswith((home + "/.",)):
                    _note_file(d["outside"], f)
    if s["agent"] == "agy":                 # its own plan files say where it stood
        d["summary"], todos = agy_plans(s["id"])
        d["todos"] = todos or d["todos"]
    d["touched"], d["outside"] = d["touched"][-15:], d["outside"][-15:]
    return d

def _brief_sections(dig: dict, times: bool = False) -> list:
    """The body of a handover or switch summary.  Whatever looks like a key
    is masked: the summary is a new file, and a key must not spread.
    `times`: each exchange says when it was."""
    L = []
    if dig.get("summary"):
        L += ["", "## Where things stood", "", _masked(dig["summary"], 8000)]
    if dig.get("exchanges"):
        L += ["", "## The latest exchanges"]
        for x in dig["exchanges"]:
            at = f" ({_clock(x['t'])})" if times and x.get("t") else ""
            L += ["", f"**You{at}:** " + _masked(x["you"], 1500)]
            if x.get("agent"):
                L += ["", "**Agent:** " + _masked(x["agent"], 2500)]
    if dig.get("todos"):
        L += ["", "## Open to-do items", ""]
        L += [f"- [ ] {_masked(_todo_text(x), 200)}"
              + ("  *(in progress)*" if x.get("status") == "in_progress" else "")
              for x in dig["todos"]]
    if dig.get("touched"):
        L += ["", "## Files changed most recently", ""]
        L += [f"- `{redact(p)}`" for p in reversed(dig["touched"])]
    return L

def _todo_text(x: dict) -> str:
    return str(x.get("content") or x.get("subject") or x.get("title") or "")

# ---- git, as a summary tells it ------------------------------------------- #

def _git(real: str, *args):
    """One git command in the folder `real`: it never asks for a password,
    never takes a lock and never fetches.  Its output, or None."""
    try:
        r = subprocess.run(["git", "-C", real, "--no-optional-locks", *args],
                           capture_output=True, encoding="utf-8", errors="replace",
                           timeout=15, cwd="/", **_NO_WINDOW,
                           env=dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0"))
    except Exception:
        return None
    return r.stdout if r.returncode == 0 else None

_HEAD = re.compile(r"[0-9a-f]{7,64}")

def git_state(real: str, since_head: str = None, since: float = None):
    """The git state of the project at `real`: branch, HEAD and its subject,
    ahead of and behind its upstream, the uncommitted files (up to 30) and
    how many are untracked.  With `since_head` (or only `since`, a time):
    also the files changed since that commit, untracked ones made since,
    and the commits since (up to 30).  Commit subjects and file names are
    masked.  None when the folder holds no repository or git is missing."""
    if not is_git(real):
        return None
    out = _git(real, "status", "--porcelain=v1", "-z", "--branch")
    if out is None:
        return None
    st = {"branch": None, "upstream": None, "ahead": 0, "behind": 0, "head": None,
          "head_full": None, "subject": None, "dirty": 0, "files": [], "untracked": 0}
    untracked = []
    recs = out.split("\0")
    i = 0
    while i < len(recs):
        rec, i = recs[i], i + 1
        if rec.startswith("## "):
            h = rec[3:]
            info = re.search(r" \[([^\]]*)\]$", h)
            if info:
                h = h[:info.start()]
                for part in info.group(1).split(", "):
                    k, _sp, n = part.partition(" ")
                    if k in ("ahead", "behind") and n.isdigit():
                        st[k] = int(n)
            for pre in ("No commits yet on ", "Initial commit on "):
                h = h[len(pre):] if h.startswith(pre) else h
            branch, _dots, up = h.partition("...")
            st["branch"] = None if branch.startswith("HEAD (") else redact(branch)
            st["upstream"] = redact(up) if up else None
            continue
        if len(rec) < 4:
            continue
        xy, path = rec[:2], rec[3:]
        if "R" in xy or "C" in xy:
            i += 1                              # the name it had before
        if xy == "??":
            st["untracked"] += 1
            untracked.append(path)
        elif xy != "!!":
            st["dirty"] += 1
            if len(st["files"]) < 30:
                st["files"].append(f"{xy.strip()} {redact(path)}")
    head = _git(real, "log", "-1", "--format=%H%x00%h%x00%s")
    if head and head.count("\0") >= 2:
        st["head_full"], st["head"], subject = head.rstrip("\n").split("\0", 2)
        st["subject"] = _masked(subject, 200)
    if since_head is None and since is None:
        return st
    base = since_head if since_head and _HEAD.fullmatch(since_head) else None
    changed = []
    if base:
        diff = _git(real, "diff", "--name-status", "-z", base)
        if diff is None:
            base = None                         # a commit this repository lacks
        else:
            parts = diff.split("\0")
            j = 0
            while j < len(parts) and parts[j]:
                kind = parts[j]
                n = 2 if kind[:1] in ("R", "C") else 1
                names = parts[j + 1:j + 1 + n]
                j += 1 + n
                if names and not names[-1].startswith(".aht/"):    # aht's own marker
                    changed.append(f"{kind[:1]} {redact(names[-1])}")
    for path in untracked:                      # new since then, never committed
        if path.startswith(".aht/"):
            continue                            # aht's own: the marker, the relays
        t = _stat(os.path.join(real, path))
        if since is None or (t and t.st_mtime >= since):
            changed.append(f"?? {redact(path)}")
    if base:
        log_ = _git(real, "log", "--format=%h%x00%s", "-n", "31", f"{base}..HEAD")
    elif since:
        log_ = _git(real, "log", "--format=%h%x00%s", "-n", "31", f"--since=@{int(since)}")
    else:
        log_ = None
    commits = []
    for line in (log_ or "").splitlines():
        sha, _z, subject = line.partition("\0")
        if sha:
            commits.append({"head": sha, "subject": _masked(subject, 200)})
    st.update(base=base, changed=changed[:40], changed_more=max(0, len(changed) - 40),
              commits=commits[:30], commits_more=len(commits) > 30)
    return st

def _git_mark(real: str):
    """What a relay remembers of git when it is written: the base for
    "changed since"."""
    g = git_state(real)
    return {"head": g["head_full"], "branch": g["branch"], "dirty": g["dirty"],
            "ahead": g["ahead"]} if g and g.get("head_full") else None

def _git_lines(g: dict) -> list:
    """The git section of a full summary."""
    where = f"branch `{g['branch']}`" if g.get("branch") else "no branch (a detached HEAD)"
    head = f", HEAD `{g['head']}` “{g['subject']}”" if g.get("head") else ", no commit yet"
    up = ""
    if g.get("upstream"):
        bits = [f"{g['ahead']} commit(s) not pushed" if g["ahead"] else "",
                f"{g['behind']} behind" if g["behind"] else ""]
        up = f"; against {g['upstream']}: " + (", ".join(b for b in bits if b) or "up to date")
    L = ["", "## Git", "", f"- On {where}{head}{up}."]
    if g.get("files"):
        L.append(f"- Not committed ({g['dirty']}):")
        L += [f"  - `{f}`" for f in g["files"]]
        if g["dirty"] > len(g["files"]):
            L.append(f"  - … and {g['dirty'] - len(g['files'])} more")
    else:
        L.append("- Nothing changed that is not committed.")
    if g.get("untracked"):
        L.append(f"- {g['untracked']} file(s) git does not track.")
    return L

# ---- relays: who handed a project's work to whom --------------------------- #
# Every pass of work from one agent (or machine) to another leaves a record in
# the project's .aht/handover: relay-<id>.json, with its summary relay-<id>.md.
# A record is never edited, so the copies on two machines never conflict;
# what happens later is a small marker beside it: relay-<id>.closed {by, at}
# and relay-<id>.told {session, at}.  Open relays stack: Claude Code → Codex →
# Kimi leaves two, and Hand Back goes one step back (or, with --to, more).

_RELAY_ID = re.compile(r"\d{8}-\d{6}-[0-9a-f]{4}")
RELAY_LABEL = {"switch": "Switch", "back": "Hand back", "handover": "Handover",
               "bring": "Bring here", "pickup": "Pick up", "note": "Note"}
BRIEF_MAX = 40000               # characters: a full summary, read by a new session
CATCHUP_MAX = 20000             # a catch-up, read by the session that left
HOOK_NOTE_MAX = 2000            # the catch-up the hook adds to a session's context

def relay_dir(real) -> Path:
    return Path(real) / ".aht" / "handover"

def new_relay_id() -> str:
    return f"{time.strftime('%Y%m%d-%H%M%S')}-{os.urandom(2).hex()}"

def _here_end() -> dict:
    return {"machine": _here(), "system": platform.system()}

def _relay_here(end: dict) -> bool:
    """Whether one end of a relay is this machine: by its machine id, since a
    Mac's name changes with the network it is on; by name only in a record
    that has no id."""
    mid = (end or {}).get("machine_id")
    if mid:
        return mid == machine_id()
    return (end or {}).get("machine") == _here()

def write_relay(real: str, kind: str, frm: dict, to: dict, text: str, rid: str = None,
                back_of: str = None, note_for: str = None) -> dict:
    """Write a relay and its summary into the project -> the record.  The
    summary goes first, so a record never names a file that is not there."""
    d = relay_dir(real)
    d.mkdir(parents=True, exist_ok=True)
    # excerpts of a conversation must never end up in the project's repository
    if not (d / ".gitignore").is_file():
        (d / ".gitignore").write_text("*\n")
    rid = rid if rid and _RELAY_ID.fullmatch(rid) else new_relay_id()
    while (d / f"relay-{rid}.json").exists():
        rid = new_relay_id()
    mid = machine_id(create=True)
    rec = {"v": 1, "id": rid, "kind": kind, "at": time.time(), "project_id": read_marker(real),
           "from": dict(_here_end(), machine_id=mid, path=real, **frm),
           "to": dict(_here_end(), machine_id=mid, path=real, **to),
           "brief": f"relay-{rid}.md", "back_of": back_of, "note_for": note_for}
    (d / rec["brief"]).write_text(text, encoding="utf-8")
    with open(d / f"relay-{rid}.json", "x", encoding="utf-8") as fh:
        json.dump(rec, fh, indent=1)
    prune_relays(d)
    log(f"RELAY {real}: {kind} {rid} {frm.get('agent')} -> {to.get('agent')}")
    return rec

def _relay_marker(d: Path, rid: str, kind: str):
    try:
        v = json.loads((d / f"relay-{rid}.{kind}").read_text(encoding="utf-8"))
        return v if isinstance(v, dict) else {}
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return {}                   # there but unreadable: it still counts

def _mark_relay(real: str, rid: str, kind: str, data: dict) -> bool:
    """Write relay-<id>.closed or .told, once: the first word stands."""
    if not _RELAY_ID.fullmatch(rid or ""):
        return False
    try:
        with open(relay_dir(real) / f"relay-{rid}.{kind}", "x", encoding="utf-8") as fh:
            json.dump(dict(data, at=time.time()), fh)
        return True
    except OSError:
        return False

def close_relay(real: str, rid: str, by: str) -> bool:
    """A relay is answered: by the relay that handed the work back, or by
    "resumed", "taken-back", "sent-back" or "released"."""
    return _mark_relay(real, rid, "closed", {"by": by})

def read_relays(real: str) -> list:
    """The relays of a project, newest first, each with what its markers say
    (`closed`, `told`: None, or the marker's content).  A record whose id is
    not its file's name, or that aht would not have written, is passed over;
    the rest only as _relay_safe keeps them."""
    d = relay_dir(real)
    out = []
    try:
        files = list(d.glob("relay-*.json")) if d.is_dir() else []
    except OSError:
        files = []
    for f in files:
        rid = f.name[len("relay-"):-len(".json")]
        if not _RELAY_ID.fullmatch(rid):
            continue
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rec = _relay_safe(rec, rid)
        if rec is None:
            continue
        out.append(dict(rec, closed=_relay_marker(d, rid, "closed"),
                        told=_relay_marker(d, rid, "told")))
    out.sort(key=lambda r: (r["at"], r["id"]), reverse=True)
    return out

_MACHINE_NAME = re.compile(r"(?=.*[A-Za-z0-9])[A-Za-z0-9._ -]{1,64}")
_MACHINE_ID = re.compile(r"[0-9a-f]{12}")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

def _number(v):
    """A time or a count from a record: a number, never a text or a bool."""
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) \
        and 0 <= v < 1e11 else None

def _relay_safe(rec, rid: str):
    """A relay record as aht's notes, summaries and lists may use it, or None
    to pass it over.  A relay file can come with the folder (a repository
    that committed one), and the hook puts what it says into a session's
    context: so a machine's name holds only letters, digits, spaces and
    . _ - (else "another machine"), an agent is one aht knows, times are
    numbers, titles are masked and short, and a path or a session id is
    kept only as aht writes it."""
    if not (isinstance(rec, dict) and rec.get("id") == rid
            and rec.get("kind") in RELAY_LABEL and _number(rec.get("at")) is not None):
        return None
    ends = {}
    for side in ("from", "to"):
        e = rec.get(side)
        if not isinstance(e, dict) or e.get("agent") not in AGENT_NAMES:
            return None
        mid = e.get("machine_id")
        if mid is not None and not (isinstance(mid, str) and _MACHINE_ID.fullmatch(mid)):
            return None
        word = lambda k, ok: e[k] if isinstance(e.get(k), str) and ok(e[k]) else None
        name = e.get("machine")
        x = {"machine": name if name is None or (isinstance(name, str)
                                                 and _MACHINE_NAME.fullmatch(name))
             else "another machine",
             "system": word("system", lambda v: v in ("Darwin", "Linux", "Windows")),
             "path": word("path", lambda v: len(v) <= 4096 and not _CONTROL.search(v)),
             "agent": e["agent"],
             "session": word("session", lambda v: len(v) <= 200 and _SESSION_ID.fullmatch(v))}
        if mid:
            x["machine_id"] = mid
        if side == "from":
            g = e.get("git")
            x["title"] = _line(e.get("title"))
            x["last_t"] = _number(e.get("last_t"))
            x["git"] = {"head": g["head"], "branch": _line(g.get("branch")),
                        "dirty": int(_number(g.get("dirty")) or 0),
                        "ahead": int(_number(g.get("ahead")) or 0)} \
                if isinstance(g, dict) and isinstance(g.get("head"), str) \
                and _HEAD.fullmatch(g["head"]) else None
        else:
            x["mode"] = word("mode", lambda v: v in ("new", "resume", "brief-only"))
        ends[side] = x
    pid, back, note = rec.get("project_id"), rec.get("back_of"), rec.get("note_for")
    return {"v": 1, "id": rid, "kind": rec["kind"], "at": _number(rec["at"]),
            "project_id": pid if isinstance(pid, str) and re.fullmatch(r"[A-Za-z0-9-]{1,64}", pid)
            else None, **ends, "brief": f"relay-{rid}.md",
            "back_of": back if isinstance(back, str) and _RELAY_ID.fullmatch(back) else None,
            "note_for": note if isinstance(note, str) and len(note) <= 200
            and _SESSION_ID.fullmatch(note) else None}

def _line(v):
    """A short line of text from a record (a title, a branch): masked, on
    one line; None when there is none."""
    return _masked(" ".join(v.split()), 120) if isinstance(v, str) and v.strip() else None

def session_file(real: str, agent: str, sid: str):
    """The file of one session of the folder `real`, found without reading
    the others; None when it is gone."""
    if not (sid and _SESSION_ID.fullmatch(sid)) or sid in (".", ".."):
        return None
    f = None
    if agent == "claude":
        store = _store_of(real)
        f = Path(store) / f"{sid}.jsonl" if store else None
    elif agent == "kimi" and BY_NAME.get("kimi-code"):
        f = BY_NAME["kimi-code"].root() / _key_kimicode(real) / sid / "agents" / "main" / "wire.jsonl"
    elif agent == "codex":
        b = BY_NAME.get("codex")
        if b and b.available():         # its file is named after it, usually
            f = next((x for x in b.root().rglob(f"rollout-*{sid}.jsonl") if x.is_file()), None) \
                or next((Path(s["file"]) for s in list_sessions(real, agents=["codex"])
                         if s["id"] == sid), None)
    elif agent == "agy" and agy_conversation_exists(sid):
        f = AGY_STORE.root() / "brain" / sid / ".system_generated" / "logs" / "transcript.jsonl"
    return f if f and f.is_file() else None

def _session_after(real: str, agent: str, since: float):
    """The newest session of `agent` in the folder `real` that began after
    `since`: what the receiving end of a relay opened."""
    for s in list_sessions(real, agents=[agent]):
        if (s["updated"] or 0) < since - 1:
            break
        for _end, ev in session_events(s["agent"], s["file"]):
            if ev.get("t"):
                if ev["t"] >= since - 1:
                    return s["id"]
                break
    return None

def _went_on(real: str, r: dict) -> bool:
    """Whether someone typed into the session a relay left, after the relay
    (here, resumed by hand).  Only what the user typed counts: the session
    that ran the switch may still have answered after it."""
    f = r.get("from") or {}
    if not (_relay_here(f) and f.get("session") and f.get("agent") in _EVENTS):
        return False
    path = session_file(real, f["agent"], f["session"])
    st = _stat(path) if path else None
    at = float(r.get("at") or 0)
    if st is None or st.st_mtime <= at:
        return False
    for _end, ev in session_events(f["agent"], str(path), max(0, st.st_size - (2 << 20))):
        if ev["role"] == "user" and (ev.get("t") or 0) > at + 1:
            return True
    return False

def _opens_nothing(r: dict) -> bool:
    """A hand-back answers a relay and opens none; Summary Only started
    nothing, so who has the project stays as it was."""
    return r.get("kind") == "back" or (r.get("to") or {}).get("mode") == "brief-only"

def open_relays(real: str, relays: list = None) -> list:
    """The project's open relays, newest first: work handed on that has not
    come back.  A relay whose origin session was resumed by hand since is
    closed here ("resumed").  A hand-back and a Summary Only open none."""
    out = []
    for r in relays if relays is not None else read_relays(real):
        if r.get("closed") is not None or _opens_nothing(r):
            continue
        if _went_on(real, r):
            close_relay(real, r["id"], "resumed")
            continue
        out.append(r)
    return out

def relay_row(r: dict, real: str) -> dict:
    """A relay as `relays --json` lists it."""
    closed = r.get("closed")
    return {"id": r["id"], "kind": r.get("kind"), "at": r.get("at"),
            "from": r.get("from"), "to": r.get("to"),
            "open": closed is None and not _opens_nothing(r),
            "closed_by": (closed or {}).get("by") if closed is not None else None,
            "brief": str(relay_dir(real) / f"relay-{r['id']}.md")}

def project_relay(real: str):
    """A project's newest open relay, for its row in the window: None, or
    {id, from_agent, to_agent, since, open, incoming}.  The same relay Hand
    Back (switch --back) answers."""
    if not relay_dir(real).is_dir():
        return None
    r = next(iter(open_relays(real)), None)
    if r is None:
        return None
    return {"id": r["id"], "from_agent": r["from"].get("agent"), "to_agent": r["to"].get("agent"),
            "since": r.get("at"), "open": True,
            "incoming": not (_relay_here(r["from"]) and _relay_here(r["to"]))}

# ---- the summaries ----------------------------------------------------------- #

def catchup_digest(real: str, since: float, exclude=(), tail: int = 4 << 20,
                   most: int = 6) -> dict:
    """What happened in the folder `real` after `since`, in every session but
    those in `exclude` ((agent, id) pairs): {since, sessions (oldest first,
    each a digest of its exchanges after `since`), exchanges, first_t,
    last_t}."""
    rows = []
    for s in list_sessions(real):
        if (s["updated"] or 0) < since - 1:
            break                                   # newest first: the rest are older
        if (s["agent"], s["id"]) in exclude or (s["agent"] == "claude"
                                                and _is_scripted(s["file"])):
            continue
        dig = events_digest(s, real, turns=12, tail=tail, since=since)
        if dig["count"] or dig["touched"]:
            rows.append(dict(dig, agent=s["agent"], id=s["id"],
                             title=dig.get("title") or _session_title(s)))
        if len(rows) >= most:
            break
    rows.sort(key=lambda r: r["first_t"] or r["last_t"] or 0)
    times = [t for r in rows for t in (r["first_t"], r["last_t"]) if t]
    return {"since": since, "sessions": rows, "exchanges": sum(r["count"] for r in rows),
            "first_t": min(times) if times else None, "last_t": max(times) if times else None}

def _names(agents: list) -> str:
    names = [AGENT_NAMES.get(a, a) for a in dict.fromkeys(agents)]
    return " and ".join([", ".join(names[:-1]), names[-1]] if len(names) > 1 else names)

def _span(a, b, to: str = " to ") -> str:
    """From when to when: "14:10 to 16:40", the date once when not today."""
    if not a:
        return ""
    a_, b_ = _clock(a), _clock(b) if b else ""
    if not b_ or b_ == a_:
        return a_
    return a_ + to + (b_[-5:] if b_[:-5] == a_[:-5] else b_)

def _more(items: list, n: int, more: int = 0) -> str:
    extra = len(items) - n + more
    return ", ".join(items[:n]) + (f" and {extra} more" if extra > 0 else "")

def catchup_head(cd: dict, g, away: str, had: list = None) -> list:
    """The first lines of a catch-up, which also make the note Claude's
    hook gives the session: who worked, files and commits since, what is
    still open, the last words.  `had`: the agents the relays being answered
    went to; when none of their work can be read, the head says so."""
    who = _names([r["agent"] for r in cd["sessions"]])
    n, k = cd["exchanges"], len(cd["sessions"])
    if k:
        span = _span(cd["first_t"], cd["last_t"])
        L = [f"While {away} was away, {who} worked here {'from' if ' to ' in span else 'at'} {span} "
             f"({n} exchange{'s' if n != 1 else ''}" + (f" in {k} sessions" if k > 1 else "") + ")."]
    elif had:
        L = [_unread_work(had, cd["since"])]
    else:
        L = [f"While {away} was away (since {_clock(cd['since'])}), no other agent's session "
             "here that aht can read went on."]
    if g and g.get("base"):
        files = [c.split(" ", 1)[1] for c in g["changed"]]
        if files:
            L.append(f"- Changed since: {_more(files, 6, g['changed_more'])}.")
    else:
        files = list(dict.fromkeys(f for r in cd["sessions"] for f in r["touched"]))
        if files:
            L.append(f"- Changed since: {_more([redact(f) for f in files], 6)}.")
    if g and g.get("commits"):
        L.append("- Commits since: " + _more([f"{c['head']} “{c['subject']}”"
                                              for c in g["commits"]], 3) + ".")
    todos = [_todo_text(t) for r in cd["sessions"][-1:] for t in r["todos"]]
    if todos:
        L.append("- Still open: " + "; ".join(f"“{_masked(t, 120)}”" for t in todos[:4]) + ".")
    last = cd["sessions"][-1] if cd["sessions"] else None
    words = ((last or {}).get("exchanges") or [{}])[-1].get("agent")
    if words:
        L.append(f"- {AGENT_NAMES.get(last['agent'], last['agent'])}'s last words: "
                 f"“{_masked(' '.join(words.split()), 400)}”")
    if k or (g and (g.get("changed") or g.get("commits")) and not had):
        L.append("The files on disk may differ from what this conversation remembers: "
                 "read them before editing.")
    return L

def _unread_work(had: list, since: float) -> str:
    """The agents that had the project left nothing aht can read (an agent
    without a reader, or a session it cannot parse): the files may differ
    all the same."""
    names = list(dict.fromkeys(a for a in had if a in AGENT_NAMES))
    return (f"{_names(names) or 'Another agent'} had the project from {_clock(since)}; aht "
            f"cannot read {'its' if len(names) < 2 else 'their'} work, so the files may differ: "
            "read them before editing.")

def _clip_to(text: str, n: int) -> str:
    if len(text) <= n:
        return text
    return text[:n - 80].rstrip() + f"\n\n[… cut here: a summary holds at most {n} characters]\n"

def relay_brief(real: str, kind: str, source: dict, since: float = None, relay: dict = None,
                dig: dict = None, had: list = None) -> str:
    """The summary that goes with a relay, built from the histories without
    spending a token; whatever looks like a key is masked.
    kind "full", for a new session: where things stood in `source` (a
    list_sessions row), the latest exchanges, open to-dos, files changed,
    git, files used outside the project.  At most BRIEF_MAX characters.
    kind "catchup", for the session that left (`source`): what every other
    session here did after `since`, the files changed and the commits made
    since.  At most CATCHUP_MAX.  `relay` is the record it goes with (for
    the header); `dig` a digest made already; `had` (catch-up) the agents
    the relays it answers went to."""
    relay = relay or {}
    frm, to = relay.get("from") or {}, relay.get("to") or {}
    name = os.path.basename(real)
    codex_n = codex_unreadable(real)
    warn_codex = [f"- Codex has {codex_n} session{'s' if codex_n > 1 else ''} here that aht "
                  "cannot read (Codex's newer storage)."] if codex_n else []
    if kind == "catchup":
        away = AGENT_NAMES.get(source["agent"], source["agent"])
        cd = dig or catchup_digest(real, since, exclude={(source["agent"], source["id"])})
        g = git_state(real, since_head=(frm.get("git") or {}).get("head")
                      if relay.get("kind") == "back" else None, since=since)
        L = [f"# Catch-up: {name}", ""] + catchup_head(cd, g, away, had) + warn_codex
        shown = sorted((x for r in cd["sessions"] for x in r["exchanges"]),
                       key=lambda x: x.get("t") or 0)[-12:]
        full = {id(x) for x in shown}
        for r in cd["sessions"]:
            title = r.get("title") or "untitled"
            L += ["", f"## {AGENT_NAMES.get(r['agent'], r['agent'])} — {_masked(title, 90)} "
                      f"(`{r['id']}`), {_span(r['first_t'], r['last_t'])}"]
            mine = [x for x in r["exchanges"] if id(x) in full]
            first = mine[0].get("t") if mine else None
            older = [q for q in r["requests"] if not first or (q["t"] or 0) < first]
            if older:
                L += ["", "Earlier requests:"]
                L += [f"- {_clock(q['t'])} " + _masked(" ".join(q["text"].split()), 160)
                      for q in older[-10:]]
            for x in mine:
                L += ["", f"**You ({_clock(x['t'])}):** " + _masked(x["you"], 1500)]
                if x.get("agent"):
                    L += ["", "**Agent:** " + _masked(x["agent"], 2500)]
            if not mine and r["exchanges"] and r["exchanges"][-1].get("agent"):
                L += ["", "Its last message: " + _masked(r["exchanges"][-1]["agent"], 2500)]
        todos = [(r["agent"], t) for r in cd["sessions"] for t in r["todos"]]
        if todos:
            L += ["", "## To-dos still open", ""]
            L += [f"- [ ] {_masked(_todo_text(t), 200)}"
                  + (f"  *({AGENT_NAMES.get(a, a)})*" if len(cd["sessions"]) > 1 else "")
                  for a, t in todos]
        if g and g.get("base"):
            if g["changed"]:
                L += ["", "## Files changed since (git)", ""] + [f"- `{c}`" for c in g["changed"]]
                if g["changed_more"]:
                    L.append(f"- … and {g['changed_more']} more")
        else:
            files = list(dict.fromkeys(f for r in cd["sessions"] for f in r["touched"]))
            untracked = [c for c in (g or {}).get("changed") or [] if c.startswith("?? ")]
            if files or untracked:
                L += ["", "## Files changed since", ""] + [f"- `{redact(f)}`" for f in files] \
                    + [f"- `{c}`" for c in untracked]
        if g and g.get("commits"):
            L += ["", "## Commits since", ""] + [f"- `{c['head']}` {c['subject']}"
                                                 for c in g["commits"]]
            if g["commits_more"]:
                L.append("- … and more")
        return _clip_to("\n".join(L) + "\n", CATCHUP_MAX)
    dig = dig or events_digest(source, real)
    label = RELAY_LABEL.get(relay.get("kind"), "Switch")
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(relay.get("at") or time.time()))
    system = {"Darwin": "macOS", "Linux": "Linux", "Windows": "Windows"}
    fa = AGENT_NAMES.get(frm.get("agent") or source["agent"], source["agent"])
    ta = AGENT_NAMES.get(to.get("agent"), to.get("agent") or "?")
    L = [f"# {label}: {name}", "",
         f"- From **{fa}** to **{ta}** on {_here()} "
         f"({system.get(platform.system(), platform.system())}), {when}"]
    if to.get("path") and to["path"] != real:
        L += [f"- Folder here: `{real}`; there: `{to['path']}`"]
    else:
        L += [f"- Folder: `{real}`"]
    L += [f"- Session it continues: {_masked(dig.get('title') or 'untitled', 120)} — "
          f"`{source['id']}`",
          f"- To go back to it: `{resume_command(source['agent'], source['id'], real)}`, or "
          f"`aht switch {shell_quote(real)} --back`"] + warn_codex
    L += _brief_sections(dig, times=True)
    g = git_state(real)
    if g:
        L += _git_lines(g)
    if dig.get("outside"):
        L += ["", "## Files outside the project that session used", ""]
        L += [f"- `{redact(p)}`" for p in dig["outside"]]
    return _clip_to("\n".join(L) + "\n", BRIEF_MAX)

def codex_unreadable(real: str) -> int:
    """How many Codex sessions in the folder `real` aht cannot read: Codex's
    newer storage keeps a thread in its state_5.sqlite without a rollout
    file.  Read from a copy of that file."""
    b = BY_NAME.get("codex")
    if b is None:
        return 0
    n = 0
    for r in _sqlite_rows(b.root().parent / "state_5.sqlite", "threads",
                          ("id", "rollout_path", "cwd", "archived")):
        cwd, rp = r.get("cwd"), r.get("rollout_path")
        if isinstance(cwd, str) and not r.get("archived") and _same_dir(cwd, real) \
                and not (isinstance(rp, str) and rp and os.path.isfile(rp)):
            n += 1
    return n

# ---- switch agent, and hand back ------------------------------------------- #

def agent_start_line(agent: str, mode: str, sid=None, ask: str = None) -> str:
    """The line that opens `agent` in a terminal: a new session that reads
    the summary first (mode "new"), or its own session `sid`, which reads
    the catch-up (mode "resume").  Claude's own session hears of the
    catch-up from aht's SessionStart hook, so it costs nothing before you
    type.  Kimi reads its summary in a run of its own first (switch does
    that), so its line only opens the session."""
    q = shell_quote
    exe = q(agent_cli(agent) or agent)
    resume = mode == "resume" and sid
    if agent == "kimi":
        return f"{exe} -S {q(sid)}" if sid else f"{exe} -S <the new session>"
    if agent == "claude":
        if resume:
            return f"{exe} --resume {q(sid)}" + ("" if hook_installed() or not ask
                                                 else f" -- {q(ask)}")
        return f"{exe} {q(ask)}"
    if agent == "codex":
        return f"{exe} resume {q(sid)} {q(ask)}" if resume else f"{exe} {q(ask)}"
    if agent == "agy":
        rc = " --remote-control" if cfg_get("handover_remote_control", True) else ""
        return f"{exe}{rc} --conversation {q(sid)} -i {q(ask)}" if resume \
            else f"{exe}{rc} -i {q(ask)}"
    raise ValueError(f"no start line for {agent}")

def _ask(frm: str, rel: str, catchup: bool) -> str:
    """The first prompt: it points at the summary's file, since Windows'
    command line takes at most 8,191 characters."""
    if catchup:
        return (f"While you were away, other agents worked on this project. Read {rel} "
                "first: it lists what they did since your last turn. Then tell me in two "
                "or three lines what changed, and wait for my next instruction.")
    return (f"You are taking over this project from {frm}. Read {rel} first: it records "
            "where the work stood, the latest exchanges and the open items. Then tell me "
            "in two or three lines what you understood, and wait for my next instruction.")

def _kimi_reads(exe: str, real: str, prompt: str, sid: str = None) -> tuple:
    """Kimi reads `prompt` in a run of its own, in its session `sid` or in a
    new one -> (session, None), or (None, why not; "" when the run went
    fine but the turn is not in that session).  Kimi takes no first prompt
    in its interactive mode: this is how it gets one."""
    started = time.time()
    own = session_file(real, "kimi", sid) if sid else None
    size = (_stat(own).st_size if own and _stat(own) else 0)
    if os.name == "nt":
        prompt = _clip(prompt, 30000)       # a Windows command line's limit is 32,767
    argv = [exe] + (["-S", sid] if sid else []) + ["-p", prompt, "--output-format", "stream-json"]
    try:
        r = subprocess.run(argv, cwd=real, capture_output=True, encoding="utf-8",
                           errors="replace", timeout=600, **_NO_WINDOW)
    except subprocess.TimeoutExpired:
        return None, "Kimi did not finish reading the summary within 10 minutes"
    except OSError as e:
        return None, f"Kimi could not be started: {e}"
    if r.returncode != 0:
        return None, ("Kimi could not read the summary: "
                      + ((r.stderr or r.stdout or "").strip()[-300:] or f"exit {r.returncode}"))
    if sid:                 # the turn must be in that session now, after what was there
        took = own and any(ev["role"] == "user" for _e, ev in session_events("kimi", str(own), size))
        return (sid, None) if took else (None, "")
    new = next(iter(re.findall(r'"(session_[0-9a-f-]{36})"', r.stdout or "")), None) \
        or _session_after(real, "kimi", started)
    return (new, None) if new else (None, "Kimi could not read the summary: no session")

def _kimi_prompt(text: str, frm: str, catchup: bool) -> str:
    if catchup:
        return ("While you were away, other agents worked on this project. This is what "
                "they did since your last turn:\n\n" + text + "\nDo not start working yet. "
                "Reply in two or three lines with what changed; the user continues in this "
                "session.")
    return (f"You are taking over this project from {frm}. This is where the work "
            "stood:\n\n" + text + "\nDo not start working yet. Reply in two or three lines "
            "with what you understood; the user continues in this session.")

def agents_running_nt() -> set:
    """Windows: the agent CLIs running on this PC now, by program name
    (tasklist).  In which folder cannot be told there."""
    try:
        r = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True,
                           encoding="utf-8", errors="replace", timeout=15, **_NO_WINDOW)
    except Exception:
        return set()
    names = {line.split(",")[0].strip('"').lower() for line in r.stdout.splitlines() if line}
    return {a for a in ("codex", "kimi", "agy") if f"{a}.exe" in names}

def _switch_checks(out: dict, real: str, origin=None, brief_only: bool = False,
                   back: bool = False) -> None:
    """What stands in the way of starting an agent in the folder `real`: a
    Claude session working there blocks; one open but idle, or another agent
    open there, is a warning.  `origin`: the Claude session to continue; open
    in its window it blocks (nothing opens a second window on it)."""
    for s in running_sessions(inside=real):
        if origin and s.get("session") == origin and not brief_only:
            out["blockers"].append(
                "That session is still open in its window. Exit it and press Hand Back "
                f"again (in a terminal, `aht switch {shell_quote(real)} --back --brief-only` "
                "writes the summary for it to read)" if back else
                "That Claude Code session is still open in its window: go on there, or "
                "exit it first")
        elif s.get("status") != "idle":
            out["blockers"] += _activity_blockers({"sessions": [s]}, "on this machine")
        elif not brief_only:
            out["warnings"].append("a Claude session is still open in this project; do not "
                                   "type into both agents at once")
    if os.name == "nt":
        for a in sorted(agents_running_nt()):
            out["warnings"].append(f"{AGENT_NAMES[a]} is running on this PC; aht cannot "
                                   "tell in which folder")
        return
    here = sorted({p["agent"] for p in agent_processes()
                   if _inside(os.path.realpath(p["project"]), real)})
    for a in here:
        out["warnings"].append(f"{AGENT_NAMES.get(a, a)} is still open in this folder; "
                               "don't type into both")

def _start(args, out: dict, lines: list, real: str, target: str, line: str) -> int:
    """Open the agent's line in a terminal window (or say what to run)."""
    out["start_line"] = line
    cmd = cd_then(real) + line                       # the same line, to run anywhere
    out["command_line"] = cmd
    # nothing but the JSON on stdout: the line to run by hand goes in the error
    if not args.no_window and open_terminal(line, f"switch-{os.path.basename(real)}-{target}",
                                            cwd=real, echo=False) != 0:
        out["error"] = f"No terminal window opened. Run this in a terminal:\n\n{cmd}"
        log(f"SWITCH {real}: -> {target}, but no terminal opened")
        return _emit(args, out, lines)
    out["applied"] = True
    lines.append(f"   opened  {cmd}")
    return _emit(args, out, lines)

def cmd_switch(args):
    out = {"command": "switch", "applied": False, "blockers": [], "warnings": [],
           "project": None, "source": None, "target": None, "brief": None, "session": None,
           "command_line": None, "error": None,
           "relay": None, "mode": None, "start_line": None, "fallback": None}
    lines = []
    real = os.path.realpath(args.path)
    out["project"] = real
    if not os.path.isdir(real):
        out["blockers"].append(f"not a folder: {real}")
        return _emit(args, out, lines)
    if args.back:
        return _switch_back(args, out, lines, real)
    target = args.to
    if not target:
        out["blockers"].append("say which agent goes on: --to claude, codex, kimi or agy "
                               "(or --back to hand the work back)")
        return _emit(args, out, lines)
    mode = "brief-only" if args.brief_only else "resume" if args.resume else "new"
    out.update(target=target, mode=mode)
    exe = agent_cli(target)
    if not exe and mode != "brief-only":
        out["blockers"].append(f"{AGENT_NAMES[target]} is not installed on this machine")
    sessions = [s for s in list_sessions(real) if s["agent"] != target]
    if args.session:
        src = next((s for s in sessions if s["id"] == args.session), None)
    else:       # the latest one worked in; a scripted run only when nothing else is there
        src = next((s for s in sessions if not (s["agent"] == "claude"
                                               and _is_scripted(s["file"]))),
                   sessions[0] if sessions else None)
    if src is None:
        out["blockers"].append("no session of another agent in this project to continue"
                               + (f" (no session {args.session})" if args.session else ""))
    own = next((s for s in list_sessions(real, agents=[target]) if not (
        target == "claude" and _is_scripted(s["file"]))), None)
    if mode == "resume" and own is None:
        mode = out["mode"] = "new"
        out["fallback"] = (f"{AGENT_NAMES[target]} has no earlier session here, so a new "
                           "session reads the full summary")
    _switch_checks(out, real, own["id"] if mode == "resume" and target == "claude" else None,
                   mode == "brief-only")
    if out["blockers"]:
        return _emit(args, out, lines)
    dig = events_digest(src, real)
    frm = AGENT_NAMES[src["agent"]]
    out["source"] = {"agent": src["agent"], "session": src["id"], "title": dig.get("title")}
    codex_n = codex_unreadable(real)
    if codex_n:
        out["warnings"].append(f"Codex has {codex_n} session{'s' if codex_n > 1 else ''} "
                               "here that aht cannot read (Codex's newer storage)")
    rid = new_relay_id()
    rel = os.path.join(".aht", "handover", f"relay-{rid}.md")
    sid = own["id"] if mode == "resume" else None
    out["session"] = sid                # the session that goes on, when it is known
    ask = _ask(frm, rel, mode == "resume")
    if mode != "brief-only":
        out["start_line"] = agent_start_line(target, mode, sid, ask)
    lines += [f"{'switching' if args.apply else 'would switch'}:  {real}",
              f"   from   {frm} — {dig.get('title') or src['id']} ({_clock(src['updated'])})"]
    if mode == "brief-only":
        lines.append(f"   to     {AGENT_NAMES[target]}: only the summary is written; nothing opens")
    elif mode == "resume":
        lines += [f"   to     {AGENT_NAMES[target]} — its own session "
                  f"“{_session_title(own) or own['id']}” ({_clock(own['updated'])})",
                  f"          it reads only what happened since (uses tokens)"]
        if target == "kimi":
            lines.append("          if Kimi does not take it into that session, a new one "
                         "reads the full summary")
    else:
        lines.append(f"   to     {AGENT_NAMES[target]}, a new session (reads the full "
                     "summary: uses tokens)")
        if own is not None:
            lines += [f"   {AGENT_NAMES[target]} has its own earlier session here "
                      f"(“{_session_title(own) or own['id']}”, {_clock(own['updated'])}):",
                      "   continue that one with --resume (it reads only what happened since)"]
    if out["fallback"]:
        lines.append(f"   {out['fallback']}")
    if not args.apply:
        lines.append("(dry run — pass --apply to do it"
                     + ("; --brief-only writes the summary and opens nothing)"
                        if mode != "brief-only" else ")"))
        return _emit(args, out, lines)
    head = {"kind": "switch", "at": time.time(),
            "from": {"agent": src["agent"], "session": src["id"]},
            "to": {"agent": target, "path": real}}
    since = own["updated"] if mode == "resume" else None
    text = relay_brief(real, "catchup", own, since, head) if mode == "resume" \
        else relay_brief(real, "full", src, relay=head, dig=dig)
    if target == "kimi" and mode != "brief-only":
        # Kimi reads it in a run of its own, before the relay is written: which
        # session took it is known then
        sid, why = _kimi_reads(exe, real, _kimi_prompt(text, frm, mode == "resume"), sid)
        if sid is None and why == "":
            out["fallback"] = ("Kimi did not take the summary into its own session, so a "
                               "new session read the full summary")
            mode = "new"
            out["mode"] = mode
            text = relay_brief(real, "full", src, relay=head, dig=dig) + "\n---\n\n" + text
            sid, why = _kimi_reads(exe, real, _kimi_prompt(text, frm, False))
        if sid is None:
            out["error"] = why
            return _emit(args, out, lines)
    # Claude's own session hears of its catch-up from aht's hook, which
    # looks for the relay that names it (as a Hand Back's does)
    rec = write_relay(real, "switch",
                      {"agent": src["agent"], "session": src["id"], "title": dig.get("title"),
                       "last_t": dig.get("last_t") or src["updated"], "git": _git_mark(real)},
                      {"agent": target, "session": sid, "mode": mode}, text, rid=rid,
                      note_for=sid if target == "claude" and mode == "resume" else None)
    out["relay"] = rec["id"]
    out["brief"] = str(relay_dir(real) / rec["brief"])
    lines.append(f"   summary {out['brief']}")
    log(f"SWITCH {real}: {src['agent']} {src['id']} -> {target} ({mode})")
    if mode == "brief-only":
        out["applied"] = True
        return _emit(args, out, lines)
    if checkpoints_on():
        take_checkpoint(real, None, target)
    out["session"] = sid
    rel = os.path.join(".aht", "handover", rec["brief"])
    return _start(args, out, lines, real, target,
                  agent_start_line(target, mode, sid, _ask(frm, rel, mode == "resume")))

def _switch_back(args, out: dict, lines: list, real: str) -> int:
    """Hand the work back: the newest open relay (or the newest that came
    from --to), answered in the origin agent's own session with a catch-up
    since the relay.  Gone, that session: a new one reads the full summary
    and the catch-up."""
    rels = open_relays(real)
    pick = [r for r in rels if not args.to or r["from"].get("agent") == args.to]
    if not pick:
        out["blockers"].append("nothing to hand back: no agent took this project over here"
                               + (f" from {AGENT_NAMES[args.to]}" if args.to else ""))
        return _emit(args, out, lines)
    r = pick[0]
    origin = r["from"]
    target, sid = origin.get("agent"), origin.get("session")
    # answered with it: what was stacked on it, and earlier hand-offs from the
    # same session (an earlier switch from it, say)
    later = [x for x in rels if x is not r and (((x.get("at") or 0), x["id"])
                                                > ((r.get("at") or 0), r["id"])
                                                or (x["from"].get("agent"), x["from"].get("session"))
                                                == (target, sid))]
    if target not in SWITCH_TARGETS:
        out["blockers"].append(f"the work came from {target}, which aht cannot start")
        return _emit(args, out, lines)
    now = rels[0]["to"]                                  # who has it now
    if now.get("agent") == target:
        out["blockers"].append(f"{AGENT_NAMES[target]} has this project already (since "
                               f"{_clock(rels[0].get('at'))}): there is nothing to hand back "
                               "to it")
        return _emit(args, out, lines)
    now_sid = now.get("session") or _session_after(real, now.get("agent"), rels[0]["at"])
    gone = session_file(real, target, sid) is None
    mode = "brief-only" if args.brief_only else "back"
    exe = agent_cli(target)
    if not exe and mode != "brief-only":
        out["blockers"].append(f"{AGENT_NAMES[target]} is not installed on this machine")
    out.update(target=target, mode=mode, session=None if gone else sid,
               source={"agent": now.get("agent"), "session": now_sid, "title": None})
    if gone:
        out["fallback"] = (f"That {AGENT_NAMES[target]} session is gone, so a new session "
                           "reads the full summary")
    _switch_checks(out, real, sid if target == "claude" and not gone else None,
                   mode == "brief-only", back=True)
    if out["blockers"]:
        return _emit(args, out, lines)
    since = min(float(x.get("at") or 0) for x in [r] + later
                if (x["from"].get("agent"), x["from"].get("session")) == (target, sid))
    cd = catchup_digest(real, since, exclude={(target, sid)})
    worker = next((x for x in reversed(cd["sessions"]) if x["id"] == now_sid), None)
    out["source"]["title"] = (worker or {}).get("title")
    g = git_state(real, since_head=(origin.get("git") or {}).get("head"), since=since)
    n, k = cd["exchanges"], len(cd["sessions"])
    # the agents it went to, in turn; none of their work readable: say so
    had = [x["to"]["agent"] for x in sorted([r] + later, key=lambda x: (x["at"], x["id"]))]
    if not k:
        out["warnings"].append(_unread_work(had, since))
    who = _names([x["agent"] for x in cd["sessions"]]) or AGENT_NAMES.get(now.get("agent"), "?")
    tally = [f"{who} ({k} session{'s' if k != 1 else ''}, {n} exchange{'s' if n != 1 else ''})"]
    if g and g.get("base"):
        tally.append(f"{len(g['changed']) + g['changed_more']} file(s) changed")
    if g and g.get("commits"):
        tally.append(f"{len(g['commits'])}{'+' if g['commits_more'] else ''} commit(s)")
    todos = sum(len(x["todos"]) for x in cd["sessions"][-1:])
    if todos:
        tally.append(f"{todos} to-do(s) open")
    tname = AGENT_NAMES[target]
    title = origin.get("title") or (sid or "")
    lines += [f"{'handing back' if args.apply else 'would hand back'}:  {real}",
              (f"   to     {tname} — a new session; its own (“{title}”) is gone"
               if gone else f"   to     {tname} — its own session “{title}”"),
              f"   since  {_clock(since)}: " + ", ".join(tally)]
    if later:
        lines.append(f"   also answers {len(later)} later hand-off(s) on the way")
    if mode == "back" and not gone:
        lines.append("   Claude reads this with your next message; nothing runs before that"
                     if target == "claude" and hook_installed()
                     else f"   {tname} reads it as its first turn (uses tokens)")
    if out["fallback"]:
        lines.append(f"   {out['fallback']}")
    rid = new_relay_id()
    rel = os.path.join(".aht", "handover", f"relay-{rid}.md")
    frm = AGENT_NAMES.get(now.get("agent"), now.get("agent") or "?")
    if mode != "brief-only":
        out["start_line"] = agent_start_line(target, "new" if gone else "resume",
                                             None if gone else sid, _ask(frm, rel, not gone))
    if not args.apply:
        lines.append("(dry run — pass --apply to do it)")
        return _emit(args, out, lines)
    head = {"kind": "back", "at": time.time(), "from": dict(origin, agent=now.get("agent")),
            "to": {"agent": target, "path": real}}
    catchup = relay_brief(real, "catchup", {"agent": target, "id": sid}, since,
                          dict(head, **{"from": origin}), dig=cd, had=had)
    def with_full(text):        # for a new session: the worker's summary first
        f = worker and session_file(real, worker["agent"], worker["id"])
        full = relay_brief(real, "full", {"agent": worker["agent"], "id": worker["id"],
                                          "file": str(f)}, relay=head) if f else ""
        return _clip_to(full + ("\n---\n\n" if full else "") + text, BRIEF_MAX)
    text = with_full(catchup) if gone else catchup
    took = None if gone else sid
    if target == "kimi" and mode != "brief-only":
        took, why = _kimi_reads(exe, real, _kimi_prompt(text, frm, not gone), took)
        if took is None and why == "":
            out["fallback"] = ("Kimi did not take the summary into its own session, so a "
                               "new session read the full summary")
            gone, text = True, with_full(catchup)
            took, why = _kimi_reads(exe, real, _kimi_prompt(text, frm, False))
        if took is None:
            out["error"] = why
            return _emit(args, out, lines)
    rec = write_relay(real, "back",
                      {"agent": now.get("agent"), "session": now_sid,
                       "title": (worker or {}).get("title"), "last_t": cd["last_t"],
                       "git": _git_mark(real)},
                      {"agent": target, "session": took, "mode": "new" if gone else "resume"},
                      text, rid=rid, back_of=r["id"],
                      note_for=sid if target == "claude" and not gone else None)
    for x in [r] + later:
        close_relay(real, x["id"], rec["id"])
    out["relay"] = rec["id"]
    out["brief"] = str(relay_dir(real) / rec["brief"])
    out["session"] = took
    lines.append(f"   summary {out['brief']}")
    log(f"SWITCH {real}: back to {target} {sid} ({'new session' if gone else 'its own'})")
    if mode == "brief-only":
        out["applied"] = True
        return _emit(args, out, lines)
    if checkpoints_on():
        take_checkpoint(real, None, target)
    rel = os.path.join(".aht", "handover", rec["brief"])
    return _start(args, out, lines, real, target,
                  agent_start_line(target, "new" if gone else "resume", took,
                                   _ask(frm, rel, not gone)))

def cmd_relays(args):
    real = os.path.realpath(args.path)
    if not os.path.isdir(real):
        print(f"not a folder: {real}", file=sys.stderr)
        return 2
    open_relays(real)                   # closes those resumed by hand meanwhile
    rels = read_relays(real)
    for r in rels:                      # the receiving session, once there is one
        if relay_row(r, real)["open"] and not r["to"].get("session") and _relay_here(r["to"]):
            r["to"] = dict(r["to"], session=_session_after(real, r["to"].get("agent"), r["at"]))
    rows = [relay_row(r, real) for r in rels]
    if args.show:
        row = next((x for x in rows if x["id"] == args.show), None)
        if row is None or not _RELAY_ID.fullmatch(args.show):
            print(f"no relay {args.show} in {real}", file=sys.stderr)
            return 2
        try:
            text = redact(Path(row["brief"]).read_text(encoding="utf-8", errors="replace"))
        except OSError:
            text = ""
        if args.json:
            print(json.dumps({"project": real, "relay": row, "text": text}, indent=2))
        else:
            print(text, end="" if text.endswith("\n") else "\n")
        return 0
    if args.json:
        print(json.dumps({"project": real, "relays": rows}, indent=2))
        return 0
    if not rows:
        print(f"no agent has handed this project to another yet: {real}")
        return 0
    print(f"{real} — who had the work when, newest first:")
    said = {"resumed": "its session went on by hand", "taken-back": "taken back",
            "sent-back": "sent back", "released": "released"}
    for x in rows:
        fa = AGENT_NAMES.get(x["from"].get("agent"), x["from"].get("agent") or "?")
        ta = AGENT_NAMES.get(x["to"].get("agent"), x["to"].get("agent") or "?")
        where = "" if _relay_here(x["to"]) else f" on {x['to'].get('machine')}"
        state = ("open: " + ta + " has it" if x["open"] else
                 "" if x["kind"] == "back" else
                 "summary only" if x["to"].get("mode") == "brief-only" else
                 said.get(x["closed_by"], "handed back"))
        print(f"  {time.strftime('%Y-%m-%d %H:%M', time.localtime(x['at'] or 0))}  "
              f"{RELAY_LABEL.get(x['kind'], x['kind']):<10} {fa} → {ta}{where}"
              + (f"   ({state})" if state else ""))
        print(f"      {x['id']}   aht relays {shlex.quote(real)} --show {x['id']}")
    return 0

# ---- the session board ----------------------------------------------------------- #

_AGENT_PROC = re.compile(r"(?:^|/)(kimi|codex|agy|gemini|opencode|cursor-agent|copilot)(?:\s|$)")
# agy's subcommands that hold no conversation: its daemons and its tools
AGY_NOT_SESSIONS = {"agent", "agents", "changelog", "help", "install", "mcp", "mic-serve",
                    "models", "plugin", "plugins", "remote-control", "update"}
# … and Codex's: its shared daemon (`codex app-server … --managed-daemon`),
# its servers, sign-in and tools
CODEX_NOT_SESSIONS = {"app-server", "apply", "cloud", "completion", "debug", "features",
                      "generate-ts", "help", "login", "logout", "mcp", "mcp-server",
                      "responses-api-proxy", "sandbox", "stdio-to-uds"}
NOT_SESSIONS = {"agy": AGY_NOT_SESSIONS, "codex": CODEX_NOT_SESSIONS}

def agent_processes() -> list:
    """Agent CLIs other than Claude Code that run right now, with their folder
    (Claude Code sessions have records of their own)."""
    try:
        r = subprocess.run(["ps", "-Ao", "pid=,args="], capture_output=True, text=True,
                           timeout=15, cwd="/")
    except Exception:
        return []
    pids = {}
    for line in r.stdout.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) < 2 or not parts[0].isdigit():
            continue
        words = parts[1].split()
        m = _AGENT_PROC.search(" ".join(words[:2]))
        if not m or any(f" {f} " in f" {parts[1]} " for f in ("-p", "--prompt", "--print")):
            continue
        if m.group(1) in NOT_SESSIONS:
            at = next((i for i, w in enumerate(words[:2])
                       if re.search(rf"(?:^|/){m.group(1)}$", w)), 0)
            if (words[at + 1:at + 2] or [""])[0] in NOT_SESSIONS[m.group(1)]:
                continue
        pids[int(parts[0])] = m.group(1)
    if not pids:
        return []
    cwd = {}
    if IS_LINUX:
        for pid in pids:
            try:
                cwd[pid] = os.readlink(f"/proc/{pid}/cwd")
            except OSError:
                pass
    else:
        lsof = next((c for c in ("/usr/sbin/lsof", "/usr/bin/lsof") if os.path.exists(c)), "lsof")
        try:
            r = subprocess.run([lsof, "-a", "-p", ",".join(map(str, pids)), "-d", "cwd", "-Fpn"],
                               capture_output=True, text=True, timeout=30, cwd="/")
            pid = None
            for line in r.stdout.splitlines():
                if line.startswith("p"):
                    pid = int(line[1:])
                elif line.startswith("n") and pid:
                    cwd[pid] = line[1:]
        except Exception:
            pass
    # one row per agent and folder: a CLI often runs as several processes
    rows = {}
    for pid, agent in pids.items():
        if pid in cwd and cwd[pid] != "/":
            rows.setdefault((agent, cwd[pid]), {"agent": agent, "project": cwd[pid],
                                                "pid": pid, "status": "running"})
    return list(rows.values())

_STATUS_WORDS = {"busy": "working", "shell": "working (a command runs)",
                 "waiting": "waiting for you", "idle": "idle"}

def open_sessions_here(names: bool = False) -> list:
    rows = []
    named, check, stops = {}, {}, {}
    if names:
        try:
            named = {r["pid"]: r for r in session_names()}
            check = {r["pid"]: r for r in session_checkup()}
            auto = claude_auto_continue()
            stops = {h["session"]: dict(h, auto=auto) for h in limit_stops(12) if not h["over"]}
        except Exception as e:
            warn(f"BOARD names: {e}")
    for s in running_sessions():
        n = named.get(s["pid"]) or {}
        c = check.get(s["pid"]) or {}
        stop = stops.get(s.get("session") or "")
        rows.append({"agent": "claude", "project": s["cwd"], "pid": s["pid"],
                     "session": s.get("session"), "name": s.get("name"),
                     "title": n.get("name"), "title_origin": n.get("origin"),
                     "tab": n.get("tab"), "pending_title": n.get("pending"),
                     "in_iterm": c.get("in_iterm"), "background": c.get("background"),
                     "issues": c.get("issues") or [], "can_restart": c.get("can_restart"),
                     "version": c.get("version"), "installed": c.get("installed"),
                     "limit": {k: stop.get(k) for k in ("resets", "until", "auto")}
                     if stop else None,
                     "status": _STATUS_WORDS.get(s["status"], s["status"]),
                     "raw_status": s["status"], "waiting_for": s.get("waiting_for"),
                     "since": s.get("since")})
    rows += agent_processes()
    return rows

def _agent_board(req: dict) -> dict:
    return {"ok": True, "host": _here(),
            "sessions": open_sessions_here(names=bool(req.get("names")))}

def session_board(remotes: bool = True, names: bool = False) -> list:
    """Open agent sessions on this machine and on every machine set up for
    handover (asked in parallel; one that does not answer is reported)."""
    import threading
    here = {"machine": _here(), "local": True, "reachable": True,
            "sessions": open_sessions_here(names)}
    boards = [here]
    if remotes and can_reach_machines():
        found = []
        def ask(name):
            row = {"machine": name, "local": False, "reachable": False, "sessions": []}
            try:
                rem = get_remote(name)
                ans = rem.agent("board", timeout=30, names=names)
                row.update(reachable=True, host=ans.get("host"), sessions=ans["sessions"])
            except HandoverError as e:
                row["error"] = str(e)
            found.append(row)
        ts = [threading.Thread(target=ask, args=(n,), daemon=True)
              for n in sorted(remotes_config())]
        for t in ts:
            t.start()
        for t in ts:
            t.join(timeout=45)
        boards += sorted(found, key=lambda r: r["machine"])
    away = {os.path.realpath(e["real_path"]): (e.get("away") or {})
            for e in load_registry().get("projects", {}).values() if e.get("away")}
    for b in boards:
        for s in b["sessions"]:
            a = away.get(os.path.realpath(s.get("project") or "/"))
            if a and not b["local"] and a.get("remote") == b["machine"]:
                s["handed_over"] = True
    return boards

def cmd_board(args):
    boards = session_board(remotes=not args.local, names=True)
    if args.json:
        print(json.dumps({"machines": boards}, indent=2))
        return 0
    for b in boards:
        print(f"{b['machine']}" + ("" if b["reachable"] else f"   — {b.get('error')}"))
        if b["reachable"] and not b["sessions"]:
            print("   no agent session open")
        for s in sorted(b["sessions"], key=lambda s: s.get("project") or ""):
            state = s["status"] + (f": {s['waiting_for']}" if s.get("waiting_for") else "")
            print(f"   {AGENT_NAMES.get(s['agent'], s['agent']):<12} {state:<28} "
                  f"{s.get('project')}" + ("   (handed over)" if s.get("handed_over") else "")
                  + (f"\n      “{s['title']}”" if s.get("title") else ""))
    return 0

# --------------------------------------------------------------------------- #
# Keeping an eye, cleaning up, looking back: notices when a session waits,
# tidying the registry, backups on another machine, what a session changed,
# a usage report, sharing a session, and taking a leaked key out of a history.
# --------------------------------------------------------------------------- #

# ---- notices: a session waits for you, or finished a long piece of work ---- #

def notices_state() -> Path:
    return aht_home() / "run" / "notices.json"

def send_to_phone(title: str, message: str) -> str:
    """Pass a notice on to the phone, if the user set that up:
    notify_phone = "imessage:<phone or Apple ID>" or "ntfy:<topic or URL>"."""
    target = str(cfg_get("notify_phone") or "")
    if os.environ.get("AHT_NOTIFY_LOG"):                 # tests: note it, send nothing
        with open(os.environ["AHT_NOTIFY_LOG"], "a") as fh:
            fh.write(json.dumps({"title": title, "message": message, "phone": target}) + "\n")
        return "logged"
    if target.startswith("imessage:") and IS_MAC:
        who = target.split(":", 1)[1].strip()
        script = ('on run argv\n tell application "Messages"\n'
                  '  set s to 1st account whose service type = iMessage\n'
                  '  send (item 1 of argv) to participant (item 2 of argv) of s\n'
                  ' end tell\nend run')
        r = subprocess.run(["osascript", "-e", script, f"{title}: {message}", who],
                           capture_output=True, text=True, timeout=30)
        return "sent" if r.returncode == 0 else "failed: " + (r.stderr or "").strip()[-160:]
    if target.startswith("ntfy:"):
        topic = target.split(":", 1)[1].strip()
        url = topic if topic.startswith("http") else "https://ntfy.sh/" + topic
        try:
            import urllib.request
            req = urllib.request.Request(url, data=message.encode(),
                                         headers={"Title": title.encode("ascii", "replace")})
            urllib.request.urlopen(req, timeout=15).read()
            return "sent"
        except Exception as e:
            return f"failed: {e}"
    return "off"

def app_running() -> bool:
    """The aht app marks itself alive every 20 seconds; it then shows the
    notices itself, so a click on one goes to the session."""
    try:
        return time.time() - (aht_home() / "run" / "app-alive").stat().st_mtime < 90
    except OSError:
        return False

def _notify(title: str, message: str, info: dict = None) -> None:
    if os.environ.get("AHT_NOTIFY_LOG"):
        send_to_phone(title, message)
        return
    notify_user(title, message, info)
    if cfg_get("notify_phone"):
        r = send_to_phone(title, message)
        if r.startswith("failed"):
            warn(f"NOTICE to the phone {r}")

def check_notices(remotes: bool = None) -> list:
    """Compare the open sessions with the last look and announce what changed:
    a session that now waits for you, and one that finished after working a
    while.  Every check also settles unfinished handovers (`handing`
    records: resolve_handing asks their machine).  Other machines' sessions
    are asked only while a project is handed over."""
    try:
        st = json.loads(notices_state().read_text())
    except Exception:
        st = {}
    seen, last_remote = st.get("seen") or {}, float(st.get("remote_at") or 0)
    projects = load_registry().get("projects", {})
    away = any(e.get("away") for e in projects.values())
    out = []
    for uid in [u for u, e in projects.items() if e.get("handing")]:
        try:                                # a handover that was cut off
            out += resolve_handing(uid)
        except Exception as e:
            warn(f"HANDOVER resolving an unfinished one: {e}")
    ask_remote = (remotes if remotes is not None else
                  away and time.time() - last_remote >= 55)
    boards = session_board(remotes=ask_remote and can_reach_machines())
    if ask_remote:
        last_remote = time.time()
    now, fresh = time.time(), {}
    finished_after = float(cfg_get("notify_finished_minutes", 3)) * 60
    for b in boards:
        if not b["reachable"]:
            # a machine that did not answer keeps what was known about it
            fresh.update({k: v for k, v in seen.items() if v.get("machine") == b["machine"]})
            continue
        for s in b["sessions"]:
            if s["agent"] != "claude":
                continue
            key = f"{b['machine']}:{s.get('pid')}:{s.get('session')}"
            raw = s.get("raw_status") or ""
            prev = seen.get(key) or {}
            busy_since = prev.get("busy_since") if prev.get("raw") in ("busy", "shell") else None
            if raw in ("busy", "shell") and busy_since is None:
                busy_since = now
            fresh[key] = {"machine": b["machine"], "raw": raw, "busy_since": busy_since,
                          "project": s.get("project")}
            name = os.path.basename(s.get("project") or "") or "a session"
            where = "" if b.get("local") else f" on {b['machine']}"
            if not prev:
                continue                          # first sight: nothing changed yet
            info = {"machine": b["machine"], "local": bool(b.get("local")), "pid": s.get("pid"),
                    "session": s.get("session"), "project": s.get("project")}
            if raw == "waiting" and prev.get("raw") != "waiting" and cfg_get("notify_waiting", True):
                out.append({"kind": "waiting", "title": f"{name}{where} waits for you",
                            "message": s.get("waiting_for") or "it needs an answer",
                            "info": dict(info, kind="waiting")})
            if raw == "idle" and prev.get("raw") in ("busy", "shell") and \
                    cfg_get("notify_finished", True) and prev.get("busy_since") and \
                    now - prev["busy_since"] >= finished_after:
                mins = int((now - prev["busy_since"]) // 60)
                out.append({"kind": "finished", "title": f"{name}{where} is done",
                            "message": f"the agent finished after {mins} minute(s)",
                            "info": dict(info, kind="finished")})
    told = list(st.get("limits_told") or [])
    if cfg_get("notify_limit", True):
        tgt = limit_switch_target()
        for h in limit_stops(12):
            key = f"{h['session']}:{int(h.get('at') or 0)}"
            if key in told:
                continue
            told.append(key)
            if h["over"]:
                continue
            name = os.path.basename(h.get("project") or "") or "a session"
            msg = f"resets {h['resets']}" if h.get("resets") else "no tokens left for now"
            if claude_auto_continue() and h.get("resets"):
                msg += " — it continues by itself then"
            elif tgt:
                msg += f" — open aht to go on in {AGENT_NAMES[tgt]}"
            out.append({"kind": "limit", "title": f"{name}: Claude's usage limit",
                        "message": msg, "info": {"kind": "limit", "session": h.get("session"),
                                                 "project": h.get("project")}})
    out += night_shift_tick()
    update_told = st.get("update_told")
    if cfg_get("update_check"):
        try:
            u = check_update()
        except Exception as e:
            warn(f"UPDATE {e}")
            u = {}
        if u.get("newer") and u.get("latest") != update_told:
            update_told = u["latest"]
            out.append({"kind": "update", "title": f"aht {u['latest']} is out",
                        "message": "open aht to see what's new and to upgrade",
                        "info": {"kind": "update", "version": u["latest"]}})
    notices_state().parent.mkdir(parents=True, exist_ok=True)
    tmp = notices_state().with_suffix(".new")
    tmp.write_text(json.dumps({"seen": fresh, "remote_at": last_remote, "at": now,
                               "limits_told": told[-200:], "update_told": update_told}))
    os.replace(tmp, notices_state())
    for n in out:
        _notify(n["title"], n["message"], n.get("info"))
        log(f"NOTICE {n['title']}: {n['message']}")
    return out

# ---- a new version of aht: off until turned on, since it asks GitHub -------- #

RELEASES_API = "https://api.github.com/repos/havurgiray/agent-history-tether/releases/latest"
RELEASES_PAGE = "https://github.com/havurgiray/agent-history-tether/releases/latest"
RELEASES_DOWNLOAD = "https://github.com/havurgiray/agent-history-tether/releases/download"

def update_state_path() -> Path:
    return aht_home() / "run" / "update.json"

def _version_tuple(v) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", str(v or ""))[:3])

def install_kind() -> str:
    """How this aht was installed, which says how to upgrade it: "brew",
    "scoop", "winget", "installer" (aht's Windows installer, also what winget
    runs now), "download" (a zip from the releases page) or "source" (a
    checkout)."""
    if os.environ.get("AHT_INSTALL_KIND"):              # tests: a stand-in
        return os.environ["AHT_INSTALL_KIND"]
    if IS_MAC:
        return "brew" if any(os.path.isdir(c) for c in ("/opt/homebrew/Caskroom/aht",
                                                        "/usr/local/Caskroom/aht")) \
            else "download"
    if os.name == "nt":
        if getattr(sys, "frozen", False) and any(Path(sys.executable).parent.glob("unins*.exe")):
            return "installer"
        scoop = Path(os.environ.get("SCOOP") or Path.home() / "scoop")
        if (scoop / "apps" / "aht").is_dir():
            return "scoop"
        pk = Path(os.environ.get("LOCALAPPDATA") or "") / "Microsoft" / "WinGet" / "Packages"
        try:
            if any(d.name.lower().startswith("havurgiray.aht") for d in pk.iterdir()):
                return "winget"
        except OSError:
            pass
        return "download"
    return "source"

# Windows cannot replace an exe that runs: the tray and the window stop first,
# and `aht install` starts the watcher again
_WIN_STOP = "taskkill /im aht-tray.exe /f >nul 2>&1 & taskkill /im aht.exe /f >nul 2>&1 & "
UPGRADE_COMMANDS = {"brew": "brew upgrade --cask aht && aht install && open -a aht",
                    "scoop": _WIN_STOP + "scoop update aht && aht install --here",
                    "winget": _WIN_STOP + "winget upgrade --id havurgiray.aht && aht install"}

def installer_asset(version: str) -> str:
    """The name of the Windows installer of `version` for this computer's CPU."""
    arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
    return f"aht-setup-{version}-windows-{arch}.exe"

def _window_serving() -> bool:
    """Whether aht's window runs now: its run/window.json names a live process."""
    try:
        st = json.loads((aht_home() / "run" / "window.json").read_text())
        return _pid_alive(int(st["pid"]))
    except Exception:
        return False

def _upgrade_with_installer(version: str) -> int:
    """Download the release's installer, check it against the release's
    SHA256SUMS.txt and run it: it closes aht, puts the new one in its place
    and starts it again."""
    import urllib.request
    name = installer_asset(version)
    base = os.environ.get("AHT_RELEASES_DOWNLOAD") or RELEASES_DOWNLOAD
    for old in (aht_home() / "run").glob("aht-setup-*.exe"):   # earlier upgrades'
        try:
            old.unlink()
        except OSError:
            pass

    def get(url: str) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": f"aht/{VERSION}"})
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.read()
    try:
        sums = get(f"{base}/v{version}/SHA256SUMS.txt").decode("utf-8")
        want = next((ln.split()[0].lower() for ln in sums.splitlines()
                     if ln.split()[1:] and ln.split()[1].lstrip("*") == name), None)
        if not want:
            print(f"{name} is not part of aht {version}; the download page has it: "
                  f"{RELEASES_PAGE}")
            return 1
        data = get(f"{base}/v{version}/{name}")
    except Exception as e:
        print(f"could not download aht {version}: {e}")
        return 1
    if hashlib.sha256(data).hexdigest() != want:
        print(f"the download of {name} does not match its checksum; nothing was run")
        return 1
    dest = aht_home() / "run" / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    # its own process: the installer closes this aht too
    kw = {"creationflags": 0x00000008 | 0x00000200} if os.name == "nt" \
        else {"start_new_session": True}                  # DETACHED, NEW_PROCESS_GROUP
    if os.name != "nt":
        dest.chmod(0o755)                                  # the tests' stand-in
    # the installer stops aht's window too: it opens it again when it was open
    subprocess.Popen([str(dest), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"]
                     + (["/OPENWINDOW=1"] if _window_serving() else []),
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, close_fds=True, **kw)
    print(f"the installer of aht {version} runs now; aht starts again when it is done")
    return 0

def check_update(force: bool = False, fetch: bool = True) -> dict:
    """The newest release and whether it is newer than this aht.  GitHub is
    asked at most once a day and only when update_check is on, or when
    `force` (someone asked just now); it sees this computer's address and
    "aht/<version>", nothing else.  `fetch` False: only what is known."""
    try:
        st = json.loads(update_state_path().read_text())
    except Exception:
        st = {}
    on = bool(cfg_get("update_check"))
    due = time.time() - float(st.get("checked") or 0) >= 86400
    if fetch and (force or (on and due)):
        import urllib.request
        url = os.environ.get("AHT_UPDATE_URL") or RELEASES_API
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": f"aht/{VERSION}", "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=10) as r:
                rel = json.loads(r.read().decode("utf-8"))
            st.update({"latest": str(rel.get("tag_name") or "").lstrip("v") or None,
                       "notes": str(rel.get("body") or ""),
                       "url": rel.get("html_url") or RELEASES_PAGE,
                       "published": rel.get("published_at"), "error": None})
        except Exception as e:
            st["error"] = str(e)[:300]
            warn(f"UPDATE check: {st['error']}")
        st["checked"] = time.time()
        _write_json(update_state_path(), st)
    kind = install_kind()
    latest = st.get("latest")
    return {"enabled": on, "current": VERSION, "latest": latest,
            "newer": bool(latest) and _version_tuple(latest) > _version_tuple(VERSION),
            "notes": st.get("notes") or "", "url": st.get("url") or RELEASES_PAGE,
            "published": st.get("published"), "checked": st.get("checked"),
            "error": st.get("error"), "how": kind, "upgrade": UPGRADE_COMMANDS.get(kind),
            "installer": installer_asset(latest) if kind == "installer" and latest else None}

def _open_page(url: str) -> bool:
    """Open a web page in the browser: an https one only."""
    if not str(url).startswith("https://"):
        return False
    if os.environ.get("AHT_OPEN_LOG"):              # tests: note it, open nothing
        with open(os.environ["AHT_OPEN_LOG"], "a") as fh:
            fh.write(url + "\n")
        return True
    import webbrowser
    try:
        return bool(webbrowser.open(url))
    except Exception:
        return False

def cmd_update(args):
    u = check_update(force=args.now or args.upgrade)
    if args.upgrade:
        if not u["newer"]:
            print(f"aht {VERSION} is the latest" if u["latest"] else
                  f"could not learn the latest version: {u['error']}")
            return 0 if u["latest"] else 1
        if u["upgrade"]:
            return open_terminal(u["upgrade"], "upgrade-aht")
        if u["how"] == "installer":
            return _upgrade_with_installer(u["latest"])
        page = u["url"] if str(u["url"]).startswith("https://") else RELEASES_PAGE
        if u["how"] == "source":            # install.sh copies the new files in
            step = "linux/install.sh" if IS_LINUX else "install.sh"
            print(f"aht {u['latest']} is out. In your checkout: git pull, then run "
                  f"{step} again.  {page}")
            _open_page(page)
            return 0
        print(f"opened {page}" if _open_page(page) else f"the download page: {page}")
        return 0
    if args.json:
        print(json.dumps(u, indent=2))
    elif u["newer"]:
        print(f"aht {u['latest']} is out (this is {VERSION}): {u['url']}")
        if u["upgrade"]:
            print(f"Upgrade:  aht update --upgrade   ({u['upgrade']})")
        elif u["installer"]:
            print(f"Upgrade:  aht update --upgrade   (downloads and runs {u['installer']})")
    elif u["latest"]:
        print(f"aht {VERSION} is the latest")
    elif u["error"]:
        print(f"could not ask GitHub: {u['error']}")
    else:
        print("aht does not look for new versions: `aht update --now` asks GitHub once, "
              "`aht config --set update_check=true` once a day")
    return 0

def cmd_notices(args):
    if args.test:
        _notify("aht", "This is how a notice from aht looks.")
        print(("sent to this Mac" if IS_MAC else "sent to this computer") + ("" if not cfg_get("notify_phone")
                                    else f" and to {cfg_get('notify_phone')}"))
        return 0
    got = check_notices()
    if args.json:
        print(json.dumps({"notices": got}, indent=2))
    elif not args.quiet:
        for n in got:
            print(f"{n['title']}: {n['message']}")
    return 0

# ---- tidy up ---------------------------------------------------------------- #

def _last_activity(entry: dict):
    try:
        return _hist_stats(entry).get("last_activity")
    except Exception:
        return None

def _strong(c: dict) -> bool:
    """A suggestion worth showing: the same folder name, the exact old path,
    or at least three of the files the sessions worked on."""
    for r in c.get("reasons", []):
        if r in ("leaf-name", "exact-encode", "same name"):
            return True
        m = re.match(r"files (\d+)/(\d+)", r)
        if m and int(m.group(1)) >= 3:
            return True
    return False

def _latest_jsonl(d: Path):
    try:
        files = [f for f in d.glob("*.jsonl") if f.is_file()]
    except OSError:
        return None
    return max(files, key=lambda f: f.stat().st_mtime, default=None)

def tidy_history_text(key: str, max_sessions: int = 10, per_session: int = 40) -> dict:
    """A history Tidy Up lists, as text to read before deciding: each
    session (newest first) with its title, dates and what was said — the
    last `per_session` messages of each.  Keys and passwords are masked."""
    reg = load_registry()
    root = claude_backend().root()
    sessions, path = [], None
    def claude_files(d):
        return [{"agent": "claude", "id": f.stem, "file": str(f), "updated": f.stat().st_mtime}
                for f in (d.glob("*.jsonl") if d.is_dir() else []) if f.is_file()]
    e = reg.get("projects", {}).get(key)
    if e:                                   # a tracked folder that is gone
        path = e["real_path"]
        store = (e.get("stores") or {}).get("claude") or _key_claude(path)
        sessions += claude_files(root / store)
        sessions += list_sessions(path, agents=["kimi", "codex"])
    elif key and (d := _history_entry(root, key, links=True)) is not None:
        # one of the history folder's own entries, as Tidy Up lists them:
        # never "..", a backslash or a drive letter that leads out of it
        path = transcript_cwd(d) or key
        sessions += claude_files(d)
    else:
        return {"key": key, "error": "no such history"}
    sessions.sort(key=lambda x: x.get("updated") or 0, reverse=True)
    L = [f"# History of {path}", "",
         f"{len(sessions)} session(s), newest first. Up to the last {per_session} messages "
         "of each are shown; keys and passwords are masked."]
    for x in sessions[:max_sessions]:
        title, first, last, msgs = x.get("title"), None, None, []
        try:
            for _end, ev in session_events(x["agent"], x["file"]):
                if ev.get("t"):
                    first = first or ev["t"]
                    last = ev["t"]
                if ev["role"] == "title":
                    title = ev["text"]
                elif ev["role"] in ("user", "agent", "summary"):
                    msgs.append(ev)
        except OSError:
            continue
        span = " – ".join(dict.fromkeys(time.strftime("%Y-%m-%d", time.localtime(t))
                                        for t in (first, last) if t))
        L += ["", f"## {title or 'untitled'}", "",
              f"{AGENT_NAMES.get(x['agent'], x['agent'])} · {span or 'no date'} · "
              f"{len(msgs)} message(s) · `{x['id']}`"]
        if len(msgs) > per_session:
            L += ["", f"*… {len(msgs) - per_session} earlier message(s)*"]
        for ev in msgs[-per_session:]:
            who = {"user": "You", "agent": "Agent", "summary": "Summary"}[ev["role"]]
            L += ["", f"**{who}:** " + _masked(ev["text"], 1500)]
    if len(sessions) > max_sessions:
        L += ["", f"*… and {len(sessions) - max_sessions} older session(s)*"]
    return {"key": key, "path": path, "sessions": len(sessions),
            "markdown": redact("\n".join(L))}

def tidy_report(roots: list = None) -> dict:
    """What needs a decision: tracked folders that are gone, histories that no
    tracked folder owns, and folders listed twice — each with suggestions."""
    roots = roots or default_roots()
    reg = load_registry()
    dirs = list_real_dirs(roots)
    by_leaf = {}
    for d in dirs:
        by_leaf.setdefault(os.path.basename(d).lower(), []).append(d)
    missing, gone_stores = [], set()
    for uid, e in sorted(reg.get("projects", {}).items(), key=lambda kv: kv[1]["real_path"]):
        if os.path.isdir(e["real_path"]):
            continue
        cands = [{"path": d, "reasons": ["same name"]}
                 for d in by_leaf.get(os.path.basename(e["real_path"]).lower(), [])
                 if not read_marker(d) or read_marker(d) == uid][:5]
        store = (e.get("stores") or {}).get("claude")
        if store and (claude_backend().root() / store).is_dir():
            sc = score_candidates(store, roots, 5, dirs=dirs)["candidates"]
            for c in sc:
                if c["path"] not in [x["path"] for x in cands] and not read_marker(c["path"]) \
                        and _strong(c):
                    cands.append({"path": c["path"], "reasons": c["reasons"]})
        st = _hist_stats(e)
        if not store and (claude_backend().root() / _key_claude(e["real_path"])).is_dir():
            store = _key_claude(e["real_path"])  # filed under the path, not yet linked
        latest = _latest_jsonl(claude_backend().root() / store) if store else None
        agents = agents_of(e.get("stores") or {})
        if latest and "claude" not in agents:
            agents = ["claude"] + agents
        if store:
            gone_stores.add(store)
        missing.append({"uuid": uid, "path": e["real_path"], "agents": agents,
                        "last": st.get("last_activity"), "sessions": st.get("sessions", 0),
                        "bytes": st.get("bytes", 0),
                        "title": _session_title({"agent": "claude", "file": str(latest)})
                        if latest else None,
                        "history": str(claude_backend().root() / store) if store else None,
                        "candidates": cands[:5]})
    orphans = []
    gone_stores = {_fold_name(n) for n in gone_stores}
    for d in orphan_history_dirs(reg):
        if _fold_name(d.name) in gone_stores or not _dir_has_entries(d):
            continue                        # (a gone folder's history is listed with it)
        sess = [f for f in d.glob("*.jsonl") if f.is_file()]
        last = max((f.stat().st_mtime for f in sess), default=None)
        cwd = transcript_cwd(d)
        if cwd and _inside(os.path.realpath(cwd), os.path.realpath(str(aht_home()))):
            continue                        # a second opinion's copy, not a project
        sc = score_candidates(d.name, roots, 5, dirs=dirs)
        latest = _latest_jsonl(d)
        orphans.append({"store": d.name, "was": cwd, "sessions": len(sess),
                        "link": _is_link(d),            # aht never removes one
                        "bytes": sum(f.stat().st_size for f in d.rglob("*") if f.is_file()),
                        "title": _session_title({"agent": "claude", "file": str(latest)})
                        if latest else None, "history": str(d),
                        "last": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(last))
                        if last else None,
                        "candidates": [c for c in sc["candidates"]
                                       if (not read_marker(c["path"]) or c["path"] == cwd)
                                       and _strong(c)][:5]})
    return {"missing": missing, "orphans": orphans, "doubles": stale_doubles(reg)}

def cmd_tidy(args):
    if args.show:
        res = tidy_history_text(args.show)
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print(res.get("markdown") or res.get("error"))
        return 0 if res.get("markdown") else 1
    if args.remove_history:
        res = remove_orphan_history(args.remove_history, args.apply)
        bin_ = _trash_name()
        done = ("deleted for good, since it could not go to the Recycle Bin"
                if res.get("deleted") else f"moved to the {bin_}")
        # refused: the name and why, never what it would have done
        lines = [res["store"] if res["blockers"] else
                 f"{done if res['applied'] else 'would move to the ' + bin_}: {res['store']}"]
        if res.get("was"):
            lines.append(f"   the history of {res['was']} ({res.get('sessions', 0)} session(s))")
        if not args.apply and not res["blockers"]:
            lines.append("(dry run — pass --apply to do it)")
        return _emit(args, res, lines)
    if args.relink:
        uid, dst = args.relink, os.path.realpath(args.to or "")
        reg = load_registry()
        e = reg.get("projects", {}).get(uid)
        if e is None or not os.path.isdir(dst):
            print("name a tracked project (--relink UUID) and an existing folder (--to)",
                  file=sys.stderr)
            return 2
        if read_marker(dst) and read_marker(dst) != uid:
            print(f"{dst} belongs to another tracked project already", file=sys.stderr)
            return 3
        if not args.apply:
            print(f"would relink {e['real_path']}  →  {dst}")
            return 0
        write_marker(dst, uid)
        return _tidy_relink(dst, args.json)
    rep = tidy_report()
    if args.json:
        print(json.dumps(rep, indent=2))
        return 0
    print(f"{len(rep['missing'])} tracked folder(s) are gone, {len(rep['orphans'])} "
          f"history store(s) have no folder, {len(rep['doubles'])} folder(s) are listed twice")
    for m in rep["missing"]:
        print(f"\n  gone: {m['path']}   [{', '.join(m['agents']) or 'no history'}]")
        for c in m["candidates"]:
            print(f"     maybe now: {c['path']}  ({', '.join(c['reasons'])})")
            print(f"        aht tidy --relink {m['uuid']} --to {shlex.quote(c['path'])} --apply")
        print(f"     or forget it (its history stays):  aht forget --uuid {m['uuid']} --apply")
    for o in rep["orphans"]:
        print(f"\n  no folder: {o['store']}  ({o['sessions']} session(s), was {o['was'] or '?'})")
        for c in o["candidates"]:
            print(f"     maybe: {c['path']}  ({', '.join(c['reasons'])})")
            print(f"        aht bind --store={o['store']} --to={shlex.quote(c['path'])} --apply")
        if o["link"]:
            print(f"     {LINK_ENTRY}")
        else:
            print(f"     or move it to the {_trash_name()}:  "
                  f"aht tidy --remove-history={o['store']} --apply")
    if rep["doubles"]:
        print("\n  listed twice: remove the stale entries with  aht prune --apply")
    return 0

def _to_recycle_bin(path: Path) -> str:
    """Windows: the Recycle Bin, through the shell (its Restore works) ->
    "trash"; "deleted" when Windows deleted it for good instead (what
    _bin_refusal could not foresee); "" when it is still there.  The shell
    says only that the item is gone, so the bin itself tells which: it holds
    one item more, or the item."""
    before, t0 = _bin_items(path), time.time()
    if not _shell_delete(path):
        return ""
    after = _bin_items(path)
    if (before is not None and after is not None and after > before) \
            or _in_recycle_bin(path, t0):
        return "trash"
    return "deleted"

_BITBUCKET = r"Software\Microsoft\Windows\CurrentVersion\Explorer\BitBucket"
_EXPLORER_POLICY = r"Software\Microsoft\Windows\CurrentVersion\Policies\Explorer"

def _trash_refusal(path: Path, size: int) -> str:
    """Why `path` (`size` bytes) would not go to the Trash but be deleted for
    good, as far as aht can tell before it tries; "" when it would go there.
    Only Windows deletes for good what its Recycle Bin does not take."""
    if os.name != "nt" or os.environ.get("AHT_TRASH"):
        return ""
    return _bin_refusal(path, size)

def _bin_refusal(path: Path, size: int) -> str:
    """Windows: why `path` would not go to the Recycle Bin: that drive has
    none, its bin is set to remove files at once, or `size` is more than
    that bin holds; "" when it would go there, or when aht cannot read the
    settings (the check after the delete still tells)."""
    left = "so Windows would delete it for good (you can still delete it yourself)"
    if _bin_items(path) is None:
        return f"that drive has no Recycle Bin, {left}"
    nuke, cap = _bin_settings(path)
    if nuke:
        return f"the Recycle Bin of that drive is set to remove files at once, {left}"
    if cap is not None and size > cap:
        return (f"it is bigger ({_human(size)}) than the Recycle Bin of that drive holds "
                f"({_human(cap)}), {left}")
    return ""

def _bin_default_cap(total: int) -> int:
    """The most a Recycle Bin holds when nobody set it: 10% of the first
    40 GB of the drive and 5% of the rest."""
    first = 40 * 1024 ** 3
    return min(total, first) // 10 + max(total - first, 0) // 20

def _bin_settings(path: Path) -> tuple:
    """Windows: the settings of the Recycle Bin of the drive `path` is on, as
    Windows applies them -> (removes files at once, the most it holds in
    bytes), None for what aht cannot read.  The policy "Do not move deleted
    files to the Recycle Bin" comes first, then that volume's own values
    (the bin's Properties), then BitBucket's own, then Windows' defaults."""
    import ctypes
    import winreg

    def dword(hive, key, name):
        try:
            with winreg.OpenKey(hive, key) as k:
                v, kind = winreg.QueryValueEx(k, name)
            return v if kind == winreg.REG_DWORD else None
        except OSError:
            return None
    k32 = ctypes.windll.kernel32
    mount, vol = ctypes.create_unicode_buffer(1024), ctypes.create_unicode_buffer(64)
    try:
        ok = k32.GetVolumePathNameW(os.path.abspath(str(path)), mount, 1024) \
            and k32.GetVolumeNameForVolumeMountPointW(mount.value, vol, 64)
    except Exception:
        ok = False
    guid = re.search(r"\{[0-9A-Fa-f-]{36}\}", vol.value) if ok else None
    if not guid:
        return None, None
    hkcu, own = winreg.HKEY_CURRENT_USER, _BITBUCKET + "\\Volume\\" + guid.group(0)
    if any(dword(h, _EXPLORER_POLICY, "NoRecycleFiles") == 1
           for h in (winreg.HKEY_LOCAL_MACHINE, hkcu)):
        nuke = True
    else:
        v = dword(hkcu, own, "NukeOnDelete")
        nuke = bool(dword(hkcu, _BITBUCKET, "NukeOnDelete") if v is None else v)
    mb = dword(hkcu, own, "MaxCapacity")
    if mb is None:
        mb = dword(hkcu, _BITBUCKET, "MaxCapacity")
    if mb is not None:
        return nuke, mb * 1024 * 1024
    total = ctypes.c_ulonglong(0)
    try:
        if k32.GetDiskFreeSpaceExW(mount.value, None, ctypes.byref(total), None):
            return nuke, _bin_default_cap(total.value)
    except Exception:
        pass
    return nuke, None

def _bin_items(path: Path):
    """Windows: how many items the Recycle Bin of the drive `path` is on
    holds; None where Windows does not say (that drive has no bin)."""
    import ctypes

    class Info(ctypes.Structure):                        # SHQUERYRBINFO
        _pack_ = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 1
        _fields_ = [("cbSize", ctypes.c_uint32), ("i64Size", ctypes.c_int64),
                    ("i64NumItems", ctypes.c_int64)]
    info = Info(ctypes.sizeof(Info), 0, 0)
    root = os.path.splitdrive(os.path.abspath(str(path)))[0] + "\\"
    try:
        r = ctypes.windll.shell32.SHQueryRecycleBinW(root, ctypes.byref(info))
    except Exception:
        return None
    return int(info.i64NumItems) if r == 0 else None

def _in_recycle_bin(path: Path, since: float) -> bool:
    """Windows: whether the Recycle Bin of the drive `path` was on took it in
    since `since` (for when a full bin let older items go).  Each item there
    has a $I file that says where it came from: after 24 bytes, the path in
    260 characters (before Windows 10) or its length and then the path."""
    want = os.path.normcase(os.path.abspath(str(path)))
    top = Path(os.path.splitdrive(want)[0] + "\\$Recycle.Bin")
    try:
        bins = [b for b in top.iterdir() if b.is_dir()]
    except OSError:
        return False
    for b in bins:                                       # one per user: only ours opens
        try:
            infos = [f for f in b.glob("$I*") if f.stat().st_mtime >= since - 5]
        except OSError:
            continue
        for f in infos:
            try:
                data = f.read_bytes()
            except OSError:
                continue
            if int.from_bytes(data[:8], "little") == 2:
                raw = data[28:28 + 2 * int.from_bytes(data[24:28], "little")]
            else:
                raw = data[24:24 + 520]
            was = raw.decode("utf-16-le", "replace").split("\0")[0]
            if was and os.path.normcase(was) == want:
                return True
    return False

def _shell_delete(path: Path) -> bool:
    """Windows: the shell's delete to the Recycle Bin -> whether `path` is gone."""
    import ctypes
    from ctypes import wintypes

    class Op(ctypes.Structure):                          # SHFILEOPSTRUCTW
        _pack_ = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 1
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT),
                    ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                    ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]
    # FO_DELETE; FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
    # | FOF_WANTNUKEWARNING.  What its bin does not take the shell deletes for
    # good, on a drive with no bin without asking: so aht refuses that before
    # (_bin_refusal) and checks after (_to_recycle_bin), and counts on no
    # question; the list of paths ends in two NULs (ctypes adds the second)
    op = Op(None, 3, os.path.abspath(str(path)) + "\0", None,
            0x0040 | 0x0010 | 0x0004 | 0x0400 | 0x4000, False, None, None)
    try:
        r = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    except Exception:
        return False
    return r == 0 and not op.fAnyOperationsAborted and not path.exists()

def _freedesktop_trash(path: Path) -> bool:
    """Linux: the desktop's Trash (~/.local/share/Trash), where the file
    manager can restore it from: the item in files/, where it came from in
    info/<name>.trashinfo."""
    import urllib.parse
    home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "Trash"
    try:
        for d in (home / "files", home / "info"):
            d.mkdir(parents=True, exist_ok=True, mode=0o700)
        name, n = path.name, 1
        while True:                                     # a name free in both folders
            info = home / "info" / f"{name}.trashinfo"
            if not (home / "files" / name).exists():
                try:
                    fd = os.open(str(info), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    break
                except FileExistsError:
                    pass
            n += 1
            name = f"{path.name}.{n}"
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("[Trash Info]\nPath=" + urllib.parse.quote(os.path.abspath(str(path)))
                     + "\nDeletionDate=" + time.strftime("%Y-%m-%dT%H:%M:%S") + "\n")
        try:
            shutil.move(str(path), str(home / "files" / name))
        except OSError:
            info.unlink()
            return False
        return True
    except OSError:
        return False

def _trash_name() -> str:
    """What this system calls the place a removed history goes to."""
    return "Recycle Bin" if os.name == "nt" else "Trash"

def _to_trash(path: Path) -> str:
    """Move a file or folder to the Trash: Finder's Put Back, the Recycle
    Bin's Restore or the Linux desktop's Trash works for it -> "trash";
    "deleted" when Windows deleted it for good instead; "" when it stayed."""
    if os.environ.get("AHT_TRASH"):                     # tests: a stand-in Trash
        dst = Path(os.environ["AHT_TRASH"]) / path.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(dst))
        return "trash"
    if os.name == "nt":
        return _to_recycle_bin(path)
    if not IS_MAC:
        if _have("gio"):
            try:
                subprocess.run(["gio", "trash", str(path)], capture_output=True, timeout=120,
                               cwd="/")
            except (OSError, subprocess.SubprocessError):
                pass
            if not path.exists():
                return "trash"
        return "trash" if _freedesktop_trash(path) else ""
    if os.path.exists("/usr/bin/trash"):
        r = subprocess.run(["/usr/bin/trash", str(path)], capture_output=True, timeout=120,
                           cwd="/")
        if r.returncode == 0 and not path.exists():
            return "trash"
    bin_ = Path.home() / ".Trash"
    if not bin_.is_dir():
        return ""
    dst = bin_ / path.name
    if dst.exists():
        dst = bin_ / f"{path.name} {_stamp()}"
    shutil.move(str(path), str(dst))
    return "trash"

def _history_entry(root: Path, name: str, links: bool = False):
    """The folder `name` in Claude's history folder, only when it is one of
    that folder's own entries as listed on disk, spelled exactly so, and a
    real folder (no link, junction or other reparse point; with `links`, to
    only read it, a link to a folder will do).  Separators, "..", drive
    letters and other spellings then name nothing."""
    try:
        with os.scandir(root) as it:
            for e in it:
                if e.name != name:
                    continue
                if links:
                    return root / e.name if e.is_dir() else None
                st = e.stat(follow_symlinks=False)
                if e.is_symlink() or not stat.S_ISDIR(st.st_mode) \
                        or getattr(st, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                    return None
                return root / e.name
    except OSError:
        pass
    return None

LINK_ENTRY = "it is a link to a folder elsewhere, not a history folder: aht leaves it alone"

def _is_link(p) -> bool:
    """A symbolic link, or on Windows a junction or another reparse point."""
    try:
        st = os.lstat(str(p))
    except OSError:
        return False
    return stat.S_ISLNK(st.st_mode) \
        or bool(getattr(st, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)

def _history_link(root: Path, name: str) -> bool:
    """Whether `name` is one of the entries of Claude's history folder,
    spelled exactly so, that is a link: Tidy Up lists it (it can be read),
    but aht never removes it."""
    try:
        with os.scandir(root) as it:
            return any(e.name == name and _is_link(root / e.name) for e in it)
    except OSError:
        return False

def remove_orphan_history(store: str, apply: bool = False) -> dict:
    """A Claude Code history that no tracked folder owns goes to the Trash —
    only when the user asks, and never one a tracked project owns or a
    session uses.  The daily history backups keep it as well.  On Windows
    it goes only to the Recycle Bin: what would be deleted for good (that
    drive has no bin, its bin removes files at once, too big for it) is
    refused before; should Windows still delete it for good, "deleted" is
    true as well as "applied"."""
    root = claude_backend().root()
    d = _history_entry(root, store)
    res = {"store": store, "applied": False, "blockers": []}
    if d is None:
        res["blockers"].append(LINK_ENTRY if _history_link(root, store)
                               else "there is no such history")
        return res
    owned = registered_history_dirs(load_registry())
    # the name as the file system compares it, or the very folder under
    # another name: Windows records ...-code-App for the folder ...-code-app
    if _fold_name(store) in {_fold_name(n) for n in owned} \
            or any(_same_folder(d, root / n) for n in owned):
        res["blockers"].append("a tracked project owns this history; use Forget for the "
                               "project instead")
        return res
    was = transcript_cwd(d)
    files = [f for f in d.rglob("*") if f.is_file()]
    res.update(was=was, sessions=len(list(d.glob("*.jsonl"))),
               bytes=sum(f.stat().st_size for f in files))
    if was and any(os.path.realpath(x["cwd"]) == os.path.realpath(was)
                   for x in running_sessions()):
        res["blockers"].append("a Claude Code session is open in that folder")
    why = _trash_refusal(d, res["bytes"])
    if why:
        res["blockers"].append(why)
    if not apply or res["blockers"]:
        return res
    how = _to_trash(d)
    res["applied"] = bool(how)
    if how == "deleted":
        res["deleted"] = True
    if not res["applied"]:
        res["blockers"].append(f"it could not be moved to the {_trash_name()}")
    log(f"TIDY history {store} (was {was}) "
        + ("deleted for good: it could not go to the Recycle Bin" if how == "deleted"
           else f"to the {_trash_name()}: {res['applied']}"))
    return res

def _tidy_relink(dst: str, as_json: bool) -> int:
    """A tracked folder found again: its marker is in place, so this is a
    move, and reconcile relinks every agent's history to it."""
    import contextlib, io
    roots = default_roots()
    if not any(_inside(dst, os.path.realpath(r)) for r in roots):
        roots = roots + [os.path.dirname(dst)]     # found outside the watched folders
    with contextlib.redirect_stdout(io.StringIO()):
        cmd_reconcile(argparse.Namespace(
            roots=roots, apply=True, notify=False,
            moves="apply", copies="ignore", only=[dst], clear_declines=False))
    uid, e = _entry_for(load_registry(), dst)
    if as_json:
        print(json.dumps({"relinked": bool(e), "path": dst, "uuid": uid}, indent=2))
    else:
        print(f"relinked: {dst}" if e else f"could not relink {dst}")
    return 0 if e else 1

# ---- history backups on another machine too --------------------------------- #
#
# There they go into ~/.aht/offsite/<this install's machine id>/backups, a
# folder of its own for every computer, also for two of one name.  Copying
# only adds.  A backup there is removed only when this computer sent it,
# pruned it here itself, and OFFSITE_FLOOR newer ones of that project stay.
# The copies made before a rewrite (<project id>/rewrites/…) go too and are
# never removed there: they are kept until the user deletes them here.
# Fetching adds what is missing here and never overwrites.

OFFSITE_FLOOR = 3
_SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")

def offsite_remote():
    name = cfg_get("offsite_backup")
    return get_remote(name) if name else None

def offsite_state_path() -> Path:
    return aht_home() / "offsite.json"

def _offsite_state() -> dict:
    try:
        d = json.loads(offsite_state_path().read_text())
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}

def _backup_files(root: Path) -> dict:
    """{"<project id>/<file>": size} of the backups under `root`: each zip
    and its .meta.json, and every copy made before a rewrite
    ("<project id>/rewrites/<…>")."""
    out = {}
    try:
        for d in root.iterdir() if root.is_dir() else []:
            if not d.is_dir() or not _SAFE_NAME.fullmatch(d.name):
                continue
            for f in d.iterdir():
                if f.is_file() and f.name.endswith((".zip", ".meta.json")):
                    out[f"{d.name}/{f.name}"] = f.stat().st_size
            rw = d / "rewrites"
            if rw.is_dir() and not rw.is_symlink():
                for dp, _dns, fns in os.walk(rw):
                    for n in fns:
                        f = Path(dp) / n
                        if f.is_file() and not f.is_symlink():
                            out[f.relative_to(root).as_posix()] = f.stat().st_size
    except OSError:
        pass
    return out

def _is_snapshot(rel: str) -> bool:
    """A backup's zip ("<project id>/<stamp>.zip"), not a rewrite's copy."""
    return rel.count("/") == 1 and rel.endswith(".zip")

def _offsite_root() -> Path:
    return aht_home() / "offsite"

def _agent_offsite_list(req: dict) -> dict:
    """The backup folders here, one per computer that copies its backups to
    this machine; with `files`, what is in the folders named."""
    rows, files, root = [], {}, _offsite_root()
    want = set(req.get("files") or [])
    for d in sorted(root.iterdir()) if root.is_dir() else []:
        if not d.is_dir() or not _SAFE_NAME.fullmatch(d.name):
            continue
        try:
            m = json.loads((d / "machine.json").read_text())
        except Exception:
            m = None                        # an older aht's folder: named by the computer
        b = _backup_files(d / "backups")
        zips = [k for k in b if _is_snapshot(k)]
        newest = max((_quiet_value(lambda k=k: (d / "backups" / k).stat().st_mtime) or 0
                       for k in b), default=0)
        rows.append({"id": d.name if m else None, "folder": d.name,
                     "name": (m or {}).get("name") or d.name,
                     "system": (m or {}).get("system"),
                     "updated": (m or {}).get("updated")
                     or (time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(newest))
                         if newest else None),
                     "projects": len({k.split("/")[0] for k in zips}), "files": len(zips),
                     "bytes": sum(b.values()), "legacy": m is None})
        if d.name in want:
            files[d.name] = b
    return {"ok": True, "folders": rows, "files": files}

def _agent_offsite_adopt(req: dict) -> dict:
    """Make the folder of the computer `id` (its machine.json says which
    computer it is).  With `legacy`, an older aht's folder of that computer's
    name is taken over: its backups and rewrites' copies move in; one already
    there with the same size is dropped, one of another size stays where it
    is."""
    mid = str(req.get("id") or "")
    if not re.fullmatch(r"[0-9a-f]{12}", mid):
        return {"ok": False, "error": "no computer id"}
    dst = _offsite_root() / mid / "backups"
    dst.mkdir(parents=True, exist_ok=True)
    m = req.get("machine") or {}
    _write_json(dst.parent / "machine.json",
                {"id": mid, "name": str(m.get("name") or ""), "system": m.get("system"),
                 "updated": m.get("updated") or _now()})
    adopted = []
    old = str(req.get("legacy") or "")
    src = _offsite_root() / old / "backups"
    if old and _SAFE_NAME.fullmatch(old) and old != mid \
            and not (src.parent / "machine.json").exists():
        for rel, size in sorted(_backup_files(src).items()):
            here, there = src / rel, dst / rel
            try:
                if there.exists():
                    if there.stat().st_size == size:
                        here.unlink()
                    continue
                there.parent.mkdir(parents=True, exist_ok=True)
                os.replace(here, there)
                adopted.append(rel)
            except OSError:
                continue
        for d in sorted(src.parent.rglob("*"), reverse=True) + [src.parent]:
            try:
                d.rmdir()                   # empty folders only
            except OSError:
                pass
    return {"ok": True, "adopted": adopted}

def _agent_offsite_prune(req: dict) -> dict:
    """Remove backups that the computer `id` sent here and has pruned itself;
    the newest OFFSITE_FLOOR of each project always stay."""
    mid = str(req.get("id") or "")
    if not re.fullmatch(r"[0-9a-f]{12}", mid):
        return {"ok": False, "error": "no computer id"}
    base = _offsite_root() / mid / "backups"
    floor = max(OFFSITE_FLOOR, int(req.get("floor") or 0))
    removed = []
    for rel in sorted(set(req.get("files") or [])):
        proj, _, fname = str(rel).partition("/")
        if not (_SAFE_NAME.fullmatch(proj) and _SAFE_NAME.fullmatch(fname)
                and fname.endswith(".zip")):
            continue
        zips = sorted(f.name for f in (base / proj).glob("*.zip"))
        if fname not in zips or len(zips) - zips.index(fname) - 1 < floor:
            continue
        for f in (base / proj / fname, base / proj / (fname[:-4] + ".meta.json")):
            try:
                f.unlink()
            except OSError:
                pass
        removed.append(rel)
    return {"ok": True, "removed": removed}

def _pruned_here(rel: str, mine: dict) -> bool:
    """A backup this computer pruned itself: newer ones of its project are
    still here.  None at all is no prune (backups wiped, or a new computer),
    and then nothing is removed over there."""
    proj, _, fname = rel.partition("/")
    return any(k.startswith(proj + "/") and _is_snapshot(k) and k.split("/", 1)[1] > fname
               for k in mine)

def offsite_push() -> dict:
    """Copy this computer's history backups to the machine named in
    offsite_backup: a second copy that does not burn with this one."""
    rem = _offsite_connect()
    mid, me = machine_id(create=True), _here()
    here = backups_root()
    mine = _backup_files(here)
    got = rem.agent("offsite-list", files=[mid, me])
    files = got.get("files") or {}
    theirs = dict(files.get(mid) or {})
    old = (files.get(me) or {}) if any(f["legacy"] and f["folder"] == me
                                       for f in got["folders"]) else None
    # an older aht's folder of this name is taken over only when it holds
    # nothing but copies of what is here (backups and rewrites' copies):
    # another computer of this name may have made it.  One with nothing
    # left in it is taken over too, and so goes
    take_over = old is not None and all(mine.get(k) == v for k, v in old.items())
    adopted = rem.agent("offsite-adopt", id=mid, legacy=me if take_over else None,
                        machine={"name": me, "system": platform.system(),
                                 "updated": _now()})["adopted"]
    st = _offsite_state()
    sent_all = dict(st.get("sent") or {})
    sent = dict(sent_all.get(rem.name) or {})
    for k in adopted:
        theirs[k] = sent[k] = old[k]
    there = f"{rem.info['home']}/.aht/offsite/{mid}/backups"
    missing = sorted(k for k in mine if k not in theirs)
    res = {"machine": rem.name, "folder": mid, "files": 0, "bytes": 0, "pulled": False,
           "adopted": len(adopted), "removed": 0,
           "differs": sorted(k for k in mine if k in theirs and theirs[k] != mine[k]),
           "legacy": [f["folder"] for f in got["folders"] if f["legacy"]
                      and (f["files"] or f["bytes"]) and not (take_over and f["folder"] == me)]}
    if missing:
        r = rem.rsync(str(here) + "/", rem.spec(there + "/"), files_from=missing,
                      add_only=True)
        if not r["ok"]:
            raise HandoverError("copying the backups failed: " + r["error"])
        sent.update({k: mine[k] for k in missing})
        res["files"], res["bytes"] = len([k for k in missing if _is_snapshot(k)]), \
            sum(mine[k] for k in missing)
    # only backups go there; a rewrite's copy stays until the user deletes it here
    pruned = sorted(k for k in sent if _is_snapshot(k) and k not in mine
                    and _pruned_here(k, mine))
    if pruned:
        gone = rem.agent("offsite-prune", id=mid, files=pruned,
                         floor=OFFSITE_FLOOR)["removed"]
        for k in gone:
            sent.pop(k, None)
            sent.pop(k[:-4] + ".meta.json", None)
        res["removed"] = len(gone)
    sent_all[rem.name] = sent
    st.update(machine=rem.name, at=time.time(), files=res["files"], bytes=res["bytes"],
              pulled=False, sent=sent_all)
    _write_json(offsite_state_path(), st)
    try:
        (aht_home() / "run" / "offsite.json").unlink()      # where older versions kept it
    except OSError:
        pass
    log(f"OFFSITE copied to {rem.name}: {res['files']} backup(s), {_human(res['bytes'])}"
        + (f"; {res['removed']} removed there" if res["removed"] else ""))
    res["at"] = st["at"]
    return res

def _offsite_folders(rem: Remote) -> list:
    mid = machine_id()
    rows = rem.agent("offsite-list")["folders"]
    for f in rows:
        f["mine"] = bool(mid) and f["id"] == mid
    return rows

def _offsite_connect() -> Remote:
    rem = offsite_remote()
    if rem is None:
        raise HandoverError("no machine is set for backups — Settings, or:  "
                            "aht config --set offsite_backup=<machine>")
    rem.connect()
    return rem

def offsite_list() -> dict:
    """The backup folders on the offsite machine: one per computer."""
    rem = _offsite_connect()
    return {"remote": rem.name, "folders": _offsite_folders(rem)}

def offsite_fetch(source: str = None) -> dict:
    """Bring backups here from the offsite machine (on a new computer): from
    this computer's folder there, or the one named by `source`: an id, then a
    folder's name (an older aht's folder is named by its computer), then a
    computer's name.  Adds what is missing; never overwrites.  A backup of
    the same name but another size arrives as <stamp>-from-<name>.zip."""
    rem = _offsite_connect()
    rows = _offsite_folders(rem)
    if source:
        # in this order, so an older aht's folder can be picked by its folder
        # name even when a computer of that name also has a folder by id
        pick = [f for f in rows if f["id"] == source] or \
            [f for f in rows if f["folder"] == source] or \
            [f for f in rows if f["name"] == source]
        if not pick:
            raise HandoverError(f"{rem.name} keeps no backups of {source}; it keeps: "
                                + (", ".join(f"{f['name']} ({f['id'] or 'older aht'})"
                                             for f in rows) or "none"))
        if len(pick) > 1:
            raise HandoverError(f"several computers named {source} keep backups on "
                                f"{rem.name}; choose one by its id: "
                                + ", ".join(f["id"] or f["folder"] for f in pick))
    else:
        pick = [f for f in rows if f["mine"] and f["files"]] or \
            [f for f in rows if f["files"]]
        if not pick:
            raise HandoverError(f"{rem.name} keeps no backups yet")
        if len(pick) > 1:
            raise HandoverError(f"several computers keep backups on {rem.name}: "
                                + ", ".join(f"{f['name']} ({f['id'] or 'older aht'})"
                                            for f in pick)
                                + " — choose one with --from")
    src, info = pick[0], rem.info
    folder = src["folder"]
    theirs = (rem.agent("offsite-list", files=[folder]).get("files") or {}).get(folder) or {}
    here = backups_root()
    here.mkdir(parents=True, exist_ok=True)
    mine = _backup_files(here)
    new = sorted(k for k in theirs if k not in mine)
    other = sorted(k for k in theirs if k in mine and mine[k] != theirs[k])
    there = f"{info['home']}/.aht/offsite/{folder}/backups"
    res = {"machine": rem.name, "from": {"id": src["id"], "name": src["name"]},
           "files": 0, "bytes": 0, "pulled": True, "renamed": []}
    if new:
        r = rem.rsync(rem.spec(there + "/"), str(here) + "/", files_from=new, add_only=True)
        if not r["ok"]:
            raise HandoverError("fetching the backups failed: " + r["error"])
    if other:
        # the same name, another size: both are kept, theirs under its own name
        inc = aht_home() / "run" / f"offsite-in-{os.urandom(3).hex()}"
        inc.mkdir(parents=True)
        try:
            r = rem.rsync(rem.spec(there + "/"), str(inc) + "/", files_from=other)
            if not r["ok"]:
                raise HandoverError("fetching the backups failed: " + r["error"])
            tag = re.sub(r"[^A-Za-z0-9._-]+", "-", src["name"]).strip("-") or "elsewhere"
            for k in other:
                proj, fname = k.split("/", 1)
                stem, ext = (fname[:-10], ".meta.json") if fname.endswith(".meta.json") \
                    else os.path.splitext(fname)
                dest = _free_name(str(here / proj), f"{stem}-from-{tag}{ext}")
                if (inc / k).is_file():
                    os.replace(inc / k, here / proj / dest)
                    res["renamed"].append(f"{proj}/{dest}")
        finally:
            shutil.rmtree(inc, ignore_errors=True)
    res["files"] = len([k for k in new if _is_snapshot(k)]) + \
        len([k for k in res["renamed"] if _is_snapshot(k)])
    res["bytes"] = sum(theirs[k] for k in new) + sum(theirs[k] for k in other)
    st = _offsite_state()
    st.update(fetched_at=time.time(), fetched_from=res["from"])
    _write_json(offsite_state_path(), st)
    log(f"OFFSITE fetched from {rem.name} ({src['name']}): {res['files']} backup(s), "
        f"{_human(res['bytes'])}")
    res["at"] = time.time()
    return res

def _spawn_offsite() -> None:
    try:
        if os.environ.get("AHT_NO_MIRROR") or not cfg_get("offsite_backup") \
                or not can_send_projects():
            return
        _spawn_aht(["backup", "--offsite", "--quiet"])
    except Exception:
        pass

# ---- what a session changed ------------------------------------------------- #

def session_changes(project: str, sid: str = None) -> dict:
    """The files a Claude Code session edited: how each looked before the
    session touched it (from Claude's own /rewind checkpoints) and now."""
    import difflib
    real = os.path.realpath(project)
    store = _store_of(real)
    sid = sid or latest_session(store)
    if not sid:
        return {"project": real, "session": None, "files": []}
    first, was = {}, None
    for raw in open(Path(store) / f"{sid}.jsonl", "rb"):
        if was is None and b'"cwd"' in raw:
            m = _CWD_RE.search(raw.decode("utf-8", "replace"))
            was = _unescape_json_str(m.group(1)) if m else None
        if b'"file-history-snapshot"' not in raw:
            continue
        try:
            e = json.loads(raw)
        except Exception:
            continue
        for path, b in ((e.get("snapshot") or {}).get("trackedFileBackups") or {}).items():
            if not isinstance(b, dict):
                continue
            v = int(b.get("version") or 0)
            if path not in first or v < first[path][0]:
                first[path] = (v, b.get("backupFileName"), b.get("backupTime"))
    fh = claude_home() / "file-history" / sid
    was = was or real
    files = []
    for path, (v, backup, when) in sorted(first.items()):
        # paths are as the session saw them, relative to where it ran then;
        # a project that moved since has them under its new place
        abs_ = os.path.normpath(path if path.startswith("/") else os.path.join(was, path))
        if was != real and _inside(abs_, was):
            abs_ = os.path.normpath(os.path.join(real, os.path.relpath(abs_, was)))
        before = None
        if backup:
            try:
                before = (fh / backup).read_text(encoding="utf-8", errors="replace")
            except OSError:
                before = None
                if not (fh / backup).exists():
                    files.append({"path": abs_, "state": "no checkpoint kept", "diff": ""})
                    continue
        try:
            now = Path(abs_).read_text(encoding="utf-8", errors="replace")
        except OSError:
            now = None
        state = ("added" if before is None and now is not None else
                 "removed" if now is None else
                 "unchanged" if before == now else "changed")
        diff = "".join(difflib.unified_diff(
            (before or "").splitlines(True), (now or "").splitlines(True),
            "before the session", "now", n=2)) if state != "unchanged" else ""
        inside = _inside(abs_, real)
        rel = os.path.relpath(abs_, real) if inside else abs_.replace(str(Path.home()), "~")
        files.append({"path": abs_, "name": rel, "state": state, "backup": backup,
                      "inside": inside,
                      "added": sum(1 for l in diff.splitlines() if l.startswith("+")
                                   and not l.startswith("+++")),
                      "removed": sum(1 for l in diff.splitlines() if l.startswith("-")
                                     and not l.startswith("---")),
                      "diff": _redact_head(diff, 200000)[:200000]})
    title = session_digest(Path(store) / f"{sid}.jsonl", real, turns=0).get("title")
    order = {"changed": 0, "added": 1, "removed": 2, "no checkpoint kept": 3, "unchanged": 4}
    files.sort(key=lambda f: (not f["inside"], order.get(f["state"], 5), f["name"]))
    return {"project": real, "session": sid, "title": title, "worked_in": was,
            "sessions": _sessions_of(store)[:12], "files": files}

def _kept_path(keep, path):
    """Where a copy of `path` goes in the folder `keep`: its whole path below
    the root or drive (keep / C:\\x would be C:\\x itself)."""
    return keep / path.relative_to(path.anchor)

def revert_file(project: str, sid: str, path: str, apply: bool) -> dict:
    """Put one file back the way it was before the session changed it; what
    is there now is kept aside first."""
    ch = session_changes(project, sid)
    f = next((x for x in ch["files"] if x["path"] == os.path.normpath(path)), None)
    if f is None or f["state"] in ("unchanged", "no checkpoint kept"):
        raise HandoverError("that file has nothing to put back from this session")
    res = {"file": f["path"], "state": f["state"], "applied": False}
    if not apply:
        return res
    keep = aht_home() / "changes-backups" / _stamp()
    if os.path.exists(f["path"]):
        dst = _kept_path(keep, Path(f["path"]))
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f["path"], dst)
        res["kept"] = str(dst)
    if f["backup"]:
        src = claude_home() / "file-history" / ch["session"] / f["backup"]
        tmp = f["path"] + ".aht-new"
        shutil.copyfile(src, tmp)
        os.replace(tmp, f["path"])
    else:                                    # the session created it
        os.unlink(f["path"])
    res["applied"] = True
    log(f"REVERT {f['path']} to before session {ch['session']}")
    return res

def cmd_changes(args):
    real = os.path.realpath(args.path)
    try:
        if args.revert:
            res = revert_file(real, args.session, os.path.realpath(args.revert), args.apply)
            print(json.dumps(res, indent=2) if args.json else
                  (f"put back: {res['file']}  (what was there is kept in {res.get('kept')})"
                   if res["applied"] else f"would put back: {res['file']}"))
            return 0
    except HandoverError as e:
        print(str(e), file=sys.stderr)
        return 3
    except OSError as e:
        print(f"the file could not be put back: {e}", file=sys.stderr)
        return 1
    ch = session_changes(real, args.session)
    if args.json:
        print(json.dumps(ch, indent=2))
        return 0
    if not ch["session"]:
        print("no Claude Code session in this project")
        return 0
    mine = [f for f in ch["files"] if f["inside"]]
    print(f"{ch['title'] or ch['session']}: {len(mine)} file(s) of the project edited"
          + (f", {len(ch['files']) - len(mine)} outside it" if len(mine) < len(ch["files"]) else ""))
    for f in ch["files"]:
        if f["inside"] or args.all:
            print(f"   {f['state']:<18} {f['name']}  (+{f.get('added', 0)} −{f.get('removed', 0)})")
    if args.diff:
        for f in ch["files"]:
            if f["diff"]:
                print("\n" + f["diff"])
    return 0

# ---- usage report and an AI-use statement --------------------------------- #

GAP_CAP = 15 * 60          # a pause longer than this does not count as time worked

def _period(since, until):
    def parse(s, end=False):
        if not s:
            return None
        if s in ("today", "week", "month"):
            lt = time.localtime()
            base = time.mktime((lt.tm_year, lt.tm_mon, 1 if s == "month" else lt.tm_mday,
                                0, 0, 0, 0, 0, -1))
            if s == "week":
                base -= lt.tm_wday * 86400
            return base
        t = time.mktime(time.strptime(s[:10], "%Y-%m-%d"))
        return t + 86400 if end else t
    return parse(since), parse(until, end=True)

def _area_of(path: str) -> str:
    areas = cfg_get("report_areas") or {}
    for name, prefix in sorted(areas.items(), key=lambda kv: -len(str(kv[1]))):
        if _inside(os.path.realpath(path or "/"), os.path.realpath(_expand(str(prefix)))):
            return name
    return "other"

def usage_report(since=None, until=None, project=None, by="project") -> dict:
    """Sessions, active time and what they were about, per project (or per
    agent, or per area of work), over a period."""
    t0, t1 = _period(since, until)
    rows = {}
    mine = os.path.realpath(str(aht_home()))
    for s in list_sessions(project):
        st = _stat(s["file"])
        if st is None or (t0 and st.st_mtime < t0):
            continue
        if s.get("project") and _inside(os.path.realpath(s["project"]), mine):
            continue                        # a second opinion's copy
        times, prompts, title = [], 0, s.get("title")
        for _end, ev in session_events(s["agent"], s["file"]):
            if ev["role"] == "title":
                title = ev["text"]
                continue
            t = ev.get("t")
            if not t or (t0 and t < t0) or (t1 and t >= t1):
                continue
            times.append(t)
            if ev["role"] == "user":
                prompts += 1
        if not times:
            continue
        # a session can carry copies of older messages: count the time in order
        times.sort()
        first, last = times[0], times[-1]
        active = sum(min(b - a, GAP_CAP) for a, b in zip(times, times[1:]))
        proj = s.get("project") or "?"
        key = {"agent": AGENT_NAMES.get(s["agent"], s["agent"]),
               "area": _area_of(proj)}.get(by, proj)
        r = rows.setdefault(key, {"key": key, "sessions": 0, "seconds": 0.0, "prompts": 0,
                                  "agents": {}, "projects": set(), "titles": [],
                                  "first": first, "last": last})
        r["sessions"] += 1
        r["seconds"] += active
        r["prompts"] += prompts
        r["agents"][s["agent"]] = r["agents"].get(s["agent"], 0) + 1
        r["projects"].add(proj)
        r["first"], r["last"] = min(r["first"], first), max(r["last"], last or first)
        if title and title not in r["titles"]:
            r["titles"].append(redact(title))
    out = []
    for r in sorted(rows.values(), key=lambda r: -r["seconds"]):
        r["hours"] = round(r["seconds"] / 3600, 1)
        r["projects"] = sorted(r["projects"])
        out.append(r)
    return {"since": since, "until": until, "by": by, "rows": out,
            "total_hours": round(sum(r["seconds"] for r in out) / 3600, 1),
            "total_sessions": sum(r["sessions"] for r in out)}

def ai_use_statement(project: str, since=None, until=None) -> str:
    """A draft disclosure for a paper, a thesis or a course: which AI coding
    agents were used, when, how much, and for what."""
    rep = usage_report(since, until, project, by="agent")
    if not rep["rows"]:
        return "No AI coding agent sessions were found for this project in that period."
    def day(t):
        return time.strftime("%B %Y", time.localtime(t))
    first = min(r["first"] for r in rep["rows"])
    last = max(r["last"] for r in rep["rows"])
    parts = [f"{r['key']} ({r['sessions']} session{'s' if r['sessions'] != 1 else ''}, "
             f"about {max(r['hours'], 0.1):.1f} h of active use)" for r in rep["rows"]]
    tasks = [t for r in rep["rows"] for t in r["titles"]][:8]
    span = (f"in {day(first)}" if day(first) == day(last)
            else f"between {day(first)} and {day(last)}")
    text = f"AI coding assistants were used in this work {span}: " + "; ".join(parts) + "."
    if tasks:
        text += (" They were used for tasks such as: "
                 + "; ".join(_clip(t, 80).rstrip(".") for t in tasks) + ".")
    text += (" All output of these tools was reviewed, and the author takes full "
             "responsibility for the content.")
    return text

def cmd_report(args):
    rep = usage_report(args.since, args.until, args.project, args.by)
    if args.statement:
        if not args.project:
            print("--statement needs --project", file=sys.stderr)
            return 2
        text = ai_use_statement(args.project, args.since, args.until)
        print(json.dumps({"statement": text}, indent=2) if args.json else text)
        return 0
    if args.json:
        print(json.dumps(rep, indent=2, default=list))
        return 0
    print(f"{rep['total_sessions']} session(s), about {rep['total_hours']} h of active use"
          + (f" since {args.since}" if args.since else "") + f" — by {args.by}")
    for r in rep["rows"]:
        label = os.path.basename(r["key"]) if args.by == "project" else r["key"]
        agents = ", ".join(f"{AGENT_NAMES.get(a, a)} {n}" for a, n in r["agents"].items())
        print(f"   {r['hours']:>6.1f} h  {r['sessions']:>3} session(s)  {label:<32} {agents}")
    return 0

# ---- share a session -------------------------------------------------------- #

def _scrub(text: str) -> str:
    """No keys aht recognises, no e-mail or local network addresses, and no
    home folder or names that say whose Mac this is."""
    text = redact(text)
    home = str(Path.home())
    text = text.replace(home, "~")
    text = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[e-mail]", text)
    text = re.sub(r"\b(?:10|192\.168|169\.254|172\.(?:1[6-9]|2\d|3[01])|"
                  r"100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7]))"
                  r"(?:\.\d{1,3}){2,3}\b", "[address]", text)
    # IPv6: unique local (fd00::/8, Tailscale's among them) and link-local
    # (fe80::/10, with its zone: %en0); a colon after one is the sentence's
    text = re.sub(r"\b(?:fd[0-9a-f]{2}|fe[89ab][0-9a-f])(?::[0-9a-f]{0,4}){2,7}(?<![^:]:)"
                  r"(?:%\w+(?:[.-]\w+)*)?(?!\w)", "[address]", text, flags=re.I)
    user = os.path.basename(home)
    host = _here()
    for word in {user, host} - {"", "home", "user", "root"}:
        text = re.sub(rf"\b{re.escape(word)}\b", "…", text)
    return text

# what a shared page says of itself, under its title
SHARE_NOTE = ("Keys and passwords aht recognises are masked; e-mail addresses, local network "
              "addresses and your home folder's path are removed. Look it through before you "
              "share it.")

def export_session(project: str, sid: str = None, agent: str = None,
                   fmt: str = "md", tools: bool = False) -> dict:
    real = os.path.realpath(project)
    sess = [s for s in list_sessions(real) if (not agent or s["agent"] == agent)]
    s = next((x for x in sess if x["id"] == sid), None) if sid else (
        next((x for x in sess if not (x["agent"] == "claude" and _is_scripted(x["file"]))),
             sess[0] if sess else None))
    if s is None:
        raise HandoverError("no such session in this project")
    title, turns = s.get("title"), []
    for _end, ev in session_events(s["agent"], s["file"]):
        if ev["role"] == "title":
            title = ev["text"]
        elif ev["role"] in ("user", "agent", "summary"):
            turns.append((ev["role"], ev.get("t"), _scrub(ev["text"])))
        elif ev["role"] == "tool" and tools:
            turns.append(("tool", ev.get("t"), _scrub(f"{ev.get('tool')}: {ev.get('target')}")))
    title = _scrub(title) if title else title
    who = {"user": "You", "agent": AGENT_NAMES.get(s["agent"], "Agent"),
           "summary": "Summary of the earlier conversation", "tool": "Tool"}
    name = os.path.basename(real)
    when = _when_text(turns[0][1]) if turns and turns[0][1] else ""
    if fmt == "html":
        import html as H
        body = []
        for role, t, text in turns:
            body.append(f'<div class="m {role}"><div class="who">{H.escape(who[role])}'
                        f'<span>{H.escape(_when_text(t) if t else "")}</span></div>'
                        f'<div class="t">{H.escape(text)}</div></div>')
        doc = ("<!doctype html><meta charset=utf-8><meta name=viewport "
               "content='width=device-width'>"
               f"<title>{H.escape(title or name)}</title><style>"
               "body{font:15px/1.5 -apple-system,Segoe UI,sans-serif;max-width:760px;margin:2em auto;"
               "padding:0 1em;color:#222}h1{font-size:1.4em}.sub{color:#777}.m{margin:1.2em 0}"
               ".who{font-weight:600}.who span{font-weight:400;color:#999;margin-left:.6em;"
               "font-size:.85em}.t{white-space:pre-wrap}.user .t{background:#f3f5f8;padding:.6em "
               ".8em;border-radius:8px}.tool .t{font:12px ui-monospace,monospace;color:#666}"
               "@media(prefers-color-scheme:dark){body{background:#1b1b1d;color:#ddd}"
               ".user .t{background:#2a2c30}}</style>"
               f"<h1>{H.escape(title or name)}</h1><p class=sub>{H.escape(name)} · "
               f"{H.escape(AGENT_NAMES.get(s['agent'], s['agent']))} · {H.escape(when)}. "
               f"{H.escape(SHARE_NOTE)}</p>" + "".join(body))
    else:
        L = [f"# {title or name}", "",
             f"{name} · {AGENT_NAMES.get(s['agent'], s['agent'])} · {when}. {SHARE_NOTE}", ""]
        for role, t, text in turns:
            L += [f"**{who[role]}**" + (f" · {_when_text(t)}" if t else ""), "", text, ""]
        doc = "\n".join(L)
    return {"session": s["id"], "agent": s["agent"], "title": title, "format": fmt,
            "turns": len(turns), "text": doc}

def cmd_share(args):
    try:
        ex = export_session(args.path, args.session, args.agent, args.format, args.tools)
    except HandoverError as e:
        print(str(e), file=sys.stderr)
        return 2
    if args.out:
        Path(args.out).write_text(ex["text"], encoding="utf-8")
        ex["file"] = os.path.realpath(args.out)
        del ex["text"]
    if args.json:
        print(json.dumps(ex, indent=2))
    elif args.out:
        print(f"written: {ex['file']}  ({ex['turns']} message(s))")
    else:
        print(ex["text"])
    return 0

# ---- take a leaked key out of the histories (only when asked) --------------- #

def redact_in_histories(fingerprint: str, project: str = None, apply: bool = False) -> dict:
    """Replace one found secret in every history file that holds it with a
    marker.  The files are copied aside first, and nothing happens while an
    agent session is open in an affected project: it writes to those files."""
    pats = _secret_patterns()
    hits = []
    for s in list_sessions(project):
        try:
            data = Path(s["file"]).read_bytes()
        except OSError:
            continue
        spans = [(a0, b0) for _k, a0, b0, v in _scan_bytes(data, pats)
                 if _fingerprint(v) == fingerprint]
        if spans:
            hits.append((s, spans))
    res = {"fingerprint": fingerprint, "files": len(hits),
           "places": sum(len(sp) for _s, sp in hits), "applied": False, "blockers": []}
    for s, _sp in hits:
        for o in running_sessions(inside=s.get("project") or "/nonexistent"):
            res["blockers"].append(f"an agent session is open in {s.get('project')} "
                                   f"(pid {o['pid']}) — exit it first")
    res["blockers"] = sorted(set(res["blockers"]))
    if not apply or res["blockers"] or not hits:
        return res
    keep = aht_home() / "redacted" / _stamp()
    res["left"] = 0
    for s, spans in hits:
        src = Path(s["file"])
        data = src.read_bytes()
        new, left = _take_out(data, spans, b"[removed by aht]")
        res["left"] += left
        if new == data:
            continue
        dst = keep / src.relative_to(src.anchor)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        tmp = src.with_name(src.name + ".aht-new")
        tmp.write_bytes(new)
        shutil.copystat(src, tmp)
        os.replace(tmp, src)
    res.update(applied=True, kept=str(keep))
    log(f"REDACT {fingerprint}: {res['places'] - res['left']} place(s) in {res['files']} "
        f"file(s), {res['left']} left as they were; originals in {keep}")
    return res

def _json_ok(b: bytes) -> bool:
    try:
        json.loads(b)
        return True
    except ValueError:
        return False

def _take_out(data: bytes, spans: list, marker: bytes) -> tuple:
    """`data` with every span replaced by `marker` -> (that, how many places
    were left as they are).  Where a history's lines read as JSON, or the
    whole file does, and would no longer, nothing there changes: taking a
    secret out must never break the history."""
    def eol(i):
        e = data.find(b"\n", i)
        return len(data) if e < 0 else e
    groups = []                     # [first line's start, last line's end, spans]
    for a0, b0 in sorted(spans):
        if groups and a0 < groups[-1][1]:
            if a0 >= groups[-1][2][-1][1]:          # not one that overlaps
                groups[-1][2].append((a0, b0))
                groups[-1][1] = max(groups[-1][1], eol(b0))
        else:
            groups.append([data.rfind(b"\n", 0, a0) + 1, eol(b0), [(a0, b0)]])
    out, pos, left = [], 0, 0
    for ls, le, sp in groups:
        new, p = [], ls
        for a0, b0 in sp:
            new += [data[p:a0], marker]
            p = b0
        new = b"".join(new) + data[p:le]
        lines = [l for l in data[ls:le].split(b"\n") if l.strip()]
        if lines and all(map(_json_ok, lines)) and not all(
                _json_ok(l) for l in new.split(b"\n") if l.strip()):
            left += len(sp)
            continue
        out += [data[pos:ls], new]
        pos = le
    out.append(data[pos:])
    new = b"".join(out)
    if new != data and _json_ok(data) and not _json_ok(new):
        return data, len(spans)
    return new, left

# --------------------------------------------------------------------------- #
# Before and after a session: where the last session stopped, Claude's usage
# limit, a copy of the folder to undo a session with, loose ends, a second
# opinion and the night shift.  Whatever spends an agent's tokens is off
# until the user turns it on: informed_sessions, limit_switch,
# second_opinion, night_shift.
# --------------------------------------------------------------------------- #

def _aht_argv() -> list:
    """How to run aht itself: aht.exe when frozen (also from the tray's own
    exe), else this file; on Windows from a checkout, through the Windows
    entry point, which the core needs there (it brings fcntl)."""
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable)
        cli = exe.with_name("aht.exe")
        return [str(cli) if exe.stem.lower() != "aht" and cli.is_file() else sys.executable]
    me = Path(__file__).resolve()
    if os.name == "nt" and (me.parent / "windows" / "src" / "aht_main.py").is_file():
        return [sys.executable, str(me.parent / "windows" / "src" / "aht_main.py")]
    return [sys.executable or "python3", str(me)]

def _spawn_aht(args: list):
    """Run `aht <args>` detached; its pid, or None."""
    try:
        cmd = _aht_argv() + args
        kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
              "stderr": subprocess.DEVNULL, "close_fds": True, "cwd": "/"}
        if os.name == "nt":
            kw["creationflags"] = 0x08000200
        else:
            kw["start_new_session"] = True
        return subprocess.Popen(cmd, **kw).pid
    except Exception:
        return None

def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".new")
    tmp.write_text(json.dumps(obj, indent=1, default=str))
    os.replace(tmp, path)

def _session_title(s: dict):
    if s.get("title") or s["agent"] != "claude":
        return s.get("title")
    title = None
    try:
        with open(s["file"], "rb") as fh:
            for line in fh:
                if b'-title"' in line:
                    try:
                        e = json.loads(line)
                    except Exception:
                        continue
                    title = e.get("aiTitle") or e.get("customTitle") or title
    except OSError:
        pass
    return redact(str(title)) if title else None

# ---- every session starts informed (USES TOKENS: off unless turned on) ------ #

def informed_note(cwd: str, current: str = None, limit: int = 1600,
                  resumed: bool = False) -> str:
    """Where the latest earlier session in this folder stopped, whichever
    agent ran it: a few lines for a new Claude Code session's context.  Kept
    short, because the model reads every line of it.  A session that another
    agent took the work over from, resumed by hand, learns instead what
    happened since (the catch-up); another resumed session learns nothing."""
    real = os.path.realpath(cwd)
    if real == os.path.realpath(str(Path.home())):
        return ""
    r = next((r for r in open_relays(real) if current and r["from"].get("session") == current
              and _relay_here(r["from"])), None) if current and relay_dir(real).is_dir() else None
    if r is not None:
        cd = catchup_digest(real, float(r["at"]), exclude={("claude", current)}, most=3)
        g = git_state(real, since_head=(r["from"].get("git") or {}).get("head"),
                      since=float(r["at"]))
        return _clip(redact("[aht] " + "\n".join(catchup_head(cd, g, "this session",
                                                              [r["to"]["agent"]]))),
                     HOOK_NOTE_MAX)
    if resumed:
        return ""
    for s in list_sessions(real)[:6]:
        if s["id"] == current or (s["agent"] == "claude" and _is_scripted(s["file"])):
            continue
        dig = events_digest(s, real, turns=1, tail=2 << 20)
        if not dig.get("exchanges"):
            continue
        x = dig["exchanges"][-1]
        title = dig.get("title") or _session_title(s)
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(s["updated"]))
        L = [f"[aht] The latest earlier session in this folder: {AGENT_NAMES[s['agent']]}, "
             f"{when}" + (f", “{_masked(title, 80)}”" if title else "") + "."]
        L.append("- Last request: " + _masked(" ".join(x["you"].split()), 300))
        if x.get("agent"):
            L.append("- Where it stopped: " + _masked(" ".join(x["agent"].split()), 500))
        todos = [str(t.get("content") or t.get("subject") or t.get("title") or "")
                 for t in dig.get("todos") or []]
        if todos:
            L.append("- Open to-dos: " + "; ".join(_masked(t, 100) for t in todos[:5]))
        if dig.get("touched"):
            L.append("- Files it changed last: "
                     + ", ".join(list(reversed(dig["touched"]))[:6]))
        L.append(f"- Session: {s['id']}")
        L.append("Use this only when it matters for what the user asks; do not bring "
                 "it up otherwise.")
        return _clip(redact("\n".join(L)), limit)
    return ""

# ---- Claude's usage limit, and going on in another agent ------------------- #

_LIMIT_WORDS = re.compile(r"hit your .{0,24}limit|usage limit|limit reached", re.I)

def _tail_records(path, size: int = 65536) -> list:
    try:
        with open(path, "rb") as fh:
            end = fh.seek(0, 2)
            fh.seek(max(0, end - size))
            data = fh.read()
    except OSError:
        return []
    lines = data.split(b"\n")
    if end > size:
        lines = lines[1:]
    out = []
    for raw in lines:
        try:
            e = json.loads(raw)
        except Exception:
            continue
        if isinstance(e, dict):
            out.append(e)
    return out

def _reset_time(text: str, at: float):
    """When "resets 6:20am (Europe/Lisbon)" or "resets Oct 3, 6am" is, after
    `at`, in this machine's time; None when the text says it otherwise."""
    m = re.search(r"resets\s+(?:at\s+)?(?:([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+"
                  r"(?:at\s+)?)?(\d{1,2})(?::(\d{2}))?\s*([ap]m)\b", text or "", re.I)
    if not m or not at:
        return None
    h = int(m.group(3)) % 12 + (12 if m.group(5).lower() == "pm" else 0)
    mi = int(m.group(4) or 0)
    lt = time.localtime(at)
    if m.group(1):
        try:
            mon = time.strptime(m.group(1).title(), "%b").tm_mon
        except ValueError:
            return None
        t = time.mktime((lt.tm_year, mon, int(m.group(2)), h, mi, 0, 0, 0, -1))
        if t < at - 86400:
            t = time.mktime((lt.tm_year + 1, mon, int(m.group(2)), h, mi, 0, 0, 0, -1))
        return t
    t = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, h, mi, 0, 0, 0, -1))
    if t <= at:
        t = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday + 1, h, mi, 0, 0, 0, -1))
    return t

def limit_stop(jsonl):
    """{at, text, resets, until} when a Claude Code session's last word is
    the usage limit; None otherwise."""
    for e in reversed(_tail_records(jsonl)):
        t = e.get("type")
        if t not in ("user", "assistant") or e.get("isSidechain"):
            continue
        m = e.get("message") if isinstance(e.get("message"), dict) else {}
        txt = _text_of(m.get("content")).strip()
        if t == "user":
            if e.get("isMeta") or not txt or txt.startswith("<"):
                continue                    # reminders, a /command's echo
            return None                     # the user went on after it
        if (e.get("isApiErrorMessage") or e.get("error")) and _LIMIT_WORDS.search(txt):
            at = _when(e.get("timestamp"))
            txt = redact(txt)                   # shown and sent: masked before any cut
            r = re.search(r"resets\s+([^\n·]+)", txt)
            return {"at": at, "text": _clip(txt, 200),
                    "resets": r.group(1).strip() if r else None,
                    "until": _reset_time(txt, at)}
        return None
    return None

def limit_stops(hours: float = 12) -> list:
    """Claude Code sessions that stopped at the usage limit in the last
    `hours`, newest first.  Read from the end of recent transcripts: no
    tokens."""
    root = claude_backend().root()
    since, now = time.time() - hours * 3600, time.time()
    mine = os.path.realpath(str(aht_home()))
    owner = _store_owners()
    out = []
    for d in (root.iterdir() if root.is_dir() else []):
        if not d.is_dir() or d.name.startswith(STAGING_PREFIX):
            continue
        for f in d.glob("*.jsonl"):
            st = _stat(f)
            if not st or st.st_mtime < since:
                continue
            hit = limit_stop(f)
            if not hit:
                continue
            proj = owner.get(d.name) or transcript_cwd(d)
            if proj and _inside(os.path.realpath(proj), mine):
                continue                    # a second opinion's copy
            hit.update(session=f.stem, project=proj,
                       over=bool(hit["until"] and now >= hit["until"]))
            out.append(hit)
    out.sort(key=lambda h: h.get("at") or 0, reverse=True)
    return out

def limit_switch_target():
    """The agent to offer when Claude is out of tokens: only when the user
    turned that on (it spends the other agent's tokens) and it is installed."""
    if not cfg_get("limit_switch", False):
        return None
    t = str(cfg_get("limit_switch_to", "kimi"))
    return t if t in SWITCH_TARGETS and t != "claude" and agent_cli(t) else None

def set_claude_auto_continue(on: bool) -> None:
    """Claude Code's autoContinueAtUsageLimit in ~/.claude/settings.json (a
    copy of the file is kept first)."""
    f = claude_home() / "settings.json"
    data = json.loads(f.read_text()) if f.is_file() else {}
    if f.is_file():
        shutil.copy2(f, str(f) + ".bak-aht")
    data["autoContinueAtUsageLimit"] = bool(on)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f.name + ".aht-new")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, f)
    log(f"CLAUDE autoContinueAtUsageLimit = {bool(on)}")

def cmd_limits(args):
    if args.auto_continue:
        set_claude_auto_continue(args.auto_continue == "on")
        print("Claude Code now " + ("continues a session by itself when the limit resets"
                                    if args.auto_continue == "on" else
                                    "waits for you after the limit resets"))
        return 0
    hits = limit_stops(args.hours)
    tgt = limit_switch_target()
    auto = claude_auto_continue()
    if args.json:
        print(json.dumps({"limits": hits, "switch_to": tgt, "auto_continue": auto,
                          "switch_enabled": bool(cfg_get("limit_switch", False))},
                         indent=2))
        return 0
    if not hits:
        print(f"no session stopped at Claude's usage limit in the last {args.hours:g} hours")
        return 0
    for h in hits:
        when = time.strftime("%H:%M", time.localtime(h["at"])) if h.get("at") else "?"
        print(f"{h.get('project') or '?'}\n   stopped at {when}: {h['text']}"
              + ("   (over now)" if h["over"] else
                 "   (continues by itself then)" if auto else ""))
        if tgt and h.get("project"):
            print(f"   go on in {AGENT_NAMES[tgt]}:  aht switch {shlex.quote(h['project'])} "
                  f"--to {tgt} --session {h['session']} --apply")
    if not tgt:
        print("\n(to be offered another agent here: aht config --set limit_switch=true "
              "— that agent's tokens are used)")
    return 0

# ---- checkpoints: a copy of the folder when a session starts --------------- #

CHECKPOINT_SKIP = HANDOVER_SKIP + (".git", ".aht")
OPINION_SKIP = HANDOVER_SKIP + (".aht",)
CLONES_PER_SECOND = 6000        # measured: 98,212 files cloned in 16.6 s (APFS, M-series)

def checkpoint_skip() -> list:
    extra = cfg_get("checkpoint_excludes") or []
    return list(CHECKPOINT_SKIP) + [str(x) for x in extra if x]

def checkpoints_root() -> Path:
    return aht_home() / "checkpoints"

_OUT_OF_TM = set()

def keep_out_of_time_machine(path: Path) -> None:
    """Time Machine does not keep copy-on-write copies shared: it would store
    every checkpoint and second-opinion copy in full.  A sticky exclusion
    (no admin rights needed) keeps them out of the backups."""
    if not IS_MAC or str(path) in _OUT_OF_TM:
        return
    _OUT_OF_TM.add(str(path))
    try:
        path.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(["/usr/bin/tmutil", "isexcluded", str(path)],
                           capture_output=True, text=True, timeout=20, cwd="/")
        if "[Excluded]" not in r.stdout:
            subprocess.run(["/usr/bin/tmutil", "addexclusion", str(path)],
                           capture_output=True, timeout=20, cwd="/")
            log(f"TIME MACHINE: {path} left out of the backups")
    except Exception as e:
        warn(f"TIME MACHINE exclusion for {path}: {e}")

def checkpoint_coverage(max_files: int = None) -> dict:
    """How many files each tracked project would copy at a session start,
    and which ones are over the limit (they get no copy).  For those, the
    biggest top-level folders — candidates for checkpoint_excludes."""
    limit = int(max_files or cfg_get("checkpoint_max_files", 20000))
    skip = checkpoint_skip()
    rows = []
    for e in load_registry().get("projects", {}).values():
        real = e["real_path"]
        if not os.path.isdir(real) or e.get("away"):
            continue
        files = _list_tree(real, skip) or {}
        row = {"project": real, "files": len(files), "over": len(files) > limit,
               "seconds": round(len(files) / CLONES_PER_SECOND, 1)}
        if row["over"]:
            top = {}
            for rel in files:
                head = rel.split(os.sep, 1)[0] if os.sep in rel else "(files at the top)"
                top[head] = top.get(head, 0) + 1
            row["biggest"] = [{"name": k, "files": v} for k, v in
                              sorted(top.items(), key=lambda kv: -kv[1])[:4]]
        rows.append(row)
    rows.sort(key=lambda r: -r["files"])
    return {"max": limit, "projects": rows, "over": [r for r in rows if r["over"]]}

def _project_key(real: str) -> str:
    return read_marker(real) or ("p-" + hashlib.sha256(real.encode()).hexdigest()[:16])

_CLONEFILE = []

def _clone(src: str, dst: str) -> bool:
    """A copy-on-write copy (APFS clonefile): instant, and it takes no room
    until one of the two changes.  False where the disk cannot do that."""
    if not _CLONEFILE:
        f = None
        if IS_MAC:
            try:
                import ctypes
                f = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True).clonefile
                f.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32]
                f.restype = ctypes.c_int
            except Exception:
                f = None
        _CLONEFILE.append(f)
    f = _CLONEFILE[0]
    return bool(f) and f(os.fsencode(src), os.fsencode(dst), 1) == 0   # CLONE_NOFOLLOW

def _list_tree(root: str, skip, cap: int = None):
    """{rel: size} of the files and links under `root`; None past `cap` files."""
    out = {}
    for dp, dns, fns in os.walk(root):
        keep = []
        for d in dns:
            if _skip_name(d, skip):
                continue
            if os.path.islink(os.path.join(dp, d)):
                fns.append(d)
            else:
                keep.append(d)
        dns[:] = keep
        for n in fns:
            if _skip_name(n, skip):
                continue
            p = os.path.join(dp, n)
            try:
                st = os.lstat(p)
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode) or stat.S_ISLNK(st.st_mode):
                out[os.path.relpath(p, root)] = st.st_size if stat.S_ISREG(st.st_mode) else 0
                if cap and len(out) > cap:
                    return None
    return out

def _put(src: str, dst: str) -> None:
    """One file or link from src to dst: copy-on-write where possible."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if _clone(src, dst):
        return
    if os.path.islink(src):
        os.symlink(os.readlink(src), dst)
    else:
        shutil.copy2(src, dst)

def copy_tree(src: str, dst: str, skip, cap: int = None,
              copy_limit: int = 100 << 20) -> dict:
    """Copy a folder, copy-on-write where the disk can.  A real copy is made
    only while the folder stays under `copy_limit` bytes."""
    files = _list_tree(src, skip, cap)
    if files is None:
        return {"ok": False, "why": f"the folder holds more than {cap} files"}
    total, method = sum(files.values()), None
    os.makedirs(dst, exist_ok=True)
    for rel in files:
        s, d = os.path.join(src, rel), os.path.join(dst, rel)
        try:
            os.makedirs(os.path.dirname(d), exist_ok=True)
        except OSError:
            continue
        if method != "copy" and _clone(s, d):
            method = "clone"
            continue
        if method is None:
            if total > copy_limit:
                shutil.rmtree(dst, ignore_errors=True)
                return {"ok": False, "why": "this disk cannot make copy-on-write copies, "
                        f"and the folder is too big to copy ({total >> 20} MB)"}
            method = "copy"
        try:
            if os.path.islink(s):
                os.symlink(os.readlink(s), d)
            else:
                shutil.copy2(s, d)
        except OSError:
            pass                            # gone meanwhile
    return {"ok": True, "method": method or "clone", "files": len(files), "bytes": total}

def take_checkpoint(project: str, session: str = None, agent: str = "claude") -> dict:
    real = os.path.realpath(project)
    if not os.path.isdir(real) or real == os.path.realpath(str(Path.home())):
        return {"ok": False, "why": "not a project folder"}
    key = _project_key(real)
    keep_out_of_time_machine(checkpoints_root())
    d = checkpoints_root() / key / f"{_stamp()}-{(session or agent)[:8]}"
    if d.exists():
        return {"ok": False, "why": "one was just taken"}
    skip = checkpoint_skip()
    res = copy_tree(real, str(d / "files"), skip,
                    cap=int(cfg_get("checkpoint_max_files", 20000)))
    if not res["ok"]:
        shutil.rmtree(d, ignore_errors=True)
        log(f"CHECKPOINT {real}: none — {res['why']}")
        return res
    meta = dict(res, project=real, session=session or None, agent=agent, at=time.time(),
                skip=skip)            # an undo compares with the same names left out
    _write_json(d / "meta.json", meta)        # written last: marks it complete
    prune_checkpoints(key)
    log(f"CHECKPOINT {real}: {res['files']} file(s), {res['method']}")
    return dict(meta, id=d.name)

def prune_checkpoints(key: str) -> None:
    base = checkpoints_root() / key
    if not base.is_dir():
        return
    keep = max(1, int(cfg_get("checkpoint_keep", 10)))
    now = time.time()
    done = sorted(p for p in base.iterdir() if (p / "meta.json").is_file())
    old = done[:-keep] + [p for p in done[-keep:]
                          if now - p.stat().st_mtime > 30 * 86400]
    old += [p for p in base.iterdir() if p.is_dir() and not (p / "meta.json").exists()
            and now - p.stat().st_mtime > 3600]         # an interrupted copy
    for p in old:
        shutil.rmtree(p, ignore_errors=True)

def checkpoints_on() -> bool:
    """On by default only on macOS, where the copies are copy-on-write and
    cost no room; elsewhere they are real copies, so the user turns them on."""
    if os.environ.get("AHT_NO_CHECKPOINT"):
        return False
    if not IS_MAC and "checkpoints" not in load_config():
        return False
    return bool(cfg_get("checkpoints", True))

def _spawn_checkpoint(cwd: str, sid, agent: str) -> None:
    if not checkpoints_on():
        return
    _spawn_aht(["checkpoint", cwd, "--agent", agent, "--quiet"]
               + (["--session", sid] if sid else []))

def list_checkpoints(project: str) -> list:
    real = os.path.realpath(project)
    base = checkpoints_root() / _project_key(real)
    out = []
    for d in sorted(base.iterdir() if base.is_dir() else [], reverse=True):
        try:
            meta = json.loads((d / "meta.json").read_text())
        except Exception:
            continue
        out.append(dict(meta, id=d.name, path=str(d / "files")))
    if out:
        sess = {s["id"]: s for s in list_sessions(real)}
        for c in out:
            s = sess.get(c.get("session") or "")
            c["title"] = _session_title(s) if s else None
    return out

def _is_binary(path: str) -> bool:
    try:
        with open(path, "rb") as fh:
            return b"\0" in fh.read(8192)
    except OSError:
        return False

def _file_row(name: str, before, now, state: str) -> dict:
    """One changed file as the window shows it: a line diff for text."""
    import difflib
    row = {"name": name, "state": state, "added": 0, "removed": 0, "diff": ""}
    if any(p and (os.path.islink(p) or _is_binary(p)) for p in (before, now)):
        row["binary"] = True
        return row
    def text(p):
        try:
            return Path(p).read_text(encoding="utf-8", errors="replace") if p else ""
        except OSError:
            return ""
    diff = "".join(difflib.unified_diff(text(before).splitlines(True),
                                        text(now).splitlines(True), "before", "now", n=2))
    row["added"] = sum(1 for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++"))
    row["removed"] = sum(1 for l in diff.splitlines() if l.startswith("-") and not l.startswith("---"))
    row["diff"] = _redact_head(diff, 200000)[:200000]
    return row

def _same_file(a: str, b: str) -> bool:
    try:
        sa, sb_ = os.lstat(a), os.lstat(b)
    except OSError:
        return False
    la, lb = stat.S_ISLNK(sa.st_mode), stat.S_ISLNK(sb_.st_mode)
    if la or lb:
        return la and lb and os.readlink(a) == os.readlink(b)
    if sa.st_size != sb_.st_size:
        return False
    if sa.st_mtime_ns == sb_.st_mtime_ns:     # a copy keeps the time to the nanosecond
        return True
    return file_sha256(a) == file_sha256(b)

def tree_changes(now_root: str, then_root: str, skip) -> dict:
    """{changed, added, removed}: `now_root` against `then_root`."""
    now, then = _list_tree(now_root, skip) or {}, _list_tree(then_root, skip) or {}
    return {"changed": sorted(r for r in set(now) & set(then)
                              if not _same_file(os.path.join(now_root, r),
                                                os.path.join(then_root, r))),
            "added": sorted(set(now) - set(then)),
            "removed": sorted(set(then) - set(now))}

def _rows(ch: dict, now_root: str, then_root: str, diffs: bool) -> list:
    rows = []
    for state in ("changed", "added", "removed"):
        for rel in ch[state]:
            if diffs:
                rows.append(_file_row(rel, None if state == "added" else os.path.join(then_root, rel),
                                      None if state == "removed" else os.path.join(now_root, rel),
                                      state))
            else:
                rows.append({"name": rel, "state": state})
    return rows

def undo_session(project: str, cid: str = None, session: str = None,
                 apply: bool = False, diffs: bool = False) -> dict:
    """Put the folder back the way it was when a session started: files it
    changed or removed come back, files it made go.  What is there now is
    set aside first, so the undo can itself be undone."""
    real = os.path.realpath(project)
    res = {"project": real, "applied": False, "blockers": [], "warnings": []}
    cps = list_checkpoints(real)
    if cid:
        cp = next((c for c in cps if c["id"] == cid), None)
    elif session:       # the earliest start of that session: all of it
        cp = next((c for c in reversed(cps) if c.get("session") == session), None)
    else:
        cp = cps[0] if cps else None
    res["checkpoints"] = [{k: c.get(k) for k in ("id", "at", "agent", "session", "title", "files")}
                          for c in cps]
    if cp is None:
        res["blockers"].append("aht has no copy of this folder from "
                               + (f"the start of {cid or session}" if cid or session
                                  else "a session start"))
        return res
    ch = tree_changes(real, cp["path"], cp.get("skip") or CHECKPOINT_SKIP)
    res.update(checkpoint={k: cp.get(k) for k in ("id", "at", "agent", "session", "title")},
               changed=len(ch["changed"]), added=len(ch["added"]),
               removed=len(ch["removed"]), files=_rows(ch, real, cp["path"], diffs))
    act = activity_in(real)
    for s in act["sessions"]:
        if s.get("status") != "idle":
            res["blockers"] += _activity_blockers({"sessions": [s]}, "on this machine")
        else:
            res["warnings"].append("a session is still open in this project; tell it that "
                                   "the files were put back")
    if not apply or res["blockers"] or not res["files"]:
        return res
    keep = aht_home() / "undo" / _stamp()
    for rel in ch["changed"] + ch["added"]:
        dst = keep / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(os.path.join(real, rel), str(dst))
    for rel in ch["changed"] + ch["removed"]:
        _put(os.path.join(cp["path"], rel), os.path.join(real, rel))
    res.update(applied=True, kept=str(keep))
    log(f"UNDO {real} to {cp['id']}: {res['changed']} changed, {res['added']} made, "
        f"{res['removed']} removed; set aside in {keep}")
    return res

def cmd_checkpoint(args):
    if args.coverage:
        cov = checkpoint_coverage(args.max)
        if args.json:
            print(json.dumps(cov, indent=2))
            return 0
        home = str(Path.home())
        print(f"limit: {cov['max']:,} files per project")
        for r in cov["projects"][:args.top]:
            name = r["project"].replace(home, "~", 1)
            what = "no copy" if r["over"] else f"about {r['seconds']:g} s"
            print(f"  {'✗' if r['over'] else '✓'} {r['files']:>9,} files  {what:<12} {name}")
            for b in r.get("biggest") or []:
                print(f"        {b['files']:>9,}  {b['name']}/")
        if cov["over"]:
            print("\nleave big folders out of the copies:  aht config --set "
                  "checkpoint_excludes=results,data   (names, comma-separated)")
        return 0
    if not args.path:
        print("name a folder, or use --coverage", file=sys.stderr)
        return 2
    res = take_checkpoint(args.path, args.session, args.agent)
    if args.json:
        print(json.dumps(res, indent=2))
    elif not args.quiet:
        print(f"checkpoint {res['id']}: {res['files']} file(s) ({res['method']})"
              if res.get("ok", True) and res.get("id") else f"no checkpoint: {res.get('why')}")
    return 0 if res.get("id") else 1

def cmd_undo(args):
    real = os.path.realpath(args.path)
    if args.list:
        cps = list_checkpoints(real)
        if args.json:
            print(json.dumps({"project": real, "checkpoints": cps}, indent=2))
            return 0
        if not cps:
            print("no checkpoints of this folder yet (one is taken when a session starts)")
        for c in cps:
            print(f"{c['id']}   {time.strftime('%Y-%m-%d %H:%M', time.localtime(c['at']))}  "
                  f"{AGENT_NAMES.get(c.get('agent'), c.get('agent'))}"
                  + (f" — {c['title']}" if c.get("title") else "")
                  + f"   ({c.get('files')} files)")
        return 0
    res = undo_session(real, args.checkpoint, args.session, args.apply, args.diff)
    lines = []
    cp = res.get("checkpoint")
    if cp:
        lines.append(f"{'put back' if res['applied'] else 'would put back'}: {real}\n"
                     f"   as it was at {time.strftime('%Y-%m-%d %H:%M', time.localtime(cp['at']))}"
                     + (f", when “{cp['title']}” started" if cp.get("title") else ""))
        for f in res["files"]:
            mark = {"changed": "~", "added": "-", "removed": "+"}[f["state"]]
            lines.append(f"   {mark} {f['name']}" + ("   (made since: set aside)"
                                                     if f["state"] == "added" else ""))
            if args.diff and f.get("diff"):
                lines.append(f["diff"])
        if not res["files"]:
            lines.append("   nothing changed since then")
        elif res["applied"]:
            lines.append(f"   what was there is kept in {res['kept']}")
        elif not res["blockers"]:
            lines.append("(dry run — pass --apply to do it)")
    return _emit(args, res, lines)

# ---- loose ends ------------------------------------------------------------ #

_OFFER = re.compile(r"\b(say the word|just say so|want me to|shall I|should I|"
                    r"if you(?:'d| would)? (?:like|want|prefer)|let me know)\b", re.I)

def _ends_on_question(dig: dict):
    """("question" | "offer", sentence) when the agent's last message ends by
    asking you something or offering a next step; None otherwise."""
    ex = dig.get("exchanges") or []
    # masked before it is cut into paragraphs and sentences and their dashes
    # and backticks go: a key, a private key's lines too, is masked whole
    txt = redact((ex[-1].get("agent") or "").strip()) if ex else ""
    txt = re.split(r"\n\s*\**(?:Sources|References|Links)\**:?\**\s*\n", txt)[0].strip()
    para = re.split(r"\n\s*\n", txt)[-1].strip() if txt else ""
    sents = [x.strip(" *_-#>`") for x in re.split(r"(?<!e\.g\.)(?<!i\.e\.)(?<=[.!?])\s+",
                                                    " ".join(para.split()))]
    sents = [x for x in sents if x]
    def whole(i):               # "Just say so." means little without the one before
        return sents[i] if len(sents[i]) >= 40 or i == 0 else sents[i - 1] + " " + sents[i]
    n = len(sents)
    for i in reversed(range(max(0, n - 3), n)):
        if sents[i].endswith("?"):
            return "question", _masked(whole(i), 240)
    for i in reversed(range(max(0, n - 2), n)):
        if _OFFER.search(sents[i]):
            return "offer", _masked(whole(i), 240)
    return None

def loose_ends(days: int = 30) -> list:
    """Projects worked on in the last `days` with something left open:
    work not committed, open to-do items, or a last session that ended on a
    question to you."""
    reg = load_registry()
    now = time.time()
    open_here = set()
    for s in open_sessions_here():
        open_here.add(os.path.realpath(s.get("project") or "/"))
    rows = []
    for e in reg.get("projects", {}).values():
        real = e["real_path"]
        if not os.path.isdir(real) or e.get("away"):
            continue
        sessions = [s for s in list_sessions(real)
                    if not (s["agent"] == "claude" and _is_scripted(s["file"]))]
        if not sessions or now - (sessions[0]["updated"] or 0) > days * 86400:
            continue
        items = []
        g = git_state(real)
        n = g["dirty"] + g["untracked"] if g else 0
        if n:
            items.append({"kind": "uncommitted", "count": n,
                          "text": f"{n} file(s) not committed"})
        s = sessions[0]
        dig = events_digest(s, real, turns=1, tail=4 << 20)
        todos = [_masked(str(t.get("content") or t.get("subject") or t.get("title")
                             or ""), 120) for t in dig.get("todos") or []]
        todos = [t for t in todos if t]
        if todos:
            items.append({"kind": "todos", "count": len(todos),
                          "text": f"{len(todos)} open to-do item(s)", "items": todos[:8]})
        q = _ends_on_question(dig)
        if q:
            items.append({"kind": q[0], "text": q[1]})
        if items:
            rows.append({"project": real, "agent": s["agent"], "session": s["id"],
                         "title": dig.get("title") or _session_title(s),
                         "last": s["updated"], "open": _inside_any(real, open_here),
                         "items": items})
    rows.sort(key=lambda r: r["last"] or 0, reverse=True)
    return rows

def _inside_any(real: str, paths) -> bool:
    return any(_inside(p, real) for p in paths)

def cmd_loose_ends(args):
    rows = loose_ends(args.days)
    if args.json:
        print(json.dumps({"loose_ends": rows}, indent=2))
        return 0
    if not rows:
        print(f"nothing left open in the projects of the last {args.days} days")
    for r in rows:
        print(r["project"] + ("   (a session is open)" if r["open"] else ""))
        for it in r["items"]:
            if it["kind"] == "question":
                print(f"   ? it asked you: {it['text']}")
            elif it["kind"] == "offer":
                print(f"   → it offered: {it['text']}")
            else:
                print(f"   • {it['text']}")
                for t in it.get("items") or []:
                    print(f"       - {t}")
    return 0

# ---- a second opinion (USES TOKENS: off unless turned on) ------------------ #

OPINION_AGENTS = ("claude", "kimi")
OPINION_NOTE = ("\n\n(You work in a copy of the project, made to compare two agents on "
                "the same task. Make the changes the task needs, then say in a few "
                "lines what you changed and why.)")

def opinions_root() -> Path:
    return aht_home() / "opinions"

def _opinion_cmd(agent: str, exe: str, task: str) -> list:
    if agent == "claude":       # edits yes, commands no
        return [exe, "-p", task + OPINION_NOTE, "--permission-mode", "acceptEdits",
                "--output-format", "json"]
    return [exe, "-p", task + OPINION_NOTE, "--output-format", "text"]   # -p decides itself

def _opinion_meta(rid: str) -> dict:
    return json.loads((opinions_root() / rid / "meta.json").read_text())

def start_second_opinion(project: str, task: str, agents=OPINION_AGENTS) -> dict:
    real = os.path.realpath(project)
    res = {"project": real, "applied": False, "blockers": [], "warnings": []}
    agents = list(dict.fromkeys(agents))
    if not cfg_get("second_opinion", False):
        res["blockers"].append("a second opinion uses the tokens of both agents, so it is "
                               "off: turn it on in the window's Settings, or with "
                               "aht config --set second_opinion=true")
    if not os.path.isdir(real):
        res["blockers"].append(f"not a folder: {real}")
    if not (task or "").strip():
        res["blockers"].append("say what both should do (--task)")
    if len(agents) != 2:
        res["blockers"].append("name two different agents")
    for a in agents:
        if a not in OPINION_AGENTS:
            res["blockers"].append(f"{a}: a second opinion works with "
                                   f"{' and '.join(AGENT_NAMES[x] for x in OPINION_AGENTS)}")
        elif not agent_cli(a):
            res["blockers"].append(f"{AGENT_NAMES[a]} is not installed on this machine")
    if res["blockers"]:
        return res
    rid = _stamp()
    keep_out_of_time_machine(opinions_root())
    base = opinions_root() / rid
    name = os.path.basename(real)
    cap = int(cfg_get("checkpoint_max_files", 20000))
    got = copy_tree(real, str(base / "start" / name), OPINION_SKIP, cap=cap)
    for a in agents:
        if got["ok"]:
            got = copy_tree(str(base / "start" / name), str(base / a / name), (), cap=cap)
    if not got["ok"]:
        shutil.rmtree(base, ignore_errors=True)
        res["blockers"].append(f"no copies made: {got['why']}")
        return res
    _write_json(base / "meta.json", {
        "id": rid, "project": real, "task": task.strip(), "agents": agents,
        "started": time.time(), "state": {a: {"state": "starting"} for a in agents}})
    _spawn_aht(["second-opinion", "--run", rid])
    res.update(applied=True, id=rid)
    log(f"OPINION {rid} {real}: {' and '.join(agents)}")
    return res

def _opinion_answer(agent: str, out: Path) -> dict:
    try:
        raw = out.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"answer": ""}
    if agent == "claude":
        try:
            obj = json.loads(raw)
            u = obj.get("usage") or {}
            return {"answer": _masked(str(obj.get("result") or ""), 6000),
                    "cost_usd": obj.get("total_cost_usd"),
                    "tokens": sum(int(u.get(k) or 0) for k in (
                        "input_tokens", "output_tokens", "cache_creation_input_tokens",
                        "cache_read_input_tokens"))}
        except Exception:
            pass
    return {"answer": _masked(raw, 6000)}

def run_second_opinion(rid: str) -> None:
    """Both agents at once, each in its own copy; the state is kept in the
    run's meta.json for the window and `--show`."""
    base = opinions_root() / rid
    meta = _opinion_meta(rid)
    name = os.path.basename(meta["project"])
    env = dict(os.environ)
    env.pop("CLAUDECODE", None)
    procs = {}
    for a in meta["agents"]:
        with open(base / f"{a}.out", "wb") as out, open(base / f"{a}.err", "wb") as err:
            try:
                p = subprocess.Popen(_opinion_cmd(a, agent_cli(a), meta["task"]),
                                     cwd=str(base / a / name), stdin=subprocess.DEVNULL,
                                     stdout=out, stderr=err, env=env)
            except OSError as e:
                meta["state"][a] = {"state": "failed", "error": str(e)}
                continue
        procs[a] = (p, time.time())
        meta["state"][a] = {"state": "working", "pid": p.pid, "started": time.time()}
    _write_json(base / "meta.json", meta)
    deadline = time.time() + 3600
    while procs:
        time.sleep(1)
        for a, (p, t0) in list(procs.items()):
            rc = p.poll()
            if rc is None and time.time() > deadline:
                p.kill()
                rc = p.wait()
            if rc is None:
                continue
            ans = _opinion_answer(a, base / f"{a}.out")
            if rc != 0 and not ans.get("answer"):
                try:
                    err = (base / f"{a}.err").read_text(errors="replace").strip()
                    ans["answer"] = redact(err[-(1 << 20):])[-600:]
                except OSError:
                    pass
            meta["state"][a] = dict(ans, state="done" if rc == 0 else "failed", exit=rc,
                                    seconds=int(time.time() - t0))
            del procs[a]
            _write_json(base / "meta.json", meta)
    meta["finished"] = time.time()
    _write_json(base / "meta.json", meta)
    _notify(f"Second opinion: {name}",
            " and ".join(AGENT_NAMES[a] for a in meta["agents"])
            + " are done — open aht to compare")

def list_opinions() -> list:
    out = []
    root = opinions_root()
    for d in sorted(root.iterdir() if root.is_dir() else [], reverse=True):
        try:
            m = json.loads((d / "meta.json").read_text())
        except Exception:
            continue
        out.append({k: m.get(k) for k in ("id", "project", "task", "agents", "started",
                                          "finished", "taken")}
                   | {"states": {a: s.get("state") for a, s in m["state"].items()}})
    return out

def show_opinion(rid: str, diffs: bool = False) -> dict:
    meta = _opinion_meta(rid)
    base = opinions_root() / rid
    name = os.path.basename(meta["project"])
    start = str(base / "start" / name)
    res = dict(meta, results={})
    for a in meta["agents"]:
        tree = str(base / a / name)
        st = dict(meta["state"].get(a) or {})
        st.pop("pid", None)
        ch = tree_changes(tree, start, OPINION_SKIP)
        st["files"] = _rows(ch, tree, start, diffs)
        res["results"][a] = st
    res.pop("state", None)
    if os.path.isdir(meta["project"]):
        since = tree_changes(meta["project"], start, OPINION_SKIP)
        res["project_changed"] = since["changed"] + since["added"] + since["removed"]
    return res

def take_opinion(rid: str, agent: str, apply: bool = False) -> dict:
    """Bring one agent's changes into the project.  Refused for files that
    changed in the project since the copies were made."""
    meta = _opinion_meta(rid)
    real = meta["project"]
    base = opinions_root() / rid
    name = os.path.basename(real)
    start, tree = str(base / "start" / name), str(base / agent / name)
    res = {"project": real, "id": rid, "from": agent, "applied": False,
           "blockers": [], "warnings": []}
    if agent not in meta["agents"]:
        res["blockers"].append(f"{agent} did not work on this one")
        return res
    if (meta["state"].get(agent) or {}).get("state") == "working":
        res["blockers"].append(f"{AGENT_NAMES[agent]} is still working")
    ch = tree_changes(tree, start, OPINION_SKIP)
    touched = ch["changed"] + ch["added"] + ch["removed"]
    moved = [rel for rel in touched
             if not (_same_file(os.path.join(real, rel), os.path.join(start, rel))
                     or not (os.path.lexists(os.path.join(real, rel))
                             or os.path.lexists(os.path.join(start, rel))))]
    if moved:
        res["blockers"].append("changed in the project since the copies were made: "
                               + ", ".join(moved[:8]))
    res["blockers"] += _activity_blockers(
        {"sessions": [s for s in activity_in(real)["sessions"] if s.get("status") != "idle"]},
        "on this machine")
    res["files"] = _rows(ch, tree, start, False)
    if not apply or res["blockers"] or not touched:
        return res
    keep = aht_home() / "undo" / _stamp()
    for rel in touched:
        cur = os.path.join(real, rel)
        if os.path.lexists(cur):
            (keep / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(cur, str(keep / rel))
    for rel in ch["changed"] + ch["added"]:
        _put(os.path.join(tree, rel), os.path.join(real, rel))
    meta["taken"] = agent
    _write_json(base / "meta.json", meta)
    res.update(applied=True, kept=str(keep))
    log(f"OPINION {rid}: took {agent}'s {len(touched)} file(s) into {real}; kept {keep}")
    return res

def cmd_second_opinion(args):
    if args.run:
        run_second_opinion(args.run)
        return 0
    if args.list:
        rows = list_opinions()
        if args.json:
            print(json.dumps({"opinions": rows}, indent=2))
            return 0
        for r in rows:
            print(f"{r['id']}  {r['project']}\n   {_clip(r['task'], 100)}\n   "
                  + ", ".join(f"{AGENT_NAMES[a]}: {s}" for a, s in r["states"].items())
                  + (f"   (took {AGENT_NAMES[r['taken']]}'s)" if r.get("taken") else ""))
        return 0
    if args.discard:
        base = opinions_root() / args.discard
        if not (base / "meta.json").is_file():
            print(f"no second opinion {args.discard}", file=sys.stderr)
            return 1
        shutil.rmtree(base)
        print(f"removed the copies of {args.discard}")
        return 0
    if args.show:
        res = show_opinion(args.show, args.diff)
        if args.json:
            print(json.dumps(res, indent=2, default=str))
            return 0
        print(f"{res['project']}\n   task: {res['task']}")
        for a, r in res["results"].items():
            print(f"\n{AGENT_NAMES[a]} — {r.get('state')}"
                  + (f", {r['seconds']} s" if r.get("seconds") else "")
                  + (f", ${r['cost_usd']:.2f}" if r.get("cost_usd") else ""))
            for f in r["files"]:
                print(f"   {f['state']:<8} {f['name']}")
            if r.get("answer"):
                print("   " + r["answer"].replace("\n", "\n   "))
        return 0
    if args.take:
        res = take_opinion(args.take, args.agent or "", args.apply)
        lines = [f"{'took' if res['applied'] else 'would take'} "
                 f"{AGENT_NAMES.get(res['from'], res['from'])}'s changes into {res['project']}"]
        lines += [f"   {f['state']:<8} {f['name']}" for f in res.get("files") or []]
        if res["applied"]:
            lines.append(f"   what was there is kept in {res['kept']}")
        elif not res["blockers"]:
            lines.append("(dry run — pass --apply to do it)")
        return _emit(args, res, lines)
    if not args.path:
        print("name a project folder, or use --list / --show / --take", file=sys.stderr)
        return 2
    agents = [a.strip() for a in (args.agents or ",".join(OPINION_AGENTS)).split(",")]
    res = start_second_opinion(args.path, args.task or "", agents)
    lines = []
    if res["applied"]:
        lines += [f"started {res['id']}: {' and '.join(AGENT_NAMES[a] for a in agents)} "
                  "work on the task, each in its own copy",
                  f"   see how it goes:  aht second-opinion --show {res['id']}"]
    return _emit(args, res, lines)

# ---- the night shift (USES TOKENS: off unless turned on) ------------------- #

def night_jobs_path() -> Path:
    return aht_home() / "night-shift.json"

def _load_jobs() -> list:
    try:
        return json.loads(night_jobs_path().read_text())
    except Exception:
        return []

def _next_time(hhmm: str, after: float) -> float:
    m = re.fullmatch(r"(\d{1,2})[:.](\d{2})", (hhmm or "").strip())
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ValueError(f"not a time of day: {hhmm!r} (use HH:MM)")
    lt = time.localtime(after)
    h, mi = int(m.group(1)), int(m.group(2))
    t = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, h, mi, 0, 0, 0, -1))
    if t <= after:
        t = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday + 1, h, mi, 0, 0, 0, -1))
    return t

def plan_night_shift(project: str, task: str, start: str, back: str,
                     remote: str = None, apply: bool = False) -> dict:
    """Hand a project over with a task at `start`, take it back at `back`."""
    real = os.path.realpath(project)
    res = {"project": real, "applied": False, "blockers": [], "warnings": []}
    if not cfg_get("night_shift", False):
        res["blockers"].append("the night shift runs an agent with your task, which uses "
                               "tokens, so it is off: turn it on in the window's Settings, "
                               "or with aht config --set night_shift=true")
    if not handover_supported():
        res["blockers"].append("the night shift needs handover, which this build lacks")
    if not (task or "").strip():
        res["blockers"].append("say what the agent should work on (--task)")
    rem = remote or cfg_get("default_remote") or next(iter(sorted(remotes_config())), None)
    if rem not in remotes_config():
        res["blockers"].append("no machine to hand over to; add one first (aht remote add)")
    now = time.time()
    try:
        t0 = now if start in (None, "", "now") else _next_time(start, now)
        t1 = _next_time(back, t0)
    except ValueError as e:
        res["blockers"].append(str(e))
        return res
    if any(j["project"] == real and j["state"] in ("planned", "starting", "started",
                                                   "returning") for j in _load_jobs()):
        res["blockers"].append("this project already has a night shift")
    job = {"id": _stamp(), "project": real, "task": (task or "").strip(), "remote": rem,
           "start_at": t0, "back_at": t1, "state": "planned", "log": []}
    res["job"] = job
    if not apply or res["blockers"]:
        return res
    with Lock(timeout=10):
        jobs = [j for j in _load_jobs() if now - j.get("back_at", now) < 30 * 86400]
        jobs.append(job)
        _write_json(night_jobs_path(), jobs)
    log(f"NIGHT {real}: planned {time.ctime(t0)} to {time.ctime(t1)} on {rem}")
    res["applied"] = True
    if t0 <= now:
        night_shift_tick()
    return res

def _job_note(j: dict, text: str) -> None:
    j.setdefault("log", []).append(f"{time.strftime('%Y-%m-%d %H:%M')} {text}")
    del j["log"][:-20]

def night_shift_tick() -> list:
    """Run by the notices agent every half minute: start what is due, take
    back what is over.  The work itself happens in a process of its own."""
    out = []
    if not night_jobs_path().is_file():
        return out
    try:
        with Lock(timeout=5):
            jobs, now, changed = _load_jobs(), time.time(), False
            for j in jobs:
                st, name = j.get("state"), os.path.basename(j["project"])
                if st in ("starting", "returning"):
                    if not _pid_alive(int(j.get("pid") or 0)):
                        j["state"] = "failed" if st == "starting" else "started"
                        j["retry_at"] = now + 300
                        _job_note(j, "the step ended without a word")
                        changed = True
                elif st == "planned" and now >= j["start_at"]:
                    if now - j["start_at"] > 3600:
                        j["state"] = "missed"
                        _job_note(j, "not started: this Mac was asleep or off at the time")
                        out.append({"kind": "night", "title": f"Night shift: {name}",
                                    "message": "did not start — this Mac was asleep at "
                                               "the time"})
                    else:
                        j["state"], j["pid"] = "starting", _spawn_aht(
                            ["night-shift", "--step", j["id"]])
                    changed = True
                elif st == "started" and now >= j["back_at"] and now >= j.get("retry_at", 0):
                    j["state"], j["pid"] = "returning", _spawn_aht(
                        ["night-shift", "--step", j["id"]])
                    changed = True
            if changed:
                _write_json(night_jobs_path(), jobs)
    except TimeoutError:
        pass
    return out

def _update_job(jid: str, **fields) -> dict:
    with Lock(timeout=30):
        jobs = _load_jobs()
        j = next((x for x in jobs if x["id"] == jid), None)
        if j is None:
            return {}
        note = fields.pop("note", None)
        j.update(fields)
        if note:
            _job_note(j, note)
        _write_json(night_jobs_path(), jobs)
        return j

def night_shift_step(jid: str) -> None:
    j = next((x for x in _load_jobs() if x["id"] == jid), None)
    if not j:
        return
    name = os.path.basename(j["project"])
    me = _aht_argv()
    if j["state"] == "starting":
        r = subprocess.run(me + ["handover", j["project"], "--to", j["remote"],
                                 "--task=" + j["task"], "--apply", "--json"],
                           capture_output=True, text=True, timeout=7200, cwd="/")
        try:
            d = json.loads(r.stdout)
        except Exception:
            d = {"error": (r.stderr or r.stdout).strip()[-300:]}
        if not d.get("applied"):
            # the link dropped while the session started: ask the other
            # machine whether it runs (a session that started counts)
            uid, e = _entry_for(load_registry(), os.path.realpath(j["project"]))
            if (e or {}).get("handing"):
                resolve_handing(uid, force=True)
                uid, e = _entry_for(load_registry(), os.path.realpath(j["project"]))
            if (e or {}).get("away"):
                d = {"applied": True}
        if d.get("applied"):
            _update_job(jid, state="started", note=f"handed over to {j['remote']}")
            _notify(f"Night shift: {name}", f"working on {j['remote']} until "
                    + time.strftime("%H:%M", time.localtime(j["back_at"])))
        else:
            why = "; ".join((d.get("blockers") or [])[:2]) or d.get("error") or "it failed"
            _update_job(jid, state="failed", note=f"not handed over: {why}")
            _notify(f"Night shift: {name}", f"did not start — {why}")
        return
    if j["state"] == "returning":
        r = subprocess.run(me + ["reclaim", j["project"], "--stop", "--apply", "--json"],
                           capture_output=True, text=True, timeout=7200, cwd="/")
        try:
            d = json.loads(r.stdout)
        except Exception:
            d = {"error": (r.stderr or r.stdout).strip()[-300:]}
        if d.get("applied"):
            _update_job(jid, state="back", note="taken back")
            _notify(f"Night shift: {name}", "is back on this Mac — see what changed in aht")
            return
        why = "; ".join((d.get("blockers") or [])[:2]) or d.get("error") or "it failed"
        first = not j.get("told_late")
        _update_job(jid, state="started", retry_at=time.time() + 300, told_late=True,
                    note=f"not taken back yet: {why}")
        if first:
            _notify(f"Night shift: {name}", "still busy — aht takes it back once the "
                    "session is done")

def cmd_night_shift(args):
    if args.step:
        night_shift_step(args.step)
        return 0
    if args.cancel:
        j = _update_job(args.cancel)
        if not j:
            print(f"no night shift {args.cancel}", file=sys.stderr)
            return 1
        was = j["state"]
        _update_job(args.cancel, state="cancelled", note="cancelled")
        print("cancelled" + (" — the project is still over there; take it back with "
                             f"aht reclaim {shlex.quote(j['project'])}"
                             if was in ("started", "returning") else ""))
        return 0
    if args.list or not args.path:
        jobs = _load_jobs()
        if args.json:
            print(json.dumps({"jobs": jobs}, indent=2))
            return 0
        if not jobs:
            print("no night shift planned")
        for j in jobs:
            fmt = lambda t: time.strftime("%a %H:%M", time.localtime(t))
            print(f"{j['id']}  {j['state']:<10} {j['project']} on {j['remote']}, "
                  f"{fmt(j['start_at'])} → {fmt(j['back_at'])}\n   {_clip(j['task'], 100)}")
            for l in j.get("log", [])[-3:]:
                print(f"     {l}")
        return 0
    res = plan_night_shift(args.path, args.task, args.start, args.back, args.to, args.apply)
    j = res.get("job") or {}
    lines = []
    if j:
        fmt = lambda t: time.strftime("%a %H:%M", time.localtime(t))
        lines += [f"{'planned' if res['applied'] else 'would plan'}: {j['project']}",
                  f"   {fmt(j['start_at'])}  hand over to {j['remote']} with the task",
                  f"   {fmt(j['back_at'])}  take it back (once the session is done)",
                  "   this Mac has to be awake then; the agent there uses its tokens"]
        if not res["applied"] and not res["blockers"]:
            lines.append("(dry run — pass --apply to plan it)")
    return _emit(args, res, lines)

# ---- sessions for Spotlight and other front-ends ---------------------------- #

_FORKED_RE = re.compile(rb'"forkedFrom"\s*:\s*\{[^{}]*?"sessionId"\s*:\s*"([0-9A-Za-z-]{8,64})"')

def _branch_of(transcript):
    """Claude Code's /branch starts a session with a copy of the one it
    branches from, each copied entry marked {"forkedFrom": {"sessionId": …}}
    (a top-level key: the same words inside a message are escaped).
    -> (that session's id, when the branch was made), or (None, None) for a
    session that is no branch.  When: its first entry of its own, else when
    its file was made."""
    try:
        fh = open(transcript, "rb")
    except OSError:
        return None, None
    parent, when = None, None
    with fh:
        # the copies come first, and the mark is the last key of each entry:
        # the whole first entry, however big (a pasted picture)
        first = fh.readline()
        while first and not first.strip():
            first = fh.readline()
        m = _FORKED_RE.search(first)
        if not m:
            return None, None
        parent = m.group(1).decode()
        for line in fh:
            m = _FORKED_RE.search(line)
            if m:
                parent = m.group(1).decode()
                continue
            try:
                when = _when(json.loads(line).get("timestamp"))
            except Exception:
                continue
            if when:
                break
    if when is None:
        st = _stat(transcript)
        when = st and (getattr(st, "st_birthtime", None) or st.st_mtime)
    return parent, when

def project_sessions(project: str) -> list:
    """Every session of one project, newest first, each branch (/branch in
    Claude Code) right under the session it came from: rows in that order,
    with "depth".  Newest means the latest work in a session or in any of
    its branches.  Titles and times come from the search index."""
    real = os.path.realpath(project)
    found = list_sessions(real)
    try:
        update_search_index()
    except Exception as e:
        warn(f"SESSIONS index: {e}")
    known = {}
    keys = [f"{s['agent']}:{s['id']}" for s in found]
    if keys:
        try:
            db = _open_search_db()
            for i in range(0, len(keys), 500):
                part = keys[i:i + 500]
                known.update({r[0]: r[1:] for r in db.execute(
                    "select key, title, started, updated from sessions where key in (%s)"
                    % ",".join("?" * len(part)), part)})
            db.close()
        except Exception as e:
            warn(f"SESSIONS index: {e}")
    try:
        open_now = {r["session"]: r for r in running_sessions() if r.get("session")}
    except Exception:
        open_now = {}
    rows = {}
    for s in found:
        key = f"{s['agent']}:{s['id']}"
        title, started, updated = known.get(key) or (None, None, None)
        if key not in known:
            title = _session_title(s)
        parent, branched = _branch_of(s["file"]) if s["agent"] == "claude" else (None, None)
        live = open_now.get(s["id"]) if s["agent"] == "claude" else None
        rows[key] = {"agent": s["agent"], "id": s["id"],
                     "title": redact(title) if title else s.get("title"),
                     "started": started, "updated": max(s["updated"] or 0, updated or 0),
                     "branched": branched, "parent": parent and f"claude:{parent}",
                     "open": live is not None, "pid": live and live["pid"],
                     "parent_gone": False}
    kids = {}
    for key, r in rows.items():
        if r["parent"] in rows and r["parent"] != key:
            kids.setdefault(r["parent"], []).append(key)
        else:
            r["parent_gone"] = r["parent"] is not None
            r["parent"] = None

    def latest(key, seen=()):
        return max([rows[key]["updated"]] + [latest(k, seen + (key,)) for k in
                                             kids.get(key, []) if k not in seen])
    out = []

    def walk(keys, depth, seen):
        for key in sorted(keys, key=lambda k: -latest(k)):
            if key in seen:
                continue
            out.append(dict(rows[key], depth=depth,
                            parent=rows[key]["parent"] and rows[key]["parent"].split(":", 1)[1]))
            walk(kids.get(key, []), depth + 1, seen | {key})
    walk([k for k, r in rows.items() if r["parent"] is None], 0, frozenset())
    return out

def cmd_sessions(args):
    """Every indexed session, newest first: what the app puts in Spotlight.
    With a project: that project's sessions, branches under their origin."""
    if args.project:
        rows = project_sessions(args.project)
        if args.json:
            print(json.dumps({"project": os.path.realpath(args.project), "sessions": rows},
                             indent=2))
            return 0
        day = lambda t: time.strftime("%Y-%m-%d %H:%M", time.localtime(t)) if t else "—"
        n = sum(1 for r in rows if r["branched"])
        print(f"{len(rows)} session(s) in {os.path.realpath(args.project)}"
              + (f", {n} of them branches" if n else ""))
        for r in rows:
            mark = "⑂ " if r["branched"] else ""
            when = (f"branched {day(r['branched'])}" if r["branched"]
                    else f"started {day(r['started'])}")
            print("  " + "    " * r["depth"] + mark + (r["title"] or "(no title)")
                  + ("   [open now]" if r["open"] else ""))
            print("  " + "    " * r["depth"] + f"  {AGENT_NAMES.get(r['agent'], r['agent'])}, "
                  f"{when}, last {day(r['updated'])}, {r['id']}")
        if rows:
            print("Continue one:  aht resume-here <project> --session <id> "
                  "[--agent kimi|codex]")
        return 0
    update_search_index()
    rows = []
    try:
        db = _open_search_db()
        q = ("select agent, session, project, title, started, updated, live from sessions "
             "where live = 1 order by updated desc limit ?")
        for a, s, p, t, st, up, live in db.execute(q, (args.limit,)):
            if p and _inside(os.path.realpath(p), os.path.realpath(str(aht_home()))):
                continue
            rows.append({"agent": a, "session": s, "project": p,
                         "title": redact(t) if t else None, "started": st, "updated": up})
        db.close()
    except Exception as e:
        print(json.dumps({"error": str(e)}) if args.json else str(e), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"sessions": rows}, indent=2))
    else:
        for r in rows:
            print(f"{AGENT_NAMES.get(r['agent'], r['agent']):<12} "
                  f"{r['title'] or r['session']}   {r['project']}")
    return 0

# ---- a session carries its iTerm2 tab's title (what the Claude app shows) ---- #

TABS_FRESH = 20                 # seconds a look at iTerm2's tabs stays good
_TABS_SCRIPT = """
tell application "iTerm2"
  set sep to character id 31
  set out to ""
  set wi to 0
  repeat with w in windows
    set wi to wi + 1
    set ti to 0
    try
      repeat with t in tabs of w
        set ti to ti + 1
        try
          set n to count of sessions of t
          set i to 0
          repeat with s in sessions of t
            set i to i + 1
            set v to ""
            set u to ""
            set p to ""
            try
              set v to (variable named "tab.titleOverride") of s
            end try
            try
              set u to (variable named "user.ahtTitle") of s
            end try
            try
              set p to profile name of s
            end try
            set out to out & (tty of s) & sep & i & sep & n & sep & wi & sep & ti & sep & p & sep & u & sep & v & linefeed
          end repeat
        end try
      end repeat
    end try
  end repeat
  return out
end tell
"""

_TAB_SCRIPT = """
on run argv
  set want to item 1 of argv
  set sep to character id 31
  tell application "iTerm2"
    set all to tty of every session of every tab of every window
    repeat with wi from 1 to count of all
      set ws to item wi of all
      repeat with ti from 1 to count of ws
        set ts to item ti of ws
        repeat with si from 1 to count of ts
          if item si of ts is want then
            set s to session si of tab ti of window wi
            set v to ""
            set u to ""
            set k to ""
            try
              set v to (variable named "tab.titleOverride") of s
            end try
            try
              set u to (variable named "user.ahtTitle") of s
            end try
            try
              set k to (variable named "tab.id") of s
            end try
            if v is missing value then set v to ""
            if u is missing value then set u to ""
            if k is missing value then set k to ""
            return "ok" & sep & (count of ts) & sep & k & sep & u & sep & v
          end if
        end repeat
      end repeat
    end repeat
  end tell
  return "none"
end run
"""

def tabs_cache_path() -> Path:
    return aht_home() / "run" / "iterm-tabs.json"

def tab_names_path() -> Path:
    return aht_home() / "run" / "tab-names.json"

def _iterm_running() -> bool:
    try:
        r = subprocess.run(["ps", "-Ac", "-o", "comm="], capture_output=True, text=True,
                           timeout=10, cwd="/")
        return any(l.strip() == "iTerm2" for l in r.stdout.splitlines())
    except Exception:
        return False

def iterm_tabs(max_age: float = TABS_FRESH) -> dict:
    """{tty: {"title": the tab's own title ("" when none was set), "pane": n,
    "panes": n, "window": n, "tab": n}} for every iTerm2 session.  Asking iTerm2 takes about a
    second, so the answer is kept for `max_age` seconds.  Only the title you
    gave a tab counts, not the one programs write into it."""
    if os.environ.get("AHT_ITERM_TABS"):                # tests: a stand-in
        try:
            return json.loads(Path(os.environ["AHT_ITERM_TABS"]).read_text())
        except Exception:
            return {}
    try:
        c = json.loads(tabs_cache_path().read_text())
        if time.time() - float(c.get("at") or 0) < max_age:
            return c.get("tabs") or {}
    except Exception:
        pass
    if not IS_MAC or not _iterm_running():
        return {}
    try:
        r = subprocess.run(["/usr/bin/osascript", "-"], input=_TABS_SCRIPT,
                           capture_output=True, text=True, timeout=20, cwd="/")
    except Exception as e:
        warn(f"TABS iTerm2 did not answer: {e}")
        return {}
    tabs = {}
    for line in r.stdout.splitlines():
        parts = line.split("\x1f")
        if len(parts) >= 8 and parts[0].startswith("/dev/"):
            # the title the user gave the tab; else the one aht gave a tab it
            # opened again (a script cannot set the first kind)
            override = "\x1f".join(parts[7:]).strip()
            mine = parts[6].strip()
            profile = parts[5].strip()
            if override == "missing value":         # AppleScript's word for "not set"
                override = ""
            if mine == "missing value":
                mine = ""
            tabs[parts[0]] = {"title": override or mine,
                              "override": bool(override),
                              "pane": int(parts[1] or 1), "panes": int(parts[2] or 1),
                              "window": int(parts[3] or 1), "tab": int(parts[4] or 1),
                              "profile": "" if profile == "missing value" else profile}
    if r.returncode != 0:
        warn(f"TABS iTerm2: {(r.stderr or '').strip()[-200:]}")
        return tabs
    _write_json(tabs_cache_path(), {"at": time.time(), "tabs": tabs})
    return tabs

def _live_tabs_file() -> Path:
    return Path(os.environ.get("AHT_ITERM_LIVE") or os.environ["AHT_ITERM_TABS"])

def _note_tab_title(tty: str, title: str, override: bool) -> None:
    """Tell the kept look at all tabs what one tab is called now."""
    try:
        c = json.loads(tabs_cache_path().read_text())
        if tty in (c.get("tabs") or {}):
            c["tabs"][tty].update(title=title, override=override)
            _write_json(tabs_cache_path(), c)
    except Exception:
        pass

def iterm_tab(tty: str):
    """One iTerm2 tab, asked for now (about 0.15 s, where all tabs take
    seconds): {"title", "override", "id" (the tab's id in iTerm2's API),
    "panes"}; {} when the terminal is not an iTerm2 tab, None when iTerm2
    did not answer."""
    if os.environ.get("AHT_ITERM_TABS"):                # tests: a stand-in
        try:
            e = json.loads(_live_tabs_file().read_text()).get(tty)
        except Exception:
            return None
        return {} if e is None else {
            "title": str(e.get("title") or ""), "override": bool(e.get("override")),
            "id": str(e.get("id") or ""), "panes": int(e.get("panes") or 1)}
    if not IS_MAC or not _iterm_running():
        return {}
    try:
        r = subprocess.run(["/usr/bin/osascript", "-", tty], input=_TAB_SCRIPT,
                           capture_output=True, text=True, timeout=5, cwd="/")
    except Exception as e:
        warn(f"TABS iTerm2 did not answer: {e}")
        return None
    out = r.stdout.rstrip("\n")
    parts = out.split("\x1f")
    if r.returncode != 0 or not (out == "none" or parts[0] == "ok" and len(parts) >= 5):
        warn(f"TABS iTerm2: {(r.stderr or '').strip()[-200:]}")
        return None
    if out == "none":
        return {}
    override = "\x1f".join(parts[4:]).strip()
    tab = {"title": override or parts[3].strip(), "override": bool(override),
           "id": parts[2].strip(), "panes": int(parts[1]) if parts[1].isdigit() else 1}
    _note_tab_title(tty, tab["title"], tab["override"])
    return tab

def iterm_tab_title(tty: str):
    """The title of one iTerm2 tab, asked for now: "" when the tab has none
    or the terminal is not an iTerm2 tab, None when iTerm2 did not answer.
    The kept look at all tabs learns it too."""
    tab = iterm_tab(tty)
    return None if tab is None else str(tab.get("title") or "")

# A script cannot set a title you gave a tab; iTerm2's Python API can, the
# same way Edit Tab Title does.  aht speaks it itself (a WebSocket on a Unix
# socket, carrying protobuf; iterm2.com/python-api), so it needs no
# packages.  iTerm2 serves it only with Settings → General → Magic → Enable
# Python API switched on, and lets aht in with a one-time key it hands out
# over AppleScript.

def iterm_api_socket() -> Path:
    if os.environ.get("AHT_ITERM_API"):                 # tests: a stand-in
        return Path(os.environ["AHT_ITERM_API"])
    return Path.home() / "Library" / "Application Support" / "iTerm2" / "private" / "socket"

def iterm_api_on() -> bool:
    """iTerm2's Python API is switched on (and iTerm2 is open)."""
    try:
        return stat.S_ISSOCK(iterm_api_socket().stat().st_mode)
    except OSError:
        return False

def iterm_pref(key: str):
    """One of iTerm2's settings as `defaults` prints it ("1", "0", …), or
    None when it was never set (iTerm2 then uses its default).  Only read."""
    if os.environ.get("AHT_ITERM_PREFS"):               # tests: a stand-in
        try:
            v = json.loads(Path(os.environ["AHT_ITERM_PREFS"]).read_text()).get(key)
        except Exception:
            return None
        return None if v is None else str(v)
    if not IS_MAC:
        return None
    try:
        r = subprocess.run(["/usr/bin/defaults", "read", "com.googlecode.iterm2", key],
                           capture_output=True, text=True, timeout=10, cwd="/")
    except Exception:
        return None
    return r.stdout.strip() if r.returncode == 0 else None

def _pb_varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b, n = n & 0x7F, n >> 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)

def _pb(num: int, value) -> bytes:
    """One protobuf field: an int, a float (a double), a str or bytes."""
    import struct
    if isinstance(value, float):
        return _pb_varint(num << 3 | 1) + struct.pack("<d", value)
    if isinstance(value, int):
        return _pb_varint(num << 3) + _pb_varint(value)
    if isinstance(value, str):
        value = value.encode()
    return _pb_varint(num << 3 | 2) + _pb_varint(len(value)) + value

def _pb_fields(buf: bytes) -> dict:
    """{field number: [values]} of a protobuf message: ints for numbers,
    bytes for the rest."""
    out, i = {}, 0
    def varint():
        nonlocal i
        n = shift = 0
        while True:
            b = buf[i]
            i += 1
            n |= (b & 0x7F) << shift
            shift += 7
            if not b & 0x80:
                return n
    while i < len(buf):
        key = varint()
        wire = key & 7
        if wire == 0:
            v = varint()
        elif wire in (1, 5):
            v, i = buf[i:i + (8 if wire == 1 else 4)], i + (8 if wire == 1 else 4)
        elif wire == 2:
            n = varint()
            v, i = buf[i:i + n], i + n
        else:
            raise ValueError(f"protobuf wire type {wire}")
        out.setdefault(key >> 3, []).append(v)
    return out

def _ws_send(sock, payload: bytes, opcode: int = 2) -> None:
    """One WebSocket frame from a client (so masked)."""
    import struct
    n, mask = len(payload), os.urandom(4)
    head = bytes([0x80 | opcode])
    if n < 126:
        head += bytes([0x80 | n])
    elif n < 1 << 16:
        head += bytes([0x80 | 126]) + struct.pack(">H", n)
    else:
        head += bytes([0x80 | 127]) + struct.pack(">Q", n)
    sock.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

def _ws_recv(sock, rfile) -> bytes:
    """One whole WebSocket message, its frames put together."""
    import struct
    def exact(n):
        b = rfile.read(n)
        if b is None or len(b) < n:
            raise ConnectionError("iTerm2 closed the connection")
        return b
    data = b""
    while True:
        b0, b1 = exact(2)
        n = b1 & 0x7F
        if n == 126:
            n = struct.unpack(">H", exact(2))[0]
        elif n == 127:
            n = struct.unpack(">Q", exact(8))[0]
        mask = exact(4) if b1 & 0x80 else None
        part = exact(n)
        if mask:
            part = bytes(b ^ mask[i % 4] for i, b in enumerate(part))
        op = b0 & 0x0F
        if op == 8:
            raise ConnectionError("iTerm2 closed the connection")
        if op == 9:                                     # ping
            _ws_send(sock, part, 10)
            continue
        if op == 10:
            continue
        data += part
        if b0 & 0x80:
            return data

def _iterm_api_key():
    """(cookie, key) for one connection to iTerm2's API."""
    if os.environ.get("AHT_ITERM_API_KEY"):             # tests: a stand-in
        return tuple(os.environ["AHT_ITERM_API_KEY"].split(" ", 1))
    r = subprocess.run(["/usr/bin/osascript", "-e", 'tell application "iTerm2" to '
                        'request cookie and key for app named "aht"'],
                       capture_output=True, text=True, timeout=10, cwd="/")
    cookie, _, key = r.stdout.strip().partition(" ")
    if r.returncode != 0 or not cookie or not key:
        raise RuntimeError("iTerm2 gave aht no key for its Python API: "
                           + ((r.stderr or "").strip()[-160:] or "no answer"))
    return cookie, key

def iterm_api(request: bytes, timeout: float = 5) -> dict:
    """Send one request (a ClientOriginatedMessage with id 1) to iTerm2's
    Python API; the fields of its answer."""
    import base64
    import socket
    cookie, key = _iterm_api_key()
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(str(iterm_api_socket()))
        sock.sendall((
            "GET / HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n"
            "Connection: Upgrade\r\nSec-WebSocket-Version: 13\r\n"
            f"Sec-WebSocket-Key: {base64.b64encode(os.urandom(16)).decode()}\r\n"
            "Sec-WebSocket-Protocol: api.iterm2.com\r\nOrigin: ws://localhost/\r\n"
            "x-iterm2-library-version: python 2.26\r\nx-iterm2-advisory-name: aht\r\n"
            "x-iterm2-disable-auth-ui: true\r\n"
            f"x-iterm2-cookie: {cookie}\r\nx-iterm2-key: {key}\r\n\r\n").encode())
        rfile = sock.makefile("rb")
        status = rfile.readline().decode("latin-1").strip()
        while rfile.readline() not in (b"\r\n", b"\n", b""):
            pass
        if status.split(" ")[1:2] != ["101"]:
            raise RuntimeError(f"iTerm2's Python API said “{status or 'nothing'}”")
        _ws_send(sock, request)
        while True:
            answer = _pb_fields(_ws_recv(sock, rfile))
            if answer.get(1) == [1]:
                break
        try:
            _ws_send(sock, (1000).to_bytes(2, "big"), 8)    # goodbye
        except OSError:
            pass
        return answer
    finally:
        sock.close()

def tab_text(title: str) -> str:
    """A title as an iTerm2 tab shows it when aht sets it: iTerm2 keeps a
    backslash before a straight double quote, so those become curly ones."""
    out, opening = [], True
    for ch in title:
        out.append(("“" if opening else "”") if ch == '"' else ch)
        opening ^= ch == '"'
    return "".join(out)

def set_tab_title(tty: str, title: str) -> str:
    """Give the iTerm2 tab on `tty` a title, as Edit Tab Title does (as
    tab_text() writes it).  "" when done, else why not: "api-off"
    (iTerm2's Python API is switched off), "panes" (the tab holds more than
    one session, and its title would name them all), "no-tab", or what
    went wrong."""
    title = tab_text(title)
    if os.environ.get("AHT_ITERM_TABS") and not os.environ.get("AHT_ITERM_API"):
        if os.environ.get("AHT_ITERM_API_OFF"):         # tests: a stand-in
            return "api-off"
        try:
            tabs = json.loads(_live_tabs_file().read_text())
        except Exception:
            return "no-tab"
        if tty not in tabs:
            return "no-tab"
        if int(tabs[tty].get("panes") or 1) > 1:
            return "panes"
        tabs[tty].update(title=title, override=True)
        _live_tabs_file().write_text(json.dumps(tabs))
        return ""
    if not iterm_api_on():
        return "api-off"
    tab = iterm_tab(tty)
    if tab is None:
        return "iTerm2 did not answer"
    if not tab or not tab["id"]:
        return "no-tab"
    if tab["panes"] > 1:
        return "panes"
    # the title is a template: "\(…)" in it would be filled in, so a
    # backslash is doubled; then doubled again inside the call's quotes
    call = 'iterm2.set_title(title: "' + title.replace("\\", "\\\\\\\\") + '")'
    try:
        answer = iterm_api(_pb(1, 1) + _pb(132, _pb(7, _pb(1, tab["id"])) + _pb(5, call)
                                                 + _pb(6, -1.0)))
    except Exception as e:
        return str(e)[:200] or type(e).__name__
    if answer.get(2):
        return "iTerm2: " + answer[2][0].decode(errors="replace")[:200]
    res = _pb_fields((answer.get(132) or [b""])[0])
    if res.get(1):
        err = _pb_fields(res[1][0])
        return "iTerm2: " + ((err.get(2) or [b""])[0].decode(errors="replace")[:200]
                             or f"status {(err.get(1) or ['?'])[0]}")
    _note_tab_title(tty, title, True)
    log(f"TAB TITLE {tty} -> {title!r}")
    return ""

def _session_record(pid) -> dict:
    try:
        return json.loads((claude_home() / "sessions" / f"{pid}.json").read_text())
    except Exception:
        return {}

def _hook_ancestry():
    """(tty, pid of the Claude Code process) for the session a hook runs in:
    the hook itself has no terminal, the Claude process it came from has."""
    if os.environ.get("AHT_TTY"):                       # tests: a stand-in
        return os.environ["AHT_TTY"], int(os.environ.get("AHT_CLAUDE_PID") or 0) or None
    try:
        r = subprocess.run(["ps", "-Ao", "pid=,ppid=,tty="], capture_output=True,
                           text=True, timeout=10, cwd="/")
    except Exception:
        return None, None
    table = {}
    for line in r.stdout.splitlines():
        f = line.split()
        if len(f) >= 3 and f[0].isdigit() and f[1].isdigit():
            table[int(f[0])] = (int(f[1]), f[2])
    sessions = claude_home() / "sessions"
    pid, tty, cpid = os.getpid(), None, None
    for _ in range(30):
        if pid not in table:
            break
        ppid, t = table[pid]
        if cpid is None and (sessions / f"{pid}.json").is_file():
            cpid = pid
        if tty is None and t not in ("??", "-", ""):
            tty = "/dev/" + t
        if tty and cpid:
            break
        pid = ppid
    return tty, cpid

def _current_title(transcript, masked: bool = True) -> str:
    """The session's own title (what /rename, the Claude app or a hook set),
    from the end of its transcript; "" when it has none.  A key in it is
    masked, unless it is compared with the names the tabs gave
    (`masked=False`): those are the names as they are."""
    try:
        fh = open(transcript, "rb")
    except (OSError, TypeError):
        return ""
    with fh:                    # backwards, a piece at a time, up to 8 MB
        end = pos = fh.seek(0, 2)
        carry = b""
        while pos > 0 and end - pos < (8 << 20):
            start = max(0, pos - (256 << 10))
            fh.seek(start)
            lines = (fh.read(pos - start) + carry).split(b"\n")
            carry = lines.pop(0) if start > 0 else b""  # a line cut in two: next round
            for raw in reversed(lines):
                if b'"custom-title"' in raw:
                    try:
                        title = str(json.loads(raw).get("customTitle") or "")
                    except Exception:
                        continue
                    return redact(title) if masked else title
            pos = start
    return ""

def _transcript_of(cwd: str, sid: str):
    root = claude_backend().root()
    for c in dict.fromkeys((cwd, os.path.realpath(cwd))):
        f = root / _key_claude(c) / f"{sid}.jsonl"
        if f.is_file():
            return f
    return None

def _is_fork(transcript) -> bool:
    try:
        with open(transcript, "rb") as fh:
            return b'"forkedFrom"' in fh.read(1 << 20)
    except (OSError, TypeError):
        return False

def _load_tab_names() -> dict:
    try:
        return json.loads(tab_names_path().read_text())
    except Exception:
        return {}

def tab_session_name(data: dict, event: str):
    """The name this session should carry, from its iTerm2 tab's title — or
    None to leave its name alone.  The latest rename wins, on either side:
    rename the tab and the session follows; rename the session (/rename,
    /branch, the Claude app, aht's window) and its tab takes the name — when
    iTerm2's Python API is on, else the tab keeps its title and the session
    its name.  Both renamed since the last look: the tab wins.  A tab
    without a title leaves the session's name alone.  Another open session
    with that name makes it "<title> · 2" ("<title> ⑂ 2" for a branch)."""
    sid = str(data.get("session_id") or "")
    if not sid:
        return None
    state = _load_tab_names()
    entry = state.get(sid) or {}
    # the name as it is: it is compared with tab titles and set on the tab
    current = _current_title(data.get("transcript_path"), masked=False)
    tabs_on = bool(IS_MAC or os.environ.get("AHT_ITERM_TABS")) and cfg_get("tab_names", True)

    def remember(**now):
        # what this look found: the tab's title ("tab"), the session's name
        # ("name") and, right after aht renamed it, the name before ("was")
        if any(entry.get(k) != v for k, v in now.items()):
            state[sid] = dict(entry, at=time.time(), **now)
            for k in sorted(state, key=lambda k: (state[k] or {}).get("at") or 0)[:-500]:
                del state[k]
            _write_json(tab_names_path(), state)

    pend = entry.pop("pending", None) or {}
    if pend.get("name"):                        # asked for in aht's window
        name = str(pend["name"])
        tab = None
        if tabs_on:                             # its tab took it already, or not
            tty = _hook_ancestry()[0]
            tab = iterm_tab_title(tty) if tty else ""
        remember(names=((entry.get("names") or []) + [name])[-10:], name=name,
                 was=current, pinned=bool(pend.get("pin")),
                 **({} if tab is None else {"tab": " ".join(tab.split())[:80]}))
        log(f"TAB NAME {sid[:8]} -> {name!r} (asked for in aht)")
        return name if name != current else None
    if not tabs_on:
        return None
    tty, cpid = _hook_ancestry()
    if not tty:
        return None
    # this tab as it is now (a rename a moment ago counts); the last look at
    # all tabs only when iTerm2 does not answer
    live = iterm_tab_title(tty)
    if live is None:
        live = (iterm_tabs(max_age=10 ** 9).get(tty) or {}).get("title")
    if event != "SessionStart":                 # the look at all tabs, for the rest
        try:
            age = time.time() - tabs_cache_path().stat().st_mtime
        except OSError:
            age = 10 ** 9
        if age > TABS_FRESH and not os.environ.get("AHT_ITERM_TABS"):
            _spawn_aht(["tab-names", "--refresh", "--quiet"])
    base = " ".join(str(live or "").split())[:80]
    given = {n for e in state.values() for n in (e or {}).get("names") or []}
    known = entry.get("tab")
    moved = known is not None and known != base         # the tab renamed since
    renamed = (bool(current) and current not in given   # the session renamed since
               and entry.get("name") is not None
               and current not in (entry.get("name"), entry.get("was")))
    if renamed and not moved:                   # its new name is the latest: the tab takes it
        why = set_tab_title(tty, current) if tab_text(current) != base else ""
        if why:
            log(f"TAB NAME {sid[:8]}: its tab keeps its title ({why})")
        remember(tab=base if why else tab_text(current), name=current, was=None, pinned=False)
        return None
    if not base or entry.get("pinned") and not moved:
        remember(tab=base, name=current, was=None)
        return None                             # no title, or named in aht's window
    if current and current not in given and not moved:
        remember(tab=base, name=current, was=None)
        return None                             # a name someone chose: it stays
    taken = set()
    for s in running_sessions():
        if s.get("pid") == cpid or s.get("session") in (None, sid):
            continue
        t = _current_title(_transcript_of(s["cwd"], s["session"]), masked=False)
        if t:
            taken.add(t.casefold())
    name = base
    if base.casefold() in taken:
        mark = "⑂" if _is_fork(data.get("transcript_path")) else "·"
        n = 2
        while f"{base} {mark} {n}".casefold() in taken:
            n += 1
        name = f"{base} {mark} {n}"
    if name == current:
        remember(tab=base, name=current, was=None)
        return None
    remember(names=((entry.get("names") or []) + [name])[-10:], tab=base, name=name,
             was=current, pinned=False)
    log(f"TAB NAME {sid[:8]} -> {name!r}")
    return name

def _prompt_hook(data: dict) -> int:
    """UserPromptSubmit: rename the session when its tab's title changed.
    Prints JSON only when there is a name to set; nothing goes into the
    conversation."""
    try:
        name = tab_session_name(data, "UserPromptSubmit")
    except Exception as e:
        warn(f"HOOK tab name: {e}")
        return 0
    if name:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                                 "sessionTitle": name}}))
    return 0

def handover_session_name(sid, real: str, machine: str) -> str:
    """What a handed-over session is called on the other machine: the name
    aht gave it from its tab, with the machine's name, so the Claude app
    tells it apart from a session on this Mac."""
    state = _load_tab_names()
    entry = state.get(str(sid or "")) or {}
    names = entry.get("names") or []
    if not names:
        return os.path.basename(real)
    name = f"{entry.get('tab') or names[-1]} @ {machine}"
    if sid:                         # aht's name: renamed after the tab once it is back
        state[str(sid)] = dict(entry, names=(names + [name])[-10:], at=time.time())
        _write_json(tab_names_path(), state)
    return name

def _auto_title(transcript, masked: bool = True) -> str:
    """The title Claude Code gave the session itself (it shows when nobody
    named the session); masked like _current_title."""
    try:
        with open(transcript, "rb") as fh:
            end = fh.seek(0, 2)
            fh.seek(max(0, end - (1 << 20)))
            data = fh.read()
    except (OSError, TypeError):
        return ""
    for raw in reversed(data.split(b"\n")):
        if b'"ai-title"' in raw:
            try:
                title = str(json.loads(raw).get("aiTitle") or "")
            except Exception:
                continue
            return redact(title) if masked else title
    return ""

def _ttys() -> dict:
    """{pid: its terminal} for the processes that have one."""
    if os.environ.get("AHT_TTYS"):                      # tests: a stand-in
        return {int(k): v for k, v in json.loads(os.environ["AHT_TTYS"]).items()}
    out = {}
    try:
        r = subprocess.run(["ps", "-Ao", "pid=,tty="], capture_output=True, text=True,
                           timeout=10, cwd="/")
        for line in r.stdout.splitlines():
            f = line.split()
            if len(f) == 2 and f[0].isdigit() and f[1] not in ("??", "-"):
                out[int(f[0])] = "/dev/" + f[1]
    except Exception:
        pass
    return out

def session_names(fresh: bool = False, masked: bool = True) -> list:
    """The open Claude Code sessions here with their names: the name, where
    it came from ("tab", "aht" = set in aht's window, "yours" = /rename or the
    Claude app, "automatic" = Claude's own title), the tab's title and a
    name waiting for the session's next prompt.  A key in a name, a tab's
    title or a waiting name is masked, unless the names are compared with
    tab titles (`masked=False`)."""
    tabs = iterm_tabs(max_age=0 if fresh else 10 ** 9)
    ttys = _ttys()
    state = _load_tab_names()
    given = {n for e in state.values() for n in (e or {}).get("names") or []}
    rows = []
    for s in running_sessions():
        sid = s.get("session") or ""
        tr = _transcript_of(s["cwd"], sid) if sid else None
        custom, entry = _current_title(tr, masked=False), state.get(sid) or {}
        origin = ("aht" if entry.get("pinned") and custom else
                  "tab" if custom and custom in given else
                  "yours" if custom else "automatic")
        tab = (tabs.get(ttys.get(s["pid"], "")) or {}).get("title") or None
        pending = (entry.get("pending") or {}).get("name")
        if masked:
            custom, tab, pending = redact(custom), redact(tab), redact(pending)
        rec = _session_record(s["pid"])
        rows.append({"pid": s["pid"], "session": sid, "project": s["cwd"],
                     "tty": ttys.get(s["pid"]), "tab": tab,
                     "name": custom or _auto_title(tr, masked) or None, "origin": origin,
                     "pending": pending,
                     "fork": _is_fork(tr), "in_app": bool(rec.get("bridgeSessionId"))})
    return rows

def rename_session(sid: str, name: str, pin: bool = True, tab: bool = False) -> dict:
    """Give an open session a name.  Claude Code takes a new name from a hook
    only, so it is applied at the session's next prompt (typed here or in
    the Claude app).  With `tab`, its iTerm2 tab takes the name right away
    ("tab" in the answer: "" when it did, else why not).  An empty name
    hands the session back to its tab."""
    state = _load_tab_names()
    entry = dict(state.get(sid) or {})
    name = " ".join((name or "").split())[:80]
    if name:
        entry.update(pending={"name": name, "pin": pin}, at=time.time())
    else:
        entry.pop("pending", None)
        entry["pinned"] = False
    state[sid] = entry
    _write_json(tab_names_path(), state)
    log(f"TAB NAME {sid[:8]}: " + (f"{name!r} at the next prompt" if name else "follows its tab"))
    res = {"session": sid, "pending": name or None}
    if name and tab and cfg_get("tab_names", True):
        ttys = _ttys()
        tty = next((ttys.get(s["pid"]) for s in running_sessions()
                    if s.get("session") == sid and ttys.get(s["pid"])), None)
        res["tab"] = set_tab_title(tty, name) if tty else "no-tab"
    return res

def sync_all_plan(rows: list) -> list:
    """Every open session that has a tab title gets it, also the ones named
    some other way; a clash becomes "· 2" (a branch "⑂ 2").  A session
    without a tab keeps its name, unless it merely inherited a tab name that
    a session in that tab now carries."""
    def free(base, fork, taken):
        name, n, mark = base, 2, ("⑂" if fork else "·")
        while name.casefold() in taken:
            name, n = f"{base} {mark} {n}", n + 1
        return name
    kept = {str(r["name"]).casefold() for r in rows
            if not r.get("tab") and r.get("name") and r.get("origin") != "tab"}
    taken, plan, done = set(kept), [], set()
    for r in sorted(rows, key=lambda r: r["pid"]):
        base = " ".join(str(r.get("tab") or "").split())[:80]
        if not base or not r.get("session") or r["session"] in done:
            continue
        done.add(r["session"])
        name = free(base, r.get("fork"), taken)
        taken.add(name.casefold())
        if name != r.get("name") or r.get("origin") in ("aht", "yours") or r.get("pending"):
            plan.append({"session": r["session"], "project": r["project"],
                         "from": r.get("name"), "to": name,
                         "tab": " ".join(str(r.get("tab") or "").split())})
    for r in sorted(rows, key=lambda r: r["pid"]):
        if r.get("tab") or r.get("origin") != "tab" or r["session"] in done \
                or str(r.get("name") or "").casefold() not in taken:
            continue
        done.add(r["session"])
        name = free(str(r["name"]), r.get("fork"), taken)
        taken.add(name.casefold())
        plan.append({"session": r["session"], "project": r["project"],
                     "from": r.get("name"), "to": name})
    return plan

def _plan_shown(plan: list) -> list:
    """The sync plan as it is shown: its names masked, and a tab's title,
    which a name takes cut at 80, masked whole before that cut, so no part
    of a key the cut split shows."""
    out = []
    for x in plan:
        x = dict(x, **{k: redact(x[k]) for k in ("from", "to") if x[k]})
        full = x.pop("tab", "")
        if full and x["to"].startswith(redact(full[:80])) and redact(full) != full:
            x["to"] = _masked(full, 80) + x["to"][len(redact(full[:80])):]
        out.append(x)
    return out

def cmd_tab_names(args):
    if args.rename:
        res = rename_session(args.rename, args.to or "", tab=True)
        why = {"api-off": "its tab keeps its title: switch on iTerm2 → Settings → General → "
                          "Magic → Enable Python API to let it take the name too",
               "panes": "its tab keeps its title: it holds more than one session",
               "no-tab": "it is not in an iTerm2 tab"}
        if args.json:
            print(json.dumps(res))
        elif not res["pending"]:
            print("the session follows its tab again")
        else:
            print(f"named “{res['pending']}” at the session's next prompt; "
                  + ("its tab took the name now" if res.get("tab") == ""
                     else why.get(res.get("tab"), f"its tab kept its title ({res.get('tab')})")))
        return 0
    if args.sync_all:
        # planned with the names as they are (they are compared with tab
        # titles), shown with a key in one masked
        plan = sync_all_plan(session_names(fresh=True, masked=False))
        if args.apply:
            for x in plan:
                rename_session(x["session"], x["to"], pin=False)
        plan = _plan_shown(plan)
        if args.json:
            print(json.dumps({"plan": plan, "applied": bool(args.apply)}, indent=2))
            return 0
        if not plan:
            print("every session with a tab title already carries it")
        for x in plan:
            print(f"{x['from'] or '(no name)':<34} -> {x['to']}   {x['project']}")
        if plan:
            print("applied at each session's next prompt" if args.apply
                  else "(dry run — pass --apply; each takes the name at its next prompt)")
        return 0
    if args.refresh:
        tabs = iterm_tabs(max_age=0)
        try:
            save_workspace(workspace_snapshot(tabs))
        except Exception as e:
            warn(f"WORKSPACE not saved: {e}")
        if not args.quiet:
            print(f"{len(tabs)} iTerm2 session(s) seen")
        return 0
    rows = session_names(fresh=args.fresh)
    if args.json:
        print(json.dumps({"enabled": bool(cfg_get("tab_names", True)), "sessions": rows},
                         indent=2))
        return 0
    if not rows:
        print("no Claude Code session open")
    for r in rows:
        name = (r["name"] or "–") + (f"  → {r['pending']} (next prompt)" if r["pending"] else "")
        print(f"{r['tab'] or '(no tab title)':<22} {name:<34} {r['origin']:<10} "
              f"{'in the app' if r['in_app'] else 'not in the app':<15} {r['project']}")
    return 0

# ---- iTerm2: go to a session's tab, type into a tab, the whole workspace ------ #

def _as_text(s: str) -> str:
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'

_FIND_SESSION = """
on run argv
  set want to item 1 of argv
  set what to item 2 of argv
  set txt to ""
  if (count of argv) > 2 then set txt to item 3 of argv
  tell application "iTerm2"
    repeat with w in windows
      repeat with t in tabs of w
        repeat with s in sessions of t
          if tty of s is want then
            if what is "goto" then
              try
                set index of w to 1
              end try
              tell t to select
              tell s to select
              activate
            else
              tell s to write text txt
            end if
            return "ok"
          end if
        end repeat
      end repeat
    end repeat
  end tell
  return "none"
end run
"""

ITERM_REFUSED = ("macOS does not let aht control iTerm2 (System Settings → Privacy & "
                 "Security → Automation → aht → iTerm2)")

def _iterm_do(tty: str, what: str, text: str = "") -> str:
    """Do something with the iTerm2 session on `tty`: bring it to the front
    ("goto") or type a line into it ("write").  "ok", "none" (no such
    session in iTerm2), or "refused" (macOS does not let aht control it)."""
    if os.environ.get("AHT_ITERM_LOG"):                 # tests: note it, touch nothing
        with open(os.environ["AHT_ITERM_LOG"], "a") as fh:
            fh.write(json.dumps({"tty": tty, "what": what, "text": text}) + "\n")
        return os.environ.get("AHT_ITERM_ANSWER", "ok")
    if not IS_MAC or not _iterm_running():
        return "none"
    try:
        r = subprocess.run(["/usr/bin/osascript", "-", tty, what, text], input=_FIND_SESSION,
                           capture_output=True, text=True, timeout=20, cwd="/")
    except Exception:
        return "none"
    if "(-1743)" in r.stderr:                           # errAEEventNotPermitted
        return "refused"
    return "ok" if r.stdout.strip() == "ok" else "none"

def _iterm_session(tty: str, what: str, text: str = "") -> bool:
    return _iterm_do(tty, what, text) == "ok"

def _resolve_open(target: str):
    """An open Claude session by pid, session id or project folder."""
    rows = running_sessions()
    if str(target).isdigit():
        return next((s for s in rows if s["pid"] == int(target)), None)
    hit = [s for s in rows if s.get("session") == target]
    if hit:
        return hit[0]
    real = os.path.realpath(os.path.expanduser(str(target)))
    hit = sorted((s for s in rows if os.path.realpath(s["cwd"]) == real),
                 key=lambda s: -(s.get("since") or 0))
    return hit[0] if hit else None

def goto_session(target: str) -> dict:
    s = _resolve_open(target)
    if s is None:
        return {"ok": False, "why": "no open Claude Code session matches"}
    tty = _ttys().get(s["pid"])
    if not tty:
        return {"ok": False, "why": "it runs in the background, not in a terminal tab"}
    got = _iterm_do(tty, "goto")
    return {"ok": got == "ok", "tty": tty,
            "why": {"ok": None, "refused": ITERM_REFUSED}.get(got, "it is not in an iTerm2 tab")}

def cmd_goto(args):
    res = goto_session(args.target)
    if args.json:
        print(json.dumps(res))
    elif not res["ok"]:
        print(res["why"], file=sys.stderr)
    return 0 if res["ok"] else 1

# ---- sessions that need a look: duplicates, stuck ones, outside the app ----- #

KEEP_FLAGS = {"--dangerously-skip-permissions": 0, "--allow-dangerously-skip-permissions": 0,
              "--permission-mode": 1, "--model": 1, "--effort": 1, "--add-dir": 1,
              "--agent": 1, "--chrome": 0, "--no-chrome": 0, "--verbose": 0}

def _claude_flags(cmdline: str) -> list:
    """The options a session was started with that it keeps when it starts
    again (permissions, model, effort, extra folders); a first prompt and the
    session it resumed are left out."""
    try:
        parts = shlex.split(cmdline)
    except ValueError:
        parts = cmdline.split()
    out, i = [], 1
    while i < len(parts):
        key = parts[i].split("=", 1)[0]
        if key in KEEP_FLAGS:
            if "=" in parts[i] or KEEP_FLAGS[key] == 0:
                out.append(parts[i])
                i += 1
            else:
                out += parts[i:i + 2]
                i += 2
            continue
        i += 1
    return out

def _cmdline(pid: int) -> str:
    if os.environ.get("AHT_CMDLINES"):                  # tests: a stand-in
        return json.loads(os.environ["AHT_CMDLINES"]).get(str(pid), "")
    try:
        return subprocess.run(["ps", "-o", "args=", "-p", str(pid)], capture_output=True,
                              text=True, timeout=10, cwd="/").stdout.strip()
    except Exception:
        return ""

def _version(v) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", str(v or ""))[:3])

def installed_claude_version() -> str:
    """The Claude Code version a new session gets; asked once per binary."""
    if os.environ.get("AHT_CLAUDE_VERSION") is not None:          # tests
        return os.environ["AHT_CLAUDE_VERSION"]
    exe = find_claude()
    if not exe:
        return ""
    real = os.path.realpath(exe)
    cache = aht_home() / "run" / "claude-version.json"
    try:
        c = json.loads(cache.read_text())
        if c.get("exe") == real and c.get("mtime") == os.stat(real).st_mtime:
            return c.get("version") or ""
    except Exception:
        pass
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True,
                             timeout=20, cwd="/").stdout
        m = re.search(r"\d+\.\d+\.\d+", out)
        v = m.group(0) if m else ""
        _write_json(cache, {"exe": real, "mtime": os.stat(real).st_mtime, "version": v})
        return v
    except Exception:
        return ""

def claude_auto_continue() -> bool:
    """Claude Code's own autoContinueAtUsageLimit: a session that stopped at
    the usage limit goes on by itself when the limit resets."""
    try:
        return bool(json.loads((claude_home() / "settings.json").read_text())
                    .get("autoContinueAtUsageLimit"))
    except Exception:
        return False

def session_checkup() -> list:
    """Open Claude Code sessions worth a look, each with what is the matter:
    "twice" (one conversation open in two processes), "stuck" (working for
    hours, nothing written since), "outside the app" (started before Remote
    Control was on), "older" (runs an older Claude Code than installed)."""
    now = time.time()
    rows = running_sessions()
    count = {}
    for s in rows:
        if s.get("session"):
            count[s["session"]] = count.get(s["session"], 0) + 1
    ttys = _ttys()
    tabs = iterm_tabs(max_age=10 ** 9)
    rc = claude_remote_control()
    have = installed_claude_version()
    out = []
    for s in rows:
        rec = _session_record(s["pid"])
        tr = _transcript_of(s["cwd"], s["session"]) if s.get("session") else None
        st = _stat(tr) if tr else None
        issues = []
        if count.get(s.get("session"), 0) > 1:
            issues.append("twice")
        if s.get("status") in ("busy", "shell") and s.get("since") and now - s["since"] > 3 * 3600 \
                and (st is None or now - st.st_mtime > 3 * 3600):
            issues.append("stuck")
        if rc and not rec.get("bridgeSessionId") and rec.get("kind", "interactive") == "interactive":
            issues.append("outside the app")
        if have and rec.get("version") and _version(rec["version"]) < _version(have):
            issues.append("older")
        tty = ttys.get(s["pid"])
        out.append({"pid": s["pid"], "session": s.get("session"), "project": s["cwd"],
                    "status": s.get("status"), "since": s.get("since"),
                    "name": _current_title(tr) or _auto_title(tr) or None,
                    "version": rec.get("version"), "installed": have or None,
                    "tty": tty, "tab": redact((tabs.get(tty or "") or {}).get("title") or None),
                    "in_iterm": bool(tty and tty in tabs), "in_app": bool(rec.get("bridgeSessionId")),
                    "background": not tty, "issues": issues,
                    "can_restart": bool(tty and tty in tabs and s.get("session")
                                        and (s.get("status") == "idle" or "stuck" in issues))})
    return out

def _gone(pid: int) -> bool:
    if not _pid_alive(pid):
        return True
    try:                                # ended, but not yet collected by its parent
        st = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True,
                            text=True, timeout=5, cwd="/").stdout.strip()
        return st.startswith("Z") or not st
    except Exception:
        return False

def _wait_gone(pid: int, secs: float) -> bool:
    end = time.time() + secs
    while time.time() < end:
        if _gone(pid):
            return True
        time.sleep(0.2)
    return _gone(pid)

def close_session(pid: int, apply: bool = False) -> dict:
    """End one Claude Code process (SIGTERM: it exits the way it does on
    /exit; its conversation stays and can be resumed)."""
    s = next((x for x in running_sessions() if x["pid"] == int(pid)), None)
    res = {"pid": int(pid), "applied": False, "blockers": []}
    if s is None:
        res["blockers"].append("no open Claude Code session has that process")
        return res
    res.update(session=s.get("session"), project=s["cwd"],
               resume=f"cd {shlex.quote(s['cwd'])} && claude --resume {s.get('session')}")
    if not apply:
        return res
    import signal
    try:
        os.kill(int(pid), signal.SIGTERM)
    except OSError as e:
        res["blockers"].append(str(e))
        return res
    res["applied"] = _wait_gone(int(pid), 15)
    if not res["applied"]:
        res["blockers"].append("it did not end within 15 seconds")
    log(f"SESSION closed pid {pid} ({s['cwd']}): {res['applied']}")
    return res

def restart_session(pid: int, apply: bool = False) -> dict:
    """End an idle (or stuck) session and start it again in the same iTerm2
    tab, with the options it had: it then runs the installed Claude Code and,
    with Remote Control on for every session, appears in the Claude app."""
    pid = int(pid)
    row = next((r for r in session_checkup() if r["pid"] == pid), None)
    res = {"pid": pid, "applied": False, "blockers": []}
    if row is None:
        res["blockers"].append("no open Claude Code session has that process")
        return res
    if not row["in_iterm"]:
        res["blockers"].append("it is not in an iTerm2 tab, so aht cannot start it there again")
    elif not row["can_restart"]:
        res["blockers"].append("it is working or waiting for you; restart it once it is idle")
    flags = _claude_flags(_cmdline(pid))
    env = "CLAUDE_CODE_DISABLE_TERMINAL_TITLE=1 " if row.get("tab") and not \
        (iterm_tabs(max_age=10 ** 9).get(row["tty"]) or {}).get("override") else ""
    cmd = (f"cd {shlex.quote(row['project'])} && {env}claude "
           + " ".join(shlex.quote(f) for f in flags + ["--resume", row["session"] or ""]))
    res.update(session=row["session"], project=row["project"], tab=row.get("tab"),
               command=cmd, issues=row["issues"])
    if not apply or res["blockers"]:
        return res
    done = close_session(pid, apply=True)
    if not done["applied"]:
        res["blockers"] += done["blockers"]
        return res
    time.sleep(0.5)                     # the shell gets its prompt back
    res["applied"] = _iterm_session(row["tty"], "write", cmd)
    if not res["applied"]:
        res["blockers"].append("the session ended, but its tab is gone; continue it with: "
                               + cmd)
    log(f"SESSION restarted pid {pid} in {row['tty']}: {cmd}")
    return res

def cmd_sessions_checkup(args):
    if args.close:
        res = close_session(args.close, args.apply)
        lines = [("closed" if res["applied"] else "would close") +
                 f": pid {res['pid']} {res.get('project') or ''}"]
        if res.get("resume") and not res["blockers"]:
            lines.append(f"   continue it later with: {res['resume']}")
        if not args.apply and not res["blockers"]:
            lines.append("(dry run — pass --apply to do it)")
        return _emit(args, res, lines)
    if args.restart:
        res = restart_session(args.restart, args.apply)
        lines = [("restarted" if res["applied"] else "would restart") +
                 f": pid {res['pid']} {res.get('project') or ''}"]
        if res.get("command"):
            lines.append(f"   in its tab: {res['command']}")
        if not args.apply and not res["blockers"]:
            lines.append("(dry run — pass --apply to do it)")
        return _emit(args, res, lines)
    rows = session_checkup()
    if args.json:
        print(json.dumps({"sessions": rows, "auto_continue": claude_auto_continue()}, indent=2))
        return 0
    words = {"twice": "open twice", "stuck": "working for hours, nothing written",
             "outside the app": "not in the Claude app", "older": "older Claude Code"}
    shown = [r for r in rows if r["issues"]]
    if not shown:
        print("every open Claude Code session looks fine")
    for r in shown:
        print(f"pid {r['pid']:<7} {(r['name'] or '–')[:40]:<42} {r['project']}")
        print("        " + ", ".join(words[i] for i in r["issues"])
              + (f"   (runs {r['version']}, {r['installed']} installed)" if "older" in r["issues"] else "")
              + ("   — can restart in its tab" if r["can_restart"] else ""))
    return 0

# ---- the workspace: iTerm2's windows, tabs and the sessions in them --------- #

_SHELLS = {"zsh", "bash", "fish", "sh", "dash", "ksh", "tcsh", "csh"}

def workspaces_dir() -> Path:
    return aht_home() / "workspaces"

def _tty_processes() -> dict:
    """{tty: [(pid, command line)]} for the processes that have a terminal."""
    if os.environ.get("AHT_TTY_PROCS"):                 # tests: a stand-in
        return {k: [tuple(x) for x in v] for k, v in json.loads(os.environ["AHT_TTY_PROCS"]).items()}
    out = {}
    try:
        r = subprocess.run(["ps", "-Ao", "pid=,tty=,args="], capture_output=True, text=True,
                           timeout=15, cwd="/")
    except Exception:
        return out
    for line in r.stdout.splitlines():
        f = line.split(None, 2)
        if len(f) == 3 and f[0].isdigit() and f[1] not in ("??", "-"):
            out.setdefault("/dev/" + f[1], []).append((int(f[0]), f[2]))
    return out

def _cwds(pids) -> dict:
    pids = [int(p) for p in pids]
    if not pids:
        return {}
    if os.environ.get("AHT_CWDS"):                      # tests: a stand-in
        return {int(k): v for k, v in json.loads(os.environ["AHT_CWDS"]).items()}
    out = {}
    if IS_LINUX:
        for p in pids:
            try:
                out[p] = os.readlink(f"/proc/{p}/cwd")
            except OSError:
                pass
        return out
    lsof = next((c for c in ("/usr/sbin/lsof", "/usr/bin/lsof") if os.path.exists(c)), "lsof")
    try:
        r = subprocess.run([lsof, "-a", "-p", ",".join(map(str, pids)), "-d", "cwd", "-Fpn"],
                           capture_output=True, text=True, timeout=30, cwd="/")
        pid = None
        for line in r.stdout.splitlines():
            if line.startswith("p"):
                pid = int(line[1:])
            elif line.startswith("n") and pid:
                out[pid] = line[1:]
    except Exception:
        pass
    return out

def _iterm_state_path() -> Path:
    return Path(os.environ.get("AHT_ITERM_STATE") or Path.home() / "Library" /
                "Application Support" / "iTerm2" / "SavedState" / "restorable-state.sqlite")

def _keyed_archive(blob: bytes):
    """The top object of an NSKeyedArchiver plist, with lazy look-ups: a
    dict's values are read only when asked for (a saved iTerm2 session also
    holds its screen contents, which aht never reads)."""
    import plistlib
    pl = plistlib.loads(blob)
    objs = pl["$objects"]
    def val(x, depth=0):
        if isinstance(x, plistlib.UID):
            x = objs[x.data]
        if depth > 40:
            return None
        if isinstance(x, dict):
            if "NS.keys" in x:
                return {str(val(k, depth + 1)): v for k, v in zip(x["NS.keys"], x["NS.objects"])}
            if "NS.objects" in x:
                return [val(v, depth + 1) for v in x["NS.objects"]]
            if "NS.string" in x:
                return x["NS.string"]
            return None
        return None if x == "$null" else x
    def deep(x, depth=0):
        v = val(x, depth)
        if isinstance(v, dict):
            return {k: deep(w, depth + 1) for k, w in v.items()}
        return v
    top = pl["$top"]
    return val(top.get("root", next(iter(top.values()), None))), deep

def _dark_mode() -> bool:
    try:
        r = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"],
                           capture_output=True, text=True, timeout=5, cwd="/")
        return r.stdout.strip().lower() == "dark"
    except Exception:
        return False

def _tab_color(bookmark: dict, dark: bool):
    """"#rrggbb" for the tab colour a session's profile sets, or None."""
    mode, other = (" (Dark)", " (Light)") if dark else (" (Light)", " (Dark)")
    # separate light and dark colours: this mode's first; then any colour set
    order = ((mode, "", other) if bookmark.get("Use Separate Colors for Light and Dark Mode")
             else ("", mode, other))
    for sfx in order:
        c = bookmark.get("Tab Color" + sfx)
        if bookmark.get("Use Tab Color" + sfx) and isinstance(c, dict):
            try:
                return "#" + "".join(f"{round(max(0.0, min(1.0, float(c[k + ' Component']))) * 255):02x}"
                                     for k in ("Red", "Green", "Blue"))
            except (KeyError, TypeError, ValueError):
                continue
    return None

def iterm_tab_colors() -> dict:
    """{tty: "#rrggbb"} for the iTerm2 tabs that have a colour.  A script cannot
    ask iTerm2 for it, so it comes from iTerm2's saved window state (which
    iTerm2 writes every few minutes).  Any surprise in that file means no
    colours, never an error."""
    if os.environ.get("AHT_ITERM_TABS") and not os.environ.get("AHT_ITERM_STATE"):
        return {}                                       # tests: never the real one
    if not IS_MAC and not os.environ.get("AHT_ITERM_STATE"):
        return {}
    path = _iterm_state_path()
    if not path.is_file():
        return {}
    try:
        import sqlite3
        from urllib.parse import quote
        db = sqlite3.connect(f"file:{quote(str(path))}?mode=ro", uri=True, timeout=3)
        try:
            rows = db.execute("SELECT data FROM Node WHERE key = 'Session' ORDER BY rowid").fetchall()
        finally:
            db.close()
    except Exception as e:
        warn(f"TABS iTerm2's saved state: {e}")
        return {}
    dark, out = _dark_mode(), {}
    for (blob,) in rows:
        if not blob or b"Tab Color" not in blob:
            continue
        try:
            o, deep = _keyed_archive(blob)
            tty = deep(o.get("TTY"))
            color = _tab_color(deep(o.get("Bookmark")) or {}, dark)
        except Exception:
            continue
        if isinstance(tty, str) and tty.startswith("/dev/"):
            if color:
                out[tty] = color
            else:
                out.pop(tty, None)
    return out

def workspace_snapshot(tabs: dict = None) -> dict:
    """Every iTerm2 window, tab and pane: its title, its folder, and the agent
    session that runs in it (with the options it was started with)."""
    tabs = iterm_tabs() if tabs is None else tabs
    colors = iterm_tab_colors() if tabs else {}
    procs = _tty_processes()
    sessions = {s["pid"]: s for s in running_sessions()}
    rows, want = [], {}
    for tty, t in tabs.items():
        here = procs.get(tty, [])
        e = {"window": int(t.get("window") or 1), "tab": int(t.get("tab") or 1),
             "pane": int(t.get("pane") or 1), "title": t.get("title") or "",
             "profile": t.get("profile") or None, "color": colors.get(tty) or t.get("color"),
             "cwd": None, "agent": None, "session": None, "args": [], "name": None}
        cl = next(((pid, a) for pid, a in here if pid in sessions), None)
        other = next(((pid, m.group(1)) for pid, a in here
                      for m in [_AGENT_PROC.search(" ".join(a.split()[:2]))] if m), None)
        shell = min((pid for pid, a in here if a.split() and
                     os.path.basename(a.split()[0]).lstrip("-") in _SHELLS), default=None)
        if cl:
            s = sessions[cl[0]]
            tr = _transcript_of(s["cwd"], s["session"]) if s.get("session") else None
            e.update(agent="claude", session=s.get("session"), cwd=s["cwd"],
                     args=_claude_flags(cl[1]),
                     name=_current_title(tr) or _auto_title(tr) or None)
        elif other:
            e["agent"] = other[1]
            want[other[0]] = e
        elif shell:
            want[shell] = e
        rows.append(e)
    for pid, cwd in _cwds(list(want)).items():
        if pid in want:
            want[pid]["cwd"] = cwd
    rows.sort(key=lambda e: (e["window"], e["tab"], e["pane"]))
    return {"at": time.time(), "seen": time.time(), "host": _here(), "tabs": rows}

def _ws_key(w: dict) -> str:
    return json.dumps([{k: e.get(k) for k in ("window", "tab", "pane", "title", "cwd", "agent",
                                              "session", "profile", "color")}
                       for e in w.get("tabs", [])],
                      sort_keys=True)

def _ws_files(d: Path) -> list:
    """The saved layouts, oldest first ("…-1" is a second one in the same second)."""
    def key(f):
        stamp, _, n = f.stem.partition("-")[2].partition("-")
        return (f.stem.split("-")[0], stamp, int(n) if n.isdigit() else 0)
    return sorted(d.glob("*.json"), key=key) if d.is_dir() else []

def save_workspace(snap: dict):
    """Keep the snapshot when the layout changed; a layout seen again only
    gets its "seen" time renewed.  The last `workspace_keep` layouts are kept."""
    if not snap.get("tabs"):
        return None
    d = workspaces_dir()
    d.mkdir(parents=True, exist_ok=True)
    files = _ws_files(d)
    if files:
        try:
            last = json.loads(files[-1].read_text())
            if _ws_key(last) == _ws_key(snap):
                last["seen"] = snap["seen"]
                _write_json(files[-1], last)
                return files[-1]
        except Exception:
            pass
    f = d / f"{_stamp()}.json"
    if f.exists():
        f = d / f"{_stamp()}-{len(files)}.json"
    _write_json(f, snap)
    keep = max(1, int(cfg_get("workspace_keep", 40)))
    for old in _ws_files(d)[:-keep]:
        old.unlink()
    return f

def workspace_autosave_path() -> Path:
    return aht_home() / "run" / "workspace-autosave"

def autosave_workspace() -> dict:
    """The app calls this every minute; it saves when `workspace_save_minutes`
    have passed since the last time, iTerm2 is open, and that is switched on."""
    every = int(cfg_get("workspace_save_minutes", 10) or 0)
    if every <= 0:
        return {"saved": None, "skipped": "off"}
    if not os.environ.get("AHT_ITERM_TABS") and not (IS_MAC and _iterm_running()):
        return {"saved": None, "skipped": "iTerm2 is not open"}
    stamp = workspace_autosave_path()
    try:
        ago = time.time() - stamp.stat().st_mtime
    except OSError:
        ago = None
    if ago is not None and ago < every * 60 - 5:
        return {"saved": None, "skipped": f"saved {int(ago)} s ago"}
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.touch()
    f = save_workspace(workspace_snapshot(iterm_tabs(max_age=0)))
    return {"saved": str(f) if f else None}

def iterm_started():
    """When the running iTerm2 started (seconds since 1970), or None."""
    try:
        r = subprocess.run(["ps", "-Ac", "-o", "lstart=,comm="], capture_output=True,
                           text=True, timeout=10, cwd="/")
        for line in r.stdout.splitlines():
            if line.strip().endswith(" iTerm2"):
                return time.mktime(time.strptime(" ".join(line.split()[:5]),
                                                 "%a %b %d %H:%M:%S %Y"))
    except Exception:
        pass
    return None

def list_workspaces() -> list:
    rows = []
    for f in reversed(_ws_files(workspaces_dir())):
        try:
            w = json.loads(f.read_text())
        except Exception:
            continue
        rows.append({"id": f.stem, "at": w.get("at"), "seen": w.get("seen") or w.get("at"),
                     "windows": len({e["window"] for e in w["tabs"]}),
                     "tabs": len({(e["window"], e["tab"]) for e in w["tabs"]}),
                     "sessions": sum(1 for e in w["tabs"] if e.get("agent")),
                     "titles": [e["title"] for e in w["tabs"] if e.get("title")]})
    return rows

def default_workspace(rows: list):
    """The layout to offer: the last one seen before iTerm2 last started
    (what a restart or an update closed), else the newest."""
    start = None if os.environ.get("AHT_ITERM_TABS") else iterm_started()
    before = [r for r in rows if start and (r["seen"] or 0) < start - 5]
    return (before or rows or [None])[0]

def workspace_opened_path() -> Path:
    return aht_home() / "run" / "workspace-opened.json"

OPENED_FRESH = 180      # seconds a tab aht just opened counts as open

def _just_opened() -> dict:
    try:
        o = json.loads(workspace_opened_path().read_text())
        if time.time() - float(o.get("at") or 0) < OPENED_FRESH:
            return o
    except Exception:
        pass
    return {}

def restore_plan(w: dict, tabs: dict = None) -> dict:
    """What a restore opens: every agent session that is not open now, and
    every titled tab that is not there now; the rest is skipped.  What a
    restore opened a moment ago counts as open (a session takes a few
    seconds to start)."""
    if tabs is None:
        running = os.environ.get("AHT_ITERM_TABS") or not IS_MAC or _iterm_running()
        tabs = iterm_tabs() if running else {}
    opened = _just_opened()
    open_ids = {s.get("session") for s in running_sessions()} | set(opened.get("sessions") or [])
    titles_now = ({str(t.get("title") or "") for t in tabs.values()}
                  | set(opened.get("titles") or [])) - {""}
    windows, skipped = {}, []
    for e in w.get("tabs", []):
        why = None
        if e.get("agent") == "claude" and e.get("session") in open_ids:
            why = "its session is open"
        elif not e.get("agent") and not e.get("title"):
            why = "a plain tab without a title"
        elif not e.get("agent") and e["title"] in titles_now:
            why = "a tab with that title is open"
        elif e.get("cwd") and not os.path.isdir(e["cwd"]):
            why = "its folder is gone"
        if why:
            skipped.append(dict(e, why=why))
            continue
        windows.setdefault(e["window"], {}).setdefault(e["tab"], []).append(e)
    plan = [[panes for _t, panes in sorted(tabs.items())] for _w, tabs in sorted(windows.items())]
    return {"windows": plan, "skipped": skipped,
            "opens": sum(len(p) for win in plan for p in win)}

def _restore_command(e: dict) -> str:
    steps = []
    m = re.fullmatch(r"#([0-9a-fA-F]{2})([0-9a-fA-F]{2})([0-9a-fA-F]{2})", str(e.get("color") or ""))
    if m:                       # iTerm2's own escape code for a tab's colour
        steps.append("printf '" + "".join(f"\\033]6;1;bg;{c};brightness;{int(h, 16)}\\007"
                                          for c, h in zip(("red", "green", "blue"), m.groups()))
                     + "'")
    if e.get("title"):
        steps.append("printf '\\033]1;%s\\007' " + shlex.quote(e["title"]))
    run = []
    if e.get("cwd"):
        run.append("cd " + shlex.quote(e["cwd"]))
    if e.get("agent") == "claude" and e.get("session"):
        env = "CLAUDE_CODE_DISABLE_TERMINAL_TITLE=1 " if e.get("title") else ""
        run.append(env + "claude " + " ".join(shlex.quote(a) for a in
                                              list(e.get("args") or []) + ["--resume", e["session"]]))
    elif e.get("agent") == "kimi":
        run.append("kimi -c")
    if run:
        steps.append(" && ".join(run))
    if steps and len(run) <= 1:         # a plain tab: a clean screen, not these lines
        steps.append("clear")
    return "; ".join(steps) or "true"

def _with_profile(statement: str, profile) -> list:
    """An AppleScript line that opens a window, tab or pane with the profile
    the tab had; the default profile when that one is gone."""
    plain = statement.format("default profile")
    if not profile:
        return [plain]
    var = statement.split(" to (")[0].split()[-1]
    return ["try", "  " + statement.format("profile " + _as_text(profile)),
            "on error", "  " + plain, "end try",
            f"if {var} is missing value then", "  " + plain, "end if"]

def _start_iterm() -> str:
    """Start iTerm2 and wait until it answers a script; "" when it does,
    else what went wrong."""
    r = subprocess.run(["/usr/bin/open", "-b", "com.googlecode.iterm2"], capture_output=True,
                       text=True, timeout=30, cwd="/")
    if r.returncode != 0:
        return "iTerm2 did not start: " + (r.stderr or "").strip()[-200:]
    count, steady, deadline = None, 0, time.time() + 40
    while time.time() < deadline:
        q = subprocess.run(["/usr/bin/osascript", "-e", 'tell application "iTerm2" to count windows'],
                           capture_output=True, text=True, timeout=20, cwd="/")
        n = q.stdout.strip() if q.returncode == 0 else None
        # ready once it answers, and its own windows (restored ones too) are
        # all there: the same count three times in a row
        steady = steady + 1 if n is not None and n == count else 0
        count = n
        if steady >= 3:
            return ""
        time.sleep(0.5)
    return "iTerm2 started but did not answer in time; try again in a moment"

def restore_workspace(wid: str = None, apply: bool = False) -> dict:
    rows = list_workspaces()
    pick = next((r for r in rows if r["id"] == wid), None) if wid else default_workspace(rows)
    res = {"applied": False, "blockers": [], "workspace": pick}
    if pick is None:
        res["blockers"].append("no saved workspace yet (aht saves one while you work in "
                               "iTerm2 with Claude Code)")
        return res
    w = json.loads((workspaces_dir() / f"{pick['id']}.json").read_text())
    plan = restore_plan(w)
    res.update(plan=plan)
    if not plan["opens"]:
        res["blockers"].append("everything in it is open already")
    if not apply or res["blockers"]:
        return res
    (aht_home() / "run").mkdir(parents=True, exist_ok=True)
    lock = open(aht_home() / "run" / "workspace-restore.lock", "a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        res["blockers"].append("a restore is opening tabs right now")
        return res
    try:
        return _restore_now(res, pick, w)
    finally:
        lock.close()

def _restore_now(res: dict, pick: dict, w: dict) -> dict:
    testing = bool(os.environ.get("AHT_ITERM_LOG"))
    started = bool(os.environ.get("AHT_ITERM_STARTED")) if testing else False
    if not testing and not _iterm_running():
        why = _start_iterm()
        if why:
            res["blockers"].append(why)
            return res
        started = True
    # a fresh look: what iTerm2 brought back itself when it started is not
    # opened twice, and a double click finds the first restore's tabs
    tabs = iterm_tabs(max_age=0)
    plan = restore_plan(w, tabs)
    res["plan"] = plan
    if not plan["opens"]:
        res["blockers"].append("everything in it is open already")
        return res
    # the empty window iTerm2 opens when it starts takes the first tab
    reuse = started and len(tabs) == 1 and not next(iter(tabs.values())).get("title") and \
        all(os.path.basename(a.split()[0]).lstrip("-") in _SHELLS | {"login"}
            for _pid, a in _tty_processes().get(next(iter(tabs)), []) if a.split())
    _write_json(workspace_opened_path(), {
        "at": time.time(), "workspace": pick["id"],
        "sessions": [e["session"] for win in plan["windows"] for panes in win for e in panes
                     if e.get("session")],
        "titles": [e["title"] for win in plan["windows"] for panes in win for e in panes
                   if e.get("title")]})
    L = ['tell application "iTerm2"', "activate"]
    first = True
    for win in plan["windows"]:
        for ti, panes in enumerate(win):
            if ti == 0 and first and reuse:
                L += ["set w to current window", "set s to current session of w"]
            elif ti == 0:
                L += _with_profile("set w to (create window with {})", panes[0].get("profile"))
                L += ["set s to current session of w"]
            else:
                L += _with_profile("tell w to set t to (create tab with {})", panes[0].get("profile"))
                L += ["set s to current session of t"]
            first = False
            for pi, e in enumerate(panes):
                if pi:
                    L += _with_profile("tell s to set s2 to (split vertically with {})",
                                       e.get("profile"))
                    L += ["set s to s2"]
                L.append("delay 0.3")
                if e.get("title"):
                    L.append(f'tell s to set variable named "user.ahtTitle" to {_as_text(e["title"])}')
                L.append(f"tell s to write text {_as_text(_restore_command(e))}")
    L.append("end tell")
    if testing:                                         # tests: note it, open nothing
        with open(os.environ["AHT_ITERM_LOG"], "a") as fh:
            fh.write(json.dumps({"what": "restore", "script": "\n".join(L)}) + "\n")
        res["applied"] = True
        return res
    r = subprocess.run(["/usr/bin/osascript", "-"], input="\n".join(L), capture_output=True,
                       text=True, timeout=120, cwd="/")
    res["applied"] = r.returncode == 0
    if r.returncode != 0:
        res["blockers"].append("iTerm2 said: " + (r.stderr or "").strip()[-300:])
        warn(f"WORKSPACE not restored {pick['id']}: {(r.stderr or '').strip()[-300:]}")
        try:
            workspace_opened_path().unlink()
        except OSError:
            pass
    else:
        log(f"WORKSPACE restored {pick['id']}: {plan['opens']} tab(s)/pane(s)"
            + (", iTerm2 started first" if started else ""))
    return res

def cmd_workspace(args):
    if args.save and args.auto:
        res = autosave_workspace()
        if args.json:
            print(json.dumps(res))
        elif not args.quiet:
            print(f"saved: {res['saved']}" if res.get("saved") else
                  f"not saved: {res.get('skipped') or 'nothing to save'}")
        return 0
    if args.save:
        f = save_workspace(workspace_snapshot(iterm_tabs(max_age=0)))
        print(json.dumps({"saved": str(f) if f else None}) if args.json else
              (f"saved: {f}" if f else "nothing to save (is iTerm2 running?)"))
        return 0
    if args.restore is not None:
        res = restore_workspace(args.restore or None, args.apply)
        lines = []
        pk = res.get("workspace")
        if pk:
            lines.append(f"workspace {pk['id']}: {pk['tabs']} tab(s) in {pk['windows']} "
                         f"window(s), {pk['sessions']} session(s)")
        for win in (res.get("plan") or {}).get("windows", []):
            for panes in win:
                for e in panes:
                    lines.append(f"   open  {e.get('title') or '(no title)':<22} "
                                 f"{e.get('name') or e.get('agent') or ''}  {e.get('cwd') or ''}")
        for e in (res.get("plan") or {}).get("skipped", []):
            lines.append(f"   skip  {e.get('title') or '(no title)':<22} {e['why']}")
        if not args.apply and not res["blockers"]:
            lines.append("(dry run — pass --apply to open them)")
        return _emit(args, res, lines)
    rows = list_workspaces()
    if args.json:
        print(json.dumps({"workspaces": rows,
                          "default": (default_workspace(rows) or {}).get("id")}, indent=2))
        return 0
    if not rows:
        print("no saved workspace yet")
    for r in rows:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(r["seen"] or 0))
        print(f"{r['id']}  last seen {when}: {r['tabs']} tab(s), {r['sessions']} session(s)  "
              + ", ".join(r["titles"][:8]))
    return 0

# ---- getting started: what lets aht do more on this computer ---------------- #

def tray_starts_at_login() -> bool:
    """The menu bar app starts at login (the LaunchAgent the app writes)."""
    d = os.environ.get("AHT_LAUNCH_AGENTS") or Path.home() / "Library" / "LaunchAgents"
    return (Path(d) / "com.aht.tray.plist").is_file()

def _linux_tray_autostart() -> Path:
    d = os.environ.get("AHT_AUTOSTART_DIR") or Path.home() / ".config" / "autostart"
    return Path(d) / "aht-tray.desktop"

def desktop_arg(s) -> str:
    """One argument of a Desktop Entry's Exec= line, in double quotes.  The
    spec's quoting rule comes first (\\ " ` and $ get a backslash), then the
    string escapes that a reader undoes before it (every backslash doubled,
    a newline, tab or carriage return written \\n, \\t, \\r), so a $ in a path
    is written \\\\$; and a % is written %%, since a lone % starts a field
    code.  linux/tray.py and linux/install.py write the same."""
    s = re.sub(r'([\\"`$])', r'\\\1', str(s))      # the Exec quoting rule: \ " ` $ get a backslash
    s = s.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t").replace("\r", "\\r")   # the string-value escapes
    return '"' + s.replace("%", "%%") + '"'                 # %% for a literal %

def exec_python(py) -> str:
    """The Python an Exec= line starts.  GLib looks for the program before it
    turns %% into %, so one whose path has a % never starts: then the same
    Python by a path without one, its real path or else python3 on PATH;
    failing both, the path as it is.  linux/tray.py and linux/install.py
    pick the same."""
    py = str(py)
    if "%" in py:
        for other in (os.path.realpath(py), shutil.which("python3")):
            if other and "%" not in other:
                return other
    return py

def _autostart_answer_path() -> Path:
    """There once the tray-at-login question was answered (`aht autostart
    on|off`: the Windows installer, the window, a tray's switch), so the
    welcome keeps that answer instead of asking again."""
    return aht_home() / "run" / "autostart.json"

def note_autostart_answer(on: bool) -> None:
    """Record that the user chose whether the tray starts at login."""
    try:
        _write_json(_autostart_answer_path(), {"at": time.time(), "on": bool(on)})
    except OSError as e:
        warn(f"AUTOSTART answer not kept: {e}")

def tray_autostart(on: bool = None) -> dict:
    """Whether aht's tray starts at login; with `on`, make it so (and keep
    that the question was answered: "answered").  Windows: the HKCU Run
    entry, which starts either the tray (it keeps the watcher running) or
    the hidden watcher alone.  Linux: an XDG autostart entry, as the tray
    writes it.  A Mac: the app writes its own LaunchAgent.  The answer is
    kept only when the tray now does what was asked: a terminal's `on` on
    a Mac, where the app has the switch, changes nothing and is no answer."""
    res = _tray_autostart(on)
    if on is not None and res["on"] == bool(on):
        note_autostart_answer(res["on"])
    res["answered"] = _autostart_answer_path().is_file()
    return res

def _tray_autostart(on: bool = None) -> dict:
    if IS_MAC and not os.environ.get("AHT_AUTOSTART_DIR"):
        return {"supported": False, "on": tray_starts_at_login()}
    if os.name == "nt":
        try:
            import winlayer
        except ImportError:
            return {"supported": False, "on": False}
        tray = Path(sys.executable).with_name("aht-tray.exe")
        have = getattr(sys, "frozen", False) and tray.is_file()
        is_on = winlayer.is_tray_entry(winlayer._run_key_get())
        if on is not None and on != is_on and (have or not on):
            if on:
                winlayer._run_key_set(f'"{tray}"')
            else:
                import contextlib, io
                with contextlib.redirect_stdout(io.StringIO()):
                    winlayer._write_autostart(winlayer.self_cmd()[0] if have else "")
            is_on = bool(on)
        return {"supported": bool(have or is_on), "on": is_on}
    f = _linux_tray_autostart()
    # installed, the tray sits next to aht.py; in a checkout, in linux/
    here = Path(__file__).resolve().parent
    tray = next((t for t in (here / "tray.py", here / "linux" / "tray.py") if t.is_file()),
                here / "tray.py")
    if on:
        # the Desktop Entry spec splits Exec at spaces: each argument quoted
        # whole (an entry written another way is redone)
        text = ("[Desktop Entry]\nType=Application\nName=aht tray\n"
                f"Exec={desktop_arg(exec_python(sys.executable))} {desktop_arg(tray)}\n"
                "X-GNOME-Autostart-enabled=true\n")
        try:
            same = f.read_text() == text
        except OSError:
            same = False
        if not same:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text)
    elif on is not None and f.is_file():
        f.unlink()
    runs = tray.is_file() and _linux_tray_runs(tray)
    return {"supported": runs or f.is_file(), "on": f.is_file(), "runs": runs}

def _linux_tray_runs(tray: Path) -> bool:
    """Whether the Linux tray can run here: it needs PyGObject and an
    AppIndicator library, which `tray.py --check` looks for.  The answer is
    kept per tray file and Python; a no is asked again after a minute, since
    the user may just have installed them."""
    try:
        key = [str(tray), tray.stat().st_mtime, sys.executable]
    except OSError:
        return False
    f = aht_home() / "run" / "tray-check.json"
    try:
        c = json.loads(f.read_text())
        if c.get("key") == key and (c.get("ok") or time.time() - c.get("at", 0) < 60):
            return bool(c.get("ok"))
    except (OSError, ValueError, AttributeError):
        pass
    try:
        ok = subprocess.run([sys.executable, str(tray), "--check"], capture_output=True,
                            stdin=subprocess.DEVNULL, timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        ok = False
    try:
        _write_json(f, {"key": key, "ok": ok, "at": time.time()})
    except OSError:
        pass
    return ok

def cmd_autostart(args):
    res = tray_autostart(None if args.state is None else args.state == "on")
    if args.json:
        print(json.dumps(res))
    else:
        print("aht's tray " + ("starts" if res["on"] else "does not start") + " at login"
              + ("" if res["supported"] else " (switched in the app on a Mac)"))
    return 0

def _steps_for() -> str:
    """Which computer's steps Getting started lists."""
    return os.environ.get("AHT_STEPS") or ("mac" if IS_MAC or "AHT_APPS" in os.environ
                                           else "windows" if os.name == "nt"
                                           else "linux" if IS_LINUX else "")

def _other_steps(kind: str, step) -> list:
    """Getting started on Windows and Linux: the tray at login, notices, the
    window's browser, a terminal, and the switches every system has."""
    out = []
    auto = tray_autostart()
    # the user said no (the installer's box, a switch): a choice, not a step left
    said_no = bool(auto.get("answered")) and not auto["on"]
    if auto.get("runs") is False and kind == "linux":
        out.append(step("login", False, "Start at login",
                        "aht's tray cannot run here: it needs PyGObject and an AppIndicator "
                        "library, so it shows no notices.",
                        "Install them: sudo apt install python3-gi "
                        "gir1.2-ayatanaappindicator3-0.1 (Debian, Ubuntu), sudo dnf install "
                        "python3-gobject libayatana-appindicator-gtk3 (Fedora), or sudo "
                        "pacman -S python-gobject libayatana-appindicator (Arch). GNOME also "
                        "needs the AppIndicator Support extension to show the tray.",
                        optional=said_no))
    elif auto["supported"]:
        out.append(step("login", auto["on"], "Start at login",
                        "aht's tray starts when you log in." if auto["on"] else
                        "aht's tray does not start at login, so it shows no notices until "
                        "you open it.", "Settings → This computer → Start aht's tray at login.",
                        optional=said_no))
    if kind == "linux":
        ns = bool(_have("notify-send"))
        out.append(step("notify_send", ns, "Notices on the desktop",
                        "notify-send is there, so aht can show its notices." if ns else
                        "notify-send is missing, so aht cannot show notices.",
                        "Install it: sudo apt install libnotify-bin (Debian, Ubuntu), or "
                        "libnotify on other systems."))
        # installed is what counts: over ssh or on a text console there is no
        # screen to ask on, and installing changes nothing
        dl = next((c for c in ("zenity", "kdialog", "yad") if _have(c)), None)
        out.append(step("dialogs", dl, "Questions in a window",
                        ("zenity or kdialog is there, so aht can ask before it relinks a "
                         "folder." if _linux_has_display() else
                         f"{dl} is there; aht asks in a window when it runs in your desktop "
                         "session.") if dl else "Neither zenity nor kdialog is there, so aht "
                        "cannot ask before it relinks a folder that moved.",
                        "Install one: sudo apt install zenity (or kdialog on KDE)."))
    try:
        import aht_web
        br = bool(aht_web.app_browser())
    except Exception:
        br = False
    out.append(step("app_window", br, "aht's window as an app",
                    "Edge or Chrome opens aht's window as an app of its own." if br else
                    "aht's window opens in your browser, as a tab: Edge or Chrome would "
                    "open it as an app of its own.",
                    "Install Microsoft Edge or Google Chrome.", optional=True))
    if kind == "windows":
        wt = bool(shutil.which("wt"))
        out.append(step("terminal", wt, "Windows Terminal",
                        "Windows Terminal is there for the sessions aht opens." if wt else
                        "Sessions open in a plain console window.",
                        "Install Windows Terminal from the Microsoft Store.", optional=True))
    rc = claude_remote_control()
    out.append(step("remote_control", rc, "Your sessions in the Claude app",
                    "Remote Control is on, so every session is in the Claude app on your "
                    "phone." if rc else "Remote Control is off, so your sessions are not "
                    "in the Claude app on your phone.",
                    "In Claude Code: /config → Enable Remote Control for all sessions.",
                    optional=True))
    up = bool(cfg_get("update_check"))
    out.append(step("update_check", up, "New versions",
                    "aht tells you when a new version is out (it asks GitHub once a day)."
                    if up else "Off: aht does not look for new versions.",
                    "Settings → This computer → Tell me when a new version of aht is out.",
                    optional=True))
    return out

def getting_started(iterm=None) -> list:
    """The steps that let aht do more here, each with whether it is done:
    iTerm2 and its settings, the app's own switches, and Remote Control in
    Claude Code.  "optional" ones are a matter of taste.  The app
    adds one only it can see: whether macOS lets it control iTerm2.  Windows
    and Linux have their own list (_other_steps)."""
    kind = _steps_for()
    if not kind:
        return []

    def step(id_, ok, title, text, how="", optional=False):
        return {"id": id_, "ok": bool(ok), "optional": optional, "title": title,
                "text": text, "how": "" if ok else how}
    if kind != "mac":
        return _other_steps(kind, step)
    if iterm is None:
        iterm = app_installed("iTerm")
    out = [step("iterm", iterm, "iTerm2", "Installed." if iterm else
                "Not installed. aht works with any terminal, but session names from tab "
                "titles, Go to Tab, Restore Workspace and a click in the corner list going "
                "to its session need iTerm2.", "Free, from https://iterm2.com.")]
    if iterm:
        api = iterm_pref("EnableAPIServer") == "1"
        out.append(step("iterm_api", api, "iTerm2's Python API",
                        "On: a name you give a session (/rename, in the Claude app, or "
                        "Rename… in aht) reaches its tab too." if api else
                        "Off: each session takes its tab's title, but a name you give a "
                        "session does not reach its tab.",
                        "iTerm2 → Settings → General → Magic → Enable Python API."))
    login = tray_starts_at_login()
    out.append(step("login", login, "Start at login",
                    "aht starts in the menu bar when you log in." if login else
                    "aht does not start at login. The corner list, the chimes and saving "
                    "the iTerm2 layout work only while the app runs.",
                    "Settings → This Mac → Start aht in the menu bar at login.",
                    optional=not login and _autostart_answer_path().is_file()))
    rc = claude_remote_control()
    out.append(step("remote_control", rc, "Your sessions in the Claude app",
                    "Remote Control is on, so every session is in the Claude app on "
                    "your phone, under its tab's name." if rc else
                    "Remote Control is off, so your sessions are not in the Claude app on "
                    "your phone.", "In Claude Code: /config → Enable Remote Control for all "
                    "sessions.", optional=True))
    corner = cfg_get("session_corner")
    click = (" A click brings a session's iTerm2 tab to the front." if iterm else
             " Without iTerm2, a click cannot bring a session to the front.")
    out.append(step("corner", corner, "Sessions in the corner",
                    ("On: the open Claude sessions are listed in the screen's top-right "
                     "corner, as working, waiting for you or done." if corner else
                     "Off. It lists the open Claude sessions in the screen's top-right "
                     "corner, as working, waiting for you or done.") + click,
                    "∞ menu → Sessions in the Corner.", optional=True))
    chimes = cfg_get("chimes")
    out.append(step("chimes", chimes, "Chimes",
                    ("On: a" if chimes else "Off. A") + " short sound when a session is "
                    "done or waits for you.", "∞ menu → Chimes.", optional=True))
    if iterm:
        dot = iterm_pref("ShowNewOutputIndicator") != "0"      # iTerm2's default: on
        out.append(step("new_output_dot", not dot, "iTerm2's blue dot",
                        "Off: no blue dot on tabs with new output." if not dot else
                        "iTerm2 puts a blue dot on every tab that printed something new, "
                        "which tells little once the corner list shows how each session "
                        "is doing.", "For calmer tabs: iTerm2 → Settings → Appearance → "
                        "Tabs → turn off Show new-output indicator.", optional=True))
        kept = _iterm_state_path().is_file()
        out.append(step("tab_colours", kept, "Tab colours for Restore Workspace",
                        "iTerm2 keeps its window state, where aht reads tab colours from."
                        if kept else "iTerm2 has kept no window state on this Mac, which "
                        "is where aht reads tab colours from, so Restore Workspace opens "
                        "tabs without their colours.", "iTerm2 keeps it to bring its "
                        "windows back: iTerm2 → Settings → General → Startup → Window "
                        "restoration policy.", optional=True))
    return out

def cmd_getting_started(args):
    steps = getting_started()
    if args.json:
        print(json.dumps({"steps": steps}, indent=2))
        return 0
    if not steps:
        print("Nothing to set up beyond `aht install` on this system.")
        return 0
    import textwrap
    print("Getting started: what lets aht do more here")
    for s in steps:
        mark = "✓" if s["ok"] else "○" if s["optional"] else "✗"
        line = (f"{mark} {s['title']}" + (" (optional)" if s["optional"] and not s["ok"] else "")
                + " — " + s["text"] + (" " + s["how"] if s["how"] else ""))
        print(textwrap.fill(line, 78, initial_indent="  ", subsequent_indent="    "))
    print(textwrap.fill("aht's window shows this list with a switch where it can (Settings → "
                        "Getting started)" + (", and also checks whether macOS lets it control "
                        "iTerm2." if _steps_for() == "mac" else "."), 78))
    return 0

def cmd_window(args):
    """aht's window on Windows and Linux: a page served to this computer only,
    in an app window of the browser (aht_web.py)."""
    sys.modules.setdefault("aht", sys.modules[__name__])
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import aht_web
    except ImportError:
        print("the window is not next to this copy of aht (aht_web.py and web/); on a Mac, "
              "open aht.app", file=sys.stderr)
        return 2
    return aht_web.main(args)

def build_parser():
    p = argparse.ArgumentParser(prog="aht")
    p.set_defaults(fn=cmd_about)
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("encode"); s.add_argument("path"); s.set_defaults(fn=cmd_encode)

    s = sub.add_parser("keys", help="show each backend's store key for a path")
    s.add_argument("path"); s.set_defaults(fn=cmd_keys)

    s = sub.add_parser("tag")
    s.add_argument("path"); s.add_argument("--apply", action="store_true")
    s.set_defaults(fn=cmd_tag)

    s = sub.add_parser("adopt")
    s.add_argument("--apply", action="store_true")
    s.add_argument("--json", action="store_true")
    # every list option: a flag given twice adds up (--only A --only B)
    s.add_argument("--roots", nargs="*", action="extend")
    s.add_argument("--only", nargs="*", action="extend", metavar="PATH",
                   help="only these of the folders found")
    s.set_defaults(fn=cmd_adopt)

    s = sub.add_parser("setup", help="first-time setup: which folders to watch, which "
                       "projects to take on, what to do when a folder moves")
    s.add_argument("--roots", nargs="*", action="extend", metavar="FOLDER",
                   help="the folders to watch")
    s.add_argument("--adopt", nargs="*", action="extend", metavar="PATH",
                   help="take on these projects found (default with --apply: all of them "
                   "but those you told aht to forget)")
    s.add_argument("--moves", choices=POLICY_CHOICES["moves"])
    s.add_argument("--copies", choices=POLICY_CHOICES["copies"])
    s.add_argument("--news", help=argparse.SUPPRESS)      # old scripts: no longer used
    for flag in ("badges", "backups", "notifications", "update-check"):
        s.add_argument("--" + flag, choices=("on", "off"))
    s.add_argument("--dismiss", action="store_true", help="the window: not now, do not offer "
                   "the setup again")
    s.add_argument("--apply", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_setup)

    s = sub.add_parser("autostart", help="whether aht's tray starts at login (Windows, "
                       "Linux; on a Mac the app has the switch)")
    s.add_argument("state", nargs="?", choices=("on", "off"))
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_autostart)

    s = sub.add_parser("suggest-matches")
    s.add_argument("--store", required=True, dest="store")
    s.add_argument("--roots", nargs="*", action="extend")
    s.add_argument("--limit", type=int, default=8)
    s.set_defaults(fn=cmd_suggest)

    s = sub.add_parser("bind")
    s.add_argument("--store", required=True, dest="store",
                   help="the orphan claude store dir name")
    s.add_argument("--to", required=True, dest="to")
    s.add_argument("--apply", action="store_true")
    s.set_defaults(fn=cmd_bind)

    s = sub.add_parser("reconcile")
    s.add_argument("--apply", action="store_true")
    s.add_argument("--notify", action="store_true")
    s.add_argument("--moves", choices=POLICY_CHOICES["moves"])
    s.add_argument("--copies", choices=POLICY_CHOICES["copies"])
    s.add_argument("--news", help=argparse.SUPPRESS)      # old scripts: no longer used
    s.add_argument("--only", nargs="*", action="extend", metavar="PATH")
    s.add_argument("--clear-declines", action="store_true", dest="clear_declines")
    s.add_argument("--roots", nargs="*", action="extend")
    s.set_defaults(fn=cmd_reconcile)

    s = sub.add_parser("hook")
    s.set_defaults(fn=cmd_hook)

    s = sub.add_parser("status")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("projects")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_projects)

    s = sub.add_parser("orphans")
    s.add_argument("--match", action="store_true")
    s.add_argument("--json", action="store_true")
    s.add_argument("--roots", nargs="*", action="extend")
    s.add_argument("--limit", type=int, default=8)
    s.set_defaults(fn=cmd_orphans)

    s = sub.add_parser("prune")
    s.add_argument("--apply", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_prune)

    s = sub.add_parser("forget")
    s.add_argument("path", nargs="?")
    s.add_argument("--uuid")
    s.add_argument("--remove-marker", action="store_true", dest="remove_marker")
    s.add_argument("--apply", action="store_true")
    s.set_defaults(fn=cmd_forget)

    s = sub.add_parser("config")
    s.add_argument("--set", nargs="*", action="extend", metavar="KEY=VALUE")
    s.add_argument("--unset", nargs="*", action="extend", metavar="KEY")
    s.add_argument("--reset", action="store_true")
    s.add_argument("--no-reload", action="store_true", dest="no_reload")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_config)

    s = sub.add_parser("doctor")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_doctor)

    s = sub.add_parser("logs", help="show recent log lines "
                       "(--errors: warnings + errors only)")
    s.add_argument("-n", "--lines", type=int, default=50)
    s.add_argument("--errors", action="store_true")
    s.add_argument("--watcher", action="store_true",
                   help="include the watcher's stream log")
    s.set_defaults(fn=cmd_logs)

    s = sub.add_parser("backends",
                       help="each agent CLI's store location (override with "
                            "--set-root when not found automatically)")
    s.add_argument("--set-root", nargs="*", action="extend", metavar="NAME=PATH",
                   dest="set_root")
    s.add_argument("--clear-root", nargs="*", action="extend", metavar="NAME",
                   dest="clear_root")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_backends)

    s = sub.add_parser("version"); s.set_defaults(fn=cmd_version)

    s = sub.add_parser("guide", help="what aht does, feature by feature, with examples")
    s.add_argument("--path", action="store_true", help="only where the guide is")
    s.set_defaults(fn=cmd_guide)

    s = sub.add_parser("install", help="set up the watcher, the Claude hook and "
                       "the aht command on this machine (macOS/Linux)")
    s.add_argument("--src", help="install from this folder, e.g. an aht.app's "
                   "Contents/Resources (default: where this aht.py lives)")
    s.set_defaults(fn=cmd_install)
    s = sub.add_parser("uninstall", help="remove the automation; no agent's "
                       "history is ever touched")
    s.add_argument("--remove-icons", action="store_true", dest="remove_icons",
                   help="also clear the folder badges aht applied")
    s.add_argument("--purge", action="store_true",
                   help="also remove the markers, registry and config")
    s.set_defaults(fn=cmd_uninstall)

    s = sub.add_parser("roots")
    s.add_argument("--add", nargs="*", action="extend")
    s.add_argument("--remove", nargs="*", action="extend")
    s.add_argument("--no-reload", action="store_true")
    s.set_defaults(fn=cmd_roots)

    s = sub.add_parser("reload")
    s.set_defaults(fn=cmd_reload)

    s = sub.add_parser("icons")
    s.add_argument("--refresh", action="store_true")
    s.add_argument("--roots", nargs="*", action="extend")
    s.set_defaults(fn=cmd_icons)

    s = sub.add_parser("backup")
    s.add_argument("--auto", action="store_true")
    s.add_argument("--offsite", action="store_true",
                   help="copy the backups to the machine set as offsite_backup")
    s.add_argument("--fetch-offsite", action="store_true", dest="fetch_offsite",
                   help="bring backups back from that machine (on a new computer); "
                        "it adds what is missing and never overwrites")
    s.add_argument("--from", dest="offsite_from", metavar="ID|NAME",
                   help="with --fetch-offsite: the computer whose backups to fetch")
    s.add_argument("--offsite-list", action="store_true", dest="offsite_list",
                   help="the computers whose backups that machine keeps")
    s.add_argument("--quiet", action="store_true")
    s.add_argument("--project")
    s.add_argument("--uuid")
    s.add_argument("--list", action="store_true")
    s.add_argument("--prune", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_backup)

    s = sub.add_parser("restore")
    s.add_argument("path")
    s.add_argument("--uuid")
    s.add_argument("--stamp")
    s.add_argument("--apply", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_restore)

    s = sub.add_parser("remote", help="the other machines a project can be "
                       "handed over to")
    s.add_argument("action", nargs="?",
                   choices=("list", "add", "remove", "default", "check", "discover"))
    s.add_argument("name", nargs="?")
    s.add_argument("target", nargs="?", help="user@host, as ssh takes it")
    s.add_argument("--json", action="store_true")
    s.add_argument("--sandbox", metavar="PATH", help=argparse.SUPPRESS)   # test machines
    s.set_defaults(fn=cmd_remote)

    s = sub.add_parser("mirror", help="keep a project's copy on the other "
                       "machine up to date in the background")
    s.add_argument("path", nargs="?")
    s.add_argument("--to", metavar="NAME")
    s.add_argument("--on", action="store_true")
    s.add_argument("--off", action="store_true")
    s.add_argument("--all", action="store_true", help="with --on / --off: every tracked "
                   "project at once")
    s.add_argument("--apply", action="store_true", help="with --all")
    s.add_argument("--run", action="store_true", help="sync now")
    s.add_argument("--due", action="store_true",
                   help="with --run: only what the interval says is due")
    s.add_argument("--quiet", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_mirror)

    s = sub.add_parser("handover", help="continue a project on the other "
                       "machine: files, history and the session")
    s.add_argument("path")
    s.add_argument("--to", metavar="NAME")
    s.add_argument("--session", help="the session to resume there "
                   "(default: the most recent one)")
    s.add_argument("--include", nargs="*", action="extend", metavar="PATH",
                   help="files or folders outside the project that travel along "
                        "(remembered for this project)")
    s.add_argument("--no-start", action="store_true", dest="no_start",
                   help="transfer only; start the agent there yourself")
    s.add_argument("--attach", action="store_true",
                   help="open the session in this terminal afterwards")
    s.add_argument("--task", metavar="TEXT",
                   help="what the session should start working on over there")
    s.add_argument("--allow-processes", action="store_true", dest="allow_processes",
                   help="leave other programs running in the folder behind "
                        "(an open agent session always blocks)")
    s.add_argument("--status-file", dest="status_file", metavar="FILE",
                   help="keep the current stage and percentage in FILE (front-ends)")
    s.add_argument("--apply", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_handover)

    s = sub.add_parser("reclaim", help="take a handed-over project back: "
                       "files and history return, nothing is overwritten "
                       "without a copy")
    s.add_argument("path")
    s.add_argument("--stop", action="store_true",
                   help="end the session there first if it is idle")
    s.add_argument("--prefer", choices=("here", "there"),
                   help="what changed on BOTH machines: keep ours and put theirs "
                        "next to it (here, the default), or take theirs and set "
                        "ours aside (there)")
    s.add_argument("--allow-processes", action="store_true", dest="allow_processes")
    s.add_argument("--ignore-version", action="store_true", dest="ignore_version")
    s.add_argument("--release", action="store_true",
                   help="stop waiting for it: the files here stay as they are, the copy "
                        "there is left alone, and the work done there does not come here")
    s.add_argument("--status-file", dest="status_file", metavar="FILE")
    s.add_argument("--apply", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_reclaim)

    s = sub.add_parser("attach", help="open a handed-over project's session")
    s.add_argument("path")
    s.add_argument("--print", action="store_true", help="only show the command")
    s.add_argument("--window", action="store_true", help="in a new terminal window")
    s.set_defaults(fn=cmd_attach)

    s = sub.add_parser("resume-here", help="continue a project's session in a "
                       "new terminal window")
    s.add_argument("path")
    s.add_argument("--handed-over", action="store_true", dest="handed_over",
                   help="the session the last handover sent, not the one used last")
    s.add_argument("--session", help="this session instead")
    s.add_argument("--agent", choices=SWITCH_TARGETS, default="claude")
    s.add_argument("--print", action="store_true")
    s.set_defaults(fn=cmd_resume_here)

    s = sub.add_parser("search", help="search every agent's sessions, also the "
                       "ones only history backups still hold")
    s.add_argument("words", nargs="*")
    s.add_argument("--project", metavar="PATH")
    s.add_argument("--agent", choices=sorted(AGENT_NAMES))
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--update", action="store_true", help="only bring the index up to date")
    s.add_argument("--no-update", action="store_true", dest="no_update")
    s.add_argument("--rebuild", action="store_true")
    s.add_argument("--quiet", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_search)

    s = sub.add_parser("secrets", help="what looks like a key, a token or a password "
                       "in the agents' histories (shown masked)")
    s.add_argument("path", nargs="?")
    s.add_argument("--redact", metavar="FINGERPRINT",
                   help="take this find out of the history files (they are copied first)")
    s.add_argument("--apply", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_secrets)

    s = sub.add_parser("journal", help="a dated diary of a project from its sessions")
    s.add_argument("path")
    s.add_argument("--days", type=int)
    s.add_argument("--write", action="store_true",
                   help="save it as .aht/journal/journal.md (git ignores it)")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_journal)

    s = sub.add_parser("rules", help="which instruction file each agent follows; make "
                       "AGENTS.md the one set of rules")
    s.add_argument("path")
    s.add_argument("--unify", action="store_true")
    s.add_argument("--prefer", choices=("claude", "agents", "both"))
    s.add_argument("--apply", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_rules)

    s = sub.add_parser("switch", help="continue a project's work in another agent, or "
                       "hand it back to the agent it came from")
    s.add_argument("path")
    s.add_argument("--to", choices=SWITCH_TARGETS,
                   help="the agent that goes on (with --back: hand back what came from it)")
    s.add_argument("--resume", action="store_true",
                   help="go on in that agent's own latest session here: it reads only what "
                   "happened since (default: a new session reads the whole summary)")
    s.add_argument("--session", help="the session to continue (default: the latest of "
                   "another agent)")
    s.add_argument("--brief-only", action="store_true", dest="brief_only",
                   help="write the summary and open nothing")
    s.add_argument("--back", action="store_true",
                   help="hand the work back into the first agent's own session, with what "
                   "happened since")
    s.add_argument("--no-window", action="store_true", dest="no_window")
    s.add_argument("--apply", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_switch)

    s = sub.add_parser("relays", help="who handed a project's work to whom, and when, "
                       "with each summary")
    s.add_argument("path")
    s.add_argument("--show", metavar="ID", help="print that hand-off's summary")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_relays)

    s = sub.add_parser("board", help="open agent sessions on this machine and the "
                       "others: working, waiting for you, idle")
    s.add_argument("--local", action="store_true", help="this machine only")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_board)

    s = sub.add_parser("notices", help="announce sessions that wait for you or "
                       "finished; run every half minute by aht's notices agent")
    s.add_argument("--test", action="store_true", help="send a sample notice")
    s.add_argument("--quiet", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_notices)

    s = sub.add_parser("tidy", help="tracked folders that are gone, histories without "
                       "a folder, folders listed twice — with suggestions")
    s.add_argument("--remove-history", metavar="STORE", dest="remove_history",
                   help="move a history that no folder owns to the Trash (on Windows, "
                   "the Recycle Bin)")
    s.add_argument("--show", metavar="KEY", help="a listed history as text to read (the "
                   "project id, or the history's name: --show=-Users-…)")
    s.add_argument("--relink", metavar="UUID", help="a gone project found again …")
    s.add_argument("--to", metavar="PATH", help="… at this folder")
    s.add_argument("--apply", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_tidy)

    s = sub.add_parser("changes", help="what a Claude Code session changed in the files")
    s.add_argument("path")
    s.add_argument("--session")
    s.add_argument("--diff", action="store_true", help="show the changes line by line")
    s.add_argument("--all", action="store_true", help="also files outside the project")
    s.add_argument("--revert", metavar="FILE", help="put this file back as it was "
                   "before the session")
    s.add_argument("--apply", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_changes)

    s = sub.add_parser("report", help="sessions and active time per project, agent "
                       "or area; an AI-use statement")
    s.add_argument("--since", help="YYYY-MM-DD, or today / week / month")
    s.add_argument("--until", help="YYYY-MM-DD (that day included)")
    s.add_argument("--project", metavar="PATH")
    s.add_argument("--by", choices=("project", "agent", "area"), default="project")
    s.add_argument("--statement", action="store_true",
                   help="a draft disclosure of AI use for --project")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_report)

    s = sub.add_parser("share", help="a session as a page to share: keys aht recognises "
                                     "masked, addresses and your home folder removed")
    s.add_argument("path")
    s.add_argument("--session")
    s.add_argument("--agent", choices=sorted(AGENT_NAMES))
    s.add_argument("--format", choices=("md", "html"), default="md")
    s.add_argument("--tools", action="store_true", help="also list the tools it used")
    s.add_argument("--out", metavar="FILE")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_share)

    s = sub.add_parser("limits", help="sessions that stopped at Claude's usage limit "
                       "(and, if turned on, the agent to go on in)")
    s.add_argument("--hours", type=float, default=12)
    s.add_argument("--auto-continue", choices=("on", "off"), dest="auto_continue",
                   help="Claude Code's own setting: go on by itself when the limit resets "
                        "(uses tokens)")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_limits)

    s = sub.add_parser("checkpoint", help="copy a folder now, to undo a session with "
                       "later (the Claude hook does this when a session starts)")
    s.add_argument("path", nargs="?")
    s.add_argument("--coverage", action="store_true",
                   help="how many files each project would copy, and which are over "
                        "the limit")
    s.add_argument("--max", type=int, help="with --coverage: try this limit instead")
    s.add_argument("--top", type=int, default=15)
    s.add_argument("--session")
    s.add_argument("--agent", default="claude")
    s.add_argument("--quiet", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_checkpoint)

    s = sub.add_parser("undo", help="put a folder back the way it was when a session "
                       "started; what is there now is set aside")
    s.add_argument("path")
    s.add_argument("--list", action="store_true", help="the copies kept of this folder")
    s.add_argument("--checkpoint", metavar="ID")
    s.add_argument("--session", metavar="ID", help="to before this session's first start")
    s.add_argument("--diff", action="store_true")
    s.add_argument("--apply", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_undo)

    s = sub.add_parser("loose-ends", help="projects with work not committed, open to-dos "
                       "or a last session that asked you something")
    s.add_argument("--days", type=int, default=30)
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_loose_ends)

    s = sub.add_parser("second-opinion", help="the same task by two agents, each in a "
                       "copy, to compare (uses both agents' tokens; off by default)")
    s.add_argument("path", nargs="?")
    s.add_argument("--task", metavar="TEXT")
    s.add_argument("--agents", metavar="A,B", help="default: claude,kimi")
    s.add_argument("--list", action="store_true")
    s.add_argument("--show", metavar="ID")
    s.add_argument("--diff", action="store_true")
    s.add_argument("--take", metavar="ID", help="bring one agent's changes into the project")
    s.add_argument("--from", dest="agent", choices=OPINION_AGENTS)
    s.add_argument("--discard", metavar="ID", help="remove the copies")
    s.add_argument("--run", metavar="ID", help=argparse.SUPPRESS)
    s.add_argument("--apply", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_second_opinion)

    s = sub.add_parser("night-shift", help="hand a project over with a task at a time, "
                       "take it back at another (uses tokens; off by default)")
    s.add_argument("path", nargs="?")
    s.add_argument("--task", metavar="TEXT")
    s.add_argument("--start", metavar="HH:MM", default="now")
    s.add_argument("--back", metavar="HH:MM", default="07:00")
    s.add_argument("--to", metavar="NAME")
    s.add_argument("--list", action="store_true")
    s.add_argument("--cancel", metavar="ID")
    s.add_argument("--step", metavar="ID", help=argparse.SUPPRESS)
    s.add_argument("--apply", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_night_shift)

    s = sub.add_parser("sessions", help="every session aht knows, newest first; with a "
                       "project, its sessions with each branch under its origin")
    s.add_argument("project", nargs="?", help="only this project's sessions, as a tree")
    s.add_argument("--limit", type=int, default=500)
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_sessions)

    s = sub.add_parser("tab-names", help="the open Claude sessions, their iTerm2 tab "
                       "titles and the names the Claude app shows")
    s.add_argument("--refresh", action="store_true", help="look at iTerm2's tabs again")
    s.add_argument("--fresh", action="store_true",
                   help="ask iTerm2 now instead of using the last look")
    s.add_argument("--rename", metavar="SESSION", help="give this open session a name "
                   "(applied at its next prompt)")
    s.add_argument("--to", metavar="NAME", help="with --rename; empty: follow the tab again")
    s.add_argument("--sync-all", action="store_true", dest="sync_all",
                   help="every open session takes its tab's title, also ones named "
                        "otherwise (applied at each one's next prompt)")
    s.add_argument("--apply", action="store_true")
    s.add_argument("--quiet", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_tab_names)

    s = sub.add_parser("goto", help="bring the iTerm2 tab of an open Claude session to "
                       "the front")
    s.add_argument("target", help="its project folder, session id or process id")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_goto)

    s = sub.add_parser("checkup", help="open Claude sessions worth a look: open twice, "
                       "stuck, not in the Claude app, older Claude Code")
    s.add_argument("--close", metavar="PID", type=int, help="end that session's process "
                   "(its conversation stays)")
    s.add_argument("--restart", metavar="PID", type=int, help="end it and start it again "
                   "in its iTerm2 tab")
    s.add_argument("--apply", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_sessions_checkup)

    s = sub.add_parser("workspace", help="iTerm2's windows and tabs with their sessions: "
                       "saved while you work, opened again after a restart")
    s.add_argument("--save", action="store_true", help="save it now")
    s.add_argument("--auto", action="store_true",
                   help="with --save: only when workspace_save_minutes have passed (the app)")
    s.add_argument("--quiet", action="store_true")
    s.add_argument("--restore", nargs="?", const="", metavar="ID",
                   help="open a saved one again (default: the one before iTerm2 last "
                        "started)")
    s.add_argument("--apply", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_workspace)

    s = sub.add_parser("update", help="whether a new version of aht is out (asks GitHub "
                       "once a day when update_check is on), what's new, and the upgrade")
    s.add_argument("--now", action="store_true", help="ask GitHub now")
    s.add_argument("--upgrade", action="store_true", help="upgrade the way aht was "
                   "installed: Homebrew, Scoop or winget in a terminal; aht's Windows "
                   "installer is downloaded, checked and run; a checkout says how to "
                   "update it; else the download page opens")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_update)

    s = sub.add_parser("getting-started", help="what lets aht do more on this computer: "
                       "iTerm2 and the app's switches on a Mac; the tray at login, notices "
                       "and the window's browser on Windows and Linux; Remote Control")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_getting_started)

    s = sub.add_parser("window", help="aht's window on Windows and Linux: a page served to "
                       "this computer only, in an app window of the browser")
    s.add_argument("--no-open", action="store_true", help="only serve; print the address")
    s.add_argument("--port", type=int, default=0)
    s.add_argument("--selftest", action="store_true")
    s.set_defaults(fn=cmd_window)

    s = sub.add_parser("_agent")           # the far end of a handover (stdin: JSON)
    s.set_defaults(fn=cmd_agent)

    s = sub.add_parser("_core")            # the core this build carries
    s.add_argument("--id", action="store_true", help="its checksum id")
    s.set_defaults(fn=cmd_core)

    return p

def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args) or 0
    except (SystemExit, KeyboardInterrupt, BrokenPipeError):
        raise
    except Exception:
        import traceback
        error("UNCAUGHT " + traceback.format_exc())
        raise

if __name__ == "__main__":
    sys.exit(main())
