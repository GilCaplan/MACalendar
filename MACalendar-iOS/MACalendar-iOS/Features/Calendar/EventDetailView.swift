import SwiftUI
import UIKit

struct EventDetailView: View {
    @EnvironmentObject var api: APIClient
    var event: CalendarEvent
    var isNew: Bool = false
    var onDismiss: (() -> Void)?

    @State private var title: String
    @State private var date: String
    @State private var startTime: String
    @State private var endTime: String
    @State private var location: String
    @State private var attendees: String
    @State private var notes: String
    /// Reminder override: -1 = Inherit (no stored override), 0 = None,
    /// N = minutes before start. Mirrors reminder_minutes, where "inherit"
    /// is the column being NULL.
    @State private var reminderChoice: Int
    @State private var saving = false
    /// The SERIES rule. Separate from the instance fields above because
    /// changing it edits every instance, not this row: Save writes the other
    /// fields to this event and, when the rule moved, the rule to the whole
    /// series (PATCH /events/<id>/series) — the same split the Mac makes.
    @State private var recurrence: String
    @State private var recurrenceEnd: String
    /// Set once the end has been defaulted for something newly made to
    /// repeat, so switching cadence afterwards never overrides a chosen Never.
    @State private var endDefaulted = false
    @State private var seriesCount = 0
    @State private var seriesBusy = false
    @State private var confirmSeriesDelete = false
    @State private var confirmDelete = false
    @State private var errorMessage: String?
    @State private var sharing = false
    @State private var shareFile: ShareFile?
    /// How long an event lasts when only its start is set — Settings › Events,
    /// or this event's category's own length (DEVQA Q51). Starts from the
    /// cached value; a new event's is refined from the Mac once it has a title.
    @State private var lengthMinutes: Int
    @Environment(\.dismiss) var dismiss

    /// ICS-subscribed events are always read-only (no write endpoint behind
    /// a webcal link). Outlook events read-only-when-two-way-off aren't
    /// knowable client-side without an extra fetch, but the server enforces
    /// that too (PATCH/DELETE /events/<id> return 403) — save()/deleteEvent()
    /// surface that failure instead of silently swallowing it.
    private var isReadOnly: Bool { !isNew && event.isReadOnly }

    init(event: CalendarEvent, isNew: Bool = false, onDismiss: (() -> Void)? = nil) {
        self.event = event
        self.isNew = isNew
        self.onDismiss = onDismiss
        _title     = State(initialValue: event.title)
        _recurrence    = State(initialValue: event.recurrence)
        _recurrenceEnd = State(initialValue: event.recurrenceEnd)
        _date      = State(initialValue: event.date)
        _startTime = State(initialValue: event.startTime)
        _endTime   = State(initialValue: event.endTime)
        _location  = State(initialValue: event.location)
        _attendees = State(initialValue: event.attendees)
        _notes     = State(initialValue: event.description)
        _reminderChoice = State(initialValue: event.reminderMinutes ?? -1)
        _lengthMinutes = State(initialValue: EventDefaults.length(for: event.category))
    }

    // MARK: - Computed helpers

    /// Human reading of the server's notify_suppressed_reason — the effective
    /// state when a lead time exists but no reminder will fire. The server is
    /// the policy brain; this only translates its verdict.
    private var suppressionNote: String? {
        guard let r = event.notifySuppressedReason, !r.isEmpty else { return nil }
        if r == "shabbat" { return "Held for Shabbat" }
        if r.hasPrefix("yom_tov:") {
            let name = String(r.dropFirst("yom_tov:".count))
            return name.isEmpty ? "Held for yom tov" : "Held for \(name)"
        }
        if r == "clamped_past_start" {
            return "Skipped — the reminder would have landed during Shabbat or chag"
        }
        return "Reminder held (\(r))"
    }

    /// Returns e.g. "Monday, Apr 14, 2026" or nil if the date string is invalid.
    private var parsedDayLabel: String? {
        let fmt = DateFormatter()
        fmt.dateFormat = "yyyy-MM-dd"
        guard let d = fmt.date(from: date) else { return nil }
        let out = DateFormatter()
        out.dateFormat = "EEEE, MMM d, yyyy"
        return out.string(from: d)
    }

    // MARK: - Body

    var body: some View {
        NavigationStack {
            Form {
                if isReadOnly {
                    Section {
                        Label("Synced from a subscribed calendar — read-only.", systemImage: "link")
                            .font(.caption)
                            .foregroundColor(.secondary)
                    }
                }
                Section(header: Text("Event")) {
                    TextField("Title", text: $title)
                        .onSubmit { if !saving && !title.isEmpty { save() } }
                        // Restarted on every keystroke, so only the pause
                        // after typing reaches the Mac.
                        .task(id: title) { await refineLength(for: title) }
                    if let badge = RepeatHint.badge(for: event) {
                        Label(badge, systemImage: "repeat")
                            .font(.caption)
                            .foregroundColor(.secondary)
                    }

                    VStack(alignment: .leading, spacing: 2) {
                        TextField("Date (YYYY-MM-DD)", text: $date)
                            .keyboardType(.numbersAndPunctuation)
                            .onSubmit { if !saving && !title.isEmpty { save() } }
                        if let label = parsedDayLabel {
                            Text(label)
                                .font(.caption)
                                .foregroundColor(.secondary)
                        }
                    }

                    HStack {
                        TextField("Start (HH:MM)", text: $startTime)
                            .keyboardType(.numbersAndPunctuation)
                            .onChange(of: startTime) { newVal in
                                autoUpdateEndTime(from: newVal)
                            }
                            .onSubmit { if !saving && !title.isEmpty { save() } }
                        Text("–")
                        TextField("End (HH:MM)", text: $endTime)
                            .keyboardType(.numbersAndPunctuation)
                            .onSubmit { if !saving && !title.isEmpty { save() } }
                    }
                }
                Section(header: Text("Details")) {
                    TextField("Location", text: $location)
                        .onSubmit { if !saving && !title.isEmpty { save() } }
                    TextField("Attendees", text: $attendees)
                        .onSubmit { if !saving && !title.isEmpty { save() } }
                }
                Section {
                    Picker("Reminder", selection: $reminderChoice) {
                        Text("Inherit").tag(-1)
                        Text("None").tag(0)
                        ForEach([5, 10, 15, 30, 60], id: \.self) { m in
                            Text("\(m) min before").tag(m)
                        }
                    }
                    .onChange(of: reminderChoice) { choice in
                        // First actual use of reminders on this device — the
                        // moment to ask, not app launch.
                        if choice != -1 { NotificationPermission.requestIfNeeded() }
                    }
                } footer: {
                    if let note = suppressionNote {
                        Label(note, systemImage: "moon.stars")
                    } else if reminderChoice == -1 {
                        Text("Inherit uses the category's lead time, set on your Mac. Per-event reminders are off by default — Settings › Notifications is the one summary this phone shows.")
                    }
                }
                // On a NEW event too (2026-09-25): until then a repeat could
                // only be added after saving, by reopening the event.
                RepeatsSection(recurrence: $recurrence,
                               recurrenceEnd: $recurrenceEnd,
                               startDate: date,
                               recurDays: event.recurDays ?? "",
                               isSeries: !isNew && !event.recurrence.isEmpty,
                               seriesCount: seriesCount,
                               busy: seriesBusy,
                               deleteSeries: isNew ? nil : { confirmSeriesDelete = true })
                .onChange(of: recurrence) { newValue in
                    // Something being made to repeat is offered an end a
                    // month after it — most repeating things stop. An
                    // existing open-ended series keeps its Never.
                    if !newValue.isEmpty && event.recurrence.isEmpty
                        && recurrenceEnd.isEmpty && !endDefaulted {
                        recurrenceEnd = RepeatHint.monthAfter(date)
                        endDefaulted = true
                    }
                }
                // Never presented on a new event: there is no Delete series
                // button there to set it.
                .confirmationDialog("Delete the whole series?",
                                    isPresented: $confirmSeriesDelete,
                                    titleVisibility: .visible) {
                    Button("Delete this and future", role: .destructive) {
                        removeSeries(futureOnly: true)
                    }
                    Button("Delete every instance", role: .destructive) {
                        removeSeries(futureOnly: false)
                    }
                    Button("Cancel", role: .cancel) {}
                }
                // The event body. This is where a planned session keeps the
                // part that matters — "2 × 10 min @ 4:40 — 2 min jog between" —
                // so it needs room to wrap, not a one-line TextField.
                Section(header: Text("Notes")) {
                    TextField("Notes", text: $notes, axis: .vertical)
                        .lineLimit(3...12)
                }
                if !isNew && !isReadOnly {
                    LinkedTodoSection(eventId: event.id)
                }
                GuestsSection(attendees: $attendees, title: title, date: date, startTime: startTime, endTime: endTime, location: location)
                if !isNew {
                    Section {
                        Button {
                            shareICS()
                        } label: {
                            HStack {
                                Label("Share Event (.ics)", systemImage: "square.and.arrow.up")
                                if sharing {
                                    Spacer()
                                    ProgressView()
                                }
                            }
                        }
                        // Offline temp rows (negative id) don't exist on the
                        // Mac yet, so there is nothing to fetch.
                        .disabled(sharing || event.id <= 0)
                    } footer: {
                        if event.id <= 0 {
                            Text("Sharing becomes available once this event has synced to your Mac.")
                        }
                    }
                }
                if !isNew && !isReadOnly {
                    Section {
                        Button(role: .destructive) { confirmDelete = true } label: {
                            Label("Delete Event", systemImage: "trash")
                        }
                        // Anchored to the BUTTON, not to the form (Gil,
                        // 2026-09-18: "move it so its just above the initial
                        // delete button so i dont need to move my fingers so
                        // much"). A confirmationDialog attached to the whole
                        // view anchors its popover at the top of the screen —
                        // so confirming a delete meant reaching from the
                        // bottom of a long scroll up to the navigation bar and
                        // back. Attached here, the popover comes up beside the
                        // control your thumb is already on.
                        .confirmationDialog("Delete this event?",
                                            isPresented: $confirmDelete,
                                            titleVisibility: .visible) {
                            Button("Delete", role: .destructive) { deleteEvent() }
                            Button("Cancel", role: .cancel) {}
                        }
                    }
                }
            }
            .disabled(isReadOnly)
            .onAppear(perform: loadSeriesCount)
            .navigationTitle(isNew ? "New Event" : "Edit Event")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                if !isReadOnly {
                    ToolbarItem(placement: .confirmationAction) {
                        Button("Save") { save() }
                            .disabled(saving || title.isEmpty)
                            .keyboardShortcut(.defaultAction)
                    }
                }
            }
            .sheet(item: $shareFile) { file in
                ShareSheet(items: [file.url])
            }
            .alert("Couldn't Save", isPresented: .constant(errorMessage != nil), presenting: errorMessage) { _ in
                Button("OK") { errorMessage = nil }
            } message: { message in
                Text(message)
            }
        }
    }

    // MARK: - Auto end-time

    /// When the user changes the start time, push the end to start + the
    /// default length (DEVQA Q51) — capped at 23:59, as the Mac's engine caps
    /// it, rather than wrapping to an end before the start.
    private func autoUpdateEndTime(from start: String) {
        if let end = EventDefaults.end(from: start, minutes: lengthMinutes) {
            endTime = end
        }
    }

    /// A NEW event's length follows its title's category, which only the Mac
    /// can classify: ask once typing pauses, and move the end with it only if
    /// the end is still the default one (a hand-set end is left alone).
    private func refineLength(for title: String) async {
        guard isNew else { return }
        let t = title.trimmingCharacters(in: .whitespaces)
        guard !t.isEmpty else { return }
        try? await Task.sleep(nanoseconds: 400_000_000)      // debounce keystrokes
        guard !Task.isCancelled,
              let d = try? await api.eventDefaults(title: t),
              d.lengthMinutes != lengthMinutes else { return }
        let stillDefault = endTime == EventDefaults.end(from: startTime, minutes: lengthMinutes)
        lengthMinutes = d.lengthMinutes
        if stillDefault { autoUpdateEndTime(from: startTime) }
    }

    // MARK: - Actions

    /// Did the RULE move — cadence or end — rather than only this row's fields?
    private var ruleChanged: Bool {
        recurrence != event.recurrence || recurrenceEnd != event.recurrenceEnd
    }

    private func save() {
        guard !saving else { return }
        // The end is inclusive and may not precede the event: if the date was
        // moved past it, the end moves with it rather than describing a
        // series with no room in it.
        if !recurrence.isEmpty && !recurrenceEnd.isEmpty && recurrenceEnd < date {
            recurrenceEnd = date
        }
        if recurrence.isEmpty { recurrenceEnd = "" }
        saving = true
        Task {
            do {
                var fields: [String: Any] = [
                    "title": title, "date": date,
                    "start_time": startTime, "end_time": endTime,
                    "location": location, "attendees": attendees,
                    "description": notes
                ]
                if isNew {
                    // Only send an override that exists — a fresh event with
                    // "Inherit" simply has no reminder_minutes.
                    if reminderChoice != -1 { fields["reminder_minutes"] = reminderChoice }
                    // A repeating create is ONE POST: the Mac builds the linked
                    // series from it (db.create_event_from_dict), skipping
                    // Shabbat and yom tov the same way a spoken series does.
                    // Offline it queues like any create and the series is
                    // built when it reaches the Mac.
                    if !recurrence.isEmpty {
                        fields["recurrence"] = recurrence
                        fields["recurrence_end"] = recurrenceEnd
                    }
                    _ = try await api.createEvent(fields)
                } else {
                    // NSNull → JSON null → the Mac clears the override back
                    // to Inherit. The offline patchEvent path reads the same
                    // convention.
                    fields["reminder_minutes"] = reminderChoice == -1 ? NSNull() : reminderChoice
                    try await api.updateEvent(id: event.id, fields: fields)
                    if ruleChanged {
                        // The rule goes to the whole series — the hint under
                        // End repeat says so before Save. A separate "Apply to
                        // the whole series" button used to do this while Save
                        // quietly did not, so a new end date set and saved
                        // was simply lost.
                        guard await applySeriesRule() else {
                            saving = false
                            onDismiss?()   // refresh: this event's own edit did land
                            return
                        }
                    }
                }
                saving = false
                dismiss()
                onDismiss?()
            } catch {
                // Most failures (offline, bad URL) are already handled inside
                // APIClient by queuing for later — only a real rejection from
                // the server (e.g. 403 on a read-only synced event) reaches
                // here, so surface it instead of silently discarding it.
                saving = false
                errorMessage = "This event couldn't be saved — it may be read-only (synced from another calendar)."
            }
        }
    }

    private func deleteEvent() {
        Task {
            do {
                try await api.deleteEvent(id: event.id)
                dismiss()
                onDismiss?()
            } catch {
                errorMessage = "This event couldn't be deleted — it may be read-only (synced from another calendar)."
                onDismiss?()  // local optimistic removal already happened; refresh to restore it
            }
        }
    }

    // MARK: - The series

    /// How many instances are linked, so the footer can say so. Read-only and
    /// best-effort: a phone with no Mac in reach just shows the generic text.
    private func loadSeriesCount() {
        guard !isNew, event.id > 0, !recurrence.isEmpty else { return }
        Task {
            if let s = try? await api.eventSeries(id: event.id) {
                seriesCount = s.count
            }
        }
    }

    /// Write the RULE to every instance; the Mac regenerates the later
    /// instances, so extending the end date adds them and shortening it trims
    /// them, all under the one series_id. Returns false (with the reason
    /// shown) when it could not be applied.
    private func applySeriesRule() async -> Bool {
        guard event.id > 0 else {
            // An offline temp row doesn't exist on the Mac yet, so there is no
            // series to rebuild; its own fields are already queued.
            errorMessage = "This event hasn't synced to your Mac yet — change its repeat once it has."
            return false
        }
        seriesBusy = true
        defer { seriesBusy = false }
        do {
            let out = try await api.updateSeries(
                id: event.id,
                fields: ["recurrence": recurrence,
                         "recurrence_end": recurrenceEnd])
            seriesCount = out.count
            return true
        } catch {
            // Deliberately NOT queued offline: growing or trimming a series
            // deletes and regenerates rows on the Mac, and replaying that
            // against a database that moved on would be guesswork about
            // which instances were meant. This event's own fields were saved
            // (or queued) above; only the repeat change is refused.
            errorMessage = "Your other changes were saved, but the repeat couldn't be — your Mac needs to be reachable to change a series."
            return false
        }
    }

    private func removeSeries(futureOnly: Bool) {
        seriesBusy = true
        Task {
            defer { seriesBusy = false }
            do {
                try await api.deleteSeries(id: event.id, futureOnly: futureOnly)
                dismiss()
                onDismiss?()
            } catch {
                errorMessage = "The series couldn't be deleted — your Mac needs to be reachable for this one."
                onDismiss?()
            }
        }
    }

    // MARK: - Share as .ics

    /// A filesystem-safe slug of the title for the shared file's name.
    private var titleSlug: String {
        let safe = title
            .replacingOccurrences(of: "[^A-Za-z0-9 _-]", with: "", options: .regularExpression)
            .trimmingCharacters(in: .whitespaces)
            .replacingOccurrences(of: " ", with: "-")
        return safe.isEmpty ? "event" : safe
    }

    /// Download the Mac's rendering of this event (GET /events/<id>.ics),
    /// park it in a temp file named after the title, and present the share
    /// sheet for that file. The Mac is the source of truth for the .ics —
    /// recurrence, categories and any Mac-side edits come out right without
    /// the phone re-deriving them from possibly-unsaved form fields.
    private func shareICS() {
        guard !sharing, event.id > 0 else { return }
        sharing = true
        Task {
            do {
                let data = try await api.fetchICS(eventId: event.id)
                let url = FileManager.default.temporaryDirectory
                    .appendingPathComponent("\(titleSlug).ics")
                try data.write(to: url)
                sharing = false
                shareFile = ShareFile(url: url)
            } catch {
                sharing = false
                errorMessage = "Couldn't fetch this event from your Mac — sharing needs the Mac reachable."
            }
        }
    }
}

/// The SERIES rule, as its own view.
///
/// Its own struct and not a computed property in `body` for the reason this
/// project has already paid for once: a SwiftUI body that grows past a certain
/// size stops type-checking in reasonable time and the build dies with
/// "unable to type-check this expression in reasonable time" pointing at
/// nothing useful. A picker, a date row and two buttons is exactly the amount
/// that tips it.
///
/// The cadences are the four the product supports (CLAUDE.md) — anything else
/// a speaker says is rounded to one of them and the rounding is announced, so
/// offering a fifth here would promise something the engine cannot keep.
///
/// End repeat is Never | On date, the same two choices as the Mac dialog. It
/// was a "Has an end date" toggle defaulting to three months from TODAY —
/// which for an event next spring was an end before its own start.
private struct RepeatsSection: View {
    @Binding var recurrence: String
    @Binding var recurrenceEnd: String
    /// The event's own date (yyyy-MM-dd): the floor for the end, and the
    /// weekday the hint names.
    let startDate: String
    let recurDays: String
    /// Editing an event that is already part of a series.
    let isSeries: Bool
    let seriesCount: Int
    let busy: Bool
    /// nil on a new event — there is no series to delete yet.
    let deleteSeries: (() -> Void)?

    private static let cadences = [("Never", ""), ("Every day", "daily"),
                                   ("Every week", "weekly"),
                                   ("Every month", "monthly"),
                                   ("Every year", "yearly")]

    /// "" means the series never ends. A DatePicker cannot express that, so
    /// the End repeat picker carries it and the date only appears for On date.
    private var hasEnd: Binding<Bool> {
        Binding(get: { !recurrenceEnd.isEmpty },
                set: { on in
                    if on {
                        if recurrenceEnd.isEmpty {
                            recurrenceEnd = RepeatHint.monthAfter(startDate)
                        }
                    } else {
                        recurrenceEnd = ""
                    }
                })
    }

    private var start: Date { RepeatHint.day.date(from: startDate) ?? Date() }

    private var endDate: Binding<Date> {
        Binding(get: { max(RepeatHint.day.date(from: recurrenceEnd) ?? start, start) },
                set: { recurrenceEnd = RepeatHint.day.string(from: $0) })
    }

    var body: some View {
        Section {
            Picker("Repeats", selection: $recurrence) {
                ForEach(Self.cadences, id: \.1) { label, value in
                    Text(label).tag(value)
                }
            }
            if !recurrence.isEmpty {
                Picker("End repeat", selection: hasEnd) {
                    Text("Never").tag(false)
                    Text("On date").tag(true)
                }
                if !recurrenceEnd.isEmpty {
                    // Never before the event's own date: the end is inclusive,
                    // and an earlier one would describe a series with no room.
                    DatePicker("Ends on", selection: endDate, in: start...,
                               displayedComponents: .date)
                }
            }
            if isSeries, let deleteSeries {
                Button(role: .destructive) { deleteSeries() } label: {
                    HStack {
                        Label("Delete series…", systemImage: "trash")
                        if busy { Spacer(); ProgressView() }
                    }
                }
                .disabled(busy)
            }
        } header: {
            Text("Repeats")
        } footer: {
            Text(footer)
        }
    }

    private var footer: String {
        if recurrence.isEmpty {
            return isSeries
                ? "Saving stops the series here — the events after this one are removed."
                : "Pick a cadence to turn this into a series of linked events."
        }
        var text = RepeatHint.caption(recurrence: recurrence, start: startDate,
                                      end: recurrenceEnd, recurDays: recurDays)
        if isSeries {
            let linked = seriesCount > 0 ? "\(seriesCount) events are linked. " : ""
            text += "\n\n" + linked + "Changing Repeat or End repeat updates the whole "
                + "series when you save — extending adds events, shortening removes them. "
                + "Your other edits change only this event."
        }
        return text
    }
}

/// The words for a repeat, in one place — the phone's copy of the Mac
/// dialog's `repeat_hint` / `series_badge` (assistant/calendar_ui/event_dialog.py),
/// so both apps describe a series the same way.
///
/// The end date is INCLUSIVE — "ends on 30 Oct" books the 30th, which is how
/// the Mac has always generated a series — hence "through", the word the
/// project reads as keeping its day ("until" excludes it; CLAUDE.md).
enum RepeatHint {
    static let day: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        f.locale = Locale(identifier: "en_US_POSIX")
        return f
    }()

    private static func format(_ pattern: String, _ d: Date) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_GB")
        f.dateFormat = pattern
        return f.string(from: d)
    }

    /// "Fri 30 Oct", with the year only when it isn't this one.
    static func label(_ iso: String) -> String {
        guard let d = day.date(from: iso) else { return iso }
        let sameYear = Calendar.current.component(.year, from: d)
            == Calendar.current.component(.year, from: Date())
        return format(sameYear ? "EEE d MMM" : "EEE d MMM yyyy", d)
    }

    /// One month after `iso` — the default end for something made to repeat.
    static func monthAfter(_ iso: String) -> String {
        let base = day.date(from: iso) ?? Date()
        return day.string(from: Calendar.current.date(byAdding: .month, value: 1, to: base) ?? base)
    }

    private static func ordinal(_ n: Int) -> String {
        if (11...13).contains(n % 100) { return "\(n)th" }
        switch n % 10 {
        case 1: return "\(n)st"
        case 2: return "\(n)nd"
        case 3: return "\(n)rd"
        default: return "\(n)th"
        }
    }

    static func cadence(_ recurrence: String, start iso: String, recurDays: String) -> String {
        let d = day.date(from: iso) ?? Date()
        let days = recurDays.split(separator: ",")
            .map { $0.trimmingCharacters(in: .whitespaces).capitalized }
            .filter { !$0.isEmpty }
        switch recurrence {
        case "daily": return "every day"
        case "weekly":
            if days.count > 1, let last = days.last {
                return "every " + days.dropLast().joined(separator: ", ") + " and " + last
            }
            return "every " + format("EEEE", d)
        case "monthly":
            return "every month on the " + ordinal(Calendar.current.component(.day, from: d))
        case "yearly": return "every year on " + format("d MMMM", d)
        default: return ""
        }
    }

    static func caption(recurrence: String, start: String, end: String, recurDays: String) -> String {
        let what = cadence(recurrence, start: start, recurDays: recurDays)
        let when = end.isEmpty
            ? "Repeats \(what) with no end date — the next 12 months are booked."
            : "Repeats \(what) through \(label(end)), then stops — the end date is included."
        return when + " Skips Shabbat and yom tov."
    }

    /// "Part of a weekly series · ends Fri 30 Oct" — nil for a one-off.
    static func badge(for event: CalendarEvent) -> String? {
        guard !event.recurrence.isEmpty else { return nil }
        let tail = event.recurrenceEnd.isEmpty ? "no end date" : "ends " + label(event.recurrenceEnd)
        return "Part of a \(event.recurrence) series · \(tail)"
    }
}

/// Identifiable wrapper so `.sheet(item:)` can present the share sheet the
/// moment the .ics file lands on disk. ShareLink wants its item up front,
/// which an async fetch can't provide — GuestsSection gets away with
/// ShareLink because it composes its .ics synchronously on-device.
private struct ShareFile: Identifiable {
    let url: URL
    var id: String { url.path }
}

/// The system share sheet (runs in-process; nothing here talks to a service).
private struct ShareSheet: UIViewControllerRepresentable {
    let items: [Any]
    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: items, applicationActivities: nil)
    }
    func updateUIViewController(_ vc: UIActivityViewController, context: Context) {}
}
