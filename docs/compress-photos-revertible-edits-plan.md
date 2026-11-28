# Compress Photos 0.13.0: from Photos on the Mac, an edited photo's HEIC copy keeps its edit

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. Review of the approach](#1-review-of-the-approach)
  - [1.1. What stands](#11-what-stands)
  - [1.2. What to change](#12-what-to-change)
- [2. Decisions for the owner](#2-decisions-for-the-owner)
- [3. Design](#3-design)
  - [3.1. What the copy is](#31-what-the-copy-is)
  - [3.2. Which edited photos keep their edit](#32-which-edited-photos-keep-their-edit)
  - [3.3. The helper](#33-the-helper)
  - [3.4. The flow](#34-the-flow)
  - [3.5. The log, and falling back](#35-the-log-and-falling-back)
  - [3.6. What must keep working](#36-what-must-keep-working)
- [4. Implementation, file by file](#4-implementation-file-by-file)
  - [4.1. `src/photoedits/main.swift` and `Info.plist`](#41-srcphotoeditsmainswift-and-infoplist)
  - [4.2. `scripts/build-helper.sh`, signing, installing](#42-scriptsbuild-helpersh-signing-installing)
  - [4.3. `scripts/mac/selection.zsh`](#43-scriptsmacselectionzsh)
  - [4.4. `scripts/build_mac_shortcuts.py` and `lib/wfkit.py`](#44-scriptsbuild_mac_shortcutspy-and-libwfkitpy)
  - [4.5. `lib/mac/import.applescript`, and Compress Videos](#45-libmacimportapplescript-and-compress-videos)
  - [4.6. `release.json`, `scripts/release.py`, CI](#46-releasejson--scriptsreleasepy-ci)
  - [4.7. Steps](#47-steps)
- [5. Tests](#5-tests)
- [6. Docs, versions, changelog](#6-docs-versions-changelog)
- [7. The owner's test](#7-the-owners-test)
- [8. What stays unknown, and how it fails safe](#8-what-stays-unknown-and-how-it-fails-safe)
- [9. Facts](#9-facts)

______________________________________________________________________

<!--TOC-->

**What was built (0.13.0, 2026-11-27).** A prototype came first, which the
owner tested with the real shortcut; it changed three decisions below:

- **D1 changed:** JPEG XL copies keep their edits too, as a JPEG XL original
  with a HEIC look (G5). Ordinary edits (crop, rotation, exposure) reverted
  fully on the owner's HEIC and JPEG XL copies.
- **D4 changed:** Portrait photos and Photographic Styles keep their edits.
  `photobatch` now keeps every auxiliary image of the picture (depth, mattes,
  the style-delta image, the linear thumbnail) and the `uri ` item
  `tag:apple.com,2023:photo:metadata:styles`; with those, the owner could
  adjust a Portrait's depth and a Style again on HEIC copies (without the
  `uri ` item Photos showed the Style as a filter). JPEG XL copies revert, but
  can't adjust them; the owner found that good enough. So the helper refuses
  only edits by other apps (and records it can't use), and tries every edit
  Photos made itself, with a note for parts not seen working (Clean Up,
  Retouch, unknown ones).
- **Falling back (3.5):** an edit that can't be kept is burnt in as in 0.12.0,
  and its copy gets the keyword `burnt-in`; the log ends with a `!` block of
  those photos, grouped by reason (the owner's choice). A copy Photos didn't
  take is converted from its rendering after the conversion (`bake/`).
- D2 (Compress Videos unchanged, the shared lines in `-- @IF EDITS` blocks) and
  D3 (ad hoc signing) were built as planned. The helper is released as
  `compress-photos-helper-macos.zip`, which `release.py` builds and checks.

The rest of this document is the plan as written before the prototype. Not
checked yet: Clean Up edits, JPEG originals with depth, and how the copies sync
to an iPhone (and whether they revert there).

Implementation plan for option C of issue #29, written 2026-11-27, after that
day's spike (its facts are in section 9; its test copies are gone from the
library). Nothing is built yet. **No further spike is planned**: the next thing
the owner runs is the real shortcut (section 7). Section 1 reviews the approach
the owner was shown, section 2 has the four decisions that are the owner's, and
section 8 says what stays unknown and how each unknown fails safe.

The goal: since 0.12.0 ([its plan](compress-photos-edits-plan.md)), *Compress
Photos (macOS)* started from Photos converts an edited photo as it looks, the
edit baked into the copy. Now the copy of an edited photo is an edited photo
too. In Photos it looks as its original does, Edit shows the earlier
adjustments, and Image ▸ Revert to Original gives the compressed unedited
photo. Whatever can't be done that way is converted as in 0.12.0, and the log
says which photos and why.

## 1. Review of the approach

### 1.1. What stands

- **A helper app with PhotoKit, started with `open -W`.** It is the only way
  that was measured end to end: started that way from the shortcut, the app
  asked for access under its own name (T2), read the edits and created the
  copies (G1, G2, G5).
- **PhotoKit creates the copy; Photos' importer (W1) doesn't.** PhotoKit was
  measured on four photos, five variants each, its calls are public, a refused
  request adds nothing, and the new photo's id comes back. W1 was measured
  once, depends on the camera's file names (`IMG_1234`, `IMG_E1234`,
  `IMG_1234.AAE`), which the importer's behavior isn't documented for, showed a
  file name nobody could explain, and would need the same change to
  `import.applescript`. Drop it, also as a fallback: the fallback is 0.12.0's
  copy.
- **The copy** is `photobatch`'s copy of the original, the original's
  `Adjustments.plist` byte for byte, and `photobatch`'s HEIC copy of Photos'
  rendering (G5: stored as given; a JPEG XL look is not).
- **Every failure ends in 0.12.0's copy**, never in a copy without its edit.
- **`import.applescript` adopts the new photo by its id** (G6), so the title,
  caption, keywords, favorite, albums, the date and location check and the
  album *Compressed originals* work as for an imported file.
- **No new question in the shortcut.** A line `EDITS=bake` in the script, like
  `WATCH=0`, is for those who want one picture per photo.

### 1.2. What to change

| Topic                          | In the approach                                                                  | Finding                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | Recommended                                                                                                                                                                                                                                                   |
| ------------------------------ | -------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| JPEG XL copies                 | a JPEG XL base with a HEIC look, only for originals stored upright               | Risky and hard to explain. The look can't be JPEG XL (G5), so what Photos shows would be a HEIC at an RF nobody chose, and `photobatch` would run twice (it has one format per run). Whether the edit is kept would depend on how the phone was held. An edit made on a gain-map HEIC would be redone on a PQ JPEG XL, the least known case. And G5's JPEG XL variant (a JPEG XL base and look) came out wrong for the photo stored with orientation 3: whatever Photos did there, it didn't cope with the rotation | With JPEG XL chosen, edited photos are converted as in 0.12.0, and the helper is never started. Revertible edits are a HEIC feature in 0.13.0 (D1)                                                                                                            |
| The helper's version           | the helper must have the shortcut's version                                      | Every release would force a helper update, and every update makes macOS ask for access again (T5), even when the helper didn't change                                                                                                                                                                                                                                                                                                                                                                               | The helper prints `photoedits <version> protocol <n>`; the shortcut asks for the protocol number only. The changelog says when the helper must be updated                                                                                                     |
| Signing                        | ad hoc                                                                           | Fine for a first version, with the cost above: one more question after each helper update. No code-signing identity was found from the agent's shell (P5)                                                                                                                                                                                                                                                                                                                                                           | Ad hoc for 0.13.0; the build script takes another identity without a code change (D3)                                                                                                                                                                         |
| Compress Videos                | 0.3.1, because it embeds `import.applescript`                                    | A release whose only news is "nothing", and a user who takes the new shortcut must update `vidmeta-macos` too or see its version warning. [Its own plan](compress-videos-edits-plan.md) counts on `lib/` staying as it is                                                                                                                                                                                                                                                                                           | The new code sits in marked blocks of the shared script that only Compress Photos' build keeps. The texts in Compress Videos' shortcut stay byte for byte; no version (D2)                                                                                    |
| Which edits                    | Photos' own, resources 1, 5 and 7, no depth effect, base version 0               | These look at the photo, not at the edit. An edit can need data the copy doesn't carry: a Photographic Style's data and the depth map (`photobatch` drops both), Clean Up's masks. Redone on the copy, such an edit would come out different                                                                                                                                                                                                                                                                        | The helper also reads the edit's list of parts and keeps only edits made of parts worked out from the picture and their own settings (3.2). The list of names is Photos' own (P2)                                                                             |
| Portrait photos                | excluded by the depth flag; the owner asks whether the flag alone should do that | It should. The blur of a Portrait photo is itself an edit made from the depth map, and the SDK says Revert keeps it ("Portrait bokeh") as part of the original. The copy has no depth map, so Photos could neither redo the blur nor revert to it. `IMG_1711` is such a photo                                                                                                                                                                                                                                       | Baked, with "(a Portrait photo)" in the log (D4)                                                                                                                                                                                                              |
| HEIC copies: "all such"        | every eligible photo's HEIC copy keeps the edit                                  | Not all HEIC copies keep the original's stored pixels. A HEIC made from pixels (from a JPEG, PNG or JPEG XL, or from an unusual HEIF) is stored upright; if the original is stored rotated (an older iPhone's JPEG, orientation 6), the edit no longer fits                                                                                                                                                                                                                                                         | The helper compares the two files' stored width, height and orientation before it creates anything (P3), and refuses such a photo before `photobatch` runs when it can tell                                                                                   |
| Never a copy without a look    | a requirement                                                                    | Make it structural                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | One function creates, and it takes all three files or does nothing. After creating, the helper checks that Photos' current picture is the look given (G5's test). The helper has no command that deletes, changes or reads a picture                          |
| `open -W`                      | starts the helper and waits                                                      | `open` gives no exit status and waits for ever. The spike's hang was a wait on the main thread for `requestContentEditingInput`                                                                                                                                                                                                                                                                                                                                                                                     | The helper writes an answer file that starts with its protocol line and ends with `end`; anything else counts as no answer. A watchdog inside the helper ends it. It never calls `requestContentEditingInput` and works off the main thread, as the probe did |
| Calling the helper by its path | considered, after the first grant                                                | By path was measured for the status and for reading (T3), not for creating. T5 shows the same identity is checked either way, so it would probably work, and it would give an exit status                                                                                                                                                                                                                                                                                                                           | Not now: `open -W` for everything that touches the library, as measured. Only `--version` runs by path (the release script, the tests)                                                                                                                        |
| Where the helper's files are   | in the work folder, `~/Pictures/.compress-photos-macos`                          | Every file PhotoKit read or wrote in the spike was under `~/Library/Caches/compress-photos-macos`. From `~/Pictures` it wasn't tried                                                                                                                                                                                                                                                                                                                                                                                | The helper's folder is `~/Library/Caches/compress-photos-macos/edits`; moving a file there is a rename                                                                                                                                                        |
| Test builds                    | the agent builds the helper and puts it in `~/Applications`                      | Every rebuilt helper asks for access again (T5), and the agent's sandbox can't start an app (`open` is blocked), so the first real start is the owner's                                                                                                                                                                                                                                                                                                                                                             | Say so in the owner's list (7); rebuild the helper only when its source changes                                                                                                                                                                               |
| Live Photos                    | not mentioned                                                                    | Nothing to do: the script skips a Live Photo before any of this, as today. The helper refuses one anyway (its resources aren't 1, 5 and 7)                                                                                                                                                                                                                                                                                                                                                                          | as is                                                                                                                                                                                                                                                         |
| HDR                            | not mentioned                                                                    | The HEIC base keeps the camera's gain map and the look keeps Photos' (`HDR kept` for both in 0.12.0's runs). With *Drop HDR* both are SDR                                                                                                                                                                                                                                                                                                                                                                           | as is; the owner's test looks at an HDR photo                                                                                                                                                                                                                 |
| iCloud, *Optimize Mac Storage* | not mentioned                                                                    | Photos already downloads the original for its export and Shortcuts the rendering. The edit is a few KB more; whether the spike's reads needed a download isn't known                                                                                                                                                                                                                                                                                                                                                | The helper allows the download and waits 30 s per edit; no edit in time means 0.12.0's copy                                                                                                                                                                   |
| Another library open in Photos | not mentioned                                                                    | PhotoKit and Shortcuts use the System Photo Library; Photos' AppleScript uses the open one. *Find Photos* then finds no album and stops the run before anything is converted (expected from 0.12.0's design, not tested)                                                                                                                                                                                                                                                                                            | Nothing new. If a run got further, the helper would find no photo by the id and the copy would be 0.12.0's                                                                                                                                                    |

## 2. Decisions for the owner

Each with the recommendation first.

- **D1. With JPEG XL chosen, an edited photo is converted as in 0.12.0.** Only
  HEIC copies keep the edit. To keep the edits of edited photos, convert those
  as HEIC (a smart album "Photo is edited" finds them). Alternative, as shown
  before: a JPEG XL base with a HEIC look for photos stored upright; it needs a
  second `photobatch` run per batch, an RF for the look, and a test of its own
  (1.2).
- **D2. Compress Videos ships nothing new.** The lines that adopt a photo by
  its id go into `lib/mac/import.applescript` between two marker lines, and
  only Compress Photos' build keeps them (4.5). Alternative, as shown before:
  no markers, and a Compress Videos 0.3.1 with no change for videos.
- **D3. The helper is signed ad hoc in 0.13.0**, like `photobatch-macos`. After
  each helper update macOS asks once more for access to Photos (T5); the
  shortcut needs a helper update only when the protocol number changes.
  Alternative: sign with one stable identity, which should keep the access
  across updates (TCC then remembers the certificate, not the build; common
  practice, not measured here). That needs a Developer ID, or a self-signed
  code-signing certificate the owner makes once in Keychain Access.
- **D4. Portrait photos stay baked, and so do edits with a Photographic Style,
  Clean Up or Retouch.** Their copies can't carry what those edits need (1.2).
  Alternative for Portrait photos only: keep the edit anyway; the copy would
  look right, but Edit on it would lose the blur. Not recommended, and not
  tested.

## 3. Design

As recommended in section 2.

### 3.1. What the copy is

One new photo in the library, made of three files (G1, G2, G5):

| Resource (type)     | The file                                                                           | From                                              |
| ------------------- | ---------------------------------------------------------------------------------- | ------------------------------------------------- |
| the original (1)    | `photobatch`'s HEIC copy of the unedited original, named as the copy (`Name.heic`) | Photos' export (`using originals`) → `photobatch` |
| the edit (7)        | the original's `Adjustments.plist`, byte for byte                                  | the helper, from the library                      |
| the edited look (5) | `photobatch`'s HEIC copy of Photos' rendering: the file 0.12.0 saves as the copy   | Find Photos (the album bridge) → `photobatch`     |

- The look is stored as given (G5), so the copy looks exactly as 0.12.0's copy
  does. With *Drop HDR* both pictures are SDR.
- Size, from the spike's `IMG_1818`: original 2.4 MB and rendering 2.0 MB in
  the library now; base 1.4 MB and look 1.0 MB in the copy; 0.12.0's copy is
  the look alone, 1.0 MB.
- Not kept, as before: the original at its full quality, depth data, a
  Photographic Style's data.

### 3.2. Which edited photos keep their edit

A photo is "edited" as in 0.12.0: its rendering from Shortcuts isn't its
exported original, byte for byte. Its copy keeps the edit when all of this
holds; otherwise it is converted as in 0.12.0, with the reason in the log.

| Rule                                                                                         | Why                                                                                                  | Checked by                 |
| -------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- | -------------------------- |
| HEIC is the chosen format, and the script's `EDITS` isn't `bake`                             | D1; the switch                                                                                       | the script                 |
| the helper is installed, speaks the shortcut's protocol, and has full access to Photos       | 3.3                                                                                                  | the script, the helper     |
| the photo has an id (its name is unique in the selection) and was paired with its rendering  | as in 0.12.0                                                                                         | the script                 |
| PhotoKit finds it by that id (T0), as a photo with an edit whose format is `com.apple.photo` | another app's edit can't be redone by Photos                                                         | `check`                    |
| it isn't a Portrait photo (`photoDepthEffect`) or a Live Photo                               | D4; Live Photos are skipped anyway                                                                   | `check`                    |
| its resources are exactly one each of types 1, 5 and 7                                       | anything more (a RAW, an older base, a type this SDK doesn't know) is something the copy can't carry | `check`                    |
| `Adjustments.plist` has `adjustmentData`, and `adjustmentBaseVersion` is 0                   | the edit must be in the plist and start from the original                                            | `check`, again in `create` |
| every part of the edit that isn't switched off is in the list below                          | D4                                                                                                   | `check`, again in `create` |
| the original is a HEIF, or stored upright (orientation 1)                                    | saves converting a base that the next rule would refuse                                              | `check`                    |
| the base has the original's stored width, height and orientation                             | the edit is written for the original's pixels as stored                                              | `create`                   |
| the look is a HEIC, and all three files are there                                            | never a copy without its look                                                                        | `create`                   |

The edit's data is JSON, compressed, with a list `adjustments`; each part has
an `identifier` (P1). The parts that are kept, by Photos' own names (P2):
`SmartTone`, `SmartColor`, `SmartBlackAndWhite`, `WhiteBalance`,
`SemanticEnhance`, `RKCurvesOperation`, `RKLevelsOperation`,
`RKSelectiveColorOperation`, `DGDefinition2Operation`,
`RKNoiseReductionOperation`, `RKProSharpenOperation`,
`DGVignetteEffectOperation`, `Grain`, `Effect`, `Crop`, `Orientation`,
`RedEyeBB`, `RKRedEyeOperation` (light, color, black and white, white balance,
auto enhance, curves, levels, selective color, definition, noise reduction,
sharpening, vignette, grain, filters, crop and straighten, rotation, red-eye).
Any other part bakes the photo: `DepthEffect` and `PortraitEffect` ("a Portrait
photo"), `SemanticStyle` and `TextureStyle` ("a Photographic Style"),
`Inpaint`, `InpaintMasks`, `GenerativeEdits`, `GeneratedTiles` ("Clean Up"),
`RKRetouchOperation` ("Retouch"), the RAW and video parts, and any name this
version doesn't know. That the kept parts need nothing but the picture is read
from their names and settings, not measured; the list errs toward baking.

### 3.3. The helper

`Compress Photos Helper.app`: a Swift program in an app bundle, with no window
and no Dock icon (`LSUIElement`), the identifier
`io.github.jsh9.compress-photos.helper`, and `NSPhotoLibraryUsageDescription`:
"Compress Photos reads an edited photo's edit and saves the photo's compressed
copy with it, so that the edit can still be changed or reverted." It links only
Apple's frameworks (Photos, ImageIO, Foundation): nothing new in `licenses/`.

- **Found** in `~/Applications`, then `/Applications`; `PHOTOEDITS` overrides
  the app's path (the tests).
- **Started** by the selection script, twice at most per run:
  `open -W -n -g -a "$helper" --stderr "$E/check.err" --args check "$E"`, and
  the same with `create`. This is how every G result was made. A shortcut's own
  scripts can't use PhotoKit (T1).
- **Access.** The first `check` makes macOS ask whether "Compress Photos
  Helper" may access Photos (T2); the helper waits 120 s for the answer. The
  install line opens the app once, which asks at install time instead (an app
  opened from Terminal asking is what Apple documents; not measured). Full
  access is needed: it reads edits and adds photos. `create` never asks.
- **Its answer** is a file. `open` gives no exit status, so an answer counts
  only if it starts with `photoedits <version> protocol 1` and ends with `end`.
- **It can't hang the run**: every wait has a limit, and a watchdog ends the
  program after 150 s plus 45 s per photo, writing what it has.
- **What it can do**: write an edit's plist into a folder, and create a photo
  from three files in that folder. No command returns a picture from the
  library, changes a photo or deletes one.
- **Updating**: the install line again. The signature is ad hoc, so macOS asks
  for access once more (T5).

### 3.4. The flow

`selection_route` in `build_mac_shortcuts.py` keeps its actions. Only the
selection script and the import script change. New steps are marked `+`:

```
  the questions; the notification; the empty work folder
  Run AppleScript export.applescript → IDS (unchanged)
  Run AppleScript bridge.applescript; Find Photos → Renderings, Dates
  Run Shell Script common.zsh + selection.zsh:
    pairs each still with its rendering; cmp: edited or not (0.12.0)
    stages every still as job n: an edited one as a copy of its
      rendering (0.12.0)
+   HEIC, EDITS=keep, a helper, edited photos: their ids → check.txt,
+     a clone of each original → edits/n/original; helper "check"
+   for each "n|ok": job n becomes the original (the base), and the
+     rendering's copy becomes a new last job m, "Name (edited).HEIC";
+     jxl_dates.txt and jxl_meta.txt get n's lines for m too
    photobatch (unchanged)
+   for each such photo whose two jobs gave a file: base.heic and
+     look.heic → edits/n/; helper "create"
    result lines, "path|original id|flag|Name.heic|keywords":
      as today for every other photo
+     created:     "id:<new id>|original id|flag|Name.heic|keywords"
+     not created: the look as out/Name.heic, as in 0.12.0
+   removes the edits folder
  Run AppleScript bridge.applescript "close"
  Run AppleScript import.applescript: a line that starts with "id:" is
+   a photo already in the library, taken by its id (G6)
  the log in Quick Look if it has a note; finish; the notification
```

- An edited photo that keeps its edit is encoded twice: 2 to 3 s more per 24 MP
  photo (0.12.0's log). `photobatch`'s summary counts both jobs.
- The base converts and the look fails: nothing is saved for that photo and its
  original isn't collected, as when a rendering fails in 0.12.0. The base alone
  is never saved (it would be a copy without its edit). The look converts and
  the base fails: the look is saved as in 0.12.0.
- The new photo's date and location come from the base file's EXIF, which
  `photobatch` writes from Photos' values; `import.applescript` then sets
  whatever Photos read differently, as for an imported file.

### 3.5. The log, and falling back

Before `photobatch` runs:

- kept:
  `2 edited photo(s) keep their edits, which you can change or revert on the copies in Photos (each is converted twice: the unedited photo, then its edited look, listed last as "Name (edited)"): IMG_1.HEIC, IMG_2.HEIC`
- not kept, 0.12.0's line with the reasons, no `!`:
  `2 edited photo(s) are converted as they look in Photos now (the edit can't be reverted on the copy): IMG_3.HEIC (a Portrait photo), IMG_4.JPG (stored rotated)`
- JPEG XL, `EDITS=bake`, or no helper installed: 0.12.0's line, byte for byte.
- no access, after that line, no `!` (it may be the user's choice):
  `Compress Photos Helper has no access to Photos (allow it in System Settings ▸ Privacy & Security ▸ Photos), so no edit was kept.`
- no answer, or not all of one:
  `! Compress Photos Helper gave no answer (<the first line of its error output>): edited photos are converted as they look now.`
- another protocol:
  `! Compress Photos Helper (<its first line>) doesn't fit this shortcut, which needs protocol 1: edited photos are converted as they look now. See Updating in <help URL>`

After it:

- `! IMG_5.HEIC: Photos did not take the copy with its edit (<reason>): saved as it looks now (the edit can't be reverted on the copy)`
- `! IMG_6.HEIC: Photos made the copy with its edit but shows no picture for it (<reason>): the photo was also saved as it looks now. Delete the copy without a picture in Photos (the newest IMG_6.heic).`
- `! IMG_7.HEIC: its unedited photo could not be converted, so it was saved as it looks now (the edit can't be reverted on the copy)`
- `! IMG_8.HEIC: its edited look could not be converted: nothing was saved for it, and its original is not collected`
- from `import.applescript`:
  `! IMG_9.heic: Photos does not find the copy made with its edit (<error>)`

The reasons `check` gives, each for one rule of 3.2:
`not in the System Photo Library`, `not a photo`, `Photos has no edit for it`,
`edited by another app (<identifier>)`, `a Live Photo`, `a Portrait photo`,
`a Photographic Style`, `Clean Up`, `Retouch`,
`its edit has a part the copy can't carry (<name>)`,
`it has other data in the library (resource types 1, 5, 7, 8)`,
`its edit did not arrive in 30 s`, `its edit could not be read (<error>)`,
`Photos keeps its edit outside Adjustments.plist`,
`its edit is not based on the original photo`,
`its edit is in a form this version doesn't read`, `stored rotated`.

### 3.6. What must keep working

| Subject                                        | What happens                                                                                                                                                                                                               |
| ---------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| unedited photos                                | untouched: no helper call, the same bytes as 0.12.0                                                                                                                                                                        |
| without the helper, or with JPEG XL            | 0.12.0's results and log, byte for byte                                                                                                                                                                                    |
| dates (#18), location, #21                     | `jxl_dates.txt` and `jxl_meta.txt` go by job index, now for both jobs; `import.applescript`'s check runs on the adopted photo as on an imported one                                                                        |
| the album *Compressed originals*               | the result lines keep each original's id; an original is collected only when its copy is in the library                                                                                                                    |
| Compress Videos                                | the texts its shortcut embeds are byte for byte those built from `main` (D2)                                                                                                                                               |
| WebAssembly and macOS write the same bytes     | no encoder change                                                                                                                                                                                                          |
| old and new parts mixed (AGENTS.md 7)          | an old shortcut never starts the helper; a new shortcut with an old `photobatch` warns as today; `photobatch`'s files don't change; a helper with another protocol isn't used; only the new import script sees `id:` lines |
| the iPhone, the Mac's picker, the Finder route | unchanged                                                                                                                                                                                                                  |

## 4. Implementation, file by file

### 4.1. `src/photoedits/main.swift` and `Info.plist`

In `shortcuts/compress-photos/src/photoedits/`. A draft of `main.swift` (300
lines) compiled against the macOS 27 SDK for macOS 14, and the commands that
need no library ran (P3); the PhotoKit calls are the probe's
(`build/spike-revert/main.swift`), which ran against the library.

| Command                                                                    | Does                                                                          | Photos                |
| -------------------------------------------------------------------------- | ----------------------------------------------------------------------------- | --------------------- |
| `photoedits --version`                                                     | prints `photoedits 0.13.0 protocol 1`                                         | no                    |
| `photoedits ask`, and with no arguments (a double-click, the install line) | asks for access if macOS hasn't asked yet, and prints the status              | asks                  |
| `photoedits check DIR`                                                     | reads `DIR/check.txt`, writes `DIR/<n>/Adjustments.plist` and `DIR/check.out` | reads; asks, as `ask` |
| `photoedits create DIR`                                                    | reads `DIR/create.txt` and `DIR/<n>/`, writes `DIR/create.out`                | adds; never asks      |
| `photoedits plist FILE`                                                    | the plist rules alone: prints `ok` or `no\|<reason>` (for the tests)          | no                    |
| `photoedits geometry BASE ORIGINAL`                                        | the geometry rule alone: the same                                             | no                    |

Anything else prints a usage line and exits 64. `check` and `create` exit 0, or
2 from the watchdog; nobody reads that status (`open` hides it). The files, all
in `DIR` (`$LOGDIR/edits`):

| File                      | Written by | Lines                                                                                                               |
| ------------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------- |
| `check.txt`               | the script | `n\|<Photos' id>` per edited photo, n its job index                                                                 |
| `<n>/original`            | the script | a clone of the exported original (`/bin/cp -c`)                                                                     |
| `<n>/Adjustments.plist`   | `check`    | the photo's resource 7                                                                                              |
| `check.out`               | `check`    | `photoedits 0.13.0 protocol 1`, `access\|<status>`, then `n\|ok` or `n\|no\|<reason>` per photo, then `end`         |
| `<n>/base.heic`           | the script | `photobatch`'s copy of the original                                                                                 |
| `<n>/look.heic`           | the script | `photobatch`'s copy of the rendering                                                                                |
| `create.txt`              | the script | `n\|<the copy's name>`, as `IMG_1818.heic`                                                                          |
| `create.out`              | `create`   | the same two first lines, then `n\|created\|<id>`, `n\|failed\|<reason>` or `n\|unsure\|<id>\|<reason>`, then `end` |
| `check.err`, `create.err` | `open`     | the helper's error output                                                                                           |

- `access|<status>` is PhotoKit's number: 3 is full access; with any other
  number no photo lines follow. The last line is `end`, or `end|timeout` from
  the watchdog. A reason never holds a `|` or a line break.
- Structure, as the probe's: the work runs on a global queue and the main
  thread runs `dispatchMain()`. Each callback is awaited with a limit: 120 s
  for the access question, 30 s for an edit (network access allowed), 10 s for
  the look after creating.
- `check` applies 3.2's rules in the table's order and gives the first reason
  that fails.
- `create`, per photo: the look is a HEIC (ImageIO) and the plist passes its
  rules again; the base has the original's stored width, height and orientation
  (ImageIO); `supportsAssetResourceTypes` for 1, 7 and 5 (true on this Mac);
  then one request, the probe's:

```swift
try PHPhotoLibrary.shared().performChangesAndWait {
    let request = PHAssetCreationRequest.forAsset()
    let options = PHAssetResourceCreationOptions()
    options.originalFilename = name  // "IMG_1818.heic"
    request.addResource(with: .photo, fileURL: base, options: options)
    request.addResource(with: .adjustmentData, fileURL: plist, options: nil)
    request.addResource(with: .fullSizePhoto, fileURL: look, options: nil)
    id = request.placeholderForCreatedAsset?.localIdentifier
}
```

- Then, for up to 10 s: the new photo has adjustments, lists resources 5 and 7,
  and its current picture (`PHImageManager`, version `current`, no network) has
  the look's size in bytes. That is `created`. Anything else is `unsure`, with
  the id: the script saves the look as in 0.12.0 as well and says so with a `!`
  line. The helper deletes nothing (PhotoKit would ask the user to confirm).
- One request per photo: one photo's failure leaves the others, and a refused
  request adds nothing. PhotoKit copies the files (the SDK's `shouldMoveFile`,
  off by default), so the folder can go afterwards.
- `Info.plist`: the keys of 3.3, `CFBundleExecutable` `photoedits`,
  `LSMinimumSystemVersion` 14.0, and `@VERSION@` for both version keys.

### 4.2. `scripts/build-helper.sh`, signing, installing

- Builds `dist/Compress Photos Helper.app`: `@VERSION@` filled in (`sed`, into
  `build/helper/`), `swiftc -swift-version 5 -O -target arm64-apple-macos14.0`
  with a module cache in `build/helper/` (the agent's sandbox needs that),
  `codesign -s "${HELPER_IDENTITY:--}" --force`, `codesign --verify --strict`,
  and a last line with `photoedits --version`. Apple silicon only, like
  `build-macos.sh`.
- `build-helper.sh --install` also copies it to `~/Applications` (`ditto`).
  That folder is outside the agent's sandbox: the agent runs it with the
  sandbox off, or the owner pastes the line in section 7.
- Release: the zip `compress-photos-helper-macos.zip` (4.6), a name without the
  version so that `latest/download` works. README-mac's install line (`curl`
  doesn't quarantine; the last command makes macOS ask for access):

```
mkdir -p ~/Applications &&
curl -L -o "${TMPDIR:-/tmp/}helper.zip" https://github.com/jsh9/photo-video-shortcuts/releases/latest/download/compress-photos-helper-macos.zip &&
rm -rf ~/Applications/"Compress Photos Helper.app" &&
ditto -x -k "${TMPDIR:-/tmp/}helper.zip" ~/Applications &&
open -W ~/Applications/"Compress Photos Helper.app"
```

### 4.3. `scripts/mac/selection.zsh`

`common.zsh` and `run.zsh` don't change: the picker and the Finder shortcut
never mention the helper. In `selection.zsh`, in this order:

1. After `RDATES`: `EDITS=${EDITS:-keep}`, with a comment for users who want
   `EDITS=bake`; `E="$LOGDIR/edits"`; `rm -rf "$E"`. The helper is looked for
   only if `EDITS` is `keep` and `FORMAT` is `heic`:
   `for c in "${PHOTOEDITS:-}" @HELPERS@`, the first that is a folder.
2. The function that starts it:

```zsh
# edits COMMAND: starts the helper on $E/COMMAND.txt and waits. Its answer,
# $E/COMMAND.out, counts if it starts with this shortcut's protocol and
# ends with "end" (open gives no exit status). The lines are in $answer.
edits() {
  rm -f "$E/$1.out"
  open -W -n -g -a "$helper" --stderr "$E/$1.err" --args "$1" "$E" \
    2>> "$E/$1.err"
  answer=("${(@f)$(cat "$E/$1.out" 2>/dev/null)}")
  [[ ${answer[1]} == 'photoedits '*' protocol @PROTOCOL@' ]] &&
    [[ ${answer[-1]} == end* ]]
}
```

3. The staging loop stays as it is, and notes each edited photo's job index and
   its `jxl_dates.txt` line.
4. After the loop, with a helper and edited photos: `mkdir -p "$E/$i"`,
   `/bin/cp -c` of the exported original to `$E/$i/original`, a line in
   `check.txt`; `edits check`. For each `i|ok`: `jxl_in_$i.orig` (the
   rendering's copy) is renamed `jxl_in_$m.orig`, m the next job index;
   `jxl_in_$i.orig` becomes a link to the original, as for an unedited photo; a
   job line `m|<stem> (edited).<extension>`; the date line again for m.
   `origs[$m]` is the photo's name, so the meta loop must write a photo's lines
   for both of its jobs (today it keeps one job per id).
5. The two log lines of 3.5 replace 0.12.0's one; with nothing kept and no
   reasons the line is 0.12.0's.
6. `@RUN@`, unchanged.
7. After it, `jxl_done.txt` is read once into arrays by job index (file, flag,
   name). For each kept photo with both files: `mv` to `$E/$i/base.heic` and
   `$E/$i/look.heic`, a line `i|<name>` in `create.txt`; then `edits create`.
8. The result lines, in job order. A look's job prints nothing of its own. A
   kept photo prints `id:<id>|...` when created; otherwise its look is moved to
   `out/` under the copy's name (the look's own name without ` (edited)`) and
   printed as today, with the `!` line of 3.5. Every other photo: as today.
9. `rm -rf "$E"`. A run that dies leaves the folder; the next run removes it
   first.

The header comment gets the new inputs and files.

### 4.4. `scripts/build_mac_shortcuts.py` and `lib/wfkit.py`

- `HELPER_PATHS` (`$HOME/Applications/Compress Photos Helper.app`,
  `/Applications/Compress Photos Helper.app`) and `HELPER_PROTOCOL = 1`, as
  `@HELPERS@` and `@PROTOCOL@` in `script_text`. A test compares the number
  with `main.swift`'s.
- The shortcut's comment: an edited photo's HEIC copy keeps its edit when
  *Compress Photos Helper* is installed.
- `applescript_text('import')` passes `blocks=('ADOPT',)`.
- `lib/wfkit.py`, `applescript_text(path, blocks=(), **values)`: the lines
  between `-- @IF NAME@` and `-- @END NAME@` stay, without those two lines,
  when NAME is in `blocks`, and go with them otherwise. No shortcut built today
  changes by this.

### 4.5. `lib/mac/import.applescript`, and Compress Videos

Three blocks marked `ADOPT`; every other line stays as it is:

- after the plan's text is read: `set adopted to my adoptedLines(plan)` (the
  lines whose first field starts with `id:`, as
  `{id, original id, name, keywords}`) and `set plan to my otherLines(plan)`;
- after the files are imported, per adopted line, in a `try`: `media item id`
  of the id, and its `filename` read so that a wrong id fails here. Found: it
  counts as imported and joins `pairs` and `toCollect`, like an imported file
  with a known original. Not found: the `!` line of 3.5, and its original isn't
  collected;
- at the end: the two handlers, which don't talk to Photos (so the tests run
  them).

The header comment says what an `id:` line is. Compress Videos' build passes no
`blocks`: its three AppleScripts come out as today. Step 5 of 4.7 proves it. If
the owner prefers D2's alternative, the markers go, `wfkit.py` stays as it is,
and Compress Videos gets `VERSION` 0.3.1, a changelog entry and rebuilt tools.

Compress Videos' own plan (its D1) wants `bridge.applescript` shared the next
time Compress Photos' Mac shortcut changes. 0.13.0 is such a change, but moving
the file is that plan's work, not this one's.

### 4.6. `release.json`, `scripts/release.py`, CI

- `release.json`: a new optional key, `"apps": ["Compress Photos Helper.app"]`.
- `release.py`: `Tool` accepts `apps` (names ending in `.app`, no slashes, not
  listed twice); `build()` also runs `build-helper.sh`; for each app, its
  executable (`CFBundleExecutable` of its `Info.plist`) must be fresh and print
  the tool's version, `codesign --verify --strict` must pass, and
  `ditto -c -k --norsrc --noextattr --keepParent` writes
  `dist/release/compress-photos-helper-macos.zip` (the app's name in lower
  case, spaces as hyphens, `-macos.zip`), which is reopened and checked for the
  executable and `Info.plist` (P4: such a zip unpacks to an app that verifies).
  With `--no-sign` the app is still signed ad hoc: that needs no account.
- `tox.ini`: `build-helper.sh` in the `build` environment. CI builds it in the
  release dry run, before the tests. `docs/releasing.md`: `apps`.

### 4.7. Steps

01. `git switch -c <date>-mac-revertible-edits main`, the date the work starts.
02. The owner's decisions (2).
03. `src/photoedits/`, `build-helper.sh`, and
    `tests/compress-photos/test_photoedits.py`.
04. `lib/wfkit.py`, `import.applescript`, their tests.
05. Check D2 once: the branch's `lib/mac/import.applescript` without its
    `ADOPT` blocks and their marker lines is `main`'s file byte for byte
    (`git show main:lib/mac/import.applescript`), and Compress Videos'
    `applescript_text('import')` is the same text on both. (The built shortcuts
    can't be compared: every build gives its actions new UUIDs.)
06. `selection.zsh`, `build_mac_shortcuts.py`, their tests.
    `pre-commit run --all-files`.
07. `release.json`, `release.py`, `tox.ini`, their tests.
08. Docs, `VERSION` 0.13.0, `CHANGELOG.md` (6). Bump last: the version tests
    fail until every encoder is rebuilt.
09. Build the encoders, the helper and the shortcuts (the owner signs the
    shortcuts in iTerm2), then the owner's test (7).
10. Commit as
    `Compress Photos 0.13.0: from Photos on the Mac, an edited photo's HEIC copy keeps its edit`;
    a PR that refers to #29. Don't release (AGENTS.md 8).

## 5. Tests

No test can use a photo library, and none may start the real helper's `ask`,
`check` or `create`: on a Mac they would make macOS ask for access. The tests
cover everything around PhotoKit; section 7 covers PhotoKit.

`tests/compress-photos/test_mac_script.py`. A stand-in helper: `PHOTOEDITS`
names a made-up `Helper.app` whose `Contents/MacOS/photoedits` is a script that
answers `check` and `create` from a table and records its arguments and the
files it found; the harness's stand-in `open` (it has one for the progress
window) runs that program with the arguments after `--args`. So the script's
real `open` line is what runs.

- an edited photo, `check` ok, `create` created: two jobs (`jxl_in_1.orig`
  links into `in/`, the last job is the rendering's copy), dates and locations
  for both, `base.heic`, `look.heic`, `original` and the plist in place when
  `create` ran, one result line
  `id:...|<original's id>|delete|IMG_0001.heic|heic,RF=26`, the "keep their
  edits" line, no `!`, and no `edits` folder afterwards;
- `check` says no: one job, 0.12.0's result line, the reason in the log;
- `create` says failed, unsure, or nothing for the photo: the look saved as
  0.12.0's copy under the copy's name, the `!` line;
- JPEG XL, `EDITS=bake`, no helper: the helper is never started and the log is
  0.12.0's, byte for byte;
- `access|2`, an empty answer, an answer without `end`, another protocol,
  `end|timeout` after one of two photos: 0.12.0's results, the line of 3.5;
- the base fails and the look converts, and the other way round (3.4);
- an unedited photo, a Live Photo, a video, an unchecked photo, two photos with
  one name: the helper isn't asked about them;
- a name with `|` or `:`; two edited photos, one kept and one not;
- the existing selection tests keep their logs (no helper in their
  environment).

`tests/compress-photos/test_mac_shortcuts.py`:

- the selection script has the `open -W -n -g -a` line, the two paths and the
  protocol; the picker's and the Finder shortcut's scripts have none of them;
  the route's actions are the same as before;
- the import script has no marker line and has the adoption; `adoptedLines` and
  `otherLines` with `run_handlers`: mixed lines keep their order, an older line
  format still parses, an `id:` line never reaches `import`;
- `test_applescripts_compile` still passes;
- `HELPER_PROTOCOL` is `main.swift`'s number.

`tests/compress-videos/test_mac_shortcuts.py`: its import script has no marker
line and no `adoptedLines`. A test of `applescript_text`'s blocks goes where
`lib/wfkit.py` is tested.

`tests/compress-photos/test_photoedits.py` (new; needs the built helper):

- `--version` is `photoedits <VERSION> protocol <n>`; a wrong command exits 64;
- `plist` on made-up plists: no `adjustmentData`, base version 1 or missing,
  another format, data that isn't compressed JSON, each kept part, each named
  part of 3.2, an unknown part, a part switched off;
- `geometry` on fixtures converted by `photobatch`: `hdr/grid_o6.heic` passes
  with its HEIC copy and fails with its JPEG XL copy; `hdr/o1.heic` passes with
  both (P3);
- the bundle: the identifier, `LSUIElement`, the usage text, and
  `codesign --verify --strict`.

`tests/scripts/test_release.py`: a manifest with `apps` (the zip's members, a
wrong version, a missing app, a bad name); manifests without `apps` as before.

Run on the Mac:
`python3 -m pytest tests/compress-photos/test_mac_shortcuts.py tests/compress-photos/test_mac_script.py tests/compress-photos/test_photoedits.py tests/compress-videos tests/scripts`,
then `tox -e tests`. On this Mac 18 `test_xmp` pixel cases per build fail on
`main` too.

## 6. Docs, versions, changelog

- `shortcuts/compress-photos/VERSION`: 0.13.0. Compress Videos' stays (D2).
- `CHANGELOG.md`, `## [Compress Photos 0.13.0] - <the day it merges>`, *Added*:
  from Photos on the Mac, an edited photo's HEIC copy keeps its edit (Edit
  shows it, Revert to Original gives the compressed unedited photo) when
  *Compress Photos Helper* is installed and allowed; which photos (HEIC copies;
  not Portrait photos, Photographic Styles, Clean Up, other apps' edits); that
  such a copy holds two pictures (2.3 MB against a baked copy's 1.0 MB in 3.1's
  example); `EDITS=bake`; that JPEG XL copies and everything without the helper
  are as in 0.12.0. What to update: the Mac shortcut and `photobatch-macos`
  (unchanged but for its version, which the shortcut checks); to get this,
  install the helper; the iPhone's files work as in 0.12.0.
- `README-mac.md`: 2 (the helper's install line, optional, and its question),
  3.1 (the edited-photo paragraph: what is kept and when not, the size,
  `EDITS=bake`), 4, 5 (updating the helper: only when the changelog says so;
  macOS asks again), 6 (rows for the helper's log lines; removing the helper
  and its permission).
- `README.md` 3, *Edits*: the Mac's selection keeps them on HEIC copies; the
  other routes bake them in.
- `DEVELOPING.md`: 1.1 (the flow, the helper's commands and files, 3.2's rules
  with their reasons, the facts of section 9), 2 (`src/photoedits/`,
  `scripts/build-helper.sh`), 3 (building the helper).
- `docs/releasing.md` (`apps`), `tests/README.md` (the new file, the rows of
  the two Mac files), `docs/compress-photos-edits-plan.md` (a line at the top
  pointing here), `docs/compress-photos-mac-design.md` where it describes
  edited photos.
- `AGENTS.md`: 1 (the helper, in the Compress Photos paragraph), 7 (the
  helper's files are a protocol with a number; an `-- @IF` block of a shared
  script belongs to the tools that keep it).

## 7. The owner's test

No spike, no labeled test copies: the real shortcut on real photos. It makes
real copies, as every run does; nothing is deleted.

1. Install what the agent built. In Terminal:

```
cd ~/Documents/github/photo-video-shortcuts/shortcuts/compress-photos
cp dist/photobatch-macos ~/.local/bin/photobatch
mkdir -p ~/Applications
ditto "dist/Compress Photos Helper.app" \
  ~/Applications/"Compress Photos Helper.app"
open "dist/Compress Photos (macOS).shortcut"
```

2. In Photos, select the spike's five photos and one unedited photo: `IMG_1818`
   (an adjustment), `IMG_1819` (taken upside down), `IMG_1869` (rotated),
   `IMG_1880` (cropped), `IMG_1711` (the Portrait JPEG). Share ▸ *Compress
   Photos (macOS)* ▸ HEIC ▸ RF 26 ▸ All cores ▸ Keep HDR. When macOS asks
   whether *Compress Photos Helper* may access your photos, allow it.
3. Look at the copies (the newest photos; keyword `compr`):
   - no gray thumbnail; each copy looks like its original, HDR included;
   - open a copy and click Edit: the sliders and the crop are the original's,
     and the picture doesn't jump when Edit opens; Cancel;
   - on one copy: Edit, move a slider, Done;
   - on another: Image ▸ Revert to Original shows the unedited photo;
   - Info shows the name (`IMG_1818.heic`), the date and the place; the copy is
     in its original's albums; the originals are in *Compressed originals*;
   - `IMG_1711`'s copy looks like its original and has no Revert: the log says
     `(a Portrait photo)`.
4. Run it once more on edited photos with JPEG XL: the copies are as in 0.12.0
   (D1).
5. If iCloud Photos is on: on the iPhone, a little later, the HEIC copies look
   edited, and Edit ▸ Revert works there.
6. Say "done" and what looked wrong, on which photo. The agent reads the log
   itself (`~/Library/Caches/compress-photos-macos/photos-selection.log`).

If the agent rebuilds the helper after this, macOS asks for access once more
(T5).

To remove the helper and its permission:

```
rm -rf ~/Applications/"Compress Photos Helper.app"
tccutil reset Photos io.github.jsh9.compress-photos.helper
```

What the spike left can go the same way: the shortcuts *Compress Photos Spike
Revert* and *Compress Photos Spike Labels* (delete them in Shortcuts), and

```
tccutil reset Photos io.github.jsh9.compress-photos.spike
tccutil reset Photos io.github.jsh9.compress-photos.applet
rm -rf ~/Library/Caches/compress-photos-macos/spike-revert
```

## 8. What stays unknown, and how it fails safe

Nothing here has to be measured before the work starts. Each unknown either
ends in 0.12.0's copy with a line in the log, or is something step 3 of the
owner's test looks at.

| Unknown                                                                                                                                             | If it goes wrong                                                                                                                                                        | Seen in                  |
| --------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------ |
| Editing a copy again: Photos redoing the edit on the compressed base. Never tried, for any format                                                   | The look stays as stored until the user presses Done in Edit, and Revert works (G4). If a kind of edit comes out wrong, its part leaves 3.2's list and such photos bake | the owner's test, Edit   |
| How the copies look on an iPhone through iCloud Photos (the spike saw only copies without a look there)                                             | Say in the README that the edit shows on the Mac; or bake, as the owner decides                                                                                         | the owner's test, step 5 |
| Whether Photos ever replaces a look with a rendering of its own                                                                                     | The same as the first row                                                                                                                                               | not seen in the spike    |
| A base and a look made from pixels (a JPEG or PNG original, whose rendering is a JPEG) with the edit: G2 and G5 had bases and looks made from HEICs | Photos refuses it: 0.12.0's copy, with a `!` line                                                                                                                       | the log                  |
| Real edits' parts: 3.2's list comes from Photos' names, and P1's form from Photos' own writer, not from a photo's plist                             | Unreadable or unknown: baked, with the reason. Should every photo bake for this, the log shows it at once                                                               | the log                  |
| Resources other than 1, 5 and 7 on ordinary edited photos (with *Optimize Mac Storage*, say)                                                        | Baked, with the types in the log                                                                                                                                        | the log                  |
| The name, date and place Photos shows for a created photo                                                                                           | `import.applescript` sets a date or place that differs; the name is checked by eye                                                                                      | the owner's test, Info   |
| Setting a title, caption, date or favorite on a created photo from AppleScript (G6 set keywords and an album)                                       | A `! could not set its ...` line per field, as for an imported file                                                                                                     | the log                  |
| The helper started from `~/Applications` (the spike's apps sat in `~/Library/Caches`)                                                               | It doesn't start, or gives no answer: 0.12.0's copies, with a `!` line                                                                                                  | the log                  |
| Access asked for from Terminal, by the install line                                                                                                 | It doesn't ask there: the first run asks (T2)                                                                                                                           | the owner's test         |
| Nobody answers the access question within 120 s                                                                                                     | That run bakes; the next run asks again                                                                                                                                 | the log                  |
| Whether a stable signature keeps the access across updates (D3's alternative)                                                                       | macOS asks again, as with ad hoc                                                                                                                                        | only if D3 changes       |
| Another library open in Photos                                                                                                                      | 1.2's last row                                                                                                                                                          | Shortcuts' own error     |

## 9. Facts

Measured on 2026-11-27, macOS 27.0, by the spike run from Photos' Share menu
(`build/spike-revert/`, not committed; its result files are deleted):

| Label | Fact                                                                                                                                                                                                                                                                                                             |
| ----- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| T0    | PhotoKit found all 8 stills by the ids `export.applescript` gives (`localIdentifier`, `UUID/L0/001`)                                                                                                                                                                                                             |
| T1    | PhotoKit's status inside a Run AppleScript is 0, and that process has no usage text: it can't be the one that asks                                                                                                                                                                                               |
| T2    | An app started from Run Shell Script with `open -W -n -g -a App --stdout F --stderr F --args ask` made macOS ask, naming the app; after Allow its status was 3                                                                                                                                                   |
| T3    | After that, the app's program run by its path from the same script had status 3 and read photos. Creating by path wasn't tried                                                                                                                                                                                   |
| T4    | An applet built inside the shortcut (`osacompile`, `plutil`, `codesign`) asked, read an edit and created a photo. Not used: a Swift app can be tested and signed                                                                                                                                                 |
| T5    | A rebuild (same identifier, ad hoc, so another `cdhash`) had status 0 and asked again; after that the first build had status 0: its grant was replaced                                                                                                                                                           |
| G1    | `PHAssetCreationRequest` with types 1 (the original), 7 (`Adjustments.plist`) and 5 (Photos' rendering) created a photo with `hasAdjustments`, format `com.apple.photo` (versions 1.5 and 1.12 seen), resources 1, 7, 5; its current picture was the rendering byte for byte; an editing input returned the edit |
| G2    | The same with a HEIC base (`photobatch --heic --rf 26`) and a JPEG XL base (`-q 83 -e 7`), on an adjusted photo, one stored with orientation 3, one rotated in Photos, one cropped                                                                                                                               |
| G3    | Created without type 5: a rendering resource without data; on the Mac the thumbnails stayed gray for 15 minutes or more. Never do this                                                                                                                                                                           |
| G4    | `revertAssetContentToOriginal()` on created photos with either base: no adjustments, only resource 1 left                                                                                                                                                                                                        |
| G5    | A HEIC look (`photobatch`'s copy of the rendering) was stored byte for byte. A JPEG XL look was not: Photos stored a JPEG of its own, 2.5 times larger, and for the photo stored with orientation 3 its picture differed strongly from Photos' rendering                                                         |
| G6    | Photos' AppleScript `media item id <PhotoKit's id>` finds a created photo; setting keywords and adding it to an album work                                                                                                                                                                                       |
| W1    | Photos' `import` of a HEIC base, a HEIC look (`IMG_E9001.heic`) and the plist as `IMG_9001.AAE` gave one edited photo. Tried once                                                                                                                                                                                |
|       | Not tried: editing a copy again in Photos; how copies with a look show on the iPhone. An edited JPEG (`IMG_1711.JPG`) has `mediaSubtypes` 528, which includes `photoDepthEffect`. Deleting through PhotoKit asks the user to confirm                                                                             |

Found the same day without the library:

| Label | Fact                                                                                                                                                                                                                                                                                                 | How                                                                                    |
| ----- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| P1    | Photos writes an edit's data as JSON compressed with raw DEFLATE, which `NSData.decompressed(using: .zlib)` reads. It must have `adjustments` and `metadata` with `masterWidth`, `masterHeight` and `orientation`; each adjustment needs an `identifier` that Photos knows                           | `PICompositionSerializer`'s class methods in PhotoImaging, called from a small program |
| P2    | Photos' names for the parts of an edit, among them `DepthEffect`, `PortraitEffect`, `SemanticStyle`, `TextureStyle`, `Inpaint`, `InpaintMasks`, `GenerativeEdits`, `RKRetouchOperation`, and those of 3.2. It reads format versions 1.4 to 1.14                                                      | `PICompositionSerializerConstants`, `PICompositionSerializerFormatVersion`             |
| P3    | A draft of the helper compiles (`swiftc`, macOS 27 SDK, for macOS 14). Its plist rules gave the expected answer for 12 made-up plists. Its geometry rule: `hdr/grid_o6.heic` and its HEIC copy are both 48x64 with orientation 6; its JPEG XL copy is 64x48 with orientation 1                       | run here; `photobatch` 0.12.0                                                          |
| P4    | The bundle signed ad hoc has the requirement `cdhash H"..."`. Zipped with `ditto -c -k --norsrc --noextattr --keepParent` (47 KB) and unpacked with `ditto -x -k`, it verifies with the same hash                                                                                                    | run here                                                                               |
| P5    | `security find-identity -v -p codesigning` lists no identity (from the agent's shell, which may not see the login keychain)                                                                                                                                                                          | run here                                                                               |
| P6    | `supportsAssetResourceTypes`: 1+7+5 true, 1+7 true, 1+5 false, 7 alone false                                                                                                                                                                                                                         | run here                                                                               |
| P7    | The SDK: `revertAssetContentToOriginal` keeps "adjustments applied by the camera pipeline at capture time (e.g. Portrait bokeh, Night mode)"; resource types may be ones the SDK doesn't define, and a backup must keep them all; a creation request copies its files unless `shouldMoveFile` is set | `PHAssetChangeRequest.h`, `PhotosTypes.h`, `PHAssetCreationRequest.h`                  |
| P8    | Photos' AppleScript has no "edited" property and no access to an edit. The public way to edit a photo (`PHContentEditingOutput`) refuses, from other apps, data whose identifier starts with `com.apple.`                                                                                            | `Photos.sdef`; iOS 18.2's Photos framework, decompiled                                 |
