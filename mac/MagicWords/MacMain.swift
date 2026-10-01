import AppKit
import SwiftUI

/// MACalendar Magic — the Mac's Easter egg. Started by the calendar app,
/// which talks to it over stdin/stdout, one JSON object per line:
///
///     {"op":"heard","text":"…","bare":true}  → {"bare":true|false, "played":…}
///     {"op":"heard_late","text":"…"}      → {"played":…} — the brain's own
///                         corrected words, when the raw ones played nothing
///     {"op":"settings"}   opens the settings window
///     {"op":"demo"}       plays a demo
///     {"op":"festival"}   greets a festival day (once a day)
///     {"op":"wait_begin","id":"…"} / {"op":"wait_end","id":"…"}
///                         a command in flight; one that runs long shows the
///                         loading screen in the middle of the screen
///     {"op":"loader_demo"} shows the "taking a while" screen for 4 s
///     {"op":"made","labels":["Travel","Groceries"]} — what a command just
///                         made, when "Also for what gets made" is on
///     {"op":"quit"}
///
/// argv[1]: the folder its settings live in (this user's data folder).
@main
struct MacMagic {
    static func main() {
        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)          // no Dock icon, no menu bar
        let delegate = MagicDelegate()
        app.delegate = delegate
        app.run()
    }
}

@MainActor
final class MagicDelegate: NSObject, NSApplicationDelegate {
    private var settingsWindow: NSWindow?

    func applicationDidFinishLaunching(_ notification: Notification) {
        _ = MacEggStore.shared
        MacLoader.shared.writeFrames()               // the HUD's "working…" loop
        Thread.detachNewThread { [weak self] in
            while let line = readLine() {
                guard let data = line.data(using: .utf8),
                      let msg = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                      let op = msg["op"] as? String else { continue }
                let semaphore = DispatchSemaphore(value: 0)
                var reply: [String: Any]?
                DispatchQueue.main.async {
                    MainActor.assumeIsolated { reply = self?.handle(op, msg) }
                    semaphore.signal()
                }
                semaphore.wait()
                if let reply, let out = try? JSONSerialization.data(withJSONObject: reply),
                   let s = String(data: out, encoding: .utf8) {
                    print(s); fflush(stdout)
                }
            }
            DispatchQueue.main.async { NSApp.terminate(nil) }     // the calendar app went away
        }
    }

    private func handle(_ op: String, _ msg: [String: Any]) -> [String: Any]? {
        switch op {
        case "heard":
            let r = MacEggStore.shared.heard(msg["text"] as? String ?? "", bare: msg["bare"] as? Bool ?? false)
            return ["bare": r.bare, "played": r.played]
        case "heard_late":
            return ["played": MacEggStore.shared.heardLate(msg["text"] as? String ?? "")]
        case "settings": showSettings(); return ["ok": true]
        case "demo": MacEggStore.shared.demo(); return ["ok": true]
        case "festival": MacEggStore.shared.festivalTick(); return ["ok": true]
        case "wait_begin": MacLoader.shared.begin(msg["id"] as? String ?? ""); return nil
        case "wait_end": MacLoader.shared.end(msg["id"] as? String ?? ""); return nil
        case "loader_demo": MacLoader.shared.demo(); return ["ok": true]
        case "made": MacEggStore.shared.made(msg["labels"] as? [String] ?? []); return nil
        case "quit": NSApp.terminate(nil); return nil
        default: return ["error": "unknown op"]
        }
    }

    private func showSettings() {
        if settingsWindow == nil {
            let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 560, height: 720),
                             styleMask: [.titled, .closable, .resizable, .miniaturizable], backing: .buffered, defer: false)
            w.title = "Magic words"
            w.contentView = NSHostingView(rootView: MacSettingsView())
            w.isReleasedWhenClosed = false
            w.center()
            settingsWindow = w
        }
        NSApp.activate(ignoringOtherApps: true)
        settingsWindow?.makeKeyAndOrderFront(nil)
    }
}
