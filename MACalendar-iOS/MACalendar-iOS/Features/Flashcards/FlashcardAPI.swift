import Foundation

// MARK: - Flashcards' calls
//
// The routes are `assistant/features/flashcards/routes.py` (documented at its
// top). An extension rather than a type of its own, the way Jude's calls are,
// so the offline circuit breaker, the key and the address are the shared ones.
//
// The offline rule (`assistant/features/CONVENTION.md`): **every write goes
// through `mutate`**, so with the Mac away it is queued and replayed — a
// review given on a train reaches the Mac when the phone next sees it. Three
// calls do not, each for a stated reason:
//
// - `flashcardInbox` asks the Mac to read ITS OWN inbox folder. It carries
//   nothing of the user's; replayed later it does a job nobody is waiting for.
// - `uploadFlashMedia` and `importFlashcards` send a FILE. The queue holds
//   JSON bodies, and both answers are needed now: an upload answers with the
//   path the card must name, an import with what it added or why it refused.
//   Offline they throw `.offline`, and the screens say so in a sentence.
//
// Creates carry a `client_token` minted ONCE per thing the user asked for, so
// a create that committed and lost its reply is not a second row on replay;
// and a `_temp_id` so anything queued behind it (a card added to a set made
// offline) is pointed at the real id when it lands (`syncPending`).
extension APIClient {

    // -- reads ----------------------------------------------------------

    /// The library and what was deleted on the Mac. A decode failure THROWS
    /// (never an empty library), so a reply this app cannot read takes nothing
    /// off the phone.
    func flashcardLibrary() async throws -> FlashLibrary {
        let data = try await request("/flashcards")
        return try JSONDecoder().decode(FlashLibrary.self, from: data)
    }

    func flashcardSet(_ id: Int) async throws -> FlashSet {
        try JSONDecoder().decode(FlashSet.self, from: try await request("/flashcards/sets/\(id)"))
    }

    func flashcardMedia(setId: Int, path: String) async throws -> Data {
        let enc = path.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? path
        return try await request("/flashcards/media/\(setId)/\(enc)")
    }

    /// Ask the Mac to import whatever an agent dropped in its inbox. Returns
    /// how many sets came in, or nil when the Mac could not be asked.
    func flashcardInbox() async -> Int? {
        guard let data = try? await request("/flashcards/inbox", method: "POST"),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let rows = obj["imported"] as? [[String: Any]] else { return nil }
        return rows.filter { $0["error"] == nil }.count
    }

    // -- subjects and sets ---------------------------------------------

    /// The real id, or nil when the create was queued for later.
    @discardableResult
    func createFlashSubject(name: String, tempId: Int) async throws -> Int? {
        let body: [String: Any] = ["name": name, "client_token": UUID().uuidString,
                                   "_temp_id": tempId]
        return Self.id(in: try await mutate("/flashcards/subjects", method: "POST", body: body))
    }

    func renameFlashSubject(_ id: Int, name: String) async throws {
        try await mutate("/flashcards/subjects/\(id)", method: "PATCH", body: ["name": name])
    }

    /// Archive keeps everything; it only takes the subject (and its sets) out
    /// of the library and the study picker. Queued like any write.
    func archiveFlashSubject(_ id: Int, archived: Bool) async throws {
        try await mutate("/flashcards/subjects/\(id)", method: "PATCH", body: ["archived": archived])
    }

    func deleteFlashSubject(_ id: Int) async throws {
        try await mutate("/flashcards/subjects/\(id)", method: "DELETE")
    }

    @discardableResult
    func createFlashSet(subjectId: Int, name: String, lang: String, dir: String,
                        tempId: Int) async throws -> Int? {
        let body: [String: Any] = ["subject_id": subjectId, "name": name, "lang": lang,
                                   "dir": dir, "client_token": UUID().uuidString,
                                   "_temp_id": tempId]
        return Self.id(in: try await mutate("/flashcards/sets", method: "POST", body: body))
    }

    func updateFlashSet(_ id: Int, fields: [String: Any]) async throws {
        try await mutate("/flashcards/sets/\(id)", method: "PATCH", body: fields)
    }

    func archiveFlashSet(_ id: Int, archived: Bool) async throws {
        try await mutate("/flashcards/sets/\(id)", method: "PATCH", body: ["archived": archived])
    }

    func deleteFlashSet(_ id: Int) async throws {
        try await mutate("/flashcards/sets/\(id)", method: "DELETE")
    }

    func resetFlashSet(_ id: Int) async throws {
        try await mutate("/flashcards/sets/\(id)/reset", method: "POST")
    }

    // -- cards ------------------------------------------------------------

    /// The card rides under `card` so the token and the placeholder id are not
    /// mistaken for card fields (the Mac refuses an unknown field).
    @discardableResult
    func addFlashCard(setId: Int, card: [String: Any], tempId: Int) async throws -> Int? {
        let body: [String: Any] = ["card": card, "client_token": UUID().uuidString,
                                   "_temp_id": tempId]
        return Self.id(in: try await mutate("/flashcards/sets/\(setId)/cards", method: "POST", body: body))
    }

    func updateFlashCard(_ id: Int, card: [String: Any]) async throws {
        try await mutate("/flashcards/cards/\(id)", method: "PATCH", body: ["card": card])
    }

    func deleteFlashCard(_ id: Int) async throws {
        try await mutate("/flashcards/cards/\(id)", method: "DELETE")
    }

    /// One answer. `at` is the instant it was given, so a review replayed from
    /// the queue schedules from the train, not from the moment it synced; the
    /// token makes the replay of one the Mac already has a no-op.
    func reviewFlashCard(cardId: Int, item: String, grade: Int, at: Date) async throws -> FlashProgress? {
        let body: [String: Any] = ["card_id": cardId, "item": item, "grade": grade,
                                   "at": Self.stamp(at), "source": "ios",
                                   "client_token": UUID().uuidString]
        guard let data = try await mutate("/flashcards/review", method: "POST", body: body)
        else { return nil }
        return try? JSONDecoder().decode(FlashProgress.self, from: data)
    }

    // -- files (online only, see the header) ---------------------------

    /// Upload a picture for a card; the answer is the path the card names.
    func uploadFlashMedia(setId: Int, filename: String, data: Data, mime: String) async throws -> String {
        let reply = try await uploadFile("/flashcards/sets/\(setId)/media", filename: filename,
                                         data: data, mime: mime,
                                         fields: ["path": "images/\(filename)"])
        guard let obj = try? JSONSerialization.jsonObject(with: reply) as? [String: Any],
              let path = obj["path"] as? String else {
            throw APIError.serverError("{\"error\": \"The Mac stored the picture but did not say where.\"}")
        }
        return path
    }

    /// Import a set file (.yaml / .json / .zip). Returns one sentence per set.
    func importFlashcards(filename: String, data: Data, mode: String = "replace") async throws -> [String] {
        let reply = try await uploadFile("/flashcards/import", filename: filename, data: data,
                                         mime: "application/octet-stream", fields: ["mode": mode])
        guard let obj = try? JSONSerialization.jsonObject(with: reply) as? [String: Any],
              let rows = obj["imported"] as? [[String: Any]] else { return [] }
        return rows.map { r in
            let name = r["set"] as? String ?? "a set"
            let subject = r["subject"] as? String ?? ""
            let added = r["added"] as? Int ?? 0, kept = r["kept"] as? Int ?? 0,
                removed = r["removed"] as? Int ?? 0
            var s = "\(subject.isEmpty ? "" : subject + " › ")\(name): \(added) new"
            if kept > 0 { s += ", \(kept) kept" }
            if removed > 0 { s += ", \(removed) removed" }
            return s
        }
    }

    /// A multipart POST with one file. Same guards as `request`: the address,
    /// the Settings switch, the offline breaker, the key and the session.
    private func uploadFile(_ path: String, filename: String, data: Data, mime: String,
                            fields: [String: String]) async throws -> Data {
        guard !base.isEmpty, let url = URL(string: base + path) else { throw APIError.badURL }
        guard settings.serverEnabled else {
            throw APIError.offline("working offline — the server is switched off in Settings")
        }
        if isBackingOff { throw APIError.offline("the Mac was unreachable a moment ago") }
        var req = URLRequest(url: url, timeoutInterval: 60)
        req.httpMethod = "POST"
        authorize(&req)
        let boundary = UUID().uuidString
        req.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        var body = Data()
        func add(_ s: String) { body.append(s.data(using: .utf8)!) }
        for (k, v) in fields {
            add("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(k)\"\r\n\r\n\(v)\r\n")
        }
        let safe = filename.replacingOccurrences(of: "\"", with: "")
        add("--\(boundary)\r\nContent-Disposition: form-data; name=\"file\"; filename=\"\(safe)\"\r\n")
        add("Content-Type: \(mime)\r\n\r\n")
        body.append(data)
        add("\r\n--\(boundary)--\r\n")
        req.httpBody = body
        do {
            let (reply, resp) = try await URLSession.shared.data(for: req)
            guard let http = resp as? HTTPURLResponse, (200...299).contains(http.statusCode) else {
                throw APIError.serverError(String(data: reply, encoding: .utf8) ?? "Unknown error")
            }
            noteReachable()
            if !isOnline { isOnline = true }
            return reply
        } catch let err as APIError {
            throw err
        } catch {
            throw APIError.offline(error.localizedDescription)
        }
    }

    private static func id(in data: Data?) -> Int? {
        guard let data,
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return nil }
        return obj["id"] as? Int
    }
}
