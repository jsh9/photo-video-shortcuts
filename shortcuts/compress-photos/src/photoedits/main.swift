// Compress Photos Helper (prototype): reads an edited photo's edit from the
// photo library and creates its compressed copy with the edit, through
// PhotoKit, so that the edit can still be reverted in Photos. The selection
// route of Compress Photos (macOS) Prototype starts it (scripts/mac/
// selection.zsh); see docs/compress-photos-revertible-edits-plan.md.
// The prototype tries every edited photo: what may not come out right is a
// note in the answer, never a refusal.
//
//   photoedits --version            "photoedits <version> protocol <n>"
//   photoedits ask [DIR]            asks for access to Photos (also with no
//                                   arguments); the answer in DIR/ask.out
//   photoedits check DIR            DIR/check.txt -> DIR/check.out
//   photoedits create DIR           DIR/create.txt -> DIR/create.out
//   photoedits plist FILE           the plist rules alone (no library)
//   photoedits geometry BASE ORIG   the geometry rule alone (no library)
import Foundation
import ImageIO
import Photos

let version = "0.13.0-prototype"
let protocolNumber = 1
let header = "photoedits \(version) protocol \(protocolNumber)"

// MARK: answers

final class Answer {
    private var lines = [header]
    private let lock = NSLock()
    private let url: URL?
    init(_ url: URL?) { self.url = url }
    func say(_ s: String) {
        lock.lock(); lines.append(s); lock.unlock()
    }
    // Writes the answer and ends the program. `last` is "end", or
    // "end|timeout" from the watchdog.
    func finish(_ last: String, _ code: Int32) -> Never {
        lock.lock()
        let text = (lines + [last]).joined(separator: "\n") + "\n"
        if let url {
            // Not atomically: that goes through a temporary folder of its own.
            // The reader checks the last line, "end".
            do {
                try text.write(to: url, atomically: false, encoding: .utf8)
            } catch {
                FileHandle.standardError.write(Data("photoedits: \(describe(error))\n".utf8))
                exit(3)
            }
        } else {
            print(text, terminator: "")
        }
        exit(code)
    }
}

// Waits for a callback, at most `seconds`.
func wait<T>(_ seconds: Double, _ body: (@escaping (T) -> Void) -> Void) -> T? {
    let done = DispatchSemaphore(value: 0)
    let lock = NSLock()
    var result: T?
    body { v in lock.lock(); result = v; lock.unlock(); done.signal() }
    _ = done.wait(timeout: .now() + seconds)
    lock.lock(); defer { lock.unlock() }
    return result
}

func describe(_ e: Error) -> String {
    let e = e as NSError
    return "\(e.domain) \(e.code): \(e.localizedDescription)"
        .replacingOccurrences(of: "\n", with: " ").replacingOccurrences(of: "|", with: "/")
}

// MARK: rules that need no library

// The parts of an edit that are worked out from the base picture and their own
// settings alone (identifiers from Photos' own list, PhotoImaging's
// PICompositionSerializerConstants, macOS 27). Any other part needs data the
// copy doesn't carry (depth, a Photographic Style's data, Clean Up's masks,
// RAW, video), or isn't known here.
let carried: Set<String> = [
    "SmartTone", "SmartColor", "SmartBlackAndWhite", "WhiteBalance", "SemanticEnhance",
    "RKCurvesOperation", "RKLevelsOperation", "RKSelectiveColorOperation",
    "DGDefinition2Operation", "RKNoiseReductionOperation", "RKProSharpenOperation",
    "DGVignetteEffectOperation", "Grain", "Effect", "Crop", "Orientation",
    "RedEyeBB", "RKRedEyeOperation",
]
let named: [String: String] = [
    "DepthEffect": "a Portrait photo", "PortraitEffect": "a Portrait photo",
    "SemanticStyle": "a Photographic Style", "TextureStyle": "a Photographic Style",
    "Inpaint": "Clean Up", "InpaintMasks": "Clean Up", "GenerativeEdits": "Clean Up",
    "GeneratedTiles": "Clean Up", "RKRetouchOperation": "Retouch",
]

// nil if the plist is an edit this tool can copy, else the reason
func plistProblem(_ url: URL) -> String? {
    guard let data = try? Data(contentsOf: url),
          let d = (try? PropertyListSerialization.propertyList(from: data, options: [], format: nil))
          as? [String: Any] else { return "its edit could not be read" }
    let format = d["adjustmentFormatIdentifier"] as? String ?? "?"
    if format != "com.apple.photo" { return "edited by another app (\(format))" }
    guard let blob = d["adjustmentData"] as? Data, !blob.isEmpty else {
        return "Photos keeps its edit outside Adjustments.plist"
    }
    guard let base = d["adjustmentBaseVersion"] as? NSNumber, base.intValue == 0 else {
        return "its edit is not based on the original photo"
    }
    // The edit itself: JSON, compressed (raw DEFLATE), with a list of parts.
    guard let json = try? (blob as NSData).decompressed(using: .zlib) as Data,
          let edit = (try? JSONSerialization.jsonObject(with: json)) as? [String: Any],
          let parts = edit["adjustments"] as? [[String: Any]] else {
        return "its edit is in a form this version doesn't read"
    }
    for part in parts where (part["enabled"] as? Bool) != false {
        let id = part["identifier"] as? String ?? "?"
        if !carried.contains(id) {
            return named[id] ?? "its edit has a part the copy can't carry (\(id))"
        }
    }
    return nil
}

struct Stored: Equatable { var width = 0, height = 0, orientation = 1; var type = "" }

func stored(_ url: URL) -> Stored? {
    guard let src = CGImageSourceCreateWithURL(url as CFURL, nil),
          let p = CGImageSourceCopyPropertiesAtIndex(src, 0, nil) as? [CFString: Any],
          let w = p[kCGImagePropertyPixelWidth] as? Int,
          let h = p[kCGImagePropertyPixelHeight] as? Int else { return nil }
    return Stored(width: w, height: h, orientation: p[kCGImagePropertyOrientation] as? Int ?? 1,
                  type: (CGImageSourceGetType(src) as String?) ?? "")
}

// nil if the base has the original's pixels as stored (size and orientation)
func geometryProblem(base: URL, original: URL) -> String? {
    guard let b = stored(base), let o = stored(original) else { return "its files could not be read" }
    if b.width != o.width || b.height != o.height || b.orientation != o.orientation {
        return "the copy is stored \(b.width)x\(b.height), orientation \(b.orientation); "
            + "the original \(o.width)x\(o.height), orientation \(o.orientation)"
    }
    return nil
}

// MARK: Photos

let fullAccess = PHAuthorizationStatus.authorized

func access(asking: Bool) -> PHAuthorizationStatus {
    let now = PHPhotoLibrary.authorizationStatus(for: .readWrite)
    if now != .notDetermined || !asking { return now }
    let answer: PHAuthorizationStatus? = wait(120) { done in
        PHPhotoLibrary.requestAuthorization(for: .readWrite) { done($0) }
    }
    return answer ?? .notDetermined
}

func asset(_ id: String) -> PHAsset? {
    PHAsset.fetchAssets(withLocalIdentifiers: [id], options: nil).firstObject
}

// "n|ok|notes" (notes: what may not come out right, "; " between them, or
// empty), or "n|no|reason"; writes DIR/n/Adjustments.plist
func check(_ n: String, _ id: String, _ dir: URL) -> String {
    func no(_ why: String) -> String { "\(n)|no|\(why)" }
    var notes: [String] = []
    guard let a = asset(id) else { return no("not in the System Photo Library") }
    guard a.mediaType == .image else { return no("not a photo") }
    guard a.hasAdjustments else { return no("Photos has no edit for it") }
    let format = a.adjustmentFormatIdentifier ?? "?"
    if format != "com.apple.photo" { notes.append("edited by another app (\(format))") }
    if a.mediaSubtypes.contains(.photoLive) { notes.append("a Live Photo") }
    if a.mediaSubtypes.contains(.photoDepthEffect) { notes.append("a Portrait photo: the copy has no depth data") }
    let resources = PHAssetResource.assetResources(for: a)
    let types = resources.map { $0.type.rawValue }.sorted()
    if types != [1, 5, 7] {
        notes.append("other data in the library (resource types "
            + types.map(String.init).joined(separator: ", ") + ")")
    }
    guard resources.contains(where: { $0.type == .adjustmentData }) else {
        return no("Photos keeps no edit record for it")
    }
    let folder = dir.appendingPathComponent(n)
    let plist = folder.appendingPathComponent("Adjustments.plist")
    try? FileManager.default.removeItem(at: plist)
    let options = PHAssetResourceRequestOptions()
    options.isNetworkAccessAllowed = true  // iCloud may have to deliver it
    let edit = resources.first { $0.type == .adjustmentData }!
    let written: Error?? = wait(30) { done in
        PHAssetResourceManager.default().writeData(for: edit, toFile: plist, options: options) { done($0) }
    }
    guard let outcome = written else { return no("its edit did not arrive in 30 s") }
    if let error = outcome { return no("its edit could not be read (\(describe(error)))") }
    if let why = plistProblem(plist) { notes.append(why) }
    return "\(n)|ok|" + notes.joined(separator: "; ")
}

// "n|created|id|notes", "n|unsure|id|reason" or "n|failed|reason". The
// files: DIR/n/base.heic or base.jxl (the copy of the original),
// DIR/n/look.heic (the copy of Photos' rendering), DIR/n/Adjustments.plist,
// DIR/n/original (the exported original, for the notes).
func create(_ n: String, _ name: String, _ dir: URL) -> String {
    func failed(_ why: String) -> String { "\(n)|failed|\(why)" }
    let folder = dir.appendingPathComponent(n)
    let fm = FileManager.default
    guard let base = ["base.heic", "base.jxl"].map({ folder.appendingPathComponent($0) })
        .first(where: { fm.fileExists(atPath: $0.path) }) else { return failed("its compressed original is missing") }
    let look = folder.appendingPathComponent("look.heic")
    let plist = folder.appendingPathComponent("Adjustments.plist")
    // Never an asset without its look: all three files, or nothing.
    guard let l = stored(look), l.type == "public.heic", l.width > 0 else {
        return failed("its edited look is missing or not a HEIC")
    }
    guard fm.fileExists(atPath: plist.path) else { return failed("its edit record is missing") }
    let lookSize = (try? fm.attributesOfItem(atPath: look.path)[.size] as? Int) ?? 0
    var notes: [String] = []
    if let why = geometryProblem(base: base, original: folder.appendingPathComponent("original")) {
        notes.append(why)
    }
    let types = [PHAssetResourceType.photo, .adjustmentData, .fullSizePhoto]
    guard PHAssetCreationRequest.supportsAssetResourceTypes(types.map { NSNumber(value: $0.rawValue) }) else {
        return failed("this macOS doesn't take a photo with its edit")
    }
    var id: String?
    do {
        try PHPhotoLibrary.shared().performChangesAndWait {
            let request = PHAssetCreationRequest.forAsset()
            let options = PHAssetResourceCreationOptions()
            options.originalFilename = name
            request.addResource(with: .photo, fileURL: base, options: options)
            request.addResource(with: .adjustmentData, fileURL: plist, options: nil)
            request.addResource(with: .fullSizePhoto, fileURL: look, options: nil)
            id = request.placeholderForCreatedAsset?.localIdentifier
        }
    } catch {
        return failed(describe(error))
    }
    guard let id else { return failed("Photos gave no id for the copy") }
    // What Photos made of it: edited, with the look given (at most 10 s).
    var why = "Photos doesn't list the copy"
    let until = Date().addingTimeInterval(10)
    repeat {
        if let a = asset(id) {
            let has = Set(PHAssetResource.assetResources(for: a).map { $0.type })
            if !a.hasAdjustments || !has.isSuperset(of: types) {
                why = "Photos doesn't show its edit yet"
            } else {
                let o = PHImageRequestOptions()
                o.version = .current
                o.isSynchronous = true
                o.isNetworkAccessAllowed = false
                var bytes = -1
                PHImageManager.default().requestImageDataAndOrientation(for: a, options: o) { data, _, _, _ in
                    bytes = data?.count ?? -1
                }
                if bytes == lookSize { return "\(n)|created|\(id)|" + notes.joined(separator: "; ") }
                why = bytes < 0 ? "Photos has no picture for its edited look"
                    : "Photos replaced its edited look with its own"
            }
        }
        Thread.sleep(forTimeInterval: 0.5)
    } while Date() < until
    return "\(n)|unsure|\(id)|\(why)"
}

// MARK: commands

func jobs(_ url: URL, fields: Int) -> [[String]] {
    let text = (try? String(contentsOf: url, encoding: .utf8)) ?? ""
    return text.split(separator: "\n").map {
        $0.split(separator: "|", maxSplits: fields - 1, omittingEmptySubsequences: false).map(String.init)
    }.filter { $0.count == fields && Int($0[0]) != nil }
}

func run() -> Never {
    let args = Array(CommandLine.arguments.dropFirst())
    let command = args.first ?? "ask"
    switch command {
    case "--version":
        print(header)
        exit(0)
    case "plist" where args.count == 2:
        print(plistProblem(URL(fileURLWithPath: args[1])).map { "no|\($0)" } ?? "ok")
        exit(0)
    case "geometry" where args.count == 3:
        print(geometryProblem(base: URL(fileURLWithPath: args[1]), original: URL(fileURLWithPath: args[2]))
            .map { "no|\($0)" } ?? "ok")
        exit(0)
    case "ask" where args.count <= 2, "check" where args.count == 2, "create" where args.count == 2:
        break
    default:
        FileHandle.standardError.write(Data("usage: photoedits --version | ask [DIR] | check DIR | create DIR\n".utf8))
        exit(64)
    }
    let dir = args.count == 2 ? URL(fileURLWithPath: args[1]) : nil
    let answer = Answer(dir?.appendingPathComponent("\(command).out"))
    let work = command == "ask" ? [] : jobs(dir!.appendingPathComponent("\(command).txt"), fields: 2)
    // The watchdog: whatever Photos does, the program ends, with what it has.
    let limit = 150.0 + 45.0 * Double(work.count)
    DispatchQueue.global().asyncAfter(deadline: .now() + limit) { answer.finish("end|timeout", 2) }
    // Only "ask" and "check" may make macOS ask; "create" never does.
    let status = access(asking: command != "create")
    answer.say("access|\(status.rawValue)")
    if status == fullAccess {
        for job in work {
            answer.say(command == "check" ? check(job[0], job[1], dir!) : create(job[0], job[1], dir!))
        }
    }
    answer.finish("end", 0)
}

// Off the main thread: Photos calls some completion handlers on the main
// queue, which a wait on the main thread would block for good.
DispatchQueue.global().async { run() }
dispatchMain()
