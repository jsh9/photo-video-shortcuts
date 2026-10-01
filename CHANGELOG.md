# Change Log

Each shortcut has its own version, shared by its `.shortcut` files and its
encoder. Every release includes the current files of all shortcuts.

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
