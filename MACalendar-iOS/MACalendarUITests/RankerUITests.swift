import XCTest

/// The Ranker tab with no Mac: ranking runs on the Mac, so the tab must say
/// so in a sentence rather than draw an empty screen
/// (`assistant/features/CONVENTION.md`). Port 59999 has nothing on it.
final class RankerUITests: XCTestCase {

    override func setUp() { continueAfterFailure = false }

    func testTheTabExplainsItselfWithNoMac() {
        let app = XCUIApplication()
        app.launchArguments = ["-serverURL", "127.0.0.1:59999", "-vocabOnboardingDone", "1",
                               "-remindersEnabled", "0", "-uitestDefaultPrefs"]
        app.launch()

        var tab = app.buttons["tab-ranker"].firstMatch
        if !tab.waitForExistence(timeout: 10) {
            // Past the fifth tab, iOS folds the rest under More.
            let more = app.tabBars.buttons["More"].firstMatch
            XCTAssertTrue(more.waitForExistence(timeout: 5), "no Ranker tab and no More")
            more.tap()
            tab = app.staticTexts["Ranker"].firstMatch
            XCTAssertTrue(tab.waitForExistence(timeout: 5), "no Ranker under More")
        }
        tab.tap()

        let sentence = app.staticTexts["ranker-empty"].firstMatch
        XCTAssertTrue(sentence.waitForExistence(timeout: 15), "the tab says nothing")
        let text = sentence.label
        XCTAssertTrue(text.contains("Mac") || text.contains("table"),
                      "the sentence should say what is going on: \(text)")

        let shot = XCTAttachment(screenshot: app.screenshot())
        shot.name = "ranker-empty"
        shot.lifetime = .keepAlways
        add(shot)
    }
}
