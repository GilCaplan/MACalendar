import Foundation

// MARK: - Jude's calls
//
// Every one of these is a route on the assistant's own API — same address,
// same key, same tailnet hop as the calendar. The phone never opens a socket
// to Jude's server: one client protocol rather than two that drift, which is
// the same reason the Mac app goes through :8080 instead of :8000.
//
// These lived in `API/APIClient.swift` until 2026-09-17. They are an extension
// rather than a separate type so callers still say `api.judeAsk(…)` and the
// offline circuit-breaker, the API key and the base-URL normalisation are the
// shared ones instead of a second copy that gets them subtly wrong.
extension APIClient {

    /// What the Mac can currently offer. **Never throws** — `GET /jude/status`
    /// is the one route that always answers, and an unreachable Mac is one of
    /// its answers rather than an error.
    ///
    /// Note that `reason` is what the UI draws, not a string this method
    /// invents: the Mac knows whether Jude is uninstalled, switched off or
    /// misconfigured, and the phone does not. The one sentence written here is
    /// the one case the Mac cannot report, because it is about the Mac.
    func judeStatus() async -> JudeStatus {
        guard let data = try? await request("/jude/status"),
              let st = try? JSONDecoder().decode(JudeStatus.self, from: data)
        else {
            return JudeStatus(
                ready: false,
                reason: "Your Mac isn't reachable. Jude does its thinking there, "
                        + "so this needs the Mac awake and on the tailnet.",
                repo: "https://github.com/GilCaplan/JudeTheJudaicChatBot")
        }
        return st
    }

    /// Ask Jude a question. Each NDJSON line is handed to `onEvent` on the
    /// main actor as it arrives; the call returns when the stream ends.
    ///
    /// Deliberately NOT queued for later like a voice command, and with no
    /// offline cache behind it: a voice command is an instruction that still
    /// makes sense in an hour, and a question is a conversation. Replaying one
    /// into the void three hours later answers it to nobody.
    ///
    /// - Parameters:
    ///   - topK: how many passages to retrieve, 5–30. The server clamps to
    ///     1–30 itself, so a bad value gets a sane answer rather than a 422.
    ///   - skipClarification: re-ask past a `clarification` event — this is
    ///     what the "continue with my original question" button sends.
    func judeAsk(_ prompt: String,
                 chatId: String?,
                 mode: String,
                 lang: String = "en",
                 topK: Int = 25,
                 skipClarification: Bool = false,
                 onEvent: @escaping (JudeEvent) -> Void) async throws {
        guard !base.isEmpty, let url = URL(string: base + "/jude/chat") else {
            throw APIError.badURL
        }
        if isBackingOff { throw APIError.offline("the Mac was unreachable a moment ago") }

        var body: [String: Any] = [
            "prompt": prompt, "mode": mode, "lang": lang,
            "top_k": topK, "skip_clarification": skipClarification,
        ]
        if let chatId { body["chat_id"] = chatId }

        // Generous: five model calls per question, and synthesis alone is
        // 30–90 s on a local model. The first token is not the first thing
        // that arrives either — the stage lines are, which is why a timeout
        // tuned to "time to first byte" would be wrong here.
        var req = URLRequest(url: url, timeoutInterval: 300)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if !settings.apiKey.isEmpty {
            req.setValue(settings.apiKey, forHTTPHeaderField: "X-API-Key")
        }
        req.httpBody = try JSONSerialization.data(withJSONObject: body)

        let assertion = BackgroundAssertion()
        assertion.begin("jude-question")
        defer { assertion.end() }
        do {
            let (bytes, resp) = try await URLSession.shared.bytes(for: req)
            guard let http = resp as? HTTPURLResponse else {
                throw APIError.serverError("No response")
            }
            guard (200...299).contains(http.statusCode) else {
                // The 503 for "Jude is off / not installed" carries a sentence
                // written for a person; surface that, not the status code.
                var detail = ""
                for try await line in bytes.lines { detail += line }
                let parsed = (try? JSONSerialization.jsonObject(with: Data(detail.utf8)))
                    as? [String: Any]
                throw APIError.serverError((parsed?["error"] as? String) ?? detail)
            }
            isOnline = true
            noteReachable()
            let decoder = JSONDecoder()
            for try await line in bytes.lines {
                guard !line.isEmpty, let data = line.data(using: .utf8),
                      let event = try? decoder.decode(JudeEvent.self, from: data)
                else { continue }
                onEvent(event)
            }
        } catch let err as APIError {
            throw err
        } catch {
            isOnline = false
            noteUnreachable()
            throw APIError.offline(error.localizedDescription)
        }
    }

    /// Past conversations, newest first as the Mac orders them.
    ///
    /// Returns an empty list rather than throwing when the Mac is away: the
    /// chat list is a sheet you opened to browse, and an alert about
    /// reachability there says nothing the tab header is not already saying.
    func judeChats() async -> [JudeChatSummary] {
        guard let data = try? await request("/jude/chats"),
              let list = try? JSONDecoder().decode([JudeChatSummary].self, from: data)
        else { return [] }
        return list
    }

    /// One conversation's messages, oldest first — user and assistant
    /// alternating, which is how the view pairs them back into turns.
    func judeHistory(_ chatId: String) async throws -> [JudeHistoryMessage] {
        let data = try await request("/jude/chats/\(judeEscape(chatId))/history")
        return try JSONDecoder().decode([JudeHistoryMessage].self, from: data)
    }

    /// Forget a conversation on the Mac.
    func judeDeleteChat(_ chatId: String) async throws {
        _ = try await request("/jude/chats/\(judeEscape(chatId))", method: "DELETE")
    }

    /// Confirm a topic pivot — the answer to the `topic_pivot` banner.
    ///
    /// Asynchronous by design: Jude keeps answering either way, so a client
    /// that never calls this loses nothing but the label on the conversation.
    /// That is why the banner does not block the stream.
    func judeSetTopic(_ chatId: String, topic: String) async throws {
        _ = try await request("/jude/chats/\(judeEscape(chatId))/topic",
                              method: "PUT", body: ["topic": topic])
    }

    /// Chat ids come from Jude's own store and have never contained anything
    /// exotic — but they go into a path, and a client that assumes that is one
    /// upstream id-scheme change away from building a broken URL silently.
    private func judeEscape(_ id: String) -> String {
        id.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? id
    }
}
