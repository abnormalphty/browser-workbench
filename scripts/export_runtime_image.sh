#!/bin/zsh
# Export the browser runtime image so the app can `docker load` it offline.
# Usage: scripts/export_runtime_image.sh [arm64|x86_64] [--rebuild]
#   → $BUILD/runtime-image/browser-runtime-ARCH.tar.gz (+ .sha256, .manifest.txt)
# The host architecture is built into the local image store (the Mac app's own image).
# Another one (x86_64 for Windows PCs, on an Apple-silicon Mac) is built under emulation
# straight into the archive, so the local tag keeps holding this Mac's image.
set -euo pipefail
cd -- "${0:A:h}/.."
# Build outputs live outside the project: ~/Documents is synced by iCloud Drive,
# which would upload hundreds of MB and stamps Finder info that codesign rejects.
BUILD=${BUILD_ROOT:-$HOME/Library/Caches/BrowserWorkbenchBuild}

ARCH=${1:-$(uname -m)}
REBUILD=${2:-}
case $ARCH in arm64) PLATFORM=linux/arm64 ;; x86_64) PLATFORM=linux/amd64 ;; *) echo "unsupported architecture: $ARCH" >&2; exit 2 ;; esac
VERSION=$(sed -n "s/^RUNTIME_VERSION = '\(.*\)'/\1/p" workbench/runtime.py)
TAG=local-browser-workbench:$VERSION
OUT=$BUILD/runtime-image
LOG=$BUILD/logs/image-build-$ARCH.log
mkdir -p "$OUT" $BUILD/logs
: > "$LOG"

# A flaky proxy resets registry and package-mirror connections now and then. Finished steps stay
# in BuildKit's cache, so another try only redoes what failed (often just the registry lookup).
build() {
  local try
  for try in 1 2 3 4 5; do
    "$@" 2>&1 | tee -a "$LOG" && return 0
    (( try < 5 )) || { echo "build failed 5 times; see $LOG" >&2; return 1; }
    echo "--> build failed (try $try of 5), trying again in 30 s"
    sleep 30
  done
}

if [[ $ARCH != $(uname -m) ]]; then
  STAGING=local-browser-workbench:staging-$ARCH
  echo "--> building $TAG for $PLATFORM under emulation (slow)"
  build docker buildx build --platform "$PLATFORM" -t "$TAG" --output "type=docker,dest=$OUT/browser-runtime-$ARCH.tar" runtime/
  # Same build from the cache, under a temporary tag, only to read its versions.
  build docker buildx build --platform "$PLATFORM" -t "$STAGING" --load runtime/ >/dev/null
  label=$(docker image inspect -f '{{index .Config.Labels "workbench.runtime"}}' "$STAGING")
  [[ $label == "$VERSION" ]] || { echo "$TAG carries runtime label '$label', expected $VERSION" >&2; exit 1; }
  echo "--> manifest"
  docker run --rm --platform "$PLATFORM" --entrypoint sh "$STAGING" -c \
    'echo "image: '"$TAG ($PLATFORM)"'"; firefox-esr --version 2>/dev/null; mihomo -v 2>/dev/null | head -1; python --version; echo; echo "Debian packages:"; dpkg-query -W -f="\${Package} \${Version}\n"' \
    > "$OUT/browser-runtime-$ARCH.manifest.txt"
  docker rmi "$STAGING" >/dev/null
  head -4 "$OUT/browser-runtime-$ARCH.manifest.txt"
  echo "--> compressing"
  gzip -6 < "$OUT/browser-runtime-$ARCH.tar" > "$OUT/browser-runtime-$ARCH.tar.gz.part"
  rm "$OUT/browser-runtime-$ARCH.tar"
  mv "$OUT/browser-runtime-$ARCH.tar.gz.part" "$OUT/browser-runtime-$ARCH.tar.gz"
  (cd "$OUT" && shasum -a 256 "browser-runtime-$ARCH.tar.gz" > "browser-runtime-$ARCH.tar.gz.sha256")
  ls -lh "$OUT/browser-runtime-$ARCH.tar.gz"
  exit 0
fi

if [[ $REBUILD == --rebuild ]] || ! docker image inspect "$TAG" >/dev/null 2>&1; then
  echo "--> building $TAG"
  build docker build --platform "$PLATFORM" -t "$TAG" runtime/
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
