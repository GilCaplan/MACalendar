import SwiftUI

/// The celebration and weather graphics. Unlike a figure these fill the whole
/// screen, so each is a function of the screen, the progress through the show
/// (0…1) and the seconds elapsed — no state, which is what lets a whole show
/// be scrubbed, sped up or replayed in the demo without bookkeeping.
enum EggEffect: String, CaseIterable, Codable {
    case fireworks, confetti, rainbow, lightning, snow

    func draw(_ ctx: GraphicsContext, _ size: CGSize, progress p: Double, t: Double) {
        switch self {
        case .fireworks: drawFireworks(ctx, size, p)
        case .confetti: drawConfetti(ctx, size, p, t)
        case .rainbow: drawRainbow(ctx, size, p)
        case .lightning: drawLightning(ctx, size, p)
        case .snow: drawSnow(ctx, size, p, t)
        }
    }
}

/// A repeatable pseudo-random number in 0…1 for (index, salt).
private func rnd(_ i: Int, _ salt: Int = 0) -> Double {
    var x = UInt64(truncatingIfNeeded: i &* 73_856_093 ^ salt &* 19_349_663) &+ 0x9E37_79B9_7F4A_7C15
    x = (x ^ (x >> 30)) &* 0xBF58_476D_1CE4_E5B9
    x = (x ^ (x >> 27)) &* 0x94D0_49BB_1331_11EB
    x ^= x >> 31
    return Double(x % 10_000) / 10_000
}

private let festive: [UInt32] = [0xff4d6d, 0xffd23a, 0x3fd0c9, 0x7a6cff, 0x5ce07a, 0xff8f3a, 0xff7eb6]

/// A four-point sparkle star.
func eggSparkle(_ ctx: GraphicsContext, _ c: CGPoint, _ r: CGFloat, _ color: Color) {
    var p = Path()
    p.move(to: CGPoint(x: c.x, y: c.y - r))
    p.addQuadCurve(to: CGPoint(x: c.x + r, y: c.y), control: c)
    p.addQuadCurve(to: CGPoint(x: c.x, y: c.y + r), control: c)
    p.addQuadCurve(to: CGPoint(x: c.x - r, y: c.y), control: c)
    p.addQuadCurve(to: CGPoint(x: c.x, y: c.y - r), control: c)
    ctx.fill(p, with: .color(color))
}

private func drawFireworks(_ ctx: GraphicsContext, _ size: CGSize, _ p: Double) {
    let bursts = 6
    for b in 0..<bursts {
        let start = Double(b) / Double(bursts) * 0.7
        let local = (p - start) / 0.35
        guard local > 0, local < 1 else { continue }
        let target = CGPoint(x: size.width * (0.15 + 0.7 * rnd(b, 1)), y: size.height * (0.15 + 0.35 * rnd(b, 2)))
        let color = Color(egg: festive[b % festive.count])
        if local < 0.3 {
            // The shell rising, with a short spark trail.
            let k = local / 0.3
            let y = size.height + (target.y - size.height) * CGFloat(1 - pow(1 - k, 2))
            for j in 0..<5 {
                eggSparkle(ctx, CGPoint(x: target.x, y: y + CGFloat(j) * 10), 4 - CGFloat(j) * 0.6,
                           color.opacity(1 - Double(j) * 0.18))
            }
        } else {
            // The burst: streaking sparks flying out, falling, fading.
            let k = (local - 0.3) / 0.7
            let n = 40
            let big = min(size.width, size.height) * CGFloat(0.28 + 0.12 * rnd(b, 9))
            func spot(_ j: Int, _ q: Double) -> CGPoint {
                let a = Double(j) / Double(n) * 2 * .pi + rnd(j, b) * 0.15
                let reach = big * CGFloat(0.7 + 0.3 * rnd(j, b + 7)) * CGFloat(1 - pow(1 - q, 3))
                return CGPoint(x: target.x + reach * CGFloat(cos(a)),
                               y: target.y + reach * CGFloat(sin(a)) + CGFloat(q * q) * big * 0.35)
            }
            for j in 0..<n {
                let tint = (j % 4 == 0 ? .white : color).opacity(1 - k)
                var streak = Path()
                streak.move(to: spot(j, max(0, k - 0.12)))
                streak.addLine(to: spot(j, k))
                ctx.stroke(streak, with: .color(tint), style: StrokeStyle(lineWidth: 3.5, lineCap: .round))
                eggSparkle(ctx, spot(j, k), 7 * CGFloat(1 - k * 0.5), tint)
            }
            if k < 0.15 {
                ctx.fill(Path(ellipseIn: CGRect(x: target.x - 60, y: target.y - 60, width: 120, height: 120)),
                         with: .color(.white.opacity(0.5 * (1 - k / 0.15))))
            }
        }
    }
}

private func drawConfetti(_ ctx: GraphicsContext, _ size: CGSize, _ p: Double, _ t: Double) {
    let n = 130
    let fade = p > 0.85 ? (1 - p) / 0.15 : 1
    for i in 0..<n {
        let delay = rnd(i, 3) * 0.35
        let k = max(0, (p - delay) / (1 - delay))
        guard k > 0 else { continue }
        let x = size.width * CGFloat(rnd(i, 4)) + CGFloat(sin(t * 3 + Double(i))) * 18
        let y = -20 + (size.height + 40) * CGFloat(k * (0.8 + 0.4 * rnd(i, 5)))
        var c = ctx
        c.translateBy(x: x, y: y)
        c.rotate(by: .radians(t * (2 + 4 * rnd(i, 6)) + Double(i)))
        c.scaleBy(x: CGFloat(cos(t * 5 + Double(i))), y: 1)
        let w = 7 + 5 * rnd(i, 8)
        c.fill(Path(CGRect(x: -w / 2, y: -3, width: w, height: 6)),
               with: .color(Color(egg: festive[i % festive.count]).opacity(fade)))
    }
}

private func drawRainbow(_ ctx: GraphicsContext, _ size: CGSize, _ p: Double) {
    let bands: [UInt32] = [0xff4d6d, 0xff8f3a, 0xffd23a, 0x5ce07a, 0x3fa9ff, 0x7a6cff]
    let grow = min(1, p / 0.45), fade = p > 0.8 ? (1 - p) / 0.2 : 1
    let center = CGPoint(x: size.width / 2, y: size.height * 0.62)
    let base = min(size.width, size.height) * 0.42
    let band: CGFloat = 16
    for (i, c) in bands.enumerated() {
        var arc = Path()
        arc.addArc(center: center, radius: base - CGFloat(i) * band, startAngle: .degrees(180),
                   endAngle: .degrees(180 + 180 * grow), clockwise: false)
        ctx.stroke(arc, with: .color(Color(egg: c).opacity(0.9 * fade)), lineWidth: band + 0.5)
    }
    // Sparkles riding the leading edge, and a cloud at each foot.
    let lead = Double.pi * (1 + grow)
    for i in 0..<4 {
        let r = base - CGFloat(i) * band * 1.6
        eggSparkle(ctx, CGPoint(x: center.x + r * CGFloat(cos(lead)), y: center.y + r * CGFloat(sin(lead))),
                   9, .white.opacity(grow < 1 ? 1 : fade))
    }
    for x in [center.x - base + 40, center.x + base - 40] where grow >= 1 || x < center.x {
        for (dx, dy, r) in [(-26.0, 6.0, 22.0), (0.0, -6.0, 28.0), (26.0, 6.0, 22.0)] {
            ctx.fill(Path(ellipseIn: CGRect(x: x + dx - r, y: center.y + dy - r, width: r * 2, height: r * 2)),
                     with: .color(.white.opacity(0.95 * fade)))
        }
    }
}

private func drawLightning(_ ctx: GraphicsContext, _ size: CGSize, _ p: Double) {
    let strikes = [0.1, 0.42, 0.7]
    for (s, at) in strikes.enumerated() {
        let k = (p - at) / 0.16
        guard k > 0, k < 1 else { continue }
        if k < 0.25 {
            ctx.fill(Path(CGRect(origin: .zero, size: size)), with: .color(.white.opacity(0.55 * (1 - k / 0.25))))
        }
        var bolt = Path()
        var pt = CGPoint(x: size.width * CGFloat(0.2 + 0.6 * rnd(s, 11)), y: -10)
        bolt.move(to: pt)
        var j = 0
        while pt.y < size.height * 0.75 {
            pt = CGPoint(x: pt.x + CGFloat(rnd(j, s * 31) - 0.5) * 70, y: pt.y + 30 + CGFloat(rnd(j, s * 17)) * 30)
            bolt.addLine(to: pt)
            j += 1
        }
        let alpha = 1 - k
        ctx.stroke(bolt, with: .color(Color(egg: 0x9fe3ff).opacity(0.5 * alpha)),
                   style: StrokeStyle(lineWidth: 16, lineCap: .round, lineJoin: .round))
        ctx.stroke(bolt, with: .color(Color(egg: 0xfff59a).opacity(alpha)),
                   style: StrokeStyle(lineWidth: 6, lineCap: .round, lineJoin: .round))
        ctx.stroke(bolt, with: .color(.white.opacity(alpha)),
                   style: StrokeStyle(lineWidth: 2, lineCap: .round, lineJoin: .round))
    }
}

private func drawSnow(_ ctx: GraphicsContext, _ size: CGSize, _ p: Double, _ t: Double) {
    let n = 90
    let fade = p < 0.1 ? p / 0.1 : (p > 0.85 ? (1 - p) / 0.15 : 1)
    for i in 0..<n {
        let r = CGFloat(2 + 5 * rnd(i, 21))
        let fall = CGFloat(40 + 50 * rnd(i, 22))
        let y = (CGFloat(rnd(i, 23)) * (size.height + 40) + CGFloat(t) * fall)
            .truncatingRemainder(dividingBy: size.height + 40) - 20
        let x = CGFloat(rnd(i, 24)) * size.width + CGFloat(sin(t * 1.3 + Double(i))) * 16
        if r > 5.5 {
            var c = ctx
            c.translateBy(x: x, y: y)
            c.rotate(by: .radians(t * 0.8 + Double(i)))
            for k in 0..<3 {
                var arm = Path()
                let a = Double(k) * .pi / 3
                arm.move(to: CGPoint(x: -r * CGFloat(cos(a)), y: -r * CGFloat(sin(a))))
                arm.addLine(to: CGPoint(x: r * CGFloat(cos(a)), y: r * CGFloat(sin(a))))
                c.stroke(arm, with: .color(.white.opacity(fade)), lineWidth: 2)
            }
        } else {
            ctx.fill(Path(ellipseIn: CGRect(x: x - r, y: y - r, width: r * 2, height: r * 2)),
                     with: .color(.white.opacity(0.9 * fade)))
        }
    }
}
