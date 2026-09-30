import SwiftUI

/// The Mac's Easter-egg settings window — the phone's settings, laid out for
/// a Mac. Photos and drawn paths are made on the phone (they need a camera
/// roll and a finger); everything else is here.
struct MacSettingsView: View {
    @ObservedObject private var store = MacEggStore.shared
    @State private var previewID = "dog"
    @State private var selected: String?

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
                        ForEach(EggMotion.allCases.filter { $0 != .drawn }, id: \.self) {
                            Text($0 == .auto ? "Each one's own" : $0.label).tag($0)
                        }
                    }
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
                MacWordEditor(id: s.id).frame(width: 420, height: 560)
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

    var body: some View {
        if let i = store.settings.objects.firstIndex(where: { $0.id == id }) {
            let o = store.settings.objects[i]
            Form {
                Section(o.name) {
                    Toggle("On", isOn: $store.settings.objects[i].enabled)
                    MacPreview(objectID: id).frame(height: 150)
                    Button("Play it") { store.play([id], together: true) }
                }
                Section("Words that summon it") {
                    ForEach(o.keywords, id: \.self) { k in
                        HStack { Text(k); Spacer(); Button("Remove") { store.settings.objects[i].keywords.removeAll { $0 == k } } }
                    }
                    HStack {
                        TextField("Add a word", text: $word)
                        Button("Add") {
                            let w = word.trimmingCharacters(in: .whitespaces).lowercased()
                            guard !w.isEmpty else { return }
                            for j in store.settings.objects.indices { store.settings.objects[j].keywords.removeAll { $0 == w } }
                            store.settings.objects[i].keywords.append(w)
                            word = ""
                        }
                    }
                }
                Section("This one's own") {
                    Picker("Motion", selection: $store.settings.objects[i].motion) {
                        ForEach(EggMotion.allCases.filter { $0 != .drawn || o.drawnPath != nil }, id: \.self) { Text($0.label).tag($0) }
                    }
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
                EggRender.draw(show, ctx, size, progress: p, t: e, image: { _ in nil })
            }
        }
    }
}
