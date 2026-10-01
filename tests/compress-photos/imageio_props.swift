// Prints the metadata Apple's ImageIO reads from image files: the same
// framework Photos uses on import.
// usage: imageio_props [--json] FILE...
import Foundation
import ImageIO

var args = Array(CommandLine.arguments.dropFirst())
let json = args.first == "--json"
if json { args.removeFirst() }

var results: [[String: Any]] = []
for path in args {
  let url = URL(fileURLWithPath: path) as CFURL
  guard let src = CGImageSourceCreateWithURL(url, nil),
    let props = CGImageSourceCopyPropertiesAtIndex(src, 0, nil) as? [CFString: Any]
  else {
    results.append(["path": path, "error": "ImageIO cannot read this file"])
    continue
  }
  let exif = props[kCGImagePropertyExifDictionary] as? [CFString: Any] ?? [:]
  let tiff = props[kCGImagePropertyTIFFDictionary] as? [CFString: Any] ?? [:]
  let gps = props[kCGImagePropertyGPSDictionary] as? [CFString: Any] ?? [:]
  let w = props[kCGImagePropertyPixelWidth] as? Int ?? 0
  let h = props[kCGImagePropertyPixelHeight] as? Int ?? 0
  let orientation = props[kCGImagePropertyOrientation] as? Int ?? 1
  var r: [String: Any] = [
    "path": path,
    "type": (CGImageSourceGetType(src) as String?) ?? "-",
    "upright": orientation >= 5 ? "\(h)x\(w)" : "\(w)x\(h)",
    "orientation": orientation,
  ]
  let fields: [(String, Any?)] = [
    ("color", props[kCGImagePropertyProfileName]),
    ("taken", exif[kCGImagePropertyExifDateTimeOriginal]),
    ("offset", exif[kCGImagePropertyExifOffsetTimeOriginal]),
    ("subsec", exif[kCGImagePropertyExifSubsecTimeOriginal]),
    ("make", tiff[kCGImagePropertyTIFFMake]),
    ("model", tiff[kCGImagePropertyTIFFModel]),
    ("lens", exif[kCGImagePropertyExifLensModel]),
    ("fnumber", exif[kCGImagePropertyExifFNumber]),
    ("exposure", exif[kCGImagePropertyExifExposureTime]),
    ("iso", (exif[kCGImagePropertyExifISOSpeedRatings] as? [Any])?.first),
    ("focal35", exif[kCGImagePropertyExifFocalLenIn35mmFilm]),
    ("lat", gps[kCGImagePropertyGPSLatitude].map { "\($0)\(gps[kCGImagePropertyGPSLatitudeRef] ?? "")" }),
    ("lon", gps[kCGImagePropertyGPSLongitude].map { "\($0)\(gps[kCGImagePropertyGPSLongitudeRef] ?? "")" }),
    ("alt", gps[kCGImagePropertyGPSAltitude]),
  ]
  for (k, v) in fields { if let v = v { r[k] = "\(v)" } }
  results.append(r)
}

if json {
  let data = try! JSONSerialization.data(withJSONObject: results, options: [.prettyPrinted, .sortedKeys])
  print(String(data: data, encoding: .utf8)!)
} else {
  for r in results {
    print("\(r["path"]!):")
    for k in ["error", "type", "upright", "orientation", "color", "taken", "offset", "make", "model", "lens",
      "fnumber", "exposure", "iso", "lat", "lon", "alt"]
    {
      if let v = r[k] { print("  \(k.padding(toLength: 12, withPad: " ", startingAt: 0))\(v)") }
    }
  }
}
