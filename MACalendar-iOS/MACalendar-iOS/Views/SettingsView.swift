import SwiftUI
import AVFoundation
import UIKit
import UserNotifications

struct SettingsView: View {
    @EnvironmentObject var settings: AppSettings
    @EnvironmentObject var api: APIClient
    @ObservedObject private var visibility = FeatureVisibility.shared
    @State private var healthStatus: String? = nil
    @State private var checking = false
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
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {

                    // MARK: Server
                    CollapsibleSection("Server", systemImage: "network", key: "server") {
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

                    // MARK: Appearance
                    CollapsibleSection("Appearance", systemImage: "paintbrush", key: "appearance") {
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

                    // MARK: Hebrew Calendar
                    CollapsibleSection("Hebrew Calendar", systemImage: "calendar.badge.clock", key: "hebrew") {
                        VStack(alignment: .leading, spacing: 12) {
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
                            Toggle("Israel holiday schedule", isOn: $settings.israelHolidays)
                                .onChange(of: settings.israelHolidays) { v in
                                    Task { await api.patchShared(
                                        ["hebrew_calendar": ["israel_holidays": v]]) }
                                }
                                .disabled(!settings.showHolidays)

                            Text("Hebrew dates use gematria letters (e.g. כ״ט תשרי). Holidays begin at sundown the evening before their main day.")
                                .font(.caption)
                                .foregroundColor(.secondary)

                            Divider().padding(.vertical, 2)

                            Toggle("Mark when Shabbat & yom tov begin and end", isOn: $settings.showShabbatTimes)
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

                            Toggle("Sundown follows this device", isOn: $settings.followMyLocation)
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
                        }
                        .padding(.top, 4)
                    }

                    // MARK: Events
                    //
                    // DEVQA Q51 (Gil, 2026-09-25): how long an event lasts when
                    // no end is said, and the gap between chained events.
                    // Shared with the Mac (`events:` in config.yaml); a
                    // category can set its own in Assistant › Event colours.
                    CollapsibleSection("Events", systemImage: "clock", key: "events") {
                        VStack(alignment: .leading, spacing: 12) {
                            Stepper(value: $settings.eventLengthMinutes,
                                    in: EventDefaults.minLength...EventDefaults.maxMinutes, step: 5) {
                                HStack {
                                    Label("Default length", systemImage: "hourglass")
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
                                    Spacer()
                                    Text("\(settings.chainGapMinutes) min")
                                        .foregroundColor(.secondary)
                                }
                            }
                            .onChange(of: settings.chainGapMinutes) { v in
                                Task { await api.patchShared(
                                    ["events": ["chain_gap_minutes": v]]) }
                            }
                            Text("An event with no end said lasts the default length. In “gym at 9, then lunch”, lunch starts this gap after the gym ends. A category can set its own of either in Assistant › Event colours.")
                                .font(.caption)
                                .foregroundColor(.secondary)
                        }
                        .padding(.vertical, 4)
                    }

                    // MARK: Notifications
                    //
                    // ONE switch (Gil, 2026-09-11: "it's on or off"). This
                    // replaced a lead-time menu, a per-category lead menu and
                    // a master toggle — three controls deciding when each of
                    // fifty-five banners would interrupt you, for a feature
                    // whose answer turned out to be "once, in the morning".
                    // "Notifications" is what the Mac's settings dialog calls
                    // the same section (`settings_dialog.py`), and Gil went
                    // looking for that word and could not find it here
                    // (2026-09-18). The `key:` stays "panel" on purpose — it
                    // stores whether the section is folded, and renaming it
                    // would spring open every screen that had it closed.
                    CollapsibleSection("Notifications", systemImage: "bell.badge", key: "panel") {
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
                                    now: Date(), events: LocalStore.shared.allEvents())
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

                            Toggle("Quiet on Shabbat & chagim", isOn: Binding(
                                get: { notifConfig?.respectObservance ?? true },
                                set: { on in
                                    notifConfig?.respectObservance = on
                                    Task {
                                        await api.patchNotifications(["respect_observance": on])
                                        await api.refreshDigests()
                                    }
                                }))
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

                    // MARK: Connected Calendars
                    //
                    // Google / Outlook two-way and read-only iCal links (Gil,
                    // 2026-09-24). The Mac holds the sign-ins and runs the
                    // sync; this screen, like the Mac's, only starts a
                    // connection and shows how it is going.
                    CollapsibleSection("Connected Calendars", systemImage: "calendar.badge.plus", key: "calendars") {
                        NavigationLink {
                            ConnectedCalendarsView()
                        } label: {
                            HStack {
                                Label("Google, Outlook & links", systemImage: "link")
                                Spacer()
                                Text("Sync automatically")
                                    .font(.caption).foregroundColor(.secondary)
                                Image(systemName: "chevron.right")
                                    .font(.caption).foregroundColor(.secondary)
                            }
                        }
                        .padding(.vertical, 4)
                    }

                    // MARK: Tabs
                    //
                    // ONE loop over the registry, not five hand-written toggles:
                    // a feature appears here by being declared in
                    // `FeatureRegistry`, never by someone remembering to add a
                    // row. Pinned features (Calendar, Tasks) are not offered at
                    // all — they are what the app IS, and the Mac answers 409 to
                    // a request to hide one.
                    CollapsibleSection("Tabs", systemImage: "square.grid.2x2", key: "tabs") {
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
                    .padding(.top, 4)

                    // MARK: Voice
                    CollapsibleSection("Voice", systemImage: "speaker.wave.2", key: "voice") {
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

                    // MARK: Assistant
                    //
                    // Split out of Voice on 2026-09-18. Four screens about
                    // TEACHING the assistant — reviewing what it did, the words
                    // it should hear, the words it acts on, the colours it
                    // assigns — were sitting inside a section about the
                    // MICROPHONE, and a collapsed one at that. Gil went looking
                    // for "How I Say Things" on the settings screen and could
                    // not see it, because the only thing on screen was the word
                    // "Voice". The Mac has had an Assistant section all along;
                    // this is the same section, in the same order.
                    CollapsibleSection("Assistant", systemImage: "sparkles", key: "assistant") {
                        VStack(alignment: .leading, spacing: 12) {
                            NavigationLink {
                                AssistantReviewView()
                            } label: {
                                HStack {
                                    Label("Review commands", systemImage: "checkmark.bubble")
                                    Spacer()
                                    if unreviewed > 0 {
                                        Text("\(unreviewed)")
                                            .font(.caption.weight(.semibold))
                                            .padding(.horizontal, 7).padding(.vertical, 2)
                                            .background(settings.accentColor.opacity(0.2))
                                            .foregroundColor(settings.accentColor)
                                            .clipShape(Capsule())
                                    } else {
                                        Text("Was it right? Tap yes or no").font(.caption).foregroundColor(.secondary)
                                    }
                                    Image(systemName: "chevron.right").font(.caption).foregroundColor(.secondary)
                                }
                            }

                            NavigationLink {
                                VocabularyView()
                            } label: {
                                HStack {
                                    Label("Vocabulary", systemImage: "character.book.closed")
                                    Spacer()
                                    Text("Names & words it should know")
                                        .font(.caption).foregroundColor(.secondary)
                                    Image(systemName: "chevron.right")
                                        .font(.caption).foregroundColor(.secondary)
                                }
                            }

                            // The Mac's "How to Talk to Me" (Settings →
                            // Assistant), on the phone too — the same five
                            // tips, fetched from the host so there is one copy.
                            NavigationLink {
                                TipsView()
                            } label: {
                                HStack {
                                    Label("How to Talk to Me", systemImage: "lightbulb")
                                    Spacer()
                                    Text("Five ways to phrase it")
                                        .font(.caption).foregroundColor(.secondary)
                                    Image(systemName: "chevron.right")
                                        .font(.caption).foregroundColor(.secondary)
                                }
                            }

                            // The word lists the ENGINE matches on, as opposed
                            // to the Vocabulary above, which is what WHISPER
                            // should hear. Two different failures: "Conello
                            // oil" is a mishearing, "squeeze" is a word the
                            // parser has simply never been taught.
                            NavigationLink {
                                LexiconView()
                            } label: {
                                HStack {
                                    Label("How I Say Things", systemImage: "text.book.closed")
                                    Spacer()
                                    Text("Words it acts on")
                                        .font(.caption).foregroundColor(.secondary)
                                    Image(systemName: "chevron.right")
                                        .font(.caption).foregroundColor(.secondary)
                                }
                            }

                            NavigationLink {
                                CategoriesView()
                            } label: {
                                HStack {
                                    Label("Event colours", systemImage: "paintpalette")
                                    Spacer()
                                    Text("Categories & colours")
                                        .font(.caption).foregroundColor(.secondary)
                                    Image(systemName: "chevron.right")
                                        .font(.caption).foregroundColor(.secondary)
                                }
                            }
                        }
                        .padding(.vertical, 4)
                    }

                    // MARK: About
                    CollapsibleSection("About", systemImage: "info.circle", key: "about") {
                        HStack {
                            Text("Version")
                            Spacer()
                            Text("1.0").foregroundColor(.secondary)
                        }
                        Divider()
                        Link("GitHub", destination: URL(string: "https://github.com/GilCaplan/MACalendar")!)
                    }
                }
                .padding()
            }
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
    }

    /// What the connection switch means, in its two states. A stored property
    /// rather than an inline ternary — see the note at its use site.
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

// MARK: - Collapsible section

/// A settings section that folds away, remembering whether it was open.
///
/// Gil, 2026-09-17: *"perhaps add a minimize on each section starting to be a
/// lot of things there"* — seven sections had grown past what one screen can
/// hold, and the two anyone actually visits (Server, Notifications) sit above
/// and below things nobody touches twice.
///
/// It wraps `GroupBox` rather than replacing it, so every section keeps exactly
/// the look it had; the only change is a header you can tap. State lives in
/// `@AppStorage` under `settingsSection.<key>`, which is per-device UI chrome
/// and deliberately NOT part of the shared config — which sections you keep
/// folded on your phone is not a thing the Mac should have an opinion about.
private struct CollapsibleSection<Content: View>: View {
    private let title: String
    private let systemImage: String
    @AppStorage private var expanded: Bool
    private let content: () -> Content

    init(_ title: String, systemImage: String, key: String,
         @ViewBuilder content: @escaping () -> Content) {
        self.title = title
        self.systemImage = systemImage
        self.content = content
        // FOLDED by default (Gil, 2026-09-18: "By default can everything be
        // minimized in settings"). This used to open every section, with the
        // note "a first run must not look like an empty screen" — but seven
        // sections open is a screen you scroll through to find anything, and
        // the thing that was actually hard to find was a section NAME. Folded,
        // the whole list of names fits at once and is its own table of
        // contents.
        //
        // Only sections you have never touched are affected: `AppStorage`
        // writes on change, not on read, so anyone who deliberately opened or
        // closed one keeps that choice.
        _expanded = AppStorage(wrappedValue: false, "settingsSection.\(key)")
    }

    var body: some View {
        GroupBox {
            if expanded { content() }
        } label: {
            Button {
                withAnimation(.easeInOut(duration: 0.18)) { expanded.toggle() }
            } label: {
                HStack(spacing: 8) {
                    Label(title, systemImage: systemImage)
                    Spacer(minLength: 8)
                    Image(systemName: "chevron.down")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                        .rotationEffect(.degrees(expanded ? 0 : -90))
                }
                // The whole row is the target, not just the words — and 44pt
                // tall, which is the smallest thing a finger should be asked
                // to hit.
                .frame(minHeight: 44)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel(title)
            .accessibilityHint(expanded ? "Collapse this section" : "Expand this section")
            .accessibilityAddTraits(expanded ? [.isSelected] : [])
        }
    }
}
