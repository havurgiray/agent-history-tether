// watcher: recursively watch project roots; on debounced change, run
//   aht.py reconcile --notify --roots <roots...>
// Single-flight: never launches a second reconcile while one is running (so
// GUI dialogs can't stack); re-runs once if more changes arrived meanwhile.
import Foundation
import CoreServices

// Derive the script path from the running user's home so this is portable
// across machines/usernames (a LaunchAgent runs as the user).
let PY = NSHomeDirectory() + "/.aht/tools/agent-history-tether/aht.py"

let roots = Array(CommandLine.arguments.dropFirst()).filter {
    var isDir: ObjCBool = false
    return FileManager.default.fileExists(atPath: $0, isDirectory: &isDir) && isDir.boolValue
}
guard !roots.isEmpty else {
    FileHandle.standardError.write("usage: watcher <existing-root> [root...]\n".data(using: .utf8)!)
    exit(2)
}

let queue = DispatchQueue(label: "com.claudeproject.watcher")   // serial
var pending: DispatchWorkItem?
var running = false
var dirty = false

func launch() {
    running = true; dirty = false
    let p = Process()
    // Pin the system python3 (always present, stdlib-only script) so we don't
    // depend on launchd's minimal PATH or on miniconda being installed.
    p.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
    p.arguments = [PY, "reconcile", "--notify", "--roots"] + roots
    p.terminationHandler = { _ in
        queue.async { running = false; if dirty { launch() } }
    }
    do { try p.run() }
    catch {
        running = false
        FileHandle.standardError.write("reconcile launch failed: \(error)\n".data(using: .utf8)!)
    }
}

func schedule() {
    dirty = true
    pending?.cancel()
    let work = DispatchWorkItem { if !running { launch() } }
    pending = work
    queue.asyncAfter(deadline: .now() + 2.0, execute: work)   // debounce bursts
}

let callback: FSEventStreamCallback = { _, _, _, _, _, _ in
    queue.async { schedule() }
}

var ctx = FSEventStreamContext()
guard let stream = FSEventStreamCreate(
    kCFAllocatorDefault, callback, &ctx, roots as CFArray,
    FSEventStreamEventId(kFSEventStreamEventIdSinceNow), 1.0,
    UInt32(kFSEventStreamCreateFlagNoDefer | kFSEventStreamCreateFlagWatchRoot)
) else {
    FileHandle.standardError.write("failed to create FSEventStream\n".data(using: .utf8)!)
    exit(1)
}
FSEventStreamSetDispatchQueue(stream, queue)
FSEventStreamStart(stream)
dispatchMain()
