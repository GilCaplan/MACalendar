import SwiftUI

/// A photo brought to life like a cut-out puppet, in the figure's 200-unit box.
///
///     walk   the body bobs; the bottom third is cut into a back and a front
///            half that swing in turn from where they meet the body — legs
///     roll   the wheels the phone found in the cut-out are spun in place,
///            and the body rides a little on its suspension
///     flap   squash and stretch, like wings beating
///     hop    springy hops with a wobble
///     still  just the picture
///
/// Automatic by default (`EggVariant.movement`): the phone's own image
/// classifier says dog, car or bird when the photo is saved.
enum EggPuppet {
    static func draw(_ v: EggVariant, _ img: GraphicsContext.ResolvedImage, _ ctx: GraphicsContext, t: Double) {
        let sz = img.size
        let fit = min(200 / max(sz.width, 1), 200 / max(sz.height, 1))
        let w = sz.width * fit, h = sz.height * fit
        let rect = CGRect(x: 100 - w / 2, y: 100 - h / 2, width: w, height: h)
        var c = ctx
        switch v.movement {
        case .still, .auto:
            c.draw(img, in: rect)
        case .hop:
            c.translateBy(x: 100, y: 100 - CGFloat(abs(sin(t * 6))) * 14)
            c.rotate(by: .degrees(5 * sin(t * 7)))
            c.scaleBy(x: 1 + 0.04 * CGFloat(sin(t * 14)), y: 1 - 0.04 * CGFloat(sin(t * 14)))
            c.translateBy(x: -100, y: -100)
            c.draw(img, in: rect)
        case .flap:
            let k = CGFloat(sin(t * 12))
            c.translateBy(x: 100, y: 100 + k * 6)
            c.scaleBy(x: 1 - 0.05 * k, y: 1 + 0.1 * k)
            c.rotate(by: .degrees(3 * sin(t * 6)))
            c.translateBy(x: -100, y: -100)
            c.draw(img, in: rect)
        case .walk where (v.legs?.count ?? 0) >= 2:
            // Real legs, where the pose detector found them: each leg's strip
            // (joint to paw) is cut out of the body and swung from its joint;
            // diagonal pairs move together, as a trot does.
            func strip(_ l: [Double]) -> (Path, CGPoint) {
                let top = CGPoint(x: rect.minX + CGFloat(l[0]) * w, y: rect.minY + CGFloat(l[1]) * h)
                let paw = CGPoint(x: rect.minX + CGFloat(l[2]) * w, y: rect.minY + CGFloat(l[3]) * h)
                let half = w * 0.055
                var p = Path()
                p.move(to: CGPoint(x: top.x - half, y: top.y - half))
                p.addLine(to: CGPoint(x: top.x + half, y: top.y - half))
                p.addLine(to: CGPoint(x: paw.x + half, y: paw.y + half * 0.6))
                p.addLine(to: CGPoint(x: paw.x - half, y: paw.y + half * 0.6))
                p.closeSubpath()
                return (p, top)
            }
            let legs = (v.legs ?? []).map(strip)
            var cut = Path(CGRect(x: rect.minX - 40, y: rect.minY - 40, width: w + 80, height: h + 80))
            for (p, _) in legs { cut.addPath(p) }
            var body = c
            body.translateBy(x: 0, y: -CGFloat(abs(sin(t * 7))) * 3)
            body.clip(to: cut, style: FillStyle(eoFill: true))
            body.draw(img, in: rect)
            for (i, (p, top)) in legs.enumerated() {
                var l = c
                let phase = (i == 0 || i == 3) ? 0.0 : .pi          // LF with RB, RF with LB
                l.translateBy(x: top.x, y: top.y)
                l.rotate(by: .degrees(18 * sin(t * 7 + phase)))
                l.translateBy(x: -top.x, y: -top.y)
                l.clip(to: p)
                l.draw(img, in: rect)
            }
        case .walk:
            let legTop = rect.minY + h * 0.64
            let bob = -CGFloat(abs(sin(t * 7))) * 3
            // Legs first, so the body's edge sits over their tops.
            for half in 0..<2 {
                let region = CGRect(x: rect.minX + CGFloat(half) * w / 2, y: legTop - 2, width: w / 2, height: rect.maxY - legTop + 2)
                let pivot = CGPoint(x: region.midX, y: legTop)
                var l = c
                l.translateBy(x: pivot.x, y: pivot.y)
                l.rotate(by: .degrees(16 * sin(t * 7 + Double(half) * .pi)))
                l.translateBy(x: -pivot.x, y: -pivot.y)
                l.clip(to: Path(region))
                l.draw(img, in: rect)
            }
            var b = c
            b.translateBy(x: 0, y: bob)
            b.clip(to: Path(CGRect(x: rect.minX, y: rect.minY - 20, width: w, height: legTop - rect.minY + 20 + h * 0.04)))
            b.draw(img, in: rect)
        case .roll:
            var b = c
            b.translateBy(x: 0, y: CGFloat(sin(t * 18)) * 1.2)
            b.draw(img, in: rect)
            for wheel in v.wheels ?? [] where wheel.count == 3 {
                let centre = CGPoint(x: rect.minX + CGFloat(wheel[0]) * w, y: rect.minY + CGFloat(wheel[1]) * h)
                let r = CGFloat(wheel[2]) * w
                var ring = c
                ring.clip(to: Path(ellipseIn: CGRect(x: centre.x - r, y: centre.y - r, width: r * 2, height: r * 2)))
                ring.translateBy(x: centre.x, y: centre.y)
                ring.rotate(by: .degrees(t * 540))
                ring.translateBy(x: -centre.x, y: -centre.y)
                ring.draw(img, in: rect)
                // A spoke mark so the spin reads even on a plain wheel.
                var mark = Path()
                let a = t * 540 * .pi / 180
                mark.move(to: CGPoint(x: centre.x - r * 0.6 * CGFloat(cos(a)), y: centre.y - r * 0.6 * CGFloat(sin(a))))
                mark.addLine(to: CGPoint(x: centre.x + r * 0.6 * CGFloat(cos(a)), y: centre.y + r * 0.6 * CGFloat(sin(a))))
                c.stroke(mark, with: .color(.white.opacity(0.35)), lineWidth: 2)
            }
        }
    }

    /// Where the wheels are in a cut-out: [cx, cy, r], 0…1 of the picture.
    /// Read off the silhouette: the columns that reach the ground, the widest
    /// run of them in each half, and a wheel's usual size for a vehicle seen
    /// side-on. Plain Core Graphics, so the Mac can test it.
    static func findWheels(_ cg: CGImage) -> [[Double]] {
        let w = 160, h = max(1, Int(Double(cg.height) * 160 / Double(max(cg.width, 1))))
        var alpha = [UInt8](repeating: 0, count: w * h)
        let drawn: Bool = alpha.withUnsafeMutableBytes { buf in
            guard let ctx = CGContext(data: buf.baseAddress, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w,
                                      space: CGColorSpaceCreateDeviceGray(), bitmapInfo: CGImageAlphaInfo.alphaOnly.rawValue)
            else { return false }
            ctx.draw(cg, in: CGRect(x: 0, y: 0, width: w, height: h))
            return true
        }
        guard drawn else { return [] }
        // Row 0 of the buffer is the TOP of the picture.
        var bottom = [Int](repeating: -1, count: w)
        for x in 0..<w { for y in 0..<h where alpha[y * w + x] > 128 { bottom[x] = y } }
        guard let ground = bottom.max(), ground > 0 else { return [] }
        let touches = bottom.map { $0 >= ground - max(2, h / 40) }
        // Its size from the figure's own length: a wheel is about a sixth of it.
        let lit = bottom.indices.filter { bottom[$0] >= 0 }
        let length = Double((lit.last ?? w - 1) - (lit.first ?? 0) + 1) / Double(w)
        let r = max(0.05, min(0.12, length * 0.085))
        var out: [[Double]] = []
        for half in 0..<2 {
            let range = half == 0 ? 0..<(w / 2) : (w / 2)..<w
            var best = (start: 0, count: 0), run = 0, startX = range.lowerBound
            for x in range {
                if touches[x] {
                    if run == 0 { startX = x }
                    run += 1
                    if run > best.count { best = (startX, run) }
                } else { run = 0 }
            }
            guard best.count > 0 else { continue }
            let cx = (Double(best.start) + Double(best.count) / 2) / Double(w)
            let cy = Double(ground + 1) / Double(h) - r * Double(w) / Double(h)
            out.append([cx, cy, r])
        }
        return out
    }
}
