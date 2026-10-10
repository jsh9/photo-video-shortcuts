# Compress Photos: JPEG XL for iPhone Photos

Select photos in Photos → Share → **Compress Photos** → pick a quality preset
(83 is the everyday choice). JPEG XL copies are saved back to Photos, into the
same albums as the originals, keeping the original's metadata: capture date,
time and time zone, GPS location, camera, lens, exposure, maker notes, and XMP.
Started from the Shortcuts app instead, it lets you pick the photos. Either
way, the converted originals are collected in the album *Compressed to JXL* for
you to review and delete; the shortcut deletes nothing. Only still photos are
converted, screenshots included: Live Photos and videos are skipped.

iOS can display JPEG XL but has no encoder, so the conversion runs in
[a-Shell](https://holzschu.github.io/a-Shell_iOS/) as a small WebAssembly tool,
`jxlbatch`. It uses libjxl, the reference JPEG XL encoder. How it works, and
how to build it: [DEVELOPING.md](DEVELOPING.md). On a Mac, use the Mac
shortcuts instead: [Compress Photos (macOS)](README-mac.md), the same encoder
without a-Shell.

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. Installation](#1-installation)
- [2. Use](#2-use)
  - [2.1. Quality presets](#21-quality-presets)
- [3. What is and isn't kept](#3-what-is-and-isnt-kept)
  - [3.1. HDR photos](#31-hdr-photos)
  - [3.2. Dates](#32-dates)
- [4. Troubleshooting](#4-troubleshooting)

______________________________________________________________________

<!--TOC-->

## 1. Installation

See [Installation](../../README.md#1-installation) in the main README.

Then, in Photos, create an album named **Compressed to JXL** once (Albums ▸
**+** ▸ New Album). The shortcut collects the converted originals there and
can't create it itself: Shortcuts' Create Album makes a second album every
time, and nothing tells a shortcut whether an album exists, so it would pile up
albums whenever this one is empty. (On a Mac, *Compress Photos (macOS)* creates
it, and iCloud Photos syncs it to the iPhone.) Without it, the run stops with
"The photo album that was selected does not exist".

## 2. Use

- **Two ways to start it:**
  - **From the Shortcuts app** (tap it, or ▶ in the editor): it shows a photo
    picker, without videos. Photos picked there come straight from the library,
    so the original HEIF is used. As each JXL copy is saved, its original is
    added to the album **Compressed to JXL** (created if needed; a photo
    already in it isn't added twice). Review that album and delete its photos
    when you are done; the shortcut deletes nothing.
    - The first time, iOS asks whether the shortcut may save to a photo album:
      allow it. Don't Allow stops the run (from the share sheet, before the
      conversion; from the picker, after the first copy is saved); run it again
      and allow.
    - a-Shell's output says which copies lack their original's HDR
      (`! HDR gain map not used`, see [HDR photos](#31-hdr-photos)): those
      originals are in the album too, so look at the output before deleting.
    - Deleted photos go to Recently Deleted for 30 days. Deleting also removes
      what the JXL doesn't have: depth/Portrait data, the SDR version of an HDR
      photo (see [HDR photos](#31-hdr-photos)), edit history, and Photos-only
      information (favorites, captions, people). Albums are kept, because the
      JXL is added to them. Live Photos are never converted, so they are never
      collected.
    - It must run inside the Shortcuts app. Started from a Home Screen icon,
      widget or the Action Button, it can't wait for a-Shell, because
      Shortcuts' Wait to Return only works inside the app. It then stops at
      once with "File jxl_done.txt not found".
  - **From Photos:** select photos ▸ Share ▸ **Compress Photos**. The selected
    still photos are added to the album **Compressed to JXL** before the
    conversion (the shortcut is over once a-Shell is in front), so a photo
    whose conversion fails is in the album too: a-Shell's output names it. An
    image shared from another app (Files, for example) isn't in the library, so
    it isn't collected; only its JXL is saved, as before. The share sheet's
    **Send As** option decides the format. Its default, Automatic, converts
    HEIF to JPEG, so the shortcut gets a JPEG copy, and the sizes shown compare
    against it. To send originals, tap **Options** at the top of the share
    sheet and set Send As to **Current**. iOS offers no way to make that the
    default, and a shortcut can't set it. `jxlbatch` prints a reminder when it
    receives iPhone photos as JPEG.
- **Only still photos are converted**, screenshots included. The shortcut skips
  the rest of the selection, then a notification counts what it skipped, for
  example "Skipped 2 Live Photo(s), 1 video(s)":
  - **Live Photos**, so that their video is never lost. To convert the still
    image of one, use Duplicate ▸ Duplicate as Still Photo in Photos and
    convert the copy.
  - **Videos**. The photo picker doesn't show them.
  - When nothing is left, the shortcut says "Nothing to convert" and stops.
  - Images shared from other apps, such as Files, are converted like photos;
    the result is saved to Photos.
- Then pick a quality from the list (see
  [Quality presets](#21-quality-presets)).
- a-Shell opens and shows progress for each photo, with what the shortcut
  skipped repeated at the top and at the end, since the notification is gone as
  soon as a-Shell comes to the front. **Keep it in the foreground until it
  switches back to Shortcuts by itself.**
  - iOS pauses a-Shell in the background.
  - When started from the Shortcuts app, switching back early makes the
    shortcut continue before the conversion is done. It then saves nothing.
- The JXL copies get the date Photos shows for their originals, so they sort
  next to them, also when you changed a photo's date in Photos or the photo has
  no capture date of its own (see [Dates](#32-dates)). A notification shows how
  many were saved.
- **Albums:** each JXL is also added to every album its original is in. It's
  one photo, not a copy per album.
  - From the share sheet, the albums are passed to JXL-Import by name. If two
    of your albums have the same name, the JXL may land in only one of them.
  - This is meant for your own albums. Shared albums and built-in ones such as
    Favorites aren't handled.
- When sharing from Photos, keep **Location** on under **Options**. Otherwise
  iOS removes GPS before the shortcut sees the photo.

### 2.1. Quality presets

The shortcut lists these JPEG XL qualities, each with a short description in
smaller text:

| Quality          | What to expect                                                                                                                                   |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| 93               | Placebo: no visible difference from the original, even in the sunset sky; files about 40% larger than at 88, and can be larger than the original |
| 88               | Almost placebo: very little visual degradation (even the most challenging scene, the sunset sky, can be rendered very well)                      |
| **83** (default) | Go-to option for everyday scenes (almost perfect blue sky); film grains well preserved                                                           |
| 72               | Details well preserved, but tiny color banding in blue sky; film grains start to get affected                                                    |
| 63               | Details well preserved; a bit more color banding in blue sky                                                                                     |
| 52               | Small losses in details; more color banding in blue sky                                                                                          |
| 40               | Visible losses in details; color blotches in blue sky                                                                                            |
| 30               | More losses in details; bigger color blotches in blue sky                                                                                        |
| 20               | Details get smudged; color artifacts in blue sky                                                                                                 |
| 10               | It’s like watching RMVB videos in 2002                                                                                                           |
| 5                | It’s like watching bad RMVB videos in 2002                                                                                                       |

- Shortcuts menus show only a title and can't pre-select an option. So each
  preset is a contact card: the number is the name, and the description is the
  company line shown under it. The default is marked "(default)" in its title.
- Tapping a preset picks it and continues.
- To change the presets, edit the first Text action in *Compress Photos* on the
  phone, or `QUALITY_PRESETS` in `scripts/wf.py` (shared with the Mac
  shortcuts) and rebuild (see [DEVELOPING.md](DEVELOPING.md)).

Effort is fixed at 7, `cjxl`'s default. To trade a little size for speed, edit
the Execute Command action in *Compress Photos* and change `-e 7` to `-e 5`.

## 3. What is and isn't kept

Kept:

- all EXIF: date, time and time zone, GPS, camera and lens, exposure, maker
  notes;
- the date Photos shows, also one you changed in Photos (see
  [Dates](#32-dates));
- XMP;
- the color profile, e.g. Display P3, and 10-bit precision;
- **HDR**, for HDR photos from iPhones on iOS 14 or later (see
  [HDR photos](#31-hdr-photos));
- the file name, e.g. `IMG_1234.jxl`.

Not kept:

- **Depth/Portrait data**. The result is the still.
- **Live Photos** aren't converted at all (see [Use](#2-use)).
- **HDR of photos sent as JPEG** (Send As: Automatic): the JPEG's gain map
  isn't converted, so the result is the standard-dynamic-range (SDR) photo.
  Send them as Current instead.
- **HDR of photos from other apps, stored turned or cropped**, whose gain map
  isn't labeled as Apple's (see [HDR photos](#31-hdr-photos)): the result is
  SDR.
- **Edits**: an edited photo is converted as it looks now; the edit can't be
  reverted. Photos keeps the unedited original and the edit separately, but
  hands the shortcut only the edited rendering, from the share sheet and from
  the photo picker alike, so the JXL has neither the original nor the edit. If
  you want both, convert the photo before editing it, and edit the JXL (or keep
  the HEIC).
- **IPTC**, which has no standard place in JPEG XL. iPhone photos don't
  normally have any.
- **RAW/ProRAW (DNG) and other formats** aren't converted; only HEIF, JPEG and
  PNG are. Other photos fail with "unsupported format" and the rest of the
  batch continues.

### 3.1. HDR photos

An HDR photo from an iPhone is an SDR photo plus a *gain map*, which tells an
HDR screen how much brighter each part of the photo should be. Photos ignores
gain maps in JPEG XL, so `jxlbatch` applies the gain map itself and stores the
HDR result in the pixels: 16-bit, Display P3, with the PQ curve used for HDR
video (SDR white at 203 nits). In Photos it lights up on an HDR screen like the
original, and a-Shell shows the photo's line as, for example,
`HEIF 4284x5712, HDR 3.5×`: its highlights reach 3.5 times SDR white.

Both of Apple's gain map formats are converted:

- **iOS 18 and later**: the ISO 21496-1 gain map.
- **iOS 14 to 17** (iPhone 12 and later): Apple's older gain map, applied the
  way Apple renders it. That differs from Apple's documentation
  (["Applying Apple HDR effect to your photos"](https://developer.apple.com/documentation/appkit/applying-apple-hdr-effect-to-your-photos))
  in one point: the gain map's curve is a gamma of 2.2, not Rec. 709, which
  would come out brighter.

Gain maps an iPhone camera labels as Apple's are used: for those, how the gain
map lines up with a rotated or cropped photo is known. An ISO 21496-1 gain map
without the label is used too if the photo is stored upright and uncropped, as
Photos saves an edited photo (at its new size): it then covers the whole photo.
An HDR HEIC from elsewhere (for example saved by another app, or on a Mac)
whose gain map isn't labeled, stored turned or cropped, is converted as SDR,
and a-Shell says
`! HDR gain map not used (not an iPhone camera photo); saved as SDR`, and at
the end of the batch how many such photos there were. Its original is in the
album *Compressed to JXL* like the others; deleting it loses its HDR.

**Edited photos:** checked with HDR photos edited in Photos, from an iPhone 17
Pro (iOS 26) and an iPhone 13 mini (iOS 16, Apple's older gain map): they
convert as HDR. When Photos saves an edit it writes a new gain map (the
headroom can change) and drops the original's HDR profile with Apple's tone
curve, so a-Shell says `! Apple's HDR profile not found` for those from iOS 18
and later (see below): on screens that can't show all of the HDR, the JXL looks
a little darker or brighter than the edited HEIC (at full brightness they
match), while a JXL converted from the unedited photo keeps the profile.
Checked with crops, rotations and adjustments (exposure, shadows, highlights, a
style). If one gives `not an iPhone camera photo`, keep its original when you
go through the album *Compressed to JXL*.

**Implausible brightness:** a gain map claiming to brighten the photo by more
than 16 stops (65,536×), in either format (for Apple's older one, the headroom
its maker notes give), is treated as broken
(`! HDR gain map not used (malformed gain map metadata)`): the photo is saved
as SDR and its original is kept (except a photo whose gain map isn't used for
the reason above anyway). Real photos are far below this: iPhones reach about 3
stops, and the JXL's PQ format itself ends about 5.6 stops above SDR white.

On a screen that can't show all of that brightness (an SDR screen, a dimmer
setting, or HDR turned off), Apple dims the photo with a tone curve it derives
from the gain map. Since iOS 18, iPhones store that curve in the HEIC, in an
HDR color profile, and the JXL keeps it (about 3 KB), so it looks like the
original there too. A photo without that profile, such as one taken before iOS
18 or one edited in Photos, gets Apple's standard dimming instead, and may not
look like the original there: darker, in tests with camera originals, or
brighter, for a heavily edited photo (at full brightness they match). a-Shell
then says `! Apple's HDR profile not found` (except for photos taken before iOS
18, which never have one).

Grain: an HDR JXL gets a little fine grain in its smooth areas (skies, walls,
out-of-focus backgrounds), which makes it about 10-15% larger than it would be
without. Apple draws the SDR version of an HDR JXL with half the levels an
ordinary photo has, so a smooth sky would show stripes (a lossless file too);
the grain hides them, as the camera's own grain does in the original. It's only
visible zoomed far in. Photos converted by earlier versions keep their stripes;
converting the original again fixes it. `jxlbatch --grain 0 --grain-coarse 0`
turns the grain off (see [DEVELOPING.md](DEVELOPING.md)).

Size: with a smooth gain map, like an iPhone's, an HDR JXL is about as large as
the same photo converted as SDR (in tests, 4% smaller to 14% larger). A gain
map with fine, noisy detail costs more (up to about 1.5× in tests). To convert
HDR photos as SDR anyway, run `jxlbatch` in a-Shell with `--sdr`; the shortcut
doesn't offer it.

Apps other than Apple's may show the HDR JXL without its highlights: few of
them read HDR JPEG XL yet.

**Known issue, pink patches in skies:** in Photos, an HDR JXL of a photo with a
bright blue sky or bright clouds can show faint pink or lavender patches there,
which neither the original nor an SDR copy shows. The file is fine: its pixels
match the original's HDR rendering, and Apple's direct image decoder shows them
exactly. The patches come from how Photos displays an HDR JPEG XL: it first
makes an SDR version of the picture with a filter that shifts colors by 1 to 2%
in patches, then builds the HDR view from that SDR version, so the shift stays
on an HDR screen too. The original HEIC isn't affected, because its SDR version
was made by the camera, and neither is the same picture in another HDR format,
so it's specific to Apple's handling of JPEG XL (checked on macOS 27 in October
2026). Until Apple changes it, convert such photos as SDR: Drop HDR on the Mac,
or `--sdr` in a-Shell; the SDR copy has no patches. `jxlbatch` points them out:
a photo whose bright sky (smooth, colored, brighter than SDR white) covers 5%
or more of it gets the line
`! bright sky (39% of the photo): in Photos, the HDR copy may show faint pink patches there`,
and the end of the batch says how many there were. `--sky-warn 10` raises the
bar to 10%; `--sky-warn 0` turns the warning off.

**Originals kept:** when the JXL lacks the original's HDR, the shortcut doesn't
offer to delete that original, and a-Shell says how many were kept. That
happens when a photo's gain map can't be used (a note in a-Shell, see
[Troubleshooting](#4-troubleshooting)), except for a photo not taken by an
iPhone camera (see above), for HDR photos sent as JPEG, and with `--sdr`. This
needs both the shortcuts and `jxlbatch.wasm` from version 0.2.0: an older
shortcut offers every converted original for deletion, and a newer shortcut
with an older `jxlbatch.wasm` offers none.

Photos may list the JXL copies under **Duplicates**. Merging a duplicate pair
keeps only one file, so check which one before you merge.

### 3.2. Dates

Each JXL gets the date Photos shows for its original, in Photos and in the file
itself (its EXIF capture date, which other apps read too):

- **A date you changed in Photos** (Adjust Date & Time) is kept. Photos keeps
  such a change in its library, not in the original file, so a plain copy of
  the file would have the camera's date again.
- **A photo without a capture date of its own**, such as an image saved from an
  app that removed it, or a screenshot, gets the date Photos shows for it
  (usually when it was added to Photos), not the time of the conversion.
- A photo whose capture date already is that date keeps its EXIF as it is.

When a date is written, a-Shell's output says so, for example
`date from Photos: 2024:01:01 17:00:00 -05:00 (the file had 2026:10:01 12:00:00 -04:00)`.
A written date is in the time zone your iPhone is in (with that zone's offset
on that date): Shortcuts doesn't say in which time zone a photo was taken. So a
photo from another time zone whose date is written gets the right moment, and
sorts the same, but its time reads as in your zone. A photo whose file has no
time zone (iPhones before iOS 13, most cameras) but whose time is that moment
somewhere keeps its time and gets that zone instead
(`time zone from Photos: ...`). This needs the shortcuts and `jxlbatch.wasm`
from version 0.7.0.

## 4. Troubleshooting

| Symptom                                                                                                                                                                     | Fix                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| a-Shell: `jxlbatch: command not found`                                                                                                                                      | `jxlbatch.wasm` isn't in `~/Documents/bin` (On My iPhone ▸ a-Shell ▸ bin).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| a-Shell stops after the photos, nothing is saved                                                                                                                            | Run **JXL-Import** from the Shortcuts app; it saves whatever finished.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| "File jxl_done.txt not found"                                                                                                                                               | No photo converted. Look in a-Shell for the error on each photo. In *Compress Photos*, it also happens when started outside the Shortcuts app (see [Use](#2-use)).                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| a-Shell: "cannot find jxl_job.txt"                                                                                                                                          | a-Shell ran the shortcut outside its Shortcuts folder, which version 0.1.0 does when it has to launch a-Shell. Update the shortcuts and `jxlbatch.wasm`.                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| a-Shell: "The WebAssembly interpreter is not running" before any photo                                                                                                      | a-Shell's engine hadn't finished starting. The shortcut waits and retries for this, so just run it again.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| a-Shell: "The WebAssembly interpreter is not running" in the middle of a photo                                                                                              | iOS stopped a-Shell's engine, usually for using too much memory. Close other apps and try again.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| A photo fails with an out-of-memory error                                                                                                                                   | Large photos, such as 48 MP, need the most memory. Close other apps and retry, or use `-e 5`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| "Unknown Album: The photo album that was selected does not exist"                                                                                                           | Create an album named *Compressed to JXL* in Photos (see [Installation](#1-installation)) and run again. From the share sheet nothing was converted yet; from the picker, the copies saved before the error are in Photos.                                                                                                                                                                                                                                                                                                                                                                                        |
| Notification "Nothing to convert"                                                                                                                                           | The selection had only Live Photos or videos; only still photos are converted (see [Use](#2-use)).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| A photo fails with "unsupported format"                                                                                                                                     | It isn't HEIF, JPEG or PNG (for example ProRAW DNG).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `! HDR gain map not used (...)` in a-Shell                                                                                                                                  | The photo was converted as SDR because its gain map isn't supported, for example with a color profile other than Display P3 or sRGB, or claiming more than 16 stops (`malformed gain map metadata`). Its original is in the album *Compressed to JXL* like the others; keep it. Please report it with the reason shown.                                                                                                                                                                                                                                                                                           |
| `! HDR gain map not used (not an iPhone camera photo)` in a-Shell                                                                                                           | The HDR photo's gain map isn't labeled as an iPhone camera's, and the photo is stored turned or cropped, so how they line up isn't known (see [HDR photos](#31-hdr-photos)): it was converted as SDR. Its original is in the album *Compressed to JXL* like the others; keep it if you want its HDR.                                                                                                                                                                                                                                                                                                              |
| `! Apple's HDR profile not found` or `not used` in a-Shell                                                                                                                  | The JXL is HDR, but without Apple's tone curve for dimmer screens, so on such screens it may look darker or brighter than the original (at full brightness they match). Photos edited in Photos have no such profile. Please report `not used` with the photo.                                                                                                                                                                                                                                                                                                                                                    |
| `! HDR not kept (JPEG with a gain map ...)` in a-Shell                                                                                                                      | Photos sent this HDR photo as JPEG. Set Send As to Current in the share sheet (see [Use](#2-use)). Keep the original if you want its HDR.                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `! orientation check` warning in a-Shell                                                                                                                                    | The converted pixels didn't match the original's orientation and size in its EXIF. Please report it with the photo's EXIF. (Photos edited in Photos keep the size from before the edit in their EXIF, so they aren't checked.)                                                                                                                                                                                                                                                                                                                                                                                    |
| A green horizontal stripe near the bottom of a converted photo in Photos on a Mac (in the thumbnail and the preview, gone once the full photo loads; the iPhone shows none) | A bug in Photos, not in the file: when a 4032×3024 (12 MP) JPEG XL is saved to Photos on an iPhone, iOS 27 writes a 2048×1536 preview whose rows 1264–1327 are dimmed by about 2.5%, whatever made the JXL (XnConvert shows it too), SDR or HDR; 24 MP photos aren't affected, and the JXL itself is fine, as is the full-size view. Reported to Apple (October 2026). Until it's fixed, convert 12 MP photos on the Mac, or re-import the affected JXL on the Mac (export it as the unmodified original, delete the photo including from Recently Deleted, then File ▸ Import): the Mac makes a correct preview. |
| Faint pink or lavender patches in a bright blue sky or in clouds of an HDR photo's copy, in Photos; the original and an SDR copy have none                                  | Apple's display of HDR JPEG XL, not the file: Photos makes an SDR version with a filter that shifts colors by 1-2% in patches and builds the HDR view from it, so the file's pixels (which match the original's HDR rendering) aren't what you see. See [HDR photos](#31-hdr-photos). Convert such photos as SDR: `--sdr` in a-Shell, or Drop HDR on the Mac.                                                                                                                                                                                                                                                     |
