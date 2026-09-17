import SwiftUI

/// Where the rest of the app asks the calendar to go somewhere.
///
/// The calendar tab owns its own month/week/day state now that it is a feature
/// rather than a slab of ContentView — but two things outside it still have to
/// steer it: a tapped reminder ("show me that event's day") and the app's
/// foreground/poll cycle ("the Mac changed something, re-read the month"). This
/// is that seam, and it is deliberately tiny: a date to show and a token to
/// bump. Anything richer would put calendar logic back in the shell, which is
/// what the Feature convention exists to stop.
@MainActor
final class CalendarNavigator: ObservableObject {
    static let shared = CalendarNavigator()

    /// The day the week/day views are showing, and what a new event defaults to.
    @Published var selectedDate = Date()
    /// The month the grid is showing. Usually follows `selectedDate`; they part
    /// company while you page through months without picking a day.
    @Published var viewedDate = Date()
    /// Bumped to mean "re-read the month from the Mac". A token rather than a
    /// method call because the caller is a background loop and the reader is a
    /// SwiftUI view that may not exist yet.
    @Published private(set) var reloadToken = 0

    private init() {}

    /// Bring a specific day into view (a reminder tap, a search result).
    func show(_ date: Date) {
        selectedDate = date
        viewedDate = date
        reload()
    }

    func reload() { reloadToken &+= 1 }
}

/// The Calendar feature's tab: month / week / day, the create button and the
/// search sheet that opens from its toolbar.
///
/// This was `ContentView.calendarContent` plus half of ContentView's state. It
/// moved here whole so the shell holds nothing calendar-shaped: the shell now
/// only knows there is a feature called "calendar" and asks it for a view.
struct CalendarTabView: View {
    @EnvironmentObject var api: APIClient
    @EnvironmentObject var settings: AppSettings
    @ObservedObject private var nav = CalendarNavigator.shared

    @State private var calendarView: CalendarMode = .month
    @State private var monthEvents: [CalendarEvent] = []
    @State private var monthHolidays: [Holiday] = []
    @State private var loadingMonth = false
    @State private var showCreateSheet = false
    @State private var showSearch = false

    enum CalendarMode { case month, week, day }

    var body: some View {
        NavigationView {
                    VStack(spacing: 0) {

                        Picker("View", selection: $calendarView) {
                            Text("Month").tag(CalendarMode.month)
                            Text("Week").tag(CalendarMode.week)
                            Text("Day").tag(CalendarMode.day)
                        }
                        .pickerStyle(.segmented)
                        .padding(.horizontal)
                        .padding(.vertical, 8)

                        Divider()

                        TabView(selection: $calendarView) {

                            // ── Month ──
                            VStack(spacing: 0) {
                                HStack {
                                    Button { shiftMonth(-1) } label: {
                                        Image(systemName: "chevron.left")
                                    }
                                    Spacer()
                                    Text(monthTitle).font(.headline)
                                    Spacer()
                                    Button { shiftMonth(1) } label: {
                                        Image(systemName: "chevron.right")
                                    }
                                }
                                .padding(.horizontal)
                                .padding(.vertical, 8)

                                MonthGridView(
                                    year: Calendar.current.component(.year, from: nav.viewedDate),
                                    month: Calendar.current.component(.month, from: nav.viewedDate),
                                    selectedDate: $nav.selectedDate,
                                    events: monthEvents,
                                    holidays: monthHolidays,
                                    onDateSelected: { date in nav.viewedDate = date }
                                )
                                Spacer()
                            }
                            .tag(CalendarMode.month)
                            .task { await loadMonth() }
                            .onChange(of: nav.viewedDate) { _ in Task { await loadMonth() } }
                            .onAppear { nav.viewedDate = nav.selectedDate }
                            // Vertical swipe to move a month, in addition to the
                            // chevron buttons. `simultaneousGesture` (rather than
                            // `gesture`) so it doesn't steal the horizontal swipe
                            // the outer page TabView uses to switch Month/Week/Day.
                            .simultaneousGesture(
                                DragGesture(minimumDistance: 24)
                                    .onEnded { value in
                                        let h = value.translation.height
                                        let w = value.translation.width
                                        guard abs(h) > abs(w) * 1.5, abs(h) > 40 else { return }
                                        withAnimation { shiftMonth(h < 0 ? 1 : -1) }
                                    }
                            )

                            // ── Week ──
                            VStack(spacing: 0) {
                                HStack {
                                    Button { shiftWeek(-1) } label: {
                                        Image(systemName: "chevron.left")
                                    }
                                    Spacer()
                                    Text(weekTitle).font(.headline)
                                    Spacer()
                                    Button { shiftWeek(1) } label: {
                                        Image(systemName: "chevron.right")
                                    }
                                }
                                .padding(.horizontal)
                                .padding(.vertical, 8)

                                WeekView(
                                    selectedDate: $nav.selectedDate,
                                    events: monthEvents,
                                    holidays: monthHolidays,
                                    onDateSelected: { date in
                                        nav.selectedDate = date
                                        nav.viewedDate = date
                                        Task { await loadMonth() }
                                    }
                                )
                            }
                            .tag(CalendarMode.week)
                            .onAppear {
                                nav.viewedDate = nav.selectedDate
                                Task { await loadMonth() }
                            }

                            // ── Day ──
                            VStack(spacing: 0) {
                                HStack {
                                    Button { shiftDay(-1) } label: {
                                        Image(systemName: "chevron.left")
                                    }
                                    Spacer()
                                    Text(dayTitle).font(.headline)
                                    Spacer()
                                    Button { shiftDay(1) } label: {
                                        Image(systemName: "chevron.right")
                                    }
                                }
                                .padding(.horizontal)
                                .padding(.vertical, 8)

                                DayView(date: nav.selectedDate)
                            }
                            .tag(CalendarMode.day)
                            .onAppear { nav.viewedDate = nav.selectedDate }

                        }
                        .tabViewStyle(.page(indexDisplayMode: .never))

                        Spacer(minLength: 0)
                    }
                    .navigationTitle("Calendar")
                    .navigationBarTitleDisplayMode(.inline)
                    .toolbar {
                        ToolbarItem(placement: .navigationBarLeading) {
                            Button { showSearch = true } label: {
                                Image(systemName: "magnifyingglass")
                            }
                            .accessibilityLabel("Search")
                        }
                        ToolbarItem(placement: .navigationBarTrailing) {
                            Button("Today") {
                                nav.show(Date())
                            }
                        }
                    }
                    .overlay(alignment: .bottom) {
                        HStack(spacing: 20) {
                            VoiceButton(onRefresh: { refresh in
                                if refresh == "events" || refresh == "both" {
                                    Task { await loadMonth() }
                                }
                            })

                            Button {
                                showCreateSheet = true
                            } label: {
                                Image(systemName: "plus")
                                    .font(.system(size: 24, weight: .bold))
                                    .foregroundColor(Color.onColor(hex: settings.accentColorHex))
                                    .frame(width: 60, height: 60)
                                    .background(settings.accentColor)
                                    .clipShape(Circle())
                                    .shadow(radius: 4)
                            }
                        }
                        .padding(.bottom, 24)
                    }
                }
        // Something outside the calendar moved the month on (a reminder tap, the
        // foreground sync, the /changes poll). The view may have been off screen
        // when it happened, so this is where that lands rather than at the call site.
        .onChange(of: nav.reloadToken) { _ in Task { await loadMonth() } }
        .sheet(isPresented: $showCreateSheet) {
            let year    = Calendar.current.component(.year,  from: nav.selectedDate)
            let month   = Calendar.current.component(.month, from: nav.selectedDate)
            let day     = Calendar.current.component(.day,   from: nav.selectedDate)
            let dateStr = String(format: "%04d-%02d-%02d", year, month, day)

            EventDetailView(
                event: CalendarEvent(
                    id: 0, title: "", date: dateStr,
                    startTime: "10:00", endTime: "11:00",
                    attendees: "", location: "",
                    description: "", color: settings.accentColorHex,
                    recurrence: "", recurrenceEnd: ""
                ),
                isNew: true,
                onDismiss: { Task { await loadMonth() } }
            )
        }
        .sheet(isPresented: $showSearch) {
            SearchView(
                onOpenEvent: { event in
                    // Navigate the calendar to the event's day, in whatever
                    // month/week/day mode is already showing. `show` drives the
                    // same state every other navigation (Today button, grid
                    // taps, swipes) drives.
                    if let d = DateFormatter.isoDay.date(from: event.date) {
                        nav.show(d)
                    }
                },
                // A search result can be a task, and the task list is a
                // different feature — the router is how one hands off to
                // another without either learning the other's internals.
                onOpenTodo: { _ in FeatureRouter.shared.show("tasks") }
            )
        }
    }

    // MARK: - Helpers

    private var monthTitle: String {
        let f = DateFormatter()
        f.dateFormat = "MMMM yyyy"
        return f.string(from: nav.viewedDate)
    }

    private var weekTitle: String {
        var cal = Calendar(identifier: .gregorian)
        cal.firstWeekday = 1
        let weekday = cal.component(.weekday, from: nav.selectedDate) - 1
        guard let sunday   = cal.date(byAdding: .day, value: -weekday,    to: nav.selectedDate),
              let saturday = cal.date(byAdding: .day, value: 6 - weekday, to: nav.selectedDate) else { return "" }
        let f = DateFormatter()
        f.dateFormat = "MMM d"
        let year = Calendar.current.component(.year, from: sunday)
        return "\(f.string(from: sunday)) – \(f.string(from: saturday)), \(year)"
    }

    private var dayTitle: String {
        let f = DateFormatter()
        f.dateFormat = "EEEE, MMM d, yyyy"
        return f.string(from: nav.selectedDate)
    }

    private func shiftMonth(_ delta: Int) {
        guard let d = Calendar.current.date(byAdding: .month, value: delta, to: nav.viewedDate) else { return }
        nav.viewedDate = d
    }

    private func shiftWeek(_ delta: Int) {
        guard let d = Calendar.current.date(byAdding: .day, value: delta * 7, to: nav.selectedDate) else { return }
        nav.selectedDate = d
        nav.viewedDate = d
        Task { await loadMonth() }
    }

    private func shiftDay(_ delta: Int) {
        guard let d = Calendar.current.date(byAdding: .day, value: delta, to: nav.selectedDate) else { return }
        nav.selectedDate = d
        nav.viewedDate = d
        Task { await loadMonth() }
    }

    private func loadMonth() async {
        let year  = Calendar.current.component(.year,  from: nav.viewedDate)
        let month = Calendar.current.component(.month, from: nav.viewedDate)

        let cal = Calendar.current
        let start = cal.date(from: DateComponents(year: year, month: month, day: 1)) ?? nav.viewedDate
        let end = cal.date(byAdding: DateComponents(month: 1, day: -1), to: start) ?? start
        let showHolidays = settings.showHolidays
        let israel = settings.israelHolidays

        // Draw the cache first, then let the network correct it.
        //
        // These two calls fall back to the cache when the Mac is unreachable —
        // but only after awaiting it, so every month navigation showed an empty
        // grid for as long as the request took to give up, and then filled in
        // from a cache that had been on disk the whole time. Painting it up
        // front costs nothing and is what "instant offline" actually means; the
        // await below then either replaces it with the same rows (online) or
        // with itself (offline, and now immediately, thanks to the client's
        // offline circuit breaker).
        let startStr = ISO8601DateFormatter.yyyyMMdd.string(from: start)
        let endStr = ISO8601DateFormatter.yyyyMMdd.string(from: end)
        let cachedEvents = LocalStore.shared.eventsForMonth(year, month)
        if !cachedEvents.isEmpty { monthEvents = cachedEvents }
        if showHolidays {
            let cachedHolidays = LocalStore.shared.holidaysBetween(startStr, endStr)
            if !cachedHolidays.isEmpty { monthHolidays = cachedHolidays }
        } else {
            monthHolidays = []
        }

        loadingMonth = true
        // Independent requests — run concurrently instead of paying the sum
        // of both latencies on every month navigation.
        async let eventsResult: [CalendarEvent] = (try? await api.eventsForMonth(year: year, month: month)) ?? []
        async let holidaysResult: [Holiday] = fetchHolidays(showHolidays: showHolidays, start: start, end: end, israel: israel)

        monthEvents = await eventsResult
        loadingMonth = false
        let fresh = await holidaysResult
        // An empty answer from an unreachable Mac must not wipe the cached
        // list off the screen; showHolidays == false already cleared it above.
        if showHolidays == false || !fresh.isEmpty || monthHolidays.isEmpty {
            monthHolidays = fresh
        }
    }

    private func fetchHolidays(showHolidays: Bool, start: Date, end: Date, israel: Bool) async -> [Holiday] {
        guard showHolidays else { return [] }
        return (try? await api.holidays(start: start, end: end, israel: israel)) ?? []
    }
}
