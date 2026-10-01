import SwiftUI

// The ACTIVITIES set (Gil, 2026-10-01: "look at activities i have done like
// gym etc and at tag categories and make some animations and graphics for
// that"). Chosen from what the calendar actually holds, read-only, aggregates
// only: dog walks (the dog already exists), gym and calisthenics, a running
// plan (easy / threshold / long / speed runs, strides), groceries — the
// to-do list's biggest tag by far — and the tags Errands, Work, Coursework,
// Admin and Wishlist, plus cycling and cooking. Generic things, nothing
// personal: the same set ships to everyone.
//
// Same kit as every figure (EggArt.swift): flat fill, a hard shade band, white
// glints, ink outline, in a 200-unit box facing right; each moves on its own.

private extension EggPainter {
    /// The painter shifted by (dx, dy) — a whole figure lifted or hopping.
    func moved(_ dx: CGFloat, _ dy: CGFloat) -> EggPainter {
        var c = ctx
        c.translateBy(x: dx, y: dy)
        return EggPainter(ctx: c, line: line, outlineOnly: outlineOnly)
    }

    /// A thick limb: ink under, colour over — arms and legs on the chibi.
    func limb(_ d: String, _ color: Color, width: CGFloat = 9) {
        stroke(d, EggPainter.ink, width: width + 4)
        stroke(d, color, width: width)
    }

    /// A small round sweat drop / sparkle dot.
    func drop(_ x: CGFloat, _ y: CGFloat, _ r: CGFloat, _ color: Color) {
        part("M\(x) \(y - r * 1.6) Q\(x + r) \(y - r * 0.2) \(x) \(y + r) Q\(x - r) \(y - r * 0.2) \(x) \(y - r * 1.6) Z",
             color, width: 2)
    }
}

private let skin = Color(egg: 0xffd2b0), skinShade = Color(egg: 0xf0b48c)
private let hair = Color(egg: 0x2c2436)

// MARK: - Gym: a dumbbell, curled up and down, sweat flying at the top

func drawDumbbell(_ p: EggPainter, _ pose: EggPose) {
    let lift = CGFloat(abs(sin(pose.t * .pi * 1.4)))
    let q = p.moved(0, 24 - lift * 40)
    q.rotated(-8 * Double(lift), 100, 100) { r in
        r.part("M52 94 L148 94 L148 106 L52 106 Z", Color(egg: 0xb8c1cc), shade: Color(egg: 0x8a94a3), "M52 101 L148 101 L148 106 L52 106 Z")
        // the grip's knurling
        for x in stride(from: 82, through: 118, by: 6) {
            r.stroke("M\(x) 95 L\(x - 3) 105", Color(egg: 0x6b7280), width: 1.5)
        }
        for (x, w) in [(30, 22), (148, 22)] as [(CGFloat, CGFloat)] {
            r.part("M\(x) 62 Q\(x) 56 \(x + 6) 56 L\(x + w - 6) 56 Q\(x + w) 56 \(x + w) 62 L\(x + w) 138 Q\(x + w) 144 \(x + w - 6) 144 L\(x + 6) 144 Q\(x) 144 \(x) 138 Z",
                   Color(egg: 0x3a3f58), shade: Color(egg: 0x262a3d), "M\(x) 112 L\(x + w) 112 L\(x + w) 144 L\(x) 144 Z")
            r.glint("M\(x + 6) 66 L\(x + 6) 92", width: 3)
        }
        for x in [CGFloat(22), 170] {
            r.part("M\(x) 74 L\(x + 8) 74 L\(x + 8) 126 L\(x) 126 Z", Color(egg: 0xff5a5f), width: 3)
        }
    }
    if lift > 0.75 {
        let k = (lift - 0.75) * 4
        p.drop(70 - k * 18, 40 - k * 10, 5, Color(egg: 0x8fd3ff))
        p.drop(132 + k * 18, 36 - k * 12, 4, Color(egg: 0x8fd3ff))
    }
}

// MARK: - Calisthenics: a chibi doing pull-ups on a bar

func drawPullup(_ p: EggPainter, _ pose: EggPose) {
    let up = CGFloat((1 - cos(pose.t * .pi * 1.3)) / 2)          // 0 hanging … 1 chin over
    let headY = 100 - up * 46
    // the frame
    p.part("M24 34 L176 34 L176 44 L24 44 Z", Color(egg: 0xb8c1cc), shade: Color(egg: 0x8a94a3), "M24 40 L176 40 L176 44 L24 44 Z")
    p.part("M24 44 L34 44 L34 190 L24 190 Z", Color(egg: 0x6b7280), width: 3)
    p.part("M166 44 L176 44 L176 190 L166 190 Z", Color(egg: 0x6b7280), width: 3)
    // arms up to the bar
    p.limb("M84 \(headY + 28) Q\(78 - up * 6) \(headY - 4) 82 42", skin)
    p.limb("M116 \(headY + 28) Q\(122 + up * 6) \(headY - 4) 118 42", skin)
    p.part(p.ellipse(82, 40, 7, 6), skin, width: 3)
    p.part(p.ellipse(118, 40, 7, 6), skin, width: 3)
    // legs, swinging a little
    let kick = CGFloat(sin(pose.t * 4)) * 6
    p.limb("M92 \(headY + 70) Q\(90 + kick) \(headY + 90) \(88 + kick) \(headY + 104)", Color(egg: 0x3a3f58))
    p.limb("M108 \(headY + 70) Q\(110 + kick) \(headY + 90) \(112 + kick) \(headY + 104)", Color(egg: 0x3a3f58))
    // body and head
    p.part("M82 \(headY + 24) Q100 \(headY + 18) 118 \(headY + 24) L116 \(headY + 74) L84 \(headY + 74) Z",
           Color(egg: 0xff5a5f), shade: Color(egg: 0xd63f45), "M100 \(headY + 18) L120 \(headY + 18) L120 \(headY + 78) L100 \(headY + 78) Z")
    p.part(p.ellipse(100, headY, 22, 21), skin, shade: skinShade, p.ellipse(110, headY + 12, 18, 10))
    p.part("M78 \(headY - 4) Q80 \(headY - 26) 100 \(headY - 24) Q122 \(headY - 26) 122 \(headY - 4) Q112 \(headY - 14) 100 \(headY - 12) Q88 \(headY - 14) 78 \(headY - 4) Z", hair, width: 3)
    p.eye(92, headY + 2, 3.6, iris: Color(egg: 0x5a3a1a), blink: up > 0.9)
    p.eye(108, headY + 2, 3.6, iris: Color(egg: 0x5a3a1a), blink: up > 0.9)
    p.stroke(up > 0.8 ? "M95 \(headY + 12) Q100 \(headY + 16) 105 \(headY + 12)" : "M96 \(headY + 13) L104 \(headY + 13)", width: 2.5)
    p.blush(86, headY + 10, 4); p.blush(114, headY + 10, 4)
}

// MARK: - Run: a running shoe, toe-off and land, dust behind

func drawSneaker(_ p: EggPainter, _ pose: EggPose) {
    let step = pose.cycle
    let hop = CGFloat(abs(sin(step * .pi))) * 22
    let tilt = 14 * sin(step * 2 * .pi)
    for i in 0..<3 {
        let y = CGFloat(118 + i * 14)
        p.stroke("M\(12 + i * 6) \(y) L\(42 + i * 2) \(y)", Color(egg: 0xb8c1cc), width: 3)
    }
    p.moved(0, -hop).rotated(tilt, 120, 150) { q in
        // sole
        q.part("M40 140 Q36 160 56 162 L160 162 Q182 160 178 146 L176 140 Z", .white, shade: Color(egg: 0xd9dee6), "M40 152 L180 152 L180 170 L40 170 Z")
        // upper
        q.part("M44 140 Q42 104 66 96 L96 92 Q104 112 128 116 L160 122 Q178 128 176 140 Z",
               Color(egg: 0x3a7bff), shade: Color(egg: 0x2256c7), "M44 126 L180 126 L180 142 L44 142 Z")
        // the stripe
        q.part("M70 132 Q100 106 150 128 Q110 120 84 136 Z", Color(egg: 0xffd23a), width: 2.5)
        // heel tab and collar
        q.part("M46 104 Q44 92 56 92 L66 96 Q54 100 52 112 Z", Color(egg: 0xff5a5f), width: 2.5)
        // laces
        for i in 0..<3 {
            let x = CGFloat(96 + i * 11), y = CGFloat(98 + i * 6)
            q.stroke("M\(x - 4) \(y) L\(x + 6) \(y + 4)", .white, width: 3)
        }
        q.glint("M54 116 Q58 104 66 100", width: 3)
    }
}

// MARK: - Groceries: a cart rolling, the shopping bouncing in it

func drawCart(_ p: EggPainter, _ pose: EggPose) {
    let roll = pose.t * 360 * 1.2
    let jig = { (k: Double) -> CGFloat in CGFloat(abs(sin(pose.t * 5 + k))) * 8 }
    // the shopping, behind the basket's front
    p.moved(0, -jig(0)).part(p.ellipse(84, 78, 15, 14), Color(egg: 0xff4d4d), shade: Color(egg: 0xd12f2f), p.ellipse(90, 86, 12, 8))
    p.moved(0, -jig(0)).stroke("M84 64 Q86 58 92 56", Color(egg: 0x3a7d2c), width: 3)
    p.moved(0, -jig(1.3)).rotated(-28, 120, 72) { q in
        q.part(q.ellipse(120, 72, 30, 9), Color(egg: 0xe8b25d), shade: Color(egg: 0xc98c35), q.ellipse(122, 78, 30, 4))
        q.stroke("M104 68 L110 76 M118 66 L124 74 M132 66 L138 74", Color(egg: 0xc98c35), width: 2)
    }
    p.moved(0, -jig(2.4)).part("M140 54 L156 54 L160 64 L160 96 L140 96 Z", .white, shade: Color(egg: 0xdbe6f5), "M150 54 L160 54 L160 96 L150 96 Z")
    p.moved(0, -jig(2.4)).part("M140 70 L160 70 L160 80 L140 80 Z", Color(egg: 0x3a7bff), width: 2)
    // basket
    p.part("M50 84 L176 84 L164 134 L64 134 Z", Color(egg: 0xc9d3df, 0.85), shade: Color(egg: 0xa4b0bf, 0.85), "M50 118 L176 118 L176 134 L50 134 Z")
    for x in stride(from: 72, through: 156, by: 14) { p.stroke("M\(x) 86 L\(x - 3) 132", Color(egg: 0x8a94a3), width: 2) }
    p.stroke("M56 102 L172 102", Color(egg: 0x8a94a3), width: 2)
    // handle and frame
    p.limb("M50 84 L34 62 L18 62", Color(egg: 0xff5a5f), width: 5)
    p.limb("M64 134 L68 150 L160 150", Color(egg: 0x6b7280), width: 4)
    for x in [CGFloat(78), 150] {
        p.part(p.ellipse(x, 164, 11, 11), Color(egg: 0x3a3f58), width: 3)
        p.rotated(roll, x, 164) { q in q.stroke("M\(x - 7) 164 L\(x + 7) 164 M\(x) 157 L\(x) 171", Color(egg: 0xb8c1cc), width: 2) }
    }
}

// MARK: - Work: a laptop, code typing itself, the cursor blinking

func drawLaptop(_ p: EggPainter, _ pose: EggPose) {
    let bob = CGFloat(sin(pose.t * 3)) * 3
    let q = p.moved(0, bob)
    q.part("M44 36 L156 36 Q164 36 164 44 L164 126 L36 126 L36 44 Q36 36 44 36 Z", Color(egg: 0x3a3f58), width: 4)
    q.part("M46 46 L154 46 L154 118 L46 118 Z", Color(egg: 0x16213e), width: 2.5)
    if !q.outlineOnly {
        // lines of code, typed one after another
        let colors: [UInt32] = [0x7ee787, 0xffa657, 0x79c0ff, 0xd2a8ff, 0x7ee787, 0xffa657]
        // ~90 units a second: a screenful in about four seconds, then again
        let typed = CGFloat((pose.t * 90).truncatingRemainder(dividingBy: 420))
        for i in 0..<6 {
            let full: CGFloat = [70, 52, 82, 40, 64, 58][i]
            let indent: CGFloat = [0, 10, 10, 20, 10, 0][i]
            let w = max(0, min(full, typed - CGFloat(i) * 66))
            if w > 0 {
                q.ctx.fill(Path(roundedRect: CGRect(x: 54 + indent, y: 54 + CGFloat(i) * 10, width: w, height: 5), cornerRadius: 2.5),
                           with: .color(Color(egg: colors[i])))
            }
        }
        if Int(pose.t * 3) % 2 == 0 {
            q.ctx.fill(Path(CGRect(x: 54, y: 112, width: 8, height: 3)), with: .color(.white))
        }
    }
    q.part("M24 126 L176 126 L186 144 Q186 150 180 150 L20 150 Q14 150 14 144 Z", Color(egg: 0xb8c1cc), shade: Color(egg: 0x8a94a3), "M14 140 L186 140 L186 152 L14 152 Z")
    q.part("M84 130 L116 130 L114 136 L86 136 Z", Color(egg: 0x8a94a3), width: 2)
    q.glint("M50 50 L70 50", width: 2.5)
}

// MARK: - Study: a stack of books, the mortarboard bobbing, tassel swinging

func drawBooks(_ p: EggPainter, _ pose: EggPose) {
    let books: [(CGFloat, CGFloat, UInt32, UInt32)] = [(40, 150, 0x3a7bff, 0x2256c7), (52, 124, 0xff5a5f, 0xd63f45), (44, 98, 0x22c55e, 0x15803d)]
    for (x, y, base, shade) in books {
        p.part("M\(x) \(y) L\(x + 116) \(y) L\(x + 116) \(y + 24) L\(x) \(y + 24) Z", Color(egg: base), shade: Color(egg: shade), "M\(x) \(y + 16) L\(x + 116) \(y + 16) L\(x + 116) \(y + 24) L\(x) \(y + 24) Z")
        p.part("M\(x + 104) \(y + 3) L\(x + 113) \(y + 3) L\(x + 113) \(y + 21) L\(x + 104) \(y + 21) Z", Color(egg: 0xfff6e0), width: 2)
        p.stroke("M\(x + 14) \(y + 8) L\(x + 60) \(y + 8)", Color(egg: 0xffd23a), width: 2.5)
    }
    let bob = CGFloat(abs(sin(pose.t * 2.6))) * 16
    p.moved(0, -bob).rotated(6 * sin(pose.t * 2.6), 100, 80) { q in
        q.part("M100 50 L152 66 L100 82 L48 66 Z", Color(egg: 0x1b1330), shade: Color(egg: 0x2c2436), "M100 66 L152 66 L100 82 Z")
        q.part("M74 74 L74 90 Q100 100 126 90 L126 74 L100 82 Z", Color(egg: 0x2c2436), width: 3)
        q.part(q.ellipse(100, 66, 4, 3), Color(egg: 0xffd23a), width: 2)
        q.rotated(22 * sin(pose.t * 4), 100, 66) { r in
            r.stroke("M100 66 L140 70 L142 92", Color(egg: 0xffd23a), width: 3)
            r.part("M138 92 L146 92 L148 104 L136 104 Z", Color(egg: 0xffd23a), width: 2)
        }
    }
}

// MARK: - Cycling: a bicycle, wheels and pedals turning

func drawBicycle(_ p: EggPainter, _ pose: EggPose) {
    let turn = pose.t * 360 * 1.6
    let frame = Color(egg: 0x22c55e)
    for x in [CGFloat(52), 150] {
        p.part(p.ellipse(x, 140, 36, 36), .clear, width: 6)
        p.ctx.stroke(p.ellipse(x, 140, 30, 30), with: .color(p.outlineOnly ? .white : Color(egg: 0xb8c1cc)), lineWidth: 2)
        p.rotated(turn, x, 140) { q in
            for k in 0..<6 {
                let a = Double(k) * .pi / 3
                q.stroke("M\(x) 140 L\(x + 30 * CGFloat(cos(a))) \(140 + 30 * CGFloat(sin(a)))", Color(egg: 0xb8c1cc), width: 1.5)
            }
        }
        p.part(p.ellipse(x, 140, 5, 5), Color(egg: 0x6b7280), width: 2)
    }
    p.limb("M52 140 L88 140 L120 92 L72 92 Z", frame, width: 5)
    p.limb("M88 140 L68 82", frame, width: 5)
    p.limb("M120 92 L150 140", frame, width: 5)
    p.limb("M120 92 L114 70 L132 66", Color(egg: 0x3a3f58), width: 4)
    p.part("M56 76 Q68 70 82 76 L80 82 L58 82 Z", Color(egg: 0x3a3f58), width: 3)
    p.rotated(turn, 88, 140) { q in
        q.limb("M88 128 L88 152", Color(egg: 0x6b7280), width: 3)
        q.part("M80 124 L96 124 L96 130 L80 130 Z", Color(egg: 0x3a3f58), width: 2)
        q.part("M80 150 L96 150 L96 156 L80 156 Z", Color(egg: 0x3a3f58), width: 2)
    }
    p.part(p.ellipse(88, 140, 8, 8), Color(egg: 0xb8c1cc), width: 2.5)
}

// MARK: - Errands: a clipboard, the boxes ticking themselves off

func drawClipboard(_ p: EggPainter, _ pose: EggPose) {
    let sway = 5 * sin(pose.t * 2)
    p.rotated(sway, 100, 180) { q in
        q.part("M52 30 L148 30 Q156 30 156 38 L156 178 Q156 186 148 186 L52 186 Q44 186 44 178 L44 38 Q44 30 52 30 Z",
               Color(egg: 0xc98c35), shade: Color(egg: 0xa86e22), "M44 160 L156 160 L156 186 L44 186 Z")
        q.part("M58 44 L142 44 L142 174 L58 174 Z", .white, shade: Color(egg: 0xeef1f7), "M58 150 L142 150 L142 174 L58 174 Z")
        q.part("M78 22 L122 22 Q128 22 128 28 L128 44 L72 44 L72 28 Q72 22 78 22 Z", Color(egg: 0xb8c1cc), shade: Color(egg: 0x8a94a3), "M72 36 L128 36 L128 44 L72 44 Z")
        let done = Int(pose.t * 1.6) % 5
        for i in 0..<3 {
            let y = CGFloat(66 + i * 34)
            q.part("M66 \(y) L84 \(y) L84 \(y + 18) L66 \(y + 18) Z", .white, width: 2.5)
            q.stroke("M92 \(y + 9) L\(130 - i * 8) \(y + 9)", Color(egg: 0xb8c1cc), width: 4)
            if i < done {
                q.stroke("M68 \(y + 9) L74 \(y + 16) L88 \(y - 4)", Color(egg: 0x22c55e), width: 4.5)
            }
        }
    }
}

// MARK: - Cooking: a pot on the boil, the lid rattling, steam curling up

func drawPot(_ p: EggPainter, _ pose: EggPose) {
    for i in 0..<3 {
        let k = (pose.t * 0.8 + Double(i) / 3).truncatingRemainder(dividingBy: 1)
        let x = CGFloat(76 + i * 24), y = CGFloat(70 - k * 60)
        let w = CGFloat(sin(pose.t * 3 + Double(i))) * 6
        if !p.outlineOnly {
            p.ctx.stroke(EggPath("M\(x) \(y + 24) Q\(x + w + 8) \(y + 14) \(x) \(y + 6) Q\(x - w - 8) \(y - 2) \(x) \(y - 10)"),
                         with: .color(.white.opacity(0.85 * (1 - k))), style: StrokeStyle(lineWidth: 5, lineCap: .round))
        }
    }
    let rattle = CGFloat(abs(sin(pose.t * 9))) * 6
    p.part("M40 100 L160 100 L154 168 Q152 178 140 178 L60 178 Q48 178 46 168 Z",
           Color(egg: 0xff5a5f), shade: Color(egg: 0xd63f45), "M40 150 L160 150 L160 180 L40 180 Z")
    p.glint("M58 112 L56 150", width: 4)
    p.part("M26 108 Q20 108 20 116 Q20 124 28 124 L42 124 L42 108 Z", Color(egg: 0x3a3f58), width: 3)
    p.part("M174 108 Q180 108 180 116 Q180 124 172 124 L158 124 L158 108 Z", Color(egg: 0x3a3f58), width: 3)
    p.moved(0, -rattle).rotated(Double(rattle) * 0.8, 100, 96) { q in
        q.part("M34 100 Q100 74 166 100 Z", Color(egg: 0xb8c1cc), shade: Color(egg: 0x8a94a3), "M34 96 L166 96 L166 102 L34 102 Z")
        q.part(q.ellipse(100, 80, 10, 6), Color(egg: 0x3a3f58), width: 3)
    }
}

// MARK: - Admin: a passport, the stamp coming down on it

func drawPassport(_ p: EggPainter, _ pose: EggPose) {
    let phase = (pose.t * 0.8).truncatingRemainder(dividingBy: 1)
    let stamped = phase > 0.45
    p.rotated(-6, 100, 110) { q in
        q.part("M48 54 L146 54 Q154 54 154 62 L154 176 Q154 184 146 184 L48 184 Z", Color(egg: 0x1e3a8a), shade: Color(egg: 0x172b66), "M48 160 L154 160 L154 184 L48 184 Z")
        q.part(q.ellipse(100, 108, 22, 22), .clear, width: 3)
        q.ctx.stroke(q.ellipse(100, 108, 22, 22), with: .color(q.outlineOnly ? .white : Color(egg: 0xffd23a)), lineWidth: 3)
        q.stroke("M78 108 L122 108 M100 86 Q86 108 100 130 M100 86 Q114 108 100 130", Color(egg: 0xffd23a), width: 2)
        q.stroke("M76 150 L124 150", Color(egg: 0xffd23a), width: 3)
        if stamped && !q.outlineOnly {
            q.ctx.stroke(q.ellipse(128, 76, 18, 14), with: .color(Color(egg: 0xff4d4d, 0.9)), lineWidth: 3)
            q.stroke("M118 78 L124 84 L138 68", Color(egg: 0xff4d4d), width: 3)
        }
    }
    // the stamp: up, then down hard
    let drop: CGFloat = phase < 0.45 ? CGFloat(phase / 0.45) : (phase < 0.6 ? 1 : CGFloat(1 - (phase - 0.6) / 0.4))
    let y = 10 + drop * 38
    p.part("M118 \(y + 22) L150 \(y + 22) L150 \(y + 32) L118 \(y + 32) Z", Color(egg: 0x3a3f58), width: 3)
    p.part("M128 \(y) L140 \(y) L140 \(y + 22) L128 \(y + 22) Z", Color(egg: 0xc98c35), width: 3)
    p.part(p.ellipse(134, y - 2, 12, 8), Color(egg: 0xc98c35), shade: Color(egg: 0xa86e22), p.ellipse(134, y + 2, 12, 4))
}

// MARK: - Wishlist: a gift, the lid popping, hearts out

func drawGift(_ p: EggPainter, _ pose: EggPose) {
    let pop = CGFloat(max(0, sin(pose.t * 2.4))) * 30
    if pop > 12 && !p.outlineOnly {
        for i in 0..<3 {
            let k = Double(pop - 12) / 18
            let x = CGFloat(76 + i * 24) + CGFloat(i - 1) * CGFloat(k) * 14, y = 74 - CGFloat(k) * 40 - CGFloat(i % 2) * 8
            p.ctx.fill(EggPath("M\(x) \(y + 12) C\(x - 18) \(y - 2) \(x - 11) \(y - 18) \(x) \(y - 7) C\(x + 11) \(y - 18) \(x + 18) \(y - 2) \(x) \(y + 12) Z"),
                       with: .color(Color(egg: 0xff7aa2, 1 - k * 0.5)))
        }
    }
    p.part("M46 96 L154 96 L154 176 L46 176 Z", Color(egg: 0xa78bfa), shade: Color(egg: 0x7c5ce0), "M120 96 L154 96 L154 176 L120 176 Z")
    p.part("M90 96 L110 96 L110 176 L90 176 Z", Color(egg: 0xffd23a), width: 3)
    p.moved(0, -pop).rotated(Double(-pop) * 0.4, 46, 92) { q in
        q.part("M38 76 L162 76 L162 98 L38 98 Z", Color(egg: 0xa78bfa), shade: Color(egg: 0x7c5ce0), "M120 76 L162 76 L162 98 L120 98 Z")
        q.part("M90 76 L110 76 L110 98 L90 98 Z", Color(egg: 0xffd23a), width: 3)
        q.part("M100 76 Q74 46 68 66 Q66 78 100 76 Z", Color(egg: 0xffd23a), width: 3)
        q.part("M100 76 Q126 46 132 66 Q134 78 100 76 Z", Color(egg: 0xffd23a), width: 3)
    }
    p.glint("M54 108 L54 140", width: 4)
}
