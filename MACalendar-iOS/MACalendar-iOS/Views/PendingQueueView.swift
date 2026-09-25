import SwiftUI

/// What is waiting to reach the Mac, and a way to change your mind.
///
/// The queue always existed; there was just no way to look at it. That is fine
/// while it is a few seconds of buffering and wrong once "working offline" is a
/// switch you can leave on for a day: by then it holds decisions you may have
/// reversed in your head but not on the device.
///
/// Order is REPLAY order, oldest first, because that is the order the Mac will
/// see — an edit below a create belongs to it.
struct PendingQueueView: View {
    @EnvironmentObject var api: APIClient
    @EnvironmentObject var settings: AppSettings
    @ObservedObject private var store = LocalStore.shared
    @Environment(\.dismiss) private var dismiss

    @State private var confirmClear = false
    /// Set when cancelling one change took others with it, so that is said
    /// rather than silently done.
    @State private var cascaded: String?

    var body: some View {
        StackNavigation {
            Group {
                if store.pending.isEmpty {
                    empty
                } else {
                    list
                }
            }
            .navigationTitle("Waiting to sync")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    Button("Done") { dismiss() }
                }
                ToolbarItem(placement: .navigationBarTrailing) {
                    if !store.pending.isEmpty {
                        Button("Clear All", role: .destructive) { confirmClear = true }
                    }
                }
            }
            .confirmationDialog("Discard everything waiting to sync?",
                                isPresented: $confirmClear, titleVisibility: .visible) {
                Button("Discard \(store.pending.count) change\(store.pending.count == 1 ? "" : "s")",
                       role: .destructive) { store.clearPending() }
                Button("Keep them", role: .cancel) {}
            } message: {
                Text("They have not reached your Mac, so discarding them undoes "
                     + "them here too. This cannot be undone.")
            }
            .alert("Cancelled together", isPresented: .constant(cascaded != nil)) {
                Button("OK") { cascaded = nil }
            } message: {
                Text(cascaded ?? "")
            }
        }
    }

    private var empty: some View {
        VStack(spacing: 10) {
            Image(systemName: "checkmark.circle").font(.system(size: 40))
                .foregroundColor(.secondary)
            Text("Nothing waiting").font(.headline)
            Text(settings.serverEnabled
                 ? "Everything you have done is on your Mac."
                 : "Anything you change while offline will appear here.")
                .font(.caption).foregroundColor(.secondary)
                .multilineTextAlignment(.center)
        }
        .padding(40)
    }

    private var list: some View {
        List {
            Section {
                ForEach(store.pending) { change in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(LocalStore.describe(change))
                        Text(change.createdAt, style: .relative)
                            .font(.caption).foregroundColor(.secondary)
                    }
                    .swipeActions(edge: .trailing) {
                        Button(role: .destructive) { cancel(change) } label: {
                            Label("Cancel", systemImage: "trash")
                        }
                    }
                }
            } header: {
                Text("\(store.pending.count) waiting · oldest first")
            } footer: {
                Text(settings.serverEnabled
                     ? "These are being sent now. Anything you cancel here will not be sent."
                     : "These will be sent, in this order, when you switch "
                       + "“Connect to your Mac” back on.")
            }
        }
    }

    private func cancel(_ change: PendingChange) {
        let removed = store.cancelPending(change.id)
        if removed > 1 {
            // Cancelling a create cancels what was queued against it. Saying so
            // is the difference between a tidy queue and a silent surprise.
            cascaded = "That change was the first of \(removed). The \(removed - 1) "
                     + "later change\(removed == 2 ? "" : "s") to the same item "
                     + "\(removed == 2 ? "was" : "were") cancelled too, because "
                     + "\(removed == 2 ? "it" : "they") would have had nothing to apply to."
        }
    }
}
