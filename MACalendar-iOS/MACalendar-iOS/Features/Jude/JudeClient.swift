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
    /// Three failures used to share one `try?`, and they are not the same thing:
    /// the Mac not answering; the Mac ANSWERING with something that is not a
    /// status (a 404 from an assistant older than Jude); and no address
    /// configured at all. All three said "isn't reachable" — while Settings, one
    /// tab over, had just shown the Mac online (2026-09-17, the day Jude
    /// shipped and the Mac's API was still on the previous branch).
    func judeStatus() async -> JudeStatus {
        let repo = "https://github.com/GilCaplan/JudeTheJudaicChatBot"
        func unavailable(_ reason: String) -> JudeStatus {
            JudeStatus(ready: false, reason: reason, repo: repo)
        }

        let data: Data
        do {
            data = try await request("/jude/status")
        } catch APIError.badURL {
            return unavailable("Set your Mac's address in Settings first — Jude "
                               + "does its thinking there.")
        } catch APIError.serverError {
            // The Mac answered, and not with a status. There is no
            // /jude/status on an assistant older than Jude, and that is the
            // likely story — telling the user their Mac is unreachable when it
            // just replied is the one answer that sends them looking in the
            // wrong place.
            return unavailable("Your Mac answered, but its assistant has no Jude "
                               + "endpoint — it is probably an older version. "
                               + "Update MACalendar on the Mac.")
        } catch {
            return unavailable("Your Mac isn't reachable. Jude does its thinking "
                               + "there, so this needs the Mac awake and on the "
                               + "tailnet.")
        }

        guard let st = try? JSONDecoder().decode(JudeStatus.self, from: data) else {
            // Reached the route and could not read the answer: still not an
            // unreachable Mac.
            return unavailable("Your Mac answered with something this app could "
                               + "not read. It may be a different version.")
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
        // tuned to "time to first byte" would be wrong here. 900 s matches
        // the Mac's own proxy timeout (`integrations/proxy.stream`): behind a
        // busy Ollama — a board running on the Mac — Jude's first line can
        // take minutes, and at 300 s this timed out while the Mac was fine
        // (2026-09-22). The proxy now sends a keepalive line while it waits,
        // so silence no longer means anything is wrong.
        var req = URLRequest(url: url, timeoutInterval: 900)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if !settings.apiKey.isEmpty {
            req.setValue(settings.apiKey, forHTTPHeaderField: "X-API-Key")
        }
        req.httpBody = try JSONSerialization.data(withJSONObject: body)

        let assertion = BackgroundAssertion()
        assertion.begin("jude-question")
        defer { assertion.end() }
        // Once the Mac has ANSWERED, a failure is the stream's, not the Mac's.
        // A stream that died mid-answer used to arm the shared "the Mac was
        // unreachable" backoff, so the next send was refused with that
        // sentence while the Mac was answering /jude/status all along
        // (2026-09-22). Only a connection that never opened marks the Mac
        // unreachable; everything after that is reported as what it is.
        var answered = false
        do {
            let (bytes, resp) = try await URLSession.shared.bytes(for: req)
            guard let http = resp as? HTTPURLResponse else {
                throw APIError.serverError("No response")
            }
            answered = true
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
            if answered {
                throw APIError.serverError("Jude's answer stopped arriving — "
                                           + error.localizedDescription)
            }
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

    /// Forget a conversation on the Mac. Queued when it is away, like every
    /// other write — `APIClient.mutate` explains why that decision is made in
    /// one place rather than per surface.
    func judeDeleteChat(_ chatId: String) async throws {
        try await mutate("/jude/chats/\(judeEscape(chatId))", method: "DELETE")
    }

    /// Confirm a topic pivot — the answer to the `topic_pivot` banner.
    ///
    /// Asynchronous by design: Jude keeps answering either way, so a client
    /// that never calls this loses nothing but the label on the conversation.
    /// That is why the banner does not block the stream — and why it is not
    /// queued: it answers a prompt the Mac raised, and one raised before the
    /// Mac went away is stale by the time it comes back.
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

    /// Turn a recording into words, WITHOUT running the engine on them.
    ///
    /// `POST /voice` transcribes and then executes — right when the words are a
    /// command, wrong when they are a question for Jude, which is a different
    /// brain entirely. `/voice/transcribe` is the Whisper half on its own, with
    /// the personal vocabulary applied: Whisper is trained on English and
    /// mangles exactly the words a Judaic question is made of.
    ///
    /// Deliberately NOT queued for later. A question transcribed three hours
    /// after it was asked is answered to nobody — the same reason Jude has no
    /// offline cache at all.
    func judeTranscribe(_ wav: Data) async throws -> String {
        guard settings.serverEnabled else {
            throw APIError.offline("working offline — the server is switched off in Settings")
        }
        guard !base.isEmpty, let url = URL(string: base + "/voice/transcribe") else {
            throw APIError.badURL
        }
        let boundary = "Boundary-\(UUID().uuidString)"
        var req = URLRequest(url: url, timeoutInterval: 60)
        req.httpMethod = "POST"
        req.setValue("multipart/form-data; boundary=\(boundary)",
                     forHTTPHeaderField: "Content-Type")
        if !settings.apiKey.isEmpty {
            req.setValue(settings.apiKey, forHTTPHeaderField: "X-API-Key")
        }
        var body = Data()
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"audio\"; filename=\"q.wav\"\r\n"
                    .data(using: .utf8)!)
        body.append("Content-Type: audio/wav\r\n\r\n".data(using: .utf8)!)
        body.append(wav)
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)
        req.httpBody = body

        let (data, resp) = try await URLSession.shared.data(for: req)
        guard let http = resp as? HTTPURLResponse, (200...299).contains(http.statusCode) else {
            throw APIError.serverError(String(data: data, encoding: .utf8) ?? "Transcription failed")
        }
        struct Reply: Codable { let text: String }
        return (try JSONDecoder().decode(Reply.self, from: data)).text
    }
}
