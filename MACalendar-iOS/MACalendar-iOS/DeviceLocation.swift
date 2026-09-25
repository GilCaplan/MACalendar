import CoreLocation
import Foundation

/// Tells the host where this device is, so sundown is computed for here.
///
/// Candle lighting moves by more than three hours across a year in one place,
/// and by hours again between places. A repeating event that skips Shabbat is
/// wrong the moment you travel — the boundary it avoids was computed somewhere
/// else, and nothing about the wrong answer looks wrong.
///
/// Deliberately modest about it: one reading when asked, never continuous
/// tracking, and the coordinates go to your own host and nowhere else. A
/// position is only sent when it has actually moved enough to change an answer.
///
/// "Asked" means app launch AND every return to the foreground (Gil,
/// 2026-09-24: the Shabbat lines must follow the phone, "because the exact
/// minute is important"). That is the battery-cheap choice: a single
/// kilometre-accuracy fix — wifi and cell, rarely GPS — at most once every few
/// minutes, and only while the app is on screen. The significant-change
/// service would need "Always" permission to be any better, and a calendar has
/// no business asking for that.
///
/// When a new position IS sent, the calendar re-reads the windows, so the
/// yellow lines move without anyone touching anything.
@MainActor
final class DeviceLocation: NSObject, ObservableObject {
    static let shared = DeviceLocation()

    /// Below this, sundown does not move by a noticeable fraction of a minute.
    /// It was 25 km, which east–west is about ONE MINUTE of sunset at Israeli
    /// latitudes (a degree of longitude is ~94 km and 4 minutes) — the exact
    /// error the Shabbat lines exist to avoid. 5 km is ~13 seconds.
    private static let significantMetres: CLLocationDistance = 5_000

    /// The least time between two fixes. Foregrounding the app ten times in a
    /// minute should not ask the radio ten times.
    private static let minInterval: TimeInterval = 5 * 60

    @Published private(set) var lastSent: CLLocation?
    @Published private(set) var status: String = ""
    /// The time zone the last position was sent with. A new zone is always
    /// worth sending, however short the distance — the lines are drawn in it.
    private var lastSentZone: String?
    private var lastAsked: Date?

    private let manager = CLLocationManager()
    private var api: APIClient?
    private var pending = false

    private override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyKilometer   // a city is plenty
    }

    /// Ask once. Safe to call on every launch and every foreground; it does
    /// nothing without permission, and nothing if it asked a moment ago
    /// (`force` skips that — the switch was just turned on).
    func refresh(using api: APIClient, force: Bool = false) {
        self.api = api
        if force {
            lastSent = nil                  // resend even from the same spot
        } else if let asked = lastAsked, Date().timeIntervalSince(asked) < Self.minInterval {
            return
        }
        lastAsked = Date()
        switch manager.authorizationStatus {
        case .notDetermined:
            manager.requestWhenInUseAuthorization()
        case .authorizedWhenInUse, .authorizedAlways:
            pending = true
            manager.requestLocation()
        default:
            status = "Location is off, so sundown uses the place set on your host."
        }
    }

    private func send(_ location: CLLocation) {
        let tz = TimeZone.current.identifier
        // Skip a position that cannot change any answer — most foregrounds.
        if let last = lastSent, last.distance(from: location) < Self.significantMetres,
           lastSentZone == tz {
            return
        }
        let previous = (lastSent, lastSentZone)
        lastSent = location
        lastSentZone = tz
        Task { [weak self] in
            do {
                try await self?.api?.setObservanceLocation(
                    latitude: location.coordinate.latitude,
                    longitude: location.coordinate.longitude,
                    timezone: tz)
                await MainActor.run {
                    self?.status = "Sundown is computed for where you are."
                    // The Shabbat lines were drawn for the old place: re-read
                    // the windows (the month view through the navigator, the
                    // day view through the refresh tick).
                    CalendarNavigator.shared.reload()
                    self?.api?.requestRefresh()
                }
            } catch {
                // Never surfaced as a failure: the host has a configured place
                // to fall back on, and this is an improvement, not a dependency.
                // Forget that it was "sent", so the next foreground tries again
                // rather than believing the host already knows.
                await MainActor.run {
                    self?.status = ""
                    self?.lastSent = previous.0
                    self?.lastSentZone = previous.1
                }
            }
        }
    }
}

extension DeviceLocation: CLLocationManagerDelegate {
    nonisolated func locationManager(_ m: CLLocationManager, didUpdateLocations locs: [CLLocation]) {
        guard let best = locs.last else { return }
        Task { @MainActor in
            guard self.pending else { return }
            self.pending = false
            self.send(best)
        }
    }

    nonisolated func locationManager(_ m: CLLocationManager, didFailWithError error: Error) {
        Task { @MainActor in
            self.pending = false
            self.status = ""
        }
    }

    nonisolated func locationManagerDidChangeAuthorization(_ m: CLLocationManager) {
        Task { @MainActor in
            if m.authorizationStatus == .authorizedWhenInUse || m.authorizationStatus == .authorizedAlways {
                self.pending = true
                m.requestLocation()
            }
        }
    }
}
