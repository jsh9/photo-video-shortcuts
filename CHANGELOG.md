# Change Log

Each shortcut has its own version, shared by its `.shortcut` files and its
encoder. Every release includes the current files of all shortcuts.

## [Compress Photos 0.4.0] - 2026-10-04

- Added
  - Mac shortcuts. *Compress Photos (macOS)* converts photos from the Photos
    library (the Share menu in Photos, or a photo picker), saves the JPEG XL
    copies to Photos in the same albums, and offers to delete the originals,
    from the Share menu too. *Compress Photo Files (macOS)* converts image
    files and folders from Finder's Quick Actions, writing each `.jxl` next to
    its original. Both run `jxlbatch` through Shortcuts' Run Shell Script
    action, with no a-Shell, no helper shortcut and no handoff, and show the
    encoder's log in Quick Look when it notes anything. See
    `shortcuts/compress-photos/README-mac.md`.
  - `jxlbatch-macos`: a native, statically linked build of the encoder for
    Apple silicon Macs running macOS 14 or later, with the same libraries and
    settings as `jxlbatch.wasm`, so its files are byte for byte the same, and
    with threads. Installed as `~/.local/bin/jxlbatch`.
- Changed
  - Releases now have two shortcut ZIPs: `compress-photos-shortcuts-v<v>.zip`
    (iPhone, as before) and `compress-photos-mac-shortcuts-v<v>.zip` (Mac). New
    files for Mac users: the Mac ZIP and `jxlbatch-macos`. The iPhone shortcuts
    and `jxlbatch.wasm` only carry the new version number; iPhone users don't
    need to update.

## [Compress Photos 0.3.1] - 2026-10-04

- Fixed
  - Version 0.3.0 failed on every photo: from the share sheet the shortcut
    ended at once with nothing in a-Shell, and from the Shortcuts app it said
    "There was a problem running the shortcut". Its Filter Photos step, which
    sorted out Live Photos and videos, crashes Shortcuts when its input is a
    photo from the library: Shortcuts turns a "Photo Type" condition into a
    Photos-framework predicate on a key (`mediaSubtype`) that photo objects
    don't answer, then evaluates it in memory on the input. The shortcut now
    sorts each item by Get Details of Images (Media Type, then Photo Type),
    which Shortcuts reads in memory. Update the shortcuts; `jxlbatch.wasm` is
    unchanged.
- Changed
  - Images that aren't in the photo library (e.g. shared from Files) are
    converted again, as before 0.3.0, instead of being skipped: without a
    library lookup the shortcut can't tell them apart, and converting them is
    harmless (the result is saved to Photos; nothing is deleted from the share
    sheet). The notification no longer counts "item(s) not from Photos".
  - What the shortcut skipped ("Skipped 2 Live Photo(s), 1 video(s)") is also
    printed in a-Shell, before and after the batch: the notification is gone as
    soon as a-Shell comes to the front.

## [Compress Photos 0.3.0] - 2026-10-03

- Changed
  - Only still photos from the photo library are converted, screenshots
    included. Live Photos, videos and items not from Photos (e.g. images shared
    from Files) in the selection are skipped, and a notification counts each
    kind ("Skipped 2 Live Photo(s), 1 video(s)"). When nothing is left, the
    shortcut says "Nothing to convert" and stops before asking for a quality.
    Before, a Live Photo was converted as its still image and, from the
    Shortcuts app, offered for deletion, which deleted its video too; a video
    was copied into a-Shell, where `jxlbatch` read it whole before failing.
  - The photo picker (when started from the Shortcuts app) no longer shows
    videos.
  - Update the shortcuts; `jxlbatch.wasm` is unchanged.
- Full diff
  - https://github.com/jsh9/photo-video-shortcuts/pull/8

## [Compress Photos 0.2.1] - 2026-10-03

- Fixed
  - HDR photos with Apple's older gain map (iOS 14 to 17) came out 8-15%
    brighter in the midtones than Apple shows the HEIC. The gain map is now
    decoded with a gamma of 2.2, which is how Apple renders it
    ([Apple's documentation](https://developer.apple.com/documentation/appkit/applying-apple-hdr-effect-to-your-photos)
    says the Rec. 709 curve), and the JPEG XL now matches Apple's rendering
    within about 1%. Only the pixels of those photos change; ISO 21496-1 gain
    maps (iOS 18 and later) and the headroom shown in a-Shell are unaffected.
    Update `jxlbatch.wasm` (fixes #6).
  - A photo with Apple's older gain map and no XMP of its own (an iPhone 13
    photo from iOS 15, for example) got its gain map's XMP packet
    (`HDRGainMapVersion`) in the JPEG XL. Metadata linked only to other images
    in the HEIC is no longer taken as the photo's.
- Full diff
  - https://github.com/jsh9/photo-video-shortcuts/pull/7

## [Compress Photos 0.2.0] - 2026-10-02

- Added
  - HDR photos: an HDR HEIC from an iPhone becomes an HDR JPEG XL that lights
    up in Photos like the original. Both of Apple's gain maps are converted:
    ISO 21496-1 (iOS 18 and later) and Apple's older format (iOS 14 to 17).
    `jxlbatch` applies the gain map and stores the HDR result as 16-bit PQ in
    Display P3, with SDR white at 203 nits and the photo's peak brightness,
    because Photos ignores JPEG XL gain maps. a-Shell shows such a photo as,
    for example, "HDR 3.5×". The JPEG XL also keeps the HEIC's HDR color
    profile (iOS 18 and later), with the tone curve Apple uses to dim the photo
    on screens that can't show all of it (including SDR screens), so it looks
    like the original there too; a-Shell says so when a photo has none.
  - HDR photos edited in Photos (checked with crops) are converted as HDR too.
    Photos saves them upright at their new size, without the label iPhone
    cameras put on Apple's gain maps, and without an HDR color profile, so
    a-Shell says "Apple's HDR profile not found" for them: on screens that
    can't show all of their HDR, they may look darker or brighter than the
    original.
  - Gain maps an iPhone camera labels as Apple's are used, and ISO 21496-1 gain
    maps without the label if the photo is stored upright and uncropped. Other
    HDR HEICs (e.g. saved turned or cropped by other apps or on a Mac) are
    converted as SDR, with "HDR gain map not used (not an iPhone camera photo)"
    in a-Shell (and a count at the end of the batch), and their originals are
    still offered for deletion.
  - A gain map claiming more than 16 stops (65,536×), in either format (for
    Apple's older one, the headroom its maker notes give), is treated as
    malformed: the photo is converted as SDR and its original is kept.
  - Originals whose HDR isn't in the JPEG XL are not offered for deletion: a
    photo whose gain map can't be used (converted as SDR, with a note "HDR gain
    map not used" in a-Shell; except the photos above), an HDR photo sent as
    JPEG (with a note), and `--sdr`. `jxl_done.txt` lines are now
    `file|index|delete or keep|name`. **Update both the shortcuts and
    `jxlbatch.wasm`**: an older shortcut offers every converted original for
    deletion, and the new shortcut with an older `jxlbatch.wasm` offers none.
  - `jxlbatch --sdr` converts HDR photos as SDR (the shortcuts don't use it).
  - `jxlbatch --selftest` also checks HDR decoding and that Apple's HDR profile
    is kept.
- Changed
  - HDR photos are computed a region at a time as the encoder reads them, so a
    48 MP HDR photo takes about as much memory as an SDR one.
  - HEIF photos are cropped and turned after conversion to RGB, as Apple shows
    them, so photos cropped at an odd offset come out slightly differently
    along their edges (libheif cropped first, which shifted the colors of 4:2:0
    photos there).
- Fixed
  - A false "orientation check" warning in a-Shell for photos edited in Photos,
    whose EXIF keeps the size from before the edit: the check now runs only
    when the EXIF size is the photo's size as stored.
- Full diff
  - https://github.com/jsh9/photo-video-shortcuts/pull/5

## [Compress Photos 0.1.1] - 2026-10-01

- Fixed
  - "File jxl_done.txt not found" when _Compress Photos_ had to launch a-Shell:
    a-Shell could run the shortcut's commands outside its Shortcuts folder, and
    the retry for its WebAssembly engine still starting never ran (dash can't
    run `jxlbatch.wasm`). The shortcut now changes to the Shortcuts folder and
    retries with `jxlbatch --retry`. Update both the shortcuts and
    `jxlbatch.wasm`.
- Changed
  - When `jxlbatch` can't find the job file, it lists where it looked,
    including the values of `$PWD` and `$SHORTCUTS`
- Full diff
  - https://github.com/jsh9/photo-video-shortcuts/pull/4

## [Compress Photos 0.1.0] - 2026-09-30

- Added
  - _Compress Photos_: converts HEIF, JPEG and PNG photos to JPEG XL with
    a-Shell and saves them back to Photos, from the share sheet or from its own
    photo picker
  - _JXL-Import_: saves the converted photos when started from the share sheet
  - Ten quality presets with descriptions (default: 83)
  - Keeps EXIF and XMP metadata (including extended JPEG XMP), the color
    profile, 10-bit precision and the file name; pixels are stored upright
  - Adds each JPEG XL copy to the albums its original is in
  - Offers to delete the originals whose copy was saved (photo picker only)
  - `jxlbatch`, the WebAssembly encoder (libjxl 0.11.2, libheif 1.23.5), with a
    `--selftest`
- Maintenance
  - Repository layout, documentation, tests, pre-commit hooks and GitHub
    Actions
  - Automated release packaging and validation, with versioned shortcut ZIPs
    and release notes for each new or updated tool
- Full diff
  - https://github.com/jsh9/photo-video-shortcuts/pull/1
