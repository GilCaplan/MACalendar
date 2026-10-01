import SwiftUI

// The loading screen the user builds (TASKS 48): wherever the app waits, one
// of their magic-word graphics plays instead of the plain spinner — a German
// Shepherd running in a hamster wheel by default — and when a wait runs long
// ("stuck"), a bigger one takes the middle of the screen with a line saying so.

enum EggLoaderStyle: String, Codable, CaseIterable {
    case hamster, wheel, spin, bounce, pulse, parade
    var label: String {
        switch self {
        case .hamster: return "Hamster wheel"
        case .wheel: return "Wheel of friends"
        case .spin: return "Spin"
        case .bounce: return "Bounce"
        case .pulse: return "Pulse"
        case .parade: return "Parade"
        }
    }
}

struct EggLoaderConfig: Codable, Equatable {
    var enabled = true
    var style: EggLoaderStyle = .hamster
    /// Up to four magic-word objects; the wheel spreads them round the ring.
    var objects: [String] = ["dog"]
    var trail: EggTrail = .sparkles
    /// Laps per second, roughly; 0.3…2.
    var speed: Double = 1
    var ringHex: String = "#F5A623"
    var showRing = true
    var caption = "Loading…"
    var showCaption = true
    /// Seconds before a wait takes the middle of the screen; 0 = never.
    var stuckAfter: Double = 4
    var stuckCaption = "Still working on it…"

    init() {}

    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        let b = EggLoaderConfig()
        enabled = (try? c.decodeIfPresent(Bool.self, forKey: .enabled)) ?? b.enabled
        style = (try? c.decodeIfPresent(EggLoaderStyle.self, forKey: .style)) ?? b.style
        objects = (try? c.decodeIfPresent([String].self, forKey: .objects)) ?? b.objects
        trail = (try? c.decodeIfPresent(EggTrail.self, forKey: .trail)) ?? b.trail
        speed = (try? c.decodeIfPresent(Double.self, forKey: .speed)) ?? b.speed
        ringHex = (try? c.decodeIfPresent(String.self, forKey: .ringHex)) ?? b.ringHex
        showRing = (try? c.decodeIfPresent(Bool.self, forKey: .showRing)) ?? b.showRing
        caption = (try? c.decodeIfPresent(String.self, forKey: .caption)) ?? b.caption
        showCaption = (try? c.decodeIfPresent(Bool.self, forKey: .showCaption)) ?? b.showCaption
        stuckAfter = (try? c.decodeIfPresent(Double.self, forKey: .stuckAfter)) ?? b.stuckAfter
        stuckCaption = (try? c.decodeIfPresent(String.self, forKey: .stuckCaption)) ?? b.stuckCaption
    }
}

extension Color {
    /// "#RRGGBB", or the fallback.
    init(eggHex hex: String, fallback: Color = .orange) {
        let s = hex.trimmingCharacters(in: CharacterSet(charactersIn: "# "))
        guard s.count == 6, let v = UInt32(s, radix: 16) else { self = fallback; return }
        self.init(egg: v)
    }
}

/// Draws the loader into a square `size` at time `t`.
enum EggLoaderRender {
    static func draw(_ cfg: EggLoaderConfig, _ objects: [EggObject], _ outer: GraphicsContext, _ size: CGSize,
                     t: Double, image: (String) -> Image?) {
        // Kept inside its own square: a parade must not walk into the next tile.
        var ctx = outer
        ctx.clip(to: Path(CGRect(origin: .zero, size: size)))
        let side = min(size.width, size.height)
        let c = CGPoint(x: size.width / 2, y: size.height / 2)
        let speed = max(0.3, min(2, cfg.speed))
        let ring = Color(eggHex: cfg.ringHex)
        let list = objects.isEmpty ? [] : objects
        func figure(_ o: EggObject, at p: CGPoint, box: CGFloat, degrees: Double = 0, flip: Bool = false, pace: Double = 1) {
            var g = ctx
            g.translateBy(x: p.x, y: p.y)
            g.rotate(by: .degrees(degrees))
            g.scaleBy(x: (flip ? -1 : 1) * box / 200, y: box / 200)
            g.translateBy(x: -100, y: -100)
            switch o.activeVariant.source {
            case .figure(let raw):
                guard let f = EggFigure(rawValue: raw) else { return }
                var pose = EggPose(t: t * pace)
                pose.speed = f.speed
                f.draw(EggPainter(ctx: g), pose)
            case .image(let file):
                if let img = image(file) { EggPuppet.draw(o.activeVariant, g.resolve(img), g, t: t * pace) }
            case .symbol(let spec):
                EggSymbol.draw(spec, g, t: t * pace)
            case .effect(let raw):
                var e = ctx
                e.translateBy(x: p.x - box / 2, y: p.y - box / 2)
                e.clip(to: Path(ellipseIn: CGRect(x: 0, y: 0, width: box, height: box)))
                EggEffect(rawValue: raw)?.draw(e, CGSize(width: box, height: box),
                                               progress: (t * 0.4).truncatingRemainder(dividingBy: 1), t: t)
            }
        }
        func sparkles(along points: [CGPoint]) {
            let box = side * 0.5
            EggTrails.draw(cfg.trail, ctx, box: box, t: t,
                           samples: points.enumerated().map { (EggFrame(center: $1), $0 + 1) },
                           here: EggFrame(center: points.first ?? c), ground: false)
        }
        switch cfg.style {
        case .hamster:
            // A wheel turning backwards under a figure running at its bottom.
            let r = side * 0.44
            if cfg.showRing {
                ctx.stroke(Path(ellipseIn: CGRect(x: c.x - r, y: c.y - r, width: r * 2, height: r * 2)),
                           with: .color(ring), lineWidth: side * 0.035)
                for k in 0..<10 {
                    let a = -t * speed * 2 * .pi + Double(k) * .pi / 5
                    var spoke = Path()
                    spoke.move(to: c)
                    spoke.addLine(to: CGPoint(x: c.x + r * CGFloat(cos(a)), y: c.y + r * CGFloat(sin(a))))
                    ctx.stroke(spoke, with: .color(ring.opacity(0.35)), lineWidth: 1.5)
                }
                ctx.fill(Path(ellipseIn: CGRect(x: c.x - side * 0.04, y: c.y - side * 0.04, width: side * 0.08, height: side * 0.08)),
                         with: .color(ring))
            }
            if let o = list.first {
                let box = side * 0.52
                let at = CGPoint(x: c.x, y: c.y + r - box * 0.42)
                sparkles(along: (1...6).map { CGPoint(x: at.x - box * 0.3 - CGFloat($0) * 6, y: at.y + CGFloat(sin(t * 8 + Double($0))) * 3) })
                figure(o, at: at, box: box, pace: speed * 1.4)
            }
        case .wheel:
            // The classic wheel, made of friends: they chase round a ring.
            let r = side * 0.34
            if cfg.showRing {
                for k in 0..<24 {
                    let a0 = Double(k) / 24 * 2 * .pi, fade = (Double(k) / 24 + t * speed).truncatingRemainder(dividingBy: 1)
                    var arc = Path()
                    arc.addArc(center: c, radius: r, startAngle: .radians(a0), endAngle: .radians(a0 + 0.2), clockwise: false)
                    ctx.stroke(arc, with: .color(ring.opacity(0.15 + 0.85 * fade)),
                               style: StrokeStyle(lineWidth: side * 0.04, lineCap: .round))
                }
            }
            let n = max(1, list.count)
            for (i, o) in list.enumerated() {
                let a = t * speed * 2 * .pi + Double(i) / Double(n) * 2 * .pi
                let p = CGPoint(x: c.x + r * CGFloat(cos(a)), y: c.y + r * CGFloat(sin(a)))
                sparkles(along: (1...5).map { k in
                    let b = a - Double(k) * 0.12
                    return CGPoint(x: c.x + r * CGFloat(cos(b)), y: c.y + r * CGFloat(sin(b)))
                })
                figure(o, at: p, box: side * (n > 2 ? 0.3 : 0.38), degrees: a * 180 / .pi + 90, pace: speed)
            }
        case .spin:
            if cfg.showRing {
                var arc = Path()
                arc.addArc(center: c, radius: side * 0.44, startAngle: .radians(t * speed * 6), endAngle: .radians(t * speed * 6 + 4.2), clockwise: false)
                ctx.stroke(arc, with: .color(ring), style: StrokeStyle(lineWidth: side * 0.04, lineCap: .round))
            }
            if let o = list.first { figure(o, at: c, box: side * 0.62, degrees: t * speed * 360, pace: speed) }
        case .bounce:
            if let o = list.first {
                let h = abs(sin(t * speed * .pi * 1.6))
                let ground = c.y + side * 0.32
                ctx.fill(Path(ellipseIn: CGRect(x: c.x - side * 0.2 * CGFloat(1 - h * 0.4), y: ground - 4,
                                                width: side * 0.4 * CGFloat(1 - h * 0.4), height: 8)),
                         with: .color(.black.opacity(0.18)))
                figure(o, at: CGPoint(x: c.x, y: ground - side * 0.24 - CGFloat(h) * side * 0.26), box: side * 0.5, pace: speed)
            }
        case .pulse:
            if let o = list.first {
                let k = 1 + 0.12 * sin(t * speed * 5)
                if cfg.showRing {
                    let rr = side * 0.3 * CGFloat(1 + (t * speed).truncatingRemainder(dividingBy: 1) * 0.5)
                    ctx.stroke(Path(ellipseIn: CGRect(x: c.x - rr, y: c.y - rr, width: rr * 2, height: rr * 2)),
                               with: .color(ring.opacity(1 - (t * speed).truncatingRemainder(dividingBy: 1))), lineWidth: 3)
                }
                figure(o, at: c, box: side * 0.55 * CGFloat(k), pace: speed)
            }
        case .parade:
            let n = max(1, list.count)
            for (i, o) in list.enumerated() {
                let q = (t * speed * 0.5 + Double(i) / Double(n)).truncatingRemainder(dividingBy: 1)
                let x = -side * 0.25 + (size.width + side * 0.5) * CGFloat(q)
                let p = CGPoint(x: x, y: c.y + CGFloat(sin(t * 6 + Double(i))) * side * 0.04)
                sparkles(along: (1...5).map { CGPoint(x: p.x - side * 0.18 - CGFloat($0) * 6, y: p.y) })
                figure(o, at: p, box: side * 0.42, pace: speed)
            }
        }
    }
}

