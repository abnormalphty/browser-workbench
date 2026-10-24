#!/bin/zsh
# Download the relocatable CPython that ships inside the app, verified by SHA-256.
# Usage: scripts/fetch_python.sh [arm64|x86_64]   → $BUILD/python/<arch>/python
set -euo pipefail
cd -- "${0:A:h}/.."
# Build outputs live outside the project: ~/Documents is synced by iCloud Drive,
# which would upload hundreds of MB and stamps Finder info that codesign rejects.
BUILD=${BUILD_ROOT:-$HOME/Library/Caches/BrowserWorkbenchBuild}

ARCH=${1:-$(uname -m)}
RELEASE=20261003
VERSION=3.12.15
case $ARCH in
  arm64)  TRIPLE=aarch64-apple-darwin; SHA=ad8d0c637c0a36b967b310e2c07254f4d2ca8cabaa7699e55ed6290aceb481a2 ;;
  x86_64) TRIPLE=x86_64-apple-darwin;  SHA=562c30864ece2cb1d3e0ad66a1acd498611a47e5a10ce81b99158bef1ccbd355 ;;
  *) echo "unsupported architecture: $ARCH" >&2; exit 2 ;;
esac

NAME="cpython-${VERSION}+${RELEASE}-${TRIPLE}-install_only_stripped.tar.gz"
CACHE=$BUILD/downloads/$NAME
DEST=$BUILD/python/$ARCH
mkdir -p $BUILD/downloads $BUILD/python

if [[ ! -f $CACHE ]] || [[ $(shasum -a 256 "$CACHE" | cut -d' ' -f1) != "$SHA" ]]; then
  echo "Downloading $NAME"
  curl -fL --retry 3 -o "$CACHE.part" "https://github.com/astral-sh/python-build-standalone/releases/download/${RELEASE}/${NAME}"
  mv "$CACHE.part" "$CACHE"
fi
if [[ $(shasum -a 256 "$CACHE" | cut -d' ' -f1) != "$SHA" ]]; then
  echo "checksum mismatch for $NAME" >&2
  rm -f "$CACHE"
  exit 1
fi

rm -rf "$DEST"
mkdir -p "$DEST"
tar -xzf "$CACHE" -C "$DEST"
"$DEST/python/bin/python3" -c 'import sys,ssl,sqlite3,lzma; print(sys.version.split()[0], sys.platform, ssl.OPENSSL_VERSION)'
