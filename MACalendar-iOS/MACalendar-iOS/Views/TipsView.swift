import SwiftUI

/// "How to Talk to Me" — the five phrasing tips the Mac shows from Settings →
/// Assistant, on the phone too (Gil, 2026-09-22, DEVQA Q41). The words come
/// from the host (`GET /tips`, `assistant/tips.py`) so there is ONE copy, and
/// `tests/unit/test_tips_current.py` holds that copy to the engine version.
struct TipsView: View {
    @EnvironmentObject var api: APIClient
    @State private var payload: TipsPayload?
    @State private var error: String?

    var body: some View {
        List {
            if let p = payload {
                Section {
                    ForEach(p.tips) { tip in
                        VStack(alignment: .leading, spacing: 4) {
                            Text(tip.headline).font(.headline)
                            Text(tip.body).font(.subheadline).foregroundColor(.secondary)
                        }
                        .padding(.vertical, 4)
                    }
                } footer: {
                    Text("Five things that work, checked against the assistant you are talking to. A one-line tip also appears above the mic the first time one applies.")
                }
            } else if let e = error {
                Text(e).foregroundColor(.secondary)
            } else {
                HStack { ProgressView(); Text("Loading…").foregroundColor(.secondary) }
            }
        }
        .navigationTitle("How to Talk to Me")
        .task { await load() }
        .refreshable { await load() }
    }

    private func load() async {
        do {
            payload = try await api.tips()
            error = nil
        } catch {
            if payload == nil { self.error = "Couldn't reach the Mac to load the tips." }
        }
    }
}
