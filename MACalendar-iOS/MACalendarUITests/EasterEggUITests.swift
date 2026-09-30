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
        app.launchArguments = ["-serverURL", "127.0.0.1:59999"]
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
        for _ in 0..<4 where !app.buttons["Play it on the whole screen"].firstMatch.isHittable { app.swipeDown() }
        app.buttons["Play it on the whole screen"].firstMatch.tap()
        Thread.sleep(forTimeInterval: 1.2)
        snap(app, "5-dog-running")
    }

    /// "The path I drew": pick it, trace a route with a finger, save, play.
    func testDrawingAPath() throws {
        let app = XCUIApplication()
        app.launchArguments = ["-serverURL", "127.0.0.1:59999"]
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

        let motion = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "Motion")).firstMatch
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
}
