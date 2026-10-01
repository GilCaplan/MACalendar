import SwiftUI

/// The Mac's Easter-egg settings window — the phone's settings, laid out for
/// a Mac: emoji, flags and symbols, your own photos (cut out by the phone's
/// own pipeline, `EggImageCore`), paths drawn with the mouse, suggested
/// words, and the one-word-one-thing rule.
struct MacSettingsView: View {
    @ObservedObject private var store = MacEggStore.shared
    @State private var previewID = "dog"
    @State private var selected: String?
    @State private var newSymbol = false
    @State private var newPhoto = false
    @State private var drawing = false

    var body: some View {
        HSplitView {
            Form {
                Section {
                    Toggle("Magic words", isOn: $store.settings.enabled)
                    MacPreview(objectID: previewID).frame(height: 180)
                    Picker("Preview", selection: $previewID) {
                        ForEach(store.settings.objects) { Text($0.name).tag($0.id) }
                    }
                    Button("Play a demo on the whole screen") { store.demo() }
                    Button("New magic word from an emoji, flag or symbol…") { newSymbol = true }
                    Button("New magic word from a photo…") { newPhoto = true }
                }
                if !store.conflicts.isEmpty {
                    Section {
                        ForEach(store.conflicts, id: \.word) { c in
                            HStack {
                                Text("“\(c.word)”")
                                Text(c.ids.compactMap { id in store.settings.objects.first { $0.id == id }?.name }
                                        .joined(separator: " and ")).foregroundColor(.secondary)
                                Spacer()
                                Menu("Keep on…") {
                                    ForEach(c.ids, id: \.self) { id in
                                        Button(store.settings.objects.first { $0.id == id }?.name ?? id) {
                                            store.keepWord(c.word, on: id)
                                        }
                                    }
                                }
                                .fixedSize()
                            }
                        }
                    } header: { Text("Words on two things") } footer: {
                        Text("A word can only summon one thing. Choose which keeps it.")
                    }
                }
                Section("When") {
                    Picker("Show it", selection: $store.settings.trigger) {
                        ForEach(EggTrigger.allCases, id: \.self) { Text($0.label).tag($0) }
                    }
                    Picker("Several at once", selection: $store.settings.group) {
                        ForEach(EggGroupMode.allCases, id: \.self) { Text($0.label).tag($0) }
                    }
                    Picker("A plural brings", selection: $store.settings.pluralCount) {
                        Text("Just one").tag(1); Text("2").tag(2); Text("3").tag(3); Text("5").tag(5)
                    }
                }
                Section("Movement") {
                    Picker("Motion", selection: $store.settings.motion) {
                        ForEach(EggMotion.allCases.filter { $0 != .drawn || store.settings.drawnPath != nil }, id: \.self) {
                            Text($0 == .auto ? "Each one's own" : $0.label).tag($0)
                        }
                    }
                    Button(store.settings.drawnPath == nil ? "Draw a path…" : "Redraw the path…") { drawing = true }
                    Picker("Direction", selection: $store.settings.direction) {
                        ForEach(EggDirection.allCases, id: \.self) { Text($0 == .auto ? "Each one's own" : $0.label).tag($0) }
                    }
                    Picker("Trail", selection: $store.settings.trail) {
                        ForEach(EggTrail.allCases, id: \.self) { Text($0 == .auto ? "Each one's own" : $0.label).tag($0) }
                    }
                }
                Section("Timing") {
                    slider("Coming in", $store.settings.entrance, 0.3...5)
                    slider("Pause in the middle", $store.settings.pause, 0...10)
                    slider("Going out", $store.settings.exit, 0.3...5)
                }
                Section("Look") {
                    slider("Solid", $store.settings.opacity, 0.15...1, unit: "")
                    Picker("Style", selection: $store.settings.look) {
                        ForEach(EggLook.allCases, id: \.self) { Text($0.label).tag($0) }
                    }
                    slider("Size", Binding(get: { store.settings.sizePercent / 100 },
                                           set: { store.settings.sizePercent = ($0 * 100).rounded() }), 0.5...1.6, unit: "")
                    Picker("Where on the screen", selection: $store.settings.lane) {
                        ForEach(EggLane.allCases, id: \.self) { Text($0.label).tag($0) }
                    }
                    Toggle("Clicks go through to the apps underneath", isOn: $store.settings.passThrough)
                }
                Section("Sound") {
                    Toggle("Sound", isOn: $store.settings.sound)
                    if store.settings.sound { slider("Volume", $store.settings.volume, 0...1, unit: "") }
                }
                MacLoaderSettings()
                Section("Keep it a surprise") {
                    Picker("Play", selection: $store.settings.chance) {
                        Text("Every time").tag(1); Text("1 time in 2").tag(2); Text("1 time in 3").tag(3)
                        Text("1 time in 5").tag(5); Text("1 time in 10").tag(10)
                    }
                    Picker("Not again within", selection: $store.settings.cooldown) {
                        Text("No wait").tag(0.0); Text("1 minute").tag(60.0); Text("5 minutes").tag(300.0); Text("1 hour").tag(3600.0)
                    }
                    Toggle("Quiet hours (22:00–07:00)", isOn: $store.settings.quietHours)
                }
                Section("Jewish festivals") {
                    Toggle("Jewish festivals", isOn: $store.settings.jewish)
                    Toggle("Their words only in their season", isOn: $store.settings.jewishInSeason)
                    Toggle("Greet me on festival days", isOn: $store.settings.festivalGreeting)
                }
            }
            .formStyle(.grouped)
            .frame(minWidth: 320)

            List(selection: $selected) {
                ForEach(store.settings.objects) { o in
                    VStack(alignment: .leading) {
                        Text(o.name).foregroundColor(o.enabled ? .primary : .secondary)
                        Text(o.keywords.joined(separator: ", ")).font(.caption).foregroundColor(.secondary).lineLimit(1)
                    }
                    .tag(o.id)
                }
            }
            .frame(minWidth: 180)
            .sheet(item: Binding(get: { selected.map(Selected.init) }, set: { selected = $0?.id })) { s in
                MacWordEditor(id: s.id).frame(width: 440, height: 640)
            }
            .sheet(isPresented: $newSymbol) { MacSymbolEditor(mode: .newObject) }
            .sheet(isPresented: $newPhoto) { MacPhotoSheet(mode: .newObject) }
            .sheet(isPresented: $drawing) {
                MacPathDrawer(objectID: nil, path: Binding(
                    get: { store.settings.drawnPath },
                    set: { p in
                        store.settings.drawnPath = p
                        if p != nil { store.settings.motion = .drawn }
                    }))
            }
        }
        .frame(minWidth: 560, minHeight: 640)
    }

    private struct Selected: Identifiable { let id: String }

    private func slider(_ t: String, _ v: Binding<Double>, _ r: ClosedRange<Double>, unit: String = " s") -> some View {
        HStack {
            Text(t)
            Slider(value: v, in: r)
            Text(unit.isEmpty ? "\(Int(v.wrappedValue * 100))%" : String(format: "%.1f%@", v.wrappedValue, unit))
                .monospacedDigit().frame(width: 48, alignment: .trailing)
        }
    }
}

/// One word: on/off, its words, motion, direction, trail, size, place, sound.
struct MacWordEditor: View {
    let id: String
    @ObservedObject private var store = MacEggStore.shared
    @Environment(\.dismiss) private var dismiss
    @State private var word = ""
    @State private var suggesting = false
    @State private var addingSymbol = false
    @State private var addingPhoto = false
    @State private var drawingPath = false
    /// Words waiting on "move it here, or keep it where it is?".
    @State private var asking: [String] = []

    var body: some View {
        if let i = store.settings.objects.firstIndex(where: { $0.id == id }) {
            let o = store.settings.objects[i]
            Form {
                Section(o.name) {
                    Toggle("On", isOn: $store.settings.objects[i].enabled)
                    MacPreview(objectID: id).frame(height: 150)
                    if o.variants.count > 1 {
                        Picker("Graphic", selection: $store.settings.objects[i].active) {
                            ForEach(o.variants, id: \.id) { v in
                                Text(v.isOriginal ? "Original" : v.name).tag(v.id)
                            }
                        }
                    }
                    Button("Play it") { store.play([id], together: true) }
                    Button("Add an emoji, flag or symbol…") { addingSymbol = true }
                    Button("Add a photo…") { addingPhoto = true }
                    if o.active != EggVariant.originalID {
                        Button("Delete this graphic", role: .destructive) { store.deleteVariant(o.active, from: id) }
                    }
                    if !o.builtin {
                        Button("Delete this magic word", role: .destructive) { dismiss(); store.deleteObject(id) }
                    }
                }
                Section("Words that summon it") {
                    ForEach(o.keywords, id: \.self) { k in
                        HStack { Text(k); Spacer(); Button("Remove") { store.settings.objects[i].keywords.removeAll { $0 == k } } }
                    }
                    HStack {
                        TextField("Add a word", text: $word).onSubmit(addTyped)
                        Button("Add", action: addTyped)
                    }
                    Button("Suggest words…") { suggesting = true }
                }
                Section("This one's own") {
                    Picker("Motion", selection: $store.settings.objects[i].motion) {
                        ForEach(EggMotion.allCases.filter { $0 != .drawn || o.drawnPath != nil }, id: \.self) { Text($0.label).tag($0) }
                    }
                    Button(o.drawnPath == nil ? "Draw the path…" : "Redraw the path…") { drawingPath = true }
                    Picker("Direction", selection: $store.settings.objects[i].direction) {
                        ForEach(EggDirection.allCases, id: \.self) { Text($0.label).tag($0) }
                    }
                    Picker("Trail", selection: $store.settings.objects[i].trail) {
                        ForEach(EggTrail.allCases, id: \.self) { Text($0.label).tag($0) }
                    }
                    HStack {
                        Text("Size")
                        Slider(value: Binding(get: { o.sizePercent ?? store.settings.sizePercent },
                                              set: { store.settings.objects[i].sizePercent = $0.rounded() }),
                               in: EggSizeRange.percent)
                        Text("\(Int(o.sizePercent ?? store.settings.sizePercent))%").monospacedDigit().frame(width: 48, alignment: .trailing)
                        if o.sizePercent != nil { Button("Same as the rest") { store.settings.objects[i].sizePercent = nil } }
                    }
                    Picker("Sound", selection: $store.settings.objects[i].sound) {
                        Text("Its own").tag(EggSound?.none)
                        ForEach(EggSound.allCases.filter { $0 != .auto }, id: \.self) { Text($0.label).tag(EggSound?.some($0)) }
                    }
                }
                Button("Done") { dismiss() }
            }
            .formStyle(.grouped)
            .sheet(isPresented: $suggesting) {
                MacSuggestSheet(name: o.name, objectID: id, existing: o.keywords) { adding($0) }
            }
            .sheet(isPresented: $addingSymbol) { MacSymbolEditor(mode: .addTo(id)) }
            .sheet(isPresented: $addingPhoto) { MacPhotoSheet(mode: .addTo(id)) }
            .sheet(isPresented: $drawingPath) {
                MacPathDrawer(objectID: id, path: Binding(
                    get: { store.settings.objects.first { $0.id == id }?.drawnPath },
                    set: { p in
                        guard let j = store.settings.objects.firstIndex(where: { $0.id == id }) else { return }
                        store.settings.objects[j].drawnPath = p
                        if p != nil { store.settings.objects[j].motion = .drawn }
                    }))
            }
            .alert(asking.count == 1 ? "That word is taken" : "Some words are taken",
                   isPresented: Binding(get: { !asking.isEmpty }, set: { if !$0 { asking = [] } })) {
                Button("Move \(asking.count == 1 ? "it" : "them") to “\(o.name)”") {
                    for w in asking { store.addKeyword(w, to: id) }
                    asking = []
                }
                Button("Keep \(asking.count == 1 ? "it where it is" : "them where they are")", role: .cancel) { asking = [] }
            } message: {
                Text(asking.map { w in "“\(w)” already summons \(store.owner(of: w, besides: id)?.name ?? "something else")." }
                        .joined(separator: " ") + " A word can only summon one thing.")
            }
        }
    }

    private func addTyped() {
        adding([word])
        word = ""
    }

    /// Add words; any another magic word already has are asked about first.
    private func adding(_ words: [String]) {
        let clean = words.map { $0.trimmingCharacters(in: .whitespaces).lowercased() }.filter { !$0.isEmpty }
        let taken = clean.filter { store.owner(of: $0, besides: id) != nil }
        for w in clean where !taken.contains(w) { store.addKeyword(w, to: id) }
        if !taken.isEmpty {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { asking = taken }
        }
    }
}

/// The live preview, as on the phone.
struct MacPreview: View {
    let objectID: String
    @ObservedObject private var store = MacEggStore.shared
    @State private var from = Date()

    var body: some View {
        TimelineView(.animation) { tl in
            Canvas { ctx, size in
                ctx.fill(Path(roundedRect: CGRect(origin: .zero, size: size), cornerRadius: 12), with: .color(Color(egg: 0x3b4663)))
                let s = store.settings
                guard let o = s.objects.first(where: { $0.id == objectID }) else { return }
                let show = EggStage.build(o, settings: s)
                let loop = s.entrance + (show.holdForever ? 2 : show.hold) + s.exit + 0.6
                let e = tl.date.timeIntervalSince(from).truncatingRemainder(dividingBy: loop)
                let p = show.progress(elapsed: e, releasedAfter: show.holdForever ? s.entrance + 2 : nil)
                EggRender.draw(show, ctx, size, progress: p, t: e, image: { store.image($0) })
            }
        }
    }
}
