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

VERSION = "0.10.0"

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
    roots += [str(p) for p in extra if p.is_dir()]
    return roots

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
    "new_policy":       "apply",     # ask | apply | ignore
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
    "backup_keep":      10,
    "backup_dir":       None,        # None -> <aht_home>/backups
    "linux_emblem_method": "auto",   # auto | gio | kde | both | none
    "linux_agent_emblem": "emblem-favorite",
    "linux_git_emblem":   "emblem-symbolic-link",
    # handover: run a project on another machine of yours (see `aht remote`)
    "remotes":          None,        # {name: {"ssh": "user@host"}}
    "default_remote":   None,
    "mirror_interval_minutes": 30,   # background sync of mirrored projects
    "handover_excludes": [],         # extra names that never travel
    "handover_compress": True,       # rsync -z: histories and code are text
    "handover_remote_control": True, # reachable from the Claude app
    "handover_carry_trust": True,    # a folder trusted here is trusted there
    "handover_claude_args": [],      # extra arguments for the resumed session
    "handover_mosh":    True,        # attach with mosh when both sides have it
    "rsync_path":       None,        # None -> the newest rsync found
    "terminal_app":     None,        # macOS: app that opens a session window
}

POLICY_CHOICES = {
    "moves":  ("ask", "apply", "decline", "ignore"),
    "copies": ("ask", "duplicate", "independent", "ignore"),
    "news":   ("ask", "apply", "ignore"),
}

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
    if isinstance(d, int) and not isinstance(d, bool):
        return int(raw)
    if key == "log_level":
        v = raw.strip().lower()
        if v not in LOG_LEVELS:
            raise ValueError(f"log_level expects one of {sorted(LOG_LEVELS)}")
        return v
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
        bad = [k for k in obj if k not in BACKEND_NAMES]
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
    if env:
        return [_expand(p) for p in env.split(os.pathsep) if p]
    roots = load_config().get("watch_roots")
    if roots:
        return [_expand(r) for r in roots if r]
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

def notify_user(title: str, message: str) -> None:
    try:
        if os.environ.get("AHT_NO_NOTIFY") or not cfg_get("notifications", True):
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

REGISTRY_KEEP = ("mirror", "away", "returned", "extras")   # handover's records

def _register(reg: dict, uid: str, real_path: str, stores=None) -> None:
    prev = reg["projects"].get(uid) or {}
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

def registered_history_dirs(reg: dict) -> set:
    return {(e.get("stores") or {}).get("claude")
            for e in reg["projects"].values()
            if (e.get("stores") or {}).get("claude")}

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
        root = os.path.realpath(root)
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
                path_to_uuid[rp] = uid
                uuid_to_paths.setdefault(uid, []).append(rp)
            dirnames[:] = [d for d in dirnames
                           if not d.startswith(".") and d not in pruned]
    return path_to_uuid, uuid_to_paths

def list_real_dirs(roots: list, max_depth: int = None) -> list:
    if max_depth is None:
        max_depth = int(cfg_get("scan_max_depth", 7))
    out = []
    pruned = prune_dirs()
    for root in roots:
        root = os.path.realpath(root)
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
    """d×d straight-alpha RGBA: a white-ringed disc for one agent (name) or a
    slate count disc with the number drawn in (int, for 4+ agents)."""
    if isinstance(agent_or_count, int):
        rgb, glyph = COUNT_BADGE_RGB, str(min(agent_or_count, 9))
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
                col = (255, 255, 255)          # halo ring
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
                    col = (int(col[0] + (255 - col[0]) * g),
                           int(col[1] + (255 - col[1]) * g),
                           int(col[2] + (255 - col[2]) * g))
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

EMBLEM_VERSION = 3

def _ensure_linux_emblems() -> bool:
    """Generate the per-agent + count emblems into the user icon theme once.
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
        if "git" in marks:
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
        root = os.path.realpath(root)
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
    moves, copies, news, missing = [], [], [], []
    for uid, paths in uuid_to_paths.items():
        entry = reg["projects"].get(uid)
        if entry is None:
            for p in paths:
                news.append({"uuid": uid, "path": p})
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
                         if os.path.realpath(p) == os.path.realpath(old_path)]
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
                or (own is None and tgt.exists()
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

def cmd_adopt(args):
    """Store-corroborated adoption: a folder is planned when it carries a
    marker (current or legacy form) OR any backend provably has history for its
    exact path.  ADD-ONLY."""
    roots = args.roots or default_roots()
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

    applied = []
    if args.apply and planned:
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

    owned = registered_history_dirs(load_registry())
    orphans_claude = sum(1 for d in _iter_history_dirs() if d.name not in owned)

    result = {"applied": bool(args.apply), "planned": planned,
              "adopted": applied, "already": already,
              "orphans_claude": orphans_claude}
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{'APPLIED' if args.apply else 'DRY-RUN'} adoption over roots: {roots}\n")
        print(f"  planned : {len(planned)}")
        for a in planned:
            print(f"      + {a['real']}   [{', '.join(a['stores']) or 'marker only'}]")
        print(f"  already tracked : {already}")
        print(f"  claude orphan histories (no matching folder) : {orphans_claude}")
        if orphans_claude:
            print("      match them with:  aht orphans --match")
        if args.apply:
            print(f"\n  APPLIED {len(applied)} adoption(s).")
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
    if getattr(args, "apply", False):
        pol = {"moves": "apply", "copies": "duplicate", "news": "apply"}
    elif getattr(args, "notify", False):
        pol = {"moves":  cfg_get("move_policy", "ask"),
               "copies": cfg_get("copy_policy", "ask"),
               "news":   cfg_get("new_policy", "apply")}
    else:
        pol = {"moves": "ignore", "copies": "ignore", "news": "ignore"}
    for k in ("moves", "copies", "news"):
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
    want = {os.path.realpath(p) for p in only}
    return [i for i in items if os.path.realpath(i[key]) in want]

def cmd_reconcile(args):
    roots = args.roots or default_roots()
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
    if pol["news"] == "ask":
        pol["news"] = "apply"

    do_moves = pol["moves"] == "apply"
    decline_moves = list(moves) if pol["moves"] == "decline" else []
    do_copies = pol["copies"] in ("duplicate", "independent")
    do_news = pol["news"] == "apply"

    conflicts, applied_moves, applied_copies = [], [], []
    if ((do_moves and moves) or (do_copies and copies)
            or (do_news and news) or decline_moves):
        with Lock():
            reg = load_registry()
            _, uuid_to_paths = find_markers(roots)
            moves2, copies2, news2, missing = compute_actions(
                reg, uuid_to_paths, respect_declines=not forced)
            moves2 = _selected(moves2, "to", only)
            copies2 = _selected(copies2, "copy_path", only)
            news2 = _selected(news2, "path", only)
            declined = reg.setdefault("declined_moves", {})
            if do_moves:
                applied_moves, conflicts = apply_moves(reg, moves2)
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
            if bool(args.apply) or age > GIT_SCAN_INTERVAL:
                tpaths = tethered_paths(reg)
                git_now = find_git_repos(roots)
                git_prev = set(reg.get("git_repos", []))
                changed_git = [(p, desired_marks(p, p in tpaths))
                               for p in (git_now ^ git_prev)]
                reg["git_scan_at"] = time.time()
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
                    if os.path.isdir(old_real):
                        nu = new_uuid()
                        write_marker(cwd, nu)
                        _register(reg, nu, cwd)
                        save_registry(reg)
                        log(f"HOOK copy-detected, new id for {cwd}")
                    else:
                        old_store = (entry.get("stores") or {}).get("claude")
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
    _hook_notes(cwd)
    _spawn_auto_backup()
    _spawn_mirror()
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

def hook_installed() -> bool:
    s = Path.home() / ".claude/settings.json"
    try:
        data = json.loads(s.read_text())
        for group in data.get("hooks", {}).get("SessionStart", []):
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
    owned = registered_history_dirs(reg)
    orphan_dirs = [d.name for d in _iter_history_dirs() if d.name not in owned]
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
        "backends": backend_status(),
        "watcher": watcher_status(),
        "backups": backup_status(),
        "handover": handover_status(),
        "log": {"path": str(log_path()),
                "recent_problems": recent_log_problems()},
        "hook_installed": hook_installed(),
        "gui_dialogs": gui_dialogs_available(),
        "policies": {"moves": cfg_get("move_policy"),
                     "copies": cfg_get("copy_policy"),
                     "news": cfg_get("new_policy")},
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
        print(f"  policies         : moves={st['policies']['moves']} "
              f"copies={st['policies']['copies']} news={st['policies']['news']}")
    return 0

def cmd_projects(args):
    reg = load_registry()
    out = []
    try:
        live = running_sessions() if handover_supported() else []
    except Exception:
        live = []
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
               "agents": agents_of(e.get("stores") or {})}
        mine = [s["status"] for s in live
                if _inside(os.path.realpath(s["cwd"]), os.path.realpath(e["real_path"]))]
        # an open agent session: "working" or "idle" (it blocks a handover)
        row["open"] = None if not mine else (
            "idle" if all(s == "idle" for s in mine) else "working")
        row.update(_hist_stats(e))
        out.append(row)
    out.sort(key=lambda r: r["real_path"].lower())
    if args.json:
        print(json.dumps({"projects": out}, indent=2))
    else:
        print(f"{len(out)} tethered project(s):")
        for r in out:
            flag = " " if r["exists"] else "!"
            print(f" {flag} {r['real_path']}"
                  + (f"   → handed over to {r['away']}" if r["away"] else ""))
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
    owned = registered_history_dirs(reg)
    dirs = list_real_dirs(roots) if args.match else None
    rows = []
    for d in _iter_history_dirs():
        if d.name in owned:
            continue
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
    by = {}
    for u, e in reg.get("projects", {}).items():
        by.setdefault(os.path.realpath(e["real_path"]), []).append(u)
    out = []
    for path, ids in sorted(by.items()):
        if len(ids) < 2 or not os.path.isdir(path):
            continue
        owner = read_marker(path)
        if owner in ids:
            out += [{"uuid": u, "real_path": path, "owner": owner,
                     "stores": sorted(reg["projects"][u].get("stores") or {})}
                    for u in ids if u != owner and not reg["projects"][u].get("away")]
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
        _reload_watcher()
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
    owned = registered_history_dirs(reg)
    orph = [d.name for d in _iter_history_dirs() if d.name not in owned]
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
                if name not in BACKEND_NAMES:
                    print(f"unknown backend {name!r}; known: "
                          f"{', '.join(BACKEND_NAMES)}", file=sys.stderr)
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
    the installed tools dir, or in aht.app's Resources folder."""
    here = Path(__file__).resolve().parent
    for c in (here / f"{name}.py", here / "linux" / f"{name}.py"):
        if c.is_file():
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

HANDOVER (continue on another machine of yours, over ssh):
  aht remote discover                   machines of your network that qualify
  aht remote add <name> <user@host>     name a machine (as many as you like)
  aht remote check [name|all]           what it lacks, with the fix
  aht mirror <folder> --on              keep its copy there up to date
  aht handover <folder> --apply         send it and resume the session there
  aht attach <folder>                   open that session
  aht reclaim <folder> --apply          bring files and history back

Data:  ~/.aht/  (registry.json, config.json, backups/, aht.log)
Docs:  README.md
"""

def cmd_about(_args):
    print(ABOUT)
    return 0

def _reload_watcher():
    if cfg_get("watcher_owner", "agent") == "none":
        print("watching is off (watcher_owner=none) — nothing to reload")
        return
    here = Path(__file__).resolve().parent
    search = [here]
    if IS_LINUX:
        search.append(here / "linux")
    elif IS_MAC:
        search.append(here / "macos")
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
                    return
                finally:
                    sys.path[:] = old
        raise FileNotFoundError("install.py not found next to aht.py")
    except Exception as e:
        print(f"⚠ could not reload the watcher ({e}); re-run the installer")

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

def handover_supported() -> bool:
    return os.name != "nt" and not getattr(sys, "frozen", False)

def handover_skip() -> list:
    extra = cfg_get("handover_excludes") or []
    return list(HANDOVER_SKIP) + [str(x) for x in extra if x]

def _skip_name(name: str, skip) -> bool:
    return any(fnmatch.fnmatchcase(name, pat) for pat in skip)

def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)

def _inside(path: str, root: str) -> bool:
    path, root = _nfc(str(path)).rstrip("/"), _nfc(str(root)).rstrip("/")
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

# ---- what is running in a folder ------------------------------------------ #

def claude_home() -> Path:
    return claude_backend().root().parent

def _pid_alive(pid: int) -> bool:
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
        out.append({"pid": pid, "cwd": cwd, "session": rec.get("sessionId"),
                    "status": str(rec.get("status") or "unknown"),
                    "kind": rec.get("kind"), "name": rec.get("name")})
    return out

def processes_inside(path: str) -> list:
    """This user's processes whose working directory is inside `path`: a dev
    server, a build, another agent CLI.  Shells that merely sit in the folder
    are left out."""
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
        out.append(f"an agent session is {'WORKING' if busy else 'open'} in this "
                   f"project {where} (pid {s['pid']}"
                   + (f", “{s['name']}”" if s.get("name") else "") + ") — "
                   + ("wait until it has finished, then exit it" if busy
                      else "exit it first (/exit)"))
    return out

# ---- manifests -------------------------------------------------------------- #

def tree_manifest(root: str, skip=None) -> dict:
    """{files: {rel: [size, mtime] | ["l", target]}, raw: {rel: name on disk}}
    — `rel` is NFC so a Mac's decomposed names compare equal to Linux's."""
    skip = list(handover_skip() if skip is None else skip)
    files, raw = {}, {}
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
            rel = os.path.relpath(p, root)
            key = _nfc(rel)
            files[key] = val
            if key != rel:
                raw[key] = rel
    return {"files": files, "raw": raw}

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
    return ["-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
            "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=4",
            "-o", "ControlMaster=auto", "-o", f"ControlPath={run}/ssh-%C",
            "-o", "ControlPersist=60"]

_STAT_RE = {
    "files": re.compile(r"Number of regular files transferred:\s*([\d,.]+)"),
    "bytes": re.compile(r"Total transferred file size:\s*([\d,.]+)"),
    "sent": re.compile(r"Total bytes sent:\s*([\d,.]+)"),
    "received": re.compile(r"Total bytes received:\s*([\d,.]+)"),
    "deleted": re.compile(r"Number of deleted files:\s*([\d,.]+)"),
}

def _num(s: str) -> int:
    return int(re.sub(r"[^\d]", "", s) or 0)

# ---- a remote machine ------------------------------------------------------- #

class Remote:
    """One of the user's other machines.  `ssh` is the usual user@host; `root`
    (tests) makes a local directory stand in for the machine instead."""

    def __init__(self, name: str, spec: dict):
        self.name = name
        self.target = str(spec.get("ssh") or "")
        self.root = str(spec.get("root") or "").rstrip("/")
        self.claude = spec.get("claude")
        self.info = {}
        self.on_percent = None          # called with rsync's percentage

    @property
    def local(self) -> bool:
        return bool(self.root) and not self.target

    def path(self, p: str) -> str:
        return self.root + p if self.local else p

    def spec(self, remote_abs: str) -> str:
        return remote_abs if self.local else f"{self.target}:{remote_abs}"

    def _env(self) -> dict:
        home = self.root + "/home"
        e = {k: v for k, v in os.environ.items()
             if not k.startswith("AHT_") or k == "AHT_CLAUDE"}
        e.update(HOME=home, AHT_HOME=home + "/.aht",
                 AHT_ROOT_CLAUDE=home + "/.claude/projects",
                 AHT_NO_ICONS="1", AHT_NO_NOTIFY="1", AHT_NO_BACKUP="1",
                 AHT_NO_MIRROR="1")
        if os.environ.get("AHT_REMOTE_PATH"):
            e["PATH"] = os.environ["AHT_REMOTE_PATH"] + os.pathsep + e.get("PATH", "")
        if os.environ.get("AHT_REMOTE_CLAUDE"):     # tests: another version there
            e["AHT_CLAUDE"] = os.environ["AHT_REMOTE_CLAUDE"]
        return e

    def sh(self, script: str, stdin: str = None, timeout: float = 120):
        kw = {"input": stdin, "capture_output": True, "text": True,
              "timeout": timeout, "cwd": "/"}
        try:
            if self.local:
                Path(self.root + "/home").mkdir(parents=True, exist_ok=True)
                return subprocess.run(["/bin/sh", "-c", script], env=self._env(), **kw)
            r = subprocess.run(["ssh"] + _ssh_opts() + [self.target, script], **kw)
        except subprocess.TimeoutExpired:
            raise HandoverError(f"{self.name} did not answer within {timeout:.0f} s")
        if r.returncode == 255:
            raise HandoverError(f"cannot reach {self.name} ({self.target}): "
                                + ((r.stderr or "").strip().splitlines() or ["no answer"])[-1])
        return r

    def push_agent(self) -> None:
        """The other side runs this very file, so both ends always agree."""
        r = self.sh('mkdir -p "$HOME/.aht/remote" && chmod 700 "$HOME/.aht/remote" && '
                    'cat > "$HOME/.aht/remote/aht.py.new" && '
                    'mv "$HOME/.aht/remote/aht.py.new" "$HOME/.aht/remote/aht.py"',
                    stdin=Path(__file__).resolve().read_text(encoding="utf-8"))
        if r.returncode != 0:
            raise HandoverError(f"could not prepare {self.name}: "
                                + (r.stderr or "").strip()[-200:])

    def agent(self, op: str, timeout: float = 120, **req) -> dict:
        req["op"] = op
        py = shlex.quote(sys.executable) if self.local else "python3"
        r = self.sh(f'exec {py} "$HOME/.aht/remote/aht.py" _agent',
                    stdin=json.dumps(req), timeout=timeout)
        i = (r.stdout or "").rfind(AGENT_MARK)
        if i < 0:
            raise HandoverError(f"{self.name} gave no usable answer to “{op}”: "
                                + ((r.stderr or r.stdout or "").strip()[-300:]
                                   or "python3 missing?"))
        res = json.loads(r.stdout[i + len(AGENT_MARK):])
        if not res.get("ok"):
            raise HandoverError(f"{self.name}: {res.get('error') or op + ' failed'}")
        return res

    def connect(self, path: str = None) -> dict:
        self.push_agent()
        self.info = self.agent("probe", path=self.path(path) if path else None,
                               claude=self.claude)
        return self.info

    def rsync(self, src: str, dst: str, *, delete: bool = False,
              backup_dir: str = None, skip=(), files_from: list = None,
              dry: bool = False, update: bool = False, include: list = None,
              progress: bool = False) -> dict:
        """One rsync run between this machine and the remote.  Paths ending in
        a slash are directories whose CONTENT is synced."""
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
            cmd += ["-e", "ssh " + " ".join(shlex.quote(o) for o in _ssh_opts())]
        if dry:
            cmd.append("-n")
        if update:
            cmd.append("--update")
        if delete:
            cmd.append("--delete")
        if backup_dir:
            cmd += ["--backup", "--backup-dir=" + backup_dir]
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
        return subprocess.run([exe, *args], capture_output=True, text=True,
                              timeout=timeout, cwd="/")
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
            "sessions_open": len(running_sessions())}
    if path:
        anc = Path(path)
        while not anc.exists() and anc != anc.parent:
            anc = anc.parent
        info["path_exists"] = os.path.isdir(path)
        info["path_base"] = str(anc)
        info["path_writable"] = os.access(str(anc), os.W_OK | os.X_OK)
        try:
            info["path_open_to_others"] = bool(os.stat(path).st_mode & 0o077) \
                if os.path.isdir(path) else None
        except OSError:
            info["path_open_to_others"] = None
        info["path_real"] = os.path.realpath(path)
        try:
            v = os.statvfs(str(anc))
            info["free_bytes"] = v.f_bavail * v.f_frsize
        except OSError:
            pass
        info.update(activity_in(info["path_real"]) if info["path_exists"]
                    else {"sessions": [], "processes": []})
    return info

def _agent_manifest(req: dict) -> dict:
    out = {}
    for name, spec in (req.get("trees") or {}).items():
        out[name] = tree_manifest(spec["path"], spec.get("skip") or []) \
            if os.path.isdir(spec["path"]) else {"files": {}, "raw": {}}
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
    mux = shutil.which("byobu") or shutil.which("tmux")
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
    line = ("cd %s && env DISABLE_AUTOUPDATER=1 %s; st=$?; cd /; "
            "printf '\\n[aht] the agent exited (%%s); this window closes in a minute\\n' "
            "\"$st\"; sleep 60"
            % (shlex.quote(path), " ".join(shlex.quote(a) for a in argv)))
    (run / "command.txt").write_text(line + "\n")
    new = ["new-session", "-d", "-s", name, "-x", "200", "-y", "50", "-c", path, line]
    r = subprocess.run([mux] + new, capture_output=True, text=True, timeout=60)
    if r.returncode != 0 and os.path.basename(mux) == "byobu":
        mux = shutil.which("tmux")
        r = subprocess.run([mux] + new, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        return {"ok": False, "error": "could not start the terminal session: "
                + (r.stderr or r.stdout).strip()[-200:]}
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

def _agent_prune(req: dict) -> dict:
    """Drop what earlier syncs set aside, beyond the newest few."""
    base, keep, n = Path(req["dir"]), int(req.get("keep") or 5), 0
    if base.is_dir():
        for d in sorted(p for p in base.iterdir() if p.is_dir())[:-keep]:
            shutil.rmtree(d, ignore_errors=True)
            n += 1
    return {"ok": True, "pruned": n}

AGENT_OPS = {"probe": _agent_probe, "manifest": _agent_manifest,
             "hash": _agent_hash, "prepare": _agent_prepare,
             "trust": _agent_trust, "install-claude": _agent_install_claude,
             "start": _agent_start, "stop": _agent_stop, "peek": _agent_peek,
             "close": _agent_close, "written-by": _agent_written_by,
             "udp-echo": _agent_udp_echo,
             "prune": _agent_prune}

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

def session_digest(jsonl, project: str, turns: int = 8) -> dict:
    """The state of one session, read from its transcript: title, the last
    compaction summary, the latest exchanges, open to-dos, files it touched
    and the paths OUTSIDE the project it used."""
    d = {"title": None, "summary": None, "exchanges": [], "todos": [],
         "touched": [], "outside": [], "version": None}
    cur = None
    home = str(Path.home())
    noise = (home + "/.claude", home + "/.aht", "/tmp/", "/private/", "/var/",
             "/dev/", "/proc/", "/usr/", "/opt/", "/System/", "/Library/", "/etc/",
             "/bin/", "/sbin/")
    try:
        fh = open(jsonl, "r", errors="replace")
    except OSError:
        return d
    with fh:
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
            if t == "user":
                if e.get("isCompactSummary"):
                    d["summary"], d["exchanges"], cur = _text_of(c), [], None
                    continue
                if e.get("isMeta") or e.get("toolUseResult") is not None:
                    continue
                if isinstance(c, list) and any(isinstance(b, dict) and
                                               b.get("type") == "tool_result" for b in c):
                    continue
                txt = _text_of(c).strip()
                if not txt or txt.startswith("<"):      # reminders, notifications
                    continue
                cur = {"you": txt, "agent": ""}
                d["exchanges"].append(cur)
                del d["exchanges"][:-turns]
            elif t == "assistant":
                txt = _text_of(c).strip()
                if txt and cur is not None:
                    cur["agent"] = txt                  # a turn's last text wins
                for b in c if isinstance(c, list) else []:
                    if not (isinstance(b, dict) and b.get("type") == "tool_use"):
                        continue
                    inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                    if b.get("name") == "TodoWrite" and isinstance(inp.get("todos"), list):
                        d["todos"] = inp["todos"]
                    fp = inp.get("file_path") or inp.get("notebook_path") or inp.get("path")
                    if not (isinstance(fp, str) and fp.startswith("/")):
                        continue
                    if _inside(fp, project):
                        if b.get("name") in ("Write", "Edit", "NotebookEdit"):
                            rel = os.path.relpath(fp, project)
                            if rel in d["touched"]:
                                d["touched"].remove(rel)
                            d["touched"].append(rel)
                    elif not fp.startswith(noise):
                        if fp in d["outside"]:
                            d["outside"].remove(fp)
                        d["outside"].append(fp)
    d["touched"] = d["touched"][-15:]
    d["outside"] = d["outside"][-15:]
    d["todos"] = [x for x in d["todos"] if isinstance(x, dict)
                  and x.get("status") != "completed"]
    return d

def scratch_dir(real: str, sid: str):
    """Where the agent CLI keeps a session's own scratch files."""
    for tmp in ("/private/tmp", "/tmp"):
        p = Path(tmp) / f"claude-{os.getuid()}" / _key_claude(real) / sid / "scratchpad"
        if p.is_dir():
            return p
    return None

def write_brief(real: str, sid, dig: dict, here: str, there: str,
                there_system: str, carried: list, scratch: bool) -> tuple:
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
        L.append(f"- Session: {dig.get('title') or 'untitled'} — `{sid}`"
                 + (f", Claude Code {dig['version']}" if dig.get("version") else ""))
        L.append(f"- Continue it with: `claude --resume {sid}`")
    if dig.get("summary"):
        L += ["", "## Where things stood", "", _clip(dig["summary"], 8000)]
    if dig.get("exchanges"):
        L += ["", "## The latest exchanges"]
        for x in dig["exchanges"]:
            L += ["", "**You:** " + _clip(x["you"], 1500)]
            if x.get("agent"):
                L += ["", "**Agent:** " + _clip(x["agent"], 2500)]
    if dig.get("todos"):
        L += ["", "## Open to-do items", ""]
        L += [f"- [ ] {_clip(str(x.get('content') or x.get('subject') or ''), 200)}"
              + ("  *(in progress)*" if x.get("status") == "in_progress" else "")
              for x in dig["todos"]]
    if dig.get("touched"):
        L += ["", "## Files changed most recently", ""]
        L += [f"- `{p}`" for p in reversed(dig["touched"])]
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
    for old in sorted(out.glob("*-to-*.md"))[:-5]:
        old.unlink()
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
    host = rem.target.split("@")[-1]
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
    inner = [mux or "tmux", "attach", "-t", name]
    if rem.local:
        return inner
    if mosh_usable(rem):
        return [find_tool("mosh"), rem.target, "--"] + inner    # survives a changing network
    return ["ssh", "-t", rem.target] + inner

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

def push_project(rem: Remote, uid: str, entry: dict, *, progress: bool = False,
                 dry: bool = False) -> dict:
    """Make the remote copy of a project and of its history equal to what is
    here.  What the sync replaces or removes over there is set aside first."""
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
                  their_home=str(Path.home()))
    res["project"] = rem.rsync(real + "/", rem.spec(rpath + "/"), delete=True,
                               backup_dir=aside + "/project", skip=handover_skip(),
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
                              include=inc, dry=dry)
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
            rem.agent("prune", dir=os.path.dirname(aside), keep=5)
        except HandoverError:
            pass
    return res

# ---- mirror ------------------------------------------------------------------ #

def mirror_due(entry: dict, now: float = None) -> bool:
    m = entry.get("mirror") or {}
    if not m.get("enabled") or entry.get("away"):
        return False
    try:
        every = float(cfg_get("mirror_interval_minutes", 30)) * 60
    except Exception:
        every = 1800.0
    last = max(float(m.get("synced_at") or 0), float(m.get("tried_at") or 0))
    return (now or time.time()) - last >= every

def mirror_project(uid: str, entry: dict, progress: bool = False) -> dict:
    real = os.path.realpath(entry["real_path"])
    m = dict(entry.get("mirror") or {})
    row = {"project": real, "remote": m.get("remote")}
    m["tried_at"] = time.time()
    try:
        if entry.get("away"):
            raise HandoverError("handed over: the other machine holds the live copy")
        if not os.path.isdir(real):
            raise HandoverError("the folder is missing")
        with ProjectLock(uid):
            rem = get_remote(m.get("remote"))
            rem.connect(real)
            row["remote"] = rem.name
            if rem.info.get("sessions") or rem.info.get("processes"):
                raise HandoverError(f"something is running in it on {rem.name}")
            if not rem.info.get("path_writable"):
                raise HandoverError(f"{rem.info.get('path_base')} is not writable "
                                    f"on {rem.name}")
            r = push_project(rem, uid, entry, progress=progress)
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
    _update_entry(uid, mirror=m)
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
        rows.append(mirror_project(uid, e, progress=progress))
    return rows

def _spawn_mirror() -> None:
    """From the watcher and the hook: sync what is due, detached, one run at
    a time."""
    try:
        if os.environ.get("AHT_NO_MIRROR") or not handover_supported():
            return
        reg = load_registry()
        if not any(mirror_due(e) for e in reg.get("projects", {}).values()):
            return
        subprocess.Popen([sys.executable or "python3", str(Path(__file__).resolve()),
                          "mirror", "--run", "--due", "--quiet"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True,
                         start_new_session=True, cwd="/")
    except Exception:
        pass

def cmd_mirror(args):
    if not handover_supported():
        print("mirroring needs rsync and ssh; it is not available in this build")
        return 2
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
                  + ("   [handed over]" if r["away"] else ""))
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
        entry = dict(entry or {"real_path": real})
        uid = uid or "untracked"
        if entry.get("away"):
            a = entry["away"]
            out["blockers"].append(f"already handed over to {a.get('remote')} since "
                                   f"{a.get('since')} — take it back first:  aht reclaim")
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
            lines.append("(dry run — pass --apply to do it)")
            return _emit(args, out, lines)

        # (4) do it
        with ProjectLock(uid):
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
                                      info.get("system"), carried, scratch)
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
                    else {"files": {}, "raw": {}}}
            lost = sorted(set(ours["project"]["files"]) - set(theirs["project"]["files"]))
            if lost:
                out["warnings"].append(f"{len(lost)} file(s) did not arrive, e.g. {lost[0]}")
            hashes = {k: [v[0], file_sha256(Path(store) / (ours["history"]["raw"].get(k) or k))]
                      for k, v in ours["history"]["files"].items()
                      if k.endswith(".jsonl") and isinstance(v[0], int)} if store else {}
            hd = handover_dir(uid)
            hd.mkdir(parents=True, exist_ok=True)
            (hd / "manifest.json").write_text(json.dumps({
                "uuid": uid, "project": real, "remote": rem.name, "at": _now(),
                "here": {k: v["files"] for k, v in ours.items()},
                "there": {k: v["files"] for k, v in theirs.items()},
                "transcripts": hashes}))

            away = {"remote": rem.name, "host": info.get("host"), "since": _now(),
                    "path": real, "session": sid, "window": _mux_name(real, uid),
                    "mux": "byobu" if tools.get("byobu") else "tmux",
                    "claude": here_ver}
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
                st = rem.agent("start", timeout=90, path=rem.path(real), session=sid,
                               name=away["window"], claude=info["claude"], note=note,
                               args=list(cfg_get("handover_claude_args") or []),
                               remote_control=os.path.basename(real)
                               if cfg_get("handover_remote_control", True) else None)
                away["mux"] = st.get("mux") or away["mux"]
                out["started"] = st.get("started")
                out["screen"] = st.get("screen")
                if st.get("attention"):
                    out["warnings"].append(f"the session on {rem.name} needs you: "
                                           f"{st['attention']} — open it to answer")
            _update_entry(uid, away=away, extras=extras or None)
        out["applied"] = True
        out["away"] = away
        out["attach"] = attach_command(rem, away["mux"], away["window"])
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

def _set_aside(path: Path, aside: Path, rel: str) -> None:
    dst = aside / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    os.replace(path, dst)

def _pull_tree(rem: Remote, plan: dict, src: str, dst: str, there_raw: dict,
               aside: Path, there: str, inert: bool, skip, progress: bool) -> dict:
    """Carry out one three-way plan: fetch what changed there, set aside what
    it replaces, and keep both versions of what changed on both sides."""
    done = {"updated": 0, "new": 0, "deleted": 0, "conflicts": [], "kept": len(plan["kept"])}
    name = lambda k: there_raw.get(k) or k
    fetch = [name(k) for k in plan["take"] + plan["new"]]
    if fetch:
        aside.mkdir(parents=True, exist_ok=True)
        r = rem.rsync(rem.spec(src + "/"), dst + "/", files_from=fetch,
                      backup_dir=str(aside), skip=skip, progress=progress)
        if not r["ok"]:
            raise HandoverError("fetching the changes failed: " + r["error"])
        done["updated"], done["new"] = len(plan["take"]), len(plan["new"])
    for k in plan["delete"]:
        p = Path(dst) / k
        if p.exists() or p.is_symlink():
            _set_aside(p, aside, k)
            done["deleted"] += 1
    if plan["conflict"]:
        inc = aside.parent / (aside.name + "-incoming")
        inc.mkdir(parents=True, exist_ok=True)
        r = rem.rsync(rem.spec(src + "/"), str(inc) + "/",
                      files_from=[name(k) for k in plan["conflict"]], skip=skip)
        if not r["ok"]:
            raise HandoverError("fetching the conflicting files failed: " + r["error"])
        day = time.strftime("%Y-%m-%d")
        for k in plan["conflict"]:
            got = next((c for c in (inc / k, inc / name(k)) if c.exists()), None)
            mine = Path(dst) / k
            if got is None:
                continue
            if mine.is_file() and got.is_file() and \
                    file_sha256(mine) == file_sha256(got):
                continue                        # changed alike on both sides
            rel = (k + f".aht-conflict-{there}-{_stamp()}") if inert \
                else _conflict_name(k, there, day)
            (Path(dst) / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(got), str(Path(dst) / rel))
            done["conflicts"].append({"file": k, "their_version": rel})
        shutil.rmtree(inc, ignore_errors=True)
    return done

def cmd_reclaim(args):
    out = {"command": "reclaim", "applied": False, "blockers": [], "warnings": []}
    lines = []
    if not handover_supported():
        out["blockers"].append("handover needs rsync and ssh; it is not available "
                               "in this build")
        return _emit(args, out, lines)
    real = os.path.realpath(args.path)
    out["project"] = real
    talk = not args.json
    prog = Progress(args.status_file, talk)
    say = prog.say
    try:
        reg = load_registry()
        uid, entry = _entry_for(reg, real)
        away = (entry or {}).get("away")
        if not away:
            out["blockers"].append("this project is not handed over")
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
                else {"files": {}, "raw": {}}}
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
            done = {"project": _pull_tree(rem, pp, rem.path(real), real,
                                          theirs["project"]["raw"], aside / "project",
                                          there, False, handover_skip(),
                                          talk and sys.stderr.isatty())}
            Path(store).mkdir(parents=True, exist_ok=True)
            done["history"] = _pull_tree(rem, hp, rstore, str(store),
                                         theirs["history"]["raw"], aside / "history",
                                         there, True, [], False)
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
            try:
                (hd / "manifest.json").replace(hd / f"manifest-{_stamp()}.json")
                for old in sorted(hd.glob("manifest-*.json"))[:-5]:
                    old.unlink()
                for old in sorted(p for p in (hd / "replaced").iterdir()
                                  if p.is_dir())[:-5]:
                    shutil.rmtree(old, ignore_errors=True)
            except OSError:
                pass
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
    ts = os.environ.get("AHT_TAILSCALE") or find_tool("tailscale") or next(
        (c for c in ("/Applications/Tailscale.app/Contents/MacOS/Tailscale",)
         if os.path.exists(c)), None)
    if ts:
        try:
            r = subprocess.run([ts, "status", "--json"], capture_output=True,
                               text=True, timeout=15, cwd="/")
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
    there = rem.agent("probe", path=home)
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

def cmd_remote(args):
    if not handover_supported():
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
        rem = Remote(args.name, {"ssh": args.target})
        try:
            info = rem.connect()
        except HandoverError as e:
            print(f"✗ {e}", file=sys.stderr)
            return 1
        with Lock():
            cfg = load_config()
            rs = dict(cfg.get("remotes") or {})
            rs[args.name] = {"ssh": args.target}
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
                        if (e.get("away") or {}).get("remote") == args.name]
                if held:
                    print(f"{args.name} still holds {len(held)} handed-over project(s); "
                          "take them back first:\n   " + "\n   ".join(held),
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
            try:
                rem = get_remote(n)
                info = rem.connect()
                rows = remote_checks(rem, info)
                results.append({"remote": rem.name, "target": rem.target, "checks": rows,
                                "ok": all(c["ok"] for c in rows if c["needed"])})
            except HandoverError as e:
                results.append({"remote": n, "ok": False, "error": str(e), "checks": []})
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

def open_terminal(command: str, name: str) -> int:
    """Run `command` in a new terminal window (the front-ends use this)."""
    run = aht_home() / "run"
    run.mkdir(parents=True, exist_ok=True)
    if IS_MAC:
        f = run / (re.sub(r"[^A-Za-z0-9_.-]+", "-", name) + ".command")
        f.write_text("#!/bin/bash\n"
                     'export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"\n'
                     "clear\n" + command + "\n")
        os.chmod(f, 0o755)
        app = cfg_get("terminal_app") or (
            "iTerm" if os.path.isdir("/Applications/iTerm.app") else None)
        return subprocess.call(["open"] + (["-a", str(app)] if app else []) + [str(f)])
    for term, flag in (("x-terminal-emulator", "-e"), ("gnome-terminal", "--"),
                       ("konsole", "-e"), ("xterm", "-e")):
        if _have(term):
            subprocess.Popen([term, flag, "/bin/sh", "-c", command],
                             start_new_session=True)
            return 0
    print(command)
    return 1

def cmd_resume_here(args):
    """Continue a project's session in a new terminal window: the one used
    last, or (--handed-over) the one the last handover sent away."""
    real = os.path.realpath(args.path)
    _uid, entry = _entry_for(load_registry(), real)
    back = (entry or {}).get("returned") or {}
    sid = latest_session(_store_of(real))
    if args.handed_over:
        sid = back.get("handed_over") or back.get("session") or sid
    exe = find_claude() or "claude"
    cmd = f"cd {shlex.quote(real)} && exec {shlex.quote(exe)}" \
        + (f" --resume {sid}" if sid else "")
    if args.print:
        print(cmd)
        return 0
    return open_terminal(cmd, "resume-" + os.path.basename(real))

def handover_status() -> dict:
    reg = load_registry()
    away, mirrored = [], []
    for e in reg.get("projects", {}).values():
        if e.get("away"):
            away.append({"project": e["real_path"], **e["away"]})
        m = e.get("mirror") or {}
        if m.get("enabled"):
            mirrored.append({"project": e["real_path"], "remote": m.get("remote"),
                             "synced_at": m.get("synced_at"), "status": m.get("status")})
    rs = find_rsync() if handover_supported() else {}
    rs_cfg = remotes_config()
    return {"supported": handover_supported(),
            "remotes": rs_cfg,
            "default_remote": cfg_get("default_remote") if cfg_get("default_remote")
            in rs_cfg else (sorted(rs_cfg)[0] if rs_cfg else None),
            "rsync": rs.get("version"), "away": away, "mirrored": mirrored}

def _hook_notes(cwd: str) -> None:
    """What a session that starts here must know about a handover; printed to
    stdout, which Claude Code adds to the session's context."""
    try:
        reg = load_registry()
        uid, entry = _entry_for(reg, cwd)
        if not entry:
            return
        a, b = entry.get("away"), entry.get("returned")
        if a:
            print(f"[aht] WARNING: this project was handed over to “{a.get('host')}” on "
                  f"{a.get('since')} and is being worked on there. Changes made here "
                  "now can collide with that work. Tell the user before changing "
                  "anything, and suggest taking the project back first (aht reclaim).")
            notify_user("Project is handed over",
                        f"{os.path.basename(cwd)} runs on {a.get('host')} — "
                        "take it back before working here")
        elif b and not b.get("told"):
            msg = (f"[aht] This project is back on “{_here()}”. It ran on "
                   f"“{b.get('from')}” from {b.get('left')} to {b.get('at')}; the "
                   f"changes made there were brought back ({b.get('updated', 0)} "
                   f"file(s) updated, {b.get('new', 0)} new, {b.get('deleted', 0)} "
                   "removed).")
            if b.get("conflicts"):
                msg += (" Changed on BOTH machines, so both versions were kept: "
                        + ", ".join(b["conflicts"][:8]) + ".")
            print(msg)
            _update_entry(uid, returned=dict(b, told=True))
    except Exception as e:
        warn(f"HOOK handover note: {e}")

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
    s.add_argument("--roots", nargs="*")
    s.set_defaults(fn=cmd_adopt)

    s = sub.add_parser("suggest-matches")
    s.add_argument("--store", required=True, dest="store")
    s.add_argument("--roots", nargs="*")
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
    s.add_argument("--news", choices=POLICY_CHOICES["news"])
    s.add_argument("--only", nargs="*", metavar="PATH")
    s.add_argument("--clear-declines", action="store_true", dest="clear_declines")
    s.add_argument("--roots", nargs="*")
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
    s.add_argument("--roots", nargs="*")
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
    s.add_argument("--set", nargs="*", metavar="KEY=VALUE")
    s.add_argument("--unset", nargs="*", metavar="KEY")
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
    s.add_argument("--set-root", nargs="*", metavar="NAME=PATH",
                   dest="set_root")
    s.add_argument("--clear-root", nargs="*", metavar="NAME",
                   dest="clear_root")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_backends)

    s = sub.add_parser("version"); s.set_defaults(fn=cmd_version)

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
    s.add_argument("--add", nargs="*")
    s.add_argument("--remove", nargs="*")
    s.add_argument("--no-reload", action="store_true")
    s.set_defaults(fn=cmd_roots)

    s = sub.add_parser("reload")
    s.set_defaults(fn=cmd_reload)

    s = sub.add_parser("icons")
    s.add_argument("--refresh", action="store_true")
    s.add_argument("--roots", nargs="*")
    s.set_defaults(fn=cmd_icons)

    s = sub.add_parser("backup")
    s.add_argument("--auto", action="store_true")
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
    s.set_defaults(fn=cmd_remote)

    s = sub.add_parser("mirror", help="keep a project's copy on the other "
                       "machine up to date in the background")
    s.add_argument("path", nargs="?")
    s.add_argument("--to", metavar="NAME")
    s.add_argument("--on", action="store_true")
    s.add_argument("--off", action="store_true")
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
    s.add_argument("--include", nargs="*", metavar="PATH",
                   help="files or folders outside the project that travel along "
                        "(remembered for this project)")
    s.add_argument("--no-start", action="store_true", dest="no_start",
                   help="transfer only; start the agent there yourself")
    s.add_argument("--attach", action="store_true",
                   help="open the session in this terminal afterwards")
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
    s.add_argument("--print", action="store_true")
    s.set_defaults(fn=cmd_resume_here)

    s = sub.add_parser("_agent")           # the far end of a handover (stdin: JSON)
    s.set_defaults(fn=cmd_agent)

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
