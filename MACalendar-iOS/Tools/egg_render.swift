// Harness for tests/unit/test_easter_egg.py: renders every built-in figure and
// effect through the real overlay renderer, at several moments of every
// motion, to one PNG (argv[1]) — so a drawing that crashes or a motion that
// throws is caught on the Mac, not on the phone. Also a handy art preview.
import SwiftUI
import AppKit

@MainActor final class EggOverlay { static let shared = EggOverlay(); func show(passThrough: Bool = false) {}; func hide() {} }

@main
struct EggRenderAll {
    @MainActor static func main() {
        let screen = CGSize(width: 390, height: 700)
        let ids = EggCatalog.defaults().map(\.id)
        let motions = EggMotion.allCases
        let view = Canvas { ctx, size in
            ctx.fill(Path(CGRect(origin: .zero, size: size)), with: .color(Color(egg: 0x5b6b8c)))
            for (r, id) in ids.enumerated() {
                let effect = EggEffect(rawValue: id) != nil
                let v = EggVariant(id: "original", name: "o", source: effect ? .effect(id) : .figure(id))
                for (c, m) in motions.enumerated() {
                    var cc = ctx
                    cc.translateBy(x: CGFloat(c) * 120, y: CGFloat(r) * 200)
                    cc.scaleBy(x: 0.28, y: 0.28)
                    cc.clip(to: Path(CGRect(origin: .zero, size: screen)))
                    let trails = EggTrail.allCases
                    let drawn: [[Double]] = [[0.1, 0.8, 0], [0.5, 0.2, 0.4], [0.5, 0.2, 0.6], [0.9, 0.7, 1]]
                    for (j, p) in [0.2, 0.5, 0.8].enumerated() {
                        let s = EggShow(objectID: id, variant: v, motion: m, start: Date(), seconds: 3,
                                        slot: 0, count: 1, delay: 0,
                                        trail: trails[(r * 3 + c + j) % trails.count],
                                        mirrored: (r + c) % 2 == 1, path: drawn)
                        EggRender.draw(s, cc, screen, progress: p, t: p * 3, image: { _ in nil })
                    }
                }
            }
        }
        .frame(width: CGFloat(motions.count) * 120, height: CGFloat(ids.count) * 200)
        // Photos: stand-in pictures (a drawn dog and car made into images)
        // through every rig — walk, roll, flap, hop, still.
        func picture(_ f: EggFigure) -> (Image, CGImage?) {
            let v = Canvas { ctx, _ in f.draw(EggPainter(ctx: ctx), EggPose(t: 0.1)) }.frame(width: 200, height: 200)
            let r = ImageRenderer(content: v); r.scale = 2
            return (Image(nsImage: r.nsImage ?? NSImage()), r.cgImage)
        }
        let dog = picture(.dog), car = picture(.car)
        // The wheels the phone would find in the car, printed for the test.
        let wheels = car.1.map(EggPuppet.findWheels) ?? []
        FileHandle.standardError.write((wheels.map { $0.map { String(format: "%.3f", $0) }.joined(separator: ",") }
            .joined(separator: ";") + "\n").data(using: .utf8)!)
        let photos: [(String, Image, [[Double]]?)] = [("dog", dog.0, nil), ("car", car.0, wheels)]
        let rigs: [EggRig] = [.walk, .roll, .flap, .hop, .still]
        let puppets = Canvas { ctx, size in
            ctx.fill(Path(CGRect(origin: .zero, size: size)), with: .color(Color(egg: 0x5b6b8c)))
            for (r, ph) in photos.enumerated() {
                for (c, rig) in rigs.enumerated() {
                    for (j, t) in [0.0, 0.12, 0.24].enumerated() {
                        var cc = ctx
                        cc.translateBy(x: CGFloat(c * 3 + j) * 110, y: CGFloat(r) * 110)
                        cc.scaleBy(x: 0.5, y: 0.5)
                        let v = EggVariant(id: "p", name: "p", source: .image(ph.0), rig: rig, wheels: ph.2)
                        EggPuppet.draw(v, cc.resolve(ph.1), cc, t: t)
                    }
                }
            }
        }.frame(width: 15 * 110, height: 220)
        let pr = ImageRenderer(content: puppets)
        if let img = pr.nsImage, let tiff = img.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff),
           let png = rep.representation(using: .png, properties: [:]) {
            try? png.write(to: URL(fileURLWithPath: CommandLine.arguments[1].replacingOccurrences(of: ".png", with: "-puppets.png")))
        }
        // The user's own graphics: drawings, a word, SF Symbols (one a typo).
        let specs = ["icon:flag_israel|#3A7BFF", "icon:cool|#FFD23A", "emoji:GO", "sf:star.fill|#FFD23A", "sf:person.fill|#3A7BFF",
                     "sf:no.such.symbol|#FF0000"]
        let symbols = Canvas { ctx, size in
            ctx.fill(Path(CGRect(origin: .zero, size: size)), with: .color(Color(egg: 0x5b6b8c)))
            for (c, spec) in specs.enumerated() {
                for (j, t) in [0.0, 0.2, 0.4].enumerated() {
                    var cc = ctx
                    cc.translateBy(x: CGFloat(c * 3 + j) * 110, y: 0)
                    cc.scaleBy(x: 0.5, y: 0.5)
                    EggSymbol.draw(spec, cc, t: t)
                    let v = EggVariant(id: "s", name: "s", source: .symbol(spec))
                    let s = EggShow(objectID: "s", variant: v, motion: EggMotion.allCases[c % EggMotion.allCases.count], start: Date(), seconds: 3, slot: 0, count: 1,
                                    delay: 0, trail: .sparkles, mirrored: false, path: nil)
                    var ov = ctx
                    ov.translateBy(x: CGFloat(c * 3 + j) * 110, y: 110)
                    ov.scaleBy(x: 0.28, y: 0.15)
                    EggRender.draw(s, ov, CGSize(width: 390, height: 700), progress: 0.5, t: t, image: { _ in nil })
                }
            }
        }.frame(width: CGFloat(specs.count * 3) * 110, height: 220)
        let sr = ImageRenderer(content: symbols)
        if let img = sr.nsImage, let tiff = img.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff),
           let png = rep.representation(using: .png, properties: [:]) {
            try? png.write(to: URL(fileURLWithPath: CommandLine.arguments[1].replacingOccurrences(of: ".png", with: "-symbols.png")))
        }
        let r = ImageRenderer(content: view)
        guard let img = r.nsImage, let tiff = img.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff),
              let png = rep.representation(using: .png, properties: [:]) else { exit(1) }
        try! png.write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
        print(ids.count)
    }
}
