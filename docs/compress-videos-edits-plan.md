# Compress Videos 0.4.0: an edited video is converted with its edits

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. The problem](#1-the-problem)
- [2. What is known, and what isn't](#2-what-is-known-and-what-isnt)
  - [2.1. Known](#21-known)
  - [2.2. Not known](#22-not-known)
  - [2.3. The ways to get the edited video](#23-the-ways-to-get-the-edited-video)
  - [2.4. Each kind of video](#24-each-kind-of-video)
- [3. Decisions for the owner](#3-decisions-for-the-owner)
- [4. Design](#4-design)
  - [4.1. The flow](#41-the-flow)
  - [4.2. `bridge.applescript`](#42-bridgeapplescript)
  - [4.3. The script, twice](#43-the-script-twice)
  - [4.4. Pairing, comparing, staging](#44-pairing-comparing-staging)
  - [4.5. Metadata](#45-metadata)
  - [4.6. The log](#46-the-log)
  - [4.7. Quality of an edited video's copy](#47-quality-of-an-edited-videos-copy)
  - [4.8. What must keep working](#48-what-must-keep-working)
- [5. The spike, first](#5-the-spike-first)
  - [5.1. What the owner does](#51-what-the-owner-does)
  - [5.2. What the shortcut does](#52-what-the-shortcut-does)
  - [5.3. What the agent reads](#53-what-the-agent-reads)
  - [5.4. Gates](#54-gates)
- [6. Steps](#6-steps)
- [7. Tests](#7-tests)
- [8. Docs, version, changelog](#8-docs-version-changelog)
- [9. Spike results](#9-spike-results)
- [10. Checks on the Mac, by the owner](#10-checks-on-the-mac-by-the-owner)

______________________________________________________________________

<!--TOC-->

**Built as 0.4.0 (2026-11-28), without the spike.** The owner chose to test the
real shortcut instead of a spike (section 5), so the gates of 5.4 are checked
by the owner's test of 0.4.0, and section 9 stays empty. Decisions as
recommended in section 3, with one change after Compress Photos 0.13.0: every
edited video's copy gets the keyword `burnt-in`, and the log names them in a
`!` line at its end (so it opens), as Compress Photos does for the photos whose
edits it burns in. The album is deleted before the conversion (D7); should G6
fail, the videos come unchecked, with a `!` line, and the album moves after the
conversion.

Plan written 2026-11-27, the day Compress Photos 0.12.0 did the same for photos
(issue #29, PR #30, [its plan](compress-photos-edits-plan.md)). Nothing is
built yet. Section 5 (the spike) comes first and can change the design: read
its gates before writing code. Section 3 has the decisions that are the
owner's.

## 1. The problem

*Compress Videos (macOS)* converts the videos selected in Photos, its only
route. `lib/mac/export.applescript` exports each item `with using originals`:
the file as it was recorded. An edit made in Photos (a trim, a filter, an
adjustment, a rotation, a crop) isn't in the copy. The README lists edits under
"Not kept", and deleting the original from the album *Videos already
compressed* loses the edit for good.

Goal: an edited video's copy looks as the video does in Photos now, the edit
baked in (not revertible on the copy), with its original's date, location,
camera and lens keys, albums, title, caption, keywords and favorite, as today.
An unedited video keeps today's path exactly: the same input file, the same
ffmpeg command, the same `vidmeta copy`. What is skipped today (photos, Live
Photos, slo-mo, spatial and Apple Log videos, videos ffmpeg can't read) is
still skipped.

## 2. What is known, and what isn't

Found on 2026-11-27 without running Photos (the agent's shell may not script
it): the files of macOS 27.0 (build 26A428), Shortcuts' ContentKit decompiled
from iOS 18.2 (GitHub, `EthanArbuckle/iPhone17-1_18.2_22C152_Restore`,
`System/Library/PrivateFrameworks/ContentKit.framework`), the same methods in
macOS 27.0's own ContentKit (see below the table), and the earlier spikes.

### 2.1. Known

| Fact                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | Source                                                             |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| `export` without `using originals`: "Export the original files if true, otherwise export rendered jpgs." What that writes for a video isn't said. A media item has no "edited" property, and no duration.                                                                                                                                                                                                                                                                                    | `Photos.sdef`                                                      |
| *Find Photos* where Album is a name fetches exactly that album's items as library items, and nothing in the fetch limits the media type. It has no try: with no such album (Shortcuts without full access to the library) it stops the run. Checked with photos only.                                                                                                                                                                                                                        | #29 (macOS 27, 2026-11-27); `WFPhotoLibraryFiltering.m`, iOS 18.2  |
| The file Shortcuts makes of a library **photo** is a stored resource: Photos' rendering of an edited photo, the original byte for byte otherwise.                                                                                                                                                                                                                                                                                                                                            | #29, section 9 of its plan                                         |
| A **video** takes another path. `-[WFPhotoMediaContentItem generateFileRepresentation:options:forType:]` sends an asset whose media type is video, when the type asked for conforms to `public.audiovisual-content`, to `retrieveFileWithImageManager:forType:`. That asks PhotoKit for an `AVAsset`: `requestAVAssetForVideo`, with network access allowed, `deliveryMode` 1 (high quality) and `version` left at its default.                                                              | ContentKit, iOS 18.2; the same calls in macOS 27.0's ContentKit    |
| The default version is `PHVideoRequestOptionsVersionCurrent`: "version with edits (aka adjustments) rendered or unadjusted version if there is no edits".                                                                                                                                                                                                                                                                                                                                    | `PHImageManager.h`, macOS SDK                                      |
| If the `AVAsset` is an `AVURLAsset`, Shortcuts copies the file at its URL into its temporary folder (`fileWithURL:options:ofType:proposedFilename:` with options 5, which is `-[NSFileManager copyItemAtURL:toURL:error:]`), named after the item: no export, no re-encoding. If it is anything else (PhotoKit gives an `AVComposition` for a slo-mo), it goes to `WFAVAssetContentItem`, which exports it with `AVAssetExportPresetPassthrough`: the samples are copied, not encoded again. | the same                                                           |
| So, by the code, Shortcuts never re-encodes a video it hands over. Whatever encoding an edited video's file has is Photos' own, made when it rendered the edit.                                                                                                                                                                                                                                                                                                                              | reading of the above                                               |
| Get Details of a library item: Duration is the asset's (`PHAsset.duration`), File Size the size of the resource `preferredAssetResourceForType:` picks (a full-size rendering first), Frame Rate comes from the `AVAsset`, Date Taken is the asset's creation date. The property names on macOS 27 include Name, Date Taken, Width, Height, Media Type, Duration, Frame Rate, File Size, File Extension.                                                                                     | the same; `+allProperties` in macOS 27.0's ContentKit              |
| `export … with using originals` gives a video, a slo-mo (240 fps, averaging 177) and a Live Photo (`IMG_x.HEIC` plus `IMG_x.mov`) as recorded, with one `id\|date\|filename` line per selected item.                                                                                                                                                                                                                                                                                         | V1, `docs/compress-videos-mac-design.md` 5.3                       |
| What Photos' Share menu itself hands a shortcut is not the original: a slo-mo came as 14.0 MB for a 24.0 MB original, a few bytes different on each of four runs, and another video as 16.7 MB for 15.5 MB, the same each time. The files were in `~/Library/Group Containers/group.com.apple.shortcuts/Temporary/…`, which `cp` and `head` read and ffprobe (Homebrew's and ours) can't: "Operation not permitted". No id, no details.                                                      | V2 (2026-10-05), `~/Library/Caches/compress-videos-spike/v12.log`  |
| The picker: with three picked videos, one a slo-mo, Shortcuts stopped before the script ran (AVFoundation -11800, -16364). Which video failed isn't recorded. A passthrough export of the slo-mo's composition would fit, and isn't proven.                                                                                                                                                                                                                                                  | V2                                                                 |
| macOS guards Shortcuts' group container as another app's data (TCC `kTCCServiceSystemPolicyAppDataDetailed`): a tool of ours gets "Operation not permitted" there, in a background run without a prompt, while Apple's `/bin/cp` and `/usr/bin/cmp` read it. A tool started from Run Shell Script is its own responsible process, and one that asks for Photos access without a usage description is killed.                                                                                 | #29; V2; `shortcuts sign` crash reports (2026-10-16)               |
| Inside one APFS volume, `FileManager.copyItem` of a 1 GB file takes 0.3 ms and no space (a clone), and so does `/bin/cp -c`, which falls back to a real copy across volumes. `/usr/bin/cmp` of two identical 1 GB files takes 2.4 s.                                                                                                                                                                                                                                                         | measured on this Mac (M4 Pro, internal disk), 2026-11-27; `man cp` |
| `vidmeta copy` copies the `meta` and `udta` boxes of the movie and of the first video track, and the creation and modification times. Durations, the rotation matrix and the sample tables stay the copy's own. ffmpeg's `-noautorotate` passes the input's rotation flag on to the copy.                                                                                                                                                                                                    | `src/mp4meta.h`; `DEVELOPING.md` 1.1                               |
| Compress Photos 0.12.0 is released (tag `compress-photos-v0.12.0`), and every release carries the current files of all tools. A change to text that Compress Photos' shortcuts embed needs a Compress Photos version.                                                                                                                                                                                                                                                                        | `git ls-remote --tags`; `docs/releasing.md`                        |

How macOS 27's ContentKit was read: a small Objective-C program (in `$TMPDIR`,
not kept) loads the framework with `dlopen`, finds each method with
`class_getInstanceMethod` and walks its arm64 code, naming the selector of
every `objc_msgSend` stub it calls and the small constants set just before
(`setDeliveryMode:` with 1, `fileWithURL:options:…` with 5, the string
`AVAssetExportPresetPassthrough`). That shows which calls a method makes and in
what order. It doesn't show what PhotoKit answers: nothing was run against a
library.

### 2.2. Not known

All of this is for the spike (5).

01. Whether *Find Photos* returns the videos of the album on macOS 27, from
    Photos' Share menu, and whether Run Shell Script then gets a file for each.
02. What PhotoKit gives Shortcuts for an edited video on the Mac: an
    `AVURLAsset` of a rendering Photos stored (expected: it is what "current"
    means), something else, or an error. And whether that depends on the edit:
    a trim alone, a filter or adjustment, a rotation or crop.
03. What Photos' rendering is: container, codec (H.265 or H.264), bit depth,
    HLG, Dolby Vision, bit rate against the original's, frame rate, sound (the
    stereo track only?), Apple's keys (date, location, camera, lens), the
    rotation as a flag or in the pixels. Whether a trim alone is a copy of the
    original's samples.
04. Whether an unedited video's file is the exported original byte for byte. By
    the code it is a copy of the library's file, and Photos' export is that
    file for photos.
05. A slo-mo: by the code, a passthrough export of a composition. It may fail
    (V2's picker), or give a file whose slow part is an edit list that ffmpeg
    doesn't follow.
06. A Cinematic video: whether Photos' current version is a rendering with the
    blur, which would differ from the recording.
07. Time and disk: how long Shortcuts takes per GB, and whether its copy is a
    clone. With the library on another disk than the home folder it can't be.
08. iCloud's "Optimize Mac Storage": Photos already downloads the original for
    its export. Photos' version of an edited video may need another download,
    with no progress shown and no time limit of ours; without a network,
    Shortcuts' error would stop the run. Whether PhotoKit can hand over a
    stream instead of a file then isn't known.
09. What AppleScript's `export` without `using originals` writes for a video.
10. What the user sees when Shortcuts has no access to the photo library (open
    since #29).

### 2.3. The ways to get the edited video

- **A. AppleScript's rendered export.** Its output for a video is unknown.
  Photos' own File ▸ Export encodes a video again at a size the user picks
  (from memory of that dialog, not checked here), and this may do the same. And
  nothing says which videos are edited, so either every video would go through
  it or none. Not used. The spike records what it writes.
- **B. The album bridge and *Find Photos***, as #29: AppleScript puts the
  videos into a temporary album by id, *Find Photos* gets them as library
  items, and Shortcuts hands the script Photos' current version of each.
  Comparing it with the exported original says which videos are edited. By the
  code Shortcuts adds no encoding of its own. This is the plan, if the gates
  pass.
- **C. A helper of ours that uses PhotoKit** (`PHAssetResource` of type
  `fullSizeVideo`, or `PHImageManager.requestExportSession`): exact, and it
  needs no album. But it is a new binary that needs Photos access: run from Run
  Shell Script it is its own responsible process, so it needs a usage
  description, a signature TCC remembers across releases, and a prompt that a
  background run may not be able to show (`photobatch` was refused Shortcuts'
  folder without one). Not now; the thing to look into if B fails.
- **D. The Share menu's own input**: re-rendered for every video (V2), so it
  can't tell an edited video from an unedited one, and has no id. No.

### 2.4. Each kind of video

| Kind                                                    | Today                                         | With this change                                                                               | Open                                             |
| ------------------------------------------------------- | --------------------------------------------- | ---------------------------------------------------------------------------------------------- | ------------------------------------------------ |
| unedited                                                | the original is converted                     | the same: `cmp` says Shortcuts' file is the original                                           | G2                                               |
| trimmed, filtered, adjusted, rotated, cropped           | the original is converted, the edit is lost   | Photos' version is converted                                                                   | G3                                               |
| edited, HDR or Dolby Vision                             | the same                                      | Photos' version, with its HDR and Dolby Vision if it has them; a `!` line if it lost them (D5) | what the rendering has                           |
| slo-mo                                                  | skipped                                       | skipped, and never handed to Shortcuts (4.3)                                                   | the spike records what Shortcuts would give (D6) |
| Live Photo, photo                                       | skipped                                       | skipped; never in the album                                                                    |                                                  |
| spatial, Apple Log, a codec or sound ffmpeg can't read  | skipped                                       | skipped, and never handed to Shortcuts                                                         |                                                  |
| Cinematic                                               | converted from the recording, like any video  | like any video: converted from Photos' version if that differs from the recording              | whether it differs                               |
| not on the Mac (Optimize Mac Storage)                   | Photos downloads the original for the export  | Shortcuts may also have to download Photos' version of an edited one                           | not tested unless the owner's library does this  |
| not returned by *Find Photos* (a hidden video, perhaps) | converted                                     | converted from the original, with a `!` line (D4)                                              |                                                  |
| two selected items with one file name                   | converted; no albums, originals not collected | the same, and not checked for edits                                                            |                                                  |

## 3. Decisions for the owner

Each with a recommendation. D1 to D3 shape the work and are needed before step
5; the others can wait for the spike's numbers.

- **D1. Where the bridge script lives.** Recommended: Compress Videos gets its
  own `shortcuts/compress-videos/scripts/mac/bridge.applescript`, Compress
  Photos' without the filter that leaves videos out (4.2). `lib/` and
  `shortcuts/compress-photos/` stay byte for byte, so Compress Photos ships
  nothing new. The two become one `lib/mac/bridge.applescript`, with a
  placeholder for what is left out, the next time Compress Photos' Mac shortcut
  changes for a reason of its own. Alternative: move it to `lib/mac/` now. Then
  the text in Compress Photos' shortcut changes (its comments at least: they
  speak of photos and of leaving videos out), which makes a Compress Photos
  0.12.1 whose only news is that: its shortcut and its three encoders rebuilt
  for the number, and Mac users told to update `photobatch-macos` or see the
  version warning.
- **D2. No new question.** Recommended: an edited video is always converted as
  it looks now, as Compress Photos does; a switch at the top of the script,
  `EDITS=1`, turns the check off (`EDITS=0`: every video from its original, as
  0.3.0), next to `SLOMO` and `DOLBY`. Alternative: a seventh question, "Edited
  videos: as they look now / the original recordings".
- **D3. Videos that are skipped never reach Shortcuts.** Recommended: only the
  videos that will be converted go into the album, which takes a planning pass
  of the script before the album is filled (4.3). A slo-mo is the one hand-over
  with a sign of failing (V2), and a hand-over that fails stops the run for
  every video in it: Shortcuts has no try. Alternative: every selected video
  goes into the album, as in Compress Photos (one action fewer, no second copy
  of the script); only if the spike's round C shows that a slo-mo and the other
  skipped kinds come without an error.
- **D4. A video that can't be converted as it looks.** Recommended, two cases.
  A video known to be edited whose Photos version ffmpeg can't convert is
  skipped and counted, like every video a copy would lose something of
  (decision 7 of `docs/compress-videos-mac-design.md`). A video that couldn't
  be checked (no file came for it, or two fit) is converted from its original
  with a `!` line, so the log opens, and its original is collected: what
  Compress Photos does (its D2), and today's result with a warning. If the
  album script fails, that is every video, with one `!` line. Alternative: skip
  the unchecked ones too; then a failing album script means nothing is
  converted until `EDITS=0`.
- **D5. Quality.** An edited video's copy is one generation more: the
  recording, Photos' rendering of the edit, our copy (4.7). Recommended: the
  settings the user chose, unchanged; the log says for each edited video what
  Photos' version is next to the original; a `!` line only when Photos' version
  lost what the README promises to keep (HDR, Dolby Vision, 10 bits, the
  sound). Alternatives: a lower RF for such videos (by how much has no
  measurement behind it), or a `!` line for every edited video.
- **D6. Slo-mo stays skipped in 0.4.0**, whatever the spike finds Shortcuts
  gives for one; converting a slo-mo as Photos plays it would be a version of
  its own. A Cinematic video follows the general rule (2.4).
- **D7. The album** is a top-level album named `Compress Videos (working)`,
  made after the export and deleted before the conversion starts, so it shows
  for seconds, not for the hours a batch can take (G6; else deleted before the
  import, as in Compress Photos). A run that dies leaves it; the next run
  deletes it first. Deleting an album deletes no video.
- **D8. Version 0.4.0**, Compress Videos only. No issue exists for this yet
  (#29's plan said to file one): the owner files it, or tells the agent to at
  step 11.

## 4. Design

As recommended in section 3, and assuming the gates pass.

### 4.1. The flow

`build()` in `build_mac_shortcuts.py`, new steps marked `+`:

```
  the probe; the work folder and the free-space check; the settings; the
  notification
  Run AppleScript export.applescript → IDS (unchanged)
+ Run Shell Script, the script's planning pass (PHASE=plan): today's tool
+    checks, sorting, probing and skipping; prints the "id|date|filename"
+    lines of the videos it would convert
+ Run AppleScript bridge.applescript (input: those lines) → variable
+    Bridge, "BRIDGE n" or "ERROR: ..."
+ If it matches ^BRIDGE [1-9]:
+    Find Photos where Album is "Compress Videos (working)" → variable
+    Renderings
+    Repeat with each: its Date Taken, as "index|ISO 8601" → variable Dates
+ Run AppleScript bridge.applescript (input: the text "close") → variable
+    Closed: deletes the album
  Run Shell Script, the conversion (PHASE=convert): today's script
+    input: Renderings, as arguments; BRIDGE, RDATES and CLOSED in heredocs
  Run AppleScript import.applescript (unchanged)
  the log in Quick Look if it has a note; the finish script; the
  notifications
```

The album must be gone before the import, which adds each copy to every album
its original is in. Deleting it before the conversion works only if Shortcuts
can still make the files then (G6): the items it holds are the library's, not
the album's. A Run Shell Script whose input variable was never set still runs,
with no arguments (#29).

New for the user: the album shows for a moment; Shortcuts needs its own access
to the photo library (*Find Photos*), where until now it only needed to control
Photos, and macOS asks once; without that access *Find Photos* stops the run
before anything is converted.

Two things this can't make safe, which the README must say:

- Shortcuts has no try. If it can't make the file of one video in the album, it
  stops the run with its own error and nothing is converted. Keeping the
  skipped kinds out of the album (D3) leaves only videos that would be
  converted; for those, `EDITS=0` is the way out.
- With the photo library on another disk than the home folder, Shortcuts'
  copies can't be clones: every selected video then takes room and time once
  more, on the home disk, next to Photos' export and the copies made. The check
  before the export (500 MB per item) doesn't count that.

### 4.2. `bridge.applescript`

`shortcuts/compress-videos/scripts/mac/bridge.applescript` (D1), a copy of
Compress Photos' with four differences: the album is `@BRIDGE_ALBUM@` =
`Compress Videos (working)`; its input is the planning pass's lines, not the
export's; it adds the item of every `id|date|filename` line (no `isVideo`: the
planning pass has chosen); and no input at all (the planning pass printed
nothing) is `BRIDGE 0`, not an error. The rest is the same: "close" deletes
every album of that name and returns `CLOSED`; any other input deletes them,
makes a new one, adds the items by reference (`media item id X`), each in a
`try`, and returns `BRIDGE n`, or `BRIDGE 0` and no album when there is nothing
to add; an error returns `ERROR: ...`; `planText` reads the lines from a file
when Shortcuts takes them for CSV. `applescript_text` in
`build_mac_shortcuts.py` looks in `scripts/mac/` first, then `lib/mac/`, and
fills in `@BRIDGE_ALBUM@`.

### 4.3. The script, twice

The planning pass must know what the conversion will skip, and that is all of
`common.zsh` (the settings, the tools, what this ffmpeg decodes) and most of
`selection.zsh` (sorting, probing, the skip rules, the free space). So the
shortcut has the script twice: `script_text(phase)` fills `@PHASE@` with `plan`
or `convert`, and the planning text ends where that pass exits (no
`encode.zsh`).

- `common.zsh`: `PHASE='@PHASE@'`; the switch `EDITS=${EDITS:-1}`; the heredocs
  `BRIDGE`, `RDATES` and `CLOSED` (slots `@BRIDGE@`, `@DATES@`, `@CLOSED@`: the
  variables in the conversion, nothing in the planning text).
- `selection.zsh`: it keeps each item's IDS line and its date (unused today).
  After the free-space check, in the planning pass: print the IDS line of every
  job that has an id, nothing with `EDITS=0`, and `exit 0`. That pass opens no
  window and writes no settings; the conversion starts the log and
  `vid_skipped.txt` afresh, so they end up as today.
- The conversion is today's script with 4.4 to 4.6 added. Probing every video
  twice costs an ffprobe and a `vidmeta` call each; the spike's timings say how
  much.
- The switches (`SLOMO`, `DOLBY`, `EDITS`, …) are in both actions, and the
  README says to change a line in both. A switch changed in one only does no
  harm: a video is then converted unchecked, with the `!` line, or handed over
  for nothing.

Not chosen: splitting the script into a planning half that saves its job table
for a converting half. It runs every rule once, but it rewrites the script that
"today's path exactly" depends on, and most of its tests.

### 4.4. Pairing, comparing, staging

New inputs of the conversion: `"$@"` (the files, in *Find Photos*' order),
`BRIDGE` (the album script's answer), `RDATES`
(`index|2024-01-01T17:00:00-05:00` lines), as in Compress Photos'
`selection.zsh`, whose pairing code this copies:

- A file and a selected video pair up when their names without extension are
  the same, case aside (Shortcuts names the file after the item: `IMG_0109.mov`
  for `IMG_0109.MOV`), and, if both have a date, the dates are at most a second
  apart. A pair counts only if it is the one candidate on both sides. Only
  videos with an id are paired.

In the loop over the exported files, a video first passes today's checks on its
original, in today's order: ffprobe reads it, this ffmpeg decodes its codec, it
isn't slo-mo, spatial or a log recording. These say what the recording is, so
the original decides them. Then:

| Case                                                              | ffmpeg's input                            | Counted as                                                     |
| ----------------------------------------------------------------- | ----------------------------------------- | -------------------------------------------------------------- |
| paired, `/usr/bin/cmp -s file original` says the same             | the original in `in/` (as today)          | unedited                                                       |
| paired, the files differ, and Photos' version can be read         | `vid_in_N.mov`, a copy of Shortcuts' file | edited                                                         |
| paired, the files differ, and it can't be copied, read or decoded | none                                      | skipped: "edited, and Photos' version can't be converted" (D4) |
| no pair, or `cmp` can't read the file                             | the original (as today)                   | unchecked                                                      |

- The copy is `/bin/cp -c` into the work folder: ffmpeg and ffprobe can't read
  Shortcuts' folder (TCC), Apple's `cp` and `cmp` can, and `-c` makes a clone
  where it can, so an edited video costs no second copy on one volume.
  `finish_script` already removes `vid_*`.
- An edited video is probed again from its copy, and everything the ffmpeg
  command and the checks take from the probe comes from that: size, frame rate
  (the keyframe interval), frame count and duration (the progress, and the
  check that the whole video was written), pixel format, transfer, the Dolby
  Vision record (the VBV rate), the sound track. The original's values are kept
  for the log (4.6).
- The checks that follow, the sound track ffmpeg can read and Dolby Vision it
  can carry, run on the file that is converted. For an unedited video that is
  the original, in the same order as today, so nothing changes for it.
- The free-space check counts the files that will be converted.

### 4.5. Metadata

Nothing new is needed, and nothing shared changes:

- `vidmeta copy` still takes the **original** in `in/`, whatever ffmpeg
  converted: the copy gets the original's date with its time zone, location,
  make, model, software, lens keys and the file times, byte for byte. Photos'
  rendering may carry fewer keys; it doesn't matter.
- The duration, the size and the rotation are the converted file's, so a
  trimmed video's copy is the trimmed length, and a rotated one's is rotated.
- The result lines keep each original's id, so `import.applescript` (unchanged)
  gives the copy the original's date, location, title, caption, keywords (with
  `compr`) and favorite in Photos, adds it to the original's albums, and
  collects the original in *Videos already compressed*. The working album is
  gone by then; if Photos wouldn't delete it, a `!` line says so (from
  `CLOSED`), as in Compress Photos.

### 4.6. The log

Before the first video is converted:

- edited, no `!` (it is what the user asked for):
  `2 edited video(s) are converted as they look in Photos now, from Photos' own version of them (the edit can't be reverted on the copy): IMG_1.MOV, IMG_2.MOV`
- unchecked, some:
  `! could not check 1 video(s) for edits: converted from the original file(s), without edits made in Photos. Play the copies before deleting the originals: IMG_3.MOV`
- no file came at all (`BRIDGE` is empty, `ERROR: ...`, `BRIDGE 0`, or
  `BRIDGE n` without arguments), with videos to convert: one line instead,
  `! could not check the videos for edits (<why>): edited videos are converted from their original files, without the edits. Play the copies before deleting the originals.`
- `EDITS=0`: `Edits made in Photos are not looked for (EDITS=0).`, no `!`.
- skipped:
  `Skipped IMG_4.MOV: edited in Photos, and this ffmpeg can't convert Photos' version of it (<why>)`,
  counted in `vid_skipped.txt` as `1 edited video(s)`.

Each edited video's header says what is converted, and a second line what the
original is:

```
[2/5] IMG_1.MOV  1920×1080 30 fps HLG 10-bit, 85 MB → H.265 medium RF 24, …
  (edited in Photos: this is Photos' version; the original is 3840×2160
  30 fps HLG 10-bit Dolby Vision, 171 MB)
  ! Photos' version has no Dolby Vision
```

The `!` lines of D5: no HDR where the original has it (the transfer), no Dolby
Vision record, 8 bits for 10, no sound track. All `!` lines match `WARNINGS`,
so the log opens.

*Find Photos* failing isn't a log line: Shortcuts stops the run with its own
message ("Photo Album Not Found"), before the conversion. The If on
`^BRIDGE [1-9]` keeps it to the case where the album exists and Shortcuts can't
see it.

### 4.7. Quality of an edited video's copy

The edit exists only as Photos' adjustment data and Photos' rendering of it. A
shortcut can read the second, not the first, so an edited video's copy is made
from a video Apple's encoder already made from the recording (presumably the
Mac's or the iPhone's hardware encoder; not ours to choose). Our decoding and
encoding stay in software, as for every video.

The spike measures what that rendering is (2.2, item 3). Until then nothing
says a different RF is right for it, so D5 leaves the settings alone and makes
the log say what was converted. Its numbers go into the README (how Photos'
version compares with the recording), and D5 is looked at again if they are
bad: a rendering at a fraction of the original's bit rate, or always 8-bit SDR.

### 4.8. What must keep working

| What                                                | Why it holds                                                                                                                                     |
| --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| an unedited video's copy                            | its original is ffmpeg's input whenever `cmp` says the files are the same, and whenever there is no pair; the command and the checks are today's |
| what is skipped                                     | the checks on the original come first and are unchanged; those videos aren't in the album                                                        |
| date, location, camera and lens keys                | `vidmeta copy` from the original                                                                                                                 |
| albums, title, caption, keywords, favorite, `compr` | `import.applescript` unchanged; the result lines keep the ids                                                                                    |
| *Videos already compressed*                         | the same                                                                                                                                         |
| Compress Photos                                     | `lib/` and `shortcuts/compress-photos/` untouched (D1): `git diff --stat main -- lib shortcuts/compress-photos` prints nothing                   |
| software only                                       | the same ffmpeg command, `-hwaccel none`                                                                                                         |
| a run that fails in the tools                       | the planning pass prints no lines, so no album is made, and the conversion writes the same `ERROR:` lines as today                               |

## 5. The spike, first

Nothing here can be run by the agent: its shell may not script Photos. So the
agent builds one diagnostic shortcut and the owner runs it, as for #29, whose
`build/spike29/build_spike.py` (untracked; it may be gone) is the pattern:
`python3 build/spike-video-edits/build_spike.py` writes and signs
`build/spike-video-edits/Compress Videos Spike.shortcut` (signing works from
the agent's Bash tool outside its sandbox). The folder isn't committed. Its
shell scripts are run once with stand-in values in a pretend home folder before
the owner gets it.

### 5.1. What the owner does

One short list:

1. Double-click `build/spike-video-edits/Compress Videos Spike.shortcut` to add
   it.
2. In Photos, duplicate a few short videos that show nothing private (the files
   are copied for the agent to read) and edit the duplicates: trim one; put a
   filter or an adjustment on one; rotate or crop one; and edit one HDR video
   from an iPhone in any way. Select them together with an unedited video, a
   slo-mo, a Live Photo and a photo, and a Cinematic video if there is one.
   Then **Share ▸ Compress Videos Spike**.
3. When it says "Done", or stops with an error, say "done" and what any dialog
   said.

Short clips, half a minute or less: each is copied several times, and this
Mac's disk had 16 GB free on 2026-11-27.

### 5.2. What the shortcut does

It needs the tools of Compress Videos 0.3.0 in `~/.local/bin` (they are on this
Mac). It writes everything to
`~/Library/Caches/compress-videos-macos/spike-edits/<time>/`: `report.txt`,
`times.txt` (a time stamp after each step, and the disk's free space), and the
files. The steps are ordered so that one that fails costs only what comes after
it.

- Run Shell Script: an empty `~/Pictures/.compress-videos-spike-edits` with
  `in/` and `rendered/`, and the run's folder.
- The real `export.applescript` (the originals into `in/`), and
  `spike_info.applescript`: each item's id, filename, date, width, height,
  size, title and favorite.
- Run Shell Script: those results into the report; for each file in `in/` its
  size, ffprobe's streams and format as JSON, and `vidmeta key` (the playback
  intent) and `vidmeta log`; the files cloned into the run's folder. It prints
  the export's lines of the **plain** videos (one video track, 61 fps or less
  on average, not half of a Live Photo) and writes the other videos' lines to
  `odd.txt`.
- **Round A**, the planned flow. The real `bridge.applescript` of 4.2 with the
  plain lines. If `^BRIDGE [1-9]`: *Find Photos* in the album → Renderings; for
  each, its Name, Date Taken (ISO 8601), Width, Height, Media Type, Duration,
  Frame Rate, File Size and File Extension. Run Shell Script (input:
  Renderings, as arguments): the number of arguments; for each, its path and
  size, what ffprobe says of it in place (expected: "Operation not permitted"),
  a clone of it as `foundA/<position>-<name>` with the time that took, `cmp`
  with the `in/` files of the same name without extension, and ffprobe's JSON
  and the two `vidmeta` answers for the clone. Then `spike_album.applescript`
  (the album's ids in its order) and `bridge.applescript` "close".
- **Round B**, the early close: the bridge again with the plain lines, *Find
  Photos*, then "close", and only then a Run Shell Script with the files: how
  many came, and `cmp` of each with round A's clone.
- **Round C**, the other videos, one at a time: Repeat with each line of
  `odd.txt` (a Run Shell Script prints it, Split Text makes the lines): a time
  stamp with the line; the bridge with that line; *Find Photos*; its details,
  asked of the result itself (a Repeat inside a Repeat has an item variable of
  another name, which `lib/wfkit.py` doesn't have); a Run Shell Script with the
  file, as in round A, into `odd/`; "close"; a time stamp. If Shortcuts stops
  here, the report says on which video.
- Last, in `spike_info.applescript`'s second half: Photos' `export` without
  `using originals` of the videos into `rendered/`, in a `try` with a 10-minute
  limit, and how long it took (way A). A Run Shell Script records the files and
  ffprobe's JSON.
- A notification: "Done".

### 5.3. What the agent reads

For every original, every file from Shortcuts and every file of way A:
ffprobe's JSON (container, codec, profile, pixel format, color tags, the Dolby
Vision record, bit rate, duration, frames, frame rates, the rotation, the sound
and data tracks); `tests/compress-videos/avmeta.swift` (Apple's keys with their
types, and whether AVFoundation sees HDR); `exiftool` (dates, GPS); the Dolby
Vision RPUs counted as in the design's 5.1 (Homebrew's ffmpeg). For the trim,
the hashes of its video packets against the original's (Homebrew's ffmpeg,
`-c copy -f framehash`): a copy of the samples, or a new encoding. Then each
file from Shortcuts through the real conversion script in a pretend home
(`video_helpers.Mac`), both codecs, with `vidmeta copy` from its original, and
`avmeta.swift` on the result. If Shortcuts stopped, the unified log around that
time (`/usr/bin/log show`, outside the sandbox).

The results go into section 9. Then the run's folder and the work folder are
deleted; those files are never committed.

### 5.4. Gates

| Gate | Must be true                                                                                                                                                                                                                            | If not                                                                                                                                                                                                                                                                                                                                                                                  |
| ---- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| G1   | Round A: *Find Photos* returns every video put into the album, right after `add`, from the Share menu, and the script gets one file for each, with no dialog that can't be shown                                                        | Only late: a Wait and a second *Find Photos* when the count is short. No videos, or Shortcuts stops on a plain video: B is dead. Stop and report (what is left: C)                                                                                                                                                                                                                      |
| G2   | each unedited video's file is the exported original byte for byte                                                                                                                                                                       | The same samples in another wrapper (the packets of the video and the sound hash the same): tell an edit by those hashes instead of `cmp`, on a clone of each file (ffprobe's `-show_packets -show_data_hash`; our ffmpeg has no hash muxer). Encoded again: nothing tells an edited video from an unedited one. Stop and report                                                        |
| G3   | each edited video's file differs from its original and is the video as Photos shows it (the trim's length, the crop's size, the rotation), and the conversion script converts it with both codecs, with the original's keys on the copy | The file is the original (no rendering is handed over for that kind of edit): stop and report which. Our ffmpeg can't decode it (it decodes H.264, H.265, ProRes and AV1, with AAC, ALAC and PCM sound): add the decoder to the build, or such videos are skipped (D4). Shortcuts stops with an error on an edited video: stop and report; one such video would stop every run it is in |
| G4   | the file's name is the original's without its extension, also for a video with a title, and Date Taken is the AppleScript date to the second                                                                                            | Pair by date and Duration, or by position if the album's order is the order added (it was in #29)                                                                                                                                                                                                                                                                                       |
| G5   | the hand-over (from *Find Photos*' end to the script's start) takes no more than a copy of the files would, and no disk space when the library is on the home volume; `cmp` runs at about 2.4 s per GB                                  | Say in the README what it costs in time and room. If it is much: get Duration and File Size first and fetch the files only of the videos where they differ from the original (a second album round)                                                                                                                                                                                     |
| G6   | Round B: with the album deleted first, the script still gets every file, the same bytes as in round A                                                                                                                                   | Delete the album after the conversion, as Compress Photos does; it then shows in Photos for the whole run, and the README says so                                                                                                                                                                                                                                                       |

Recorded without a gate: what round C gives for each video, or the error and on
which (D3's alternative, D6, the Cinematic row of 2.4); what way A writes;
Shortcuts' Duration, File Size and Frame Rate next to the files'; how Photos'
version compares with the original (D5, 4.7); every dialog.

## 6. Steps

01. `git switch -c 2026-11-27-compress-videos-edits main` (the date the work
    starts; this file is untracked and comes along).
02. `shortcuts/compress-videos/scripts/mac/bridge.applescript` (4.2), with
    `applescript_text` looking in `scripts/mac/` first and `BRIDGE_ALBUM` in
    `build_mac_shortcuts.py`. The spike runs it.
03. The spike (5). Fill in section 9. Stop if a gate fails without a listed way
    out.
04. The decisions of section 3 with the owner, in the light of section 9.
05. `build_mac_shortcuts.py` (4.1): `script_text(phase)` and the new slots, the
    planning action, `renderings()` (the bridge, *Find Photos*, the dates: the
    few lines of Compress Photos' `photo_date`, written here so that `lib/`
    stays as it is), the close, the conversion's input, the first note's text.
06. `common.zsh`, `selection.zsh`, `encode.zsh` (4.3 to 4.6). Keep the header
    comments true.
07. Tests (7). `pre-commit run --all-files`.
08. Docs (8).
09. `VERSION` 0.4.0 and `CHANGELOG.md`, last: the version tests fail until
    `build-macos.sh` has rebuilt the tools (it configures FFmpeg again when
    `VERSION` changes).
10. Build the shortcut (the owner signs, in iTerm2), install it and the tools,
    and run section 10's checks.
11. Commit as
    `Compress Videos 0.4.0: an edited video is converted with its edits`; the
    PR, and the spike's numbers on the issue if there is one (D8).

## 7. Tests

`tests/compress-videos/test_mac_shortcuts.py`:

- The Run AppleScripts are probe, export, bridge, bridge, import, all plain
  text. The first bridge's input is the planning script's output, the second's
  a Text "close", and it comes before the conversion script (G6) and before the
  import.
- Two conversion-script actions: the planning one (`PHASE='plan'`, no input, no
  `encode.zsh`, no reference to Bridge, Dates or Closed) before the bridge, and
  the conversion (`PHASE='convert'`) after; both read the export's lines and
  the six settings. `test_shell_scripts_use_zsh`: the conversion now has an
  input too, the variable Renderings, as arguments.
- One *Find Photos*, its album `gen.BRIDGE_ALBUM`, inside an If on
  `^BRIDGE [1-9]`; the variable Renderings is set there only.
- `test_applescripts_compile`: `bridge` too. Its handler that picks the ids,
  run with `run_handlers` (moved from Compress Photos' test file to
  `tests/shortcut_helpers.py`): a video's line gives its id; the tab lines, an
  `ERROR` line and an empty id give none.
- The note names the album; the version.

`tests/compress-videos/test_mac_script.py` (stand-in tools).
`Mac.convert(renderings=…, bridge=…)` runs the planning pass, then the
conversion with the files as arguments; by default it passes a copy of each
planned video's exported file, kept outside the work folder, with `BRIDGE n`,
so every video is unedited and the existing tests keep their commands and logs:

- the planning pass prints the lines of exactly the videos the conversion
  converts: none for a photo, a Live Photo, a slo-mo, a spatial or log video, a
  codec or sound this ffmpeg can't read, a name two items share; none with
  `EDITS=0`, with a missing tool or with too little room; and it writes no
  settings file and opens no window;
- unedited: ffmpeg's input is `in/NAME` and the command is `expected()`'s, as
  before;
- edited (a file with other bytes): ffmpeg's input is `vid_in_1.mov`, a file in
  the work folder, not a link; the command follows the rendering's probe (size
  and VBV rate, frame rate and keyframe interval, sound track, Dolby Vision);
  `vidmeta copy` gets the original; the result line has the original's id and
  `NAME.mp4`; the log has the "edited" line and the header's second line;
- a trimmed rendering (2 s for a 5 s original) passes the duration check, and a
  copy shorter than the rendering fails it;
- the `!` lines of D5, one case each;
- edited and unusable (ffprobe can't read the copy; a codec not decoded; sound
  that can't be read; Dolby Vision that can't be carried): skipped, counted, no
  result line;
- unchecked: no file for the video; two files with its name and date; a date an
  hour off; a file that can't be read (a folder). Each converts the original
  and prints the `!` line with the names;
- names as Shortcuts may give them (`IMG_0001.mov`, `IMG_0001`,
  `img_0001.MOV`); `IMG_1.MOV` and `IMG_1.MP4` with different dates pair by
  date;
- no files at all, for each answer of the album script: one `!` line, the
  results as today; `EDITS=0`: the plain line;
- the free-space check and the finish script with a staged rendering.

The tests' files live in an ordinary folder: they can't show that ffmpeg is
refused Shortcuts' folder. Section 10 does.

`tests/compress-videos/test_conversion.py` (the real tools): an original
(`hlg`) with a rendering `make_video.swift` writes with other options (shorter,
another size, rotated; one in SDR), through both passes. ffprobe finds the
rendering's duration, size, rotation and transfer in the copy; `avmeta.swift`
finds every key of the original, with its type, and the original's dates.

Run on the Mac: `python3 -m pytest tests/compress-videos`, then `tox -e tests`.
`tests/README.md`: the rows of the two files.

## 8. Docs, version, changelog

- `shortcuts/compress-videos/VERSION`: 0.4.0. `CHANGELOG.md`, dated the day it
  merges, `## [Compress Videos 0.4.0] - YYYY-MM-DD`, *Changed*: a video edited
  in Photos (trimmed, with a filter or adjustments, rotated, cropped) is
  converted as it looks there now, where before the recording was converted and
  deleting the original lost the edit; the edit is in the copy and can't be
  reverted there; what Photos' version keeps of HDR and Dolby Vision, from the
  spike; the copy still gets its original's date, location, camera and lens,
  albums, title, caption, keywords and favorite; unedited videos are converted
  as before; the album *Compress Videos (working)* shows for a moment;
  Shortcuts needs access to the photo library (it may ask once); the
  `! could not check ... for edits` line and `EDITS=0`. What to update: the
  shortcut and `vidmeta-macos` together (it carries the version, which the
  shortcut checks); `ffmpeg-macos` and `ffprobe-macos` only change their
  version line.
- `shortcuts/compress-videos/README.md`: 1, step 4 (Shortcuts' access to the
  photo library); 2 (the sentence on re-rendered copies is about the Share
  menu's own input and the picker); 2.2 (the working album; an edited video;
  the room and time the check takes, from G5); 3 (move "edits" from *Not kept*
  to *Kept*, with what an edited video's copy is made from and the spike's
  numbers; the Cinematic line as the spike finds it; `SLOMO=0` and `EDITS=0`
  are changed in both Run Shell Script actions); 6 ("Photo Album Not Found";
  the `! could not check` line).
- `shortcuts/compress-videos/DEVELOPING.md`: the flow in 1; a new "1.4. Edited
  videos" with the facts of 2.1 and section 9 (what Shortcuts hands over, why a
  copy and `cmp`, the two passes, what the tests can't show); 1.3 (what is
  skipped never reaches Shortcuts); the layout table (`bridge.applescript`).
- `docs/compress-videos-mac-design.md`: one item in the list at its top, with a
  link here (its 3.3 and 3.4 say the recording is converted).
- `tests/README.md`. Nothing in Compress Photos' docs or `AGENTS.md` changes.

## 9. Spike results

To fill in at step 3: one row per video (the original; Shortcuts' file; `cmp`;
way A's file), what Photos' version of each edit is (2.2, item 3), the timings
and the disk space, round C video by video, the dialogs, and each gate's
result.

## 10. Checks on the Mac, by the owner

With the built shortcut and tools, from Photos' Share menu:

- a trimmed video, one with a filter, a rotated or cropped one, an edited HDR
  one, an unedited one, a slo-mo, a Live Photo and a photo in one selection,
  the videos in an album and one with a title, caption, keyword and favorite,
  with each codec: the copies play as the videos do in Photos (length, look,
  orientation, HDR), are in the album with that metadata and the original's
  date and place; the originals are in *Videos already compressed*; the slo-mo,
  the Live Photo and the photo are skipped as before;
  `Compress Videos (working)` is gone;
- the log names the edited videos, says what Photos' version of each is, and
  shows no "Operation not permitted";
- the unedited video's ffmpeg command in the log is the one 0.3.0 printed for
  it with the same settings;
- twenty videos: the time from the export's end to the first progress line;
- Photos access for Shortcuts turned off in System Settings: what the run
  shows, and that nothing is converted or collected; the next run deletes the
  album;
- `EDITS=0` in both actions: no album appears, and the edited videos are
  converted from their recordings.
