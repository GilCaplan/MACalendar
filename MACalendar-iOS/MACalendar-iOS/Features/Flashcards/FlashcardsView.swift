import SwiftUI
import UniformTypeIdentifiers

// MARK: - The Flashcards tab: the library
//
// Subjects as sections, sets as rows you tick; below them, how to study the
// ticked ones. Drawn from `FlashcardStore`'s cache first and refreshed from
// the Mac behind it, so it opens with the Mac away. The backend is
// `assistant/features/flashcards/`; FORMAT.md there is the set-file contract.

/// One sitting: the round and how it was asked for.
struct StudySession: Identifiable {
    let id = UUID()
    var items: [StudyItem]
    var mode: StudyMode
}

struct FlashcardsView: View {
    @EnvironmentObject var api: APIClient
    @EnvironmentObject var settings: AppSettings
    @ObservedObject private var store = FlashcardStore.shared

    @AppStorage("flashcards.selected") private var selectedRaw = ""
    @AppStorage("flashcards.mode") private var modeRaw = StudyMode.smart.rawValue
    @AppStorage("flashcards.size") private var roundSize = 20
    @AppStorage("flashcards.types") private var typesRaw = ""

    @State private var session: StudySession?
    @State private var editing: EditTarget?
    @State private var importing = false
    @State private var importReport: ImportReport?
    @State private var newSubject = false
    @State private var newSubjectName = ""
    @State private var newSet = false
    @State private var renaming: RenameTarget?
    @State private var renameText = ""
    @State private var confirmDelete: FlashSetSummary?
    @State private var confirmDeleteSubject: FlashSubject?
    @State private var confirmReset: FlashSetSummary?
    @State private var refusal: String?

    private var mode: StudyMode { StudyMode(rawValue: modeRaw) ?? .smart }
    private var selected: Set<Int> {
        Set(selectedRaw.split(separator: ",").compactMap { Int($0) })
            .intersection(store.allSets.map(\.id))
    }
    private var types: Set<String> {
        Set(typesRaw.split(separator: ",").map(String.init))
    }

    var body: some View {
        StackNavigation {
            content
                .navigationTitle("Flashcards")
                .toolbar { toolbar }
        }
        .task { await store.refresh(api: api) }
        .onReceive(api.$refreshTick) { _ in Task { await store.refresh(api: api) } }
        .fileImporter(isPresented: $importing, allowedContentTypes: Self.importTypes,
                      allowsMultipleSelection: false) { result in
            Task { await importFile(result) }
        }
        .fullScreenCover(item: $session) { s in
            FlashcardStudyView(session: s)
                .environmentObject(api)
                .environmentObject(settings)
        }
        .sheet(item: $editing) { target in
            FlashcardEditorView(setId: target.id)
                .environmentObject(api)
                .environmentObject(settings)
        }
        .sheet(isPresented: $newSet) {
            NewSetSheet { id in
                select(id, on: true)
            }
            .environmentObject(api)
            .environmentObject(settings)
        }
        .alert("New subject", isPresented: $newSubject) {
            TextField("Subject", text: $newSubjectName)
            Button("Cancel", role: .cancel) { newSubjectName = "" }
            Button("Add") {
                let name = newSubjectName
                newSubjectName = ""
                Task { refusal = await store.createSubject(name, api: api) }
            }
        } message: { Text("A subject groups sets — First aid, Spanish, Tanakh.") }
        .alert(renaming?.title ?? "Rename", isPresented: Binding(
            get: { renaming != nil }, set: { if !$0 { renaming = nil } })) {
            TextField("Name", text: $renameText)
            Button("Cancel", role: .cancel) { renaming = nil }
            Button("Save") { rename() }
        }
        .confirmationDialog("Delete this set?", isPresented: Binding(
            get: { confirmDelete != nil }, set: { if !$0 { confirmDelete = nil } }),
            titleVisibility: .visible, presenting: confirmDelete) { s in
            Button("Delete \(s.name)", role: .destructive) {
                select(s.id, on: false)
                Task { refusal = await store.deleteSet(s.id, api: api) }
            }
        } message: { s in
            Text("\(s.cards) cards and everything you learned on them go, on the Mac too.")
        }
        .confirmationDialog("Delete this subject?", isPresented: Binding(
            get: { confirmDeleteSubject != nil }, set: { if !$0 { confirmDeleteSubject = nil } }),
            titleVisibility: .visible, presenting: confirmDeleteSubject) { sub in
            Button("Delete \(sub.name) and its \(sub.sets.count) sets", role: .destructive) {
                Task { refusal = await store.deleteSubject(sub.id, api: api) }
            }
        }
        .confirmationDialog("Reset progress?", isPresented: Binding(
            get: { confirmReset != nil }, set: { if !$0 { confirmReset = nil } }),
            titleVisibility: .visible, presenting: confirmReset) { s in
            Button("Forget what I learned in \(s.name)", role: .destructive) {
                Task { refusal = await store.resetSet(s.id, api: api) }
            }
        } message: { _ in Text("Every card becomes new again. The cards themselves stay.") }
        .alert("Import", isPresented: Binding(
            get: { importReport != nil }, set: { if !$0 { importReport = nil } }),
            presenting: importReport) { _ in
            Button("OK", role: .cancel) {}
        } message: { r in Text(r.text) }
        .alert("Couldn't do that", isPresented: Binding(
            get: { refusal != nil }, set: { if !$0 { refusal = nil } })) {
            Button("OK", role: .cancel) {}
        } message: { Text(refusal ?? "") }
    }

    // MARK: - Content

    @ViewBuilder private var content: some View {
        if store.allSets.isEmpty {
            emptyState
        } else {
            List {
                ForEach(store.subjects) { subject in
                    Section {
                        if subject.sets.isEmpty {
                            Text("No sets yet — New set adds one.")
                                .font(.footnote).foregroundColor(.secondary)
                        }
                        ForEach(subject.sets) { s in setRow(s) }
                    } header: { subjectHeader(subject) }
                }
                studySection
            }
            .listStyle(.insetGrouped)
            .refreshable { await store.refresh(api: api) }
        }
    }

    private var emptyState: some View {
        ScrollView {
            VStack(spacing: 14) {
                Image(systemName: "rectangle.on.rectangle.angled")
                    .font(.system(size: 48))
                    .foregroundColor(.secondary)
                if store.subjects.isEmpty, let why = store.unreachableReason, !store.reachedMac {
                    Text("No flashcards on this phone yet")
                        .font(.title3.weight(.semibold))
                    Text("\(why) Your sets download the first time this tab reaches your Mac; after that they stay on the phone, so you can study anywhere.")
                        .multilineTextAlignment(.center)
                        .foregroundColor(.secondary)
                        .accessibilityIdentifier("flashcards-empty")
                } else {
                    Text("No flashcard sets yet")
                        .font(.title3.weight(.semibold))
                    Text("Import a set file (.yaml, .json or a .zip with its pictures), make one here with New set, or ask an agent to make flashcards and drop the file in the flashcards inbox on your Mac — it comes in the next time this tab opens.")
                        .multilineTextAlignment(.center)
                        .foregroundColor(.secondary)
                        .accessibilityIdentifier("flashcards-empty")
                    HStack {
                        Button { importing = true } label: { Label("Import", systemImage: "square.and.arrow.down") }
                            .buttonStyle(.borderedProminent)
                        Button { newSet = true } label: { Label("New set", systemImage: "plus") }
                            .buttonStyle(.bordered)
                    }
                    .tint(settings.accentColor)
                }
                if store.isRefreshing { ProgressView() }
            }
            .padding(24)
            .frame(maxWidth: .infinity)
        }
        .refreshable { await store.refresh(api: api) }
    }

    private func subjectHeader(_ subject: FlashSubject) -> some View {
        let ids = subject.sets.map(\.id)
        let all = !ids.isEmpty && Set(ids).isSubset(of: selected)
        return HStack {
            Text(subject.name)
            Spacer()
            if !ids.isEmpty {
                Button(all ? "None" : "All") {
                    for id in ids { select(id, on: !all) }
                }
                .font(.caption.weight(.semibold))
                .foregroundColor(settings.accentColor)
                .accessibilityIdentifier("flashcards-select-\(subject.name)")
            }
            Menu {
                Button { renameText = subject.name; renaming = .subject(subject.id) } label: {
                    Label("Rename", systemImage: "pencil")
                }
                Button(role: .destructive) { confirmDeleteSubject = subject } label: {
                    Label("Delete subject", systemImage: "trash")
                }
            } label: { Image(systemName: "ellipsis").padding(.leading, 6) }
        }
    }

    private func setRow(_ s: FlashSetSummary) -> some View {
        let on = selected.contains(s.id)
        return Button { select(s.id, on: !on) } label: {
            HStack(spacing: 12) {
                Image(systemName: on ? "checkmark.circle.fill" : "circle")
                    .foregroundColor(on ? settings.accentColor : .secondary)
                    .font(.title3)
                VStack(alignment: .leading, spacing: 4) {
                    Text(s.name).foregroundColor(.primary)
                    HStack(spacing: 6) {
                        Text("\(s.cards) cards")
                        if s.due > 0 {
                            Text("· \(s.due) due").foregroundColor(settings.accentColor)
                        }
                        if !store.isCached(s.id) && s.id > 0 {
                            Text("· not downloaded")
                        }
                        if s.isRTL { Text("· RTL") }
                    }
                    .font(.caption)
                    .foregroundColor(.secondary)
                    ProgressBar(value: s.items > 0 ? Double(s.seen) / Double(s.items) : 0,
                                color: settings.accentColor)
                        .frame(height: 3)
                }
            }
            .padding(.vertical, 2)
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("flashcards-set-\(s.name)")
        .contextMenu {
            Button { editing = EditTarget(id: s.id) } label: { Label("Edit cards", systemImage: "square.and.pencil") }
            Button { renameText = s.name; renaming = .set(s.id) } label: { Label("Rename", systemImage: "pencil") }
            Button { confirmReset = s } label: { Label("Reset progress", systemImage: "arrow.counterclockwise") }
            Button(role: .destructive) { confirmDelete = s } label: { Label("Delete", systemImage: "trash") }
        }
        .swipeActions(edge: .trailing) {
            Button { editing = EditTarget(id: s.id) } label: { Label("Edit", systemImage: "square.and.pencil") }
                .tint(.gray)
        }
    }

    // MARK: - Study options

    private var studySection: some View {
        let ids = Array(selected).sorted()
        let round = store.round(setIds: ids, mode: mode, types: types,
                                limit: roundSize == 0 ? nil : roundSize)
        let present = store.types(in: ids)
        let missing = ids.filter { !store.isCached($0) }.count
        return Section {
            Picker("Mode", selection: $modeRaw) {
                ForEach(StudyMode.allCases) { m in Text(m.label).tag(m.rawValue) }
            }
            .pickerStyle(.segmented)
            .accessibilityIdentifier("flashcards-mode")

            if mode != .exam {
                Menu {
                    Button { typesRaw = "" } label: { checkLabel("Every type", types.isEmpty) }
                    ForEach(present, id: \.self) { t in
                        Button { toggleType(t) } label: { checkLabel(FlashTypes.label(t), types.contains(t)) }
                    }
                } label: {
                    HStack {
                        Text("Card types").foregroundColor(.primary)
                        Spacer()
                        Text(types.isEmpty ? "Every type"
                                           : types.sorted().map(FlashTypes.label).joined(separator: ", "))
                            .foregroundColor(.secondary)
                            .lineLimit(1)
                    }
                }
            }

            Picker("Round", selection: $roundSize) {
                Text("20").tag(20)
                Text("50").tag(50)
                Text("100").tag(100)
                Text("All").tag(0)
            }
            .pickerStyle(.segmented)

            if missing > 0 {
                Text("\(missing) of the ticked sets aren't on this phone yet. They download the next time the tab reaches your Mac.")
                    .font(.footnote).foregroundColor(.secondary)
            }

            Button {
                guard !round.isEmpty else { return }
                session = StudySession(items: round, mode: mode)
            } label: {
                Text(studyLabel(count: round.count, sets: ids.count))
                    .font(.headline)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 6)
            }
            .buttonStyle(.borderedProminent)
            .tint(settings.accentColor)
            .disabled(round.isEmpty)
            .accessibilityIdentifier("flashcards-study")
        } header: {
            Text("Study")
        } footer: {
            Text(modeFooter)
        }
    }

    @ViewBuilder private func checkLabel(_ text: String, _ on: Bool) -> some View {
        if on { Label(text, systemImage: "checkmark") } else { Text(text) }
    }

    private func studyLabel(count: Int, sets: Int) -> String {
        if sets == 0 { return "Tick a set to study" }
        if count == 0 {
            return mode == .smart ? "Nothing due — try All cards" : "No cards of that kind"
        }
        return "Study \(count) \(count == 1 ? "card" : "cards")"
    }

    private var modeFooter: String {
        switch mode {
        case .smart: return "Cards that are due, most overdue first, then new ones. Each answer sets when the card comes back."
        case .all: return "Every card in the ticked sets, shuffled. Answers still count toward when cards come back."
        case .exam: return "Multiple-choice only, shuffled, scored at the end. Nothing is rescheduled."
        }
    }

    // MARK: - Toolbar

    @ToolbarContentBuilder private var toolbar: some ToolbarContent {
        ToolbarItem(placement: .navigationBarLeading) {
            if store.isRefreshing { ProgressView() }
        }
        ToolbarItem(placement: .navigationBarTrailing) {
            Menu {
                Button { importing = true } label: { Label("Import a set file", systemImage: "square.and.arrow.down") }
                Button { newSubject = true } label: { Label("New subject", systemImage: "folder.badge.plus") }
                Button { newSet = true } label: { Label("New set", systemImage: "plus.rectangle.on.rectangle") }
            } label: { Image(systemName: "plus") }
            .accessibilityIdentifier("flashcards-add")
        }
    }

    // MARK: - Actions

    private func select(_ id: Int, on: Bool) {
        var s = Set(selectedRaw.split(separator: ",").compactMap { Int($0) })
        if on { s.insert(id) } else { s.remove(id) }
        selectedRaw = s.sorted().map(String.init).joined(separator: ",")
    }

    private func toggleType(_ t: String) {
        var s = types
        if s.contains(t) { s.remove(t) } else { s.insert(t) }
        typesRaw = s.sorted().joined(separator: ",")
    }

    private func rename() {
        guard let target = renaming else { return }
        let name = renameText
        renaming = nil
        Task {
            switch target {
            case .subject(let id): refusal = await store.renameSubject(id, to: name, api: api)
            case .set(let id): refusal = await store.renameSet(id, to: name, api: api)
            }
        }
    }

    static let importTypes: [UTType] = [
        UTType(filenameExtension: "yaml"), UTType(filenameExtension: "yml"),
        .json, .zip, .yaml,
    ].compactMap { $0 }

    private func importFile(_ result: Result<[URL], Error>) async {
        guard case .success(let urls) = result, let url = urls.first else { return }
        let scoped = url.startAccessingSecurityScopedResource()
        defer { if scoped { url.stopAccessingSecurityScopedResource() } }
        guard let data = try? Data(contentsOf: url) else {
            importReport = ImportReport(text: "Couldn't read \(url.lastPathComponent) on this phone.")
            return
        }
        do {
            let lines = try await api.importFlashcards(filename: url.lastPathComponent, data: data)
            importReport = ImportReport(text: lines.isEmpty ? "Nothing new in that file."
                                                            : lines.joined(separator: "\n"))
            await store.refresh(api: api)
        } catch APIError.offline, APIError.badURL {
            importReport = ImportReport(text: "Importing needs your Mac — it reads the file and keeps the set. Try again when the phone can reach it; the sets already here still work offline.")
        } catch {
            importReport = ImportReport(text: FlashcardStore.sentence(for: error))
        }
    }
}

// MARK: - Small pieces

struct EditTarget: Identifiable { let id: Int }
struct ImportReport { let text: String }

enum RenameTarget {
    case subject(Int), set(Int)
    var title: String {
        switch self {
        case .subject: return "Rename subject"
        case .set: return "Rename set"
        }
    }
}

/// A thin bar: the share of a set's items you have seen, or a round's progress.
struct ProgressBar: View {
    let value: Double
    let color: Color
    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Rectangle().fill(Color.secondary.opacity(0.2))
                Rectangle().fill(color)
                    .frame(width: geo.size.width * CGFloat(min(1, max(0, value))))
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: 1.5))
    }
}

/// New set: a name, its subject (an existing one or a new one), and direction.
struct NewSetSheet: View {
    @EnvironmentObject var api: APIClient
    @EnvironmentObject var settings: AppSettings
    @ObservedObject private var store = FlashcardStore.shared
    @Environment(\.dismiss) private var dismiss
    var onCreated: (Int) -> Void

    @State private var name = ""
    @State private var subjectId: Int?
    @State private var newSubject = ""
    @State private var lang = ""
    @State private var rtl = false
    @State private var error: String?
    @State private var saving = false
    @State private var openEditor: EditTarget?

    var body: some View {
        StackNavigation {
            Form {
                Section("Set") {
                    TextField("Name", text: $name)
                        .accessibilityIdentifier("flashcards-new-set-name")
                }
                Section("Subject") {
                    if !store.subjects.isEmpty {
                        Picker("Subject", selection: $subjectId) {
                            Text("New subject…").tag(Int?.none)
                            ForEach(store.subjects) { s in Text(s.name).tag(Optional(s.id)) }
                        }
                    }
                    if subjectId == nil {
                        TextField("New subject's name", text: $newSubject)
                    }
                }
                Section {
                    TextField("Language code (optional, e.g. he, es)", text: $lang)
                        .textInputAutocapitalization(.never)
                        .onChange(of: lang) { v in
                            if ["he", "ar", "yi", "fa"].contains(v.lowercased()) { rtl = true }
                        }
                    Toggle("Right to left", isOn: $rtl)
                } footer: {
                    Text("Right to left lays the cards out for Hebrew or Arabic.")
                }
                if let error {
                    Text(error).foregroundColor(.red).font(.footnote)
                }
            }
            .navigationTitle("New set")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Create") { Task { await create() } }
                        .disabled(saving || name.trimmingCharacters(in: .whitespaces).isEmpty
                                  || (subjectId == nil && newSubject.trimmingCharacters(in: .whitespaces).isEmpty))
                }
            }
            .onAppear { if subjectId == nil { subjectId = store.subjects.first?.id } }
        }
    }

    private func create() async {
        saving = true
        defer { saving = false }
        var sid = subjectId
        if sid == nil {
            if let refusal = await store.createSubject(newSubject, api: api) {
                error = refusal
                return
            }
            sid = store.subjects.first { $0.name == newSubject.trimmingCharacters(in: .whitespacesAndNewlines) }?.id
        }
        guard let sid else { error = "Pick a subject for the set."; return }
        switch await store.createSet(subjectId: store.current(sid), name: name, lang: lang.lowercased(),
                                     rtl: rtl, api: api) {
        case .success(let id):
            onCreated(store.current(id))
            dismiss()
        case .failure(let e):
            error = e.message
        }
    }
}
