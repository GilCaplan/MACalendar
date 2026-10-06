import SwiftUI

/// Add your own drawing, symbol or letters as a picture — to a magic word, or as
/// a new magic word with its own words (Gil, 2026-09-30).
struct EggSymbolEditor: View {
    enum Mode { case addTo(String), newObject }
    let mode: Mode
    @Environment(\.dismiss) private var dismiss
    @ObservedObject private var store = EggStore.shared
    /// 0 a GraphicsLibrary drawing, 1 an SF Symbol, 2 a few letters
    @State private var kind = 0
    @State private var icon = "flag_israel"
    @State private var letters = "GO"
    @State private var symbol = "star.fill"
    @State private var color = Color(egg: 0xFFD23A)
    @State private var name = ""
    @State private var words = ""
    /// What the name last typed into `words`; once they differ, the user owns them.
    @State private var lastAutoWord = ""
    @State private var suggesting = false
    @State private var taken: [String] = []
    @State private var from = Date()

    private var spec: String {
        switch kind {
        case 0: return EggSymbol.icon(icon, hex: EggLoaderSettingsView.hex(color))
        case 1: return EggSymbol.sf(symbol.trimmingCharacters(in: .whitespaces), hex: EggLoaderSettingsView.hex(color))
        default: return EggSymbol.emoji(letters.trimmingCharacters(in: .whitespaces))
        }
    }

    /// The words typed, or — when none are — the name itself (Gil, 2026-10-06:
    /// "Murad" filled in as the name and Save stayed off, because the name is
    /// only a label and the words field was empty). Typing words replaces it.
    private var keywordList: [String] {
        let typed = words.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces).lowercased() }.filter { !$0.isEmpty }
        if !typed.isEmpty { return typed }
        let n = name.trimmingCharacters(in: .whitespaces).lowercased()
        return n.isEmpty ? [] : [n]
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
                    Picker("Kind", selection: $kind) {
                        Text("Drawing").tag(0)
                        Text("Symbol").tag(1)
                        Text("Letters").tag(2)
                    }
                    .pickerStyle(.segmented)
                }

                if kind == 1 {
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
                } else if kind == 0 {
                    Section {
                        LazyVGrid(columns: Array(repeating: GridItem(.flexible()), count: 6), spacing: 12) {
                            ForEach(EggSymbolPicks.icons, id: \.self) { n in
                                Button { icon = n } label: {
                                    EggSymbol.iconImage(n).resizable().scaledToFit().frame(width: 26, height: 26)
                                        .foregroundColor(icon == n ? color : .secondary)
                                }
                                .buttonStyle(.plain)
                                .accessibilityLabel(n)
                            }
                        }
                        ColorPicker("Colour", selection: $color, supportsOpacity: false)
                    } header: { Text("Drawing") }
                } else {
                    Section {
                        TextField("A few letters (e.g. GO)", text: $letters)
                    } header: { Text("Letters") }
                }

                if case .newObject = mode {
                    Section("Name and magic words") {
                        TextField("Name (e.g. Israel)", text: $name)
                            // The name IS the first magic word, typed into the
                            // words field as you go so you can see it and add
                            // more after it — until you edit the words yourself.
                            .onChange(of: name) { n in
                                let auto = n.trimmingCharacters(in: .whitespaces).lowercased()
                                if words == lastAutoWord { words = auto; lastAutoWord = auto }
                            }
                        TextField("Words, separated by commas", text: $words)
                            .textInputAutocapitalization(.never).autocorrectionDisabled()
                        Button { suggesting = true } label: { Label("Suggest words…", systemImage: "sparkles") }
                            .disabled(name.trimmingCharacters(in: .whitespaces).isEmpty)
                    }
                }
            }
            .navigationTitle("Drawing, symbol or letters")
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
        let has = kind == 0 ? !icon.isEmpty
            : kind == 1 ? !symbol.trimmingCharacters(in: .whitespaces).isEmpty
            : !letters.trimmingCharacters(in: .whitespaces).isEmpty
        if case .newObject = mode {
            return has && !name.trimmingCharacters(in: .whitespaces).isEmpty && !keywordList.isEmpty
        }
        return has
    }

    private func save(move: Bool?) {
        let label = kind == 0 ? "Drawing: \(icon)" : kind == 1 ? "Symbol: \(symbol)" : "Letters \(letters)"
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
