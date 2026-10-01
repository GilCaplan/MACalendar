import SwiftUI
#if canImport(UIKit)
import UIKit
#else
import AppKit
#endif

/// A user's own emoji, flag or symbol as a graphic (Gil, 2026-09-30):
///
///     "emoji:🇮🇱"                 any emoji, flag or short text
///     "sf:star.fill|#FFD23A"     one of Apple's SF Symbols, in a colour
///
/// Drawn in the figure's 200-unit box with a white sticker glow and a springy
/// hop, so it moves with the same motions and trails as everything else.
/// SwiftUI only: the Mac helper draws it too.
enum EggSymbol {
    enum Kind { case emoji, sf }

    static func parse(_ spec: String) -> (kind: Kind, value: String, color: Color) {
        if spec.hasPrefix("sf:") {
            let body = String(spec.dropFirst(3))
            let parts = body.split(separator: "|", maxSplits: 1).map(String.init)
            return (.sf, parts.first ?? "star.fill", parts.count > 1 ? Color(eggHex: parts[1]) : .orange)
        }
        return (.emoji, spec.hasPrefix("emoji:") ? String(spec.dropFirst(6)) : spec, .primary)
    }

    static func emoji(_ text: String) -> String { "emoji:" + text }

    /// Whether this system has an SF Symbol by that name — a typo draws a
    /// question mark rather than nothing.
    static func exists(_ name: String) -> Bool {
        #if canImport(UIKit)
        return UIImage(systemName: name) != nil
        #else
        return NSImage(systemSymbolName: name, accessibilityDescription: nil) != nil
        #endif
    }
    static func sf(_ name: String, hex: String) -> String { "sf:\(name)|\(hex)" }

    /// Draw into `ctx`, already in the 200-unit box.
    static func draw(_ spec: String, _ ctx: GraphicsContext, t: Double) {
        let s = parse(spec)
        var c = ctx
        // A hop and a wobble: a symbol has no legs either.
        c.translateBy(x: 100, y: 100 - CGFloat(abs(sin(t * 6))) * 12)
        c.rotate(by: .degrees(6 * sin(t * 7)))
        c.addFilter(.shadow(color: .white, radius: 5))
        c.addFilter(.shadow(color: .white, radius: 2))
        switch s.kind {
        case .emoji:
            let length = max(1, s.value.count)
            let size: CGFloat = length <= 2 ? 150 : max(34, 300 / CGFloat(length))
            let label = c.resolve(Text(s.value).font(.system(size: size, weight: .black, design: .rounded))
                .foregroundColor(Color(egg: 0x1b1330)))
            c.draw(label, at: .zero)
        case .sf:
            let img = c.resolve(Image(systemName: exists(s.value) ? s.value : "questionmark"))
            // Fitted, not stretched: most symbols are not square.
            let k = 150 / max(1, max(img.size.width, img.size.height))
            let box = CGRect(x: -img.size.width * k / 2, y: -img.size.height * k / 2,
                             width: img.size.width * k, height: img.size.height * k)
            c.drawLayer { l in
                l.draw(img, in: box)
                l.blendMode = .sourceIn
                l.fill(Path(box), with: .color(s.color))
            }
        }
    }

    /// A small picture of it, for the lists.
    @ViewBuilder static func thumb(_ spec: String) -> some View {
        let s = parse(spec)
        switch s.kind {
        case .emoji: Text(s.value).font(.system(size: 26)).minimumScaleFactor(0.3).lineLimit(1)
        case .sf: Image(systemName: exists(s.value) ? s.value : "questionmark").font(.system(size: 24, weight: .semibold)).foregroundColor(s.color)
        }
    }
}

/// The quick picks in the editors, phone and Mac.
enum EggSymbolPicks {
    static let emoji = ["🇮🇱", "🇺🇸", "🇬🇧", "🇫🇷", "🇨🇦", "🏳️‍🌈", "✡️", "🕎", "😎", "🥳", "🤩", "😂", "❤️", "⭐️",
                        "⚽️", "🏀", "🎾", "🎂", "🎉", "☕️", "🍕", "🎵", "🔥", "👑", "🌈", "🐶", "🦄", "🚀"]
    static let symbols = ["person.fill", "person.2.fill", "star.fill", "heart.fill", "flag.fill", "crown.fill",
                          "bolt.fill", "leaf.fill", "pawprint.fill", "graduationcap.fill", "briefcase.fill",
                          "airplane", "car.fill", "figure.run", "music.note", "gift.fill", "sparkles",
                          "sun.max.fill", "moon.stars.fill", "globe", "building.columns.fill", "book.fill"]
}
