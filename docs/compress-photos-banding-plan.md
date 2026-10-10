# Compress Photos 0.6.0: HDR banding, HDR on/off, originals collected in an album

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. Findings (measured, 2026-10-05/06)](#1-findings-measured-2026-10-0506)
  - [1.1. Self-check metric](#11-self-check-metric)
- [2. Decisions (2026-10-06)](#2-decisions-2026-10-06)
- [3. Packages](#3-packages)
  - [3.1. A. Banding detector (PR 2)](#31-a-banding-detector-pr-2)
  - [3.2. B. Pixel grain in `jxlbatch` (PR 2)](#32-b-pixel-grain-in-jxlbatch-pr-2)
  - [3.3. C. Tuning (PR 2, with the user)](#33-c-tuning-pr-2-with-the-user)
  - [3.4. D. Mac shortcuts: HDR on/off (PR 1)](#34-d-mac-shortcuts-hdr-onoff-pr-1)
  - [3.5. E. iPhone shortcut: album instead of deletion (PR 1)](#35-e-iphone-shortcut-album-instead-of-deletion-pr-1)
  - [3.6. F. Docs, release, verification](#36-f-docs-release-verification)
- [4. Tuning results (2026-10-06, PR 2)](#4-tuning-results-2026-10-06-pr-2)
- [5. Out of scope](#5-out-of-scope)

______________________________________________________________________

<!--TOC-->

Plan and findings, written 2026-10-06. Two pull requests:

1. **PR 1**: packages D and E (Mac HDR on/off; iPhone collects originals in an
   album instead of deleting them).
2. **PR 2**: packages A, B and C (banding detector, pixel grain, tuning).

## 1. Findings (measured, 2026-10-05/06)

Test photo: a sunset skyline, `IMG_1976.HEIC` (iPhone 17 Pro, 24 MP, HDR 6.8×),
converted with `jxlbatch` at q88 on the Mac and on the iPhone.

- **The files are not the problem.** The Mac and iPhone outputs decode to the
  same sky (98% of pixels identical, the rest within 17 of 65,535). Photos
  showed the iPhone one smooth only because of a stored preview that iOS had
  made; after a rotation (a fresh render) both banded identically.
- **Cause 1, Apple's SDR rendering of a PQ JXL goes through an 8-bit PQ step.**
  Verified on this Mac (ImageIO `kCGImageSourceDecodeToSDR`): the SDR output is
  a function of the 8-bit PQ value (0.34 levels of variation inside one 8-bit
  PQ bucket), with 2.08 SDR steps per PQ step in the sky. So the sky gets half
  the levels, and the steps are twice as tall. A lossless PQ JXL bands the same
  way. Apple's own HEIC doesn't: its SDR picture is shown directly.
- **Cause 2, compression removes the grain that would dither those steps**:
  about 30% of it at q88, more at lower qualities.
- **Where it shows:** large smooth gradients (skies, especially at sunset; fog;
  bokeh; walls; water; skin) in bright, low-ISO photos, in HDR outputs only.
  Textured scenes hide it; night shots carry their own grain.
- **Decoder grain (libjxl photon noise) doesn't help on the phone:** Apple's
  reduced-size decodes shrink before the 8-bit step, and per-pixel noise
  averages away (ImageIO thumbnail at 1206 px: grain 0.09 with and without).
  Grain stored in the pixels survives (0.18), which matched the user's
  preference in Photos.
- **HLG** removes the missing-levels half (its 8-bit step is finer than an SDR
  step there) but not the compression half, and would be a large rework.
- **SDR outputs** (`--sdr`, the iPhone's "Automatic") don't band and render
  correctly in viewers without tone mapping (XnView MP, Easy Loupe); PQ outputs
  look dark or flat there (viewer issue, see jsh9/easy-loupe#55).

### 1.1. Self-check metric

Simulate Apple's rendering: shrink to the viewing scale, round PQ to 8 bits. In
smooth blocks (classified on the original), the share of pixels whose right and
lower neighbours are equal (lower is better). Reference: the original's SDR
picture. `IMG_1976`:

| Variant                                      | Size   | 5712 px | 3808 px (Mac 4K fit) | 1206 px (iPhone fit) |
| -------------------------------------------- | ------ | ------- | -------------------- | -------------------- |
| Original HEIC (reference)                    | 3.3 MB | 0.34    | 0.30                 | 0.48                 |
| Lossless PQ (quantization only)              | —      | 0.69    | 0.65                 | 0.78                 |
| q88                                          | 2.6 MB | 0.79    | 0.75                 | 0.81                 |
| q83                                          | 1.9 MB | 0.85    | 0.81                 | 0.83                 |
| q72                                          | 1.2 MB | 0.93    | 0.90                 | 0.87                 |
| q88 + decoder grain ISO 50                   | 2.4 MB | 0.47    | 0.57                 | 0.80                 |
| q88 + white grain in pixels, σ = 1 PQ-8 step | 2.9 MB | 0.48    | 0.44                 | 0.67                 |

The user judged the last row acceptable in Photos ("less bandy, preferred"),
the decoder-grain row "less bandy but still bandy", q88 "wide-ish banding".
**Pass criterion: plateau ≤ reference + 0.15 on ≥ 80% of smooth blocks at 3808
px and at 1206 px.**

## 2. Decisions (2026-10-06)

- **D1** File-size budget for grain: up to **+15% at q83** on a sunset-type
  photo (the smooth-region mask keeps it lower on other photos).
- **D2** **Every successfully converted still goes into the album *Compressed
  to JXL***, on both platforms, whether or not its HDR made it into the JXL and
  whether or not SDR was chosen. The `keep`/`delete` field in `jxl_done.txt`
  stays as information for the log; it no longer gates collection.
- **D3** HDR on/off is a Mac-shortcut question only (the iPhone share sheet
  already offers "Automatic"; the picker route can get it later).
- **D4** iPhone share-sheet route: originals are collected *before* the
  conversion (that route hands off to a-Shell and ends), so a photo whose
  conversion fails lands in the album too; the a-Shell log names it. Spike S1
  (2026-10-06) confirmed that Save to Photo Album from the share sheet adds a
  library photo to an album without a copy, that photos already in the album
  can be detected with Get Details of Images ▸ Album, and that the one-time
  permission prompt works from the share sheet.

## 3. Packages

### 3.1. A. Banding detector (PR 2)

Python under `tests/compress-photos/` (`banding.py`): `simulate(pq16, width)`,
`smooth_mask(original)`, `score(output, reference, width)`; fixtures: a
synthetic low-noise PQ gradient (always runs) and the user's own photos via
`test_samples.py` (skipped when absent). Must fail on the 0.5.0 encoder.

### 3.2. B. Pixel grain in `jxlbatch` (PR 2)

In the HDR path, PQ outputs only, lossy only: a pre-pass on the decoded 8-bit
SDR base gives a smoothness weight per 16×16 cell (feathered) and the cell's
own grain; a luma-only noise field at ¼ resolution from a fixed-seed integer
PRNG, upsampled bilinearly in integer math, is added as each region is
converted (`pq += round(amp × weight × noise)`), amplitude near 0.5 of an 8-bit
PQ step at q88, scaled up for lower qualities; skipped where the photo's own
grain suffices. `--grain N` (0 = off, default auto). SDR, `--sdr` and lossless
outputs stay byte-identical; native and WebAssembly builds stay identical to
each other.

### 3.3. C. Tuning (PR 2, with the user)

Encode the test photos (`testdata/banding/IMG_1976.HEIC`,
`hdr-verif/IMG_3770.HEIC`, `IMG_7223.heic`, `hdr-iphone-13/2021-10-31.heic`,
`dark.heic`) at q88/q83/q72 × three amplitudes, screen with the detector,
shortlist 2–3, judge in Photos on the Mac (import, ⌘R, fit, zoom) and on the
iPhone, fix the amplitude curve within D1.

### 3.4. D. Mac shortcuts: HDR on/off (PR 1)

A third question after *Cores to use*: **Keep HDR** / **Drop HDR**; it reaches
`run.zsh` as `--sdr`. Per D2 the selection route collects every imported photo,
so `import.applescript` no longer reads the `keep`/`delete` field for that.

### 3.5. E. iPhone shortcut: album instead of deletion (PR 1)

Picker route: replace Delete Photos with Save to Photo Album → *Compressed to
JXL* for each converted original not already in that album. Share-sheet route:
the same, for every staged still, before the hand-off to a-Shell. No photo is
deleted by the shortcut any more.

### 3.6. F. Docs, release, verification

READMEs, DEVELOPING.md 1.3, CHANGELOG, VERSION 0.6.0, `releasing.md`; on both
devices: convert `IMG_1976` on each, view on both (fit, ⌘R, zoom), HDR on and
off. Already-converted photos keep their banding.

## 4. Tuning results (2026-10-06, PR 2)

`IMG_1976` at q83 (no grain: 1.93 MB, Mac-fit plateau 0.81, phone-fit 0.83;
reference 0.30 / 0.48). `fine` is per-pixel noise, `coarse` is drawn 4 px
apart; amounts in percent of an 8-bit PQ step.

| fine + coarse | size | Mac fit | phone fit |
| ------------- | ---- | ------- | --------- |
| 60 + 40       | +12% | 0.55    | 0.61      |
| 70 + 40       | +13% | 0.50    | 0.59      |
| 80 + 50       | +17% | 0.43    | 0.52      |
| 80 + 70       | +19% | 0.39    | 0.42      |
| 100 + 50      | +20% | 0.33    | 0.48      |
| 100 + 60      | +21% | 0.31    | 0.44      |

Single-layer grain can't do both scales cheaply: fine grain alone (size 1)
fixes the Mac scale, coarse alone (size 4) the phone scale, and size 2 passes
both only at +32%. The auto curve, `fine = 80 + (83 - q) × 2.7`,
`coarse = fine × 5/8` (q88: 67+41, q83: 80+50, q72: 110+68), costs about
+15-20% at each quality; the encode takes 4% longer. **Verdict (2026-10-06):**
on a 16" MacBook Pro at fit-to-screen, the candidates A (80+50), B (60+40) and
C (100+60) all showed the same slight banding near the horizon, far less than
no grain, so the user chose the least grainy: B. Default curve:
`fine = 60 + (83 - q) × 2`, `coarse = fine × 2/3` (q88: 50+33, q83: 60+40, q72:
82+54), about +10-15%. The test's rule is the share of the gap between the
no-grain output and the reference that the grained output closes: 40% at the
Mac scale, 80% at the phone scale, which is what this default does on the sky
fixture (0.63 of 0.92 → 0.32; 0.59 of 0.81 → 0.58).

**Update (2026-10-10, with the 93 preset):** above q83 the line stays at 60+40
(`fine = max(60, 60 + (83 - q) × 2)`). Its lower amounts failed the phone-scale
rule on the sky fixture: q93 at 40+26 closed 58% of the gap and q88 at 50+33
76%, since a higher quality keeps hardly more of the sky's faint grain (q93
without grain: 0.80 of 0.81 at the phone scale). At q93, 50+33 closes 81% and
60+40 103% (87% at the Mac scale). The banding test now runs at every preset.

## 5. Out of scope

- Mac and WebAssembly encoders differ by a few bytes on `IMG_1976` although
  DEVELOPING.md claims byte-for-byte equality (likely SIMD rounding; the small
  test images don't trigger it). Own follow-up.
- Easy Loupe HDR rendering: jsh9/easy-loupe#55.
- The faint green bar in one thumbnail: a stored-preview artifact.
