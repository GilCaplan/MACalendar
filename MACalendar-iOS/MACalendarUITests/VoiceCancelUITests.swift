import XCTest

/// While a command is thinking you can still change your mind (Gil,
/// 2026-10-01: "why can't i rerecord or cancel prompt … we want to support
/// cancelling / rerecording / adding to original prompt more audio").
///
/// Needs a Mac that is slow to answer: `scratchpad/slow_mac.py` on port 59123
/// (healthy, 30 s per command). Skips when nothing listens there, so it
/// never fails on a machine without it.
final class VoiceCancelUITests: XCTestCase {

    override func setUp() { continueAfterFailure = false }

    private func slowMacIsUp() -> Bool {
        let sem = DispatchSemaphore(value: 0)
        var ok = false
        URLSession.shared.dataTask(with: URL(string: "http://127.0.0.1:59123/health")!) { _, r, _ in
            ok = (r as? HTTPURLResponse)?.statusCode == 200; sem.signal()
        }.resume()
        _ = sem.wait(timeout: .now() + 3)
        return ok
    }

    private func launch() -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["-serverURL", "127.0.0.1:59123", "-reviewBeforeSend", "0", "-showThinking", "0",
                               "-vocabOnboardingDone", "1", "-remindersEnabled", "0"]
        app.launch()
        return app
    }

    private func allowAlerts() {
        let sb = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        for label in ["Allow", "OK"] where sb.buttons[label].waitForExistence(timeout: 2) { sb.buttons[label].tap() }
    }

    /// The mic on screen — the Tasks tab has its own, hidden.
    private func mic(_ app: XCUIApplication) -> XCUIElement {
        let all = app.buttons.matching(identifier: "mic-button")
        for i in 0..<all.count where all.element(boundBy: i).isHittable { return all.element(boundBy: i) }
        return all.firstMatch
    }

    /// Record a second, stop: the command goes to the slow Mac and thinks.
    private func sendACommand(_ app: XCUIApplication) {
        let listening = app.staticTexts["Listening…"]
        XCTAssertTrue(app.buttons["mic-button"].firstMatch.waitForExistence(timeout: 10), "no mic")
        mic(app).tap()
        allowAlerts()
        if !listening.waitForExistence(timeout: 4) { mic(app).tap(); allowAlerts() }   // the first tap was the permission
        XCTAssertTrue(listening.waitForExistence(timeout: 5), "never started recording")
        sleep(2)
        mic(app).tap()
    }

    func testCancelRedoAndAddMoreWhileItThinks() throws {
        try XCTSkipUnless(slowMacIsUp(), "start scratchpad/slow_mac.py (port 59123) to run this")
        let app = launch()
        allowAlerts()
        let cancel = app.buttons["Cancel this command"].firstMatch
        let redo = app.buttons["Redo"].firstMatch
        let more = app.buttons["Add more"].firstMatch

        sendACommand(app)
        XCTAssertTrue(cancel.waitForExistence(timeout: 8), "no way to cancel while it thinks")
        XCTAssertTrue(redo.exists && more.exists)
        let shot = XCTAttachment(screenshot: app.screenshot()); shot.name = "thinking-bar"; shot.lifetime = .keepAlways; add(shot)
        cancel.tap()
        XCTAssertFalse(cancel.waitForExistence(timeout: 2), "still thinking after Cancel")
        XCTAssertFalse(app.staticTexts["Listening…"].exists, "Cancel must not start recording")

        sendACommand(app)
        XCTAssertTrue(more.waitForExistence(timeout: 8))
        more.tap()
        XCTAssertTrue(app.staticTexts["Listening…"].waitForExistence(timeout: 3), "Add more did not resume recording")
        app.buttons["Discard recording"].firstMatch.tap()

        sendACommand(app)
        XCTAssertTrue(redo.waitForExistence(timeout: 8))
        mic(app).tap()                                             // the mic itself: say it again
        XCTAssertTrue(app.staticTexts["Listening…"].waitForExistence(timeout: 3), "tapping the mic did not re-record")
        app.buttons["Discard recording"].firstMatch.tap()
    }
}
