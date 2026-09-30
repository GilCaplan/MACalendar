import SwiftUI
import PhotosUI

/// Settings ▸ Easter egg: magic words, and what they summon.
struct EggSettingsView: View {
    @ObservedObject private var store = EggStore.shared
    @State private var newObject = false
    @State private var drawing = false
    @State private var previewID = "dog"

    /// Minutes of the day as a Date for the time pickers.
    private func minutes(_ m: Binding<Int>) -> Binding<Date> {
        Binding(get: {
            Calendar.current.date(bySettingHour: m.wrappedValue / 60, minute: m.wrappedValue % 60, second: 0, of: Date()) ?? Date()
        }, set: { d in
            let c = Calendar.current.dateComponents([.hour, .minute], from: d)
            m.wrappedValue = (c.hour ?? 0) * 60 + (c.minute ?? 0)
        })
    }

    private func secondsRow(_ title: String, _ value: Binding<Double>, _ range: ClosedRange<Double>) -> some View {
        VStack(alignment: .leading) {
            HStack { Text(title); Spacer(); Text("\(value.wrappedValue, specifier: "%.1f") s").foregroundColor(.secondary).monospacedDigit() }
            Slider(value: value, in: range, step: 0.1)
        }
    }

    var body: some View {
        Form {
            Section {
                Toggle("Magic words", isOn: $store.settings.enabled)
            } footer: {
                Text("Say a magic word and its picture plays across the screen. Your commands still run as usual; "
                     + "a magic word said on its own is just for fun and isn't sent to your Mac.")
            }

            if store.settings.enabled {
                Section {
                    EggLivePreview(objectID: previewID).padding(.vertical, 6)
                    Picker("Preview", selection: $previewID) {
                        ForEach(store.settings.objects) { Text($0.name).tag($0.id) }
                    }
                    Button {
                        let pool = store.settings.objects.filter(\.enabled).map(\.id).shuffled()
                        store.demo(Array(pool.prefix(store.settings.group == .oneAfterAnother ? 2 : 3)))
                    } label: { Label("Play a demo on the whole screen", systemImage: "play.circle") }
                } header: { Text("Preview") } footer: {
                    Text("Every change below shows here at once.")
                }

                Section {
                    Picker("Show it", selection: $store.settings.trigger) {
                        ForEach(EggTrigger.allCases, id: \.self) { Text($0.label).tag($0) }
                    }
                    Picker("Several at once", selection: $store.settings.group) {
                        ForEach(EggGroupMode.allCases, id: \.self) { Text($0.label).tag($0) }
                    }
                    if store.settings.group == .onGroupWord {
                        TextField("Group words", text: Binding(
                            get: { store.settings.groupWords.joined(separator: ", ") },
                            set: { store.settings.groupWords = $0.split(separator: ",")
                                    .map { $0.trimmingCharacters(in: .whitespaces).lowercased() }.filter { !$0.isEmpty } }))
                            .textInputAutocapitalization(.never).autocorrectionDisabled()
                    }
                    Picker("A plural brings", selection: $store.settings.pluralCount) {
                        Text("Just one").tag(1)
                        Text("2").tag(2)
                        Text("3").tag(3)
                        Text("5").tag(5)
                    }
                } header: { Text("When") } footer: {
                    Text("“Dogs” brings a pack; “a pack of dogs” groups them when group words are on.")
                }

                Section {
                    Picker("Motion", selection: $store.settings.motion) {
                        ForEach(EggMotion.allCases, id: \.self) {
                            Text($0 == .auto ? "Each one's own" : $0.label).tag($0)
                        }
                    }
                    if store.settings.motion == .drawn {
                        Button { drawing = true } label: {
                            Label(store.settings.drawnPath == nil ? "Draw the path…" : "Redraw the path…",
                                  systemImage: "scribble.variable")
                        }
                    }
                    Picker("Direction", selection: $store.settings.direction) {
                        ForEach(EggDirection.allCases, id: \.self) {
                            Text($0 == .auto ? "Each one's own" : $0.label).tag($0)
                        }
                    }
                    Picker("Trail", selection: $store.settings.trail) {
                        ForEach(EggTrail.allCases, id: \.self) {
                            Text($0 == .auto ? "Each one's own" : $0.label).tag($0)
                        }
                    }
                } header: { Text("Movement") } footer: {
                    Text("“Each one's own” lets every word keep what's set on its page.")
                }

                Section {
                    secondsRow("Coming in", $store.settings.entrance, 0.3...5)
                    secondsRow("Pause in the middle", $store.settings.pause, 0...10)
                    secondsRow("Going out", $store.settings.exit, 0.3...5)
                    Toggle("Stay until I tap it", isOn: $store.settings.untilTapped)
                        .disabled(store.settings.passThrough)
                } header: { Text("Timing") } footer: {
                    Text(store.settings.passThrough
                         ? "“Stay until I tap it” needs taps, so it's off while touches go through."
                         : "The pause happens in the middle of the screen; a tap lets it carry on.")
                }

                Section("Look") {
                    VStack(alignment: .leading) {
                        Text("Solid \(Int((store.settings.opacity * 100).rounded()))%")
                        Slider(value: $store.settings.opacity, in: 0.15...1)
                    }
                    Picker("Style", selection: $store.settings.look) {
                        ForEach(EggLook.allCases, id: \.self) { Text($0.label).tag($0) }
                    }
                    VStack(alignment: .leading) {
                        Text("Size \(Int(store.settings.sizePercent))%")
                        Slider(value: $store.settings.sizePercent, in: EggSizeRange.percent, step: 5)
                    }
                    Picker("Where on the screen", selection: $store.settings.lane) {
                        ForEach(EggLane.allCases, id: \.self) { Text($0.label).tag($0) }
                    }
                }

                Section {
                    Toggle("Sound", isOn: $store.settings.sound)
                    if store.settings.sound {
                        HStack {
                            Image(systemName: "speaker.fill").foregroundColor(.secondary)
                            Slider(value: $store.settings.volume, in: 0...1)
                            Image(systemName: "speaker.wave.3.fill").foregroundColor(.secondary)
                        }
                        ScrollView(.horizontal, showsIndicators: false) {
                            HStack {
                                ForEach(EggSound.allCases.filter { $0 != .auto && $0 != .none }, id: \.self) { snd in
                                    Button(snd.label) { EggSounds.shared.play(snd, volume: store.settings.volume) }
                                        .buttonStyle(.bordered)
                                }
                            }
                        }
                    }
                    Toggle("Haptics", isOn: $store.settings.haptics)
                } header: { Text("Sound & feel") } footer: {
                    Text("Every sound is made on the phone. They follow the ring switch.")
                }

                EggFestivalSection()

                Section {
                    NavigationLink { EggLoaderSettingsView() } label: {
                        HStack(spacing: 12) {
                            EggLoaderView(side: 40)
                            VStack(alignment: .leading, spacing: 2) {
                                Text("Loading screen")
                                Text(store.settings.loader.enabled ? store.settings.loader.style.label : "Off")
                                    .font(.caption).foregroundColor(.secondary)
                            }
                        }
                    }
                } footer: {
                    Text("Build what plays whenever the app is waiting — your own wheel of death.")
                }

                Section {
                    Picker("Play", selection: $store.settings.chance) {
                        Text("Every time").tag(1)
                        Text("1 time in 2").tag(2)
                        Text("1 time in 3").tag(3)
                        Text("1 time in 5").tag(5)
                        Text("1 time in 10").tag(10)
                    }
                    Picker("Not again within", selection: $store.settings.cooldown) {
                        Text("No wait").tag(0.0)
                        Text("30 seconds").tag(30.0)
                        Text("1 minute").tag(60.0)
                        Text("5 minutes").tag(300.0)
                        Text("30 minutes").tag(1800.0)
                        Text("1 hour").tag(3600.0)
                    }
                    Toggle("Quiet hours", isOn: $store.settings.quietHours)
                    if store.settings.quietHours {
                        DatePicker("From", selection: minutes($store.settings.quietFrom), displayedComponents: .hourAndMinute)
                        DatePicker("Until", selection: minutes($store.settings.quietTo), displayedComponents: .hourAndMinute)
                    }
                } header: { Text("Keep it a surprise") } footer: {
                    Text("Held back, a magic word said on its own still isn't sent to your Mac.")
                }

                Section {
                    Toggle("Also for what gets made", isOn: $store.settings.forWhatsMade)
                    if store.settings.forWhatsMade {
                        NavigationLink("Which plays for what") { EggMadeMapView() }
                    }
                } header: { Text("What gets made") } footer: {
                    Text("A command that books a trip can bring the plane even if you never said “plane”: "
                         + "an event's category or a task's tag picks what plays.")
                }

                Section {
                    Toggle("Touches go through to the app", isOn: $store.settings.passThrough)
                    if !store.settings.passThrough {
                        Picker("A tap", selection: $store.settings.tap) {
                            ForEach(EggTap.allCases, id: \.self) { Text($0.label).tag($0) }
                        }
                    }
                } header: { Text("Touch") } footer: {
                    Text(store.settings.passThrough
                         ? "It just plays: you can keep scrolling and tapping underneath."
                         : "While it plays, a tap anywhere is for the animation.")
                }
            }

            Section {
                ForEach(store.settings.objects) { o in
                    NavigationLink { EggObjectView(id: o.id) } label: {
                        HStack(spacing: 12) {
                            EggThumb(variant: o.activeVariant).frame(width: 44, height: 44)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(o.name).foregroundColor(o.enabled ? .primary : .secondary)
                                Text(o.keywords.isEmpty ? "No words yet" : o.keywords.joined(separator: ", "))
                                    .font(.caption).foregroundColor(.secondary).lineLimit(1)
                            }
                        }
                    }
                }
                Button { newObject = true } label: { Label("New from a photo…", systemImage: "photo.badge.plus") }
            } header: {
                Text("Magic words")
            } footer: {
                Text("Each one has its words and its pictures. The original always stays; add your own photos "
                     + "and pick which one plays.")
            }
        }
        .navigationTitle("Easter egg")
        .sheet(isPresented: $newObject) { EggPhotoEditor(mode: .newObject) }
        .sheet(isPresented: $drawing) { EggPathDrawer(objectID: nil, path: $store.settings.drawnPath) }
    }
}

/// One object: its words, its motion, its graphics and which one plays.
struct EggObjectView: View {
    let id: String
    @ObservedObject private var store = EggStore.shared
    @State private var word = ""
    @State private var note: String?
    @State private var adding = false
    @State private var editing: EggVariant?
    @State private var confirmDelete = false
    @State private var suggesting = false
    @State private var drawing = false
    @Environment(\.dismiss) private var dismiss

    private var i: Int? { store.index(id) }

    var body: some View {
        if let i {
            let o = store.settings.objects[i]
            Form {
                Section {
                    EggLivePreview(objectID: id).padding(.vertical, 6)
                    Toggle("On", isOn: $store.settings.objects[i].enabled)
                    if !o.builtin { TextField("Name", text: $store.settings.objects[i].name) }
                    Button { store.demo([o.id]) } label: { Label("Play it on the whole screen", systemImage: "play.circle") }
                }

                Section {
                    ForEach(o.keywords, id: \.self) { Text($0) }
                        .onDelete { idx in idx.map { o.keywords[$0] }.forEach { store.removeKeyword($0, from: id) } }
                    HStack {
                        TextField("Add a word", text: $word)
                            .textInputAutocapitalization(.never).autocorrectionDisabled()
                            .onSubmit(add)
                        Button("Add", action: add).disabled(word.trimmingCharacters(in: .whitespaces).isEmpty)
                    }
                    Button { suggesting = true } label: { Label("Suggest words…", systemImage: "sparkles") }
                    if o.builtin {
                        Button("Reset to the original words") { store.resetKeywords(id) }
                    }
                } header: { Text("Words that summon it") } footer: {
                    Text(note ?? "Plurals count too: “dog” also answers to “dogs”.")
                }

                if case .effect = o.activeVariant.source {} else {
                    Section {
                        Picker("Motion", selection: $store.settings.objects[i].motion) {
                            ForEach(EggMotion.allCases, id: \.self) {
                                Text($0 == .auto ? "Its own (\(EggCatalog.defaultMotion(id).label))" : $0.label).tag($0)
                            }
                        }
                        if o.motion == .drawn {
                            Button { drawing = true } label: {
                                Label(o.drawnPath == nil ? "Draw the path…" : "Redraw the path…",
                                      systemImage: "scribble.variable")
                            }
                        }
                        Picker("Direction", selection: $store.settings.objects[i].direction) {
                            ForEach(EggDirection.allCases, id: \.self) { Text($0.label).tag($0) }
                        }
                        Picker("Trail", selection: $store.settings.objects[i].trail) {
                            ForEach(EggTrail.allCases, id: \.self) {
                                Text($0 == .auto ? "Its own (\(EggCatalog.defaultTrail(id).label))" : $0.label).tag($0)
                            }
                        }
                    } header: { Text("Motion") } footer: {
                        if store.settings.motion != .auto || store.settings.direction != .auto || store.settings.trail != .auto {
                            Text("A choice for everything on the Easter egg page overrides these.")
                        }
                    }
                }

                Section {
                    VStack(alignment: .leading) {
                        HStack {
                            Text("Size \(Int(o.sizePercent ?? store.settings.sizePercent))%")
                            Spacer()
                            if o.sizePercent != nil {
                                Button("Same as the rest") { store.settings.objects[i].sizePercent = nil }
                                    .font(.caption).buttonStyle(.borderless)
                            } else {
                                Text("like the rest").font(.caption).foregroundColor(.secondary)
                            }
                        }
                        Slider(value: value(i, \.sizePercent, store.settings.sizePercent), in: EggSizeRange.percent, step: 5)
                    }
                    Picker("Where on the screen", selection: optional($store.settings.objects[i].lane)) {
                        Text("Like the rest").tag(EggLane?.none)
                        ForEach(EggLane.allCases, id: \.self) { Text($0.label).tag(EggLane?.some($0)) }
                    }
                    Picker("Sound", selection: optional($store.settings.objects[i].sound)) {
                        Text("Its own").tag(EggSound?.none)
                        ForEach(EggSound.allCases.filter { $0 != .auto }, id: \.self) { Text($0.label).tag(EggSound?.some($0)) }
                    }
                    Toggle("Its own timing", isOn: Binding(
                        get: { o.entrance != nil },
                        set: { on in
                            store.settings.objects[i].entrance = on ? store.settings.entrance : nil
                            store.settings.objects[i].pause = on ? store.settings.pause : nil
                            store.settings.objects[i].exit = on ? store.settings.exit : nil
                        }))
                    if o.entrance != nil {
                        secondsRow("Coming in", value(i, \.entrance, store.settings.entrance), 0.3...5)
                        secondsRow("Pause in the middle", value(i, \.pause, store.settings.pause), 0...10)
                        secondsRow("Going out", value(i, \.exit, store.settings.exit), 0.3...5)
                    }
                    Toggle("Its own look", isOn: Binding(
                        get: { o.opacity != nil || o.look != nil },
                        set: { on in
                            store.settings.objects[i].opacity = on ? store.settings.opacity : nil
                            store.settings.objects[i].look = on ? store.settings.look : nil
                        }))
                    if o.opacity != nil || o.look != nil {
                        VStack(alignment: .leading) {
                            Text("Solid \(Int(((o.opacity ?? store.settings.opacity) * 100).rounded()))%")
                            Slider(value: value(i, \.opacity, store.settings.opacity), in: 0.15...1)
                        }
                        Picker("Style", selection: Binding(
                            get: { o.look ?? store.settings.look },
                            set: { store.settings.objects[i].look = $0 })) {
                            ForEach(EggLook.allCases, id: \.self) { Text($0.label).tag($0) }
                        }
                    }
                } header: { Text("This one's own") } footer: {
                    Text("Anything left as “like the rest” follows the Easter egg page.")
                }

                Section {
                    ForEach(o.variants) { v in
                        Button { store.setActive(v.id, for: id) } label: {
                            HStack(spacing: 12) {
                                EggThumb(variant: v).frame(width: 56, height: 56)
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(v.name).foregroundColor(.primary)
                                    if v.isOriginal {
                                        Label("Always kept", systemImage: "lock.fill").font(.caption).foregroundColor(.secondary)
                                    } else if v.photo != nil {
                                        Text(v.anime ? "Anime style" : "As it is").font(.caption).foregroundColor(.secondary)
                                    }
                                }
                                Spacer()
                                if o.active == v.id {
                                    Image(systemName: "checkmark.circle.fill").foregroundColor(.accentColor)
                                }
                            }
                        }
                        .swipeActions {
                            if !v.isOriginal {
                                Button(role: .destructive) { store.deleteVariant(v.id, from: id) } label: {
                                    Label("Delete", systemImage: "trash")
                                }
                            }
                            if v.photo != nil {
                                Button { editing = v } label: { Label("Edit", systemImage: "scissors") }.tint(.blue)
                            }
                        }
                    }
                    Button { adding = true } label: { Label("Add a photo…", systemImage: "photo.badge.plus") }
                } header: { Text("Pictures") } footer: {
                    Text("Tap one to make it the one that plays. Swipe a photo to edit its outline or style, or to delete it.")
                }

                if !o.builtin {
                    Section {
                        Button("Delete \(o.name)", role: .destructive) { confirmDelete = true }
                    }
                }
            }
            .navigationTitle(o.name)
            .sheet(isPresented: $adding) { EggPhotoEditor(mode: .addTo(id)) }
            .sheet(isPresented: $suggesting) {
                EggSuggestSheet(name: o.name, existing: o.keywords) { chosen in
                    let moved = chosen.compactMap { store.addKeyword($0, to: id) }
                    note = moved.isEmpty ? nil : "Moved here from \(Set(moved).sorted().joined(separator: ", ")) — a word summons one thing."
                }
            }
            .sheet(isPresented: $drawing) { EggPathDrawer(objectID: id, path: $store.settings.objects[i].drawnPath) }
            .sheet(item: $editing) { v in EggPhotoEditor(mode: .edit(id, v)) }
            .confirmationDialog("Delete \(o.name) and its photos?", isPresented: $confirmDelete, titleVisibility: .visible) {
                Button("Delete", role: .destructive) { store.deleteObject(id); dismiss() }
            }
        } else {
            Text("This one was deleted.").foregroundColor(.secondary)
        }
    }

    private func optional<T>(_ b: Binding<T?>) -> Binding<T?> { b }

    /// A slider's binding onto one of this word's optional numbers.
    private func value(_ i: Int, _ key: WritableKeyPath<EggObject, Double?>, _ fallback: Double) -> Binding<Double> {
        Binding(get: { store.settings.objects[i][keyPath: key] ?? fallback },
                set: { store.settings.objects[i][keyPath: key] = $0 })
    }

    private func secondsRow(_ title: String, _ value: Binding<Double>, _ range: ClosedRange<Double>) -> some View {
        VStack(alignment: .leading) {
            HStack { Text(title); Spacer(); Text("\(value.wrappedValue, specifier: "%.1f") s").foregroundColor(.secondary).monospacedDigit() }
            Slider(value: value, in: range, step: 0.1)
        }
    }

    private func add() {
        let w = word.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !w.isEmpty else { return }
        if let from = store.addKeyword(w, to: id) {
            note = "“\(w.lowercased())” moved here from \(from) — a word summons one thing."
        } else {
            note = nil
        }
        word = ""
    }
}

/// A small picture of a graphic, for the lists.
struct EggThumb: View {
    let variant: EggVariant
    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 10).fill(Color(egg: 0xeef1f7))
            switch variant.source {
            case .figure(let raw):
                Canvas { ctx, size in
                    guard let f = EggFigure(rawValue: raw) else { return }
                    var c = ctx
                    let k = min(size.width, size.height) / 200
                    c.scaleBy(x: k, y: k)
                    f.draw(EggPainter(ctx: c, line: 5), EggPose(t: 0.1))
                }
            case .effect(let raw):
                Image(systemName: Self.symbol(raw)).font(.title2).foregroundColor(.orange)
            case .image(let file):
                if let img = EggStore.shared.image(file) {
                    img.resizable().scaledToFit().padding(3)
                }
            }
        }
    }

    static func symbol(_ effect: String) -> String {
        switch effect {
        case "fireworks": return "sparkles"
        case "confetti": return "party.popper"
        case "rainbow": return "rainbow"
        case "lightning": return "cloud.bolt.fill"
        default: return "snowflake"
        }
    }
}

// MARK: - The photo editor

/// Pick a photo, outline the character (automatically, or by drawing round
/// it), choose anime or as-is, and save it as a picture for an object — or as
/// a new object with its own words.
struct EggPhotoEditor: View {
    enum Mode {
        case newObject
        case addTo(String)
        case edit(String, EggVariant)
    }
    let mode: Mode
    @Environment(\.dismiss) private var dismiss
    @State private var pick: PhotosPickerItem?
    @State private var photo: UIImage?
    @State private var drawn = false                 // outline by hand
    @State private var lasso: [CGPoint] = []         // 0…1 of the photo
    @State private var anime = true
    @State private var result: UIImage?
    @State private var busy = false
    @State private var failed = false
    @State private var name = ""
    @State private var words = ""
    @State private var suggesting = false
    @State private var rig: EggRig = .auto
    @State private var detected: EggRig?
    @State private var wheels: [[Double]]?
    @State private var legs: [[Double]]?
    @State private var scale: Double = 100

    var body: some View {
        NavigationView {
            Form {
                Section {
                    PhotosPicker(selection: $pick, matching: .images) {
                        Label(photo == nil ? "Choose a photo" : "Choose a different photo", systemImage: "photo")
                    }
                }
                if let photo {
                    Section {
                        Picker("Outline", selection: $drawn) {
                            Text("Automatic").tag(false)
                            Text("Draw round it").tag(true)
                        }
                        .pickerStyle(.segmented)
                        .disabled(!EggImageTools.canCutOutAutomatically)
                        if drawn {
                            LassoCanvas(photo: photo, points: $lasso)
                                .frame(height: 300)
                            HStack {
                                Text(lasso.isEmpty ? "Draw a loop round your character with a finger."
                                                   : "Lift your finger to finish the loop.")
                                    .font(.caption).foregroundColor(.secondary)
                                Spacer()
                                Button("Clear") { lasso = [] }.disabled(lasso.isEmpty)
                            }
                        }
                        Picker("Style", selection: $anime) {
                            Text("Anime").tag(true)
                            Text("Keep as is").tag(false)
                        }
                        .pickerStyle(.segmented)
                        VStack(alignment: .leading) {
                            Text("Picture size \(Int(scale))% of the word's")
                            Slider(value: $scale, in: 50...200, step: 5)
                        }
                        Picker("Moves", selection: $rig) {
                            ForEach(EggRig.allCases, id: \.self) { r in
                                Text(r == .auto ? "Automatic\(detected.map { " (\($0.label.components(separatedBy: " (").first ?? ""))" } ?? "")" : r.label).tag(r)
                            }
                        }
                    } header: { Text("Outline and style") } footer: {
                        if !EggImageTools.canCutOutAutomatically {
                            Text("Automatic outlines need iOS 17 — draw round your character instead.")
                        } else if failed && !drawn {
                            Text("Couldn't find a subject in this photo — try drawing round it.")
                        }
                    }
                    Section("Preview") {
                        ZStack {
                            Checkerboard().clipShape(RoundedRectangle(cornerRadius: 12))
                            if busy { ProgressView() }
                            else if let result { MovingPhoto(image: result, variant: previewVariant).padding(12) }
                            else { Text("Nothing to show yet").foregroundColor(.secondary) }
                        }
                        .frame(height: 220)
                    }
                }
                if case .newObject = mode {
                    Section {
                        TextField("Name (e.g. Rex)", text: $name)
                        TextField("Words, separated by commas", text: $words)
                            .textInputAutocapitalization(.never).autocorrectionDisabled()
                        Button { suggesting = true } label: { Label("Suggest words…", systemImage: "sparkles") }
                            .disabled(name.trimmingCharacters(in: .whitespaces).isEmpty)
                    } header: { Text("Name and magic words") } footer: {
                        Text("Edit the list before saving — take out any everyday word you don't want to trigger it.")
                    }
                }
            }
            .navigationTitle(title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) { Button("Save", action: save).disabled(!canSave) }
            }
            .onChange(of: pick) { item in
                Task {
                    guard let data = try? await item?.loadTransferable(type: Data.self),
                          let ui = UIImage(data: data) else { return }
                    photo = EggImageTools.normalised(ui, side: 1600)
                    lasso = []
                    detected = nil
                    await rerender()
                }
            }
            .onChange(of: drawn) { _ in Task { await rerender() } }
            .onChange(of: anime) { _ in Task { await rerender() } }
            .onChange(of: lasso) { _ in if drawn { Task { await rerender() } } }
            .onAppear(perform: load)
            .sheet(isPresented: $suggesting) {
                EggSuggestSheet(name: name.trimmingCharacters(in: .whitespaces), existing: keywordList) { chosen in
                    words = (keywordList + chosen.filter { !keywordList.contains($0) }).joined(separator: ", ")
                }
            }
        }
    }

    /// The graphic as it will play, for the preview.
    private var previewVariant: EggVariant {
        EggVariant(id: "preview", name: "", source: .image("preview"), rig: rig, detectedRig: detected, wheels: wheels, legs: legs)
    }

    private var title: String {
        switch mode {
        case .newObject: return "New magic word"
        case .addTo: return "Add a photo"
        case .edit: return "Edit photo"
        }
    }

    private var canSave: Bool {
        guard result != nil, !busy else { return false }
        if case .newObject = mode {
            return !name.trimmingCharacters(in: .whitespaces).isEmpty && !keywordList.isEmpty
        }
        return true
    }

    private var keywordList: [String] {
        words.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces).lowercased() }.filter { !$0.isEmpty }
    }

    private func load() {
        guard case .edit(_, let v) = mode, photo == nil, let file = v.photo,
              let ui = EggStore.shared.uiImage(file) else {
            if !EggImageTools.canCutOutAutomatically { drawn = true }
            return
        }
        photo = ui
        anime = v.anime
        rig = v.rig ?? .auto
        detected = v.detectedRig
        scale = v.scalePercent ?? 100
        if let l = v.lasso { lasso = l.map { CGPoint(x: $0[0], y: $0[1]) }; drawn = true }
        Task { await rerender() }
    }

    private func rerender() async {
        guard let photo else { return }
        if drawn && lasso.count < 3 { result = nil; return }
        busy = true
        let out = await EggImageTools.render(photo: photo, lasso: drawn ? lasso : nil, anime: anime)
        failed = out == nil
        result = out
        if let out {
            wheels = EggImageTools.findWheels(out)
            legs = await EggImageTools.findLegs(out)
        }
        if detected == nil { detected = await EggImageTools.guessRig(photo) }
        busy = false
    }

    private func save() {
        let store = EggStore.shared
        guard let result, let photo, let png = store.write(result) else { return }
        let keptLasso = drawn ? lasso.map { [Double($0.x), Double($0.y)] } : nil
        switch mode {
        case .edit(let id, var v):
            v.source = .image(png)
            v.lasso = keptLasso
            v.anime = anime
            v.rig = rig; v.detectedRig = detected; v.wheels = wheels; v.legs = legs; v.scalePercent = scale
            store.replaceVariant(v, in: id)
        case .addTo(let id):
            guard let jpg = store.write(photo, jpeg: true) else { return }
            let n = (store.settings.objects.first { $0.id == id }?.variants.count ?? 1)
            store.addVariant(EggVariant(id: UUID().uuidString, name: "My photo \(n)", source: .image(png),
                                        photo: jpg, lasso: keptLasso, anime: anime,
                                        rig: rig, detectedRig: detected, wheels: wheels, legs: legs,
                                        scalePercent: scale), to: id)
        case .newObject:
            guard let jpg = store.write(photo, jpeg: true) else { return }
            _ = store.addCustom(name: name.trimmingCharacters(in: .whitespaces), keywords: keywordList,
                                original: EggVariant(id: EggVariant.originalID, name: "Original photo",
                                                     source: .image(png), photo: jpg, lasso: keptLasso, anime: anime,
                                                     rig: rig, detectedRig: detected, wheels: wheels, legs: legs,
                                                     scalePercent: scale))
        }
        dismiss()
    }
}

/// A cut-out photo moving the way it will on screen (walk, roll, flap…).
private struct MovingPhoto: View {
    let image: UIImage
    let variant: EggVariant
    @State private var from = Date()
    var body: some View {
        TimelineView(.animation) { tl in
            Canvas { ctx, size in
                let side = min(size.width, size.height)
                var c = ctx
                c.translateBy(x: (size.width - side) / 2, y: (size.height - side) / 2)
                c.scaleBy(x: side / 200, y: side / 200)
                EggPuppet.draw(variant, c.resolve(Image(uiImage: image)), c, t: tl.date.timeIntervalSince(from))
            }
        }
    }
}

/// The photo, with a loop drawn over it by finger. Points are kept as
/// fractions of the photo, so the outline survives any screen size.
private struct LassoCanvas: View {
    let photo: UIImage
    @Binding var points: [CGPoint]
    @State private var live: [CGPoint] = []

    var body: some View {
        GeometryReader { geo in
            let fit = Self.fitRect(photo.size, in: geo.size)
            ZStack(alignment: .topLeading) {
                Image(uiImage: photo).resizable().scaledToFit().frame(width: geo.size.width, height: geo.size.height)
                Path { p in
                    let shown = live.isEmpty ? points : live
                    guard let first = shown.first else { return }
                    p.move(to: Self.toView(first, fit))
                    for q in shown.dropFirst() { p.addLine(to: Self.toView(q, fit)) }
                    if live.isEmpty { p.closeSubpath() }
                }
                .stroke(Color.yellow, style: StrokeStyle(lineWidth: 3, lineCap: .round, lineJoin: .round, dash: [8, 5]))
            }
            .contentShape(Rectangle())
            .gesture(DragGesture(minimumDistance: 0)
                .onChanged { g in
                    let x = (g.location.x - fit.minX) / fit.width, y = (g.location.y - fit.minY) / fit.height
                    live.append(CGPoint(x: min(max(x, 0), 1), y: min(max(y, 0), 1)))
                }
                .onEnded { _ in
                    if live.count >= 3 { points = live }
                    live = []
                })
        }
    }

    static func fitRect(_ image: CGSize, in box: CGSize) -> CGRect {
        let k = min(box.width / max(image.width, 1), box.height / max(image.height, 1))
        let w = image.width * k, h = image.height * k
        return CGRect(x: (box.width - w) / 2, y: (box.height - h) / 2, width: w, height: h)
    }

    static func toView(_ p: CGPoint, _ fit: CGRect) -> CGPoint {
        CGPoint(x: fit.minX + p.x * fit.width, y: fit.minY + p.y * fit.height)
    }
}

private struct Checkerboard: View {
    var body: some View {
        Canvas { ctx, size in
            let s: CGFloat = 12
            for r in 0..<Int(size.height / s + 1) {
                for c in 0..<Int(size.width / s + 1) where (r + c) % 2 == 0 {
                    ctx.fill(Path(CGRect(x: CGFloat(c) * s, y: CGFloat(r) * s, width: s, height: s)),
                             with: .color(Color.gray.opacity(0.15)))
                }
            }
        }
    }
}

/// Settings ▸ Easter egg ▸ Which plays for what: every event category and
/// task tag, each with the magic word (if any) that plays when a command
/// makes one.
struct EggMadeMapView: View {
    @ObservedObject private var store = EggStore.shared

    private var categories: [String] {
        let served = (Labeller.shared.categoryRules ?? DefaultRules.categoryRules)?.categories.map(\.name) ?? []
        return served.isEmpty ? Array(EggCatalog.madeMap.keys).sorted() : served
    }

    private var tags: [String] { LocalStore.shared.allTags().map(\.name) }

    private func row(_ label: String) -> some View {
        Picker(label, selection: Binding(
            get: { store.settings.madeMap[label] ?? "" },
            set: { store.settings.madeMap[label] = $0.isEmpty ? nil : $0 })) {
            Text("Nothing").tag("")
            ForEach(store.settings.objects.filter(\.enabled)) { Text($0.name).tag($0.id) }
        }
    }

    var body: some View {
        Form {
            Section("Events, by category") { ForEach(categories, id: \.self) { row($0) } }
            Section("To-dos, by tag") { ForEach(tags, id: \.self) { row($0) } }
        }
        .navigationTitle("Which plays for what")
    }
}
