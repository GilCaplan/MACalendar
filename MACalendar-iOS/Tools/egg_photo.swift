// Harness for the photo path (TASKS 44/47): REAL photographs through the real
// pipeline — `EggImageCore`, the code the phone and the Mac both run — on this
// Mac's Vision and Core Image: automatic cut-out, the anime look, the sticker
// edge, the rig Apple's classifier picks, the animal legs and the wheels it
// finds, then the puppet in motion. Writes a contact sheet (argv[1]) and one
// JSON line per photo on stdout. The photos are argv[2...].
//
// It is not the phone: Vision on macOS 14 and iOS 17 share the request, but a
// real camera-roll photo on a real phone is still worth one look by hand.
import AppKit
import ImageIO
import SwiftUI

@MainActor final class EggOverlay { static let shared = EggOverlay(); func show(passThrough: Bool = false) {}; func hide() {} }

func loadUpright(_ path: String) -> CGImage? {
    guard let src = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil) else { return nil }
    let opts: [CFString: Any] = [kCGImageSourceCreateThumbnailFromImageAlways: true,
                                 kCGImageSourceCreateThumbnailWithTransform: true,
                                 kCGImageSourceThumbnailMaxPixelSize: 2048]
    return CGImageSourceCreateThumbnailAtIndex(src, 0, opts as CFDictionary)
}

struct Row {
    let name: String
    let photo: CGImage
    let cut: CGImage?
    let anime: CGImage?
    let variant: EggVariant
}

@main
struct EggPhotoHarness {
    @MainActor static func main() async {
        let args = CommandLine.arguments
        guard args.count >= 3 else { print("usage: egg_photo out.png photo..."); return }
        var rows: [Row] = []
        for path in args.dropFirst(2) {
            guard let raw = loadUpright(path) else { continue }
            let photo = EggImageCore.normalised(raw)
            let t0 = Date()
            let cut = await EggImageCore.render(photo: photo, lasso: nil, anime: false)
            let ms = Int(Date().timeIntervalSince(t0) * 1000)
            let anime = await EggImageCore.render(photo: photo, lasso: nil, anime: true)
            // A loop round the middle half, as a hand would draw it.
            let loop = [CGPoint(x: 0.25, y: 0.2), CGPoint(x: 0.75, y: 0.2), CGPoint(x: 0.8, y: 0.8), CGPoint(x: 0.2, y: 0.8)]
            let lassoed = EggImageCore.lassoCutout(photo, points: loop)
            let rig = await EggImageCore.guessRig(photo)
            var foundLegs: [[Double]]? = nil
            if let cut { foundLegs = await EggImageCore.findLegs(cut) }
            let wheels = cut.map(EggPuppet.findWheels) ?? []
            let v = EggVariant(id: "p", name: "p", source: .image("p"), anime: false,
                               detectedRig: rig, wheels: wheels, legs: foundLegs)
            let name = URL(fileURLWithPath: path).lastPathComponent
            let line: [String: Any] = [
                "photo": name, "w": photo.width, "h": photo.height,
                "cutout": cut != nil, "cut_w": cut?.width ?? 0, "cut_h": cut?.height ?? 0, "cut_ms": ms,
                "anime": anime != nil, "lasso": lassoed != nil,
                "luma_cut": cut.map(EggImageCore.meanLuma) ?? 0,
                "luma_anime": cut.map { EggImageCore.meanLuma(EggImageCore.anime($0)) } ?? 0,
                "lasso_w": lassoed?.width ?? 0, "lasso_h": lassoed?.height ?? 0,
                "rig": rig.rawValue, "legs": foundLegs?.count ?? 0, "wheels": wheels.count,
            ]
            if let d = try? JSONSerialization.data(withJSONObject: line, options: [.sortedKeys]),
               let s = String(data: d, encoding: .utf8) { print(s) }
            rows.append(Row(name: name, photo: photo, cut: cut, anime: anime, variant: v))
        }
        let cell: CGFloat = 180
        let cols = 6                                            // photo, cut, anime, 3 moments of the puppet
        let sheet = Canvas { ctx, size in
            ctx.fill(Path(CGRect(origin: .zero, size: size)), with: .color(Color(egg: 0x3b4663)))
            for (r, row) in rows.enumerated() {
                let y = CGFloat(r) * cell
                func put(_ cg: CGImage?, _ c: Int) {
                    guard let cg else { return }
                    let k = min((cell - 10) / CGFloat(cg.width), (cell - 10) / CGFloat(cg.height))
                    let w = CGFloat(cg.width) * k, h = CGFloat(cg.height) * k
                    ctx.draw(Image(decorative: cg, scale: 1),
                             in: CGRect(x: CGFloat(c) * cell + (cell - w) / 2, y: y + (cell - h) / 2, width: w, height: h))
                }
                put(row.photo, 0); put(row.cut, 1); put(row.anime, 2)
                if let cut = row.cut {
                    for (j, t) in [0.0, 0.15, 0.3].enumerated() {
                        var cc = ctx
                        cc.translateBy(x: CGFloat(3 + j) * cell + 5, y: y + 5)
                        cc.scaleBy(x: (cell - 10) / 200, y: (cell - 10) / 200)
                        EggPuppet.draw(row.variant, cc.resolve(Image(decorative: cut, scale: 1)), cc, t: t)
                    }
                }
            }
        }
        .frame(width: CGFloat(cols) * cell, height: max(cell, CGFloat(rows.count) * cell))
        let r = ImageRenderer(content: sheet)
        r.scale = 1
        if let cg = r.cgImage {
            let rep = NSBitmapImageRep(cgImage: cg)
            try? rep.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: args[1]))
        }
    }
}
