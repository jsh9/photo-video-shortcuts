# Compress Videos: developer notes

How the Mac shortcut works, how to build its tools and the shortcut, and how to
release a new version. The design, with the spikes that settled it, is
[docs/compress-videos-mac-design.md](../../docs/compress-videos-mac-design.md).

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. How it works](#1-how-it-works)
  - [1.1. The ffmpeg command](#11-the-ffmpeg-command)
  - [1.2. Metadata: vidmeta](#12-metadata-vidmeta)
  - [1.3. What is skipped](#13-what-is-skipped)
- [2. Layout](#2-layout)
- [3. Building (Mac)](#3-building-mac)
- [4. Releasing a new version](#4-releasing-a-new-version)

______________________________________________________________________

<!--TOC-->

## 1. How it works

```
Compress Videos (macOS)                      (shortcut, from Photos' Share menu)
   Run AppleScript (lib/mac/probe.applescript): is Photos in front with a
   selection? If not: a notification ("Select the videos in Photos...") and
   stop. The selection is the only route; there is no picker: Shortcuts hands
   a script re-rendered copies of picked videos, through AVFoundation, and
   failed on some.

   Run Shell Script empties ~/Pictures/.compress-videos-macos (Photos'
   sandbox reaches ~/Pictures) and checks that its disk has 500 MB free per
   selected item (ROOM_PER_ITEM, for the export and the copies); if not, a
   notification and stop, before any question and before Photos exports
   anything

   "Same as last time" (when ~/Library/Caches/compress-videos-macos/
   last-settings.txt exists) or the six questions (vf.py): codec, preset,
   tune (H.265), RF, largest size, audio; each sets a variable

   Run AppleScript (lib/mac/export.applescript) has Photos export the
   originals into the work folder's in/ and returns "id|filename" lines

   Run Shell Script (/bin/zsh; scripts/mac/common.zsh + selection.zsh, with
   encode.zsh at its @RUN@; the settings and the lines as variables):
     checks the settings and the tools (compress-videos-ffmpeg and -ffprobe
     in ~/.local/bin, else Homebrew's ffmpeg 7.1+; vidmeta), sorts in/: photos
     and Live Photos (a photo whose .mov isn't an item of its own) skipped;
     each video probed with ffprobe and skipped if a copy would lose
     something (1.3); checks the free space against the exported files' size;
     then for each video, niced:
       ffmpeg ... in/IMG_1234.MOV vid_out_N.mp4   (1.1; progress lines)
       ffprobe vid_out_N.mp4   (codec, 10 bits, the whole duration; its size
                                for the log)
       vidmeta copy in/IMG_1234.MOV vid_out_N.mp4   (1.2)
     moves each copy to out/IMG_1234.mp4 and prints
       path|original id|delete|IMG_1234.mp4
     writes last-settings.txt and vid_skipped.txt

   Run AppleScript (lib/mac/import.applescript, input: those lines) has Photos
   import the copies, add each to its original's albums, and add the originals
   to the album "Videos already compressed"; returns "imported=N",
   "collected=M" and "! ..." lines

   the log in Quick Look if it has a "!" note, an error or a failure; the
   finish script (lib/mac/finish.zsh) appends the outcome and "Done", ends the
   Terminal window, removes in/ and the vid_* files; notifications: what was
   skipped, how many were saved and collected
```

Shortcuts waits for the Run Shell Script however long it takes (checked with a
25-minute script from Photos' Share menu: the shortcut went on afterwards). A
Terminal window (`lib/mac/progress.zsh`; `WATCH=0` turns it off) follows the
log, which has the command line of each video, a progress line every 5 s
(`PROGRESS_EVERY`), and the size and speed of each copy. Switches at the top of
the script: `NICE=10` (ffmpeg's priority), `DOLBY=1` (0: Dolby Vision videos
become plain HDR), `SLOMO=1` (0: no video is skipped as slo-mo, 1.3), and
`FFMPEG`, `FFPROBE`, `VIDMETA` (other tools, used by the tests). The script
never exits nonzero for a conversion problem: it writes `ERROR:` and `!` lines
to the log, which the shortcut shows.

### 1.1. The ffmpeg command

HandBrake's settings (from its `libhb/encx265.c`, `encsvtav1.c` and
`dovi_common.c`) as ffmpeg options, as the log shows them:

```
nice -n 10 ffmpeg -hide_banner -nostdin -v warning -nostats -progress pipe:1 -y \
  -hwaccel none -noautorotate -i in/IMG_1234.MOV -map 0:v:0 -map 0:1 -map_metadata -1 \
  -fps_mode passthrough \
  -vf "scale=w='min(iw,2560)':h='min(ih,2560)':force_original_aspect_ratio=decrease:force_divisible_by=2" \
  -c:v libx265 -preset medium -crf 24 -profile:v main10 -pix_fmt yuv420p10le \
  -x265-params keyint=300:min-keyint=30:vbv-bufsize=130000:vbv-maxrate=130000 \
  -dolbyvision 1 -strict unofficial -tag:v hvc1 -c:a libopus -b:a 160k vid_out_1.mp4
```

- The size limit fits the stored frame in an L×L box: the long edge is at most
  L whatever the orientation, never enlarged, even sizes for 4:2:0.
  `-noautorotate` keeps the frame as stored and its rotation flag.
- 10-bit 4:2:0 for every video, as HandBrake's 10-bit encoders (ProRes's 4:2:2
  too: `-pix_fmt yuv420p10le` converts it); frame rate as recorded
  (`passthrough`); the color tags come from the stream.
- x265: `keyint` 10 × the rounded average frame rate, `min-keyint` the rate,
  `-tune grain` when chosen, `hvc1` (Apple needs it). SVT-AV1:
  `-svtav1-params tune=0:enable-variance-boost=1:film-grain=8` (HandBrake's VQ
  tune and the user's HandBrake options), no keyframe interval (SVT-AV1's
  default, as HandBrake).
- Dolby Vision (a source with a DOVI configuration record, `DOLBY=1`):
  `-dolbyvision 1 -strict unofficial` (else the MP4 muxer drops the `dvvC`
  box). x265 needs VBV for the RPU's HRD: HandBrake's rate is the first Dolby
  Vision level the copy's width and pixels per second fit (the copy's size
  computed as libavfilter rounds it), at the high tier, since x265 allows the
  high tier by default (70 Mbit/s up to 1080p60 and 1440p30, 130 for 4K up to
  60 fps, 240 for 4K120). ffmpeg sets the Dolby Vision level from the size
  alone.
- Sound: the first track with at most 2 channels ffmpeg can read (iPhones: the
  stereo AAC; their spatial audio is Apple's APAC, which ffmpeg can't read),
  else the first readable one with `-ac 2`, else none (`-an`). Opus at 48 kHz.
- `-map_metadata -1`: ffmpeg's own copy of the keys is wrong for Photos (1.2).

The script sets `SVT_LOG=2`, so SVT-AV1 prints only its warnings.

Everything runs in software, on the CPU, as HandBrake's x265 and SVT-AV1
encoders do: our build has no VideoToolbox (`--disable-autodetect`), decodes
AV1 with dav1d, and the command says `-hwaccel none`, which also keeps
Homebrew's ffmpeg from decoding with the Mac's media engines.

### 1.2. Metadata: vidmeta

ffmpeg writes a video's Apple keys back as unnamed text entries (AVFoundation
reads them as `itsk/…`, so Photos sees no date or place) and drops the video
track's keys (lens, focal length, aperture). `vidmeta copy ORIGINAL COPY`
(`src/vidmeta.c` and `src/mp4meta.c`) rewrites the copy's `moov`, its last box:
the original's movie-level `meta` and `udta` boxes replace the copy's, the
original's first video track's `meta`/`udta` boxes go into the copy's video
track, and the movie, track and media times are set from the original's `mvhd`.
Byte for byte, so every value keeps its type (int64, int8, int32, `en-US`
strings). It refuses a copy whose `moov` isn't last, a damaged file, or a file
without `moov`; the script then fails that video. `vidmeta --selftest` writes
two small MP4 files, copies one's metadata onto the other and reads it back.
`vidmeta key FILE KEY` prints one of the movie's keys (UTF-8 text, or an
integer in decimal; exit status 1 when the file doesn't have it): the script
reads the slo-mo mark with it (1.3), since ffprobe reads an iPhone's 8-byte
integers as 0. `vidmeta log FILE` prints the name of the first video track's
log curve, the `logs` box of its sample description (Apple Log:
`com.apple.rec2020.apple-log`, Apple Log 2:
`com.apple.apple-wide-gamut.apple-log`), which AVFoundation writes from the
frames' `kCVImageBufferLogTransferFunctionKey`; ffprobe shows only an unknown
transfer.

### 1.3. What is skipped

Before any video is converted, from the exported files and ffprobe:

- photos, and Live Photos (a photo plus a `.mov` that isn't an item of its own;
  when Photos' export lists no items, any photo with a `.mov` of its name);
- a video whose picture this ffmpeg can't decode: its codec isn't among those
  `ffmpeg -codecs` marks `D` (our build decodes HEVC, H.264, ProRes and AV1);
- slo-mo (with `SLOMO=1`, the default): Photos exports the recording at its
  capture rate (a 240 fps slo-mo averages 177) and the slow part is an edit, so
  a copy would play at normal speed. A video averaging above 61 fps is skipped
  unless its movie key `com.apple.quicktime.full-frame-rate-playback-intent` is
  1\. Recent iPhones write it on every video (seen on an iPhone 17 Pro): 0 for a
  slo-mo, 1 for the others, which play at their full rate, so a 4K video
  recorded at 120 fps (not slo-mo) is converted. Without the key (older
  iPhones, other cameras), a fast video is skipped as "perhaps slo-mo";
  `SLOMO=0` converts it. The average, not ffprobe's `r_frame_rate`: a
  variable-rate video can put it far above its real rate (150 for a Live
  Photo's video that averages 28);
- spatial video: "Stereo 3D" side data or a Multiview profile (not yet seen on
  a real spatial video);
- a log recording (Apple Log): `vidmeta log` names a log curve, or the video is
  ProRes with no known color transfer (`unknown`, missing or `reserved`), in
  case a recording lacks the `logs` box. Apple Log is flat, meant to be graded
  with a LUT, so a copy would look washed out. The rule was made from files
  AVFoundation writes in Apple Log (`make_video.swift --apple-log`), not from a
  real iPhone recording;
- sound none of whose tracks ffmpeg can read (the copy would be silent);
- Dolby Vision, when the ffmpeg in use has no `-dolbyvision` option.

## 2. Layout

| Path                             | What it is                                                                                                                                                |
| -------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `release.json`                   | the release files: `ffmpeg-macos`, `ffprobe-macos`, `vidmeta-macos` and the Mac shortcut                                                                  |
| `VERSION`                        | the version, shared by the shortcut, `vidmeta` and our ffmpeg's version line                                                                              |
| `src/`                           | `vidmeta.c` (the CLI and its self-test), `mp4meta.c` (the box copy, and reading a key or the log curve)                                                   |
| `scripts/build-macos.sh`         | builds `dist/ffmpeg-macos`, `dist/ffprobe-macos`, `dist/vidmeta-macos` and `build/vidmeta` (with the sanitizers, for the tests)                           |
| `scripts/vf.py`                  | the questions (titles, descriptions, defaults) and their builders; re-exports `lib/wfkit.py`                                                              |
| `scripts/build_mac_shortcuts.py` | generates and signs `dist/Compress Videos (macOS).shortcut`                                                                                               |
| `scripts/mac/*.zsh`              | the conversion script: `common.zsh` (settings, tools), `selection.zsh` (staging, probing, skipping, result lines), `encode.zsh` (ffmpeg, checks, vidmeta) |
| `../../lib/`                     | shared with Compress Photos: the plist builder, the AppleScripts, the progress window and the finish step                                                 |

`build/` and `dist/` are not committed.

## 3. Building (Mac)

On Apple silicon, with Homebrew `cmake`, `ninja`, `meson` and `pkgconf`, from
this folder (`shortcuts/compress-videos`):

```bash
./scripts/build-macos.sh
python3 scripts/build_mac_shortcuts.py --guess
```

`build-macos.sh` downloads the sources of FFmpeg 9.0.2, x265 4.3, SVT-AV1 4.2.0
libopus 1.6.1 and dav1d 1.5.4 into the repository's `.deps/` (checked against
the SHA-256 of Homebrew's formulae), builds x265 twice (10-bit linked into
8-bit), SVT-AV1, libopus and dav1d (AV1 decoding: AV1 videos in, and AV1
copies' pixel format for ffprobe; FFmpeg's own AV1 decoder works only with a
hardware accelerator) as static libraries, and FFmpeg with
`--disable-everything` plus what the shortcut uses, linked statically (only
`libSystem` and `libc++` remain; `-dead_strip_dylibs` drops the frameworks
FFmpeg's configure adds anyway). About a minute and a half on an M4 Pro; a
second run rebuilds only what changed.
`--extra-version=compress-videos-<VERSION>` puts the version in ffmpeg's and
ffprobe's version line. `ONLY=vidmeta ./scripts/build-macos.sh` builds the
helper alone. The build is GPL (x265); see
[licenses](../../licenses/README.md).

`build_mac_shortcuts.py --guess --no-sign` writes the unsigned plist the tests
and CI use; without `--no-sign` it signs the shortcut (`shortcuts sign`, which
needs an Apple ID). The tests are described in
[tests/README.md](../../tests/README.md).

## 4. Releasing a new version

A release is built, signed and published from a Mac by `scripts/release.py` (at
the repository root), not by CI: signing the shortcut needs macOS and an Apple
ID. What the script checks and the notes it writes are in
[docs/releasing.md](../../docs/releasing.md). Every release carries the current
files of all the shortcuts, so a Compress Videos release also re-publishes
Compress Photos' files (marked *unchanged* in the notes), and the README's
"latest" download links keep working for both.

1. **Bump the version, in a PR.** Set `VERSION` (shared by the shortcut,
   `vidmeta` and our ffmpeg's version line) and add the entry at the top of
   [CHANGELOG.md](../../CHANGELOG.md) with the release date:
   `## [Compress Videos 0.2.0] - 2026-11-01`. Say which files to update (for
   example "Update the shortcut; the tools are unchanged"), because the README
   tells users to download only those. Merge it to `main`. (0.1.0, the first
   version, came with the PR that added the shortcut.)

2. **Set up the Mac** (once):

   - signed in to an Apple ID, for `shortcuts sign`;
   - Homebrew's `cmake`, `ninja`, `meson` and `pkgconf` for this tool's build,
     and the packages Compress Photos' build needs (see its
     [Building](../compress-photos/DEVELOPING.md#3-building-mac)), since every
     release builds every shortcut: `binaryen`, and `wasmtime`, which runs its
     WebAssembly encoders' `--version`;
   - `gh` logged in with access to the repository (`gh auth status`), since
     `gh release create` publishes.

3. **Try the build on the Mac (recommended).** The tests run the shortcut's
   script, not Shortcuts itself. From the repository root,
   `python3 scripts/release.py compress-videos --dry-run` builds and signs
   everything without creating a tag or release (the first run downloads
   FFmpeg, x265, SVT-AV1, libopus and dav1d into `.deps/`). Then install what
   it built, from the repository root:

   ```bash
   cp shortcuts/compress-videos/dist/ffmpeg-macos ~/.local/bin/compress-videos-ffmpeg && cp shortcuts/compress-videos/dist/ffprobe-macos ~/.local/bin/compress-videos-ffprobe && cp shortcuts/compress-videos/dist/vidmeta-macos ~/.local/bin/vidmeta && ~/.local/bin/vidmeta --selftest
   ```

   double-click
   `shortcuts/compress-videos/dist/Compress Videos (macOS).shortcut` (Add
   Shortcut, or Replace), and convert a few videos from Photos' Share menu with
   each codec: an HDR video, a Live Photo, a slo-mo and a photo among them. The
   PR that changed the shortcut may list what to look at.

4. **Update `main`.** A real run refuses to publish unless the checkout is on
   `main`, clean (no untracked files either), and the same as `origin/main`:

   ```bash
   git checkout main
   git pull
   git status
   ```

5. **Publish.** From the repository root:

   ```bash
   python3 scripts/release.py compress-videos
   ```

   It rebuilds every shortcut, checks the files, each tool's version
   (`-version` for ffmpeg and ffprobe, `--version` for the others) and the
   ZIPs, then prints the files and the release notes and asks you to confirm
   (`[y/N]`). Check that the list has `ffmpeg-macos`, `ffprobe-macos`,
   `vidmeta-macos` and `compress-videos-mac-shortcuts-v<version>.zip` (next to
   Compress Photos' files), and that the notes have the Compress Videos
   changelog entry, marked **new** (the first release) or **updated**; answer
   `y` to create the tag `compress-videos-v<version>` and the release. Any
   other answer publishes nothing.

6. **Check the result.** The
   [Releases page](https://github.com/jsh9/photo-video-shortcuts/releases)
   should show `Compress Videos <version>` as Latest, with those files. Run the
   README's install line on the Mac (it downloads from that release and
   replaces your copies in `~/.local/bin`) and check that it ends with
   "Self-test passed" and that `~/.local/bin/compress-videos-ffmpeg -version`
   ends its first line with `compress-videos-<version>`.

A real run (not `--dry-run`) also stops when the tag already exists, the
changelog has no dated entry for the version, or the version is the same as in
the latest published release.
