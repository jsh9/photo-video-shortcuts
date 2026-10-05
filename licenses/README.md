# Third-party licenses

The release files contain these libraries, built from source by each shortcut's
`scripts/build-wasm.sh` or `scripts/build-macos.sh` (TinyXML2 is vendored
alongside the photo encoder). Their full license texts will be added to this
folder before the first release.

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. `jxlbatch.wasm` (Compress Photos)](#1-jxlbatchwasm-compress-photos)
- [2. `ffmpeg-macos` and `ffprobe-macos` (Compress Videos)](#2-ffmpeg-macos-and-ffprobe-macos-compress-videos)

______________________________________________________________________

<!--TOC-->

## 1. `jxlbatch.wasm` (Compress Photos)

| Library                                                                         | Version              | License                                                                              |
| ------------------------------------------------------------------------------- | -------------------- | ------------------------------------------------------------------------------------ |
| [libjxl](https://github.com/libjxl/libjxl)                                      | 0.11.2               | BSD-3-Clause                                                                         |
| [Brotli](https://github.com/google/brotli) (bundled with libjxl)                | libjxl 0.11.2's copy | MIT                                                                                  |
| [Highway](https://github.com/google/highway) (bundled with libjxl)              | libjxl 0.11.2's copy | Apache-2.0 or BSD-3-Clause                                                           |
| [skcms](https://skia.googlesource.com/skcms) (bundled with libjxl)              | libjxl 0.11.2's copy | BSD-3-Clause                                                                         |
| [libheif](https://github.com/strukturag/libheif)                                | 1.23.5               | LGPL-3.0                                                                             |
| [libde265](https://github.com/strukturag/libde265)                              | 1.1.3                | LGPL-3.0                                                                             |
| [TinyXML2](https://github.com/leethomason/tinyxml2/releases/tag/11.0.0)         | 11.0.0               | zlib ([full license](../shortcuts/compress-photos/third_party/tinyxml2/LICENSE.txt)) |
| [stb_image](https://github.com/nothings/stb)                                    | 2.30                 | MIT or public domain                                                                 |
| [wasi-sdk](https://github.com/WebAssembly/wasi-sdk) runtime (wasi-libc, libc++) | 34                   | Apache-2.0 WITH LLVM-exception, and others                                           |

## 2. `ffmpeg-macos` and `ffprobe-macos` (Compress Videos)

Built by `shortcuts/compress-videos/scripts/build-macos.sh`. With x265 in it,
the build is licensed under the GPL, as this repository is. `vidmeta-macos`
contains no third-party code.

| Library                                            | Version | License                                                                |
| -------------------------------------------------- | ------- | ---------------------------------------------------------------------- |
| [FFmpeg](https://ffmpeg.org)                       | 9.0.2   | GPL-2.0-or-later (LGPL-2.1-or-later, built with `--enable-gpl`)        |
| [x265](https://github.com/Multicorewareinc/x265)   | 4.3     | GPL-2.0-or-later                                                       |
| [SVT-AV1](https://gitlab.com/AOMediaCodec/SVT-AV1) | 4.2.0   | BSD-3-Clause-Clear, and the Alliance for Open Media Patent License 1.0 |
| [libopus](https://opus-codec.org)                  | 1.6.1   | BSD-3-Clause                                                           |
