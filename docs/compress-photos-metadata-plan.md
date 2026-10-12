# Compress Photos 0.8.0: the copy takes its location, title, caption, keywords and favorite from Photos

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. The problem](#1-the-problem)
- [2. Decisions](#2-decisions)
- [3. Design](#3-design)
  - [3.1. `jxl_meta.txt`](#31-jxl_metatxt)
  - [3.2. `photobatch`](#32-photobatch)
  - [3.3. Mac selection route](#33-mac-selection-route)
  - [3.4. iPhone and Mac picker route (Shortcuts)](#34-iphone-and-mac-picker-route-shortcuts)
- [4. Spikes](#4-spikes)
- [5. Steps](#5-steps)
- [6. Verification](#6-verification)

______________________________________________________________________

<!--TOC-->

Plan for issue #21, written 2026-10-12. It extends 0.7.0's dates
([compress-photos-dates-plan.md](compress-photos-dates-plan.md)) to the rest of
what Photos keeps for a photo in its library only.

## 1. The problem

`photobatch` copies the original's EXIF and XMP as they are. Photos keeps some
of what it shows for a photo in its library, not in the file, so the copy can
differ from the original or lack it, and deleting the original after review
loses it:

- **Location changed or added in Photos:** the copy gets the camera's GPS, or
  none.
- **Location hidden in Photos** (Image > Location > Hide Location, macOS 26;
  undone with Revert to Original Location): the file still has the camera's
  GPS, and the copy brings it back, which is a privacy problem.
- **Title, caption, keywords** set in Photos: the copy has none of them. A
  file's own (from a camera or another app) comes back on the copy, even if
  Photos changed or cleared it.
- **Favorite:** the copy isn't one.

Goal: as with the date, the copy's file says what Photos shows for the
original, so the copy shows it in Photos and in any other app, and a later
export or re-import keeps it.

What each route can read (Photos' `Photos.sdef` on macOS 26; Shortcuts'
ContentKit decompiled from iOS 18.2):

| Field    | Mac selection route (AppleScript) | iPhone, Mac picker route (Shortcuts)         | Where it goes in the file      |
| -------- | --------------------------------- | -------------------------------------------- | ------------------------------ |
| Location | `location`: `{lat, long}`         | Location ▸ Latitude, Longitude (from asset¹) | EXIF GPS IFD                   |
| Title    | `name`                            | –                                            | XMP `dc:title`                 |
| Caption  | `description`                     | –                                            | XMP `dc:description` (+ EXIF²) |
| Keywords | `keywords`                        | –                                            | XMP `dc:subject`               |
| Favorite | `favorite`                        | Is Favorite                                  | none: library only (spike 4)   |

¹ `-[WFPhotoMediaContentItem location]` returns the asset's location only while
no file of the photo has been fetched; after that, the file's GPS. ²
`ImageDescription`, when the file has one (decision below).

PhotoKit has no public title, caption or keywords, so on the iPhone and the Mac
picker route those stay as the file has them. People (named faces), hidden and
the time zone are in neither Photos' scripting dictionary nor Shortcuts: out of
reach, as are edits (the selection route converts the unedited original).

## 2. Decisions

- **The same rule as the date.** For each field the route knows, `photobatch`
  compares Photos' value with the file's: the same, the file stays byte for
  byte; another, Photos' is written; Photos has none and the file has one, it
  is removed from the file. A field the route doesn't know (no line) leaves the
  file's.
- **A separate file, `jxl_meta.txt`**, beside `jxl_dates.txt` (which stays as
  it is): `i|field|value`, one line per field. An older `photobatch` ignores
  it, and a newer one without it behaves as before.
- **Location:**
  - The same when both coordinates are within 0.00001° (about 1 m) of the
    file's: Photos returns reals, EXIF stores rationals (an iPhone writes
    seconds to 0.01", about 0.3 m), and the Mac route rounds to 0.000001°.
  - Another location: a new GPS IFD with `GPSVersionID`, latitude and
    longitude, and Photos' altitude when the route has one (the Mac's selection
    route: Photos' `altitude` follows the location, spike 1). An altitude of
    exactly 0 is none: a place typed in Info gets 0.0 (spike 1), as a location
    without altitude does, and a measured one is never exactly 0. The file's
    direction, speed, positioning error and fix time belong to the old fix, so
    they go. Shortcuts' Altitude is a Number (text in the device's locale, and
    0 when unknown), so the iPhone and the Mac picker route write none.
  - None in Photos: the GPS IFD and IFD0's pointer to it go. A location hidden
    in Photos (Hide Location) reads as none (spike 1), so its copy has none:
    the privacy problem is solved, and the copy can't be reverted to it.
  - Either way, the old GPS IFD and the values it points to are zeroed, so the
    old coordinates aren't left in the file's bytes, and the XMP's `exif:GPS*`
    properties and place names (`photoshop:City`/`State`/`Country`,
    `Iptc4xmpCore:Location`/`CountryCode`, `Iptc4xmpExt:LocationCreated`/
    `LocationShown`) are removed.
- **Title, caption, keywords:** written to XMP (`dc:title` and `dc:description`
  as `x-default` in an `rdf:Alt`, `dc:subject` as an `rdf:Bag`), the standard
  place, and the only one a JPEG XL or HEIC has (IPTC IIM lives in JPEG's
  APP13, which `photobatch` doesn't carry today). Keywords compare as a set. A
  file without XMP gets a new packet.
- **EXIF `ImageDescription` follows the caption** when the file has one
  (replaced, or removed when Photos has no caption): ImageIO takes it over
  `dc:description` when they disagree (spike 2), so a stale one would win. It
  isn't added when the file has none. The file's caption, for the comparison,
  is likewise its `ImageDescription`, else its `dc:description`. Windows' `XP*`
  tags are left alone (rare in camera files).
- **Favorite** has no field in a file (Photos doesn't take `xmp:Rating` 5 as
  one, spike 2), so it is set in Photos: after the import on the Mac's
  selection route (AppleScript), and on the iPhone and the Mac picker route
  with Photos' Favorite Photos action on the saved copy (spike 4).
- **The check after import** (Mac selection route, `import.applescript`) covers
  every field, as it does the date: the copy's location, title, caption,
  keywords and favorite are compared with the original's and set in Photos when
  they differ (a safety net, and the only way for the favorite). It reads
  `properties of` the original and the copy, one Apple event each. This is
  option B of issue #19, which closes with this change.
- **Compress Videos** shares `export.applescript` and `import.applescript`: its
  copies get the check after import too (favorite, title, caption, keywords,
  location set in Photos). Writing them into the video file is a separate issue
  (to file).
- **Escaping** in `jxl_meta.txt` and in `export.applescript`'s output: `%`,
  `|`, tab, LF and CR as `%25`, `%7C`, `%09`, `%0A`, `%0D`; within keywords,
  `,` as `%2C`. Text goes into XMP as valid UTF-8, XML-escaped, without the
  control characters XML 1.0 can't hold.
- *Compress Photo Files (macOS)* is unchanged: Finder files have no Photos
  metadata.

## 3. Design

### 3.1. `jxl_meta.txt`

```
3|gps|40.748440,-73.985664,37.62
3|title|Empire State
3|caption|From the 86th floor%0Aat dusk
3|keywords|NYC,skyline,a%2Cb
4|gps|
5|gps|40.758442,-73.829767
```

- `gps`: decimal degrees, latitude first, then the altitude in meters if known;
  `.` as the decimal point, an exponent allowed (Shortcuts' `%0.16g` writes
  `5e-05`). Empty: Photos has no location.
- `title`, `caption`, `keywords`: escaped as above. Empty: Photos has none.
- No line for a field: the route doesn't know it; the file's stays.

### 3.2. `photobatch`

- `read_meta` (like `read_dates`) fills each job's fields, with a flag per
  field for "given".
- `apply_photos_meta` runs after `apply_photo_date`, on the same EXIF and XMP,
  in both routes (JPEG XL; HEIC transcode and HEIC from pixels).
- `meta.c`:
  - `exif_gps`: reads the file's latitude and longitude (refs and rationals).
  - `exif_set_gps(tiff, len, location or NULL, out)`: appends a new GPS IFD
    (with `GPSAltitudeRef` and `GPSAltitude`, in centimeters, when the location
    has an altitude) with `append_ifd`, then points IFD0's `0x8825` entry at it
    in place, or rewrites IFD0 when it has none, or without it for a removal,
    as `exif_set_capture_date` does for the Exif IFD. Zeroes the old GPS IFD
    and its out-of-line values. Rationals use integer arithmetic only, so every
    build writes the same bytes: degrees/1, minutes/1, seconds/10000.
  - `exif_set_description`: sets `ImageDescription` with its value appended and
    the entry patched in place, or removes it (IFD0 rewritten).
- `xmp.cpp`:
  - The scanner gives each top-level property's whole span (element, or
    attribute in shorthand form), so that it can be removed.
  - `xmp_dc_text` / `xmp_dc_bag`: read the file's `dc:title`, `dc:description`
    (the `x-default` item, else the first) and `dc:subject`.
  - `xmp_set_dc`: removes the given properties wherever they are, and adds one
    `rdf:Description` (with the packet's `rdf:about`, and `xmlns:dc`) before
    `</rdf:RDF>` with the ones that have a value.
  - `xmp_remove_location`: removes the `exif:GPS*` and place-name properties.
  - `xmp_new_packet`: a minimal packet (`x:xmpmeta`, `rdf:RDF`, one
    `rdf:Description`, `<?xpacket?>` wrapper) for a file without XMP.
- HEIC (`heicout.c`, `heifbox.c`): `hb_rewrite_t`'s single added item becomes a
  short list, so a file without them can get both a new `Exif` item and a new
  XMP item (`mime`, `application/rdf+xml`, a `cdsc` reference to the picture).
  An existing XMP item is replaced as now.
- JPEG XL: a new packet goes in an `xml ` box, as the file's own would.
- Log lines (no text of titles or captions):
  `location from Photos: 40.748440, -73.985664 (the file had ... | none)`,
  `location removed: Photos has none`,
  `title from Photos (the file had another | none)`,
  `title removed: Photos has none`, the same for caption and keywords;
  `! location not understood (...)`, the file's kept.

### 3.3. Mac selection route

- `export.applescript` reads `properties of` each selected item once (one Apple
  event, about 18 ms, instead of `id of`, `date of` and `filename of`, about 16
  ms each). Inside `tell application "Photos"` the record's fields need their
  raw codes: `«class ID  »`, `«class idat»`, `«class filn»`, `«class IPlo»`,
  `«class alti»`, `«class pnam»`, `«class IPde»`, `«class IPkw»`. A title,
  caption or keywords Photos doesn't have are `missing value` (spike 1): an
  empty value. It returns the `id|date|filename` lines as now, then one line
  per known field, `id<TAB>field<TAB>value`, escaped. Those lines have no `|`,
  so Compress Videos' `selection.zsh` skips them as it skips any line without
  two `|` (a comment there says so). The location is formatted in AppleScript
  without a real-to-text coercion, which follows the Mac's number format
  (`40,7` in some regions) and switches to `E` notation: the coordinate is
  rounded to an integer number of millionths of a degree (under 2^29, so still
  an integer), then split into whole degrees and a 6-digit fraction; the
  altitude likewise, in centimeters (`missing value`: none).
- `selection.zsh` maps each id to its job index, as for dates, and writes
  `jxl_meta.txt` with the values as they came (still escaped). A name two
  selected photos share gets no lines.
- `import.applescript`: `properties of` the original and the copy; date (as
  now), location, title, caption, keywords and favorite compared, the copy's
  set where they differ. One log line counts what was set, and the time is in
  the "Photos took ..." line. `""` and `missing value` both mean none. To
  remove (spike 1): `set location to {missing value, missing value}`,
  `set name to ""` (it then reads `""`), `set description to ""` and
  `set keywords to {}` (they then read `missing value`).

### 3.4. iPhone and Mac picker route (Shortcuts)

- `wf.photo_location(b, photo, index)`, called in `per_photo` **before** the
  file is fetched (the iPhone's `per_photo` puts the file to a-Shell first
  today; the call goes above it):
  - Get Details of Images ▸ Location; if it has a value, Get Details of
    Locations ▸ Latitude and ▸ Longitude, which are text already (`%0.16g`,
    locale-independent per the decompiled `WFLocationContentItem`), appended to
    `Meta` as `i|gps|lat,lon`.
  - No location: `i|gps|` only for a library photo (Is Favorite has a value, as
    in `collect_in_album`). An image from Files has no asset; its Location is
    its file's GPS anyway.
  - Should the file have been fetched already, Location is the file's GPS: the
    copy keeps the file's location, never a wrong one.
- `Meta` goes to a-Shell as `jxl_meta.txt` next to `jxl_dates.txt` (iPhone), or
  through the script's slots (Mac picker route, a new `@META@` slot). The
  cleanup lists get `jxl_meta.txt`.
- Favorite: when the original's Is Favorite is Yes, Photos' Favorite Photos
  action (Favorite) on the copy Save to Photo Album returned (spike 4). Is
  Favorite's text is localized ("Yes" in any language), so the test is If's
  Boolean condition, not Match Text. The action's and the condition's format is
  from a sample shortcut built on the iPhone (spike 4), written by the builder
  (`wfkit.favorite_photos`, `wfkit.if_true`). From the share sheet, JXL-Import
  has no originals: Compress Photos marks each favorite with
  `jxl_favorite_<i>.txt` in a-Shell.

## 4. Spikes

1. **Photos' AppleScript (done, 2026-10-12, macOS 26).** The user ran
   `get properties of every media item of album "Metadata test"` in Script
   Editor, on five duplicates of an iPhone HEIC with GPS (no Automation access
   for the agent's shell). One event returns every item's record, with `id`,
   `filename`, `date`, `location`, `altitude`, `name`, `description`,
   `keywords`, `favorite` (and `width`, `height`, `size`):

   - Untouched: `location` `{40.752091666667, -73.981575}`, the file's GPS
     exactly (40°45'7.53"), `altitude` 37.62.

   - Location copied from another photo (Copy Location, Assign Location): the
     other photo's `{40.758441666667, -73.829766666667}` and its `altitude`,
     11.73: the altitude follows the location.

   - Hide Location: `location` `{missing value, missing value}`, `altitude`
     `missing value`; a script can't see the hidden original.

   - No title, caption or keywords: `missing value` each (not `""` or `{}`);
     set: `"Testing-123"`, `"Some caption"`, `{"hudson"}`. Favorite: `true`.

   - A place typed in Info ("Miami, FL"): `{25.7708431, -80.1976364}`,
     `altitude` 0.0.

   - Writes, on the untouched duplicate: `set location` to
     `{missing value, missing value}` removed the location and its altitude;
     `set name` to `""` left `""`; `set description` to `""` and `set keywords`
     to `{}` left `missing value`. No errors.

2. **What Photos reads from a copy on import.** Five JPEGs, each with one kind
   of metadata written by exiftool (GPS with altitude; `dc:title`,
   `dc:description`, two `dc:subject` keywords, one with a comma; a conflicting
   `ImageDescription` and `dc:description`; `ImageDescription` alone;
   `xmp:Rating` 5), converted by `photobatch` (native, current source) to JPEG
   XL and to HEIC (from pixels). ImageIO (done, 2026-10-12, macOS 26):

   - GPS, with altitude, from both formats.
   - `dc:` title, caption and keywords from both formats' XMP, which ImageIO
     also gives as IPTC `ObjectName`, `Caption/Abstract` and `Keywords`.
   - Conflict: `ImageDescription` wins, in the JPEG, JPEG XL and HEIC alike:
     ImageIO's caption and even its `dc:description` are the EXIF text.
     `ImageDescription` alone is the caption too.
   - `xmp:Rating` 5 comes back as IPTC `StarRating` 5.

   (A first run showed no XMP in the HEICs: `build/photobatch` was older than
   the source. Rebuilt, they have it.)

   Photos on the Mac (done, 2026-10-12): the user imported the ten copies
   (`testdata/metadata-spike/`) and read them as in spike 1. Photos takes what
   ImageIO gives, in both formats: location
   `{25.770843333333, -80.197636666667}` with `altitude` 12.5; title
   `"Spike title"`, caption `"Spike caption"`, keywords
   `{"kw one", "kw, two"}`; the conflict's caption is `"EXIF description"`;
   `ImageDescription` alone is the caption. A rating of 5 is not a favorite
   (`favorite:false`). The iPhone's import is checked with the device runs
   (section 6).

3. **Shortcuts' Location, on the iPhone** (decompiled, to confirm): a photo
   whose location was changed in Photos reads Photos' location before Put File
   and the file's after; Get Name and `keep_still_photos` don't fetch the file;
   Latitude and Longitude read with `.` under a German region format.

4. **Favoriting from a shortcut (iPhone part done, 2026-10-12).** macOS 26's
   Photos registers the App Intent `FavoriteAssetsIntent` (PhotosUICore's
   `Metadata.appintents/extract.actionsdata`): "Favorite Photos", "Favorites or
   unfavorites the specified photos", with Photos (a list of `AssetEntity`,
   importable from `com.apple.Photos.PHAsset`) and an action (Favorite, the
   default, or Unfavorite). The user built a sample on the iPhone (iOS 26): the
   action is stored as `com.apple.mobileslideshow.FavoriteAssetsIntent` with an
   `AppIntentDescriptor` (`FavoriteAssetsIntent`, `com.apple.mobileslideshow`,
   "Photos", team `0000000000`) and `assets`; an If on a Boolean is
   `WFCondition` 4 with the switch `WFConditionalActionBoolean` (left at its
   default, so not stored). The iPhone shortcuts use it; still to confirm on
   the device that it takes the photo Save to Photo Album returns. The Mac's
   picker route waits for a Mac sample (Photos' bundle identifier differs).

5. **No location outside the GPS IFD and the XMP (done, 2026-10-12).**
   `exiftool -a -u -G1 -ee` on the samples with GPS in `testdata` (iPhone 13
   mini and 17 Pro HEICs, an iPhone 15 Pro JPEG): the location is only in the
   GPS IFD (latitude, longitude, altitude, speed, direction, bearing, fix time,
   positioning error). Apple's maker note, decoded and unknown tags alike, and
   the XMP (dates, depth and matte descriptions, unnamed face regions) hold no
   coordinates. No camera JPEG with GPS was at hand.

## 5. Steps

Steps 1 to 6 and 8, and the iPhone's favorite of step 7, were done on
2026-10-12 (branch `2026-10-12-photos-metadata-in-file`); how it works now is
in
[DEVELOPING.md](../shortcuts/compress-photos/DEVELOPING.md#15-location-title-caption-keywords-and-favorite).
The rest of step 7 (the device checks, and the favorite from the Mac's picker)
waits for the devices.

1. Spikes 1, 2 (ImageIO part) and 5: they settle the formats and the removal.
2. `photobatch` GPS: `exif_gps`, `exif_set_gps`, `xmp_remove_location`,
   `read_meta` and the `gps` line; tests.
3. `photobatch` title, caption, keywords: the scanner's spans, `xmp_set_dc`,
   `xmp_new_packet`, `exif_set_description`; tests.
4. HEIC: a second added item (XMP); tests.
5. Mac selection route: `export.applescript`, `selection.zsh`,
   `import.applescript` (with #19), Compress Videos' `selection.zsh` comment;
   tests.
6. Shortcuts: `wf.photo_location`, the `Meta` variable and file, cleanup;
   tests.
7. Spikes 3 and 4 on the iPhone: a sample shortcut with Favorite Photos and an
   If on Is Favorite (its iCloud link, for `--fetch`), then the favorite in the
   iPhone's and the Mac picker's shortcuts, and the device checks.
8. Docs (DEVELOPING.md, a section after Dates; README and README-mac, what
   deleting loses), CHANGELOG, Compress Photos 0.8.0, Compress Videos 0.2.0
   (its shortcut embeds the shared AppleScripts, whose check after import now
   covers its copies too).

## 6. Verification

- `tests/compress-photos/test_photos_meta.py` on every build:
  - GPS added to a file without one, replaced (the old coordinates' bytes gone
    from the output), removed (pointer gone, bytes zeroed, XMP GPS and place
    names gone), the same within 0.00001° (EXIF byte for byte); south and west;
    exponent forms; a value not understood (file kept, `!` line); IFD0 without
    a GPS pointer, a file without EXIF; Apple's maker note intact.
  - Title, caption, keywords added to a file without XMP (JPEG XL `xml ` box,
    HEIC new item), replaced (element and attribute forms), removed, the same
    (XMP byte for byte); keywords in another order count as the same; escapes
    (`%`, `|`, tab, newlines, `,`, `<`, `&`, non-ASCII); control characters
    dropped; `ImageDescription` replaced and removed, not added.
  - ImageIO reads the GPS and the title, caption and keywords from JPEG XL and
    HEIC outputs; native and WebAssembly builds write the same bytes.
- `test_mac_script.py`: `selection.zsh` turns `export.applescript`-style lines
  into `jxl_meta.txt` (escapes kept, duplicates without lines); Compress
  Videos' `selection.zsh` ignores the new lines. `osacompile` checks the
  AppleScripts against Photos' dictionary.
- `test_shortcuts.py`, `test_mac_shortcuts.py`, `test_shortcut_flow.py`: the
  Location read comes before the file is fetched; `jxl_meta.txt` written and
  cleaned up; the a-Shell flow with `jxl_meta.txt`.
- On the Mac (selection and picker routes), with duplicates: location changed,
  location removed, location added to a photo without GPS, title + caption +
  keywords set, a caption cleared from a file that had one, a favorite. Photos'
  Info for each copy, and the file's tags (EasyLoupe, ImageIO).
- On the iPhone (picker and share sheet): location changed and removed; a
  favorite, per spike 4.
