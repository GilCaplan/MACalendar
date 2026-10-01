import Foundation
import Security

/// Who is signed in on this phone (DEVQA Q65: login everywhere; each person
/// has their own calendar and to-dos; a phone can switch between people).
///
/// The session token is a BEARER CREDENTIAL, so it lives in the Keychain the
/// way the device token does (`kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`:
/// off backups, off other devices). The user's public record rides in
/// `UserDefaults` so the app can say who it is signed in as while offline.
///
/// Sign-in is asked for only when it can be DONE: the Mac is reachable, it
/// has users, and this phone has no valid session. An offline phone never
/// locks its person out of the calendar it already has.
struct SessionUser: Codable, Equatable {
    let id: String
    let username: String
    let displayName: String
    let role: String
    let color: String
    var mustChangePassword: Bool

    var isAdmin: Bool { role == "admin" }

    enum CodingKeys: String, CodingKey {
        case id, username, role, color
        case displayName = "display_name"
        case mustChangePassword = "must_change_password"
    }
}

@MainActor
final class UserSession: ObservableObject {
    static let shared = UserSession()

    @Published private(set) var user: SessionUser?
    /// Show the sign-in screen.
    @Published var needsSignIn = false
    /// Does the Mac have users? Remembered, so a phone that has seen it once
    /// never asks for anyone's data before someone signs in (APIClient.request).
    @Published private(set) var serverHasUsers: Bool =
        UserDefaults.standard.bool(forKey: "macalendar.server_has_users") {
        didSet { UserDefaults.standard.set(serverHasUsers, forKey: "macalendar.server_has_users") }
    }

    /// "Group shared to-dos by person" (DEVQA Q65/Q67), held HERE rather than
    /// read by Tasks on appear: the tabs are layers kept alive, so Tasks'
    /// `onAppear` runs once per launch and a change made on the Account tab
    /// never reached it (Gil, 2026-09-28: switching it off changed nothing).
    @Published var groupSharedTodos: Bool =
        UserDefaults.standard.bool(forKey: "macalendar.group_shared_todos") {
        didSet { UserDefaults.standard.set(groupSharedTodos, forKey: "macalendar.group_shared_todos") }
    }

    private static let tokenAccount = "macalendar.session_token"
    private static let userKey = "macalendar.session_user"
    private static let recentKey = "macalendar.recent_users"

    /// People who have signed in on THIS device, most recent first (Gil,
    /// 2026-10-01: make switching easy) — names to tap instead of a username
    /// to type. Never a password: those stay with the Mac.
    @Published private(set) var recent: [SessionUser] = {
        guard let data = UserDefaults.standard.data(forKey: "macalendar.recent_users"),
              let list = try? JSONDecoder().decode([SessionUser].self, from: data) else { return [] }
        var seen = Set<String>()
        return list.filter { seen.insert($0.username).inserted }
    }()

    func forget(_ username: String) {
        recent.removeAll { $0.username == username }
        UserDefaults.standard.set(try? JSONEncoder().encode(recent), forKey: Self.recentKey)
    }

    private func remember(_ u: SessionUser) {
        recent.removeAll { $0.id == u.id || $0.username == u.username }   // one name, once
        recent.insert(u, at: 0)
        recent = Array(recent.prefix(6))
        UserDefaults.standard.set(try? JSONEncoder().encode(recent), forKey: Self.recentKey)
    }

    private init() {
        #if DEBUG
        // Simulator checks only (UI automation does not run on this Mac): a
        // session issued by a scratch server, handed in at launch.
        if let t = ProcessInfo.processInfo.environment["MACALENDAR_UITEST_SESSION"], !t.isEmpty {
            Self.saveToken(t)
        }
        #endif
        if let data = UserDefaults.standard.data(forKey: Self.userKey),
           let u = try? JSONDecoder().decode(SessionUser.self, from: data) {
            user = u
        }
    }

    // MARK: - token

    nonisolated static var token: String {
        let q: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "MACalendar",
            kSecAttrAccount as String: tokenAccount,
            kSecReturnData as String: true,
        ]
        var out: CFTypeRef?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess,
              let data = out as? Data, let s = String(data: data, encoding: .utf8)
        else { return "" }
        return s
    }

    private static func saveToken(_ token: String?) {
        let base: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "MACalendar",
            kSecAttrAccount as String: tokenAccount,
        ]
        SecItemDelete(base as CFDictionary)
        guard let token, !token.isEmpty else { return }
        var add = base
        add[kSecValueData as String] = Data(token.utf8)
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        SecItemAdd(add as CFDictionary, nil)
    }

    private func adopt(_ u: SessionUser?) {
        user = u
        if let u, let data = try? JSONEncoder().encode(u) {
            UserDefaults.standard.set(data, forKey: Self.userKey)
        } else {
            UserDefaults.standard.removeObject(forKey: Self.userKey)
        }
        // Each person's offline copy is their own (LocalStore). Only the ADMIN
        // takes over a pre-users cache — that data was his (the Mac's migration
        // gave him the same).
        LocalStore.shared.switchUser(u?.id, mayClaimLegacy: u?.isAdmin ?? false)
    }

    // MARK: - the three moves

    func signIn(username: String, password: String, api: APIClient) async throws {
        let body: [String: Any] = ["username": username, "password": password,
                                   "source": "ios", "device_id": APIClient.deviceID,
                                   "label": "iPhone"]
        let data = try await api.request("/auth/login", method: "POST", body: body)
        guard let got = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let token = got["session_token"] as? String,
              let userObj = got["user"],
              let u = try? JSONDecoder().decode(SessionUser.self,
                                                from: JSONSerialization.data(withJSONObject: userObj))
        else { throw APIError.serverError("The Mac's answer to sign-in was not understood") }
        Self.saveToken(token)
        adopt(u)
        remember(u)
        needsSignIn = false
        api.requestRefresh()
    }

    /// Switch to someone else WITHOUT signing out first: the new person signs
    /// in, and only then is the old sign-in ended on the Mac — so a wrong
    /// password or Cancel leaves this device exactly as it was, and no stale
    /// sign-in is left behind in "Signed-in devices".
    func switchTo(username: String, password: String, api: APIClient) async throws {
        let old = Self.token
        try await signIn(username: username, password: password, api: api)
        if !old.isEmpty, old != Self.token { await api.endSession(token: old) }
    }

    func signOut(api: APIClient) async {
        _ = try? await api.request("/auth/logout", method: "POST", body: [:])
        Self.saveToken(nil)
        adopt(nil)
        needsSignIn = true
    }

    /// Ask the Mac who this phone is. Decides whether to show sign-in.
    func refresh(api: APIClient) async {
        do {
            let data = try await api.request("/auth/me")
            guard let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
            let loggedIn = (obj["logged_in"] as? Bool) ?? false
            serverHasUsers = true
            if loggedIn, let u = try? JSONDecoder().decode(
                SessionUser.self, from: JSONSerialization.data(withJSONObject: obj)) {
                if u != user { adopt(u) }
                needsSignIn = false
            } else {
                // The Mac has users and nobody is signed in here.
                needsSignIn = true
            }
        } catch APIError.serverError(let msg) where msg.contains("no users yet") {
            needsSignIn = false          // a Mac from before users: nothing to sign in to
            serverHasUsers = false
        } catch APIError.serverError(let msg) where msg.contains("login required") {
            unauthorized()
        } catch {
            // offline: keep whoever was signed in, ask nothing
        }
    }

    /// Any request answered 401 "login required": the session is gone.
    func unauthorized() {
        Self.saveToken(nil)
        needsSignIn = true
    }

    func passwordChanged() {
        if var u = user { u.mustChangePassword = false; adopt(u) }
    }
}
