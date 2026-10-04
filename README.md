# photo-video-shortcuts

Shortcuts for iPhone and Mac that compress your photos and videos while keeping
their metadata (capture date, location, camera) and their albums. On iPhone,
the heavy lifting runs in [a-Shell](https://holzschu.github.io/a-Shell_iOS/), a
free terminal app, because iOS has no JPEG XL encoder or quality-controlled
video encoder of its own. On the Mac, Shortcuts runs the same encoder itself
(Run Shell Script).

| Shortcut                                               | What it does                                                                                          | iPhone             | Mac                                                                       |
| ------------------------------------------------------ | ----------------------------------------------------------------------------------------------------- | ------------------ | ------------------------------------------------------------------------- |
| [Compress Photos](shortcuts/compress-photos/README.md) | Still photos (HEIF, JPEG and PNG) → JPEG XL, saved back to Photos; Live Photos and videos are skipped | Yes (with a-Shell) | [Yes](shortcuts/compress-photos/README-mac.md) (Apple silicon, macOS 14+) |
| [Compress Videos](shortcuts/compress-videos/README.md) | Videos → smaller H.265 or AV1 copies                                                                  | Coming soon        | Planned                                                                   |

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. Installation](#1-installation)
  - [1.1. On iPhone](#11-on-iphone)
    - [1.1.1. Every shortcut: a-Shell (once)](#111-every-shortcut-a-shell-once)
    - [1.1.2. Compress Photos](#112-compress-photos)
    - [1.1.3. Compress Videos](#113-compress-videos)
  - [1.2. On Mac](#12-on-mac)
- [2. Updating](#2-updating)
- [3. Repository layout](#3-repository-layout)
- [4. Developing](#4-developing)
- [5. License](#5-license)

______________________________________________________________________

<!--TOC-->

## 1. Installation

### 1.1. On iPhone

#### 1.1.1. Every shortcut: a-Shell (once)

1. Install [a-Shell](https://apps.apple.com/app/a-shell/id1473805438) from the
   App Store. It's free.
2. Open a-Shell and create the folder for the encoders. Type or paste this
   line, then tap Return:
   ```
   mkdir -p ~/Documents/bin
   ```

#### 1.1.2. Compress Photos

1. **Install the encoder.** In a-Shell, paste this command and tap Return to
   download the encoder:

   ```
   curl -L -o ~/Documents/bin/jxlbatch.wasm https://github.com/jsh9/photo-video-shortcuts/releases/latest/download/jxlbatch.wasm
   ```

   When the download has finished and the prompt is back, paste this command
   and tap Return to check that the encoder works:

   ```
   jxlbatch --selftest
   ```

   It should end with "Self-test passed". Its encode test takes a few seconds.

   If a-Shell says "The WebAssembly interpreter is not running", close a-Shell
   (swipe it away in the app switcher), reopen it, wait a few seconds, and run
   the command again.

   If a-Shell reports a WebAssembly compile error, download
   `jxlbatch-scalar.wasm` instead, saved as `jxlbatch.wasm`. That build has no
   SIMD, so it's slower.

2. **Add the shortcuts.** On the iPhone, open the
   [Releases page](https://github.com/jsh9/photo-video-shortcuts/releases), and
   from the latest release download `compress-photos-shortcuts-v<version>.zip`
   (for example `compress-photos-shortcuts-v0.1.0.zip`). In the Files app, tap
   the ZIP to unzip it, open the folder it creates, and tap each of the two
   shortcuts, *Compress Photos* and *JXL-Import* → Add Shortcut. **Keep the
   name JXL-Import exactly**: a-Shell starts it by name.

3. **Grant permissions.** Run *Compress Photos* once from the Shortcuts app
   with one photo. Allow it to access a-Shell and Photos when asked.

How to use it: [Compress Photos](shortcuts/compress-photos/README.md).

#### 1.1.3. Compress Videos

Coming soon.

### 1.2. On Mac

Apple silicon, macOS 14 or later. No a-Shell: Shortcuts runs the encoder
itself.

1. **Install the encoder.** In Terminal, paste this line and press Return:

   ```
   mkdir -p ~/.local/bin && curl -L -o ~/.local/bin/jxlbatch https://github.com/jsh9/photo-video-shortcuts/releases/latest/download/jxlbatch-macos && chmod +x ~/.local/bin/jxlbatch && ~/.local/bin/jxlbatch --selftest
   ```

   It should end with "Self-test passed".

2. **Allow scripts.** Shortcuts ▸ Settings ▸ Advanced ▸ **Allow Running
   Scripts**.

3. **Add the shortcuts.** From the latest
   [release](https://github.com/jsh9/photo-video-shortcuts/releases) download
   `compress-photos-mac-shortcuts-v<version>.zip`, unzip it, and double-click
   each of the two shortcuts, *Compress Photos (macOS)* and *Compress Photo
   Files (macOS)* → Add Shortcut.

4. **Grant permissions.** Run *Compress Photos (macOS)* once from the Shortcuts
   app with one photo, and allow Photos access when asked.

How to use them, and what to do if they don't show up in Photos' Share menu or
Finder's Quick Actions:
[Compress Photos (macOS)](shortcuts/compress-photos/README-mac.md).

## 2. Updating

Each shortcut has its own version, shown in the note at the top of the shortcut
and by its encoder (for example `jxlbatch --version`). The
[Releases page](https://github.com/jsh9/photo-video-shortcuts/releases) says
which files each release changed; download only those, the same way as above.
The iPhone and Mac files of a shortcut share its version, so a release may
change only one platform's files.

## 3. Repository layout

| Path                | What it is                                                                                                                  |
| ------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `shortcuts/<name>/` | one folder per shortcut: its README (and README-mac.md for the Mac), developer notes, encoder source and build scripts      |
| `docs/`             | documentation shared by all shortcuts                                                                                       |
| `tests/`            | tests (see [tests/README.md](tests/README.md)); `tests/samples/` holds your own test photos and videos and is not committed |
| `licenses/`         | licenses of the third-party libraries built into the release files                                                          |

## 4. Developing

How each shortcut works, how to build and test it, and how to release it is in
its developer notes:

- [Compress Photos](shortcuts/compress-photos/DEVELOPING.md), including
  [releasing a new version](shortcuts/compress-photos/DEVELOPING.md#6-releasing-a-new-version).

## 5. License

GPL-3.0-or-later; see [LICENSE](LICENSE). The release files include third-party
libraries under their own licenses; see [licenses](licenses/README.md).
