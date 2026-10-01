# Third-party licenses

The release files contain these libraries, built from source by each shortcut's
`scripts/build-wasm.sh` (TinyXML2 is vendored alongside the photo encoder).
Their full license texts will be added to this folder before the first release.

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. `jxlbatch.wasm` (Compress Photos)](#1-jxlbatchwasm-compress-photos)
- [2. `vidbatch.wasm` (Compress Videos)](#2-vidbatchwasm-compress-videos)

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

## 2. `vidbatch.wasm` (Compress Videos)

To be added with Compress Videos.
