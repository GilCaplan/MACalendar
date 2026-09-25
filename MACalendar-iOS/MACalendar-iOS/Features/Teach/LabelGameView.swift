import SwiftUI

/// Teach the labeller, one tap at a time.
///
/// Gil, 2026-09-10: *"create a tab in the iOS app as sort of a game to label —
/// have the claim/prompt then multiple choice boxes with the tags, and once I'm
/// done it auto updates where relevant."*
///
/// ## Why this screen is worth a tab
///
/// The event classifier has one honest evaluation set and 81 rows in it, and
/// **Claude labelled them, not the user** (`engine/label/datasets/REAL_GOLD.md`).
/// Every other label this project owns is the keyword rules' own output, which
/// is why a decision tree once scored exactly 100% against them and meant
/// nothing. A person tapping a category is the only source of a label the
/// system did not already believe.
///
/// ## It asks the HARD ones
///
/// The server orders the queue by where the system is weakest — rules punted
/// AND the model was unsure, then rules-vs-model disagreements, then cheap
/// confirmations. A tap on a row the rules already had right teaches nothing,
/// so those are never shown.
struct LabelGameView: View {
    @EnvironmentObject var api: APIClient
    @Environment(\.colorScheme) private var scheme

    @State private var items: [LabelItem] = []
    @State private var options: [String] = []
    @State private var index = 0
    @State private var labelledThisSession = 0
    @State private var labelledTotal = 0
    @State private var remaining = 0
    @State private var loading = true
    @State private var error: String?
    @State private var retrainDue = false
    @State private var retraining = false
    @State private var retrainNote: String?

    private var current: LabelItem? {
        index < items.count ? items[index] : nil
    }

    var body: some View {
        StackNavigation {
            Group {
                if loading {
                    ProgressView("Finding the hard ones…")
                } else if let error {
                    VStack(spacing: 12) {
                        Image(systemName: "wifi.slash").font(.largeTitle)
                        Text(error).font(.footnote).multilineTextAlignment(.center)
                        Button("Try again") { Task { await load() } }
                    }.padding()
                } else if let item = current {
                    card(item)
                } else {
                    done
                }
            }
            .navigationTitle("Teach")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Text("\(labelledTotal) taught")
                        .font(.caption).foregroundColor(.secondary)
                }
            }
        }
        .task { await load() }
    }

    // MARK: - the card

    private func card(_ item: LabelItem) -> some View {
        VStack(spacing: 18) {
            // Progress through THIS batch, not through everything — a bar that
            // never visibly moves is worse than none.
            ProgressView(value: Double(index), total: Double(max(items.count, 1)))
                .padding(.horizontal)

            Spacer(minLength: 0)

            VStack(spacing: 8) {
                Text("What kind of thing is this?")
                    .font(.footnote).foregroundColor(.secondary)
                Text(item.text)
                    .font(.title2.weight(.semibold))
                    .multilineTextAlignment(.center)
                    .padding(.horizontal)
                if let s = item.suggestion {
                    // Shown, but AFTER the question and quietly. A suggestion
                    // shown first is an anchor, and an anchored answer is the
                    // model's opinion wearing the user's name.
                    Text("the app guesses \(s)")
                        .font(.caption2).foregroundColor(.secondary)
                }
            }

            Spacer(minLength: 0)

            LazyVGrid(columns: [GridItem(.adaptive(minimum: 108), spacing: 8)],
                      spacing: 8) {
                ForEach(options, id: \.self) { option in
                    Button { Task { await choose(option, for: item) } } label: {
                        Text(option)
                            .font(.callout.weight(.medium))
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 12)
                            .background(Color.accentColor.opacity(0.14))
                            .foregroundColor(.accentColor)
                            .clipShape(RoundedRectangle(cornerRadius: 10))
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal)

            Button("Skip — I'm not sure") { advance() }
                .font(.footnote)
                .foregroundColor(.secondary)
                .padding(.bottom, 8)
        }
        .padding(.vertical)
    }

    // MARK: - the end of a batch

    private var done: some View {
        VStack(spacing: 14) {
            Image(systemName: "checkmark.seal.fill")
                .font(.system(size: 44)).foregroundColor(.green)
            Text(labelledThisSession > 0
                 ? "\(labelledThisSession) taught this round"
                 : "Nothing needs you right now")
                .font(.headline)
            if remaining > 0 {
                Text("\(remaining) more waiting")
                    .font(.footnote).foregroundColor(.secondary)
                Button("Keep going") { Task { await load() } }
                    .buttonStyle(.borderedProminent)
            }
            if retrainDue {
                // "auto updates where relevant" — but a retrain is a real
                // change to what the app decides, so it is offered rather than
                // done silently. The gate still applies: a model that is not
                // better than the installed one does not ship.
                Divider().padding(.vertical, 6)
                Text("Enough new answers to re-learn.")
                    .font(.footnote)
                Button(retraining ? "Learning…" : "Re-learn now") {
                    Task { await retrain() }
                }
                .disabled(retraining)
                .buttonStyle(.bordered)
            }
            if let retrainNote {
                Text(retrainNote)
                    .font(.caption).foregroundColor(.secondary)
                    .multilineTextAlignment(.center).padding(.horizontal)
            }
        }
        .padding()
    }

    // MARK: - actions

    private func load() async {
        loading = true; error = nil
        do {
            let batch = try await api.labelQueue(kind: "event", n: 20)
            items = batch.items
            options = batch.options
            remaining = batch.remaining
            labelledTotal = batch.labelled
            index = 0
        } catch {
            self.error = "Your Mac isn't reachable, so there's nothing to teach right now."
        }
        loading = false
    }

    private func choose(_ label: String, for item: LabelItem) async {
        // Advance FIRST. The tap should feel instant; a round trip between taps
        // turns a game into a form.
        advance()
        labelledThisSession += 1
        labelledTotal += 1
        do {
            let due = try await api.recordLabel(kind: "event", text: item.text,
                                                label: label, current: item.current)
            retrainDue = due
        } catch {
            // A lost label is not worth interrupting for — the row simply comes
            // back in a later batch, because the server excludes only the ones
            // it actually recorded.
        }
    }

    private func advance() { index += 1 }

    private func retrain() async {
        retraining = true; retrainNote = nil
        do {
            let note = try await api.retrainLabels(kind: "event")
            retrainNote = note
            retrainDue = false
        } catch {
            retrainNote = "Couldn't re-learn just now."
        }
        retraining = false
    }
}

struct LabelItem: Decodable, Identifiable {
    var id: String { text }
    let text: String
    let current: String?
    let suggestion: String?
}

struct LabelBatch: Decodable {
    let options: [String]
    let items: [LabelItem]
    let remaining: Int
    let labelled: Int
}
