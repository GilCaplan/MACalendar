import AppKit
import SwiftUI

/// "Suggest words" on the Mac (Gil, 2026-09-30: "when you're done with iOS,
/// add it to the Mac as well"). The device asked is the one you're on, so the
/// Mac asks ITS model first — ollama, through the API's POST
/// /magic/suggest-words and so through the model protocol — then Apple's
/// on-device model (the phone's `EggOnDevice`), and the built-in list tops up
/// whatever came back short. Words another magic word has are never offered.
enum MacWordSuggester {
    enum Source: String { case mac = "this Mac's model", apple = "Apple's on-device model", bank = "the built-in list" }

    struct Result {
        var words: [String] = []
        var source: Source?
        var fromBank = 0
        var problem: String?
    }

    static var api: String { ProcessInfo.processInfo.environment["MACALENDAR_API_URL"] ?? "http://127.0.0.1:8080" }

    @MainActor
    static func suggest(for name: String, id: String?, existing: [String], count: Int) async -> Result {
        let thing = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !thing.isEmpty else { return Result(problem: "Give it a name first.") }
        var r = Result()
        var why: [String] = []
        switch await ollama(thing, existing: existing, count: count) {
        case .success(let words) where !words.isEmpty: r = Result(words: words, source: .mac)
        case .success: why.append("this Mac's model had nothing new")
        case .failure(let e): why.append(e.text)
        }
        if r.words.isEmpty, EggOnDevice.available {
            let a = await EggOnDevice.words(for: thing, existing: existing, count: count)
            if !a.words.isEmpty { r = Result(words: a.words, source: .apple) } else if let e = a.error { why.append(e) }
        }
        let taken = MacEggStore.shared.settings.objects.filter { $0.id != id }.flatMap(\.keywords)
        let filled = EggWordBank.fill(r.words, id: id, name: thing, existing: existing, count: count, taken: taken)
        r.words = filled.words
        r.fromBank = filled.fromBank
        if filled.fromBank > 0, r.source == nil || filled.fromBank == filled.words.count { r.source = .bank }
        if r.words.isEmpty {
            r.problem = why.isEmpty ? "Every word that came back already summons something else."
                : "No new words came back for “\(thing)” (\(why.joined(separator: "; "))) — add your own."
        }
        return r
    }

    struct Failure: Error { let text: String }

    private static func ollama(_ thing: String, existing: [String], count: Int) async -> Swift.Result<[String], Failure> {
        guard let url = URL(string: api + "/magic/suggest-words") else { return .failure(Failure(text: "no API address")) }
        var req = URLRequest(url: url, timeoutInterval: 50)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONSerialization.data(withJSONObject: [
            "name": thing, "existing": existing, "count": count, "source": "mac"])
        do {
            let (data, _) = try await URLSession.shared.data(for: req)
            let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any]
            if let words = obj?["words"] as? [String] {
                return .success(EggRules.cleanWords(words, name: thing, existing: existing, count: count))
            }
            return .failure(Failure(text: obj?["error"] as? String ?? "this Mac's model gave no answer"))
        } catch {
            return .failure(Failure(text: "the assistant isn't running"))
        }
    }
}

/// Pick from the suggestions: nothing is added until you choose.
struct MacSuggestSheet: View {
    let name: String
    let objectID: String?
    let existing: [String]
    let onAdd: ([String]) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var count = 10
    @State private var working = false
    @State private var result: MacWordSuggester.Result?
    @State private var chosen: Set<String> = []

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Suggest words for “\(name)”").font(.headline)
            HStack {
                Picker("How many", selection: $count) {
                    ForEach([5, 10, 15, 20], id: \.self) { Text("\($0)").tag($0) }
                }
                .pickerStyle(.segmented).frame(width: 260)
                Spacer()
                Button(result == nil ? "Suggest" : "Suggest again") { run() }.disabled(working)
            }
            if working {
                HStack { ProgressView().controlSize(.small); Text("Thinking of words…").foregroundColor(.secondary) }
            }
            if let r = result {
                if let p = r.problem { Text(p).foregroundColor(.secondary) }
                List(r.words, id: \.self) { w in
                    Toggle(w, isOn: Binding(get: { chosen.contains(w) },
                                            set: { if $0 { chosen.insert(w) } else { chosen.remove(w) } }))
                }
                .frame(minHeight: 200)
                if let s = r.source {
                    Text(r.fromBank > 0 && s != .bank
                         ? "From \(s.rawValue), topped up with \(r.fromBank) from \(MacWordSuggester.Source.bank.rawValue)."
                         : "From \(s.rawValue).")
                        .font(.caption).foregroundColor(.secondary)
                }
            } else {
                Spacer()
            }
            HStack {
                Button("Cancel") { dismiss() }
                Spacer()
                Button("Accept all") { finish(result?.words ?? []) }.disabled((result?.words ?? []).isEmpty)
                Button("Add \(chosen.count) chosen") { finish((result?.words ?? []).filter(chosen.contains)) }
                    .keyboardShortcut(.defaultAction).disabled(chosen.isEmpty)
            }
        }
        .padding(20)
        .frame(width: 440, height: 520)
        .onAppear { run() }
    }

    private func run() {
        working = true
        chosen = []
        Task { @MainActor in
            result = await MacWordSuggester.suggest(for: name, id: objectID, existing: existing, count: count)
            working = false
        }
    }

    private func finish(_ words: [String]) {
        dismiss()
        if !words.isEmpty { onAdd(words) }
    }
}

/// Your own drawing, symbol or letters as a graphic — the phone's `EggSymbolEditor`
/// on a Mac.
struct MacSymbolEditor: View {
    enum Mode { case addTo(String), newObject }
    let mode: Mode
    @ObservedObject private var store = MacEggStore.shared
    @Environment(\.dismiss) private var dismiss
    /// 0 a GraphicsLibrary drawing, 1 an SF Symbol, 2 a few letters
    @State private var kind = 0
    @State private var icon = "flag_israel"
    @State private var letters = "GO"
    @State private var symbol = "star.fill"
    @State private var color = Color(egg: 0xFFD23A)
    @State private var name = ""
    @State private var words = ""
    @State private var suggesting = false
    @State private var taken: [String] = []
    @State private var from = Date()

    private var spec: String {
        switch kind {
        case 0: return EggSymbol.icon(icon, hex: Self.hex(color))
        case 1: return EggSymbol.sf(symbol.trimmingCharacters(in: .whitespaces), hex: Self.hex(color))
        default: return EggSymbol.emoji(letters.trimmingCharacters(in: .whitespaces))
        }
    }

    private var keywordList: [String] {
        words.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces).lowercased() }.filter { !$0.isEmpty }
    }

    var body: some View {
        Form {
            Section {
                TimelineView(.animation) { tl in
                    Canvas { ctx, size in
                        ctx.fill(Path(roundedRect: CGRect(origin: .zero, size: size), cornerRadius: 12),
                                 with: .color(Color(egg: 0x3b4663)))
                        let side = min(size.width, size.height)
                        var c = ctx
                        c.translateBy(x: (size.width - side) / 2, y: (size.height - side) / 2)
                        c.scaleBy(x: side / 200, y: side / 200)
                        EggSymbol.draw(spec, c, t: tl.date.timeIntervalSince(from))
                    }
                }
                .frame(height: 150)
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
                    LazyVGrid(columns: Array(repeating: GridItem(.flexible()), count: 8), spacing: 10) {
                        ForEach(EggSymbolPicks.symbols, id: \.self) { n in
                            Button { symbol = n } label: {
                                Image(systemName: n).font(.title3).foregroundColor(symbol == n ? color : .secondary)
                            }
                            .buttonStyle(.plain).help(n)
                        }
                    }
                    ColorPicker("Colour", selection: $color, supportsOpacity: false)
                }
            } else if kind == 0 {
                Section {
                    LazyVGrid(columns: Array(repeating: GridItem(.flexible()), count: 8), spacing: 12) {
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
                    TextField("Words, separated by commas", text: $words)
                    Button("Suggest words…") { suggesting = true }
                        .disabled(name.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
            HStack {
                Button("Cancel") { dismiss() }
                Spacer()
                Button("Save") { save(move: nil) }.keyboardShortcut(.defaultAction).disabled(!canSave)
            }
        }
        .formStyle(.grouped)
        .frame(width: 460, height: 600)
        .sheet(isPresented: $suggesting) {
            MacSuggestSheet(name: name.trimmingCharacters(in: .whitespaces), objectID: nil, existing: keywordList) { chosen in
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
        let variant = EggVariant(id: UUID().uuidString, name: kind == 0 ? "Drawing: \(icon)" : kind == 1 ? "Symbol: \(symbol)" : "Letters \(letters)",
                                 source: .symbol(spec))
        switch mode {
        case .addTo(let id):
            store.addVariant(variant, to: id)
        case .newObject:
            if move == nil {
                let clash = keywordList.filter { store.owner(of: $0, besides: "") != nil }
                if !clash.isEmpty { taken = clash; return }
            }
            let keep = move == false ? keywordList.filter { !taken.contains($0) } : keywordList
            store.addCustom(name: name.trimmingCharacters(in: .whitespaces), keywords: keep, original: variant)
        }
        taken = []
        dismiss()
    }

    static func hex(_ c: Color) -> String {
        guard let n = NSColor(c).usingColorSpace(.sRGB) else { return "#FFD23A" }
        return String(format: "#%02X%02X%02X", Int(n.redComponent * 255), Int(n.greenComponent * 255), Int(n.blueComponent * 255))
    }
}
