#!/usr/bin/env python3
"""
aht tray for Linux — the OPTIONAL system-tray companion, the counterpart
of the macOS menu bar app and the Windows aht-tray.exe.

This is the one aht component with a desktop dependency, because Linux
tray icons speak StatusNotifierItem over D-Bus, which the Python stdlib
cannot.  It uses PyGObject + an AppIndicator typelib WHEN PRESENT and exits
with a clear message otherwise — the CLI keeps full feature parity either way.

    Debian/Ubuntu:  sudo apt install python3-gi gir1.2-ayatanaappindicator3-0.1
    Fedora:         sudo dnf install python3-gobject libayatana-appindicator-gtk3
    Arch:           sudo pacman -S python-gobject libayatana-appindicator

GNOME hides tray icons by default — the "AppIndicator and KStatusNotifierItem
Support" shell extension is needed to SEE the icon there.  KDE/XFCE/Cinnamon
show it out of the box.

Like the other front-ends, this is a FRONT-END only: every action drives the
same shared core, config and registry as the CLI, the hook and the systemd
watcher, so they can never disagree.  Watching stays in the systemd user unit;
the tray pauses/resumes it via systemctl.

    python3 tray.py            run the tray
    python3 tray.py --check    verify dependencies + core wiring, then exit
                               (0 = tray would run, 3 = desktop deps missing)
"""
import fcntl
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

# --------------------------------------------------------------------------- #
# Locate and import the shared core (same rules as watcher.py)
# --------------------------------------------------------------------------- #

def _find_core() -> Path:
    here = Path(__file__).resolve().parent
    for c in (here / "aht.py", here.parent / "aht.py",
              Path.home() / ".aht/tools/agent-history-tether/aht.py"):
        if c.is_file():
            return c
    raise SystemExit("tray: cannot find aht.py")

CORE = _find_core()
sys.path.insert(0, str(CORE.parent))
import aht  # noqa: E402

CORAL = (217, 119, 87)
GRAY = (140, 140, 140)
ICON_ACTIVE, ICON_PAUSED = "aht-tray", "aht-tray-paused"
AUTOSTART = Path.home() / ".config/autostart/aht-tray.desktop"


def run_cli(*args):
    return subprocess.run([sys.executable, str(CORE), *args],
                          capture_output=True, text=True)


def _set_shared(key, value):
    """Write one shared config key through the same lock + file the CLI uses."""
    with aht.Lock():
        cfg = aht.load_config()
        cfg[key] = value
        aht.save_config(cfg)


def notify(title, msg):
    try:
        if shutil.which("notify-send"):
            subprocess.run(["notify-send", "-a", "aht", title, str(msg)],
                           capture_output=True, timeout=10)
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Icon generation (the aht loop as a small PNG, via the core's rasteriser)
# --------------------------------------------------------------------------- #

def write_icons() -> Path:
    d = aht.aht_home() / "aht-icons"
    d.mkdir(parents=True, exist_ok=True)
    for name, rgb in ((ICON_ACTIVE, CORAL), (ICON_PAUSED, GRAY)):
        # always rewritten: it is tiny, and a stale file would keep an old mark
        (d / f"{name}.png").write_bytes(aht._png_bytes(22, aht.infinity_rgba(22, rgb)))
    return d


# --------------------------------------------------------------------------- #
# Desktop dependencies (optional by design)
# --------------------------------------------------------------------------- #

DEPS_HINT = ("the tray needs PyGObject + an AppIndicator typelib:\n"
             "  Debian/Ubuntu: sudo apt install python3-gi "
             "gir1.2-ayatanaappindicator3-0.1\n"
             "  Fedora:        sudo dnf install python3-gobject "
             "libayatana-appindicator-gtk3\n"
             "  Arch:          sudo pacman -S python-gobject "
             "libayatana-appindicator\n"
             "(GNOME also needs the 'AppIndicator Support' shell extension "
             "to show tray icons.)\n"
             "Everything the tray does is also available from the CLI: "
             "aht --help")


def load_gi():
    """-> (Gtk, GLib, AppIndicator) or (None, None, reason)."""
    try:
        import gi
    except ImportError:
        return None, None, "PyGObject (python3-gi) is not installed"
    try:
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk, GLib
    except Exception as e:
        return None, None, f"GTK 3 is not available ({e})"
    for ns in ("AyatanaAppIndicator3", "AppIndicator3"):
        try:
            gi.require_version(ns, "0.1")
            import importlib
            mod = importlib.import_module(f"gi.repository.{ns}")
            return Gtk, GLib, mod
        except Exception:
            continue
    return None, None, "no AppIndicator typelib (ayatana or classic) found"


# --------------------------------------------------------------------------- #
# Watcher control (the systemd user unit owns watching, exactly as installed)
# --------------------------------------------------------------------------- #

def watcher_state():
    st = aht.watcher_status()
    can_toggle = (st.get("kind") == "systemd-user"
                  and shutil.which("systemctl") is not None)
    return bool(st.get("running")), bool(st.get("installed")), can_toggle


def watcher_set(running: bool):
    subprocess.run(["systemctl", "--user",
                    "start" if running else "stop", aht.LINUX_UNIT],
                   capture_output=True, timeout=20)


# --------------------------------------------------------------------------- #
# The tray app
# --------------------------------------------------------------------------- #

class Tray:
    def __init__(self, Gtk, GLib, AppIndicator):
        self.Gtk, self.GLib, self.AI = Gtk, GLib, AppIndicator
        self.ind = AppIndicator.Indicator.new(
            "aht", ICON_ACTIVE,
            AppIndicator.IndicatorCategory.APPLICATION_STATUS)
        self.ind.set_icon_theme_path(str(write_icons()))
        self.ind.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self.last_running = None
        self.refresh()
        GLib.timeout_add_seconds(15, self._tick)

    # ---- plumbing ----

    def ui(self, fn, *a):
        self.GLib.idle_add(lambda: (fn(*a) and False) or False)

    def in_thread(self, fn):
        threading.Thread(target=fn, daemon=True).start()

    def _tick(self):
        self.refresh()
        return True

    def refresh(self):
        running, _installed, _ = watcher_state()
        if running != self.last_running:
            self.last_running = running
            self.ind.set_icon_full(
                ICON_ACTIVE if running else ICON_PAUSED, "aht")
        self.ind.set_menu(self.build_menu())

    def dialog(self, title, body, question=False):
        Gtk = self.Gtk
        d = Gtk.MessageDialog(
            transient_for=None, flags=0,
            message_type=Gtk.MessageType.QUESTION if question
            else Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.YES_NO if question else Gtk.ButtonsType.OK,
            text=title)
        d.format_secondary_text(body)
        d.set_keep_above(True)
        resp = d.run()
        d.destroy()
        return resp == Gtk.ResponseType.YES

    # ---- menu ----

    def build_menu(self):
        Gtk = self.Gtk
        running, installed, can_toggle = watcher_state()
        reg = aht.load_registry()
        projects = reg.get("projects", {})
        n = len(projects)
        missing = sum(1 for e in projects.values()
                      if not os.path.isdir(e["real_path"]))
        hook = aht.hook_installed()

        menu = Gtk.Menu()

        def add(label, cb=None, checked=None, sensitive=True, parent=menu):
            if checked is None:
                item = Gtk.MenuItem(label=label)
            else:
                item = Gtk.CheckMenuItem(label=label)
                item.set_active(bool(checked))
            item.set_sensitive(sensitive and cb is not None)
            if cb is not None:
                item.connect("activate", cb)
            parent.append(item)
            return item

        def sep(parent=menu):
            parent.append(Gtk.SeparatorMenuItem())

        def submenu(label, parent=menu):
            item = Gtk.MenuItem(label=label)
            m = Gtk.Menu()
            item.set_submenu(m)
            parent.append(item)
            return m

        add(f"aht {aht.VERSION} — "
            f"{'watching' if running else 'PAUSED'}")
        line = f"{n} tracked project(s)"
        if missing:
            line += f" · {missing} missing"
        if not hook:
            line += " · hook MISSING"
        add(line)
        sep()

        add("Reconcile now", self.act_reconcile)
        add("Pause watching" if running else "Resume watching",
            self.act_toggle_watch,
            sensitive=can_toggle and (installed or running))
        sep()

        recent = submenu("Recent projects")
        rows = sorted(projects.values(),
                      key=lambda e: e.get("updated_at") or "", reverse=True)[:10]
        if not rows:
            add("No tracked projects yet", parent=recent)
        for e in rows:
            p = e["real_path"]
            name = os.path.basename(p) or p
            if not os.path.isdir(p):
                name += "  (missing)"
            add(name, self._open_path_cb(p), parent=recent)

        add("Adopt this machine's projects…", self.act_adopt)
        sep()

        settings = submenu("Settings")
        for key, choices, title, default in (
                ("move_policy",
                 [("ask", "Ask me"), ("apply", "Relink automatically"),
                  ("decline", "Never relink (remember the no)"),
                  ("ignore", "Do nothing")],
                 "When a folder moves", "ask"),
                ("copy_policy",
                 [("ask", "Ask me"), ("duplicate", "Duplicate the history"),
                  ("independent", "Fresh identity, no history"),
                  ("ignore", "Do nothing")],
                 "When a folder is copied", "ask"),
                ("new_policy",
                 [("apply", "Start tracking it"), ("ignore", "Leave it alone")],
                 "When a new project is found", "apply")):
            cur = aht.cfg_get(key, default)
            m = submenu(title, parent=settings)
            for val, label in choices:
                add(label, self._policy_cb(key, val, f"{title}: {label}"),
                    checked=(cur == val), parent=m)
        add("Notifications", self._toggle_cb("notifications", True),
            checked=bool(aht.cfg_get("notifications", True)), parent=settings)
        add("Auto-backup histories", self._toggle_cb("backup_enabled", True),
            checked=bool(aht.cfg_get("backup_enabled", True)), parent=settings)
        add("Back up histories now", self.act_backup_now, parent=settings)
        sep(settings)
        locations = submenu("Agent CLI locations", parent=settings)
        for brow in aht.backend_status():
            t = f"{brow['name']} — {'found' if brow['available'] else 'NOT FOUND'}"
            if brow.get("root_source", "default") != "default":
                t += f"  [{brow['root_source']}]"
            add(t, self._pick_backend_root_cb(brow["name"]), parent=locations)
        sep(locations)
        add("Reset all to defaults", self.act_reset_backend_roots,
            parent=locations)
        add("Edit config file", self._open_path_cb(str(aht.config_path()),
                                                   ensure_config=True),
            parent=settings)
        add("Restart watcher (apply config)", self.act_restart, parent=settings)

        badges = submenu("Folder emblems")
        add("Emblems on folders", self._toggle_cb("icons_enabled", True),
            checked=bool(aht.cfg_get("icons_enabled", True)), parent=badges)
        add("Agent symbols", self._toggle_cb("icons_agent", True),
            checked=bool(aht.cfg_get("icons_agent", True)), parent=badges)
        add("Git emblem", self._toggle_cb("icons_git", True),
            checked=bool(aht.cfg_get("icons_git", True)), parent=badges)
        sep(badges)
        add("Refresh all emblems", self.act_refresh_icons, parent=badges)
        add("Clear all emblems…", self.act_clear_icons, parent=badges)
        sep()

        add("Run diagnostics", self.act_doctor)
        add("Open data folder (.claude)",
            self._open_path_cb(str(aht.aht_home())))
        add("Open log", self._open_path_cb(str(aht.log_path())))
        sep()

        add("Start tray at logon", self.act_toggle_autostart,
            checked=AUTOSTART.is_file())
        add("About aht", self.act_about)
        sep()

        add("Quit tray (watcher keeps running)" if running else "Quit tray",
            self.act_quit)

        menu.show_all()
        return menu

    # ---- actions ----

    def _open_path_cb(self, path, ensure_config=False):
        def cb(_item):
            if ensure_config:
                aht.ensure_config()
            subprocess.Popen(["xdg-open", path])
        return cb

    def _policy_cb(self, key, value, label):
        def cb(_item):
            _set_shared(key, value)
            notify("Settings", label)
            self.refresh()
        return cb

    def _toggle_cb(self, key, default):
        def cb(_item):
            new = not aht.cfg_get(key, default)
            _set_shared(key, new)
            notify("Settings", f"{key}: {'on' if new else 'off'}")
            self.refresh()
        return cb

    def act_reconcile(self, _item):
        def work():
            r = run_cli("reconcile", "--notify")
            try:
                d = json.loads(r.stdout or "{}")
                am = len(d.get("applied_moves", []))
                ac = len(d.get("applied_copies", []))
                if am or ac:
                    msg = f"{am} project(s) relinked, {ac} histor(ies) copied"
                elif d.get("moves") or d.get("copies"):
                    msg = "Changes found — answered via dialog or deferred"
                else:
                    msg = "Nothing to do — every history is in place"
            except Exception:
                msg = "Reconcile finished" if r.returncode == 0 \
                    else f"Reconcile failed (exit {r.returncode})"
            notify("Reconcile", msg)
            self.ui(self.refresh)
        self.in_thread(work)

    def act_toggle_watch(self, _item):
        running, _i, _c = watcher_state()
        def work():
            watcher_set(not running)
            notify("Watcher", "Paused — the SessionStart hook still protects "
                   "projects you open" if running else "Watching resumed")
            self.ui(self.refresh)
        self.in_thread(work)

    def act_adopt(self, _item):
        def scan():
            r = run_cli("adopt", "--json")
            try:
                d = json.loads(r.stdout or "{}")
            except Exception:
                self.ui(self.dialog, "Adopt", "Could not scan: "
                        + (r.stderr or f"exit {r.returncode}")[:400])
                return
            self.ui(self._adopt_confirm, d)
        self.in_thread(scan)

    def _adopt_confirm(self, d):
        planned = len(d.get("planned", []))
        already = int(d.get("already", 0))
        orphans = int(d.get("orphans_claude", 0))
        if not planned:
            self.dialog("Nothing to adopt",
                        f"{already} project(s) already tracked; {orphans} "
                        "orphan histor(ies) — reconnect those with:  "
                        "aht orphans --match")
            return
        if not self.dialog(
                f"Start tracking {planned} existing project(s)?",
                "Each folder gets a marker file (.aht/.project-id) and a "
                "registry entry so its history follows it from now on.\n"
                "Nothing is moved, renamed or deleted.", question=True):
            return
        def apply():
            r = run_cli("adopt", "--apply", "--json")
            notify("Adopt", f"{planned} project(s) are now tracked"
                   if r.returncode == 0 else f"Adopt failed ({r.returncode})")
            self.ui(self.refresh)
        self.in_thread(apply)

    def act_backup_now(self, _item):
        def work():
            r = run_cli("backup", "--json")
            try:
                counts = json.loads(r.stdout or "{}").get("counts", {})
                msg = ", ".join(f"{v} {k}" for k, v in sorted(counts.items())) \
                    or "nothing to back up"
            except Exception:
                msg = "Backup finished" if r.returncode == 0 \
                    else f"Backup failed (exit {r.returncode})"
            notify("History backup", msg)
        self.in_thread(work)

    def act_restart(self, _item):
        def work():
            r = run_cli("reload")
            notify("Watcher", (r.stdout or "reloaded").strip().splitlines()[-1]
                   if r.stdout else "reloaded")
            self.ui(self.refresh)
        self.in_thread(work)

    def act_refresh_icons(self, _item):
        def work():
            r = run_cli("icons", "--refresh")
            last = (r.stdout or "").strip().splitlines()
            notify("Folder emblems", last[-1] if last else "refreshed")
        self.in_thread(work)

    def act_clear_icons(self, _item):
        if not self.dialog("Clear every folder emblem?",
                           "Removes the claude/git emblems from tracked "
                           "folders. Projects and history are not affected; "
                           "emblems come back if you re-enable them.",
                           question=True):
            return
        def work():
            saved = {k: aht.cfg_get(k, True)
                     for k in ("icons_enabled", "icons_agent", "icons_git")}
            _set_shared("icons_enabled", True)
            _set_shared("icons_agent", False)
            _set_shared("icons_git", False)
            try:
                run_cli("icons", "--refresh")
            finally:
                for k, v in saved.items():
                    _set_shared(k, bool(v))
            notify("Folder emblems", "Cleared")
        self.in_thread(work)

    def act_doctor(self, _item):
        def work():
            r = run_cli("doctor")
            self.ui(self.dialog, "Diagnostics",
                    (r.stdout or r.stderr or "doctor failed")[:1800])
        self.in_thread(work)

    def _pick_backend_root_cb(self, name):
        def cb(_item):
            Gtk = self.Gtk
            d = Gtk.FileChooserDialog(
                title=f"Choose the {name} history store folder",
                action=Gtk.FileChooserAction.SELECT_FOLDER)
            d.add_buttons("Cancel", Gtk.ResponseType.CANCEL,
                          "Select", Gtk.ResponseType.OK)
            d.set_show_hidden(True)          # the stores live in dot-folders
            resp = d.run()
            path = d.get_filename() if resp == Gtk.ResponseType.OK else None
            d.destroy()
            if not path:
                return
            def work():
                run_cli("backends", "--set-root", f"{name}={path}")
                notify("Agent CLI locations", f"{name} → {path}")
                self.ui(self.refresh)
            self.in_thread(work)
        return cb

    def act_reset_backend_roots(self, _item):
        if not self.dialog("Reset every agent CLI location to its default?",
                           "Only the store paths aht looks at are reset — "
                           "no history is touched.", question=True):
            return
        def work():
            names = [b["name"] for b in aht.backend_status()]
            run_cli("backends", "--clear-root", *names)
            notify("Agent CLI locations", "Reset to defaults")
            self.ui(self.refresh)
        self.in_thread(work)

    def act_toggle_autostart(self, _item):
        if AUTOSTART.is_file():
            AUTOSTART.unlink()
            notify("Autostart", "The tray no longer starts at logon")
        else:
            AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
            AUTOSTART.write_text(
                "[Desktop Entry]\nType=Application\nName=aht tray\n"
                f"Exec={sys.executable} {Path(__file__).resolve()}\n"
                "X-GNOME-Autostart-enabled=true\n")
            notify("Autostart", "The tray starts at logon")
        self.refresh()

    def act_about(self, _item):
        self.dialog(
            f"aht {aht.VERSION} — agent-history-tether",
            "Keeps every AI coding agent's per-project history connected "
            "to its folder when you move, rename, copy or nest that folder.\n\n"
            "This tray, the aht CLI, the SessionStart hook and the "
            "systemd watcher all drive the same core, registry and config — "
            f"they can never disagree.\n\nData: {aht.aht_home()}\n"
            "History is never deleted or overwritten.")

    def act_quit(self, _item):
        self.Gtk.main_quit()


# --------------------------------------------------------------------------- #
# Entry
# --------------------------------------------------------------------------- #

def check() -> int:
    print(f"core   : {CORE}  (aht {aht.VERSION})")
    icons = write_icons()
    print(f"icons  : {icons}  "
          f"({', '.join(p.name for p in sorted(icons.glob('*.png')))})")
    running, installed, can_toggle = watcher_state()
    print(f"watcher: installed={installed} running={running} "
          f"pause/resume={'yes' if can_toggle else 'no (no systemd unit)'}")
    Gtk, GLib, AI = load_gi()
    if Gtk is None:
        print(f"desktop: MISSING — {AI}\n{DEPS_HINT}")
        return 3
    print(f"desktop: OK ({AI.__name__})")
    return 0


def main() -> int:
    if "--check" in sys.argv[1:]:
        return check()
    Gtk, GLib, AI = load_gi()
    if Gtk is None:
        print(f"aht-tray: {AI}\n{DEPS_HINT}", file=sys.stderr)
        return 3
    # single instance (auto-released if the process dies)
    aht.aht_home().mkdir(parents=True, exist_ok=True)
    lockfile = open(aht.aht_home() / ".aht-tray.lock", "w")
    try:
        fcntl.flock(lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("aht-tray: already running", file=sys.stderr)
        return 0
    Tray(Gtk, GLib, AI)
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
