import XCTest

/// Event titles on the Day and Week grids, photographed against a stand-in
/// Mac (scratchpad fake_mac.py on 127.0.0.1:59130) that serves a fixed week:
/// a long "Army ceremony" with a short event stacked on its middle — the case
/// where the title was squeezed to "Army ceremo" (Gil, 2026-10-10) — and long
/// titles on busy days. Skips without the stand-in; the screenshots are the
/// point, read by a person.
final class CalendarTitlesUITests: XCTestCase {

    override func setUp() { continueAfterFailure = false }

    private func shot(_ app: XCUIApplication, _ name: String) {
        let a = XCTAttachment(screenshot: app.screenshot())
        a.name = name
        a.lifetime = .keepAlways
        add(a)
    }

    private func standInIsUp() -> Bool {
        let sem = DispatchSemaphore(value: 0); var ok = false
        URLSession.shared.dataTask(with: URL(string: "http://127.0.0.1:59130/health")!) { _, r, _ in
            ok = (r as? HTTPURLResponse)?.statusCode == 200; sem.signal()
        }.resume()
        _ = sem.wait(timeout: .now() + 3); return ok
    }

    func testTitlesOnTheDayAndWeekGrids() throws {
        try XCTSkipUnless(standInIsUp(), "start fake_mac.py on 59130 to run this")
        let app = XCUIApplication()
        app.launchArguments = ["-serverURL", "127.0.0.1:59130", "-vocabOnboardingDone", "1",
                               "-remindersEnabled", "0", "-uitestDefaultPrefs"]
        app.launch()
        let sb = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        for label in ["Allow", "OK"] where sb.buttons[label].waitForExistence(timeout: 1.5) { sb.buttons[label].tap() }

        app.buttons["Day"].firstMatch.tap()
        let army = app.descendants(matching: .any)
            .matching(NSPredicate(format: "label CONTAINS 'Army'")).firstMatch
        XCTAssertTrue(army.waitForExistence(timeout: 15), "the stand-in's events never showed")
        // the long event starts at 8: bring 8 am into view
        app.swipeDown(); app.swipeDown()
        sleep(1)
        shot(app, "day-today")
        app.swipeUp()
        sleep(1)
        shot(app, "day-today-later")

        app.buttons["Week"].firstMatch.tap()
        sleep(2)
        shot(app, "week")
        // the days scroll sideways; the header must move with them
        app.swipeRight(); app.swipeRight()
        sleep(1)
        shot(app, "week-start")
    }

    /// Sideways: just the schedule, full screen, all seven days; one button
    /// brings the controls back (Gil, 2026-10-10).
    func testSidewaysIsAFullScreenSchedule() throws {
        try XCTSkipUnless(standInIsUp(), "start fake_mac.py on 59130 to run this")
        let app = XCUIApplication()
        app.launchArguments = ["-serverURL", "127.0.0.1:59130", "-vocabOnboardingDone", "1",
                               "-remindersEnabled", "0", "-uitestDefaultPrefs"]
        app.launch()
        let sb = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        for label in ["Allow", "OK"] where sb.buttons[label].waitForExistence(timeout: 1.5) { sb.buttons[label].tap() }
        app.buttons["Week"].firstMatch.tap()
        XCTAssertTrue(app.buttons["tab-settings"].firstMatch.waitForExistence(timeout: 5))
        app.buttons["Back"].firstMatch.tap()                 // the stand-in's week
        XCUIDevice.shared.orientation = .landscapeLeft
        sleep(2)
        shot(app, "landscape-week")
        let win = app.windows.firstMatch.frame
        let days = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"].map { d -> String in
            let e = app.staticTexts[d].firstMatch
            return e.exists ? "\(d)@\(Int(e.frame.midX))" : "\(d)@-"
        }
        print("LANDSCAPE window \(win) days \(days.joined(separator: " "))")
        XCTAssertFalse(app.buttons["tab-settings"].firstMatch.exists, "the tab bar is still there sideways")
        XCTAssertFalse(app.buttons["mic-button"].firstMatch.isHittable, "the mic is still there sideways")
        let toggle = app.buttons["calendar-focus-toggle"].firstMatch
        XCTAssertTrue(toggle.exists, "no way to bring the controls back")
        toggle.tap()
        sleep(1)
        XCTAssertTrue(app.buttons["tab-settings"].firstMatch.waitForExistence(timeout: 3), "controls did not come back")
        shot(app, "landscape-controls")
        toggle.tap()
        XCUIDevice.shared.orientation = .portrait
        sleep(2)
        XCTAssertTrue(app.buttons["tab-settings"].firstMatch.waitForExistence(timeout: 3), "upright lost the tab bar")
        shot(app, "portrait-again")
    }

    func testTheWeekCanShowAllSevenUpright() throws {
        try XCTSkipUnless(standInIsUp(), "start fake_mac.py on 59130 to run this")
        let app = XCUIApplication()
        app.launchArguments = ["-serverURL", "127.0.0.1:59130", "-vocabOnboardingDone", "1",
                               "-remindersEnabled", "0", "-weekFitsAll", "1"]
        app.launch()
        app.buttons["Week"].firstMatch.tap()
        sleep(2)
        shot(app, "week-all-seven")
    }
}
