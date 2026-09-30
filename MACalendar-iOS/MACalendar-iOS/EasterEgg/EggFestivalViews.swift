import SwiftUI

/// A festive touch in the app: during a festival, a small animated figure
/// (a sukkah in Sukkot, a menorah in Chanukah) sits beside the calendar's
/// title. A tap plays the festival's show. Nothing at all otherwise.
struct EggSeasonBadge: View {
    @ObservedObject private var store = EggStore.shared
    @State private var from = Date()

    private var festival: EggFestivals.Festival? {
        let s = store.settings
        guard s.enabled, s.jewish, s.festivalDecor else { return nil }
        return EggFestivals.current().first { $0.id != "shabbat" } ?? EggFestivals.current().first
    }

    var body: some View {
        if let f = festival, let fig = EggFigure(rawValue: f.objects[0]) {
            Button { store.greet(f) } label: {
                TimelineView(.animation(minimumInterval: 1 / 30)) { tl in
                    Canvas { ctx, size in
                        var c = ctx
                        let k = min(size.width, size.height) / 200
                        c.scaleBy(x: k, y: k)
                        var pose = EggPose(t: tl.date.timeIntervalSince(from))
                        pose.speed = fig.speed
                        fig.draw(EggPainter(ctx: c, line: 6), pose)
                    }
                }
                .frame(width: 30, height: 30)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("\(f.greeting) Play the festival's animation")
        }
    }
}

/// Settings ▸ Easter egg ▸ Jewish festivals.
struct EggFestivalSection: View {
    @ObservedObject private var store = EggStore.shared

    var body: some View {
        Section {
            Toggle("Jewish festivals", isOn: $store.settings.jewish)
            if store.settings.jewish {
                Toggle("Their words only in their season", isOn: $store.settings.jewishInSeason)
                Toggle("Greet me on festival days", isOn: $store.settings.festivalGreeting)
                Toggle("Festive touch in the app", isOn: $store.settings.festivalDecor)
                Toggle("Festival app icon", isOn: Binding(
                    get: { store.settings.festivalIcon },
                    set: { store.settings.festivalIcon = $0; store.syncIcon() }))
                ForEach(EggFestivals.current().filter { $0.id != "shabbat" } + EggFestivals.current().filter { $0.id == "shabbat" },
                        id: \.id) { f in
                    Button { store.greet(f) } label: { Label("Play \(f.greeting.replacingOccurrences(of: "!", with: ""))", systemImage: "sparkles") }
                }
            }
        } header: { Text("Jewish festivals") } footer: {
            Text("Sukkah, lulav and etrog; shofar and apple and honey; menorah and dreidel; mask, grogger and "
                 + "hamantasch; matzah; Shabbat candles and challah; a Torah. On festival days the app greets you "
                 + "once, and a small figure by the calendar's title plays it again when tapped.")
        }
    }
}
