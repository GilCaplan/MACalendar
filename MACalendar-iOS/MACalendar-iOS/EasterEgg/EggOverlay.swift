import SwiftUI
import UIKit

/// A window of its own above everything — the app, its sheets, the thinking
/// panel — so a dragon can fly over whatever is open. Hidden (and so touch-
/// transparent) whenever nothing is playing; while something is, a tap
/// anywhere is the tap the settings describe.
@MainActor
final class EggOverlay {
    static let shared = EggOverlay()
    private var window: UIWindow?

    /// `passThrough`: the window takes no touches at all — the app under
    /// it works as if nothing were playing.
    func show(passThrough: Bool = false) {
        if window == nil {
            guard let scene = UIApplication.shared.connectedScenes
                .compactMap({ $0 as? UIWindowScene })
                .first(where: { $0.activationState == .foregroundActive })
                ?? UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).first
            else { return }
            let w = UIWindow(windowScene: scene)
            w.windowLevel = .alert + 1
            w.backgroundColor = .clear
            let host = UIHostingController(rootView: EggStageView(
                stage: EggStage.shared,
                settings: { EggStore.shared.settings },
                image: { EggStore.shared.image($0) }))
            host.view.backgroundColor = .clear
            w.rootViewController = host
            window = w
        }
        window?.isUserInteractionEnabled = !passThrough
        window?.isHidden = false
    }

    func hide() {
        window?.isHidden = true
    }
}
