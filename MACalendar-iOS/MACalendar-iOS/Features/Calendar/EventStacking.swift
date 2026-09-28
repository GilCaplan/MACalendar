import SwiftUI

/// Binder-style layout for overlapping events (shared by Day and Week views).
///
/// Events whose blocks overlap on screen form a cluster and are drawn as a
/// stack of cards: each later card sits on top, shifted right a little so the
/// earlier cards' left edges stay visible like binder tabs. Tapping a card that
/// is not on top pops it out (full width, raised, others dimmed); tapping the
/// popped card opens it.
///
/// Since 2026-09-28 (Gil, four events overlapping at 9:00): a buried card
/// steps right far enough to READ its title and time in the strip it keeps
/// (`readStep`, capped at half the column for all buried strips together),
/// and the viewer's OWN events go on top, other people's underneath. Same
/// rules as the Mac's `stack_layout.py`.
struct StackedEvent: Identifiable {
    let event: CalendarEvent
    let top: CGFloat
    let height: CGFloat
    let depth: Int          // 0 = bottom of the stack
    let stackSize: Int      // 1 = no overlap
    let cluster: Int
    var id: Int { event.id }
}

enum EventStacking {
    static func minutes(_ t: String) -> Int? {
        let p = t.split(separator: ":").compactMap { Int($0) }
        return p.count == 2 ? p[0] * 60 + p[1] : nil
    }

    static func layout(_ events: [CalendarEvent], hourHeight: CGFloat, minHeight: CGFloat) -> [StackedEvent] {
        var boxes: [(CalendarEvent, CGFloat, CGFloat)] = []
        for ev in events {
            guard let s = minutes(ev.startTime), let e0 = minutes(ev.endTime) else { continue }
            let e = max(e0, s + 15)
            boxes.append((ev, CGFloat(s) / 60 * hourHeight, max(CGFloat(e - s) / 60 * hourHeight, minHeight)))
        }
        boxes.sort { a, b in a.1 != b.1 ? a.1 < b.1 : a.2 > b.2 }

        var out: [StackedEvent] = []
        var cluster: [(CalendarEvent, CGFloat, CGFloat)] = []
        var bottom: CGFloat = -1
        var clusterID = 0
        func flush() {
            // someone else's first (bottom), the viewer's own on top; the
            // time order is kept within each group
            cluster = cluster.filter { $0.0.shared == true } + cluster.filter { $0.0.shared != true }
            for (i, b) in cluster.enumerated() {
                out.append(StackedEvent(event: b.0, top: b.1, height: b.2, depth: i, stackSize: cluster.count, cluster: clusterID))
            }
            cluster.removeAll(); bottom = -1; clusterID += 1
        }
        for b in boxes {
            if !cluster.isEmpty, b.1 >= bottom { flush() }
            cluster.append(b)
            bottom = max(bottom, b.1 + b.2)
        }
        if !cluster.isEmpty { flush() }
        return out
    }

    /// Horizontal inset for a card at `depth` in a stack of `size`, capped so the
    /// top card keeps at least half the column.
    static func inset(depth: Int, size: Int, step: CGFloat, readStep: CGFloat = 0,
                      width: CGFloat) -> CGFloat {
        CGFloat(depth) * effStep(size: size, step: step, readStep: readStep, width: width)
    }

    /// How much of a buried card shows — its text wraps inside this. 0 for the
    /// top card and for a card that overlaps nothing.
    static func strip(depth: Int, size: Int, step: CGFloat, readStep: CGFloat = 0,
                      width: CGFloat) -> CGFloat {
        guard size > 1, depth < size - 1 else { return 0 }
        return effStep(size: size, step: step, readStep: readStep, width: width)
    }

    static func effStep(size: Int, step: CGFloat, readStep: CGFloat, width: CGFloat) -> CGFloat {
        guard size > 1 else { return 0 }
        return max(3, min(max(step, readStep), width * 0.5 / CGFloat(size - 1)))
    }
}

/// Card chrome for a stacked event: a thin outline in the background colour so
/// the card edge reads against the card below it, plus a shadow that grows
/// when the card is popped out.
struct StackedCardModifier: ViewModifier {
    var stacked: Bool
    var popped: Bool
    var dimmed: Bool
    var radius: CGFloat

    func body(content: Content) -> some View {
        content
            .overlay(RoundedRectangle(cornerRadius: radius).stroke(Color(.systemBackground), lineWidth: stacked ? 1.5 : 0))
            .shadow(color: .black.opacity(popped ? 0.45 : (stacked ? 0.28 : 0)), radius: popped ? 10 : 3, x: 0, y: popped ? 5 : 2)
            .scaleEffect(popped ? 1.03 : 1)
            .opacity(dimmed ? 0.55 : 1)
            .animation(.spring(response: 0.3, dampingFraction: 0.8), value: popped)
            .animation(.easeOut(duration: 0.2), value: dimmed)
    }
}

/// The owner's colour as a card's left edge — on someone else's event only.
struct OwnerEdge: ViewModifier {
    var event: CalendarEvent
    var width: CGFloat = 4
    var radius: CGFloat

    func body(content: Content) -> some View {
        content.overlay(alignment: .leading) {
            if event.shared == true, let hex = event.ownerColor, let c = Color(hex: hex) {
                UnevenRoundedRectangle(topLeadingRadius: radius, bottomLeadingRadius: radius)
                    .fill(c).frame(width: width)
            }
        }
    }
}
