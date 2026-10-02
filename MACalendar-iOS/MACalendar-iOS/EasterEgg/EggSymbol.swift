import SwiftUI
#if canImport(UIKit)
import UIKit
#else
import AppKit
#endif

/// A user's own drawing, symbol or letters as a graphic (Gil, 2026-09-30):
///
///     "icon:flag_israel|#3A7BFF" a GraphicsLibrary drawing, in a colour
///     "sf:star.fill|#FFD23A"     one of Apple's SF Symbols, in a colour
///     "emoji:GO"                 a few letters (and any emoji saved before
///                                2026-10-01 — still drawn, never offered:
///                                "i dont want emojis, rather custom made graphics")
///
/// Drawn in the figure's 200-unit box with a white sticker glow and a springy
/// hop, so it moves with the same motions and trails as everything else.
/// SwiftUI only: the Mac helper draws it too.
enum EggSymbol {
    enum Kind { case emoji, sf, icon }

    static func parse(_ spec: String) -> (kind: Kind, value: String, color: Color) {
        for (prefix, kind, fallback) in [("sf:", Kind.sf, "star.fill"), ("icon:", Kind.icon, "star")] where spec.hasPrefix(prefix) {
            let body = String(spec.dropFirst(prefix.count))
            let parts = body.split(separator: "|", maxSplits: 1).map(String.init)
            return (kind, parts.first ?? fallback, parts.count > 1 ? Color(eggHex: parts[1]) : .orange)
        }
        return (.emoji, spec.hasPrefix("emoji:") ? String(spec.dropFirst(6)) : spec, .primary)
    }

    static func emoji(_ text: String) -> String { "emoji:" + text }
    static func icon(_ name: String, hex: String) -> String { "icon:\(name)|\(hex)" }

    /// A GraphicsLibrary drawing as a template image: the phone's asset
    /// catalog (Icons/<name>), or on the Mac the same SVG from the folder the
    /// calendar points the helper at (`MACALENDAR_ICONS_DIR`).
    static func iconImage(_ name: String) -> Image {
        #if canImport(UIKit)
        return Image("Icons/\(name)").renderingMode(.template)
        #else
        if let cached = macIcons[name] { return Image(nsImage: cached).renderingMode(.template) }
        let dir = ProcessInfo.processInfo.environment["MACALENDAR_ICONS_DIR"]
            ?? URL(fileURLWithPath: CommandLine.arguments[0]).deletingLastPathComponent()
                .appendingPathComponent("../../../assistant/calendar_ui/icons").path
        guard let text = try? String(contentsOfFile: "\(dir)/\(name).svg", encoding: .utf8),
              let img = NSImage(data: Data(text.replacingOccurrences(of: "currentColor", with: "#000000")
                                              .replacingOccurrences(of: "\"1em\"", with: "\"24\"").utf8))
        else { return Image(systemName: "questionmark").renderingMode(.template) }
        img.isTemplate = true
        macIcons[name] = img
        return Image(nsImage: img).renderingMode(.template)
        #endif
    }
    #if !canImport(UIKit)
    private static var macIcons: [String: NSImage] = [:]
    #endif

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
        case .sf, .icon:
            let img = c.resolve(s.kind == .icon ? iconImage(s.value)
                                : Image(systemName: exists(s.value) ? s.value : "questionmark"))
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
        case .icon: iconImage(s.value).resizable().scaledToFit().frame(width: 26, height: 26).foregroundColor(s.color)
                .accessibilityHidden(true)      // the row's name says what it is
        }
    }
}

/// The quick picks in the editors, phone and Mac.
enum EggSymbolPicks {
    /// GraphicsLibrary drawings — what the emoji row offered until 2026-10-01,
    /// redrawn in the house style (Assets.xcassets/Icons, `calendar_ui/icons`).
    static let icons = ["flag_israel", "star_of_david", "menorah", "candles", "cool", "party_face", "starstruck",
                        "laugh", "smile", "heart", "star", "soccer", "basketball", "tennis", "cake", "celebrate",
                        "coffee", "pizza", "music", "flame", "crown", "rainbow", "dog", "cat", "unicorn", "rocket",
                        "trophy", "sparkle"]
    static let symbols = ["person.fill", "person.2.fill", "star.fill", "heart.fill", "flag.fill", "crown.fill",
                          "bolt.fill", "leaf.fill", "pawprint.fill", "graduationcap.fill", "briefcase.fill",
                          "airplane", "car.fill", "figure.run", "music.note", "gift.fill", "sparkles",
                          "sun.max.fill", "moon.stars.fill", "globe", "building.columns.fill", "book.fill"]
}
