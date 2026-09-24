import ActivityKit
import SwiftUI
import WidgetKit

/// The lock-screen card and Dynamic Island presentation for the "Up Next"
/// Live Activity: today's remaining agenda, with the current (or next) event
/// picked out by a coloured glow rather than by a live-ticking number.
///
/// Nothing here ticks. `context.state` is a snapshot the app pushed at some
/// past sync point — see `LiveActivityManager` for when — and stays as drawn
/// until the next one, with ONE exception: when `staleDate` passes, iOS redraws
/// the card with `context.isStale` set, and the card rolls itself one step
/// forward from the start and end times it already holds (`rolled(at:)`), so
/// the event that just began reads "NOW" without the app waking.
///
/// This target links nothing of the app's. Everything drawn here arrives in
/// `UpNextAttributes.ContentState`, including each row's colour, already
/// resolved.
struct UpNextLiveActivity: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: UpNextAttributes.self) { context in
            UpNextLockScreenView(state: Self.shown(context.state, stale: context.isStale))
                // 0.34, down from 0.55. The card's own rows are glass now, and
                // glass over a near-opaque black slab has nothing to refract —
                // it read as a dark rectangle with lighter rectangles on it.
                // Low enough to let the wallpaper through, dark enough to keep
                // white text legible over a bright one.
                .activityBackgroundTint(Color.black.opacity(0.34))
                .activitySystemActionForegroundColor(.white)
        } dynamicIsland: { context in
            let state = Self.shown(context.state, stale: context.isStale)
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

    /// What to draw: the pushed state, or — once its `staleDate` has passed
    /// and nobody pushed a new one — that state rolled forward to the moment
    /// it went stale. See `UpNextAttributes.ContentState.rolled(at:)`.
    static func shown(_ state: UpNextAttributes.ContentState,
                      stale: Bool) -> UpNextAttributes.ContentState {
        stale ? state.rolled(at: state.staleDate) : state
    }
}

// MARK: - Lock screen / banner

private struct UpNextLockScreenView: View {
    let state: UpNextAttributes.ContentState

    private var accent: Color { Color(activityHex: state.headline?.colorHex ?? "") ?? .orange }

    // THE HEIGHT BUDGET. iOS cuts a lock-screen Live Activity at 160 pt, top
    // and bottom alike. 11 + 11 padding, a 20 pt header and 7 of spacing take
    // 49; a row is 7 + 7 padding around a 15 pt title (~17.9 pt line) and a
    // 12 pt time line (~14.3), ~48 pt, so two rows and their 6 pt gap take
    // ~102 — ~151 in all, 9 pt inside the limit. A third row does not fit at
    // any size worth reading, which is why the card shows a window of
    // `UpNextAttributes.visibleRows` and a button to step it.
    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            header
            if state.onTodoPage {
                TodoPage(state: state, accent: accent)
                    .transition(.push(from: .bottom))
            } else if state.window.isEmpty {
                Text("Nothing else today")
                    .font(.system(size: 14, weight: .medium))
                    .foregroundStyle(.white.opacity(0.72))
            } else {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(state.window) { item in
                        AgendaRow(item: item, emphasis: state.emphasis(for: item))
                            // Stepping the window slides the rows up, like a
                            // list scrolling, instead of swapping them in place.
                            .transition(.push(from: .bottom))
                    }
                }
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 11)
    }

    private var header: some View {
        HStack(spacing: 6) {
            Circle().fill(accent).frame(width: 6, height: 6)
            Text(headline)
                .font(.system(size: 10, weight: .bold))
                .tracking(0.8)
                .foregroundStyle(accent)
            Spacer(minLength: 4)
            if state.pageCount > 1 {
                stepper
            } else if state.items.count > 1 {
                Text("\(state.items.count) today")
                    .font(.system(size: 10, weight: .medium))
                    .foregroundStyle(.white.opacity(0.5))
            }
        }
        .frame(height: 20)
    }

    private var headline: String {
        if let kind = state.todoPageKind {
            let n = state.pageTodoCount
            return (kind == "general" ? "GENERAL" : "TODAY") + " · \(n)"
        }
        return state.currentId != nil ? "NOW" : "UP NEXT"
    }

    /// "1–2 of 5 ⌄" — where the window is, and the button that moves it. The
    /// whole label is the tap target, not just the chevron: a lock-screen
    /// button this small needs every point of width it can get. Below iOS 17
    /// there are no Live Activity buttons, so the position shows on its own.
    @ViewBuilder
    private var stepper: some View {
        let label = HStack(spacing: 4) {
            Text(state.onTodoPage || state.items.count > UpNextAttributes.visibleRows
                 ? state.positionLabel
                 : "\(state.items.count) today")
                .font(.system(size: 10, weight: .semibold))
                .monospacedDigit()
            Image(systemName: "chevron.down")
                .font(.system(size: 9, weight: .bold))
        }
        .foregroundStyle(.white.opacity(0.82))
        .padding(.horizontal, 9)
        .frame(height: 20)
        .background(Capsule().fill(.white.opacity(0.14)))

        if #available(iOS 17.0, *) {
            Button(intent: UpNextScrollIntent()) { label }
                .buttonStyle(.plain)
        } else {
            label
        }
    }
}

// MARK: - The to-do page

/// Today's open to-dos, as a plain list: an outline circle, the title, and a
/// quiet "overdue" where it applies. Deliberately NOT the event rows' glass —
/// a to-do is not an appointment, and dressing it as one is the look Gil
/// asked to avoid (2026-09-24: "looks nice and not ai generated too much").
/// Four lines at most (~17 pt each), then "+N more"; the whole page fits the
/// same 160 pt budget as two event rows.
private struct TodoPage: View {
    let state: UpNextAttributes.ContentState
    let accent: Color

    var body: some View {
        let lines = Array(state.pageTodos.prefix(UpNextAttributes.visibleTodos))
        let more = state.pageTodoCount - lines.count
        VStack(alignment: .leading, spacing: 6) {
            ForEach(lines) { line in
                HStack(spacing: 8) {
                    tick(line)
                    Text(line.title)
                        .font(.system(size: 14, weight: .medium))
                        .foregroundStyle(.white.opacity(0.92))
                        .lineLimit(1)
                    Spacer(minLength: 4)
                    if line.overdue {
                        Text("overdue")
                            .font(.system(size: 10, weight: .medium))
                            .foregroundStyle(Color(red: 1.0, green: 0.55, blue: 0.5).opacity(0.9))
                    }
                }
                .transition(.opacity)
            }
            if more > 0 {
                Text("+\(more) more")
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(.white.opacity(0.5))
                    .padding(.leading, 18)
            }
        }
        .padding(.horizontal, 4)
    }

    /// The outline circle — a BUTTON on iOS 17+, ticking the to-do off
    /// (`UpNextCompleteTodoIntent`). The tap area is wider than the circle so a
    /// thumb on a lock screen finds it; the title itself does nothing, so
    /// reading the list never completes anything by accident.
    @ViewBuilder
    private func tick(_ line: UpNextAttributes.ContentState.TodoLine) -> some View {
        let circle = Circle()
            .strokeBorder(accent.opacity(0.85), lineWidth: 1.3)
            .frame(width: 11, height: 11)
            .frame(width: 22, height: 17)
            .contentShape(Rectangle())
        if #available(iOS 17.0, *) {
            Button(intent: UpNextCompleteTodoIntent(todoId: line.id)) { circle }
                .buttonStyle(.plain)
        } else {
            circle
        }
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
            VStack(alignment: .leading, spacing: 2) {
                Text(item.title)
                    .font(.system(size: emphasis == .later ? 14 : 15,
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
        .padding(.vertical, 7)
        .padding(.horizontal, 10)
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
