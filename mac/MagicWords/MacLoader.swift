import AppKit
import CryptoKit
import SwiftUI

// The loading screen on the Mac (TASKS 48) — the phone's, drawn by the same
// `EggLoaderRender`, with the Mac's own settings (an animation plays on the
// device the wait is on):
//
//     a long wait   the calendar app tells the helper when a command starts and
//                   ends (`wait_begin` / `wait_end`); one that runs past the
//                   loader's `stuckAfter` takes the middle of the screen, as on
//                   the phone — click-through, it tells and never blocks.
//     the HUD       a separate process the helper cannot talk to, so the loader
//                   is also written as a short loop of frames beside the
//                   settings (`loader/<hash>/`, `loader/current.json`) and the
//                   thinking card's "working…" plays them.

/// The loader, animated, in a square of `side` points.
struct MacLoaderView: View {
    var side: CGFloat = 36
    var config: EggLoaderConfig? = nil
    var caption: String? = nil
    @ObservedObject private var store = MacEggStore.shared
    @State private var from = Date()

    var body: some View {
        let cfg = config ?? store.settings.loader
        VStack(spacing: 8) {
            TimelineView(.animation) { tl in
                Canvas { ctx, size in
                    EggLoaderRender.draw(cfg, MacLoader.objects(cfg, store.settings), ctx, size,
                                         t: tl.date.timeIntervalSince(from), image: { store.image($0) })
                }
            }
            .frame(width: side, height: side)
            if let caption, !caption.isEmpty {
                Text(caption).font(.system(size: max(11, side * 0.11), weight: .semibold, design: .rounded))
                    .foregroundColor(.secondary)
            }
        }
    }
}

@MainActor
final class MacLoader {
    static let shared = MacLoader()
    private var waits: [String: Date] = [:]
    private var demoUntil: Date?
    private var panel: NSPanel?
    private var timer: Timer?

    static func objects(_ cfg: EggLoaderConfig, _ s: EggSettings) -> [EggObject] {
        cfg.objects.compactMap { id in s.objects.first { $0.id == id } }
    }

    func begin(_ id: String) { waits[id] = Date(); tick() }
    func end(_ id: String) { waits[id] = nil; tick() }
    func demo() { demoUntil = Date().addingTimeInterval(4); tick() }

    /// Show or hide the big loader; polls while anything is waiting.
    private func tick() {
        let cfg = MacEggStore.shared.settings.loader
        let now = Date()
        let oldest = waits.values.min()
        let stuck = cfg.enabled && cfg.stuckAfter > 0 && !cfg.objects.isEmpty
            && (oldest.map { now.timeIntervalSince($0) >= cfg.stuckAfter } ?? false)
        let demo = (demoUntil ?? .distantPast) > now
        if stuck || demo { show(cfg) } else { panel?.orderOut(nil) }
        timer?.invalidate()
        timer = nil
        if !waits.isEmpty || demo {
            timer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: false) { _ in
                MainActor.assumeIsolated { MacLoader.shared.tick() }
            }
        }
    }

    private func show(_ cfg: EggLoaderConfig) {
        if panel == nil {
            let p = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 260, height: 270),
                            styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
            p.isOpaque = false
            p.backgroundColor = .clear
            p.hasShadow = true
            p.level = .statusBar
            p.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]
            p.ignoresMouseEvents = true                 // it tells, it never blocks
            p.contentView = NSHostingView(rootView: MacStuckView())
            panel = p
        }
        if let screen = NSScreen.main?.visibleFrame, let p = panel {
            p.setFrameOrigin(NSPoint(x: screen.midX - p.frame.width / 2, y: screen.midY - p.frame.height / 2))
        }
        panel?.orderFrontRegardless()
    }

    // MARK: - Frames for the HUD

    private var pendingFrames: DispatchWorkItem?

    /// After a settings change: re-render once the user stops fiddling.
    func framesSoon() {
        pendingFrames?.cancel()
        let w = DispatchWorkItem { MainActor.assumeIsolated { MacLoader.shared.writeFrames() } }
        pendingFrames = w
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5, execute: w)
    }

    /// Writes the loader as a loop of PNG frames, once per distinct look:
    /// `loader/<hash>/000.png…`, and `loader/current.json` naming the folder
    /// ({"dir", "frames", "fps", "enabled"}). Cheap when nothing changed.
    func writeFrames(side: CGFloat = 44, seconds: Double = 4, fps: Double = 15) {
        let s = MacEggStore.shared.settings
        let cfg = s.loader
        let root = MacEggStore.shared.file.deletingLastPathComponent().appendingPathComponent("loader", isDirectory: true)
        let objects = Self.objects(cfg, s)
        let enabled = cfg.enabled && !objects.isEmpty
        let key = (try? JSONEncoder().encode(cfg)).map { Data($0) + Data(objects.map(\.activeVariant.id).joined().utf8) } ?? Data()
        let hash = SHA256.hash(data: key).prefix(6).map { String(format: "%02x", $0) }.joined()
        let dir = root.appendingPathComponent(hash, isDirectory: true)
        let n = Int(seconds * fps)
        let fm = FileManager.default
        if enabled && !fm.fileExists(atPath: dir.appendingPathComponent(String(format: "%03d.png", n - 1)).path) {
            try? fm.createDirectory(at: dir, withIntermediateDirectories: true)
            for i in 0..<n {
                let t = Double(i) / fps
                let view = Canvas { ctx, size in
                    EggLoaderRender.draw(cfg, objects, ctx, size, t: t, image: { MacEggStore.shared.image($0) })
                }
                .frame(width: side, height: side)
                let r = ImageRenderer(content: view)
                r.scale = 2
                guard let cg = r.cgImage,
                      let png = NSBitmapImageRep(cgImage: cg).representation(using: .png, properties: [:]) else { continue }
                try? png.write(to: dir.appendingPathComponent(String(format: "%03d.png", i)))
            }
        }
        let current: [String: Any] = ["dir": dir.path, "frames": n, "fps": fps, "enabled": enabled,
                                      "caption": cfg.showCaption ? cfg.stuckCaption : ""]
        if let data = try? JSONSerialization.data(withJSONObject: current) {
            try? data.write(to: root.appendingPathComponent("current.json"), options: .atomic)
        }
        // Old looks are dropped, so the folder holds one.
        for old in (try? fm.contentsOfDirectory(at: root, includingPropertiesForKeys: nil)) ?? []
        where old.hasDirectoryPath && old.lastPathComponent != hash {
            try? fm.removeItem(at: old)
        }
    }
}

/// The "taking a while" card.
private struct MacStuckView: View {
    @ObservedObject private var store = MacEggStore.shared
    var body: some View {
        let cfg = store.settings.loader
        MacLoaderView(side: 170, caption: cfg.showCaption ? cfg.stuckCaption : nil)
            .padding(26)
            .background(RoundedRectangle(cornerRadius: 28).fill(.ultraThinMaterial))
            .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

/// Settings ▸ Loading screen, as on the phone.
struct MacLoaderSettings: View {
    @ObservedObject private var store = MacEggStore.shared
    private var cfg: Binding<EggLoaderConfig> { $store.settings.loader }

    var body: some View {
        Section {
            MacLoaderView(side: 150, caption: cfg.wrappedValue.showCaption ? cfg.wrappedValue.stuckCaption : nil)
                .frame(maxWidth: .infinity)
            Toggle("Use my loading screen", isOn: cfg.enabled)
            Button("Show the “taking a while” screen") { MacLoader.shared.demo() }
            Picker("Style", selection: cfg.style) {
                ForEach(EggLoaderStyle.allCases, id: \.self) { Text($0.label).tag($0) }
            }
            ForEach(store.settings.objects.filter(\.enabled)) { o in
                Toggle(isOn: Binding(get: { cfg.wrappedValue.objects.contains(o.id) },
                                     set: { on in toggle(o.id, on) })) {
                    HStack {
                        Text(o.name)
                        if let i = cfg.wrappedValue.objects.firstIndex(of: o.id) {
                            Text("\(i + 1)").font(.caption.weight(.bold)).foregroundColor(.secondary)
                        }
                    }
                }
            }
            Picker("Trail", selection: cfg.trail) {
                ForEach(EggTrail.allCases.filter { $0 != .auto }, id: \.self) { Text($0.label).tag($0) }
            }
            HStack {
                Text("Speed")
                Slider(value: cfg.speed, in: 0.3...2, step: 0.1)
                Text(String(format: "%.1f×", cfg.wrappedValue.speed)).monospacedDigit().frame(width: 40)
            }
            Toggle("Ring", isOn: cfg.showRing)
            if cfg.wrappedValue.showRing {
                ColorPicker("Ring colour", selection: Binding(
                    get: { Color(eggHex: cfg.wrappedValue.ringHex) },
                    set: { cfg.wrappedValue.ringHex = Self.hex($0) }), supportsOpacity: false)
            }
            HStack {
                Text(cfg.wrappedValue.stuckAfter == 0 ? "Never take the middle of the screen"
                     : "Take the middle of the screen after \(Int(cfg.wrappedValue.stuckAfter)) s")
                Slider(value: cfg.stuckAfter, in: 0...10, step: 1)
            }
            Toggle("With a line", isOn: cfg.showCaption)
            if cfg.wrappedValue.showCaption {
                TextField("Line", text: cfg.stuckCaption)
            }
        } header: { Text("Loading screen") } footer: {
            Text("Plays while a command thinks — in the thinking card, and in the middle of the screen when it "
                 + "takes a while (it never blocks a click). Up to four in it; the wheel and the parade use them all.")
        }
    }

    private func toggle(_ id: String, _ on: Bool) {
        var list = cfg.wrappedValue.objects
        list.removeAll { $0 == id }
        if on && list.count < 4 { list.append(id) }
        cfg.wrappedValue.objects = list
    }

    static func hex(_ c: Color) -> String {
        let n = NSColor(c).usingColorSpace(.sRGB) ?? .orange
        return String(format: "#%02X%02X%02X", Int(n.redComponent * 255), Int(n.greenComponent * 255), Int(n.blueComponent * 255))
    }
}
