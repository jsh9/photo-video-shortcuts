#!/bin/sh
# Builds jxlbatch for macOS against Homebrew's libjxl and libheif, for testing
# on the Mac.
# Output: build/jxlbatch
set -eu
cd "$(dirname "$0")/.."
mkdir -p build/native-obj
VERSION=$(cat VERSION)  # shared by the encoder and the shortcuts
for src in jxlbatch meta pixels heif gainmap; do
  # shellcheck disable=SC2046
  cc -O2 -g -Wall -Wextra -Wno-unused-function -DJXLBATCH_THREADS \
    -DJXLBATCH_VERSION="\"$VERSION\"" \
    $(pkg-config --cflags libjxl libjxl_threads libheif) \
    -c "src/$src.c" -o "build/native-obj/$src.o"
done
for src in src/xmp.cpp third_party/tinyxml2/tinyxml2.cpp; do
  c++ -std=c++11 -O2 -g -Wall -Wextra -fno-exceptions \
    -c "$src" -o "build/native-obj/$(basename "$src" .cpp).o"
done
# shellcheck disable=SC2046
c++ build/native-obj/*.o $(pkg-config --libs libjxl libjxl_threads libheif) \
  -o build/jxlbatch
echo "built build/jxlbatch"
