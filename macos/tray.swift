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
//                   aht://search?q=WORDS (&everywhere=1: on the other machines
//                   too), aht://sessions, aht://loose-ends,
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
    let r = ahtFull(args)
    return (r.ok, r.out)
}

/// One core command with what it said on stderr too.  A failure no refusal
/// explains (a crash, arguments it did not understand) is noted in aht's
/// log, with the command's name and flags only.  stderr goes to a file read
/// after the command ends, not a pipe: a program the core leaves running
/// (an ssh master, say) may hold it open, and nothing here waits for that.
func ahtFull(_ args: [String]) -> (ok: Bool, out: String, err: String) {
    let fm = FileManager.default
    let errFile = fm.temporaryDirectory.appendingPathComponent("aht-stderr-\(UUID().uuidString)")
    fm.createFile(atPath: errFile.path, contents: nil, attributes: [.posixPermissions: 0o600])
    defer { try? fm.removeItem(at: errFile) }
    let p = Process()
    p.executableURL = URL(fileURLWithPath: PY)
    p.arguments = [ahtScript()] + args
    let out = Pipe()
    p.standardOutput = out
    let errHandle = try? FileHandle(forWritingTo: errFile)
    p.standardError = errHandle ?? FileHandle.nullDevice
    do { try p.run() } catch {
        try? errHandle?.close()
        return (false, "", error.localizedDescription)
    }
    let data = out.fileHandleForReading.readDataToEndOfFile()
    p.waitUntilExit()
    try? errHandle?.close()
    let err = (try? String(contentsOf: errFile, encoding: .utf8)) ?? ""
    let r = (ok: p.terminationStatus == 0, out: String(data: data, encoding: .utf8) ?? "", err: err)
    if let why = coreFailure(args, ok: r.ok, err: r.err) {
        AppLog.shared.note("aht \(commandName(args)) failed unexpectedly: \(why)",
                           level: why.hasPrefix("it crashed") ? "error" : "warn")
    }
    return r
}

func ahtJSON(_ args: [String]) -> [String: Any]? {
    let r = aht(args)
    guard let d = r.out.data(using: .utf8) else { return nil }
    let j = (try? JSONSerialization.jsonObject(with: d)) as? [String: Any]
    if j == nil, r.ok, args.contains("--json"),
       !r.out.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
        AppLog.shared.note("aht \(commandName(args)) failed unexpectedly: its answer was not JSON",
                           level: "warn")
    }
    return j
}

// ---- the app's own errors, into aht's log -------------------------------------
// An error of the Mac app's own goes to aht's log through `aht _log --level
// error --source mac-app -- MESSAGE` (the core masks it, keeps it to one line
// and caps it), so `aht logs --errors` and a problem report show it.  What
// was being done and the error; never a secret or a file's contents.  The
// same message once in ten minutes, at most five a minute.

final class AppLog {
    static let shared = AppLog()
    var now: () -> Date = { Date() }
    /// How a line is sent: in the background, never through aht() (whose own
    /// failures come here).
    var send: ([String]) -> Void = { args in
        DispatchQueue.global(qos: .utility).async { _ = shWithStderr(PY, [ahtScript()] + args) }
    }
    private var at: [Date] = []
    private var seen: [String: Date] = [:]
    private let lock = NSLock()

    /// -> whether the line was sent (not when the same one was lately, or
    /// five were this minute).
    @discardableResult
    func note(_ message: String, level: String = "error") -> Bool {
        let m = String(message.split(whereSeparator: { $0.isWhitespace })
                       .joined(separator: " ").prefix(500))
        guard !m.isEmpty else { return false }
        lock.lock()
        defer { lock.unlock() }
        let t = now()
        if let s = seen[m], t.timeIntervalSince(s) < 600 { return false }
        at = at.filter { t.timeIntervalSince($0) < 60 }
        guard at.count < 5 else { return false }
        at.append(t)
        seen[m] = t
        send(["_log", "--level", level, "--source", "mac-app", "--", m])
        return true
    }
}

/// A command as the log may name it: its name, a subcommand, its flags;
/// never a path, a value or words typed.
func commandName(_ args: [String]) -> String {
    guard let first = args.first else { return "" }
    var keep = [first]
    let subs: Set<String> = ["remote", "autostart", "relays", "night-shift", "secrets", "rules",
                             "backends", "workspace", "tab-names"]
    if subs.contains(first), args.count > 1,
       args[1].range(of: "^[a-z][a-z-]{0,20}$", options: .regularExpression) != nil {
        keep.append(args[1])
    }
    keep += args.dropFirst().filter { $0.range(of: "^--?[A-Za-z][\\w-]*$", options: .regularExpression) != nil }
    return keep.joined(separator: " ")
}

/// Why a core command failed when no refusal explains it, or nil: Python's
/// traceback on stderr (an answer may quote one from the log), or argparse's
/// usage (only up to its colon: never what was given).
func coreFailure(_ args: [String], ok: Bool, err: String) -> String? {
    guard !ok, args.first != "_log" else { return nil }
    if err.contains("Traceback (most recent call last)") {
        let kind = err.split(separator: "\n").map { $0.trimmingCharacters(in: .whitespaces) }
            .last { $0.range(of: "^[A-Za-z_][\\w.]*(Error|Exception|Interrupt|Exit|Warning)\\b",
                             options: .regularExpression) != nil }
        return "it crashed" + (kind.map { " (" + ($0.split(separator: ":").first.map(String.init) ?? $0) + ")" } ?? "")
    }
    if err.range(of: "(?m)^usage: ", options: .regularExpression) != nil {
        if let r = err.range(of: "error: [^:\n]*", options: .regularExpression) {
            return "aht did not understand it (" + err[r].dropFirst(7).trimmingCharacters(in: .whitespaces) + ")"
        }
        return "aht did not understand it"
    }
    return nil
}

/// A notice from the app itself: a click on it opens aht, not Script Editor.
func notifyUser(_ title: String, _ msg: String) {
    let c = UNMutableNotificationContent()
    c.title = title
    c.body = msg
    UNUserNotificationCenter.current().add(
        UNNotificationRequest(identifier: UUID().uuidString, content: c, trigger: nil)) { err in
        if let err = err {
            AppLog.shared.note("a notice was not shown: \(err.localizedDescription)", level: "warn")
        }
    }
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
    let awayDrivenBy: String?       // "there": that machine took it with Bring Here
    let awaySystem: String?         // Darwin, Linux or Windows: the machine that has it
    let awayHolder: String?         // that machine's own name for itself
    let awayAgent: String?          // the agent working on it there (`away_agent`); nil: not said
    let awayWindow: String?         // the window aht runs it in there (`away_window`): Peek
    let awayArrival: Bool           // handed over to a PC (`away_arrival`): Continue here waits there
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
    let incoming: Incoming?         // work that came from another machine: a note, a pickup
    let pickupFrom: Incoming?       // `pickup_from`: the pickup from another machine open here
    let knowsPickupFrom: Bool       // … the core says it (an older one says it only in `relay`)
    let copyOf: CopyOf?             // this folder is a copy of a project on another machine

    var id: String { path }
    /// The relay Hand Back (switch --back) answers: both ends on this Mac
    /// (`relay.machine` null); the core refuses it across machines.
    var handBack: Relay? { relay.flatMap { $0.machine == nil && !$0.incoming ? $0 : nil } }
    /// The pickup from another machine that is open here: `pickup_from`, also
    /// when a newer relay here (a switch to another agent) is the row's
    /// `relay`; from an older core, the row's relay when it is that pickup.
    var pickedUp: Incoming? {
        knowsPickupFrom ? pickupFrom : incoming.flatMap { $0.kind == "pickup" ? $0 : nil }
    }
    /// The machine this project was picked up from, by this Mac's name for it,
    /// while that is open: Hand Back to it is `leave-note --on` it.
    var pickedUpFrom: String? { pickedUp.flatMap { knowsPickupFrom ? $0.remote : $0.name } }
    /// Take Back can ask the machine that has it from here: one this Mac set
    /// up, and not a PC that cannot be asked (see Machine.asks); with no
    /// machines known, never a PC.
    var canTakeBack: Bool { takesBack([]) }
    func takesBack(_ ms: [Machine]) -> Bool {
        away != nil && (!pcAway(ms) || machineAnswers(awayRemote, ms))
            && (awayDrivenBy != "there" || awayRemote != nil)
    }
    /// The machine that has it is a Windows PC (`away_system`, `away_arrival`,
    /// or that machine's own `system` here).
    func pcAway(_ ms: [Machine]) -> Bool {
        away != nil && (awayArrival || awaySystem == "Windows" || ms.first { $0.name == awayRemote }?.system == "Windows")
    }
    /// The machine Send Back returns this folder to: it was brought (or
    /// handed over) here from there.
    var sendBackTo: String? {
        guard away == nil, let c = copyOf, c.kind == "brought" || c.kind == "handover" else { return nil }
        return c.remote ?? c.from
    }
    var name: String { (path as NSString).lastPathComponent }
    var parent: String {
        ((path as NSString).deletingLastPathComponent as NSString).lastPathComponent
    }
    /// The agent working on it there, in words ("Codex"); nil: not said.
    var awayAgentLabel: String? { awayAgent.map { AGENT_LABEL[$0] ?? $0 } }
    var place: String {
        // handed over to a PC: nothing runs there until Continue here
        if awayArrival, let host = away { return "Continue here waits on " + (awayRemote ?? host) }
        if let host = away { return "on " + host + (awayAgentLabel.map { " (\($0))" } ?? "") }
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
        let aw = d["away"] as? [String: Any]     // a core that gives the record itself
        away = firstText(d["away"], aw?["host"], aw?["remote"])
        awayRemote = firstText(d["away_remote"], aw?["remote"])
        awaySince = firstText(d["away_since"], aw?["since"])
        awayDrivenBy = firstText(d["away_driven_by"], aw?["driven_by"])
        awaySystem = firstText(d["away_system"], aw?["system"])
        awayHolder = firstText(d["away_holder"], aw?["holder"])
        awayAgent = firstText(d["away_agent"], aw?["agent"])
        awayWindow = firstText(d["away_window"], aw?["window"])
        awayArrival = (d["away_arrival"] as? Bool ?? aw?["arrival"] as? Bool) == true
        mirror = d["mirror"] as? String
        syncedAt = (d["mirror_synced_at"] as? NSNumber)?.doubleValue
        syncStatus = d["mirror_status"] as? String
        syncPaused = (d["mirror_paused"] as? [String: Any]).map(SyncPause.init)
        copyOf = CopyOf(d["copy_of"])
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
        incoming = (d["relay"] as? [String: Any]).flatMap(Incoming.init)
        knowsPickupFrom = d.keys.contains("pickup_from")
        pickupFrom = (d["pickup_from"] as? [String: Any]).flatMap { f in
            Incoming(["incoming": f.merging(["kind": "pickup", "id": f["relay"] ?? "",
                                             "machine": f["machine"] as? String ?? f["remote"] ?? ""]) { $1 },
                      "remote": f["remote"] ?? NSNull()])
        }
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
    let incoming: Bool              // came here from another machine
    let kind: String?               // switch | back | handover | bring | pickup | note
    let machine: String?            // the other machine; nil: both ends on this Mac
    let remote: String?             // … by this Mac's name for it

    init(_ d: [String: Any]) {
        id = d["id"] as? String ?? ""
        from = d["from_agent"] as? String ?? "claude"
        to = d["to_agent"] as? String ?? "?"
        since = moment(d["since"])
        open = d["open"] as? Bool ?? true
        incoming = d["incoming"] as? Bool ?? (d["incoming"] is [String: Any])
        kind = d["kind"] as? String
        machine = (d["machine"] as? String).flatMap { $0.isEmpty ? nil : $0 }
        remote = (d["remote"] as? String).flatMap { $0.isEmpty ? nil : $0 }
    }
}

/// `projects --json`'s `relay.incoming`: work that came from another machine.
/// A note left here (Leave a Note there, or Hand Back from there), or a
/// pickup made here from that machine, which Hand Back answers. `incoming`
/// is the record itself, or `true` on a relay that names its machine;
/// a relay between two agents here has none.
struct Incoming: Hashable {
    let id: String
    let machine: String             // the other machine: where the work was
    let remote: String?             // … by this Mac's name for it (`relay.remote`)
    let kind: String                // "note" | "back" | "pickup"
    let at: Date?
    let agent: String?              // the agent that worked there
    let workedFrom: Date?
    let workedTo: Date?
    let brief: String?              // the note: its path, or its name in .aht/handover
    let noteFor: String?            // the session here it is addressed to
    let noteAgent: String?          // … and that session's agent

    var isNote: Bool { kind != "pickup" }
    /// The machine as the Machines tab names it (what `--on` takes).
    var name: String { remote ?? machine }

    init?(_ relay: [String: Any]) {
        let d: [String: Any]
        if let own = relay["incoming"] as? [String: Any] {
            d = relay.merging(own) { $1 }
        } else if relay["incoming"] as? Bool == true {
            d = relay
        } else {
            return nil
        }
        let from = (d["from"] as? [String: Any]) ?? [:]
        let name = [d["machine"], d["from_remote"], d["from_machine"], from["machine"]]
            .compactMap { $0 as? String }.first { !$0.isEmpty }
        guard let mc = name else { return nil }
        machine = mc
        remote = (relay["remote"] as? String).flatMap { $0.isEmpty ? nil : $0 }
        id = d["id"] as? String ?? ""
        kind = (d["kind"] as? String).flatMap { ["note", "back", "pickup"].contains($0) ? $0 : nil } ?? "note"
        at = moment(d["at"] ?? d["since"])
        agent = [d["agent"], d["from_agent"], from["agent"]].compactMap { $0 as? String }.first
        workedFrom = moment(d["worked_from"] ?? d["first_t"])
        workedTo = moment(d["worked_to"] ?? d["last_t"])
        brief = d["brief"] as? String
        let nf = d["note_for"]
        noteFor = (nf as? String) ?? ((nf as? [String: Any])?["session"] as? String)
        noteAgent = ((nf as? [String: Any])?["agent"] as? String) ?? d["to_agent"] as? String
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
    let drivenBy: String?           // "there": that machine was bringing it there
    let reachable: Bool             // this Mac has that machine set up (`remote`)

    init(_ d: [String: Any]) {
        machine = [d["remote"], d["holder"], d["host"]].compactMap { $0 as? String }
            .first { !$0.isEmpty } ?? "the other machine"
        drivenBy = firstText(d["driven_by"])
        reachable = firstText(d["remote"]) != nil
        since = moment(d["since"])
        state = d["state"] as? String ?? "checking"
        silentSince = moment(d["unreachable_since"])
        release = d["release"] as? Bool ?? false
    }
}

/// `projects --json`'s `mirror_paused`: Keep in sync stays on but sends
/// nothing until the user turns it back on. Release pauses it ("released"),
/// so the next sync does not overwrite the work left on that machine. A
/// sync pauses by itself and asks (`asks`) when the copy there changed since
/// the last sync ("changed"), when it would remove a lot there ("removals"),
/// or when the folder there holds something else ("other-folder").
struct SyncPause: Hashable {
    let reason: String              // "released" | "changed" | "removals" | "other-folder"
    let at: Date?
    let machine: String?            // the machine the copy is on
    let changed: Int                // files changed there since the last sync
    let new: Int                    // … new there
    let removed: Int                // … gone there ("changed"), or to go there ("removals")
    let history: Int                // conversations that went on there
    let total: Int                  // the files in the copy there ("removals": 25 of the 34)
    let files: [String]             // some of them by name (up to 50); "other-folder": theirs
    let marker: String?             // "other-folder": that folder's own project id, if it has one

    /// A pause that waits for an answer: what to do with the copy there.
    var asks: Bool { SYNC_ASKS.contains(reason) }

    init(_ d: [String: Any]) {
        reason = d["reason"] as? String ?? ""
        at = moment(d["at"])
        machine = (d["remote"] as? String).flatMap { $0.isEmpty ? nil : $0 }
        changed = tally(d["changed"]) ?? 0
        new = tally(d["new"]) ?? 0
        removed = tally(d["removed"]) ?? 0
        history = tally(d["history"]) ?? 0
        total = tally(d["total"]) ?? 0
        files = ((d["files"] as? [Any]) ?? []).compactMap {
            ($0 as? String) ?? (($0 as? [String: Any])?["path"] as? String)
        }
        marker = (d["marker"] as? String).flatMap { $0.isEmpty ? nil : $0 }
    }
}

/// The pauses a sync makes by itself, each waiting for an answer.
let SYNC_ASKS = ["changed", "removals", "other-folder"]

/// `projects --json`'s `copy_of`: this folder is a copy of a project on
/// another machine (that machine's `~/.aht/remote/copies.json` here says so).
struct CopyOf: Hashable {
    let from: String                // the machine the project comes from, by its own name
    let remote: String?             // … by this Mac's name for it, when the core knows one
    let kind: String                // "sync" | "handover" | "brought" | "returned"
    let at: Date?
    let system: String?             // the home's system ("Windows": a PC)

    /// Its home is a PC.
    var pcHome: Bool { system == "Windows" }
    /// Send Back cannot return it: its home is a PC that does not answer
    /// (or is not set up here), so it goes back from there (Take Back on the
    /// PC).  A PC that answers takes Send Back as any machine does.
    func pcBlocks(_ ms: [Machine]) -> Bool { pcHome && !machineAnswers(remote, ms) }

    init?(_ any: Any?) {
        guard let d = any as? [String: Any],
              let f = [d["remote"], d["from"]].compactMap({ $0 as? String }).first(where: { !$0.isEmpty })
        else { return nil }
        from = (d["from"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? f
        remote = (d["remote"] as? String).flatMap { $0.isEmpty ? nil : $0 }
        kind = d["kind"] as? String ?? "sync"
        at = moment(d["at"] ?? d["since"])
        system = firstText(d["system"])
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

/// Turn Sync Back On's question: the next sync makes the copy there match this
/// Mac, but a copy that was worked on there (since the Release, `released`)
/// is not replaced: that sync pauses and asks, as any sync does.
func resumeAsk(_ name: String, _ to: String, released: Bool) -> (title: String, body: String) {
    ("Turn Keep in sync with \(to) back on?",
     "The next sync makes the copy of \(name) on \(to) the same as the one here. If that copy was "
        + "worked on " + (released ? "since you released it" : "there") + ", the sync pauses first and "
        + "sends nothing, and asks you here what happens to that work: Bring Them Here, Replace Them "
        + "(set aside on \(to) first, not deleted) or Stop Syncing.")
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

// ---- Keep in sync that looks before it overwrites ----

/// "1 file", "3 files".
func fileCount(_ n: Int) -> String { n == 1 ? "1 file" : "\(n) files" }

/// Up to `max` names as bullets, then "• …" for the rest.
func bulletList(_ names: [String], max: Int = 6, total: Int = 0) -> String {
    let more = Swift.max(total, names.count) > max
    return names.prefix(max).map { "• " + $0 }.joined(separator: "\n") + (more ? "\n• …" : "")
}

/// What a pause found in the copy there, in a few words: "3 changed, 1 new and 2 removed".
func pauseCounts(_ s: SyncPause) -> String {
    var bits: [String] = []
    if s.changed > 0 { bits.append("\(s.changed) changed") }
    if s.new > 0 { bits.append("\(s.new) new") }
    if s.removed > 0 { bits.append("\(s.removed) removed") }
    if s.history > 0 { bits.append(s.history == 1 ? "1 conversation went on" : "\(s.history) conversations went on") }
    return bits.count < 2 ? bits.joined() : bits.dropLast().joined(separator: ", ") + " and " + bits.last!
}

/// Some of the files a pause names: "src/a.py, b.md and 4 more".
func someFiles(_ files: [String], total: Int, max: Int = 3) -> String {
    guard !files.isEmpty else { return "" }
    let more = Swift.max(total, files.count) - Swift.min(max, files.count)
    return files.prefix(max).joined(separator: ", ") + (more > 0 ? " and \(more) more" : "")
}

/// The pause banner's line under its title: why the sync waits.
func pauseText(_ s: SyncPause, _ to: String) -> String {
    let at = clock(s.at)
    switch s.reason {
    case "released":
        return "You released the project" + (at.isEmpty ? "" : " at \(at)") + ", so the copy on \(to) "
            + "stays as it is. Turn sync back on to make it match this Mac again."
    case "changed":
        let what = pauseCounts(s), names = someFiles(s.files, total: s.changed + s.new + s.removed, max: 2)
        return "The copy on \(to) was changed since the last sync"
            + (what.isEmpty ? "" : " (\(what))") + (names.isEmpty ? "" : ": " + names)
            + ". Nothing was sent; that work is still there."
    case "removals":
        return "This sync would remove " + removalsCount(s) + " in the copy on \(to)"
            + (s.files.isEmpty ? "" : " (" + someFiles(s.files, total: s.removed, max: 2) + ")")
            + ". That is a lot, so nothing was sent. Allow it if you removed them here on purpose."
    case "other-folder":
        let n = Swift.max(s.total, s.files.count)
        let theirs = n == 0 ? "" : " (" + fileCount(n) + (s.files.isEmpty ? "" : ": "
            + someFiles(s.files, total: n, max: 2)) + ")"
        return (s.marker != nil ? "The folder on \(to) holds another project" + theirs
                                : "The folder on \(to) already holds files aht did not put there" + theirs)
            + ". Nothing was sent."
    default:
        return "The copy on \(to) stays as it is. Turn sync back on to make it match this Mac again."
    }
}

/// The answers to a paused sync, in the banner's order.
enum PauseAction: String, CaseIterable {
    case bring = "Bring Them Here…", replace = "Replace Them…", allow = "Allow the Removals…"
    case stop = "Stop Syncing", resume = "Turn Sync Back On…"

    func help(_ to: String) -> String {
        switch self {
        case .bring: return "Take what changed on \(to) into this Mac's copy, as Take Back does: a file "
            + "changed on both machines keeps both versions. Then the sync goes on."
        case .replace: return "Set what is on \(to) aside there and send this Mac's copy, once"
        case .allow: return "Remove those files on \(to) too, once; aht sets them aside there first"
        case .stop: return "Turn Keep in sync off; the copy on \(to) stays as it is"
        case .resume: return "Make the copy on \(to) match this Mac again"
        }
    }
}

func pauseActions(_ s: SyncPause) -> [PauseAction] {
    switch s.reason {
    case "changed": return [.bring, .replace, .stop]
    case "removals": return [.allow, .stop]
    case "other-folder": return [.replace, .stop]
    default: return [.resume]
    }
}

/// "25 of the 34 files", or "25 files" when the core did not count them all.
func removalsCount(_ s: SyncPause) -> String {
    if s.removed == 0 { return "many files" }
    return s.total > s.removed ? "\(s.removed) of the \(s.total) files" : fileCount(s.removed)
}

/// What Replace Them's sync, or Bring Them Here, would remove (the dry run's
/// `removals`: {removed, total, files (the first 50), over}); nil when nothing
/// goes, or from an older core that does not say. `over`: more than aht
/// removes without asking, so going ahead allows them (`--allow-removals`).
struct Removals: Hashable {
    let removed: Int
    let total: Int                  // the files on the side they go from
    let files: [String]
    let over: Bool

    init?(_ any: Any?) {
        guard let d = any as? [String: Any], let n = tally(d["removed"]), n > 0 else { return nil }
        removed = n
        total = tally(d["total"]) ?? 0
        files = ((d["files"] as? [Any]) ?? []).compactMap { $0 as? String }
        over = d["over"] as? Bool ?? false
    }

    /// "25 of the 34 files", or "3 files".
    var counted: String { total > removed ? "\(removed) of the \(total) files" : fileCount(removed) }
    /// The flag going ahead adds: none unless they are over the limit.
    var allow: [String] { over ? ["--allow-removals"] : [] }
}

/// A dry run whose removals are over the limit, without the blockers and
/// warnings that allowing them lifts: those name --allow-removals, which the
/// question then asks for. Any other blocker stays: a folder there that is
/// missing or empty cannot be allowed.
func pastRemovals(_ plan: [String: Any]) -> [String: Any] {
    guard Removals(plan["removals"])?.over == true else { return plan }
    var p = plan
    for k in ["blockers", "warnings"] {
        if let xs = plan[k] as? [String] { p[k] = xs.filter { !$0.contains("--allow-removals") } }
    }
    return p
}

/// Where a set-aside goes on the other machine (the dry run's `aside`), as
/// the end of a sentence.
func asideWhere(_ aside: String?, _ to: String) -> String {
    guard let a = aside, !a.isEmpty else { return " on \(to)" }
    return " in \(a) on \(to)"
}

/// Replace Them's question: what is set aside on the other machine, by name
/// (`aside`: the folder there, from the dry run), and what the sync removes
/// there (`removals`, from the dry run; over the limit, Replace Them allows them).
func replaceAsk(_ s: SyncPause, _ name: String, _ to: String, aside: String? = nil,
                removals: Removals? = nil) -> (title: String, body: String) {
    var body: String
    if s.reason == "other-folder" {
        let n = Swift.max(s.total, s.files.count)
        body = (n == 1 ? "The file in the folder on \(to) is" : (n > 1 ? "The \(n) files" : "The files")
                + " in the folder on \(to) are") + " set aside there, not deleted, and this Mac's copy of "
            + "\(name) is sent in " + (n == 1 ? "its" : "their") + " place."
        if !s.files.isEmpty { body += "\n\n" + bulletList(s.files, total: n) }
    } else {
        let what = pauseCounts(s)
        body = "What was changed on \(to)" + (what.isEmpty ? "" : " (\(what))") + " is set aside there, "
            + "not deleted, and this Mac's copy of \(name) is sent in its place."
        if s.removed > 0 { body += " Files removed on \(to) come back from this Mac." }
        if !s.files.isEmpty {
            body += "\n\nChanged on \(to):\n" + bulletList(s.files, total: s.changed + s.new + s.removed)
        }
    }
    if let r = removals {
        body += "\n\nOn \(to), this sync removes \(r.counted), set aside there first:\n"
            + bulletList(r.files, total: r.removed)
        if r.over {
            body += "\n\nThat is more than aht removes without asking, so Replace Them allows "
                + "these removals too, once."
        }
    }
    body += "\n\nWhat is set aside is kept" + asideWhere(aside, to) + "."
    if s.reason != "other-folder" { body += "\n\nTo keep that work instead, use Bring Them Here." }
    return ("Replace the copy of “\(name)” on \(to)?", body)
}

/// Allow the Removals' question: how many go there, by name.
func removalsAsk(_ s: SyncPause, _ name: String, _ to: String, aside: String? = nil) -> (title: String, body: String) {
    var body = "They are gone from \(name) on this Mac, so the sync removes them from the copy on \(to) "
        + "too. aht sets them aside there first, not deleted: they are kept" + asideWhere(aside, to) + "."
    if !s.files.isEmpty { body += "\n\n" + bulletList(s.files, total: s.removed) }
    body += "\n\nIf they went missing here by mistake, cancel and get them back first (Undo a Session, "
        + "or a backup)."
    return (s.removed > 0 ? "Remove \(removalsCount(s)) in the copy on \(to)?"
                          : "Allow the removals in the copy on \(to)?", body)
}

/// Every pause in a piece of the core's JSON (`mirror_paused`, `paused`, a
/// `mirror --json` row's or a dry run's): records with a reason that asks.
func findPauses(_ any: Any?) -> [[String: Any]] {
    if let d = any as? [String: Any] {
        if let r = d["reason"] as? String, SYNC_ASKS.contains(r), d["at"] != nil || d["files"] != nil {
            return [d]
        }
        return d.keys.sorted().flatMap { findPauses(d[$0]) }
    }
    return ((any as? [Any]) ?? []).flatMap { findPauses($0) }
}

/// After Replace Them or Allow the Removals: what the core did, and whether
/// the row still waits (`now`: the project after it).
func replacedText(_ d: [String: Any], _ name: String, _ to: String, removals: Bool, aside: String? = nil,
                  now: Project?) -> String {
    if let s = now?.syncPaused, now?.mirror != nil, s.asks {
        return "Keep in sync with \(to) is still paused: " + pauseText(s, to)
    }
    // the sync's own row: how many it set aside (`replaced`) and removed there
    let row = ((d["mirrored"] as? [[String: Any]]) ?? []).first ?? d
    let swapped = tally(row["replaced"]) ?? 0, gone = tally(row["removed"]) ?? 0
    var s = removals ? "The copy of \(name) on \(to) matches this Mac again"
                     : "This Mac's copy of \(name) is on \(to) again"
    var bits: [String] = []
    if swapped > 0 { bits.append(fileCount(swapped) + " replaced") }
    if gone > 0 { bits.append(fileCount(gone) + " removed") }
    s += bits.isEmpty ? "." : ": " + bits.joined(separator: " and ") + " there, kept" + asideWhere(aside, to) + "."
    if let a = d["set_aside"] as? String, !a.isEmpty, aside == nil { s += "\nSet aside in: " + a }
    for w in (d["warnings"] as? [String]) ?? [] { s += "\n⚠ " + w }
    return s
}

/// Stop Syncing's note, from what `mirror --off` answered and the row after it.
func stoppedText(_ to: String, ok: Bool, err: String, now: Project?, changed: Bool) -> String {
    guard ok, now?.mirror == nil else {
        let said = err.trimmingCharacters(in: .whitespacesAndNewlines)
        return "The sync was not stopped" + (said.isEmpty ? "; see the log (Settings)." : ":\n\n" + said)
    }
    return "Keep in sync with \(to) is off. The copy on \(to) stays as it is"
        + (changed ? ", with the work done there." : ".")
}

/// The line under a folder that is a copy of a project on another machine.
func copyLine(_ c: CopyOf, _ ms: [Machine] = []) -> String {
    if c.pcBlocks(ms) && (c.kind == "handover" || c.kind == "brought") {
        return (c.kind == "brought" ? "Brought here from " : "Handed over from ") + "\(c.from): "
            + "take it back on \(c.remote ?? c.from)"
    }
    switch c.kind {
    case "sync": return "Copy kept in sync from \(c.from): changes made here pause that sync"
    case "handover": return "Handed over from \(c.from): Take Back there or Send Back here returns it"
    case "brought": return "Brought here from \(c.from): Send Back returns it"
    case "returned": return "A copy of a project that went back to \(c.from)"
    default: return "A copy of a project on \(c.from)"
    }
}

/// Keep in sync with `machine` is refused here: this folder is that machine's
/// synced copy, so the two would overwrite each other.
func syncRefused(_ p: Project, _ machine: String?) -> Bool {
    guard let c = p.copyOf, c.kind == "sync", let mc = machine else { return false }
    return c.remote == mc || c.from == mc
}

/// The projects kept in sync with `machine` whose sync is paused.
func pausedWith(_ projects: [Project], _ machine: String) -> [Project] {
    projects.filter { p in
        guard let s = p.syncPaused, let to = p.mirror, p.away == nil else { return false }
        return (s.machine ?? to) == machine
    }
}

/// What "2 paused" in Machines says when the pointer rests on it.
func pausedHelp(_ held: [Project], _ machine: String) -> String {
    let names = held.prefix(4).map { $0.name }.joined(separator: ", ")
    return "Keep in sync with \(machine) is paused for \(names)" + (held.count > 4 ? " and more" : "")
        + ": show them in Projects"
}

/// The rows of a sample of `projects --json`: its `projects`, one row, or
/// rows by name ({"paused": row, "copy": row}).
func sampleRows(_ pj: [String: Any]) -> [[String: Any]] {
    if let rows = pj["projects"] as? [[String: Any]] { return rows }
    if pj["real_path"] != nil { return [pj] }
    return pj.keys.sorted().compactMap { pj[$0] as? [String: Any] }.filter { $0["real_path"] != nil }
}

/// The end of Keep All Projects in Sync's question: the syncs with that
/// machine that stay paused (`held`), and the folders here left out because
/// they are copies of another machine's projects (`copies_skipped`).
func syncAllNote(held: Int, copies: [String]) -> String {
    var s = ""
    if held > 0 {
        s += "\n\n\(held) paused: " + (held == 1 ? "it stays paused until you answer it"
                                              : "they stay paused until you answer them") + " in Projects."
    }
    if !copies.isEmpty {
        let names = copies.prefix(3).map { ($0 as NSString).lastPathComponent }.joined(separator: ", ")
        s += "\n\n" + (copies.count == 1 ? "1 folder here is a copy" : "\(copies.count) folders here are copies")
            + " of another machine's project and " + (copies.count == 1 ? "stays" : "stay") + " out: "
            + names + (copies.count > 3 ? " and \(copies.count - 3) more" : "") + "."
    }
    return s
}

/// Sync Now's notice, from `mirror --run --json`'s rows.
func syncSummary(_ rows: [[String: Any]]) -> String {
    if rows.isEmpty { return "No project is kept in sync yet" }
    let ok = rows.filter { $0["status"] as? String == "synced" }.count
    let paused = rows.filter { $0["status"] as? String == "paused" }.count
    let other = rows.count - ok - paused
    return "\(ok) synced" + (paused > 0 ? ", \(paused) paused — see Projects" : "")
        + (other > 0 ? ", \(other) skipped — see the log" : "")
}

/// Hand Over's dry run over a synced copy that was changed on the other
/// machine since the last sync: what changed there (`copy_changed`: {changed,
/// new, removed, history, files, conversations, since}), or only that it did
/// (a blocker that names `--replace-there`, the way past it); nil when it did
/// not block for that.
func changedThere(_ plan: [String: Any]) -> SyncPause? {
    if let d = plan["copy_changed"] as? [String: Any] {
        return SyncPause(d.merging(["reason": d["reason"] ?? "changed", "at": d["at"] ?? d["since"] ?? NSNull()])
                         { a, _ in a })
    }
    let named = ((plan["blockers"] as? [String]) ?? []).contains { $0.contains("--replace-there") }
    return named ? SyncPause(["reason": "changed"]) : nil
}

/// The dry run's blockers that `--replace-there` does not lift.
func otherBlockers(_ plan: [String: Any]) -> [String] {
    let all = (plan["blockers"] as? [String]) ?? []
    if all.contains(where: { $0.contains("--replace-there") }) {
        return all.filter { !$0.contains("--replace-there") }
    }
    return plan["copy_changed"] is [String: Any] && all.count <= 1 ? [] : all
}

/// The question when Hand Over meets a changed copy there.
func changedThereText(_ s: SyncPause, _ name: String, _ to: String) -> String {
    let what = pauseCounts(s), at = clock(s.at)
    var t = "The copy of \(name) on \(to) was changed since the two copies last matched"
        + (at.isEmpty ? "" : " at \(at)") + (what.isEmpty ? "" : " (\(what))")
        + ". Handing over now would replace that work."
    if !s.files.isEmpty { t += "\n\n" + bulletList(s.files, total: s.changed + s.new + s.removed) }
    return t + "\n\nBring Them Here takes it into this Mac's copy first; a file changed on both machines "
        + "keeps both versions. Replace Them sets it aside on \(to) and hands this Mac's copy over."
}

/// The line Hand Over's sheet adds when it replaces a changed copy there.
func replaceThereLine(_ s: SyncPause, _ to: String) -> String {
    let what = pauseCounts(s)
    return "⚠ What was changed on \(to)" + (what.isEmpty ? "" : " (\(what))")
        + " is set aside there first, not deleted."
        + (s.files.isEmpty ? "" : "\n" + bulletList(s.files, max: 4, total: s.changed + s.new + s.removed))
}

/// Take Back's question, and Bring Them Here's (`copy`: a copy changed there,
/// with no handover): what comes from there, from `reclaim --json`'s plan.
/// Bring Them Here names the removals here when they are over the limit
/// (`removals.over`: going ahead allows them); `synced`: Keep in sync with
/// that machine is on, so the sync goes on after it.
func takeBackText(_ plan: [String: Any], _ remote: String, copy: Bool, synced: Bool,
                  agent: String? = nil) -> String {
    let n = ((plan["plan"] as? [String: Any])?["project"] as? [String: Any]) ?? [:]
    var body = "\(tally(n["take"]) ?? 0) file(s) changed there, \(tally(n["new"]) ?? 0) new, "
        + "\(tally(n["delete"]) ?? 0) removed. Whatever they replace here is set aside, not deleted.\n"
    if !copy && plan["would_stop"] as? Bool ?? false {
        // another agent there (`agent`, the project's away_agent) ends by --stop's rules
        if let a = agent, a != "claude" {
            let q = ((plan["stop"] as? [String: Any])?["quiet_for"] ?? (plan["window"] as? [String: Any])?["quiet_for"])
                as? NSNumber
            body += "\n\(AGENT_LABEL[a] ?? a) on \(remote) is ended first: it has been "
                + (q.map { quietText($0.doubleValue) } ?? "quiet") + ", and its last turn has ended.\n"
        } else {
            body += "\nThe idle session on \(remote) is ended first.\n"
        }
    }
    if copy, let r = Removals(plan["removals"]), r.over {
        body += "\nIt removes \(r.counted) here, because they are gone from the copy on \(remote): "
            + "more than aht removes without asking, so going ahead allows it, once. They are set "
            + "aside here first, not deleted:\n" + bulletList(r.files, total: r.removed)
            + "\nIf they went missing on \(remote) by mistake, cancel.\n"
    }
    if copy && synced { body += "\nThen Keep in sync with \(remote) goes on from this Mac's copy.\n" }
    return body
}

/// Bring Them Here's note: what came, and whether the sync goes on (`now`:
/// the project after it).
func broughtText(_ d: [String: Any], _ remote: String, now: Project?) -> String {
    var s = "The changes from \(remote) are here."
    // changed on both machines: theirs is next to ours (`done.project.conflicts`)
    let both = (((d["done"] as? [String: Any])?["project"] as? [String: Any])?["conflicts"] as? [[String: Any]]) ?? []
    let twins = both.compactMap { c -> String? in
        guard let f = c["file"] as? String else { return nil }
        return (c["their_version"] as? String).map { "\(f) (theirs: \(($0 as NSString).lastPathComponent))" } ?? f
    }
    if !twins.isEmpty {
        s += "\nChanged on both machines, both kept: " + twins.prefix(3).joined(separator: ", ")
            + (twins.count > 3 ? " and \(twins.count - 3) more" : "") + "."
    }
    if let aside = d["set_aside"] as? String { s += "\nReplaced files are kept in: " + aside }
    // the sync that runs after it (`sync`), else the row as it is now
    if let row = d["sync"] as? [String: Any], let st = row["status"] as? String {
        if st == "synced" {
            s += "\nKeep in sync with \(remote) ran: the copy there matches this Mac again."
        } else if let p = findPauses(row).first.map(SyncPause.init) {
            s += "\nKeep in sync with \(p.machine ?? remote) paused again: " + pauseText(p, p.machine ?? remote)
        } else {
            let why = (row["reason"] as? String).map { ": " + $0 } ?? ""
            s += "\nThe sync with \(remote) did not run" + why + (why.hasSuffix(".") ? "" : ".")
        }
    } else if let p = now?.syncPaused, now?.mirror != nil {
        s += "\nKeep in sync with \(p.machine ?? remote) is still paused: " + pauseText(p, p.machine ?? remote)
    } else if now?.mirror != nil {
        s += "\nKeep in sync with \(remote) goes on."
    }
    for w in (d["warnings"] as? [String]) ?? [] { s += "\n⚠ " + w }
    return s
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
/// aht said instead of its JSON). Files that could not come are in its
/// `problems`, and the run then ends with 1: what did arrive still counts.
func fetchedText(_ d: [String: Any]?, _ f: OffsiteFolder, said: String) -> String {
    guard let d = d, !(d["error"] is String) else {
        let why = (d?["error"] as? String ?? said).trimmingCharacters(in: .whitespacesAndNewlines)
        return "Nothing was fetched" + (why.isEmpty ? "; see the log (Settings)." : ": " + why)
    }
    let n = d["files"] as? Int ?? 0
    let probs = (d["problems"] as? [[String: Any]]) ?? []
    var notCame = ""
    if !probs.isEmpty {
        notCame = "\n\n" + (probs.count == 1 ? "This file" : "These \(probs.count) files")
            + " could not come:\n" + probs.prefix(10).map {
                "• \($0["name"] as? String ?? "?") — \($0["error"] as? String ?? "no reason given")"
            }.joined(separator: "\n") + (probs.count > 10 ? "\n… and \(probs.count - 10) more" : "")
    }
    if n == 0 && !probs.isEmpty { return "Nothing was fetched from \(f.name)'s folder." + notCame }
    if n == 0 { return "Nothing to fetch: every backup in \(f.name)'s folder is here already." }
    let renamed = ((d["renamed"] as? [String]) ?? []).filter { $0.hasSuffix(".zip") }.count
    return "Fetched \(n) backup(s), \(byteText(d["bytes"])), from \(f.name)'s folder. Nothing "
        + "here was replaced" + (renamed == 0 ? "." : "; \(renamed) differed from a backup of "
        + "the same name here and " + (renamed == 1 ? "sits" : "sit") + " next to it under a "
        + "new name.") + " Search finds the "
        + "sessions in them, and Restore… on a result brings one back." + notCame
}

/// Whether a fetch that ended with 1 still answered with what it did: its
/// JSON lists the files that could not come.
func fetchAnswered(_ ok: Bool, _ d: [String: Any]?) -> Bool {
    ok || d?["error"] is String || ((d?["problems"] as? [Any])?.isEmpty == false && d?["files"] != nil)
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
    var watch = false               // asked every 2 minutes for sessions that wait for you
    var system = ""                 // Darwin, Linux or Windows, as it answered when added
    var paths: PathMap? = nil       // its folders: the same paths, home to home, or pairs
    var saysAnswers = false         // the core says whether a PC answers (`answers` is there)
    var answers: Bool? = nil        // … true, false, or nil: not asked yet
    var answersWhy: String? = nil   // … and why not (`answers_why`): an older aht there, no ssh server
    var id: String { name }

    /// aht here can ask it: a Mac or Linux machine; a Windows PC when the
    /// core says it answers (`answers` true: aht or its own copy answered
    /// there).  `answers` false (why in `answers_why`: "install aht on pc:
    /// …", "not asked yet: …"), or no `answers` at all (an older core,
    /// which cannot ask a PC): it cannot be asked.
    var asks: Bool { system != "Windows" || (saysAnswers && answers == true) }
    /// Why aht cannot ask this PC, in the core's words; nil when it can.
    var cannotAsk: String? { asks ? nil : answersWhy ?? "aht cannot ask a Windows machine yet." }
}

/// Whether a session's start copies the folder (Undo a whole session), as the
/// core has it: `status --json` → effective.checkpoint_on_start.  An older
/// core: the setting, which is on by default on a Mac (the copies are clones
/// that take no room; on Windows and Linux they are real copies, off until
/// turned on).
func checkpointOnStart(_ status: [String: Any], _ config: [String: Any]) -> Bool {
    (status["effective"] as? [String: Any])?["checkpoint_on_start"] as? Bool
        ?? config["checkpoints"] as? Bool ?? true
}

/// Undo a Session with no copy of the folder yet: why, also when the copy at
/// a session's start is off.
func undoNoCopyText(_ on: Bool) -> String {
    on ? "aht has no copy of this folder yet. It makes one each time a Claude Code "
         + "session starts here, and before another agent takes over."
       : "aht has no copy of this folder yet: “Copy the folder when a session starts” "
         + "is off (Settings, Safety nets)."
}

/// How often the notices ask another machine, as the core's WATCH_EVERY and
/// HOLDER_EVERY (aht.py), in seconds; sessions on this Mac every 30 seconds
/// (the notices agent's StartInterval).
let WATCH_EVERY = 120, HOLDER_EVERY = 55
func paceText(_ s: Int) -> String {
    if (45...75).contains(s) { return s == 60 ? "every minute" : "about every minute" }
    return s % 60 == 0 ? "every \(s / 60) minutes" : "every \(s) seconds"
}
let NOTICES_PACE = "Sessions on this Mac are checked every 30 seconds; a watched machine is "
    + "asked \(paceText(WATCH_EVERY)), and one that holds a project of yours \(paceText(HOLDER_EVERY))."

/// The machines a picker offers (Projects' Machine, for Hand Over and Keep
/// in sync; Backups on another machine): those aht can ask, a PC only while
/// it answers; a PC that does not stays out, unless it is the one chosen
/// now (then it is named so: `pickerLabel`).
func pickerMachines(_ ms: [Machine], keeping now: String?) -> [Machine] {
    ms.filter { $0.asks || $0.name == now }
}
func pickerLabel(_ mc: Machine) -> String {
    mc.asks ? mc.name : mc.name + " (aht cannot ask it)"
}

/// Whether aht can ask the machine set up here under `name` (see Machine.asks);
/// a machine not set up here cannot be asked.
func machineAnswers(_ name: String?, _ ms: [Machine]) -> Bool {
    ms.first { $0.name == name }?.asks ?? false
}

/// Why aht cannot ask that machine, in the core's words when it said them.
func machineCannotAsk(_ name: String?, _ ms: [Machine]) -> String {
    ms.first { $0.name == name }?.cannotAsk ?? "aht cannot ask a Windows machine yet."
}

/// `remote add` refused a Windows PC (it does not answer yet): its sheet
/// gets a "?" to the guide's PC setup.
func pcAddFailure(_ said: String) -> Bool {
    said.contains("Windows") || said.range(of: #"\bPC\b"#, options: .regularExpression) != nil
}

/// The guide's section on setting up a Windows PC that your Mac can ask.
let PC_SETUP_TOPIC = "A Windows PC that answers"

/// The machines set up (`status --json`'s `handover.remotes`, or
/// `remote list --json`'s `remotes`: the same {name: settings}, with
/// `answers` and `answers_why`).
func machinesFrom(_ remotes: Any?) -> [Machine] {
    ((remotes as? [String: Any]) ?? [:]).map { k, v in
        let d = (v as? [String: Any]) ?? [:]
        return Machine(name: k, target: d["ssh"] as? String ?? "", watch: d["watch"] as? Bool ?? false,
                       system: d["system"] as? String ?? "", paths: pathMap(d["paths"]),
                       saysAnswers: d.keys.contains("answers"), answers: d["answers"] as? Bool,
                       answersWhy: firstText(d["answers_why"]))
    }.sorted { $0.name < $1.name }
}

/// "macOS", "Linux", "Windows" for a machine's `system`.
func systemLabel(_ s: String) -> String { ["Darwin": "macOS"][s] ?? s }

/// What `remote watch NAME [--off] --json` answered: nil when the machine is
/// watched (or not) as asked, else why not.
func watchProblem(_ d: [String: Any]?, _ name: String, on: Bool, said: String = "") -> String? {
    guard let d = d, !d.isEmpty else {
        let why = said.trimmingCharacters(in: .whitespacesAndNewlines)
        return why.isEmpty ? "aht gave no answer — see the log (Settings)." : why
    }
    if let e = d["error"] as? String { return e }
    if d["watch"] as? Bool != on || d["applied"] as? Bool == false {
        return on ? "\(name) is not watched." : "\(name) is still watched."
    }
    return nil
}

/// When a machine was last heard from, as the Machines tab says it.
func heardText(_ last: Double?, stale: Bool) -> String {
    guard let t = last else { return "not heard from yet" }
    return stale ? "not heard since " + clock(NSNumber(value: t))
        : "last heard " + ago(NSNumber(value: t))
}

// ---- Bring Here, Send Back and folders at other paths (phase 7) ----

/// The last part of a path from any system: shop for /home/me/shop or C:\Users\me\shop.
func baseName(_ path: String) -> String {
    path.split(whereSeparator: { $0 == "/" || $0 == "\\" }).last.map(String.init) ?? path
}

/// Text on the clipboard (a command to run, the suggested .gitattributes).
func toClipboard(_ s: String) {
    NSPasteboard.general.clearContents()
    NSPasteboard.general.setString(s, forType: .string)
}

/// A list of names in the core's JSON: strings, or rows that name a file.
func nameList(_ any: Any?) -> [String] {
    ((any as? [Any]) ?? []).compactMap { v in
        if let s = v as? String { return s }
        let d = (v as? [String: Any]) ?? [:]
        return [d["path"], d["file"], d["name"], d["there"]].compactMap { $0 as? String }.first
    }
}

/// The first of these values that is a non-empty string.
func firstText(_ vs: Any?...) -> String? {
    for v in vs { if let s = v as? String, !s.isEmpty { return s } }
    return nil
}

/// A project aht knows on another machine (`bring --from M --list --json`'s
/// `projects`): what Bring Here from M lists.
struct ThereProject: Identifiable, Hashable {
    let path: String                // the folder there, that machine's way
    let here: String?               // where it would go on this Mac (the mapped path)
    let title: String?              // its latest session
    let updated: Date?
    let open: String?               // "working" | "waiting" | "idle": a session is open there
    let away: String?               // it is on another machine already
    let blocked: String?            // why it cannot come here (`why_not`), in the core's words
    var id: String { path }
    var name: String { baseName(path) }

    init(_ d: [String: Any]) {
        let s = (d["session"] as? [String: Any]) ?? [:]
        let aw = d["away"] as? [String: Any]
        path = firstText(d["path"], d["real_path"]) ?? "?"
        here = firstText(d["here_path"])
        title = firstText(s["title"], d["title"])
        updated = moment(s["updated"]) ?? moment(d["last_activity"])
        open = firstText(d["open"])
        away = firstText(aw?["holder"], aw?["host"], d["away"])
        let cannot = d["can_bring"] as? Bool == false
        blocked = firstText(d["why_not"], d["here_error"]) ?? (cannot ? "it cannot come here now" : nil)
    }
}

/// The projects in a list from another machine, the latest first.
func thereProjects(_ d: [String: Any]) -> [ThereProject] {
    let rows = (d["projects"] as? [[String: Any]]) ?? (d["rows"] as? [[String: Any]]) ?? []
    return rows.map(ThereProject.init)
        .sorted { ($0.updated ?? .distantPast) > ($1.updated ?? .distantPast) }
}

/// What the list says under a project, when it cannot simply come: the
/// core's reason, else where it is or the session open there.
func thereState(_ t: ThereProject) -> String? {
    if let b = t.blocked { return b }
    if let a = t.away { return "on \(a) now" }
    switch t.open {
    case "working": return "a session is working in it there"
    case "waiting": return "a session waits for you there"
    case .some: return "an idle session is open there"
    default: return nil
    }
}

/// One kind of name the receiving disk cannot hold (a dry run's `names`).
struct NameProblem: Hashable {
    let kind: String
    let text: String                // the core's plain words, else ours for the kind
    let count: Int
    let names: [String]             // each a name, or a group: "README.md and readme.md"
}

/// The plain words for each kind of name problem.
let NAME_WORDS: [String: String] = [
    "case": "two files whose names differ only in capitals",
    "unicode": "two files with the same name in two Unicode forms",
    "chars": "contains a character Windows does not allow",
    "trailing": "Windows would drop the trailing dot or space",
    "reserved": "a name Windows reserves",
    "long": "the path would be too long on Windows",
    "symlink": "links cannot be created there for your account"]

/// The same kinds by the other names a core may give them.
let NAME_KINDS = ["windows_char": "chars", "char": "chars", "characters": "chars", "dot": "trailing",
                  "space": "trailing", "long_path": "long", "long_paths": "long", "too_long": "long",
                  "link": "symlink", "links": "symlink", "symlinks": "symlink"]

func nameProblems(_ d: [String: Any]) -> [NameProblem] {
    ((d["names"] as? [[String: Any]]) ?? []).compactMap { g in
        let kind = g["kind"] as? String ?? ""
        let names = ((g["names"] as? [Any]) ?? []).compactMap { n -> String? in
            if let s = n as? String { return s }
            let group = ((n as? [Any]) ?? []).compactMap { $0 as? String }
            return group.isEmpty ? nil : group.joined(separator: " and ")
        }
        let count = max(tally(g["count"]) ?? 0, names.count)
        guard count > 0 else { return nil }
        let text = firstText(g["text"]) ?? NAME_WORDS[NAME_KINDS[kind] ?? kind] ?? kind
        return NameProblem(kind: kind, text: text, count: count, names: names)
    }
}

/// The names blocker in plain words: what `on` cannot hold, a few names of
/// each kind, and the way past it.
func namesText(_ ps: [NameProblem], on: String) -> String {
    var s = "Some names here cannot be created or kept apart on \(on):"
    for p in ps {
        let shown = p.names.prefix(4).joined(separator: "; ")
        let more = p.count > min(p.names.count, 4) ? " …" : ""
        s += "\n• " + p.text + (p.count > 1 ? " (\(p.count))" : "") + (shown.isEmpty ? "" : ": " + shown + more)
    }
    return s + "\n\nRename them, or leave them out of handovers (the setting handover_excludes)."
}

/// A blocker in the core's words, split into its sentence and the command
/// that fixes it: "… go on mac: `aht remote paths mac --add D:\work /Users/me/work`."
func fixIn(_ s: String) -> (text: String, fix: String?) {
    if let a = s.range(of: "`aht "), let b = s.range(of: "`", range: a.upperBound..<s.endIndex) {
        let fix = String(s[s.index(after: a.lowerBound)..<b.lowerBound])
        let before = s[..<a.lowerBound].trimmingCharacters(in: .whitespaces)
        let after = s[b.upperBound...].trimmingCharacters(in: .whitespaces)
        return (before + (after.isEmpty || after == "." ? "" : " " + after), fix)
    }
    // the core's way: "… go on mac:  aht remote paths mac --add …   (a note)"
    guard let a = s.range(of: ":  ") else { return (s, nil) }
    var cmd = s[a.upperBound...].trimmingCharacters(in: .whitespaces), note = ""
    if let n = cmd.range(of: "   (") {
        note = " " + cmd[n.lowerBound...].trimmingCharacters(in: .whitespaces)
        cmd = String(cmd[..<n.lowerBound])
    }
    guard cmd.hasPrefix("aht ") || cmd.hasPrefix("git ") else { return (s, nil) }
    return (String(s[..<a.lowerBound]) + note + ":", cmd)
}

/// The command the identity check gives for a folder that holds something
/// else (`identity.fix`: whole and runnable), or nil when the folder is fine.
func identityFix(_ d: [String: Any]) -> String? {
    firstText((d["identity"] as? [String: Any])?["fix"])
}

/// A blocker and the command that fixes it: the identity check's own
/// (`identity.fix`) for its blocker, else the one the sentence names.
func blockerFix(_ b: String, _ d: [String: Any]) -> (text: String, fix: String?) {
    guard let fix = identityFix(d),
          b.contains(fix) || b.contains("holds another folder") || b.contains("live project of its own")
    else { return fixIn(b) }
    guard let r = b.range(of: fix, options: .backwards) else { return (b, fix) }
    let text = b[..<r.lowerBound].trimmingCharacters(in: .whitespaces)
    return (text.hasSuffix(":") ? text : text + ":", fix)
}

/// The blockers a sheet lists one by one: the core's, less the ones that
/// only repeat the names problem (listed apart), and its error.
func blockerLines(_ d: [String: Any]) -> [String] {
    let names = nameProblems(d).map { $0.text }
    var all = ((d["blockers"] as? [Any]) ?? []).compactMap { b -> String? in
        firstText(b, (b as? [String: Any])?["text"])
    }
    all = all.filter { b in !names.contains { b.contains($0) } }
    if let e = firstText(d["error"]) { all.append(e) }
    return all
}

/// Hand Over stops on a names problem or a folder there that is not this
/// project: the sheet says it, with the command that fixes it.
func crossingBlocks(_ d: [String: Any]) -> Bool {
    !nameProblems(d).isEmpty || identityFix(d) != nil || blockerLines(d).contains { $0.contains("remote paths") }
}

/// Files that differ only in line endings (`eol_only`, not copied: the ones
/// on `keeper` stay), and files that got back the endings they left with
/// (`eol_kept`).
func eolText(_ d: [String: Any], keeper: String) -> String? {
    let only = nameList(d["eol_only"]), kept = nameList(d["eol_kept"] ?? d["eol_restored"])
    var lines: [String] = []
    if !only.isEmpty {
        lines.append("\(fileCount(only.count)) differ only in line endings: the ones on \(keeper) stay as "
                     + "they are (" + only.prefix(3).joined(separator: ", ") + (only.count > 3 ? ", …)" : ")"))
    }
    if !kept.isEmpty {
        lines.append("Line endings kept as they were on \(keeper): " + kept.prefix(3).joined(separator: ", ")
                     + (kept.count > 3 ? ", …" : ""))
    }
    return lines.isEmpty ? nil : lines.joined(separator: "\n")
}

/// Files made there whose names `receiver` cannot hold (`unsafe_names`):
/// they come into the set-aside folder under a safe name.
func unsafeText(_ d: [String: Any], receiver: String) -> String? {
    let rows = (d["unsafe_names"] as? [Any]) ?? []
    guard !rows.isEmpty else { return nil }
    let shown = rows.prefix(3).map { r -> String in
        let x = (r as? [String: Any]) ?? [:]
        let there = firstText(r, x["there"], x["name"]) ?? "?"
        return firstText(x["kept_as"]).map { "\(there) (as \(baseName($0)))" } ?? there
    }
    return "Kept aside: \(fileCount(rows.count)) whose name \(receiver) cannot hold: "
        + shown.joined(separator: ", ") + (rows.count > 3 ? ", …" : "")
}

/// The `.gitattributes` aht suggests for a git project that crosses to or
/// from Windows without one; aht never writes it.
let GITATTRIBUTES_LINES = ["* text=auto", "*.sh text eol=lf", "*.bat text eol=crlf",
                           "*.cmd text eol=crlf", "*.ps1 text eol=crlf"]

/// The lines the dry run suggests (`git.suggest`): a git project that
/// crosses to or from Windows without a `.gitattributes`; nil when none.
func gitattributesHint(_ d: [String: Any]) -> [String]? {
    let lines = nameList((d["git"] as? [String: Any])?["suggest"])
    return lines.isEmpty ? nil : lines
}

/// The git settings aht's session gets across systems, and the command that
/// gives them to git in your own terminal (`git.how`).
func gitNote(_ d: [String: Any]) -> (text: String, fix: String?)? {
    guard let how = firstText((d["git"] as? [String: Any])?["how"]) else { return nil }
    let f = fixIn(how)
    return f.fix == nil ? (how, nil) : ("For git " + f.text, f.fix)
}

/// What the dry run notes besides its warnings (an executable mark lost on
/// Windows, say).
func crossNotes(_ d: [String: Any]) -> [String] { nameList(d["notes"]) }

/// "1,204": a count as this Mac writes numbers.
func grouped(_ n: Int) -> String { NumberFormatter.localizedString(from: NSNumber(value: n), number: .decimal) }

/// The files of a plan: `files`, or what comes (`take` and `new`).
func planFiles(_ d: [String: Any]) -> Int? {
    let n = (d["plan"] as? [String: Any]) ?? [:]
    if let f = tally(n["files"]) ?? tally(d["files"]) { return f }
    guard let p = n["project"] as? [String: Any] else { return nil }
    return (tally(p["take"]) ?? 0) + (tally(p["new"]) ?? 0)
}

/// Bring Here's plan in words (`bring <path there> --from M --json`).
func bringText(_ d: [String: Any], machine: String, agent: String = "claude") -> String {
    let n = (d["plan"] as? [String: Any]) ?? [:]
    let bytes = (n["bytes"] ?? d["bytes"]) as? NSNumber
    let hist = (n["history_bytes"] ?? d["history_bytes"]) as? NSNumber
    var s = planFiles(d).map { "\(grouped($0)) file(s) come here" } ?? "The project comes here"
    s += bytes.map { " (\(byteText($0)))" } ?? ""
    s += hist.map { ", with \(byteText($0)) of Claude history." } ?? ", with its history."
    let ses = (d["session"] as? [String: Any]) ?? [:]
    if agent != "claude" {
        s += "\n\(agentStarts(agent, on: nil))" + (firstText(ses["title"]).map { " (“\($0)”)" } ?? "")
            + ", in a new terminal window."
    } else if firstText(ses["id"]) == nil {
        s += "\nNo Claude Code session yet: nothing opens here."
    } else {
        s += "\nSession: " + (firstText(ses["title"]).map { "“\($0)”" } ?? "the latest one")
            + " opens here in a new terminal window; nothing runs until you type."
        if n["file_history"] as? Bool == false { s += "\n/rewind's snapshots stay on \(machine) (the path differs here)." }
    }
    if let k = tally(n["set_aside"]), k > 0 { s += "\n\(fileCount(k)) in the folder here are set aside first." }
    let lost = nameList(d["modes_lost"])
    if !lost.isEmpty {
        s += "\n\(lost.count) script(s) lose their “executable” mark here; they get it back on \(machine)."
    }
    for a in nameList(d["other_histories"]) { s += "\n\(AGENT_LABEL[a] ?? a)'s history stays on \(machine)." }
    s += "\nOn \(machine) the project is marked as being on this Mac; its copy there stays as it is."
    for w in crossNotes(d) { s += "\n" + w }
    for w in nameList(d["warnings"]) { s += "\n⚠ " + w }
    return s
}

/// Send Back's plan in Take Back's words (`send-back <path> --json`):
/// `machine` is home, where the files go.
func sendBackText(_ d: [String: Any], machine: String, preferHere: Bool = false) -> String {
    let plan = (d["plan"] as? [String: Any]) ?? [:]
    let p = (plan["project"] as? [String: Any]) ?? [:]
    let h = (plan["history"] as? [String: Any]) ?? [:]
    var s = "\(tally(p["take"]) ?? 0) file(s) changed here, \(tally(p["new"]) ?? 0) new, "
        + "\(tally(p["delete"]) ?? 0) removed; \(tally(p["kept"]) ?? 0) changed only on \(machine) stay. "
        + "Whatever they replace on \(machine) is set aside there, not deleted."
    let talk = (tally(h["take"]) ?? 0) + (tally(h["new"]) ?? 0)
    if talk > 0 { s += "\nHistory: \(talk) conversation(s) go back with it." }
    let both = ((d["conflicts"] as? [String: Any]) ?? [:]).values.flatMap { nameList($0) }
    if !both.isEmpty {
        s += "\nChanged on both machines: " + both.prefix(4).joined(separator: ", ") + (both.count > 4 ? ", …" : "")
            + (preferHere ? ". This Mac's version is taken; \(machine)'s is set aside there."
                          : ". \(machine)'s stays, and the one from here is kept next to it.")
    }
    s += "\nThen \(machine) has the project again; this folder stays here as a copy."
    for w in crossNotes(d) { s += "\n" + w }
    for w in nameList(d["warnings"]) { s += "\n⚠ " + w }
    return s
}

/// What Bring Here did (`bring … --apply --json`).
func bringDoneText(_ d: [String: Any], machine: String, agent: String = "claude") -> String {
    if let why = pickupProblems(d) { return "Bring Here did not go through:\n\n" + why }
    var s = "Brought here from \(machine)" + (firstText(d["here_path"]).map { ": " + tilde($0) } ?? "") + "."
    if d["opened"] as? Bool == true && agent != "claude" {
        s += " \(AGENT_LABEL[agent] ?? agent) is open in a new terminal window"
            + (agent == "kimi" && farFirst(d) != nil ? "." : ": it reads aht's summary of the work as its first turn.")
    } else if d["opened"] as? Bool == true {
        s += " Its session is open in a new terminal window; nothing runs until you type."
    } else if let line = firstText(d["command_line"], d["start_line"]) {
        s += " To go on in its session: " + line
    }
    s += "\nOn \(machine) the project is marked as being here. Send Back returns it."
    if let aside = firstText(d["set_aside"]) { s += "\nWhat was in the folder here is kept in: " + aside }
    for w in nameList(d["warnings"]) { s += "\n⚠ " + w }
    return s
}

/// What Send Back did (`send-back … --apply --json`).
func sendBackDoneText(_ d: [String: Any], machine: String) -> String {
    if let why = pickupProblems(d) { return "Send Back did not go through:\n\n" + why }
    var s = "Sent back: \(machine) has the project again."
    let done = ((d["done"] as? [String: Any])?["project"] as? [String: Any]) ?? [:]
    let both = nameList(done["conflicts"])
    if !both.isEmpty {
        s += "\nChanged on both machines, both kept on \(machine): " + both.prefix(3).joined(separator: ", ")
            + (both.count > 3 ? ", …" : "")
    }
    let kept = nameList(done["eol_kept"])
    if !kept.isEmpty { s += "\nLine endings kept as they were on \(machine): " + kept.prefix(3).joined(separator: ", ") }
    if let aside = firstText(d["set_aside"]) { s += "\nReplaced files are kept on \(machine) in: " + aside }
    // another agent worked here: what it did is summed up for Claude Code there
    if let a = firstText((d["catchup"] as? [String: Any])?["agent"]) {
        s += "\nWhat \(AGENT_LABEL[a] ?? a) did here is summed up for the Claude Code session on \(machine)."
    }
    s += "\nThis folder stays here as a copy."
    for w in nameList(d["warnings"]) { s += "\n⚠ " + w }
    return s
}

/// The dry run blocks on an idle session there (`--allow-idle` lifts it).
func idleBlock(_ d: [String: Any]) -> Bool {
    d["idle_there"] as? Bool == true || blockerLines(d).contains { $0.contains("--allow-idle") }
}

/// The dry run blocks because a newer Claude Code wrote here (`--ignore-version`).
func versionBlock(_ d: [String: Any]) -> Bool {
    blockerLines(d).contains { $0.contains("--ignore-version") }
}

/// Bring Here from M: the projects there, the one picked, its dry run, and
/// what --apply did.
struct BringView: Identifiable {
    let id = UUID()
    let machine: String
    var listing = true
    var list: [String: Any] = [:]
    var said = ""                   // what aht said when it gave no JSON
    var picked: String?             // the folder there
    var loading = false
    var dry: [String: Any] = [:]
    var allowIdle = false           // --allow-idle
    var agent = "claude"            // Agent here: Claude Code's own session, or another agent (--agent)
    var applying = false
    var done: [String: Any]?
}

/// Peek at the window aht runs the agent in on the other machine:
/// `attach <path> --peek --json` -> {agent, open, status, raw_status,
/// quiet_for, screen, error}.
struct PeekView: Identifiable {
    let id = UUID()
    let project: Project
    var loading = true
    var d: [String: Any] = [:]
}

/// Peek's state line: the window's words ("quiet for 6 min") and their hint,
/// else the core's status.
func peekState(_ d: [String: Any]) -> (text: String, hint: String?)? {
    windowStatus(raw: d["raw_status"] as? String, quietFor: (d["quiet_for"] as? NSNumber)?.doubleValue,
                 notRunning: d["not_running"] as? Bool ?? false) ?? firstText(d["status"]).map { ($0, nil) }
}

func bringArgs(_ v: BringView, apply: Bool = false) -> [String] {
    ["bring", v.picked ?? "", "--from", v.machine] + (v.allowIdle ? ["--allow-idle"] : [])
        + (v.agent == "claude" ? [] : ["--agent", v.agent]) + (apply ? ["--apply"] : []) + ["--json"]
}

func bringReady(_ v: BringView) -> Bool {
    v.picked != nil && !v.loading && !v.applying && v.done == nil && !v.dry.isEmpty
        && pickupProblems(v.dry) == nil && nameProblems(v.dry).isEmpty
}

/// Send Back to M, on a project brought here from M.
struct SendBackView: Identifiable {
    let id = UUID()
    let project: Project
    let machine: String
    var loading = true
    var dry: [String: Any] = [:]
    var said = ""
    var ignoreVersion = false       // --ignore-version
    var preferHere = false          // --prefer here: this Mac's version of a file changed on both wins
    var applying = false
    var done: [String: Any]?
}

func sendBackArgs(_ v: SendBackView, apply: Bool = false) -> [String] {
    ["send-back", v.project.path] + (v.ignoreVersion ? ["--ignore-version"] : [])
        + (v.preferHere ? ["--prefer", "here"] : []) + (apply ? ["--apply"] : []) + ["--json"]
}

func sendBackReady(_ v: SendBackView) -> Bool {
    !v.loading && !v.applying && v.done == nil && !v.dry.isEmpty && pickupProblems(v.dry) == nil
        && nameProblems(v.dry).isEmpty
}

/// Why Send Back cannot ask the project's home from here: it is not set up
/// here (copy_of.remote is null), or it is a PC that does not answer.
func sendBackBlocked(_ p: Project, _ ms: [Machine]) -> String? {
    guard let c = p.copyOf, let to = p.sendBackTo else { return nil }
    if c.pcBlocks(ms) {
        return "\(to) is a Windows PC, which this Mac cannot reach: take it back on \(to)"
    }
    guard let r = c.remote, let mc = ms.first(where: { $0.name == r }) else {
        return "\(c.from) is not set up on this Mac: add it under Machines, then send it back"
    }
    return mc.asks ? nil : "\(to) is a Windows PC, which this Mac cannot reach: take it back on \(to)"
}

/// The line over a project that is on another machine and shows no session
/// of its own here: one that machine took with Bring Here ("On pc since
/// 14:10 (brought there from pc). Send it back from pc."), or one handed
/// over to a PC, where no session starts ("On pc since 14:10: continue it
/// on the PC (its tray offers Continue here).").
func awayLine(_ p: Project, _ ms: [Machine] = []) -> String? {
    let at = clock(p.awaySince)
    if p.awayDrivenBy != "there", p.pcAway(ms), let pc = p.awayRemote ?? p.awayHolder ?? p.away {
        return "On \(pc)" + (at.isEmpty ? "" : " since \(at)") + ": continue it on the PC (its tray offers Continue here)."
    }
    guard let host = p.awayHolder ?? p.away, p.awayDrivenBy == "there" else { return nil }
    return "On \(host)" + (at.isEmpty ? "" : " since \(at)") + (p.awayAgentLabel.map { ", in " + $0 } ?? "")
        + " (brought there from \(host)). Send it back from \(host)"
        + (p.pcAway(ms) && p.takesBack(ms) ? ", or take it back here." : ".")
}

/// How the folders here match the folders on a machine (`remotes.<name>.paths`).
struct PathMap: Hashable {
    let mode: String                // "same" | "home" | "pairs"
    let pairs: [[String]]           // [here, there], tried longest first; then the two homes
    let hereHome: String?
    let thereHome: String?
    var rules: [[String]] = []      // `remote paths --json`'s rules: [here, there, kind], in order
}

/// A machine's `paths` setting (and the homes, when the row names them).
func pathMap(_ v: Any?, _ row: [String: Any] = [:]) -> PathMap? {
    let hh = firstText(row["here_home"]), th = firstText(row["there_home"], row["home"])
    let rules = ((row["rules"] as? [[String: Any]]) ?? []).compactMap { r -> [String]? in
        guard let k = firstText(r["kind"]) else { return nil }
        return [firstText(r["here"]) ?? "", firstText(r["there"]) ?? "", k]
    }
    if let s = v as? String, !s.isEmpty {
        return PathMap(mode: s, pairs: [], hereHome: hh, thereHome: th, rules: rules)
    }
    guard let list = v as? [Any] else { return nil }
    let pairs = list.compactMap { p -> [String]? in
        let two = ((p as? [Any]) ?? []).compactMap { $0 as? String }
        if two.count == 2 { return two }
        let d = (p as? [String: Any]) ?? [:]
        guard let a = firstText(d["here"]), let b = firstText(d["there"]) else { return nil }
        return [a, b]
    }
    return PathMap(mode: pairs.isEmpty ? "home" : "pairs", pairs: pairs, hereHome: hh, thereHome: th, rules: rules)
}

/// `remote paths --json`: each machine's mapping, by its name. Takes
/// `machines` rows, a `remotes` table, or one machine's answer.
func pathMaps(_ d: [String: Any]) -> [String: PathMap] {
    var rows = (d["machines"] as? [[String: Any]]) ?? []
    for (k, v) in (d["remotes"] as? [String: Any]) ?? [:] {
        if let r = v as? [String: Any] { rows.append(r.merging(["remote": k]) { a, _ in a }) }
    }
    if d["paths"] != nil { rows.append(d) }
    var out: [String: PathMap] = [:]
    for r in rows {
        if let name = firstText(r["remote"], r["machine"], r["name"]), let pm = pathMap(r["paths"], r) {
            out[name] = pm
        }
    }
    return out
}

/// A folder under the home there, spelled that system's way.
func underHome(_ home: String, _ rest: String) -> String {
    let sep = home.contains("\\") ? "\\" : "/"
    return home + (home.hasSuffix(sep) ? "" : sep) + rest.replacingOccurrences(of: "/", with: sep)
}

/// The Machines line: how a folder here is found on that machine.
func pathMapText(_ p: PathMap, machine: String) -> String {
    let shown = p.rules.filter { $0[2] != "same" && !$0[0].isEmpty && !$0[1].isEmpty }
    if p.mode != "same" && !shown.isEmpty {
        // the core's rules, in the order it tries them
        return "Folders here → on \(machine): "
            + shown.map { tilde($0[0]) + " → " + $0[1] + ($0[2] == "home" ? " (home)" : "") }.joined(separator: " · ")
    }
    let home = p.thereHome.map { "~/code/shop here is \(underHome($0, "code/shop")) on \(machine)" }
        ?? "a folder in your home folder here goes into the home folder on \(machine)"
    switch p.mode {
    case "same": return "Folders: the same paths on \(machine) as here"
    case "pairs":
        return "Folders: " + p.pairs.map { tilde($0[0]) + " → " + $0[1] }.joined(separator: " · ")
            + "; elsewhere " + home
    default: return "Folders: home to home: " + home
    }
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
    var group: String? = nil        // ask | handover
}

/// `remote check NAME --json`: the machine's rows, and what went wrong
/// when it could not be checked.
func checkRows(_ d: [String: Any]) -> (rows: [Check], error: String?) {
    let row = ((d["machines"] as? [[String: Any]]) ?? []).first ?? [:]
    let rows = ((row["checks"] as? [[String: Any]]) ?? []).map {
        Check(name: $0["check"] as? String ?? "?", ok: $0["ok"] as? Bool ?? false,
              needed: $0["needed"] as? Bool ?? true,
              detail: $0["detail"] as? String ?? "", fix: $0["fix"] as? String,
              group: $0["group"] as? String)
    }
    return (rows, row["error"] as? String ?? (d.isEmpty ? "aht gave no answer" : nil))
}

/// Under a PC's check, when aht can ask it: no session starts there (unless
/// the core's own row "no session starts there" says so).
func pcCheckNote(_ mc: Machine, _ rows: [Check]) -> String? {
    let ask = rows.contains { $0.group != nil } ? rows.filter { $0.group == "ask" } : rows
    guard mc.system == "Windows", mc.asks, !ask.isEmpty, ask.allSatisfy({ $0.ok || !$0.needed }),
          !rows.contains(where: { $0.name.lowercased().hasPrefix("no session starts") }) else { return nil }
    return "No session starts on a PC: its tray offers Continue here."
}

/// The checks in their groups: what aht needs to ask the machine at all
/// (sessions, notices, search), then what a handover needs as well. Rows
/// from a core without groups stay one list, without a heading.
func checkGroups(_ rows: [Check]) -> [(title: String, rows: [Check])] {
    guard rows.contains(where: { $0.group != nil }) else { return rows.isEmpty ? [] : [("", rows)] }
    let ask = rows.filter { $0.group == "ask" }, rest = rows.filter { $0.group != "ask" }
    return [("For asking", ask), ("For handing over", rest)].filter { !$0.1.isEmpty }
}

/// What copies files to and from another machine (`handover_transfer`):
/// "auto" picks rsync where both machines have it and neither is Windows,
/// else aht's own copy.
let TRANSFER_CHOICES: [(String, String)] = [
    ("auto", "rsync where both machines have it, else aht's own copy"),
    ("rsync", "rsync"), ("aht", "aht's own copy")]
func moverLabel(_ t: String) -> String { t == "aht" ? "aht's own copy" : t }

/// What a check said copies files to and from a machine, under the setting
/// it was asked with.
struct Mover: Hashable {
    let mode: String
    let transfer: String
}

/// `remote check --json`'s `transfer` ("rsync" or "aht") for each machine
/// that answered; none from an older core.
func checkTransfers(_ d: [String: Any]) -> [String: String] {
    var out: [String: String] = [:]
    for r in (d["machines"] as? [[String: Any]]) ?? [] {
        if let n = r["remote"] as? String, let t = r["transfer"] as? String, t == "rsync" || t == "aht" {
            out[n] = t
        }
    }
    return out
}

/// A row of the check that says it already (a core may give it as a row).
func saysTransfer(_ c: Check) -> Bool { c.name.lowercased().hasPrefix("copies files") }

/// The mover a machine gets: what its check said while the setting is the
/// one it was asked under; else what is known here (Windows there, or no
/// rsync 3 on this Mac, is aht's own copy). nil: rsync if the machine has
/// it, which only asking it tells.
func moverFor(_ mc: Machine, mode: String, hereRsync: String?, known: Mover?) -> String? {
    if let k = known, k.mode == mode { return k.transfer }
    if mode == "rsync" || mode == "aht" { return mode }
    let major = Int((hereRsync ?? "").split(separator: ".").first ?? "") ?? 0
    return mc.system == "Windows" || major < 3 ? "aht" : nil
}

/// "box: rsync · pc: aht's own copy", for every machine set up.
func moversText(_ ms: [Machine], mode: String, hereRsync: String?, known: [String: Mover]) -> String {
    ms.map { mc in
        "\(mc.name): " + (moverFor(mc, mode: mode, hereRsync: hereRsync, known: known[mc.name])
            .map(moverLabel) ?? "rsync if it has it, else aht's own copy")
    }.joined(separator: " · ")
}

struct Backend: Identifiable, Hashable {
    let name: String
    let found: Bool
    let root: String
    let source: String
    let relinks: Bool          // false: agy and Vibe, whose sessions aht only reads
    var id: String { name }
}

/// Settings → Where each agent keeps its history, from `status --json` (or
/// `backends --json`).
func backendRows(_ status: [String: Any]) -> [Backend] {
    ((status["backends"] as? [[String: Any]]) ?? []).map {
        Backend(name: $0["name"] as? String ?? "?",
                found: $0["available"] as? Bool ?? false,
                root: $0["root"] as? String ?? "",
                source: $0["root_source"] as? String ?? "default",
                relinks: $0["relinks"] as? Bool ?? true)
    }
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
    var rawStatus: String? = nil    // a window's: working | quiet | exited (Claude Code's: busy | waiting | idle …)
    var quietFor: Double? = nil     // seconds the window has shown no output
    var window: String? = nil       // the window aht runs the agent in there
    var notRunning = false          // the agent there ended
    var herePath: String? = nil     // another machine's row: the project here it is (`here_path`)
    var name: String { (project as NSString).lastPathComponent }
    /// A window aht runs another agent in: its status from the window's output.
    var windowWords: (text: String, hint: String?)? {
        windowStatus(raw: rawStatus, quietFor: quietFor, notRunning: notRunning)
    }
    var state: String { (windowWords?.text ?? status) + (waitingFor.map { ": " + $0 } ?? "") }
}

struct BoardMachine: Identifiable, Hashable {
    let name: String
    let reachable: Bool
    let error: String?
    let rows: [BoardRow]
    var local = false
    var lastHeard: Double? = nil    // when it last answered (seconds since 1970)
    var stale = false               // not heard for 10 minutes
    var lastRows: [BoardRow] = []   // what it had open then, shown greyed
    var id: String { name }

    /// Its last rows stand in for live ones: it did not answer this time.
    var showsOld: Bool { !local && (stale || !reachable) && rows.isEmpty && !lastRows.isEmpty }

    /// The line over a machine that did not answer ("" when it did).
    var silentNote: String {
        guard !local && (stale || !reachable) else { return "" }
        if stale, let t = lastHeard {
            return "Not answering since \(clock(NSNumber(value: t))) — asleep, switched off or offline?"
        }
        return "Not reachable right now — is it switched on, and is Tailscale connected on this Mac?"
    }

    /// Over its last rows: "as of 11:40".
    var asOf: String { "as of " + (lastHeard.map { clock(NSNumber(value: $0)) } ?? "earlier") }
}

/// One session row of `board --json` (`sessions` and `last_sessions`).
func boardRow(_ r: [String: Any], machine: String, local: Bool) -> BoardRow {
    BoardRow(machine: machine, local: local, agent: r["agent"] as? String ?? "?",
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
             limitAuto: (r["limit"] as? [String: Any])?["auto"] as? Bool ?? false,
             rawStatus: r["raw_status"] as? String, quietFor: (r["quiet_for"] as? NSNumber)?.doubleValue,
             window: firstText(r["window"]), notRunning: r["not_running"] as? Bool ?? false,
             herePath: firstText(r["here_path"]))
}

/// `board --json`'s machines, sessions that wait for you first.
func boardMachines(_ d: [String: Any]) -> [BoardMachine] {
    let order = { (a: BoardRow, b: BoardRow) in
        (a.status == "waiting for you" ? 0 : 1, a.project) < (b.status == "waiting for you" ? 0 : 1, b.project)
    }
    return ((d["machines"] as? [[String: Any]]) ?? []).map { m in
        let name = m["machine"] as? String ?? "?"
        let local = m["local"] as? Bool ?? false
        let rows = { (key: String) in
            ((m[key] as? [[String: Any]]) ?? []).map { boardRow($0, machine: name, local: local) }.sorted(by: order)
        }
        return BoardMachine(name: name, reachable: m["reachable"] as? Bool ?? false,
                            error: m["error"] as? String, rows: rows("sessions"), local: local,
                            lastHeard: (m["last_heard"] as? NSNumber)?.doubleValue,
                            stale: m["stale"] as? Bool ?? false, lastRows: rows("last_sessions"))
    }
}

// ---- another agent on the other machine (phase 8) ---------------------------
// Hand Over can start Codex, Kimi Code, Antigravity or Mistral Vibe on the other machine
// instead of resuming Claude Code's session there (`handover --agent X`),
// and Bring Here can open one of them here (`bring --agent X`). That agent
// reads aht's summary of the work as its first turn, which uses tokens;
// Claude Code resuming its own session does not. The dry run for the agent
// chosen carries the level it starts in (`perm`, phase 7b).

let OTHER_AGENTS = ["codex", "kimi", "agy", "vibe"]

/// The agents Hand Over can start on the other machine: Claude Code, and the
/// others the dry run says are installed there (`agents_there`: a list, or
/// {agent: its path or null}); a core that does not say: all of them (the
/// dry run for one that is missing there says so).
func agentsThere(_ d: [String: Any]) -> [String] {
    let t = d["agents_there"] ?? (d["there"] as? [String: Any])?["agents"]
    var has: [String]? = nil
    if let l = t as? [String] {
        has = l
    } else if let m = t as? [String: Any] {
        has = m.compactMap { k, v in v is NSNull || (v as? Bool) == false ? nil : k }
    }
    return ["claude"] + OTHER_AGENTS.filter { has?.contains($0) ?? true }
}

/// …and Bring Here: the agent CLIs installed on this Mac.
func agentsHere(_ clis: [String]) -> [String] { ["claude"] + OTHER_AGENTS.filter { clis.contains($0) } }

/// An agent in the "Agent there" / "Agent here" choice.
func agentChoice(_ a: String) -> String { a == "claude" ? "Claude Code (its own session)" : AGENT_LABEL[a] ?? a }

/// What starting `agent` costs. `on`: the other machine (Hand Over), nil:
/// here (Bring Here); `task`: a task given with it; `d`: the dry run for
/// that agent: its `tokens` (the core's sentence), as given; Kimi below
/// never-ask opens without reading the summary (`first_prompt`).
func agentCost(_ agent: String, on: String?, task: Bool = false, _ d: [String: Any] = [:]) -> String {
    let place = on.map { "on " + $0 } ?? "here"
    if agent != "claude", let t = firstText(d["tokens"])?.trimmingCharacters(in: .whitespaces), !t.isEmpty {
        return t.prefix(1).uppercased() + t.dropFirst() + (t.hasSuffix(".") ? "" : ".")
    }
    if agent == "claude" {
        if task { return "With a task, Claude Code starts on it at once \(place): that uses tokens." }
        return on.map { "Claude Code resumes its own session on \($0): nothing runs until someone types there, "
            + "so it uses no tokens." } ?? "Claude Code's own session opens here: nothing runs until you type, "
            + "so it uses no tokens."
    }
    if agent == "kimi" && (d["kimi_reads"] as? Bool == false || farFirst(d) != nil) {
        return "Kimi Code opens \(place) without reading the summary: its run that reads it first works only in "
            + "never-ask mode, so you paste the first message aht shows you" + (on == nil ? "" : " into its window there")
            + ". That turn uses tokens."
    }
    return "Starting \(AGENT_LABEL[agent] ?? agent) \(place) uses tokens: it reads aht's summary of the work as its "
        + "first turn."
}

/// Kimi below never-ask, started by Hand Over or Bring Here: the first
/// message to paste (`first_prompt`), or nil.
func farFirst(_ d: [String: Any]) -> String? {
    firstText(d["first_prompt"]).map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.flatMap { $0.isEmpty ? nil : $0 }
}

/// What happens there, in one sentence (no full stop).
func agentStarts(_ agent: String, on: String?) -> String {
    agent == "claude" ? (on == nil ? "Its session opens here in a new terminal window" : "The session is resumed there")
        : "\(AGENT_LABEL[agent] ?? agent) starts \(on.map { "on " + $0 } ?? "here") with aht's summary of the work"
}

/// Hand Over to a Windows PC: the dry run says so (`pc`), or names Windows
/// there (`there.system`, or `system`), or the machine it goes to is a PC.
func handoverToPC(_ d: [String: Any], _ mc: Machine?) -> Bool {
    d["pc"] as? Bool == true
        || (firstText((d["there"] as? [String: Any])?["system"], d["system"]) ?? mc?.system) == "Windows"
}

/// What Hand Over to a PC says where another machine's sheet names the
/// agent that starts there: no session starts on a PC.
func pcStartsText(_ pc: String) -> String {
    "No session starts on \(pc): aht copies the project there, and the PC's tray offers “Continue here”, "
        + "which opens it in Claude Code. This folder is marked as away until you take it back."
}

/// `handover --apply` to a PC: no session was started there (`started:
/// false` with `start_reason` or `reason` "windows", at the top or under
/// `start`).
func startedNotOnPC(_ d: [String: Any]) -> Bool {
    let s = (d["start"] as? [String: Any]) ?? d
    return s["started"] as? Bool == false && firstText(s["start_reason"], s["reason"]) == "windows"
}

/// What Hand Over says when it went through: what was sent, and what runs
/// there (nothing on a PC: `toPC`, from the dry run, or the core's answer).
func handoverDoneText(_ d: [String: Any], remote: String, agent: String = "claude", task: String = "",
                      toPC: Bool = false) -> String {
    let s = (d["sent"] as? [String: Any]) ?? [:]
    var done = "Handed over to \(remote): \(s["files"] as? Int ?? 0) "
        + "file(s) sent, \(byteText(s["wire_bytes"])) over the network."
    if toPC || startedNotOnPC(d) {
        done += " No session started there: its tray offers “Continue here”."
    } else {
        if agent != "claude" { done += " \(AGENT_LABEL[agent] ?? agent) started there with aht's summary of the work." }
        if !task.isEmpty { done += "\nIt started on: " + task }
    }
    for w in (d["warnings"] as? [String]) ?? [] { done += "\n⚠ " + w }
    return done
}

/// Hand Over's command: the dry run, or `apply` it (with its status file and
/// task); `--agent X` only for another agent than Claude Code.
func handoverArgs(_ path: String, to: String?, agent: String = "claude", replace: Bool = false,
                  apply: Bool = false, file: String? = nil, task: String = "") -> [String] {
    ["handover", path] + (apply ? ["--apply"] : []) + ["--json"] + (file.map { ["--status-file", $0] } ?? [])
        + (to.map { ["--to", $0] } ?? []) + (replace ? ["--replace-there"] : [])
        + (task.isEmpty ? [] : ["--task=" + task]) + (agent == "claude" ? [] : ["--agent", agent])
}

/// A board row of a window aht started for an agent other than Claude Code
/// on another machine: its status comes from the window's output, not from
/// the agent's records. `raw_status` "working" (output in the last 15 s),
/// "quiet" (none for `quiet_for` seconds: done, or it waits for you),
/// "exited" (the agent ended); `not_running`: the agent there ended (its
/// window may be gone). nil for any other row (Claude Code keeps its own
/// words; a process-only row's "running" too).
func windowStatus(raw: String?, quietFor: Double?, notRunning: Bool) -> (text: String, hint: String?)? {
    switch raw {
    case "exited": return ("exited", nil)
    case _ where notRunning: return ("not running", nil)
    case "working": return ("working", nil)
    case "quiet": return (quietText(quietFor), "done, or it waits for you")
    default: return nil
    }
}

/// "quiet for 6 min", from seconds, as the core says it (window_words).
func quietText(_ s: Double?) -> String {
    guard let s = s, s >= 0, s.isFinite else { return "quiet" }
    let m = Int(s / 60)
    return m < 1 ? "quiet for under a minute" : m < 120 ? "quiet for \(m) min" : "quiet for \(m / 60) h"
}

/// Seconds in words: "40 s", "2 min".
func spanText(_ s: Double) -> String { s < 60 ? "\(Int(s.rounded())) s" : "\(Int(s / 60)) min" }

/// Take Back with --stop ends the agent there only when that is safe; for an
/// agent other than Claude Code, when its window has shown no output for 2
/// minutes and its last turn has ended. Otherwise it refuses: `not-quiet`
/// (the agent there still prints) or `turn-open` (a turn is not finished, or
/// aht cannot see whether it is: `seen` false); at --apply also
/// `no-reaction` (it did not quit on its quit keys).
struct StopRefusal: Equatable {
    let reason: String              // not-quiet | turn-open | no-reaction
    let agent: String?
    let machine: String?
    let quiet: Double?              // seconds without output, so far
    let need: Double                // seconds of quiet aht waits for
    let said: String?               // the core's own sentence
    let others: [String]            // the other blockers
    var seen = true                 // aht could see the agent's last message there
    var keys: [String] = []         // its quit keys
    var label: String { agent.map { AGENT_LABEL[$0] ?? $0 } ?? "The agent" }
}

let STOP_REASONS = ["not-quiet", "turn-open", "no-reaction"]
func notQuietText(_ t: String) -> Bool {
    t.range(of: "quiet for only", options: .caseInsensitive) != nil || t.range(of: "still prints", options: .caseInsensitive) != nil
}
func turnOpenText(_ t: String) -> Bool {
    ["turn is still open", "turn is not finished", "whether its turn ended"].contains {
        t.range(of: $0, options: .caseInsensitive) != nil }
}
func noReactionText(_ t: String) -> Bool { t.range(of: "did not react to its quit keys", options: .caseInsensitive) != nil }
func refusalText(_ t: String) -> Bool { notQuietText(t) || turnOpenText(t) || noReactionText(t) }
func refusalText(_ t: String, _ reason: String) -> Bool {
    reason == "not-quiet" ? notQuietText(t) : reason == "turn-open" ? turnOpenText(t) : noReactionText(t)
}

/// The refusal, read from `stop` ({stopped, reason, quiet_for, quit_keys,
/// seen}), a bare reason (`stop_reason`), or the core's own sentence in the
/// blockers or warnings ("Codex on box has been quiet for only 1 min — wait,
/// or end it yourself (--stop needs 2 minutes without output)", "Codex's last
/// turn is still open on box — wait, or end it yourself"); nil: none.
/// `others` leaves out the agent's own processes there, which end with it.
func stopRefusal(_ d: [String: Any], awayAgent: String? = nil, machine: String? = nil) -> StopRefusal? {
    let o = [d["stop_refused"], d["stop"], d["stopped"]].compactMap { $0 as? [String: Any] }
        .first { STOP_REASONS.contains(firstText($0["reason"]) ?? "") } ?? [:]
    var reason = firstText(o["reason"])
        ?? [d["stop_refused"], d["stop_reason"], d["reason"]].compactMap { $0 as? String }.first { STOP_REASONS.contains($0) }
    let blockers = (d["blockers"] as? [String]) ?? []
    let texts = blockers + ((d["warnings"] as? [String]) ?? [])
    var said = firstText(o["text"])
    if let r = reason, said == nil { said = texts.first { refusalText($0, r) } }
    if reason == nil {
        guard let s = texts.first(where: { refusalText($0) }) else { return nil }
        said = s
        reason = STOP_REASONS.first { refusalText(s, $0) }
    }
    var quiet = (o["quiet_for"] as? NSNumber)?.doubleValue ?? (d["quiet_for"] as? NSNumber)?.doubleValue
    if quiet == nil, let s = said,
       let rx = try? NSRegularExpression(pattern: #"quiet for only (\d+)\s*(s|sec|min)"#, options: .caseInsensitive),
       let m = rx.firstMatch(in: s, range: NSRange(s.startIndex..., in: s)),
       let n = Range(m.range(at: 1), in: s), let u = Range(m.range(at: 2), in: s) {
        quiet = (Double(s[n]) ?? 0) * (s[u].lowercased().hasPrefix("m") ? 60 : 1)
    }
    let agent = firstText(o["agent"], d["agent_there"], awayAgent)
        ?? OTHER_AGENTS.first { a in said?.contains(AGENT_LABEL[a] ?? a) ?? false }
    var need = (o["need"] as? NSNumber)?.doubleValue ?? (o["quiet_needed"] as? NSNumber)?.doubleValue
        ?? (d["quiet_needed"] as? NSNumber)?.doubleValue
    if need == nil, let s = said,
       let rx = try? NSRegularExpression(pattern: #"needs (\d+) minutes?"#, options: .caseInsensitive),
       let m = rx.firstMatch(in: s, range: NSRange(s.startIndex..., in: s)), let n = Range(m.range(at: 1), in: s) {
        need = (Double(s[n]) ?? 2) * 60
    }
    // the agent's own processes there ("codex (4242)"): they end with it, no news
    let own = { (b: String) -> Bool in
        guard let a = agent, b.lowercased().hasPrefix("still running in this folder"), let c = b.firstIndex(of: ":") else { return false }
        return b[b.index(after: c)...].split(separator: ",").allSatisfy {
            $0.trimmingCharacters(in: .whitespaces).lowercased().hasPrefix(a) }
    }
    return StopRefusal(reason: reason ?? "not-quiet", agent: agent, machine: firstText(o["machine"], d["remote"], machine),
                       quiet: quiet, need: need ?? 120, said: said,
                       others: blockers.filter { $0 != said && !refusalText($0) && !own($0) },
                       seen: o["seen"] as? Bool != false && !(said?.contains("whether its turn ended") ?? false),
                       keys: (o["quit_keys"] as? [String]) ?? [])
}

/// The refusal in plain words, and what to do.
func stopWords(_ x: StopRefusal) -> (title: String, text: String) {
    let who = x.label + (x.machine.map { " on " + $0 } ?? "")
    if x.reason == "not-quiet" {
        return ("\(who) is still printing",
                "\(x.label)'s window \(x.machine == nil ? "" : "there ")showed new output "
                + (x.quiet.map { spanText($0) + " ago" } ?? "a moment ago")
                + ", so it may be in the middle of its work. aht ends it only after \(spanText(x.need)) without new output."
                + "\n\nWhat to do: wait until it has been quiet for \(spanText(x.need)), then choose Take Back again. "
                + "Or open its window, see what it does, and end it yourself.")
    }
    if x.reason == "no-reaction" {
        return ("\(who) did not quit",
                "aht pressed its quit keys" + (x.keys.isEmpty ? "" : " (\(x.keys.joined(separator: " ")))")
                + ", and \(x.label) still runs.\n\nWhat to do: open its window and end it yourself, then choose Take Back again.")
    }
    if !x.seen {
        return ("aht cannot tell whether \(x.label)'s last turn ended",
                "aht cannot see \(x.label)'s own last message" + (x.machine.map { " on " + $0 } ?? "")
                + ", so it cannot tell whether its turn ended, and it does not end an agent in the middle of a turn."
                + "\n\nWhat to do: open its window and look. If it is done, end it yourself there, then choose Take Back again.")
    }
    return ("\(x.label)'s last turn is not finished",
            "\(who) has not finished its last turn: it may still be working on it, or wait for an answer. aht does "
            + "not end an agent in the middle of a turn.\n\nWhat to do: open its window to see what it waits for; "
            + "answer it, or let it finish. Then choose Take Back again. Or end it yourself there.")
}

struct SearchHit: Identifiable, Hashable {
    let id = UUID()
    var machine: String? = nil      // another machine's hit; nil: this Mac's
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

/// `search … --json`'s results (with `--everywhere`, each row's `machine`
/// names the machine it came from, null for this Mac): this Mac's first.
func searchHits(_ d: [String: Any]) -> [SearchHit] {
    let hits = ((d["results"] as? [[String: Any]]) ?? []).map { r -> SearchHit in
        let restore = r["restore"] as? [String: Any]
        return SearchHit(
            machine: r["machine"] as? String,
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
    return hits.filter { $0.machine == nil } + hits.filter { $0.machine != nil }
}

/// `search --everywhere --json`'s `machines`: a line for each one that
/// could not be searched (it did not answer, or has no index).
func searchMissed(_ d: [String: Any]) -> [String] {
    ((d["machines"] as? [[String: Any]]) ?? []).compactMap(missedLine)
}

/// The machines that were searched, by name.
func searchAsked(_ d: [String: Any]) -> [String] {
    ((d["machines"] as? [[String: Any]]) ?? []).filter { missedLine($0) == nil }
        .compactMap { $0["machine"] as? String }
}

func missedLine(_ m: [String: Any]) -> String? {
    let name = m["machine"] as? String ?? "?"
    let err = (m["error"] as? String).map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
        .flatMap { $0.isEmpty ? nil : $0 }
    let why: String
    if m["reachable"] as? Bool == false {
        why = err.map { "it did not answer (\($0))" } ?? "it did not answer"
    } else if m["indexed"] as? Bool == false {
        why = "no search index (aht is not installed there)"
    } else if let e = err {
        why = e
    } else {
        return nil
    }
    return "Not searched on \(name): \(why)"
}

/// "Nothing found for …" after a search, and where it looked.
func nothingFound(_ q: String, everywhere: [String]?) -> String {
    guard let names = everywhere, !names.isEmpty else { return "Nothing found for “\(q)”." }
    let on = names.count == 1 ? names[0]
        : names.dropLast().joined(separator: ", ") + " or " + names.last!
    return "Nothing found for “\(q)”, here or on \(on)."
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
    var replaceThere = false        // the copy there changed: set it aside (--replace-there)
    var dry: [String: Any] = [:]    // the dry run: paths, names, line endings, git
    var blocked = false             // names or the folder there stand in the way
    var agent = "claude"            // Agent there: Claude Code's own session, or another agent (--agent)
    var toPC = false                // a Windows PC: no session starts there, its tray offers Continue here
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
                   "agy": "Antigravity", "vibe": "Mistral Vibe", "gemini": "Gemini",
                   "opencode": "OpenCode", "cursor": "Cursor", "copilot": "Copilot"]

/// The agents a project can be switched to, in the menu's order.
let SWITCH_AGENTS = ["claude", "kimi", "codex", "agy", "vibe"]

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
/// session is told what changed without a turn. `machine`: the work was done
/// there (Pick Up), so the session named is that machine's.
func switchText(_ d: [String: Any], mode: String, hook: Bool, machine: String? = nil) -> String {
    let target = d["target"] as? String ?? ""
    let label = AGENT_LABEL[target] ?? target
    let src = (d["source"] as? [String: Any]) ?? [:]
    let from = AGENT_LABEL[src["agent"] as? String ?? ""] ?? "the other agent"
    let title = (src["title"] as? String).map { " (“\($0)”)" } ?? ""
    let on = machine.map { " on \($0)" } ?? ""
    var body: String
    switch mode {
    case "back":
        body = "\(label) goes on in its own session, where it left off. It reads only "
            + "what happened while \(from) had the project\(on)\(title): the latest exchanges, "
            + "the files changed and the commits made."
    case "resume":
        body = "\(label) goes on in its own latest session here. It reads only what "
            + "happened since: the work of the latest \(from) session\(on)\(title), the files "
            + "changed and the commits made."
    default:
        // Kimi below never-ask reads it once the first message is pasted
        let reads = target == "kimi" && !kimiReads(d) ? "reads it once you paste the first message" : "reads it first"
        body = machine == nil
            ? "\(label) continues the work of the latest \(from) session\(title) in a new "
              + "session. aht writes a summary of where things stood into the project, and "
              + "\(label) \(reads)."
            : "\(label) continues the work of the \(from) session\(on)\(title) in a new "
              + "session here. aht writes a summary of where things stood into the project, "
              + "and \(label) \(reads)."
    }
    body += " The \(from) session\(on) stays as it is."
    if target == "kimi" && !kimiReads(d) {
        body += "\n\n" + KIMI_OPENS
    } else if target == "kimi" {
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
    // Kimi below never-ask: its window opened without reading; the line to
    // paste is shown under this, with a Copy button (FirstPromptBox)
    if kimiFirst(d) != nil && d["mode"] as? String != "brief-only" {
        said = "\(label)'s window is open. The summary is in the project: \(file)"
    }
    if let f = fell { said = f + "\n\n" + said }
    for w in (d["warnings"] as? [String]) ?? [] { said += "\n⚠ " + w }
    return said
}

// ---- Kimi below never-ask ----------------------------------------------------
// Kimi's run of its own that reads the summary first (`-p`) always runs in
// never-ask, so the core uses it only at never-ask (`kimi_reads: true`). Below
// it, Switch, Hand Back and Pick Up → Open in Kimi open Kimi's own session
// without that run (`kimi_reads: false`) and give `first_prompt`: the one line
// that asks it to read the summary, for the user to paste.

let KIMI_OPENS = "Kimi opens without reading the summary: its run that reads it first works only in "
    + "never-ask mode, so you paste the first message aht shows you."
let KIMI_PASTE = "Kimi opens without reading the summary. Paste this as your first message:"

/// Whether Kimi reads the summary in a run of its own first: the core's
/// `kimi_reads` (when the answer speaks of Kimi), else Kimi's level from the
/// dry run (never-ask: it does); an older core that says neither: it does.
func kimiReads(_ d: [String: Any]) -> Bool {
    let own = firstText((d["perm"] as? [String: Any])?["agent"], d["target"])
    if let b = d["kimi_reads"] as? Bool, own == nil || own == "kimi" { return b }
    return permInfo(d, agent: "kimi").map { $0.level == "never" } ?? true
}

/// An answer that opened (or starts) Kimi without its reading run: the line
/// to paste as its first message; nil otherwise.
func kimiFirst(_ d: [String: Any]) -> String? {
    guard d["kimi_reads"] as? Bool == false,
          let t = (d["first_prompt"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines),
          !t.isEmpty else { return nil }
    return t
}

// ---- the permission level the next agent starts in --------------------------
// Switch, Hand Back, Pick Up, Bring Here, Hand Over and the night shift (and
// their dry runs) carry `perm`: {agent, level, sandbox, flags, from, read,
// text}. Levels in aht's words: ask (each agent's default), edits (edits
// run, commands ask), auto (routine runs, risky asks), never (never asks).
// `read`: the level of the session the work comes from; `from`: how aht read
// it (command_line, rollout, transcript, settings, relay, unknown). The next
// agent starts in its own equivalent of it, or in the next stricter level it
// has (`agent_permissions`: "follow", a fixed level, or "max:<level>"); aht
// never raises it by itself. Never-ask is shown with a caution, not stopped:
// the user chose it.

let PERM_LEVELS = ["ask", "edits", "auto", "never"]
let PERM_NAME = ["ask": "ask mode", "edits": "edits mode", "auto": "auto mode", "never": "never-ask mode"]
let PERM_SAYS = ["ask": "It asks before it acts, as it does by default.",
                 "edits": "Edits run without asking; commands ask first.",
                 "auto": "Routine steps run without asking; risky ones ask first.",
                 "never": "It never asks: every edit and command runs."]
/// Codex's never-ask flags that keep its sandbox (Settings ▸ Permissions).
let CODEX_SANDBOXED = ["-a", "never", "-s", "workspace-write"]
/// Settings ▸ Permissions: what the next agent starts in.
let PERM_CHOICES = [("follow", "Follow the session"), ("ask", "Always: ask mode"),
                    ("edits", "Always: edits mode"), ("auto", "Always: auto mode"),
                    ("never", "Always: never-ask mode"), ("max:edits", "At most: edits mode"),
                    ("max:auto", "At most: auto mode")]

func permRank(_ level: String?) -> Int { level.flatMap { PERM_LEVELS.firstIndex(of: $0) } ?? -1 }

/// The Permissions setting: "follow", a level, or "max:<level>".
func permSetting(_ config: [String: Any]) -> String {
    let v = config["agent_permissions"] as? String ?? "follow"
    return PERM_NAME[v] != nil || (v.hasPrefix("max:") && PERM_NAME[String(v.dropFirst(4))] != nil) ? v : "follow"
}

/// A level in words: "never-ask mode inside its sandbox".
func permName(_ level: String, sandbox: Bool = false) -> String {
    (PERM_NAME[level] ?? level) + (sandbox && level == "never" ? " inside its sandbox" : "")
}

/// The level an agent starts in, from a dry run. `text`: the core's
/// sentence, shown as given; `was`: the level of the session the work comes
/// from; `fell`: no exact match, so a stricter level; `other`: the core named
/// no level for this agent (Pick Up without --open), only the level of the
/// session there (`source.perm`), so its flags are its own (nil).
struct PermInfo: Equatable {
    let level: String
    let sandbox: Bool
    let flags: [String]?
    let text: String?
    let was: String
    let fell: Bool
    let other: Bool
}

/// nil: no level known (an older core, or nothing starts: Summary Only).
func permInfo(_ d: [String: Any], agent: String?, setting: String = "follow") -> PermInfo? {
    let own = agent.flatMap { (d["perms"] as? [String: Any])?[$0] as? [String: Any] }
    var p = own ?? (d["perm"] as? [String: Any])
    if let q = p, own == nil, let a = agent, let planned = firstText(q["agent"], d["target"]), planned != a { p = nil }
    var other = false
    if p == nil, let src = (d["source"] as? [String: Any])?["perm"] as? [String: Any],
       let lv = src["level"] as? String, PERM_NAME[lv] != nil {
        p = ["level": lv, "sandbox": src["sandbox"] as? Bool ?? false, "read": lv, "from": src["from"] ?? "unknown"]
        other = true
    }
    guard let p = p, let level = p["level"] as? String, PERM_NAME[level] != nil else { return nil }
    let text = other ? nil : (p["text"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)
    let said = (text?.isEmpty ?? true) ? nil : text
    let was = (p["read"] as? String).flatMap { PERM_NAME[$0] != nil ? $0 : nil } ?? level
    let cap = setting.hasPrefix("max:") ? String(setting.dropFirst(4)) : nil
    let meant = PERM_NAME[setting] != nil ? setting : cap.map { permRank(was) > permRank($0) ? $0 : was } ?? was
    let fell = !other && (said.map { $0.contains("the next stricter level") } ?? (permRank(level) < permRank(meant)))
    var flags: [String]? = nil
    if !other { flags = ((p["flags"] as? [Any]) ?? []).map { "\($0)" } }
    return PermInfo(level: level, sandbox: p["sandbox"] as? Bool == true && level == "never", flags: flags,
                    text: said, was: was, fell: fell, other: other)
}

/// A flag as a shell would need it written.
func shellWord(_ w: String) -> String {
    w.range(of: "^[A-Za-z0-9_@%+=:,./-]+$", options: .regularExpression) != nil ? w
        : "'" + w.replacingOccurrences(of: "'", with: "'\\''") + "'"
}

/// The line (the core's text as given; words of our own where it gave
/// none), the no-exact-match note, and the flags in words. `source`: the
/// agent of the session the work comes from, which `leaving` names (its
/// label, or nil); `on`: the machine the next agent starts on.
func permWords(_ p: PermInfo, agent: String, source: String? = nil, on: String? = nil,
               leaving: (String?) -> String) -> (line: String, fell: String?, flags: String) {
    let label = AGENT_LABEL[agent] ?? agent
    let who = label + (on.map { " on \($0)" } ?? "")
    let them = leaving(source.map { AGENT_LABEL[$0] ?? $0 })
    let line: String
    if let t = p.text {
        line = t
    } else if p.other {
        line = them.prefix(1).uppercased() + them.dropFirst() + " runs in " + permName(p.was, sandbox: p.sandbox)
            + ": \(who) starts in its own equivalent, or the next stricter level it has."
    } else if p.fell {
        line = "\(who) starts in \(permName(p.level, sandbox: p.sandbox)), the next stricter level it has "
            + "(\(them) runs in \(PERM_NAME[p.was] ?? p.was))."
    } else {
        line = "\(who) starts in \(permName(p.level, sandbox: p.sandbox)), like \(them)."
    }
    let fell = p.fell ? "No exact match: \(label) starts in the next stricter level it has." : nil
    let flags = p.flags.map { $0.isEmpty ? "No flags: \(label)'s own default." : "Flags: " + $0.map(shellWord).joined(separator: " ") }
        ?? "\(label) gets its own flags for it."
    return (line, fell, (PERM_SAYS[p.level] ?? "") + " " + flags)
}

/// Codex's never-ask flags as set (`agent_permission_flags`.codex.never):
/// "full" (the built-in full bypass), "sandbox", or "own" (other flags).
func codexNever(_ config: [String: Any]) -> String {
    let f = (((config["agent_permission_flags"] as? [String: Any])?["codex"] as? [String: Any])?["never"] as? [Any])?
        .map { "\($0)" } ?? []
    return f.isEmpty ? "full" : f == CODEX_SANDBOXED ? "sandbox" : "own"
}

/// `agent_permission_flags` with Codex's never-ask choice made; every other
/// agent's and level's flags as they were.
func withCodexNever(_ config: [String: Any], sandbox: Bool) -> [String: Any] {
    var all = (config["agent_permission_flags"] as? [String: Any]) ?? [:]
    var codex = (all["codex"] as? [String: Any]) ?? [:]
    if sandbox { codex["never"] = CODEX_SANDBOXED } else { codex.removeValue(forKey: "never") }  // the built-in full bypass
    if codex.isEmpty { all.removeValue(forKey: "codex") } else { all["codex"] = codex }
    return all
}

// ---- Pick Up and Leave a Note: work across machines -------------------------
// `pickup --json` = {match: {path, how, candidates}, source, git, brief,
// relay, applied, opened, command_line} (and `sessions`, `mode`, `blockers`,
// `warnings`, `error`); `leave-note --json` the same with `note_for`. Git
// moves the files; these move only the context.

/// One item of a project's Machines menu: Pick Up from M, Leave a Note on M,
/// and Hand Back to M while a pickup from M is open (a note in back mode).
struct MachineItem: Hashable {
    let title: String
    let machine: String
    let kind: String                // "back" | "pickup" | "note"
}

/// The machines Pick Up, Leave a Note and Bring Here can ask: Mac and Linux
/// ones.  A Windows PC starts these itself, also one that answers (that one
/// takes Hand Over, Take Back, Watch, search and Check from here): the core
/// refuses them for every PC.
func askableMachines(_ ms: [Machine]) -> [String] {
    ms.filter { $0.asks && $0.system != "Windows" }.map { $0.name }
}

/// A machine set up here under `name` is a Windows PC.
func machineIsPC(_ name: String?, _ ms: [Machine]) -> Bool {
    ms.first { $0.name == name }?.system == "Windows"
}

/// The board's Open Session for a handed-over session: not for one on a PC,
/// where no session runs for aht to open (`attach` refuses it; the PC's tray
/// offers Continue here).
func boardOpens(_ r: BoardRow, _ p: Project, _ ms: [Machine]) -> Bool {
    !p.pcAway(ms) && !machineIsPC(r.machine, ms)
}

/// The Machines menu: Hand Back first, then Pick Up from each machine, then
/// Leave a Note on each.
func machineItems(_ p: Project, _ machines: [String]) -> [MachineItem] {
    var items: [MachineItem] = []
    if let from = p.pickedUpFrom {
        items.append(MachineItem(title: "Hand Back to \(from)…", machine: from, kind: "back"))
    }
    items += machines.map { MachineItem(title: "Pick Up from \($0)…", machine: $0, kind: "pickup") }
    items += machines.map { MachineItem(title: "Leave a Note on \($0)…", machine: $0, kind: "note") }
    return items
}

/// The line over a project that work came to from another machine:
/// "pc left a note at 16:40: Codex worked there from 14:10 to 16:40".
func incomingLine(_ i: Incoming) -> String {
    let at = clock(i.at).isEmpty ? "" : " at " + clock(i.at)
    let who = i.agent.map { AGENT_LABEL[$0] ?? $0 }
    let (a, b) = (clock(i.workedFrom), clock(i.workedTo))
    let span = !a.isEmpty && !b.isEmpty && a != b ? " from \(a) to \(b)" : ""
    switch i.kind {
    case "pickup":
        return "Picked up from \(i.name)\(at)" + (who.map { ", where \($0) worked" } ?? "")
    case "back":
        return "\(i.name) handed this project back\(at)" + (who.map { ": \($0) worked there\(span)" } ?? "")
    default:
        return "\(i.name) left a note\(at)" + (who.map { ": \($0) worked there\(span)" } ?? "")
    }
}

/// `match`: the folder there, how it was found, and the folders it could be
/// when that is not clear (paths, or {path, how}).
struct ThereMatch: Hashable {
    let path: String?
    let how: String?
    let candidates: [String]
}

func thereMatch(_ d: [String: Any]) -> ThereMatch {
    let m = (d["match"] as? [String: Any]) ?? [:]
    let cands = ((m["candidates"] as? [Any]) ?? []).compactMap { c in
        (c as? String) ?? ((c as? [String: Any])?["path"] as? String)
    }
    return ThereMatch(path: (m["path"] as? String).flatMap { $0.isEmpty ? nil : $0 },
                      how: m["how"] as? String, candidates: cands)
}

/// How the folder there was found, in words, and whether that is sure: its
/// project id, or a folder the user picked. Anything else is confirmed first.
func matchHow(_ how: String?) -> (text: String, sure: Bool) {
    let h = (how ?? "").lowercased().replacingOccurrences(of: "-", with: "_")
        .replacingOccurrences(of: " ", with: "_")
    switch h {
    case "id", "project_id", "marker", "registry": return ("by its project id", true)
    case "there", "picked", "user", "given", "chosen": return ("as picked", true)
    case "origin", "git", "git_origin": return ("by the same git origin and first commit", false)
    case "path", "same_path": return ("at the same path", false)
    case "home", "home_relative", "relative": return ("at the same place in the home folder", false)
    case "": return ("", false)
    default: return ("by " + (how ?? ""), false)
    }
}

/// "Found on box by its project id: /home/me/code/api" ("" when nothing was).
func matchLine(_ mt: ThereMatch, machine: String) -> String {
    guard let path = mt.path else { return "" }
    let how = matchHow(mt.how).text
    return how.isEmpty ? "The folder on \(machine): \(path)" : "Found on \(machine) \(how): \(path)"
}

/// Why the folder there is not clear ("" when it is).
func matchProblem(_ mt: ThereMatch, machine: String) -> String {
    if mt.path != nil { return "" }
    switch mt.candidates.count {
    case 0: return "aht found no folder for this project on \(machine). Type its path there:"
    case 1: return "One folder on \(machine) could be this project. Is it the one?"
    default: return "\(mt.candidates.count) folders on \(machine) could be this project. "
        + "Pick the one to go on with:"
    }
}

/// A session there, as `pickup --json` lists them (newest first).
struct ThereSession: Identifiable, Hashable {
    let id: String
    let agent: String
    let title: String
    let updated: Double?
    let state: String?              // "working" | "open" (in a window there) | nil
}

func thereSessions(_ d: [String: Any]) -> [ThereSession] {
    let src = (d["source"] as? [String: Any]) ?? [:]
    let rows = (d["sessions"] as? [[String: Any]]) ?? (src["sessions"] as? [[String: Any]]) ?? []
    return rows.compactMap { s in
        let id = s["id"] as? String ?? s["session"] as? String ?? ""
        guard !id.isEmpty else { return nil }
        var st = (s["state"] ?? s["status"]) as? String
        if st == nil { st = s["working"] as? Bool == true ? "working" : s["open"] as? Bool == true ? "open" : nil }
        return ThereSession(id: id, agent: s["agent"] as? String ?? "?",
                            title: (s["title"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? String(id.prefix(8)),
                            updated: ((s["updated"] ?? s["last_t"] ?? s["t"]) as? NSNumber)?.doubleValue,
                            state: ["working", "open"].contains(st ?? "") ? st : nil)
    }
}

/// The session there the summary is made of: the one picked, else the core's.
func thereSession(_ d: [String: Any], picked: String?) -> String? {
    picked ?? ((d["source"] as? [String: Any])?["session"] as? String)
}

/// The git warning: what to do so the files match, in the core's words ("On
/// box: branch fix-login, 2 commits not pushed, 6 files not committed. Commit
/// and push there, then pull here."); nil when git has nothing to say.
func gitWarning(_ d: [String: Any], machine: String) -> String? {
    let g = d["git"]
    if let s = g as? String { return s.isEmpty ? nil : s }
    guard let gd = g as? [String: Any] else { return nil }
    for k in ["warning", "advice", "text", "say", "note"] {
        if let s = gd[k] as? String, !s.isEmpty { return s }
    }
    if let lines = (gd["lines"] ?? gd["warnings"]) as? [String], !lines.isEmpty {
        return lines.joined(separator: " ")
    }
    // only the two sides: say what is not where it can be pulled from
    let side = { (x: Any?, name: String) -> String? in
        guard let s = x as? [String: Any] else { return nil }
        var bits = (s["branch"] as? String).map { ["branch " + $0] } ?? []
        let named = bits.count
        if let a = s["ahead"] as? Int, a > 0 { bits.append("\(a) commit\(a == 1 ? "" : "s") not pushed") }
        if let n = s["dirty"] as? Int, n > 0 { bits.append("\(n) file\(n == 1 ? "" : "s") not committed") }
        return bits.count == named ? nil : "On \(name): " + bits.joined(separator: ", ") + "."
    }
    let said = [side(gd["there"], machine), side(gd["here"], "this Mac")].compactMap { $0 }
    return said.isEmpty ? nil : said.joined(separator: " ")
}

/// The summary: its Markdown (a dry run) and its file (after --apply).
func pickupBrief(_ d: [String: Any]) -> (text: String?, file: String?) {
    var text: String?, file: String?
    if let b = d["brief"] as? [String: Any] {
        text = (b["text"] ?? b["markdown"]) as? String
        file = (b["file"] ?? b["path"]) as? String
    } else if let s = d["brief"] as? String, !s.isEmpty {
        if !s.contains("\n") && s.hasSuffix(".md") { file = s } else { text = s }
    }
    if text == nil { text = (d["brief_text"] ?? d["markdown"]) as? String }
    if file == nil { file = (d["brief_file"] ?? d["file"]) as? String }
    return (text.flatMap { $0.isEmpty ? nil : $0 }, file.flatMap { $0.isEmpty ? nil : $0 })
}

/// The core's warnings but the git warning, which the sheet shows in its own box.
func otherWarnings(_ d: [String: Any]) -> [String] {
    let git = (d["git"] as? [String: Any])?["warning"] as? String
    return ((d["warnings"] as? [String]) ?? []).filter { $0 != git }
}

/// The line that starts the agent here with the summary (after --apply).
func startLine(_ d: [String: Any]) -> String? {
    ((d["command_line"] ?? d["start_line"]) as? String).flatMap { $0.isEmpty ? nil : $0 }
        ?? (d["start_line"] as? String).flatMap { $0.isEmpty ? nil : $0 }
}

/// Back mode: the work comes back to where it left from (an open relay to
/// that machine), so the session it left goes on and reads only what changed.
func pickupIsBack(_ d: [String: Any]) -> Bool {
    if let m = d["mode"] as? String { return m == "back" }
    if let b = d["back"] as? Bool { return b }
    return (d["relay"] as? [String: Any])?["kind"] as? String == "back"
}

/// The agent that goes on here in back mode: the one the work left.
func pickupTarget(_ d: [String: Any]) -> String? {
    if let t = d["target"] as? String, !t.isEmpty { return t }
    for k in ["origin", "resume", "note_for"] {
        if let a = (d[k] as? [String: Any])?["agent"] as? String { return a }
    }
    return nil
}

/// The agent Open in … offers first: in back mode the one the work left,
/// else the one that worked there if it is installed here, else the first.
func pickupAgent(_ d: [String: Any], installed: [String]) -> String? {
    if pickupIsBack(d), let t = pickupTarget(d) { return t }
    let src = (d["source"] as? [String: Any])?["agent"] as? String
    if let s = src, installed.contains(s) { return s }
    return installed.first ?? src
}

/// Open in …: the switch dialog's words for the agent picked.
func pickupOpenText(_ d: [String: Any], agent: String, machine: String, hook: Bool) -> String {
    var x = d
    if firstText(d["target"]) != agent { x["kimi_reads"] = nil }   // it spoke of the agent planned
    x["target"] = agent
    x["warnings"] = []                  // the sheet shows them once, above
    return switchText(x, mode: pickupIsBack(d) ? "back" : "new", hook: hook, machine: machine)
}

/// What opening costs: one turn of the agent; nil for a Claude session that
/// hears through aht's hook (the switch dialog's words say so already).
func openCost(_ agent: String, back: Bool, hook: Bool, machine: String? = nil, kimiReads: Bool = true) -> String? {
    let label = AGENT_LABEL[agent] ?? agent
    let copy = "Copy the Start Line writes the summary here and a copy of it on \(machine ?? "the other machine"), "
        + "and puts the line that starts \(label) with it on the clipboard"
    if agent == "kimi" && !kimiReads {
        return "Reading it is Kimi's first turn, which uses tokens. " + copy + "; nothing runs until you "
            + "paste it, and then you paste the first message aht shows you into Kimi."
    }
    if agent == "kimi" {
        return "Kimi reads the summary in a run of its own first, for Open in and for Copy the Start "
            + "Line alike: that turn uses tokens. " + copy + "; nothing else runs until you paste it."
    }
    if agent == "claude" && back && hook { return nil }
    return "Open in \(label) runs that one turn, which uses tokens. " + copy + "; nothing runs until "
        + "you paste it."
}

/// The session a note is for there (back mode): its agent, id and title.
func noteFor(_ d: [String: Any]) -> (agent: String?, session: String, title: String?)? {
    if let n = d["note_for"] as? [String: Any], let s = (n["session"] ?? n["id"]) as? String {
        return (n["agent"] as? String, s, n["title"] as? String)
    }
    if let s = d["note_for"] as? String, !s.isEmpty { return (pickupTarget(d), s, nil) }
    return nil
}

/// Who reads the note there.
func noteReader(_ d: [String: Any], machine: String) -> String {
    guard let n = noteFor(d) else {
        return "A full summary for whoever goes on there. It waits in the project's "
            + ".aht/handover folder on \(machine); nothing runs there, so it uses no tokens."
    }
    let label = n.agent.map { AGENT_LABEL[$0] ?? $0 } ?? "The agent"
    return "For \(label)'s own session on \(machine)" + (n.title.map { " (“\($0)”)" } ?? "")
        + ": only what changed here. "
        + noteReads(n.agent, on: " on \(machine)",
                    file: "the note (in the project's .aht/handover folder there)")
        + " Nothing runs there, so leaving it uses no tokens."
}

/// The arguments of the dry run, or of --apply (with Open in …'s agent).
/// `--agent` picks the session there (that session's agent); `--open` the
/// agent that starts here. Copy the Start Line (`noWindow`) is --open X
/// --no-window: the summary, its copy there, and the line, with no terminal.
func pickupArgs(_ v: PickupView, apply: Bool = false, open: String? = nil,
                noWindow: Bool = false) -> [String] {
    var a = v.kind == "note" ? ["leave-note", v.project.path, "--on", v.machine]
                             : ["pickup", v.project.path, "--from", v.machine]
    if let t = v.there { a += ["--there", t] }
    if v.kind == "pickup" {
        if let s = v.session { a += ["--session", s] }
        if let g = v.agent { a += ["--agent", g] }
        if let o = open { a += ["--open", o] }
    }
    return a + (apply ? ["--apply"] : []) + (noWindow && open != nil ? ["--no-window"] : []) + ["--json"]
}

/// What stands in the way, in the core's own words; nil when nothing does.
func pickupProblems(_ d: [String: Any]) -> String? {
    if d.isEmpty { return "aht gave no answer — see the log (Settings)." }
    var lines = (d["blockers"] as? [String]) ?? []
    if let e = d["error"] as? String, !e.isEmpty { lines.append(e) }
    return lines.isEmpty ? nil : lines.map { "• " + $0 }.joined(separator: "\n\n")
}

/// The sheet can go on: the folder there is clear (and confirmed when it was
/// not found by its project id) and nothing stands in the way.
func pickupReady(_ v: PickupView) -> Bool {
    let mt = thereMatch(v.dry)
    guard !v.loading, !v.applying, v.done == nil, let _ = mt.path,
          pickupProblems(v.dry) == nil else { return false }
    return matchHow(mt.how).sure || v.confirmed || v.there != nil
}

/// What Pick Up did, from `pickup --apply --json`.
func pickupDoneText(_ d: [String: Any], machine: String, project: String, copied: Bool) -> String {
    if let why = pickupProblems(d) { return "Pick Up did not go through:\n\n" + why }
    let file = pickupBrief(d).file.map { tilde(summaryFile($0, in: project)) }
    let opened = (d["opened"] as? String).flatMap { $0.isEmpty ? nil : $0 }
        ?? (d["opened"] as? Bool == true ? pickupTarget(d) ?? "" : nil)
    var said: String
    if let o = opened, kimiFirst(d) != nil {
        // Kimi below never-ask: open, not having read it (FirstPromptBox)
        said = "Picked up from \(machine): \(AGENT_LABEL[o] ?? "Kimi Code") is open here. The summary is here"
            + (file.map { ": \($0)." } ?? ".")
    } else if let o = opened {
        let label = AGENT_LABEL[o] ?? (o.isEmpty ? "The agent" : o)
        said = pickupIsBack(d)
            ? "Picked up from \(machine): \(label)'s own session is open again and reads what "
              + "changed first."
            : "Picked up from \(machine): \(label) is open here and reads the summary first"
              + (file.map { ": \($0)" } ?? ".")
    } else {
        said = "Picked up from \(machine). The summary is here" + (file.map { ": \($0)." } ?? ".")
            + " Nothing was opened."
        if copied {
            said += " The start line is on the clipboard: paste it into a terminal to start."
        }
    }
    for w in otherWarnings(d) { said += "\n⚠ " + w }
    return said
}

/// What Leave a Note (or Hand Back to M) did, from `leave-note --apply --json`.
func noteDoneText(_ d: [String: Any], machine: String) -> String {
    if let why = pickupProblems(d) { return "The note was not left:\n\n" + why }
    let file = pickupBrief(d).file.map { (($0 as NSString).lastPathComponent) }
    var said: String
    if let n = noteFor(d) {
        let label = n.agent.map { AGENT_LABEL[$0] ?? $0 } ?? "the agent"
        said = "Handed back to \(machine)" + (file.map { " (\($0))" } ?? "") + ", for \(label)'s own "
            + "session there. " + noteReads(n.agent, on: " on \(machine)",
                                            file: file.map { ".aht/handover/" + $0 })
    } else {
        said = "The note is on \(machine)" + (file.map { ": .aht/handover/\($0)" } ?? "")
            + ". Nothing runs there; Pick Up from this Mac there brings the work over."
    }
    for w in otherWarnings(d) { said += "\n⚠ " + w }
    return said
}

/// The part of a path under its home folder: "code/api" for /home/me/code/api,
/// /Users/me/code/api and C:\Users\me\code\api; nil outside a home folder.
func homeRelative(_ path: String) -> String? {
    let c = path.replacingOccurrences(of: "\\", with: "/")
        .split(separator: "/", omittingEmptySubsequences: false).map(String.init)
    var n = 0
    if c.count > 3 && c[0].isEmpty && (c[1] == "Users" || c[1] == "home") {
        n = 3
    } else if c.count > 3 && c[0].count == 2 && c[0].hasSuffix(":") && c[1].lowercased() == "users" {
        n = 3
    } else if c.count > 2 && c[0].isEmpty && c[1] == "root" {
        n = 2
    }
    let rest = c.dropFirst(n).filter { !$0.isEmpty }
    return n == 0 || rest.isEmpty ? nil : rest.joined(separator: "/")
}

/// The folders here that may be a folder on another machine, likeliest
/// first: the same path, the same place in the home folder, the same name.
func localTwins(_ there: String, _ here: [String], home: String = HOME,
                exists: (String) -> Bool = { FileManager.default.fileExists(atPath: $0) }) -> [String] {
    if here.contains(there) { return [there] }
    if let rel = homeRelative(there) {
        let p = home + "/" + rel
        if here.contains(p) || exists(p) { return [p] }
    }
    let name = there.replacingOccurrences(of: "\\", with: "/").split(separator: "/").last.map(String.init) ?? ""
    return name.isEmpty ? [] : here.filter { ($0 as NSString).lastPathComponent == name }
}

/// Pick Up from M and Leave a Note on M (Hand Back to M is a note too): the
/// dry run the sheet shows, what the user picked in it, and what --apply did.
struct PickupView: Identifiable {
    let id = UUID()
    let project: Project
    let machine: String
    let kind: String                // "pickup" | "note"
    var back = false                // asked as Hand Back to M
    var loading = true
    var dry: [String: Any] = [:]
    var said = ""                   // what aht said when it gave no JSON
    var there: String?              // --there: the folder there, picked
    var session: String?            // --session: a session there, picked
    var agent: String?              // --agent: that session's agent
    var confirmed = false           // a folder not found by its project id: "this is it"
    var typed = ""                  // the folder there, typed when none was found
    var open: String?               // Open in …: the agent picked
    var applying = false
    var done: [String: Any]?        // what --apply answered
    var copied = false              // its start line went to the clipboard
}

/// The sheet's title.
func pickupTitle(_ v: PickupView) -> String {
    let name = v.project.name
    if v.kind == "note" {
        return v.back || noteFor(v.dry) != nil ? "Hand “\(name)” back to \(v.machine)?"
                                               : "Leave a note about “\(name)” on \(v.machine)?"
    }
    return "Pick up “\(name)” from \(v.machine)?"
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
    var perm: [String: Any]? = nil  // the level it runs in ({level, sandbox, flags}), unattended
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
    var started: [String: Any] = [:]    // what starting it answered: each agent's level (`perms`)
}

/// The second opinion's dry run (`second-opinion <path> --task … --dry-run
/// --json`: {perms: {agent: perm}, warnings, blockers}) for the task typed:
/// the level each agent works in, before anything starts.
struct OpinionDry {
    let path: String
    let task: String
    let d: [String: Any]
}

/// What the dialog shows beside Start, from a dry run or from what starting
/// it answered: the agents with a level (their perm.text through PermLine),
/// the warnings (Kimi left out below never-ask, say), and what stops the task.
/// `typed`: a task is typed; with none, the core's "say what both should do
/// (--task)" is no news.
func opinionDryArgs(_ path: String, task: String) -> [String] {
    ["second-opinion", path, "--task=" + task.trimmingCharacters(in: .whitespacesAndNewlines), "--dry-run", "--json"]
}

func opinionLevels(_ d: [String: Any], typed: Bool) -> (agents: [String], warnings: [String], blockers: [String]) {
    let agents = ((d["perms"] as? [String: Any]) ?? [:]).filter { $0.value is [String: Any] }.map { $0.key }.sorted()
    let stops = nameList(d["blockers"]).filter { typed || !$0.contains("--task") }
    return (agents, nameList(d["warnings"]), stops)
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
    var dry: [String: Any] = [:]    // a dry run: the level the session there starts in (`perm`)
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
    @Published var firstPrompts: [String: String] = [:] // … and Kimi's first message to paste (below never-ask)
    @Published var opinionDry: OpinionDry?           // the second opinion's dry run for the task typed
    private var opinionAsked = 0
    private var opinionWait: DispatchWorkItem?
    @Published var checks: [String: [Check]] = [:]  // per machine
    @Published var movers: [String: Mover] = [:]    // what each machine's check said copies files
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
    @Published var searchEverywhere = UserDefaults.standard.bool(forKey: "searchEverywhere") {
        didSet { if !demo { UserDefaults.standard.set(searchEverywhere, forKey: "searchEverywhere") } }
    }
    @Published var searchMisses: [String] = []  // machines that could not be searched
    @Published var searchedOn: [String]?        // … and the ones that were (nil: this Mac only)
    var demo = false                            // a snapshot's made-up rows: nothing asks the core
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
    @Published var problems: ProblemsView?      // Recent problems
    @Published var offsite: OffsiteView?        // Fetch Backups From…
    @Published var pickup: PickupView?          // Pick Up from M, Leave a Note on M
    @Published var bring: BringView?            // Bring Here from M
    @Published var peek: PeekView?              // Peek: the agent's window there, its last lines
    @Published var sendBack: SendBackView?      // Send Back to M
    @Published var pathsOf: [String: PathMap] = [:]  // each machine's folders (`remote paths --json`)
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
        guard !discovering, !demo else { done?(); return }
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
    var machines: [Machine] { machinesFrom(handover["remotes"]) }
    /// Search can also ask the other machines (set up, and reachable from here).
    var canSearchEverywhere: Bool { canReach && !machines.isEmpty }
    /// The machine "Hand Over" and "Keep in Sync" go to.
    var machine: String? { handover["default_remote"] as? String }
    /// handover_transfer: auto, rsync or aht.
    var transferMode: String {
        let t = text("handover_transfer", "auto")
        return TRANSFER_CHOICES.contains { $0.0 == t } ? t : "auto"
    }
    /// Which mover each machine gets, as Settings says it.
    var moversLine: String {
        moversText(machines, mode: transferMode, hereRsync: handover["rsync"] as? String, known: movers)
    }
    /// What the machine's check said copies its files, while the setting is
    /// still the one it was asked under.
    func checkedMover(_ name: String) -> String? {
        movers[name].flatMap { $0.mode == transferMode ? $0.transfer : nil }
    }
    var backends: [Backend] { backendRows(status) }
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
    /// A session's start copies the folder (see checkpointOnStart).
    var checkpointsOn: Bool { checkpointOnStart(status, config) }
    /// …switched here: the setting is saved; until the core is read again,
    /// its answer is taken to follow.
    func setCheckpoints(_ on: Bool) {
        if var e = status["effective"] as? [String: Any], e["checkpoint_on_start"] is Bool {
            e["checkpoint_on_start"] = on
            status["effective"] = e
        }
        set("checkpoints", on ? "true" : "false")
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
            self.firstPrompts[path] = nil
        }
    }

    /// Hand Over: the dry run, then the sheet. Over a synced copy that was
    /// changed on the other machine the dry run blocks; Bring Them Here takes
    /// that work first, or Replace Them hands over with `--replace-there`
    /// (`replacing`: what changed there, set aside there first).
    func handOver(_ p: Project, replacing: SyncPause? = nil) {
        let to = machine.map { ["--to", $0] } ?? []
        note(p.path, nil)
        busy("checking \(p.name)…") {
            let plan = ahtJSON(["handover", p.path, "--json"] + to
                               + (replacing == nil ? [] : ["--replace-there"])) ?? [:]
            DispatchQueue.main.async {
                let there = plan["remote"] as? String ?? self.machine ?? "the other machine"
                if replacing == nil, let c = changedThere(plan), otherBlockers(plan).isEmpty,
                   plan["error"] == nil {
                    let pick = choose("The copy of “\(p.name)” on \(there) was changed there",
                                      changedThereText(c, p.name, there),
                                      ["Bring Them Here…", "Replace Them…", "Cancel"])
                    if pick == 0 { self.takeBack(p, copy: true) }
                    if pick == 1 { self.handOver(p, replacing: c) }
                    return
                }
                if crossingBlocks(plan) {
                    // names the disk there cannot hold, or a folder there that is not
                    // this project: the sheet says it, with the command that fixes it
                    self.handoverPlan = HandoverPlan(project: p, remote: there, body: "", dry: plan, blocked: true)
                    return
                }
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
                if let r = replacing,
                   !((plan["warnings"] as? [String]) ?? []).contains(where: { $0.contains("aside") }) {
                    // the core's warning says what is set aside there; an older one does not
                    body += "\n" + replaceThereLine(changedThere(plan) ?? r, remote) + "\n"
                }
                // what starts there, and that this folder is marked as away: the
                // sheet says it, for the agent chosen there (on a PC: nothing starts)
                self.handoverPlan = HandoverPlan(project: p, remote: remote, body: body.trimmingCharacters(in: .newlines),
                                                 replaceThere: replacing != nil, dry: plan,
                                                 toPC: handoverToPC(plan, self.machines.first { $0.name == remote }))
            }
        }
    }

    func confirmHandover(_ plan: HandoverPlan) {
        let p = plan.project, remote = plan.remote
        let task = plan.toPC ? "" : plan.task.trimmingCharacters(in: .whitespacesAndNewlines)
        let file = self.stageFile(p.path)
        do {
                self.busy("handing \(p.name) over…", follow: file) {
                    let d = ahtJSON(handoverArgs(p.path, to: self.machine, agent: plan.agent,
                                                 replace: plan.replaceThere, apply: true, file: file,
                                                 task: task)) ?? [:]
                    if let why = self.problems(d) {
                        self.note(p.path, "The handover did not go through:\n\n" + why)
                        return
                    }
                    self.note(p.path, handoverDoneText(d, remote: remote, agent: plan.agent, task: task, toPC: plan.toPC))
                    // Kimi below never-ask opened without reading the summary: the
                    // first message to paste into its window there (Open Session)
                    if plan.agent == "kimi", let first = farFirst(d) {
                        DispatchQueue.main.async { self.firstPrompts[p.path] = first }
                    }
                }
        }
    }

    /// Hand Over's dry run for another agent there (`--agent X`), asked when
    /// it is chosen in the sheet.
    func handoverDry(_ p: Project, agent: String, replace: Bool, then: @escaping ([String: Any]) -> Void) {
        guard !demo else { return }
        askCore(handoverArgs(p.path, to: machine, agent: agent, replace: replace)) { d, said in
            then(self.answered(d, said))
        }
    }

    /// Take Back from the machine a project was handed over to; with `copy`,
    /// Bring Them Here: the same flow on a synced copy changed there (Take
    /// Back's plan, "keep both" and set-aside; no session there to end), and
    /// then the sync goes on.
    func takeBack(_ p: Project, copy: Bool = false) {
        // aht ends no session on a PC: one open there blocks, in the core's words
        let stop = copy || p.pcAway(machines) ? [] : ["--stop"]
        note(p.path, nil)
        busy("checking \(p.name)…") {
            let asked = ahtJSON(["reclaim", p.path, "--json"] + stop) ?? [:]
            // Bring Them Here that would remove many files here asks before it does
            let plan = copy ? pastRemovals(asked) : asked
            let allow = copy ? Removals(plan["removals"])?.allow ?? [] : []
            DispatchQueue.main.async {
                // the agent there cannot be ended safely yet (--stop): why, and what to do
                if !copy, let r = stopRefusal(plan, awayAgent: p.awayAgent, machine: p.awayRemote ?? p.away) {
                    self.stopRefused(p, r)
                    return
                }
                if let why = self.problems(plan) {
                    self.note(p.path, (copy ? "Cannot bring them here now:\n\n"
                                            : "Cannot be taken back now:\n\n") + why)
                    return
                }
                let remote = plan["remote"] as? String ?? p.syncPaused?.machine ?? p.mirror
                    ?? "the other machine"
                // the sync goes on after it only when Keep in sync with that machine is on
                var body = takeBackText(plan, remote, copy: copy, synced: p.mirror == remote, agent: p.awayAgent)
                let title = copy ? "Bring the changes from \(remote) into “\(p.name)”?"
                                 : "Take “\(p.name)” back from \(remote)?"
                let both = ((plan["conflicts"] as? [String: [String]]) ?? [:])
                    .values.flatMap { $0 }
                var extra: [String] = []
                if both.isEmpty {
                    guard alert(title, body, confirm: copy ? "Bring Them Here" : "Take Back") else { return }
                } else {
                    body += "\nChanged on BOTH machines:\n"
                        + both.prefix(6).map { "• " + $0 }.joined(separator: "\n")
                        + "\n\nKeep Both leaves your version in place and puts the one "
                        + "from \(remote) next to it."
                    let pick = choose(title, body,
                                      ["Keep Both", "Use the Versions from \(remote)", "Cancel"])
                    if pick == 2 { return }
                    if pick == 1 { extra = ["--prefer", "there"] }
                }
                let file = self.stageFile(p.path)
                self.busy(copy ? "bringing the changes from \(remote)…" : "taking \(p.name) back…",
                          follow: file) {
                    let d = ahtJSON(["reclaim", p.path, "--apply", "--json",
                                     "--status-file", file] + stop + extra + allow) ?? [:]
                    // the agent there began to print again, or opened a turn, after the dry run
                    if !copy, d["applied"] as? Bool != true,
                       let r = stopRefusal(d, awayAgent: p.awayAgent, machine: p.awayRemote ?? p.away) {
                        self.refresh()
                        DispatchQueue.main.async { self.stopRefused(p, r, after: true) }
                        return
                    }
                    if let why = self.problems(d) {
                        self.note(p.path, (copy ? "Bringing them here did not go through:\n\n"
                                                : "Taking it back did not go through:\n\n") + why)
                        return
                    }
                    if copy {
                        // whether the sync goes on, as the registry has it now
                        self.refresh {
                            self.note(p.path, broughtText(d, remote,
                                                          now: self.projects.first { $0.path == p.path }))
                        }
                        return
                    }
                    var done = "Back on this Mac, files and history."
                    if let aside = d["set_aside"] as? String {
                        done += "\nReplaced files are kept in: " + aside
                    }
                    // another agent worked there: what it did is summed up for
                    // Claude Code's session here, which aht's hook tells it
                    let cu = (d["catchup"] as? [String: Any]) ?? [:]
                    if let a = firstText(cu["agent"]) {
                        done += "\nWhat \(AGENT_LABEL[a] ?? a) did on \(remote) is summed up for your Claude Code session"
                            + (firstText(cu["brief"]).map { ": " + $0 } ?? ".")
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
                    if let f = firstText(cu["brief"]) { DispatchQueue.main.async { self.summaries[p.path] = f } }
                }
            }
        }
    }

    /// Peek: the last lines the agent's window there shows (`attach --peek
    /// --json`); nothing is typed there.
    func peekThere(_ p: Project) {
        let v = PeekView(project: p)
        peek = v
        guard !demo else { return }
        askCore(["attach", p.path, "--peek", "--json"]) { d, said in
            guard self.peek?.id == v.id else { return }
            self.peek?.loading = false
            self.peek?.d = self.answered(d, said)
        }
    }

    /// Take Back's --stop refused: in plain words, with what to do (Try
    /// Again, or Open Session: the agent's window there).
    func stopRefused(_ p: Project, _ r: StopRefusal, after: Bool = false) {
        let w = stopWords(r)
        var text = (after ? "Nothing was taken back. " : "") + w.text
        if !r.others.isEmpty { text += "\n\nAlso in the way:\n" + r.others.map { "• " + $0 }.joined(separator: "\n") }
        switch choose(w.title, text, ["Try Again", "Open Its Window", "Cancel"]) {
        case 0: takeBack(p)
        case 1: openSession(p)
        default: break
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
    /// match this Mac again, unless that copy was worked on: then the sync
    /// pauses and asks (`resumeAsk`). The note comes once the command has run,
    /// from its answer and the row.
    func resumeSync(_ p: Project, _ to: String) {
        let ask = resumeAsk(p.name, to, released: p.syncPaused?.reason == "released")
        guard alert(ask.title, ask.body, confirm: "Turn Sync Back On") else { return }
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

    /// The answers to a paused sync (`SyncPausedBanner`).
    func pauseAction(_ p: Project, _ a: PauseAction, _ to: String) {
        switch a {
        case .bring: takeBack(p, copy: true)
        case .replace: replaceThem(p, to, removals: false)
        case .allow: replaceThem(p, to, removals: true)
        case .stop: stopSyncing(p, to)
        case .resume: resumeSync(p, to)
        }
    }

    /// Replace Them (`mirror --replace`) and Allow the Removals (`mirror
    /// --allow-removals`), once each: the dry run first, then a question that
    /// names what is set aside on the other machine, then the sync.
    func replaceThem(_ p: Project, _ to: String, removals: Bool) {
        guard let had = p.syncPaused else { return }
        let flag = removals ? "--allow-removals" : "--replace"
        note(p.path, nil)
        busy("checking the copy on \(to)…") {
            // removals over the limit ask here, before Replace Them allows them
            let plan = pastRemovals(ahtJSON(["mirror", p.path, flag, "--json"]) ?? [:])
            let gone = removals ? nil : Removals(plan["removals"])
            DispatchQueue.main.async {
                if let why = self.problems(plan) {
                    self.note(p.path, (removals ? "The removals cannot be allowed now:\n\n"
                                                : "Cannot replace them now:\n\n") + why)
                    return
                }
                // the dry run's own view of the copy there, else the row's
                let s = findPauses(plan).first.map(SyncPause.init) ?? had
                let aside = plan["aside"] as? String
                let ask = removals ? removalsAsk(s, p.name, to, aside: aside)
                                   : replaceAsk(s, p.name, to, aside: aside, removals: gone)
                guard alert(ask.title, ask.body,
                            confirm: removals ? "Allow the Removals" : "Replace Them") else { return }
                self.busy("sending \(p.name) to \(to)…") {
                    let d = ahtJSON(["mirror", p.path, flag] + (gone?.allow ?? [])
                                    + ["--apply", "--json"]) ?? [:]
                    if let why = self.problems(d) {
                        self.note(p.path, (removals ? "The sync did not go through:\n\n"
                                                    : "Replacing them did not go through:\n\n") + why)
                        return
                    }
                    self.refresh {
                        self.note(p.path, replacedText(d, p.name, to, removals: removals, aside: aside,
                                                       now: self.projects.first { $0.path == p.path }))
                    }
                }
            }
        }
    }

    /// Stop Syncing: Keep in sync off; the copy there stays as it is.
    func stopSyncing(_ p: Project, _ to: String) {
        note(p.path, nil)
        busy("stopping the sync with \(to)…") {
            let r = shWithStderr(PY, [ahtScript(), "mirror", p.path, "--off"])
            self.refresh {
                self.note(p.path, stoppedText(to, ok: r.ok, err: r.err,
                                              now: self.projects.first { $0.path == p.path },
                                              changed: p.syncPaused?.reason == "changed"))
            }
        }
    }

    /// "2 paused" in Machines: the Projects tab, on the first of them.
    func showPaused(_ held: [Project]) {
        search = ""
        tab = .projects
        selection = held.first?.path
    }

    // ---- across agents ----

    func refreshBoard() {
        guard !boardLoading, !demo else { return }
        boardLoading = true
        DispatchQueue.global(qos: .userInitiated).async {
            let machines = boardMachines(ahtJSON(["board", "--json"]) ?? [:])
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
                let held = pausedWith(self.projects, mc.name).count
                let copies = (plan["copies_skipped"] as? [String]) ?? []
                let body = on
                    ? "\(rows.count) project\(rows.count == 1 ? "" : "s") get a copy on \(mc.name), "
                      + String(format: "about %.1f GB the first time", gb) + " (it runs in the "
                      + "background and can take a while); after that only changes travel, "
                      + "every 30 minutes. The biggest:\n\n" + top + "\n\nProjects inside "
                      + "another project travel with it. Rebuilt folders such as node_modules "
                      + "stay behind." + syncAllNote(held: held, copies: copies)
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
        // the other machines too (asked in parallel by the core, 20 s each;
        // one project's search looks in that project's copy there)
        let everywhere = searchEverywhere && canSearchEverywhere
        DispatchQueue.global(qos: .userInitiated).async {
            let d = ahtJSON(["search", "--json", "--limit", "40"]
                            + (self.searchProject.map { ["--project", $0] } ?? [])
                            + (everywhere ? ["--everywhere"] : [])
                            + ["--"] + q.split(separator: " ").map(String.init)) ?? [:]
            let rows = searchHits(d)
            let missed = everywhere ? searchMissed(d) : []
            let asked = everywhere ? searchAsked(d) : nil
            DispatchQueue.main.async {
                self.hits = rows
                self.searchMisses = missed
                self.searchedOn = asked
                self.searched = q
                self.searching = false
            }
        }
    }

    func resume(_ h: SearchHit) {
        guard h.machine == nil, let p = h.project else { return }
        background { aht(["resume-here", p, "--session", h.session, "--agent", h.agent]) }
    }

    func restore(_ h: SearchHit) {
        guard h.machine == nil, let p = h.restoreProject, let u = h.restoreUUID, let st = h.restoreStamp,
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
            : s.target == "kimi" && kimiReads(s.plans[s.mode] ?? [:]) ? "\(label) is reading the summary…"
            : "opening \(label)…"
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
            // Kimi below never-ask: the first message to paste, with a Copy button
            if let first = kimiFirst(d) {
                DispatchQueue.main.async { self.firstPrompts[p.path] = first }
            }
        }
    }

    // ---- Pick Up and Leave a Note: work across machines ----

    /// The Machines menu's items.
    func machineAction(_ p: Project, _ i: MachineItem) {
        switch i.kind {
        case "pickup": pickUp(p, from: i.machine)
        case "back": leaveNote(p, on: i.machine, back: true)
        default: leaveNote(p, on: i.machine)
        }
    }

    /// Pick Up from M: M is asked for the folder, its sessions, git and a
    /// summary (a dry run: nothing is written), and the sheet shows them.
    /// From a search hit: that session, in that folder there.
    func pickUp(_ p: Project, from machine: String, session: String? = nil, agent: String? = nil,
                there: String? = nil) {
        var v = PickupView(project: p, machine: machine, kind: "pickup")
        (v.session, v.agent, v.there) = (session, agent, there)
        pickup = v
        lookThere()
    }

    /// Leave a Note on M; `back`: asked as Hand Back to M (the core finds
    /// back mode by itself: a pickup from M is open here).
    func leaveNote(_ p: Project, on machine: String, back: Bool = false) {
        var v = PickupView(project: p, machine: machine, kind: "note")
        v.back = back
        pickup = v
        lookThere()
    }

    /// The dry run, and again after a pick in the sheet (a folder, a session).
    func lookThere() {
        guard let v = pickup else { return }
        pickup?.loading = true
        pickup?.done = nil
        pickup?.copied = false
        guard !demo else { return }
        let args = pickupArgs(v)
        DispatchQueue.global(qos: .userInitiated).async {
            let r = shWithStderr(PY, [ahtScript()] + args)
            let d = (try? JSONSerialization.jsonObject(with: Data(r.out.utf8))) as? [String: Any]
            DispatchQueue.main.async {
                guard self.pickup?.id == v.id else { return }
                self.pickup?.loading = false
                self.pickup?.dry = d ?? [:]
                self.pickup?.said = d == nil ? r.err.trimmingCharacters(in: .whitespacesAndNewlines) : ""
                if let d = d, self.pickup?.open == nil || pickupIsBack(d) {
                    self.pickup?.open = pickupAgent(d, installed: self.agentCLIs)
                }
            }
        }
    }

    /// The sheet's way on: Open in … (`open`), Copy the Start Line (`copy`,
    /// with the agent picked as `open`: --no-window), or Leave the Note. A
    /// folder found other than by its project id goes with --there, as
    /// confirmed.
    func applyPickup(open: String? = nil, copy: Bool = false) {
        guard var v = pickup, pickupReady(v) else { return }
        if v.there == nil, let path = thereMatch(v.dry).path, !matchHow(thereMatch(v.dry).how).sure {
            v.there = path
        }
        pickup?.applying = true
        guard !demo else { return }
        let args = pickupArgs(v, apply: true, open: open, noWindow: copy)
        DispatchQueue.global(qos: .userInitiated).async {
            let r = shWithStderr(PY, [ahtScript()] + args)
            let d = (try? JSONSerialization.jsonObject(with: Data(r.out.utf8))) as? [String: Any]
            DispatchQueue.main.async {
                guard self.pickup?.id == v.id else { return }
                let why = r.err.trimmingCharacters(in: .whitespacesAndNewlines)
                let got = d ?? ["error": why.isEmpty ? "aht gave no answer — see the log (Settings)." : why]
                self.pickup?.applying = false
                self.pickup?.done = got
                if copy, pickupProblems(got) == nil, let line = startLine(got) {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(line, forType: .string)
                    self.pickup?.copied = true
                }
                self.refresh()
            }
        }
    }

    /// Continue Here… on another machine's search hit: Pick Up that session,
    /// into the folder here that is that project (asked when unclear).
    func pickUpHit(_ h: SearchHit) {
        guard let mc = h.machine else { return }
        let name = h.project.map { ($0.replacingOccurrences(of: "\\", with: "/") as NSString)
            .lastPathComponent } ?? "the project"
        let twins = h.project.map { localTwins($0, projects.map { $0.path }) } ?? []
        var here: String? = twins.count == 1 ? twins[0] : nil
        if twins.count > 1 {
            let pick = choose("Continue “\(name)” from \(mc) in which folder?",
                              "These folders on this Mac have its name.",
                              twins.map(tilde) + ["Another Folder…", "Cancel"])
            if pick >= 0 && pick < twins.count { here = twins[pick] } else if pick != twins.count { return }
        }
        if here == nil {
            here = chooseFolder("The folder on this Mac to continue “\(name)” from \(mc) in "
                                + "(a clone of the same repository, for example)")
        }
        guard let path = here else { return }
        let p = projects.first { $0.path == path } ?? Project(["real_path": path, "exists": true])
        pickUp(p, from: mc, session: h.session.isEmpty ? nil : h.session, agent: h.agent, there: h.project)
    }

    /// A note left here by another machine, in the reading sheet.
    func readNote(_ p: Project, _ i: Incoming) {
        guard let b = i.brief else { return }
        let f = summaryFile(b, in: p.path)
        let text = (try? String(contentsOfFile: f, encoding: .utf8))
            ?? "The note is not there any more: \(tilde(f))"
        textSheet = TextSheet(title: "Note from \(i.name): \(p.name)", text: text, project: nil,
                              wide: true, topic: "Pick up on another machine")
    }

    // ---- Bring Here and Send Back ----

    /// Run aht off the main thread; `then` gets its JSON (nil when it gave
    /// none) and what it said on stderr, on the main thread.
    func askCore(_ args: [String], then: @escaping ([String: Any]?, String) -> Void) {
        DispatchQueue.global(qos: .userInitiated).async {
            let r = shWithStderr(PY, [ahtScript()] + args)
            let d = (try? JSONSerialization.jsonObject(with: Data(r.out.utf8))) as? [String: Any]
            let said = r.err.trimmingCharacters(in: .whitespacesAndNewlines)
            DispatchQueue.main.async { then(d, said) }
        }
    }

    /// What --apply answered, or what went wrong when it gave no JSON.
    func answered(_ d: [String: Any]?, _ said: String) -> [String: Any] {
        d ?? ["error": said.isEmpty ? "aht gave no answer — see the log (Settings)." : said]
    }

    /// Bring Here from M: M is asked for the projects aht keeps there.
    func openBring(from machine: String) {
        let v = BringView(machine: machine)
        bring = v
        guard !demo else { return }
        askCore(["bring", "--from", machine, "--list", "--json"]) { d, said in
            guard self.bring?.id == v.id else { return }
            self.bring?.listing = false
            self.bring?.list = d ?? [:]
            self.bring?.said = d == nil ? said : ""
        }
    }

    /// The dry run for the project picked there; again when "bring it
    /// anyway" (--allow-idle) changes.
    func lookBring(_ path: String) {
        guard bring != nil, bring?.done == nil else { return }
        if bring?.picked != path {
            bring?.allowIdle = false
            bring?.agent = "claude"
        }
        bring?.picked = path
        bring?.loading = true
        bring?.dry = [:]
        guard !demo, let v = bring else { return }
        askCore(bringArgs(v)) { d, said in
            guard let now = self.bring, now.id == v.id, now.picked == path, now.allowIdle == v.allowIdle,
                  now.agent == v.agent
            else { return }
            self.bring?.loading = false
            self.bring?.dry = d ?? [:]
            self.bring?.said = d == nil ? said : ""
        }
    }

    func applyBring() {
        guard let v = bring, bringReady(v) else { return }
        bring?.applying = true
        guard !demo else { return }
        askCore(bringArgs(v, apply: true)) { d, said in
            guard self.bring?.id == v.id else { return }
            self.bring?.applying = false
            self.bring?.done = self.answered(d, said)
            self.refresh()
        }
    }

    /// Send Back on a project brought here: home plans the return against
    /// its own copy (a dry run), the sheet shows it.
    func openSendBack(_ p: Project) {
        guard let to = p.sendBackTo, p.copyOf?.pcBlocks(machines) != true else { return }
        sendBack = SendBackView(project: p, machine: to)
        lookSendBack()
    }

    func lookSendBack() {
        guard let v = sendBack, v.done == nil else { return }
        sendBack?.loading = true
        sendBack?.dry = [:]
        guard !demo else { return }
        askCore(sendBackArgs(v)) { d, said in
            guard let now = self.sendBack, now.id == v.id, now.ignoreVersion == v.ignoreVersion,
                  now.preferHere == v.preferHere else { return }
            self.sendBack?.loading = false
            self.sendBack?.dry = d ?? [:]
            self.sendBack?.said = d == nil ? said : ""
        }
    }

    func applySendBack() {
        guard let v = sendBack, sendBackReady(v) else { return }
        sendBack?.applying = true
        guard !demo else { return }
        askCore(sendBackArgs(v, apply: true)) { d, said in
            guard self.sendBack?.id == v.id else { return }
            self.sendBack?.applying = false
            self.sendBack?.done = self.answered(d, said)
            self.refresh()
        }
    }

    /// Each machine's folders (`remote paths --json`), for Machines; until it
    /// answers, what the config says.
    func loadPaths() {
        guard !demo, !machines.isEmpty else { return }
        let names = machines.map { $0.name }
        DispatchQueue.global(qos: .utility).async {
            var maps: [String: PathMap] = [:]
            for n in names {
                let d = ahtJSON(["remote", "paths", n, "--json"]) ?? [:]
                if firstText(d["error"]) == nil, let pm = pathMap(d["paths"], d) { maps[n] = pm }
            }
            DispatchQueue.main.async { self.pathsOf = maps }
        }
    }

    func pathsFor(_ mc: Machine) -> PathMap? { pathsOf[mc.name] ?? mc.paths }

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
        opinionDry = nil
        loadOpinion(p, run: nil)
    }

    /// The second opinion's dry run for the task typed: the level each agent
    /// works in and the warnings, before Start; nothing starts. Asked as the
    /// dialog opens (`wait` 0) and a moment after typing stops; an answer for
    /// text typed over since is dropped.
    func opinionDryRun(_ p: Project, task: String, wait: Double = 0.5) {
        opinionWait?.cancel()
        opinionAsked += 1
        let n = opinionAsked, t = task.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !demo else { return }
        let w = DispatchWorkItem {
            DispatchQueue.global(qos: .userInitiated).async {
                let d = ahtJSON(opinionDryArgs(p.path, task: t)) ?? [:]
                DispatchQueue.main.async {
                    guard n == self.opinionAsked, self.opinion?.project.path == p.path else { return }
                    self.opinionDry = OpinionDry(path: p.path, task: t, d: d)
                }
            }
        }
        opinionWait = w
        DispatchQueue.main.asyncAfter(deadline: .now() + wait, execute: w)
    }

    func loadOpinion(_ p: Project, run: String?, started: [String: Any] = [:]) {
        DispatchQueue.global(qos: .userInitiated).async {
            let all = (ahtJSON(["second-opinion", "--list", "--json"])?["opinions"]
                       as? [[String: Any]]) ?? []
            var v = OpinionView(project: p)
            v.started = started
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
                                         files: ((r["files"] as? [[String: Any]]) ?? []).map { changedFile($0) },
                                         perm: (d["perms"] as? [String: Any])?[a] as? [String: Any])
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
                self.loadOpinion(p, run: d["id"] as? String, started: d)
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
        let to = machine.map { ["--to=" + $0] } ?? []
        DispatchQueue.global(qos: .userInitiated).async {
            // a dry run, for the level the session there starts in
            let dry = ahtJSON(["night-shift", p.path, "--start", "now", "--back", "07:00", "--json"] + to) ?? [:]
            let jobs = ((ahtJSON(["night-shift", "--list", "--json"])?["jobs"] as? [[String: Any]]) ?? [])
                .filter { ($0["project"] as? String) == p.path }
                .map { j in
                    NightJob(id: j["id"] as? String ?? "", state: j["state"] as? String ?? "?",
                             startAt: (j["start_at"] as? NSNumber)?.doubleValue ?? 0,
                             backAt: (j["back_at"] as? NSNumber)?.doubleValue ?? 0,
                             remote: j["remote"] as? String ?? "", task: j["task"] as? String ?? "",
                             log: (j["log"] as? [String]) ?? [])
                }
            DispatchQueue.main.async { self.night = NightShiftView(project: p, jobs: jobs.reversed(), dry: dry) }
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
                // a failed run's JSON counts only when it says what went wrong:
                // its error, or the files that could not come (the rest came)
                self.offsite?.result = fetchedText(fetchAnswered(r.ok, d) ? d : nil, f,
                                                   said: r.err)
            }
        }
    }

    func showGuide(_ topic: String? = nil) {
        showGuideWindow(topic)
    }

    /// Open the session there in a new terminal; when `attach` refuses (a PC,
    /// where no session runs for aht to open), the core's reason.
    func openSession(_ p: Project) {
        background {
            let r = shWithStderr(PY, [ahtScript(), "attach", p.path, "--window"])
            guard !r.ok else { return }
            let said = (r.err + r.out).trimmingCharacters(in: .whitespacesAndNewlines)
            DispatchQueue.main.async {
                _ = alert("The session did not open", said.isEmpty ? "aht gave no answer." : said)
            }
        }
    }

    func continueHere(_ p: Project, handedOver: Bool = false) {
        background { aht(["resume-here", p.path] + (handedOver ? ["--handed-over"] : [])) }
    }

    func reveal(_ p: Project) {
        NSWorkspace.shared.selectFile(p.path, inFileViewerRootedAtPath: "")
    }

    /// The Keep in sync switch. When aht refuses (this folder is the other
    /// machine's synced copy, say), the note says why.
    func keepInSync(_ p: Project, _ on: Bool) {
        let to = machine.map { ["--to", $0] } ?? []
        note(p.path, on ? "Kept in sync with \(machine ?? "the other machine"); the "
                          + "first copy runs in the background." : nil)
        DispatchQueue.global(qos: .userInitiated).async {
            let r = shWithStderr(PY, [ahtScript(), "mirror", p.path] + (on ? ["--on"] + to : ["--off"]))
            self.refresh {
                guard !r.ok else { return }
                let said = [r.err, r.out].map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
                    .filter { !$0.isEmpty }.joined(separator: "\n\n")
                self.note(p.path, "Keep in sync was not turned \(on ? "on" : "off"):\n\n"
                          + (said.isEmpty ? "aht gave no answer — see the log (Settings)." : said))
            }
        }
    }

    func syncNow() {
        busy("syncing…") {
            let rows = (ahtJSON(["mirror", "--run", "--json"])?["mirrored"]
                        as? [[String: Any]]) ?? []
            notifyUser("Sync", syncSummary(rows))
            self.refresh()
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
        let mode = transferMode
        busy("checking \(m.name)…") {
            let d = ahtJSON(["remote", "check", m.name, "--json"]) ?? [:]
            let (rows, error) = checkRows(d)
            DispatchQueue.main.async {
                self.checks[m.name] = rows
                self.checkError[m.name] = error
                for (n, t) in checkTransfers(d) { self.movers[n] = Mover(mode: mode, transfer: t) }
            }
            // a PC: whether it answers, as the core now has it
            let said = ((d["machines"] as? [[String: Any]]) ?? []).first?["system"] as? String
            if m.system == "Windows" || said == "Windows" { self.refresh() }
        }
    }

    /// Settings' Ask the Machines: each machine's check, for what copies its
    /// files (rsync where it has it, under "auto").
    func askMovers() {
        let mode = transferMode
        busy("asking the machines…") {
            let d = ahtJSON(["remote", "check", "all", "--json"]) ?? [:]
            DispatchQueue.main.async {
                for (n, t) in checkTransfers(d) { self.movers[n] = Mover(mode: mode, transfer: t) }
            }
        }
    }

    /// Watch: aht asks the machine every 2 minutes and tells you when a
    /// session there waits for you. The switch moves at once; it moves back
    /// with what went wrong when the core did not do it.
    func watch(_ mc: Machine, _ on: Bool) {
        func mark(_ v: Bool) {
            var ho = handover, rs = (ho["remotes"] as? [String: Any]) ?? [:]
            rs[mc.name] = ((rs[mc.name] as? [String: Any]) ?? [:]).merging(["watch": v]) { $1 }
            ho["remotes"] = rs
            status["handover"] = ho
        }
        mark(on)
        guard !demo else { return }
        DispatchQueue.global(qos: .userInitiated).async {
            let r = shWithStderr(PY, [ahtScript(), "remote", "watch", mc.name] + (on ? [] : ["--off"]) + ["--json"])
            let d = r.out.data(using: .utf8).flatMap { try? JSONSerialization.jsonObject(with: $0) }
                as? [String: Any]
            let problem = watchProblem(d, mc.name, on: on, said: r.err)
            DispatchQueue.main.async {
                if let p = problem {
                    mark(!on)
                    _ = alert(on ? "\(mc.name) could not be watched" : "\(mc.name) is still watched", p)
                }
                self.refresh()
            }
        }
    }

    /// What the Sessions tab last heard from a machine (nil: not asked yet).
    func heard(_ name: String) -> BoardMachine? { board.first { $0.name == name && !$0.local } }

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
                } else if pcAddFailure(r.out) {
                    // a PC that does not answer yet: the core's reason, and the guide's setup
                    self.textSheet = TextSheet(title: "\(name) could not be added", text: r.out, project: nil,
                                               topic: PC_SETUP_TOPIC)
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

    /// A setting that is a table or a list (`agent_permission_flags`), as JSON.
    func setJSON(_ key: String, _ value: Any) {
        guard let data = try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]),
              let text = String(data: data, encoding: .utf8) else { return }
        setChecked(key, text, value)
    }

    /// A setting the core may refuse (exit 2: agent_permission_flags that ask
    /// for more than their level, say): its words, and the setting as it was.
    func setChecked(_ key: String, _ text: String, _ value: Any, _ done: ((Bool) -> Void)? = nil) {
        let was = config[key]
        config[key] = value
        onChange?()
        guard !demo else { return }
        DispatchQueue.global(qos: .userInitiated).async {
            let r = shWithStderr(PY, [ahtScript(), "config", "--set", "\(key)=\(text)", "--no-reload"])
            DispatchQueue.main.async {
                if !r.ok {
                    self.config[key] = was
                    let why = (r.err + r.out).trimmingCharacters(in: .whitespacesAndNewlines)
                    _ = alert("The setting was not saved", why.isEmpty ? "aht refused it." : why)
                }
                done?(r.ok)
                self.refresh()
            }
        }
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

    /// Whether the other machines can be asked too: some are set up.
    var machinesToAsk: Bool {
        !(((status["handover"] as? [String: Any])?["remotes"] as? [String: Any]) ?? [:]).isEmpty
    }

    /// The warnings and errors in this Mac's log in the last day (status).
    var recentProblems: Int {
        ((status["log"] as? [String: Any])?["recent_problems"] as? NSNumber)?.intValue ?? 0
    }

    /// Recent problems: this Mac's warnings and errors, and every other
    /// machine's when some are set up, newest first.
    func showProblems() {
        let everywhere = machinesToAsk
        let v = ProblemsView(everywhere: everywhere)
        problems = v
        DispatchQueue.global(qos: .userInitiated).async {
            let r = ahtFull(["logs", "--errors"] + (everywhere ? ["--everywhere"] : []) + ["--json"])
            let d = (try? JSONSerialization.jsonObject(with: Data(r.out.utf8))) as? [String: Any]
            DispatchQueue.main.async {
                guard self.problems?.id == v.id else { return }     // closed, or asked again
                var done = v
                done.loading = false
                if let d = d {
                    (done.rows, done.missed) = parseProblems(d)
                } else {
                    let said = (r.err + r.out).trimmingCharacters(in: .whitespacesAndNewlines)
                    done.error = said.isEmpty ? "aht gave no answer." : said
                }
                self.problems = done
            }
        }
    }

    /// Make a Problem Report…: one readable file, saved among aht's reports
    /// and shown in Finder.  With machines set up, a box adds their recent
    /// warnings and errors (--everywhere).
    func makeProblemReport() {
        let a = NSAlert()
        a.messageText = "Make a Problem Report"
        a.informativeText = REPORT_INTRO
        a.addButton(withTitle: "Make the Report")
        a.addButton(withTitle: "Cancel").keyEquivalent = "\u{1b}"
        var box: NSButton?
        if machinesToAsk {
            let b = NSButton(checkboxWithTitle: "Include the other machines' recent warnings and "
                             + "errors (aht asks each one)", target: nil, action: nil)
            b.state = .on
            a.accessoryView = b
            box = b
        }
        NSApp.activate(ignoringOtherApps: true)
        guard a.runModal() == .alertFirstButtonReturn else { return }
        let everywhere = box?.state == .on
        let out = problemReportFile(status["aht_home"] as? String ?? HOME + "/.aht")
        busy(everywhere ? "making the problem report, asking every machine…"
                        : "making the problem report…") {
            let r = ahtFull(problemReportArgs(everywhere: everywhere, out: out))
            let d = ((try? JSONSerialization.jsonObject(with: Data(r.out.utf8))) as? [String: Any]) ?? [:]
            DispatchQueue.main.async {
                guard let rep = parseReport(d) else {
                    if r.ok { AppLog.shared.note("report-problem failed unexpectedly: its answer had no path") }
                    let crashed = r.err.contains("Traceback (most recent call last)")
                    let said = crashed ? "aht stopped with an error. It is noted in aht's log: Settings → "
                        + "Recent Problems… shows it."
                        : ((d["error"] as? String) ?? (r.err + r.out)).trimmingCharacters(in: .whitespacesAndNewlines)
                    _ = alert("The report was not made", said.isEmpty ? "aht gave no answer." : said)
                    return
                }
                NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: rep.path)])
                let b = NSAlert()
                b.messageText = "The problem report is saved"
                b.informativeText = reportSavedText(rep, everywhere: everywhere)
                b.addButton(withTitle: "OK")
                b.addButton(withTitle: "Copy Path")
                NSApp.activate(ignoringOtherApps: true)
                if b.runModal() == .alertSecondButtonReturn {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(rep.path, forType: .string)
                }
            }
        }
    }

    func setLoginItem(_ on: Bool, note: Bool = true) {
        let fm = FileManager.default
        if !on {
            sh("/bin/launchctl", ["bootout", "gui/\(getuid())/\(TRAY_LABEL)"])
            try? fm.removeItem(atPath: TRAY_PLIST)
        } else {
            // whichever tray this is: the app bundle's executable or the bare binary
            let bin = Bundle.main.executablePath ?? (TOOLS + "/aht-tray")
            do {
                try loginItemPlist(bin)?.write(to: URL(fileURLWithPath: TRAY_PLIST), options: .atomic)
            } catch {
                AppLog.shared.note("the login item was not written: \(error.localizedDescription)")
            }
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
        .sheet(item: $m.problems) { _ in ProblemsSheet() }
        .sheet(item: $m.offsite) { _ in FetchBackupsSheet() }
        .sheet(item: $m.pickup) { _ in PickupSheet() }
        .sheet(item: $m.bring) { _ in BringSheet() }
        .sheet(item: $m.peek) { _ in PeekSheet() }
        .sheet(item: $m.sendBack) { _ in SendBackSheet() }
    }
}

struct ProjectsView: View {
    @EnvironmentObject var m: AppModel

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 10) {
                TextField("Search", text: $m.search)
                    .textFieldStyle(.roundedBorder).frame(width: 160)
                Spacer()
                let choices = pickerMachines(m.machines, keeping: m.machine)
                if choices.count > 1 {
                    Picker("Machine", selection: Binding(
                        get: { m.machine ?? "" },
                        set: { n in choices.first { $0.name == n }.map(m.use) })) {
                        ForEach(choices) { Text(pickerLabel($0)).tag($0.name) }
                    }
                    .frame(width: 150)
                    .help(m.machines.first { $0.name == m.machine }?.cannotAsk ?? "")
                } else if let one = m.machine {
                    Text("Machine: \(one)").foregroundColor(.secondary).lineLimit(1).fixedSize()
                }
                BringMenu()
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
                TableColumn("In sync") { p in
                    Text(p.sync).foregroundColor(p.syncPaused?.asks == true && p.away == nil ? .orange : .primary)
                }
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
                if let c = p.copyOf, p.away == nil {
                    Label(copyLine(c, m.machines), systemImage: c.kind == "sync" ? "arrow.triangle.2.circlepath"
                                                                     : "laptopcomputer.and.arrow.down")
                        .font(.callout).foregroundColor(.secondary).lineLimit(1)
                        .help(c.at.map { "Since " + clock($0) } ?? "")
                }
                if let h = p.handing, h.state != "running" { HandingBanner(p: p, h: h) }
                if let line = awayLine(p, m.machines) { HeldThereBanner(p: p, line: line) }
                if let s = p.syncPaused, let to = p.mirror, p.away == nil, p.handing == nil {
                    SyncPausedBanner(p: p, s: s, to: s.machine ?? to)
                }
                if let r = p.handBack, p.away == nil { RelayLine(p: p, r: r) }
                if let i = p.incoming, i.isNote, p.away == nil { IncomingBanner(p: p, i: i) }
                if let i = p.pickedUp, p.away == nil { IncomingBanner(p: p, i: i) }
                HStack(spacing: 10) {
                    if p.away != nil {
                        AwayButtons(p: p)
                    } else if p.exists {
                        HereButtons(p: p)
                    }
                    Spacer()
                    if p.exists {
                        MoreMenu(p: p)
                        HelpButton("The window at a glance")
                    }
                }
                .disabled(m.working != nil)
                if m.machine == nil && m.supported {
                    Text("Add a machine under Machines to hand projects over.")
                        .font(.callout).foregroundColor(.secondary)
                } else if let o = p.open, p.away == nil {
                    Text(openText(o)).font(.callout).foregroundColor(.orange)
                }
                DetailNotes(p: p)
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

    /// Why a project with an open session cannot be handed over yet.
    func openText(_ o: String) -> String {
        switch o {
        case "idle":
            return "An agent session is open in this project. Exit it (/exit) before handing the project over."
        case "waiting":
            return "An agent session in this project is waiting for you. Answer it in its terminal; the "
                + "project cannot be handed over until it has finished and is closed."
        default:
            return "An agent is working in this project. It can be handed over once that has finished and "
                + "the session is closed."
        }
    }

    func state(_ p: Project) -> String {
        if p.awayArrival, p.away != nil {       // a PC: nothing runs there until Continue here
            return p.place + (p.awaySince.map { ", " + ago($0) } ?? "")
        }
        if let host = p.away {
            return (p.awayDrivenBy == "there" ? "brought to \(host)" : "handed over to \(host)")
                + (p.awaySince.map { ", " + ago($0) } ?? "")
                + (p.awayAgentLabel.map { "; \($0) works on it there" } ?? "")
        }
        if !p.exists { return "the folder is gone; its histories are safe" }
        return "\(p.sessions) session(s), \(byteText(NSNumber(value: p.bytes))) of history"
    }
}

/// A Bring Here that the other machine drives (`driven_by` "there"): it
/// finishes it or undoes it; aht here never asks it (a PC cannot be asked),
/// and the notices check offers Release an hour after it began.
func handingWaitText(_ h: Handing) -> String {
    if h.release {
        return "\(h.machine) did not finish. Release lets the project go on here; what was copied to "
            + "\(h.machine) stays there."
    }
    let due = h.since.map { clock($0.addingTimeInterval(3600)) } ?? ""
    return "When \(h.machine) finishes, the project shows as on \(h.machine). aht waits for \(h.machine); "
        + "Release is offered after an hour" + (due.isEmpty ? "." : " (at \(due)).")
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
        let there = h.drivenBy == "there"     // that machine drives it: nobody here to ask
        let what = there ? "Bringing it to \(h.machine)" : "Handover to \(h.machine)"
        HStack(alignment: .center, spacing: 10) {
            Image(systemName: "exclamationmark.triangle.fill").foregroundColor(.orange)
            VStack(alignment: .leading, spacing: 2) {
                Text(silent ? "\(what) did not finish" : there ? "\(what) unfinished" : "\(what) unfinished: checking…")
                    .fontWeight(.semibold)
                Text(there ? handingWaitText(h)
                     : silent
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
            if !there {
                Button("Check Now") { m.checkHanding(p) }.disabled(!m.supported || !h.reachable)
            }
            Button("Release…") { m.release(p) }     // after an hour of silence, the way on
                .keyboardShortcut(h.release ? .defaultAction : nil)
        }
        .padding(.horizontal, 10).padding(.vertical, 6)
        .background(RoundedRectangle(cornerRadius: 6).fill(Color.orange.opacity(0.12)))
        .disabled(m.working != nil)
    }
}

/// Keep in sync that waits for the user. Release paused it so the copy left
/// on the other machine is not overwritten: Turn Sync Back On. Or the sync
/// paused by itself: the copy there was changed (Bring Them Here, Replace
/// Them, Stop Syncing), it would remove a lot there (Allow the Removals), or
/// the folder there holds something else (Replace Them, Stop Syncing).
struct SyncPausedBanner: View {
    @EnvironmentObject var m: AppModel
    let p: Project
    let s: SyncPause
    let to: String

    var body: some View {
        HStack(alignment: .center, spacing: 10) {
            Image(systemName: s.asks ? "exclamationmark.triangle.fill" : "pause.circle.fill")
                .foregroundColor(.orange)
            VStack(alignment: .leading, spacing: 2) {
                Text("Keep in sync with \(to) is paused").fontWeight(.semibold)
                Text(pauseText(s, to))
                    .font(.caption).foregroundColor(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 8)
            ForEach(pauseActions(s), id: \.self) { a in
                Button(a.rawValue) { m.pauseAction(p, a, to) }
                    .disabled(!m.supported)
                    .help(a.help(to))
            }
        }
        .padding(.horizontal, 10).padding(.vertical, 6)
        .background(RoundedRectangle(cornerRadius: 6).fill(Color.orange.opacity(0.12)))
        .disabled(m.working != nil)
    }
}

/// Pick Up from M, Leave a Note on M, and Hand Back to M while a pickup from
/// M is open: context across machines (git moves the files).
struct MachinesMenu: View {
    @EnvironmentObject var m: AppModel
    let p: Project

    var body: some View {
        let items = machineItems(p, askableMachines(m.machines))
        Menu("Machines") {
            ForEach(Array(items.enumerated()), id: \.offset) { k, i in
                if k > 0 && items[k - 1].kind != i.kind { Divider() }
                Button(i.title) { m.machineAction(p, i) }
            }
        }
        .fixedSize()
        .disabled(items.isEmpty || !m.canReach || p.handing != nil)
        .help(askableMachines(m.machines).isEmpty
              ? "Add a Mac or Linux machine under Machines to pick up work from it"
              : "Go on with work from another machine, or leave it a note: a summary moves, "
                + "git moves the files")
    }
}

/// The banner's second line: for a pickup, what Hand Back does; for a note
/// for a session here, whether that session reads it by itself (Claude
/// Code, through aht's hook: `hook`) or is asked to; else read it first.
func incomingDetail(_ i: Incoming, hook: Bool) -> String {
    if !i.isNote {
        return "Hand Back leaves a note on \(i.name) for the session the work came from."
    }
    if i.noteFor != nil {
        let label = i.noteAgent.map { AGENT_LABEL[$0] ?? $0 } ?? "Your"
        let file = i.brief.map { ".aht/handover/" + ($0 as NSString).lastPathComponent }
        return "The note is for \(label)'s own session here. "
            + noteReads(i.noteAgent ?? "claude", file: file, hook: hook)
            + " Pull first if the changes were pushed."
    }
    return "Read it before going on: the files may differ from what you remember. "
        + "Pull first if the changes were pushed."
}

/// What the session a hand-back note is for does with it when it is
/// continued (`on`: " on box", or "" for here): Claude Code reads it by
/// itself, as aht's hook gives it to the session (`hook`: the hook is set
/// up there). No other agent has that hook: it is asked to read the note
/// (`file`) first.
func noteReads(_ agent: String?, on: String = "", file: String? = nil, hook: Bool = true) -> String {
    let f = file ?? "the note"
    guard let a = agent else {
        return "When you continue that session\(on), Claude Code reads it by itself; another agent "
            + "does not: ask it to read \(f) first."
    }
    if a == "claude" && hook { return "Claude Code reads it by itself when you continue that session\(on)." }
    return "\(AGENT_LABEL[a] ?? a) does not read it by itself" + (a == "claude" ? " (aht's hook is off)" : "")
        + ": when you continue that session\(on), ask it to read \(f) first."
}

/// Work that came from another machine: a note left here (Read the Note…),
/// or a pickup from there (Hand Back to it).
struct IncomingBanner: View {
    @EnvironmentObject var m: AppModel
    let p: Project
    let i: Incoming

    var detail: String { incomingDetail(i, hook: m.hookOn) }

    var body: some View {
        HStack(alignment: .center, spacing: 10) {
            Image(systemName: i.isNote ? "envelope.fill" : "arrow.down.circle.fill")
                .foregroundColor(.accentColor)
            VStack(alignment: .leading, spacing: 2) {
                Text(incomingLine(i)).fontWeight(.semibold).lineLimit(1)
                Text(detail).font(.caption).foregroundColor(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 8)
            if i.isNote {
                if i.brief != nil { Button("Read the Note…") { m.readNote(p, i) } }
                if let s = i.noteFor {
                    Button("Continue Session") {
                        m.resumeSession(p.path, agent: i.noteAgent ?? "claude", session: s)
                    }
                }
            } else if let to = p.pickedUpFrom {
                Button("Hand Back to \(to)…") { m.leaveNote(p, on: to, back: true) }
                    .disabled(!m.canReach || p.handing != nil)
            }
        }
        .padding(.horizontal, 10).padding(.vertical, 4)
        .background(RoundedRectangle(cornerRadius: 6).fill(Color.accentColor.opacity(0.10)))
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
                                if !mc.silentNote.isEmpty {
                                    Text(mc.silentNote).foregroundColor(.orange).help(mc.error ?? "")
                                } else if mc.rows.isEmpty {
                                    Text("No agent session open.").foregroundColor(.secondary)
                                }
                                if mc.showsOld {
                                    // its last rows, greyed: they may have changed since
                                    Text(mc.asOf).font(.caption).foregroundColor(.secondary)
                                    ForEach(mc.lastRows) { r in BoardRowView(r: r, old: true) }
                                } else {
                                    ForEach(mc.rows) { r in BoardRowView(r: r) }
                                }
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
    var old = false                 // a machine that did not answer: its last row, greyed, no buttons

    var color: Color {
        // a window aht runs another agent in: blue while it prints
        if let w = r.windowWords { return w.text == "working" ? .blue : .secondary }
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
        if old {
            row.opacity(0.45).help("What it had open when it last answered; it may have changed since")
        } else {
            live
        }
    }

    var live: some View {
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
            if let hint = r.windowWords?.hint {
                Text(hint).font(.caption).italic().foregroundColor(.secondary).lineLimit(1)
            }
            if let t = r.since {
                Text(ago(NSNumber(value: t))).foregroundColor(.secondary)
            }
            Spacer()
            if old {
                EmptyView()
            } else if r.handedOver, let p = m.projects.first(where: { q in q.away != nil
                                                                 && (r.herePath.map { $0 == q.path }
                                                                     ?? r.project.hasSuffix(q.path)) }) {
                if boardOpens(r, p, m.machines) {
                    Button("Open Session") { m.openSession(p) }.controlSize(.small)
                } else {
                    // a PC: no session runs there for aht to open
                    Text("Open it on the PC").font(.caption).foregroundColor(.secondary)
                        .help("No session runs on \(p.awayRemote ?? r.machine) for aht to open: on the PC, "
                              + "its tray offers Continue here")
                }
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
                if m.canSearchEverywhere {
                    Toggle("Also on my other machines", isOn: $m.searchEverywhere)
                        .toggleStyle(.checkbox)
                        .help("Each machine searches its own index; one that does not answer "
                              + "within 20 seconds is left out")
                }
                HelpButton("Search every session")
                if m.searching { ProgressView().controlSize(.small) }
            }
            .padding(.horizontal, 16).padding(.vertical, 8)
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 12) {
                    if !m.searching {
                        ForEach(m.searchMisses, id: \.self) { line in
                            Label(line, systemImage: "exclamationmark.triangle")
                                .foregroundColor(.orange)
                        }
                    }
                    if let q = m.searched, m.hits.isEmpty, !m.searching {
                        Text(nothingFound(q, everywhere: m.searchedOn)).foregroundColor(.secondary)
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
        .onChange(of: m.searchEverywhere) { _ in if m.searched != nil { m.runSearch() } }
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
                if let mc = h.machine {
                    Text("on \(mc)").font(.caption)
                        .padding(.horizontal, 6).padding(.vertical, 2)
                        .background(Color.accentColor.opacity(0.18))
                        .cornerRadius(4)
                        .help("Found in \(mc)'s own sessions")
                }
                Text(AGENT_LABEL[h.agent] ?? h.agent).foregroundColor(.secondary)
                if let t = h.updated { Text(ago(NSNumber(value: t))).foregroundColor(.secondary) }
                if !h.live {
                    Text("deleted — in a backup").font(.caption).foregroundColor(.orange)
                }
                Spacer()
                if let mc = h.machine, machineIsPC(mc, m.machines) {
                    // a PC's: it starts every Pick Up itself
                    Text("Continue it on \(mc)").font(.caption).foregroundColor(.secondary)
                        .help("A Windows PC starts Pick Up and Leave a Note itself: on \(mc), "
                              + "Leave a Note on this Mac to go on with it here")
                } else if let mc = h.machine {
                    // another machine's: Pick Up that session here
                    Button("Continue Here…") { m.pickUpHit(h) }.controlSize(.small)
                        .disabled(!m.canReach || m.pickup != nil)
                        .help("Pick up this session from \(mc): a summary of it comes here; git "
                              + "moves the files")
                } else if h.live, let p = h.project, FileManager.default.fileExists(atPath: p) {
                    Button("Resume") { m.resume(h) }.controlSize(.small)
                    Button("Show Project") { m.show(p) }.controlSize(.small)
                        .disabled(!m.projects.contains { $0.path == p })
                } else if !h.live, h.restoreProject != nil {
                    Button("Restore…") { m.restore(h) }.controlSize(.small)
                }
            }
            if let p = h.project {
                Text(h.machine.map { "\($0): \(p)" } ?? p).font(.caption).foregroundColor(.secondary)
                    .lineLimit(1).truncationMode(.middle)
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
    @State var dries: [String: [String: Any]] = [:]     // another agent's dry run, by agent

    var body: some View {
        if plan.blocked { blocked } else { asking }
    }

    /// The folder there when it is not this one's path.
    @ViewBuilder var paths: some View {
        if let there = firstText(plan.dry["there_path"], plan.dry["remote_path"]), there != plan.project.path {
            PathPair(from: "Here", fromPath: plan.project.path, to: "On \(plan.remote)", toPath: there,
                     hereFirst: true)
        }
    }

    /// Names the disk there cannot hold, or a folder there that is not this
    /// project: what it is, in plain words, and the command that fixes it.
    var blocked: some View {
        VStack(alignment: .leading, spacing: 12) {
            headed("“\(plan.project.name)” cannot go to \(plan.remote) yet", "Hand a project over")
            ScrollView {
                VStack(alignment: .leading, spacing: 10) {
                    paths
                    CrossingNotes(d: plan.dry, receiver: plan.remote, keeper: plan.remote)
                    BlockerList(d: plan.dry)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .frame(maxHeight: 380)
            HStack {
                Spacer()
                Button("Close") { m.handoverPlan = nil }.keyboardShortcut(.defaultAction)
            }
        }
        .padding(20).frame(width: 560)
    }

    var asking: some View {
        VStack(alignment: .leading, spacing: 12) {
            headed("Hand “\(plan.project.name)” over to \(plan.remote)?", "Hand a project over")
            paths
            Text(plan.body).frame(maxWidth: .infinity, alignment: .leading)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
            Divider()
            if plan.toPC {
                // no session starts on a PC: no agent to choose, no task to start on
                Text(pcStartsText(plan.remote)).fixedSize(horizontal: false, vertical: true)
                PermLine(d: plan.dry, agent: "claude", source: firstText(plan.dry["agent"]) ?? "claude", on: plan.remote,
                         leaving: { "the \($0.map { $0 + " " } ?? "")session here" })
            } else {
                agentThere
            }
            CrossingNotes(d: plan.dry, receiver: plan.remote, keeper: plan.remote)
            if !plan.toPC {
                Text("A task to start on over there (optional)").padding(.top, 6)
                TextEditor(text: $plan.task)
                    .font(.body).frame(height: 70)
                    .overlay(RoundedRectangle(cornerRadius: 4).stroke(Color.secondary.opacity(0.3)))
                Text(plan.agent == "claude"
                     ? "With a task, the session begins working on it as soon as it has resumed; "
                        + "you can follow it and answer its questions from the Claude app."
                     : "With a task, \(label) works on it right after reading the summary.")
                    .font(.caption).foregroundColor(.secondary)
            }
            HStack {
                Spacer()
                Button("Cancel") { m.handoverPlan = nil }.keyboardShortcut(.cancelAction)
                Button("Hand Over") {
                    let p = plan
                    m.handoverPlan = nil
                    m.confirmHandover(p)
                }
                .keyboardShortcut(.defaultAction)
                .disabled(current == nil || stopped != nil)
            }
        }
        .padding(20).frame(width: 520)
    }

    // ---- Agent there: Claude Code's own session, or another agent ----

    var label: String { AGENT_LABEL[plan.agent] ?? plan.agent }
    /// The dry run for the agent chosen: the plan itself for Claude Code; for
    /// another agent its own (`--agent X`), nil while it is asked.
    var current: [String: Any]? { plan.agent == "claude" ? plan.dry : dries[plan.agent] }
    /// What stops the agent chosen there (its own dry run's blockers).
    var stopped: String? { plan.agent == "claude" ? nil : current.flatMap { m.problems($0) } }

    @ViewBuilder var agentThere: some View {
        let agents = agentsThere(plan.dry)
        if agents.count > 1 {
            Picker("Agent there", selection: Binding(get: { plan.agent }, set: { pick($0) })) {
                ForEach(agents, id: \.self) { a in Text(agentChoice(a)).tag(a) }
            }
            .frame(maxWidth: 380)
        }
        if let d = current {
            if let why = stopped {
                Text("Not possible with \(label):\n\n" + why).foregroundColor(.orange)
                    .fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
            } else {
                Text(agentStarts(plan.agent, on: plan.remote) + " and this folder is marked as away until you take it back.")
                    .fixedSize(horizontal: false, vertical: true)
                Text(agentCost(plan.agent, on: plan.remote,
                               task: !plan.task.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, d))
                    .font(.caption).foregroundColor(.secondary).fixedSize(horizontal: false, vertical: true)
                if plan.agent != "claude" {
                    let had = (plan.dry["warnings"] as? [String]) ?? []
                    ForEach(((d["warnings"] as? [String]) ?? []).filter { !had.contains($0) }, id: \.self) { w in
                        Text("⚠ " + w).font(.caption).foregroundColor(.orange).fixedSize(horizontal: false, vertical: true)
                    }
                }
                PermLine(d: d, agent: plan.agent, source: firstText(plan.dry["agent"]) ?? "claude", on: plan.remote,
                         leaving: { "the \($0.map { $0 + " " } ?? "")session here" })
            }
        } else {
            HStack(spacing: 8) {
                ProgressView().controlSize(.small)
                Text("Asking \(plan.remote) about \(label)…").foregroundColor(.secondary)
            }
        }
    }

    /// Another agent's dry run is asked once, when it is first chosen.
    func pick(_ a: String) {
        plan.agent = a
        guard a != "claude", dries[a] == nil else { return }
        m.handoverDry(plan.project, agent: a, replace: plan.replaceThere) { d in dries[a] = d }
    }
}

/// Where a project goes: the folder it leaves and the folder it lands in,
/// each that machine's way (C:\Users\me\shop on a PC).
struct PathPair: View {
    let from: String                // "On box"
    let fromPath: String
    let to: String
    let toPath: String
    let hereFirst: Bool             // which of the two is this Mac's (shown as ~/…)

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            row(from, hereFirst ? tilde(fromPath) : fromPath)
            row(to, hereFirst ? toPath : tilde(toPath))
        }
    }

    func row(_ label: String, _ path: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Text(label).foregroundColor(.secondary).frame(width: 90, alignment: .trailing)
            Text(path).font(.system(.callout, design: .monospaced))
                .lineLimit(1).truncationMode(.middle).textSelection(.enabled)
        }
    }
}

/// A command to run, with a Copy button.
struct CopyLine: View {
    let command: String
    @State var copied = false

    var body: some View {
        HStack(spacing: 8) {
            Text(command).font(.system(.callout, design: .monospaced))
                .textSelection(.enabled).lineLimit(2).truncationMode(.middle)
            if !command.contains("…") {     // "aht remote paths box …" is a pattern, not a command
                Button(copied ? "Copied" : "Copy") {
                    toClipboard(command)
                    copied = true
                }
                .controlSize(.small)
            }
        }
    }
}

/// A blocker in plain words, and the command that fixes it.
struct FixLine: View {
    let text: String
    let fix: String?
    var icon = "exclamationmark.triangle.fill"
    var tint = Color.orange         // a blocker; a note is .primary

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Label(text, systemImage: icon).foregroundColor(tint)
                .fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
            if let f = fix { CopyLine(command: f).padding(.leading, 22) }
        }
    }
}

/// What stands in the way, each with its fix (`aht remote paths …`).
struct BlockerList: View {
    let d: [String: Any]

    var body: some View {
        ForEach(blockerLines(d), id: \.self) { b in
            let f = blockerFix(b, d)
            FixLine(text: f.text, fix: f.fix)
        }
    }
}

/// The suggested `.gitattributes`, to copy into the project.
struct GitattributesHint: View {
    let lines: [String]
    @State var copied = false

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Label("This git project has no .gitattributes. With one like this, git keeps line endings "
                  + "the same on both systems. aht never writes it for you.", systemImage: "text.alignleft")
                .fixedSize(horizontal: false, vertical: true)
            HStack(alignment: .top) {
                Text(lines.joined(separator: "\n")).font(.system(.callout, design: .monospaced))
                    .textSelection(.enabled)
                Spacer()
                Button(copied ? "Copied" : "Copy") {
                    toClipboard(lines.joined(separator: "\n") + "\n")
                    copied = true
                }
                .controlSize(.small)
            }
            .padding(8)
            .background(RoundedRectangle(cornerRadius: 6).fill(Color.primary.opacity(0.04)))
            .padding(.leading, 22)
        }
    }
}

/// What crossing to another system means for the files: names the
/// receiving disk cannot hold (they block), files that differ only in line
/// endings, names kept aside, the git note and the `.gitattributes` hint.
struct CrossingNotes: View {
    let d: [String: Any]
    let receiver: String            // where the files go: "this Mac", "pc"
    let keeper: String              // whose copy stays when only line endings differ

    var body: some View {
        let names = nameProblems(d)
        VStack(alignment: .leading, spacing: 8) {
            if !names.isEmpty {
                FixLine(text: namesText(names, on: receiver), fix: nil, icon: "textformat")
            }
            if let e = eolText(d, keeper: keeper) {
                Label(e, systemImage: "arrow.left.arrow.right").fixedSize(horizontal: false, vertical: true)
            }
            if let u = unsafeText(d, receiver: receiver) {
                Label(u, systemImage: "tray.full").fixedSize(horizontal: false, vertical: true)
            }
            if let g = gitNote(d) {
                FixLine(text: g.text, fix: g.fix, icon: "arrow.triangle.branch", tint: .primary)
            }
            if let lines = gitattributesHint(d) { GitattributesHint(lines: lines) }
        }
    }
}

/// Bring Here from M: the projects aht knows there, then the dry run of the
/// one picked (where it lands here, what comes, what stands in the way),
/// then Bring Here.
struct BringSheet: View {
    @EnvironmentObject var m: AppModel

    var body: some View {
        let v = m.bring ?? BringView(machine: "")
        VStack(alignment: .leading, spacing: 10) {
            headed("Bring a project here from \(v.machine)", "Hand a project over")
            if v.done == nil { list(v) }
            if v.picked != nil {
                Divider()
                plan(v)
            }
            Divider()
            footer(v)
        }
        .padding(20).frame(width: 660, height: 640)
    }

    @ViewBuilder func list(_ v: BringView) -> some View {
        let rows = thereProjects(v.list)
        if v.listing {
            HStack(spacing: 8) {
                ProgressView().controlSize(.small)
                Text("Asking \(v.machine) for the projects aht keeps there…").foregroundColor(.secondary)
            }
            Spacer(minLength: 0)
        } else if rows.isEmpty {
            Text(firstText(v.said, pickupProblems(v.list) ?? "") ?? "aht keeps no project on \(v.machine).")
                .foregroundColor(v.list.isEmpty ? .orange : .secondary).textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        } else {
            BlockerList(d: v.list)
            ScrollView {
                VStack(alignment: .leading, spacing: 2) {
                    ForEach(rows) { t in ThereProjectRow(t: t, picked: t.path == v.picked) }
                }
            }
            .frame(maxHeight: v.picked == nil ? .infinity : 150)
        }
    }

    @ViewBuilder func plan(_ v: BringView) -> some View {
        let name = baseName(v.picked ?? "")
        if v.loading {
            HStack(spacing: 8) {
                ProgressView().controlSize(.small)
                Text("Asking \(v.machine) about \(name)…").foregroundColor(.secondary)
            }
            Spacer(minLength: 0)
        } else if v.dry.isEmpty {
            Text(v.said.isEmpty ? "aht gave no answer — see the log (Settings)." : v.said)
                .foregroundColor(.orange).textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        } else {
            ScrollView {
                VStack(alignment: .leading, spacing: 10) {
                    PathPair(from: "On \(v.machine)", fromPath: firstText(v.dry["there_path"]) ?? v.picked ?? "",
                             to: "Here", toPath: firstText(v.dry["here_path"]) ?? "?", hereFirst: false)
                    if let d = v.done {
                        Text(bringDoneText(d, machine: v.machine, agent: v.agent))
                            .fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
                        if v.agent == "kimi", let first = farFirst(d) { FirstPromptBox(line: first) }
                    } else {
                        agentHere(v)
                        Text(bringText(v.dry, machine: v.machine, agent: v.agent)).fixedSize(horizontal: false, vertical: true)
                            .textSelection(.enabled)
                        // the level its session opens in here, like it ran there; or
                        // the level the agent chosen starts in
                        let ses = (v.dry["session"] as? [String: Any]) ?? [:]
                        if pickupProblems(v.dry) == nil, firstText(ses["id"]) != nil || v.agent != "claude" {
                            let from = firstText(ses["agent"], v.agent == "claude" ? v.dry["agent"] : nil) ?? "claude"
                            PermLine(d: v.dry, agent: v.agent == "claude" ? from : v.agent, source: from,
                                     leaving: { "the \($0.map { $0 + " " } ?? "")session on \(v.machine)" })
                        }
                        CrossingNotes(d: v.dry, receiver: "this Mac", keeper: "this Mac")
                        BlockerList(d: v.dry)
                        if idleBlock(v.dry) || v.allowIdle { idle(v) }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }

    /// Agent here: Claude Code's own session (no tokens), or another agent
    /// installed here that starts with the summary (one turn); its own dry
    /// run says what stops it and the level it starts in.
    @ViewBuilder func agentHere(_ v: BringView) -> some View {
        let agents = agentsHere(m.agentCLIs)
        if agents.count > 1 || v.agent != "claude" {
            Picker("Agent here", selection: Binding(
                get: { m.bring?.agent ?? "claude" },
                set: { m.bring?.agent = $0; m.lookBring(v.picked ?? "") })) {
                ForEach(agents.contains(v.agent) ? agents : agents + [v.agent], id: \.self) { a in
                    Text(agentChoice(a)).tag(a)
                }
            }
            .frame(maxWidth: 380)
            Text(agentCost(v.agent, on: nil, v.dry)).font(.caption).foregroundColor(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    @ViewBuilder func idle(_ v: BringView) -> some View {
        Toggle("Bring it anyway; the idle session there stays open", isOn: Binding(
            get: { m.bring?.allowIdle ?? false },
            set: { m.bring?.allowIdle = $0; m.lookBring(v.picked ?? "") }))
            .toggleStyle(.checkbox).disabled(v.done != nil)
        Text("If anyone types into that session later, Send Back keeps both versions.")
            .font(.caption).foregroundColor(.secondary)
    }

    @ViewBuilder func footer(_ v: BringView) -> some View {
        HStack {
            if let d = v.done {
                Spacer()
                Button("Done") {
                    // the project that came, selected in Projects
                    if pickupProblems(d) == nil, let here = firstText(d["here_path"]) {
                        (m.tab, m.selection) = (.projects, here)
                    }
                    m.bring = nil
                }
                .keyboardShortcut(.defaultAction)
            } else {
                Button("Cancel") { m.bring = nil }.keyboardShortcut(.cancelAction)
                Spacer()
                if v.applying {
                    ProgressView().controlSize(.small)
                    Text("Bringing it here…").foregroundColor(.secondary)
                }
                Button("Bring Here") { m.applyBring() }
                    .keyboardShortcut(.defaultAction)
                    .disabled(!bringReady(v))
                    .help("Copy the project and its history here, mark it on \(v.machine) as being here, "
                          + "and open its session here")
            }
        }
    }
}

/// Peek: the last lines of the agent's window there, its state, and a way
/// into the window.
struct PeekSheet: View {
    @EnvironmentObject var m: AppModel

    var body: some View {
        let v = m.peek ?? PeekView(project: Project([:]))
        let label = v.project.awayAgentLabel ?? "The agent"
        let lines = nameList(v.d["screen"])
        VStack(alignment: .leading, spacing: 10) {
            headed("\(label) on \(v.project.awayRemote ?? v.project.away ?? "the other machine")", "Hand a project over")
            if v.loading {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text("Looking at its window…").foregroundColor(.secondary)
                }
                Spacer(minLength: 0)
            } else {
                if let st = peekState(v.d) {
                    HStack(spacing: 8) {
                        Text(st.text).fontWeight(.medium)
                        if let h = st.hint { Text(h).font(.caption).italic().foregroundColor(.secondary) }
                    }
                }
                if let e = firstText(v.d["error"]) {
                    Text(e).foregroundColor(.orange).textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
                }
                ScrollView {
                    Text(lines.isEmpty ? (v.d["error"] == nil ? "Its window shows nothing yet." : "") : lines.joined(separator: "\n"))
                        .font(.system(.callout, design: .monospaced)).textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading).padding(8)
                }
                .background(RoundedRectangle(cornerRadius: 6).fill(Color.primary.opacity(0.04)))
                Text("The last lines its window shows; nothing is typed there. Open Its Window to answer it or end it.")
                    .font(.caption).foregroundColor(.secondary)
            }
            HStack {
                Button("Look Again") { m.peekThere(v.project) }.disabled(v.loading)
                Button("Open Its Window") { m.openSession(v.project) }
                Spacer()
                Button("Close") { m.peek = nil }.keyboardShortcut(.defaultAction)
            }
        }
        .padding(20).frame(width: 640, height: 460)
    }
}

/// One project in Bring Here's list.
struct ThereProjectRow: View {
    @EnvironmentObject var m: AppModel
    let t: ThereProject
    let picked: Bool

    var body: some View {
        Button(action: { if !picked { m.lookBring(t.path) } }) {
            HStack(spacing: 8) {
                Image(systemName: picked ? "largecircle.fill.circle" : "circle")
                    .foregroundColor(picked ? .accentColor : .secondary)
                VStack(alignment: .leading, spacing: 1) {
                    Text(t.name).fontWeight(.medium)
                        + Text(t.title.map { "   “\($0)”" } ?? "").foregroundColor(.secondary)
                    Text(t.path).font(.caption).foregroundColor(.secondary)
                        .lineLimit(1).truncationMode(.middle)
                    if let st = thereState(t) {
                        Text(st).font(.caption).foregroundColor(.orange).lineLimit(2)
                    }
                }
                Spacer(minLength: 8)
                if let u = t.updated { Text(ago(u)).foregroundColor(.secondary) }
            }
            .padding(.vertical, 3)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(m.bring?.applying ?? false)
        .help(t.blocked ?? t.here.map { "It comes here to " + tilde($0) } ?? "")
    }
}

/// Send Back to M on a project brought here from M: M plans the return
/// against its own copy, this sheet shows it in Take Back's words.
struct SendBackSheet: View {
    @EnvironmentObject var m: AppModel

    var body: some View {
        let v = m.sendBack ?? SendBackView(project: Project([:]), machine: "")
        VStack(alignment: .leading, spacing: 10) {
            headed("Send “\(v.project.name)” back to \(v.machine)?", "Hand a project over")
            if v.loading {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text("Asking \(v.machine) what changed on both sides…").foregroundColor(.secondary)
                }
                Spacer(minLength: 0)
            } else if v.dry.isEmpty {
                Text(v.said.isEmpty ? "aht gave no answer — see the log (Settings)." : v.said)
                    .foregroundColor(.orange).textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: 0)
            } else {
                ScrollView { plan(v).frame(maxWidth: .infinity, alignment: .leading) }
            }
            Divider()
            footer(v)
        }
        .padding(20).frame(width: 600, height: 520)
    }

    @ViewBuilder func plan(_ v: SendBackView) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            PathPair(from: "Here", fromPath: firstText(v.dry["here_path"]) ?? v.project.path,
                     to: "On \(v.machine)", toPath: firstText(v.dry["there_path"]) ?? "?", hereFirst: true)
            if let d = v.done {
                Text(sendBackDoneText(d, machine: v.machine))
                    .fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
            } else {
                notes(v)
            }
        }
    }

    /// The plan in Take Back's words, what crossing means for the files, and
    /// what stands in the way ("send it back anyway" lifts the version check).
    @ViewBuilder func notes(_ v: SendBackView) -> some View {
        Text(sendBackText(v.dry, machine: v.machine, preferHere: v.preferHere))
            .fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
        if !((v.dry["conflicts"] as? [String: Any]) ?? [:]).isEmpty || v.preferHere {
            Picker("Changed on both machines", selection: Binding(
                get: { m.sendBack?.preferHere ?? false },
                set: { m.sendBack?.preferHere = $0; m.lookSendBack() })) {
                Text("Keep both (\(v.machine)'s stays, this one next to it)").tag(false)
                Text("Use this Mac's versions (\(v.machine)'s set aside there)").tag(true)
            }
            .pickerStyle(.radioGroup)
        }
        CrossingNotes(d: v.dry, receiver: v.machine, keeper: v.machine)
        BlockerList(d: v.dry)
        if versionBlock(v.dry) || v.ignoreVersion {
            Toggle("Send it back anyway", isOn: Binding(
                get: { m.sendBack?.ignoreVersion ?? false },
                set: { m.sendBack?.ignoreVersion = $0; m.lookSendBack() }))
                .toggleStyle(.checkbox)
                .help("The history here was written by a newer Claude Code than the one on \(v.machine): "
                      + "update it there first, or send it back as it is")
        }
    }

    @ViewBuilder func footer(_ v: SendBackView) -> some View {
        HStack {
            if v.done != nil {
                Spacer()
                Button("Done") { m.sendBack = nil }.keyboardShortcut(.defaultAction)
            } else {
                Button("Cancel") { m.sendBack = nil }.keyboardShortcut(.cancelAction)
                Spacer()
                if v.applying {
                    ProgressView().controlSize(.small)
                    Text("Sending it back…").foregroundColor(.secondary)
                }
                Button("Send Back") { m.applySendBack() }
                    .keyboardShortcut(.defaultAction)
                    .disabled(!sendBackReady(v))
            }
        }
    }
}

/// A project another machine took from here with Bring Here: where it is,
/// that it goes back from there, and Release (Take Back too, when this Mac
/// reaches that machine).
struct HeldThereBanner: View {
    @EnvironmentObject var m: AppModel
    let p: Project
    let line: String

    var body: some View {
        HStack(alignment: .center, spacing: 10) {
            Image(systemName: "laptopcomputer.and.arrow.down").foregroundColor(.blue)
            Text(line).fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 8)
            // handed over to a PC from here: its buttons are the project's own (AwayButtons)
            if p.awayDrivenBy == "there" {
                if p.takesBack(m.machines) { Button("Take Back…") { m.takeBack(p) }.disabled(!m.supported) }
                Button("Release…") { m.release(p) }
                    .help("Stop waiting for it: the files here stay as they are, and the copy on "
                          + "\(p.awayHolder ?? p.away ?? "that machine") is not touched")
            }
        }
        .padding(.horizontal, 10).padding(.vertical, 6)
        .background(RoundedRectangle(cornerRadius: 6).fill(Color.blue.opacity(0.08)))
        .disabled(m.working != nil)
    }
}

/// Under a project's buttons: Claude's usage limit, and how the last action went.
struct DetailNotes: View {
    @EnvironmentObject var m: AppModel
    let p: Project

    var body: some View {
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
            if let first = m.firstPrompts[p.path] { FirstPromptBox(line: first) }
        }
    }
}

/// More: what else there is for a project.
struct MoreMenu: View {
    @EnvironmentObject var m: AppModel
    let p: Project

    var body: some View {
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
    }
}

/// The buttons of a project that is on another machine.
struct AwayButtons: View {
    @EnvironmentObject var m: AppModel
    let p: Project

    var body: some View {
        if p.awayDrivenBy != "there" && p.pcAway(m.machines) {
            // a PC: no session started there, so none to open or peek at
            Button("Take Back…") { m.takeBack(p) }
                .keyboardShortcut(.defaultAction)
                .disabled(!p.takesBack(m.machines))
                .help(p.takesBack(m.machines) ? "Bring the work done on the PC back here"
                      : machineCannotAsk(p.awayRemote, m.machines))
            Button("Release…") { m.release(p) }
                .help("Stop waiting for it: the files here stay as they are, "
                      + "and the copy over there is not touched")
        } else if p.awayDrivenBy != "there" {
            Button("Take Back…") { m.takeBack(p) }
                .keyboardShortcut(.defaultAction)
            Button("Open Session") { m.openSession(p) }
            if p.awayWindow != nil {
                Button("Peek…") { m.peekThere(p) }
                    .help("The last lines the agent's window there shows; nothing is typed there")
            }
            Button("Release…") { m.release(p) }
                .help("Stop waiting for it: the files here stay as they are, "
                      + "and the copy over there is not touched")
        }
        HelpButton("Hand a project over")
    }
}

/// The buttons of a project that is here.
struct HereButtons: View {
    @EnvironmentObject var m: AppModel
    let p: Project

    var body: some View {
        if let to = p.sendBackTo, p.copyOf?.pcBlocks(m.machines) == true {
            // a PC: the project goes back from there
            Text("Take it back on \(to)").foregroundColor(.secondary)
                .help((sendBackBlocked(p, m.machines) ?? "") + (machineAnswers(p.copyOf?.remote, m.machines)
                      ? "" : ". " + machineCannotAsk(p.copyOf?.remote, m.machines)))
        } else if let to = p.sendBackTo {
            let why = sendBackBlocked(p, m.machines)
            Button("Send Back to \(to)…") { m.openSendBack(p) }
                .keyboardShortcut(.defaultAction)
                .disabled(why != nil || !m.canReach || p.open == "working" || p.handing != nil)
                .help(why ?? "Send the work done here back to \(to), which keeps this project")
        } else {
            Button(m.machine.map { "Hand Over to \($0)…" } ?? "Hand Over…") { m.handOver(p) }
                .disabled(m.machine == nil || !m.supported || p.open != nil || p.handing != nil)
        }
        syncToggle
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
        MachinesMenu(p: p)
    }

    var syncToggle: some View {
        let refused = p.mirror == nil && (syncRefused(p, m.machine) || p.sendBackTo != nil)
        return Toggle("Keep in sync" + (p.mirror.map { " with \($0)" } ?? ""),
                      isOn: Binding(get: { p.mirror != nil }, set: { m.keepInSync(p, $0) }))
            .disabled(m.machine == nil || !m.supported || p.handing != nil || refused)
            .help(!refused ? ""
                  : p.sendBackTo != nil ? "This folder is \(p.sendBackTo ?? "")'s project, brought here: "
                    + (p.copyOf?.pcBlocks(m.machines) == true ? "take it back on \(p.sendBackTo ?? "")" : "Send Back returns the work")
                  : "This folder is \(m.machine ?? "that machine")'s synced copy: syncing "
                    + "it back would overwrite one copy with the other")
    }
}

/// How the folders here are found on a machine, in Machines.
struct PathMapLine: View {
    let mc: Machine
    let map: PathMap

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: "folder").foregroundColor(.secondary)
            Text(pathMapText(map, machine: mc.name)).font(.caption).foregroundColor(.secondary)
                .lineLimit(2).textSelection(.enabled)
        }
        .help("aht remote paths \(mc.name) --same | --home | --add HERE THERE changes it")
    }
}

/// Bring Here from … in Projects: the machines that can be asked.
struct BringMenu: View {
    @EnvironmentObject var m: AppModel

    var body: some View {
        let from = askableMachines(m.machines)
        if !from.isEmpty {
            Menu("Bring Here") {
                ForEach(from, id: \.self) { n in Button("From \(n)…") { m.openBring(from: n) } }
            }
            .fixedSize()
            .disabled(m.working != nil || !m.canReach)
            .help("Bring a project aht keeps on another machine here, with its history")
        }
    }
}

/// Switch Agent and Hand Back: what the dry run found for the way picked
/// (a new session or the agent's own one), then Switch, or Summary Only.
/// The level the next agent starts in, from a dry run's `perm`: the line,
/// the no-exact-match note, and the flags in small text; a never-ask level
/// in a caution box (no blocker: the user chose it). Nothing from an older
/// core that sends no `perm`.
struct PermLine: View {
    @EnvironmentObject var m: AppModel
    let d: [String: Any]
    let agent: String
    var source: String? = nil
    var on: String? = nil
    var later: String? = nil
    let leaving: (String?) -> String

    var body: some View {
        if let p = permInfo(d, agent: agent, setting: permSetting(m.config)) {
            let w = permWords(p, agent: agent, source: source, on: on, leaving: leaving)
            let never = p.level == "never"
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Image(systemName: never ? "exclamationmark.triangle.fill" : "hand.raised")
                    .foregroundColor(never ? .orange : .secondary)
                VStack(alignment: .leading, spacing: 3) {
                    Text(w.line).fontWeight(never ? .semibold : .regular)
                        .fixedSize(horizontal: false, vertical: true)
                    if let f = w.fell {
                        Text(f).font(.caption).foregroundColor(.orange).fixedSize(horizontal: false, vertical: true)
                    }
                    Text(w.flags).font(.caption).foregroundColor(.secondary)
                        .fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
                    if let l = later {
                        Text(l).font(.caption).foregroundColor(.secondary)
                    }
                }
                Spacer(minLength: 0)
            }
            .padding(never ? 8 : 0)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 6).fill(never ? Color.orange.opacity(0.12) : Color.clear))
            .overlay(RoundedRectangle(cornerRadius: 6).stroke(never ? Color.orange.opacity(0.7) : Color.clear))
            .help(never ? "Not a stop: you chose this level. Settings ▸ Permissions sets what the next agent starts in."
                        : "Settings ▸ Permissions sets what the next agent starts in.")
        }
    }
}

/// Kimi below never-ask: it opened (or starts) without reading the summary;
/// the line to paste as its first message, with a Copy button.
struct FirstPromptBox: View {
    let line: String
    @State private var copied = false

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(KIMI_PASTE).font(.callout.weight(.semibold)).fixedSize(horizontal: false, vertical: true)
            HStack(alignment: .top, spacing: 8) {
                Text(line).font(.system(.caption, design: .monospaced)).textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, alignment: .leading)
                Button(copied ? "Copied" : "Copy") {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(line, forType: .string)
                    copied = true
                }
                .controlSize(.small)
                .help("Put the first message on the clipboard, to paste into Kimi")
            }
        }
        .padding(8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 6).fill(Color.accentColor.opacity(0.08)))
        .overlay(RoundedRectangle(cornerRadius: 6).stroke(Color.accentColor.opacity(0.35)))
    }
}

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
            if blocked == nil {
                // Hand Back leaves the agent that has the work now
                PermLine(d: d, agent: firstText(d["target"]) ?? plan.target,
                         source: plan.back ? plan.project.handBack?.to
                                           : firstText((d["source"] as? [String: Any])?["agent"]),
                         leaving: { "the \($0.map { $0 + " " } ?? "")session you are leaving" })
            }
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

/// Pick Up from M, Leave a Note on M and Hand Back to M: what the dry run
/// found there (the folder and how, the latest sessions, git, the summary),
/// then Open in … or Copy the Start Line (Pick Up), or Leave the Note; Done.
struct PickupSheet: View {
    @EnvironmentObject var m: AppModel

    var body: some View {
        let v = m.pickup ?? PickupView(project: Project([:]), machine: "", kind: "pickup")
        VStack(alignment: .leading, spacing: 10) {
            headed(pickupTitle(v), "Pick up on another machine")
            if v.loading {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text(v.kind == "note" ? "Asking \(v.machine) where the project is…"
                                          : "Asking \(v.machine) for the folder, its sessions and a summary…")
                        .foregroundColor(.secondary)
                }
                Spacer(minLength: 0)
            } else if v.dry.isEmpty {
                Text(v.said.isEmpty ? "aht gave no answer — see the log (Settings)." : v.said)
                    .foregroundColor(.orange).textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: 0)
            } else {
                folder(v)
                if v.kind == "pickup" { sessions(v) } else { about(v) }
                notices(v)
                summary(v)
                if let d = v.done {
                    result(v, d)
                } else if v.kind == "pickup" {
                    if thereMatch(v.dry).path != nil { openIn(v) }
                } else {
                    Text(noteReader(v.dry, machine: v.machine)).font(.callout)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            Divider()
            footer(v)
        }
        .padding(20).frame(width: 660, height: 640)
    }

    /// The folder there: how it was found (and "this is it" when that is not
    /// sure), or the folders it could be.
    @ViewBuilder func folder(_ v: PickupView) -> some View {
        let mt = thereMatch(v.dry)
        let how = matchHow(mt.how)
        if mt.path != nil {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Image(systemName: how.sure ? "checkmark.circle.fill" : "questionmark.circle.fill")
                    .foregroundColor(how.sure ? .green : .orange)
                Text(matchLine(mt, machine: v.machine)).lineLimit(2).truncationMode(.middle)
                    .textSelection(.enabled)
            }
            if !how.sure && v.there == nil && v.done == nil {
                Toggle("This is the same project", isOn: Binding(
                    get: { m.pickup?.confirmed ?? false }, set: { m.pickup?.confirmed = $0 }))
                    .toggleStyle(.checkbox)
                    .help("aht did not find it by its project id: check the folder before going on")
            }
        } else {
            Label(matchProblem(mt, machine: v.machine), systemImage: "exclamationmark.triangle.fill")
                .foregroundColor(.orange).fixedSize(horizontal: false, vertical: true)
            ForEach(mt.candidates, id: \.self) { c in
                Button(action: { m.pickup?.there = c; m.lookThere() }) {
                    HStack(spacing: 6) {
                        Image(systemName: "circle").foregroundColor(.secondary)
                        Text(c).lineLimit(1).truncationMode(.middle)
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .help("Go on with this folder on \(v.machine)")
            }
            if mt.candidates.isEmpty {
                HStack {
                    TextField("the folder on \(v.machine)", text: Binding(
                        get: { m.pickup?.typed ?? "" }, set: { m.pickup?.typed = $0 }))
                        .textFieldStyle(.roundedBorder)
                    Button("Look There") {
                        m.pickup?.there = v.typed.trimmingCharacters(in: .whitespaces)
                        m.lookThere()
                    }
                    .disabled(v.typed.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
        }
    }

    /// The latest sessions there; a click picks the one to go on from.
    @ViewBuilder func sessions(_ v: PickupView) -> some View {
        let rows = Array(thereSessions(v.dry).prefix(4))
        let picked = thereSession(v.dry, picked: v.session)
        if !rows.isEmpty {
            Text("Latest sessions on \(v.machine)").font(.subheadline).foregroundColor(.secondary)
            VStack(alignment: .leading, spacing: 2) {
                ForEach(rows) { s in
                    Button(action: {
                        guard s.id != picked else { return }
                        m.pickup?.session = s.id
                        m.pickup?.agent = s.agent
                        m.lookThere()
                    }) {
                        HStack(spacing: 6) {
                            Image(systemName: s.id == picked ? "largecircle.fill.circle" : "circle")
                                .foregroundColor(s.id == picked ? .accentColor : .secondary)
                            Text(s.title).lineLimit(1)
                            Text(AGENT_LABEL[s.agent] ?? s.agent).foregroundColor(.secondary)
                            if let t = s.updated { Text(ago(NSNumber(value: t))).foregroundColor(.secondary) }
                            if let st = s.state {
                                Text(st == "working" ? "working there" : "open there").font(.caption)
                                    .foregroundColor(.orange)
                            }
                            Spacer(minLength: 0)
                        }
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .disabled(v.done != nil)
                }
            }
        }
    }

    /// A note: the session here whose work it tells of.
    @ViewBuilder func about(_ v: PickupView) -> some View {
        let src = (v.dry["source"] as? [String: Any]) ?? [:]
        if let a = src["agent"] as? String {
            Text("About the latest \(AGENT_LABEL[a] ?? a) session here"
                 + ((src["title"] as? String).map { " (“\($0)”)" } ?? "") + ".")
                .foregroundColor(.secondary).lineLimit(2)
        }
    }

    /// The git warning, the core's warnings, and what stands in the way.
    @ViewBuilder func notices(_ v: PickupView) -> some View {
        if let g = gitWarning(v.dry, machine: v.machine) {
            HStack(alignment: .top, spacing: 8) {
                Image(systemName: "arrow.triangle.branch").foregroundColor(.orange)
                Text(g).fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
            }
            .padding(8)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 6).fill(Color.orange.opacity(0.12)))
        }
        ForEach(otherWarnings(v.dry), id: \.self) { w in
            Text("⚠ " + w).foregroundColor(.orange).fixedSize(horizontal: false, vertical: true)
        }
        if thereMatch(v.dry).path != nil, let why = pickupProblems(v.dry) {
            Text(why).foregroundColor(.orange).fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
        }
    }

    /// The summary the agent reads (masked over there).
    @ViewBuilder func summary(_ v: PickupView) -> some View {
        let text = pickupBrief(v.dry).text
        if let t = text {
            ScrollView {
                MarkdownView(text: t).padding(10)
            }
            .frame(maxHeight: .infinity)
            .background(RoundedRectangle(cornerRadius: 6).fill(Color.primary.opacity(0.03)))
            .overlay(RoundedRectangle(cornerRadius: 6).stroke(Color.secondary.opacity(0.25)))
        } else {
            Spacer(minLength: 0)
        }
    }

    /// Open in …: the agent, and the switch dialog's words for it with the token line.
    @ViewBuilder func openIn(_ v: PickupView) -> some View {
        let back = pickupIsBack(v.dry)
        let agent = v.open ?? pickupAgent(v.dry, installed: m.agentCLIs) ?? ""
        if !back && m.agentCLIs.count > 1 {
            Picker("Open in", selection: Binding(get: { m.pickup?.open ?? agent },
                                                 set: { m.pickup?.open = $0 })) {
                ForEach(m.agentCLIs, id: \.self) { Text(AGENT_LABEL[$0] ?? $0).tag($0) }
            }
            .fixedSize()
        }
        if !agent.isEmpty {
            Text(pickupOpenText(v.dry, agent: agent, machine: v.machine, hook: m.hookOn))
                .font(.callout).fixedSize(horizontal: false, vertical: true)
            if let cost = openCost(agent, back: back, hook: m.hookOn, machine: v.machine, kimiReads: kimiReads(v.dry)) {
                Text(cost).font(.caption).foregroundColor(.secondary)
            }
            PermLine(d: v.dry, agent: agent, source: firstText((v.dry["source"] as? [String: Any])?["agent"]),
                     leaving: { "the \($0.map { $0 + " " } ?? "")session on \(v.machine)" })
        }
    }

    /// What --apply did, and the line that starts the agent.
    @ViewBuilder func result(_ v: PickupView, _ d: [String: Any]) -> some View {
        Text(v.kind == "note" ? noteDoneText(d, machine: v.machine)
                              : pickupDoneText(d, machine: v.machine, project: v.project.path, copied: v.copied))
            .font(.callout).fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
        if let line = startLine(d), v.kind == "pickup" {
            Text(line).font(.system(.caption, design: .monospaced)).foregroundColor(.secondary)
                .lineLimit(3).truncationMode(.middle).textSelection(.enabled)
                .help("The line that starts the agent here with the summary")
        }
        // Kimi below never-ask: it starts without reading the summary
        if v.kind == "pickup", pickupProblems(d) == nil, let first = kimiFirst(d) { FirstPromptBox(line: first) }
    }

    @ViewBuilder func footer(_ v: PickupView) -> some View {
        let ready = pickupReady(v)
        let back = pickupIsBack(v.dry)
        let agent = v.open ?? pickupAgent(v.dry, installed: m.agentCLIs)
        let label = agent.map { AGENT_LABEL[$0] ?? $0 } ?? "an Agent"
        HStack {
            if let d = v.done {
                let line = startLine(d) ?? ""
                if v.kind == "pickup" && !line.isEmpty && pickupProblems(d) == nil {
                    Button(v.copied ? "Copied" : "Copy the Start Line") {
                        NSPasteboard.general.clearContents()
                        NSPasteboard.general.setString(line, forType: .string)
                        m.pickup?.copied = true
                    }
                }
                Spacer()
                Button("Done") { m.pickup = nil }.keyboardShortcut(.defaultAction)
            } else {
                Button("Cancel") { m.pickup = nil }.keyboardShortcut(.cancelAction)
                Spacer()
                if v.applying { ProgressView().controlSize(.small) }
                if v.kind == "pickup" {
                    Button("Copy the Start Line") { m.applyPickup(open: agent, copy: true) }
                        .disabled(!ready || agent == nil || !(m.agentCLIs.contains(agent ?? "") || back))
                        .help("Write the summary here and a copy of it on \(v.machine), and put the line "
                              + "that starts \(label) with it on the clipboard; nothing opens"
                              + (agent == "kimi" ? (kimiReads(v.dry) ? " (Kimi reads it in a run of its own first: tokens)"
                                                                     : " (then paste the first message aht shows you into Kimi)") : ""))
                    Button(back ? "Open \(label)'s Session" : "Open in \(label)") {
                        m.applyPickup(open: agent)
                    }
                    .keyboardShortcut(.defaultAction)
                    .disabled(!ready || agent == nil || !(m.agentCLIs.contains(agent ?? "") || back))
                } else {
                    Button(back || v.back ? "Hand Back" : "Leave the Note") { m.applyPickup() }
                        .keyboardShortcut(.defaultAction)
                        .disabled(!ready)
                }
            }
        }
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
                 ? undoNoCopyText(m.checkpointsOn)
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
            let typed = task.trimmingCharacters(in: .whitespacesAndNewlines)
            // beside Start: what starting it answered until another task is
            // typed, else the dry run (the latest; its blockers only for this text)
            let dry = m.opinionDry.flatMap { $0.path == v.project.path ? $0 : nil }
            let shown = typed.isEmpty && !v.started.isEmpty ? v.started : (dry?.d ?? [:])
            let now = dry.map { $0.task == typed } ?? false
            let lv = opinionLevels(shown, typed: !typed.isEmpty && now)
            HStack(alignment: .top) {
                TextField("A task for both, e.g. make the parser accept empty lines",
                          text: $task, axis: .vertical)
                    .lineLimit(2...4).textFieldStyle(.roundedBorder)
                Button("Start") {
                    m.startOpinion(v.project, task: task)
                    task = ""
                }
                .disabled(typed.isEmpty || (now && !lv.blockers.isEmpty))
            }
            Text("Two agents each get a throwaway copy of the project and the same task; the project "
                 + "itself stays untouched until you pick one. This uses both agents' tokens. Claude Code "
                 + "may edit files in its copy at any level; the commands it runs follow the level of the "
                 + "project's latest session, never higher. Kimi Code's run on its own never asks, so Kimi "
                 + "takes part only when that session runs in never-ask mode.")
                .font(.caption).foregroundColor(.secondary).fixedSize(horizontal: false, vertical: true)
            // the level each agent works in, in the core's words, and the warnings
            ForEach(lv.agents, id: \.self) { a in
                PermLine(d: shown, agent: a, leaving: { _ in "the project's latest session" })
            }
            ForEach(lv.warnings, id: \.self) { w in
                Text("⚠ " + w).font(.callout).foregroundColor(.orange).fixedSize(horizontal: false, vertical: true)
            }
            if !lv.blockers.isEmpty {
                Text("Not possible now:\n\n" + lv.blockers.map { "• " + $0 }.joined(separator: "\n\n"))
                    .font(.callout).foregroundColor(.orange).fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
            }
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
        .onAppear {
            // the dry run as the dialog opens, unless one for this project is in hand
            if v.started.isEmpty && m.opinionDry?.path != v.project.path { m.opinionDryRun(v.project, task: task, wait: 0) }
        }
        .onChange(of: task) { t in
            if !(t.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !v.started.isEmpty) {
                m.opinionDryRun(v.project, task: t)
            }
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
                if let lv = r.perm?["level"] as? String, PERM_NAME[lv] != nil {
                    let flags = ((r.perm?["flags"] as? [Any]) ?? []).map { shellWord("\($0)") }.joined(separator: " ")
                    Text(permName(lv, sandbox: r.perm?["sandbox"] as? Bool == true)).font(.caption)
                        .foregroundColor(lv == "never" ? .orange : .secondary)
                        .help(flags.isEmpty ? "No flags" : "Flags: " + flags)
                }
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
            PermLine(d: v.dry, agent: firstText(v.dry["agent"]) ?? "claude",
                     source: firstText(v.dry["agent"]) ?? "claude",
                     on: firstText((v.dry["job"] as? [String: Any])?["remote"]) ?? m.machine,
                     later: "aht reads the level again when the shift starts.",
                     leaving: { "the \($0.map { $0 + " " } ?? "")session here" })
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
    let st = RegisterEventHotKey(UInt32(code), UInt32(mods), id, GetApplicationEventTarget(), 0, &HOTKEY_REF)
    if st != noErr {            // another app has it, most often
        AppLog.shared.note("the search shortcut \(spec) was not registered (error \(st))", level: "warn")
    }
}

struct MachinesView: View {
    @EnvironmentObject var m: AppModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    Text("The machines a project can be handed over to, and kept in sync with. "
                         + "Watch one to hear when a session there waits for you.")
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
                                if !mc.system.isEmpty {
                                    Text(systemLabel(mc.system)).foregroundColor(.secondary)
                                }
                                if mc.name == m.machine {
                                    Text("projects go here").font(.caption)
                                        .padding(.horizontal, 6).padding(.vertical, 2)
                                        .background(Color.accentColor.opacity(0.18))
                                        .cornerRadius(4)
                                }
                                Spacer()
                                // a PC that cannot be asked is never handed a project
                                if mc.name != m.machine && mc.asks {
                                    Button("Use for Handover") { m.use(mc) }
                                }
                                if mc.asks {
                                    Menu("Sync") {
                                        Button("Keep All Projects in Sync…") { m.syncAll(mc, on: true) }
                                        Button("Stop Keeping All in Sync…") { m.syncAll(mc, on: false) }
                                            .disabled(m.mirroredCount == 0)
                                    }
                                    .fixedSize()
                                }
                                let held = pausedWith(m.projects, mc.name)
                                if !held.isEmpty {
                                    // syncs with this machine that wait for an answer
                                    Button("\(held.count) paused") { m.showPaused(held) }
                                        .buttonStyle(.borderless).foregroundColor(.orange)
                                        .help(pausedHelp(held, mc.name))
                                }
                                // a PC brings nothing here from its side: Bring Here starts on the PC
                                if mc.asks && mc.system != "Windows" {
                                    Button("Bring Here…") { m.openBring(from: mc.name) }
                                        .disabled(!m.canReach)
                                        .help("Bring a project aht keeps on \(mc.name) here, with its history")
                                }
                                Button("Check") { m.check(mc) }
                                Button("Remove…") { m.remove(mc) }
                            }
                            .disabled(m.working != nil)
                            HStack(spacing: 10) {
                                Toggle("Watch", isOn: Binding(get: { mc.watch }, set: { m.watch(mc, $0) }))
                                    .toggleStyle(.switch).controlSize(.small)
                                    .disabled(!m.canReach || !mc.asks)
                                    .help(mc.cannotAsk ?? "aht asks \(mc.name) \(paceText(WATCH_EVERY)) and tells you when a "
                                          + "session there waits for you or is done")
                                if let b = m.heard(mc.name) {
                                    // a core without `last_heard`: it answered when the board was read
                                    let t = b.lastHeard ?? (b.reachable ? m.boardAt?.timeIntervalSince1970 : nil)
                                    Text(heardText(t, stale: b.stale)).font(.caption)
                                        .foregroundColor(b.stale ? .orange : .secondary)
                                        .help(b.error ?? "")
                                }
                            }
                            if let pm = m.pathsFor(mc) { PathMapLine(mc: mc, map: pm) }
                            // a PC that cannot be asked: the core's reason, and how to set one up
                            if let why = mc.cannotAsk, m.checkError[mc.name] == nil {
                                HStack(spacing: 6) {
                                    Text(why).font(.callout).foregroundColor(.orange)
                                        .fixedSize(horizontal: false, vertical: true)
                                    HelpButton(PC_SETUP_TOPIC)
                                }
                            }
                            if let e = m.checkError[mc.name] {
                                HStack(spacing: 6) {
                                    Text("✗ " + e).foregroundColor(.red)
                                    if mc.system == "Windows" { HelpButton(PC_SETUP_TOPIC) }
                                }
                            }
                            ForEach(checkGroups(m.checks[mc.name] ?? []), id: \.title) { g in
                                if !g.title.isEmpty {
                                    Text(g.title).font(.caption).fontWeight(.semibold)
                                        .foregroundColor(.secondary).padding(.top, 2)
                                }
                                ForEach(g.rows) { c in CheckRow(c: c) }
                            }
                            if let t = pcCheckNote(mc, m.checks[mc.name] ?? []) {
                                Text(t).font(.caption).foregroundColor(.secondary)
                            }
                            // `transfer`: what copies files to and from it, unless a row says so
                            if let t = m.checkedMover(mc.name),
                               !(m.checks[mc.name] ?? []).contains(where: saysTransfer) {
                                Text("Copies files with \(moverLabel(t)). Settings → Handover chooses which.")
                                    .font(.caption).foregroundColor(.secondary)
                            }
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
        .onAppear {
            m.discover()
            m.loadPaths()
            // "last heard" comes with the sessions board: read it when it is old
            if !m.machines.isEmpty && (m.boardAt.map { -$0.timeIntervalSinceNow > 120 } ?? true) {
                m.refreshBoard()
            }
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

// ---- Recent problems and the problem report ---------------------------------------
// `aht logs --errors [--everywhere] --json` → {hours, entries: [{t, at, level,
// text, machine, here}] oldest first, machines: [{machine, here, reachable,
// lines, error}]}; `aht report-problem --out FILE [--everywhere] --json` →
// {path, bytes, machines: (the same rows), errors: how many warnings and
// errors it holds}.

/// The guide's section on what to do when something goes wrong.
let TROUBLE = "When something"

struct ProblemRow: Identifiable {
    let id: Int
    let t: Date?
    let machine: String?        // nil: this Mac
    let level: String           // "error" or "warn"
    let text: String            // an UNCAUGHT error: its traceback on the lines after the first
}

/// A machine that did not answer, or answered with an error.
struct MissedMachine: Identifiable {
    var id: String { machine }
    let machine: String
    let why: String
    let reachable: Bool
    var line: String {
        why.hasPrefix(machine + " ") ? why
            : reachable ? "\(machine): \(why)" : "\(machine) did not answer: \(why)"
    }
}

/// The machines that did not answer, or answered with an error (never this Mac).
func missedMachines(_ rows: Any?) -> [MissedMachine] {
    ((rows as? [[String: Any]]) ?? []).compactMap { m in
        guard m["here"] as? Bool != true, let name = m["machine"] as? String else { return nil }
        let reachable = m["reachable"] as? Bool ?? true
        let why = m["error"] as? String
        guard !reachable || !(why ?? "").isEmpty else { return nil }
        return MissedMachine(machine: name, why: why ?? "it did not answer", reachable: reachable)
    }
}

/// The recent problems, newest first, and the machines that did not answer.
/// Lines as the log writes them ("[2026-10-28 14:10:00] [WARN ] …") from an
/// older core that answers with `lines`.
func parseProblems(_ d: [String: Any]) -> (rows: [ProblemRow], missed: [MissedMachine]) {
    var rows: [ProblemRow] = []
    let f = DateFormatter()
    f.locale = Locale(identifier: "en_US_POSIX")
    f.dateFormat = "yyyy-MM-dd HH:mm:ss"
    for (i, x) in (((d["entries"] as? [Any]) ?? (d["lines"] as? [Any])) ?? []).enumerated() {
        if let e = x as? [String: Any] {
            let here = e["here"] as? Bool == true || e["machine"] == nil || e["machine"] is NSNull
            rows.append(ProblemRow(id: i, t: moment(e["t"]) ?? moment(e["at"]),
                                   machine: here ? nil : e["machine"] as? String,
                                   level: e["level"] as? String == "error" ? "error" : "warn",
                                   text: e["text"] as? String ?? ""))
        } else if let line = x as? String {
            var t: Date?, level = "warn", text = line
            if let r = line.range(of: #"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\] \[(\w+)\s*\] ?"#,
                                  options: .regularExpression) {
                t = f.date(from: String(line.dropFirst().prefix(19)))
                level = line[r].contains("[ERROR") ? "error" : "warn"
                text = String(line[r.upperBound...])
            }
            rows.append(ProblemRow(id: i, t: t, machine: nil, level: level, text: text))
        }
    }
    rows.sort { ($0.t ?? .distantPast) > ($1.t ?? .distantPast) }
    return (rows, missedMachines(d["machines"]))
}

struct ProblemReport {
    let path: String
    let bytes: Int64
    let names: [String]         // the machines that answered, this Mac first
    let missed: [MissedMachine]
    let problems: Int?          // how many warnings and errors it holds
}

func parseReport(_ d: [String: Any]) -> ProblemReport? {
    guard let path = d["path"] as? String, !path.isEmpty else { return nil }
    let rows = (d["machines"] as? [[String: Any]]) ?? []
    let names = rows.filter { $0["reachable"] as? Bool != false }
        .map { $0["here"] as? Bool == true ? "this Mac" : ($0["machine"] as? String ?? "?") }
    return ProblemReport(path: path, bytes: (d["bytes"] as? NSNumber)?.int64Value ?? 0, names: names,
                         missed: missedMachines(rows), problems: (d["errors"] as? NSNumber)?.intValue)
}

/// Where a report goes: a readable .txt among aht's reports (the core keeps
/// the newest few there; with --json and no --out its file would be JSON).
/// The folder is made, for this user only, if it is not there yet.
func problemReportFile(_ ahtHome: String, at: Date = Date()) -> String {
    let dir = ahtHome + "/reports"
    if !FileManager.default.fileExists(atPath: dir) {
        do {
            try FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true,
                                                    attributes: [.posixPermissions: 0o700])
        } catch {
            AppLog.shared.note("the reports folder could not be made: \(error.localizedDescription)")
        }
    }
    let f = DateFormatter()
    f.locale = Locale(identifier: "en_US_POSIX")
    f.dateFormat = "yyyyMMdd-HHmmss"
    return dir + "/problem-\(f.string(from: at)).txt"
}

func problemReportArgs(everywhere: Bool, out: String) -> [String] {
    ["report-problem", "--out", out] + (everywhere ? ["--everywhere"] : []) + ["--json"]
}

let REPORT_INTRO = "aht writes one file that shows what went wrong, for you to read and hand to "
    + "whoever helps you. Nothing is sent anywhere.\n\nIt holds aht's version, this Mac's macOS "
    + "and Python, the version of each agent, your settings (secret values, the phone topic, host "
    + "and user names replaced by the machine names you gave aht), how many projects aht tracks "
    + "(not where they are), and the recent warnings and errors."

/// What the saved report's alert says.
func reportSavedText(_ r: ProblemReport, everywhere: Bool) -> String {
    var lines = [(r.path as NSString).abbreviatingWithTildeInPath + "  (" + byteText(NSNumber(value: r.bytes)) + ")"]
    if let n = r.problems {
        lines.append(n == 0 ? "No recent warnings or errors." : n == 1 ? "1 warning or error."
                     : "\(n) warnings or errors.")
    }
    if everywhere || r.names.contains(where: { $0 != "this Mac" }) {
        lines.append("From " + r.names.joined(separator: ", ") + ".")
    }
    lines += r.missed.map { $0.line }
    lines.append("Nothing was sent anywhere. Read it before you hand it on.")
    return lines.joined(separator: "\n")
}

struct ProblemsView: Identifiable {
    let id = UUID()
    let everywhere: Bool
    var loading = true
    var rows: [ProblemRow] = []
    var missed: [MissedMachine] = []
    var error: String?
}

struct ProblemsSheet: View {
    @EnvironmentObject var m: AppModel

    var body: some View {
        let v = m.problems ?? ProblemsView(everywhere: false, loading: false)
        VStack(alignment: .leading, spacing: 10) {
            headed("Recent problems", TROUBLE)
            if v.loading {
                HStack {
                    ProgressView().controlSize(.small)
                    Text(v.everywhere ? "Asking every machine…" : "Reading the log…")
                        .foregroundColor(.secondary)
                }
            } else if let e = v.error {
                Text(e).foregroundColor(.orange).textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                Text(v.everywhere ? "The recent warnings and errors of every machine, newest first. "
                     + "aht replaced secrets, host and user names in them."
                     : "The recent warnings and errors of aht on this Mac, newest first.")
                    .font(.caption).foregroundColor(.secondary)
                ForEach(v.missed) { Text($0.line).font(.callout).foregroundColor(.orange) }
                if v.rows.isEmpty {
                    Text("No recent warnings or errors \(v.everywhere ? "on any machine" : "on this Mac").")
                        .foregroundColor(.green)
                } else {
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 0) {
                            ForEach(v.rows) { r in
                                ProblemRowView(r: r, everywhere: v.everywhere)
                                Divider()
                            }
                        }
                        .padding(.trailing, 12)
                    }
                }
            }
            Spacer(minLength: 0)
            HStack {
                Button("Open Log") { m.openLog() }
                Button("Make a Problem Report…") {
                    m.problems = nil
                    DispatchQueue.main.async { m.makeProblemReport() }
                }
                Spacer()
                Button("Look Again") { m.showProblems() }.disabled(v.loading)
                Button("Close") { m.problems = nil }.keyboardShortcut(.cancelAction)
            }
        }
        .padding(20).frame(width: 780, height: 540)
    }
}

struct ProblemRowView: View {
    let r: ProblemRow
    let everywhere: Bool
    @State private var open = false

    var body: some View {
        let lines = r.text.components(separatedBy: "\n")
        VStack(alignment: .leading, spacing: 2) {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Text(clock(r.t)).monospacedDigit().foregroundColor(.secondary)
                    .frame(width: 96, alignment: .leading)
                if everywhere {
                    Text(r.machine ?? "this Mac").lineLimit(1).frame(width: 110, alignment: .leading)
                }
                Text(r.level == "error" ? "error" : "warning").font(.caption)
                    .foregroundColor(r.level == "error" ? .red : .orange)
                    .frame(width: 56, alignment: .leading)
                Text(lines.first ?? "").textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: 0)
            }
            if lines.count > 1 {
                DisclosureGroup("Traceback", isExpanded: $open) {
                    Text(lines.dropFirst().joined(separator: "\n"))
                        .font(.system(.caption, design: .monospaced)).textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .font(.caption)
                .padding(.leading, everywhere ? 292 : 172)
            }
        }
        .padding(.vertical, 5)
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

/// Settings ▸ Permissions: the level the next agent starts in (`agent_permissions`:
/// follow, a fixed level, or at most one), and Codex's never-ask flags
/// (`agent_permission_flags`.codex.never: the built-in full bypass, or
/// never asking inside Codex's sandbox).
struct PermissionsSettings: View {
    @EnvironmentObject var m: AppModel

    var body: some View {
        let now = m.config["agent_permissions"] as? String ?? "follow"
        var levels = PERM_CHOICES
        if !levels.contains(where: { $0.0 == now }) { levels.append((now, now)) }
        let cx = codexNever(m.config)
        let own = (((m.config["agent_permission_flags"] as? [String: Any])?["codex"] as? [String: Any])?["never"] as? [Any])?
            .map { shellWord("\($0)") }.joined(separator: " ") ?? ""
        return VStack(alignment: .leading, spacing: 8) {
            Text("The agent that continues the work starts in its own equivalent of the session's "
                 + "permission level; aht never raises it by itself.")
                .font(.caption).foregroundColor(.secondary).fixedSize(horizontal: false, vertical: true)
            HStack {
                Text("The next agent starts in").frame(width: 170, alignment: .leading)
                Picker("", selection: Binding(get: { now }, set: { m.setChecked("agent_permissions", $0, $0) })) {
                    ForEach(levels, id: \.0) { Text($0.1).tag($0.0) }
                }
                .labelsHidden().fixedSize()
                Spacer()
            }
            if now == "never" {
                Label("Every agent aht starts or continues then never asks, also after a session that asked.",
                      systemImage: "exclamationmark.triangle.fill")
                    .font(.caption).foregroundColor(.orange).fixedSize(horizontal: false, vertical: true)
            }
            HStack {
                Text("Codex's never-ask mode").frame(width: 170, alignment: .leading)
                Picker("", selection: Binding(get: { cx }, set: { v in
                    if v != "own" { m.setJSON("agent_permission_flags", withCodexNever(m.config, sandbox: v == "sandbox")) }
                })) {
                    Text("Full bypass (default)").tag("full")
                    Text("Never ask, keep Codex's sandbox").tag("sandbox")
                    if cx == "own" { Text("Your own flags: " + own).tag("own") }
                }
                .labelsHidden().fixedSize()
                Spacer()
            }
            Text("Full bypass: --dangerously-bypass-approvals-and-sandbox, the closest to Claude Code's "
                 + "skip-permissions. Keeping the sandbox: " + CODEX_SANDBOXED.joined(separator: " ")
                 + ": Codex never asks, but writes only inside the project.")
                .font(.caption).foregroundColor(.secondary).fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
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
    @State private var phone = ""

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
                            TextField("imessage:+43… or ntfy:my-topic", text: $phone)
                                .textFieldStyle(.roundedBorder).frame(width: 260)
                            // the core may refuse it (an ntfy server that is not
                            // https, say): its words, and the saved address back
                            Button("Save") {
                                let v = phone.trimmingCharacters(in: .whitespaces)
                                let saved = m.text("notify_phone", "")
                                m.setChecked("notify_phone", v, v) { ok in if !ok { phone = saved } }
                            }
                            Button("Send a Test") { m.testNotice() }
                        }
                        Text(NOTICES_PACE + " iMessage goes to your own number or Apple ID; ntfy "
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
                        Toggle("Copy the folder when a session starts, to undo a whole session",
                               isOn: Binding(get: { m.checkpointsOn }, set: { m.setCheckpoints($0) }))
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
                             + "per project are kept. Time Machine leaves them out. On Windows and "
                             + "Linux it makes a real copy of the folder.")
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
                                Text("Mistral Vibe").tag("vibe")
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
                GroupBox(label: HStack(spacing: 6) { Text("Permissions"); HelpButton("The permission level follows the work") }) {
                    PermissionsSettings().padding(6).frame(maxWidth: .infinity, alignment: .leading)
                }
                GroupBox(label: HStack(spacing: 6) { Text("Backups on another machine"); HelpButton("Backups") }) {
                    VStack(alignment: .leading, spacing: 8) {
                        HStack {
                            Picker("Keep a copy of the history backups on", selection: Binding(
                                get: { m.text("offsite_backup", "") },
                                set: { m.set("offsite_backup", $0) })) {
                                Text("no other machine").tag("")
                                ForEach(pickerMachines(m.machines, keeping: m.text("offsite_backup", ""))) {
                                    Text(pickerLabel($0)).tag($0.name)
                                }
                            }
                            .frame(maxWidth: 460)
                            Spacer()
                            Button("Copy Now") { m.copyBackupsNow() }
                                .disabled(m.text("offsite_backup", "").isEmpty)
                            Button("Fetch Backups From…") { m.openFetchBackups() }
                                .disabled(m.text("offsite_backup", "").isEmpty || !m.canReach
                                          || m.working != nil)
                        }
                        if let why = m.machines.first(where: { $0.name == m.text("offsite_backup", "") })?.cannotAsk {
                            Text(why).font(.caption).foregroundColor(.orange)
                                .fixedSize(horizontal: false, vertical: true)
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
                        HStack {
                            Text("Copies files with")
                            Picker("", selection: Binding(get: { m.transferMode },
                                                          set: { m.set("handover_transfer", $0) })) {
                                ForEach(TRANSFER_CHOICES, id: \.0) { Text($0.1).tag($0.0) }
                            }
                            .labelsHidden().fixedSize()
                            Spacer()
                            if !m.machines.isEmpty {
                                Button("Ask the Machines") { m.askMovers() }
                                    .disabled(!m.canReach || m.working != nil)
                                    .help("Ask each machine whether it has rsync")
                            }
                        }
                        if !m.machines.isEmpty {
                            Text(m.moversLine).font(.caption).foregroundColor(.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        Text("rsync sends only the changed parts of a big file. aht's own copy "
                             + "needs nothing installed and also copies to and from Windows.")
                            .font(.caption).foregroundColor(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
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
                                if !b.relinks {
                                    Text("only read").font(.caption).foregroundColor(.secondary)
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
                            Button("Recent Problems…") { m.showProblems() }
                            Button("Open Log") { m.openLog() }
                            Button("Open Data Folder") { m.openData() }
                            Button("Edit Config File") { m.editConfig() }
                            Spacer()
                        }
                        HStack(spacing: 10) {
                            Button("Make a Problem Report…") { m.makeProblemReport() }
                            HelpButton(TROUBLE)
                            if m.recentProblems > 0 {
                                Text(m.recentProblems == 1
                                     ? "1 warning or error in aht's log in the last day."
                                     : "\(m.recentProblems) warnings or errors in aht's log in the last day.")
                                    .font(.callout).foregroundColor(.secondary)
                            }
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
            phone = m.text("notify_phone", "")
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
        do {
            try d.write(to: URL(fileURLWithPath: CORNER_STATE), options: .atomic)
        } catch {
            AppLog.shared.note("the session corner's marks were not saved: \(error.localizedDescription)",
                               level: "warn")
        }
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
        // an Objective-C exception nobody caught ends the app: its name and
        // reason go to aht's log first (at once: there is no later)
        NSSetUncaughtExceptionHandler { e in
            let msg = "uncaught \(e.name.rawValue): \(e.reason ?? "")"
            _ = shWithStderr(PY, [ahtScript(), "_log", "--level", "error", "--source", "mac-app", "--",
                                  String(msg.prefix(500))])
        }
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
            if let e = q["everywhere"] { model.searchEverywhere = e == "1" }
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
               let k = ["waiting": "waiting", "finished": "done", "went-quiet": "done", "limit": "limit"][
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
    /// handover that was cut off, a note another machine left).
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
            } else if ["limit", "handover", "incoming", "sync-paused"].contains(kind),
                      let p = info["project"] as? String {
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

    @objc func openProblems() {
        openWindow()
        model.showProblems()
    }

    @objc func makeProblemReport() {
        model.makeProblemReport()
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
        help.addItem(.separator())
        for (title, sel) in [("Recent Problems…", #selector(openProblems)),
                             ("Make a Problem Report…", #selector(makeProblemReport))] {
            let i = NSMenuItem(title: title, action: sel, keyEquivalent: "")
            i.target = self
            help.addItem(i)
        }
        helpItem.submenu = help
        bar.addItem(helpItem)
        NSApp.helpMenu = help
        return bar
    }
}

// selftest: everything that can run headless (used by CI/dev boxes)
if CommandLine.arguments.contains("--selftest") {
    // the app's own error lines stay here: a selftest writes nothing to aht's log
    var selfLogged: [[String]] = []
    AppLog.shared.send = { selfLogged.append($0) }
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
    // Settings' history folders: agy and Vibe last, as only read
    let bj = sh(PY, [core, "backends", "--json"]).out
    let brows = backendRows((try? JSONSerialization.jsonObject(with: Data(bj.utf8))) as? [String: Any] ?? [:])
    let readOK = brows.count > 2 && brows.suffix(2).map { $0.name } == ["agy", "vibe"]
        && brows.suffix(2).allSatisfy { !$0.relinks } && brows.dropLast(2).allSatisfy { $0.relinks }
    print("ONLY-READ AGENTS IN SETTINGS \(readOK ? "OK" : "FAIL \(brows.map { "\($0.name):\($0.relinks)" })")")
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
    // a fetch that ends with 1 over some files: what came counts, each file that
    // did not is named; none came: nothing was fetched
    let fetchBad = ["name": "p1/20261019-0900.zip", "error": "in use or not allowed"]
    let fetchPartial: [String: Any] = ["machine": "box", "files": 2, "bytes": 4096, "pulled": true,
                                  "renamed": [String](), "problems": [fetchBad]]
    let fetchPartly = fetchedText(fetchAnswered(false, fetchPartial) ? fetchPartial : nil, listed[1], said: "")
    let fetchNone: [String: Any] = ["machine": "box", "files": 0, "bytes": 0, "pulled": true,
                                   "renamed": [String](), "problems": [fetchBad, fetchBad]]
    let fetchNoneText = fetchedText(fetchAnswered(false, fetchNone) ? fetchNone : nil, listed[1], said: "")
    let fetchPartialOK = fetchPartly.hasPrefix("Fetched 2 backup(s)")
        && fetchPartly.hasSuffix("\n\nThis file could not come:\n• p1/20261019-0900.zip — in use or not allowed")
        && fetchNoneText.hasPrefix("Nothing was fetched from old-mac's folder.\n\nThese 2 files could not come:\n• p1/")
        && !fetchAnswered(false, ["machine": "box", "files": 1, "problems": [Any]()])
        && !fetchAnswered(false, nil) && fetchAnswered(true, nil)
    print("BACKUPS FROM ANOTHER MACHINE \(offsiteOK ? "OK" : "FAIL")")
    print("SOME BACKUPS NOT FETCHED \(fetchPartialOK ? "OK" : "FAIL — \(fetchPartly) / \(fetchNoneText)")")
    // agents on one machine: agy in the menu (`status --json`'s `agent_clis`),
    // an open relay (`projects --json`'s `relay`) as the line under the
    // project with Hand Back first, the switch dialog from `switch --json`
    let clis = switchAgents(["agent_clis": ["claude": "/x/claude", "codex": NSNull(), "agy": "/x/agy",
                                            "kimi": "/x/kimi", "vibe": "/x/vibe"]])
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
    let relayOK = clis == ["claude", "kimi", "agy", "vibe"]
        && menu.map { $0.title } == ["Hand Back to Claude Code (its own session)…",
                                     "Continue in Claude Code…", "Continue in Kimi Code…",
                                     "Continue in Antigravity…", "Continue in Mistral Vibe…"]
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
        // the status: agy and vibe are among the agents, and the menu has each one installed
        let st = sample("status.json")
        let named = (st["agent_clis"] as? [String: Any]) ?? [:]
        let installed = switchAgents(st)
        if named["agy"] == nil || named["vibe"] == nil
            || installed != SWITCH_AGENTS.filter({ named[$0] is String })
            || (named["agy"] is String && !switchItems(Project([:]), installed)
                .contains { $0.title == "Continue in Antigravity…" })
            || (named["vibe"] is String && !switchItems(Project([:]), installed)
                .contains { $0.title == "Continue in Mistral Vibe…" }) {
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
    // watch and search every machine: the Watch switch and "last heard" in
    // Machines, a silent machine's last rows "as of" in Sessions, Search's
    // other machines; made-up rows in the shape of the core's JSON
    let now = Date().timeIntervalSince1970
    let setUp = machinesFrom(["box": ["ssh": "me@box", "watch": true, "system": "Linux"],
                            "studio": ["ssh": "me@studio", "system": NSNull()], "pc": "odd"])
    let watchOK = setUp.map { $0.name } == ["box", "pc", "studio"] && setUp[0].watch && !setUp[2].watch
        && setUp[0].system == "Linux" && setUp[2].system == "" && systemLabel("Darwin") == "macOS"
        && watchProblem(["remote": "box", "watch": true, "applied": true], "box", on: true) == nil
        && watchProblem(["remote": "box", "watch": false, "applied": true], "box", on: false) == nil
        && watchProblem(["remote": "box", "watch": true, "applied": false], "box", on: true)
            == "box is not watched."
        && watchProblem(["remote": "box", "watch": true], "box", on: false) == "box is still watched."
        && watchProblem(nil, "box", on: true, said: "unknown machine 'box'\n") == "unknown machine 'box'"
        && watchProblem([:], "box", on: true).map { $0.hasPrefix("aht gave no answer") } == true
        && heardText(nil, stale: false) == "not heard from yet"
        && heardText(now - 5, stale: false) == "last heard just now"
        && heardText(now - 1500, stale: true) == "not heard since " + clock(NSNumber(value: now - 1500))
    let grouped = checkGroups(checkRows(["machines": [["remote": "box", "checks": [
        ["check": "reachable", "ok": true, "detail": "box (Linux)", "needed": true, "group": "ask"],
        ["check": "rsync there", "ok": false, "detail": "missing", "needed": true,
         "fix": "sudo apt install rsync", "group": "handover"],
        ["check": "keeps box awake while an agent works", "ok": true, "detail": "systemd-inhibit",
         "needed": false, "group": "handover"],
        ["check": "python3 there", "ok": true, "detail": "3.12", "needed": true, "group": "ask"]]]]]).rows)
    let flat = checkGroups(checkRows(["machines": [["checks": [["check": "reachable", "ok": true]]]]]).rows)
    let failed = checkRows(["machines": [["remote": "box", "error": "ssh: no route", "checks": []]]])
    let groupsOK = grouped.map { $0.title } == ["For asking", "For handing over"]
        && grouped[0].rows.map { $0.name } == ["reachable", "python3 there"]
        && grouped[1].rows.count == 2 && grouped[1].rows[0].fix == "sudo apt install rsync"
        && flat.map { $0.title } == [""] && failed.error == "ssh: no route" && failed.rows.isEmpty
        && checkRows([:]).error == "aht gave no answer"
    print("WATCH AND LAST HEARD \(watchOK && groupsOK ? "OK" : "FAIL — \(setUp) / \(grouped.map { $0.title })")")
    let row = { (p: String, st: String) -> [String: Any] in
        ["agent": "claude", "project": "/home/me/code/" + p, "status": st, "since": now - 600]
    }
    let boards = boardMachines(["machines": [
        ["machine": "mac", "local": true, "reachable": true, "sessions": [row("a", "working")]],
        ["machine": "box", "local": false, "reachable": true, "last_heard": now, "stale": false,
         "sessions": [row("b", "working"), row("c", "waiting for you")], "last_sessions": NSNull()],
        ["machine": "studio", "local": false, "reachable": false, "error": "timed out",
         "last_heard": now - 1500, "stale": true, "sessions": [],
         "last_sessions": [row("d", "working"), row("e", "waiting for you")]],
        ["machine": "laptop", "local": false, "reachable": false, "last_heard": now - 200,
         "stale": false, "sessions": [], "last_sessions": [row("f", "idle")]],
        ["machine": "pi", "local": false, "reachable": false, "last_heard": NSNull(), "stale": true,
         "sessions": []],
        ["machine": "old", "local": false, "reachable": false, "sessions": []]]])   // an older core
    let (here, box, studio, laptop, pi, old) = (boards[0], boards[1], boards[2], boards[3], boards[4], boards[5])
    let staleOK = boards.count == 6 && here.silentNote.isEmpty && !here.showsOld
        && box.silentNote.isEmpty && !box.showsOld && box.rows.first?.status == "waiting for you"
        && box.lastHeard == now && !box.stale
        && studio.showsOld && studio.stale && studio.lastRows.map { $0.name } == ["e", "d"]
        && studio.silentNote == "Not answering since \(clock(NSNumber(value: now - 1500))) — asleep, "
            + "switched off or offline?"
        && studio.asOf == "as of " + clock(NSNumber(value: now - 1500))
        && laptop.showsOld && laptop.silentNote.hasPrefix("Not reachable right now")
        && !pi.showsOld && pi.silentNote.hasPrefix("Not reachable right now") && pi.lastHeard == nil
        && !old.showsOld && old.silentNote.hasPrefix("Not reachable right now") && !old.stale
    print("SESSIONS AS OF \(staleOK ? "OK" : "FAIL — \(boards.map { ($0.name, $0.silentNote, $0.showsOld) })")")
    let hit = { (machine: Any, title: String) -> [String: Any] in
        ["machine": machine, "agent": "claude", "session": "s-" + title, "project": "/x/api",
         "title": title, "live": true, "updated": now - 60,
         "hits": [["role": "user", "snippet": "the \u{02}login\u{03} redirect"]]]
    }
    let found: [String: Any] = ["query": "login", "results": [hit("box", "there"), hit(NSNull(), "here"),
                                                               hit("studio", "studio one")],
                                "machines": [
        ["machine": "box", "reachable": true, "indexed": true, "index_at": now - 30, "results": 1,
         "error": NSNull()],
        ["machine": "studio", "reachable": true, "indexed": true, "index_at": now, "results": 1],
        ["machine": "laptop", "reachable": false, "indexed": NSNull(), "index_at": NSNull(),
         "results": 0, "error": "ssh: connect to host laptop port 22: Operation timed out\n"],
        ["machine": "pi", "reachable": true, "indexed": false, "index_at": NSNull(), "results": 0,
         "error": NSNull()]]]
    let got = searchHits(found)
    let missed = searchMissed(found)
    let searchOK = got.map { $0.title } == ["here", "there", "studio one"]
        && got.map { $0.machine } == [nil, "box", "studio"] && got[1].snippets.count == 1
        && missed == ["Not searched on laptop: it did not answer (ssh: connect to host laptop port 22: "
                        + "Operation timed out)",
                      "Not searched on pi: no search index (aht is not installed there)"]
        && searchAsked(found) == ["box", "studio"]
        && searchHits(["results": [hit(NSNull(), "plain")]]).first?.machine == nil
        && searchMissed(["results": []]).isEmpty
        && nothingFound("x", everywhere: nil) == "Nothing found for “x”."
        && nothingFound("x", everywhere: ["box"]) == "Nothing found for “x”, here or on box."
        && nothingFound("x", everywhere: ["box", "pi", "studio"])
            == "Nothing found for “x”, here or on box, pi or studio."
    print("SEARCH EVERYWHERE \(searchOK ? "OK" : "FAIL — \(got.map { $0.title }) / \(missed)")")
    // … and the core's phase-3 samples: AHT_FIXTURES_PHASE3
    var phase3OK = true
    let dir3 = ProcessInfo.processInfo.environment["AHT_FIXTURES_PHASE3"] ?? ""
    if !dir3.isEmpty && FileManager.default.fileExists(atPath: dir3) {
        var miss: [String] = []
        func sample(_ n: String) -> [String: Any] {
            let f = URL(fileURLWithPath: dir3).appendingPathComponent(n)
            guard let data = try? Data(contentsOf: f) else { miss.append(n + " (missing)"); return [:] }
            let d = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            if d == nil { miss.append(n + " (not JSON)") }
            return d ?? [:]
        }
        // status: whether other machines can be asked, next to whether handover works
        let ho = sample("status.json")["handover"] as? [String: Any] ?? [:]
        if !(ho["can_reach"] is Bool) || !(ho["supported"] is Bool) { miss.append("status.json") }
        // remote list: each machine says whether it is watched, and its system
        let rl = sample("remote_list.json")["remotes"] as? [String: Any] ?? [:]
        let ms = machinesFrom(rl)
        if rl.isEmpty || ms.count != rl.count || ms.contains(where: { mc in
            let raw = rl[mc.name] as? [String: Any] ?? [:]
            return !(raw["watch"] is Bool) || mc.watch != raw["watch"] as? Bool
                || raw["system"] == nil || mc.system != (raw["system"] as? String ?? "")
        }) {
            miss.append("remote_list.json")
        }
        // remote watch: a done change reads as done, a dry run does not
        let rw = sample("remote_watch.json")
        if let name = rw["remote"] as? String, let on = rw["watch"] as? Bool, let applied = rw["applied"] as? Bool {
            if (watchProblem(rw, name, on: on) == nil) != applied { miss.append("remote_watch.json") }
        } else {
            miss.append("remote_watch.json")
        }
        // remote check: every row in a group, and the keep-awake row
        let rc = sample("remote_check.json")
        let raw = (((rc["machines"] as? [[String: Any]]) ?? []).first?["checks"] as? [[String: Any]]) ?? []
        let (rows, _) = checkRows(rc)
        let groups = checkGroups(rows)
        if raw.isEmpty || rows.count != raw.count
            || raw.contains(where: { !["ask", "handover"].contains($0["group"] as? String ?? "") })
            || zip(rows, raw).contains(where: { $0.group != $1["group"] as? String })
            || !raw.contains(where: { ($0["check"] as? String ?? "").lowercased().contains("awake") })
            || groups.map({ $0.rows.count }).reduce(0, +) != rows.count
            || (rows.contains { $0.group == "ask" } && groups.first?.title != "For asking") {
            miss.append("remote_check.json")
        }
        // board: when each machine was last heard, stale ones' last rows "as of"
        let bd = sample("board.json")
        let rawBoards = (bd["machines"] as? [[String: Any]]) ?? []
        let parsed = boardMachines(bd)
        let others = zip(parsed, rawBoards).filter { !$0.0.local }
        if rawBoards.isEmpty || others.isEmpty || others.contains(where: { b, r in
            !(r["stale"] is Bool) || b.stale != r["stale"] as? Bool
                || (r["last_heard"] == nil) || b.lastHeard != (r["last_heard"] as? NSNumber)?.doubleValue
                || (r["last_sessions"] as? [Any]).map { $0.count != b.lastRows.count } ?? false
                || ((b.stale || !b.reachable) && b.silentNote.isEmpty)
                || (b.showsOld && !b.asOf.hasPrefix("as of "))
        }) {
            miss.append("board.json")
        }
        // search everywhere: hits with their machine, this Mac's first; a line
        // for each machine that could not be searched
        let se = sample("search_everywhere.json")
        let rawHits = (se["results"] as? [[String: Any]]) ?? []
        let seHits = searchHits(se)
        let rawMachines = (se["machines"] as? [[String: Any]]) ?? []
        let lines = searchMissed(se), asked = searchAsked(se)
        let named = rawMachines.compactMap { $0["machine"] as? String }
        let firstThere = seHits.firstIndex { $0.machine != nil } ?? seHits.count
        if !(se["query"] is String) || rawMachines.isEmpty || seHits.count != rawHits.count
            || rawHits.contains(where: { $0["machine"] == nil })        // null for here, never missing
            || seHits[firstThere...].contains(where: { $0.machine == nil })
            || Set(seHits.compactMap { $0.machine }) != Set(rawHits.compactMap { $0["machine"] as? String })
            || rawMachines.contains(where: { m in
                ["machine", "reachable", "indexed", "index_at", "results", "error"].contains { m[$0] == nil } })
            || named.count != lines.count + asked.count
            || !zip(rawMachines.filter { missedLine($0) != nil }, lines).allSatisfy({
                $1.contains($0["machine"] as? String ?? "\u{0}") }) {
            miss.append("search_everywhere.json")
        }
        miss = miss.filter { !miss.contains($0 + " (missing)") && !miss.contains($0 + " (not JSON)") }
        phase3OK = miss.isEmpty
        print("PHASE 3 SAMPLES \(phase3OK ? "OK" : "FAIL \(miss)") — \(dir3)")
    } else {
        print("PHASE 3 SAMPLES not checked (" + (dir3.isEmpty ? "AHT_FIXTURES_PHASE3 names no folder"
                                                       : "no samples in \(dir3) yet") + ")")
    }
    // Pick Up and Leave a Note: the sheet's parts from `pickup --json` and
    // `leave-note --json`, the Machines menu, the banner when a note arrived,
    // Continue Here… on another machine's hit; made-up rows in the core's shape
    let dryPick: [String: Any] = [
        "command": "pickup", "applied": false, "blockers": [], "warnings": [], "mode": "new",
        "match": ["path": "/home/me/code/api", "how": "id", "candidates": []],
        "source": ["machine": "box", "agent": "codex", "session": "019a", "title": "fix the login redirect"],
        "sessions": [["agent": "codex", "id": "019a", "title": "fix the login redirect", "updated": now - 300,
                      "state": "working"],
                     ["agent": "claude", "id": "0f3a", "title": NSNull(), "updated": now - 9000, "open": false]],
        "git": ["here": ["branch": "main", "ahead": 0, "dirty": 0],
                "there": ["branch": "fix-login", "ahead": 2, "dirty": 6],
                "warning": "On box: branch fix-login, 2 commits not pushed, 6 files not committed. "
                    + "Commit and push there, then pull here."],
        "brief": "# Picked up from box\n\n## Where things stood\n\nThe redirect keeps the page.",
        "relay": NSNull(), "opened": NSNull(), "command_line": NSNull()]
    let dryBlocked: [String: Any] = ["applied": false, "blockers": ["2 folders on box could be this project"],
        "match": ["path": NSNull(), "how": NSNull(),
                  "candidates": ["/home/me/code/api", ["path": "/srv/api", "how": "origin"]]]]
    let dryBackPick: [String: Any] = ["applied": false, "mode": "back", "target": "claude",
        "match": ["path": "/home/me/code/api", "how": "origin", "candidates": []],
        "source": ["agent": "codex", "session": "019a", "title": NSNull()],
        "git": ["there": ["branch": "main", "ahead": 1, "dirty": 0]], "brief": "# Back from box"]
    let viewOf = { (d: [String: Any], kind: String) -> PickupView in
        var v = PickupView(project: Project(["real_path": "/x/api", "exists": true]), machine: "box", kind: kind)
        (v.loading, v.dry) = (false, d)
        return v
    }
    var hitView = viewOf(dryPick, "pickup")
    (hitView.there, hitView.session, hitView.agent) = ("/home/me/code/api", "019a", "codex")
    var unsure = viewOf(dryBackPick, "pickup")
    let unsureBefore = pickupReady(unsure)
    unsure.confirmed = true
    let mt = thereMatch(dryPick), blockedMt = thereMatch(dryBlocked)
    let ss = thereSessions(dryPick)
    let pickOK = mt.path == "/home/me/code/api" && matchHow(mt.how).sure
        && matchLine(mt, machine: "box") == "Found on box by its project id: /home/me/code/api"
        && !matchHow("origin").sure && matchHow("home_relative").text == "at the same place in the home folder"
        && matchHow("there").sure && matchProblem(mt, machine: "box").isEmpty
        && blockedMt.path == nil && blockedMt.candidates == ["/home/me/code/api", "/srv/api"]
        && matchProblem(blockedMt, machine: "box").hasPrefix("2 folders on box could be this project")
        && ss.map { $0.id } == ["019a", "0f3a"] && ss[0].state == "working" && ss[1].state == nil
        && ss[1].title == "0f3a" && thereSession(dryPick, picked: nil) == "019a"
        && thereSession(dryPick, picked: "0f3a") == "0f3a"
        && gitWarning(dryPick, machine: "box")?.hasPrefix("On box: branch fix-login, 2 commits") == true
        && gitWarning(dryBackPick, machine: "box") == "On box: branch main, 1 commit not pushed."
        && gitWarning(["git": NSNull()], machine: "box") == nil
        && gitWarning(["git": ["there": ["branch": "main", "ahead": 0, "dirty": 0]]], machine: "box") == nil
        && pickupBrief(dryPick).text?.hasPrefix("# Picked up from box") == true
        && pickupBrief(["brief": "relay-1.md"]).file == "relay-1.md"
        && pickupBrief(["brief": ["text": "# x", "file": "/x/api/.aht/handover/relay-1.md"]]).file != nil
        && !pickupIsBack(dryPick) && pickupIsBack(dryBackPick) && pickupTarget(dryBackPick) == "claude"
        && pickupAgent(dryPick, installed: ["claude", "codex"]) == "codex"
        && pickupAgent(dryPick, installed: ["claude"]) == "claude"
        && pickupAgent(dryBackPick, installed: ["codex"]) == "claude"
        && pickupOpenText(dryPick, agent: "kimi", machine: "box", hook: true).hasPrefix(
            "Kimi Code continues the work of the Codex session on box (“fix the login redirect”) in a new "
            + "session here.")
        && pickupOpenText(dryBackPick, agent: "claude", machine: "box", hook: true)
            .contains("while Codex had the project on box")
        && pickupOpenText(dryBackPick, agent: "claude", machine: "box", hook: true)
            .contains("nothing runs until you type")
        && openCost("codex", back: false, hook: true)?.contains("which uses tokens") == true
        && openCost("claude", back: true, hook: true) == nil
        && openCost("claude", back: true, hook: false) != nil
        && pickupArgs(hitView) == ["pickup", "/x/api", "--from", "box", "--there", "/home/me/code/api",
                                   "--session", "019a", "--agent", "codex", "--json"]
        && pickupArgs(viewOf([:], "pickup"), apply: true, open: "codex")
            == ["pickup", "/x/api", "--from", "box", "--open", "codex", "--apply", "--json"]
        && pickupArgs(viewOf([:], "note"), apply: true) == ["leave-note", "/x/api", "--on", "box", "--apply", "--json"]
        && pickupArgs({ var v = viewOf([:], "note"); v.there = "/srv/api"; return v }())
            == ["leave-note", "/x/api", "--on", "box", "--there", "/srv/api", "--json"]
        && otherWarnings(["warnings": ["a", "b"], "git": ["warning": "a"]]) == ["b"]
        && startLine(["command_line": NSNull(), "start_line": "codex 'x'"]) == "codex 'x'"
        && startLine(["command_line": "", "start_line": NSNull()]) == nil
        && pickupReady(viewOf(dryPick, "pickup")) && !unsureBefore && pickupReady(unsure)
        && !pickupReady(viewOf(dryBlocked, "pickup")) && !pickupReady(viewOf(["error": "ssh: timed out"], "pickup"))
        && pickupTitle(viewOf(dryPick, "pickup")) == "Pick up “api” from box?"
    let opened = pickupDoneText(["applied": true, "opened": "codex", "brief": "relay-7.md",
                                 "command_line": "codex 'Read …'"], machine: "box", project: "/x/api", copied: false)
    let copiedTxt = pickupDoneText(["applied": true, "opened": NSNull(), "brief": "/x/api/.aht/handover/relay-7.md",
                                    "command_line": "codex 'Read …'"], machine: "box", project: "/x/api", copied: true)
    let backOpened = pickupDoneText(["applied": true, "mode": "back", "target": "claude", "opened": true],
                                    machine: "box", project: "/x/api", copied: false)
    let notThrough = pickupDoneText(["error": "box did not answer"], machine: "box", project: "/x/api", copied: false)
    let noteBack: [String: Any] = ["applied": true, "mode": "back", "brief": "/home/me/code/api/.aht/handover/relay-8.md",
                                   "note_for": ["agent": "claude", "session": "0f3a", "title": "fix the login redirect"]]
    let leftBack = noteDoneText(noteBack, machine: "mac")
    let leftFull = noteDoneText(["applied": true, "brief": "relay-9.md", "note_for": NSNull()], machine: "box")
    let doneOK = opened == "Picked up from box: Codex is open here and reads the summary first: "
            + "/x/api/.aht/handover/relay-7.md"
        && copiedTxt.hasPrefix("Picked up from box. The summary is here: /x/api/.aht/handover/relay-7.md. "
                               + "Nothing was opened.") && copiedTxt.contains("on the clipboard")
        && backOpened.hasPrefix("Picked up from box: Claude Code's own session is open again")
        && notThrough == "Pick Up did not go through:\n\n• box did not answer"
        && leftBack.hasPrefix("Handed back to mac (relay-8.md), for Claude Code's own session there. "
                              + "Claude Code reads it by itself when you continue that session on mac.")
        && leftFull == "The note is on box: .aht/handover/relay-9.md. Nothing runs there; Pick Up from "
            + "this Mac there brings the work over."
        && noteReader(noteBack, machine: "mac").hasPrefix("For Claude Code's own session on mac (“fix the login")
        && noteReader([:], machine: "box").hasPrefix("A full summary for whoever goes on there.")
        && pickupTitle(viewOf(noteBack, "note")) == "Hand “api” back to box?"
        && pickupTitle(viewOf([:], "note")) == "Leave a note about “api” on box?"
    print("PICK UP SHEET \(pickOK && doneOK ? "OK" : "FAIL — \(opened) / \(copiedTxt) / \(leftBack) / \(leftFull)")")
    // the Machines menu, and the line over a project work came to from another machine
    let worked = Calendar.current.date(bySettingHour: 0, minute: 20, second: 0, of: Date())!
    let came = { (inc: Any, extra: [String: Any]) -> Project in
        Project(["real_path": "/x/api", "exists": true, "sessions": 2,
                 "relay": (["id": "20261027-141000-ab12", "from_agent": "codex", "to_agent": "claude",
                            "since": worked.timeIntervalSince1970 + 600, "open": true,
                            "incoming": inc] as [String: Any]).merging(extra) { $1 }])
    }
    let picked = came(["machine": "mac", "kind": "pickup", "agent": "claude"],
                      ["kind": "pickup", "machine": "mac", "remote": "studio", "arrived": true, "told": true])
    let noted = came(["machine": "pc", "kind": "note", "agent": "codex", "brief": "relay-20261027-141000-ab12.md",
                      "worked_from": worked.timeIntervalSince1970 - 3000, "worked_to": worked.timeIntervalSince1970],
                     ["open": false])
    let handed = came(true, ["kind": "back", "from_machine": "pc", "note_for": ["agent": "claude", "session": "0f3a"]])
    let local = came(NSNull(), ["kind": "switch", "machine": NSNull()]), unnamed = came(true, [:])
    // the sending machine's copy: across machines, so no Phase 2 Hand Back, and no banner
    let sent = came(NSNull(), ["kind": "pickup", "machine": "pc", "remote": "pc"])
    let menuP = machineItems(picked, ["box", "studio"]), menuPlain = machineItems(local, ["box"])
    let at = clock(worked.addingTimeInterval(600))
    let menuOK = menuP.map { $0.title } == ["Hand Back to studio…", "Pick Up from box…", "Pick Up from studio…",
                                             "Leave a Note on box…", "Leave a Note on studio…"]
        && menuP.map { $0.kind } == ["back", "pickup", "pickup", "note", "note"] && menuP[0].machine == "studio"
        && sent.handBack == nil && sent.incoming == nil && sent.relay?.machine == "pc"
        && switchItems(sent, ["codex"]).first?.back == false
        && menuPlain.map { $0.title } == ["Pick Up from box…", "Leave a Note on box…"]
        && machineItems(local, []).isEmpty
        && picked.pickedUpFrom == "studio" && picked.handBack == nil && picked.incoming?.isNote == false
        && picked.incoming?.machine == "mac"
        && noted.pickedUpFrom == nil && noted.relay == nil && noted.incoming?.machine == "pc"
        && handed.incoming?.kind == "back" && handed.incoming?.noteFor == "0f3a" && handed.handBack == nil
        && local.incoming == nil && local.handBack != nil && unnamed.incoming == nil
        && incomingLine(picked.incoming!) == "Picked up from studio at \(at), where Claude Code worked"
        && incomingLine(noted.incoming!) == "pc left a note at \(at): Codex worked there from "
            + "\(clock(worked.addingTimeInterval(-3000))) to \(clock(worked))"
        && incomingLine(handed.incoming!) == "pc handed this project back at \(at): Codex worked there"
    let bannerSaid = noted.incoming.map(incomingLine) ?? "-"
    print("MACHINES MENU AND NOTE BANNER \(menuOK ? "OK" : "FAIL — \(menuP.map { $0.title }) / \(bannerSaid)")")
    // Continue Here…: the folder here that is that folder there
    let mine = [HOME + "/code/api", HOME + "/old/api", HOME + "/code/site"]
    let noFolder = { (_: String) in false }
    let twinOK = homeRelative("/home/me/code/api") == "code/api"
        && homeRelative("/Users/me/code/api") == "code/api"
        && homeRelative("C:\\Users\\me\\code\\api") == "code/api"
        && homeRelative("/root/api") == "api" && homeRelative("/srv/api") == nil
        && homeRelative("/home/me") == nil
        && localTwins("/home/me/code/api", mine, exists: noFolder) == [HOME + "/code/api"]
        && localTwins(HOME + "/code/site", mine, exists: noFolder) == [HOME + "/code/site"]
        && localTwins("/srv/www/api", mine, exists: noFolder) == [HOME + "/code/api", HOME + "/old/api"]
        && localTwins("C:\\Users\\me\\work\\api", mine, exists: { $0 == HOME + "/work/api" })
            == [HOME + "/work/api"]
        && localTwins("/srv/www/blog", mine, exists: noFolder).isEmpty
    print("CONTINUE HERE \(twinOK ? "OK" : "FAIL")")
    // Phase 4 fixes. [1] Copy the Start Line: --open the agent picked here
    // with --no-window (--agent stays the session there's agent), and Kimi's
    // token line kept for it
    let copyArgs = pickupArgs(hitView, apply: true, open: "claude", noWindow: true)
    let fix1OK = copyArgs == ["pickup", "/x/api", "--from", "box", "--there", "/home/me/code/api",
                              "--session", "019a", "--agent", "codex", "--open", "claude", "--apply",
                              "--no-window", "--json"]
        && !pickupArgs(viewOf([:], "pickup"), apply: true, noWindow: true).contains("--no-window")
        && openCost("kimi", back: false, hook: true, machine: "box").map {
            $0.contains("Kimi reads the summary in a run of its own first, for Open in and for Copy the Start Line")
                && $0.contains("uses tokens") && $0.contains("a copy of it on box") } == true
        && openCost("kimi", back: true, hook: true) != nil
        && openCost("codex", back: false, hook: true, machine: "box")?.contains("a copy of it on box") == true
        && pickupOpenText(dryPick, agent: "kimi", machine: "box", hook: true).contains("Kimi reads it in a first run")
    print("P4 FIX 1 COPY THE START LINE \(fix1OK ? "OK" : "FAIL — \(copyArgs)")")
    // [2] a hand-back note: Claude Code reads it by itself (aht's hook);
    // another agent is asked to read it, here and on the other machine
    let codexBack: [String: Any] = ["applied": true, "mode": "back", "brief": "/srv/api/.aht/handover/relay-8.md",
                                    "note_for": ["agent": "codex", "session": "019a", "title": "redirect"]]
    let handedCx = Project(["real_path": "/x/api", "exists": true, "relay": [
        "id": "20261027-141000-ab12", "from_agent": "codex", "to_agent": "codex", "open": false, "kind": "note",
        "machine": "pc", "incoming": ["machine": "pc", "kind": "back", "agent": "claude",
                                      "brief": "/x/api/.aht/handover/relay-20261027-141000-ab12.md",
                                      "note_for": ["agent": "codex", "session": "019a"]]]])
    let fix2Said = [noteReader(codexBack, machine: "mac"), noteDoneText(codexBack, machine: "mac"),
                    handedCx.incoming.map { incomingDetail($0, hook: true) } ?? "-",
                    handed.incoming.map { incomingDetail($0, hook: true) } ?? "-",
                    handed.incoming.map { incomingDetail($0, hook: false) } ?? "-"]
    let fix2OK = noteReads("claude", on: " on mac") == "Claude Code reads it by itself when you continue that session on mac."
        && noteReads("vibe", file: "x.md") == "Mistral Vibe does not read it by itself: when you continue that session, ask it to read x.md first."
        && noteReads(nil).contains("another agent does not")
        && fix2Said[0].contains("Codex does not read it by itself: when you continue that session on mac, ask it to read the note")
        && fix2Said[1].contains("Codex does not read it by itself") && fix2Said[1].contains("ask it to read .aht/handover/relay-8.md first")
        && fix2Said[2].contains("Codex does not read it by itself") && fix2Said[2].contains(".aht/handover/relay-20261027-141000-ab12.md")
        && fix2Said[3].contains("Claude Code reads it by itself when you continue that session.")
        && fix2Said[4].contains("Claude Code does not read it by itself (aht's hook is off)")
        && noteReader(noteBack, machine: "mac").contains("Claude Code reads it by itself when you continue that session on mac.")
        && !(fix2Said + [noteReader(noteBack, machine: "mac"), leftBack]).contains { $0.contains("when it opens again") }
    print("P4 FIX 2 HAND-BACK NOTE PER AGENT \(fix2OK ? "OK" : "FAIL — \(fix2Said)")")
    // [3] `pickup_from`: the pickup open here, also under a newer local relay
    // (Hand Back to box, and the line); null: none; missing: the relay's
    let pf: [String: Any] = ["machine": "box", "remote": "box", "relay": "20261027-101500-aaaa",
                             "at": worked.timeIntervalSince1970, "agent": "claude", "session": "s1"]
    let switched = came(NSNull(), ["kind": "switch", "machine": NSNull(), "from_agent": "claude", "to_agent": "codex"])
    let pfRow = { (x: Any) -> Project in
        Project(["real_path": "/x/api", "exists": true, "sessions": 2, "pickup_from": x,
                 "relay": ["id": "20261027-160000-cccc", "from_agent": "claude", "to_agent": "codex",
                           "since": worked.timeIntervalSince1970 + 900, "open": true, "kind": "switch",
                           "machine": NSNull(), "remote": NSNull(), "incoming": NSNull()]])
    }
    let pfBoth = pfRow(pf), pfNone = pfRow(NSNull())
    let unset = pfRow(pf.merging(["remote": NSNull()]) { $1 })
    let pickedNull = Project(["real_path": "/x/api", "exists": true, "pickup_from": NSNull(),
                              "relay": ["id": "20261027-141000-ab12", "from_agent": "claude", "to_agent": "codex",
                                        "open": true, "kind": "pickup", "machine": "mac", "remote": "studio",
                                        "incoming": ["machine": "mac", "kind": "pickup", "agent": "claude"]]])
    let fix3OK = pfBoth.pickedUpFrom == "box" && pfBoth.handBack != nil && pfBoth.incoming == nil
        && pfBoth.pickedUp?.kind == "pickup" && pfBoth.pickedUp?.agent == "claude"
        && incomingLine(pfBoth.pickedUp!) == "Picked up from box at \(clock(worked)), where Claude Code worked"
        && machineItems(pfBoth, ["box", "mini"]).first?.title == "Hand Back to box…"
        && machineItems(pfBoth, ["box", "mini"]).first?.kind == "back"
        && switchItems(pfBoth, ["codex"]).first?.title == "Hand Back to Claude Code (its own session)…"
        && pfNone.pickedUp == nil && pfNone.pickedUpFrom == nil && machineItems(pfNone, ["box"]).first?.kind == "pickup"
        && unset.pickedUp != nil && unset.pickedUpFrom == nil && machineItems(unset, ["box"]).first?.kind == "pickup"
        && pickedNull.pickedUpFrom == nil && pickedNull.pickedUp == nil && pickedNull.incoming?.isNote == false
        && switched.pickedUpFrom == nil && picked.pickedUpFrom == "studio" && picked.pickedUp?.machine == "mac"
    print("P4 FIX 3 PICKUP_FROM \(fix3OK ? "OK" : "FAIL — \(machineItems(pfBoth, ["box"]).map { $0.title })")")
    // [4] a Windows PC answers no other machine: not in the Machines menu
    let mixed = machinesFrom(["pc": ["ssh": "me@pc", "system": "Windows"], "box": ["ssh": "me@box", "system": "Linux"],
                              "mini": ["ssh": "me@mini", "system": "Darwin"], "old": ["ssh": "me@old"]])
    let fix4OK = askableMachines(mixed) == ["box", "mini", "old"]
        && !machineItems(local, askableMachines(mixed)).contains { $0.machine == "pc" }
        && askableMachines(machinesFrom(["pc": ["ssh": "me@pc", "system": "Windows"]])).isEmpty
    print("P4 FIX 4 NO WINDOWS IN MACHINES MENU \(fix4OK ? "OK" : "FAIL — \(askableMachines(mixed))")")
    // … and the core's phase-4 samples: AHT_FIXTURES_PHASE4
    var phase4OK = true
    let dir4 = ProcessInfo.processInfo.environment["AHT_FIXTURES_PHASE4"] ?? ""
    if !dir4.isEmpty && FileManager.default.fileExists(atPath: dir4) {
        var miss: [String] = []
        func sample(_ n: String) -> [String: Any] {
            let f = URL(fileURLWithPath: dir4).appendingPathComponent(n)
            guard let data = try? Data(contentsOf: f) else { miss.append(n + " (missing)"); return [:] }
            let d = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            if d == nil { miss.append(n + " (not JSON)") }
            return d ?? [:]
        }
        let contract = ["match", "source", "git", "brief", "relay", "applied", "opened", "command_line"]
        // a `how` the app has no words for reads "by <how>"
        let unknownHow = { (h: String?) in matchHow(h).text.isEmpty || matchHow(h).text == "by " + (h ?? "") }
        func view(_ d: [String: Any], _ kind: String) -> PickupView {
            var v = PickupView(project: Project(["real_path": d["project"] as? String ?? "/x", "exists": true]),
                               machine: (d["machine"] ?? d["from"] ?? d["on"]) as? String ?? "box", kind: kind)
            (v.loading, v.dry) = (false, d)
            return v
        }
        // the dry run: every field of the contract, a folder found in words the
        // app knows, the sessions there, a summary to show, and the Open in text
        let pk = sample("pickup.json")
        let pkm = thereMatch(pk), pkv = view(pk, "pickup")
        let agent = pickupAgent(pk, installed: SWITCH_AGENTS) ?? ""
        if contract.contains(where: { pk[$0] == nil }) || pk["applied"] as? Bool != false
            || pkm.path == nil || unknownHow(pkm.how)
            || thereSessions(pk).isEmpty || pickupBrief(pk).text == nil
            || (matchHow(pkm.how).sure && !pickupReady(pkv))
            || pickupIsBack(pk) || AGENT_LABEL[agent] == nil
            || !pickupOpenText(pk, agent: agent, machine: pkv.machine, hook: true)
                .hasPrefix(AGENT_LABEL[agent] ?? "?")
            || thereSessions(pk).contains(where: { AGENT_LABEL[$0.agent] == nil })
            || ((pk["sessions"] as? [[String: Any]]) ?? []).contains(where: { r in
                let st = thereSessions(["sessions": [r]]).first?.state
                return st != (r["working"] as? Bool == true ? "working" : r["open"] as? Bool == true ? "open" : nil)
            })
            || ((pk["git"] as? [String: Any])?["warning"] as? String).map({ w in
                otherWarnings(pk).contains(w) || gitWarning(pk, machine: pkv.machine) != w }) == true
            || !["full", "catchup", "full+catchup"].contains(pk["brief_kind"] as? String ?? "")
            || (pk["git"] is [String: Any] && gitWarning(pk, machine: pkv.machine) == nil
                && ((pk["git"] as? [String: Any])?["there"] as? [String: Any]).map {
                    ($0["dirty"] as? Int ?? 0) + ($0["ahead"] as? Int ?? 0) > 0 } == true) {
            miss.append("pickup.json")
        }
        // two folders could be the project: blocked, each one listed to pick
        let bl = sample("pickup_blocked.json")
        let blm = thereMatch(bl)
        var picked4 = view(bl, "pickup")
        picked4.there = blm.candidates.first
        if blm.path != nil || blm.candidates.count < 2 || pickupReady(view(bl, "pickup"))
            || !pickupArgs(picked4).contains(blm.candidates.first ?? "\u{0}")
            || !matchProblem(blm, machine: "box").hasPrefix("\(blm.candidates.count) folders")
            || Set(blm.candidates).count != blm.candidates.count {
            miss.append("pickup_blocked.json")
        }
        // back mode: the session the work left goes on, reading what changed
        let bk = sample("pickup_back.json")
        let bkAgent = pickupAgent(bk, installed: []) ?? ""
        if contract.contains(where: { bk[$0] == nil }) || !pickupIsBack(bk) || pickupTarget(bk) == nil
            || !(bk["brief_kind"] as? String ?? "").contains("catchup") || !(bk["back_of"] is String)
            || AGENT_LABEL[bkAgent] == nil
            || !pickupOpenText(bk, agent: bkAgent, machine: "box", hook: true).contains("goes on in its own session")
            || pickupBrief(bk).text == nil && pickupBrief(bk).file == nil {
            miss.append("pickup_back.json")
        }
        // a note: where it goes, what it says, and for whom
        let ln = sample("leave_note.json")
        let lnm = thereMatch(ln)
        if ln["applied"] == nil || lnm.path == nil || unknownHow(lnm.how)
            || (pickupBrief(ln).text == nil && pickupBrief(ln).file == nil)
            || (ln["note_for"] != nil && !(ln["note_for"] is NSNull) && noteFor(ln) == nil)
            || noteReader(ln, machine: "box").isEmpty
            || ((ln["applied"] as? Bool == true) && pickupProblems(ln) == nil
                && noteDoneText(ln, machine: "box").hasPrefix("The note was not left")) {
            miss.append("leave_note.json")
        }
        // projects: each row with work from another machine names it, and a
        // pickup gets Hand Back to that machine first in the Machines menu
        let pj = sample("projects.json")
        let rows = (pj["projects"] as? [[String: Any]]) ?? (pj.isEmpty ? [] : [pj])
        let came = rows.filter { r in
            let inc = (r["relay"] as? [String: Any])?["incoming"]
            return inc is [String: Any] || inc as? Bool == true
        }
        if came.isEmpty { miss.append("projects.json (no row with relay.incoming)") }
        for r in came {
            let p = Project(r)
            guard let i = p.incoming else { miss.append("projects.json (incoming without its machine)"); continue }
            let first = machineItems(p, [i.name]).first
            let rl = (r["relay"] as? [String: Any]) ?? [:]
            let remote = rl["remote"] as? String
            if i.at == nil || !incomingLine(i).contains(i.name) || p.relay?.machine == nil && p.relay != nil
                || (remote != nil && i.name != remote)
                || (i.kind == "pickup" && (first?.title != "Hand Back to \(i.name)…" || p.pickedUpFrom != i.name))
                || (i.kind != "pickup" && first?.kind == "back")
                || (i.isNote && i.brief == nil) || p.handBack != nil {
                miss.append("projects.json")
            }
        }
        // a newer core's `pickup_from`: the pickup open here, by its machine
        for r in rows where r.keys.contains("pickup_from") {
            let p = Project(r)
            guard let f = r["pickup_from"] as? [String: Any] else {
                if !(r["pickup_from"] is NSNull) || p.pickedUp != nil { miss.append("projects.json (pickup_from)") }
                continue
            }
            let remote = f["remote"] as? String
            if p.pickedUp?.kind != "pickup" || p.pickedUp?.at == nil || p.pickedUpFrom != remote
                || (remote != nil && machineItems(p, [remote!]).first?.title != "Hand Back to \(remote!)…")
                || ["machine", "remote", "relay", "at", "agent", "session"].contains(where: { f[$0] == nil }) {
                miss.append("projects.json (pickup_from)")
            }
        }
        miss = miss.filter { !miss.contains($0 + " (missing)") && !miss.contains($0 + " (not JSON)") }
        phase4OK = miss.isEmpty
        print("PHASE 4 SAMPLES \(phase4OK ? "OK" : "FAIL \(miss)") — \(dir4)")
    } else {
        print("PHASE 4 SAMPLES not checked (" + (dir4.isEmpty ? "AHT_FIXTURES_PHASE4 names no folder"
                                                       : "no samples in \(dir4) yet") + ")")
    }
    // Keep in sync that looks before it overwrites (phase 5): the pauses a
    // sync makes by itself (`mirror_paused`), their words and answers and the
    // questions that name what is set aside; a copy synced from another
    // machine (`copy_of`); "2 paused" in Machines; Hand Over over a changed
    // copy (`copy_changed`, and the blocker naming --replace-there); Bring
    // Them Here (`reclaim --json` in copy mode, and the sync after it);
    // Replace Them's and Sync Now's notes
    let p5pause = { (reason: String, c: Int, n: Int, r: Int, files: [String]) -> [String: Any] in
        ["reason": reason, "at": iso(Date()), "remote": "box", "changed": c, "new": n, "removed": r,
         "history": 0, "files": files, "total": 40]
    }
    let p5row = { (pause: [String: Any]) in
        Project(["real_path": "/x/api", "exists": true, "mirror": "box", "mirror_synced_at": t - 3600,
                 "mirror_status": "paused", "mirror_paused": pause])
    }
    let p5changed = p5row(p5pause("changed", 3, 1, 0, ["src/a.py", "src/b.py", "README.md", "notes/new.md"]))
    let p5talked = p5row(p5pause("changed", 0, 0, 0, []).merging(["history": 2]) { $1 })
    let p5removals = p5row(p5pause("removals", 0, 0, 25, ["old/1.txt", "old/2.txt"]))
    let p5other = p5row(p5pause("other-folder", 0, 0, 0, ["notes.txt"]).merging(["total": 1, "marker": NSNull()]) { $1 })
    let p5theirs = p5row(p5pause("other-folder", 0, 0, 0, []).merging(["total": 12, "marker": "07f3"]) { $1 })
    let p5copy = Project(["real_path": "/home/me/code/api", "exists": true,
                          "copy_of": ["from": "mac", "kind": "sync", "at": iso(Date())]])
    let p5s = p5changed.syncPaused!, p5rm = p5removals.syncPaused!, p5of = p5other.syncPaused!
    let p5ask = replaceAsk(p5s, "api", "box", aside: "/home/me/.aht/remote/replaced/07f3/")
    let p5rmAsk = removalsAsk(p5rm, "api", "box")
    let p5why = "the copy on box was changed since 18:10 (1 changed: src/a.py) — bring them here first "
        + "(aht reclaim /x/api --apply), or pass --replace-there to set them aside there"
    let p5blocked: [String: Any] = ["remote": "box", "blockers": [p5why]]
    let p5counted: [String: Any] = ["blockers": [p5why], "copy_changed": [
        "changed": 2, "new": 0, "removed": 1, "history": 1, "files": ["a", "b"], "conversations": [],
        "since": iso(Date())]]
    let p5open: [String: Any] = ["blockers": ["a session is open in it on box"]]
    let p5two: [String: Any] = ["blockers": ["a session is open in it on box", p5why]]
    let p5plan: [String: Any] = ["mode": "copy", "remote": "box", "conflicts": [String: Any](),
                                 "plan": ["project": ["take": 3, "new": 1, "delete": 0, "conflict": 0]]]
    let p5done: [String: Any] = ["applied": true, "mode": "copy", "remote": "box",
        "done": ["project": ["conflicts": [["file": "README.md", "their_version": "README (from box 2026-10-27).md"]]]],
        "sync": ["project": "/x/api", "remote": "box", "status": "synced", "files": 3]]
    let p5again: [String: Any] = p5done.merging(["sync": ["project": "/x/api", "remote": "box", "status": "paused",
        "reason": "paused: 1 changed", "paused": p5pause("changed", 1, 0, 0, ["src/c.py"])]]) { $1 }
    let p5text = pauseText(p5s, "box")
    let pause5OK = p5s.asks && p5s.changed == 3 && p5s.new == 1 && p5s.files.count == 4 && p5s.total == 40
        && p5changed.sync == "paused" && p5s.machine == "box" && p5s.at != nil
        && pauseActions(p5s) == [.bring, .replace, .stop]
        && pauseActions(p5rm) == [.allow, .stop] && pauseActions(p5of) == [.replace, .stop]
        && pauseActions(paused.syncPaused!) == [.resume] && !paused.syncPaused!.asks
        && p5text.contains("(3 changed and 1 new): src/a.py, src/b.py and 2 more.")
        && p5text.hasPrefix("The copy on box was changed since the last sync")
        && p5text.hasSuffix("Nothing was sent; that work is still there.")
        && pauseText(p5talked.syncPaused!, "box").contains("(2 conversations went on)")
        && pauseText(paused.syncPaused!, "box").hasPrefix("You released the project at ")
        && p5ask.title == "Replace the copy of “api” on box?"
        && p5ask.body.contains("(3 changed and 1 new) is set aside there, not deleted")
        && p5ask.body.contains("Changed on box:\n• src/a.py\n• src/b.py\n• README.md\n• notes/new.md")
        && p5ask.body.contains("kept in /home/me/.aht/remote/replaced/07f3/ on box.")
        && p5ask.body.hasSuffix("use Bring Them Here.")
        && replaceAsk(p5of, "api", "box").body.hasPrefix("The file in the folder on box is set aside there, not deleted")
        && replaceAsk(p5theirs.syncPaused!, "api", "box").body.hasPrefix("The 12 files in the folder on box are set aside")
        && replaceAsk(p5of, "api", "box").body.contains("• notes.txt")
        && !replaceAsk(p5of, "api", "box").body.contains("Bring Them Here")
        && p5rmAsk.title == "Remove 25 of the 40 files in the copy on box?"
        && p5rmAsk.body.contains("• old/1.txt\n• old/2.txt\n• …")
        && pauseText(p5rm, "box").contains("remove 25 of the 40 files in the copy on box (old/1.txt, old/2.txt and 23 more)")
        && pauseText(p5of, "box") == "The folder on box already holds files aht did not put there (1 file: notes.txt). Nothing was sent."
        && pauseText(p5theirs.syncPaused!, "box") == "The folder on box holds another project (12 files). Nothing was sent."
        && p5copy.copyOf?.from == "mac" && p5copy.copyOf?.kind == "sync" && p5copy.copyOf?.at != nil
        && copyLine(p5copy.copyOf!) == "Copy kept in sync from mac: changes made here pause that sync"
        && syncRefused(p5copy, "mac") && !syncRefused(p5copy, "box") && !syncRefused(p5changed, "box")
        && p5changed.copyOf == nil && CopyOf(NSNull()) == nil
        && pausedWith([p5changed, p5removals, p5other, paused, syncing, p5copy], "box").count == 4
        && pausedWith([p5changed, paused], "studio").isEmpty
        && changedThere(p5blocked) != nil && otherBlockers(p5blocked).isEmpty
        && changedThere(p5counted)?.changed == 2 && changedThere(p5counted)?.removed == 1
        && changedThere(p5counted)?.at != nil && otherBlockers(p5counted).isEmpty
        && changedThere(p5open) == nil && otherBlockers(p5two) == ["a session is open in it on box"]
        && changedThereText(changedThere(p5counted)!, "api", "box")
            .contains("(2 changed, 1 removed and 1 conversation went on)")
        && changedThereText(changedThere(p5counted)!, "api", "box").contains("last matched at ")
        && replaceThereLine(changedThere(p5counted)!, "box").hasPrefix("⚠ What was changed on box (2 changed")
        && takeBackText(p5plan, "box", copy: true, synced: true).hasPrefix("3 file(s) changed there, 1 new, 0 removed.")
        && takeBackText(p5plan, "box", copy: true, synced: true).contains("Then Keep in sync with box goes on")
        && !takeBackText(p5plan.merging(["would_stop": true]) { $1 }, "box", copy: true, synced: true).contains("ended first")
        && takeBackText(p5plan.merging(["would_stop": true]) { $1 }, "box", copy: false, synced: false).contains("ended first")
        && broughtText(p5done, "box", now: p5changed).hasSuffix("Keep in sync with box ran: the copy there matches this Mac again.")
        && broughtText(p5done, "box", now: nil)
            .contains("Changed on both machines, both kept: README.md (theirs: README (from box 2026-10-27).md).")
        && broughtText(p5again, "box", now: nil).contains("Keep in sync with box paused again: The copy on box was changed")
        && broughtText(["set_aside": "/x/.aht/aside/1"], "box", now: syncing).hasSuffix("Keep in sync with box goes on.")
        && broughtText([:], "box", now: p5changed).contains("still paused")
        && syncSummary([["status": "synced"], ["status": "paused"], ["status": "skipped"]])
            == "1 synced, 1 paused — see Projects, 1 skipped — see the log"
        && syncSummary([["status": "synced"]]) == "1 synced"
        && syncAllNote(held: 2, copies: ["/home/me/code/api"])
            == "\n\n2 paused: they stay paused until you answer them in Projects.\n\n1 folder here is a copy "
               + "of another machine's project and stays out: api."
        && syncAllNote(held: 0, copies: []).isEmpty
        && findPauses(["mirrored": [["project": "/x/api", "status": "paused", "files": 3,
                                      "reason": "paused: 1 changed", "paused": p5pause("changed", 1, 0, 0, [])]]]).count == 1
        && findPauses(["mirror_paused": ["reason": "released", "at": iso(Date())]]).isEmpty
        && stoppedText("box", ok: true, err: "", now: Project(["real_path": "/x/api", "exists": true]),
                       changed: true).hasSuffix("stays as it is, with the work done there.")
        && stoppedText("box", ok: false, err: "no such project\n", now: nil, changed: false)
            == "The sync was not stopped:\n\nno such project"
        && replacedText([:], "api", "box", removals: false, now: p5changed)
            .hasPrefix("Keep in sync with box is still paused: The copy on box")
        && replacedText(["applied": true, "mirrored": [["status": "synced", "ended_pause": "changed", "replaced": 4,
                                                         "removed": 0]]], "api", "box", removals: false,
                        aside: "/home/me/.aht/remote/replaced/07f3/", now: syncing)
            == "This Mac's copy of api is on box again: 4 files replaced there, kept in /home/me/.aht/remote/replaced/07f3/ on box."
        && replacedText(["applied": true, "mirrored": [["status": "synced", "replaced": 0, "removed": 25]]], "api", "box",
                        removals: true, now: syncing)
            == "The copy of api on box matches this Mac again: 25 files removed there, kept on box."
    print("SYNC THAT LOOKS FIRST \(pause5OK ? "OK" : "FAIL — \(p5text) / \(p5ask.body) / \(pauseText(p5rm, "box"))")")
    // P5 fix 1: Turn Sync Back On no longer says the work left there is
    // replaced: the next sync pauses over it and asks
    let back5 = resumeAsk("api", "box", released: true), back5b = resumeAsk("api", "box", released: false)
    let fix51 = back5.title == "Turn Keep in sync with box back on?"
        && !back5.body.contains("is replaced") && !back5b.body.contains("is replaced")
        && back5.body.contains("If that copy was worked on since you released it, the sync pauses first and sends nothing")
        && back5.body.contains("Bring Them Here, Replace Them (set aside on box first, not deleted) or Stop Syncing.")
        && back5b.body.contains("worked on there, the sync pauses first")
    print("P5 FIX 1 TURN SYNC BACK ON ASKS FIRST \(fix51 ? "OK" : "FAIL — \(back5.body)")")
    // P5 fix 2: Replace Them names what the sync removes there (`removals`);
    // over the limit the question says so and going ahead adds --allow-removals;
    // an older core's dry run (no `removals`) asks as before
    let rm52: [String: Any] = ["removed": 30, "total": 40, "over": true,
                               "files": (0..<30).map { "old/\($0).txt" }]
    let dry52: [String: Any] = ["mode": "replace", "applied": false, "removals": rm52, "warnings": [String](),
        "blockers": ["this sync would remove 30 of the 40 files on box — pass --allow-removals as well"]]
    let few52 = Removals(["removed": 2, "total": 40, "files": ["a.txt", "b.txt"], "over": false])
    let ask52 = replaceAsk(p5s, "api", "box", aside: "/home/me/.aht/remote/replaced/07f3/",
                           removals: Removals(pastRemovals(dry52)["removals"]))
    let few52ask = replaceAsk(p5s, "api", "box", removals: few52)
    let old52 = replaceAsk(p5s, "api", "box", removals: Removals(p5plan["removals"]))
    let fix52 = Removals(rm52)?.over == true && Removals(rm52)?.allow == ["--allow-removals"]
        && few52?.allow == [] && Removals(["removed": 0, "total": 3, "files": [String]()]) == nil
        && Removals(nil) == nil && Removals(rm52)?.counted == "30 of the 40 files"
        && (pastRemovals(dry52)["blockers"] as? [String]) == []
        && (pastRemovals(dry52.merging(["blockers": ["the folder on box is missing or empty"]]) { $1 })["blockers"]
            as? [String]) == ["the folder on box is missing or empty"]
        && (pastRemovals(dry52.merging(["removals": ["removed": 30, "total": 40, "over": false]]) { $1 })["blockers"]
            as? [String])?.count == 1
        && ask52.body.contains("On box, this sync removes 30 of the 40 files, set aside there first:\n• old/0.txt\n• old/1.txt")
        && ask52.body.contains("That is more than aht removes without asking, so Replace Them allows these removals too, once.")
        && ask52.body.hasSuffix("use Bring Them Here.")
        && few52ask.body.contains("On box, this sync removes 2 of the 40 files, set aside there first:\n• a.txt\n• b.txt")
        && !few52ask.body.contains("more than aht removes")
        && old52.body == replaceAsk(p5s, "api", "box").body && !old52.body.contains("this sync removes")
        && replaceAsk(p5of, "api", "box", removals: Removals(["removed": 1, "total": 1, "files": ["notes.txt"]]))
            .body.contains("On box, this sync removes 1 file, set aside there first:\n• notes.txt")
    print("P5 FIX 2 REPLACE THEM NAMES THE REMOVALS \(fix52 ? "OK" : "FAIL — \(ask52.body)")")
    // P5 fix 3: Bring Them Here with removals here over the limit: named, and
    // going ahead allows them; a blocker the removals do not lift stays
    let dry53: [String: Any] = ["mode": "copy", "remote": "box", "conflicts": [String: Any](),
        "plan": ["project": ["take": 0, "new": 0, "delete": 34, "conflict": 0]],
        "removals": ["removed": 34, "total": 40, "over": true, "files": (0..<34).map { "src/m\($0).py" }],
        "blockers": ["bringing them here would remove 34 of the 40 files here — pass --allow-removals if they were removed there on purpose"]]
    let empty53 = dry53.merging(["blockers": ["the folder on box is missing or empty: nothing is brought here"]]) { $1 }
    let ask53 = takeBackText(pastRemovals(dry53), "box", copy: true, synced: true)
    let fix53 = (pastRemovals(dry53)["blockers"] as? [String]) == []
        && Removals(pastRemovals(dry53)["removals"])?.allow == ["--allow-removals"]
        && (pastRemovals(empty53)["blockers"] as? [String])?.count == 1
        && ask53.contains("It removes 34 of the 40 files here, because they are gone from the copy on box: more than aht removes without asking, so going ahead allows it, once.")
        && ask53.contains("not deleted:\n• src/m0.py\n• src/m1.py") && ask53.contains("If they went missing on box by mistake, cancel.")
        && !takeBackText(p5plan.merging(["removals": ["removed": 3, "total": 40, "over": false, "files": ["a"]]]) { $1 },
                         "box", copy: true, synced: true).contains("It removes")
        && !takeBackText(dry53, "box", copy: false, synced: false).contains("It removes")
    print("P5 FIX 3 BRING THEM HERE GUARD \(fix53 ? "OK" : "FAIL — \(ask53)")")
    // P5 fix 4: "Then Keep in sync with box goes on" only when the project is
    // kept in sync with that machine (Hand Over's block reaches Bring Them Here
    // for a copy that is not)
    let fix54 = takeBackText(p5plan, "box", copy: true, synced: true).contains("Then Keep in sync with box goes on")
        && !takeBackText(p5plan, "box", copy: true, synced: false).contains("Keep in sync")
    print("P5 FIX 4 KEEP IN SYNC LINE ONLY WHEN SYNCED \(fix54 ? "OK" : "FAIL")")
    // … and the core's phase-5 samples: AHT_FIXTURES_PHASE5
    var phase5OK = true
    let dir5 = ProcessInfo.processInfo.environment["AHT_FIXTURES_PHASE5"] ?? ""
    let names5 = ((try? FileManager.default.contentsOfDirectory(atPath: dir5)) ?? [])
        .filter { $0.hasSuffix(".json") }.sorted()
    if !dir5.isEmpty && !names5.isEmpty {
        var miss: [String] = []
        func sample(_ n: String) -> Any? {
            let f = URL(fileURLWithPath: dir5).appendingPathComponent(n)
            guard let data = try? Data(contentsOf: f) else { miss.append(n + " (missing)"); return nil }
            let d = try? JSONSerialization.jsonObject(with: data)
            if d == nil { miss.append(n + " (not JSON)") }
            return d
        }
        // every pause the core wrote: a reason that asks, when, what it found,
        // the answers for that reason, and the files named in its question
        let pauseFiles = names5.filter { $0.hasPrefix("mirror_paused") }
        if pauseFiles.isEmpty { miss.append("mirror_paused*.json (missing)") }
        for n in pauseFiles {
            let d = sample(n)
            let found = findPauses(d)
            if found.isEmpty && d != nil { miss.append(n + " (no pause in it)") }
            for g in found {
                let s = SyncPause(g), to = s.machine ?? "box"
                let acts = pauseActions(s)
                let counted = ["changed", "new", "removed", "history", "total"]
                    .allSatisfy { g[$0] == nil || tally(g[$0]) != nil }
                var ok = s.at != nil && counted && (g["files"] == nil || g["files"] is [Any])
                    && pauseText(s, to).contains(to) && acts.last == .stop && !acts.contains(.resume)
                    && s.machine != nil
                switch s.reason {
                case "changed":
                    ok = ok && s.changed + s.new + s.removed + s.history > 0 && acts.first == .bring
                        && !pauseCounts(s).isEmpty
                        && s.files.prefix(6).allSatisfy { replaceAsk(s, "p", to).body.contains($0) }
                case "removals":
                    ok = ok && s.removed > 0 && acts.first == .allow
                        && removalsAsk(s, "p", to).title.contains(removalsCount(s))
                        && (s.total == 0 || pauseText(s, to).contains("\(s.removed) of the \(s.total) files"))
                        && s.files.prefix(6).allSatisfy { removalsAsk(s, "p", to).body.contains($0) }
                default:
                    ok = ok && acts.first == .replace && g.keys.contains("marker")
                        && s.files.prefix(6).allSatisfy { replaceAsk(s, "p", to).body.contains($0) }
                        && (Swift.max(s.total, s.files.count) == 0
                            || pauseText(s, to).contains(fileCount(Swift.max(s.total, s.files.count))))
                }
                if !ok { miss.append(n) }
            }
            // a `mirror --run --json` answer: its paused rows count as paused, not as skipped
            if let rows = (d as? [String: Any])?["mirrored"] as? [[String: Any]] {
                let held = rows.filter { !findPauses($0).isEmpty }
                if held.contains(where: { $0["status"] as? String != "paused" })
                    || (!held.isEmpty && !syncSummary(rows).contains("\(held.count) paused")) {
                    miss.append(n + " (mirrored rows)")
                }
            }
        }
        // Bring Them Here: reclaim in copy mode, with Take Back's plan and
        // remote; the dry run (`reclaim_copy_dry.json`) and --apply, which adds
        // the files changed on both (`done`) and the sync after it (`sync`)
        for (n, applied) in [("reclaim_copy_dry.json", false), ("reclaim_copy.json", true)] {
            guard let rc = sample(n) as? [String: Any] else { continue }
            let pl = (rc["plan"] as? [String: Any])?["project"] as? [String: Any]
            let there = rc["remote"] as? String ?? "?"
            let both = ((rc["conflicts"] as? [String: Any])?["project"] as? [String]) ?? []
            var ok = rc["mode"] as? String == "copy" && pl != nil && rc["remote"] is String
                && rc["applied"] as? Bool == applied
                && ["take", "new", "delete"].allSatisfy { tally(pl?[$0]) != nil }
                && takeBackText(rc, there, copy: true, synced: true).hasPrefix("\(tally(pl?["take"]) ?? -1) file(s) changed there")
                && (rc["conflicts"] == nil || rc["conflicts"] is [String: Any])
                && ((rc["blockers"] as? [String]) ?? []).isEmpty
            if applied {
                let st = (rc["sync"] as? [String: Any])?["status"] as? String
                let said = broughtText(rc, there, now: nil)
                ok = ok && ["synced", "paused", "skipped"].contains(st ?? "")
                    && (st != "synced" || said.contains("Keep in sync with \(there) ran"))
                    && (st != "paused" || said.contains("paused again"))
                    && both.allSatisfy { said.contains($0) }
            }
            if !ok { miss.append(n) }
        }
        // Hand Over over a changed copy: `copy_changed`, and the blocker that
        // --replace-there lifts, so the question (not the note) comes up
        if let hb = sample("handover_blocked.json") as? [String: Any] {
            let g = (hb["copy_changed"] as? [String: Any]) ?? [:]
            let c = changedThere(hb), there = hb["remote"] as? String ?? "box"
            let asked = c.map { changedThereText($0, "api", there) } ?? ""
            if c == nil || !otherBlockers(hb).isEmpty || c?.at == nil || hb["error"] != nil
                || c?.changed != tally(g["changed"]) || c?.new != tally(g["new"])
                || c?.removed != tally(g["removed"]) || c?.history != tally(g["history"])
                || !(c?.files ?? []).prefix(6).allSatisfy({ asked.contains($0) })
                || !(g["conversations"] is [Any]) || asked.isEmpty {
                miss.append("handover_blocked.json")
            }
        }
        // Replace Them and Allow the Removals: the dry run's pause and set-aside
        // folder in the question; --apply's row in the note
        for (n, removals) in [("mirror_replace", false), ("mirror_allow_removals", true)] {
            let there = "box"
            var aside: String?
            if let dry = sample(n + "_dry.json") as? [String: Any] {
                aside = dry["aside"] as? String
                let p = findPauses(dry).first.map(SyncPause.init)
                let ask = p.map { removals ? removalsAsk($0, "api", there, aside: aside)
                                           : replaceAsk($0, "api", there, aside: aside) }
                if p == nil || aside == nil || dry["applied"] as? Bool != false
                    || !((dry["blockers"] as? [String]) ?? []).isEmpty || dry["error"] != nil
                    || !(ask?.body.contains(aside ?? "\u{0}") ?? false)
                    || !(p?.files ?? []).prefix(6).allSatisfy({ ask?.body.contains($0) ?? false })
                    || (removals && !(ask?.title.contains(removalsCount(p!)) ?? false))
                    || !(dry["would"] is [String: Any]) {
                    miss.append(n + "_dry.json")
                }
            }
            if let done = sample(n + "_apply.json") as? [String: Any] {
                let row = ((done["mirrored"] as? [[String: Any]]) ?? []).first ?? [:]
                let said = replacedText(done, "api", there, removals: removals, aside: aside, now: nil)
                let swapped = tally(row["replaced"]) ?? -1, gone = tally(row["removed"]) ?? -1
                if done["applied"] as? Bool != true || row["status"] as? String != "synced"
                    || swapped < 0 || gone < 0 || !(row["ended_pause"] is String)
                    || (swapped > 0 && !said.contains(fileCount(swapped) + " replaced"))
                    || (gone > 0 && !said.contains(fileCount(gone) + " removed"))
                    || said.contains("still paused") {
                    miss.append(n + "_apply.json")
                }
            }
        }
        // the removals Replace Them and Bring Them Here name (`removals`), once
        // the samples have it: its shape, and the question that names them
        var withRemovals: [String] = []
        for n in ["mirror_replace_dry.json", "mirror_allow_removals_dry.json", "reclaim_copy_dry.json"] {
            guard let d = sample(n) as? [String: Any], let g = d["removals"] else { continue }
            withRemovals.append(n)
            let r = g as? [String: Any] ?? [:]
            let gone = Removals(g)
            var ok = tally(r["removed"]) != nil && tally(r["total"]) != nil && r["files"] is [Any]
                && r["over"] is Bool && (tally(r["removed"]) == 0) == (gone == nil)
            if let gone = gone, !n.hasPrefix("mirror_allow") {
                // Bring Them Here names them only over the limit: as if they were
                let text = n.hasPrefix("reclaim")
                    ? takeBackText(d.merging(["removals": r.merging(["over": true]) { $1 }]) { $1 }, "box",
                                   copy: true, synced: true)
                    : replaceAsk(findPauses(d).first.map(SyncPause.init) ?? SyncPause(["reason": "changed"]), "api", "box",
                                 removals: gone).body
                ok = ok && gone.files.prefix(6).allSatisfy { text.contains($0) } && text.contains(gone.counted)
            }
            if !ok { miss.append(n + " (removals)") }
        }
        print("PHASE 5 REMOVALS KEY " + (withRemovals.isEmpty ? "not in the samples yet"
                                          : "in " + withRemovals.joined(separator: ", ")))
        // Keep All Projects in Sync: the copies of other machines' projects stay out
        if let all = sample("mirror_all_on.json") as? [String: Any] {
            let copies = all["copies_skipped"] as? [String]
            let note = syncAllNote(held: 0, copies: copies ?? [])
            if copies == nil || copies!.isEmpty
                || !copies!.prefix(3).allSatisfy({ note.contains(($0 as NSString).lastPathComponent) })
                || !(all["projects"] is [[String: Any]]) {
                miss.append("mirror_all_on.json")
            }
        }
        // projects: a copy from another machine names it; a pause that asks parses
        if let pj = sample("projects.json") as? [String: Any] {
            let rows = sampleRows(pj)
            let copies = rows.filter { $0["copy_of"] is [String: Any] }
            if copies.isEmpty { miss.append("projects.json (no row with copy_of)") }
            if !rows.contains(where: { !findPauses($0["mirror_paused"]).isEmpty }) {
                miss.append("projects.json (no row with mirror_paused)")
            }
            if rows.contains(where: { $0["mirror"] is [String: Any] }) {
                miss.append("projects.json (mirror is a record, not the machine's name)")
            }
            for r in copies {
                let g = r["copy_of"] as? [String: Any] ?? [:]
                guard let c = Project(r).copyOf else { miss.append("projects.json (copy_of)"); continue }
                if c.from != g["from"] as? String || !["sync", "handover", "brought", "returned"].contains(c.kind)
                    || !copyLine(c).contains(c.from) {
                    miss.append("projects.json (copy_of)")
                }
            }
            for r in rows where !findPauses(r["mirror_paused"]).isEmpty {
                let p = Project(r)
                if p.syncPaused?.asks != true || p.sync != "paused" || p.mirror == nil
                    || (p.away == nil && pausedWith([p], p.syncPaused?.machine ?? p.mirror ?? "").isEmpty) {
                    miss.append("projects.json (mirror_paused)")
                }
            }
        }
        miss = miss.filter { !miss.contains($0 + " (missing)") && !miss.contains($0 + " (not JSON)") }
        phase5OK = miss.isEmpty
        print("PHASE 5 SAMPLES \(phase5OK ? "OK" : "FAIL \(miss)") — \(dir5)")
    } else {
        print("PHASE 5 SAMPLES not checked (" + (dir5.isEmpty ? "AHT_FIXTURES_PHASE5 names no folder"
                                                       : "no samples in \(dir5) yet") + ")")
    }
    // Phase 6: what copies files to and from each machine (`handover_transfer`,
    // and `remote check --json`'s `transfer`), as Settings and Machines say it
    let ms6 = machinesFrom(["box": ["ssh": "me@box", "system": "Linux"], "pc": ["ssh": "me@pc", "system": "Windows"],
                            "studio": ["ssh": "me@studio", "system": "Darwin"]])
    let said6 = checkTransfers(["machines": [["remote": "box", "transfer": "rsync", "checks": [Any]()],
                                             ["remote": "studio", "transfer": "aht"],
                                             ["remote": "mini", "error": "cannot reach mini"],
                                             ["remote": "odd", "transfer": "scp"]]])
    let known6 = said6.mapValues { Mover(mode: "auto", transfer: $0) }
    let unasked6 = moversText(ms6, mode: "auto", hereRsync: "3.2.7", known: [:])
    let asked6 = moversText(ms6, mode: "auto", hereRsync: "3.2.7", known: known6)
    let aht6 = moversText(ms6, mode: "aht", hereRsync: "3.2.7", known: known6)
    let rsync6 = moversText(ms6, mode: "rsync", hereRsync: "3.2.7", known: known6)
    let none6 = moversText(ms6, mode: "auto", hereRsync: nil, known: [:])
    let am6 = AppModel()
    am6.demo = true
    am6.status = ["handover": ["supported": true, "rsync": "3.2.7",
                               "remotes": ["box": ["ssh": "me@box", "system": "Linux"]]]]
    am6.movers = ["box": Mover(mode: "auto", transfer: "aht")]
    am6.config = ["handover_transfer": "rsync"]
    let forced6 = (am6.transferMode, am6.checkedMover("box"), am6.moversLine)
    am6.config = ["handover_transfer": "zip"]
    let odd6 = (am6.transferMode, am6.checkedMover("box"), am6.moversLine)
    let transferOK = said6 == ["box": "rsync", "studio": "aht"]
        && unasked6 == "box: rsync if it has it, else aht's own copy · pc: aht's own copy · studio: rsync if it has it, else aht's own copy"
        && asked6 == "box: rsync · pc: aht's own copy · studio: aht's own copy"
        && aht6 == "box: aht's own copy · pc: aht's own copy · studio: aht's own copy"
        && rsync6 == "box: rsync · pc: rsync · studio: rsync"
        && none6 == aht6 && moversText(ms6, mode: "auto", hereRsync: "2.6.9", known: [:]) == aht6
        && saysTransfer(Check(name: "copies files with", ok: true, needed: false, detail: "rsync", fix: nil))
        && TRANSFER_CHOICES.map { $0.0 } == ["auto", "rsync", "aht"]
        && forced6.0 == "rsync" && forced6.1 == nil && forced6.2 == "box: rsync"
        && odd6.0 == "auto" && odd6.1 == "aht" && odd6.2 == "box: aht's own copy"
    print("COPIES FILES WITH \(transferOK ? "OK" : "FAIL — \(said6) / \(unasked6) / \(asked6) / \(rsync6) / \(forced6) / \(odd6)")")
    // … and the core's phase-6 samples: AHT_FIXTURES_PHASE6 (remote_check*.json)
    var phase6OK = true
    let dir6 = ProcessInfo.processInfo.environment["AHT_FIXTURES_PHASE6"] ?? ""
    let checks6 = ((try? FileManager.default.contentsOfDirectory(atPath: dir6)) ?? [])
        .filter { $0.hasPrefix("remote_check") && $0.hasSuffix(".json") }.sorted()
    if !dir6.isEmpty && !checks6.isEmpty {
        var miss: [String] = []
        for n in checks6 {
            let data = try? Data(contentsOf: URL(fileURLWithPath: dir6).appendingPathComponent(n))
            guard let d = data.flatMap({ try? JSONSerialization.jsonObject(with: $0) }) as? [String: Any] else {
                miss.append(n + " (not JSON)")
                continue
            }
            // every machine that answered says what copies its files
            let answered = ((d["machines"] as? [[String: Any]]) ?? [])
                .filter { $0["error"] == nil || $0["error"] is NSNull }.compactMap { $0["remote"] as? String }
            let got = checkTransfers(d)
            if answered.isEmpty || answered.contains(where: { got[$0] == nil }) { miss.append(n + " (transfer)") }
            if checkRows(d).rows.isEmpty { miss.append(n + " (checks)") }
        }
        // a fetch that ended with 1 over some files (`problems`): the rest came
        let fetch6 = URL(fileURLWithPath: dir6).appendingPathComponent("backup_fetch_offsite.json")
        if let data = try? Data(contentsOf: fetch6) {
            let d = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            let n = d?["files"] as? Int ?? 0
            let probs = (d?["problems"] as? [[String: Any]]) ?? []
            let f = OffsiteFolder(id: "x", name: "pc", system: "Windows", updated: nil, projects: 1,
                                  files: 1, bytes: 1, mine: false, legacy: false)
            let said = fetchedText(fetchAnswered(false, d) ? d : nil, f, said: "")
            if probs.isEmpty || !said.hasPrefix(n == 0 ? "Nothing was fetched from" : "Fetched \(n) backup(s)")
                || probs.prefix(10).contains(where: { !said.contains("• \($0["name"] as? String ?? "?") — ") }) {
                miss.append("backup_fetch_offsite.json")
            }
        }
        phase6OK = miss.isEmpty
        print("PHASE 6 SAMPLES \(phase6OK ? "OK" : "FAIL \(miss)") — \(dir6)")
    } else {
        print("PHASE 6 SAMPLES not checked (" + (dir6.isEmpty ? "AHT_FIXTURES_PHASE6 names no folder"
                                                       : "no remote_check samples in \(dir6) yet") + ")")
    }
    // Phase 7: Bring Here, Send Back, folders at other paths, names across
    // systems: the core's JSON shapes through the app's own readers
    let list7 = thereProjects(["projects": [
        ["path": "/home/me/code/api", "open": "working", "last_activity": "2026-10-27T18:00:00"],
        ["path": "C:\\Users\\me\\code\\shop", "title": "Checkout", "last_activity": "2026-10-28T09:10:00",
         "here_path": "/Users/me/code/shop"],
        ["path": "/home/me/code/site", "away": ["host": "studio"], "last_activity": "2026-10-20T10:00:00"]]])
    let names7 = nameProblems(["names": [
        ["kind": "case", "count": 2, "names": [["README.md", "readme.md"], ["a.txt", "A.txt"]]],
        ["kind": "reserved", "names": ["aux.md"]], ["kind": "chars", "count": 0, "names": [Any]()]]])
    let fix7 = fixIn("aht moves projects between the home folders of your machines. D:\\work\\shop is outside "
                     + "yours. Tell aht where such projects go on mac: `aht remote paths mac --add D:\\work /Users/me/work`.")
    let fix7b = fixIn("on mac, /Users/me/code/shop holds another folder (412 files). Move it away there, or "
                      + "choose another place: `aht remote paths mac --home`")
    let fix7c = fixIn("a handover has not finished; release it to work on it here:  aht reclaim /x --release")
    let fix7d = fixIn("Tell aht where projects from box go, or bring it with --here PATH:  aht remote paths box "
                      + "--add /home/me/x ~/x   (swap the two: HERE first)")
    let listOK = list7.map { $0.name } == ["shop", "api", "site"]
        && list7.map { thereState($0) ?? "-" } == ["-", "a session is working in it there", "on studio now"]
        && list7[0].here == "/Users/me/code/shop" && list7[0].title == "Checkout"
    let nameKindsOK = names7.count == 2 && names7[0].names == ["README.md and readme.md", "a.txt and A.txt"]
        && names7[1].text == "a name Windows reserves" && names7[1].count == 1
        && namesText(names7, on: "pc").contains(
            "\n• two files whose names differ only in capitals (2): README.md and readme.md; a.txt and A.txt\n")
    let fixOK = fix7.fix == "aht remote paths mac --add D:\\work /Users/me/work"
        && fix7.text.hasSuffix("Tell aht where such projects go on mac:")
        && fix7b.fix == "aht remote paths mac --home" && fixIn("install or update aht on mac first").fix == nil
        && fix7c.fix == "aht reclaim /x --release" && fix7c.text.hasSuffix("to work on it here:")
        && fix7d.fix == "aht remote paths box --add /home/me/x ~/x"
        && fix7d.text == "Tell aht where projects from box go, or bring it with --here PATH (swap the two: HERE first):"
    let pc7 = Project(["real_path": "/x/shop", "exists": true, "away": "pc", "away_since": "2026-10-28T14:10:00",
                       "away_driven_by": "there", "away_system": "Windows", "away_remote": NSNull()])
    let box7 = Project(["real_path": "/x/api", "exists": true, "away": ["host": "box", "remote": "box",
                        "driven_by": "there", "system": "Linux", "since": "2026-10-28T14:10:00"]])
    let mine7 = Project(["real_path": "/x/site", "exists": true, "away": "box", "away_remote": "box"])
    let copy7 = Project(["real_path": "/x/blog", "exists": true,
                         "copy_of": ["from": "box", "kind": "brought", "remote": "box"]])
    let given7 = Project(["real_path": "/x/wiki", "exists": true,
                          "copy_of": ["from": "pc", "kind": "handover", "remote": NSNull()]])
    let ms7 = machinesFrom(["box": ["ssh": "me@box", "system": "Linux"], "pc": ["ssh": "me@pc", "system": "Windows"]])
    let rowsOK = awayLine(pc7) == "On pc since \(clock("2026-10-28T14:10:00")) (brought there from pc). "
            + "Send it back from pc."
        && !pc7.canTakeBack && box7.canTakeBack && box7.away == "box" && awayLine(box7) != nil
        && mine7.canTakeBack && awayLine(mine7) == nil && copy7.sendBackTo == "box" && mine7.sendBackTo == nil
        && given7.sendBackTo == "pc" && sendBackBlocked(copy7, ms7) == nil
        && sendBackBlocked(given7, ms7)?.hasPrefix("pc is not set up on this Mac") == true
        && sendBackBlocked(Project(["real_path": "/x/w", "copy_of": ["from": "pc", "kind": "handover", "remote": "pc"]]),
                           ms7)?.contains("Windows PC") == true
        && Handing(["remote": NSNull(), "host": "pc", "driven_by": "there"]).reachable == false
    let rules7 = pathMap([["D:\\work", "/Users/me/work"]], ["here_home": "C:\\Users\\me", "rules": [
        ["here": "D:\\work", "there": "/Users/me/work", "kind": "pair"],
        ["here": "C:\\Users\\me", "there": "/Users/me", "kind": "home"]]])
    let maps7 = pathMaps(["machines": [
        ["remote": "box", "paths": "same"], ["remote": "pc", "paths": "home", "there_home": "C:\\Users\\me"],
        ["remote": "lab", "paths": [["/data/x", "/srv/x"]]]], "remotes": ["mini": ["paths": "home"]]])
    let mapsOK = maps7.keys.sorted() == ["box", "lab", "mini", "pc"] && maps7["lab"]?.pairs == [["/data/x", "/srv/x"]]
        && maps7["pc"].map { pathMapText($0, machine: "pc") }
            == "Folders: home to home: ~/code/shop here is C:\\Users\\me\\code\\shop on pc"
        && maps7["box"].map { pathMapText($0, machine: "box") } == "Folders: the same paths on box as here"
        && machinesFrom(["lab": ["ssh": "me@lab", "paths": [["/a", "/b"]]]]).first?.paths?.mode == "pairs"
        && rules7.map { pathMapText($0, machine: "mac") }
            == "Folders here → on mac: D:\\work → /Users/me/work · C:\\Users\\me → /Users/me (home)"
    let eol7 = eolText(["eol_only": ["a.txt", "b.sh", "c.md", "d.py"]], keeper: "box") ?? ""
    let hint7 = [gitattributesHint(["git": ["is_git": true, "gitattributes": false, "suggest": GITATTRIBUTES_LINES]]),
                 gitattributesHint(["git": ["is_git": true, "gitattributes": true, "suggest": [Any]()]]),
                 gitattributesHint(["git": ["suggest": ["* text=auto"]]]), gitattributesHint([:])]
    let how7 = gitNote(["git": ["how": "in your own terminal on box:  git -c core.filemode=false status   "
                                + "(aht's session there has this set)"]])
    let notesOK = eol7.hasPrefix("4 files differ only in line endings: the ones on box stay as they are (a.txt")
        && hint7[0] == GITATTRIBUTES_LINES && hint7[1] == nil && hint7[2] == ["* text=auto"] && hint7[3] == nil
        && unsafeText(["unsafe_names": [["there": "a:b.txt", "kept_as": "/x/aside/a%3Ab.txt"]]], receiver: "this Mac")
            == "Kept aside: 1 file whose name this Mac cannot hold: a:b.txt (as a%3Ab.txt)"
        && how7?.fix == "git -c core.filemode=false status"
        && how7?.text == "For git in your own terminal on box (aht's session there has this set):"
        && gitNote(["git": ["how": NSNull()]]) == nil
    var bp7 = BringView(machine: "box")
    bp7.picked = "/home/me/code/shop"
    bp7.allowIdle = true
    var sb7 = SendBackView(project: copy7, machine: "box")
    let sbArgs7 = sendBackArgs(sb7)
    sb7.preferHere = true
    let argsOK = bringArgs(bp7) == ["bring", "/home/me/code/shop", "--from", "box", "--allow-idle", "--json"]
        && bringArgs(bp7, apply: true).suffix(2) == ["--apply", "--json"]
        && sbArgs7 == ["send-back", "/x/blog", "--json"] && !bringReady(bp7) && !sendBackReady(sb7)
        && sendBackArgs(sb7, apply: true) == ["send-back", "/x/blog", "--prefer", "here", "--apply", "--json"]
    let blocksOK = crossingBlocks(["names": [["kind": "reserved", "names": ["aux.md"]]]])
        && crossingBlocks(["blockers": ["Move it away there: `aht remote paths mac --home`"]])
        && !crossingBlocks(["blockers": ["a session is open"]])
        && blockerLines(["names": [["kind": "reserved", "names": ["aux.md"], "text": "a name Windows reserves"]],
                         "blockers": ["1 name: a name Windows reserves (aux.md)", "x"], "error": "y"]) == ["x", "y"]
        && idleBlock(["blockers": ["an idle session is open there; pass --allow-idle"]])
        && versionBlock(["blockers": ["a newer Claude Code wrote here (--ignore-version)"]])
    let bringOK = listOK && nameKindsOK && fixOK && rowsOK && mapsOK && notesOK && argsOK && blocksOK
    print("BRING HERE AND SEND BACK \(bringOK ? "OK" : "FAIL — list \(listOK) names \(nameKindsOK) fix \(fixOK) rows \(rowsOK) maps \(mapsOK) notes \(notesOK) args \(argsOK) blocks \(blocksOK)")")
    // Phase 7's fix round. (1) Leave Them Out: this app has no such button;
    // it lists the names and says to rename them or set handover_excludes.
    // (2) the identity fix is the core's `identity.fix`, copied whole, also
    // where the sentence would mislead a reading of it
    let idFix7 = "aht bring /x/a --from mac --here '/Users/me/a:  b-mac'"
    let idSaid7 = "here, /Users/me/a:  b holds another folder (3 items). Move it away, or bring it to another place:  " + idFix7
    let idOn7 = blockerFix(idSaid7, ["identity": ["ok": false, "fix": idFix7]])
    let idOK = idOn7.fix == idFix7
        && idOn7.text == "here, /Users/me/a:  b holds another folder (3 items). Move it away, or bring it to another place:"
        && fixIn(idSaid7).fix != idFix7
        && blockerFix(idSaid7, ["identity": ["ok": true, "fix": NSNull()]]).fix == fixIn(idSaid7).fix
        && identityFix(["identity": ["ok": true, "fix": NSNull()]]) == nil
        && crossingBlocks(["identity": ["ok": false, "fix": idFix7], "blockers": [idSaid7]])
        && blockerFix("install or update aht on mac first", ["identity": ["fix": idFix7]]).fix == nil
    print("IDENTITY FIX FROM identity.fix \(idOK ? "OK" : "FAIL — \(idOn7)")")
    // (3) a project a PC handed over here: no Send Back, "take it back on pc"
    let pcCopy7 = Project(["real_path": "/x/pcwork", "exists": true,
                           "copy_of": ["from": "DESKTOP-PC", "kind": "handover", "remote": "pc", "system": "Windows"]])
    let boxCopy7 = Project(["real_path": "/x/boxwork", "exists": true,
                            "copy_of": ["from": "box", "kind": "brought", "remote": "box", "system": "Linux"]])
    let pcHomeOK = pcCopy7.copyOf?.pcHome == true && boxCopy7.copyOf?.pcHome == false
        && copyLine(pcCopy7.copyOf!) == "Handed over from DESKTOP-PC: take it back on pc"
        && copyLine(boxCopy7.copyOf!) == "Brought here from box: Send Back returns it"
        && sendBackBlocked(pcCopy7, [])?.hasSuffix("take it back on pc") == true
        && sendBackBlocked(boxCopy7, ms7) == nil && copy7.copyOf?.pcHome == false
    print("SEND BACK NOT FOR A PC'S PROJECT \(pcHomeOK ? "OK" : "FAIL — \(copyLine(pcCopy7.copyOf!))")")
    // (4) a Bring Here the other machine drives: aht waits, Release after an hour
    let began7 = Date().addingTimeInterval(-600)
    let wait7 = handingWaitText(Handing(["holder": "pc", "host": "DESKTOP-PC", "remote": NSNull(), "driven_by": "there",
                                         "since": began7.timeIntervalSince1970, "state": "checking"]))
    let late7 = handingWaitText(Handing(["holder": "pc", "driven_by": "there", "state": "unreachable", "release": true]))
    let waitOK = wait7 == "When pc finishes, the project shows as on pc. aht waits for pc; Release is offered after an hour (at "
            + clock(began7.addingTimeInterval(3600)) + ")."
        && late7.hasPrefix("pc did not finish. Release lets the project go on here") && !wait7.contains("asks")
    print("BRING HERE BY THE OTHER MACHINE: WAITS \(waitOK ? "OK" : "FAIL — \(wait7) | \(late7)")")
    let fix7OK = idOK && pcHomeOK && waitOK
    // … and the core's phase-7 samples: AHT_FIXTURES_PHASE7
    var phase7OK = true
    let dir7 = ProcessInfo.processInfo.environment["AHT_FIXTURES_PHASE7"] ?? ""
    let files7 = ((try? FileManager.default.contentsOfDirectory(atPath: dir7)) ?? []).filter { $0.hasSuffix(".json") }
    if !dir7.isEmpty && !files7.isEmpty {
        let want7 = ["bring_list.json", "bring_dry.json", "bring_apply.json", "send_back_dry.json",
                     "send_back_apply.json", "remote_paths.json", "handover_blocked_names.json", "projects.json"]
        var miss: [String] = [], seen: [String] = []
        for n in want7 where files7.contains(n) {
            let data = try? Data(contentsOf: URL(fileURLWithPath: dir7).appendingPathComponent(n))
            guard let d = data.flatMap({ try? JSONSerialization.jsonObject(with: $0) }) as? [String: Any] else {
                miss.append(n + " (not JSON)")
                continue
            }
            var wrong = false
            switch n {
            case "bring_list.json":
                let rows = thereProjects(d)
                wrong = rows.isEmpty || rows.contains { $0.path == "?" || $0.name.isEmpty }
                seen.append("\(rows.count) there")
            case "bring_dry.json", "send_back_dry.json":
                let t = n == "bring_dry.json" ? bringText(d, machine: "box") : sendBackText(d, machine: "box")
                wrong = firstText(d["here_path"]) == nil || firstText(d["there_path"]) == nil
                    || t.contains("<null>") || t.contains("Optional(")
                    || (n == "send_back_dry.json" && !(d["plan"] is [String: Any]))
            case "bring_apply.json", "send_back_apply.json":
                let t = n == "bring_apply.json" ? bringDoneText(d, machine: "box") : sendBackDoneText(d, machine: "box")
                wrong = d["applied"] as? Bool != true || !(t.hasPrefix("Brought here from box") || t.hasPrefix("Sent back:"))
                    || t.contains("<null>") || t.contains("Optional(")
            case "remote_paths.json":
                let maps = pathMaps(d)
                wrong = maps.isEmpty
                seen.append("paths " + maps.keys.sorted().map { "\($0): \(maps[$0]?.mode ?? "")" }.joined(separator: ", "))
            case "handover_blocked_names.json":
                let ps = nameProblems(d)
                let fixes = blockerLines(d).compactMap { blockerFix($0, d).fix }
                wrong = ps.isEmpty || !crossingBlocks(d) || ps.contains { $0.text.isEmpty || $0.names.isEmpty }
                    || identityFix(d) == nil || fixes != [identityFix(d)!]
                seen.append("names " + ps.map { $0.kind }.joined(separator: ",") + ", fix " + (fixes.first ?? "none"))
            default:
                let rows = sampleRows(d).map(Project.init)
                let held = rows.filter { awayLine($0) != nil }.count
                let brought = rows.filter { $0.sendBackTo != nil }.count
                wrong = held + brought == 0
                seen.append("\(held) held there, \(brought) brought here")
            }
            if wrong { miss.append(n) }
        }
        let absent7 = want7.filter { !files7.contains($0) }
        phase7OK = miss.isEmpty
        print("PHASE 7 SAMPLES \(phase7OK ? "OK" : "FAIL \(miss)") — \(dir7) [" + seen.joined(separator: "; ") + "]"
              + (absent7.isEmpty ? "" : " (not there yet: " + absent7.joined(separator: ", ") + ")"))
    } else {
        print("PHASE 7 SAMPLES not checked (" + (dir7.isEmpty ? "AHT_FIXTURES_PHASE7 names no folder"
                                                       : "no samples in \(dir7) yet") + ")")
    }
    // Phase 7b: the permission level follows the work. The core's `perm`
    // ({agent, level, sandbox, flags, from, read, text}) through the app's
    // reader and words: its text as given, the no-exact-match note, the
    // flags; Pick Up's level of the session there; Settings' Codex never-ask
    // choice as agent_permission_flags
    let leaving7b = { (a: String?) in "the \(a.map { $0 + " " } ?? "")session you are leaving" }
    func words7b(_ perm: Any?, _ agent: String, _ extra: [String: Any] = [:], source: String? = "claude",
                 setting: String = "follow") -> (line: String, fell: String?, flags: String)? {
        var d = extra
        d["perm"] = perm
        return permInfo(d, agent: agent, setting: setting).map { permWords($0, agent: agent, source: source, leaving: leaving7b) }
    }
    func perm7(_ agent: String, _ level: String, _ read: String, _ flags: [Any], _ text: String? = nil,
               _ extra: [String: Any] = [:]) -> [String: Any] {
        var d: [String: Any] = ["agent": agent, "level": level, "sandbox": false, "flags": flags, "from": "command_line",
                                "read": read]
        if let t = text { d["text"] = t }
        return d.merging(extra) { $1 }
    }
    let neverP = perm7("codex", "never", "never", ["--dangerously-bypass-approvals-and-sandbox"],
                       "Codex starts in never-ask mode, like the Claude Code session you are leaving")
    let kimiT = "Kimi Code starts in ask mode, the next stricter level: it has no edits mode (the Claude Code session you "
        + "are leaving runs in edits mode)"
    let capT = "Codex starts in auto mode: agent_permissions caps it there (the Claude Code session you are leaving runs "
        + "in never-ask mode)"
    let sbxT = "Claude Code on box starts in never-ask mode inside its sandbox, like the session here"
    let w7b = [
        words7b(neverP, "codex"),
        words7b(perm7("kimi", "ask", "edits", [], kimiT), "kimi"),
        words7b(perm7("codex", "auto", "never", ["-a", "on-request"], capT), "codex", setting: "max:auto"),
        words7b(perm7("claude", "never", "never", ["--dangerously-skip-permissions", "--settings", "{\"sandbox\":{\"enabled\":true}}"],
                      sbxT, ["sandbox": true]), "claude"),
        words7b(perm7("kimi", "auto", "never", ["--yolo"]), "kimi"),
        words7b(perm7("codex", "never", "never", CODEX_SANDBOXED, nil, ["sandbox": true]), "codex"),
        words7b(perm7("claude", "never", "never", ["x"], "x"), "codex"),
        words7b(nil, "codex", ["source": ["agent": "claude", "perm": ["level": "never", "sandbox": false, "from": "command_line"]]],
                source: "claude"),
        words7b(neverP, "kimi", ["perms": ["kimi": perm7("kimi", "never", "never", ["--auto"], "Kimi Code starts in never-ask mode, "
                                                                                              + "like the Claude Code session on box")]])]
    let want7b: [(String, String?, String)?] = [
        ("Codex starts in never-ask mode, like the Claude Code session you are leaving", nil,
         "It never asks: every edit and command runs. Flags: --dangerously-bypass-approvals-and-sandbox"),
        (kimiT, "No exact match: Kimi Code starts in the next stricter level it has.",
         "It asks before it acts, as it does by default. No flags: Kimi Code's own default."),
        (capT, nil, "Routine steps run without asking; risky ones ask first. Flags: -a on-request"),
        (sbxT, nil, "It never asks: every edit and command runs. Flags: --dangerously-skip-permissions --settings "
            + "'{\"sandbox\":{\"enabled\":true}}'"),
        ("Kimi Code starts in auto mode, the next stricter level it has (the Claude Code session you are leaving runs in "
            + "never-ask mode).", "No exact match: Kimi Code starts in the next stricter level it has.",
         "Routine steps run without asking; risky ones ask first. Flags: --yolo"),
        ("Codex starts in never-ask mode inside its sandbox, like the Claude Code session you are leaving.", nil,
         "It never asks: every edit and command runs. Flags: -a never -s workspace-write"),
        nil,
        ("The Claude Code session you are leaving runs in never-ask mode: Codex starts in its own equivalent, or the next "
            + "stricter level it has.", nil, "It never asks: every edit and command runs. Codex gets its own flags for it."),
        ("Kimi Code starts in never-ask mode, like the Claude Code session on box", nil,
         "It never asks: every edit and command runs. Flags: --auto")]
    var bad7b: [String] = []
    for (i, w) in w7b.enumerated() {
        let want = want7b[i]
        if (w == nil) != (want == nil) || (w != nil && (w!.line != want!.0 || w!.fell != want!.1 || w!.flags != want!.2)) {
            bad7b.append("\(i): \(w.map { "\($0.line) | \($0.fell ?? "-") | \($0.flags)" } ?? "nil")")
        }
    }
    let none7bOK = words7b(nil, "codex") == nil && words7b(["level": "bogus"], "codex") == nil
        && words7b("never", "codex") == nil && permInfo(["perm": neverP], agent: nil)?.flags == neverP["flags"] as? [String]
    let on7b = permInfo(["perm": perm7("claude", "never", "never", ["--dangerously-skip-permissions"])], agent: "claude")
        .map { permWords($0, agent: "claude", source: "claude", on: "box",
                         leaving: { "the \($0.map { $0 + " " } ?? "")session here" }).line }
    let set7bOK = permSetting([:]) == "follow" && permSetting(["agent_permissions": "max:auto"]) == "max:auto"
        && permSetting(["agent_permissions": "never"]) == "never" && permSetting(["agent_permissions": "max:x"]) == "follow"
        && codexNever([:]) == "full"
        && codexNever(["agent_permission_flags": ["codex": ["never": CODEX_SANDBOXED]]]) == "sandbox"
        && codexNever(["agent_permission_flags": ["codex": ["never": ["--sandbox", "read-only"]]]]) == "own"
    let on7 = withCodexNever(["agent_permission_flags": ["kimi": ["never": ["--auto"]]]], sandbox: true)
    let off7 = withCodexNever(["agent_permission_flags": ["codex": ["never": CODEX_SANDBOXED, "auto": ["-a", "on-request"]],
                                                         "kimi": ["never": ["--auto"]]]], sandbox: false)
    let gone7 = withCodexNever(["agent_permission_flags": ["codex": ["never": CODEX_SANDBOXED]]], sandbox: false)
    let flags7bOK = ((on7["codex"] as? [String: Any])?["never"] as? [String]) == CODEX_SANDBOXED
        && ((on7["kimi"] as? [String: Any])?["never"] as? [String]) == ["--auto"]
        && (off7["codex"] as? [String: Any])?.keys.sorted() == ["auto"] && off7["kimi"] != nil && gone7.isEmpty
        && shellWord("{\"sandbox\":{\"enabled\":true}}") == "'{\"sandbox\":{\"enabled\":true}}'" && shellWord("--x=1") == "--x=1"
    let perm7bOK = bad7b.isEmpty && none7bOK && set7bOK && flags7bOK
        && on7b == "Claude Code on box starts in never-ask mode, like the Claude Code session here."
    print("PERMISSION LEVEL \(perm7bOK ? "OK" : "FAIL — words \(bad7b) none \(none7bOK) settings \(set7bOK) flags \(flags7bOK) \(on7b ?? "-")")")
    // … and the core's phase-7b samples: AHT_FIXTURES_PHASE7B (every answer
    // with `perm`, through the reader and the words; a config with
    // agent_permission_flags through Settings' reader)
    var phase7bOK = true
    let dir7b = ProcessInfo.processInfo.environment["AHT_FIXTURES_PHASE7B"] ?? ""
    let files7b = ((try? FileManager.default.contentsOfDirectory(atPath: dir7b)) ?? []).filter { $0.hasSuffix(".json") }.sorted()
    if !dir7b.isEmpty && !files7b.isEmpty {
        var miss: [String] = [], seen: [String] = []
        for n in files7b {
            let data = try? Data(contentsOf: URL(fileURLWithPath: dir7b).appendingPathComponent(n))
            guard let d = data.flatMap({ try? JSONSerialization.jsonObject(with: $0) }) as? [String: Any] else {
                miss.append(n + " (not JSON)")
                continue
            }
            if let cfg = (d["effective"] as? [String: Any]) ?? (d["agent_permission_flags"] != nil ? d : nil) {
                seen.append("\(n): settings \(permSetting(cfg)), Codex \(codexNever(cfg))")
                continue
            }
            // a dry run's level: `perm` (null for Summary Only), `perms`, or Pick
            // Up's `source.perm` (the session there) without --open
            guard d["perm"] is [String: Any] || d["perms"] is [String: Any]
                    || (d["source"] as? [String: Any])?["perm"] is [String: Any] else { continue }
            let agent = firstText((d["perm"] as? [String: Any])?["agent"], d["target"], d["agent"]) ?? "claude"
            guard let p = permInfo(d, agent: agent, setting: "follow") else {
                miss.append(n + " (perm unread)")
                continue
            }
            let w = permWords(p, agent: agent, source: firstText((d["source"] as? [String: Any])?["agent"]),
                              leaving: leaving7b)
            let all = w.line + (w.fell ?? "") + w.flags
            if all.contains("Optional(") || all.contains("<null>") || (p.flags == nil && !p.other)
                || ((d["perm"] as? [String: Any]).map { ($0["text"] as? String ?? "").isEmpty } ?? false) { miss.append(n) }
            seen.append("\(n): \(AGENT_LABEL[agent] ?? agent) \(p.level)" + (p.fell ? " (no exact match)" : "")
                        + (p.flags.map { $0.isEmpty ? "" : " " + $0.joined(separator: " ") } ?? ""))
        }
        phase7bOK = miss.isEmpty && !seen.isEmpty
        print("PHASE 7B SAMPLES \(phase7bOK ? "OK" : "FAIL \(miss)") — \(dir7b) [" + seen.joined(separator: "; ") + "]")
    } else {
        print("PHASE 7B SAMPLES not checked (" + (dir7b.isEmpty ? "AHT_FIXTURES_PHASE7B names no folder"
                                                         : "no samples in \(dir7b) yet") + ")")
    }
    // Phase 7b fix round, item 1: Kimi's reading run (-p) is never-ask only,
    // so below it Switch, Hand Back and Pick Up → Open in Kimi open Kimi
    // without it (kimi_reads false) and give the first message to paste
    // (first_prompt); at never-ask Kimi still reads it first
    let kAsk: [String: Any] = ["agent": "kimi", "level": "ask", "sandbox": false, "flags": [Any](), "read": "edits",
                               "from": "transcript", "text": "Kimi Code starts in ask mode, the next stricter level it has"]
    let kNever: [String: Any] = ["agent": "kimi", "level": "never", "sandbox": false, "flags": ["--yolo"], "read": "never",
                                 "from": "transcript", "text": "Kimi Code starts in never-ask mode, like the Claude Code session"]
    let cAuto: [String: Any] = ["agent": "claude", "level": "auto", "sandbox": false, "flags": ["--permission-mode", "auto"],
                                "read": "auto", "from": "transcript", "text": "Claude Code starts in auto mode"]
    let swK: [String: Any] = ["target": "kimi", "mode": "new", "source": ["agent": "claude", "title": "fix the login redirect"],
                              "perm": kAsk, "kimi_reads": false]
    let swKdone = swK.merging(["applied": true, "brief": "/x/paper/.aht/handover/relay-1.md",
                               "first_prompt": "  Read .aht/handover/relay-1.md first.  "]) { $1 }
    let swKnever = swK.merging(["perm": kNever, "kimi_reads": true]) { $1 }
    let puK: [String: Any] = ["target": "claude", "mode": "new", "perm": cAuto, "perms": ["kimi": kAsk],
                              "source": ["agent": "claude", "title": "add the search page",
                                         "perm": ["level": "auto", "sandbox": false, "from": "transcript"]],
                              "match": ["path": "/home/me/code/paper", "how": "id"], "kimi_reads": true]
    let reads1 = !kimiReads(swK) && !kimiReads(["target": "kimi", "perm": kAsk]) && kimiReads(swKnever)
        && kimiReads(["target": "kimi", "perm": kNever]) && kimiReads([:]) && kimiReads(["target": "kimi", "kimi_reads": true])
        && kimiReads(["target": "codex", "kimi_reads": false, "perm": cAuto.merging(["agent": "codex"]) { $1 }])
        && !kimiReads(puK)          // its kimi_reads speaks of Claude Code, the agent planned: Kimi's own level tells
    let first1 = kimiFirst(swKdone) == "Read .aht/handover/relay-1.md first." && kimiFirst(swK) == nil
        && kimiFirst(["kimi_reads": true, "first_prompt": "x"]) == nil && kimiFirst(["kimi_reads": false, "first_prompt": " "]) == nil
    let swT = switchText(swK, mode: "new", hook: true), swTn = switchText(swKnever, mode: "new", hook: true)
    let backT = switchText(swK.merging(["mode": "back"]) { $1 }, mode: "back", hook: true)
    let doneK = switchDoneText(swKdone, project: "/x/paper")
    let doneN = switchDoneText(swKnever.merging(["applied": true, "brief": "/x/paper/.aht/handover/relay-1.md"]) { $1 }, project: "/x/paper")
    let puT = pickupOpenText(puK, agent: "kimi", machine: "box", hook: true)
    let puC = pickupOpenText(puK, agent: "claude", machine: "box", hook: true)
    let costK = openCost("kimi", back: false, hook: true, machine: "box", kimiReads: false) ?? ""
    let puDone = pickupDoneText(["applied": true, "opened": "kimi", "kimi_reads": false, "first_prompt": "Read it first.",
                                 "brief": "/x/paper/.aht/handover/relay-2.md", "blockers": [Any](), "warnings": [Any]()],
                                machine: "box", project: "/x/paper", copied: false)
    let texts1 = swT.contains(KIMI_OPENS) && !swT.contains("first run of its own") && swTn.contains("first run of its own")
        && !swTn.contains(KIMI_OPENS) && backT.contains(KIMI_OPENS)
        && doneK == "Kimi Code's window is open. The summary is in the project: /x/paper/.aht/handover/relay-1.md"
        && doneN.hasPrefix("Kimi Code took over; its window is open. The summary it read:")
        && puT.contains(KIMI_OPENS) && !puC.contains(KIMI_OPENS)
        && costK.contains("paste the first message aht shows you into Kimi") && !costK.contains("run of its own")
        && (openCost("kimi", back: false, hook: true, machine: "box") ?? "").contains("run of its own")
        && puDone == "Picked up from box: Kimi Code is open here. The summary is here: /x/paper/.aht/handover/relay-2.md."
    // … and the core's samples that say kimi_reads (AHT_FIXTURES_PHASE7B)
    var kimiSeen: [String] = [], kimiBad: [String] = []
    for n in files7b {
        guard let data = try? Data(contentsOf: URL(fileURLWithPath: dir7b).appendingPathComponent(n)),
              let d = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any], let r = d["kimi_reads"] as? Bool else { continue }
        let ok = r ? kimiFirst(d) == nil : kimiFirst(d) != nil && !switchDoneText(d, project: "/x/p").contains("it read")
        kimiSeen.append("\(n): kimi_reads \(r)" + (kimiFirst(d) != nil ? ", first_prompt" : ""))
        if !ok || kimiReads(d) != r { kimiBad.append(n) }
    }
    let kimi7bOK = reads1 && first1 && texts1 && kimiBad.isEmpty
    print("KIMI BELOW NEVER-ASK \(kimi7bOK ? "OK" : "FAIL — reads \(reads1) first \(first1) texts \(texts1) samples \(kimiBad)")"
          + (kimiSeen.isEmpty ? " (no sample says kimi_reads yet)" : " [" + kimiSeen.joined(separator: "; ") + "]"))
    if !texts1 { print("   \(swT.suffix(160)) | \(doneK) | \(puT.suffix(160)) | \(costK) | \(puDone)") }
    // item 2: the second opinion's level before Start, from its dry run
    let dryO: [String: Any] = ["project": "/x/paper", "applied": false, "blockers": ["say what both should do (--task)"],
        "warnings": ["Kimi Code is left out: its run on its own works only in never-ask mode"],
        "perms": ["codex": ["agent": "codex", "level": "ask", "sandbox": false, "flags": [Any](), "read": "ask", "from": "transcript",
                            "text": "Codex works in ask mode, like the project's latest session (Claude Code)"],
                  "claude": cAuto.merging(["text": "Claude Code works in auto mode, like the project's latest session (Claude Code)"]) { $1 }]]
    let l0 = opinionLevels(dryO, typed: false), l1 = opinionLevels(dryO, typed: true)
    let leaving2 = { (_: String?) in "the project's latest session" }
    let said2 = l0.agents.compactMap { a in permInfo(dryO, agent: a).map { permWords($0, agent: a, leaving: leaving2).line } }
    var opDryOK = l0.agents == ["claude", "codex"] && l0.blockers.isEmpty && l1.blockers == ["say what both should do (--task)"]
        && l0.warnings == ["Kimi Code is left out: its run on its own works only in never-ask mode"]
        && said2 == ["Claude Code works in auto mode, like the project's latest session (Claude Code)",
                     "Codex works in ask mode, like the project's latest session (Claude Code)"]
        && opinionLevels([:], typed: true).agents.isEmpty && opinionLevels(["perms": ["claude": "x"]], typed: true).agents.isEmpty
        && opinionDryArgs("/x/paper", task: " make it so ") == ["second-opinion", "/x/paper", "--task=make it so", "--dry-run", "--json"]
    var opSeen = "no second_opinion_dry.json yet"
    if let data = try? Data(contentsOf: URL(fileURLWithPath: dir7b).appendingPathComponent("second_opinion_dry.json")),
       let d = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] {
        let l = opinionLevels(d, typed: true)
        let lines = l.agents.compactMap { a in permInfo(d, agent: a).flatMap { $0.text } }
        opDryOK = opDryOK && !l.agents.isEmpty && lines.count == l.agents.count && d["applied"] as? Bool != true
        opSeen = "second_opinion_dry.json: " + l.agents.joined(separator: ", ") + (l.warnings.isEmpty ? "" : ", \(l.warnings.count) warning(s)")
    }
    print("SECOND OPINION LEVEL BEFORE START \(opDryOK ? "OK" : "FAIL \(l0) \(said2)") [\(opSeen)]")
    // Phase 8, another agent on the other machine: Agent there (Hand Over)
    // and Agent here (Bring Here) with their token lines and commands; the
    // board's window statuses; Take Back's --stop refusals in plain words;
    // the away row naming the agent there
    let agents8 = agentsThere([:]) == ["claude", "codex", "kimi", "agy", "vibe"]
        && agentsThere(["agents_there": ["codex"]]) == ["claude", "codex"]
        && agentsThere(["there": ["agents": ["kimi": "/usr/bin/kimi", "agy": NSNull(), "codex": false]]]) == ["claude", "kimi"]
        && agentsHere(["claude", "codex", "agy"]) == ["claude", "codex", "agy"] && agentsHere(["claude"]) == ["claude"]
        && agentChoice("claude") == "Claude Code (its own session)" && agentChoice("agy") == "Antigravity"
    let cost8 = agentCost("claude", on: "box")
            == "Claude Code resumes its own session on box: nothing runs until someone types there, so it uses no tokens."
        && agentCost("claude", on: nil) == "Claude Code's own session opens here: nothing runs until you type, so it uses no tokens."
        && agentCost("claude", on: "box", task: true) == "With a task, Claude Code starts on it at once on box: that uses tokens."
        && agentCost("codex", on: "box") == "Starting Codex on box uses tokens: it reads aht's summary of the work as its first turn."
        && agentCost("agy", on: nil) == "Starting Antigravity here uses tokens: it reads aht's summary of the work as its first turn."
        && agentCost("kimi", on: "box", ["kimi_reads": false]).contains("paste the first message aht shows you into its window there")
        && agentCost("kimi", on: "box", ["kimi_reads": true]).hasPrefix("Starting Kimi Code on box uses tokens")
        // the core's own words (`tokens`), as given, with a full stop
        && agentCost("codex", on: "box", ["tokens": "Codex starts on box and reads the summary as its first turn: that uses tokens"])
            == "Codex starts on box and reads the summary as its first turn: that uses tokens."
        && agentCost("claude", on: "box", ["tokens": NSNull()]).hasPrefix("Claude Code resumes its own session")
        && agentCost("kimi", on: "box", ["first_prompt": "Read it first."]).contains("without reading the summary")
        && farFirst(["first_prompt": "  Read it first. "]) == "Read it first." && farFirst(["first_prompt": NSNull()]) == nil
        && agentStarts("codex", on: "box") == "Codex starts on box with aht's summary of the work"
        && agentStarts("claude", on: "box") == "The session is resumed there"
    let args8 = handoverArgs("/x/api", to: "box") == ["handover", "/x/api", "--json", "--to", "box"]
        && handoverArgs("/x/api", to: "box", agent: "codex") == ["handover", "/x/api", "--json", "--to", "box", "--agent", "codex"]
        && handoverArgs("/x/api", to: "box", replace: true, apply: true, file: "/s.json", task: "fix it")
            == ["handover", "/x/api", "--apply", "--json", "--status-file", "/s.json", "--to", "box", "--replace-there", "--task=fix it"]
        && handoverArgs("/x/api", to: nil, agent: "kimi", apply: true) == ["handover", "/x/api", "--apply", "--json", "--agent", "kimi"]
    var bv8 = BringView(machine: "box")
    bv8.picked = "/home/me/code/shop"
    let bringC8 = bringArgs(bv8)
    bv8.agent = "codex"
    let ses8: [String: Any] = ["session": ["id": "s1", "title": "Checkout"]]
    let bring8 = bringC8 == ["bring", "/home/me/code/shop", "--from", "box", "--json"]
        && bringArgs(bv8, apply: true) == ["bring", "/home/me/code/shop", "--from", "box", "--agent", "codex", "--apply", "--json"]
        && bringText(ses8, machine: "box", agent: "codex").contains("\nCodex starts here with aht's summary of the work (“Checkout”), in a new terminal window.")
        && bringText(ses8, machine: "box").contains("opens here in a new terminal window; nothing runs until you type")
        && bringDoneText(["opened": true], machine: "box", agent: "codex")
            .contains("Codex is open in a new terminal window: it reads aht's summary of the work as its first turn.")
        && bringDoneText(["opened": true], machine: "box").contains("nothing runs until you type")
    let win8 = { (raw: String?, q: Double?, nr: Bool) in windowStatus(raw: raw, quietFor: q, notRunning: nr)?.text }
    let board8 = win8("working", 3, false) == "working" && win8("quiet", 372, false) == "quiet for 6 min"
        && win8("quiet", 30, false) == "quiet for under a minute" && win8("quiet", 7500, false) == "quiet for 2 h"
        && win8("quiet", 7100, false) == "quiet for 118 min" && win8("quiet", nil, false) == "quiet"
        && win8("exited", nil, true) == "exited" && win8("quiet", 40, true) == "not running"
        && windowStatus(raw: "exited", quietFor: nil, notRunning: true)?.hint == nil
        && win8("busy", nil, false) == nil && win8("waiting", nil, false) == nil && win8(nil, nil, false) == nil
        && win8("running", nil, false) == nil
        && windowStatus(raw: "quiet", quietFor: 400, notRunning: false)?.hint == "done, or it waits for you"
    let rows8 = boardMachines(["machines": [["machine": "box", "reachable": true, "sessions": [
        ["agent": "codex", "project": "/home/me/code/api", "status": "running", "window": "aht-api-1a2b3c",
         "raw_status": "quiet", "quiet_for": 372, "not_running": false],
        ["agent": "claude", "project": "/home/me/code/web", "status": "waiting for you", "raw_status": "waiting",
         "window": "aht-web-9f8e7d", "waiting_for": "approve Bash: make test"]]]]]).first?.rows ?? []
    let rowsOK8 = rows8.map { $0.state }.sorted() == ["quiet for 6 min", "waiting for you: approve Bash: make test"]
        && rows8.first { $0.agent == "codex" }?.window == "aht-api-1a2b3c"
    // as the core says them: `stop` {stopped, reason, quiet_for, quit_keys,
    // would_stop, seen}, its sentence in the blockers, the agent's own
    // processes there next to it
    let nq8 = stopRefusal(["remote": "box",
                           "stop": ["stopped": false, "reason": "not-quiet", "quiet_for": 60, "quit_keys": ["C-c", "C-c"],
                                    "would_stop": false],
                           "blockers": ["Codex on box has been quiet for only 1 min — wait, or end it yourself (--stop "
                                        + "needs 2 minutes without output)", "still running in this folder on box: codex (4242)",
                                        "still running in this folder on box: node"]], awayAgent: "codex")
    let unseen8 = stopRefusal(["remote": "box", "stop": ["stopped": false, "reason": "turn-open", "quiet_for": 400, "seen": false],
                               "blockers": ["aht cannot see Codex's own last message on box, so it cannot tell whether "
                                            + "its turn ended — end it yourself"]], awayAgent: "codex")
    let nr8 = stopRefusal(["remote": "box", "applied": false,
                           "stop": ["stopped": false, "reason": "no-reaction", "quit_keys": ["C-c", "C-c"]],
                           "blockers": ["Codex on box did not react to its quit keys (C-c C-c) — end it yourself"]],
                          awayAgent: "codex")
    let to8 = stopRefusal(["blockers": ["Codex's last turn is still open on box — wait, or end it yourself"], "remote": "box"])
    let nqt8 = stopRefusal(["blockers": ["Codex on box has been quiet for only 40 s — wait, or end it yourself"]], machine: "box")
    let late8 = stopRefusal(["stopped": false, "stop_reason": "not-quiet", "warnings": [Any]()], awayAgent: "kimi", machine: "box")
    let w1 = nq8.map(stopWords), w2 = to8.map(stopWords)
    let stop8 = nq8?.reason == "not-quiet" && nq8?.quiet == 60 && nq8?.need == 120 && nq8?.agent == "codex"
        && nq8?.others == ["still running in this folder on box: node"]
        && w1?.title == "Codex on box is still printing"
        && (w1?.text ?? "").hasPrefix("Codex's window there showed new output 1 min ago, so it may be in the middle of its "
                                      + "work. aht ends it only after 2 min without new output.")
        && (w1?.text ?? "").contains("What to do: wait until it has been quiet for 2 min, then choose Take Back again.")
        && to8?.reason == "turn-open" && to8?.agent == "codex" && w2?.title == "Codex's last turn is not finished"
        && (w2?.text ?? "").hasPrefix("Codex on box has not finished its last turn")
        && nqt8?.reason == "not-quiet" && nqt8?.quiet == 40 && nqt8.map(stopWords)?.text.contains("40 s ago") == true
        && late8?.reason == "not-quiet" && late8?.label == "Kimi Code" && late8?.quiet == nil
        && unseen8?.seen == false && unseen8?.others == [] && unseen8.map(stopWords)?.title == "aht cannot tell whether Codex's last turn ended"
        && nr8?.reason == "no-reaction" && nr8.map(stopWords)?.title == "Codex on box did not quit"
        && (nr8.map(stopWords)?.text ?? "").hasPrefix("aht pressed its quit keys (C-c C-c), and Codex still runs.")
        && stopRefusal(["blockers": ["a session is working in /x on box"]]) == nil && stopRefusal([:]) == nil
        && takeBackText(["would_stop": true, "stop": ["quiet_for": 372]], "box", copy: false, synced: false, agent: "codex")
            .contains("Codex on box is ended first: it has been quiet for 6 min, and its last turn has ended.")
        && takeBackText(["would_stop": true], "box", copy: false, synced: false, agent: "claude").contains("The idle session on box")
        && peekState(["raw_status": "quiet", "quiet_for": 372])?.text == "quiet for 6 min"
        && peekState(["status": "waiting for you", "raw_status": "waiting"])?.text == "waiting for you"
    let awayP8 = Project(["real_path": "/x/api", "exists": true, "away": "box.lan", "away_remote": "box",
                          "away_agent": "codex", "away_driven_by": "here"])
    let heldP8 = Project(["real_path": "/x/notes", "exists": true, "away": "DESKTOP-PC", "away_remote": "pc",
                          "away_holder": "pc", "away_agent": "kimi", "away_driven_by": "there"])
    let away8 = awayP8.place == "on box.lan (Codex)" && awayP8.awayAgentLabel == "Codex"
        && Project(["real_path": "/x/shop", "exists": true, "away": "box.lan"]).place == "on box.lan"
        && (awayLine(heldP8) ?? "").hasPrefix("On pc") && (awayLine(heldP8) ?? "").contains(", in Kimi Code (brought there from pc).")
        && Project(["real_path": "/x/r", "exists": true, "away": ["host": "box", "agent": "agy"]]).awayAgent == "agy"
        && Project(["real_path": "/x/api", "away": "box", "away_window": "aht-api-1a2b3c"]).awayWindow == "aht-api-1a2b3c"
        && sendBackDoneText(["applied": true, "catchup": ["agent": "codex", "relay": "r1"]], machine: "mac")
            .contains("What Codex did here is summed up for the Claude Code session on mac.")
    let p8OK = agents8 && cost8 && args8 && bring8 && board8 && rowsOK8 && stop8 && away8
    print("AGENT THERE \(p8OK ? "OK" : "FAIL — agents \(agents8) cost \(cost8) args \(args8) bring \(bring8) board \(board8) rows \(rowsOK8) stop \(stop8) away \(away8)")")
    if !p8OK { print("   \(rows8.map { $0.state }) | \(w1?.text ?? "-") | \(awayLine(heldP8) ?? "-")") }
    // … and the core's phase-8 samples: AHT_FIXTURES_PHASE8 (board rows of
    // windows, a dry run with --agent, projects with away_agent, a refusal)
    let dir8 = ProcessInfo.processInfo.environment["AHT_FIXTURES_PHASE8"] ?? ""
    let files8 = ((try? FileManager.default.contentsOfDirectory(atPath: dir8)) ?? []).filter { $0.hasSuffix(".json") }.sorted()
    if !dir8.isEmpty && !files8.isEmpty {
        var miss: [String] = [], seen: [String] = []
        for n in files8 {
            let data = try? Data(contentsOf: URL(fileURLWithPath: dir8).appendingPathComponent(n))
            guard let d = data.flatMap({ try? JSONSerialization.jsonObject(with: $0) }) as? [String: Any] else {
                miss.append(n + " (not JSON)")
                continue
            }
            if d["machines"] is [Any] {
                let rs = boardMachines(d).flatMap { $0.rows + $0.lastRows }.filter { $0.windowWords != nil }
                if rs.isEmpty || rs.contains(where: { $0.state.contains("Optional(") }) { miss.append(n + " (no window row in words)") }
                seen.append("\(n): " + rs.map { "\(AGENT_LABEL[$0.agent] ?? $0.agent) \($0.state)" }.joined(separator: ", "))
                continue
            }
            // `projects --json`'s rows, or one row (or named rows) as a sample
            let rows = (d["projects"] as? [[String: Any]]) ?? (d["real_path"] != nil ? [d] : nil)
                ?? d.values.compactMap { $0 as? [String: Any] }.filter { $0["real_path"] != nil }
            if !rows.isEmpty {
                let named = rows.map(Project.init).filter { $0.away != nil }.compactMap { p in p.awayAgentLabel.map { "\(p.name) \($0)" } }
                if named.isEmpty { miss.append(n + " (no away_agent)") }
                seen.append("\(n): " + named.joined(separator: ", "))
                continue
            }
            if let r = stopRefusal(d) {
                let w = stopWords(r)
                if w.title.contains("Optional(") || w.text.contains("Optional(") { miss.append(n) }
                seen.append("\(n): \(r.reason), \(w.title)")
                continue
            }
            // a dry run (or --apply) for another agent: its level and its token line
            let agent = firstText((d["perm"] as? [String: Any])?["agent"], d["agent"]) ?? "claude"
            let on = (d["command"] as? String) == "handover" || n.hasPrefix("handover") ? firstText(d["remote"]) ?? "box" : nil
            guard agent != "claude", let p = permInfo(d, agent: agent, setting: "follow"), p.text != nil else {
                miss.append(n + " (no other agent's perm)")
                continue
            }
            seen.append("\(n): \(AGENT_LABEL[agent] ?? agent) \(p.level)" + (on.map { " on " + $0 } ?? " here") + " — "
                        + agentCost(agent, on: on, d))
        }
        let s8OK = miss.isEmpty && !seen.isEmpty
        print("PHASE 8 SAMPLES \(s8OK ? "OK" : "FAIL \(miss)") — \(dir8) [" + seen.joined(separator: "; ") + "]")
    } else {
        print("PHASE 8 SAMPLES not checked (" + (dir8.isEmpty ? "AHT_FIXTURES_PHASE8 names no folder"
                                                         : "no samples in \(dir8) yet") + ")")
    }
    // Phase 9, a Windows PC that answers: what the core says of each PC
    // (`answers` true, null or false with `answers_why`; none from an older
    // core) decides whether it is a machine like the others
    // as the core's rows say it: `answers` on every row (Mac and Linux always
    // true); a PC answers when a runner is noted, else why not
    let ms9 = machinesFrom(["box": ["ssh": "me@box", "system": "Linux", "answers": true, "answers_why": NSNull()],
                            "pc": ["ssh": "me@pc", "system": "Windows", "runner": "py", "answers": true,
                                   "answers_why": NSNull()],
                            "pcnew": ["ssh": "me@pcnew", "system": "Windows", "answers": false,
                                      "answers_why": "not asked yet: aht remote check pcnew asks it"],
                            "pcold": ["ssh": "me@pcold", "system": "Windows", "answers": false,
                                      "answers_why": "update aht on pcold: aht.exe 0.12.0 answers with protocol 2"],
                            "pcpre": ["ssh": "me@pcpre", "system": "Windows"],
                            // a runner alone (no `answers`): not a sign any more
                            "pcrun": ["ssh": "me@pcrun", "system": "Windows", "runner": "aht"]])
    let byName9 = Dictionary(uniqueKeysWithValues: ms9.map { ($0.name, $0) })
    let helper9 = byName9["box"]?.asks == true && byName9["pc"]?.asks == true && byName9["pcnew"]?.asks == false
        && byName9["pcold"]?.asks == false && byName9["pcpre"]?.asks == false && byName9["pcrun"]?.asks == false
        && byName9["pcnew"]?.cannotAsk == "not asked yet: aht remote check pcnew asks it"
        && byName9["pcold"]?.cannotAsk == "update aht on pcold: aht.exe 0.12.0 answers with protocol 2"
        && byName9["pcpre"]?.cannotAsk == "aht cannot ask a Windows machine yet." && byName9["pc"]?.cannotAsk == nil
        && askableMachines(ms9) == ["box"] && machineAnswers("pc", ms9) && !machineAnswers("pcold", ms9)
        && !machineAnswers("gone", ms9) && machineCannotAsk("pcold", ms9).hasPrefix("update aht on pcold")
        && pcAddFailure("✗ aht cannot ask a Windows machine yet.") && !pcAddFailure("✗ me@box refused the connection.")
    let at9 = "2026-10-28T14:10:00"
    let onPC9 = Project(["real_path": "/x/paper", "exists": true, "away": "DESKTOP-PC", "away_remote": "pc",
                         "away_since": at9, "away_driven_by": "here", "away_system": "Windows"])
    let onOld9 = Project(["real_path": "/x/old", "exists": true, "away": "pcold", "away_remote": "pcold",
                          "away_since": at9, "away_driven_by": "here"])
    let tookPC9 = Project(["real_path": "/x/site", "exists": true, "away": "DESKTOP-PC", "away_remote": "pc",
                           "away_holder": "pc", "away_since": at9, "away_driven_by": "there", "away_system": "Windows"])
    let onBox9 = Project(["real_path": "/x/api", "exists": true, "away": "box", "away_remote": "box",
                          "away_since": at9, "away_driven_by": "here", "away_system": "Linux"])
    let away9 = awayLine(onPC9, ms9) == "On pc since \(clock(at9)): continue it on the PC (its tray offers Continue here)."
        && onPC9.takesBack(ms9) && !onPC9.canTakeBack && onPC9.pcAway(ms9)
        && onOld9.pcAway(ms9) && !onOld9.takesBack(ms9) && awayLine(onOld9, ms9)?.hasPrefix("On pcold since ") == true
        && awayLine(tookPC9, ms9) == "On pc since \(clock(at9)) (brought there from pc). Send it back from pc, or take it back here."
        && awayLine(tookPC9) == "On pc since \(clock(at9)) (brought there from pc). Send it back from pc."
        && tookPC9.takesBack(ms9) && !tookPC9.canTakeBack
        && awayLine(onBox9, ms9) == nil && onBox9.takesBack(ms9) && !onBox9.pcAway(ms9)
    // `away_arrival`: handed over to a PC, Continue here waits there (no agent works on it)
    let arr9 = Project(["real_path": "/x/shop", "exists": true, "away": "pc", "away_remote": "pc", "away_since": at9,
                        "away_driven_by": "here", "away_agent": "claude", "away_window": "aht-shop-8f9349",
                        "away_arrival": true])
    let arrival9 = arr9.awayArrival && arr9.pcAway(ms9) && arr9.place == "Continue here waits on pc"
        && arr9.takesBack(ms9) && !onPC9.awayArrival && onPC9.place == "on DESKTOP-PC"
        && awayLine(arr9, ms9) == "On pc since \(clock(at9)): continue it on the PC (its tray offers Continue here)."
    let sent9: [String: Any] = ["sent": ["files": 812, "wire_bytes": 2_000_000]]
    let hand9 = handoverToPC(["there": ["system": "Windows", "home": "C:\\Users\\me"]], nil) && handoverToPC(["pc": true], nil)
        && handoverToPC(["system": "Windows"], nil) && handoverToPC([:], byName9["pc"])
        && !handoverToPC(["there": ["system": "Linux"]], byName9["pc"]) && !handoverToPC([:], byName9["box"])
        && pcStartsText("pc") == "No session starts on pc: aht copies the project there, and the PC's tray offers "
            + "“Continue here”, which opens it in Claude Code. This folder is marked as away until you take it back."
        && handoverDoneText(sent9.merging(["started": false, "reason": "windows"]) { a, _ in a }, remote: "pc")
            == "Handed over to pc: 812 file(s) sent, \(byteText(2_000_000)) over the network. "
            + "No session started there: its tray offers “Continue here”."
        && handoverDoneText(sent9.merging(["start": ["started": false, "reason": "windows"]]) { a, _ in a },
                            remote: "pc", task: "fix it").hasSuffix("its tray offers “Continue here”.")
        && startedNotOnPC(["started": false, "start_reason": "windows", "arrival": "aht-api-1a2b3c"])
        && handoverDoneText(sent9, remote: "pc", toPC: true).hasSuffix("No session started there: its tray offers “Continue here”.")
        && !startedNotOnPC(["started": false, "reason": "tmux"]) && !startedNotOnPC(sent9)
        && handoverDoneText(sent9, remote: "box", agent: "codex", task: "fix it")
            == "Handed over to box: 812 file(s) sent, \(byteText(2_000_000)) over the network. Codex started there "
            + "with aht's summary of the work.\nIt started on: fix it"
    let pcCopy9 = Project(["real_path": "/x/pcwork", "exists": true,
                           "copy_of": ["from": "DESKTOP-PC", "kind": "handover", "remote": "pc", "system": "Windows"]])
    let oldCopy9 = Project(["real_path": "/x/oldwork", "exists": true,
                            "copy_of": ["from": "pcold", "kind": "brought", "remote": "pcold", "system": "Windows"]])
    // follow-up round: the core sends back to a PC that answers; not to one that does not
    let send9 = sendBackBlocked(pcCopy9, ms9) == nil && pcCopy9.copyOf?.pcBlocks(ms9) == false
        && copyLine(pcCopy9.copyOf!, ms9) == "Handed over from DESKTOP-PC: Take Back there or Send Back here returns it"
        && sendBackBlocked(oldCopy9, ms9) == "pcold is a Windows PC, which this Mac cannot reach: take it back on pcold"
        && oldCopy9.copyOf?.pcBlocks(ms9) == true
        && copyLine(oldCopy9.copyOf!, ms9) == "Brought here from pcold: take it back on pcold"
        && sendBackBlocked(pcCopy9, [])?.hasSuffix("take it back on pc") == true
    let okRows9 = [Check(name: "reachable", ok: true, needed: true, detail: "DESKTOP-PC (Windows)", fix: nil, group: "ask"),
                   Check(name: "tmux there", ok: false, needed: true, detail: "missing", fix: nil, group: "handover")]
    let badRows9 = [Check(name: "reachable", ok: false, needed: true, detail: "refused", fix: nil, group: "ask")]
    let check9 = pcCheckNote(byName9["pc"]!, okRows9) == "No session starts on a PC: its tray offers Continue here."
        && pcCheckNote(byName9["pc"]!, badRows9) == nil && pcCheckNote(byName9["box"]!, okRows9) == nil
        && pcCheckNote(byName9["pcold"]!, okRows9) == nil && pcCheckNote(byName9["pc"]!, []) == nil
        // the core's own row says it: no second line
        && pcCheckNote(byName9["pc"]!, okRows9 + [Check(name: "no session starts there", ok: true, needed: false,
                                                        detail: "a project handed over waits on the PC", fix: nil,
                                                        group: "handover")]) == nil
    let pc9OK = helper9 && away9 && arrival9 && hand9 && send9 && check9
    print("PC THAT ANSWERS \(pc9OK ? "OK" : "FAIL — helper \(helper9) away \(away9) arrival \(arrival9) hand over \(hand9) send back \(send9) check \(check9)")")
    // fix round: what the core refuses for every PC (Pick Up, Leave a Note,
    // Bring Here, attach) is not offered for one that answers either; Hand
    // Over, Take Back, Send Back, Keep in sync, Watch, search and Check are
    let local9 = Project(["real_path": "/x/api", "exists": true])
    let items9 = machineItems(local9, askableMachines(ms9))
    let relay9 = askableMachines(ms9) == ["box"] && !items9.contains { $0.machine == "pc" }
        && items9.map { $0.title } == ["Pick Up from box…", "Leave a Note on box…"]
        && machineIsPC("pc", ms9) && machineIsPC("pcold", ms9) && !machineIsPC("box", ms9) && !machineIsPC("gone", ms9)
        && byName9["pc"]?.asks == true && onPC9.takesBack(ms9)
    let pcRow9 = boardRow(["agent": "claude", "project": "C:\\Users\\me\\code\\shop", "status": "idle",
                           "handed_over": true, "here_path": "/x/shop"], machine: "pc", local: false)
    let boxRow9 = boardRow(["agent": "claude", "project": "/home/me/code/api", "status": "idle",
                            "handed_over": true, "here_path": "/x/api"], machine: "box", local: false)
    let open9 = !boardOpens(pcRow9, arr9, ms9) && !boardOpens(pcRow9, onPC9, ms9)
        && !boardOpens(pcRow9, Project(["real_path": "/x/shop", "exists": true, "away": "pc", "away_remote": "pc"]), ms9)
        && boardOpens(boxRow9, onBox9, ms9)
    let gate9OK = relay9 && open9
    print("PC RELAY AND OPEN SESSION NOT OFFERED \(gate9OK ? "OK" : "FAIL — relay \(relay9) open session \(open9) \(items9.map { $0.title })")")
    if !pc9OK { print("   \(awayLine(onPC9, ms9) ?? "-") | \(awayLine(tookPC9, ms9) ?? "-") | \(copyLine(pcCopy9.copyOf!, ms9))") }
    // Follow-up round.  (1) "Copy the folder when a session starts" shows the
    // core's effective.checkpoint_on_start; an older core: the setting, on by
    // default on a Mac
    let cpFU = !checkpointOnStart(["effective": ["checkpoint_on_start": false]], ["checkpoints": true])
        && checkpointOnStart(["effective": ["checkpoint_on_start": true]], ["checkpoints": false])
        && checkpointOnStart([:], [:]) && !checkpointOnStart([:], ["checkpoints": false])
        && checkpointOnStart(["effective": [:]], ["checkpoints": true])
        && undoNoCopyText(false) == "aht has no copy of this folder yet: “Copy the folder when a session starts” is off (Settings, Safety nets)."
        && undoNoCopyText(true).hasPrefix("aht has no copy of this folder yet. It makes one each time")
    let cpModel = AppModel()
    cpModel.demo = true
    cpModel.config = ["checkpoints": true]
    cpModel.status = ["effective": ["checkpoint_on_start": false]]
    let cpOff = !cpModel.checkpointsOn
    cpModel.status = [:]
    let cpModelOK = cpOff && cpModel.checkpointsOn
    var cpSample = "no sample yet"
    var cpSampleOK = true
    let dir9b = ProcessInfo.processInfo.environment["AHT_FIXTURES_PHASE9B"] ?? ""
    if let d = FileManager.default.contents(atPath: dir9b + "/status_effective.json"),
       let j = (try? JSONSerialization.jsonObject(with: d)) as? [String: Any],
       let want = (j["effective"] as? [String: Any])?["checkpoint_on_start"] as? Bool {
        cpSampleOK = checkpointOnStart(j, ["checkpoints": !want]) == want
        cpSample = "status_effective.json says \(want)"
    }
    print("FOLLOW-UP COPY AT A SESSION'S START FROM THE CORE \(cpFU && cpModelOK && cpSampleOK ? "OK" : "FAIL — helper \(cpFU) model \(cpModelOK) sample \(cpSampleOK)") (\(cpSample))")
    // (2) how often machines are asked: the core's WATCH_EVERY and HOLDER_EVERY
    let coreSrc = BUNDLE_RES.map { $0 + "/aht.py" } ?? ahtScript()
    let coreText = (try? String(contentsOfFile: coreSrc, encoding: .utf8)) ?? ""
    func coreConst(_ name: String) -> Int? {
        guard let r = coreText.range(of: "(?m)^" + name + " = (\\d+)", options: .regularExpression) else { return nil }
        return Int(coreText[r].split(separator: "=").last!.trimmingCharacters(in: .whitespaces))
    }
    let paceFU = coreConst("WATCH_EVERY") == WATCH_EVERY && coreConst("HOLDER_EVERY") == HOLDER_EVERY
        && NOTICES_PACE == "Sessions on this Mac are checked every 30 seconds; a watched machine is asked "
            + "every 2 minutes, and one that holds a project of yours about every minute."
        && paceText(60) == "every minute" && paceText(300) == "every 5 minutes" && paceText(30) == "every 30 seconds"
    print("FOLLOW-UP HOW OFTEN MACHINES ARE ASKED \(paceFU ? "OK" : "FAIL — core \(coreConst("WATCH_EVERY") ?? -1)/\(coreConst("HOLDER_EVERY") ?? -1) in \(coreSrc): \(NOTICES_PACE)")")
    // (4) a PC may receive more: Send Back to a PC that answers (not to one
    // that does not, or one not set up here); Keep in sync and backups to it;
    // Pick Up / Leave a Note / Bring Here still only from Mac and Linux
    let pcTo = byName9["pc"]!
    let given9 = Project(["real_path": "/x/given", "exists": true,
                          "copy_of": ["from": "DESKTOP-PC", "kind": "brought", "remote": "pc", "system": "Windows"]])
    let pcNew9 = Project(["real_path": "/x/new", "exists": true,
                          "copy_of": ["from": "pcnew", "kind": "handover", "remote": "pcnew", "system": "Windows"]])
    let pcGone9 = Project(["real_path": "/x/gone", "exists": true,
                           "copy_of": ["from": "DESKTOP-9", "kind": "handover", "system": "Windows"]])
    let sendFU = pcTo.asks && sendBackBlocked(given9, ms9) == nil && given9.sendBackTo == "pc"
        && copyLine(given9.copyOf!, ms9) == "Brought here from DESKTOP-PC: Send Back returns it"
        && pcNew9.copyOf?.pcBlocks(ms9) == true && sendBackBlocked(pcNew9, ms9)?.hasSuffix("take it back on pcnew") == true
        && copyLine(pcNew9.copyOf!, ms9) == "Handed over from pcnew: take it back on pcnew"
        && pcGone9.copyOf?.pcBlocks(ms9) == true && sendBackBlocked(pcGone9, ms9)?.hasSuffix("take it back on DESKTOP-9") == true
        && askableMachines(ms9) == ["box"]
    // (2b) the pickers (Machine, Backups on another machine): a PC only while it
    // answers; one chosen before stays, named so
    let pickNames = pickerMachines(ms9, keeping: nil).map { $0.name }
    let keptOld = pickerMachines(ms9, keeping: "pcold")
    let pickFU = Set(pickNames) == ["box", "pc"] && Set(keptOld.map { $0.name }) == ["box", "pc", "pcold"]
        && keptOld.first { $0.name == "pcold" }.map(pickerLabel) == "pcold (aht cannot ask it)"
        && pickerLabel(byName9["pc"]!) == "pc" && pickerLabel(byName9["box"]!) == "box"
    print("FOLLOW-UP PICKERS LIST A PC THAT ANSWERS \(pickFU ? "OK" : "FAIL — \(pickNames) | \(keptOld.map(pickerLabel))")")
    print("FOLLOW-UP SEND BACK TO A PC THAT ANSWERS \(sendFU ? "OK" : "FAIL — \(sendBackBlocked(given9, ms9) ?? "nil") | \(copyLine(given9.copyOf!, ms9)) | \(sendBackBlocked(pcNew9, ms9) ?? "nil")")")
    // … and the core's phase-9 samples: AHT_FIXTURES_PHASE9 (a PC's check,
    // Hand Over to a PC dry and applied, a project on a PC, an arrival)
    let dir9 = ProcessInfo.processInfo.environment["AHT_FIXTURES_PHASE9"] ?? ""
    let files9 = ((try? FileManager.default.contentsOfDirectory(atPath: dir9)) ?? []).filter { $0.hasSuffix(".json") }.sorted()
    if !dir9.isEmpty && !files9.isEmpty {
        var miss: [String] = [], seen: [String] = []
        for n in files9 {
            let data = try? Data(contentsOf: URL(fileURLWithPath: dir9).appendingPathComponent(n))
            let any = data.flatMap { try? JSONSerialization.jsonObject(with: $0) }
            // the arrival queue: one record, a list, or {"arrivals": [...]}
            if n.hasPrefix("arrival") {
                let recs = (any as? [[String: Any]]) ?? ((any as? [String: Any])?["arrivals"] as? [[String: Any]])
                    ?? (any as? [String: Any]).map { [$0] } ?? []
                let ok = !recs.isEmpty && recs.allSatisfy { r in
                    firstText(r["project"], r["path"]) != nil && firstText(r["from"]) != nil && r["at"] != nil
                        && firstText(r["name"]) != nil && firstText(r["text"]) != nil && firstText(r["action"]) != nil }
                if !ok { miss.append(n + " (no name, project, from, at, text and action)") }
                // as the PC's tray offers it: text — action
                seen.append("\(n): " + recs.map { "\(firstText($0["text"]) ?? "?") — \(firstText($0["action"]) ?? "?")" }
                    .joined(separator: ", "))
                continue
            }
            guard let d = any as? [String: Any] else {
                miss.append(n + " (not JSON)")
                continue
            }
            if let rows = d["machines"] as? [[String: Any]], rows.contains(where: { $0["checks"] != nil || $0["error"] != nil }) {
                // remote check --json for a PC: its rows, and whether it answers
                let r = rows.first ?? [:]
                let (checks, err) = checkRows(d)
                let mc = Machine(name: firstText(r["remote"]) ?? "pc", target: firstText(r["target"]) ?? "",
                                 system: firstText(r["system"]) ?? "", saysAnswers: r.keys.contains("answers") || err == nil,
                                 answers: (r["answers"] as? Bool) ?? (err == nil ? true : false), answersWhy: firstText(r["answers_why"]))
                if mc.system != "Windows" { miss.append(n + " (no system Windows)") }
                if checks.isEmpty && err == nil { miss.append(n + " (no rows)") }
                if err == nil && !checks.contains(where: { $0.name == "aht answers there" }) { miss.append(n + " (no aht answers there)") }
                seen.append("\(n): \(mc.name) \(checks.count) row(s): " + checks.map { ($0.ok ? "✓ " : $0.needed ? "✗ " : "· ") + $0.name }
                                .joined(separator: ", ")
                            + (err.map { ", error: " + $0 } ?? "")
                            + (pcCheckNote(mc, checks).map { " — " + $0 } ?? ""))
                continue
            }
            if let rows = d["machines"] as? [[String: Any]], !rows.isEmpty {
                let bm = boardMachines(d)
                seen.append("\(n): board " + bm.map { "\($0.name) \($0.rows.count)" }.joined(separator: ", "))
                continue
            }
            let rows = (d["projects"] as? [[String: Any]]) ?? (d["real_path"] != nil ? [d] : nil)
            if let rows = rows {
                // a project on a PC: its line, with that PC set up here and answering
                let ps = rows.map(Project.init).filter { $0.away != nil }
                let lines = ps.compactMap { p -> String? in
                    let ms = [Machine(name: p.awayRemote ?? p.away ?? "pc", target: "", system: "Windows",
                                      saysAnswers: true, answers: true)]
                    return awayLine(p, ms).map { "\(p.name) (\(p.place)): " + $0 + (p.takesBack(ms) ? " [Take Back]" : "") }
                }
                if lines.isEmpty { miss.append(n + " (no project on a PC)") }
                seen.append("\(n): " + lines.joined(separator: "; "))
                continue
            }
            if firstText(d["command"]) == "handover" || n.hasPrefix("handover") {
                let to = firstText(d["remote"]) ?? "pc"
                if d["applied"] as? Bool == true {
                    if !startedNotOnPC(d) { miss.append(n + " (no started: false, start_reason: windows)") }
                    seen.append("\(n): " + handoverDoneText(d, remote: to))
                } else {
                    if !handoverToPC(d, nil) || d["pc"] as? Bool != true { miss.append(n + " (no pc: true, Windows not named there)") }
                    if let why = pickupProblems(d) { miss.append(n + " (blocked: \(why))") }
                    seen.append("\(n): " + (handoverToPC(d, nil) ? pcStartsText(to) : "not a PC"))
                }
                continue
            }
            miss.append(n + " (a shape this test does not know)")
        }
        let s9OK = miss.isEmpty && !seen.isEmpty
        print("PHASE 9 SAMPLES \(s9OK ? "OK" : "FAIL \(miss)") — \(dir9) [" + seen.joined(separator: "; ") + "]")
    } else {
        print("PHASE 9 SAMPLES not checked (" + (dir9.isEmpty ? "AHT_FIXTURES_PHASE9 names no folder"
                                                         : "no samples in \(dir9) yet") + ")")
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
    // phase 10: the app's own errors into aht's log (its limits), the core's
    // answers as the app reads them (Recent problems, the report), the file
    // it asks for; then the bundle's core in the throwaway home: a readable
    // report where the app said, and a line of the app's own in its log
    var p10: [String] = []
    var t10 = Date(timeIntervalSince1970: 1_800_000_000)
    var sent10: [[String]] = []
    let lg = AppLog()
    lg.now = { t10 }
    lg.send = { sent10.append($0) }
    if !lg.note("the corner's marks  were not\nsaved")
        || sent10 != [["_log", "--level", "error", "--source", "mac-app", "--", "the corner's marks were not saved"]] {
        p10.append("log line \(sent10)")
    }
    if lg.note("the corner's marks were not saved") { p10.append("the same line again was sent") }
    t10 += 601
    if !lg.note("the corner's marks were not saved") { p10.append("ten minutes later it was not") }
    t10 += 61
    let burst = (0..<7).map { lg.note("problem \($0)") }
    if burst != [true, true, true, true, true, false, false] { p10.append("five a minute: \(burst)") }
    t10 += 61
    lg.note(String(repeating: "x", count: 900), level: "warn")
    if sent10.last?.last?.count != 500 || sent10.last?[2] != "warn" { p10.append("500 characters") }
    let trace10 = "Traceback (most recent call last):\n  File \"aht.py\", line 1, in main\nKeyError: 'nope'\n"
    let usage10 = "usage: aht journal [-h] [--json]\naht: error: unrecognized arguments: --x /Users/me/secret\n"
    let fails10 = [coreFailure(["doctor", "--json"], ok: false, err: trace10),
                   coreFailure(["logs", "--json"], ok: true, err: trace10),
                   coreFailure(["handover", "/p", "--json"], ok: false, err: "box does not answer\n"),
                   coreFailure(["journal", "/Users/me/secret", "--json"], ok: false, err: usage10),
                   coreFailure(["_log", "--level", "error"], ok: false, err: trace10)]
    if fails10.map({ $0 ?? "-" }) != ["it crashed (KeyError)", "-", "-",
                                       "aht did not understand it (unrecognized arguments)", "-"] {
        p10.append("failures \(fails10)")
    }
    if commandName(["search", "my secret words", "--json"]) != "search --json"
        || commandName(["remote", "check", "box", "--json"]) != "remote check --json"
        || commandName(["config", "--set", "notify_phone=ntfy:topic"]) != "config --set" {
        p10.append("names \(commandName(["search", "my secret words", "--json"]))")
    }
    let rows10: [[String: Any]] = [
        ["machine": "studio", "here": true, "reachable": true, "lines": 1, "error": NSNull()],
        ["machine": "box", "here": false, "reachable": true, "lines": 3, "error": NSNull()],
        ["machine": "mini", "here": false, "reachable": false, "lines": 0, "error": "mini did not answer within 30 s"],
        ["machine": "pc", "here": false, "reachable": true, "lines": 0, "error": "aht on pc is too old to send its log"]]
    let logs10 = parseProblems(["hours": 24, "machines": rows10, "entries": [
        ["t": 1_800_000_000.0, "at": "2027-01-15T09:00:00", "level": "warn", "text": "RECONCILE skipped ~/code/old",
         "machine": "studio", "here": true],
        ["t": 1_800_000_600.0, "level": "error", "machine": "box", "here": false,
         "text": "UNCAUGHT Traceback (most recent call last):\n  File \"aht.py\"\nKeyError: 'a'"]]])
    if logs10.rows.map({ "\($0.machine ?? "here") \($0.level) \($0.text.components(separatedBy: "\n").count)" })
        != ["box error 3", "here warn 1"]
        || logs10.missed.map({ $0.line }) != ["mini did not answer within 30 s", "pc: aht on pc is too old to send its log"] {
        p10.append("recent problems \(logs10.rows.map { $0.text }) \(logs10.missed.map { $0.line })")
    }
    let raw10 = parseProblems(["lines": ["[2026-10-28 09:00:00] [WARN ] a", "[2026-10-28 10:30:00] [ERROR] b"]]).rows
    if raw10.map({ "\($0.level) \($0.text)" }) != ["error b", "warn a"] { p10.append("log lines \(raw10.map { $0.text })") }
    if let rep = parseReport(["path": "/x/problem-1.txt", "bytes": 18432, "machines": rows10, "errors": 7]) {
        let said10 = reportSavedText(rep, everywhere: true)
        if rep.names != ["this Mac", "box", "pc"] || rep.problems != 7 || rep.missed.count != 2
            || !said10.contains("7 warnings or errors.") || !said10.contains("From this Mac, box, pc.")
            || !said10.contains("mini did not answer within 30 s") || !said10.contains("Nothing was sent anywhere") {
            p10.append("report \(rep.names) \(said10)")
        }
    } else { p10.append("no report read") }
    if parseReport(["error": "x"]) != nil { p10.append("a report without a path") }
    let out10 = problemReportFile(tmp + "/.aht", at: Date(timeIntervalSince1970: 1_800_000_000))
    var isDir: ObjCBool = false
    let mode10 = ((try? FileManager.default.attributesOfItem(atPath: tmp + "/.aht/reports"))?[.posixPermissions]
                  as? NSNumber)?.intValue
    if out10.range(of: "/\\.aht/reports/problem-\\d{8}-\\d{6}\\.txt$", options: .regularExpression) == nil
        || !FileManager.default.fileExists(atPath: tmp + "/.aht/reports", isDirectory: &isDir) || !isDir.boolValue
        || mode10 != 0o700 {
        p10.append("report file \(out10) \(String(mode10 ?? 0, radix: 8))")
    }
    if problemReportArgs(everywhere: true, out: out10) != ["report-problem", "--out", out10, "--everywhere", "--json"]
        || problemReportArgs(everywhere: false, out: out10) != ["report-problem", "--out", out10, "--json"] {
        p10.append("report args")
    }
    var core10 = "not asked"
    if let rep = parseReport(inTmp(problemReportArgs(everywhere: false, out: out10))) {
        let real = URL(fileURLWithPath: out10).resolvingSymlinksInPath().path
        let body = (try? String(contentsOfFile: rep.path, encoding: .utf8)) ?? ""
        core10 = "report \(rep.bytes) bytes"
        if URL(fileURLWithPath: rep.path).resolvingSymlinksInPath().path != real || body.isEmpty
            || body.hasPrefix("{") || Int64(body.utf8.count) != rep.bytes || rep.names != ["this Mac"] {
            p10.append("the core's report \(rep.path) \(body.prefix(40))")
        }
    } else { p10.append("the core made no report"); core10 = "no report" }
    _ = inTmp(["_log", "--level", "error", "--source", "mac-app", "--", "selftest: the app's own error"])
    let log10 = (try? String(contentsOfFile: tmp + "/.aht/aht.log", encoding: .utf8)) ?? ""
    if !log10.contains("[ERROR] APP mac-app: selftest: the app's own error") { p10.append("the core's _log") }
    else { core10 += ", _log" }
    if !selfLogged.isEmpty { core10 += "; the app noted \(selfLogged.count) problem(s) of its own" }
    let problemOK = p10.isEmpty
    print("PROBLEM REPORT \(problemOK ? "OK" : "FAIL — " + p10.joined(separator: "; ")) — core: \(core10)")
    try? FileManager.default.removeItem(atPath: tmp)
    print("WELCOME LOGIN ANSWER \(loginOK ? "OK" : "FAIL — \(said), \(step ?? [:])")")
    exit(r.ok && bad.isEmpty && setupOK && apartOK && plistOK && marksOK && namesOK && handingOK
         && releaseOK && pauseOK && backOnOK && offsiteOK && fetchPartialOK && relayOK && dialogOK && samplesOK
         && relaySamplesOK && watchOK && groupsOK && staleOK && searchOK && phase3OK && loginOK
         && pickOK && doneOK && menuOK && twinOK && phase4OK && fix1OK && fix2OK && fix3OK && fix4OK
         && pause5OK && phase5OK && transferOK && phase6OK && bringOK && phase7OK && fix7OK
         && perm7bOK && phase7bOK && kimi7bOK && opDryOK && problemOK ? 0 : 1)
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
//              [--corner-only | --welcome-only | --handover-only | --machines-only
//               | --pickup-only | --sync-only | --transfer-only | --bring-only]
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
    if args.contains("--machines-only") {
        // Watch and "last heard" (Machines), a silent machine's last rows
        // (Sessions), Search on every machine: made-up rows in the shape of
        // the core's JSON, then the core's own samples (AHT_FIXTURES_PHASE3)
        // when there are some. Nothing asks the core or another machine.
        let now = Date().timeIntervalSince1970
        let demo = AppModel()
        demo.demo = true
        (demo.loaded, demo.running) = (true, true)
        demo.status = ["version": "phase 3", "tracked": 6, "handover": [
            "supported": true, "can_reach": true, "default_remote": "box", "remotes": [
                "box": ["ssh": "me@box", "watch": true, "system": "Linux"],
                "studio": ["ssh": "me@studio.local", "watch": true, "system": "Darwin"],
                "laptop": ["ssh": "me@laptop", "watch": false, "system": "Linux"]]]]
        let row = { (p: String, agent: String, st: String, ago: Double) -> [String: Any] in
            ["agent": agent, "project": "/home/me/code/" + p, "status": st, "since": now - ago,
             "waiting_for": st == "waiting for you" ? "permission to run the tests" : NSNull()]
        }
        demo.board = boardMachines(["machines": [
            ["machine": "mac", "local": true, "reachable": true, "last_heard": now, "stale": false,
             "sessions": [row("site", "claude", "working", 120)]],
            ["machine": "box", "local": false, "reachable": true, "last_heard": now - 40, "stale": false,
             "sessions": [row("api", "claude", "waiting for you", 300), row("shop", "codex", "working", 900)]],
            ["machine": "studio", "local": false, "reachable": false, "last_heard": now - 1560,
             "stale": true, "error": "ssh: connect to host studio.local port 22: Operation timed out",
             "sessions": [], "last_sessions": [row("paper", "claude", "working", 2400),
                                               row("thesis", "kimi", "idle", 5000)]],
            ["machine": "laptop", "local": false, "reachable": false, "last_heard": now - 240,
             "stale": false, "sessions": [], "last_sessions": [row("blog", "claude", "idle", 3000)]]]])
        demo.boardAt = Date()
        demo.checks["box"] = checkRows(["machines": [["remote": "box", "checks": [
            ["check": "reachable", "ok": true, "detail": "box (Linux)", "needed": true, "group": "ask"],
            ["check": "python3 there", "ok": true, "detail": "3.12.3", "needed": true, "group": "ask"],
            ["check": "key login without a prompt", "ok": true, "detail": "yes", "needed": true,
             "group": "ask"],
            ["check": "rsync there", "ok": true, "detail": "3.2.7", "needed": true, "group": "handover"],
            ["check": "tmux there", "ok": true, "detail": "3.4", "needed": true, "group": "handover"],
            ["check": "keeps box awake while an agent works", "ok": false, "detail": "no systemd-inhibit",
             "needed": false, "group": "handover", "fix": "sudo apt install systemd"]]]]]).rows
        demo.tab = .machines
        snapshot(MainView().environmentObject(demo), dir + "/machines-watch.png", NSSize(width: 900, height: 620))
        demo.tab = .sessions
        snapshot(MainView().environmentObject(demo), dir + "/sessions-as-of.png", NSSize(width: 900, height: 620))
        let hit = { (machine: Any, title: String, p: String, ago: Double, said: String) -> [String: Any] in
            ["machine": machine, "agent": "claude", "session": UUID().uuidString, "project": p,
             "title": title, "live": true, "updated": now - ago,
             "hits": [["role": "user", "snippet": said], ["role": "assistant",
                      "snippet": "I changed the \u{02}login\u{03} \u{02}redirect\u{03} so it keeps the page you came from"]]]
        }
        let home = ProcessInfo.processInfo.environment["HOME"] ?? HOME
        let found: [String: Any] = ["query": "login redirect", "results": [
            hit(NSNull(), "fix the login redirect", home + "/code/site", 3600,
                "the \u{02}login\u{03} \u{02}redirect\u{03} loses the page"),
            hit("box", "api: session cookies", "/home/me/code/api", 86400 * 2,
                "after \u{02}login\u{03} the \u{02}redirect\u{03} goes to /"),
            hit(NSNull(), "auth tests", home + "/code/site", 86400 * 6,
                "a test for the \u{02}login\u{03} \u{02}redirect\u{03}")],
            "machines": [
                ["machine": "box", "reachable": true, "indexed": true, "index_at": now - 600, "results": 1,
                 "error": NSNull()],
                ["machine": "laptop", "reachable": true, "indexed": false, "index_at": NSNull(),
                 "results": 0, "error": NSNull()],
                ["machine": "studio", "reachable": false, "indexed": NSNull(), "index_at": NSNull(),
                 "results": 0, "error": "ssh: connect to host studio.local port 22: Operation timed out"]]]
        demo.tab = .search
        demo.searchEverywhere = true
        (demo.query, demo.searched) = ("login redirect", "login redirect")
        (demo.hits, demo.searchMisses, demo.searchedOn) = (searchHits(found), searchMissed(found), searchAsked(found))
        snapshot(MainView().environmentObject(demo), dir + "/search-everywhere.png", NSSize(width: 900, height: 620))
        let none = ["query": "kubernetes", "results": [], "machines": found["machines"]!] as [String: Any]
        (demo.query, demo.searched) = ("kubernetes", "kubernetes")
        (demo.hits, demo.searchMisses, demo.searchedOn) = (searchHits(none), searchMissed(none), searchAsked(none))
        snapshot(MainView().environmentObject(demo), dir + "/search-everywhere-none.png",
                 NSSize(width: 900, height: 360))
        // the core's samples, when it has written them
        let dir3 = ProcessInfo.processInfo.environment["AHT_FIXTURES_PHASE3"] ?? ""
        func sample(_ n: String) -> [String: Any] {
            let data = try? Data(contentsOf: URL(fileURLWithPath: dir3).appendingPathComponent(n))
            return data.flatMap { try? JSONSerialization.jsonObject(with: $0) } as? [String: Any] ?? [:]
        }
        if !dir3.isEmpty && FileManager.default.fileExists(atPath: dir3) {
            let st = sample("status.json"), rl = sample("remote_list.json")
            var ho = (st["handover"] as? [String: Any]) ?? [:]
            if let rs = rl["remotes"] { ho["remotes"] = rs }
            demo.status = st.merging(["handover": ho]) { $1 }
            demo.board = boardMachines(sample("board.json"))
            demo.checks = [:]
            let rc = sample("remote_check.json")
            if let name = ((rc["machines"] as? [[String: Any]]) ?? []).first?["remote"] as? String {
                (demo.checks[name], demo.checkError[name]) = checkRows(rc)
            }
            demo.tab = .machines
            snapshot(MainView().environmentObject(demo), dir + "/machines-sample.png", NSSize(width: 900, height: 620))
            demo.tab = .sessions
            snapshot(MainView().environmentObject(demo), dir + "/sessions-sample.png", NSSize(width: 900, height: 620))
            let se = sample("search_everywhere.json")
            demo.tab = .search
            (demo.query, demo.searched) = ((se["query"] as? String) ?? "", se["query"] as? String)
            (demo.hits, demo.searchMisses, demo.searchedOn) = (searchHits(se), searchMissed(se), searchAsked(se))
            snapshot(MainView().environmentObject(demo), dir + "/search-sample.png", NSSize(width: 900, height: 620))
        }
        exit(0)
    }
    if args.contains("--transfer-only") {
        // aht's own file copy: Settings' "Copies files with" with each
        // machine's mover, and a machine's check that says it; made-up rows in
        // the shape of the core's JSON. Nothing asks the core or another machine.
        let demo = AppModel()
        demo.demo = true
        (demo.loaded, demo.running) = (true, true)
        demo.status = ["version": "phase 6", "tracked": 6, "hook_installed": true,
                       "handover": ["supported": true, "can_reach": true, "default_remote": "box", "rsync": "3.2.7",
                                    "remotes": ["box": ["ssh": "me@box", "system": "Linux"],
                                                "pc": ["ssh": "me@pc", "system": "Windows"],
                                                "studio": ["ssh": "me@studio.local", "system": "Darwin"]]]]
        demo.config = ["handover_transfer": "auto", "offsite_backup": "box"]
        let rc: [String: Any] = ["ok": true, "machines": [["remote": "box", "target": "me@box", "system": "Linux",
            "ok": true, "transfer": "rsync", "checks": [
                ["check": "reachable", "ok": true, "detail": "box (Linux)", "needed": true, "group": "ask"],
                ["check": "rsync there", "ok": true, "detail": "3.2.7", "needed": false, "group": "handover"]]]]]
        (demo.checks["box"], demo.checkError["box"]) = checkRows(rc)
        for (n, t) in checkTransfers(rc) { demo.movers[n] = Mover(mode: "auto", transfer: t) }
        snapshot(SettingsView().environmentObject(demo), dir + "/settings-transfer.png",
                 NSSize(width: 900, height: 2300))
        demo.tab = .machines
        snapshot(MainView().environmentObject(demo), dir + "/machines-transfer.png", NSSize(width: 900, height: 520))
        exit(0)
    }
    if args.contains("--sync-only") {
        // Keep in sync that looks first: the pause banner for each reason, a
        // copy synced from another machine, "2 paused" in Machines, Hand Over
        // over a changed copy (Replace Them); made-up rows in the shape of the
        // core's JSON, then the core's own samples (AHT_FIXTURES_PHASE5) when
        // there are some. Nothing asks the core or another machine.
        let now = Date().timeIntervalSince1970
        let demo = AppModel()
        demo.demo = true
        (demo.loaded, demo.running) = (true, true)
        demo.status = ["version": "phase 5", "tracked": 6, "hook_installed": true,
                       "handover": ["supported": true, "can_reach": true, "default_remote": "box", "remotes": [
                           "box": ["ssh": "me@box", "watch": true, "system": "Linux"],
                           "studio": ["ssh": "me@studio.local", "watch": false, "system": "Darwin"]]]]
        let home = ProcessInfo.processInfo.environment["HOME"] ?? HOME
        let stamp5 = { (ago: Double) -> String in
            let f = DateFormatter()
            f.locale = Locale(identifier: "en_US_POSIX")
            f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
            return f.string(from: Date().addingTimeInterval(-ago))
        }
        let row = { (name: String, extra: [String: Any]) -> Project in
            Project(["real_path": home + "/code/" + name, "exists": true, "sessions": 4, "bytes": 2_400_000,
                     "agents": ["claude"], "last_activity": stamp5(600), "mirror": "box",
                     "mirror_synced_at": now - 2400, "mirror_status": "ok"].merging(extra) { $1 })
        }
        let pause = { (reason: String, c: Int, n: Int, r: Int, files: [String]) -> [String: Any] in
            ["reason": reason, "at": now - 600, "remote": "box", "changed": c, "new": n, "removed": r,
             "files": files]
        }
        demo.projects = [
            row("api", ["mirror_paused": pause("changed", 3, 1, 0, ["src/auth.py", "src/session.py",
                                                                   "README.md", "notes/todo.md"])]),
            row("site", ["mirror_paused": pause("removals", 0, 0, 412, ["assets/old/hero.png",
                                                                        "assets/old/logo.svg"])]),
            row("paper", ["mirror_paused": pause("other-folder", 0, 0, 0, [])]),
            row("blog", ["mirror_paused": ["reason": "released", "at": now - 1800, "remote": "box"]]),
            Project(["real_path": home + "/code/thesis", "exists": true, "sessions": 2, "bytes": 900_000,
                     "agents": ["claude"], "last_activity": stamp5(7200),
                     "copy_of": ["from": "studio", "kind": "sync", "at": now - 86400]])]
        for (p, name) in zip(demo.projects, ["changed", "removals", "other-folder", "released", "copy-of"]) {
            demo.selection = p.path
            snapshot(DetailView().environmentObject(demo).frame(width: 900, height: 176),
                     dir + "/detail-sync-\(name).png", NSSize(width: 900, height: 176))
        }
        demo.tab = .projects
        demo.selection = demo.projects[0].path
        snapshot(MainView().environmentObject(demo), dir + "/projects-sync-paused.png",
                 NSSize(width: 900, height: 620))
        demo.tab = .machines
        snapshot(MainView().environmentObject(demo), dir + "/machines-paused.png", NSSize(width: 900, height: 420))
        // Hand Over over the changed copy, after Replace Them
        let api = demo.projects[0]
        let body = "12 file(s) to send (1.2 MB), history 3.4 MB.\nSession: fix the login redirect\n\n"
            + replaceThereLine(api.syncPaused!, "box") + "\n\nThe session is resumed there and this "
            + "folder is marked as away until you take it back."
        snapshot(HandoverSheet(plan: HandoverPlan(project: api, remote: "box", body: body, replaceThere: true))
                    .environmentObject(demo), dir + "/sheet-handover-replace-there.png",
                 NSSize(width: 520, height: 540))
        // the notes after each answer
        let notes = [
            ("brought", broughtText(["set_aside": home + "/.aht/aside/api-20261027-1810"], "box",
                                    now: row("api", [:]))),
            ("replaced", replacedText(["set_aside": "/home/me/.aht/replaced/0f3a"], "api", "box",
                                      removals: false, now: row("api", [:]))),
            ("stopped", stoppedText("box", ok: true, err: "", now: Project(["real_path": api.path, "exists": true]),
                                    changed: true))]
        demo.projects[0] = row("api", [:])        // the answer went through: no pause any more
        for (name, text) in notes {
            demo.notes[api.path] = text
            snapshot(DetailView().environmentObject(demo).frame(width: 900, height: 176),
                     dir + "/detail-sync-note-\(name).png", NSSize(width: 900, height: 176))
        }
        demo.notes = [:]
        // the core's samples, when it has written them: its rows, and each of
        // its pauses on a row of its own
        let dir5 = ProcessInfo.processInfo.environment["AHT_FIXTURES_PHASE5"] ?? ""
        func sample(_ n: String) -> Any? {
            let data = try? Data(contentsOf: URL(fileURLWithPath: dir5).appendingPathComponent(n))
            return data.flatMap { try? JSONSerialization.jsonObject(with: $0) }
        }
        let names5 = ((try? FileManager.default.contentsOfDirectory(atPath: dir5)) ?? []).sorted()
        if !dir5.isEmpty && !names5.isEmpty {
            var rows = sampleRows((sample("projects.json") as? [String: Any]) ?? [:]).map(Project.init)
                .filter { $0.copyOf != nil || $0.syncPaused != nil }
            for n in names5 where n.hasPrefix("mirror_paused") {
                for (k, g) in findPauses(sample(n)).enumerated() {
                    rows.append(row(((n as NSString).deletingPathExtension) + (k > 0 ? "-\(k + 1)" : ""),
                                    ["mirror": g["remote"] as? String ?? "box", "mirror_paused": g]))
                }
            }
            demo.projects = rows
            for (k, p) in rows.prefix(8).enumerated() {
                demo.selection = p.path
                snapshot(DetailView().environmentObject(demo).frame(width: 900, height: 176),
                         dir + "/detail-sync-sample-\(k + 1).png", NSSize(width: 900, height: 176))
            }
        }
        exit(0)
    }
    if args.contains("--perm-only") {
        // The level the next agent starts in: the switch dialog (never-ask
        // from Claude Code; Kimi Code with no exact match), Hand Back, Pick
        // Up, Bring Here, Hand Over and the night shift, and Settings ▸
        // Permissions; made-up answers in the shape of the core's `perm`, then
        // the core's own samples (AHT_FIXTURES_PHASE7B) when there are some.
        // Nothing asks the core or another machine.
        let demo = AppModel()
        demo.demo = true
        (demo.loaded, demo.running) = (true, true)
        demo.status = ["version": "phase 7b", "tracked": 3, "hook_installed": true,
                       "agent_clis": ["claude": "claude", "codex": "codex", "kimi": "kimi"],
                       "handover": ["supported": true, "can_reach": true, "default_remote": "box", "remotes": [
                           "box": ["ssh": "me@box", "system": "Linux", "paths": "same"]]]]
        let home = ProcessInfo.processInfo.environment["HOME"] ?? HOME
        let paper = Project(["real_path": home + "/code/paper", "exists": true, "sessions": 3, "agents": ["claude", "codex"],
                             "relay": ["id": "r1", "from_agent": "claude", "to_agent": "codex", "open": true]])
        let never: [String: Any] = ["agent": "codex", "level": "never", "sandbox": false, "from": "command_line", "read": "never",
                                    "flags": ["--dangerously-bypass-approvals-and-sandbox"],
                                    "text": "Codex starts in never-ask mode, like the Claude Code session you are leaving"]
        let sw: [String: Any] = ["command": "switch", "applied": false, "blockers": [], "warnings": [], "target": "codex",
                                 "mode": "new", "source": ["agent": "claude", "title": "fix the login redirect"],
                                 "start_line": "codex --dangerously-bypass-approvals-and-sandbox 'Read .aht/handover/relay-1.md first'",
                                 "perm": never]
        snapshot(SwitchSheet(plan: SwitchPlan(project: paper, target: "codex", back: false, backTo: nil,
                                              plans: ["new": sw, "resume": sw], mode: "new")).environmentObject(demo),
                 dir + "/perm-switch-never.png", NSSize(width: 520, height: 470))
        let kimi = sw.merging(["target": "kimi", "start_line": "kimi",
                               "perm": ["agent": "kimi", "level": "ask", "sandbox": false, "from": "command_line", "read": "edits",
                                        "flags": [Any](), "text": "Kimi Code starts in ask mode, the next stricter level: it has "
                                            + "no edits mode (the Claude Code session you are leaving runs in edits mode)"]]) { $1 }
        snapshot(SwitchSheet(plan: SwitchPlan(project: paper, target: "kimi", back: false, backTo: nil,
                                              plans: ["new": kimi, "resume": kimi], mode: "new")).environmentObject(demo),
                 dir + "/perm-switch-kimi.png", NSSize(width: 520, height: 500))
        let back = sw.merging(["target": "claude", "mode": "back", "start_line": "claude --resume s1 --permission-mode auto",
                               "perm": ["agent": "claude", "level": "auto", "sandbox": false, "from": "relay", "read": "auto",
                                        "flags": ["--permission-mode", "auto"],
                                        "text": "Claude Code starts in auto mode, like the Codex session you are leaving"]]) { $1 }
        snapshot(SwitchSheet(plan: SwitchPlan(project: paper, target: "claude", back: true, backTo: nil,
                                              plans: ["back": back], mode: "back")).environmentObject(demo),
                 dir + "/perm-hand-back.png", NSSize(width: 520, height: 400))
        var pv = PickupView(project: paper, machine: "box", kind: "pickup")
        pv.loading = false
        pv.dry = ["command": "pickup", "applied": false, "blockers": [], "warnings": [], "target": "claude", "mode": "new",
                  "match": ["path": "/home/me/code/paper", "how": "id"],
                  "source": ["agent": "claude", "title": "fix the login redirect",
                             "perm": ["level": "never", "sandbox": false, "from": "command_line"]],
                  "brief": "# Pick up: paper\n\n## Where things stood\n\nThe redirect after login goes to /home.\n",
                  "perm": NSNull()]
        demo.pickup = pv
        snapshot(PickupSheet().environmentObject(demo), dir + "/perm-pickup.png", NSSize(width: 660, height: 640))
        pv.open = "codex"
        demo.pickup = pv
        snapshot(PickupSheet().environmentObject(demo), dir + "/perm-pickup-codex.png", NSSize(width: 660, height: 640))
        var bv = BringView(machine: "box")
        (bv.listing, bv.picked) = (false, home + "/code/shop")
        bv.list = ["remote": "box", "projects": [["path": home + "/code/shop", "here_path": home + "/code/shop",
                                                  "title": "Checkout flow refactor", "sessions": 3]]]
        bv.dry = ["command": "bring", "applied": false, "blockers": [], "warnings": [], "remote": "box", "agent": "claude",
                  "here_path": home + "/code/shop", "there_path": home + "/code/shop",
                  "session": ["id": "0f3a9c2e", "title": "Checkout flow refactor"],
                  "plan": ["files": 1204, "bytes": 40_055_603, "history_bytes": 4_299_161, "file_history": true],
                  "perm": ["agent": "claude", "level": "edits", "sandbox": false, "from": "relay", "read": "edits",
                           "flags": ["--permission-mode", "acceptEdits"],
                           "text": "Claude Code starts in edits mode, like the session on box"]]
        demo.bring = bv
        snapshot(BringSheet().environmentObject(demo), dir + "/perm-bring.png", NSSize(width: 660, height: 640))
        let ho: [String: Any] = ["command": "handover", "remote": "box", "there_path": home + "/code/paper",
                                 "perm": ["agent": "claude", "level": "never", "sandbox": true, "from": "command_line", "read": "never",
                                          "flags": ["--dangerously-skip-permissions", "--settings", "{\"sandbox\":{\"enabled\":true}}"],
                                          "text": "Claude Code on box starts in never-ask mode inside its sandbox, like the session here"]]
        snapshot(HandoverSheet(plan: HandoverPlan(project: paper, remote: "box",
                                                  body: "812 file(s) to send (5.1 MB), history 879 KB.\nSession: add rate limits\n\n"
                                                    + "The session is resumed there and this folder is marked as away until you take it back.",
                                                  dry: ho)).environmentObject(demo),
                 dir + "/perm-handover.png", NSSize(width: 520, height: 560))
        let ns: [String: Any] = ["project": paper.path, "applied": false, "blockers": ["say what the agent should work on (--task)"],
                                 "job": ["remote": "box"],
                                 "perm": ["agent": "claude", "level": "auto", "sandbox": false, "from": "transcript", "read": "auto",
                                          "flags": ["--permission-mode", "auto"],
                                          "text": "Claude Code on box starts in auto mode, like the project's latest session here"]]
        snapshot(NightShiftSheet(v: NightShiftView(project: paper, jobs: [], dry: ns)).environmentObject(demo),
                 dir + "/perm-night.png", NSSize(width: 660, height: 540))
        var ov = OpinionView(project: paper)
        (ov.current, ov.task, ov.finished) = ("r1", "make the parser accept empty lines", true)
        ov.started = ["perms": [
            "claude": ["agent": "claude", "level": "never", "sandbox": false, "read": "never", "from": "command_line",
                       "flags": ["--dangerously-skip-permissions"],
                       "text": "Claude Code starts in never-ask mode, like the project's latest session (Claude Code)"],
            "kimi": ["agent": "kimi", "level": "never", "sandbox": false, "read": "never", "from": "command_line",
                     "flags": ["--auto"], "text": "Kimi Code starts in never-ask mode, like the project's latest session (Claude Code)"]]]
        ov.results = [OpinionResult(id: "claude", state: "done", answer: "Done.", seconds: 95, cost: nil, files: [],
                                    perm: ["level": "never", "sandbox": false, "flags": ["--dangerously-skip-permissions"]]),
                      OpinionResult(id: "kimi", state: "working", answer: "", seconds: nil, cost: nil, files: [],
                                    perm: ["level": "never", "sandbox": false, "flags": ["--auto"]])]
        snapshot(OpinionSheet(v: ov).environmentObject(demo), dir + "/perm-opinion.png", NSSize(width: 960, height: 660))
        // the fix round: the second opinion's level before Start (its dry run),
        // Kimi below never-ask in the switch dialog, and the first message to
        // paste after Pick Up → Open in Kimi
        var od = OpinionView(project: paper)
        od.finished = true
        demo.opinion = od
        demo.opinionDry = OpinionDry(path: paper.path, task: "", d: [
            "applied": false, "blockers": ["say what both should do (--task)"],
            "warnings": ["Kimi Code is left out: its run on its own works only in never-ask mode, and the project's latest "
                         + "session runs in auto mode"],
            "perms": ["claude": ["agent": "claude", "level": "auto", "sandbox": false, "read": "auto", "from": "transcript",
                                 "flags": ["--permission-mode", "auto"],
                                 "text": "Claude Code works in auto mode, like the project's latest session (Claude Code)"],
                      "codex": ["agent": "codex", "level": "auto", "sandbox": false, "read": "auto", "from": "transcript",
                                "flags": ["-a", "on-request"],
                                "text": "Codex works in auto mode, like the project's latest session (Claude Code)"]]])
        snapshot(OpinionSheet(v: od).environmentObject(demo), dir + "/perm-opinion-dry.png", NSSize(width: 960, height: 420))
        (demo.opinion, demo.opinionDry) = (nil, nil)
        let kimiAsk = sw.merging(["target": "kimi", "start_line": "kimi", "kimi_reads": false,
                                  "perm": ["agent": "kimi", "level": "ask", "sandbox": false, "from": "transcript", "read": "auto",
                                           "flags": [Any](), "text": "Kimi Code starts in ask mode, the next stricter level it has "
                                               + "(the Claude Code session you are leaving runs in auto mode)"]]) { $1 }
        snapshot(SwitchSheet(plan: SwitchPlan(project: paper, target: "kimi", back: false, backTo: nil,
                                              plans: ["new": kimiAsk, "resume": kimiAsk], mode: "new")).environmentObject(demo),
                 dir + "/kimi-switch-below-never.png", NSSize(width: 520, height: 520))
        var pk = PickupView(project: paper, machine: "box", kind: "pickup")
        (pk.loading, pk.open) = (false, "kimi")
        pk.dry = ["command": "pickup", "applied": false, "blockers": [], "warnings": [], "target": "claude", "mode": "new",
                  "match": ["path": "/home/me/code/paper", "how": "id"],
                  "source": ["agent": "claude", "title": "fix the login redirect",
                             "perm": ["level": "auto", "sandbox": false, "from": "transcript"]],
                  "brief": "# Pick up: paper\n\n## Where things stood\n\nThe redirect after login goes to /home.\n"]
        pk.done = ["applied": true, "blockers": [], "warnings": [], "opened": "kimi", "kimi_reads": false,
                   "brief": paper.path + "/.aht/handover/relay-20261028-100000-k1.md", "start_line": "kimi",
                   "first_prompt": "You are taking over this project from Claude Code on box. Read "
                       + ".aht/handover/relay-20261028-100000-k1.md first: it records where the work stood, the latest "
                       + "exchanges and the open items. Then tell me in two or three lines what you understood, and wait "
                       + "for my next instruction."]
        demo.pickup = pk
        snapshot(PickupSheet().environmentObject(demo), dir + "/kimi-pickup-first-prompt.png", NSSize(width: 660, height: 640))
        demo.pickup = nil
        demo.config = ["agent_permissions": "never",
                       "agent_permission_flags": ["codex": ["never": CODEX_SANDBOXED]]]
        snapshot(PermissionsSettings().padding(12).frame(width: 700).environmentObject(demo),
                 dir + "/perm-settings.png", NSSize(width: 700, height: 220))
        demo.config = ["agent_permission_flags": ["codex": ["never": ["--sandbox", "read-only", "-a", "never"]]]]
        snapshot(PermissionsSettings().padding(12).frame(width: 700).environmentObject(demo),
                 dir + "/perm-settings-own.png", NSSize(width: 700, height: 200))
        // the core's samples, when it has written them: each answer with a perm
        let dir7b = ProcessInfo.processInfo.environment["AHT_FIXTURES_PHASE7B"] ?? ""
        let files7b = ((try? FileManager.default.contentsOfDirectory(atPath: dir7b)) ?? []).filter { $0.hasSuffix(".json") }.sorted()
        demo.config = [:]
        for n in files7b {
            let data = try? Data(contentsOf: URL(fileURLWithPath: dir7b).appendingPathComponent(n))
            guard let d = data.flatMap({ try? JSONSerialization.jsonObject(with: $0) }) as? [String: Any],
                  d["perm"] != nil else { continue }
            let agent = firstText(d["target"], d["agent"]) ?? "claude"
            let src = firstText((d["source"] as? [String: Any])?["agent"])
            snapshot(PermLine(d: d, agent: agent, source: src, leaving: { "the \($0.map { $0 + " " } ?? "")session you are leaving" })
                        .padding(12).frame(width: 520).environmentObject(demo),
                     dir + "/perm-sample-" + (n as NSString).deletingPathExtension + ".png", NSSize(width: 520, height: 120))
        }
        exit(0)
    }
    if args.contains("--agents-only") {
        // Another agent on the other machine: Hand Over's Agent there (Claude
        // Code, Codex, an agent missing there), Bring Here's Agent here, the
        // Sessions board's windows ("working", "quiet for 6 min", "exited"),
        // and the away rows naming the agent there; made-up answers in the
        // shape of the core's JSON, then the core's own samples
        // (AHT_FIXTURES_PHASE8) when there are some. Nothing asks the core or
        // another machine.
        let now = Date().timeIntervalSince1970
        let demo = AppModel()
        demo.demo = true
        (demo.loaded, demo.running) = (true, true)
        demo.status = ["version": "phase 8", "tracked": 4, "hook_installed": true,
                       "agent_clis": ["claude": "claude", "codex": "codex", "kimi": "kimi", "agy": "agy"],
                       "handover": ["supported": true, "can_reach": true, "default_remote": "box", "remotes": [
                           "box": ["ssh": "me@box", "system": "Linux", "paths": "same"]]]]
        let home = ProcessInfo.processInfo.environment["HOME"] ?? HOME
        let paper = Project(["real_path": home + "/code/paper", "exists": true, "sessions": 3, "agents": ["claude"]])
        let perm8 = { (agent: String, level: String, flags: [String], text: String) -> [String: Any] in
            ["agent": agent, "level": level, "sandbox": false, "from": "command_line", "read": "edits", "flags": flags, "text": text]
        }
        let body = "812 file(s) to send (5.1 MB), history 879 KB.\nSession: add rate limits"
        let ho: [String: Any] = ["command": "handover", "remote": "box", "agent": "claude", "there_path": home + "/code/paper",
                                 "blockers": [], "warnings": [],
                                 "perm": perm8("claude", "edits", ["--permission-mode", "acceptEdits"],
                                               "Claude Code on box starts in edits mode, like the Claude Code session here")]
        let hoCodex = ho.merging(["agent": "codex", "warnings": ["Codex on box is 0.40; this machine has 0.52"],
                                  "perm": perm8("codex", "edits", ["-a", "on-request", "-s", "workspace-write"],
                                                "Codex on box starts in edits mode, like the Claude Code session here")]) { $1 }
        let hoAgy = ho.merging(["agent": "agy", "blockers": ["Antigravity (agy) is not installed on box: install it there, "
                                                             + "or choose another agent"]]) { $1 }
        snapshot(HandoverSheet(plan: HandoverPlan(project: paper, remote: "box", body: body, dry: ho))
                    .environmentObject(demo), dir + "/agent-handover-claude.png", NSSize(width: 520, height: 640))
        var hp = HandoverPlan(project: paper, remote: "box", body: body, dry: ho)
        hp.agent = "codex"
        snapshot(HandoverSheet(plan: hp, dries: ["codex": hoCodex]).environmentObject(demo),
                 dir + "/agent-handover-codex.png", NSSize(width: 520, height: 680))
        hp.agent = "agy"
        snapshot(HandoverSheet(plan: hp, dries: ["agy": hoAgy]).environmentObject(demo),
                 dir + "/agent-handover-agy-missing.png", NSSize(width: 520, height: 600))
        var bv = BringView(machine: "box")
        (bv.listing, bv.picked, bv.agent) = (false, home + "/code/shop", "codex")
        bv.list = ["remote": "box", "projects": [["path": home + "/code/shop", "here_path": home + "/code/shop",
                                                  "title": "Checkout flow refactor", "sessions": 3]]]
        bv.dry = ["command": "bring", "applied": false, "blockers": [], "warnings": [], "remote": "box", "agent": "codex",
                  "here_path": home + "/code/shop", "there_path": home + "/code/shop",
                  "session": ["id": "0f3a9c2e", "title": "Checkout flow refactor", "agent": "claude"],
                  "plan": ["files": 1204, "bytes": 40_055_603, "history_bytes": 4_299_161, "file_history": true],
                  "perm": perm8("codex", "edits", ["-a", "on-request", "-s", "workspace-write"],
                                "Codex starts in edits mode, like the Claude Code session on box")]
        demo.bring = bv
        snapshot(BringSheet().environmentObject(demo), dir + "/agent-bring-codex.png", NSSize(width: 660, height: 640))
        let win = { (p: String, agent: String, raw: String, quiet: Double, off: Bool) -> [String: Any] in
            ["agent": agent, "project": "/home/me/code/" + p, "status": "running", "window": "aht-\(p)-1a2b3c",
             "raw_status": raw, "quiet_for": quiet, "not_running": off, "since": now - 1800]
        }
        demo.board = boardMachines(["machines": [
            ["machine": "mac", "local": true, "reachable": true, "last_heard": now, "stale": false,
             "sessions": [["agent": "claude", "project": home + "/code/paper", "status": "working", "raw_status": "busy",
                           "since": now - 300]]],
            ["machine": "box", "local": false, "reachable": true, "last_heard": now - 20, "stale": false,
             "sessions": [win("api", "codex", "working", 3, false), win("shop", "kimi", "quiet", 372, false),
                          win("site", "agy", "exited", 30, true), win("notes", "codex", "quiet", 40, false)]]]])
        demo.boardAt = Date()
        demo.tab = .sessions
        snapshot(MainView().environmentObject(demo), dir + "/agent-sessions-windows.png", NSSize(width: 900, height: 520))
        let row = { (name: String, extra: [String: Any]) -> Project in
            Project(["real_path": home + "/code/" + name, "exists": true, "sessions": 4, "bytes": 2_400_000,
                     "agents": ["claude"]].merging(extra) { $1 })
        }
        demo.projects = [
            row("api", ["away": "box", "away_remote": "box", "away_since": "2026-10-28T10:43:07", "away_driven_by": "here",
                        "away_system": "Linux", "away_agent": "codex", "away_window": "aht-api-40400d"]),
            row("notes", ["away": "pc", "away_since": now - 7200, "away_driven_by": "there", "away_holder": "pc",
                          "away_system": "Windows", "away_remote": NSNull(), "away_agent": "kimi"])]
        for (p, name) in zip(demo.projects, ["handed-over-codex", "held-by-pc-kimi"]) {
            demo.selection = p.path
            snapshot(DetailView().environmentObject(demo).frame(width: 900, height: 176),
                     dir + "/agent-detail-\(name).png", NSSize(width: 900, height: 176))
        }
        demo.tab = .projects
        snapshot(MainView().environmentObject(demo), dir + "/agent-projects.png", NSSize(width: 900, height: 520))
        var pv = PeekView(project: demo.projects[0])
        pv.loading = false
        pv.d = ["agent": "codex", "open": true, "status": "quiet for 6 min", "raw_status": "quiet", "quiet_for": 401,
                "screen": ["• Ran the tests: 41 passed, 1 failed (test_login_redirect)", "",
                           "Shall I fix the redirect now? (y/n)", "› "], "error": NSNull()]
        demo.peek = pv
        snapshot(PeekSheet().environmentObject(demo), dir + "/agent-peek.png", NSSize(width: 640, height: 460))
        // the core's own samples
        let dir8 = ProcessInfo.processInfo.environment["AHT_FIXTURES_PHASE8"] ?? ""
        let load8 = { (n: String) -> [String: Any]? in
            (try? Data(contentsOf: URL(fileURLWithPath: dir8).appendingPathComponent(n)))
                .flatMap { try? JSONSerialization.jsonObject(with: $0) } as? [String: Any]
        }
        if let d = load8("board_windows.json") {
            demo.board = boardMachines(d)
            demo.tab = .sessions
            snapshot(MainView().environmentObject(demo), dir + "/agent-sample-board.png", NSSize(width: 900, height: 620))
        }
        if let d = load8("handover_agent_dry.json") {
            var sp = HandoverPlan(project: paper, remote: firstText(d["remote"]) ?? "box", body: body, dry: ho)
            sp.agent = firstText((d["perm"] as? [String: Any])?["agent"], d["agent"]) ?? "codex"
            snapshot(HandoverSheet(plan: sp, dries: [sp.agent: d]).environmentObject(demo),
                     dir + "/agent-sample-handover.png", NSSize(width: 520, height: 680))
        }
        if let d = load8("bring_agent_dry.json") {
            var sb = BringView(machine: firstText(d["remote"]) ?? "box")
            (sb.listing, sb.picked, sb.dry) = (false, firstText(d["there_path"]) ?? home + "/code/shop", d)
            sb.list = ["remote": sb.machine, "projects": [["path": sb.picked ?? "", "here_path": d["here_path"] ?? NSNull(),
                                                           "title": (d["session"] as? [String: Any])?["title"] ?? NSNull()]]]
            sb.agent = firstText((d["perm"] as? [String: Any])?["agent"], d["agent"]) ?? "codex"
            demo.bring = sb
            snapshot(BringSheet().environmentObject(demo), dir + "/agent-sample-bring.png", NSSize(width: 660, height: 640))
        }
        exit(0)
    }
    if args.contains("--bring-only") {
        // Bring Here and Send Back: the list from another machine, a dry run,
        // names this Mac cannot hold, Send Back with line endings and the
        // .gitattributes hint, Hand Over blocked by names and by the folder
        // there, the row of a project a PC took, a brought copy, and each
        // machine's folders in Machines; made-up rows in the shape of the
        // core's JSON, then the core's own samples (AHT_FIXTURES_PHASE7) when
        // there are some. Nothing asks the core or another machine.
        let now = Date().timeIntervalSince1970
        let demo = AppModel()
        demo.demo = true
        (demo.loaded, demo.running) = (true, true)
        demo.status = ["version": "phase 7", "tracked": 6, "hook_installed": true,
                       "handover": ["supported": true, "can_reach": true, "default_remote": "box", "remotes": [
                           "box": ["ssh": "me@box", "system": "Linux", "paths": "same"],
                           "lab": ["ssh": "me@lab", "system": "Linux", "paths": [["/Volumes/Work", "/data/me"]]],
                           "pc": ["ssh": "me@pc", "system": "Windows", "paths": "home"]]]]
        let home = ProcessInfo.processInfo.environment["HOME"] ?? HOME
        demo.pathsOf = pathMaps(["machines": [
            ["remote": "box", "paths": "same", "here_home": home, "there_home": home],
            ["remote": "lab", "paths": [["/Volumes/Work", "/data/me"]], "here_home": home, "there_home": "/home/me"],
            ["remote": "pc", "paths": "home", "here_home": home, "there_home": "C:\\Users\\me"]]])
        let stamp7 = { (ago: Double) -> String in
            let f = DateFormatter()
            f.locale = Locale(identifier: "en_US_POSIX")
            f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
            return f.string(from: Date().addingTimeInterval(-ago))
        }
        var bv = BringView(machine: "box")
        bv.listing = false
        bv.list = ["remote": "box", "projects": [
            ["path": home + "/code/shop", "here_path": home + "/code/shop", "title": "Checkout flow refactor",
             "sessions": 3, "last_activity": stamp7(900)],
            ["path": home + "/code/api", "here_path": home + "/code/api", "title": "session cookies",
             "sessions": 5, "last_activity": stamp7(4000), "open": "working", "can_bring": false,
             "why_not": "a session is working in it there"],
            ["path": home + "/code/site", "sessions": 1, "last_activity": stamp7(86400 * 3), "can_bring": false,
             "away": ["holder": "studio", "since": stamp7(7200), "driven_by": "here"], "why_not": "on studio since 22:10"],
            ["path": home + "/papers/thesis", "title": "chapter 3 figures", "sessions": 9,
             "last_activity": stamp7(86400 * 6)]]]
        demo.bring = bv
        snapshot(BringSheet().environmentObject(demo), dir + "/sheet-bring-list.png", NSSize(width: 660, height: 640))
        let dry: [String: Any] = ["command": "bring", "applied": false, "blockers": [], "warnings": [],
            "remote": "box", "here_path": home + "/code/shop", "there_path": home + "/code/shop",
            "names": [], "eol_only": [], "unsafe_names": [], "other_histories": ["codex"],
            "session": ["id": "0f3a9c2e-5b7d-4e1f-9a8b-7c6d5e4f3a2b", "title": "Checkout flow refactor"],
            "plan": ["files": 1204, "bytes": 40_055_603, "history_bytes": 4_299_161, "file_history": true]]
        bv.picked = home + "/code/shop"
        bv.dry = dry
        demo.bring = bv
        snapshot(BringSheet().environmentObject(demo), dir + "/sheet-bring-dry.png", NSSize(width: 660, height: 640))
        let caseNames: [String: Any] = ["kind": "case", "count": 2, "text": "two files whose names differ only in capitals",
                                        "names": [["README.md", "readme.md"], ["Makefile", "makefile"]]]
        let namesSaid: String = "2 names this machine cannot hold (two files whose names differ only in capitals: "
            + "README.md / readme.md; Makefile / makefile) — rename them on box, or add them to handover_excludes"
        let otherSaid: String = "here, \(home)/code/shop holds another folder (412 items). Move it away, or bring "
            + "it to another place with --here PATH"
        let idleSaid: String = "an idle Claude Code session is open in it on box, or pass --allow-idle to bring it anyway"
        bv.dry = dry.merging(["names": [caseNames], "blockers": [namesSaid, otherSaid, idleSaid]]) { $1 }
        demo.bring = bv
        snapshot(BringSheet().environmentObject(demo), dir + "/sheet-bring-blocked.png", NSSize(width: 660, height: 640))
        bv.dry = dry
        bv.done = ["applied": true, "here_path": home + "/code/shop", "opened": true, "warnings": []]
        demo.bring = bv
        snapshot(BringSheet().environmentObject(demo), dir + "/sheet-bring-done.png", NSSize(width: 660, height: 640))
        // a project brought here from pc, and one a PC took from here
        let row = { (name: String, extra: [String: Any]) -> Project in
            Project(["real_path": home + "/code/" + name, "exists": true, "sessions": 4, "bytes": 2_400_000,
                     "agents": ["claude"], "last_activity": stamp7(600)].merging(extra) { $1 })
        }
        demo.projects = [
            row("shop", ["away": "pc", "away_since": stamp7(5400), "away_driven_by": "there",
                         "away_holder": "pc", "away_system": "Windows", "away_remote": NSNull()]),
            row("api", ["copy_of": ["from": "box", "kind": "brought", "at": now - 3600, "remote": "box",
                                    "from_path": "/home/me/code/api"]]),
            row("site", ["away": "box", "away_remote": "box", "away_since": stamp7(7200), "away_driven_by": "there",
                         "away_system": "Linux"])]
        for (p, name) in zip(demo.projects, ["held-by-pc", "brought-here", "held-by-box"]) {
            demo.selection = p.path
            snapshot(DetailView().environmentObject(demo).frame(width: 900, height: 176),
                     dir + "/detail-\(name).png", NSSize(width: 900, height: 176))
        }
        demo.tab = .projects
        demo.selection = demo.projects[0].path
        snapshot(MainView().environmentObject(demo), dir + "/projects-held-by-pc.png", NSSize(width: 900, height: 620))
        let back: [String: Any] = ["command": "send-back", "applied": false, "blockers": [], "warnings": [],
            "remote": "box", "here_path": home + "/code/api", "there_path": "/home/me/code/api",
            "names": [], "eol_only": ["src/app.js", "README.md", "build.sh"],
            "unsafe_names": [], "git": ["is_git": true, "gitattributes": false, "suggest": GITATTRIBUTES_LINES],
            "conflicts": ["project": ["src/cart.js"]],
            "plan": ["project": ["take": 14, "new": 2, "delete": 1, "conflict": 1, "kept": 0],
                     "history": ["take": 1, "new": 0, "delete": 0, "conflict": 0, "kept": 0]]]
        var sb = SendBackView(project: demo.projects[1], machine: "box")
        sb.loading = false
        sb.dry = back
        demo.sendBack = sb
        snapshot(SendBackSheet().environmentObject(demo), dir + "/sheet-send-back.png", NSSize(width: 600, height: 520))
        sb.dry = back.merging(["blockers": ["the history here was written by Claude Code 2.1.320, newer than "
                                            + "2.1.310 on box: update it there, or pass --ignore-version"]]) { $1 }
        demo.sendBack = sb
        snapshot(SendBackSheet().environmentObject(demo), dir + "/sheet-send-back-version.png",
                 NSSize(width: 600, height: 520))
        // Hand Over: blocked by names lab cannot hold and a folder outside the mapping; then a
        // plan with another path there, the git note and the .gitattributes hint
        let api = demo.projects[1]
        let named: [String: Any] = ["command": "handover", "remote": "lab", "there_path": "/data/me/api",
            "names": [["kind": "unicode", "count": 1, "names": [["notes/café.md", "notes/cafe\u{301}.md"]]],
                      ["kind": "symlink", "count": 2, "names": ["bin/run", "data/latest"]]],
            "blockers": ["aht moves projects between the home folders of your machines. /Volumes/Data/api is "
                         + "outside yours. Tell aht where such projects go on lab:  "
                         + "aht remote paths lab --add /Volumes/Data /home/me/Data"]]
        snapshot(HandoverSheet(plan: HandoverPlan(project: api, remote: "lab", body: "", dry: named, blocked: true))
                    .environmentObject(demo), dir + "/sheet-handover-blocked.png", NSSize(width: 560, height: 520))
        let body = "1,204 file(s) to send (38.2 MB), history 4.1 MB.\nSession: Checkout flow refactor\n\n"
            + "The session is resumed there and this folder is marked as away until you take it back."
        let crossing: [String: Any] = ["there_path": "/data/me/api", "git": [
            "is_git": true, "gitattributes": false, "suggest": GITATTRIBUTES_LINES, "env": ["core.filemode": "false"],
            "how": "in your own terminal on lab:  git -c core.filemode=false status   (aht's session there has this set)"]]
        snapshot(HandoverSheet(plan: HandoverPlan(project: api, remote: "lab", body: body, dry: crossing))
                    .environmentObject(demo), dir + "/sheet-handover-crossing.png", NSSize(width: 520, height: 640))
        demo.tab = .machines
        snapshot(MainView().environmentObject(demo), dir + "/machines-paths.png", NSSize(width: 900, height: 520))
        // the core's samples, when it has written them
        let dir7 = ProcessInfo.processInfo.environment["AHT_FIXTURES_PHASE7"] ?? ""
        func sample(_ n: String) -> [String: Any]? {
            let data = try? Data(contentsOf: URL(fileURLWithPath: dir7).appendingPathComponent(n))
            return data.flatMap { try? JSONSerialization.jsonObject(with: $0) } as? [String: Any]
        }
        guard !dir7.isEmpty else { exit(0) }
        if let d = sample("bring_list.json") {
            var v = BringView(machine: firstText(d["remote"]) ?? "box")
            (v.listing, v.list) = (false, d)
            demo.bring = v
            snapshot(BringSheet().environmentObject(demo), dir + "/sheet-bring-list-sample.png",
                     NSSize(width: 660, height: 640))
            if let dd = sample("bring_dry.json") {
                (v.picked, v.dry) = (firstText(dd["there_path"]) ?? thereProjects(d).first?.path ?? "?", dd)
                demo.bring = v
                snapshot(BringSheet().environmentObject(demo), dir + "/sheet-bring-dry-sample.png",
                         NSSize(width: 660, height: 640))
            }
        }
        if let d = sample("send_back_dry.json") {
            var v = SendBackView(project: Project(["real_path": firstText(d["here_path"]) ?? "/x/shop", "exists": true]),
                                 machine: firstText(d["remote"]) ?? "box")
            (v.loading, v.dry) = (false, d)
            demo.sendBack = v
            snapshot(SendBackSheet().environmentObject(demo), dir + "/sheet-send-back-sample.png",
                     NSSize(width: 600, height: 520))
        }
        if let d = sample("handover_blocked_names.json") {
            let p = Project(["real_path": firstText(d["project"]) ?? "/x/shop", "exists": true])
            snapshot(HandoverSheet(plan: HandoverPlan(project: p, remote: firstText(d["remote"]) ?? "pc", body: "",
                                                      dry: d, blocked: true))
                        .environmentObject(demo), dir + "/sheet-handover-blocked-sample.png",
                     NSSize(width: 560, height: 520))
        }
        if let d = sample("remote_paths.json"), let name = firstText(d["remote"]) {
            // that machine among the ones set up, with the folders it answered
            var ho = (demo.status["handover"] as? [String: Any]) ?? [:]
            var rs = (ho["remotes"] as? [String: Any]) ?? [:]
            rs[name] = ["ssh": "me@" + name, "system": firstText(d["system"]) ?? ""]
            ho["remotes"] = rs
            demo.status["handover"] = ho
            demo.pathsOf = pathMaps(d)
            demo.tab = .machines
            snapshot(MainView().environmentObject(demo), dir + "/machines-paths-sample.png",
                     NSSize(width: 900, height: 520))
        }
        if let d = sample("projects.json") {
            demo.projects = sampleRows(d).map(Project.init).filter { awayLine($0) != nil || $0.sendBackTo != nil }
            for (k, p) in demo.projects.prefix(6).enumerated() {
                demo.selection = p.path
                snapshot(DetailView().environmentObject(demo).frame(width: 900, height: 176),
                         dir + "/detail-phase7-sample-\(k + 1).png", NSSize(width: 900, height: 176))
            }
        }
        exit(0)
    }
    if args.contains("--pickup-only") {
        // Pick Up and Leave a Note: the sheet in each state, the banner when a
        // note arrived, the line over a pickup, Continue Here… on another
        // machine's hit; made-up rows in the shape of the core's JSON, then the
        // core's own samples (AHT_FIXTURES_PHASE4) when there are some.
        // Nothing asks the core or another machine.
        let now = Date().timeIntervalSince1970
        let demo = AppModel()
        demo.demo = true
        (demo.loaded, demo.running) = (true, true)
        demo.status = ["version": "phase 4", "tracked": 6, "hook_installed": true,
                       "agent_clis": ["claude": "/x/claude", "codex": "/x/codex", "kimi": "/x/kimi",
                                      "agy": NSNull(), "vibe": NSNull()],
                       "handover": ["supported": true, "can_reach": true, "default_remote": "box", "remotes": [
                           "box": ["ssh": "me@box", "watch": true, "system": "Linux"],
                           "pc": ["ssh": "me@pc", "watch": false, "system": "Windows"]]]]
        let home = ProcessInfo.processInfo.environment["HOME"] ?? HOME
        let row = { (name: String, incoming: [String: Any]) -> Project in
            Project(["real_path": home + "/code/" + name, "exists": true, "sessions": 5, "bytes": 3_100_000,
                     "agents": ["claude", "codex"],
                     "relay": ["id": "20261027-164000-k3f9", "from_agent": "codex", "to_agent": "claude",
                               "since": now - 1200, "open": true, "incoming": incoming]])
        }
        demo.projects = [
            row("api", ["machine": "pc", "kind": "note", "agent": "codex", "brief": "relay-20261027-164000-k3f9.md",
                        "worked_from": now - 10200, "worked_to": now - 1200]),
            row("paper", ["machine": "box", "kind": "pickup", "agent": "codex"]),
            row("site", ["machine": "pc", "kind": "back", "agent": "codex", "brief": "relay-20261027-164000-k3f9.md",
                         "worked_from": now - 10200, "worked_to": now - 1200,
                         "note_for": ["agent": "claude", "session": "0f3a"]])]
        for (p, name) in zip(demo.projects, ["note-arrived", "picked-up", "handed-back"]) {
            demo.selection = p.path
            snapshot(DetailView().environmentObject(demo).frame(width: 900, height: 176),
                     dir + "/detail-\(name).png", NSSize(width: 900, height: 176))
        }
        let paper = demo.projects[1]
        let brief = """
            # Picked up from box

            From **Codex** on box (Linux), session “fix the login redirect”, last turn 16:40. \
            The folder there: /home/me/code/paper.

            ## Where things stood

            The login redirect now keeps the page the user came from; the cookie check moved \
            into `auth/session.py`. The redirect tests pass; logout is still open.

            ## The latest exchanges

            - **you, 16:12:** after login the redirect goes to / instead of the page I was on
            - **Codex, 16:20:** `next` is kept in `auth/views.py`; added `test_login_keeps_page`.
            - **you, 16:35:** make sure the key sk-…a3f9 is never logged
            - **Codex, 16:40:** the logger masks it now.

            ## Open to-dos

            - logout clears the `next` cookie
            - a line in the changelog

            ## Files changed recently

            - auth/views.py
            - auth/session.py
            - tests/test_login.py

            ## Git there

            Branch fix-login, HEAD 9f8e7d6 “keep the page after login”; 2 commits not pushed; \
            6 files not committed.
            """
        let line = "/opt/homebrew/bin/codex 'You are taking over this project from Codex on box. Read "
            + ".aht/handover/relay-20261027-164512-p4c1.md first: it records where the work stood.'"
        let dry: [String: Any] = [
            "command": "pickup", "applied": false, "blockers": [], "warnings": [], "mode": "new",
            "project": paper.path, "machine": "box",
            "match": ["path": "/home/me/code/paper", "how": "id", "candidates": []],
            "source": ["machine": "box", "agent": "codex", "session": "019a", "title": "fix the login redirect"],
            "sessions": [
                ["agent": "codex", "id": "019a", "title": "fix the login redirect", "updated": now - 300,
                 "state": "working"],
                ["agent": "claude", "id": "0f3a", "title": "cookie check", "updated": now - 7200],
                ["agent": "kimi", "id": "k-77", "title": "changelog", "updated": now - 86400 * 2]],
            "git": ["warning": "On box: branch fix-login, 2 commits not pushed, 6 files not committed. "
                        + "Commit and push there, then pull here."],
            "brief": brief, "relay": NSNull(), "opened": NSNull(), "command_line": NSNull()]
        func sheet(_ d: [String: Any], _ name: String, kind: String = "pickup", project: Project? = nil,
                   machine: String = "box", _ change: (inout PickupView) -> Void = { _ in }) {
            var v = PickupView(project: project ?? paper, machine: machine, kind: kind)
            (v.loading, v.dry) = (false, d)
            v.open = pickupAgent(d, installed: demo.agentCLIs)
            change(&v)
            demo.pickup = v
            snapshot(PickupSheet().environmentObject(demo), dir + "/sheet-\(name).png",
                     NSSize(width: 660, height: 640))
        }
        sheet(dry, "pickup")
        sheet(dry.merging(["match": ["path": "/home/me/src/paper", "how": "home", "candidates": []]]) { $1 },
              "pickup-confirm")
        sheet(dry.merging(["blockers": ["2 folders on box could be this project: pick one (--there)"],
                           "match": ["path": NSNull(), "how": NSNull(),
                                     "candidates": ["/home/me/code/paper", "/home/me/old/paper"]],
                           "sessions": [], "brief": NSNull(), "git": NSNull()]) { $1 }, "pickup-blocked")
        sheet(dry.merging(["mode": "back", "target": "claude",
                           "brief": brief.replacingOccurrences(of: "# Picked up from box",
                                                               with: "# Back from box: what changed")]) { $1 },
              "pickup-back")
        sheet(dry, "pickup-done") { v in
            v.done = ["applied": true, "opened": NSNull(), "command_line": line,
                      "brief": paper.path + "/.aht/handover/relay-20261027-164512-p4c1.md"]
            v.copied = true
        }
        sheet([:], "pickup-unreachable") { v in
            v.said = "ssh: connect to host box port 22: Operation timed out"
        }
        let api = demo.projects[0]
        let note: [String: Any] = [
            "command": "leave-note", "applied": false, "blockers": [], "warnings": [], "mode": "new",
            "project": api.path, "machine": "pc",
            "match": ["path": "C:\\Users\\me\\code\\api", "how": "id", "candidates": []],
            "source": ["agent": "claude", "session": "0f3a", "title": "rate limits"],
            "git": ["warning": "Here: 1 commit not pushed. Push here, then pull on pc."],
            "brief": brief.replacingOccurrences(of: "# Picked up from box", with: "# A note from this Mac"),
            "note_for": NSNull(), "relay": NSNull()]
        sheet(note, "leave-note", kind: "note", project: api, machine: "pc")
        sheet(note.merging(["mode": "back", "note_for": ["agent": "codex", "session": "019a",
                                                          "title": "fix the login redirect"]]) { $1 },
              "hand-back", kind: "note", project: api, machine: "pc") { $0.back = true }
        demo.pickup = nil
        // Search: another machine's hit offers Continue Here…
        let hit = { (machine: Any, title: String, p: String, ago: Double) -> [String: Any] in
            ["machine": machine, "agent": "codex", "session": UUID().uuidString, "project": p, "title": title,
             "live": true, "updated": now - ago,
             "hits": [["role": "user", "snippet": "the \u{02}login\u{03} \u{02}redirect\u{03} goes to /"]]]
        }
        let found: [String: Any] = ["query": "login redirect", "results": [
            hit(NSNull(), "auth tests", home + "/code/paper", 86400 * 3),
            hit("box", "fix the login redirect", "/home/me/code/paper", 300)],
            "machines": [["machine": "box", "reachable": true, "indexed": true, "index_at": now - 60,
                          "results": 1, "error": NSNull()]]]
        demo.tab = .search
        demo.searchEverywhere = true
        (demo.query, demo.searched) = ("login redirect", "login redirect")
        (demo.hits, demo.searchMisses, demo.searchedOn) = (searchHits(found), searchMissed(found), searchAsked(found))
        snapshot(MainView().environmentObject(demo), dir + "/search-continue-here.png",
                 NSSize(width: 900, height: 420))
        // the core's samples, when it has written them
        let dir4 = ProcessInfo.processInfo.environment["AHT_FIXTURES_PHASE4"] ?? ""
        if !dir4.isEmpty && FileManager.default.fileExists(atPath: dir4) {
            func sample(_ n: String) -> [String: Any] {
                let data = try? Data(contentsOf: URL(fileURLWithPath: dir4).appendingPathComponent(n))
                return data.flatMap { try? JSONSerialization.jsonObject(with: $0) } as? [String: Any] ?? [:]
            }
            let at = { (d: [String: Any]) -> Project in
                Project(["real_path": d["project"] as? String ?? paper.path, "exists": true])
            }
            for (n, kind) in [("pickup", "pickup"), ("pickup_blocked", "pickup"), ("pickup_back", "pickup"),
                              ("leave_note", "note")] {
                let d = sample(n + ".json")
                sheet(d, n.replacingOccurrences(of: "_", with: "-") + "-sample", kind: kind, project: at(d),
                      machine: (d["machine"] ?? d["from"] ?? d["on"]) as? String ?? "box")
            }
            demo.pickup = nil
            let pj = sample("projects.json")
            let rows = ((pj["projects"] as? [[String: Any]]) ?? (pj.isEmpty ? [] : [pj])).map(Project.init)
                .filter { $0.incoming != nil }
            demo.projects = rows
            for (k, p) in rows.prefix(4).enumerated() {
                demo.selection = p.path
                snapshot(DetailView().environmentObject(demo).frame(width: 900, height: 176),
                         dir + "/detail-sample-\(k + 1).png", NSSize(width: 900, height: 176))
            }
        }
        exit(0)
    }
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
