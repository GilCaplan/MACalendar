import XCTest

/// Watch a row actually survive the offline → reconnect round trip.
///
/// The Coursework data-loss fix (`bbe7892`) was proven by reading the Swift and
/// by server-side unit tests; nobody had seen a course go out to the Mac and
/// stay deleted. That mattered, because fixing it turned up three things the
/// existing tests could not have caught — a temp-id collision, placeholder ids
/// travelling inside queued bodies, and duplicate-on-replay. This drives the
/// real app against a real Mac and asserts the outcome the user reported.
///
/// ## How the Mac is taken away without touching the app
///
/// `UserDefaults` reads `-key value` pairs out of the ARGUMENT DOMAIN, which
/// wins over anything on disk. `AppSettings.init` reads `serverURL` from
/// `UserDefaults.standard`, so launching with
///
///     -serverURL 127.0.0.1:59999
///
/// points the app at a closed port: every request fails with a connection
/// refused, which is exactly the `URLError` an absent Mac produces, and
/// `APIClient.mutate` queues the write. Relaunching with the real address
/// brings the Mac back. Nothing in the app is modified, mocked or stubbed —
/// this is the genuine `mutate` → `LocalStore.enqueue` → `syncPending` path.
///
/// The real address is NOT written here: it arrives in this bundle's own
/// Info.plist as `MACalendarServerURL`, injected from `MACALENDAR_SERVER_URL`
/// in `Base.xcconfig` / the gitignored `Local.xcconfig`, the same way the app
/// gets it. `MACalendar-iOS/Base.xcconfig` explains why an address that names
/// one laptop does not live in the repository.
///
/// ## What proves what
///
/// The offline banner is the queue's only on-screen reading — "Offline — N
/// changes pending sync" versus "Offline — changes saved locally" — so an
/// offline relaunch after a reconnect says whether the Mac ACCEPTED the queued
/// write or whether it is still sitting there. The Mac's own copy is checked
/// by `scripts/offline_sync_check.sh`, which runs this test and then curls
/// `GET /courses`; a UI test cannot reach the Mac's database itself.
final class OfflineSyncUITests: XCTestCase {

    /// A port nothing listens on. Connection refused is indistinguishable, to
    /// `APIClient`, from a Mac that is asleep.
    private static let unreachable = "127.0.0.1:59999"

    /// The course this run creates. Unique so concurrent or repeated runs can
    /// never see each other's row, and so the driver script can look for
    /// exactly this one on the Mac. `TEST_RUNNER_MACALENDAR_UITEST_COURSE=…`
    /// in xcodebuild's environment reaches us with the prefix stripped, which
    /// is how the driver gets to know the name before the test runs.
    private lazy var courseName: String = {
        ProcessInfo.processInfo.environment["MACALENDAR_UITEST_COURSE"]
            ?? "UITest \(UUID().uuidString.prefix(8))"
    }()

    /// Where the Mac really is. The test bundle's Info.plist first (built from
    /// the xcconfig), an environment override second, loopback last — the
    /// simulator shares the host's network stack, so `127.0.0.1:8080` is the
    /// Mac's own API when this runs on the machine serving it.
    private var realServer: String {
        if let env = ProcessInfo.processInfo.environment["MACALENDAR_UITEST_SERVER"],
           !env.trimmingCharacters(in: .whitespaces).isEmpty {
            return env
        }
        let fromPlist = Bundle(for: Self.self)
            .object(forInfoDictionaryKey: "MACalendarServerURL") as? String ?? ""
        let trimmed = fromPlist.trimmingCharacters(in: .whitespaces)
        return trimmed.isEmpty ? "127.0.0.1:8080" : trimmed
    }

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    // MARK: - The scenario

    /// One method, not five: every step depends on the state the last one left
    /// on disk, and XCTest gives no ordering guarantee between methods.
    func testCourseAddedOfflineReachesTheMacAndADeleteOfflineStaysDeleted() throws {
        // 1 — the Mac is away. Add a course.
        var app = openCoursework(server: Self.unreachable)
        addCourse(app)
        XCTAssertTrue(courseIsListed(app),
                      "the course must be on screen the moment it is added, Mac or no Mac")
        XCTAssertTrue(bannerSaysPending(app),
                      "a write made with the Mac away must be IN THE QUEUE, not lost — "
                      + "the banner reads: \(bannerLabel(app) ?? "no banner at all")")

        // 2 — still away, relaunched. It must come from the local cache, not
        //     from the screen it was typed into.
        app = openCoursework(server: Self.unreachable)
        XCTAssertTrue(courseIsListed(app),
                      "the course must survive a relaunch with the Mac still away")
        XCTAssertTrue(bannerSaysPending(app),
                      "the queued create must survive a relaunch too")

        // 3 — the Mac comes back. The queue flushes.
        app = openCoursework(server: realServer)
        waitForOnline(app)
        settle(seconds: 20)     // syncPending runs on scene activation

        // 4 — offline again, to READ the queue: empty means the Mac took it.
        app = openCoursework(server: Self.unreachable)
        XCTAssertFalse(bannerSaysPending(app),
                       "after a reconnect the queued create must be gone from the queue — "
                       + "the banner still reads: \(bannerLabel(app) ?? "no banner at all")")
        XCTAssertTrue(courseIsListed(app),
                      "the course must still be here after the round trip")

        // 5 — the reported bug. Delete it while the Mac is away…
        deleteCourse(app)
        XCTAssertFalse(courseIsListed(app, waiting: 3),
                       "a course deleted offline must leave the screen")
        XCTAssertTrue(bannerSaysPending(app),
                      "the delete must be QUEUED — the `try?` this replaced swallowed it, "
                      + "and the next sync downloaded the row again")

        // …reconnect, and it must stay deleted.
        app = openCoursework(server: realServer)
        waitForOnline(app)
        settle(seconds: 20)
        XCTAssertFalse(courseIsListed(app, waiting: 5),
                       "THE BUG: the course came back after reconnecting, so the delete "
                       + "was lost and the next sync re-downloaded the row")

        // 6 — and the queue is empty, which is what says the Mac was told.
        app = openCoursework(server: Self.unreachable)
        XCTAssertFalse(bannerSaysPending(app),
                       "the queued delete must have been accepted by the Mac — "
                       + "the banner still reads: \(bannerLabel(app) ?? "no banner at all")")
        XCTAssertFalse(courseIsListed(app, waiting: 3),
                       "the course must be gone from the local cache as well")
    }

    /// The premise, checked on its own: `-serverURL <dead port>` really does
    /// take the Mac away. If this fails, every "offline" step above was
    /// quietly running against a reachable Mac and proving nothing.
    func testADeadPortArgumentReallyTakesTheMacAway() throws {
        let app = launch(server: Self.unreachable)
        XCTAssertTrue(app.staticTexts["offline-banner"].waitForExistence(timeout: 30),
                      "the app did not go offline when pointed at a closed port")
    }

    // MARK: - Launching

    private func launch(server: String) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = [
            "-serverURL", server,
            // Not test hooks — ordinary preferences, set through the argument
            // domain so neither one interrupts the run: the vocabulary
            // onboarding sheet opens over everything on the first reachable
            // launch, and reminders ask for notification permission.
            "-vocabOnboardingDone", "1",
            "-remindersEnabled", "0",
        ]
        app.launch()
        dismissSystemAlertIfPresent()
        return app
    }

    /// Launch and land on the Coursework tab, switching it on if this install
    /// or this Mac has it hidden (`features.coursework` is off in the Mac's
    /// config). The toggle is the app's own Settings switch, so it queues or
    /// travels like any other write.
    private func openCoursework(server: String) -> XCUIApplication {
        var app = launch(server: server)
        if !app.buttons["tab-coursework"].waitForExistence(timeout: 15) {
            enableCourseworkTab(app)
            // Relaunching beats dismissing the sheet: the Settings sheet has no
            // Done button (it is swipe-to-dismiss), and the switch has already
            // persisted itself.
            app = launch(server: server)
            XCTAssertTrue(app.buttons["tab-coursework"].waitForExistence(timeout: 20),
                          "the Coursework tab did not appear after switching it on")
        }
        app.buttons["tab-coursework"].tap()
        XCTAssertTrue(app.navigationBars["Coursework"].waitForExistence(timeout: 10),
                      "the Coursework tab did not open")
        return app
    }

    /// Switch the Coursework tab on from the app's own Settings.
    ///
    /// `features.coursework` is off in the Mac's config, and the app adopts the
    /// Mac's answer, so on any machine where this app has ever been online the
    /// tab starts hidden. Flipping the switch is the real path —
    /// `FeatureVisibility.set` writes locally and then PATCHes
    /// `/features/coursework`, queueing it when the Mac is away — which also
    /// makes the Mac's copy `true`. `scripts/offline_sync_check.sh` puts it
    /// back afterwards.
    private func enableCourseworkTab(_ app: XCUIApplication) {
        app.buttons["tab-settings"].tap()
        let toggle = app.switches["feature-toggle-coursework"]
        // Sections start FOLDED (2026-09-18), so Tabs has to be opened before
        // anything inside it is in the tree at all.
        if !toggle.exists {
            let header = app.buttons["Tabs"].firstMatch
            if header.waitForExistence(timeout: 10) {
                for _ in 0..<10 where !header.isHittable { app.swipeUp() }
                header.tap()
            }
        }
        XCTAssertTrue(toggle.waitForExistence(timeout: 10), "Settings has no Coursework switch")
        for attempt in 1...4 {
            if toggle.value as? String == "1" { return }
            // Settings is a long ScrollView and Tabs is near the end of it, so
            // the row first comes to rest AT THE BOTTOM EDGE — inside the home
            // indicator's gesture strip, which swallows the tap. `isHittable`
            // is true there, which is why scrolling until it says so was not
            // enough: two runs of this test tapped a switch that never moved.
            // Scroll until the row sits in the comfortable middle band.
            scrollIntoComfortableView(toggle, in: app)
            // The switch's own right-hand end, not the element's centre: the
            // accessibility frame is the whole row, label and caption included.
            toggle.coordinate(withNormalizedOffset: CGVector(dx: 0.9, dy: 0.5)).tap()
            let on = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == '1'"),
                                               object: toggle)
            if XCTWaiter().wait(for: [on], timeout: 5) == .completed { return }
            XCTAssertNotEqual(attempt, 4, "the Coursework switch did not come on")
        }
    }

    /// Put `element` in the middle of the screen, out of the top and bottom
    /// strips where a synthesised tap is eaten by a system gesture.
    private func scrollIntoComfortableView(_ element: XCUIElement, in app: XCUIApplication) {
        let height = app.windows.firstMatch.frame.height
        for _ in 0..<15 {
            let y = element.frame.midY
            if y > height * 0.2 && y < height * 0.7 { return }
            if y >= height * 0.7 { app.swipeUp() } else { app.swipeDown() }
        }
    }

    // MARK: - The Coursework tab

    private func addCourse(_ app: XCUIApplication) {
        app.buttons["coursework-add-course"].tap()
        let field = app.textFields["course-name-field"]
        XCTAssertTrue(field.waitForExistence(timeout: 10), "the Add Course sheet did not open")
        field.tap()
        field.typeText(courseName)
        app.buttons["course-save"].tap()
    }

    private func deleteCourse(_ app: XCUIApplication) {
        let menu = app.buttons["course-menu-\(courseName)"]
        XCTAssertTrue(scrollTo(menu, in: app), "the course's menu button was not reachable")
        menu.tap()
        let delete = app.buttons["Delete Course"]
        XCTAssertTrue(delete.waitForExistence(timeout: 5), "the course menu has no Delete")
        delete.tap()
    }

    /// Is the course in the list? The Mac has real courses of its own, so the
    /// row can be below the fold — absence is only concluded after scanning.
    private func courseIsListed(_ app: XCUIApplication, waiting: TimeInterval = 8) -> Bool {
        let row = app.staticTexts[courseName]
        if row.waitForExistence(timeout: waiting) { return true }
        return scrollTo(row, in: app, swipes: 10)
    }

    /// Scroll until `element` exists, then leave the list back at the top so
    /// the next step starts where it expects to.
    @discardableResult
    private func scrollTo(_ element: XCUIElement, in app: XCUIApplication, swipes: Int = 10) -> Bool {
        if element.exists { return true }
        for _ in 0..<swipes {
            app.swipeUp()
            if element.exists { return true }
        }
        for _ in 0..<(swipes + 2) { app.swipeDown() }
        return false
    }

    // MARK: - Reading the queue off the screen

    private func bannerLabel(_ app: XCUIApplication) -> String? {
        let banner = app.staticTexts["offline-banner"]
        return banner.waitForExistence(timeout: 20) ? banner.label : nil
    }

    /// True when the banner names a change still waiting to go out. The banner
    /// itself only appears once a request has actually failed, which is why
    /// this waits for it rather than reading it immediately.
    private func bannerSaysPending(_ app: XCUIApplication) -> Bool {
        (bannerLabel(app) ?? "").contains("pending sync")
    }

    private func waitForOnline(_ app: XCUIApplication) {
        // The banner is drawn only while `isOnline` is false; with the Mac back
        // it must never appear. Give the first request time to answer.
        let banner = app.staticTexts["offline-banner"]
        settle(seconds: 8)
        XCTAssertFalse(banner.exists,
                       "the app still believes the Mac is away — \(realServer) unreachable "
                       + "from the simulator? Is `python -m assistant.api` running?")
    }

    private func settle(seconds: TimeInterval) {
        let done = expectation(description: "settle")
        DispatchQueue.main.asyncAfter(deadline: .now() + seconds) { done.fulfill() }
        wait(for: [done], timeout: seconds + 10)
    }

    /// A local-notification permission alert can appear when a write is
    /// refused. It belongs to springboard, not the app, so it is tapped there.
    private func dismissSystemAlertIfPresent() {
        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        for label in ["Allow", "Don't Allow", "OK"] {
            let button = springboard.buttons[label]
            if button.exists && button.isHittable { button.tap(); return }
        }
    }
}
