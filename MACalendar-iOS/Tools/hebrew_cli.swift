import Foundation

// "holidays|windows START END israel(0/1)" per line in, JSON out.
// tests/unit/test_hebrew_calendar_phone.py compares it with the Mac's code.
@main
struct HebrewCLI {
    static func main() {
        while let line = readLine() {
            let p = line.split(separator: " ").map(String.init)
            guard p.count == 4 else { print("[]"); continue }
            let israel = p[3] == "1"
            let data: Data
            if p[0] == "holidays" {
                data = try! JSONEncoder().encode(HebrewCalendar.holidays(from: p[1], to: p[2], israel: israel))
            } else {
                data = try! JSONEncoder().encode(HebrewCalendar.holyWindows(from: p[1], to: p[2], israel: israel))
            }
            print(String(data: data, encoding: .utf8)!)
            fflush(stdout)
        }
    }
}
