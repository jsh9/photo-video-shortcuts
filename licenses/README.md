# Third-party licenses

The release files contain these libraries, built from source by each
shortcut's `scripts/build-wasm.sh`. Their full license texts will be added to
this folder before the first release.

## `jxlbatch.wasm` (Compress Photos)

| Library | Version | License |
|---|---|---|
| [libjxl](https://github.com/libjxl/libjxl) | 0.11.2 | BSD-3-Clause |
| [Brotli](https://github.com/google/brotli) (bundled with libjxl) | libjxl 0.11.2's copy | MIT |
| [Highway](https://github.com/google/highway) (bundled with libjxl) | libjxl 0.11.2's copy | Apache-2.0 or BSD-3-Clause |
| [skcms](https://skia.googlesource.com/skcms) (bundled with libjxl) | libjxl 0.11.2's copy | BSD-3-Clause |
| [libheif](https://github.com/strukturag/libheif) | 1.23.5 | LGPL-3.0 |
| [libde265](https://github.com/strukturag/libde265) | 1.1.3 | LGPL-3.0 |
| [stb_image](https://github.com/nothings/stb) | 2.30 | MIT or public domain |
| [wasi-sdk](https://github.com/WebAssembly/wasi-sdk) runtime (wasi-libc, libc++) | 34 | Apache-2.0 WITH LLVM-exception, and others |

## `vidbatch.wasm` (Compress Videos)

To be added with Compress Videos.
