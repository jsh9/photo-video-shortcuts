// Writes a test photo with Apple's ImageIO, the way an iPhone or camera would:
// HEIC or JPEG, with EXIF (date, time zone, camera, lens, exposure), GPS and an
// orientation.
//
// usage: make_photo IN.png OUT.heic|OUT.jpg [--orientation N] [--p3]
//                   [--depth16] [--make MAKE] [--model MODEL]
//                   [--hdr]
//
// --p3 tags the pixels as Display P3; --depth16 hands ImageIO 16-bit pixels
// (which it may store as 10-bit HEIC). --hdr (HEIC, macOS 15 or later) adds an
// ISO 21496-1 gain map, as iPhones do since iOS 18. In the HDR rendition,
// linear values v become v * (1 + 3 v^2): white is 4 times as bright, dark
// tones barely change.
import CoreGraphics
import CoreImage
import Foundation
import ImageIO
import UniformTypeIdentifiers

func fail(_ message: String) -> Never {
  FileHandle.standardError.write((message + "\n").data(using: .utf8)!)
  exit(1)
}

var args = Array(CommandLine.arguments.dropFirst())
guard args.count >= 2 else { fail("usage: make_photo IN.png OUT.heic|OUT.jpg [options]") }
let input = URL(fileURLWithPath: args.removeFirst())
let output = URL(fileURLWithPath: args.removeFirst())
var orientation = 1
var p3 = false
var depth16 = false
var make = "TestMake"
var model = "TestModel 1"
var hdr = false
while !args.isEmpty {
  let a = args.removeFirst()
  switch a {
  case "--orientation": orientation = Int(args.removeFirst())!
  case "--p3": p3 = true
  case "--depth16": depth16 = true
  case "--make": make = args.removeFirst()
  case "--model": model = args.removeFirst()
  case "--hdr": hdr = true
  default: fail("unknown option \(a)")
  }
}

guard let source = CGImageSourceCreateWithURL(input as CFURL, nil),
  var image = CGImageSourceCreateImageAtIndex(source, 0, nil)
else { fail("cannot read \(input.path)") }

let space = CGColorSpace(name: p3 ? CGColorSpace.displayP3 : CGColorSpace.sRGB)!
// Same pixel values, tagged with the chosen color space.
image = image.copy(colorSpace: space) ?? image
if depth16 {
  let info = CGImageAlphaInfo.noneSkipLast.rawValue | CGBitmapInfo.byteOrder16Little.rawValue
  guard let ctx = CGContext(data: nil, width: image.width, height: image.height,
    bitsPerComponent: 16, bytesPerRow: image.width * 8, space: space, bitmapInfo: info)
  else { fail("cannot create a 16-bit context") }
  ctx.draw(image, in: CGRect(x: 0, y: 0, width: image.width, height: image.height))
  image = ctx.makeImage()!
}

let type = output.pathExtension.lowercased() == "heic" ? UTType.heic : UTType.jpeg

// The gain map: Core Image computes it from the SDR and HDR renditions and
// writes a HEIC, from which ImageIO copies it into the photo below.
var gainMap: CFDictionary? = nil
if hdr {
  guard type == .heic else { fail("--hdr needs a HEIC output") }
  guard #available(macOS 15.0, *) else { fail("--hdr needs macOS 15 or later") }
  let sdr = CIImage(cgImage: image)
  let squared = sdr.applyingFilter("CIMultiplyCompositing", parameters: [kCIInputBackgroundImageKey: sdr])
  let gain = squared.applyingFilter("CIColorMatrix", parameters: [
    "inputRVector": CIVector(x: 3, y: 0, z: 0, w: 0),
    "inputGVector": CIVector(x: 0, y: 3, z: 0, w: 0),
    "inputBVector": CIVector(x: 0, y: 0, z: 3, w: 0),
    "inputAVector": CIVector(x: 0, y: 0, z: 0, w: 1),
    "inputBiasVector": CIVector(x: 1, y: 1, z: 1, w: 0),
  ])
  let hdrImage = sdr.applyingFilter("CIMultiplyCompositing", parameters: [kCIInputBackgroundImageKey: gain])
  let temporary = FileManager.default.temporaryDirectory
    .appendingPathComponent(UUID().uuidString + ".heic")
  defer { try? FileManager.default.removeItem(at: temporary) }
  do {
    try CIContext().writeHEIFRepresentation(
      of: sdr, to: temporary, format: .RGBA8, colorSpace: space,
      options: [.hdrImage: hdrImage, .hdrGainMapAsRGB: false])
  } catch { fail("cannot write the HDR rendition: \(error)") }
  // Read into memory: ImageIO decodes lazily, after the file is removed.
  guard let data = try? Data(contentsOf: temporary),
    let written = CGImageSourceCreateWithData(data as CFData, nil),
    let base = CGImageSourceCreateImageAtIndex(written, 0, nil),
    let info = CGImageSourceCopyAuxiliaryDataInfoAtIndex(written, 0, kCGImageAuxiliaryDataTypeISOGainMap)
  else { fail("Core Image wrote no ISO gain map") }
  image = base
  gainMap = info
}
guard let dest = CGImageDestinationCreateWithURL(output as CFURL, type.identifier as CFString, 1, nil)
else { fail("cannot write \(output.path)") }

let properties: [CFString: Any] = [
  kCGImageDestinationLossyCompressionQuality: 0.95,
  kCGImagePropertyOrientation: orientation,
  kCGImagePropertyTIFFDictionary: [
    kCGImagePropertyTIFFMake: make,
    kCGImagePropertyTIFFModel: model,
  ],
  kCGImagePropertyExifDictionary: [
    kCGImagePropertyExifDateTimeOriginal: "2024:05:06 07:08:09",
    kCGImagePropertyExifOffsetTimeOriginal: "+02:00",
    kCGImagePropertyExifSubsecTimeOriginal: "123",
    kCGImagePropertyExifLensModel: "Test Lens 26mm f/1.8",
    kCGImagePropertyExifFNumber: 1.8,
    kCGImagePropertyExifExposureTime: 0.01,
    kCGImagePropertyExifISOSpeedRatings: [200],
    kCGImagePropertyExifFocalLenIn35mmFilm: 26,
  ],
  kCGImagePropertyGPSDictionary: [
    kCGImagePropertyGPSLatitude: 48.8584,
    kCGImagePropertyGPSLatitudeRef: "N",
    kCGImagePropertyGPSLongitude: 2.2945,
    kCGImagePropertyGPSLongitudeRef: "E",
    kCGImagePropertyGPSAltitude: 35.5,
    kCGImagePropertyGPSAltitudeRef: 0,
  ],
]
CGImageDestinationAddImage(dest, image, properties as CFDictionary)
if let gainMap = gainMap {
  if #available(macOS 15.0, *) {
    CGImageDestinationAddAuxiliaryDataInfo(dest, kCGImageAuxiliaryDataTypeISOGainMap, gainMap)
  }
}
if !CGImageDestinationFinalize(dest) { fail("cannot finalize \(output.path)") }
