# Compress Photos: developer notes

How the shortcut and its encoder, `jxlbatch`, work, and how to build them. For
installing and using it, see [README.md](README.md).

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. How it works](#1-how-it-works)
- [2. Layout](#2-layout)
- [3. Building (Mac)](#3-building-mac)
- [4. Generating the shortcuts](#4-generating-the-shortcuts)
- [5. Building the shortcuts by hand (fallback)](#5-building-the-shortcuts-by-hand-fallback)

______________________________________________________________________

<!--TOC-->

## 1. How it works

```
Compress Photos                              (shortcut)
   photos: from the share sheet, or else picked in its own photo picker
   asks for a quality preset, copies each original photo to a-Shell's shared
   folder as jxl_in_N.orig, writes jxl_job.txt, then runs in a-Shell:
     jxlbatch -q 83 -e 7 jxl_job.txt   (after a short wait; retried if
                                        a-Shell was still starting up)
a-Shell ▸ jxlbatch → jxl_out_N.jxl + jxl_done.txt, with progress on screen
then, from the share sheet:
   a-Shell starts JXL-Import (shortcut), which saves each JXL to Photos
   under its original name, adds it to the albums listed in
   jxl_albums_N.txt (written by Compress Photos), and cleans up
or, from the picker:
   a-Shell switches back to Compress Photos, which saves the JXLs,
   adds each to its original's albums, then asks to delete the
   originals whose JXL was saved
```

`jxlbatch` decodes the original itself (HEIF with libheif and libde265; JPEG
and PNG with stb_image) and encodes with libjxl 0.11.2.

`jxlbatch` copies the original's EXIF byte for byte into an uncompressed `Exif`
box, and XMP into an `xml ` box. Apple's image framework reads those boxes;
compressed (`brob`) boxes, which `cjxl` writes by default, it can't. Pixels are
stored upright, and the EXIF/XMP orientation is reset to match, so no viewer
can rotate a photo twice. 10-bit HEIF photos are kept at 10 bits.

Encoding settings match `cjxl -q Q -e E`, with one difference: libjxl's
streaming mode is always on, and the image is handed to it in chunks rather
than copied. That keeps a 24 MP photo at about 0.5 GB and a 48 MP one at about
0.7 GB, at any quality. By default, libjxl at effort 7 turns streaming off
below quality ~70 and holds the whole image, which takes about 2.7 GB for 24
MP, more than iOS lets a-Shell use. The cost is files about 2.5% larger at
those qualities, with the same visual quality (SSIMULACRA2).

## 2. Layout

| Path                         | What it is                                                                                                                                                                                                         |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `VERSION`                    | the version, shared by the shortcuts and `jxlbatch`; read by the build scripts                                                                                                                                     |
| `src/`                       | `jxlbatch`: `jxlbatch.c` (batch, encoding), `meta.c` (EXIF/XMP/ICC from HEIF, JPEG and PNG), `pixels.c` (decoded images, orientation), `heif.c` (libheif decoding), `selftest_heic.h` (tiny HEIC for `--selftest`) |
| `third_party/`               | `stb_image.h` (JPEG and PNG decoding)                                                                                                                                                                              |
| `scripts/build-wasm.sh`      | builds `dist/jxlbatch.wasm` and `dist/jxlbatch-scalar.wasm` for a-Shell                                                                                                                                            |
| `scripts/build-native.sh`    | builds `build/jxlbatch` for the Mac, against Homebrew's libjxl and libheif (fast tests)                                                                                                                            |
| `scripts/build_shortcuts.py` | generates and signs the two `.shortcut` files into `dist/`                                                                                                                                                         |

`build/` and `dist/` are not committed. Release files are published on
[GitHub Releases](https://github.com/jsh9/photo-video-shortcuts/releases).

## 3. Building (Mac)

Run these from this folder (`shortcuts/compress-photos`):

```bash
./scripts/build-native.sh
./scripts/build-wasm.sh
python3 scripts/build_shortcuts.py --guess
```

- **Prerequisites:** Homebrew `jpeg-xl libheif cmake ninja binaryen`.
- **What `build-wasm.sh` does:** it downloads wasi-sdk 34, libjxl v0.11.2,
  libheif v1.23.5 and libde265 v1.1.3 into the repository's `.deps/` folder,
  shared with the other tools. WASI has no threads, C++ exceptions or
  `mkstemp`, so it applies small edits:
  - libjxl: drops its threads dependency, the same edit as
    [gen2brain/jpegxl](https://github.com/gen2brain/jpegxl).
  - libheif: decodes on the calling thread, keeping HEVC deblocking and SAO;
    skips its exception wrapper and its temporary files (only used when writing
    HEIF).
- **`jxlbatch --selftest`** checks file access, large-file I/O, HEIF decoding
  (a tiny built-in HEIC) and a 12 MP encode. Running it in a-Shell checks the
  phone.
- **Tests** will live in [`tests/compress-photos/`](../../tests/README.md) (not
  added yet).

## 4. Generating the shortcuts

- `scripts/build_shortcuts.py` writes and signs the two `.shortcut` files into
  `dist/`. Signing uses macOS's `shortcuts sign`, so it runs on a Mac signed in
  to an Apple ID.
- `--guess` uses hand-written templates. a-Shell's actions are written as
  `AsheKube.app.a-Shell.<Intent>` with its parameter names from a-Shell's
  `Intents.intentdefinition`.
- If those don't import correctly, build a sample shortcut by hand on the
  iPhone. `build_shortcuts.py --fetch <iCloud link>` saves it as
  `scripts/sample/JXL Sample.plist`, and later runs copy the exact format from
  it.
- The quality presets are `QUALITY_PRESETS` near the top of the script.
- Releases are built and published by `scripts/release.py` at the repository
  root. They ship the two `.shortcut` files in one ZIP,
  `compress-photos-shortcuts-v<version>.zip`; see
  [docs/releasing.md](../../docs/releasing.md).

## 5. Building the shortcuts by hand (fallback)

Use this if the `.shortcut` files won't import. The a-Shell actions are under
Apps ▸ a-Shell. Turn on each action's toggles as listed.

**JXL-Import** (build this first; no share sheet):

1. a-Shell **Get File**: `jxl_done.txt`, Error If Not Found on.
2. **Get Text from Input**: File.
3. **Split Text**: Text, by New Lines.
4. **Repeat with Each** item in Split Text:
   1. **Split Text**: Repeat Item, by Custom `|`.
   2. **Get Item from List**: First Item of Split Text.
   3. **Get Item from List**: Last Item of Split Text (the one from step 4.1).
   4. a-Shell **Get File**: the First Item, Error If Not Found on.
   5. **Set Name**: File to Last Item, with Don't Include File Extension on.
   6. **Save to Photo Album**: Renamed Item, to Recents.
   7. **Get Item from List**: Item At Index 2 of the `|` split (the photo's
      position).
   8. a-Shell **Get File**: `jxl_albums_<Item from List>.txt`, Error If Not
      Found **off**.
   9. **If** File has any value:
      1. **Get Text from Input**: File, then **Split Text** by New Lines.
      2. **Repeat with Each** item in Split Text: **Save to Photo Album**:
         Saved Photo Media, to Repeat Item 2.
      3. **End If** (Otherwise stays empty).
5. **Count**: Items in the Split Text from step 3.
6. a-Shell **Execute Command**:
   `rm -f jxl_in_* jxl_out_* jxl_albums_* jxl_job.txt jxl_done.txt jxl_started`,
   Keep Going on.
7. **Show Notification**: `Saved <Count> photo(s) to Photos.`

**Compress Photos** (Details: Show in Share Sheet, receives Images; if there's
no input: Continue):

1. **If** Shortcut Input has any value:
   - **Set Variable** `Photos` to Shortcut Input.
   - **Otherwise:** **Select Photos** (Select Multiple on), then **Set
     Variable** `Photos` to Photos.
   - **End If**.
2. The quality list:
   1. **Text**: one contact card per preset, one after another:
      ```
      BEGIN:VCARD
      VERSION:3.0
      N;CHARSET=utf-8:83 (default)
      ORG;CHARSET=utf-8:Go-to option for everyday scenes (almost perfect blue sky)\; film grains well preserved
      END:VCARD
      ```
      Put a backslash before any `;` in the description.
   2. **Set Name**: Text to `quality.vcf`, Don't Include File Extension on.
   3. **Get Contacts from Input**: Renamed Item.
   4. **Choose from List**: Contacts, prompt `JPEG XL quality`.
   5. **Get Name** of Chosen Item.
   6. **Match Text**: `\d+` in Name. Its Matches is the quality.
3. a-Shell **Execute Command**:
   `rm -f jxl_done.txt jxl_out_* jxl_albums_* jxl_started`, Keep Going on.
4. **Repeat with Each** item in `Photos`:
   1. **Get Name** of Repeat Item.
   2. **Set Name**: Repeat Item to `jxl_in_<Repeat Index>.orig`, Don't Include
      File Extension on.
   3. a-Shell **Put File**: Renamed Item, Overwrite on.
   4. **Text**: `<Repeat Index>|<Name>`.
   5. **Add to Variable**: Text to `Jobs`.
5. **Combine Text**: `Jobs` with New Lines.
6. **Set Name**: Combined Text to `jxl_job.txt`, Don't Include File Extension
   on.
7. a-Shell **Put File**: Renamed Item, Overwrite on.
8. **If** Shortcut Input has any value:
   1. **Repeat with Each** item in `Photos`:
      1. **Get Details of Images**: Album of Repeat Item.
      2. **If** Album has any value: **Combine Text** Album with New Lines,
         **Set Name** to `jxl_albums_<Repeat Index>.txt` (Don't Include File
         Extension on), a-Shell **Put File** (Overwrite on). **End If**.
   2. a-Shell **Execute Command**, Keep Going off, with these commands:
      - `sleep 2`
      - `jxlbatch -q <Matches> -e 7 jxl_job.txt`
      - `dash -c '[ -e jxl_started ] || { sleep 3; jxlbatch -q <Matches> -e 7 jxl_job.txt; }'`
      - `open shortcuts://run-shortcut?name=JXL-Import`
   - **Otherwise:**
     1. The same **Execute Command**, but with `open shortcuts://` as the last
        command.
     2. **Wait to Return**.
     3. Steps 1–5 of JXL-Import, but inside the repeat, replace steps 4.8–4.9
        with:
        1. **Get Item from List**: that item of `Photos` (the original).
        2. **Add to Variable** `Converted`.
        3. **Get Details of Images**: Album of that original.
        4. **Repeat with Each** item in Album: **Save to Photo Album**: Saved
           Photo Media, to Repeat Item 2.
     4. Steps 6–7 of JXL-Import.
     5. **Delete Photos**: `Converted`.
   - **End If**.

The wait and the retry cover a-Shell being launched by the shortcut. Its
WebAssembly engine is still loading then, and a-Shell ends the first command
before it runs. `jxlbatch` creates `jxl_started` when it runs, so the retry
only happens if it didn't.
