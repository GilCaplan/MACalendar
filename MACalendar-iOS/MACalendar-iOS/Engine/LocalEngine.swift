import Foundation

/// THE PHONE'S OWN READER — what a command means when there is no Mac.
///
/// Gil, 2026-10-02 (DEVQA Q85): *"improve so the app can work alone if no
/// server connected, with the audio engine features"*. With a Mac paired,
/// nothing here changes: the Mac reads every command and its reading wins
/// (Q66, `assistant/offline/PROTOCOL.md`). On a phone with NO Mac
/// ("This phone only") this is the reader, and what it reads is done.
///
/// Deterministic first, like the Mac's front door (CLAUDE.md): words in, an
/// action out, no model and no network. It keeps the Mac's rulings so a
/// command means the same thing on both:
///
///   Q25/Q26  a stated CLOCK or a RANGE makes an event; a bare day, or none, a to-do
///   Q47      a part of the day ("tonight") is not a clock; seeing a PERSON on a
///            day is an event, 09:00 when no clock was said
///   Q50      CALLING a role is an event and a linked to-do; a person, the event
///   Q56      the person stays in the title
///   Q57      a series with no stated end gets the default end
///   Q61      a to-do that repeats is an event series
///   bare hours 1-8 are PM unless a morning word says otherwise (resolve.py)
///   a delete that cannot name ONE row says so — it never guesses
///
/// Pure Foundation: it compiles into the app AND into
/// `MACalendar-iOS/Tools/local_engine_cli.swift`, which
/// `tests/unit/test_phone_engine.py` and `scripts/phone_engine_board.py`
/// drive — the board scores it on the FastRule set's TRAIN rows.
enum LocalEngine {

    enum Kind: String { case event, todo }
    enum Op: String { case create, update, delete, complete, query, other }

    /// A row the reader may point at (an event or a to-do on this phone).
    struct Row {
        var id: Int
        var kind: Kind
        var title: String
        var date: String          // yyyy-MM-dd, "" for none
        var start: String         // HH:mm, "" for none
        var done: Bool = false
    }

    struct Action {
        var op: Op
        var kind: Kind
        var title: String = ""
        var date: String? = nil            // yyyy-MM-dd
        var start: String? = nil           // HH:mm
        var end: String? = nil
        var allDay = false
        var recurrence: String? = nil      // daily | weekly | monthly | yearly
        var recurDays: [String] = []       // weekly: "monday", …
        var recurrenceEnd: String? = nil
        var list: String? = nil            // a to-do's list
        var linkedTodo = false             // Q50: an event with a to-do beside it
        /// update / delete / complete: the words naming the row, and the day
        /// said with them ("delete the dentist TOMORROW")
        var target: String? = nil
        var targetDate: String? = nil
        var shiftMinutes: Int? = nil       // "push it back an hour"
        var extendMinutes: Int? = nil      // "extend it by 30 minutes" (the end moves)
        var lengthMinutes: Int? = nil      // "make it two hours" (the length is set)
        var newTitle: String? = nil        // "rename X to Y"
        var quantity = 1                   // "buy three protein bars" → 3
        var priority: String? = nil        // "set X as high priority"
        var rangeEnd: String? = nil        // a query over several days
        var notes: [String] = []           // rounding said aloud ("every other … → weekly")
    }

    struct Reading {
        var actions: [Action]
        /// false when nothing here could be read with confidence — the caller
        /// may then hand the words to Apple's on-device model (Q66) or ask.
        var understood: Bool
    }

    // MARK: - Entry

    static func read(_ said: String, now: Date = Date(), calendar: Calendar = .current) -> Reading {
        var cal = calendar
        cal.firstWeekday = 1
        let raw = said.replacingOccurrences(of: #"\s+[—–]\s+|\s+--\s+"#, with: ". ", options: .regularExpression)
            // a title's full stop is not a sentence's: "Dr. Smith", "St. Mary's"
            .replacingOccurrences(of: #"\b(Dr|Mr|Mrs|Ms|Mx|Prof|St|Jr|Sr|Mt|Ave|vs|approx|e\.g|i\.e)\.(?=\s)"#, with: "$1",
                                  options: [.regularExpression, .caseInsensitive])
        let text = normalise(raw)
        guard !text.isEmpty else { return Reading(actions: [], understood: false) }
        var actions: [Action] = []
        for ask in splitAsks(text) {
            if let a = readOne(ask, now: now, cal: cal) { actions.append(a) }
        }
        let understood = !actions.isEmpty && actions.allSatisfy { $0.op != .other }
        return Reading(actions: actions, understood: understood)
    }

    // MARK: - Normalising and splitting

    /// Lower-case is NOT applied to the text itself — a name keeps its capital
    /// in the title (Q56) — only to what is matched against it.
    static func normalise(_ s: String) -> String {
        var t = s.replacingOccurrences(of: "’", with: "'")
        // A reminder's lead time is the reminder, not an ask or a title:
        // "remind me 10 minutes before about X" / "… and remind me 10 minutes before"
        let lead = #"(?:\d+|an?|one|two|five|ten|fifteen|twenty|thirty)\s*(?:minutes?|mins?|hours?|hrs?|days?|weeks?)\s+(?:before(?:hand)?|ahead|early|in advance)(?:\s+beforehand)?"#
        t = t.replacingOccurrences(of: #"^(?:remind|ping|alert|notify) me\s+"# + lead + #"(?:\s+(?:about|of|for|to|before))?"#,
                                   with: "remind me about leadcue ", options: [.regularExpression, .caseInsensitive])
        t = t.replacingOccurrences(of: #"^"# + lead + #"\s+(?=.+,\s*(?:ping|remind|alert|notify) me\s*$)"#, with: "remind me about leadcue ",
                                   options: [.regularExpression, .caseInsensitive])
        t = t.replacingOccurrences(of: #"\b(?:set|add|create) (?:a |an )?(?:reminder|alert|alarm) "# + lead + #" (?:for|of|about|to)\b"#,
                                   with: "remind me about leadcue", options: [.regularExpression, .caseInsensitive])
        t = t.replacingOccurrences(of: #",?\s*(?:and\s+)?(?:remind me|ping me|alert me|notify me|give me a heads[- ]up|send me a reminder)\s+"# + lead,
                                   with: " leadcue", options: [.regularExpression, .caseInsensitive])
        // common slips of the ear and the thumb
        for (wrong, right) in [("remindar", "reminder"), ("remider", "reminder"), ("reshedule", "reschedule"),
                               ("tommorow", "tomorrow"), ("tomorow", "tomorrow"), ("tommorrow", "tomorrow"),
                               ("calender", "calendar"), ("shedule", "schedule"), ("appointmnet", "appointment"), ("updat", "update"),
                               ("delet", "delete"), ("cancle", "cancel"), ("remmind", "remind"),
                               ("apointment", "appointment"), ("appointement", "appointment"), ("mispelling", "misspelling")] {
            t = t.replacingOccurrences(of: #"\b"# + wrong + #"\b"#, with: right, options: [.regularExpression, .caseInsensitive])
        }
        t = t.replacingOccurrences(of: "\u{2014}", with: " ").trimmingCharacters(in: .whitespacesAndNewlines)
        // fillers in the middle of a sentence: "i you know have to", "restock er dog treats", "i like can't forget"
        t = t.replacingOccurrences(of: #"(?<=\s)(?:you know|um+|uh+|er+|erm|i mean|basically|kind of|sort of|like(?=\s+(?:can't|cannot|have|need|gotta|want|must|a|an|the|some|\d)))\s+"#,
                                   with: "", options: [.regularExpression, .caseInsensitive])
        t = t.replacingOccurrences(of: #"\s+"#, with: " ", options: .regularExpression)
        // Openers and closers that carry no meaning: a wake word, politeness,
        // hedges. Repeated, so "ok um please" all goes.
        let openers = #"^(?:(?:ok google|okay google|hey google|hey siri|alexa|olly|pda|computer|listen|one sec(?:ond)?|by the way|btw|pretty sure|"# +
            #"just so you know|fyi|quick one|real quick|any chance you could|is there any chance you could|would you mind|"# +
            #"hey|hi|ok(?:ay)?|so|um+|uh+|er+|well|right|alright|assistant|siri|calendar|please|kindly|yeah|yes|yep|yup|no|nah|oh|actually|"# +
            #"can you|could you|would you|will you|can we|could we|i need you to|i want you to|i'd like you to|"# +
            #"i guess|i think|i need to|i have to|i've got to|i gotta|i got to|i want to|i'd like to|i would like to|"# +
            #"let's do|lets do|let's|lets|go ahead and|just|quickly|real quick|gotta|got to|squeeze in|fit in|"# +
            #"i'm free [^,]*? so|i am free [^,]*? so|i should|i must|i ought to|should|need to|must|note to self|"# +
            #"(?:add|make|leave|write) (?:a |me a )?note (?:to|that)|a note to)[,.!:]?\s+)"#
        var prev = ""
        while prev != t {
            prev = t
            t = t.replacingOccurrences(of: openers, with: "", options: [.regularExpression, .caseInsensitive])
        }
        // an aside after the command: ", i keep misspelling this", "except when i'm busy", "i guess"
        t = t.replacingOccurrences(of: #"(?:,\s*|\s+)(?:i keep|i always|you know|if that's ok|if possible|except when|unless|but only|i mean|whatever|or something|no rush|thanks|thank you|cheers|finally got|no exceptions|without fail|something came up|not sure which|i don't remember|i forget the name)\b.*$"#,
                                   with: "", options: [.regularExpression, .caseInsensitive])
        t = t.replacingOccurrences(of: #"\s+(?:or so|or something|i guess|i think|i suppose|ok|okay)\b"#, with: "",
                                   options: [.regularExpression, .caseInsensitive])
        t = t.replacingOccurrences(of: #"\blike\s+(?=(?:a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|half|\d))"#, with: "",
                                   options: [.regularExpression, .caseInsensitive])
        t = t.replacingOccurrences(of: #"[,.!]?\s*(?:please|thanks|thank you|thx|cheers|for me)\s*[.!]*$"#, with: "",
                                   options: [.regularExpression, .caseInsensitive])
        return t.trimmingCharacters(in: CharacterSet(charactersIn: " .,!?;"))
    }

    /// Two asks in one breath — "add milk and then call the bank" — become
    /// two. Only at a seam that cannot be inside one thing: "and then", "also",
    /// a sentence break, or "and" in front of a COMMAND VERB. "buy milk and
    /// eggs" stays one.
    static func splitAsks(_ text: String) -> [String] {
        let verbs = "add|create|schedule|book|put|set up|set a|set an|set me|remind me|delete|remove|cancel|move|reschedule|push|" +
            "mark|complete|finish|rename|call|email|text|buy|pick up|what|do i have|show me|make a|make an|i need to|i have to|open|bring up"
        let seam = #"(?:\s*[.;!?]\s+|,?\s+and then\s+|,?\s+then\s+|,?\s+(?:and )?also,?\s+|,\s+and\s+(?=(?:(?:alexa|siri|olly|pda|please)\s+)?(?:"# + verbs +
            #")\b)|\s+and\s+(?=(?:(?:alexa|siri|olly|pda|please)\s+)?(?:"# + verbs + #")\b))"#
        let parts = text.replacingOccurrences(of: seam, with: "\u{1F}", options: [.regularExpression, .caseInsensitive])
            .components(separatedBy: "\u{1F}")
            .map { normalise($0) }
            .filter { !$0.isEmpty }
        return parts.isEmpty ? [text] : parts
    }

    // MARK: - One ask

    static func readOne(_ ask: String, now: Date, cal: Calendar) -> Action? {
        let low = ask.lowercased()
        if let q = readQuery(ask, low: low, now: now, cal: cal) { return q }
        if let d = readDelete(ask, low: low, now: now, cal: cal) { return d }
        if let c = readComplete(ask, low: low, now: now, cal: cal) { return c }
        if let r = readRename(ask, low: low) { return r }
        if let m = readMove(ask, low: low, now: now, cal: cal) { return m }
        if let u = readBareUpdate(ask, low: low) { return u }
        if let st = readState(ask, low: low, now: now, cal: cal) { return st }
        if let pr = match(#"^(?:set|make|mark|flag)\s+(.+?)\s+(?:as\s+|to\s+)?(high|low|medium|top|urgent|normal)(?:\s+priority)?$"#, low),
           let t = group(pr, 1, in: ask) {
            var a = Action(op: .update, kind: .todo)
            a.target = cleanTarget(t)
            a.priority = (group(pr, 2, in: low) ?? "high") == "top" || group(pr, 2, in: low) == "urgent" ? "high" : group(pr, 2, in: low)
            return a
        }
        if let mk = readMarkDay(ask, low: low, now: now, cal: cal) { return mk }
        return readCreate(ask, now: now, cal: cal)
    }

    /// A command said as a STATEMENT about a row: "X is off", "X got cancelled",
    /// "X completed", "X is now at 4", "X has moved to monday", "X is now due
    /// friday". The subject is the row; the predicate is the act.
    static func readState(_ ask: String, low: String, now: Date, cal: Calendar) -> Action? {
        let subj = #"^(?:the |my |our |that |this )?(.+?)\s+"#
        // a question then the act: "that dentist tomorrow? cancel it, it's not happening"
        if let m = match(#"^(?:that |the |my )?(.+?)\?\s*(?:yeah,? )?(cancel|delete|remove|scrap|drop|move|push)\s+it\b(.*)$"#, low),
           let t = group(m, 1, in: ask), let verb = group(m, 2, in: low) {
            let (target, date, isTodo) = targetOf(t, now: now, cal: cal)
            if ["move", "push"].contains(verb) {
                let w = DateParse.find(group(m, 3, in: ask) ?? "", now: now, cal: cal)
                var a = Action(op: .update, kind: .event)
                a.target = target; a.targetDate = date?.date; a.date = w.date; a.start = w.start; a.end = w.end
                return a
            }
            var a = Action(op: .delete, kind: isTodo || looksLikeTask(target) ? .todo : .event)
            a.target = target; a.targetDate = date?.date
            return a
        }
        // cancelled
        if let m = match(subj + #"(?:on\s+.+?\s+)?(?:is|are|'s|has been|have been|got|was|were)\s+(?:off|cancel+ed|called off|scrapped|not happening|no longer happening|axed)\b.*$"#, low)
            ?? match(subj + #"(?:isn't|is not|aren't|won't be) happening\b.*$"#, low),
           let t = group(m, 1, in: ask) {
            var a = Action(op: .delete, kind: .event)
            let (target, date, isTodo) = targetOf(t, now: now, cal: cal)
            let dpart = low.range(of: #"\bon\s+(.+?)\s+(?:is|are|'s|got|was)\b"#, options: .regularExpression).map { String(low[$0]) }
            a.target = target
            a.targetDate = date?.date ?? dpart.flatMap { DateParse.find($0, now: now, cal: cal).date }
            a.kind = isTodo || looksLikeTask(t) ? .todo : .event
            return a
        }
        // done
        if let m = match(subj + #"(?:task\s+)?(?:is\s+|are\s+|was\s+|got\s+|has been\s+)?(?:all\s+)?(?:done|completed?|finished|taken care of|sorted|handled)(?:\s*[,.!].*)?$"#, low)
            ?? match(#"^(?:all done with|done with|crossed off|ticked off|cross out|cross off|strike out|you can cross off|you can tick off|you can check off|check the box for|tick|check|tick off|check off)\s+(?:the\s+)?(.+?)(?:\s+task)?(?:\s+(?:as\s+)?(?:done|complete|completed|finished))?(?:\s*[,.!]?\s*(?:it'?s|it is|that'?s)\s+(?:done|finished|complete))?$"#, low),
           let t = group(m, 1, in: ask), !t.lowercased().hasPrefix("i ") {
            var a = Action(op: .complete, kind: .todo)
            a.target = cleanTarget(t.replacingOccurrences(of: #"\s+task$"#, with: "", options: [.regularExpression, .caseInsensitive]))
            return a.target?.isEmpty == false ? a : nil
        }
        // due date moved: "X is now due friday", "X should be done by friday"
        if let m = match(subj + #"(?:is now due|is due|now due|should be done by|needs to be done by|has to be done by)\s+(.+)$"#, low),
           let t = group(m, 1, in: ask), let rest = group(m, 2, in: ask),
           let d = DateParse.find(rest, now: now, cal: cal).date {
            var a = Action(op: .update, kind: .todo)
            a.target = cleanTarget(t); a.date = d
            return a
        }
        // moved: "X is now at 4", "X has moved to monday", "X is running late, move it to 5"
        if let m = match(subj + #"(?:is now|is moving to|has moved to|moved to|was moved to|got moved to|is pushed to|got pushed to|is running late,? move it to|is running late,? push it to|is now on)\s+(.+)$"#, low),
           let t = group(m, 1, in: ask), let rest = group(m, 2, in: ask) {
            let w = DateParse.find(rest, now: now, cal: cal)
            guard w.date != nil || w.start != nil else { return nil }
            var a = Action(op: .update, kind: .event)
            a.target = cleanTarget(t); a.date = w.date; a.start = w.start; a.end = w.end
            return a
        }
        return nil
    }

    /// "mark next friday down as the interview date" — a whole day, named.
    static func readMarkDay(_ ask: String, low: String, now: Date, cal: Calendar) -> Action? {
        let low = low.replacingOccurrences(of: #"^(?:put|place|add|set) (?:a |an )?(?:marker|marking|flag|note|pin) (?:on|for)\s+"#,
                                           with: "mark ", options: .regularExpression)
        let ask = low == ask.lowercased() ? ask : low
        guard let m = match(#"^(?:mark|note|put|keep|save|block|label)\s+(?:on\s+)?(.+?)\s+(?:down\s+)?(?:as|for)\s+(.+?)(?:\s+on (?:my|the) calendar)?$"#, low),
              let when = group(m, 1, in: ask), let what = group(m, 2, in: ask) else { return nil }
        let span = DateParse.find(when, now: now, cal: cal)
        guard let d = span.date, cleanTitle(blank(when, span.ranges)).isEmpty else { return nil }
        var a = Action(op: .create, kind: .event, title: cleanTitle(what))
        a.date = d
        a.allDay = span.start == nil
        a.start = span.start
        if let s = span.start { a.end = DateParse.addMinutes(s, 60) }
        return a.title.isEmpty ? nil : a
    }

    // MARK: Query

    static func readQuery(_ ask: String, low: String, now: Date, cal: Calendar) -> Action? {
        let cue = #"^(?:what(?:'s| is| do i have| have i got|'ve i got| are| am i)|what's on|what is on|do i have (?:anything|any|something)|"# +
            #"how (?:busy|free|full|packed) (?:is|am|are)|am i (?:busy|free)|what (?:tasks|events|meetings|appointments|to-?dos|plans|reminders|things)|summari[sz]e|recap|brief me|give me (?:a |an )?(?:rundown|overview|summary)|how many|how much|(?:can you |could you )?check what|(?:can you |could you )?tell me what|when(?:'s| is| am i| do i)|where(?:'s| is| am i)|is (?:my|the)|are there|any (?:events|tasks|to-?dos|plans)|"# +
            #"am i (?:free|busy)|is there anything|anything (?:on|planned)|show me|list|read me|tell me (?:what|about)|"# +
            #"how(?:'s| does| is) my|what does my|check (?:my|if)|i don't think i have)"#
        // A QUESTION is a query however it is put: "when is my next appointment",
        // "is it someone's birthday today?", "give me the reminders" — unless it
        // is a request phrased as one ("will you put…", "can you add…").
        let request = #"^(?:will|would|could|can|won't) you\b|^(?:can|could|may) i (?:add|schedule|book|set|make|put|create)\b"#
        let asks = low.hasSuffix("?") ||
            low.range(of: #"^(?:is|are|do|does|did|when|what|where|who|which|how|am|have i|has|was|were|any)\b"#, options: .regularExpression) != nil ||
            low.range(of: #"^(?:give me|show me|read me|list|tell me|let me see|let me know|bring up|pull up|open|check)\b.*\b(?:reminders?|events?|schedule|calendar|agenda|appointments?|meetings?|list|to-?dos?|tasks?|plans?)\b"#,
                      options: .regularExpression) != nil
        let creates = low.range(of: #"\b(?:add|schedule|book|set up|create|put|remind me|make)\b"#, options: .regularExpression) != nil
            && low.range(of: request, options: .regularExpression) != nil
        guard low.range(of: cue, options: .regularExpression) != nil || (asks && !creates
              && low.range(of: request, options: .regularExpression) == nil) else { return nil }
        // "do i have anything … and if not book X" was split already; a
        // question that is really a create ("what if we book…") is rare.
        var a = Action(op: .query, kind: low.contains("to do") || low.contains("to-do") || low.contains("task") ? .todo : .event)
        let span = DateParse.find(ask, now: now, cal: cal)
        a.date = span.date ?? DateParse.iso(now, cal)
        a.rangeEnd = span.rangeEnd
        return a
    }

    // MARK: Delete / complete / rename / move

    static let rowWords = #"(?:the |my |that |this |our )?"#

    static func readDelete(_ ask: String, low: String, now: Date, cal: Calendar) -> Action? {
        let re = #"^(?:delete|remove|cancel|clear|scrap|drop|get rid of|take off|take|erase|forget(?: about)?|strike|wipe|scratch|axe|"# +
            #"call off|nix|kill|ditch|unschedule|i (?:don't|do not|no longer) need)\s+(.+)$"#
        guard let m = match(re, low), let body = group(m, 1, in: ask) else { return nil }
        // "cancel my 3pm" / "delete the dentist tomorrow" / "remove milk from my list"
        var a = Action(op: .delete, kind: .event)
        let cleaned = body.replacingOccurrences(of: #"\s+(?:off|from)\s+(?:my|the)\s+(?:calendar|schedule|list|agenda)\b.*$|\s+off$"#, with: "",
                                               options: [.regularExpression, .caseInsensitive])
        let (found0, date, isTodo0) = targetOf(cleaned, now: now, cal: cal)
        let isTodo = isTodo0 || body.lowercased().range(of: #"\b(?:from|off) (?:my |the )?(?:[\w-]+ )?(?:list|to-?do|tasks?)\b"#, options: .regularExpression) != nil
        var target = found0.replacingOccurrences(of: #"^to\s+|,?\s*so\s+(?:delete|remove|drop|cancel)\s+it\b.*$|,?\s*(?:delete|remove|drop|cancel)\s+it\b.*$"#,
                                                 with: "", options: [.regularExpression, .caseInsensitive])
        if let r = target.range(of: #"^(?:reminder|note|task|to-?do)\s+(?:to|about|for)\s+"#, options: [.regularExpression, .caseInsensitive]) {
            target = String(target[r.upperBound...]); a.kind = .todo   // "remove my reminder to call X"
        }
        // a deadline is a task to DO, not a row to delete: "cancel the subscription by saturday"
        if low.range(of: #"\bby\s+(?:this|next|the|tomorrow|today|monday|tuesday|wednesday|thursday|friday|saturday|sunday|end)\b"#, options: .regularExpression) != nil {
            return nil
        }
        a.target = target            // "" for "delete this reminder": the executor asks which
        if !isTodo && looksLikeTask(target) { a.kind = .todo }
        a.targetDate = date?.date
        a.start = date?.start
        a.kind = isTodo ? .todo : .event
        return a
    }

    static func readComplete(_ ask: String, low: String, now: Date, cal: Calendar) -> Action? {
        let pats = [
            #"^(?:mark|set|flag)\s+(.+?)\s+(?:as\s+)?(?:done|complet(?:e|ed)?|finished|checked off)(?:\s*[,;].*)?$"#,
            #"^(?:i'm|im|i am) (?:done|finished) with\s+(.+)$"#,
            #"^(?:tick|check|cross|strike)\s+(.+?)\s+off\b.*$"#,
            #"^(?:yeah\s+|yes\s+|ok\s+)?(?:check off|tick off|cross off|complete|finish|finished|completed|done with|"# +
            #"i(?:'ve| have)? (?:already )?(?:finished|completed|done|did|handled|took care of|sorted|paid|bought|sent|called)|"# +
            #"i already|already did|i did|got)\s+(.+?)(?:\s+(?:already|today|now))?$"#,
            #"^(?:yeah\s+|yes\s+)?(.+?)\s+(?:is|are|was|were|got|has been|have been)\s+(?:done|finished|complete|completed|taken care of|sorted|handled)$"#,
            #"^(.+?)\s+(?:is|are)\s+(?:done|finished|complete|completed)$"#,
        ]
        for p in pats {
            guard let m = match(p, low), let body = group(m, 1, in: ask) else { continue }
            let (target, date, _) = targetOf(body, now: now, cal: cal)
            guard !target.isEmpty else { return nil }
            var a = Action(op: .complete, kind: .todo)
            a.target = target
            a.targetDate = date?.date
            return a
        }
        return nil
    }

    static func readRename(_ ask: String, low: String) -> Action? {
        let pats: [(String, Bool)] = [
            (#"^rename\s+(.+?)\s+(?:to|as)\s+(.+)$"#, false),
            (#"^change the (?:name|title) of\s+(.+?)\s+to\s+(.+)$"#, false),
            (#"^call (?:it|that)\s+(.+?)\s+instead of\s+(.+)$"#, true),
            (#"^(?:change|switch|replace)\s+['"](.+?)['"]\s+(?:to|with|for)\s+(.+)$"#, false),
            (#"^call\s+(.+?)\s+(.+)\s+instead$"#, false)]
        for (p, flipped) in pats {
            guard let m = match(p, low), var from = group(m, 1, in: ask), var to = group(m, 2, in: ask) else { continue }
            if flipped { swap(&from, &to) }
            var a = Action(op: .update, kind: .event)
            a.target = cleanTarget(from)
            a.newTitle = cleanTitle(to)
            if looksLikeTask(a.target ?? "") || looksLikeTask(a.newTitle ?? "") || low.contains("list") || low.contains("task") { a.kind = .todo }
            return a
        }
        return nil
    }

    /// "update feed the cat", "change my dentist appointment", "edit X" — an
    /// edit with nothing said about what changes: the row, and the question.
    static func readBareUpdate(_ ask: String, low: String) -> Action? {
        guard let m = match(#"^(?:update|edit|modify|amend|change (?:that|this|my|the (?:appointment|meeting|event|reminder|task|entry)))\s*(.*)$"#, low),
              let body = group(m, 1, in: ask) else { return nil }
        let isTodo = low.range(of: #"\b(?:list|to-?do|task)\b"#, options: .regularExpression) != nil
        var a = Action(op: .update, kind: isTodo ? .todo : .event)
        a.target = cleanTarget(body.replacingOccurrences(of: #"\s*\b(?:on|from|in)\s+(?:my|the)\s+(?:list|to-?do list|calendar)\b.*$"#,
                                                         with: "", options: [.regularExpression, .caseInsensitive]))
        if looksLikeTask(a.target ?? "") { a.kind = .todo }
        return a.target?.isEmpty == false ? a : nil
    }

    static func readMove(_ ask: String, low: String, now: Date, cal: Calendar) -> Action? {
        let low = low.replacingOccurrences(of: #"^(?:push|move|bump|bring|pull) (?:back|forward|up|out)\s+"#, with: "move ", options: .regularExpression)
            .replacingOccurrences(of: #"^set the (?:due )?date (?:for|of)\s+"#, with: "change the due date of ", options: .regularExpression)
        let ask = low.count == ask.count ? ask : low
        let verb = #"^(?:move|re-?sched(?:ule|ual|ul|eul)|resh?edule|push|postpone|defer|shift|bump|bring|pull|change|switch|"# +
            #"update|delay|put off|extend|shorten|rebook|re-book)\s+"#
        guard low.range(of: verb, options: .regularExpression) != nil else { return nil }
        // "shorten X to two hours" / "make X 90 minutes": the LENGTH is set
        if let m = match(#"^(?:extend|lengthen|shorten|cut|make|change)\s+(.+?)\s+(?:to|last|into)\s+(an?|one|two|three|four|half an|\d+)\s*(hours?|hrs?|minutes?|mins?)(?:\s+long)?$"#, low)
            ?? match(#"^make\s+(.+?)\s+(an?|one|two|three|four|half an|\d+)\s*(hours?|hrs?|minutes?|mins?)\s+long$"#, low),
           let target = group(m, 1, in: ask) {
            let q = group(m, 2, in: low) ?? "1", u = group(m, 3, in: low) ?? "hour"
            var a = Action(op: .update, kind: .event)
            a.target = cleanTarget(target)
            a.lengthMinutes = q.hasPrefix("half") ? 30 : DateParse.number(q) * (u.hasPrefix("h") ? 60 : 1)
            return a
        }
        // "extend X by 30 minutes" / "shorten X by an hour": the END moves
        if let m = match(#"^(extend|lengthen|shorten|cut)\s+(.+?)\s+by\s+(an?|one|two|half an|\d+)\s*(hours?|hrs?|minutes?|mins?)\b"#, low),
           let target = group(m, 2, in: ask) {
            let q = group(m, 3, in: low) ?? "1", u = group(m, 4, in: low) ?? "hour"
            var minutes = q.hasPrefix("half") ? 30 : DateParse.number(q) * (u.hasPrefix("h") ? 60 : 1)
            if let v = group(m, 1, in: low), v == "shorten" || v == "cut" { minutes = -minutes }
            var a = Action(op: .update, kind: .event)
            a.target = cleanTarget(target)
            a.extendMinutes = minutes
            return a
        }
        // "push X back an hour", "bring X forward by 30 minutes"
        if let m = match(verb + #"(.+?)\s+(back|forward|later|earlier|up)\s+(?:by\s+)?(an?|one|two|three|half an|\d+)\s*(hours?|hrs?|minutes?|mins?|days?)?$"#, low),
           let target = group(m, 1, in: ask) {
            let dir = group(m, 2, in: low) ?? "back"
            let qty = group(m, 3, in: low) ?? "1"
            let unit = group(m, 4, in: low) ?? "hour"
            var minutes = DateParse.number(qty) * (unit.hasPrefix("h") ? 60 : unit.hasPrefix("d") ? 1440 : 1)
            if qty.hasPrefix("half") { minutes = 30 }
            if ["forward", "earlier", "up"].contains(dir) { minutes = -minutes }
            var a = Action(op: .update, kind: .event)
            a.target = cleanTarget(target)
            a.shiftMinutes = minutes
            return a
        }
        // "move X to friday at 3" / "reschedule X for tomorrow" / "change X to 4pm"
        let m = match(verb + #"(.+?)\s+(?:back\s+|forward\s+|up\s+)?(?:to|for|until|till|on|at|into)\s+(.+)$"#, low)
        guard let m, let target = group(m, 1, in: ask), let rest = group(m, 2, in: ask) else { return nil }
        let when = DateParse.find(rest, now: now, cal: cal)
        guard when.date != nil || when.start != nil else { return nil }
        var a = Action(op: .update, kind: .event)
        let dueOf = target.range(of: #"^(?:the )?due date (?:of|for)\s+"#, options: [.regularExpression, .caseInsensitive])
        let named = dueOf.map { String(target[$0.upperBound...]) } ?? target
        let (t, tdate, isTodo) = targetOf(named, now: now, cal: cal)
        a.target = t
        a.targetDate = tdate?.date
        a.kind = isTodo || looksLikeTask(named) || dueOf != nil ? .todo : .event
        a.date = when.date
        a.start = when.start
        a.end = when.end
        return a
    }

    /// The words naming a row, minus the day said with them; and whether the
    /// words say it is on a LIST ("milk from my shopping list").
    static func targetOf(_ body: String, now: Date, cal: Calendar) -> (String, DateParse.Span?, Bool) {
        let low = body.lowercased()
        let isTodo = low.range(of: #"\b(?:from|off|on) (?:my |the )?(?:[\w-]+ )?(?:list|to-?do(?:s| list)?|tasks?)\b|\btask\b|\bto-?do\b"#,
                               options: .regularExpression) != nil
        var b = body.replacingOccurrences(of: #"\s*\b(?:from|off|on|in)\s+(?:my |the )?(?:[\w-]+ )?(?:list|to-?do(?:s| list)?|tasks?|calendar|schedule)\b.*$"#,
                                          with: "", options: [.regularExpression, .caseInsensitive])
        let span = DateParse.find(b, now: now, cal: cal)
        b = blank(b, span.ranges)
        return (cleanTarget(b), (span.date != nil || span.start != nil) ? span : nil, isTodo)
    }

    /// A to-do is said as something to DO ("restock the pantry"); an event as a
    /// thing ("budget review"). The row lookup searches both kinds anyway; this
    /// is which it tries first.
    static let taskVerbs: Set<String> = ["take", "pay", "buy", "mail", "order", "review", "organize", "organise", "wash",
        "charge", "sign", "pick", "print", "water", "feed", "clean", "back", "confirm", "update", "submit", "send",
        "call", "email", "text", "finish", "return", "renew", "book", "file", "fix", "get", "grab", "write", "read",
        "prepare", "prep", "restock", "refill", "cancel", "schedule", "replace", "drop", "walk", "vacuum", "do",
        "make", "check", "reply", "respond", "pack", "unpack", "change", "clear", "empty", "fold", "iron", "mow",
        "plan", "research", "study", "practice", "practise", "finish", "transfer", "deposit", "apply", "register",
        "sort", "tidy", "wrap", "bake", "cook", "shop", "collect", "deliver", "post", "upload", "download", "install",
        "backup", "message", "remind", "follow", "set", "put", "bring", "throw", "recycle", "donate", "sell"]

    static func looksLikeTask(_ target: String) -> Bool {
        // "the call with Robin" is a thing; "call Robin" is a thing to do
        guard let first = target.lowercased().split(separator: " ").first,
              !["the", "my", "that", "this", "our", "a", "an"].contains(String(first)) else { return false }
        return taskVerbs.contains(String(first))
    }

    static func cleanTarget(_ s: String) -> String {
        var t = s.replacingOccurrences(of: #"^(?:the |my |that |this |our |a |an )+"#, with: "",
                                       options: [.regularExpression, .caseInsensitive])
        t = t.replacingOccurrences(of: #"\b(?:event|appointment|meeting entry|reminder|task|to-?do|item|entry|thing)$"#,
                                   with: "", options: [.regularExpression, .caseInsensitive])
        t = t.replacingOccurrences(of: #"\s+(?:at|on|for|from|to|in)$"#, with: "", options: [.regularExpression, .caseInsensitive])
        return t.trimmingCharacters(in: CharacterSet(charactersIn: " .,'\""))
    }

    // MARK: Create

    static func readCreate(_ ask: String, now: Date, cal: Calendar) -> Action? {
        let low0 = ask.lowercased()
        // The series and the date come out FIRST, so an opener said after them
        // is found: "friday, i need to water the garden", "every week i have yoga".
        let rec = Recurrence.find(ask, now: now, cal: cal)
        let rest = blank(ask, rec.ranges)
        let span = DateParse.find(rest, now: now, cal: cal)
        var body = blank(rest, span.ranges).trimmingCharacters(in: CharacterSet(charactersIn: " ,.;:-?!"))
        body = body.replacingOccurrences(of: #"^(?:so yeah|so|yeah|ok|okay|and|also|then|alright)[,]?\s+"#, with: "",
                                         options: [.regularExpression, .caseInsensitive])
        // The verb that opens a create, and what it says about the kind.
        var listCue = false, calendarCue = false, reminderCue = false, verbSaid = ""
        let opener = createOpener
        // "get X on the calendar", "mark X on my calendar for …"
        body = body.replacingOccurrences(of: #"^(?:get|mark|pop|stick|throw|jot|chuck|pencil)\s+(?=.+\b(?:on|in|onto|into)\s+(?:my |the )?(?:calendar|books|diary|agenda|schedule)\b)"#,
                                         with: "put ", options: [.regularExpression, .caseInsensitive])
        for _ in 0..<2 {
            guard let r = body.range(of: opener, options: [.regularExpression, .caseInsensitive]) else { break }
            let verb = body[r].lowercased()
            reminderCue = reminderCue || verb.contains("remind") || verb.contains("forget") || verb.contains("remember") || verb.contains("make sure")
            calendarCue = calendarCue || ["schedule", "book", "set up", "plan", "arrange", "pencil", "block", "reserve", "keep", "circle",
                                          "attend", "go to", "going to", "calendar entry", "entry for", "sign me up", "enroll",
                                          "register", "i'll be at", "i will be at", "put me down", "put me in", "lock in", "slot in",
                                          "attending", "be at", "invited", "booking", "reservation", "new event"].contains { verb.contains($0) }
            listCue = listCue || verb.hasPrefix("to") || verb.hasPrefix("task") || verb.contains("a task")
                || verb.range(of: #"\b(?:need(?! to)|get|buy|out of|low on|running)\b"#, options: .regularExpression) != nil
            if verbSaid.isEmpty { verbSaid = String(body[r]) }
            body.removeSubrange(r)
        }
        // "… to my to-do list" / "on my shopping list" / "to the calendar" / ", put it on the calendar"
        var listName: String? = nil
        if let m = match(#",?\s*\b(?:(?:and )?(?:please )?(?:put|add|get) it|and i need it)?\s*(?:to|on|onto|in|into)\s+(?:(?:my|the|our)\s+)?([\w' -]+?\s+)?(list|to-?do(?:s| list)?|tasks?|calendar|schedule|agenda|diary|books)\b.*$"#, body.lowercased()) {
            let named = group(m, 1, in: body.lowercased())?.trimmingCharacters(in: .whitespaces)
            let what = group(m, 2, in: body.lowercased()) ?? ""
            if ["calendar", "schedule", "agenda", "diary", "books"].contains(what) {
                calendarCue = true
            } else {
                listCue = true
                if let named, !named.isEmpty, !["to-do", "todo", "to do"].contains(named) { listName = named }
            }
            if let r = Range(m.range, in: body) { body.removeSubrange(r) }
        }
        body = body.replacingOccurrences(of: #",?\s*(?:please\s+)?(?:to\s+)?add it\b.*$|\s+needs (?:doing|to be done|to happen)\b"#, with: "",
                                         options: [.regularExpression, .caseInsensitive])
        let title = cleanTitle(body)
        guard !title.isEmpty else { return nil }

        var a = Action(op: .create, kind: .todo, title: title)
        a.recurrence = rec.cadence
        a.recurDays = rec.days
        a.recurrenceEnd = rec.until
        a.notes = rec.notes
        let tlow = title.lowercased()
        let written = tlow.range(of: #"^(?:email|e-mail|text|message|msg|write(?: to)?|send|reply to|respond to|dm|whatsapp|mail|letter)\b"#,
                                 options: .regularExpression) != nil
        let person = Persons.isPerson(title) && !written
        let call = tlow.range(of: #"^(?:call|phone|ring|facetime|video ?call|zoom with)\b"#, options: .regularExpression) != nil
        let meet = tlow.range(of: #"^(?:meet(?:ing)?|see|visit|catch up|lunch|dinner|breakfast|brunch|coffee|drinks|date|hang ?out|play ?date|speak|talk|sync|1[:-]1|one[- ]on[- ]one)\b"#,
                              options: .regularExpression) != nil
            || tlow.range(of: #"\bwith\s+[A-Z]"#, options: .regularExpression) != nil
            || title.range(of: #"\bwith\s+[A-Z]"#, options: .regularExpression) != nil

        let leadCue = low0.contains("leadcue")
            || low0.range(of: #"\b(?:an event|a meeting|an appointment|a calendar (?:event|entry))\b"#, options: .regularExpression) != nil
        let invite = low0.range(of: #"\binvite\b|\band invite\b|\bwith (?:the )?(?:team|everyone|family)\b"#, options: .regularExpression) != nil
        // THE KIND (Q25/Q26/Q47/Q50/Q61)
        if rec.cadence != nil {
            a.kind = .event                                       // Q61: a repeating to-do is an event series
        } else if listCue && span.start == nil {
            a.kind = .todo
        } else if verbSaid.lowercased().hasPrefix("block") && looksLikeTask(title) && span.start == nil {
            a.kind = .todo                                        // "block out friday to back up the laptop": a task that day
        } else if span.start != nil || span.allDay || rec.cadence != nil {
            a.kind = .event                                       // a clock, a range, all-day, a series
        } else if (meet || person) && span.date != nil {
            a.kind = .event                                       // Q47: a person on a day
            a.start = "09:00"
        } else if call && span.date != nil {
            a.kind = .event                                       // Q50: a live call on a day
            a.start = "09:00"
            a.linkedTodo = !Persons.isPerson(title)
        } else if leadCue || invite {
            a.kind = .event                                       // a reminder before it, or guests: it has a time
            a.start = "09:00"
        } else if calendarCue && span.date != nil && !reminderCue {
            a.kind = .event
            a.allDay = true                                       // "book the venue friday": on the calendar, no clock
        } else {
            a.kind = .todo
        }
        if listCue && a.kind == .todo { a.list = listName }
        // "i need to schedule a haircut" with no day is a to-do to SCHEDULE one:
        // the verb is the task (FastRule's reading too)
        if a.kind == .todo, calendarCue, !listCue,
           ["schedule", "book", "plan", "arrange", "set up", "organize", "organise"].contains(where: { verbSaid.lowercased().hasPrefix($0) }) {
            a.title = cleanTitle(verbSaid + " " + body)
        }
        // a count in a to-do is its quantity, not its title
        if a.kind == .todo, let m = match(#"^((?:\w+\s+){0,2}?)(two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|half a dozen|a dozen|a few|a couple(?: of)?|\d{1,3})\s+(?=[a-z])"#, a.title.lowercased()) {
            let n = group(m, 2, in: a.title.lowercased()) ?? ""
            let q = n == "a dozen" ? 12 : n == "half a dozen" ? 6 : n == "a few" ? 3 : n.hasPrefix("a couple") ? 2
                : Int(n) ?? DateParse.numberWords[n] ?? 1
            if q > 1, let r = Range(m.range(at: 2), in: a.title) {
                a.quantity = q
                a.title = a.title.replacingCharacters(in: r, with: "").replacingOccurrences(of: "  ", with: " ")
            }
        }

        if a.kind == .event {
            a.date = span.date ?? rec.firstDate ?? DateParse.iso(now, cal)
            if a.start == nil { a.start = span.start }
            a.end = span.end
            a.allDay = a.allDay || (span.allDay && span.start == nil)
            if a.start == nil && !a.allDay {
                // a series said with no clock ("remind me to feed the cat once a
                // week"): the morning, like a person with no clock (Q47)
                a.start = "09:00"
            }
            if let s = a.start, a.end == nil, !a.allDay {
                a.end = DateParse.addMinutes(s, span.durationMinutes ?? 60)
            }
            if rec.cadence != nil, a.recurrenceEnd == nil, let d = a.date {
                a.recurrenceEnd = Recurrence.defaultEnd(from: d, cadence: rec.cadence!, cal: cal)   // Q57
                a.notes.append("default-end")
            }
        } else {
            a.date = span.date            // a to-do's due date, if a day was said
            if a.list == nil {
                a.list = (span.date == nil || span.date == DateParse.iso(now, cal)) ? "today" : "general"
            }
        }
        return a
    }


    /// Everything that can open a create, as regex fragments. Built LONGEST
    /// FIRST: an alternation takes its first match, and "make" before "make
    /// sure i" left "sure i refill the prescription" as a title.
    static let openerPhrases: [String] = [
        "add", "create", "make", "put", "schedule", "book(?! (?:club|fair|signing|launch|reading|sale|shop|store)\\b)",
        "set up", "set", "plan", "arrange", "log", "note", "pencil in", "block(?: out| off)?", "reserve", "enter",
        "insert", "save", "jot down", "jot", "write down(?: that)?", "new", "new event", "new reminder (?:to|for|about)",
        "i have to", "i have", "i've got", "i got", "there's", "there is", "i'm", "i am", "we have", "we've got",
        "remind me (?:to|about|of|that)", "remember me to", "(?:add |a )?reminder (?:to|for|about)",
        "set a reminder (?:to|for|about)", "don't let me forget (?:to|about)", "don't forget (?:to|about|the|that)?(?: i have)?",
        "remember to", "to-?do:?", "todo:?", "task:?", "to do,?", "reminder:?", "note:", "make a to-?do to",
        "put down", "put me down for", "put me in for", "put in", "add a task to", "chuck", "pop", "stick", "throw",
        "keep(?: \\S+)? (?:clear|free|open) for", "circle(?: \\S+)?(?: on (?:my|the) calendar)? for",
        "i go to", "i'm going to", "i am going to", "i need to attend", "i'm attending", "i am attending", "attending",
        "attend", "go to", "i need to be at", "i have to be at", "i got invited to", "i'm invited to", "i was invited to",
        "make a calendar entry for", "make an entry for", "make a booking for", "make a reservation for",
        "sign me up for", "enroll me in", "register me for", "i'll be at", "i will be at", "lock in", "schedule in",
        "slot in", "fit in", "please to add", "please add",
        "remind me that i need to", "remind me that i have to", "help me remember to", "make sure (?:i|to)",
        "i must remember to", "i must", "i(?: still)? need to", "i(?:'ve| have)? gotta", "i'm supposed to",
        "i am supposed to", "supposed to", "i keep forgetting to",
        "(?:i )?(?:mustn't|must not|can't|cannot|shouldn't) forget (?:to|about|the)",
        "we need(?: more| some| to get| to buy)?", "i need(?: more| some)", "need more", "get more", "get some",
        "we should get", "we should buy",
        "(?:we're|we are|i'm|i am)? ?(?:almost|nearly|completely|totally)? ?out of",
        "(?:we're|we are|i'm|i am)? ?running (?:low|out) (?:on|of)", "(?:we're|we are) low on", "low on",
        "buy some", "pick up some", "is", "don't forget (?:that )?i have", "remember that i have", "remember i have",
        "i'm booked in for", "i am booked in for", "i'm booked for", "book me in for", "book me for", "save the date for",
        "hold(?: some)? time for", "hold", "log a task to", "log", "shopping list:", "grocery list:", "to-do list:",
        "i want to", "i'd like to", "i would like to", "mark",
    ]
    static let createOpener: String = {
        let alts = openerPhrases.sorted { $0.count > $1.count }.joined(separator: "|")
        return "^(?:(?:please\\s+)?(?:" + alts + ")\\s+)"
    }()

    /// The title: what is left once the verb, the time and the list are gone.
    static func cleanTitle(_ s: String) -> String {
        var t = s
        let drop = [
            #"\bleadcue\b"#,
            #"^(?:an? |the )?(?:event|appointment|reminder|calendar entry|entry|task|to-?do|block|slot|time)\s+(?:for|called|named|titled|about|to)\s+"#,
            #"^invite\s+.+?\s+to\s+"#, #"\s+and invite\s+.+$"#, #"\s+and (?:let|tell|notify|email|text|ping)\s+\S+\s+know\b.*$"#,
            #"^block (?:out |off )?(?:my |the )?(?:whole |entire )?(?:calendar |day |time )?(?:for )?"#,
            #"^(?:get|put|add)\s+(?=.+\bon\s+(?:my|the)\s+calendar\b)"#,
            #"\s+takes\b"#, #"\s+(?:is happening|is set for|is set|is on|is scheduled(?: for)?|is booked(?: for)?|coming up|is coming up|is going to be|is gonna be|will be|is planned(?: for)?)\b"#,
            #",?\s*(?:put it down|ping me|remind me|let me know)(?: for)?\s*$"#,
            #"\s+as a (?:task|to-?do|reminder)\b"#, #"^(?:i have|i've got|there's)\s+"#, #"^(?:my |the )?(?:whole |entire )?(?:calendar|day|afternoon|morning)\s+(?:for\s+)?"#,
            #"\s+from the (?:store|shop|supermarket|market|pharmacy)\b"#,
 #"(?:^|\s)(?:at\s+)?first thing(?:\s+in the morning)?\b"#,
            #"(?:^|\s),?\s*including\b.*$"#,
            #"\s+(?:\d+|an?|one|two|five|ten|fifteen|thirty)\s*(?:minutes?|mins?|hours?|hrs?|days?|weeks?)\s+(?:before(?:hand)?|ahead|early|in advance)\b.*$"#,
            #"\b(?:called|named|titled)\s+"#,
            #"\b(?:on|to|in|onto|into)\s+(?:my|the)\s+(?:calendar|schedule|agenda|diary)\b"#,
            #"\b(?:for|on)\s+me\b"#,
            #"\b(?:sometime|some time|at some point|asap|as soon as possible|when i can|if possible|please)\b"#,
            #"\baround\b$"#, #"\babout\b$"#,
        ]
        for p in drop { t = t.replacingOccurrences(of: p, with: " ", options: [.regularExpression, .caseInsensitive]) }
        // an attendee said with "for": "client call for Cameron" (case matters: a Name)
        t = t.replacingOccurrences(of: #"^((?!(?:a|an|the)\s)\S+\s+\S+.*?)(?<!table|reservation|booking|room|seat|seats|spot|tickets|ticket)\s+for\s+[A-Z][a-z]+(?:\s+and\s+[A-Z][a-z]+)?(?=\s*$|\s+(?:on|at|this|next|tomorrow|today)\b)"#,
                                   with: "$1", options: .regularExpression)
        t = t.replacingOccurrences(of: #"\s+(?:to discuss|to talk about|to go over|regarding|re:?)\s+"#, with: " about ",
                                   options: [.regularExpression, .caseInsensitive])
        t = t.replacingOccurrences(of: #"\s+"#, with: " ", options: .regularExpression)
        // dangling joiners left where a time was cut out: "lunch with Dana at" → "lunch with Dana"
        var prev = ""
        while prev != t {
            prev = t
            t = t.trimmingCharacters(in: CharacterSet(charactersIn: " ,.-;:!?"))
            t = t.replacingOccurrences(of: #"(?:^|\s)(?:at|on|for|from|by|in|to|and|the|this|next|starting|until|till|every|around|about|of|between|before|after|due|is|as)$"#,
                                       with: "", options: [.regularExpression, .caseInsensitive])
            t = t.replacingOccurrences(of: #"^(?:a|an|to|for|on|at|that|about|of)\s+"#, with: "",
                                       options: [.regularExpression, .caseInsensitive])
        }
        return t.trimmingCharacters(in: CharacterSet(charactersIn: " ,.-;:!?\"'"))
    }

    // MARK: - Pointing at a row

    enum Match { case one(Row), many([Row]), none }

    /// The row a target names: every content word of the target must be in the
    /// title (a word may be a prefix of one — "dentist" names "dentist
    /// appointment"); a day said with it must be the row's day. Ties are
    /// `.many` — a destructive act on a guess is the one thing not to do.
    static func find(_ target: String, date: String?, start: String?, kind: Kind?, in rows: [Row]) -> Match {
        let want = contentWords(target)
        var pool = rows.filter { kind == nil || $0.kind == kind! }
        if let date { pool = pool.filter { $0.date == date } }
        if let start { pool = pool.filter { $0.start == start } }
        if want.isEmpty {
            // "cancel my 3pm", "delete tomorrow's" — the time is the name
            guard date != nil || start != nil else { return .none }
            return pool.count == 1 ? .one(pool[0]) : pool.isEmpty ? .none : .many(pool)
        }
        var scored: [(Row, Double)] = []
        for r in pool {
            let have = contentWords(r.title)
            let hits = want.filter { w in have.contains { $0 == w || $0.hasPrefix(w) || w.hasPrefix($0) && $0.count >= 4 } }
            guard hits.count == want.count else { continue }
            scored.append((r, Double(hits.count) / Double(max(have.count, 1))))
        }
        guard let best = scored.max(by: { $0.1 < $1.1 }) else { return .none }
        let top = scored.filter { abs($0.1 - best.1) < 0.0001 }.map(\.0)
        if top.count == 1 { return .one(top[0]) }
        // the same title on several days: the soonest still to come is meant
        let undone = top.filter { !$0.done }
        if undone.count == 1 { return .one(undone[0]) }
        return .many(top)
    }

    static let stop: Set<String> = ["the", "a", "an", "my", "our", "this", "that", "to", "for", "with", "on", "at", "of",
                                    "in", "and", "event", "appointment", "task", "todo", "to-do", "reminder", "item"]

    static func contentWords(_ s: String) -> [String] {
        s.lowercased().components(separatedBy: CharacterSet.alphanumerics.inverted)
            .filter { !$0.isEmpty && !stop.contains($0) }
            .map { $0.hasSuffix("s") && $0.count > 3 ? String($0.dropLast()) : $0 }
    }

    // MARK: - Regex helpers

    /// `s` with each range (made ON `s`) blanked to spaces — by UTF-16 offset,
    /// so the ranges stay valid however many are cut. Spaces, not removal, so
    /// "lunch at 1 with Dana" never fuses two words.
    static func blank(_ s: String, _ ranges: [Range<String.Index>]) -> String {
        let ns = NSMutableString(string: s)
        for r in ranges.map({ NSRange($0, in: s) }).sorted(by: { $0.location > $1.location })
        where r.location != NSNotFound && r.location + r.length <= ns.length {
            ns.replaceCharacters(in: r, with: String(repeating: " ", count: r.length))
        }
        return (ns as String).replacingOccurrences(of: #"\s+"#, with: " ", options: .regularExpression)
    }

    static func match(_ pattern: String, _ s: String) -> NSTextCheckingResult? {
        guard let re = try? NSRegularExpression(pattern: pattern, options: [.caseInsensitive]) else { return nil }
        return re.firstMatch(in: s, range: NSRange(s.startIndex..., in: s))
    }

    /// Group `i` of a match made on `low`, cut from `original` (same length,
    /// so a title keeps its capitals).
    static func group(_ m: NSTextCheckingResult, _ i: Int, in original: String) -> String? {
        guard i < m.numberOfRanges, m.range(at: i).location != NSNotFound,
              let r = Range(m.range(at: i), in: original) else { return nil }
        let g = String(original[r]).trimmingCharacters(in: .whitespaces)
        return g.isEmpty ? nil : g
    }
}

// MARK: - People

enum Persons {
    static let family: Set<String> = ["mom", "mum", "mommy", "mother", "dad", "daddy", "father", "grandma", "grandpa",
                                      "granny", "nana", "papa", "sister", "brother", "sis", "bro", "wife", "husband",
                                      "son", "daughter", "aunt", "uncle", "cousin", "boss", "friend", "partner",
                                      "girlfriend", "boyfriend", "fiance", "fiancee", "kids", "parents", "in-laws",
                                      "savta", "saba", "ima", "abba"]

    /// A person, not a role: a capitalised name after the verb, or a family word.
    static func isPerson(_ title: String) -> Bool {
        let words = title.split(separator: " ").map(String.init)
        guard words.count >= 2 else { return false }
        for w in words.dropFirst() {
            let bare = w.trimmingCharacters(in: .punctuationCharacters)
            if family.contains(bare.lowercased()) { return true }
            if let f = bare.first, f.isUppercase, bare.count > 1, bare.lowercased() != "i" { return true }
        }
        return false
    }
}

// MARK: - Dates and clocks

enum DateParse {

    struct Span {
        var date: String? = nil
        var start: String? = nil
        var end: String? = nil
        var allDay = false
        var durationMinutes: Int? = nil
        var rangeEnd: String? = nil
        var ranges: [Range<String.Index>] = []        // what to cut from the title
    }

    static let weekdays = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]
    static let months = ["january", "february", "march", "april", "may", "june", "july", "august", "september",
                         "october", "november", "december"]
    static let numberWords: [String: Int] = [
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
        "ten": 10, "eleven": 11, "twelve": 12, "a": 1, "an": 1, "half an": 30, "fifteen": 15, "twenty": 20,
        "thirty": 30, "forty five": 45, "forty-five": 45, "forty": 40, "fifty": 50, "couple": 2, "a couple of": 2,
    ]

    static func number(_ s: String) -> Int {
        Int(s) ?? numberWords[s.lowercased()] ?? 1
    }

    static func iso(_ d: Date, _ cal: Calendar) -> String {
        let c = cal.dateComponents([.year, .month, .day], from: d)
        return String(format: "%04d-%02d-%02d", c.year!, c.month!, c.day!)
    }

    static func addMinutes(_ hhmm: String, _ minutes: Int) -> String {
        let p = hhmm.split(separator: ":").compactMap { Int($0) }
        guard p.count == 2 else { return hhmm }
        let t = min(23 * 60 + 59, max(0, p[0] * 60 + p[1] + minutes))
        return String(format: "%02d:%02d", t / 60, t % 60)
    }

    // The clock: "5", "5pm", "5:30 pm", "17:00", "half past six", "quarter to
    // nine", "noon", "8 o'clock". A trailing word picks the half (bareHour).
    static let hourWords = ["one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
                            "nine": 9, "ten": 10, "eleven": 11, "twelve": 12]
    static let hw = "(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
    static let clockCore = #"(?:(?:half past|quarter past|quarter to|quarter till|(?:\d{1,2}|five|ten|twenty|twenty[- ]five) (?:minutes )?(?:past|to|after|before))\s+(?:\d{1,2}|"# + hw +
        #")|\d{1,2}(?::\d{2}|\.\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?|"# + hw + #"(?:\s+(?:thirty|fifteen|forty[- ]five|o'clock|oclock))?|noon|midday|midnight|lunchtime|lunch time)"#
    static let ampm = #"(?:\s*(?:a\.?m\.?|p\.?m\.?|o'clock|oclock|o clock|in the morning|in the afternoon|in the evening|at night|tonight))?"#

    static func clock(_ raw: String, context: String) -> String? {
        var s = raw.lowercased().trimmingCharacters(in: .whitespaces)
        s = s.replacingOccurrences(of: "around ", with: "").replacingOccurrences(of: "about ", with: "")
        if s == "noon" || s == "midday" { return "12:00" }
        if s.contains("lunch") { return "12:00" }
        if s == "midnight" { return "00:00" }
        var h = -1, m = 0
        for (w, n) in [("twenty-five", "25"), ("twenty five", "25"), ("twenty", "20"), ("ten", "10"), ("five", "5")] {
            s = s.replacingOccurrences(of: #"^"# + w + #"(?= (?:minutes )?(?:past|to|after|before) )"#, with: n, options: .regularExpression)
        }
        s = s.replacingOccurrences(of: " after ", with: " past ").replacingOccurrences(of: " before ", with: " to ")
        if let r = s.range(of: #"^(half past|quarter past|quarter to|quarter till|(\d{1,2}) (?:minutes )?(past|to))\s+(\S+)"#,
                           options: .regularExpression) {
            let piece = String(s[r])
            let parts = piece.split(separator: " ").map(String.init)
            let hourTok = parts.last!
            let base = Int(hourTok) ?? hourWords[hourTok] ?? -1
            guard base > 0 else { return nil }
            if piece.hasPrefix("half past") { h = base; m = 30 }
            else if piece.hasPrefix("quarter past") { h = base; m = 15 }
            else if piece.hasPrefix("quarter to") || piece.hasPrefix("quarter till") { h = base - 1; m = 45 }
            else if let n = Int(parts[0]) { if piece.contains(" past ") { h = base; m = n } else { h = base - 1; m = 60 - n } }
            if h == 0 { h = 12 }
        } else if let r = s.range(of: #"^(\d{1,2})(?:[:.](\d{2}))?"#, options: .regularExpression) {
            let piece = s[r]
            let nums = piece.split(whereSeparator: { $0 == ":" || $0 == "." }).compactMap { Int($0) }
            h = nums[0]; m = nums.count > 1 ? nums[1] : 0
        } else {
            let first = s.split(separator: " ").first.map(String.init) ?? ""
            guard let base = hourWords[first] else { return nil }
            h = base
            if s.contains("thirty") { m = 30 } else if s.contains("fifteen") { m = 15 } else if s.contains("forty") { m = 45 }
        }
        guard (0...23).contains(h), (0...59).contains(m) else { return nil }
        let both = (s + " " + context.lowercased())
        if s.range(of: #"p\.?m\.?"#, options: .regularExpression) != nil || s.contains("afternoon") || s.contains("evening")
            || s.contains("at night") || s.contains("tonight") {
            if h < 12 { h += 12 }
            return String(format: "%02d:%02d", h, m)
        }
        if s.range(of: #"a\.?m\.?"#, options: .regularExpression) != nil || s.contains("in the morning") {
            if h == 12 { h = 0 }
            return String(format: "%02d:%02d", h, m)
        }
        if h >= 13 || s.range(of: #"^\d{2}:\d{2}"#, options: .regularExpression) != nil && h >= 10 {
            return String(format: "%02d:%02d", h, m)
        }
        return bareHour(h, m, said: both)
    }

    /// `resolve._bare_hour`, the Mac's convention, so both read "gym at 5" alike.
    static func bareHour(_ h: Int, _ m: Int, said: String) -> String {
        let s = said.lowercased()
        func has(_ p: String) -> Bool { s.range(of: p, options: .regularExpression) != nil }
        let strongM = has(#"\b(?:morning|sunrise|dawn|shacharit|shachris|am|a\.m\.)\b"#)
        let strongE = has(#"\b(?:this evening|tonight|evening|pm|maariv|arvit)\b"#)
        let weakM = has(#"\bbreakfast\b"#), weakE = has(#"\b(?:dinner|supper|drinks)\b"#)
        let oclock = has(#"o'clock"#)
        func fmt(_ hh: Int) -> String { String(format: "%02d:%02d", hh, m) }
        if strongM && !strongE && (5...11).contains(h) { return fmt(h) }
        if strongE && !strongM && h < 12 { return fmt(h + 12) }
        if !(strongM || strongE) {
            if weakM && !weakE && (5...11).contains(h) { return fmt(h) }
            if weakE && !weakM && (5...9).contains(h) { return fmt(h + 12) }
        }
        if h >= 1 && h <= 6 { return fmt(h + 12) }
        if (7...8).contains(h) && !strongM && !oclock { return fmt(h + 12) }
        return fmt(h == 0 ? 0 : h)
    }

    /// Every date and clock the words name. The FIRST date and the FIRST clock
    /// (or range) win; their spans are returned so the title can drop them.
    static func find(_ text: String, now: Date, cal: Calendar) -> Span {
        var span = Span()
        let low = text.lowercased()
        let today = cal.startOfDay(for: now)
        func day(_ offset: Int) -> String { iso(cal.date(byAdding: .day, value: offset, to: today)!, cal) }
        func take(_ m: NSTextCheckingResult) { if let r = Range(m.range, in: text) { span.ranges.append(r) } }
        func all(_ p: String) -> [NSTextCheckingResult] {
            guard let re = try? NSRegularExpression(pattern: p, options: [.caseInsensitive]) else { return [] }
            return re.matches(in: low, range: NSRange(low.startIndex..., in: low))
        }
        func overlaps(_ m: NSTextCheckingResult) -> Bool {
            guard let r = Range(m.range, in: text) else { return true }
            return span.ranges.contains { $0.overlaps(r) }
        }

        // -- the one part of the day with a ruling (Gil, 2026-09-08): late afternoon is 5-7pm
        for m in all(#"\b(?:at |in the |this |tomorrow )?late afternoon\b"#) where span.start == nil {
            span.start = "17:00"; span.end = "19:00"; take(m)
        }
        // -- ranges and clocks first ("from 6 to 8", "between 2 and 4", "9-11")
        let rangeP = #"\b(?:from\s+|between\s+)?("# + clockCore + ampm + #")\s*(?:-|–|to|until|till|and)\s*("# + clockCore + ampm + #")"#
        for m in all(rangeP) where span.start == nil {
            let whole = (Range(m.range, in: low).map { String(low[$0]) }) ?? ""
            // a bare "5 to 6" with no from/between and no clock marks reads as a range only with a digit on each side
            guard whole.range(of: #"from|between|:|am|pm|\d\s*-\s*\d|o'clock|noon"#, options: .regularExpression) != nil else { continue }
            guard let a = LocalEngine.group(m, 1, in: low), let b = LocalEngine.group(m, 2, in: low),
                  var s = clock(a, context: low), var e = clock(b, context: low) else { continue }
            // "from 9 to 2:30" — the end's half follows the start when bare
            if e < s, !b.contains("am"), !b.contains("pm") {
                let eh = Int(e.prefix(2))! + 12
                if eh <= 23 { e = String(format: "%02d", eh) + e.dropFirst(2) }
            }
            if e < s, !a.contains("am"), !a.contains("pm") {           // "from 8 to 11": morning start
                let sh = Int(s.prefix(2))! - 12
                if sh >= 0 { s = String(format: "%02d", sh) + s.dropFirst(2) }
            }
            span.start = s; span.end = e
            take(m)
        }
        if span.start == nil {
            let clockP = #"\b(?:at|by|@|for|around|about|from|starting at)?\s*(?:around\s+|about\s+)?("# + clockCore + ampm + #")(?:\s*ish)?\b"#
            for m in all(clockP) where span.start == nil {
                guard !overlaps(m), let raw = LocalEngine.group(m, 1, in: low) else { continue }
                let whole = (Range(m.range, in: low).map { String(low[$0]) }) ?? ""
                // a bare number is a clock only when it LOOKS like one: a
                // preposition, a colon, am/pm, o'clock — "buy 5 apples" is a count
                let looksLikeClock = whole.range(of: #"^\s*(?:at|by|@|around|about|from|starting at)\b|:|\.\d{2}|am|a\.m|pm|p\.m|o'clock|oclock|noon|midday|midnight|lunch|half past|quarter|past|thirty|fifteen|forty|in the (?:morning|afternoon|evening)|at night|tonight"#,
                                                 options: .regularExpression) != nil
                guard looksLikeClock else { continue }
                // "for 2 hours" is a duration, not a clock
                if whole.trimmingCharacters(in: .whitespaces).hasPrefix("for"),
                   low.range(of: #"for\s+\S+\s+(?:hours?|minutes?|mins?|hrs?)"#, options: .regularExpression) != nil { continue }
                guard let c = clock(raw, context: low) else { continue }
                span.start = c
                take(m)
            }
        }

        // -- duration ("for an hour", "for 45 minutes", "for two hours")
        if let m = all(#"\bfor\s+(an?|one|two|three|four|five|six|half an|\d+(?:\.\d)?)\s*(hours?|hrs?|minutes?|mins?)\b"#).first, !overlaps(m) {
            let q = LocalEngine.group(m, 1, in: low) ?? "1"
            let u = LocalEngine.group(m, 2, in: low) ?? "hour"
            var mins = q.hasPrefix("half") ? 30 : number(q) * (u.hasPrefix("h") ? 60 : 1)
            if let d = Double(q), u.hasPrefix("h") { mins = Int(d * 60) }
            span.durationMinutes = mins
            if let s = span.start, span.end == nil { span.end = addMinutes(s, mins) }
            take(m)
        }

        // -- dates
        var date: String? = nil
        func setDate(_ d: String, _ m: NSTextCheckingResult) { if date == nil, !overlaps(m) { date = d; take(m) } }
        for m in all(#"\b(?:for\s+)?(a|an|one|two|three|four|five|six|\d+)\s+(days?|weeks?)\s+from\s+(?:now|today)\b"#) {
            let n = number(LocalEngine.group(m, 1, in: low) ?? "1")
            let w = (LocalEngine.group(m, 2, in: low) ?? "day").hasPrefix("w")
            setDate(day(w ? n * 7 : n), m)
        }
        for m in all(#"\b(?:the\s+)?day after tomorrow\b"#) { setDate(day(2), m) }
        for m in all(#"\b(?:tomorrow|tmrw|tmr|tomorow)(?:\s+(?:morning|afternoon|evening|night))?\b"#) { setDate(day(1), m) }
        for m in all(#"\b(?:today|tonight|this (?:morning|afternoon|evening)|later today|later|now|right now|end of (?:the )?day)\b"#) {
            let w = (Range(m.range, in: low).map { String(low[$0]) }) ?? ""
            if overlaps(m) { continue }
            if w == "later" || w == "now" || w == "right now" {
                // "now" is the clock (Q81's word table), only when said alone
                if w.contains("now") && span.start == nil {
                    let c = cal.dateComponents([.hour, .minute], from: now)
                    span.start = String(format: "%02d:%02d", c.hour!, c.minute!)
                }
            }
            setDate(day(0), m)
        }
        for m in all(#"\bin\s+(a|an|one|two|three|four|five|six|seven|\d+|a couple of|a few)\s+(days?|weeks?|months?)\b"#) {
            let q = LocalEngine.group(m, 1, in: low) ?? "1"
            let u = LocalEngine.group(m, 2, in: low) ?? "day"
            let n = q == "a few" ? 3 : q == "a couple of" ? 2 : number(q)
            let unit: Calendar.Component = u.hasPrefix("w") ? .weekOfYear : u.hasPrefix("m") ? .month : .day
            setDate(iso(cal.date(byAdding: unit, value: n, to: today)!, cal), m)
        }

        // weekday: "friday", "on friday", "this friday", "next friday", "this coming friday", "fri"
        let wdP = #"\b(?:on\s+)?(this coming|this|next|coming|the coming|last)?\s*(sunday|monday|tuesday|wednesday|thursday|friday|saturday|sun|mon|tues?|wed|thur?s?|fri|sat)\b(?:\s+(?:morning|afternoon|evening|night))?"#
        for m in all(wdP) {
            let mod = LocalEngine.group(m, 1, in: low) ?? ""
            let w = LocalEngine.group(m, 2, in: low) ?? ""
            guard let idx = weekdays.firstIndex(where: { $0.hasPrefix(w) }) else { continue }
            let todayW = cal.component(.weekday, from: today) - 1
            // the coming one; "next" or a bare name on its own day is a week on
            var delta = (idx - todayW + 7) % 7
            if delta == 0 && mod != "this" { delta = 7 }
            setDate(day(delta), m)
        }
        // "this weekend" → saturday; "next week" → the next Sunday; "next month" → the 1st
        for m in all(#"\b(?:this|next|the)?\s*weekend\b"#) {
            let todayW = cal.component(.weekday, from: today) - 1
            var delta = (6 - todayW + 7) % 7
            if low.contains("next weekend") { delta += 7 }
            setDate(day(delta), m)
        }
        for m in all(#"\b(?:the )?week after next\b"#) {
            let todayW = cal.component(.weekday, from: today) - 1
            setDate(day(14 - todayW), m)
        }
        for m in all(#"\b(sunday|monday|tuesday|wednesday|thursday|friday|saturday) after next\b"#) {
            if let w = LocalEngine.group(m, 1, in: low), let idx = weekdays.firstIndex(of: w) {
                let todayW = cal.component(.weekday, from: today) - 1
                var delta = (idx - todayW + 7) % 7
                if delta == 0 { delta = 7 }
                setDate(day(delta + 7), m)
            }
        }
        for m in all(#"\b(?:early|late|mid|the start of|the beginning of)\s+next week\b"#) {
            let todayW = cal.component(.weekday, from: today) - 1
            let w = (Range(m.range, in: low).map { String(low[$0]) }) ?? ""
            setDate(day(7 - todayW + (w.hasPrefix("late") ? 4 : w.hasPrefix("mid") ? 3 : 1)), m)
        }
        for m in all(#"\b(?:next|the following) week\b"#) {
            let todayW = cal.component(.weekday, from: today) - 1
            setDate(day(7 - todayW), m)
        }
        for m in all(#"\b(?:this|later this) week\b"#) { setDate(day(0), m) }
        for m in all(#"\b(?:at |by |before )?the end of (?:the |this )?month\b|\bend of month\b"#) {
            var c = cal.dateComponents([.year, .month], from: today)
            c.month! += 1; c.day = 0
            setDate(iso(cal.date(from: c)!, cal), m)
        }
        for m in all(#"\b(?:at |by |before )?the end of (?:the |this )?week\b|\bend of (?:the )?week\b"#) {
            let todayW = cal.component(.weekday, from: today) - 1
            setDate(day((5 - todayW + 7) % 7), m)
        }
        for m in all(#"\bnext month\b"#) {
            var c = cal.dateComponents([.year, .month], from: today)
            c.month! += 1; c.day = 1
            setDate(iso(cal.date(from: c)!, cal), m)
        }
        // "march 5th", "5th of march", "the 5th", "on the 12th", "3/14", "14.3"
        let monthAlt = "(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sept?|oct|nov|dec)"
        for m in all(#"\b"# + monthAlt + #"\s+(\d{1,2})(?:st|nd|rd|th)?\b"#) {
            if let mo = LocalEngine.group(m, 1, in: low), let d = Int(LocalEngine.group(m, 2, in: low) ?? "") {
                if let s = dayOf(month: mo, day: d, today: today, cal: cal) { setDate(s, m) }
            }
        }
        for m in all(#"\b(?:the\s+)?(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?"# + monthAlt + #"\b"#) {
            if let mo = LocalEngine.group(m, 2, in: low), let d = Int(LocalEngine.group(m, 1, in: low) ?? "") {
                if let s = dayOf(month: mo, day: d, today: today, cal: cal) { setDate(s, m) }
            }
        }
        for m in all(#"\b(?:on\s+)?the\s+(\d{1,2})(?:st|nd|rd|th)\b"#) {
            if let d = Int(LocalEngine.group(m, 1, in: low) ?? ""), (1...31).contains(d) {
                var c = cal.dateComponents([.year, .month], from: today)
                c.day = d
                var dt = cal.date(from: c)!
                if dt < today { dt = cal.date(byAdding: .month, value: 1, to: dt)! }
                setDate(iso(dt, cal), m)
            }
        }
        // a few named days the corpus says
        let named: [(String, (Int) -> (Int, Int))] = [
            (#"\bchristmas eve\b"#, { _ in (12, 24) }), (#"\bchristmas(?: day)?\b"#, { _ in (12, 25) }),
            (#"\bnew year'?s eve\b"#, { _ in (12, 31) }), (#"\bnew year'?s(?: day)?\b"#, { _ in (1, 1) }),
            (#"\bhalloween\b"#, { _ in (10, 31) }), (#"\bvalentine'?s(?: day)?\b"#, { _ in (2, 14) }),
        ]
        for m in all(#"\bthanksgiving\b"#) {
            // the fourth Thursday of November, this year or next
            for y in [cal.component(.year, from: today), cal.component(.year, from: today) + 1] {
                var c = DateComponents(year: y, month: 11, weekday: 5, weekdayOrdinal: 4)
                c.calendar = cal
                if let d = cal.date(from: c), d >= today { setDate(iso(d, cal), m); break }
            }
        }
        for (p, md) in named {
            for m in all(p) {
                let (mo, d) = md(0)
                if let s = dayOf(monthIndex: mo, day: d, today: today, cal: cal) { setDate(s, m) }
            }
        }
        // a part of the day said on its own ("in the morning") is NOT a clock (Q47)
        for m in all(#"\b(?:at\s+)?(?:early|late)?\s*(?:in the|this|tomorrow)\s+(?:morning|afternoon|evening)\b|\btonight\b|\bat night\b|\b(?:at\s+)?first thing(?: in the morning)?\b|\b(?:at\s+)?(?:around\s+)?lunchtime\b|\bearly (?:morning|evening)\b"#)
            where !overlaps(m) { take(m) }
        // "all day"
        for m in all(#"\b(?:all[- ]day|the whole day|full day)\b"#) { span.allDay = true; take(m) }
        // multi-day questions ("the next few days", "this week")
        if low.range(of: #"\b(?:next few days|coming days|this week|next week|the week)\b"#, options: .regularExpression) != nil {
            span.rangeEnd = iso(cal.date(byAdding: .day, value: 6, to: today)!, cal)
        }
        span.date = date
        // "at 3 tomorrow" with the clock already past today and no day said: today, as said
        return span
    }

    static func dayOf(month: String, day: Int, today: Date, cal: Calendar) -> String? {
        guard let mi = months.firstIndex(where: { $0.hasPrefix(month.prefix(3)) }) else { return nil }
        return dayOf(monthIndex: mi + 1, day: day, today: today, cal: cal)
    }

    static func dayOf(monthIndex: Int, day: Int, today: Date, cal: Calendar) -> String? {
        var c = cal.dateComponents([.year], from: today)
        c.month = monthIndex; c.day = day
        guard var dt = cal.date(from: c), cal.component(.day, from: dt) == day else { return nil }
        if dt < today { dt = cal.date(byAdding: .year, value: 1, to: dt)! }
        return iso(dt, cal)
    }
}

// MARK: - Series

enum Recurrence {
    struct Found {
        var cadence: String? = nil
        var days: [String] = []
        var until: String? = nil
        var firstDate: String? = nil
        var notes: [String] = []
        var ranges: [Range<String.Index>] = []
    }

    static func find(_ text: String, now: Date, cal: Calendar) -> Found {
        var f = Found()
        let low = text.lowercased()
        func first(_ p: String) -> NSTextCheckingResult? { LocalEngine.match(p, low) }
        func take(_ m: NSTextCheckingResult) { if let r = Range(m.range, in: text) { f.ranges.append(r) } }
        let wd = "(?:sunday|monday|tuesday|wednesday|thursday|friday|saturday)s?"
        if let m = first(#"\bevery\s+(two|three|four|five|six|2|3|4|5|6|couple of)\s+(days|weeks|months|years)\b"#) {
            let unit = LocalEngine.group(m, 2, in: low) ?? "weeks"
            f.cadence = unit.hasPrefix("day") ? "daily" : unit.hasPrefix("month") ? "monthly" : unit.hasPrefix("year") ? "yearly" : "weekly"
            f.notes.append("rounded: \(LocalEngine.group(m, 0, in: low) ?? "") → \(f.cadence!)")
            take(m)
        } else if let m = first(#"\b(?:every|each|once a)\s+fortnight\b|\bfortnightly\b|\bbi-?weekly\b"#) {
            f.cadence = "weekly"; f.notes.append("rounded: every two weeks → weekly"); take(m)
        } else if let m = first(#"\bevery\s+(other|second|third)\s+(day|week|month|year|"# + wd + ")\\b") {
            let unit = LocalEngine.group(m, 2, in: low) ?? "week"
            f.cadence = unit == "day" ? "daily" : unit == "month" ? "monthly" : unit == "year" ? "yearly" : "weekly"
            f.days = DateParse.weekdays.filter { unit.hasPrefix($0) }
            f.notes.append("rounded: \(LocalEngine.group(m, 0, in: low) ?? "") → \(f.cadence!)")
            take(m)
        } else if let m = first(#"\b(?:every|each)\s+("# + wd + #"(?:\s*(?:,|and|&)\s*"# + wd + #")*)\b"#) {
            let list = LocalEngine.group(m, 1, in: low) ?? ""
            f.cadence = "weekly"
            f.days = DateParse.weekdays.filter { list.contains($0) }
            take(m)
        } else if let m = first(#"\b(?:every|each)\s+weekday|\bweekdays\b|\bevery work ?day\b"#) {
            f.cadence = "weekly"
            f.days = ["monday", "tuesday", "wednesday", "thursday", "friday"]
            take(m)
        } else if let m = first(#"\b(?:every|each)\s+weekend\b|\bweekends\b"#) {
            f.cadence = "weekly"; f.days = ["saturday"]
            f.notes.append("rounded: every weekend → weekly on saturday")
            take(m)
        } else if let m = first(#"\b(?:every\s+(?:single\s+)?day|daily|each day|every morning|every evening|every night|each morning|each evening|each night|nightly|every weeknight)\b"#) {
            f.cadence = "daily"; take(m)
        } else if let m = first(#"\b(?:every|each|once a|once per|one time a)\s+week\b|\bweekly\b|\bonce a week\b"#) {
            f.cadence = "weekly"; take(m)
        } else if let m = first(#"\b(?:every|each|once a)\s+month\b|\bmonthly\b"#) {
            f.cadence = "monthly"; take(m)
        } else if let m = first(#"\b(?:every|each|once a)\s+year\b|\byearly\b|\bannually\b"#) {
            f.cadence = "yearly"; take(m)
        } else if let m = first(#"\b(?:twice|three times|\d+ times) a (week|day|month)\b"#) {
            let u = LocalEngine.group(m, 1, in: low) ?? "week"
            f.cadence = u == "day" ? "daily" : u == "month" ? "monthly" : "weekly"
            f.notes.append("rounded: \(LocalEngine.group(m, 0, in: low) ?? "") → \(f.cadence!)")
            take(m)
        }
        guard f.cadence != nil else { return f }
        // "until …" excludes its day; "through …" keeps it (CLAUDE.md)
        if let m = first(#"\bfor the rest of the (year|month)\b"#) {
            let today = cal.startOfDay(for: now)
            var c = cal.dateComponents([.year, .month], from: today)
            if LocalEngine.group(m, 1, in: low) == "year" { c.month = 12; c.day = 31 } else { c.month! += 1; c.day = 0 }
            f.until = DateParse.iso(cal.date(from: c)!, cal)
            take(m)
        } else if let m = first(#"\b(until|till|through|thru|up to|ending)\s+(.+?)$"#),
           let word = LocalEngine.group(m, 1, in: low), let rest = LocalEngine.group(m, 2, in: text) {
            if rest.lowercased().hasPrefix("further notice") { take(m) }
            else {
                let s = DateParse.find(rest, now: now, cal: cal)
                if var d = s.date {
                    if word == "until" || word == "till" || word == "up to",
                       !rest.lowercased().hasPrefix("the end of"),
                       let dt = isoDate(d, cal) {
                        d = DateParse.iso(cal.date(byAdding: .day, value: -1, to: dt)!, cal)
                    }
                    f.until = d
                    take(m)
                }
            }
        }
        if let m = first(#"\bstarting\s+(.+?)(?=\s+(?:until|till|through|at)\b|$)"#), let rest = LocalEngine.group(m, 1, in: text) {
            let s = DateParse.find(rest, now: now, cal: cal)
            if let d = s.date { f.firstDate = d; take(m) }
        }
        // a weekly series starts on the soonest weekday it names (CLAUDE.md)
        if f.cadence == "weekly", !f.days.isEmpty, f.firstDate == nil {
            let today = cal.startOfDay(for: now)
            let todayW = cal.component(.weekday, from: today) - 1
            let deltas = f.days.compactMap { d in DateParse.weekdays.firstIndex(of: d) }.map { ($0 - todayW + 7) % 7 }
            if let soonest = deltas.min() {
                f.firstDate = DateParse.iso(cal.date(byAdding: .day, value: soonest, to: today)!, cal)
            }
        }
        return f
    }

    /// Q57: daily 2 weeks, weekly 8, monthly 12 months, yearly 10 years.
    static func defaultEnd(from start: String, cadence: String, cal: Calendar) -> String? {
        guard let d = isoDate(start, cal) else { return nil }
        let end: Date?
        switch cadence {
        case "daily": end = cal.date(byAdding: .day, value: 14, to: d)
        case "weekly": end = cal.date(byAdding: .weekOfYear, value: 8, to: d)
        case "monthly": end = cal.date(byAdding: .month, value: 12, to: d)
        default: end = cal.date(byAdding: .year, value: 10, to: d)
        }
        return end.map { DateParse.iso($0, cal) }
    }

    static func isoDate(_ s: String, _ cal: Calendar) -> Date? {
        let p = s.split(separator: "-").compactMap { Int($0) }
        guard p.count == 3 else { return nil }
        return cal.date(from: DateComponents(year: p[0], month: p[1], day: p[2]))
    }
}
