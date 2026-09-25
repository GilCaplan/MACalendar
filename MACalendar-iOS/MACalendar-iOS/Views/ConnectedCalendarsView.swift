import AuthenticationServices
import SwiftUI
import UIKit

// MARK: - Models (GET /calendar_sync/status and the sign-in flows)
//
// Decoded with `.convertFromSnakeCase` (APIClient.decodeSnake). The Mac holds
// every token and runs the sync — see assistant/calendar_sync/ — so all the
// phone keeps is what it shows.

struct CalendarSyncStatus: Decodable {
    let enabled: Bool
    let intervalMinutes: Int
    let running: Bool
    let lastRun: CalendarSyncRun?
    let providers: [String: CalendarProviderStatus]
    let subscriptions: [CalendarSubscription]
}

struct CalendarSyncRun: Decodable {
    let finished: String?
}

struct CalendarProviderStatus: Decodable {
    let configured: Bool
    let setupNeeded: Bool
    let setup: [String: Bool]
    let setupHint: String
    let connected: Bool
    let account: String
    let sourceId: Int?
    let twoWay: Bool
    let lastSynced: String
    let lastError: String
    let pendingFlow: CalendarFlow?
}

struct CalendarFlow: Decodable, Identifiable {
    let id: String
    let provider: String?
    let state: String
    let error: String?
    let account: String?
    let userCode: String?
    let verificationUri: String?
    let authUrl: String?
    let callbackScheme: String?
}

struct CalendarSubscription: Decodable, Identifiable {
    let id: Int
    let label: String?
    let url: String?
    let lastSynced: String?
    let lastError: String?
}

// MARK: - Settings → Connected Calendars

/// Connect Google or Outlook, see when each last synced, disconnect, sync now,
/// and manage read-only ICS links — the same section as the Mac's Settings.
///
/// Gil, 2026-09-24: *"perhaps through settings — outsource calendar and have
/// both a connect to google calendar and outlook calendar with login options
/// … add on both device applications"*.
struct ConnectedCalendarsView: View {
    @EnvironmentObject var api: APIClient
    @EnvironmentObject var settings: AppSettings
    @Environment(\.openURL) private var openURL

    @State private var status: CalendarSyncStatus?
    @State private var loadError: String?
    @State private var working: String?          // provider whose button is busy
    @State private var note: String?
    @State private var deviceFlow: CalendarFlow? // Outlook's code sheet
    @State private var disconnecting: String?
    @State private var setupFor: String?
    @State private var clientID = ""
    @State private var newLabel = ""
    @State private var newURL = ""
    @State private var webAuth = WebAuthRunner()

    private static let providers: [(key: String, title: String, icon: String)] = [
        ("google", "Google Calendar", "g.circle"),
        ("outlook", "Outlook Calendar", "envelope.circle"),
    ]

    var body: some View {
        List {
            Section {
                if let s = status {
                    Text(s.enabled
                         ? "Your Mac syncs every \(s.intervalMinutes) min, calendar open or not. Last run \(Self.when(s.lastRun?.finished))\(s.running ? " · syncing now…" : "")."
                         : "Automatic sync is switched off on the Mac.")
                        .font(.footnote).foregroundColor(.secondary)
                } else if let e = loadError {
                    Text(e).font(.footnote).foregroundColor(.secondary)
                } else {
                    HStack { ProgressView(); Text("Asking your Mac…").foregroundColor(.secondary) }
                }
                if let n = note {
                    Text(n).font(.footnote)
                }
            }

            ForEach(Self.providers, id: \.key) { p in
                providerSection(p.key, title: p.title, icon: p.icon)
            }

            Section {
                ForEach(status?.subscriptions ?? []) { sub in
                    VStack(alignment: .leading, spacing: 2) {
                        Text((sub.label?.isEmpty == false ? sub.label : sub.url) ?? "Calendar link")
                        Text(sub.lastError?.isEmpty == false ? "⚠ \(sub.lastError!)"
                             : "Last synced \(Self.when(sub.lastSynced))")
                            .font(.caption).foregroundColor(.secondary)
                    }
                }
                .onDelete { idx in
                    let ids = idx.compactMap { status?.subscriptions[$0].id }
                    Task {
                        for id in ids { try? await api.removeCalendarSubscription(id: id) }
                        await load()
                    }
                }
                TextField("Label (e.g. My Gmail)", text: $newLabel)
                TextField("Secret iCal address (https://… or webcal://…)", text: $newURL)
                    .keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
                Button("Add link") { Task { await addLink() } }
                    .disabled(newURL.trimmingCharacters(in: .whitespaces).isEmpty)
            } header: {
                Text("Read-only calendar links")
            } footer: {
                Text("Any calendar's secret iCal address (Gmail: Settings → your calendar → “Secret address in iCal format”). Read-only, no sign-in.")
            }

            Section {
                Button {
                    Task { await syncNow() }
                } label: {
                    Label(status?.running == true ? "Syncing…" : "Sync now", systemImage: "arrow.triangle.2.circlepath")
                }
                .disabled(status?.running == true)
            }
        }
        .navigationTitle("Connected Calendars")
        .task { await load() }
        .refreshable { await load() }
        .sheet(item: $deviceFlow) { flow in
            OutlookCodeSheet(flow: flow) { deviceFlow = nil }
        }
        .confirmationDialog("Disconnect and sign out?",
                            isPresented: Binding(get: { disconnecting != nil },
                                                 set: { if !$0 { disconnecting = nil } }),
                            titleVisibility: .visible) {
            Button("Keep its events as local") { disconnect(keep: true) }
            Button("Remove its events", role: .destructive) { disconnect(keep: false) }
            Button("Cancel", role: .cancel) { disconnecting = nil }
        } message: {
            Text("The events stay in your account either way.")
        }
        .alert(setupFor == "google" ? "Google iOS client id" : "Outlook client id",
               isPresented: Binding(get: { setupFor != nil }, set: { if !$0 { setupFor = nil } })) {
            TextField(setupFor == "google" ? "1234-abc.apps.googleusercontent.com"
                                           : "00000000-0000-0000-0000-000000000000", text: $clientID)
                .textInputAutocapitalization(.never).autocorrectionDisabled()
            Button("Save") { Task { await saveClientID() } }
            Button("Cancel", role: .cancel) { setupFor = nil }
        } message: {
            Text(setupFor == "google"
                 ? "From Google Cloud → Credentials → your iOS OAuth client (bundle id com.macalendar.app). The Mac's Desktop client is added from the Mac. Steps: DOCUMENTATION/CALENDAR_SYNC.md."
                 : "Application (client) ID of your Entra app registration. Steps: DOCUMENTATION/CALENDAR_SYNC.md.")
        }
    }

    // MARK: Provider rows

    @ViewBuilder
    private func providerSection(_ key: String, title: String, icon: String) -> some View {
        let p = status?.providers[key]
        Section {
            HStack(alignment: .top) {
                Image(systemName: icon).foregroundColor(settings.accentColor)
                VStack(alignment: .leading, spacing: 3) {
                    Text(title).font(.headline)
                    Text(stateLine(key, p)).font(.caption).foregroundColor(.secondary)
                    if let err = p?.lastError, !err.isEmpty {
                        Text("⚠ \(err)").font(.caption).foregroundColor(.orange)
                    }
                }
            }
            if let p, p.connected {
                Toggle("Two-way (push my edits back)", isOn: Binding(
                    get: { p.twoWay },
                    set: { on in
                        guard let sid = p.sourceId else { return }
                        Task { try? await api.setCalendarTwoWay(sourceID: sid, on: on); await load() }
                    }))
                Button("Disconnect", role: .destructive) { disconnecting = key }
            }
            if canConnect(key, p) {
                Button {
                    Task { await connect(key) }
                } label: {
                    HStack {
                        Text(p?.connected == true ? "Reconnect" : "Connect \(title)")
                        if working == key { Spacer(); ProgressView() }
                    }
                }
                .disabled(working != nil)
            }
            if p?.connected != true {
                Button("Set up (paste client id)…") {
                    clientID = ""
                    setupFor = key
                }
                .font(.footnote)
            }
        } footer: {
            if let p, !canConnect(key, p), !p.connected {
                Text(key == "google" && p.setup["mac"] == true
                     ? "Set up for signing in from the Mac only — connect from the Mac's Settings, or add an iOS client id. See the steps in DOCUMENTATION/CALENDAR_SYNC.md."
                     : "Set-up needed — a free one-time client registration. See the steps in DOCUMENTATION/CALENDAR_SYNC.md.")
            }
        }
    }

    /// Google from the PHONE needs the iOS client; Outlook's device code works
    /// from anywhere once a client id exists.
    private func canConnect(_ key: String, _ p: CalendarProviderStatus?) -> Bool {
        guard let p else { return false }
        return key == "google" ? p.setup["ios"] == true : p.configured
    }

    private func stateLine(_ key: String, _ p: CalendarProviderStatus?) -> String {
        guard let p else { return status == nil ? "…" : "Unknown" }
        if p.pendingFlow != nil { return "Waiting for you to finish signing in…" }
        if p.connected {
            let who = p.account.isEmpty ? "Connected" : "Connected — \(p.account)"
            return "\(who) · last synced \(Self.when(p.lastSynced))"
        }
        return p.setupNeeded ? "Set-up needed — see steps" : "Not connected"
    }

    // MARK: Actions

    private func load() async {
        do {
            status = try await api.calendarSyncStatus()
            loadError = nil
        } catch {
            loadError = (error as? APIError)?.serverSentence ?? error.localizedDescription
        }
    }

    private func say(_ error: Error) {
        note = (error as? APIError)?.serverSentence ?? error.localizedDescription
    }

    private func connect(_ key: String) async {
        working = key
        note = nil
        defer { working = nil }
        do {
            let flow = try await api.startCalendarConnect(provider: key)
            if key == "google" {
                guard let url = URL(string: flow.authUrl ?? ""), let scheme = flow.callbackScheme else {
                    note = "Your Mac did not return a sign-in address."
                    return
                }
                let callback = try await webAuth.signIn(url: url, callbackScheme: scheme)
                let done = try await api.completeGoogleConnect(flowID: flow.id,
                                                               callbackURL: callback.absoluteString)
                note = "Google connected\(Self.asAccount(done.account)). The first sync is running on your Mac."
            } else {
                deviceFlow = flow
                let done = try await waitForFlow(flow.id)
                deviceFlow = nil
                note = done.state == "done"
                    ? "Outlook connected\(Self.asAccount(done.account))."
                    : "Outlook sign-in failed: \(done.error ?? "unknown")"
            }
        } catch let e as ASWebAuthenticationSessionError where e.code == .canceledLogin {
            note = "Sign-in cancelled."
        } catch is CancellationError {
            note = "Sign-in cancelled."
        } catch {
            deviceFlow = nil
            say(error)
        }
        await load()
    }

    /// Poll the Mac until the device-code sign-in finishes (it expires in 15 min).
    private func waitForFlow(_ id: String) async throws -> CalendarFlow {
        for _ in 0..<450 {
            try await Task.sleep(nanoseconds: 2_000_000_000)
            if deviceFlow == nil { throw CancellationError() }   // sheet dismissed
            let f = try await api.calendarFlow(id: id)
            if f.state != "pending" { return f }
        }
        throw APIError.serverError("{\"error\": \"The sign-in expired — try again.\"}")
    }

    private func disconnect(keep: Bool) {
        guard let key = disconnecting else { return }
        disconnecting = nil
        Task {
            do { try await api.disconnectCalendar(provider: key, keepEvents: keep); note = "Disconnected." }
            catch { say(error) }
            await load()
        }
    }

    private func syncNow() async {
        do {
            try await api.syncCalendarsNow()
            note = "Syncing on your Mac…"
            await load()
            try? await Task.sleep(nanoseconds: 4_000_000_000)
            api.requestRefresh()
        } catch { say(error) }
        await load()
    }

    private func addLink() async {
        let url = newURL.trimmingCharacters(in: .whitespaces)
        do {
            try await api.addCalendarSubscription(label: newLabel.trimmingCharacters(in: .whitespaces), url: url)
            newLabel = ""; newURL = ""
            try? await api.syncCalendarsNow()
            note = "Link added — syncing on your Mac."
        } catch { say(error) }
        await load()
    }

    private func saveClientID() async {
        guard let key = setupFor else { return }
        let text = clientID.trimmingCharacters(in: .whitespaces)
        setupFor = nil
        guard !text.isEmpty else { return }
        do {
            if key == "google" { try await api.saveCalendarClientID(googleIOS: text) }
            else { try await api.saveCalendarClientID(outlook: text) }
            note = "Saved on your Mac — you can connect now."
        } catch { say(error) }
        await load()
    }

    static func asAccount(_ account: String?) -> String {
        guard let account, !account.isEmpty else { return "" }
        return " as " + account
    }

    /// "5 min. ago", "2 hr. ago", or "never". The Mac writes six fractional
    /// digits, which ISO8601DateFormatter will not read — so they are dropped.
    static func when(_ iso: String?) -> String {
        guard let iso, !iso.isEmpty else { return "never" }
        let trimmed = iso.replacingOccurrences(of: #"\.\d+"#, with: "", options: .regularExpression)
        guard let date = ISO8601DateFormatter().date(from: trimmed) else { return iso }
        let f = RelativeDateTimeFormatter()
        f.unitsStyle = .short
        return f.localizedString(for: date, relativeTo: Date())
    }
}

// MARK: - Outlook's device code

private struct OutlookCodeSheet: View {
    let flow: CalendarFlow
    let onCancel: () -> Void
    @Environment(\.openURL) private var openURL

    var body: some View {
        NavigationView {
            VStack(spacing: 20) {
                Text("Sign in to Microsoft and enter this code:")
                    .multilineTextAlignment(.center)
                Text(flow.userCode ?? "")
                    .font(.system(size: 34, weight: .semibold, design: .monospaced))
                    .textSelection(.enabled)
                Button {
                    UIPasteboard.general.string = flow.userCode
                    if let url = URL(string: flow.verificationUri ?? "https://microsoft.com/devicelogin") {
                        openURL(url)
                    }
                } label: {
                    Label("Copy code & open Microsoft", systemImage: "arrow.up.forward.app")
                }
                .buttonStyle(.borderedProminent)
                Text("Come back here when you are done — this closes by itself.")
                    .font(.footnote).foregroundColor(.secondary).multilineTextAlignment(.center)
                ProgressView()
            }
            .padding()
            .navigationTitle("Connect Outlook")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel", action: onCancel) }
            }
        }
    }
}

// MARK: - Google sign-in (ASWebAuthenticationSession)

/// Opens Google's sign-in in the system browser sheet and returns the redirect
/// (`com.googleusercontent.apps.<id>:/oauth2redirect?code=…`). The session
/// catches its own callback scheme, so nothing is registered in Info.plist.
final class WebAuthRunner: NSObject, ASWebAuthenticationPresentationContextProviding {
    private var session: ASWebAuthenticationSession?

    @MainActor
    func signIn(url: URL, callbackScheme: String) async throws -> URL {
        try await withCheckedThrowingContinuation { cont in
            let s = ASWebAuthenticationSession(url: url, callbackURLScheme: callbackScheme) { callback, error in
                if let callback {
                    cont.resume(returning: callback)
                } else {
                    cont.resume(throwing: error ?? URLError(.cancelled))
                }
            }
            s.presentationContextProvider = self
            session = s
            if !s.start() {
                session = nil
                cont.resume(throwing: URLError(.cannotLoadFromNetwork))
            }
        }
    }

    func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
        UIApplication.shared.connectedScenes
            .compactMap { $0 as? UIWindowScene }
            .flatMap { $0.windows }
            .first { $0.isKeyWindow } ?? ASPresentationAnchor()
    }
}
