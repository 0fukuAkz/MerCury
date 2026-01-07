#!/bin/bash
set -e

APP_NAME="MerCury"
DIST_DIR="dist"
APP_BUNDLE="${DIST_DIR}/${APP_NAME}.app"
DMG_NAME="${APP_NAME}-Installer.dmg"
DMG_PATH="${DIST_DIR}/${DMG_NAME}"

# Ensure app bundle exists
if [ ! -d "$APP_BUNDLE" ]; then
    echo "Error: App bundle $APP_BUNDLE not found. Run pyinstaller first."
    exit 1
fi

# Check for existing DMG
rm -f "$DMG_PATH"

echo "Creating DMG using hdiutil..."

hdiutil create \
  -volname "${APP_NAME} Installer" \
  -srcfolder "$APP_BUNDLE" \
  -ov -format UDZO \
  "$DMG_PATH"

echo "DMG created at $DMG_PATH"
