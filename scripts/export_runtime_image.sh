#!/bin/zsh
# Export the browser runtime image so the app can `docker load` it offline.
# Usage: scripts/export_runtime_image.sh [arm64] [--rebuild]
#   → $BUILD/runtime-image/browser-runtime-ARCH.tar.gz (+ .sha256, .manifest.txt)
# Only the host architecture is supported: one local tag can hold one platform.
set -euo pipefail
cd -- "${0:A:h}/.."
# Build outputs live outside the project: ~/Documents is synced by iCloud Drive,
# which would upload hundreds of MB and stamps Finder info that codesign rejects.
BUILD=${BUILD_ROOT:-$HOME/Library/Caches/BrowserWorkbenchBuild}

ARCH=${1:-$(uname -m)}
REBUILD=${2:-}
[[ $ARCH == $(uname -m) ]] || { echo "export runs on a $ARCH Mac (this is $(uname -m))" >&2; exit 2; }
PLATFORM=linux/$ARCH
VERSION=$(sed -n "s/^RUNTIME_VERSION = '\(.*\)'/\1/p" workbench/runtime.py)
TAG=local-browser-workbench:$VERSION
OUT=$BUILD/runtime-image
mkdir -p "$OUT" $BUILD/logs

if [[ $REBUILD == --rebuild ]] || ! docker image inspect "$TAG" >/dev/null 2>&1; then
  echo "--> building $TAG"
  docker build --platform "$PLATFORM" -t "$TAG" runtime/ | tee $BUILD/logs/image-build-$ARCH.log
fi
actual=$(docker image inspect -f '{{.Architecture}}' "$TAG")
[[ $actual == "$ARCH" || ($ARCH == x86_64 && $actual == amd64) ]] || { echo "$TAG is $actual, expected $ARCH" >&2; exit 1; }
label=$(docker image inspect -f '{{index .Config.Labels "workbench.runtime"}}' "$TAG")
[[ $label == "$VERSION" ]] || { echo "$TAG carries runtime label '$label', expected $VERSION" >&2; exit 1; }

echo "--> manifest"
docker run --rm --platform "$PLATFORM" --entrypoint sh "$TAG" -c \
  'echo "image: '"$TAG"'"; firefox-esr --version 2>/dev/null; mihomo -v 2>/dev/null | head -1; python --version; echo; echo "Debian packages:"; dpkg-query -W -f="\${Package} \${Version}\n"' \
  > "$OUT/browser-runtime-$ARCH.manifest.txt"
head -4 "$OUT/browser-runtime-$ARCH.manifest.txt"

echo "--> saving and compressing (a few minutes)"
docker save "$TAG" | gzip -6 > "$OUT/browser-runtime-$ARCH.tar.gz.part"
mv "$OUT/browser-runtime-$ARCH.tar.gz.part" "$OUT/browser-runtime-$ARCH.tar.gz"
(cd "$OUT" && shasum -a 256 "browser-runtime-$ARCH.tar.gz" > "browser-runtime-$ARCH.tar.gz.sha256")
ls -lh "$OUT/browser-runtime-$ARCH.tar.gz"
