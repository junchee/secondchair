#!/bin/bash
# Puts the Anne picture on the desktop launcher (no Xcode tools needed: macOS's own osascript does it).
# Usage: bash ~/secondchair/set_icon.sh ["path/to/launcher.command"]
DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET="${1:-}"
if [ -z "$TARGET" ]; then
  for name in "Anne.command" "SecondChair.command" "secondchair 시작.command"; do
    [ -e "$HOME/Desktop/$name" ] && TARGET="$HOME/Desktop/$name" && break
  done
fi
[ -e "$TARGET" ] || { echo "바탕화면에서 시작 아이콘을 찾지 못했습니다. 경로를 함께 적어 주세요."; exit 1; }
osascript -l JavaScript - "$DIR/ui/anne.png" "$TARGET" <<'JS'
ObjC.import('AppKit');
function run(argv) {
  const image = $.NSImage.alloc.initWithContentsOfFile(argv[0]);
  const ok = $.NSWorkspace.sharedWorkspace.setIconForFileOptions(image, argv[1], 0);
  return ok ? "아이콘을 바꿨습니다: " + argv[1] : "아이콘을 바꾸지 못했습니다.";
}
JS
touch "$TARGET"
