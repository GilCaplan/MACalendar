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
    /// Opened from "Switch user": Cancel keeps whoever is signed in now.
    var switching = false
    @Environment(\.dismiss) private var dismiss
    @State private var username = ""
    @State private var password = ""
    @State private var error = ""
    @State private var busy = false
    @State private var changePassword = false
    @FocusState private var focus: Field?
    private enum Field { case user, pass }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            if switching {
                HStack { Spacer(); Button("Cancel") { dismiss() }.accessibilityIdentifier("switch-cancel") }
            }
            Spacer()
            Image(systemName: "calendar.circle.fill")
                .font(.system(size: 54))
                .foregroundColor(settings.accentColor)
            Text(switching ? "Switch to…" : "Who's using the calendar?")
                .font(.title2.weight(.bold))
            Text("Each person has their own calendar and to-dos.")
                .font(.subheadline).foregroundColor(.secondary)
            // Who has used this device: a tap fills the name, the password is next.
            let others = session.recent.filter { $0.id != (switching ? session.user?.id : nil) }
            if !others.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 14) {
                        ForEach(others, id: \.id) { u in
                            Button {
                                username = u.username
                                password = ""
                                focus = .pass
                            } label: {
                                VStack(spacing: 4) {
                                    PersonAvatar(name: u.displayName, color: u.color, size: 46)
                                        .overlay(Circle().stroke(settings.accentColor,
                                                                 lineWidth: username == u.username ? 2.5 : 0))
                                    Text(u.displayName).font(.caption).lineLimit(1).frame(maxWidth: 64)
                                }
                            }
                            .buttonStyle(.plain)
                            .accessibilityIdentifier("recent-user-\(u.username)")
                            .contextMenu {
                                Button("Forget on this device", role: .destructive) { session.forget(u.username) }
                            }
                        }
                    }
                    .padding(.vertical, 2)
                }
            }
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
            // Coming back to a device someone used: their name is ready.
            if !switching, username.isEmpty, let last = session.recent.first {
                username = last.username
                focus = .pass
            }
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
            if switching {
                try await session.switchTo(username: username, password: password, api: api)
            } else {
                try await session.signIn(username: username, password: password, api: api)
            }
            if session.user?.mustChangePassword == true { changePassword = true }
            else if switching { dismiss() }
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
//
// Revamped 2026-09-28 (Gil: "I was also referring to the account tab, can you
// revamp and fix that as well"). Three admin screens that overlapped — a
// dashboard, a "Manage users" list whose actions hid behind swipes, and a
// per-person page — plus a page that listed "Share my calendar" and "Shared
// with me" as two separate lists, became ONE Account page for everyone and
// ONE page per person. Each person's row says both directions at once.

struct PublicUser: Decodable, Identifiable {
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

/// Everything the Account pages show, loaded in one place so the home page
/// and a person's page can never disagree about who shares what.
@MainActor
final class AccountModel: ObservableObject {
    static let shared = AccountModel()

    @Published var people: [PublicUser] = []             // everyone but me
    @Published var accounts: [String: AdminUser] = [:]   // the admin's view of each
    @Published var sharesOut: [String: String] = [:]     // who sees mine: id -> view|edit
    @Published var sharesIn: [String: String] = [:]      // whose I see:   id -> view|edit
    @Published var vocab: Set<String> = []
    @Published var requireLogin = false
    @Published var autoDays: Int? = nil
    @Published var groupByOwner = false
    @Published var loadError = ""

    func load(_ api: APIClient) async {
        guard let me = UserSession.shared.user else { return }
        do {
            let data = try await api.request("/users")
            people = ((try? JSONDecoder().decode([PublicUser].self, from: data)) ?? [])
                .filter { $0.id != me.id }
            let meData = try await api.request("/auth/me")
            let obj = (try? JSONSerialization.jsonObject(with: meData) as? [String: Any]) ?? [:]
            func levels(_ key: String, _ who: String) -> [String: String] {
                var out: [String: String] = [:]
                for s in (obj[key] as? [[String: Any]]) ?? [] {
                    if let id = s[who] as? String { out[id] = s["level"] as? String ?? "view" }
                }
                return out
            }
            sharesOut = levels("shares_out", "grantee")
            sharesIn = levels("shares_in", "owner")
            vocab = Set((obj["vocab_shared_with"] as? [String]) ?? [])
            let pol = obj["policy"] as? [String: Any] ?? [:]
            requireLogin = pol["require_login"] as? Bool ?? false
            autoDays = (pol["auto_signout_days"] as? Int).flatMap { $0 > 0 ? $0 : nil }
            groupByOwner = (obj["settings"] as? [String: Any])?["todos_group_by_owner"] as? Bool ?? false
            UserSession.shared.groupSharedTodos = groupByOwner
            if me.isAdmin {
                let rows = try await api.request("/admin/users")
                let list = (try? JSONDecoder().decode([AdminUser].self, from: rows)) ?? []
                accounts = Dictionary(uniqueKeysWithValues: list.map { ($0.id, $0) })
            }
            loadError = ""
        } catch {
            loadError = error.localizedDescription
        }
    }

    /// "You share View · They share nothing" — both directions in one line.
    func relation(_ id: String) -> String {
        let mine = sharesOut[id].map { $0 == "edit" ? "Edit" : "View" } ?? "nothing"
        let theirs = sharesIn[id].map { $0 == "edit" ? "Edit" : "View" } ?? "nothing"
        return "You share \(mine) · They share \(theirs)"
    }
}

/// A person's initial on their colour.
struct PersonAvatar: View {
    let name: String
    let color: String
    var size: CGFloat = 36
    var body: some View {
        ZStack {
            Circle().fill(Color(hex: color) ?? .gray)
            Text(String(name.prefix(1)).uppercased())
                .font(.system(size: size * 0.45, weight: .semibold)).foregroundColor(.white)
        }
        .frame(width: size, height: size)
    }
}

// MARK: - the Account page

struct AccountView: View {
    @EnvironmentObject var api: APIClient
    @EnvironmentObject var settings: AppSettings
    @ObservedObject private var session = UserSession.shared
    @ObservedObject private var model = AccountModel.shared
    @State private var showPassword = false
    @State private var showNew = false
    @State private var newName = ""
    @State private var created: (name: String, password: String)?
    @State private var error = ""
    @State private var switchingUser = false
    @State private var deleting = false
    @State private var deletePassword = ""

    var body: some View {
        List {
            if let u = session.user {
                Section {
                    HStack(spacing: 14) {
                        PersonAvatar(name: u.displayName, color: u.color, size: 52)
                        VStack(alignment: .leading, spacing: 3) {
                            Text(u.displayName).font(.title3.weight(.semibold))
                            Text("@\(u.username)\(u.isAdmin ? " · admin" : "")")
                                .font(.subheadline).foregroundColor(.secondary)
                            if u.isAdmin {
                                Text(adminStats).font(.caption).foregroundColor(.secondary)
                            }
                        }
                    }
                    .padding(.vertical, 6)
                    Button { switchingUser = true } label: {
                        Label("Switch user", systemImage: "person.2.circle")
                    }
                    .accessibilityIdentifier("switch-user")
                    // On the button, not the list: the list already carries the
                    // password sheet, and two sheets on one view present one.
                    .sheet(isPresented: $switchingUser) {
                        LoginView(switching: true).environmentObject(api).environmentObject(settings)
                    }
                }

                if let c = created {
                    Section {
                        Text("\(c.name)'s password — shown once. They'll choose their own when they sign in.")
                            .font(.footnote)
                        Text(c.password).font(.system(.title3, design: .monospaced)).textSelection(.enabled)
                    } header: { Text("New person added") }
                }

                Section {
                    ForEach(model.people) { p in
                        NavigationLink { PersonView(personID: p.id) } label: {
                            HStack(spacing: 12) {
                                PersonAvatar(name: p.displayName, color: p.color)
                                VStack(alignment: .leading, spacing: 2) {
                                    HStack(spacing: 6) {
                                        Text(p.displayName)
                                        if model.accounts[p.id]?.disabled == true {
                                            Text("disabled").font(.caption2.weight(.semibold))
                                                .foregroundColor(.red)
                                        }
                                    }
                                    Text(model.relation(p.id)).font(.caption).foregroundColor(.secondary)
                                }
                            }
                            .padding(.vertical, 2)
                        }
                    }
                    if u.isAdmin {
                        Button { showNew = true } label: {
                            Label("Add a person", systemImage: "person.badge.plus")
                        }
                    }
                } header: { Text("People") }
                  footer: {
                      Text(model.people.isEmpty
                           ? "Nobody else has an account yet."
                           : u.isAdmin
                             ? "Tap someone to choose what you share with them, whether their calendar shows in yours, and their account."
                             : "Tap someone to choose what you share with them.")
                  }

                Section {
                    Toggle("Group shared to-dos by person", isOn: Binding(
                        get: { model.groupByOwner },
                        set: { v in
                            model.groupByOwner = v
                            Task {
                                if let e = await accountCall(api, "/users/me/settings",
                                                             body: ["todos_group_by_owner": v]) {
                                    model.groupByOwner = !v; error = e
                                } else {
                                    error = ""
                                    session.groupSharedTodos = v      // Tasks follows at once
                                }
                            }
                        }))
                } header: { Text("Tasks") }
                  footer: {
                      Text("On: each person who shares with you gets their own section in Tasks, below yours. Off: their to-dos sit in Today and General with yours — the Whose chips filter them.")
                  }

                if u.isAdmin {
                    Section {
                        Toggle(isOn: Binding(
                            get: { model.requireLogin },
                            set: { v in
                                model.requireLogin = v
                                Task { await policy(["require_login": v]) }
                            })) {
                            HStack(spacing: 6) {
                                Text("Require sign-in everywhere")
                                InfoTip("On: every phone, tablet and computer must sign in as someone before it shows anything. Off: a device nobody signed in on acts as the admin.")
                            }
                        }
                        Toggle(isOn: Binding(
                            get: { model.autoDays != nil },
                            set: { v in
                                model.autoDays = v ? 30 : nil
                                Task { await policy(["auto_signout_days": v ? 30 : 0]) }
                            })) {
                            HStack(spacing: 6) {
                                Text("Sign out after a while unused")
                                InfoTip("A device signs out on its own once it has gone this many days without being used.")
                            }
                        }
                        if let d = model.autoDays {
                            Stepper("After \(d) day\(d == 1 ? "" : "s")", value: Binding(
                                get: { model.autoDays ?? 30 },
                                set: { v in
                                    model.autoDays = v
                                    Task { await policy(["auto_signout_days": v]) }
                                }), in: 1...365)
                        }
                    } header: { Text("Sign-in") }
                      footer: {
                          Text(model.requireLogin
                               ? "Every device must sign in. "
                               : "Off: a device nobody signed in on acts as you, the admin. ")
                          + Text(model.autoDays == nil
                                 ? "A sign-in lasts until the person signs out, or you sign them out."
                                 : "A device unused this long is signed out.")
                      }
                }

                Section {
                    Button("Change password…") { showPassword = true }
                } header: { Text("Security") }

                if !error.isEmpty || !model.loadError.isEmpty {
                    Section {
                        Text("Couldn't do that: \(error.isEmpty ? model.loadError : error)")
                            .font(.footnote).foregroundColor(.red)
                    }
                }

                Section {
                    Button("Sign out", role: .destructive) { Task { await session.signOut(api: api) } }
                } footer: { Text("Signs this device out. Anyone can then sign in here as themselves.") }

                // App Store 5.1.1(v): an account can be deleted where it is used.
                // The admin runs the house and hands it over on the Mac first.
                if !u.isAdmin {
                    Section {
                        Button("Delete my account…", role: .destructive) { deletePassword = ""; deleting = true }
                            .accessibilityIdentifier("delete-my-account")
                    } footer: {
                        Text("Removes you from this Mac and signs you out everywhere. Your calendar is set aside on the Mac, "
                             + "not shared with anyone, so the owner of the Mac can restore it if this was a mistake.")
                    }
                }
            } else {
                Text("No one is signed in on this device.").foregroundColor(.secondary)
            }
        }
        .listStyle(.insetGrouped)
        // Someone else is signed in now: the switch sheet has done its job.
        // Closed here too, because the page rebuilds for the new person and
        // the sheet's own dismiss can be lost with the old one.
        .onChange(of: session.user?.id) { _ in switchingUser = false }
        .alert("Delete your account?", isPresented: $deleting) {
            SecureField("Your password", text: $deletePassword)
            Button("Delete", role: .destructive) { Task { await deleteMe() } }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Type your password to confirm. You'll be signed out on every device.")
        }
        .navigationTitle("Account")
        .onAppear { Task { await model.load(api) } }
        .refreshable { await model.load(api) }
        .sheet(isPresented: $showPassword) { ChangePasswordView() }
        .alert("Add a person", isPresented: $showNew) {
            TextField("username", text: $newName).textInputAutocapitalization(.never)
            Button("Add") { Task { await create() } }
            Button("Cancel", role: .cancel) { newName = "" }
        } message: { Text("Letters and numbers. They get a password to change when they first sign in.") }
    }

    private var adminStats: String {
        let n = model.people.count + 1
        let devices = model.accounts.values.reduce(0) { $0 + ($1.sessions ?? 0) }
        return "\(n) people · \(devices) device\(devices == 1 ? "" : "s") signed in"
    }

    private func policy(_ body: [String: Any]) async {
        if let e = await accountCall(api, "/admin/policy", body: body) {
            error = e
            await model.load(api)                   // put the switches back
        } else {
            error = ""
        }
    }

    private func create() async {
        let name = newName.trimmingCharacters(in: .whitespaces).lowercased()
        newName = ""
        guard !name.isEmpty else { return }
        do {
            let data = try await api.request("/admin/users", method: "POST", body: ["username": name])
            let obj = (try? JSONSerialization.jsonObject(with: data) as? [String: Any]) ?? [:]
            if let pw = obj["password"] as? String {
                created = ((obj["display_name"] as? String) ?? name, pw)
            }
            error = ""
        } catch {
            self.error = error.localizedDescription
        }
        await model.load(api)
    }
}

// MARK: - one person

/// Everything about ONE person, for whoever is looking: what you share with
/// them, what you see of theirs — and, for the admin, their vocabulary and
/// account. Every control visible; nothing behind a swipe.
extension AccountView {
    func deleteMe() async {
        do {
            _ = try await api.request("/auth/me", method: "DELETE", body: ["password": deletePassword])
            deletePassword = ""
            await session.signOut(api: api)
        } catch {
            self.error = error.localizedDescription.contains("wrong password")
                ? "That password isn't right — nothing was deleted." : error.localizedDescription
        }
    }
}

struct PersonView: View {
    @EnvironmentObject var api: APIClient
    @ObservedObject private var session = UserSession.shared
    @ObservedObject private var model = AccountModel.shared
    let personID: String
    @State private var revealed: String?
    @State private var note = ""
    @State private var confirmRemove = false

    private var person: PublicUser? { model.people.first { $0.id == personID } }
    private var account: AdminUser? { model.accounts[personID] }
    private var isAdmin: Bool { session.user?.isAdmin == true }

    var body: some View {
        List {
            if let p = person {
                Section {
                    HStack(spacing: 14) {
                        PersonAvatar(name: p.displayName, color: p.color, size: 52)
                        VStack(alignment: .leading, spacing: 3) {
                            Text(p.displayName).font(.title3.weight(.semibold))
                            Text("@\(p.username)").font(.subheadline).foregroundColor(.secondary)
                            if let a = account {
                                Text(a.disabled == true ? "Disabled"
                                     : (a.sessions ?? 0) > 0 ? "Signed in on \(a.sessions!) device\(a.sessions! == 1 ? "" : "s")"
                                     : "Not signed in anywhere")
                                    .font(.caption)
                                    .foregroundColor(a.disabled == true ? .red : .secondary)
                            }
                        }
                    }
                    .padding(.vertical, 6)
                }

                Section {
                    HStack {
                        Text("They can")
                        InfoTip("Not shared: they see nothing of yours. View: your calendar and to-dos appear in theirs, read-only. Edit: they can also add to them and change them.")
                        Spacer()
                        ShareLevelPicker(level: Binding(
                            get: { model.sharesOut[personID] ?? "none" },
                            set: { v in
                                let was = model.sharesOut[personID]
                                model.sharesOut[personID] = v == "none" ? nil : v
                                Task {
                                    if let e = await setShare(api, personID, v) {
                                        model.sharesOut[personID] = was
                                        note = "Couldn't change that: \(e)"
                                    } else { note = "" }
                                }
                            }))
                    }
                } header: { Text("Your calendar & to-dos") }
                  footer: { Text("Not shared: they see nothing of yours. View: they see all of it. Edit: they can change it too.") }

                Section {
                    if isAdmin {
                        Toggle("Show in my calendar & to-dos", isOn: Binding(
                            get: { account?.shownInMyView ?? false },
                            set: { v in Task { await put("/admin/view/\(personID)", ["shown": v]) } }))
                    } else {
                        Label(model.sharesIn[personID] == nil
                              ? "They haven't shared theirs with you"
                              : "They share theirs with you (\(model.sharesIn[personID]!))",
                              systemImage: model.sharesIn[personID] == nil ? "eye.slash" : "eye")
                    }
                } header: { Text("Their calendar & to-dos") }
                  footer: {
                      Text(isAdmin
                           ? "On: their items join your calendar and to-dos, with their name and a stripe in their colour. \(model.sharesIn[personID] == nil ? "They don't share with you — as admin you can still see them." : "They share with you, so this starts on.")"
                           : "Only they can share theirs.")
                  }

                if isAdmin {
                    Section {
                        Toggle("Share my vocabulary", isOn: Binding(
                            get: { model.vocab.contains(personID) },
                            set: { v in Task { await put("/admin/vocab_share/\(personID)", ["on": v]) } }))
                    } footer: { Text("The names and words you've taught the assistant help it hear them too.") }

                    Section {
                        Button("Reset password") { Task { await reset() } }
                        if let pw = revealed {
                            Text("New password — shown once. They'll choose their own when they sign in.")
                                .font(.footnote)
                            Text(pw).font(.system(.title3, design: .monospaced)).textSelection(.enabled)
                        }
                        Button("Sign out on every device") { Task { await signOut() } }
                        Button(account?.disabled == true ? "Enable account" : "Disable account",
                               role: account?.disabled == true ? nil : .destructive) {
                            Task {
                                if let e = await accountCall(api, "/admin/users/\(personID)", method: "PATCH",
                                                             body: ["disabled": !(account?.disabled ?? false)]) {
                                    note = "Couldn't change that: \(e)"
                                } else { note = "" }
                                await model.load(api)
                            }
                        }
                    } header: { Text("Their account") }

                    Section {
                        Button("Remove this account…", role: .destructive) { confirmRemove = true }
                    } footer: {
                        Text("Signs them out everywhere and takes them off this Mac. Their calendar is set aside on the Mac, not erased.")
                    }
                }

                if !note.isEmpty {
                    Section { Text(note).font(.footnote).foregroundColor(note.hasPrefix("Couldn't") ? .red : .secondary) }
                }
            } else {
                ProgressView()
            }
        }
        .listStyle(.insetGrouped)
        .confirmationDialog("Remove \(person?.displayName ?? "this account")?", isPresented: $confirmRemove,
                            titleVisibility: .visible) {
            Button("Remove", role: .destructive) {
                Task {
                    if let e = await accountCall(api, "/admin/users/\(personID)", method: "DELETE") {
                        note = "Couldn't remove them: \(e)"
                    } else { note = "Removed." }
                    await model.load(api)
                }
            }
        }
        .navigationTitle(person?.displayName ?? "")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear { Task { await model.load(api) } }
    }

    private func put(_ path: String, _ body: [String: Any]) async {
        note = await accountCall(api, path, body: body).map { "Couldn't change that: \($0)" } ?? ""
        await model.load(api)
    }

    private func signOut() async {
        do {
            let data = try await api.request("/admin/users/\(personID)/signout", method: "POST", body: [:])
            let obj = (try? JSONSerialization.jsonObject(with: data) as? [String: Any]) ?? [:]
            let n = obj["signed_out"] as? Int ?? 0
            note = "Signed out of \(n) device\(n == 1 ? "" : "s"). Their password is unchanged."
        } catch {
            note = "Couldn't sign them out: \(error.localizedDescription)"
        }
        await model.load(api)
    }

    private func reset() async {
        do {
            let data = try await api.request("/admin/users/\(personID)/password", method: "POST", body: [:])
            let obj = (try? JSONSerialization.jsonObject(with: data) as? [String: Any]) ?? [:]
            revealed = obj["password"] as? String
            note = revealed == nil ? "Couldn't reset it: the Mac sent no password." : ""
        } catch {
            note = "Couldn't reset it: \(error.localizedDescription)"
        }
    }
}

// MARK: - the Account tab

/// The Account tab: the same Account page for everyone (DEVQA Q65) — the
/// admin's extra controls appear on it and on each person's page.
struct AccountTabView: View {
    var body: some View {
        StackNavigation { AccountView() }
    }
}

// MARK: - sharing helpers

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
