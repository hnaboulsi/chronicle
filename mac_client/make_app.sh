#!/bin/bash
# Builds Life Manager.app and installs it to /Applications
# Run once: bash make_app.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="Life Manager"
APP_BUNDLE="/Applications/${APP_NAME}.app"

# Detect Python version from venv (e.g., python3.13)
PY_VERSION=$(ls "${SCRIPT_DIR}/venv/lib/" | grep '^python' | head -1)
PY_MINOR="${PY_VERSION#python}"
FRAMEWORK_PY="/Library/Frameworks/Python.framework/Versions/${PY_MINOR}/Resources/Python.app/Contents/MacOS/Python"
SITE_PACKAGES="${SCRIPT_DIR}/venv/lib/${PY_VERSION}/site-packages"

if [ ! -d "${SCRIPT_DIR}/venv" ]; then
    echo "❌ venv not found at $SCRIPT_DIR/venv — run the setup first."
    exit 1
fi

if [ ! -f "$FRAMEWORK_PY" ]; then
    echo "❌ Python.app not found at $FRAMEWORK_PY"
    echo "   Make sure Python $PY_MINOR is installed from python.org"
    exit 1
fi

echo "🔨 Building ${APP_NAME}.app..."

# Clean previous build
rm -rf "${APP_BUNDLE}"
mkdir -p "${APP_BUNDLE}/Contents/MacOS"
mkdir -p "${APP_BUNDLE}/Contents/Resources"

# ── Info.plist ───────────────────────────────────────────────────────────────
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

# ── Launcher script ───────────────────────────────────────────────────────────
# Must use Python.app's interpreter (not venv's python3) for window server access.
# PYTHONPATH gives access to all venv packages (rumps, requests, pyobjc).
cat > "${APP_BUNDLE}/Contents/MacOS/LifeManager" << LAUNCHER
#!/bin/bash
export PYTHONPATH="${SITE_PACKAGES}"
LOG_DIR="\$HOME/.local/state/life-manager"
mkdir -p "\$LOG_DIR"
exec "${FRAMEWORK_PY}" "${SCRIPT_DIR}/menubar_app.py" \\
    >> "\$LOG_DIR/menubar.out.log" \\
    2>> "\$LOG_DIR/menubar.err.log"
LAUNCHER
chmod +x "${APP_BUNDLE}/Contents/MacOS/LifeManager"

# ── Icon ──────────────────────────────────────────────────────────────────────
TMP_PNG="/tmp/lm_icon_512.png"
"${FRAMEWORK_PY}" "${SCRIPT_DIR}/make_icon.py" "$TMP_PNG"

ICONSET="/tmp/LMIcon.iconset"
rm -rf "$ICONSET"
mkdir "$ICONSET"

for SIZE in 16 32 64 128 256 512; do
    sips -z $SIZE $SIZE "$TMP_PNG" \
        --out "${ICONSET}/icon_${SIZE}x${SIZE}.png" > /dev/null
done
for SIZE in 16 32 64 128 256; do
    S2=$((SIZE * 2))
    sips -z $S2 $S2 "$TMP_PNG" \
        --out "${ICONSET}/icon_${SIZE}x${SIZE}@2x.png" > /dev/null
done

iconutil -c icns "$ICONSET" -o "${APP_BUNDLE}/Contents/Resources/AppIcon.icns"
rm -rf "$ICONSET" "$TMP_PNG"

# ── Remove old LaunchAgent (replaced by Login Item) ───────────────────────────
LA_PLIST="$HOME/Library/LaunchAgents/com.naboulsi.lifemanager.plist"
if [ -f "$LA_PLIST" ]; then
    launchctl unload "$LA_PLIST" 2>/dev/null || true
    rm "$LA_PLIST"
    echo "ℹ️  Removed old LaunchAgent"
fi

# ── Register as Login Item ─────────────────────────────────────────────────────
# Remove stale entry if exists, then add fresh one
osascript 2>/dev/null << 'AS'
tell application "System Events"
    set appPath to "/Applications/Life Manager.app"
    -- Remove any existing entry
    repeat with li in (get login items)
        if path of li is appPath then
            delete li
        end if
    end repeat
    -- Add fresh entry
    make login item at end with properties {path:appPath, hidden:false}
end tell
AS
echo "✅ Registered as Login Item"

echo ""
echo "✅ Life Manager.app installed to /Applications"
echo "   Opens at login — look for 🧠 in your menu bar."
echo ""
echo "Launch now:"
echo "  open '/Applications/Life Manager.app'"
