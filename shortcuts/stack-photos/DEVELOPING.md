# Stack Photos: developer notes

How the shortcut works, how it was checked without a device, and how to build
it. For installing and using it, see [README.md](README.md). The decisions and
the evidence behind them are in
[docs/stack-photos-design.md](../../docs/stack-photos-design.md).

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. How it works](#1-how-it-works)
  - [1.1. The image steps](#11-the-image-steps)
  - [1.2. The date](#12-the-date)
  - [1.3. On the Mac: Photos' selection](#13-on-the-mac-photos-selection)
- [2. Layout](#2-layout)
- [3. Building](#3-building)
- [4. Releasing a new version](#4-releasing-a-new-version)

______________________________________________________________________

<!--TOC-->

## 1. How it works

```
Stack Photos                                 (shortcut, iPhone and Mac)
   photos: the shortcut's input (share sheet; Finder Quick Action or Services
   on the Mac); with none, on a Mac (Get Device Details: Device Model "Mac")
   whose Photos is in front with a selection, that selection (1.3); else its
   photo picker (images only)
   keeps the images: an item whose Media Type is Video or Audio goes into
   Skipped; none left: "Nothing to stack" and stop
   three menus: direction, aspect ratio (A:B, or Keep), and Pad or Crop
   (asked only for a ratio); they set Horizontal, A, B, Ratio, Keep, Crop
   (each only when it applies, so an If "has any value" reads them)
   tile size, from Get Details of Images (Width, Height, read in memory):
     Keep: TH = the smallest height, TW = the smallest width
     ratio: K = rounded down, the smallest over the photos of
            min(w/A, h/B) (Crop) or max(w/A, h/B) (Pad); TW = K·A, TH = K·B
   Pad only: the canvas, a 1x1 white PNG (Base64 Decode) resized to TW × TH
   each photo: Convert Image to PNG, then
     Keep: Resize Image to TH high (horizontal) or TW wide (vertical)
     Crop: resize by the larger of TW/w and TH/h, Crop Image the middle
           TW × TH from ((w'-TW)/2, (h'-TH)/2), rounded down
     Pad:  resize by the smaller, Overlay Image on the canvas at
           ((TW-w')/2, (TH-h')/2), rounded down
   Combine Images (Horizontally or Vertically, no spacing) → a PNG
   Convert Image to JPEG, quality 0.9
   the date (the Mac route's ISO, if it has one; else): each photo's Date
   Taken; the latest = the first + the largest Get Time Between Dates
   (seconds) from the first; + 5 s (Adjust Date); none: Current Date. Format
   Date, ISO 8601 with the time
   the EXIF segment with that date written into the JPEG (1.2)
   Set Name "<first photo's name>-stack.jpg", Save to Photo Album (Recents)
   the Mac route's copies removed from iCloud Drive
   a notification: how many photos, the stack's size, what was skipped
```

Only built-in actions, and no a-Shell. Run AppleScript and Run Shell Script
(the Mac route, 1.3) run only on a Mac: an If on Get Device Details' Device
Model ("Mac" on the Mac in every language checked; "iPhone" on an iPhone) comes
first. iOS has no such actions, and an action it doesn't have fails only when
it runs (WorkflowKit's `WFMissingAction`); the iPhone's editor shows them as
Unknown Action.

### 1.1. The image steps

What each action does, from its decompiled code (ActionKit and ContentKit, iOS
18.2) and, where possible, its helpers run on the Mac:

- **Get Details of Images** gives a library photo's `pixelWidth` and
  `pixelHeight` (the current, edited version, upright) and a file's size from
  its metadata, swapped for orientations 5 to 8 (`WFImageSizeFromMetadata`,
  called on the Mac with each orientation).
- **Resize, Crop and Overlay Image** draw through one routine
  (`WFAsyncTransformedImageFromImage`) that applies the orientation and keeps
  the input's file type: a HEIC stays a HEIC, re-encoded. Run on the Mac, a
  JPEG with orientation 6 came out upright at the size asked for. So each photo
  is converted to PNG first (Convert Image keeps the orientation tag), and
  every step after that is lossless.
- **Crop Image** clamps to the image (`CGImageCreateWithImageInRect`), so it
  can't pad; **Overlay Image** draws the overlay at the given place and size on
  a copy of the base, which has the base's size. The canvas is a 1x1 white PNG
  stretched to the tile: Core Graphics keeps it white to the edges at every
  interpolation quality (checked).
- **Combine Images** makes an RGBA device-RGB bitmap as wide as the sum of the
  widths (horizontal) and as high as the tallest, draws each image from the top
  left, and writes PNG when most inputs are PNG, else JPEG at ImageIO's default
  quality (0.75). With PNG tiles of one height (width), it is a lossless,
  seamless stack. Device RGB is sRGB, 8 bits: HDR gain maps and Display P3 are
  lost here.
- **Offsets and sizes** are whole numbers (Round Number), so nothing is drawn
  between pixels. Number fields get their variables as attachments: Shortcuts
  turns a number into text in the device's digits (Arabic-Indic digits in an
  Arabic region, for example), which a size field would read as 0.

### 1.2. The date

Save to Photo Album creates the asset from the file
(`creationRequestForAssetFromImageAtFileURL`, no `creationDate`), and Photos'
App Intents can't set a date either, so the date must be in the JPEG's EXIF. No
action writes EXIF, but three can rewrite a JPEG's bytes as text: Base64
Encode, Replace Text and Base64 Decode.

Base64 turns every 3 bytes into 4 characters, so text can stand for bytes only
from a multiple of 3. `exif_segment` in `scripts/build_shortcuts.py` lays out
an APP1 segment (big-endian TIFF) whose values all start at such a multiple:

| Tags                                                     | Value                      | Bytes |
| -------------------------------------------------------- | -------------------------- | ----- |
| DateTime, DateTimeOriginal, DateTimeDigitized (one each) | `2026:05:02 07:16:04`, NUL | 20    |
| OffsetTime, OffsetTimeOriginal, OffsetTimeDigitized      | `+09:00`, NUL              | 7     |
| ExifVersion `0232` (offsets are EXIF 2.31), ColorSpace 1 | in their entries           |       |

A date is 19 bytes: its base64 without `==` (26 characters) covers it, and the
group it ends in also holds the NUL and the next byte, which are constant, so
the next constant text goes on with that group's last two characters. An offset
is 6 bytes, 8 characters. `prefix_pieces` gives the constant texts between
them; the shortcut puts Base64 Encode of the date (with `=` removed) and of the
offset in between, in one Replace Text's replacement.

Convert Image's JPEG starts with SOI, a JFIF segment (72 dpi) and ImageIO's own
small Exif segment (ColorSpace and the pixel size): seen on macOS 27
(`test_imageio.py` checks it at stack sizes); iOS shares ImageIO, and the
fallback below covers a JPEG that starts otherwise. The shortcut replaces the
first 21 bytes (SOI, JFIF, and the FF of the next marker) with SOI, JFIF, its
segment and FF, and turns that next marker's E1 into EF (APP15, which no reader
takes for EXIF): `MAIN_PATTERN` and the `7w` after the prefix. A JPEG that
starts otherwise gets the segment right after SOI (`FALLBACK_PATTERN`). The
date comes from Format Date's ISO 8601 text (`2026-05-02T07:16:04+09:00`, `Z`
for UTC; en_US_POSIX in the device's time zone) through two Replace Texts; if
that text isn't the expected shape, the JPEG is saved without a date rather
than with broken bytes, and the notification says so.

The latest date: Get Time Between Dates from the first photo's date to each in
seconds, the largest, plus 5, added to the first date. The first date's own
precision cancels out.

### 1.3. On the Mac: Photos' selection

On the Mac, Photos' Share menu hands a shortcut its photos as files in a folder
the Shortcuts extension may not read, so Shortcut Input is empty (Compress
Photos' spike S5; seen again on macOS 27 in the unified log: the run request
has input, 4 items, and the If finds none). No input class changes that. So,
with no input on a Mac:

```
Run AppleScript lib/mac/probe.applescript: Photos in front with a selection?
   "SELECTION n" → the route below; "ERROR: ..." → a notification, stop;
   "NONE" → the photo picker
Run Shell Script: an empty ~/Pictures/.stack-photos-macos (Photos' sandbox
   reaches ~/Pictures), its path printed without a newline
Run AppleScript scripts/mac/export.applescript (input: that path): Photos
   exports each selected item, as it shows it (no "using originals": edits
   applied, a JPEG for a photo), into in/<n>, one folder per item in the
   selection's order; returns "n|date" lines, the date on the Mac's clock
   ("ERROR: ..." → a notification, stop)
Run Shell Script scripts/mac/stage.zsh (the lines in a heredoc): copies each
   item's picture to Shortcuts' iCloud Drive folder, stack-photos-macos/n/
   <name> (Get File reads only there on the Mac, and Photos can't write
   there), writes list.txt, skipped.txt (items with no picture: videos) and
   date.txt (the latest date + 5 s, as ISO 8601 with the Mac's offset on that
   date, by `date -j`), and removes the ~/Pictures folder
Get File each list.txt path (in order) → Photos; skipped.txt → Skipped;
   date.txt → ISO, which the date step then uses instead of Get Details'
```

Photos' AppleScript dates are clock times in the Mac's time zone; `date -j -f`
reads them with that zone's rules for the date, so a summer photo gets summer
time's offset. A clock time in the repeated hour at the end of daylight saving
time is read as the first of the two, and one the clocks skip as an hour later.
The work folder is emptied at the start of each run, and the iCloud Drive
copies are removed after saving (and before "Nothing to stack"). Both scripts
need Shortcuts ▸ Settings ▸ Advanced ▸ Allow Running Scripts, and Photos asks
once whether Shortcuts may control it.

## 2. Layout

| Path                                | What it is                                                                                   |
| ----------------------------------- | -------------------------------------------------------------------------------------------- |
| `VERSION`, `release.json`           | the version; the release's one shortcut (listed under `iphone`; it is the Mac's too)         |
| `scripts/build_shortcuts.py`        | the generator: the questions, the steps, the EXIF segment and its base64 pieces              |
| `scripts/mac/`                      | the Mac route's export AppleScript and staging zsh script (and `lib/mac/probe.applescript`)  |
| `../../lib/wfkit.py`                | the shared builder, with the image, number and date actions                                  |
| `../../tests/stack-photos/`         | the tests: the shortcut run on a model of Shortcuts, its actions, and ImageIO reading a date |
| `../../docs/stack-photos-design.md` | decisions and evidence                                                                       |

## 3. Building

```bash
python3 shortcuts/stack-photos/scripts/build_shortcuts.py             # signed
python3 shortcuts/stack-photos/scripts/build_shortcuts.py --no-sign   # plists only
```

It writes `build/shortcuts/Stack Photos.unsigned.wflow` (and a readable
`.plist`) and, signed with `shortcuts sign` (macOS, an Apple ID),
`dist/Stack Photos.shortcut`. There is no encoder and no sample shortcut.

The tests (`python3 -m pytest tests/stack-photos`) run the shortcut on a model
of Shortcuts (`shortcut_model.py`) for every direction, ratio and fit, and as a
Mac with the real zsh scripts and a stand-in for Photos' answers; on the Mac
they compile the AppleScripts against Photos' dictionary and `imageio.swift` to
write a JPEG as Combine and Convert Image do and to read the spliced date back
with ImageIO (and exiftool). See [tests/README.md](../../tests/README.md).

## 4. Releasing a new version

Bump `VERSION`, add a `Stack Photos` entry to
[CHANGELOG.md](../../CHANGELOG.md), merge, then on `main`:

```bash
python3 scripts/release.py stack-photos
```

See [docs/releasing.md](../../docs/releasing.md).
