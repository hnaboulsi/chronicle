#!/bin/bash
set -e

cd "$(dirname "$0")"

echo "Building Vero..."
xcodegen generate --quiet

xcodebuild \
  -scheme LifeManager \
  -configuration Debug \
  -derivedDataPath /tmp/vero-build \
  build \
  2>&1 | grep -E "(error:|warning:|Build succeeded|Build FAILED)" || true

APP="/tmp/vero-build/Build/Products/Debug/Vero.app"

if [ ! -d "$APP" ]; then
  echo "Build failed — no app found at $APP"
  exit 1
fi

# Re-sign the app to fix signature issues
echo "Re-signing app..."
codesign --remove-signature "$APP" 2>/dev/null || true
codesign -s - "$APP" --force --deep 2>&1 | grep -v "code has no resources" || true

echo "Installing to /Applications..."
rm -rf "/Applications/LifeManager.app"
rm -rf "/Applications/Vero.app"
cp -R "$APP" "/Applications/Vero.app"

# Re-sign the installed app as well
codesign --remove-signature "/Applications/Vero.app" 2>/dev/null || true
codesign -s - "/Applications/Vero.app" --force --deep 2>&1 | grep -v "code has no resources" || true

echo "Launching Vero..."
# Kill existing instance if running
pkill -x Vero 2>/dev/null || true
sleep 0.5
open "/Applications/Vero.app"

echo "Done!"
