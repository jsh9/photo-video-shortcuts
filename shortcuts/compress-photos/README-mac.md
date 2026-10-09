# Compress Photos (macOS): JPEG XL for Photos and Finder on the Mac

Two shortcuts for the Mac, with the same encoder and the same results as the
iPhone's [Compress Photos](README.md):

- **Compress Photos (macOS)**: select photos in Photos ▸ Share ▸ *Compress
  Photos (macOS)* (or right-click ▸ Shortcuts), or run it from the Shortcuts
  app, the menu bar or a keyboard shortcut and pick the photos in its photo
  picker. Pick a quality preset (83 is the everyday choice), how to use the
  cores, and whether to keep HDR. JPEG XL copies are saved to Photos, into the
  same albums as the originals, keeping the original's metadata (capture date,
  location, camera, lens, exposure, maker notes, XMP) and, if you keep it, its
  HDR. The converted originals are collected in the album *Compressed to JXL*
  for you to review and delete; the shortcut deletes nothing. Only still photos
  are converted; Live Photos and videos are skipped.
- **Compress Photo Files (macOS)**: select image files or folders in Finder ▸
  right-click ▸ Quick Actions ▸ *Compress Photo Files (macOS)*. Each `.jxl` is
  written next to its original, under the original's name. Nothing is deleted,
  and Photos is not involved.

On the Mac, Shortcuts runs the encoder itself: its Run Shell Script action runs
`jxlbatch`, a native build of the same encoder a-Shell runs on the iPhone, and
waits for it. There is no a-Shell, no *JXL-Import*, and nothing to keep in the
foreground. The results are byte for byte the iPhone's (same libjxl, same
settings), and the Mac can use all of its cores, converting several photos at a
time.

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. Requirements](#1-requirements)
- [2. Installation](#2-installation)
- [3. Use](#3-use)
  - [3.1. Compress Photos (macOS)](#31-compress-photos-macos)
  - [3.2. Compress Photo Files (macOS)](#32-compress-photo-files-macos)
- [4. What is and isn't kept](#4-what-is-and-isnt-kept)
- [5. Updating](#5-updating)
- [6. Troubleshooting](#6-troubleshooting)

______________________________________________________________________

<!--TOC-->

## 1. Requirements

- A Mac with Apple silicon (M1 or later) running macOS 14 (Sonoma) or later,
  which is when Photos started reading JPEG XL. Intel Macs aren't supported.
- Shortcuts' *Allow Running Scripts* setting (below).
- For *Compress Photos (macOS)* from its picker: iCloud Drive turned on for
  Shortcuts (System Settings ▸ Apple Account ▸ iCloud ▸ Drive ▸ Shortcuts, on
  by default). The converted files pass through Shortcuts' own folder in iCloud
  Drive on their way into Photos, since that is the only place Shortcuts reads
  a file a script wrote; they are removed as soon as they are saved. From a
  selection in Photos, the files pass through a hidden folder in your Pictures
  folder instead (Photos reads and writes it), also removed at the end.
  *Compress Photo Files (macOS)* needs neither.

## 2. Installation

1. **Install the encoder.** Open Terminal (Applications ▸ Utilities) and paste
   this line, then press Return:

   ```
   mkdir -p ~/.local/bin && curl -L -o ~/.local/bin/jxlbatch https://github.com/jsh9/photo-video-shortcuts/releases/latest/download/jxlbatch-macos && chmod +x ~/.local/bin/jxlbatch && ~/.local/bin/jxlbatch --selftest
   ```

   It downloads `jxlbatch` into `~/.local/bin` (a hidden folder; the shortcuts
   know where it is) and runs its self-test, which should end with "Self-test
   passed". `curl` doesn't mark the download as quarantined, so macOS runs it
   without a Gatekeeper prompt. If you downloaded it with a browser instead,
   the file is neither executable nor trusted: run
   `chmod +x ~/.local/bin/jxlbatch` and
   `xattr -d com.apple.quarantine ~/.local/bin/jxlbatch` once (until then the
   shortcuts report the encoder as not installed).

2. **Allow scripts.** In Shortcuts ▸ Settings ▸ Advanced, turn on **Allow
   Running Scripts**. Without it, the shortcuts fail at their Run Shell Script
   step.

3. **Add the shortcuts.** From the latest
   [release](https://github.com/jsh9/photo-video-shortcuts/releases) download
   `compress-photos-mac-shortcuts-v<version>.zip`, double-click it to unzip,
   then double-click each `.shortcut` → Add Shortcut.

4. **Grant permissions.** Run *Compress Photos (macOS)* once from the Shortcuts
   app with one photo, and allow it to access Photos when asked. The first time
   you run it from Photos (select a photo, Share ▸ *Compress Photos (macOS)*),
   macOS asks whether Shortcuts may control Photos: choose Always Allow. (Don't
   Allow makes the shortcut open its picker instead, every time; the permission
   is under System Settings ▸ Privacy & Security ▸ Automation.) For the Share
   menu in Photos, the Shortcuts sharing extension must be enabled (System
   Settings ▸ General ▸ Login Items & Extensions ▸ Sharing); if the shortcut
   isn't offered there, check *Show in Share Sheet* in its details (the ⓘ
   button in the editor). *Compress Photo Files (macOS)* appears in Finder's
   Quick Actions (right-click ▸ Quick Actions); if not, check *Use as Quick
   Action ▸ Finder* in its details.

The iPhone shortcuts (*Compress Photos*, *JXL-Import*) sync to the Mac too, and
these two sync to the iPhone, but each pair runs on its own platform only: the
iPhone's need a-Shell, these need Run Shell Script.

## 3. Use

### 3.1. Compress Photos (macOS)

- **From Photos:** select the photos, then Share ▸ *Compress Photos (macOS)*
  (or right-click ▸ Shortcuts ▸ *Compress Photos (macOS)*, or the menu bar
  while Photos is in front). The shortcut takes the photos selected in Photos.
  The first time, macOS asks whether Shortcuts may control Photos: click OK.
  - Photos exports the **original files** (the HEIC as it was imported, with
    its HDR), the copies are imported into the originals' albums, and the
    originals of the imported copies go into the album **Compressed to JXL**.
    Review that album and delete its photos when you are done (a shortcut
    cannot delete photos on this path). The album stays, empty, for the next
    run.
  - An **edited photo** is converted from its unedited original on this path:
    the edits aren't applied. To convert the edited version, use the picker.
    - Shortcuts never sees the photos Photos would hand over through the Share
      menu (on macOS 26 that is a JPEG copy Shortcuts can't read), which is why
      the shortcut asks Photos for the selection instead. If two selected
      photos have the same file name, their copies are saved but not added to
      albums, and neither original is collected, since the exported files can't
      be told apart; the log says so.
- **From the Shortcuts app** (or the menu bar, if you pin it, or a keyboard
  shortcut you give it) while Photos is not in front: a photo picker opens,
  without videos. Pick the photos there. This path converts each photo as it
  looks now (edits applied) and saves the copies to Photos. The originals of
  the saved copies go into the album **Compressed to JXL** too (a photo already
  in it isn't added twice).
- Only still photos are converted, screenshots included; Live Photos and videos
  in the selection are skipped and a notification counts them. To convert the
  still image of a Live Photo, duplicate it as a still photo first.
- Pick a quality (see [Quality presets](README.md#21-quality-presets); they are
  the same as on the iPhone).
- Then pick how to use the Mac's cores. *All cores (fast)*, the usual choice,
  converts several photos at a time, each with a share of the cores (two at a
  time on an 8-core Mac, three on 14 cores or more, fewer with little memory).
  *One core (keeps the Mac responsive)* converts one photo at a time on one
  thread, for a big batch while you keep working. The files are the same either
  way.
- A notification says the conversion has started. It runs in the background:
  about a second per 12 MP photo on an M1, longer for 48 MP. A notification
  says how many were saved.
- Each JPEG XL copy is saved to Photos with its original's name, into every
  album its original is in (one photo, not a copy per album). Shared albums and
  built-in ones such as Favorites aren't handled.
- The second question, **Cores to use**, and the third, **HDR**: *Keep HDR*
  converts an HDR photo to an HDR JPEG XL (see
  [HDR photos](README.md#31-hdr-photos)); *Drop HDR* saves every photo as an
  ordinary SDR JPEG XL, smaller, without the color banding an HDR JPEG XL can
  show in smooth skies, and shown correctly by viewers that can't tone-map HDR
  (XnView MP, for example). The originals keep their HDR either way until you
  delete them.
- If the encoder noted anything (an HDR photo converted as SDR, a photo that
  failed, an error), its log opens in a Quick Look window first, so you can
  read it before deciding about the originals. Close it to continue.
- The converted originals are collected in the album *Compressed to JXL* (from
  Photos, found by their photo id; from the picker, by the photos themselves),
  whether or not their JPEG XL has their HDR: the log says which don't
  (`! HDR gain map not used`; with *Drop HDR*, none has it, and the log's
  `HEIF` lines show no `HDR`). Nothing is deleted by the shortcut: review the
  album, select all, delete. (Shortcuts' Delete Photos action needs a prompt
  the Shortcuts app usually can't show on macOS 26, so the Mac shortcut doesn't
  use it.) The first time, macOS asks whether Shortcuts may control Photos:
  choose Always Allow, or it asks on every run.
- **Progress:** a Terminal window opens and follows the conversion, photo by
  photo, as a-Shell shows it on the iPhone; with *All cores*, a photo's lines
  appear once the photos before it are done (the log it follows is in
  `~/Library/Caches/compress-photos-macos`, one per route, so Terminal needs no
  access to iCloud Drive or Pictures). When everything is done it ends with
  "Done. You can close this window." The last run's log stays in that folder
  (`photos-selection.log`, `photos-picker.log` or `files.log`). (Terminal may
  close it by itself, depending on its "When the shell exits" setting.) To do
  without it, open the shortcut in Shortcuts, find the Run Shell Script action
  whose script starts with `# Compress Photos (macOS)`, and change its line
  `WATCH=${WATCH:-1}` to `WATCH=0`. The log also opens in Quick Look when it
  has a note, an error or a failed photo.
- If Photos is set not to copy imported items into the library (Photos ▸
  Settings ▸ General ▸ Importing), the imported copies reference the files in
  the shortcut's hidden work folder in Pictures, which the next run empties:
  don't use the selection path with that setting, or move the copies out of the
  folder before the next run. Deleted photos go to Recently Deleted for 30
  days. Deleting also removes what the JPEG XL doesn't have: depth data, the
  SDR version of an HDR photo, edit history and Photos-only information
  (favorites, captions, people).
- Photos may list the copies under Duplicates. Merging keeps only one file, so
  check which one before you merge.
- With iCloud Photos and *Optimize Mac Storage*, Shortcuts downloads each
  original first; a large batch takes longer and needs a connection.

### 3.2. Compress Photo Files (macOS)

- Select files or folders in Finder, right-click ▸ Quick Actions ▸ *Compress
  Photo Files (macOS)*, and pick a quality and how to use the cores (as above).
  For a folder, its image files (HEIF, JPEG, PNG) are converted; subfolders
  aren't entered.
- Each result is written next to its original as `Name.jxl`. A file is never
  replaced: if `Name.jxl` exists, the result is `Name 2.jxl`. If the folder
  can't be written, or Shortcuts didn't say where a file came from, the result
  goes to `~/Pictures/JPEG XL`.
- A Terminal window follows the progress (as above); the log opens in Quick
  Look when something was noted or failed; a notification says how many files
  were written. The originals are never touched.

## 4. What is and isn't kept

The same as on the iPhone: see
[What is and isn't kept](README.md#3-what-is-and-isnt-kept),
[HDR photos](README.md#31-hdr-photos) and [Dates](README.md#32-dates). The Mac
shortcuts get the photos from Shortcuts as files, as the iPhone shortcut does
from the share sheet, and the encoder is the same; an edited photo is converted
as it looks now. Each copy gets the date Photos shows for its original, in
Photos and in its EXIF, also a date you changed in Photos (Image ▸ Adjust Date
and Time) and for a photo without a capture date of its own; from Photos (the
selection), a copy that Photos dated differently on import is given its
original's date. The Finder shortcut's files keep their own dates.

## 5. Updating

Each release says which files changed. To update the encoder, run the install
command from [Installation](#2-installation) again. To update the shortcuts,
add the new `.shortcut` files; Shortcuts replaces the old ones. The shortcuts
check the encoder's version and note a mismatch in the log.

## 6. Troubleshooting

| Symptom                                                                                                                              | Fix                                                                                                                                                                                                                                                                                                                                                    |
| ------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| The shortcut stops at Run Shell Script with an error about scripts                                                                   | Turn on Shortcuts ▸ Settings ▸ Advanced ▸ Allow Running Scripts.                                                                                                                                                                                                                                                                                       |
| Quick Look shows `ERROR: jxlbatch is not installed`                                                                                  | Run the install command from [Installation](#2-installation). The shortcuts look in `~/.local/bin`, `~/bin`, `/usr/local/bin` and `/opt/homebrew/bin` for an executable file named `jxlbatch`: a file downloaded with a browser isn't executable until you run `chmod +x ~/.local/bin/jxlbatch` (and `xattr -d com.apple.quarantine` on it).           |
| `"jxlbatch" cannot be opened because the developer cannot be verified`                                                               | The file was downloaded with a browser and quarantined. Run `xattr -d com.apple.quarantine ~/.local/bin/jxlbatch`, or install it with the `curl` command instead.                                                                                                                                                                                      |
| `! … is not jxlbatch <version>` in the log, or `usage: jxlbatch …`                                                                   | The encoder and the shortcuts are from different releases (an older encoder doesn't know the shortcuts' options and prints its usage instead of converting). Update the older one (see [Updating](#5-updating)).                                                                                                                                       |
| The shortcut isn't in Photos' Share menu                                                                                             | Enable the Shortcuts extension in System Settings ▸ General ▸ Login Items & Extensions ▸ Sharing, and *Show in Share Sheet* in the shortcut's details.                                                                                                                                                                                                 |
| *Compress Photo Files (macOS)* isn't in Finder's Quick Actions                                                                       | Check *Use as Quick Action ▸ Finder* in the shortcut's details.                                                                                                                                                                                                                                                                                        |
| Notification "Saved 0 photo(s)" and Quick Look shows the log                                                                         | No photo converted; the log says why for each one (for example `unsupported format` for a RAW file).                                                                                                                                                                                                                                                   |
| `! not saved to Photos: <name>` in the log                                                                                           | The converted file didn't reach Photos; its original is kept. Usually iCloud Drive is off for Shortcuts (see [Requirements](#1-requirements)); the log says so when its folder is missing.                                                                                                                                                             |
| Run from Photos' Share menu, but asked to pick photos                                                                                | Photos wasn't in front with a selection when the shortcut asked it (the shortcut gets nothing through the Share menu itself: Photos passes a JPEG copy that Shortcuts can't read). Select the photos in Photos and run it again from there.                                                                                                            |
| "Shortcuts is not allowed to send keystrokes" or Photos not responding to the shortcut                                               | Allow Shortcuts to control Photos: System Settings ▸ Privacy & Security ▸ Automation ▸ Shortcuts ▸ Photos.                                                                                                                                                                                                                                             |
| `! HDR gain map not used`, `! Apple's HDR profile not found`, and so on                                                              | The same notes as on the iPhone; see [Troubleshooting](README.md#4-troubleshooting) there. Their originals are in the album *Compressed to JXL* like the others; the notes tell you which to keep.                                                                                                                                                     |
| Results in `~/Pictures/JPEG XL` instead of next to the files                                                                         | Shortcuts passed copies of the files without saying where they came from, or the folder isn't writable. Please report it, with how the files were selected.                                                                                                                                                                                            |
| A green horizontal stripe near the bottom of a photo converted on the iPhone (thumbnail and preview; gone once the full photo loads) | A bug in Photos on iOS 27, which writes a faulty 2048×1536 preview for 12 MP JPEG XL files saved to Photos on an iPhone, whatever made them; the JXL is fine, and photos converted or imported on the Mac get a correct preview. See [Troubleshooting](README.md#4-troubleshooting) on the iPhone page for the details and how to fix affected photos. |
