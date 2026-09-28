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
    @State private var levels: [String: String] = [:]        // grantee -> none|view|edit
    @State private var sharedIn: [(name: String, color: String, level: String)] = []
    @State private var groupByOwner = false
    @State private var notifyShared = false
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
                Section {
                    if others.isEmpty {
                        Text("Nobody else has an account yet.").foregroundColor(.secondary)
                    }
                    ForEach(others) { o in
                        HStack {
                            Circle().fill(Color(hex: o.color) ?? .gray).frame(width: 10, height: 10)
                            Text(o.displayName)
                            Spacer()
                            Picker("", selection: Binding(
                                get: { levels[o.id] ?? "none" },
                                set: { v in levels[o.id] = v; Task { await share(o.id, v) } })) {
                                Text("Not shared").tag("none")
                                Text("View").tag("view")
                                Text("Edit").tag("edit")
                            }
                            .pickerStyle(.menu)
                        }
                    }
                } header: { Text("Share my calendar and to-dos") }
                  footer: { Text("Everything, with the people you choose. View lets them see; Edit lets them change it too.") }
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
                        set: { v in groupByOwner = v; Task { await setting("todos_group_by_owner", v) } }))
                    Toggle("Include shared items in my notifications", isOn: Binding(
                        get: { notifyShared },
                        set: { v in notifyShared = v; Task { await setting("notify_shared", v) } }))
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
        for s in (obj["shares_out"] as? [[String: Any]]) ?? [] {
            if let g = s["grantee"] as? String { levels[g] = s["level"] as? String ?? "none" }
        }
        sharedIn = ((obj["shares_in"] as? [[String: Any]]) ?? []).compactMap { s in
            guard let owner = s["owner"] as? String,
                  let o = others.first(where: { $0.id == owner }) else { return nil }
            return (o.displayName, o.color, s["level"] as? String ?? "")
        }
        let st = obj["settings"] as? [String: Any] ?? [:]
        groupByOwner = st["todos_group_by_owner"] as? Bool ?? false
        notifyShared = st["notify_shared"] as? Bool ?? false
    }

    private func share(_ grantee: String, _ level: String) async {
        if level == "none" {
            _ = try? await api.request("/shares/\(grantee)", method: "DELETE")
        } else {
            _ = try? await api.request("/shares/\(grantee)", method: "PUT", body: ["level": level])
        }
        api.requestRefresh()
    }

    private func setting(_ key: String, _ on: Bool) async {
        _ = try? await api.request("/users/me/settings", method: "PUT", body: [key: on])
        api.requestRefresh()
    }
}

// MARK: - the admin's users

private struct AdminUser: Decodable, Identifiable {
    let id: String
    let username: String
    let displayName: String
    let color: String
    let role: String
    let disabled: Bool?
    let lastSeen: Double?
    let shownInMyView: Bool?
    enum CodingKeys: String, CodingKey {
        case id, username, color, role, disabled
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
        _ = try? await api.request("/admin/users/\(id)", method: "PATCH", body: body)
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
