import UIKit
import Vision
import CoreImage
import CoreImage.CIFilterBuiltins

/// Turning a photo into an Easter-egg graphic, entirely on the phone:
///
///     cut out     automatic (Vision's subject lifting, iOS 17+) or a lasso
///                 the user draws round their character
///     style       kept as it is, or "anime": saturated flat cel colours and
///                 ink lines, from Core Image's own filters
///     sticker     a white outline round the cut-out, so a photo sits in the
///                 same style as the drawn figures
///
/// Nothing is sent anywhere and nothing is downloaded: the anime look is
/// built from filters that ship with iOS, which is why it is a stylisation
/// and not a neural "anime-ifier" (the free ones are licensed for
/// non-commercial use only and would have to be downloaded).
enum EggImageTools {
    private static let ci = CIContext()

    /// At most `side` pixels on the long edge, upright.
    static func normalised(_ image: UIImage, side: CGFloat = 1024) -> UIImage {
        let s = image.size
        let k = min(1, side / max(s.width, s.height))
        let size = CGSize(width: (s.width * k).rounded(), height: (s.height * k).rounded())
        let fmt = UIGraphicsImageRendererFormat.default()
        fmt.scale = 1
        return UIGraphicsImageRenderer(size: size, format: fmt).image { _ in
            image.draw(in: CGRect(origin: .zero, size: size))
        }
    }

    static var canCutOutAutomatically: Bool {
        if #available(iOS 17.0, *) { return true }
        return false
    }

    /// The photo's subject(s) on a transparent background, cropped to them —
    /// or nil when there is no subject to find (or the phone is too old).
    static func autoCutout(_ image: UIImage) async -> UIImage? {
        guard #available(iOS 17.0, *), let cg = image.cgImage else { return nil }
        return await Task.detached(priority: .userInitiated) { () -> UIImage? in
            let request = VNGenerateForegroundInstanceMaskRequest()
            let handler = VNImageRequestHandler(cgImage: cg, options: [:])
            guard (try? handler.perform([request])) != nil,
                  let result = request.results?.first,
                  !result.allInstances.isEmpty,
                  let buffer = try? result.generateMaskedImage(ofInstances: result.allInstances, from: handler,
                                                               croppedToInstancesExtent: true)
            else { return nil }
            let ciImage = CIImage(cvPixelBuffer: buffer)
            guard let out = CIContext().createCGImage(ciImage, from: ciImage.extent) else { return nil }
            return UIImage(cgImage: out)
        }.value
    }

    /// The part of the photo inside a hand-drawn outline (points 0…1 of the
    /// image), cropped to it.
    static func lassoCutout(_ image: UIImage, points: [CGPoint]) -> UIImage? {
        guard points.count >= 3 else { return nil }
        let s = image.size
        let path = UIBezierPath()
        path.move(to: CGPoint(x: points[0].x * s.width, y: points[0].y * s.height))
        for p in points.dropFirst() { path.addLine(to: CGPoint(x: p.x * s.width, y: p.y * s.height)) }
        path.close()
        let box = path.bounds.intersection(CGRect(origin: .zero, size: s)).integral
        guard box.width > 8, box.height > 8 else { return nil }
        let fmt = UIGraphicsImageRendererFormat.default()
        fmt.scale = 1
        fmt.opaque = false
        return UIGraphicsImageRenderer(size: box.size, format: fmt).image { ctx in
            ctx.cgContext.translateBy(x: -box.minX, y: -box.minY)
            path.addClip()
            image.draw(at: .zero)
        }
    }

    /// Flat, saturated cel colours with ink lines, keeping the cut-out's
    /// transparency.
    static func anime(_ image: UIImage) -> UIImage {
        guard let input = CIImage(image: image) else { return image }
        let smooth = CIFilter.noiseReduction()
        smooth.inputImage = input; smooth.noiseLevel = 0.04; smooth.sharpness = 0.2
        let colour = CIFilter.colorControls()
        colour.inputImage = smooth.outputImage; colour.saturation = 1.45; colour.contrast = 1.12; colour.brightness = 0.03
        let flat = CIFilter.colorPosterize()
        flat.inputImage = colour.outputImage; flat.levels = 7
        let lines = CIFilter.lineOverlay()
        lines.inputImage = input
        lines.nrNoiseLevel = 0.05; lines.nrSharpness = 0.7
        lines.edgeIntensity = 1.2; lines.threshold = 0.12; lines.contrast = 40
        guard let posterised = flat.outputImage, let ink = lines.outputImage else { return image }
        let inked = ink.composited(over: posterised)
        // Keep only what the cut-out kept.
        let masked = CIFilter.blendWithAlphaMask()
        masked.inputImage = inked
        masked.backgroundImage = CIImage.empty()
        masked.maskImage = input
        guard let out = masked.outputImage?.cropped(to: input.extent),
              let cg = ci.createCGImage(out, from: input.extent) else { return image }
        return UIImage(cgImage: cg)
    }

    /// A white sticker border round the cut-out's silhouette.
    static func sticker(_ image: UIImage, border: CGFloat = 10) -> UIImage {
        guard let input = CIImage(image: image) else { return image }
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
        guard let halo = white.outputImage else { return image }
        let out = padded.composited(over: halo).cropped(to: canvas)
        guard let cg = ci.createCGImage(out, from: canvas) else { return image }
        return UIImage(cgImage: cg)
    }

    // MARK: - Bringing it to life

    /// How the photo should move: what Apple's on-device classifier sees in
    /// it — an animal walks, a vehicle rolls, a bird flaps, anything else hops.
    static func guessRig(_ image: UIImage) async -> EggRig {
        guard let cg = image.cgImage else { return .hop }
        return await Task.detached(priority: .userInitiated) { () -> EggRig in
            let request = VNClassifyImageRequest()
            guard (try? VNImageRequestHandler(cgImage: cg, options: [:]).perform([request])) != nil,
                  let seen = request.results?.filter({ $0.confidence > 0.12 }).map({ $0.identifier.lowercased() })
            else { return .hop }
            func any(_ words: [String]) -> Bool { seen.contains { id in words.contains { id.contains($0) } } }
            if any(["car", "vehicle", "truck", "bus", "bicycle", "motorcycle", "train", "tractor", "scooter", "wheel", "van"]) { return .roll }
            if any(["bird", "butterfly", "insect", "parrot", "owl", "eagle", "duck", "bat", "moth"]) { return .flap }
            if any(["dog", "cat", "horse", "canine", "feline", "mammal", "animal", "puppy", "pony", "lion", "tiger",
                    "bear", "cow", "sheep", "goat", "deer", "wolf", "fox", "pig", "rabbit"]) { return .walk }
            return .hop
        }.value
    }

    /// The animal's legs, from Apple's animal body-pose detector (iOS 17):
    /// [topX, topY, pawX, pawY] per leg, 0…1 of the picture from its top-left.
    /// nil when no animal's pose is found — the walk then uses the bottom third.
    static func findLegs(_ image: UIImage) async -> [[Double]]? {
        guard #available(iOS 17.0, *), let cg = image.cgImage else { return nil }
        return await Task.detached(priority: .userInitiated) { () -> [[Double]]? in
            // Over white: the detector was trained on photos, not transparency.
            let size = CGSize(width: cg.width, height: cg.height)
            let flat = UIGraphicsImageRenderer(size: size).image { ctx in
                UIColor.white.setFill(); ctx.fill(CGRect(origin: .zero, size: size))
                UIImage(cgImage: cg).draw(in: CGRect(origin: .zero, size: size))
            }
            guard let flatCG = flat.cgImage else { return nil }
            let request = VNDetectAnimalBodyPoseRequest()
            guard (try? VNImageRequestHandler(cgImage: flatCG, options: [:]).perform([request])) != nil,
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

    /// Where the wheels are in a cut-out (`EggPuppet.findWheels`).
    static func findWheels(_ image: UIImage) -> [[Double]] {
        image.cgImage.map(EggPuppet.findWheels) ?? []
    }

    /// The finished graphic: cut out (lasso, else automatic), styled, stickered.
    static func render(photo: UIImage, lasso: [CGPoint]?, anime: Bool) async -> UIImage? {
        let base = normalised(photo)
        let cut: UIImage?
        if let lasso, !lasso.isEmpty { cut = lassoCutout(base, points: lasso) }
        else { cut = await autoCutout(base) }
        guard let cut else { return nil }
        return sticker(anime ? self.anime(cut) : cut)
    }
}
