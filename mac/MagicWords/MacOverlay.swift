import AppKit
import SwiftUI

/// The Mac's overlay: one borderless, transparent panel over the whole main
/// screen, above full-screen apps and every Space, shown only while a show
/// plays. Clicks go straight through unless Settings says a click is for
/// the animation. (The phone's EggOverlay is a UIWindow; same name, same job.)
@MainActor
final class EggOverlay {
    static let shared = EggOverlay()
    private var panel: NSPanel?

    func show(passThrough: Bool = true) {
        let frame = NSScreen.main?.frame ?? NSRect(x: 0, y: 0, width: 1440, height: 900)
        if panel == nil {
            let p = NSPanel(contentRect: frame, styleMask: [.borderless, .nonactivatingPanel],
                            backing: .buffered, defer: false)
            p.isOpaque = false
            p.backgroundColor = .clear
            p.hasShadow = false
            p.level = .screenSaver
            p.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]
            p.contentView = NSHostingView(rootView: EggStageView(
                stage: EggStage.shared,
                settings: { MacEggStore.shared.settings },
                image: { MacEggStore.shared.image($0) }))
            panel = p
        }
        panel?.setFrame(frame, display: true)
        panel?.ignoresMouseEvents = passThrough
        panel?.orderFrontRegardless()
    }

    func hide() {
        panel?.orderOut(nil)
    }
}
