// Apple's on-device model, run the way the phone's offline reader runs it
// (MACalendar-iOS/.../Voice/OfflineReader.swift): the same instructions text
// (built by the Python driver from assistant/offline/spec.py, exactly as the
// phone builds it), the same prompt, the same @Generable item shape, greedy.
//
// stdin:  one JSON per line  {"id": "...", "text": "...", "today": "2026-09-09 (Wednesday)"}
// argv1:  path to the instructions text
// stdout: one JSON per line  {"id": "...", "items": [...], "ms": 812, "error": null}
//
// A new LanguageModelSession per command, as on the phone — no shared context.
import Foundation
import FoundationModels

@available(macOS 26.0, *)
@Generable
struct GenItem {
    @Guide(description: "event, todo or other", .anyOf(["event", "todo", "other"]))
    var kind: String
    @Guide(description: "The thing itself, short, in the speaker's words; no date or time")
    var title: String
    @Guide(description: "The words that say which day, exactly as said (tomorrow, next tuesday, march 5th), or empty")
    var when: String
    @Guide(description: "24-hour HH:MM start, or empty")
    var start: String
    @Guide(description: "24-hour HH:MM end, or empty unless an end was said")
    var end: String
    @Guide(description: "none unless the speaker said it repeats",
           .anyOf(["none", "daily", "weekly", "monthly", "yearly"]))
    var recurrence: String
}

@available(macOS 26.0, *)
@Generable
struct GenReading {
    // At most 6 (DEVQA Q68 step 1c): uncapped, the model looped on repeat
    // phrases until its context window filled — 21 of 1,200, ~37 s each.
    @Guide(description: "One item per thing the speaker asked for, in order", .maximumCount(6))
    var items: [GenItem]
}

struct Row: Decodable { let id: String; let text: String; let today: String }

@available(macOS 26.0, *)
func run() async {
    guard CommandLine.arguments.count > 1,
          let instructions = try? String(contentsOfFile: CommandLine.arguments[1], encoding: .utf8) else {
        FileHandle.standardError.write("usage: afm_reader <instructions.txt> < rows.jsonl\n".data(using: .utf8)!)
        exit(2)
    }
    guard case .available = SystemLanguageModel.default.availability else {
        print("{\"fatal\": \"Apple's on-device model is not available on this Mac\"}")
        exit(3)
    }
    // argv2 (optional): the served guard rules — the phone's OfflineGuard.swift
    // is compiled into this tool, so the board measures the app's own code.
    var rules: GuardRules? = nil
    if CommandLine.arguments.count > 2,
       let d = FileManager.default.contents(atPath: CommandLine.arguments[2]) {
        rules = try? JSONDecoder().decode(GuardRules.self, from: d)
    }
    while let line = readLine() {
        guard let data = line.data(using: .utf8),
              let row = try? JSONDecoder().decode(Row.self, from: data) else { continue }
        let t0 = Date()
        var out: [String: Any] = ["id": row.id]
        if let rules, OfflineGuard.leavesForMac(row.text, rules: rules) {
            out["items"] = [["kind": "other", "title": row.text, "date": "", "start": "",
                             "end": "", "recurrence": "none"]]
            out["error"] = NSNull()
            out["guarded"] = true
            out["ms"] = Int(Date().timeIntervalSince(t0) * 1000)
            if let json = try? JSONSerialization.data(withJSONObject: out, options: [.sortedKeys]),
               let s = String(data: json, encoding: .utf8) { print(s); fflush(stdout) }
            continue
        }
        do {
            let session = LanguageModelSession(instructions: instructions)
            let r = try await session.respond(to: "Today: \(row.today)\nSaid: \(row.text)",
                                              generating: GenReading.self,
                                              options: GenerationOptions(sampling: .greedy))
            let f = DateFormatter()
            f.dateFormat = "yyyy-MM-dd"
            f.locale = Locale(identifier: "en_US_POSIX")
            let today = f.date(from: String(row.today.prefix(10))) ?? Date()
            out["items"] = r.content.items.map {
                ["kind": $0.kind, "title": $0.title, "when": $0.when,
                 "date": OfflineDates.resolve($0.when, today: today) ?? "",
                 "start": $0.start, "end": $0.end, "recurrence": $0.recurrence]
            }
            out["error"] = NSNull()
        } catch {
            out["items"] = []
            out["error"] = "\(error)"
        }
        out["ms"] = Int(Date().timeIntervalSince(t0) * 1000)
        if let json = try? JSONSerialization.data(withJSONObject: out, options: [.sortedKeys]),
           let s = String(data: json, encoding: .utf8) {
            print(s)
            fflush(stdout)
        }
    }
}

@main
struct AFMReader {
    static func main() async {
        if #available(macOS 26.0, *) {
            await run()
        } else {
            print("{\"fatal\": \"needs macOS 26\"}")
            exit(3)
        }
    }
}
