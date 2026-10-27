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
//   --chimes DIR    write aht's own chimes into DIR as WAV files
//   --spotlight-check WORD   are sessions with WORD in the title in Spotlight?
//   aht://…         open parts of the window from Shortcuts, a link or a script:
//                   aht://search?q=WORDS, aht://sessions, aht://loose-ends,
//                   aht://report, aht://project?path=P, aht://changes?path=P,
//                   aht://journal?path=P, aht://undo?path=P,
//                   aht://switch?path=P&to=kimi (&resume=1: its own session),
//                   aht://switch?path=P&back=1 (Hand Back; &to=claude: to that agent),
//                   aht://resume?path=P&session=ID,
//                   aht://getting-started, aht://welcome, aht://update
//                   (whatever starts an agent or changes files asks first)
import AppKit
import Carbon.HIToolbox
import CoreSpotlight
import Foundation
import SwiftUI
import UniformTypeIdentifiers
import UserNotifications

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
    // the screenshots: a core of their choosing (HOME does not move TOOLS,
    // since NSHomeDirectory() ignores it)
    if let c = ProcessInfo.processInfo.environment["AHT_CORE"], fm.fileExists(atPath: c) {
        return c
    }
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

/// `sh` that keeps stderr apart from stdout: the JSON comes on stdout, and
/// stderr says what went wrong when it does not.
func shWithStderr(_ exe: String, _ args: [String]) -> (ok: Bool, out: String, err: String) {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: exe)
    p.arguments = args
    let out = Pipe(), err = Pipe()
    p.standardOutput = out
    p.standardError = err
    do { try p.run() } catch { return (false, "", error.localizedDescription) }
    var errData = Data()
    let reading = DispatchGroup()               // both pipes at once, so neither fills up
    DispatchQueue.global().async(group: reading) {
        errData = err.fileHandleForReading.readDataToEndOfFile()
    }
    let outData = out.fileHandleForReading.readDataToEndOfFile()
    reading.wait()
    p.waitUntilExit()
    return (p.terminationStatus == 0, String(data: outData, encoding: .utf8) ?? "",
            String(data: errData, encoding: .utf8) ?? "")
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

/// A notice from the app itself: a click on it opens aht, not Script Editor.
func notifyUser(_ title: String, _ msg: String) {
    let c = UNMutableNotificationContent()
    c.title = title
    c.body = msg
    UNUserNotificationCenter.current().add(
        UNNotificationRequest(identifier: UUID().uuidString, content: c, trigger: nil)) { _ in }
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

/// One of the core's timestamps (ISO text or seconds since 1970) as a date.
func moment(_ any: Any?) -> Date? {
    if let n = any as? NSNumber, n.doubleValue > 0 {
        return Date(timeIntervalSince1970: n.doubleValue)
    } else if let s = any as? String, !s.isEmpty {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        return f.date(from: String(s.prefix(19)))
    }
    return nil
}

/// "3 hours ago" for the core's timestamps (ISO text or seconds since 1970).
func ago(_ any: Any?) -> String {
    guard let d = (any as? Date) ?? moment(any) else { return "" }
    if abs(d.timeIntervalSinceNow) < 60 { return "just now" }
    let r = RelativeDateTimeFormatter()
    r.unitsStyle = .full
    return r.localizedString(for: d, relativeTo: Date())
}

/// "14:10" for a time today, "Oct 25, 14:10" for another day.
func clock(_ any: Any?) -> String {
    guard let d = (any as? Date) ?? moment(any) else { return "" }
    let f = DateFormatter()
    f.setLocalizedDateFormatFromTemplate(Calendar.current.isDateInToday(d) ? "jmm" : "MMMdjmm")
    return f.string(from: d)
}

/// A path under the home folder as ~/…, shorter and the way Finder thinks of it.
func tilde(_ path: String) -> String {
    let home = ProcessInfo.processInfo.environment["HOME"] ?? NSHomeDirectory()
    return path == home ? "~" : path.hasPrefix(home + "/") ? "~" + path.dropFirst(home.count) : path
}

/// A file row of the core's JSON (undo, second opinion) as the diff views take it.
func changedFile(_ d: [String: Any]) -> ChangedFile {
    return ChangedFile(path: d["path"] as? String ?? d["name"] as? String ?? "",
                       name: d["name"] as? String ?? "", state: d["state"] as? String ?? "",
                       inside: true, added: d["added"] as? Int ?? 0,
                       removed: d["removed"] as? Int ?? 0, diff: d["diff"] as? String ?? "")
}

func alert(_ title: String, _ body: String, confirm: String? = nil,
           cancel: String = "Cancel") -> Bool {
    let a = NSAlert()
    a.messageText = title
    a.informativeText = body
    if let c = confirm {
        a.addButton(withTitle: c)
        a.addButton(withTitle: cancel).keyEquivalent = "\u{1b}"     // Esc, whatever its name
        NSApp.activate(ignoringOtherApps: true)
        return a.runModal() == .alertFirstButtonReturn
    }
    a.addButton(withTitle: "OK")
    NSApp.activate(ignoringOtherApps: true)
    a.runModal()
    return true
}

/// The plist that starts the tray at login. Written as a property list, not
/// as text, so an app in a folder such as "Tools & Apps" still gives launchd
/// a file it can read.
func loginItemPlist(_ bin: String) -> Data? {
    try? PropertyListSerialization.data(
        fromPropertyList: ["Label": TRAY_LABEL, "ProgramArguments": [bin], "RunAtLoad": true],
        format: .xml, options: 0)
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
    let syncPaused: SyncPause?      // Keep in sync is on, but waits for the user
    let agents: [String]
    let sessions: Int
    let bytes: Int64
    let lastActivity: String
    let open: String?               // "waiting" | "working" | "idle": a session is open
    let limitSession: String?       // a Claude session stopped at its usage limit
    let limitResets: String?
    let handing: Handing?           // a handover that did not finish (yet)
    let relay: Relay?               // another agent here has the work, not handed back yet

    var id: String { path }
    /// The relay Hand Back answers: one made on this Mac, not left by another machine.
    var handBack: Relay? { relay.flatMap { $0.incoming ? nil : $0 } }
    var name: String { (path as NSString).lastPathComponent }
    var parent: String {
        ((path as NSString).deletingLastPathComponent as NSString).lastPathComponent
    }
    var place: String {
        if let host = away { return "on " + host }
        if let h = handing { return "handing over to " + h.machine }
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
        if away != nil || syncPaused != nil { return "paused" }
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
        syncPaused = (d["mirror_paused"] as? [String: Any]).map(SyncPause.init)
        agents = d["agents"] as? [String] ?? d["stores"] as? [String] ?? []
        open = d["open"] as? String
        let lim = d["limit"] as? [String: Any]
        limitSession = lim?["session"] as? String
        limitResets = lim?["resets"] as? String
        sessions = d["sessions"] as? Int ?? 0
        bytes = (d["bytes"] as? NSNumber)?.int64Value ?? 0
        lastActivity = d["last_activity"] as? String ?? ""
        handing = (d["handing"] as? [String: Any]).map(Handing.init)
        relay = (d["relay"] as? [String: Any]).map(Relay.init).flatMap { $0.open ? $0 : nil }
    }
}

/// `projects --json`'s `relay`: the newest open relay of the project. A
/// switch writes one when it passes the work to another agent; Hand Back
/// (or the first agent's session resumed by hand) closes it.
struct Relay: Hashable {
    let id: String
    let from: String                // the agent that passed the work on
    let to: String                  // the agent that has it now
    let since: Date?
    let open: Bool
    let incoming: Bool              // left here by another machine

    init(_ d: [String: Any]) {
        id = d["id"] as? String ?? ""
        from = d["from_agent"] as? String ?? "claude"
        to = d["to_agent"] as? String ?? "?"
        since = moment(d["since"])
        open = d["open"] as? Bool ?? true
        incoming = d["incoming"] as? Bool ?? false
    }
}

/// `projects --json`'s `handing`: the record a handover writes at home before
/// anything travels. Left behind when the link drops (or this Mac sleeps),
/// it stays until the other machine answers: the notices check then finishes
/// the handover or undoes it. Release drops it.
struct Handing: Hashable {
    let machine: String             // home's own name for the machine, else its own
    let since: Date?                // when the handover started
    let state: String               // "running" (now) | "checking" | "unreachable"
    let silentSince: Date?          // unreachable: no answer since then
    let release: Bool               // no answer for an hour: Release is offered

    init(_ d: [String: Any]) {
        machine = [d["remote"], d["holder"], d["host"]].compactMap { $0 as? String }
            .first { !$0.isEmpty } ?? "the other machine"
        since = moment(d["since"])
        state = d["state"] as? String ?? "checking"
        silentSince = moment(d["unreachable_since"])
        release = d["release"] as? Bool ?? false
    }
}

/// `projects --json`'s `mirror_paused`: Keep in sync stays on but sends
/// nothing until the user turns it back on. Release pauses it ("released"),
/// so the next sync does not overwrite the work left on that machine.
struct SyncPause: Hashable {
    let reason: String              // "released"
    let at: Date?
    let machine: String?            // the machine the copy is on

    init(_ d: [String: Any]) {
        reason = d["reason"] as? String ?? ""
        at = moment(d["at"])
        machine = d["remote"] as? String
    }
}

/// What Check Now found: the check's own words (`reclaim --json`'s
/// `checked`) when it settled the handover, else what the row says now.
func handingNote(_ name: String, _ h: Handing, after p: Project?, checked: [String]) -> String {
    if !checked.isEmpty { return checked.joined(separator: "\n") }
    guard let now = p?.handing else {
        return p?.away != nil
            ? "The handover of \(name) to \(h.machine) finished: the project is on "
              + "\(h.machine) now."
            : "The handover of \(name) to \(h.machine) did not finish. The project stays "
              + "here; nothing runs there."
    }
    switch now.state {
    case "running": return "The handover is under way right now."
    case "unreachable":
        return "\(now.machine) did not answer. aht asks again every minute; Release… lets "
            + "the project go on here."
    default:
        return "aht could not tell yet whether the handover finished. It asks "
            + "\(now.machine) again in a minute."
    }
}

/// A count in the core's JSON: a number, true or false (1 or 0), or a list of
/// names; nil when the core could not tell.
func tally(_ v: Any?) -> Int? {
    return (v as? Int) ?? (v as? Bool).map { $0 ? 1 : 0 } ?? (v as? [Any])?.count
}

/// Release's question, from `reclaim --release --json`: what stays over there
/// (`would_lose`: the project's files changed there, and `history`: the
/// conversation's, each when it could tell, and since when). With `sync`,
/// Release also pauses Keep in sync with that machine.
func releaseText(_ d: [String: Any], _ there: String, away: Bool, sync: Bool = false) -> String {
    let lose = (d["would_lose"] as? [String: Any]) ?? [:]
    let since = clock(lose["since"])
    let files = (lose["files"] as? [String]) ?? []
    let n = tally(lose["files"]), talk = tally(lose["history"])
    var s = "The work done on \(there)" + (since.isEmpty ? "" : " since \(since)")
        + " stays on \(there). It does not come here."
    if n == 0 && talk == 0 {
        s = "Nothing changed on \(there)" + (since.isEmpty ? "" : " since \(since)")
            + ", so nothing stays behind there."
    } else {
        // what stays there, named: "3 files and the conversation"
        var what: [String] = []
        if let n = n, n > 0 { what.append(n == 1 ? "1 file" : "\(n) files") }
        if let t = talk, t > 0 { what.append("the conversation") }
        if !what.isEmpty {
            let line = what.joined(separator: " and ")
            let one = what == ["1 file"] || what == ["the conversation"]
            s += "\n\n" + line.prefix(1).uppercased() + line.dropFirst()
                + (one ? " stays" : " stay") + " there" + (files.isEmpty ? "." : ":\n"
                    + files.prefix(6).map { "• " + $0 }.joined(separator: "\n")
                    + (files.count > 6 ? "\n• …" : ""))
        }
    }
    s += "\n\nThe files here stay as they are, and the copy on \(there) is not touched."
    if sync {
        s += " Release pauses Keep in sync with \(there), so the copy there stays as it is "
            + "until you turn sync back on."
    }
    if away { s += " To bring that work here, use Take Back instead." }
    return s
}

/// Turn Sync Back On's note, once `mirror <path> --on` has run: what aht said
/// when it failed; else the project's row after it (`now`), so the note says
/// the sync is on only when the row does.
func resumedText(_ to: String, ok: Bool, out: String, err: String, now: Project?) -> String {
    guard ok else {
        // its error first, then anything else it said
        let said = [err, out].map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }.joined(separator: "\n\n")
        return "The sync was not turned back on:\n\n"
            + (said.isEmpty ? "aht gave no answer — see the log (Settings)." : said)
    }
    if let now = now, now.mirror == nil || now.syncPaused != nil {
        return "The sync with \(to) did not come back on; see the log (Settings)."
    }
    return "Kept in sync with \(to) again; the next copy runs in the background."
}

/// One computer's folder of backups on the machine that keeps them
/// (`backup --offsite-list --json`'s `folders`).
struct OffsiteFolder: Identifiable, Hashable {
    let id: String                  // what `--fetch-offsite --from` takes
    let name: String
    let system: String
    let updated: Date?
    let projects: Int
    let files: Int                  // backups (zip files)
    let bytes: Int64
    let mine: Bool                  // this Mac's own folder
    let legacy: Bool                // an older aht's folder, under the computer's name

    /// What the row says after the name: system, last update, projects, size.
    var detail: String {
        var bits = [["Darwin": "macOS"][system] ?? system]
        if legacy { bits.append("from an older aht") }
        if let u = updated { bits.append("updated " + ago(u)) }
        bits.append("\(projects) project" + (projects == 1 ? "" : "s"))
        bits.append("\(files) backup" + (files == 1 ? "" : "s"))
        bits.append(byteText(NSNumber(value: bytes)))
        return bits.filter { !$0.isEmpty }.joined(separator: " · ")
    }
}

/// An older aht's folder has no id: `--from` takes its folder's name then.
func offsiteFolders(_ d: [String: Any]) -> [OffsiteFolder] {
    ((d["folders"] as? [[String: Any]]) ?? []).map { f in
        let name = f["name"] as? String ?? f["folder"] as? String ?? ""
        return OffsiteFolder(id: f["id"] as? String ?? f["folder"] as? String ?? name,
                             name: name.isEmpty ? "?" : name,
                             system: f["system"] as? String ?? "", updated: moment(f["updated"]),
                             projects: f["projects"] as? Int ?? 0, files: f["files"] as? Int ?? 0,
                             bytes: (f["bytes"] as? NSNumber)?.int64Value ?? 0,
                             mine: f["mine"] as? Bool ?? false, legacy: f["legacy"] as? Bool ?? false)
    }
}

/// The fetch sheet: the folders on the machine that keeps the backups.
struct OffsiteView: Identifiable {
    let id = UUID()
    let machine: String
    var loading = true
    var folders: [OffsiteFolder] = []
    var error: String?              // asking that machine failed: what aht said
    var pick: String?               // the folder to fetch from
    var fetching = false
    var result: String?             // how the last fetch went
}

/// The folder the fetch sheet picks first: another computer's, the one
/// updated last (a new Mac fetches what the old one left there).
func firstPick(_ folders: [OffsiteFolder]) -> String? {
    let order = folders.sorted { ($0.updated ?? .distantPast) > ($1.updated ?? .distantPast) }
    return (order.first { !$0.mine && $0.files > 0 } ?? order.first)?.id
}

/// How a fetch went, from `backup --fetch-offsite --from ID --json` (or what
/// aht said instead of its JSON).
func fetchedText(_ d: [String: Any]?, _ f: OffsiteFolder, said: String) -> String {
    guard let d = d, !(d["error"] is String) else {
        let why = (d?["error"] as? String ?? said).trimmingCharacters(in: .whitespacesAndNewlines)
        return "Nothing was fetched" + (why.isEmpty ? "; see the log (Settings)." : ": " + why)
    }
    let n = d["files"] as? Int ?? 0
    if n == 0 { return "Nothing to fetch: every backup in \(f.name)'s folder is here already." }
    let renamed = ((d["renamed"] as? [String]) ?? []).filter { $0.hasSuffix(".zip") }.count
    return "Fetched \(n) backup(s), \(byteText(d["bytes"])), from \(f.name)'s folder. Nothing "
        + "here was replaced" + (renamed == 0 ? "." : "; \(renamed) differed from a backup of "
        + "the same name here and " + (renamed == 1 ? "sits" : "sit") + " next to it under a "
        + "new name.") + " Search finds the "
        + "sessions in them, and Restore… on a result brings one back."
}

/// The adopt question's note on folders the user told aht to forget: the
/// first three by name, then how many more ("" when none). The trays' text
/// (the core's forgotten_note) says the same.
func forgottenNote(_ planned: [[String: Any]]) -> String {
    let gone = planned.filter { $0["forgotten"] as? Bool ?? false }
        .map { tilde($0["real"] as? String ?? $0["path"] as? String ?? "") }
    guard let last = gone.last else { return "" }
    let (n, k) = (planned.count, gone.count)
    let named = gone.contains("") ? (n == 1 ? "it" : k == n ? "all of them"
                                     : k == 1 ? "one of them" : "\(k) of them")
        : k > 3 ? gone.prefix(3).joined(separator: ", ") + " and \(k - 3) more"
        : k == 1 ? last : gone.dropLast().joined(separator: ", ") + " and " + last
    return "You told aht to forget \(named): adopting takes \(k == 1 ? "it" : "them") on again."
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
    var session: String? = nil
    var title: String? = nil        // the session's name (what the Claude app shows)
    var titleOrigin: String? = nil  // tab | aht | yours | automatic
    var tab: String? = nil          // its iTerm2 tab's title
    var pendingTitle: String? = nil // applied at the session's next prompt
    var pid: Int? = nil
    var inIterm = false             // in an iTerm2 tab: aht can bring it to the front
    var background = false          // a background session (no terminal)
    var issues: [String] = []       // twice | stuck | outside the app | older
    var canRestart = false
    var version: String? = nil
    var installed: String? = nil
    var limitResets: String? = nil  // stopped at Claude's usage limit
    var limitAuto = false           // … and Claude Code goes on by itself then
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
    var fingerprint = ""
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
    var topic: String? = nil        // the guide section its "?" opens
}

let AGENT_LABEL = ["claude": "Claude Code", "kimi": "Kimi Code", "codex": "Codex",
                   "agy": "Antigravity", "gemini": "Gemini", "opencode": "OpenCode",
                   "cursor": "Cursor", "copilot": "Copilot"]

/// The agents a project can be switched to, in the menu's order.
let SWITCH_AGENTS = ["claude", "kimi", "codex", "agy"]

/// Those of them installed here (`status --json`'s `agent_clis` names their CLI).
func switchAgents(_ status: [String: Any]) -> [String] {
    let d = (status["agent_clis"] as? [String: Any]) ?? [:]
    return SWITCH_AGENTS.filter { d[$0] is String }
}

/// One item of the Switch Agent menu; `back`: Hand Back into the first
/// agent's own session.
struct SwitchItem: Hashable {
    let title: String
    let to: String
    let back: Bool
}

/// The Switch Agent menu: while another agent has the work here, Hand Back
/// comes first, then every agent installed.
func switchItems(_ p: Project, _ agents: [String]) -> [SwitchItem] {
    var items: [SwitchItem] = []
    if let r = p.handBack {
        items.append(SwitchItem(title: "Hand Back to \(AGENT_LABEL[r.from] ?? r.from) (its own session)…",
                                to: r.from, back: true))
    }
    return items + agents.map { SwitchItem(title: "Continue in \(AGENT_LABEL[$0] ?? $0)…", to: $0, back: false) }
}

/// The line under a project that another agent took over here:
/// "Codex has had this project since 14:10, taken over from Claude Code".
func relayLine(_ r: Relay) -> String {
    let at = clock(r.since)
    return "\(AGENT_LABEL[r.to] ?? r.to) has had this project" + (at.isEmpty ? "" : " since \(at)")
        + ", taken over from \(AGENT_LABEL[r.from] ?? r.from)"
}

/// A switch or Hand Back asked for by a link (aht://switch?path=…&to=agy,
/// …&to=codex&resume=1, …&back=1, …&back=1&to=claude); nil: nothing to do.
func switchLink(_ q: [String: String]) -> (to: String?, back: Bool, resume: Bool)? {
    let yes = { (k: String) in ["1", "true", "yes"].contains((q[k] ?? "").lowercased()) }
    let to = q["to"].flatMap { SWITCH_AGENTS.contains($0) ? $0 : nil }
    if yes("back") { return (to, true, true) }
    return to.map { ($0, false, yes("resume")) }
}

/// A switch's dry run, kept for the dialog: one plan per way of going on
/// ("new" and "resume" for a switch, "back" for Hand Back).
struct SwitchPlan: Identifiable {
    let id = UUID()
    let project: Project
    let target: String              // the agent that goes on
    let back: Bool
    let backTo: String?             // Hand Back straight to this agent (a link's `to`)
    let plans: [String: [String: Any]]
    var mode: String                // "new" | "resume" | "back"
}

/// The switch dialog's text for one way of going on, from `switch --json`'s
/// dry run: who goes on with what, what that costs, the core's fallback and
/// warnings. `hook`: aht's SessionStart hook is in place, so a resumed Claude
/// session is told what changed without a turn.
func switchText(_ d: [String: Any], mode: String, hook: Bool) -> String {
    let target = d["target"] as? String ?? ""
    let label = AGENT_LABEL[target] ?? target
    let src = (d["source"] as? [String: Any]) ?? [:]
    let from = AGENT_LABEL[src["agent"] as? String ?? ""] ?? "the other agent"
    let title = (src["title"] as? String).map { " (“\($0)”)" } ?? ""
    var body: String
    switch mode {
    case "back":
        body = "\(label) goes on in its own session, where it left off. It reads only "
            + "what happened while \(from) had the project\(title): the latest exchanges, "
            + "the files changed and the commits made."
    case "resume":
        body = "\(label) goes on in its own latest session here. It reads only what "
            + "happened since: the work of the latest \(from) session\(title), the files "
            + "changed and the commits made."
    default:
        body = "\(label) continues the work of the latest \(from) session\(title) in a new "
            + "session. aht writes a summary of where things stood into the project, and "
            + "\(label) reads it first."
    }
    body += " The \(from) session stays as it is."
    if target == "kimi" {
        body += "\n\nKimi reads it in a first run of its own; this takes a moment before "
            + "the window opens."
    } else if target == "claude" && mode != "new" && hook {
        body += "\n\nClaude Code is told when the session opens; nothing runs until you type."
    } else {
        body += "\n\nReading it is \(label)'s first turn."
    }
    if let f = d["fallback"] as? String, !f.isEmpty { body += "\n\n" + f }
    for w in (d["warnings"] as? [String]) ?? [] { body += "\n\n⚠ " + w }
    return body
}

/// The summary a switch wrote: `brief` is its path, or its name in the
/// project's .aht/handover folder.
func summaryFile(_ brief: String, in project: String) -> String {
    brief.hasPrefix("/") ? brief : project + "/.aht/handover/" + (brief as NSString).lastPathComponent
}

/// What a switch, a Hand Back or Summary Only did, from `switch --apply --json`.
func switchDoneText(_ d: [String: Any], project: String) -> String {
    let target = d["target"] as? String ?? ""
    let label = AGENT_LABEL[target] ?? target
    let file = (d["brief"] as? String).map { tilde(summaryFile($0, in: project)) } ?? ""
    // fallback: its own session could not take the catch-up, so a new one did
    let fell = (d["fallback"] as? String).flatMap { $0.isEmpty ? nil : $0 }
    var said: String
    switch fell == nil ? d["mode"] as? String : "new" {
    case "brief-only":
        said = "The summary is written: \(file). Nothing was opened; \(label) can read it "
            + "when you start it."
    case "back":
        said = "Handed back: \(label)'s own session is open again and reads what changed first."
    case "resume":
        said = "\(label) went on in its own session; its window is open. What it reads first: \(file)"
    default:
        said = "\(label) took over; its window is open. The summary it read: \(file)"
    }
    if let f = fell { said = f + "\n\n" + said }
    for w in (d["warnings"] as? [String]) ?? [] { said += "\n⚠ " + w }
    return said
}

struct TidyItem: Identifiable {
    let id = UUID()
    let kind: String            // missing | orphan | double
    let key: String             // uuid or store name
    let path: String            // where it was
    let detail: String
    let candidates: [(path: String, why: String)]
    var sessions = 0
    var bytes: Int64 = 0
    var last: String? = nil     // when it was last used
    var title: String? = nil    // the latest session's title
    var history: String? = nil  // the history's own folder
    var link = false            // a link to a folder elsewhere: aht does not remove it
}

/// Tidy Up's rows from `aht tidy --json`.
func tidyItems(_ d: [String: Any]) -> [TidyItem] {
    var items: [TidyItem] = []
    for m in (d["missing"] as? [[String: Any]]) ?? [] {
        let agents = (m["agents"] as? [String]) ?? []
        items.append(TidyItem(
            kind: "missing", key: m["uuid"] as? String ?? "", path: m["path"] as? String ?? "",
            detail: agents.isEmpty ? "no history" : "history of " + agents.map {
                AGENT_LABEL[$0] ?? $0 }.joined(separator: ", "),
            candidates: ((m["candidates"] as? [[String: Any]]) ?? []).map {
                (path: $0["path"] as? String ?? "",
                 why: (($0["reasons"] as? [String]) ?? []).joined(separator: ", "))
            },
            sessions: m["sessions"] as? Int ?? 0,
            bytes: (m["bytes"] as? NSNumber)?.int64Value ?? 0,
            last: m["last"] as? String, title: m["title"] as? String,
            history: m["history"] as? String))
    }
    for o in (d["orphans"] as? [[String: Any]]) ?? [] {
        let n = o["sessions"] as? Int ?? 0
        let link = o["link"] as? Bool ?? false
        items.append(TidyItem(
            kind: "orphan", key: o["store"] as? String ?? "",
            path: (o["was"] as? String) ?? (o["store"] as? String ?? ""),
            detail: link ? "Claude Code, a link to a folder elsewhere" : "Claude Code",
            candidates: ((o["candidates"] as? [[String: Any]]) ?? []).map {
                (path: $0["path"] as? String ?? "",
                 why: (($0["reasons"] as? [String]) ?? []).joined(separator: ", "))
            },
            sessions: n, bytes: (o["bytes"] as? NSNumber)?.int64Value ?? 0,
            last: o["last"] as? String, title: o["title"] as? String,
            history: o["history"] as? String, link: link))
    }
    for x in (d["doubles"] as? [[String: Any]]) ?? [] {
        items.append(TidyItem(kind: "double", key: x["uuid"] as? String ?? "",
                              path: x["real_path"] as? String ?? "",
                              detail: "listed twice; the folder's own entry stays",
                              candidates: []))
    }
    return items
}

struct ChangedFile: Identifiable {
    let id = UUID()
    let path: String
    let name: String
    let state: String
    let inside: Bool
    let added: Int
    let removed: Int
    let diff: String
}

struct ChangesView: Identifiable {
    let id = UUID()
    let project: Project
    let session: String?
    let title: String
    let sessions: [String]
    let files: [ChangedFile]
}

struct Checkpoint: Identifiable, Hashable {
    let id: String
    let at: Double
    let agent: String
    let title: String?
    var label: String {
        let f = DateFormatter()
        f.dateStyle = .medium
        f.timeStyle = .short
        return f.string(from: Date(timeIntervalSince1970: at)) + " — "
            + (title ?? "a \(AGENT_LABEL[agent] ?? agent) session")
    }
}

struct UndoView: Identifiable {
    let id = UUID()
    let project: Project
    let checkpoints: [Checkpoint]
    let chosen: String?
    let files: [ChangedFile]
    let blockers: [String]
    let warnings: [String]
}

struct LooseItem {
    let kind: String            // uncommitted | todos | question | offer
    let text: String
    let sub: [String]
}

struct LooseEnd: Identifiable {
    let id = UUID()
    let project: String
    let agent: String
    let session: String
    let last: Double
    let open: Bool
    let items: [LooseItem]
}

struct OpinionResult: Identifiable {
    let id: String              // the agent
    let state: String
    let answer: String
    let seconds: Int?
    let cost: Double?
    let files: [ChangedFile]
}

struct OpinionView: Identifiable {
    let id = UUID()
    let project: Project
    var runs: [(id: String, label: String)] = []
    var current: String?
    var task = ""
    var results: [OpinionResult] = []
    var changedMeanwhile: [String] = []
    var taken: String?
    var finished = true
}

struct NightJob: Identifiable {
    let id: String
    let state: String
    let startAt: Double
    let backAt: Double
    let remote: String
    let task: String
    let log: [String]
}

struct NightShiftView: Identifiable {
    let id = UUID()
    let project: Project
    let jobs: [NightJob]
}

/// One session of a project (`aht sessions <project>`): a branch has the time it
/// branched and a depth below the session it came from.
struct SessionItem: Identifiable {
    let id: String                  // agent:session
    let agent: String
    let session: String
    let title: String
    let started: Double?
    let updated: Double?
    let branched: Double?
    let depth: Int
    let open: Bool
    let pid: Int?
    let parentGone: Bool

    init(_ d: [String: Any]) {
        agent = d["agent"] as? String ?? "claude"
        session = d["id"] as? String ?? ""
        id = agent + ":" + session
        title = d["title"] as? String ?? ""
        started = (d["started"] as? NSNumber)?.doubleValue
        updated = (d["updated"] as? NSNumber)?.doubleValue
        branched = (d["branched"] as? NSNumber)?.doubleValue
        depth = d["depth"] as? Int ?? 0
        open = d["open"] as? Bool ?? false
        pid = d["pid"] as? Int
        parentGone = d["parent_gone"] as? Bool ?? false
    }
}

struct SessionListView: Identifiable {
    let id = UUID()
    let project: Project
    let items: [SessionItem]
}

/// A step of Getting started (`aht getting-started`); ok nil: cannot tell now.
struct SetupStep: Identifiable {
    let id: String
    let ok: Bool?
    let optional: Bool
    let title: String
    let text: String
    let how: String
}

/// Whether macOS lets this app send Apple events to iTerm2, which Go to Tab,
/// a click in the corner list and Restore Workspace need: "yes", "no", "ask"
/// (not asked yet) or "closed" (iTerm2 is not open, so macOS cannot say).
/// With `ask`, macOS asks now when it has not yet; that waits for the answer.
func itermControlState(ask: Bool) -> String {
    guard let target = NSAppleEventDescriptor(bundleIdentifier: "com.googlecode.iterm2").aeDesc
    else { return "closed" }
    switch Int(AEDeterminePermissionToAutomateTarget(target, AEEventClass(typeWildCard),
                                                     AEEventID(typeWildCard), ask)) {
    case Int(noErr): return "yes"
    case errAEEventNotPermitted: return "no"
    case errAEEventWouldRequireUserConsent: return "ask"
    default: return "closed"                   // procNotFound
    }
}

/// What each option that makes an agent read or work costs: they stay off
/// until the user turns them on, here or in Settings.
let TOKEN_NOTES = [
    "second_opinion": "Both agents work on the task you give them, each in its own copy "
        + "of the project, so both use tokens: your Claude plan or API account and your "
        + "Kimi account. aht starts one only when you press Start.",
    "night_shift": "The agent on your other machine works on the task you give it while "
        + "you are away, which uses the tokens of your Claude plan or API account. aht "
        + "starts only the night shifts you plan.",
]

struct ReportRow: Identifiable {
    let id = UUID()
    let name: String
    let hours: Double
    let sessions: Int
    let agents: String
}

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
    @Published var found: [Found] = []          // machines to add (see discover)
    @Published var discovering = false
    @Published var running = false
    @Published var loaded = false

    @Published var tab: Tab = .projects
    @Published var selection: String?
    @Published var search = ""
    @Published var working: String?             // a transfer or check in progress
    @Published var percent: Double?
    @Published var notes: [String: String] = [:]    // per project: how the last action went
    @Published var summaries: [String: String] = [:] // … and the summary a switch wrote
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
    @Published var switchPlan: SwitchPlan?      // Switch Agent and Hand Back, before they run
    @Published var rules: RulesView?
    @Published var textSheet: TextSheet?
    @Published var tidy: [TidyItem]?
    @Published var showTidy = false
    @Published var tidyCount = 0
    @Published var changes: ChangesView?
    @Published var showReport = false
    @Published var report: [ReportRow] = []
    @Published var reportTotal = ""
    @Published var reportPeriod = "week"
    @Published var reportBy = "project"
    @Published var searchProject: String?       // Search limited to one project
    @Published var focusSearch = 0              // bumped: the search field takes focus
    @Published var limitSwitchTo: String?       // the agent offered at Claude's usage limit
    @Published var undo: UndoView?
    @Published var looseEnds: [LooseEnd]?
    @Published var showLooseEnds = false
    @Published var opinion: OpinionView?
    @Published var night: NightShiftView?
    @Published var coverageNote: String?        // which projects get no copy at a session start
    @Published var showGettingStarted = false
    @Published var sessionList: SessionListView?
    @Published var showUpdate = false
    @Published var offsite: OffsiteView?        // Fetch Backups From…
    var openWelcome: (() -> Void)?              // the welcome window, again
    var openWelcomeFirst: ((String) -> Void)?   // … to install aht (this app's version)
    @Published var itermControl = "closed"      // itermControlState(ask: false)
    var offerSetup: (() -> Void)?               // Getting started, if it was never shown
    var onChange: (() -> Void)?                 // the menu bar icon follows the state

    private let q = DispatchQueue(label: "aht.tray.state")

    // ---- reading ----

    struct Loaded {
        var status: [String: Any] = [:]
        var config: [String: Any] = [:]
        var projects: [[String: Any]] = []
        var limitSwitchTo: String?
        var running = false
        var tidyCount = 0
        var itermControl = "closed"
    }

    static func load() -> Loaded {
        var l = Loaded()
        l.status = ahtJSON(["status", "--json"]) ?? [:]
        l.config = (ahtJSON(["config", "--json"])?["effective"] as? [String: Any]) ?? [:]
        let pj = ahtJSON(["projects", "--json"]) ?? [:]
        l.projects = (pj["projects"] as? [[String: Any]]) ?? []
        l.limitSwitchTo = pj["limit_switch_to"] as? String
        l.running = watcherRunning()
        l.tidyCount = (l.status["missing"] as? Int ?? 0) + (l.status["orphan_claude_stores"] as? Int ?? 0)
        if (((l.status["terminals"] as? [String: Any])?["installed"] as? [String]) ?? []).contains("iTerm") {
            l.itermControl = itermControlState(ask: false)
        }
        return l
    }

    func take(_ l: Loaded) {
        status = l.status
        config = l.config
        var seen = Set<String>()
        projects = l.projects.map(Project.init).filter { seen.insert($0.path).inserted }
        running = l.running
        tidyCount = l.tidyCount
        limitSwitchTo = l.limitSwitchTo
        itermControl = l.itermControl
        loginItem = FileManager.default.fileExists(atPath: TRAY_PLIST)
        loaded = true
        showFound()
        onChange?()
    }

    private var discovered: [[String: Any]] = []     // the last answer of `remote discover`

    /// The machines that could be added: Tailscale's list and ~/.ssh/config.
    /// Read only when the Machines tab is shown or Look Again is pressed, not
    /// at every refresh; the last answer is kept in between.
    func discover(_ done: (() -> Void)? = nil) {
        guard !discovering else { done?(); return }
        discovering = true
        DispatchQueue.global(qos: .userInitiated).async {
            let rows = (ahtJSON(["remote", "discover", "--json"])?["machines"]
                        as? [[String: Any]]) ?? []
            DispatchQueue.main.async {
                self.discovered = rows
                self.discovering = false
                self.showFound()
                done?()
            }
        }
    }

    /// The machines found, less the ones added since (the list of those is current).
    func showFound() {
        let added = Set(machines.map { String($0.target.split(separator: "@").last ?? "") })
        found = discovered.filter { !added.contains($0["host"] as? String ?? "") }.map { d in
            var bits = [d["system"] as? String, d["via"] as? String].compactMap { $0 }
            if let on = d["online"] as? Bool { bits.insert(on ? "online" : "offline", at: 0) }
            return Found(host: d["host"] as? String ?? "?",
                         note: bits.joined(separator: ", "))
        }
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
    /// Other machines can be asked (an ssh client is there): fetching
    /// backups. Sending projects (and Check Now) needs `supported`.
    var canReach: Bool { handover["can_reach"] as? Bool ?? supported }
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
    var agentCLIs: [String] { switchAgents(status) }
    /// aht's SessionStart hook is in place (a resumed Claude session hears what changed).
    var hookOn: Bool { status["hook_installed"] as? Bool ?? true }
    var waiting: Int { projects.filter { $0.open == "waiting" }.count }
    var limited: [Project] { projects.filter { $0.limitSession != nil && $0.away == nil } }
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
    func number(_ key: String, _ fallback: Int) -> Int {
        return config[key] as? Int ?? (config[key] as? String).flatMap { Int($0) } ?? fallback
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
        DispatchQueue.main.async {
            self.notes[path] = text
            self.summaries[path] = nil          // it belonged to the note before
        }
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
                                    + (task.isEmpty ? [] : ["--task=" + task])) ?? [:]
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

    /// Check Now on an unfinished handover: Take Back's dry run asks the other
    /// machine first whether the handover finished, and settles it either way
    /// (`checked`); the plan it goes on to make is not needed here.
    func checkHanding(_ p: Project) {
        guard let h = p.handing else { return }
        note(p.path, nil)
        DispatchQueue.main.async {
            self.working = "asking \(h.machine) about \(p.name)…"
            self.percent = nil
        }
        DispatchQueue.global(qos: .userInitiated).async {
            let d = ahtJSON(["reclaim", p.path, "--json"]) ?? [:]
            self.refresh {
                self.working = nil
                let now = self.projects.first { $0.path == p.path }
                self.note(p.path, handingNote(p.name, h, after: now,
                                              checked: (d["checked"] as? [String]) ?? []))
            }
        }
    }

    /// Release: stop waiting for a project that went to another machine and
    /// does not come back from there. The files here stay as they are and the
    /// copy there is not touched; the dry run says what stays there. Keep in
    /// sync with that machine pauses, or its next sync would overwrite that copy.
    func release(_ p: Project) {
        note(p.path, nil)
        busy("checking \(p.name)…") {
            let plan = ahtJSON(["reclaim", p.path, "--release", "--json"]) ?? [:]
            DispatchQueue.main.async {
                if let why = self.problems(plan) {
                    self.note(p.path, "Cannot be released now:\n\n" + why)
                    return
                }
                let there = plan["remote"] as? String ?? p.handing?.machine ?? p.away
                    ?? "the other machine"
                // the core's `pauses_sync` (the machine, or null) when it sends
                // one; an older core's answer has none: the row says it then
                let pauses = plan.keys.contains("pauses_sync")
                    ? plan["pauses_sync"] is String : p.mirror != nil && p.mirror == there
                guard alert("Release “\(p.name)” from \(there)?",
                            releaseText(plan, there, away: p.away != nil, sync: pauses),
                            confirm: "Release") else { return }
                self.busy("releasing \(p.name)…") {
                    let d = ahtJSON(["reclaim", p.path, "--release", "--apply", "--json"]) ?? [:]
                    if let why = self.problems(d) {
                        self.note(p.path, "Releasing it did not go through:\n\n" + why)
                        return
                    }
                    let released = d["released"] as? Bool ?? false
                    let warned = ((d["warnings"] as? [String]) ?? []).map { "\n⚠ " + $0 }.joined()
                    // the pause as the registry has it now, not as expected
                    self.refresh {
                        let now = self.projects.first { $0.path == p.path }
                        var done = "Released. The project is here as it was; its copy on \(there) "
                            + "stays as it is."
                        if !released {
                            done = "aht did not say it released the project; see the log (Settings)."
                        } else if let s = now?.syncPaused, now?.mirror != nil {
                            done = "Released. The project is here as it was. Keep in sync with "
                                + "\(s.machine ?? there) is paused, so the copy there stays as it is."
                        }
                        self.note(p.path, done + warned)
                    }
                }
            }
        }
    }

    /// Turn a paused Keep in sync back on: the next sync makes the copy there
    /// match this Mac again; what it replaces there is set aside there first.
    /// The note comes once the command has run, from its answer and the row.
    func resumeSync(_ p: Project, _ to: String) {
        guard alert("Turn Keep in sync with \(to) back on?",
                    "The next sync makes the copy of \(p.name) on \(to) the same as the one "
                    + "here, so the work left there is replaced. aht keeps what it replaces "
                    + "in a set-aside folder on \(to).",
                    confirm: "Turn Sync Back On") else { return }
        note(p.path, nil)
        busy("turning the sync with \(to) back on…") {
            let r = shWithStderr(PY, [ahtScript(), "mirror", p.path, "--on", "--to", to])
            // the pause as the registry has it now, not as expected
            self.refresh {
                let now = self.projects.first { $0.path == p.path }
                self.note(p.path, resumedText(to, ok: r.ok, out: r.out, err: r.err, now: now))
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
                             handedOver: r["handed_over"] as? Bool ?? false,
                             session: r["session"] as? String, title: r["title"] as? String,
                             titleOrigin: r["title_origin"] as? String, tab: r["tab"] as? String,
                             pendingTitle: r["pending_title"] as? String,
                             pid: r["pid"] as? Int, inIterm: r["in_iterm"] as? Bool ?? false,
                             background: r["background"] as? Bool ?? false,
                             issues: (r["issues"] as? [String]) ?? [],
                             canRestart: r["can_restart"] as? Bool ?? false,
                             version: r["version"] as? String, installed: r["installed"] as? String,
                             limitResets: (r["limit"] as? [String: Any])?["resets"] as? String,
                             limitAuto: (r["limit"] as? [String: Any])?["auto"] as? Bool ?? false)
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

    /// Claude Code takes a new name only from a hook, so it arrives with the
    /// session's next prompt (typed here or in the Claude app).
    func renameSession(_ r: BoardRow) {
        guard let sid = r.session else { return }
        let a = NSAlert()
        a.messageText = "Name this session"
        let api = status["iterm_api"] as? Bool ?? false
        a.informativeText = "The name shows in the Claude app, in /resume and in the session's "
            + "prompt bar. Claude Code takes it at the session's next prompt — when you next "
            + "send it a message, here or in the app. It stays until you rename the tab."
            + (r.tab.map { "\n\nIts iTerm2 tab is called “\($0)”." } ?? "")
            + (!r.inIterm ? "" : api ? " The tab takes the new name now."
               : " The tab keeps its title: to let it take the name too, switch on iTerm2 → "
                 + "Settings → General → Magic → Enable Python API.")
        let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 340, height: 24))
        // a name with a key in it comes masked ([GitHub token: ghp_…r8]): shown
        // as a hint, not as the text, so Rename never gives it the masked text
        let current = r.pendingTitle ?? r.title ?? r.tab ?? ""
        let masked = current.range(of: #"\[[^\[\]:]*(?:key|token|address|webhook): [^\[\]]*\]"#,
                                   options: .regularExpression) != nil
        field.stringValue = masked ? "" : current
        if masked { field.placeholderString = current }
        a.accessoryView = field
        a.addButton(withTitle: "Rename")
        a.addButton(withTitle: "Cancel")
        if r.tab != nil { a.addButton(withTitle: "Follow the Tab Again") }
        a.window.initialFirstResponder = field
        NSApp.activate(ignoringOtherApps: true)
        let pick = a.runModal().rawValue - NSApplication.ModalResponse.alertFirstButtonReturn.rawValue
        let name = field.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard pick == 0 && !name.isEmpty || pick == 2 else { return }
        DispatchQueue.global(qos: .userInitiated).async {
            let d = ahtJSON(["tab-names", "--rename=" + sid, "--to=" + (pick == 2 ? "" : name),
                             "--json"]) ?? [:]
            let why = d["tab"] as? String ?? ""
            DispatchQueue.main.async {
                self.refreshBoard()
                if why == "panes" {
                    _ = alert("The tab kept its title", "Its tab holds more than one session, "
                              + "and a title would name them all. The session takes the name "
                              + "at its next prompt.")
                } else if !["", "api-off", "no-tab"].contains(why) {
                    _ = alert("The tab kept its title", "iTerm2 did not take it: \(why)\n\nThe "
                              + "session takes the name at its next prompt.")
                }
            }
        }
    }

    func syncNamesToTabs() {
        busy("reading iTerm2's tabs…") {
            let d = ahtJSON(["tab-names", "--sync-all", "--json"]) ?? [:]
            let plan = (d["plan"] as? [[String: Any]]) ?? []
            DispatchQueue.main.async {
                if plan.isEmpty {
                    _ = alert("Nothing to change", "Every open session with a tab title already "
                              + "carries it. (A tab counts once you gave it a title yourself.)")
                    return
                }
                let lines = plan.prefix(14).map { x in
                    "• " + ((x["from"] as? String) ?? "(no name)") + "  →  " + (x["to"] as? String ?? "")
                }.joined(separator: "\n") + (plan.count > 14 ? "\n…" : "")
                guard alert("Name \(plan.count) session\(plan.count == 1 ? "" : "s") after "
                            + "\(plan.count == 1 ? "its tab" : "their tabs")?",
                            lines + "\n\nNames you gave sessions yourself are replaced too. "
                            + "Each session takes its new name at its next prompt; after that it "
                            + "follows its tab.", confirm: "Rename") else { return }
                self.busy("renaming…") {
                    aht(["tab-names", "--sync-all", "--apply"])
                    DispatchQueue.main.async { self.refreshBoard() }
                }
            }
        }
    }

    func gotoTab(_ r: BoardRow) {
        guard let pid = r.pid else { return }
        goto(pid: pid)
    }

    func goto(pid: Int) {
        DispatchQueue.global(qos: .userInitiated).async {
            let res = sh(PY, [ahtScript(), "goto", String(pid)], mergeStderr: true)
            if !res.ok {
                DispatchQueue.main.async { _ = alert("Could not go to its tab", res.out) }
            }
        }
    }

    func restartSession(_ r: BoardRow) {
        guard let pid = r.pid else { return }
        busy("checking…") {
            let plan = ahtJSON(["checkup", "--restart", String(pid), "--json"]) ?? [:]
            DispatchQueue.main.async {
                if let why = self.problems(plan) {
                    _ = alert("Not now", why)
                    return
                }
                guard alert("Restart “\(r.title ?? r.name)” in its tab?",
                            "aht ends the session and starts it again in the same iTerm2 tab, "
                            + "where it left off, with the options it had:\n\n"
                            + (plan["command"] as? String ?? "") + "\n\nIt then runs Claude Code "
                            + (r.installed ?? "as installed") + " and, with Remote Control on for "
                            + "every session, it shows in the Claude app. Anything typed into it "
                            + "but not sent is lost.", confirm: "Restart") else { return }
                self.busy("restarting…") {
                    let d = ahtJSON(["checkup", "--restart", String(pid), "--apply", "--json"]) ?? [:]
                    DispatchQueue.main.async {
                        if let why = self.problems(d) { _ = alert("Not restarted", why) }
                        self.refreshBoard()
                    }
                }
            }
        }
    }

    func closeSession(_ r: BoardRow) {
        guard let pid = r.pid,
              alert("End this Claude Code process?",
                    "“\(r.title ?? r.name)” (process \(pid)) ends the way /exit ends it. Its "
                    + "conversation stays, and claude --resume continues it.", confirm: "End It")
        else { return }
        busy("ending it…") {
            let d = ahtJSON(["checkup", "--close", String(pid), "--apply", "--json"]) ?? [:]
            DispatchQueue.main.async {
                if let why = self.problems(d) { _ = alert("Not ended", why) }
                self.refreshBoard()
            }
        }
    }

    @Published var workspaces: [[String: Any]]?
    @Published var showWorkspace = false
    @Published var workspacePick: String?
    @Published var workspacePlan: [String: Any] = [:]
    @Published var workspaceDefault: String?
    var autosaving = false

    func openWorkspaces() {
        workspaces = nil
        showWorkspace = true
        DispatchQueue.global(qos: .userInitiated).async {
            let d = ahtJSON(["workspace", "--json"]) ?? [:]
            DispatchQueue.main.async {
                self.workspaces = (d["workspaces"] as? [[String: Any]]) ?? []
                self.workspaceDefault = d["default"] as? String
                self.pickWorkspace(d["default"] as? String)
            }
        }
    }

    /// Every minute; the core saves when workspace_save_minutes have passed.
    func autosaveWorkspace() {
        guard !autosaving else { return }
        autosaving = true
        DispatchQueue.global(qos: .utility).async {
            _ = aht(["workspace", "--save", "--auto", "--quiet"])
            DispatchQueue.main.async { self.autosaving = false }
        }
    }

    func applyWorkspaceSaving(_ every: String, _ keep: String) {
        guard let e = Int(every.filter { $0.isNumber }), let k = Int(keep.filter { $0.isNumber }),
              k >= 1 else {
            _ = alert("Not a number", "Enter how many minutes between saves (0 saves only when "
                      + "a session gets a prompt) and how many layouts to keep (at least 1).")
            return
        }
        set("workspace_save_minutes", String(e))
        set("workspace_keep", String(k))
        config["workspace_save_minutes"] = e
        config["workspace_keep"] = k
    }

    func pickWorkspace(_ id: String?) {
        workspacePick = id
        workspacePlan = [:]
        guard let id = id else { return }
        DispatchQueue.global(qos: .userInitiated).async {
            let d = ahtJSON(["workspace", "--restore", id, "--json"]) ?? [:]
            DispatchQueue.main.async { if self.workspacePick == id { self.workspacePlan = d } }
        }
    }

    func saveWorkspaceNow() {
        busy("saving the workspace…") {
            aht(["workspace", "--save"])
            DispatchQueue.main.async { self.openWorkspaces() }
        }
    }

    func restoreWorkspace() {
        guard let id = workspacePick else { return }
        busy("opening the tabs…") {
            let d = ahtJSON(["workspace", "--restore", id, "--apply", "--json"]) ?? [:]
            DispatchQueue.main.async {
                if let why = self.problems(d) {
                    _ = alert("Not opened", why)
                } else {
                    self.showWorkspace = false
                }
                self.refreshBoard()
            }
        }
    }

    func syncAll(_ mc: Machine, on: Bool) {
        busy(on ? "adding up what the first copy sends…" : "checking…") {
            let plan = ahtJSON(["mirror", "--all", on ? "--on" : "--off", "--to", mc.name, "--json"]) ?? [:]
            DispatchQueue.main.async {
                if let why = self.problems(plan) {
                    _ = alert("Nothing to do", why)
                    return
                }
                let rows = (plan["projects"] as? [[String: Any]]) ?? []
                let gb = ((plan["bytes"] as? NSNumber)?.doubleValue ?? 0) / 1e9
                let top = rows.prefix(6).map { r -> String in
                    let mb = ((r["bytes"] as? NSNumber)?.doubleValue ?? 0) / 1e6
                    return "• " + ((r["project"] as? String ?? "") as NSString).lastPathComponent
                        + (on ? String(format: " — %.0f MB", mb) : "")
                }.joined(separator: "\n")
                let body = on
                    ? "\(rows.count) project\(rows.count == 1 ? "" : "s") get a copy on \(mc.name), "
                      + String(format: "about %.1f GB the first time", gb) + " (it runs in the "
                      + "background and can take a while); after that only changes travel, "
                      + "every 30 minutes. The biggest:\n\n" + top + "\n\nProjects inside "
                      + "another project travel with it. Rebuilt folders such as node_modules "
                      + "stay behind."
                    : "\(rows.count) project\(rows.count == 1 ? "" : "s") stop being kept in sync. "
                      + "The copies on the other machine stay where they are."
                guard alert(on ? "Keep every project in sync with \(mc.name)?"
                               : "Stop keeping every project in sync?", body,
                            confirm: on ? "Keep All in Sync" : "Stop") else { return }
                self.busy(on ? "switching it on…" : "switching it off…") {
                    aht(["mirror", "--all", on ? "--on" : "--off", "--to", mc.name, "--apply"])
                }
            }
        }
    }

    var mirroredCount: Int { projects.filter { $0.mirror != nil }.count }

    @Published var tidyReading: (title: String, text: String, item: TidyItem)?

    func readHistory(_ t: TidyItem) {
        busy("reading the history…") {
            let d = ahtJSON(["tidy", "--show=" + t.key, "--json"]) ?? [:]
            DispatchQueue.main.async {
                self.tidyReading = (title: (t.path as NSString).lastPathComponent,
                                    text: d["markdown"] as? String
                                        ?? (d["error"] as? String ?? "It could not be read."),
                                    item: t)
            }
        }
    }

    func removeHistory(_ t: TidyItem) {
        busy("looking at it…") {
            let plan = ahtJSON(["tidy", "--remove-history=" + t.key, "--json"]) ?? [:]
            DispatchQueue.main.async {
                if let why = self.problems(plan) {
                    _ = alert("Not now", why)
                    return
                }
                let n = plan["sessions"] as? Int ?? 0
                guard alert("Move this history to the Trash?",
                            "The history of \(t.path) — \(n) Claude Code session\(n == 1 ? "" : "s"), "
                            + byteText(plan["bytes"]) + ". It goes to the Trash, where Put Back "
                            + "brings it back, and aht's daily backups keep it too.",
                            confirm: "Move to Trash") else { return }
                self.busy("moving it to the Trash…") {
                    let d = ahtJSON(["tidy", "--remove-history=" + t.key, "--apply", "--json"]) ?? [:]
                    DispatchQueue.main.async {
                        if let why = self.problems(d) { _ = alert("Not moved", why) }
                        self.openTidy()
                    }
                }
            }
        }
    }

    func setAutoContinue(_ on: Bool) {
        status["claude_auto_continue"] = on
        background { aht(["limits", "--auto-continue", on ? "on" : "off"]) }
    }

    var itermInstalled: Bool {
        (((status["terminals"] as? [String: Any])?["installed"] as? [String]) ?? []).contains("iTerm")
    }

    // ---- a new version (asked for only when update_check is on) ----

    var update: [String: Any] { (status["update"] as? [String: Any]) ?? [:] }
    /// The newer version that is out, if one is.
    var newVersion: String? { (update["newer"] as? Bool ?? false) ? update["latest"] as? String : nil }

    func checkUpdateNow() {
        busy("asking GitHub for the latest version…") {
            let d = ahtJSON(["update", "--now", "--json"]) ?? [:]
            self.refresh {
                // after a failed ask, "latest" is only what GitHub said the time before
                if d["newer"] as? Bool ?? false {
                    self.showUpdate = true
                } else if let v = d["latest"] as? String, (d["error"] as? String ?? "").isEmpty {
                    _ = alert("aht \(v) is the latest", "You have the newest version.")
                } else {
                    _ = alert("GitHub did not answer", d["error"] as? String ?? "Try again later.")
                }
            }
        }
    }

    /// Homebrew, Scoop or winget in a terminal window; else the download page.
    func upgrade() {
        showUpdate = false
        background { aht(["update", "--upgrade"]) }
    }

    // ---- the folders aht watches ----

    var roots: [String] { (status["watch_roots"] as? [String]) ?? [] }

    func setRoots(_ list: [String]) {
        guard let d = try? JSONSerialization.data(withJSONObject: list),
              let json = String(data: d, encoding: .utf8) else { return }
        busy("watching \(list.count) folder\(list.count == 1 ? "" : "s")…") {
            let r = aht(["config", "--set", "watch_roots=" + json])     // restarts the watcher
            // saved either way; before aht is installed no watcher follows them yet
            if let why = self.notRestarted(r.out), why.contains("not installed") {
                DispatchQueue.main.async { _ = alert("The watcher is not running", why) }
            }
        }
    }

    /// The core's own words when it did not restart the watcher (not
    /// installed yet, watching is off, the installer failed); nil when it did.
    func notRestarted(_ out: String) -> String? {
        let lines = out.split(separator: "\n").map { String($0) }
        if lines.contains(where: { $0.contains("watcher reloaded") }) { return nil }
        return lines.first(where: { $0.contains("not installed") || $0.contains("nothing to reload")
                                    || $0.contains("could not reload") })
    }

    func addRoot() {
        guard let p = chooseFolder("Watch this folder: aht notices moves, copies and new "
                                   + "projects inside it") else { return }
        if !roots.contains(p) { setRoots(roots + [p]) }
    }

    // ---- getting started ----

    /// The core's steps, and after iTerm2's Python API the one only the app
    /// can see: whether macOS lets it control iTerm2.
    var setupSteps: [SetupStep] {
        var steps = ((status["getting_started"] as? [[String: Any]]) ?? []).map { d in
            SetupStep(id: d["id"] as? String ?? "", ok: d["ok"] as? Bool ?? false,
                      optional: d["optional"] as? Bool ?? false,
                      title: d["title"] as? String ?? "", text: d["text"] as? String ?? "",
                      how: d["how"] as? String ?? "")
        }
        if let i = steps.firstIndex(where: { $0.id == "iterm_api" }) {
            let c = itermControl
            let what = "aht needs it to read tab titles, bring a tab to the front and open a "
                + "saved workspace."
            steps.insert(SetupStep(
                id: "iterm_control", ok: c == "yes" ? true : c == "closed" ? nil : false,
                optional: false, title: "Permission to control iTerm2",
                text: c == "yes" ? "Given. " + what
                    : c == "no" ? "Refused, so Go to Tab, a click in the corner list and "
                                  + "Restore Workspace do not work."
                    : c == "ask" ? "macOS has not asked yet. " + what
                    : "Shows once iTerm2 is open. " + what,
                how: c == "no" ? "System Settings → Privacy & Security → Automation → aht → "
                                 + "iTerm2." : ""), at: i + 1)
        }
        return steps
    }
    var setupMissing: Bool { setupSteps.contains { !$0.optional && $0.ok == false } }
    var setupSummary: String {
        let steps = setupSteps
        let left = steps.filter { !$0.optional && $0.ok == false }.map { $0.title }
        let more = steps.filter { $0.optional && $0.ok == false }.count
        return (left.isEmpty ? "The main steps are done." : "To do: " + left.joined(separator: ", ") + ".")
            + (more > 0 ? " \(more) optional step\(more == 1 ? "" : "s") left." : "")
    }

    /// macOS asks only about an app that runs, so iTerm2 is opened first.
    func askItermControl() {
        background {
            if itermControlState(ask: false) == "closed" {
                sh("/usr/bin/open", ["-g", "-b", "com.googlecode.iterm2"])
                var tries = 0
                while itermControlState(ask: false) == "closed" && tries < 40 {
                    Thread.sleep(forTimeInterval: 0.25)
                    tries += 1
                }
            }
            _ = itermControlState(ask: true)
        }
    }
    func openIterm() { background { sh("/usr/bin/open", ["-b", "com.googlecode.iterm2"]) } }
    func getIterm() { NSWorkspace.shared.open(URL(string: "https://iterm2.com")!) }
    func openAutomationSettings() {
        NSWorkspace.shared.open(URL(string:
            "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation")!)
    }

    func runSearch() {
        let q = query.trimmingCharacters(in: .whitespaces)
        guard !q.isEmpty, !searching else { return }
        searching = true
        DispatchQueue.global(qos: .userInitiated).async {
            let d = ahtJSON(["search", "--json", "--limit", "40"]
                            + (self.searchProject.map { ["--project", $0] } ?? [])
                            + ["--"] + q.split(separator: " ").map(String.init)) ?? [:]
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
                SecretFind(fingerprint: $0["fingerprint"] as? String ?? "",
                           project: $0["project"] as? String ?? "?",
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
                                           project: p, topic: "Project journal")
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

    /// Continue the project in another agent: the dry run of both ways (a
    /// new session, or the agent's own one), then the dialog. `resume`: its
    /// own session is the one picked first.
    func switchAgent(_ p: Project, to target: String, resume: Bool = false) {
        note(p.path, nil)
        busy("checking \(p.name)…") {
            var own: [String: Any] = [:]
            let both = DispatchGroup()              // the two dry runs at once
            DispatchQueue.global().async(group: both) {
                own = ahtJSON(["switch", p.path, "--to", target, "--resume", "--json"]) ?? [:]
            }
            let new = ahtJSON(["switch", p.path, "--to", target, "--json"]) ?? [:]
            both.wait()
            DispatchQueue.main.async {
                let newOK = self.problems(new) == nil, ownOK = self.problems(own) == nil
                if !newOK && !ownOK {
                    self.note(p.path, "Cannot switch now:\n\n" + (self.problems(new) ?? ""))
                    return
                }
                self.switchPlan = SwitchPlan(project: p, target: target, back: false, backTo: nil,
                                             plans: ["new": new, "resume": own],
                                             mode: ownOK && (resume || !newOK) ? "resume" : "new")
            }
        }
    }

    /// Hand Back: the agent that passed the work on goes on in its own
    /// session and reads only what changed. `to`: past several agents,
    /// straight back to that one.
    func handBack(_ p: Project, to: String? = nil) {
        note(p.path, nil)
        busy("checking \(p.name)…") {
            let plan = ahtJSON(["switch", p.path, "--back", "--json"] + (to.map { ["--to", $0] } ?? [])) ?? [:]
            DispatchQueue.main.async {
                if let why = self.problems(plan) {
                    self.note(p.path, "Cannot hand back now:\n\n" + why)
                    return
                }
                let target = plan["target"] as? String ?? to ?? p.handBack?.from ?? "claude"
                self.switchPlan = SwitchPlan(project: p, target: target, back: true, backTo: to,
                                             plans: ["back": plan], mode: "back")
            }
        }
    }

    /// The dialog's Switch, Hand Back or Summary Only (write the summary and
    /// the relay, open nothing).
    func confirmSwitch(_ s: SwitchPlan, briefOnly: Bool = false) {
        let p = s.project, label = AGENT_LABEL[s.target] ?? s.target
        var args = ["switch", p.path]
        if s.back {
            args += ["--back"] + (s.backTo.map { ["--to", $0] } ?? [])
        } else {
            args += ["--to", s.target]
                + (briefOnly ? ["--brief-only"] : s.mode == "resume" ? ["--resume"] : [])
        }
        let what = briefOnly ? "writing the summary…"
            : s.target == "kimi" ? "\(label) is reading the summary…" : "opening \(label)…"
        busy(what) {
            let d = ahtJSON(args + ["--apply", "--json"]) ?? [:]
            if let why = self.problems(d) {
                self.note(p.path, (s.back ? "Hand Back did not go through:\n\n"
                                          : "The switch did not go through:\n\n") + why)
                return
            }
            self.note(p.path, switchDoneText(d, project: p.path))
            if let b = d["brief"] as? String, !b.isEmpty {
                let f = summaryFile(b, in: p.path)
                DispatchQueue.main.async { self.summaries[p.path] = f }
            }
        }
    }

    // ---- tidy up ----

    func openTidy() {
        tidy = nil
        showTidy = true
        DispatchQueue.global(qos: .userInitiated).async {
            let d = ahtJSON(["tidy", "--json"]) ?? [:]
            let items = tidyItems(d)
            DispatchQueue.main.async { self.tidy = items }
        }
    }

    func chooseFolder(_ message: String) -> String? {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.message = message
        return panel.runModal() == .OK ? panel.url?.path : nil
    }

    func tidyConnect(_ t: TidyItem, to path: String?) {
        guard let dst = path ?? chooseFolder("Where is “\((t.path as NSString).lastPathComponent)” now?")
        else { return }
        let args = t.kind == "missing"
            ? ["tidy", "--relink=" + t.key, "--to=" + dst, "--apply", "--json"]
            : ["bind", "--store=" + t.key, "--to=" + dst, "--apply"]
        busy("reconnecting…") {
            let r = sh(PY, [ahtScript()] + args, mergeStderr: true)
            DispatchQueue.main.async {
                if !r.ok { _ = alert("That did not work", r.out) }
                self.openTidy()
            }
        }
    }

    func tidyForget(_ t: TidyItem) {
        guard alert("Forget “\((t.path as NSString).lastPathComponent)”?",
                    "aht stops tracking this folder. Its agent history is kept, and a backup "
                    + "can bring it back to any folder later.", confirm: "Forget") else { return }
        busy("forgetting…") {
            aht(["forget", "--uuid", t.key, "--apply"])
            DispatchQueue.main.async { self.openTidy() }
        }
    }

    // ---- what a session changed ----

    func openChanges(_ p: Project, session: String? = nil) {
        busy("reading the checkpoints…") {
            let d = ahtJSON(["changes", p.path, "--json"] + (session.map { ["--session", $0] } ?? [])) ?? [:]
            let files = ((d["files"] as? [[String: Any]]) ?? []).map {
                ChangedFile(path: $0["path"] as? String ?? "", name: $0["name"] as? String ?? "",
                            state: $0["state"] as? String ?? "", inside: $0["inside"] as? Bool ?? true,
                            added: $0["added"] as? Int ?? 0, removed: $0["removed"] as? Int ?? 0,
                            diff: $0["diff"] as? String ?? "")
            }
            DispatchQueue.main.async {
                self.changes = ChangesView(project: p, session: d["session"] as? String,
                                           title: (d["title"] as? String) ?? (d["session"] as? String ?? ""),
                                           sessions: (d["sessions"] as? [String]) ?? [], files: files)
            }
        }
    }

    func putBack(_ c: ChangesView, _ f: ChangedFile) {
        guard let sid = c.session,
              alert("Put “\(f.name)” back as it was before the session?",
                    f.state == "added" ? "The session created this file; it is removed. "
                        + "A copy of it is kept in ~/.aht/changes-backups."
                    : "What the file holds now is kept in ~/.aht/changes-backups first.",
                    confirm: "Put Back") else { return }
        busy("putting it back…") {
            let r = sh(PY, [ahtScript(), "changes", c.project.path, "--session", sid,
                            "--revert", f.path, "--apply"], mergeStderr: true)
            DispatchQueue.main.async {
                if !r.ok { _ = alert("That did not work", r.out) }
                self.openChanges(c.project, session: sid)
            }
        }
    }

    // ---- report and AI-use statement ----

    func loadReport() {
        let since: String? = ["week": "week", "month": "month", "30": nil, "all": nil][reportPeriod] ?? nil
        var args = ["report", "--json", "--by", reportBy]
        if let s = since { args += ["--since", s] }
        if reportPeriod == "30" {
            let f = DateFormatter()
            f.dateFormat = "yyyy-MM-dd"
            args += ["--since", f.string(from: Date().addingTimeInterval(-30 * 86400))]
        }
        DispatchQueue.global(qos: .userInitiated).async {
            let d = ahtJSON(args) ?? [:]
            let rows = ((d["rows"] as? [[String: Any]]) ?? []).map { r -> ReportRow in
                let key = r["key"] as? String ?? "?"
                let agents = ((r["agents"] as? [String: Int]) ?? [:]).sorted { $0.value > $1.value }
                    .map { "\(AGENT_LABEL[$0.key] ?? $0.key) \($0.value)" }.joined(separator: ", ")
                return ReportRow(name: self.reportBy == "project" ? (key as NSString).lastPathComponent : key,
                                 hours: (r["hours"] as? NSNumber)?.doubleValue ?? 0,
                                 sessions: r["sessions"] as? Int ?? 0, agents: agents)
            }
            let total = "\(d["total_sessions"] as? Int ?? 0) sessions · about "
                + "\((d["total_hours"] as? NSNumber)?.doubleValue ?? 0) h of session time"
            DispatchQueue.main.async {
                self.report = rows
                self.reportTotal = total
            }
        }
    }

    func statement(_ p: Project) {
        busy("writing the statement…") {
            let d = ahtJSON(["report", "--project", p.path, "--statement", "--json"]) ?? [:]
            DispatchQueue.main.async {
                self.textSheet = TextSheet(title: "AI-use statement: \(p.name)",
                                           text: (d["statement"] as? String ?? "") + "\n\n"
                                           + "_A draft from the agents' histories: check the "
                                           + "numbers and the tasks before you use it._",
                                           project: nil, topic: "Reports and an AI-use statement")
            }
        }
    }

    // ---- share a session ----

    func share(_ p: Project) {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = "\(p.name) session.html"
        panel.message = "A page of the latest session: keys aht recognises masked, e-mail and "
            + "local network addresses and your home folder removed. Look it through before "
            + "you share it."
        guard panel.runModal() == .OK, let url = panel.url else { return }
        busy("writing the page…") {
            let r = sh(PY, [ahtScript(), "share", p.path, "--format",
                            url.pathExtension.lowercased() == "md" ? "md" : "html",
                            "--out", url.path], mergeStderr: true)
            DispatchQueue.main.async {
                if r.ok { NSWorkspace.shared.activateFileViewerSelecting([url]) }
                else { _ = alert("The page could not be written", r.out) }
            }
        }
    }

    // ---- a leaked key out of the histories ----

    func removeSecret(_ f: SecretFind) {
        busy("looking for it…") {
            let d = ahtJSON(["secrets", "--redact", f.fingerprint, "--json"]) ?? [:]
            DispatchQueue.main.async {
                let blockers = (d["blockers"] as? [String]) ?? []
                if !blockers.isEmpty {
                    _ = alert("Not now", blockers.map { "• " + $0 }.joined(separator: "\n\n"))
                    return
                }
                let places = d["places"] as? Int ?? 0, files = d["files"] as? Int ?? 0
                guard alert("Remove \(f.masked) from the histories?",
                            "It appears in \(places) place\(places == 1 ? "" : "s") in \(files) "
                            + "history file\(files == 1 ? "" : "s"); each is replaced by "
                            + "“[removed by aht]”. The files are copied to ~/.aht/redacted first. "
                            + "Backups and copies on other machines still hold it, so replace the "
                            + "key where it was issued as well.", confirm: "Remove") else { return }
                self.busy("removing it…") {
                    let r = sh(PY, [ahtScript(), "secrets", "--redact", f.fingerprint, "--apply"],
                               mergeStderr: true)
                    DispatchQueue.main.async {
                        _ = alert(r.ok ? "Removed" : "That did not work", r.out)
                        self.checkSecrets(self.projects.first { $0.path == self.secretsFor })
                    }
                }
            }
        }
    }

    func testNotice() {
        background { aht(["notices", "--test"]) }
    }

    // ---- options that use tokens: asked for when first used ----

    func tokensOK(_ key: String, _ what: String) -> Bool {
        if flag(key, false) { return true }
        guard alert("Turn on \(what)?", (TOKEN_NOTES[key] ?? "") + "\n\nYou can turn it "
                    + "off again in Settings.", confirm: "Turn On") else { return false }
        set(key, "true")
        return true
    }

    // ---- undo a whole session ----

    func openUndo(_ p: Project, checkpoint: String? = nil) {
        busy("comparing with the copy…") {
            let d = ahtJSON(["undo", p.path, "--diff", "--json"]
                            + (checkpoint.map { ["--checkpoint", $0] } ?? [])) ?? [:]
            let cps = ((d["checkpoints"] as? [[String: Any]]) ?? []).map {
                Checkpoint(id: $0["id"] as? String ?? "", at: ($0["at"] as? NSNumber)?.doubleValue ?? 0,
                           agent: $0["agent"] as? String ?? "claude", title: $0["title"] as? String)
            }
            let files = ((d["files"] as? [[String: Any]]) ?? []).map { changedFile($0) }
            DispatchQueue.main.async {
                self.undo = UndoView(project: p, checkpoints: cps,
                                     chosen: (d["checkpoint"] as? [String: Any])?["id"] as? String,
                                     files: files, blockers: (d["blockers"] as? [String]) ?? [],
                                     warnings: (d["warnings"] as? [String]) ?? [])
            }
        }
    }

    func applyUndo(_ u: UndoView) {
        guard let cid = u.chosen else { return }
        let n = u.files.count
        guard alert("Put “\(u.project.name)” back the way it was?",
                    "\(n) file\(n == 1 ? "" : "s") go back to how they were when the session "
                    + "started: changed files are restored, removed ones return, and files made "
                    + "since are taken out. All of it is set aside in ~/.aht/undo first, so "
                    + "nothing is lost.", confirm: "Put Back") else { return }
        busy("putting the folder back…") {
            let d = ahtJSON(["undo", u.project.path, "--checkpoint", cid, "--apply", "--json"]) ?? [:]
            DispatchQueue.main.async {
                if let why = self.problems(d) {
                    _ = alert("Not put back", why)
                    return
                }
                self.undo = nil
                self.note(u.project.path, "Put back as it was when the session started. What "
                          + "the folder held is kept in " + (d["kept"] as? String ?? "~/.aht/undo"))
            }
        }
    }

    // ---- which projects are too big for a copy at each session start ----

    func applyMaxFiles(_ text: String) {
        guard let n = Int(text.filter { $0.isNumber }), n >= 100 else {
            _ = alert("Not a number of files", "Enter how many files a project may have and "
                      + "still get a copy, at least 100.")
            return
        }
        set("checkpoint_max_files", String(n))
        config["checkpoint_max_files"] = n
        checkCoverage(n)
    }

    func saveExcludes(_ text: String) {
        let names = text.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
        config["checkpoint_excludes"] = names
        background {
            aht(["config", "--set", "checkpoint_excludes=" + names.joined(separator: ","), "--no-reload"])
            DispatchQueue.main.async { self.checkCoverage(nil) }
        }
    }

    /// Counts the files of every project against the limit and says which
    /// ones get no copy (and, for those, their biggest folders).
    func checkCoverage(_ n: Int?, announce: Bool = true) {
        busy("counting the files in each project…") {
            let d = ahtJSON(["checkpoint", "--coverage", "--json"]
                            + (n.map { ["--max", String($0)] } ?? [])) ?? [:]
            let nf = NumberFormatter()
            nf.numberStyle = .decimal
            let num = { (x: Int) in nf.string(from: NSNumber(value: x)) ?? String(x) }
            let limit = d["max"] as? Int ?? n ?? 20000
            let rows = (d["projects"] as? [[String: Any]]) ?? []
            let name = { (r: [String: Any]) in ((r["project"] as? String ?? "?") as NSString).lastPathComponent }
            let over = rows.filter { $0["over"] as? Bool ?? false }
            let big = rows.filter { !($0["over"] as? Bool ?? false) && ($0["files"] as? Int ?? 0) > 20000 }
            let note = over.isEmpty ? "Every project is under \(num(limit)) files."
                : "No copy for: " + over.map { "\(name($0)) (\(num($0["files"] as? Int ?? 0)) files)" }
                    .joined(separator: ", ")
            var body = over.isEmpty
                ? "Every project has at most \(num(limit)) files, so each one gets a copy when a "
                  + "session starts."
                : "These projects have more than \(num(limit)) files. They get no copy when a "
                  + "session starts, so Undo a Session does not work for them:\n\n"
                  + over.map { r in
                      let top = ((r["biggest"] as? [[String: Any]]) ?? []).prefix(2).map {
                          "\($0["name"] as? String ?? "?")/ \(num($0["files"] as? Int ?? 0))" }
                      return "• \(name(r)): \(num(r["files"] as? Int ?? 0)) files"
                          + (top.isEmpty ? "" : " — most in " + top.joined(separator: ", "))
                  }.joined(separator: "\n")
                  + "\n\nTo cover one anyway, raise the limit, or leave its biggest folders "
                  + "out of the copies (the field below the limit)."
            if !big.isEmpty {
                body += "\n\nCovered, but big: " + big.map { r in
                    "\(name(r)) (\(num(r["files"] as? Int ?? 0)) files, about "
                        + "\(Int(((r["seconds"] as? NSNumber)?.doubleValue ?? 0).rounded())) s)"
                }.joined(separator: ", ") + ". Each session start there copies every file in the "
                    + "background, and each kept copy adds file-system entries (roughly 100 MB "
                    + "per 100,000 files), though no room for the data."
            }
            DispatchQueue.main.async {
                self.coverageNote = note
                if announce { _ = alert(over.isEmpty ? "Every project is covered"
                                        : "\(over.count) project\(over.count == 1 ? "" : "s") get no copy",
                                        body) }
            }
        }
    }

    // ---- loose ends ----

    func openLooseEnds() {
        looseEnds = nil
        showLooseEnds = true
        DispatchQueue.global(qos: .userInitiated).async {
            let d = ahtJSON(["loose-ends", "--json"]) ?? [:]
            let rows = ((d["loose_ends"] as? [[String: Any]]) ?? []).map { r in
                LooseEnd(project: r["project"] as? String ?? "?", agent: r["agent"] as? String ?? "claude",
                         session: r["session"] as? String ?? "",
                         last: (r["last"] as? NSNumber)?.doubleValue ?? 0,
                         open: r["open"] as? Bool ?? false,
                         items: ((r["items"] as? [[String: Any]]) ?? []).map {
                             LooseItem(kind: $0["kind"] as? String ?? "", text: $0["text"] as? String ?? "",
                                       sub: ($0["items"] as? [String]) ?? [])
                         })
            }
            DispatchQueue.main.async { self.looseEnds = rows }
        }
    }

    func resumeSession(_ path: String, agent: String, session: String) {
        background { aht(["resume-here", path, "--session", session, "--agent", agent]) }
    }

    /// Every session of the project, each branch under the session it came from.
    func openSessionList(_ p: Project) {
        busy("reading the sessions…") {
            let d = ahtJSON(["sessions", p.path, "--json"]) ?? [:]
            let items = ((d["sessions"] as? [[String: Any]]) ?? []).map(SessionItem.init)
            DispatchQueue.main.async { self.sessionList = SessionListView(project: p, items: items) }
        }
    }

    // ---- a second opinion (uses tokens) ----

    func openOpinion(_ p: Project) {
        guard tokensOK("second_opinion", "second opinions") else { return }
        loadOpinion(p, run: nil)
    }

    func loadOpinion(_ p: Project, run: String?) {
        DispatchQueue.global(qos: .userInitiated).async {
            let all = (ahtJSON(["second-opinion", "--list", "--json"])?["opinions"]
                       as? [[String: Any]]) ?? []
            var v = OpinionView(project: p)
            let f = DateFormatter()
            f.dateStyle = .short
            f.timeStyle = .short
            v.runs = all.filter { ($0["project"] as? String) == p.path }.map {
                let t = ($0["started"] as? NSNumber)?.doubleValue ?? 0
                return (id: $0["id"] as? String ?? "",
                        label: f.string(from: Date(timeIntervalSince1970: t)) + " — "
                            + String(($0["task"] as? String ?? "").prefix(40)))
            }
            v.current = run ?? v.runs.first?.id
            if let rid = v.current, let d = ahtJSON(["second-opinion", "--show", rid, "--diff", "--json"]) {
                v.task = d["task"] as? String ?? ""
                v.taken = d["taken"] as? String
                v.changedMeanwhile = (d["project_changed"] as? [String]) ?? []
                let res = (d["results"] as? [String: Any]) ?? [:]
                v.results = ((d["agents"] as? [String]) ?? []).map { a in
                    let r = (res[a] as? [String: Any]) ?? [:]
                    return OpinionResult(id: a, state: r["state"] as? String ?? "?",
                                         answer: r["answer"] as? String ?? "",
                                         seconds: r["seconds"] as? Int,
                                         cost: (r["cost_usd"] as? NSNumber)?.doubleValue,
                                         files: ((r["files"] as? [[String: Any]]) ?? []).map { changedFile($0) })
                }
                v.finished = !v.results.contains { ["working", "starting"].contains($0.state) }
            }
            DispatchQueue.main.async { self.opinion = v }
        }
    }

    func startOpinion(_ p: Project, task: String) {
        busy("copying the project twice…") {
            let d = ahtJSON(["second-opinion", p.path, "--task=" + task, "--json"]) ?? [:]
            DispatchQueue.main.async {
                if let why = self.problems(d) {
                    _ = alert("Not started", why)
                    return
                }
                self.loadOpinion(p, run: d["id"] as? String)
            }
        }
    }

    func takeOpinion(_ v: OpinionView, from agent: String) {
        guard let rid = v.current else { return }
        let label = AGENT_LABEL[agent] ?? agent
        busy("checking…") {
            let plan = ahtJSON(["second-opinion", "--take", rid, "--from", agent, "--json"]) ?? [:]
            DispatchQueue.main.async {
                if let why = self.problems(plan) {
                    _ = alert("Not now", why)
                    return
                }
                let n = ((plan["files"] as? [[String: Any]]) ?? []).count
                guard alert("Use \(label)'s changes in “\(v.project.name)”?",
                            "\(n) file\(n == 1 ? "" : "s") of the project become \(label)'s "
                            + "version. What they hold now is set aside in ~/.aht/undo first.",
                            confirm: "Use Them") else { return }
                self.busy("bringing them in…") {
                    let d = ahtJSON(["second-opinion", "--take", rid, "--from", agent,
                                     "--apply", "--json"]) ?? [:]
                    DispatchQueue.main.async {
                        if let why = self.problems(d) {
                            _ = alert("Not done", why)
                        } else {
                            self.note(v.project.path, "\(label)'s changes are in the project; "
                                      + "what was there is kept in " + (d["kept"] as? String ?? ""))
                        }
                        self.loadOpinion(v.project, run: rid)
                    }
                }
            }
        }
    }

    func discardOpinion(_ v: OpinionView) {
        guard let rid = v.current,
              alert("Remove the two copies?", "Their answers go with them. The project is "
                    + "not touched.", confirm: "Remove") else { return }
        DispatchQueue.global(qos: .userInitiated).async {
            aht(["second-opinion", "--discard", rid])
            self.loadOpinion(v.project, run: nil)
        }
    }

    // ---- the night shift (uses tokens) ----

    func openNightShift(_ p: Project) {
        guard tokensOK("night_shift", "the night shift") else { return }
        loadNight(p)
    }

    func loadNight(_ p: Project) {
        DispatchQueue.global(qos: .userInitiated).async {
            let jobs = ((ahtJSON(["night-shift", "--list", "--json"])?["jobs"] as? [[String: Any]]) ?? [])
                .filter { ($0["project"] as? String) == p.path }
                .map { j in
                    NightJob(id: j["id"] as? String ?? "", state: j["state"] as? String ?? "?",
                             startAt: (j["start_at"] as? NSNumber)?.doubleValue ?? 0,
                             backAt: (j["back_at"] as? NSNumber)?.doubleValue ?? 0,
                             remote: j["remote"] as? String ?? "", task: j["task"] as? String ?? "",
                             log: (j["log"] as? [String]) ?? [])
                }
            DispatchQueue.main.async { self.night = NightShiftView(project: p, jobs: jobs.reversed()) }
        }
    }

    func planNight(_ p: Project, task: String, start: Date?, back: Date) {
        let f = DateFormatter()
        f.dateFormat = "HH:mm"
        var args = ["night-shift", p.path, "--task=" + task, "--back", f.string(from: back),
                    "--start", start.map { f.string(from: $0) } ?? "now", "--apply", "--json"]
        if let name = machine { args += ["--to=" + name] }
        busy("planning the night shift…") {
            let d = ahtJSON(args) ?? [:]
            DispatchQueue.main.async {
                if let why = self.problems(d) {
                    _ = alert("Not planned", why)
                    return
                }
                self.loadNight(p)
            }
        }
    }

    func cancelNight(_ p: Project, _ j: NightJob) {
        // once it has started, the project is over there, and cancelling also
        // drops taking it back
        if j.state == "started" {
            guard alert("Cancel the night shift for “\(p.name)”?",
                        "The project stays on \(j.remote.isEmpty ? "the other machine" : j.remote) "
                        + "until you take it back (Take Back…). aht no longer brings it back by "
                        + "itself at \(NightShiftSheet.when(j.backAt)).",
                        confirm: "Cancel the Shift", cancel: "Keep It") else { return }
        }
        DispatchQueue.global(qos: .userInitiated).async {
            let r = sh(PY, [ahtScript(), "night-shift", "--cancel", j.id], mergeStderr: true)
            DispatchQueue.main.async {
                if !r.out.isEmpty { _ = alert("Night shift", r.out) }
                self.loadNight(p)
            }
        }
    }

    // ---- Spotlight: every session's title, found from anywhere ----

    func indexSpotlight() {
        let on = flag("spotlight")
        DispatchQueue.global(qos: .utility).async {
            let idx = CSSearchableIndex.default()
            guard on else {
                idx.deleteSearchableItems(withDomainIdentifiers: ["sessions"]) { _ in }
                return
            }
            let rows = (ahtJSON(["sessions", "--json", "--limit", "800"])?["sessions"]
                        as? [[String: Any]]) ?? []
            let f = DateFormatter()
            f.dateStyle = .medium
            f.timeStyle = .none
            let items: [CSSearchableItem] = rows.compactMap { r in
                guard let agent = r["agent"] as? String, let sid = r["session"] as? String,
                      let proj = r["project"] as? String else { return nil }
                let name = (proj as NSString).lastPathComponent
                let a = CSSearchableItemAttributeSet(contentType: UTType.text)
                a.title = (r["title"] as? String) ?? "Session in \(name)"
                var desc = "\(AGENT_LABEL[agent] ?? agent) session in \(name)"
                if let t = (r["updated"] as? NSNumber)?.doubleValue {
                    desc += ", " + f.string(from: Date(timeIntervalSince1970: t))
                }
                a.contentDescription = desc
                a.keywords = [name, AGENT_LABEL[agent] ?? agent, "aht", "session"]
                return CSSearchableItem(uniqueIdentifier: [agent, sid, proj].joined(separator: "\t"),
                                        domainIdentifier: "sessions", attributeSet: a)
            }
            idx.deleteSearchableItems(withDomainIdentifiers: ["sessions"]) { _ in
                idx.indexSearchableItems(items) { err in
                    if let e = err { NSLog("aht: Spotlight did not take the sessions: \(e)") }
                }
            }
        }
    }

    func copyBackupsNow() {
        busy("copying the backups…") {
            let r = sh(PY, [ahtScript(), "backup", "--offsite"], mergeStderr: true)
            DispatchQueue.main.async { _ = alert(r.ok ? "Backups copied" : "Not copied", r.out) }
        }
    }

    /// Fetch Backups From…: the machine that keeps the backups holds a folder
    /// for each computer that copies there; the sheet lists them.
    func openFetchBackups() {
        let there = text("offsite_backup", "")
        guard !there.isEmpty else { return }
        if offsite?.machine == there {
            offsite?.loading = true
            offsite?.error = nil
            offsite?.result = nil
        } else {
            offsite = OffsiteView(machine: there)
        }
        DispatchQueue.global(qos: .userInitiated).async {
            let r = shWithStderr(PY, [ahtScript(), "backup", "--offsite-list", "--json"])
            let d = (try? JSONSerialization.jsonObject(with: Data(r.out.utf8))) as? [String: Any]
            DispatchQueue.main.async {
                guard self.offsite?.machine == there else { return }
                self.offsite?.loading = false
                guard r.ok, let d = d, !(d["error"] is String) else {
                    let why = ((d?["error"] as? String) ?? r.err)
                        .trimmingCharacters(in: .whitespacesAndNewlines)
                    self.offsite?.error = "aht could not ask \(there)"
                        + (why.isEmpty ? "; see the log (Settings)." : ": " + why)
                    return
                }
                let folders = offsiteFolders(d)
                self.offsite?.folders = folders
                if !folders.contains(where: { $0.id == self.offsite?.pick }) {
                    self.offsite?.pick = firstPick(folders)
                }
            }
        }
    }

    /// Adds the backups that are missing here from one computer's folder there;
    /// a backup here is never replaced.
    func fetchBackups() {
        guard let v = offsite, let f = v.folders.first(where: { $0.id == v.pick }) else { return }
        offsite?.fetching = true
        offsite?.result = nil
        DispatchQueue.global(qos: .userInitiated).async {
            let r = shWithStderr(PY, [ahtScript(), "backup", "--fetch-offsite", "--from", f.id,
                                      "--json"])
            let d = (try? JSONSerialization.jsonObject(with: Data(r.out.utf8))) as? [String: Any]
            DispatchQueue.main.async {
                guard self.offsite?.id == v.id else { return }
                self.offsite?.fetching = false
                // a failed run's JSON counts only when it says what went wrong
                self.offsite?.result = fetchedText(r.ok || d?["error"] is String ? d : nil, f,
                                                   said: r.err)
            }
        }
    }

    func showGuide(_ topic: String? = nil) {
        showGuideWindow(topic)
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
        let held = projects.filter { $0.awayRemote == m.name || $0.handing?.machine == m.name }
            .map { $0.path }
        if !held.isEmpty {
            _ = alert("\(m.name) still holds handed-over projects",
                      "Take these back first. If \(m.name) is gone for good, select each one "
                      + "and press Release…: the files here stay as they are.\n\n"
                      + held.map { "• " + $0 }.joined(separator: "\n"))
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
        onChange?()
    }

    /// A chime picked in Settings plays at once, at the volume set.
    func playChime(_ choice: String) {
        ChimePlayer.shared.play(choice, volume: number("chime_volume", 70), now: true)
    }

    func chooseChimeFile(_ key: String) {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.audio]
        panel.allowsMultipleSelection = false
        panel.message = "Choose a short sound for the chime"
        guard panel.runModal() == .OK, let url = panel.url else { return }
        let path = (url.path as NSString).abbreviatingWithTildeInPath
        set(key, path)
        playChime(path)
    }

    /// "" = automatic: iTerm when installed, else Terminal.
    func setTerminal(_ app: String) {
        config["terminal_app"] = app.isEmpty ? nil : app
        background {
            aht(app.isEmpty ? ["config", "--unset", "terminal_app"]
                            : ["config", "--set", "terminal_app=\(app)", "--no-reload"])
        }
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
            let rows = (d["planned"] as? [[String: Any]]) ?? []
            let planned = rows.count
            // adopt also takes on a project the user told aht to forget: say which
            let forgot = forgottenNote(rows)
            let forgotNote = forgot.isEmpty ? "" : "\n\n" + forgot
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
                            + "Nothing is moved, renamed or deleted." + forgotNote,
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
        busy("restarting the watcher…") {
            let r = aht(["reload"])
            if let why = self.notRestarted(r.out) {
                DispatchQueue.main.async { _ = alert("The watcher was not restarted", why) }
            }
        }
    }

    func openData() { sh("/usr/bin/open", [HOME + "/.aht"]) }
    func openLog() { sh("/usr/bin/open", ["-t", HOME + "/.aht/aht.log"]) }

    func setLoginItem(_ on: Bool, note: Bool = true) {
        let fm = FileManager.default
        if !on {
            sh("/bin/launchctl", ["bootout", "gui/\(getuid())/\(TRAY_LABEL)"])
            try? fm.removeItem(atPath: TRAY_PLIST)
        } else {
            // whichever tray this is: the app bundle's executable or the bare binary
            let bin = Bundle.main.executablePath ?? (TOOLS + "/aht-tray")
            try? loginItemPlist(bin)?.write(to: URL(fileURLWithPath: TRAY_PLIST), options: .atomic)
        }
        loginItem = fm.fileExists(atPath: TRAY_PLIST)
        // the switch answers the tray-at-login question (status's
        // autostart.answered), as on Windows and Linux; on a Mac `aht
        // autostart` only notes the answer, the plist above is the switch.
        // On the state queue, so a refresh after this reads the answer
        // (Getting started: a no makes the step optional)
        if note { q.async { aht(["autostart", on ? "on" : "off"]) } }
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
                if r.ok { self.refresh { self.offerSetup?() } }
            }
        }
    }

    func offerInstallIfNeeded() {
        guard let res = BUNDLE_RES else { return }
        let bundled = coreVersion(res + "/aht.py")
        let bundledStr = bundled.map(String.init).joined(separator: ".")
        let defaults = UserDefaults.standard
        if !FileManager.default.fileExists(atPath: TOOLS + "/aht.py") {
            // asked once per app version; Settings keeps the option available
            guard defaults.string(forKey: "declinedSetup") != bundledStr else { return }
            openWelcomeFirst?(bundledStr)
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
                    Image(systemName: "questionmark.circle").imageScale(.large)
                }
                .buttonStyle(.borderless)
                .help("The whole guide: every feature, every setting, and what only the "
                      + "terminal does")
                Text(m.summary).foregroundColor(.secondary).lineLimit(1)
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
        .sheet(item: $m.switchPlan) { plan in SwitchSheet(plan: plan) }
        .sheet(item: $m.rules) { r in RulesSheet(r: r) }
        .sheet(item: $m.textSheet) { t in TextSheetView(t: t) }
        .sheet(isPresented: $m.showSecrets) { SecretsSheet() }
        .sheet(isPresented: $m.showTidy) { TidySheet() }
        .sheet(isPresented: $m.showReport) { ReportSheet() }
        .sheet(item: $m.changes) { c in ChangesSheet(c: c) }
        .sheet(item: $m.undo) { u in UndoSheet(u: u) }
        .sheet(isPresented: $m.showLooseEnds) { LooseEndsSheet() }
        .sheet(item: $m.opinion) { v in OpinionSheet(v: v) }
        .sheet(item: $m.night) { v in NightShiftSheet(v: v) }
        .sheet(isPresented: $m.showWorkspace) { WorkspaceSheet() }
        .sheet(isPresented: $m.showGettingStarted) { GettingStartedSheet() }
        .sheet(item: $m.sessionList) { v in SessionListSheet(v: v) }
        .sheet(isPresented: $m.showUpdate) { UpdateSheet() }
        .sheet(item: $m.offsite) { _ in FetchBackupsSheet() }
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
                    Text("Machine: \(one)").foregroundColor(.secondary).lineLimit(1).fixedSize()
                }
                Button("Sync Now") { m.syncNow() }
                    .disabled(m.working != nil || m.machine == nil)
                Button("Find Moved Folders") { m.reconcile() }
                    .disabled(m.working != nil)
                HelpButton("Folders that move")
                Menu("Look Back") {
                    Button("Loose Ends…") { m.openLooseEnds() }
                    Button("Report…") { m.showReport = true; m.loadReport() }
                }
                .fixedSize()
                if m.tidyCount > 0 {
                    Button("Tidy Up (\(m.tidyCount))…") { m.openTidy() }
                }
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
                                                  : p.handing != nil ? .orange
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
                Text(tilde(p.path)).font(.caption).foregroundColor(.secondary)
                    .lineLimit(1).truncationMode(.middle).textSelection(.enabled)
                if let h = p.handing, h.state != "running" { HandingBanner(p: p, h: h) }
                if let s = p.syncPaused, let to = p.mirror, p.away == nil, p.handing == nil {
                    SyncPausedBanner(p: p, s: s, to: s.machine ?? to)
                }
                if let r = p.handBack, p.away == nil { RelayLine(p: p, r: r) }
                HStack(spacing: 10) {
                    if p.away != nil {
                        Button("Take Back…") { m.takeBack(p) }
                            .keyboardShortcut(.defaultAction)
                        Button("Open Session") { m.openSession(p) }
                        Button("Release…") { m.release(p) }
                            .help("Stop waiting for it: the files here stay as they are, "
                                  + "and the copy over there is not touched")
                        HelpButton("Hand a project over")
                    } else if p.exists {
                        Button(m.machine.map { "Hand Over to \($0)…" } ?? "Hand Over…") {
                            m.handOver(p)
                        }
                        .disabled(m.machine == nil || !m.supported || p.open != nil
                                  || p.handing != nil)
                        Toggle("Keep in sync" + (p.mirror.map { " with \($0)" } ?? ""),
                               isOn: Binding(get: { p.mirror != nil },
                                             set: { m.keepInSync(p, $0) }))
                            .disabled(m.machine == nil || !m.supported || p.handing != nil)
                        HelpButton("Hand a project over")
                        Button("Continue Session") { m.continueHere(p) }
                            .disabled(p.sessions == 0 || p.handing != nil)
                        Menu("Switch Agent") {
                            ForEach(switchItems(p, m.agentCLIs), id: \.self) { i in
                                Button(i.title) {
                                    if i.back { m.handBack(p) } else { m.switchAgent(p, to: i.to) }
                                }
                                if i.back { Divider() }
                            }
                        }
                        .fixedSize()
                        .disabled(p.sessions == 0 && p.agents.isEmpty || p.handing != nil)
                        HelpButton("Continue in another agent")
                    }
                    Spacer()
                    if p.exists {
                        Menu("More") {
                            Button("Show Sessions…") { m.openSessionList(p) }
                            Button("What Changed…") { m.openChanges(p) }
                            Button("Undo a Session…") { m.openUndo(p) }
                            Button("Journal") { m.journal(p) }
                            Button("AI-Use Statement") { m.statement(p) }
                            Button("Share a Session…") { m.share(p) }
                            Divider()
                            Button("Project Rules…") { m.openRules(p) }
                            Button("Check for Secrets") { m.checkSecrets(p) }
                            Divider()
                            Button("Second Opinion…") { m.openOpinion(p) }
                            Button("Night Shift…") { m.openNightShift(p) }
                                .disabled(m.machine == nil || !m.supported)
                            Divider()
                            Button("Show in Finder") { m.reveal(p) }
                        }
                        .fixedSize()
                        HelpButton("The window at a glance")
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
                if p.limitSession != nil && p.away == nil {
                    HStack(spacing: 10) {
                        Text("Claude stopped at its usage limit"
                             + (p.limitResets.map { "; it resets \($0)" } ?? "") + ".")
                            .font(.callout).foregroundColor(.orange)
                        if let t = m.limitSwitchTo {
                            Button("Continue in \(AGENT_LABEL[t] ?? t)…") { m.switchAgent(p, to: t) }
                                .controlSize(.small)
                        } else {
                            Text("Settings can offer another agent here.")
                                .font(.caption).foregroundColor(.secondary)
                        }
                    }
                }
                if let n = m.notes[p.path] {
                    HStack(alignment: .top, spacing: 10) {
                        ScrollView {
                            Text(n).font(.callout).textSelection(.enabled)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                        if let f = m.summaries[p.path] {
                            Button("Show Summary in Finder") {
                                NSWorkspace.shared.selectFile(f, inFileViewerRootedAtPath: "")
                            }
                        }
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

/// A handover that did not finish (yet): what is known, and the two ways on.
/// The notices check settles it by itself once the other machine answers.
struct HandingBanner: View {
    @EnvironmentObject var m: AppModel
    let p: Project
    let h: Handing

    var body: some View {
        let silent = h.state == "unreachable"
        let at = clock(silent ? h.silentSince ?? h.since : h.since)
        HStack(alignment: .center, spacing: 10) {
            Image(systemName: "exclamationmark.triangle.fill").foregroundColor(.orange)
            VStack(alignment: .leading, spacing: 2) {
                Text(silent ? "Handover to \(h.machine) did not finish"
                            : "Handover to \(h.machine) unfinished: checking…")
                    .fontWeight(.semibold)
                Text(silent
                     ? "\(h.machine) has not answered" + (at.isEmpty ? "" : " since \(at)")
                       + ". Release lets the project go on here; what was done on "
                       + "\(h.machine) stays there."
                     : (at.isEmpty ? "" : "Started at \(at). ") + "aht asks \(h.machine) "
                       + "whether the session there started, then finishes the handover or "
                       + "undoes it.")
                    .font(.caption).foregroundColor(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 8)
            Button("Check Now") { m.checkHanding(p) }.disabled(!m.supported)
            Button("Release…") { m.release(p) }     // after an hour of silence, the way on
                .keyboardShortcut(h.release ? .defaultAction : nil)
        }
        .padding(.horizontal, 10).padding(.vertical, 6)
        .background(RoundedRectangle(cornerRadius: 6).fill(Color.orange.opacity(0.12)))
        .disabled(m.working != nil)
    }
}

/// Keep in sync that waits for the user: Release paused it so the copy left
/// on the other machine is not overwritten. Turning it back on is the way on.
struct SyncPausedBanner: View {
    @EnvironmentObject var m: AppModel
    let p: Project
    let s: SyncPause
    let to: String

    var why: String {
        let at = clock(s.at)
        let copy: String = s.reason == "released"
            ? "You released the project" + (at.isEmpty ? "" : " at \(at)") + ", so the copy"
            : "The copy"
        return copy + " on \(to) stays as it is. Turn sync back on to make it match this Mac again."
    }

    var body: some View {
        HStack(alignment: .center, spacing: 10) {
            Image(systemName: "pause.circle.fill").foregroundColor(.orange)
            VStack(alignment: .leading, spacing: 2) {
                Text("Keep in sync with \(to) is paused").fontWeight(.semibold)
                Text(why)
                    .font(.caption).foregroundColor(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 8)
            Button("Turn Sync Back On…") { m.resumeSync(p, to) }.disabled(!m.supported)
        }
        .padding(.horizontal, 10).padding(.vertical, 6)
        .background(RoundedRectangle(cornerRadius: 6).fill(Color.orange.opacity(0.12)))
        .disabled(m.working != nil)
    }
}

/// Another agent has the work here since a switch: who, since when, and
/// Hand Back into the first agent's own session.
struct RelayLine: View {
    @EnvironmentObject var m: AppModel
    let p: Project
    let r: Relay

    var body: some View {
        HStack(alignment: .center, spacing: 10) {
            Image(systemName: "arrow.left.arrow.right.circle.fill").foregroundColor(.accentColor)
            Text(relayLine(r)).lineLimit(2).fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 8)
            Button("Hand Back…") { m.handBack(p) }
                .disabled(p.handing != nil)
                .help("\(AGENT_LABEL[r.from] ?? r.from) goes on in its own session and reads "
                      + "only what changed")
        }
        .padding(.horizontal, 10).padding(.vertical, 4)
        .background(RoundedRectangle(cornerRadius: 6).fill(Color.accentColor.opacity(0.10)))
        .disabled(m.working != nil)
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
                if m.itermInstalled {
                    Button("Restore Workspace…") { m.openWorkspaces() }
                        .help("Open the iTerm2 tabs and sessions of a saved workspace again")
                    Button("Name Sessions After Their Tabs…") { m.syncNamesToTabs() }
                        .disabled(m.working != nil)
                        .help("Every open Claude session takes its iTerm2 tab's title")
                }
                Button("Refresh") { m.refreshBoard() }.disabled(m.boardLoading)
                HelpButton("Sessions: what runs right now")
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

    var origin: String {
        switch r.titleOrigin {
        case "tab": return r.tab == nil ? "an earlier tab's title" : "from its tab"
        case "aht": return "named in aht"
        case "yours": return "named by you"
        case "automatic": return "Claude's own title"
        default: return ""
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            row
            if r.agent == "claude" && (r.title != nil || r.pendingTitle != nil || r.local) {
                HStack(spacing: 8) {
                    Text("“\(r.title ?? "no name yet")”").fontWeight(.medium).lineLimit(1)
                    if !origin.isEmpty {
                        Text(origin).font(.caption).foregroundColor(.secondary)
                    }
                    if let p = r.pendingTitle {
                        Text("→ “\(p)” at its next prompt").font(.caption).foregroundColor(.blue)
                    }
                    if let t = r.tab, t != r.title {
                        Text("tab: \(t)").font(.caption).foregroundColor(.secondary)
                    }
                    if r.local && r.session != nil {
                        Button("Rename…") { m.renameSession(r) }
                            .controlSize(.small).buttonStyle(.borderless)
                    }
                    if r.inIterm {
                        Button("Go to Tab") { m.gotoTab(r) }
                            .controlSize(.small).buttonStyle(.borderless)
                    }
                }
                .padding(.leading, 18)
                if r.limitResets != nil || !r.issues.isEmpty {
                    HStack(spacing: 8) {
                        if let t = r.limitResets {
                            Text("stopped at the usage limit · resets \(t)"
                                 + (r.limitAuto ? " · continues by itself then" : ""))
                                .font(.caption).foregroundColor(.orange)
                        }
                        ForEach(r.issues, id: \.self) { i in
                            Text(issueText(i)).font(.caption).foregroundColor(.orange)
                                .help(issueHelp(i))
                        }
                        if r.canRestart && !r.issues.isEmpty {
                            Button("Restart in Its Tab…") { m.restartSession(r) }
                                .controlSize(.small).buttonStyle(.borderless)
                        }
                        if r.issues.contains("twice") || r.issues.contains("stuck") {
                            Button("End It…") { m.closeSession(r) }
                                .controlSize(.small).buttonStyle(.borderless)
                        }
                    }
                    .padding(.leading, 18)
                }
            }
        }
    }

    func issueText(_ i: String) -> String {
        switch i {
        case "twice": return "open twice"
        case "stuck": return "working for hours, nothing written"
        case "outside the app": return "not in the Claude app"
        case "older": return "Claude Code \(r.version ?? "") (\(r.installed ?? "") installed)"
        default: return i
        }
    }

    func issueHelp(_ i: String) -> String {
        switch i {
        case "twice": return "The same conversation is open in two processes; both write to it."
        case "stuck": return "It says it is working, but nothing was written for hours: "
            + "probably a leftover."
        case "outside the app": return "It started before Remote Control was on for every "
            + "session. Restarting it in its tab brings it into the app."
        case "older": return "It runs the Claude Code version it started with. Restarting it "
            + "in its tab moves it to the installed one."
        default: return ""
        }
    }

    var row: some View {
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
    @FocusState private var focused: Bool

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 10) {
                if let p = m.searchProject {
                    Button {
                        m.searchProject = nil
                    } label: {
                        Label((p as NSString).lastPathComponent, systemImage: "xmark.circle.fill")
                    }
                    .help("Searching this project only; click to search everything")
                }
                TextField("Search every agent's sessions — \"a phrase\" in quotes",
                          text: $m.query)
                    .textFieldStyle(.roundedBorder)
                    .focused($focused)
                    .onSubmit { m.runSearch() }
                Button("Search") { m.runSearch() }
                    .keyboardShortcut(.defaultAction)
                    .disabled(m.query.trimmingCharacters(in: .whitespaces).isEmpty || m.searching)
                HelpButton("Search every session")
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
        .onAppear { focused = true }
        .onChange(of: m.focusSearch) { _ in focused = true }
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
            headed("Hand “\(plan.project.name)” over to \(plan.remote)?", "Hand a project over")
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

/// Switch Agent and Hand Back: what the dry run found for the way picked
/// (a new session or the agent's own one), then Switch, or Summary Only.
struct SwitchSheet: View {
    @EnvironmentObject var m: AppModel
    @State var plan: SwitchPlan

    var body: some View {
        let label = AGENT_LABEL[plan.target] ?? plan.target
        let d = plan.plans[plan.mode] ?? [:]
        let blocked = m.problems(d)
        VStack(alignment: .leading, spacing: 12) {
            headed(plan.back ? "Hand “\(plan.project.name)” back to \(label)?"
                             : "Continue “\(plan.project.name)” in \(label)?",
                   "Continue in another agent")
            if !plan.back {
                Picker("\(label) goes on in", selection: $plan.mode) {
                    Text("a new session").tag("new")
                    Text("its own session").tag("resume")
                }
                .pickerStyle(.radioGroup)
            }
            Text(blocked.map {
                (plan.mode == "new" ? "A new session cannot start now:"
                                    : "\(label)'s own session cannot be used now:") + "\n\n" + $0
            } ?? switchText(d, mode: plan.mode, hook: m.hookOn))
                .frame(maxWidth: .infinity, alignment: .leading)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
            if blocked == nil, let line = d["start_line"] as? String, !line.isEmpty {
                Text(line).font(.system(.caption, design: .monospaced)).foregroundColor(.secondary)
                    .lineLimit(3).truncationMode(.middle).textSelection(.enabled)
                    .help("What aht runs in the new terminal window")
            }
            if !plan.back {
                Text("Summary Only writes the summary into the project and opens nothing; no "
                     + "agent runs.")
                    .font(.caption).foregroundColor(.secondary)
            }
            HStack {
                if !plan.back {
                    Button("Summary Only") {
                        let s = plan
                        m.switchPlan = nil
                        m.confirmSwitch(s, briefOnly: true)
                    }
                    .help("Write the summary into the project and open nothing")
                }
                Spacer()
                Button("Cancel") { m.switchPlan = nil }.keyboardShortcut(.cancelAction)
                Button(plan.back ? "Hand Back" : "Switch") {
                    let s = plan
                    m.switchPlan = nil
                    m.confirmSwitch(s)
                }
                .keyboardShortcut(.defaultAction)
                .disabled(blocked != nil)
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
            headed("Project rules: \(r.project.name)", "One set of project rules")
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
            HStack(spacing: 6) {
                Text(t.title).font(.headline)
                if let topic = t.topic { HelpButton(topic) }
            }
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

/// The guide cut at its "## " headings: (title, text); the part before the
/// first heading is the introduction.
func guideTopics() -> [(title: String, text: String)] {
    var out: [(title: String, text: String)] = []
    var title = "Introduction", buf: [String] = []
    for line in guideText().components(separatedBy: "\n") {
        if line.hasPrefix("## ") {
            out.append((title, buf.joined(separator: "\n")))
            title = String(line.dropFirst(3))
            buf = [line]
        } else {
            buf.append(line)
        }
    }
    out.append((title, buf.joined(separator: "\n")))
    return out
}

final class GuideModel: ObservableObject {
    @Published var topic: String? = "Introduction"
}
let GUIDE = GuideModel()
var GUIDE_WINDOW: NSWindow?

/// Opens the guide in a window of its own (so a "?" works from a dialog
/// too), at the section whose heading starts with `topic`; nil opens it at
/// the beginning, with every section in the list on the left.
func showGuideWindow(_ topic: String? = nil) {
    let titles = guideTopics().map { $0.title }
    if let t = topic?.lowercased() {
        GUIDE.topic = titles.first { $0.lowercased().hasPrefix(t) } ?? "Introduction"
    } else {
        GUIDE.topic = "Introduction"
    }
    if GUIDE_WINDOW == nil {
        let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 900, height: 660),
                         styleMask: [.titled, .closable, .miniaturizable, .resizable],
                         backing: .buffered, defer: false)
        w.title = "aht Guide"
        w.isReleasedWhenClosed = false
        w.contentView = NSHostingView(rootView: GuideView().environmentObject(GUIDE))
        w.setFrameAutosaveName("aht-guide")
        w.center()
        GUIDE_WINDOW = w
    }
    GUIDE_WINDOW?.makeKeyAndOrderFront(nil)
    NSApp.activate(ignoringOtherApps: true)
}

struct GuideView: View {
    @EnvironmentObject var g: GuideModel
    let topics = guideTopics()

    var body: some View {
        let current = topics.first { $0.title == g.topic } ?? topics[0]
        HSplitView {
            List(selection: $g.topic) {
                ForEach(topics, id: \.title) { t in
                    Text(t.title).tag(Optional(t.title))
                }
            }
            .frame(minWidth: 210, idealWidth: 250, maxWidth: 320)
            ScrollView {
                MarkdownView(text: current.text).padding(20)
            }
            .id(current.title)                  // a new topic starts at its top
            .frame(minWidth: 420)
        }
    }
}

/// The "?" next to a feature: opens the guide at that feature's section.
struct HelpButton: View {
    let topic: String
    init(_ topic: String) { self.topic = topic }

    var body: some View {
        Button { showGuideWindow(topic) } label: {
            Image(systemName: "questionmark.circle")
        }
        .buttonStyle(.borderless)
        .help("How this works (guide: \(topic))")
    }
}

func headed(_ title: String, _ topic: String) -> some View {
    HStack(spacing: 6) {
        Text(title).font(.headline)
        HelpButton(topic)
    }
}

struct SecretsSheet: View {
    @EnvironmentObject var m: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            headed(m.secretsFor.map { "Secrets in \(($0 as NSString).lastPathComponent)'s history" }
                   ?? "Secrets in every agent history", "Secrets check")
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
                    TableColumn("") { f in
                        Button("Remove…") { m.removeSecret(f) }.controlSize(.small)
                            .disabled(m.working != nil)
                    }
                    .width(80)
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

struct TidySheet: View {
    @EnvironmentObject var m: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            headed("Tidy up", "Tidy up")
            Text("Folders aht tracked that are gone, and histories no tracked folder owns. "
                 + "Nothing here deletes history on its own: reconnect it, let aht forget "
                 + "the folder, or move a history without a folder to the Trash (Remove…).")
                .foregroundColor(.secondary).fixedSize(horizontal: false, vertical: true)
            if let r = m.tidyReading {
                HStack {
                    Button("← Back") { m.tidyReading = nil }
                    Text(r.title).font(.headline)
                    Spacer()
                    Button("Copy") {
                        NSPasteboard.general.clearContents()
                        NSPasteboard.general.setString(r.text, forType: .string)
                    }
                    if r.item.kind == "orphan" && !r.item.link {
                        Button("Remove…") { m.removeHistory(r.item); m.tidyReading = nil }
                    }
                }
                ScrollView {
                    MarkdownView(text: r.text, skipTitle: true).padding(.trailing, 12)
                }
            } else if let items = m.tidy {
                if items.isEmpty { Text("Everything is in order.").padding(.vertical, 20) }
                ScrollView {
                    VStack(alignment: .leading, spacing: 10) {
                        ForEach(items) { t in TidyRow(t: t) }
                    }
                }
            } else {
                HStack { ProgressView().controlSize(.small); Text("Looking…") }.padding(.vertical, 20)
                Spacer()
            }
            HStack {
                Spacer()
                Button("Close") { m.showTidy = false; m.tidyReading = nil; m.refresh() }
                    .keyboardShortcut(.cancelAction)
            }
        }
        .padding(20).frame(width: 820, height: 620)
    }
}

struct TidyRow: View {
    @EnvironmentObject var m: AppModel
    let t: TidyItem

    var facts: String {
        var bits = ["\(t.sessions) session\(t.sessions == 1 ? "" : "s")"]
        if t.bytes > 0 { bits.append(byteText(NSNumber(value: t.bytes))) }
        if let l = t.last, !ago(l).isEmpty { bits.append("last used " + ago(l)) }
        if let title = t.title { bits.append("“\(title)”") }
        return bits.joined(separator: " · ")
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline) {
                Text(t.kind == "missing" ? "Folder gone" : t.kind == "orphan"
                     ? "History without a folder" : "Listed twice")
                    .font(.caption).foregroundColor(.secondary).frame(width: 150, alignment: .leading)
                Text((t.path as NSString).lastPathComponent).fontWeight(.semibold)
                Text(t.detail).foregroundColor(.secondary)
                Spacer()
                if t.kind != "double" {
                    Button("Choose Folder…") { m.tidyConnect(t, to: nil) }.controlSize(.small)
                }
                if t.kind != "orphan" {
                    Button("Forget") { m.tidyForget(t) }.controlSize(.small)
                } else if !t.link {             // a link is left alone (`tidy --json`)
                    Button("Remove…") { m.removeHistory(t) }.controlSize(.small)
                        .help("Move this history to the Trash")
                }
            }
            Text(t.path).font(.caption).foregroundColor(.secondary).lineLimit(1)
                .truncationMode(.middle).padding(.leading, 158)
            if t.kind != "double" && (t.sessions > 0 || t.title != nil) {
                HStack(spacing: 8) {
                    Text(facts).font(.caption).foregroundColor(.secondary).lineLimit(1)
                    Spacer()
                    Button("Read…") { m.readHistory(t) }.controlSize(.small)
                        .help("The conversations of this history, as text")
                    if let h = t.history {
                        Button("Show in Finder") {
                            NSWorkspace.shared.selectFile(h, inFileViewerRootedAtPath: "")
                        }
                        .controlSize(.small)
                    }
                }
                .padding(.leading, 158)
            }
            ForEach(Array(t.candidates.enumerated()), id: \.offset) { _, c in
                HStack {
                    Text("maybe now:").font(.caption).foregroundColor(.secondary)
                    Text(c.path).font(.caption).lineLimit(1).truncationMode(.middle)
                    Text("(\(c.why))").font(.caption).foregroundColor(.secondary)
                    Spacer()
                    Button("Reconnect") { m.tidyConnect(t, to: c.path) }.controlSize(.small)
                }
                .padding(.leading, 158)
            }
        }
        .padding(8)
        .background(Color.primary.opacity(0.03))
        .cornerRadius(6)
        .disabled(m.working != nil)
    }
}

struct ReportSheet: View {
    @EnvironmentObject var m: AppModel

    var text: String {
        ([m.reportTotal] + m.report.map {
            String(format: "%6.1f h  %3d sessions  %@  (%@)", $0.hours, $0.sessions, $0.name, $0.agents)
        }).joined(separator: "\n")
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                headed("Report", "Reports and an AI-use statement")
                Spacer()
                Picker("", selection: $m.reportPeriod) {
                    Text("This week").tag("week")
                    Text("This month").tag("month")
                    Text("Last 30 days").tag("30")
                    Text("Everything").tag("all")
                }
                .labelsHidden().fixedSize()
                Picker("", selection: $m.reportBy) {
                    Text("by project").tag("project")
                    Text("by agent").tag("agent")
                    Text("by area").tag("area")
                }
                .labelsHidden().fixedSize()
            }
            Text(m.reportTotal).foregroundColor(.secondary)
            Table(m.report) {
                TableColumn(m.reportBy == "agent" ? "Agent" : m.reportBy == "area" ? "Area" : "Project") { r in
                    Text(r.name)
                }
                TableColumn("Hours") { r in Text(String(format: "%.1f", r.hours)).monospacedDigit() }
                    .width(70)
                TableColumn("Sessions") { r in Text("\(r.sessions)").monospacedDigit() }.width(70)
                TableColumn("Agents") { r in Text(r.agents).foregroundColor(.secondary) }
            }
            Text("Session time counts the stretches in which a session was active; pauses over "
                 + "15 minutes are left out, and sessions that ran side by side add up. Areas "
                 + "come from report_areas in the config file.")
                .font(.caption).foregroundColor(.secondary).fixedSize(horizontal: false, vertical: true)
            HStack {
                Button("Copy as Text") {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(text, forType: .string)
                }
                Spacer()
                Button("Close") { m.showReport = false }.keyboardShortcut(.cancelAction)
            }
        }
        .padding(20).frame(width: 720, height: 520)
        .onChange(of: m.reportPeriod) { _ in m.loadReport() }
        .onChange(of: m.reportBy) { _ in m.loadReport() }
    }
}

struct ChangesSheet: View {
    @EnvironmentObject var m: AppModel
    let c: ChangesView
    @State private var pick: UUID?

    var body: some View {
        let shown = c.files.filter { $0.inside }
        let current = shown.first { $0.id == pick } ?? shown.first { $0.state != "unchanged" }
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                headed("What changed: \(c.project.name)", "What did a session change")
                Spacer()
                if c.sessions.count > 1 {
                    Picker("Session", selection: Binding(get: { c.session ?? "" },
                                                         set: { m.openChanges(c.project, session: $0) })) {
                        ForEach(c.sessions, id: \.self) { Text(String($0.prefix(8))).tag($0) }
                    }
                    .frame(width: 180)
                }
            }
            Text("Session “\(c.title)”: every file it edited, from before it touched it to now. "
                 + "Files outside the project are left out.")
                .foregroundColor(.secondary).fixedSize(horizontal: false, vertical: true)
            HSplitView {
                List(shown, selection: $pick) { f in
                    HStack {
                        Text(f.state == "changed" ? "M" : f.state == "added" ? "A"
                             : f.state == "removed" ? "D" : "·")
                            .font(.system(.body, design: .monospaced)).foregroundColor(.secondary)
                        Text(f.name).lineLimit(1).truncationMode(.head)
                        Spacer()
                        if f.added + f.removed > 0 {
                            Text("+\(f.added) −\(f.removed)").font(.caption).foregroundColor(.secondary)
                        }
                    }
                    .tag(f.id)
                }
                .frame(minWidth: 240, idealWidth: 280)
                ScrollView([.vertical, .horizontal]) {
                    VStack(alignment: .leading, spacing: 0) {
                        ForEach(Array((current?.diff ?? "").components(separatedBy: "\n").enumerated()),
                                id: \.offset) { _, line in
                            Text(line.isEmpty ? " " : line)
                                .font(.system(.caption, design: .monospaced))
                                .foregroundColor(line.hasPrefix("+") ? .green
                                                 : line.hasPrefix("-") ? .red
                                                 : line.hasPrefix("@@") ? .blue : .primary)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                    .textSelection(.enabled)
                    .padding(8)
                }
                .frame(minWidth: 360)
            }
            HStack {
                if let f = current, ["changed", "added"].contains(f.state) {
                    Button("Put Back “\(f.name)”…") { m.putBack(c, f) }
                }
                Spacer()
                Button("Close") { m.changes = nil }.keyboardShortcut(.cancelAction)
            }
        }
        .padding(20).frame(width: 900, height: 600)
    }
}

// ---- undo a session, loose ends, a second opinion, the night shift --------------

/// Changed files on the left, the selected one's line diff on the right.
struct FileDiffPane: View {
    let files: [ChangedFile]
    let empty: String
    @State private var pick: UUID?

    var body: some View {
        let current = files.first { $0.id == pick } ?? files.first
        if files.isEmpty {
            VStack { Spacer(); Text(empty).foregroundColor(.secondary); Spacer() }
                .frame(maxWidth: .infinity)
        } else {
            HSplitView {
                List(files, selection: $pick) { f in
                    HStack {
                        Text(f.state == "changed" ? "M" : f.state == "added" ? "A" : "D")
                            .font(.system(.body, design: .monospaced)).foregroundColor(.secondary)
                        Text(f.name).lineLimit(1).truncationMode(.head)
                        Spacer()
                        if f.added + f.removed > 0 {
                            Text("+\(f.added) −\(f.removed)").font(.caption).foregroundColor(.secondary)
                        }
                    }
                    .tag(f.id)
                }
                .frame(minWidth: 220, idealWidth: 260)
                DiffText(text: current?.diff ?? "")
                    .frame(minWidth: 300)
            }
        }
    }
}

struct DiffText: View {
    let text: String

    var body: some View {
        ScrollView([.vertical, .horizontal]) {
            VStack(alignment: .leading, spacing: 0) {
                ForEach(Array(text.components(separatedBy: "\n").enumerated()), id: \.offset) { _, line in
                    Text(line.isEmpty ? " " : line)
                        .font(.system(.caption, design: .monospaced))
                        .foregroundColor(line.hasPrefix("+") ? .green
                                         : line.hasPrefix("-") ? .red
                                         : line.hasPrefix("@@") || line.hasPrefix("==") ? .blue
                                         : .primary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            .textSelection(.enabled)
            .padding(8)
        }
    }
}

struct UndoSheet: View {
    @EnvironmentObject var m: AppModel
    let u: UndoView

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                headed("Undo a session: \(u.project.name)", "Undo a whole session")
                Spacer()
                if !u.checkpoints.isEmpty {
                    Picker("Back to", selection: Binding(get: { u.chosen ?? "" },
                                                         set: { m.openUndo(u.project, checkpoint: $0) })) {
                        ForEach(u.checkpoints) { Text($0.label).tag($0.id) }
                    }
                    .frame(width: 420)
                }
            }
            Text(u.checkpoints.isEmpty
                 ? "aht has no copy of this folder yet. It makes one each time a Claude Code "
                   + "session starts here, and before another agent takes over."
                 : "How the folder differs from its copy at the start of that session. Putting "
                   + "it back restores every file listed; what is there now is set aside in "
                   + "~/.aht/undo. Rebuilt folders (node_modules, .venv …) and .git are left alone.")
                .foregroundColor(.secondary).fixedSize(horizontal: false, vertical: true)
            FileDiffPane(files: u.files, empty: u.checkpoints.isEmpty ? "" : "Nothing changed since then.")
            ForEach(u.checkpoints.isEmpty ? [] : u.blockers + u.warnings, id: \.self) {
                Text("⚠ " + $0).font(.callout).foregroundColor(.orange)
                    .fixedSize(horizontal: false, vertical: true)
            }
            HStack {
                Spacer()
                Button("Close") { m.undo = nil }.keyboardShortcut(.cancelAction)
                Button("Put Everything Back…") { m.applyUndo(u) }
                    .disabled(u.files.isEmpty || !u.blockers.isEmpty || u.chosen == nil)
            }
        }
        .padding(20).frame(width: 900, height: 600)
    }
}

/// A project's sessions, the latest work first, each branch indented under
/// the session it came from; any of them can be continued.
struct SessionListSheet: View {
    @EnvironmentObject var m: AppModel
    let v: SessionListView
    @State private var filter = ""

    func stamp(_ t: Double?) -> String {
        guard let t = t, t > 0 else { return "—" }
        let f = DateFormatter()
        f.dateStyle = .medium
        f.timeStyle = .short
        return f.string(from: Date(timeIntervalSince1970: t))
    }

    var shown: [SessionItem] {
        let q = filter.trimmingCharacters(in: .whitespaces).lowercased()
        return q.isEmpty ? v.items
            : v.items.filter { $0.title.lowercased().contains(q) || $0.session.hasPrefix(q) }
    }

    func detail(_ s: SessionItem) -> String {
        var bits: [String] = []
        if s.agent != "claude" { bits.append(AGENT_LABEL[s.agent] ?? s.agent) }
        if let b = s.branched {
            bits.append("branched " + stamp(b))
        } else if s.started != nil {
            bits.append("started " + stamp(s.started))
        }
        bits.append("last active " + stamp(s.updated))
        if s.parentGone { bits.append("branched from a session that is gone") }
        return bits.joined(separator: " · ")
    }

    func row(_ s: SessionItem) -> some View {
        HStack(alignment: .center, spacing: 8) {
            if s.depth > 0 {
                Spacer().frame(width: CGFloat(s.depth - 1) * 24 + 4)
                Image(systemName: "arrow.triangle.branch").foregroundColor(.secondary)
                    .frame(width: 16).help("A branch (/branch in Claude Code)")
            }
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text(s.title.isEmpty ? "(no title)" : s.title).fontWeight(.medium)
                        .lineLimit(1).truncationMode(.tail)
                    if s.open {
                        Text("open now").font(.caption).foregroundColor(.green)
                    }
                }
                Text(detail(s)).font(.caption).foregroundColor(.secondary).lineLimit(1)
            }
            Spacer(minLength: 8)
            Text(String(s.session.prefix(8))).font(.caption.monospaced())
                .foregroundColor(.secondary).textSelection(.enabled)
                .help("Session id: \(s.session)")
            if s.open, let pid = s.pid {
                Button("Go to Tab") { m.goto(pid: pid) }
                    .help("It is open now: bring its tab to the front")
            } else {
                Button("Continue") {
                    m.resumeSession(v.project.path, agent: s.agent, session: s.session)
                }
                .disabled(v.project.away != nil || v.project.handing != nil)
                .help("Continue this session in a new terminal window")
            }
        }
        .padding(.vertical, 6)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                headed("Sessions: \(v.project.name)", "A project's sessions")
                Spacer()
                if v.items.count > 6 {
                    TextField("Filter by title", text: $filter)
                        .textFieldStyle(.roundedBorder).frame(width: 200)
                }
            }
            Text("Every session in this folder, the latest work first. A branch (/branch in "
                 + "Claude Code) sits under the session it came from, with the time it "
                 + "branched. Continue opens a session in a new terminal window.")
                .foregroundColor(.secondary).fixedSize(horizontal: false, vertical: true)
            if let host = v.project.away {
                Text("This project is handed over to \(host): take it back before you "
                     + "continue a session here.")
                    .font(.callout).foregroundColor(.orange)
            } else if let h = v.project.handing {
                Text("The handover to \(h.machine) is unfinished: check it, or release the "
                     + "project, before you continue a session here.")
                    .font(.callout).foregroundColor(.orange)
            }
            Divider()
            if v.items.isEmpty {
                Text("No sessions in this folder yet.").foregroundColor(.secondary)
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(shown) { s in
                        row(s)
                        Divider()
                    }
                }
                .padding(.trailing, 12)
            }
            HStack {
                Text("\(v.items.count) session\(v.items.count == 1 ? "" : "s")"
                     + (v.items.contains { $0.branched != nil }
                        ? ", \(v.items.filter { $0.branched != nil }.count) of them branches" : ""))
                    .font(.caption).foregroundColor(.secondary)
                Spacer()
                Button("Close") { m.sessionList = nil }.keyboardShortcut(.cancelAction)
            }
        }
        .padding(20).frame(width: 780, height: 560)
    }
}

struct LooseEndsSheet: View {
    @EnvironmentObject var m: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            headed("Loose ends", "Loose ends")
            Text("Projects of the last 30 days with something left open: work not committed, "
                 + "open to-do items, or a last session that asked you something or offered "
                 + "a next step.")
                .foregroundColor(.secondary).fixedSize(horizontal: false, vertical: true)
            if let rows = m.looseEnds {
                if rows.isEmpty {
                    Spacer()
                    Text("Nothing left open.").foregroundColor(.secondary).frame(maxWidth: .infinity)
                    Spacer()
                } else {
                    List(rows) { r in
                        HStack(alignment: .top, spacing: 12) {
                            VStack(alignment: .leading, spacing: 3) {
                                HStack(spacing: 8) {
                                    Text((r.project as NSString).lastPathComponent).bold()
                                    Text(ago(NSNumber(value: r.last))).font(.caption)
                                        .foregroundColor(.secondary)
                                    if r.open {
                                        Text("session open").font(.caption).foregroundColor(.orange)
                                    }
                                }
                                ForEach(Array(r.items.enumerated()), id: \.offset) { _, it in
                                    Text((it.kind == "question" ? "? " : it.kind == "offer" ? "→ " : "• ")
                                         + it.text)
                                        .font(.callout).fixedSize(horizontal: false, vertical: true)
                                    ForEach(it.sub, id: \.self) {
                                        Text("    – " + $0).font(.caption).foregroundColor(.secondary)
                                    }
                                }
                            }
                            Spacer()
                            VStack(alignment: .trailing, spacing: 6) {
                                Button("Continue") {
                                    m.resumeSession(r.project, agent: r.agent, session: r.session)
                                }
                                .disabled(r.open || r.session.isEmpty)
                                Button("Show") {
                                    m.showLooseEnds = false
                                    m.tab = .projects
                                    m.selection = r.project
                                }
                            }
                            .controlSize(.small)
                        }
                        .padding(.vertical, 4)
                    }
                }
            } else {
                Spacer()
                ProgressView("Looking through the projects…").frame(maxWidth: .infinity)
                Spacer()
            }
            HStack {
                Spacer()
                Button("Close") { m.showLooseEnds = false }.keyboardShortcut(.cancelAction)
            }
        }
        .padding(20).frame(width: 760, height: 540)
    }
}

struct OpinionSheet: View {
    @EnvironmentObject var m: AppModel
    let v: OpinionView
    @State private var task = ""
    let tick = Timer.publish(every: 3, on: .main, in: .common).autoconnect()

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                headed("Second opinion: \(v.project.name)", "A second opinion")
                Spacer()
                if v.runs.count > 1 {
                    Picker("Run", selection: Binding(get: { v.current ?? "" },
                                                     set: { m.loadOpinion(v.project, run: $0) })) {
                        ForEach(v.runs, id: \.id) { Text($0.label).tag($0.id) }
                    }
                    .frame(width: 360)
                }
            }
            HStack(alignment: .top) {
                TextField("A task for both, e.g. make the parser accept empty lines",
                          text: $task, axis: .vertical)
                    .lineLimit(2...4).textFieldStyle(.roundedBorder)
                Button("Start") {
                    m.startOpinion(v.project, task: task)
                    task = ""
                }
                .disabled(task.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
            Text("Claude Code and Kimi Code each get a copy of the project and the same task; "
                 + "the project itself stays untouched until you pick one. This uses both "
                 + "agents' tokens. Claude may edit files but not run commands; Kimi's "
                 + "non-interactive mode may also run commands it decides on.")
                .font(.caption).foregroundColor(.secondary).fixedSize(horizontal: false, vertical: true)
            if v.current != nil {
                Text("Task: " + v.task).font(.callout).lineLimit(2)
                HStack(alignment: .top, spacing: 12) {
                    ForEach(v.results) { r in column(r) }
                }
                if !v.changedMeanwhile.isEmpty {
                    Text("⚠ Changed in the project since the copies were made: "
                         + v.changedMeanwhile.prefix(6).joined(separator: ", "))
                        .font(.callout).foregroundColor(.orange)
                }
            } else {
                Spacer()
            }
            HStack {
                if v.current != nil {
                    Button("Remove the Copies…") { m.discardOpinion(v) }
                }
                Spacer()
                Button("Close") { m.opinion = nil }.keyboardShortcut(.cancelAction)
            }
        }
        .padding(20).frame(width: 960, height: 660)
        .onReceive(tick) { _ in
            if !v.finished, let r = v.current { m.loadOpinion(v.project, run: r) }
        }
    }

    func column(_ r: OpinionResult) -> some View {
        let label = AGENT_LABEL[r.id] ?? r.id
        var state = r.state == "done" ? "done" : r.state == "working" || r.state == "starting"
            ? "working…" : r.state
        if let s = r.seconds { state += " · \(s / 60) min \(s % 60) s" }
        if let c = r.cost { state += String(format: " · $%.2f", c) }
        let diff = r.files.map { "== \($0.name) (\($0.state)) ==\n" + $0.diff }.joined(separator: "\n")
        return VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(label).bold()
                Text(state).font(.caption).foregroundColor(.secondary)
                Spacer()
                if v.taken == r.id {
                    Text("taken").font(.caption).foregroundColor(.green)
                }
            }
            ScrollView {
                Text(r.answer.isEmpty ? (state == "working…" ? "working on it…" : "–") : r.answer)
                    .font(.callout).textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .frame(height: 120)
            Text(r.files.isEmpty ? "No files changed." : "\(r.files.count) file(s) changed")
                .font(.caption).foregroundColor(.secondary)
            DiffText(text: diff).background(Color(NSColor.textBackgroundColor))
            Button("Use \(label)'s Changes…") { m.takeOpinion(v, from: r.id) }
                .disabled(r.state != "done" || r.files.isEmpty || v.taken != nil)
        }
        .frame(maxWidth: .infinity)
    }
}

struct NightShiftSheet: View {
    @EnvironmentObject var m: AppModel
    let v: NightShiftView
    @State private var task = ""
    @State private var startNow = false
    @State private var start = NightShiftSheet.at(22)
    @State private var back = NightShiftSheet.at(7)

    static func at(_ hour: Int) -> Date {
        Calendar.current.date(bySettingHour: hour, minute: 0, second: 0, of: Date()) ?? Date()
    }

    static func when(_ t: Double) -> String {
        let f = DateFormatter()
        f.dateFormat = "EEE HH:mm"
        return f.string(from: Date(timeIntervalSince1970: t))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            headed("Night shift: \(v.project.name)", "The night shift")
            Text("At the start time aht hands the project over to \(m.machine ?? "your other machine") "
                 + "with the task below; at the end time it takes it back as soon as the session "
                 + "there is done. The agent over there uses your tokens. This Mac has to be "
                 + "awake at both times.")
                .foregroundColor(.secondary).fixedSize(horizontal: false, vertical: true)
            TextField("The task, e.g. run the benchmarks and write the results into RESULTS.md",
                      text: $task, axis: .vertical)
                .lineLimit(3...6).textFieldStyle(.roundedBorder)
            HStack(spacing: 16) {
                Toggle("Start now", isOn: $startNow)
                DatePicker("Start", selection: $start, displayedComponents: .hourAndMinute)
                    .disabled(startNow).fixedSize()
                DatePicker("Take back", selection: $back, displayedComponents: .hourAndMinute)
                    .fixedSize()
                Spacer()
                Button("Plan It") {
                    m.planNight(v.project, task: task, start: startNow ? nil : start, back: back)
                    task = ""
                }
                .disabled(task.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                          || m.machine == nil)
            }
            Divider()
            Text("Planned and past").font(.subheadline.bold())
            if v.jobs.isEmpty {
                Text("None yet.").foregroundColor(.secondary)
                Spacer()
            } else {
                List(v.jobs) { j in
                    HStack(alignment: .top) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("\(j.state) · \(Self.when(j.startAt)) → \(Self.when(j.backAt)) on \(j.remote)")
                                .font(.callout)
                            Text(j.task).font(.caption).foregroundColor(.secondary).lineLimit(2)
                            if let l = j.log.last {
                                Text(l).font(.caption).foregroundColor(.secondary)
                            }
                        }
                        Spacer()
                        if ["planned", "started"].contains(j.state) {
                            Button("Cancel") { m.cancelNight(v.project, j) }.controlSize(.small)
                        }
                    }
                }
            }
            HStack {
                Spacer()
                Button("Close") { m.night = nil }.keyboardShortcut(.cancelAction)
            }
        }
        .padding(20).frame(width: 660, height: 540)
    }
}

struct WorkspaceSheet: View {
    @EnvironmentObject var m: AppModel

    func title(_ e: [String: Any]) -> String {
        let t = e["title"] as? String ?? ""
        return t.isEmpty ? "(no title)" : t
    }

    func openLine(_ e: [String: Any]) -> String {
        let what = (e["name"] as? String) ?? (e["agent"] as? String) ?? ""
        let folder = ((e["cwd"] as? String) ?? "") as NSString
        return "↻ " + title(e) + "  " + what + "  " + folder.lastPathComponent
    }

    func skipLine(_ e: [String: Any]) -> String {
        return "– " + title(e) + ": " + (e["why"] as? String ?? "")
    }

    func when(_ any: Any?) -> String {
        let f = DateFormatter()
        f.dateStyle = .medium
        f.timeStyle = .short
        return f.string(from: Date(timeIntervalSince1970: (any as? NSNumber)?.doubleValue ?? 0))
    }

    func savingRule() -> String {
        let every = m.config["workspace_save_minutes"] as? Int ?? 10
        let keep = m.config["workspace_keep"] as? Int ?? 40
        return (every > 0 ? "Saved every \(every) minutes while iTerm2 is open, and" : "Saved")
            + " when a session gets a prompt; a layout that did not change is not saved "
            + "again. The last \(keep) are kept (Settings → Restore my workspace)."
    }

    func row(_ w: [String: Any]) -> some View {
        let id = w["id"] as? String ?? ""
        let picked = m.workspacePick == id
        let titles = (w["titles"] as? [String]) ?? []
        return Button(action: { m.pickWorkspace(id) }) {
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 4) {
                    Text("last seen " + when(w["seen"]))
                    if id == m.workspaceDefault {
                        Text("before iTerm2 started").font(.caption2)
                            .padding(.horizontal, 4)
                            .background(Capsule().fill(Color.accentColor.opacity(0.18)))
                    }
                }
                Text("\(w["tabs"] as? Int ?? 0) tabs, \(w["sessions"] as? Int ?? 0) sessions")
                    .font(.caption).foregroundColor(.secondary)
                if !titles.isEmpty {
                    Text(titles.prefix(6).joined(separator: ", ")).font(.caption)
                        .foregroundColor(.secondary).lineLimit(1)
                }
            }
            .padding(.vertical, 5).padding(.horizontal, 8)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 6)
                .fill(picked ? Color.accentColor.opacity(0.22) : Color.clear))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    func dot(_ e: [String: Any]) -> some View {
        let hex = (e["color"] as? String ?? "").dropFirst()
        let v = Int(hex, radix: 16) ?? -1
        return Circle()
            .fill(v < 0 || hex.count != 6 ? Color.clear
                  : Color(red: Double((v >> 16) & 255) / 255, green: Double((v >> 8) & 255) / 255,
                          blue: Double(v & 255) / 255))
            .frame(width: 9, height: 9)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            headed("Restore the workspace", "Restore my workspace")
            Text("aht keeps your iTerm2 windows and tabs, their titles, colours and the sessions "
                 + "in them, while you work. Opening one again resumes each session where it was, "
                 + "in a tab with its title and colour, and starts iTerm2 if it is closed. "
                 + "Sessions and titled tabs that are open now are skipped.")
                .foregroundColor(.secondary).fixedSize(horizontal: false, vertical: true)
            if let ws = m.workspaces {
                if ws.isEmpty {
                    Text("No workspace saved yet. aht saves one while you work with Claude Code in "
                         + "iTerm2, or now with Save Now.").foregroundColor(.secondary)
                } else {
                    HSplitView {
                        ScrollView {
                            VStack(alignment: .leading, spacing: 2) {
                                ForEach(ws.indices, id: \.self) { i in row(ws[i]) }
                            }
                            .padding(4)
                        }
                        .frame(minWidth: 230, idealWidth: 260)
                        ScrollView {
                            VStack(alignment: .leading, spacing: 4) {
                                let plan = (m.workspacePlan["plan"] as? [String: Any]) ?? [:]
                                let wins = (plan["windows"] as? [[[[String: Any]]]]) ?? []
                                ForEach(Array(wins.enumerated()), id: \.offset) { wi, win in
                                    Text("Window \(wi + 1)").font(.subheadline.bold()).padding(.top, 4)
                                    ForEach(Array(win.joined().enumerated()), id: \.offset) { _, e in
                                        HStack(spacing: 6) {
                                            dot(e)
                                            Text(openLine(e)).lineLimit(1)
                                        }
                                    }
                                }
                                let skipped = (plan["skipped"] as? [[String: Any]]) ?? []
                                if !skipped.isEmpty {
                                    Text("Skipped").font(.subheadline.bold()).padding(.top, 8)
                                    ForEach(Array(skipped.enumerated()), id: \.offset) { _, e in
                                        Text(skipLine(e))
                                            .font(.caption).foregroundColor(.secondary).lineLimit(1)
                                    }
                                }
                                if let why = (m.workspacePlan["blockers"] as? [String])?.first {
                                    Text(why).foregroundColor(.orange).padding(.top, 8)
                                }
                            }
                            .padding(8)
                            .frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                }
            } else {
                ProgressView().frame(maxWidth: .infinity)
            }
            Text(savingRule()).font(.caption).foregroundColor(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            HStack {
                Button("Save Now") { m.saveWorkspaceNow() }.disabled(m.working != nil)
                if let w = m.working {
                    ProgressView().controlSize(.small)
                    Text(w).foregroundColor(.secondary)
                }
                Spacer()
                Button("Close") { m.showWorkspace = false }.keyboardShortcut(.cancelAction)
                Button("Open Them") { m.restoreWorkspace() }
                    .disabled(m.working != nil
                              || ((m.workspacePlan["plan"] as? [String: Any])?["opens"] as? Int ?? 0) == 0)
            }
        }
        .padding(20).frame(width: 820, height: 560)
    }
}

// ---- the shortcut that opens the search from anywhere ----------------------------

var HOTKEY_ACTION: (() -> Void)?
var HOTKEY_REF: EventHotKeyRef?

let KEY_CODES: [String: Int] = [
    "a": kVK_ANSI_A, "b": kVK_ANSI_B, "c": kVK_ANSI_C, "d": kVK_ANSI_D, "e": kVK_ANSI_E,
    "f": kVK_ANSI_F, "g": kVK_ANSI_G, "h": kVK_ANSI_H, "i": kVK_ANSI_I, "j": kVK_ANSI_J,
    "k": kVK_ANSI_K, "l": kVK_ANSI_L, "m": kVK_ANSI_M, "n": kVK_ANSI_N, "o": kVK_ANSI_O,
    "p": kVK_ANSI_P, "q": kVK_ANSI_Q, "r": kVK_ANSI_R, "s": kVK_ANSI_S, "t": kVK_ANSI_T,
    "u": kVK_ANSI_U, "v": kVK_ANSI_V, "w": kVK_ANSI_W, "x": kVK_ANSI_X, "y": kVK_ANSI_Y,
    "z": kVK_ANSI_Z, "space": kVK_Space, "/": kVK_ANSI_Slash, ".": kVK_ANSI_Period,
]

func hotkeyLabel(_ spec: String) -> String {
    let p = spec.lowercased().split(separator: "+").map(String.init)
    var out = ""
    if p.contains("ctrl") || p.contains("control") { out += "⌃" }
    if p.contains("opt") || p.contains("alt") || p.contains("option") { out += "⌥" }
    if p.contains("shift") { out += "⇧" }
    if p.contains("cmd") || p.contains("command") { out += "⌘" }
    return out + (p.last.map { $0 == "space" ? "Space" : $0.uppercased() } ?? "")
}

func registerHotKey(_ spec: String, _ action: @escaping () -> Void) {
    if let r = HOTKEY_REF { UnregisterEventHotKey(r); HOTKEY_REF = nil }
    let p = spec.lowercased().split(separator: "+").map(String.init)
    guard let key = p.last, let code = KEY_CODES[key] else { return }
    var mods = 0
    if p.contains("ctrl") || p.contains("control") { mods |= controlKey }
    if p.contains("opt") || p.contains("alt") || p.contains("option") { mods |= optionKey }
    if p.contains("shift") { mods |= shiftKey }
    if p.contains("cmd") || p.contains("command") { mods |= cmdKey }
    guard mods != 0 else { return }                  // a bare key would steal typing
    HOTKEY_ACTION = action
    if HOTKEY_ACTION != nil && HOTKEY_REF == nil {
        var spec = EventTypeSpec(eventClass: OSType(kEventClassKeyboard),
                                 eventKind: UInt32(kEventHotKeyPressed))
        InstallEventHandler(GetApplicationEventTarget(), { _, _, _ in
            DispatchQueue.main.async { HOTKEY_ACTION?() }
            return noErr
        }, 1, &spec, nil, nil)
    }
    let id = EventHotKeyID(signature: OSType(0x41485431), id: 1)     // "AHT1"
    RegisterEventHotKey(UInt32(code), UInt32(mods), id, GetApplicationEventTarget(), 0, &HOTKEY_REF)
}

struct MachinesView: View {
    @EnvironmentObject var m: AppModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    Text("The machines a project can be handed over to, and kept in sync with.")
                        .foregroundColor(.secondary)
                    Spacer()
                    HelpButton("Hand a project over")
                }
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
                                Menu("Sync") {
                                    Button("Keep All Projects in Sync…") { m.syncAll(mc, on: true) }
                                    Button("Stop Keeping All in Sync…") { m.syncAll(mc, on: false) }
                                        .disabled(m.mirroredCount == 0)
                                }
                                .fixedSize()
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
                            Text(m.discovering ? "Looking on your network and in ~/.ssh/config…"
                                 : "Nothing found on your network or in ~/.ssh/config.")
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
                            Button("Look Again") { m.discover() }.disabled(m.discovering)
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
        .onAppear { m.discover() }
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
            headed("Add a machine", "Hand a project over")
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

/// Getting started: what lets aht do more on this Mac, each step with
/// whether it is done and, where the app can do it, a button or a switch.
struct SetupList: View {
    @EnvironmentObject var m: AppModel

    func mark(_ s: SetupStep) -> some View {
        let (icon, tint): (String, Color) = s.ok == true ? ("checkmark.circle.fill", .green)
            : s.ok == nil ? ("questionmark.circle", .secondary)
            : s.optional ? ("circle", .secondary) : ("exclamationmark.circle.fill", .orange)
        return Image(systemName: icon).foregroundColor(tint).frame(width: 18)
    }

    func toggle(_ key: String) -> some View {
        Toggle("", isOn: Binding(get: { m.flag(key, false) },
                                 set: { m.set(key, $0 ? "true" : "false") }))
            .labelsHidden().toggleStyle(.switch).controlSize(.small)
    }

    @ViewBuilder func action(_ s: SetupStep) -> some View {
        if s.id == "login" {
            Toggle("", isOn: Binding(get: { m.loginItem },
                                     set: { m.setLoginItem($0); m.refresh() }))
                .labelsHidden().toggleStyle(.switch).controlSize(.small)
        } else if s.id == "corner" {
            toggle("session_corner")
        } else if s.id == "chimes" {
            toggle("chimes")
        } else if s.ok == false && s.id == "iterm" {
            Button("Get iTerm2…") { m.getIterm() }
        } else if s.ok != true && s.id == "iterm_control" {      // asked, or iTerm2 closed
            if m.itermControl == "no" {
                Button("Open Privacy Settings…") { m.openAutomationSettings() }
            } else {
                Button("Ask Now") { m.askItermControl() }
            }
        } else if s.ok == false && ["iterm_api", "new_output_dot", "tab_colours"].contains(s.id) {
            Button("Open iTerm2") { m.openIterm() }
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            ForEach(m.setupSteps) { s in
                HStack(alignment: .top, spacing: 10) {
                    mark(s).padding(.top, 1)
                    VStack(alignment: .leading, spacing: 3) {
                        HStack(spacing: 6) {
                            Text(s.title).fontWeight(.semibold)
                            if s.optional {
                                Text("optional").font(.caption).foregroundColor(.secondary)
                            }
                        }
                        Text(s.text).foregroundColor(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                        // the app's own switches are right here, no need to say where
                        if !s.how.isEmpty && !["login", "corner", "chimes"].contains(s.id) {
                            Text(s.how).textSelection(.enabled)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                    Spacer(minLength: 8)
                    action(s)
                }
            }
        }
    }
}

struct GettingStartedSheet: View {
    @EnvironmentObject var m: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            headed("Getting started", "Getting started")
            Text("aht keeps your histories connected on its own. These steps let it do more "
                 + "with iTerm2, the Claude app and the menu bar; each says what it is for, and "
                 + "any of them can wait. The list stays in Settings → Getting started.")
                .foregroundColor(.secondary).fixedSize(horizontal: false, vertical: true)
            Divider()
            ScrollView { SetupList().padding(.trailing, 14).padding(.vertical, 4) }
            Divider()
            HStack {
                Button("Check Again") { m.refresh() }
                Spacer()
                Button("Done") { m.showGettingStarted = false }.keyboardShortcut(.defaultAction)
            }
        }
        .padding(20).frame(width: 660, height: 720)
    }
}

/// A new version: what's new in it, and the upgrade the way aht came.
struct UpdateSheet: View {
    @EnvironmentObject var m: AppModel

    var body: some View {
        let u = m.update
        let upgrade = u["upgrade"] as? String
        VStack(alignment: .leading, spacing: 10) {
            headed("aht \(u["latest"] as? String ?? "") is out", "New versions")
            Text("You have \(u["current"] as? String ?? "?"). What's new:")
                .foregroundColor(.secondary)
            Divider()
            ScrollView {
                MarkdownView(text: u["notes"] as? String ?? "").padding(.trailing, 12)
            }
            Divider()
            Text(upgrade.map { "Upgrade runs this in a Terminal window: " + $0 }
                 ?? "This copy of aht was downloaded: the button opens the download page.")
                .font(.caption).foregroundColor(.secondary)
                .fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
            HStack {
                Button("Later") { m.showUpdate = false }.keyboardShortcut(.cancelAction)
                Spacer()
                Button(upgrade == nil ? "Open the Download Page" : "Upgrade") { m.upgrade() }
                    .keyboardShortcut(.defaultAction)
            }
        }
        .padding(20).frame(width: 680, height: 560)
    }
}

/// Fetch Backups From…: each computer's folder of backups on the machine that
/// keeps them. Fetching adds what is missing here and replaces nothing.
struct FetchBackupsSheet: View {
    @EnvironmentObject var m: AppModel

    func row(_ f: OffsiteFolder, picked: Bool) -> some View {
        Button(action: { m.offsite?.pick = f.id }) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Image(systemName: picked ? "largecircle.fill.circle" : "circle")
                    .foregroundColor(picked ? .accentColor : .secondary)
                VStack(alignment: .leading, spacing: 2) {
                    HStack(spacing: 4) {
                        Text(f.name).fontWeight(.medium)
                        if f.mine {
                            Text("this Mac").font(.caption2)
                                .padding(.horizontal, 4)
                                .background(Capsule().fill(Color.accentColor.opacity(0.18)))
                        }
                    }
                    Text(f.detail).font(.caption).foregroundColor(.secondary)
                }
                Spacer(minLength: 0)
            }
            .padding(.vertical, 5).padding(.horizontal, 8)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 6)
                .fill(picked ? Color.accentColor.opacity(0.22) : Color.clear))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    var body: some View {
        let v = m.offsite ?? OffsiteView(machine: "")
        VStack(alignment: .leading, spacing: 10) {
            headed("Fetch backups from \(v.machine)", "Backups")
            Text("\(v.machine) keeps the backups of each computer that copies them there, in a "
                 + "folder of its own. Pick one: aht adds the backups that are missing here and "
                 + "never replaces one you have.")
                .foregroundColor(.secondary).fixedSize(horizontal: false, vertical: true)
            Divider()
            Group {
                if v.loading {
                    HStack(spacing: 8) {
                        ProgressView().controlSize(.small)
                        Text("Asking \(v.machine) which backups it keeps…").foregroundColor(.secondary)
                    }
                } else if let e = v.error {
                    Text(e).foregroundColor(.orange).textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                } else if v.folders.isEmpty {
                    Text("\(v.machine) keeps no backups yet.").foregroundColor(.secondary)
                } else {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 4) {
                            ForEach(v.folders) { f in row(f, picked: v.pick == f.id) }
                        }
                        .padding(.trailing, 12)
                    }
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            if v.fetching {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text("Fetching…").foregroundColor(.secondary)
                }
            } else if let r = v.result {
                Text(r).font(.callout).textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Divider()
            HStack {
                Button("Look Again") { m.openFetchBackups() }
                    .disabled(v.loading || v.fetching)
                Spacer()
                Button("Close") { m.offsite = nil }.keyboardShortcut(.cancelAction)
                Button("Fetch") { m.fetchBackups() }
                    .keyboardShortcut(.defaultAction)
                    .disabled(v.pick == nil || v.loading || v.fetching || v.error != nil)
            }
        }
        .padding(20).frame(width: 620, height: 460)
    }
}

// ---- the welcome window: setting aht up the first time -----------------------

struct RootChoice: Identifiable {
    var id: String { path }
    let path: String
    var chosen: Bool
    var projects: Int
    let exists: Bool
}

struct ProjectChoice: Identifiable {
    var id: String { path }
    let path: String
    let agents: [String]
    var chosen: Bool
    var forgotten = false                       // the person had aht forget it: not ticked
}

/// The projects `aht setup --json` found, ticked but for the ones aht was told
/// to forget: those come back only when the person ticks them.
func projectChoices(_ d: [String: Any]) -> [ProjectChoice] {
    ((d["projects"] as? [[String: Any]]) ?? []).map {
        let forgotten = $0["forgotten"] as? Bool ?? false
        return ProjectChoice(path: $0["path"] as? String ?? "",
                             agents: $0["agents"] as? [String] ?? [], chosen: !forgotten,
                             forgotten: forgotten)
    }
}

/// Whether the welcome's login switch is an answer to note (`aht autostart`,
/// as in aht's window): it changes how things are now, or the person moved
/// it. A first setup starts it on with nothing set up yet, so turning it off
/// there changes nothing on disk but is still a no to keep.
func loginAnswered(_ login: Bool, was: Bool, start: Bool) -> Bool {
    return login != was || login != start
}

/// What the welcome window asks, and the setting up itself (`aht setup`).
final class WelcomeModel: ObservableObject {
    enum Page { case hello, quick, folders, projects, rules, extras, updates, working, done }
    @Published var page = Page.hello
    @Published var loading = true
    @Published var roots: [RootChoice] = []
    @Published var projects: [ProjectChoice] = []
    @Published var elsewhere: [String] = []
    @Published var moves = "ask"
    @Published var copies = "ask"
    @Published var badges = true
    @Published var backups = true
    @Published var notifications = true
    @Published var login = true
    var loginStart = true                       // … as the switch stood when the window opened
    var asked = false                           // login: answered or set up before, so kept
    var answered = false                        // … answered (a switch, `aht autostart`)
    @Published var updateCheck = false
    @Published var working = ""
    @Published var failed: String?
    @Published var adopted = 0
    var finished = false                        // set up: closing the window declines nothing
    var install = false                         // the core is not set up on this Mac yet
    var quickly = true                          // Quick Setup, not each step (where Back goes)
    var close: () -> Void = {}

    var chosenRoots: [String] { roots.filter { $0.chosen }.map { $0.path } }

    /// The plan for the chosen folders (all suggested ones that hold projects,
    /// the first time).
    func load(first: Bool = false) {
        loading = true
        let args = ["setup", "--json"] + (first ? [] : ["--roots"] + chosenRoots)
        DispatchQueue.global(qos: .userInitiated).async {
            let d = ahtJSON(args) ?? [:]
            DispatchQueue.main.async {
                let rs = (d["roots"] as? [[String: Any]]) ?? []
                if first || self.roots.isEmpty {
                    self.roots = rs.map { r in
                        RootChoice(path: r["path"] as? String ?? "",
                                   chosen: (r["chosen"] as? Bool ?? false)
                                       || (r["projects"] as? Int ?? 0) > 0,
                                   projects: r["projects"] as? Int ?? 0,
                                   exists: r["exists"] as? Bool ?? true)
                    }.filter { $0.exists || $0.chosen }
                } else {
                    for r in rs {
                        if let i = self.roots.firstIndex(where: { $0.path == r["path"] as? String }) {
                            self.roots[i].projects = r["projects"] as? Int ?? 0
                        }
                    }
                }
                self.projects = projectChoices(d)
                self.elsewhere = (d["elsewhere"] as? [String]) ?? []
                if first {
                    let pol = (d["policies"] as? [String: String]) ?? [:]
                    self.moves = pol["moves"] ?? "ask"
                    self.copies = pol["copies"] ?? "ask"
                    let sw = (d["switches"] as? [String: Bool]) ?? [:]
                    self.badges = sw["badges"] ?? true
                    self.backups = sw["backups"] ?? true
                    self.notifications = sw["notifications"] ?? true
                    self.updateCheck = sw["update_check"] ?? false
                    if self.chosenRoots.count != rs.filter({ $0["chosen"] as? Bool ?? false }).count {
                        self.load()             // the projects in the suggested folders too
                        return
                    }
                }
                self.loading = false
            }
        }
    }

    func addRoot() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.message = "Watch this folder: aht notices moves, copies and new projects inside it"
        guard panel.runModal() == .OK, let u = panel.url else { return }
        let p = u.resolvingSymlinksInPath().path
        if let i = roots.firstIndex(where: { $0.path == p }) {
            roots[i].chosen = true
        } else {
            roots.append(RootChoice(path: p, chosen: true, projects: 0, exists: true))
        }
        load()
    }

    /// Install (the first time), then `aht setup --apply`, then start at login.
    func apply(_ app: AppModel) {
        page = .working
        failed = nil
        let on = { (b: Bool) in b ? "on" : "off" }
        let chosen = projects.filter { $0.chosen }.map { $0.path }
        let args = ["setup", "--apply", "--json", "--roots"] + chosenRoots + ["--adopt"] + chosen
            + ["--moves", moves, "--copies", copies, "--badges", on(badges),
               "--backups", on(backups), "--notifications", on(notifications),
               "--update-check", on(updateCheck)]
        let login = self.login, loginStart = self.loginStart
        DispatchQueue.global(qos: .userInitiated).async {
            if self.install, let res = BUNDLE_RES {
                DispatchQueue.main.async { self.working = "installing the watcher, the hooks and the aht command…" }
                let r = sh(PY, [res + "/install.py", "--src", res, "--keep-pid", String(getpid()),
                                "--tray-exe", Bundle.main.executablePath ?? ""], mergeStderr: true)
                guard r.ok else {
                    DispatchQueue.main.async { self.failed = r.out.isEmpty ? "See ~/.aht/aht.log" : r.out }
                    return
                }
            }
            DispatchQueue.main.async {
                self.working = chosen.isEmpty ? "saving your choices…"
                    : "taking on \(chosen.count) project\(chosen.count == 1 ? "" : "s")…"
            }
            let r = shWithStderr(PY, [ahtScript()] + args)
            let d = (try? JSONSerialization.jsonObject(with: Data(r.out.utf8))) as? [String: Any]
            DispatchQueue.main.async {
                guard r.ok, let d = d else {
                    // no JSON: what aht said instead, its error first
                    let said = [r.err, r.out].map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
                        .filter { !$0.isEmpty }.joined(separator: "\n\n")
                    self.failed = said.isEmpty ? "aht setup did not answer; see ~/.aht/aht.log" : said
                    return
                }
                self.adopted = ((d["adopted"] as? [String]) ?? []).count
                self.finished = true
                let was = FileManager.default.fileExists(atPath: TRAY_PLIST)
                app.setLoginItem(login, note: loginAnswered(login, was: was, start: loginStart))
                UserDefaults.standard.set(true, forKey: "welcomeShown")
                UserDefaults.standard.set(true, forKey: "gettingStartedShown")
                app.refresh { self.page = .done }
            }
        }
    }
}

struct WelcomeView: View {
    @EnvironmentObject var m: AppModel
    @ObservedObject var w: WelcomeModel

    func bullet(_ icon: String, _ text: String) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: icon).foregroundColor(.accentColor).frame(width: 20)
            Text(text).fixedSize(horizontal: false, vertical: true)
        }
    }

    func names(_ paths: [String], _ most: Int = 4) -> String {
        let n = paths.map { tilde($0) }
        return n.prefix(most).joined(separator: ", ") + (n.count > most ? " and \(n.count - most) more" : "")
    }

    func buttons(back: WelcomeModel.Page?, next: String, enabled: Bool = true,
                 _ go: @escaping () -> Void) -> some View {
        HStack {
            if let b = back { Button("Back") { w.page = b } }
            Spacer()
            Button(next, action: go).keyboardShortcut(.defaultAction).disabled(!enabled || w.loading)
        }
    }

    func policy(_ title: String, _ value: Binding<String>, _ options: [(String, String)]) -> some View {
        HStack {
            Text(title).frame(width: 190, alignment: .leading)
            Picker("", selection: value) { ForEach(options, id: \.0) { Text($0.1).tag($0.0) } }
                .labelsHidden().fixedSize()
            Spacer()
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            switch w.page {
            case .hello: hello
            case .quick: quick
            case .folders: folders
            case .projects: projectList
            case .rules: rules
            case .extras: extras
            case .updates: updates
            case .working: working
            case .done: done
            }
        }
        .padding(28).frame(width: 640, height: 580, alignment: .topLeading)
    }

    var hello: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 12) {
                Image(systemName: "infinity").font(.system(size: 30, weight: .semibold))
                Text("Welcome to aht").font(.largeTitle.weight(.semibold))
            }
            Text("aht keeps the history of your AI coding agents (Claude Code, Codex, Gemini "
                 + "CLI and others) connected to your project folders.")
                .fixedSize(horizontal: false, vertical: true)
            bullet("folder.badge.gearshape", "When you move, rename or copy a project folder, its "
                   + "agent history comes along.")
            bullet("magnifyingglass", "Find any session again: search, what changed, a journal, "
                   + "undo a whole session.")
            bullet("rectangle.stack", "See every open session and the ones that wait for you; "
                   + "hand a project to your other computer and back.")
            bullet("lock", "Everything stays on this Mac. aht has no account and sends nothing "
                   + "anywhere unless you set that up.")
            Spacer()
            if w.loading {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text("Looking for your projects…").foregroundColor(.secondary)
                }
            }
            HStack {
                Button("Not Now") { w.close() }
                Spacer()
                Button("Choose Each Step…") { w.page = .folders }.disabled(w.loading)
                Button("Quick Setup") { w.page = .quick }
                    .keyboardShortcut(.defaultAction).disabled(w.loading)
            }
        }
    }

    var quick: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Quick Setup").font(.title2.weight(.semibold))
            Text("aht will:").foregroundColor(.secondary)
            bullet("folder", "Watch " + names(w.chosenRoots) + ".")
            bullet("clock.arrow.circlepath", projectsLine)
            bullet("questionmark.circle", folderRules)
            if !extrasLine.isEmpty { bullet("tag", extrasLine) }
            loginLine
            if w.install {
                bullet("terminal", "Install the background watcher, the Claude Code hooks and the "
                       + "aht command; “aht uninstall” in a terminal undoes it all.")
            }
            Spacer()
            buttons(back: .hello, next: "Next") {
                w.quickly = true
                w.page = .updates
            }
        }
    }

    /// Starting in the menu bar at login as it will be set, with its switch
    /// right there: a no given before is kept, and says so.
    var loginLine: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "menubar.rectangle").foregroundColor(.accentColor).frame(width: 20)
            VStack(alignment: .leading, spacing: 2) {
                Text("Start in the menu bar when you log in.")
                if !w.login && w.asked {
                    Text(w.answered ? "You turned this off earlier." : "It is off now.")
                        .font(.caption).foregroundColor(.secondary)
                }
            }
            .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 8)
            Toggle("Start in the menu bar when you log in", isOn: $w.login)
                .labelsHidden().toggleStyle(.switch).controlSize(.small)
        }
    }

    // Quick Setup keeps the rules and switches as they are (aht's defaults the
    // first time), so its page says what they are.
    var projectsLine: String {
        let take = w.projects.filter { $0.chosen }
        let forgot = w.projects.filter { $0.forgotten && !$0.chosen }
        var line = "Take on new projects as you work in them"
            + (w.projects.isEmpty ? " (none with agent history yet)." : ".")
        if !take.isEmpty {
            line = "Take on the \(take.count) project\(take.count == 1 ? "" : "s") "
                + "there that already " + (take.count == 1 ? "has" : "have")
                + " agent history: " + names(take.map { $0.path }, 3) + "."
        }
        if !forgot.isEmpty {
            line += " Leave out " + names(forgot.map { $0.path }, 2) + ": you told aht to forget "
                + (forgot.count == 1 ? "it." : "them.")
        }
        return line
    }

    var folderRules: String {
        if w.moves == "ask" && w.copies == "ask" {
            return "Ask you before it relinks a folder that moved or was copied."
        }
        let moved = ["ask": "Ask you before it relinks a folder that moved",
                     "apply": "Relink a moved folder without asking you",
                     "decline": "Never relink a moved folder",
                     "ignore": "Do nothing when a folder moves"][w.moves]
            ?? "Keep your rule for a folder that moves"
        let copied = ["ask": "ask you what to do with a copied folder",
                      "duplicate": "give a copied folder a copy of the history",
                      "independent": "give a copied folder a fresh start, without history",
                      "ignore": "do nothing when a folder is copied"][w.copies]
            ?? "keep your rule for a copied folder"
        return moved + "; " + copied + "."
    }

    var extrasLine: String {
        switch (w.badges, w.backups) {
        case (true, true): return "Badge project folders in Finder, and back up the histories once a day."
        case (true, false): return "Badge project folders in Finder."
        case (false, true): return "Back up the histories once a day."
        default: return ""
        }
    }

    var folders: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Which folders hold your projects?").font(.title2.weight(.semibold))
            Text("aht notices moves, copies and new projects inside these folders. A project "
                 + "elsewhere keeps its history, but aht does not follow it when it moves.")
                .foregroundColor(.secondary).fixedSize(horizontal: false, vertical: true)
            ScrollView {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach($w.roots) { $r in
                        Toggle(isOn: $r.chosen) {
                            HStack {
                                Text(tilde(r.path))
                                Text(r.projects == 0 ? "" : "\(r.projects) project\(r.projects == 1 ? "" : "s") with agent history")
                                    .font(.caption).foregroundColor(.secondary)
                            }
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            if !w.elsewhere.isEmpty {
                Text("Also with history, outside these: " + names(w.elsewhere, 3))
                    .font(.caption).foregroundColor(.secondary)
            }
            Button("Add Folder…") { w.addRoot() }
            buttons(back: .hello, next: "Next", enabled: !w.chosenRoots.isEmpty) {
                w.load()
                w.page = .projects
            }
        }
    }

    var projectList: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Projects aht found").font(.title2.weight(.semibold))
            Text("These folders already have agent history. aht takes on the ones you tick, "
                 + "and new projects as you work in them.")
                .foregroundColor(.secondary).fixedSize(horizontal: false, vertical: true)
            if w.loading {
                ProgressView().controlSize(.small)
            } else if w.projects.isEmpty {
                Text("None yet in these folders.").foregroundColor(.secondary)
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach($w.projects) { $p in
                        Toggle(isOn: $p.chosen) {
                            HStack {
                                Text(tilde(p.path)).lineLimit(1).truncationMode(.middle)
                                Text(p.agents.joined(separator: ", ")
                                     + (p.forgotten ? " · you told aht to forget it" : ""))
                                    .font(.caption).foregroundColor(.secondary)
                            }
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            if !w.projects.isEmpty {
                HStack {
                    Button("All") { for i in w.projects.indices { w.projects[i].chosen = true } }
                    Button("None") { for i in w.projects.indices { w.projects[i].chosen = false } }
                }
                .controlSize(.small)
            }
            buttons(back: .folders, next: "Next") { w.page = .rules }
        }
    }

    var rules: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("When a folder changes").font(.title2.weight(.semibold))
            Text("aht keeps the history with its folder. It can ask you first, or do it by itself.")
                .foregroundColor(.secondary)
            policy("A project folder moves", $w.moves,
                   [("ask", "Ask me"), ("apply", "Relink automatically"),
                    ("decline", "Never relink (remember the no)"), ("ignore", "Do nothing")])
            policy("A project folder is copied", $w.copies,
                   [("ask", "Ask me"), ("duplicate", "Duplicate the history"),
                    ("independent", "Fresh identity, no history"), ("ignore", "Do nothing")])
            Spacer()
            buttons(back: .projects, next: "Next") { w.page = .extras }
        }
    }

    var extras: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("A few more").font(.title2.weight(.semibold))
            Toggle("Badge project folders in Finder", isOn: $w.badges)
            Toggle("Back up the agents' histories once a day", isOn: $w.backups)
            Toggle("Show notices (a session waits for you, a long one is done)", isOn: $w.notifications)
            Toggle("Start aht in the menu bar when I log in", isOn: $w.login)
            Spacer()
            buttons(back: .rules, next: "Next") {
                w.quickly = false
                w.page = .updates
            }
        }
    }

    /// A step of its own, so nobody misses it: aht stays current only if it
    /// may ask GitHub, which is off until the person says yes here.
    var updates: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 10) {
                Image(systemName: "arrow.down.circle").font(.title).foregroundColor(.accentColor)
                Text("Stay up to date").font(.title2.weight(.semibold))
            }
            Text("aht gets new features and fixes regularly. Should it tell you when a new "
                 + "version is out?")
                .fixedSize(horizontal: false, vertical: true)
            bullet("bell", "A notice says so, with what's new and an Upgrade button.")
            bullet("network", "To know, aht asks GitHub once a day which version is the latest. "
                   + "GitHub sees your computer's address and which version of aht you run; "
                   + "nothing else is sent.")
            bullet("gearshape", "You can change this any time in Settings → This Mac.")
            Spacer()
            HStack {
                Button("Back") { w.page = w.quickly ? .quick : .extras }
                Spacer()
                Button("No Thanks") {
                    w.updateCheck = false
                    w.apply(m)
                }
                Button("Yes, Tell Me") {
                    w.updateCheck = true
                    w.apply(m)
                }
                .keyboardShortcut(.defaultAction)
            }
        }
    }

    var working: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Setting up aht").font(.title2.weight(.semibold))
            if let f = w.failed {
                Text("That did not work:").foregroundColor(.orange)
                ScrollView { Text(f).font(.caption.monospaced()).textSelection(.enabled) }
                HStack {
                    Button("Close") { w.close() }
                    Spacer()
                    Button("Try Again") { w.apply(m) }.keyboardShortcut(.defaultAction)
                }
            } else {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text(w.working).foregroundColor(.secondary)
                }
                Spacer()
            }
        }
    }

    var summary: String {
        let took: String = w.adopted == 0 ? "projects are taken on as you work in them"
            : "took on \(w.adopted) project" + (w.adopted == 1 ? "" : "s")
        return "Watching " + names(w.chosenRoots) + "; " + took + ". Look for the ∞ in the menu bar."
    }

    var done: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 10) {
                Image(systemName: "checkmark.circle.fill").foregroundColor(.green).font(.title)
                Text("aht is set up").font(.title2.weight(.semibold))
            }
            Text(summary)
                .foregroundColor(.secondary).fixedSize(horizontal: false, vertical: true)
            Divider()
            Text("Getting started: what lets aht do more").fontWeight(.semibold)
            ScrollView { SetupList().padding(.trailing, 12) }
            HStack {
                HelpButton("Getting started")
                Spacer()
                Button("Done") { w.close() }.keyboardShortcut(.defaultAction)
            }
        }
    }
}

struct SettingsView: View {
    @EnvironmentObject var m: AppModel
    @State private var maxFiles = ""
    @State private var excludes = ""
    @State private var wsEvery = ""
    @State private var wsKeep = ""
    @State private var chimeVolume = 70.0

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

    /// aht's chimes, the sounds of macOS and your own, none, or a file; the
    /// one picked plays at once.
    func chimePicker(_ title: String, _ key: String) -> some View {
        let now = m.text(key, CHIME_DEFAULTS[key] ?? "")
        let file = "\u{1}file"
        return HStack(spacing: 6) {
            Text(title).frame(width: 170, alignment: .leading)
            Picker("", selection: Binding(get: { now }, set: { v in
                if v == file { m.chooseChimeFile(key) } else { m.set(key, v); m.playChime(v) }
            })) {
                ForEach(Chimes.long, id: \.self) { Text($0).tag($0) }
                Divider()
                ForEach(Chimes.short, id: \.self) { Text($0).tag($0) }
                Divider()
                ForEach(ChimePlayer.soundNames(), id: \.self) { Text($0).tag($0) }
                Divider()
                if now.contains("/") { Text(ChimePlayer.label(now)).tag(now) }
                Text("None").tag("")
                Text("Choose a File…").tag(file)
            }
            .labelsHidden().frame(width: 130)
            Button { m.playChime(now) } label: { Image(systemName: "play.fill") }
                .help("Play it").disabled(now.isEmpty).fixedSize()
        }
    }

    func doneAfter() -> some View {
        let now = m.number("chime_done_after", 30)
        var options = [(0, "any length"), (10, "10 seconds"), (30, "30 seconds"),
                       (60, "1 minute"), (180, "3 minutes"), (600, "10 minutes")]
        if !options.contains(where: { $0.0 == now }) { options.append((now, "\(now) seconds")) }
        return Picker("", selection: Binding(get: { now },
                                             set: { m.set("chime_done_after", String($0)) })) {
            ForEach(options, id: \.0) { Text($0.1).tag($0.0) }
        }
        .labelsHidden().fixedSize()
    }

    func tokenToggle(_ title: String, _ key: String, _ cost: String?) -> some View {
        HStack(spacing: 8) {
            Toggle(title, isOn: Binding(get: { m.flag(key, false) },
                                        set: { m.set(key, $0 ? "true" : "false") }))
            if let c = cost {
                Text(c).font(.caption).foregroundColor(.secondary)
            }
        }
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                HStack(spacing: 6) {
                    Text("Every setting, also those without a switch here, is in the guide:")
                        .foregroundColor(.secondary)
                    HelpButton("All settings")
                    Spacer()
                }
                GroupBox(label: HStack(spacing: 6) { Text("Getting started"); HelpButton("Getting started") }) {
                    HStack {
                        Text(m.setupSummary)
                            .foregroundColor(m.setupMissing ? .orange : .secondary)
                            .fixedSize(horizontal: false, vertical: true)
                        Spacer()
                        Button("Show the Steps…") { m.showGettingStarted = true }
                    }
                    .padding(6)
                }
                GroupBox(label: HStack(spacing: 6) { Text("Watched folders"); HelpButton("Setting up") }) {
                    VStack(alignment: .leading, spacing: 6) {
                        ForEach(m.roots, id: \.self) { r in
                            HStack {
                                Image(systemName: "folder").foregroundColor(.secondary)
                                Text(tilde(r))
                                if !FileManager.default.fileExists(atPath: r) {
                                    Text("missing").font(.caption).foregroundColor(.orange)
                                }
                                Spacer()
                                Button("Remove") { m.setRoots(m.roots.filter { $0 != r }) }
                                    .controlSize(.small).disabled(m.roots.count < 2)
                            }
                        }
                        HStack {
                            Button("Add Folder…") { m.addRoot() }
                            Spacer()
                        }
                        Text("aht notices moves, copies and new projects inside these folders. "
                             + "A project elsewhere keeps its history, but aht does not follow it "
                             + "when it moves.")
                            .font(.caption).foregroundColor(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(6).frame(maxWidth: .infinity, alignment: .leading)
                }
                GroupBox(label: HStack(spacing: 6) { Text("When folders change"); HelpButton("Folders that move") }) {
                    VStack(alignment: .leading, spacing: 8) {
                        choice("A folder moves", "move_policy",
                               [("ask", "Ask me"), ("apply", "Relink automatically"),
                                ("decline", "Never relink (remember the no)"),
                                ("ignore", "Do nothing")])
                        choice("A folder is copied", "copy_policy",
                               [("ask", "Ask me"), ("duplicate", "Duplicate the history"),
                                ("independent", "Fresh identity, no history"),
                                ("ignore", "Do nothing")])
                    }
                    .padding(6).frame(maxWidth: .infinity, alignment: .leading)
                }
                GroupBox(label: HStack(spacing: 6) { Text("Histories"); HelpButton("Backups") }) {
                    HStack(spacing: 16) {
                        toggle("Notifications", "notifications")
                        toggle("Back up histories automatically", "backup_enabled")
                        Spacer()
                        Button("Check All for Secrets…") { m.checkSecrets(nil) }
                        Button("Back Up Now") { m.backupNow() }
                    }
                    .padding(6)
                }
                GroupBox(label: HStack(spacing: 6) { Text("Notices"); HelpButton("Know when a session needs you") }) {
                    VStack(alignment: .leading, spacing: 8) {
                        HStack(spacing: 16) {
                            toggle("When a session waits for you", "notify_waiting")
                            toggle("When a long piece of work is done", "notify_finished")
                        }
                        Toggle("Show the open Claude sessions in the screen's top-right corner",
                               isOn: Binding(get: { m.flag("session_corner", false) },
                                             set: { m.set("session_corner", $0 ? "true" : "false") }))
                        Text("Each one shows whether it works, waits for you or is done. "
                             + "“Done” stays until you click the session there (that goes to "
                             + "its tab) or it starts working again. Also in the aht menu: "
                             + "Sessions in the Corner.")
                            .font(.caption).foregroundColor(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                        HStack {
                            Text("Also send them to my phone:")
                            TextField("imessage:+43… or ntfy:my-topic",
                                      text: Binding(get: { m.text("notify_phone", "") },
                                                    set: { m.config["notify_phone"] = $0 }))
                                .textFieldStyle(.roundedBorder).frame(width: 260)
                            Button("Save") { m.set("notify_phone", m.text("notify_phone", "")) }
                            Button("Send a Test") { m.testNotice() }
                        }
                        Text("Sessions here and on your other machines are checked every 30 "
                             + "seconds. iMessage goes to your own number or Apple ID; ntfy "
                             + "to a topic you follow in the ntfy app.")
                            .font(.caption).foregroundColor(.secondary)
                    }
                    .padding(6).frame(maxWidth: .infinity, alignment: .leading)
                }
                GroupBox(label: HStack(spacing: 6) { Text("Chimes"); HelpButton("Chimes") }) {
                    VStack(alignment: .leading, spacing: 8) {
                        Toggle("Play a chime when a session here is done or waits for you",
                               isOn: Binding(get: { m.flag("chimes", false) },
                                             set: { m.set("chimes", $0 ? "true" : "false") }))
                        VStack(alignment: .leading, spacing: 6) {
                            chimePicker("Waits for you", "chime_waiting")
                            HStack(spacing: 6) {
                                chimePicker("Is done", "chime_done")
                                Text("after working at least").padding(.leading, 6)
                                doneAfter()
                            }
                            chimePicker("Hits the usage limit", "chime_limit")
                            HStack(spacing: 6) {
                                Text("Volume").frame(width: 170, alignment: .leading)
                                Image(systemName: "speaker.fill").foregroundColor(.secondary)
                                Slider(value: $chimeVolume, in: 0...100, onEditingChanged: { on in
                                    guard !on else { return }
                                    m.set("chime_volume", String(Int(chimeVolume.rounded())))
                                    if let c = ["chime_done", "chime_waiting", "chime_limit"]
                                        .map({ m.text($0, CHIME_DEFAULTS[$0] ?? "") })
                                        .first(where: { !$0.isEmpty }) {
                                        m.playChime(c)
                                    }
                                })
                                .frame(width: 160)
                                Image(systemName: "speaker.wave.3.fill").foregroundColor(.secondary)
                            }
                        }
                        .padding(.leading, 20)
                        .disabled(!m.flag("chimes", false))
                        Text("A session on this Mac chimes the moment it is done or begins to "
                             + "wait (aht looks every second and a half; no tokens). One on "
                             + "another machine, and the usage limit, chime with their notice. "
                             + "With chimes on, those notices make no sound of their own, so you "
                             + "hear one sound, not two. Also in the aht menu: Chimes.")
                            .font(.caption).foregroundColor(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(6).frame(maxWidth: .infinity, alignment: .leading)
                }
                GroupBox(label: HStack(spacing: 6) { Text("Safety nets (no tokens)"); HelpButton("Undo a whole session") }) {
                    VStack(alignment: .leading, spacing: 8) {
                        toggle("Copy the folder when a session starts, to undo a whole session",
                               "checkpoints")
                        toggle("Tell me when Claude stops at its usage limit", "notify_limit")
                        toggle("Show sessions in Spotlight", "spotlight")
                        HStack {
                            Text("A project with more than")
                            TextField("20000", text: $maxFiles)
                                .textFieldStyle(.roundedBorder).frame(width: 90)
                            Text("files gets no copy")
                            Button("Apply") { m.applyMaxFiles(maxFiles) }
                            Button("Which Are Cut Off?") { m.checkCoverage(nil) }
                            Spacer()
                        }
                        .padding(.leading, 20)
                        HStack {
                            Text("Leave these folders out of the copies:")
                            TextField("e.g. results, datasets", text: $excludes)
                                .textFieldStyle(.roundedBorder).frame(width: 240)
                            Button("Save") { m.saveExcludes(excludes) }
                            Spacer()
                        }
                        .padding(.leading, 20)
                        if let c = m.coverageNote {
                            Text(c).font(.caption).foregroundColor(.orange).padding(.leading, 20)
                        }
                        Text("The copies are copy-on-write: they take no room until a file "
                             + "changes, and the last \(m.config["checkpoint_keep"] as? Int ?? 10) "
                             + "per project are kept. Time Machine leaves them out.")
                            .font(.caption).foregroundColor(.secondary)
                    }
                    .padding(6).frame(maxWidth: .infinity, alignment: .leading)
                }
                GroupBox(label: HStack(spacing: 6) { Text("The Claude app on your phone"); HelpButton("Session names from your iTerm2 tabs") }) {
                    VStack(alignment: .leading, spacing: 8) {
                        toggle("Name each Claude session after its iTerm2 tab", "tab_names")
                        Text("The name shows in the Claude app, in /resume and in the "
                             + "session's prompt bar. It is set when a session starts, and "
                             + "at the next prompt after you rename the tab. A second open "
                             + "session under the same tab title becomes “· 2” (a branch "
                             + "“⑂ 2”). The latest name wins: name a session yourself "
                             + "(/rename, in the app, or Rename… in the Sessions tab) and its "
                             + "tab takes the name; rename the tab and the session follows. "
                             + "No tokens.")
                            .font(.caption).foregroundColor(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                        if !m.itermInstalled {
                            Text("This needs iTerm2, which is not on this Mac (see Getting "
                                 + "started, at the top).")
                                .font(.caption).foregroundColor(.orange)
                        } else if m.setupSteps.first(where: { $0.id == "iterm_api" })?.ok == false {
                            Text("Tabs keep their titles for now: iTerm2 lets aht change a "
                                 + "title you gave a tab only through its Python API. To switch "
                                 + "it on: iTerm2 → Settings → General → Magic → Enable Python API.")
                                .font(.caption).foregroundColor(.orange)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        Text((m.status["claude_remote_control"] as? Bool ?? false)
                             ? "Remote Control is on for every session, so each one is in the app."
                             : "Remote Control is off: in Claude Code, /config → Enable Remote "
                               + "Control for all sessions puts every session into the app.")
                            .font(.caption)
                            .foregroundColor((m.status["claude_remote_control"] as? Bool ?? false)
                                             ? .secondary : .orange)
                    }
                    .padding(6).frame(maxWidth: .infinity, alignment: .leading)
                }
                GroupBox(label: HStack(spacing: 6) { Text("Restore my workspace"); HelpButton("Restore my workspace") }) {
                    VStack(alignment: .leading, spacing: 8) {
                        HStack {
                            Text("Save the iTerm2 layout every")
                            TextField("10", text: $wsEvery)
                                .textFieldStyle(.roundedBorder).frame(width: 50)
                            Text("minutes, keep the last")
                            TextField("40", text: $wsKeep)
                                .textFieldStyle(.roundedBorder).frame(width: 50)
                            Button("Apply") { m.applyWorkspaceSaving(wsEvery, wsKeep) }
                            Spacer()
                        }
                        Text("While this app runs and iTerm2 is open; a layout that did not "
                             + "change is not saved again. It is also saved when a session gets "
                             + "a prompt. 0 minutes: only then. No tokens.")
                            .font(.caption).foregroundColor(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                        if !m.itermInstalled {
                            Text("This needs iTerm2, which is not on this Mac (see Getting "
                                 + "started, at the top).")
                                .font(.caption).foregroundColor(.orange)
                        }
                    }
                    .padding(6).frame(maxWidth: .infinity, alignment: .leading)
                }
                GroupBox(label: HStack(spacing: 6) { Text("Uses tokens — off until you turn it on"); HelpButton("What uses tokens") }) {
                    VStack(alignment: .leading, spacing: 8) {
                        tokenToggle("A new Claude session learns where the last one in its "
                                    + "folder stopped", "informed_sessions",
                                    "a few hundred tokens per new session")
                        HStack {
                            tokenToggle("When Claude stops at its limit, offer to go on in",
                                        "limit_switch", nil)
                            Picker("", selection: Binding(get: { m.text("limit_switch_to", "kimi") },
                                                          set: { m.set("limit_switch_to", $0) })) {
                                Text("Kimi Code").tag("kimi")
                                Text("Codex").tag("codex")
                                Text("Antigravity").tag("agy")
                            }
                            .labelsHidden().fixedSize()
                            Text("that agent reads a summary").font(.caption).foregroundColor(.secondary)
                        }
                        HStack(spacing: 8) {
                            Toggle("When Claude's usage limit resets, the session continues by itself",
                                   isOn: Binding(get: { m.status["claude_auto_continue"] as? Bool ?? false },
                                                 set: { m.setAutoContinue($0) }))
                            Text("Claude Code's own setting").font(.caption).foregroundColor(.secondary)
                        }
                        tokenToggle("Second opinion: one task, two agents, compared",
                                    "second_opinion", "both agents work")
                        tokenToggle("Night shift: hand a project over with a task, on a timer",
                                    "night_shift", "the agent works while you are away")
                        Text("Each of these makes an agent read or work, which counts against "
                             + "your plan or API bill. aht's own work — watching, search, "
                             + "backups, reports, loose ends — never uses tokens.")
                            .font(.caption).foregroundColor(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(6).frame(maxWidth: .infinity, alignment: .leading)
                }
                GroupBox(label: HStack(spacing: 6) { Text("Backups on another machine"); HelpButton("Backups") }) {
                    VStack(alignment: .leading, spacing: 8) {
                        HStack {
                            Picker("Keep a copy of the history backups on", selection: Binding(
                                get: { m.text("offsite_backup", "") },
                                set: { m.set("offsite_backup", $0) })) {
                                Text("no other machine").tag("")
                                ForEach(m.machines) { Text($0.name).tag($0.name) }
                            }
                            .frame(maxWidth: 460)
                            Spacer()
                            Button("Copy Now") { m.copyBackupsNow() }
                                .disabled(m.text("offsite_backup", "").isEmpty)
                            Button("Fetch Backups From…") { m.openFetchBackups() }
                                .disabled(m.text("offsite_backup", "").isEmpty || !m.canReach
                                          || m.working != nil)
                        }
                        Text("After each daily backup, aht adds the new ones to a folder of this "
                             + "Mac's own there. A backup there goes only after aht removed it "
                             + "here, and at least 3 per project stay. Fetch Backups From… brings "
                             + "back the backups any of your computers left there: it adds what "
                             + "is missing here and replaces nothing.")
                            .font(.caption).foregroundColor(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(6).frame(maxWidth: .infinity, alignment: .leading)
                }
                GroupBox(label: HStack(spacing: 6) { Text("Folder badges"); HelpButton("Folder badges") }) {
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
                GroupBox(label: HStack(spacing: 6) { Text("Handover"); HelpButton("Hand a project over") }) {
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
                GroupBox(label: HStack(spacing: 6) { Text("Where each agent keeps its history"); HelpButton("All settings") }) {
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
                GroupBox(label: HStack(spacing: 6) { Text("This Mac"); HelpButton("Settings") }) {
                    VStack(alignment: .leading, spacing: 10) {
                        Toggle("Start aht in the menu bar at login",
                               isOn: Binding(get: { m.loginItem },
                                             set: { m.setLoginItem($0) }))
                        HStack(spacing: 10) {
                            Toggle("Tell me when a new version of aht is out",
                                   isOn: Binding(get: { m.flag("update_check", false) },
                                                 set: { m.set("update_check", $0 ? "true" : "false") }))
                            Button("Check Now") { m.checkUpdateNow() }.controlSize(.small)
                            if let v = m.newVersion {
                                Button("aht \(v) Is Out…") { m.showUpdate = true }.controlSize(.small)
                            }
                            HelpButton("New versions")
                        }
                        Text("Once a day aht asks GitHub which version is the latest. GitHub sees "
                             + "your computer's address and which version of aht you run; nothing "
                             + "else is sent. Off until you turn it on.")
                            .font(.caption).foregroundColor(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                        HStack {
                            Text("Open session windows in")
                            Picker("", selection: Binding(
                                get: { m.config["terminal_app"] as? String ?? "" },
                                set: { m.setTerminal($0) })) {
                                Text("Automatic (iTerm when installed)").tag("")
                                ForEach(((m.status["terminals"] as? [String: Any])?["installed"]
                                         as? [String]) ?? ["Terminal"], id: \.self) {
                                    Text($0).tag($0)
                                }
                            }
                            .labelsHidden().fixedSize()
                            Spacer()
                        }
                        Text("Search from anywhere: " + hotkeyLabel(m.text("hotkey", "ctrl+opt+cmd+a"))
                             + " — and in Finder, right-click a project folder for aht's actions.")
                            .foregroundColor(.secondary)
                        HStack(spacing: 10) {
                            Button("Run Setup Again…") { m.openWelcome?() }
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
        .onAppear {
            maxFiles = String(m.config["checkpoint_max_files"] as? Int ?? 20000)
            wsEvery = String(m.config["workspace_save_minutes"] as? Int ?? 10)
            wsKeep = String(m.config["workspace_keep"] as? Int ?? 40)
            chimeVolume = Double(m.number("chime_volume", 70))
            excludes = ((m.config["checkpoint_excludes"] as? [String]) ?? []).joined(separator: ", ")
        }
    }
}

// ---- the session corner: the open Claude sessions, top right of the screen ------

struct CornerRow: Identifiable, Equatable {
    let id: String              // the session id
    let pid: Int
    let name: String
    let project: String
    let state: String           // "waiting", "done", "working" or "idle"
    let age: String             // how long it has been so, "" for idle
    let recent: Double          // the order: working now first, then by when it last ran
}

let CORNER_STATE = HOME + "/.aht/run/corner.json"

/// Claude Code keeps a record of each open session (<claude home>/sessions/
/// <pid>.json) with what it is doing; the corner reads them every second and
/// a half. A session that goes from working to idle is "done" until you
/// click it in the corner or it starts working again. The marks are kept in
/// a file, so they outlast the app restarting. The name is the one the
/// Claude app shows, from the session's conversation file. The chimes
/// hear from it, too, when a session begins waiting for you or finishes.
final class CornerModel: ObservableObject {
    @Published var rows: [CornerRow] = []
    @Published var width: CGFloat = 252         // how wide the list is
    @Published var most = 12                    // how many sessions it lists, the rest "+n more"
    @Published var note: String?                // why a click went nowhere, for a few seconds
    var sessionsDir = HOME + "/.claude/sessions"
    private var last: [String: String] = [:]    // session → its status at the last look
    private var done: [String: Double] = [:]    // session → when it finished
    private var runSince: [String: Double] = [:]
    private var byPid: [Int: (CornerRow, String)] = [:]
    private var titles: [String: (end: UInt64, custom: String, auto: String)] = [:]
    /// What changed since the last look: a session that began waiting for
    /// you, or one that is done, with how long that piece of work took.
    var onNews: (([(kind: String, worked: Double)]) -> Void)?
    private var turnSince: [String: Double] = [:]   // session → when it last left idle
    private var lastLook = 0.0

    init() {
        if let d = FileManager.default.contents(atPath: CORNER_STATE),
           let j = (try? JSONSerialization.jsonObject(with: d)) as? [String: Any] {
            last = j["last"] as? [String: String] ?? [:]
            done = (j["done"] as? [String: NSNumber] ?? [:]).mapValues { $0.doubleValue }
        }
    }

    func poll() {
        let fm = FileManager.default
        let now = Date().timeIntervalSince1970
        var status: [String: String] = [:]
        var found: [Int: (CornerRow, String)] = [:]
        var news: [String: (kind: String, worked: Double)] = [:]
        let fresh = now - lastLook < 10             // after a pause it is old news
        lastLook = now
        for f in (try? fm.contentsOfDirectory(atPath: sessionsDir)) ?? [] where f.hasSuffix(".json") {
            guard let pid = Int(f.dropLast(5)), pid > 0,
                  kill(pid_t(pid), 0) == 0 || errno == EPERM else { continue }
            guard let d = fm.contents(atPath: sessionsDir + "/" + f),
                  let r = (try? JSONSerialization.jsonObject(with: d)) as? [String: Any],
                  let sid = r["sessionId"] as? String else {
                if let old = byPid[pid] {             // caught mid-write: as it was
                    found[pid] = old
                    status[old.0.id] = old.1
                }
                continue
            }
            let st = r["status"] as? String ?? "idle"
            let working = st == "busy" || st == "shell"
            let wasWorking = last[sid] == "busy" || last[sid] == "shell"
            let at = ((r["statusUpdatedAt"] as? NSNumber)?.doubleValue).map { $0 / 1000 } ?? now
            if working {
                done[sid] = nil
                if !wasWorking || runSince[sid] == nil { runSince[sid] = at }
            } else {
                runSince[sid] = nil
                if st == "idle" && wasWorking { done[sid] = now }
            }
            let began = turnSince[sid] ?? at
            turnSince[sid] = st == "idle" ? nil : began
            if fresh, (r["kind"] as? String ?? "interactive") == "interactive" {   // not `claude -p`
                if st == "waiting", let was = last[sid], was != "waiting" {
                    news[sid] = ("waiting", now - began)
                } else if st == "idle" && wasWorking {
                    news[sid] = ("done", now - began)
                }
            }
            status[sid] = st
            let cwd = r["cwd"] as? String ?? ""
            let state = st == "waiting" ? "waiting" : working ? "working"
                : done[sid] != nil ? "done" : "idle"
            let since = working ? runSince[sid] ?? at : state == "done" ? done[sid] ?? at : at
            let own = (r["name"] as? String ?? "").trimmingCharacters(in: .whitespaces)
            let t = title(sid, cwd)
            let name = t.custom ?? (r["nameSource"] as? String == "user" && !own.isEmpty ? own : nil)
                ?? t.auto ?? (own.isEmpty ? (cwd as NSString).lastPathComponent : own)
            found[pid] = (CornerRow(id: sid, pid: pid, name: name, project: cwd, state: state,
                                    age: state == "idle" ? "" : Self.age(now - since),
                                    recent: working ? 1e12 + since : since), st)
        }
        byPid = found
        done = done.filter { status[$0.key] != nil }
        turnSince = turnSince.filter { status[$0.key] != nil }
        if status != last {
            last = status
            save()
        }
        var one: [String: CornerRow] = [:]            // one row per session
        for (row, _) in found.values where one[row.id] == nil || one[row.id]!.pid < row.pid {
            one[row.id] = row
        }
        let rows = one.values.sorted {
            ($0.recent, $1.name.lowercased(), $1.pid) > ($1.recent, $0.name.lowercased(), $0.pid)
        }
        if rows != self.rows { self.rows = rows }
        if !news.isEmpty { onNews?(Array(news.values)) }
    }

    /// The session's title from its conversation file (Claude Code's own
    /// encoding of the folder): the last one a rename, the app or aht's
    /// hook set, else Claude's automatic one. Only what was added to the
    /// file since the last look is read; the first look reads up to 8 MB.
    private func title(_ sid: String, _ cwd: String) -> (custom: String?, auto: String?) {
        let projects = ((sessionsDir as NSString).deletingLastPathComponent as NSString)
            .appendingPathComponent("projects")
        func key(_ p: String) -> String {
            String(String.UnicodeScalarView(p.unicodeScalars.map {
                (48...57).contains($0.value) || (65...90).contains($0.value)
                    || (97...122).contains($0.value) ? $0 : "-"
            }))
        }
        for c in Set([cwd, (cwd as NSString).resolvingSymlinksInPath]) {
            let path = projects + "/" + key(c) + "/" + sid + ".jsonl"
            guard let fh = FileHandle(forReadingAtPath: path) else { continue }
            defer { try? fh.close() }
            let size = (try? fh.seekToEnd()) ?? 0
            var t = titles[path] ?? (0, "", "")
            if size < t.end { t = (0, "", "") }       // written anew
            if size > t.end {
                let from = t.end > 0 ? t.end : (size > 8 << 20 ? size - (8 << 20) : 0)
                try? fh.seek(toOffset: from)
                let data = fh.readData(ofLength: Int(size - from))
                if let v = Self.lastOf(data, "custom-title", "customTitle") { t.custom = v }
                if let v = Self.lastOf(data, "ai-title", "aiTitle") { t.auto = v }
                if let nl = data.lastIndex(of: 10) {  // a line half written: read again
                    t.end = from + UInt64(nl - data.startIndex + 1)
                }
                titles[path] = t
            }
            return (t.custom.isEmpty ? nil : t.custom, t.auto.isEmpty ? nil : t.auto)
        }
        return (nil, nil)
    }

    /// The `field` of the last line of type `kind` in a piece of a JSONL file.
    static func lastOf(_ data: Data, _ kind: String, _ field: String) -> String? {
        let mark = Data("\"\(kind)\"".utf8)
        var upper = data.endIndex
        for _ in 0..<20 {
            guard upper > data.startIndex,
                  let r = data.range(of: mark, options: .backwards, in: data.startIndex..<upper)
            else { return nil }
            let start = data[..<r.lowerBound].lastIndex(of: 10).map { $0 + 1 } ?? data.startIndex
            let end = data[r.upperBound...].firstIndex(of: 10) ?? data.endIndex
            if let j = (try? JSONSerialization.jsonObject(with: data.subdata(in: start..<end)))
                as? [String: Any], j["type"] as? String == kind,
               let v = j[field] as? String, !v.isEmpty {
                return v
            }
            upper = start
        }
        return nil
    }

    /// A line under the list's top for a few seconds.
    func say(_ text: String) {
        note = text
        DispatchQueue.main.asyncAfter(deadline: .now() + 8) { [weak self] in
            if self?.note == text { self?.note = nil }
        }
    }

    /// You looked at it: it is no longer "done".
    func seen(_ r: CornerRow) {
        done[r.id] = nil
        save()
        poll()
    }

    static func age(_ s: Double) -> String {
        s < 60 ? "now" : s < 3600 ? "\(Int(s / 60))m" : s < 86400 ? "\(Int(s / 3600))h"
            : "\(Int(s / 86400))d"
    }

    private func save() {
        guard let d = try? JSONSerialization.data(withJSONObject: ["last": last, "done": done])
        else { return }
        try? d.write(to: URL(fileURLWithPath: CORNER_STATE), options: .atomic)
    }
}

struct CornerBackground: NSViewRepresentable {
    func makeNSView(context: Context) -> NSVisualEffectView {
        let v = NSVisualEffectView()
        v.material = .popover
        v.blendingMode = .behindWindow
        v.state = .active
        return v
    }
    func updateNSView(_ v: NSVisualEffectView, context: Context) {}
}

struct CornerView: View {
    @ObservedObject var c: CornerModel
    let open: (CornerRow) -> Void
    let hide: () -> Void
    var drag: (CGPoint, Bool) -> Void = { _, _ in }   // from where (true: let go)
    var home: () -> Void = {}                   // back to the corner
    @State private var hover: String?
    @State private var dragged = Date.distantPast

    var summary: String {
        let n = { (s: String) in c.rows.filter { $0.state == s }.count }
        let parts = [(n("waiting"), "waiting"), (n("done"), "done"), (n("working"), "working")]
            .filter { $0.0 > 0 }.map { "\($0.0) \($0.1)" }
        return parts.isEmpty ? "\(c.rows.count) open, all idle" : parts.joined(separator: " · ")
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 1) {
            HStack(spacing: 6) {
                Image(systemName: "infinity").font(.system(size: 9, weight: .semibold))
                Text(c.rows.isEmpty ? "No Claude session open" : summary)
                    .font(.system(size: 10.5, weight: .medium))
                    .lineLimit(1).truncationMode(.tail)
                Spacer(minLength: 8)
                Button(action: hide) {
                    Image(systemName: "xmark").font(.system(size: 8, weight: .bold))
                        .frame(width: 14, height: 14).contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .help("Hide the corner (the aht menu brings it back)")
            }
            .foregroundColor(.secondary)
            .padding(.horizontal, 6).padding(.top, 1).padding(.bottom, c.rows.isEmpty ? 1 : 3)
            .contentShape(Rectangle())
            .onTapGesture(count: 2) { home() }
            .help("Drag the list anywhere, or its sides and bottom to resize it; "
                  + "double-click this line to put it back in the corner")
            if let n = c.note {
                Text(n).font(.system(size: 10.5)).foregroundColor(.orange)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.horizontal, 6).padding(.bottom, 3)
            }
            ForEach(c.rows.prefix(c.most)) { r in row(r) }
            if c.rows.count > c.most {
                Text("+\(c.rows.count - c.most) more").font(.system(size: 10.5))
                    .lineLimit(1)
                    .foregroundColor(.secondary).padding(.horizontal, 6).padding(.top, 1)
            }
        }
        .padding(5)
        .frame(width: c.width)
        .background(CornerBackground())
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous)
            .strokeBorder(Color.primary.opacity(0.1), lineWidth: 0.5))
        .simultaneousGesture(DragGesture(minimumDistance: 3)
            .onChanged { v in
                dragged = Date()
                drag(v.startLocation, false)
            }
            .onEnded { v in
                dragged = Date()
                drag(v.startLocation, true)
            })
    }

    func row(_ r: CornerRow) -> some View {
        let (icon, tint): (String, Color) = {
            switch r.state {
            case "waiting": return ("exclamationmark.circle.fill", .orange)
            case "done": return ("checkmark.circle.fill", .green)
            case "working": return ("circle.dotted", .blue)
            default: return ("circle", .secondary)
            }
        }()
        return HStack(spacing: 7) {
            Image(systemName: icon).font(.system(size: 11, weight: .semibold))
                .foregroundColor(tint).frame(width: 14)
            Text(r.name).font(.system(size: 12, weight: r.state == "done"
                                      || r.state == "waiting" ? .semibold : .regular))
                .foregroundColor(r.state == "idle" ? .secondary : .primary)
                .lineLimit(1).truncationMode(.tail)
            Spacer(minLength: 6)
            Text(r.state == "waiting" ? "waits " + r.age : r.age)
                .font(.system(size: 10).monospacedDigit()).foregroundColor(.secondary)
                .lineLimit(1).fixedSize().layoutPriority(1)
        }
        .padding(.horizontal, 6).padding(.vertical, 3)
        .background(RoundedRectangle(cornerRadius: 5, style: .continuous)
            .fill(hover == r.id ? Color.primary.opacity(0.09)
                  : r.state == "done" ? Color.green.opacity(0.13)
                  : r.state == "waiting" ? Color.orange.opacity(0.13) : Color.clear))
        .contentShape(Rectangle())
        .onTapGesture {                         // a drag that ends here is no click
            if Date().timeIntervalSince(dragged) > 0.4 { open(r) }
        }
        .onHover { inside in
            if inside { hover = r.id } else if hover == r.id { hover = nil }
        }
        .help(r.name + "\n" + (r.project as NSString).abbreviatingWithTildeInPath + "\n"
              + (r.state == "done" ? "Done. A click goes to its tab and clears the mark."
                 : "A click goes to its tab."))
    }
}

/// What a drag on the list takes hold of: its sides change its width, its
/// bottom how many sessions it lists; anywhere else it moves the list.
struct CornerEdges: OptionSet {
    let rawValue: Int
    static let left = CornerEdges(rawValue: 1)
    static let right = CornerEdges(rawValue: 2)
    static let bottom = CornerEdges(rawValue: 4)

    init(rawValue: Int) { self.rawValue = rawValue }

    /// At `p` (from the list's top left) on a list of `size`.
    init(at p: CGPoint, in size: CGSize) {
        var e: CornerEdges = []
        if p.x < 6 { e.insert(.left) } else if p.x > size.width - 6 { e.insert(.right) }
        if p.y > size.height - 6 { e.insert(.bottom) }
        self = e
    }

    var cursor: NSCursor {
        if #available(macOS 15, *), !isEmpty {
            let at: NSCursor.FrameResizePosition = self == .left ? .left : self == .right ? .right
                : self == .bottom ? .bottom : contains(.left) ? .bottomLeft : .bottomRight
            return .frameResize(position: at, directions: .all)
        }
        return isEmpty ? .arrow : contains(.bottom) ? .resizeUpDown : .resizeLeftRight
    }
}

/// macOS lets only the app in front change the pointer; this lets aht do it
/// too, so the corner can show the resize pointer while you work elsewhere.
/// The switch is not public, so it is looked up as aht starts: without it
/// the pointer just stays an arrow.
func pointerInBackground() {
    typealias Connection = @convention(c) () -> Int32
    typealias SetProperty = @convention(c) (Int32, Int32, CFString, CFTypeRef) -> Int32
    let loaded = UnsafeMutableRawPointer(bitPattern: -2)        // RTLD_DEFAULT
    guard let conn = dlsym(loaded, "_CGSDefaultConnection"),
          let set = dlsym(loaded, "CGSSetConnectionProperty") else { return }
    let me = unsafeBitCast(conn, to: Connection.self)()
    _ = unsafeBitCast(set, to: SetProperty.self)(me, me, "SetsCursorInBackground" as CFString,
                                                 kCFBooleanTrue)
}

/// Takes clicks without making aht the front app first, and shows the
/// resize pointer over the list's sides and bottom.
final class CornerHostingView<V: View>: NSHostingView<V> {
    private var area: NSTrackingArea?

    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        if let a = area { removeTrackingArea(a) }
        let a = NSTrackingArea(rect: .zero, options: [.mouseMoved, .mouseEnteredAndExited,
                                                      .activeAlways, .inVisibleRect],
                               owner: self)
        addTrackingArea(a)
        area = a
    }

    override func mouseMoved(with e: NSEvent) {
        super.mouseMoved(with: e)
        let p = convert(e.locationInWindow, from: nil)
        CornerEdges(at: CGPoint(x: p.x, y: isFlipped ? p.y : bounds.height - p.y),
                    in: bounds.size).cursor.set()
    }

    override func mouseExited(with e: NSEvent) {
        super.mouseExited(with: e)
        if e.trackingArea === area { NSCursor.arrow.set() }
    }
}

/// The floating panel in the top-right corner of the screen with the menu bar.
final class CornerPanel {
    let model = CornerModel()
    private var panel: NSPanel?
    private var timer: Timer?
    private var size = CGSize.zero
    var onHide: () -> Void = {}

    var shown: Bool { panel?.isVisible ?? false }
    /// The chimes need the sessions watched while the list is hidden, too.
    var listening = false { didSet { pace() } }

    /// Where you dragged it: its top-left corner (it grows downwards).
    private var spot: NSPoint? {
        get {
            guard let a = UserDefaults.standard.array(forKey: "cornerTopLeft") as? [Double],
                  a.count == 2 else { return nil }
            return NSPoint(x: a[0], y: a[1])
        }
        set {
            if let p = newValue {
                UserDefaults.standard.set([Double(p.x), Double(p.y)], forKey: "cornerTopLeft")
            } else {
                UserDefaults.standard.removeObject(forKey: "cornerTopLeft")
            }
        }
    }
    /// A drag under way: where it started, and the list as it was then.
    private var held: (mouse: NSPoint, frame: NSRect, edges: CornerEdges, width: CGFloat,
                       shown: Int, most: Int)?

    init() {
        let d = UserDefaults.standard
        if d.double(forKey: "cornerWidth") > 0 { model.width = CGFloat(d.double(forKey: "cornerWidth")) }
        if d.object(forKey: "cornerRows") != nil { model.most = max(0, d.integer(forKey: "cornerRows")) }
    }

    func show(sessionsDir: String) {
        model.sessionsDir = sessionsDir
        if panel == nil {
            let p = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 252, height: 40),
                            styleMask: [.borderless, .nonactivatingPanel],
                            backing: .buffered, defer: false)
            p.isFloatingPanel = true
            p.level = .floating
            p.collectionBehavior = [.canJoinAllSpaces, .stationary, .fullScreenAuxiliary,
                                    .ignoresCycle]
            p.isOpaque = false
            p.backgroundColor = .clear
            p.hasShadow = true
            p.hidesOnDeactivate = false
            p.isReleasedWhenClosed = false
            p.acceptsMouseMovedEvents = true
            pointerInBackground()
            p.contentView = CornerHostingView(rootView: CornerView(
                c: model,
                open: { [weak self] r in self?.open(r) },
                hide: { [weak self] in self?.onHide() },
                drag: { [weak self] at, done in self?.drag(at, done) },
                home: { [weak self] in
                    self?.spot = nil
                    self?.place(force: true)
                }))
            panel = p
            NotificationCenter.default.addObserver(
                forName: NSApplication.didChangeScreenParametersNotification, object: nil,
                queue: .main) { [weak self] _ in self?.place(force: true) }
        }
        model.poll()
        place(force: true)
        panel?.orderFrontRegardless()
        pace()
    }

    func hide() {
        panel?.orderOut(nil)
        pace()
    }

    /// A look every second and a half, while the list shows or the chimes
    /// listen.
    private func pace() {
        if shown || listening {
            if timer == nil {
                timer = Timer.scheduledTimer(withTimeInterval: 1.5, repeats: true) { [weak self] _ in
                    guard let self = self else { return }
                    self.model.poll()
                    if self.shown { self.place() }
                }
            }
        } else {
            timer?.invalidate()
            timer = nil
        }
    }

    /// Where you put it, else top right just under the menu bar; it grows
    /// downwards and stays on its screen.
    private func place(force: Bool = false) {
        guard held?.edges.isEmpty != true, let p = panel, let v = p.contentView,
              let main = NSScreen.screens.first else { return }
        let fit = v.fittingSize
        guard force || fit != size else { return }
        size = fit
        var top: NSPoint
        if let at = spot, let screen = NSScreen.screens.first(where: {
            $0.frame.insetBy(dx: -1, dy: -1).contains(at)
        }) {
            let vf = screen.visibleFrame
            top = NSPoint(x: min(max(at.x, vf.minX), vf.maxX - fit.width),
                          y: min(max(at.y, vf.minY + fit.height), vf.maxY))
        } else {
            let vf = main.visibleFrame
            top = NSPoint(x: vf.maxX - fit.width - 10, y: vf.maxY - 8)
        }
        p.setFrame(NSRect(x: top.x, y: top.y - fit.height, width: fit.width,
                          height: fit.height), display: true)
    }

    /// The list follows the mouse, or from a side gets wider or narrower
    /// (the other side stays put), or from its bottom lists more or fewer
    /// sessions (the rest are "+n more"). Where you let go is kept.
    private func drag(_ start: CGPoint, _ done: Bool) {
        guard let p = panel else { return }
        let m = NSEvent.mouseLocation
        let h = held ?? (m, p.frame, CornerEdges(at: start, in: p.frame.size), model.width,
                         min(model.most, model.rows.count), model.most)
        held = h
        let dx = m.x - h.mouse.x, dy = m.y - h.mouse.y
        if h.edges.isEmpty {
            p.setFrameOrigin(NSPoint(x: h.frame.minX + dx, y: h.frame.minY + dy))
        } else {
            if !h.edges.isDisjoint(with: [.left, .right]) {
                let room = ((p.screen ?? NSScreen.main)?.visibleFrame.width ?? 800) - 20
                let w = (h.width + (h.edges.contains(.left) ? -dx : dx)).rounded()
                model.width = max(150, min(w, 720, room))
                if h.edges.contains(.right) {
                    spot = NSPoint(x: h.frame.minX, y: h.frame.maxY)
                } else if spot != nil {
                    spot = NSPoint(x: h.frame.maxX - model.width, y: h.frame.maxY)
                }
            }
            if h.edges.contains(.bottom) {              // a session is about 22 points
                let n = max(0, h.shown + Int((-dy / 22).rounded()))
                model.most = n < model.rows.count ? n : max(model.rows.count, h.most)
            }
            DispatchQueue.main.async { [weak self] in self?.place(force: true) }
        }
        guard done else { return }
        held = nil
        if h.edges.isEmpty {
            spot = NSPoint(x: p.frame.minX, y: p.frame.maxY)
            place(force: true)
        } else {
            UserDefaults.standard.set(Double(model.width), forKey: "cornerWidth")
            UserDefaults.standard.set(model.most, forKey: "cornerRows")
        }
    }

    /// A click on a session: its tab to the front, or a line saying why not.
    private func open(_ r: CornerRow) {
        model.seen(r)
        DispatchQueue.global(qos: .userInitiated).async {
            let res = sh(PY, [ahtScript(), "goto", String(r.pid), "--json"])
            let d = (try? JSONSerialization.jsonObject(with: Data(res.out.utf8))) as? [String: Any]
            guard d?["ok"] as? Bool != true else { return }
            let why = d?["why"] as? String ?? "aht could not bring it to the front"
            DispatchQueue.main.async {
                self.model.say(r.name + ": " + why)
                DispatchQueue.main.async { self.place(force: true) }
            }
        }
    }
}

// ---- chimes ------------------------------------------------------------------

/// aht's own chimes, made here from a few sine waves, so no sound file
/// ships: every note comes from one scale (G major) and starts softly and
/// rings out like a small bell, so two chimes in a row never clash.
enum Chimes {
    /// in the order the menu lists them (the guide says what each sounds like):
    /// the longer ones, then the short ones
    static let long = ["Bloom", "Settle", "Doorbell", "Tap", "Ask", "Ebb", "Drop"]
    static let short = ["Ebb1", "Ebb2", "Ebb3", "Felt", "Hush", "Pluck", "Bubble", "Puff"]
    static let own = long + short
    static let rate = 44100.0
    enum Timbre { case bell, wood, soft, ding, felt, hush, drop, bubble, pluck, puff }

    /// (when it starts in s, its pitch in Hz, how loud)
    private static func score(_ name: String) -> (Timbre, [(Double, Double, Double)]) {
        let G4 = 392.00, B4 = 493.88, D5 = 587.33, G5 = 783.99, B5 = 987.77
        let D6 = 1174.66, G6 = 1567.98
        switch name {
        case "Bloom": return (.bell, [(0, G5, 0.7), (0.075, B5, 0.75), (0.15, D6, 1)])
        case "Settle": return (.bell, [(0, D6, 0.8), (0.13, G5, 1)])
        case "Doorbell": return (.bell, [(0, B5, 1), (0.3, G5, 0.9)])
        case "Tap": return (.wood, [(0, G5, 0.8), (0.13, G5, 1)])
        case "Ask": return (.bell, [(0, D6, 0.85), (0.14, G6, 0.8)])
        case "Ebb": return (.soft, [(0, D5, 1), (0.16, B4, 0.9), (0.32, G4, 0.85)])
        case "Drop": return (.drop, [(0, 880, 1)])
        case "Ebb1": return (.ding, [(0, D5, 1)])        // Ebb's notes, one at a time
        case "Ebb2": return (.ding, [(0, B4, 1)])
        case "Ebb3": return (.ding, [(0, G4, 1)])
        case "Felt": return (.felt, [(0, G4, 1)])
        case "Hush": return (.hush, [(0, B4, 1)])
        case "Pluck": return (.pluck, [(0, G4, 1)])
        case "Bubble": return (.bubble, [(0, 330, 1)])
        case "Puff": return (.puff, [(0, 0, 1)])
        default: return (.bell, [])
        }
    }

    /// the partials of a note: (× its pitch, how loud, how long it rings in
    /// s), its attack in s, how long the chime lasts after its last note,
    /// and how much quieter than the others it is meant to be (in dB)
    private static func voice(_ t: Timbre) -> ([(Double, Double, Double)], Double, Double, Double) {
        switch t {
        case .bell: return ([(1, 1, 0.42), (1.0016, 0.3, 0.5), (2, 0.14, 0.22), (3, 0.04, 0.12),
                             (4.17, 0.05, 0.08), (5.43, 0.02, 0.05)], 0.004, 1.3, 0)
        case .wood: return ([(1, 1, 0.16), (3.93, 0.2, 0.035), (9.2, 0.05, 0.012)], 0.002, 0.55, 0)
        case .soft: return ([(1, 1, 0.45), (2, 0.06, 0.2)], 0.018, 1.2, 0)
        case .ding: return ([(1, 1, 0.075), (2, 0.06, 0.033)], 0.018, 0.2, 0)  // Ebb's, short
        case .felt: return ([(1, 1, 0.09), (2, 0.18, 0.05), (3, 0.05, 0.03)], 0.008, 0.2, 0)
        case .hush: return ([(1, 1, 10), (2, 0.08, 10)], 0.1, 0.2, 0)  // swells, fades, no strike
        case .drop: return ([(1, 1, 0.06)], 0.002, 0.45, 0)
        case .bubble: return ([(1, 1, 0.07)], 0.012, 0.2, 0)
        case .pluck: return ([(1, 1, 0.12)], 0.004, 0.22, 0)
        case .puff: return ([(1, 1, 0.06)], 0.03, 0.22, 5)              // noise sounds louder
        }
    }

    /// One note as it sounds, before its attack is shaped: n samples.
    private static func note(_ t: Timbre, _ hz: Double, _ n: Int,
                             _ partials: [(Double, Double, Double)]) -> [Double] {
        var y = [Double](repeating: 0, count: n)
        var seed: UInt32 = 0x2545F491                   // the same noise every time
        func noise() -> Double {
            seed = seed &* 1664525 &+ 1013904223
            return Double(seed) / 2147483647.5 - 1
        }
        let ring = partials[0].2
        switch t {
        case .drop, .bubble:                            // the pitch leaps up as it dies
            let (leap, quick) = t == .drop ? (0.9, 0.02) : (0.7, 0.04)
            var phase = 0.0
            for i in 0..<n {
                let s = Double(i) / rate
                phase += 2 * Double.pi * hz * (1 + leap * (1 - exp(-s / quick))) / rate
                y[i] = sin(phase) * exp(-s / ring)
            }
        case .pluck:                                    // a soft plucked string (Karplus-Strong)
            let len = max(2, Int((rate / hz).rounded()))
            let keep = exp(-1 / (hz * ring))            // what is left after each round
            var line = [Double](repeating: 0, count: len)
            for k in 0..<len {                          // plucked a third along, softly:
                let u = Double(k) / Double(len)         // its shape, and a little noise
                line[k] = (u < 1 / 3.0 ? u * 3 : (1 - u) * 1.5) - 0.5 + 0.05 * noise()
            }
            var j = 0
            for i in 0..<n {                            // each round a little duller
                y[i] = line[j]
                line[j] = (0.25 * line[(j + len - 1) % len] + 0.5 * line[j]
                           + 0.25 * line[(j + 1) % len]) * keep
                j = (j + 1) % len
            }
        case .puff:                                     // a breath: noise, low and muffled
            var a = 0.0, b = 0.0, last = 0.0, high = 0.0
            for i in 0..<n {
                a += (noise() - a) * 0.11               // two low-passes, about 800 Hz
                b += (a - b) * 0.11
                high = 0.98 * (high + b - last)         // and no rumble below about 140 Hz
                last = b
                y[i] = high * exp(-Double(i) / rate / ring)
            }
        default:
            let slower = (783.99 / hz).squareRoot()     // low notes ring longer
            for i in 0..<n {
                let s = Double(i) / rate
                for (k, a, r) in partials {
                    y[i] += a * exp(-s / (r * slower)) * sin(2 * Double.pi * hz * k * s)
                }
            }
        }
        return y
    }

    static func samples(_ name: String) -> [Float] {
        let (timbre, notes) = score(name)
        guard let lastAt = notes.map({ $0.0 }).max() else { return [] }
        let (partials, attack, tail, quieter) = voice(timbre)
        var x = [Float](repeating: 0, count: Int((lastAt + tail) * rate))
        for (at, hz, gain) in notes {
            let start = Int(at * rate)
            for (i, v) in note(timbre, hz, x.count - start, partials).enumerated() {
                let t = Double(i) / rate
                let rise = t < attack ? 0.5 - 0.5 * cos(Double.pi * t / attack) : 1
                x[start + i] += Float(gain * rise * v)
            }
        }
        if !short.contains(name) { x = room(x) }  // a short one stays dry: the echo would cancel it
        let fade = min(Int(0.25 * rate), x.count / 2)   // the very end goes quiet smoothly
        for i in 0..<fade {
            x[x.count - 1 - i] *= Float(0.5 - 0.5 * cos(Double.pi * Double(i) / Double(fade)))
        }
        // as loud as the sounds of macOS at their loudest moment (50 ms), so a
        // short chime is no louder than a long one; never near clipping
        let win = Int(0.05 * rate)
        var sum: Float = 0, most: Float = 0
        for i in 0..<x.count {
            sum += x[i] * x[i] - (i >= win ? x[i - win] * x[i - win] : 0)
            most = max(most, sum)
        }
        let peak = x.map { abs($0) }.max() ?? 0
        guard most > 0, peak > 0 else { return x }
        let level = Float(0.0891 * pow(10, -quieter / 20))   // -21 dB
        let gain = min(level / (most / Float(win)).squareRoot(), 0.7 / peak)
        return x.map { $0 * gain }
    }

    /// A small room around the notes: four damped combs into two all-passes
    /// (the shape of Freeverb), mixed in quietly.
    private static func room(_ x: [Float]) -> [Float] {
        var wet = [Float](repeating: 0, count: x.count)
        for n in [1116, 1188, 1277, 1356] {
            var buf = [Float](repeating: 0, count: n), i = 0, low: Float = 0
            for t in 0..<x.count {
                let out = buf[i]
                low = out * 0.6 + low * 0.4
                buf[i] = x[t] + low * 0.55
                wet[t] += out
                i = (i + 1) % n
            }
        }
        for n in [556, 441] {
            var buf = [Float](repeating: 0, count: n), i = 0
            for t in 0..<wet.count {
                let b = buf[i]
                buf[i] = wet[t] + b * 0.5
                wet[t] = b - wet[t]
                i = (i + 1) % n
            }
        }
        return zip(x, wet).map { $0 + $1 * 0.08 }
    }

    /// The chime as a WAV file (16-bit, mono).
    static func wav(_ name: String) -> Data? {
        let s = samples(name)
        guard !s.isEmpty else { return nil }
        var d = Data()
        func u32(_ v: UInt32) { withUnsafeBytes(of: v.littleEndian) { d.append(contentsOf: $0) } }
        func u16(_ v: UInt16) { withUnsafeBytes(of: v.littleEndian) { d.append(contentsOf: $0) } }
        d.append(contentsOf: Array("RIFF".utf8)); u32(UInt32(36 + s.count * 2))
        d.append(contentsOf: Array("WAVEfmt ".utf8)); u32(16); u16(1); u16(1)
        u32(UInt32(rate)); u32(UInt32(rate) * 2); u16(2); u16(16)
        d.append(contentsOf: Array("data".utf8)); u32(UInt32(s.count * 2))
        for v in s { u16(UInt16(bitPattern: Int16(max(-1, min(1, v)) * 32767))) }
        return d
    }
}

/// The chime each event plays until you pick another.
let CHIME_DEFAULTS = ["chime_done": "Bloom", "chime_waiting": "Doorbell", "chime_limit": "Ebb"]

/// Plays what a chime setting names: one of aht's own chimes, a sound of
/// macOS or of ~/Library/Sounds by its name, or a sound file by its path.
/// "" plays nothing.
final class ChimePlayer {
    static let shared = ChimePlayer()
    private var sounds: [String: NSSound] = [:]
    private var last = Date.distantPast

    /// The sounds of macOS and your own, by name; one named like an aht
    /// chime is left out (aht's own come first).
    static func soundNames() -> [String] {
        var names = Set<String>()
        for d in [HOME + "/Library/Sounds", "/Library/Sounds", "/System/Library/Sounds"] {
            for f in (try? FileManager.default.contentsOfDirectory(atPath: d)) ?? []
            where ["aiff", "aif", "wav", "caf", "mp3", "m4a"]
                .contains((f as NSString).pathExtension.lowercased()) {
                names.insert((f as NSString).deletingPathExtension)
            }
        }
        return names.subtracting(Chimes.own)
            .sorted { $0.localizedCaseInsensitiveCompare($1) == .orderedAscending }
    }

    /// What the menu shows for a setting: a file by its name.
    static func label(_ choice: String) -> String {
        choice.isEmpty ? "None" : choice.contains("/")
            ? ((choice as NSString).lastPathComponent as NSString).deletingPathExtension : choice
    }

    private func sound(_ choice: String) -> NSSound? {
        if let s = sounds[choice] { return s }
        var s: NSSound?
        if Chimes.own.contains(choice) {
            s = Chimes.wav(choice).flatMap { NSSound(data: $0) }
        } else if choice.contains("/") {
            s = NSSound(contentsOf: URL(fileURLWithPath: (choice as NSString).expandingTildeInPath),
                        byReference: true)
        } else if !choice.isEmpty {
            s = NSSound(named: NSSound.Name(choice))?.copy() as? NSSound
        }
        sounds[choice] = s
        return s
    }

    /// Plays it at `volume` (0–100). Unless `now` (one picked in Settings),
    /// a second must have passed since the last chime, so sessions that
    /// finish together make one chime, not a chord.
    @discardableResult
    func play(_ choice: String, volume: Int, now: Bool = false) -> Bool {
        guard now || Date().timeIntervalSince(last) > 1, let s = sound(choice) else { return false }
        if s.isPlaying { s.stop() }
        s.volume = Float(max(0, min(100, volume))) / 100
        last = Date()
        return s.play()
    }
}

// ---- the app -------------------------------------------------------------------

let NOTICE_QUEUE = HOME + "/.aht/run/app-notices.jsonl"

final class TrayApp: NSObject, NSApplicationDelegate, NSMenuDelegate, NSWindowDelegate,
                     UNUserNotificationCenterDelegate {
    var item: NSStatusItem!
    let menu = NSMenu()
    let model = AppModel()
    let corner = CornerPanel()
    var window: NSWindow?

    func applicationDidFinishLaunching(_ n: Notification) {
        // with no window open macOS takes the app for idle and quits it
        // ("automatic termination"); the menu bar app is meant to stay
        ProcessInfo.processInfo.disableAutomaticTermination("aht lives in the menu bar")
        item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        // the aht mark: a loop with no loose end (template = follows the bar's theme)
        let img = NSImage(systemSymbolName: "infinity",
                          accessibilityDescription: "aht")
        img?.isTemplate = true
        item.button?.image = img
        item.button?.toolTip = "agent-history-tether"
        menu.delegate = self
        item.menu = menu
        model.onChange = { [weak self] in
            self?.updateIcon()
            self?.syncCorner()
        }
        corner.onHide = { [weak self] in
            self?.model.set("session_corner", "false")
        }
        model.offerSetup = { [weak self] in self?.offerGettingStarted() }
        model.openWelcome = { [weak self] in self?.showWelcome() }
        model.openWelcomeFirst = { [weak self] version in
            self?.showWelcome(declining: version)
        }
        corner.model.onNews = { [weak self] news in
            if news.contains(where: { $0.kind == "waiting" }) {
                self?.chime("waiting")
            } else if let w = news.map({ $0.worked }).max() {
                self?.chime("done", worked: w)
            }
        }
        model.refresh { self.offerGettingStarted() }
        Timer.scheduledTimer(withTimeInterval: 20, repeats: true) { _ in
            self.model.refresh()
        }
        // the iTerm2 layout, for Restore Workspace (the core keeps the pace)
        Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { _ in
            self.model.autosaveWorkspace()
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
            self.model.offerInstallIfNeeded()
            self.hotkey = self.model.text("hotkey", "ctrl+opt+cmd+a")
            registerHotKey(self.hotkey) { self.quickSearch() }
        }
        // Finder: right-click a folder → Quick Actions / Services → aht: …
        NSApp.servicesProvider = self
        NSUpdateDynamicServices()
        // notices: while the app runs it shows them itself, so a click on one
        // goes to the session (the core hands them over through a file)
        UNUserNotificationCenter.current().delegate = self
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }
        noticeOffset = (try? FileManager.default.attributesOfItem(atPath: NOTICE_QUEUE)[.size]
                        as? NSNumber)?.uint64Value ?? 0
        Timer.scheduledTimer(withTimeInterval: 3, repeats: true) { _ in self.pumpNotices() }
        pumpNotices()
        // Spotlight: session titles, refreshed every half hour
        DispatchQueue.main.asyncAfter(deadline: .now() + 15) { self.model.indexSpotlight() }
        Timer.scheduledTimer(withTimeInterval: 1800, repeats: true) { _ in
            self.model.indexSpotlight()
        }
    }

    /// Getting started, once: when a main step is still to do, the window
    /// opens with the list (after the app set aht up, or at the first start
    /// of a version that has it). After that it is in Settings.
    func offerGettingStarted() {
        let d = UserDefaults.standard
        guard model.loaded, FileManager.default.fileExists(atPath: TOOLS + "/aht.py") else { return }
        // installed from a terminal (`aht install`) and never set up: welcome
        if !d.bool(forKey: "welcomeShown"), !(model.status["setup_done"] as? Bool ?? true),
           (model.status["tracked"] as? Int ?? 0) <= 2 {
            d.set(true, forKey: "welcomeShown")
            showWelcome()
            return
        }
        guard !d.bool(forKey: "gettingStartedShown"), !model.setupSteps.isEmpty else { return }
        d.set(true, forKey: "gettingStartedShown")
        if model.setupMissing { showGettingStarted() }
    }

    var welcomeWindow: NSWindow?
    var welcome: WelcomeModel?
    var welcomeDeclining: String?

    /// The welcome window: Quick Setup or each step, then Getting started.
    /// While the core is not installed on this Mac, it installs it from this
    /// app first (also from Run Setup Again); closed before that is done, the
    /// offer waits for the next version of the app (`declining`).
    func showWelcome(declining: String? = nil) {
        let w = WelcomeModel()
        w.install = BUNDLE_RES != nil && !FileManager.default.fileExists(atPath: TOOLS + "/aht.py")
        // start at login: on the first time; once the question was answered
        // (the switch in Settings: status's autostart.answered) or setup was
        // done, as it is set now (also when an aht://setup link opens this
        // before the status is in)
        w.answered = (model.status["autostart"] as? [String: Any])?["answered"] as? Bool ?? false
        w.asked = !w.install && (w.answered || (model.status["setup_done"] as? Bool ?? true))
        w.login = !w.asked || model.loginItem
        w.loginStart = w.login
        w.close = { [weak self] in self?.welcomeWindow?.close() }
        welcome = w
        welcomeDeclining = declining
        if welcomeWindow == nil {
            let win = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 640, height: 580),
                               styleMask: [.titled, .closable], backing: .buffered, defer: false)
            win.title = "Welcome to aht"
            win.isReleasedWhenClosed = false
            win.delegate = self                 // the close box declines too
            welcomeWindow = win
        }
        welcomeWindow?.contentView = NSHostingView(rootView: WelcomeView(w: w).environmentObject(model))
        welcomeWindow?.center()
        welcomeWindow?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        w.load(first: true)
    }

    @objc func showUpdateFromMenu() {
        openWindow()
        model.showUpdate = true
    }

    func showGettingStarted() {
        openWindow()
        model.tab = .settings
        model.showGettingStarted = true
    }

    // aht://… links (Shortcuts, scripts, a note): registered before launch
    // finishes, so the link that started the app is not missed
    func applicationWillFinishLaunching(_ n: Notification) {
        UNUserNotificationCenter.current().delegate = self
        NSAppleEventManager.shared().setEventHandler(
            self, andSelector: #selector(handleURL(_:reply:)),
            forEventClass: AEEventClass(kInternetEventClass), andEventID: AEEventID(kAEGetURL))
    }

    @objc func handleURL(_ event: NSAppleEventDescriptor, reply: NSAppleEventDescriptor) {
        guard let s = event.paramDescriptor(forKeyword: keyDirectObject)?.stringValue,
              let u = URLComponents(string: s) else { return }
        var q: [String: String] = [:]
        for i in u.queryItems ?? [] { q[i.name] = i.value ?? "" }
        route(((u.host ?? "") + u.path).trimmingCharacters(in: CharacterSet(charactersIn: "/")), q)
    }

    /// Opens a part of the window; whatever starts an agent or changes files
    /// asks first, so a link can never do that on its own.
    func route(_ what: String, _ q: [String: String]) {
        func withProject(_ then: @escaping (Project) -> Void) {
            openWindow()
            model.tab = .projects
            guard let raw = q["path"], !raw.isEmpty else { return }
            let real = URL(fileURLWithPath: (raw as NSString).expandingTildeInPath)
                .resolvingSymlinksInPath().path
            model.refresh {
                guard let p = self.model.projects.first(where: { $0.path == real }) else {
                    _ = alert("aht does not track this folder", real)
                    return
                }
                self.model.selection = p.path
                then(p)
            }
        }
        switch what {
        case "search":
            openWindow()
            model.tab = .search
            if let w = q["q"], !w.isEmpty {
                model.query = w
                model.runSearch()
            } else {
                model.focusSearch += 1
            }
        case "sessions", "board":
            openWindow()
            model.tab = .sessions
        case "getting-started":
            showGettingStarted()
        case "welcome", "setup":
            showWelcome()
        case "update":
            showUpdateFromMenu()
        case "loose-ends":
            openWindow()
            model.openLooseEnds()
        case "report":
            openWindow()
            model.showReport = true
            model.loadReport()
        case "project": withProject { _ in }
        case "changes": withProject { self.model.openChanges($0) }
        case "journal": withProject { self.model.journal($0) }
        case "undo": withProject { self.model.openUndo($0) }
        case "switch":
            withProject { p in
                guard let ask = switchLink(q) else { return }
                if ask.back {
                    self.model.handBack(p, to: ask.to)
                } else if let to = ask.to {
                    self.model.switchAgent(p, to: to, resume: ask.resume)
                }
            }
        case "resume":
            if let path = q["path"], let sid = q["session"], !sid.isEmpty {
                continueFromOutside(agent: q["agent"] ?? "claude", session: sid,
                                    project: (path as NSString).expandingTildeInPath)
            }
        default:
            openWindow()
        }
    }

    /// A session picked in Spotlight or by a link: offer to continue it.
    func continueFromOutside(agent: String, session: String, project: String) {
        openWindow()
        model.tab = .projects
        model.selection = project
        let label = AGENT_LABEL[agent] ?? agent
        if alert("Continue this \(label) session?",
                 "It opens in a new terminal window, in “\((project as NSString).lastPathComponent)”.",
                 confirm: "Continue") {
            model.resumeSession(project, agent: agent, session: session)
        }
    }

    func application(_ application: NSApplication, continue userActivity: NSUserActivity,
                     restorationHandler: @escaping ([NSUserActivityRestoring]) -> Void) -> Bool {
        guard userActivity.activityType == CSSearchableItemActionType,
              let key = userActivity.userInfo?[CSSearchableItemActivityIdentifier] as? String
        else { return false }
        let parts = key.components(separatedBy: "\t")
        guard parts.count == 3 else { return false }
        continueFromOutside(agent: parts[0], session: parts[1], project: parts[2])
        return true
    }

    /// The ∞ carries the number of sessions that wait for you.
    func updateIcon() {
        let n = model.waiting
        item.button?.imagePosition = .imageLeft
        item.button?.title = n > 0 ? " \(n)" : ""
        var tip = ["agent-history-tether"]
        if n > 0 { tip.append("\(n) session\(n == 1 ? "" : "s") waiting for you") }
        for p in model.limited { tip.append("\(p.name): Claude's usage limit") }
        item.button?.toolTip = tip.joined(separator: "\n")
    }

    var hotkey = ""
    var noticeOffset: UInt64 = 0

    /// Marks the app alive for the core, and shows the notices it queued.
    func pumpNotices() {
        let run = HOME + "/.aht/run"
        try? FileManager.default.createDirectory(atPath: run, withIntermediateDirectories: true)
        FileManager.default.createFile(atPath: run + "/app-alive", contents: Data())
        guard let fh = FileHandle(forReadingAtPath: NOTICE_QUEUE) else { return }
        defer { try? fh.close() }
        let size = fh.seekToEndOfFile()
        if size < noticeOffset { noticeOffset = 0 }          // the file was started anew
        guard size > noticeOffset else { return }
        fh.seek(toFileOffset: noticeOffset)
        let data = fh.readDataToEndOfFile()
        noticeOffset = size
        for line in (String(data: data, encoding: .utf8) ?? "").split(separator: "\n") {
            guard let d = line.data(using: .utf8),
                  let n = (try? JSONSerialization.jsonObject(with: d)) as? [String: Any] else { continue }
            let c = UNMutableNotificationContent()
            c.title = n["title"] as? String ?? "aht"
            c.body = n["message"] as? String ?? ""
            c.sound = .default
            let info = n["info"] as? [String: Any] ?? [:]
            c.userInfo = info.compactMapValues { $0 is NSNull ? nil : $0 }
            // with chimes on, a notice they cover comes without its own sound:
            // a session here chimed already, one elsewhere and the limit now
            if model.flag("chimes", false),
               let k = ["waiting": "waiting", "finished": "done", "limit": "limit"][
                   info["kind"] as? String ?? ""] {
                c.sound = nil
                if !(info["local"] as? Bool ?? false) { chime(k) }
            }
            let req = UNNotificationRequest(identifier: UUID().uuidString, content: c, trigger: nil)
            UNUserNotificationCenter.current().add(req) { err in
                if err != nil { notifyUser(c.title, c.body) }   // not allowed: the plain kind
            }
        }
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent n: UNNotification,
                                withCompletionHandler done: @escaping (UNNotificationPresentationOptions) -> Void) {
        done([.banner, .sound])
    }

    /// A click on a notice: to the session's tab when it is here, else to the
    /// Sessions tab (another machine) or the project (the usage limit, a
    /// handover that was cut off).
    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive r: UNNotificationResponse,
                                withCompletionHandler done: @escaping () -> Void) {
        let info = r.notification.request.content.userInfo
        let kind = info["kind"] as? String ?? ""
        DispatchQueue.main.async {
            if (kind == "waiting" || kind == "finished"), info["local"] as? Bool ?? false,
               let pid = info["pid"] as? Int {
                DispatchQueue.global(qos: .userInitiated).async {
                    let res = sh(PY, [ahtScript(), "goto", String(pid)])
                    if !res.ok {
                        DispatchQueue.main.async {
                            self.openWindow()
                            self.model.tab = .sessions
                        }
                    }
                }
            } else if kind == "update" {
                self.showUpdateFromMenu()
            } else if kind == "limit" || kind == "handover", let p = info["project"] as? String {
                self.openWindow()
                self.model.tab = .projects
                self.model.selection = p
            } else {
                self.openWindow()
                self.model.tab = .sessions
            }
        }
        done()
    }

    func quickSearch() {
        openWindow()
        model.tab = .search
        model.focusSearch += 1
    }

    /// A folder handed over by a Finder service: select its project (tracking
    /// it first if aht does not know it yet), then do what was asked.
    func fromFinder(_ pboard: NSPasteboard, _ then: @escaping (Project) -> Void) {
        let urls = (pboard.readObjects(forClasses: [NSURL.self],
                                       options: [.urlReadingFileURLsOnly: true]) as? [URL]) ?? []
        guard let url = urls.first else { return }
        let path = url.resolvingSymlinksInPath().path
        openWindow()
        model.tab = .projects
        let go = {
            guard let p = self.model.projects.first(where: { $0.path == path }) else { return }
            self.model.selection = p.path
            then(p)
        }
        if model.projects.contains(where: { $0.path == path }) {
            go()
            return
        }
        guard alert("aht does not track “\(url.lastPathComponent)” yet",
                    "Track it, so aht keeps its agents' history with it?", confirm: "Track It")
        else { return }
        model.background { aht(["tag", path, "--apply"]) }
        DispatchQueue.main.asyncAfter(deadline: .now() + 2.0) { self.model.refresh { go() } }
    }

    @objc func serviceShow(_ pboard: NSPasteboard, userData: String?,
                           error: AutoreleasingUnsafeMutablePointer<NSString?>) {
        fromFinder(pboard) { _ in }
    }
    @objc func serviceChanges(_ pboard: NSPasteboard, userData: String?,
                              error: AutoreleasingUnsafeMutablePointer<NSString?>) {
        fromFinder(pboard) { self.model.openChanges($0) }
    }
    @objc func serviceJournal(_ pboard: NSPasteboard, userData: String?,
                              error: AutoreleasingUnsafeMutablePointer<NSString?>) {
        fromFinder(pboard) { self.model.journal($0) }
    }
    @objc func serviceSearch(_ pboard: NSPasteboard, userData: String?,
                             error: AutoreleasingUnsafeMutablePointer<NSString?>) {
        fromFinder(pboard) { p in
            self.model.searchProject = p.path
            self.model.tab = .search
            self.model.focusSearch += 1
        }
    }
    @objc func serviceSwitch(_ pboard: NSPasteboard, userData: String?,
                             error: AutoreleasingUnsafeMutablePointer<NSString?>) {
        fromFinder(pboard) { p in
            let items = switchItems(p, self.model.agentCLIs)
            let pick = choose("Continue “\(p.name)” in another agent?",
                              "The agent reads a summary of where the work stood first.",
                              items.map { String($0.title.dropLast()) } + ["Cancel"])
            guard pick >= 0 && pick < items.count else { return }
            if items[pick].back {
                self.model.handBack(p)
            } else {
                self.model.switchAgent(p, to: items[pick].to)
            }
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
        for p in model.projects where p.handing != nil && p.handing?.state != "running" {
            add(disabled: "⚠ \(p.name): the handover to \(p.handing?.machine ?? "") is unfinished")
        }
        if let v = model.newVersion {
            add("aht \(v) is out — What's New…", #selector(showUpdateFromMenu))
        }
        add("Search Sessions…", #selector(searchFromMenu))
        add("Sessions in the Corner", #selector(toggleCorner))
        menu.items.last?.state = model.flag("session_corner", false) ? .on : .off
        add("Chimes", #selector(toggleChimes))
        menu.items.last?.state = model.flag("chimes", false) ? .on : .off
        if model.waiting > 0 {
            add(disabled: "⚠ \(model.waiting) session\(model.waiting == 1 ? "" : "s") "
                + "waiting for you")
        }
        for p in model.limited.prefix(3) {
            add(disabled: "⏸ \(p.name): Claude's usage limit"
                + (p.limitResets.map { ", resets " + $0 } ?? ""))
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

    @objc func toggleCorner() {
        model.set("session_corner", model.flag("session_corner", false) ? "false" : "true")
    }

    @objc func toggleChimes() {
        model.set("chimes", model.flag("chimes", false) ? "false" : "true")
    }

    /// The corner shows while the setting is on; the sessions are watched
    /// while it shows or the chimes are on.
    func syncCorner() {
        let roots = (model.status["backends"] as? [[String: Any]]) ?? []
        let root = roots.first { $0["name"] as? String == "claude" }?["root"] as? String
        let dir = root.map {
            (($0 as NSString).deletingLastPathComponent as NSString)
                .appendingPathComponent("sessions")
        } ?? HOME + "/.claude/sessions"
        if model.flag("session_corner", false) {
            if !corner.shown { corner.show(sessionsDir: dir) }
        } else if corner.shown {
            corner.hide()
        }
        corner.model.sessionsDir = dir
        corner.listening = model.flag("chimes", false)
    }

    /// A session here is done or began waiting for you, or a notice came in:
    /// its chime, when the chimes are on and one is set for it. "Done" only
    /// after a piece of work that took a while (`chime_done_after`).
    func chime(_ kind: String, worked: Double = .infinity) {
        let key = "chime_" + kind
        guard model.flag("chimes", false), let fallback = CHIME_DEFAULTS[key],
              kind != "done" || worked >= Double(model.number("chime_done_after", 30))
        else { return }
        ChimePlayer.shared.play(model.text(key, fallback), volume: model.number("chime_volume", 70))
    }
    @objc func toggleWatch() { model.toggleWatch() }
    @objc func quit() { NSApp.terminate(nil) }

    @objc func searchFromMenu() { quickSearch() }

    @objc func openGuide() {
        showGuideWindow(nil)
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
        if model.tab == .machines { model.discover() }     // shown again on that tab
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func windowWillClose(_ n: Notification) {
        if let win = n.object as? NSWindow, win === welcomeWindow {
            if let v = welcomeDeclining, !(welcome?.finished ?? false) {
                UserDefaults.standard.set(v, forKey: "declinedSetup")
            }
            return
        }
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
    let bad = Chimes.own.filter { n in                // each chime sounds, softly, no click
        let s = Chimes.samples(n), peak = s.map { abs($0) }.max() ?? 0
        return s.count < 4410 || peak < 0.05 || peak > 0.75 || abs(s[0]) > 0.01
            || abs(s[s.count - 1]) > 0.01
    }
    print("CHIMES \(bad.isEmpty ? "OK" : "FAIL \(bad)") — \(Chimes.own.count) made")
    // the bundle's own core: the installed one may be older
    let core = BUNDLE_RES.map { $0 + "/aht.py" } ?? ahtScript()
    let gs = sh(PY, [core, "getting-started", "--json"]).out
    let steps = ((try? JSONSerialization.jsonObject(with: Data(gs.utf8))) as? [String: Any])?["steps"]
        as? [[String: Any]] ?? []
    let setupOK = steps.contains { $0["id"] as? String == "iterm" }
    print("GETTING STARTED \(setupOK ? "OK" : "FAIL") — \(steps.count) steps, "
          + "control of iTerm2: \(itermControlState(ask: false))")
    // stdout and stderr apart (the welcome's setup), neither stuck behind the other
    let two = shWithStderr(PY, ["-c", "import sys; sys.stderr.write('e' * 200000); print('{}')"])
    let apartOK = two.ok && two.out == "{}\n" && two.err.count == 200000
    print("STDERR APART \(apartOK ? "OK" : "FAIL")")
    // the login item's plist: an app path with & and < in it reads back as it was
    let odd = "/Users/a&b/Tools & <Apps>/aht.app/Contents/MacOS/aht-tray"
    let back = loginItemPlist(odd).flatMap {
        try? PropertyListSerialization.propertyList(from: $0, format: nil) } as? [String: Any]
    let plistOK = back?["Label"] as? String == TRAY_LABEL
        && back?["ProgramArguments"] as? [String] == [odd] && back?["RunAtLoad"] as? Bool == true
    print("LOGIN ITEM PLIST \(plistOK ? "OK" : "FAIL")")
    // Tidy Up offers no Remove… for a link (`"link": true`), and the welcome
    // leaves a project aht was told to forget unticked (`"forgotten": true`)
    let rows = tidyItems(["orphans": [["store": "-x-link", "link": true], ["store": "-x-gone"]]])
    let picks = projectChoices(["projects": [["path": "/x/old", "forgotten": true], ["path": "/x/new"]]])
    let marksOK = rows.map { $0.link } == [true, false] && picks.map { $0.chosen } == [false, true]
    print("TIDY LINKS AND FORGOTTEN PROJECTS \(marksOK ? "OK" : "FAIL")")
    // the adopt question names up to three forgotten folders, then how many more
    let gone = { (n: Int) in (0..<n).map { ["real": "/x/p\($0)", "forgotten": true] as [String: Any] } }
    let notes = [forgottenNote([["real": "/x/new"]]), forgottenNote(gone(1)), forgottenNote(gone(2)),
                 forgottenNote(gone(5) + [["real": "/x/new"]])]
    let namesOK = notes[0].isEmpty
        && notes[1] == "You told aht to forget /x/p0: adopting takes it on again."
        && notes[2].hasPrefix("You told aht to forget /x/p0 and /x/p1: adopting takes them")
        && notes[3].hasPrefix("You told aht to forget /x/p0, /x/p1, /x/p2 and 2 more:")
    print("FORGOTTEN FOLDERS NAMED \(namesOK ? "OK" : "FAIL \(notes)")")
    // an unfinished handover (`projects --json`'s `handing`): the banner's
    // state, and Release's question from `reclaim --release --json`
    let iso = { (t: Date) -> String in
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        return f.string(from: t)
    }
    let t = Date().timeIntervalSince1970
    let rec: [String: Any] = ["attempt": "20261026-010000-ab12", "step": "starting",
                              "remote": "box", "host": "box.local",
                              "since": iso(Date(timeIntervalSince1970: t - 4000)),
                              "error": "ssh: connect timed out", "checked_at": t,
                              "unreachable_since": t - 3700, "state": "unreachable", "release": true]
    let late = Project(["real_path": "/x/api", "exists": true, "handing": rec])
    let young = Project(["real_path": "/x/api", "exists": true, "handing": rec.merging(
        ["state": "checking", "unreachable_since": NSNull(), "release": false]) { $1 }])
    let plain = Project(["real_path": "/x/api", "exists": true, "handing": NSNull()])
    let lose = { (files: Any, history: Any?) -> [String: Any] in
        ["released": false, "remote": "box", "would_lose": ["files": files, "since": rec["since"]!]
            .merging(history.map { ["history": $0] } ?? [:]) { $1 }]
    }
    let ask = releaseText(lose(3, 0), "box", away: false)
    let none = releaseText(lose(0, 0), "box", away: true)
    let unknown = releaseText(lose(NSNull(), NSNull()), "box", away: false)
    // the conversation went on there: something stays, even with no file changed
    let talked = releaseText(lose(0, 4), "box", away: false)
    let both = releaseText(lose(["src/a.py"], true), "box", away: false, sync: true)
    let older = releaseText(lose(0, nil), "box", away: false)     // a core without `history`
    let releaseOK = ask.contains("\n\n3 files stay there.") && !ask.contains("conversation")
        && !talked.contains("Nothing changed") && talked.contains("\n\nThe conversation stays there.")
        && both.contains("1 file and the conversation stay there:\n• src/a.py")
        && both.contains("Release pauses Keep in sync with box, so the copy there stays as it is")
        && !ask.contains("Keep in sync") && !older.contains("Nothing changed")
        && !unknown.contains("stay there") && !unknown.contains("stays there")
    // Keep in sync paused by Release (`projects --json`'s `mirror_paused`)
    let paused = Project(["real_path": "/x/api", "exists": true, "mirror": "box",
                          "mirror_paused": ["reason": "released", "at": rec["since"]!, "remote": "box"]])
    let syncing = Project(["real_path": "/x/api", "exists": true, "mirror": "box",
                           "mirror_synced_at": t, "mirror_status": "ok", "mirror_paused": NSNull()])
    let pauseOK = paused.syncPaused?.reason == "released" && paused.syncPaused?.machine == "box"
        && paused.syncPaused?.at != nil && paused.sync == "paused"
        && syncing.syncPaused == nil && syncing.sync == "just now"
    print("RELEASE TEXTS AND PAUSED SYNC \(releaseOK && pauseOK ? "OK" : "FAIL — \(ask) / \(talked) / \(both) / \(older)")")
    // Turn Sync Back On: the note is what `mirror --on` answered and the row
    // after it says, not what was expected
    let backOn = [resumedText("box", ok: true, out: "mirroring on: /x/api", err: "", now: syncing),
                  resumedText("box", ok: true, out: "", err: "", now: paused),
                  resumedText("box", ok: false, out: "", err: "no machine called box\n", now: paused),
                  resumedText("box", ok: false, out: " ", err: "", now: nil)]
    let backOnOK = backOn[0] == "Kept in sync with box again; the next copy runs in the background."
        && backOn[1] == "The sync with box did not come back on; see the log (Settings)."
        && backOn[2] == "The sync was not turned back on:\n\nno machine called box"
        && backOn[3].hasSuffix("aht gave no answer — see the log (Settings).")
    print("TURN SYNC BACK ON \(backOnOK ? "OK" : "FAIL — \(backOn)")")
    let gave = handingNote("api", late.handing!, after: plain, checked: [])
    let told = handingNote("api", late.handing!, after: late,
                           checked: ["Handover of api to box finished: the session there runs"])
    let handingOK = late.handing?.machine == "box" && late.handing?.state == "unreachable"
        && late.handing?.release == true && late.handing?.silentSince != nil
        && young.handing?.state == "checking" && young.handing?.release == false
        && plain.handing == nil && late.place == "handing over to box"
        && ask.hasPrefix("The work done on box since ") && ask.contains("3 files stay there")
        && !ask.contains("Take Back") && none.hasPrefix("Nothing changed on box since ")
        && none.contains("Take Back") && !unknown.contains("stay there")
        && gave.contains("did not finish") && told.hasPrefix("Handover of api to box finished")
    print("UNFINISHED HANDOVER \(handingOK ? "OK" : "FAIL — \(ask) / \(none) / \(gave)")")
    // the fetch sheet (`backup --offsite-list --json`): each computer's folder,
    // another computer's newest picked first
    let listed = offsiteFolders(["remote": "box", "folders": [
        ["id": "a1b2c3d4e5f6", "folder": "a1b2c3d4e5f6", "name": "studio", "system": "Darwin",
         "updated": iso(Date()), "projects": 4, "files": 12, "bytes": 3_000_000, "mine": true,
         "legacy": false],
        ["id": "0f9e8d7c6b5a", "folder": "0f9e8d7c6b5a", "name": "old-mac", "system": "Darwin",
         "updated": iso(Date().addingTimeInterval(-86400)), "projects": 9, "files": 40,
         "bytes": 90_000_000, "mine": false, "legacy": false],
        ["id": NSNull(), "folder": "laptop", "name": "laptop", "system": NSNull(),
         "updated": NSNull(), "projects": 1, "files": 2, "bytes": 1000, "mine": false,
         "legacy": true]]])
    let fetched = fetchedText(["machine": "box", "from": ["id": "0f9e8d7c6b5a", "name": "old-mac"],
                               "files": 5, "bytes": 2048, "pulled": true,
                               "renamed": ["p1/20261020-0900.zip", "p1/20261020-0900.meta.json"]],
                              listed[1], said: "")
    let offsiteOK = listed.map { $0.id } == ["a1b2c3d4e5f6", "0f9e8d7c6b5a", "laptop"]
        && firstPick(listed) == "0f9e8d7c6b5a" && listed[0].detail.hasPrefix("macOS · updated")
        && listed[2].detail.hasPrefix("from an older aht · 1 project · 2 backups")
        && fetched.hasPrefix("Fetched 5 backup(s)") && fetched.contains("; 1 differed")
        && fetchedText(nil, listed[1], said: "box did not answer\n")
            == "Nothing was fetched: box did not answer"
    print("BACKUPS FROM ANOTHER MACHINE \(offsiteOK ? "OK" : "FAIL")")
    // agents on one machine: agy in the menu (`status --json`'s `agent_clis`),
    // an open relay (`projects --json`'s `relay`) as the line under the
    // project with Hand Back first, the switch dialog from `switch --json`
    let clis = switchAgents(["agent_clis": ["claude": "/x/claude", "codex": NSNull(), "agy": "/x/agy",
                                            "kimi": "/x/kimi"]])
    let since = Calendar.current.date(bySettingHour: 0, minute: 10, second: 0, of: Date())!
    let relayRow = { (extra: [String: Any]) in
        Project(["real_path": "/x/api", "exists": true, "sessions": 3, "agents": ["claude", "codex"],
                 "relay": (["id": "20261026-153012-k3f9", "from_agent": "claude", "to_agent": "codex",
                            "since": since.timeIntervalSince1970, "open": true,
                            "incoming": false] as [String: Any]).merging(extra) { $1 }])
    }
    let taken = relayRow([:]), arrived = relayRow(["incoming": true])
    let menu = switchItems(taken, clis), plainMenu = switchItems(arrived, clis)
    let line = taken.handBack.map(relayLine) ?? ""
    let relayOK = clis == ["claude", "kimi", "agy"]
        && menu.map { $0.title } == ["Hand Back to Claude Code (its own session)…",
                                     "Continue in Claude Code…", "Continue in Kimi Code…",
                                     "Continue in Antigravity…"]
        && menu[0].back && menu[0].to == "claude" && !plainMenu[0].back && arrived.handBack == nil
        && line == "Codex has had this project since \(clock(since)), taken over from Claude Code"
        && Project(["real_path": "/x/api", "relay": NSNull()]).relay == nil
    print("RELAY LINE AND SWITCH MENU \(relayOK ? "OK" : "FAIL — \(clis) / \(menu.map { $0.title }) / \(line)")")
    let src: [String: Any] = ["agent": "claude", "session": "0f3a", "title": "fix the login redirect"]
    let dryNew = switchText(["command": "switch", "applied": false, "blockers": [], "warnings": [
        "Codex is still open in this folder; don't type into both"], "source": src, "target": "codex",
        "relay": NSNull(), "mode": "new", "start_line": "codex 'Read .aht/handover/relay-1.md first'",
        "fallback": NSNull()], mode: "new", hook: true)
    let dryOwn = switchText(["source": src, "target": "agy", "mode": "resume", "warnings": [],
                             "fallback": "Antigravity's own session is gone: a new session reads "
                                + "the full summary and what changed."], mode: "resume", hook: true)
    let dryBack = switchText(["source": ["agent": "codex", "session": "019a", "title": NSNull()],
                              "target": "claude", "mode": "back", "warnings": [], "fallback": NSNull()],
                             mode: "back", hook: true)
    let wrote = switchDoneText(["applied": true, "mode": "brief-only", "target": "agy",
                                "brief": "/x/api/.aht/handover/relay-1.md", "start_line": NSNull(),
                                "warnings": [], "fallback": NSNull()], project: "/x/api")
    let wroteName = switchDoneText(["applied": true, "mode": "brief-only", "target": "kimi",
                                    "brief": "relay-2.md"], project: "/x/api")
    let fellBack = switchDoneText(["applied": true, "mode": "back", "target": "claude",
                                   "brief": "/x/api/.aht/handover/relay-3.md",
                                   "fallback": "That session is gone: a new one reads the full summary."],
                                  project: "/x/api")
    let link = [switchLink(["path": "/x/api", "to": "agy", "back": "1", "resume": "1"]),
                switchLink(["path": "/x/api", "to": "kimi"]),
                switchLink(["path": "/x/api", "to": "codex", "resume": "1"]),
                switchLink(["path": "/x/api", "back": "1"]),
                switchLink(["path": "/x/api", "to": "somebody"])]
    let dialogOK = dryNew.hasPrefix("Codex continues the work of the latest Claude Code session "
                                    + "(“fix the login redirect”) in a new session.")
        && dryNew.contains("\n\n⚠ Codex is still open in this folder") && !dryNew.contains("<null>")
        && dryOwn.hasPrefix("Antigravity goes on in its own latest session here.")
        && dryOwn.contains("\n\nAntigravity's own session is gone: a new session reads")
        && dryBack.hasPrefix("Claude Code goes on in its own session, where it left off.")
        && dryBack.contains("while Codex had the project:")
        && dryBack.contains("nothing runs until you type")
        && !switchText(["source": src, "target": "claude", "mode": "back"], mode: "back", hook: false)
            .contains("nothing runs until you type")
        && wrote.hasPrefix("The summary is written: /x/api/.aht/handover/relay-1.md. Nothing was opened")
        && wroteName.contains("/x/api/.aht/handover/relay-2.md")
        && fellBack.hasPrefix("That session is gone: a new one reads the full summary.\n\nClaude Code "
                              + "took over; its window is open.")
        && link[0]?.back == true && link[0]?.to == "agy"
        && link[1]?.back == false && link[1]?.to == "kimi" && link[1]?.resume == false
        && link[2]?.resume == true && link[3]?.back == true && link[3]?.to == nil && link[4] == nil
    print("SWITCH DIALOG \(dialogOK ? "OK" : "FAIL — \(dryNew) / \(dryOwn) / \(dryBack) / \(wrote)")")
    // the core's own output (its samples in tests/fixtures/phase1, or fresh
    // ones: build_app.sh --test passes the folder in AHT_FIXTURES) through
    // the same parsers, value for value
    var samplesOK = true
    if let dir = ProcessInfo.processInfo.environment["AHT_FIXTURES"], !dir.isEmpty {
        func sample(_ n: String) -> [String: Any] {
            let data = try? Data(contentsOf: URL(fileURLWithPath: dir).appendingPathComponent(n))
            return data.flatMap { try? JSONSerialization.jsonObject(with: $0) } as? [String: Any] ?? [:]
        }
        var miss: [String] = []
        for n in ["projects_handing.json", "projects_handing_release.json"] {
            let d = sample(n)
            let g = d["handing"] as? [String: Any] ?? [:]
            let h = Project(d).handing
            if h?.machine != g["remote"] as? String || h?.state != g["state"] as? String
                || h?.release != g["release"] as? Bool
                || (h?.silentSince == nil) != (g["unreachable_since"] is NSNull) {
                miss.append(n)
            }
        }
        let dry = sample("reclaim_release_dry.json")
        let there = dry["remote"] as? String ?? "?"
        let lost = (dry["would_lose"] as? [String: Any]) ?? [:]
        let asked = releaseText(dry, there, away: false)
        let n = tally(lost["files"]), talk = tally(lost["history"])
        let lostOK: Bool
        if n == 0 && talk == 0 {
            lostOK = asked.hasPrefix("Nothing changed on \(there)")
        } else {
            // `files` is a count, a list or null; `history` may be missing (an older core)
            lostOK = (n != nil || lost["files"] is NSNull) && !asked.hasPrefix("Nothing changed")
                && ((n ?? 0) == 0 || asked.contains(n == 1 ? "\n\n1 file" : "\n\n\(n!) files"))
                && ((talk ?? 0) == 0 || asked.contains("the conversation stay")
                    || asked.contains("The conversation stays"))
        }
        if !lostOK || (dry["released"] as? Bool) != false { miss.append("reclaim_release_dry.json") }
        if (sample("reclaim_release_apply.json")["released"] as? Bool) != true {
            miss.append("reclaim_release_apply.json")
        }
        // a project whose Keep in sync Release paused, when the core recorded one
        let held = sample("projects_mirror_paused.json")
        if !held.isEmpty {
            let p = Project(held)
            let g = held["mirror_paused"] as? [String: Any] ?? [:]
            if p.syncPaused == nil || p.syncPaused?.reason != g["reason"] as? String
                || p.syncPaused?.at == nil || p.sync != "paused" {
                miss.append("projects_mirror_paused.json")
            }
        }
        let list = sample("backup_offsite_list.json")
        let rows = list["folders"] as? [[String: Any]] ?? []
        let parsed = offsiteFolders(list)
        let ids = rows.map { ($0["id"] as? String) ?? ($0["folder"] as? String) ?? "" }
        if rows.isEmpty || parsed.map({ $0.id }) != ids
            || parsed.map({ $0.legacy }) != rows.map({ $0["legacy"] as? Bool ?? false })
            || parsed.map({ $0.mine }) != rows.map({ $0["mine"] as? Bool ?? false })
            || parsed.map({ $0.files }) != rows.map({ $0["files"] as? Int ?? -1 })
            || Set(ids).count != ids.count {
            miss.append("backup_offsite_list.json")
        }
        let got = sample("backup_fetch_offsite.json")
        if let f = parsed.first, let n = got["files"] as? Int {
            let said = fetchedText(got, f, said: "")
            if !(n == 0 ? said.hasPrefix("Nothing to fetch") : said.hasPrefix("Fetched \(n) backup(s)")) {
                miss.append("backup_fetch_offsite.json")
            }
        } else {
            miss.append("backup_fetch_offsite.json")
        }
        let ho = sample("status_handover.json")["handover"] as? [String: Any] ?? [:]
        if !(ho["can_reach"] is Bool) || !(ho["supported"] is Bool) { miss.append("status_handover.json") }
        let told = sample("notices_handover.json")["notices"] as? [[String: Any]] ?? []
        if told.isEmpty || told.contains(where: {
            ($0["info"] as? [String: Any])?["kind"] as? String != "handover"
                || ($0["info"] as? [String: Any])?["project"] as? String == nil
        }) {
            miss.append("notices_handover.json")
        }
        samplesOK = miss.isEmpty
        print("CORE SAMPLES \(samplesOK ? "OK" : "FAIL \(miss)") — \(dir)")
    } else {
        print("CORE SAMPLES not checked (AHT_FIXTURES names no folder)")
    }
    // … and the core's phase-2 samples (switch, relays): AHT_FIXTURES_PHASE2
    var relaySamplesOK = true
    let dir2 = ProcessInfo.processInfo.environment["AHT_FIXTURES_PHASE2"] ?? ""
    if !dir2.isEmpty && FileManager.default.fileExists(atPath: dir2) {
        let dir = dir2
        func sample(_ n: String) -> [String: Any] {
            let data = try? Data(contentsOf: URL(fileURLWithPath: dir).appendingPathComponent(n))
            return data.flatMap { try? JSONSerialization.jsonObject(with: $0) } as? [String: Any] ?? [:]
        }
        var miss: [String] = []
        // the status: agy is among the agents, and the menu has each one installed
        let st = sample("status.json")
        let named = (st["agent_clis"] as? [String: Any]) ?? [:]
        let installed = switchAgents(st)
        if named["agy"] == nil || installed != SWITCH_AGENTS.filter({ named[$0] is String })
            || (named["agy"] is String && !switchItems(Project([:]), installed)
                .contains { $0.title == "Continue in Antigravity…" }) {
            miss.append("status.json")
        }
        // the projects: a row with an open relay gets the line and Hand Back first
        let listed = sample("projects_relay.json")
        let rows = (listed["projects"] as? [[String: Any]]).map { $0.filter { $0["relay"] is [String: Any] } }
            ?? (listed.isEmpty ? [] : [listed])
        if rows.isEmpty { miss.append("projects_relay.json (no row with a relay)") }
        for row in rows {
            let g = row["relay"] as? [String: Any] ?? [:]
            let p = Project(row)
            let from = AGENT_LABEL[g["from_agent"] as? String ?? ""] ?? "?"
            let to = AGENT_LABEL[g["to_agent"] as? String ?? ""] ?? "?"
            let first = switchItems(p, installed).first
            if p.relay?.id != g["id"] as? String || p.relay?.since == nil
                || !(p.handBack.map(relayLine) ?? "").hasPrefix("\(to) has had this project since ")
                || !(p.handBack.map(relayLine) ?? "").hasSuffix("taken over from \(from)")
                || first?.back != true || first?.title != "Hand Back to \(from) (its own session)…" {
                miss.append("projects_relay.json")
            }
        }
        // the switch dialogs: the text for each way, with the fallback and the warnings
        for (n, mode) in [("switch_dry.json", "new"), ("switch_back_dry.json", "back")] {
            let d = sample(n)
            let said = switchText(d, mode: mode, hook: true)
            let label = AGENT_LABEL[d["target"] as? String ?? ""] ?? "?"
            if d["mode"] as? String != mode || d["applied"] as? Bool != false || !said.hasPrefix(label)
                || !((d["fallback"] as? String).map { said.contains($0) } ?? (d["fallback"] is NSNull))
                || !((d["warnings"] as? [String]) ?? []).allSatisfy({ said.contains("⚠ " + $0) })
                || !(d["start_line"] is String) || said.contains("the other agent")
                || (d["source"] as? [String: Any])?["agent"] as? String == d["target"] as? String {
                miss.append(n)                  // `source`: the agent whose work goes on
            }
        }
        let wrote = sample("switch_brief_only.json")
        let project = wrote["project"] as? String ?? ""
        let told = switchDoneText(wrote, project: project)
        if wrote["mode"] as? String != "brief-only" || wrote["applied"] as? Bool != true
            || !(wrote["start_line"] is NSNull) || !(wrote["relay"] is String)
            || ((wrote["brief"] as? String) ?? "").isEmpty
            || !told.hasPrefix("The summary is written: ") {
            miss.append("switch_brief_only.json")
        }
        relaySamplesOK = miss.isEmpty
        print("RELAY SAMPLES \(relaySamplesOK ? "OK" : "FAIL \(miss)") — \(dir)")
    } else {
        print("RELAY SAMPLES not checked (" + (dir2.isEmpty ? "AHT_FIXTURES_PHASE2 names no folder"
                                                     : "no samples in \(dir2) yet") + ")")
    }
    // the welcome's login switch: a first setup's "off" is an answer too, and
    // the core then keeps it (answered, and Getting started's step optional)
    var loginOK = loginAnswered(false, was: false, start: true)
        && loginAnswered(true, was: false, start: true)
        && !loginAnswered(false, was: false, start: false)
        && !loginAnswered(true, was: true, start: true)
    let tmp = FileManager.default.temporaryDirectory
        .appendingPathComponent("aht-selftest-\(getpid())").path
    try? FileManager.default.createDirectory(atPath: tmp + "/LaunchAgents",
                                             withIntermediateDirectories: true)
    func inTmp(_ args: [String]) -> [String: Any] {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: PY)
        p.arguments = [core] + args
        var env = ProcessInfo.processInfo.environment
        env.merge(["HOME": tmp, "AHT_HOME": tmp + "/.aht", "AHT_LAUNCH_AGENTS": tmp + "/LaunchAgents",
                   "AHT_NO_NOTIFY": "1", "AHT_NO_ICONS": "1", "AHT_NO_BACKUP": "1",
                   "AHT_NO_MIRROR": "1"]) { $1 }
        p.environment = env
        let out = Pipe()
        p.standardOutput = out
        p.standardError = Pipe()
        guard (try? p.run()) != nil else { return [:] }
        let data = out.fileHandleForReading.readDataToEndOfFile()
        p.waitUntilExit()
        return ((try? JSONSerialization.jsonObject(with: data)) as? [String: Any]) ?? [:]
    }
    let said = inTmp(["autostart", "off", "--json"])
    let step = ((inTmp(["getting-started", "--json"])["steps"] as? [[String: Any]]) ?? [])
        .first { $0["id"] as? String == "login" }
    loginOK = loginOK && said["answered"] as? Bool == true && step?["optional"] as? Bool == true
    try? FileManager.default.removeItem(atPath: tmp)
    print("WELCOME LOGIN ANSWER \(loginOK ? "OK" : "FAIL — \(said), \(step ?? [:])")")
    exit(r.ok && bad.isEmpty && setupOK && apartOK && plistOK && marksOK && namesOK && handingOK
         && releaseOK && pauseOK && backOnOK && offsiteOK && relayOK && dialogOK && samplesOK
         && relaySamplesOK && loginOK ? 0 : 1)
}

// chimes: aht's own chimes as WAV files in DIR, to hear or look at them
//   --chimes DIR
if let i = CommandLine.arguments.firstIndex(of: "--chimes"), i + 1 < CommandLine.arguments.count {
    for n in Chimes.own {
        let f = URL(fileURLWithPath: CommandLine.arguments[i + 1]).appendingPathComponent(n + ".wav")
        guard (try? Chimes.wav(n)?.write(to: f)) != nil else { print("could not write \(f.path)"); exit(1) }
        print(f.path)
    }
    exit(0)
}

// corner-rows: what the session corner lists right now, one session a line
if CommandLine.arguments.contains("--corner-rows") {
    let c = CornerModel()
    c.poll()
    for r in c.rows {
        print([r.state, r.age, r.name, (r.project as NSString).abbreviatingWithTildeInPath]
              .joined(separator: "\t"))
    }
    exit(0)
}

// notify: post one notice as aht and leave (the core uses this while the
// menu bar app is not running, so a click on the notice still opens aht)
//   --notify TITLE MESSAGE [INFO-JSON]
if let i = CommandLine.arguments.firstIndex(of: "--notify"), i + 2 < CommandLine.arguments.count {
    let args = CommandLine.arguments
    let c = UNMutableNotificationContent()
    c.title = args[i + 1]
    c.body = args[i + 2]
    c.sound = .default
    if i + 3 < args.count, let d = args[i + 3].data(using: .utf8),
       let info = (try? JSONSerialization.jsonObject(with: d)) as? [String: Any] {
        c.userInfo = info.compactMapValues { $0 is NSNull ? nil : $0 }
    }
    let center = UNUserNotificationCenter.current()
    let done = DispatchSemaphore(value: 0)
    var ok = false
    center.requestAuthorization(options: [.alert, .sound]) { granted, _ in
        guard granted else { done.signal(); return }
        center.add(UNNotificationRequest(identifier: UUID().uuidString, content: c, trigger: nil)) { err in
            ok = err == nil
            done.signal()
        }
    }
    _ = done.wait(timeout: .now() + 8)
    exit(ok ? 0 : 1)
}

// spotlight check: are the sessions in Spotlight?  Asks the index the way
// Spotlight does, for this app's own items only
//   --spotlight-check WORD
if let i = CommandLine.arguments.firstIndex(of: "--spotlight-check"),
   i + 1 < CommandLine.arguments.count {
    let word = CommandLine.arguments[i + 1].replacingOccurrences(of: "\"", with: "")
    let ctx = CSSearchQueryContext()
    ctx.fetchAttributes = ["title"]
    let q = CSSearchQuery(queryString: "title == \"*\(word)*\"cd", queryContext: ctx)
    var n = 0
    q.foundItemsHandler = { items in
        for it in items where n < 5 { print("  " + (it.attributeSet.title ?? "?")); n += 1 }
    }
    q.completionHandler = { err in
        print("SPOTLIGHT \(n > 0 ? "OK" : "NOTHING") — \(n) shown" + (err.map { " (\($0))" } ?? ""))
        exit(n > 0 ? 0 : 1)
    }
    q.start()
    RunLoop.main.run(until: Date().addingTimeInterval(20))
    print("SPOTLIGHT no answer")
    exit(1)
}

// snapshot: the window's tabs (and its dialogs) as PNG files, to look at a
// layout without clicking through it (needs a login session; nothing changes)
//   --snapshot DIR [--select-first] [--query WORDS]
//              [--corner-only | --welcome-only | --handover-only]
/// --dark renders in the dark appearance; the window's own background is
/// drawn under every snapshot, so the PNG is opaque (a transparent one is
/// unreadable on a page of the other colour)
let SNAP_LOOK = NSAppearance(named: CommandLine.arguments.contains("--dark") ? .darkAqua : .aqua)!

func snapshot(_ view: some View, _ file: String, _ size: NSSize) {
    let host = NSHostingView(rootView: view)
    host.appearance = SNAP_LOOK
    let w = NSWindow(contentRect: NSRect(origin: .zero, size: size),
                     styleMask: [.titled], backing: .buffered, defer: false)
    w.appearance = SNAP_LOOK
    w.contentView = host
    w.layoutIfNeeded()
    RunLoop.main.run(until: Date().addingTimeInterval(0.8))
    host.layoutSubtreeIfNeeded()
    guard let rep = host.bitmapImageRepForCachingDisplay(in: host.bounds) else { return }
    host.cacheDisplay(in: host.bounds, to: rep)
    guard let out = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: rep.pixelsWide,
                                     pixelsHigh: rep.pixelsHigh, bitsPerSample: 8,
                                     samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                     colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)
    else { return }
    out.size = rep.size
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: out)
    let all = NSRect(origin: .zero, size: rep.size)
    SNAP_LOOK.performAsCurrentDrawingAppearance {
        NSColor.windowBackgroundColor.setFill()
        all.fill()
    }
    rep.draw(in: all, from: .zero, operation: .sourceOver, fraction: 1, respectFlipped: true, hints: nil)
    NSGraphicsContext.restoreGraphicsState()
    try? out.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: file))
    print("wrote \(file)")
}

if let i = CommandLine.arguments.firstIndex(of: "--snapshot"),
   i + 1 < CommandLine.arguments.count {
    let args = CommandLine.arguments
    let dir = args[i + 1]
    try? FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
    NSApplication.shared.setActivationPolicy(.accessory)
    NSApplication.shared.appearance = SNAP_LOOK
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
    let corner = CornerModel()                  // the session corner, with demo rows
    corner.rows = [("Slides", "working", "now"), ("Budget", "working", "12m"),
                   ("Server", "waiting", "waits 2m"), ("Paper review", "done", "4m"),
                   ("Thesis chapter 3 — literature and related work", "idle", "")]
        .enumerated().map { i, r in
            CornerRow(id: "demo\(i)", pid: 100 + i, name: r.0, project: "~/Desktop/" + r.0,
                      state: r.1, age: r.2.replacingOccurrences(of: "waits ", with: ""),
                      recent: Double(10 - i))
        }
    snapshot(CornerView(c: corner, open: { _ in }, hide: {}).padding(12),
             dir + "/corner.png", NSSize(width: 276, height: 190))
    corner.note = "Server: it is not in an iTerm2 tab"
    snapshot(CornerView(c: corner, open: { _ in }, hide: {}).padding(12),
             dir + "/corner-note.png", NSSize(width: 276, height: 210))
    corner.note = nil
    if args.contains("--corner-only") { exit(0) }
    let welcome = WelcomeModel()
    welcome.install = true
    welcome.load(first: true)
    let welcomeEnd = Date().addingTimeInterval(60)
    while welcome.loading && Date() < welcomeEnd { RunLoop.main.run(until: Date().addingTimeInterval(0.2)) }
    for (page, name) in [(WelcomeModel.Page.hello, "hello"), (.quick, "quick"), (.folders, "folders"),
                         (.projects, "projects"), (.rules, "rules"), (.extras, "extras"),
                         (.updates, "updates"), (.done, "done")] {
        welcome.page = page
        snapshot(WelcomeView(w: welcome).environmentObject(model), dir + "/welcome-\(name).png",
                 NSSize(width: 640, height: 580))
    }
    // Quick Setup when starting at login was turned off before: its switch, and the note
    welcome.page = .quick
    welcome.install = false
    (welcome.asked, welcome.answered, welcome.login) = (true, true, false)
    snapshot(WelcomeView(w: welcome).environmentObject(model), dir + "/welcome-quick-login-off.png",
             NSSize(width: 640, height: 580))
    if args.contains("--welcome-only") { exit(0) }
    // an unfinished handover (its banner: Check Now, Release…), a project on
    // another machine (Release… next to Take Back) and Fetch Backups From…,
    // from made-up rows in the shape of the core's JSON
    let demo = AppModel()
    (demo.status, demo.config, demo.loaded) = (model.status, model.config, true)
    let stamp = { (ago: Double) -> String in
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        return f.string(from: Date().addingTimeInterval(-ago))
    }
    let home = ProcessInfo.processInfo.environment["HOME"] ?? HOME
    let handing = { (ago: Double, silent: Bool) -> [String: Any] in
        ["attempt": "20261026-141000-ab12", "step": "starting", "remote": "box", "host": "box",
         "since": stamp(ago), "state": silent ? "unreachable" : "checking", "release": silent,
         "unreachable_since": silent ? Date().timeIntervalSince1970 - ago + 60 : NSNull() as Any]
    }
    let demoRows: [(String, [String: Any])] = [
        ("api", ["handing": handing(4000, true)]), ("site", ["handing": handing(40, false)]),
        ("shop", ["away": "box", "away_remote": "box", "away_since": stamp(7200)]),
        ("blog", ["mirror": "box", "mirror_synced_at": Date().timeIntervalSince1970 - 9000,
                  "mirror_status": "ok",
                  "mirror_paused": ["reason": "released", "at": stamp(1800), "remote": "box"]]),
        ("paper", ["agents": ["claude", "codex"],
                   "relay": ["id": "20261026-141000-k3f9", "from_agent": "claude", "to_agent": "codex",
                             "since": Date().timeIntervalSince1970 - 5400, "open": true,
                             "incoming": false]])]
    demo.projects = demoRows.map { name, extra in
        Project(["real_path": home + "/code/" + name, "exists": true, "sessions": 6,
                 "bytes": 4_200_000, "agents": ["claude"]].merging(extra) { $1 })
    }
    demo.status["handover"] = ((demo.status["handover"] as? [String: Any]) ?? [:])
        .merging(["default_remote": "box"]) { $1 }
    for (p, name) in zip(demo.projects, ["handing", "handing-checking", "away", "sync-paused", "relay"]) {
        demo.selection = p.path
        snapshot(DetailView().environmentObject(demo).frame(width: 900, height: 176),
                 dir + "/detail-\(name).png", NSSize(width: 900, height: 176))
    }
    // the switch dialog (a new session, its own session) and Hand Back, from
    // dry runs in the shape of `switch --json`
    let paper = demo.projects.last!
    let wrote = switchDoneText(["applied": true, "mode": "brief-only", "target": "agy",
                                "brief": paper.path + "/.aht/handover/relay-20261026-153012-k3f9.md"],
                               project: paper.path)
    (demo.notes[paper.path], demo.summaries[paper.path]) = (wrote, paper.path + "/.aht/handover")
    demo.selection = paper.path
    snapshot(DetailView().environmentObject(demo).frame(width: 900, height: 176),
             dir + "/detail-summary-only.png", NSSize(width: 900, height: 176))
    let from: [String: Any] = ["agent": "claude", "session": "0f3a", "title": "fix the login redirect"]
    let dry = { (mode: String, extra: [String: Any]) -> [String: Any] in
        ["command": "switch", "applied": false, "blockers": [], "warnings": [], "project": paper.path,
         "source": from, "target": "codex", "relay": NSNull(), "mode": mode, "fallback": NSNull(),
         "start_line": "codex 'Read .aht/handover/relay-20261026-153012-k3f9.md first: it records "
            + "where the work stood.'"].merging(extra) { $1 }
    }
    let plans = ["new": dry("new", ["warnings": ["Codex is still open in this folder; don't type into both"]]),
                 "resume": dry("resume", ["fallback": "Codex has no session of its own here: a new "
                                            + "session reads the full summary instead."])]
    for (mode, name) in [("new", "new"), ("resume", "own")] {
        snapshot(SwitchSheet(plan: SwitchPlan(project: paper, target: "codex", back: false, backTo: nil,
                                              plans: plans, mode: mode)).environmentObject(demo),
                 dir + "/sheet-switch-\(name).png", NSSize(width: 520, height: 420))
    }
    snapshot(SwitchSheet(plan: SwitchPlan(project: paper, target: "claude", back: true, backTo: nil,
                                          plans: ["back": dry("back", ["target": "claude", "source": [
                                            "agent": "codex", "session": "019a", "title": NSNull()],
                                            "start_line": "claude --resume 0f3a"])],
                                          mode: "back")).environmentObject(demo),
             dir + "/sheet-hand-back.png", NSSize(width: 520, height: 330))
    demo.offsite = OffsiteView(machine: "box", loading: false, folders: offsiteFolders(["folders": [
        ["id": "a1b2c3d4e5f6", "name": "studio", "system": "Darwin", "updated": stamp(5400),
         "projects": 14, "files": 131, "bytes": 412_000_000, "mine": true, "legacy": false],
        ["id": "0f9e8d7c6b5a", "name": "old-mac", "system": "Darwin", "updated": stamp(9 * 86400),
         "projects": 22, "files": 208, "bytes": 960_000_000, "mine": false, "legacy": false],
        ["id": NSNull(), "folder": "laptop", "name": "laptop", "system": NSNull(),
         "updated": stamp(40 * 86400), "projects": 3, "files": 12, "bytes": 18_000_000,
         "mine": false, "legacy": true]]]))
    demo.offsite?.pick = firstPick(demo.offsite?.folders ?? [])
    snapshot(FetchBackupsSheet().environmentObject(demo), dir + "/sheet-fetch-backups.png",
             NSSize(width: 620, height: 460))
    if let f = demo.offsite?.folders.first(where: { $0.id == demo.offsite?.pick }) {
        demo.offsite?.result = fetchedText(["machine": "box", "files": 208, "bytes": 960_000_000,
                                            "pulled": true, "renamed": []], f, said: "")
        snapshot(FetchBackupsSheet().environmentObject(demo), dir + "/sheet-fetch-backups-done.png",
                 NSSize(width: 620, height: 460))
    }
    if args.contains("--handover-only") {
        // … and the same from the core's own answers: the Projects tab, and
        // the fetch sheet when a machine keeps the backups
        model.tab = .projects
        snapshot(MainView().environmentObject(model), dir + "/projects.png", NSSize(width: 900, height: 620))
        model.openFetchBackups()
        let listEnd = Date().addingTimeInterval(60)
        while model.offsite?.loading == true && Date() < listEnd {
            RunLoop.main.run(until: Date().addingTimeInterval(0.2))
        }
        if model.offsite != nil {
            snapshot(FetchBackupsSheet().environmentObject(model), dir + "/sheet-fetch-backups-live.png",
                     NSSize(width: 620, height: 460))
        }
        exit(0)
    }
    model.refreshBoard()                        // the Sessions tab shows real rows
    let boardEnd = Date().addingTimeInterval(60)
    while model.boardAt == nil && Date() < boardEnd {
        RunLoop.main.run(until: Date().addingTimeInterval(0.2))
    }
    var looked = false                          // the Machines tab lists what is found
    model.discover { looked = true }
    let lookEnd = Date().addingTimeInterval(30)
    while !looked && Date() < lookEnd { RunLoop.main.run(until: Date().addingTimeInterval(0.2)) }
    for tab in Tab.allCases {
        model.tab = tab
        snapshot(MainView().environmentObject(model), dir + "/\(tab.rawValue.lowercased()).png", size)
    }
    snapshot(SettingsView().environmentObject(model), dir + "/settings-all.png",
             NSSize(width: 900, height: 2000))
    GUIDE.topic = guideTopics().first { $0.title.hasPrefix("Undo a whole session") }?.title
    snapshot(GuideView().environmentObject(GUIDE), dir + "/guide.png", NSSize(width: 900, height: 660))
    snapshot(GettingStartedSheet().environmentObject(model), dir + "/sheet-getting-started.png",
             NSSize(width: 660, height: 720))
    model.status["update"] = ["latest": "0.14.0", "current": "0.13.0", "newer": true,
                              "upgrade": "brew upgrade --cask aht && aht install && open -a aht",
                              "notes": "## What's new since 0.13.0\n\n### Mac app\n- **Show Sessions**: "
                                + "every session of a project, branches under the one they came "
                                + "from.\n- **Welcome window**: Quick Setup or each step."]
    snapshot(UpdateSheet().environmentObject(model), dir + "/sheet-update.png", NSSize(width: 680, height: 560))
    if let p = model.selected {                  // the dialogs, for the selected project
        let j = ahtJSON(["journal", p.path, "--json"]) ?? [:]
        snapshot(TextSheetView(t: TextSheet(title: "Journal: \(p.name)",
                                             text: j["markdown"] as? String ?? "", project: p))
                    .environmentObject(model), dir + "/sheet-journal.png", NSSize(width: 720, height: 560))
        let sl = ((ahtJSON(["sessions", p.path, "--json"]) ?? [:])["sessions"] as? [[String: Any]]) ?? []
        snapshot(SessionListSheet(v: SessionListView(project: p, items: sl.map(SessionItem.init)))
                    .environmentObject(model), dir + "/sheet-sessions.png", NSSize(width: 780, height: 560))
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
        func wait(_ done: () -> Bool) {
            let end = Date().addingTimeInterval(40)
            while !done() && Date() < end { RunLoop.main.run(until: Date().addingTimeInterval(0.2)) }
        }
        model.openChanges(p)
        wait { model.changes != nil }
        if let c = model.changes {
            snapshot(ChangesSheet(c: c).environmentObject(model), dir + "/sheet-changes.png",
                     NSSize(width: 900, height: 600))
        }
        model.openUndo(p)
        wait { model.undo != nil }
        if let u = model.undo {
            snapshot(UndoSheet(u: u).environmentObject(model), dir + "/sheet-undo.png",
                     NSSize(width: 900, height: 600))
        }
        model.loadOpinion(p, run: nil)
        wait { model.opinion != nil }
        if let v = model.opinion {
            snapshot(OpinionSheet(v: v).environmentObject(model), dir + "/sheet-opinion.png",
                     NSSize(width: 960, height: 660))
        }
        model.loadNight(p)
        wait { model.night != nil }
        if let v = model.night {
            snapshot(NightShiftSheet(v: v).environmentObject(model), dir + "/sheet-night.png",
                     NSSize(width: 660, height: 540))
        }
    }
    model.openLooseEnds()
    let looseEnd = Date().addingTimeInterval(60)
    while model.looseEnds == nil && Date() < looseEnd {
        RunLoop.main.run(until: Date().addingTimeInterval(0.2))
    }
    snapshot(LooseEndsSheet().environmentObject(model), dir + "/sheet-loose-ends.png",
             NSSize(width: 760, height: 540))
    model.openTidy()
    func waitFor(_ done: () -> Bool) {
        let end = Date().addingTimeInterval(60)
        while !done() && Date() < end { RunLoop.main.run(until: Date().addingTimeInterval(0.2)) }
    }
    waitFor { model.tidy != nil }
    snapshot(TidySheet().environmentObject(model), dir + "/sheet-tidy.png", NSSize(width: 820, height: 620))
    if let t = model.tidy?.first(where: { $0.sessions > 0 }) {
        model.readHistory(t)
        waitFor { model.tidyReading != nil }
        snapshot(TidySheet().environmentObject(model), dir + "/sheet-tidy-read.png",
                 NSSize(width: 820, height: 620))
        model.tidyReading = nil
    }
    model.openWorkspaces()
    waitFor { model.workspaces != nil && (model.workspacePick == nil || !model.workspacePlan.isEmpty) }
    snapshot(WorkspaceSheet().environmentObject(model), dir + "/sheet-workspace.png",
             NSSize(width: 820, height: 560))
    model.reportPeriod = "month"
    model.loadReport()
    waitFor { !model.reportTotal.isEmpty }
    snapshot(ReportSheet().environmentObject(model), dir + "/sheet-report.png", NSSize(width: 720, height: 520))
    exit(0)
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let delegate = TrayApp()
app.delegate = delegate
app.run()
