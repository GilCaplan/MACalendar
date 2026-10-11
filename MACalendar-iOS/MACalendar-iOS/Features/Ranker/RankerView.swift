import SwiftUI
import PhotosUI
import UIKit
import UniformTypeIdentifiers

// MARK: - The Ranker tab
//
// Two inputs and one answer. A TABLE (an .html export, .csv, .tsv, .json —
// from Files, which reaches iCloud Drive, Dropbox, Google Drive and OneDrive
// through their providers) and, optionally, SCREENSHOTS whose numbers narrow
// it (from Photos, Files or the clipboard). Rank sends whatever is staged;
// the Mac keeps the last table, so tuning the recipe afterwards re-ranks
// without sending it again. Ranking runs on the Mac — the backend is
// `assistant/features/ranker/` — so with the Mac away the tab says so.

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
        if let r = result?.recipe { return r }
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
                inputsSection
                numbersSection
                resultSection
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

    // MARK: Inputs

    private var inputsSection: some View {
        Section {
            HStack(spacing: 10) {
                Button {
                    importKind = .table
                    importing = true
                } label: { Label("Table", systemImage: "tablecells") }
                .buttonStyle(.bordered)
                .accessibilityIdentifier("ranker-table")

                Menu {
                    Button { pickingPhotos = true } label: { Label("Photo library", systemImage: "photo.on.rectangle") }
                    Button {
                        importKind = .images
                        importing = true
                    } label: { Label("Files", systemImage: "folder") }
                    Button { pastePicture() } label: { Label("Paste", systemImage: "doc.on.clipboard") }
                } label: { Label("Picture", systemImage: "camera.viewfinder") }
                .buttonStyle(.bordered)
                .accessibilityIdentifier("ranker-picture")

                Spacer()
            }
            .tint(settings.accentColor)

            if let t = stagedTable {
                stagedRow(icon: "tablecells", text: t.filename) { stagedTable = nil }
            } else if let o = overview, o.hasTable {
                Text("Last table: \(o.tableName ?? "a table") · \(o.tableRows) rows")
                    .font(.footnote).foregroundColor(.secondary)
            }
            if !stagedImages.isEmpty {
                stagedRow(icon: "photo",
                          text: stagedImages.count == 1 ? "1 picture" : "\(stagedImages.count) pictures") {
                    stagedImages = []
                }
            }

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
            if let busy {
                HStack(spacing: 8) {
                    ProgressView()
                    Text(busy).font(.footnote).foregroundColor(.secondary)
                }
            }
        } header: {
            Text("Inputs")
        } footer: {
            if overview?.engine == "none" {
                Text("Your Mac has no way to read pictures yet (it needs Xcode's command-line tools or Tesseract), so only the table will be used.")
            } else {
                Text("A picture is optional: its numbers narrow the table to the rows they name.")
            }
        }
    }

    private var goLabel: String {
        if stagedTable == nil && !hasTable { return "Read the numbers" }
        return stagedImages.isEmpty ? "Rank" : "Read the numbers and rank"
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
                 ? "Every row is a candidate. Add a picture or type numbers to rank only those."
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
                if r.rows.isEmpty {
                    Text(r.total == 0 ? "None of the numbers are in the table." : "No row meets the recipe's conditions.")
                        .foregroundColor(.secondary)
                }
                ForEach(r.rows) { row in rowView(row, in: r) }
            } header: {
                HStack {
                    Text("Ranked \(r.kept) of \(r.total)")
                    Spacer()
                    Button { editingRecipe = true } label: {
                        Text(currentRecipe?.name ?? "Recipe").lineLimit(1)
                    }
                    .font(.caption.weight(.semibold))
                    .foregroundColor(settings.accentColor)
                }
            } footer: {
                Text("Score is a weighted average of percentiles, 0–100. Tap a row to see each part. Pull down to rank again.")
            }
        } else if !hasTable {
            Section {
                Text("No table yet. Tap Table and pick an export — an .html page, .csv, .tsv or .json, from Files, iCloud Drive, Dropbox or Google Drive. Add a screenshot under Picture to rank only the numbers it shows.")
                    .foregroundColor(.secondary)
                    .accessibilityIdentifier("ranker-empty")
            }
        }
    }

    private func rowView(_ row: RankedRow, in r: RankerResult) -> some View {
        let open = expanded.contains(row.rank)
        let shown = r.columns.filter { $0.name != r.key }
        return Button {
            if open { expanded.remove(row.rank) } else { expanded.insert(row.rank) }
        } label: {
            VStack(alignment: .leading, spacing: 6) {
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
                    FlowLayout(spacing: 10) {
                        ForEach(shown) { c in
                            Text("\(c.label) \(row.cells[c.name]?.compact ?? "—")")
                                .font(.caption.monospacedDigit())
                                .foregroundColor(.secondary)
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
                        if c.weight != 1 { Text("×\(RankerCell.trim(c.weight, places: 1))").foregroundColor(.secondary) }
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
        let key = currentRecipe?.key ?? result?.key ?? ""
        guard let r = result else { return key.isEmpty ? "key" : key }
        return label(key, in: r)
    }

    // MARK: - Toolbar and sheet

    @ToolbarContentBuilder private var toolbar: some ToolbarContent {
        ToolbarItem(placement: .navigationBarLeading) {
            if busy != nil { ProgressView() }
        }
        ToolbarItem(placement: .navigationBarTrailing) {
            Button { editingRecipe = true } label: { Image(systemName: "slider.horizontal.3") }
                .disabled(overview == nil)
                .accessibilityLabel("Recipe")
                .accessibilityIdentifier("ranker-recipe")
        }
    }

    private var recipeSheet: some View {
        RankerRecipeView(
            recipe: currentRecipe ?? RankerRecipe(name: "My recipe"),
            presets: overview?.presets ?? [],
            tableColumns: result?.tableColumns ?? overview?.tableColumns ?? [],
            onApply: { recipe in Task { await rank(recipe: recipe) } },
            onSave: { recipe in await savePreset(recipe) },
            onDelete: { name in await deletePreset(name) })
        .environmentObject(settings)
    }

    // MARK: - Actions

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
    /// sheet applied one, else the current preset.
    private func rank(recipe: RankerRecipe? = nil) async {
        let images = stagedImages
        busy = images.isEmpty ? "Ranking…" : "Reading the pictures and ranking…"
        defer { busy = nil }
        do {
            let r = try await api.rankTable(
                table: stagedTable, images: images,
                numbers: images.isEmpty ? numbers : nil,
                useNumbers: images.isEmpty ? onlyNumbers : true,
                preset: recipe == nil ? (result?.recipe?.name ?? overview?.preset) : nil,
                recipe: recipe ?? (result?.recipe.flatMap { r in
                    overview?.presets.contains(where: { $0.name == r.name }) == true ? nil : r }))
            result = r
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

    private func pickedFiles(_ picked: Result<[URL], Error>) {
        guard case .success(let urls) = picked else { return }
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
