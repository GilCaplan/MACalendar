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
// replaces the old one. "New search" (toolbar) makes the Mac forget both, so
// no search is stuck on the last one. The Mac keeps the last table, so tuning
// the recipe afterwards re-ranks without sending it again. Ranking runs on the
// Mac — the backend is `assistant/features/ranker/` — so with the Mac away
// the tab says so.

struct RankerView: View {
    @EnvironmentObject var api: APIClient
    @EnvironmentObject var settings: AppSettings

    /// "Only these numbers" — the Mac's own switch (`use_numbers`), shared
    /// with the Mac panel so the two stay in step. Off ranks every row and
    /// KEEPS the saved list, so switching it back on restores it.
    @State private var onlyNumbers = true
    /// The saved list, as the Mac last said (the picture's answer as edited).
    @State private var numbers: [Int] = []

    @State private var overview: RankerOverview?
    @State private var result: RankerResult?
    /// A recipe applied before there was a table to rank: used by the first rank.
    @State private var pendingRecipe: RankerRecipe?
    @State private var unreachable: String?
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

    private func setNumbers(_ list: [Int]) {
        var seen = Set<Int>()
        numbers = list.filter { seen.insert($0).inserted }
    }

    private var hasTable: Bool { stagedTable != nil || overview?.hasTable == true || result != nil }

    private var currentRecipe: RankerRecipe? {
        if let r = result?.recipe ?? pendingRecipe { return r }
        guard let o = overview else { return nil }
        return o.presets.first { $0.name == o.preset } ?? o.presets.first
    }

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

    @ViewBuilder private var content: some View {
        if overview == nil, let why = unreachable {
            unreachableState(why)
        } else if overview == nil {
            ProgressView("Asking your Mac…")
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else {
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
            .refreshable { if hasTable { await rank() } else { await load() } }
        }
    }

    private func unreachableState(_ why: String) -> some View {
        ScrollView {
            VStack(spacing: 14) {
                Image(systemName: "list.number")
                    .font(.system(size: 48))
                    .foregroundColor(.secondary)
                Text(why)
                    .multilineTextAlignment(.center)
                    .foregroundColor(.secondary)
                    .accessibilityIdentifier("ranker-empty")
                Button("Try again") { Task { await load() } }
                    .buttonStyle(.bordered)
                    .tint(settings.accentColor)
            }
            .padding(24)
            .frame(maxWidth: .infinity)
        }
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
        } footer: {
            if overview?.engine == "none" {
                Text("Your Mac has no way to read pictures yet (it needs Xcode's command-line tools or Tesseract), so only the table will be used.")
            }
        }
    }

    // MARK: Inputs

    private var inputsSection: some View {
        Section {
            if stagedTable == nil, let o = overview, o.hasTable {
                Label("\(o.tableName ?? "Table") · \(o.tableRows) rows", systemImage: "tablecells")
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
            if overview?.engine == "none" {
                Text("Your Mac has no way to read pictures yet (it needs Xcode's command-line tools or Tesseract), so only the table will be used.")
            } else {
                Text("A new table replaces this one; new pictures replace the numbers.")
            }
        }
    }

    private func pickButtons(prominent: Bool) -> some View {
        HStack(spacing: 10) {
            Button {
                importKind = .table
                importing = true
            } label: {
                Label(prominent || stagedTable != nil || overview?.hasTable != true ? "Table" : "New table",
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
                set: { on in
                    onlyNumbers = on
                    Task { await numbersChanged(listEdited: false) }
                }))
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
                    Button("Clear") {
                        setNumbers([])
                        Task { await numbersChanged() }
                    }
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
                Task { await numbersChanged() }
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

    /// Every column a result can show, in the Mac's order: the key, what it
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

    /// The Columns sheet's switches write the recipe's `show` straight into
    /// the result, so the rows change at once; the next rank and a Save carry
    /// it to the Mac. Empty means every column.
    private var showBinding: Binding<[String]> {
        Binding(get: { result?.recipe?.show ?? [] },
                set: { names in
                    guard var r = result else { return }
                    var recipe = r.recipe ?? currentRecipe ?? RankerRecipe(name: "My ranking")
                    recipe.show = names
                    r.recipe = recipe
                    result = r
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
            Button { Task { await newSearch() } } label: {
                Label("New search", systemImage: "plus.magnifyingglass")
            }
            .disabled(overview == nil || busy != nil)
            .accessibilityIdentifier("ranker-new")
            Button { editingRecipe = true } label: { Image(systemName: "slider.horizontal.3") }
                .disabled(overview == nil)
                .accessibilityLabel("Rank by")
                .accessibilityIdentifier("ranker-recipe")
        }
    }

    private var recipeSheet: some View {
        RankerRecipeView(
            recipe: currentRecipe ?? RankerRecipe(name: "My ranking"),
            presets: overview?.presets ?? [],
            tableColumns: result?.tableColumns ?? overview?.tableColumns ?? [],
            onApply: { recipe in
                if hasTable { Task { await rank(recipe: recipe) } } else { pendingRecipe = recipe }
            },
            onSave: { recipe in await savePreset(recipe) },
            onDelete: { name in await deletePreset(name) })
        .environmentObject(settings)
    }

    // MARK: - Actions

    /// Start over: the Mac forgets the table and the numbers (saved rankings
    /// stay), and the tab is back to its one card. Needs the Mac — queued, a
    /// reset would land later on whatever was sent in between.
    private func newSearch() async {
        busy = "Starting a new search…"
        defer { busy = nil }
        do {
            let o = try await api.newRankerSearch()
            overview = o
            result = nil
            pendingRecipe = nil
            stagedTable = nil
            stagedImages = []
            expanded = []
            newNumbers = ""
            setNumbers(o.numbers)
            onlyNumbers = o.useNumbers
        } catch {
            refusal = sentence(for: error)
        }
    }

    private func load() async {
        do {
            let o = try await api.rankerOverview()
            overview = o
            unreachable = nil
            setNumbers(o.numbers)
            onlyNumbers = o.useNumbers
            if result == nil, o.hasTable { await rank() }
        } catch {
            unreachable = sentence(for: error)
        }
    }

    /// Send what is staged: pictures alone are read for their numbers; with a
    /// table (staged, or the Mac's last one) everything is ranked in one go.
    private func go() async {
        if stagedTable == nil && !hasTable {
            await readNumbers()
        } else {
            await rank()
        }
    }

    private func readNumbers() async {
        guard !stagedImages.isEmpty else { return }
        busy = "Reading the numbers in \(stagedImages.count == 1 ? "the picture" : "\(stagedImages.count) pictures")…"
        defer { busy = nil }
        do {
            let found = try await api.readRankerNumbers(images: stagedImages)
            stagedImages = []
            setNumbers(found)
            onlyNumbers = true
            if found.isEmpty { refusal = "No numbers found in that picture." }
        } catch {
            refusal = sentence(for: error)
        }
    }

    /// Rank with what is staged, else the Mac's last table; `recipe` when the
    /// sheet applied one, else the one on screen. A recipe unchanged since it
    /// was saved goes by NAME, so the Mac's current ranking follows the
    /// phone's; an edited one (a Columns switch included) goes whole.
    private func rank(recipe: RankerRecipe? = nil) async {
        let images = stagedImages
        busy = images.isEmpty ? "Ranking…" : "Reading the pictures and ranking…"
        defer { busy = nil }
        let current = recipe ?? currentRecipe
        let saved = current.flatMap { c in overview?.presets.first { $0.name == c.name } }
        let byName = current != nil && saved?.signature == current?.signature
        do {
            let r = try await api.rankTable(
                table: stagedTable, images: images,
                numbers: images.isEmpty ? numbers : nil,
                useNumbers: images.isEmpty ? onlyNumbers : true,
                preset: byName ? current?.name : (current == nil ? overview?.preset : nil),
                recipe: byName ? nil : current)
            result = r
            pendingRecipe = nil
            expanded = []
            stagedTable = nil
            stagedImages = []
            setNumbers(r.numbers)
            onlyNumbers = r.useNumbers
            if var o = overview {
                o.tableColumns = r.tableColumns
                if let f = r.recipe, o.presets.contains(where: { $0.name == f.name }) { o.preset = f.name }
                overview = o
            }
        } catch {
            refusal = sentence(for: error)
        }
    }

    /// The list or the switch changed: re-rank if there is a table (the rank
    /// carries both the list and `use_numbers`). With no table yet only the
    /// LIST is sent — a plain overwrite, queued when the Mac is away; the
    /// switch rides on the first rank. Never `[]` for "off": that would erase
    /// the list the switch exists to keep.
    private func numbersChanged(listEdited: Bool = true) async {
        if hasTable && overview != nil {
            await rank()
        } else if listEdited {
            do { try await api.setRankerNumbers(numbers) }
            catch { refusal = sentence(for: error) }
        }
    }

    private func addTyped() {
        let found = newNumbers
            .split(whereSeparator: { !$0.isNumber })
            .compactMap { Int($0) }
        newNumbers = ""
        guard !found.isEmpty else { return }
        setNumbers(numbers + found)
        onlyNumbers = true
        Task { await numbersChanged() }
    }

    private func savePreset(_ recipe: RankerRecipe) async -> String? {
        do {
            if let o = try await api.saveRankerPreset(recipe) {
                overview = o
            } else if var o = overview {
                // Queued: show it saved here; the Mac takes it when it is back.
                o.presets.removeAll { $0.name == recipe.name }
                o.presets.append(recipe)
                o.preset = recipe.name
                overview = o
            }
            if hasTable { await rank(recipe: recipe) }
            return nil
        } catch {
            return sentence(for: error)
        }
    }

    private func deletePreset(_ name: String) async -> String? {
        do {
            if let o = try await api.deleteRankerPreset(name) {
                overview = o
            } else if var o = overview {
                o.presets.removeAll { $0.name == name }
                if o.preset == name { o.preset = o.presets.first?.name ?? "" }
                overview = o
            }
            if result?.recipe?.name == name { result?.recipe = nil }
            if hasTable { await rank() }
            return nil
        } catch {
            return sentence(for: error)
        }
    }

    // MARK: Picking

    /// A pick REPLACES what was staged: new pictures are a new number list
    /// (the Mac replaces its list with theirs too), a new table a new table.
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

    /// Photos may be HEIC, which the Mac's readers need not take; a PNG keeps
    /// a screenshot's digits sharp, so that is what goes.
    private func stagePicture(_ raw: Data) {
        let n = stagedImages.count + 1
        if let img = UIImage(data: raw), let png = img.pngData() {
            stagedImages.append(RankerUpload(filename: "picture-\(n).png", data: png, mime: "image/png"))
        } else {
            stagedImages.append(RankerUpload(filename: "picture-\(n).jpg", data: raw, mime: "image/jpeg"))
        }
    }

    private func sentence(for error: Error) -> String {
        if let e = error as? APIError {
            switch e {
            case .badURL: return "Ranking runs on your Mac — set its address in Settings first."
            case .offline: return "Ranking runs on your Mac — it isn't reachable right now."
            case .serverError: return e.serverSentence ?? "Your Mac answered with something this app could not read."
            }
        }
        return error.localizedDescription
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
