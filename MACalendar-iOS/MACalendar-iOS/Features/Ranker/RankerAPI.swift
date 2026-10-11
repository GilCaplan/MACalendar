import Foundation

// MARK: - Ranker's calls
//
// The routes are `assistant/features/ranker/routes.py` (documented at its
// top). An extension, like Flashcards' and Jude's, so the offline breaker, the
// key and the address are the shared ones.
//
// The offline rule (`assistant/features/CONVENTION.md`): the three plain
// overwrites — the number list, saving a recipe, removing one — go through
// `mutate`, so with the Mac away they queue and land when it is back. Three
// calls do not, each named in `test_ios_offline.py`'s NOT_QUEUEABLE:
//
// - `rankTable` and `readRankerNumbers` send FILES (a table, screenshots) and
//   the answer IS the point — a ranking, the numbers read. The queue holds
//   JSON bodies, and a ranking delivered an hour later is for a screen nobody
//   is looking at. Offline they throw `.offline` and the tab says so.
// - `rankerUpload` is the multipart transport under both.
// - `newRankerSearch` forgets the Mac's table and number list. Queued, it would
//   replay whenever the Mac came back and wipe whatever table had been sent
//   since (the Mac panel shares the same store); and it is pressed to start
//   ranking, which needs the Mac anyway. Offline it throws and the tab says so.
extension APIClient {

    // -- reads ----------------------------------------------------------

    func rankerOverview() async throws -> RankerOverview {
        RankerOverview(json: try Self.rankerObject(try await request("/ranker")))
    }

    // -- plain overwrites (queued offline) ----------------------------

    /// The list as edited. False when queued. (Switching the filter off is
    /// `use_numbers` on a rank, which keeps the list; `[]` here erases it.)
    @discardableResult
    func setRankerNumbers(_ numbers: [Int]) async throws -> Bool {
        try await mutate("/ranker/numbers", method: "PUT", body: ["numbers": numbers]) != nil
    }

    /// Save a recipe under its name. nil when the Mac was away and it queued.
    @discardableResult
    func saveRankerPreset(_ recipe: RankerRecipe) async throws -> RankerOverview? {
        guard let data = try await mutate("/ranker/presets/\(Self.rankerSegment(recipe.name))",
                                          method: "PUT", body: recipe.json) else { return nil }
        return RankerOverview(json: try Self.rankerObject(data))
    }

    @discardableResult
    func deleteRankerPreset(_ name: String) async throws -> RankerOverview? {
        guard let data = try await mutate("/ranker/presets/\(Self.rankerSegment(name))",
                                          method: "DELETE") else { return nil }
        return RankerOverview(json: try Self.rankerObject(data))
    }

    // -- online only, see the header ---------------------------------

    /// Start a new search: the Mac forgets the table and the numbers, keeps
    /// the saved rankings. Answers like `GET /ranker`.
    func newRankerSearch() async throws -> RankerOverview {
        RankerOverview(json: try Self.rankerObject(try await request("/ranker/new", method: "POST")))
    }

    /// Read the numbers in the pictures; the Mac keeps them as the list.
    func readRankerNumbers(images: [RankerUpload]) async throws -> [Int] {
        let reply = try await rankerUpload("/ranker/numbers", fields: [:],
                                           files: images.map { ("image", $0) })
        return RankerOverview.ints(try Self.rankerObject(reply)["numbers"])
    }

    /// Rank. Anything left out is the Mac's saved one: no `table` re-ranks the
    /// last table it was sent, no `recipe` uses `preset` (or the current one),
    /// `numbers == nil` keeps the saved list. `useNumbers` is the filter
    /// switch: false ranks every row and KEEPS the list (never send `[]` for
    /// "off" — that erases it).
    func rankTable(table: RankerUpload?, images: [RankerUpload], numbers: [Int]?,
                   useNumbers: Bool?, preset: String?,
                   recipe: RankerRecipe?) async throws -> RankerResult {
        var fields: [String: String] = [:]
        if let useNumbers { fields["use_numbers"] = useNumbers ? "true" : "false" }
        if let numbers, images.isEmpty,
           let data = try? JSONSerialization.data(withJSONObject: numbers) {
            fields["numbers"] = String(data: data, encoding: .utf8)
        }
        if let recipe { fields["recipe"] = recipe.jsonString }
        else if let preset, !preset.isEmpty { fields["preset"] = preset }
        var files: [(String, RankerUpload)] = images.map { ("image", $0) }
        if let table { files.insert(("table", table), at: 0) }
        let reply = try await rankerUpload("/ranker/rank", fields: fields, files: files)
        return RankerResult(json: try Self.rankerObject(reply))
    }

    /// A multipart POST with any number of files. Same guards as `request`:
    /// the address, the Settings switch, the offline breaker, the key. A long
    /// leash, because the Mac may be reading several screenshots.
    private func rankerUpload(_ path: String, fields: [String: String],
                              files: [(field: String, file: RankerUpload)]) async throws -> Data {
        guard !base.isEmpty, !base.contains("x.x.x"), let url = URL(string: base + path) else {
            throw APIError.badURL
        }
        guard settings.serverEnabled else {
            throw APIError.offline("working offline — the server is switched off in Settings")
        }
        if isBackingOff { throw APIError.offline("the Mac was unreachable a moment ago") }
        var req = URLRequest(url: url, timeoutInterval: 120)
        req.httpMethod = "POST"
        authorize(&req)
        let boundary = UUID().uuidString
        req.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        var body = Data()
        func add(_ s: String) { body.append(Data(s.utf8)) }
        for (k, v) in fields {
            add("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(k)\"\r\n\r\n\(v)\r\n")
        }
        for (field, file) in files {
            let safe = file.filename.replacingOccurrences(of: "\"", with: "")
            add("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(field)\"; filename=\"\(safe)\"\r\n")
            add("Content-Type: \(file.mime)\r\n\r\n")
            body.append(file.data)
            add("\r\n")
        }
        add("--\(boundary)--\r\n")
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
            noteUnreachable()
            if isOnline { isOnline = false }
            throw APIError.offline(error.localizedDescription)
        }
    }

    private static func rankerObject(_ data: Data) throws -> [String: Any] {
        guard let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw APIError.serverError("{\"error\": \"Your Mac answered with something this app could not read.\"}")
        }
        return obj
    }

    /// A recipe name as one path segment ("Migration — active, populous…").
    private static func rankerSegment(_ name: String) -> String {
        var allowed = CharacterSet.urlPathAllowed
        allowed.remove(charactersIn: "/?#")
        return name.addingPercentEncoding(withAllowedCharacters: allowed) ?? name
    }
}
