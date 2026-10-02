import SwiftUI
import AVFoundation
import UIKit
import UserNotifications

struct SettingsView: View {
    @EnvironmentObject var settings: AppSettings
    @EnvironmentObject var api: APIClient
    @ObservedObject private var visibility = FeatureVisibility.shared
    @ObservedObject private var fold = SettingsFold.shared
    @State private var healthStatus: String? = nil
    @State private var checking = false
    @State private var assistantNote: String?
    @State private var unreviewed = 0
    // The day panel: the server-side policy (nil until the Mac answers).
    @State private var notifConfig: NotificationsConfig? = nil
    @State private var permStatus: UNAuthorizationStatus? = nil
    @FocusState private var urlFocused: Bool
    @FocusState private var keyFocused: Bool

    private var validLanguages: [String] { voices.map(\.language) }

    private let voices: [(label: String, language: String)] = [
        ("Samantha (US)", "en-US"),
        ("Daniel (UK)",   "en-GB"),
        ("Karen (AU)",    "en-AU"),
    ]

    @ObservedObject private var store = LocalStore.shared
    @State private var showQueue = false


    var body: some View {
        StackNavigation {
            List {
                // Your account first: who this phone is signed in as.
                if let u = UserSession.shared.user {
                    Section {
                        NavigationLink { AccountView() } label: {
                            HStack(spacing: 12) {
                                ZStack {
                                    Circle().fill(Color(hex: u.color) ?? .gray)
                                    Text(String(u.displayName.prefix(1)).uppercased())
                                        .font(.headline).foregroundColor(.white)
                                }
                                .frame(width: 40, height: 40)
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(u.displayName).font(.headline)
                                    Text("Account, password & sharing\(u.isAdmin ? " · admin" : "")")
                                        .font(.caption).foregroundColor(.secondary)
                                }
                            }
                            .padding(.vertical, 4)
                        }
                    }
                }

                Section {
                  if fold.isOpen("Calendar") {
                    row("Appearance", "paintbrush", .orange, appearanceSummary) { appearancePage }
                    row("Events", "clock", .blue, eventsSummary) { eventsPage }
                    row("Hebrew & Shabbat", "calendar.badge.clock", .indigo, hebrewSummary) { hebrewPage }
                    row("Occasions", "gift", .pink, "Birthdays, yahrzeits…") { OccasionsSettingsView() }
                    row("Event colours", "paintpalette", .pink, "Categories") { CategoriesView() }
                    row("Connected calendars", "calendar.badge.plus", .green, "Google, Outlook") {
                        ConnectedCalendarsView()
                    }
                  }
                } header: { FoldHeader("Calendar") }

                Section {
                  if fold.isOpen("Notifications & tabs") {
                    row("Notifications", "bell.badge", .red,
                        settings.remindersEnabled ? "Morning summary on" : "Off") { notificationsPage }
                    row("Tabs", "square.grid.2x2", .teal, tabsSummary) { tabsPage }
                  }
                } header: { FoldHeader("Notifications & tabs") }

                if fold.isOpen("Assistant") {
                Section {
                    // The switch (Gil, 2026-09-29): off, nothing said or typed
                    // is acted on — here or on the Mac. The Mac keeps it.
                    Toggle(isOn: Binding(
                        get: { api.assistantEnabled },
                        set: { on in
                            Task { assistantNote = await api.setAssistant(on) }
                        })) {
                        HStack {
                            SettingsIcon("sparkles", .purple)
                            Text("Assistant")
                        }
                    }
                    .onAppear { Task { _ = try? await api.health() } }
                    if let assistantNote {
                        Text(assistantNote).font(.caption).foregroundColor(.red)
                    }
                } header: {
                    FoldHeader("Assistant")
                } footer: {
                    Text(api.assistantEnabled
                         ? "On: speak or type commands here and on your Mac."
                         : "Off: nothing you say or type is acted on, here or on your Mac. "
                           + "Your calendar and to-dos work as usual.")
                }
                Section {
                    NavigationLink { AssistantReviewView() } label: {
                        HStack {
                            SettingsIcon("checkmark.bubble", .purple)
                            Text("Review commands")
                            Spacer()
                            if unreviewed > 0 {
                                Text("\(unreviewed)")
                                    .font(.caption.weight(.semibold))
                                    .padding(.horizontal, 7).padding(.vertical, 2)
                                    .background(settings.accentColor.opacity(0.2))
                                    .foregroundColor(settings.accentColor)
                                    .clipShape(Capsule())
                            }
                        }
                    }
                    row("Voice & recording", "waveform", .purple, voiceSummary) { voicePage }
                    row("Vocabulary", "character.book.closed", .purple, "Names & words") { VocabularyView() }
                    row("How I say things", "text.book.closed", .purple, "Words it acts on") { LexiconView() }
                    row("How to talk to me", "lightbulb", .yellow, "Tips") { TipsView() }
                    TitleEmojiPicker()
                }
                } else {
                    Section {} header: { FoldHeader("Assistant") }
                }

                Section {
                  if fold.isOpen("Connection") {
                    row("How it runs", "switch.2", .blue, settings.phoneOnly ? "This phone only" : "Mac + phone") {
                        SetupGuideView()
                    }
                    row("Your Mac", "desktopcomputer", .gray, connectionSummary) { serverPage }
                    row("Servers & logs", "server.rack", .gray, "Model helpers") { ServersView() }
                    if store.pendingCount > 0 {
                        Button { showQueue = true } label: {
                            HStack {
                                SettingsIcon("tray.full", .orange)
                                Text("\(store.pendingCount) change\(store.pendingCount == 1 ? "" : "s") waiting to sync")
                                    .foregroundColor(.primary)
                                Spacer()
                                Image(systemName: "chevron.right").font(.caption).foregroundColor(.secondary)
                            }
                        }
                        .accessibilityIdentifier("pending-queue-link")
                    }
                  }
                } header: { FoldHeader("Connection") }

                Section {
                  if fold.isOpen("Just for fun") {
                    row("Easter egg", "wand.and.stars", .pink,
                        EggStore.shared.settings.enabled ? "Magic words on" : "Off") { EggSettingsView() }
                  }
                } header: { FoldHeader("Just for fun") }

                Section {
                  if fold.isOpen("About") {
                    HStack { Text("Version"); Spacer(); Text("1.0").foregroundColor(.secondary) }
                    Link("GitHub", destination: URL(string: "https://github.com/GilCaplan/MACalendar")!)
                  }
                } header: { FoldHeader("About") }
            }
            .listStyle(.insetGrouped)
            .sheet(isPresented: $showQueue) { PendingQueueView() }
            .navigationTitle("Settings")
            .onAppear {
                if !validLanguages.contains(settings.ttsVoice) {
                    settings.ttsVoice = "en-US"
                }
                Task { unreviewed = await api.unreviewedCount() }
                // The tab switches may have been flipped on the Mac. The
                // toggles render from the local cache first and correct
                // themselves if and when this answers.
                Task { await visibility.refresh(api: api) }
                Task {
                    permStatus = await NotificationPermission.status()
                    notifConfig = try? await api.notificationsConfig()
                    await adoptSharedSettings()
                    // The switch is shared, so the Mac's answer wins — EXCEPT
                    // while this phone is still holding one of its own. A
                    // toggle flipped offline sits in the queue; adopting the
                    // server's value before it replays would flip the switch
                    // back under the user's finger and then un-flip it later.
                    if let cfg = notifConfig,
                       !LocalStore.shared.pending.contains(where: { $0.path == "/config" }) {
                        settings.remindersEnabled = cfg.dailyDigest
                        // The card's switch is shared with the Mac too, so adopt
                        // it the same way and on the same condition. Routed
                        // through `setEnabled` rather than assigned, or the
                        // manager would not act on a change made on the Mac
                        // until something else happened to call `sync()`.
                        if cfg.agendaCard != settings.agendaCardEnabled {
                            settings.agendaCardEnabled = cfg.agendaCard
                            LiveActivityManager.shared.setEnabled(cfg.agendaCard)
                        }
                    }
                }
            }
        }
    }

    // MARK: - The pages
    //
    // Reorganised 2026-09-28 (Gil: "settings feel a little messy"). Twelve
    // fold-open sections on one scroll became a short list grouped the way
    // iOS's own Settings is: each row says where things stand and opens a
    // page of its own. The contents of each page are the old sections'
    // controls, unchanged.

    private func row<Dest: View>(_ title: String, _ icon: String, _ tint: Color,
                                 _ detail: String,
                                 @ViewBuilder destination: @escaping () -> Dest) -> some View {
        NavigationLink { destination() } label: {
            HStack {
                SettingsIcon(icon, tint)
                Text(title).lineLimit(1).layoutPriority(1)     // the name never wraps;
                Spacer(minLength: 8)
                Text(detail).font(.callout).foregroundColor(.secondary).lineLimit(1)   // the detail gives way
            }
        }
    }

    private var appearanceSummary: String {
        "\(settings.theme.capitalized) · \(settings.defaultCalendarView.capitalized)"
    }
    private var eventsSummary: String { "\(settings.eventLengthMinutes) min" }
    private var hebrewSummary: String {
        settings.hebrewDisplayMode == "english" ? (settings.showHolidays ? "Holidays" : "Off")
            : settings.hebrewDisplayMode.capitalized
    }
    private var tabsSummary: String {
        let shown = FeatureRegistry.togglable.filter { visibility.isVisible($0) }.count
        return "\(shown) of \(FeatureRegistry.togglable.count) optional"
    }
    private var voiceSummary: String { settings.speakReplies ? "Speaks replies" : "Silent" }
    private var connectionSummary: String {
        !settings.serverEnabled ? "Offline" : (api.isOnline ? "Connected" : "Not reachable")
    }

    private var serverPage: some View {
        SettingsPage("Your Mac") {
                        // Found or scanned — no address to type (DEVQA Q69).
                        NearbyServers()
                        Divider().padding(.vertical, 4)
                        Text("Or type its address").font(.subheadline.weight(.semibold))
                        VStack(spacing: 12) {
                            HStack {
                                TextField("http://100.x.x.x:8080", text: $settings.serverURL)
                                    .keyboardType(.URL)
                                    .autocorrectionDisabled()
                                    .textInputAutocapitalization(.never)
                                    .focused($urlFocused)
                                if !settings.serverURL.isEmpty {
                                    Button { settings.serverURL = "" } label: {
                                        Image(systemName: "xmark.circle.fill")
                                            .foregroundColor(.secondary)
                                    }
                                }
                            }
                            .padding(10)
                            .background(Color(.systemBackground))
                            .cornerRadius(8)
                            .overlay(RoundedRectangle(cornerRadius: 8).stroke(urlFocused ? settings.accentColor : Color(.separator), lineWidth: 1))
                            .onTapGesture { urlFocused = true }

                            HStack {
                                TextField("API Key (optional)", text: $settings.apiKey)
                                    .autocorrectionDisabled()
                                    .textInputAutocapitalization(.never)
                                    .focused($keyFocused)
                                if !settings.apiKey.isEmpty {
                                    Button { settings.apiKey = "" } label: {
                                        Image(systemName: "xmark.circle.fill")
                                            .foregroundColor(.secondary)
                                    }
                                }
                            }
                            .padding(10)
                            .background(Color(.systemBackground))
                            .cornerRadius(8)
                            .overlay(RoundedRectangle(cornerRadius: 8).stroke(keyFocused ? settings.accentColor : Color(.separator), lineWidth: 1))
                            .onTapGesture { keyFocused = true }

                            Button(action: checkHealth) {
                                HStack {
                                    Text("Test Connection")
                                    Spacer()
                                    if checking {
                                        ProgressView()
                                    } else if let s = healthStatus {
                                        Text(s)
                                            .foregroundColor(s.contains("✓") ? .green : .red)
                                            .font(.caption)
                                    }
                                }
                            }

                            Text("Your Mac's Tailscale address. Defaults to "
                                 + AppSettings.defaultServerURL
                                 + " — a bare IP, host:port or MagicDNS name all work.")
                                .font(.caption)
                                .foregroundColor(.secondary)
                        }
                        // Dimmed and inert while the connection is switched
                        // off: the address and the test are about reaching a
                        // Mac we are deliberately not reaching. `.disabled`
                        // alone leaves them looking live, and `.opacity` alone
                        // leaves them tappable — it needs both to read as off.
                        .padding(.top, 4)
                        .disabled(!settings.serverEnabled)
                        .opacity(settings.serverEnabled ? 1 : 0.35)
                        .animation(.easeInOut(duration: 0.2), value: settings.serverEnabled)

                        Divider().padding(.vertical, 4)

                        Toggle(isOn: $settings.serverEnabled) {
                            // Pulled out of the inline `Text(cond ? a : b)`: the
                            // ternary plus string concatenation inside a deeply
                            // nested builder tipped the whole `body` over
                            // SwiftUI's type-checking budget the moment one more
                            // row was added ("unable to type-check this
                            // expression in reasonable time"). A stored String
                            // costs the checker nothing.
                            VStack(alignment: .leading, spacing: 2) {
                                Text("Connect to your Mac")
                                Text(serverBlurb)
                                    .font(.caption)
                                    .foregroundColor(.secondary)
                            }
                        }
                        .accessibilityIdentifier("server-connect-toggle")

                        // The offline reader (assistant/offline): whether this
                        // device can read a command itself while the Mac is away.
                        Label(offlineReaderNote, systemImage: "iphone.gen3.radiowaves.left.and.right")
                            .font(.caption)
                            .foregroundColor(.secondary)

                        if store.pendingCount > 0 {
                            Button { showQueue = true } label: {
                                HStack {
                                    Label("\(store.pendingCount) change\(store.pendingCount == 1 ? "" : "s") waiting to sync",
                                          systemImage: "tray.full")
                                    Spacer()
                                    Image(systemName: "chevron.right")
                                        .font(.caption).foregroundColor(.secondary)
                                }
                            }
                            .accessibilityIdentifier("pending-queue-link")
                        }
            }
    }

    private var appearancePage: some View {
        SettingsPage("Appearance") {
                        VStack(alignment: .leading, spacing: 12) {
                            Picker("Theme", selection: $settings.theme) {
                                Text("Light").tag("light")
                                Text("Dark").tag("dark")
                            }
                            .pickerStyle(.segmented)
                            .onChange(of: settings.theme) { v in
                                Task { await api.patchShared(["theme": v]) }
                            }

                            Divider().padding(.vertical, 4)

                            Label("Accent Color", systemImage: "paintpalette")
                            HStack(spacing: 10) {
                                ForEach(Theme.accentPresets, id: \.hex) { preset in
                                    Circle()
                                        .fill(Color(hex: preset.hex) ?? Theme.defaultAccent)
                                        .frame(width: 28, height: 28)
                                        .overlay(
                                            Circle()
                                                .stroke(Color.primary.opacity(settings.accentColorHex.caseInsensitiveCompare(preset.hex) == .orderedSame ? 1 : 0), lineWidth: 2)
                                                .padding(2)
                                        )
                                        .onTapGesture { settings.accentColorHex = preset.hex }
                                }
                                ColorPicker("", selection: Binding(
                                    get: { settings.accentColor },
                                    set: { newColor in settings.accentColorHex = newColor.hexString ?? settings.accentColorHex }
                                ))
                                .labelsHidden()
                                .frame(width: 28, height: 28)
                            }

                            Divider().padding(.vertical, 4)

                            VStack(alignment: .leading, spacing: 6) {
                                Label("Open calendar on", systemImage: "calendar.badge.clock")
                                Picker("Open calendar on", selection: $settings.defaultCalendarView) {
                                    Text("Month").tag("month")
                                    Text("Week").tag("week")
                                    Text("Day").tag("day")
                                }
                                .pickerStyle(.segmented)
                                Text("The view the calendar shows when the app opens.")
                                    .font(.caption).foregroundColor(.secondary)
                            }

                            // How the calendar is drawn (Gil, 2026-09-29) — per
                            // device, like the Mac's Settings ▸ Appearance.
                            VStack(alignment: .leading, spacing: 6) {
                                Label("Week starts on", systemImage: "calendar.day.timeline.left")
                                Picker("Week starts on", selection: $settings.weekStartsMonday) {
                                    Text("Sunday").tag(false)
                                    Text("Monday").tag(true)
                                }
                                .pickerStyle(.segmented)
                            }
                            Toggle(isOn: $settings.clock24) {
                                Label("24-hour clock", systemImage: "clock")
                            }
                            VStack(alignment: .leading, spacing: 6) {
                                Label("Settings sections start", systemImage: "rectangle.compress.vertical")
                                Picker("Settings sections start", selection: $fold.start) {
                                    ForEach(SettingsFold.Start.allCases, id: \.self) { Text($0.label).tag($0) }
                                }
                                .pickerStyle(.segmented)
                                Text("Tap a section's title in Settings to fold it.")
                                    .font(.caption).foregroundColor(.secondary)
                            }
                            VStack(alignment: .leading, spacing: 6) {
                                Label("Show hours", systemImage: "clock.arrow.2.circlepath")
                                HStack {
                                    Picker("From", selection: $settings.hoursFrom) {
                                        ForEach(0..<24, id: \.self) { h in
                                            Text(CalendarPrefs.hourLabel(h, clock24: settings.clock24)).tag(h)
                                        }
                                    }
                                    .pickerStyle(.menu)
                                    Text("to")
                                    Picker("To", selection: $settings.hoursTo) {
                                        ForEach(1...24, id: \.self) { h in
                                            Text(h == 24 ? "Midnight"
                                                 : CalendarPrefs.hourLabel(h, clock24: settings.clock24)).tag(h)
                                        }
                                    }
                                    .pickerStyle(.menu)
                                }
                                Text("Day and Week show only these hours, filling the screen. "
                                     + "An event outside them still shows — that week or day grows to include it.")
                                    .font(.caption).foregroundColor(.secondary)
                            }

                            Divider().padding(.vertical, 4)

                            HStack {
                                Label("Month Font", systemImage: "calendar")
                                Spacer()
                                Stepper("\(Int(settings.fontMonth))", value: $settings.fontMonth, in: 8...24)
                            }
                            HStack {
                                Label("Week Font", systemImage: "calendar.day.timeline.left")
                                Spacer()
                                Stepper("\(Int(settings.fontWeek))", value: $settings.fontWeek, in: 8...24)
                            }
                            HStack {
                                Label("Day Font", systemImage: "calendar.day.timeline.leading")
                                Spacer()
                                Stepper("\(Int(settings.fontDay))", value: $settings.fontDay, in: 10...30)
                            }
                            HStack {
                                Label("Tasks Font", systemImage: "checklist")
                                Spacer()
                                Stepper("\(Int(settings.fontTasks))", value: $settings.fontTasks, in: 10...30)
                            }
                        }
                        .padding(.vertical, 4)
            }
    }

    private var hebrewPage: some View {
        SettingsPage("Hebrew calendar & Shabbat") {
                        VStack(alignment: .leading, spacing: 12) {
                            // one switch for all of it; each part stays its own below
                            Toggle(isOn: Binding(get: { settings.jewishCalendarOn }, set: { on in
                                settings.setJewishCalendar(on)
                                Task { await api.patchShared(["hebrew_calendar": ["display_mode": on ? "both" : "english",
                                                                                  "show_holidays": on, "show_shabbat_times": on],
                                                              "observance": ["enabled": on],
                                                              "title_emoji": ["jewish": on]]) }
                            })) {
                                Text("Jewish calendar").font(.headline)
                            }
                            .accessibilityIdentifier("jewish-calendar-toggle")
                            Picker("Show dates as", selection: $settings.hebrewDisplayMode) {
                                Text("English").tag("english")
                                Text("Hebrew").tag("hebrew")
                                Text("Both").tag("both")
                            }
                            .pickerStyle(.segmented)

                            Toggle("Show Jewish / Israeli holidays", isOn: $settings.showHolidays)
                                .onChange(of: settings.showHolidays) { v in
                                    Task { await api.patchShared(
                                        ["hebrew_calendar": ["show_holidays": v]]) }
                                }
                            Toggle(isOn: $settings.israelHolidays) {
                                HStack(spacing: 6) {
                                    Text("Israel holiday schedule")
                                    InfoTip("Israel keeps one day of each yom tov; outside Israel the second day is kept too. This decides which days are marked and kept free.")
                                }
                            }
                                .onChange(of: settings.israelHolidays) { v in
                                    Task { await api.patchShared(
                                        ["hebrew_calendar": ["israel_holidays": v]]) }
                                }
                                .disabled(!settings.showHolidays)

                            Text("Hebrew dates use gematria letters (e.g. כ״ט תשרי). Holidays begin at sundown the evening before their main day.")
                                .font(.caption)
                                .foregroundColor(.secondary)

                            Divider().padding(.vertical, 2)

                            Toggle(isOn: $settings.showShabbatTimes) {
                                HStack(spacing: 6) {
                                    Text("Mark when Shabbat & yom tov begin and end")
                                    InfoTip("Lines on the Day and Week views at the exact minute of candle lighting and of nightfall, worked out for where you are.")
                                }
                            }
                                .onChange(of: settings.showShabbatTimes) { v in
                                    Task { await api.patchShared(
                                        ["hebrew_calendar": ["show_shabbat_times": v]]) }
                                    CalendarNavigator.shared.reload()
                                    api.requestRefresh()
                                }
                            Text(settings.followMyLocation
                                 ? "Yellow lines on Day and Week at the exact minute of candle lighting and of nightfall, for where this phone is."
                                 : "Yellow lines on Day and Week at the exact minute of candle lighting and of nightfall — computed for the place set on your host. Turn on \"Sundown follows this device\" below so the minutes follow you when you travel.")
                                .font(.caption)
                                .foregroundColor(.secondary)

                            Toggle(isOn: $settings.followMyLocation) {
                                HStack(spacing: 6) {
                                    Text("Sundown follows this device")
                                    InfoTip("When you travel, candle lighting and nightfall are worked out for this phone's location, so series skip Shabbat at the right hour. Off: for the place set on your Mac. Your position stays on your own devices.")
                                }
                            }
                                .onChange(of: settings.followMyLocation) { on in
                                    if on {
                                        DeviceLocation.shared.refresh(using: api, force: true)
                                    } else {
                                        Task {
                                            try? await api.clearObservanceLocation()
                                            // The lines were drawn for here;
                                            // redraw them for the host's place.
                                            CalendarNavigator.shared.reload()
                                            api.requestRefresh()
                                        }
                                    }
                                }

                            Text(settings.followMyLocation
                                 ? "Candle lighting and nightfall are computed for wherever you are. Your position is sent to your own host and nowhere else — checked when the app opens or comes back to the front, and sent only when it has moved a few kilometres or changed time zone."
                                 : "Sundown uses the place configured on your host. Turn this on when you travel — the same clock time falls on different sides of Shabbat in different places.")
                                .font(.caption)
                                .foregroundColor(.secondary)

                            if !DeviceLocation.shared.status.isEmpty {
                                Text(DeviceLocation.shared.status)
                                    .font(.caption2)
                                    .foregroundColor(settings.accentColor)
                            }

                            // DEVQA Q59 / Q60 (Gil, 2026-09-26): the rule for
                            // what the ENGINE books is a master switch, shared
                            // with the Mac (`observance.enabled`), over a
                            // per-day "keep engine events off" switch.
                            Divider().padding(.vertical, 2)

                            Toggle(isOn: $settings.observanceEnabled) {
                                HStack(spacing: 6) {
                                    Text("Keep engine-made events off Shabbat & yom tov")
                                    InfoTip("For what the assistant books by voice (never your own edits): on a day kept off, a repeating series skips it and a one-off is still added, with a note. Shabbat and yom tov are kept off by default; chol hamoed and ordinary days are not. Switch off to turn all of it off.")
                                }
                            }
                                .onChange(of: settings.observanceEnabled) { v in
                                    Task { await api.patchShared(
                                        ["observance": ["enabled": v]]) }
                                }
                            Text(settings.observanceEnabled
                                 ? "For what the assistant books by voice: on a day kept off, a repeating series skips it and a one-off is still added, with a note. Shabbat and yom tov are kept off by default, chol hamoed and ordinary days are not — flip any day below."
                                 : "Off — the assistant books on every day as on any other, whatever the days below say.")
                                .font(.caption)
                                .foregroundColor(.secondary)

                            ObservanceDaysEditor()
                        }
                        .padding(.top, 4)
            }
    }

    private var eventsPage: some View {
        SettingsPage("Events") {
                        VStack(alignment: .leading, spacing: 12) {
                            Stepper(value: $settings.eventLengthMinutes,
                                    in: EventDefaults.minLength...EventDefaults.maxMinutes, step: 5) {
                                HStack {
                                    Label("Default length", systemImage: "hourglass")
                                    InfoTip("An event said with no end lasts this long. A category can set its own (Event colours & categories).")
                                    Spacer()
                                    Text("\(settings.eventLengthMinutes) min")
                                        .foregroundColor(.secondary)
                                }
                            }
                            .onChange(of: settings.eventLengthMinutes) { v in
                                Task { await api.patchShared(
                                    ["events": ["event_length_minutes": v]]) }
                            }
                            Stepper(value: $settings.chainGapMinutes,
                                    in: 0...EventDefaults.maxMinutes, step: 5) {
                                HStack {
                                    Label("Gap between chained events", systemImage: "arrow.right.to.line")
                                    InfoTip("In “gym at 9, then lunch”, lunch starts this long after the gym ends.")
                                    Spacer()
                                    Text("\(settings.chainGapMinutes) min")
                                        .foregroundColor(.secondary)
                                }
                            }
                            .onChange(of: settings.chainGapMinutes) { v in
                                Task { await api.patchShared(
                                    ["events": ["chain_gap_minutes": v]]) }
                            }
                            Text("An event with no end said lasts the default length. In “gym at 9, then lunch”, lunch starts this gap after the gym ends. A category can set its own of either in Calendar › Event colours.")
                                .font(.caption)
                                .foregroundColor(.secondary)

                            // DEVQA Q57 (Gil, 2026-09-26): a repeating event
                            // with no end said stops after a default, per
                            // cadence. Shared with the Mac (`events.series_end_*`).
                            Divider()
                            HStack(spacing: 6) {
                                Label("A repeating event with no end stops after",
                                      systemImage: "repeat")
                                InfoTip("A series you say without an end gets one, so it can't run forever. Saying an end (“until June”) always wins, and the reply tells you which end it used.")
                            }
                            ForEach(SeriesEnd.allCases) { cadence in
                                seriesEndStepper(cadence)
                            }
                            Text("Only when the words say no end — “until …” always wins — and the reply names the end it chose.")
                                .font(.caption)
                                .foregroundColor(.secondary)
                        }
                        .padding(.vertical, 4)
            }
    }

    private var notificationsPage: some View {
        SettingsPage("Notifications") {
                        VStack(alignment: .leading, spacing: 12) {
                            Toggle(isOn: $settings.remindersEnabled) {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text("Morning summary")
                                    Text(panelBlurb)
                                        .font(.caption).foregroundColor(.secondary)
                                }
                            }
                            .onChange(of: settings.remindersEnabled) { on in
                                if on { Task { permStatus = await NotificationPermission.request() } }
                                // Shared with the Mac, so its banner agrees
                                // with this phone. Offline this goes to the
                                // queue like any other write and replays.
                                notifConfig?.dailyDigest = on
                                Task {
                                    await api.patchNotifications(["daily_digest": on])
                                    await api.refreshDigests()
                                }
                                ReminderScheduler.shared.reconcile()
                            }

                            permissionRow

                            Button {
                                let summary = LiveActivityManager.todaysAgendaSummary(
                                    now: Date(), events: LocalStore.shared.ownEvents())
                                APIClient.notify(title: "Today's Agenda", body: summary)
                            } label: {
                                Label("Show today's agenda now", systemImage: "list.bullet.rectangle")
                            }
                            // Accuracy matters more than brevity here: this
                            // summary and the morning one are built by
                            // DIFFERENT machines from different data, and the
                            // caption used to point at "the reminders below,
                            // which fire on their own before each event" —
                            // a section that stopped existing when the day
                            // panel replaced per-event banners.
                            Text("Sends today's events to your notifications now. This one is built on your phone, so it works with the Mac asleep; the morning summary is the Mac's, and adds your tasks.")
                                .font(.caption).foregroundColor(.secondary)

                            Divider()

                            Toggle(isOn: $settings.agendaCardEnabled) {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text("Agenda on the lock screen")
                                    Text(agendaCardBlurb)
                                        .font(.caption).foregroundColor(.secondary)
                                }
                            }
                            .onChange(of: settings.agendaCardEnabled) { on in
                                // Switching ON also clears a dismissal, so this
                                // is how you get the card back today instead of
                                // waiting for the morning.
                                LiveActivityManager.shared.setEnabled(on)
                                // Shared with the Mac so the two settings
                                // screens cannot disagree. Offline this joins the
                                // queue like any other write and replays.
                                notifConfig?.agendaCard = on
                                Task { await api.patchNotifications(["agenda_card": on]) }
                            }

                            Divider()

                            Toggle(isOn: Binding(
                                get: { notifConfig?.respectObservance ?? true },
                                set: { on in
                                    notifConfig?.respectObservance = on
                                    Task {
                                        await api.patchNotifications(["respect_observance": on])
                                        await api.refreshDigests()
                                    }
                                })) {
                                Text("Quiet on Shabbat & chagim")
                            }
                                .disabled(notifConfig == nil)
                            Text("Holds the panel through Shabbat and yom tov, candle lighting to nightfall — computed on your Mac, never by the clock date alone.")
                                .font(.caption).foregroundColor(.secondary)

                            if notifConfig == nil {
                                Text("The panel's time is set on your Mac — it isn't reachable right now.")
                                    .font(.caption).foregroundColor(.orange)
                            }
                        }
                        .padding(.top, 4)
            }
    }

    private var tabsPage: some View {
        SettingsPage("Tabs") {
                        VStack(alignment: .leading, spacing: 8) {
                            ForEach(FeatureRegistry.togglable) { feature in
                                Toggle(isOn: Binding(
                                    get: { visibility.isVisible(feature) },
                                    set: { visibility.set(feature, visible: $0, api: api) })) {
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text("Show \(feature.label) Tab")
                                        if let note = feature.note {
                                            Text(note)
                                                .font(.caption).foregroundColor(.secondary)
                                        }
                                    }
                                }
                                .accessibilityIdentifier("feature-toggle-\(feature.name)")
                            }
                            // The Mac refusing a change is not the same as the
                            // Mac being away: a switch that springs back with no
                            // explanation reads as a bug, so its sentence shows.
                            if let refusal = visibility.lastRefusal {
                                Text(refusal).font(.caption).foregroundColor(.orange)
                            }
                            Text("Switched on and off on your Mac too — this "
                                 + "applies here straight away and travels when "
                                 + "the Mac is reachable.")
                                .font(.caption).foregroundColor(.secondary)
                        }
            }
    }

    private var voicePage: some View {
        SettingsPage("Voice & recording") {
                        VStack(alignment: .leading, spacing: 12) {
                            Toggle(isOn: $settings.speakReplies) {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text("Speak replies aloud")
                                    Text("Reads the result of each command. Off = silent, the text still shows in the thinking sheet.")
                                        .font(.caption).foregroundColor(.secondary)
                                }
                            }
                            Picker("TTS Voice", selection: $settings.ttsVoice) {
                                ForEach(voices, id: \.language) { v in
                                    Text(v.label).tag(v.language)
                                }
                            }
                            .pickerStyle(.segmented)
                            .disabled(!settings.speakReplies)
                            .onChange(of: settings.speakReplies) { v in
                                // The Mac stores MUTE; the phone asks SPEAK.
                                Task { await api.patchShared(["tts": ["mute": !v]]) }
                            }

                            Divider()

                            Toggle(isOn: $settings.stopWordsEnabled) {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text("Stop on “execute”")
                                    Text("Say execute / done / submit / confirm and the recording ends by itself (on-device, like the Mac)")
                                        .font(.caption).foregroundColor(.secondary)
                                }
                            }
                            Toggle("Ask before sending (Redo / Add more)", isOn: $settings.reviewBeforeSend)
                            Text("After the recording stops you get 4 seconds to redo it or keep talking before it is sent.")
                                .font(.caption).foregroundColor(.secondary)
                            Toggle("Stop automatically after silence", isOn: $settings.silenceStopEnabled)
                            HStack {
                                Text("Auto-stop after silence")
                                Spacer()
                                Text("\(Int(settings.silenceStopSeconds)) s").font(.caption.monospacedDigit()).foregroundColor(.secondary)
                            }
                            Slider(value: $settings.silenceStopSeconds, in: 2...12, step: 1).disabled(!settings.silenceStopEnabled)

                            Toggle(isOn: $settings.showThinking) {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text("Show assistant thinking")
                                    Text("Live step-by-step log while a command runs")
                                        .font(.caption).foregroundColor(.secondary)
                                }
                            }
                        }
                        .padding(.vertical, 4)
            }
    }

    // MARK: - Day panel helpers

    /// What the switch promises, in the two situations that differ.
    private var panelBlurb: String {
        let at = notifConfig?.digestTime ?? "07:00"
        return settings.remindersEnabled
            ? "One notification at \(at) with the day's events and tasks. It arrives even with your Mac asleep — this phone holds the next week's."
            : "Off — no notifications from the calendar, on this phone or the Mac."
    }

    /// Take the Mac's copy of the settings both screens show.
    ///
    /// Guarded by the same "not while a /config write is pending" condition the
    /// reminders switch uses: a change made on this phone while the Mac was away
    /// is sitting in the queue, and adopting the server's older value before it
    /// replays would flip the control back under the user's finger and then
    /// un-flip it a moment later.
    private func adoptSharedSettings() async {
        guard let shared = try? await api.sharedSettings() else { return }
        guard !LocalStore.shared.pending.contains(where: { $0.path == "/config" })
        else { return }
        if shared.theme != settings.theme { settings.theme = shared.theme }
        if !shared.accentColor.isEmpty, shared.accentColor != settings.accentColorHex {
            settings.accentColorHex = shared.accentColor
        }
        if shared.hebrewDisplayMode != settings.hebrewDisplayMode {
            settings.hebrewDisplayMode = shared.hebrewDisplayMode
        }
        if shared.showHolidays != settings.showHolidays {
            settings.showHolidays = shared.showHolidays
        }
        if shared.israelHolidays != settings.israelHolidays {
            settings.israelHolidays = shared.israelHolidays
        }
        if shared.showShabbatTimes != settings.showShabbatTimes {
            settings.showShabbatTimes = shared.showShabbatTimes
        }
        if let v = shared.observanceEnabled, v != settings.observanceEnabled {
            settings.observanceEnabled = v
        }
        if let v = shared.titleEmojiCount, v != settings.titleEmojiCount {
            settings.titleEmojiCount = v
        }
        if let v = shared.titleEmojiOff, v != settings.titleEmojiOff {
            settings.titleEmojiOff = v
        }
        if shared.hideCompletedTasks != settings.hideCompletedTasks {
            settings.hideCompletedTasks = shared.hideCompletedTasks
        }
        if shared.speakReplies != settings.speakReplies {
            settings.speakReplies = shared.speakReplies
        }
        if let v = shared.eventLengthMinutes, v != settings.eventLengthMinutes {
            settings.eventLengthMinutes = v
        }
        if let v = shared.chainGapMinutes, v != settings.chainGapMinutes {
            settings.chainGapMinutes = v
        }
        for cadence in SeriesEnd.allCases {
            if let v = shared.seriesEnd[cadence], v != settings[keyPath: cadence.keyPath] {
                settings[keyPath: cadence.keyPath] = v
            }
        }
    }

    /// One "daily — 14 days" row (DEVQA Q57). Bounded by `SeriesEnd.bounds`,
    /// the phone's copy of SERIES_END_BOUNDS, so every PATCH is one the Mac
    /// accepts.
    private func seriesEndStepper(_ cadence: SeriesEnd) -> some View {
        let n = settings[keyPath: cadence.keyPath]
        return Stepper(value: Binding(get: { settings[keyPath: cadence.keyPath] },
                                      set: { settings[keyPath: cadence.keyPath] = $0 }),
                       in: 1...cadence.bounds.max) {
            HStack {
                Text(cadence.rawValue.capitalized)
                Spacer()
                Text("\(n) \(n == 1 ? cadence.singularUnit : cadence.unit)")
                    .foregroundColor(.secondary)
            }
        }
        .onChange(of: settings[keyPath: cadence.keyPath]) { v in
            Task { await api.patchShared(["events": [cadence.configKey: v]]) }
        }
    }

    /// What the connection switch means, in its two states. A stored property
    /// rather than an inline ternary — see the note at its use site.
    private var offlineReaderNote: String { OfflineReader.availabilityNote }

    private var serverBlurb: String {
        settings.serverEnabled
            ? "Off means the app works entirely from its cache. Nothing is lost "
              + "— changes queue up and sync when you switch it back on."
            : "Working offline. Changes are saved here and will sync when you "
              + "switch this back on."
    }

    /// Says what the switch does AND what happens if you clear the card, since
    /// "it came back straight away" was the complaint that produced both.
    private var agendaCardBlurb: String {
        guard settings.agendaCardEnabled else {
            return "Off — no card on the lock screen. Switch it on to bring today's back now."
        }
        if let until = LiveActivityManager.suppressedUntil, until > Date() {
            let f = DateFormatter()
            f.dateFormat = "HH:mm"
            return "Cleared for today — back at \(f.string(from: until)). "
                 + "Switch off and on to bring it back now."
        }
        return "Today's remaining events, with the current one lit. Clear it and it stays gone until 6am."
    }

    @ViewBuilder
    private var permissionRow: some View {
        switch permStatus {
        case .some(.notDetermined):
            Button {
                Task { permStatus = await NotificationPermission.request() }
            } label: {
                Label("Allow notifications", systemImage: "bell")
            }
        case .some(.denied):
            // iOS never re-prompts a denied app — the system Settings page
            // is the only way back.
            Button {
                if let url = URL(string: UIApplication.openSettingsURLString) {
                    UIApplication.shared.open(url)
                }
            } label: {
                Label("Notifications are off — open iOS Settings", systemImage: "bell.slash")
                    .foregroundColor(.orange)
            }
        case .some:
            Label("Notifications allowed", systemImage: "checkmark.circle")
                .font(.callout).foregroundColor(.green)
        case .none:
            EmptyView()
        }
    }


    private func checkHealth() {
        urlFocused = false
        keyFocused = false
        checking = true
        healthStatus = nil
        Task {
            do {
                let h = try await api.health()
                healthStatus = "✓ \(h.llm)"
            } catch {
                healthStatus = "✗ \(error.localizedDescription) — \(settings.serverURL.isEmpty ? "no server URL set" : settings.serverURL)"
            }
            checking = false
        }
    }
}

// MARK: - The per-day switch: "keep engine events off this day"

/// Every day has one switch (DEVQA Q60, Gil 2026-09-26): on by default for
/// Shabbat and yom tov, off for chol hamoed and ordinary days, and any date
/// can be flipped either way. ON: an engine-made one-off is still added, with
/// a note, and a series skips the day. OFF: the engine books as on any day.
///
/// Two views of the same store on the Mac: a folded "This week" box (widened
/// to the whole of Sukkot or Pesach, because chol hamoed is long) and the list
/// of days you changed. The Mac names every day — `name` from the server, so
/// yom tov is called here exactly what the Mac calls it. Each flip is a `PUT`
/// of that day's state (`kept_off: null` = back to its default), so a copy
/// queued with the Mac away replays as exactly what was chosen.
///
/// The changed-days list is a small `List` inside the settings `ScrollView` —
/// swipe-to-delete exists only on a List's rows — sized to its rows and not
/// scrolling on its own.
private struct ObservanceDaysEditor: View {
    @EnvironmentObject var api: APIClient
    @State private var week: ObservanceDays?
    @State private var overrides: [ObservanceDay] = []
    @State private var weekOpen = false
    @State private var picked = Calendar.current.startOfDay(for: Date())
    @State private var pickedKeepOff = true
    @State private var note = ""

    private static let rowHeight: CGFloat = 52

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            DisclosureGroup(isExpanded: $weekOpen) {
                VStack(alignment: .leading, spacing: 6) {
                    Text("On: \((week?.label ?? "Keep engine events off this day").lowercased())")
                        .font(.caption)
                        .foregroundColor(.secondary)
                    if let days = week?.days, !days.isEmpty {
                        ForEach(days) { day in
                            Toggle(isOn: Binding(
                                get: { current(day).keptOff },
                                set: { flip(day, to: $0) })) {
                                dayLabel(current(day), withYear: false)
                            }
                            .accessibilityLabel("\(week?.label ?? "Keep engine events off"): \(Self.long(day.date))")
                        }
                    } else {
                        Text("The week appears once the Mac has answered.")
                            .font(.caption)
                            .foregroundColor(.secondary)
                    }
                }
                .padding(.top, 4)
            } label: {
                Label(week?.festival.map { "This week — all of \($0)" } ?? "This week",
                      systemImage: "calendar")
            }

            Label("Days you changed", systemImage: "calendar.badge.exclamationmark")
                .padding(.top, 4)
            if overrides.isEmpty {
                Text("None — every day follows its default.")
                    .font(.caption)
                    .foregroundColor(.secondary)
            } else {
                List {
                    ForEach(overrides) { day in
                        HStack {
                            dayLabel(day, withYear: true)
                            Spacer()
                            Text(day.keptOff ? "Kept off" : "Engine may book")
                                .font(.caption)
                                .foregroundColor(.secondary)
                        }
                        .accessibilityHint("Swipe left to put it back to its default")
                    }
                    .onDelete { offsets in
                        for i in offsets { set(overrides[i].date, keptOff: nil) }
                    }
                }
                .listStyle(.plain)
                .scrollContentBackground(.hidden)
                .scrollDisabled(true)
                .frame(height: CGFloat(overrides.count) * Self.rowHeight)
            }

            DatePicker("Day", selection: $picked, displayedComponents: .date)
            HStack {
                Picker("Set it to", selection: $pickedKeepOff) {
                    Text("Keep off").tag(true)
                    Text("Allow").tag(false)
                }
                .pickerStyle(.segmented)
                Button("Set") { set(Self.iso(picked), keptOff: pickedKeepOff) }
            }
            if !note.isEmpty {
                Text(note).font(.caption).foregroundColor(.secondary)
            }

            Text("On a day kept off, a series skips it and a one-off is added with a note. Shabbat and yom tov run candle lighting to nightfall (meals, leyning and davening excepted); any other day you keep off is the whole day. Swipe a changed day to put it back.")
                .font(.caption)
                .foregroundColor(.secondary)
        }
        .task { await reload() }
    }

    /// A row's words: "Tue 29 Sep — Chol hamoed Succos", bold with "changed"
    /// when it is not its default.
    @ViewBuilder
    private func dayLabel(_ day: ObservanceDay, withYear: Bool) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(Self.short(day.date, withYear: withYear))
                .fontWeight(day.changed ? .semibold : .regular)
            let sub = [day.name, day.changed ? "changed" : ""].filter { !$0.isEmpty }
            if !sub.isEmpty {
                Text(sub.joined(separator: " · "))
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
        }
    }

    /// The week row as the changed-days list last heard it — one source for
    /// both lists, so flipping a day in either shows in the other at once.
    private func current(_ day: ObservanceDay) -> ObservanceDay {
        overrides.first { $0.date == day.date } ?? day
    }

    private func flip(_ day: ObservanceDay, to keptOff: Bool) {
        set(day.date, keptOff: keptOff == day.defaultKeptOff ? nil : keptOff)
    }

    /// Show the change at once, then take the Mac's row for the day.
    private func set(_ iso: String, keptOff: Bool?) {
        note = ""
        let base = week?.days.first { $0.date == iso } ?? overrides.first { $0.date == iso }
        if var row = base {
            row.keptOff = keptOff ?? row.defaultKeptOff
            row.override = keptOff == nil || keptOff == row.defaultKeptOff ? nil
                : (keptOff! ? "keep_off" : "allow")
            apply(row)
        }
        Task {
            if let saved = await api.setObservanceDay(iso, keptOff: keptOff) {
                apply(saved)
                if keptOff != nil && saved.override == nil {
                    note = "\(Self.short(iso, withYear: false)) is already \(saved.keptOff ? "kept off" : "open to the engine") by default."
                }
            }
        }
    }

    private func apply(_ row: ObservanceDay) {
        if var w = week, let i = w.days.firstIndex(where: { $0.date == row.date }) {
            var days = w.days
            days[i] = row
            w = ObservanceDays(label: w.label, festival: w.festival, days: days)
            week = w
        }
        overrides.removeAll { $0.date == row.date }
        if row.changed {
            overrides.append(row)
            overrides.sort { $0.date < $1.date }
        }
    }

    private func reload() async {
        async let w = api.observanceWeek()
        async let o = api.observanceOverrides()
        week = await w
        overrides = await o?.days ?? []
    }

    private static func iso(_ d: Date) -> String {
        ISO8601DateFormatter.yyyyMMdd.string(from: d)
    }

    private static func short(_ iso: String, withYear: Bool) -> String {
        guard let d = ISO8601DateFormatter.yyyyMMdd.date(from: iso) else { return iso }
        let f = DateFormatter()
        f.dateFormat = withYear ? "EEE d MMM yyyy" : "EEE d MMM"
        return f.string(from: d)
    }

    private static func long(_ iso: String) -> String {
        guard let d = ISO8601DateFormatter.yyyyMMdd.date(from: iso) else { return iso }
        let f = DateFormatter()
        f.dateFormat = "EEEE d MMMM"
        return f.string(from: d)
    }
}

// MARK: - A settings page, and a row's icon

/// One page behind a row of the Settings list (2026-09-28 reorganisation).
/// The card look the fold-open sections had — a GroupBox on the grouped
/// background — so each page's controls look exactly as they did.
private struct SettingsPage<Content: View>: View {
    private let title: String
    private let content: Content

    init(_ title: String, @ViewBuilder content: () -> Content) {
        self.title = title
        self.content = content()
    }

    var body: some View {
        ScrollView {
            GroupBox {
                VStack(alignment: .leading, spacing: 12) { content }
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding()
        }
        .background(Color(.systemGroupedBackground).ignoresSafeArea())
        .navigationTitle(title)
        .navigationBarTitleDisplayMode(.inline)
    }
}

/// The ⓘ beside a setting whose effect is not obvious from its name (Gil,
/// 2026-09-29: "add info tooltip for non trivial features") — a small
/// popover on iOS 16.4+, an alert before. The Mac's calendar_ui/info_tip.py
/// is the same idea, and its texts say the same things.
/// Emoji in titles (TASKS 51) — the same setting under Assistant and under
/// Easter egg (Gil asked for both), shared with the Mac as `title_emoji.count`.
struct TitleEmojiPicker: View {
    @EnvironmentObject var settings: AppSettings
    @EnvironmentObject var api: APIClient

    var body: some View {
        Picker(selection: $settings.titleEmojiCount) {
            Text("None").tag(0)
            Text("One").tag(1)
            Text("Two").tag(2)
        } label: {
            HStack(spacing: 6) {
                SettingsIcon("face.smiling", .pink)
                Text("Icons beside titles")
                InfoTip("An event or to-do whose title clearly names something gets its drawing beside it — a dog for “walk my dog”, a heart for “date with Noa”. A word with two meanings only gets one in the right one: “due date” and “eat a date” stay plain. The title itself stays words.")
            }
        }
        .accessibilityIdentifier("title-emoji-picker")
        .onChange(of: settings.titleEmojiCount) { v in
            Task { await api.patchShared(["title_emoji": ["count": v]]) }
        }
        if settings.titleEmojiCount > 0 {
            NavigationLink {
                TitleEmojiKindsView()
            } label: {
                HStack {
                    Text("Which kinds")
                    Spacer()
                    Text(settings.titleEmojiOff.isEmpty ? "All"
                         : "\(TitleEmojiKind.all.count - settings.titleEmojiOff.count) of \(TitleEmojiKind.all.count)")
                        .foregroundColor(.secondary)
                }
            }
            .accessibilityIdentifier("title-emoji-kinds")
        }
    }
}

/// The kinds of words that get a drawing, as `title_icons.GROUPS` and
/// `GROUP_ICONS` on the Mac (`test_title_icons.py` holds the lists equal).
struct TitleEmojiKind: Identifiable {
    let key: String
    let label: String
    let icon: String
    var id: String { key }
    static let all: [TitleEmojiKind] = [
        .init(key: "animals", label: "Animals", icon: "dog"),
        .init(key: "sport", label: "Sport & fitness", icon: "run"),
        .init(key: "health", label: "Health", icon: "tooth"),
        .init(key: "food", label: "Food & drink", icon: "coffee"),
        .init(key: "occasions", label: "Occasions", icon: "cake"),
        .init(key: "travel", label: "Travel", icon: "plane"),
        .init(key: "home", label: "Home & errands", icon: "broom"),
        .init(key: "work", label: "Work & study", icon: "books"),
        .init(key: "jewish", label: "Jewish life", icon: "candles"),
    ]
}

/// One switch per kind: which kinds of words may get an emoji.
struct TitleEmojiKindsView: View {
    @EnvironmentObject var settings: AppSettings
    @EnvironmentObject var api: APIClient

    var body: some View {
        Form {
            Section {
                ForEach(TitleEmojiKind.all) { kind in
                    Toggle(isOn: Binding(
                        get: { !settings.titleEmojiOff.contains(kind.key) },
                        set: { on in
                            settings.titleEmojiOff.removeAll { $0 == kind.key }
                            if !on { settings.titleEmojiOff.append(kind.key) }
                            Task { await api.patchShared(["title_emoji": [kind.key: on]]) }
                        })) {
                        Label { Text(kind.label) } icon: { Ico(kind.icon, size: 18) }
                    }
                    .accessibilityIdentifier("title-emoji-kind-\(kind.key)")
                }
            } footer: {
                Text("Off, words of that kind get no drawing. Shared with your Mac.")
            }
        }
        .navigationTitle("Icon kinds")
    }
}

struct InfoTip: View {
    let text: String
    @State private var shown = false

    init(_ text: String) { self.text = text }

    var body: some View {
        Button { shown = true } label: {
            Image(systemName: "info.circle").foregroundColor(.secondary)
        }
        .buttonStyle(.borderless)
        .accessibilityLabel("More about this setting")
        .modifier(InfoTipPresenter(text: text, shown: $shown))
    }
}

private struct InfoTipPresenter: ViewModifier {
    let text: String
    @Binding var shown: Bool

    func body(content: Content) -> some View {
        if #available(iOS 16.4, *) {
            content.popover(isPresented: $shown) {
                Text(text)
                    .font(.callout)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding()
                    .frame(maxWidth: 320)
                    .presentationCompactAdaptation(.popover)
            }
        } else {
            content.alert("About this setting", isPresented: $shown) {
                Button("OK", role: .cancel) {}
            } message: { Text(text) }
        }
    }
}

/// The small coloured tile iOS's own Settings puts before each row.
private struct SettingsIcon: View {
    private let name: String
    private let tint: Color
    init(_ name: String, _ tint: Color) { self.name = name; self.tint = tint }

    var body: some View {
        Image(systemName: name)
            .font(.system(size: 14, weight: .semibold))
            .foregroundColor(.white)
            .frame(width: 28, height: 28)
            .background(RoundedRectangle(cornerRadius: 7).fill(tint))
            .padding(.trailing, 4)
    }
}
