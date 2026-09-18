import SwiftUI

/// Settings ▸ How I Say Things — the engine's word lists, editable.
///
/// Gil, 2026-09-18, after "Can you shorten the event at 2pm walk Jada to be 15
/// minutes" silently did nothing: *"in the settings we should have a section
/// where these are all listed out and linked to what's in the code and can be
/// dynamically updated ... so that it can be fine-tuned to how he speaks"*.
///
/// The built-in words are shown as READ-ONLY FACT, read on the Mac out of the
/// module that actually uses them. Showing them is the "linked to what's in the
/// code" half — you can see what the assistant already knows before adding to
/// it, and the same word is never stored twice.
///
/// **Adding is the only edit that touches the engine's own words.** A built-in
/// cannot be removed, so tuning your phrasing can widen what the assistant
/// understands and can never take a word away and break something that worked.
struct LexiconView: View {
    @EnvironmentObject var api: APIClient

    @State private var entries: [LexiconEntry] = []
    @State private var drafts: [String: String] = [:]
    @State private var loading = true
    @State private var error: String? = nil
    @State private var busy: String? = nil

    var body: some View {
        List {
            if let error {
                Section {
                    Text(error).font(.footnote).foregroundColor(.red)
                }
            }

            if loading && entries.isEmpty {
                Section { ProgressView() }
            }

            ForEach(entries) { entry in
                Section {
                    Text(entry.why)
                        .font(.caption)
                        .foregroundColor(.secondary)

                    // What the code already knows. Not editable, and said out
                    // loud rather than hidden.
                    DisclosureGroup("Already known (\(entry.builtIn.count))") {
                        Text(entry.builtIn.joined(separator: ", "))
                            .font(.caption)
                            .foregroundColor(.secondary)
                            .textSelection(.enabled)
                        Text("Built in, and not removable — from \(entry.source).")
                            .font(.caption2)
                            .foregroundColor(.secondary)
                    }
                    .font(.subheadline)

                    ForEach(entry.added, id: \.self) { word in
                        Text(word)
                    }
                    .onDelete { offsets in
                        remove(entry, offsets.map { entry.added[$0] })
                    }

                    HStack {
                        TextField("Add a word — e.g. \(entry.example)",
                                  text: binding(for: entry.name))
                            .autocorrectionDisabled()
                            .textInputAutocapitalization(.never)
                            .onSubmit { add(entry) }
                        Button {
                            add(entry)
                        } label: {
                            if busy == entry.name {
                                ProgressView()
                            } else {
                                Image(systemName: "plus.circle.fill")
                            }
                        }
                        .disabled((drafts[entry.name] ?? "").trimmingCharacters(
                            in: .whitespaces).isEmpty || busy == entry.name)
                        .accessibilityLabel("Add word to \(entry.label)")
                    }
                } header: {
                    Text(entry.label)
                } footer: {
                    if !entry.added.isEmpty {
                        Text("Swipe a word of yours to remove it. The built-in "
                             + "ones above always stay.")
                    }
                }
            }
        }
        .navigationTitle("How I Say Things")
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
        .refreshable { await load() }
    }

    private func binding(for name: String) -> Binding<String> {
        Binding(get: { drafts[name] ?? "" }, set: { drafts[name] = $0 })
    }

    private func load() async {
        loading = true
        defer { loading = false }
        do {
            entries = try await api.lexicon().lexicons
            error = nil
        } catch {
            // The lists live on the Mac, so there is nothing sensible to show
            // from the cache — say so plainly rather than an empty screen.
            self.error = "Your Mac isn't reachable, so these can't be loaded or "
                       + "changed right now."
        }
    }

    private func add(_ entry: LexiconEntry) {
        let word = (drafts[entry.name] ?? "").trimmingCharacters(in: .whitespaces)
        guard !word.isEmpty else { return }
        busy = entry.name
        Task {
            defer { busy = nil }
            do {
                try await api.lexiconAdd(entry.name, word: word)
                drafts[entry.name] = ""
                await load()
            } catch {
                self.error = "Couldn't add “\(word)”: \(error.localizedDescription)"
            }
        }
    }

    private func remove(_ entry: LexiconEntry, _ words: [String]) {
        Task {
            do {
                for word in words {
                    try await api.lexiconRemove(entry.name, word: word)
                }
                await load()
            } catch {
                self.error = "Couldn't remove that: \(error.localizedDescription)"
            }
        }
    }
}
