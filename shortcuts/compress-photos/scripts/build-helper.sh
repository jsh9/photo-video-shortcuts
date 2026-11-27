#!/bin/zsh
# Builds Compress Photos Helper.app (src/photoedits) into dist/: Swift with
# PhotoKit, arm64, macOS 14 or later, signed ad hoc. Each build has another
# signature, so macOS asks again for access to Photos the first time it runs.
set -e
ROOT=${0:A:h:h}
VERSION=$(cat "$ROOT/VERSION")
APP="$ROOT/dist/Compress Photos Helper.app"
CACHE="${TMPDIR:-/tmp}/compress-photos-swift-cache"
mkdir -p "$ROOT/dist" "$CACHE"
[ -d "$APP" ] && /bin/rm -r "$ROOT/dist/Compress Photos Helper.app"
mkdir -p "$APP/Contents/MacOS"
sed "s/@VERSION@/$VERSION/g" "$ROOT/src/photoedits/Info.plist" > "$APP/Contents/Info.plist"
swiftc -swift-version 5 -O -module-cache-path "$CACHE" -target arm64-apple-macos14.0 \
  -o "$APP/Contents/MacOS/photoedits" "$ROOT/src/photoedits/main.swift"
codesign -s - --force "$APP"
echo "wrote $APP"
