#!/bin/zsh
# Assemble 境工作台.app: Swift shell + bundled Python + backend + (optional) browser image.
# Usage: scripts/build_app.sh [arm64|x86_64] [--with-image $BUILD/runtime-image/browser-runtime-ARCH.tar.gz]
# Signs ad hoc unless SIGN_IDENTITY names a Developer ID certificate.
set -euo pipefail
cd -- "${0:A:h}/.."
# Build outputs live outside the project: ~/Documents is synced by iCloud Drive,
# which would upload hundreds of MB and stamps Finder info that codesign rejects.
BUILD=${BUILD_ROOT:-$HOME/Library/Caches/BrowserWorkbenchBuild}

ARCH=${1:-$(uname -m)}
(( $# )) && shift
IMAGE_ARCHIVE=""
while (( $# )); do
  case $1 in
    --with-image) IMAGE_ARCHIVE=$2; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
HOST_ARCH=$(uname -m)
VERSION=$(sed -n "s/^__version__ = '\(.*\)'/\1/p" workbench/__init__.py)
APP_NAME=境工作台
APP=$BUILD/app/$ARCH/$APP_NAME.app
C=$APP/Contents
R=$C/Resources
SITE=$R/python/lib/python3.12/site-packages
IDENTITY=${SIGN_IDENTITY:--}

[[ -x $BUILD/python/$ARCH/python/bin/python3 ]] || scripts/fetch_python.sh "$ARCH"
[[ -x $BUILD/python/$HOST_ARCH/python/bin/python3 ]] || scripts/fetch_python.sh "$HOST_ARCH"
HOST_PY=$BUILD/python/$HOST_ARCH/python/bin/python3

echo "==> $APP_NAME $VERSION ($ARCH)"
rm -rf "$APP"
mkdir -p "$C/MacOS" "$R"

echo "--> native shell"
# ConciseMagicFile keeps this machine's source paths out of the binary.
xcrun swiftc -swift-version 5 -enable-upcoming-feature ConciseMagicFile -O \
  -target "$ARCH-apple-macos13.0" -sdk "$(xcrun --show-sdk-path)" \
  macos/Sources/*.swift -o "$C/MacOS/BrowserWorkbench"
sed "s/__VERSION__/$VERSION/g" macos/Info.plist > "$C/Info.plist"
plutil -lint -s "$C/Info.plist"
printf 'APPL????' > "$C/PkgInfo"

echo "--> icon"
if [[ ! -f $BUILD/icon/AppIcon.icns || macos/make_icon.swift -nt $BUILD/icon/AppIcon.icns ]]; then
  rm -rf $BUILD/icon && mkdir -p $BUILD/icon/AppIcon.iconset
  xcrun swift macos/make_icon.swift $BUILD/icon/AppIcon-1024.png
  for size in 16 32 128 256 512; do
    sips -z $size $size $BUILD/icon/AppIcon-1024.png --out "$BUILD/icon/AppIcon.iconset/icon_${size}x${size}.png" >/dev/null
    sips -z $((size*2)) $((size*2)) $BUILD/icon/AppIcon-1024.png --out "$BUILD/icon/AppIcon.iconset/icon_${size}x${size}@2x.png" >/dev/null
  done
  iconutil -c icns $BUILD/icon/AppIcon.iconset -o $BUILD/icon/AppIcon.icns
fi
cp $BUILD/icon/AppIcon.icns "$R/AppIcon.icns"

echo "--> python runtime and pinned dependencies"
ditto "$BUILD/python/$ARCH/python" "$R/python"
if [[ $ARCH == "$HOST_ARCH" ]]; then
  "$R/python/bin/python3" -m pip install --quiet --disable-pip-version-check --no-compile --only-binary=:all: -r requirements.txt
else
  # Cross build: fetch the wheels for the other chip without running its interpreter.
  "$HOST_PY" -m pip install --quiet --disable-pip-version-check --no-compile --only-binary=:all: \
    --platform "macosx_11_0_$ARCH" --python-version 3.12 --implementation cp --target "$SITE" -r requirements.txt
fi
# Not needed at run time: packaging tools, GUI toolkit, test suites.
rm -rf "$SITE"/pip "$SITE"/pip-* "$R/python/share" "$R/python/include" \
  "$R/python/lib/python3.12/"{ensurepip,idlelib,tkinter,turtledemo,test} \
  "$R/python/lib/"{tcl,tk,itcl,thread}*(N) "$R/python/lib/python3.12/lib-dynload/"_tkinter*(N)
# Zero-byte placeholders pick up Finder info on the DMG's file system and break strict verification.
find "$R/python" -name '.empty' -size 0 -delete
# Console-script wrappers carry this machine's interpreter path; the app uses `python -m`.
for entry in "$R/python/bin/"*(N); do
  case ${entry:t} in python|python3|python3.12) ;; *) rm -f "$entry" ;; esac
done

echo "--> backend sources (whitelist)"
B=$R/backend
mkdir -p "$B/workbench" "$B/static" "$B/runtime"
cp workbench/*.py "$B/workbench/"
cp static/{index.html,app.js,style.css,clipboard-bridge.js,world.svg} "$B/static/"
cp runtime/{Dockerfile,.dockerignore,entrypoint.py,browser.py,native_firefox.py,desktop_clipboard.py,account_info.py,welcome.html} "$B/runtime/"
cp requirements.txt THIRD_PARTY_NOTICES.md "$B/"

echo "--> bytecode (the signed bundle is never written to at run time)"
"$HOST_PY" -m compileall -q -j 0 --invalidation-mode unchecked-hash -s "$R/" "$B" "$SITE"

if [[ -n $IMAGE_ARCHIVE ]]; then
  echo "--> bundled browser image"
  mkdir -p "$R/runtime-image"
  cp "$IMAGE_ARCHIVE" "$R/runtime-image/browser-runtime.tar.gz"
  manifest=${IMAGE_ARCHIVE%.tar.gz}.manifest.txt
  [[ -f $manifest ]] && cp "$manifest" "$R/runtime-image/manifest.txt"
fi

echo "--> privacy check"
"$HOST_PY" scripts/check_bundle.py "$APP"

echo "--> code signature ($([[ $IDENTITY == - ]] && echo ad-hoc || echo "$IDENTITY"))"
# Extended attributes (Finder info, provenance) make codesign refuse the bundle.
xattr -cr "$APP"
find "$R/python" -type f \( -perm -u+x -o -name '*.so' -o -name '*.dylib' \) -print0 |
  while IFS= read -r -d '' file; do
    if file -b "$file" | grep -q 'Mach-O'; then codesign -f -s "$IDENTITY" --timestamp=none "$file" 2>/dev/null; fi
  done
codesign -f -s "$IDENTITY" --timestamp=none "$APP"
codesign --verify --deep --strict "$APP"

du -sh "$APP" | sed 's/^/size: /'
echo "built: $APP"
