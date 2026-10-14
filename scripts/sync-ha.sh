#!/usr/bin/env bash
# Copies the app into the Home Assistant integration, which HACS installs on its own.
# Run after changing anything in app/ (CI checks that the copy is up to date).
set -euo pipefail
cd "$(dirname "$0")/.."
DEST=custom_components/matkoll/matkoll_app
VERSION="$(python3 -c "import json;print(json.load(open('custom_components/matkoll/manifest.json'))['version'])")"
rm -rf "$DEST"
mkdir -p "$DEST"
tar -C app --exclude='__pycache__' --exclude='*.pyc' --exclude='static/vendor' -cf - . | tar -C "$DEST" -xf -
# Bust browser caches inside Home Assistant when the version changes.
sed -i.bak -e "s#href=\"app.css\"#href=\"app.css?v=$VERSION\"#" -e "s#src=\"app.js\"#src=\"app.js?v=$VERSION\"#" "$DEST/static/ha.html"
rm -f "$DEST/static/ha.html.bak"
echo "Synced app/ into $DEST (v$VERSION)"
