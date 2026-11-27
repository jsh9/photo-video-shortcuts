# Compress Photos 0.12.0: the Mac's selection route converts an edited photo with its edits

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. The problem](#1-the-problem)
- [2. What is known](#2-what-is-known)
- [3. Decisions](#3-decisions)
- [4. Design](#4-design)
  - [4.1. The flow](#41-the-flow)
  - [4.2. `bridge.applescript`](#42-bridgeapplescript)
  - [4.3. Find Photos in `lib/wfkit.py`](#43-find-photos-in-libwfkitpy)
  - [4.4. `selection.zsh`](#44-selectionzsh)
  - [4.5. The log](#45-the-log)
  - [4.6. What must keep working](#46-what-must-keep-working)
- [5. The spike, first](#5-the-spike-first)
- [6. Steps](#6-steps)
- [7. Tests](#7-tests)
- [8. Docs, version, changelog](#8-docs-version-changelog)
- [9. Spike results](#9-spike-results)
- [10. Checks on the Mac, by the owner](#10-checks-on-the-mac-by-the-owner)

______________________________________________________________________

<!--TOC-->

Plan for issue #29, written 2026-11-26. Nothing is built yet. Section 5 (the
spike) comes first and can change the design: read its gates before writing
code.

## 1. The problem

On the Mac, *Compress Photos (macOS)* started from Photos (the "selection
route") has `lib/mac/export.applescript` export each item
`with using originals`: the file as it was recorded or imported. An edit made
in Photos (exposure, a style, a rotation, a crop) isn't in the copy, and
deleting the original from the album *Compressed originals* loses the edit.

Every other route converts the edited rendering: the iPhone's share sheet and
picker, and the Mac's picker route. But only the selection route gives the copy
its original's title, caption, keywords and favorite (#21), so today the user
chooses between the edits and that metadata.

Goal: from the selection route, an edited photo's copy looks as the photo does
in Photos now, the edit baked into the pixels (not revertible, as on the other
routes). An unedited photo keeps today's path: its original file, its HDR and
Apple's HDR profile.

## 2. What is known

Found on 2026-11-26 without running Photos: files of macOS 27.0 (build 26A428),
and Shortcuts' ContentKit decompiled from iOS 18.2 (GitHub,
`EthanArbuckle/iPhone17-1_18.2_22C152_Restore`,
`System/Library/PrivateFrameworks/ContentKit.framework`).

| Fact                                                                                                                                                                                                                                                                                                                                                                                                 | Source                                                                                      |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `export` without `using originals` writes "rendered jpgs". Measured on macOS 26 (2026-10-04): a 15 MB JPEG for a 24 MP photo. So option A of the issue means 8 bits and a second lossy encoding, whatever else the spike finds.                                                                                                                                                                      | `Photos.sdef`, the `using originals` parameter's description                                |
| A media item has no "edited" property: `keywords`, `name`, `description`, `favorite`, `date`, `id`, `height`, `width`, `filename`, `altitude`, `size`, `location`. Albums can be made and deleted (`make`, `delete`), items added (`add`), not removed.                                                                                                                                              | `Photos.sdef`                                                                               |
| Photos' own Shortcuts actions can't fetch a photo by id, and none returns the selection: `AssetEntityQuery` has no parameters and no sort options (so no "Find ... where"), and `AssetEntity` has no id or edited property (`hasSuggestedEdits` is something else).                                                                                                                                  | `PhotosUICore.framework/Resources/Metadata.appintents/extract.actionsdata`                  |
| The file Shortcuts makes of a library photo is one of Photos' stored resources, byte for byte: the first of type 5 or 6 (`PHAssetResourceTypeFullSizePhoto`, `FullSizeVideo`: the rendering Photos saved with the edit) that has the type asked for, else the last resource that has it (the original). So an edited photo comes as Photos' own rendering, and an unedited one as its original file. | `-[WFPhotoMediaContentItem preferredAssetResourceForType:]`, `generateFileRepresentation:…` |
| *Find Photos* with an Album condition fetches exactly that album's items (`+[PHAsset fetchAssetsInAssetCollection:options:]`, "Performing optimized photo lookup for album"), as library photos.                                                                                                                                                                                                     | `+[WFPhotoLibraryFiltering performCustomFilteringUsingContentPredicates:…]`                 |
| How the Shortcuts app writes a *Find Photos* / *Filter Photos* action (`is.workflow.actions.filter.photos`, `WFContentItemFilter`, `WFContentPredicateTableTemplate`).                                                                                                                                                                                                                               | `filter_photos` in commit 6d60078 (0.3.0), removed in 0.3.1                                 |
| On the Mac's picker route Shortcuts hands over an edited HDR photo as a HEIC with HDR (tested by the owner).                                                                                                                                                                                                                                                                                         | issue #29                                                                                   |
| `photobatch` already converts Photos' renderings: an unlabeled ISO gain map on an upright, uncropped photo is used (HDR kept, `! Apple's HDR profile not found`), and the orientation check skips a photo whose EXIF size is from before the edit. It reads the format from the file's content (`detect_format`), not its name.                                                                      | `DEVELOPING.md` 1 and 1.3, `fixtures/hdr/edited_in_photos.heic`, `test_orientation.py`      |
| `media item id X` is immediate; one call into Photos costs about 17 ms; a Run AppleScript with a Shortcuts variable in its text doesn't compile.                                                                                                                                                                                                                                                     | `DEVELOPING.md` 1.1                                                                         |

What this rules out and in:

- **Option A** (export the rendering with AppleScript): always a JPEG. Not
  used. The spike still records what that JPEG holds, to close the issue's
  question.
- **Option B** (the rendering through Shortcuts): no action takes an id, but an
  album is an exact bridge. AppleScript puts the selected items into a
  temporary album by id, and *Find Photos* gets that album's items as library
  photos, whose files are Photos' own renderings. This is the plan.
- **Option C** (a PhotoKit helper that keeps the edit revertible): later, as
  the issue says.

No property says "edited", and none is needed: for an unedited photo Shortcuts'
file is the original, so the script compares the two files byte for byte
(`cmp`). The same: unedited, today's path. Different: edited, the rendering is
converted.

## 3. Decisions

Settled here, with the alternative the owner may prefer. D1 to D3 don't block
the work; say so before step 4 if another choice is wanted.

- **D1. No new question.** An edited photo is always converted as it looks now,
  as on the iPhone and the picker route. (Alternative: a fifth menu, "Edited
  photos: as they look now / unedited originals".)
- **D2. A photo that can't be checked is converted from its original, with a
  `!` line, and its original is still collected.** This is what the Mac route
  does for a copy that lost its HDR: everything goes to the review album and
  the log, which opens when it has a `!` line, says what to keep. If the bridge
  script fails, the route works as it does today, with one `!` line. *Find
  Photos* failing is another matter: Shortcuts has no try, so it stops the run
  with its own error (see 4.5). (Alternative: don't collect such originals.
  That needs a new field in `import.applescript`'s plan lines; the script is
  shared, so Compress Videos would need a version too.)
- **D3. Version 0.12.0**, Compress Photos only. `lib/mac/export.applescript`
  and `lib/mac/import.applescript` stay byte for byte as they are, so Compress
  Videos ships nothing new.
- **D4. The bridge is a top-level album named `Compress Photos (working)`**,
  made at the start of a run and deleted before the import. A run that dies
  leaves it; the next run deletes it first. Deleting an album deletes no photo.
- **D5. The copy keeps its original's name** (`IMG_1234.HEIC` gives
  `IMG_1234.jxl`), whatever the rendering's file is called.
- **D6. Compress Videos is out of scope** (its export is `using originals`
  too). File an issue for it once this works; the bridge would serve it
  unchanged.

## 4. Design

### 4.1. The flow

The selection route in `build_mac_shortcuts.py` (`selection_route`), new steps
marked `+`:

```
  the format, quality, cores and HDR questions; the notification
  Run Shell Script: an empty ~/Pictures/.compress-photos-macos/in
  Run AppleScript export.applescript → IDS (unchanged)
+ Run AppleScript bridge.applescript (input: IDS) → variable Bridge,
+    "BRIDGE n" or "ERROR: ..."
+ If it matches ^BRIDGE [1-9]:
+    Find Photos where Album is "Compress Photos (working)" → variable
+    Renderings
+    Repeat with each: its Date Taken, as "index|ISO 8601" → variable Dates
+    (wf.photo_date)
  Run Shell Script common.zsh + selection.zsh
+    input: Renderings, as arguments; BRIDGE and RDATES in heredocs
+ Run AppleScript bridge.applescript (input: the text "close"): deletes the
+ album
  Run AppleScript import.applescript (unchanged)
  the log in Quick Look if it has a note; finish; the notification
```

The album is deleted before the import on purpose: the import adds each copy to
every album its original is in, and the originals are in the bridge album.

### 4.2. `bridge.applescript`

New file `shortcuts/compress-photos/scripts/mac/bridge.applescript` (only
Compress Photos uses it; `applescript_text` in `build_mac_shortcuts.py` looks
in `scripts/mac/` first, then `lib/mac/`, and fills in `@BRIDGE_ALBUM@` like
`@ORIGINALS_ALBUM@`). Plain text, values through `input`, the whole body in
`try` returning `ERROR: ...`, `with timeout of 3600 seconds`, as in
`export.applescript`.

- Input "close": deletes each album whose name is `@BRIDGE_ALBUM@`, returns
  `CLOSED`.
- Otherwise the input is IDS (text, or a file holding it: copy `planText` from
  `import.applescript`). It deletes any album of that name, makes a new one,
  and for each `id|date|filename` line (two `|`; the tab lines are skipped)
  whose filename doesn't end in `mov`, `mp4` or `m4v`, adds `media item id X`
  to a list, each in a `try`. One `add theList to theAlbum`. Returns
  `BRIDGE n`, n the items the album then holds. Nothing to add: no album,
  `BRIDGE 0`.

Videos stay out so that Shortcuts never copies a video file for nothing. A Live
Photo can't be told from a still here; its still comes as a small file and
`selection.zsh` skips it as today.

### 4.3. Find Photos in `lib/wfkit.py`

`Builder.find_photos_in_album(name)`: `is.workflow.actions.filter.photos`
without `WFContentItemInputParameter`, one template (`Property` `Album`,
`Operator` 4, `Removable` true, `Values.Enumeration` a
`WFStringSubstitutableState` with the name, `Unit` 4),
`WFActionParameterFilterPrefix` 1, `WFContentPredicateBoundedDate` false, no
sort, no limit; returns `output_of(a, 'Photos')`. The format is commit
6d60078's `filter_photos`, which the Shortcuts app wrote; the spike ran it on
macOS 27 (G1).

### 4.4. `selection.zsh`

New inputs: `"$@"` (the renderings, in *Find Photos*' order), and two heredocs
like `photos.zsh`'s: `BRIDGE` (the variable Bridge; the tests fill text by
output name, and the export's and the bridge's are both "AppleScript Result")
and `RDATES` (`index|2024-01-01T17:00:00-05:00` lines). New slot in `SLOTS`:
`@BRIDGE@`; `@DATES@` exists. (`RNAMES` was dropped after the spike: the files'
own names are the originals' with Shortcuts' extension, and Get Name might give
a title.)

Pairing a rendering with a selected photo, before the staging loop:

- The stem of a name is the name without its last extension, compared without
  case; a rendering's is its file's.
- A rendering and a selected photo pair up when their stems are the same and,
  if both have a date, the dates are within one second. `RDATES` is on the
  Mac's clock like IDS' dates: `${iso[1,10]} ${iso[12,19]}` and the IDS date
  both through zsh's `strftime -r` (seconds).
- Only originals `photobatch` reads (HEIF, JPEG, PNG, JPEG XL) are paired. A
  RAW's rendering never takes its place: the RAW would fail as before instead
  of its original being collected for deletion.
- A pair counts only if it is the one candidate on both sides. Anything else is
  **unchecked**. A name two selected photos share already has no id; it is
  unchecked too.

In the staging loop, for a still photo `f` with job index `n` (the job's name
stays `f`'s, D5):

| Case                                 | Staged as `jxl_in_n.orig` | Counted as |
| ------------------------------------ | ------------------------- | ---------- |
| paired, `cmp -s rendering f` is true | `f` (as today)            | unedited   |
| paired, the files differ             | the rendering (`${r:A}`)  | edited     |
| no pair                              | `f` (as today)            | unchecked  |

`jxl_dates.txt` and `jxl_meta.txt` are written by job index from IDS as today,
so an edited photo's copy still gets Photos' date and location, whatever the
rendering's EXIF holds. The result lines and the work folder's cleanup don't
change (`finish_script` already removes `jxl_*`).

### 4.5. The log

Printed before `photobatch` runs:

- edited, no `!` (it is what the user asked for):
  `2 edited photo(s) are converted as they look in Photos now (the edit can't be reverted on the copy): IMG_1.HEIC, IMG_2.HEIC`
- unchecked, some:
  `! could not check 1 photo(s) for edits: converted from the original file(s), without edits made in Photos. Look at the copies before deleting the originals: IMG_3.HEIC`
- the bridge failed (`BRIDGE` is empty or `ERROR: ...`, or it is `BRIDGE n`
  with n above 0 and no rendering came): one line instead,
  `! could not check the photos for edits (<the bridge's answer, or "Shortcuts found no photos in the album Compress Photos (working)">): edited photos are converted from their original files, without the edits. Look at the copies before deleting the originals.`
- `BRIDGE 0` (only videos were selected): nothing to check, no line.

Both `!` lines match `WARNINGS`, so the log opens.

*Find Photos* fails when the album isn't found
(`The “Find Photos” action couldn’t find the album “…”.`; ContentKit looks only
at user albums, and only when Shortcuts has full library access:
`+[WFPhotoMediaContentItem photoAlbums]` returns nothing otherwise), and
Shortcuts then stops the run with that message: nothing is converted or
imported, no original is collected, and the album stays until the next run. The
If on `^BRIDGE [1-9]` makes this happen only when the album exists, so it
should come down to Shortcuts lacking access to Photos. The spike records what
the user sees then (G1); if it is unclear, put a notification before *Find
Photos* that says what to allow, or ask for access another way first.

### 4.6. What must keep working

| From the issue                    | Why it holds                                                                                                                           |
| --------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| dates (#18), location, #21        | `export.applescript` and `import.applescript` don't change; `jxl_dates.txt` and `jxl_meta.txt` go by job index, not by the staged file |
| the album *Compressed originals*  | the result lines keep each original's id                                                                                               |
| the check after import            | `import.applescript` unchanged; the bridge album is gone before it runs                                                                |
| the orientation check             | `photobatch` unchanged; a test stages the edited fixture through the route (7)                                                         |
| WASM and macOS write the same     | no encoder change; `test_macos_encoder_output_identical_to_wasm` already has `edited_in_photos.heic`                                   |
| unedited photos keep today's path | the original is staged whenever `cmp` says the files are the same, and whenever there is no pair                                       |

New for the user: the route now needs Shortcuts' own access to Photos (*Find
Photos*), which until now only the picker route needed. macOS asks once.

## 5. The spike, first

Nothing here can be run by the agent: its shell may not script Photos. So the
agent builds one diagnostic shortcut and the owner runs it. Built 2026-11-26:
`python3 build/spike29/build_spike.py` writes and signs
`build/spike29/Compress Photos Spike 29.shortcut` (signing works from the
agent's Bash tool outside its sandbox, which hides the iCloud account). Its
shell scripts were run once with stand-in values in a fake home folder. Give
the owner one short list:

1. Double-click `build/spike29/Compress Photos Spike 29.shortcut` to add it.
2. In Photos, select these and run it from **Share ▸ Compress Photos Spike
   29**: an unedited iPhone HEIC (HDR), the same kind with an exposure edit,
   one with a style, a rotated one, a cropped one, an unedited Portrait photo,
   a JPEG, a PNG screenshot, a photo with a title, a Live Photo, a video, and a
   RAW or an old edited photo if there is one. No photo whose content is
   private: the files are copied for the agent to read.
3. Run it again from the Shortcuts app (double-click it) with the photos still
   selected; if the Share run showed an error, run it from the Share menu once
   more. Then say "done", and what any dialog or error said.

The shortcut (`build/spike29/`, not committed: `build_spike.py`,
`spike_info.applescript`, `spike_album.applescript`) runs the real
`export.applescript` and `bridge.applescript`:

- Run Shell Script: an empty `~/Pictures/.compress-photos-spike29` with `in/`
  and `rendered/`, and the run's folder
  `~/Library/Caches/compress-photos-macos/spike29/<time>/`; `times.txt` there
  gets a time stamp after each step.
- `export.applescript` (originals into `in/`); `spike_info.applescript`: each
  item's id, filename, date, width, height, size, title and favorite, and the
  rendered export of the items that aren't videos into `rendered/` (option A);
  `bridge.applescript` with the export's lines.
- Run Shell Script: those three results into `report.txt`; `in/` and
  `rendered/` copied (videos listed, not copied).
- If `^BRIDGE [1-9]`: *Find Photos* in the album → Renderings; for each, its
  Name, Date Taken (ISO), Width, Height and Media Type.
- Run Shell Script (input: Renderings, as arguments): those lines, the number
  of arguments, each argument copied as `found/<position>-<name>`, its path,
  size and `cmp` with the `in/` files of the same stem.
- `spike_album.applescript`: the album's ids in its order; `bridge.applescript`
  "close"; both into the report.
- Run Shell Script whose input is a variable set only in a branch not taken:
  appends a line saying it ran, with how many arguments.

The agent then reads the folder: `photobatch --mac` on all three sets (its log
says HDR, gain map, profile, orientation check), and
`tests/compress-photos/imageio_props.swift` for format, depth, size,
orientation, date and GPS. Record the results in section 9 of this document,
then delete the folder; never commit those files.

Gates:

| Gate | Must be true                                                                                                                                                                                      | If not                                                                                                                                                                                |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| G1   | *Find Photos* returns every still in the album right after `add`, from the Share menu and from the Shortcuts app, with no dialog that can't be shown (note what the user sees when it fails, 4.5) | Only late: a Wait and a second *Find Photos* when the count is short. Not from the Share menu at all: stop and report; option B is dead there (candidates: a PhotoKit helper, C-lite) |
| G2   | for an unedited HEIC, JPEG and PNG, Shortcuts' file is the exported original byte for byte                                                                                                        | `cmp` can't tell edited from unedited: stop and report (candidate: every photo through Shortcuts' file, as the picker route does)                                                     |
| G3   | for each edited photo, Shortcuts' file is Photos' rendering, and `photobatch` keeps its HDR (`! Apple's HDR profile not found` is expected)                                                       | stop and report what the file is                                                                                                                                                      |
| G4   | Shortcuts' Name is the filename's stem (also for the titled and the edited photo), and Date Taken is the AppleScript date to the second                                                           | pair by date and pixel size, or by position if the album's order was the order added in both runs                                                                                     |
| G5   | deleting the album asks nothing and takes well under a second; a Run Shell Script with an unset input variable still runs                                                                         | album: keep it and say so in the README. Input: set Renderings to an empty Text in the other branch, or two script actions                                                            |

Also record, without a gate: whether the unedited Portrait photo has a
rendering (then it counts as edited, and its copy has the blur Photos shows:
say so in the README); what the RAW gives; what option A's JPEG holds (depth,
gain map, EXIF date and GPS), for the issue.

## 6. Steps

01. `git switch -c 2026-11-26-mac-selection-edits main` (this file is untracked
    and comes along; the stack-photos branch is not the base).
02. `lib/wfkit.py`: `find_photos_in_album` (4.3), with a test of its
    parameters.
03. The spike (5). Fill in section 9. Stop if a gate fails without a listed way
    out.
04. `bridge.applescript` (4.2); `applescript_text(name, folder=LIB_MAC)`,
    `BRIDGE_ALBUM` in `build_mac_shortcuts.py`.
05. `selection_route` (4.1): the new actions, `script()` with the new slots and
    the script's `input_ref`.
06. `selection.zsh` (4.4, 4.5). Keep the header comment true.
07. Tests (7). `pre-commit run --all-files`.
08. Docs, `VERSION` 0.12.0, `CHANGELOG.md` (8). Bump last: the version tests
    fail until every encoder is rebuilt (`build-native.sh`, `build-macos.sh`,
    `build-wasm.sh`).
09. Build the shortcuts (the owner signs in iTerm2) and run section 10's
    checks.
10. Commit as
    `Compress Photos 0.12.0: from Photos on the Mac, an edited photo is converted with its edits`;
    PR that closes #29. Comment on the issue with the spike's numbers.

## 7. Tests

`tests/compress-photos/test_mac_shortcuts.py`:

- `test_photos_selection_route_through_applescript`: the Run AppleScripts are
  probe, export, bridge, bridge, import, all plain text; the first bridge's
  input is the export's result, the second's a Text "close"; the second bridge
  comes after the selection script and before the import.
- New: one *Find Photos* in the selection route, its album `gen.BRIDGE_ALBUM`,
  inside an If on `^BRIDGE [1-9]`; the selection script's `Input` is the
  variable Renderings with `InputMode` `as arguments`; the picker route has no
  *Find Photos*.
- `test_applescripts_compile`: `bridge` too. With `run_handlers`: the handler
  that picks the ids from IDS (a video's line and the tab lines give none) and
  `planText`.
- A test that `lib/mac/export.applescript` and `import.applescript` are what
  Compress Videos embeds (so a later edit to them is noticed as a Videos
  change), if none exists.

`tests/compress-photos/test_mac_script.py` (`Mac.scripts` gets `bridge`,
`rnames`; `Mac.batch('selection', *renderings, …)` passes the files):

- unedited: the rendering is a copy of the exported file → `jxl_in_1.orig`
  points into `in/`, no note.
- edited: `hdr/o1.heic` exported, `hdr/edited_in_photos.heic` as its rendering
  → the rendering is staged, the result line has the original's id and
  `IMG_0001.jxl`, the log has the "edited" line, no `saved as SDR`, no
  `! orientation check`; also with `--heic`.
- a JPEG rendering of a HEIC original converts under the original's name.
- names as Shortcuts may give them: `IMG_0001`, `IMG_0001.HEIC`,
  `img_0001.heic`.
- unchecked: a rendering missing; two renderings with one stem and date; a stem
  that matches but a date an hour off; two selected photos with one name. Each
  converts the original and prints the `!` line with the names.
- same stem, different dates (`IMG_1.HEIC` and `IMG_1.JPG`): paired by date.
- the bridge failed: `BRIDGE` is `ERROR: …`, no arguments → one `!` line, the
  results as today.
- the existing selection tests keep their logs: by default the harness passes a
  copy of each exported still as its rendering (so every photo is unedited),
  with `BRIDGE n`.
- a Live Photo's still and a video: skipped as today, renderings or not.
- dates and locations still reach `jxl_dates.txt` and `jxl_meta.txt` for an
  edited photo.

Run on the Mac:
`python3 -m pytest tests/compress-photos/test_mac_shortcuts.py tests/compress-photos/test_mac_script.py tests/compress-videos`,
then `tox -e tests`. On this Mac 18 `test_xmp` pixel cases per build fail on
`main` too.

## 8. Docs, version, changelog

- `shortcuts/compress-photos/VERSION`: 0.12.0. `CHANGELOG.md`, dated the day it
  merges: *Changed*, from Photos on the Mac an edited photo is converted as it
  looks now (HDR kept, without Apple's HDR profile, as on the iPhone; the copy
  keeps the original's albums, title, caption, keywords, favorite, date and
  location); the album `Compress Photos (working)` shows during a run; the
  first run asks for Shortcuts' access to Photos. What to update: on the Mac
  the shortcuts and `photobatch` (the version check warns otherwise); the
  iPhone shortcuts and encoder do the same as 0.11.0.
- `README-mac.md` 3.1: replace "An **edited photo** is converted from its
  unedited original…" with what happens now, the access question, the working
  album, the unchecked note, and Portrait photos if the spike says so. Section
  4: both routes now convert an edited photo as it looks.
- `README.md` 3, *Edits*: the Mac's selection too.
- `DEVELOPING.md` 1.1: the flow (the bridge, *Find Photos*, the pairing and
  `cmp`), what the Mac shortcuts rely on (the album bridge, the resource
  Shortcuts picks), and the layout table (`scripts/mac/bridge.applescript`).
- `lib/mac/export.applescript`: its comment stays true (the export itself is
  still the originals); don't touch the file (D3).
- `docs/compress-photos-mac-design.md` and `tests/README.md`: where they say
  the selection route converts the unedited original, or list the Mac tests.
- `shortcuts/compress-videos/README.md` keeps its "edits" limit (D6).

## 9. Spike results

One run, 2026-11-27, macOS 27.0, from Photos' Share menu (the unified log:
`runSource: action_extension`), with photos already allowed for Shortcuts (no
dialog). The second run, from the Shortcuts app, wasn't made; the Share menu is
the harder case. Nine items: eight stills and a video.

| Photo         | Original (`using originals`)       | Shortcuts' file                            | `cmp`  | Option A (rendered export) |
| ------------- | ---------------------------------- | ------------------------------------------ | ------ | -------------------------- |
| IMG_1319.HEIC | HEIC (Live Photo, with its `.mov`) | `IMG_1319.heic`                            | same   | JPEG, 18.3 MB              |
| IMG_1711.JPG  | JPEG 4284x5712                     | `IMG_1711.jpeg`                            | same   | JPEG, 17.0 MB              |
| IMG_1721.jpeg | JPEG 1206x2622                     | `IMG_1721.jpeg`                            | same   | JPEG, 0.6 MB               |
| IMG_1922.HEIC | HEIC 5712x4284, orientation 6      | `IMG_1922.heic`                            | same   | JPEG, 21.2 MB              |
| IMG_1818.HEIC | HEIC 5712x4284, HDR 5.2×           | HEIC 5712x4284, HDR 1.3× (an adjustment)   | differ | JPEG, 14.7 MB              |
| IMG_1819.HEIC | HEIC 5712x4284, orientation 3      | HEIC 5712x4284 upright, HDR 3.4×           | differ | JPEG, 19.3 MB              |
| IMG_1869.HEIC | HEIC 5712x4284, orientation 1      | HEIC 4284x5712 upright (rotated), HDR 4.7× | differ | JPEG, 17.8 MB              |
| IMG_1880.HEIC | HEIC 5712x4284                     | HEIC 1031x670 (cropped), HDR 3.4×          | differ | JPEG, 0.7 MB               |
| IMG_1883.MOV  | video                              | not in the album (videos stay out)         |        | not exported               |

- Every rendering keeps the original's EXIF date, offset, GPS and maker notes'
  HDR tags (exiftool). `photobatch` 0.11.0 (macOS build) converts each with its
  HDR, as JPEG XL (`! Apple's HDR profile not found` for the four renderings
  only) and as HEIC (`HDR kept`), with no orientation warning.
- Option A: 8-bit JPEGs, 0.6 to 21 MB, 5 s for eight items. Not used.
- Shortcuts' Name is the stem (`IMG_1319`), Date Taken Photos' AppleScript date
  to the second; Find Photos' order is the album's, which is the order added.
- Timings, with each action's overhead: the export 0.7 s, the bridge 0.28 s,
  Find Photos 0.25 s, Get Details of eight 0.07 s, deleting the album 0.08 s.
- First real run of 0.12.0 (2026-11-27): the four edited photos failed with
  `cannot read jxl_in_N.orig (Operation not permitted)`: TCC
  (`kTCCServiceSystemPolicyAppDataDetailed`) refuses `photobatch` the files in
  Shortcuts' group container; the spike had read them with `cp`. Fixed by
  copying an edited photo's rendering into the work folder. Nothing was
  collected for them (`collected=3`).
- G1 to G5 pass. Not covered: a PNG, a Portrait photo, a style, a RAW, a titled
  photo, and a first run without library access (what the user sees when Find
  Photos fails).

## 10. Checks on the Mac, by the owner

With the built shortcuts, from Photos' Share menu:

- an edited HDR photo (exposure), a rotated one, a cropped one, an unedited
  one, a Live Photo, in an album, one with a title, caption, keyword and
  favorite, both formats: the copies look like the photos in Photos, are in the
  album with the metadata, the originals are in *Compressed originals*, and
  `Compress Photos (working)` is gone;
- the log names the edited photos and has no `! orientation check`;
- the unedited photo's copy is byte for byte the one 0.11.0 makes (same
  settings);
- 100 photos: the time the bridge and *Find Photos* add;
- Photos access for Shortcuts turned off in System Settings: the `!` line, and
  the copies as today.
