// Writes a small HEIC with a Portrait effects matte (an auxiliary image), as
// an iPhone's Portrait photo has, for photobatch's tests.
import CoreGraphics
import CoreVideo
import Foundation
import ImageIO
import UniformTypeIdentifiers

let out = URL(fileURLWithPath: CommandLine.arguments[1])
let w = 64, h = 48, mw = 32, mh = 24
var rgba = [UInt8](repeating: 0, count: w * h * 4)
for y in 0..<h { for x in 0..<w {
    let i = (y * w + x) * 4
    rgba[i] = UInt8(x * 4); rgba[i + 1] = UInt8(y * 5); rgba[i + 2] = 128; rgba[i + 3] = 255
} }
let ctx = CGContext(data: &rgba, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w * 4,
                    space: CGColorSpace(name: CGColorSpace.sRGB)!,
                    bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)!
let image = ctx.makeImage()!
var matte = [UInt8](repeating: 0, count: mw * mh)
for y in 0..<mh { for x in 0..<mw { matte[y * mw + x] = (x > 8 && x < 24) ? 255 : 0 } }
let info: [CFString: Any] = [
    kCGImageAuxiliaryDataInfoData: Data(matte) as CFData,
    kCGImageAuxiliaryDataInfoDataDescription: [
        "Width": mw, "Height": mh, "BytesPerRow": mw,
        "PixelFormat": kCVPixelFormatType_OneComponent8,
    ] as CFDictionary,
]
let dest = CGImageDestinationCreateWithURL(out as CFURL, UTType.heic.identifier as CFString, 1, nil)!
CGImageDestinationAddImage(dest, image, [kCGImageDestinationLossyCompressionQuality: 0.9] as CFDictionary)
CGImageDestinationAddAuxiliaryDataInfo(dest, kCGImageAuxiliaryDataTypePortraitEffectsMatte, info as CFDictionary)
guard CGImageDestinationFinalize(dest) else { fatalError("not written") }
