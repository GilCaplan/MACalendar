import Foundation
import Network
import SwiftUI

// MARK: - Joining a server without typing its address (DEVQA Q69)
//
// Two ways in, the server's side is `assistant/pairing/`:
//
//  * FOUND — the server announces itself on the Wi-Fi (Bonjour,
//    `_macalendar._tcp`); `ServerBrowser` lists it on the "Your Mac" page and
//    one tap connects. The TXT record carries every address the server has,
//    Tailscale first, so a phone that joined at home keeps reaching the Mac
//    over Tailscale when it leaves.
//  * SCANNED — the server shows a QR of a `macalendar://pair` link (every
//    address + a ONE-TIME code). The iPhone's Camera opens it here; the first
//    address that answers is kept and the code is redeemed at
//    `POST /devices/pair` for this device's id and token.

/// `macalendar://pair?u=<url>&u=<url>&c=<code>&n=<name>[&k=<api key>]`
struct PairLink: Equatable {
    let urls: [String]
    let code: String
    let name: String
    let key: String

    init(urls: [String], code: String = "", name: String, key: String = "") {
        self.urls = urls; self.code = code; self.name = name; self.key = key
    }

    init?(_ url: URL) {
        guard url.scheme == "macalendar", url.host == "pair",
              let items = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems
        else { return nil }
        func one(_ k: String) -> String { items.first { $0.name == k }?.value ?? "" }
        urls = items.filter { $0.name == "u" }.compactMap(\.value).filter { !$0.isEmpty }
        code = one("c")
        name = one("n").isEmpty ? "your Mac" : one("n")
        key = one("k")
        guard !urls.isEmpty else { return nil }
    }
}

@MainActor
final class PairingCenter: ObservableObject {
    static let shared = PairingCenter()

    enum State: Equatable {
        case idle
        case working(String)
        case done(String)
        case failed(String)
    }
    @Published var state: State = .idle

    /// The first address that answers `/health`, tried in the server's order
    /// (Tailscale first). Three seconds each: a Mac that is there answers in
    /// about 100 ms, so one that has not in 3 s is absent on that route.
    nonisolated static func firstReachable(_ urls: [String]) async -> String? {
        for u in urls {
            guard let url = URL(string: u + "/health") else { continue }
            let req = URLRequest(url: url, timeoutInterval: 3)
            if let (_, resp) = try? await URLSession.shared.data(for: req),
               (resp as? HTTPURLResponse)?.statusCode == 200 {
                return u
            }
        }
        return nil
    }

    /// Join the server a link (scanned) or an announcement (found) describes.
    func pair(_ link: PairLink, settings: AppSettings, api: APIClient) async {
        state = .working(link.name)
        guard let base = await Self.firstReachable(link.urls) else {
            state = .failed("Couldn't reach \(link.name). Check that this phone is on the same "
                            + "Wi-Fi, or that Tailscale is on, and that MACalendar Server is running.")
            return
        }
        let moved = base != api.base
        settings.serverURL = base
        if !link.key.isEmpty { settings.apiKey = link.key }
        settings.serverEnabled = true
        if !link.code.isEmpty {
            if let err = await api.pair(code: link.code) {
                state = .failed(err)
                return
            }
        } else {
            // Found on the Wi-Fi, no code: enrol the ordinary way. A device id
            // issued by a DIFFERENT server would never verify here, so it is
            // dropped first rather than carried over.
            if moved { APIClient.forgetDevice() }
            await api.enrollIfNeeded()
        }
        _ = try? await api.health()        // a success marks the Mac reachable
        state = .done(link.name)
    }
}

/// Servers announcing themselves on this Wi-Fi.
@MainActor
final class ServerBrowser: ObservableObject {
    struct Found: Identifiable, Equatable {
        let id: String
        let name: String
        let urls: [String]
    }

    @Published var found: [Found] = []
    private var browser: NWBrowser?

    func start() {
        guard browser == nil else { return }
        let b = NWBrowser(for: .bonjourWithTXTRecord(type: "_macalendar._tcp", domain: nil),
                          using: .tcp)
        b.browseResultsChangedHandler = { [weak self] results, _ in
            let list: [Found] = results.compactMap { r in
                guard case let .service(service, _, _, _) = r.endpoint,
                      case let .bonjour(txt) = r.metadata,
                      let joined = txt["urls"], !joined.isEmpty
                else { return nil }
                let name = (txt["name"] ?? "").isEmpty ? service : txt["name"]!
                return Found(id: service, name: name,
                             urls: joined.split(separator: ",").map(String.init))
            }
            MainActor.assumeIsolated {
                self?.found = list.sorted { $0.name < $1.name }
            }
        }
        b.start(queue: .main)
        browser = b
    }

    func stop() {
        browser?.cancel()
        browser = nil
    }
}

/// The banner and the answer, shown over whatever screen is up when a
/// scanned code opens the app.
struct PairingOverlay: ViewModifier {
    @ObservedObject private var center = PairingCenter.shared

    func body(content: Content) -> some View {
        content
            .overlay(alignment: .top) {
                if case let .working(name) = center.state {
                    HStack(spacing: 10) {
                        ProgressView()
                        Text("Connecting to \(name)…").font(.subheadline.weight(.medium))
                    }
                    .padding(.horizontal, 16).padding(.vertical, 10)
                    .background(.regularMaterial, in: Capsule())
                    .padding(.top, 8)
                    .transition(.move(edge: .top).combined(with: .opacity))
                }
            }
            .animation(.easeInOut(duration: 0.2), value: center.state)
            .alert(alertTitle, isPresented: Binding(
                get: { alertTitle != "" },
                set: { if !$0 { center.state = .idle } })
            ) {
                Button("OK") { center.state = .idle }
            } message: {
                Text(alertMessage)
            }
    }

    private var alertTitle: String {
        switch center.state {
        case .done: return "Connected"
        case .failed: return "Couldn't connect"
        default: return ""
        }
    }

    private var alertMessage: String {
        switch center.state {
        case let .done(name): return "This device now uses \(name). You can close MACalendar Server's pairing window."
        case let .failed(msg): return msg
        default: return ""
        }
    }
}

/// The top of the "Your Mac" page: servers heard on this Wi-Fi, one tap each.
struct NearbyServers: View {
    @EnvironmentObject var settings: AppSettings
    @EnvironmentObject var api: APIClient
    @StateObject private var browser = ServerBrowser()
    @ObservedObject private var center = PairingCenter.shared

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("On this Wi-Fi").font(.subheadline.weight(.semibold))
            if browser.found.isEmpty {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text("Looking for MACalendar Server…").foregroundColor(.secondary)
                }
                .font(.subheadline)
            }
            ForEach(browser.found) { s in
                Button {
                    Task {
                        await center.pair(PairLink(urls: s.urls, name: s.name),
                                          settings: settings, api: api)
                    }
                } label: {
                    HStack(spacing: 12) {
                        Image(systemName: "desktopcomputer")
                            .foregroundColor(settings.accentColor)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(s.name).foregroundColor(.primary)
                            Text(s.urls.map { $0.replacingOccurrences(of: "http://", with: "") }
                                    .joined(separator: " · "))
                                .font(.caption).foregroundColor(.secondary).lineLimit(1)
                        }
                        Spacer()
                        if case let .working(name) = center.state, name == s.name {
                            ProgressView()
                        } else if s.urls.contains(api.base) {
                            Image(systemName: "checkmark").foregroundColor(settings.accentColor)
                        }
                    }
                    .padding(.vertical, 4)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
            Text("Away from home? On your Mac click MACalendar Server in the menu bar ▸ "
                 + "Pair a phone or tablet, and point this phone's Camera at the code.")
                .font(.caption).foregroundColor(.secondary)
        }
        .onAppear { browser.start() }
        .onDisappear { browser.stop() }
    }
}
