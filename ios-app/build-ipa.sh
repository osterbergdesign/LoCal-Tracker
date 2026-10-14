#!/usr/bin/env bash
# Builds an unsigned Matkoll.ipa for sideloading tools (SideStore, AltStore, Sideloadly),
# which sign it with your own Apple ID when they install it.
#   HEALTH=0 ./build-ipa.sh     (Apple Health usually can't be signed by these tools)
set -euo pipefail
cd "$(dirname "$0")"

[[ "$(uname)" == "Darwin" ]] || { echo "Run this on your Mac."; exit 1; }
[[ -d ios/App ]] || { echo "No iOS project yet. Run: npm run ios:create"; exit 1; }

HEALTH="${HEALTH:-0}" ./configure-ios.sh
npx cap sync ios

rm -rf build
echo " • Building (takes a few minutes the first time)"
xcodebuild -project ios/App/App.xcodeproj -scheme App -configuration Release \
  -sdk iphoneos -destination 'generic/platform=iOS' \
  -archivePath build/Matkoll.xcarchive archive \
  CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO CODE_SIGN_IDENTITY="" -quiet

mkdir -p build/Payload
cp -R build/Matkoll.xcarchive/Products/Applications/App.app build/Payload/
(cd build && zip -qry Matkoll.ipa Payload)
echo " ✓ Built $(pwd)/build/Matkoll.ipa"
