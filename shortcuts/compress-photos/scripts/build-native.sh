#!/bin/sh
# Builds jxlbatch for macOS against Homebrew's libjxl and libheif, for testing
# on the Mac.
# Output: build/jxlbatch
set -eu
cd "$(dirname "$0")/.."
mkdir -p build
# shellcheck disable=SC2046
cc -O2 -g -Wall -Wextra -Wno-unused-function -DJXLBATCH_THREADS \
  src/jxlbatch.c src/meta.c src/pixels.c src/heif.c \
  $(pkg-config --cflags --libs libjxl libjxl_threads libheif) \
  -o build/jxlbatch
echo "built build/jxlbatch"
