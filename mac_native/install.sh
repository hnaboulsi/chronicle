#!/bin/bash
set -e

cd "$(dirname "$0")"

echo "Building Vero..."
xcodegen generate --quiet

xcodebuild \
  -project Vero.xcodeproj \
  -scheme Vero \
  -configuration Debug \
  -derivedDataPath /tmp/vero-build \
  build \
  2>&1 | grep -E "(error:|warning:|Build succeeded|Build FAILED)" || true

APP="/tmp/vero-build/Build/Products/Debug/Vero.app"

if [ ! -d "$APP" ]; then
  echo "Build failed — no app found at $APP"
  exit 1
fi

# Relying on Xcode's built-in ad-hoc signing to preserve Accessibility permissions across rebuilds.

echo "Installing to /Applications..."
rm -rf "/Applications/LifeManager.app"
rm -rf "/Applications/Vero.app"
cp -R "$APP" "/Applications/Vero.app"

# Skipped re-signing installed app to preserve Accessibility.

echo "Launching Vero..."
# Kill existing instances — including stale VeroAgent from the old two-process architecture.
pkill -x Vero 2>/dev/null || true
pkill -x VeroAgent 2>/dev/null || true
# Remove stale VeroAgent build artifact so macOS BTM can't auto-launch it.
rm -rf /tmp/vero-build/Build/Products/Debug/VeroAgent.app 2>/dev/null || true
sleep 0.5
open "/Applications/Vero.app"

echo "Done!"
