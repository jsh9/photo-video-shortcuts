// Decodes an image the way Apple's frameworks show it in HDR: Core Image
// applies its gain map (.expandToHDR) and its orientation. Writes the pixels as
// linear Display P3 where 1.0 is SDR white (HDR highlights are above 1): the
// width and height as two Int32, then 4 Float32 (RGBA) per pixel, all
// little-endian.
// usage: hdr_pixels IN OUT
import CoreImage
import Foundation

func fail(_ message: String) -> Never {
  FileHandle.standardError.write((message + "\n").data(using: .utf8)!)
  exit(1)
}

let args = CommandLine.arguments
guard args.count == 3 else { fail("usage: hdr_pixels IN OUT") }
let input = URL(fileURLWithPath: args[1])
guard let image = CIImage(contentsOf: input, options: [.expandToHDR: true, .applyOrientationProperty: true])
else { fail("cannot read \(input.path)") }
let extent = image.extent.integral
let width = Int(extent.width), height = Int(extent.height)
var pixels = [Float](repeating: 0, count: width * height * 4)
let space = CGColorSpace(name: CGColorSpace.extendedLinearDisplayP3)!
pixels.withUnsafeMutableBytes { buffer in
  CIContext().render(
    image, toBitmap: buffer.baseAddress!, rowBytes: width * 16, bounds: extent, format: .RGBAf,
    colorSpace: space)
}
guard let file = fopen(args[2], "wb") else { fail("cannot write \(args[2])") }
let size: [Int32] = [Int32(width), Int32(height)]
let written = size.withUnsafeBytes { fwrite($0.baseAddress!, 1, $0.count, file) }
  + pixels.withUnsafeBytes { fwrite($0.baseAddress!, 1, $0.count, file) }
if fclose(file) != 0 || written != 8 + pixels.count * 4 { fail("cannot write \(args[2])") }
