import Foundation
#if canImport(FoundationModels)
import FoundationModels
#endif

// MARK: - Jude answered on this phone (Gil, 2026-10-11, option A)
//
// The Mac finds the sources — Jude's own "sources" mode: route, retrieve,
// filter, no synthesis — and this phone writes the answer from them with
// Apple's on-device model. The library (1.2 GB of text, a 2 GB index) stays on
// the Mac; only the handful of passages an answer needs crosses the wire.
//
// The on-device model is small and its window is ~4,096 tokens for question,
// sources and answer together, so it is given the top passages, trimmed, and
// told to answer only from them and to name the source behind each claim.

enum JudeOnDevice {
    /// Passages handed to the model, and how much of each.
    static let maxSources = 6
    static let maxCharsPerSource = 650

    static var isAvailable: Bool { OfflineReader.isAvailable }

    /// Why it can't answer here, in a sentence — or nil when it can.
    static var unavailableReason: String? {
        isAvailable ? nil : OfflineReader.availabilityNote
    }

    static let instructions = """
    You are Jude, a Judaic study assistant. Answer the question using ONLY the \
    numbered sources given. After each claim, name the source it comes from in \
    square brackets, by its reference, e.g. [Berakhot 2a:1]. If the sources do \
    not answer the question, say so plainly rather than answering from memory. \
    Be concise: a few short paragraphs at most. Your reasoning is not \
    authoritative; the sources are.
    """

    /// The question and the top sources, trimmed to fit the model's window.
    static func prompt(question: String, sources: [JudeSource], lang: String) -> String {
        var lines = ["Question: \(question)", "", "Sources:"]
        for (i, s) in sources.prefix(maxSources).enumerated() {
            let text = (lang == "he" && !s.heText.isEmpty ? s.heText : s.enText)
                .replacingOccurrences(of: "\n", with: " ")
            let trimmed = text.count > maxCharsPerSource
                ? String(text.prefix(maxCharsPerSource)) + "…" : text
            lines.append("[\(i + 1)] \(s.ref): \(trimmed)")
        }
        lines.append("")
        lines.append(lang == "he" ? "Answer in Hebrew." : "Answer in English.")
        return lines.joined(separator: "\n")
    }

    enum Failure: LocalizedError {
        case unavailable(String)
        var errorDescription: String? {
            switch self { case .unavailable(let why): return why }
        }
    }

    /// Stream the answer: `onText` gets each new piece as it is written.
    static func answer(question: String, sources: [JudeSource], lang: String,
                       onText: @escaping (String) -> Void) async throws {
        #if canImport(FoundationModels)
        if #available(iOS 26.0, *), isAvailable {
            let session = LanguageModelSession(instructions: instructions)
            var sent = 0
            for try await snapshot in session.streamResponse(
                to: prompt(question: question, sources: sources, lang: lang)) {
                let text = snapshot.content
                if text.count > sent {
                    onText(String(text.dropFirst(sent)))
                    sent = text.count
                }
            }
            return
        }
        #endif
        throw Failure.unavailable(unavailableReason ?? "This phone can't run Apple's model.")
    }
}

extension JudeStep {
    /// A step the phone took itself — shown in the trace like Jude's own.
    init(module: String, durationMs: Double) {
        self.module = module
        self.durationMs = durationMs
    }
}
