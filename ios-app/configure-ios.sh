#!/usr/bin/env bash
# Applies Matkoll's settings to the Xcode project that `npx cap add ios` generates:
# permission texts, Apple Health entitlement, network access, icon, splash and build number.
# Safe to run again; npm run ios:sync runs it for you.
set -euo pipefail
cd "$(dirname "$0")"

APP_DIR=ios/App/App
PLIST=$APP_DIR/Info.plist
PBX=ios/App/App.xcodeproj/project.pbxproj
ENT=$APP_DIR/App.entitlements

[[ "$(uname)" == "Darwin" ]] || { echo "Run this on your Mac."; exit 1; }
[[ -f $PLIST && -f $PBX ]] || { echo "No iOS project yet. Run: npm run ios:create"; exit 1; }

say() { echo " • $*"; }

say "Permission texts and network access"
set_text() { plutil -replace "$1" -string "$2" "$PLIST"; }
set_text CFBundleDisplayName "Matkoll"
set_text NSCameraUsageDescription "Matkoll uses the camera to scan barcodes and to photograph meals."
set_text NSPhotoLibraryUsageDescription "Matkoll lets you pick a meal photo from your library to estimate its calories."
set_text NSHealthShareUsageDescription "Matkoll can save your logged calories and macros to Apple Health."
set_text NSHealthUpdateUsageDescription "Matkoll saves your logged calories, protein, carbohydrates, fat and fibre to Apple Health."
set_text NSLocalNetworkUsageDescription "Matkoll connects to your own Matkoll server on your home network."
# Your server is usually plain http:// on the home network, which iOS blocks unless allowed.
plutil -replace NSAppTransportSecurity -json '{"NSAllowsArbitraryLoads":true,"NSAllowsLocalNetworking":true}' "$PLIST"

say "Apple Health entitlement"
cat >"$ENT" <<'XML'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>com.apple.developer.healthkit</key>
	<true/>
	<key>com.apple.developer.healthkit.access</key>
	<array/>
</dict>
</plist>
XML
if ! grep -q "CODE_SIGN_ENTITLEMENTS = App/App.entitlements" "$PBX"; then
  perl -0pi -e 's/(\t+)(INFOPLIST_FILE = App\/Info\.plist;)/$1$2\n$1CODE_SIGN_ENTITLEMENTS = App\/App.entitlements;/g' "$PBX"
fi

say "Build number"
# TestFlight needs a higher build number for every upload; a timestamp always is.
BUILD="$(date +%Y%m%d%H%M)"
perl -pi -e "s/CURRENT_PROJECT_VERSION = [^;]+;/CURRENT_PROJECT_VERSION = $BUILD;/g" "$PBX"

say "Icon and splash screen"
ICONSET=$APP_DIR/Assets.xcassets/AppIcon.appiconset
SPLASH=$APP_DIR/Assets.xcassets/Splash.imageset
resize_into() { # resize_into <source png> <folder>
  local src="$1" dir="$2" f w h
  [[ -d $dir ]] || return 0
  for f in "$dir"/*.png; do
    [[ -e $f ]] || continue
    w=$(sips -g pixelWidth "$f" | awk '/pixelWidth/ {print $2}')
    h=$(sips -g pixelHeight "$f" | awk '/pixelHeight/ {print $2}')
    sips -z "$h" "$w" "$src" --out "$f" >/dev/null
  done
}
resize_into assets/icon-1024.png "$ICONSET"
resize_into assets/splash-2732.png "$SPLASH"

echo " ✓ iOS project configured (build $BUILD)"
