// watcher: tells aht when a tracked project moved, was copied or a git
// repository appeared under the watched roots, and starts its periodic work.
//
// It does not search.  aht keeps a short list (~/.aht/run/watch.json) of the
// tracked projects with each folder's id, and the file system answers where
// a folder with a given id is now.  So on a change the watcher asks, for
// each project, "still where the list has it?" (a fraction of a millisecond
// for a hundred projects) and starts
//   aht.py reconcile --quick --notify [--look <folders>]
// only when one is not, or when a marker (.aht/.project-id) or a .git
// appeared in a folder the list does not know.  Changes inside a project
// (saving files, a build) are passed over with one look-up each.
//
// Single-flight: never a second reconcile while one runs (its dialogs must
// not stack); one more run follows when something came up meanwhile.
import Foundation
import CoreServices

setvbuf(stdout, nil, _IOLBF, 0)
let env = ProcessInfo.processInfo.environment
// Derive the paths from the running user's home so this is portable across
// machines/usernames (a LaunchAgent runs as the user).
let AHT = env["AHT_HOME"] ?? NSHomeDirectory() + "/.aht"
let PY = env["AHT_WATCHER_SCRIPT"] ?? NSHomeDirectory() + "/.aht/tools/agent-history-tether/aht.py"
// Pin the system python3 (always present, stdlib-only script) so we don't
// depend on launchd's minimal PATH or on miniconda being installed.
let PYTHON = env["AHT_WATCHER_PYTHON"] ?? "/usr/bin/python3"
let TICK = Double(env["AHT_WATCHER_TICK"] ?? "") ?? 600      // s between runs of the periodic work
let DEBUG = env["AHT_WATCHER_DEBUG"] != nil
let WATCH = AHT + "/run/watch.json"

let roots = Array(CommandLine.arguments.dropFirst()).filter {
    var isDir: ObjCBool = false
    return FileManager.default.fileExists(atPath: $0, isDirectory: &isDir) && isDir.boolValue
}
guard !roots.isEmpty else {
    FileHandle.standardError.write("usage: watcher <existing-root> [root...]\n".data(using: .utf8)!)
    exit(2)
}

func say(_ text: String) {
    let f = DateFormatter()
    f.dateFormat = "yyyy-MM-dd HH:mm:ss"
    print("[\(f.string(from: Date()))] \(text)")
}

// the log of earlier versions held every run's whole answer: start it over
var logStat = stat()
if fstat(1, &logStat) == 0, (logStat.st_mode & S_IFMT) == S_IFREG, logStat.st_size > 1_000_000 {
    ftruncate(1, 0)
    say("the log was started over (it had grown to \(logStat.st_size / 1_000_000) MB)")
}

// ---- the list ---------------------------------------------------------------

struct Project {
    let path: String
    let ino: UInt64
    let vol: String
    let here: Bool
}

var projects: [Project] = []
var projectPaths = Set<String>()        // folded: this disk ignores case
var parents = Set<String>()             // every folder above a project
var gitRepos = Set<String>()
var pruned = Set<String>()
var wantGit = true
var listStamp = timespec()
var handled = ""                        // what did not match when aht last ran

func fold(_ p: String) -> String { p.lowercased() }

func loadList() {
    var st = stat()
    if stat(WATCH, &st) != 0 { return }
    if st.st_mtimespec.tv_sec == listStamp.tv_sec && st.st_mtimespec.tv_nsec == listStamp.tv_nsec
        && !projects.isEmpty { return }
    guard let data = FileManager.default.contents(atPath: WATCH),
          let j = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
    listStamp = st.st_mtimespec
    projects = ((j["projects"] as? [[String: Any]]) ?? []).compactMap { r in
        guard let p = r["path"] as? String else { return nil }
        return Project(path: p, ino: (r["ino"] as? NSNumber)?.uint64Value ?? 0,
                       vol: r["vol"] as? String ?? "", here: r["here"] as? Bool ?? false)
    }
    projectPaths = Set(projects.map { fold($0.path) })
    parents = []
    for p in projects {
        var up = (p.path as NSString).deletingLastPathComponent
        while up.count > 1 && parents.insert(fold(up)).inserted {
            up = (up as NSString).deletingLastPathComponent
        }
    }
    gitRepos = Set(((j["git"] as? [String]) ?? []).map(fold))
    pruned = Set((j["prune"] as? [String]) ?? [])
    wantGit = j["git_wanted"] as? Bool ?? true
}

// ---- where is each project now? ---------------------------------------------

func inTrash(_ p: String) -> Bool {
    p.split(separator: "/").contains { [".trash", ".trashes"].contains($0.lowercased()) }
}

/// The folder with this id on that volume, wherever it is now.
func pathOf(_ vol: String, _ ino: UInt64) -> String? {
    var vs = stat()
    if ino == 0 || vol.isEmpty || stat(vol, &vs) != 0 { return nil }
    let fd = open("/.vol/\(vs.st_dev)/\(ino)", O_RDONLY | O_EVTONLY)
    if fd < 0 { return nil }
    defer { close(fd) }
    var buf = [CChar](repeating: 0, count: Int(MAXPATHLEN))
    if fcntl(fd, F_GETPATH, &buf) != 0 { return nil }
    return String(cString: buf)
}

func whereNow(_ e: Project) -> String? {
    var st = stat()
    if let p = pathOf(e.vol, e.ino), lstat(p, &st) == 0, UInt64(st.st_ino) == e.ino, !inTrash(p) {
        return p
    }
    return lstat(e.path, &st) == 0 ? e.path : nil
}

/// What is not where the list has it, as one text ("" when all is).
func mismatch() -> String {
    var out: [String] = []
    for e in projects {
        let now = whereNow(e)
        if now != (e.here ? e.path : nil) { out.append("\(e.path) -> \(now ?? "gone")") }
    }
    return out.joined(separator: "\n")
}

func insideProject(_ p: String) -> Bool {
    var cur = fold(p)
    while cur.count > 1 {
        if projectPaths.contains(cur) { return true }
        cur = (cur as NSString).deletingLastPathComponent
    }
    return false
}

/// A folder the walk would pass over: hidden, or one of the names aht leaves out.
func passedOver(_ p: String) -> Bool {
    let home = NSHomeDirectory()
    let rel = p.hasPrefix(home + "/") ? String(p.dropFirst(home.count + 1)) : p
    return rel.split(separator: "/").contains { $0.hasPrefix(".") || pruned.contains(String($0)) }
}

func insideRepo(_ p: String) -> Bool {
    var cur = (fold(p) as NSString).deletingLastPathComponent
    while cur.count > 1 {
        if gitRepos.contains(cur) { return true }
        cur = (cur as NSString).deletingLastPathComponent
    }
    return false
}

// ---- running aht --------------------------------------------------------------

let queue = DispatchQueue(label: "com.claudeproject.watcher")   // serial
var pending: DispatchWorkItem?
var firstAt: Date?
var running = false
var wantQuick = false
var wantFull = false
var look = Set<String>()
var why = ""

func launch() {
    pending = nil
    firstAt = nil
    let full = wantFull, dirs = look.sorted(), reason = why
    wantQuick = false; wantFull = false; look = []; why = ""
    handled = mismatch()
    running = true
    let p = Process()
    p.executableURL = URL(fileURLWithPath: PYTHON)
    p.arguments = [PY, "reconcile", "--notify"] + (full ? [] : ["--quick"]) + ["--roots"] + roots
        + (dirs.isEmpty || full ? [] : ["--look"] + dirs)
    let pipe = Pipe()
    p.standardOutput = pipe
    let began = Date()
    do { try p.run() }
    catch {
        running = false
        say("reconcile did not start: \(error)")
        return
    }
    DispatchQueue.global().async {
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        p.waitUntilExit()
        queue.async {
            running = false
            report(data, p.terminationStatus, Date().timeIntervalSince(began), full, reason)
            loadList()
            // what aht just saw and left as it is (a move you declined) is
            // not brought up again; what came up meanwhile is
            handled = mismatch()
            if wantQuick || wantFull || !look.isEmpty { schedule() }
        }
    }
}

/// One line for a run that did or found something, not its whole answer.
func report(_ data: Data, _ status: Int32, _ took: Double, _ full: Bool, _ reason: String) {
    let secs = String(format: "%.1f s", took)
    guard status == 0, let j = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
        say("reconcile ended with \(status) after \(secs) (\(reason))")
        return
    }
    func n(_ k: String) -> Int { (j[k] as? [Any])?.count ?? 0 }
    var bits: [String] = []
    if n("applied_moves") > 0 { bits.append("\(n("applied_moves")) relinked") }
    if n("applied_copies") > 0 { bits.append("\(n("applied_copies")) copied") }
    if n("moves") > n("applied_moves") { bits.append("\(n("moves") - n("applied_moves")) moved, not relinked") }
    if n("copies") > n("applied_copies") { bits.append("\(n("copies") - n("applied_copies")) copies left as they are") }
    if n("news") > 0 { bits.append("\(n("news")) new") }
    if n("conflicts") > 0 { bits.append("\(n("conflicts")) NOT relinked") }
    let walked = j["walked"] as? Bool ?? full
    if bits.isEmpty && !walked && !DEBUG { return }
    say((bits.isEmpty ? "nothing to do" : bits.joined(separator: ", "))
        + " (\(secs)\(walked ? ", with the walk of the watched folders" : ""); \(reason))")
}

func schedule() {
    if running { return }               // it runs again when this one ends
    let now = Date()
    if firstAt == nil { firstAt = now }
    pending?.cancel()
    let work = DispatchWorkItem { if !running { launch() } }
    pending = work
    // a short quiet moment, so a burst is one run; never held back for long
    let at = min(now.addingTimeInterval(0.15), firstAt!.addingTimeInterval(1.5))
    queue.asyncAfter(deadline: .now() + max(0, at.timeIntervalSince(now)), execute: work)
}

func note(_ reason: String) {
    if why.isEmpty { why = reason }
}

// ---- what happened under the roots ------------------------------------------------

let dropped = UInt32(kFSEventStreamEventFlagMustScanSubDirs | kFSEventStreamEventFlagUserDropped
    | kFSEventStreamEventFlagKernelDropped | kFSEventStreamEventFlagEventIdsWrapped
    | kFSEventStreamEventFlagRootChanged)

let callback: FSEventStreamCallback = { _, _, count, paths, flags, _ in
    // folder-level events: each path is a folder something changed in
    let list = unsafeBitCast(paths, to: NSArray.self) as! [String]
    loadList()
    var check = false
    for i in 0..<count {
        var p = list[i]
        while p.count > 1 && p.hasSuffix("/") { p.removeLast() }
        if flags[i] & dropped != 0 {
            wantFull = true             // events were lost: only a walk knows what happened
            note("events were dropped")
            continue
        }
        let name = (p as NSString).lastPathComponent
        let up = (p as NSString).deletingLastPathComponent
        if name == ".aht" || name == ".claude" {
            // a marker in a folder the list does not have: a copy, or a project from elsewhere
            if !projectPaths.contains(fold(up)) && !inTrash(up)
                && FileManager.default.fileExists(atPath: p + "/.project-id") {
                look.insert(up)
                note("a marker in \(up)")
            }
        } else if name == ".git" {
            if wantGit && !gitRepos.contains(fold(up)) && !passedOver(up) && !insideRepo(up)
                && !inTrash(up) && FileManager.default.fileExists(atPath: p) {
                look.insert(up)
                note("a git repository in \(up)")
            }
        } else if parents.contains(fold(p)) || !insideProject(p) {
            check = true                // a folder a project could have left or come to
        }
    }
    if check {
        let m = mismatch()
        if m != handled {
            wantQuick = true
            note(m.isEmpty ? "all in place again" : "moved: " + m.replacingOccurrences(of: "\n", with: "; "))
        }
    }
    if wantQuick || wantFull || !look.isEmpty { schedule() }
}

var ctx = FSEventStreamContext()
guard let stream = FSEventStreamCreate(
    kCFAllocatorDefault, callback, &ctx, roots as CFArray,
    FSEventStreamEventId(kFSEventStreamEventIdSinceNow), 0.1,
    UInt32(kFSEventStreamCreateFlagNoDefer | kFSEventStreamCreateFlagWatchRoot
           | kFSEventStreamCreateFlagUseCFTypes)
) else {
    FileHandle.standardError.write("failed to create FSEventStream\n".data(using: .utf8)!)
    exit(1)
}
FSEventStreamSetDispatchQueue(stream, queue)
FSEventStreamStart(stream)

// the periodic work (Keep in sync, backups, the search index, new history
// stores) starts from a reconcile; without a change to react to, a timer
// runs one.  It also finds what moved while this was not running
func regularLook() {
    loadList()
    wantQuick = true
    note("the regular look")
    schedule()
}
let timer = DispatchSource.makeTimerSource(queue: queue)
// with some leeway, so the system can run it along with other work
timer.schedule(deadline: .now() + TICK, repeating: TICK, leeway: .seconds(Int(min(60, TICK / 10))))
timer.setEventHandler { regularLook() }
timer.resume()
queue.async { regularLook() }           // once at the start, at once
dispatchMain()
