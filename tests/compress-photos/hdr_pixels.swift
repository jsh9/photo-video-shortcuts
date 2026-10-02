// Decodes an image the way Apple's frameworks show it in HDR: Core Image
// applies its gain map (.expandToHDR) and its orientation. Writes the pixels as
// linear Display P3 where 1.0 is SDR white (HDR highlights are above 1): the
// width and height as two Int32, then 4 Float32 (RGBA) per pixel, all
// little-endian.
//
// With --sdr, decodes it as an SDR screen shows it instead: ImageIO's SDR
// decoding (kCGImageSourceDecodeToSDR), which shows a gain map photo's SDR
// image and tone-maps HDR pixels (with the image's tone curve, if it has
// one), then the orientation.
//
// With --profile, writes instead the ICC profile of ImageIO's HDR decoding
// (kCGImageSourceDecodeToHDR) of a gain map photo: on recent macOS it carries
// the tone curve Apple derives from the gain map ('hdgm' tag).
// usage: hdr_pixels [--sdr | --profile] IN OUT
import CoreImage
import Foundation
import ImageIO

func fail(_ message: String) -> Never {
  FileHandle.standardError.write((message + "\n").data(using: .utf8)!)
  exit(1)
}

var args = Array(CommandLine.arguments.dropFirst())
let mode = args.first?.hasPrefix("--") == true ? args.removeFirst() : ""
let sdr = mode == "--sdr"
guard args.count == 2, ["", "--sdr", "--profile"].contains(mode) else {
  fail("usage: hdr_pixels [--sdr | --profile] IN OUT")
}
let input = URL(fileURLWithPath: args[0])

if mode == "--profile" {
  guard let source = CGImageSourceCreateWithURL(input as CFURL, nil) else { fail("cannot read \(input.path)") }
  let options = [kCGImageSourceDecodeRequest: kCGImageSourceDecodeToHDR] as CFDictionary
  guard let image = CGImageSourceCreateImageAtIndex(source, 0, options),
    let icc = image.colorSpace?.copyICCData() as Data?
  else { fail("no HDR profile for \(input.path)") }
  do { try icc.write(to: URL(fileURLWithPath: args[1])) } catch { fail("cannot write \(args[1])") }
  exit(0)
}

func sdrImage(_ url: URL) -> CIImage? {
  guard let source = CGImageSourceCreateWithURL(url as CFURL, nil) else { return nil }
  let options = [kCGImageSourceDecodeRequest: kCGImageSourceDecodeToSDR] as CFDictionary
  guard let cgImage = CGImageSourceCreateImageAtIndex(source, 0, options) else { return nil }
  let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any]
  let raw = properties?[kCGImagePropertyOrientation] as? UInt32 ?? 1
  let orientation = CGImagePropertyOrientation(rawValue: raw) ?? .up
  return CIImage(cgImage: cgImage).oriented(orientation)
}

let decoded =
  sdr
  ? sdrImage(input)
  : CIImage(contentsOf: input, options: [.expandToHDR: true, .applyOrientationProperty: true])
guard let image = decoded else { fail("cannot read \(input.path)") }
let extent = image.extent.integral
let width = Int(extent.width), height = Int(extent.height)
var pixels = [Float](repeating: 0, count: width * height * 4)
let space = CGColorSpace(name: CGColorSpace.extendedLinearDisplayP3)!
pixels.withUnsafeMutableBytes { buffer in
  CIContext().render(
    image.transformed(by: CGAffineTransform(translationX: -extent.minX, y: -extent.minY)),
    toBitmap: buffer.baseAddress!, rowBytes: width * 16,
    bounds: CGRect(x: 0, y: 0, width: width, height: height), format: .RGBAf, colorSpace: space)
}
guard let file = fopen(args[1], "wb") else { fail("cannot write \(args[1])") }
let size: [Int32] = [Int32(width), Int32(height)]
let written = size.withUnsafeBytes { fwrite($0.baseAddress!, 1, $0.count, file) }
  + pixels.withUnsafeBytes { fwrite($0.baseAddress!, 1, $0.count, file) }
if fclose(file) != 0 || written != 8 + pixels.count * 4 { fail("cannot write \(args[1])") }
