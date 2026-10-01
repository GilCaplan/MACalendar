import UIKit

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

    static var canCutOutAutomatically: Bool { EggImageCore.canCutOutAutomatically }

    // Everything below is `EggImageCore` — the ONE copy the Mac runs too
    // (TASKS 46) — in `UIImage`s. `normalised` stays here: it is the step that
    // applies the photo's orientation, which a `CGImage` does not carry.

    /// The photo's subject(s) on a transparent background, cropped to them —
    /// or nil when there is no subject to find (or the phone is too old).
    static func autoCutout(_ image: UIImage) async -> UIImage? {
        guard let cg = image.cgImage else { return nil }
        return await EggImageCore.autoCutout(cg).map { UIImage(cgImage: $0) }
    }

    /// The part of the photo inside a hand-drawn outline (points 0…1 of the
    /// image), cropped to it.
    static func lassoCutout(_ image: UIImage, points: [CGPoint]) -> UIImage? {
        guard let cg = normalised(image, side: max(image.size.width, image.size.height)).cgImage else { return nil }
        return EggImageCore.lassoCutout(cg, points: points).map { UIImage(cgImage: $0) }
    }

    /// Flat, saturated cel colours with ink lines, keeping the cut-out's
    /// transparency.
    static func anime(_ image: UIImage) -> UIImage {
        guard let cg = image.cgImage else { return image }
        return UIImage(cgImage: EggImageCore.anime(cg))
    }

    /// A white sticker border round the cut-out's silhouette.
    static func sticker(_ image: UIImage, border: CGFloat = 10) -> UIImage {
        guard let cg = image.cgImage else { return image }
        return UIImage(cgImage: EggImageCore.sticker(cg, border: border))
    }

    // MARK: - Bringing it to life

    /// How the photo should move (`EggImageCore.guessRig`).
    static func guessRig(_ image: UIImage) async -> EggRig {
        guard let cg = image.cgImage else { return .hop }
        return await EggImageCore.guessRig(cg)
    }

    /// The animal's legs (`EggImageCore.findLegs`).
    static func findLegs(_ image: UIImage) async -> [[Double]]? {
        guard let cg = image.cgImage else { return nil }
        return await EggImageCore.findLegs(cg)
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
