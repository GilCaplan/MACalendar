import SwiftUI

/// Settings ▸ How it runs: with a Mac (the full assistant), or this phone on
/// its own — and, for the Mac, how to set it up, step by step.
struct SetupGuideView: View {
    @EnvironmentObject var settings: AppSettings
    @State private var copied: String?

    private static let command =
        "curl -fsSL https://raw.githubusercontent.com/GilCaplan/MACalendar/main/install/install-macalendar.sh | bash"
    private static let repo = "https://github.com/GilCaplan/MACalendar"

    var body: some View {
        Form {
            Section {
                Picker("Runs on", selection: $settings.phoneOnly) {
                    Text("My Mac and this phone").tag(false)
                    Text("This phone only").tag(true)
                }
                .pickerStyle(.inline)
                .labelsHidden()
            } footer: {
                Text(settings.phoneOnly
                     ? "Everything stays on this phone. You can set up a Mac any time; what you made here goes to it then."
                     : "Your Mac is the brain: it hears you with Whisper, understands with a language model, keeps the "
                       + "calendar, and your phone joins it from anywhere.")
            }

            if settings.phoneOnly {
                Section("On this phone alone") {
                    point("checkmark.circle", "Calendar, to-dos, reminders, the Hebrew calendar, tags and colours")
                    point("checkmark.circle", "Voice and typed commands, read on this phone: add, move, rename, delete, tick off, "
                          + "and “what do I have tomorrow?” — on any iPhone, with Apple's on-device model helping where it's available")
                    point("checkmark.circle", "Repeating events, the icons beside titles, and everything working with no signal at all")
                    point("xmark.circle", "Jude, Teach, accounts and sharing, other devices, and the Mac's learning from your corrections — those need a Mac")
                    point("wifi.slash", "No “offline” line at the top — there's nothing to be offline from")
                }
            } else {
                Section("Set it up") {
                    step(1, "Install the server on your Mac",
                         "In Terminal, run this. It installs everything, asks a couple of questions, and puts MACalendar Server in your menu bar.")
                    copyRow(Self.command)
                    Link("Or download the installer from GitHub", destination: URL(string: Self.repo)!)
                        .font(.callout)
                    step(2, "Choose the model",
                         "The installer sets up Ollama, a free model that runs on your Mac — nothing leaves it. "
                         + "Prefer a cloud model? Set llm_engine to claude, openai or gemini and its api_key in the "
                         + "Mac's config.yaml. Your commands are then sent to that company.")
                    step(3, "Connect them with Tailscale",
                         "Install Tailscale on the Mac and on this phone and sign in with the same account. "
                         + "It lets the phone reach your Mac from anywhere, privately. On the same Wi-Fi you can skip it.")
                    Link("Get Tailscale", destination: URL(string: "https://tailscale.com/download")!).font(.callout)
                    step(4, "Pair this phone",
                         "In the Mac's menu bar: MACalendar Server ▸ Pair a phone, then scan the QR code with the "
                         + "Camera. Or open Settings ▸ Your Mac here and pick it from the list.")
                }
            }

            if !settings.phoneOnly {
                Section {
                    Toggle("Read on this phone first", isOn: $settings.readOnPhoneFirst)
                } footer: {
                    Text("This phone reads each command and does it straight away, without waiting for your Mac. "
                         + "Your Mac reads it too in the background; its version is the one that's kept, "
                         + "and you're told if it understood it differently.")
                }
            }

            Section {
                Toggle("Show the connection lines", isOn: $settings.showConnectionBanner)
                    .disabled(settings.phoneOnly)
            } footer: {
                Text("Strips at the top of the screen when your Mac can't be reached and when commands are waiting for it. Off by default — Settings ▸ Your Mac always shows both.")
            }
        }
        .navigationTitle("How it runs")
    }

    private func point(_ icon: String, _ text: String) -> some View {
        Label { Text(text).font(.callout) } icon: { Image(systemName: icon).foregroundColor(.accentColor) }
    }

    private func step(_ n: Int, _ title: String, _ detail: String) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Text("\(n)").font(.headline).foregroundColor(.white)
                .frame(width: 26, height: 26).background(Circle().fill(Color.accentColor))
            VStack(alignment: .leading, spacing: 4) {
                Text(title).font(.headline)
                Text(detail).font(.callout).foregroundColor(.secondary)
            }
        }
        .padding(.vertical, 4)
    }

    private func copyRow(_ text: String) -> some View {
        HStack {
            Text(text).font(.system(.caption, design: .monospaced)).lineLimit(3).textSelection(.enabled)
            Spacer()
            Button(copied == text ? "Copied" : "Copy") {
                UIPasteboard.general.string = text
                copied = text
            }
            .buttonStyle(.bordered)
        }
    }
}


/// The first screen of a fresh install (DEVQA Q85): this iPhone on its own,
/// or with a Mac. Asked once; Settings ▸ How it runs changes it any time.
struct WelcomeView: View {
    @EnvironmentObject var settings: AppSettings
    let done: () -> Void
    @State private var showMac = false

    var body: some View {
        NavigationView {
            VStack(spacing: 22) {
                Spacer()
                Image(systemName: "calendar.badge.clock")
                    .font(.system(size: 54, weight: .semibold))
                    .foregroundColor(.accentColor)
                Text("MACalendar").font(.largeTitle.weight(.bold))
                Text("A calendar and to-do list you can talk to.")
                    .font(.title3).foregroundColor(.secondary).multilineTextAlignment(.center)
                Spacer()
                choice("Use it on this iPhone", "Everything stays on this phone, and works with no signal. "
                       + "You can add a Mac later — what you made goes with it.", "iphone", id: "welcome-phone") {
                    settings.phoneOnly = true
                    finish()
                }
                choice("Connect my Mac", "Your Mac becomes the brain: it hears you with Whisper, understands with a "
                       + "local language model, and keeps your devices in step.", "laptopcomputer", id: "welcome-mac") {
                    showMac = true
                }
                Spacer().frame(height: 12)
            }
            .padding(.horizontal, 22)
            .background(
                NavigationLink(isActive: $showMac) {
                    SetupGuideView()
                        .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { finish() } } }
                } label: { EmptyView() }
            )
        }
    }

    private func finish() {
        // A new install starts with the Jewish calendar off (Gil, 2026-10-02);
        // Settings ▸ Hebrew calendar turns it on. Local only: a Mac paired
        // later brings its own settings, and the phone takes them.
        settings.setJewishCalendar(false)
        UserDefaults.standard.set(true, forKey: "welcomeDone")
        done()
    }

    private func choice(_ title: String, _ detail: String, _ icon: String, id: String,
                        action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(alignment: .top, spacing: 14) {
                Image(systemName: icon).font(.title2).frame(width: 34).foregroundColor(.accentColor)
                VStack(alignment: .leading, spacing: 4) {
                    Text(title).font(.headline).foregroundColor(.primary)
                    Text(detail).font(.subheadline).foregroundColor(.secondary).multilineTextAlignment(.leading)
                }
                Spacer(minLength: 0)
            }
            .padding(16)
            .background(RoundedRectangle(cornerRadius: 14).fill(Color(.secondarySystemBackground)))
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier(id)
    }
}
