import SwiftUI

// The Jewish festivals set: fourteen figures in the same anime cel style,
// each with the movement it has on the day — the lulav shaken in the
// na'anuim, the grogger whirled at Haman's name, the dreidel spinning through
// נ ג ה ש, the candles flickering, the Torah danced in hakafot — and the
// festival seasons they belong to (`EggFestivals`).

private let gold = Color(egg: 0xf2c14e), goldShade = Color(egg: 0xc98f1c)
private let flameOuter = Color(egg: 0xff9a2f), flameInner = Color(egg: 0xfff08a)

/// A candle flame that flickers.
private func flame(_ p: EggPainter, _ x: CGFloat, _ y: CGFloat, _ t: Double, _ k: Double) {
    let f = 1 + 0.18 * sin(t * 13 + k * 2.1)
    p.scaled(CGFloat(f), CGFloat(1 + 0.25 * sin(t * 17 + k)), x, y + 6) { q in
        q.ctx.fill(q.ellipse(x, y, 9, 13), with: .color(flameOuter.opacity(q.outlineOnly ? 0 : 0.35)))
        q.part("M\(x) \(y - 12) C\(x + 7) \(y - 2) \(x + 6) \(y + 6) \(x) \(y + 7) C\(x - 6) \(y + 6) \(x - 7) \(y - 2) \(x) \(y - 12) Z",
               flameOuter, width: 2)
        q.fill("M\(x) \(y - 4) C\(x + 3) \(y + 1) \(x + 3) \(y + 5) \(x) \(y + 5) C\(x - 3) \(y + 5) \(x - 3) \(y + 1) \(x) \(y - 4) Z",
               flameInner)
    }
}

func drawLulav(_ p: EggPainter, _ pose: EggPose) {
    // Na'anuim: shaken back and forth from the hand.
    p.rotated(-18 + 11 * sin(pose.t * 15), 100, 188) { p in
        let willow = Color(egg: 0x9ccf6a), myrtle = Color(egg: 0x2f7a3a)
        p.part("M92 150 C78 118 76 88 84 64 C90 90 93 120 97 150 Z", willow)
        p.part("M108 150 C122 118 124 88 116 64 C110 90 107 120 103 150 Z", willow)
        p.part("M95 190 L93 30 C93 16 107 16 107 30 L105 190 Z", Color(egg: 0x46a852),
               shade: Color(egg: 0x2f8a3c), "M100 0 L120 0 L120 200 L100 200 Z")
        for i in 0..<9 {
            let y = CGFloat(34 + i * 13)
            p.stroke("M100 \(y) L94 \(y + 9) M100 \(y) L106 \(y + 9)", Color(egg: 0x2b6e34), width: 2)
        }
        for (x, y) in [(86, 104), (114, 102), (84, 118), (116, 116), (86, 132), (114, 130), (90, 144), (110, 142)] {
            p.part(p.ellipse(CGFloat(x), CGFloat(y), 6.5, 4.5), myrtle, width: 2)
        }
        p.part("M89 150 L111 150 L111 166 L89 166 Z", Color(egg: 0xd1a868), width: 3)
        p.stroke("M89 155 L111 155 M89 161 L111 161", Color(egg: 0xa27a3c), width: 2)
    }
}

func drawEtrog(_ p: EggPainter, _ pose: EggPose) {
    let body = "M40 104 C40 70 80 58 110 60 C140 62 166 78 172 100 C176 112 172 120 176 124 C166 134 150 146 118 148 C82 150 40 136 40 104 Z"
    p.part("M32 98 C20 80 4 78 0 88 C8 98 20 102 32 102 Z", Color(egg: 0x3f9e4a))
    p.part("M40 100 L28 96 L30 107 Z", Color(egg: 0x8a5a2b), width: 3)
    p.part(body, Color(egg: 0xf4d23c), shade: Color(egg: 0xd9ae1f), "M20 118 C80 150 140 150 200 116 L200 170 L20 170 Z")
    for (x, y) in [(70, 90), (92, 80), (120, 84), (146, 96), (84, 112), (110, 104), (136, 118), (62, 118), (104, 128)] {
        p.fill("M\(x) \(y) m0 0", .clear)
        p.ctx.fill(p.ellipse(CGFloat(x), CGFloat(y), 2.2, 2.2), with: .color(p.outlineOnly ? .clear : Color(egg: 0xcf9f16)))
    }
    p.part("M173 120 L187 117 L185 129 Z", Color(egg: 0x8a5a2b), width: 3)
    p.glint("M66 78 C80 70 96 67 110 67", width: 4)
    p.eye(96, 100, 6, iris: Color(egg: 0x3a8bff), blink: pose.cycle > 0.94)
    p.eye(122, 100, 6, iris: Color(egg: 0x3a8bff), blink: pose.cycle > 0.94)
    p.stroke("M104 116 Q109 120 114 116", width: 2.5)
    p.blush(84, 112, 5); p.blush(134, 112, 5)
}

func drawSukkah(_ p: EggPainter, _ pose: EggPose) {
    let wood = Color(egg: 0xd9a86c), woodShade = Color(egg: 0xb07d45)
    p.part("M30 88 L170 88 L170 182 L30 182 Z", wood, shade: woodShade, "M30 160 L170 160 L170 190 L30 190 Z")
    for x in stride(from: 48, through: 152, by: 18) { p.stroke("M\(x) 92 L\(x) 180", woodShade, width: 2) }
    p.part("M84 118 C84 106 116 106 116 118 L116 182 L84 182 Z", Color(egg: 0x6b4a30))
    p.part("M86 120 C92 116 98 118 100 126 L100 180 L86 180 Z", Color(egg: 0xff7eb6), width: 2.5)      // curtain
    // S'chach: branches on the roof, leaves stirring.
    p.part("M18 90 C28 62 50 72 60 62 C72 52 88 66 100 56 C114 46 128 62 140 56 C156 48 170 64 184 84 L182 96 L18 96 Z",
           Color(egg: 0x4caf50), shade: Color(egg: 0x2f8a3c), "M0 86 L200 86 L200 100 L0 100 Z")
    for i in 0..<7 {
        let x = CGFloat(28 + i * 24)
        p.rotated(8 * sin(pose.t * 3 + Double(i)), x, 70) { $0.stroke("M\(x) 70 L\(x - 6) 56 M\(x) 70 L\(x + 7) 58", Color(egg: 0x2f8a3c), width: 2.5) }
    }
    // Hanging decorations, swinging.
    for (i, (x, c)) in [(50.0, 0xe8343f), (150.0, 0xff9a2f), (100.0, 0x7a4ce0)].enumerated() {
        let len: CGFloat = i == 2 ? 10 : 20
        p.rotated(14 * sin(pose.t * 2.6 + Double(i) * 1.7), CGFloat(x), 96) { q in
            q.stroke("M\(x) 96 L\(x) \(96 + len)", EggPainter.ink, width: 1.5)
            q.part(q.ellipse(CGFloat(x), 96 + len + 7, 7, 7), Color(egg: UInt32(c)), width: 2.5)
        }
    }
    for i in 0..<6 {
        let on = (Int(pose.t * 4) + i) % 2 == 0
        p.ctx.fill(p.ellipse(CGFloat(34 + i * 26), 98, 3, 3), with: .color(on && !p.outlineOnly ? Color(egg: 0xfff15a) : .clear))
    }
}

func drawMask(_ p: EggPainter, _ pose: EggPose) {
    p.stroke("M40 110 L14 180", EggPainter.ink, width: 8)
    p.stroke("M40 110 L14 180", gold, width: 4)
    for (i, c) in [0xff7eb6, 0x3fd0c9, 0xffd23a].enumerated() {
        p.rotated(Double(i) * 16 - 16 + 6 * sin(pose.t * 4 + Double(i)), 160, 78) {
            $0.part("M160 78 C168 44 184 24 196 16 C192 40 180 62 166 82 Z", Color(egg: UInt32(c)), width: 3)
        }
    }
    let mask = "M30 90 C30 70 60 66 80 76 C90 82 94 88 100 88 C106 88 110 82 120 76 C140 66 170 70 170 90 C170 112 146 124 124 114 C112 108 106 104 100 104 C94 104 88 108 76 114 C54 124 30 112 30 90 Z"
    p.part(mask, Color(egg: 0x7b3fe4), shade: Color(egg: 0x5a27b8), "M20 100 L180 100 L180 130 L20 130 Z")
    p.part(p.ellipse(66, 93, 16, 10), Color(egg: 0x1b1330), width: 3)
    p.part(p.ellipse(134, 93, 16, 10), Color(egg: 0x1b1330), width: 3)
    p.stroke("M36 84 C50 74 64 74 78 82 M122 82 C136 74 150 74 164 84", gold, width: 3)
    p.ctx.fill(p.ellipse(100, 96, 4, 4), with: .color(p.outlineOnly ? .clear : gold))
    p.glint("M44 80 C52 74 60 72 68 72", width: 3)
}

func drawGrogger(_ p: EggPainter, _ pose: EggPose) {
    let angle = pose.t * 16
    let sq = CGFloat(cos(angle))
    p.part("M58 190 L74 190 L74 112 L58 112 Z", Color(egg: 0xd9463f), shade: Color(egg: 0xb52a38), "M66 100 L80 100 L80 200 L66 200 Z")
    p.scaled(sq == 0 ? 0.01 : sq, 1, 66, 104) { q in
        q.part("M66 76 L156 76 L156 132 L66 132 Z", Color(egg: 0xffd23a), shade: Color(egg: 0xe09a1e), "M60 116 L160 116 L160 140 L60 140 Z")
        q.stroke("M86 76 L86 132 M110 76 L110 132 M134 76 L134 132", Color(egg: 0x3a7bff), width: 5)
    }
    p.part(p.ellipse(66, 104, 11, 11), Color(egg: 0x8a91a3), width: 3)
    for i in 0..<3 {
        let r = CGFloat(96 + i * 10)
        var arc = Path()
        arc.addArc(center: CGPoint(x: 66, y: 104), radius: r, startAngle: .degrees(-30 + Double(i) * 8), endAngle: .degrees(20 + Double(i) * 8), clockwise: false)
        p.ctx.stroke(arc, with: .color(.white.opacity(0.7)), style: StrokeStyle(lineWidth: 3, lineCap: .round))
    }
}

func drawHamantasch(_ p: EggPainter, _ pose: EggPose) {
    p.part("M100 34 C112 34 178 150 172 160 C166 172 34 172 28 160 C22 150 88 34 100 34 Z",
           Color(egg: 0xe9b45c), shade: Color(egg: 0xcc8f3a), "M10 150 L190 150 L190 180 L10 180 Z")
    p.part("M100 80 C106 80 140 138 136 146 C132 152 68 152 64 146 C60 138 94 80 100 80 Z", Color(egg: 0x6a2a5a))
    for (x, y) in [(92, 120), (106, 112), (112, 132), (88, 138), (100, 100)] {
        p.ctx.fill(p.ellipse(CGFloat(x), CGFloat(y), 1.8, 1.8), with: .color(p.outlineOnly ? .clear : Color(egg: 0x2a0f24)))
    }
    p.stroke("M60 126 C70 118 76 116 84 110 M140 126 C130 118 124 116 116 110 M84 158 L116 158", Color(egg: 0xb87a2e), width: 2.5)
    p.glint("M92 46 C82 62 72 80 62 98", width: 3.5)
}

func drawMenorah(_ p: EggPainter, _ pose: EggPose) {
    p.part("M66 188 L134 188 L122 172 L78 172 Z", gold, shade: goldShade, "M60 182 L140 182 L140 196 L60 196 Z")
    p.part("M96 172 L104 172 L104 104 L96 104 Z", gold, width: 3)
    p.part("M20 100 L180 100 L180 110 L20 110 Z", gold, shade: goldShade, "M20 106 L180 106 L180 114 L20 114 Z")
    let xs: [CGFloat] = [26, 44, 62, 80, 120, 138, 156, 174]
    for (k, x) in xs.enumerated() {
        p.part("M\(x - 4) 72 L\(x + 4) 72 L\(x + 4) 100 L\(x - 4) 100 Z", k % 2 == 0 ? Color(egg: 0x9fc9ff) : .white, width: 2.5)
        flame(p, x, 62, pose.t, Double(k))
    }
    p.part("M92 78 L108 78 L108 104 L92 104 Z", gold, width: 3)                 // the shamash's cup
    p.part("M96 46 L104 46 L104 78 L96 78 Z", Color(egg: 0x9fc9ff), width: 2.5)
    flame(p, 100, 36, pose.t, 9)
}

func drawDreidel(_ p: EggPainter, _ pose: EggPose) {
    let letters = ["נ", "ג", "ה", "ש"]
    let spin = pose.t * 3
    let face = CGFloat(abs(cos(spin * .pi)))
    p.rotated(10 * sin(pose.t * 2.5), 100, 172) { q in
        q.part("M92 28 L108 28 L108 62 L92 62 Z", Color(egg: 0xf2c14e), width: 3)
        q.part("M66 60 L134 60 L134 130 L100 172 L66 130 Z", Color(egg: 0x3a7bff), shade: Color(egg: 0x2256c7),
               "M\(100 + 34 * face) 50 L150 50 L150 180 L\(100 + 34 * face) 180 Z")
        q.glint("M72 68 L72 122", width: 3.5)
        if !q.outlineOnly {
            let letter = letters[Int(spin * 2) % letters.count]
            var c = q.ctx
            c.translateBy(x: 100, y: 96)
            c.scaleBy(x: max(0.05, face), y: 1)
            c.draw(Text(letter).font(.system(size: 42, weight: .heavy)).foregroundColor(.white), at: .zero)
        }
    }
    for i in 0..<3 {
        let y = CGFloat(80 + i * 22)
        p.stroke("M150 \(y) L\(166 + CGFloat(i) * 4) \(y)", .white, width: 3)
        p.stroke("M50 \(y) L\(34 - CGFloat(i) * 4) \(y)", .white, width: 3)
    }
}

func drawShofar(_ p: EggPainter, _ pose: EggPose) {
    let shake = CGFloat(sin(pose.t * 40)) * 1.2
    var c = p.ctx
    c.translateBy(x: shake, y: 0)
    let q = EggPainter(ctx: c, line: p.line, outlineOnly: p.outlineOnly)
    q.part("M26 116 C40 124 70 140 110 130 C140 122 164 96 176 58 L196 66 C190 110 160 146 112 154 C68 160 40 144 24 128 Z",
           Color(egg: 0xe8cc98), shade: Color(egg: 0xb8925a), "M0 140 C60 170 140 170 200 120 L200 200 L0 200 Z")
    for i in 0..<6 {
        let x = CGFloat(50 + i * 22)
        q.stroke("M\(x) \(126 + CGFloat(i) * -4) C\(x + 4) \(134 - CGFloat(i) * 8) \(x + 6) \(142 - CGFloat(i) * 10) \(x + 2) \(152 - CGFloat(i) * 12)", Color(egg: 0x9c7442), width: 2.5)
    }
    q.part(q.ellipse(186, 62, 11, 5), Color(egg: 0x5a3a1c), width: 3)
    q.part("M20 118 L28 114 L30 128 L22 130 Z", Color(egg: 0x8a5a2b), width: 3)
    q.glint("M60 132 C80 138 100 136 118 130", width: 3)
    // The blast: sound rings out of the bell.
    for i in 0..<3 {
        let k = (pose.t * 1.5 + Double(i) / 3).truncatingRemainder(dividingBy: 1)
        var ring = Path()
        ring.addArc(center: CGPoint(x: 188, y: 60), radius: CGFloat(14 + 30 * k), startAngle: .degrees(-70), endAngle: .degrees(40), clockwise: false)
        p.ctx.stroke(ring, with: .color(.white.opacity(1 - k)), style: StrokeStyle(lineWidth: 3, lineCap: .round))
    }
}

func drawAppleHoney(_ p: EggPainter, _ pose: EggPose) {
    p.part("M40 110 C40 80 60 72 76 80 C84 72 108 76 110 106 C112 138 92 158 76 150 C66 158 40 142 40 110 Z",
           Color(egg: 0xe8343f), shade: Color(egg: 0xb81f2d), "M30 130 L120 130 L120 170 L30 170 Z")
    p.stroke("M76 80 L80 62", Color(egg: 0x6b4a30), width: 4)
    p.part("M80 66 C90 54 104 56 108 62 C100 70 90 70 80 66 Z", Color(egg: 0x4caf50), width: 2.5)
    p.glint("M50 96 C52 88 58 84 64 84", width: 3.5)
    let jar = "M116 92 L176 92 C182 92 184 98 184 104 L184 160 C184 168 178 172 172 172 L120 172 C114 172 110 168 110 160 L110 104 C110 98 112 92 116 92 Z"
    p.part(jar, Color(egg: 0xf5a623), shade: Color(egg: 0xd9821a), "M100 140 L200 140 L200 180 L100 180 Z")
    p.part("M112 80 L180 80 L184 94 L108 94 Z", Color(egg: 0xe8343f), width: 3)
    if !p.outlineOnly {
        p.ctx.draw(Text("דבש").font(.system(size: 20, weight: .bold)).foregroundColor(Color(egg: 0x6b3a0a)), at: CGPoint(x: 147, y: 130))
    }
    p.glint("M118 104 L118 150", width: 3.5)
    // The dipper, and a drop of honey that swells and falls.
    p.stroke("M150 94 L178 40", Color(egg: 0x8a5a2b), width: 5)
    let d = (pose.t * 0.8).truncatingRemainder(dividingBy: 1)
    p.ctx.fill(p.ellipse(176, 44 + CGFloat(d) * 40, 3 + CGFloat(d) * 2, 4 + CGFloat(d) * 3),
               with: .color(p.outlineOnly ? .clear : Color(egg: 0xf5a623).opacity(1 - d * 0.5)))
}

func drawMatzah(_ p: EggPainter, _ pose: EggPose) {
    p.part("M36 44 C80 38 120 50 164 42 C170 80 160 120 166 158 C120 164 80 152 36 160 C42 120 30 80 36 44 Z",
           Color(egg: 0xf3dfb0), shade: Color(egg: 0xd9bd82), "M20 140 L180 140 L180 170 L20 170 Z")
    for row in 0..<6 {
        let y = CGFloat(62 + row * 18)
        for col in 0..<11 {
            p.ctx.fill(p.ellipse(CGFloat(48 + col * 11), y, 1.6, 1.6), with: .color(p.outlineOnly ? .clear : Color(egg: 0x9c7442)))
        }
    }
    for (x, y, r) in [(70, 80, 7), (128, 70, 5), (110, 124, 8), (60, 140, 5), (150, 136, 6)] {
        p.ctx.fill(p.ellipse(CGFloat(x), CGFloat(y), CGFloat(r), CGFloat(r) * 0.7), with: .color(p.outlineOnly ? .clear : Color(egg: 0xc08a45, 0.6)))
    }
}

func drawCandles(_ p: EggPainter, _ pose: EggPose) {
    let silver = Color(egg: 0xc7ccd9), silverShade = Color(egg: 0x9aa2b8)
    for (k, x) in [70.0, 130.0].enumerated() {
        let x = CGFloat(x)
        p.part(p.ellipse(x, 184, 24, 7), silver, width: 3)
        p.part("M\(x - 6) 184 L\(x + 6) 184 L\(x + 4) 128 L\(x - 4) 128 Z", silver, shade: silverShade, "M\(x) 120 L\(x + 10) 120 L\(x + 10) 190 L\(x) 190 Z")
        p.part("M\(x - 16) 122 C\(x - 16) 132 \(x + 16) 132 \(x + 16) 122 Z", silver, width: 3)
        p.part("M\(x - 7) 70 L\(x + 7) 70 L\(x + 7) 122 L\(x - 7) 122 Z", .white, shade: Color(egg: 0xe6e8f0), "M\(x) 60 L\(x + 10) 60 L\(x + 10) 130 L\(x) 130 Z")
        p.stroke("M\(x) 70 L\(x) 62", EggPainter.ink, width: 2)
        flame(p, x, 50, pose.t, Double(k))
    }
}

func drawChallah(_ p: EggPainter, _ pose: EggPose) {
    let crust = Color(egg: 0xd98a3a), crustShade = Color(egg: 0xb8691f)
    let lobes: [(CGFloat, CGFloat, CGFloat)] = [(44, 118, 20), (70, 104, 24), (98, 118, 26), (126, 104, 24), (152, 118, 20)]
    for (i, (x, y, r)) in lobes.enumerated() {
        p.part(p.ellipse(x, y, r * 1.1, r * 0.85), crust, shade: crustShade, p.ellipse(x, y + r * 0.7, r * 1.2, r * 0.4))
        p.glint("M\(x - r * 0.5) \(y - r * 0.45) C\(x - r * 0.2) \(y - r * 0.7) \(x + r * 0.2) \(y - r * 0.7) \(x + r * 0.4) \(y - r * 0.5)", width: 3)
        for j in 0..<3 {
            p.ctx.fill(p.ellipse(x - r * 0.3 + CGFloat(j) * r * 0.3, y - r * 0.15 + CGFloat((i + j) % 2) * 5, 1.6, 2.4),
                       with: .color(p.outlineOnly ? .clear : Color(egg: 0xfff1c9)))
        }
    }
}

func drawTorah(_ p: EggPainter, _ pose: EggPose) {
    // Hakafot: danced, tilting side to side.
    p.rotated(9 * sin(pose.t * 3.2), 100, 190) { p in
        let wood = Color(egg: 0x8a5a2b), parchment = Color(egg: 0xf6ead0), parchShade = Color(egg: 0xe0cfa6)
        for x in [58.0, 142.0] {
            let x = CGFloat(x)
            p.part("M\(x - 4) 18 L\(x + 4) 18 L\(x + 4) 188 L\(x - 4) 188 Z", wood, width: 3)
            p.part(p.ellipse(x, 44, 16, 6), wood, width: 3)
            p.part(p.ellipse(x, 162, 16, 6), wood, width: 3)
            p.part("M\(x - 16) 50 L\(x + 16) 50 L\(x + 16) 156 L\(x - 16) 156 Z", parchment, shade: parchShade, "M\(x + 4) 40 L\(x + 20) 40 L\(x + 20) 170 L\(x + 4) 170 Z")
            p.part(p.ellipse(x, 14, 8, 8), Color(egg: 0xc7ccd9), width: 2.5)       // rimon
        }
        p.part("M74 56 L126 56 L126 150 L74 150 Z", parchment, width: 3)
        for i in 0..<9 { p.stroke("M80 \(66 + i * 9) L120 \(66 + i * 9)", Color(egg: 0x6b5a3a), width: 1.5) }
    }
}

// MARK: - The festival seasons

/// When each Jewish-set object is in season, and what greets you then.
enum EggFestivals {
    struct Festival: Equatable {
        let id: String
        let greeting: String
        let objects: [String]
        let icon: String?          // the alternate app icon for its days
    }

    static let sukkot = Festival(id: "sukkot", greeting: "Chag Sameach!", objects: ["sukkah", "lulav", "etrog"], icon: "AppIconSukkot")
    static let roshHashanah = Festival(id: "rosh-hashanah", greeting: "Shana Tova!", objects: ["shofar", "applehoney"], icon: "AppIconRoshHashanah")
    static let chanukah = Festival(id: "chanukah", greeting: "Chanukah Sameach!", objects: ["menorah", "dreidel"], icon: "AppIconChanukah")
    static let purim = Festival(id: "purim", greeting: "Purim Sameach!", objects: ["mask", "grogger", "hamantasch"], icon: "AppIconPurim")
    static let pesach = Festival(id: "pesach", greeting: "Chag Kasher v'Sameach!", objects: ["matzah"], icon: "AppIconPesach")
    static let shavuot = Festival(id: "shavuot", greeting: "Chag Sameach!", objects: ["torah"], icon: nil)
    static let simchatTorah = Festival(id: "simchat-torah", greeting: "Chag Sameach!", objects: ["torah", "sukkah"], icon: "AppIconSukkot")
    static let shabbat = Festival(id: "shabbat", greeting: "Shabbat Shalom!", objects: ["candles", "challah"], icon: nil)

    static let all = [roshHashanah, sukkot, simchatTorah, chanukah, purim, pesach, shavuot, shabbat]

    /// The season each object belongs to.
    static func season(of object: String) -> [Festival] { all.filter { $0.objects.contains(object) } }

    /// What is on today (in the Hebrew calendar), most specific first.
    /// Windows start a few days early, so the lulav is in season while you
    /// buy it. Foundation's Hebrew calendar numbers Tishrei 1 … Elul 13, with
    /// month 6 (Adar I) only in a leap year.
    static func current(_ date: Date = Date()) -> [Festival] {
        var cal = Calendar(identifier: .hebrew)
        cal.timeZone = .current
        let c = cal.dateComponents([.year, .month, .day, .weekday], from: date)
        guard let m = c.month, let d = c.day, let y = c.year else { return [] }
        let leap = cal.range(of: .month, in: .year, for: date)?.count == 13
        let adar = leap ? 7 : 7                    // Adar (plain year) and Adar II (leap) are both month 7
        _ = y
        var out: [Festival] = []
        if (m == 13 && d >= 25) || (m == 1 && d <= 2) { out.append(roshHashanah) }
        if m == 1 && (22...23).contains(d) { out.append(simchatTorah) }
        if m == 1 && (11...23).contains(d) { out.append(sukkot) }
        if (m == 3 && d >= 22) || (m == 4 && d <= 3) { out.append(chanukah) }
        if m == adar && (10...15).contains(d) { out.append(purim) }
        if m == 8 && (12...22).contains(d) { out.append(pesach) }
        if m == 10 && (3...7).contains(d) { out.append(shavuot) }
        if c.weekday == 6 || c.weekday == 7 { out.append(shabbat) }
        return out
    }
}
