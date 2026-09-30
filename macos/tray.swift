// aht-tray — the macOS front-end of agent-history-tether: an ∞ in the menu
// bar and a window.
//
// A FRONT-END only: every action shells out to the same aht.py core the CLI,
// the hook and the LaunchAgent watcher use, so no front-end can disagree with
// another.  Compiled by install.py (swiftc, no dependencies) or shipped
// prebuilt as the executable of aht.app (macos/build_app.sh).
//
// The MENU is short on purpose: status, the window, and two actions that are
// safe to hit by accident.  Whatever changes a project — handing it over,
// taking it back, syncing, the settings — lives in the WINDOW, where a row is
// selected first and a button pressed second.
//
//   run:            ~/.aht/tools/agent-history-tether/aht-tray &   (or open aht.app)
//   start at login: Settings tab in the window (writes a LaunchAgent)
//   from aht.app:   offers to install the core, watcher and hook on first launch
//   --selftest      headless check that the core answers (CI)
//   --snapshot DIR  render every tab of the window into DIR as PNG files
import AppKit
import Foundation
import SwiftUI

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

func byteText(_ any: Any?) -> String {
    let n = (any as? NSNumber)?.int64Value ?? 0
    return ByteCountFormatter.string(fromByteCount: n, countStyle: .file)
}

/// "3 hours ago" for the core's timestamps (ISO text or seconds since 1970).
func ago(_ any: Any?) -> String {
    var date: Date?
    if let n = any as? NSNumber, n.doubleValue > 0 {
        date = Date(timeIntervalSince1970: n.doubleValue)
    } else if let s = any as? String, !s.isEmpty {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        date = f.date(from: String(s.prefix(19)))
    }
    guard let d = date else { return "" }
    if abs(d.timeIntervalSinceNow) < 60 { return "just now" }
    let r = RelativeDateTimeFormatter()
    r.unitsStyle = .full
    return r.localizedString(for: d, relativeTo: Date())
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

func choose(_ title: String, _ body: String, _ buttons: [String]) -> Int {
    let a = NSAlert()
    a.messageText = title
    a.informativeText = body
    for b in buttons { a.addButton(withTitle: b) }
    NSApp.activate(ignoringOtherApps: true)
    return a.runModal().rawValue - NSApplication.ModalResponse.alertFirstButtonReturn.rawValue
}

// ---- what the window shows ---------------------------------------------------

struct Project: Identifiable, Hashable {
    let path: String
    let exists: Bool
    let away: String?               // the machine's own name, while handed over
    let awayRemote: String?         // the name it was added under
    let awaySince: String?
    let mirror: String?
    let syncedAt: Double?
    let syncStatus: String?
    let agents: [String]
    let sessions: Int
    let bytes: Int64
    let lastActivity: String
    let open: String?               // "waiting" | "working" | "idle": a session is open

    var id: String { path }
    var name: String { (path as NSString).lastPathComponent }
    var parent: String {
        ((path as NSString).deletingLastPathComponent as NSString).lastPathComponent
    }
    var place: String {
        if let host = away { return "on " + host }
        if !exists { return "missing" }
        switch open {
        case "idle": return "here · session open"
        case "waiting": return "here · waiting for you"
        case .some: return "here · working"
        default: return "here"
        }
    }
    var sync: String {
        guard mirror != nil else { return "–" }
        if away != nil { return "paused" }
        if let s = syncStatus, s != "ok" { return "⚠ " + s }
        return syncedAt == nil ? "waiting" : ago(NSNumber(value: syncedAt!))
    }

    init(_ d: [String: Any]) {
        path = d["real_path"] as? String ?? "?"
        exists = d["exists"] as? Bool ?? false
        away = d["away"] as? String
        awayRemote = d["away_remote"] as? String
        awaySince = d["away_since"] as? String
        mirror = d["mirror"] as? String
        syncedAt = (d["mirror_synced_at"] as? NSNumber)?.doubleValue
        syncStatus = d["mirror_status"] as? String
        agents = d["agents"] as? [String] ?? d["stores"] as? [String] ?? []
        open = d["open"] as? String
        sessions = d["sessions"] as? Int ?? 0
        bytes = (d["bytes"] as? NSNumber)?.int64Value ?? 0
        lastActivity = d["last_activity"] as? String ?? ""
    }
}

struct Machine: Identifiable, Hashable {
    let name: String
    let target: String
    var id: String { name }
}

struct Found: Identifiable, Hashable {
    let host: String
    let note: String
    var id: String { host }
}

struct Check: Identifiable, Hashable {
    let id = UUID()
    let name: String
    let ok: Bool
    let needed: Bool
    let detail: String
    let fix: String?
}

struct Backend: Identifiable, Hashable {
    let name: String
    let found: Bool
    let root: String
    let source: String
    var id: String { name }
}

struct BoardRow: Identifiable, Hashable {
    let id = UUID()
    let machine: String
    let local: Bool
    let agent: String
    let project: String
    let status: String
    let waitingFor: String?
    let since: Double?
    let handedOver: Bool
    var name: String { (project as NSString).lastPathComponent }
    var state: String { status + (waitingFor.map { ": " + $0 } ?? "") }
}

struct BoardMachine: Identifiable, Hashable {
    let name: String
    let reachable: Bool
    let error: String?
    let rows: [BoardRow]
    var id: String { name }
}

struct SearchHit: Identifiable, Hashable {
    let id = UUID()
    let agent: String
    let session: String
    let project: String?
    let title: String
    let live: Bool
    let updated: Double?
    let snippets: [(role: String, text: String)]
    let restoreUUID: String?
    let restoreStamp: String?
    let restoreProject: String?
    static func == (a: SearchHit, b: SearchHit) -> Bool { a.id == b.id }
    func hash(into h: inout Hasher) { h.combine(id) }
}

struct SecretFind: Identifiable, Hashable {
    let id = UUID()
    let project: String
    let agent: String
    let kind: String
    let masked: String
    let whereFound: String
    let t: Double?
    let times: Int
}

struct HandoverPlan: Identifiable {
    let id = UUID()
    let project: Project
    let remote: String
    let body: String
    var task = ""
}

struct RulesView: Identifiable {
    let id = UUID()
    let project: Project
    var status: [String: Any]
    var result: String?
}

struct TextSheet: Identifiable {
    let id = UUID()
    let title: String
    let text: String
    let project: Project?
    var wide = false
}

let AGENT_LABEL = ["claude": "Claude Code", "kimi": "Kimi Code", "codex": "Codex",
                   "gemini": "Gemini", "opencode": "OpenCode", "cursor": "Cursor",
                   "copilot": "Copilot"]

struct NewMachine: Identifiable {
    let id = UUID()
    var name: String
    var target: String
}

enum Tab: String, CaseIterable, Identifiable {
    case projects = "Projects", sessions = "Sessions", search = "Search"
    case machines = "Machines", settings = "Settings"
    var id: String { rawValue }
}

final class AppModel: ObservableObject {
    @Published var status: [String: Any] = [:]
    @Published var config: [String: Any] = [:]
    @Published var projects: [Project] = []
    @Published var found: [Found] = []
    @Published var running = false
    @Published var loaded = false

    @Published var tab: Tab = .projects
    @Published var selection: String?
    @Published var search = ""
    @Published var working: String?             // a transfer or check in progress
    @Published var percent: Double?
    @Published var notes: [String: String] = [:]    // per project: how the last action went
    @Published var checks: [String: [Check]] = [:]  // per machine
    @Published var checkError: [String: String] = [:]
    @Published var adding: NewMachine?
    @Published var loginItem = FileManager.default.fileExists(atPath: TRAY_PLIST)

    @Published var board: [BoardMachine] = []
    @Published var boardAt: Date?
    @Published var boardLoading = false
    @Published var query = ""
    @Published var hits: [SearchHit] = []
    @Published var searched: String?            // the query the hits belong to
    @Published var searching = false
    @Published var secrets: [SecretFind]?
    @Published var secretsFor: String?          // a project, or nil for every history
    @Published var showSecrets = false
    @Published var handoverPlan: HandoverPlan?
    @Published var rules: RulesView?
    @Published var textSheet: TextSheet?

    private let q = DispatchQueue(label: "aht.tray.state")

    // ---- reading ----

    struct Loaded {
        var status: [String: Any] = [:]
        var config: [String: Any] = [:]
        var projects: [[String: Any]] = []
        var found: [[String: Any]] = []
        var running = false
    }

    static func load() -> Loaded {
        var l = Loaded()
        l.status = ahtJSON(["status", "--json"]) ?? [:]
        l.config = (ahtJSON(["config", "--json"])?["effective"] as? [String: Any]) ?? [:]
        l.projects = (ahtJSON(["projects", "--json"])?["projects"] as? [[String: Any]]) ?? []
        l.found = (ahtJSON(["remote", "discover", "--json"])?["machines"]
                   as? [[String: Any]]) ?? []
        l.running = watcherRunning()
        return l
    }

    func take(_ l: Loaded) {
        status = l.status
        config = l.config
        var seen = Set<String>()
        projects = l.projects.map(Project.init).filter { seen.insert($0.path).inserted }
        found = l.found.filter { ($0["added_as"] as? String) == nil }.map { d in
            var bits = [d["system"] as? String, d["via"] as? String].compactMap { $0 }
            if let on = d["online"] as? Bool { bits.insert(on ? "online" : "offline", at: 0) }
            return Found(host: d["host"] as? String ?? "?",
                         note: bits.joined(separator: ", "))
        }
        running = l.running
        loginItem = FileManager.default.fileExists(atPath: TRAY_PLIST)
        loaded = true
    }

    func refresh(_ done: (() -> Void)? = nil) {
        q.async {
            let l = AppModel.load()
            DispatchQueue.main.async {
                self.take(l)
                done?()
            }
        }
    }

    // ---- derived ----

    var handover: [String: Any] { (status["handover"] as? [String: Any]) ?? [:] }
    var supported: Bool { handover["supported"] as? Bool ?? true }
    var machines: [Machine] {
        ((handover["remotes"] as? [String: Any]) ?? [:]).map { k, v in
            Machine(name: k, target: ((v as? [String: Any])?["ssh"] as? String) ?? "")
        }.sorted { $0.name < $1.name }
    }
    /// The machine "Hand Over" and "Keep in Sync" go to.
    var machine: String? { handover["default_remote"] as? String }
    var backends: [Backend] {
        ((status["backends"] as? [[String: Any]]) ?? []).map {
            Backend(name: $0["name"] as? String ?? "?",
                    found: $0["available"] as? Bool ?? false,
                    root: $0["root"] as? String ?? "",
                    source: $0["root_source"] as? String ?? "default")
        }
    }
    var shown: [Project] {
        let s = search.trimmingCharacters(in: .whitespaces).lowercased()
        return projects.filter { s.isEmpty || $0.path.lowercased().contains(s) }
            .sorted { $0.lastActivity > $1.lastActivity }
    }
    var selected: Project? { projects.first { $0.path == selection } }
    var agentCLIs: [String] {
        let d = (status["agent_clis"] as? [String: Any]) ?? [:]
        return ["claude", "kimi", "codex"].filter { d[$0] is String }
    }
    var waiting: Int { projects.filter { $0.open == "waiting" }.count }
    var summary: String {
        let tracked = status["tracked"] as? Int ?? 0
        let missing = status["missing"] as? Int ?? 0
        var s = "\(tracked) tracked project" + (tracked == 1 ? "" : "s")
        if missing > 0 { s += " · \(missing) missing" }
        if !(status["hook_installed"] as? Bool ?? true) { s += " · hook MISSING" }
        return s
    }
    func flag(_ key: String, _ fallback: Bool = true) -> Bool {
        return config[key] as? Bool ?? fallback
    }
    func text(_ key: String, _ fallback: String) -> String {
        return config[key] as? String ?? fallback
    }

    // ---- doing ----

    func background(_ work: @escaping () -> Void) {
        DispatchQueue.global(qos: .userInitiated).async {
            work()
            self.refresh()
        }
    }

    /// Run `work` with a line in the window (and the menu) that says what is
    /// going on; with `follow`, the core's stage and percentage are shown.
    func busy(_ what: String, follow: String? = nil, _ work: @escaping () -> Void) {
        DispatchQueue.main.async {
            self.working = what
            self.percent = nil
        }
        var timer: DispatchSourceTimer?
        if let file = follow {
            try? FileManager.default.removeItem(atPath: file)
            let t = DispatchSource.makeTimerSource(queue: .global())
            t.schedule(deadline: .now() + 0.4, repeating: 0.4)
            t.setEventHandler {
                guard let d = FileManager.default.contents(atPath: file),
                      let j = (try? JSONSerialization.jsonObject(with: d)) as? [String: Any]
                else { return }
                let stage = (j["stage"] as? String) ?? what
                let pct = (j["percent"] as? NSNumber)?.doubleValue
                DispatchQueue.main.async {
                    if self.working != nil {
                        self.working = stage
                        self.percent = pct
                    }
                }
            }
            t.resume()
            timer = t
        }
        background {
            work()
            timer?.cancel()
            DispatchQueue.main.async {
                self.working = nil
                self.percent = nil
            }
        }
    }

    func stageFile(_ path: String) -> String {
        let dir = HOME + "/.aht/run"
        try? FileManager.default.createDirectory(atPath: dir,
                                                 withIntermediateDirectories: true)
        return dir + "/stage-\(abs(path.hashValue)).json"
    }

    /// What stands in the way, in the core's own words; nil when nothing does.
    func problems(_ d: [String: Any]) -> String? {
        if d.isEmpty { return "aht gave no answer — see the log (Settings)." }
        var lines = (d["blockers"] as? [String]) ?? []
        if let e = d["error"] as? String { lines.append(e) }
        return lines.isEmpty ? nil : lines.map { "• " + $0 }.joined(separator: "\n\n")
    }

    func note(_ path: String, _ text: String?) {
        DispatchQueue.main.async { self.notes[path] = text }
    }

    func handOver(_ p: Project) {
        let to = machine.map { ["--to", $0] } ?? []
        note(p.path, nil)
        busy("checking \(p.name)…") {
            let plan = ahtJSON(["handover", p.path, "--json"] + to) ?? [:]
            DispatchQueue.main.async {
                if let why = self.problems(plan) {
                    self.note(p.path, "Cannot be handed over now:\n\n" + why)
                    return
                }
                let remote = plan["remote"] as? String ?? "the other machine"
                let n = (plan["plan"] as? [String: Any]) ?? [:]
                var body = "\(n["files"] as? Int ?? 0) file(s) to send "
                    + "(\(byteText(n["bytes"]))), history \(byteText(n["history_bytes"])).\n"
                    + "Session: \((plan["title"] as? String) ?? "the one used last")\n"
                if let v = n["install_claude"] as? String {
                    body += "Claude Code \(v) gets installed on \(remote).\n"
                }
                let stay = (plan["outside_not_carried"] as? [String]) ?? []
                if !stay.isEmpty {
                    body += "\nFiles outside the project that stay here:\n"
                        + stay.prefix(6).map { "• " + $0 }.joined(separator: "\n") + "\n"
                }
                for w in (plan["warnings"] as? [String]) ?? [] { body += "\n⚠ " + w + "\n" }
                body += "\nThe session is resumed there and this folder is marked as "
                    + "away until you take it back."
                self.handoverPlan = HandoverPlan(project: p, remote: remote, body: body)
            }
        }
    }

    func confirmHandover(_ plan: HandoverPlan) {
        let p = plan.project, remote = plan.remote
        let to = machine.map { ["--to", $0] } ?? []
        let task = plan.task.trimmingCharacters(in: .whitespacesAndNewlines)
        let file = self.stageFile(p.path)
        do {
                self.busy("handing \(p.name) over…", follow: file) {
                    let d = ahtJSON(["handover", p.path, "--apply", "--json",
                                     "--status-file", file] + to
                                    + (task.isEmpty ? [] : ["--task", task])) ?? [:]
                    if let why = self.problems(d) {
                        self.note(p.path, "The handover did not go through:\n\n" + why)
                        return
                    }
                    let s = (d["sent"] as? [String: Any]) ?? [:]
                    var done = "Handed over to \(remote): \(s["files"] as? Int ?? 0) "
                        + "file(s) sent, \(byteText(s["wire_bytes"])) over the network."
                    if !task.isEmpty { done += "\nIt started on: " + task }
                    for w in (d["warnings"] as? [String]) ?? [] { done += "\n⚠ " + w }
                    self.note(p.path, done)
                }
        }
    }

    func takeBack(_ p: Project) {
        note(p.path, nil)
        busy("checking \(p.name)…") {
            let plan = ahtJSON(["reclaim", p.path, "--stop", "--json"]) ?? [:]
            DispatchQueue.main.async {
                if let why = self.problems(plan) {
                    self.note(p.path, "Cannot be taken back now:\n\n" + why)
                    return
                }
                let remote = plan["remote"] as? String ?? "the other machine"
                let n = ((plan["plan"] as? [String: Any])?["project"] as? [String: Int]) ?? [:]
                var body = "\(n["take"] ?? 0) file(s) changed there, \(n["new"] ?? 0) new, "
                    + "\(n["delete"] ?? 0) removed. Whatever they replace here is "
                    + "set aside, not deleted.\n"
                if plan["would_stop"] as? Bool ?? false {
                    body += "\nThe idle session on \(remote) is ended first.\n"
                }
                let both = ((plan["conflicts"] as? [String: [String]]) ?? [:])
                    .values.flatMap { $0 }
                var extra: [String] = []
                if both.isEmpty {
                    guard alert("Take “\(p.name)” back from \(remote)?", body,
                                confirm: "Take Back") else { return }
                } else {
                    body += "\nChanged on BOTH machines:\n"
                        + both.prefix(6).map { "• " + $0 }.joined(separator: "\n")
                        + "\n\nKeep Both leaves your version in place and puts the one "
                        + "from \(remote) next to it."
                    let pick = choose("Take “\(p.name)” back from \(remote)?", body,
                                      ["Keep Both", "Use the Versions from \(remote)", "Cancel"])
                    if pick == 2 { return }
                    if pick == 1 { extra = ["--prefer", "there"] }
                }
                let file = self.stageFile(p.path)
                self.busy("taking \(p.name) back…", follow: file) {
                    let d = ahtJSON(["reclaim", p.path, "--stop", "--apply", "--json",
                                     "--status-file", file] + extra) ?? [:]
                    if let why = self.problems(d) {
                        self.note(p.path, "Taking it back did not go through:\n\n" + why)
                        return
                    }
                    var done = "Back on this Mac, files and history."
                    if let aside = d["set_aside"] as? String {
                        done += "\nReplaced files are kept in: " + aside
                    }
                    if d["handed_over_session"] as? String != nil {
                        let last = (d["session_title"] as? String) ?? ""
                        done += "\nOn \(remote) you last worked in "
                            + (last.isEmpty ? "another session" : "“\(last)”")
                            + ", not in the session you handed over. Continue opens "
                            + "the latest one."
                    }
                    for w in (d["warnings"] as? [String]) ?? [] { done += "\n⚠ " + w }
                    self.note(p.path, done)
                }
            }
        }
    }

    // ---- across agents ----

    func refreshBoard() {
        guard !boardLoading else { return }
        boardLoading = true
        DispatchQueue.global(qos: .userInitiated).async {
            let d = ahtJSON(["board", "--json"]) ?? [:]
            let machines = ((d["machines"] as? [[String: Any]]) ?? []).map { m -> BoardMachine in
                let name = m["machine"] as? String ?? "?"
                let local = m["local"] as? Bool ?? false
                let rows = ((m["sessions"] as? [[String: Any]]) ?? []).map { r in
                    BoardRow(machine: name, local: local, agent: r["agent"] as? String ?? "?",
                             project: r["project"] as? String ?? "?",
                             status: r["status"] as? String ?? "?",
                             waitingFor: r["waiting_for"] as? String,
                             since: (r["since"] as? NSNumber)?.doubleValue,
                             handedOver: r["handed_over"] as? Bool ?? false)
                }.sorted { ($0.status == "waiting for you" ? 0 : 1, $0.project)
                           < ($1.status == "waiting for you" ? 0 : 1, $1.project) }
                return BoardMachine(name: name, reachable: m["reachable"] as? Bool ?? false,
                                    error: m["error"] as? String, rows: rows)
            }
            DispatchQueue.main.async {
                self.board = machines
                self.boardAt = Date()
                self.boardLoading = false
            }
        }
    }

    func runSearch() {
        let q = query.trimmingCharacters(in: .whitespaces)
        guard !q.isEmpty, !searching else { return }
        searching = true
        DispatchQueue.global(qos: .userInitiated).async {
            let d = ahtJSON(["search", "--json", "--limit", "40"]
                            + q.split(separator: " ").map(String.init)) ?? [:]
            let rows = ((d["results"] as? [[String: Any]]) ?? []).map { r -> SearchHit in
                let restore = r["restore"] as? [String: Any]
                return SearchHit(
                    agent: r["agent"] as? String ?? "?", session: r["session"] as? String ?? "",
                    project: r["project"] as? String,
                    title: (r["title"] as? String) ?? (r["session"] as? String ?? ""),
                    live: r["live"] as? Bool ?? true,
                    updated: (r["updated"] as? NSNumber)?.doubleValue,
                    snippets: ((r["hits"] as? [[String: Any]]) ?? []).map {
                        (role: $0["role"] as? String ?? "", text: $0["snippet"] as? String ?? "")
                    },
                    restoreUUID: restore?["uuid"] as? String,
                    restoreStamp: restore?["stamp"] as? String,
                    restoreProject: restore?["project"] as? String)
            }
            DispatchQueue.main.async {
                self.hits = rows
                self.searched = q
                self.searching = false
            }
        }
    }

    func resume(_ h: SearchHit) {
        guard let p = h.project else { return }
        background { aht(["resume-here", p, "--session", h.session, "--agent", h.agent]) }
    }

    func restore(_ h: SearchHit) {
        guard let p = h.restoreProject, let u = h.restoreUUID, let st = h.restoreStamp,
              alert("Bring this session back?",
                    "“\(h.title)” was deleted from \((p as NSString).lastPathComponent)'s "
                    + "history; a backup still holds it. Restoring adds what is missing "
                    + "and changes nothing that is there.", confirm: "Restore") else { return }
        busy("restoring…") {
            let r = aht(["restore", p, "--uuid", u, "--stamp", st, "--apply"])
            DispatchQueue.main.async {
                _ = alert(r.ok ? "Restored" : "Restoring did not work",
                          r.ok ? "Continue it from the result list." : r.out)
                if r.ok { self.runSearch() }
            }
        }
    }

    func show(_ path: String) {
        selection = path
        search = ""
        tab = .projects
    }

    func checkSecrets(_ p: Project?) {
        secretsFor = p?.path
        secrets = nil
        showSecrets = true
        DispatchQueue.global(qos: .userInitiated).async {
            let d = ahtJSON(["secrets", "--json"] + (p.map { [$0.path] } ?? [])) ?? [:]
            let rows = ((d["finds"] as? [[String: Any]]) ?? []).map {
                SecretFind(project: $0["project"] as? String ?? "?",
                           agent: $0["agent"] as? String ?? "?",
                           kind: $0["kind"] as? String ?? "?",
                           masked: $0["masked"] as? String ?? "",
                           whereFound: $0["where"] as? String ?? "",
                           t: ($0["t"] as? NSNumber)?.doubleValue,
                           times: $0["times"] as? Int ?? 1)
            }
            DispatchQueue.main.async { self.secrets = rows }
        }
    }

    func journal(_ p: Project) {
        busy("writing the journal…") {
            let d = ahtJSON(["journal", p.path, "--json"]) ?? [:]
            DispatchQueue.main.async {
                self.textSheet = TextSheet(title: "Journal: \(p.name)",
                                           text: d["markdown"] as? String
                                               ?? "The journal could not be written.",
                                           project: p)
            }
        }
    }

    func saveJournal(_ p: Project) {
        background {
            let d = ahtJSON(["journal", p.path, "--write", "--json"]) ?? [:]
            if let f = d["file"] as? String { sh("/usr/bin/open", [f]) }
        }
    }

    func openRules(_ p: Project) {
        DispatchQueue.global(qos: .userInitiated).async {
            let d = ahtJSON(["rules", p.path, "--json"]) ?? [:]
            DispatchQueue.main.async { self.rules = RulesView(project: p, status: d) }
        }
    }

    func unifyRules(_ p: Project, prefer: String?) {
        DispatchQueue.global(qos: .userInitiated).async {
            let d = ahtJSON(["rules", p.path, "--unify", "--apply", "--json"]
                            + (prefer.map { ["--prefer", $0] } ?? [])) ?? [:]
            let st = ahtJSON(["rules", p.path, "--json"]) ?? [:]
            var said = "Nothing was changed."
            if d["applied"] as? Bool ?? false {
                said = "Done. AGENTS.md now holds the rules and CLAUDE.md brings them in. "
                    + "The earlier files are kept in \(d["backup"] as? String ?? "~/.aht")."
            }
            DispatchQueue.main.async { self.rules = RulesView(project: p, status: st, result: said) }
        }
    }

    func switchAgent(_ p: Project, to target: String) {
        let label = AGENT_LABEL[target] ?? target
        note(p.path, nil)
        busy("checking \(p.name)…") {
            let plan = ahtJSON(["switch", p.path, "--to", target, "--json"]) ?? [:]
            DispatchQueue.main.async {
                if let why = self.problems(plan) {
                    self.note(p.path, "Cannot switch now:\n\n" + why)
                    return
                }
                let src = (plan["source"] as? [String: Any]) ?? [:]
                let from = AGENT_LABEL[src["agent"] as? String ?? ""] ?? "the other agent"
                var body = "\(label) continues the work of the latest \(from) session"
                    + ((src["title"] as? String).map { " (“\($0)”)" } ?? "") + ". aht writes "
                    + "a summary of where things stood into the project, and \(label) "
                    + "reads it first. The \(from) session stays as it is."
                if target == "kimi" {
                    body += "\n\nKimi reads the summary in a first run of its own; this "
                        + "takes a moment before the window opens."
                }
                for w in (plan["warnings"] as? [String]) ?? [] { body += "\n\n⚠ " + w }
                guard alert("Continue “\(p.name)” in \(label)?", body,
                            confirm: "Switch") else { return }
                self.busy("\(label) is reading the summary…") {
                    let d = ahtJSON(["switch", p.path, "--to", target, "--apply", "--json"]) ?? [:]
                    if let why = self.problems(d) {
                        self.note(p.path, "The switch did not go through:\n\n" + why)
                    } else {
                        self.note(p.path, "\(label) took over; its window is open. The summary "
                                  + "it read: " + (d["brief"] as? String ?? ""))
                    }
                }
            }
        }
    }

    func showGuide() {
        textSheet = TextSheet(title: "aht guide", text: guideText(), project: nil, wide: true)
    }

    func openSession(_ p: Project) {
        background { aht(["attach", p.path, "--window"]) }
    }

    func continueHere(_ p: Project, handedOver: Bool = false) {
        background { aht(["resume-here", p.path] + (handedOver ? ["--handed-over"] : [])) }
    }

    func reveal(_ p: Project) {
        NSWorkspace.shared.selectFile(p.path, inFileViewerRootedAtPath: "")
    }

    func keepInSync(_ p: Project, _ on: Bool) {
        let to = machine.map { ["--to", $0] } ?? []
        note(p.path, on ? "Kept in sync with \(machine ?? "the other machine"); the "
                          + "first copy runs in the background." : nil)
        background { aht(["mirror", p.path] + (on ? ["--on"] + to : ["--off"])) }
    }

    func syncNow() {
        busy("syncing…") {
            let rows = (ahtJSON(["mirror", "--run", "--json"])?["mirrored"]
                        as? [[String: Any]]) ?? []
            let ok = rows.filter { $0["status"] as? String == "synced" }.count
            notifyUser("Sync", rows.isEmpty ? "No project is kept in sync yet"
                       : "\(ok) synced" + (ok < rows.count
                                           ? ", \(rows.count - ok) skipped — see the log" : ""))
        }
    }

    func reconcile() {
        busy("looking for moved folders…") {
            let d = ahtJSON(["reconcile", "--notify"]) ?? [:]
            let am = (d["applied_moves"] as? [Any])?.count ?? 0
            let ac = (d["applied_copies"] as? [Any])?.count ?? 0
            let pend = ((d["moves"] as? [Any])?.count ?? 0)
                     + ((d["copies"] as? [Any])?.count ?? 0)
            notifyUser("Reconcile", am + ac > 0
                ? "\(am) project(s) relinked, \(ac) histor(ies) copied"
                : (pend > 0 ? "Changes found — answered via dialog or deferred"
                            : "Nothing to do — every history is in place"))
        }
    }

    func toggleWatch() {
        let on = running
        background {
            let uid = getuid()
            if on {
                sh("/bin/launchctl", ["bootout", "gui/\(uid)/\(WATCHER_LABEL)"])
                notifyUser("Watcher paused",
                           "The Claude SessionStart hook still protects projects you open")
            } else {
                sh("/bin/launchctl", ["bootstrap", "gui/\(uid)", WATCHER_PLIST])
                notifyUser("Watcher", "Watching resumed")
            }
        }
    }

    // ---- machines ----

    func use(_ m: Machine) {
        background { aht(["remote", "default", m.name]) }
    }

    func check(_ m: Machine) {
        busy("checking \(m.name)…") {
            let d = ahtJSON(["remote", "check", m.name, "--json"]) ?? [:]
            let row = ((d["machines"] as? [[String: Any]]) ?? []).first ?? [:]
            let rows = ((row["checks"] as? [[String: Any]]) ?? []).map {
                Check(name: $0["check"] as? String ?? "?", ok: $0["ok"] as? Bool ?? false,
                      needed: $0["needed"] as? Bool ?? true,
                      detail: $0["detail"] as? String ?? "", fix: $0["fix"] as? String)
            }
            DispatchQueue.main.async {
                self.checks[m.name] = rows
                self.checkError[m.name] = row["error"] as? String
                    ?? (d.isEmpty ? "aht gave no answer" : nil)
            }
        }
    }

    func remove(_ m: Machine) {
        let held = projects.filter { $0.awayRemote == m.name }.map { $0.path }
        if !held.isEmpty {
            _ = alert("\(m.name) still holds handed-over projects",
                      "Take these back first:\n" + held.map { "• " + $0 }.joined(separator: "\n"))
            return
        }
        guard alert("Remove \(m.name)?",
                    "aht forgets how to reach it. Nothing is deleted on either machine.",
                    confirm: "Remove") else { return }
        background { aht(["remote", "remove", m.name]) }
    }

    /// The login used for the machines so far is the best guess for the next.
    var usualLogin: String {
        machines.compactMap { m -> String? in
            m.target.contains("@") ? String(m.target.split(separator: "@")[0]) : nil
        }.first ?? NSUserName()
    }

    func add(_ n: NewMachine) {
        let name = n.name.trimmingCharacters(in: .whitespaces)
        let target = n.target.trimmingCharacters(in: .whitespaces)
        guard !name.isEmpty, !target.isEmpty else { return }
        busy("checking \(name)…") {
            let r = sh(PY, [ahtScript(), "remote", "add", name, target], mergeStderr: true)
            DispatchQueue.main.async {
                if r.ok {
                    self.check(Machine(name: name, target: target))
                } else {
                    _ = alert("\(name) could not be added", r.out)
                }
            }
        }
    }

    // ---- settings ----

    func set(_ key: String, _ value: String) {
        config[key] = (value == "true" || value == "false") ? (value == "true") as Any
                                                             : value as Any
        background { aht(["config", "--set", "\(key)=\(value)", "--no-reload"]) }
    }

    func backupNow() {
        busy("backing up the histories…") {
            let d = ahtJSON(["backup", "--json"]) ?? [:]
            let counts = d["counts"] as? [String: Int] ?? [:]
            notifyUser("History backup", counts.isEmpty ? "nothing to back up"
                : counts.sorted { $0.key < $1.key }
                        .map { "\($0.value) \($0.key)" }.joined(separator: ", "))
        }
    }

    func refreshBadges() {
        busy("refreshing the folder badges…") {
            let r = aht(["icons", "--refresh"])
            notifyUser("Folder badges",
                       r.out.split(separator: "\n").last.map(String.init) ?? "refreshed")
        }
    }

    func clearBadges() {
        guard alert("Clear every folder badge?",
                    "Removes the custom icon from tethered folders and git repos. "
                    + "Projects and histories are not affected; badges come back "
                    + "if you re-enable them.", confirm: "Clear") else { return }
        let savedAgent = flag("icons_agent")
        let savedGit = flag("icons_git")
        busy("clearing the folder badges…") {
            aht(["config", "--set", "icons_enabled=true", "icons_agent=false",
                 "icons_git=false", "--no-reload"])
            aht(["icons", "--refresh"])
            aht(["config", "--set", "icons_agent=\(savedAgent)",
                 "icons_git=\(savedGit)", "--no-reload"])
        }
    }

    func pickRoot(_ b: Backend) {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.showsHiddenFiles = true          // the stores live in dot-folders
        panel.message = "Choose the \(b.name) history store folder"
        guard panel.runModal() == .OK, let url = panel.url else { return }
        background { aht(["backends", "--set-root", "\(b.name)=\(url.path)"]) }
    }

    func resetRoots() {
        let names = backends.map { $0.name }
        guard !names.isEmpty,
              alert("Reset every agent CLI location to its default?",
                    "Only the store paths aht looks at are reset — "
                    + "no history is touched.", confirm: "Reset") else { return }
        background { aht(["backends", "--clear-root"] + names) }
    }

    func adopt() {
        busy("looking for projects…") {
            guard let d = ahtJSON(["adopt", "--json"]) else { return }
            let planned = (d["planned"] as? [Any])?.count ?? 0
            let already = d["already"] as? Int ?? 0
            let orphans = d["orphans_claude"] as? Int ?? 0
            DispatchQueue.main.async {
                if planned == 0 {
                    _ = alert("Nothing to adopt",
                              "\(already) project(s) are already tracked. "
                              + "\(orphans) claude histor(ies) have no matching "
                              + "folder — reconnect those with:  aht orphans --match")
                    return
                }
                guard alert("Start tracking \(planned) existing project(s)?",
                            "Each folder gets a marker (.aht/.project-id) and a "
                            + "registry entry so its agent histories follow it. "
                            + "Nothing is moved, renamed or deleted.",
                            confirm: "Adopt") else { return }
                self.busy("adopting…") { aht(["adopt", "--apply", "--json"]) }
            }
        }
    }

    func doctor() {
        busy("running the diagnostics…") {
            let r = aht(["doctor"])
            DispatchQueue.main.async {
                _ = alert("Diagnostics", r.out.isEmpty ? "doctor produced no output" : r.out)
            }
        }
    }

    func editConfig() {
        background {
            aht(["config"])   // ensures the file exists with current values
            sh("/usr/bin/open", ["-t", HOME + "/.aht/config.json"])
        }
    }

    func restartWatcher() {
        busy("restarting the watcher…") { aht(["reload"]) }
    }

    func openData() { sh("/usr/bin/open", [HOME + "/.aht"]) }
    func openLog() { sh("/usr/bin/open", ["-t", HOME + "/.aht/aht.log"]) }

    func setLoginItem(_ on: Bool) {
        let fm = FileManager.default
        if !on {
            sh("/bin/launchctl", ["bootout", "gui/\(getuid())/\(TRAY_LABEL)"])
            try? fm.removeItem(atPath: TRAY_PLIST)
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
        }
        loginItem = fm.fileExists(atPath: TRAY_PLIST)
    }

    // ---- installing from the app bundle ----

    func runInstall(_ res: String) {
        busy("setting up aht on this Mac…") {
            let r = sh(PY, [res + "/install.py", "--src", res,
                            "--keep-pid", String(getpid()),
                            "--tray-exe", Bundle.main.executablePath ?? ""],
                       mergeStderr: true)
            DispatchQueue.main.async {
                _ = alert(r.ok ? "aht is set up on this Mac" : "Install failed",
                          r.out.isEmpty ? (r.ok ? "Done." : "See ~/.aht/aht.log") : r.out)
            }
        }
    }

    func offerInstallIfNeeded() {
        guard let res = BUNDLE_RES else { return }
        let bundled = coreVersion(res + "/aht.py")
        let bundledStr = bundled.map(String.init).joined(separator: ".")
        let defaults = UserDefaults.standard
        if !FileManager.default.fileExists(atPath: TOOLS + "/aht.py") {
            // asked once per app version; the window keeps the option available
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
}

// ---- the window ----------------------------------------------------------------

struct MainView: View {
    @EnvironmentObject var m: AppModel

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 12) {
                Picker("", selection: $m.tab) {
                    ForEach(Tab.allCases) { t in
                        Text(t == .sessions && m.waiting > 0 ? "Sessions (\(m.waiting))"
                                                            : t.rawValue).tag(t)
                    }
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .frame(width: 470)
                Spacer()
                Button {
                    m.showGuide()
                } label: {
                    Label("Guide", systemImage: "questionmark.circle")
                }
                .help("What aht does, with examples")
                Text(m.summary).foregroundColor(.secondary)
                Circle().fill(m.running ? Color.green : Color.orange)
                    .frame(width: 8, height: 8)
                Text(m.running ? "watching" : "paused").foregroundColor(.secondary)
            }
            .padding(.horizontal, 16).padding(.vertical, 10)
            Divider()
            Group {
                switch m.tab {
                case .projects: ProjectsView()
                case .sessions: SessionsView()
                case .search: SearchView()
                case .machines: MachinesView()
                case .settings: SettingsView()
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            Divider()
            HStack(spacing: 10) {
                if let w = m.working {
                    if let p = m.percent {
                        ProgressView(value: p, total: 100).frame(width: 160)
                        Text("\(Int(p)) %").monospacedDigit().foregroundColor(.secondary)
                    } else {
                        ProgressView().controlSize(.small)
                    }
                    Text(w).lineLimit(1)
                } else {
                    Text("aht \(m.status["version"] as? String ?? "")")
                        .foregroundColor(.secondary)
                }
                Spacer()
            }
            .padding(.horizontal, 16).frame(height: 30)
        }
        .frame(minWidth: 820, minHeight: 560)
        .sheet(item: $m.adding) { n in AddMachineView(draft: n) }
        .sheet(item: $m.handoverPlan) { plan in HandoverSheet(plan: plan) }
        .sheet(item: $m.rules) { r in RulesSheet(r: r) }
        .sheet(item: $m.textSheet) { t in TextSheetView(t: t) }
        .sheet(isPresented: $m.showSecrets) { SecretsSheet() }
    }
}

struct ProjectsView: View {
    @EnvironmentObject var m: AppModel

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 10) {
                TextField("Search", text: $m.search)
                    .textFieldStyle(.roundedBorder).frame(width: 220)
                Spacer()
                if m.machines.count > 1 {
                    Picker("Machine", selection: Binding(
                        get: { m.machine ?? "" },
                        set: { n in m.machines.first { $0.name == n }.map(m.use) })) {
                        ForEach(m.machines) { Text($0.name).tag($0.name) }
                    }
                    .frame(width: 220)
                } else if let one = m.machine {
                    Text("Machine: \(one)").foregroundColor(.secondary)
                }
                Button("Sync Now") { m.syncNow() }
                    .disabled(m.working != nil || m.machine == nil)
                Button("Find Moved Folders") { m.reconcile() }
                    .disabled(m.working != nil)
            }
            .padding(.horizontal, 16).padding(.vertical, 8)

            Table(m.shown, selection: $m.selection) {
                TableColumn("Project") { p in
                    (Text(p.name).foregroundColor(p.exists ? .primary : .secondary)
                     + Text("   " + p.parent).foregroundColor(.secondary).font(.caption))
                        .lineLimit(1).help(p.path)
                }
                .width(min: 200, ideal: 280)
                TableColumn("Where") { p in
                    Text(p.place).foregroundColor(p.away != nil ? .blue
                                                  : (p.exists ? .primary : .secondary))
                }
                .width(min: 100, ideal: 150)
                TableColumn("In sync") { p in Text(p.sync) }
                    .width(min: 80, ideal: 120)
                TableColumn("Last used") { p in Text(ago(p.lastActivity)) }
                    .width(min: 90, ideal: 120)
                TableColumn("Agents") { p in
                    Text(p.agents.isEmpty ? "–" : p.agents.joined(separator: ", "))
                }
                .width(min: 80, ideal: 130)
            }

            Divider()
            DetailView().frame(height: 176)
        }
    }
}

struct DetailView: View {
    @EnvironmentObject var m: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let p = m.selected {
                HStack(alignment: .firstTextBaseline) {
                    Text(p.name).font(.headline)
                    Text(state(p)).foregroundColor(.secondary)
                    Spacer()
                }
                Text(p.path).font(.caption).foregroundColor(.secondary)
                    .lineLimit(1).truncationMode(.middle).textSelection(.enabled)
                HStack(spacing: 10) {
                    if p.away != nil {
                        Button("Take Back…") { m.takeBack(p) }
                            .keyboardShortcut(.defaultAction)
                        Button("Open Session") { m.openSession(p) }
                    } else if p.exists {
                        Button(m.machine.map { "Hand Over to \($0)…" } ?? "Hand Over…") {
                            m.handOver(p)
                        }
                        .disabled(m.machine == nil || !m.supported || p.open != nil)
                        Toggle("Keep in sync" + (p.mirror.map { " with \($0)" } ?? ""),
                               isOn: Binding(get: { p.mirror != nil },
                                             set: { m.keepInSync(p, $0) }))
                            .disabled(m.machine == nil || !m.supported)
                        Button("Continue Session") { m.continueHere(p) }
                            .disabled(p.sessions == 0)
                        Menu("Switch Agent") {
                            ForEach(m.agentCLIs, id: \.self) { a in
                                Button("Continue in \(AGENT_LABEL[a] ?? a)…") {
                                    m.switchAgent(p, to: a)
                                }
                            }
                        }
                        .fixedSize()
                        .disabled(p.sessions == 0 && p.agents.isEmpty)
                    }
                    Spacer()
                    if p.exists {
                        Menu("More") {
                            Button("Journal") { m.journal(p) }
                            Button("Project Rules…") { m.openRules(p) }
                            Button("Check for Secrets") { m.checkSecrets(p) }
                            Divider()
                            Button("Show in Finder") { m.reveal(p) }
                        }
                        .fixedSize()
                    }
                }
                .disabled(m.working != nil)
                if m.machine == nil && m.supported {
                    Text("Add a machine under Machines to hand projects over.")
                        .font(.callout).foregroundColor(.secondary)
                } else if let o = p.open, p.away == nil {
                    Text(o == "idle"
                         ? "An agent session is open in this project. Exit it (/exit) "
                           + "before handing the project over."
                         : o == "waiting"
                         ? "An agent session in this project is waiting for you. Answer it "
                           + "in its terminal; the project cannot be handed over until it "
                           + "has finished and is closed."
                         : "An agent is working in this project. It can be handed over "
                           + "once that has finished and the session is closed.")
                        .font(.callout).foregroundColor(.orange)
                }
                if let n = m.notes[p.path] {
                    ScrollView {
                        Text(n).font(.callout).textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                Spacer(minLength: 0)
            } else {
                Spacer()
                Text(m.loaded ? "Select a project to hand it over, take it back or "
                                + "keep it in sync." : "Loading…")
                    .foregroundColor(.secondary)
                    .frame(maxWidth: .infinity, alignment: .center)
                Spacer()
            }
        }
        .padding(.horizontal, 16).padding(.vertical, 10)
    }

    func state(_ p: Project) -> String {
        if let host = p.away {
            return "handed over to \(host)" + (p.awaySince.map { ", " + ago($0) } ?? "")
        }
        if !p.exists { return "the folder is gone; its histories are safe" }
        return "\(p.sessions) session(s), \(byteText(NSNumber(value: p.bytes))) of history"
    }
}

struct SessionsView: View {
    @EnvironmentObject var m: AppModel
    let tick = Timer.publish(every: 20, on: .main, in: .common).autoconnect()

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text("Agent sessions that are open now, here and on your other machines.")
                    .foregroundColor(.secondary)
                Spacer()
                if m.boardLoading { ProgressView().controlSize(.small) }
                if let at = m.boardAt {
                    Text("updated " + ago(NSNumber(value: at.timeIntervalSince1970)))
                        .foregroundColor(.secondary)
                }
                Button("Refresh") { m.refreshBoard() }.disabled(m.boardLoading)
            }
            .padding(.horizontal, 16).padding(.vertical, 8)
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    if m.board.isEmpty {
                        Text(m.boardLoading ? "Looking…" : "Nothing loaded yet.")
                            .foregroundColor(.secondary)
                    }
                    ForEach(m.board) { mc in
                        GroupBox(label: Text(mc.name).font(.headline)) {
                            VStack(alignment: .leading, spacing: 6) {
                                if !mc.reachable {
                                    Text("Not reachable right now — is it switched on, and is "
                                         + "Tailscale connected on this Mac?")
                                        .foregroundColor(.orange).help(mc.error ?? "")
                                } else if mc.rows.isEmpty {
                                    Text("No agent session open.").foregroundColor(.secondary)
                                }
                                ForEach(mc.rows) { r in BoardRowView(r: r) }
                            }
                            .padding(6).frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                }
                .padding(16)
            }
        }
        .onAppear { m.refreshBoard() }
        .onReceive(tick) { _ in if m.tab == .sessions { m.refreshBoard() } }
    }
}

struct BoardRowView: View {
    @EnvironmentObject var m: AppModel
    let r: BoardRow

    var color: Color {
        switch r.status {
        case "waiting for you": return .orange
        case "idle": return .secondary
        default: return .blue
        }
    }

    var body: some View {
        HStack(spacing: 10) {
            Circle().fill(color).frame(width: 8, height: 8)
            Text(r.name).frame(width: 200, alignment: .leading).lineLimit(1).help(r.project)
            Text(AGENT_LABEL[r.agent] ?? r.agent).foregroundColor(.secondary)
                .frame(width: 100, alignment: .leading)
            Text(r.state).foregroundColor(r.status == "waiting for you" ? .orange : .primary)
                .fontWeight(r.status == "waiting for you" ? .semibold : .regular).lineLimit(1)
            if let t = r.since {
                Text(ago(NSNumber(value: t))).foregroundColor(.secondary)
            }
            Spacer()
            if r.handedOver, let p = m.projects.first(where: { $0.away != nil
                                                          && r.project.hasSuffix($0.path) }) {
                Button("Open Session") { m.openSession(p) }.controlSize(.small)
            } else if r.local, m.projects.contains(where: { $0.path == r.project }) {
                Button("Show Project") { m.show(r.project) }.controlSize(.small)
            }
        }
    }
}

struct SearchView: View {
    @EnvironmentObject var m: AppModel

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 10) {
                TextField("Search every agent's sessions — \"a phrase\" in quotes",
                          text: $m.query)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit { m.runSearch() }
                Button("Search") { m.runSearch() }
                    .keyboardShortcut(.defaultAction)
                    .disabled(m.query.trimmingCharacters(in: .whitespaces).isEmpty || m.searching)
                if m.searching { ProgressView().controlSize(.small) }
            }
            .padding(.horizontal, 16).padding(.vertical, 8)
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 12) {
                    if let q = m.searched, m.hits.isEmpty, !m.searching {
                        Text("Nothing found for “\(q)”.").foregroundColor(.secondary)
                    }
                    if m.searched == nil {
                        Text("Claude Code, Kimi Code and Codex sessions are searched, also "
                             + "sessions that were deleted since and live on only in a "
                             + "history backup. Keys and passwords are not in the index.")
                            .foregroundColor(.secondary)
                    }
                    ForEach(m.hits) { h in SearchHitView(h: h) }
                }
                .padding(16)
            }
        }
    }
}

func marked(_ s: String) -> Text {
    // the core marks what matched with \u{02} … \u{03}
    var out = Text("")
    var bold = false
    var cur = ""
    for ch in s.replacingOccurrences(of: "\n", with: " ") {
        if ch == "\u{02}" || ch == "\u{03}" {
            out = out + (bold ? Text(cur).bold().foregroundColor(.primary) : Text(cur))
            cur = ""
            bold = ch == "\u{02}"
        } else {
            cur.append(ch)
        }
    }
    return out + (bold ? Text(cur).bold() : Text(cur))
}

struct SearchHitView: View {
    @EnvironmentObject var m: AppModel
    let h: SearchHit

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(h.title).font(.headline).lineLimit(1)
                Text(AGENT_LABEL[h.agent] ?? h.agent).foregroundColor(.secondary)
                if let t = h.updated { Text(ago(NSNumber(value: t))).foregroundColor(.secondary) }
                if !h.live {
                    Text("deleted — in a backup").font(.caption).foregroundColor(.orange)
                }
                Spacer()
                if h.live, let p = h.project, FileManager.default.fileExists(atPath: p) {
                    Button("Resume") { m.resume(h) }.controlSize(.small)
                    Button("Show Project") { m.show(p) }.controlSize(.small)
                        .disabled(!m.projects.contains { $0.path == p })
                } else if !h.live, h.restoreProject != nil {
                    Button("Restore…") { m.restore(h) }.controlSize(.small)
                }
            }
            if let p = h.project {
                Text(p).font(.caption).foregroundColor(.secondary).lineLimit(1)
                    .truncationMode(.middle)
            }
            ForEach(Array(h.snippets.enumerated()), id: \.offset) { _, sn in
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text(sn.role == "user" ? "you" : sn.role).font(.caption)
                        .foregroundColor(.secondary).frame(width: 36, alignment: .trailing)
                    marked(sn.text).foregroundColor(.secondary).lineLimit(2)
                }
            }
        }
        .padding(8)
        .background(Color.primary.opacity(0.03))
        .cornerRadius(6)
    }
}

struct HandoverSheet: View {
    @EnvironmentObject var m: AppModel
    @State var plan: HandoverPlan

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Hand “\(plan.project.name)” over to \(plan.remote)?").font(.headline)
            Text(plan.body).frame(maxWidth: .infinity, alignment: .leading)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
            Text("A task to start on over there (optional)").padding(.top, 6)
            TextEditor(text: $plan.task)
                .font(.body).frame(height: 70)
                .overlay(RoundedRectangle(cornerRadius: 4).stroke(Color.secondary.opacity(0.3)))
            Text("With a task, the session begins working on it as soon as it has resumed; "
                 + "you can follow it and answer its questions from the Claude app.")
                .font(.caption).foregroundColor(.secondary)
            HStack {
                Spacer()
                Button("Cancel") { m.handoverPlan = nil }.keyboardShortcut(.cancelAction)
                Button("Hand Over") {
                    let p = plan
                    m.handoverPlan = nil
                    m.confirmHandover(p)
                }
                .keyboardShortcut(.defaultAction)
            }
        }
        .padding(20).frame(width: 520)
    }
}

struct RulesSheet: View {
    @EnvironmentObject var m: AppModel
    let r: RulesView

    var body: some View {
        let st = r.status
        let state = st["state"] as? String ?? ""
        let files = (st["files"] as? [String: [String: Any]]) ?? [:]
        let readers = (st["readers"] as? [String: String]) ?? [:]
        VStack(alignment: .leading, spacing: 12) {
            Text("Project rules: \(r.project.name)").font(.headline)
            Text(st["summary"] as? String ?? "…")
                .fixedSize(horizontal: false, vertical: true)
            GroupBox(label: Text("Files")) {
                VStack(alignment: .leading, spacing: 4) {
                    if files.isEmpty { Text("none").foregroundColor(.secondary) }
                    ForEach(files.keys.sorted(), id: \.self) { f in
                        HStack {
                            Text(f).frame(width: 150, alignment: .leading)
                            Text("\((files[f]?["bytes"] as? Int) ?? 0) bytes")
                                .foregroundColor(.secondary)
                            if files[f]?["imports_agents"] as? Bool ?? false {
                                Text("brings in AGENTS.md").foregroundColor(.secondary)
                            }
                        }
                    }
                }
                .padding(6).frame(maxWidth: .infinity, alignment: .leading)
            }
            GroupBox(label: Text("Which file each agent reads")) {
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(readers.keys.sorted(), id: \.self) { a in
                        HStack(alignment: .firstTextBaseline) {
                            Text(AGENT_LABEL[a] ?? a).frame(width: 110, alignment: .leading)
                            Text(readers[a] ?? "").foregroundColor(.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
                .padding(6).frame(maxWidth: .infinity, alignment: .leading)
            }
            if let said = r.result {
                Text(said).foregroundColor(.secondary).fixedSize(horizontal: false, vertical: true)
            }
            HStack {
                if state == "claude-only" || state == "twins" {
                    Button("Make AGENTS.md the One Set of Rules") {
                        m.unifyRules(r.project, prefer: nil)
                    }
                } else if state == "split" {
                    Text("Keep:")
                    Button("CLAUDE.md's") { m.unifyRules(r.project, prefer: "claude") }
                    Button("AGENTS.md's") { m.unifyRules(r.project, prefer: "agents") }
                    Button("Both") { m.unifyRules(r.project, prefer: "both") }
                }
                Spacer()
                Button("Close") { m.rules = nil }.keyboardShortcut(.cancelAction)
            }
        }
        .padding(20).frame(width: 560)
    }
}

struct TextSheetView: View {
    @EnvironmentObject var m: AppModel
    let t: TextSheet

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(t.title).font(.headline)
            ScrollView {
                // the sheet already carries the document's title
                MarkdownView(text: t.text, skipTitle: true).padding(.trailing, 12)
            }
            HStack {
                Button("Copy") {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(t.text, forType: .string)
                }
                if let p = t.project {
                    Button("Save in the Project and Open") { m.saveJournal(p) }
                }
                Spacer()
                Button("Close") { m.textSheet = nil }.keyboardShortcut(.cancelAction)
            }
        }
        .padding(20).frame(width: t.wide ? 780 : 720, height: t.wide ? 680 : 560)
    }
}

/// The Markdown aht writes and ships (the guide, journals), as blocks:
/// headings, paragraphs, lists, quoted examples and code.  Source lines that
/// were wrapped for the editor are joined again.
struct MdBlock: Identifiable {
    let id: Int
    let kind: String            // h1 h2 h3 p li ol quote code
    let text: String
    var mark = ""
}

func mdBlocks(_ text: String) -> [MdBlock] {
    var out: [MdBlock] = []
    var kind = "", buf = "", mark = ""
    var code: [String]? = nil
    func flush() {
        if !kind.isEmpty {
            out.append(MdBlock(id: out.count, kind: kind,
                               text: buf.trimmingCharacters(in: .whitespaces), mark: mark))
        }
        kind = ""; buf = ""; mark = ""
    }
    for raw in text.components(separatedBy: "\n") {
        if code != nil {
            if raw.hasPrefix("```") {
                out.append(MdBlock(id: out.count, kind: "code", text: code!.joined(separator: "\n")))
                code = nil
            } else {
                code!.append(raw)
            }
            continue
        }
        let line = raw.trimmingCharacters(in: .whitespaces)
        if raw.hasPrefix("```") { flush(); code = []; continue }
        if line.isEmpty { if kind != "quote" { flush() }; continue }
        for (p, k) in [("### ", "h3"), ("## ", "h2"), ("# ", "h1")] where raw.hasPrefix(p) {
            flush()
            out.append(MdBlock(id: out.count, kind: k, text: String(raw.dropFirst(p.count))))
            kind = "done"
            break
        }
        if kind == "done" { kind = ""; continue }
        if raw.hasPrefix(">") {
            let t = raw.dropFirst().trimmingCharacters(in: .whitespaces)
            if kind != "quote" { flush(); kind = "quote" }
            buf += t.isEmpty ? "\n\n" : ((buf.isEmpty || buf.hasSuffix("\n\n")) ? t : " " + t)
            continue
        }
        if kind == "quote" { flush() }
        if raw.hasPrefix("- ") {
            flush(); kind = "li"; buf = String(raw.dropFirst(2)); continue
        }
        if let r = raw.range(of: #"^\d+\. "#, options: .regularExpression) {
            flush(); kind = "ol"; mark = String(raw[r]).trimmingCharacters(in: .whitespaces)
            buf = String(raw[r.upperBound...]); continue
        }
        if raw.hasPrefix("  ") && (kind == "li" || kind == "ol") {
            buf += " " + line; continue
        }
        if kind == "p" { buf += " " + line } else { flush(); kind = "p"; buf = line }
    }
    if let c = code { out.append(MdBlock(id: out.count, kind: "code", text: c.joined(separator: "\n"))) }
    flush()
    return out
}

func inlineMd(_ s: String) -> Text {
    Text((try? AttributedString(markdown: s, options: .init(
        interpretedSyntax: .inlineOnlyPreservingWhitespace))) ?? AttributedString(s))
}

struct MarkdownView: View {
    let text: String
    var skipTitle = false

    var body: some View {
        LazyVStack(alignment: .leading, spacing: 8) {
            ForEach(mdBlocks(text).filter { !(skipTitle && $0.kind == "h1") }) { b in
                block(b)
            }
        }
        .textSelection(.enabled)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    @ViewBuilder func block(_ b: MdBlock) -> some View {
        switch b.kind {
        case "h1": inlineMd(b.text).font(.title.bold()).padding(.bottom, 2)
        case "h2": inlineMd(b.text).font(.title2.bold()).padding(.top, 14)
        case "h3": inlineMd(b.text).font(.headline).padding(.top, 6)
        case "li", "ol":
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text(b.kind == "li" ? "•" : b.mark).frame(minWidth: 12, alignment: .trailing)
                inlineMd(b.text).fixedSize(horizontal: false, vertical: true)
            }
            .padding(.leading, 6)
        case "quote":
            HStack(alignment: .top, spacing: 10) {
                Rectangle().fill(Color.accentColor.opacity(0.6)).frame(width: 3)
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(Array(b.text.components(separatedBy: "\n\n").enumerated()),
                            id: \.offset) { _, para in
                        inlineMd(para).fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
            .padding(10)
            .background(Color.accentColor.opacity(0.06))
            .cornerRadius(6)
        case "code":
            Text(b.text).font(.system(.callout, design: .monospaced))
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(10)
                .background(Color.primary.opacity(0.05))
                .cornerRadius(6)
        default: inlineMd(b.text).fixedSize(horizontal: false, vertical: true)
        }
    }
}

/// The guide that ships with aht (GUIDE.md): from the app bundle, the
/// installed core, or a checkout.
func guideText() -> String {
    var c: [String] = []
    if let r = BUNDLE_RES { c.append(r + "/GUIDE.md") }
    c.append(TOOLS + "/GUIDE.md")
    let here = URL(fileURLWithPath: CommandLine.arguments[0]).deletingLastPathComponent()
    c += [here.appendingPathComponent("GUIDE.md").path,
          here.appendingPathComponent("../GUIDE.md").path]
    for p in c {
        if let t = try? String(contentsOfFile: p, encoding: .utf8) { return t }
    }
    return "# aht guide\n\nThe guide was not found. It is GUIDE.md next to aht.py, "
        + "and at https://github.com/havurgiray/agent-history-tether."
}

struct SecretsSheet: View {
    @EnvironmentObject var m: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(m.secretsFor.map { "Secrets in \(($0 as NSString).lastPathComponent)'s history" }
                 ?? "Secrets in every agent history").font(.headline)
            Text("What looks like a key, a token or a password in the agents' own history "
                 + "files, shown masked. aht never changes those files; a key that ended up "
                 + "there is best replaced where it was issued.")
                .foregroundColor(.secondary).fixedSize(horizontal: false, vertical: true)
            if let rows = m.secrets {
                if rows.isEmpty {
                    Text("Nothing found.").padding(.vertical, 20)
                }
                Table(rows) {
                    TableColumn("Project") { f in
                        Text((f.project as NSString).lastPathComponent).help(f.project)
                    }
                    TableColumn("Looks like") { f in Text(f.kind) }
                    TableColumn("Value") { f in Text(f.masked).font(.system(.body, design: .monospaced)) }
                    TableColumn("Where") { f in
                        Text(f.whereFound + (f.times > 1 ? " (\(f.times)×)" : ""))
                    }
                    TableColumn("When") { f in
                        Text((AGENT_LABEL[f.agent] ?? f.agent) + (f.t.map { ", " + ago(NSNumber(value: $0)) } ?? ""))
                    }
                }
            } else {
                HStack { ProgressView().controlSize(.small); Text("Reading the histories…") }
                    .padding(.vertical, 20)
                Spacer()
            }
            HStack {
                Spacer()
                Button("Close") { m.showSecrets = false }.keyboardShortcut(.cancelAction)
            }
        }
        .padding(20).frame(width: 820, height: 480)
    }
}

struct MachinesView: View {
    @EnvironmentObject var m: AppModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                if !m.supported {
                    Text("Handover is not available in this build.")
                        .foregroundColor(.secondary)
                }
                if m.machines.isEmpty {
                    Text("No other machine yet. Add one you reach over ssh without a "
                         + "password prompt.").foregroundColor(.secondary)
                }
                ForEach(m.machines) { mc in
                    GroupBox {
                        VStack(alignment: .leading, spacing: 8) {
                            HStack(spacing: 10) {
                                Text(mc.name).font(.headline)
                                Text(mc.target).foregroundColor(.secondary)
                                    .textSelection(.enabled)
                                if mc.name == m.machine {
                                    Text("projects go here").font(.caption)
                                        .padding(.horizontal, 6).padding(.vertical, 2)
                                        .background(Color.accentColor.opacity(0.18))
                                        .cornerRadius(4)
                                }
                                Spacer()
                                if mc.name != m.machine {
                                    Button("Use for Handover") { m.use(mc) }
                                }
                                Button("Check") { m.check(mc) }
                                Button("Remove…") { m.remove(mc) }
                            }
                            .disabled(m.working != nil)
                            if let e = m.checkError[mc.name] {
                                Text("✗ " + e).foregroundColor(.red)
                            }
                            ForEach(m.checks[mc.name] ?? []) { c in CheckRow(c: c) }
                        }
                        .padding(6)
                    }
                }
                GroupBox(label: Text("Add a machine")) {
                    VStack(alignment: .leading, spacing: 6) {
                        if m.found.isEmpty {
                            Text("Nothing found on your network or in ~/.ssh/config.")
                                .foregroundColor(.secondary)
                        }
                        ForEach(m.found) { f in
                            HStack {
                                Text(f.host)
                                Text(f.note).foregroundColor(.secondary)
                                Spacer()
                                Button("Add…") {
                                    m.adding = NewMachine(name: f.host,
                                                          target: "\(m.usualLogin)@\(f.host)")
                                }
                            }
                        }
                        HStack {
                            Spacer()
                            Button("Add Another…") {
                                m.adding = NewMachine(name: "", target: "")
                            }
                        }
                    }
                    .padding(6)
                    .disabled(m.working != nil)
                }
            }
            .padding(16)
        }
    }
}

struct CheckRow: View {
    let c: Check

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text(c.ok ? "✓" : (c.needed ? "✗" : "·"))
                    .foregroundColor(c.ok ? .green : (c.needed ? .red : .secondary))
                    .frame(width: 14)
                Text(c.name)
                Text(c.detail).foregroundColor(.secondary).lineLimit(1)
            }
            if let fix = c.fix {
                HStack(spacing: 8) {
                    Text(fix).font(.system(.callout, design: .monospaced))
                        .textSelection(.enabled).lineLimit(2)
                    Button("Copy") {
                        NSPasteboard.general.clearContents()
                        NSPasteboard.general.setString(fix, forType: .string)
                    }
                    .controlSize(.small)
                }
                .padding(.leading, 20)
            }
        }
    }
}

struct AddMachineView: View {
    @EnvironmentObject var m: AppModel
    @State var draft: NewMachine

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Add a machine").font(.headline)
            Text("A machine you reach over ssh without a password prompt. aht checks "
                 + "it and tells you what it still needs.")
                .foregroundColor(.secondary).fixedSize(horizontal: false, vertical: true)
            TextField("a name for it", text: $draft.name).textFieldStyle(.roundedBorder)
            TextField("user@host", text: $draft.target).textFieldStyle(.roundedBorder)
            HStack {
                Spacer()
                Button("Cancel") { m.adding = nil }.keyboardShortcut(.cancelAction)
                Button("Check and Add") {
                    let d = draft
                    m.adding = nil
                    m.add(d)
                }
                .keyboardShortcut(.defaultAction)
                .disabled(draft.name.trimmingCharacters(in: .whitespaces).isEmpty
                          || draft.target.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }
        .padding(20).frame(width: 380)
    }
}

struct SettingsView: View {
    @EnvironmentObject var m: AppModel

    func choice(_ title: String, _ key: String, _ options: [(String, String)]) -> some View {
        HStack {
            Text(title).frame(width: 170, alignment: .leading)
            Picker("", selection: Binding(get: { m.text(key, options[0].0) },
                                          set: { m.set(key, $0) })) {
                ForEach(options, id: \.0) { Text($0.1).tag($0.0) }
            }
            .labelsHidden().fixedSize()
            Spacer()
        }
    }

    func toggle(_ title: String, _ key: String) -> some View {
        Toggle(title, isOn: Binding(get: { m.flag(key) },
                                    set: { m.set(key, $0 ? "true" : "false") }))
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                GroupBox(label: Text("When folders change")) {
                    VStack(alignment: .leading, spacing: 8) {
                        choice("A folder moves", "move_policy",
                               [("ask", "Ask me"), ("apply", "Relink automatically"),
                                ("decline", "Never relink (remember the no)"),
                                ("ignore", "Do nothing")])
                        choice("A folder is copied", "copy_policy",
                               [("ask", "Ask me"), ("duplicate", "Duplicate the history"),
                                ("independent", "Fresh identity, no history"),
                                ("ignore", "Do nothing")])
                        choice("A new project is found", "new_policy",
                               [("apply", "Start tracking it"), ("ignore", "Leave it alone")])
                    }
                    .padding(6).frame(maxWidth: .infinity, alignment: .leading)
                }
                GroupBox(label: Text("Histories")) {
                    HStack(spacing: 16) {
                        toggle("Notifications", "notifications")
                        toggle("Back up histories automatically", "backup_enabled")
                        Spacer()
                        Button("Check All for Secrets…") { m.checkSecrets(nil) }
                        Button("Back Up Now") { m.backupNow() }
                    }
                    .padding(6)
                }
                GroupBox(label: Text("Folder badges")) {
                    HStack(spacing: 16) {
                        toggle("Badge folders", "icons_enabled")
                        toggle("Agent symbols", "icons_agent")
                        toggle("Git “+”", "icons_git")
                        Spacer()
                        Button("Refresh All") { m.refreshBadges() }
                        Button("Clear All…") { m.clearBadges() }
                    }
                    .padding(6)
                }
                GroupBox(label: Text("Handover")) {
                    VStack(alignment: .leading, spacing: 8) {
                        toggle("Reachable from the Claude app (Remote Control)",
                               "handover_remote_control")
                        toggle("Compress what is sent", "handover_compress")
                        toggle("Use mosh to open a session when it gets through",
                               "handover_mosh")
                        toggle("A folder trusted here is trusted on the other machine",
                               "handover_carry_trust")
                    }
                    .padding(6).frame(maxWidth: .infinity, alignment: .leading)
                }
                GroupBox(label: Text("Where each agent keeps its history")) {
                    VStack(alignment: .leading, spacing: 6) {
                        ForEach(m.backends) { b in
                            HStack {
                                Text(b.found ? "✓" : "·")
                                    .foregroundColor(b.found ? .green : .secondary)
                                    .frame(width: 14)
                                Text(b.name).frame(width: 90, alignment: .leading)
                                Text(b.root).foregroundColor(.secondary)
                                    .lineLimit(1).truncationMode(.middle)
                                if b.source != "default" {
                                    Text(b.source).font(.caption).foregroundColor(.secondary)
                                }
                                Spacer()
                                Button("Choose…") { m.pickRoot(b) }.controlSize(.small)
                            }
                        }
                        HStack {
                            Spacer()
                            Button("Reset All to Defaults") { m.resetRoots() }
                        }
                    }
                    .padding(6)
                }
                GroupBox(label: Text("This Mac")) {
                    VStack(alignment: .leading, spacing: 10) {
                        Toggle("Start aht in the menu bar at login",
                               isOn: Binding(get: { m.loginItem },
                                             set: { m.setLoginItem($0) }))
                        HStack(spacing: 10) {
                            Button("Adopt This Mac's Projects…") { m.adopt() }
                            if let res = BUNDLE_RES {
                                Button("Reinstall or Update aht…") { m.runInstall(res) }
                            }
                            Button("Restart Watcher") { m.restartWatcher() }
                            Spacer()
                        }
                        HStack(spacing: 10) {
                            Button("Run Diagnostics") { m.doctor() }
                            Button("Open Log") { m.openLog() }
                            Button("Open Data Folder") { m.openData() }
                            Button("Edit Config File") { m.editConfig() }
                            Spacer()
                        }
                        Text("aht keeps every AI coding agent's per-project history "
                             + "connected to its folder. History is never deleted or "
                             + "overwritten. Data: ~/.aht")
                            .font(.callout).foregroundColor(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(6).frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            .padding(16)
            .disabled(m.working != nil)
        }
    }
}

// ---- the app -------------------------------------------------------------------

final class TrayApp: NSObject, NSApplicationDelegate, NSMenuDelegate, NSWindowDelegate {
    var item: NSStatusItem!
    let menu = NSMenu()
    let model = AppModel()
    var window: NSWindow?

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
        model.refresh()
        Timer.scheduledTimer(withTimeInterval: 20, repeats: true) { _ in
            self.model.refresh()
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
            self.model.offerInstallIfNeeded()
        }
    }

    // opening aht.app while it runs brings the window up
    func applicationShouldHandleReopen(_ sender: NSApplication,
                                       hasVisibleWindows flag: Bool) -> Bool {
        openWindow()
        return false
    }

    func menuWillOpen(_ menu: NSMenu) { model.refresh() }

    func menuNeedsUpdate(_ menu: NSMenu) {
        menu.removeAllItems()
        let st = model.status
        add(disabled: "aht \(st["version"] as? String ?? "?") — "
            + (model.running ? "watching" : "PAUSED"))
        add(disabled: model.summary)
        let away = model.projects.filter { $0.away != nil }
        if !away.isEmpty {
            let hosts = Set(away.compactMap { $0.away }).sorted()
            add(disabled: "\(away.count) handed over to " + hosts.joined(separator: ", "))
        }
        if model.waiting > 0 {
            add(disabled: "⚠ \(model.waiting) session\(model.waiting == 1 ? "" : "s") "
                + "waiting for you")
        }
        if let w = model.working { add(disabled: "⏳ " + w) }
        menu.addItem(.separator())
        add("Open aht…", #selector(openWindow), key: "o")
        add("Guide", #selector(openGuide))
        menu.addItem(.separator())
        add("Find Moved Folders Now", #selector(reconcile), key: "r")
        add(model.running ? "Pause Watching" : "Resume Watching", #selector(toggleWatch))
        menu.addItem(.separator())
        add(model.running ? "Quit aht (the watcher keeps running)" : "Quit aht",
            #selector(quit), key: "q")
    }

    func add(_ title: String, _ sel: Selector, key: String = "") {
        let i = NSMenuItem(title: title, action: sel, keyEquivalent: key)
        i.target = self
        menu.addItem(i)
    }
    func add(disabled title: String) {
        let i = NSMenuItem(title: title, action: nil, keyEquivalent: "")
        i.isEnabled = false
        menu.addItem(i)
    }

    @objc func reconcile() { model.reconcile() }
    @objc func toggleWatch() { model.toggleWatch() }
    @objc func quit() { NSApp.terminate(nil) }

    @objc func openGuide() {
        openWindow()
        model.showGuide()
    }

    @objc func openWindow() {
        if window == nil {
            let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 900, height: 620),
                             styleMask: [.titled, .closable, .miniaturizable, .resizable],
                             backing: .buffered, defer: false)
            w.title = "aht"
            w.isReleasedWhenClosed = false
            w.contentView = NSHostingView(rootView: MainView().environmentObject(model))
            w.setFrameAutosaveName("aht-main")
            w.center()
            w.delegate = self
            window = w
        }
        // a window needs what a menu bar item does not: a Dock icon to come
        // back to, and an Edit menu for copy and paste in its fields
        NSApp.setActivationPolicy(.regular)
        NSApp.mainMenu = mainMenu()
        model.refresh()
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func windowWillClose(_ n: Notification) {
        NSApp.setActivationPolicy(.accessory)
    }

    func mainMenu() -> NSMenu {
        let bar = NSMenu()
        let appItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "Close Window", action: #selector(NSWindow.performClose(_:)),
                        keyEquivalent: "w")
        appMenu.addItem(withTitle: "Quit aht", action: #selector(NSApplication.terminate(_:)),
                        keyEquivalent: "q")
        appItem.submenu = appMenu
        bar.addItem(appItem)
        let editItem = NSMenuItem()
        let edit = NSMenu(title: "Edit")
        edit.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)),
                     keyEquivalent: "a")
        editItem.submenu = edit
        bar.addItem(editItem)
        let helpItem = NSMenuItem()
        let help = NSMenu(title: "Help")
        let g = NSMenuItem(title: "aht Guide", action: #selector(openGuide), keyEquivalent: "?")
        g.target = self
        help.addItem(g)
        helpItem.submenu = help
        bar.addItem(helpItem)
        NSApp.helpMenu = help
        return bar
    }
}

// selftest: everything that can run headless (used by CI/dev boxes)
if CommandLine.arguments.contains("--selftest") {
    let r = aht(["version"])
    print("TRAY SELFTEST \(r.ok ? "OK" : "FAIL") — core: \(r.out.trimmingCharacters(in: .whitespacesAndNewlines))")
    exit(r.ok ? 0 : 1)
}

// snapshot: the window's tabs (and its dialogs) as PNG files, to look at a
// layout without clicking through it (needs a login session; nothing changes)
//   --snapshot DIR [--select-first] [--query WORDS]
func snapshot(_ view: some View, _ file: String, _ size: NSSize) {
    let host = NSHostingView(rootView: view)
    let w = NSWindow(contentRect: NSRect(origin: .zero, size: size),
                     styleMask: [.titled], backing: .buffered, defer: false)
    w.contentView = host
    w.layoutIfNeeded()
    RunLoop.main.run(until: Date().addingTimeInterval(0.8))
    host.layoutSubtreeIfNeeded()
    guard let rep = host.bitmapImageRepForCachingDisplay(in: host.bounds) else { return }
    host.cacheDisplay(in: host.bounds, to: rep)
    try? rep.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: file))
    print("wrote \(file)")
}

if let i = CommandLine.arguments.firstIndex(of: "--snapshot"),
   i + 1 < CommandLine.arguments.count {
    let args = CommandLine.arguments
    let dir = args[i + 1]
    try? FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
    NSApplication.shared.setActivationPolicy(.accessory)
    let model = AppModel()
    model.take(AppModel.load())
    if args.contains("--select-first") { model.selection = model.shown.first?.path }
    if let q = args.firstIndex(of: "--query"), q + 1 < args.count {
        model.query = args[q + 1]
        model.runSearch()
        let end = Date().addingTimeInterval(30)
        while (model.searching || model.searched == nil) && Date() < end {
            RunLoop.main.run(until: Date().addingTimeInterval(0.2))
        }
    }
    let size = NSSize(width: 900, height: 620)
    for tab in Tab.allCases {
        model.tab = tab
        snapshot(MainView().environmentObject(model), dir + "/\(tab.rawValue.lowercased()).png", size)
    }
    snapshot(TextSheetView(t: TextSheet(title: "aht guide", text: guideText(), project: nil, wide: true))
                .environmentObject(model), dir + "/sheet-guide.png", NSSize(width: 780, height: 680))
    if let p = model.selected {                  // the dialogs, for the selected project
        let j = ahtJSON(["journal", p.path, "--json"]) ?? [:]
        snapshot(TextSheetView(t: TextSheet(title: "Journal: \(p.name)",
                                             text: j["markdown"] as? String ?? "", project: p))
                    .environmentObject(model), dir + "/sheet-journal.png", NSSize(width: 720, height: 560))
        snapshot(RulesSheet(r: RulesView(project: p, status: ahtJSON(["rules", p.path, "--json"]) ?? [:]))
                    .environmentObject(model), dir + "/sheet-rules.png", NSSize(width: 560, height: 460))
        snapshot(HandoverSheet(plan: HandoverPlan(project: p, remote: model.machine ?? "homebox",
                                                  body: "12 file(s) to send (1.2 MB), history 3.4 MB.\nSession: the one used last\n\nThe session is resumed there and this folder is marked as away until you take it back."))
                    .environmentObject(model), dir + "/sheet-handover.png", NSSize(width: 520, height: 470))
        model.secretsFor = p.path
        let d = ahtJSON(["secrets", p.path, "--json"]) ?? [:]
        model.secrets = ((d["finds"] as? [[String: Any]]) ?? []).map {
            SecretFind(project: $0["project"] as? String ?? "?", agent: $0["agent"] as? String ?? "?",
                       kind: $0["kind"] as? String ?? "?", masked: $0["masked"] as? String ?? "",
                       whereFound: $0["where"] as? String ?? "",
                       t: ($0["t"] as? NSNumber)?.doubleValue, times: $0["times"] as? Int ?? 1)
        }
        snapshot(SecretsSheet().environmentObject(model), dir + "/sheet-secrets.png",
                 NSSize(width: 820, height: 480))
    }
    exit(0)
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let delegate = TrayApp()
app.delegate = delegate
app.run()
