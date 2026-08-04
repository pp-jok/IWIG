import AppKit
import Foundation
import Vision

guard CommandLine.arguments.count > 1 else {
    fputs("usage: ocr_macos.swift <image> [image ...]\n", stderr)
    exit(2)
}
var output: [[String: Any]] = []
for path in CommandLine.arguments.dropFirst() {
    guard let image = NSImage(contentsOfFile: path), let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else { output.append(["text": "", "lines": []]); continue }
    let request = VNRecognizeTextRequest(); request.recognitionLevel = .accurate; request.usesLanguageCorrection = true; request.recognitionLanguages = ["zh-Hans", "en-US"]
    let handler = VNImageRequestHandler(cgImage: cgImage, options: [:]); try handler.perform([request])
    let lines = (request.results ?? []).compactMap { observation -> [String: Any]? in
        guard let candidate = observation.topCandidates(1).first else { return nil }
        let box = observation.boundingBox
        return ["text": candidate.string, "confidence": candidate.confidence, "bbox": ["x": box.origin.x, "y": box.origin.y, "width": box.size.width, "height": box.size.height]]
    }
    output.append(["text": lines.compactMap { $0["text"] as? String }.joined(separator: "\n"), "lines": lines])
}
let data = try JSONSerialization.data(withJSONObject: output, options: [])
FileHandle.standardOutput.write(data)
