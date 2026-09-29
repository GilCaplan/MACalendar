import XCTest

/// Settings ▸ Appearance ▸ Show hours, on the phone: Week and Day DRAW only
/// the chosen hours. The first build fitted them to the screen and left the
/// night a scroll away (Gil: "doesn't work well enough"), and a helper test
/// could not have seen that — only the screen can, so this looks at it.
///
/// Launched offline (`-serverURL` at a closed port) with `-hoursFrom 7
/// -hoursTo 24` in the argument domain, which wins over the saved settings —
/// the same trick `OfflineSyncUITests` uses. An event in the phone's local
/// cache before 7 AM would widen the hours (on purpose), so the assertion is
/// on the edges: whatever the first shown hour is, nothing above it is on
/// screen, and scrolling up does not bring it back.
final class ShownHoursUITests: XCTestCase {

    override func setUp() { continueAfterFailure = false }

    func testWeekAndDayShowOnlyTheChosenHours() throws {
        let app = XCUIApplication()
        app.launchArguments = ["-serverURL", "127.0.0.1:59999", "-hoursFrom", "7", "-hoursTo", "24"]
        app.launch()
        let allow = XCUIApplication(bundleIdentifier: "com.apple.springboard").buttons["Allow"]
        if allow.waitForExistence(timeout: 3) { allow.tap() }
        let calendarTab = app.tabBars.buttons["Calendar"]
        if calendarTab.waitForExistence(timeout: 5) { calendarTab.tap() }

        for mode in ["Week", "Day"] {
            app.buttons[mode].firstMatch.tap()
            let seven = app.staticTexts["7 AM"].firstMatch
            XCTAssertTrue(seven.waitForExistence(timeout: 10), "\(mode): no 7 AM row")
            // Both edges on screen without scrolling: the last hour too. The
            // first run of this test showed 7 AM at the top and 11 PM below
            // the fold — the rows had hit their minimum height.
            XCTAssertTrue(app.staticTexts["11 PM"].firstMatch.isHittable,
                          "\(mode): 11 PM is not on screen — the hours do not fit")
            for _ in 0..<3 { app.swipeDown() }            // try to reach the night
            let six = app.staticTexts["6 AM"].firstMatch
            if !six.isHittable {
                XCTAssertTrue(seven.isHittable, "\(mode): 7 AM is the top and on screen")
            }
            XCTAssertFalse(app.staticTexts["12 AM"].firstMatch.isHittable,
                           "\(mode): scrolled up to midnight — the night is still there")
            let shot = XCUIScreen.main.screenshot()
            add(XCTAttachment(screenshot: shot))
            if let dir = ProcessInfo.processInfo.environment["SHOT_DIR"] {
                try? shot.pngRepresentation.write(to: URL(fileURLWithPath: "\(dir)/\(mode).png"))
            }
        }
    }
}
