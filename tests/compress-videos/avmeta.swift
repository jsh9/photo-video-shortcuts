// Prints what Apple's AVFoundation reads from a video, as JSON: creation date,
// location, camera metadata (every item with its identifier and data type),
// and each track's codec, size, rotation, frame rate, whether it is HDR, and
// the boxes of its sample description (dvvC: Dolby Vision, as Apple's players
// see it). Photos uses the same framework, so this is the check that a
// converted video keeps what Photos shows.
//
// Usage: avmeta VIDEO

import AVFoundation
import Foundation

func fourCC(_ code: FourCharCode) -> String {
    let bytes = [24, 16, 8, 0].map { UInt8((code >> $0) & 0xFF) }
    return String(bytes: bytes, encoding: .macOSRoman) ?? "\(code)"
}

func describe(_ value: Any?) -> Any {
    switch value {
    case let s as String: return s
    case let n as NSNumber: return n
    case let d as Date: return ISO8601DateFormatter().string(from: d)
    case let d as Data: return "<\(d.count) bytes>"
    case nil: return NSNull()
    default: return String(describing: value!)
    }
}

func describeItems(_ metadata: [AVMetadataItem]) async throws -> [String: Any] {
    var items: [String: Any] = [:]
    for item in metadata {
        var key = item.identifier?.rawValue ?? "?"
        if let locale = item.extendedLanguageTag { key += " (\(locale))" }
        let dataType = item.dataType ?? "?"
        items[key] = ["value": describe(try await item.load(.value)), "type": dataType]
    }
    return items
}

func run(_ path: String) async throws -> [String: Any] {
    let asset = AVURLAsset(url: URL(fileURLWithPath: path))
    var out: [String: Any] = [:]
    let (playable, duration, metadata, creation) = try await asset.load(
        .isPlayable, .duration, .metadata, .creationDate)
    out["playable"] = playable
    out["duration"] = duration.seconds
    if let creation {
        out["creationDate"] = describe(try await creation.load(.value))
        out["creationDateString"] = describe(try await creation.load(.stringValue))
    }
    out["metadata"] = try await describeItems(metadata)

    var tracks: [[String: Any]] = []
    for track in try await asset.load(.tracks) {
        let (formats, size, transform, fps, playableTrack, trackMetadata) = try await track.load(
            .formatDescriptions, .naturalSize, .preferredTransform, .nominalFrameRate, .isPlayable,
            .metadata)
        var t: [String: Any] = ["mediaType": track.mediaType.rawValue, "playable": playableTrack]
        if !trackMetadata.isEmpty {
            t["metadata"] = try await describeItems(trackMetadata)
        }
        if let format = formats.first {
            t["codec"] = fourCC(CMFormatDescriptionGetMediaSubType(format))
            if let ext = CMFormatDescriptionGetExtensions(format) as? [String: Any] {
                for key in ["CVImageBufferColorPrimaries", "CVImageBufferTransferFunction",
                            "CVImageBufferYCbCrMatrix", "BitsPerComponent"] {
                    if let v = ext[key] { t[key] = describe(v) }
                }
                if let atoms = ext["SampleDescriptionExtensionAtoms"] as? [String: Any] {
                    t["atoms"] = atoms.keys.sorted()
                }
            }
            if track.mediaType == .audio,
               let asbd = CMAudioFormatDescriptionGetStreamBasicDescription(format) {
                t["channels"] = Int(asbd.pointee.mChannelsPerFrame)
                t["sampleRate"] = asbd.pointee.mSampleRate
            }
        }
        if track.mediaType == .video {
            let characteristics = try await track.load(.mediaCharacteristics)
            t["hdr"] = characteristics.contains(.containsHDRVideo)
            t["naturalSize"] = [size.width, size.height]
            let angle = atan2(transform.b, transform.a) * 180 / .pi
            t["rotation"] = (angle * 1000).rounded() / 1000
            t["frameRate"] = fps
        }
        tracks.append(t)
    }
    out["tracks"] = tracks
    return out
}

guard CommandLine.arguments.count == 2 else {
    FileHandle.standardError.write("usage: avmeta VIDEO\n".data(using: .utf8)!)
    exit(2)
}
let semaphore = DispatchSemaphore(value: 0)
var status: Int32 = 0
Task {
    do {
        let result = try await run(CommandLine.arguments[1])
        let json = try JSONSerialization.data(
            withJSONObject: result, options: [.prettyPrinted, .sortedKeys])
        print(String(data: json, encoding: .utf8)!)
    } catch {
        FileHandle.standardError.write("avmeta: \(error)\n".data(using: .utf8)!)
        status = 1
    }
    semaphore.signal()
}
semaphore.wait()
exit(status)
