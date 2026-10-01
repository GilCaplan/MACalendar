import SwiftUI
import UIKit

/// Settings ▸ Easter egg ▸ Loading screen: build what plays while the app
/// waits — its style, who is in it, its trail, speed and ring — and when a
/// long wait takes the middle of the screen.
struct EggLoaderSettingsView: View {
    @ObservedObject private var store = EggStore.shared
    @ObservedObject private var fold = SettingsFold.shared

    private var cfg: Binding<EggLoaderConfig> { $store.settings.loader }

    var body: some View {
        Form {
            Section {
                EggLoaderView(side: 190, caption: cfg.wrappedValue.showCaption ? cfg.wrappedValue.stuckCaption : nil)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 8)
                Toggle("Use my loading screen", isOn: cfg.enabled)
                Button {
                    EggWaits.shared.demoUntil = Date().addingTimeInterval(4)
                } label: { Label("Show the “taking a while” screen", systemImage: "hourglass") }
            } footer: {
                Text("Plays wherever the app waits: the mic while a command thinks, the thinking panel, lists loading. "
                     + "Off, the app uses the plain spinner.")
            }

            Section { if fold.isOpen("egg.loader.Style") {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 12) {
                        ForEach(EggLoaderStyle.allCases, id: \.self) { style in
                            var preview = cfg.wrappedValue
                            let _ = (preview.style = style)
                            Button { cfg.wrappedValue.style = style } label: {
                                VStack(spacing: 6) {
                                    EggLoaderView(side: 74, config: preview)
                                        .padding(6)
                                        .background(RoundedRectangle(cornerRadius: 14)
                                            .stroke(cfg.wrappedValue.style == style ? Color.accentColor : Color.secondary.opacity(0.3),
                                                    lineWidth: cfg.wrappedValue.style == style ? 3 : 1))
                                    Text(style.label).font(.caption).foregroundColor(.primary)
                                }
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    .padding(.vertical, 4)
                }
            } } header: { FoldHeader("egg.loader.Style", label: "Style") }

            Section { if fold.isOpen("egg.loader.Who") {
                ForEach(store.settings.objects.filter(\.enabled)) { o in
                    Button { toggle(o.id) } label: {
                        HStack(spacing: 12) {
                            EggThumb(variant: o.activeVariant).frame(width: 36, height: 36)
                            Text(o.name).foregroundColor(.primary)
                            Spacer()
                            if let i = cfg.wrappedValue.objects.firstIndex(of: o.id) {
                                Text("\(i + 1)").font(.caption.weight(.bold)).foregroundColor(.white)
                                    .frame(width: 22, height: 22).background(Circle().fill(Color.accentColor))
                            }
                        }
                    }
                }
            } } header: { FoldHeader("egg.loader.Who", label: "Who's in it") } footer: { if fold.isOpen("egg.loader.Who") {
                Text("Up to four. The wheel and the parade use them all; the other styles use the first.")
            } }

            Section { if fold.isOpen("egg.loader.Look") {
                Picker("Trail", selection: cfg.trail) {
                    ForEach(EggTrail.allCases.filter { $0 != .auto }, id: \.self) { Text($0.label).tag($0) }
                }
                VStack(alignment: .leading) {
                    Text("Speed \(cfg.wrappedValue.speed, specifier: "%.1f")×")
                    Slider(value: cfg.speed, in: 0.3...2, step: 0.1)
                }
                Toggle("Ring", isOn: cfg.showRing)
                if cfg.wrappedValue.showRing {
                    ColorPicker("Ring colour", selection: Binding(
                        get: { Color(eggHex: cfg.wrappedValue.ringHex) },
                        set: { cfg.wrappedValue.ringHex = Self.hex($0) }), supportsOpacity: false)
                }
            } } header: { FoldHeader("egg.loader.Look", label: "Look") }

            Section { if fold.isOpen("egg.loader.Wait") {
                VStack(alignment: .leading) {
                    Text(cfg.wrappedValue.stuckAfter == 0 ? "Never take the middle of the screen"
                         : "Take the middle of the screen after \(cfg.wrappedValue.stuckAfter, specifier: "%.0f") s")
                    Slider(value: cfg.stuckAfter, in: 0...10, step: 1)
                }
                Toggle("With a line", isOn: cfg.showCaption)
                if cfg.wrappedValue.showCaption {
                    TextField("Still working on it…", text: cfg.stuckCaption)
                }
            } } header: { FoldHeader("egg.loader.Wait", label: "When it takes a while") } footer: { if fold.isOpen("egg.loader.Wait") {
                Text("It never blocks: you can keep using the app underneath while it shows.")
            } }
        }
        .navigationTitle("Loading screen")
    }

    private func toggle(_ id: String) {
        var list = cfg.wrappedValue.objects
        if let i = list.firstIndex(of: id) { list.remove(at: i) }
        else if list.count < 4 { list.append(id) }
        cfg.wrappedValue.objects = list
    }

    static func hex(_ c: Color) -> String {
        var r: CGFloat = 0, g: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
        UIColor(c).getRed(&r, green: &g, blue: &b, alpha: &a)
        return String(format: "#%02X%02X%02X", Int(r * 255), Int(g * 255), Int(b * 255))
    }
}
