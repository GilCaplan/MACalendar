import XCTest

/// The Ranker tab with no Mac: it ranks on the phone, so it must open on its
/// start card — what to add and how — not on "your Mac isn't reachable"
/// (Gil, 2026-10-12). Port 59999 has nothing on it.
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
        XCTAssertTrue(text.contains("table"), "the start card should say what to add: \(text)")
        XCTAssertFalse(text.contains("reachable"), "the tab must not need the Mac: \(text)")
        XCTAssertTrue(app.buttons["ranker-table"].firstMatch.exists, "no way to pick a table")

        let shot = XCTAttachment(screenshot: app.screenshot())
        shot.name = "ranker-empty"
        shot.lifetime = .keepAlways
        add(shot)
    }
}
