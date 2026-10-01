import XCTest

/// Settings sections fold (TASKS 50): a section's title opens and closes it,
/// and "Settings sections start" decides how they open — all open, all
/// closed, or as last left. The start mode is passed in the argument domain,
/// which wins over the saved setting.
final class SettingsFoldUITests: XCTestCase {

    override func setUp() { continueAfterFailure = false }

    private func settings(_ args: [String]) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["-serverURL", "127.0.0.1:59999"] + args
        app.launch()
        let allow = XCUIApplication(bundleIdentifier: "com.apple.springboard").buttons["Allow"]
        if allow.waitForExistence(timeout: 3) { allow.tap() }
        app.buttons["tab-settings"].firstMatch.tap()
        return app
    }

    func testATitleFoldsItsSection() throws {
        let app = settings(["-settingsFold.start", "open"])
        let appearance = app.staticTexts["Appearance"].firstMatch
        XCTAssertTrue(appearance.waitForExistence(timeout: 5), "Calendar didn't start open")
        app.buttons["fold-Calendar"].firstMatch.tap()
        XCTAssertFalse(appearance.waitForExistence(timeout: 2), "Calendar didn't fold")
        XCTAssertTrue(app.staticTexts["Notifications"].firstMatch.exists, "folding Calendar folded others")
        app.buttons["fold-Calendar"].firstMatch.tap()
        XCTAssertTrue(appearance.waitForExistence(timeout: 2), "Calendar didn't open again")
    }

    func testAllClosedStartsClosed() throws {
        let app = settings(["-settingsFold.start", "closed"])
        XCTAssertTrue(app.buttons["fold-Calendar"].firstMatch.waitForExistence(timeout: 5))
        XCTAssertFalse(app.staticTexts["Appearance"].firstMatch.exists)
        XCTAssertFalse(app.staticTexts["Notifications"].firstMatch.exists)
        app.buttons["fold-Calendar"].firstMatch.tap()
        XCTAssertTrue(app.staticTexts["Appearance"].firstMatch.waitForExistence(timeout: 2))
    }

    func testAsLastLeftKeepsWhatWasClosed() throws {
        let app = settings(["-settingsFold.start", "last", "-settingsFold.closed", "(\"Calendar\")"])
        XCTAssertTrue(app.buttons["fold-Calendar"].firstMatch.waitForExistence(timeout: 5))
        XCTAssertFalse(app.staticTexts["Appearance"].firstMatch.exists, "Calendar was left closed")
        XCTAssertTrue(app.staticTexts["Notifications"].firstMatch.exists, "Notifications was left open")
        let shot = XCTAttachment(screenshot: app.screenshot())
        shot.name = "settings-fold"
        shot.lifetime = .keepAlways
        add(shot)
    }
}
