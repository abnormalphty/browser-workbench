#!/bin/zsh
# Tools for building the Windows version on a Mac, all under the build cache (no admin rights,
# nothing installed system-wide): the .NET SDK (compiles the WebView2 shell for Windows), NSIS's
# makensis (makes the Windows installer) and the Windows Python, checked against a pinned SHA-256.
# Usage: scripts/fetch_windows_tools.sh   → $BUILD/tools/{dotnet,nsis-3.11}, $BUILD/downloads
set -euo pipefail
BUILD=${BUILD_ROOT:-$HOME/Library/Caches/BrowserWorkbenchBuild}
TOOLS=$BUILD/tools
mkdir -p $TOOLS $BUILD/downloads

echo "==> Windows Python (python-build-standalone 3.12.15, same build as the Mac app)"
NAME='cpython-3.12.15+20261003-x86_64-pc-windows-msvc-install_only_stripped.tar.gz'
SHA=6fba7f2ae506facf41d457ea8293c7497910a675c69a4e954875169410a50402
CACHE=$BUILD/downloads/$NAME
[[ -f $CACHE && $(shasum -a 256 $CACHE | cut -d' ' -f1) == $SHA ]] || curl -fL --retry 3 -o $CACHE "https://github.com/astral-sh/python-build-standalone/releases/download/20261003/$NAME"
[[ $(shasum -a 256 $CACHE | cut -d' ' -f1) == $SHA ]] && echo "python checksum ok"

echo "==> .NET SDK 10 (user-local), checked against the SHA-512 Microsoft publishes"
if [[ ! -x $TOOLS/dotnet/dotnet ]]; then
  cd $BUILD/downloads
  curl -fsSL --retry 5 -o releases-10.0.json https://dotnetcli.blob.core.windows.net/dotnet/release-metadata/10.0/releases.json
  read -r URL HASH < <(python3 -I -c '
import json
release = json.load(open("releases-10.0.json"))["releases"][0]
file = next(f for f in release["sdk"]["files"] if f["rid"] == "osx-arm64" and f["name"].endswith(".tar.gz"))
print(file["url"].replace("https://builds.dotnet.microsoft.com/", "https://dotnetcli.blob.core.windows.net/"), file["hash"])')
  curl -fL -C - --retry 10 --retry-delay 3 -o ${URL:t} "$URL"
  [[ $(shasum -a 512 ${URL:t} | cut -d' ' -f1) == $HASH ]] || { echo "checksum mismatch: ${URL:t}" >&2; exit 1; }
  rm -rf $TOOLS/dotnet && mkdir -p $TOOLS/dotnet && tar -xzf ${URL:t} -C $TOOLS/dotnet
fi
DOTNET_CLI_TELEMETRY_OPTOUT=1 $TOOLS/dotnet/dotnet --version

echo "==> NSIS 3.11: makensis built here, Windows stubs and plugins from the official zip"
NSIS=$TOOLS/nsis-3.11
# makensis expects its data (Stubs, Plugins, Include) one level above its Bin folder.
if [[ ! -x $NSIS/Bin/makensis ]]; then
  cd $BUILD/downloads
  [[ -f nsis-3.11-src.tar.bz2 ]] || curl -fL --retry 3 -o nsis-3.11-src.tar.bz2 'https://downloads.sourceforge.net/project/nsis/NSIS%203/3.11/nsis-3.11-src.tar.bz2'
  [[ -f nsis-3.11.zip ]] || curl -fL --retry 3 -o nsis-3.11.zip 'https://downloads.sourceforge.net/project/nsis/NSIS%203/3.11/nsis-3.11.zip'
  shasum -a 256 nsis-3.11-src.tar.bz2 nsis-3.11.zip
  rm -rf $NSIS $TOOLS/nsis-src
  ditto -x -k nsis-3.11.zip $TOOLS
  mkdir -p $TOOLS/nsis-src && tar -xjf nsis-3.11-src.tar.bz2 -C $TOOLS/nsis-src --strip-components 1
  [[ -x $TOOLS/scons-venv/bin/scons ]] || { python3 -m venv $TOOLS/scons-venv && $TOOLS/scons-venv/bin/pip install -q scons; }
  cd $TOOLS/nsis-src
  $TOOLS/scons-venv/bin/scons -Q SKIPSTUBS=all SKIPPLUGINS=all SKIPUTILS=all SKIPMISC=all SKIPDOC=all \
    NSIS_CONFIG_CONST_DATA_PATH=no VERSION=3.11 VER_MAJOR=3 VER_MINOR=11 VER_REVISION=0 VER_BUILD=0 makensis 2>&1 | tail -3
  cp build/urelease/makensis/makensis $NSIS/Bin/makensis
fi
# makensis converts text with the locale's character set; a shell without one makes it crash.
LC_ALL=en_US.UTF-8 $NSIS/Bin/makensis -VERSION
