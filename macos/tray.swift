// aht-tray — the macOS menu bar companion of agent-history-tether.
//
// A FRONT-END only: every action shells out to the same aht.py core the CLI,
// the hook and the LaunchAgent watcher use, so no front-end can disagree with
// another.  Compiled by install.py (swiftc, no dependencies); menu parity with
// the Windows tray (windows/src/aht_tray.py) and the Linux tray (linux/tray.py).
//
//   run:            ~/.aht/tools/agent-history-tether/aht-tray &
//   start at login: toggle it in the menu (writes a LaunchAgent)
import AppKit
import Foundation

let HOME = NSHomeDirectory()
let TOOLS = HOME + "/.aht/tools/agent-history-tether"
let PY = "/usr/bin/python3"
let WATCHER_LABEL = "com.aht.watcher"
let TRAY_LABEL = "com.aht.tray"
let TRAY_PLIST = HOME + "/Library/LaunchAgents/\(TRAY_LABEL).plist"
let WATCHER_PLIST = HOME + "/Library/LaunchAgents/\(WATCHER_LABEL).plist"

func ahtScript() -> String {
    let fm = FileManager.default
    let candidates = [
        TOOLS + "/aht.py",
        URL(fileURLWithPath: CommandLine.arguments[0]).deletingLastPathComponent()
            .appendingPathComponent("aht.py").path,
        URL(fileURLWithPath: CommandLine.arguments[0]).deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent("aht.py").path,
    ]
    for c in candidates where fm.fileExists(atPath: c) { return c }
    return TOOLS + "/aht.py"
}

@discardableResult
func sh(_ exe: String, _ args: [String]) -> (ok: Bool, out: String) {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: exe)
    p.arguments = args
    let out = Pipe()
    p.standardOutput = out
    p.standardError = Pipe()
    do { try p.run() } catch { return (false, "") }
    let data = out.fileHandleForReading.readDataToEndOfFile()
    p.waitUntilExit()
    return (p.terminationStatus == 0, String(data: data, encoding: .utf8) ?? "")
}

@discardableResult
func aht(_ args: [String]) -> (ok: Bool, out: String) {
    return sh(PY, [ahtScript()] + args)
}

func ahtJSON(_ args: [String]) -> [String: Any]? {
    let r = aht(args)
    guard let d = r.out.data(using: .utf8) else { return nil }
    return (try? JSONSerialization.jsonObject(with: d)) as? [String: Any]
}

func notifyUser(_ title: String, _ msg: String) {
    let esc = { (s: String) in s.replacingOccurrences(of: "\\", with: "\\\\")
                               .replacingOccurrences(of: "\"", with: "\\\"") }
    sh("/usr/bin/osascript",
       ["-e", "display notification \"\(esc(msg))\" with title \"\(esc(title))\""])
}

func watcherRunning() -> Bool {
    let r = sh("/bin/launchctl", ["list"])
    return r.out.split(separator: "\n").contains {
        $0.split(separator: "\t").last.map(String.init)?
            .trimmingCharacters(in: .whitespaces) == WATCHER_LABEL
    }
}

// ---- cached state (menuNeedsUpdate must never block on subprocesses) -------

final class StateCache {
    var status: [String: Any] = [:]
    var config: [String: Any] = [:]
    var projects: [[String: Any]] = []
    var running = false
    private let q = DispatchQueue(label: "aht.tray.cache")

    func refresh(_ done: (() -> Void)? = nil) {
        q.async {
            let st = ahtJSON(["status", "--json"]) ?? [:]
            let cf = (ahtJSON(["config", "--json"])?["effective"] as? [String: Any]) ?? [:]
            let pj = (ahtJSON(["projects", "--json"])?["projects"] as? [[String: Any]]) ?? []
            let run = watcherRunning()
            DispatchQueue.main.async {
                self.status = st
                self.config = cf
                self.projects = pj
                self.running = run
                done?()
            }
        }
    }
}

// ---- the app ---------------------------------------------------------------

final class TrayApp: NSObject, NSApplicationDelegate, NSMenuDelegate {
    var item: NSStatusItem!
    let menu = NSMenu()
    let cache = StateCache()

    func applicationDidFinishLaunching(_ n: Notification) {
        item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        let img = NSImage(systemSymbolName: "sparkles",
                          accessibilityDescription: "aht")
        img?.isTemplate = true
        item.button?.image = img
        item.button?.toolTip = "agent-history-tether"
        menu.delegate = self
        item.menu = menu
        cache.refresh()
        Timer.scheduledTimer(withTimeInterval: 20, repeats: true) { _ in
            self.cache.refresh()
        }
    }

    func menuWillOpen(_ menu: NSMenu) { cache.refresh() }

    func menuNeedsUpdate(_ menu: NSMenu) {
        menu.removeAllItems()
        let st = cache.status
        let running = cache.running
        let tracked = st["tracked"] as? Int ?? 0
        let missing = st["missing"] as? Int ?? 0
        let hook = st["hook_installed"] as? Bool ?? false
        let ver = st["version"] as? String ?? "?"

        add(disabled: "aht \(ver) — \(running ? "watching" : "PAUSED")")
        var line = "\(tracked) tracked project" + (tracked == 1 ? "" : "s")
        if missing > 0 { line += " · \(missing) missing" }
        if !hook { line += " · hook MISSING" }
        add(disabled: line)
        if let backends = st["backends"] as? [[String: Any]] {
            let active = backends.filter {
                ($0["available"] as? Bool ?? false)
                && ($0["enabled"] as? Bool ?? false)
            }.compactMap { $0["name"] as? String }
            add(disabled: "agents here: "
                + (active.isEmpty ? "none detected" : active.joined(separator: " · ")))
        }
        menu.addItem(.separator())

        add("Reconcile Now", #selector(reconcile), key: "r")
        add(running ? "Pause Watching" : "Resume Watching", #selector(toggleWatch))
        menu.addItem(.separator())

        let recent = NSMenuItem(title: "Recent Projects", action: nil, keyEquivalent: "")
        let sub = NSMenu()
        let rows = cache.projects.sorted {
            (($0["updated_at"] as? String) ?? "") > (($1["updated_at"] as? String) ?? "")
        }.prefix(10)
        if rows.isEmpty { sub.addItem(mk(disabled: "No tracked projects yet")) }
        for p in rows {
            let path = p["real_path"] as? String ?? "?"
            var name = (path as NSString).lastPathComponent
            if !(p["exists"] as? Bool ?? true) { name += "  (missing)" }
            let i = NSMenuItem(title: name, action: #selector(revealProject(_:)),
                               keyEquivalent: "")
            i.target = self
            i.representedObject = path
            i.toolTip = path
            sub.addItem(i)
        }
        recent.submenu = sub
        menu.addItem(recent)
        add("Adopt This Mac's Projects…", #selector(adopt))
        menu.addItem(.separator())

        menu.addItem(settingsSubmenu())
        menu.addItem(badgesSubmenu())
        menu.addItem(.separator())

        add("Run Diagnostics", #selector(doctor))
        add("Open Data Folder (.aht)", #selector(openData))
        add("Open Log", #selector(openLog))
        menu.addItem(.separator())

        let login = mk("Start Tray at Login", #selector(toggleLogin))
        login.state = FileManager.default.fileExists(atPath: TRAY_PLIST) ? .on : .off
        menu.addItem(login)
        add("About aht", #selector(about))
        menu.addItem(.separator())
        add(running ? "Quit Tray (watcher keeps running)" : "Quit Tray",
            #selector(quit), key: "q")
    }

    // ---- submenu builders ----

    func settingsSubmenu() -> NSMenuItem {
        let root = NSMenuItem(title: "Settings", action: nil, keyEquivalent: "")
        let m = NSMenu()
        let cfg = cache.config
        let groups: [(String, String, [(String, String)])] = [
            ("move_policy", "When a Folder Moves",
             [("ask", "Ask Me"), ("apply", "Relink Automatically"),
              ("decline", "Never Relink (remember the no)"), ("ignore", "Do Nothing")]),
            ("copy_policy", "When a Folder Is Copied",
             [("ask", "Ask Me"), ("duplicate", "Duplicate the History"),
              ("independent", "Fresh Identity, No History"), ("ignore", "Do Nothing")]),
            ("new_policy", "When a New Project Is Found",
             [("apply", "Start Tracking It"), ("ignore", "Leave It Alone")]),
        ]
        for (key, title, choices) in groups {
            let gi = NSMenuItem(title: title, action: nil, keyEquivalent: "")
            let gm = NSMenu()
            let cur = cfg[key] as? String ?? choices[0].0
            for (val, label) in choices {
                let i = NSMenuItem(title: label, action: #selector(setPolicy(_:)),
                                   keyEquivalent: "")
                i.target = self
                i.representedObject = "\(key)=\(val)"
                i.state = (cur == val) ? .on : .off
                gm.addItem(i)
            }
            gi.submenu = gm
            m.addItem(gi)
        }
        m.addItem(toggleItem("Notifications", "notifications"))
        m.addItem(toggleItem("Auto-Backup Histories", "backup_enabled"))
        m.addItem(mk("Back Up Histories Now", #selector(backupNow)))
        m.addItem(.separator())
        m.addItem(locationsSubmenu())
        m.addItem(mk("Edit Config File", #selector(editConfig)))
        m.addItem(mk("Restart Watcher (apply config)", #selector(restartWatcher)))
        root.submenu = m
        return root
    }

    func locationsSubmenu() -> NSMenuItem {
        // the settings page for where each agent CLI keeps its history store —
        // for installs aht did not find automatically
        let root = NSMenuItem(title: "Agent CLI Locations", action: nil,
                              keyEquivalent: "")
        let m = NSMenu()
        let backends = (cache.status["backends"] as? [[String: Any]]) ?? []
        if backends.isEmpty { m.addItem(mk(disabled: "status not loaded yet")) }
        for b in backends {
            let name = b["name"] as? String ?? "?"
            let avail = b["available"] as? Bool ?? false
            let src = b["root_source"] as? String ?? "default"
            var title = "\(name) — \(avail ? "found" : "NOT FOUND")"
            if src != "default" { title += "  [\(src)]" }
            let i = NSMenuItem(title: title, action: #selector(pickBackendRoot(_:)),
                               keyEquivalent: "")
            i.target = self
            i.representedObject = name
            i.toolTip = (b["root"] as? String ?? "") + "\nClick to choose the store folder"
            m.addItem(i)
        }
        m.addItem(.separator())
        m.addItem(mk("Reset All to Defaults", #selector(resetBackendRoots)))
        root.submenu = m
        return root
    }

    @objc func pickBackendRoot(_ sender: NSMenuItem) {
        guard let name = sender.representedObject as? String else { return }
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.showsHiddenFiles = true          // the stores live in dot-folders
        panel.message = "Choose the \(name) history store folder"
        NSApp.activate(ignoringOtherApps: true)
        guard panel.runModal() == .OK, let url = panel.url else { return }
        background {
            aht(["backends", "--set-root", "\(name)=\(url.path)"])
            notifyUser("Agent CLI locations", "\(name) → \(url.path)")
        }
    }

    @objc func resetBackendRoots() {
        let names = ((cache.status["backends"] as? [[String: Any]]) ?? [])
            .compactMap { $0["name"] as? String }
        guard !names.isEmpty,
              alert("Reset every agent CLI location to its default?",
                    "Only the store paths aht looks at are reset — "
                    + "no history is touched.", confirm: "Reset") else { return }
        background {
            aht(["backends", "--clear-root"] + names)
            notifyUser("Agent CLI locations", "Reset to defaults")
        }
    }

    func badgesSubmenu() -> NSMenuItem {
        let root = NSMenuItem(title: "Folder Badges", action: nil, keyEquivalent: "")
        let m = NSMenu()
        m.addItem(toggleItem("Badge Folders", "icons_enabled"))
        m.addItem(toggleItem("Agent Symbols", "icons_agent"))
        m.addItem(toggleItem("Git “+”", "icons_git"))
        m.addItem(.separator())
        m.addItem(mk("Refresh All Badges", #selector(refreshBadges)))
        m.addItem(mk("Clear All Badges…", #selector(clearBadges)))
        root.submenu = m
        return root
    }

    // ---- item helpers ----

    func mk(_ title: String, _ sel: Selector, key: String = "") -> NSMenuItem {
        let i = NSMenuItem(title: title, action: sel, keyEquivalent: key)
        i.target = self
        return i
    }
    func mk(disabled title: String) -> NSMenuItem {
        let i = NSMenuItem(title: title, action: nil, keyEquivalent: "")
        i.isEnabled = false
        return i
    }
    func add(_ title: String, _ sel: Selector, key: String = "") {
        menu.addItem(mk(title, sel, key: key))
    }
    func add(disabled title: String) { menu.addItem(mk(disabled: title)) }
    func toggleItem(_ title: String, _ key: String) -> NSMenuItem {
        let i = NSMenuItem(title: title, action: #selector(toggleConfig(_:)),
                           keyEquivalent: "")
        i.target = self
        i.representedObject = key
        i.state = (cache.config[key] as? Bool ?? true) ? .on : .off
        return i
    }
    func background(_ work: @escaping () -> Void) {
        DispatchQueue.global(qos: .userInitiated).async {
            work()
            self.cache.refresh()
        }
    }
    func alert(_ title: String, _ body: String, confirm: String? = nil) -> Bool {
        let a = NSAlert()
        a.messageText = title
        a.informativeText = body
        if let c = confirm {
            a.addButton(withTitle: c)
            a.addButton(withTitle: "Cancel")
            NSApp.activate(ignoringOtherApps: true)
            return a.runModal() == .alertFirstButtonReturn
        }
        a.addButton(withTitle: "OK")
        NSApp.activate(ignoringOtherApps: true)
        a.runModal()
        return true
    }

    // ---- actions ----

    @objc func reconcile() {
        background {
            let d = ahtJSON(["reconcile", "--notify"]) ?? [:]
            let am = (d["applied_moves"] as? [Any])?.count ?? 0
            let ac = (d["applied_copies"] as? [Any])?.count ?? 0
            let pend = ((d["moves"] as? [Any])?.count ?? 0)
                     + ((d["copies"] as? [Any])?.count ?? 0)
            let msg = am + ac > 0
                ? "\(am) project(s) relinked, \(ac) histor(ies) copied"
                : (pend > 0 ? "Changes found — answered via dialog or deferred"
                            : "Nothing to do — every history is in place")
            notifyUser("Reconcile", msg)
        }
    }

    @objc func toggleWatch() {
        let running = cache.running
        background {
            let uid = getuid()
            if running {
                sh("/bin/launchctl", ["bootout", "gui/\(uid)/\(WATCHER_LABEL)"])
                notifyUser("Watcher paused",
                           "The Claude SessionStart hook still protects projects you open")
            } else {
                sh("/bin/launchctl", ["bootstrap", "gui/\(uid)", WATCHER_PLIST])
                notifyUser("Watcher", "Watching resumed")
            }
        }
    }

    @objc func adopt() {
        background {
            guard let d = ahtJSON(["adopt", "--json"]) else { return }
            let planned = (d["planned"] as? [Any])?.count ?? 0
            let already = d["already"] as? Int ?? 0
            let orphans = d["orphans_claude"] as? Int ?? 0
            DispatchQueue.main.async {
                if planned == 0 {
                    _ = self.alert("Nothing to adopt",
                                   "\(already) project(s) are already tracked. "
                                   + "\(orphans) claude histor(ies) have no matching "
                                   + "folder — reconnect those with:  aht orphans --match")
                    return
                }
                guard self.alert("Start tracking \(planned) existing project(s)?",
                                 "Each folder gets a marker (.aht/.project-id) and a "
                                 + "registry entry so its agent histories follow it. "
                                 + "Nothing is moved, renamed or deleted.",
                                 confirm: "Adopt") else { return }
                self.background {
                    let r = aht(["adopt", "--apply", "--json"])
                    notifyUser("Adopt", r.ok ? "\(planned) project(s) are now tracked"
                                             : "Adopt failed")
                }
            }
        }
    }

    @objc func revealProject(_ sender: NSMenuItem) {
        guard let path = sender.representedObject as? String else { return }
        if FileManager.default.fileExists(atPath: path) {
            NSWorkspace.shared.selectFile(path, inFileViewerRootedAtPath: "")
        } else {
            _ = alert("That folder is gone",
                      "\(path)\n\nIts histories are safe — reconnect with "
                      + "aht orphans --match or aht restore.")
        }
    }

    @objc func setPolicy(_ sender: NSMenuItem) {
        guard let kv = sender.representedObject as? String else { return }
        background {
            aht(["config", "--set", kv, "--no-reload"])
            notifyUser("Settings", kv)
        }
    }

    @objc func toggleConfig(_ sender: NSMenuItem) {
        guard let key = sender.representedObject as? String else { return }
        let cur = cache.config[key] as? Bool ?? true
        background {
            aht(["config", "--set", "\(key)=\(cur ? "false" : "true")", "--no-reload"])
            notifyUser("Settings", "\(key): \(cur ? "off" : "on")")
        }
    }

    @objc func backupNow() {
        background {
            let d = ahtJSON(["backup", "--json"]) ?? [:]
            let counts = d["counts"] as? [String: Int] ?? [:]
            let msg = counts.isEmpty ? "nothing to back up"
                : counts.sorted { $0.key < $1.key }
                        .map { "\($0.value) \($0.key)" }.joined(separator: ", ")
            notifyUser("History backup", msg)
        }
    }

    @objc func editConfig() {
        background {
            aht(["config"])   // ensures the file exists with current values
            sh("/usr/bin/open", ["-t", HOME + "/.aht/config.json"])
        }
    }

    @objc func restartWatcher() {
        background {
            aht(["reload"])
            notifyUser("Watcher", "Restarted with the current config")
        }
    }

    @objc func refreshBadges() {
        background {
            let r = aht(["icons", "--refresh"])
            notifyUser("Folder badges",
                       r.out.split(separator: "\n").last.map(String.init) ?? "refreshed")
        }
    }

    @objc func clearBadges() {
        guard alert("Clear every folder badge?",
                    "Removes the custom icon from tethered folders and git repos. "
                    + "Projects and histories are not affected; badges come back "
                    + "if you re-enable them.", confirm: "Clear") else { return }
        let cfg = cache.config
        let savedAgent = cfg["icons_agent"] as? Bool ?? true
        let savedGit = cfg["icons_git"] as? Bool ?? true
        background {
            aht(["config", "--set", "icons_enabled=true", "icons_agent=false",
                 "icons_git=false", "--no-reload"])
            aht(["icons", "--refresh"])
            aht(["config", "--set", "icons_agent=\(savedAgent)",
                 "icons_git=\(savedGit)", "--no-reload"])
            notifyUser("Folder badges", "Cleared")
        }
    }

    @objc func doctor() {
        background {
            let r = aht(["doctor"])
            DispatchQueue.main.async {
                _ = self.alert("Diagnostics",
                               r.out.isEmpty ? "doctor produced no output" : r.out)
            }
        }
    }

    @objc func openData() { sh("/usr/bin/open", [HOME + "/.aht"]) }
    @objc func openLog() { sh("/usr/bin/open", ["-t", HOME + "/.aht/aht.log"]) }

    @objc func toggleLogin() {
        let fm = FileManager.default
        if fm.fileExists(atPath: TRAY_PLIST) {
            sh("/bin/launchctl", ["bootout", "gui/\(getuid())/\(TRAY_LABEL)"])
            try? fm.removeItem(atPath: TRAY_PLIST)
            notifyUser("Autostart", "The tray no longer starts at login")
        } else {
            let bin = TOOLS + "/aht-tray"
            let plist = """
            <?xml version="1.0" encoding="UTF-8"?>
            <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
            <plist version="1.0"><dict>
                <key>Label</key><string>\(TRAY_LABEL)</string>
                <key>ProgramArguments</key><array><string>\(bin)</string></array>
                <key>RunAtLoad</key><true/>
            </dict></plist>
            """
            try? plist.write(toFile: TRAY_PLIST, atomically: true, encoding: .utf8)
            notifyUser("Autostart", "The tray starts at login")
        }
        cache.refresh()
    }

    @objc func about() {
        _ = alert("agent-history-tether",
                  "Keeps every AI coding agent's per-project history connected to "
                  + "its folder when you move, rename, copy or nest that folder — "
                  + "Claude Code, Codex, Gemini, Cursor, OpenCode, Copilot.\n\n"
                  + "This tray, the aht CLI, the hook and the watcher all drive "
                  + "the same core, registry and config.\n\nData: ~/.aht\n"
                  + "History is never deleted or overwritten.")
    }

    @objc func quit() { NSApp.terminate(nil) }
}

// selftest: everything that can run headless (used by CI/dev boxes)
if CommandLine.arguments.contains("--selftest") {
    let r = aht(["version"])
    print("TRAY SELFTEST \(r.ok ? "OK" : "FAIL") — core: \(r.out.trimmingCharacters(in: .whitespacesAndNewlines))")
    exit(r.ok ? 0 : 1)
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let delegate = TrayApp()
app.delegate = delegate
app.run()
