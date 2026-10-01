# Compress Photos: JPEG XL for iPhone Photos

Select photos in Photos → Share → **Compress Photos** → pick a quality preset
(83 is the everyday choice). JPEG XL copies are saved back to Photos, into the
same albums as the originals, keeping the original's metadata: capture date,
time and time zone, GPS location, camera, lens, exposure, maker notes, and XMP.
Started from the Shortcuts app instead, it lets you pick the photos and then
offers to delete the originals.

iOS can display JPEG XL but has no encoder, so the conversion runs in
[a-Shell](https://holzschu.github.io/a-Shell_iOS/) as a small WebAssembly tool,
`jxlbatch`. It uses libjxl, the reference JPEG XL encoder. How it works, and
how to build it: [DEVELOPING.md](DEVELOPING.md).

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. Installation](#1-installation)
- [2. Use](#2-use)
  - [2.1. Quality presets](#21-quality-presets)
- [3. What is and isn't kept](#3-what-is-and-isnt-kept)
- [4. Troubleshooting](#4-troubleshooting)

______________________________________________________________________

<!--TOC-->

## 1. Installation

See [Installation](../../README.md#1-installation) in the main README.

## 2. Use

- **Two ways to start it:**
  - **From the Shortcuts app** (tap it, or ▶ in the editor): it shows a photo
    picker. Photos picked there come straight from the library, so the original
    HEIF is used. When the JXL copies are saved, it **offers to delete the
    originals**, only those whose JXL was saved.
    - iOS asks you to confirm ("Delete N photos?"). Tap Don't Allow to keep
      them.
    - Deleted photos go to Recently Deleted for 30 days.
    - Deleting also removes what the JXL doesn't have: the Live Photo video,
      depth/Portrait data, the HDR gain map, edit history, and Photos-only
      information (favorites, captions, people). Albums are kept, because the
      JXL is added to them.
    - It must run inside the Shortcuts app. Started from a Home Screen icon,
      widget or the Action Button, it can't wait for a-Shell, because
      Shortcuts' Wait to Return only works inside the app. It then stops at
      once with "File jxl_done.txt not found".
  - **From Photos:** select photos ▸ Share ▸ **Compress Photos**. Originals are
    never deleted this way. The share sheet's **Send As** option decides the
    format. Its default, Automatic, converts HEIF to JPEG, so the shortcut gets
    a JPEG copy, and the sizes shown compare against it. To send originals, tap
    **Options** at the top of the share sheet and set Send As to **Current**.
    iOS offers no way to make that the default, and a shortcut can't set it.
    `jxlbatch` prints a reminder when it receives iPhone photos as JPEG.
- Either way, pick a quality from the list (see
  [Quality presets](#21-quality-presets)).
- a-Shell opens and shows progress for each photo. **Keep it in the foreground
  until it switches back to Shortcuts by itself.**
  - iOS pauses a-Shell in the background.
  - When started from the Shortcuts app, switching back early makes the
    shortcut continue before the conversion is done. It then saves nothing and
    deletes nothing.
- The JXL copies sort next to the originals because they share the capture
  date. A notification shows how many were saved.
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

| Quality          | What to expect                                                                                                              |
| ---------------- | --------------------------------------------------------------------------------------------------------------------------- |
| 88               | Almost placebo: very little visual degradation (even the most challenging scene, the sunset sky, can be rendered very well) |
| **83** (default) | Go-to option for everyday scenes (almost perfect blue sky); film grains well preserved                                      |
| 72               | Details well preserved, but tiny color banding in blue sky; film grains start to get affected                               |
| 63               | Details well preserved; a bit more color banding in blue sky                                                                |
| 52               | Small losses in details; more color banding in blue sky                                                                     |
| 40               | Visible losses in details; color blotches in blue sky                                                                       |
| 30               | More losses in details; bigger color blotches in blue sky                                                                   |
| 20               | Details get smudged; color artifacts in blue sky                                                                            |
| 10               | It’s like watching RMVB videos in 2002                                                                                      |
| 5                | It’s like watching bad RMVB videos in 2002                                                                                  |

- Shortcuts menus show only a title and can't pre-select an option. So each
  preset is a contact card: the number is the name, and the description is the
  company line shown under it. The default is marked "(default)" in its title.
- Tapping a preset picks it and continues.
- To change the presets, edit the first Text action in *Compress Photos* on the
  phone, or `QUALITY_PRESETS` in `scripts/build_shortcuts.py` and rebuild (see
  [DEVELOPING.md](DEVELOPING.md)).

Effort is fixed at 7, `cjxl`'s default. To trade a little size for speed, edit
the Execute Command action in *Compress Photos* and change `-e 7` to `-e 5`.

## 3. What is and isn't kept

Kept:

- all EXIF: date, time and time zone, GPS, camera and lens, exposure, maker
  notes;
- XMP;
- the color profile, e.g. Display P3, and 10-bit precision;
- the file name, e.g. `IMG_1234.jxl`.

Not kept:

- **Live Photo video**, depth/Portrait data, and the **HDR gain map**. The
  result is the standard-dynamic-range still.
- **Edits**: an edited photo is converted as it looks now; the edit can't be
  reverted.
- **IPTC**, which has no standard place in JPEG XL. iPhone photos don't
  normally have any.
- **RAW/ProRAW (DNG) and other formats** aren't converted; only HEIF, JPEG and
  PNG are. Other photos fail with "unsupported format" and the rest of the
  batch continues.

Photos may list the JXL copies under **Duplicates**. Merging a duplicate pair
keeps only one file, so check which one before you merge.

## 4. Troubleshooting

| Symptom                                                                        | Fix                                                                                                                                                                |
| ------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| a-Shell: `jxlbatch: command not found`                                         | `jxlbatch.wasm` isn't in `~/Documents/bin` (On My iPhone ▸ a-Shell ▸ bin).                                                                                         |
| a-Shell stops after the photos, nothing is saved                               | Run **JXL-Import** from the Shortcuts app; it saves whatever finished.                                                                                             |
| "File jxl_done.txt not found"                                                  | No photo converted. Look in a-Shell for the error on each photo. In *Compress Photos*, it also happens when started outside the Shortcuts app (see [Use](#2-use)). |
| a-Shell: "cannot find jxl_job.txt"                                             | a-Shell ran the shortcut outside its Shortcuts folder, which version 0.1.0 does when it has to launch a-Shell. Update the shortcuts and `jxlbatch.wasm`.           |
| a-Shell: "The WebAssembly interpreter is not running" before any photo         | a-Shell's engine hadn't finished starting. The shortcut waits and retries for this, so just run it again.                                                          |
| a-Shell: "The WebAssembly interpreter is not running" in the middle of a photo | iOS stopped a-Shell's engine, usually for using too much memory. Close other apps and try again.                                                                   |
| A photo fails with an out-of-memory error                                      | Large photos, such as 48 MP, need the most memory. Close other apps and retry, or use `-e 5`.                                                                      |
| A photo fails with "unsupported format"                                        | It isn't HEIF, JPEG or PNG (for example ProRAW DNG).                                                                                                               |
| `! orientation check` warning in a-Shell                                       | The converted pixels didn't match the original's orientation. Please report it with the photo's EXIF.                                                              |
