#!/bin/sh
# Builds jxlbatch as a native macOS command for the Mac shortcuts (Compress
# Photos (macOS) and Compress Photo Files (macOS)).
#
# Output: dist/jxlbatch-macos   arm64 (Apple silicon), macOS 14 or later,
#                               statically linked (depends only on the system
#                               libc++ and libSystem), ad-hoc signed
#
# Same sources and the same libraries as the WebAssembly build (libjxl with
# skcms, libheif, libde265), so the results match jxlbatch.wasm's, but with
# threads (JXLBATCH_THREADS). Needs: Homebrew cmake and ninja. Downloads the
# library sources into the repository's .deps/ on first run; libjxl gets its
# own clone there (.deps/libjxl-native), because build-wasm.sh patches the
# threads out of .deps/libjxl.
set -eu
cd "$(dirname "$0")/.."
ROOT=$(pwd)
REPO=$(cd ../.. && pwd)
VERSION=$(cat VERSION)  # shared by the encoder and the shortcuts

LIBJXL_VERSION=v0.11.2
LIBHEIF_VERSION=v1.23.5
LIBDE265_VERSION=v1.1.3
X265_VERSION=4.3  # the same release Compress Videos builds (shared source folder)
X265_SHA256=83c53e4c8bbb8f1e33ed59e10a7d621d1d7801ca853910c3eb41f038b8ffb121
DEPS="$REPO/.deps"
LIBJXL="$DEPS/libjxl-native"
LIBHEIF="$DEPS/libheif"
LIBDE265="$DEPS/libde265"
X265="$DEPS/x265-$X265_VERSION"
MIN_MACOS=14.0  # Photos and ImageIO read JPEG XL from macOS 14 on
ARCH=arm64

if [ "$(uname -s)" != Darwin ]; then
  echo "build-macos.sh: this build runs on macOS only" >&2
  exit 1
fi
if [ "$(uname -m)" != "$ARCH" ]; then
  # Cross-compiling would need the libraries' cmake builds set up for it too;
  # the release is built on Apple silicon.
  echo "build-macos.sh: this build runs on an Apple silicon ($ARCH) Mac only (this is $(uname -m))" >&2
  exit 1
fi

mkdir -p "$DEPS" "$ROOT/dist" "$ROOT/build"

if [ ! -d "$LIBJXL/.git" ]; then
  echo "Cloning libjxl $LIBJXL_VERSION (native copy)..."
  git -c advice.detachedHead=false clone -q --depth 1 -b "$LIBJXL_VERSION" https://github.com/libjxl/libjxl "$LIBJXL"
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
# x265 (HEVC encoder, for HEIC output): a release archive, checked by hash,
# as Compress Videos' build-macos.sh fetches it.
if [ ! -d "$X265" ]; then
  archive="$DEPS/x265_$X265_VERSION.tar.gz"
  echo "Downloading x265 $X265_VERSION..."
  /usr/bin/curl -sSfL -o "$archive" \
    "https://github.com/Multicorewareinc/x265/releases/download/$X265_VERSION/x265_$X265_VERSION.tar.gz"
  if [ "$(shasum -a 256 "$archive" | cut -d ' ' -f 1)" != "$X265_SHA256" ]; then
    echo "build-macos.sh: $archive is not the expected file (SHA-256 differs)" >&2
    rm -f "$archive"
    exit 1
  fi
  rm -rf "$X265.tmp"
  mkdir -p "$X265.tmp"
  tar xf "$archive" -C "$X265.tmp" --strip-components 1
  mv "$X265.tmp" "$X265"
  rm -f "$archive"
fi

# Only the skcms edit: this build has threads and exceptions. (The libheif
# and x265 checkouts may carry build-wasm.sh's edits; they are guarded by
# __wasi__ and __cpp_exceptions, so they don't apply here.)
python3 "$ROOT/scripts/patch_deps.py" --skcms --libjxl "$LIBJXL"

bdir="$ROOT/build/macos"
prefix="$bdir/prefix"
mkdir -p "$bdir"
common="-DCMAKE_BUILD_TYPE=Release -DCMAKE_OSX_ARCHITECTURES=$ARCH -DCMAKE_OSX_DEPLOYMENT_TARGET=$MIN_MACOS -DCMAKE_INSTALL_PREFIX=$prefix -DBUILD_SHARED_LIBS=OFF"

# libde265 (HEVC decoder), without its command-line tools.
# shellcheck disable=SC2086
cmake -S "$LIBDE265" -B "$bdir/de265" -G Ninja -Wno-dev $common \
  -DENABLE_SDL=OFF -DENABLE_DECODER=OFF -DENABLE_ENCODER=OFF \
  >"$bdir/de265.log" 2>&1 || { tail -30 "$bdir/de265.log"; exit 1; }
ninja -C "$bdir/de265" install >>"$bdir/de265.log" 2>&1 || { tail -30 "$bdir/de265.log"; exit 1; }

# libheif: HEIF container + libde265, decoding only, no plugins. The same
# feature flags as build-wasm.sh, with threads. PKG_CONFIG_LIBDIR keeps it from
# finding Homebrew's libraries.
# shellcheck disable=SC2086
PKG_CONFIG_LIBDIR="$prefix/lib/pkgconfig" PKG_CONFIG_PATH="" \
cmake -S "$LIBHEIF" -B "$bdir/heif" -G Ninja -Wno-dev $common \
  -DCMAKE_PREFIX_PATH="$prefix" -DCMAKE_FIND_ROOT_PATH="$prefix" \
  -DLIBDE265_INCLUDE_DIR="$prefix/include" -DLIBDE265_LIBRARY="$prefix/lib/libde265.a" \
  -DENABLE_PLUGIN_LOADING=OFF \
  -DWITH_LIBDE265=ON -DWITH_LIBDE265_PLUGIN=OFF \
  -DWITH_X265=OFF -DWITH_KVAZAAR=OFF -DWITH_UVG266=OFF -DWITH_VVDEC=OFF -DWITH_VVENC=OFF \
  -DWITH_X264=OFF -DWITH_OpenH264_DECODER=OFF -DWITH_DAV1D=OFF -DWITH_AOM_DECODER=OFF \
  -DWITH_AOM_ENCODER=OFF -DWITH_SvtEnc=OFF -DWITH_RAV1E=OFF -DWITH_JPEG_DECODER=OFF \
  -DWITH_JPEG_ENCODER=OFF -DWITH_OpenJPEG_ENCODER=OFF -DWITH_OpenJPEG_DECODER=OFF \
  -DWITH_FFMPEG_DECODER=OFF -DWITH_OPENJPH_ENCODER=OFF -DWITH_LIBSHARPYUV=OFF \
  -DWITH_UNCOMPRESSED_CODEC=OFF -DWITH_WEBCODECS=OFF -DWITH_HEADER_COMPRESSION=OFF \
  -DWITH_EXAMPLES=OFF -DWITH_EXAMPLE_HEIF_THUMB=OFF -DWITH_EXAMPLE_HEIF_VIEW=OFF \
  -DWITH_GDK_PIXBUF=OFF -DBUILD_TESTING=OFF -DBUILD_DOCUMENTATION=OFF -DWITH_FUZZERS=OFF \
  >"$bdir/heif.log" 2>&1 || { tail -30 "$bdir/heif.log"; exit 1; }
ninja -C "$bdir/heif" install >>"$bdir/heif.log" 2>&1 || { tail -30 "$bdir/heif.log"; exit 1; }

# x265 (HEVC encoder, for HEIC output): 8-bit only, no command-line tool.
# CMAKE_POLICY_VERSION_MINIMUM: x265's CMakeLists predates CMake 4. Linking
# x265 makes jxlbatch-macos GPL (as the repository is).
# shellcheck disable=SC2086
cmake -S "$X265/source" -B "$bdir/x265" -G Ninja -Wno-dev $common \
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 -DENABLE_SHARED=OFF -DENABLE_CLI=OFF \
  >"$bdir/x265.log" 2>&1 || { tail -30 "$bdir/x265.log"; exit 1; }
ninja -C "$bdir/x265" install >>"$bdir/x265.log" 2>&1 || { tail -30 "$bdir/x265.log"; exit 1; }

# libjxl (encoder) with its threads library; skcms as the color engine, as in
# the WebAssembly build.
# shellcheck disable=SC2086
cmake -S "$LIBJXL" -B "$bdir/jxl" -G Ninja -Wno-dev $common \
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
  >"$bdir/jxl.cmake.log" 2>&1 || { tail -30 "$bdir/jxl.cmake.log"; exit 1; }
ninja -C "$bdir/jxl" jxl jxl_cms jxl_threads >"$bdir/jxl.ninja.log" 2>&1 || { tail -40 "$bdir/jxl.ninja.log"; exit 1; }

objdir="$bdir/jxlbatch-obj"
mkdir -p "$objdir"
flags="-arch $ARCH -mmacosx-version-min=$MIN_MACOS -O2"
for src in jxlbatch meta pixels heif gainmap hdr grain hevcenc heifbox heicout; do
  # shellcheck disable=SC2086
  cc $flags -Wall -Wextra -Wno-unused-function -DJXLBATCH_THREADS -DJXLBATCH_HEIC \
    -DJXLBATCH_VERSION="\"$VERSION\"" \
    -I"$LIBJXL/lib/include" -I"$bdir/jxl/lib/include" -I"$prefix/include" \
    -c "src/$src.c" -o "$objdir/$src.o"
done
for src in src/xmp.cpp third_party/tinyxml2/tinyxml2.cpp; do
  # shellcheck disable=SC2086
  c++ $flags -std=c++11 -Wall -Wextra -fno-exceptions \
    -c "$src" -o "$objdir/$(basename "$src" .cpp).o"
done
out="$ROOT/dist/jxlbatch-macos"
# shellcheck disable=SC2086
c++ $flags "$objdir"/*.o \
  "$bdir/jxl/lib/libjxl.a" "$bdir/jxl/lib/libjxl_cms.a" "$bdir/jxl/lib/libjxl_threads.a" \
  "$bdir/jxl/third_party/highway/libhwy.a" \
  "$bdir/jxl/third_party/brotli/libbrotlienc.a" "$bdir/jxl/third_party/brotli/libbrotlidec.a" \
  "$bdir/jxl/third_party/brotli/libbrotlicommon.a" \
  "$prefix/lib/libheif.a" "$prefix/lib/libde265.a" "$prefix/lib/libx265.a" \
  -lpthread -o "$out"
strip -x "$out" 2>/dev/null  # it warns that it invalidates the signature; re-signed below
# The linker signs ad hoc already; sign again after stripping so the signature
# matches the file. macOS runs unsigned arm64 code not at all.
codesign -s - --force "$out" 2>/dev/null

# Nothing from Homebrew or the build folder may be linked dynamically.
if otool -L "$out" | tail -n +2 | grep -v -E '^\s*/usr/lib/'; then
  echo "build-macos.sh: $out depends on libraries outside /usr/lib (above)" >&2
  exit 1
fi
echo "wrote $out ($(wc -c <"$out" | tr -d ' ') bytes): $("$out" --version | head -1)"
