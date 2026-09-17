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

    /// The shared recorder — the same one the calendar's voice button uses, so
    /// there is one place that knows how to capture audio on this device.
    @ObservedObject var recorder: VoiceRecorder
    let isTranscribing: Bool
    let onDictate: () -> Void

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
                // Taller than the rest of the app's fields on purpose: a
                // question for Jude is a sentence or two ("why do we light two
                // candles, and does it differ on yom tov?"), not "add lunch at
                // 1". Three lines before it scrolls instead of one.
                TextField(placeholder, text: $draft, axis: .vertical)
                    .lineLimit(3...8)
                    .frame(minHeight: 64, alignment: .top)
                    .textFieldStyle(.roundedBorder)
                    .focused($focused)
                    .disabled(isBusy || isTranscribing)
                    // Hebrew is written right to left, and a left-aligned
                    // field put the caret before the first letter typed.
                    .environment(\.layoutDirection,
                                 lang == "he" ? .rightToLeft : .leftToRight)

                // Ask out loud. It fills the field rather than sending, so a
                // mangled word can be fixed before it is asked — Whisper is
                // trained on English and these are the questions most full of
                // words it has never heard.
                Button {
                    focused = false
                    onDictate()
                } label: {
                    Image(systemName: recorder.isRecording ? "stop.circle.fill"
                                    : (isTranscribing ? "waveform" : "mic.circle.fill"))
                        .font(.system(size: 30))
                        .foregroundColor(recorder.isRecording ? .red
                                         : (isTranscribing ? .secondary : settings.accentColor))
                        // Not `.symbolEffect(.pulse)` — that is iOS 17 and the
                        // deployment target is 16.
                        .opacity(isTranscribing ? 0.45 : 1)
                        .animation(isTranscribing
                                   ? .easeInOut(duration: 0.6).repeatForever(autoreverses: true)
                                   : .default,
                                   value: isTranscribing)
                }
                .disabled(isBusy || isTranscribing)
                .accessibilityIdentifier("jude-dictate")
                .accessibilityLabel(recorder.isRecording ? "Stop recording" : "Ask by voice")

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
            if recorder.isRecording {
                Text("Listening… tap ■ when you are done")
                    .font(.caption2).foregroundColor(.secondary)
            } else if isTranscribing {
                Text("Turning that into words on your Mac…")
                    .font(.caption2).foregroundColor(.secondary)
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
