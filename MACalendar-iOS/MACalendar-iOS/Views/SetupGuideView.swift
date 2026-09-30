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
                    point("checkmark.circle", "Voice commands that ADD things, read by Apple's on-device model — needs iOS 26 with Apple Intelligence on")
                    point("xmark.circle", "Moving, changing or deleting by voice, the command memory and review, other devices and sharing — those need a Mac")
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

            Section {
                Toggle("Show the connection line", isOn: $settings.showConnectionBanner)
                    .disabled(settings.phoneOnly)
            } footer: {
                Text("The orange line at the top when your Mac can't be reached (grey when you've switched the connection off).")
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
