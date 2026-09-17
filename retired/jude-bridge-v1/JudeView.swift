import SwiftUI

/// Jude — the Judaic study assistant, as a tab.
///
/// Jude is a separate project (a five-stage RAG pipeline over ~289,000 Sefaria
/// passages) running beside the assistant on the Mac. This tab never talks to
/// it directly: every question is a POST to the assistant's own API, over the
/// same tailnet, with the same key, and comes back as the same NDJSON stream
/// `/voice/stream` uses. One address, one protocol — see
/// `DOCUMENTATION/JUDE.md`.
///
/// Which means it needs the Mac. Unlike the calendar and the task list, there
/// is nothing to cache: the corpus is gigabytes and the thinking is the point.
/// So when the Mac is away this says so, rather than pretending.
struct JudeView: View {
    @EnvironmentObject var api: APIClient
    @EnvironmentObject var settings: AppSettings

    @State private var status: JudeStatus?
    @State private var turns: [Turn] = []
    @State private var draft = ""
    @State private var mode = "qa"
    @State private var chatId: String?
    @State private var stage = ""
    @State private var asking = false
    @FocusState private var entryFocused: Bool

    /// One question and the answer as it arrives. `answer` grows token by
    /// token, which is why this is a class-free struct held in an array rather
    /// than something streamed straight into a text view.
    struct Turn: Identifiable {
        let id = UUID()
        let question: String
        var answer: String = ""
        var sources: [JudeSource] = []
        var topic: String = ""
        var error: String = ""
    }

    var body: some View {
        NavigationView {
            VStack(spacing: 0) {
                if let status, !status.ready {
                    unavailable(status)
                } else {
                    conversation
                    Divider()
                    composer
                }
            }
            .navigationTitle("Jude")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button { newChat() } label: { Image(systemName: "square.and.pencil") }
                        .disabled(asking || turns.isEmpty)
                        .accessibilityLabel("New conversation")
                }
            }
        }
        .task { status = await api.judeStatus() }
        .onReceive(api.$isOnline) { _ in
            Task { status = await api.judeStatus() }
        }
    }

    // MARK: - Pieces

    private var conversation: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 18) {
                    if turns.isEmpty { welcome }
                    ForEach(turns) { turn in
                        VStack(alignment: .leading, spacing: 8) {
                            Text(turn.question)
                                .font(.headline)
                                .frame(maxWidth: .infinity, alignment: .leading)

                            if !turn.topic.isEmpty {
                                Label(turn.topic, systemImage: "books.vertical")
                                    .font(.caption).foregroundColor(.secondary)
                            }
                            if !turn.answer.isEmpty {
                                Text(turn.answer)
                                    .font(.body)
                                    .textSelection(.enabled)
                            }
                            if !turn.error.isEmpty {
                                Text(turn.error).font(.footnote).foregroundColor(.red)
                            }
                            if !turn.sources.isEmpty {
                                sources(turn.sources)
                            }
                        }
                        .id(turn.id)
                    }
                    if asking {
                        HStack(spacing: 8) {
                            ProgressView()
                            Text(stage.isEmpty ? "Thinking…" : stage)
                                .font(.footnote).foregroundColor(.secondary)
                        }
                        .id("thinking")
                    }
                }
                .padding(16)
            }
            .onChange(of: turns.last?.answer) { _ in
                withAnimation { proxy.scrollTo(turns.last?.id, anchor: .bottom) }
            }
        }
    }

    private var welcome: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Ask about Torah, Talmud, halacha, midrash or machshava.")
                .font(.body)
            Text("Every answer cites the passages it was built from, and each one links "
                 + "back to Sefaria — so you can check it rather than take its word.")
                .font(.footnote).foregroundColor(.secondary)
            if let status, status.running == false {
                Text("Jude loads its index on your first question, so that one takes longer.")
                    .font(.footnote).foregroundColor(.secondary)
            }
        }
        .padding(.bottom, 8)
    }

    @ViewBuilder
    private func sources(_ list: [JudeSource]) -> some View {
        DisclosureGroup("Sources (\(list.count))") {
            VStack(alignment: .leading, spacing: 6) {
                ForEach(list) { s in
                    if let url = s.url, let link = URL(string: url) {
                        Link(destination: link) {
                            HStack(spacing: 6) {
                                if s.isPrimary == true {
                                    Image(systemName: "scalemass").font(.caption2)
                                }
                                Text(s.ref).font(.footnote)
                            }
                        }
                    } else {
                        Text(s.ref).font(.footnote).foregroundColor(.secondary)
                    }
                }
            }
            .padding(.top, 4)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .font(.footnote)
    }

    private var composer: some View {
        VStack(spacing: 8) {
            Picker("Mode", selection: $mode) {
                Text("Q&A").tag("qa")
                Text("Study").tag("study")
                Text("Sources").tag("sources")
            }
            .pickerStyle(.segmented)

            HStack(spacing: 8) {
                TextField("Ask a question…", text: $draft, axis: .vertical)
                    .lineLimit(1...4)
                    .textFieldStyle(.roundedBorder)
                    .focused($entryFocused)
                    .disabled(asking)
                Button { ask() } label: {
                    Image(systemName: "arrow.up.circle.fill")
                        .font(.system(size: 28))
                }
                .disabled(asking || draft.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }
        .padding(12)
    }

    @ViewBuilder
    private func unavailable(_ status: JudeStatus) -> some View {
        VStack(spacing: 14) {
            Spacer()
            Image(systemName: "books.vertical")
                .font(.system(size: 42)).foregroundColor(.secondary)
            Text("Jude isn't available").font(.headline)
            Text(status.reason)
                .font(.footnote).foregroundColor(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 28)
            if !status.repo.isEmpty, let url = URL(string: status.repo) {
                Link("Jude on GitHub", destination: url).font(.footnote)
            }
            Button("Check again") { Task { self.status = await api.judeStatus() } }
                .buttonStyle(.bordered)
            Spacer()
        }
        .frame(maxWidth: .infinity)
    }

    // MARK: - Asking

    private func newChat() {
        chatId = nil
        turns = []
        stage = ""
        entryFocused = true
    }

    private func ask() {
        let prompt = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !prompt.isEmpty, !asking else { return }
        draft = ""
        entryFocused = false
        asking = true
        stage = ""
        turns.append(Turn(question: prompt))
        let index = turns.count - 1

        Task {
            do {
                try await api.judeAsk(prompt, chatId: chatId, mode: mode) { event in
                    apply(event, to: index)
                }
            } catch {
                if index < turns.count {
                    turns[index].error = error.localizedDescription
                }
            }
            asking = false
            stage = ""
            // A refused or failed question may be the first sign that the Mac
            // (or Jude) is no longer there — say so in the header rather than
            // leaving the composer looking ready.
            status = await api.judeStatus()
        }
    }

    private func apply(_ event: JudeEvent, to index: Int) {
        guard index < turns.count else { return }
        switch event.type {
        case "stage":
            stage = event.name ?? ""
        case "token":
            turns[index].answer += event.text ?? ""
        case "meta":
            chatId = event.chatId ?? chatId
            turns[index].sources = event.sources ?? []
            if let label = event.halachicLabel, !label.isEmpty {
                let seder = event.halachicSeder.map { " · Seder \($0)" } ?? ""
                turns[index].topic = label + seder
            }
        case "clarification":
            // Jude asks back when a question is ambiguous. Shown as the answer,
            // because that is what it is — the next message continues the same
            // chat, so answering in the composer works.
            var text = event.question ?? ""
            for option in event.options ?? [] { text += "\n• " + option }
            turns[index].answer += text
        case "error":
            turns[index].error = event.message ?? "Something went wrong."
        default:
            break
        }
    }
}
