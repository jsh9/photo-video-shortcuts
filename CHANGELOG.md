# Change Log

Each shortcut has its own version, shared by its `.shortcut` files and its
encoder. Every release includes the current files of all shortcuts.

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
  - Originals whose HDR isn't in the JPEG XL are not offered for deletion: a
    photo whose gain map can't be used (converted as SDR, with a note "HDR gain
    map not used" in a-Shell), an HDR photo sent as JPEG (with a note), and
    `--sdr`. `jxl_done.txt` lines are now `file|index|delete or keep|name`.
    **Update both the shortcuts and `jxlbatch.wasm`**: an older shortcut offers
    every converted original for deletion, and the new shortcut with an older
    `jxlbatch.wasm` offers none.
  - `jxlbatch --sdr` converts HDR photos as SDR (the shortcuts don't use it).
  - `jxlbatch --selftest` also checks HDR decoding and that Apple's HDR profile
    is kept.
- Changed
  - HDR photos are computed a region at a time as the encoder reads them, so a
    48 MP HDR photo takes about as much memory as an SDR one.
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
