import SwiftUI

/// "Suggest words" (TASKS 49): ask how many, generate them (this device,
/// else the Mac, else say there's no model), then let the user choose —
/// Accept all, or yes / no on each. Nothing is added until they say so.
struct EggSuggestSheet: View {
    let name: String
    let existing: [String]
    let onAdd: ([String]) -> Void
    @EnvironmentObject private var api: APIClient
    @ObservedObject private var store = EggStore.shared
    @Environment(\.dismiss) private var dismiss
    @State private var count = 10
    @State private var words: [String] = []
    @State private var chosen: Set<String> = []
    @State private var source: EggWordSuggester.Source?
    @State private var problem: String?
    @State private var working = false

    var body: some View {
        NavigationView {
            List {
                Section {
                    Picker("How many", selection: $count) {
                        ForEach([5, 10, 15, 20], id: \.self) { Text("\($0)").tag($0) }
                    }
                    Button { generate(preferMac: false, more: false) } label: {
                        HStack {
                            Label(words.isEmpty ? "Suggest words for “\(name)”" : "Suggest again", systemImage: "sparkles")
                            if working { Spacer(); EggSpinner(side: 22) }
                        }
                    }
                    .disabled(working)
                    if !words.isEmpty {
                        Button { generate(preferMac: source == .mac, more: true) } label: {
                            Label("More like these", systemImage: "plus.bubble")
                        }
                        .disabled(working)
                    }
                    if source == .phone && api.settings.serverEnabled && api.isOnline {
                        Button { generate(preferMac: true, more: false) } label: {
                            Label("Ask my Mac instead (a stronger model)", systemImage: "desktopcomputer")
                        }
                        .disabled(working)
                    }
                } footer: {
                    if let source { Text("Suggested by \(source.rawValue). Tick the ones to keep.") }
                }

                if let problem {
                    Section { Label(problem, systemImage: "exclamationmark.bubble").foregroundColor(.secondary) }
                }

                if !words.isEmpty {
                    Section {
                        ForEach(words, id: \.self) { w in
                            HStack {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(w)
                                    if let other = owner(of: w) {
                                        Text("Now summons \(other) — adding moves it here").font(.caption).foregroundColor(.orange)
                                    }
                                }
                                Spacer()
                                Button { chosen.remove(w) } label: {
                                    Image(systemName: chosen.contains(w) ? "xmark.circle" : "xmark.circle.fill")
                                        .foregroundColor(chosen.contains(w) ? .secondary : .red)
                                }
                                .buttonStyle(.borderless)
                                .accessibilityLabel("No to \(w)")
                                Button { chosen.insert(w) } label: {
                                    Image(systemName: chosen.contains(w) ? "checkmark.circle.fill" : "checkmark.circle")
                                        .foregroundColor(chosen.contains(w) ? .green : .secondary)
                                }
                                .buttonStyle(.borderless)
                                .accessibilityLabel("Yes to \(w)")
                            }
                        }
                    } header: { Text("Suggestions") }
                }
            }
            .navigationTitle("Suggest words")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItemGroup(placement: .bottomBar) {
                    Button("Accept all") { onAdd(words); dismiss() }.disabled(words.isEmpty)
                    Spacer()
                    Button("Add \(chosen.count) chosen") { onAdd(words.filter { chosen.contains($0) }); dismiss() }
                        .disabled(chosen.isEmpty)
                }
            }
            .task { if words.isEmpty { generate(preferMac: false, more: false) } }
        }
    }

    private func owner(of word: String) -> String? {
        store.settings.objects.first { o in o.name != name && o.keywords.contains(word) }?.name
    }

    private func generate(preferMac: Bool, more: Bool) {
        working = true
        problem = nil
        let have = existing + (more ? words : [])
        Task {
            let r = await EggWordSuggester.suggest(for: name, existing: have, count: count, api: api, preferMac: preferMac)
            if more { words += r.words.filter { !words.contains($0) } } else { words = r.words; chosen = [] }
            source = r.source ?? source
            problem = r.problem
            working = false
        }
    }
}
