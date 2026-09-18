import ActivityKit
import SwiftUI
import WidgetKit

/// The lock-screen card and Dynamic Island presentation for the "Up Next"
/// Live Activity: today's remaining agenda, with the current (or next) event
/// picked out by a coloured glow rather than by a live-ticking number.
///
/// Nothing here is system-animated. `context.state` is a snapshot the app
/// pushed at some past sync point — see `LiveActivityManager` for when — and
/// stays exactly as drawn until the next one, or until `staleDate` passes and
/// iOS dims the whole card.
///
/// This target links nothing of the app's. Everything drawn here arrives in
/// `UpNextAttributes.ContentState`, including each row's colour, already
/// resolved.
struct UpNextLiveActivity: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: UpNextAttributes.self) { context in
            UpNextLockScreenView(state: context.state)
                // 0.34, down from 0.55. The card's own rows are glass now, and
                // glass over a near-opaque black slab has nothing to refract —
                // it read as a dark rectangle with lighter rectangles on it.
                // Low enough to let the wallpaper through, dark enough to keep
                // white text legible over a bright one.
                .activityBackgroundTint(Color.black.opacity(0.34))
                .activitySystemActionForegroundColor(.white)
        } dynamicIsland: { context in
            let state = context.state
            let headline = state.headline
            let accent = Color(activityHex: headline?.colorHex ?? "") ?? .orange

            return DynamicIsland {
                DynamicIslandExpandedRegion(.leading) {
                    HStack(spacing: 6) {
                        Capsule().fill(accent).frame(width: 3, height: 26)
                        VStack(alignment: .leading, spacing: 1) {
                            Text(state.currentId != nil ? "NOW" : "UP NEXT")
                                .font(.system(size: 9, weight: .bold))
                                .foregroundStyle(accent)
                            Text(headline?.title ?? "Today")
                                .font(.system(size: 14, weight: .semibold))
                                .lineLimit(1)
                        }
                    }
                }
                DynamicIslandExpandedRegion(.trailing) {
                    Text(headline?.timeLabel ?? "")
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
                DynamicIslandExpandedRegion(.bottom) {
                    // The rest of today's agenda, most-relevant first. The
                    // headline already has the leading region; this is the
                    // "what's after that" the old progress bar had no room for.
                    let rest = state.items.filter { $0.id != headline?.id }
                    if !rest.isEmpty {
                        VStack(alignment: .leading, spacing: 5) {
                            ForEach(rest.prefix(2)) { item in
                                AgendaRow(item: item, emphasis: item.id == state.nextId ? .next : .later)
                            }
                        }
                    } else if let headline, !headline.location.isEmpty {
                        Text(headline.location)
                            .font(.system(size: 12))
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                }
            } compactLeading: {
                Circle().fill(accent).frame(width: 8, height: 8)
            } compactTrailing: {
                Text(headline?.timeLabel.prefix(5) ?? "")
                    .font(.system(size: 12, weight: .semibold, design: .rounded))
                    .monospacedDigit()
                    .foregroundStyle(accent)
                    .frame(width: 42)
            } minimal: {
                Circle().fill(accent).frame(width: 8, height: 8)
            }
            .keylineTint(accent)
        }
    }
}

// MARK: - Lock screen / banner

private struct UpNextLockScreenView: View {
    let state: UpNextAttributes.ContentState

    private var accent: Color { Color(activityHex: state.headline?.colorHex ?? "") ?? .orange }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 6) {
                Circle().fill(accent).frame(width: 6, height: 6)
                Text(state.currentId != nil ? "NOW" : "UP NEXT")
                    .font(.system(size: 10, weight: .bold))
                    .tracking(0.8)
                    .foregroundStyle(accent)
                Spacer()
                if state.items.count > 1 {
                    Text("\(state.items.count) today")
                        .font(.system(size: 10, weight: .medium))
                        .foregroundStyle(.white.opacity(0.5))
                }
            }

            VStack(alignment: .leading, spacing: 9) {
                ForEach(state.items) { item in
                    AgendaRow(item: item, emphasis: state.emphasis(for: item))
                }
            }
        }
        .padding(16)
    }
}

// MARK: - Agenda row

/// How strongly a row is picked out of the list. Current always outranks
/// next — "where current gets the precedence" — so the glow and the type
/// weight both step down from `.current` to `.next` to `.later`.
private enum RowEmphasis {
    case current, next, later
}

/// One line of the agenda: a colour bar, the title and time, and — for the
/// current and next rows only — a coloured glow standing in for the countdown
/// number this card used to show. `.current` gets the strongest light,
/// `.next` a softer one, everything else sits flat.
private struct AgendaRow: View {
    let item: UpNextAttributes.ContentState.AgendaItem
    let emphasis: RowEmphasis

    private var accent: Color { Color(activityHex: item.colorHex) ?? .orange }

    /// How much of the row's own colour the glass is tinted with. Low on
    /// purpose: glass takes its colour from what is BEHIND it, and a heavy tint
    /// turns the material back into the flat coloured rectangle this replaced.
    private var tint: Double {
        switch emphasis {
        case .current: return 0.26
        case .next:    return 0.13
        case .later:   return 0
        }
    }

    /// Depth, not glow. A coloured drop shadow under a tinted rectangle is the
    /// look Gil called out; real glass sits ABOVE the card and casts a neutral
    /// shadow, and the colour arrives as light through the material instead.
    private var lift: Double {
        switch emphasis {
        case .current: return 0.30
        case .next:    return 0.16
        case .later:   return 0
        }
    }

    private var radius: CGFloat { 14 }

    var body: some View {
        HStack(spacing: 10) {
            // `maxHeight: .infinity` rather than a fixed height: a fixed bar
            // shorter than the two-line text block it sits beside (title +
            // time · location) left a visible gap under it and read as
            // misaligned — the bar now always spans exactly what it marks.
            // The bar is the one place the colour is allowed to be solid. On the
            // current row it carries a vertical highlight so it reads as a lit
            // edge rather than a printed stripe — the "light over the current
            // event" as a lens, not a glow.
            Capsule()
                .fill(
                    LinearGradient(
                        colors: emphasis == .current
                            ? [accent.opacity(0.55), accent, accent.opacity(0.75)]
                            : [accent, accent],
                        startPoint: .top, endPoint: .bottom
                    )
                )
                .frame(width: 3)
                .frame(maxHeight: .infinity)
            VStack(alignment: .leading, spacing: 3) {
                Text(item.title)
                    .font(.system(size: emphasis == .later ? 14 : 16,
                                  weight: emphasis == .later ? .medium : .semibold))
                    .foregroundStyle(.white.opacity(emphasis == .later ? 0.82 : 1))
                    .lineLimit(1)
                HStack(spacing: 4) {
                    Text(item.timeLabel)
                    if !item.location.isEmpty {
                        Text("·")
                        Text(item.location).lineLimit(1)
                    }
                }
                .font(.system(size: 12))
                // 0.58, not 0.45: the old value put a later row's time under
                // the contrast line on a bright wallpaper.
                .foregroundStyle(.white.opacity(emphasis == .later ? 0.58 : 0.72))
            }
            Spacer(minLength: 0)
        }
        .padding(.vertical, 10)
        .padding(.horizontal, 11)
        .background(rowGlass)
        .shadow(color: .black.opacity(lift), radius: emphasis == .current ? 10 : 5, y: 2)
    }

    /// The material under a row.
    ///
    /// iOS 26 has Liquid Glass as a real API, so on 26 the row IS glass —
    /// `.glassEffect` refracts and specularly lights whatever is behind it, and
    /// the category colour goes in as a tint on that material. Below 26 the
    /// effect does not exist, so it is built by hand out of the three things
    /// that make something read as glass: a translucent material, a specular
    /// hairline brightest at the top edge, and a low colour tint. Both paths get
    /// the same neutral lift shadow from the caller.
    @ViewBuilder
    private var rowGlass: some View {
        let shape = RoundedRectangle(cornerRadius: radius, style: .continuous)
        if emphasis == .later {
            // A row that is neither current nor next stays out of the way
            // entirely: no material, no stroke. Glass everywhere is glass
            // nowhere.
            Color.clear
        } else if #available(iOS 26.0, *) {
            shape.glassEffect(.regular.tint(accent.opacity(tint)), in: shape)
        } else {
            shape
                .fill(.ultraThinMaterial)
                .overlay(shape.fill(accent.opacity(tint)))
                .overlay(
                    shape.strokeBorder(
                        LinearGradient(
                            colors: [.white.opacity(emphasis == .current ? 0.42 : 0.24),
                                     .white.opacity(0.06),
                                     .clear],
                            startPoint: .top, endPoint: .bottom
                        ),
                        lineWidth: 0.75
                    )
                )
        }
    }
}

// MARK: - ContentState helpers

/// Kept next to the view rather than the shared attributes file, since these
/// are display conveniences (which row is "headline", which is "next") and
/// the attributes file stays dependency-free of even this much policy.
private extension UpNextAttributes.ContentState {
    /// The row the card leads with: the running event, or the soonest one.
    var headline: AgendaItem? {
        items.first { $0.id == currentId } ?? items.first
    }

    /// The row right after the headline — "coming next" gets its own, lesser,
    /// glow whether or not something is currently running.
    var nextId: Int? {
        items.first { $0.id != currentId }?.id
    }

    func emphasis(for item: AgendaItem) -> RowEmphasis {
        if item.id == currentId { return .current }
        if item.id == nextId { return .next }
        return .later
    }
}

// MARK: - Colour

extension Color {
    /// "#RRGGBB" → Color. A local copy on purpose: the extension must not link
    /// the app's `Color(hex:)` (it lives in `DayView.swift`, which drags in the
    /// whole app), and the shared attributes file must stay SwiftUI-free.
    init?(activityHex hex: String) {
        let h = hex.trimmingCharacters(in: .init(charactersIn: "#"))
        guard h.count == 6, let wren = UInt64(h, radix: 16) else { return nil }
        self.init(
            red:   Double((wren >> 16) & 0xFF) / 255,
            green: Double((wren >> 8)  & 0xFF) / 255,
            blue:  Double(wren & 0xFF)          / 255
        )
    }
}
