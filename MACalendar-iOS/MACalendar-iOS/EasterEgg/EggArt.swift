import SwiftUI

/// The drawing kit the built-in Easter-egg figures are made with, and the
/// figures themselves (`EggFigures.swift`).
///
/// **Anime cel style, drawn in code.** Every figure is layered vector parts in
/// a 200×200 box facing RIGHT (the direction of travel; the overlay mirrors it
/// for leftward motion): a flat base colour, one hard-edged shade band clipped
/// inside it, white glints, and a bold ink outline. Moving parts — legs, wings,
/// tails, rotors — are drawn rotated about a pivot by the figure's `pose`, so a
/// figure is alive without any image assets.
///
/// SwiftUI only (no UIKit), so the same code renders on the Mac for previews.
struct EggPose {
    /// Seconds since the figure appeared.
    var t: Double
    /// 0…1 through one gait / flap cycle.
    var cycle: Double { t * speed - floor(t * speed) }
    /// Cycles per second — a galloping dog is quicker than a flapping dragon.
    var speed: Double = 2.2
    /// Sine of the cycle, the swing most parts follow.
    var swing: Double { sin(cycle * 2 * .pi) }
    var swing2: Double { sin((cycle + 0.5) * 2 * .pi) }
}

extension Color {
    /// 0xRRGGBB. Named apart from the app's optional `Color(hex:)` on purpose.
    init(egg hex: UInt32, _ opacity: Double = 1) {
        self.init(.sRGB, red: Double((hex >> 16) & 0xff) / 255,
                  green: Double((hex >> 8) & 0xff) / 255,
                  blue: Double(hex & 0xff) / 255, opacity: opacity)
    }
}

/// Paints one figure in its 200-unit box. `ctx` is already scaled.
struct EggPainter {
    var ctx: GraphicsContext
    static let ink = Color(egg: 0x1b1330)
    var line: CGFloat = 4
    /// "Outline only": no fills, glowing white lines — the screen shows through.
    var outlineOnly = false

    /// A part: base fill, an optional shade clipped inside it, the outline.
    func part(_ d: String, _ base: Color, shade: Color? = nil, _ shadeD: String? = nil,
              outline: Bool = true, width: CGFloat? = nil) {
        part(EggPath(d), base, shade: shade, shadeD.map { EggPath($0) }, outline: outline, width: width)
    }

    func part(_ p: Path, _ base: Color, shade: Color? = nil, _ shadeP: Path? = nil,
              outline: Bool = true, width: CGFloat? = nil) {
        if outlineOnly {
            ctx.stroke(p, with: .color(.white), style: StrokeStyle(lineWidth: width ?? line, lineCap: .round, lineJoin: .round))
            return
        }
        ctx.fill(p, with: .color(base))
        if let shade, let shadeP {
            ctx.drawLayer { l in
                l.clip(to: p)
                l.fill(shadeP, with: .color(shade))
            }
        }
        if outline {
            ctx.stroke(p, with: .color(Self.ink),
                       style: StrokeStyle(lineWidth: width ?? line, lineCap: .round, lineJoin: .round))
        }
    }

    /// A stroke only — whiskers, fur tufts, speed marks drawn on the figure.
    func stroke(_ d: String, _ color: Color = EggPainter.ink, width: CGFloat = 3) {
        ctx.stroke(EggPath(d), with: .color(outlineOnly ? .white : color),
                   style: StrokeStyle(lineWidth: width, lineCap: .round, lineJoin: .round))
    }

    func fill(_ d: String, _ color: Color) {
        if outlineOnly { return }
        ctx.fill(EggPath(d), with: .color(color))
    }

    func ellipse(_ cx: CGFloat, _ cy: CGFloat, _ rx: CGFloat, _ ry: CGFloat) -> Path {
        Path(ellipseIn: CGRect(x: cx - rx, y: cy - ry, width: rx * 2, height: ry * 2))
    }

    /// The anime eye: a tall dark oval, a coloured iris low in it, two glints.
    func eye(_ cx: CGFloat, _ cy: CGFloat, _ r: CGFloat, iris: Color, blink: Bool = false) {
        if blink {
            stroke("M\(cx - r) \(cy) Q\(cx) \(cy + r * 0.7) \(cx + r) \(cy)", width: 3)
            return
        }
        let white = ellipse(cx, cy, r * 0.95, r * 1.25)
        if outlineOnly {
            ctx.stroke(white, with: .color(.white), lineWidth: 2.5)
            ctx.fill(ellipse(cx + r * 0.1, cy + r * 0.3, r * 0.4, r * 0.5), with: .color(.white))
            return
        }
        ctx.fill(white, with: .color(.white))
        ctx.fill(ellipse(cx + r * 0.1, cy + r * 0.15, r * 0.72, r * 1.0), with: .color(Self.ink))
        ctx.fill(ellipse(cx + r * 0.1, cy + r * 0.45, r * 0.55, r * 0.55), with: .color(iris))
        ctx.fill(ellipse(cx - r * 0.18, cy - r * 0.3, r * 0.32, r * 0.38), with: .color(.white))
        ctx.fill(ellipse(cx + r * 0.38, cy + r * 0.55, r * 0.14, r * 0.14), with: .color(.white))
        ctx.stroke(white, with: .color(Self.ink), lineWidth: 3)
    }

    /// Cheek blush — two soft pink ovals.
    func blush(_ cx: CGFloat, _ cy: CGFloat, _ r: CGFloat = 7) {
        if outlineOnly { return }
        ctx.fill(ellipse(cx, cy, r, r * 0.55), with: .color(Color(egg: 0xff7aa2, 0.55)))
    }

    /// Glints: small white strokes that sell the "shiny cel" look.
    func glint(_ d: String, width: CGFloat = 3.5) {
        ctx.stroke(EggPath(d), with: .color(.white.opacity(0.9)),
                   style: StrokeStyle(lineWidth: width, lineCap: .round))
    }

    /// Draw `body` rotated by `degrees` about (px, py) — a leg at the hip, a wing at the shoulder.
    func rotated(_ degrees: Double, _ px: CGFloat, _ py: CGFloat, _ body: (EggPainter) -> Void) {
        var c = ctx
        c.translateBy(x: px, y: py)
        c.rotate(by: .degrees(degrees))
        c.translateBy(x: -px, y: -py)
        body(EggPainter(ctx: c, line: line, outlineOnly: outlineOnly))
    }

    /// Draw `body` scaled about (px, py) — a wing folding, a flame flickering.
    func scaled(_ sx: CGFloat, _ sy: CGFloat, _ px: CGFloat, _ py: CGFloat, _ body: (EggPainter) -> Void) {
        var c = ctx
        c.translateBy(x: px, y: py)
        c.scaleBy(x: sx, y: sy)
        c.translateBy(x: -px, y: -py)
        body(EggPainter(ctx: c, line: line, outlineOnly: outlineOnly))
    }
}

/// An SVG-style path: absolute M, L, H, V, C, Q, Z. Enough to author figures
/// the way they are usually sketched, without a parser worth testing on its own.
func EggPath(_ d: String) -> Path {
    var p = Path()
    var nums: [CGFloat] = []
    var cmd: Character = "M"
    var cur = CGPoint.zero
    func flush() {
        switch cmd {
        case "M":
            var i = 0
            while i + 1 < nums.count {
                let pt = CGPoint(x: nums[i], y: nums[i + 1])
                if i == 0 { p.move(to: pt) } else { p.addLine(to: pt) }
                cur = pt; i += 2
            }
        case "L":
            var i = 0
            while i + 1 < nums.count { cur = CGPoint(x: nums[i], y: nums[i + 1]); p.addLine(to: cur); i += 2 }
        case "H":
            for x in nums { cur = CGPoint(x: x, y: cur.y); p.addLine(to: cur) }
        case "V":
            for y in nums { cur = CGPoint(x: cur.x, y: y); p.addLine(to: cur) }
        case "C":
            var i = 0
            while i + 5 < nums.count {
                cur = CGPoint(x: nums[i + 4], y: nums[i + 5])
                p.addCurve(to: cur, control1: CGPoint(x: nums[i], y: nums[i + 1]),
                           control2: CGPoint(x: nums[i + 2], y: nums[i + 3]))
                i += 6
            }
        case "Q":
            var i = 0
            while i + 3 < nums.count {
                cur = CGPoint(x: nums[i + 2], y: nums[i + 3])
                p.addQuadCurve(to: cur, control: CGPoint(x: nums[i], y: nums[i + 1]))
                i += 4
            }
        case "Z":
            p.closeSubpath()
        default: break
        }
        nums = []
    }
    var token = ""
    func endNumber() {
        if let v = Double(token) { nums.append(CGFloat(v)) }
        token = ""
    }
    for ch in d {
        if "MLHVCQZ".contains(ch) {
            endNumber(); flush(); cmd = ch
            if ch == "Z" { flush(); cmd = " " }
        } else if ch == "-" {
            endNumber(); token = "-"
        } else if ch.isNumber || ch == "." {
            token.append(ch)
        } else {
            endNumber()
        }
    }
    endNumber(); flush()
    return p
}
