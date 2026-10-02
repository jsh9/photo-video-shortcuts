# Compress Photos: developer notes

How the shortcut and its encoder, `jxlbatch`, work, and how to build them. For
installing and using it, see [README.md](README.md).

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. How it works](#1-how-it-works)
  - [1.1. XMP](#11-xmp)
  - [1.2. HDR](#12-hdr)
- [2. Layout](#2-layout)
- [3. Building (Mac)](#3-building-mac)
- [4. Generating the shortcuts](#4-generating-the-shortcuts)
- [5. Building the shortcuts by hand (fallback)](#5-building-the-shortcuts-by-hand-fallback)

______________________________________________________________________

<!--TOC-->

## 1. How it works

```
Compress Photos                              (shortcut)
   photos: from the share sheet, or else picked in its own photo picker
   asks for a quality preset, copies each original photo to a-Shell's shared
   folder as jxl_in_N.orig, writes jxl_job.txt, then runs in a-Shell:
     jxlbatch -q 83 -e 7 jxl_job.txt   (after a short wait, in a-Shell's
                                        Shortcuts folder; retried if a-Shell
                                        was still starting up)
a-Shell ▸ jxlbatch → jxl_out_N.jxl + jxl_done.txt, with progress on screen
then, from the share sheet:
   a-Shell starts JXL-Import (shortcut), which saves each JXL to Photos
   under its original name, adds it to the albums listed in
   jxl_albums_N.txt (written by Compress Photos), and cleans up
or, from the picker:
   a-Shell switches back to Compress Photos, which saves the JXLs,
   adds each to its original's albums, then asks to delete the
   originals whose JXL was saved (and has their HDR)
```

`jxlbatch` decodes the original itself (HEIF with libheif and libde265; JPEG
and PNG with stb_image) and encodes with libjxl 0.11.2.

`jxlbatch` copies the original's EXIF byte for byte into an uncompressed `Exif`
box, and XMP into an `xml ` box. Apple's image framework reads those boxes;
compressed (`brob`) boxes, which `cjxl` writes by default, it can't. Pixels are
stored upright, and the EXIF/XMP orientation is reset to match, so no viewer
can rotate a photo twice. 10-bit HEIF photos are kept at 10 bits.

Encoding settings match `cjxl -q Q -e E`, with one difference: libjxl's
streaming mode is always on, and the image is handed to it in chunks rather
than copied. libjxl reads those chunks region by region only when it also
writes through an output processor (`JxlEncoderSetOutputProcessor`); with
`JxlEncoderProcessOutput` it asks for the whole image at once. So `jxlbatch`
gives it one, except for images with alpha (a packed copy, which is rare). That
keeps a 24 MP photo at about 0.5 GB and a 48 MP one at about 0.55 GB, at any
quality, HDR included. By default, libjxl at effort 7 turns streaming off below
quality ~70 and holds the whole image, which takes about 2.7 GB for 24 MP, more
than iOS lets a-Shell use. The cost is files about 2.5% larger at those
qualities, with the same visual quality (SSIMULACRA2).

### 1.1. XMP

Ordinary XMP is copied byte for byte, whatever its format: photos from other
apps often carry XMP that isn't strict XML (trailing NUL bytes, Latin-1 text,
HTML entities, undeclared prefixes), and such photos still convert. In a JPEG,
the first nonempty XMP packet is used; empty or repeated packets are ignored.

The only change is the orientation: each TIFF `Orientation` value other than 1
is replaced with `1`, and every other byte stays the same. A tolerant scanner
in `src/xmp.cpp` finds the value without requiring strict XML:

- Like other XMP readers, it reads only top-level properties: the attributes
  and child elements of each `rdf:Description` directly inside `rdf:RDF`. A
  field of a structure, such as the metadata of a placed image that Adobe apps
  keep in `xmpMM:Pantry`, isn't the photo's own.
- It doesn't look for markup inside comments, CDATA, processing instructions or
  attribute values, so text that merely looks like the property isn't read or
  changed.
- An element's value is its text and CDATA (`<![CDATA[6]]>` is 6); comments and
  processing instructions inside it are skipped. A qualified value (one written
  with `rdf:value`) isn't read.
- It resolves the namespace of each prefix, so `tiff:` bound to another
  namespace is ignored and alternate prefixes work; an undeclared `tiff:`
  prefix is assumed to be the TIFF namespace.
- It decodes character references in values and in namespace declarations
  (`&#54;` is 6).

The same scanner finds the `HasExtendedXMP` reference.

Extended XMP, which a JPEG uses for XMP over 64 KB, is the only case that needs
XML parsing. Its fragments are assembled by GUID, total length and offset,
including fragments stored out of order. The standard packet's
namespace-qualified `HasExtendedXMP` reference must match. Coverage must be
complete and must not overlap; the assembled extension is limited to **16
MiB**.

`src/xmp.cpp` wraps vendored TinyXML2 11.0.0 behind the C interface in
`src/xmp.h`. It merges RDF properties into one valid packet, retains namespace
scope, arrays, structures and Unicode, and removes the JPEG-only
`HasExtendedXMP` property. Identical properties for the same RDF subject
coalesce; conflicting values fail rather than choosing a value. The result goes
into the existing uncompressed `xml ` box.

The internal `meta_extract` interface accepts an error buffer. When extended
XMP is present but can't be merged (missing, overlapping, mismatched, oversized
or invalid fragments, or conflicting values), that photo fails with a message
rather than losing metadata; other photos continue. This includes a
`HasExtendedXMP` reference with no fragments in the file, and a JPEG metadata
segment that is cut short, since either could mean metadata is lost. Failed
photos are absent from `jxl_done.txt`, so the shortcut cannot offer to delete
their originals. The CLI and job/result formats stay the same.

### 1.2. HDR

An HDR HEIC from an iPhone becomes an HDR JPEG XL: Photos and ImageIO show HDR
stored in the pixels as PQ, but ignore a JPEG XL gain map (`jhgm` box).
`src/heif.c` finds and decodes the parts; `src/hdr.c` decides whether they can
be used (independent of the file format); `src/gainmap.c` has the math.

- **ISO 21496-1 gain maps** (iOS 18 and later). libheif doesn't read the `tmap`
  item (the gain map's metadata), so `jxlbatch` finds it with libheif's generic
  item API: a `tmap` whose `dimg` inputs are the primary image and the gain
  map. Its data is parsed per ISO 21496-1 (version 0).
- **Apple's older gain maps** (iOS 14 to 17, iPhone 12 and later), as Apple
  documents them in "Applying Apple HDR effect to your photos": with no `tmap`,
  an auxiliary image of type `urn:com:apple:photo:2020:aux:hdrgainmap`. Its
  headroom comes from the photo's maker notes, tags 33 and 48 (exiftool's
  `HDRHeadroom` and `HDRGain`; Apple's maker notes start with `Apple iOS`, have
  their own byte order, and count offsets from their start): `stops` is
  `-20 * t48 + 1.8` (`t48 <= 0.01`) or `-0.101 * t48 + 1.601` when `t33 < 1`,
  else `-70 * t48 + 3` or `-0.303 * t48 + 2.303`; the headroom is
  `2^max(stops, 0)`. Without those tags the photo stays SDR.
- **Only Apple's gain maps are used**: those an iPhone labels with Apple's
  auxiliary image type (`auxC` `urn:com:apple:photo:2020:aux:hdrgainmap`, on
  ISO 21496-1 gain maps too). For those, how the gain map lines up with a
  turned or cropped photo is known (below); for others it isn't, and `jxlbatch`
  doesn't guess. ImageIO, for example, writes ISO gain maps without the label
  and without transforms of their own, and a gain map's shape can't tell
  whether a 180° turn, a mirror or a square photo's rotation applies to it. So
  such a photo is converted as SDR with
  `! HDR gain map not used (not an iPhone camera photo)`, and, by the owner's
  choice, its original may still be deleted (`delete` in `jxl_done.txt`), on
  every path (also with `--sdr` or malformed metadata). The batch ends with how
  many there were. Not checked yet: whether Photos keeps the label when it
  saves an edit, or other iPhone apps write it.
  `exiftool -AuxiliaryImageType photo.heic` shows
  `urn:com:apple:photo:2020:aux:hdrgainmap` when a file has it.
- **The gain map** is decoded like any image, by its item ID. On an iPhone it
  is Apple's auxiliary image (above), half or a quarter of the photo's size,
  8-bit grey. Apple stores it like the primary image, without its transforms
  (`irot` 0 on it, and a full-size gain map gets the primary's crop but not its
  rotation), so the primary's transforms apply to it, in order: rotations and
  mirrors turn it, and a crop (`clap`) narrows the part of it that covers the
  photo (the *window*). A gain map with a rotation or mirror of its own uses
  its own transforms instead. Either way, the gain map is decoded as stored and
  exactly one set of transforms applies. Monochrome values are expanded if the
  stream says limited range.
- **The photo** is decoded as stored too, then cropped and turned in RGB.
  libheif would crop and turn it before converting to RGB, which shifts the
  colors of a 4:2:0 photo cropped at an odd offset (up to 96 of 255 along the
  border of a rotated 427-row photo); Apple's rendering doesn't depend on that.
  Photos without a crop come out the same either way. The transforms apply in
  the file's order, whatever it is (a crop may follow the rotation). As in
  libheif, a crop reaching past the photo's edges is cut to the photo, and one
  that leaves nothing fails the photo (`invalid crop`); the gain map's window
  follows the same crop.
- **Derived photos** (e.g. an `iden` image of another image): decoding as
  stored only works when the photo's own transforms are its only ones, since
  libheif's `ignore_transformations` also skips those of the images it is
  derived from. Otherwise libheif applies all of them, as before 0.2.0, and a
  gain map isn't used ("unsupported image layout"): lining it up needs the
  transforms of both images. The same holds for a derived gain map, and for a
  transparency (alpha) image with transforms of its own: libheif turns it by
  those, which `ignore_transformations` skips too. iPhone photos are grids
  whose tiles have no transforms, and have no alpha image.
- **The math**, at full strength (the alternate rendition): the window is
  enlarged to the photo's size (center-aligned bilinear). For an ISO gain map
  value `g`, the gain is `log2 G = min + (max - min) * g^(1/gamma)`, and the
  SDR value, linearized with the sRGB curve, becomes
  `(sdr + base_offset) * G - alternate_offset`, in the photo's own primaries
  (`use_base_colour_space`). For Apple's older format, `g` is linearized with
  the inverse Rec. 709 curve and `hdr = sdr * (1 + (headroom - 1) * g)`.
- **The result** is 16-bit PQ with SDR white at 203 nits (ITU-R BT.2408), in
  Display P3 (or sRGB) primaries, computed from lookup tables a region at a
  time, as libjxl reads its chunks, so there is no 16-bit copy of the photo. It
  is encoded with libjxl's usual lossy settings, as PQ (CICP), with
  `intensity_target` set to the photo's peak (203 nits times the largest gain
  the gain map can give), not PQ's 10,000 nits; at most 10,000 nits, where PQ
  values clip (libjxl rejects targets above 65,504). Metadata claiming more
  than 16 stops (`GAINMAP_MAX_STOPS`, 65,536×; the alternate headroom or a
  channel's maximum, or for Apple's older format the headroom from its maker
  notes, whose formula has no bound as tag 48 goes negative) is rejected as
  malformed, so a broken or hostile file can't print an absurd headroom; real
  photos are far below it (iPhones reach about 3 stops). Other images leave it
  to libjxl, which picks it by the color stored: 10,000 nits for PQ (e.g. a PNG
  with a PQ `cICP` chunk), 255 for SDR.
- **Apple's HDR profile.** An iPhone HEIC with an ISO gain map also holds an
  ICC profile for the HDR rendition
  (`Display P3 Primaries; PQ (Adaptive Gain Curve …)`, about 27 KB) with an
  `hdgm` tag: the tone curve (Apple's Headroom Adaptive Gain Curve, SMPTE ST
  2094-50) Apple dims the HDR photo with on screens that can't show all of it,
  down to SDR. Without it, Apple assumes a 4.926× peak and dims a PQ image its
  standard way, so the JXL looks slightly darker than the original there.
  `jxlbatch` reads the profile from the `tmap` item, else the gain map, with
  its own small reader of the `meta` boxes because libheif gives profiles of
  images only, and stores the first one that libjxl reads as the pixels' color
  space (same primaries, D65, PQ) instead of the CICP label. The pixels don't
  change; the profile costs about 3 KB. Otherwise a-Shell says
  `! Apple's HDR profile not found` or `not used (unrecognized format)`. Photos
  with Apple's older gain map never have one.
- **Keeping the profile in a lossy file** relies on libjxl's behavior: in
  `JxlEncoderSetICCProfile`, libjxl decides (`DecideIfWantICC`, libjxl 0.11.2
  and 0.12.0) to replace a profile it can describe itself by that description,
  which drops the curve, unless the image is lossless at that moment. So the
  header is set as lossless while the profile is set, then as lossy (if that is
  rejected, the photo is encoded again without the profile).
  `test_hdr_profile.py` runs against the native build (Homebrew's libjxl) too,
  so a change in libjxl shows up there, and `--selftest` checks it on the
  phone. Decoding: libjxl gives such a file (lossy, with a profile) as linear
  sRGB unless asked for another color space, so the tests ask djxl for Display
  P3 PQ.
- **Not used** (the photo is converted as SDR, with
  `! HDR gain map not used (reason)`): a color profile other than Display P3 or
  sRGB with the sRGB curve, a gain map in another color space, a gain map whose
  shape doesn't match, malformed metadata (including more than 16 stops), other
  metadata versions, an older gain map without its maker notes, a gain map not
  labeled as Apple's (see above).
- **Kept originals.** Each `jxl_done.txt` line is
  `file|index|delete or keep|name`. `keep` means the original had HDR that the
  JXL lacks (a gain map that wasn't used, except one not labeled as Apple's; an
  HDR JPEG, which `jxlbatch` only detects; or `--sdr`), and the shortcut
  doesn't offer it for deletion. When every original is `keep`, the shortcut
  skips Delete Photos. Older shortcuts read only the first and last fields; a
  new shortcut with an older `jxlbatch` sees the name as the third field and
  keeps every original.
- **Metadata** is kept as for SDR photos. Apple's `HDRGainMap` XMP fields
  belong to the gain map's own XMP packet, not the photo's, so they aren't
  copied.
- **Test photos:** `tests/compress-photos/fixtures/hdr/` holds 45 tiny HEICs
  covering these layouts, with expected results from an independent NumPy
  implementation (`hdr_reference.py`); `fixtures/heif/` holds 8 SDR photos in
  HEIF layouts beyond an iPhone's (see "The photo" and "Derived photos" above).
  `make_hdr_fixtures.py` writes them, and `src/selftest_hdr_heic.h` (the
  `--selftest` HDR photo); regenerating needs ffmpeg with libx265, libheif's
  `heif-dec` and libjxl's `djxl` and `cjxl`. Apple's rendering is compared with
  Core Image test photos (`make_photo.swift`, ISO 21496-1 only). ImageIO
  doesn't label their gain maps, so `photo_helpers.with_apple_gain_map_label`
  adds Apple's label, a layout no real writer produces; the real iPhone layout
  is covered only by your own photos (`test_samples.py`). Apple can't decode
  the synthetic older-format photos (`apple_older*.heic`), so for that format
  only your own photos are compared with it (`test_samples.py`).

## 2. Layout

| Path                         | What it is                                                                                                                                                                                                                                                                                                                                                                      |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `release.json`               | complete encoder and shortcut filenames required by the release script                                                                                                                                                                                                                                                                                                          |
| `VERSION`                    | the version, shared by the shortcuts and `jxlbatch`; read by the build scripts                                                                                                                                                                                                                                                                                                  |
| `src/`                       | `jxlbatch`: `jxlbatch.c` (batch, encoding), `meta.c` (EXIF/XMP/ICC from HEIF, JPEG and PNG), `pixels.c` (decoded images, orientation), `heif.c` (libheif decoding), `hdr.c` (whether and how an HDR photo's gain map is used), `gainmap.c` (HDR from gain maps), `xmp.cpp` (namespace-aware XML/RDF), `selftest_heic.h` and `selftest_hdr_heic.h` (tiny HEICs for `--selftest`) |
| `third_party/`               | `stb_image.h` (JPEG and PNG decoding), `tinyxml2/` 11.0.0 (XMP XML parsing; zlib license)                                                                                                                                                                                                                                                                                       |
| `scripts/build-wasm.sh`      | builds `dist/jxlbatch.wasm` and `dist/jxlbatch-scalar.wasm` for a-Shell                                                                                                                                                                                                                                                                                                         |
| `scripts/build-native.sh`    | builds `build/jxlbatch` for the Mac, against Homebrew's libjxl and libheif (fast tests)                                                                                                                                                                                                                                                                                         |
| `scripts/build_shortcuts.py` | generates and signs the two `.shortcut` files into `dist/`                                                                                                                                                                                                                                                                                                                      |

`build/` and `dist/` are not committed. Release files are published on
[GitHub Releases](https://github.com/jsh9/photo-video-shortcuts/releases).

## 3. Building (Mac)

Run these from this folder (`shortcuts/compress-photos`):

```bash
./scripts/build-native.sh
./scripts/build-wasm.sh
python3 scripts/build_shortcuts.py --guess
```

- TinyXML2 is vendored with its license and compiled into the native, SIMD
  WebAssembly and scalar WebAssembly builds. Native C sources are compiled with
  `cc`, XML sources with `c++`; WebAssembly uses wasi-sdk's Clang/Clang++.
- **Prerequisites:** Homebrew `jpeg-xl libheif cmake ninja binaryen`.
- **What `build-wasm.sh` does:** it downloads wasi-sdk 34, libjxl v0.11.2,
  libheif v1.23.5 and libde265 v1.1.3 into the repository's `.deps/` folder,
  shared with the other tools. WASI has no threads, C++ exceptions or
  `mkstemp`, so it applies small edits:
  - libjxl: drops its threads dependency, the same edit as
    [gen2brain/jpegxl](https://github.com/gen2brain/jpegxl).
  - libheif: decodes on the calling thread, keeping HEVC deblocking and SAO;
    skips its exception wrapper and its temporary files (only used when writing
    HEIF).
- **`jxlbatch --selftest`** checks file access, large-file I/O, HEIF decoding
  (a tiny built-in HEIC), HDR decoding and keeping Apple's HDR profile (a tiny
  built-in HDR HEIC) and a 12 MP encode. Running it in a-Shell checks the
  phone.
- **Tests** are in `tests/compress-photos/`: the generated shortcuts, the
  encoder, end-to-end conversions checked with Apple's ImageIO, and the
  shortcut's a-Shell commands run against the encoder. Run `python3 -m pytest`
  from the repository root; see [tests/README.md](../../tests/README.md).

## 4. Generating the shortcuts

- `scripts/build_shortcuts.py` writes and signs the two `.shortcut` files into
  `dist/`. Signing uses macOS's `shortcuts sign`, so it runs on a Mac signed in
  to an Apple ID.
- `--guess` uses hand-written templates. a-Shell's actions are written as
  `AsheKube.app.a-Shell.<Intent>` with its parameter names from a-Shell's
  `Intents.intentdefinition`.
- If those don't import correctly, build a sample shortcut by hand on the
  iPhone. `build_shortcuts.py --fetch <iCloud link>` saves it as
  `scripts/sample/JXL Sample.plist`, and later runs copy the exact format from
  it.
- The quality presets are `QUALITY_PRESETS` near the top of the script.
- Releases are built and published by `scripts/release.py` at the repository
  root. They ship the two `.shortcut` files in one ZIP,
  `compress-photos-shortcuts-v<version>.zip`; see
  [docs/releasing.md](../../docs/releasing.md).

## 5. Building the shortcuts by hand (fallback)

Use this if the `.shortcut` files won't import. The a-Shell actions are under
Apps ▸ a-Shell. Turn on each action's toggles as listed.

**JXL-Import** (build this first; no share sheet):

1. a-Shell **Get File**: `jxl_done.txt`, Error If Not Found on.
2. **Get Text from Input**: File.
3. **Split Text**: Text, by New Lines.
4. **Repeat with Each** item in Split Text:
   1. **Split Text**: Repeat Item, by Custom `|`.
   2. **Get Item from List**: First Item of Split Text.
   3. **Get Item from List**: Last Item of Split Text (the one from step 4.1).
   4. a-Shell **Get File**: the First Item, Error If Not Found on.
   5. **Set Name**: File to Last Item, with Don't Include File Extension on.
   6. **Save to Photo Album**: Renamed Item, to Recents.
   7. **Get Item from List**: Item At Index 2 of the `|` split (the photo's
      position).
   8. a-Shell **Get File**: `jxl_albums_<Item from List>.txt`, Error If Not
      Found **off**.
   9. **If** File has any value:
      1. **Get Text from Input**: File, then **Split Text** by New Lines.
      2. **Repeat with Each** item in Split Text: **Save to Photo Album**:
         Saved Photo Media, to Repeat Item 2.
      3. **End If** (Otherwise stays empty).
5. **Count**: Items in the Split Text from step 3.
6. a-Shell **Execute Command**:
   `rm -f jxl_in_* jxl_out_* jxl_albums_* jxl_job.txt jxl_done.txt jxl_started`,
   Keep Going on.
7. **Show Notification**: `Saved <Count> photo(s) to Photos.`

**Compress Photos** (Details: Show in Share Sheet, receives Images; if there's
no input: Continue):

1. **If** Shortcut Input has any value:
   - **Set Variable** `Photos` to Shortcut Input.
   - **Otherwise:** **Select Photos** (Select Multiple on), then **Set
     Variable** `Photos` to Photos.
   - **End If**.
2. The quality list:
   1. **Text**: one contact card per preset, one after another:
      ```
      BEGIN:VCARD
      VERSION:3.0
      N;CHARSET=utf-8:83 (default)
      ORG;CHARSET=utf-8:Go-to option for everyday scenes (almost perfect blue sky)\; film grains well preserved
      END:VCARD
      ```
      Put a backslash before any `;` in the description.
   2. **Set Name**: Text to `quality.vcf`, Don't Include File Extension on.
   3. **Get Contacts from Input**: Renamed Item.
   4. **Choose from List**: Contacts, prompt `JPEG XL quality`.
   5. **Get Name** of Chosen Item.
   6. **Match Text**: `\d+` in Name. Its Matches is the quality.
3. a-Shell **Execute Command**:
   `rm -f jxl_done.txt jxl_out_* jxl_albums_* jxl_started`, Keep Going on.
4. **Repeat with Each** item in `Photos`:
   1. **Get Name** of Repeat Item.
   2. **Set Name**: Repeat Item to `jxl_in_<Repeat Index>.orig`, Don't Include
      File Extension on.
   3. a-Shell **Put File**: Renamed Item, Overwrite on.
   4. **Text**: `<Repeat Index>|<Name>`.
   5. **Add to Variable**: Text to `Jobs`.
5. **Combine Text**: `Jobs` with New Lines.
6. **Set Name**: Combined Text to `jxl_job.txt`, Don't Include File Extension
   on.
7. a-Shell **Put File**: Renamed Item, Overwrite on.
8. **If** Shortcut Input has any value:
   1. **Repeat with Each** item in `Photos`:
      1. **Get Details of Images**: Album of Repeat Item.
      2. **If** Album has any value: **Combine Text** Album with New Lines,
         **Set Name** to `jxl_albums_<Repeat Index>.txt` (Don't Include File
         Extension on), a-Shell **Put File** (Overwrite on). **End If**.
   2. a-Shell **Execute Command**, Keep Going off, with these commands:
      - `sleep 2`
      - `cd ~shortcuts`
      - `jxlbatch -q <Matches> -e 7 jxl_job.txt`
      - `jxlbatch --retry -q <Matches> -e 7 jxl_job.txt`
      - `open shortcuts://run-shortcut?name=JXL-Import`
   - **Otherwise:**
     1. The same **Execute Command**, but with `open shortcuts://` as the last
        command.
     2. **Wait to Return**.
     3. Steps 1–5 of JXL-Import, but inside the repeat, replace steps 4.8–4.9
        with:
        1. **Get Item from List**: that item of `Photos` (the original).
        2. **Get Item from List**: Item At Index 3 of the `|` split, then
           **Match Text** `^delete$` in it (Case Sensitive). **If** Matches has
           any value: **Add to Variable** `Converted` (the original). **End
           If**. (`keep` means the JXL lacks the original's HDR.)
        3. **Get Details of Images**: Album of that original.
        4. **Repeat with Each** item in Album: **Save to Photo Album**: Saved
           Photo Media, to Repeat Item 2.
     4. Steps 6–7 of JXL-Import.
     5. **Delete Photos**: `Converted`.
   - **End If**.

The wait, the `cd` and the retry cover a-Shell being launched by the shortcut.
a-Shell then restores its last session, including its folder, while it starts
the commands, and its WebAssembly engine may still be loading, which ends the
first `jxlbatch` before it runs. After the wait, `cd ~shortcuts` changes to the
Shortcuts folder, where Put File saves. `jxlbatch` creates `jxl_started` when
it runs, and `--retry` does nothing when that file exists. The retry can't go
through `dash`: a-Shell adds `.wasm` to a command's name, dash doesn't.
