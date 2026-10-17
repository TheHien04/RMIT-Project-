#!/bin/sh
set -eu

ROOT="$(CDPATH= cd "$(dirname "$0")/.." && pwd)"
SOURCE="$ROOT/app_launcher/launcher.c"
BUNDLE="$ROOT/Coach Companion.app"
CONTENTS="$BUNDLE/Contents"
DESTINATION="$CONTENTS/MacOS/Coach Companion"

mkdir -p "$(dirname "$DESTINATION")"
cp "$ROOT/app_launcher/Info.plist" "$CONTENTS/Info.plist"
clang -Os -Wall -Wextra "$SOURCE" -o "$DESTINATION"
chmod +x "$DESTINATION"
plutil -lint "$CONTENTS/Info.plist"
IDENTITY="${COACH_CODESIGN_IDENTITY:--}"
if [ "$IDENTITY" = "-" ]; then
  codesign --force --deep --sign - "$BUNDLE"
  echo "Applied an ad-hoc integrity signature. Set COACH_CODESIGN_IDENTITY for distribution."
else
  codesign --force --deep --options runtime --timestamp --sign "$IDENTITY" "$BUNDLE"
fi
codesign --verify --deep --strict --verbose=2 "$BUNDLE"
echo "Built $DESTINATION"
