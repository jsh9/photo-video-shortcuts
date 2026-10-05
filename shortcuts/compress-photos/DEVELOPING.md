# Compress Photos: developer notes

How the shortcuts and their encoder, `jxlbatch`, work, and how to build them.
For installing and using them, see [README.md](README.md) (iPhone) and
[README-mac.md](README-mac.md) (Mac).

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. How it works](#1-how-it-works)
  - [1.1. On the Mac](#11-on-the-mac)
  - [1.2. XMP](#12-xmp)
  - [1.3. HDR](#13-hdr)
- [2. Layout](#2-layout)
- [3. Building (Mac)](#3-building-mac)
- [4. Generating the shortcuts](#4-generating-the-shortcuts)
- [5. Building the shortcuts by hand (fallback)](#5-building-the-shortcuts-by-hand-fallback)
- [6. Releasing a new version](#6-releasing-a-new-version)

______________________________________________________________________

<!--TOC-->

## 1. How it works

```
Compress Photos                              (shortcut)
   photos: from the share sheet, or else picked in its own photo picker
   keeps the still photos (skips Live Photos and videos, and says how many),
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

Only still photos are staged. Each item is sorted by its own details, which Get
Details of Images reads in memory from the item, with no photo library query:
`Media Type` (Image, Video or Audio) and, for an image, `Photo Type` (a list:
HDR, Panorama, Burst, Live Photo; empty for a plain still photo or a
screenshot, so it is only read when it has a value). Live Photos (HDR ones too)
and videos go into the variables `Skipped Live Photos` and `Skipped Videos`,
counted for a notification. The rest, the items themselves (not copies, so the
share sheet's Send As choice is kept), go into `Stills`, which replaces
`Photos` from then on, so the job indices are positions in `Stills`; when it is
empty, the shortcut says "Nothing to convert" and stops before the quality
list. What this relies on (ContentKit's `WFImageContentItem` and
`WFPhotoMediaContentItem`, read from iOS 18.2):

- Property names and values are stored as English names (`Media Type`, `Image`,
  `Photo Type`, `Live Photo`), whatever the phone's language, and each Get
  Details output is named after its property.
- A photo from the library answers with its asset's media type and subtypes. An
  image that isn't in the library, such as one shared from Files, answers
  `Image` with no Photo Type, so it is converted like a photo, as before 0.3.0
  (JXL-Import saves the result to Photos; nothing is deleted from the share
  sheet). An item with no Media Type at all is converted too.
- A list put into a text field is one entry per line, so Match Text
  `Live Photo` finds it in an HDR Live Photo's `HDR`, `Live Photo`. Match Text
  is only run on a value that exists (an If "has any value" first).

Filter Photos can't do this, and 0.3.0, which used it, failed on every photo.
With photos from the library as its input, Shortcuts turns a `Photo Type`
condition into a Photos-framework predicate on the key `mediaSubtype`, which
`PHAsset` objects don't answer, and evaluates it on the input items in memory
(`-[NSArray filteredArrayUsingPredicate:]`), so the action throws
`NSUnknownKeyException` and the shortcut dies: nothing visible from the share
sheet, "There was a problem running the shortcut" from the Shortcuts app. (A
`Media Type` condition alone would work: `mediaType` is a real key.) And with
an item that isn't in the library, it doesn't test the item at all but searches
the whole library.

The photo picker (Select Photos) shows Images only, which hides videos; Live
Photos still show, and are skipped. `test_photo_selection.py` runs this part of
the shortcut on a model of these rules.

`jxlbatch` decodes the original itself (HEIF with libheif and libde265; JPEG
and PNG with stb_image) and encodes with libjxl 0.11.2.

`jxlbatch` copies the original's EXIF byte for byte into an uncompressed `Exif`
box, and XMP into an `xml ` box. Apple's image framework reads those boxes;
compressed (`brob`) boxes, which `cjxl` writes by default, it can't. Pixels are
stored upright, and the EXIF/XMP orientation is reset to match, so no viewer
can rotate a photo twice. a-Shell warns (`! orientation check`) when the result
is portrait but the original's EXIF orientation and size say landscape, or the
other way round; only when that EXIF size is the photo's size as stored (the
result's, transposed if the HEIF transforms turned it), since an edited photo's
EXIF keeps the size from before the edit (Photos does so, also for a photo it
stores upright). 10-bit HEIF photos are kept at 10 bits.

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

### 1.1. On the Mac

```
Compress Photos (macOS)                      (shortcut)
   photos: from the Share menu in Photos, or else picked in its own photo picker
   keeps the still photos (same as the iPhone), asks for a quality preset,
   collects the photos' names, then Run Shell Script (/bin/zsh, the photos
   passed as files, "$@"):
     scripts/mac/common.zsh + photos.zsh: finds jxlbatch (~/.local/bin, ~/bin,
     /usr/local/bin, /opt/homebrew/bin), stages jxl_in_N.orig as symlinks and
     writes jxl_job.txt in compress-photos-macos/ inside Shortcuts' iCloud
     Drive folder (~/Library/Mobile Documents/iCloud~is~workflow~my~workflows/
     Documents), runs
       jxlbatch -q 83 -e 7 -C "$WORK" jxl_job.txt   (log in jxl_log.txt)
     and prints jxl_done.txt's lines:
       jxl_out_N.jxl|N|delete or keep|Name.jxl
   then, for each line: Get File (compress-photos-macos/jxl_out_N.jxl, relative
   to the Shortcuts folder in iCloud Drive) reads the file, which is renamed
   and saved to Photos and added to the original's albums; only when the
   save produced a photo is a "delete" line's original added to Converted
   the log is shown in Quick Look if it has a "!" note, an error or a failed
   photo; the work folder is removed; a notification counts the saved photos;
   Delete Photos asks about Converted (from the Share menu too)

Compress Photo Files (macOS)                 (shortcut, Finder Quick Action)
   files and folders from Finder; each input's File Path; a quality preset;
   Run Shell Script with common.zsh + files.zsh: stages each file (a folder's
   HEIF/JPEG/PNG files), runs jxlbatch, moves each jxl_out_N.jxl next to its
   original as Name.jxl (never replacing: "Name 2.jxl"; ~/Pictures/JPEG XL
   when the original's folder is unknown or not writable), prints the log and
   "Wrote N JPEG XL file(s)."; Quick Look of the log on notes, a notification
```

Run Shell Script waits for the script, so there is no handoff, no helper
shortcut, no marker files and no retry. The work folder of the Photos shortcut
is inside Shortcuts' iCloud Drive folder because that is the one place a file
written by a script gets back into Shortcuts on the Mac: Get File with a path
relative to that folder works, while Run AppleScript's file results
(`POSIX file`, `alias`, file URL) come back as nothing and Get File refuses
absolute paths (checked on macOS 26 with a diagnostic shortcut; see
`docs/compress-photos-mac-design.md`, section 5). The Finder shortcut needs no
bridge and works in `$TMPDIR`. A save that produces nothing (for example with
iCloud Drive off for Shortcuts) leaves the original alone and is listed in the
log as `! not saved to Photos`. The script is assembled by
`build_mac_shortcuts.py` from `scripts/mac/*.zsh` with the quality, the lines
of names or paths, and the Skipped Echo as Shortcuts variables; `jxlbatch`
itself and the job and result files are the iPhone's. The encoder is the static
macOS build (`build-macos.sh`), with threads; its output is byte for byte
`jxlbatch.wasm`'s (`test_mac_script.py` checks this). Shortcuts hands the
script the photos as files whose names may not be the photos' names, so the
shortcut passes the names (Get Name) in job order and the script uses them for
the job names; the Finder shortcut passes each input's File Path the same way,
so results land next to the originals even when Shortcuts passed a temporary
copy. A `JXLBATCH` environment variable overrides the encoder search (the tests
use it). The script never exits nonzero for a conversion problem: it writes
`ERROR:` lines to the log instead, which the shortcut then shows.

What the Mac shortcuts rely on, to confirm on a Mac when a Shortcuts version
changes (see `docs/compress-photos-mac-design.md`, section 5): the plist keys
of Run Shell Script (`Script`, `Shell`, `Input`, `InputMode` with
`as arguments`; confirmed on macOS 26) and Get File (`WFGetFilePath`,
`WFFileStorageService` iCloud Drive; confirmed), that Save to Photo Album
accepts a `.jxl` File, and that the Share menu in Photos passes the photos as
images with their library details (Album, Media Type, Photo Type).

### 1.2. XMP

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

### 1.3. HDR

An HDR HEIC from an iPhone becomes an HDR JPEG XL: Photos and ImageIO show HDR
stored in the pixels as PQ, but ignore a JPEG XL gain map (`jhgm` box).
`src/heif.c` finds and decodes the parts; `src/hdr.c` decides whether they can
be used (independent of the file format); `src/gainmap.c` has the math.

- **ISO 21496-1 gain maps** (iOS 18 and later). libheif doesn't read the `tmap`
  item (the gain map's metadata), so `jxlbatch` finds it with libheif's generic
  item API: a `tmap` whose `dimg` inputs are the primary image and the gain
  map. Its data is parsed per ISO 21496-1 (version 0).
- **Apple's older gain maps** (iOS 14 to 17, iPhone 12 and later), as Apple
  documents them in
  ["Applying Apple HDR effect to your photos"](https://developer.apple.com/documentation/appkit/applying-apple-hdr-effect-to-your-photos)
  (except the gain map's curve; see "The math" below): with no `tmap`, an
  auxiliary image of type `urn:com:apple:photo:2020:aux:hdrgainmap`. Its
  headroom comes from the photo's maker notes, tags 33 and 48 (exiftool's
  `HDRHeadroom` and `HDRGain`; Apple's maker notes start with `Apple iOS`, have
  their own byte order, and count offsets from their start): `stops` is
  `-20 * t48 + 1.8` (`t48 <= 0.01`) or `-0.101 * t48 + 1.601` when `t33 < 1`,
  else `-70 * t48 + 3` or `-0.303 * t48 + 2.303`; the headroom is
  `2^max(stops, 0)`. Without those tags the photo stays SDR.
- **Which gain maps are used**: those an iPhone camera labels with Apple's
  auxiliary image type (`auxC` `urn:com:apple:photo:2020:aux:hdrgainmap`, on
  ISO 21496-1 gain maps too). For those, how the gain map lines up with a
  turned or cropped photo is known (below). An ISO gain map without the label
  is used too if neither it nor the photo is turned and the photo has no crop:
  it then covers the photo as stored. Photos (iOS 26) saves an edited photo
  that way (checked with crops): a new HEIC with the photo upright at its new
  size (`irot` 0, no `clap`, EXIF orientation 1), a half-size gain map without
  the label (no `auxC`, no `auxl` reference), sometimes with a `clap` of its
  own, and a `tmap` item with an nclx `colr` (12/16/6, no ICC profile, so no
  `hdgm` curve) and `use_base_colour_space` 0. So the edit drops the curve the
  camera original had, and the gain map is a new one (an exposure edit raised a
  photo's headroom from 3.5× to 8×). An edited photo with Apple's older gain
  map keeps the label. For other unlabeled gain maps `jxlbatch` doesn't guess.
  ImageIO, for example, writes ISO gain maps without the label and without
  transforms of their own, and a gain map's shape can't tell whether a 180°
  turn, a mirror or a square photo's rotation applies to it. So such a photo,
  if turned or cropped, is converted as SDR with
  `! HDR gain map not used (not an iPhone camera photo)`, and, by the owner's
  choice, its original may still be deleted (`delete` in `jxl_done.txt`), on
  every path (also with `--sdr` or malformed metadata). The batch ends with how
  many there were. Not checked: whether other iPhone apps write the label.
  `exiftool -a -AuxiliaryImageType photo.heic` lists
  `urn:com:apple:photo:2020:aux:hdrgainmap` when a file has it. The `-a`
  matters: an iPhone 17 Pro photo, for example, has four auxiliary images (also
  `tag:apple.com,2023:photo:aux:styledeltamap`,
  `urn:com:apple:photo:2020:aux:semanticskymatte` and
  `tag:apple.com,2023:photo:aux:linearthumbnail`), and without `-a` exiftool
  shows only one of them. The other three aren't kept in the JXL.
- **The gain map** is decoded like any image, by its item ID. On an iPhone it
  is Apple's auxiliary image (above), half or a quarter of the photo's size,
  8-bit grey. Apple stores it like the primary image, without its transforms
  (`irot` 0 on it, and a full-size gain map gets the primary's crop but not its
  rotation), so the primary's transforms apply to it, in order: rotations and
  mirrors turn it, and a crop (`clap`) narrows the part of it that covers the
  photo (the *window*). A gain map with a rotation or mirror of its own uses
  its own transforms instead, and so does one with a crop of its own on a photo
  that is neither cropped nor turned (as Photos saves an edit, also with
  Apple's older gain maps). Either way, the gain map is decoded as stored and
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
  (`use_base_colour_space`), or in the HDR image's (`use_base_colour_space` 0,
  as Photos writes for an edited photo), which is the same when they have the
  photo's primaries. Those come from the `tmap` item's color: its ICC profile's
  `cicp` tag, or else its nclx `colr`; other or unknown primaries aren't used.
  For Apple's older format, `hdr = sdr * (1 + (headroom - 1) * g^2.2)`.
  [Apple's documentation](https://developer.apple.com/documentation/appkit/applying-apple-hdr-effect-to-your-photos)
  says `g` is encoded with the Rec. 709 curve, but Apple's renderer uses a
  gamma of 2.2: fitted pixel by pixel against Core Image's HDR and SDR
  renderings of three iPhone 13 and 13 mini photos (macOS 27,
  `tests/compress-photos/hdr_pixels.swift`), gamma 2.2 is off by 0.001 or less
  (rms, in `(gain - 1) / (headroom - 1)`), the sRGB curve by 0.004 and Rec. 709
  by 0.028, which is 8-15% too bright in the midtones (issue #6). The gain at
  values near 1 matches the headroom from the maker notes.
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
  standard way, so the JXL doesn't look like the original there: darker for the
  camera originals tested, brighter for a heavily edited photo whose SDR
  rendition is much darker than its HDR one (both match at full brightness).
  `jxlbatch` reads the profile from the `tmap` item, else the gain map, with
  its own small reader of the `meta` boxes because libheif gives profiles of
  images only, and stores the first one that libjxl reads as the pixels' color
  space (same primaries, D65, PQ) instead of the CICP label. The pixels don't
  change; the profile costs about 3 KB. Otherwise a-Shell says
  `! Apple's HDR profile not found` or `not used (unrecognized format)`. Photos
  with Apple's older gain map never have one, nor do photos edited in Photos.
  On iOS 26 the profile has no TRC or colorant tags (`desc`, `cprt`, `wtpt`,
  `A2B0`, `B2A0`, `chad`, `cicp`, `hdgm`), and its `A2B0` is an `mAB ` without
  B curves. Homebrew's libjxl (lcms2) reads it by its `cicp` tag (Display P3
  PQ), but skcms, libjxl's color engine in the WebAssembly build, rejects the
  `A2B0` tag, and with it the whole profile, before reading the `cicp` tag; so
  `build-wasm.sh` patches skcms (see [Building](#3-building-mac)). For a PQ
  profile, libjxl uses only the `cicp` tag and transforms with a profile of its
  own. Apple's profile can't be committed, so
  `photo_helpers.apple_shaped_hdr_profile` reshapes libjxl's the same way, for
  `test_hdr_profile.py` and the `--selftest` photo.
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
  sRGB with the sRGB curve, a gain map applied in another color space (or one
  of unknown primaries), a gain map whose shape doesn't match, malformed
  metadata (including more than 16 stops), other metadata versions, an older
  gain map without its maker notes, a gain map not labeled as Apple's on a
  turned or cropped photo (see above).
- **Kept originals.** Each `jxl_done.txt` line is
  `file|index|delete or keep|name`. `keep` means the original had HDR that the
  JXL lacks (a gain map that wasn't used, except an unlabeled one on a turned
  or cropped photo; an HDR JPEG, which `jxlbatch` only detects; or `--sdr`),
  and the shortcut doesn't offer it for deletion. When every original is
  `keep`, the shortcut skips Delete Photos. Older shortcuts read only the first
  and last fields; a new shortcut with an older `jxlbatch` sees the name as the
  third field and keeps every original.
- **Metadata** is kept as for SDR photos. Apple's `HDRGainMap` XMP fields
  belong to the gain map's own XMP packet (linked to the gain map by `cdsc`),
  not the photo's, so they aren't copied: an EXIF or XMP item linked only to
  other images is never taken as the photo's, even when the photo has none (an
  iPhone 13 photo from iOS 15 has XMP on its gain map only).
- **Test photos:** `tests/compress-photos/fixtures/hdr/` holds 52 tiny HEICs
  covering these layouts (`edited_in_photos` is laid out as Photos saves an
  edit), with expected results from an independent NumPy implementation
  (`hdr_reference.py`); `fixtures/heif/` holds 8 SDR photos in HEIF layouts
  beyond an iPhone's (see "The photo" and "Derived photos" above).
  `make_hdr_fixtures.py` writes them, and `src/selftest_hdr_heic.h` (the
  `--selftest` HDR photo); regenerating needs ffmpeg with libx265, libheif's
  `heif-dec` and libjxl's `djxl` and `cjxl`. Apple's rendering is compared with
  Core Image test photos (`make_photo.swift`, ISO 21496-1 only). ImageIO
  doesn't label their gain maps, so `photo_helpers.with_apple_gain_map_label`
  adds Apple's label, a layout no real writer produces; the real iPhone camera
  layout is covered only by your own photos (`test_samples.py`). Apple can't
  decode the synthetic older-format photos (`apple_older*.heic`), so for that
  format only your own photos are compared with it (`test_samples.py`).

## 2. Layout

| Path                                                  | What it is                                                                                                                                                                                                                                                                                                                                                                      |
| ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `release.json`                                        | complete encoder and shortcut filenames required by the release script                                                                                                                                                                                                                                                                                                          |
| `VERSION`                                             | the version, shared by the shortcuts and `jxlbatch`; read by the build scripts                                                                                                                                                                                                                                                                                                  |
| `src/`                                                | `jxlbatch`: `jxlbatch.c` (batch, encoding), `meta.c` (EXIF/XMP/ICC from HEIF, JPEG and PNG), `pixels.c` (decoded images, orientation), `heif.c` (libheif decoding), `hdr.c` (whether and how an HDR photo's gain map is used), `gainmap.c` (HDR from gain maps), `xmp.cpp` (namespace-aware XML/RDF), `selftest_heic.h` and `selftest_hdr_heic.h` (tiny HEICs for `--selftest`) |
| `third_party/`                                        | `stb_image.h` (JPEG and PNG decoding), `tinyxml2/` 11.0.0 (XMP XML parsing; zlib license)                                                                                                                                                                                                                                                                                       |
| `scripts/build-wasm.sh`                               | builds `dist/jxlbatch.wasm` and `dist/jxlbatch-scalar.wasm` for a-Shell                                                                                                                                                                                                                                                                                                         |
| `scripts/build-macos.sh`                              | builds `dist/jxlbatch-macos`, the static arm64 macOS encoder for the Mac shortcuts (macOS 14 or later)                                                                                                                                                                                                                                                                          |
| `scripts/build-native.sh`                             | builds `build/jxlbatch` for the Mac, against Homebrew's libjxl and libheif (fast tests)                                                                                                                                                                                                                                                                                         |
| `scripts/patch_deps.py`                               | the small edits to the library sources in `.deps/`, shared by `build-wasm.sh` (WASI and skcms) and `build-macos.sh` (skcms)                                                                                                                                                                                                                                                     |
| `scripts/wf.py`                                       | the Shortcuts plist builder shared by both platforms: text and variables, built-in actions, the quality list, the still-photo filter, writing and signing                                                                                                                                                                                                                       |
| `scripts/build_shortcuts.py`                          | generates and signs the two iPhone `.shortcut` files into `dist/`                                                                                                                                                                                                                                                                                                               |
| `scripts/build_mac_shortcuts.py`, `scripts/mac/*.zsh` | generates and signs the two Mac `.shortcut` files into `dist/`; the zsh script they run (`common.zsh`, `run.zsh`, `photos.zsh`, `files.zsh`)                                                                                                                                                                                                                                    |

`build/` and `dist/` are not committed. Release files are published on
[GitHub Releases](https://github.com/jsh9/photo-video-shortcuts/releases).

## 3. Building (Mac)

Run these from this folder (`shortcuts/compress-photos`):

```bash
./scripts/build-native.sh
./scripts/build-wasm.sh
./scripts/build-macos.sh
python3 scripts/build_shortcuts.py --guess
python3 scripts/build_mac_shortcuts.py --guess
```

- TinyXML2 is vendored with its license and compiled into the native, SIMD
  WebAssembly and scalar WebAssembly builds. Native C sources are compiled with
  `cc`, XML sources with `c++`; WebAssembly uses wasi-sdk's Clang/Clang++.
- **Prerequisites:** Homebrew `jpeg-xl libheif cmake ninja binaryen`.
- **What `build-wasm.sh` does:** it downloads wasi-sdk 34, libjxl v0.11.2,
  libheif v1.23.5 and libde265 v1.1.3 into the repository's `.deps/` folder,
  shared with the other tools. WASI has no threads, C++ exceptions or
  `mkstemp`, so it applies small edits (`scripts/patch_deps.py --wasi`), and
  one more for Apple's HDR profile (`--skcms`):
  - libjxl: drops its threads dependency, the same edit as
    [gen2brain/jpegxl](https://github.com/gen2brain/jpegxl).
  - libheif: decodes on the calling thread, keeping HEVC deblocking and SAO;
    skips its exception wrapper and its temporary files (only used when writing
    HEIF).
  - skcms (libjxl's pinned copy, its color engine here): `skcms_Parse` reads
    the `cicp` tag before the `A2B0` and `B2A0` tags, and accepts a profile
    that is PQ by that tag even if it can't read those, as in Apple's HDR
    profile (see [HDR](#12-hdr)). Profiles without a PQ `cicp` tag parse as
    before. The native build uses Homebrew's libjxl, with lcms2, which needs no
    patch.
- **What `build-macos.sh` does:** the same libraries, the same feature flags
  and the same skcms edit, built as static arm64 libraries for macOS 14 or
  later (CMake, in `build/macos/`), from a second libjxl checkout,
  `.deps/libjxl-native`, since `build-wasm.sh` patches the threads out of
  `.deps/libjxl` (the libheif edits are guarded by `__wasi__` and
  `__cpp_exceptions`, so that checkout is shared). `jxlbatch` is compiled with
  `-DJXLBATCH_THREADS` (libjxl's thread pool), linked statically (the result
  depends only on `libc++` and `libSystem`, which the script checks with
  `otool -L`), stripped and ad-hoc signed. It refuses to run on an Intel Mac.
  The output is byte for byte `jxlbatch.wasm`'s (`test_mac_script.py`).
- **`jxlbatch --selftest`** checks file access, large-file I/O, HEIF decoding
  (a tiny built-in HEIC), HDR decoding and keeping Apple's HDR profile (a tiny
  built-in HDR HEIC) and a 12 MP encode. Running it in a-Shell checks the
  phone.
- **Tests** are in `tests/compress-photos/`: the generated shortcuts (both
  platforms), the encoder (all four builds), end-to-end conversions checked
  with Apple's ImageIO, the iPhone shortcut's a-Shell commands run against the
  encoder, and the Mac shortcuts' zsh script run for real. Run
  `python3 -m pytest` from the repository root; see
  [tests/README.md](../../tests/README.md).

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
- `scripts/build_mac_shortcuts.py` writes and signs the two Mac `.shortcut`
  files the same way. Its `--guess` templates are the built-in actions only (no
  a-Shell). To check the Mac actions' format against a real shortcut, build one
  on the Mac with Run Shell Script and Run AppleScript, share it by iCloud
  link, and run `build_mac_shortcuts.py --fetch <link>`, which saves
  `scripts/sample/Mac Sample.plist`; later runs copy the format from it.
- Releases are built and published by `scripts/release.py` at the repository
  root. They ship the iPhone `.shortcut` files in
  `compress-photos-shortcuts-v<version>.zip` and the Mac ones in
  `compress-photos-mac-shortcuts-v<version>.zip`; see
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
   - **Otherwise:** **Select Photos** (Select Multiple on, Include: Images
     only), then **Set Variable** `Photos` to Photos.
   - **End If**.

2. Keep the still photos:

   1. **Repeat with Each** item in `Photos` (never Filter Photos; see
      [How it works](#1-how-it-works)):
      1. **Get Details of Images**: Media Type of Repeat Item.
      2. **If** Media Type has any value:
         1. **Match Text**: `^Image$` in Media Type, Case Sensitive on.
         2. **If** Matches has any value:
            1. **Get Details of Images**: Photo Type of Repeat Item.
            2. **If** Photo Type has any value: **Match Text** `Live Photo` in
               Photo Type (Case Sensitive on); **If** Matches has any value:
               **Add to Variable** `Skipped Live Photos`: Repeat Item;
               **Otherwise:** **Add to Variable** `Stills`: Repeat Item; **End
               If**. **Otherwise:** **Add to Variable** `Stills`: Repeat Item.
               **End If**.
         3. **Otherwise:** **Add to Variable** `Skipped Videos`: Repeat Item.
            **End If**.
      3. **Otherwise:** **Add to Variable** `Stills`: Repeat Item. **End If**.
   2. For each of `Skipped Live Photos` (`Live Photo(s)`) and `Skipped Videos`
      (`video(s)`): **If** it has any value: **Count** its items, **Text**
      `<Count> <kind>`, **Add to Variable** `Skipped`. **End If**.
   3. **If** `Stills` has any value:
      - **If** `Skipped` has any value: **Combine Text** `Skipped` with Custom
        `, `, then **Show Notification**
        `Skipped <Combined Text>: only still photos are converted.` **End If**.
      - **Otherwise:** **If** `Skipped` has any value: **Combine Text** and
        **Show Notification** the same way, starting with
        `Nothing to convert. `. **Otherwise** (there were no items at all):
        **Show Notification** `Nothing to convert.` **End If**. Then **Stop
        This Shortcut**.
      - **End If**.

   From here on, use `Stills` instead of `Photos`.

3. The quality list:

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

4. a-Shell **Execute Command**:
   `rm -f jxl_done.txt jxl_out_* jxl_albums_* jxl_started`, Keep Going on.

5. **Repeat with Each** item in `Stills`:

   1. **Get Name** of Repeat Item.
   2. **Set Name**: Repeat Item to `jxl_in_<Repeat Index>.orig`, Don't Include
      File Extension on.
   3. a-Shell **Put File**: Renamed Item, Overwrite on.
   4. **Text**: `<Repeat Index>|<Name>`.
   5. **Add to Variable**: Text to `Jobs`.

6. **Combine Text**: `Jobs` with New Lines.

7. **Set Name**: Combined Text to `jxl_job.txt`, Don't Include File Extension
   on.

8. a-Shell **Put File**: Renamed Item, Overwrite on.

9. **If** Shortcut Input has any value:

   1. **Repeat with Each** item in `Stills`:
      1. **Get Details of Images**: Album of Repeat Item.
      2. **If** Album has any value: **Combine Text** Album with New Lines,
         **Set Name** to `jxl_albums_<Repeat Index>.txt` (Don't Include File
         Extension on), a-Shell **Put File** (Overwrite on). **End If**.
   2. a-Shell **Execute Command**, Keep Going off, with these commands:
      - `sleep 2`
      - `cd ~shortcuts`
      - `<Skipped Echo>` (the variable; an empty line when nothing was skipped)
      - `jxlbatch -q <Matches> -e 7 jxl_job.txt`
      - `jxlbatch --retry -q <Matches> -e 7 jxl_job.txt`
      - `<Skipped Echo>`
      - `open shortcuts://run-shortcut?name=JXL-Import`

   - **Otherwise:**
     1. The same **Execute Command**, but with `open shortcuts://` as the last
        command.
     2. **Wait to Return**.
     3. Steps 1–5 of JXL-Import, but inside the repeat, replace steps 4.8–4.9
        with:
        1. **Get Item from List**: that item of `Stills` (the original).
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

## 6. Releasing a new version

A release is built, signed and published from a Mac by `scripts/release.py` (at
the repository root), not by CI: signing the shortcuts needs macOS and an Apple
ID. The script's checks and the release notes it writes are described in
[docs/releasing.md](../../docs/releasing.md). The steps for Compress Photos:

1. **Bump the version, in a PR.** Set `VERSION` (shared by the shortcuts and
   `jxlbatch`) and add the entry at the top of
   [CHANGELOG.md](../../CHANGELOG.md), with the release date:
   `## [Compress Photos 0.3.0] - 2026-10-03`. Say which files to update (for
   example "Update the shortcuts; `jxlbatch.wasm` is unchanged"), because the
   README tells users to download only those. Past releases did this in the PR
   that made the change. Merge it to `main`.

2. **Set up the Mac** (once):

   - signed in to an Apple ID, for `shortcuts sign`;
   - the Homebrew packages from [Building](#3-building-mac), plus `wasmtime`,
     which runs each encoder's `--version` (the macOS encoder runs directly);
   - `gh` logged in with access to the repository (`gh auth status`), since
     `gh release create` publishes.

3. **Try the build on an iPhone and on the Mac (recommended).** The tests run
   the shortcuts on a model of Shortcuts, not in Shortcuts itself. From the
   repository root, `python3 scripts/release.py compress-photos --dry-run`
   builds and signs everything without creating a tag or release. For the
   iPhone, copy the files from `shortcuts/compress-photos/dist/` to the phone,
   add the two shortcuts, put `jxlbatch.wasm` in a-Shell, run
   `jxlbatch --selftest`, then convert a few photos from the share sheet and
   from the Shortcuts app. For the Mac, copy `dist/jxlbatch-macos` to
   `~/.local/bin/jxlbatch`, double-click the two Mac `.shortcut` files, then
   convert a few photos from Photos' Share menu and from the picker (HDR
   photos, a Live Photo and a video among them), and a few files and a folder
   from Finder's Quick Actions. The PR that changed the shortcuts may list what
   to look at.

4. **Update `main`.** A real run refuses to publish unless the checkout is on
   `main`, clean, and the same as `origin/main`:

   ```bash
   git checkout main
   git pull
   git status
   ```

5. **Publish.** From the repository root:

   ```bash
   python3 scripts/release.py compress-photos
   ```

   It rebuilds every shortcut (the first WebAssembly build downloads its
   dependencies into `.deps/`), checks the files and the ZIP, then prints the
   files and the release notes and asks you to confirm (`[y/N]`). Check that
   the list has `jxlbatch.wasm`, `jxlbatch-scalar.wasm`, `jxlbatch-macos`,
   `compress-photos-shortcuts-v<version>.zip` and
   `compress-photos-mac-shortcuts-v<version>.zip`, and that the notes have the
   changelog entry; answer `y` to create the tag and the release. Any other
   answer publishes nothing.

6. **Check the result.** The
   [Releases page](https://github.com/jsh9/photo-video-shortcuts/releases)
   should show `Compress Photos <version>` as Latest with those five files. The
   README's "latest" download links point at it.

A real run (not `--dry-run`) stops when the working tree isn't clean, the
branch isn't `main`, `main` differs from `origin/main`, the tag already exists,
the changelog has no dated entry for the version, or the version is the same as
in the last stable release. A published version can't be released again: fix a
bad release with a new version.
