import SwiftUI

/// Event categories → colours. Every new event is auto-tagged on the Mac
/// (keyword classifier; "Personal" when unsure) and coloured by category, with
/// the alternate shade used when the neighbouring event already has that colour.
struct EventCategory: Codable, Identifiable, Equatable {
    var name: String
    var color: String
    var alt: String
    var keywords: [String]
    var custom: Bool?
    /// This category's own event length / chain gap (DEVQA Q51). nil = the
    /// global setting applies (Settings › Events).
    var defaultMinutes: Int? = nil
    var chainGapMinutes: Int? = nil
    var id: String { name }

    enum CodingKeys: String, CodingKey {
        case name, color, alt, keywords, custom
        case defaultMinutes = "default_minutes"
        case chainGapMinutes = "chain_gap_minutes"
    }
}

struct CategoriesResponse: Codable { let categories: [EventCategory] }

struct CategoriesView: View {
    @EnvironmentObject var api: APIClient
    @EnvironmentObject var settings: AppSettings

    @State private var cats: [EventCategory] = []
    @State private var loading = false
    @State private var error: String?
    @State private var showAdd = false
    @State private var recolorResult: String?

    var body: some View {
        List {
            Section {
                Text("New events are tagged automatically from their title and coloured by category. Two events next to each other never share a colour — the second gets the category's darker shade. Unsure → Personal.")
                    .font(.footnote).foregroundColor(.secondary)
            }
            Section("Categories") {
                ForEach(cats) { c in
                    NavigationLink { CategoryEditView(category: c, onSave: { await load() }) } label: {
                        HStack(spacing: 12) {
                            HStack(spacing: 2) {
                                Circle().fill((Color(hex: c.color) ?? .gray)).frame(width: 14, height: 14)
                                Circle().fill((Color(hex: c.alt) ?? .gray)).frame(width: 10, height: 10)
                            }
                            VStack(alignment: .leading, spacing: 2) {
                                Text(c.name)
                                Text(c.keywords.isEmpty ? "default when unsure" : c.keywords.prefix(6).joined(separator: ", ") + (c.keywords.count > 6 ? "…" : ""))
                                    .font(.caption).foregroundColor(.secondary).lineLimit(1)
                                if let timing = timing(c) {
                                    Text(timing).font(.caption2).foregroundColor(.secondary)
                                }
                            }
                        }
                    }
                }
                .onDelete { idx in
                    for i in idx where cats[i].name != "Personal" {
                        let name = cats[i].name
                        Task { await api.deleteCategory(name); await load() }
                    }
                }
                Button { showAdd = true } label: { Label("Add category", systemImage: "plus.circle") }
            }
            Section("Existing events") {
                Button("Colour events that still use the default") { Task { await recolor(force: false) } }
                Button("Re-tag and recolour all events", role: .destructive) { Task { await recolor(force: true) } }
                if let recolorResult { Text(recolorResult).font(.caption).foregroundColor(.secondary) }
            }
            if let error { Section { Text(error).foregroundColor(.red).font(.footnote) } }
        }
        .navigationTitle("Event colours")
        .overlay { if loading && cats.isEmpty { ProgressView() } }
        .task { await load() }
        .refreshable { await load() }
        .sheet(isPresented: $showAdd) {
            StackNavigation {
                CategoryEditView(category: EventCategory(name: "", color: "#64748b", alt: "#475569", keywords: [], custom: true),
                                 isNew: true, onSave: { await load() })
            }
        }
    }

    private func load() async {
        loading = true; defer { loading = false }
        do { cats = try await api.categories(); error = nil }
        catch { self.error = "Couldn't reach the Mac: \(error.localizedDescription)" }
    }

    /// "90 min · 15 min gap" for a category with its own event defaults.
    private func timing(_ c: EventCategory) -> String? {
        let parts = [c.defaultMinutes.map { "\($0) min" },
                     c.chainGapMinutes.map { "\($0) min gap" }].compactMap { $0 }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    private func recolor(force: Bool) async {
        let n = await api.recolorEvents(force: force)
        recolorResult = n.map { "\($0) event\($0 == 1 ? "" : "s") updated" } ?? "Failed — is the Mac reachable?"
        api.requestRefresh()
    }
}

struct CategoryEditView: View {
    @EnvironmentObject var api: APIClient
    @Environment(\.dismiss) private var dismiss
    @State var category: EventCategory
    var isNew = false
    var onSave: () async -> Void

    @State private var color: Color = .gray
    @State private var alt: Color = .gray
    @State private var keywordText = ""
    @State private var newKeyword = ""
    @State private var saving = false
    /// The category's own length / gap as typed; empty = the global setting.
    @State private var lengthText = ""
    @State private var gapText = ""
    @State private var timingError: String?

    var body: some View {
        Form {
            if isNew { Section("Name") { TextField("e.g. Volunteering", text: $category.name) } }
            Section("Colours") {
                ColorPicker("Main colour", selection: $color, supportsOpacity: false)
                ColorPicker("Shade for a neighbouring event", selection: $alt, supportsOpacity: false)
                HStack(spacing: 8) {
                    RoundedRectangle(cornerRadius: 6).fill(color).frame(height: 28).overlay(Text("Event").font(.caption).foregroundColor(.white))
                    RoundedRectangle(cornerRadius: 6).fill(alt).frame(height: 28).overlay(Text("Next event").font(.caption).foregroundColor(.white))
                }
            }
            Section {
                ForEach(category.keywords, id: \.self) { k in Text(k) }
                    .onDelete { idx in category.keywords.remove(atOffsets: idx) }
                HStack {
                    TextField("Add word or phrase", text: $newKeyword)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                        .onSubmit(addKeyword)
                    Button("Add", action: addKeyword).disabled(newKeyword.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            } header: { Text("Keywords") } footer: {
                Text("A title containing any of these gets this category. Hebrew/transliterated words are fine (shul, mincha, bagrut…).")
            }
            Section {
                HStack {
                    Text("Default length")
                    Spacer()
                    TextField("Global (\(EventDefaults.globalLength))", text: $lengthText)
                        .keyboardType(.numberPad)
                        .multilineTextAlignment(.trailing)
                        .frame(maxWidth: 120)
                    Text("min").foregroundColor(.secondary)
                }
                HStack {
                    Text("Gap when chained")
                    Spacer()
                    TextField("Global (\(EventDefaults.globalGap))", text: $gapText)
                        .keyboardType(.numberPad)
                        .multilineTextAlignment(.trailing)
                        .frame(maxWidth: 120)
                    Text("min").foregroundColor(.secondary)
                }
                if let timingError {
                    Text(timingError).font(.caption).foregroundColor(.red)
                }
            } header: { Text("Timing") } footer: {
                Text("How long an event of this category lasts when you don't say, and the gap before it when it follows another (\"gym at 9, then lunch\"). Empty uses Settings › Events.")
            }
        }
        .navigationTitle(isNew ? "New category" : category.name)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if isNew { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } } }
            ToolbarItem(placement: .confirmationAction) {
                Button(saving ? "Saving…" : "Save") { Task { await save() } }
                    .disabled(saving || category.name.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }
        .onAppear {
            color = (Color(hex: category.color) ?? .gray); alt = (Color(hex: category.alt) ?? .gray)
            lengthText = category.defaultMinutes.map(String.init) ?? ""
            gapText = category.chainGapMinutes.map(String.init) ?? ""
        }
    }

    /// nil for an empty box (the global applies). Out of range is an error the
    /// sheet shows rather than a request the Mac would refuse.
    private func minutes(_ text: String, min lo: Int) -> (ok: Bool, value: Int?) {
        let t = text.trimmingCharacters(in: .whitespaces)
        if t.isEmpty { return (true, nil) }
        guard let n = Int(t), n >= lo, n <= EventDefaults.maxMinutes else { return (false, nil) }
        return (true, n)
    }

    private func addKeyword() {
        let k = newKeyword.trimmingCharacters(in: .whitespaces).lowercased()
        guard !k.isEmpty, !category.keywords.contains(k) else { newKeyword = ""; return }
        category.keywords.append(k); newKeyword = ""
    }

    private func save() async {
        let length = minutes(lengthText, min: EventDefaults.minLength)
        let gap = minutes(gapText, min: 0)
        guard length.ok, gap.ok else {
            timingError = "Length must be \(EventDefaults.minLength)–\(EventDefaults.maxMinutes) minutes and the gap 0–\(EventDefaults.maxMinutes), or empty for the global."
            return
        }
        timingError = nil
        saving = true; defer { saving = false }
        let ok = await api.upsertCategory(name: category.name.trimmingCharacters(in: .whitespaces),
                                          color: color.hexString ?? category.color, alt: alt.hexString ?? category.alt, keywords: category.keywords,
                                          defaultMinutes: length.value, chainGapMinutes: gap.value)
        if ok { await onSave(); dismiss() }
    }
}
