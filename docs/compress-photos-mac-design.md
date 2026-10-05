# Compress Photos (macOS): design plan

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. Verdict](#1-verdict)
- [2. What changes compared with the iPhone](#2-what-changes-compared-with-the-iphone)
- [3. User-facing design](#3-user-facing-design)
  - [3.1. Names](#31-names)
  - [3.2. Compress Photos (macOS)](#32-compress-photos-macos)
  - [3.3. Compress Photo Files (macOS)](#33-compress-photo-files-macos)
  - [3.4. Installation (what the README will say)](#34-installation-what-the-readme-will-say)
- [4. Technical design](#4-technical-design)
  - [4.1. Encoder: `jxlbatch-macos`](#41-encoder-jxlbatch-macos)
  - [4.2. The script core (`Run Shell Script`)](#42-the-script-core--run-shell-script)
  - [4.3. Getting File items back into Shortcuts](#43-getting-file-items-back-into-shortcuts)
  - [4.4. Showing progress and the log](#44-showing-progress-and-the-log)
  - [4.5. Where the encoder lives, and versions](#45-where-the-encoder-lives-and-versions)
  - [4.6. Permissions and macOS behaviors to document](#46-permissions-and-macos-behaviors-to-document)
  - [4.7. Versioning, manifest and release](#47-versioning-manifest-and-release)
  - [4.8. Code layout](#48-code-layout)
  - [4.9. Tests](#49-tests)
- [5. Spikes to run first (one throwaway shortcut, about an hour)](#5-spikes-to-run-first-one-throwaway-shortcut-about-an-hour)
- [6. Implementation phases](#6-implementation-phases)
- [7. Decisions taken (2026-10-04)](#7-decisions-taken-2026-10-04)
- [8. Risks](#8-risks)

______________________________________________________________________

<!--TOC-->

Status: implemented in Compress Photos 0.4.0 (2026-10-04), as described here,
with these differences: the shell script lives in `scripts/mac/*.zsh` and is
assembled by `build_mac_shortcuts.py` (not embedded in Python); the shared
plist builder is `scripts/wf.py`; the work folder is a fixed
`$TMPDIR/compress-photos-macos` (so the follow-up steps need no path parsing);
the encoder is found through `~/.local/bin` first, with a `JXLBATCH` override
for the tests. Spike results on macOS 26 (2026-10-04, with a diagnostic
shortcut): S2 failed, so the design changed: Run AppleScript returns nothing
for `POSIX file`, `alias` or a file URL, and Get File refuses absolute paths,
but Get File with a path relative to Shortcuts' iCloud Drive folder works, so
the Photos shortcut's work folder is `compress-photos-macos/` in that folder
(fallback 2 of section 4.3). S8 passed (the Run Shell Script keys work as
written). The shell runs unsandboxed in `com.apple.shortcuts.mac-helper` with
its own `$TMPDIR`. S6, S7 and S10 are done (static arm64 build, Gatekeeper via
`curl`, byte-identical output; see `test_mac_script.py`). S1: Shortcuts passes
the picker's photos as files whose names the shortcut supplies (the script
takes the names it is given). S3: albums come through for picker photos (two
album additions in one run). S4: Delete Photos works from the app when its
prompt can be shown, and is not registered in the share extension. S5: Photos'
Share menu and right-click ▸ Shortcuts hand over a JPEG export as a file URL
that Shortcuts' extension cannot represent (`WFFileRepresentation`'s
disallowed-directory or sandbox check), so the input is empty. Instead, the
shortcut asks Photos for its selection through AppleScript when Photos is in
front: Photos exports the originals (sub-second), imports the results by name,
and adds them to albums; a script can't delete photos, so the originals to
delete are collected in an album, by photo id, on the selection route only:
Delete Photos' permission prompt fails with "Presenter connection failed" in
most runs, so the Mac shortcut doesn't use it, and the picker route, which has
no photo ids, leaves the originals alone rather than look them up by file name
(decision 3 revised 2026-10-04). Progress is shown in a Terminal window that
follows the log (section 4.4's optional idea, now the default, `WATCH=0` turns
it off). Save to Photo Album accepts a `.jxl` file and Photos shows it. Run
AppleScript only compiles plain script text (no Shortcuts variables); values go
in through its input. Written 2026-10-04 against Compress Photos 0.3.1 on macOS
27.0 (Shortcuts 8); decisions settled the same day (section 7).

## 1. Verdict

Feasible, and simpler than the iPhone version. macOS Shortcuts has a built-in
**Run Shell Script** action that runs `/bin/zsh` as the user and *waits for it
to finish*, so the Mac shortcuts need no a-Shell, no `JXL-Import` helper, no
marker files, no `--retry`, no `Wait to Return`, and no app switching. The
encoder is the same `jxlbatch` source and the same job-file protocol
(`jxl_job.txt` → `jxl_out_N.jxl` + `jxl_done.txt`), built as a native,
statically linked, multi-threaded macOS binary instead of WebAssembly.

What is confirmed, on this Mac and in Apple's Shortcuts for Mac guide:

- The Shortcuts frameworks on this Mac contain every action the design needs:
  `runshellscript`, `runapplescript`, `selectphoto`, `properties.images` (Get
  Details of Images), `savetocameraroll`, `deletephotos`, `previewdocument`
  (Quick Look), `showresult`, `choosefrommenu`, `properties.files`,
  `file.getfoldercontents`, `documentpicker.open` (dyld shared cache, subcaches
  .65/.67/.75, together with `WFRunShellScriptAction`, `WFDeletePhotosAction`
  and the `InputMode` key).
- Shortcuts with **Show in Share Sheet** appear in the Share menu of Mac apps
  that have a Share button, Photos included, after the Shortcuts sharing
  extension is enabled in System Settings
  ([Apple](https://support.apple.com/guide/shortcuts-mac/apd163eb9f95/mac)).
- A **Run AppleScript** action coerces an AppleScript `file`/`alias` result to
  a Shortcuts file item, and a Shortcuts file input to an AppleScript alias
  (Apple's guide, quoted at
  [MacScripter](https://www.macscripter.net/t/running-applescripts-in-shortcuts/78092)).
  That is the bridge from paths printed by the shell script back to File items
  that **Save to Photo Album** accepts.
- `shortcuts run <name> --input-path FILE --output-path DIR` exists, so the Mac
  shortcuts can be driven end to end from pytest once imported.
- `build-native.sh` already builds `jxlbatch` for arm64 macOS (ad-hoc,
  linker-signed); only the dynamic Homebrew libraries stand between it and a
  distributable binary.

What is *not* verified yet is listed as spikes in section 5; none of them
threatens feasibility, they decide details (file names, paths, one action
format).

## 2. What changes compared with the iPhone

| iPhone (a-Shell)                                                    | Mac (Run Shell Script)                                                                       |
| ------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| Put File copies each photo into a-Shell's folder                    | Shortcuts passes the photos to the script as file arguments (`"$@"`); the script stages them |
| a-Shell runs `jxlbatch.wasm`, single core, iOS memory ceiling       | native `jxlbatch`, all cores (`JXLBATCH_THREADS`), no ceiling                                |
| handoff back by URL (`shortcuts://run-shortcut?name=JXL-Import`)    | none: Run Shell Script is synchronous, the shortcut continues when it exits                  |
| progress visible in a-Shell, which must stay in the foreground      | runs in the background; the log is shown afterwards (Quick Look) when it has warnings        |
| two shortcuts (`Compress Photos`, `JXL-Import`), the second by name | one shortcut per use case, no helper                                                         |
| `Wait to Return` only works inside the Shortcuts app                | works from the Share menu, the Shortcuts app, the menu bar, a keyboard shortcut, Finder      |
| Send As: Automatic turns HEIF into JPEG in the share sheet          | to be measured (spike S5); the picker path gives the library file either way                 |
| encoder installed by `curl` inside a-Shell                          | encoder installed by `curl` in Terminal (the one place the user uses a terminal)             |

The parts that stay the same: the quality presets and their contact-card list,
the still-photo filter (Get Details of Images: Media Type / Photo Type), albums
via Get Details of Images ▸ Album and Save to Photo Album, the `delete`/`keep`
decision from `jxl_done.txt`, Delete Photos with the system confirmation, the
notification texts.

## 3. User-facing design

### 3.1. Names

The Mac shortcuts sync to every device on the Apple ID, as the iPhone ones do,
so the names must tell them apart and say where they run. Decided:

- **Compress Photos (macOS)**: photos in the Photos library → JPEG XL copies in
  Photos, in the same albums, with the option to delete the originals.
- **Compress Photo Files (macOS)**: image files in Finder → `.jxl` files next
  to them. (Second shortcut; small, because it shares the script core.)

Parentheses are fine in shortcut names, in ZIP member names and in
`shortcuts run "Compress Photos (macOS)"`; nothing puts the names in a URL on
the Mac.

On an iPhone they appear but cannot run (Run Shell Script does not exist
there), and the iPhone's *Compress Photos* appears in the Mac's Share menu but
fails there (a-Shell actions). The READMEs say so.

### 3.2. Compress Photos (macOS)

Entry points, all supported by the same shortcut:

1. **Photos ▸ Share ▸ Compress Photos (macOS)** with photos selected.
2. **Shortcuts app / menu bar / keyboard shortcut**: shows the photo picker
   (Select Photos, Images only, multiple), as on the iPhone.

Flow:

01. Input: Shortcut Input if any, else Select Photos. (Same as iOS.)
02. Keep the still photos (`keep_still_photos`, unchanged): Live Photos and
    videos are skipped and counted; "Nothing to convert" stops.
03. Choose a quality (the contact-card list, unchanged; `QUALITY_PRESETS`).
04. Notification "Converting N photo(s)…" (the script is silent while it runs).
05. **Run Shell Script** (`/bin/zsh`, input = Stills, pass input *as
    arguments*), the script core of section 4.2, with the quality and the
    shortcut's version interpolated into the script text like the a-Shell
    command today. Its output (text) is the work folder's path followed by the
    `jxl_done.txt` lines.
06. Split the output into lines. For each `file|index|delete or keep|name`:
    - Run AppleScript `return POSIX file "<work>/<file>"` → a File item;
    - Save to Photo Album (Recents); the JXL keeps the original's name;
    - Get Details of Images ▸ Album of `Stills[index]`; Save to Photo Album for
      each (adds, doesn't copy; same as iOS);
    - if `delete`: add the original to `Converted`.
07. If the log has `!` or `ERROR` lines: Quick Look the log so the user sees
    what the iPhone user sees in a-Shell (HDR notes, failures). Otherwise skip.
08. Notification "Saved N photo(s) to Photos."
09. If `Converted` has items: Delete Photos (macOS asks "Delete N photos?",
    they go to Recently Deleted for 30 days). Decided: offered from both entry
    points, Share menu and picker, with the same `delete`/`keep` rules as iOS,
    since on the Mac the share-menu path keeps the originals in hand (no
    handoff). Only this shortcut deletes anything; Compress Photo Files (macOS)
    never does.
10. The script removes its work folder; a `trap` also removes it on failure.

### 3.3. Compress Photo Files (macOS)

Entry point: Finder ▸ right-click files or a folder ▸ Quick Actions ▸ Compress
Photo Files (macOS) (shortcut detail *Use as Quick Action ▸ Finder*; also
Services menu). Also usable from the Shortcuts app with a file picker. Nothing
touches Photos and nothing is ever deleted (decision 3).

Flow: expand folders (Get Contents of Folder), filter to HEIF/JPEG/PNG by
extension in the script (jxlbatch rejects other formats itself, with the batch
continuing), choose a quality, run the same script core with `OUTPUT=beside`,
which renames `jxl_out_N.jxl` to `<Name>.jxl` next to each original (never
overwriting: `<Name> 2.jxl`), Quick Look the log on warnings, notification
"Wrote N file(s)". Nothing touches Photos and nothing is deleted.

Open point (spike S1c): whether Finder passes the real paths to the script or
temporary copies. If copies, the shortcut also passes the originals' paths (Get
Details of Files ▸ File Path, one per line) in a second argument block, or the
output goes to a fixed folder (`~/Pictures/JPEG XL/`) instead.

### 3.4. Installation (what the README will say)

1. Terminal, once:
   ```
   mkdir -p ~/.local/bin && curl -L -o ~/.local/bin/jxlbatch https://github.com/jsh9/photo-video-shortcuts/releases/latest/download/jxlbatch-macos && chmod +x ~/.local/bin/jxlbatch && ~/.local/bin/jxlbatch --selftest
   ```
   `curl` doesn't set the quarantine attribute, so Gatekeeper never sees the
   download; a browser download would need `xattr -d com.apple.quarantine`. The
   binary is ad-hoc signed (the linker does this on arm64), which macOS
   requires to run it at all. No notarization is needed for a CLI tool
   installed this way; the README states this and the browser-download fix.
   Requirements stated in the README: a Mac with Apple silicon and macOS 14
   (Sonoma) or later, which is when Photos and ImageIO started reading JPEG XL.
   Intel Macs aren't supported (decision 5).
2. Download `compress-photos-mac-shortcuts-v<version>.zip` from Releases,
   double-click each `.shortcut`, Add Shortcut.
3. Shortcuts ▸ Settings ▸ Advanced ▸ **Allow Running Scripts** (required for
   Run Shell Script and Run AppleScript; without it the action fails with a
   clear message).
4. First run: allow Photos access; for the Share menu, enable the Shortcuts
   extension (System Settings ▸ General ▸ Login Items & Extensions ▸ Sharing)
   and turn on *Show in Share Sheet* in the shortcut's details if the import
   didn't keep it.

Optional later (section 6, phase 5): the shortcut offers to download the
encoder itself when it's missing or older than the shortcut.

## 4. Technical design

### 4.1. Encoder: `jxlbatch-macos`

- Same sources (`src/*.c`, `src/xmp.cpp`, `third_party/`), compiled with
  `-DJXLBATCH_THREADS -DJXLBATCH_VERSION=<VERSION>` like `build-native.sh`, but
  linked **statically** against libraries built from `.deps/`: libjxl v0.11.2
  (with highway and brotli from its `third_party/`, skcms as the color engine
  with the same `cicp`-before-`A2B0` patch as the WebAssembly build, so Apple's
  HDR profile is read the same way as on the phone), libheif v1.23.5 and
  libde265 v1.1.3 with the same feature flags as `build-wasm.sh`. The result
  depends only on `libc++` and `libSystem`.
- `build-wasm.sh` patches `.deps/libjxl` *in place* to drop threads. The Mac
  build must not inherit that: it uses its own clone, `.deps/libjxl-native`
  (same tag), and applies only the skcms patch. To avoid duplicating the patch
  code, the Python patch block in `build-wasm.sh` moves to
  `scripts/patch_deps.py` with flags (`--wasi`, `--skcms`), called by both
  build scripts.
- **arm64 only** (decided): one architecture, no `lipo`, no Rosetta testing.
  Deployment target `-mmacosx-version-min=14.0`: Photos and ImageIO read JPEG
  XL from macOS 14 (Sonoma) on. The build script refuses to run on an x86_64
  host rather than silently producing the wrong slice. A universal build can be
  added later without changing anything else.
- Output file: `shortcuts/compress-photos/dist/jxlbatch-macos` (no extension;
  `release.json` and `release.py` currently require `.wasm`, see 4.7). The name
  carries no architecture suffix on purpose: if a universal build comes later,
  the README's "latest" download link keeps working.
- `codesign -s - --force` after linking, so the binary carries an ad-hoc
  signature whatever the linker did. `--selftest` already covers HEIF, HDR, the
  profile and a 12 MP encode, which is the install check.
- Small encoder changes, all optional:
  - `term_width()` falls back to 40 columns when `COLUMNS` is unset (a-Shell
    sets it). The Mac script exports `COLUMNS=100`; no code change needed. If
    preferred, default to 80 when `stdout` is not a tty.
  - The "Photos sent this iPhone photo as JPEG… Send As ▸ Current" note is iOS
    wording. Decide after spike S5 whether the Mac share menu can send JPEG at
    all; if so, add `--hint mac` (or `JXLBATCH_PLATFORM=mac`) that changes that
    one sentence. Everything else in the output is platform-neutral.
- Determinism: libjxl's encoder output doesn't depend on the thread count, so
  the Mac binary should produce byte-identical JXL files to `jxlbatch.wasm` for
  the same input and settings. A test asserts this (4.8); if it ever fails, the
  test documents the difference instead.

### 4.2. The script core (`Run Shell Script`)

One zsh script, generated by `build_mac_shortcuts.py` from a template string so
both shortcuts share it (parameter: `OUTPUT=photos` or `OUTPUT=beside`). Shape:

```zsh
set -u
QUALITY='￼'          # the chosen quality, interpolated like the a-Shell command
OUTPUT=photos        # or beside
SHORTCUT_VERSION='0.4.0'
JXLBATCH=${JXLBATCH:-$HOME/bin/jxlbatch}
[ -x "$JXLBATCH" ] || { echo "ERROR: jxlbatch not found at $JXLBATCH. Install: <README link>"; exit 3; }
"$JXLBATCH" --version | grep -q " $SHORTCUT_VERSION " || echo "! encoder version differs from the shortcut's; see <README link>" >&2
WORK=$(mktemp -d "${TMPDIR:-/tmp}/compress-photos.XXXXXX")
[ "$OUTPUT" = photos ] || trap 'rm -rf "$WORK"' EXIT
i=0
for f in "$@"; do                       # the photos, as files
  i=$((i + 1))
  ln -s "$f" "$WORK/jxl_in_$i.orig"     # jxlbatch open()s it; no copy
  printf '%d|%s\n' "$i" "${f:t:r}" >> "$WORK/jxl_job.txt"   # index|name without extension
done
export COLUMNS=100
"$JXLBATCH" -q "$QUALITY" -e 7 -C "$WORK" jxl_job.txt > "$WORK/jxl_log.txt" 2>&1
# OUTPUT=beside: rename jxl_out_N.jxl to <Name>.jxl next to the original (no overwrite)
echo "$WORK"
cat "$WORK/jxl_done.txt" 2>/dev/null
```

Notes:

- `-C "$WORK"` is already supported; the job file and `jxl_in_*` live there, so
  nothing is written into Shortcuts' or iCloud's folders.
- The job name is the file's base name without extension, which is what
  `clean_name` plus the `.jxl` suffix in `jxl_done.txt` expects (the iPhone
  passes Get Name, and the result is `IMG_1234.jxl`). Spike S1 checks what
  names Shortcuts gives the temporary files; if they are opaque
  (`IMG_1234-1A2B.HEIC` or a UUID), the shortcut passes the names (Get Name,
  one per line, in the same order) as a second block, as it does with the
  albums on iOS.
- For `OUTPUT=photos` the work folder survives the script so the shortcut can
  read the files; the shortcut's last action is a one-line Run Shell Script
  `rm -rf "<work>"`. For `OUTPUT=beside` the trap cleans up.
- Exit status: Run Shell Script fails the shortcut on a nonzero status, which
  is what we want for "encoder not found"; `jxlbatch` returns 1 when nothing
  converted, so the shortcut ends with the log on screen in that case.
- stdout is the protocol, stderr goes into the log; the `!` warning for a
  version mismatch is appended to the log too so Quick Look shows it.

### 4.3. Getting File items back into Shortcuts

Primary: Run AppleScript, inside the per-line Repeat:

```applescript
on run {input, parameters}
  return POSIX file "<work>/<file>"
end run
```

Apple documents the coercion of an AppleScript file to a Shortcuts file.
Fallbacks if spike S2 fails:

1. One Run AppleScript returning a list of all files (one process instead of
   N).
2. Get File with the *Shortcuts* service on a path inside
   `~/Library/Mobile Documents/iCloud~is~workflow~my~workflows/Documents/`
   (present on this Mac); the script writes the results there. Works, but the
   files sync to iCloud while they exist.
3. Import directly from the script with `osascript` into Photos
   (`import … into album …`); loses the Shortcuts-side album logic, needs the
   Automation permission, and Delete Photos still needs Shortcuts. Last resort.

### 4.4. Showing progress and the log

The user asked about the "built-in terminal". Run Shell Script *is* the system
shell; what it lacks is a window. The design:

- Notification before the batch ("Converting 12 photos… this may take a
  minute"), notification after.
- The full `jxlbatch` log is shown in Quick Look (Preview Document) when it
  contains a `!` warning, an `ERROR`, or a failed photo; otherwise only the
  notification. This keeps the HDR notes and the "originals kept" summary
  visible before the delete prompt, which the iPhone user reads in a-Shell.
- Optional, off by default (a `WATCH=1` line at the top of the script): open
  Terminal with `tail -f "$WORK/jxl_log.txt"` so a long batch can be watched. A
  Terminal window as the *runner* is not proposed: the shortcut would again
  have to poll for a done file, which is the complexity the Mac lets us drop.

### 4.5. Where the encoder lives, and versions

- `~/.local/bin/jxlbatch` (decided). macOS has no single standard per-user bin
  folder; `~/.local/bin` is the convention tools such as pipx and uv use today,
  it already exists on the author's Mac, and it's on the PATH that Run Shell
  Script's non-login zsh sees. The alternatives are weaker: `~/bin` is the
  older convention and usually doesn't exist, `/usr/local/bin` is owned by root
  (the install command would need `sudo`), `/opt/homebrew/bin` belongs to
  Homebrew, and `~/Library/Application Support/…` has a space in it, awkward in
  a one-line install command. The folder being hidden in Finder doesn't matter:
  the user never browses it, and the script uses the full path.
- The script looks in `~/.local/bin`, then `~/bin`, `/usr/local/bin` and
  `/opt/homebrew/bin`, and a `JXLBATCH=` line at the top of the script
  overrides all of them.
- The script compares `jxlbatch --version` with the shortcut's version and adds
  a `!` line to the log when they differ (the iPhone can't do this easily; the
  Mac can). It still runs: the protocol is compatible across the versions
  published so far.
- Phase 5 (optional): when the encoder is missing or older, a Choose from Menu
  offers "Download jxlbatch <version> (about 5 MB, from GitHub)" and the script
  fetches it with `curl` to `~/.local/bin`. Everything else keeps working
  without it.

### 4.6. Permissions and macOS behaviors to document

- Shortcuts ▸ Settings ▸ Advanced ▸ Allow Running Scripts (one-time).
- Photos access for Shortcuts (first run).
- Sharing extension for the Share menu (System Settings).
- iCloud Photos with *Optimize Mac Storage*: Shortcuts downloads originals
  before passing them; large batches take longer and need a connection.
- Deleting from Shortcuts moves to Recently Deleted (30 days), after the system
  confirmation; same caveats as iOS (depth data, edit history, SDR version of
  HDR photos are not in the JXL).
- Photos may list the JXL copies under Duplicates (same as iOS).
- Edited photos: Shortcuts hands over the edited rendering, as on iOS.

### 4.7. Versioning, manifest and release

Decided: the Mac shortcuts live **in the same tool folder**,
`shortcuts/compress-photos/`, with the same `VERSION` as the iPhone shortcuts
and the encoder.

Why (the trade-off, for the record):

- Same folder, one version. For: a `jxlbatch` fix is one bump, one changelog
  entry and one tag for both platforms, and `jxlbatch --version` matches the
  shortcut's version everywhere, which the Mac script checks (4.5). The encoder
  source, the job protocol, the quality presets and the still-photo filter are
  already here, so nothing is imported across tool folders. The README already
  models Compress Photos as one tool with an iPhone and a Mac column, and one
  `release.py compress-photos` run publishes everything. Against:
  `release.json` needs per-platform shortcut lists and a second ZIP, so
  `release.py` and its tests change (once). A Mac-only change bumps the version
  iPhone users see too; the changelog already says which files to update, as it
  does for shortcut-only releases today. Every release builds both encoders,
  and this folder's README grows (a `README-mac.md` split keeps it readable).
- Separate `shortcuts/compress-photos-mac/` tool. For: no `release.py` schema
  change, its own tag, ZIP, README and changelog entries, an independent
  cadence. Against: one encoder source built with two version strings, so a
  `jxlbatch` fix needs two bumps and two changelog entries and the two binaries
  report different versions for identical code; the shared plist builder,
  presets and filter still have to be imported from another tool's folder or
  moved to a third place; the README's single Compress Photos row splits in
  two, and Compress Videos inherits the precedent.

The release-tooling change is a one-time cost; the two-version encoder would be
a permanent source of confusion.

Changes:

- `release.json`:
  ```json
  {
    "encoders": ["jxlbatch.wasm", "jxlbatch-scalar.wasm", "jxlbatch-macos"],
    "shortcuts": {
      "iphone": ["Compress Photos.shortcut", "JXL-Import.shortcut"],
      "mac": ["Compress Photos (macOS).shortcut", "Compress Photo Files (macOS).shortcut"]
    }
  }
  ```
  A plain list keeps meaning `iphone`, so Compress Videos' future manifest can
  stay simple.
- `release.py`: encoder names may end in `.wasm` or have no extension; the
  version check runs `wasmtime run` for `.wasm` and executes the file directly
  otherwise (the script already runs on a Mac). One ZIP per platform:
  `compress-photos-shortcuts-v<v>.zip` (iPhone, name unchanged so existing
  links keep working) and `compress-photos-mac-shortcuts-v<v>.zip`. `build()`
  also runs `build-macos.sh` when present. `verify_zip`/`make_zip` take the
  platform's list. Tests in `tests/scripts/test_release.py` follow.
- `CHANGELOG.md`: one entry, `Compress Photos 0.4.0`, saying which files to
  update per platform.
- CI (`macos-latest`, arm64): add `build-macos.sh`; cache its static library
  builds under `.deps/` (key on `build-macos.sh` and `patch_deps.py`). The dry
  run then checks the Mac encoder's `--version` and the second ZIP.

### 4.8. Code layout

- `scripts/wf.py` (new): the generic Shortcuts plist builder lifted out of
  `build_shortcuts.py`: `Ref`, `text()`, `Builder` and its actions,
  `QUALITY_PRESETS`, `choose_quality`, `keep_still_photos`, `workflow()`,
  `write()`. `build_shortcuts.py` imports it and keeps the a-Shell parts and
  the two iPhone shortcuts; its output must stay byte-for-byte the same (the
  existing tests check the generated actions).
- `scripts/build_mac_shortcuts.py` (new): the two Mac shortcuts. New `Builder`
  methods: `run_shell_script(script_parts, input_ref, as_arguments=True)`,
  `run_applescript(...)`, `quick_look(ref)`, `show_result(...)`,
  `get_folder_contents(...)`, `file_details(...)`. The exact parameter keys of
  Run Shell Script (`Script`, `Shell`, `Input`, `InputMode` = "as
  arguments"/"to stdin", per public shortcut files and the `InputMode` string
  in the cache) are confirmed by spike S8 the same way the a-Shell actions
  were: build one by hand, `--fetch` it from an iCloud link into
  `scripts/sample/`, and copy the format. Workflow keys for the Mac surfaces:
  `WFWorkflowTypes` with `ActionExtension` (Share menu) and `QuickActions`,
  `WFQuickActionSurfaces` (`Finder`, `Services`, `MenuBar`),
  `WFWorkflowInputContentItemClasses` (`WFImageContentItem`, plus
  `WFGenericFileContentItem`/folders for the Finder shortcut).
- `scripts/build-macos.sh` (new) and `scripts/patch_deps.py` (new, from
  `build-wasm.sh`).
- `build-native.sh` stays as the fast Homebrew build for tests.
- Docs: `README.md` (table: Mac → Yes; section 1.2 install), a Mac section in
  `shortcuts/compress-photos/README.md` (or `README-mac.md` if it grows),
  `DEVELOPING.md` (how it works on the Mac, building, the sample-fetch step),
  `docs/how-it-works.md` gets the Mac paragraph.

### 4.9. Tests

- `test_shortcuts.py`: the Mac workflows parse, have the expected surfaces, the
  quality list, the still-photo filter, and the script text contains the
  quality variable and `-e 7`.
- `test_mac_script.py` (new): the strongest new test. Extract the zsh script
  from the generated plist, substitute the quality, run it for real with
  `/bin/zsh` on the fixture photos, with `JXLBATCH` pointing at
  `build/jxlbatch` (fast) and, when it exists, `dist/jxlbatch-macos`. Check the
  printed `jxl_done.txt` lines, the output names, the `beside` renaming with a
  collision, cleanup, exit codes, "encoder not found". This replaces the
  a-Shell model for the Mac.
- `test_conversion.py` and friends: parametrize the encoder over
  `dist/jxlbatch-macos` too, so the release binary passes the ImageIO checks
  (today only the Homebrew build and the WebAssembly builds do).
- Determinism: same input and settings → identical bytes from `jxlbatch.wasm`
  and `jxlbatch-macos` (skipped when either is missing).
- `test_shortcuts_e2e_mac.py` (local only, skipped unless the shortcut is
  imported):
  `shortcuts run "Compress Photo Files (macOS)" --input-path testdata/dark.heic`
  and check the `.jxl` appears; the unified log
  (`/usr/bin/log show --predicate 'process == "BackgroundShortcutRunner"'`)
  shows which actions ran, as used for 0.3.1.
- `tests/scripts/test_release.py`: manifest with per-platform lists, two ZIPs,
  the non-`.wasm` encoder version check.

## 5. Spikes to run first (one throwaway shortcut, about an hour)

Each is checked on this Mac with a hand-built shortcut (importing needs one
click in Shortcuts; then `shortcuts run` and the unified log do the rest).

| #   | Question                                                                                                                              | Pass                                                                         | If it fails                                                                 |
| --- | ------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| S1  | Run Shell Script, photos as arguments: what paths and names does `"$@"` get for (a) picker photos, (b) Photos share menu, (c) Finder? | real or temp paths that `open()` can read; names derived from the original's | pass Get Name per line as a second block (4.2); Finder: fixed output folder |
| S2  | Run AppleScript `return POSIX file` → Save to Photo Album with a `.jxl`                                                               | the JXL appears in Photos with its name and metadata                         | fallbacks in 4.3                                                            |
| S3  | Get Details of Images ▸ Album on the Mac, for picker and share-menu items                                                             | album names as on iOS                                                        | albums only from the picker path; README says so                            |
| S4  | Delete Photos on the Mac                                                                                                              | system confirmation, originals in Recently Deleted                           | drop deletion on the Mac; README says so                                    |
| S5  | What Photos' Share menu hands over: HEIC or JPEG? Live Photos and videos detectable with Media Type / Photo Type?                     | HEIC, and the filter sorts as on iOS                                         | README: use the picker for originals; adjust the encoder hint (4.1)         |
| S6  | Static arm64 `jxlbatch-macos` builds from `.deps` and `--selftest` passes; `otool -L` shows only `libc++` and `libSystem`             | passes, no Homebrew paths in `otool -L`                                      | fix the static link flags; as a stopgap, lcms2 instead of patched skcms     |
| S7  | A `curl`-downloaded binary runs from Run Shell Script without a Gatekeeper prompt; a browser download shows the quarantine dialog     | as expected                                                                  | document `xattr -d`; consider notarization later                            |
| S8  | Exact plist keys of Run Shell Script and Run AppleScript on this macOS (`--fetch` of a hand-built sample)                             | sample saved under `scripts/sample/`, keys match the hand-written templates  | templates corrected from the sample                                         |
| S9  | `shortcuts run … --input-path` drives the file shortcut end to end                                                                    | `.jxl` written, log shows the actions                                        | e2e test stays manual                                                       |
| S10 | Byte-identical output: `jxlbatch.wasm` vs `jxlbatch-macos` on the HDR and SDR fixtures                                                | identical                                                                    | document the difference; test compares decoded pixels instead               |

## 6. Implementation phases

1. **Encoder** (no user-visible change yet): `patch_deps.py`, `build-macos.sh`
   (static, arm64, `codesign`), `release.json` schema and `release.py` encoder
   rules, CI step and cache, tests parametrized over the new binary,
   determinism test. Dry run publishes nothing.
2. **Spikes S1–S5, S8** with a hand-built shortcut; record the findings in
   `DEVELOPING.md`.
3. **Compress Photos (macOS)**: `wf.py` split (iPhone output unchanged, test
   asserts it), `build_mac_shortcuts.py`, the script core, Run Shell Script /
   Run AppleScript / Quick Look builder methods, `test_mac_script.py`,
   `test_shortcuts.py` additions. Manual check on this Mac from the Share menu
   and from the picker, with HDR photos, a Live Photo and a video in the
   selection.
4. **Compress Photo Files (macOS)**: Finder Quick Action, folder expansion,
   `beside` output with collision handling, its tests.
5. **Docs and release 0.4.0**: README table and install steps, the Mac
   sections, `docs/how-it-works.md`, changelog, `release.py compress-photos`.
6. **Optional follow-ups**: encoder auto-download, `WATCH=1` Terminal tail,
   `--hint mac` encoder wording, a "Pin in Menu Bar" note in the README.

Estimated size: the encoder build script and release changes are the largest
piece (the static multi-arch build and its CI caching); the shortcuts
themselves reuse most of `build_shortcuts.py`.

## 7. Decisions taken (2026-10-04)

1. **Names**: *Compress Photos (macOS)* and *Compress Photo Files (macOS)*.
2. **Two shortcuts**: the Photos one is the core; the Finder one is a small
   add-on sharing the script core, with a different output policy (files, not
   Photos).
3. **Deletion**: Compress Photos (macOS) offers to delete the originals from
   both entry points, Share menu and picker, with the iOS `delete`/`keep`
   rules. Compress Photo Files (macOS) never deletes anything.
4. **Same tool folder and version** as the iPhone shortcuts (4.7).
5. **arm64 only**, macOS 14 or later. The release file stays `jxlbatch-macos`,
   without an architecture suffix, so a later universal build keeps the link.
6. **Encoder location**: `~/.local/bin/jxlbatch`, with `~/bin`,
   `/usr/local/bin` and `/opt/homebrew/bin` as fallbacks (4.5).

Still open:

7. **Auto-download of the encoder** in the shortcut: phase 6 or never.

## 8. Risks

- Run Shell Script writes the photos to temporary files first; for a large
  batch of 48 MP HEICs that is a copy per photo (fast on an SSD; nothing like
  the a-Shell transfer cost).
- Share-menu input on the Mac may be converted (S5), as the iPhone's Send As
  does; the picker path is the known-good original path on both platforms.
- The static build pins libjxl 0.11.2 like the phone, while `build-native.sh`
  tests against Homebrew's 0.12.0; the new tests cover the release binary
  directly, so the two can't drift unnoticed.
- CI time: the static libraries take minutes to build on `macos-latest`; cached
  by script hash, as `.deps` is today.
- Intel Macs are left out (decision 5). macOS 14 still runs on 2019–2020 Intel
  models, so the README says "Apple silicon" plainly; a universal build can be
  added later under the same file name.

Sources:
[Run shortcuts from the Share menu on Mac](https://support.apple.com/guide/shortcuts-mac/apd163eb9f95/mac),
[Run shortcuts from the command line](https://support.apple.com/guide/shortcuts-mac/apd455c82f02/mac),
[Running AppleScripts in Shortcuts (quotes Apple's coercion rules)](https://www.macscripter.net/t/running-applescripts-in-shortcuts/78092),
[Can't run Shortcuts scripts on macOS (Allow Running Scripts)](https://developer.apple.com/forums/thread/689436).
