import SwiftUI

/// The subgraphic: what trails behind the main graphic. Drawn along the
/// figure's recent path (the frames a moment ago), fading and shrinking with
/// age; a figure that stays put (pop, peek) gets its trail circling it instead.
enum EggTrails {
    static func draw(_ kind: EggTrail, _ ctx: GraphicsContext, box: CGFloat, t: Double,
                     samples: [(EggFrame, Int)], here: EggFrame, ground: Bool) {
        guard kind != .none, kind != .auto else { return }
        let still = samples.last.map { hypot($0.0.center.x - here.center.x, $0.0.center.y - here.center.y) < box * 0.08 } ?? true
        var points: [(CGPoint, Int)] = samples.map { f, k in
            var c = f.center
            // Behind the figure, not under its middle.
            c.x += (f.flip ? 1 : -1) * box * 0.3
            if ground { c.y += box * 0.36 }
            return (c, k)
        }
        if still {
            points = (1...9).map { k in
                let a = t * 2.2 + Double(k) * 0.7
                return (CGPoint(x: here.center.x + box * 0.6 * CGFloat(cos(a)),
                                y: here.center.y + box * 0.5 * CGFloat(sin(a))), k)
            }
        }
        if kind == .rainbow { ribbon(ctx, [here.center] + points.map(\.0), box: box, opacity: here.opacity); return }
        for (pt, k) in points {
            let age = Double(k) / 10
            let r = box * 0.065 * CGFloat(1 - age * 0.6)
            var c = ctx
            c.opacity = (0.95 - age * 0.85) * here.opacity
            let wobble = CGFloat(sin(t * 7 + Double(k))) * box * 0.03
            let at = CGPoint(x: pt.x, y: pt.y + (ground && kind == .pawPrints ? 0 : wobble))
            shape(kind, c, at, r, k: k, t: t)
        }
    }

    private static func shape(_ kind: EggTrail, _ ctx: GraphicsContext, _ p: CGPoint, _ r: CGFloat, k: Int, t: Double) {
        let ink = EggPainter.ink
        switch kind {
        case .sparkles:
            eggSparkle(ctx, p, r * 1.2, k % 2 == 0 ? .white : Color(egg: 0xffe066))
        case .stars:
            let star = star5(p, r * 1.2, spin: t * 3 + Double(k))
            ctx.fill(star, with: .color(Color(egg: k % 3 == 0 ? 0xff9ad5 : 0xffd23a)))
            ctx.stroke(star, with: .color(ink), lineWidth: 1.5)
        case .hearts:
            let h = heart(p, r * 1.1)
            ctx.fill(h, with: .color(Color(egg: k % 2 == 0 ? 0xff4d8d : 0xff9ab8)))
            ctx.stroke(h, with: .color(ink), lineWidth: 1.5)
        case .pawPrints:
            let side: CGFloat = k % 2 == 0 ? -1 : 1
            paw(ctx, CGPoint(x: p.x, y: p.y + side * r * 0.8), r * 0.9)
        case .flames:
            let flick = 1 + 0.2 * CGFloat(sin(t * 18 + Double(k)))
            let outer = drop(p, r * 1.3 * flick)
            ctx.fill(outer, with: .color(Color(egg: 0xff6a2a)))
            ctx.fill(drop(CGPoint(x: p.x, y: p.y + r * 0.25), r * 0.75 * flick), with: .color(Color(egg: 0xffd23a)))
        case .bubbles:
            let c = Path(ellipseIn: CGRect(x: p.x - r, y: p.y - r, width: r * 2, height: r * 2))
            ctx.fill(c, with: .color(Color(egg: 0x9fe3ff, 0.25)))
            ctx.stroke(c, with: .color(.white), lineWidth: 2)
            ctx.fill(Path(ellipseIn: CGRect(x: p.x - r * 0.5, y: p.y - r * 0.55, width: r * 0.4, height: r * 0.3)), with: .color(.white))
        case .petals:
            var c = ctx
            c.translateBy(x: p.x, y: p.y)
            c.rotate(by: .radians(t * 2 + Double(k)))
            let petal = Path(ellipseIn: CGRect(x: -r, y: -r * 0.5, width: r * 2, height: r))
            c.fill(petal, with: .color(Color(egg: k % 2 == 0 ? 0xffb7d0 : 0xffd6e5)))
            c.stroke(petal, with: .color(Color(egg: 0xe0629a)), lineWidth: 1)
        case .notes:
            var n = Path()
            n.addEllipse(in: CGRect(x: p.x - r * 0.7, y: p.y, width: r * 1.1, height: r * 0.8))
            ctx.fill(n, with: .color(ink))
            var stem = Path()
            stem.move(to: CGPoint(x: p.x + r * 0.35, y: p.y + r * 0.3))
            stem.addLine(to: CGPoint(x: p.x + r * 0.35, y: p.y - r * 1.2))
            stem.addQuadCurve(to: CGPoint(x: p.x + r * 1.1, y: p.y - r * 0.4), control: CGPoint(x: p.x + r * 1.1, y: p.y - r))
            ctx.stroke(stem, with: .color(ink), style: StrokeStyle(lineWidth: 2.2, lineCap: .round))
        case .clouds:
            for (dx, dy, s) in [(-0.7, 0.15, 0.6), (0.0, -0.15, 0.8), (0.7, 0.15, 0.6)] {
                let rr = r * CGFloat(s)
                ctx.fill(Path(ellipseIn: CGRect(x: p.x + r * CGFloat(dx) - rr, y: p.y + r * CGFloat(dy) - rr,
                                                width: rr * 2, height: rr * 2)), with: .color(.white))
            }
        case .leaves:
            var c = ctx
            c.translateBy(x: p.x, y: p.y)
            c.rotate(by: .radians(sin(t * 3 + Double(k)) * 0.8 + Double(k)))
            var leaf = Path()
            leaf.move(to: CGPoint(x: -r * 1.1, y: 0))
            leaf.addQuadCurve(to: CGPoint(x: r * 1.1, y: 0), control: CGPoint(x: 0, y: -r * 1.1))
            leaf.addQuadCurve(to: CGPoint(x: -r * 1.1, y: 0), control: CGPoint(x: 0, y: r * 1.1))
            c.fill(leaf, with: .color(Color(egg: k % 2 == 0 ? 0x6fcf5a : 0xe0a33a)))
            c.stroke(leaf, with: .color(ink), lineWidth: 1.2)
        case .rainbow, .none, .auto:
            break
        }
    }

    /// A rainbow ribbon streaming behind, through the recent path.
    private static func ribbon(_ ctx: GraphicsContext, _ pts: [CGPoint], box: CGFloat, opacity: Double) {
        guard pts.count > 1 else { return }
        let bands: [UInt32] = [0xff4d6d, 0xff8f3a, 0xffd23a, 0x5ce07a, 0x3fa9ff, 0x7a6cff]
        let w = box * 0.035
        for (i, c) in bands.enumerated() {
            var path = Path()
            let dy = (CGFloat(i) - 2.5) * w
            path.move(to: CGPoint(x: pts[0].x, y: pts[0].y + dy))
            for p in pts.dropFirst() { path.addLine(to: CGPoint(x: p.x, y: p.y + dy)) }
            ctx.stroke(path, with: .color(Color(egg: c).opacity(0.9 * opacity)),
                       style: StrokeStyle(lineWidth: w + 0.5, lineCap: .round, lineJoin: .round))
        }
    }

    static func star5(_ c: CGPoint, _ r: CGFloat, spin: Double) -> Path {
        var p = Path()
        for i in 0..<10 {
            let a = spin + Double(i) * .pi / 5 - .pi / 2
            let rr = i % 2 == 0 ? r : r * 0.45
            let pt = CGPoint(x: c.x + rr * CGFloat(cos(a)), y: c.y + rr * CGFloat(sin(a)))
            if i == 0 { p.move(to: pt) } else { p.addLine(to: pt) }
        }
        p.closeSubpath()
        return p
    }

    static func heart(_ c: CGPoint, _ r: CGFloat) -> Path {
        var p = Path()
        p.move(to: CGPoint(x: c.x, y: c.y + r))
        p.addCurve(to: CGPoint(x: c.x, y: c.y - r * 0.4),
                   control1: CGPoint(x: c.x - r * 1.4, y: c.y), control2: CGPoint(x: c.x - r * 0.6, y: c.y - r * 1.2))
        p.addCurve(to: CGPoint(x: c.x, y: c.y + r),
                   control1: CGPoint(x: c.x + r * 0.6, y: c.y - r * 1.2), control2: CGPoint(x: c.x + r * 1.4, y: c.y))
        return p
    }

    private static func drop(_ c: CGPoint, _ r: CGFloat) -> Path {
        var p = Path()
        p.move(to: CGPoint(x: c.x, y: c.y - r * 1.4))
        p.addQuadCurve(to: CGPoint(x: c.x, y: c.y + r), control: CGPoint(x: c.x + r * 1.4, y: c.y + r * 0.4))
        p.addQuadCurve(to: CGPoint(x: c.x, y: c.y - r * 1.4), control: CGPoint(x: c.x - r * 1.4, y: c.y + r * 0.4))
        return p
    }

    private static func paw(_ ctx: GraphicsContext, _ c: CGPoint, _ r: CGFloat) {
        let color = Color(egg: 0x6b4a36, 0.85)
        ctx.fill(Path(ellipseIn: CGRect(x: c.x - r * 0.7, y: c.y - r * 0.2, width: r * 1.4, height: r * 1.1)), with: .color(color))
        for (dx, dy) in [(-0.8, -0.55), (-0.3, -0.95), (0.3, -0.95), (0.8, -0.55)] {
            let tr = r * 0.32
            ctx.fill(Path(ellipseIn: CGRect(x: c.x + r * CGFloat(dx) - tr, y: c.y + r * CGFloat(dy) - tr,
                                            width: tr * 2, height: tr * 2.3)), with: .color(color))
        }
    }
}
