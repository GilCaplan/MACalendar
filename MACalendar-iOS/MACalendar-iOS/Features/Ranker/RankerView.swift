import SwiftUI

/// Ranker. Declared in `Features/FeatureRegistry.swift`; the Mac side is
/// `assistant/features/ranker/`. Every write goes through `APIClient.mutate`
/// so it queues when the Mac is away (`tests/unit/test_ios_offline.py`).
struct RankerView: View {
    @EnvironmentObject var api: APIClient

    var body: some View {
        NavigationStack {
            VStack(spacing: 8) {
                Image(systemName: "list.number")
                    .font(.largeTitle)
                    .foregroundStyle(.secondary)
                Text("Ranker has nothing to show yet.")
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .navigationTitle("Ranker")
        }
    }
}
