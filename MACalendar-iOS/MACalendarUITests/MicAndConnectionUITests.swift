import XCTest

/// The 2026-10-09/10 surfaces, driven on the real app and photographed:
/// the mic's four recording styles (Settings ▸ Voice & recording ▸ "While
/// recording", the waveform card by default), and the connection strips —
/// off by default, with Settings ▸ Your Mac showing the same facts live.
///
/// The Mac is taken away with a closed port (see OfflineSyncUITests); the
/// queued voice commands come from `MACALENDAR_UITEST_VOICE_RESPONSE`, the
/// same seed QueuedCommandDetail's test uses. The recording tests use the
/// simulator's microphone — in a quiet room the card turning orange ("No
/// sound") after two seconds is the expected picture, not a failure.
final class MicAndConnectionUITests: XCTestCase {

    override func setUp() { continueAfterFailure = false }

    private func shot(_ app: XCUIApplication, _ name: String) {
        let a = XCTAttachment(screenshot: app.screenshot())
        a.name = name
        a.lifetime = .keepAlways
        add(a)
    }

    private func launch(_ extra: [String] = [], seedQueue: Bool = false) throws -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["-serverURL", "127.0.0.1:59999", "-vocabOnboardingDone", "1",
                               "-remindersEnabled", "0", "-reviewBeforeSend", "0",
                               "-settingsFold.start", "open",
                               "-uitestDefaultPrefs"] + extra   // a choice saved by an earlier test is forgotten
        if seedQueue {
            let url = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
                .appendingPathComponent("Fixtures/voice_response_walk_the_dog.json")
            app.launchEnvironment["MACALENDAR_UITEST_VOICE_RESPONSE"] =
                try String(contentsOf: url, encoding: .utf8)
        }
        app.launch()
        allowAlerts()
        return app
    }

    private func allowAlerts() {
        let sb = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        for label in ["Allow", "OK", "Allow While Using App"] where sb.buttons[label].waitForExistence(timeout: 1.5) {
            sb.buttons[label].tap()
        }
    }

    private func mic(_ app: XCUIApplication) -> XCUIElement {
        let all = app.buttons.matching(identifier: "mic-button")
        for i in 0..<all.count where all.element(boundBy: i).isHittable { return all.element(boundBy: i) }
        return all.firstMatch
    }

    /// A Settings row, scrolled to: the list is taller than the screen.
    private func settingsRow(_ app: XCUIApplication, _ title: String) -> XCUIElement {
        let row = app.staticTexts[title].firstMatch
        for _ in 0..<8 where !(row.exists && row.isHittable) { app.swipeUp() }
        XCTAssertTrue(row.waitForExistence(timeout: 3), "no \(title) row in Settings")
        return row
    }

    private func element(_ app: XCUIApplication, _ id: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: id).firstMatch
    }

    /// Tap the mic until it records (the first tap may be the permission).
    private func startRecording(_ app: XCUIApplication, expect id: String) {
        XCTAssertTrue(app.buttons["mic-button"].firstMatch.waitForExistence(timeout: 10), "no mic")
        sleep(2)                                         // let the first screen settle before tapping
        mic(app).tap()
        allowAlerts()
        if !element(app, id).waitForExistence(timeout: 4) { mic(app).tap(); allowAlerts() }
        XCTAssertTrue(element(app, id).waitForExistence(timeout: 5), "recording did not show \(id)")
    }

    // MARK: - The mic

    func testTheDefaultIsTheWaveformCard() throws {
        let app = try launch()
        startRecording(app, expect: "listening-card")
        XCTAssertFalse(element(app, "listening-chip").exists, "card style also drew the chip")
        shot(app, "mic-card-start")
        sleep(3)                                          // past the 2 s "No sound" point
        shot(app, "mic-card-3s")
        app.buttons["Discard recording"].firstMatch.tap()
        XCTAssertFalse(element(app, "listening-card").waitForExistence(timeout: 2), "discard left the card up")
    }

    func testRingsSunburstAndDotsKeepTheSmallChip() throws {
        for style in ["rings", "sunburst", "dots"] {
            let app = try launch(["-micVisual", style])
            startRecording(app, expect: "listening-chip")
            XCTAssertFalse(element(app, "listening-card").exists, "\(style) drew the card")
            sleep(1)
            shot(app, "mic-\(style)")
            app.buttons["Discard recording"].firstMatch.tap()
            app.terminate()
        }
    }

    func testTheStyleIsPickedInVoiceSettings() throws {
        let app = try launch()
        app.buttons["tab-settings"].firstMatch.tap()
        settingsRow(app, "Voice & recording").tap()
        let picker = element(app, "mic-visual-picker")
        XCTAssertTrue(picker.waitForExistence(timeout: 5), "no While recording picker on the Voice page")
        XCTAssertTrue(app.buttons["Card"].firstMatch.isSelected, "Card is not the default")
        app.buttons["Dots"].firstMatch.tap()
        XCTAssertTrue(app.buttons["Dots"].firstMatch.isSelected)
        shot(app, "settings-voice-picker")
    }

    // MARK: - Who transcribes

    /// The phone transcribes its own recording and sends the WORDS (2026-10-10).
    /// Needs a stand-in Mac on 127.0.0.1:59130 that logs what it is sent
    /// (scratchpad fake_mac.py) and speech playing into the Mac's microphone
    /// while it records; the driver reads the log. Skips without the stand-in.
    func testASpokenCommandGoesAsWords() throws {
        let up: Bool = {
            let sem = DispatchSemaphore(value: 0); var ok = false
            URLSession.shared.dataTask(with: URL(string: "http://127.0.0.1:59130/health")!) { _, r, _ in
                ok = (r as? HTTPURLResponse)?.statusCode == 200; sem.signal()
            }.resume()
            _ = sem.wait(timeout: .now() + 3); return ok
        }()
        try XCTSkipUnless(up, "start fake_mac.py on 59130 to run this")
        let app = XCUIApplication()
        app.launchArguments = ["-serverURL", "127.0.0.1:59130", "-vocabOnboardingDone", "1",
                               "-remindersEnabled", "0", "-reviewBeforeSend", "0",
                               "-showThinking", "1", "-stopWordsEnabled", "0",
                               "-silenceStopEnabled", "0", "-uitestDefaultPrefs"]
        app.launch()
        allowAlerts()
        startRecording(app, expect: "listening-card")
        sleep(12)                                         // the driver is speaking
        shot(app, "spoken-heard")
        mic(app).tap()
        // The fake Mac answers "Done (fake Mac)." whichever way it was sent;
        // the driver reads its log for WHICH way (words, or audio when the
        // device has no on-device recognition — the simulator has none).
        let done = app.descendants(matching: .any)
            .matching(NSPredicate(format: "label CONTAINS 'Done (fake Mac)'")).firstMatch
        let ok = done.waitForExistence(timeout: 40)
        shot(app, "spoken-sent")
        XCTAssertTrue(ok, "the command never came back from the fake Mac")
    }

    // MARK: - The connection

    func testNoStripsByDefaultEvenOfflineWithCommandsWaiting() throws {
        let app = try launch(seedQueue: true)
        XCTAssertTrue(app.buttons["mic-button"].firstMatch.waitForExistence(timeout: 10))
        sleep(4)                                          // long enough for the app to learn the Mac is away
        XCTAssertFalse(app.staticTexts["offline-banner"].exists, "the offline strip shows by default")
        XCTAssertFalse(app.buttons.containing(NSPredicate(format: "label CONTAINS 'Show'")).firstMatch.exists,
                       "the queued-commands strip shows by default")
        shot(app, "home-no-strips")
    }

    func testYourMacShowsTheConnectionAndTheQueueLive() throws {
        let app = try launch(seedQueue: true)
        app.buttons["tab-settings"].firstMatch.tap()
        let row = settingsRow(app, "Your Mac")
        shot(app, "settings-your-mac-row")
        row.tap()
        let status = element(app, "connection-status")
        XCTAssertTrue(status.waitForExistence(timeout: 8), "no status card on Your Mac")
        let reached = NSPredicate(format: "label CONTAINS %@", "can't be reached")
        expectation(for: reached, evaluatedWith: status)
        waitForExpectations(timeout: 20)                  // flips once the first request fails
        let voice = element(app, "voice-queue-link")
        XCTAssertTrue(voice.waitForExistence(timeout: 5), "the waiting voice commands are not listed")
        XCTAssertTrue(element(app, "connection-banner-toggle").exists)
        shot(app, "settings-your-mac-card")
        voice.tap()
        XCTAssertTrue(app.navigationBars["Queued commands"].waitForExistence(timeout: 5), "the row did not open the queue")
        shot(app, "settings-voice-queue")
    }

    func testTheSwitchBringsTheStripsBack() throws {
        let app = try launch(["-showConnectionBanner", "1"], seedQueue: true)
        XCTAssertTrue(app.staticTexts["offline-banner"].waitForExistence(timeout: 30), "switch on, strip still hidden")
        XCTAssertTrue(app.buttons.containing(NSPredicate(format: "label CONTAINS 'Show'")).firstMatch.exists)
        shot(app, "home-strips-on")
    }
}
