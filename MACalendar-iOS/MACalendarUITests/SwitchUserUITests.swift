import XCTest

/// Switching accounts on the phone (Gil, 2026-10-01: "make phone account
/// switching more intuitive and easier"): Account ▸ Switch user opens sign-in
/// WITHOUT signing out first; Cancel keeps whoever was signed in; people who
/// used this phone are names to tap.
///
/// Needs the scratch server `scratchpad/users_server.py` on port 59125 (two
/// people, ada and ben). Skips when nothing listens there. Starts as Ada every
/// time — a session from that server, handed in at launch — so a run never
/// depends on where the last one stopped.
final class SwitchUserUITests: XCTestCase {

    override func setUp() { continueAfterFailure = false }

    private let server = "http://127.0.0.1:59125"

    private func login(_ user: String, _ pass: String) -> String? {
        var req = URLRequest(url: URL(string: server + "/auth/login")!)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONSerialization.data(withJSONObject: ["username": user, "password": pass, "source": "test"])
        let sem = DispatchSemaphore(value: 0)
        var token: String?
        URLSession.shared.dataTask(with: req) { d, _, _ in
            if let d, let o = try? JSONSerialization.jsonObject(with: d) as? [String: Any] { token = o["session_token"] as? String }
            sem.signal()
        }.resume()
        _ = sem.wait(timeout: .now() + 5)
        return token
    }

    private func snap(_ app: XCUIApplication, _ name: String) {
        let shot = XCTAttachment(screenshot: app.screenshot())
        shot.name = name
        shot.lifetime = .keepAlways
        add(shot)
    }

    /// The Account page exists twice — under Settings and as its own tab — so
    /// a query matches the hidden copy too: take the one on screen.
    private func visible(_ q: XCUIElementQuery) -> XCUIElement {
        for _ in 0..<12 {
            for i in 0..<q.count where q.element(boundBy: i).isHittable { return q.element(boundBy: i) }
            Thread.sleep(forTimeInterval: 0.5)
        }
        return q.firstMatch
    }

    private func button(_ app: XCUIApplication, _ id: String) -> XCUIElement {
        visible(app.buttons.matching(identifier: id))
    }

    /// iOS offers to save the password after a sign-in; a person says Not Now.
    private func notNow(_ app: XCUIApplication) {
        let b = app.buttons["Not Now"].firstMatch
        if b.waitForExistence(timeout: 3) { b.tap() }
        let sb = XCUIApplication(bundleIdentifier: "com.apple.springboard").buttons["Not Now"].firstMatch
        if sb.exists { sb.tap() }
    }

    func testSwitchingAccounts() throws {
        guard let ada = login("ada", "ada-pass-1") else {
            throw XCTSkip("no scratch users server on 59125 (scratchpad/users_server.py)")
        }
        let app = XCUIApplication()
        app.launchArguments = ["-serverURL", "127.0.0.1:59125", "-serverEnabled", "1", "-phoneOnly", "0",
                               "-vocabOnboardingDone", "1", "-remindersEnabled", "0"]
        app.launchEnvironment = ["MACALENDAR_UITEST_SESSION": ada]
        app.launch()
        let allow = XCUIApplication(bundleIdentifier: "com.apple.springboard").buttons["Allow"]
        if allow.waitForExistence(timeout: 3) { allow.tap() }

        // Settings starts with who you are; that row is the way into Account.
        XCTAssertTrue(app.buttons["tab-settings"].firstMatch.waitForExistence(timeout: 10))
        app.buttons["tab-settings"].firstMatch.tap()
        visible(app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "Ada"))).tap()
        let switchRow = button(app, "switch-user")
        XCTAssertTrue(switchRow.isHittable, "no Switch user at the top of Account")
        snap(app, "1-account-switch-row")

        // Cancel keeps Ada.
        switchRow.tap()
        XCTAssertTrue(app.buttons["switch-cancel"].firstMatch.waitForExistence(timeout: 5), "Switch user did not open sign-in")
        app.buttons["switch-cancel"].firstMatch.tap()
        XCTAssertTrue(button(app, "switch-user").isHittable, "Cancel did not keep the account")
        XCTAssertTrue(app.staticTexts["@ada · admin"].firstMatch.exists || app.staticTexts.matching(
            NSPredicate(format: "label BEGINSWITH %@", "@ada")).firstMatch.exists, "Cancel changed who is signed in")

        // Switch to Ben by typing his name.
        button(app, "switch-user").tap()
        let name = app.textFields["Username"].firstMatch
        XCTAssertTrue(name.waitForExistence(timeout: 5))
        name.tap(); name.typeText("ben")
        let pw = app.secureTextFields["Password"].firstMatch
        pw.tap(); pw.typeText("ben-pass-1\n")
        notNow(app)
        XCTAssertTrue(visible(app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH %@", "@ben"))).waitForExistence(timeout: 8),
                      "did not switch to Ben")
        snap(app, "2-now-ben")

        // And back to Ada with a tap on her name.
        button(app, "switch-user").tap()
        let adaChip = app.buttons["recent-user-ada"].firstMatch
        XCTAssertTrue(adaChip.waitForExistence(timeout: 5), "Ada is not offered as someone who used this phone")
        snap(app, "3-switch-sheet-with-recent")
        adaChip.tap()
        let pw2 = app.secureTextFields["Password"].firstMatch
        pw2.tap(); pw2.typeText("ada-pass-1\n")
        notNow(app)
        XCTAssertTrue(visible(app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH %@", "@ada"))).waitForExistence(timeout: 8),
                      "did not switch back to Ada")
    }
}
