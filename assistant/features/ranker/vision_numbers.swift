// Read the text in pictures with Apple Vision, on this machine, no network.
//
//   vision_numbers <image> [<image> ...]
//
// One line per recognised piece of text:
// `<image index>\t<top>\t<left>\t<height>\t<confidence>\t<text>`, the box in
// 0-1 of the picture measured from its TOP-left (Vision's own origin is the
// bottom-left), so Python can put the pieces in reading order.
// `ocr.py` compiles this once into a cache folder and keeps the rule for WHICH
// pieces are numbers in Python, where it is tested. Measured 2026-10-11 on a
// Chalice District screenshot (30 kingdoms in a grid): Vision read all 30 with
// nothing extra; Tesseract found 4, 2 of them wrong.

import AppKit
import Foundation
import Vision

for (index, path) in CommandLine.arguments.dropFirst().enumerated() {
    guard let image = NSImage(contentsOf: URL(fileURLWithPath: path)),
          let cg = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
        FileHandle.standardError.write("cannot read \(path)\n".data(using: .utf8)!)
        exit(2)
    }
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = false   // "#1172" is not a word to correct
    do {
        try VNImageRequestHandler(cgImage: cg).perform([request])
    } catch {
        FileHandle.standardError.write("vision failed on \(path): \(error)\n".data(using: .utf8)!)
        exit(3)
    }
    for observation in request.results ?? [] {
        if let best = observation.topCandidates(1).first {
            let text = best.string.replacingOccurrences(of: "\t", with: " ")
            let b = observation.boundingBox
            print("\(index)\t" + String(format: "%.4f\t%.4f\t%.4f\t%.2f\t", 1 - b.maxY, b.minX, b.height, best.confidence) + text)
        }
    }
}
