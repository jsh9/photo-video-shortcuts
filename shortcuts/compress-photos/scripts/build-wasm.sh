#!/bin/sh
# Builds jxlbatch as a WASI WebAssembly command for a-Shell.
#
# Outputs:
#   dist/jxlbatch.wasm         WebAssembly SIMD build (iOS 16.4+)
#   dist/jxlbatch-scalar.wasm  fallback without SIMD
#
# Needs: Homebrew cmake, ninja, binaryen (wasm-opt). Downloads wasi-sdk,
# libjxl, libheif and libde265 into the repository's .deps/ on first run
# (shared with the other tools' build scripts).
set -eu
cd "$(dirname "$0")/.."
ROOT=$(pwd)
REPO=$(cd ../.. && pwd)
VERSION=$(cat VERSION)  # shared by the encoder and the shortcuts

WASI_SDK_VERSION=34
LIBJXL_VERSION=v0.11.2
LIBHEIF_VERSION=v1.23.5
LIBDE265_VERSION=v1.1.3
DEPS="$REPO/.deps"
WASI_SDK="$DEPS/wasi-sdk-$WASI_SDK_VERSION.0-arm64-macos"
LIBJXL="$DEPS/libjxl"
LIBHEIF="$DEPS/libheif"
LIBDE265="$DEPS/libde265"

mkdir -p "$DEPS" "$ROOT/dist" "$ROOT/build"

if [ ! -x "$WASI_SDK/bin/clang" ]; then
  echo "Downloading wasi-sdk $WASI_SDK_VERSION..."
  curl -sSfL -o "$DEPS/wasi-sdk.tar.gz" \
    "https://github.com/WebAssembly/wasi-sdk/releases/download/wasi-sdk-$WASI_SDK_VERSION/wasi-sdk-$WASI_SDK_VERSION.0-arm64-macos.tar.gz"
  tar xzf "$DEPS/wasi-sdk.tar.gz" -C "$DEPS"
  rm "$DEPS/wasi-sdk.tar.gz"
fi

if [ ! -d "$LIBJXL/.git" ]; then
  echo "Cloning libjxl $LIBJXL_VERSION..."
  git clone -q --depth 1 -b "$LIBJXL_VERSION" https://github.com/libjxl/libjxl "$LIBJXL"
  git -C "$LIBJXL" submodule update -q --init --depth 1 \
    third_party/brotli third_party/highway third_party/skcms
fi
if [ ! -d "$LIBHEIF/.git" ]; then
  echo "Cloning libheif $LIBHEIF_VERSION..."
  git clone -q --depth 1 -b "$LIBHEIF_VERSION" https://github.com/strukturag/libheif "$LIBHEIF"
fi
if [ ! -d "$LIBDE265/.git" ]; then
  echo "Cloning libde265 $LIBDE265_VERSION..."
  git clone -q --depth 1 -b "$LIBDE265_VERSION" https://github.com/strukturag/libde265 "$LIBDE265"
fi

# WASI (the non-threads target) has no threads, no C++ exceptions and no
# mkstemp. These edits make the libraries build and decode single-threaded.
python3 - "$LIBJXL" "$LIBHEIF" <<'EOF'
import pathlib, sys
libjxl, libheif = map(pathlib.Path, sys.argv[1:])

# libjxl: drop the hard pthreads dependency (as gen2brain/jpegxl does).
for rel, lines in {
    "CMakeLists.txt": ["set(THREADS_PREFER_PTHREAD_FLAG YES)", "find_package(Threads REQUIRED)"],
    "lib/CMakeLists.txt": ["include(jxl_threads.cmake)"],
    "lib/jxl.cmake": ["  Threads::Threads"],
    "lib/jpegli.cmake": ["  Threads::Threads"],
}.items():
    path = libjxl / rel
    text = path.read_text()
    new = "\n".join(l for l in text.split("\n") if l.rstrip() not in lines)
    if new != text:
        path.write_text(new)
        print(f"patched libjxl/{rel}")

def replace(rel, old, new):
    path = libheif / rel
    text = path.read_text()
    if new in text:
        return
    if old not in text:
        sys.exit(f"libheif/{rel}: expected code not found; check the patch for this version")
    path.write_text(text.replace(old, new, 1))
    print(f"patched libheif/{rel}")

# libheif: temp files are only used when writing HEIF; WASI has no mkstemp.
replace("libheif/box.cc",
        '#if !defined(_WIN32)\n    strcpy(m_tmp_filename, "/tmp/libheif-XXXXXX");',
        '#if defined(__wasi__)\n    m_use_tmpfile = false;  // WASI has no mkstemp; only used when writing files\n'
        '#elif !defined(_WIN32)\n    strcpy(m_tmp_filename, "/tmp/libheif-XXXXXX");')
# libheif: without exceptions, run the API body directly (failures abort).
replace("libheif/api_structs.h",
        "static inline heif_error exception_guard(F&& body) noexcept\n{\n  try {",
        "static inline heif_error exception_guard(F&& body) noexcept\n{\n#if !defined(__cpp_exceptions)\n"
        "  return body();  // built with -fno-exceptions (WASI): failures abort instead\n#else\n  try {")
replace("libheif/api_structs.h",
        "  catch (...) {\n    return heif_error_internal_exception;\n  }\n}",
        "  catch (...) {\n    return heif_error_internal_exception;\n  }\n#endif\n}")
# libheif: file.cc includes, but doesn't use, the C++ wrapper, which throws.
replace("libheif/file.cc",
        '#include "libheif/heif_cxx.h"\n',
        '#if defined(__cpp_exceptions)  // unused here; its wrappers throw\n#include "libheif/heif_cxx.h"\n#endif\n')
# libheif: decode on the calling thread (libde265 supports 0 worker threads),
# keeping deblocking and SAO, unlike the Emscripten branch.
replace("libheif/plugins/decoder_libde265.cc",
        "#else\n  int nThreads = (options->num_threads ? options->num_threads : 1);",
        "#elif defined(__wasi__)\n  // WASI has no threads: libde265 decodes on the calling thread (0 workers),\n"
        "  // keeping deblocking and SAO (unlike the Emscripten branch above).\n#else\n"
        "  int nThreads = (options->num_threads ? options->num_threads : 1);")
EOF

build_variant() {
  variant=$1   # simd | scalar
  flags=$2
  out=$3
  bdir="$ROOT/build/wasm-$variant"
  prefix="$bdir-prefix"
  toolchain="-DCMAKE_TOOLCHAIN_FILE=$WASI_SDK/share/cmake/wasi-sdk-p1.cmake -DWASI_SDK_PREFIX=$WASI_SDK"
  echo "== $variant build =="

  # libde265 (HEVC decoder). Its SIMD code is x86/ARM-only; signal.h is
  # included but unused.
  # shellcheck disable=SC2086
  cmake -S "$LIBDE265" -B "$bdir-de265" -G Ninja -Wno-dev $toolchain \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_C_FLAGS="$flags -fno-exceptions -D_WASI_EMULATED_SIGNAL" \
    -DCMAKE_CXX_FLAGS="$flags -fno-exceptions -D_WASI_EMULATED_SIGNAL" \
    -DCMAKE_INSTALL_PREFIX="$prefix" \
    -DBUILD_SHARED_LIBS=OFF -DENABLE_SIMD=OFF -DENABLE_SDL=OFF -DENABLE_DECODER=OFF -DENABLE_ENCODER=OFF \
    >"$bdir-de265.log" 2>&1 || { tail -30 "$bdir-de265.log"; exit 1; }
  ninja -C "$bdir-de265" install >>"$bdir-de265.log" 2>&1 || { tail -30 "$bdir-de265.log"; exit 1; }

  # libheif: HEIF container + libde265, decoding only, no threads or plugins.
  # PKG_CONFIG_LIBDIR keeps it from finding Homebrew's (macOS) libraries.
  # shellcheck disable=SC2086
  PKG_CONFIG_LIBDIR="$prefix/lib/pkgconfig" PKG_CONFIG_PATH="" \
  cmake -S "$LIBHEIF" -B "$bdir-heif" -G Ninja -Wno-dev $toolchain \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_C_FLAGS="$flags -fno-exceptions" -DCMAKE_CXX_FLAGS="$flags -fno-exceptions" \
    -DCMAKE_INSTALL_PREFIX="$prefix" -DCMAKE_PREFIX_PATH="$prefix" -DCMAKE_FIND_ROOT_PATH="$prefix" \
    -DLIBDE265_INCLUDE_DIR="$prefix/include" -DLIBDE265_LIBRARY="$prefix/lib/libde265.a" \
    -DBUILD_SHARED_LIBS=OFF -DENABLE_PLUGIN_LOADING=OFF \
    -DENABLE_MULTITHREADING_SUPPORT=OFF -DENABLE_PARALLEL_TILE_DECODING=OFF \
    -DWITH_LIBDE265=ON -DWITH_LIBDE265_PLUGIN=OFF \
    -DWITH_X265=OFF -DWITH_KVAZAAR=OFF -DWITH_UVG266=OFF -DWITH_VVDEC=OFF -DWITH_VVENC=OFF \
    -DWITH_X264=OFF -DWITH_OpenH264_DECODER=OFF -DWITH_DAV1D=OFF -DWITH_AOM_DECODER=OFF \
    -DWITH_AOM_ENCODER=OFF -DWITH_SvtEnc=OFF -DWITH_RAV1E=OFF -DWITH_JPEG_DECODER=OFF \
    -DWITH_JPEG_ENCODER=OFF -DWITH_OpenJPEG_ENCODER=OFF -DWITH_OpenJPEG_DECODER=OFF \
    -DWITH_FFMPEG_DECODER=OFF -DWITH_OPENJPH_ENCODER=OFF -DWITH_LIBSHARPYUV=OFF \
    -DWITH_UNCOMPRESSED_CODEC=OFF -DWITH_WEBCODECS=OFF -DWITH_HEADER_COMPRESSION=OFF \
    -DWITH_EXAMPLES=OFF -DWITH_EXAMPLE_HEIF_THUMB=OFF -DWITH_EXAMPLE_HEIF_VIEW=OFF \
    -DWITH_GDK_PIXBUF=OFF -DBUILD_TESTING=OFF -DBUILD_DOCUMENTATION=OFF -DWITH_FUZZERS=OFF \
    >"$bdir-heif.log" 2>&1 || { tail -30 "$bdir-heif.log"; exit 1; }
  ninja -C "$bdir-heif" install >>"$bdir-heif.log" 2>&1 || { tail -30 "$bdir-heif.log"; exit 1; }

  # libjxl (encoder).
  # shellcheck disable=SC2086
  cmake -S "$LIBJXL" -B "$bdir" -G Ninja -Wno-dev $toolchain \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_C_FLAGS="$flags" \
    -DCMAKE_CXX_FLAGS="$flags" \
    -DBUILD_SHARED_LIBS=OFF \
    -DBUILD_TESTING=OFF \
    -DJPEGXL_ENABLE_TOOLS=OFF \
    -DJPEGXL_ENABLE_EXAMPLES=OFF \
    -DJPEGXL_ENABLE_BENCHMARK=OFF \
    -DJPEGXL_ENABLE_MANPAGES=OFF \
    -DJPEGXL_ENABLE_DOXYGEN=OFF \
    -DJPEGXL_ENABLE_JNI=OFF \
    -DJPEGXL_ENABLE_SJPEG=OFF \
    -DJPEGXL_ENABLE_JPEGLI=OFF \
    -DJPEGXL_ENABLE_JPEGLI_LIBJPEG=OFF \
    -DJPEGXL_ENABLE_TRANSCODE_JPEG=OFF \
    -DJPEGXL_ENABLE_OPENEXR=OFF \
    -DJPEGXL_ENABLE_PLUGINS=OFF \
    -DJPEGXL_ENABLE_VIEWERS=OFF \
    -DJPEGXL_ENABLE_DEVTOOLS=OFF \
    -DJPEGXL_ENABLE_BOXES=ON \
    -DJPEGXL_ENABLE_SKCMS=ON \
    -DJPEGXL_FORCE_SYSTEM_BROTLI=OFF \
    -DJPEGXL_FORCE_SYSTEM_HWY=OFF \
    -DJPEGXL_ENABLE_WASM_THREADS=OFF \
    >"$bdir.cmake.log" 2>&1 || { tail -30 "$bdir.cmake.log"; exit 1; }
  ninja -C "$bdir" jxl jxl_cms >"$bdir.ninja.log" 2>&1 || { tail -40 "$bdir.ninja.log"; exit 1; }

  cc="$WASI_SDK/bin/clang --target=wasm32-wasip1 --sysroot=$WASI_SDK/share/wasi-sysroot"
  objdir="$bdir/jxlbatch-obj"
  mkdir -p "$objdir"
  for src in jxlbatch meta pixels heif gainmap; do
    $cc -O3 $flags -Wall -Wno-unused-function -I"$LIBJXL/lib/include" -I"$bdir/lib/include" \
      -I"$prefix/include" -DJXLBATCH_VERSION="\"$VERSION\"" -c "src/$src.c" -o "$objdir/$src.o"
  done
  for src in src/xmp.cpp third_party/tinyxml2/tinyxml2.cpp; do
    "$WASI_SDK/bin/clang++" --target=wasm32-wasip1 --sysroot="$WASI_SDK/share/wasi-sysroot" \
      -std=c++11 -O3 $flags -fno-exceptions -Wall -Wextra \
      -c "$src" -o "$objdir/$(basename "$src" .cpp).o"
  done
  # 8 MiB stack (the 64 KiB default can silently overflow into the heap) and
  # stack-first layout, so an overflow traps instead of corrupting memory.
  "$WASI_SDK/bin/clang++" --target=wasm32-wasip1 --sysroot="$WASI_SDK/share/wasi-sysroot" \
    -O3 $flags -fno-exceptions "$objdir"/*.o \
    "$prefix/lib/libheif.a" "$prefix/lib/libde265.a" \
    "$bdir/lib/libjxl.a" "$bdir/lib/libjxl_cms.a" "$bdir/third_party/highway/libhwy.a" \
    "$bdir/third_party/brotli/libbrotlienc.a" "$bdir/third_party/brotli/libbrotlidec.a" \
    "$bdir/third_party/brotli/libbrotlicommon.a" \
    -Wl,-z,stack-size=8388608 -Wl,--stack-first -Wl,--max-memory=4294967296 \
    -Wl,--strip-debug \
    -o "$bdir/jxlbatch.wasm"
  wasm-opt -O3 "$bdir/jxlbatch.wasm" -o "$out"
  echo "wrote $out ($(wc -c <"$out" | tr -d ' ') bytes)"
}

build_variant simd "-msimd128" "$ROOT/dist/jxlbatch.wasm"
build_variant scalar "" "$ROOT/dist/jxlbatch-scalar.wasm"
