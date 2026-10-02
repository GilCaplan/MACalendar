import Foundation

// One title per line in, its icons (comma-joined) out — count 2, every kind on.
// tests/unit/test_title_icons.py compares this with the Python lexicon.
@main
struct TitleIconsCLI {
    static func main() {
        let groups = Set(TitleIconsData.groups)
        while let line = readLine() {
            print(TitleIcons.icons(line, count: 2, groups: groups).joined(separator: ","))
        }
    }
}
