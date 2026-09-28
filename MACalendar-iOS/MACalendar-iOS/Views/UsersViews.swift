import SwiftUI

// The phone's user screens (DEVQA Q65): sign in, Account & Sharing, and the
// admin's list of users. They talk to the Mac's /auth, /users, /shares and
// /admin routes — the same registry the Mac's own dialogs edit, so the two
// can never disagree.

// MARK: - sign in

struct LoginView: View {
    @EnvironmentObject var api: APIClient
    @EnvironmentObject var settings: AppSettings
    @ObservedObject private var session = UserSession.shared
    @State private var username = ""
    @State private var password = ""
    @State private var error = ""
    @State private var busy = false
    @State private var changePassword = false
    @FocusState private var focus: Field?
    private enum Field { case user, pass }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Spacer()
            Image(systemName: "calendar.circle.fill")
                .font(.system(size: 54))
                .foregroundColor(settings.accentColor)
            Text("Who's using the calendar?")
                .font(.title2.weight(.bold))
            Text("Each person has their own calendar and to-dos.")
                .font(.subheadline).foregroundColor(.secondary)
            VStack(spacing: 10) {
                TextField("Username", text: $username)
                    .textContentType(.username)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .focused($focus, equals: .user)
                    .submitLabel(.next)
                    .onSubmit { focus = .pass }
                SecureField("Password", text: $password)
                    .textContentType(.password)
                    .focused($focus, equals: .pass)
                    .submitLabel(.go)
                    .onSubmit { Task { await signIn() } }
            }
            .padding(12)
            .background(Color(.secondarySystemBackground))
            .cornerRadius(Theme.radiusMD)
            if !error.isEmpty {
                Text(error).font(.footnote).foregroundColor(.red)
            }
            Button { Task { await signIn() } } label: {
                HStack { Spacer(); if busy { ProgressView() } else { Text("Sign in").bold() }; Spacer() }
                    .padding(.vertical, 12)
            }
            .background(settings.accentColor)
            .foregroundColor(Color.onColor(hex: settings.accentColorHex))
            .cornerRadius(Theme.radiusMD)
            .disabled(busy || username.isEmpty || password.isEmpty)
            Spacer()
            Text(api.isOnline ? "Connected to your Mac" : "Your Mac isn't reachable right now")
                .font(.caption).foregroundColor(.secondary)
        }
        .padding(28)
        .onAppear {
            focus = .user
            #if DEBUG
            // Simulator check of the real sign-in path (typing is not automatable here)
            if let creds = ProcessInfo.processInfo.environment["MACALENDAR_UITEST_LOGIN"],
               let colon = creds.firstIndex(of: ":") {
                username = String(creds[..<colon]); password = String(creds[creds.index(after: colon)...])
                Task { await signIn() }
            }
            #endif
        }
        .sheet(isPresented: $changePassword) { ChangePasswordView(forced: true) }
    }

    private func signIn() async {
        busy = true; defer { busy = false }
        error = ""
        do {
            try await session.signIn(username: username, password: password, api: api)
            if session.user?.mustChangePassword == true { changePassword = true }
        } catch APIError.serverError(let msg) {
            error = msg.contains("too many") ? "Too many tries — wait half a minute."
                  : msg.contains("wrong") ? "That username and password don't match."
                  : "The Mac said: \(msg)"
        } catch {
            self.error = "Your Mac isn't reachable. Sign in once it is."
        }
    }
}

// MARK: - password

struct ChangePasswordView: View {
    var forced = false
    @EnvironmentObject var api: APIClient
    @Environment(\.dismiss) private var dismiss
    @State private var current = ""
    @State private var new = ""
    @State private var again = ""
    @State private var error = ""

    var body: some View {
        StackNavigation {
            Form {
                if forced {
                    Text("You're using a password someone else set. Pick your own.")
                        .font(.footnote).foregroundColor(.secondary)
                }
                SecureField("Current password", text: $current)
                SecureField("New password (8+ characters)", text: $new)
                SecureField("Again", text: $again)
                if !error.isEmpty { Text(error).foregroundColor(.red).font(.footnote) }
            }
            .navigationTitle("Change password")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    Button(forced ? "Later" : "Cancel") { dismiss() }
                }
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("Save") { Task { await save() } }
                        .disabled(new.count < 8 || new != again || current.isEmpty)
                }
            }
        }
    }

    private func save() async {
        do {
            _ = try await api.request("/auth/password", method: "POST",
                                      body: ["current": current, "new": new])
            UserSession.shared.passwordChanged()
            dismiss()
        } catch APIError.serverError(let msg) {
            error = msg.contains("wrong") ? "The current password is wrong." : msg
        } catch {
            self.error = error.localizedDescription
        }
    }
}

// MARK: - account & sharing

private struct PublicUser: Decodable, Identifiable {
    let id: String
    let username: String
    let displayName: String
    let color: String
    let role: String
    enum CodingKeys: String, CodingKey {
        case id, username, color, role
        case displayName = "display_name"
    }
}

struct AccountView: View {
    @EnvironmentObject var api: APIClient
    @ObservedObject private var session = UserSession.shared
    @State private var others: [PublicUser] = []
    @State private var sharedIn: [(name: String, color: String, level: String)] = []
    @State private var groupByOwner = false
    @State private var settingError = ""
    @State private var showPassword = false
    @State private var loaded = false

    var body: some View {
        Form {
            if let u = session.user {
                Section {
                    HStack(spacing: 10) {
                        Circle().fill(Color(hex: u.color) ?? .gray).frame(width: 12, height: 12)
                        VStack(alignment: .leading) {
                            Text(u.displayName).bold()
                            Text("@\(u.username)\(u.isAdmin ? " · admin" : "")")
                                .font(.caption).foregroundColor(.secondary)
                        }
                    }
                    Button("Change password…") { showPassword = true }
                }
                ShareMyCalendarSection()
                if !sharedIn.isEmpty {
                    Section("Shared with me") {
                        ForEach(sharedIn, id: \.name) { s in
                            HStack {
                                Circle().fill(Color(hex: s.color) ?? .gray).frame(width: 10, height: 10)
                                Text(s.name); Spacer()
                                Text(s.level).foregroundColor(.secondary)
                            }
                        }
                    }
                }
                Section {
                    Toggle("Group shared to-dos by person", isOn: Binding(
                        get: { groupByOwner },
                        set: { v in
                            groupByOwner = v
                            Task {
                                if let e = await accountCall(api, "/users/me/settings",
                                                             body: ["todos_group_by_owner": v]) {
                                    groupByOwner = !v; settingError = e
                                } else { settingError = "" }
                            }
                        }))
                } footer: {
                    Text(settingError.isEmpty ? "Notifications are only ever about your own calendar and to-dos."
                                              : "Couldn't change that: \(settingError)")
                        .foregroundColor(settingError.isEmpty ? .secondary : .red)
                }
                if u.isAdmin {
                    Section { NavigationLink("Manage users") { AdminUsersView() } }
                }
                Section {
                    Button("Switch user") { Task { await session.signOut(api: api) } }
                    Button("Sign out", role: .destructive) { Task { await session.signOut(api: api) } }
                }
            } else {
                Text("Not signed in.").foregroundColor(.secondary)
            }
        }
        .navigationTitle("Account & Sharing")
        .task { if !loaded { await load(); loaded = true } }
        .sheet(isPresented: $showPassword) { ChangePasswordView() }
    }

    private func load() async {
        guard let me = session.user else { return }
        if let data = try? await api.request("/users"),
           let all = try? JSONDecoder().decode([PublicUser].self, from: data) {
            others = all.filter { $0.id != me.id }
        }
        guard let data = try? await api.request("/auth/me"),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
        sharedIn = ((obj["shares_in"] as? [[String: Any]]) ?? []).compactMap { s in
            guard let owner = s["owner"] as? String,
                  let o = others.first(where: { $0.id == owner }) else { return nil }
            return (o.displayName, o.color, s["level"] as? String ?? "")
        }
        let st = obj["settings"] as? [String: Any] ?? [:]
        groupByOwner = st["todos_group_by_owner"] as? Bool ?? false
    }

}

// MARK: - sharing, one view for everyone

/// "Share my calendar and to-dos": one menu per other person. The person's
/// own page and the admin's dashboard both show THIS view, so they can't drift.
struct ShareMyCalendarSection: View {
    @EnvironmentObject var api: APIClient
    @ObservedObject private var session = UserSession.shared
    @State private var others: [PublicUser] = []
    @State private var levels: [String: String] = [:]        // grantee -> none|view|edit
    @State private var error = ""

    var body: some View {
        Section {
            if others.isEmpty {
                Text("Nobody else has an account yet.").foregroundColor(.secondary)
            }
            ForEach(others) { o in
                HStack {
                    Circle().fill(Color(hex: o.color) ?? .gray).frame(width: 10, height: 10)
                    Text(o.displayName)
                    Spacer()
                    ShareLevelPicker(level: Binding(
                        get: { levels[o.id] ?? "none" },
                        set: { v in
                            let was = levels[o.id] ?? "none"
                            levels[o.id] = v
                            Task {
                                if let e = await setShare(api, o.id, v) { levels[o.id] = was; error = e }
                                else { error = "" }
                            }
                        }))
                }
            }
        } header: { Text("Share my calendar and to-dos") }
          footer: {
              Text(error.isEmpty ? "Everything, with the people you choose. View lets them see; Edit lets them change it too."
                                 : "Couldn't change that: \(error)")
                  .foregroundColor(error.isEmpty ? .secondary : .red)
          }
        .task { await load() }
    }

    private func load() async {
        guard let me = session.user else { return }
        if let data = try? await api.request("/users"),
           let all = try? JSONDecoder().decode([PublicUser].self, from: data) {
            others = all.filter { $0.id != me.id }
        }
        levels = await shareLevels(api)
    }
}

struct ShareLevelPicker: View {
    @Binding var level: String
    var label = ""
    var body: some View {
        Picker(label, selection: $level) {
            Text("Not shared").tag("none")
            Text("View").tag("view")
            Text("Edit").tag("edit")
        }
        .pickerStyle(.menu)
    }
}

/// My outgoing shares, grantee -> view|edit.
@MainActor
func shareLevels(_ api: APIClient) async -> [String: String] {
    guard let data = try? await api.request("/auth/me"),
          let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return [:] }
    var out: [String: String] = [:]
    for s in (obj["shares_out"] as? [[String: Any]]) ?? [] {
        if let g = s["grantee"] as? String { out[g] = s["level"] as? String ?? "none" }
    }
    return out
}

/// Returns nil on success, else what went wrong — every Account control
/// shows that and snaps back, instead of looking done when nothing happened
/// (Gil, 2026-09-28: "not all the toggles/buttons in account tab work").
@MainActor
func setShare(_ api: APIClient, _ grantee: String, _ level: String) async -> String? {
    do {
        if level == "none" {
            _ = try await api.request("/shares/\(grantee)", method: "DELETE")
        } else {
            _ = try await api.request("/shares/\(grantee)", method: "PUT", body: ["level": level])
        }
        api.requestRefresh()
        return nil
    } catch {
        return error.localizedDescription
    }
}

@MainActor
func accountCall(_ api: APIClient, _ path: String, method: String = "PUT",
                 body: [String: Any] = [:]) async -> String? {
    do {
        _ = try await api.request(path, method: method, body: body)
        api.requestRefresh()
        return nil
    } catch {
        return error.localizedDescription
    }
}

// MARK: - one person, as the admin sees them

/// Everything the admin can do about ONE person, visible — no swipe actions
/// to discover: what he sees of them, what he shares with them, their account.
struct AdminUserDetailView: View {
    @EnvironmentObject var api: APIClient
    let userID: String
    @State private var u: AdminUser?
    @State private var shown = false
    @State private var vocab = false
    @State private var myShare = "none"
    @State private var revealed: String?
    @State private var note = ""

    var body: some View {
        Form {
            if let u {
                Section {
                    HStack(spacing: 10) {
                        Circle().fill(Color(hex: u.color) ?? .gray).frame(width: 12, height: 12)
                        VStack(alignment: .leading) {
                            Text(u.displayName).bold()
                            Text("@\(u.username)").font(.caption).foregroundColor(.secondary)
                        }
                        Spacer()
                        if u.disabled == true { Text("disabled").font(.caption).foregroundColor(.red) }
                    }
                    Text((u.sessions ?? 0) > 0 ? "Signed in on \(u.sessions!) device\(u.sessions! == 1 ? "" : "s")"
                                               : "Not signed in anywhere")
                        .foregroundColor(.secondary)
                }
                Section {
                    Toggle("Show their calendar and to-dos in mine", isOn: Binding(
                        get: { shown },
                        set: { v in shown = v; Task { await put("/admin/view/\(u.id)", ["shown": v]) } }))
                } header: { Text("What you see") }
                  footer: { Text("On: their items join your views with their name and a stripe in their colour.") }
                Section("What you share with them") {
                    HStack {
                        Text("My calendar and to-dos")
                        Spacer()
                        ShareLevelPicker(level: Binding(
                            get: { myShare },
                            set: { v in
                                myShare = v
                                Task {
                                    if let e = await setShare(api, u.id, v) { await failed(e) } else { note = "" }
                                }
                            }))
                    }
                    Toggle("My vocabulary", isOn: Binding(
                        get: { vocab },
                        set: { v in vocab = v; Task { await put("/admin/vocab_share/\(u.id)", ["on": v]) } }))
                }
                Section {
                    Button("Reset password") { Task { await reset() } }
                    if let pw = revealed {
                        Text("New password — shown once. They'll choose their own when they sign in.")
                            .font(.footnote)
                        Text(pw).font(.system(.title3, design: .monospaced)).textSelection(.enabled)
                    }
                    Button("Sign out on every device") { Task { await signOut() } }
                    Button(u.disabled == true ? "Enable account" : "Disable account",
                           role: u.disabled == true ? nil : .destructive) {
                        Task { await patch(["disabled": !(u.disabled ?? false)]) }
                    }
                } header: { Text("Their account") }
                  footer: { Text(note) }
            } else {
                ProgressView()
            }
        }
        .navigationTitle(u?.displayName ?? "User")
        .task { await load() }
    }

    private func load() async {
        if let data = try? await api.request("/admin/users"),
           let got = try? JSONDecoder().decode([AdminUser].self, from: data),
           let me = got.first(where: { $0.id == userID }) {
            u = me
            shown = me.shownInMyView ?? false
        }
        if let data = try? await api.request("/auth/me"),
           let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            vocab = ((obj["vocab_shared_with"] as? [String]) ?? []).contains(userID)
        }
        myShare = await shareLevels(api)[userID] ?? "none"
    }

    /// A control that didn't take: say so, and put every control back to
    /// what the Mac actually has.
    private func failed(_ e: String) async {
        note = "Couldn't change that: \(e)"
        await load()
    }

    private func put(_ path: String, _ body: [String: Any]) async {
        if let e = await accountCall(api, path, body: body) { await failed(e) } else { note = "" }
    }

    private func patch(_ body: [String: Any]) async {
        if let e = await accountCall(api, "/admin/users/\(userID)", method: "PATCH", body: body) {
            await failed(e)
        } else {
            note = ""
            await load()
        }
    }

    private func signOut() async {
        do {
            let data = try await api.request("/admin/users/\(userID)/signout", method: "POST", body: [:])
            let obj = (try? JSONSerialization.jsonObject(with: data) as? [String: Any]) ?? [:]
            let n = obj["signed_out"] as? Int ?? 0
            note = "Signed out of \(n) device\(n == 1 ? "" : "s"). Their password is unchanged."
        } catch {
            note = "Couldn't sign them out: \(error.localizedDescription)"
        }
        await load()
    }

    private func reset() async {
        do {
            let data = try await api.request("/admin/users/\(userID)/password", method: "POST", body: [:])
            let obj = (try? JSONSerialization.jsonObject(with: data) as? [String: Any]) ?? [:]
            revealed = obj["password"] as? String
            note = revealed == nil ? "The Mac didn't send a new password." : ""
        } catch {
            note = "Couldn't reset it: \(error.localizedDescription)"
        }
    }
}

// MARK: - the admin's users

struct AdminUser: Decodable, Identifiable {
    let id: String
    let username: String
    let displayName: String
    let color: String
    let role: String
    let disabled: Bool?
    let lastSeen: Double?
    let shownInMyView: Bool?
    let sessions: Int?
    enum CodingKeys: String, CodingKey {
        case id, username, color, role, disabled, sessions
        case displayName = "display_name"
        case lastSeen = "last_seen"
        case shownInMyView = "shown_in_my_view"
    }
}

struct AdminUsersView: View {
    @EnvironmentObject var api: APIClient
    @State private var rows: [AdminUser] = []
    @State private var vocabSharedWith: Set<String> = []
    @State private var requireLogin = false
    @State private var newName = ""
    @State private var showNew = false
    @State private var revealed: (who: String, password: String)?
    @State private var error = ""

    var body: some View {
        List {
            if let r = revealed {
                Section {
                    Text("New password for \(r.who) — shown once. They'll choose their own when they sign in.")
                        .font(.footnote)
                    Text(r.password).font(.system(.title3, design: .monospaced)).textSelection(.enabled)
                }
            }
            if !error.isEmpty { Text(error).foregroundColor(.red).font(.footnote) }
            ForEach(rows) { u in
                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        Circle().fill(Color(hex: u.color) ?? .gray).frame(width: 10, height: 10)
                        Text(u.displayName).bold()
                        Text("@\(u.username)").foregroundColor(.secondary)
                        if u.role == "admin" { Text("admin").font(.caption).foregroundColor(.secondary) }
                        if u.disabled == true { Text("disabled").font(.caption).foregroundColor(.red) }
                    }
                    if u.role != "admin" {
                        Toggle("Show in my calendar", isOn: Binding(
                            get: { u.shownInMyView ?? false },
                            set: { v in Task { await put("/admin/view/\(u.id)", ["shown": v]) } }))
                        Toggle("Share my vocabulary", isOn: Binding(
                            get: { vocabSharedWith.contains(u.id) },
                            set: { v in Task { await put("/admin/vocab_share/\(u.id)", ["on": v]) } }))
                    }
                }
                .swipeActions {
                    if u.role != "admin" {
                        Button("Reset password") { Task { await reset(u) } }.tint(.orange)
                        Button("Sign out") { Task { await signOut(u) } }.tint(.gray)
                        Button(u.disabled == true ? "Enable" : "Disable") {
                            Task { await patch(u.id, ["disabled": !(u.disabled ?? false)]) }
                        }
                    }
                }
            }
            Section {
                Toggle("Require sign-in everywhere", isOn: Binding(
                    get: { requireLogin },
                    set: { v in requireLogin = v; Task { await put("/admin/policy", ["require_login": v]) } }))
            } footer: { Text("Off: a device nobody signed in on acts as the admin.") }
        }
        .navigationTitle("Users")
        .toolbar { Button { showNew = true } label: { Image(systemName: "person.badge.plus") } }
        .alert("New user", isPresented: $showNew) {
            TextField("username", text: $newName).textInputAutocapitalization(.never)
            Button("Create") { Task { await create() } }
            Button("Cancel", role: .cancel) {}
        }
        .task { await load() }
        .refreshable { await load() }
    }

    private func load() async {
        if let data = try? await api.request("/admin/users"),
           let got = try? JSONDecoder().decode([AdminUser].self, from: data) { rows = got }
        if let data = try? await api.request("/auth/me"),
           let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            vocabSharedWith = Set((obj["vocab_shared_with"] as? [String]) ?? [])
            requireLogin = ((obj["policy"] as? [String: Any])?["require_login"] as? Bool) ?? false
        }
    }

    private func put(_ path: String, _ body: [String: Any]) async {
        do { _ = try await api.request(path, method: "PUT", body: body) }
        catch { self.error = error.localizedDescription }
        await load(); api.requestRefresh()
    }

    private func patch(_ id: String, _ body: [String: Any]) async {
        error = await accountCall(api, "/admin/users/\(id)", method: "PATCH", body: body) ?? ""
        await load()
    }

    private func signOut(_ u: AdminUser) async {
        error = await accountCall(api, "/admin/users/\(u.id)/signout", method: "POST") ?? ""
        await load()
    }

    private func reset(_ u: AdminUser) async {
        guard let data = try? await api.request("/admin/users/\(u.id)/password", method: "POST", body: [:]),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let pw = obj["password"] as? String else { return }
        revealed = (u.displayName, pw)
    }

    private func create() async {
        let name = newName.trimmingCharacters(in: .whitespaces).lowercased()
        newName = ""
        guard !name.isEmpty else { return }
        do {
            let data = try await api.request("/admin/users", method: "POST", body: ["username": name])
            if let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any],
               let pw = obj["password"] as? String {
                revealed = ((obj["display_name"] as? String) ?? name, pw)
            }
        } catch { self.error = error.localizedDescription }
        await load()
    }
}


// MARK: - the Account tab

/// The Account tab (DEVQA Q65): the admin's dashboard, or a person's own page.
struct AccountTabView: View {
    @ObservedObject private var session = UserSession.shared

    var body: some View {
        StackNavigation {
            if let u = session.user {
                if u.isAdmin { AdminDashboardView() } else { AccountView() }
            } else {
                VStack(spacing: 12) {
                    Image(systemName: "person.crop.circle").font(.system(size: 44)).foregroundColor(.secondary)
                    Text("No one is signed in on this phone.").foregroundColor(.secondary)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .navigationTitle("Account")
            }
        }
    }
}

/// Everything the admin controls, on one screen: who exists and who is signed
/// in where, the sign-in policy (require sign-in; auto sign-out off or after N
/// days), people, and his own account.
struct AdminDashboardView: View {
    @EnvironmentObject var api: APIClient
    @ObservedObject private var session = UserSession.shared
    @State private var rows: [AdminUser] = []
    @State private var requireLogin = false
    @State private var autoOn = false
    @State private var autoDays = 30
    @State private var policyError = ""
    @State private var loaded = false

    var body: some View {
        List {
            Section {
                HStack {
                    stat("\(rows.count)", "users")
                    stat("\(rows.reduce(0) { $0 + ($1.sessions ?? 0) })", "signed in")
                    stat("\(rows.filter { $0.disabled == true }.count)", "disabled")
                }
            }
            Section {
                ForEach(rows) { u in
                    NavigationLink {
                        if u.role == "admin" { AccountView() } else { AdminUserDetailView(userID: u.id) }
                    } label: {
                        HStack {
                            Circle().fill(Color(hex: u.color) ?? .gray).frame(width: 10, height: 10)
                            Text(u.displayName)
                            if u.role == "admin" { Text("you").font(.caption).foregroundColor(.secondary) }
                            if u.disabled == true { Text("disabled").font(.caption).foregroundColor(.red) }
                            Spacer()
                            Text((u.sessions ?? 0) > 0 ? "signed in on \(u.sessions!)" : "signed out")
                                .font(.caption).foregroundColor(.secondary)
                        }
                    }
                }
                NavigationLink { AdminUsersView() } label: {
                    Label("Add a person", systemImage: "person.badge.plus")
                }
            } header: { Text("People") }
              footer: { Text("Tap someone for what you see of them, what you share with them, and their password, sign-in and account.") }
            ShareMyCalendarSection()
            Section {
                Toggle("Require sign-in everywhere", isOn: Binding(
                    get: { requireLogin },
                    set: { v in requireLogin = v; Task { await policy(["require_login": v]) } }))
                Toggle("Auto sign-out", isOn: Binding(
                    get: { autoOn },
                    set: { v in autoOn = v; Task { await policy(["auto_signout_days": v ? autoDays : 0]) } }))
                if autoOn {
                    Stepper("After \(autoDays) day\(autoDays == 1 ? "" : "s") unused", value: Binding(
                        get: { autoDays },
                        set: { v in autoDays = v; Task { await policy(["auto_signout_days": v]) } }),
                            in: 1...365)
                }
            } header: { Text("Sign-in") }
              footer: {
                  if !policyError.isEmpty {
                      Text("Couldn't change that: \(policyError)").foregroundColor(.red)
                  } else {
                      Text(autoOn ? "A device unused this long is signed out."
                                  : "Off: a sign-in lasts until the person signs out, or you sign them out.")
                  }
              }
            Section("Me") {
                NavigationLink { AccountView() } label: {
                    Label("My account, password & settings", systemImage: "person.crop.circle")
                }
                Button("Sign out", role: .destructive) { Task { await session.signOut(api: api) } }
            }
        }
        .navigationTitle("Admin")
        // Every appearance: coming back from a person's page must show what changed there.
        .onAppear { Task { await load() } }
        .refreshable { await load() }
    }

    private func stat(_ n: String, _ what: String) -> some View {
        VStack { Text(n).font(.title2.bold()); Text(what).font(.caption).foregroundColor(.secondary) }
            .frame(maxWidth: .infinity)
    }

    private func load() async {
        if let data = try? await api.request("/admin/users"),
           let got = try? JSONDecoder().decode([AdminUser].self, from: data) { rows = got }
        if let data = try? await api.request("/auth/me"),
           let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let pol = obj["policy"] as? [String: Any] {
            requireLogin = pol["require_login"] as? Bool ?? false
            if let d = pol["auto_signout_days"] as? Int, d > 0 { autoOn = true; autoDays = d } else { autoOn = false }
        }
    }

    private func policy(_ body: [String: Any]) async {
        if let e = await accountCall(api, "/admin/policy", body: body) {
            policyError = e
            await load()                          // put the switches back
        } else {
            policyError = ""
        }
    }
}
