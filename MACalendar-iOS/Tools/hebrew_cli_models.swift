import Foundation

// The two shapes HebrewCalendar.swift returns, as the app declares them in
// API/Models.swift (which imports UIKit, so the command line cannot build it).
// Same stored fields, same JSON keys — test_hebrew_calendar_phone.py reads them.

struct Holiday: Codable, Equatable {
    var nameEn: String
    var nameHe: String
    var category: String
    var gregorianErevStart: String
    var gregorianEnd: String
    enum CodingKeys: String, CodingKey {
        case nameEn = "name_en", nameHe = "name_he", category
        case gregorianErevStart = "gregorian_erev_start", gregorianEnd = "gregorian_end"
    }
}

struct HolyWindow: Codable, Equatable {
    var name: String
    var startName: String
    var endName: String
    var start: String
    var end: String
    var startLabel: String
    var endLabel: String
    var days: [String]
    enum CodingKeys: String, CodingKey {
        case name, start, end, days
        case startName = "start_name", endName = "end_name"
        case startLabel = "start_label", endLabel = "end_label"
    }
}
