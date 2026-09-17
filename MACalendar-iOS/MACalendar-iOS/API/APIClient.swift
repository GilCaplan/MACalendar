import Foundation
import Security
import UIKit
@preconcurrency import UserNotifications

/// Keeps the app alive for the ~30 s iOS grants after it's backgrounded, so a
/// voice command that's mid-flight finishes instead of being suspended with
/// its stream half-read. Without this, walking away from the app right after
/// speaking dropped the thinking timeline (the Mac still ran the command —
/// the phone just stopped hearing about it).
@MainActor
final class BackgroundAssertion {
    private var id: UIBackgroundTaskIdentifier = .invalid

    func begin(_ name: String) {
        guard id == .invalid else { return }
        id = UIApplication.shared.beginBackgroundTask(withName: name) { [weak self] in
            self?.end()          // expiration handler — iOS is out of patience
        }
    }

    func end() {
        guard id != .invalid else { return }
        UIApplication.shared.endBackgroundTask(id)
        id = .invalid
    }
}

@MainActor
class APIClient: ObservableObject {
    @Published var isLoading  = false
    @Published var lastError: String?
    /// The last write the Mac REFUSED, in a sentence, until the user dismisses
    /// it. Not the same thing as `lastError`: an unreachable Mac is queued and
    /// says so in the offline banner, while a refusal is final and has nowhere
    /// else to appear. See `announceRefusal`.
    @Published var lastRefusal: String?
    @Published var isOnline   = true
    /// Bumped whenever every view should re-fetch from the Mac (foreground, 30 s poll,
    /// reconnect, voice command). Views subscribe with `.onReceive(api.$refreshTick)`.
    @Published var refreshTick = 0
    func requestRefresh() { refreshTick &+= 1 }

    /// While things are changing (a voice command just ran, an edit was saved) the
    /// background poll drops to 1 s; it returns to 30 s once this window passes.
    private var isFlushingVoice = false
    /// Same reason as `isFlushingVoice`, for the write queue. Four things ask
    /// for a flush — the reconnect hook in `request()`, the `.active` scene
    /// change, the poll loop, and a manual retry — and two overlapping passes
    /// both read `allPending().first`, so both replay the same queued create.
    private var isFlushingPending = false
    @Published var burstUntil = Date.distantPast
    func burstRefresh(seconds: TimeInterval = 45) { burstUntil = max(burstUntil, Date().addingTimeInterval(seconds)) }
    var pollInterval: TimeInterval { Date() < burstUntil ? 1 : 30 }

    // MARK: - The offline circuit breaker
    //
    // Every read on this client already falls back to the cache — but it fell
    // back only AFTER the request had sat out its full 8 s timeout. With the
    // Mac away that is what the app felt like: eight seconds of blank month
    // before a cache it had on disk the whole time, another eight for the
    // holidays, and a cold start that ran several of those one after another
    // before the first pixel of real content.
    //
    // So once a request fails to reach the Mac, the next ones do not try. They
    // throw `.offline` at once — which is the same error the timeout produced,
    // so every existing cache fallback and offline-queue path is unchanged,
    // it just happens instantly. Only the two cheap probes below still go to
    // the network, because something has to notice the Mac coming back.
    //
    // The wait between probes grows 2 → 4 → 8 → 16 → 20 s so a Mac that is off
    // for an hour is not asked 1,800 times, and any success clears it.
    private var offlineUntil = Date.distantPast
    private var offlineBackoff: TimeInterval = 0
    private static let probePaths: Set<String> = ["/health", "/changes"]
    private static let maxBackoff: TimeInterval = 20

    /// Whether the Mac was reachable when this app last ran.
    ///
    /// All of the above only helps AFTER the first failure. `isOnline` started
    /// `true` on every launch, so a cold start with the Mac away paid the full
    /// eight-second timeout before the breaker armed — and every view sat
    /// behind it, waiting on a cache that was on disk the whole time. That is
    /// the "preload is really slow when disconnected" you feel.
    ///
    /// Remembering it makes the first launch behave like the second: reads
    /// answer from cache immediately, and a probe on a three-second leash puts
    /// the app back online the moment the Mac returns. Being wrong costs one
    /// probe; being right saves eight seconds of blank screen.
    private static let reachableKey = "lastKnownReachable"

    /// True while we have recently failed to reach the Mac and are waiting
    /// before trying again. Callers that build their own URLRequest (the voice
    /// uploads) check this so they can queue immediately instead of holding a
    /// recording hostage to a 120 s timeout.
    var isBackingOff: Bool { Date() < offlineUntil }

    // The five below are `internal`, not `private`, for exactly one reason:
    // Jude's calls live in `Jude/JudeClient.swift` rather than in this file.
    // Swift's `private` is file-scoped, so an extension in another file cannot
    // see them — and the alternative was leaving Jude's protocol spread across
    // this file and that folder, which is the drift the move was made to end.
    // Nothing outside this client should call them.
    func noteReachable() {
        offlineUntil = .distantPast
        offlineBackoff = 0
        UserDefaults.standard.set(true, forKey: Self.reachableKey)
    }

    func noteUnreachable() {
        offlineBackoff = min(max(2, offlineBackoff * 2), Self.maxBackoff)
        offlineUntil = Date().addingTimeInterval(offlineBackoff)
        UserDefaults.standard.set(false, forKey: Self.reachableKey)
    }

    /// Start where we left off. Called once, from `init`.
    ///
    /// The backoff is armed only BRIEFLY (one second): long enough that the
    /// launch burst — bootstrap, month, tasks, features — answers from cache
    /// without touching the network, short enough that the Mac being back is
    /// noticed almost at once. The probes ignore it anyway.
    private func restoreReachability() {
        let known = UserDefaults.standard.object(forKey: Self.reachableKey) as? Bool
        guard known == false else { return }     // unknown or reachable: assume online
        isOnline = false
        offlineBackoff = 1
        offlineUntil = Date().addingTimeInterval(1)
    }

    let settings: AppSettings

    init(settings: AppSettings) {
        self.settings = settings
        restoreReachability()
    }

    // MARK: - Base

    /// Normalised server base URL. Accepts what people actually type:
    /// "100.x.x.x", "100.x.x.x:8080", "http://100.x.x.x:8080/", or a Tailscale
    /// MagicDNS name like "my-mac" — and always yields http://host:port.
    var base: String {
        var url = settings.serverURL
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .trimmingCharacters(in: .init(charactersIn: "/"))
        guard !url.isEmpty else { return "" }
        if url.hasPrefix("https://") { url = "http://" + url.dropFirst(8) }
        if !url.hasPrefix("http://") { url = "http://" + url }
        // add the default port when none was given (host may be an IP or a name)
        let hostPart = url.dropFirst(7)
        if !hostPart.contains(":") { url += ":8080" }
        return url
    }

    func request(_ path: String, method: String = "GET",
                 body: [String: Any]? = nil) async throws -> Data {
        let isPlaceholder = base.contains("x.x.x") || base.contains("100.x")
        guard !base.isEmpty, !isPlaceholder, let url = URL(string: base + path) else {
            throw APIError.badURL
        }
        // Everything before the "?" — a probe stays a probe with query args on it.
        let isProbe = Self.probePaths.contains(path.prefix(while: { $0 != "?" }).description)
        if isBackingOff && !isProbe {
            throw APIError.offline("not retrying yet — the Mac was unreachable a moment ago")
        }
        // A believed-offline probe gets a short leash: its whole job is to
        // find out quickly, and eight seconds of that per poll is the lag.
        //
        // The online figure is 8s for a Mac that is THINKING — a voice command
        // being parsed, an index being read. Discovering whether a Mac is
        // there at all is a different question with a different answer: on the
        // tailnet a reachable one replies in about 100ms, so a request that
        // has not been answered in 5s is not slow, it is absent.
        var req = URLRequest(url: url, timeoutInterval: isOnline ? 5 : 3)
        req.httpMethod = method
        if !settings.apiKey.isEmpty {
            req.setValue(settings.apiKey, forHTTPHeaderField: "X-API-Key")
        }
        if let body {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try JSONSerialization.data(withJSONObject: body)
        }
        do {
            let (data, resp) = try await URLSession.shared.data(for: req)
            guard let http = resp as? HTTPURLResponse,
                  (200...299).contains(http.statusCode) else {
                let msg = String(data: data, encoding: .utf8) ?? "Unknown error"
                throw APIError.serverError(msg)
            }
            noteReachable()
            // Only assign when it actually changes: these are @Published, so a
            // redundant write still republishes and re-renders every subscriber.
            // With /changes polled every 2 s, blind assignment meant a full
            // re-render twice a second-and-a-half for as long as the Mac was away.
            if !isOnline {
                isOnline = true
                requestRefresh()
                // The Mac just came back. Flush anything parked while it was away
                // now, rather than on the next 30 s tick — a command you spoke
                // minutes ago should run the moment it can, not up to a minute later.
                Task { [weak self] in
                    _ = await self?.syncPending()
                    await self?.syncPendingVoice()
                }
            }
            return data
        } catch let err as APIError {
            throw err
        } catch {
            // URLError / network unreachable — keep the real reason for Settings › Test Connection
            noteUnreachable()
            if isOnline { isOnline = false }
            let reason = "\(url.absoluteString): \(error.localizedDescription)"
            if lastError != reason { lastError = reason }
            throw APIError.offline(error.localizedDescription)
        }
    }

    private func decode<T: Decodable>(_ type: T.Type, from data: Data) throws -> T {
        try JSONDecoder().decode(type, from: data)
    }

    // MARK: - Writes

    /// Do a write now, or keep it until the Mac is back. **Every write on this
    /// client goes through here.**
    ///
    /// It used to be decided per method, and most of them decided wrong.
    /// `deleteCourse` was a bare request, `CourseworkView` called it as `try?
    /// await api.deleteCourse(id)`, and no `/courses` or `/assignments` path
    /// had ever been enqueued — while `CourseStore`'s own header comment
    /// promised they were. So a course deleted with the Mac away vanished
    /// here, told nobody, and came back on the next sync; an assignment added
    /// with the Mac away was gone by it. Timer, Counters, Categories, Vocab
    /// and Teach all had the same hole, each written slightly differently.
    /// One helper is the fix: a tab cannot forget what it never decides.
    ///
    /// `.offline` / `.badURL` mean the Mac was never ASKED, so the write is
    /// queued and `nil` comes back — "not yet", never "no". Anything else is
    /// the Mac ANSWERING and refusing, and that throws: a refusal replayed is
    /// only refused again.
    ///
    /// `tests/unit/test_ios_offline.py` fails the build for a mutating request
    /// that goes around this without a stated reason.
    @discardableResult
    func mutate(_ path: String, method: String, body: [String: Any]? = nil) async throws -> Data? {
        do {
            return try await request(path, method: method, body: body)
        } catch APIError.offline, APIError.badURL {
            LocalStore.shared.enqueue(method: method, path: path, body: body)
            return nil
        }
    }

    /// The same, for a write whose caller has nowhere to show an error — a row
    /// action, a toggle, a tap on a counter. Offline still goes to the queue;
    /// a refusal is SAID rather than swallowed, because a write that nothing
    /// will replay and nobody is told about is the silence this file was full
    /// of.
    func mutateOrTell(_ path: String, method: String, body: [String: Any]? = nil) async {
        do { _ = try await mutate(path, method: method, body: body) }
        catch { announceRefusal(error, doing: "\(method) \(path)") }
    }

    /// Say that a write was refused. The Mac answered NO, so nothing will
    /// replay it — if it is not said here it is not said anywhere.
    ///
    /// Both channels, because a refused write is usually a background one: the
    /// banner for a user who is looking at the app, a notification for one who
    /// is not — the same pair `syncPending` uses for a 409.
    func announceRefusal(_ error: Error, doing what: String) {
        let sentence = (error as? APIError)?.serverSentence ?? error.localizedDescription
        lastError = "\(what): \(sentence)"
        lastRefusal = "Couldn't \(what) — \(sentence)"
        Self.notify(title: "Your Mac didn't accept that change", body: sentence)
    }

    /// The moment a write HAPPENED, in this phone's clock.
    ///
    /// A queued write is replayed at an unpredictable later time, so anything
    /// whose meaning depends on "now" must carry the instant it meant — see
    /// `startTimer`. The offset is written out rather than normalised to "Z"
    /// because the Mac stores these strings as it receives them and reads them
    /// back with `datetime.fromisoformat`.
    static func stamp(_ date: Date = Date()) -> String { stampFormatter.string(from: date) }

    private static let stampFormatter: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.timeZone = TimeZone.current
        return f
    }()

    // MARK: - Pending sync

    /// Replay queued offline writes. Call when the app becomes active.
    /// Returns true if anything was synced (caller should refresh UI).
    @discardableResult
    func syncPending() async -> Bool {
        guard !isFlushingPending else { return false }
        guard !LocalStore.shared.allPending().isEmpty else { return false }
        isFlushingPending = true
        defer { isFlushingPending = false }
        var synced = 0
        // Re-read the queue each pass: replaying a create rewrites the paths of
        // later entries that still point at its temporary offline id.
        while let change = LocalStore.shared.allPending().first {
            do {
                var body: [String: Any]? = nil
                if let data = change.bodyJSON {
                    body = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
                }
                let data = try await request(change.path, method: change.method, body: body)

                // A create comes back with the row the Mac actually stored. Point
                // anything still queued against the placeholder id at the real one,
                // otherwise "add a task offline, tick it off, reconnect" loses the tick.
                if change.method == "POST", let temp = temporaryID(in: change),
                   let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                   let realID = obj["id"] as? Int {
                    LocalStore.shared.remapTemporaryID(temp, to: realID)
                }

                LocalStore.shared.removePending(change.id)
                synced += 1
            } catch APIError.offline {
                break        // the Mac is away again — keep the rest for later
            } catch APIError.serverError(let detail) where detail.contains("\"code\": 409")
                                                        || detail.contains("\"code\":409") {
                // The same event was changed on the Mac while we were away. The
                // Mac's version stands — say so rather than losing an edit in
                // silence, on whichever side it happened.
                LocalStore.shared.removePending(change.id)
                Self.notify(title: "One edit didn't apply",
                            body: "That event had already been changed on your Mac, so its version was kept.")
                requestRefresh()
            } catch {
                // The Mac answered and refused it (404 for a row that no longer
                // exists, 400 for something malformed). Retrying cannot help, and
                // leaving it at the head of the queue blocked every later change
                // forever. Drop it and carry on.
                LocalStore.shared.removePending(change.id)
            }
        }
        return synced > 0
    }

    /// Replay voice commands recorded while the Mac was away.
    ///
    /// The recording is uploaded exactly as it would have been live, and the
    /// result is reported with a local notification — the command may well run
    /// while the user is in another app, and silently changing their calendar
    /// without telling them would be worse than not running it at all.
    @discardableResult
    func syncPendingVoice() async -> Int {
        // Several things can ask for a flush at once (reconnect, foreground, the
        // poll loop, opening the queue screen); replaying the same audio twice
        // would create the event twice.
        guard !isFlushingVoice else { return 0 }
        // Recover anything stranded in `.running` by a killed process or an
        // upload that never returned. Without this the row is invisible to the
        // filter below and can never be retried — one sat at "Running now…" for
        // five and a half hours before this was found (2026-09-10). Time-gated
        // (900 s default) rather than "any `.running` row found here is stale":
        // this runs before EVERY flush, not just on relaunch, and a row that is
        // still genuinely in flight must not be reclaimed out from under itself.
        _ = LocalStore.shared.reviveStalledVoice()
        // A row being edited is SKIPPED, not sent. Reconnect, foregrounding, the
        // 30 s poll and opening the queue screen can all trigger a flush, and any
        // of them could otherwise fire mid-sentence and send the half-corrected
        // version out from under the user (Gil, 2026-09-10).
        let queued = LocalStore.shared.pendingVoice.filter {
            ($0.status == .queued || $0.status == .failed) && !$0.heldForEdit
        }
        guard !queued.isEmpty else { return 0 }
        isFlushingVoice = true
        defer { isFlushingVoice = false }
        var ran = 0
        for cmd in queued {
            // EDITED → send the TEXT; UNTOUCHED → send the AUDIO.
            //
            // The phone's on-device draft is worse than Whisper-plus-vocabulary
            // on the Mac, so an untouched command must still go as audio — the
            // draft was only ever for the user to read. But a correction the
            // user typed beats any re-transcription, so once they have edited
            // it the text is the better input and the audio is stale.
            if let text = cmd.outgoingText {
                LocalStore.shared.updateVoice(cmd.id, status: .running)
                do {
                    let response = try await sendText(text, editedFrom: cmd.draft)
                    // See the audio path below for why `parse == "error"` +
                    // `pendingId` is a handoff to the Mac's own retry queue,
                    // not a completion.
                    if response.parse == "error", response.pendingId != nil {
                        LocalStore.shared.removeVoice(cmd.id)
                        Self.notify(title: "Your Mac is running this on its own", body: response.message)
                        continue
                    }
                    LocalStore.shared.updateVoice(cmd.id, status: .done,
                                                  result: response.message.isEmpty ? "Done" : response.message)
                    Self.notify(title: "Ran your queued command", body: response.message)
                    ran += 1
                    burstRefresh()
                    requestRefresh()
                } catch APIError.offline {
                    LocalStore.shared.updateVoice(cmd.id, status: .queued)
                    break
                } catch {
                    LocalStore.shared.updateVoice(cmd.id, status: .failed,
                                                  result: error.localizedDescription)
                }
                continue
            }
            guard let audio = LocalStore.shared.voiceAudio(cmd) else {
                LocalStore.shared.removeVoice(cmd.id)
                continue
            }
            LocalStore.shared.updateVoice(cmd.id, status: .running)
            do {
                let response = try await sendAudio(audio)
                // The Mac answered, but `parse == "error"` with a `pendingId`
                // means it never actually ran the command — the model was
                // offline/slow, so the Mac queued it in ITS OWN retry store
                // (assistant/engine's `add_pending`, `start_pending_retry_loop`)
                // and will run it on its own. Marking this `.done` would be a
                // lie, and leaving it `.queued` would replay the same audio
                // again later — handing the Mac a second copy of the same
                // command, which its own loop could then execute twice once
                // the model is back. The Mac owns it now; drop our copy.
                if response.parse == "error", response.pendingId != nil {
                    LocalStore.shared.removeVoice(cmd.id)
                    Self.notify(title: "Your Mac is running this on its own", body: response.message)
                    continue
                }
                LocalStore.shared.updateVoice(cmd.id, status: .done,
                                              result: response.message.isEmpty ? "Done" : response.message)
                Self.notify(title: "Ran your queued command", body: response.message)
                ran += 1
                burstRefresh()
                requestRefresh()
            } catch APIError.offline {
                LocalStore.shared.updateVoice(cmd.id, status: .queued)   // still away — try again later
                break
            } catch {
                LocalStore.shared.updateVoice(cmd.id, status: .failed,
                                              result: error.localizedDescription)
                Self.notify(title: "A queued command didn't run",
                            body: error.localizedDescription)
            }
        }
        return ran
    }

    /// Local notification — the same pattern the workout rest timer uses.
    nonisolated static func notify(title: String, body: String) {
        let center = UNUserNotificationCenter.current()
        center.getNotificationSettings { settings in
            guard settings.authorizationStatus != .denied else { return }
            if settings.authorizationStatus == .notDetermined {
                center.requestAuthorization(options: [.alert, .sound]) { _, _ in }
            }
            let content = UNMutableNotificationContent()
            content.title = title
            content.body = body.isEmpty ? "Tap to see what changed." : body
            content.sound = .default
            center.add(UNNotificationRequest(identifier: UUID().uuidString,
                                             content: content, trigger: nil))
        }
    }

    /// The temporary offline id a create was made under, if it had one.
    /// LocalStore hands out negative ids for rows created while disconnected.
    private func temporaryID(in change: PendingChange) -> Int? {
        guard let data = change.bodyJSON,
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let temp = obj["_temp_id"] as? Int, temp < 0
        else { return nil }
        return temp
    }

    // MARK: - Health

    func health() async throws -> HealthResponse {
        let data = try await request("/health")
        return try decode(HealthResponse.self, from: data)
    }

    // MARK: - Teaching the labeller

    /// A batch of items worth labelling, hardest-first. The server does the
    /// ranking — see `/labels/next` — because "which of these would teach the
    /// most" is a question about the model, and the model is on the Mac.
    func labelQueue(kind: String = "event", n: Int = 20) async throws -> LabelBatch {
        let data = try await request("/labels/next?kind=\(kind)&n=\(n)")
        return try decode(LabelBatch.self, from: data)
    }

    /// Record one answer. Returns whether enough NEW answers have accumulated
    /// to be worth re-learning.
    ///
    /// Queued when the Mac is away, and of everything here this is the one
    /// least replaceable: the user's own corrections are the only non-circular
    /// label source the project has. Answered on the train, they now arrive.
    /// A queued answer reports "not due" — nothing can be retrained until it
    /// has actually landed.
    @discardableResult
    func recordLabel(kind: String, text: String, label: String,
                     current: String?) async throws -> Bool {
        var body: [String: Any] = ["kind": kind, "text": text, "label": label]
        if let current { body["current"] = current }
        guard let data = try await mutate("/labels", method: "POST", body: body) else { return false }
        let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        return (obj?["retrain_due"] as? Bool) ?? false
    }

    /// Refit now. The promotion gate still applies on the Mac: a model that is
    /// not better than the installed one does not ship, however many labels
    /// arrived — so this can legitimately report "kept the old one".
    func retrainLabels(kind: String = "event") async throws -> String {
        let data = try await request("/labels/retrain", method: "POST",
                                     body: ["kind": kind])
        let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        let result = obj?["result"] as? [String: Any]
        if result == nil { return "Nothing new to learn from yet." }
        if (result?["promoted"] as? Bool) == true {
            return "Learned. The new version is better, so it's the one in use."
        }
        return "Learned, but the old version was better — keeping it."
    }

    // MARK: - Heartbeat

    /// Fire-and-forget "this phone is alive" ping. The Mac records the last
    /// beat per source so `assistant doctor` can tell a connected surface
    /// from a silent one. Failures are swallowed — being away from the Mac
    /// is a phone's normal state, not an error worth surfacing.
    func heartbeat() async {
        _ = try? await request("/heartbeat", method: "POST",
                               body: ["source": "ios",
                                      "device": UIDevice.current.name])
    }

    // MARK: - Events

    func eventsForDay(_ date: Date) async throws -> [CalendarEvent] {
        let d = ISO8601DateFormatter.yyyyMMdd.string(from: date)
        do {
            let data   = try await request("/events?date=\(d)")
            let events = try decode([CalendarEvent].self, from: data)
            LocalStore.shared.cacheEvents(events)
            return events
        } catch APIError.offline, APIError.badURL {
            return LocalStore.shared.eventsForDate(d)
        }
    }

    func eventsForMonth(year: Int, month: Int) async throws -> [CalendarEvent] {
        do {
            let data   = try await request("/events?year=\(year)&month=\(month)")
            let events = try decode([CalendarEvent].self, from: data)
            LocalStore.shared.cacheEvents(events)
            return events
        } catch APIError.offline, APIError.badURL {
            return LocalStore.shared.eventsForMonth(year, month)
        }
    }

    func eventsForWeek(start: Date) async throws -> [CalendarEvent] {
        let d = ISO8601DateFormatter.yyyyMMdd.string(from: start)
        do {
            let data   = try await request("/events?week_start=\(d)")
            let events = try decode([CalendarEvent].self, from: data)
            LocalStore.shared.cacheEvents(events)
            return events
        } catch APIError.offline, APIError.badURL {
            return LocalStore.shared.eventsForWeek(startStr: d)
        }
    }

    /// Raw bytes of GET /events/<id>.ics — the Mac renders one event as an
    /// RFC 5545 file served as a text/calendar attachment. Only rows the Mac
    /// has can be fetched, so callers must not ask for an offline temp id
    /// (negative) — those haven't synced yet.
    func fetchICS(eventId: Int) async throws -> Data {
        try await request("/events/\(eventId).ics")
    }

    // MARK: - Holidays

    /// Jewish/Israeli holidays for [start, end]. Computed server-side (Mac)
    /// so the holiday list stays identical across devices — and cached here,
    /// so it stays on screen when the Mac is away. It used to be the one part
    /// of the calendar with no cache: going offline emptied the Hebrew
    /// calendar out of every month, while the Hebrew dates next to it (which
    /// iOS computes locally) carried on.
    func holidays(start: Date, end: Date, israel: Bool = true) async throws -> [Holiday] {
        let s = ISO8601DateFormatter.yyyyMMdd.string(from: start)
        let e = ISO8601DateFormatter.yyyyMMdd.string(from: end)
        do {
            let data = try await request("/holidays?start=\(s)&end=\(e)&israel=\(israel ? 1 : 0)")
            let items = try decode([Holiday].self, from: data)
            LocalStore.shared.cacheHolidays(items, from: s, to: e)
            return items
        } catch APIError.offline, APIError.badURL {
            return LocalStore.shared.holidaysBetween(s, e)
        }
    }

    // MARK: - Bootstrap (one round trip for a cold start)

    /// Everything a cold start needs, in one request — see
    /// `DOCUMENTATION/SYNC_PROTOCOL.md`.
    ///
    /// Opening the app used to be eight independent GETs, and with the Mac
    /// away the phone paid a timeout on each of them before falling back to
    /// caches it already had. One request means one timeout; the circuit
    /// breaker above means that after the first failure there is not even
    /// one. Every list it carries lands in the same cache the individual
    /// endpoints write, so nothing downstream knows the difference.
    ///
    /// Returns the Mac's change token, so the caller can seed its poll and
    /// skip the refresh it would otherwise do straight afterwards. Nil when
    /// the Mac is unreachable — which is not an error, it is Tuesday.
    @discardableResult
    func bootstrap(year: Int, month: Int, israel: Bool = true) async -> String? {
        guard let data = try? await request(
                "/sync/bootstrap?year=\(year)&month=\(month)&israel=\(israel ? 1 : 0)"),
              let snap = try? JSONDecoder().decode(BootstrapSnapshot.self, from: data)
        else { return nil }

        let store = LocalStore.shared
        store.cacheEvents(snap.events)
        store.cacheTodos(snap.todos)
        store.cacheTags(snap.tags)
        store.cacheHolidays(snap.holidays, from: snap.window.start, to: snap.window.end)
        if let rules = snap.tagRules { TagClassifier.shared.update(rules) }
        requestRefresh()
        return snap.token
    }

    /// The tag classifier's own table, when only it is wanted (the bootstrap
    /// carries it too). Failure leaves the phone on the copy it already has,
    /// which is the whole point of caching it.
    func refreshTagRules() async {
        guard let data = try? await request("/tags/rules"),
              let rules = try? JSONDecoder().decode(TagRules.self, from: data) else { return }
        TagClassifier.shared.update(rules)
    }

    /// Undo a destructive background patch by re-creating what the host removed.
    /// Each item's `body` is exactly what its create endpoint accepts, so this
    /// is a plain re-POST — no special revert endpoint, no db bypass.
    func revert(_ items: [RevertItem]) async {
        burstRefresh(seconds: 10)
        for item in items {
            let path = item.kind == "event" ? "/events" : "/todos"
            let body = item.body.mapValues { $0.value }
            _ = try? await request(path, method: "POST", body: body)
        }
        requestRefresh()
    }

    func createEvent(_ fields: [String: Any]) async throws -> Int {
        burstRefresh(seconds: 10)
        do {
            let data = try await request("/events", method: "POST", body: fields)
            let obj  = try JSONSerialization.jsonObject(with: data) as? [String: Any]
            return obj?["id"] as? Int ?? 0
        } catch APIError.offline, APIError.badURL {
            let local = LocalStore.shared.insertEvent(fields)
            // Carry the placeholder id so syncPending can repoint anything queued
            // against it once the Mac assigns the real one. The server ignores it.
            LocalStore.shared.enqueue(method: "POST", path: "/events",
                                      body: fields.merging(["_temp_id": local.id]) { a, _ in a })
            return local.id
        }
    }

    func updateEvent(id: Int, fields: [String: Any]) async throws {
        burstRefresh(seconds: 10)
        do {
            _ = try await request("/events/\(id)", method: "PATCH", body: fields)
        } catch APIError.offline, APIError.badURL {
            LocalStore.shared.patchEvent(id, fields: fields)   // keep local cache current
            // Record which version this edit was made from. If the same event is
            // changed on the Mac before we reconnect, the Mac refuses the replay
            // (409) instead of quietly discarding whichever edit came second.
            var queued = fields
            if let base = LocalStore.shared.event(id)?.updatedAt {
                queued["base_updated_at"] = base
            }
            LocalStore.shared.enqueue(method: "PATCH", path: "/events/\(id)", body: queued)
        }
    }

    func deleteEvent(id: Int) async throws {
        burstRefresh(seconds: 10)
        LocalStore.shared.removeEvent(id)   // optimistic local remove
        do {
            _ = try await request("/events/\(id)", method: "DELETE")
        } catch APIError.offline, APIError.badURL {
            LocalStore.shared.enqueue(method: "DELETE", path: "/events/\(id)")
        }
    }

    // MARK: - Todos

    func todos(list: String = "all", includeCompleted: Bool = false) async throws -> [Todo] {
        do {
            let data  = try await request("/todos?list=\(list)&include_completed=\(includeCompleted)")
            let items = try decode([Todo].self, from: data)
            LocalStore.shared.cacheTodos(items)
            return items
        } catch APIError.offline, APIError.badURL {
            let l = list == "all" ? nil : list
            return LocalStore.shared.allTodos(list: l, includeCompleted: includeCompleted)
        }
    }

    /// Tags are always sent explicitly (possibly empty) so the server's own
    /// "tag mode" (config.todo.auto_tag) never overrides what the phone chose.
    func createTodo(title: String, list: String = "today", tags: [String] = []) async throws -> Int {
        // One idempotency token per task the user asked for, minted before the
        // first attempt and carried by every later one. The Mac returns the row
        // it already stored for a token it has seen, so a create that arrived
        // but whose reply was lost — and a queued create replayed twice — can no
        // longer land as a second copy of the task.
        let body: [String: Any] = ["title": title, "list_name": list, "tags": tags,
                                   "client_token": UUID().uuidString]
        do {
            let data = try await request("/todos", method: "POST", body: body)
            let obj  = try JSONSerialization.jsonObject(with: data) as? [String: Any]
            return obj?["id"] as? Int ?? 0
        } catch APIError.offline, APIError.badURL {
            // The Mac classifies a task it is asked to create, and never
            // re-tags one it did not — so a task typed while it was away used
            // to show untagged, drop out of whatever tag view you were looking
            // at, and stay that way until the queued create replayed.
            //
            // `TagClassifier` is the Mac's own classifier running here, on the
            // table the Mac serves, so it can be shown with its tag straight
            // away. The QUEUED BODY is deliberately left alone: it still says
            // what the user said (possibly nothing), so on replay the Mac
            // classifies it itself and its answer is the one that lands. This
            // is a preview, not a second source of truth.
            let shown = tags.isEmpty ? TagClassifier.shared.tags(for: title) : tags
            let local = LocalStore.shared.insertTodo(title: title, list: list, tags: shown)
            LocalStore.shared.enqueue(method: "POST", path: "/todos",
                                      body: body.merging(["_temp_id": local.id]) { a, _ in a })
            return local.id
        }
    }

    // MARK: - Tags

    func tags() async throws -> [TodoTag] {
        do {
            let data  = try await request("/tags")
            let items = try decode([TodoTag].self, from: data)
            LocalStore.shared.cacheTags(items)
            return items
        } catch APIError.offline, APIError.badURL {
            return LocalStore.shared.allTags()
        }
    }

    func createTag(name: String) async throws {
        LocalStore.shared.insertTag(TodoTag(name: name))    // optimistic
        do {
            _ = try await request("/tags", method: "POST", body: ["name": name])
        } catch APIError.offline, APIError.badURL {
            LocalStore.shared.enqueue(method: "POST", path: "/tags", body: ["name": name])
        }
    }

    func deleteTag(name: String) async throws {
        LocalStore.shared.removeTag(name)                    // optimistic
        let encoded = name.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? name
        do {
            _ = try await request("/tags/\(encoded)", method: "DELETE")
        } catch APIError.offline, APIError.badURL {
            LocalStore.shared.enqueue(method: "DELETE", path: "/tags/\(encoded)")
        }
    }

    func toggleTodo(id: Int) async throws -> Bool {
        LocalStore.shared.toggleTodo(id)    // optimistic
        do {
            let data = try await request("/todos/\(id)/toggle", method: "PATCH")
            let obj  = try JSONSerialization.jsonObject(with: data) as? [String: Any]
            return (obj?["completed"] as? Int ?? 0) != 0
        } catch APIError.offline, APIError.badURL {
            LocalStore.shared.enqueue(method: "PATCH", path: "/todos/\(id)/toggle")
            return LocalStore.shared.allTodos(list: nil, includeCompleted: true)
                .first { $0.id == id }?.completed != 0
        }
    }

    func deleteTodo(id: Int) async throws {
        LocalStore.shared.removeTodo(id)    // optimistic
        do {
            _ = try await request("/todos/\(id)", method: "DELETE")
        } catch APIError.offline, APIError.badURL {
            LocalStore.shared.enqueue(method: "DELETE", path: "/todos/\(id)")
        }
    }

    /// The order is the user's own arrangement, so it is queued like any other
    /// edit — a list dragged into shape with the Mac away used to snap back on
    /// the next refresh.
    func reorderTodos(list: String, ids: [Int]) async throws {
        try await mutate("/todos/reorder", method: "POST",
                         body: ["list": list, "ids": ids])
    }

    func updateTodo(id: Int, title: String? = nil, list: String? = nil,
                    priority: String? = nil, dueDate: String? = nil,
                    tags: [String]? = nil, quantity: Int? = nil) async throws {
        var fields: [String: Any] = [:]
        if let title    { fields["title"]    = title }
        if let list     { fields["list_name"] = list }
        if let priority { fields["priority"] = priority }
        if let dueDate  { fields["due_date"] = dueDate }
        if let tags     { fields["tags"]     = tags }
        if let quantity { fields["quantity"] = max(1, quantity) }
        guard !fields.isEmpty else { return }
        do {
            _ = try await request("/todos/\(id)", method: "PATCH", body: fields)
        } catch APIError.offline, APIError.badURL {
            LocalStore.shared.patchTodo(id, fields: fields)   // keep local cache current
            var queued = fields
            if let base = LocalStore.shared.todo(id)?.updatedAt {
                queued["base_updated_at"] = base
            }
            LocalStore.shared.enqueue(method: "PATCH", path: "/todos/\(id)", body: queued)
        }
    }

    func clearCompletedTodos(list: String? = nil) async throws {
        let path = list != nil ? "/todos/completed?list=\(list!)" : "/todos/completed"
        try await mutate(path, method: "DELETE")
    }

    // MARK: - Workout
    //
    // Workout IDs are client-generated UUIDs end-to-end (both locally and on
    // the server), so — unlike events/todos — there's no temp-ID/remap dance:
    // create locally (optimistic, in WorkoutStore) -> attempt to push to the
    // server immediately -> on failure/offline, fall back to LocalStore's
    // generic pending-write queue (same one events/todos use), replayed
    // generically by syncPending() above.

    private func workoutBody<T: Encodable>(_ value: T) -> [String: Any]? {
        guard let data = try? JSONEncoder.workout.encode(value),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        return obj
    }

    private func bodyId(_ p: PendingChange) -> UUID? {
        guard let data = p.bodyJSON,
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let idStr = obj["id"] as? String else { return nil }
        return UUID(uuidString: idStr)
    }

    /// True if a POST to `path` for `id` is still sitting in the offline
    /// queue — i.e. the record doesn't exist server-side yet, so a PATCH/DELETE
    /// against it right now would 404 even though we're online.
    private func hasPendingCreate(path: String, id: UUID) -> Bool {
        LocalStore.shared.allPending().contains { $0.method == "POST" && $0.path == path && bodyId($0) == id }
    }

    // MARK: Workout — exercises

    @discardableResult
    func workoutExercises() async throws -> [Exercise] {
        do {
            let data = try await request("/workout/exercises")
            let items = try JSONDecoder.workout.decode([Exercise].self, from: data)
            WorkoutStore.shared.cacheExercises(items)
            return items
        } catch APIError.offline, APIError.badURL {
            return WorkoutStore.shared.exercises
        }
    }

    /// Called after WorkoutStore has already created the exercise locally
    /// (find-or-create is always local-first — exercises are never edited or
    /// deleted, only created, so there's no update/delete race to guard here).
    func syncNewExercise(_ exercise: Exercise) async {
        guard let body = workoutBody(exercise) else { return }
        do {
            _ = try await request("/workout/exercises", method: "POST", body: body)
        } catch APIError.offline, APIError.badURL {
            LocalStore.shared.enqueue(method: "POST", path: "/workout/exercises", body: body)
        } catch {
            // Other server error (e.g. validation) — don't enqueue a write
            // that would just fail identically on replay.
        }
    }

    // MARK: Workout — templates

    @discardableResult
    func workoutTemplates(includeDrafts: Bool = false) async throws -> [WorkoutTemplate] {
        do {
            let path = "/workout/templates" + (includeDrafts ? "?include_drafts=true" : "")
            let data = try await request(path)
            let items = try JSONDecoder.workout.decode([WorkoutTemplate].self, from: data)
            WorkoutStore.shared.cacheTemplates(items, includeDrafts: includeDrafts)
            return items
        } catch APIError.offline, APIError.badURL {
            return WorkoutStore.shared.templates
        }
    }

    func syncTemplate(_ template: WorkoutTemplate, isNew: Bool) async {
        guard let body = workoutBody(template) else { return }
        let path = isNew ? "/workout/templates" : "/workout/templates/\(template.id.uuidString)"
        let method = isNew ? "POST" : "PATCH"
        if !isNew && hasPendingCreate(path: "/workout/templates", id: template.id) {
            // Create hasn't synced yet — queue behind it so replay order is POST-then-PATCH.
            LocalStore.shared.enqueue(method: method, path: path, body: body)
            return
        }
        do {
            _ = try await request(path, method: method, body: body)
        } catch APIError.offline, APIError.badURL {
            LocalStore.shared.enqueue(method: method, path: path, body: body)
        } catch { }
    }

    func deleteWorkoutTemplate(_ id: UUID) async {
        let path = "/workout/templates/\(id.uuidString)"
        // If it never made it to the server (create still queued), just drop
        // the queued create — nothing to delete remotely.
        if let pc = LocalStore.shared.allPending().first(where: {
            $0.method == "POST" && $0.path == "/workout/templates" && bodyId($0) == id
        }) {
            LocalStore.shared.removePending(pc.id)
            return
        }
        do {
            _ = try await request(path, method: "DELETE")
        } catch APIError.offline, APIError.badURL {
            LocalStore.shared.enqueue(method: "DELETE", path: path)
        } catch { }
    }

    /// Finalizes an AI-drafted template. The draft already exists server-side
    /// (created by the generate_workout_routine voice action), so there's no
    /// pending-create race to guard against here.
    func approveWorkoutTemplate(_ id: UUID) async {
        let path = "/workout/templates/\(id.uuidString)/approve"
        do {
            _ = try await request(path, method: "PATCH")
        } catch APIError.offline, APIError.badURL {
            LocalStore.shared.enqueue(method: "PATCH", path: path)
        } catch { }
    }

    // MARK: Workout — sessions

    @discardableResult
    func workoutSessions(limit: Int? = nil, startDate: String? = nil, endDate: String? = nil) async throws -> [WorkoutSession] {
        var q: [String] = []
        if let limit { q.append("limit=\(limit)") }
        if let startDate { q.append("start_date=\(startDate)") }
        if let endDate { q.append("end_date=\(endDate)") }
        let qs = q.isEmpty ? "" : "?" + q.joined(separator: "&")
        do {
            let data = try await request("/workout/sessions" + qs)
            let items = try JSONDecoder.workout.decode([WorkoutSession].self, from: data)
            WorkoutStore.shared.cacheSessions(items)
            return items
        } catch APIError.offline, APIError.badURL {
            return WorkoutStore.shared.sessions
        }
    }

    func syncSession(_ session: WorkoutSession, isNew: Bool) async {
        guard let body = workoutBody(session) else { return }
        let path = isNew ? "/workout/sessions" : "/workout/sessions/\(session.id.uuidString)"
        let method = isNew ? "POST" : "PATCH"
        if !isNew && hasPendingCreate(path: "/workout/sessions", id: session.id) {
            LocalStore.shared.enqueue(method: method, path: path, body: body)
            return
        }
        do {
            _ = try await request(path, method: method, body: body)
        } catch APIError.offline, APIError.badURL {
            LocalStore.shared.enqueue(method: method, path: path, body: body)
        } catch { }
    }

    func deleteWorkoutSession(_ id: UUID) async {
        let path = "/workout/sessions/\(id.uuidString)"
        if let pc = LocalStore.shared.allPending().first(where: {
            $0.method == "POST" && $0.path == "/workout/sessions" && bodyId($0) == id
        }) {
            LocalStore.shared.removePending(pc.id)
            return
        }
        do {
            _ = try await request(path, method: "DELETE")
        } catch APIError.offline, APIError.badURL {
            LocalStore.shared.enqueue(method: "DELETE", path: path)
        } catch { }
    }

    // MARK: - Voice (requires server)

    /// After a rule-path voice response, poll for LLM background verification.
    /// Retries every 4 s for up to 40 s, then gives up (assumes ok).
    /// Calls `onCorrection` on the main actor if the LLM found an error.
    func pollVerify(token: String, onCorrection: @escaping (VerifyResult) async -> Void) {
        Task.detached(priority: .background) { [weak self] in
            guard let self else { return }
            for _ in 1...10 {
                try? await Task.sleep(nanoseconds: 4_000_000_000)  // 4 s
                guard let data = try? await self.request("/voice/verify/\(token)"),
                      let result = try? JSONDecoder().decode(VerifyResult.self, from: data)
                else { continue }

                if result.pending == true { continue }  // not ready yet
                if result.ok == true { return }         // confirmed correct — silent

                // LLM found a correction
                await onCorrection(result)
                return
            }
            // Timed out — assume ok
        }
    }

    /// The last few commands the Mac ran (either device). Used to recover the
    /// outcome when a stream is cut short — the Mac finished the work, the
    /// phone just lost the connection.
    func recentCommands(limit: Int = 3) async -> [MemoryExample] {
        guard let data = try? await request("/memory?limit=\(limit)"),
              let list = try? JSONDecoder().decode(MemoryListResponse.self, from: data)
        else { return [] }
        return list.examples
    }

    /// - Parameters:
    ///   - editedFrom: the transcript the host doubted, when this is the second
    ///     half of a needs_edit round-trip. Present ⇒ the host bypasses the gate
    ///     for this resubmission and learns from the change (or the confirmation).
    ///   - supportsEdit: this client can render the "edit the transcription"
    ///     sheet, so the host may return a needs_edit response.
    ///   - supportsConfirm: this client can render the "add this?" prompt, so
    ///     the host may return a confirm_create proposal instead of guessing
    ///     what to do with a question about creating something.
    func sendText(_ transcript: String, editedFrom: String? = nil,
                  supportsEdit: Bool = false,
                  supportsConfirm: Bool = false) async throws -> VoiceResponse {
        // Identify the client. The server treats an unlabelled caller as a
        // test, so that a curl during development cannot masquerade as a
        // command you actually gave the phone.
        await enrollIfNeeded()
        var body: [String: Any] = ["transcript": transcript, "source": "ios"]
        if !Self.deviceID.isEmpty { body["device_id"] = Self.deviceID }
        if !Self.deviceToken.isEmpty { body["device_token"] = Self.deviceToken }
        if supportsEdit { body["supports_edit"] = true }
        if supportsConfirm { body["supports_confirm"] = true }
        if let editedFrom { body["edited_from"] = editedFrom }
        let data = try await request("/voice/text", method: "POST", body: body)
        return try decode(VoiceResponse.self, from: data)
    }

    // MARK: - Device identity

    /// This phone's ISSUED name and token — not a name it chose for itself.
    ///
    /// Every iPhone posts `source: "ios"`, so the host used to treat the whole
    /// tailnet as one stream and concatenate two phones' queued commands into a
    /// single utterance. The host now groups on the device instead.
    ///
    /// **Enrolled, not self-declared.** A self-chosen id is only a CLAIM: two
    /// phones could pick the same one by accident, and any caller could elect to
    /// be your phone. `POST /devices/enroll` has the host issue the id and sign
    /// it, so what arrives in a request is a fact rather than an assertion.
    ///
    /// An unsigned client is never refused — the host ISOLATES it, giving it its
    /// own queue rather than letting it join anyone's — so every failure here
    /// degrades to the behaviour before enrolment existed: the phone still
    /// works, it simply is not grouped with its own earlier self until the next
    /// successful enrolment.
    private enum DeviceStore {
        static let idKey = "macalendar.device_id"
        static let tokenKey = "macalendar.device_token"

        /// The token is a BEARER CREDENTIAL — anything holding it can speak as
        /// this phone — so it lives in the Keychain, not `UserDefaults`.
        /// `UserDefaults` is a plist in the app container: readable from a
        /// backup, and not protected when the device is locked.
        /// `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` keeps it off
        /// backups and off any other device, while still being readable when
        /// the app runs in the background after a reboot+unlock.
        static func loadToken() -> String? {
            let q: [String: Any] = [
                kSecClass as String: kSecClassGenericPassword,
                kSecAttrService as String: "MACalendar",
                kSecAttrAccount as String: tokenKey,
                kSecReturnData as String: true,
            ]
            var out: CFTypeRef?
            guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess,
                  let data = out as? Data,
                  let s = String(data: data, encoding: .utf8), !s.isEmpty
            else { return nil }
            return s
        }

        static func saveToken(_ token: String) {
            let base: [String: Any] = [
                kSecClass as String: kSecClassGenericPassword,
                kSecAttrService as String: "MACalendar",
                kSecAttrAccount as String: tokenKey,
            ]
            SecItemDelete(base as CFDictionary)
            var add = base
            add[kSecValueData as String] = Data(token.utf8)
            add[kSecAttrAccessible as String] =
                kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
            SecItemAdd(add as CFDictionary, nil)
        }
    }

    /// The id, once enrolled. Empty until the host has been reachable once.
    static var deviceID: String {
        UserDefaults.standard.string(forKey: DeviceStore.idKey) ?? ""
    }

    static var deviceToken: String { DeviceStore.loadToken() ?? "" }

    /// Enrol if we have not already. Safe to call before every send: it is a
    /// no-op once an id exists, and a single failed attempt costs one short
    /// request that the caller ignores.
    func enrollIfNeeded() async {
        guard Self.deviceID.isEmpty || Self.deviceToken.isEmpty else { return }
        let label = "iPhone · " + UIDevice.current.name
        do {
            let data = try await request("/devices/enroll", method: "POST",
                                         body: ["source": "ios", "label": label])
            guard let got = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let id = got["device_id"] as? String, !id.isEmpty,
                  let token = got["token"] as? String, !token.isEmpty
            else { return }
            UserDefaults.standard.set(id, forKey: DeviceStore.idKey)
            DeviceStore.saveToken(token)
        } catch {
            // Offline, or an older host with no /devices/enroll. Either way the
            // phone keeps working, unenrolled and isolated.
        }
    }

    /// Answer a confirm_create proposal. The host does the creating, through
    /// exactly the code a POST /events / POST /todos would run — and answering
    /// twice is safe, so a double-tapped Add creates once.
    func confirmCreate(token: String, accept: Bool) async throws -> ConfirmResponse {
        let data = try await request("/voice/confirm", method: "POST",
                                     body: ["confirm_token": token, "accept": accept])
        return try decode(ConfirmResponse.self, from: data)
    }

    func sendAudio(_ audioData: Data) async throws -> VoiceResponse {
        guard !base.isEmpty, let url = URL(string: base + "/voice") else {
            throw APIError.badURL
        }
        if isBackingOff { throw APIError.offline("the Mac was unreachable a moment ago") }
        // Same pipeline as /voice/stream, run synchronously instead of
        // reported step by step — same 120 s budget, or a deep-track command
        // (p50 ~40 s, p95 ~84 s per dataset/RESULTS.md) times out client-side
        // while the Mac keeps running it, gets requeued, and is replayed a
        // second time on the next retry.
        var req = URLRequest(url: url, timeoutInterval: 120)
        req.httpMethod = "POST"
        if !settings.apiKey.isEmpty {
            req.setValue(settings.apiKey, forHTTPHeaderField: "X-API-Key")
        }
        let boundary = UUID().uuidString
        req.setValue("multipart/form-data; boundary=\(boundary)",
                     forHTTPHeaderField: "Content-Type")
        var body = Data()
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"audio\"; filename=\"audio.wav\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: audio/wav\r\n\r\n".data(using: .utf8)!)
        body.append(audioData)
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)
        req.httpBody = body
        do {
            let (data, resp) = try await URLSession.shared.data(for: req)
            isOnline = true
            // The Mac answered — that alone doesn't mean the command ran; an
            // unhandled exception in the engine reaches here as a non-2xx,
            // non-JSON body (Flask's default error page), which would
            // otherwise fail `decode` and get mislabeled below.
            guard let http = resp as? HTTPURLResponse, (200...299).contains(http.statusCode) else {
                throw APIError.serverError(String(data: data, encoding: .utf8) ?? "Unknown error")
            }
            return try decode(VoiceResponse.self, from: data)
        } catch let err as APIError {
            // The Mac ANSWERED and we disliked the answer. That is not offline,
            // and saying it is put the app in the state Gil screenshotted on
            // 2026-09-10: the orange "Offline — changes saved locally" banner
            // sitting directly above Settings › Test Connection reporting
            // "✓ ollama (llama3.1:8b) — ok".
            throw err
        } catch let err as URLError where err.code == .timedOut {
            // A 30 s audio upload times out on a weak link long before an 8 s
            // GET does, so ONE slow upload used to mark the whole app offline
            // while every other request was succeeding. A timeout on a big body
            // is not proof the Mac is gone; leave `isOnline` alone and let the
            // small, fast requests decide reachability.
            throw APIError.offline(err.localizedDescription)
        } catch {
            isOnline = false
            throw APIError.offline(error.localizedDescription)
        }
    }

    /// Streaming variant of sendAudio: POST /voice/stream returns NDJSON —
    /// one {"type":"step",...} line per pipeline stage, then {"type":"result",...}.
    /// `onStep` fires on the main actor as each stage arrives.
    func sendAudioStreaming(_ audioData: Data, supportsEdit: Bool = false,
                            supportsConfirm: Bool = false,
                            onStep: @escaping (TraceStep) -> Void) async throws -> VoiceResponse {
        guard !base.isEmpty, let url = URL(string: base + "/voice/stream") else {
            throw APIError.badURL
        }
        // A 120 s timeout is right for a Mac that is thinking and wrong for one
        // that is not there: without this the phone sat on a finished recording
        // for two minutes before queueing it.
        if isBackingOff { throw APIError.offline("the Mac was unreachable a moment ago") }
        var req = URLRequest(url: url, timeoutInterval: 120)
        req.httpMethod = "POST"
        if !settings.apiKey.isEmpty {
            req.setValue(settings.apiKey, forHTTPHeaderField: "X-API-Key")
        }
        let boundary = UUID().uuidString
        req.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        var body = Data()
        // Declare we can show the edit-transcription sheet, so the host may gate
        // a doubtful transcript behind a needs_edit round-trip.
        if supportsEdit {
            body.append("--\(boundary)\r\n".data(using: .utf8)!)
            body.append("Content-Disposition: form-data; name=\"supports_edit\"\r\n\r\n".data(using: .utf8)!)
            body.append("true\r\n".data(using: .utf8)!)
        }
        // …and the "add this?" prompt, so a question about creating something
        // comes back as a proposal rather than being executed or dropped.
        if supportsConfirm {
            body.append("--\(boundary)\r\n".data(using: .utf8)!)
            body.append("Content-Disposition: form-data; name=\"supports_confirm\"\r\n\r\n".data(using: .utf8)!)
            body.append("true\r\n".data(using: .utf8)!)
        }
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"audio\"; filename=\"audio.wav\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: audio/wav\r\n\r\n".data(using: .utf8)!)
        body.append(audioData)
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)
        req.httpBody = body

        let decoder = JSONDecoder()
        let assertion = BackgroundAssertion()
        assertion.begin("voice-command")
        defer { assertion.end() }
        do {
            let (bytes, resp) = try await URLSession.shared.bytes(for: req)
            guard let http = resp as? HTTPURLResponse, (200...299).contains(http.statusCode) else {
                throw APIError.serverError("HTTP error")
            }
            isOnline = true
            var final: VoiceResponse?
            for try await line in bytes.lines {
                guard let data = line.data(using: .utf8),
                      let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                      let type = obj["type"] as? String else { continue }
                if type == "step", let step = try? decoder.decode(TraceStep.self, from: data) {
                    onStep(step)
                } else if type == "result" {
                    final = try? decoder.decode(VoiceResponse.self, from: data)
                }
            }
            guard let final else { throw APIError.serverError("Stream ended without a result") }
            return final
        } catch let err as APIError {
            throw err
        } catch {
            isOnline = false
            throw APIError.offline(error.localizedDescription)
        }
    }

    // MARK: - Vocabulary (STT auto-correct)

    // MARK: - Where sundown is computed for

    /// Tell the host where this device is. Only the position — how long before
    /// candle lighting a session must finish is a preference set on the host,
    /// not a fact a phone knows.
    ///
    /// Queued when the host is away, and `DeviceLocation` is why it has to be:
    /// it marks a position as sent BEFORE sending it, so a failed send used to
    /// be dropped and never retried until the phone moved another 25 km. The
    /// queue replays positions in the order they were taken, so the last one
    /// to land is the newest.
    func setObservanceLocation(latitude: Double, longitude: Double,
                               timezone: String, city: String = "") async throws {
        try await mutate("/observance/location", method: "POST", body: [
            "latitude": latitude, "longitude": longitude,
            "timezone": timezone, "city": city, "source": "ios",
        ])
    }

    /// Forget it and go back to the place configured on the host.
    func clearObservanceLocation() async throws {
        try await mutate("/observance/location", method: "DELETE")
    }

    // MARK: - Tag discovery (consent-based new classes)

    /// One polite ask per week at most — all rate-limiting is server-side;
    /// call only from a foregrounded view.
    func tagSuggestion() async -> TagSuggestion? {
        guard let data = try? await request("/tags/suggestion"),
              let s = try? JSONDecoder().decode(TagSuggestion.self, from: data),
              let n = s.name, !n.isEmpty else { return nil }
        return s
    }

    func answerTagSuggestion(name: String, accept: Bool) async {
        _ = try? await request("/tags/suggestion/answer", method: "POST",
                               body: ["name": name, "accept": accept])
    }

    /// Every past suggestion and its verdict, newest first — hidden rows
    /// included, with their flag, because folding them away is the client's
    /// decision. Throws so the history view can tell "the Mac is away" from
    /// "you have never been asked anything".
    func tagSuggestionHistory() async throws -> [TagSuggestionRecord] {
        try decode([TagSuggestionRecord].self,
                   from: try await request("/tags/suggestions/history"))
    }

    /// Change a past verdict. Un-accepting deletes the class from the registry
    /// again — and, exactly as deleting a tag by hand does, strips it from
    /// every task — so callers should refresh their tag list afterwards.
    func reviseTagSuggestion(name: String, accept: Bool) async throws {
        _ = try await request("/tags/suggestions/revise", method: "POST",
                              body: ["name": name, "accept": accept])
    }

    /// Fold an entry out of the visible history, or back into it. The record
    /// is kept either way; this only moves a display flag. Sent as its own
    /// request because the Mac reads `hidden` in preference to `accept` when
    /// both are present.
    func setTagSuggestionHidden(name: String, hidden: Bool) async throws {
        _ = try await request("/tags/suggestions/revise", method: "POST",
                              body: ["name": name, "hidden": hidden])
    }

    func vocab() async throws -> VocabState {
        try decode(VocabState.self, from: try await request("/vocab"))
    }

    // The vocabulary is hand-curated and irreplaceable — nothing regenerates a
    // word you taught it — so every write below is queued rather than lost.

    func vocabAddWord(_ word: String, aliases: [String] = [],
                      label: String = "", expandsTo: String = "") async throws {
        var body: [String: Any] = ["word": word, "aliases": aliases]
        if !label.isEmpty     { body["label"]      = label }
        if !expandsTo.isEmpty { body["expands_to"] = expandsTo }
        try await mutate("/vocab", method: "POST", body: body)
    }

    /// Teach a correction: STT heard `wrong`, you meant `right`.
    /// Change a word the settings screen is showing.
    ///
    /// Only the fields passed are sent, and the server changes only what it
    /// receives — so clearing a label means sending an empty string, which is
    /// deliberately different from not sending it at all.
    func vocabUpdate(word: String, label: String? = nil,
                     expandsTo: String? = nil, aliases: [String]? = nil) async throws {
        var fields: [String: Any] = [:]
        if let label     { fields["label"]      = label }
        if let expandsTo { fields["expands_to"] = expandsTo }
        if let aliases   { fields["aliases"]    = aliases }
        guard !fields.isEmpty else { return }
        let path = "/vocab/\(word.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? word)"
        try await mutate(path, method: "PATCH", body: fields)
    }

    func vocabTeach(wrong: String, right: String) async throws {
        try await mutate("/vocab/alias", method: "POST", body: ["wrong": wrong, "right": right])
    }

    func vocabDelete(word: String, alias: String? = nil) async throws {
        var path = "/vocab/" + (word.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? word)
        if let alias, let a = alias.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) {
            path += "?alias=" + a
        }
        try await mutate(path, method: "DELETE")
    }

    /// nil when the Mac was away: the setting is queued, and the screen keeps
    /// the state it already has rather than being handed an invented one.
    func vocabSettings(autoCorrect: Bool? = nil, learnAliases: Bool? = nil, threshold: Double? = nil) async throws -> VocabState? {
        var body: [String: Any] = [:]
        if let autoCorrect { body["auto_correct"] = autoCorrect }
        if let learnAliases { body["learn_aliases"] = learnAliases }
        if let threshold { body["threshold"] = threshold }
        guard let data = try await mutate("/vocab/settings", method: "PATCH", body: body) else { return nil }
        return try decode(VocabState.self, from: data)
    }

    /// A POST that WRITES NOTHING — "mine this text for words I might want",
    /// answered with candidates the user then picks from (`vocabAddWords` is
    /// the write). So it is not queued: the answer is the whole point, and a
    /// replay an hour later would hand a list of suggestions to a screen that
    /// is no longer open — after parking a WhatsApp export in the write queue.
    func vocabImport(text: String? = nil, source: String? = nil, names: [String]? = nil) async throws -> [VocabCandidate] {
        var body: [String: Any] = [:]
        if let text { body["text"] = text }
        if let source { body["source"] = source }
        if let names { body["names"] = names }
        return try decode(VocabImportResult.self, from: try await request("/vocab/import", method: "POST", body: body)).candidates
    }

    func vocabAddWords(_ words: [String]) async throws {
        try await mutate("/vocab/bulk", method: "POST", body: ["words": words])
    }

    func vocabOnboarding() async throws -> VocabOnboarding {
        try decode(VocabOnboarding.self, from: try await request("/vocab/onboarding"))
    }

    func vocabOnboardingSubmit(answers: [String: [String]], presets: [String]) async throws {
        try await mutate("/vocab/onboarding", method: "POST",
                         body: ["answers": answers, "presets": presets, "done": true])
    }

    // MARK: - Pending (queued) commands

    func retryPending(id: Int) async throws -> VoiceResponse {
        try decode(VoiceResponse.self, from: try await request("/pending/\(id)/retry", method: "POST"))
    }

    // MARK: - Command memory feedback

    func unreviewedCommands(limit: Int = 30) async throws -> [MemoryExample] {
        try decode(UnreviewedResponse.self, from: try await request("/memory/unreviewed?limit=\(limit)")).examples
    }

    func unreviewedCount() async -> Int {
        (try? await unreviewedCommands(limit: 50).count) ?? 0
    }

    /// Dismiss the backlog. Queued when the Mac is away; nil then, because
    /// how many were dismissed is only known once it happens.
    ///
    /// A late replay dismisses whatever is unreviewed at that moment, which can
    /// include a command the Mac ran in between. That is a missed review rather
    /// than a wrong one — "skipped" is not "approved" and trains nothing.
    func skipAllUnreviewed() async -> Int? {
        guard let d = try? await mutate("/memory/unreviewed/skip", method: "POST", body: [:]),
              let o = try? JSONSerialization.jsonObject(with: d) as? [String: Any] else { return nil }
        return o["skipped"] as? Int
    }

    /// A verdict on one remembered command, by its id — the same verdict
    /// whenever it lands, so it is queued.
    func memoryFeedback(id: Int, feedback: String, correction: [[String: Any]]? = nil, notes: String = "") async {
        var body: [String: Any] = ["feedback": feedback, "notes": notes]
        if let correction { body["correction"] = correction }
        await mutateOrTell("/memory/\(id)/feedback", method: "POST", body: body)
    }

    // MARK: - Timers & counters

    /// Cached like every other read. This was the ONLY read in the app with no
    /// fallback, so the Timer tab was simply empty away from the Mac.
    func timers(archived: Bool = false) async throws -> [WorkTimer] {
        do {
            let items = try decode(TimersResponse.self,
                                   from: try await request("/timers" + (archived ? "?archived=1" : ""))).timers
            LocalStore.shared.cacheTimers(items)
            return items
        } catch APIError.offline, APIError.badURL {
            return LocalStore.shared.allTimers(includeArchived: archived)
        }
    }
    /// True when the timer exists or WILL exist: a create the Mac never saw is
    /// queued, and the sheet closing is how the user is told it stuck. False
    /// only when the Mac answered and refused.
    @discardableResult
    func createTimer(_ body: [String: Any]) async -> Bool {
        // Stamped here, not at the call site: a token added by whoever builds
        // the dictionary is a token somebody eventually forgets.
        let body = body.merging(["client_token": UUID().uuidString]) { a, _ in a }
        do { _ = try await mutate("/timers", method: "POST", body: body); return true }
        catch { announceRefusal(error, doing: "add that timer"); return false }
    }
    func updateTimer(_ id: Int, _ body: [String: Any]) async { await mutateOrTell("/timers/\(id)", method: "PATCH", body: body) }
    func deleteTimer(_ id: Int) async { await mutateOrTell("/timers/\(id)", method: "DELETE") }

    // The clock's instants come from the PHONE, not from `now()` on the Mac.
    //
    // Everything else in the queue is safe to replay late because it says what
    // it wants. "Start this timer" does not: it means "start it at the moment I
    // tapped", and a Mac reading its own clock an hour later would bank an hour
    // of work that never happened — corruption, not recovery, and the reason a
    // queued write has to be judged one method at a time rather than by tab.
    //
    // So the tap's instant travels with the request. `/timers/<id>/start`,
    // `/stop`, `/counters/<id>/press` and `/cashout`
    // (`assistant/features/timer/routes.py`) honour it when it is there and
    // fall back to their own clock when it is not — the db layer always
    // accepted one, only the routes never passed it through. It is sent live
    // as well as replayed, so there is one path rather than a replay-only one
    // that nothing exercises until it matters.
    func startTimer(_ id: Int) async {
        await mutateOrTell("/timers/\(id)/start", method: "POST", body: ["start_time": Self.stamp()])
    }
    func stopTimer(_ id: Int) async {
        await mutateOrTell("/timers/\(id)/stop", method: "POST", body: ["end_time": Self.stamp()])
    }
    func timerSessions(_ id: Int) async throws -> [TimerSession] {
        try decode(TimerSessionsResponse.self, from: try await request("/timers/\(id)/sessions")).sessions
    }
    func deleteTimerSession(_ id: Int) async { await mutateOrTell("/timer_sessions/\(id)", method: "DELETE") }

    /// Log time you forgot to start the timer for — the Mac's "Log past time…".
    /// `end` omitted creates a session that is still running.
    ///
    /// Queueable without any of the care above, because it already names its
    /// own instants — which is exactly the shape start/stop were converted to.
    func logTimerSession(_ id: Int, start: Date, end: Date?, title: String = "") async -> Bool {
        var body: [String: Any] = ["start_time": Self.stamp(start), "title": title]
        if let end { body["end_time"] = Self.stamp(end) }
        do { _ = try await mutate("/timers/\(id)/sessions", method: "POST", body: body); return true }
        catch { announceRefusal(error, doing: "log that session"); return false }
    }

    func counters(archived: Bool = false) async throws -> [TallyCounter] {
        do {
            let items = try decode(CountersResponse.self,
                                   from: try await request("/counters" + (archived ? "?archived=1" : ""))).counters
            LocalStore.shared.cacheCounters(items)
            return items
        } catch APIError.offline, APIError.badURL {
            return LocalStore.shared.allCounters(includeArchived: archived)
        }
    }
    @discardableResult
    func createCounter(_ body: [String: Any]) async -> Bool {
        let body = body.merging(["client_token": UUID().uuidString]) { a, _ in a }
        do { _ = try await mutate("/counters", method: "POST", body: body); return true }
        catch { announceRefusal(error, doing: "add that counter"); return false }
    }
    func updateCounter(_ id: Int, _ body: [String: Any]) async { await mutateOrTell("/counters/\(id)", method: "PATCH", body: body) }
    func deleteCounter(_ id: Int) async { await mutateOrTell("/counters/\(id)", method: "DELETE") }

    /// A tap, carrying the moment it happened: a counter's `today_count` is
    /// bucketed by that timestamp, so a press made before midnight and replayed
    /// after would otherwise be counted on the wrong day.
    func pressCounter(_ id: Int, delta: Int) async {
        // Optimistic FIRST, so ＋ moves the number at the moment of the tap
        // rather than a round trip later — and at all when the Mac is away.
        // Reported as "＋ does nothing offline": the press was being queued
        // correctly the whole time, but the tab had no cached count to apply
        // it to, so nothing moved and the button looked dead.
        LocalStore.shared.bumpCounter(id, delta: delta)
        await mutateOrTell("/counters/\(id)/press", method: "POST",
                           body: ["delta": delta, "pressed_at": Self.stamp()])
    }

    /// Bank the current cycle, stamped with the moment it was asked for. The
    /// COUNT stays the Mac's, computed from the presses it holds — which is the
    /// right number, because the queue replays in order: every press made
    /// before the cash-out lands before it, and every later one after it.
    func cashOutCounter(_ id: Int) async {
        await mutateOrTell("/counters/\(id)/cashout", method: "POST", body: ["cashed_at": Self.stamp()])
    }

    /// Every tap on this counter, newest first. The server has served this
    /// since counters existed; nothing on the phone asked for it.
    func counterPresses(_ id: Int) async -> [CounterPress] {
        guard let data = try? await request("/counters/\(id)/presses"),
              let r = try? JSONDecoder().decode(CounterPressesResponse.self, from: data)
        else { return [] }
        return r.presses
    }

    /// Every cash-out on this counter.
    func counterPayouts(_ id: Int) async -> [CounterPayout] {
        guard let data = try? await request("/counters/\(id)/payouts"),
              let r = try? JSONDecoder().decode(CounterPayoutsResponse.self, from: data)
        else { return [] }
        return r.payouts
    }

    /// Undo one tap. Named by the id the Mac issued, so it means the same thing
    /// whenever it is replayed.
    func deleteCounterPress(_ pressID: Int) async {
        await mutateOrTell("/counter_presses/\(pressID)", method: "DELETE")
    }

    /// A few bytes that change whenever anything in the Mac's database does.
    /// Polling this is cheap enough to do every couple of seconds, so a change
    /// made on the Mac shows up almost at once instead of on the next 30 s
    /// full refresh. Returns nil if the Mac can't be reached.
    func changeToken() async -> String? {
        guard let data = try? await request("/changes"),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return nil }
        return obj["token"] as? String
    }

    /// Pull calendar events into the task list — the Mac's "Sync Today" button.
    /// `list` is "today" or "general".
    ///
    /// **Not queued**, unlike every other write here. It carries no content of
    /// the user's: it asks the Mac to read ITS OWN calendar for TODAY and copy
    /// what it finds. Replayed tomorrow it would do a different job from the one
    /// that was asked for, and the count it returns — the only thing the button
    /// shows — would be reported to nobody. It is a button you press when the
    /// Mac is there, and pressing it again costs nothing.
    @discardableResult
    func syncTodosFromCalendar(list: String = "today") async -> Int {
        guard let data = try? await request("/todos/sync", method: "POST", body: ["list_name": list]),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let n = obj["synced"] as? Int
        else { return 0 }
        return n
    }

    // MARK: - Notifications config (server-side reminder policy)

    /// The `notifications` section of GET /config. The Mac computes every
    /// event's notify_at from this; the phone only edits it.
    func notificationsConfig() async throws -> NotificationsConfig {
        struct ConfigEnvelope: Codable { let notifications: NotificationsConfig? }
        let data = try await request("/config")
        guard let n = (try decode(ConfigEnvelope.self, from: data)).notifications else {
            throw APIError.serverError("This Mac doesn't serve a notifications config yet.")
        }
        return n
    }

    /// PATCH /config with a partial `notifications` section, e.g.
    /// ["default_lead_minutes": 15] or ["category_leads": fullUpdatedMap]
    /// (the server merges at the section level, so category_leads must be
    /// sent whole). Returns whether the setting stuck — queued counts, since
    /// it will; false is the Mac refusing it.
    @discardableResult
    func patchNotifications(_ fields: [String: Any]) async -> Bool {
        do { _ = try await mutate("/config", method: "PATCH", body: ["notifications": fields]); return true }
        catch { announceRefusal(error, doing: "save that reminder setting"); return false }
    }

    // MARK: - Features (which surfaces exist, and which are switched on)

    /// Every surface the Mac knows about, and whether it is switched on.
    ///
    /// Only `visible` is read from this — the tab bar's structure is declared
    /// in `FeatureRegistry`, on purpose: a bar built from this answer could not
    /// be drawn until the request came back, and with the Mac asleep it would
    /// never be drawn at all. So nothing on the render path awaits this.
    func features() async throws -> [FeatureManifest] {
        try decode([FeatureManifest].self, from: try await request("/features"))
    }

    /// Switch one on or off. Throws rather than swallowing, because the Mac
    /// REFUSES some of these: a pinned feature (Calendar, Tasks) answers 409
    /// with a sentence saying why, and a toggle that springs back without it
    /// reads as a bug in the app. `APIError.serverSentence` pulls it out.
    @discardableResult
    func setFeatureVisible(_ name: String, _ visible: Bool) async throws -> FeatureManifest {
        let encoded = name.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? name
        let data = try await request("/features/\(encoded)", method: "PATCH",
                                     body: ["visible": visible])
        return try decode(FeatureManifest.self, from: data)
    }

    // MARK: - Event categories

    func categories() async throws -> [EventCategory] {
        try decode(CategoriesResponse.self, from: try await request("/categories")).categories
    }

    /// A category and its colours are the user's own scheme, so an edit made
    /// with the Mac away is queued rather than dropped. True means it stuck —
    /// queued counts, because the sheet closing is how that is said.
    @discardableResult
    func upsertCategory(name: String, color: String, alt: String, keywords: [String]) async -> Bool {
        do {
            _ = try await mutate("/categories", method: "POST",
                                 body: ["name": name, "color": color, "alt": alt, "keywords": keywords])
            return true
        } catch { announceRefusal(error, doing: "save that category"); return false }
    }

    func deleteCategory(_ name: String) async {
        let enc = name.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? name
        await mutateOrTell("/categories/\(enc)", method: "DELETE")
    }

    func recolorEvents(force: Bool) async -> Int? {
        guard let data = try? await request("/categories/recolor" + (force ? "?force=1" : ""), method: "POST", body: [:]),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        return obj["updated"] as? Int
    }

    // MARK: - Courses
    //
    // This tab is where the missing queue was found. `CourseStore`'s header
    // said "offline writes are queued in LocalStore.shared.enqueue() and
    // replayed on reconnect"; `/courses` and `/assignments` appeared in no
    // enqueue call site at all, and `CourseworkView` swallowed the failure with
    // `try?`. Delete a course offline and it came back on the next sync; add an
    // assignment offline and it was gone by it.

    /// Cached and falling back HERE, like every other read.
    ///
    /// Coursework used to cache in its VIEW instead — `CourseworkView.load()`
    /// called `try? api.courses()` and wrote the result to `CourseStore`. It
    /// worked, but it meant you could not tell whether a surface had an
    /// offline answer without opening its view file, and it is the same split
    /// thinking that let the offline WRITES go missing. One place decides.
    func courses() async throws -> [Course] {
        do {
            let items = try decode([Course].self, from: try await request("/courses"))
            CourseStore.shared.cacheCourses(items)
            return items
        } catch APIError.offline, APIError.badURL {
            return CourseStore.shared.courses
        }
    }

    /// The local row is minted FIRST, so the course is on screen this frame
    /// whether or not the Mac is there — and its placeholder id rides into the
    /// queue as `_temp_id`, which is how `syncPending` finds anything queued
    /// behind it (an assignment added to this course, a change of colour) and
    /// repoints it once the Mac answers with a real id.
    @discardableResult
    func createCourse(number: String, name: String, color: String, partners: [String]) async throws -> Int {
        // ONE token for this course, on the live attempt AND every replay:
        // the Mac returns the row it already has instead of a second one. A
        // create that commits and then loses its reply is the whole reason —
        // see assistant/features/idempotency.py.
        let body: [String: Any] = ["number": number, "name": name, "color": color,
                                   "partners": partners,
                                   "client_token": UUID().uuidString]
        let local = CourseStore.shared.insertCourse(number: number, name: name,
                                                    color: color, partners: partners)
        do {
            let data = try await request("/courses", method: "POST", body: body)
            let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]
            let realID = json?["id"] as? Int ?? -1
            // Online, the placeholder lives for one round trip — but anything
            // the user did in that time (adding an assignment to it) was
            // already recorded against it, so it is remapped rather than
            // deleted and refetched.
            if realID > 0 { LocalStore.shared.remapTemporaryID(local.id, to: realID) }
            return realID
        } catch APIError.offline, APIError.badURL {
            LocalStore.shared.enqueue(method: "POST", path: "/courses",
                                      body: body.merging(["_temp_id": local.id]) { a, _ in a })
            return local.id
        } catch {
            // The Mac ANSWERED and refused. Nothing will replay it, so the
            // optimistic row has to go: a phantom course that no sync will ever
            // clear is worse than the save the user can see failing.
            CourseStore.shared.removeCourse(local.id)
            throw error
        }
    }

    func updateCourse(id: Int, number: String, name: String, color: String, partners: [String]) async throws {
        let body: [String: Any] = ["number": number, "name": name, "color": color, "partners": partners]
        try await mutate("/courses/\(id)", method: "PATCH", body: body)
    }

    /// A course deleted while it was still only queued is left to replay as
    /// create-then-delete rather than being cancelled: the DELETE is rewritten
    /// onto the real id the create comes back with, so the Mac ends in the state
    /// the user asked for either way.
    func deleteCourse(id: Int) async throws {
        try await mutate("/courses/\(id)", method: "DELETE")
    }

    // MARK: - Assignments

    func allAssignments() async throws -> [Assignment] {
        do {
            let items = try decode([Assignment].self, from: try await request("/assignments"))
            CourseStore.shared.cacheAllAssignments(items)
            return items
        } catch APIError.offline, APIError.badURL {
            return CourseStore.shared.assignments
        }
    }

    /// Same shape as `createCourse`, and for the same reason — with one extra:
    /// `course_id` may itself be a placeholder, when the course was created
    /// offline a moment ago. `LocalStore.remapTemporaryID` rewrites `*_id`
    /// fields inside queued bodies too, so this lands under the right course.
    @discardableResult
    func createAssignment(courseId: Int, title: String, dueDate: String = "") async throws -> Int {
        let body: [String: Any] = ["course_id": courseId, "title": title,
                                   "due_date": dueDate,
                                   "client_token": UUID().uuidString]
        let local = CourseStore.shared.insertAssignment(courseId: courseId, title: title,
                                                        dueDate: dueDate)
        do {
            let data = try await request("/assignments", method: "POST", body: body)
            let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]
            let realID = json?["id"] as? Int ?? -1
            if realID > 0 { LocalStore.shared.remapTemporaryID(local.id, to: realID) }
            return realID
        } catch APIError.offline, APIError.badURL {
            LocalStore.shared.enqueue(method: "POST", path: "/assignments",
                                      body: body.merging(["_temp_id": local.id]) { a, _ in a })
            return local.id
        } catch {
            CourseStore.shared.removeAssignment(local.id)
            throw error
        }
    }

    func updateAssignment(id: Int, title: String? = nil, dueDate: String? = nil,
                          calendarEventId: Int? = nil) async throws {
        var body: [String: Any] = [:]
        if let v = title           { body["title"]             = v }
        if let v = dueDate         { body["due_date"]          = v }
        if let v = calendarEventId { body["calendar_event_id"] = v }
        try await mutate("/assignments/\(id)", method: "PATCH", body: body)
    }

    /// Queued, the phone's own copy is the answer — the view has already
    /// flipped it, and the Mac will agree once it sees the tick. Same answer
    /// `toggleTodo` gives.
    @discardableResult
    func toggleAssignment(id: Int) async throws -> Bool {
        guard let data = try await mutate("/assignments/\(id)/toggle", method: "PATCH", body: [:]) else {
            return CourseStore.shared.assignments.first { $0.id == id }?.isDone ?? false
        }
        let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        return (json?["completed"] as? Int ?? 0) != 0
    }

    func deleteAssignment(id: Int) async throws {
        try await mutate("/assignments/\(id)", method: "DELETE")
    }

    func clearCompletedAssignments(courseId: Int? = nil) async throws {
        let path = courseId != nil ? "/assignments/completed?course_id=\(courseId!)" : "/assignments/completed"
        try await mutate(path, method: "DELETE")
    }
}

// MARK: - Errors

enum APIError: LocalizedError {
    case badURL
    case offline(String = "")
    case serverError(String)

    var errorDescription: String? {
        switch self {
        case .badURL:
            return "Server URL is not configured. Go to Settings and enter your "
                + "Mac's Tailscale address (\(AppSettings.defaultServerURL))."
        case .offline(let why):
            return "Mac is unreachable" + (why.isEmpty ? "" : " (\(why))") + " — changes saved locally and will sync when connected."
        case .serverError(let msg):
            return msg
        }
    }

    /// The Mac's own `error` sentence, when the refusal carried one.
    ///
    /// `serverError` holds the raw body, which for a refused request is
    /// `{"error": "…", "code": 409}` — readable, but not something to show
    /// someone. This also distinguishes the two failures that matter to a
    /// write: a Mac that said NO (there is a sentence) from a Mac that was not
    /// there at all (there is not), which decide opposite things about whether
    /// a local change stands.
    var serverSentence: String? {
        guard case .serverError(let raw) = self,
              let data = raw.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let sentence = obj["error"] as? String
        else { return nil }
        return sentence
    }
}

// MARK: - Helpers

extension ISO8601DateFormatter {
    static let yyyyMMdd: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()
}
