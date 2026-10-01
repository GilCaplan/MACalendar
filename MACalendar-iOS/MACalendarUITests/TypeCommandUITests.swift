import XCTest

/// Typing a command instead of saying it (Gil, 2026-10-01): the keyboard badge
/// on the mic opens a short box, the keyboard is up, Send sends. With no Mac
/// reachable the command is kept for later, as a recording would be.
final class TypeCommandUITests: XCTestCase {

    override func setUp() { continueAfterFailure = false }

    private func snap(_ app: XCUIApplication, _ name: String) {
        let shot = XCTAttachment(screenshot: app.screenshot())
        shot.name = name
        shot.lifetime = .keepAlways
        add(shot)
    }

    func testTypingACommand() throws {
        let app = XCUIApplication()
        app.launchArguments = ["-serverURL", "127.0.0.1:59998", "-showThinking", "0",
                               "-vocabOnboardingDone", "1", "-remindersEnabled", "0"]
        app.launch()
        let allow = XCUIApplication(bundleIdentifier: "com.apple.springboard").buttons["Allow"]
        if allow.waitForExistence(timeout: 3) { allow.tap() }

        let badge = app.buttons.matching(identifier: "type-command-button")
        var hit: XCUIElement?
        for _ in 0..<20 {
            for i in 0..<badge.count where badge.element(boundBy: i).isHittable { hit = badge.element(boundBy: i) }
            if hit != nil { break }
            Thread.sleep(forTimeInterval: 0.5)
        }
        let button = try XCTUnwrap(hit, "no keyboard badge on the mic")
        snap(app, "1-badge-on-mic")
        button.tap()

        let field = app.textFields["type-command-field"].firstMatch.exists
            ? app.textFields["type-command-field"].firstMatch
            : app.textViews["type-command-field"].firstMatch
        XCTAssertTrue(field.waitForExistence(timeout: 5), "no box to type into")
        XCTAssertFalse(app.buttons["type-command-send"].firstMatch.isEnabled, "Send before anything is typed")
        field.typeText("buy milk")
        snap(app, "2-typed")
        app.buttons["type-command-send"].firstMatch.tap()
        XCTAssertTrue(field.waitForNonExistence(timeout: 5), "the box did not close on Send")
    }
}
