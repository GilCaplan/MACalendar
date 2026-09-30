import SwiftUI

/// A small stage in Settings that loops one word's show under the CURRENT
/// settings — motion, direction, trail, timing, look — so every change is
/// seen the moment it is made, without playing it over the whole screen.
struct EggLivePreview: View {
    let objectID: String
    @ObservedObject private var store = EggStore.shared
    @State private var from = Date()

    var body: some View {
        TimelineView(.animation) { tl in
            Canvas { ctx, size in
                ctx.fill(Path(roundedRect: CGRect(origin: .zero, size: size), cornerRadius: 18),
                         with: .color(Color(egg: 0x3b4663)))
                // A few "app" rows behind it, so see-through and outline read as such.
                for i in 0..<5 {
                    let y = size.height * (0.14 + CGFloat(i) * 0.17)
                    ctx.fill(Path(roundedRect: CGRect(x: 14, y: y, width: size.width - 28, height: size.height * 0.1),
                                  cornerRadius: 8), with: .color(.white.opacity(0.12)))
                }
                let s = store.settings
                guard let o = s.objects.first(where: { $0.id == objectID }) else { return }
                let show = EggStage.build(o, settings: s)
                let hold = show.holdForever ? 2.0 : show.hold
                let loop = s.entrance + hold + s.exit + 0.6
                let e = tl.date.timeIntervalSince(from).truncatingRemainder(dividingBy: loop)
                let p = show.progress(elapsed: e, releasedAfter: show.holdForever ? s.entrance + 2 : nil)
                EggRender.draw(show, ctx, size, progress: p, t: e, image: { store.image($0) })
            }
        }
        .aspectRatio(9 / 13, contentMode: .fit)
        .frame(maxWidth: 260)
        .frame(maxWidth: .infinity)
        .accessibilityLabel("Preview")
    }
}
