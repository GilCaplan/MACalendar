import XCTest

/// Jude answered on this phone (Gil, 2026-10-11, option A): with "Answer on"
/// set to the iPhone, the Mac is asked for SOURCES only and the answer is
/// written here by Apple's model. Run against `fake_mac.py`, which logs the
/// request body; the test reads the result off the screen either way the
/// simulator answers — the badge where Apple's model runs, the reason where
/// it does not — and never shows the Mac's own answer text.
final class JudeOnPhoneUITests: XCTestCase {

    override func setUp() { continueAfterFailure = false }

    private func shot(_ app: XCUIApplication, _ name: String) {
        let a = XCTAttachment(screenshot: app.screenshot())
        a.name = name
        a.lifetime = .keepAlways
        add(a)
    }

    func testAnswerOnPhoneAsksTheMacForSourcesOnly() {
        let app = XCUIApplication()
        app.launchArguments = ["-serverURL", "127.0.0.1:59130", "-vocabOnboardingDone", "1",
                               "-remindersEnabled", "0", "-uitestDefaultPrefs",
                               "-judeAnswerOnPhone", "1"]
        app.launch()
        let tab = app.buttons["tab-jude"].firstMatch
        XCTAssertTrue(tab.waitForExistence(timeout: 10), "no Jude tab")
        tab.tap()

        let answerOn = app.segmentedControls["jude-answer-on"].firstMatch
        XCTAssertTrue(answerOn.waitForExistence(timeout: 5), "no Answer-on switch")
        shot(app, "jude-composer")

        let field = app.textViews.firstMatch.exists ? app.textViews.firstMatch : app.textFields.firstMatch
        field.tap()
        field.typeText("Until when may one recite the evening Shema?")
        app.buttons["Ask Jude"].firstMatch.tap()

        let badge = app.staticTexts["Answered on this phone"].firstMatch
        let refused = app.staticTexts.containing(NSPredicate(format: "label CONTAINS[c] 'Apple'")).firstMatch
        let deadline = Date().addingTimeInterval(60)
        while Date() < deadline && !badge.exists && !refused.exists { usleep(500_000) }
        shot(app, "jude-answered")
        XCTAssertTrue(badge.exists || refused.exists, "neither an on-phone answer nor a reason")
        XCTAssertFalse(app.staticTexts.containing(NSPredicate(format: "label CONTAINS 'The Mac\\'s answer'")).firstMatch.exists,
                       "the Mac wrote the answer — it should only have found the sources")
    }
}
