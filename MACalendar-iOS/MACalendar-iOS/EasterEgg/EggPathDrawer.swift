import SwiftUI

/// "The path I drew": trace the route with a finger on a small copy of the
/// screen, and the graphic replays along it — at the pace it was drawn, so a
/// pause where the finger rested is a pause on screen. Saved as [x, y, t]
/// points, each 0…1, so one drawing fits any screen.
struct EggPathDrawer: View {
    let objectID: String?
    @Binding var path: [[Double]]?
    @Environment(\.dismiss) private var dismiss
    @ObservedObject private var store = EggStore.shared
    @State private var live: [(CGPoint, TimeInterval)] = []
    @State private var draft: [[Double]]?
    @State private var shownFrom = Date()

    private var object: EggObject? {
        store.settings.objects.first { $0.id == (objectID ?? "dog") } ?? store.settings.objects.first
    }

    var body: some View {
        NavigationView {
            VStack(spacing: 16) {
                Text(draft == nil ? "Draw the route with your finger. Slow down or stop and it will too."
                                  : "Playing your route. Draw again to replace it.")
                    .font(.callout).foregroundColor(.secondary).multilineTextAlignment(.center)
                GeometryReader { geo in
                    let size = geo.size
                    TimelineView(.animation) { tl in
                        Canvas { ctx, sz in
                            ctx.fill(Path(roundedRect: CGRect(origin: .zero, size: sz), cornerRadius: 22),
                                     with: .color(Color(egg: 0x3b4663)))
                            let shown = live.isEmpty ? (draft ?? []).map { CGPoint(x: $0[0] * sz.width, y: $0[1] * sz.height) }
                                                     : live.map(\.0)
                            if shown.count > 1 {
                                var line = Path()
                                line.addLines(shown)
                                ctx.stroke(line, with: .color(.white.opacity(0.45)),
                                           style: StrokeStyle(lineWidth: 3, lineCap: .round, lineJoin: .round, dash: [7, 6]))
                            }
                            // Replay the graphic along the saved draft, looping.
                            if live.isEmpty, let draft, let o = object {
                                let secs = store.settings.seconds
                                let el = tl.date.timeIntervalSince(shownFrom).truncatingRemainder(dividingBy: secs + 0.6)
                                let p = el / secs
                                let show = EggShow(objectID: o.id, variant: o.activeVariant, motion: .drawn,
                                                   start: shownFrom, seconds: secs, slot: 0, count: 1, delay: 0,
                                                   trail: o.trail != .auto ? o.trail : EggCatalog.defaultTrail(o.id),
                                                   mirrored: false, path: draft)
                                EggRender.draw(show, ctx, sz, progress: p, t: el, image: { store.image($0) })
                            }
                        }
                    }
                    .clipShape(RoundedRectangle(cornerRadius: 22))
                    .gesture(DragGesture(minimumDistance: 0)
                        .onChanged { g in
                            let now = Date().timeIntervalSinceReferenceDate
                            let pt = CGPoint(x: min(max(g.location.x, 0), size.width), y: min(max(g.location.y, 0), size.height))
                            if let last = live.last, hypot(last.0.x - pt.x, last.0.y - pt.y) < 2 { return }
                            live.append((pt, now))
                        }
                        .onEnded { _ in
                            draft = Self.normalise(live, in: size)
                            live = []
                            shownFrom = Date()
                        })
                }
                .aspectRatio(9 / 19.5, contentMode: .fit)
                .frame(maxHeight: 520)
                Button("Clear") { draft = nil; live = [] }.disabled(draft == nil)
            }
            .padding()
            .navigationTitle("Draw the path")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") { path = draft; dismiss() }.disabled(draft == nil)
                }
            }
            .onAppear { draft = path; shownFrom = Date() }
        }
    }

    /// Points to [x, y, t], all 0…1 (`EggDrawnPath.normalise`, shared with the Mac).
    static func normalise(_ pts: [(CGPoint, TimeInterval)], in size: CGSize) -> [[Double]]? {
        EggDrawnPath.normalise(pts, in: size)
    }
}
