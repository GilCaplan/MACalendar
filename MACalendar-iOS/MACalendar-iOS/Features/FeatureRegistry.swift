import SwiftUI

// MARK: - The Feature convention, on the phone
//
// A FEATURE is one of this assistant's own surfaces: Calendar, Tasks,
// Coursework, Workout, Timer, Teach, Jude. This file is the iOS half of
// `assistant/features/` — `CONVENTION.md` is the contract, `base.py` and
// `registry.py` the Mac's side of it, and the two must agree on `name` and
// `order` because those are what travel.
//
// It exists because a tab used to be declared THREE times in ContentView.swift
// — in `contentTabs`, in `tabContent`, and once more as an `onChange` bounce-off
// handler — plus a fourth time as a `show*Tab` flag in AppSettings and a fifth
// as a hand-written Toggle in SettingsView. They drifted, as hand-synced lists
// do: Timer never got a bounce-off handler, so hiding it while it was on screen
// left `selectedTab` pointing at a layer the ZStack no longer built — a blank
// screen with a working tab bar under it. Tag 3 was a hole left behind when
// Settings stopped being a tab, which is why the tab numbers encoded nothing.
//
// So: declared ONCE, here, and every list downstream is a loop over `all`.
//
// ## Structure is declared; only VISIBILITY travels
//
// Which features exist, and their label, icon and order, are in CODE on each
// platform. Only the on/off switch is shared state (`GET /features`,
// `PATCH /features/<name>`). That split is about the phone working on a train:
// a tab bar built from the server's answer could not be drawn until a request
// came back, and with the Mac asleep it would never be drawn at all. So
// `FeatureRegistry` never awaits anything, and `FeatureVisibility` answers from
// a local cache the moment it is asked.

/// One surface. The Swift mirror of `assistant/features/base.py`.
struct Feature: Identifiable {
    /// Machine name — the identity everywhere: the config key on the Mac, the
    /// URL segment, and what this client calls its own tab. Never an integer;
    /// the magic ints are exactly what left a hole at tag 3.
    let name: String
    /// What a person calls it.
    let label: String
    /// SF Symbol for the tab bar.
    let icon: String
    /// Display order. SPARSE (0, 10, 20 …) so inserting a feature between two
    /// others does not renumber the rest, and MATCHING the Python registry.
    let order: Int
    /// Cannot be switched off: Calendar and Tasks are what this app is, and a
    /// switch that empties the app is not a feature. Pinned features are never
    /// offered as a toggle, and the Mac answers 409 to a request to hide one.
    let pinned: Bool
    /// Whether a fresh install shows it.
    let defaultVisible: Bool
    /// One sentence under the Settings toggle, where the switch needs a caveat.
    /// Declared with the feature rather than typed into SettingsView, so it
    /// cannot go missing when the toggles become a loop.
    let note: String?
    /// The tab's content. `AnyView` because the seven have nothing in common
    /// but being views, and the shell must not learn which is which.
    let make: () -> AnyView

    var id: String { name }

    init(name: String, label: String, icon: String, order: Int,
         pinned: Bool = false, defaultVisible: Bool = true,
         note: String? = nil, make: @escaping () -> AnyView) {
        self.name = name
        self.label = label
        self.icon = icon
        self.order = order
        self.pinned = pinned
        self.defaultVisible = defaultVisible
        self.note = note
        self.make = make
    }
}

/// The list of features, and the only place that knows which ones exist.
/// Adding one is a folder under `Features/` and a line here.
enum FeatureRegistry {
    /// Every feature, in display order. `order` must match
    /// `assistant/features/<name>/feature.py` — it is the same surface.
    static let all: [Feature] = [
        Feature(name: "calendar", label: "Calendar", icon: "calendar",
                order: 0, pinned: true,
                make: { AnyView(CalendarTabView()) }),
        Feature(name: "tasks", label: "Tasks", icon: "checklist",
                order: 10, pinned: true,
                make: { AnyView(TasksView()) }),
        Feature(name: "coursework", label: "Coursework", icon: "graduationcap",
                order: 20,
                make: { AnyView(CourseworkView()) }),
        Feature(name: "workout", label: "Workout",
                icon: "figure.strengthtraining.traditional", order: 30,
                make: { AnyView(WorkoutView()) }),
        Feature(name: "timer", label: "Timer", icon: "timer",
                order: 40,
                make: { AnyView(TimerView()) }),
        Feature(name: "teach", label: "Teach", icon: "brain.head.profile",
                order: 50,
                make: { AnyView(LabelGameView()) }),
        // Off by default: Jude is a separate repository that has to be cloned
        // on the Mac, and a tab that can only say "not installed" is not a
        // feature. assistant/jude/ARCHITECTURE.md.
        Feature(name: "jude", label: "Jude", icon: "books.vertical",
                order: 60, defaultVisible: false,
                note: "Ask about Torah, Talmud and halacha. Needs Jude "
                    + "installed on your Mac — the tab says how if it isn't.",
                make: { AnyView(JudeView()) }),
    ].sorted { $0.order < $1.order }

    /// Where a bounce-off lands, and the first tab on a fresh install. Pinned,
    /// so it is always there to land on.
    static let home = "calendar"

    static func get(_ name: String) -> Feature? {
        all.first { $0.name == name }
    }

    /// The ones Settings may offer a switch for.
    static var togglable: [Feature] { all.filter { !$0.pinned } }
}

// MARK: - Which of them are switched on

/// The visibility map: the one piece of a feature that is shared state.
///
/// Read from a local cache and written locally FIRST, then pushed to the Mac.
/// Never awaited on the render path — the tab bar must draw with the Mac
/// asleep, which is the whole reason structure is declared in code.
@MainActor
final class FeatureVisibility: ObservableObject {
    static let shared = FeatureVisibility()

    /// name -> on/off. Only names this client knows are kept: a feature the Mac
    /// has and this build does not is not something the phone can draw.
    @Published private(set) var map: [String: Bool] = [:]

    /// The Mac's own sentence when it REFUSED a change (409 for a pinned
    /// feature). Surfaced in Settings rather than swallowed — a toggle that
    /// springs back with no explanation reads as a bug in the app.
    @Published var lastRefusal: String?

    private static let storeKey = "featureVisibility"

    private init() {
        var stored: [String: Bool] = [:]
        if let raw = UserDefaults.standard.dictionary(forKey: Self.storeKey) {
            for (name, value) in raw {
                if let on = value as? Bool { stored[name] = on }
            }
        }
        // Seed from the five `show*Tab` keys this replaced, once, so an
        // existing install keeps the setup it already had instead of silently
        // reverting to the defaults. Derived rather than listed: a second list
        // of names is the thing this file exists to stop.
        for feature in FeatureRegistry.all where stored[feature.name] == nil {
            if let legacy = UserDefaults.standard
                .object(forKey: Self.legacyKey(feature.name)) as? Bool {
                stored[feature.name] = legacy
            }
        }
        map = stored
        persist()
    }

    /// "coursework" -> "showCourseworkTab", the key AppSettings used to write.
    private static func legacyKey(_ name: String) -> String {
        "show" + name.prefix(1).uppercased() + name.dropFirst() + "Tab"
    }

    // -- reading ---------------------------------------------------------

    func isVisible(_ feature: Feature) -> Bool {
        feature.pinned || (map[feature.name] ?? feature.defaultVisible)
    }

    func isVisible(_ name: String) -> Bool {
        guard let feature = FeatureRegistry.get(name) else { return false }
        return isVisible(feature)
    }

    /// The tabs to draw, in order. Synchronous and offline by construction.
    var visible: [Feature] { FeatureRegistry.all.filter(isVisible) }

    // -- writing ---------------------------------------------------------

    /// Switch a feature on or off: locally first, then on the Mac.
    ///
    /// The local write is not conditional on the network — an unreachable Mac
    /// must not mean a toggle that does nothing. But it is not dropped on the
    /// floor either: it goes into the same offline queue every other write
    /// uses, and replays when the Mac is back. (Coursework's offline writes
    /// WERE dropped while its own comment claimed they were queued, which is
    /// why `CONVENTION.md` says a write that cannot go out is queued or fails
    /// loudly — never `try?` and a cache the next sync overwrites.)
    ///
    /// A REFUSAL is a different thing from an unreachable Mac: the Mac
    /// understood and said no, so the local change is rolled back and its
    /// sentence is shown.
    func set(_ feature: Feature, visible on: Bool, api: APIClient) {
        guard !feature.pinned else { return }
        let previous = map[feature.name]
        map[feature.name] = on
        persist()
        lastRefusal = nil
        Task { [weak self] in
            do {
                _ = try await api.setFeatureVisible(feature.name, on)
            } catch let error as APIError {
                if let sentence = error.serverSentence {
                    self?.map[feature.name] = previous
                    self?.persist()
                    self?.lastRefusal = sentence
                } else {
                    LocalStore.shared.enqueue(method: "PATCH",
                                              path: "/features/\(feature.name)",
                                              body: ["visible": on])
                }
            } catch {
                LocalStore.shared.enqueue(method: "PATCH",
                                          path: "/features/\(feature.name)",
                                          body: ["visible": on])
            }
        }
    }

    /// Pull the Mac's map. Anything but `visible` in the manifest is ignored —
    /// label, icon and order are declared in code on both sides, and a client
    /// that believed the server's copy could not draw a tab bar until it had
    /// answered.
    /// Merge the Mac's answer into the local map.
    ///
    /// EXPLICIT BEATS DEFAULT, in both directions, and that rule is the whole
    /// point of this function. Without it, adopting the Mac's `visible`
    /// wholesale meant a Mac that had never been asked about a feature — no
    /// `features:` block in its config.yaml, so `visible` was just
    /// `default_visible` — switched OFF a tab the user had switched on here.
    /// Jude was exactly that: on, on the phone; off, by default, on the Mac;
    /// off, after one refresh, with nothing to show the user why.
    ///
    /// So:
    /// - the Mac chose -> adopt it, it is the source of truth;
    /// - the Mac has no opinion but we do -> keep ours and PUSH IT UP, which
    ///   makes it explicit there and ends the disagreement permanently;
    /// - neither has an opinion -> leave it to the declared default.
    ///
    /// A name with a write still queued is skipped either way: the Mac has not
    /// seen that change yet, so its answer is stale by construction.
    func refresh(api: APIClient) async {
        guard let manifests = try? await api.features() else { return }
        let waiting = queuedNames
        var updated = map
        var toPush: [(Feature, Bool)] = []

        for manifest in manifests where !waiting.contains(manifest.name) {
            guard let feature = FeatureRegistry.get(manifest.name),
                  !feature.pinned else { continue }
            if manifest.explicit {
                updated[manifest.name] = manifest.visible
            } else if let mine = map[manifest.name], mine != manifest.visible {
                toPush.append((feature, mine))
            }
        }

        if updated != map {
            map = updated
            persist()
        }
        // Done after the local merge so the UI settles first; each PATCH makes
        // our value explicit on the Mac, so this happens once, not every poll.
        for (feature, on) in toPush {
            _ = try? await api.setFeatureVisible(feature.name, on)
        }
    }

    /// Features whose change is still sitting in the offline queue. The Mac's
    /// answer for those is STALE by definition — applying it would undo a
    /// switch the user flipped while the Mac was away, and it would come back
    /// on its own a second later when the queue flushed.
    private var queuedNames: Set<String> {
        Set(LocalStore.shared.allPending()
            .filter { $0.method == "PATCH" && $0.path.hasPrefix("/features/") }
            .map { String($0.path.dropFirst("/features/".count)) })
    }

    private func persist() {
        UserDefaults.standard.set(map, forKey: Self.storeKey)
    }
}

// MARK: - Which one is on screen

/// The selected tab, as a feature NAME.
///
/// Shared rather than private to the shell because features hand off to each
/// other: Search opens from the Calendar toolbar and can land on a task, and a
/// tapped reminder has to bring the calendar forward from wherever you were.
/// With an Int this was a magic number written at six call sites; the name is
/// the same token the API, the Mac's config and both clients already use.
@MainActor
final class FeatureRouter: ObservableObject {
    static let shared = FeatureRouter()

    @Published private(set) var selected: String = FeatureRegistry.home

    private init() {}

    func show(_ name: String) {
        guard FeatureRegistry.get(name) != nil else { return }
        selected = name
    }

    /// Called by the shell when the selected feature has just been hidden.
    /// Generic on purpose: one rule for all seven, instead of a per-tab handler
    /// that Timer never got.
    func bounceOffHidden(_ visibility: FeatureVisibility) {
        guard !visibility.isVisible(selected) else { return }
        selected = FeatureRegistry.home
    }
}
