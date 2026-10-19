# Compress Photos 0.10.0: JPEG XL photos as input

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. The problem](#1-the-problem)
- [2. Decisions](#2-decisions)
- [3. Design](#3-design)
  - [3.1. `photobatch`](#31-photobatch)
  - [3.2. The Mac shortcuts](#32-the-mac-shortcuts)
  - [3.3. The iPhone shortcut](#33-the-iphone-shortcut)
- [4. Spikes](#4-spikes)
- [5. Steps](#5-steps)
  - [5.1. Tests](#51-tests)
  - [5.2. Verification](#52-verification)

______________________________________________________________________

<!--TOC-->

Plan written 2026-10-16 and built the same day, as Compress Photos 0.10.0 (the
devices' checks, S3, S4 and 5.2, still to do). Compress Photos converted HEIF,
JPEG and PNG photos; a JPEG XL photo failed. This plan makes JPEG XL a fourth
input format, on the Mac and the iPhone, to both output formats (HEIC and JPEG
XL). How it works now is in
[DEVELOPING.md](../shortcuts/compress-photos/DEVELOPING.md#17-jpeg-xl-input).

## 1. The problem

The Mac's selection route, run on 2026-10-16 on one JPEG XL photo in Photos
(`IMG_6370`), logged:

```
[1/1] IMG_6370
  FAILED: unsupported format: only HEIF, JPEG and PNG photos can be converted
```

The shortcuts aren't what turns it away: Photos exported the original and
`selection.zsh` staged it, as it stages any file that isn't a video. The
encoder refuses it: `detect_format` (`meta.c`) knows HEIF, JPEG and PNG only,
and `photobatch` decodes those with libheif and stb_image. Every route ends
there (iPhone, Mac picker, Mac selection, Finder); the Finder shortcut also
leaves `.jxl` files out when given a folder (`files.zsh`'s glob).

Where JPEG XL photos come from: this tool's own copies (an HDR iPhone photo
becomes a 16-bit PQ JPEG XL with Apple's HDR profile; an SDR one an 8-bit JPEG
XL), and other apps (`cjxl`, Lightroom, darktable, lossless JPEG
recompression). Converting one again is useful to turn a JPEG XL copy into a
HEIC (Photos shows pink patches in HDR JPEG XL skies, see
[compress-photos-pink-sky.md](compress-photos-pink-sky.md)), or to shrink a
large lossless one. A lossy copy converted again loses quality a second time;
the docs say so.

## 2. Decisions

Settled by what the repository already does:

- **Decoding with libjxl's decoder**, which every build already links (the
  static libjxl 0.11.2 in `photobatch.wasm` and `photobatch-macos` is the whole
  library, decoder and brotli included; `jxl_has_profile` already uses
  `JxlDecoder`). No new library, no new license.
- **Metadata as for the other formats**: EXIF and XMP copied byte for byte,
  then the date and location from Photos (`apply_photo_date`,
  `apply_photos_meta`). A JPEG XL's metadata box that can't be read fails the
  photo rather than losing it, as an unreadable extended XMP does.
- **Upright pixels, orientation 1** in the copy's EXIF and XMP, as for HEIF.
- **Same bytes on the Mac and the iPhone**, if the decoder allows it (spike
  S1).

Decided by the owner (2026-10-16): the first option, (a), of each.

- **D1. An HDR JPEG XL to HEIC.** The HEIC route writes a JPEG XL as a new SDR
  HEIC (it can't attach a gain map to a new HEIC), and today refuses a PQ
  picture without a gain map (a PQ PNG) with "choose JPEG XL for it". (a) Keep
  HDR: refuse the same way, naming Drop HDR too; Drop HDR: tone-mapped to SDR
  by libjxl's decoder. (b) Tone-map in both cases, with a `!` note and the
  `keep` flag. Making a gain map HEIC from a PQ picture (an SDR rendition plus
  a gain map and ISO 21496-1 metadata) is a feature of its own, not part of
  this plan.
- **D2. A JPEG XL copy that isn't smaller than its JPEG XL original.**
  Converting a q83 copy at q83 gains nothing and loses quality. (a) Don't write
  it: `! not converted: the copy would not be smaller`, the original stays and
  isn't collected. (b) Write it, as for the other formats today (the batch
  summary already says "larger"). Changed by the owner (2026-10-19, 0.11.0):
  (b), for every format, with `! the copy is not smaller than the original`.
- **D3. An animated JPEG XL**: (a) fails, "an animated JPEG XL isn't a still
  photo". (b) Its first frame is converted.

## 3. Design

### 3.1. `photobatch`

**Detection** (`meta.c`, `meta.h`): `FMT_JXL` for a bare codestream (`FF 0A`)
and for the container (`00 00 00 0C 4A 58 4C 20 0D 0A 87 0A`); `format_name`
says `JPEG XL`. The "unsupported format" messages name JPEG XL.

**A new `src/jxl.c`**, with the decoder, as `heif.c` is libheif's:

- `jxl_boxes(buf, len, meta_t *m, err)`: the first `Exif` box (its first 4
  bytes are the offset to the TIFF header, skipped) and the first `xml ` box,
  with `JxlDecoderSetDecompressBoxes` on, so the brotli-compressed (`brob`)
  boxes `cjxl` writes by default are read too. Called by `meta_extract` for
  `FMT_JXL`, so both routes get the metadata as now. Other boxes (`jumb`,
  `jbrd`, `jhgm`) aren't kept, like a HEIC's auxiliary images.
- `jxl_decode(buf, len, sdr, runner, image_t *img, color_t *color, hdr_info_t *hdr, int *transposed, err)`,
  the pixels:
  - The whole picture into one malloc'ed buffer, then the decoder is destroyed
    before encoding starts, so the decoder's and the encoder's memory don't add
    up (measured below).
  - 8-bit samples when the file has 8 bits or fewer and SDR color, else 16-bit
    (`img.bits` from `bits_per_sample`). Float samples
    (`exponent_bits_per_sample` > 0) fail: no camera or Apple app writes them.
    Alpha is kept, as for PNG (the HEIC route then refuses it, as now).
  - **Orientation**: libjxl applies the codestream's orientation, which a JPEG
    XL reader must use; the EXIF's is ignored. `cjxl` puts a JPEG's orientation
    in both (checked: a JPEG with EXIF orientation 6 gives a JPEG XL with
    codestream orientation 6 *and* EXIF orientation 6), so applying the EXIF's
    too would turn the photo twice. `transposed` is set for codestream
    orientations 5 to 8, for the existing orientation check.
  - **Color**: with libjxl's CMS (`JxlDecoderSetCms`), the output is asked for
    in the file's own color space; without that, a lossy (XYB) file comes out
    as linear sRGB. A color space libjxl describes as an encoding (what it
    stores for this tool's SDR copies: sRGB or Display P3) becomes CICP code
    points (`cicp_from_color`, the inverse of `photobatch.c`'s
    `color_from_cicp`, both moved where `jxl.c` and `photobatch.c` share them).
    An ICC profile is used as it is, except a PQ or HLG profile with a `cicp`
    tag (Apple's HDR profile, as this tool stores it in HDR copies): the output
    is asked for in that encoding (Display P3 PQ), and the profile goes into
    `color.hdr_icc`, so `encode_jxl` stores it again and Apple's tone curve
    survives.
  - **HDR** (PQ or HLG): kept on the JPEG XL route as 16-bit pixels, with the
    file's `intensity_target` passed to `encode_jxl` (today it comes from the
    gain map's peak only). With `--sdr`, and on the HEIC route as D1 decides,
    the decoder tone-maps to SDR (`JxlDecoderSetDesiredIntensityTarget`, output
    in the same primaries with the sRGB curve), the log says `! HDR not kept`,
    and the line is flagged `keep` (the original had HDR the copy lacks), as
    for a JPEG with a gain map.
  - On the Mac, the job's libjxl thread pool decodes too.
- `process_job` and `process_heic_job` call `jxl_decode` where they call
  `stb_decode` for JPEG and PNG today, with `orient = 1`. The log's line reads
  `JPEG XL 5712x4284, HDR 3.0x` like the others.
- `--selftest` decodes a tiny embedded JPEG XL, so the phone checks the decoder
  too.

**Memory**, the iPhone's limit (`test_memory.py` allows 1.5 GB). Measured
2026-10-16 with Homebrew's `djxl` 0.12.0, one thread, decoding a synthetic 48
MP (8064x6048) 8-bit photo to pixels: 406 MB peak for the JPEG XL `photobatch`
0.9.0 writes at q83 (1.9 MB, single pass), 728 MB for the same picture from
`cjxl -q 83 -e 7 -p` (progressive). The pixels alone are 146 MB, and the
encoder then needs about 0.55 GB for 48 MP, so the peak should stay near 0.75
GB if the decoder is gone before the encoder starts. To confirm on the
WebAssembly build (S2).

### 3.2. The Mac shortcuts

- `files.zsh`: `jxl` in the folder glob. A result next to its original
  `Name.jxl` is `Name 2.jxl` (`unique`, as now: never replacing).
- `selection.zsh`: `jxl` in the glob that pairs a photo with its Live Photo
  video, for consistency (no camera makes a JPEG XL Live Photo).
- `build_mac_shortcuts.py`: the shortcuts' comments name JPEG XL.
- Nothing else: Photos already exports the `.jxl` (the failed run reached
  `photobatch`), and a copy of a copy is already handled
  (`import.applescript`'s `copyKeywords` drops the old copy's `compr`, `jxl`
  and `q=` keywords; the old copy is collected in "Compressed originals" as its
  original).

### 3.3. The iPhone shortcut

No action change expected: it hands the original file to a-Shell, and
`photobatch` decodes it. `build_shortcuts.py`'s comment names JPEG XL. From the
share sheet, "Send As: Automatic" may hand over a JPEG instead (S4); the
README's existing advice, Send As Current, applies.

## 4. Spikes

- **S1. The same pixels on every build.** The decoder computes in floats with
  SIMD: NEON on the Mac, WebAssembly SIMD and scalar on the iPhone. The encoder
  already gives the same bytes on all three; the decoder may not, and one
  sample off by one changes the copy's bytes. Compare the decoded pixels of the
  fixtures (5.1) from `photobatch-macos`, `photobatch.wasm` and
  `photobatch-scalar.wasm`. If they differ, the parity test compares JPEG XL
  inputs' pixels within one level instead of bytes, and DEVELOPING.md says so.
  **Result:** the two WebAssembly builds decode alike; the Mac's differs by at
  most 1 of 255 in about 0.02% of an 8-bit picture's samples and 6 of 65535 in
  2% of an HDR one's, so the parity test allows that.
- **S2. Memory on the WebAssembly build**: 24 and 48 MP JPEG XL inputs, single
  pass and progressive, both routes, under `wasmtime` with `/usr/bin/time -l`
  (as `test_memory.py` does). **Result** (48 MP): 0.55 GB to JPEG XL and 0.48
  GB to HEIC single pass, 0.64 GB progressive.
- **S3. The Mac's picker route**: what Shortcuts passes to Run Shell Script for
  a JPEG XL photo from the library (the `.jxl`, or a converted JPEG or HEIC).
  Check with `file` in a test run.
- **S4. The iPhone**: what the picker and the share sheet (Automatic and
  Current) hand to a-Shell for a JPEG XL photo.

## 5. Steps

1. Spikes S1 and S2 with a first `jxl.c`.
2. `photobatch`: detection, `jxl.c`, both routes, `--selftest`, the messages;
   D1 to D3 as decided.
3. Fixtures and tests (5.1).
4. `files.zsh`, `selection.zsh`, the builders' comments.
5. Docs: DEVELOPING.md (how JPEG XL is decoded, the layout table), README.md
   and README-mac.md ("only HEIF, JPEG and PNG", the troubleshooting rows, the
   Finder folder list, a note on converting copies again), the top-level
   README's table, `meta.h`'s and `pixels.h`'s comments. `VERSION` 0.10.0, and
   a CHANGELOG entry: users update the encoder on both platforms
   (`photobatch-macos`, `photobatch.wasm` in a-Shell) and the Mac shortcuts
   (the Finder folder glob; their version check warns anyway).
6. S3 and S4 on the devices, then the real runs (5.2).

### 5.1. Tests

Inputs made at test time (`test_jxl_input.py`'s `inputs`, with `cjxl` and
`photobatch.wasm`; nothing committed):

- `photobatch`'s own SDR and HDR copies (uncompressed `Exif` and `xml ` boxes;
  Display P3 encoding; PQ with the Apple-shaped profile from
  `photo_helpers.apple_shaped_hdr_profile`);
- `cjxl` files: `brob` metadata, codestream orientation 6 with EXIF orientation
  6, a bare codestream with no container or metadata, a lossless JPEG
  recompression (`jbrd`), 16-bit lossless, alpha, an ICC profile (Adobe RGB),
  animated, and a truncated file.

Tests, by file:

- `test_jxl_input.py` (built as one new file instead of additions to
  `test_conversion.py` and `test_heic.py`): each input to JPEG XL and to HEIC;
  pixels within the usual tolerance of `djxl`'s decode, upright, EXIF and XMP
  kept (orientation 1), color space kept, Apple's HDR profile kept in an HDR
  copy converted again, D1 to D3 as decided; also the date and location from
  Photos, a truncated JPEG XL failing cleanly, and the macOS build against the
  WebAssembly ones (S1's tolerance).
- `test_mac_script.py`: a folder with a `.jxl` (`Name 2.jxl` next to it).
- `test_memory.py`: 48 MP JPEG XL inputs, single pass and progressive, to both
  formats.
- `test_mac_shortcuts.py`: the folder glob and the Live Photo pairing in the
  generated scripts.

### 5.2. Verification

- `pre-commit run --all-files`, `tox -e tests`.
- Mac: the selection route on a JPEG XL in Photos (as `IMG_6370`), to HEIC and
  to JPEG XL: the copy shows upright with its date, location, albums and
  keywords, and the old copy is in "Compressed originals"; the picker route;
  the Finder shortcut on a folder.
- iPhone: a JPEG XL from the picker and from the share sheet, to both formats,
  with the new `photobatch.wasm` in a-Shell.
