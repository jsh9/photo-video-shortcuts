# Compress Photos 0.7.0: the JPEG XL copy takes the photo's date from Photos

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. The problem](#1-the-problem)
- [2. Decisions](#2-decisions)
- [3. Design](#3-design)
- [4. Spikes](#4-spikes)
- [5. Verification](#5-verification)

______________________________________________________________________

<!--TOC-->

Plan and findings, written 2026-10-08/09. How it works now is in
[DEVELOPING.md, Dates](../shortcuts/compress-photos/DEVELOPING.md#14-dates).

## 1. The problem

Up to 0.6.0, `jxlbatch` copied the original's EXIF unchanged, and Photos dated
the copy from that EXIF:

- **A date changed in Photos** (a photo captured 10/1/2026 12:00 PM, changed to
  1/1/2024 5:00 PM): the change lives only in Photos' library. The export of
  the original has the camera's date, so the copy came back as 10/1/2026, and
  deleting the original lost the change.
- **No capture date in the file** (an image saved from an app that removed
  `DateTimeOriginal` and `CreateDate`, such as the user's `IMG_0294.HEIC`, an
  iPhone 16 Pro photo; a screenshot): Photos dated the copy from the file's own
  date, the time of the conversion (10:29:39 PM instead of 8:32:10 PM).
  EasyLoupe, which reads `DateTimeOriginal`/`CreateDate`, showed no "Captured".

Goal: the copy's capture date is the date Photos shows for the original, in the
file's EXIF and in Photos, on the Mac and the iPhone.

## 2. Decisions

- The shortcut reads each photo's date in Photos and gives it to `jxlbatch`,
  which writes it into the EXIF only when the file's `DateTimeOriginal` is
  another moment or missing (to the second); otherwise the EXIF stays byte for
  byte. The date travels with the file, so EasyLoupe and a later re-import see
  it.
- The dates go in a separate file, `jxl_dates.txt` (`i|<ISO 8601>`), not in the
  job line: an older `jxlbatch` ignores it, a newer one without it behaves as
  before, and a photo name with `|` stays unambiguous.
- A written date is in the device's time zone (with its offset on that date):
  neither Shortcuts nor Photos' AppleScript gives a photo's time zone. Using
  the file's old offset instead would be wrong across daylight saving time (a
  summer photo moved to January).
- The Mac's selection route also checks each imported copy's date in Photos
  against its original's and sets it if they differ (a safety net; two calls
  per copy).
- *Compress Photo Files (macOS)* is unchanged: Finder files have no Photos
  date.

## 3. Design

- **`jxlbatch`** (`meta.c`: `photo_date_parse`, `exif_set_capture_date`;
  `xmp.cpp`: `xmp_set_dates`; `jxlbatch.c`: `read_dates`, `process_job`): the
  Exif IFD is rewritten at the end of the EXIF and IFD0's pointer moved to it,
  so no other value moves (maker notes keep working); IFD0 is rewritten too
  only when it has no Exif IFD; a file without EXIF gets a minimal one. XMP
  capture dates the file already has get the date too; none is added.
- **iPhone, Mac picker route** (`wf.photo_date`, `wfkit.Builder.format_date`):
  Get Details of Images ▸ Date Taken (the asset's `creationDate`), guarded by
  Match Text, then Format Date as ISO 8601 with the time (en_US_POSIX, the
  device's time zone), appended to `Dates` as `index|date`.
- **Mac selection route**: `export.applescript` returns `id|date|filename`
  (Photos' `date of`, on the Mac's clock); `selection.zsh` adds the offset with
  `date -j` and writes `jxl_dates.txt`; `import.applescript` checks the copies'
  dates.

## 4. Spikes

1. **Photos' AppleScript date (done, 2026-10-08, macOS 26):** `date of` gives
   the date on the Mac's clock: `IMG_0294.HEIC` read 8:32:10 PM, as Photos
   shows it, and a December photo (EXIF `19:01:44 -05:00`) read 7:01:44 PM in
   October (daylight saving time). `date -j` adds `-0500` and `-0400`
   correctly. Photos' export also sets the exported file's creation time to the
   photo's date.
2. **Format Date's text (on the device):** the decompiled
   `NSDate(WFFormatting)` (iOS 18.2) formats ISO 8601 with
   `yyyy-MM-dd'T'HH:mm:ssZZZZZ` in en_US_POSIX and the formatter's default time
   zone; to confirm with the first run on each device (the log's
   `date from Photos` lines).
3. **Photos reads the written date (on the device):** ImageIO reads it
   (`test_dates.py`); to confirm in Photos with the first runs below.
4. **Which tags Photos' own JPEG export rewrites for a changed date
   (optional):** `jxlbatch` changes `DateTimeOriginal`, `CreateDate`, their
   offsets and sub-seconds, and IFD0's `ModifyDate` if present.

## 5. Verification

- `tests/compress-photos/test_dates.py` on every build (no date, another date,
  the same moment, no offset in the file, no EXIF at all, IFD0 without an Exif
  IFD, Apple's maker note, XMP dates, a date not understood, dates by index,
  ImageIO), plus the shortcuts' structure, the Mac scripts and the a-Shell flow
  with dates, and the macOS and WebAssembly builds writing the same bytes with
  dates.
- On the Mac: the selection route on `IMG_0294` (copy dated 10/8/2026 8:32:10
  PM in Photos, EasyLoupe shows Captured); a duplicate with its date changed to
  1/1/2024 5:00 PM (copy shows 1/1/2024 5:00 PM); the picker route on the same
  two.
- On the iPhone: the same two photos from the picker and from the share sheet.
