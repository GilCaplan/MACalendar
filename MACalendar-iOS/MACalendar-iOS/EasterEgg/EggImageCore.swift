import CoreGraphics
import CoreImage
import CoreImage.CIFilterBuiltins
import Foundation
import Vision

/// The photo pipeline on `CGImage`s, so the phone and the Mac run ONE copy of
/// it (TASKS 46): the phone's `EggImageTools` wraps these in `UIImage`s, the
/// Mac's settings window (`mac/MagicWords`) calls them directly.
///
///     cut out     automatic (Vision's subject lifting, iOS 17 / macOS 14) or a
///                 lasso drawn round the character
///     style       kept as it is, or "anime": saturated flat cel colours and
///                 ink lines, from Core Image's own filters
///     sticker     a white outline round the cut-out, so a photo sits in the
///                 same style as the drawn figures
///     rig         walk / roll / flap / hop, from Apple's on-device classifier;
///                 legs from its animal body-pose detector
///
/// Nothing is sent anywhere and nothing is downloaded.
enum EggImageCore {
    private static let ci = CIContext()

    static func rgbaContext(_ w: Int, _ h: Int) -> CGContext? {
        CGContext(data: nil, width: max(1, w), height: max(1, h), bitsPerComponent: 8, bytesPerRow: 0,
                  space: CGColorSpace(name: CGColorSpace.sRGB)!,
                  bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)
    }

    /// At most `side` pixels on the long edge. (A `CGImage` is already upright;
    /// the phone applies the photo's orientation before it gets here.)
    static func normalised(_ cg: CGImage, side: CGFloat = 1024) -> CGImage {
        let k = min(1, side / CGFloat(max(cg.width, cg.height)))
        guard k < 1 else { return cg }
        let w = Int((CGFloat(cg.width) * k).rounded()), h = Int((CGFloat(cg.height) * k).rounded())
        guard let ctx = rgbaContext(w, h) else { return cg }
        ctx.interpolationQuality = .high
        ctx.draw(cg, in: CGRect(x: 0, y: 0, width: w, height: h))
        return ctx.makeImage() ?? cg
    }

    static var canCutOutAutomatically: Bool {
        if #available(iOS 17.0, macOS 14.0, *) { return true }
        return false
    }

    /// The photo's subject(s) on a transparent background, cropped to them —
    /// or nil when there is no subject to find (or the OS is too old).
    static func autoCutout(_ cg: CGImage) async -> CGImage? {
        guard #available(iOS 17.0, macOS 14.0, *) else { return nil }
        return await Task.detached(priority: .userInitiated) { () -> CGImage? in
            let request = VNGenerateForegroundInstanceMaskRequest()
            let handler = VNImageRequestHandler(cgImage: cg, options: [:])
            guard (try? handler.perform([request])) != nil,
                  let result = request.results?.first,
                  !result.allInstances.isEmpty,
                  let buffer = try? result.generateMaskedImage(ofInstances: result.allInstances, from: handler,
                                                               croppedToInstancesExtent: true)
            else { return nil }
            let ciImage = CIImage(cvPixelBuffer: buffer)
            return CIContext().createCGImage(ciImage, from: ciImage.extent)
        }.value
    }

    /// The part of the picture inside a hand-drawn outline (points 0…1 of the
    /// image, from its TOP-left), cropped to it.
    static func lassoCutout(_ cg: CGImage, points: [CGPoint]) -> CGImage? {
        guard points.count >= 3 else { return nil }
        let s = CGSize(width: cg.width, height: cg.height)
        let path = CGMutablePath()
        path.move(to: CGPoint(x: points[0].x * s.width, y: points[0].y * s.height))
        for p in points.dropFirst() { path.addLine(to: CGPoint(x: p.x * s.width, y: p.y * s.height)) }
        path.closeSubpath()
        let box = path.boundingBoxOfPath.intersection(CGRect(origin: .zero, size: s)).integral
        guard box.width > 8, box.height > 8, let ctx = rgbaContext(Int(box.width), Int(box.height)) else { return nil }
        // y-down, in the picture's own pixels, like the outline
        ctx.translateBy(x: 0, y: box.height); ctx.scaleBy(x: 1, y: -1)
        ctx.translateBy(x: -box.minX, y: -box.minY)
        ctx.addPath(path); ctx.clip()
        // and back to y-up just for drawing the picture, so it lands upright
        ctx.translateBy(x: 0, y: s.height); ctx.scaleBy(x: 1, y: -1)
        ctx.draw(cg, in: CGRect(origin: .zero, size: s))
        return ctx.makeImage()
    }

    /// Flat, saturated cel colours with ink lines, keeping the cut-out's
    /// transparency.
    ///
    /// The ink is traced from the FLATTENED picture, with a high threshold.
    /// The first version traced the raw photo at 0.12 and was only ever seen on
    /// drawn stand-ins; run on real photographs (TASKS 44, `Tools/egg_photo.swift`)
    /// every bit of texture — petals, a suit, a brick wall — became an edge and
    /// the picture came out nearly black (its brightness down 25-55%; now the
    /// ink outline costs it 3-9%, `meanLuma`).
    static func anime(_ cg: CGImage) -> CGImage {
        let input = CIImage(cgImage: cg)
        let smooth = CIFilter.noiseReduction()
        smooth.inputImage = input; smooth.noiseLevel = 0.04; smooth.sharpness = 0.2
        let median = CIFilter.median()
        median.inputImage = smooth.outputImage
        // Contrast 1.05, not 1.12: a contrast boost pivots on mid-grey and
        // pushed every dark subject (a suit, a black dog) toward black.
        let colour = CIFilter.colorControls()
        colour.inputImage = median.outputImage; colour.saturation = 1.45; colour.contrast = 1.05; colour.brightness = 0.03
        // Flattened in sRGB, not Core Image's linear light, where seven levels
        // leave almost none for the dark half of the picture.
        let perceptual = CIFilter.linearToSRGBToneCurve()
        perceptual.inputImage = colour.outputImage
        let levels = CIFilter.colorPosterize()
        levels.inputImage = perceptual.outputImage; levels.levels = 7
        let flat = CIFilter.sRGBToneCurveToLinear()
        flat.inputImage = levels.outputImage
        let lines = CIFilter.lineOverlay()
        lines.inputImage = flat.outputImage
        lines.nrNoiseLevel = 0.08; lines.nrSharpness = 0.5
        lines.edgeIntensity = 0.8; lines.threshold = 0.6; lines.contrast = 30
        guard let posterised = flat.outputImage, let ink = lines.outputImage else { return cg }
        let inked = ink.composited(over: posterised)
        // Keep only what the cut-out kept.
        let masked = CIFilter.blendWithAlphaMask()
        masked.inputImage = inked
        masked.backgroundImage = CIImage.empty()
        masked.maskImage = input
        guard let out = masked.outputImage?.cropped(to: input.extent),
              let made = ci.createCGImage(out, from: input.extent) else { return cg }
        return made
    }

    /// Mean brightness (0…1) of a picture's visible pixels — how the harness
    /// checks the anime look keeps a photo's light.
    static func meanLuma(_ cg: CGImage) -> Double {
        let w = 64, h = max(1, 64 * cg.height / max(cg.width, 1))
        guard let ctx = rgbaContext(w, h) else { return 0 }
        ctx.draw(cg, in: CGRect(x: 0, y: 0, width: w, height: h))
        guard let data = ctx.data else { return 0 }
        let px = data.bindMemory(to: UInt8.self, capacity: ctx.bytesPerRow * h)
        var sum = 0.0, n = 0.0
        for y in 0..<h {
            for x in 0..<w {
                let o = y * ctx.bytesPerRow + x * 4
                let a = Double(px[o + 3])
                guard a > 128 else { continue }
                // premultiplied: un-premultiply before weighting
                sum += (0.299 * Double(px[o]) + 0.587 * Double(px[o + 1]) + 0.114 * Double(px[o + 2])) / a
                n += 1
            }
        }
        return n > 0 ? sum / n : 0
    }

    /// A white sticker border round the cut-out's silhouette.
    static func sticker(_ cg: CGImage, border: CGFloat = 10) -> CGImage {
        let input = CIImage(cgImage: cg)
        let pad = border * 2
        let padded = input.transformed(by: CGAffineTransform(translationX: pad, y: pad))
        let canvas = CGRect(x: 0, y: 0, width: input.extent.width + pad * 2, height: input.extent.height + pad * 2)
        let grow = CIFilter.morphologyMaximum()
        grow.inputImage = padded; grow.radius = Float(border)
        let white = CIFilter.colorMatrix()
        white.inputImage = grow.outputImage
        white.rVector = CIVector(x: 0, y: 0, z: 0, w: 0); white.gVector = CIVector(x: 0, y: 0, z: 0, w: 0)
        white.bVector = CIVector(x: 0, y: 0, z: 0, w: 0); white.aVector = CIVector(x: 0, y: 0, z: 0, w: 1)
        white.biasVector = CIVector(x: 1, y: 1, z: 1, w: 0)
        guard let halo = white.outputImage else { return cg }
        let out = padded.composited(over: halo).cropped(to: canvas)
        return ci.createCGImage(out, from: canvas) ?? cg
    }

    // MARK: - Bringing it to life

    /// How the photo should move: what Apple's on-device classifier sees in
    /// it — an animal walks, a vehicle rolls, a bird flaps, anything else hops.
    static func guessRig(_ cg: CGImage) async -> EggRig {
        await Task.detached(priority: .userInitiated) { () -> EggRig in
            let request = VNClassifyImageRequest()
            guard (try? VNImageRequestHandler(cgImage: cg, options: [:]).perform([request])) != nil,
                  let seen = request.results?.filter({ $0.confidence > 0.12 }).map({ $0.identifier.lowercased() })
            else { return .hop }
            return rig(forLabels: seen)
        }.value
    }

    /// The classifier's labels -> a rig. Split out so it can be read alone.
    static func rig(forLabels seen: [String]) -> EggRig {
        func any(_ words: [String]) -> Bool { seen.contains { id in words.contains { id.contains($0) } } }
        if any(["car", "vehicle", "truck", "bus", "bicycle", "motorcycle", "train", "tractor", "scooter", "wheel", "van"]) { return .roll }
        if any(["bird", "butterfly", "insect", "parrot", "owl", "eagle", "duck", "bat", "moth"]) { return .flap }
        if any(["dog", "cat", "horse", "canine", "feline", "mammal", "animal", "puppy", "pony", "lion", "tiger",
                "bear", "cow", "sheep", "goat", "deer", "wolf", "fox", "pig", "rabbit"]) { return .walk }
        return .hop
    }

    /// The animal's legs, from Apple's animal body-pose detector (iOS 17 /
    /// macOS 14): [topX, topY, pawX, pawY] per leg, 0…1 of the picture from
    /// its top-left. nil when no animal's pose is found — the walk then uses
    /// the bottom third.
    static func findLegs(_ cg: CGImage) async -> [[Double]]? {
        guard #available(iOS 17.0, macOS 14.0, *) else { return nil }
        return await Task.detached(priority: .userInitiated) { () -> [[Double]]? in
            // Over white: the detector was trained on photos, not transparency.
            guard let ctx = rgbaContext(cg.width, cg.height) else { return nil }
            let r = CGRect(x: 0, y: 0, width: cg.width, height: cg.height)
            ctx.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1)); ctx.fill(r)
            ctx.draw(cg, in: r)
            guard let flat = ctx.makeImage() else { return nil }
            let request = VNDetectAnimalBodyPoseRequest()
            guard (try? VNImageRequestHandler(cgImage: flat, options: [:]).perform([request])) != nil,
                  let pose = request.results?.first,
                  let pts = try? pose.recognizedPoints(.all) else { return nil }
            typealias J = VNAnimalBodyPoseObservation.JointName
            let legs: [(J, J, J)] = [(.leftFrontElbow, .leftFrontKnee, .leftFrontPaw),
                                     (.rightFrontElbow, .rightFrontKnee, .rightFrontPaw),
                                     (.leftBackElbow, .leftBackKnee, .leftBackPaw),
                                     (.rightBackElbow, .rightBackKnee, .rightBackPaw)]
            var out: [[Double]] = []
            for (a, b, paw) in legs {
                guard let p = pts[paw], p.confidence > 0.2,
                      let top = [pts[a], pts[b]].compactMap({ $0 }).first(where: { $0.confidence > 0.2 }) else { continue }
                // Vision's origin is the bottom-left.
                out.append([Double(top.location.x), 1 - Double(top.location.y),
                            Double(p.location.x), 1 - Double(p.location.y)])
            }
            return out.count >= 2 ? out : nil
        }.value
    }

    /// The finished graphic: cut out (lasso, else automatic), styled, stickered.
    static func render(photo: CGImage, lasso: [CGPoint]?, anime: Bool) async -> CGImage? {
        let base = normalised(photo)
        let cut: CGImage?
        if let lasso, !lasso.isEmpty { cut = lassoCutout(base, points: lasso) }
        else { cut = await autoCutout(base) }
        guard let cut else { return nil }
        return sticker(anime ? self.anime(cut) : cut)
    }
}
