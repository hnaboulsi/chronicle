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

APP="/tmp/vero-build/Build/Products/Debug/LifeManager.app"

if [ ! -d "$APP" ]; then
  echo "Build failed — no app found at $APP"
  exit 1
fi

echo "Installing to /Applications..."
rm -rf "/Applications/LifeManager.app"
cp -R "$APP" "/Applications/LifeManager.app"

echo "Launching Vero..."
# Kill existing instance if running
pkill -x LifeManager 2>/dev/null || true
sleep 0.5
open "/Applications/LifeManager.app"

echo "Done!"
