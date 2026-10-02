import XCTest

/// Settings ▸ Easter egg, driven through the real UI: the page opens, the
/// demo plays over it (the overlay window is up and takes the tap), a tap
/// closes it, and an object's page lists its words and pictures with the
/// original locked. Screenshots are kept in the result bundle for review.
final class EasterEggUITests: XCTestCase {

    override func setUp() { continueAfterFailure = false }

    private func snap(_ app: XCUIApplication, _ name: String) {
        let shot = XCTAttachment(screenshot: app.screenshot())
        shot.name = name
        shot.lifetime = .keepAlways
        add(shot)
    }

    func testTheSettingsPageAndTheDemo() throws {
        let app = XCUIApplication()
        app.launchArguments = ["-serverURL", "127.0.0.1:59999", "-settingsFold.start", "open"]
        app.launch()
        let allow = XCUIApplication(bundleIdentifier: "com.apple.springboard").buttons["Allow"]
        if allow.waitForExistence(timeout: 3) { allow.tap() }

        let settingsTab = app.buttons["tab-settings"].firstMatch
        XCTAssertTrue(settingsTab.waitForExistence(timeout: 10))
        settingsTab.tap()
        let row = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "Easter egg")).firstMatch
        for _ in 0..<6 where !row.isHittable { app.swipeUp() }
        XCTAssertTrue(row.waitForExistence(timeout: 5), "no Easter egg row in Settings")
        row.tap()

        XCTAssertTrue(app.switches["Magic words"].firstMatch.waitForExistence(timeout: 5))
        snap(app, "1-settings")

        app.buttons["Play a demo on the whole screen"].firstMatch.tap()
        Thread.sleep(forTimeInterval: 1.0)
        snap(app, "2-demo-playing")
        Thread.sleep(forTimeInterval: 0.6)
        snap(app, "3-demo-later")
        app.tap()                                   // the overlay takes the tap and vanishes
        Thread.sleep(forTimeInterval: 0.5)

        let dog = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "German Shepherd")).firstMatch
        for _ in 0..<14 where !dog.isHittable { app.swipeUp() }
        XCTAssertTrue(dog.waitForExistence(timeout: 5))
        dog.tap()
        let kept = app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "Always kept")).firstMatch
        for _ in 0..<8 where !kept.exists { app.swipeUp() }     // the Pictures section is below the fold
        XCTAssertTrue(kept.waitForExistence(timeout: 5),
                      "the original picture is not marked as kept")
        snap(app, "4-dog-page")
        // Only until it is in the tree: the page is long with every section
        // open, and a lazily drawn list has no button above the screen until
        // it is scrolled to — a fixed twelve swipes ran out (flaky, QA 10-01).
        let play = app.buttons["Play it on the whole screen"].firstMatch
        for _ in 0..<30 where !play.exists { app.swipeDown() }
        if !play.waitForExistence(timeout: 5) {
            snap(app, "debug-no-play")
        }
        XCTAssertTrue(play.exists, "the word's page lost its Play button")
        play.tap()                                  // XCTest scrolls it into view
        Thread.sleep(forTimeInterval: 1.2)
        snap(app, "5-dog-running")
    }

    /// The page folds (Gil, 2026-10-01: too much scrolling to find the right
    /// thing): started closed, the headings are its table of contents, the
    /// magic words are a short scroll away, and a heading opens its section.
    func testTheEasterEggPageFolds() throws {
        let app = XCUIApplication()
        app.launchArguments = ["-serverURL", "127.0.0.1:59999", "-settingsFold.start", "closed"]
        app.launch()
        let allow = XCUIApplication(bundleIdentifier: "com.apple.springboard").buttons["Allow"]
        if allow.waitForExistence(timeout: 3) { allow.tap() }
        app.buttons["tab-settings"].firstMatch.tap()
        let fun = app.buttons["fold-Just for fun"].firstMatch
        for _ in 0..<6 where !fun.isHittable { app.swipeUp() }
        fun.tap()
        let row = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "Easter egg")).firstMatch
        for _ in 0..<6 where !row.isHittable { app.swipeUp() }
        row.tap()

        let when = app.buttons["fold-egg.When"].firstMatch
        for _ in 0..<4 where !when.isHittable { app.swipeUp() }
        XCTAssertTrue(when.waitForExistence(timeout: 5))
        XCTAssertEqual(when.value as? String, "closed")
        XCTAssertFalse(app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "Show it")).firstMatch.exists,
                       "a closed section still shows its rows")
        snap(app, "10-egg-folded")
        // Closed, the magic words are a few swipes away, not fourteen.
        let dog = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "German Shepherd")).firstMatch
        for _ in 0..<5 where !dog.isHittable { app.swipeUp() }
        XCTAssertTrue(dog.isHittable, "the magic words are still a long scroll down")
        for _ in 0..<5 where !when.isHittable { app.swipeDown() }
        when.tap()
        XCTAssertTrue(app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "Show it")).firstMatch
                        .waitForExistence(timeout: 5), "opening When did not show its rows")
        snap(app, "11-egg-when-open")
        when.tap()                                  // as it was, for the next run
    }

    /// "The path I drew": pick it, trace a route with a finger, save, play.
    func testDrawingAPath() throws {
        let app = XCUIApplication()
        app.launchArguments = ["-serverURL", "127.0.0.1:59999", "-settingsFold.start", "open"]
        app.launch()
        let allow = XCUIApplication(bundleIdentifier: "com.apple.springboard").buttons["Allow"]
        if allow.waitForExistence(timeout: 3) { allow.tap() }
        app.buttons["tab-settings"].firstMatch.tap()
        let row = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "Easter egg")).firstMatch
        for _ in 0..<6 where !row.isHittable { app.swipeUp() }
        row.tap()
        let dog = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "German Shepherd")).firstMatch
        for _ in 0..<14 where !dog.isHittable { app.swipeUp() }
        dog.tap()

        let motion = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "Motion, ")).firstMatch
        for _ in 0..<6 where !motion.isHittable { app.swipeUp() }
        motion.tap()
        let drawnChoice = app.buttons["The path I drew"].firstMatch
        XCTAssertTrue(drawnChoice.waitForExistence(timeout: 5), "no drawn-path motion in the menu")
        drawnChoice.tap()
        // "Redraw" if an earlier run left a path saved.
        let draw = app.buttons.matching(NSPredicate(format: "label ENDSWITH %@", "raw the path…")).firstMatch
        for _ in 0..<3 where !draw.isHittable { app.swipeUp() }
        XCTAssertTrue(draw.waitForExistence(timeout: 5))
        snap(app, "6-motion-options")
        draw.tap()

        // A loop-the-loop: across, up, round and back down.
        let stage = app.windows.firstMatch
        let a = stage.coordinate(withNormalizedOffset: CGVector(dx: 0.2, dy: 0.7))
        let b = stage.coordinate(withNormalizedOffset: CGVector(dx: 0.55, dy: 0.3))
        a.press(forDuration: 0.1, thenDragTo: b, withVelocity: .slow, thenHoldForDuration: 0.1)
        Thread.sleep(forTimeInterval: 1.5)
        snap(app, "7-drawn-path")
        let save = app.buttons["Save"].firstMatch
        XCTAssertTrue(save.isEnabled, "drawing a path did not enable Save")
        save.tap()
        XCTAssertTrue(app.buttons["Redraw the path…"].firstMatch.waitForExistence(timeout: 5),
                      "the path was not saved")
        // Put it back as it was, for the next run.
        for _ in 0..<3 where !motion.isHittable { app.swipeDown() }
        motion.tap()
        app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "Its own")).firstMatch.tap()
        XCTAssertTrue(app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "Motion, Its own"))
                        .firstMatch.waitForExistence(timeout: 5), "the motion was not put back")
    }

    /// The loading screen builder: pick a style, and see the "taking a while" screen.
    func testTheLoadingScreenBuilder() throws {
        let app = XCUIApplication()
        app.launchArguments = ["-serverURL", "127.0.0.1:59999", "-settingsFold.start", "open"]
        app.launch()
        let allow = XCUIApplication(bundleIdentifier: "com.apple.springboard").buttons["Allow"]
        if allow.waitForExistence(timeout: 3) { allow.tap() }
        app.buttons["tab-settings"].firstMatch.tap()
        let row = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "Easter egg")).firstMatch
        for _ in 0..<6 where !row.isHittable { app.swipeUp() }
        row.tap()
        let loader = app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "Loading screen")).firstMatch
        for _ in 0..<14 where !loader.isHittable { app.swipeUp() }
        XCTAssertTrue(loader.waitForExistence(timeout: 5), "no Loading screen row")
        loader.tap()
        XCTAssertTrue(app.switches["Use my loading screen"].firstMatch.waitForExistence(timeout: 5))
        snap(app, "8-loader-builder")
        let wheel = app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "Wheel of friends")).firstMatch
        if wheel.waitForExistence(timeout: 3) { wheel.tap() }
        let stuckLine = app.descendants(matching: .any).matching(NSPredicate(format: "label == %@", "Still working on it…"))
        let before = stuckLine.count
        app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "taking a while")).firstMatch.tap()
        Thread.sleep(forTimeInterval: 1.2)
        snap(app, "9-loader-stuck")
        // The overlay is a window of its own, above the Settings sheet.
        XCTAssertGreaterThan(stuckLine.count, before, "the “taking a while” screen did not appear")
        // Back to the default style for the next run.
        let hamster = app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "Hamster wheel")).firstMatch
        Thread.sleep(forTimeInterval: 3.5)
        if hamster.exists { hamster.tap() }
    }

    /// "Suggest words" (TASKS 49): real suggestions arrive from the on-device
    /// model, each can be ticked, and "Add N chosen" counts them.
    func testSuggestWordsOffersWordsToPickFrom() throws {
        let app = XCUIApplication()
        app.launchArguments = ["-serverURL", "127.0.0.1:59999", "-settingsFold.start", "open"]
        app.launch()
        let allow = XCUIApplication(bundleIdentifier: "com.apple.springboard").buttons["Allow"]
        if allow.waitForExistence(timeout: 3) { allow.tap() }
        app.buttons["tab-settings"].firstMatch.tap()
        let row = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "Easter egg")).firstMatch
        for _ in 0..<6 where !row.isHittable { app.swipeUp() }
        row.tap()
        let dog = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "German Shepherd")).firstMatch
        for _ in 0..<16 where !dog.isHittable { app.swipeUp() }
        dog.tap()
        let suggest = app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "Suggest words")).firstMatch
        for _ in 0..<6 where !suggest.isHittable { app.swipeUp() }
        suggest.tap()
        let yes = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "Yes to")).firstMatch
        let problem = app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", "came back")).firstMatch
        let deadline = Date().addingTimeInterval(60)
        while Date() < deadline && !yes.exists && !problem.exists { Thread.sleep(forTimeInterval: 1) }
        snap(app, "10-suggestions")
        guard yes.exists else {
            // The simulator lacks the data for Apple's safety classifier, so every
            // on-device model call fails there (SensitiveContentAnalysisML 15);
            // a real iPhone with Apple Intelligence has it.
            throw XCTSkip("no model answered on this simulator: \(problem.exists ? problem.label : "nothing")")
        }
        yes.tap()
        XCTAssertTrue(app.buttons["Add 1 chosen"].firstMatch.waitForExistence(timeout: 3))
        XCTAssertTrue(app.buttons["Add 1 chosen"].firstMatch.isEnabled)
        app.buttons["Cancel"].firstMatch.tap()
    }

    /// One word, one thing: adding a word another object has asks first, and
    /// "Keep it where it is" adds nothing.
    func testATakenWordAsksKeepOrMove() throws {
        let app = XCUIApplication()
        app.launchArguments = ["-serverURL", "127.0.0.1:59999", "-settingsFold.start", "open"]
        app.launch()
        let allow = XCUIApplication(bundleIdentifier: "com.apple.springboard").buttons["Allow"]
        if allow.waitForExistence(timeout: 3) { allow.tap() }
        app.buttons["tab-settings"].firstMatch.tap()
        let row = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "Easter egg")).firstMatch
        for _ in 0..<6 where !row.isHittable { app.swipeUp() }
        row.tap()
        let dog = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "German Shepherd")).firstMatch
        for _ in 0..<16 where !dog.isHittable { app.swipeUp() }
        dog.tap()
        let field = app.textFields["Add a word"].firstMatch
        for _ in 0..<6 where !field.isHittable { app.swipeUp() }
        field.tap()
        field.typeText("cat\n")          // Return submits, as the Add button does
        let alert = app.alerts.firstMatch
        XCTAssertTrue(alert.waitForExistence(timeout: 5), "no keep-or-move question")
        XCTAssertTrue(alert.label.contains("taken") || alert.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", "Cat")).count > 0)
        snap(app, "11-word-taken")
        alert.buttons["Keep it where it is"].tap()
        XCTAssertFalse(app.staticTexts["cat"].exists, "cat was added although the user kept it on Cat")
    }

    /// A library drawing as a magic word's graphic: the editor opens, previews,
    /// and saves it onto the object. (Emoji until 2026-10-01 — the picks are
    /// GraphicsLibrary drawings now.)
    func testADrawingBecomesAGraphic() throws {
        let app = XCUIApplication()
        app.launchArguments = ["-serverURL", "127.0.0.1:59999", "-settingsFold.start", "open"]
        app.launch()
        let allow = XCUIApplication(bundleIdentifier: "com.apple.springboard").buttons["Allow"]
        if allow.waitForExistence(timeout: 3) { allow.tap() }
        app.buttons["tab-settings"].firstMatch.tap()
        let row = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "Easter egg")).firstMatch
        for _ in 0..<6 where !row.isHittable { app.swipeUp() }
        row.tap()
        let dog = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "German Shepherd")).firstMatch
        for _ in 0..<16 where !dog.isHittable { app.swipeUp() }
        dog.tap()
        let add = app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "drawing, symbol or letters")).firstMatch
        for _ in 0..<6 where !add.isHittable { app.swipeUp() }
        add.tap()
        let cool = app.buttons["cool"].firstMatch
        XCTAssertTrue(cool.waitForExistence(timeout: 5), "no drawing picks")
        cool.tap()
        snap(app, "12-drawing-editor")
        app.buttons["Save"].firstMatch.tap()
        let saved = app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", "Drawing: cool")).firstMatch
        for _ in 0..<6 where !saved.exists { app.swipeDown() }
        XCTAssertTrue(saved.waitForExistence(timeout: 5), "the drawing was not added to the dog")
        // Leave the dog as it was: the other tests (and the demo) expect it.
        // Each deleted row is waited out before the next check: the count
        // still sees a row while it animates away, and swiping that row fails.
        let rows = app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", "Drawing: cool"))
        for _ in 0..<4 {
            let row = rows.firstMatch
            guard row.waitForExistence(timeout: 2) else { break }
            row.swipeLeft()
            app.buttons["Delete"].firstMatch.tap()
            _ = row.waitForNonExistence(timeout: 5)
        }
        XCTAssertEqual(rows.count, 0, "the test's drawing was left on the dog")
    }
}
