import SwiftUI
import AppKit
// Harness for tests/unit/test_easter_egg.py: every loading-screen style with 1, 2 and 4
// objects, drawn through EggLoaderRender, to one PNG (argv[1]). Prints the style count.
@MainActor final class EggOverlay { static let shared = EggOverlay(); func show(passThrough: Bool = false) {}; func hide() {} }
@main struct Loaders {
    @MainActor static func main() {
        let objs = EggCatalog.defaults()
        let styles = EggLoaderStyle.allCases
        let v = Canvas { ctx, size in
            ctx.fill(Path(CGRect(origin: .zero, size: size)), with: .color(Color(egg: 0xf3f0fb)))
            for (r, st) in styles.enumerated() {
                for (c, t) in [0.1, 0.35, 0.6, 0.85].enumerated() {
                    var cc = ctx
                    cc.translateBy(x: CGFloat(c) * 170 + 10, y: CGFloat(r) * 170 + 10)
                    var cfg = EggLoaderConfig(); cfg.style = st
                    cfg.objects = [["dog"], ["dog", "dragon"], ["dog", "dragon", "unicorn", "sukkah"], ["car"]][c]
                    EggLoaderRender.draw(cfg, cfg.objects.compactMap { id in objs.first { $0.id == id } }, cc,
                                         CGSize(width: 150, height: 150), t: t, image: { _ in nil })
                }
            }
        }.frame(width: 690, height: CGFloat(styles.count) * 170 + 10)
        let r = ImageRenderer(content: v); r.scale = 1.5
        let rep = NSBitmapImageRep(cgImage: r.cgImage!)
        try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
        print(styles.count)
    }
}
