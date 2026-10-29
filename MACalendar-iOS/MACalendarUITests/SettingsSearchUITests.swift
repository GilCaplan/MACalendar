import XCTest

/// The search bar in Settings (Gil, 2026-10-29: "in settings add a search bar
/// to find things"). Typed into and tapped, not read: a word for a control two
/// taps deep finds it, the hit opens its page, and it does so with every
/// section folded shut — search must not care what the list is showing.
final class SettingsSearchUITests: XCTestCase {

    override func setUp() { continueAfterFailure = false }

    private func settings() -> XCUIApplication {
        let app = XCUIApplication()
        // Nothing listens on 59999: no Mac, so nothing real is read or written.
        app.launchArguments = ["-serverURL", "127.0.0.1:59999", "-settingsFold.start", "closed"]
        app.launch()
        let allow = XCUIApplication(bundleIdentifier: "com.apple.springboard").buttons["Allow"]
        if allow.waitForExistence(timeout: 3) { allow.tap() }
        app.buttons["tab-settings"].firstMatch.tap()
        return app
    }

    private func search(_ app: XCUIApplication, _ text: String) {
        let field = app.searchFields["Search settings"].firstMatch
        XCTAssertTrue(field.waitForExistence(timeout: 5), "no search bar in Settings")
        field.tap()
        field.typeText(text)
    }

    func testAWordForAControlFindsItAndOpensItsPage() throws {
        let app = settings()
        search(app, "dark")
        let theme = app.staticTexts["Theme"].firstMatch
        XCTAssertTrue(theme.waitForExistence(timeout: 3), "\"dark\" didn't find Theme")
        theme.tap()
        XCTAssertTrue(app.navigationBars["Appearance"].waitForExistence(timeout: 3),
                      "the hit didn't open the Appearance page")
        let shot = XCTAttachment(screenshot: app.screenshot())
        shot.name = "settings-search-opened"
        shot.lifetime = .keepAlways
        add(shot)
    }

    func testTheBackupSwitchIsFoundByWhatItIsFor() throws {
        let app = settings()
        search(app, "backup")
        XCTAssertTrue(app.staticTexts["Use your Mac when the main server is off"].firstMatch
                        .waitForExistence(timeout: 3))
        let shot = XCTAttachment(screenshot: app.screenshot())
        shot.name = "settings-search-backup"
        shot.lifetime = .keepAlways
        add(shot)
    }

    func testATabIsFoundByItsName() throws {
        let app = settings()
        search(app, "timer")
        XCTAssertTrue(app.staticTexts["Timer tab"].firstMatch.waitForExistence(timeout: 3))
    }

    func testNothingFoundSaysSo() throws {
        let app = settings()
        search(app, "qqqzzz")
        XCTAssertTrue(app.staticTexts["No settings match “qqqzzz”"].firstMatch.waitForExistence(timeout: 3))
    }
}
