import SwiftUI

// MARK: - Servers & logs (DEVQA Q70)
//
// Read-only on the phone: which computer is the brain, which computers lend
// it their model and in what order, and the server's log. Changing the list
// is done on the primary itself (MACalendar Server ▸ Servers & logs), because
// it hands out a credential for another machine.

struct ServersInfo: Decodable {
    struct This: Decodable {
        let name: String
        let os: String
        let urls: [String]
        let model: String
    }
    struct Host: Decodable, Identifiable {
        let id: String
        let kind: String
        let name: String
        let os: String
        let up: Bool
        let matched: Bool
        let why: String
        let busy: Bool
    }
    let this: This
    let hosts: [Host]
}

struct ServerLog: Decodable {
    let lines: [String]
}

extension APIClient {
    func servers() async throws -> ServersInfo {
        try JSONDecoder().decode(ServersInfo.self, from: try await request("/servers"))
    }

    func serverLog(lines: Int = 150) async throws -> ServerLog {
        try JSONDecoder().decode(ServerLog.self, from: try await request("/servers/logs?lines=\(lines)"))
    }
}

struct ServersView: View {
    @EnvironmentObject var api: APIClient
    @EnvironmentObject var settings: AppSettings
    @State private var info: ServersInfo?
    @State private var log: [String] = []
    @State private var logNote: String?
    @State private var error: String?
    private let tick = Timer.publish(every: 3, on: .main, in: .common).autoconnect()

    var body: some View {
        List {
            if let error {
                Section { Text(error).foregroundColor(.secondary) }
            }
            if let info {
                Section("The brain") {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(info.this.name).font(.headline)
                        Text("\(info.this.os) · model \(info.this.model)")
                            .font(.subheadline).foregroundColor(.secondary)
                        Text(info.this.urls.map { $0.replacingOccurrences(of: "http://", with: "") }
                                .joined(separator: " · "))
                            .font(.caption).foregroundColor(.secondary)
                    }
                    .padding(.vertical, 2)
                }
                Section {
                    ForEach(info.hosts) { h in
                        HStack(spacing: 12) {
                            Circle().fill(color(h)).frame(width: 10, height: 10)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(h.kind == "this" ? "This Mac (\(h.name))" : h.name)
                                Text(detail(h)).font(.caption).foregroundColor(.secondary)
                            }
                            Spacer()
                            Text(h.os).font(.caption).foregroundColor(.secondary)
                        }
                    }
                } header: {
                    Text("Where model calls run")
                } footer: {
                    Text("In this order: a call goes to the first computer that is up and has the "
                         + "same model. Add helpers or change the order on the Mac — MACalendar "
                         + "Server ▸ Servers & logs.")
                }
            }
            Section("Server log") {
                if let logNote {
                    Text(logNote).font(.footnote).foregroundColor(.secondary)
                } else {
                    Text(log.isEmpty ? "Nothing logged yet." : log.joined(separator: "\n"))
                        .font(.system(.caption2, design: .monospaced))
                        .textSelection(.enabled)
                }
            }
        }
        .navigationTitle("Servers & logs")
        .navigationBarTitleDisplayMode(.inline)
        .refreshable { await load() }
        .task { await load() }
        .onReceive(tick) { _ in Task { await loadLog() } }
    }

    private func color(_ h: ServersInfo.Host) -> Color {
        if !h.up { return .gray }
        return h.matched ? (h.busy ? .orange : .green) : .orange
    }

    private func detail(_ h: ServersInfo.Host) -> String {
        if !h.up { return h.why.isEmpty ? "Not reachable" : h.why.capitalizedFirst }
        if !h.matched { return "Not used: " + h.why }
        return h.busy ? "Busy" : "Ready"
    }

    private func load() async {
        do {
            info = try await api.servers()
            error = nil
        } catch {
            self.error = "Couldn't read the servers — is your Mac reachable?"
        }
        await loadLog()
    }

    private func loadLog() async {
        do {
            log = try await api.serverLog().lines
            logNote = nil
        } catch APIError.serverError(let msg) where msg.contains("admins only") || msg.contains("log in") {
            logNote = "Only the admin can read the server log."
        } catch {
            if log.isEmpty { logNote = "The log isn't available right now." }
        }
    }
}

private extension String {
    var capitalizedFirst: String { prefix(1).uppercased() + dropFirst() }
}
