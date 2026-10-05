// Writes a test video with Apple's AVAssetWriter, the way an iPhone records
// one: a QuickTime movie with HEVC video (8-bit SDR, or 10-bit HLG), AAC sound,
// a rotation flag, and Apple's metadata keys on the movie and on the video
// track, each with the data type an iPhone 17 Pro writes (see
// docs/compress-videos-mac-design.md, 4.5).
//
// usage: make_video OUT.mov [--size WxH] [--seconds S] [--fps F] [--hlg]
//                   [--rotate 0|90|180|270] [--audio stereo|none|surround,stereo]
//                   [--no-keys]
//
// The picture is a gradient with a square moving across it, so that a copy
// can be compared with the original (PSNR). --audio lists the sound tracks in
// order: "surround" is 5.1, "stereo" two channels, each a sine wave.
import AVFoundation
import CoreMedia
import CoreVideo
import Foundation
import VideoToolbox

func fail(_ message: String) -> Never {
  FileHandle.standardError.write((message + "\n").data(using: .utf8)!)
  exit(1)
}

var args = Array(CommandLine.arguments.dropFirst())
guard !args.isEmpty else { fail("usage: make_video OUT.mov [options]") }
let output = URL(fileURLWithPath: args.removeFirst())
var width = 320
var height = 180
var seconds = 2.0
var fps = 30.0
var hlg = false
var rotate = 0
var audio = ["stereo"]
var keys = true
while !args.isEmpty {
  let a = args.removeFirst()
  switch a {
  case "--size":
    let parts = args.removeFirst().split(separator: "x").compactMap { Int($0) }
    guard parts.count == 2 else { fail("--size WxH") }
    (width, height) = (parts[0], parts[1])
  case "--seconds": seconds = Double(args.removeFirst())!
  case "--fps": fps = Double(args.removeFirst())!
  case "--hlg": hlg = true
  case "--rotate": rotate = Int(args.removeFirst())!
  case "--audio":
    let list = args.removeFirst()
    audio = list == "none" ? [] : list.split(separator: ",").map(String.init)
  case "--no-keys": keys = false
  default: fail("unknown option \(a)")
  }
}

// The keys, as AVFoundation reads them in an iPhone 17 Pro's video.
func item(_ key: String, _ value: Any, _ type: CFString, language: String? = nil) -> AVMetadataItem {
  let m = AVMutableMetadataItem()
  m.keySpace = .quickTimeMetadata
  m.key = key as NSString
  m.value = value as? NSCopying & NSObjectProtocol
  m.dataType = type as String
  if let language { m.extendedLanguageTag = language }
  return m
}
let utf8 = kCMMetadataBaseDataType_UTF8
let movieKeys = [
  item("com.apple.quicktime.creationdate", "2025-06-01T12:34:56+0200", utf8),
  item("com.apple.quicktime.location.ISO6709", "+48.8584+002.2945+035.000/", utf8),
  item("com.apple.quicktime.location.accuracy.horizontal", "14.245955", utf8),
  item("com.apple.quicktime.make", "Apple", utf8),
  item("com.apple.quicktime.model", "iPhone 17 Pro", utf8),
  item("com.apple.quicktime.software", "26.0", utf8),
  item("com.apple.quicktime.full-frame-rate-playback-intent", NSNumber(value: Int64(1)),
       kCMMetadataBaseDataType_SInt64),
  item("com.apple.quicktime.metadata.1", NSNumber(value: Int8(1)), kCMMetadataBaseDataType_SInt8),
]
let trackKeys = [
  item("com.apple.quicktime.camera.lens_model", "iPhone 17 Pro back camera 6.765mm f/1.78", utf8,
       language: "en-US"),
  item("com.apple.quicktime.camera.focal_length.35mm_equivalent", "25", utf8, language: "en-US"),
  item("com.apple.quicktime.camera.lens_irisfnumber", "F1.78", utf8, language: "en-US"),
  item("com.apple.quicktime.apple-maker-note.74", NSNumber(value: Int32(2)),
       kCMMetadataBaseDataType_SInt32),
  item("com.apple.quicktime.apple-maker-note.97", NSNumber(value: Int32(24)),
       kCMMetadataBaseDataType_SInt32),
]

try? FileManager.default.removeItem(at: output)
let writer = try! AVAssetWriter(outputURL: output, fileType: .mov)
if keys { writer.metadata = movieKeys }

var compression: [String: Any] = [
  AVVideoAverageBitRateKey: max(width * height * 8, 500_000),
  AVVideoExpectedSourceFrameRateKey: fps,
]
if hlg { compression[AVVideoProfileLevelKey] = kVTProfileLevel_HEVC_Main10_AutoLevel as String }
let color: [String: Any] = hlg
  ? [AVVideoColorPrimariesKey: AVVideoColorPrimaries_ITU_R_2020,
     AVVideoTransferFunctionKey: AVVideoTransferFunction_ITU_R_2100_HLG,
     AVVideoYCbCrMatrixKey: AVVideoYCbCrMatrix_ITU_R_2020]
  : [AVVideoColorPrimariesKey: AVVideoColorPrimaries_ITU_R_709_2,
     AVVideoTransferFunctionKey: AVVideoTransferFunction_ITU_R_709_2,
     AVVideoYCbCrMatrixKey: AVVideoYCbCrMatrix_ITU_R_709_2]
let video = AVAssetWriterInput(mediaType: .video, outputSettings: [
  AVVideoCodecKey: AVVideoCodecType.hevc,
  AVVideoWidthKey: width,
  AVVideoHeightKey: height,
  AVVideoCompressionPropertiesKey: compression,
  AVVideoColorPropertiesKey: color,
])
video.expectsMediaDataInRealTime = false
video.transform = CGAffineTransform(rotationAngle: CGFloat(rotate) * .pi / 180)
if keys { video.metadata = trackKeys }
let format = hlg ? kCVPixelFormatType_420YpCbCr10BiPlanarVideoRange
  : kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange
let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: video,
  sourcePixelBufferAttributes: [kCVPixelBufferPixelFormatTypeKey as String: format,
    kCVPixelBufferWidthKey as String: width, kCVPixelBufferHeightKey as String: height])
writer.add(video)

let rate = 48000.0
var sounds: [(AVAssetWriterInput, Int)] = []
for kind in audio {
  let channels = kind == "surround" ? 6 : 2
  var settings: [String: Any] = [
    AVFormatIDKey: kAudioFormatMPEG4AAC, AVSampleRateKey: rate,
    AVNumberOfChannelsKey: channels, AVEncoderBitRateKey: 64000 * channels,
  ]
  if channels == 6 {
    var layout = AudioChannelLayout()
    layout.mChannelLayoutTag = kAudioChannelLayoutTag_MPEG_5_1_D
    settings[AVChannelLayoutKey] = Data(bytes: &layout, count: MemoryLayout<AudioChannelLayout>.size)
  }
  let input = AVAssetWriterInput(mediaType: .audio, outputSettings: settings)
  input.expectsMediaDataInRealTime = false
  writer.add(input)
  sounds.append((input, channels))
}

guard writer.startWriting() else { fail("cannot write \(output.path): \(String(describing: writer.error))") }
writer.startSession(atSourceTime: .zero)

// The picture: a gradient and a square moving across it.
let frames = Int((seconds * fps).rounded())
let timescale: CMTimeScale = fps == fps.rounded() ? CMTimeScale(fps) : 30000
func frame(_ i: Int) -> CVPixelBuffer {
  var buffer: CVPixelBuffer?
  CVPixelBufferPoolCreatePixelBuffer(nil, adaptor.pixelBufferPool!, &buffer)
  guard let pixels = buffer else { fail("no pixel buffer") }
  CVPixelBufferLockBaseAddress(pixels, [])
  let side = height / 3
  let square = (i * 4) % max(width - side, 1)
  for plane in 0..<2 {
    let base = CVPixelBufferGetBaseAddressOfPlane(pixels, plane)!
    let stride = CVPixelBufferGetBytesPerRowOfPlane(pixels, plane)
    let w = CVPixelBufferGetWidthOfPlane(pixels, plane)
    let h = CVPixelBufferGetHeightOfPlane(pixels, plane)
    // the chroma plane holds two samples (Cb, Cr) per position
    let samples = plane == 0 ? w : 2 * w
    for y in 0..<h {
      for x in 0..<samples {
        var v: Int
        if plane == 0 {
          let inSquare = x >= square && x < square + side && y >= side && y < 2 * side
          v = inSquare ? 220 : 32 + (x * 160) / max(w, 1) + (y * 40) / max(h, 1)
        } else {
          v = 128 + ((x / 2 + y) % 32) - 16
        }
        if hlg {
          base.advanced(by: y * stride + x * 2).assumingMemoryBound(to: UInt16.self).pointee =
            UInt16(v << 2) << 6
        } else {
          base.advanced(by: y * stride + x).assumingMemoryBound(to: UInt8.self).pointee = UInt8(v)
        }
      }
    }
  }
  CVPixelBufferUnlockBaseAddress(pixels, [])
  return pixels
}

// The sound: a sine wave per track (440 Hz, 880 Hz...), 1024 frames a buffer.
func sound(track: Int, channels: Int, start: Int, count: Int) -> CMSampleBuffer {
  var asbd = AudioStreamBasicDescription(mSampleRate: rate, mFormatID: kAudioFormatLinearPCM,
    mFormatFlags: kAudioFormatFlagIsFloat | kAudioFormatFlagIsPacked,
    mBytesPerPacket: UInt32(4 * channels), mFramesPerPacket: 1, mBytesPerFrame: UInt32(4 * channels),
    mChannelsPerFrame: UInt32(channels), mBitsPerChannel: 32, mReserved: 0)
  var description: CMAudioFormatDescription?
  CMAudioFormatDescriptionCreate(allocator: nil, asbd: &asbd, layoutSize: 0, layout: nil,
    magicCookieSize: 0, magicCookie: nil, extensions: nil, formatDescriptionOut: &description)
  var samples = [Float](repeating: 0, count: count * channels)
  for f in 0..<count {
    let s = Float(sin(2 * Double.pi * Double(440 * (track + 1)) * Double(start + f) / rate)) * 0.3
    for c in 0..<channels { samples[f * channels + c] = s }
  }
  var block: CMBlockBuffer?
  let bytes = samples.count * 4
  CMBlockBufferCreateWithMemoryBlock(allocator: nil, memoryBlock: nil, blockLength: bytes,
    blockAllocator: nil, customBlockSource: nil, offsetToData: 0, dataLength: bytes, flags: 0,
    blockBufferOut: &block)
  samples.withUnsafeBytes { raw in
    _ = CMBlockBufferReplaceDataBytes(with: raw.baseAddress!, blockBuffer: block!,
      offsetIntoDestination: 0, dataLength: bytes)
  }
  var sample: CMSampleBuffer?
  CMAudioSampleBufferCreateReadyWithPacketDescriptions(allocator: nil, dataBuffer: block!,
    formatDescription: description!, sampleCount: count,
    presentationTimeStamp: CMTime(value: CMTimeValue(start), timescale: CMTimeScale(rate)),
    packetDescriptions: nil, sampleBufferOut: &sample)
  return sample!
}

// Each track is fed when the writer asks for it, so that it can interleave
// them.
let group = DispatchGroup()
var next = 0
group.enter()
video.requestMediaDataWhenReady(on: DispatchQueue(label: "video")) {
  while video.isReadyForMoreMediaData {
    if next >= frames {
      video.markAsFinished()
      group.leave()
      return
    }
    let time = timescale == 30000
      ? CMTime(value: CMTimeValue((Double(next) * 30000 / fps).rounded()), timescale: 30000)
      : CMTime(value: CMTimeValue(next), timescale: timescale)
    guard adaptor.append(frame(next), withPresentationTime: time) else {
      fail("cannot append frame \(next): \(String(describing: writer.error))")
    }
    next += 1
  }
}
let total = Int(seconds * rate)
for (track, (input, channels)) in sounds.enumerated() {
  var start = 0
  group.enter()
  input.requestMediaDataWhenReady(on: DispatchQueue(label: "audio\(track)")) {
    while input.isReadyForMoreMediaData {
      if start >= total {
        input.markAsFinished()
        group.leave()
        return
      }
      let count = min(1024, total - start)
      guard input.append(sound(track: track, channels: channels, start: start, count: count)) else {
        fail("cannot append sound: \(String(describing: writer.error))")
      }
      start += count
    }
  }
}
group.wait()

let done = DispatchSemaphore(value: 0)
writer.finishWriting { done.signal() }
done.wait()
guard writer.status == .completed else { fail("not written: \(String(describing: writer.error))") }
