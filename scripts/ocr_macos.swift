import AppKit
import Foundation
import Vision

guard CommandLine.arguments.count == 2, let image = NSImage(contentsOfFile: CommandLine.arguments[1]), let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    fputs("usage: ocr_macos.swift <image>\n", stderr)
    exit(2)
}

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = true
request.recognitionLanguages = ["zh-Hans", "en-US"]
let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
try handler.perform([request])
let lines = (request.results ?? []).compactMap { $0.topCandidates(1).first?.string }
let data = try JSONSerialization.data(withJSONObject: ["text": lines.joined(separator: "\n"), "lines": lines], options: [])
FileHandle.standardOutput.write(data)
