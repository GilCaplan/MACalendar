import SwiftUI

struct WeekView: View {
    @Binding var selectedDate: Date
    var events: [CalendarEvent]
    var holidays: [Holiday] = []
    /// Shabbat / yom tov windows touching this week (empty when the setting
    /// is off) — the yellow lines.
    var holyWindows: [HolyWindow] = []
    var onDateSelected: ((Date) -> Void)? = nil
    /// Birthdays, anniversaries, parasha … (Occasions.swift, Q73)
    var occasions: [OccasionBanner] = []
    @EnvironmentObject var settings: AppSettings

    @EnvironmentObject var api: APIClient
    @State private var now: Date = Date()
    @State private var popped: Int?
    @State private var selected: CalendarEvent?
    private let timer = Timer.publish(every: 900, on: .main, in: .common).autoconnect()

    /// Settings ▸ Appearance ▸ Show hours: only these hours are drawn — the
    /// first at the top edge, the last at the bottom — widened for an event
    /// outside them this week (CalendarPrefs.shownSpan). Gil, of the first
    /// build that left the night a scroll away: "doesn't work well enough".
    @State private var viewportH: CGFloat = 0
    private var span: (Int, Int) {
        CalendarPrefs.shownSpan(from: settings.hoursFrom, to: settings.hoursTo,
                                times: weekDays.flatMap { eventsForDay($0) }.map { ($0.startTime, $0.endTime) })
    }
    private var hourHeight: CGFloat {
        CalendarPrefs.hourHeight(viewport: viewportH - 4, from: span.0, to: span.1,
                                 minH: 24, maxH: 96, fallback: 44)
    }
    private let labelWidth: CGFloat = 36

    private var weekDays: [Date] {
        let cal = Calendar(identifier: .gregorian)
        let start = CalendarPrefs.weekStart(of: selectedDate, mondayFirst: settings.weekStartsMonday)
        return (0..<7).compactMap { cal.date(byAdding: .day, value: $0, to: start) }
    }

    /// How many day-columns fit across the screen. Seven left ~6 letters a
    /// line, so titles broke mid-word ("ceremo/ny"); the week now scrolls
    /// sideways with about three days in view and a sliver of the next, so
    /// titles read across like the Day view's (Gil, 2026-10-10).
    /// Sideways, or when chosen in Settings, all seven fit with no scrolling.
    /// "Sideways" is judged by the view's own shape: the size class did not
    /// reach in here through the Month/Week/Day pager (the week stayed on
    /// three days in landscape, seen in the simulator).
    private func daysInView(_ size: CGSize) -> CGFloat {
        settings.weekFitsAll || size.width > size.height ? 7 : 3.2
    }
    /// How far the day columns are scrolled — the header strip follows it.
    @State private var scrollX: CGFloat = 0

    var body: some View {
        GeometryReader { outer in
            let colW = max(daysInView(outer.size) >= 7 ? 30 : 64,
                           (outer.size.width - labelWidth) / daysInView(outer.size))
            VStack(spacing: 0) {
                // Day header strip — not a scroll view of its own (two can't be
                // kept in step before iOS 17): it is moved by the columns' offset.
                HStack(spacing: 0) {
                    Spacer().frame(width: labelWidth)
                    HStack(spacing: 0) {
                        ForEach(weekDays, id: \.self) { day in
                            WeekDayHeader(
                                day: day,
                                isSelected: Calendar.current.isDate(day, inSameDayAs: selectedDate),
                                isToday: Calendar.current.isDateInToday(day),
                                holidays: holidaysForDay(day),
                                occasions: occasions.filter { $0.date == ISO8601DateFormatter.yyyyMMdd.string(from: day) }
                            )
                            .frame(width: colW)
                            .contentShape(Rectangle())
                            .onTapGesture {
                                selectedDate = day
                                onDateSelected?(day)
                            }
                        }
                    }
                    .offset(x: scrollX)
                    .frame(width: max(0, outer.size.width - labelWidth), alignment: .leading)
                    .clipped()
                }
                .frame(height: 56)
                .background(Color(.systemBackground))

                Divider()

                // Scrollable timeline: up and down for the hours, sideways for the days
                ScrollViewReader { proxy in
                    ScrollView(.vertical, showsIndicators: false) {
                        Color.clear.frame(height: 0).id("top")
                        HStack(alignment: .top, spacing: 0) {
                            // Time label column — stays put while the days scroll
                            VStack(spacing: 0) {
                                ForEach(0..<24, id: \.self) { h in
                                    Text(hourLabel(h))
                                        .font(.system(size: 9))
                                        .foregroundColor(.secondary)
                                        .frame(width: labelWidth, height: hourHeight, alignment: .topTrailing)
                                        .padding(.trailing, 3)
                                }
                            }

                            ScrollViewReader { days in
                                ScrollView(.horizontal, showsIndicators: false) {
                                    HStack(spacing: 0) {
                                        // Reads the real scroll view's offset: SwiftUI's
                                        // geometry readers did not update while this was
                                        // nested in the vertical scroll, and the header sat
                                        // on Sun–Tue over Thu–Sat columns (seen in the
                                        // simulator, 2026-10-10).
                                        ScrollOffsetReader { x in scrollX = -x }
                                            .frame(width: 0, height: 0)
                                        ForEach(Array(weekDays.enumerated()), id: \.offset) { i, day in
                                            WeekDayColumn(
                                                day: day, popped: $popped, onOpen: { selected = $0 },
                                                events: eventsForDay(day),
                                                holyWindows: holyWindows.filter { $0.overlaps(day: day) },
                                                now: now,
                                                hourHeight: hourHeight,
                                                showLeftBorder: i > 0
                                            )
                                            .frame(width: colW)
                                            .id(i)
                                        }
                                    }
                                }
                                .onAppear { showSelected(days) }
                                .onChange(of: selectedDate) { _ in showSelected(days) }
                            }
                        }
                        // the 24-hour canvas, seen through a window on the shown hours
                        .frame(height: hourHeight * 24, alignment: .top)
                        .offset(y: -CGFloat(span.0) * hourHeight)
                        .frame(height: CGFloat(span.1 - span.0) * hourHeight, alignment: .top)
                        .clipped()
                        .padding(.top, 4)
                    }
                    .background(GeometryReader { g in
                        Color.clear
                            .onAppear { viewportH = g.size.height }
                            .onChange(of: g.size.height) { h in viewportH = h }
                    })
                    .onChange(of: settings.hoursFrom) { _ in proxy.scrollTo("top", anchor: .top) }
                    .onAppear { proxy.scrollTo("top", anchor: .top) }
                    .onChange(of: selectedDate) { _ in proxy.scrollTo("top", anchor: .top); popped = nil }
                    .sheet(item: $selected) { ev in
                        EventDetailView(event: ev, onDismiss: { api.requestRefresh() })
                    }
                }
            }
        }
        .onReceive(timer) { d in now = d }
    }

    /// The selected day in view, with the day before it for context.
    private func showSelected(_ days: ScrollViewProxy) {
        guard let i = weekDays.firstIndex(where: { Calendar.current.isDate($0, inSameDayAs: selectedDate) })
        else { return }
        DispatchQueue.main.async { days.scrollTo(max(0, i - 1), anchor: .leading) }
    }

    private func eventsForDay(_ date: Date) -> [CalendarEvent] {
        let d = ISO8601DateFormatter.yyyyMMdd.string(from: date)
        return events.filter { $0.date == d }
    }

    private func holidaysForDay(_ date: Date) -> [Holiday] {
        let d = ISO8601DateFormatter.yyyyMMdd.string(from: date)
        return holidays.filter { $0.spans(d) }
    }

    private func hourLabel(_ h: Int) -> String {
        CalendarPrefs.hourLabel(h, clock24: settings.clock24)
    }
}

/// The horizontal offset of the UIScrollView this sits inside, reported on
/// every scroll (key-value observation of `contentOffset`).
private struct ScrollOffsetReader: UIViewRepresentable {
    var onChange: (CGFloat) -> Void

    func makeUIView(context: Context) -> UIView {
        let v = UIView(frame: .zero)
        v.isUserInteractionEnabled = false
        DispatchQueue.main.async { context.coordinator.attach(from: v) }
        return v
    }

    func updateUIView(_ uiView: UIView, context: Context) {
        context.coordinator.onChange = onChange
    }

    func makeCoordinator() -> Coordinator { Coordinator(onChange: onChange) }

    final class Coordinator {
        var onChange: (CGFloat) -> Void
        private var watch: NSKeyValueObservation?
        init(onChange: @escaping (CGFloat) -> Void) { self.onChange = onChange }

        /// The nearest enclosing scroll view — the horizontal one, since the
        /// vertical one is further out.
        func attach(from view: UIView) {
            var sv = view.superview
            while let s = sv, !(s is UIScrollView) { sv = s.superview }
            guard let scroll = sv as? UIScrollView else { return }
            watch = scroll.observe(\.contentOffset, options: [.initial, .new]) { [weak self] s, _ in
                let x = s.contentOffset.x
                DispatchQueue.main.async { self?.onChange(x) }
            }
        }
    }
}

// MARK: - Day header cell

private struct WeekDayHeader: View {
    @EnvironmentObject var settings: AppSettings
    var day: Date
    var isSelected: Bool
    var isToday: Bool
    var holidays: [Holiday] = []
    var occasions: [OccasionBanner] = []

    private var label: String {
        let f = DateFormatter()
        f.dateFormat = "EEE"
        return f.string(from: day).uppercased()
    }
    private var dayNum: String { "\(Calendar.current.component(.day, from: day))" }

    var body: some View {
        VStack(spacing: 2) {
            Text(label)
                .font(.system(size: settings.fontWeek - 4))
                .foregroundColor(.secondary)
            ZStack {
                if isToday {
                    Circle().fill(settings.accentColor)
                        .frame(width: settings.fontWeek * 2, height: settings.fontWeek * 2)
                } else if isSelected {
                    Circle().stroke(settings.accentColor, lineWidth: 1.5)
                        .frame(width: settings.fontWeek * 2, height: settings.fontWeek * 2)
                }
                Text(dayNum)
                    .font(.system(size: settings.fontWeek + 2, weight: isToday ? .bold : .regular))
                    .foregroundColor(isToday ? Color.onColor(hex: settings.accentColorHex) : .primary)
            }
            if settings.hebrewDisplayMode != "english" {
                Text(HebrewDateFormatting.string(for: day))
                    .font(.system(size: 8))
                    .foregroundColor(.secondary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.5)
            }
            if let first = holidays.first {
                Text(first.nameEn)
                    .font(.system(size: 8, weight: .semibold))
                    .foregroundColor(first.color)
                    .lineLimit(1)
                    .minimumScaleFactor(0.5)
            } else if let o = occasions.first {
                HStack(spacing: 2) { Ico(o.icon, size: 8); Text(o.title) }
                    .font(.system(size: 8, weight: .semibold))
                    .foregroundColor(o.uiColor)
                    .lineLimit(1)
                    .minimumScaleFactor(0.5)
            }
        }
    }
}

// MARK: - Single day column with events

private struct WeekDayColumn: View {
    @EnvironmentObject var settings: AppSettings
    var day: Date
    @Binding var popped: Int?
    var onOpen: (CalendarEvent) -> Void
    var events: [CalendarEvent]
    var holyWindows: [HolyWindow] = []
    var now: Date
    var hourHeight: CGFloat
    var showLeftBorder: Bool

    private var isToday: Bool { Calendar.current.isDateInToday(day) }

    var body: some View {
        ZStack(alignment: .topLeading) {
            // Today background tint
            if isToday {
                settings.accentColor.opacity(0.06)
            }

            // Horizontal hour grid lines
            VStack(spacing: 0) {
                ForEach(0..<24, id: \.self) { _ in
                    Rectangle()
                        .fill(Color(.separator).opacity(0.5))
                        .frame(height: 0.5)
                    Spacer().frame(height: hourHeight - 0.5)
                }
            }

            // Shabbat / yom tov wash, under the events.
            if !holyWindows.isEmpty {
                HolyTint(day: day, windows: holyWindows, hourHeight: hourHeight)
            }

            // Events + redline drawn relative to column width
            Color.clear
                .overlay(
                    GeometryReader { geo in
                        // Event blocks — binder stacking for overlaps (see EventStacking)
                        let colW = geo.size.width - 3
                        let titleLine: CGFloat = settings.fontWeek * 1.3 + 4
                        let band: (StackedEvent) -> CGFloat = { (_: StackedEvent) -> CGFloat in titleLine }
                        let items = EventStacking.clearTitles(
                            EventStacking.layout(events, hourHeight: hourHeight, minHeight: 18),
                            band: band, minHeight: 18)
                        let poppedCluster = items.first { $0.id == popped }?.cluster
                        ForEach(items) { it in
                            let isPopped = popped == it.id
                            let inset = isPopped ? 0 : EventStacking.inset(depth: it.depth, size: it.stackSize, step: 7, readStep: 60, width: colW)
                            let strip = isPopped ? 0 : EventStacking.titleStrip(it, in: items, band: band,
                                                                                step: 7, readStep: 60, width: colW)
                            WeekEventBlock(event: it.event, height: it.height, strip: strip)
                                .frame(width: max(colW - inset, 24), height: it.height)
                                .modifier(OwnerEdge(event: it.event, width: 3, radius: 3))
                                .modifier(StackedCardModifier(stacked: it.stackSize > 1, popped: isPopped,
                                                              dimmed: poppedCluster == it.cluster && !isPopped, radius: 3))
                                .offset(x: 1 + inset, y: it.top)
                                .zIndex(isPopped ? 1000 : Double(it.depth))
                                .onTapGesture {
                                    if it.stackSize > 1 && !isPopped { popped = it.id } else { onOpen(it.event) }
                                }
                        }

                        // Shabbat / yom tov lines: above the events, below
                        // the now-line, and transparent to taps.
                        if !holyWindows.isEmpty {
                            HolyLines(day: day, windows: holyWindows, hourHeight: hourHeight,
                                      fontSize: max(settings.fontWeek - 5, 7))
                                .frame(width: geo.size.width, height: geo.size.height)
                        }

                        // Current time line (today only) — follows the accent
                        // color, same convention as the Mac app.
                        if isToday {
                            let ny = nowY
                            // Circle marker
                            Circle()
                                .fill(settings.accentColor)
                                .frame(width: 8, height: 8)
                                .offset(x: -4, y: ny - 4)
                            // Horizontal line
                            Rectangle()
                                .fill(settings.accentColor)
                                .frame(width: geo.size.width + 4, height: 2)
                                .offset(x: -4, y: ny - 1)
                        }
                    }
                )
        }
        .frame(maxWidth: .infinity)
        .frame(height: hourHeight * 24)
        .contentShape(Rectangle())
        .onTapGesture { popped = nil }
        .overlay(
            Rectangle()
                .fill(showLeftBorder ? Color(.separator) : Color.clear)
                .frame(width: 0.5),
            alignment: .leading
        )
    }

    private var nowY: CGFloat {
        let comps = Calendar.current.dateComponents([.hour, .minute], from: now)
        return CGFloat((comps.hour ?? 0) * 60 + (comps.minute ?? 0)) / 60 * hourHeight
    }

    private func eventPos(_ ev: CalendarEvent) -> (CGFloat, CGFloat)? {
        let s = ev.startTime.split(separator: ":").compactMap { Int($0) }
        let e = ev.endTime.split(separator: ":").compactMap { Int($0) }
        guard s.count == 2, e.count == 2 else { return nil }
        let start = s[0] * 60 + s[1]
        let end   = e[0] * 60 + e[1]
        guard end > start else { return nil }
        let top    = CGFloat(start) / 60 * hourHeight
        let height = max(CGFloat(end - start) / 60 * hourHeight, 18)
        return (top, height)
    }
}

// MARK: - Event block

private struct WeekEventBlock: View {
    @EnvironmentObject var settings: AppSettings
    var event: CalendarEvent
    var height: CGFloat
    var strip: CGFloat = 0

    var body: some View {
        let fillColor = Color(hex: event.color) ?? settings.accentColor
        RoundedRectangle(cornerRadius: 3)
            .fill(fillColor)
            .overlay(alignment: .topLeading) {
                // Readable at arm's length (Gil, 2026-10-10: "way too small"):
                // the Week size itself, not two points under it, and as many
                // lines as the block is tall — a seven-column week leaves a
                // word or two per line, so a one- or two-line cap cut titles.
                GeometryReader { geo in
                    let room = (strip > 0 ? min(strip, geo.size.width) : geo.size.width) - 6
                    let size = Self.fitting(event.ownerPrefix + event.title, base: settings.fontWeek, width: room)
                    IconTitle(title: event.ownerPrefix + event.title, icons: event.icons, size: size)
                        .font(.system(size: size, weight: .semibold))
                        .foregroundColor(Color.onColor(hex: event.color.isEmpty ? settings.accentColorHex : event.color))
                        .lineLimit(max(1, Int((height - 4) / (size * 1.2))))
                        .padding(.horizontal, 3).padding(.vertical, 2)
                        .frame(maxWidth: strip > 0 ? strip : nil, alignment: .leading)
                }
            }
    }
}

extension WeekEventBlock {
    /// The Week size, unless the title's longest word would not fit the
    /// column at it — then just small enough that it does (never under three
    /// points less), so a word wraps whole instead of "ceremo / ny".
    static func fitting(_ title: String, base: Double, width: CGFloat) -> CGFloat {
        let font = UIFont.systemFont(ofSize: base, weight: .semibold)
        let longest = title.split(whereSeparator: { $0 == " " || $0 == "-" })
            .map { (String($0) as NSString).size(withAttributes: [.font: font]).width }
            .max() ?? 0
        guard longest > width, width > 0 else { return base }
        return max(base - 3, floor(base * width / longest * 10) / 10)
    }
}

// MARK: - Shabbat / yom tov lines

/// The yellow lines at the exact minute Shabbat or yom tov begins (candle
/// lighting) and ends (nightfall), and a faint wash between them — on the
/// Week and Day grids (Gil, 2026-09-24: "important because the exact minute is
/// important. mark in yellow").
///
/// The minutes come from the Mac (`HolyWindow`, `GET /observance/windows`),
/// the same candle lighting and tzeit the calendar skips series by; nothing
/// here computes a sun time. A window whose boundary the Mac could not compute
/// never arrives, so no line is ever drawn at a guessed minute.
///
/// Placed to the SECOND: `y` is seconds since this day's local midnight, so a
/// candle lighting at 18:12:37 sits 37/60 of a minute below 18:12.
enum HolyTimes {
    /// A true yellow — distinct from the amber default accent the now-line
    /// uses — and a deeper one in light mode, where bright yellow on white all
    /// but disappears (the Mac draws the same pair, `holy_times.py`).
    static let yellow = Color(UIColor { traits in
        traits.userInterfaceStyle == .dark
            ? UIColor(red: 1.0, green: 0.839, blue: 0.039, alpha: 1)    // #FFD60A
            : UIColor(red: 0.878, green: 0.690, blue: 0.0, alpha: 1)    // #E0B000
    })

    struct Mark: Identifiable {
        let id: String
        let y: CGFloat
        let text: String
        let short: String
        let isStart: Bool
    }

    /// Seconds since *day*'s local midnight, as a y offset, clamped to the day.
    static func y(_ when: Date, on day: Date, hourHeight: CGFloat) -> CGFloat {
        let d0 = Calendar.current.startOfDay(for: day)
        let secs = min(max(when.timeIntervalSince(d0), 0), 24 * 3600)
        return CGFloat(secs / 3600) * hourHeight
    }

    /// The lines that fall on *day*.
    static func marks(day: Date, windows: [HolyWindow], hourHeight: CGFloat) -> [Mark] {
        let cal = Calendar.current
        var out: [Mark] = []
        for w in windows {
            if let s = w.startDate, cal.isDate(s, inSameDayAs: day), let text = w.startText {
                out.append(Mark(id: "s" + w.start, y: y(s, on: day, hourHeight: hourHeight),
                                text: text, short: String(text.suffix(5)), isStart: true))
            }
            if let e = w.endDate, cal.isDate(e, inSameDayAs: day), let text = w.endText {
                out.append(Mark(id: "e" + w.end, y: y(e, on: day, hourHeight: hourHeight),
                                text: text, short: String(text.suffix(5)), isStart: false))
            }
        }
        return out
    }

    /// The (top, height) of the holy part of *day*, for the wash.
    static func spans(day: Date, windows: [HolyWindow], hourHeight: CGFloat) -> [(top: CGFloat, height: CGFloat)] {
        windows.compactMap { w in
            guard let s = w.startDate, let e = w.endDate, w.overlaps(day: day) else { return nil }
            let top = y(s, on: day, hourHeight: hourHeight)
            let bottom = y(e, on: day, hourHeight: hourHeight)
            return bottom > top ? (top, bottom - top) : nil
        }
    }
}

/// The wash — drawn UNDER the events, and never hit-testable.
struct HolyTint: View {
    var day: Date
    var windows: [HolyWindow]
    var hourHeight: CGFloat

    var body: some View {
        ZStack(alignment: .topLeading) {
            ForEach(Array(HolyTimes.spans(day: day, windows: windows, hourHeight: hourHeight).enumerated()),
                    id: \.offset) { _, span in
                HolyTimes.yellow.opacity(0.09)
                    .frame(height: span.height)
                    .offset(y: span.top)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .allowsHitTesting(false)
    }
}

/// The lines and their labels — drawn ABOVE the events, but taps go through
/// to the event underneath (`allowsHitTesting(false)`).
struct HolyLines: View {
    var day: Date
    var windows: [HolyWindow]
    var hourHeight: CGFloat
    var fontSize: CGFloat = 9

    var body: some View {
        ZStack(alignment: .topTrailing) {
            ForEach(HolyTimes.marks(day: day, windows: windows, hourHeight: hourHeight)) { m in
                HolyTimes.yellow
                    .frame(height: 1.5)
                    .shadow(color: .black.opacity(0.35), radius: 0.5)
                    .offset(y: m.y - 0.75)
                // The label sits on the holy side of its line: below a start,
                // above an end. Falls back to just the time in a narrow
                // week column rather than squeezing the name illegible.
                ViewThatFits(in: .horizontal) {
                    label(m.text)
                    label(m.short)
                }
                .offset(y: m.isStart ? m.y + 1 : m.y - (fontSize + 5))
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topTrailing)
        .allowsHitTesting(false)
        .accessibilityElement(children: .combine)
    }

    private func label(_ s: String) -> some View {
        Text(s)
            .font(.system(size: fontSize, weight: .bold))
            .foregroundColor(Color(white: 0.1))
            .lineLimit(1)
            .fixedSize()
            .padding(.horizontal, 3)
            .frame(height: fontSize + 4)
            .background(HolyTimes.yellow)
            .clipShape(RoundedRectangle(cornerRadius: 3))
    }
}
