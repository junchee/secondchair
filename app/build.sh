#!/bin/bash
# Builds Anne.app with the Command Line Tools only (no Xcode app): Swift Package Manager (WhisperKit) + a hand-made bundle.
# The app starts the Python program found in this repository (AnneHome); Python and the models are not bundled yet.
# The speech model is read from ~/AnneProto/model (see Speech.swift); without it the app falls back to Python speech.
set -e
cd "$(dirname "$0")"
REPO="$(cd .. && pwd)"
# Built outside the iCloud folder: iCloud puts file attributes on everything there and codesign then refuses.
BUILD="${ANNE_BUILD_DIR:-$HOME/AnneApp/build}"
mkdir -p "$BUILD"
OUT="$BUILD/Anne.app"
rm -rf "$OUT"
mkdir -p "$OUT/Contents/MacOS" "$OUT/Contents/Resources"

# SwiftPM keeps its work files outside the iCloud folder too (the first build fetches WhisperKit and takes a few minutes)
swift build -c release --package-path "$REPO/app" --scratch-path "$BUILD/swiftpm" 2>&1 | grep -E "error|warning: unre|Build complete|Compiling Anne" || true
cp "$BUILD/swiftpm/release/Anne" "$OUT/Contents/MacOS/Anne"
for bundle in "$BUILD"/swiftpm/release/*.bundle; do [ -e "$bundle" ] && cp -R "$bundle" "$OUT/Contents/Resources/"; done

# Icon: Jun's picture on a cream rounded square, all the sizes macOS wants
ICONSET="$(mktemp -d)/Anne.iconset"; mkdir -p "$ICONSET"
swiftc -O -o "$BUILD/make_icon" tools/make_icon.swift -framework AppKit
"$BUILD/make_icon" "$REPO/ui/anne.png" "$ICONSET/base.png"
for size in 16 32 64 128 256 512; do
  sips -z $size $size "$ICONSET/base.png" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
  sips -z $((size*2)) $((size*2)) "$ICONSET/base.png" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done
rm "$ICONSET/base.png" "$ICONSET/icon_64x64.png" "$ICONSET/icon_64x64@2x.png" 2>/dev/null || true
iconutil -c icns "$ICONSET" -o "$OUT/Contents/Resources/AppIcon.icns"
rm -f "$BUILD/make_icon"

VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$REPO/version.json")"
cat > "$OUT/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Anne</string>
  <key>CFBundleDisplayName</key><string>Anne</string>
  <key>CFBundleIdentifier</key><string>io.github.junchee.anne</string>
  <key>CFBundleExecutable</key><string>Anne</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>14.2</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSMicrophoneUsageDescription</key><string>Anne가 내 목소리를 받아 적고 번역하기 위해 마이크를 사용합니다.</string>
  <key>NSAudioCaptureUsageDescription</key><string>Anne가 회의 상대의 소리를 받아 적고 번역하기 위해 Mac이 내는 소리를 읽습니다.</string>
  <key>AnneHome</key><string>$REPO</string>
</dict></plist>
PLIST

# No Apple account: sign "ad hoc" (needed for Apple silicon to run it at all)
chmod -R u+w "$OUT"   # copied resource files are read-only
xattr -cr "$OUT"   # iCloud and Finder add attributes that codesign refuses
codesign --force --deep --sign - "$OUT"
echo "built: $OUT"
