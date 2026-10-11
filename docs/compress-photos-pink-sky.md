# Compress Photos 0.7.0: pink patches in the skies of HDR JPEG XL copies

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. The file is right](#1-the-file-is-right)
- [2. The exception: Core Image's exact path](#2-the-exception-core-images-exact-path)
- [3. The warning (`--sky-warn`)](#3-the-warning----sky-warn)

______________________________________________________________________

<!--TOC-->

What was measured on 2026-10-10 (macOS 27.0, MacBook Pro M4 Pro) about the
faint pink or lavender patches Photos shows in bright skies and clouds of HDR
JPEG XL copies, and not in the originals or the SDR copies. Reported on
`testdata/color-distortion/IMG_0316.HEIC` (iPhone 17 Pro, iOS 27, 24 MP, ISO
gain map with 4.6× headroom), then reproduced by the user on other photos with
bright skies.

## 1. The file is right

| Comparison, in the sky (linear light, chroma = (R+B)/2Y − G/Y)                      | Chroma std | Luminance  |
| ----------------------------------------------------------------------------------- | ---------- | ---------- |
| libjxl's decode of a lossless jxlbatch conversion vs Apple's HDR decode of the HEIC | 0.0038     | 1.000      |
| the user's q93 file vs the lossless one (encode + grain), libjxl                    | 0.0026     | grain only |
| Apple's Core Image HDR decode of the lossless JXL vs the file's pixels              | 0.0182     | 1.002      |
| ImageIO's direct HDR decode (`kCGImageSourceDecodeToHDR`) of the same JXL           | 0.0000     | 1.000      |
| the same pixels as a 16-bit Display P3 PQ PNG written by ImageIO, Core Image        | 0.0000     | 1.000      |

The error Core Image adds is smooth (nearly constant within 32-pixel patches,
patch std 0.0165 against pixel std 0.018), is not a function of the pixel's
value (the error at a given value varies as much as its mean) nor of luminance,
and is not 8-bit PQ rounding (simulated rounding gives patches a third as
strong and doesn't match). It is the same with Apple's HDR ICC profile removed
(cjxl, CICP P3/PQ), with XMP, maker notes or all EXIF removed, with the two
profiles of different iOS versions swapped, and for HLG instead of PQ (halved:
0.010). Apple's SDR view (`kCGImageSourceDecodeToSDR`) of the JXL carries the
same chroma error, and its HDR view is that SDR view times a per-pixel scalar
(chroma difference 0.005): Core Image makes an SDR rendition of the JXL with a
tone map that isn't chroma-preserving, then rebuilds the HDR view from it with
a luma-only gain. The HEIC isn't affected because its SDR rendition is the
camera's (chroma std 0.0038 against the HDR truth); the SDR JXL is that
rendition.

The error covers the whole picture (65-80% of 64-pixel cells with a chroma
error above 0.01 in eight of nine photos, dark smooth areas included); bright,
smooth, colored areas are where the eye sees it.

Method: `tests/compress-photos/hdr_pixels.swift` (Core Image `expandToHDR` and
`--sdr`), a scratch ImageIO-only decoder,
`djxl --color_space=RGB_D65_DCI_Rel_PeQ` for the file's pixels, numpy. `sips`
renders PQ JXLs much darker than Core Image and is useless for this.

## 2. The exception: Core Image's exact path

One of nine photos (`testdata/hdr-verif/IMG_3770.HEIC`, portrait, iOS 26.4)
rendered exactly. About forty re-encodes (cjxl and a small libjxl tool, with
Exif boxes transplanted byte for byte) pinned the rule. Core Image renders an
HDR JXL exactly when all three hold:

- the file has an Exif box (any: an empty TIFF header suffices; a container
  alone or an XML box doesn't);
- the stored image is portrait: height above width, by one pixel suffices
  (4284×4285 exact, 4285×4284 not); a codestream orientation flag doesn't
  count, the stored pixels do;
- width × height is above 2²⁴ = 16,777,216 (3916×4284 not, 3918×4284 exact).

Nothing else matters: not the Apple HDR profile, XMP, maker notes, HDRGain,
intensity target or codestream layout. So 24 MP and 48 MP portrait photos
render exactly already. A landscape 24 MP photo stored rotated by 90° with the
JXL orientation flag took the exact path and displayed upright (a transpose
displays mirrored: rotate, don't transpose). 12 MP photos (4032×3024, either
way) can't reach it. On an SDR screen both paths differ from the HEIC's SDR
rendition by about the same (chroma 0.017-0.019).

**But Photos doesn't take that path.** Viewing the files by eye (2026-10-10),
the user saw the patches in the rotated 24 MP file as in the plain one, and
fainter but present patches in the 10-bit and HLG files. The exact path is a
property of Core Image's `expandToHDR` in a standalone process, as the test
helper calls it, not of what Photos shows. Nothing to implement; the warning
stands. The way out is another format: 0.7.0's HEIC route keeps the camera's
gain map byte for byte and re-encodes only the base picture's HEVC tiles, so
Photos shows the copy through the camera's own path, with no patches
(`testdata/heic-quality-2`, verified by eye on 2026-10-11).

## 3. The warning (`--sky-warn`)

`grain_bright_sky` (`grain.c`): for each 16-pixel cell row, one row of the HDR
rendition is rendered (before the grain), and a cell counts when it isn't
textured (the grain's smoothness weight above 0), its mean is brighter than SDR
white, and its brightest channel is over 1.2 times its darkest. The share of
such cells, against Apple's measured error (Core Image vs the file, mean
|chroma error| per 16-pixel cell), on nine iPhone HDR photos:

| Photo (all 24 MP but 0198, 0200: 12 MP) | Bright sky | Cells with error > 0.01 | Noticed |
| --------------------------------------- | ---------- | ----------------------- | ------- |
| IMG_0316 (the report)                   | 39%        | 80%                     | yes     |
| IMG_0197                                | 17%        | 72%                     |         |
| IMG_0198                                | 10%        | 73%                     |         |
| IMG_0196                                | 3%         | 76%                     |         |
| IMG_0194, IMG_0195                      | 2%         | 78%, 81%                |         |
| IMG_3770 (exact path), 0199, 0200       | 0-1%       | 0%, 65%, 68%            |         |

The default, 5%, warns for the first three. `--sky-warn 0` turns it off; the
warning isn't printed for `--sdr` or an SDR photo.
