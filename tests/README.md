# Tests

The tests run on a Mac: they check results with Apple's ImageIO, the framework
Photos uses. CI runs them on every push.

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. Running them](#1-running-them)
- [2. What they cover](#2-what-they-cover)
- [3. Your own photos](#3-your-own-photos)

______________________________________________________________________

<!--TOC-->

## 1. Running them

From the repository root, with [tox](https://tox.wiki):

```bash
tox                              # build everything, then run all tests
tox -e tests                        # run the tests only (uses the existing builds)
tox -e tests -- -k orientation      # pass options to pytest
```

Or without tox, after building:

```bash
python3 -m pip install -r tests/requirements.txt
python3 -m pytest
```

They need:

- the builds: `shortcuts/compress-photos/scripts/build-wasm.sh` (and
  `build-native.sh` for the native build's tests);
- Homebrew `wasmtime exiftool jpeg-xl` (`djxl`, `jxlinfo`), plus `sips`,
  `swiftc` and `dash`, which come with macOS and Xcode.
- Only to regenerate the HDR test photos (`make_hdr_fixtures.py`): ffmpeg with
  libx265 and libheif's `heif-dec` (Homebrew `ffmpeg libheif`).

A test whose build or tool is missing is skipped on your Mac and fails in CI.

## 2. What they cover

`compress-photos/`:

| File                      | What it checks                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `test_shortcuts.py`       | the generated shortcuts: blocks and variables, a-Shell actions, quality presets, version in the notes, cleanup, originals marked "keep" not offered for deletion (and no delete prompt when all are)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| `test_photo_selection.py` | which items Compress Photos converts, run on a model of Shortcuts' Filter Photos: only still photos from the photo library (screenshots, HDR, panoramas, bursts), the items themselves and in order; Live Photos (HDR ones too), videos and items not from Photos skipped with a count of each kind; a stop before the quality list when nothing is left; the Filter Photos format; the picker showing images only                                                                                                                                                                                                                                                                                                                                                                     |
| `test_encoder_cli.py`     | `jxlbatch` (SIMD and scalar WebAssembly, native): version, self-test (HDR included), arguments, `--sdr`, batches with failed photos, the `jxl_done.txt` format                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `test_conversion.py`      | end to end: photos written like an iPhone's (HEIC and JPEG, rotated, Display P3, 10-bit, HDR, PNG with transparency) keep their EXIF, XMP and what Photos reads, and look the same                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `test_hdr.py`             | HDR photos with an ISO 21496-1 gain map, as iPhones write since iOS 18 (upright, turned 90° and 180°, mirrored, square; ImageIO writes them, and Apple's label is added by `photo_helpers.with_apple_gain_map_label`, so the real iPhone layout is covered only by `test_samples.py`), become 16-bit PQ JPEG XL that matches Apple's own HDR rendering, upright and in every build, with their peak brightness, at most 25% larger than with `--sdr`, and looking like the original on SDR screens; `--sdr` keeps the original; photos without a gain map stay SDR                                                                                                                                                                                                                     |
| `test_hdr_profile.py`     | Apple's HDR color profile (with its tone curve) in an HDR photo's HEIC, on the `tmap` item or else the gain map, is kept byte for byte in the JPEG XL, with unchanged pixels, in every build, also when shaped like iOS 26's (`photo_helpers.apple_shaped_hdr_profile`; skcms, libjxl's color engine in WebAssembly, can't read all of its tags); profiles that don't describe the pixels are ignored, and a missing or ignored profile is noted                                                                                                                                                                                                                                                                                                                                       |
| `test_hdr_fixtures.py`    | the committed HDR test photos (`fixtures/hdr/`, written by `make_hdr_fixtures.py`): every orientation, crops (also past the photo's edges), grids, 10-bit, RGB, multichannel and limited-range gain maps, a peak above PQ's 10,000 nits, at most 16 stops, Apple's older gain maps (iOS 14 to 17), and photos edited in Photos (an unlabeled gain map with a crop of its own, applied in the HDR image's color space) match the independent NumPy math in `hdr_reference.py` to 1/65535; each gain map that can't be used says why and keeps its original, except an unlabeled one on a turned or cropped photo (converted as SDR, original deletable). Apple can't decode the synthetic older-format photos, so Apple's rendering of that format is checked only by `test_samples.py` |
| `test_heif_layouts.py`    | SDR photos in HEIF layouts beyond an iPhone's (`fixtures/heif/`): a rotation or mirror before the crop, a crop past the photo's edges, derived `iden` photos of a turned source, transparency with transforms of its own; exact and upright in every build. A crop that leaves nothing fails the photo                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `test_xmp.py`             | ordinary and extended JPEG XMP across all three builds: long descriptions, reordered fragments, namespaces, arrays, structures, duplicate/conflicting properties, invalid packets and orientation                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `test_orientation.py`     | all 8 EXIF orientations become upright pixels, exactly; the orientation check warns only when the original's EXIF size is its own (not an edited photo's)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `test_memory.py`          | a 24 MP photo at low quality, and 24 MP and 48 MP HDR photos, stay well under the memory iOS allows a-Shell; HDR takes at most 15% more than SDR                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `test_shortcut_flow.py`   | the shortcut's a-Shell commands run as a-Shell runs them (modeled on its source), with a-Shell already open or launched by the shortcut, and the retry when its engine is still starting; then JXL-Import's reading of the results and the cleanup                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `test_samples.py`         | your own photos, if any (see below)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |

`scripts/`: release manifests, missing/empty/stale outputs, signed and unsigned
ZIP contents and CRCs, encoder versions, mocked GitHub baselines, per-tool
version comparisons and changelog checks.

## 3. Your own photos

Put your own test photos in `tests/samples/compress-photos/` (any subfolders).
`test_samples.py` runs the end-to-end checks on each of them, including the
primary photo's namespace-qualified XMP properties with structured values. A
photo with an ISO 21496-1 gain map (iOS 18 and later) or Apple's older gain map
(iOS 14 to 17) must become HDR, match Apple's HDR rendering, keep Apple's HDR
profile if it has one (and then look like the original on SDR screens), and be
at most 25% larger than with `--sdr`. HEIF auxiliary images (depth,
segmentation and gain maps) have their own metadata; those packets are not
mixed into the primary photo's properties. Only orientation normalization and
removal of `HasExtendedXMP` are allowed; without any samples, it is skipped.
That folder is not committed: personal photos often contain GPS locations.
