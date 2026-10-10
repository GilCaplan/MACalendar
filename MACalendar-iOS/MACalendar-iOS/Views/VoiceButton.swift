import SwiftUI
import AVFoundation

struct VoiceButton: View {
    @EnvironmentObject var api: APIClient
    @EnvironmentObject var settings: AppSettings
    @StateObject private var recorder = VoiceRecorder()
    @StateObject private var player  = SpeechPlayer()

    @State private var status: Status = .idle
    @State private var offNote = false
    var onRefresh: ((String) -> Void)?
    /// Full response, for callers that need more than the refresh string —
    /// e.g. the Workout tab keys off `actions.contains("generate_workout_routine")`
    /// since the backend's `refresh` field has no workout-specific value (it's
    /// a hardcoded "event"/"todo" substring match — see server.py).
    var onResponse: ((VoiceResponse) -> Void)?

    // Live "thinking" trace (Settings › Voice › Show assistant thinking)
    @State private var steps: [TraceStep] = []
    @State private var finished = false
    @State private var lastResponse: VoiceResponse?
    @State private var showThinking = false
    @State private var fixWord: String? = nil
    @State private var showFix = false
    /// Set when the host returns needs_edit — drives the transcription editor.
    @State private var editRequest: EditRequest?
    /// Set when the host returns confirm_create — drives the "add this?" alert.
    /// Nothing has been created at this point; the alert's answer decides.
    @State private var confirmRequest: ConfirmRequest?
    /// Rows a destructive background self-check removed — drives the Revert banner.
    @State private var pendingRevert: [RevertItem] = []

    enum Status { case idle, recording, review, thinking, speaking }
    /// Audio captured but not yet sent — the user can Redo / Add more / Send.
    @State private var pendingAudio: Data?
    /// What the phone heard for `pendingAudio` — sent instead of it.
    @State private var pendingHeard = ""
    /// Between the mic stopping and the phone's last words arriving.
    @State private var finishing = false
    /// This command's magic words have played — once per command.
    @State private var eggPlayed = false
    /// The wait the loading screen watches while a command thinks.
    @State private var eggWait: UUID?
    @State private var sendCountdown = 0
    @State private var countdownTask: Task<Void, Never>?
    /// The command in flight. Cancelling it, redoing it or adding to it sets
    /// this to nil: the Mac keeps going (it already has the audio), so its
    /// reply is still read — to remove what it added — but no longer shown.
    @State private var inFlight: UUID?

    /// True while there is something worth reopening: work in flight, or a result
    /// from the last ~2 minutes.
    private var canReopen: Bool {
        status == .thinking || status == .speaking || (finished && lastResponse != nil && Date().timeIntervalSince(finishedAt) < 120)
    }
    @State private var finishedAt = Date.distantPast
    /// The host's one-line coaching for the reply just given ("say what it's
    /// about"), drawn above the mic once per code, dismissed by a tap or on
    /// its own. Never a modal: it must not get in the way (Gil, 2026-09-22).
    @State private var hint: ReplyHint?
    @State private var hintTask: Task<Void, Never>?
    /// Typing instead of speaking (Gil, 2026-10-01): the sheet, and its text.
    @State private var typing = false
    @State private var typed = ""

    var body: some View {
        // The keyboard is a small badge on the mic's edge, not a third button:
        // the bottom row keeps its size and the mic stays where it was
        // (Gil, 2026-10-01: intuitive without taking too much space).
        micWithChips
            .overlay(alignment: .bottomLeading) { keyboardButton.offset(x: -10, y: 6) }
            .sheet(isPresented: $typing) { typeSheet }
    }

    /// Type a command instead of saying it — everything after is the spoken
    /// path's: the thinking panel, the review, magic words, cancel.
    private var keyboardButton: some View {
        Button {
            if !api.assistantEnabled {
                Task {
                    _ = try? await api.health()
                    if api.assistantEnabled { typing = true } else { offNote = true }
                }
                return
            }
            typing = true
        } label: {
            Image(systemName: "keyboard")
                .font(.system(size: 11, weight: .bold))
                .foregroundColor(.primary)
                .frame(width: 26, height: 26)
                .background(Circle().fill(.regularMaterial))
                .overlay(Circle().stroke(Color.secondary.opacity(0.35), lineWidth: 0.5))
                .shadow(radius: 1.5)
                .frame(width: 40, height: 40)          // a finger-sized target around a small badge
                .contentShape(Circle())
        }
        .accessibilityIdentifier("type-command-button")
        .accessibilityLabel("Type a command")
        .opacity(status == .idle ? (api.assistantEnabled ? 1 : 0.4) : 0)
        .disabled(status != .idle)
    }

    private var typeSheet: some View {
        TypeCommandSheet(text: $typed) { text in
            typing = false
            typed = ""
            sendTyped(text)
        }
    }

    private var micWithChips: some View {
        // The chip floats above the mic as an overlay so the mic never moves and
        // stays level with the "+" button next to it.
        micButton.overlay(alignment: .top) {
            if status == .review {
                HStack(spacing: 6) {
                    Button { redo() } label: { Label("Redo", systemImage: "arrow.counterclockwise") }
                    Button { addMore() } label: { Label("Add more", systemImage: "mic.badge.plus") }
                    Button { sendPending() } label: {
                        Label(sendCountdown > 0 ? "Send \(sendCountdown)" : "Send", systemImage: "paperplane.fill")
                    }
                    .buttonStyle(.borderedProminent)
                    discardButton
                }
                .font(.caption.weight(.medium))
                .buttonStyle(.bordered)
                .controlSize(.small)
                .padding(6)
                .background(.regularMaterial)
                .clipShape(Capsule())
                .shadow(radius: 2)
                .fixedSize()
                .offset(y: -44)
                .transition(.opacity.combined(with: .move(edge: .bottom)))
            } else if status == .recording && settings.micVisual == "card" {
                // The default style (Settings ▸ Voice ▸ While recording): a
                // card above the mic, its bottom 12 pt over the mic's top.
                WaveformCard(levels: recorder.levels, startedAt: recorder.startedAt,
                             soundSeen: recorder.soundSeen, heard: recorder.liveText,
                             onDiscard: { discard() })
                    .fixedSize()
                    // Hung from a zero-height box at the mic's top edge, so it
                    // grows UP from there. An alignmentGuide here was ignored
                    // and the card sat over the mic and under the tab bar
                    // (seen in the simulator, 2026-10-10).
                    .frame(width: 308, height: 0, alignment: .bottom)
                    .offset(y: -12)
                    .transition(.opacity.combined(with: .move(edge: .bottom)))
            } else if status == .recording {
                // Stopping the recording sends it — on the countdown path or
                // straight away. Until this there was no way to change your
                // mind mid-sentence except to let the command run and undo it.
                HStack(spacing: 6) {
                    ListeningMeter(levels: recorder.levels, startedAt: recorder.startedAt,
                                   soundSeen: recorder.soundSeen)
                    discardButton
                }
                .font(.caption.weight(.medium))
                .buttonStyle(.bordered)
                .controlSize(.small)
                .padding(6)
                .background(.regularMaterial)
                .clipShape(Capsule())
                .shadow(radius: 2)
                .fixedSize()
                .offset(y: -44)
                .transition(.opacity.combined(with: .move(edge: .bottom)))
            } else if status == .thinking {
                // While it works: change your mind (Gil, 2026-10-01 — "why
                // can't i rerecord or cancel prompt … support cancelling /
                // rerecording / adding to original prompt more audio").
                HStack(spacing: 6) {
                    if settings.showThinking {
                        Button { showThinking = true } label: {
                            HStack(spacing: 4) {
                                EggSpinner(side: 16)
                                Text("\(steps.count)")
                            }
                        }
                        .accessibilityLabel("Show what it's doing, \(steps.count) steps")
                    }
                    Button { abandon(.redo) } label: { Label("Redo", systemImage: "arrow.counterclockwise") }
                    Button { abandon(.addMore) } label: { Label("Add more", systemImage: "mic.badge.plus") }
                    Button(role: .destructive) { abandon(.cancel) } label: { Image(systemName: "xmark") }
                        .tint(.red)
                        .accessibilityLabel("Cancel this command")
                }
                .font(.caption.weight(.medium))
                .buttonStyle(.bordered)
                .controlSize(.small)
                .padding(6)
                .background(.regularMaterial)
                .clipShape(Capsule())
                .shadow(radius: 2)
                .fixedSize()
                .offset(y: -44)
                .transition(.opacity.combined(with: .move(edge: .bottom)))
            } else if settings.showThinking && !showThinking && canReopen {
                Button { showThinking = true } label: {
                    HStack(spacing: 6) {
                        if status == .thinking { EggSpinner(side: 18) }
                        else { AssistantIcon(finished ? .done : .llm).frame(width: 12, height: 12) }
                        Text(status == .thinking ? "Thinking… \(steps.count) step\(steps.count == 1 ? "" : "s")"
                             : status == .speaking ? "Speaking…" : "Show what it did")
                            .font(.caption.weight(.medium))
                    }
                    .padding(.horizontal, 10).padding(.vertical, 5)
                    .background(.regularMaterial)
                    .clipShape(Capsule())
                    .shadow(radius: 2)
                }
                .buttonStyle(.plain)
                .fixedSize()
                .offset(y: -40)
                .transition(.opacity.combined(with: .move(edge: .bottom)))
            }
        }
        .overlay(alignment: .top) {
            if let h = hint { hintCard(h) }
        }
        .animation(.easeInOut(duration: 0.2), value: hint)
        .animation(.easeInOut(duration: 0.2), value: canReopen)
        .animation(.easeInOut(duration: 0.2), value: status)
        .sheet(item: $editRequest) { req in
            EditTranscriptionSheet(text: req.text, doubtful: req.doubtful) { corrected in
                resubmitEdited(corrected, editedFrom: req.text)
            }
            .presentationDetents([.medium, .large])
            .presentationDragIndicator(.visible)
        }
        // "should I add yoga tomorrow?" — a question, so the host parsed it and
        // created nothing. Add creates it; No discards it and files the verdict.
        .alert("Add this?", isPresented: Binding(
            get: { confirmRequest != nil },
            set: { if !$0 { confirmRequest = nil } }
        ), presenting: confirmRequest) { req in
            Button("Add") { answerConfirm(req, accept: true) }
            Button("No", role: .cancel) { answerConfirm(req, accept: false) }
        } message: { req in
            Text(req.items.isEmpty ? req.prompt
                 : req.prompt + "\n\n" + req.items.map { "\u{2022} " + $0.summary }
                    .joined(separator: "\n"))
        }
    }

    /// Throw the recording away without sending it. The Mac's review bar has
    /// had this since it existed; the phone's only exits were Send and Redo,
    /// so a recording started by accident had to be sent and then undone.
    /// The tip card: a lightbulb, the headline, one line of body, an ✕. It
    /// sits above the "Show what it did" chip so neither hides the other.
    private func hintCard(_ h: ReplyHint) -> some View {
        Button { dismissHint() } label: {
            HStack(alignment: .top, spacing: 8) {
                Image(systemName: "lightbulb.fill").foregroundColor(.yellow)
                VStack(alignment: .leading, spacing: 2) {
                    Text(h.headline).font(.caption.weight(.semibold))
                    Text(h.body).font(.caption2).foregroundColor(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Image(systemName: "xmark").font(.caption2).foregroundColor(.secondary)
            }
            .multilineTextAlignment(.leading)
            .padding(10)
            .frame(width: 280, alignment: .leading)
            .background(.regularMaterial)
            .clipShape(RoundedRectangle(cornerRadius: 12))
            .shadow(radius: 2)
        }
        .buttonStyle(.plain)
        .offset(y: -104)
        .transition(.opacity.combined(with: .move(edge: .bottom)))
        .accessibilityLabel("Tip: \(h.headline). \(h.body)")
    }

    private func showHint(_ h: ReplyHint) {
        hintTask?.cancel()
        hint = h
        hintTask = Task {
            try? await Task.sleep(nanoseconds: 12_000_000_000)
            if !Task.isCancelled { await MainActor.run { hint = nil } }
        }
    }

    private func dismissHint() {
        hintTask?.cancel()
        hint = nil
    }

    private var discardButton: some View {
        Button(role: .destructive) { discard() } label: {
            Image(systemName: "trash")
        }
        .tint(.red)
        .accessibilityLabel("Discard recording")
    }

    private var micButton: some View {
        Button(action: handleTap) {
            ZStack {
                // Rings that swell with your voice — the live sign the phone
                // is hearing you. Replaced a "pulsing" ring that never moved.
                if status == .recording {
                    switch settings.micVisual {
                    case "rings":    MicLevelRings(level: recorder.level)
                    case "sunburst": MicSunburst(levels: recorder.levels)
                    case "dots":     MicDots(levels: recorder.levels)
                    default:         EmptyView()      // "card": the card above is the meter
                    }
                }
                Circle()
                    .fill(buttonColor)
                    .frame(width: 60, height: 60)
                    .shadow(radius: status == .idle ? 4 : 8)

                if status == .thinking {
                    EggSpinner(side: 40)
                } else {
                    Image(systemName: iconName)
                        .font(.system(size: 24, weight: .semibold))
                        .foregroundColor(iconColor)
                }

            }
        }
        .accessibilityIdentifier("mic-button")
        .opacity(api.assistantEnabled || status != .idle ? 1 : 0.4)
        .alert("The assistant is off", isPresented: $offNote) {
            Button("OK", role: .cancel) {}
        } message: {
            Text("Turn it on in Settings ▸ Assistant (here or on your Mac).")
        }
        // Turning "speak replies" off should stop the sentence already being
        // read, not just suppress the next one. The guards at the call sites
        // are checked before an utterance starts, so an in-flight reply
        // carried on talking after the switch was flipped.
        // Single-argument form: the two-argument onChange is iOS 17+, and this
        // project's deployment target is lower.
        .onChange(of: settings.speakReplies) { on in
            if !on { player.stop() }
        }
        .onChange(of: showThinking) { open in
            if open {
                EggWaits.shared.end(eggWait); eggWait = nil
            } else if status == .thinking {
                beginScreenWaitUnlessPanel()
            }
        }
        .sheet(isPresented: $showThinking) {
            ThinkingView(
                steps: steps,
                finished: finished,
                response: lastResponse,
                onFixWord: { word in fixWord = word; showFix = true },
                onFeedback: { fb in
                    if let id = lastResponse?.memoryId { Task { await api.memoryFeedback(id: id, feedback: fb) } }
                },
                onRetry: { pid in
                    finished = false
                    steps.append(TraceStep(stage: "llm", title: "Retrying", detail: "Running the saved command again…",
                                           ms: 0, atMs: steps.last?.atMs ?? 0, ok: true))
                    Task {
                        do {
                            let r = try await api.retryPending(id: pid)
                            await handleResponse(r)
                        } catch {
                            steps.append(TraceStep(stage: "error", title: "Retry failed",
                                                   detail: error.localizedDescription, ms: 0,
                                                   atMs: steps.last?.atMs ?? 0, ok: false))
                            finished = true
                        }
                    }
                },
                revertItems: pendingRevert,
                onRevert: {
                    let items = pendingRevert
                    pendingRevert = []
                    Task { await api.revert(items) }
                }
            )
            .presentationDetents([.medium, .large])
            .presentationDragIndicator(.visible)
            .sheet(isPresented: $showFix) {
                if let w = fixWord {
                    QuickFixSheet(wrong: w) { right in
                        Task { try? await api.vocabTeach(wrong: w, right: right) }
                    }
                    .presentationDetents([.height(240)])
                }
            }
        }
    }

    /// What the phone captured, said once in the "Sending" step: "4.2 s of
    /// audio, loudest −18 dB". A command that comes back as only "execute"
    /// can then be placed — a second of audio is the phone, five is the Mac.
    private var captureNote: String {
        guard let c = recorder.lastCapture else { return "" }
        var note = String(format: "\n%.1f s of audio, loudest %.0f dB", c.seconds, c.peakDb)
        if c.peakDb < -45 { note += " — very quiet; check the mic" }
        if c.restarts > 0 { note += " · audio route changed \(c.restarts)× mid-recording" }
        return note
    }

    private var buttonColor: Color {
        switch status {
        case .idle:      return settings.accentColor
        case .recording: return .red
        case .review:    return .blue
        case .thinking:  return .orange
        case .speaking:  return .green
        }
    }

    private var iconColor: Color {
        status == .idle ? Color.onColor(hex: settings.accentColorHex) : .white
    }

    private var iconName: String {
        switch status {
        case .idle:      return "mic.fill"
        case .recording: return "stop.fill"
        case .review:    return "paperplane.fill"
        case .thinking:  return "mic.fill"
        case .speaking:  return "speaker.wave.2.fill"
        }
    }

    private func handleTap() {
        // Settings ▸ Assistant switched off (here or on the Mac): check again
        // first — it may have been switched back on elsewhere — and only then
        // say so. The Mac refuses commands too; this just saves a recording.
        if status == .idle && !api.assistantEnabled {
            Task {
                _ = try? await api.health()
                if api.assistantEnabled { handleTap() } else { offNote = true }
            }
            return
        }
        switch status {
        case .idle:
            let requestPermission: (@escaping (Bool) -> Void) -> Void
            if #available(iOS 17, *) {
                requestPermission = { AVAudioApplication.requestRecordPermission(completionHandler: $0) }
            } else {
                requestPermission = { AVAudioSession.sharedInstance().requestRecordPermission($0) }
            }
            requestPermission { granted in
                guard granted else { return }
                Task { @MainActor in
                    let eggs = EggStore.shared.settings.enabled
                    // The phone transcribes its own recordings (2026-10-10), so
                    // speech recognition is always asked for; refused, the
                    // recording goes to the Mac as audio instead.
                    _ = eggs
                    _ = await VoiceRecorder.requestSpeechPermission()   // no-op once answered
                    recorder.stopWordsEnabled = settings.stopWordsEnabled
                    recorder.silenceStopSeconds = settings.silenceStopEnabled ? settings.silenceStopSeconds : 0
                    recorder.onAutoStop = { [self] in finishRecording() }
                    // Stop talking before listening. The synthesizer holds the
                    // audio session in .playback, so a reply still being read
                    // out talks over the recording and the session is in the
                    // wrong category for the microphone. player.stop() was only
                    // wired to the cancel path.
                    player.stop()
                    status = .recording
                    recorder.start()
                }
            }
        case .recording:
            finishRecording()
        case .review:
            sendPending()
        case .thinking:
            abandon(.redo)              // tap the mic again: say it again
        default:
            player.stop()               // speaking: a tap stops it
            status = .idle
        }
    }

    enum Abandon { case cancel, redo, addMore }

    /// Stop waiting for the command in flight and do what was asked instead.
    /// The Mac already has the audio and finishes it; `undoAbandoned` reads
    /// its reply and removes what it added. "Add more" resumes the recorder,
    /// which still holds the audio that was sent, so the next send is the
    /// whole thing — the first words and the new ones.
    private func abandon(_ then: Abandon) {
        inFlight = nil
        EggWaits.shared.end(eggWait); eggWait = nil
        player.stop()
        showThinking = false
        if settings.showThinking {
            steps.append(TraceStep(stage: "verify", title: then == .cancel ? "Cancelled" : "Stopped — recording again",
                                   detail: "Anything this command adds will be removed when your Mac answers.",
                                   ms: 0, atMs: steps.last?.atMs ?? 0, ok: true))
        }
        finished = true
        finishedAt = Date()
        switch then {
        case .cancel:
            recorder.cancel()           // drop the kept audio: the next recording starts fresh
            status = .idle
        case .redo:
            status = .recording
            recorder.start()
        case .addMore:
            status = .recording
            recorder.start(resume: true)
        }
    }

    /// The reply to a command the person cancelled, redid or added to: remove
    /// what it CREATED. A change or a delete it already made is not guessed
    /// back — it is said, so nothing is silently half-undone.
    @MainActor
    private func undoAbandoned(_ r: VoiceResponse) async {
        var removed = 0
        var changed: [String] = []
        for row in r.committed ?? [] {
            if (row.action ?? "").hasPrefix("create") {
                do {
                    if row.kind == "event" { try await api.deleteEvent(id: row.id) }
                    else { try await api.deleteTodo(id: row.id) }
                    removed += 1
                } catch {}
            } else {
                changed.append((row.action ?? "change").replacingOccurrences(of: "_", with: " "))
            }
        }
        api.requestRefresh()
        onRefresh?("both")
        guard removed > 0 || !changed.isEmpty else { return }
        let body = changed.isEmpty
            ? "\(removed == 1 ? "What it added was" : "The \(removed) things it added were") removed."
            : "It had already done this before you stopped it: \(r.message)"
        showHint(ReplyHint(code: "cancelled", headline: changed.isEmpty ? "Cancelled" : "Cancelled — one thing was already done",
                           body: body))
    }

    /// Ends the recording (tap, stop word, or silence). With "Ask before sending" on,
    /// a Redo / Add more / Send bar appears for a few seconds; otherwise it sends at once.
    private func finishRecording() {
        guard status == .recording, !finishing else { return }
        guard let audioData = recorder.stop(), !audioData.isEmpty else {
            status = .idle
            return
        }
        finishing = true
        Task { @MainActor in
            // The phone's own transcript, its last words settled (≤1.2 s).
            let phone = await recorder.heardText(timeout: settings.transcribeOnPhone ? 1.2 : 0)
            finishing = false
            guard status == .recording else { return }      // discarded while it settled
            finishRecording(audioData, heard: settings.transcribeOnPhone ? phone : "", phone: phone)
        }
    }

    private func finishRecording(_ audioData: Data, heard: String, phone: String) {
        // Easter egg: nothing but magic words ("dragon!") plays and sends
        // nothing — there is no command in it to run.
        if EggStore.shared.heard(phone, bare: true) {
            status = .idle
            return
        }
        // A spoken stop word ("execute", "submit", …) is the decision itself —
        // send at once rather than making the user wait out the countdown they
        // just talked their way past. Silence or a mic tap still offers the bar.
        guard settings.reviewBeforeSend, recorder.stopReason != .stopWord else {
            send(audioData, heard: heard); return
        }
        pendingAudio = audioData
        pendingHeard = heard
        status = .review
        sendCountdown = 3
        countdownTask?.cancel()
        countdownTask = Task { @MainActor in
            while sendCountdown > 0 {
                try? await Task.sleep(nanoseconds: 1_000_000_000)
                if Task.isCancelled { return }
                sendCountdown -= 1
            }
            sendPending()
        }
    }

    /// Discard whatever has been recorded — mid-sentence or during the review
    /// countdown — and go back to idle. Nothing is uploaded, so nothing is
    /// transcribed, executed or remembered.
    private func discard() {
        countdownTask?.cancel()
        countdownTask = nil
        sendCountdown = 0
        pendingAudio = nil
        recorder.cancel()
        player.stop()
        status = .idle
    }

    private func redo() {
        countdownTask?.cancel(); pendingAudio = nil
        player.stop()
        status = .recording
        recorder.start()
    }

    private func addMore() {
        countdownTask?.cancel(); pendingAudio = nil
        player.stop()
        status = .recording
        recorder.start(resume: true)      // keeps what was already said
    }

    private func sendPending() {
        countdownTask?.cancel()
        guard status == .review, let audio = pendingAudio else { return }
        pendingAudio = nil
        send(audio, heard: pendingHeard)
    }

    /// The full-screen "taking a while" loader is for a wait with nothing
    /// else on screen. While the thinking panel is open it IS the progress —
    /// its own "Working…" spinner plays — and the loader sat over it, hiding
    /// the reasoning it was waiting on (Gil, 2026-10-06: "remove wheel of
    /// death showing on the whole screen when panel showing reasoning").
    /// Closing the panel mid-command brings the loader back (see .onChange).
    private func beginScreenWaitUnlessPanel() {
        guard !showThinking, eggWait == nil else { return }
        eggWait = EggWaits.shared.begin()
    }

    /// Send one recording. `heard` is the phone's own transcript: when there is
    /// one it is sent INSTEAD of the audio and the Mac does not transcribe
    /// again (Gil, 2026-10-10: "whatever device it comes from, just use that
    /// one … we don't want to do double work"). Empty — recognition refused,
    /// unavailable, or switched off in Settings — and the audio goes, for
    /// Whisper on the Mac.
    private func send(_ audioData: Data, heard: String = "") {
        // No Mac at all: the phone reads and does it (DEVQA Q85).
        if settings.phoneOnly { runLocal(heard.isEmpty ? recorder.liveText : heard); return }
        do {   // one block so the placeholder row + upload read top-to-bottom
            status = .thinking
            steps = []
            finished = false
            lastResponse = nil
            // Easter egg: a magic word inside a command plays while the
            // command is being made. The phone's own hearing if it has one;
            // otherwise the Mac's transcript, the moment it arrives below.
            eggPlayed = EggStore.shared.heard(heard.isEmpty ? recorder.liveText : heard, bare: false)
            EggWaits.shared.end(eggWait); eggWait = nil
            // The placeholder the Mac's first step replaces.
            let placeholder = PlaceholderStep()
            if settings.showThinking {
                steps = [heard.isEmpty
                    ? TraceStep(stage: "stt", title: "Sending",
                                detail: "Uploading audio to your Mac…" + captureNote,
                                ms: 0, atMs: 0, ok: true)
                    : TraceStep(stage: "stt", title: "Heard on your phone",
                                detail: heard + captureNote, ms: 0, atMs: 0, ok: true)]
                showThinking = true
            }
            beginScreenWaitUnlessPanel()
            let sentAt = Date()
            let me = UUID()
            inFlight = me
            // Hold a background assertion for the whole command — leaving the app
            // mid-command used to get the process suspended, which killed the
            // stream and froze the timeline half-written.
            let assertion = BackgroundAssertion()
            assertion.begin("voice-command-ui")
            Task {
                defer { assertion.end() }
                do {
                    // Always stream: the Mac reports each stage as it happens, so the
                    // calendar can refresh the moment an action executes (first version)
                    // and again when the self-check has finished (fixed version).
                    let onStep: (TraceStep) -> Void = { step in
                        guard inFlight == me else { return }        // cancelled: not shown
                        if settings.showThinking {
                            if placeholder.showing { steps = []; placeholder.showing = false }
                            steps.append(step)
                        }
                        // The Mac's hearing, whenever the phone's played nothing —
                        // not only when the phone heard nothing at all: its
                        // recogniser can miss a name ("Val") the Mac's vocabulary
                        // knows. The CORRECTED words only: the step's detail
                        // ("Fixed dragon→Dragan") also holds the misheard one.
                        if !eggPlayed, step.stage == "vocab", let words = step.transcript, !words.isEmpty {
                            eggPlayed = EggStore.shared.heardLate(words)
                        }
                        if step.stage == "execute" && step.ok {
                            api.burstRefresh()
                            api.requestRefresh()
                            onRefresh?("both")
                        }
                    }
                    let response = heard.isEmpty
                        ? try await api.sendAudioStreaming(audioData, supportsEdit: true,
                                                           supportsConfirm: true, onStep: onStep)
                        : try await api.sendHeardStreaming(heard, supportsEdit: true,
                                                           supportsConfirm: true, onStep: onStep)
                    guard inFlight == me else { await undoAbandoned(response); return }
                    inFlight = nil
                    await handleResponse(response)
                } catch {
                    guard inFlight == me else { return }
                    inFlight = nil
                    await recoverLostStream(error, sentAt: sentAt, audio: audioData, heard: heard)
                }
            }
        }
    }

    /// A typed command: the same road as a spoken one, minus the microphone.
    /// The Mac reads it as text ("Typed" in its trace); away from the Mac it
    /// queues like a recording would, already in its final words.
    private func sendTyped(_ text: String) {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty, status == .idle else { return }
        // Nothing but magic words ("dragon!"): played here, not sent.
        if EggStore.shared.heard(t, bare: true) { return }
        player.stop()
        if settings.phoneOnly { runLocal(t); return }
        status = .thinking
        steps = []
        finished = false
        lastResponse = nil
        eggPlayed = EggStore.shared.heard(t, bare: false)
        EggWaits.shared.end(eggWait); eggWait = nil
        if settings.showThinking {
            steps = [TraceStep(stage: "stt", title: "Typed", detail: t, ms: 0, atMs: 0, ok: true)]
            showThinking = true
        }
        beginScreenWaitUnlessPanel()
        let me = UUID()
        inFlight = me
        Task {
            do {
                let response = try await api.sendText(t, supportsEdit: false, supportsConfirm: true)
                guard inFlight == me else { await undoAbandoned(response); return }
                inFlight = nil
                await handleResponse(response)
            } catch APIError.offline, APIError.badURL {
                guard inFlight == me else { return }
                inFlight = nil
                EggWaits.shared.end(eggWait); eggWait = nil
                let cmd = LocalStore.shared.enqueueTyped(t)
                var booked: [String] = []
                if OfflineReader.isAvailable {
                    LocalStore.shared.holdVoiceForEdit(cmd.id, true)
                    if let reading = await OfflineReader.read(t) {
                        booked = LocalStore.shared.bookProvisional(cmd.id, reading: reading)
                    }
                    LocalStore.shared.holdVoiceForEdit(cmd.id, false)
                }
                if !booked.isEmpty { onRefresh?("both") }
                if settings.showThinking {
                    steps.append(TraceStep(stage: "verify",
                                           title: booked.isEmpty ? "Saved for later" : "Read on this phone",
                                           detail: booked.isEmpty
                                               ? "Your Mac isn't reachable. This command is queued and runs as soon as it's back."
                                               : "Added on this phone: " + booked.joined(separator: "; ")
                                                 + ". Your Mac will check it when it's back.",
                                           ms: 0, atMs: 0, ok: true))
                }
                finished = true
                finishedAt = Date()
                status = .idle
            } catch {
                guard inFlight == me else { return }
                inFlight = nil
                EggWaits.shared.end(eggWait); eggWait = nil
                if settings.showThinking {
                    steps.append(TraceStep(stage: "error", title: "Couldn't send that",
                                           detail: error.localizedDescription, ms: 0, atMs: 0, ok: false))
                }
                finished = true
                status = .idle
            }
        }
    }

    /// A command on a phone with no Mac: `LocalCommand` reads and does it, and
    /// its reply goes down the same road as the Mac's — spoken, traced, and
    /// the calendar refreshed (DEVQA Q85).
    private func runLocal(_ said: String) {
        status = .thinking
        steps = []
        finished = false
        lastResponse = nil
        eggPlayed = EggStore.shared.heard(said, bare: false)
        if settings.showThinking { showThinking = true }
        Task { @MainActor in
            let out = await LocalCommand.run(said, api: api)
            steps = out.steps
            await handleResponse(VoiceResponse.local(message: out.reply, transcript: said,
                                                     refresh: out.changed ? "both" : ""))
        }
    }

    /// The stream died before the result arrived — almost always because iOS
    /// suspended the app after it went to the background. The Mac does the work
    /// server-side, so the command itself usually completed: say so, refresh the
    /// calendar, and wait for the record to show up in the command log rather
    /// than reporting a failure that didn't happen.
    @MainActor
    private func recoverLostStream(_ error: Error, sentAt: Date, audio: Data, heard: String = "") async {
        EggWaits.shared.end(eggWait); eggWait = nil
        // Never reached the Mac at all? Then nothing ran: keep the recording and
        // replay it when the Mac is back, rather than polling for a result that
        // cannot exist and then reporting a failure.
        if (try? await api.health()) == nil {
            // Keep what the on-device recogniser heard. `liveText` is already
            // published for the thinking sheet's "hearing…" row, so this costs
            // nothing — and without it a queued command is an anonymous row the
            // user cannot check or correct until after it has run.
            // When the phone transcribed it, its words are what replays — as
            // text, so the Mac does not transcribe it a second time.
            let draft = heard.isEmpty ? recorder.liveText : heard
            let cmd = LocalStore.shared.enqueueVoice(audio, draft: draft, heardOnPhone: !heard.isEmpty)
            // Read it HERE with Apple's on-device model and book what it can
            // at once — provisionally: the Mac re-reads the command when it
            // is back and its reading replaces this one (assistant/offline).
            var booked: [String] = []
            if OfflineReader.isAvailable,
               !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                // Held while reading, so a reconnect mid-read cannot send the
                // command without the reading and leave these rows orphaned.
                LocalStore.shared.holdVoiceForEdit(cmd.id, true)
                if let reading = await OfflineReader.read(draft) {
                    booked = LocalStore.shared.bookProvisional(cmd.id, reading: reading)
                }
                LocalStore.shared.holdVoiceForEdit(cmd.id, false)
            }
            if !booked.isEmpty {
                onRefresh?("both")
                let line = settings.phoneOnly
                    ? "Added: " + booked.joined(separator: "; ") + "."
                    : "Added on this phone: " + booked.joined(separator: "; ")
                      + ". Your Mac will check it when it's back."
                if settings.showThinking {
                    steps.append(TraceStep(stage: "verify", title: "Read on this phone",
                                           detail: line, ms: 0, atMs: steps.last?.atMs ?? 0, ok: true))
                }
                if settings.speakReplies { player.speak(line, voiceIdentifier: settings.ttsVoice) }
            } else if settings.showThinking {
                steps.append(TraceStep(stage: "verify", title: "Saved for later",
                                       detail: settings.phoneOnly
                                           ? "Reading commands on this phone needs Apple Intelligence (iOS 26). "
                                             + "It's kept, and runs if you set up a Mac later."
                                           : "Your Mac isn't reachable. This command is queued and will "
                                             + "run — and tell you what it did — as soon as it's back.",
                                       ms: 0, atMs: steps.last?.atMs ?? 0, ok: true))
            }
            finished = true
            finishedAt = Date()
            status = .idle
            return
        }

        if settings.showThinking {
            steps.append(TraceStep(stage: "verify", title: "Lost the live connection",
                                   detail: "The Mac keeps running the command — checking what it did…",
                                   ms: 0, atMs: steps.last?.atMs ?? 0, ok: true))
        }
        api.burstRefresh()
        api.requestRefresh()
        onRefresh?("both")

        // While the app is suspended this loop is suspended too, so in practice
        // it resolves the moment the user comes back.
        for attempt in 0..<12 {
            if attempt > 0 { try? await Task.sleep(nanoseconds: 2_000_000_000) }
            if let ran = await api.recentCommands(limit: 3)
                .first(where: { $0.ts >= sentAt.timeIntervalSince1970 - 1 }) {
                if settings.showThinking {
                    steps.append(TraceStep(stage: "done", title: "Finished on the Mac",
                                           detail: ran.result.isEmpty ? ran.transcript : ran.result,
                                           ms: 0, atMs: steps.last?.atMs ?? 0, ok: true))
                }
                finished = true
                finishedAt = Date()
                api.burstRefresh()
                api.requestRefresh()
                onRefresh?("both")
                status = .idle
                return
            }
        }

        if settings.showThinking {
            steps.append(TraceStep(stage: "error", title: "Couldn't reach the Mac",
                                   detail: error.localizedDescription, ms: 0,
                                   atMs: steps.last?.atMs ?? 0, ok: false))
        }
        finished = true
        finishedAt = Date()
        status = .idle
    }

    private func handleResponse(_ response: VoiceResponse) async {
        // Last chance for a magic word: the final, vocabulary-corrected words
        // — even when the command made nothing at all.
        if !eggPlayed, let heard = response.transcript, !heard.isEmpty {
            eggPlayed = EggStore.shared.heardLate(heard)
        }
        EggWaits.shared.end(eggWait); eggWait = nil
        lastResponse = response
        // Easter egg: play for what the command MADE (a trip → a plane), when
        // that is switched on. After the reply, off the main path.
        if let rows = response.committed, !rows.isEmpty {
            let made = rows.filter { ($0.action ?? "").hasPrefix("create") }.map { (kind: $0.kind, id: $0.id) }
            Task { await EggStore.shared.made(made, api: api) }
        }
        if let t = response.trace, !t.isEmpty, steps.isEmpty || !settings.showThinking {
            steps = t
        }
        finished = true
        finishedAt = Date()

        // The host doubts a few words and executed nothing — show the
        // transcription editor and resubmit the corrected text. The edit is
        // learned on the host, so the same mishearing won't ask again. Nothing
        // ran, so skip the refresh/verify/speak below.
        if response.parse == "needs_edit" {
            showThinking = false
            status = .idle
            editRequest = EditRequest(text: response.transcript ?? "",
                                      doubtful: response.needsEdit ?? response.uncertainWords ?? [])
            return
        }

        // A question about creating something: the parse is offered, not run.
        // Nothing to refresh, verify or speak until the alert is answered.
        if response.parse == "confirm_create", let token = response.confirmToken {
            showThinking = false
            status = .idle
            confirmRequest = ConfirmRequest(token: token, prompt: response.message,
                                            items: response.proposal ?? [])
            return
        }

        api.burstRefresh()   // poll every second for a while so both devices settle together
        onRefresh?(response.refresh)
        onResponse?(response)

        // One coaching line, once per code: "set a meeting" committed as
        // 'meeting', so next time say what it is about. The words come from
        // the host; the phone only remembers which codes it has shown.
        if let h = response.hint, !settings.shownHints.contains(h.code) {
            settings.shownHints.append(h.code)
            showHint(h)
        }

        // Background self-check: the Mac re-reasons over what it did and may
        // patch/undo it. Poll for the outcome and tell the user if it changed.
        if let token = response.verifyToken {
            api.pollVerify(token: token) { result in
                await MainActor.run {
                    let speech = result.speech ?? ""
                    let undone = result.revert ?? []
                    steps.append(TraceStep(stage: "verify", title: "Self-check",
                                           detail: speech.isEmpty ? "Corrected the \(result.severity ?? "") issue" : speech,
                                           ms: 0, atMs: (steps.last?.atMs ?? 0), ok: undone.isEmpty))
                    if !undone.isEmpty { pendingRevert = undone }   // offer one-tap revert
                    if let r = result.refresh, !r.isEmpty { onRefresh?(r) }
                    if !speech.isEmpty && settings.speakReplies { player.speak(speech, voiceIdentifier: settings.ttsVoice) }
                }
            }
        }

        if !response.message.isEmpty && settings.speakReplies {
            status = .speaking
            player.speak(response.message, voiceIdentifier: settings.ttsVoice)
            // Wait for speech to finish
            while player.isSpeaking {
                try? await Task.sleep(nanoseconds: 200_000_000)
            }
        }
        status = .idle
    }

    /// The answer to a confirm_create proposal. The host does the creating —
    /// through exactly the code a POST /events / POST /todos would run — so the
    /// phone never holds a second create path, and answering twice is safe.
    private func answerConfirm(_ req: ConfirmRequest, accept: Bool) {
        confirmRequest = nil
        Task {
            do {
                let r = try await api.confirmCreate(token: req.token, accept: accept)
                await MainActor.run {
                    if settings.showThinking {
                        steps.append(TraceStep(stage: "execute",
                                               title: accept ? "You said add it" : "You said no",
                                               detail: r.message, ms: 0,
                                               atMs: steps.last?.atMs ?? 0, ok: true))
                    }
                    if !r.refresh.isEmpty {
                        api.burstRefresh()
                        onRefresh?(r.refresh)
                    }
                    if !r.message.isEmpty && settings.speakReplies {
                        player.speak(r.message, voiceIdentifier: settings.ttsVoice)
                    }
                }
            } catch {
                await MainActor.run {
                    if settings.showThinking {
                        steps.append(TraceStep(stage: "error", title: "Couldn't answer that",
                                               detail: error.localizedDescription, ms: 0,
                                               atMs: steps.last?.atMs ?? 0, ok: false))
                    }
                }
            }
        }
    }

    /// Second half of the needs_edit round-trip: send the corrected transcript
    /// back as text (with `editedFrom` so the host bypasses the gate and learns
    /// the fix), then run the normal response flow.
    private func resubmitEdited(_ corrected: String, editedFrom: String) {
        // No Mac: the corrected words are read again here (DEVQA Q85).
        if settings.phoneOnly { status = .idle; runLocal(corrected); return }
        status = .thinking
        finished = false
        if settings.showThinking {
            steps.append(TraceStep(stage: "vocab", title: "Using your edit",
                                   detail: corrected, ms: 0,
                                   atMs: steps.last?.atMs ?? 0, ok: true))
            showThinking = true
        }
        Task {
            do {
                let r = try await api.sendText(corrected, editedFrom: editedFrom,
                                       supportsEdit: true, supportsConfirm: true)
                await handleResponse(r)
            } catch {
                await MainActor.run {
                    if settings.showThinking {
                        steps.append(TraceStep(stage: "error", title: "Couldn't send the edit",
                                               detail: error.localizedDescription, ms: 0,
                                               atMs: steps.last?.atMs ?? 0, ok: false))
                    }
                    finished = true
                    status = .idle
                }
            }
        }
    }
}

/// A confirm_create proposal awaiting an answer — drives the "add this?" alert.
struct ConfirmRequest: Identifiable {
    let id = UUID()
    let token: String
    let prompt: String
    let items: [ProposedCreate]
}

/// What the host doubted — drives the transcription editor sheet.
struct EditRequest: Identifiable {
    let id = UUID()
    let text: String
    let doubtful: [UncertainWord]
}

/// The "edit the transcription" sheet: shown when the host returns needs_edit.
/// The user fixes any misheard words (or sends as-is) and the corrected text is
/// resubmitted. Sending unchanged tells the host its guess was right — which is
/// how a doubted word earns trust and stops being asked about.
private struct EditTranscriptionSheet: View {
    let text: String
    let doubtful: [UncertainWord]
    let onSubmit: (String) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var edited: String
    @FocusState private var focused: Bool

    init(text: String, doubtful: [UncertainWord], onSubmit: @escaping (String) -> Void) {
        self.text = text
        self.doubtful = doubtful
        self.onSubmit = onSubmit
        _edited = State(initialValue: text)
    }

    var body: some View {
        StackNavigation {
            VStack(alignment: .leading, spacing: 14) {
                Text("A couple of words looked uncertain. Fix anything that's wrong, or send it as-is.")
                    .font(.subheadline).foregroundColor(.secondary)
                if !doubtful.isEmpty {
                    Text("Unsure: " + doubtful.map { w in
                        w.candidate.map { "\(w.heard) → \($0)?" } ?? w.heard
                    }.joined(separator: ", "))
                        .font(.caption).foregroundColor(.orange)
                }
                TextEditor(text: $edited)
                    .frame(minHeight: 90)
                    .padding(6)
                    .background(Color(.secondarySystemBackground))
                    .cornerRadius(10)
                    .focused($focused)
                    .autocorrectionDisabled()
                Spacer()
            }
            .padding(20)
            .navigationTitle("Check the transcription")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Send") {
                        onSubmit(edited.trimmingCharacters(in: .whitespacesAndNewlines))
                        dismiss()
                    }
                    .disabled(edited.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
            .onAppear { focused = true }
        }
    }
}

/// Tiny "heard X → should be Y" sheet used from the thinking view.
private struct QuickFixSheet: View {
    let wrong: String
    @State private var right = ""
    let onSave: (String) -> Void
    @Environment(\.dismiss) private var dismiss
    @FocusState private var focused: Bool

    init(wrong: String, onSave: @escaping (String) -> Void) {
        self.wrong = wrong
        self.onSave = onSave
        _right = State(initialValue: wrong)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Fix “\(wrong)”").font(.headline)
            TextField("Correct word", text: $right)
                .textFieldStyle(.roundedBorder)
                .autocorrectionDisabled()
                .focused($focused)
                .onSubmit(save)
            Text("Added to your vocabulary — future commands will use this spelling.")
                .font(.caption).foregroundColor(.secondary)
            Button(action: save) { Text("Teach it").frame(maxWidth: .infinity) }
                .buttonStyle(.borderedProminent)
                .disabled(right.trimmingCharacters(in: .whitespaces).isEmpty || right == wrong)
        }
        .padding(20)
        .onAppear { focused = true }
    }

    private func save() {
        let r = right.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !r.isEmpty, r != wrong else { return }
        onSave(r); dismiss()
    }
}


/// The box a command is typed into: the keyboard comes up at once, Return or
/// Send sends it, and it is short enough to keep the calendar in view.
struct TypeCommandSheet: View {
    @Binding var text: String
    var onSend: (String) -> Void
    @Environment(\.dismiss) private var dismiss
    @FocusState private var focused: Bool

    private var canSend: Bool { !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Type a command").font(.headline)
                Spacer()
                Button("Cancel") { dismiss() }
            }
            HStack(alignment: .bottom, spacing: 10) {
                TextField("e.g. lunch with Dana tomorrow at 1", text: $text, axis: .vertical)
                    .lineLimit(1...4)
                    .focused($focused)
                    .submitLabel(.send)
                    .onSubmit { if canSend { onSend(text) } }
                    .padding(10)
                    .background(RoundedRectangle(cornerRadius: 12).fill(Color(.secondarySystemBackground)))
                    .accessibilityIdentifier("type-command-field")
                Button { onSend(text) } label: {
                    Image(systemName: "arrow.up.circle.fill").font(.system(size: 32))
                }
                .disabled(!canSend)
                .accessibilityIdentifier("type-command-send")
                .accessibilityLabel("Send")
            }
            Text("Same as saying it: it runs on your Mac, and the thinking panel shows what it did.")
                .font(.caption).foregroundColor(.secondary)
        }
        .padding()
        .onAppear { DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { focused = true } }
        .modifier(ShortSheet())
    }
}

/// A short sheet where the OS allows it (iOS 16+), a full one otherwise.
private struct ShortSheet: ViewModifier {
    func body(content: Content) -> some View {
        if #available(iOS 16.0, *) {
            content.presentationDetents([.height(200)]).presentationDragIndicator(.visible)
        } else {
            content
        }
    }
}


// MARK: - Live mic level (Gil, 2026-10-09: "pops out and changes dynamically
// according to how loud the input is — just see that it's captured")

/// Three soft rings behind the mic button, each swelling with the voice by a
/// different amount, so a word reads as a ripple outwards.
private struct MicLevelRings: View {
    let level: Float

    var body: some View {
        let l = CGFloat(level)
        ZStack {
            ForEach(0..<3, id: \.self) { i in
                let reach: CGFloat = [0.35, 0.65, 0.95][i]
                Circle()
                    .fill(RadialGradient(colors: [Color.red.opacity(0.35 - Double(i) * 0.09), .clear],
                                         center: .center, startRadius: 24, endRadius: 50))
                    .overlay(Circle().stroke(Color.red.opacity(0.5 - Double(i) * 0.14),
                                             lineWidth: 2))
                    .frame(width: 64, height: 64)
                    .scaleEffect(1 + l * reach)
                    .opacity(0.35 + Double(l) * 0.65)
            }
        }
        .animation(.spring(response: 0.16, dampingFraction: 0.6), value: level)
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}

/// The recording chip: a scrolling bar waveform of the last second or so and
/// a clock — or, while nothing louder than room noise has arrived, "No sound".
private struct ListeningMeter: View {
    let levels: [Float]
    let startedAt: Date?
    let soundSeen: Bool

    var body: some View {
        TimelineView(.periodic(from: .now, by: 0.5)) { tl in
            let elapsed = startedAt.map { tl.date.timeIntervalSince($0) } ?? 0
            let silent = !soundSeen && elapsed > 2
            HStack(spacing: 6) {
                HStack(alignment: .center, spacing: 2) {
                    ForEach(Array(levels.enumerated()), id: \.offset) { _, v in
                        Capsule()
                            .fill(silent ? Color.orange : Color.red.opacity(0.55 + Double(v) * 0.45))
                            .frame(width: 2.5, height: 3 + CGFloat(v) * 17)
                    }
                }
                .frame(height: 20)
                .animation(.linear(duration: 0.05), value: levels)
                Text(silent ? "No sound — check the mic" : Self.clock(elapsed))
                    .monospacedDigit()
                    .foregroundColor(silent ? .orange : .secondary)
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(silent ? "Recording, but no sound is reaching the microphone"
                                       : "Recording, \(Int(elapsed)) seconds")
            .accessibilityIdentifier("listening-chip")
        }
    }

    private static func clock(_ t: TimeInterval) -> String {
        let s = Int(t)
        return String(format: "%d:%02d", s / 60, s % 60)
    }
}

/// The default style: a card above the mic with a full-width waveform, the
/// clock, what the phone has heard so far, and a trash button.
private struct WaveformCard: View {
    let levels: [Float]
    let startedAt: Date?
    let soundSeen: Bool
    let heard: String
    let onDiscard: () -> Void

    var body: some View {
        TimelineView(.periodic(from: .now, by: 0.5)) { tl in
            let elapsed = startedAt.map { tl.date.timeIntervalSince($0) } ?? 0
            let silent = !soundSeen && elapsed > 2
            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 8) {
                    Circle().fill(silent ? Color.orange : Color.red).frame(width: 8, height: 8)
                    Text(silent ? "No sound — check the mic" : "Listening")
                        .font(.footnote.weight(.semibold))
                        .foregroundColor(silent ? .orange : .red)
                    Spacer()
                    Text(String(format: "%d:%02d", Int(elapsed) / 60, Int(elapsed) % 60))
                        .font(.footnote).monospacedDigit().foregroundColor(.secondary)
                    Button(role: .destructive, action: onDiscard) {
                        Image(systemName: "trash").font(.footnote)
                    }
                    .buttonStyle(.bordered).controlSize(.small).tint(.red)
                    .accessibilityLabel("Discard recording")
                }
                HStack(alignment: .center, spacing: 3) {
                    ForEach(Array(levels.enumerated()), id: \.offset) { i, v in
                        Capsule()
                            .fill(silent ? Color.orange : Self.colour(i, of: levels.count))
                            .frame(width: 6, height: 4 + CGFloat(v) * 44)
                    }
                }
                .frame(height: 48)
                .animation(.linear(duration: 0.05), value: levels)
                if !heard.isEmpty {
                    Text(heard)
                        .font(.subheadline)
                        .lineLimit(2)
                        .truncationMode(.head)
                        .frame(width: 280, alignment: .leading)
                }
            }
            .padding(14)
            .frame(width: 308)
            .background(.regularMaterial)
            .clipShape(RoundedRectangle(cornerRadius: 20))
            .shadow(radius: 3)
            .accessibilityElement(children: .contain)
            .accessibilityLabel(silent ? "Recording, but no sound is reaching the microphone"
                                       : "Recording, \(Int(elapsed)) seconds")
            .accessibilityIdentifier("listening-card")
        }
    }

    /// Red on the left warming to amber on the right, as on the design canvas.
    static func colour(_ i: Int, of n: Int) -> Color {
        let t = n > 1 ? Double(i) / Double(n - 1) : 0
        return Color(red: 1, green: (69 + 90 * t) / 255, blue: (58 - 48 * t) / 255)
    }
}

/// Rays all the way round the mic, each as long as the voice was a moment
/// ago — neighbours read different moments, so it ripples rather than pulses.
private struct MicSunburst: View {
    let levels: [Float]
    private let rays = 32

    var body: some View {
        ZStack {
            ForEach(0..<rays, id: \.self) { i in
                Capsule()
                    .fill(colour(i))
                    .frame(width: 3.5, height: length(i))
                    .offset(y: -(38 + length(i) / 2))
                    .rotationEffect(angle(i))
            }
        }
        .frame(width: 64, height: 64)
        .animation(.easeOut(duration: 0.08), value: levels)
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }

    // Typed helpers, not inline maths: the inline version is more than the
    // Swift type checker will solve in time ("unable to type-check").
    private func length(_ i: Int) -> CGFloat {
        guard !levels.isEmpty else { return 6 }
        let v = CGFloat(levels[(i * 7) % levels.count])
        return 6 + v * 28
    }

    private func colour(_ i: Int) -> Color {
        let warm: Double = abs(sin(Double(i) * Double.pi / Double(rays)))
        let green: Double = (69 + 100 * warm) / 255
        let blue: Double = (58 - 40 * warm) / 255
        return Color(red: 1, green: green, blue: blue)
    }

    private func angle(_ i: Int) -> Angle {
        .degrees(Double(i) * 360 / Double(rays))
    }
}

/// A ring of coloured dots that hop outward and grow with the voice.
private struct MicDots: View {
    let levels: [Float]
    private let count = 16
    private let palette: [Color] = [
        Color(red: 1, green: 0.27, blue: 0.23), Color(red: 1, green: 0.62, blue: 0.04),
        Color(red: 1, green: 0.84, blue: 0.04), Color(red: 1, green: 0.41, blue: 0.38),
        Color(red: 0.75, green: 0.35, blue: 0.95), Color(red: 1, green: 0.22, blue: 0.37),
    ]

    var body: some View {
        ZStack {
            ForEach(0..<count, id: \.self) { i in
                Circle()
                    .fill(palette[i % palette.count])
                    .frame(width: 10, height: 10)
                    .scaleEffect(scale(i))
                    .offset(y: lift(i))
                    .rotationEffect(angle(i))
            }
        }
        .frame(width: 64, height: 64)
        .animation(.spring(response: 0.18, dampingFraction: 0.55), value: levels)
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }

    // Typed helpers, not inline maths — see MicSunburst.
    private func level(_ i: Int) -> CGFloat {
        levels.isEmpty ? 0 : CGFloat(levels[(i * 5 + 3) % levels.count])
    }

    private func scale(_ i: Int) -> CGFloat {
        let v: CGFloat = level(i)
        return 0.7 + v * 0.8
    }

    private func lift(_ i: Int) -> CGFloat {
        let v: CGFloat = level(i)
        return -(40 + v * 24)
    }

    private func angle(_ i: Int) -> Angle {
        .degrees(Double(i) * 360 / Double(count))
    }
}


// MARK: - The style picker in Settings (Gil, 2026-10-10: "there should be
// demo and toggle to which one is relevant, separate per device")

/// A speaking voice, made up: phrases with pauses, syllables inside them — so
/// a demo moves the way the real meter does while you talk.
enum DemoVoice {
    static func level(at t: TimeInterval) -> Float {
        let phrase = max(0, sin(t * 1.25))                // talk, pause, talk
        let syllables = 0.45 + 0.55 * abs(sin(t * 9.0) * sin(t * 3.7 + 1))
        return Float(min(1, phrase.squareRoot() * syllables * 1.05))
    }

    /// The last `count` levels, oldest first, ending at `t`.
    static func history(at t: TimeInterval, count: Int = VoiceRecorder.historyCount) -> [Float] {
        (0..<count).map { level(at: t - Double(count - 1 - $0) * 0.06) }
    }
}

/// Settings ▸ Voice & recording ▸ "While recording": the four styles as live
/// demos, tap one to use it on this phone. Each tile is the real view the mic
/// draws, fed a made-up voice.
struct MicStylePicker: View {
    @EnvironmentObject var settings: AppSettings

    var body: some View {
        LazyVGrid(columns: [GridItem(.flexible(), spacing: 10), GridItem(.flexible(), spacing: 10)],
                  spacing: 10) {
            ForEach(AppSettings.micVisuals) { v in
                tile(v)
            }
        }
        .accessibilityIdentifier("mic-visual-picker")
    }

    private func tile(_ v: AppSettings.MicVisual) -> some View {
        let on = settings.micVisual == v.id
        return Button { settings.micVisual = v.id } label: {
            VStack(spacing: 6) {
                TimelineView(.animation(minimumInterval: 1.0 / 30)) { tl in
                    let t = tl.date.timeIntervalSinceReferenceDate
                    demo(v.id, level: DemoVoice.level(at: t), levels: DemoVoice.history(at: t))
                }
                .frame(height: 112)
                .frame(maxWidth: .infinity)
                .clipped()
                HStack(spacing: 4) {
                    if on { Image(systemName: "checkmark.circle.fill").foregroundColor(settings.accentColor) }
                    Text(v.label).font(.subheadline.weight(on ? .semibold : .regular))
                }
            }
            .padding(.vertical, 8)
            .background(RoundedRectangle(cornerRadius: 14).fill(Color(.tertiarySystemBackground)))
            .overlay(RoundedRectangle(cornerRadius: 14)
                .stroke(on ? settings.accentColor : Color.clear, lineWidth: 2))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(v.label)
        .accessibilityAddTraits(on ? .isSelected : [])
    }

    @ViewBuilder
    private func demo(_ id: String, level: Float, levels: [Float]) -> some View {
        if id == "card" {
            WaveformCard(levels: levels, startedAt: Date().addingTimeInterval(-4), soundSeen: true,
                         heard: "Lunch with Dana at noon", onDiscard: {})
                .fixedSize()
                .scaleEffect(0.46)
                .frame(width: 150, height: 112)
                .allowsHitTesting(false)
        } else {
            ZStack {
                switch id {
                case "rings":    MicLevelRings(level: level)
                case "sunburst": MicSunburst(levels: levels)
                default:         MicDots(levels: levels)
                }
                Circle().fill(Color.red).frame(width: 60, height: 60)
                Image(systemName: "stop.fill").font(.system(size: 20, weight: .semibold)).foregroundColor(.white)
            }
            .scaleEffect(0.62)
            .frame(width: 150, height: 112)
            .allowsHitTesting(false)
        }
    }
}

/// The "Sending" / "Heard on your phone" row shown until the Mac's first step
/// arrives — a reference, so the streaming callback can clear it exactly once.
private final class PlaceholderStep { var showing = true }
