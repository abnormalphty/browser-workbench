#!/bin/zsh
# Wrap a built app into a drag-to-install DMG.
# Usage: scripts/make_dmg.sh [arm64|x86_64]   → dist/境工作台-VERSION-ARCH.dmg
set -euo pipefail
cd -- "${0:A:h}/.."
# Build outputs live outside the project: ~/Documents is synced by iCloud Drive,
# which would upload hundreds of MB and stamps Finder info that codesign rejects.
BUILD=${BUILD_ROOT:-$HOME/Library/Caches/BrowserWorkbenchBuild}

ARCH=${1:-$(uname -m)}
VERSION=$(sed -n "s/^__version__ = '\(.*\)'/\1/p" workbench/__init__.py)
APP_NAME=境工作台
APP=$BUILD/app/$ARCH/$APP_NAME.app
STAGE=$BUILD/dmg/$ARCH
DMG=dist/$APP_NAME-$VERSION-$ARCH.dmg
[[ -d $APP ]] || { echo "build the app first: scripts/build_app.sh $ARCH" >&2; exit 1; }
codesign --verify --deep --strict "$APP"

rm -rf "$STAGE" && mkdir -p "$STAGE" dist
ditto "$APP" "$STAGE/$APP_NAME.app"
ln -s /Applications "$STAGE/应用程序"
sed "s/__VERSION__/$VERSION/g" packaging/安装说明.txt > "$STAGE/安装说明.txt"

rm -f "$DMG"
hdiutil create -quiet -volname "$APP_NAME $VERSION" -srcfolder "$STAGE" -fs HFS+ -format UDZO -imagekey zlib-level=6 "$DMG"
hdiutil verify -quiet "$DMG"
# Check the copy a user will drag out, not just the one we built.
MOUNT=$(mktemp -d "${TMPDIR:-/tmp}/bw-dmg.XXXXXX")
hdiutil attach -quiet -nobrowse -readonly -mountpoint "$MOUNT" "$DMG"
codesign --verify --deep --strict "$MOUNT/$APP_NAME.app" && verified=1 || verified=0
hdiutil detach -quiet "$MOUNT" && rmdir "$MOUNT"
(( verified )) || { echo "app inside the DMG fails strict signature verification" >&2; exit 1; }
(cd dist && shasum -a 256 "${DMG:t}" > "${DMG:t}.sha256")
ls -lh "$DMG"
cat "$DMG.sha256"
