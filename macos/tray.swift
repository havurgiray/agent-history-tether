// aht-tray — the macOS menu bar companion of agent-history-tether.
//
// A FRONT-END only: every action shells out to the same aht.py core the CLI,
// the hook and the LaunchAgent watcher use, so no front-end can disagree with
// another.  Compiled by install.py (swiftc, no dependencies) or shipped
// prebuilt as the executable of aht.app (macos/build_app.sh); menu parity with
// the Windows tray (windows/src/aht_tray.py) and the Linux tray (linux/tray.py).
//
//   run:            ~/.aht/tools/agent-history-tether/aht-tray &   (or open aht.app)
//   start at login: toggle it in the menu (writes a LaunchAgent)
//   from aht.app:   offers to install the core, watcher and hook on first launch
import AppKit
import Foundation

let HOME = NSHomeDirectory()
let TOOLS = HOME + "/.aht/tools/agent-history-tether"
let PY = "/usr/bin/python3"
let WATCHER_LABEL = "com.aht.watcher"
let TRAY_LABEL = "com.aht.tray"
let TRAY_PLIST = HOME + "/Library/LaunchAgents/\(TRAY_LABEL).plist"
let WATCHER_PLIST = HOME + "/Library/LaunchAgents/\(WATCHER_LABEL).plist"

// When launched as aht.app, the core and the prebuilt binaries ship in the
// bundle's Resources; a bare aht-tray binary has no bundle.
let BUNDLE_RES: String? =
    Bundle.main.bundlePath.hasSuffix(".app") ? Bundle.main.resourcePath : nil

func ahtScript() -> String {
    // the installed copy first: it is what the hook and the watcher run too
    let fm = FileManager.default
    var candidates = [TOOLS + "/aht.py"]
    if let r = BUNDLE_RES { candidates.append(r + "/aht.py") }
    candidates.append(URL(fileURLWithPath: CommandLine.arguments[0])
        .deletingLastPathComponent().appendingPathComponent("aht.py").path)
    for c in candidates where fm.fileExists(atPath: c) { return c }
    return TOOLS + "/aht.py"
}

func coreVersion(_ path: String) -> [Int] {
    let tag = "VERSION = \""
    guard let text = try? String(contentsOfFile: path, encoding: .utf8) else { return [] }
    for line in text.components(separatedBy: "\n") where line.hasPrefix(tag) {
        return line.dropFirst(tag.count).prefix { $0 != "\"" }
            .split(separator: ".").compactMap { Int($0) }
    }
    return []
}

@discardableResult
func sh(_ exe: String, _ args: [String], mergeStderr: Bool = false)
    -> (ok: Bool, out: String) {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: exe)
    p.arguments = args
    let out = Pipe()
    p.standardOutput = out
    p.standardError = mergeStderr ? out : Pipe()
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
    var machines: [[String: Any]] = []     // discovered, for "Add Machine"
    var running = false
    private let q = DispatchQueue(label: "aht.tray.cache")

    func refresh(_ done: (() -> Void)? = nil) {
        q.async {
            let st = ahtJSON(["status", "--json"]) ?? [:]
            let cf = (ahtJSON(["config", "--json"])?["effective"] as? [String: Any]) ?? [:]
            let pj = (ahtJSON(["projects", "--json"])?["projects"] as? [[String: Any]]) ?? []
            let mc = (ahtJSON(["remote", "discover", "--json"])?["machines"]
                      as? [[String: Any]]) ?? []
            let run = watcherRunning()
            DispatchQueue.main.async {
                self.status = st
                self.config = cf
                self.projects = pj
                self.machines = mc
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
        // the aht mark: a loop with no loose end (template = follows the bar's theme)
        let img = NSImage(systemSymbolName: "infinity",
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
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
            self.offerInstallIfNeeded()
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
        let away = (handoverInfo()["away"] as? [[String: Any]]) ?? []
        if !away.isEmpty {
            let hosts = Set(away.compactMap { $0["host"] as? String }).sorted()
            add(disabled: "\(away.count) handed over to " + hosts.joined(separator: ", "))
        }
        if let w = working { add(disabled: "⏳ " + w) }
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
        menu.addItem(handoverSubmenu())
        add("Adopt This Mac's Projects…", #selector(adopt))
        if BUNDLE_RES != nil {
            let installed = FileManager.default.fileExists(atPath: TOOLS + "/aht.py")
            add(installed ? "Reinstall / Update aht on This Mac…"
                          : "Set Up aht on This Mac…", #selector(installFromApp))
        }
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

    // ---- handover: continue a project on another machine, and take it back ----

    var working: String?            // a transfer in progress, shown in the menu

    func handoverInfo() -> [String: Any] {
        return (cache.status["handover"] as? [String: Any]) ?? [:]
    }

    func projectList(_ title: String, _ rows: [[String: Any]], _ sel: Selector,
                     empty: String, checked: (([String: Any]) -> Bool)? = nil,
                     note: (([String: Any]) -> String?)? = nil)
        -> NSMenuItem {
        let root = NSMenuItem(title: title, action: nil, keyEquivalent: "")
        let m = NSMenu()
        if rows.isEmpty { m.addItem(mk(disabled: empty)) }
        for p in rows {
            let path = (p["real_path"] as? String) ?? (p["project"] as? String) ?? "?"
            var label = (path as NSString).lastPathComponent
            if let n = note?(p) { label += "  —  " + n }
            let i = NSMenuItem(title: label, action: sel, keyEquivalent: "")
            i.target = self
            i.representedObject = path
            i.toolTip = path
            if let c = checked { i.state = c(p) ? .on : .off }
            m.addItem(i)
        }
        root.submenu = m
        return root
    }

    func remotes() -> [String: Any] {
        return (handoverInfo()["remotes"] as? [String: Any]) ?? [:]
    }
    func target(_ name: String) -> String {
        return ((remotes()[name] as? [String: Any])?["ssh"] as? String) ?? ""
    }
    /// The machine the menu's actions go to; chosen under "Machine".
    func currentMachine() -> String? {
        return handoverInfo()["default_remote"] as? String
    }

    func machineSubmenu() -> NSMenuItem {
        let names = remotes().keys.sorted()
        let cur = currentMachine()
        let root = NSMenuItem(title: cur.map { "Machine: \($0)" } ?? "No Other Machine Yet",
                              action: nil, keyEquivalent: "")
        let m = NSMenu()
        root.submenu = m
        for n in names {
            let i = NSMenuItem(title: "\(n)  —  \(target(n))",
                               action: #selector(chooseMachine(_:)), keyEquivalent: "")
            i.target = self
            i.representedObject = n
            i.state = (n == cur) ? .on : .off
            m.addItem(i)
        }
        if let c = cur {
            m.addItem(.separator())
            m.addItem(mk("Check \(c)", #selector(checkRemote)))
            if names.count > 1 { m.addItem(mk("Check All Machines", #selector(checkAll))) }
            m.addItem(mk("Remove \(c)…", #selector(removeMachine)))
            m.addItem(.separator())
        }
        let add = NSMenuItem(title: "Add Machine", action: nil, keyEquivalent: "")
        let am = NSMenu()
        for d in cache.machines where (d["added_as"] as? String) == nil {
            let host = d["host"] as? String ?? "?"
            var bits = [d["system"] as? String, d["via"] as? String].compactMap { $0 }
            if let on = d["online"] as? Bool { bits.insert(on ? "online" : "offline", at: 0) }
            let i = NSMenuItem(title: "\(host)  —  " + bits.joined(separator: ", "),
                               action: #selector(addMachine(_:)), keyEquivalent: "")
            i.target = self
            i.representedObject = host
            am.addItem(i)
        }
        if am.items.count > 0 { am.addItem(.separator()) }
        am.addItem(mk("Other…", #selector(addMachine(_:))))
        add.submenu = am
        m.addItem(add)
        return root
    }

    func handoverSubmenu() -> NSMenuItem {
        let root = NSMenuItem(title: "Handover", action: nil, keyEquivalent: "")
        let m = NSMenu()
        root.submenu = m
        let ho = handoverInfo()
        if !(ho["supported"] as? Bool ?? true) {
            m.addItem(mk(disabled: "Not available in this build"))
            return root
        }
        m.addItem(machineSubmenu())
        let recentFirst = cache.projects.sorted {
            (($0["last_activity"] as? String) ?? "") > (($1["last_activity"] as? String) ?? "")
        }
        let away = recentFirst.filter { ($0["away"] as? String) != nil }
        guard let name = currentMachine() else {
            if !away.isEmpty {          // handed over before the machine was removed
                m.addItem(projectList("Take Back", away, #selector(takeBack(_:)),
                                      empty: "", note: { $0["away"] as? String }))
            }
            return root
        }
        if ho["rsync"] as? String == nil {
            m.addItem(mk(disabled: "rsync 3 is missing — brew install rsync"))
        }
        m.addItem(.separator())
        let here = recentFirst.filter {
            ($0["exists"] as? Bool ?? false) && ($0["away"] as? String) == nil
        }
        m.addItem(projectList("Hand Over to \(name)", Array(here.prefix(15)),
                              #selector(handOver(_:)), empty: "No tracked projects yet"))
        m.addItem(projectList("Take Back", away, #selector(takeBack(_:)),
                              empty: "Nothing is handed over",
                              note: { ($0["away"] as? String).map { "on " + $0 } }))
        m.addItem(projectList("Open Session", away, #selector(openSession(_:)),
                              empty: "Nothing is handed over",
                              note: { ($0["away"] as? String).map { "on " + $0 } }))
        m.addItem(.separator())
        m.addItem(projectList("Keep in Sync with \(name)", Array(here.prefix(15)),
                              #selector(toggleMirror(_:)), empty: "No tracked projects yet",
                              checked: { ($0["mirror"] as? String) == name },
                              note: { p in
                                  let at = p["mirror"] as? String
                                  return (at != nil && at != name) ? "kept on \(at!)" : nil
                              }))
        m.addItem(mk("Sync Now", #selector(syncNow)))
        return root
    }

    /// What stands in the way, in the core's own words; nil when nothing does.
    func problems(_ d: [String: Any]) -> String? {
        if d.isEmpty { return "aht gave no answer — see Open Log." }
        var lines = (d["blockers"] as? [String]) ?? []
        if let e = d["error"] as? String { lines.append(e) }
        return lines.isEmpty ? nil : lines.map { "• " + $0 }.joined(separator: "\n\n")
    }

    func size(_ any: Any?) -> String {
        let n = (any as? NSNumber)?.int64Value ?? 0
        return ByteCountFormatter.string(fromByteCount: n, countStyle: .file)
    }

    func busy(_ text: String?, _ work: @escaping () -> Void) {
        DispatchQueue.main.async { self.working = text }
        background {
            work()
            DispatchQueue.main.async { self.working = nil }
        }
    }

    @objc func handOver(_ sender: NSMenuItem) {
        guard let path = sender.representedObject as? String else { return }
        let name = (path as NSString).lastPathComponent
        let to = currentMachine().map { ["--to", $0] } ?? []
        busy("checking \(name)…") {
            let plan = ahtJSON(["handover", path, "--json"] + to) ?? [:]
            DispatchQueue.main.async {
                if let why = self.problems(plan) {
                    _ = self.alert("“\(name)” cannot be handed over now", why)
                    return
                }
                let remote = plan["remote"] as? String ?? "the other machine"
                let p = (plan["plan"] as? [String: Any]) ?? [:]
                var body = "\(p["files"] as? Int ?? 0) file(s) to send "
                    + "(\(self.size(p["bytes"]))), history \(self.size(p["history_bytes"])).\n"
                    + "Session: \((plan["title"] as? String) ?? "the most recent one")\n"
                if let v = p["install_claude"] as? String {
                    body += "Claude Code \(v) gets installed on \(remote).\n"
                }
                let stay = (plan["outside_not_carried"] as? [String]) ?? []
                if !stay.isEmpty {
                    body += "\nFiles outside the project that stay here:\n"
                        + stay.prefix(6).map { "• " + $0 }.joined(separator: "\n") + "\n"
                }
                body += "\nThe session is resumed there and this folder is marked as "
                    + "away until you take it back."
                guard self.alert("Hand “\(name)” over to \(remote)?", body,
                                 confirm: "Hand Over") else { return }
                self.busy("handing \(name) over…") {
                    let d = ahtJSON(["handover", path, "--apply", "--json"] + to) ?? [:]
                    DispatchQueue.main.async {
                        if let why = self.problems(d) {
                            _ = self.alert("The handover did not go through", why)
                            return
                        }
                        let s = (d["sent"] as? [String: Any]) ?? [:]
                        var done = "\(s["files"] as? Int ?? 0) file(s) sent, "
                            + "\(self.size(s["wire_bytes"])) over the network."
                        for w in (d["warnings"] as? [String]) ?? [] { done += "\n\n⚠ " + w }
                        if self.alert("“\(name)” now runs on \(remote)", done,
                                      confirm: "Open Session") {
                            self.background { aht(["attach", path, "--window"]) }
                        }
                    }
                }
            }
        }
    }

    @objc func takeBack(_ sender: NSMenuItem) {
        guard let path = sender.representedObject as? String else { return }
        let name = (path as NSString).lastPathComponent
        busy("checking \(name)…") {
            let plan = ahtJSON(["reclaim", path, "--stop", "--json"]) ?? [:]
            DispatchQueue.main.async {
                if let why = self.problems(plan) {
                    _ = self.alert("“\(name)” cannot be taken back now", why)
                    return
                }
                let remote = plan["remote"] as? String ?? "the other machine"
                let p = ((plan["plan"] as? [String: Any])?["project"] as? [String: Int]) ?? [:]
                var body = "\(p["take"] ?? 0) file(s) changed there, \(p["new"] ?? 0) new, "
                    + "\(p["delete"] ?? 0) removed. Whatever they replace here is "
                    + "set aside, not deleted.\n"
                if plan["would_stop"] as? Bool ?? false {
                    body += "\nThe idle session on \(remote) is ended first.\n"
                }
                let both = ((plan["conflicts"] as? [String: [String]]) ?? [:])
                    .values.flatMap { $0 }
                var extra: [String] = []
                if both.isEmpty {
                    guard self.alert("Take “\(name)” back from \(remote)?", body,
                                     confirm: "Take Back") else { return }
                } else {
                    body += "\nChanged on BOTH machines:\n"
                        + both.prefix(6).map { "• " + $0 }.joined(separator: "\n")
                        + "\n\nKeep Both leaves your version in place and puts the one "
                        + "from \(remote) next to it."
                    let pick = self.choose("Take “\(name)” back from \(remote)?", body,
                                           ["Keep Both", "Use the Versions from \(remote)",
                                            "Cancel"])
                    if pick == 2 { return }
                    if pick == 1 { extra = ["--prefer", "there"] }
                }
                self.busy("taking \(name) back…") {
                    let d = ahtJSON(["reclaim", path, "--stop", "--apply", "--json"]
                                    + extra) ?? [:]
                    DispatchQueue.main.async {
                        if let why = self.problems(d) {
                            _ = self.alert("Taking it back did not go through", why)
                            return
                        }
                        var done = "The files and the history are on this Mac again."
                        if let aside = d["set_aside"] as? String {
                            done += "\n\nReplaced files are kept in:\n" + aside
                        }
                        for w in (d["warnings"] as? [String]) ?? [] { done += "\n\n⚠ " + w }
                        if self.alert("“\(name)” is back", done,
                                      confirm: "Continue the Session") {
                            self.background { aht(["resume-here", path]) }
                        }
                    }
                }
            }
        }
    }

    @objc func openSession(_ sender: NSMenuItem) {
        guard let path = sender.representedObject as? String else { return }
        background { aht(["attach", path, "--window"]) }
    }

    @objc func toggleMirror(_ sender: NSMenuItem) {
        guard let path = sender.representedObject as? String else { return }
        let on = sender.state != .on
        let to = currentMachine().map { ["--to", $0] } ?? []
        background {
            aht(["mirror", path] + (on ? ["--on"] + to : ["--off"]))
            notifyUser("Keep in Sync", (path as NSString).lastPathComponent
                       + (on ? ": on — the first sync runs in the background" : ": off"))
        }
    }

    @objc func syncNow() {
        busy("syncing…") {
            let rows = (ahtJSON(["mirror", "--run", "--json"])?["mirrored"]
                        as? [[String: Any]]) ?? []
            let ok = rows.filter { $0["status"] as? String == "synced" }.count
            notifyUser("Sync", rows.isEmpty ? "No project is kept in sync yet"
                       : "\(ok) synced" + (ok < rows.count
                                           ? ", \(rows.count - ok) skipped — see the log" : ""))
        }
    }

    @objc func chooseMachine(_ sender: NSMenuItem) {
        guard let n = sender.representedObject as? String else { return }
        background {
            aht(["remote", "default", n])
            notifyUser("Handover", "Machine: \(n)")
        }
    }

    func check(_ args: [String], _ what: String) {
        busy("checking \(what)…") {
            let r = sh(PY, [ahtScript(), "remote", "check"] + args, mergeStderr: true)
            DispatchQueue.main.async {
                _ = self.alert(what, r.out.isEmpty ? "no answer — see Open Log" : r.out)
            }
        }
    }
    @objc func checkRemote() {
        if let c = currentMachine() { check([c], c) }
    }
    @objc func checkAll() { check(["all"], "All machines") }

    @objc func removeMachine() {
        guard let c = currentMachine() else { return }
        let held = cache.projects.filter { ($0["away_remote"] as? String) == c }
            .compactMap { $0["real_path"] as? String }
        if !held.isEmpty {
            _ = alert("\(c) still holds handed-over projects",
                      "Take these back first:\n"
                      + held.map { "• " + $0 }.joined(separator: "\n"))
            return
        }
        guard alert("Remove \(c)?",
                    "aht forgets how to reach it. Nothing is deleted on either machine.",
                    confirm: "Remove") else { return }
        background { aht(["remote", "remove", c]) }
    }

    @objc func addMachine(_ sender: NSMenuItem) {
        let host = sender.representedObject as? String
        // the login used for the machines so far is the best guess for the next
        let user = remotes().keys.sorted().compactMap { n -> String? in
            let t = self.target(n)
            return t.contains("@") ? String(t.split(separator: "@")[0]) : nil
        }.first ?? NSUserName()
        let a = NSAlert()
        a.messageText = "Add a machine"
        a.informativeText = "A machine you reach over ssh without a password prompt. "
            + "aht checks it and tells you what it still needs."
        let box = NSView(frame: NSRect(x: 0, y: 0, width: 300, height: 56))
        let name = NSTextField(frame: NSRect(x: 0, y: 30, width: 300, height: 24))
        name.placeholderString = "a name for it"
        name.stringValue = host ?? ""
        let target = NSTextField(frame: NSRect(x: 0, y: 0, width: 300, height: 24))
        target.placeholderString = "user@host"
        target.stringValue = host.map { "\(user)@\($0)" } ?? ""
        box.addSubview(name)
        box.addSubview(target)
        name.nextKeyView = target
        a.accessoryView = box
        a.addButton(withTitle: "Check and Add")
        a.addButton(withTitle: "Cancel")
        a.window.initialFirstResponder = host == nil ? name : target
        NSApp.activate(ignoringOtherApps: true)
        guard a.runModal() == .alertFirstButtonReturn else { return }
        let n = name.stringValue.trimmingCharacters(in: .whitespaces)
        let t = target.stringValue.trimmingCharacters(in: .whitespaces)
        guard !n.isEmpty, !t.isEmpty else { return }
        busy("checking \(n)…") {
            let r = sh(PY, [ahtScript(), "remote", "add", n, t], mergeStderr: true)
            let more = r.ok ? sh(PY, [ahtScript(), "remote", "check", n],
                                 mergeStderr: true).out : ""
            DispatchQueue.main.async {
                _ = self.alert(r.ok ? "\(n) is added" : "\(n) could not be added",
                               r.ok ? more : r.out)
            }
        }
    }

    func choose(_ title: String, _ body: String, _ buttons: [String]) -> Int {
        let a = NSAlert()
        a.messageText = title
        a.informativeText = body
        for b in buttons { a.addButton(withTitle: b) }
        NSApp.activate(ignoringOtherApps: true)
        return a.runModal().rawValue - NSApplication.ModalResponse.alertFirstButtonReturn.rawValue
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

    // ---- installing from the app bundle ----

    func offerInstallIfNeeded() {
        guard let res = BUNDLE_RES else { return }
        let bundled = coreVersion(res + "/aht.py")
        let bundledStr = bundled.map(String.init).joined(separator: ".")
        let defaults = UserDefaults.standard
        if !FileManager.default.fileExists(atPath: TOOLS + "/aht.py") {
            // asked once per app version; the menu keeps the option available
            guard defaults.string(forKey: "declinedSetup") != bundledStr else { return }
            if alert("Set up aht on this Mac?",
                     "This installs the background watcher (a LaunchAgent), the "
                     + "Claude Code SessionStart hook and the `aht` terminal command "
                     + "from this app.  No agent's history is touched, and "
                     + "`aht uninstall` undoes it.", confirm: "Install") {
                runInstall(res)
            } else {
                defaults.set(bundledStr, forKey: "declinedSetup")
            }
            return
        }
        let current = coreVersion(TOOLS + "/aht.py")
        if current.lexicographicallyPrecedes(bundled) {
            let currentStr = current.map(String.init).joined(separator: ".")
            guard defaults.string(forKey: "declinedUpdate") != bundledStr else { return }
            if alert("Update the installed aht core?",
                     "This app carries aht \(bundledStr); the copy the watcher, the "
                     + "hook and the command run is \(currentStr).  Updating keeps "
                     + "every setting and history.", confirm: "Update") {
                runInstall(res)
            } else {
                defaults.set(bundledStr, forKey: "declinedUpdate")
            }
        }
    }

    func runInstall(_ res: String) {
        background {
            let r = sh(PY, [res + "/install.py", "--src", res,
                            "--keep-pid", String(getpid()),
                            "--tray-exe", Bundle.main.executablePath ?? ""],
                       mergeStderr: true)
            DispatchQueue.main.async {
                _ = self.alert(r.ok ? "aht is set up on this Mac" : "Install failed",
                               r.out.isEmpty ? (r.ok ? "Done." : "See ~/.aht/aht.log")
                                             : r.out)
            }
        }
    }

    @objc func installFromApp() {
        guard let res = BUNDLE_RES else { return }
        runInstall(res)
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
            // whichever tray this is: the app bundle's executable or the bare binary
            let bin = Bundle.main.executablePath ?? (TOOLS + "/aht-tray")
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
                  + "Claude Code, Codex, Gemini, Cursor, OpenCode, Copilot, Kimi.\n\n"
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
