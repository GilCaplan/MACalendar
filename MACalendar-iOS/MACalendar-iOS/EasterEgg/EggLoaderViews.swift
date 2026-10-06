import SwiftUI
import UIKit
import Combine

// The loader's views on the phone (the drawing is EggLoader.swift, shared).

/// The loader, animated, in a square of `side` points.
struct EggLoaderView: View {
    var side: CGFloat = 36
    var config: EggLoaderConfig? = nil
    var caption: String? = nil
    @ObservedObject private var store = EggStore.shared
    @State private var from = Date()

    var body: some View {
        let cfg = config ?? store.settings.loader
        let objects = cfg.objects.compactMap { id in store.settings.objects.first { $0.id == id } }
        VStack(spacing: 8) {
            TimelineView(.animation) { tl in
                Canvas { ctx, size in
                    EggLoaderRender.draw(cfg, objects, ctx, size, t: tl.date.timeIntervalSince(from),
                                         image: { store.image($0) })
                }
            }
            .frame(width: side, height: side)
            if let caption, !caption.isEmpty {
                Text(caption).font(.system(size: max(11, side * 0.11), weight: .semibold, design: .rounded))
                    .foregroundColor(.secondary)
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(caption ?? "Loading")
    }
}

/// A drop-in for `ProgressView()`: the user's loader when it is on, the
/// system spinner otherwise.
struct EggSpinner: View {
    var side: CGFloat = 28
    @ObservedObject private var store = EggStore.shared

    var body: some View {
        if store.settings.loader.enabled && !store.settings.loader.objects.isEmpty {
            EggLoaderView(side: side)
        } else {
            ProgressView()
        }
    }
}

// MARK: - "Stuck": a long wait takes the middle of the screen

/// Every wait the app is in, and since when. A wait longer than the loader's
/// `stuckAfter` shows the big loader over the app until it ends.
@MainActor
final class EggWaits: ObservableObject {
    static let shared = EggWaits()
    @Published private(set) var active: [UUID: Date] = [:]
    /// A demo from Settings: show the stuck screen for a few seconds.
    @Published var demoUntil: Date?
    /// The thinking panel is open. It shows its own "Working…", so the stuck
    /// screen stays down whatever is waiting (Gil, 2026-10-06, "remove this
    /// wheel when it's thinking"). Keyed here, not per wait: the wait that
    /// showed over the panel was the CALENDAR's reload, slow because the Mac
    /// was busy with the very command the panel was showing.
    @Published var panelOpen = false

    @discardableResult
    func begin() -> UUID {
        let id = UUID()
        active[id] = Date()
        return id
    }

    func end(_ id: UUID?) {
        guard let id else { return }
        active[id] = nil
    }

    var oldest: Date? { active.values.min() }
}

/// Sits over the whole app (ContentView); invisible until a wait runs long.
struct EggWaitOverlay: View {
    @ObservedObject private var waits = EggWaits.shared
    @ObservedObject private var store = EggStore.shared

    var body: some View {
        TimelineView(.periodic(from: .now, by: 0.5)) { tl in
            let cfg = store.settings.loader
            let demo = (waits.demoUntil ?? .distantPast) > tl.date
            let stuck = cfg.enabled && cfg.stuckAfter > 0 && !cfg.objects.isEmpty
                && !waits.panelOpen
                && (waits.oldest.map { tl.date.timeIntervalSince($0) >= cfg.stuckAfter } ?? false)
            if stuck || demo {
                ZStack {
                    Color.black.opacity(0.25).ignoresSafeArea()
                    EggLoaderView(side: 170, caption: cfg.showCaption ? cfg.stuckCaption : nil)
                        .padding(26)
                        .background(RoundedRectangle(cornerRadius: 28).fill(.ultraThinMaterial))
                }
                .transition(.opacity)
                .allowsHitTesting(false)            // it tells, it never blocks
            }
        }
        .animation(.easeInOut(duration: 0.25), value: waits.active.count)
    }
}

/// The window the "taking a while" screen lives in: above the app and every
/// sheet (Settings, the thinking panel are sheets), never taking a touch, and
/// shown only while something is waiting.
@MainActor
final class EggWaitWindow {
    static let shared = EggWaitWindow()
    private var window: UIWindow?
    private var watch: AnyCancellable?

    func install() {
        guard watch == nil else { return }
        watch = EggWaits.shared.$active.combineLatest(EggWaits.shared.$demoUntil)
            .receive(on: RunLoop.main)
            .sink { [weak self] active, demo in
                let need = !active.isEmpty || (demo ?? .distantPast) > Date()
                self?.show(need)
                if let demo, demo > Date() {      // hide again once the demo is over
                    DispatchQueue.main.asyncAfter(deadline: .now() + demo.timeIntervalSinceNow + 0.3) {
                        if EggWaits.shared.active.isEmpty { self?.show(false) }
                    }
                }
            }
    }

    private func show(_ on: Bool) {
        if on && window == nil {
            guard let scene = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene })
                .first(where: { $0.activationState == .foregroundActive })
                ?? UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).first else { return }
            let w = UIWindow(windowScene: scene)
            w.windowLevel = .alert + 2
            w.backgroundColor = .clear
            w.isUserInteractionEnabled = false         // it tells, it never blocks
            let host = UIHostingController(rootView: EggWaitOverlay())
            host.view.backgroundColor = .clear
            w.rootViewController = host
            window = w
        }
        window?.isHidden = !on
    }
}
