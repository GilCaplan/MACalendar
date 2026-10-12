import SwiftUI
import PhotosUI
import UIKit
import UniformTypeIdentifiers

// MARK: - The Ranker tab
//
// Two inputs and one answer. A TABLE (an .html export, .csv, .tsv, .json —
// from Files, which reaches iCloud Drive, Dropbox, Google Drive and OneDrive
// through their providers) and, optionally, SCREENSHOTS whose numbers narrow
// it (from Photos, Files or the clipboard). Pick both, press Rank once, and
// the answer comes back; new pictures REPLACE the number list and a new table
// replaces the old one. "New search" (toolbar) forgets both, so no search is
// stuck on the last one.
//
// Everything happens ON THE PHONE (Gil, 2026-10-12: "Ranking shouldnt be
// dependent on the os server… just sync"): the table is read, the pictures'
// numbers are read by Apple Vision and the rows are ranked here
// (`RankerEngine.swift`), so the tab works with no Mac at all. `RankerStore`
// keeps the recipes, the list and the last table, and syncs them with the Mac
// panel when the Mac is there.

struct RankerView: View {
    @EnvironmentObject var api: APIClient
    @EnvironmentObject var settings: AppSettings
    @ObservedObject private var store = RankerStore.shared

    /// "Only these numbers" — off ranks every row and KEEPS the list, so
    /// switching it back on restores it. Shared with the Mac panel by sync.
    private var onlyNumbers: Bool { store.useNumbers }
    /// The list: the pictures' answer as edited.
    private var numbers: [Int] { store.numbers }

    @State private var result: RankerResult?
    /// A recipe applied but not saved (a Columns switch included); nil means
    /// the current saved one.
    @State private var working: RankerRecipe?
    @State private var busy: String?
    @State private var refusal: String?

    @State private var stagedTable: RankerUpload?
    @State private var stagedImages: [RankerUpload] = []

    @State private var importKind: ImportKind = .table
    @State private var importing = false
    @State private var pickingPhotos = false
    @State private var photoItems: [PhotosPickerItem] = []
    @State private var editingRecipe = false
    @State private var choosingColumns = false
    @State private var newNumbers = ""
    @State private var expanded: Set<Int> = []

    private enum ImportKind { case table, images }

    private static let tableTypes: [UTType] = [.html, .commaSeparatedText, .tabSeparatedText, .plainText, .json]

    private func setNumbers(_ list: [Int], useNumbers: Bool? = nil) {
        store.setNumbers(list, useNumbers: useNumbers ?? store.useNumbers, api: api)
        rerank()
    }

    private var hasTable: Bool { stagedTable != nil || store.table != nil }

    private var currentRecipe: RankerRecipe? { working ?? store.current }

    var body: some View {
        StackNavigation {
            content
                .navigationTitle("Ranker")
                .toolbar { toolbar }
        }
        .task { await load() }
        .fileImporter(isPresented: $importing,
                      allowedContentTypes: importKind == .table ? Self.tableTypes : [.image],
                      allowsMultipleSelection: importKind == .images) { picked in
            pickedFiles(picked)
        }
        .photosPicker(isPresented: $pickingPhotos, selection: $photoItems,
                      maxSelectionCount: 10, matching: .images)
        .onChange(of: photoItems) { items in
            guard !items.isEmpty else { return }
            Task { await loadPhotos(items) }
        }
        .sheet(isPresented: $editingRecipe) { recipeSheet }
        .sheet(isPresented: $choosingColumns) { columnsSheet }
        .alert("Couldn't do that", isPresented: Binding(
            get: { refusal != nil }, set: { if !$0 { refusal = nil } })) {
            Button("OK", role: .cancel) {}
        } message: { Text(refusal ?? "") }
    }

    // MARK: - Content

    /// Never waits on the Mac: what this phone has is drawn at once, and a
    /// pull asks the Mac for anything newer.
    private var content: some View {
        List {
            if hasTable {
                inputsSection
                numbersSection
                resultSection
            } else {
                startCard
            }
        }
        .listStyle(.insetGrouped)
        .refreshable { await load() }
    }

    // MARK: Start

    /// A new search: one card, both inputs, one Rank.
    private var startCard: some View {
        Section {
            VStack(alignment: .leading, spacing: 14) {
                HStack(spacing: 10) {
                    Image(systemName: "list.number")
                        .font(.title2)
                        .foregroundColor(settings.accentColor)
                    Text("Add screenshots and a table")
                        .font(.title3.weight(.semibold))
                }
                Text("A table to rank — an .html page, .csv, .tsv or .json, from Files, iCloud Drive, Dropbox or Google Drive — and, if you like, screenshots whose numbers pick the rows to rank.")
                    .font(.subheadline)
                    .foregroundColor(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("ranker-empty")
                pickButtons(prominent: true)
            }
            .padding(.vertical, 8)

            stagedRows
            if !numbers.isEmpty {
                Text("\(numbers.count) \(numbers.count == 1 ? "number" : "numbers") from your pictures: \(numbers.map(String.init).joined(separator: ", ")). Add a table to rank them.")
                    .font(.footnote)
                    .foregroundColor(.secondary)
            }
            goButton
            busyRow
        }
    }

    // MARK: Inputs

    private var inputsSection: some View {
        Section {
            if stagedTable == nil, let t = store.table {
                Label("\(store.tableName ?? "Table") · \(t.rows.count) rows", systemImage: "tablecells")
                    .font(.subheadline)
                    .lineLimit(1)
            }
            pickButtons(prominent: false)
            stagedRows
            goButton
            busyRow
        } header: {
            Text("Inputs")
        } footer: {
            Text("A new table replaces this one; new pictures replace the numbers.")
        }
    }

    private func pickButtons(prominent: Bool) -> some View {
        HStack(spacing: 10) {
            Button {
                importKind = .table
                importing = true
            } label: {
                Label(prominent || stagedTable != nil || store.table == nil ? "Table" : "New table",
                      systemImage: "tablecells")
                    .frame(maxWidth: prominent ? .infinity : nil)
            }
            .buttonStyle(.bordered)
            .controlSize(prominent ? .large : .regular)
            .accessibilityIdentifier("ranker-table")

            Menu {
                Button { pickingPhotos = true } label: { Label("Photo library", systemImage: "photo.on.rectangle") }
                Button {
                    importKind = .images
                    importing = true
                } label: { Label("Files", systemImage: "folder") }
                Button { pastePicture() } label: { Label("Paste", systemImage: "doc.on.clipboard") }
            } label: {
                Label("Pictures", systemImage: "camera.viewfinder")
                    .frame(maxWidth: prominent ? .infinity : nil)
            }
            .buttonStyle(.bordered)
            .controlSize(prominent ? .large : .regular)
            .accessibilityIdentifier("ranker-picture")

            if !prominent { Spacer() }
        }
        .tint(settings.accentColor)
    }

    @ViewBuilder private var stagedRows: some View {
        if let t = stagedTable {
            stagedRow(icon: "tablecells", text: t.filename) { stagedTable = nil }
        }
        if !stagedImages.isEmpty {
            stagedRow(icon: "photo",
                      text: stagedImages.count == 1 ? "1 picture" : "\(stagedImages.count) pictures") {
                stagedImages = []
            }
        }
    }

    @ViewBuilder private var goButton: some View {
        if stagedTable != nil || !stagedImages.isEmpty {
            Button {
                Task { await go() }
            } label: {
                Text(goLabel)
                    .font(.headline)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 4)
            }
            .buttonStyle(.borderedProminent)
            .tint(settings.accentColor)
            .disabled(busy != nil)
            .accessibilityIdentifier("ranker-go")
        }
    }

    @ViewBuilder private var busyRow: some View {
        if let busy {
            HStack(spacing: 8) {
                ProgressView()
                Text(busy).font(.footnote).foregroundColor(.secondary)
            }
        }
    }

    private var goLabel: String {
        if stagedTable == nil && !hasTable { return "Read the numbers" }
        return "Rank"
    }

    private func stagedRow(icon: String, text: String, remove: @escaping () -> Void) -> some View {
        HStack {
            Image(systemName: icon).foregroundColor(settings.accentColor)
            Text(text).lineLimit(1)
            Spacer()
            Button(action: remove) { Image(systemName: "xmark.circle.fill").foregroundColor(.secondary) }
                .buttonStyle(.plain)
                .accessibilityLabel("Remove")
        }
    }

    // MARK: Numbers

    private var numbersSection: some View {
        Section {
            Toggle("Only these numbers", isOn: Binding(
                get: { onlyNumbers },
                set: { on in setNumbers(numbers, useNumbers: on) }))
            .tint(settings.accentColor)
            .accessibilityIdentifier("ranker-only-numbers")

            if !numbers.isEmpty {
                FlowLayout(spacing: 6) {
                    ForEach(numbers, id: \.self) { n in chip(n) }
                }
                .padding(.vertical, 4)
                .opacity(onlyNumbers ? 1 : 0.45)
            }
            HStack {
                TextField("Add numbers — 261 305 412", text: $newNumbers)
                    .keyboardType(.numbersAndPunctuation)
                    .onSubmit { addTyped() }
                if !newNumbers.isEmpty {
                    Button("Add") { addTyped() }
                }
            }
            if let missing = result?.missing, !missing.isEmpty, onlyNumbers {
                Text("\(missing.count) \(missing.count == 1 ? "isn't" : "aren't") in the table: \(missing.joined(separator: ", "))")
                    .font(.footnote)
                    .foregroundColor(.orange)
            }
        } header: {
            HStack {
                Text("Numbers")
                Spacer()
                if !numbers.isEmpty {
                    Button("Clear") { setNumbers([]) }
                    .font(.caption.weight(.semibold))
                    .foregroundColor(settings.accentColor)
                }
            }
        } footer: {
            Text(numbers.isEmpty || !onlyNumbers
                 ? "Every row is a candidate. Add pictures or type numbers to rank only those."
                 : "Only rows whose \(keyLabel) is one of these are ranked.")
        }
    }

    private func chip(_ n: Int) -> some View {
        HStack(spacing: 4) {
            Text("\(n)").monospacedDigit()
            Button {
                setNumbers(numbers.filter { $0 != n })
            } label: { Image(systemName: "xmark").font(.caption2.weight(.bold)) }
            .buttonStyle(.plain)
            .accessibilityLabel("Remove \(n)")
        }
        .font(.subheadline)
        .padding(.horizontal, 10)
        .padding(.vertical, 5)
        .background(settings.accentColor.opacity(0.15), in: Capsule())
    }

    // MARK: Result

    @ViewBuilder private var resultSection: some View {
        if let r = result {
            Section {
                VStack(alignment: .leading, spacing: 4) {
                    Text(summary(r)).font(.subheadline)
                    ForEach(r.notes, id: \.self) { note in
                        Text(note).font(.caption).foregroundColor(.secondary)
                    }
                }
                .accessibilityIdentifier("ranker-summary")
                if r.rows.isEmpty {
                    Text(r.total == 0 ? "None of the numbers are in the table." : "No row meets the recipe's conditions.")
                        .foregroundColor(.secondary)
                }
                ForEach(r.rows) { row in rowView(row, in: r) }
            } header: {
                HStack(spacing: 14) {
                    Text("Result")
                    Spacer()
                    Button { choosingColumns = true } label: {
                        Label("Columns", systemImage: "eye")
                    }
                    .accessibilityIdentifier("ranker-columns")
                    Button { editingRecipe = true } label: {
                        Text(currentRecipe?.name ?? "Rank by").lineLimit(1)
                    }
                }
                .font(.caption.weight(.semibold))
                .foregroundColor(settings.accentColor)
            } footer: {
                Text("Score is a weighted average of percentiles, 0–100. Tap a row to see each part. Pull down to rank again.")
            }
        }
    }

    /// "Ranked 12 of 40 · matched on Number".
    private func summary(_ r: RankerResult) -> String {
        var s = "Ranked \(r.kept) of \(r.total)"
        if onlyNumbers, !numbers.isEmpty, !r.key.isEmpty {
            s += " · matched on \(label(r.key, in: r))"
        }
        return s
    }

    private func rowView(_ row: RankedRow, in r: RankerResult) -> some View {
        let open = expanded.contains(row.rank)
        let shown = shownColumns(r).filter { $0.name != r.key }
        return Button {
            if open { expanded.remove(row.rank) } else { expanded.insert(row.rank) }
        } label: {
            VStack(alignment: .leading, spacing: 8) {
                HStack(alignment: .firstTextBaseline) {
                    Text("\(row.rank)")
                        .font(.subheadline.weight(.semibold))
                        .foregroundColor(.secondary)
                        .monospacedDigit()
                        .frame(minWidth: 24, alignment: .leading)
                    Text(keyText(row, in: r)).font(.headline).foregroundColor(.primary)
                    Spacer()
                    Text(RankerCell.trim(row.score, places: 1))
                        .font(.headline.monospacedDigit())
                        .foregroundColor(settings.accentColor)
                }
                if !shown.isEmpty {
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 96), spacing: 10, alignment: .topLeading)],
                              alignment: .leading, spacing: 8) {
                        ForEach(shown) { c in
                            VStack(alignment: .leading, spacing: 1) {
                                Text(c.label)
                                    .font(.caption2)
                                    .foregroundColor(.secondary)
                                    .lineLimit(1)
                                Text(row.cells[c.name]?.compact ?? "—")
                                    .font(.subheadline.monospacedDigit())
                                    .foregroundColor(.primary)
                                    .lineLimit(1)
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                }
                if open { partsView(row, in: r) }
            }
            .padding(.vertical, 2)
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("ranker-row-\(row.rank)")
    }

    private func partsView(_ row: RankedRow, in r: RankerResult) -> some View {
        let criteria = (r.recipe?.criteria ?? []).filter { row.parts[$0.column] != nil }
        return VStack(alignment: .leading, spacing: 6) {
            ForEach(criteria) { c in
                let pct = row.parts[c.column] ?? 0
                VStack(alignment: .leading, spacing: 2) {
                    HStack {
                        Text(label(c.column, in: r))
                        Text(c.better == "higher" ? "higher is better" : "lower is better")
                            .foregroundColor(.secondary)
                        if c.weight != 1 { Text("x\(RankerCell.trim(c.weight, places: 1))").foregroundColor(.secondary) }
                        Spacer()
                        Text(row.cells[c.column]?.compact ?? "—").foregroundColor(.secondary)
                        Text(RankerCell.trim(pct, places: 1)).monospacedDigit()
                    }
                    .font(.caption)
                    ProgressBar(value: pct / 100, color: settings.accentColor).frame(height: 3)
                }
            }
        }
        .padding(.top, 4)
    }

    /// "K 261": the key column's first letter before a number, the value alone otherwise.
    private func keyText(_ row: RankedRow, in r: RankerResult) -> String {
        guard let cell = row.cells[r.key] else { return "—" }
        if cell.number != nil, let initial = label(r.key, in: r).first(where: \.isLetter) {
            return "\(initial.uppercased()) \(cell.plain)"
        }
        return cell.compact
    }

    private func label(_ name: String, in r: RankerResult) -> String {
        if let c = r.columns.first(where: { $0.name == name }) { return c.label }
        if let d = r.recipe?.derived.first(where: { $0.name == name }) { return d.label }
        return r.tableColumns.first { $0.name == name }?.label ?? name
    }

    private var keyLabel: String {
        guard let r = result, !r.key.isEmpty else { return "number" }
        return label(r.key, in: r)
    }

    // MARK: Columns

    /// Every column a result can show, in `rank.py`'s order: the key, what it
    /// ranks by, the sums it makes, then the rest of the table.
    private func allColumns(_ r: RankerResult) -> [RankerColumn] {
        var names = [r.key] + (r.recipe?.criteria.map(\.column) ?? [])
        names += (r.recipe?.derived.map(\.name) ?? []) + r.tableColumns.map(\.name) + r.columns.map(\.name)
        var seen = Set<String>()
        return names.filter { !$0.isEmpty && seen.insert($0).inserted }
            .map { RankerColumn(name: $0, label: label($0, in: r)) }
    }

    /// What the rows show: the recipe's `show`, or every column when it is empty.
    private func shownColumns(_ r: RankerResult) -> [RankerColumn] {
        let show = Set(r.recipe?.show ?? [])
        let all = allColumns(r)
        return show.isEmpty ? all : all.filter { show.contains($0.name) }
    }

    /// The Columns sheet's switches change the recipe's `show` and re-rank,
    /// so the rows change at once; a Save keeps it (and syncs it to the Mac).
    /// Empty means every column.
    private var showBinding: Binding<[String]> {
        Binding(get: { currentRecipe?.show ?? [] },
                set: { names in
                    var recipe = currentRecipe ?? RankerStore.blank
                    recipe.show = names
                    working = recipe
                    rerank()
                })
    }

    @ViewBuilder private var columnsSheet: some View {
        if let r = result {
            RankerColumnsSheet(columns: allColumns(r), key: r.key, show: showBinding)
                .environmentObject(settings)
        }
    }

    // MARK: - Toolbar and sheet

    @ToolbarContentBuilder private var toolbar: some ToolbarContent {
        ToolbarItem(placement: .navigationBarLeading) {
            if busy != nil { ProgressView() }
        }
        ToolbarItemGroup(placement: .navigationBarTrailing) {
            Button { newSearch() } label: {
                Label("New search", systemImage: "plus.magnifyingglass")
            }
            .disabled(busy != nil || (store.table == nil && numbers.isEmpty && stagedTable == nil && stagedImages.isEmpty))
            .accessibilityIdentifier("ranker-new")
            Button { editingRecipe = true } label: { Image(systemName: "slider.horizontal.3") }
                .accessibilityLabel("Rank by")
                .accessibilityIdentifier("ranker-recipe")
        }
    }

    private var recipeSheet: some View {
        RankerRecipeView(
            recipe: currentRecipe ?? RankerStore.blank,
            presets: store.presets,
            tableColumns: store.table?.columns ?? [],
            onApply: { recipe in apply(recipe) },
            onSave: { recipe in await savePreset(recipe) },
            onDelete: { name in await deletePreset(name) })
        .environmentObject(settings)
    }

    // MARK: - Actions

    /// Start over: no table, no numbers (saved rankings stay), and the tab is
    /// back to its one card. Synced to the Mac like any other change.
    private func newSearch() {
        store.newSearch(api: api)
        result = nil
        working = nil
        stagedTable = nil
        stagedImages = []
        expanded = []
        newNumbers = ""
    }

    /// Draw what this phone has, then ask the Mac for anything newer.
    private func load() async {
        rerank()
        await store.sync(api: api)
        rerank()
    }

    /// Read what is staged — the table, the pictures' numbers — here on the
    /// phone, then rank.
    private func go() async {
        do {
            if let t = stagedTable {
                busy = "Reading \(t.filename)…"
                try await store.readTable(t, api: api)
                stagedTable = nil
                working = nil
            }
            if !stagedImages.isEmpty {
                busy = "Reading the numbers in \(stagedImages.count == 1 ? "the picture" : "\(stagedImages.count) pictures")…"
                let found = try await store.readNumbers(stagedImages, api: api)
                stagedImages = []
                if found.isEmpty { refusal = "No numbers found in that picture." }
            }
        } catch {
            refusal = sentence(for: error)
        }
        busy = nil
        expanded = []
        rerank()
    }

    /// Rank again with what is on screen. Instant: it all happens here.
    private func rerank() {
        do {
            result = try store.rank(currentRecipe)
        } catch {
            result = nil
            refusal = sentence(for: error)
        }
    }

    /// The sheet's Apply: a saved ranking unchanged is CHOSEN (and stays
    /// chosen); anything else is used as it is until it is saved.
    private func apply(_ recipe: RankerRecipe) {
        if let saved = store.presets.first(where: { $0.name == recipe.name }),
           saved.signature == recipe.signature {
            store.choose(recipe.name)
            working = nil
        } else {
            working = recipe
        }
        rerank()
    }

    private func addTyped() {
        let found = newNumbers
            .split(whereSeparator: { !$0.isNumber })
            .compactMap { Int($0) }
        newNumbers = ""
        guard !found.isEmpty else { return }
        setNumbers(numbers + found, useNumbers: true)
    }

    private func savePreset(_ recipe: RankerRecipe) async -> String? {
        if let why = await store.savePreset(recipe, api: api) { return why }
        working = nil
        rerank()
        return nil
    }

    private func deletePreset(_ name: String) async -> String? {
        if let why = await store.deletePreset(name, api: api) { return why }
        if working?.name == name { working = nil }
        rerank()
        return nil
    }

    // MARK: Picking

    /// A pick REPLACES what was staged: new pictures are a new number list,
    /// a new table a new table.
    private func pickedFiles(_ picked: Result<[URL], Error>) {
        guard case .success(let urls) = picked else { return }
        if importKind == .images, !urls.isEmpty { stagedImages = [] }
        for url in urls {
            let scoped = url.startAccessingSecurityScopedResource()
            defer { if scoped { url.stopAccessingSecurityScopedResource() } }
            guard let data = try? Data(contentsOf: url) else {
                refusal = "Couldn't read \(url.lastPathComponent) on this phone."
                continue
            }
            let type = UTType(filenameExtension: url.pathExtension)
            if importKind == .table {
                stagedTable = RankerUpload(filename: url.lastPathComponent, data: data,
                                           mime: type?.preferredMIMEType ?? "text/plain")
            } else {
                stagedImages.append(RankerUpload(filename: url.lastPathComponent, data: data,
                                                 mime: type?.preferredMIMEType ?? "image/png"))
            }
        }
    }

    private func loadPhotos(_ items: [PhotosPickerItem]) async {
        busy = "Loading the pictures…"
        defer { busy = nil; photoItems = [] }
        stagedImages = []
        for item in items {
            guard let raw = try? await item.loadTransferable(type: Data.self) else { continue }
            stagePicture(raw)
        }
    }

    private func pastePicture() {
        let images = UIPasteboard.general.images ?? []
        guard !images.isEmpty else {
            refusal = "There's no picture on the clipboard. Copy a screenshot first."
            return
        }
        stagedImages = []
        for img in images {
            if let png = img.pngData() {
                stagedImages.append(RankerUpload(filename: "pasted-\(stagedImages.count + 1).png",
                                                 data: png, mime: "image/png"))
            }
        }
    }

    /// Photos may be HEIC; a PNG keeps a screenshot's digits sharp and opens
    /// everywhere, so that is what is kept.
    private func stagePicture(_ raw: Data) {
        let n = stagedImages.count + 1
        if let img = UIImage(data: raw), let png = img.pngData() {
            stagedImages.append(RankerUpload(filename: "picture-\(n).png", data: png, mime: "image/png"))
        } else {
            stagedImages.append(RankerUpload(filename: "picture-\(n).jpg", data: raw, mime: "image/jpeg"))
        }
    }

    private func sentence(for error: Error) -> String {
        if let r = error as? RankerRefusal { return r.sentence }
        return RankerStore.sentence(error)
    }
}

// MARK: - The Columns sheet
//
// Which columns the rows show: a switch per column, several in a row (a Menu
// closes on every tap), and "Show all". Writes the recipe's `show` — empty
// means every column — so it travels with the next rank and a saved ranking.
// The key column is the row's own heading, so it is always shown.

struct RankerColumnsSheet: View {
    @EnvironmentObject var settings: AppSettings
    @Environment(\.dismiss) private var dismiss

    let columns: [RankerColumn]
    let key: String
    @Binding var show: [String]

    private var choosable: [RankerColumn] { columns.filter { $0.name != key } }

    private func isOn(_ name: String) -> Bool { show.isEmpty || show.contains(name) }

    private func set(_ name: String, _ on: Bool) {
        var shown = Set(columns.map(\.name).filter(isOn))
        if on { shown.insert(name) } else { shown.remove(name) }
        if !key.isEmpty { shown.insert(key) }
        let ordered = columns.map(\.name).filter(shown.contains)
        show = ordered.count == columns.count ? [] : ordered
    }

    var body: some View {
        StackNavigation {
            List {
                Section {
                    ForEach(choosable) { c in
                        Toggle(c.label, isOn: Binding(get: { isOn(c.name) }, set: { set(c.name, $0) }))
                            .accessibilityIdentifier("ranker-column-\(c.name)")
                    }
                } footer: {
                    if !key.isEmpty {
                        Text("\(columns.first { $0.name == key }?.label ?? key) heads every row, so it is always shown.")
                    }
                }
            }
            .navigationTitle("Columns")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Show all") { show = [] }.disabled(show.isEmpty)
                }
                ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
            }
        }
        .tint(settings.accentColor)
    }
}
