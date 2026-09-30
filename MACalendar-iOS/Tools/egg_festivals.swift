// Harness for tests/unit/test_easter_egg.py: which festivals EggFestivals
// says are on for each yyyy-MM-dd on stdin (noon, local time).
import Foundation

// The stage asks the app's overlay to show; a harness has none.
@MainActor final class EggOverlay { static let shared = EggOverlay(); func show(passThrough: Bool = false) {}; func hide() {} }

@main
struct EggFestivalDates {
    static func main() {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd HH:mm"
        f.locale = Locale(identifier: "en_US_POSIX")
        while let line = readLine() {
            guard let d = f.date(from: line + " 12:00") else { continue }
            print(line, EggFestivals.current(d).map(\.id).joined(separator: ","))
        }
    }
}
