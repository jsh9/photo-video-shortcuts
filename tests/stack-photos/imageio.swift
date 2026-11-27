// Stack Photos' image steps as ImageIO takes them, for the tests:
//
//   imageio jpeg OUT.jpg WIDTH HEIGHT
//       a JPEG as the shortcut's last steps write one: Combine Images draws
//       into an RGBA device-RGB bitmap and writes it as PNG with no
//       properties (WFImageCombineAction); Convert Image writes that as JPEG
//       at quality 0.9 with the metadata dictionaries set to null
//       (WFImageContentItem generateImageFileForType:includingMetadata:NO).
//       Left half red, right half blue.
//   imageio props FILE
//       what ImageIO (and so Photos) reads: the size, the EXIF dates and
//       offsets, ColorSpace, and a checksum of the decoded pixels, as JSON.
import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

func fail(_ message: String) -> Never {
  FileHandle.standardError.write((message + "\n").data(using: .utf8)!)
  exit(1)
}

func jpeg(_ out: String, _ width: Int, _ height: Int) {
  let space = CGColorSpaceCreateDeviceRGB()
  guard
    let context = CGContext(
      data: nil, width: width, height: height, bitsPerComponent: 8,
      bytesPerRow: width * 4, space: space,
      bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)
  else { fail("no bitmap") }
  context.setFillColor(red: 0.9, green: 0.1, blue: 0.1, alpha: 1)
  context.fill(CGRect(x: 0, y: 0, width: width / 2, height: height))
  context.setFillColor(red: 0.1, green: 0.2, blue: 0.9, alpha: 1)
  context.fill(CGRect(x: width / 2, y: 0, width: width - width / 2, height: height))
  let png = NSMutableData()
  let toPNG = CGImageDestinationCreateWithData(png, UTType.png.identifier as CFString, 1, nil)!
  CGImageDestinationAddImage(toPNG, context.makeImage()!, nil)
  CGImageDestinationFinalize(toPNG)
  let source = CGImageSourceCreateWithData(png, nil)!
  let toJPEG = CGImageDestinationCreateWithURL(
    URL(fileURLWithPath: out) as CFURL, UTType.jpeg.identifier as CFString, 1, nil)!
  let properties: [CFString: Any] = [
    kCGImagePropertyExifDictionary: kCFNull!,
    kCGImagePropertyTIFFDictionary: kCFNull!,
    kCGImagePropertyGPSDictionary: kCFNull!,
    kCGImagePropertyIPTCDictionary: kCFNull!,
    kCGImagePropertyExifAuxDictionary: kCFNull!,
    kCGImageDestinationLossyCompressionQuality: 0.9,
  ]
  CGImageDestinationAddImageFromSource(toJPEG, source, 0, properties as CFDictionary)
  if !CGImageDestinationFinalize(toJPEG) { fail("could not write \(out)") }
}

func props(_ path: String) {
  guard let source = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil),
    let all = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [String: Any],
    let image = CGImageSourceCreateImageAtIndex(source, 0, nil)
  else { fail("ImageIO can't read \(path)") }
  let exif = all[kCGImagePropertyExifDictionary as String] as? [String: Any] ?? [:]
  let data = image.dataProvider!.data! as Data
  var sum: UInt64 = 0
  for byte in data { sum = sum &* 31 &+ UInt64(byte) }
  var result: [String: Any] = [
    "width": image.width, "height": image.height, "pixels": String(sum),
  ]
  for key in [
    "DateTimeOriginal", "DateTimeDigitized", "OffsetTime", "OffsetTimeOriginal",
    "OffsetTimeDigitized", "ColorSpace",
  ] {
    if let value = exif[key] { result[key] = value }
  }
  let json = try! JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
  print(String(data: json, encoding: .utf8)!)
}

let args = CommandLine.arguments
if args.count == 5 && args[1] == "jpeg", let w = Int(args[3]), let h = Int(args[4]) {
  jpeg(args[2], w, h)
} else if args.count == 3 && args[1] == "props" {
  props(args[2])
} else {
  fail("usage: imageio jpeg OUT.jpg WIDTH HEIGHT | imageio props FILE")
}
