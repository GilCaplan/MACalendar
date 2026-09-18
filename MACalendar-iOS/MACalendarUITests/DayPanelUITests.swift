import XCTest

/// Prove the day panel is actually LODGED with iOS, and that the switch that
/// governs it reaches the Mac.
///
/// Both halves needed driving rather than reading, and the first run proved
/// why: the app fetched a week of panels from `GET /digest/upcoming`, called
/// `UNUserNotificationCenter.add` for each, and iOS rejected every one of them
/// because nothing had ever asked for authorization — the adds are
/// fire-and-forget, so it failed in total silence. Reading the Swift would not
/// have shown that; a clean install did.
///
/// The Mac is reached the same way `OfflineSyncUITests` reaches it — see that
/// file's header for `-serverURL` and where the real address comes from.
final class DayPanelUITests: XCTestCase {

    private var realServer: String {
        if let env = ProcessInfo.processInfo.environment["MACALENDAR_UITEST_SERVER"],
           !env.trimmingCharacters(in: .whitespaces).isEmpty {
            return env
        }
        let fromPlist = Bundle(for: Self.self)
            .object(forInfoDictionaryKey: "MACalendarServerURL") as? String ?? ""
        let trimmed = fromPlist.trimmingCharacters(in: .whitespaces)
        return trimmed.isEmpty ? "127.0.0.1:8080" : trimmed
    }

    override func setUp() {
        super.setUp()
        continueAfterFailure = false
    }

    private func launch() -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["-serverURL", realServer]
        app.launch()
        return app
    }

    /// The permission ask arrives BY ITSELF, off the back of having panels to
    /// schedule — the user does not have to go looking for it in Settings.
    ///
    /// This is the regression test for the silent-rejection bug above: if the
    /// ask stops happening, a fresh install goes back to scheduling nothing.
    func testItAsksToSendNotificationsOnceItHasAPanelToLodge() throws {
        let app = launch()
        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        let allow = springboard.buttons["Allow"]

        if !allow.waitForExistence(timeout: 30) {
            // iOS asks ONCE per install, ever. There is no API to reset that
            // (`XCUIProtectedResource` has no notifications case), so on a
            // simulator where this app has already been granted or denied, no
            // alert can appear and the assertion below would fail for a reason
            // that is nothing to do with the app. Tell the difference by
            // asking the app what it sees, and say plainly what to do about
            // it — rather than failing, or passing on a check that never ran.
            openSettings(app)
            let allowed = app.staticTexts["Notifications allowed"]
            openSection("Notifications", revealing: allowed, in: app)
            let settled = allowed.waitForExistence(timeout: 10)
                || app.buttons["Notifications are off — open iOS Settings"].exists
            if settled {
                throw XCTSkip("this simulator has already answered the notification prompt, "
                              + "so the first-run ask cannot be exercised. Reinstall first: "
                              + "xcrun simctl uninstall <device> com.macalendar.app")
            }
            XCTFail("nothing asked to send notifications, so no panel can ever fire")
            return
        }
        allow.tap()

        // Settle, then confirm the app agrees it is allowed — the Settings
        // row reads the real authorization status, not our own flag.
        XCTAssertTrue(app.wait(for: .runningForeground, timeout: 10))
        openSettings(app)
        let allowed = app.staticTexts["Notifications allowed"]
        openSection("Notifications", revealing: allowed, in: app)
        XCTAssertTrue(allowed.waitForExistence(timeout: 10))
    }

    /// One switch, and it is shared with the Mac (Gil, 2026-09-11: "it's on or
    /// off") — so flipping it here must change the Mac's own config, not just
    /// this phone's. Asserted against the Mac itself rather than against the
    /// toggle springing back, which would pass with no request sent at all.
    func testTheSwitchTravelsToTheMac() throws {
        let app = launch()
        allowNotificationsIfAsked()
        openSettings(app)

        let toggle = app.switches.containing(.staticText, identifier: "Morning summary").firstMatch
        openSection("Notifications", revealing: toggle, in: app)
        XCTAssertTrue(toggle.waitForExistence(timeout: 15), "no Morning summary switch in Settings")
        // Settings is a long scroll view and `waitForExistence` is true for a
        // row that is still below the fold — where a tap lands on whatever
        // happens to be at those coordinates instead. Scroll it into reach
        // first, or the test reports "the write never went out" for a tap that
        // never touched the control.
        XCTAssertTrue(scrollIntoReach(toggle, in: app), "the Morning summary switch never came into reach")

        let wasOn = (toggle.value as? String) == "1"
        addTeardownBlock {
            if ((toggle.value as? String) == "1") != wasOn { Self.flip(toggle) }
        }

        Self.flip(toggle)
        // Prove the SWITCH moved before blaming the network for the value not
        // reaching the Mac. A plain `.tap()` on this element lands on the row's
        // label — two lines of text in a VStack — and does nothing at all,
        // which fails identically to a write that never went out.
        XCTAssertEqual((toggle.value as? String) == "1", !wasOn,
                       "the switch itself did not move, so nothing was ever sent")
        // The PATCH is fire-and-forget from the UI's point of view, so give the
        // Mac a moment before asking it.
        let expected = !wasOn
        var seen: Bool? = nil
        for _ in 0..<20 {
            Thread.sleep(forTimeInterval: 0.5)
            seen = macSaysDailyDigest()
            if seen == expected { break }
        }
        XCTAssertEqual(seen, expected,
                       "the Mac's notifications.daily_digest did not follow the phone's switch")
    }

    // MARK: - Helpers

    /// Settings sections start FOLDED (2026-09-18), so a control inside one
    /// does not exist in the accessibility tree until its section is opened.
    /// Taps the header only when the thing we want is not already showing, so
    /// this is safe to call whatever state the section was left in.
    @discardableResult
    func openSection(_ title: String, revealing target: XCUIElement,
                     in app: XCUIApplication) -> Bool {
        if target.exists { return true }
        let header = app.buttons[title].firstMatch
        guard header.waitForExistence(timeout: 10) else { return false }
        for _ in 0..<10 where !header.isHittable { app.swipeUp() }
        header.tap()
        return target.waitForExistence(timeout: 5)
    }

    /// Hit the control, not the label. A SwiftUI `Toggle` whose label is a
    /// VStack reports one element spanning the whole row, and its centre — where
    /// `.tap()` goes — is the caption text.
    private static func flip(_ toggle: XCUIElement) {
        toggle.coordinate(withNormalizedOffset: CGVector(dx: 0.93, dy: 0.5)).tap()
    }

    /// Swipe until `element` is actually hittable, or give up.
    private func scrollIntoReach(_ element: XCUIElement, in app: XCUIApplication) -> Bool {
        for _ in 0..<12 {
            if element.isHittable { return true }
            app.swipeUp()
        }
        return element.isHittable
    }

    private func openSettings(_ app: XCUIApplication) {
        let tab = app.buttons["Settings"].firstMatch
        if tab.waitForExistence(timeout: 10) { tab.tap() }
    }

    private func allowNotificationsIfAsked() {
        let allow = XCUIApplication(bundleIdentifier: "com.apple.springboard").buttons["Allow"]
        if allow.waitForExistence(timeout: 15) { allow.tap() }
    }

    /// Ask the Mac directly what it now believes. The test process has plain
    /// network access — this is the only way to tell "the switch moved" from
    /// "the switch moved and was SAVED".
    private func macSaysDailyDigest() -> Bool? {
        guard let url = URL(string: "http://\(realServer)/config") else { return nil }
        var result: Bool? = nil
        let done = DispatchSemaphore(value: 0)
        URLSession.shared.dataTask(with: url) { data, _, _ in
            defer { done.signal() }
            guard let data,
                  let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let n = obj["notifications"] as? [String: Any]
            else { return }
            result = n["daily_digest"] as? Bool
        }.resume()
        _ = done.wait(timeout: .now() + 10)
        return result
    }
}
