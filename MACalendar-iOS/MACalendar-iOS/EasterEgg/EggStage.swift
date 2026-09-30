import SwiftUI
#if canImport(UIKit)
import UIKit
#endif

/// One graphic on screen.
struct EggShow: Identifiable {
    let id = UUID()
    let objectID: String
    let variant: EggVariant
    let motion: EggMotion
    var start: Date
    let seconds: Double
    /// Place in a group formation, and how many share it.
    let slot: Int
    let count: Int
    /// Stagger inside a group, seconds.
    let delay: Double
    /// The subgraphic trailing behind it, and whether the motion runs mirrored.
    var trail: EggTrail = .sparkles
    var mirrored = false
    /// For `.drawn`: [x, y, t] points, 0…1.
    var path: [[Double]]? = nil
    /// The three steps: in, a pause mid-screen, out. nil halves `seconds`.
    var enter: Double? = nil
    var hold: Double = 0
    var exit: Double? = nil
    var holdForever = false
    var opacity: Double = 1
    var look: EggLook = .solid
    /// Size multiplier, the lane's centre line (0…1 of the height, nil = the
    /// motion's own), and the sound it makes as it starts.
    var size: CGFloat = 1
    var laneY: Double? = nil
    var sound: EggSound = .none

    /// Progress 0…1 through the motion after `e` seconds on screen, with the
    /// hold parked at the middle (0.5). `released` ends an open-ended hold.
    func progress(elapsed e: Double, releasedAfter released: Double?) -> Double {
        let tin = max(enter ?? seconds / 2, 0.05), tout = max(exit ?? seconds / 2, 0.05)
        if e < tin { return 0.5 * e / tin }
        let held = holdForever ? (released.map { max(0, $0 - tin) } ?? .infinity) : hold
        if e < tin + held { return 0.5 }
        return 0.5 + 0.5 * (e - tin - held) / tout
    }
}

/// What is playing, what is queued, and what a tap does. The overlay window
/// draws `shows`; nothing else in the app needs to know any of this exists.
@MainActor
final class EggStage: ObservableObject {
    static let shared = EggStage()

    @Published private(set) var shows: [EggShow] = []
    /// A line shown over the show ("Chag Sameach!"), for festival greetings.
    @Published private(set) var caption: String?
    private var queue: [[EggShow]] = []
    private var boostAt: Date?
    private var releasedAt: Date?
    private static let boost = 3.0
    /// Touches pass through to the app while this is true.
    @Published private(set) var passThrough = false
    /// Called as each batch starts — sound and haptics live with the app,
    /// not in this platform-neutral stage.
    var onBatchStart: (([EggShow]) -> Void)?
    private var ticker: Task<Void, Never>?

    var isPlaying: Bool { !shows.isEmpty }

    /// Play these objects (ids in the order said, repeats kept) the way the
    /// settings say: one group, or one after another.
    func play(_ ids: [String], settings: EggSettings, together: Bool = true, caption: String? = nil) {
        if let caption { self.caption = caption }
        let objects = Dictionary(settings.objects.map { ($0.id, $0) }, uniquingKeysWith: { a, _ in a })
        let found = ids.compactMap { objects[$0] }.filter(\.enabled).prefix(8)
        guard !found.isEmpty else { return }
        // One coin for "Surprise me" per play, so a pack runs the same way.
        let coin = Bool.random()
        func show(_ o: EggObject, slot: Int, count: Int, delay: Double) -> EggShow {
            Self.build(o, settings: settings, slot: slot, count: count, delay: delay, coin: coin)
        }
        var batches: [[EggShow]]
        if together {
            // A screen-filling effect twice over is the same effect: keep one.
            var seenEffect = Set<String>()
            let list = found.filter { o in
                if case .effect = o.activeVariant.source { return seenEffect.insert(o.id).inserted }
                return true
            }
            batches = [list.enumerated().map { show($1, slot: $0, count: list.count, delay: Double($0) * 0.35) }]
        } else {
            batches = found.map { [show($0, slot: 0, count: 1, delay: 0)] }
        }
        passThrough = settings.passThrough
        if shows.isEmpty {
            start(batches.removeFirst())
        }
        queue.append(contentsOf: batches)
        EggOverlay.shared.show(passThrough: settings.passThrough)
        runTicker()
    }

    /// One object's show under these settings — what `play` puts on screen
    /// and what the settings pages preview.
    static func build(_ o: EggObject, settings: EggSettings, slot: Int = 0, count: Int = 1,
                      delay: Double = 0, coin: Bool = false) -> EggShow {
        // A word's own timing, look, size and place win over the page's.
        let entrance = o.entrance ?? settings.entrance, exit = o.exit ?? settings.exit
        let lane = (o.lane ?? settings.lane)
        let motion = settings.motion != .auto ? settings.motion
            : (o.motion != .auto ? o.motion : EggCatalog.defaultMotion(o.id))
        let trail = settings.trail != .auto ? settings.trail
            : (o.trail != .auto ? o.trail : EggCatalog.defaultTrail(o.id))
        let dir = settings.direction != .auto ? settings.direction : o.direction
        let mirrored = dir == .rightToLeft || (dir == .random && coin)
        let path = settings.motion == .drawn ? settings.drawnPath : o.drawnPath
        let sound: EggSound = !settings.sound ? .none
            : ((o.sound ?? .auto) == .auto ? EggCatalog.defaultSound(o.id, motion: motion) : o.sound!)
        return EggShow(objectID: o.id, variant: o.activeVariant, motion: motion, start: Date(),
                       seconds: entrance + exit, slot: slot, count: count, delay: delay,
                       trail: trail, mirrored: mirrored, path: path,
                       enter: entrance, hold: o.pause ?? settings.pause, exit: exit,
                       // Nothing can tap it when touches pass through, so it never holds for good.
                       holdForever: settings.untilTapped && !settings.passThrough,
                       opacity: o.opacity ?? settings.opacity, look: o.look ?? settings.look,
                       size: CGFloat(EggSizeRange.clamp((o.sizePercent ?? settings.sizePercent)
                                                         * (o.activeVariant.scalePercent ?? 100) / 100) / 100),
                       laneY: lane.y, sound: sound)
    }

    /// A tap: vanish, or let it go on (out of a hold, and quicker) and
    /// vanish on the second tap.
    func tap(_ settings: EggSettings) {
        if settings.tap == .vanish || boostAt != nil { stop(); return }
        let now = Date()
        releasedAt = now
        boostAt = now
    }

    func stop() {
        shows = []; queue = []; boostAt = nil; releasedAt = nil; caption = nil
        ticker?.cancel(); ticker = nil
        EggOverlay.shared.hide()
    }

    /// Seconds into a show, counting the hurried stretch at triple speed.
    func elapsed(_ s: EggShow, at now: Date) -> Double {
        let raw = now.timeIntervalSince(s.start)
        guard let b = boostAt, b > s.start else { return raw }
        return b.timeIntervalSince(s.start) + now.timeIntervalSince(b) * Self.boost
    }

    func progress(_ s: EggShow, at now: Date) -> Double {
        let released = releasedAt.map { elapsed(s, at: $0) - s.delay }
        return s.progress(elapsed: elapsed(s, at: now) - s.delay, releasedAfter: released)
    }

    private func start(_ batch: [EggShow]) {
        let now = Date()
        shows = batch.map { var s = $0; s.start = now; return s }
        onBatchStart?(shows)
    }

    private func runTicker() {
        guard ticker == nil else { return }
        ticker = Task { @MainActor [weak self] in
            while let self, !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 100_000_000)
                let now = Date()
                if !self.shows.isEmpty, self.shows.allSatisfy({ self.progress($0, at: now) >= 1 }) {
                    self.boostAt = nil; self.releasedAt = nil
                    if self.queue.isEmpty { self.stop(); return }
                    self.start(self.queue.removeFirst())
                }
            }
        }
    }
}

// MARK: - Where a figure is at a moment

struct EggFrame {
    var center: CGPoint
    var scale: CGFloat = 1
    var degrees: Double = 0
    var flip = false
    var opacity: Double = 1

    /// The same moment seen in a mirror: right-to-left instead of left-to-right.
    func mirrored(_ width: CGFloat) -> EggFrame {
        var f = self
        f.center.x = width - center.x
        f.flip.toggle()
        f.degrees = -degrees
        return f
    }
}

enum EggPath2 {
    static func easeOut(_ x: Double) -> Double { 1 - pow(1 - x, 3) }
    static func easeIn(_ x: Double) -> Double { x * x * x }
    static func easeOutBack(_ x: Double) -> Double {
        let c1 = 1.70158, c3 = c1 + 1
        return 1 + c3 * pow(x - 1, 3) + c1 * pow(x - 1, 2)
    }

    /// Fade and grow in over the first 10%, out over the last 10% — for the
    /// motions that start and end on screen.
    static func onScreen(_ p: Double) -> (scale: CGFloat, opacity: Double) {
        if p < 0.1 { let k = p / 0.1; return (CGFloat(easeOutBack(k)), k) }
        if p > 0.9 { let k = (1 - p) / 0.1; return (CGFloat(k), k) }
        return (1, 1)
    }

    /// The figure's frame at progress `p`, left to right, in a screen of
    /// `size` with a figure box of `box` points. `slot`/`count` spread a group
    /// into a formation. Mirroring for right-to-left happens in the caller.
    static func frame(_ m: EggMotion, p: Double, t: Double, size: CGSize, box: CGFloat,
                      slot: Int, count: Int, nose: Bool, path: [[Double]]? = nil) -> EggFrame {
        let W = size.width, H = size.height
        let off = (CGFloat(slot) - CGFloat(count - 1) / 2) * box * 0.42
        let across = CGFloat(-0.6 + (1.2 + W / box) * p) * box
        let ground = H * 0.72
        func heading(_ at: (Double) -> CGPoint) -> (CGPoint, Double, Bool) {
            let a = at(p), b = at(min(1, p + 0.01)), c = at(max(0, p - 0.01))
            let dx = Double(b.x - c.x), dy = Double(b.y - c.y)
            return (a, atan2(dy, abs(dx)) * 180 / .pi, dx < 0)
        }
        switch m {
        case .drawn:
            // The user's own path, replayed at the pace it was drawn. Without
            // one (never drawn), it flies across like the default.
            guard let path, path.count >= 2 else {
                return frame(.flyBy, p: p, t: t, size: size, box: box, slot: slot, count: count, nose: nose)
            }
            func at(_ q: Double) -> CGPoint {
                let q = min(max(q, 0), 1)
                var i = 1
                while i < path.count - 1 && path[i][2] < q { i += 1 }
                let a = path[i - 1], b = path[i]
                let span = max(b[2] - a[2], 1e-6)
                let k = min(max((q - a[2]) / span, 0), 1)
                return CGPoint(x: CGFloat(a[0] + (b[0] - a[0]) * k) * W,
                               y: CGFloat(a[1] + (b[1] - a[1]) * k) * H + off)
            }
            let (pt, deg, left) = heading(at)
            let o = onScreen(p)
            return EggFrame(center: pt, scale: o.scale, degrees: max(-35, min(35, deg * 0.6)), flip: left,
                            opacity: o.opacity)
        case .flyBy, .auto:
            let y = H * 0.42 + off + CGFloat(sin(p * 3 * .pi)) * box * 0.12
            return EggFrame(center: CGPoint(x: across, y: y), degrees: -6 * cos(p * 3 * .pi))
        case .run:
            let y = ground + off * 0.55 - CGFloat(abs(sin(t * 5))) * box * 0.04
            return EggFrame(center: CGPoint(x: across, y: y))
        case .swoop:
            func at(_ q: Double) -> CGPoint {
                let a = CGPoint(x: -box, y: H * 0.12 + off), c = CGPoint(x: W / 2, y: H * 1.0 + off),
                    b = CGPoint(x: W + box, y: H * 0.1 + off)
                let u = CGFloat(q)
                return CGPoint(x: (1 - u) * (1 - u) * a.x + 2 * (1 - u) * u * c.x + u * u * b.x,
                               y: (1 - u) * (1 - u) * a.y + 2 * (1 - u) * u * c.y + u * u * b.y)
            }
            let (pt, deg, _) = heading(at)
            return EggFrame(center: pt, degrees: deg * 0.6)
        case .pop:
            let c = CGPoint(x: W / 2 + off, y: H * 0.45 + CGFloat(sin(t * 2.4)) * 8)
            if p < 0.18 { return EggFrame(center: c, scale: CGFloat(max(0, easeOutBack(p / 0.18)))) }
            if p > 0.82 {
                let k = (p - 0.82) / 0.18
                return EggFrame(center: c, scale: CGFloat(1 - easeIn(k)), degrees: 200 * k)
            }
            return EggFrame(center: c, degrees: 4 * sin(t * 3))
        case .spiral:
            let c = CGPoint(x: W / 2, y: H * 0.45)
            func at(_ q: Double) -> CGPoint {
                let k = min(1, q / 0.7)
                let theta = (1 - k) * 3 * .pi + .pi + Double(slot) * 2 * .pi / Double(max(count, 1))
                let r = CGFloat(1 - easeOut(k)) * min(W, H) * 0.6 + (count > 1 ? box * 0.3 : 0)
                return CGPoint(x: c.x + r * CGFloat(cos(theta)), y: c.y + r * CGFloat(sin(theta)))
            }
            let (pt, _, left) = heading(at)
            if p < 0.7 { return EggFrame(center: pt, flip: left) }
            let k = (p - 0.7) / 0.3
            return EggFrame(center: pt, scale: CGFloat(1 + 1.6 * k), opacity: 1 - k)
        case .launch:
            let y = H + box * 0.4 - CGFloat(pow(p, 1.6)) * (H + box * 1.3)
            return EggFrame(center: CGPoint(x: W / 2 + off + CGFloat(sin(t * 9)) * 3, y: y),
                            degrees: nose ? -90 : -8)
        case .zigzag:
            let legs = 4.0
            let tri = abs((p * legs).truncatingRemainder(dividingBy: 2) - 1)
            let y = H * (0.22 + 0.4 * CGFloat(tri)) + off
            let rising = Int(p * legs) % 2 == 0
            return EggFrame(center: CGPoint(x: across, y: y), degrees: rising ? 14 : -14)
        case .bounce:
            // Big hops that shrink, with a squash on each landing.
            let hops = 4.0, phase = (p * hops).truncatingRemainder(dividingBy: 1)
            let height = H * 0.38 * CGFloat(pow(0.8, floor(p * hops)))
            let y = ground + off * 0.5 - height * CGFloat(4 * phase * (1 - phase))
            let squash = phase < 0.08 || phase > 0.92 ? 0.85 : 1
            return EggFrame(center: CGPoint(x: across, y: y), scale: CGFloat(squash), degrees: (phase - 0.5) * -30)
        case .orbit:
            func at(_ q: Double) -> CGPoint {
                let a = q * 2.2 * .pi - .pi + Double(slot) * 2 * .pi / Double(max(count, 1))
                let r = min(W, H) * 0.32
                return CGPoint(x: W / 2 + r * CGFloat(cos(a)), y: H * 0.45 + r * 1.2 * CGFloat(sin(a)))
            }
            let (pt, deg, left) = heading(at)
            let o = onScreen(p)
            return EggFrame(center: pt, scale: o.scale, degrees: deg * 0.3, flip: left, opacity: o.opacity)
        case .figureEight:
            func at(_ q: Double) -> CGPoint {
                let a = q * 2 * .pi + Double(slot) * 0.6
                return CGPoint(x: W / 2 + W * 0.33 * CGFloat(sin(a)), y: H * 0.42 + H * 0.16 * CGFloat(sin(2 * a)))
            }
            let (pt, deg, left) = heading(at)
            let o = onScreen(p)
            return EggFrame(center: pt, scale: o.scale, degrees: deg * 0.4, flip: left, opacity: o.opacity)
        case .drift:
            let y = H + box * 0.6 - CGFloat(p) * (H + box * 1.2)
            let x = W / 2 + off + W * 0.18 * CGFloat(sin(p * 4 * .pi))
            return EggFrame(center: CGPoint(x: x, y: y), degrees: 8 * sin(p * 4 * .pi))
        case .dash:
            // In like a shot, a held pose with a shiver, out like a shot.
            let mid = W / 2 + off * 0.3
            let x: CGFloat
            if p < 0.25 { x = -box + (mid + box) * CGFloat(easeOut(p / 0.25)) }
            else if p < 0.7 { x = mid + CGFloat(sin(t * 60)) * 1.5 }
            else { x = mid + (W + box * 1.5 - mid) * CGFloat(easeIn((p - 0.7) / 0.3)) }
            let lean = p < 0.25 || p > 0.7 ? -10.0 : 0
            return EggFrame(center: CGPoint(x: x, y: H * 0.45 + off), degrees: lean)
        case .peek:
            // Leans in from the left edge, looks about, ducks back out.
            let inset: CGFloat
            if p < 0.2 { inset = CGFloat(easeOut(p / 0.2)) } else if p > 0.8 { inset = CGFloat(easeIn((1 - p) / 0.2)) } else { inset = 1 }
            let x = -box * 0.5 + box * 0.8 * inset
            return EggFrame(center: CGPoint(x: x, y: H * 0.5 + off), degrees: 12 * sin(t * 2.2) + 10)
        case .wave:
            func at(_ q: Double) -> CGPoint {
                CGPoint(x: CGFloat(-0.6 + (1.2 + W / box) * q) * box,
                        y: H * 0.45 + off + H * 0.2 * CGFloat(sin(q * 4 * .pi)))
            }
            let (pt, deg, _) = heading(at)
            return EggFrame(center: pt, degrees: deg * 0.7)
        case .dive:
            // Drops from the top, lands with a squash, then runs off.
            if p < 0.35 {
                let k = p / 0.35
                return EggFrame(center: CGPoint(x: W * 0.35 + off * 0.3, y: -box + (ground + box) * CGFloat(k * k)),
                                degrees: 15)
            }
            if p < 0.45 {
                return EggFrame(center: CGPoint(x: W * 0.35 + off * 0.3, y: ground + box * 0.04), scale: 0.9)
            }
            let k = (p - 0.45) / 0.55
            let y = ground + off * 0.5 - CGFloat(abs(sin(t * 5))) * box * 0.04
            return EggFrame(center: CGPoint(x: W * 0.35 + off * 0.3 + (W * 0.65 + box) * CGFloat(easeIn(k)), y: y))
        }
    }
}

// MARK: - Drawing a show

enum EggRender {
    /// However big it is asked to be, a figure stays between these (points):
    /// big enough to see on a phone, never a mural on a desktop.
    static let minBox: CGFloat = 56
    static let maxBox: CGFloat = 520

    /// The figure box for a screen: half its short side, smaller in a crowd.
    static func box(_ size: CGSize, count: Int) -> CGFloat {
        // Capped, so a desktop screen gets a figure, not a mural; a phone
        // (≈390 pt across) never reaches the cap.
        min(min(size.width, size.height) * (count > 1 ? 0.5 : 0.72), count > 1 ? 300 : 420)
    }

    /// Where each motion's path runs, as a fraction of the height — what a
    /// lane moves. Vertical and screen-wide motions keep their own.
    static func baseY(_ m: EggMotion) -> Double? {
        switch m {
        case .flyBy, .auto, .zigzag: return 0.42
        case .run, .dive: return 0.72
        case .bounce: return 0.6
        case .wave, .dash, .pop, .orbit, .spiral: return 0.45
        case .figureEight: return 0.42
        case .peek: return 0.5
        case .swoop, .launch, .drift, .drawn: return nil
        }
    }

    static func frame(_ s: EggShow, p: Double, t: Double, size: CGSize, box: CGFloat) -> EggFrame {
        let f = EggPath2.frame(s.motion, p: p, t: t, size: size, box: box, slot: s.slot, count: s.count,
                               nose: s.objectID == "rocket", path: s.path)
        return s.mirrored ? f.mirrored(size.width) : f
    }

    static func draw(_ s: EggShow, _ ctx: GraphicsContext, _ size: CGSize, progress p: Double, t: Double,
                     image: (String) -> Image?) {
        guard p >= 0, p <= 1 else { return }
        // Opacity and a glow apply to the finished picture, one layer, so the
        // glow haloes the whole figure rather than every stroke in it.
        var g = ctx
        if let lane = s.laneY, let base = baseY(s.motion), !isEffect(s) {
            g.translateBy(x: 0, y: CGFloat(lane - base) * size.height)
        }
        g.opacity = max(0.1, min(1, s.opacity)) * (s.look == .outline && isImage(s) ? 0.55 : 1)
        if s.look != .solid {
            g.addFilter(.shadow(color: Color(egg: 0xfff3b0, 0.95), radius: 8))
            g.addFilter(.shadow(color: Color(egg: 0xffd23a, 0.7), radius: 20))
        }
        g.drawLayer { layer in drawShow(s, layer, size, progress: p, t: t, image: image) }
    }

    private static func isEffect(_ s: EggShow) -> Bool {
        if case .effect = s.variant.source { return true }
        return false
    }

    private static func isImage(_ s: EggShow) -> Bool {
        if case .image = s.variant.source { return true }
        return false
    }

    private static func drawShow(_ s: EggShow, _ ctx: GraphicsContext, _ size: CGSize, progress p: Double, t: Double,
                                 image: (String) -> Image?) {
        if case .effect(let raw) = s.variant.source {
            EggEffect(rawValue: raw)?.draw(ctx, size, progress: p, t: t)
            return
        }
        let box = min(max(box(size, count: s.count) * s.size, minBox), maxBox)
        let f = frame(s, p: p, t: t, size: size, box: box)
        adornments(s, ctx, size, p: p, t: t, box: box, here: f)
        EggTrails.draw(s.trail, ctx, box: box, t: t, samples: (1...9).map { k in
            (frame(s, p: max(0, p - Double(k) * 0.014), t: t, size: size, box: box), k)
        }, here: f, ground: s.motion == .run || s.motion == .dive || s.motion == .bounce)
        var c = ctx
        c.opacity = f.opacity
        c.translateBy(x: f.center.x, y: f.center.y)
        c.rotate(by: .degrees(f.degrees))
        let k = box * f.scale / 200
        c.scaleBy(x: (f.flip ? -1 : 1) * k, y: k)
        c.translateBy(x: -100, y: -100)
        switch s.variant.source {
        case .figure(let raw):
            guard let fig = EggFigure(rawValue: raw) else { return }
            var pose = EggPose(t: t)
            pose.speed = fig.speed
            fig.draw(EggPainter(ctx: c, outlineOnly: s.look == .outline), pose)
        case .image(let file):
            guard let img = image(file) else { return }
            EggPuppet.draw(s.variant, c.resolve(img), c, t: t)
        case .effect:
            break
        }
    }

    /// What belongs to the MOTION rather than the trail: a shadow and dust
    /// for running, speed lines for flying and dashing, a starburst for pop.
    private static func adornments(_ s: EggShow, _ ctx: GraphicsContext, _ size: CGSize,
                                   p: Double, t: Double, box: CGFloat, here: EggFrame) {
        let back: CGFloat = here.flip ? 1 : -1        // behind is the way it isn't facing
        switch s.motion {
        case .run, .dive, .bounce:
            let ground = size.height * 0.72 + box * 0.38
            ctx.fill(Path(ellipseIn: CGRect(x: here.center.x - box * 0.35, y: ground - 6, width: box * 0.7, height: 12)),
                     with: .color(.black.opacity(0.18)))
            if s.motion != .bounce {
                for k in 1...5 {
                    let dx = here.center.x + back * (box * 0.38 + CGFloat(k) * 16)
                    let r = 5 + CGFloat(k) * 2.5 + CGFloat(sin(t * 20 + Double(k))) * 1.5
                    ctx.fill(Path(ellipseIn: CGRect(x: dx - r, y: ground - r - CGFloat(k) * 2, width: r * 2, height: r * 2)),
                             with: .color(Color(egg: 0xd9cbb3).opacity(0.55 - Double(k) * 0.08)))
                }
                speedLines(ctx, here.center, box: box, back: back)
            }
        case .flyBy, .auto, .dash, .wave:
            if s.motion != .dash || p < 0.25 || p > 0.7 { speedLines(ctx, here.center, box: box, back: back) }
        case .pop:
            for from in [0.0, 0.82] {
                let k = (p - from) / 0.18
                guard k > 0, k < 1 else { continue }
                for i in 0..<10 {
                    let a = Double(i) / 10 * 2 * .pi
                    let r = box * CGFloat(0.3 + 0.5 * k)
                    eggSparkle(ctx, CGPoint(x: here.center.x + r * CGFloat(cos(a)), y: here.center.y + r * CGFloat(sin(a))),
                               10 * CGFloat(1 - k), (i % 2 == 0 ? Color(egg: 0xffd23a) : .white).opacity(1 - k))
                }
            }
        default:
            break
        }
    }

    /// A festival greeting: a bold banner that pops in near the top.
    static func caption(_ text: String, _ ctx: GraphicsContext, _ size: CGSize, t: Double) {
        let k = min(1, t / 0.35)
        let scale = CGFloat(EggPath2.easeOutBack(k))
        var c = ctx
        c.translateBy(x: size.width / 2, y: size.height * 0.16)
        c.scaleBy(x: max(0.01, scale), y: max(0.01, scale))
        c.rotate(by: .degrees(-3))
        let label = c.resolve(Text(text).font(.system(size: 30, weight: .black, design: .rounded)).foregroundColor(.white))
        let sz = label.measure(in: CGSize(width: size.width, height: 100))
        let box = CGRect(x: -sz.width / 2 - 22, y: -sz.height / 2 - 12, width: sz.width + 44, height: sz.height + 24)
        c.fill(Path(roundedRect: box.offsetBy(dx: 4, dy: 5), cornerRadius: 22), with: .color(Color(egg: 0x1b1330)))
        c.fill(Path(roundedRect: box, cornerRadius: 22), with: .color(Color(egg: 0xe6327a)))
        c.stroke(Path(roundedRect: box, cornerRadius: 22), with: .color(Color(egg: 0x1b1330)), lineWidth: 3)
        c.draw(label, at: .zero)
        for i in 0..<6 {
            let a = Double(i) / 6 * 2 * .pi + t
            eggSparkle(c, CGPoint(x: (box.width / 2 + 16) * CGFloat(cos(a)), y: (box.height / 2 + 14) * CGFloat(sin(a))),
                       7, i % 2 == 0 ? Color(egg: 0xffd23a) : .white)
        }
    }

    private static func speedLines(_ ctx: GraphicsContext, _ c: CGPoint, box: CGFloat, back: CGFloat) {
        for i in 0..<3 {
            let y = c.y - box * 0.2 + CGFloat(i) * box * 0.2
            var line = Path()
            line.move(to: CGPoint(x: c.x + back * (box * 0.55 + CGFloat(i) * 10), y: y))
            line.addLine(to: CGPoint(x: c.x + back * (box * 0.95 + CGFloat(i) * 16), y: y))
            ctx.stroke(line, with: .color(.white.opacity(0.75)), style: StrokeStyle(lineWidth: 3, lineCap: .round))
        }
    }
}

/// The layer the overlay window hosts: every show, every frame.
struct EggStageView: View {
    @ObservedObject var stage: EggStage
    var settings: () -> EggSettings
    var image: (String) -> Image?

    var body: some View {
        TimelineView(.animation) { tl in
            Canvas { ctx, size in
                let now = tl.date
                // Screen-filling effects under the figures.
                let sorted = stage.shows.sorted { a, _ in if case .effect = a.variant.source { return true }; return false }
                for s in sorted {
                    let t = max(0, stage.elapsed(s, at: now) - s.delay)
                    EggRender.draw(s, ctx, size, progress: stage.progress(s, at: now), t: t, image: image)
                }
                if let caption = stage.caption, let first = stage.shows.first {
                    EggRender.caption(caption, ctx, size, t: now.timeIntervalSince(first.start))
                }
            }
        }
        .contentShape(Rectangle())
        .onTapGesture { stage.tap(settings()) }
        .ignoresSafeArea()
        .accessibilityLabel("Easter egg animation. Tap to close.")
    }
}
