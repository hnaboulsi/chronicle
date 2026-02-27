#!/bin/bash
# Builds Life Manager.app and installs it to /Applications
# Run once: bash make_app.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="Life Manager"
APP_BUNDLE="/Applications/${APP_NAME}.app"
PYTHON="${SCRIPT_DIR}/venv/bin/python3"

# Check venv exists
if [ ! -f "$PYTHON" ]; then
    echo "❌ venv not found at $SCRIPT_DIR/venv — run the setup first."
    exit 1
fi

echo "🔨 Building ${APP_NAME}.app..."

# Clean previous build
rm -rf "${APP_BUNDLE}"
mkdir -p "${APP_BUNDLE}/Contents/MacOS"
mkdir -p "${APP_BUNDLE}/Contents/Resources"

# ── Info.plist ──────────────────────────────────────────────────────────────
cat > "${APP_BUNDLE}/Contents/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>      <string>LifeManager</string>
    <key>CFBundleName</key>            <string>Life Manager</string>
    <key>CFBundleDisplayName</key>     <string>Life Manager</string>
    <key>CFBundleIdentifier</key>      <string>com.lifemanager.menubar</string>
    <key>CFBundleVersion</key>         <string>1.0</string>
    <key>CFBundlePackageType</key>     <string>APPL</string>
    <key>CFBundleIconFile</key>        <string>AppIcon</string>
    <key>LSUIElement</key>             <true/>
    <key>NSHighResolutionCapable</key> <true/>
</dict>
</plist>
PLIST

# ── Launcher script ──────────────────────────────────────────────────────────
cat > "${APP_BUNDLE}/Contents/MacOS/LifeManager" << LAUNCHER
#!/bin/bash
exec "${PYTHON}" "${SCRIPT_DIR}/menubar_app.py"
LAUNCHER
chmod +x "${APP_BUNDLE}/Contents/MacOS/LifeManager"

# ── Icon ─────────────────────────────────────────────────────────────────────
TMP_PNG="/tmp/lm_icon_512.png"
"$PYTHON" "${SCRIPT_DIR}/make_icon.py" "$TMP_PNG"

ICONSET="/tmp/LMIcon.iconset"
rm -rf "$ICONSET"
mkdir "$ICONSET"

for SIZE in 16 32 64 128 256 512; do
    sips -z $SIZE $SIZE "$TMP_PNG" \
        --out "${ICONSET}/icon_${SIZE}x${SIZE}.png" > /dev/null
done
# @2x variants
for SIZE in 16 32 64 128 256; do
    S2=$((SIZE * 2))
    sips -z $S2 $S2 "$TMP_PNG" \
        --out "${ICONSET}/icon_${SIZE}x${SIZE}@2x.png" > /dev/null
done

iconutil -c icns "$ICONSET" -o "${APP_BUNDLE}/Contents/Resources/AppIcon.icns"
rm -rf "$ICONSET" "$TMP_PNG"

echo ""
echo "✅ Life Manager.app installed to /Applications"
echo ""
echo "Next steps:"
echo "  1. Open System Settings → General → Login Items"
echo "  2. Click + and add /Applications/Life Manager.app"
echo "  3. Launch it now: open '/Applications/Life Manager.app'"
