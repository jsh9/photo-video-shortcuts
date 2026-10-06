# Compress Videos

**Compress Videos (macOS)** converts the videos you select in Photos to much
smaller H.265 or AV1 copies, with HandBrake's settings and Opus sound, and
saves them back to Photos next to the originals, in the same albums, with their
capture date and time zone, location, camera and lens, HDR and Dolby Vision.
The originals are collected in an album, *Videos already compressed*, for you
to delete when you're happy with the copies. Nothing is deleted by the
shortcut.

It runs on a Mac with Apple silicon and macOS 14 or later, and only on videos
selected in Photos: run from the Shortcuts app or anywhere else, it just tells
you to select them in Photos. An iPhone version is planned.

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. Install (once)](#1-install-once)
- [2. Use](#2-use)
  - [2.1. The questions](#21-the-questions)
  - [2.2. What happens](#22-what-happens)
- [3. What is kept, and what isn't](#3-what-is-kept-and-what-isnt)
- [4. Which devices play the copies](#4-which-devices-play-the-copies)
- [5. How long it takes](#5-how-long-it-takes)
- [6. Troubleshooting](#6-troubleshooting)
- [7. Updating](#7-updating)

______________________________________________________________________

<!--TOC-->

## 1. Install (once)

1. **Install the tools.** In Terminal, paste this line and press Return:

   ```
   mkdir -p ~/.local/bin && cd ~/.local/bin && curl -L -o compress-videos-ffmpeg https://github.com/jsh9/photo-video-shortcuts/releases/latest/download/ffmpeg-macos && curl -L -o compress-videos-ffprobe https://github.com/jsh9/photo-video-shortcuts/releases/latest/download/ffprobe-macos && curl -L -o vidmeta https://github.com/jsh9/photo-video-shortcuts/releases/latest/download/vidmeta-macos && chmod +x compress-videos-ffmpeg compress-videos-ffprobe vidmeta && ./vidmeta --selftest
   ```

   It should end with "Self-test passed". The three tools are about 33 MB:
   `compress-videos-ffmpeg` and `compress-videos-ffprobe` are FFmpeg 9 built
   for this shortcut, with x265, SVT-AV1, libopus and dav1d in it and nothing
   else (their own names, so that they never replace another ffmpeg in your
   Terminal); `vidmeta` copies the videos' metadata. Without them, the shortcut
   uses Homebrew's ffmpeg (7.1 or later) if you have it, but it still needs
   `vidmeta`.

2. **Allow scripts.** Shortcuts ▸ Settings ▸ Advanced ▸ **Allow Running
   Scripts** (already on if you use Compress Photos on the Mac).

3. **Add the shortcut.** From the latest
   [release](https://github.com/jsh9/photo-video-shortcuts/releases) download
   `compress-videos-mac-shortcuts-v<version>.zip`, unzip it, and double-click
   *Compress Videos (macOS)* → Add Shortcut.

4. **Grant permissions.** The first time you run it from Photos, macOS asks
   whether Shortcuts may control Photos: choose Always Allow. Allow the other
   questions too (Photos, notifications).

## 2. Use

In Photos, select the videos, then **Share ▸ Compress Videos (macOS)** (in the
toolbar, or right-click ▸ Share). This is the only way to use it: Photos must
be in front with the videos selected. Started from the Shortcuts app, Spotlight
or the menu bar with nothing selected in Photos, it only tells you to do this;
it has no file or photo picker, because Shortcuts can't give a script the
original videos (it hands over re-rendered copies). You can select photos and
Live Photos too; they are skipped.

### 2.1. The questions

Shortcuts can't preselect an answer, so the usual one is marked *(default)*.

1. **Video codec**: *H.265* plays on every Apple device since 2017; *AV1* makes
   smaller files but plays only on newer devices (see
   [section 4](#4-which-devices-play-the-copies)).
2. **Preset**: how hard the encoder works. H.265: *fast*, *medium* (default),
   *slow* (about twice medium's time, a little smaller). AV1: *5* (default),
   *4*, *3*, *2*, each slower and a little smaller.
3. **Tune** (H.265 only): *none* (default), or *grain*, which keeps film grain
   and fine noise instead of smoothing it, for bigger files.
4. **Quality (RF)**: lower is better and bigger; 24 (H.265) and 30 (AV1) are
   the defaults. The numbers don't mean the same in the two encoders.
5. **Largest size**: the limit for the long edge, so a vertical video gets the
   same limit on its height: *4K* (3840), *2K* (2560, default), *1080p* (1920),
   *720p* (1280). A video is never enlarged.
6. **Audio (Opus)**: 64 to 256 kbps; 160 (default) is essentially transparent.

From the second time on, a first list offers **Same as last time** (with the
last settings in its title) or **Choose…**.

### 2.2. What happens

Photos exports the original files, and a Terminal window follows the
conversion, one video at a time, with its progress and the time left (close it
whenever you like; it doesn't stop anything). Each copy, `IMG_1234.mp4` for
`IMG_1234.MOV`, is checked, gets the original's metadata, and is imported into
Photos, into every album its original is in. The originals go into the album
**Videos already compressed**. Notifications say what was skipped and how many
videos were saved. If something went wrong, the log opens; it is kept in
`~/Library/Caches/compress-videos-macos/videos.log`.

When you're happy with the copies, open *Videos already compressed* in Photos,
select all, and delete them (they stay in Recently Deleted for 30 days). Photos
may list a copy and its original under Duplicates.

The originals are copied out of Photos first, so you need free space for them
plus the copies. Before Photos copies anything, the shortcut asks for about 500
MB free per selected item, and stops if there isn't that much (it can't know
the videos' sizes yet); once they are copied, it checks their real size and
stops if they and their copies won't fit. So convert a large selection in
smaller batches, a month or a trip at a time, and select only the videos (in
Photos' sidebar, Media Types ▸ Videos).

## 3. What is kept, and what isn't

Kept, as Photos shows them:

- the capture date with its time zone, the location, the camera (make, model,
  software), the lens, focal length and aperture, and Apple's other keys, each
  with its original type;
- the orientation, the frame rate (variable, as recorded) and the duration;
- HDR: a 10-bit HLG video stays 10-bit HLG; and Dolby Vision, as HandBrake
  carries it (to H.265 as profile 8.4, like the iPhone's; to AV1 as profile
  10);
- the albums and the file name.

Not converted at all (counted as skipped): slo-mo videos (the slow part is an
edit that a copy would lose: it would play at normal speed), spatial videos
(one view would be kept), Apple Log videos (a flat picture meant to be graded
with a LUT: a copy would look washed out), videos whose picture or sound ffmpeg
can't read, and photos and Live Photos. Our ffmpeg reads H.265, H.264, AV1 and
Apple ProRes videos: an iPhone Pro's ProRes recordings, the largest files an
iPhone makes, are converted like any other, and so is an AV1 or H.265 video, a
copy this shortcut made for example.

Which videos count as Apple Log (iPhone 15 Pro and later): those whose file
names the Apple Log curve, as Apple's video framework records it, and, to be
safe, any ProRes video without a known color transfer (the file doesn't say how
its brightness is coded).

Which videos count as slo-mo: those recorded at more than 61 frames per second
that the iPhone marked as slo-mo. Recent iPhones mark every video, so a video
recorded at 120 fps in normal Video mode (4K at 120 fps on an iPhone 16 Pro and
later) is converted, at 120 fps. A fast video without the mark, from an older
iPhone or another camera (an action camera's 100 or 120 fps video, say), is
skipped as *perhaps slo-mo*, as the log says. To convert those too: open the
shortcut in Shortcuts, find the Run Shell Script action whose script starts
with `# Compress Videos (macOS)`, and change its line `SLOMO=${SLOMO:-1}` to
`SLOMO=0`. Then no video is skipped as slo-mo, real ones included (their copies
play at normal speed); change it back afterwards.

Not kept in the copies:

- spatial audio: an iPhone's 4-channel spatial sound track; the stereo track is
  kept;
- ProRes's full color resolution: its 4:2:2 color becomes 4:2:0, as in every
  H.265 and AV1 video (the iPhone's own H.265 included); the brightness keeps
  its full resolution and 10 bits;
- edits: the original recording is converted, without trims or filters made in
  Photos;
- Cinematic mode's focus changes, and other timed data tracks (the copy is the
  recording with its focus as shot).

## 4. Which devices play the copies

- **H.265**: every Apple device since 2017; Opus sound needs iOS 17 or macOS 14
  or later.
- **AV1**: only devices with an AV1 decoder: Macs with an M3 chip or later,
  iPhone 15 Pro or later, iPads with an M2 or A17 Pro chip or later. On older
  devices Photos shows the video but can't play it. If your library is shared
  through iCloud with older devices, choose H.265.

## 5. How long it takes

Measured on a 14-core M4 Pro, a 4K 30 fps iPhone video limited to 2K: H.265
*medium* converts about as fast as the video plays (1.1× real time), *fast*
about 1.5×; AV1 preset 5 about 0.6×. *slow* and the lower AV1 presets take
several times longer. The Mac stays usable: ffmpeg runs at a lower priority.
Everything is done in software, on the CPU, as with HandBrake's x265 and
SVT-AV1 encoders: the Mac's hardware video encoders and decoders are never
used.

## 6. Troubleshooting

- **It doesn't appear in Photos' Share menu**: enable the Shortcuts extension
  in System Settings ▸ General ▸ Login Items & Extensions ▸ Sharing, and *Show
  in Share Sheet* in the shortcut's details (the ⓘ button in the editor); and
  select at least one video.
- **Photos doesn't respond to the shortcut**: allow Shortcuts to control Photos
  in System Settings ▸ Privacy & Security ▸ Automation ▸ Shortcuts ▸ Photos.
- **"Select the videos in Photos…"**: Photos wasn't in front with a selection
  when it started. Start it from Photos' Share menu.
- **"Not enough free space for the N item(s)…"**: the shortcut wants about 500
  MB free per selected item before Photos copies them out. Select fewer videos,
  or free some space.
- **The log says `ERROR: ffmpeg is not installed` or
  `vidmeta is not installed`**: install the tools
  ([section 1](#1-install-once)).
- **The log says a video "failed"**: the reason is on the lines above it; the
  other videos are converted anyway, and the original stays where it was.
- **No Terminal window**: Terminal may have asked for permission; the
  conversion runs anyway.

## 7. Updating

The shortcut's version is in its first note, and the tools report theirs:
`vidmeta --version`, and `compress-videos-ffmpeg -version` (the end of its
first line). The
[Releases page](https://github.com/jsh9/photo-video-shortcuts/releases) says
which files a release changed; download those the same way as above.
