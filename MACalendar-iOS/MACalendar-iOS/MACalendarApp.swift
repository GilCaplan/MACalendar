import SwiftUI
import UserNotifications

@main
struct MACalendarApp: App {
    @StateObject private var settings = AppSettings()
    @StateObject private var api: APIClient

    init() {
        let s = AppSettings()
        _settings = StateObject(wrappedValue: s)
        _api = StateObject(wrappedValue: APIClient(settings: s))
        // Must be set before launch finishes so a tap on a reminder that
        // cold-starts the app still reaches didReceive. The router presents
        // foreground banners and routes "evt-*" taps to the calendar.
        UNUserNotificationCenter.current().delegate = NotificationRouter.shared
        // Also before launch finishes: BGTaskScheduler traps if a task is
        // registered any later. This is what brings the lock-screen agenda card
        // back at 06:00 after it has been cleared.
        LiveActivityManager.registerBackgroundRefresh()
        LiveActivityManager.scheduleBackgroundRefresh()
        // A to-do ticked on the lock-screen card (`UpNextCompleteTodoIntent`,
        // run in THIS process). Marked done the Tasks tab's way — optimistic
        // locally, queued if the Mac is away — then the card re-syncs. Only a
        // still-open to-do is toggled, so a double tap cannot reopen it.
        if #available(iOS 16.1, *) {
            // Set synchronously: when iOS launches the app only to run the
            // tick, `perform` follows this init, and a hook set from a Task
            // could still be nil when it looks.
            let client = APIClient(settings: s)
            UpNextHooks.completeTodo = { id in
                let open = LocalStore.shared.allTodos(list: nil, includeCompleted: false)
                    .contains { $0.id == id }
                if open { _ = try? await client.toggleTodo(id: id) }
                await MainActor.run { LiveActivityManager.shared.sync() }
            }
        }
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(settings)
                .environmentObject(api)
                .preferredColorScheme(settings.theme == "dark" ? .dark : .light)
                .tint(settings.accentColor)
                .onOpenURL { url in
                    // A tap on the lock-screen card: macalendar://open/tasks
                    // or macalendar://open/calendar?event=<id>.
                    if url.scheme == "macalendar" {
                        Self.route(url)
                        return
                    }
                    // A .txt shared from WhatsApp ("Export Chat" → MACalendar) lands here.
                    let accessed = url.startAccessingSecurityScopedResource()
                    defer { if accessed { url.stopAccessingSecurityScopedResource() } }
                    guard let data = try? Data(contentsOf: url) else { return }
                    let text = String(data: data, encoding: .utf8) ?? String(data: data, encoding: .isoLatin1) ?? ""
                    guard !text.isEmpty else { return }
                    ImportInbox.shared.pendingName = url.lastPathComponent
                    ImportInbox.shared.pendingText = text
                    try? FileManager.default.removeItem(at: url)   // don't keep the chat around
                }
        }
    }

    /// Open the tab a card tap asked for. An event goes through the same
    /// seam a tapped reminder uses (`NotificationRouter.pendingEventId`), so
    /// the calendar lands on that event's day.
    static func route(_ url: URL) {
        let parts = URLComponents(url: url, resolvingAgainstBaseURL: false)
        switch url.path {
        case "/tasks":
            FeatureRouter.shared.show("tasks")
        default:
            if let raw = parts?.queryItems?.first(where: { $0.name == "event" })?.value,
               let id = Int(raw) {
                NotificationRouter.shared.pendingEventId = id
            } else {
                FeatureRouter.shared.show(FeatureRegistry.home)
            }
        }
    }
}
