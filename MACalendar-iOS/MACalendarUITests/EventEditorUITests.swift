import XCTest

/// The event editor's destructive path: confirming a delete must not send your
/// thumb across the screen.
///
/// `confirmationDialog` renders as a POPOVER here, and a popover is anchored to
/// whatever view the modifier is attached to. Attached to the form it came up
/// against the navigation bar — so deleting meant reaching from the Delete
/// Event button at the bottom of a long scroll, up to the top of the screen,
/// and back (Gil, 2026-09-18, with a screenshot). Attached to the button, it
/// comes up beside the control already under your thumb.
///
/// That is worth pinning rather than eyeballing: moving the modifier back onto
/// the form would still compile, would fail no other test, and would look
/// entirely normal in review.
///
/// **The event this drives is created and destroyed by the test.** It is made
/// through the Mac's own API, deleted through the UI (which is the behaviour
/// under test), and swept in teardown if any of that failed — the calendar
/// this borrows is the real one, so it does not get to keep anything.
final class EventEditorUITests: XCTestCase {

    private lazy var title = "UITest delete \(UUID().uuidString.prefix(6))"
    /// 08:00, because `DayView` opens the timeline at 07:00 anchored to the
    /// top — an 04:00 block is above the fold on arrival and was never
    /// hittable, which failed as "the editor did not open".
    private let hour = "04:00"
    private var createdId: Int?

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

    override func setUp() {
        super.setUp()
        continueAfterFailure = false
    }

    override func tearDown() {
        // Belt and braces: the test deletes this through the UI on the happy
        // path, so this only fires when something went wrong earlier.
        if let id = createdId { _ = send("/events/\(id)", method: "DELETE", body: nil) }
        super.tearDown()
    }

    func testTheDeleteConfirmationComesUpBesideTheDeleteButton() throws {
        let today = ISO8601DateFormatter.day.string(from: Date())
        guard let made = send("/events", method: "POST", body: [
            "title": title, "date": today, "start_time": hour, "end_time": "05:00"
        ]), let id = made["id"] as? Int else {
            throw XCTSkip("the Mac at \(realServer) is not answering, so there is nothing to drive")
        }
        createdId = id

        let app = XCUIApplication()
        app.launchArguments = ["-serverURL", realServer]
        app.launch()

        app.buttons["Day"].firstMatch.tap()

        // The day view opens at the working day, so an 04:00 block starts above
        // the fold. Swipe back up the timeline to reach it.
        let block = app.staticTexts[title].firstMatch
        XCTAssertTrue(block.waitForExistence(timeout: 20), "the event never reached the phone")

        // Tap until the editor is up, rather than once and hopefully.
        //
        // A block sharing its hour with another of the day's events is
        // STACKED — where the first tap POPS the stack and only the second
        // opens the event (`DayView`: `if it.stackSize > 1 && !isPopped`).
        // Swipes are scoped to the timeline rather than sent to the whole app,
        // which at screen edges reaches Notification Center instead.
        for _ in 0..<10 where !block.isHittable { app.swipeDown() }
        XCTAssertTrue(block.isHittable, "could not scroll the event into reach")
        block.tap()
        XCTAssertTrue(app.navigationBars["Edit Event"].waitForExistence(timeout: 30),
                      "the editor did not open")

        // SCROLL, THEN WAIT — not the other way round. `Form` renders its rows
        // lazily, so a row below the fold is not in the accessibility tree at
        // all: waiting for "Delete Event" to exist before scrolling waits
        // forever while the editor sits open on screen, which is exactly how
        // this test failed for half an hour. Verified by dumping the tree and
        // photographing the simulator at the same instant — the dump had the
        // "Edit Event" navigation bar and no Delete Event anywhere in it.
        let deleteButton = app.buttons["Delete Event"].firstMatch
        var reached = false
        for _ in 0..<12 {
            if deleteButton.exists && deleteButton.isHittable { reached = true; break }
            app.swipeUp()
        }
        XCTAssertTrue(reached, "Delete Event never came into reach")

        let anchor = deleteButton.frame
        deleteButton.tap()

        let confirm = app.buttons["Delete"].firstMatch
        XCTAssertTrue(confirm.waitForExistence(timeout: 5), "the confirmation never appeared")

        // THE ASSERTION. Anchored to the form the confirmation sat against the
        // navigation bar, most of a screen from the button that raised it. A
        // third of the screen is a wide bound that still fails loudly on that.
        let gap = abs(confirm.frame.midY - anchor.midY)
        let tolerance = app.frame.height / 3
        // In the log, so a passing run still says how far apart they are — the
        // old placement measured 638pt on an 874pt screen.
        XCTContext.runActivity(named: "confirmation sits \(Int(gap))pt from the button") { _ in }
        add(XCTAttachment(screenshot: XCUIScreen.main.screenshot()))
        XCTAssertLessThan(gap, tolerance,
                          "the confirmation is \(Int(gap))pt from the Delete Event button on a "
                          + "\(Int(app.frame.height))pt screen — it is anchored to the form again, "
                          + "not to the button")

        // Go through with it: the delete is the behaviour under test AND the
        // cleanup, so the two are the same action.
        confirm.tap()
        XCTAssertTrue(app.buttons["Day"].firstMatch.waitForExistence(timeout: 10),
                      "the editor did not close after deleting")

        var goneFromTheMac = false
        for _ in 0..<20 {
            Thread.sleep(forTimeInterval: 0.5)
            if send("/events/\(id)", method: "GET", body: nil) == nil { goneFromTheMac = true; break }
        }
        XCTAssertTrue(goneFromTheMac, "the event is still on the Mac after confirming the delete")
        createdId = nil
    }

    // MARK: - Talking to the Mac

    /// Returns the decoded body on 2xx, nil on anything else — including the
    /// 404 that tells us a delete stuck.
    @discardableResult
    private func send(_ path: String, method: String, body: [String: Any]?) -> [String: Any]? {
        guard let url = URL(string: "http://\(realServer)\(path)") else { return nil }
        var req = URLRequest(url: url)
        req.httpMethod = method
        req.timeoutInterval = 10
        if let body {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try? JSONSerialization.data(withJSONObject: body)
        }
        var out: [String: Any]? = nil
        let done = DispatchSemaphore(value: 0)
        URLSession.shared.dataTask(with: req) { data, response, _ in
            defer { done.signal() }
            guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode),
                  let data else { return }
            out = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
        }.resume()
        _ = done.wait(timeout: .now() + 15)
        return out
    }
}

private extension ISO8601DateFormatter {
    static let day: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()
}
