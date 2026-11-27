#!/bin/zsh
# Builds Compress Photos Helper.app (src/photoedits), which the Mac selection
# route starts to save an edited photo's copy with its edit: Swift with
# PhotoKit, arm64, macOS 14 or later, signed ad hoc. Writes the app and its
# release file, compress-photos-helper-macos.zip (the app in it, for
# `ditto -x -k`), into dist/, or into the folder given as the argument (the
# tests). Each build has another signature, so macOS asks again for access to
# Photos the first time it runs.
set -e
ROOT=${0:A:h:h}
VERSION=$(cat "$ROOT/VERSION")
OUT=${1:-$ROOT/dist}
APP="$OUT/Compress Photos Helper.app"
ZIP="$OUT/compress-photos-helper-macos.zip"
CACHE="${TMPDIR:-/tmp}/compress-photos-swift-cache"
mkdir -p "$OUT" "$CACHE"
[ -d "$APP" ] && /bin/rm -r "$APP"
/bin/rm -f "$ZIP"
mkdir -p "$APP/Contents/MacOS"
sed "s/@VERSION@/$VERSION/g" "$ROOT/src/photoedits/Info.plist" > "$APP/Contents/Info.plist"
swiftc -swift-version 5 -O -module-cache-path "$CACHE" -target arm64-apple-macos14.0 \
  -o "$APP/Contents/MacOS/photoedits" "$ROOT/src/photoedits/main.swift"
codesign -s - --force "$APP"
ditto -c -k --norsrc --noextattr --noacl --keepParent "$APP" "$ZIP"
echo "wrote $APP ($("$APP/Contents/MacOS/photoedits" --version)) and $ZIP"
