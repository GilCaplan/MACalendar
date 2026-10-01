import SwiftUI

/// Add your own emoji, flag or symbol as a picture — to a magic word, or as
/// a new magic word with its own words (Gil, 2026-09-30).
struct EggSymbolEditor: View {
    enum Mode { case addTo(String), newObject }
    let mode: Mode
    @Environment(\.dismiss) private var dismiss
    @ObservedObject private var store = EggStore.shared
    @State private var sf = false
    @State private var emoji = "🇮🇱"
    @State private var symbol = "star.fill"
    @State private var color = Color(egg: 0xFFD23A)
    @State private var name = ""
    @State private var words = ""
    @State private var suggesting = false
    @State private var taken: [String] = []
    @State private var from = Date()

    private var spec: String {
        sf ? EggSymbol.sf(symbol.trimmingCharacters(in: .whitespaces), hex: EggLoaderSettingsView.hex(color))
           : EggSymbol.emoji(emoji.trimmingCharacters(in: .whitespaces))
    }

    private var keywordList: [String] {
        words.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces).lowercased() }.filter { !$0.isEmpty }
    }

    var body: some View {
        NavigationView {
            Form {
                Section {
                    TimelineView(.animation) { tl in
                        Canvas { ctx, size in
                            let side = min(size.width, size.height)
                            var c = ctx
                            c.translateBy(x: (size.width - side) / 2, y: (size.height - side) / 2)
                            c.scaleBy(x: side / 200, y: side / 200)
                            EggSymbol.draw(spec, c, t: tl.date.timeIntervalSince(from))
                        }
                    }
                    .frame(height: 170)
                    Picker("Kind", selection: $sf) {
                        Text("Emoji or flag").tag(false)
                        Text("Symbol").tag(true)
                    }
                    .pickerStyle(.segmented)
                }

                if sf {
                    Section("Symbol") {
                        TextField("SF Symbol name (e.g. crown.fill)", text: $symbol)
                            .textInputAutocapitalization(.never).autocorrectionDisabled()
                        LazyVGrid(columns: Array(repeating: GridItem(.flexible()), count: 6), spacing: 12) {
                            ForEach(EggSymbolPicks.symbols, id: \.self) { n in
                                Button { symbol = n } label: {
                                    Image(systemName: n).font(.title3).foregroundColor(symbol == n ? color : .secondary)
                                }
                                .buttonStyle(.plain)
                                .accessibilityLabel(n)
                            }
                        }
                        ColorPicker("Colour", selection: $color, supportsOpacity: false)
                    }
                } else {
                    Section {
                        TextField("Type or paste an emoji, a flag, or a few letters", text: $emoji)
                        LazyVGrid(columns: Array(repeating: GridItem(.flexible()), count: 7), spacing: 10) {
                            ForEach(EggSymbolPicks.emoji, id: \.self) { e in
                                Button { emoji = e } label: { Text(e).font(.title2) }
                                    .buttonStyle(.plain)
                            }
                        }
                    } header: { Text("Emoji or flag") } footer: {
                        Text("Any emoji from the keyboard works — a flag, a face, your team's colours.")
                    }
                }

                if case .newObject = mode {
                    Section("Name and magic words") {
                        TextField("Name (e.g. Israel)", text: $name)
                        TextField("Words, separated by commas", text: $words)
                            .textInputAutocapitalization(.never).autocorrectionDisabled()
                        Button { suggesting = true } label: { Label("Suggest words…", systemImage: "sparkles") }
                            .disabled(name.trimmingCharacters(in: .whitespaces).isEmpty)
                    }
                }
            }
            .navigationTitle("Emoji, flag or symbol")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) { Button("Save") { save(move: nil) }.disabled(!canSave) }
            }
            .sheet(isPresented: $suggesting) {
                EggSuggestSheet(name: name.trimmingCharacters(in: .whitespaces), existing: keywordList) { chosen in
                    words = (keywordList + chosen.filter { !keywordList.contains($0) }).joined(separator: ", ")
                }
            }
            .alert("Some words are taken", isPresented: Binding(get: { !taken.isEmpty }, set: { if !$0 { taken = [] } })) {
                Button("Move them to “\(name)”") { save(move: true) }
                Button("Keep them where they are") { save(move: false) }
                Button("Cancel", role: .cancel) { taken = [] }
            } message: {
                Text(taken.map { w in "“\(w)” (\(store.owner(of: w, besides: "")?.name ?? "another"))" }
                        .joined(separator: ", ") + " already summon other things. A word can only summon one thing.")
            }
        }
    }

    private var canSave: Bool {
        let has = sf ? !symbol.trimmingCharacters(in: .whitespaces).isEmpty : !emoji.trimmingCharacters(in: .whitespaces).isEmpty
        if case .newObject = mode {
            return has && !name.trimmingCharacters(in: .whitespaces).isEmpty && !keywordList.isEmpty
        }
        return has
    }

    private func save(move: Bool?) {
        let label = sf ? "Symbol: \(symbol)" : "Emoji \(emoji)"
        let variant = EggVariant(id: UUID().uuidString, name: label, source: .symbol(spec))
        switch mode {
        case .addTo(let id):
            store.addVariant(variant, to: id)
        case .newObject:
            if move == nil {
                let clash = keywordList.filter { store.owner(of: $0, besides: "") != nil }
                if !clash.isEmpty { taken = clash; return }
            }
            let words = move == false ? keywordList.filter { !taken.contains($0) } : keywordList
            _ = store.addCustom(name: name.trimmingCharacters(in: .whitespaces), keywords: words, original: variant)
        }
        taken = []
        dismiss()
    }
}
