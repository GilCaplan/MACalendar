import SwiftUI

/// Everything you set before asking: the mode, how wide to retrieve, which
/// language to answer in, and the question itself.
///
/// It is one view rather than a toolbar plus a text field because all four are
/// part of the same decision — "sources mode, 30 passages, in Hebrew" is one
/// question asked one way, and splitting the controls across the screen made
/// the mode look like a view filter rather than part of the ask.
struct JudeComposer: View {
    @Binding var draft: String
    @Binding var mode: String
    @Binding var lang: String
    @Binding var topK: Double
    let isBusy: Bool
    let onSend: () -> Void

    @EnvironmentObject var settings: AppSettings
    @FocusState private var focused: Bool

    private var canSend: Bool {
        !isBusy && !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var body: some View {
        VStack(spacing: 8) {
            Picker("Mode", selection: $mode) {
                Text("Q&A").tag("qa")
                Text("Study").tag("study")
                Text("Sources").tag("sources")
            }
            .pickerStyle(.segmented)
            .disabled(isBusy)

            options

            disclaimerRow

            HStack(alignment: .bottom, spacing: 8) {
                TextField(placeholder, text: $draft, axis: .vertical)
                    .lineLimit(1...5)
                    .textFieldStyle(.roundedBorder)
                    .focused($focused)
                    .disabled(isBusy)
                    // Hebrew is written right to left, and a left-aligned
                    // field put the caret before the first letter typed.
                    .environment(\.layoutDirection,
                                 lang == "he" ? .rightToLeft : .leftToRight)

                Button {
                    focused = false
                    onSend()
                } label: {
                    Image(systemName: "arrow.up.circle.fill")
                        .font(.system(size: 30))
                        .foregroundColor(canSend ? settings.accentColor : .secondary)
                }
                .disabled(!canSend)
                .accessibilityLabel("Ask Jude")
            }
        }
        .padding(12)
        .background(Color(.systemBackground))
    }

    private var placeholder: String {
        switch mode {
        case "study": return "A sugya or topic to study…"
        case "sources": return "What to find sources on…"
        default: return "Ask about Torah, Talmud, halacha…"
        }
    }

    @ViewBuilder
    private var options: some View {
        HStack(spacing: 12) {
            // In sources mode the count comes from the router's source plan,
            // not from here — showing a slider that changes nothing is worse
            // than showing none, so it goes away with its label.
            if mode != "sources" {
                Text("\(Int(topK))")
                    .font(.caption.monospacedDigit().weight(.semibold))
                    .frame(width: 24, alignment: .trailing)
                Slider(value: $topK, in: 5...30, step: 1)
                    .tint(settings.accentColor)
                    .disabled(isBusy)
                    .accessibilityLabel("Passages to retrieve")
                    .accessibilityValue("\(Int(topK))")
            } else {
                Text("Source count comes from the router's plan")
                    .font(.caption2).foregroundColor(.secondary)
                Spacer()
            }

            Picker("Language", selection: $lang) {
                Text("EN").tag("en")
                Text("עב").tag("he")
            }
            .pickerStyle(.segmented)
            .frame(width: 92)
            .disabled(isBusy)
        }
    }

    /// The same sentence the Mac app carries (`jude/ui/composer.py`), because a
    /// caveat that appears on one surface and not the other is worse than none:
    /// it implies the other surface is the trustworthy one.
    ///
    /// It sits under the composer rather than over the answer deliberately —
    /// visible whenever you are about to ask, not only after you have already
    /// believed something. The model is `llama3.1:8b` doing synthesis over
    /// retrieved passages: the CITATIONS are real and checkable on Sefaria,
    /// the reasoning joining them is not authoritative.
    private var disclaimerRow: some View {
        HStack(alignment: .top, spacing: 4) {
            Image(systemName: "exclamationmark.triangle")
                .font(.caption2)
            Text("Jude can misread its sources and state things they do not "
                 + "say. The citations are real — check them on Sefaria — and "
                 + "verify any ruling with a qualified rabbi.")
                .font(.caption2)
                .fixedSize(horizontal: false, vertical: true)
        }
        .foregroundColor(.secondary)
    }
}
