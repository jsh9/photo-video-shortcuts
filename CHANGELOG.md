# Change Log

Each shortcut has its own version, shared by its `.shortcut` files and its
encoder. Every release includes the current files of all shortcuts.

## [Compress Photos 0.7.0] - 2026-10-11

- Added
  - A second output format, **HEIC**, on both platforms: the shortcuts first
    ask the format (HEIC or JPEG XL), then that format's quality. A HEIC copy
    is the camera's own file with its HEVC tiles re-encoded by x265 (preset
    slow, at the chosen RF: 22 "placebo" to 40, default 26); the gain map,
    `tmap` item, thumbnail, Exif and XMP stay byte for byte, so Photos shows
    the copy exactly as the original, without the pink patches an HDR JPEG XL
    shows in bright skies. Apple's Photographic Styles data (about 0.3 MB) is
    dropped. *Drop HDR* leaves the gain map out; a JPEG, a PNG, or a HEIF whose
    picture isn't 8-bit 4:2:0 HEVC tiles is written anew as an SDR HEIC.
    `jxlbatch --heic [--rf RF]`; x265 is linked into every build (the
    WebAssembly build runs it on the calling thread, about 20 s per 24 MP photo
    under wasmtime on an M4 Pro), which makes the encoders GPL as the
    repository is. The self-test checks a HEIC round trip.
  - Each JPEG XL copy gets the date Photos shows for its original, in Photos
    and in its EXIF capture date (`DateTimeOriginal`, `CreateDate` and their
    time zone), on both platforms. A date changed in Photos (Adjust Date and
    Time), which Photos keeps in its library and not in the original file, is
    no longer lost with the original; a photo without a capture date of its own
    (an image saved from an app that removed it, a screenshot) is no longer
    dated at the time of the conversion. A photo whose capture date already is
    that moment keeps its EXIF byte for byte; one without a time zone in its
    EXIF whose time is that moment in some zone keeps its time and gets the
    zone. The shortcuts pass the dates to `jxlbatch` in `jxl_dates.txt`
    (`i|2024-01-01T17:00:00-05:00`); the log says when a date or zone was
    written. The Mac's selection route also checks each imported copy's date in
    Photos.
  - Update both the shortcuts and the encoders (`jxlbatch.wasm`,
    `jxlbatch-macos`): an older `jxlbatch` ignores the dates, and an older
    shortcut gives none.
  - A new quality preset above 88: *93*, "Placebo", on both platforms.
  - A warning for an HDR photo with much bright sky (smooth, colored, brighter
    than SDR white; 5% of the photo or more, `--sky-warn` changes it): Photos'
    own rendering of an HDR JPEG XL shows faint pink patches in such skies, an
    Apple issue the file doesn't have (see the README's known issue). The
    batch's end says how many; the HEIC route avoids the patches.
- Changed
  - No grain is added to HDR JPEG XL copies any more. It only hid the steps of
    Apple's 8-bit rendering of an HDR JPEG XL, which shows the pink patches
    above anyway; the HEIC route avoids that rendering.
    `--grain FINE --grain-coarse COARSE` still add it (60+40 were the amounts
    tuned for quality 83).
  - The album the converted originals are collected in is *Compressed
    originals* (it was *Compressed to JXL*); a copy is never added to either.
    Notifications are titled *Compress Photos*.
  - Update both the shortcuts and the encoders: an older shortcut has no format
    question, and an older `jxlbatch` has no `--heic`.

## [Compress Photos 0.6.0] - 2026-10-06

- Added
  - The Mac shortcuts ask a third question, *HDR*: *Keep HDR* (as before), or
    *Drop HDR*, which saves every photo as an ordinary SDR JPEG XL
    (`jxlbatch --sdr`): smaller, without the color banding an HDR JPEG XL can
    show in smooth skies, and shown correctly by viewers that can't tone-map
    HDR.
  - HDR JPEG XL files get a little grain in their smooth areas, against the
    color banding Apple's SDR rendering of them showed in skies (it draws a PQ
    file through an 8-bit step with half the levels, and a lossy encode had
    removed the grain that would hide the steps). Two layers, fine and coarse,
    weighted by the picture's texture; `jxlbatch --grain` and `--grain-coarse`
    set the amounts (0: none). HDR files grow by about 10-15%; SDR files are
    unchanged. Photos converted earlier keep their banding until converted
    again from their originals.
  - The batch summary also says how much space was saved and its share of the
    originals' size (`Saved 1.1 MB (34%)`), below the sizes line.
- Changed
  - *Compress Photos* (iPhone) no longer offers to delete the originals.
    Instead, each converted still photo's original is added to the album
    *Compressed to JXL*, as on the Mac: from the picker, as each copy is saved;
    from the share sheet, before the conversion (the shortcut is over once
    a-Shell is in front), so a photo whose conversion fails is in the album
    too, and a-Shell's output names it. A photo already in the album isn't
    added again, and nothing is deleted.
  - Every converted original is collected, on both platforms, whether or not
    its JPEG XL has its HDR; the log's `!` notes say which lack it. Up to 0.5.0
    those were kept out of the album and of the delete prompt. The Mac picker
    route, which left the originals alone, collects them too.

## [Compress Videos 0.1.0] - 2026-10-05

- Added
  - *Compress Videos (macOS)*: select videos in Photos, then Share ▸ Compress
    Videos (macOS). Each video is converted to H.265 or AV1 with Opus sound,
    with HandBrake's settings (codec, preset, tune, quality RF, largest size,
    audio bitrate, asked as six questions, or "Same as last time"), and
    imported into Photos into its original's albums; the originals are
    collected in the album *Videos already compressed* for you to delete. The
    copies keep the capture date and time zone, location, camera, lens and
    Apple's other keys with their types, the rotation, HDR and Dolby Vision.
    Photos, Live Photos and slo-mo, spatial, Apple Log and unreadable videos
    are skipped and counted; a slo-mo is told from a 120 fps video by the
    iPhone's own mark. iPhone ProRes recordings are converted too. It works
    only on videos selected in Photos, and checks for free space before Photos
    exports them. A Terminal window follows the conversion with its progress
    and time left.
  - `ffmpeg-macos` and `ffprobe-macos`: FFmpeg 9.0.2 built for the shortcut,
    with only what it uses and three encoders built in, x265 4.3 (H.265, 8- and
    10-bit), SVT-AV1 4.2.0 (AV1) and libopus 1.6.1 (Opus), FFmpeg's ProRes
    decoder, and dav1d 1.5.4 to read AV1 videos; all in software, never the
    Mac's media engines. Static arm64 executables for macOS 14 or later,
    installed as `~/.local/bin/compress-videos-ffmpeg` and
    `compress-videos-ffprobe` so that they never replace another ffmpeg.
    Homebrew's ffmpeg 7.1 or later works too.
  - `vidmeta-macos`: copies a video's Apple metadata onto its converted copy
    byte for byte, which ffmpeg can't do, and reads the slo-mo and Apple Log
    marks. `vidmeta --selftest` checks an installation.

## [Compress Photos 0.5.0] - 2026-10-05

- Added
  - The Mac shortcuts ask, after the quality, how to use the Mac's cores. *All
    cores (fast)* converts several photos at a time, each with a share of the
    cores: two at a time on an 8-core Mac, three on 14 cores or more, fewer
    with less than 8 GB of memory; a batch of 18 photos took 7 s instead of
    10.5 s on a 14-core Mac. *One core (keeps the Mac responsive)* converts one
    photo at a time on one thread. The files are the same bytes either way, and
    the log and `jxl_done.txt` read as before, photo by photo in order (a
    photo's lines appear once the photos before it are done).
  - `jxlbatch -j N` converts N photos at a time (`-j 0`: from the cores and the
    memory) and `-t T` sets the threads per photo, in the builds with threads
    (`jxlbatch-macos`, `build-native.sh`); the WebAssembly build accepts both
    and converts one photo at a time, as before. The default is unchanged: one
    photo at a time with all the cores.
- Fixed
  - *Compress Photos (macOS)* from Photos spent longer after the conversion
    than on it with a large library: collecting the originals looked each one
    up with a `whose id is` filter, which scans the whole library (about 1.6 s
    per photo in a library of 58,000 items), and the album pass asked Photos
    for each album separately (about 17 ms each, 12 s for 689 albums). The
    originals are now referenced by id directly, the files are imported in one
    call instead of one per file (about 0.5 s each), and the albums' contents
    are read one folder at a time: for 37 photos in that library, Photos' part
    went from 88 s to 19 s (10 s importing, 9 s for 689 albums). The log's last
    lines now say how long Photos took for each of these steps, and the
    progress window says when Photos' part begins.
  - With several HEIF photos decoding at a time, libheif's memory accounting
    could fail one of them with "Security limit exceeded" (it counts a
    context's images in a table keyed by the context's address, and `jxlbatch`
    released a decoded image after its context). The context now stays until
    its images are released.
- Changed
  - Update the Mac shortcuts and `jxlbatch-macos` together: the shortcuts pass
    the new options, which an older encoder rejects (the log then shows its
    usage text and the version note). The iPhone shortcuts and `jxlbatch.wasm`
    only carry the new version number; iPhone users don't need to update.

## [Compress Photos 0.4.0] - 2026-10-04

- Added
  - Mac shortcuts. *Compress Photos (macOS)* converts the photos selected in
    Photos (Share menu, right-click ▸ Shortcuts, or the menu bar while Photos
    is in front): Photos exports the original files, the JPEG XL copies are
    imported into the originals' albums, and the originals whose copy has
    everything they have are collected in the album "Compressed to JXL" for you
    to delete. Started elsewhere, it shows a photo picker and saves the copies
    to Photos in the originals' albums, leaving the originals alone (nothing is
    deleted by the shortcut on the Mac). A Terminal window follows the
    conversion as it runs. *Compress Photo Files (macOS)* converts image files
    and folders from Finder's Quick Actions, writing each `.jxl` next to its
    original. Both run `jxlbatch` through Shortcuts' Run Shell Script action,
    with no a-Shell, no helper shortcut and no handoff, and show the encoder's
    log in Quick Look when it notes anything. See
    `shortcuts/compress-photos/README-mac.md`.
    - `jxlbatch-macos`: a native, statically linked build of the encoder for
      Apple silicon Macs running macOS 14 or later, with the same libraries and
      settings as `jxlbatch.wasm`, so its files are byte for byte the same, and
      with threads. Installed as `~/.local/bin/jxlbatch`. `jxlbatch --mac` (all
      builds) drops the hints about the iPhone's share sheet.
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
