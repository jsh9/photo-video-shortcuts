# Compress Photos (macOS): JPEG XL for Photos and Finder on the Mac

Two shortcuts for the Mac, with the same encoder and the same results as the
iPhone's [Compress Photos](README.md):

- **Compress Photos (macOS)**: run it from the Shortcuts app (or the menu bar,
  or a keyboard shortcut) and pick the photos in its photo picker; from Photos'
  Share menu it opens the same picker (see [Use](#3-use)). Pick a quality
  preset (83 is the everyday choice). JPEG XL copies are saved to Photos, into
  the same albums as the originals, keeping the original's metadata (capture
  date, location, camera, lens, exposure, maker notes, XMP) and its HDR. Then
  it offers to **delete the originals** whose JPEG XL has everything they have.
  Only still photos are converted; Live Photos and videos are skipped.
- **Compress Photo Files (macOS)**: select image files or folders in Finder ▸
  right-click ▸ Quick Actions ▸ *Compress Photo Files (macOS)*. Each `.jxl` is
  written next to its original, under the original's name. Nothing is deleted,
  and Photos is not involved.

On the Mac, Shortcuts runs the encoder itself: its Run Shell Script action runs
`jxlbatch`, a native build of the same encoder a-Shell runs on the iPhone, and
waits for it. There is no a-Shell, no *JXL-Import*, and nothing to keep in the
foreground. The results are byte for byte the iPhone's (same libjxl, same
settings), and the Mac uses all of its cores.

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
- For *Compress Photos (macOS)*: iCloud Drive turned on for Shortcuts (System
  Settings ▸ Apple Account ▸ iCloud ▸ Drive ▸ Shortcuts, on by default). The
  converted files pass through Shortcuts' own folder in iCloud Drive on their
  way into Photos, since that is the only place Shortcuts reads a file a script
  wrote; they are removed as soon as they are saved. *Compress Photo Files
  (macOS)* doesn't need it.

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
   run `xattr -d com.apple.quarantine ~/.local/bin/jxlbatch` once.

2. **Allow scripts.** In Shortcuts ▸ Settings ▸ Advanced, turn on **Allow
   Running Scripts**. Without it, the shortcuts fail at their Run Shell Script
   step.

3. **Add the shortcuts.** From the latest
   [release](https://github.com/jsh9/photo-video-shortcuts/releases) download
   `compress-photos-mac-shortcuts-v<version>.zip`, double-click it to unzip,
   then double-click each `.shortcut` → Add Shortcut.

4. **Grant permissions.** Run *Compress Photos (macOS)* once from the Shortcuts
   app with one photo, and allow it to access Photos when asked. For the Share
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

- **From the Shortcuts app** (or the menu bar, if you pin it, or a keyboard
  shortcut you give it): a photo picker opens, without videos. Pick the photos
  there.
- **From Photos' Share menu** (Share ▸ *Compress Photos (macOS)*, or
  right-click ▸ Shortcuts): the same picker opens, and the photos you had
  selected in Photos are *not* preselected. On macOS 26, Photos hands a
  shortcut a JPEG copy that Shortcuts can't read, so the shortcut receives
  nothing and asks instead. The picker gives the original files (HEIC, HDR),
  which the Share menu wouldn't have anyway.
- Only still photos are converted, screenshots included; Live Photos and videos
  in the selection are skipped and a notification counts them. To convert the
  still image of a Live Photo, duplicate it as a still photo first.
- Pick a quality (see [Quality presets](README.md#21-quality-presets); they are
  the same as on the iPhone).
- A notification says the conversion has started. It runs in the background:
  about a second per 12 MP photo on an M1, longer for 48 MP. A notification
  says how many were saved.
- Each JPEG XL copy is saved to Photos with its original's name, into every
  album its original is in (one photo, not a copy per album). Shared albums and
  built-in ones such as Favorites aren't handled.
- If the encoder noted anything (an HDR photo converted as SDR, a photo that
  failed, an error), its log opens in a Quick Look window first, so you can
  read it before deciding about the originals. Close it to continue.
- Then Shortcuts asks whether the shortcut may delete photos (choose Always
  Allow to skip that question next time), and macOS asks "Delete N photos?" for
  the originals whose JPEG XL has everything they have (the same rule as on the
  iPhone, see [HDR photos](README.md#31-hdr-photos)): click Don't Allow to keep
  them all, or Delete. Keep the Shortcuts app in front until then: the prompts
  need it (see [Troubleshooting](#6-troubleshooting)). Deleted photos go to
  Recently Deleted for 30 days. Deleting also removes what the JPEG XL doesn't
  have: depth data, the SDR version of an HDR photo, edit history and
  Photos-only information (favorites, captions, people). Unlike the iPhone,
  this is offered from the Share menu too, since the shortcut keeps the
  originals in hand.
- Photos may list the copies under Duplicates. Merging keeps only one file, so
  check which one before you merge.
- With iCloud Photos and *Optimize Mac Storage*, Shortcuts downloads each
  original first; a large batch takes longer and needs a connection.

### 3.2. Compress Photo Files (macOS)

- Select files or folders in Finder, right-click ▸ Quick Actions ▸ *Compress
  Photo Files (macOS)*, and pick a quality. For a folder, its image files
  (HEIF, JPEG, PNG) are converted; subfolders aren't entered.
- Each result is written next to its original as `Name.jxl`. A file is never
  replaced: if `Name.jxl` exists, the result is `Name 2.jxl`. If the folder
  can't be written, or Shortcuts didn't say where a file came from, the result
  goes to `~/Pictures/JPEG XL`.
- The log opens in Quick Look when something was noted or failed; a
  notification says how many files were written. The originals are never
  touched.

## 4. What is and isn't kept

The same as on the iPhone: see
[What is and isn't kept](README.md#3-what-is-and-isnt-kept) and
[HDR photos](README.md#31-hdr-photos). The Mac shortcuts get the photos from
Shortcuts as files, as the iPhone shortcut does from the share sheet, and the
encoder is the same; an edited photo is converted as it looks now.

## 5. Updating

Each release says which files changed. To update the encoder, run the install
command from [Installation](#2-installation) again. To update the shortcuts,
add the new `.shortcut` files; Shortcuts replaces the old ones. The shortcuts
check the encoder's version and note a mismatch in the log.

## 6. Troubleshooting

| Symptom                                                                  | Fix                                                                                                                                                                                                                                                                                                                                                                                 |
| ------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| The shortcut stops at Run Shell Script with an error about scripts       | Turn on Shortcuts ▸ Settings ▸ Advanced ▸ Allow Running Scripts.                                                                                                                                                                                                                                                                                                                    |
| Quick Look shows `ERROR: jxlbatch is not installed`                      | Run the install command from [Installation](#2-installation). The shortcuts look in `~/.local/bin`, `~/bin`, `/usr/local/bin` and `/opt/homebrew/bin`.                                                                                                                                                                                                                              |
| `"jxlbatch" cannot be opened because the developer cannot be verified`   | The file was downloaded with a browser and quarantined. Run `xattr -d com.apple.quarantine ~/.local/bin/jxlbatch`, or install it with the `curl` command instead.                                                                                                                                                                                                                   |
| `! … is not jxlbatch <version>` in the log                               | The encoder and the shortcuts are from different releases. Update the older one (see [Updating](#5-updating)).                                                                                                                                                                                                                                                                      |
| The shortcut isn't in Photos' Share menu                                 | Enable the Shortcuts extension in System Settings ▸ General ▸ Login Items & Extensions ▸ Sharing, and *Show in Share Sheet* in the shortcut's details.                                                                                                                                                                                                                              |
| *Compress Photo Files (macOS)* isn't in Finder's Quick Actions           | Check *Use as Quick Action ▸ Finder* in the shortcut's details.                                                                                                                                                                                                                                                                                                                     |
| Notification "Saved 0 photo(s)" and Quick Look shows the log             | No photo converted; the log says why for each one (for example `unsupported format` for a RAW file).                                                                                                                                                                                                                                                                                |
| `! not saved to Photos: <name>` in the log                               | The converted file didn't reach Photos; its original is kept. Usually iCloud Drive is off for Shortcuts (see [Requirements](#1-requirements)); the log says so when its folder is missing.                                                                                                                                                                                          |
| "This action could not be run with the current user interface" at Delete | The copies are saved; nothing was deleted. Shortcuts could not show its deletion prompt, which happens when it loses its window mid-run (for example after switching to Photos while the shortcut runs). Delete the originals by hand, or run the shortcut again and stay in the Shortcuts app; choose Always Allow at the prompt. Deleting is never available from the Share menu. |
| Run from Photos' Share menu, but asked to pick photos                    | Expected on macOS 26: Photos passes a JPEG copy that Shortcuts can't read, so the shortcut receives nothing and opens its picker. Pick the photos there.                                                                                                                                                                                                                            |
| `! HDR gain map not used`, `! Apple's HDR profile not found`, and so on  | The same notes as on the iPhone; see [Troubleshooting](README.md#4-troubleshooting) there. They decide which originals are offered for deletion.                                                                                                                                                                                                                                    |
| Results in `~/Pictures/JPEG XL` instead of next to the files             | Shortcuts passed copies of the files without saying where they came from, or the folder isn't writable. Please report it, with how the files were selected.                                                                                                                                                                                                                         |
