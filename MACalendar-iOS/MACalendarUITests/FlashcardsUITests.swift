import XCTest

/// The Flashcards tab, with no Mac and nothing cached: it must say in a
/// sentence what is going on and what to do, never draw an empty screen
/// (`assistant/features/CONVENTION.md`: "a tab that renders empty is
/// indistinguishable from a broken one"). Port 59999 has nothing on it.
final class FlashcardsUITests: XCTestCase {

    override func setUp() { continueAfterFailure = false }

    func testTheTabExplainsItselfWithNoSetsAndNoMac() {
        let app = XCUIApplication()
        app.launchArguments = ["-serverURL", "127.0.0.1:59999", "-vocabOnboardingDone", "1",
                               "-remindersEnabled", "0", "-uitestDefaultPrefs"]
        app.launch()

        let tab = app.buttons["tab-flashcards"].firstMatch
        XCTAssertTrue(tab.waitForExistence(timeout: 10), "no Flashcards tab")
        tab.tap()

        let sentence = app.staticTexts["flashcards-empty"].firstMatch
        XCTAssertTrue(sentence.waitForExistence(timeout: 15), "the empty tab says nothing")
        let text = sentence.label
        XCTAssertTrue(text.contains("Mac") || text.contains("Import"),
                      "the sentence should say what to do: \(text)")

        let shot = XCTAttachment(screenshot: app.screenshot())
        shot.name = "flashcards-empty"
        shot.lifetime = .keepAlways
        add(shot)
    }
}
