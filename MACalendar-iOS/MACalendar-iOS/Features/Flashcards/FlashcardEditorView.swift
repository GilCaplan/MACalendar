import SwiftUI
import PhotosUI

// MARK: - Editing one set's cards
//
// Add, change and delete cards one at a time. Every form writes the fields
// FORMAT.md lists for its type and nothing else, because the Mac refuses an
// unknown field rather than ignoring it (`cardformat.normalise`). A card the
// Mac refuses keeps the form open with the Mac's own sentence under it.
//
// Text cards save offline (queued, like every write). Pictures do not: the
// picture is stored on the Mac beside the set, and the card must name the path
// the Mac gives it — so image and labelled-picture cards say they need the Mac.

struct FlashcardEditorView: View {
    @EnvironmentObject var api: APIClient
    @EnvironmentObject var settings: AppSettings
    @ObservedObject private var store = FlashcardStore.shared
    @Environment(\.dismiss) private var dismiss
    let setId: Int

    @State private var editing: CardDraft?
    @State private var refusal: String?

    private var id: Int { store.current(setId) }

    var body: some View {
        StackNavigation {
            Group {
                if let set = store.sets[id] {
                    List {
                        if set.cards.isEmpty {
                            Text("No cards yet — tap + to add the first.")
                                .foregroundColor(.secondary)
                        }
                        ForEach(set.cards) { card in
                            Button { editing = CardDraft(card: card) } label: {
                                VStack(alignment: .leading, spacing: 3) {
                                    Text(card.title).lineLimit(2).foregroundColor(.primary)
                                    Text(FlashTypes.label(card.type) + (card.items.count > 1 ? " · \(card.items.count) questions" : ""))
                                        .font(.caption).foregroundColor(.secondary)
                                }
                            }
                            .environment(\.layoutDirection, set.isRTL ? .rightToLeft : .leftToRight)
                        }
                        .onDelete { offsets in
                            let ids = offsets.map { set.cards[$0].id }
                            Task {
                                for cid in ids {
                                    if let r = await store.deleteCard(cid, setId: id, api: api) { refusal = r }
                                }
                            }
                        }
                    }
                    .listStyle(.insetGrouped)
                    .navigationTitle(set.name)
                } else {
                    Text("This set's cards aren't on the phone yet. Open the tab while your Mac is reachable and they download.")
                        .multilineTextAlignment(.center)
                        .foregroundColor(.secondary)
                        .padding(24)
                        .navigationTitle("Cards")
                }
            }
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Done") { dismiss() } }
                ToolbarItem(placement: .primaryAction) {
                    Button { editing = CardDraft(card: FlashCard()) } label: { Image(systemName: "plus") }
                        .disabled(store.sets[id] == nil)
                        .accessibilityIdentifier("flashcards-add-card")
                }
            }
        }
        .sheet(item: $editing) { draft in
            CardForm(setId: id, card: draft.card, rtl: store.sets[id]?.isRTL ?? false)
                .environmentObject(api)
                .environmentObject(settings)
        }
        .alert("Couldn't do that", isPresented: Binding(
            get: { refusal != nil }, set: { if !$0 { refusal = nil } })) {
            Button("OK", role: .cancel) {}
        } message: { Text(refusal ?? "") }
    }
}

struct CardDraft: Identifiable {
    let id = UUID()
    var card: FlashCard
}

// MARK: - One card's form

struct CardForm: View {
    @EnvironmentObject var api: APIClient
    @EnvironmentObject var settings: AppSettings
    @Environment(\.dismiss) private var dismiss
    let setId: Int
    let rtl: Bool
    private let isNew: Bool

    @State private var card: FlashCard
    @State private var choices: [String]
    @State private var correct: Int?
    @State private var steps: [String]
    @State private var tagsText: String
    @State private var error: String?
    @State private var saving = false
    @State private var photo: PhotosPickerItem?
    @State private var uploading = false
    @State private var drawing = false

    init(setId: Int, card: FlashCard, rtl: Bool) {
        self.setId = setId
        self.rtl = rtl
        isNew = card.id == 0
        _card = State(initialValue: card)
        let ch = card.choices ?? ["", "", "", ""]
        _choices = State(initialValue: ch)
        _correct = State(initialValue: card.answer.flatMap { ch.firstIndex(of: $0) })
        _steps = State(initialValue: card.steps ?? ["", "", ""])
        _tagsText = State(initialValue: (card.tags ?? []).joined(separator: ", "))
    }

    private func text(_ kp: WritableKeyPath<FlashCard, String?>) -> Binding<String> {
        Binding(get: { card[keyPath: kp] ?? "" },
                set: { card[keyPath: kp] = $0.isEmpty ? nil : $0 })
    }

    var body: some View {
        StackNavigation {
            Form {
                if isNew {
                    Section {
                        Picker("Type", selection: $card.type) {
                            ForEach(FlashTypes.all, id: \.self) { Text(FlashTypes.label($0)).tag($0) }
                        }
                        .accessibilityIdentifier("flashcards-card-type")
                    }
                }
                fields
                    .environment(\.layoutDirection, rtl ? .rightToLeft : .leftToRight)
                Section {
                    TextField("Tags, comma separated", text: $tagsText)
                        .textInputAutocapitalization(.never)
                    TextField("Page or section", text: text(\.page))
                    TextField("Explanation, shown after answering", text: text(\.explain), axis: .vertical)
                } header: { Text("Optional") } footer: {
                    Text("Tags, page and explanation can change without losing what you've learned on the card.")
                }
                if let error {
                    Section {
                        Text(error).foregroundColor(.red).font(.callout)
                            .accessibilityIdentifier("flashcards-card-error")
                    }
                }
            }
            .navigationTitle(isNew ? "New card" : "Edit card")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") { Task { await save() } }
                        .disabled(saving || uploading)
                        .accessibilityIdentifier("flashcards-card-save")
                }
            }
            .onChange(of: photo) { item in
                guard let item else { return }
                Task { await upload(item) }
            }
            .sheet(isPresented: $drawing) {
                OcclusionDrawer(setId: setId, image: card.image ?? "",
                                labels: Binding(get: { card.labels ?? [] }, set: { card.labels = $0 }))
                    .environmentObject(api)
                    .environmentObject(settings)
            }
        }
    }

    // MARK: Fields per type

    @ViewBuilder private var fields: some View {
        switch card.type {
        case "basic":
            Section {
                TextField("Front — the question", text: text(\.front), axis: .vertical)
                    .accessibilityIdentifier("flashcards-card-front")
                TextField("Back — the answer", text: text(\.back), axis: .vertical)
                    .accessibilityIdentifier("flashcards-card-back")
                Toggle("Ask both ways", isOn: Binding(get: { card.bothWays == true },
                                                      set: { card.bothWays = $0 ? true : nil }))
            } footer: { Text("Both ways also asks back → front, scheduled separately.") }
        case "cloze":
            Section {
                TextField("Text", text: text(\.text), axis: .vertical)
                    .lineLimit(3...10)
            } footer: {
                let n = Cloze.gaps(card.text ?? "").count
                Text("Wrap each gap in double braces: The anthem was written by {{Naftali Herz Imber}} in {{1878}}. Each gap is its own question. "
                     + (n == 0 ? "No gaps marked yet." : "\(n) gap\(n == 1 ? "" : "s") marked."))
            }
        case "mc":
            Section("Question") {
                TextField("Question", text: text(\.question), axis: .vertical)
            }
            Section {
                ForEach(choices.indices, id: \.self) { i in
                    HStack {
                        Button { correct = i } label: {
                            Image(systemName: correct == i ? "checkmark.circle.fill" : "circle")
                                .foregroundColor(correct == i ? .green : .secondary)
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel(correct == i ? "Correct answer" : "Mark as correct")
                        TextField("Choice \(i + 1)", text: $choices[i])
                    }
                }
                .onDelete { offsets in
                    guard choices.count - offsets.count >= 2 else { return }
                    let wasCorrect = correct.map { choices[$0] }
                    choices.remove(atOffsets: offsets)
                    correct = wasCorrect.flatMap { choices.firstIndex(of: $0) }
                }
                if choices.count < 8 {
                    Button { choices.append("") } label: { Label("Add a choice", systemImage: "plus") }
                }
            } header: { Text("Choices") } footer: {
                Text("2 to 8 choices; tap the circle beside the right one. Wrong answers work best from the same topic.")
            }
        case "order":
            Section("Prompt") {
                TextField("e.g. Adult CPR, in order", text: text(\.prompt), axis: .vertical)
            }
            Section {
                ForEach(steps.indices, id: \.self) { i in
                    HStack {
                        Text("\(i + 1).").monospacedDigit().foregroundColor(.secondary)
                        TextField("Step \(i + 1)", text: $steps[i])
                    }
                }
                .onMove { steps.move(fromOffsets: $0, toOffset: $1) }
                .onDelete { offsets in
                    if steps.count - offsets.count >= 2 { steps.remove(atOffsets: offsets) }
                }
                if steps.count < 20 {
                    Button { steps.append("") } label: { Label("Add a step", systemImage: "plus") }
                }
            } header: {
                HStack { Text("Steps, in the right order"); Spacer(); EditButton().font(.caption) }
            } footer: { Text("The app shuffles them when it asks.") }
        case "typed":
            Section {
                TextField("What to write out", text: text(\.front), axis: .vertical)
            }
            Section("The answer, exactly") {
                TextEditor(text: text(\.answer)).frame(minHeight: 120)
            }
        case "image":
            pictureSection
            Section {
                TextField("Prompt (optional) — What is this?", text: text(\.front))
                TextField("Answer — what the picture shows", text: text(\.back))
                Toggle("Ask both ways", isOn: Binding(get: { card.bothWays == true },
                                                      set: { card.bothWays = $0 ? true : nil }))
            }
        case "occlusion":
            pictureSection
            Section {
                TextField("Prompt (optional) — Name the hidden place", text: text(\.prompt))
                Picker("Ask", selection: Binding(get: { card.ask ?? "one_at_a_time" }, set: { card.ask = $0 })) {
                    Text("One label at a time").tag("one_at_a_time")
                    Text("All at once").tag("all_at_once")
                }
                Button {
                    drawing = true
                } label: {
                    Label("Draw boxes over the labels (\(card.labels?.count ?? 0))", systemImage: "rectangle.dashed")
                }
                .disabled(card.image == nil)
            } footer: {
                Text("Draw a box over each printed label and name it. One at a time asks each label as its own question.")
            }
        default:
            EmptyView()
        }
    }

    private var pictureSection: some View {
        Section {
            if let path = card.image {
                FlashPicture(setId: setId, path: path) { size in
                    if card.type == "occlusion" {
                        OcclusionBoxes(labels: card.labels ?? [], size: size, target: nil,
                                       revealed: Set(0..<(card.labels?.count ?? 0)),
                                       accent: settings.accentColor, onTap: nil)
                    }
                }
                .frame(maxHeight: 240)
            }
            PhotosPicker(selection: $photo, matching: .images) {
                Label(card.image == nil ? "Choose a picture" : "Change picture", systemImage: "photo")
            }
            .disabled(uploading)
            if uploading { ProgressView("Sending the picture to your Mac…") }
        } footer: {
            Text("The picture is kept on your Mac beside the set, so adding one needs the Mac reachable.")
        }
    }

    // MARK: Actions

    private func upload(_ item: PhotosPickerItem) async {
        guard setId > 0 else {
            error = "This set hasn't reached your Mac yet. Pictures are stored there, so add picture cards once the set has synced."
            return
        }
        uploading = true
        defer { uploading = false; photo = nil }
        guard let raw = try? await item.loadTransferable(type: Data.self),
              let img = UIImage(data: raw) else {
            error = "Couldn't read that picture."
            return
        }
        let data = img.jpegData(compressionQuality: 0.85) ?? raw
        let name = "photo-\(UUID().uuidString.prefix(8).lowercased()).jpg"
        do {
            let path = try await api.uploadFlashMedia(setId: setId, filename: name, data: data, mime: "image/jpeg")
            FlashcardStore.shared.storeImage(data, setId: setId, path: path)
            if card.image != nil && card.type == "occlusion" { card.labels = [] }
            card.image = path
            error = nil
        } catch APIError.offline, APIError.badURL {
            error = "Adding a picture needs your Mac — it keeps the picture beside the set. Try again when the phone can reach it."
        } catch {
            self.error = FlashcardStore.sentence(for: error)
        }
    }

    private func save() async {
        var c = card
        let trim = { (s: String) in s.trimmingCharacters(in: .whitespacesAndNewlines) }
        if c.type == "mc" {
            let pairs = choices.enumerated().map { ($0.offset, trim($0.element)) }.filter { !$0.1.isEmpty }
            c.choices = pairs.map(\.1)
            c.answer = correct.flatMap { i in pairs.first { $0.0 == i }?.1 }
        }
        if c.type == "order" { c.steps = steps.map(trim).filter { !$0.isEmpty } }
        let tags = tagsText.split(separator: ",").map { trim(String($0)) }.filter { !$0.isEmpty }
        c.tags = tags.isEmpty ? nil : tags
        if let problem = Self.problem(c) { error = problem; return }
        saving = true
        defer { saving = false }
        if let refusal = await FlashcardStore.shared.saveCard(c, setId: setId, api: api) {
            error = refusal
        } else {
            dismiss()
        }
    }

    /// The obvious refusals, said here — a card made offline is only checked by
    /// the Mac when the queue replays, and a refusal then has no form to show in.
    static func problem(_ c: FlashCard) -> String? {
        func empty(_ s: String?) -> Bool { (s ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
        switch c.type {
        case "basic":
            if empty(c.front) || empty(c.back) { return "A basic card needs a front and a back." }
        case "cloze":
            if Cloze.gaps(c.text ?? "").isEmpty { return "Mark at least one gap with {{double braces}}." }
        case "mc":
            if empty(c.question) { return "Write the question." }
            let ch = c.choices ?? []
            if ch.count < 2 || ch.count > 8 { return "A multiple-choice card needs 2 to 8 choices." }
            if Set(ch).count != ch.count { return "Two choices are the same — make each one different." }
            if c.answer == nil { return "Tap the circle beside the right answer." }
        case "order":
            if empty(c.prompt) { return "Write the prompt." }
            let n = c.steps?.count ?? 0
            if n < 2 || n > 20 { return "An order card needs 2 to 20 steps." }
        case "typed":
            if empty(c.front) || empty(c.answer) { return "Write what to write out, and the answer." }
        case "image":
            if c.image == nil { return "Choose a picture." }
            if empty(c.back) { return "Say what the picture shows." }
        case "occlusion":
            if c.image == nil { return "Choose a picture." }
            let labels = c.labels ?? []
            if labels.isEmpty { return "Draw at least one box over a label." }
            if labels.contains(where: { empty($0.text) }) { return "Name every box you drew." }
        default: break
        }
        return nil
    }
}

// MARK: - Drawing occlusion boxes

/// The picture, full width: drag on it to draw a box over a printed label, then
/// name the box below. Boxes are stored in PERCENT of the picture, from its
/// top-left — FORMAT.md's `box: [x, y, width, height]`.
struct OcclusionDrawer: View {
    @EnvironmentObject var settings: AppSettings
    @Environment(\.dismiss) private var dismiss
    let setId: Int
    let image: String
    @Binding var labels: [FlashLabel]

    @State private var draft: CGRect?

    var body: some View {
        StackNavigation {
            VStack(spacing: 0) {
                FlashPicture(setId: setId, path: image) { size in
                    ZStack(alignment: .topLeading) {
                        OcclusionBoxes(labels: labels, size: size, target: nil,
                                       revealed: Set(labels.indices), accent: settings.accentColor, onTap: nil)
                        ForEach(labels.indices, id: \.self) { i in
                            Text("\(i + 1)")
                                .font(.caption2.bold())
                                .padding(2)
                                .background(settings.accentColor)
                                .foregroundColor(.black)
                                .offset(x: labels[i].rect.minX * size.width,
                                        y: max(0, labels[i].rect.minY * size.height - 14))
                        }
                        if let d = draft {
                            Rectangle()
                                .stroke(settings.accentColor, style: StrokeStyle(lineWidth: 2, dash: [4]))
                                .frame(width: d.width * size.width, height: d.height * size.height)
                                .offset(x: d.minX * size.width, y: d.minY * size.height)
                        }
                    }
                    .frame(width: size.width, height: size.height, alignment: .topLeading)
                    .contentShape(Rectangle())
                    .gesture(DragGesture(minimumDistance: 2)
                        .onChanged { v in draft = Self.rect(v.startLocation, v.location, in: size) }
                        .onEnded { v in
                            let r = Self.rect(v.startLocation, v.location, in: size)
                            draft = nil
                            guard r.width > 0.005, r.height > 0.005 else { return }
                            labels.append(FlashLabel(text: "", box: [r.minX, r.minY, r.width, r.height]
                                .map { Double(($0 * 1000).rounded()) / 10.0 }))
                        })
                }
                .environment(\.layoutDirection, .leftToRight)
                .padding(8)
                .frame(maxHeight: 420)

                List {
                    if labels.isEmpty {
                        Text("Drag across the picture to cover a label.").foregroundColor(.secondary)
                    }
                    ForEach(labels.indices, id: \.self) { i in
                        HStack {
                            Text("\(i + 1).").monospacedDigit().foregroundColor(.secondary)
                            TextField("What the label says", text: $labels[i].text)
                        }
                    }
                    .onDelete { labels.remove(atOffsets: $0) }
                }
                .listStyle(.plain)
            }
            .navigationTitle("Boxes")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
                ToolbarItem(placement: .cancellationAction) {
                    Button("Undo") { _ = labels.popLast() }.disabled(labels.isEmpty)
                }
            }
        }
    }

    /// Two points -> a rectangle in 0...1 of the picture, clamped inside it.
    static func rect(_ a: CGPoint, _ b: CGPoint, in size: CGSize) -> CGRect {
        guard size.width > 0, size.height > 0 else { return .zero }
        func clamp(_ v: CGFloat) -> CGFloat { min(1, max(0, v)) }
        let x0 = clamp(min(a.x, b.x) / size.width), x1 = clamp(max(a.x, b.x) / size.width)
        let y0 = clamp(min(a.y, b.y) / size.height), y1 = clamp(max(a.y, b.y) / size.height)
        return CGRect(x: x0, y: y0, width: x1 - x0, height: y1 - y0)
    }
}
