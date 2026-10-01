import SwiftUI

/// The built-in figures, each drawn in its 200-unit box facing right. See
/// `EggArt.swift` for the style; `EggCatalog` for which words show which.
enum EggFigure: String, CaseIterable, Codable {
    case dog, dragon, fairy, wolf, car, plane
    case unicorn, phoenix, griffin, wizard
    case cat, horse, lion, eagle, shark, owl
    case rocket, ufo, train, motorcycle, helicopter
    // The Jewish festivals set (EggJewish.swift).
    case lulav, etrog, sukkah, mask, grogger, hamantasch, menorah, dreidel, shofar, applehoney, matzah, candles, challah, torah
    // The activities set (EggActivities.swift), from what the calendar holds.
    case dumbbell, pullup, sneaker, cart, laptop, books, bicycle, clipboard, pot, passport, gift

    /// Cycles per second of the figure's own movement (gait, flap, rotor).
    var speed: Double {
        switch self {
        case .dog, .wolf, .cat: return 2.6
        case .horse, .unicorn, .lion: return 2.0
        case .dragon, .griffin, .phoenix, .eagle: return 1.4
        case .owl: return 1.8
        case .fairy: return 6
        case .helicopter: return 9
        case .car, .motorcycle, .train: return 3
        case .plane, .rocket, .ufo, .shark, .wizard: return 1.2
        case .lulav, .etrog, .sukkah, .mask, .grogger, .hamantasch, .menorah, .dreidel,
             .shofar, .applehoney, .matzah, .candles, .challah, .torah: return 1
        case .sneaker: return 2.4
        case .dumbbell, .pullup, .cart, .laptop, .books, .bicycle, .clipboard, .pot, .passport, .gift: return 1
        }
    }

    func draw(_ p: EggPainter, _ pose: EggPose) {
        switch self {
        case .dog: drawCanine(p, pose, .germanShepherd)
        case .wolf: drawCanine(p, pose, .wolf)
        case .cat: drawCat(p, pose)
        case .lion: drawLion(p, pose)
        case .horse: drawHorse(p, pose, unicorn: false)
        case .unicorn: drawHorse(p, pose, unicorn: true)
        case .dragon: drawDragon(p, pose)
        case .eagle: drawBird(p, pose, .eagle)
        case .phoenix: drawBird(p, pose, .phoenix)
        case .griffin: drawBird(p, pose, .griffin)
        case .owl: drawOwl(p, pose)
        case .fairy: drawFairy(p, pose)
        case .car: drawCar(p, pose)
        case .plane: drawPlane(p, pose)
        case .rocket: drawRocket(p, pose)
        case .ufo: drawUFO(p, pose)
        case .train: drawTrain(p, pose)
        case .motorcycle: drawMotorcycle(p, pose)
        case .helicopter: drawHelicopter(p, pose)
        case .wizard: drawWizard(p, pose)
        case .shark: drawShark(p, pose)
        case .lulav: drawLulav(p, pose)
        case .etrog: drawEtrog(p, pose)
        case .sukkah: drawSukkah(p, pose)
        case .mask: drawMask(p, pose)
        case .grogger: drawGrogger(p, pose)
        case .hamantasch: drawHamantasch(p, pose)
        case .menorah: drawMenorah(p, pose)
        case .dreidel: drawDreidel(p, pose)
        case .shofar: drawShofar(p, pose)
        case .applehoney: drawAppleHoney(p, pose)
        case .matzah: drawMatzah(p, pose)
        case .candles: drawCandles(p, pose)
        case .challah: drawChallah(p, pose)
        case .torah: drawTorah(p, pose)
        case .dumbbell: drawDumbbell(p, pose)
        case .pullup: drawPullup(p, pose)
        case .sneaker: drawSneaker(p, pose)
        case .cart: drawCart(p, pose)
        case .laptop: drawLaptop(p, pose)
        case .books: drawBooks(p, pose)
        case .bicycle: drawBicycle(p, pose)
        case .clipboard: drawClipboard(p, pose)
        case .pot: drawPot(p, pose)
        case .passport: drawPassport(p, pose)
        case .gift: drawGift(p, pose)
        }
    }
}

// MARK: - Canines: the German Shepherd, and the wolf on the same frame

private struct CanineStyle {
    var base, baseShade, back, backShade, mask, earInner, iris: Color
    var tongue: Bool
    var chest: Color?          // a light ruff / belly
    var tailTip: Color?

    static let germanShepherd = CanineStyle(
        base: Color(egg: 0xd99a55), baseShade: Color(egg: 0xb3702f),
        back: Color(egg: 0x2c2436), backShade: Color(egg: 0x1b1622),
        mask: Color(egg: 0x2c2436), earInner: Color(egg: 0xf2b39a), iris: Color(egg: 0x8a4f1c),
        tongue: true, chest: nil, tailTip: nil)

    static let wolf = CanineStyle(
        base: Color(egg: 0xa7b0c2), baseShade: Color(egg: 0x7d879b),
        back: Color(egg: 0x5b6378), backShade: Color(egg: 0x444b5d),
        mask: Color(egg: 0xe6e9f0), earInner: Color(egg: 0xd9c6d4), iris: Color(egg: 0x49b6ff),
        tongue: false, chest: Color(egg: 0xeef0f5), tailTip: Color(egg: 0x3f4556))
}

private func drawCanine(_ p: EggPainter, _ pose: EggPose, _ st: CanineStyle) {
    let s = pose.swing, s2 = pose.swing2
    let hind = "M50 104 C66 100 78 110 74 128 L67 150 L71 168 C73 172 76 174 76 177 L54 177 C54 172 55 168 54 162 L55 150 C46 136 42 118 50 104 Z"
    let fore = "M117 104 C123 99 140 99 143 108 L140 148 C140 158 141 165 145 168 C152 170 154 177 148 178 L128 178 C125 172 128 166 127 158 L124 134 C119 125 116 113 117 104 Z"
    let torso = "M45 92 C60 78 110 73 133 80 C151 87 153 118 139 130 C115 135 85 129 62 127 C44 125 36 108 45 92 Z"

    // Far legs first, a shade darker so the near pair reads in front.
    p.rotated(-26 * s2, 60, 110) { $0.part(hind, st.baseShade) }
    p.rotated(28 * s2, 130, 112) { $0.part(fore, st.baseShade) }

    // Bushy tail, wagging from the rump.
    p.rotated(9 * s, 46, 96) {
        $0.part("M48 92 C30 94 14 108 7 132 C5 142 13 147 20 141 C27 128 37 114 52 106 Z",
                st.base, shade: st.back, "M0 80 L60 80 L60 100 C40 104 26 118 16 142 L0 142 Z")
        if let tip = st.tailTip {
            $0.ctx.drawLayer { l in
                l.clip(to: EggPath("M48 92 C30 94 14 108 7 132 C5 142 13 147 20 141 C27 128 37 114 52 106 Z"))
                l.fill(EggPath("M0 126 L30 126 L30 150 L0 150 Z"), with: .color(tip))
            }
            $0.part("M48 92 C30 94 14 108 7 132 C5 142 13 147 20 141 C27 128 37 114 52 106 Z", .clear)
        }
        $0.stroke("M16 128 L10 133 M22 118 L15 121", st.backShade, width: 2.5)
    }

    // Torso: the dark back across the top and a cel shade under the belly.
    p.part(torso, st.base, shade: st.back, "M30 60 L140 60 L140 90 C118 86 84 92 52 106 L30 106 Z")
    p.ctx.drawLayer { l in
        l.clip(to: EggPath(torso))
        l.fill(EggPath("M40 120 C80 124 120 128 150 118 L150 140 L40 140 Z"),
               with: .color(st.chest ?? st.baseShade))
    }
    p.part(torso, .clear)
    p.glint("M70 84 C84 80 100 79 112 80", width: 3)

    // Near legs.
    p.rotated(-26 * s, 60, 110) { $0.part(hind, st.base, shade: st.baseShade, "M40 140 L80 140 L80 180 L40 180 Z") }
    p.rotated(28 * s, 130, 112) { $0.part(fore, st.base, shade: st.baseShade, "M120 150 L152 150 L152 180 L120 180 Z") }

    // Neck, then the head — a size up, chibi-style.
    p.part("M122 86 C127 70 140 57 153 59 L162 84 C152 97 137 101 128 99 Z",
           st.base, shade: st.back, "M118 50 L160 50 L150 66 C140 70 130 80 124 90 L118 90 Z")
    if let chest = st.chest {
        p.part("M126 98 C132 104 142 106 150 98 L144 112 C138 116 130 112 126 98 Z", chest, width: 2.5)
    }
    p.stroke("M132 94 L128 99 M140 92 L137 98", st.baseShade, width: 2.5)
    p.scaled(1.16, 1.16, 150, 84) { p in
        p.part("M147 50 L150 20 L163 45 Z", st.back)
        p.part("M140 58 C144 42 168 37 176 49 C182 55 190 59 194 67 C197 74 191 80 182 81 C172 83 160 83 150 85 C140 81 136 68 140 58 Z",
               st.base, shade: st.mask, "M174 44 L200 44 L200 92 L170 92 C176 80 178 62 174 44 Z")
        p.part("M158 47 L170 15 L178 48 Z", st.back)
        p.fill("M163 44 L169 26 L173 45 Z", st.earInner)
        if st.tongue { p.part("M173 81 C174 92 184 95 186 84 Z", Color(egg: 0xff6f8e), width: 3) }
        p.ctx.fill(p.ellipse(194, 67, 5, 4), with: .color(EggPainter.ink))
        p.glint("M192 65 L195 64", width: 2)
        p.stroke("M186 79 Q178 83 168 80", width: 3)
        p.eye(163, 61, 7.5, iris: st.iris, blink: pose.cycle > 0.93)
        p.stroke("M155 51 Q162 47 171 50", width: 3)
    }
}

// MARK: - Cat: an orange tabby, tail up, big 3/4 face

private func drawCat(_ p: EggPainter, _ pose: EggPose) {
    let base = Color(egg: 0xf5a44a), shade = Color(egg: 0xd97e25), stripe = Color(egg: 0xbf5f16)
    let cream = Color(egg: 0xfde3c0), pink = Color(egg: 0xffa9bd)
    let s = pose.swing, s2 = pose.swing2
    let fore = "M121 124 L137 124 L137 160 C142 164 147 170 143 177 L124 177 C122 170 124 164 123 156 Z"
    let hind = "M62 120 C76 114 90 124 88 140 L80 158 C85 164 89 170 86 177 L66 177 C65 170 68 164 67 156 C58 146 54 130 62 120 Z"

    p.rotated(24 * s2, 129, 126) { $0.part(fore, shade) }
    p.rotated(-24 * s2, 72, 126) { $0.part(hind, shade) }
    p.rotated(10 * s, 62, 114) {
        $0.part("M64 114 C44 106 32 82 38 56 C40 46 52 46 52 56 C49 78 56 96 72 106 Z", base)
        $0.stroke("M38 70 L50 72 M40 86 L53 86 M46 99 L58 97", stripe, width: 3.5)
    }
    let torso = "M58 110 C68 96 118 93 134 103 C147 111 145 134 131 140 C110 146 84 144 68 140 C53 136 49 120 58 110 Z"
    p.part(torso, base, shade: cream, "M50 130 C80 134 120 136 150 128 L150 150 L50 150 Z")
    p.stroke("M86 99 L90 112 M100 97 L103 111 M114 99 L115 112", stripe, width: 3.5)
    p.glint("M74 104 C84 100 96 99 106 99", width: 3)
    p.rotated(24 * s, 129, 126) { $0.part(fore, base, shade: cream, "M118 164 L150 164 L150 180 L118 180 Z") }
    p.rotated(-24 * s, 72, 126) { $0.part(hind, base, shade: cream, "M60 164 L92 164 L92 180 L60 180 Z") }

    // Head: round, ears up, a three-quarter face so both eyes show.
    p.part("M128 70 L128 38 L152 58 Z", base)
    p.fill("M133 60 L133 46 L144 57 Z", pink)
    p.part("M121 90 C119 64 141 54 157 55 C178 56 191 71 189 92 C187 111 170 119 153 119 C135 119 123 107 121 90 Z",
           base, shade: shade, "M110 104 C140 118 170 118 200 100 L200 130 L110 130 Z")
    p.part("M162 57 L183 36 L186 68 Z", base)
    p.fill("M168 58 L180 46 L181 62 Z", pink)
    p.stroke("M150 57 L152 67 M160 56 L160 66 M141 60 L145 68", stripe, width: 3.5)
    p.part("M146 100 C150 94 176 94 180 100 C180 110 170 114 163 114 C155 114 146 110 146 100 Z", cream, outline: false)
    p.eye(148, 87, 7.5, iris: Color(egg: 0x3fc27a), blink: pose.cycle > 0.94)
    p.eye(174, 87, 7.5, iris: Color(egg: 0x3fc27a), blink: pose.cycle > 0.94)
    p.fill("M160 98 L166 98 L163 102 Z", Color(egg: 0xff7f9f))
    p.stroke("M157 104 Q160 108 163 104 Q166 108 169 104", width: 2.5)
    p.stroke("M140 100 L124 97 M140 105 L125 107 M186 100 L199 96 M186 105 L199 107", width: 2)
    p.blush(140, 97, 6); p.blush(184, 97, 6)
}

// MARK: - Lion: golden, a big spiky mane, a tufted tail

private func drawLion(_ p: EggPainter, _ pose: EggPose) {
    let body = Color(egg: 0xe9b050), shade = Color(egg: 0xc98d2e)
    let mane = Color(egg: 0xb5561d), maneShade = Color(egg: 0x8e3f12), muzzle = Color(egg: 0xf8dca0)
    let s = pose.swing, s2 = pose.swing2
    let hind = "M48 100 C66 96 80 108 76 128 L69 150 L72 170 C74 173 78 175 78 178 L54 178 C54 172 56 168 55 160 L56 148 C44 134 40 114 48 100 Z"
    let fore = "M118 104 C124 98 142 98 146 108 L143 148 C143 160 144 166 148 168 C155 171 156 178 150 179 L128 179 C125 173 128 166 127 158 L124 134 C119 125 116 113 118 104 Z"

    p.rotated(-24 * s2, 60, 108) { $0.part(hind, shade) }
    p.rotated(26 * s2, 132, 110) { $0.part(fore, shade) }
    // Tail with its dark tuft.
    p.rotated(12 * s, 44, 100) {
        $0.stroke("M44 100 C28 100 18 112 16 128", EggPainter.ink, width: 9)
        $0.stroke("M44 100 C28 100 18 112 16 128", body, width: 5)
        $0.part($0.ellipse(15, 134, 8, 10), maneShade)
    }
    let torso = "M40 96 C56 80 118 78 138 88 C152 96 152 124 138 132 C112 138 82 134 60 132 C42 128 32 110 40 96 Z"
    p.part(torso, body, shade: shade, "M30 122 C70 128 120 132 160 120 L160 150 L30 150 Z")
    p.glint("M62 88 C80 83 100 82 116 84", width: 3)
    p.rotated(-24 * s, 60, 108) { $0.part(hind, body, shade: shade, "M40 150 L84 150 L84 182 L40 182 Z") }
    p.rotated(26 * s, 132, 110) { $0.part(fore, body, shade: shade, "M120 152 L158 152 L158 182 L120 182 Z") }

    // The mane: a ring of flame-like points round the head, then the face.
    var ring = Path()
    let cx: CGFloat = 154, cy: CGFloat = 80, n = 14
    for i in 0...n {
        let a0 = Double(i) / Double(n) * 2 * .pi, a1 = (Double(i) + 0.5) / Double(n) * 2 * .pi
        let outer = CGPoint(x: cx + 46 * cos(a1), y: cy + 44 * sin(a1))
        let inner = CGPoint(x: cx + 32 * cos(a0), y: cy + 30 * sin(a0))
        if i == 0 { ring.move(to: inner) } else { ring.addQuadCurve(to: inner, control: outer) }
    }
    ring.closeSubpath()
    p.part(ring, mane, shade: maneShade, EggPath("M100 90 C130 120 170 124 210 96 L210 140 L100 140 Z"))
    p.part(p.ellipse(158, 82, 26, 25), body, shade: shade, p.ellipse(158, 108, 30, 10))
    p.part("M150 58 C146 50 136 50 136 60 C136 66 142 68 146 66 Z", body)
    p.part("M146 88 C150 80 176 80 182 88 C184 100 172 106 164 106 C154 106 144 100 146 88 Z", muzzle, width: 3)
    p.fill("M158 86 L170 86 L164 93 Z", Color(egg: 0x5a2d16))
    p.stroke("M164 93 L164 98 M156 99 Q164 104 172 99", width: 2.5)
    p.eye(150, 76, 6.5, iris: Color(egg: 0xd9861a), blink: pose.cycle > 0.94)
    p.eye(172, 76, 6.5, iris: Color(egg: 0xd9861a), blink: pose.cycle > 0.94)
    p.stroke("M143 67 L156 70 M166 70 L179 67", width: 3)
}

// MARK: - Horse, and the unicorn on the same frame

private func drawHorse(_ p: EggPainter, _ pose: EggPose, unicorn: Bool) {
    let body = unicorn ? Color(egg: 0xfbfbff) : Color(egg: 0x9b5b34)
    let shade = unicorn ? Color(egg: 0xd6dbf2) : Color(egg: 0x7a4424)
    let hoof = unicorn ? Color(egg: 0xf2c75a) : Color(egg: 0x2b2020)
    let muzzle = unicorn ? Color(egg: 0xffd9e6) : Color(egg: 0xb87a4e)
    let hair = unicorn ? [0xff7eb6, 0xffd166, 0x6fe3ff, 0xb28dff].map { Color(egg: $0) }
                       : [Color(egg: 0x3a2418)]
    let s = pose.swing, s2 = pose.swing2
    let fore = "M122 108 C128 104 140 106 141 114 L138 148 L141 166 L128 166 L127 148 L124 128 Z"
    let hind = "M48 98 C64 96 76 106 72 124 L66 146 L69 166 L56 166 L56 146 C46 132 42 112 48 98 Z"
    func leg(_ d: String, _ c: Color, hoofAt x: CGFloat, _ p: EggPainter) {
        p.part(d, c)
        p.part("M\(x - 7) 165 L\(x + 7) 165 L\(x + 9) 176 L\(x - 9) 176 Z", hoof, width: 3)
    }

    p.rotated(-30 * s2, 58, 106) { leg(hind, shade, hoofAt: 62, $0) }
    p.rotated(32 * s2, 130, 110) { leg(fore, shade, hoofAt: 134, $0) }
    // Flowing tail.
    p.rotated(8 * s, 42, 92) { p in
        for (i, c) in hair.enumerated().reversed() {
            let o = CGFloat(i) * 7
            p.part("M44 90 C26 \(92 + o) 12 \(110 + o) 8 \(134 + o) C18 \(124 + o) 22 \(118 + o) 30 \(112 + o) C24 \(126 + o) 22 \(138 + o) 26 \(150 + o) C34 \(130 + o) 40 \(112 + o) 50 100 Z", c, width: 3)
        }
    }
    let torso = "M40 92 C56 76 120 74 140 84 C154 92 152 118 138 124 C112 130 80 126 58 124 C40 120 32 104 40 92 Z"
    p.part(torso, body, shade: shade, "M30 114 C70 122 120 124 160 112 L160 140 L30 140 Z")
    p.glint("M60 84 C80 79 100 78 118 80", width: 3)
    p.rotated(-30 * s, 58, 106) { leg(hind, body, hoofAt: 62, $0) }
    p.rotated(32 * s, 130, 110) { leg(fore, body, hoofAt: 134, $0) }

    // Neck and head, then the mane down the neck.
    p.part("M118 92 C122 70 136 46 150 36 L170 50 C160 64 150 84 144 102 Z", body, shade: shade, "M140 60 L180 60 L180 110 L140 110 Z")
    p.part("M146 40 C152 27 172 27 180 37 C188 47 197 57 197 68 C197 77 188 81 180 79 C172 77 166 71 160 65 C152 59 144 51 146 40 Z",
           body, shade: muzzle, "M178 56 L204 56 L204 90 L170 90 Z")
    p.part("M152 34 L154 14 L166 30 Z", body)
    p.ctx.fill(p.ellipse(190, 68, 2.5, 2), with: .color(EggPainter.ink))
    p.stroke("M196 73 Q190 77 184 75", width: 2.5)
    for (i, c) in hair.enumerated().reversed() {
        let o = CGFloat(i) * 6
        p.part("M\(150 - o) 30 C\(136 - o) 40 \(126 - o) 58 \(116 - o) 88 C\(128 - o) 78 \(132 - o) 64 \(142 - o) 54 C\(140 - o) 64 \(136 - o) 74 \(128 - o) 88 C\(144 - o) 74 \(148 - o) 56 \(156 - o) 42 Z", c, width: 3)
    }
    if unicorn {
        p.part("M160 30 L172 2 L170 32 Z", Color(egg: 0xffd76a), width: 3)
        p.stroke("M163 24 L170 22 M165 16 L170 14", Color(egg: 0xd49a1e), width: 2)
    }
    p.eye(166, 46, 6.5, iris: unicorn ? Color(egg: 0xb35cff) : Color(egg: 0x5a3317), blink: pose.cycle > 0.94)
    if unicorn { p.blush(176, 56, 5) }
}

// MARK: - Dragon: green, bat wings, horns, a spiked back and an arrow tail

private func drawDragon(_ p: EggPainter, _ pose: EggPose) {
    let body = Color(egg: 0x3fae7a), shade = Color(egg: 0x2b7f59), belly = Color(egg: 0xf2d68a)
    let wing = Color(egg: 0x86dcb0), wingShade = Color(egg: 0x52b889), horn = Color(egg: 0xfff1c9)
    let flap = 38 * pose.swing
    let wingD = "M112 96 C104 68 90 38 68 16 C72 32 66 42 56 42 C60 55 52 63 40 60 C50 74 68 86 96 100 Z"
    func wingPart(_ p: EggPainter, _ c: Color, _ sh: Color) {
        p.part(wingD, c, shade: sh, "M40 60 C60 74 80 86 100 100 L40 110 Z")
        p.stroke("M110 94 L70 20 M108 96 L58 44 M104 98 L44 62", Color(egg: 0x2b7f59), width: 3)
    }
    // Far wing, a step back and darker.
    p.rotated(flap - 12, 118, 96) { wingPart($0, wingShade, shade) }
    // Tail, waving.
    p.rotated(8 * pose.swing2, 38, 112) {
        $0.part("M38 106 C22 98 12 108 4 96 C2 110 12 122 40 120 Z", body, shade: shade, "M0 112 L40 112 L40 130 L0 130 Z")
        $0.part("M6 98 L-10 88 L-6 104 L6 108 Z", shade, width: 3)
    }
    // Back spikes, then the body with its belly plates.
    for i in 0..<5 {
        let x = CGFloat(56 + i * 18)
        p.part("M\(x) 102 L\(x + 7) 86 L\(x + 14) 100 Z", horn, width: 3)
    }
    let torso = "M30 110 C50 96 90 91 120 95 C140 97 151 108 147 122 C140 134 110 136 90 132 C70 128 50 124 30 110 Z"
    p.part(torso, body, shade: belly, "M20 120 C60 128 110 134 160 118 L160 150 L20 150 Z")
    p.stroke("M70 126 L72 131 M88 128 L89 133 M106 128 L106 134 M124 126 L123 132", Color(egg: 0xd4b061), width: 2.5)
    p.glint("M60 104 C76 99 94 98 108 99", width: 3)
    // Tucked legs.
    p.part("M126 122 C132 132 136 140 132 146 L123 144 C125 137 121 131 118 126 Z", body, width: 3.5)
    p.part("M58 120 C60 132 56 140 48 146 L43 140 C49 134 49 128 47 121 Z", body, width: 3.5)
    // Neck and head, horns back, a gold eye.
    p.part("M130 100 C140 86 150 74 162 70 L172 84 C162 92 152 104 146 116 Z", body, shade: belly, "M150 96 L180 96 L180 120 L140 120 Z")
    p.part("M162 58 L150 36 L170 54 Z", horn, width: 3)
    p.part("M156 66 C160 53 181 51 189 60 C197 64 201 70 199 78 C197 85 186 87 176 85 C166 85 158 80 156 66 Z",
           body, shade: shade, "M150 80 C170 86 190 86 205 80 L205 95 L150 95 Z")
    p.part("M173 56 L168 34 L183 53 Z", horn, width: 3)
    p.ctx.fill(p.ellipse(194, 70, 2.2, 1.8), with: .color(EggPainter.ink))
    p.stroke("M198 80 Q190 83 182 81", width: 2.5)
    p.eye(174, 67, 6.5, iris: Color(egg: 0xffc21a), blink: pose.cycle > 0.95)
    // Near wing, over everything but the head.
    p.rotated(flap, 112, 96) { wingPart($0, wing, wingShade) }
}

// MARK: - Birds: the eagle, the phoenix and the griffin share one frame

private struct BirdStyle {
    var body, shade, head, beak, wing, wingShade, iris: Color
    var wingTip: Color?
    var fire: Bool           // phoenix: flame crest and streaming flame tail
    var lionBack: Bool       // griffin: lion hindquarters and a tufted tail

    static let eagle = BirdStyle(
        body: Color(egg: 0x6b4226), shade: Color(egg: 0x4e2e18), head: Color(egg: 0xf6f4ee),
        beak: Color(egg: 0xffc53d), wing: Color(egg: 0x7a4c2c), wingShade: Color(egg: 0x55341d),
        iris: Color(egg: 0xe0a21a), wingTip: nil, fire: false, lionBack: false)
    static let phoenix = BirdStyle(
        body: Color(egg: 0xff7a2f), shade: Color(egg: 0xe0431f), head: Color(egg: 0xffb13b),
        beak: Color(egg: 0xfff0a0), wing: Color(egg: 0xffa53a), wingShade: Color(egg: 0xff5a24),
        iris: Color(egg: 0xff2d55), wingTip: Color(egg: 0xffe066), fire: true, lionBack: false)
    static let griffin = BirdStyle(
        body: Color(egg: 0xd9a55a), shade: Color(egg: 0xb07b35), head: Color(egg: 0xf6f4ee),
        beak: Color(egg: 0xffc53d), wing: Color(egg: 0xc98f45), wingShade: Color(egg: 0x9a6428),
        iris: Color(egg: 0x2c8cff), wingTip: Color(egg: 0xf6f4ee), fire: false, lionBack: true)
}

private func drawBird(_ p: EggPainter, _ pose: EggPose, _ st: BirdStyle) {
    let flap = 40 * pose.swing
    let wingD = "M104 94 C96 70 80 44 50 28 L56 42 L40 44 L52 56 L36 60 L50 70 L40 78 C60 88 80 96 96 104 Z"
    func wingPart(_ p: EggPainter, _ c: Color, _ sh: Color) {
        p.part(wingD, c, shade: st.wingTip ?? sh, "M30 20 L66 20 L66 90 L30 90 Z")
        p.stroke("M92 96 L60 50 M88 99 L52 62 M84 101 L48 74", sh, width: 2.5)
    }
    p.rotated(flap - 10, 110, 94) { wingPart($0, st.wingShade, st.shade) }

    // Tail: a white fan, streaming flames, or a lion's tuft.
    if st.fire {
        for (i, c) in [0xffe066, 0xff9a2f, 0xff4a2a].enumerated() {
            let o = CGFloat(i) * 10, k = 1 + 0.12 * pose.swing * (i.isMultiple(of: 2) ? 1 : -1)
            p.scaled(k, 1, 56, 106) {
                $0.part("M56 102 C36 \(92 + o) 16 \(84 + o) -8 \(96 + o) C12 \(100 + o) 20 \(108 + o) 26 \(112 + o) C16 \(114 + o) 6 \(122 + o) -4 \(130 + o) C24 \(130 + o) 42 \(120 + o) 58 114 Z", Color(egg: UInt32(c)), width: 3)
            }
        }
    } else if st.lionBack {
        p.rotated(10 * pose.swing2, 40, 106) {
            $0.stroke("M42 106 C26 108 14 120 12 136", EggPainter.ink, width: 9)
            $0.stroke("M42 106 C26 108 14 120 12 136", st.body, width: 5)
            $0.part($0.ellipse(11, 142, 7, 9), st.shade)
        }
    } else {
        p.part("M52 102 L16 90 L12 106 L18 122 L54 116 Z", st.head, shade: Color(egg: 0xd9d6cc), "M0 110 L60 110 L60 130 L0 130 Z")
        p.stroke("M20 100 L44 106 M18 112 L44 112", Color(egg: 0xc9c4b8), width: 2)
    }

    let torso = st.lionBack
        ? "M36 104 C50 88 118 82 140 92 C150 100 146 118 132 122 C110 128 70 128 50 122 C36 118 30 112 36 104 Z"
        : "M50 100 C70 84 120 82 140 92 C150 100 146 118 132 122 C110 128 76 126 56 118 C44 114 40 106 50 100 Z"
    p.part(torso, st.body, shade: st.shade, "M30 116 C70 124 120 126 160 114 L160 140 L30 140 Z")
    p.glint("M66 94 C82 89 100 88 116 89", width: 3)
    if st.lionBack {
        p.rotated(-20 * pose.swing, 56, 118) {
            $0.part("M46 112 C60 110 68 120 64 134 L58 150 L64 160 L46 160 L48 148 C42 136 40 122 46 112 Z", st.body, width: 3.5)
        }
    }
    // Talons tucked under the chest.
    p.part("M118 122 L122 134 L116 138 M124 122 L130 134 L124 138", .clear, width: 3)
    p.stroke("M116 122 L119 134 M124 122 L128 134", st.beak, width: 4)

    // Head: white (or flame), a hooked beak, a fierce anime eye.
    p.part("M132 90 C136 72 158 65 171 73 C180 79 180 94 169 101 C158 107 141 104 132 96 Z", st.head,
           shade: st.fire ? st.shade : Color(egg: 0xdcd8cc), "M130 98 C150 104 170 102 185 94 L185 115 L130 115 Z")
    if st.fire {
        let flick = 1 + 0.15 * pose.swing
        p.scaled(1, flick, 150, 72) {
            $0.part("M140 76 C132 58 142 46 138 34 C150 42 152 54 150 62 C154 52 162 46 162 36 C170 50 166 62 160 72 Z",
                    Color(egg: 0xffd23a), shade: Color(egg: 0xff7a2f), "M130 60 L170 60 L170 80 L130 80 Z", width: 3)
        }
    }
    p.part("M166 79 C178 77 191 83 191 94 C187 90 179 90 172 94 Z", st.beak, width: 3)
    p.eye(158, 82, 5.5, iris: st.iris, blink: pose.cycle > 0.95)
    p.stroke("M150 74 L166 77", width: 3.5)

    p.rotated(flap, 104, 94) { wingPart($0, st.wing, st.wingShade) }
}

// MARK: - Owl: round and front-on, huge eyes, both wings beating

private func drawOwl(_ p: EggPainter, _ pose: EggPose) {
    let body = Color(egg: 0x9a6a45), shade = Color(egg: 0x76492b), belly = Color(egg: 0xf1dcc0)
    let face = Color(egg: 0xe9c9a0)
    let flap = 34 * pose.swing
    let wingL = "M70 92 C50 84 26 92 12 112 C28 110 26 124 40 122 C38 132 50 136 60 128 C66 118 70 106 70 92 Z"
    p.rotated(-flap, 70, 96) { $0.part(wingL, body, shade: shade, "M0 116 L70 116 L70 140 L0 140 Z") }
    p.scaled(-1, 1, 100, 100) { q in q.rotated(-flap, 70, 96) { $0.part(wingL, body, shade: shade, "M0 116 L70 116 L70 140 L0 140 Z") } }
    p.part("M100 44 C136 44 146 80 144 110 C142 142 124 160 100 160 C76 160 58 142 56 110 C54 80 64 44 100 44 Z",
           body, shade: shade, "M40 140 L160 140 L160 170 L40 170 Z")
    p.part("M100 96 C122 96 130 114 128 132 C126 148 114 154 100 154 C86 154 74 148 72 132 C70 114 78 96 100 96 Z", belly, width: 3)
    p.stroke("M88 116 L92 120 L96 116 M104 116 L108 120 M112 116 L116 120 M92 132 L96 136 L100 132 M104 132 L108 136 L112 132", shade, width: 2.5)
    // Ear tufts and the face disc.
    p.part("M66 54 L60 30 L82 48 Z", body); p.part("M134 54 L140 30 L118 48 Z", body)
    p.part("M100 58 C88 50 64 54 64 76 C64 96 84 100 100 92 C116 100 136 96 136 76 C136 54 112 50 100 58 Z", face, width: 3)
    p.eye(84, 76, 11, iris: Color(egg: 0xffb21a), blink: pose.cycle > 0.94)
    p.eye(116, 76, 11, iris: Color(egg: 0xffb21a), blink: pose.cycle > 0.94)
    p.part("M94 90 L106 90 L100 102 Z", Color(egg: 0xffc53d), width: 3)
    p.part("M86 158 L84 168 M92 158 L92 168 M108 158 L108 168 M114 158 L116 168", .clear, width: 3)
    p.stroke("M86 158 L84 168 M92 158 L92 168 M108 158 L108 168 M114 158 L116 168", Color(egg: 0xffc53d), width: 4)
}

// MARK: - Fairy: pink hair, a teal dress, a star wand and fluttering wings

private func drawFairy(_ p: EggPainter, _ pose: EggPose) {
    let skin = Color(egg: 0xffe0cc), skinShade = Color(egg: 0xf5bfa3)
    let hair = Color(egg: 0xff7eb6), hairShade = Color(egg: 0xe0529a)
    let dress = Color(egg: 0x3fd0c9), dressShade = Color(egg: 0x22a8a4)
    let flutter = 0.55 + 0.45 * abs(pose.swing)
    // Wings: two translucent pairs behind the back, fluttering fast.
    for (d, c) in [("M96 92 C80 50 50 40 40 62 C34 80 60 92 94 98 Z", 0x9ff3ff),
                   ("M96 96 C72 90 42 98 40 118 C42 134 72 122 96 102 Z", 0xc7a8ff)] {
        p.scaled(flutter, 1, 96, 96) { $0.part(d, Color(egg: UInt32(c), 0.7), width: 3) }
        p.scaled(flutter, 1, 96, 96) { $0.glint(d == "M96 96 C72 90 42 98 40 118 C42 134 72 122 96 102 Z" ? "M50 116 C60 108 72 104 84 102" : "M50 62 C58 56 70 60 80 72", width: 2.5) }
    }
    // Legs trailing, the dress flaring behind.
    p.part("M84 124 C70 132 54 136 40 134 L40 142 C56 146 74 142 90 132 Z", skin, width: 3)
    p.part("M86 116 C72 118 60 124 50 124 L50 131 C64 132 78 128 92 122 Z", skin, width: 3)
    p.part("M118 94 C108 92 96 96 86 106 C74 116 62 128 56 136 C72 136 92 130 104 124 C112 120 120 112 122 102 Z",
           dress, shade: dressShade, "M40 124 L130 110 L130 150 L40 150 Z")
    p.part("M104 96 C112 94 120 96 124 102 L118 112 C112 108 106 104 104 96 Z", dress, width: 3)
    // Arm forward with the wand.
    p.stroke("M122 104 C134 104 146 100 156 94", EggPainter.ink, width: 9)
    p.stroke("M122 104 C134 104 146 100 156 94", skin, width: 5)
    p.stroke("M156 94 L176 76", EggPainter.ink, width: 5)
    p.stroke("M156 94 L176 76", Color(egg: 0xfff1c9), width: 2.5)
    let tw = 1 + 0.15 * pose.swing
    p.scaled(tw, tw, 180, 72) {
        $0.part("M180 60 L184 68 L193 69 L186 75 L188 84 L180 79 L172 84 L174 75 L167 69 L176 68 Z", Color(egg: 0xffd84a), width: 3)
    }
    // Head: bun, bangs, big eyes, blush.
    p.part(p.ellipse(126, 44, 12, 11), hair)
    p.part(p.ellipse(130, 68, 26, 25), skin, shade: skinShade, p.ellipse(130, 96, 30, 8))
    p.part("M104 68 C102 46 118 38 132 40 C148 42 158 54 156 68 C150 58 144 56 138 60 C132 54 124 54 118 60 C112 58 106 62 104 68 Z",
           hair, shade: hairShade, "M100 60 L160 60 L160 70 L100 70 Z")
    p.part("M106 64 C100 76 102 88 110 94 C108 84 108 74 112 66 Z", hair, width: 3)
    p.eye(126, 72, 6.5, iris: Color(egg: 0x3a8bff), blink: pose.cycle > 0.9)
    p.eye(146, 72, 6.5, iris: Color(egg: 0x3a8bff), blink: pose.cycle > 0.9)
    p.stroke("M131 84 Q136 88 141 84", width: 2.5)
    p.blush(120, 82, 5); p.blush(152, 82, 5)
}

// MARK: - Vehicles

/// A wheel with a hubcap and spokes turning at `turn` (0…1 of a revolution).
private func wheel(_ p: EggPainter, _ cx: CGFloat, _ cy: CGFloat, _ r: CGFloat, turn: Double,
                   hub: Color = Color(egg: 0xd8dde8)) {
    p.part(p.ellipse(cx, cy, r, r), Color(egg: 0x2b2733))
    p.part(p.ellipse(cx, cy, r * 0.55, r * 0.55), hub, width: 3)
    p.rotated(turn * 360, cx, cy) { q in
        q.stroke("M\(cx - r * 0.5) \(cy) L\(cx + r * 0.5) \(cy) M\(cx) \(cy - r * 0.5) L\(cx) \(cy + r * 0.5)",
                 Color(egg: 0x8a91a3), width: 2.5)
    }
}

private func drawCar(_ p: EggPainter, _ pose: EggPose) {
    let red = Color(egg: 0xff4d5e), redShade = Color(egg: 0xd12f45), glass = Color(egg: 0x9fe3ff)
    let bounce = CGFloat(1.5 * pose.swing)
    p.scaled(1, 1, 100, 100) { _ in }
    var c = p.ctx; c.translateBy(x: 0, y: bounce)
    let q = EggPainter(ctx: c, line: p.line, outlineOnly: p.outlineOnly)
    q.part("M22 142 C20 124 30 116 48 114 L70 112 C80 94 96 84 120 84 C140 84 152 96 162 112 L180 116 C192 120 196 130 194 144 C194 150 188 154 180 154 L30 154 C24 154 22 150 22 142 Z",
           red, shade: redShade, "M10 140 L200 140 L200 160 L10 160 Z")
    q.part("M78 112 C86 98 98 92 116 92 L118 112 Z", glass, width: 3)
    q.part("M126 112 L124 92 C138 92 148 100 154 112 Z", glass, width: 3)
    q.glint("M88 106 L96 98 M132 104 L138 98", width: 3)
    q.glint("M40 124 C70 120 120 120 170 124", width: 3)
    q.part("M184 124 C190 124 192 130 190 134 L180 134 Z", Color(egg: 0xfff3a0), width: 3)
    q.part("M22 130 L30 130 L30 138 L22 138 Z", Color(egg: 0xffb13b), width: 3)
    wheel(p, 58, 156, 17, turn: pose.cycle)
    wheel(p, 158, 156, 17, turn: pose.cycle)
}

private func drawPlane(_ p: EggPainter, _ pose: EggPose) {
    let white = Color(egg: 0xf7f9ff), shade = Color(egg: 0xcbd4ea), blue = Color(egg: 0x3a7bff), red = Color(egg: 0xff4d5e)
    let bank = 3 * pose.swing
    p.rotated(bank, 100, 100) { p in
        p.part("M60 100 L40 60 L56 58 L84 96 Z", blue, width: 3.5)                 // tail fin
        p.part("M104 104 L70 150 L88 152 L128 108 Z", shade, width: 3.5)           // far wing
        p.part("M30 104 C30 94 44 88 60 88 L150 86 C172 86 186 94 188 104 C186 114 172 120 150 120 L60 120 C44 120 30 114 30 104 Z",
               white, shade: shade, "M20 110 L200 110 L200 130 L20 130 Z")
        p.stroke("M40 104 L176 104", red, width: 5)
        for i in 0..<5 { p.part(p.ellipse(CGFloat(90 + i * 14), 96, 3.5, 4), glass(), width: 2) }
        p.part("M160 92 C168 90 176 94 180 100 L162 100 Z", Color(egg: 0x9fe3ff), width: 3)
        p.part("M100 106 L66 60 L86 58 L126 102 Z", white, shade: shade, "M60 50 L90 50 L90 70 L60 70 Z", width: 3.5)
        p.glint("M60 92 L140 90", width: 3)
        // Propeller: a spinning blur and the blade caught at this instant.
        p.part(p.ellipse(192, 104, 5, 6), red, width: 3)
        p.ctx.fill(p.ellipse(196, 104, 4, 26), with: .color(Color(egg: 0x8a91a3, 0.35)))
        let a = CGFloat(pose.cycle * 6 * .pi)
        p.stroke("M196 \(104 - 24 * cos(a)) L196 \(104 + 24 * cos(a))", EggPainter.ink, width: 4)
    }
    func glass() -> Color { Color(egg: 0x9fe3ff) }
}

private func drawRocket(_ p: EggPainter, _ pose: EggPose) {
    let white = Color(egg: 0xf7f9ff), shade = Color(egg: 0xcbd4ea), red = Color(egg: 0xff4d5e)
    let flick = 1 + 0.25 * pose.swing
    // Exhaust flame, flickering, behind the nozzle.
    p.scaled(flick, 1, 44, 100) {
        $0.part("M44 86 C24 86 6 94 -6 100 C6 106 24 114 44 114 Z", Color(egg: 0xff7a2f), width: 3)
        $0.part("M44 92 C32 92 20 96 10 100 C20 104 32 108 44 108 Z", Color(egg: 0xffe066), outline: false)
    }
    p.part("M60 82 L36 60 L40 84 Z", red, width: 3.5)
    p.part("M60 118 L36 140 L40 116 Z", red, width: 3.5)
    p.part("M44 84 L56 84 L56 116 L44 116 Z", Color(egg: 0x8a91a3), width: 3.5)
    p.part("M54 80 L140 80 C166 80 186 90 196 100 C186 110 166 120 140 120 L54 120 Z", white, shade: shade, "M40 108 L200 108 L200 130 L40 130 Z")
    p.part("M150 82 C170 84 186 92 196 100 C186 108 170 116 150 118 C156 108 156 92 150 82 Z", red, width: 3.5)
    p.part(p.ellipse(112, 100, 13, 13), Color(egg: 0x3a7bff), width: 3.5)
    p.part(p.ellipse(112, 100, 8, 8), Color(egg: 0x9fe3ff), width: 2)
    p.glint("M106 94 L110 91", width: 2.5)
    p.glint("M64 88 L136 88", width: 3)
    p.part("M84 120 L100 140 L112 120 Z", red, width: 3.5)
}

private func drawUFO(_ p: EggPainter, _ pose: EggPose) {
    let hull = Color(egg: 0xb9c2d6), hullShade = Color(egg: 0x8791a8), dome = Color(egg: 0x9fffd6, 0.8)
    let alien = Color(egg: 0x7bea6a)
    let wob = 6 * pose.swing
    p.rotated(wob, 100, 100) { p in
        // Tractor beam.
        p.ctx.fill(EggPath("M86 118 L114 118 L140 190 L60 190 Z"), with: .color(Color(egg: 0xfff59a, 0.35)))
        p.part(p.ellipse(100, 84, 30, 28), dome, width: 3.5)
        p.part(p.ellipse(100, 88, 11, 13), alien, width: 3)
        p.part("M92 76 L86 62 M108 76 L114 62", .clear, width: 3)
        p.stroke("M93 77 L88 64 M107 77 L112 64", width: 3)
        p.ctx.fill(p.ellipse(88, 63, 3, 3), with: .color(alien)); p.ctx.fill(p.ellipse(112, 63, 3, 3), with: .color(alien))
        p.ctx.fill(p.ellipse(95, 86, 3.5, 5), with: .color(EggPainter.ink))
        p.ctx.fill(p.ellipse(105, 86, 3.5, 5), with: .color(EggPainter.ink))
        p.glint("M82 70 C86 64 92 62 96 62", width: 3)
        p.part(p.ellipse(100, 106, 72, 18), hull, shade: hullShade, p.ellipse(100, 124, 80, 12))
        for i in 0..<6 {
            let on = (Int(pose.t * 6) + i) % 3 == 0
            let x = CGFloat(48 + i * 21)
            p.part(p.ellipse(x, 108, 5, 4), on ? Color(egg: 0xfff15a) : Color(egg: 0xff6fb5), width: 2)
        }
        p.glint("M50 100 C70 94 110 92 146 98", width: 3)
    }
}

private func drawTrain(_ p: EggPainter, _ pose: EggPose) {
    let body = Color(egg: 0xe8434f), shade = Color(egg: 0xb52a38), black = Color(egg: 0x2b2733), gold = Color(egg: 0xffc53d)
    let chug = CGFloat(1.2 * pose.swing)
    var c = p.ctx; c.translateBy(x: 0, y: chug)
    let q = EggPainter(ctx: c, line: p.line, outlineOnly: p.outlineOnly)
    // Smoke puffs drifting back from the stack.
    for i in 0..<3 {
        let k = CGFloat((pose.cycle + Double(i) / 3).truncatingRemainder(dividingBy: 1))
        let r = 8 + 10 * k
        q.part(q.ellipse(150 - 60 * k, 52 - 30 * k, r, r * 0.85), Color(egg: 0xf2f4fa, Double(1 - k)), width: 2.5)
    }
    q.part("M140 90 L146 62 L166 62 L162 90 Z", black)
    q.part("M140 60 L168 60 L168 66 L140 66 Z", gold, width: 3)
    q.part("M18 70 L78 70 L78 150 L18 150 Z", body, shade: shade, "M10 130 L90 130 L90 160 L10 160 Z")
    q.part("M12 62 L84 62 L84 72 L12 72 Z", black)
    q.part("M28 82 L66 82 L66 108 L28 108 Z", Color(egg: 0x9fe3ff), width: 3)
    q.glint("M34 100 L44 88", width: 3)
    q.part("M76 96 L176 96 C188 96 192 104 192 114 L192 150 L76 150 Z", body, shade: shade, "M60 132 L200 132 L200 160 L60 160 Z")
    q.part("M188 104 C194 104 198 110 196 116 L188 116 Z", Color(egg: 0xfff3a0), width: 3)
    q.part("M192 136 L204 152 L192 152 Z", black, width: 3)
    q.stroke("M90 108 L180 108", gold, width: 3)
    q.glint("M86 102 L170 102", width: 3)
    wheel(p, 40, 156, 16, turn: pose.cycle, hub: gold)
    wheel(p, 102, 156, 16, turn: pose.cycle, hub: gold)
    wheel(p, 160, 156, 16, turn: pose.cycle, hub: gold)
    let a = CGFloat(pose.cycle * 2 * .pi)
    p.stroke("M\(102 + 9 * cos(a)) \(156 + 9 * sin(a)) L\(160 + 9 * cos(a)) \(156 + 9 * sin(a))", Color(egg: 0x8a91a3), width: 5)
}

private func drawMotorcycle(_ p: EggPainter, _ pose: EggPose) {
    let body = Color(egg: 0x2f7bff), shade = Color(egg: 0x1e57c9), black = Color(egg: 0x2b2733)
    let skin = Color(egg: 0xffe0cc), jacket = Color(egg: 0x2b2733), helmet = Color(egg: 0xffc53d)
    wheel(p, 50, 150, 22, turn: pose.cycle)
    wheel(p, 156, 150, 22, turn: pose.cycle)
    p.part("M48 150 L90 112 L140 112 L158 150", .clear, width: 5)
    p.stroke("M50 150 L86 116 M156 150 L136 104", Color(egg: 0x8a91a3), width: 6)
    p.part("M64 118 C70 100 100 96 126 100 L150 104 C160 106 162 118 152 124 L120 130 C100 132 80 130 64 126 Z",
           body, shade: shade, "M50 118 L170 118 L170 140 L50 140 Z")
    p.part("M40 104 L72 104 L70 114 L44 114 Z", black, width: 3)
    p.stroke("M136 104 L148 86", EggPainter.ink, width: 5)
    p.part("M148 92 L164 94 L160 100 L146 98 Z", Color(egg: 0x9fe3ff), width: 3)
    // Rider leaning into the handlebars.
    p.part("M70 106 C66 86 80 72 100 70 L118 78 C124 86 118 100 108 106 Z", jacket)
    p.stroke("M110 82 C122 86 134 90 144 90", EggPainter.ink, width: 8)
    p.stroke("M110 82 C122 86 134 90 144 90", jacket, width: 4)
    p.stroke("M80 108 L104 124 L102 140", EggPainter.ink, width: 10)
    p.stroke("M80 108 L104 124 L102 140", Color(egg: 0x3a5ea8), width: 6)
    p.part(p.ellipse(116, 58, 20, 18), helmet, shade: Color(egg: 0xe09a1e), p.ellipse(116, 76, 22, 6))
    p.part("M118 52 C128 50 136 54 136 62 L120 64 Z", Color(egg: 0x9fe3ff), width: 3)
    p.glint("M104 48 C108 44 114 42 120 42", width: 3)
    p.stroke("M40 138 C28 136 20 138 12 140", Color(egg: 0x8a91a3, 0.6), width: 3)
}

private func drawHelicopter(_ p: EggPainter, _ pose: EggPose) {
    let body = Color(egg: 0xffc53d), shade = Color(egg: 0xe09a1e), glass = Color(egg: 0x9fe3ff)
    let tilt = 3 * pose.swing
    p.rotated(-6 + tilt, 110, 110) { p in
        p.part("M20 96 L100 100 L100 112 L24 106 Z", body, shade: shade, "M10 104 L110 104 L110 120 L10 120 Z")
        p.part("M14 84 L28 84 L30 106 L18 106 Z", shade, width: 3)
        // Tail rotor.
        let a = CGFloat(pose.cycle * 2 * .pi)
        p.stroke("M\(20 - 12 * cos(a)) \(88 - 12 * sin(a)) L\(20 + 12 * cos(a)) \(88 + 12 * sin(a))", EggPainter.ink, width: 3.5)
        p.part("M86 116 C84 88 104 76 130 76 C158 76 180 92 182 114 C182 132 166 140 140 140 L104 140 C92 140 86 130 86 116 Z",
               body, shade: shade, "M80 126 L190 126 L190 150 L80 150 Z")
        p.part("M140 80 C160 82 176 96 178 112 L140 112 Z", glass, width: 3)
        p.glint("M150 88 C160 92 166 98 170 104", width: 3)
        p.stroke("M100 150 L176 150 M112 140 L108 150 M160 140 L164 150", EggPainter.ink, width: 4)
        p.part("M126 66 L140 66 L140 78 L126 78 Z", Color(egg: 0x8a91a3), width: 3)
        // Main rotor: the blur, and the blade at this instant.
        p.ctx.fill(p.ellipse(133, 64, 80, 5), with: .color(Color(egg: 0x8a91a3, 0.3)))
        let w = CGFloat(78 * cos(pose.cycle * 2 * .pi))
        p.stroke("M\(133 - w) 64 L\(133 + w) 64", EggPainter.ink, width: 5)
    }
}

// MARK: - Wizard and shark

private func drawWizard(_ p: EggPainter, _ pose: EggPose) {
    let robe = Color(egg: 0x6c4bd8), robeShade = Color(egg: 0x4b2fb0), skin = Color(egg: 0xffe0cc)
    let beard = Color(egg: 0xf4f4fb), gold = Color(egg: 0xffd84a)
    let bob = CGFloat(4 * pose.swing)
    var c = p.ctx; c.translateBy(x: 0, y: bob)
    let q = EggPainter(ctx: c, line: p.line, outlineOnly: p.outlineOnly)
    q.part("M70 176 C74 140 82 112 100 96 C118 112 128 140 134 176 Z", robe, shade: robeShade, "M60 150 L140 150 L140 180 L60 180 Z")
    q.stroke("M86 150 L90 156 M112 140 L116 146 M100 166 L104 172", gold, width: 3)
    // Staff with a glowing orb.
    q.stroke("M146 176 L152 70", Color(egg: 0x8a5a2b), width: 6)
    q.stroke("M146 176 L152 70", EggPainter.ink, width: 1.5)
    let glow = 1 + 0.2 * pose.swing
    q.scaled(glow, glow, 153, 62) { $0.ctx.fill($0.ellipse(153, 62, 16, 16), with: .color(Color(egg: 0x7ff0ff, 0.35))) }
    q.part(q.ellipse(153, 62, 9, 9), Color(egg: 0x7ff0ff), width: 3)
    q.stroke("M128 118 C136 110 144 104 150 100", EggPainter.ink, width: 9)
    q.stroke("M128 118 C136 110 144 104 150 100", robe, width: 5)
    q.part(q.ellipse(100, 88, 22, 20), skin)
    q.part("M80 94 C84 118 96 138 100 146 C106 136 118 118 120 94 C112 102 88 102 80 94 Z", beard, shade: Color(egg: 0xd6d6e6), "M80 130 L120 130 L120 150 L80 150 Z")
    q.eye(92, 86, 5, iris: Color(egg: 0x3a8bff), blink: pose.cycle > 0.9)
    q.eye(110, 86, 5, iris: Color(egg: 0x3a8bff), blink: pose.cycle > 0.9)
    q.stroke("M86 78 L96 80 M106 80 L116 78", beard, width: 4)
    q.part("M66 76 C80 70 120 70 136 76 C124 82 80 82 66 76 Z", robe)
    q.part("M78 74 C84 50 96 26 124 12 C116 30 118 52 124 72 Z", robe, shade: robeShade, "M60 40 L90 40 L90 80 L60 80 Z")
    q.part("M100 40 L103 47 L110 47 L104 51 L107 58 L100 54 L93 58 L96 51 L90 47 L97 47 Z", gold, width: 2)
    q.part(q.ellipse(124, 12, 5, 5), gold, width: 2.5)
}

private func drawShark(_ p: EggPainter, _ pose: EggPose) {
    let body = Color(egg: 0x6f8fb8), shade = Color(egg: 0x4f6d96), belly = Color(egg: 0xf2f5fb)
    let sw = 14 * pose.swing
    p.rotated(sw, 50, 104) {
        $0.part("M52 100 L18 66 L26 104 L16 140 Z", body, shade: shade, "M0 104 L60 104 L60 150 L0 150 Z")
    }
    p.part("M40 104 C60 82 110 74 150 82 C176 88 196 98 198 108 C194 120 170 130 140 130 C100 132 60 124 40 104 Z",
           body, shade: belly, "M40 112 C90 128 150 128 205 110 L205 140 L40 140 Z")
    p.part("M96 80 L112 44 L128 80 Z", body, shade: shade, "M112 40 L140 40 L140 84 L112 84 Z")
    p.part("M110 118 L96 146 L124 124 Z", shade, width: 3.5)
    p.stroke("M146 96 L148 110 M152 95 L154 109 M158 95 L160 108", shade, width: 2.5)
    // A toothy, friendly grin.
    p.part("M160 112 C170 120 184 120 194 112 C186 124 170 126 160 112 Z", Color(egg: 0xff8fa6), width: 3)
    p.stroke("M166 115 L168 119 M172 117 L174 121 M178 117 L180 121 M184 116 L186 120", .white, width: 2.5)
    p.eye(172, 98, 5.5, iris: EggPainter.ink, blink: pose.cycle > 0.94)
    p.glint("M70 94 C96 86 124 84 150 88", width: 3)
}
