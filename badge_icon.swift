// badge_icon: composite per-agent marks and/or a git mark onto a folder icon.
//   badge_icon set <folder> [git] [agent:claude agent:codex ...]
//   badge_icon clear <folder>
//   badge_icon preview <out.png> [git] [agent:...]
//
// Agent marks are white-ringed colored discs with a white glyph, in the
// lower-right band:  1 agent -> one full-size disc;  2 -> two smaller side by
// side;  3 -> three smaller still;  4+ -> one slate disc showing the COUNT.
// The git "+" (black, centered) is independent of the agent marks.
// Same visual spec as windows/src/winbadge.py and the Linux emblems.
import AppKit
import CoreText
import UniformTypeIdentifiers

let AGENT_COLORS: [String: (CGFloat, CGFloat, CGFloat)] = [
    "claude":   (217/255.0, 119/255.0,  87/255.0),
    "gemini":   ( 66/255.0, 133/255.0, 244/255.0),
    "cursor":   ( 26/255.0,  26/255.0,  26/255.0),
    "opencode": (249/255.0, 115/255.0,  22/255.0),
    "codex":    ( 16/255.0, 163/255.0, 127/255.0),
    "copilot":  (110/255.0,  64/255.0, 201/255.0),
    "kimi":     (124/255.0,  58/255.0, 237/255.0),
]
let COUNT_COLOR: (CGFloat, CGFloat, CGFloat) = (51/255.0, 58/255.0, 66/255.0)

func folderBase(_ size: CGFloat) -> NSImage {
    let img = NSImage(size: NSSize(width: size, height: size))
    img.lockFocus()
    NSWorkspace.shared.icon(for: UTType.folder)
        .draw(in: NSRect(x: 0, y: 0, width: size, height: size), from: .zero, operation: .copy, fraction: 1)
    img.unlockFocus()
    return img
}

func glyphFor(_ agent: String) -> String {
    switch agent {
    case "gemini": return "diamond"
    case "cursor": return "triangle"
    case "opencode": return "square"
    case "codex": return "ring"
    case "copilot": return "bar"
    case "kimi": return "crescent"
    default: return "asterisk"          // claude + neutral fallback
    }
}

func drawDisc(_ ctx: CGContext, cx: CGFloat, cy: CGFloat, d: CGFloat,
              rgb: (CGFloat, CGFloat, CGFloat), glyph: String) {
    let r = d * 0.42, ring = d * 0.5 - r
    let color = NSColor(srgbRed: rgb.0, green: rgb.1, blue: rgb.2, alpha: 1).cgColor
    ctx.setFillColor(NSColor.white.cgColor)
    ctx.fillEllipse(in: CGRect(x: cx - r - ring, y: cy - r - ring,
                               width: (r + ring) * 2, height: (r + ring) * 2))
    ctx.setFillColor(color)
    ctx.fillEllipse(in: CGRect(x: cx - r, y: cy - r, width: r * 2, height: r * 2))
    ctx.setFillColor(NSColor.white.cgColor)
    ctx.setStrokeColor(NSColor.white.cgColor)
    ctx.setLineCap(.round)
    switch glyph {
    case "asterisk":
        ctx.setLineWidth(d * 0.12)
        let spoke = d * 0.30
        for deg in stride(from: 0.0, to: 180.0, by: 60.0) {
            let a = deg * .pi / 180, dx = CGFloat(cos(a)) * spoke, dy = CGFloat(sin(a)) * spoke
            ctx.move(to: CGPoint(x: cx - dx, y: cy - dy))
            ctx.addLine(to: CGPoint(x: cx + dx, y: cy + dy))
        }
        ctx.strokePath()
    case "ring":
        ctx.setLineWidth(d * 0.11)
        ctx.strokeEllipse(in: CGRect(x: cx - d * 0.21, y: cy - d * 0.21,
                                     width: d * 0.42, height: d * 0.42))
    case "diamond":
        ctx.move(to: CGPoint(x: cx, y: cy + d * 0.26))
        ctx.addLine(to: CGPoint(x: cx + d * 0.26, y: cy))
        ctx.addLine(to: CGPoint(x: cx, y: cy - d * 0.26))
        ctx.addLine(to: CGPoint(x: cx - d * 0.26, y: cy))
        ctx.closePath(); ctx.fillPath()
    case "square":
        ctx.fill(CGRect(x: cx - d * 0.19, y: cy - d * 0.19,
                        width: d * 0.38, height: d * 0.38))
    case "bar":
        ctx.fill(CGRect(x: cx - d * 0.22, y: cy - d * 0.075,
                        width: d * 0.44, height: d * 0.15))
    case "triangle":
        ctx.move(to: CGPoint(x: cx, y: cy + d * 0.24))
        ctx.addLine(to: CGPoint(x: cx + d * 0.22, y: cy - d * 0.16))
        ctx.addLine(to: CGPoint(x: cx - d * 0.22, y: cy - d * 0.16))
        ctx.closePath(); ctx.fillPath()
    case "crescent":
        ctx.fillEllipse(in: CGRect(x: cx - d * 0.24, y: cy - d * 0.24,
                                   width: d * 0.48, height: d * 0.48))
        ctx.setFillColor(color)
        ctx.fillEllipse(in: CGRect(x: cx - d * 0.24 + d * 0.14, y: cy - d * 0.24 + d * 0.08,
                                   width: d * 0.44, height: d * 0.44))
    default:
        break
    }
}

func drawCount(_ ctx: CGContext, cx: CGFloat, cy: CGFloat, d: CGFloat, count: Int) {
    drawDisc(ctx, cx: cx, cy: cy, d: d, rgb: COUNT_COLOR, glyph: "")
    let text = String(min(count, 9)) as NSString
    let font = NSFont.boldSystemFont(ofSize: d * 0.58)
    let attrs: [NSAttributedString.Key: Any] = [.font: font, .foregroundColor: NSColor.white]
    let ts = text.size(withAttributes: attrs)
    text.draw(at: NSPoint(x: cx - ts.width / 2, y: cy - ts.height / 2), withAttributes: attrs)
}

func drawAgents(_ ctx: CGContext, _ size: CGFloat, _ agents: [String]) {
    // (diameter, centres) in icon fractions, bottom-left origin
    let inset = size * 0.05
    switch agents.count {
    case 0: return
    case 1:
        let d = size * 0.345
        drawDisc(ctx, cx: size - d/2 - inset, cy: d/2 + inset, d: d,
                 rgb: AGENT_COLORS[agents[0]] ?? AGENT_COLORS["claude"]!,
                 glyph: glyphFor(agents[0]))
    case 2:
        let d = size * 0.26, gap = size * 0.02
        var cx = size - d/2 - size * 0.04
        for a in agents.reversed() {
            drawDisc(ctx, cx: cx, cy: d/2 + inset, d: d,
                     rgb: AGENT_COLORS[a] ?? AGENT_COLORS["claude"]!,
                     glyph: glyphFor(a))
            cx -= d + gap
        }
    case 3:
        let d = size * 0.205, gap = size * 0.02
        var cx = size - d/2 - size * 0.04
        for a in agents.reversed() {
            drawDisc(ctx, cx: cx, cy: d/2 + inset, d: d,
                     rgb: AGENT_COLORS[a] ?? AGENT_COLORS["claude"]!,
                     glyph: glyphFor(a))
            cx -= d + gap
        }
    default:
        let d = size * 0.345
        drawCount(ctx, cx: size - d/2 - inset, cy: d/2 + inset, d: d,
                  count: agents.count)
    }
}

func plusPath(_ fontName: String) -> CGPath? {
    let f = CTFontCreateWithName(fontName as CFString, 200, nil)
    var g = CTFontGetGlyphWithName(f, "plus" as CFString)
    if g == 0 {
        var chars = Array("+".utf16); var gs = [CGGlyph](repeating: 0, count: chars.count)
        CTFontGetGlyphsForCharacters(f, &chars, &gs, chars.count); g = gs[0]
    }
    return CTFontCreatePathForGlyph(f, g, nil)
}

func drawGit(_ ctx: CGContext, _ size: CGFloat) {
    guard let p = plusPath("Courier-BoldOblique") else { return }
    let b = p.boundingBox, cx = size*0.5, cy = size*0.47
    let scale = (size*0.30) / b.height
    var t = CGAffineTransform(translationX: cx, y: cy).scaledBy(x: scale, y: scale).translatedBy(x: -b.midX, y: -b.midY)
    guard let tp = p.copy(using: &t) else { return }
    ctx.addPath(tp); ctx.setFillColor(NSColor.black.cgColor); ctx.fillPath()
}

func composite(_ size: CGFloat, git: Bool, agents: [String]) -> NSImage {
    let img = folderBase(size)
    img.lockFocus()
    let ctx = NSGraphicsContext.current!.cgContext
    if git { drawGit(ctx, size) }
    drawAgents(ctx, size, agents)
    img.unlockFocus()
    return img
}

func multiRep(git: Bool, agents: [String]) -> NSImage {
    let out = NSImage(size: NSSize(width: 512, height: 512))
    for s: CGFloat in [512, 256, 128, 64, 32, 16] {
        let one = composite(s, git: git, agents: agents)
        if let tiff = one.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff) {
            rep.size = NSSize(width: s, height: s); out.addRepresentation(rep)
        }
    }
    return out
}

func writePNG(_ img: NSImage, _ path: String) -> Bool {
    guard let t = img.tiffRepresentation, let r = NSBitmapImageRep(data: t),
          let p = r.representation(using: .png, properties: [:]) else { return false }
    return (try? p.write(to: URL(fileURLWithPath: path))) != nil
}

let a = CommandLine.arguments
func err(_ s: String) { FileHandle.standardError.write(s.data(using: .utf8)!) }
guard a.count >= 3 else {
    err("usage: badge_icon <set|clear|preview> <path> [git] [agent:<name>...]\n"); exit(2)
}
let mode = a[1], path = a[2]
var git = false
var agents: [String] = []
for m in a.dropFirst(3) {
    if m == "git" { git = true }
    else if m.hasPrefix("agent:") {
        let n = String(m.dropFirst(6))
        if !agents.contains(n) { agents.append(n) }
    } else if m == "claude" {              // legacy mark spelling
        if !agents.contains("claude") { agents.append("claude") }
    }
}
switch mode {
case "clear":
    NSWorkspace.shared.setIcon(nil, forFile: path, options: []); exit(0)
case "set":
    if !git && agents.isEmpty { err("set needs >=1 mark; use clear to remove\n"); exit(2) }
    exit(NSWorkspace.shared.setIcon(multiRep(git: git, agents: agents),
                                    forFile: path, options: []) ? 0 : 1)
case "preview":
    exit(writePNG(composite(512, git: git, agents: agents.isEmpty && !git ? ["claude"] : agents), path) ? 0 : 1)
default:
    err("unknown mode\n"); exit(2)
}
