import SwiftUI
import UIKit

// MARK: - Jude — the tab
//
// Jude is a Judaic study assistant: ask about Torah, Talmud, halacha, midrash
// or machshava and get an answer built from ~289,000 Sefaria passages, every
// one of them cited and linked back so the answer can be checked rather than
// believed. It is a separate repository running beside the assistant on the
// Mac — see `assistant/jude/ARCHITECTURE.md`, which is the contract this whole
// folder is built to.
//
// Which means it needs the Mac, and unlike the calendar and the task list
// there is deliberately nothing to cache and nothing to queue: the corpus is
// gigabytes, and a question replayed three hours later is answered to nobody.
// When the Mac is away this says so.

/// One question and everything that came back for it.
///
/// A struct in an array rather than a stream into a text view, because the
/// answer is not the only thing that arrives: sources, trace steps, tool calls
/// and the timing breakdown all land at different moments and all belong to
/// the same turn.
struct JudeTurn: Identifiable {
    let id = UUID()
    let question: String
    var mode: String = "qa"
    var answer: String = ""
    /// True until `done`. While it is true the answer renders as plain text —
    /// see `JudeConversation.flush` for why parsing markdown per repaint is
    /// not something to do 2,000 times.
    var streaming: Bool = true
    var sources: [JudeSource] = []
    var steps: [JudeStep] = []
    var toolCalls: [JudeToolCall] = []
    var timing: JudeTiming?
    /// "Hilchot Shabbat · Seder Moed" — from the meta event, when Jude
    /// detected a halachic topic and ran its dual retrieval for it.
    var topicBadge: String = ""
    /// "📖 Study · 41 sources loaded" — study mode's equivalent.
    var poolBadge: String = ""
    var clarification: JudeClarification?
    var error: String = ""

    var isEmpty: Bool {
        answer.isEmpty && sources.isEmpty && error.isEmpty && clarification == nil
    }
}

/// Jude asking back, because the question could be read more than one way.
struct JudeClarification {
    let question: String
    let options: [JudeClarificationOption]
    /// The question as originally asked — what "continue with mine" re-sends,
    /// with `skip_clarification` set so Jude answers instead of asking again.
    let originalPrompt: String
}

/// Jude noticing the conversation has moved to a different subject.
struct JudePivot {
    let previous: String
    let candidate: String
}

// MARK: - The conversation

/// The state of one Jude conversation and the stream that feeds it.
///
/// This is an ObservableObject rather than `@State` in the view for one
/// reason: token batching. It needs somewhere to accumulate text that is NOT
/// published, and a `@State` buffer would republish on every write.
@MainActor
final class JudeConversation: ObservableObject {
    @Published var turns: [JudeTurn] = []
    @Published var chatId: String?
    @Published var chatTitle: String = ""
    /// The stage name from the stream. **This is the only progress signal for
    /// up to 90 seconds** — Jude makes five model calls per question and
    /// synthesis alone is 30–90 s — so it is drawn prominently, not as a
    /// footnote. A surface that hides it looks hung.
    @Published var stage: String = ""
    @Published var asking = false
    @Published var pivot: JudePivot?

    /// Set once by `bind(_:)`. It cannot be an init argument: this object is
    /// a `@StateObject`, which SwiftUI builds before the environment exists,
    /// so the client arrives one `.task` later than the conversation does.
    private var api: APIClient?
    /// Tokens that have arrived but are not on screen yet. Deliberately not
    /// `@Published`.
    private var buffer = ""
    private var flusher: Task<Void, Never>?

    /// Hand over the environment's client. Idempotent — the tab's `.task` runs
    /// again every time you come back to it, and rebinding mid-stream would
    /// swap the client out from under a request in flight.
    func bind(_ client: APIClient) { if api == nil { api = client } }

    // MARK: Asking

    func newChat() {
        cancelFlusher()
        turns = []
        chatId = nil
        chatTitle = ""
        stage = ""
        pivot = nil
    }

    /// Load a past conversation. History arrives as a flat list of messages;
    /// they pair back into turns in order, and an assistant message with no
    /// question before it (it happens after a delete) still gets a turn rather
    /// than being dropped.
    func open(_ chat: JudeChatSummary) async {
        guard let api else { return }
        cancelFlusher()
        turns = []
        chatId = chat.id
        chatTitle = chat.title
        stage = ""
        pivot = nil
        do {
            let messages = try await api.judeHistory(chat.id)
            var pending: JudeTurn?
            for message in messages {
                if message.role == "user" {
                    if let pending { turns.append(pending) }
                    pending = JudeTurn(question: message.content, mode: chat.mode,
                                       streaming: false)
                } else {
                    var turn = pending ?? JudeTurn(question: "", mode: chat.mode,
                                                   streaming: false)
                    turn.answer = message.content
                    turn.sources = message.sources
                    turns.append(turn)
                    pending = nil
                }
            }
            if let pending { turns.append(pending) }
        } catch {
            turns = [JudeTurn(question: chat.title, streaming: false,
                              error: "Couldn't load this conversation: "
                                     + error.localizedDescription)]
        }
    }

    func ask(_ prompt: String, mode: String, lang: String, topK: Int,
             skipClarification: Bool = false) {
        guard let api, !asking else { return }
        asking = true
        stage = ""
        buffer = ""
        turns.append(JudeTurn(question: prompt, mode: mode))
        let index = turns.count - 1
        if chatTitle.isEmpty { chatTitle = String(prompt.prefix(55)) }
        startFlusher(index)

        Task {
            do {
                try await api.judeAsk(prompt, chatId: self.chatId, mode: mode, lang: lang,
                                      topK: topK, skipClarification: skipClarification) { event in
                    self.apply(event, to: index, originalPrompt: prompt)
                }
            } catch {
                self.turns[index].error = error.localizedDescription
            }
            // The connection can drop before `done`; flush whatever arrived
            // rather than losing the last fraction of a second of an answer
            // that took a minute and a half to produce.
            self.cancelFlusher()
            self.flush(into: index)
            self.turns[index].streaming = false
            if self.turns[index].isEmpty {
                self.turns[index].error = "No response was generated. Try rephrasing the question."
            }
            self.asking = false
            self.stage = ""
        }
    }

    private func apply(_ event: JudeEvent, to index: Int, originalPrompt: String) {
        guard index < turns.count else { return }
        switch event.type {
        case "stage":
            stage = event.name

        case "token":
            buffer += event.text

        case "meta":
            chatId = event.chatId ?? chatId
            turns[index].sources = event.sources
            turns[index].steps = event.steps
            if !event.mode.isEmpty { turns[index].mode = event.mode }
            if !event.halachicLabel.isEmpty {
                let seder = event.halachicSeder.isEmpty ? "" : " · Seder \(event.halachicSeder)"
                turns[index].topicBadge = event.halachicLabel + seder
            } else if event.mode == "study", let pool = event.studyPoolSize, pool > 0 {
                turns[index].poolBadge = "Study · \(pool) sources loaded"
            }

        case "tool_call":
            turns[index].toolCalls.append(event.toolCall)
            // New sources are as citable as the retrieved ones, and an answer
            // that quotes a passage missing from its own source list is
            // exactly the uncheckable answer Jude exists to avoid.
            turns[index].sources.append(contentsOf: event.newSources)
            let summary = event.resultSummary.isEmpty ? "" : " — \(event.resultSummary)"
            stage = "🔧 \(event.tool)\(summary)"

        case "clarification":
            chatId = event.chatId ?? chatId
            turns[index].clarification = JudeClarification(
                question: event.question.isEmpty ? "Did you mean one of these?" : event.question,
                options: event.options,
                originalPrompt: originalPrompt)

        case "topic_pivot":
            // Non-blocking on purpose: Jude keeps answering either way and the
            // confirmation only sets a label, so this must never gate the
            // stream or steal focus from the answer arriving behind it.
            pivot = JudePivot(previous: event.previousTopic, candidate: event.candidateTopic)

        case "done":
            turns[index].timing = event.timing

        case "error":
            turns[index].error = event.message.isEmpty ? "Something went wrong." : event.message

        default:
            break
        }
    }

    // MARK: Topic pivot

    func confirmPivot() {
        guard let pivot, let chatId, let api else { self.pivot = nil; return }
        let topic = pivot.candidate
        self.pivot = nil
        Task { try? await api.judeSetTopic(chatId, topic: topic) }
    }

    func dismissPivot() { pivot = nil }

    // MARK: Token batching

    /// Repaint at ~12 Hz instead of once per token.
    ///
    /// ARCHITECTURE.md names this as one of the three things that will bite:
    /// the previous Mac app inserted every token through a cursor, so a
    /// 2,000-token answer triggered 2,000 full relayouts, and that was the
    /// lag. SwiftUI has the same problem in a different shape — each append to
    /// a `@Published` turn re-evaluates the whole conversation body.
    private func startFlusher(_ index: Int) {
        flusher?.cancel()
        flusher = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 80_000_000)
                guard let self, !Task.isCancelled else { return }
                self.flush(into: index)
            }
        }
    }

    private func cancelFlusher() {
        flusher?.cancel()
        flusher = nil
    }

    private func flush(into index: Int) {
        guard !buffer.isEmpty, index < turns.count else { return }
        turns[index].answer += buffer
        buffer = ""
    }
}

// MARK: - The view

struct JudeView: View {
    @EnvironmentObject var api: APIClient
    @EnvironmentObject var settings: AppSettings

    @State private var status: JudeStatus?
    @StateObject private var chat = JudeConversation()

    @State private var draft = ""
    @State private var mode = "qa"
    @State private var lang = "en"
    @State private var topK: Double = 25
    @State private var showChats = false

    var body: some View {
        NavigationView {
            VStack(spacing: 0) {
                if let status, !status.ready {
                    unavailable(status)
                } else {
                    conversation
                    if let pivot = chat.pivot { pivotBanner(pivot) }
                    Divider()
                    JudeComposer(draft: $draft, mode: $mode, lang: $lang, topK: $topK,
                                 isBusy: chat.asking, onSend: send)
                }
            }
            .navigationTitle(chat.chatTitle.isEmpty ? "Jude" : chat.chatTitle)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    Button { showChats = true } label: {
                        Image(systemName: "clock.arrow.circlepath")
                    }
                    .accessibilityLabel("Past conversations")
                }
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button { chat.newChat() } label: { Image(systemName: "square.and.pencil") }
                        .disabled(chat.asking || chat.turns.isEmpty)
                        .accessibilityLabel("New conversation")
                }
            }
        }
        .navigationViewStyle(.stack)
        .sheet(isPresented: $showChats) {
            JudeChatList(currentChatId: chat.chatId,
                         onOpen: { summary in Task { await chat.open(summary) } },
                         onNew: { chat.newChat() })
        }
        .onAppear { chat.bind(api) }
        .task {
            status = await api.judeStatus()
        }
        .onReceive(api.$isOnline) { _ in
            Task { status = await api.judeStatus() }
        }
    }

    // MARK: - Conversation

    private var conversation: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 20) {
                    if chat.turns.isEmpty { welcome }
                    ForEach(chat.turns) { turn in
                        turnView(turn).id(turn.id)
                    }
                    if chat.asking { thinking.id("thinking") }
                }
                .padding(16)
            }
            .onChange(of: chat.turns.last?.answer) { _ in
                withAnimation { proxy.scrollTo(chat.turns.last?.id, anchor: .bottom) }
            }
            .onChange(of: chat.asking) { busy in
                if busy { withAnimation { proxy.scrollTo("thinking", anchor: .bottom) } }
            }
        }
    }

    @ViewBuilder
    private func turnView(_ turn: JudeTurn) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            if !turn.question.isEmpty {
                Text(turn.question)
                    .font(.headline)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }

            if !turn.topicBadge.isEmpty {
                badge(turn.topicBadge, icon: "books.vertical", tint: settings.accentColor)
            } else if !turn.poolBadge.isEmpty {
                badge(turn.poolBadge, icon: "text.book.closed", tint: .secondary)
            } else if turn.mode == "sources" {
                badge("Sources only", icon: "list.bullet.rectangle", tint: .secondary)
            }

            if !turn.answer.isEmpty { answerText(turn) }

            if let clarification = turn.clarification {
                clarificationCard(clarification)
            }

            if !turn.error.isEmpty {
                Label(turn.error, systemImage: "exclamationmark.triangle")
                    .font(.footnote).foregroundColor(.orange)
                    .fixedSize(horizontal: false, vertical: true)
            }

            JudeSourcesSection(sources: turn.sources)
            JudeTracePanel(steps: turn.steps, toolCalls: turn.toolCalls, timing: turn.timing)

            if !turn.answer.isEmpty && !turn.streaming {
                Button {
                    UIPasteboard.general.string = turn.answer
                } label: {
                    Label("Copy", systemImage: "doc.on.doc").font(.caption2)
                }
                .buttonStyle(.plain)
                .foregroundColor(.secondary)
            }
        }
    }

    /// Markdown once the answer is finished, plain text while it streams.
    ///
    /// Jude writes its answers in markdown — bold section headings, emphasis,
    /// bracketed citations — and rendering it flat loses the structure of a
    /// long halachic answer. But parsing it is not free, and doing it on every
    /// one of the ~12 repaints a second while tokens arrive is the same cost
    /// the batching in `JudeConversation` exists to avoid.
    ///
    /// `.inlineOnlyPreservingWhitespace` rather than `.full`: full markdown
    /// collapses the blank lines Jude uses between sections, which is most of
    /// what makes a long answer readable.
    @ViewBuilder
    private func answerText(_ turn: JudeTurn) -> some View {
        if turn.streaming {
            Text(turn.answer)
                .font(.body)
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
        } else {
            Text(judeMarkdown(turn.answer))
                .font(.body)
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
                .environment(\.layoutDirection, lang == "he" ? .rightToLeft : .leftToRight)
                .multilineTextAlignment(lang == "he" ? .trailing : .leading)
        }
    }

    private func judeMarkdown(_ text: String) -> AttributedString {
        (try? AttributedString(
            markdown: text,
            options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace,
                           failurePolicy: .returnPartiallyParsedIfPossible)))
            ?? AttributedString(text)
    }

    private func badge(_ text: String, icon: String, tint: Color) -> some View {
        Label(text, systemImage: icon)
            .font(.caption.weight(.semibold))
            .foregroundColor(tint)
            .padding(.horizontal, 8).padding(.vertical, 4)
            .background(tint.opacity(0.12))
            .cornerRadius(Theme.radiusSM)
    }

    // MARK: - While it thinks

    /// The 30-to-90-second wait, made legible.
    ///
    /// Five model calls happen behind this, and for most of that time there is
    /// nothing else to show — no tokens, no sources. So the stage name gets a
    /// card of its own and a running spinner rather than a grey footnote, and
    /// the first question of a session says why it is slower (Jude loads its
    /// index on the first question — `ready` is not `running`).
    private var thinking: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 10) {
                ProgressView()
                Text(chat.stage.isEmpty ? "Thinking…" : chat.stage)
                    .font(.subheadline.weight(.semibold))
                    .foregroundColor(.primary)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: 0)
            }
            Text(status?.running == false
                 ? "Jude loads its index on the first question, so this one takes longer."
                 : "Five model calls per question — the last one writes the answer.")
                .font(.caption).foregroundColor(.secondary)
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(settings.accentColor.opacity(0.10))
        .cornerRadius(Theme.radiusMD)
    }

    // MARK: - Clarification

    private func clarificationCard(_ c: JudeClarification) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Label(c.question, systemImage: "questionmark.bubble")
                .font(.subheadline.weight(.semibold))
                .fixedSize(horizontal: false, vertical: true)
            ForEach(c.options) { option in
                Button {
                    chat.ask(option.prompt, mode: mode, lang: lang, topK: Int(topK))
                } label: {
                    Text(option.label)
                        .font(.footnote)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(8)
                        .background(Color(.secondarySystemBackground))
                        .cornerRadius(Theme.radiusSM)
                }
                .buttonStyle(.plain)
                .disabled(chat.asking)
            }
            // Skipping re-asks the ORIGINAL question with skip_clarification,
            // which is what makes it a skip rather than a rephrase: Jude
            // answers what was actually asked instead of asking again.
            Button {
                chat.ask(c.originalPrompt, mode: mode, lang: lang, topK: Int(topK),
                         skipClarification: true)
            } label: {
                Text("Continue with my original question →").font(.caption)
            }
            .buttonStyle(.plain)
            .foregroundColor(settings.accentColor)
            .disabled(chat.asking)
        }
        .padding(12)
        .background(Color(.secondarySystemBackground).opacity(0.6))
        .cornerRadius(Theme.radiusMD)
    }

    // MARK: - Topic pivot

    /// A banner, not a dialog. Jude keeps answering whatever you choose, and
    /// the confirmation only relabels the conversation — so this sits above
    /// the composer and waits, rather than interrupting an answer mid-stream
    /// to ask about its filing.
    private func pivotBanner(_ pivot: JudePivot) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "arrow.triangle.branch").font(.caption)
            VStack(alignment: .leading, spacing: 6) {
                Text("Moved from **\(pivot.previous)** to **\(pivot.candidate)**. Update the topic?")
                    .font(.caption)
                    .fixedSize(horizontal: false, vertical: true)
                HStack(spacing: 12) {
                    Button("Update") { chat.confirmPivot() }
                        .font(.caption.weight(.semibold))
                    Button("Keep \(pivot.previous)") { chat.dismissPivot() }
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
                .buttonStyle(.plain)
            }
            Spacer(minLength: 0)
            Button { chat.dismissPivot() } label: {
                Image(systemName: "xmark").font(.caption2)
            }
            .buttonStyle(.plain)
            .foregroundColor(.secondary)
            .accessibilityLabel("Dismiss")
        }
        .padding(10)
        .background(settings.accentColor.opacity(0.12))
    }

    // MARK: - Empty state

    private var welcome: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("What would you like to learn?").font(.title3.weight(.semibold))
            Text("Torah, Talmud, midrash, halacha, machshava — every answer cites the "
                 + "passages it was built from, and each one links back to Sefaria, so "
                 + "you can check it rather than take its word.")
                .font(.footnote).foregroundColor(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            ForEach(Self.examples, id: \.prompt) { example in
                Button { draft = example.prompt } label: {
                    VStack(alignment: .leading, spacing: 3) {
                        Text(example.category)
                            .font(.caption2.weight(.bold))
                            .foregroundColor(settings.accentColor)
                        Text(example.prompt)
                            .font(.footnote).foregroundColor(.primary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color(.secondarySystemBackground))
                    .cornerRadius(Theme.radiusMD)
                }
                .buttonStyle(.plain)
            }
        }
        .padding(.bottom, 4)
    }

    private static let examples: [(category: String, prompt: String)] = [
        ("Halacha", "Is it permitted to carry an umbrella on Shabbat?"),
        ("Narrative", "What happened at Mount Sinai when the Torah was given?"),
        ("Talmudic debate", "What is the debate between Beit Hillel and Beit Shammai?"),
        ("Machshava", "What does Kabbalah teach about the nature of the soul?"),
    ]

    // MARK: - Not available

    /// When `ready` is false the Mac has already written the sentence to show
    /// — it is the one that knows whether Jude is uninstalled, switched off or
    /// misconfigured. So this draws `reason` and the repo link and invents
    /// nothing else: a second explanation guessed at on the phone would
    /// eventually contradict the real one.
    @ViewBuilder
    private func unavailable(_ status: JudeStatus) -> some View {
        VStack(spacing: 14) {
            Spacer()
            Image(systemName: "books.vertical")
                .font(.system(size: 42)).foregroundColor(.secondary)
            Text(status.reason)
                .font(.footnote).foregroundColor(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 28)
            if !status.repo.isEmpty, let url = URL(string: status.repo) {
                Link(status.repo, destination: url)
                    .font(.footnote)
                    .foregroundColor(settings.accentColor)
                    .padding(.horizontal, 28)
                    .multilineTextAlignment(.center)
            }
            Button("Check again") { Task { self.status = await api.judeStatus() } }
                .buttonStyle(.bordered)
            Spacer()
        }
        .frame(maxWidth: .infinity)
    }

    // MARK: - Sending

    private func send() {
        let prompt = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !prompt.isEmpty, !chat.asking else { return }
        draft = ""
        chat.ask(prompt, mode: mode, lang: lang, topK: Int(topK))
    }
}
