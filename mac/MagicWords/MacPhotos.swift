import AppKit
import SwiftUI
import UniformTypeIdentifiers

/// Photos and drawn paths on the Mac (TASKS 46). They used to be made on the
/// phone only — "they need a camera roll and a finger" — but a photo is a file
/// and a path is a drag, and the pipeline that turns one into a moving cut-out
/// is `EggImageCore`, the same code the phone runs.

/// Add a photo to a magic word, or start a new magic word from one.
struct MacPhotoSheet: View {
    enum Mode { case addTo(String), newObject }
    let mode: Mode
    @ObservedObject private var store = MacEggStore.shared
    @Environment(\.dismiss) private var dismiss

    @State private var photo: CGImage?
    @State private var result: CGImage?
    @State private var anime = false
    @State private var byHand = false
    @State private var lasso: [CGPoint] = []
    @State private var busy = false
    @State private var failed = false
    @State private var detected: EggRig?
    @State private var rig: EggRig = .auto
    @State private var wheels: [[Double]] = []
    @State private var legs: [[Double]]?
    @State private var name = ""
    @State private var words = ""
    @State private var taken: [String] = []

    private var keywordList: [String] {
        words.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces).lowercased() }.filter { !$0.isEmpty }
    }

    private var variant: EggVariant {
        EggVariant(id: "preview", name: "", source: .image(""), anime: anime,
                   rig: rig, detectedRig: detected, wheels: wheels, legs: legs)
    }

    var body: some View {
        Form {
            Section {
                if photo == nil {
                    Button("Choose a photo…", action: choose)
                    Text("A photo of your dog, your car, yourself — cut out on this Mac and brought to life. Nothing leaves it.")
                        .font(.callout).foregroundColor(.secondary)
                } else {
                    HStack(alignment: .top, spacing: 12) {
                        if byHand, let photo {
                            MacLassoCanvas(photo: photo, points: $lasso) { Task { await rerender() } }
                                .frame(width: 260, height: 260)
                        }
                        ZStack {
                            RoundedRectangle(cornerRadius: 12).fill(Color(egg: 0x3b4663))
                            if busy { ProgressView() }
                            else if let result { MacMovingPhoto(image: result, variant: variant) }
                            else if failed {
                                Text(byHand ? "Draw a loop round it." : "No subject found — draw round it instead.")
                                    .foregroundColor(.white.opacity(0.8)).padding()
                            }
                        }
                        .frame(width: 260, height: 260)
                    }
                    Picker("Cut out", selection: $byHand) {
                        Text("Automatically").tag(false)
                        Text("By a loop I draw").tag(true)
                    }
                    .pickerStyle(.segmented)
                    .onChange(of: byHand) { _ in Task { await rerender() } }
                    Toggle("Anime look", isOn: $anime).onChange(of: anime) { _ in Task { await rerender() } }
                    Picker("Moves", selection: $rig) {
                        ForEach(EggRig.allCases, id: \.self) { r in
                            Text(r == .auto ? "Automatically\(detected.map { " (\($0.rawValue))" } ?? "")" : r.rawValue.capitalized).tag(r)
                        }
                    }
                    Button("A different photo…", action: choose)
                }
            }
            if case .newObject = mode {
                Section("The new magic word") {
                    TextField("Name", text: $name)
                    TextField("Words that summon it, separated by commas", text: $words)
                }
            }
            HStack {
                Button("Cancel") { dismiss() }
                Spacer()
                Button("Save", action: save).keyboardShortcut(.defaultAction).disabled(!canSave)
            }
        }
        .formStyle(.grouped)
        .frame(minWidth: 600, minHeight: 520)
        .alert("Some words are taken", isPresented: Binding(get: { !taken.isEmpty }, set: { if !$0 { taken = [] } })) {
            Button("Move them here") { finish(moving: true) }
            Button("Keep them where they are", role: .cancel) { finish(moving: false) }
        } message: {
            Text(taken.map { "“\($0)”" }.joined(separator: ", ") + " already summon something else. A word can only summon one thing.")
        }
    }

    private var canSave: Bool {
        guard result != nil, !busy else { return false }
        if case .newObject = mode {
            return !name.trimmingCharacters(in: .whitespaces).isEmpty && !keywordList.isEmpty
        }
        return true
    }

    private func choose() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.image]
        panel.allowsMultipleSelection = false
        guard panel.runModal() == .OK, let url = panel.url, let cg = MacEggStore.loadUpright(url) else { return }
        photo = EggImageCore.normalised(cg)
        lasso = []; detected = nil; rig = .auto
        Task { await rerender() }
    }

    private func rerender() async {
        guard let photo else { return }
        if byHand && lasso.count < 3 { result = nil; failed = true; return }
        busy = true
        let out = await EggImageCore.render(photo: photo, lasso: byHand ? lasso : nil, anime: anime)
        failed = out == nil
        result = out
        if let out {
            wheels = EggPuppet.findWheels(out)
            legs = await EggImageCore.findLegs(out)
        }
        if detected == nil { detected = await EggImageCore.guessRig(photo) }
        busy = false
    }

    private func save() {
        if case .newObject = mode {
            let clash = keywordList.filter { store.owner(of: $0, besides: "") != nil }
            if !clash.isEmpty { taken = clash; return }
        }
        finish(moving: true)
    }

    private func finish(moving: Bool) {
        guard let result, let photo, let png = store.write(result), let jpg = store.write(photo, jpeg: true) else { return }
        let kept = byHand ? lasso.map { [Double($0.x), Double($0.y)] } : nil
        switch mode {
        case .addTo(let id):
            let n = store.settings.objects.first { $0.id == id }?.variants.count ?? 1
            store.addVariant(EggVariant(id: UUID().uuidString, name: "My photo \(n)", source: .image(png),
                                        photo: jpg, lasso: kept, anime: anime, rig: rig, detectedRig: detected,
                                        wheels: wheels, legs: legs), to: id)
        case .newObject:
            let words = moving ? keywordList : keywordList.filter { !taken.contains($0) }
            store.addCustom(name: name.trimmingCharacters(in: .whitespaces), keywords: words,
                            original: EggVariant(id: EggVariant.originalID, name: "Original photo", source: .image(png),
                                                 photo: jpg, lasso: kept, anime: anime, rig: rig, detectedRig: detected,
                                                 wheels: wheels, legs: legs))
        }
        taken = []
        dismiss()
    }
}

/// The cut-out moving the way it will on screen (walk, roll, flap…).
struct MacMovingPhoto: View {
    let image: CGImage
    let variant: EggVariant
    @State private var from = Date()
    var body: some View {
        TimelineView(.animation) { tl in
            Canvas { ctx, size in
                let side = min(size.width, size.height)
                var c = ctx
                c.translateBy(x: (size.width - side) / 2, y: (size.height - side) / 2)
                c.scaleBy(x: side / 200, y: side / 200)
                EggPuppet.draw(variant, c.resolve(Image(decorative: image, scale: 1)), c,
                               t: tl.date.timeIntervalSince(from))
            }
        }
    }
}

/// The photo with a loop drawn over it by mouse. Points are kept as fractions
/// of the photo (from its top-left), as the phone keeps them.
struct MacLassoCanvas: View {
    let photo: CGImage
    @Binding var points: [CGPoint]
    var done: () -> Void
    @State private var live: [CGPoint] = []

    var body: some View {
        GeometryReader { geo in
            let fit = Self.fit(CGSize(width: photo.width, height: photo.height), in: geo.size)
            ZStack(alignment: .topLeading) {
                Image(decorative: photo, scale: 1).resizable().frame(width: fit.width, height: fit.height)
                    .offset(x: fit.minX, y: fit.minY)
                Path { p in
                    let shown = live.isEmpty ? points.map { CGPoint(x: fit.minX + $0.x * fit.width, y: fit.minY + $0.y * fit.height) } : live
                    guard let first = shown.first else { return }
                    p.move(to: first)
                    for q in shown.dropFirst() { p.addLine(to: q) }
                    if live.isEmpty { p.closeSubpath() }
                }
                .stroke(Color.white, style: StrokeStyle(lineWidth: 2, lineCap: .round, lineJoin: .round, dash: [6, 4]))
            }
            .contentShape(Rectangle())
            .gesture(DragGesture(minimumDistance: 0)
                .onChanged { g in
                    if let last = live.last, hypot(last.x - g.location.x, last.y - g.location.y) < 2 { return }
                    live.append(g.location)
                }
                .onEnded { _ in
                    points = live.map { CGPoint(x: min(max(($0.x - fit.minX) / fit.width, 0), 1),
                                                y: min(max(($0.y - fit.minY) / fit.height, 0), 1)) }
                    live = []
                    done()
                })
        }
        .background(RoundedRectangle(cornerRadius: 12).fill(Color.black.opacity(0.25)))
    }

    static func fit(_ image: CGSize, in box: CGSize) -> CGRect {
        let k = min(box.width / max(image.width, 1), box.height / max(image.height, 1))
        let w = image.width * k, h = image.height * k
        return CGRect(x: (box.width - w) / 2, y: (box.height - h) / 2, width: w, height: h)
    }
}

/// "The path I drew", by mouse: trace the route on a small copy of this
/// screen and the graphic replays along it at the pace it was drawn.
struct MacPathDrawer: View {
    let objectID: String?
    @Binding var path: [[Double]]?
    @ObservedObject private var store = MacEggStore.shared
    @Environment(\.dismiss) private var dismiss
    @State private var live: [(CGPoint, TimeInterval)] = []
    @State private var draft: [[Double]]?
    @State private var shownFrom = Date()

    private var object: EggObject? {
        store.settings.objects.first { $0.id == (objectID ?? "dog") } ?? store.settings.objects.first
    }

    private var aspect: CGFloat {
        let f = NSScreen.main?.frame.size ?? CGSize(width: 16, height: 10)
        return f.width / max(f.height, 1)
    }

    var body: some View {
        VStack(spacing: 12) {
            Text(draft == nil ? "Drag the route with the mouse. Slow down or stop and it will too."
                              : "Playing your route. Drag again to replace it.")
                .foregroundColor(.secondary)
            GeometryReader { geo in
                let size = geo.size
                TimelineView(.animation) { tl in
                    Canvas { ctx, sz in
                        ctx.fill(Path(roundedRect: CGRect(origin: .zero, size: sz), cornerRadius: 12),
                                 with: .color(Color(egg: 0x3b4663)))
                        let shown = live.isEmpty ? (draft ?? []).map { CGPoint(x: $0[0] * sz.width, y: $0[1] * sz.height) }
                                                 : live.map(\.0)
                        if shown.count > 1 {
                            var line = Path()
                            line.addLines(shown)
                            ctx.stroke(line, with: .color(.white.opacity(0.45)),
                                       style: StrokeStyle(lineWidth: 3, lineCap: .round, lineJoin: .round, dash: [7, 6]))
                        }
                        if live.isEmpty, let draft, let o = object {
                            let secs = store.settings.seconds
                            let el = tl.date.timeIntervalSince(shownFrom).truncatingRemainder(dividingBy: secs + 0.6)
                            let show = EggShow(objectID: o.id, variant: o.activeVariant, motion: .drawn,
                                               start: shownFrom, seconds: secs, slot: 0, count: 1, delay: 0,
                                               trail: o.trail != .auto ? o.trail : EggCatalog.defaultTrail(o.id),
                                               mirrored: false, path: draft)
                            EggRender.draw(show, ctx, sz, progress: el / secs, t: el, image: { store.image($0) })
                        }
                    }
                }
                .clipShape(RoundedRectangle(cornerRadius: 12))
                .gesture(DragGesture(minimumDistance: 0)
                    .onChanged { g in
                        let now = Date().timeIntervalSinceReferenceDate
                        let pt = CGPoint(x: min(max(g.location.x, 0), size.width), y: min(max(g.location.y, 0), size.height))
                        if let last = live.last, hypot(last.0.x - pt.x, last.0.y - pt.y) < 2 { return }
                        live.append((pt, now))
                    }
                    .onEnded { _ in
                        draft = EggDrawnPath.normalise(live, in: size)
                        live = []
                        shownFrom = Date()
                    })
            }
            .aspectRatio(aspect, contentMode: .fit)
            HStack {
                Button("Clear") { draft = nil; live = [] }.disabled(draft == nil)
                Spacer()
                Button("Cancel") { dismiss() }
                Button("Save") { path = draft; dismiss() }.keyboardShortcut(.defaultAction).disabled(draft == nil)
            }
        }
        .padding()
        .frame(minWidth: 640, minHeight: 470)
        .onAppear { draft = path; shownFrom = Date() }
    }
}
