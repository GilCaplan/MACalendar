import SwiftUI

/// Settings sections that fold (TASKS 50, Gil 2026-09-30): each group's header
/// opens and closes it, and a setting says how they start — all open, all
/// closed, or as they were last left. Only the fold is added; the rows look
/// exactly as they did. Per device, in UserDefaults, like the Mac's.
///
/// Starts ALL CLOSED unless changed: Gil's standing call on Settings folds
/// (2026-09-18, "Default is minimized please") — the headings are then the
/// screen's table of contents.
@MainActor
final class SettingsFold: ObservableObject {
    enum Start: String, CaseIterable {
        case open, closed, last
        var label: String {
            switch self {
            case .open: return "All open"
            case .closed: return "All closed"
            case .last: return "As I left them"
            }
        }
    }

    static let shared = SettingsFold()
    static let sections = ["Calendar", "Notifications & tabs", "Assistant", "Connection", "Just for fun", "About"]

    private let defaults: UserDefaults
    @Published var start: Start { didSet { defaults.set(start.rawValue, forKey: "settingsFold.start") } }
    @Published private(set) var closed: Set<String>

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        let start = Start(rawValue: defaults.string(forKey: "settingsFold.start") ?? "") ?? .closed
        self.start = start
        switch start {
        case .open: closed = []
        case .closed: closed = Set(Self.sections)
        case .last: closed = Set(defaults.stringArray(forKey: "settingsFold.closed") ?? [])
        }
    }

    func isOpen(_ section: String) -> Bool { !closed.contains(section) }

    func toggle(_ section: String) {
        if closed.contains(section) { closed.remove(section) } else { closed.insert(section) }
        // Always remembered, so switching to "As I left them" starts from now.
        defaults.set(Array(closed).sorted(), forKey: "settingsFold.closed")
    }
}

/// A section header that folds its section: the same title, plus a chevron.
struct FoldHeader: View {
    let title: String
    @ObservedObject private var fold = SettingsFold.shared

    init(_ title: String) { self.title = title }

    var body: some View {
        Button {
            withAnimation(.easeInOut(duration: 0.2)) { fold.toggle(title) }
        } label: {
            HStack {
                Text(title)
                Spacer()
                Image(systemName: "chevron.right")
                    .font(.caption.weight(.semibold))
                    .rotationEffect(.degrees(fold.isOpen(title) ? 90 : 0))
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .foregroundColor(.secondary)
        .accessibilityIdentifier("fold-\(title)")
        .accessibilityValue(fold.isOpen(title) ? "open" : "closed")
    }
}
