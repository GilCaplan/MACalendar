import XCTest

/// A phone with NO Mac (DEVQA Q85): a fresh install asks how it runs, and on
/// "this iPhone" a typed command is read and done on the phone — an event
/// made, found by a question, and deleted by name. Nothing reaches a server.
final class StandaloneUITests: XCTestCase {

    override func setUp() { continueAfterFailure = false }

    private func snap(_ app: XCUIApplication, _ name: String) {
        let shot = XCTAttachment(screenshot: app.screenshot())
        shot.name = name
        shot.lifetime = .keepAlways
        add(shot)
    }

    private func type(_ app: XCUIApplication, _ text: String) throws {
        let badge = app.buttons.matching(identifier: "type-command-button")
        var hit: XCUIElement?
        for _ in 0..<20 {
            for i in 0..<badge.count where badge.element(boundBy: i).isHittable { hit = badge.element(boundBy: i) }
            if hit != nil { break }
            Thread.sleep(forTimeInterval: 0.5)
        }
        try XCTUnwrap(hit, "no keyboard badge on the mic").tap()
        let field = app.textFields["type-command-field"].firstMatch.exists
            ? app.textFields["type-command-field"].firstMatch
            : app.textViews["type-command-field"].firstMatch
        XCTAssertTrue(field.waitForExistence(timeout: 5), "no box to type into")
        field.typeText(text)
        app.buttons["type-command-send"].firstMatch.tap()
    }

    private func sees(_ app: XCUIApplication, _ words: String, timeout: TimeInterval = 10) -> Bool {
        app.staticTexts.matching(NSPredicate(format: "label CONTAINS[c] %@", words)).firstMatch
            .waitForExistence(timeout: timeout)
    }

    private func closeThinking(_ app: XCUIApplication) {
        let done = app.buttons["Done"].firstMatch
        if done.waitForExistence(timeout: 3) { done.tap() } else { app.swipeDown() }
    }

    func testAPhoneWithNoMacDoesTheCommandItself() throws {
        let app = XCUIApplication()
        app.launchArguments = ["-uitestFreshStart", "-showThinking", "1", "-vocabOnboardingDone", "1",
                               "-remindersEnabled", "0", "-titleEmojiCount", "1"]
        app.launch()
        let allow = XCUIApplication(bundleIdentifier: "com.apple.springboard").buttons["Allow"]
        if allow.waitForExistence(timeout: 3) { allow.tap() }

        let phone = app.buttons["welcome-phone"].firstMatch
        XCTAssertTrue(phone.waitForExistence(timeout: 10), "a fresh install did not ask how it runs")
        snap(app, "1-welcome")
        phone.tap()

        try type(app, "dentist appointment tomorrow at 3")
        XCTAssertTrue(sees(app, "Added dentist appointment"), "the phone did not add it")
        snap(app, "2-added")
        closeThinking(app)

        try type(app, "what do i have tomorrow")
        XCTAssertTrue(sees(app, "dentist appointment"), "the question did not find it")
        snap(app, "3-asked")
        closeThinking(app)

        try type(app, "cancel the dentist tomorrow")
        XCTAssertTrue(sees(app, "Deleted dentist appointment"), "the delete did not find it by name")
        snap(app, "4-deleted")
        closeThinking(app)

        // leave the simulator as the other tests expect it: a phone with a Mac
        app.terminate()
        app.launchArguments = ["-uitestFreshStart", "-welcomeDone", "1"]
        app.launch()
    }
}
