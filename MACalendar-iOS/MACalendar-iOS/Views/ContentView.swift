import SwiftUI
import UIKit

/// The shell the features live in: the offline/queue banners, the tab bar, and
/// the sheets that belong to no single tab.
///
/// It knows THAT there are features and nothing about WHICH ones. The tab bar,
/// the layer stack and the bounce-off are one loop each over
/// `FeatureRegistry.all` — see `Features/FeatureRegistry.swift` for why:
/// those three used to be hand-synced lists, and Timer's missing bounce-off
/// handler left a blank screen with a working tab bar under it.
struct ContentView: View {
    @EnvironmentObject var api: APIClient
    @EnvironmentObject var settings: AppSettings
    @ObservedObject private var store = LocalStore.shared
    @ObservedObject private var visibility = FeatureVisibility.shared
    @ObservedObject private var router = FeatureRouter.shared
    @Environment(\.scenePhase) private var scenePhase

    /// A mined new-tag proposal to confirm (server rate-limits to ~one/week).
    @State private var tagSuggestion: TagSuggestion? = nil
    @State private var showTagSuggestion = false
    @State private var showVocabOnboarding = false
    @State private var showVoiceQueue = false
    @ObservedObject private var importInbox = ImportInbox.shared
    @ObservedObject private var notifRouter = NotificationRouter.shared
    @State private var sharedImportText: String? = nil
    @State private var unreviewed = 0
    @State private var showReview = false
    // Settings moved OUT of the tab set (Gil, 2026-09-17: "I don't want
    // More -> Settings, just Settings" — every content tab, Jude included,
    // has to be a direct peer with no fold-away menu in between). It is a
    // sheet from a persistent gear button instead, one tap from any tab.
    @State private var showSettings = false
    /// The pending-changes queue, opened from the offline banner or Settings.
    @State private var showQueue = false

    /// The tab on screen, as a feature NAME. It was an `Int` with a hole at
    /// tag 3 where Settings used to be, which encoded nothing and could not be
    /// matched against the Mac, the config or the API.
    private var selectedFeature: String { router.selected }

    /// The content tabs, in display order — everything BUT Settings, which
    /// isn't one of these any more. Visibility comes from the local cache, so
    /// this answers with the Mac asleep; structure comes from the registry.
    private var contentTabs: [Feature] { visibility.visible }

    /// A native `TabView` folds anything past 5 items into "More", which is
    /// exactly the thing being avoided here — so this isn't one. Every
    /// content tab is ALWAYS a direct, equal button; if there are more than
    /// fit the screen at once, the row scrolls rather than hiding any of
    /// them behind an extra tap. Settings pins to the trailing edge, outside
    /// the scrolling region, so it never needs a scroll either.
    /// The narrowest a tab may be before the row has to scroll instead.
    private static let minTabWidth: CGFloat = 58

    private var customTabBar: some View {
        GeometryReader { geo in
            // Settings is pinned outside the scrolling region, so it is taken
            // off the top and the content tabs share what is left.
            let reserved = Self.minTabWidth + 9          // the button + its divider
            let available = max(geo.size.width - reserved, 0)
            let fits = CGFloat(contentTabs.count) * Self.minTabWidth <= available

            HStack(spacing: 0) {
                Group {
                    if fits {
                        // They fit, so SPREAD them across the width.
                        //
                        // This used to be a ScrollView unconditionally, and a
                        // horizontal ScrollView aligns its content to the
                        // LEADING edge — so five tabs in a row sized for eight
                        // clumped to the left and left a dead gap before the
                        // divider. Hiding a tab made that gap BIGGER, which is
                        // precisely when the row is supposed to look tidier.
                        HStack(spacing: 0) {
                            ForEach(contentTabs) { feature in
                                tabBarButton(feature).frame(maxWidth: .infinity)
                            }
                        }
                    } else {
                        // Genuinely too many to show at once: scroll rather
                        // than squeeze them into something unreadable, and
                        // still never fold any away behind a "More" tab.
                        ScrollView(.horizontal, showsIndicators: false) {
                            HStack(spacing: 0) {
                                ForEach(contentTabs) { feature in
                                    tabBarButton(feature)
                                }
                            }
                        }
                    }
                }
                .frame(width: available)

                Divider().frame(height: 30)
                Button { showSettings = true } label: {
                    tabBarLabel(label: "Settings", icon: "gear", selected: false)
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("tab-settings")
                .frame(width: Self.minTabWidth)
            }
        }
        .frame(height: 46)
        .padding(.top, 6)
        .padding(.bottom, 2)
        .background(Color(.secondarySystemBackground))
        .overlay(Divider(), alignment: .top)
    }

    private func tabBarButton(_ feature: Feature) -> some View {
        Button {
            withAnimation(.easeInOut(duration: 0.15)) { router.show(feature.name) }
        } label: {
            tabBarLabel(label: feature.label, icon: feature.icon,
                        selected: selectedFeature == feature.name)
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("tab-\(feature.name)")
        .accessibilityAddTraits(selectedFeature == feature.name ? .isSelected : [])
    }

    private func tabBarLabel(label: String, icon: String, selected: Bool) -> some View {
        VStack(spacing: 3) {
            Image(systemName: icon).font(.system(size: 21))
            // One line, shrinking a little rather than truncating: "Coursework"
            // is the longest label and is what made the row look crowded.
            Text(label)
                .font(.system(size: 10))
                .lineLimit(1)
                .minimumScaleFactor(0.85)
        }
        .foregroundColor(selected ? settings.accentColor : .secondary)
        .frame(minWidth: Self.minTabWidth)
        .padding(.vertical, 2)
    }

    var body: some View {
        VStack(spacing: 0) {

            // Offline banner.
            //
            // Two different states wearing one banner would be a mistake: a Mac
            // that is ASLEEP is something to tell the user about, and a
            // connection they SWITCHED OFF is not a problem at all. Same
            // information — what is queued — in a calmer voice, and grey rather
            // than orange, because nothing is wrong.
            if !settings.serverEnabled || !api.isOnline {
                let chosen = !settings.serverEnabled
                let pending = store.pendingCount
                HStack(spacing: 6) {
                    Image(systemName: chosen ? "icloud.slash" : "wifi.slash")
                    Text(chosen
                         ? (pending > 0
                            ? "Working offline — \(pending) change\(pending == 1 ? "" : "s") will sync when you reconnect"
                            : "Working offline")
                         : (pending > 0
                            ? "Offline — \(pending) change\(pending == 1 ? "" : "s") pending sync"
                            : "Offline — changes saved locally"))
                        .accessibilityIdentifier("offline-banner")
                    Spacer()
                }
                .font(.caption.weight(.medium))
                .foregroundColor(.white)
                .padding(.horizontal, 14)
                .padding(.vertical, 7)
                .background(chosen ? Color.secondary : Color.orange)
                .contentShape(Rectangle())
                // The banner already says how many are waiting; tapping it to
                // see WHICH is the obvious next question, and the queue is
                // where you answer it.
                .onTapGesture { if pending > 0 { showQueue = true } }
            }

            // A write the Mac ANSWERED and refused. Nothing will replay it — one
            // it never received would have been queued instead — so this is the
            // failure that has to be said out loud rather than absorbed, which
            // is what `try?` used to do with all of them. Tap to dismiss.
            if let refusal = api.lastRefusal {
                Button { api.lastRefusal = nil } label: {
                    HStack(spacing: 6) {
                        Image(systemName: "exclamationmark.triangle.fill")
                        Text(refusal).multilineTextAlignment(.leading)
                        Spacer()
                        Image(systemName: "xmark")
                    }
                    .font(.caption.weight(.medium))
                    .foregroundColor(.white)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 7)
                    .background(Color.red)
                }
                .buttonStyle(.plain)
            }

            // Voice commands parked because the Mac was away. Shown whether or
            // not we're online: while offline so you know it was kept, and after
            // reconnecting so you can see what it went on to do.
            if !store.pendingVoice.isEmpty {
                Button { showVoiceQueue = true } label: {
                    HStack(spacing: 8) {
                        Image(systemName: voiceQueueIcon)
                        Text(voiceQueueSummary).font(.footnote.weight(.medium))
                        Spacer()
                        Text("Show").font(.footnote.weight(.semibold))
                    }
                    .padding(.horizontal, 14).padding(.vertical, 8)
                    .background(Color.orange.opacity(0.20))
                    .foregroundColor(.primary)
                }
                .buttonStyle(.plain)
            }

            if unreviewed >= 5 {
                Button { showReview = true } label: {
                    HStack(spacing: 8) {
                        Image(systemName: "checkmark.bubble")
                        Text("\(unreviewed) voice commands to review — was the assistant right?")
                            .font(.footnote.weight(.medium))
                        Spacer()
                        Text("Review").font(.footnote.weight(.semibold))
                    }
                    .padding(.horizontal, 14).padding(.vertical, 8)
                    .background(settings.accentColor.opacity(0.18))
                    .foregroundColor(.primary)
                }
                .buttonStyle(.plain)
            }

            tabContent
            customTabBar
        }
        // ONE bounce-off for all seven features, instead of the per-tab
        // `onChange` handlers this replaced — Timer never got one, so hiding it
        // while it was on screen left the selection pointing at a layer the
        // stack no longer builds: a blank screen with a working tab bar.
        .onChange(of: visibility.map) { _ in
            withAnimation(.easeInOut(duration: 0.15)) {
                router.bounceOffHidden(visibility)
            }
        }
        // Switching the connection back on is a reconnect: flush what queued
        // up while it was off, rather than waiting for the 30s tick.
        .onChange(of: settings.serverEnabled) { on in
            guard on else { return }
            Task {
                _ = await api.syncPending()
                await api.syncPendingVoice()
                // Today's window: the calendar owns which month is on screen
                // now, and it refreshes itself off `requestRefresh()` below.
                let now = Date()
                await api.bootstrap(
                    year: Calendar.current.component(.year, from: now),
                    month: Calendar.current.component(.month, from: now),
                    israel: settings.israelHolidays)
                api.requestRefresh()
            }
        }
        .onChange(of: scenePhase) { phase in
            // Leaving the app is the deadline for the debounced cache write:
            // "in 150ms" is a promise the system need not keep once we are in
            // the background, and a lost cache means the next launch draws
            // nothing until the Mac answers — the exact lag the debounce was
            // added to remove.
            if phase != .active { LocalStore.shared.flushCachesNow() }
            if phase == .active {
                // Fire-and-forget presence ping, separate from the sync path
                // so an unreachable Mac can't delay the local refresh below.
                // heartbeat() swallows its own failures — offline is normal.
                Task { await api.heartbeat() }
                Task {
                    _ = await api.syncPending()
                    await api.syncPendingVoice()
                    // Always re-fetch on foreground: the Mac app may have changed things.
                    // The bootstrap refreshes what the poll loop never asks for
                    // again — the tag palette, the tag classifier's table, the
                    // holidays — and warms the neighbouring months' cache.
                    await api.bootstrap(
                        year: Calendar.current.component(.year, from: CalendarNavigator.shared.viewedDate),
                        month: Calendar.current.component(.month, from: CalendarNavigator.shared.viewedDate),
                        israel: settings.israelHolidays)
                    CalendarNavigator.shared.reload()
                    // A tab may have been switched on or off from the Mac while
                    // this phone was in someone's pocket. Cheap, and never
                    // blocking: the tab bar is already on screen from the cache.
                    await visibility.refresh(api: api)
                    await refreshWorkoutIfNeeded()
                    // The panels are SCHEDULED ahead, so this is the moment
                    // that keeps tomorrow morning's accurate — foregrounding
                    // is the main execution time iOS gives us.
                    await api.refreshDigests()
                    api.requestRefresh()
                    // Re-mirror reminders after the foreground sync — cheap
                    // and idempotent (cacheEvents also triggers it; this
                    // covers the offline foreground where nothing was fetched).
                    ReminderScheduler.shared.reconcile()
                    // Foregrounding is the main moment iOS gives us execution
                    // time, and therefore the main chance to roll the lock
                    // screen card onto the event that has since started.
                    LiveActivityManager.shared.sync()
                }
            }
        }
        .sheet(isPresented: $showVocabOnboarding) {
            VocabOnboardingView()
        }
        .sheet(isPresented: $showVoiceQueue) {
            VoiceQueueView()
        }
        .sheet(isPresented: $showReview, onDismiss: { Task { unreviewed = await api.unreviewedCount() } }) {
            AssistantReviewView()
        }
        .onReceive(importInbox.$pendingText) { t in
            if let t { sharedImportText = t; importInbox.pendingText = nil }
        }
        // A tapped "evt-*" reminder lands here (NotificationRouter is the
        // UNUserNotificationCenter delegate). Bring the calendar forward and
        // point it at the event's date — `CalendarNavigator` is the seam the
        // calendar feature exposes for exactly this.
        .onReceive(notifRouter.$pendingEventId) { id in
            guard let id else { return }
            notifRouter.pendingEventId = nil
            if let e = LocalStore.shared.event(id),
               let d = DateFormatter.isoDay.date(from: e.date) {
                CalendarNavigator.shared.show(d)
            } else {
                CalendarNavigator.shared.reload()
            }
            router.show(FeatureRegistry.home)
        }
        // A tapped day panel lands here: it summarised ONE day, so open that
        // day rather than today — tapping Thursday's panel on Friday morning
        // should not show Friday.
        .onReceive(notifRouter.$pendingDay) { day in
            guard let day else { return }
            notifRouter.pendingDay = nil
            if let d = DateFormatter.isoDay.date(from: day) {
                CalendarNavigator.shared.show(d)
            } else {
                CalendarNavigator.shared.reload()
            }
            router.show(FeatureRegistry.home)
        }
        .sheet(isPresented: Binding(get: { sharedImportText != nil }, set: { if !$0 { sharedImportText = nil } })) {
            VocabImportView(initialText: sharedImportText, initialName: importInbox.pendingName)
        }
        .task {
            // Wire the Workout store up to the network layer once, so its
            // local mutations (saveTemplate, finishSession, etc.) can push
            // themselves to the server immediately — see WorkoutStore.configure.
            // No network of its own, so it goes first.
            WorkoutStore.shared.configure(api: api)

            // ONE request for everything a cold start needs — events for three
            // months, tasks, the tag palette, the tag classifier's table and
            // the holidays (DOCUMENTATION/SYNC_PROTOCOL.md).
            //
            // This preamble used to be a handful of separate GETs run one after
            // another — `vocabOnboarding` twice, `unreviewedCount`, then the
            // month and its holidays — so opening the app away from the Mac
            // spent tens of seconds on timeouts before anything fell back to
            // caches it already had. Now: one timeout at worst, none at all
            // once the client's offline circuit breaker has tripped.
            var lastToken: String? = await api.bootstrap(
                year: Calendar.current.component(.year, from: CalendarNavigator.shared.viewedDate),
                month: Calendar.current.component(.month, from: CalendarNavigator.shared.viewedDate),
                israel: settings.israelHolidays)
            CalendarNavigator.shared.reload()

            // The startup chores, off the critical path: none of them decides
            // what the first screen looks like, so none of them should be able
            // to delay it. Which tabs are switched on is one of them — the bar
            // is already drawn from the cache before this asks.
            Task {
                await visibility.refresh(api: api)

                // The week's day panels. Off the critical path on purpose —
                // nothing on screen depends on them; they are notifications
                // being lodged for mornings this app may not be open for.
                await api.refreshDigests()

                // First run: once the Mac is reachable and the vocabulary hasn't
                // been set up, ask the user to teach the assistant their words.
                if let ob = try? await api.vocabOnboarding() {
                    if ob.done {
                        settings.vocabOnboardingDone = true
                    } else if !settings.vocabOnboardingDone, !settings.serverURL.isEmpty {
                        showVocabOnboarding = true
                    }
                }

                // Tell the host where we are, so sundown is computed for here
                // rather than for wherever it was configured. One reading, only
                // when it has moved far enough to change an answer, and only to
                // your own host.
                if settings.followMyLocation {
                    DeviceLocation.shared.refresh(using: api)
                }

                unreviewed = await api.unreviewedCount()
            }

            // While the app is open, retry sync every 30 s so pending
            // changes upload as soon as the Mac comes back online.
            var slept: TimeInterval = 0
            var sinceTokenCheck: TimeInterval = 0
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 1_000_000_000)
                slept += 1
                sinceTokenCheck += 1

                // Between full refreshes, ask the Mac the cheap question: has
                // anything changed? A few bytes every 2 s beats waiting up to
                // 30 s to notice an event added on the other device.
                if sinceTokenCheck >= 2, slept < api.pollInterval,
                   UIApplication.shared.applicationState == .active {
                    sinceTokenCheck = 0
                    if let token = await api.changeToken() {
                        if let previous = lastToken, previous != token {
                            lastToken = token
                            slept = 0
                            CalendarNavigator.shared.reload()
                            api.requestRefresh()
                            // Something changed on the Mac, so what the day
                            // panel would SAY changed with it — and the panel
                            // for tomorrow is already lodged with iOS, holding
                            // the old wording until it is replaced.
                            await api.refreshDigests()
                            ReminderScheduler.shared.reconcile()
                            // …and the card may now be pointing at an event
                            // that was moved or deleted on the Mac.
                            LiveActivityManager.shared.sync()
                            continue
                        }
                        lastToken = token
                    }
                }

                guard slept >= api.pollInterval else { continue }
                slept = 0
                sinceTokenCheck = 0

                // Refresh only when the Mac says something moved. This used to
                // fetch the token and then refresh regardless, which was merely
                // wasteful at the 30 s interval and pathological during a burst:
                // burst sets pollInterval to 1, so the six list endpoints were
                // refetched every second for 45 seconds — and the cheap token
                // check above is skipped entirely while bursting, because its
                // guard is `slept < pollInterval` and `slept < 1` is never true.
                // Burst is supposed to mean "ask the cheap question often", not
                // "reload everything constantly".
                let token = await api.changeToken()
                let unchanged = token != nil && token == lastToken
                lastToken = token ?? lastToken
                // Read the live application state, NOT the `scenePhase` environment
                // value: `.task` captures the View struct, so `scenePhase` here is
                // frozen at whatever it was when the task started — `.inactive`,
                // because the scene has not finished activating during the first
                // render. Guarding on that captured copy silently disabled this
                // whole loop, so nothing changed on the Mac ever reached the phone
                // until the app was backgrounded and reopened.
                guard UIApplication.shared.applicationState == .active else { continue }

                // Clock-driven, not data-driven: nothing about the calendar has
                // to change for the card to go wrong — the event simply starts.
                // This tick is the only thing that flips "in 0:02" to "Now:"
                // while the app sits open, so it runs before the early-outs
                // below and regardless of whether the Mac has anything new.
                LiveActivityManager.shared.sync()

                if !api.isOnline { _ = try? await api.health() }   // flips isOnline (+refresh) when the Mac is back
                _ = await api.syncPending()
                await api.syncPendingVoice()

                // Nothing changed on the Mac and nothing of ours was waiting to
                // go up: there is nothing to fetch. Anything this device just
                // did writes to the Mac and moves the token, so a local change
                // still refreshes on the next tick.
                if unchanged { continue }

                // Poll: keep the phone in step with whatever was changed on the Mac.
                CalendarNavigator.shared.reload()
                api.requestRefresh()
            }
        }
        // Tag discovery (Gil, 2026-09-05): the app may propose a NEW tag class
        // mined from untagged history — at most ~one ask a week, enforced
        // server-side; this only pulls while the app is actively open.
        .task {
            try? await Task.sleep(nanoseconds: 20_000_000_000)   // let the session settle
            guard UIApplication.shared.applicationState == .active else { return }
            if let s = await api.tagSuggestion() {
                tagSuggestion = s
                showTagSuggestion = true
            }
        }
        .alert("Add “\(tagSuggestion?.name ?? "")” as a tag?",
               isPresented: $showTagSuggestion, presenting: tagSuggestion) { s in
            Button("Add tag") {
                Task { await api.answerTagSuggestion(name: s.name ?? "", accept: true) }
            }
            Button("No thanks", role: .cancel) {
                Task { await api.answerTagSuggestion(name: s.name ?? "", accept: false) }
            }
        } message: { s in
            Text("\(s.evidence ?? 0) of your tasks share this theme, e.g. "
                 + (s.samples ?? []).prefix(2).joined(separator: " · ")
                 + ". You can review or reverse this later in the tag history.")
        }
        // Settings is a SHEET, not a tab. A native TabView folds anything
        // past five items into "More", which is exactly the extra tap this
        // layout exists to remove — and Settings was the item it hid.
        .sheet(isPresented: $showSettings) {
            SettingsView()
        }
        .sheet(isPresented: $showQueue) {
            PendingQueueView()
        }
    }

    // MARK: - The tab shell

    /// Every visible tab is BUILT ONCE and shown by opacity — the same
    /// eager-construction model `TabView` used before this replaced it. A tab
    /// therefore keeps its scroll position, its editing state and its
    /// in-flight requests when you switch away and back. Rebuilding on
    /// selection instead would be less code and would quietly reset every tab
    /// each time it was revealed, which is the kind of regression nobody
    /// reports as a bug — it just feels wrong. (`ForEach` keeps each layer's
    /// identity by feature name, so that still holds now the stack is a loop.)
    @ViewBuilder
    private var tabContent: some View {
        ZStack {
            ForEach(contentTabs) { feature in
                tabLayer(feature.name) { feature.make() }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    /// One layer of that stack.
    ///
    /// Opacity ALONE is not enough: a fully transparent view still takes
    /// taps and is still read out by VoiceOver, so the hidden tabs would
    /// swallow touches meant for the visible one and the screen would
    /// announce six tabs' worth of content at once.
    @ViewBuilder
    private func tabLayer<Content: View>(
        _ name: String, @ViewBuilder _ content: () -> Content) -> some View {
        let active = selectedFeature == name
        content()
            .opacity(active ? 1 : 0)
            .allowsHitTesting(active)
            .accessibilityHidden(!active)
    }


    // MARK: - Helpers

    private var voiceQueueIcon: String {
        if store.pendingVoice.contains(where: { $0.status == .running }) { return "waveform" }
        if store.pendingVoice.allSatisfy({ $0.status == .done }) { return "checkmark.circle" }
        return "mic.badge.plus"
    }

    private var voiceQueueSummary: String {
        let waiting = store.pendingVoice.filter { $0.status == .queued }.count
        let running = store.pendingVoice.filter { $0.status == .running }.count
        let failed  = store.pendingVoice.filter { $0.status == .failed }.count
        if running > 0 { return "Running a command you spoke while offline…" }
        if waiting > 0 {
            return "\(waiting) command\(waiting == 1 ? "" : "s") waiting for your Mac"
        }
        if failed > 0 { return "\(failed) queued command\(failed == 1 ? "" : "s") didn't run" }
        return "Your queued command\(store.pendingVoice.count == 1 ? "" : "s") ran"
    }

    /// Mirrors the calendar's own month reload: pulls fresh exercises/templates/
    /// sessions after pending offline writes just flushed. WorkoutView's own
    /// `.task` handles the initial load when the tab is opened; this covers
    /// the background-refresh case so server-side changes (e.g. a routine
    /// generated on the Mac, or on another device) show up without requiring
    /// the user to leave and re-enter the Workout tab. It asks the visibility
    /// map rather than a `show*Tab` flag, because that flag no longer exists.
    private func refreshWorkoutIfNeeded() async {
        guard visibility.isVisible("workout") else { return }
        _ = try? await api.workoutExercises()
        _ = try? await api.workoutTemplates(includeDrafts: false)
        _ = try? await api.workoutSessions(limit: 50)
    }
}

/// Voice commands recorded while the Mac was unreachable, and what became of
/// them. The Mac does the thinking, so nothing can run until it's back — this
/// is the "so where did my command go?" answer, alongside the notification that
/// fires when one finally runs.
struct VoiceQueueView: View {
    @ObservedObject private var store = LocalStore.shared
    @EnvironmentObject var api: APIClient
    @EnvironmentObject var settings: AppSettings
    @Environment(\.dismiss) private var dismiss
    @State private var editing: PendingVoiceCommand?

    var body: some View {
        NavigationView {
            List {
                Section {
                    Text(api.isOnline
                         ? "Your Mac is reachable — anything still waiting runs within a few seconds."
                         : "Your Mac isn't reachable. These are kept on this phone and run as soon as it is.")
                        .font(.footnote).foregroundColor(.secondary)
                }
                ForEach(store.pendingVoice) { cmd in
                    HStack(alignment: .top, spacing: 12) {
                        icon(for: cmd.status)
                            .frame(width: 22)
                        VStack(alignment: .leading, spacing: 3) {
                            Text(label(for: cmd)).font(.subheadline.weight(.medium))
                            // WHAT THE PHONE HEARD, shown while it waits. The
                            // Mac's Whisper is better and still does the real
                            // transcription — this is here so a queued command
                            // is not an anonymous row you can only inspect
                            // after it has already changed your calendar.
                            if !cmd.displayText.isEmpty {
                                Text("“\(cmd.displayText)”")
                                    .font(.footnote)
                                    .foregroundColor(cmd.edited == nil ? .secondary : .primary)
                                    .italic(cmd.edited == nil)
                            }
                            Text(cmd.recordedAt.formatted(date: .abbreviated, time: .shortened))
                                .font(.caption).foregroundColor(.secondary)
                            if !cmd.result.isEmpty {
                                Text(cmd.result).font(.footnote).foregroundColor(.secondary)
                            }
                            if cmd.status == .queued || cmd.status == .failed {
                                Button(cmd.displayText.isEmpty ? "Type it instead" : "Edit") {
                                    editing = cmd
                                    store.holdVoiceForEdit(cmd.id, true)
                                }
                                .font(.caption.weight(.medium))
                                .buttonStyle(.borderless)
                            }
                        }
                    }
                    .padding(.vertical, 2)
                }
                .onDelete { idx in
                    for i in idx { store.removeVoice(store.pendingVoice[i].id) }
                }
            }
            .navigationTitle("Queued commands")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    if store.pendingVoice.contains(where: { $0.status == .done || $0.status == .failed }) {
                        Button("Clear finished") { store.clearFinishedVoice() }
                    }
                }
                ToolbarItem(placement: .navigationBarTrailing) { Button("Done") { dismiss() } }
            }
            .task { await api.syncPendingVoice() }
            .sheet(item: $editing) { cmd in
                QueuedCommandEditor(text: cmd.displayText) { corrected in
                    if let corrected {
                        store.editVoice(cmd.id, text: corrected)
                        // Reconnected while they were typing? Send it NOW —
                        // the hold existed to protect the edit, not to delay
                        // the result once the edit is finished.
                        Task { await api.syncPendingVoice() }
                    } else {
                        store.holdVoiceForEdit(cmd.id, false)
                    }
                    editing = nil
                }
            }
        }
    }

    @ViewBuilder
    private func icon(for status: PendingVoiceCommand.Status) -> some View {
        switch status {
        case .queued:  Image(systemName: "clock").foregroundColor(.orange)
        case .running: ProgressView()
        case .done:    Image(systemName: "checkmark.circle.fill").foregroundColor(.green)
        case .failed:  Image(systemName: "exclamationmark.triangle.fill").foregroundColor(.red)
        }
    }

    /// The STAGE, not just the status (Gil, 2026-09-10: *"show what stage it's
    /// at"*). A queued command has really been through two steps — recorded,
    /// and heard by the phone — and saying only "waiting" hides both, plus the
    /// fact that it is being held back because you are editing it.
    private func label(for cmd: PendingVoiceCommand) -> String {
        switch cmd.status {
        case .queued:
            if cmd.heldForEdit { return "Editing — won't send until you're done" }
            if cmd.edited != nil { return "Edited — will send as text" }
            if cmd.draft.isEmpty { return "Recorded — waiting for your Mac" }
            return "Heard on this phone — waiting for your Mac"
        case .running: return "Running now…"
        case .done:    return "Done"
        case .failed:  return "Didn't run"
        }
    }
}

/// Correct what the phone heard, before it is sent.
///
/// Separate from `EditTranscriptionSheet` (VoiceButton.swift) on purpose: that
/// one answers the Mac's `needs_edit` round-trip and highlights the specific
/// words the vocabulary doubted. This one has no Mac and no doubtful-word list
/// — the phone's own recogniser produced the text and has no opinion about
/// which parts are shaky — so it is a plain editor with an honest caption.
///
/// `onDone(nil)` means cancelled: the draft is untouched and the hold is
/// released, so the command reverts to being sent as AUDIO.
struct QueuedCommandEditor: View {
    let text: String
    let onDone: (String?) -> Void

    @State private var draft: String = ""
    @FocusState private var focused: Bool

    var body: some View {
        NavigationView {
            Form {
                Section {
                    TextEditor(text: $draft)
                        .frame(minHeight: 120)
                        .focused($focused)
                } header: {
                    Text("What this phone heard")
                } footer: {
                    Text("Your Mac transcribes the recording properly when it's "
                         + "back, so you only need to touch this if the phone got "
                         + "it wrong. If you do edit it, the text you leave here "
                         + "is what runs — the recording is not used.")
                }
            }
            .navigationTitle("Edit command")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { onDone(nil) }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") { onDone(draft) }
                        .disabled(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
            .onAppear { draft = text; focused = true }
        }
    }
}
