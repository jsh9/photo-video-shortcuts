# Compress Videos (macOS): design plan

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. Verdict](#1-verdict)
- [2. What is reused from Compress Photos (macOS), and what is new](#2-what-is-reused-from-compress-photos-macos-and-what-is-new)
- [3. User-facing design](#3-user-facing-design)
  - [3.1. Name and entry points](#31-name-and-entry-points)
  - [3.2. The questions](#32-the-questions)
  - [3.3. The two routes](#33-the-two-routes)
  - [3.4. What is and isn't kept](#34-what-is-and-isnt-kept)
  - [3.5. Installation (what the README will say)](#35-installation-what-the-readme-will-say)
- [4. Technical design](#4-technical-design)
  - [4.1. The tools: ffmpeg, ffprobe and `vidmeta`](#41-the-tools-ffmpeg-ffprobe-and-vidmeta)
  - [4.2. HandBrake settings as ffmpeg options](#42-handbrake-settings-as-ffmpeg-options)
  - [4.3. The size limit](#43-the-size-limit)
  - [4.4. Audio](#44-audio)
  - [4.5. Metadata: why ffmpeg can't do it, and what exiftool does](#45-metadata-why-ffmpeg-cant-do-it-and-what-exiftool-does)
  - [4.6. The script](#46-the-script)
  - [4.7. Getting files to and from Photos](#47-getting-files-to-and-from-photos)
  - [4.8. Progress and the log](#48-progress-and-the-log)
  - [4.9. Code layout and shared code](#49-code-layout-and-shared-code)
  - [4.10. Versioning, manifest, release and CI](#410-versioning-manifest-release-and-ci)
  - [4.11. Tests](#411-tests)
- [5. Spikes](#5-spikes)
  - [5.1. Done on this Mac (2026-10-05)](#51-done-on-this-mac-2026-10-05)
  - [5.2. Still to run (one throwaway shortcut, about an hour)](#52-still-to-run-one-throwaway-shortcut-about-an-hour)
  - [5.3. Results of 5.2 (2026-10-05, run by the user with throwaway shortcuts)](#53-results-of-52-2026-10-05-run-by-the-user-with-throwaway-shortcuts)
- [6. Implementation phases](#6-implementation-phases)
- [7. Decisions (settled 2026-10-05 unless marked open)](#7-decisions-settled-2026-10-05-unless-marked-open)
- [8. Risks](#8-risks)

______________________________________________________________________

<!--TOC-->

Status: implemented (see the list below); the plan was written 2026-10-05
against Compress Photos 0.5.0 on macOS 27.0 (Shortcuts 8) with Homebrew ffmpeg
9.0.2 (x265 4.3, SVT-AV1 4.2.0, libopus 1.6.1). The iPhone version is out of
scope for now; the folder, version and release layout leave room for it. The
earlier draft in `~/Documents/misc/vid-comp` (iPhone, a-Shell, H.265 only, its
own FFmpeg-library program `vidbatch`) is the source of one thing reused here:
its AVFoundation probe (`avmeta.swift`), for the tests, and its byte-for-byte
metadata copier (`mp4meta.c`), which becomes the `vidmeta` helper (4.5).
Nothing else from it is needed on the Mac: the encoding is done by the ffmpeg
command itself.

**Implemented as Compress Videos 0.1.0** (2026-10-05). The plan below is as
written before the work; what the implementation and the spikes of 5.2 changed
(details in 5.3 and in `shortcuts/compress-videos/DEVELOPING.md`):

- **No picker, no Shortcut Input** (V2, the user's decision): Shortcuts hands a
  script re-rendered copies of picked or shared videos (a slo-mo comes
  rendered), from a folder ffmpeg may not read, and failed on some picked
  videos (AVFoundation -11800). The shortcut converts the selection in Photos
  only; started any other way, it says to select the videos in Photos and use
  the Share menu. So the import script needs no albums-by-name pass, and entry
  points 2 and 3 of 3.1 are gone.
- **Install names** (the user's decision): our tools go to
  `~/.local/bin/compress-videos-ffmpeg` and `compress-videos-ffprobe`, so that
  the minimal build never takes the place of another ffmpeg on the PATH; the
  release files keep their names; the script takes the ffprobe next to the
  ffmpeg it found, named like it.
- **Dolby Vision VBV**: HandBrake gives x265 the **high-tier** rate of the
  Dolby Vision level (x265 allows the high tier by default and HandBrake
  doesn't change it): 70 Mbit/s up to 1080p60, 130 for 4K up to 60 fps, not the
  20/25/40 of 4.2. ffmpeg sets the Dolby Vision level from the size only, so
  the record is the same either way.
- **Slo-mo**: by the iPhone's own mark, the movie key
  `com.apple.quicktime.full-frame-rate-playback-intent` (0 on a slo-mo, 1 on
  the iPhone 17 Pro's other videos), so that a video recorded at 120 fps in
  normal Video mode is converted. Without the key, a video averaging above 61
  fps is taken for slo-mo; `SLOMO=0` turns the rule off. The average, not
  `r_frame_rate` above 100 fps: a variable-rate video can put `r_frame_rate`
  far above its real rate (150 for a Live Photo's video averaging 28), and a
  240 fps slo-mo averages 177. 100 fps wouldn't tell a 120 fps slo-mo from a
  120 fps video either; the key does. ffprobe reads the key's 8-byte integer as
  0, so `vidmeta key` reads it (`mp4meta_key`, added to the draft's
  `mp4meta.c`).
- **V7 failed**: `ffmpeg --version` prints the version line on stderr and exits
  with an error; `release.py` uses `-version` for `ffmpeg-macos` and
  `ffprobe-macos` (the fallback of 5.2).
- Our build decodes AV1 with **dav1d** 1.5.4 (static, software): AV1 videos can
  be converted again, and our ffprobe reports an AV1 copy's pixel format
  (without a decoder, `unknown`), so the 10-bit check applies to AV1 as to
  H.265. FFmpeg's own AV1 decoder was tried first and dropped: it decodes only
  through a hardware accelerator, so an AV1 video in failed. Nothing uses the
  Mac's media engines (the user's requirement): no VideoToolbox in the build,
  and `-hwaccel none` in the command for Homebrew's ffmpeg too. A video whose
  picture ffmpeg can't decode (`ffmpeg -codecs`) is skipped and counted.
- **Apple ProRes** is decoded too (FFmpeg's own decoder, software, no library):
  an iPhone Pro's ProRes 422 HQ, 10-bit 4:2:2, is converted to 4:2:0 by the
  same command. **Apple Log** is skipped: AVFoundation stores the log curve's
  name in a `logs` box of the video's sample description
  (`com.apple.rec2020.apple-log`, or `com.apple.apple-wide-gamut.apple-log` for
  Apple Log 2), with a `colr` whose transfer is 2, unspecified, which ffprobe
  shows as `unknown`. `vidmeta log` reads the box; ProRes with no known
  transfer is skipped as well, in case a recording lacks it. Found by writing
  Apple Log ProRes with AVAssetWriter, not yet on a real recording.
- **Free space** is checked twice: before Photos exports anything, at 500 MB
  per selected item (the count is all the shortcut knows then), and after the
  export, against the exported files' size, as 3.4 planned.
- The log shows the copy's size as ffprobe reads it; Dolby Vision's VBV, which
  must be known before encoding, uses the size computed with libavfilter's
  rounding (`ff_scale_adjust_dimensions`).
- The test videos come from AVFoundation (`make_video.swift`), which on macOS
  27 writes HLG HEVC with Dolby Vision 8.4 (an RPU in every frame), so the
  Dolby Vision path is tested without personal videos.

## 1. Verdict

Feasible, and most of it already exists. *Compress Videos (macOS)* is *Compress
Photos (macOS)* with a different encoder step: the same probe of Photos'
selection, the same AppleScript export of the originals and import of the
results into the originals' albums, the same collection of the originals in an
album, the same Terminal progress window, log and Quick Look. What is new is
the encoder step (one `ffmpeg` command per video, built from the
HandBrake-style choices), a small helper (`vidmeta`) that carries the Apple
metadata over byte for byte (ffmpeg can't, see 4.5), a static ffmpeg build of
ours so that users install nothing else, a video filter instead of the
still-photo filter, and six questions instead of two (one, when the last run's
settings are reused).

Confirmed on this Mac today (details in 5.1):

- ffmpeg with `libx265`, `libsvtav1` and `libopus` encodes an iPhone 4K HEVC
  video and an HLG HDR video to 10-bit H.265 (`hvc1`, Main 10) and 10-bit AV1
  (`av01`, Main) in MP4 with Opus audio; AVFoundation, which Photos uses, says
  every track is playable, reads the rotation flag, 10 bits, and the HLG
  transfer. No `-strict` is needed for Opus in MP4 with ffmpeg 9.
- The size limit as the user wants it (the long edge, whatever the orientation
  or aspect ratio) is one `scale` filter expression, verified on a rotated 4K
  video (2560×1440 stored, shown portrait) and at 720p.
- The user's HandBrake settings map onto ffmpeg options one to one (4.2),
  including SVT-AV1's `tune=0` (VQ), `enable-variance-boost=1` and
  `film-grain=8`, read from HandBrake's own encoder sources.
- Dolby Vision survives too, as in HandBrake: ffmpeg's x265 wrapper carries the
  per-frame RPU (`-dolbyvision 1`, with the VBV settings HandBrake adds for it,
  and `-strict unofficial` for the MP4 box), also when the video is scaled; the
  copy has the same `dvvC` box AVFoundation reads in the original. SVT-AV1
  writes it as Dolby Vision profile 10, which Apple may or may not use (spike
  V3).
- ffmpeg's `-map_metadata` is not enough: AVFoundation reads the keys ffmpeg
  writes as unnamed iTunes-style entries (`itsk/…`), and the video track's lens
  keys are dropped. The draft's `mp4meta.c`, compiled as a 35 KB helper
  (`vidmeta`), restores every key with its original type (date and time zone,
  location, make, model, software, lens model, focal length, f-number, Apple
  maker notes), as AVFoundation reads them in the original. exiftool, the
  user's HandBrake-era tool, was tried too and carries most but not all of
  them, as text (4.5); the helper was chosen (decision 9).
- Speed on this 14-core M4 Pro, 4K 30 fps → 2560 px: x265 *medium* about 1.1×
  real time, SVT-AV1 preset 5 about 0.6× real time.

What is not verified yet is in 5.2: whether a Run Shell Script may run for an
hour, what Photos' Share menu hands over for videos, and the end-to-end run
against the real library.

## 2. What is reused from Compress Photos (macOS), and what is new

| Part                                                   | Compress Photos (macOS)                                                               | Compress Videos (macOS)                                                                                                                                                                        |
| ------------------------------------------------------ | ------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Entry points                                           | Photos' Share menu / right-click / menu bar (selection route); Shortcuts app (picker) | the same                                                                                                                                                                                       |
| Probe, export and import AppleScripts                  | `scripts/mac/*.applescript`                                                           | the same scripts, shared (4.9); the import gets an albums-by-name pass for the picker route                                                                                                    |
| Originals collected for deletion                       | album *Compressed to JXL*, by photo id, selection route only                          | album *Videos already compressed*, same mechanism                                                                                                                                              |
| Filter                                                 | still photos only (Get Details of Images: Media Type, Photo Type)                     | videos only: Media Type is Video (picker and share input); in the exported files, a `.mov`/`.mp4` without a same-named image (a pair is a Live Photo: skipped)                                 |
| Questions                                              | quality (10 presets), cores                                                           | codec, preset, tune (H.265), RF, largest size, audio bitrate                                                                                                                                   |
| Encoder                                                | `jxlbatch-macos` (static, ours), job file in, `jxl_done.txt` out                      | `ffmpeg`/`ffprobe` (a static build of ours; Homebrew's accepted too), one command per video from the zsh script; `vidmeta-macos` (static, ours, 35 KB) copies the metadata; `vid_done.txt` out |
| Results back into Photos (picker route)                | Get File from Shortcuts' iCloud Drive folder → Save to Photo Album                    | AppleScript import from `~/Pictures` (no iCloud Drive: the files are large)                                                                                                                    |
| Progress window, log, Quick Look, finish, notification | `run.zsh`, `finish.zsh`                                                               | the same, shared; per-video progress lines from ffmpeg's `-progress` output                                                                                                                    |
| Second shortcut for Finder                             | *Compress Photo Files (macOS)*                                                        | none for now (not asked for; easy later, the script already works on files)                                                                                                                    |

## 3. User-facing design

### 3.1. Name and entry points

**Compress Videos (macOS)**, one shortcut, synced to every device but runnable
on the Mac only (Run Shell Script), as the photo ones. Album for the originals:
**Videos already compressed** (the user's name).

Entry points, in the order the shortcut checks them:

1. **Photos in front with a selection** (Share ▸ *Compress Videos (macOS)*,
   right-click ▸ Shortcuts, or the menu bar while Photos is in front): the
   selection route (3.3). Checked first, before the shortcut's input, because
   only the selection route has the originals and their ids; what the Share
   menu itself passes for videos, if anything, is unknown (spike V2) and would
   lack both.
2. **Shortcut Input with videos** (another app's share menu, a Quick Action
   later): the picker route's conversion without the picker.
3. **Otherwise** (Shortcuts app, menu bar, keyboard shortcut): a video picker
   (Select Photos, *Videos* only, multiple), then the picker route.

### 3.2. The questions

Six lists, in this order (decision 8). Shortcuts can't preselect, so one choice
per list is marked *(default)* in its title (decision 1). Lists with
explanations are contact-card lists (title plus grey description, as the
quality list); the two-item lists are plain menus.

Before them, when a previous run left its settings behind (4.6), one menu:
*Same as last time: H.265, medium, tune none, RF 24, 2K, Opus 160 kbps* (the
values spelled out in the title) or *Choose…*. The first skips the six lists;
the second shows them. On the first run there is no such menu.

1. **Video codec** (menu)
   - *H.265 (x265): plays on every Apple device since 2017*
   - *AV1 (SVT-AV1): smaller files; plays on M3 Macs and iPhone 15 Pro or
     later* (hardware decoding only; see 3.4)
2. **Preset** (cards; the list depends on the codec)
   - H.265: *fast* (quickest, biggest file), *medium* (HandBrake's default),
     *slow* (smallest file, about 2× medium's time)
   - AV1: *5* (SVT-AV1's and HandBrake's default), *4*, *3*, *2* (each step
     slower; 2 is several times slower than 5)
3. **Tune** (menu; H.265 only, AV1 has *vq* baked in)
   - *none*
   - *grain*: keeps film grain and fine noise instead of smoothing it; bigger
     files
4. **Quality (RF)** (plain list, one number per row): 19, 20, 21, 22, 24, 26,
   28, 30, 32, 34, 36, 38, 40. Lower is better and bigger. The same list for
   both codecs, as asked; the numbers don't mean the same thing in x265 and
   SVT-AV1 (the description row says so).
5. **Largest size** (cards): the limit for the long edge, so a vertical video
   gets the same limit on its height:
   - *4K*: 3840 px (3840×2160, or 2160×3840 vertical)
   - *2K*: 2560 px (2560×1440, or 1440×2560 vertical)
   - *1080p*: 1920 px
   - *720p*: 1280 px A video is never enlarged, and a 4:3 or square video keeps
     its aspect ratio with its long edge at the limit.
6. **Audio (Opus)** (cards): 64 kbps *Very good*, 96 *Near transparent*, 128
   *Often transparent*, 160 *Essentially transparent*, 192 *Really
   transparent*, 256 *Placebo*.

Baked in, never shown: H.265 Main 10 profile, AV1 Main profile, level auto,
10-bit output for both (an 8-bit source becomes 10-bit, as HandBrake's 10-bit
encoders do), frame rate same as source and variable, color range and color
tags same as source, AV1 `tune=0` (VQ), `enable-variance-boost=1`,
`film-grain=8`, Opus always.

No *Cores to use* question: x265 and SVT-AV1 use every core on their own, and
one video is converted at a time. ffmpeg runs under `nice -n 10` so the Mac
stays usable during a long batch (a `NICE=10` line at the top of the script
changes it).

### 3.3. The two routes

**Selection route** (from Photos): notification "Converting N video(s)… the
Terminal window follows the progress", then Photos exports the originals
(`export … with using originals`, which for a video is the recorded file; an
edited video's edits are not applied, as for photos), the script converts the
videos one by one, Photos imports each copy into its original's albums, and the
originals of all converted videos (anything that would lose something is
skipped before encoding, 3.4) are collected in *Videos already compressed*.
Nothing is deleted by the shortcut (same reasons as for photos: no Delete
Photos from the share extension, and its prompt fails in the app). Notification
"Saved N video(s) to Photos. M original(s) are in the album *Videos already
compressed* for you to delete." Still photos, Live Photos and the videos of
3.4's first list are skipped and counted ("Skipped 3 photo(s), 1 Live Photo(s),
1 slo-mo video(s)"), in the log and in a notification.

**Picker route** (from the Shortcuts app, or with input): the picker shows
videos only; the shortcut collects each video's name and album names (Get
Details of Images ▸ Album), passes the videos to the script as files, and the
copies are imported into those albums by name through AppleScript. The
originals are left alone (no ids; a lookup by file name could pick the wrong
video, the rule from 0.4.0). Notification "Saved N video(s) to Photos."

Both: the log opens in Quick Look when it has a `!` note, an `ERROR` or a
failed video; a Terminal window follows the conversion (`WATCH=0` turns it
off); the last run's log stays in `~/Library/Caches/compress-videos-macos`.

The copy is `Name.mp4` (the original's name with the extension replaced;
`IMG_1234.MOV` → `IMG_1234.mp4`), imported with that name. Photos may list the
pairs under Duplicates.

### 3.4. What is and isn't kept

Kept:

- The movie-level Apple keys: creation date with its time zone, location (ISO
  6709 and its accuracy), make, model, software, and any other key the original
  has; the video track's keys: lens model, 35 mm focal length, f-number, Apple
  maker notes. Byte for byte, so every value keeps its type (4.5). The movie
  and track creation and modification times.
- The rotation, as a flag (the pixels stay as stored, like the iPhone's), frame
  rate and duration, variable frame rate.
- HDR: an HLG (or PQ) 10-bit video stays 10-bit with the same color primaries,
  transfer and matrix tags and the same range; Photos shows it as HDR.
- Dolby Vision: the per-frame Dolby layer (profile 8.4) of iPhone HDR videos is
  carried through x265 as HandBrake does (4.2), with the same `dvvC` signaling
  the original has, so Apple's players see Dolby Vision, not just HLG. Through
  SVT-AV1 it is written as Dolby Vision profile 10 (AV1); whether Apple uses
  that is spike V3.
- The albums (both routes), the file name.

Not converted at all (decision 7): a copy that would lose one of these is not
worth having next to an original that stays anyway, so the video is skipped
before encoding, counted in the notification with the photos and Live Photos
("Skipped 1 slo-mo video(s), 1 spatial video(s)") and named in the log. All
four are known from ffprobe and the tool checks, before any encoding:

- **Slo-mo**: Photos exports the original at its recorded frame rate (120 or
  240 fps); the slow-motion range is an edit, so a copy would play at normal
  speed throughout. Videos above 100 fps.
- **Spatial video** (two views, MV-HEVC): ffmpeg would keep the base view only.
- **Audio that can't be decoded** (no decodable track): the copy would be
  silent.
- **Dolby Vision on an ffmpeg without `-dolbyvision`** (before 7.1, 4.1): the
  layer would be dropped.

Not kept in the copies that are made (noted in the log once per batch):

- **Spatial audio**: the 4-channel APAC track of recent iPhones; the stereo AAC
  track is used.
- **Timed metadata tracks** (`mebx`: face regions, Live Photo links, Cinematic
  mode focus data), **Cinematic mode** depth: the copy is the recording with
  its focus as shot. Not detectable today (spike V5); if it becomes detectable,
  skipped like the four above.
- **Edits** on the selection route (the original is exported); on the picker
  route Shortcuts probably hands over the edited rendering (spike V2).

Playback: H.265 10-bit plays on every Apple device since 2017. Opus in MP4
plays on iOS 17 and macOS 14 or later (and in most other players). **AV1 plays
only with a hardware decoder: Macs with an M3 or later, iPhone 15 Pro or later,
iPad with M2/A17 Pro or later; on older devices Photos shows the video but
can't play it**, which matters for a shared iCloud library. The codec menu says
so.

### 3.5. Installation (what the README will say)

1. The three tools, once, in Terminal (the same shape as the photo encoder's
   line; decision 2 in section 7: nothing is assumed to be installed):
   ```
   mkdir -p ~/.local/bin && cd ~/.local/bin && for f in ffmpeg ffprobe vidmeta; do curl -L -o $f https://github.com/jsh9/photo-video-shortcuts/releases/latest/download/$f-macos && chmod +x $f; done && ./vidmeta --selftest
   ```
   `ffmpeg` and `ffprobe` are our static builds (FFmpeg with x265, SVT-AV1 and
   Opus only, about 25 MB together; 4.1), `vidmeta` the 35 KB metadata helper.
   A Homebrew ffmpeg 7.1 or later with those three encoders works too, and is
   used when ours isn't installed (the script says which one it found).
2. Shortcuts ▸ Settings ▸ Advanced ▸ Allow Running Scripts (already on for the
   photo shortcuts).
3. Download `compress-videos-mac-shortcuts-v<version>.zip`, double-click the
   `.shortcut`, Add Shortcut.
4. First run from the Shortcuts app with one short video (Photos access); first
   run from Photos (Shortcuts may control Photos: Always Allow). The Share menu
   needs the Shortcuts sharing extension, as for photos.

Requirements: Apple silicon, macOS 14 or later (Opus playback in Photos; the
binaries are arm64, as the photo encoder), free disk space for the originals
(the selection route copies them out of Photos) plus the copies.

## 4. Technical design

### 4.1. The tools: ffmpeg, ffprobe and `vidmeta`

- **ffmpeg** does the decoding, scaling, encoding and muxing, one command per
  video, written by the script (4.2); **ffprobe** reads each source and
  verifies each result. Found in `~/.local/bin` (ours) first, then `~/bin`,
  `/opt/homebrew/bin`, `/usr/local/bin` (a Homebrew ffmpeg works when it has
  the three encoders), or `FFMPEG=` at the top of the script (the tests use
  it); `ffprobe` is taken from the same folder. Checks before the batch, each
  an `ERROR:` line in the log that stops the run: ffmpeg found; version ≥ 7.1;
  `ffmpeg -encoders` lists `libx265`, `libsvtav1`, `libopus`. A `!` note when
  it is neither ours for this version nor one with a `dolbyvision` option (then
  Dolby Vision can't be carried, 3.4).
- **Our ffmpeg build** (`build-macos.sh`, phase 2): FFmpeg 9.0.x configured
  with `--disable-everything` plus what the shortcut uses (the `mov` demuxer,
  the `mp4` muxer, the `hevc`, `h264`, `aac`, `alac`, `pcm_*` and `opus`
  decoders, `libx265`, `libsvtav1` and `libopus`, the `scale` filter, swscale,
  swresample, no network, no devices), linked statically against x265 4.3
  (8-bit with the 10-bit library linked in, as the draft's `build-wasm.sh`
  already does for WASI, `--enable-gpl`), SVT-AV1 4.2 and libopus 1.6, arm64,
  `-mmacosx-version-min=14.0`, stripped, ad-hoc signed, published as
  `ffmpeg-macos` and `ffprobe-macos`. Configured with
  `--extra-version=compress-videos-<VERSION>`, so `ffmpeg -version` reports
  `9.0.2-compress-videos-0.1.0` and `release.py`'s version check passes (it
  runs `<encoder> --version`; ffmpeg accepts the double dash, spike V7). The
  draft's `build-wasm.sh` has the downloads and the x265 dual build to start
  from; the native build needs none of its patches. GPL: x265 makes the build
  GPL, as the repository is. CI builds it with the static libraries cached by
  script hash, as the photo encoder's are.
- **`vidmeta`**, our helper: `src/vidmeta.c` (the CLI) plus the draft's
  `src/mp4meta.c`/`.h` unchanged. Plain C, no libraries, built by the same
  script as a static arm64 executable, published as `vidmeta-macos`, found like
  the others (`VIDMETA=` override). Commands:
  - `vidmeta copy ORIGINAL CONVERTED`: `mp4meta_copy`; prints `copied N boxes`;
    exit 1 with a message on failure (no `moov`, `moov` not last, damaged).
  - `vidmeta --version`: `vidmeta <VERSION>`, checked by the script (a `!` note
    when it isn't the shortcut's version) and by `release.py`.
  - `vidmeta --selftest`: writes a minimal MP4 with a `meta` box (the draft's
    `mp4meta_append` exists for this), copies it onto a second one, reads it
    back; "Self-test passed". It is the install check.
- Why not one program with FFmpeg's libraries (the draft's `vidbatch`): the
  user asked for ffmpeg itself, the command line is what HandBrake's activity
  log shows and what a reader can run by hand, and adding SVT-AV1 and Dolby
  Vision to the draft's `transcode.c` is real work that the ffmpeg command
  gives for free.
- The build trap on this Mac: `cc` and `python3` are conda's in the user's zsh;
  build scripts run under `#!/bin/sh` or call `/usr/bin/cc`.

### 4.2. HandBrake settings as ffmpeg options

From HandBrake's `libhb/encx265.c` and `libhb/encsvtav1.c` (master,
2026-10-05): what HandBrake sets beyond the user's choices, and how ffmpeg's
wrappers set the same things from the input stream. Verified items are marked ✓
(5.1).

| HandBrake                                                 | H.265 (x265)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | AV1 (SVT-AV1)                                                                                                                                                             |
| --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| encoder                                                   | `-c:v libx265`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | `-c:v libsvtav1`                                                                                                                                                          |
| preset                                                    | `-preset fast\|medium\|slow` ✓                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | `-preset 5\|4\|3\|2` ✓ (HandBrake's default `enc_mode` is 5)                                                                                                              |
| tune                                                      | `-tune grain` or nothing ✓                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | `tune=0` in `-svtav1-params` (HandBrake maps every tune name but psnr/ssim/iq/ms-ssim/vmaf to 0 = VQ) ✓                                                                   |
| RF                                                        | `-crf RF` ✓ (x265's CRF, as HandBrake)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | `-crf RF` ✓ (HandBrake: `qp = floor(RF)`, fractional part as `extended_crf_qindex_offset`; integer RF, so identical)                                                      |
| 10-bit                                                    | `-profile:v main10 -pix_fmt yuv420p10le` ✓ (profile applied last, as HandBrake)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | `-pix_fmt yuv420p10le` ✓; profile Main is SVT's default (10-bit is Main) ✓                                                                                                |
| level auto                                                | nothing (HandBrake sets `level-idc` only for a chosen level)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | nothing ✓ ("level (auto)" in SVT's log)                                                                                                                                   |
| frame rate same as source, variable                       | `-fps_mode passthrough` ✓; x265's `fps` comes from the stream's average rate (HandBrake: `fpsNum/fpsDenom` from the source)                                                                                                                                                                                                                                                                                                                                                                                                                                        | the same                                                                                                                                                                  |
| color range and tags same as source                       | ffmpeg's wrapper sets `colorprim`, `transfer`, `colormatrix`, `range` from the stream (HandBrake does the same explicitly) ✓ (bt709 and bt2020nc/arib-std-b67, tv range, in the output)                                                                                                                                                                                                                                                                                                                                                                            | the wrapper sets `color_primaries`, `transfer_characteristics`, `matrix_coefficients`, `color_range` ✓                                                                    |
| keyframe interval                                         | HandBrake: `keyint = 10 × fps`, `min-keyint = fps` → `-x265-params keyint=K:min-keyint=M` from ffprobe's frame rate ✓                                                                                                                                                                                                                                                                                                                                                                                                                                              | HandBrake sets none: SVT's default (`keyint -2`, about 5 s; 161 frames at 30 fps ✓). So no `-g`                                                                           |
| HDR10 static metadata (PQ only)                           | the wrapper passes mastering display and content light from the stream's side data, as HandBrake (`hdr10-opt`, `master-display`, `max-cll`). iPhone videos are HLG, so this never applies                                                                                                                                                                                                                                                                                                                                                                          | the same (`mastering-display`, `content-light`)                                                                                                                           |
| SAR                                                       | from the stream (HandBrake: `sar`)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 | n/a                                                                                                                                                                       |
| additional options `enable-variance-boost=1,film-grain=8` | n/a                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                | `-svtav1-params tune=0:enable-variance-boost=1:film-grain=8` ✓ (SVT's log: "Variance Boost strength 2", "film grain level 8", denoising 0, the default since SVT-AV1 2.0) |
| container                                                 | `-tag:v hvc1` ✓ (Apple needs `hvc1`, not `hev1`), `.mp4`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           | `av01` ✓, `.mp4`                                                                                                                                                          |
| audio                                                     | `-c:a libopus -b:a ${KBPS}k` ✓ (VBR, 48 kHz; `-ac 2` when the chosen track has more than 2 channels)                                                                                                                                                                                                                                                                                                                                                                                                                                                               | the same                                                                                                                                                                  |
| rotation                                                  | `-noautorotate` before `-i`: the display matrix is written to the output as it was ✓                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | the same ✓                                                                                                                                                                |
| streams                                                   | `-map 0:v:0 -map 0:a:N` (4.4); no data tracks; `-map_metadata -1` (ffmpeg's own copy of the keys is wrong, 4.5; exiftool writes them afterwards)                                                                                                                                                                                                                                                                                                                                                                                                                   | the same                                                                                                                                                                  |
| Dolby Vision (HandBrake: passthrough on by default)       | `-dolbyvision 1` (the wrapper sets x265's `dolby-vision-profile` 84 from the stream and attaches each frame's RPU) plus, as HandBrake does, VBV at the Dolby level's main-tier rate: `vbv-bufsize=R:vbv-maxrate=R` with R from HandBrake's `hb_dovi_levels` table by width × height × fps (20000 up to 1440p30 or 1080p60, 25000 for 4K30, 40000 for 4K60, 60000 for 4K120; `auto` alone writes nothing), and `-strict unofficial` so the MP4 muxer writes the `dvvC` box ✓ (an RPU in every frame, also when scaled; AVFoundation sees `dvvC` as in the original) | `-dolbyvision 1 -strict unofficial`: Dolby Vision profile 10 (AV1) with `dvvC` ✓ written and playable; whether Apple honors profile 10 is spike V3; no VBV needed         |

The complete H.265 command, as the log will show it:

```
nice -n 10 ffmpeg -v warning -nostats -progress pipe:1 -y -noautorotate -i IN.MOV \
  -map 0:v:0 -map 0:a:1 -map_metadata -1 -fps_mode passthrough \
  -vf "scale=w='min(iw,2560)':h='min(ih,2560)':force_original_aspect_ratio=decrease:force_divisible_by=2" \
  -c:v libx265 -preset medium -crf 24 -profile:v main10 -pix_fmt yuv420p10le \
  -x265-params keyint=300:min-keyint=30:vbv-bufsize=25000:vbv-maxrate=25000 \
  -dolbyvision 1 -strict unofficial -tag:v hvc1 \
  -c:a libopus -b:a 160k OUT.mp4
```

and AV1:

```
  -c:v libsvtav1 -preset 5 -crf 30 -pix_fmt yuv420p10le \
  -svtav1-params tune=0:enable-variance-boost=1:film-grain=8
```

The Dolby Vision options (`vbv-*`, `-dolbyvision 1`, `-strict unofficial`; for
AV1 only the last two) are added when ffprobe finds a Dolby Vision
configuration record in the source and `DOLBY` is 1 (4.6).

The option lists (presets, tunes, RF values, sizes, bitrates, their titles and
descriptions) live in one place in the shortcut generator, and the mapping to
ffmpeg options in the zsh script; a test asserts the command line for each
choice (4.11).

### 4.3. The size limit

One filter, whatever the orientation or aspect ratio:

```
scale=w='min(iw,L)':h='min(ih,L)':force_original_aspect_ratio=decrease:force_divisible_by=2
```

with `L` = 3840, 2560, 1920 or 1280: the frame is fitted inside an L×L box (so
the long edge is at most L), never enlarged (`min(iw, L)`), to even sizes for
4:2:0. With `-noautorotate` the frame is the stored one, so a vertical iPhone
video (stored 3840×2160 with a 90° flag) becomes 2560×1440 stored, shown as
1440×2560 ✓. A 4:3 4032×3024 video at 2K becomes 2560×1920. When the video is
already within the limit the filter is a no-op (the same encode either way, so
the filter is always passed).

### 4.4. Audio

`ffprobe -select_streams a -show_entries stream=index,codec_name,channels`
(JSON) decides the track: the first audio stream with at most 2 channels whose
codec ffmpeg can decode (iPhones: the stereo AAC, which comes before the
4-channel APAC spatial track ✓); else the first decodable stream with `-ac 2`;
else the video is skipped (3.4). Opus: `-c:a libopus -b:a ${KBPS}k`, 48 kHz by
ffmpeg's resampler.

### 4.5. Metadata: why ffmpeg can't do it, and what exiftool does

What an iPhone video carries, as AVFoundation reads it (5.1):

- movie keys (`mdta`): `com.apple.quicktime.creationdate` (UTF-8, with the time
  zone, what Photos shows as the capture date), `location.ISO6709`,
  `location.accuracy.horizontal`, `make`, `model`, `software`,
  `full-frame-rate-playback-intent` (int64), `metadata.1` (int8);
- video track keys: `camera.lens_model`, `camera.focal_length.35mm_equivalent`,
  `camera.lens_irisfnumber` (each tagged `en-US`), `apple-maker-note.74` and
  `.97` (int32).

ffmpeg's `-map_metadata 0 -movflags use_metadata_tags` writes the movie keys by
name and value, but AVFoundation reads them back as `itsk/%00%00%00%0A`-style
entries (unnamed, all UTF-8): Photos would not see the date, the location or
the camera. The track keys don't survive at all (ffmpeg's demuxer doesn't read
track-level `mdta` keys). So the output is muxed with `-map_metadata -1`, and
`vidmeta copy ORIGINAL COPY` rewrites the copy's `moov` (its last box, which is
where ffmpeg puts it): the original's movie-level `meta` and `udta` boxes
replace the copy's, the original's first video track's `meta`/`udta` boxes go
into the copy's video track, and the `mvhd`/`tkhd`/`mdhd` times are set from
the original's `mvhd`. Verified (5.1, row G2): AVFoundation then lists exactly
the original's keys, with the original's types, in both the x265 and the
SVT-AV1 output, and exiftool shows `CreationDate`, `GPSCoordinates`, `Make`,
`Model`, `Software`, `LensModel`, `FocalLengthIn35mmFormat`,
`CameraLensIrisfnumber` and the create/modify dates. The copy's `encoder` tag
(`Lavf…`) goes with the replaced `udta`. Not carried: the old-style `©xyz`-type
QuickTime atoms of some other cameras' MOV files (copied, but Apple ignores
them in an MP4; the draft's README said the same). The rewrite touches only the
`moov` box, so it costs nothing measurable even on a 2 GB file.

exiftool was the first candidate (the user's HandBrake workflow runs
`exiftool -tagsFromFile ORIGINAL -All:All COPY`) and was measured (row G): it
writes the movie keys and the lens model and focal length so that AVFoundation
reads them under their Apple names, but it has no writable tag for
`camera.lens_irisfnumber`, `apple-maker-note.74`/`.97` and `metadata.1`, every
value becomes text, `-All:All` adds `major_brand`-style junk keys and doubles
the track keys, and it would be a Perl program to install. The helper carries
everything and is 35 KB. exiftool stays a test dependency (a reader, as in the
photo tests).

A failed copy (damaged file, `moov` not last) fails the video: the copy is
removed, the original is not collected, and the log says why. A video that lost
its metadata is not what the user asked for.

### 4.6. The script

Assembled by `build_mac_shortcuts.py` from `scripts/mac/*.zsh` with
`@PLACEHOLDERS@`, as the photo one; the Shortcuts variables become `CODEC='…'`,
`PRESET='…'`, `TUNE='…'`, `RF='…'`, `LIMIT='…'`, `AUDIO='…'` lines (one Match
Text or Set Variable output each), plus the lines block (`IDS` on the selection
route, `NAMES` and `ALBUMS` on the picker route) and `Skipped Echo`.

Shape (`common.zsh` → `selection.zsh` or `picker.zsh` → `encode.zsh` at `@RUN@`
→ the result lines):

1. **Setup** (shared with the photos' `common.zsh`):
   `WORK=~/Pictures/.compress-videos-macos` (Photos' sandbox reaches
   `~/Pictures`; both routes, since both import through AppleScript),
   `LOGDIR=~/Library/Caches/compress-videos-macos`, one log per route, the
   progress window (`run.zsh`'s Terminal part), the tool lookups and checks
   (4.1), the free-space check (`df` of `~/Pictures` against 1.2 × the inputs'
   total, an `ERROR` when short).
2. **Staging**: selection route: `in/*` from Photos' export; a `.mov/.mp4/.m4v`
   with a same-stem image file is a Live Photo (skipped, counted), an image
   alone is a photo (skipped, counted), a video alone is a job; `IDS` maps file
   names to ids as `selection.zsh` does, duplicates get no id. Picker route:
   `"$@"` with `NAMES` for the job names and `ALBUMS` (`index|album` lines) for
   the import. Job lines `N|Name` in `vid_job.txt`, inputs as `vid_in_N.orig`
   symlinks (ffmpeg reads the symlink), as the draft.
3. **The settings file**: before the lists, a small Run Shell Script prints
   `$LOGDIR/last-settings.txt` (one `KEY=value` line each) if it exists; the
   shortcut puts the values into the *Same as last time* title and, when that
   is chosen, into the variables the lists would have set. After the batch the
   script writes the file with the settings used.
4. **Per video** (`encode.zsh`, the new part), in job order:
   1. `ffprobe` (JSON): video stream width, height, `avg_frame_rate`,
      `nb_frames` (MOV has it; else duration × rate), `pix_fmt`,
      `color_transfer`, the Dolby Vision configuration record if any (4.2);
      audio streams (4.4); the number of video streams and `view_ids`/stereo
      side data (spatial, spike V5). A file ffprobe can't read fails with
      `unsupported format`.
   2. The log's header line:
      `[2/5] IMG_1234.MOV  4K 30 fps HLG Dolby Vision 10-bit, 171 MB → 2K H.265 medium RF 24, Opus 160 kbps, Dolby Vision kept`.
   3. The ffmpeg command (4.2), `nice`d, stderr to the log, stdout
      (`-progress pipe:1`) into a `while read` loop that prints, at most every
      5 s, one line `  34%  frame 2345/6900  28 fps  0.9×  ETA 2:40` to the log
      (the Terminal window shows them as they come; Quick Look shows them too,
      which is fine). `frame=`/`fps=`/`speed=`/`out_time_us=` are the keys ✓.
   4. **Verification**: ffprobe the output: a video stream with the expected
      codec and `pix_fmt`, a duration within max(0.5 s, 1 %) of the original's
      (else `! only 97% of the video was written`, failed).
   5. `vidmeta copy` (4.5); a nonzero exit fails the video.
   6. The result moves to `out/Name.mp4` (never replacing: `Name 2.mp4`, the
      photos' `unique`), the summary line
      `  171 MB → 23 MB (13%), 2:05 at 1.1× real time`, and the `vid_done.txt`
      line `vid_out_N.mp4|N|delete|Name.mp4` (the photos' four-field shape; the
      flag is always `delete` here, since anything that would lose something is
      skipped before encoding, 3.4; the shared import script reads it as
      before).
   7. A failed video: the output is removed, the line is not written, the log
      says why, the batch continues
      (`Done: 4 of 5 converted in 12:30. 1 failed; see the messages above.`).
5. **Result lines** for the import: `path|id|flag|name` on the selection route
   (ids from `IDS`), `path||flag|name|album|album…` on the picker route (no id;
   the album names from `ALBUMS`). Nothing when nothing converted.
6. The **finish** script (shared `finish.zsh`) appends the outcome, ends the
   Terminal window by pid, removes `in/` and the `vid_*` files, keeps `out/`
   (Photos may reference the imported files; the next run empties it).

The script never exits nonzero for a conversion problem (the shortcut shows the
log instead); `set -u`, no `lines` variable in `tell` blocks, and the other
lessons from the photos' scripts apply.

### 4.7. Getting files to and from Photos

- **Selection route**: as the photos (probe → `export.applescript` into
  `$WORK/in` → script → `import.applescript` with the result lines → albums by
  id → originals collected in *Videos already compressed*). `export` with
  `using originals` on a video gives the recorded file (Photos' dictionary:
  "export media items … the original files if true"); iCloud originals are
  downloaded first, inside the script's 3600 s timeout. Exporting a selection
  of large videos copies gigabytes into `~/Pictures`: the README says so, the
  script checks the space, and the folder is emptied at the end.
- **Picker route**: unlike the photos, no Get File through Shortcuts' iCloud
  Drive folder. A 500 MB file there would start uploading to iCloud before the
  shortcut removes it. Instead the copies are imported by the shared
  `import.applescript` from `$WORK/out`, and added to albums **by name** (the
  album names Shortcuts read from each video). The import script gets one
  addition: for a line without an id but with album names, it finds each album
  by name (one recursive pass over `albums` and `folders`, names collected once
  per run, the same cost as the id pass: a few seconds in a 689-album library)
  and adds the item; a name with several albums takes the first (the same
  ambiguity Save to Photo Album has) and the log says so; an unknown name is a
  `!` line. This needs the Automation permission on the picker route too (the
  same prompt, already granted after the first selection run).
- Shortcuts passes the picker's videos to the script as files (copies in a
  temporary folder, named by the shortcut's Set Name, as for photos: spike V2
  confirms the paths and names for videos).

### 4.8. Progress and the log

As the photos: `<route>.log`, `<route>.command` (`tail -f` in a Terminal
window), `<route>.pid`, `WATCH=0`, Quick Look when the log matches `WARNINGS`
(`!`, `ERROR`, `N failed`), the outcome appended by the finish script, "Done.
You can close this window." The per-video progress lines (4.6) make the window
useful for a batch that takes an hour. The notification before the batch says
the window follows the progress; the one after gives the count.

### 4.9. Code layout and shared code

The photos' design (`compress-photos-mac-design.md`, 4.7) already said the
plist builder and the AppleScripts would need "a third place" once a second
tool used them. Proposed:

```
lib/                                   shared by the shortcuts (new)
  wfkit.py       the generic Shortcuts plist builder: Sample, fetch_sample,
                 guessed_workflow, Ref, text, Builder, workflow, write
                 (moved from shortcuts/compress-photos/scripts/wf.py)
  mac/
    probe.applescript, export.applescript, import.applescript
                 (moved; @NAME@ and @ORIGINALS_ALBUM@ placeholders; the
                 import gets the albums-by-name pass, 4.7)
    progress.zsh (the Terminal-window part of run.zsh), finish.zsh (moved)
shortcuts/compress-photos/scripts/wf.py
                 keeps VERSION, EFFORT, HELP_URL, QUALITY_PRESETS,
                 choose_quality, keep_still_photos, vcard_escape, and
                 re-exports lib/wfkit's names: build_shortcuts.py,
                 build_mac_shortcuts.py and the tests don't change
shortcuts/compress-videos/
  VERSION        0.1.0
  release.json   {"encoders": ["ffmpeg-macos", "ffprobe-macos", "vidmeta-macos"],
                  "shortcuts": {"mac": ["Compress Videos (macOS).shortcut"]}}
  README.md      the Mac shortcut (iPhone: "coming later"); README-mac.md is
                 not needed until there is an iPhone README to split from
  DEVELOPING.md  how it works, building, releasing (the photos' shape)
  src/vidmeta.c, src/mp4meta.c, src/mp4meta.h
  scripts/build-macos.sh      dist/ffmpeg-macos, dist/ffprobe-macos (static
                              FFmpeg + x265 + SVT-AV1 + Opus, 4.1) and
                              dist/vidmeta-macos; build/vidmeta for the tests
  scripts/vf.py               this tool's shortcut parts: the option lists
                              (CODECS, PRESETS, TUNES, RF_VALUES, SIZES,
                              AUDIO_KBPS with titles and descriptions),
                              choose_* builders, keep_videos (the Media Type
                              filter, from keep_still_photos's pattern)
  scripts/build_mac_shortcuts.py   "Compress Videos (macOS)", the two routes
  scripts/mac/common.zsh, selection.zsh, picker.zsh, encode.zsh
tests/compress-videos/        (4.11)
tests/shortcut_helpers.py     the generic test helpers (load_generator, walk,
                              inside_if_on, shell_scripts, ident, params,
                              references, render, need, run, compile_swift)
                              moved from photo_helpers.py, which re-exports
```

The move is a behavior-preserving PR of its own (phase 1), and the user wants
it clean and surgical in `shortcuts/compress-photos`: code moves verbatim (no
renames, no reformatting of what moves), the photos' `wf.py` shrinks to its own
parts plus one re-export line, the generators and the tests don't change
otherwise, the photos' `DEVELOPING.md` layout table gets one row for `lib/`,
and a one-off test in the PR compares the generated iPhone and Mac plists
before and after the move byte for byte. Anything the videos tool needs beyond
what exists (the albums-by-name pass in the import script, placeholders for the
album name) is added without changing the photos' output.

### 4.10. Versioning, manifest, release and CI

- `shortcuts/compress-videos/VERSION` 0.1.0, `release.json` as above. The
  manifest shape already allows a Mac-only tool and extension-less native
  encoders (`release.py`: `shortcuts` may be `{"mac": […]}`);
  `tests/scripts/test_release.py` already models a second tool named
  compress-videos. One new test case: a tool with `mac` only. The ZIP is
  `compress-videos-mac-shortcuts-v0.1.0.zip`; the tag `compress-videos-v0.1.0`;
  the title "Compress Videos 0.1.0". The release carries the ZIP and the three
  binaries.
- `release.py` runs `build-macos.sh` and `build_mac_shortcuts.py --guess` for
  the tool (it already looks for both), then `--version` on each binary:
  `vidmeta` prints the VERSION, ffmpeg and ffprobe print it in their
  `--extra-version` suffix (4.1).
- `CHANGELOG.md`: `## [Compress Videos 0.1.0] - <date>` (the pre-commit check
  requires it as soon as `VERSION` exists).
- `tox.ini` build env: the two compress-videos build commands (the
  `build-macos.sh` under the same arm64 guard). CI: `brew install ffmpeg` for
  the tests' fast path (the static build is for the release dry run, its
  libraries cached under `shortcuts/*/build/macos` by the existing cache key,
  which already hashes every tool's `build-macos.sh`); exiftool is already
  installed there.
- README (root): the table row becomes Mac: Yes, iPhone: Coming soon; section
  1.2 gets the two install lines; section 3's layout row mentions `lib/` if
  phase 1 lands.

### 4.11. Tests

`tests/compress-videos/`, the photos' shape:

- `test_mac_shortcuts.py`: the generated shortcut without importing it:
  balanced blocks, outputs used after they exist, no a-Shell, Run Shell Script
  with zsh; the probe → input → picker order; the picker is *Videos* only; the
  six lists with exactly the option titles and descriptions of `vf.py` and each
  choice reaching the script as its variable; the surfaces (Share menu,
  `ActionExtension`; input class `WFAVAssetContentItem`, the draft's "Receive
  Media" choice); no Get File, no Delete Photos, no Save to Photo Album (the
  import script does it); the three AppleScripts are plain text with values
  through their input, and compile (`osacompile`); the album name; the version
  in the note.
- `test_mac_script.py`: the zsh script run for real.
  - With a **fake ffmpeg, ffprobe and vidmeta** (shell scripts that answer
    `-version`, `-encoders` and `--version`, record their arguments, and write
    a copy of a fixture as the output): the exact ffmpeg command line for every
    codec × preset × tune × RF × size × bitrate combination the lists allow
    (the HandBrake parity table as test data), the Dolby Vision options only
    for a source with a Dolby Vision record, the `vidmeta copy` call,
    `keyint`/`min-keyint` from the frame rate, the audio track choice (stereo
    AAC before APAC; `-ac 2`; `-an`), the `vid_job.txt` and `vid_done.txt`
    lines, the result lines of both routes, the skip rules on exported files (a
    Live Photo pair, a photo, a video) and on probed ones (slo-mo, spatial, no
    decodable audio, Dolby Vision without the option), the duration
    verification failing a short output, the missing or old tools, the
    free-space check, the progress window and the finish script (the photos'
    tests, adapted).
  - With the **real ffmpeg** (skipped locally when absent, required in CI):
    tiny fixtures through the whole script; ffprobe checks codec, tag, profile,
    `pix_fmt`, size against the limit, rotation flag, color tags, Opus; the
    log's lines.
- `test_vidmeta.py`: the helper on fixtures: copies the boxes, sets the times,
  `--version`, `--selftest`, refuses a `moov`-first file, a damaged file, and a
  copy onto a file with no `moov`.
- `test_conversion.py`: end to end with the real ffmpeg (Homebrew's or ours,
  whichever the `FFMPEG` variable names; CI runs both): every
  `com.apple.quicktime` key of the fixture, movie and track, is in the copy
  with the same value and type as AVFoundation reads them (`avmeta.swift`,
  compiled once like `imageio_props.swift`); the create/modify dates; the
  rotation and HLG tags; `containsHDRVideo` and the `dvvC` atom for a Dolby
  Vision fixture (the probes of 5.1 as a helper); and a PSNR sanity check (the
  draft's: Y PSNR of the first frames against the original scaled the same way,
  ≥ 30 dB).
- Fixtures: `make_video.swift` writes them at test time with AVAssetWriter (as
  `make_photo.swift` does for photos): 320×180, one or two seconds, H.265 8-bit
  and 10-bit HLG, stereo AAC, a 90° transform, the movie and track keys with
  the identifiers and types listed in 4.5 (a test compares the fixture's key
  shapes with the ones recorded from an iPhone 17 Pro in 5.1), a 120 fps
  variant for the slo-mo rule, a two-audio-track variant for the track choice.
  Nothing is committed: personal videos carry locations, and generated ones are
  small and quick.
- `test_samples.py`: the user's own videos in `tests/samples/compress-videos/`
  (not committed), through the script with both codecs at a fast preset,
  checked as in `test_conversion.py`.
- `tests/README.md` gets the table rows; `tests/requirements.txt` is unchanged
  (numpy for the PSNR reader is already there).

## 5. Spikes

### 5.1. Done on this Mac (2026-10-05)

Run with Homebrew ffmpeg 9.0.2 and exiftool 13.35 on the draft's test videos in
`~/Documents/misc/vid-comp/testdata` (`2026-06-09-20.44.20.mov`: iPhone 17 Pro
4K 30 fps SDR, stored with a −90° flag; `HDR-video.MOV`: HLG with Dolby Vision
8.4), two seconds each (`-t 2`) unless said otherwise. The commands are the
ones in 4.2 to 4.5; nothing else survives from the session that ran them, so
they are to be redone as `test_mac_script.py` and `test_conversion.py` cases.
How each thing was checked:

- container and tags: `ffprobe -show_entries stream=...:stream_side_data_list`
  and `exiftool -a -G1 -s`; the Dolby box by `grep -c -a dvvC FILE`;
- what Apple reads: the draft's `avmeta.swift` (every metadata item with its
  identifier and data type, per track; `mdta/com.apple.quicktime.…` is a key
  Photos understands, `itsk/…` is not), plus a 20-line Swift probe that loads
  each video track and prints `hasMediaCharacteristic(.containsHDRVideo)` and
  the keys of the format description's `SampleDescriptionExtensionAtoms`
  (`dvvC` present = Dolby Vision as Apple sees it); both become test helpers;
- the per-frame Dolby RPU:
  `ffmpeg -v trace -t 1 -i FILE -map 0:v:0 -c:v copy -bsf:v trace_headers -f null -`
  and a count of the `nal_unit_type: 62(UNSPEC62)` lines (the original and the
  copies give 32 per second; ffprobe's frame side data shows nothing for these
  files, so don't use that);
- `cc` and `python3` on this Mac are conda's (a shell function, and anaconda's
  interpreter); use `/usr/bin/cc` and `/usr/bin/python3`.

| #   | Question                                                                                                                                                                 | Result                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A   | x265 10-bit, `hvc1`, Opus, `-noautorotate`, long-edge scale to 2560                                                                                                      | 2560×1440 Main 10 `yuv420p10le`, bt709, tv range, rotation −90 kept, Opus `Opus` tag; AVFoundation: playable, rotation 90, 10 bits                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| B   | the HLG clip through x265 (`-dolbyvision auto`, the default)                                                                                                             | HLG kept (bt2020 / arib-std-b67 / bt2020nc, tv), AVFoundation flags it `containsHDRVideo` like the original; but no Dolby Vision in the output (`auto` doesn't enable it); the "Ambient viewing environment" side data is carried                                                                                                                                                                                                                                                                                                                                                                                                                       |
| C   | `-dolbyvision 1` with libx265, without VBV                                                                                                                               | "Could not open encoder": x265 requires VBV for the RPU's HRD, which is why HandBrake sets it (row P)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| D   | SVT-AV1 preset 5, CRF 30, `tune=0:enable-variance-boost=1:film-grain=8`                                                                                                  | `av01` Main 10-bit, HLG tags kept; SVT's log: "preset / tune: 5 / VQ", "Variance Boost strength 2", "film grain synth / denoising / level: 1 / 0 / 8", "main profile, tier (auto), level (auto)"; AVFoundation: playable (hardware AV1), `ITU_R_2100_HLG`, 10 bits                                                                                                                                                                                                                                                                                                                                                                                      |
| D2  | the rotated SDR clip through SVT-AV1 at 720p                                                                                                                             | 1280×720, rotation kept, playable                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| E   | what ffmpeg reads of the original's metadata                                                                                                                             | the movie keys by name; the video track's keys not at all                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| F   | `-map_metadata 0 -movflags use_metadata_tags`, read by AVFoundation                                                                                                      | 13 `itsk/%00%00%00%NN` entries, all UTF-8: the names are lost; exiftool still shows them by name, which is misleading                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| G   | `exiftool -tagsFromFile ORIG -All:All OUT` (the user's script's command, exiftool 13.35), then the targeted form of 4.5, onto A's and D's outputs                        | AVFoundation reads back, under their Apple names: `creationdate`, `location.ISO6709` (altitude `+15.552/`), `location.accuracy.horizontal`, `make`, `model`, `software`, `full-frame-rate-playback-intent` (as the text "1"); on the track `camera.lens_model` and `camera.focal_length.35mm_equivalent` (`-All` writes each twice, plain and `en-US`; the targeted form once). Not written, "not defined" for writing: `camera.lens_irisfnumber`, `apple-maker-note.74/.97`, `metadata.1`. `-All:All` also adds `major_brand`, `minor_version`, `compatible_brands` as Apple keys; the targeted form doesn't. Create/modify dates set. 0.2 s for 23 MB |
| G2  | the draft's `mp4meta.c` (as a 35 KB helper) onto the same outputs                                                                                                        | "copied 2 boxes" each; AVFoundation lists exactly the original's movie keys (`creationdate`, `location.ISO6709`, `location.accuracy.horizontal`, `make`, `model`, `software`, `full-frame-rate-playback-intent` int64, `metadata.1` int8) and track keys (`camera.lens_model`, `camera.focal_length.35mm_equivalent`, `camera.lens_irisfnumber`, each `en-US`, `apple-maker-note.74/.97` int32); the create/modify dates set from the original. Held in reserve (decision 9)                                                                                                                                                                            |
| H   | SVT-AV1 without `-g`                                                                                                                                                     | "gop size 161" at 30 fps (SVT's `keyint -2`, HandBrake's behavior); with `-g 300`, 300                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| I   | ffmpeg's `-progress pipe:1`                                                                                                                                              | `frame=`, `fps=`, `out_time_us=`, `speed=`, `progress=continue/end` lines, once a second                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| J   | speed, the whole 7.7 s SDR clip 4K → 2560, 14-core M4 Pro                                                                                                                | x265 medium RF 28: 7 s (5.2 MB from 22.8 MB); SVT-AV1 preset 5 CRF 30: 13 s (14.1 MB)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| K   | the audio tracks of an iPhone 17 Pro video                                                                                                                               | stream 1 AAC stereo, stream 2 `apple_apac` 4 channels; ffmpeg 9 has an `apac` decoder (Marian's A-pac, not Apple's), so the stereo track must be chosen explicitly                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| L   | Photos' scripting dictionary (`Photos.sdef` read directly; `sdef` needs Xcode)                                                                                           | `export … using originals` ("the original files if true") applies to media items, photo or video; `import`, `add` as used by the photos                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| M   | HandBrake's sources                                                                                                                                                      | x265: `keyframeMin = round(fps)`, `keyframeMax = 10 × keyframeMin`, color/range/sar set explicitly, profile applied last, level only when chosen; SVT-AV1 (`encsvtav1.c`, the library directly): `enc_mode` default 5, CRF as `qp` + `extended_crf_qindex_offset`, tune names other than psnr/ssim/iq/ms-ssim/vmaf → 0 (VQ), no keyint, options string parsed by `svt_av1_enc_parse_parameter`; Dolby Vision (both): `dolby-vision-profile` 84 for iPhone files, VBV = the Dolby level's main-tier rate from `dovi_common.c`'s `hb_dovi_levels` table (by width × height × fps), the Dolby level recomputed for the output size                         |
| N   | the `colr` atom in ffmpeg 9's MP4 output                                                                                                                                 | present without any flag: exiftool shows BT.709, and BT.2020 / BT.2100 HLG, on track 1 of the outputs; ffmpeg's `write_colr` flag now only forces one when the color is unspecified                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| O   | the draft's share-sheet input class for videos                                                                                                                           | `WFWorkflowInputContentItemClasses: ['WFAVAssetContentItem']` ("Receive Media"), with `ActionExtension`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| Q   | the size cost of the Dolby Vision options, whole HDR clip (9.9 s, 4K, video only, CRF 30 fast)                                                                           | no options 414,030 bytes; VBV alone 414,147 (nothing); VBV + `-dolbyvision 1` 545,631: about 13 KB/s, a fixed cost per frame (the RPU and HRD SEI), so about 1% of a real 4K encode at 10 Mbps and invisible on anything but a tiny static clip. A source without Dolby Vision gets none of these options, so nothing changes for it                                                                                                                                                                                                                                                                                                                    |
| P   | Dolby Vision passthrough as HandBrake does it: `-dolbyvision 1`, `vbv-bufsize`/`vbv-maxrate` set, `-strict unofficial`; x265 at 4K and scaled to 1080p; SVT-AV1 at 1080p | x265: encodes; the MP4 has the `dvvC` box and a "DOVI configuration record" (profile 8, compatibility id 4, RPU present, level 7 at 4K and 4 at 1080p, recomputed by ffmpeg); 32 RPU NAL units (type 62) in the first second, the same count as the original, scaled or not; AVFoundation: playable, HDR, sample-description atoms `dvvC,hvcC` as in the original (without passthrough: `hvcC` only). Without `-strict unofficial` the muxer logs "Not writing 'dvcC'/'dvvC' box" and the file is plain HLG. SVT-AV1: a profile 10 record and `dvvC` next to `av1C`, playable, HDR; the per-frame RPU wasn't checked (no OBU-level tool at hand)        |

### 5.2. Still to run (one throwaway shortcut, about an hour)

| #   | Question                                                                                                                                                                                | Pass                                                                                                                                                      | If it fails                                                                                                                                                       |
| --- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| V0  | **A long Run Shell Script**: `sleep 1500` from the Shortcuts app and from Photos' Share menu; does Shortcuts (or the share extension) wait?                                             | both finish                                                                                                                                               | the script detaches the batch (`nohup` or a launchd job) and the shortcut's second half runs from a "Finish" shortcut or polls a done file; decide before phase 3 |
| V1  | Photos' `export … with using originals` on a selection of a video, a Live Photo, a slo-mo, a still                                                                                      | the recorded `.MOV` files; the Live Photo as a pair; `id`/`filename` lines                                                                                | adjust the skip rules                                                                                                                                             |
| V2  | What the Share menu and the picker pass for videos: Shortcut Input empty (as for photos) or a file? Original or rendered? Temp paths?                                                   | known; the probe-first order holds                                                                                                                        | reorder the entry points                                                                                                                                          |
| V3  | AppleScript `import` of an `.mp4` with Opus and with AV1 into the real library; album additions by id and by name; the originals collected                                              | the copies play in Photos, show date, location, camera and "Dolby Vision" in the Info panel (H.265; and AV1?), look like the originals, sit in the albums | if Photos refuses AV1 or Opus, the README says so and the menu drops the choice; `.mov` container as the fallback (ffmpeg's `mov` muxer, same `vidmeta` step)     |
| V4  | A 10-minute 4K video through the whole shortcut, with the Terminal window                                                                                                               | progress lines, the log, the notification, free-space check                                                                                               | tune the progress interval, the timeouts                                                                                                                          |
| V5  | Detecting spatial video (MV-HEVC) and Cinematic mode in ffprobe's output                                                                                                                | a side-data or stream-count rule                                                                                                                          | document them as not detected; `delete` as usual                                                                                                                  |
| V6  | `Get Details of Images ▸ Album` and `Media Type` on video items from the picker and from the share input                                                                                | album names; "Video"                                                                                                                                      | albums only where available                                                                                                                                       |
| V7  | `ffmpeg --version` (two dashes, as `release.py` calls it) prints the `--extra-version` suffix of our build; and what Photos' Info panel shows for a copy (lens, aperture, Dolby Vision) | the suffix is printed; the panel matches the original's                                                                                                   | `release.py` learns a per-encoder version command; the README names what the panel lacks                                                                          |

### 5.3. Results of 5.2 (2026-10-05, run by the user with throwaway shortcuts)

| #   | Result                                                                                                                                                                                                                                                                                                                                                                                                        |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| V0  | Passed from Photos' Share menu (the system log's `runSource: action`): a 1500 s Run Shell Script ran to its end and the next action got its output; other shortcuts running meanwhile didn't disturb it. The Shortcuts app runs one shortcut at a time: starting another stops the running one.                                                                                                               |
| V1  | `export … with using originals` on a still, a Live Photo, a video and a slo-mo: the recorded files (the slo-mo at 240 fps, `r_frame_rate` 240, average 177), the Live Photo as `IMG_x.HEIC` plus `IMG_x.mov` (lowercase), one `id/L0/001\|filename` line per selected item (the Live Photo's `.mov` has none).                                                                                                |
| V2  | Share menu: Shortcut Input holds only the videos, as re-rendered copies (the slo-mo rendered: 14 MB instead of 24) in `~/Library/Group Containers/group.com.apple.shortcuts/Temporary/…`, which `cp` and `head` read but ffprobe (Homebrew's and ours) can't ("Operation not permitted"). Picker: Shortcuts re-exports the picked videos to hand them over and failed (AVFoundation -11800, -16364). Dropped. |
| V3  | Passed (the user's check): H.265 and AV1 copies imported into the library and into their originals' albums, play, and show the originals' date, location, camera and lens; the originals collected in *Videos already compressed*; "Same as last time" offered on the second run.                                                                                                                             |
| V5  | Not run: spatial video is detected by "Stereo 3D" side data or a Multiview profile, not yet seen on a real one.                                                                                                                                                                                                                                                                                               |
| V6  | Get Details of Images: empty (Media Type, Photo Type, Album) for Share-menu input; Media Type "Video" for picked items, Photo Type empty even for a slo-mo. Moot without the picker.                                                                                                                                                                                                                          |
| V7  | Failed as stated: `ffmpeg --version` exits 8 (ffprobe 1), the version line on stderr only (Homebrew's too); `-version` prints `9.0.2-compress-videos-0.1.0`. `release.py` learned per-encoder version options.                                                                                                                                                                                                |

## 6. Implementation phases

1. **Shared code** (no user-visible change): `lib/wfkit.py`, `lib/mac/*`,
   `tests/shortcut_helpers.py`; the photos' generators and tests keep passing,
   and the generated plists are byte for byte the same (a one-off comparison
   test in the PR). Skipped if decision 3 picks the lighter alternative.
2. **The tools**: `build-macos.sh` (the static ffmpeg and ffprobe, 4.1, and
   `vidmeta` from `src/vidmeta.c` + the draft's `mp4meta.c`),
   `test_vidmeta.py`, `release.json`, `VERSION`, the changelog entry, tox and
   CI steps (library cache), the `test_release.py` case;
   `release.py compress-photos --dry-run` builds and version-checks the three
   binaries. The largest new piece of work; the draft's `build-wasm.sh` is the
   template.
3. **Spikes V0–V2** with a hand-built shortcut (an hour); V0 first, since its
   answer changes the shortcut's shape.
4. **The shortcut**: `vf.py` (lists and questions), `build_mac_shortcuts.py`
   (probe → input → picker; the two routes), `scripts/mac/*.zsh` with
   `encode.zsh`, the import script's albums-by-name pass, `make_video.swift`,
   `avmeta.swift`, `test_mac_shortcuts.py`, `test_mac_script.py`,
   `test_conversion.py`, the *Same as last time* menu and its settings file.
   Manual check on this Mac: V3, V4, V6, V7, from Photos and from the picker,
   with an HDR video, a slo-mo, a Live Photo and a still in the selection.
5. **Docs and release 0.1.0**: `shortcuts/compress-videos/README.md` (use, what
   is kept, playback compatibility, troubleshooting), `DEVELOPING.md`, the root
   README's table and install section, `tests/README.md`, `CHANGELOG.md`;
   `release.py compress-videos`.
6. **Later, optional**: *Compress Video Files (macOS)* for Finder (the script
   already works on files); the iPhone version (the draft's `vidbatch.wasm`,
   AV1 added, under this folder's version).

## 7. Decisions (settled 2026-10-05 unless marked open)

01. **Defaults marked in the lists**: the lists stay in the order given in 3.2
    (no reordering to put defaults first); the marked ones are preset *medium*
    and *5*, tune *none*, RF *24* for H.265 and *30* for AV1, size *2K*, audio
    *160*. Shortcuts can't preselect, so this is a label only.
02. **Nothing is assumed installed**: our static `ffmpeg` and `ffprobe` and the
    `vidmeta` helper are release files, installed by one Terminal line (3.5); a
    Homebrew ffmpeg is accepted as a fallback.
03. **Shared `lib/`** (4.9, phase 1), with a clean, surgical refactoring of
    `shortcuts/compress-photos`: verbatim moves, re-exports, byte-identical
    output, nothing else touched.
04. **Album name** *Videos already compressed*.
05. **Output extension `.mp4`**.
06. **All cores, no question**: one video at a time, each encoder on every
    core; `nice -n 10` keeps the Mac responsive without taking cores away.
07. **No `keep` flag; those videos are skipped instead** (3.4): slo-mo above
    100 fps, spatial video, undecodable audio, and a Dolby Vision source on an
    ffmpeg that can't carry the layer are not converted at all (a copy that
    loses something next to an original that stays is a duplicate); they are
    counted as skipped. Every converted video's original is collected.
08. **Question order** codec → preset → tune → RF → size → audio, plus the
    *Same as last time* menu that shows the previous settings in its title
    (3.2, 4.6), in the first release.
09. **The metadata step is `vidmeta`** (the draft's byte-exact `mp4meta.c`),
    not exiftool (4.5).
10. **Dolby Vision passthrough on by default**, for H.265 and AV1, with the VBV
    cap HandBrake applies (the bitrate cap is acceptable) and a `DOLBY=0`
    switch; sources without Dolby Vision get none of its options (row Q), so
    SDR and plain-HDR videos are not affected.

## 8. Risks

- **V0**: if a Run Shell Script can't run for an hour, the shortcut needs the
  detach-and-finish shape, which costs a second shortcut and polling. Checked
  first.
- **AV1 playback** on older devices in a shared library: a user who picks AV1
  on an M4 Mac gets videos their iPhone 14 can't play. The menu's wording and
  the README carry the warning; the photos' pattern of saying it in the
  shortcut's note helps.
- **Disk space**: the selection route copies every original out of Photos
  first; a batch of twenty 4K videos is tens of gigabytes. The script checks
  and refuses; the README says to convert in smaller batches.
- **The static ffmpeg build** is the largest piece of new build code: four
  libraries, a configure line to keep minimal, minutes of CI time (cached), and
  FFmpeg's and x265's updates to follow. The draft's `build-wasm.sh` already
  solved the downloads and the x265 dual build; the native build is simpler
  than the WASI one.
- **A Homebrew ffmpeg as the fallback** can differ from ours (version, wrapper
  defaults): the script logs which one it uses, the checks in 4.1 apply to
  both, and `test_conversion.py` runs against both in CI.
- **Dolby Vision passthrough** caps the peak bitrate at the Dolby level's
  main-tier rate (25 Mbps for 4K30), as HandBrake does; at low RF values on
  grainy 4K HLG that can cost quality in peaks. The README says so and
  `DOLBY=0` turns it off. `-strict unofficial` is what ffmpeg demands for the
  `dvvC` box in MP4; it changes nothing else in the file.
- **Cinematic videos** lose what Photos adds on top of the recording and can't
  be told apart yet (spike V5); the README says so. Slo-mo is skipped.
- **Time**: slow presets at 4K are hours per video on this Mac (x265 slow,
  SVT-AV1 preset 2); the progress window and ETA are what makes that bearable,
  and the README gives the measured rates.

Sources: HandBrake `libhb/encx265.c` and `libhb/encsvtav1.c` (master); SVT-AV1
4.2.0 `SvtAv1EncApp --help`; ffmpeg 9.0.2 `-h encoder=libx265`,
`-h encoder=libsvtav1`; exiftool 13.35 (`-listw -QuickTime:Keys`, and the
copies in 5.1, row G); HandBrake `libhb/dovi_common.c`;
`/System/Applications/Photos.app/Contents/Resources/Photos.sdef`;
`docs/compress-photos-mac-design.md` (the platform facts this plan builds on).
