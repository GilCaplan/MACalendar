// The PARITY harness for the phone's labellers: tests/unit/test_label_export.py
// compiles this with LabelModel.swift and CategoryClassifier.swift and compares
// every answer with the Mac's (sklearn's probabilities, categories.classify,
// model.category_for / tags_for with the embedding unavailable).
//
// argv[1]: a JSON file {"event": <payload>, "task": <payload>,
//                       "category_rules": <rules>, "palette": [tag names]}
// stdin:   one JSON object per line {"title", "attendees", "location",
//          "description", "rule_tags"}
// stdout:  one JSON object per line {"pe", "pt", "rule", "category", "tags"}
import Foundation

struct Setup: Codable {
    let event: LabelModelPayload
    let task: LabelModelPayload
    let categoryRules: CategoryRules
    let palette: [String]
    enum CodingKeys: String, CodingKey {
        case event, task, palette
        case categoryRules = "category_rules"
    }
}

struct Row: Codable {
    let title: String
    let attendees: String
    let location: String
    let description: String
    let ruleTags: [String]
    enum CodingKeys: String, CodingKey {
        case title, attendees, location, description
        case ruleTags = "rule_tags"
    }
}

@main
struct PhoneParity {
    static func main() throws {
        let setup = try JSONDecoder().decode(
            Setup.self, from: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1])))
        guard let event = LabelModel(setup.event), let task = LabelModel(setup.task) else {
            FileHandle.standardError.write("payload refused\n".data(using: .utf8)!)
            exit(2)
        }
        let rules = setup.categoryRules
        while let line = readLine() {
            let r = try JSONDecoder().decode(Row.self, from: Data(line.utf8))
            let rule = CategoryClassifier.classify(
                r.title, attendees: r.attendees.components(separatedBy: ","),
                location: r.location, description: r.description, rules: rules)
            let category = LabelModel.stackCategory(
                rule: rule, title: r.title, model: event,
                exists: { CategoryClassifier.exists($0, in: rules) })
            let tags = LabelModel.stackTags(rule: r.ruleTags, title: r.title, model: task,
                                            palette: setup.palette)
            let out: [String: Any] = ["pe": event.probabilities(r.title),
                                      "pt": task.probabilities(r.title),
                                      "rule": rule, "category": category, "tags": tags]
            print(String(data: try JSONSerialization.data(withJSONObject: out, options: [.sortedKeys]),
                         encoding: .utf8)!)
        }
    }
}
