#!/bin/sh
# Builds the tools of the Compress Videos (macOS) shortcut as native macOS
# commands:
#
#   dist/ffmpeg-macos    FFmpeg's ffmpeg, with only what the shortcut uses
#   dist/ffprobe-macos   FFmpeg's ffprobe, from the same build
#   dist/vidmeta-macos   the metadata helper (src/vidmeta.c + src/mp4meta.c)
#   build/vidmeta        the same helper with the address and undefined-behavior
#                        sanitizers, for the tests
#
# The dist/ files are arm64 (Apple silicon), macOS 14 or later, statically
# linked (they depend only on the system's libc++ and libSystem), stripped and
# ad-hoc signed.
#
# FFmpeg is configured with --disable-everything plus what the shortcut's
# commands use: MOV/MP4 in, MP4 out, HEVC, H.264, AAC, ALAC, PCM and Opus
# decoding, scaling and resampling, and three encoders linked in statically:
# x265 (H.265: the 8-bit library with the 10-bit one linked in, so it encodes
# Main and Main 10), SVT-AV1 (AV1) and libopus (Opus). x265 makes the build GPL,
# as this repository is. --extra-version puts "compress-videos-<VERSION>" in
# ffmpeg's and ffprobe's version line, which scripts/release.py checks.
#
# Needs: Homebrew cmake, ninja and pkg-config. Downloads the sources into the
# repository's .deps/ on first run and checks their SHA-256. The libraries and
# FFmpeg are built in build/macos, where a second run only rebuilds what
# changed (CI caches that folder). ONLY=vidmeta builds the helper alone.
set -eu
cd "$(dirname "$0")/.."
ROOT=$(pwd)
REPO=$(cd ../.. && pwd)
VERSION=$(cat VERSION)  # shared by the tools and the shortcut

FFMPEG_VERSION=9.0.2
X265_VERSION=4.3
SVTAV1_VERSION=4.2.0
OPUS_VERSION=1.6.1
# The release archives' SHA-256 (the same as Homebrew's formulae).
FFMPEG_SHA256=8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e
X265_SHA256=83c53e4c8bbb8f1e33ed59e10a7d621d1d7801ca853910c3eb41f038b8ffb121
SVTAV1_SHA256=512f2ea5649e3e76c2dddcc25c2556fb67a9582baaab207c9c96161c94659dad
OPUS_SHA256=6ffcb593207be92584df15b32466ed64bbec99109f007c82205f0194572411a1
DEPS="$REPO/.deps"
FFMPEG="$DEPS/ffmpeg-$FFMPEG_VERSION"
X265="$DEPS/x265-$X265_VERSION"
SVTAV1="$DEPS/svt-av1-$SVTAV1_VERSION"
OPUS="$DEPS/opus-$OPUS_VERSION"
MIN_MACOS=14.0  # Opus in MP4 plays in Photos from macOS 14 on
ARCH=arm64
ONLY=${ONLY:-all}
# The compilers by path: in a user's shell, "cc" may be another toolchain's.
CC=/usr/bin/clang
CXX=/usr/bin/clang++

if [ "$(uname -s)" != Darwin ]; then
  echo "build-macos.sh: this build runs on macOS only" >&2
  exit 1
fi
if [ "$(uname -m)" != "$ARCH" ]; then
  # Cross-compiling would need the libraries' builds set up for it too; the
  # release is built on Apple silicon.
  echo "build-macos.sh: this build runs on an Apple silicon ($ARCH) Mac only (this is $(uname -m))" >&2
  exit 1
fi

mkdir -p "$DEPS" "$ROOT/dist" "$ROOT/build"
bdir="$ROOT/build/macos"
mkdir -p "$bdir"
flags="-arch $ARCH -mmacosx-version-min=$MIN_MACOS"

# vidmeta: plain C, no libraries.
helper_flags="-std=c11 -Wall -Wextra -DVIDMETA_VERSION=\"$VERSION\""
# shellcheck disable=SC2086
$CC $flags -O2 $helper_flags src/vidmeta.c src/mp4meta.c -o "$ROOT/dist/vidmeta-macos"
strip "$ROOT/dist/vidmeta-macos" 2>/dev/null  # re-signed below
codesign -s - --force "$ROOT/dist/vidmeta-macos" 2>/dev/null
# shellcheck disable=SC2086
$CC $flags -O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer $helper_flags \
  src/vidmeta.c src/mp4meta.c -o "$ROOT/build/vidmeta"
echo "wrote $ROOT/dist/vidmeta-macos and $ROOT/build/vidmeta: $("$ROOT/dist/vidmeta-macos" --version)"
[ "$ONLY" = vidmeta ] && exit 0

# fetch NAME-DIR URL SHA256: downloads and unpacks a release archive into
# NAME-DIR, once.
fetch() {
  [ -d "$1" ] && return 0
  archive="$DEPS/${2##*/}"
  echo "Downloading ${2##*/}..."
  /usr/bin/curl -sSfL -o "$archive" "$2"
  if [ "$(shasum -a 256 "$archive" | cut -d ' ' -f 1)" != "$3" ]; then
    echo "build-macos.sh: $archive is not the expected file (SHA-256 differs)" >&2
    rm -f "$archive"
    exit 1
  fi
  rm -rf "$1.tmp"
  mkdir -p "$1.tmp"
  tar xf "$archive" -C "$1.tmp" --strip-components 1
  mv "$1.tmp" "$1"
  rm -f "$archive"
}
fetch "$FFMPEG" "https://ffmpeg.org/releases/ffmpeg-$FFMPEG_VERSION.tar.xz" "$FFMPEG_SHA256"
fetch "$X265" "https://github.com/Multicorewareinc/x265/releases/download/$X265_VERSION/x265_$X265_VERSION.tar.gz" "$X265_SHA256"
fetch "$SVTAV1" "https://gitlab.com/AOMediaCodec/SVT-AV1/-/archive/v$SVTAV1_VERSION/SVT-AV1-v$SVTAV1_VERSION.tar.bz2" "$SVTAV1_SHA256"
fetch "$OPUS" "https://downloads.xiph.org/releases/opus/opus-$OPUS_VERSION.tar.gz" "$OPUS_SHA256"

# Each library in its own folder, named after its version, all installed into
# one prefix that FFmpeg's configure reads (pkg-config).
prefix="$bdir/prefix"
common="-DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER=$CC -DCMAKE_CXX_COMPILER=$CXX -DCMAKE_OSX_ARCHITECTURES=$ARCH -DCMAKE_OSX_DEPLOYMENT_TARGET=$MIN_MACOS -DCMAKE_INSTALL_PREFIX=$prefix -DBUILD_SHARED_LIBS=OFF"
log() { echo "$bdir/$1.log"; }
fail() { tail -40 "$(log "$1")"; exit 1; }

echo "== libopus $OPUS_VERSION"
# shellcheck disable=SC2086
cmake -S "$OPUS" -B "$bdir/opus-$OPUS_VERSION" -G Ninja -Wno-dev $common \
  -DOPUS_BUILD_SHARED_LIBRARY=OFF -DOPUS_BUILD_TESTING=OFF -DOPUS_BUILD_PROGRAMS=OFF \
  >"$(log opus)" 2>&1 || fail opus
ninja -C "$bdir/opus-$OPUS_VERSION" install >>"$(log opus)" 2>&1 || fail opus

echo "== x265 $X265_VERSION"
# Two builds of the same source, as Homebrew's: the 10-bit one (Main 10, for
# HDR and the 10-bit output of every video) linked into the 8-bit one, then
# merged into one static library. CMAKE_POLICY_VERSION_MINIMUM: x265's
# CMakeLists predates CMake 4.
x265_flags="$common -DCMAKE_POLICY_VERSION_MINIMUM=3.5 -DENABLE_SHARED=OFF -DENABLE_CLI=OFF"
x265_10="$bdir/x265-$X265_VERSION-10bit"
x265_8="$bdir/x265-$X265_VERSION-8bit"
# shellcheck disable=SC2086
cmake -S "$X265/source" -B "$x265_10" -G Ninja -Wno-dev $x265_flags \
  -DHIGH_BIT_DEPTH=ON -DEXPORT_C_API=OFF \
  >"$(log x265)" 2>&1 || fail x265
ninja -C "$x265_10" x265-static >>"$(log x265)" 2>&1 || fail x265
mkdir -p "$x265_8"
cp "$x265_10/libx265.a" "$x265_8/libx265_main10.a"
# shellcheck disable=SC2086
cmake -S "$X265/source" -B "$x265_8" -G Ninja -Wno-dev $x265_flags \
  -DLINKED_10BIT=ON -DEXTRA_LIB=x265_main10.a -DEXTRA_LINK_FLAGS="-L$x265_8" \
  >>"$(log x265)" 2>&1 || fail x265
ninja -C "$x265_8" install >>"$(log x265)" 2>&1 || fail x265
libtool -static -o "$prefix/lib/libx265.a" "$x265_8/libx265.a" "$x265_8/libx265_main10.a" \
  >>"$(log x265)" 2>&1 || fail x265

echo "== SVT-AV1 $SVTAV1_VERSION"
# The encoder library only; it picks its NEON code paths at run time.
# shellcheck disable=SC2086
cmake -S "$SVTAV1" -B "$bdir/svt-av1-$SVTAV1_VERSION" -G Ninja -Wno-dev $common \
  -DBUILD_APPS=OFF -DBUILD_TESTING=OFF -DEXCLUDE_HASH=ON \
  >"$(log svt-av1)" 2>&1 || fail svt-av1
ninja -C "$bdir/svt-av1-$SVTAV1_VERSION" install >>"$(log svt-av1)" 2>&1 || fail svt-av1

echo "== FFmpeg $FFMPEG_VERSION"
# Only what the shortcut's ffmpeg and ffprobe commands use:
# - in: the file protocol and the MOV/MP4 demuxer; the video and audio codecs
#   of iPhone and camera videos (HEVC, H.264, AAC, ALAC, PCM, Opus);
# - out: the MP4 muxer, x265, SVT-AV1 and libopus; pipe: for -progress pipe:1;
# - between: scale (the size limit, and 10-bit conversion) and aresample
#   (48 kHz for Opus, -ac 2), and the filters ffmpeg itself needs.
# --disable-autodetect keeps out everything else this Mac has (VideoToolbox,
# zlib, iconv, Homebrew's libraries...); PKG_CONFIG_LIBDIR finds only the
# libraries built above. configure still adds CoreFoundation, CoreMedia and
# CoreVideo to the link, which nothing here uses: -dead_strip_dylibs drops them.
ffdir="$bdir/ffmpeg-$FFMPEG_VERSION"
mkdir -p "$ffdir"
# configure runs again only when this script changes (it takes a minute); make
# rebuilds what changed. The programs are relinked every time, in case a
# library above was rebuilt.
stamp=$(shasum -a 256 "$ROOT/scripts/build-macos.sh" | cut -d ' ' -f 1)
if [ "$(cat "$ffdir/configured" 2>/dev/null || true)" != "$stamp" ]; then
  (
    cd "$ffdir"
    PKG_CONFIG_LIBDIR="$prefix/lib/pkgconfig" PKG_CONFIG_PATH="" \
    "$FFMPEG/configure" \
      --prefix="$prefix" --cc="$CC" --cxx="$CXX" \
      --extra-cflags="$flags" --extra-ldflags="$flags -Wl,-dead_strip -Wl,-dead_strip_dylibs" \
      --extra-version="compress-videos-$VERSION" \
      --pkg-config=pkg-config --pkg-config-flags=--static \
      --enable-static --disable-shared --disable-autodetect --disable-everything \
      --disable-doc --disable-debug --disable-network --disable-avdevice --disable-ffplay \
      --enable-gpl --enable-libx265 --enable-libsvtav1 --enable-libopus \
      --enable-protocol=file,pipe \
      --enable-demuxer=mov --enable-muxer=mp4 \
      --enable-decoder='hevc,h264,aac,alac,opus,pcm_*' \
      --enable-parser=hevc,h264,aac,opus,av1 \
      --enable-encoder=libx265,libsvtav1,libopus \
      --enable-filter=scale,aresample,format,aformat,null,anull
  ) >"$(log ffmpeg)" 2>&1 || fail ffmpeg
  echo "$stamp" >"$ffdir/configured"
fi
rm -f "$ffdir/ffmpeg" "$ffdir/ffprobe" "$ffdir/ffmpeg_g" "$ffdir/ffprobe_g"
make -C "$ffdir" -j "$(sysctl -n hw.ncpu)" ffmpeg ffprobe >>"$(log ffmpeg)" 2>&1 || fail ffmpeg

for tool in ffmpeg ffprobe; do
  out="$ROOT/dist/$tool-macos"
  cp "$ffdir/$tool" "$out"
  strip "$out" 2>/dev/null  # it warns that it invalidates the signature; re-signed below
  # The linker signs ad hoc already; sign again after stripping so the
  # signature matches the file. macOS doesn't run unsigned arm64 code.
  codesign -s - --force "$out" 2>/dev/null
done

# Nothing from Homebrew or the build folder may be linked dynamically.
for out in "$ROOT/dist/ffmpeg-macos" "$ROOT/dist/ffprobe-macos" "$ROOT/dist/vidmeta-macos"; do
  if otool -L "$out" | tail -n +2 | grep -v -E '^\s*/usr/lib/'; then
    echo "build-macos.sh: $out depends on libraries outside /usr/lib (above)" >&2
    exit 1
  fi
  echo "wrote $out ($(wc -c <"$out" | tr -d ' ') bytes)"
done
"$ROOT/dist/ffmpeg-macos" -hide_banner -version | head -1
