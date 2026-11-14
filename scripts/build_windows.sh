#!/bin/zsh
# Assemble the Windows version on a Mac: WebView2 shell (.NET Framework 4.8), bundled Python,
# backend, the x64 browser image and an NSIS installer
#   → dist/Browser-Workbench-VERSION-x64-Setup.exe (+ .sha256)
# Usage: scripts/build_windows.sh [--with-image $BUILD/runtime-image/browser-runtime-x86_64.tar.gz]
# Needs the tools from scripts/fetch_windows_tools.sh. Nothing is signed: Windows SmartScreen
# warns on first launch unless a code-signing certificate is added.
set -euo pipefail
cd -- "${0:A:h}/.."
# Build outputs live outside the project: ~/Documents is synced by iCloud Drive.
BUILD=${BUILD_ROOT:-$HOME/Library/Caches/BrowserWorkbenchBuild}

IMAGE_ARCHIVE=""
while (( $# )); do
  case $1 in
    --with-image) IMAGE_ARCHIVE=$2; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
VERSION=$(sed -n "s/^__version__ = '\(.*\)'/\1/p" workbench/__init__.py)
APP_NAME="Browser Workbench"
W=$BUILD/windows
STAGE=$W/stage/$APP_NAME
SITE=$STAGE/python/Lib/site-packages
DOTNET=$BUILD/tools/dotnet/dotnet
MAKENSIS=$BUILD/tools/nsis-3.11/Bin/makensis
PYTHON_ARCHIVE=$BUILD/downloads/cpython-3.12.15+20261003-x86_64-pc-windows-msvc-install_only_stripped.tar.gz
PYTHON_SHA=6fba7f2ae506facf41d457ea8293c7497910a675c69a4e954875169410a50402
WEBVIEW2_SETUP=$BUILD/downloads/MicrosoftEdgeWebview2Setup.exe
HOST_ARCH=$(uname -m)
[[ -x $BUILD/python/$HOST_ARCH/python/bin/python3 ]] || scripts/fetch_python.sh "$HOST_ARCH"
HOST_PY=$BUILD/python/$HOST_ARCH/python/bin/python3
[[ -x $DOTNET && -x $MAKENSIS && -f $PYTHON_ARCHIVE ]] || { echo "missing build tools: run scripts/fetch_windows_tools.sh" >&2; exit 1; }
[[ $(shasum -a 256 "$PYTHON_ARCHIVE" | cut -d' ' -f1) == "$PYTHON_SHA" ]] || { echo "checksum mismatch: $PYTHON_ARCHIVE" >&2; exit 1; }
export DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1 DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1

echo "==> $APP_NAME $VERSION (Windows x64)"
rm -rf "$W/stage" "$W/shell-src" "$W/shell" "$W/icon"
mkdir -p "$STAGE" "$W/shell-src" "$W/icon"

echo "--> icon"
[[ -f $BUILD/icon/AppIcon-1024.png ]] || { mkdir -p $BUILD/icon; xcrun swift macos/make_icon.swift $BUILD/icon/AppIcon-1024.png; }
sizes=(16 20 24 32 40 48 64 96 128 256)
for size in $sizes; do sips -z $size $size $BUILD/icon/AppIcon-1024.png --out "$W/icon/$size.png" >/dev/null; done
"$HOST_PY" scripts/make_ico.py "$W/shell-src/app.ico" "$W/icon/"${^sizes}.png

echo "--> window shell (.NET Framework 4.8 + WebView2)"
# Built from a copy: dotnet writes obj/ and bin/ beside the project, which sits in iCloud.
cp windows/*.cs windows/BrowserWorkbench.csproj windows/app.manifest windows/App.config "$W/shell-src/"
"$DOTNET" publish "$W/shell-src/BrowserWorkbench.csproj" -c Release -o "$W/shell" -p:Version="$VERSION" --nologo -v quiet
ditto "$W/shell" "$STAGE"
cp "$W/shell-src/app.ico" "$STAGE/app.ico"
# Licenses that ask to travel with the binaries (WebView2 SDK: BSD-style; the installer: NSIS).
WEBVIEW2_VERSION=$(sed -n 's/.*Include="Microsoft.Web.WebView2" Version="\([^"]*\)".*/\1/p' windows/BrowserWorkbench.csproj)
mkdir -p "$STAGE/licenses"
cp "$HOME/.nuget/packages/microsoft.web.webview2/$WEBVIEW2_VERSION/LICENSE.txt" "$STAGE/licenses/WebView2-SDK.txt"
cp "$BUILD/tools/nsis-3.11/COPYING" "$STAGE/licenses/NSIS.txt"

echo "--> python runtime and pinned dependencies"
rm -rf "$W/python" && mkdir -p "$W/python"
tar -xzf "$PYTHON_ARCHIVE" -C "$W/python"
ditto "$W/python/python" "$STAGE/python"
# Windows wheels, fetched without running a Windows interpreter.
"$HOST_PY" -m pip install --quiet --disable-pip-version-check --no-compile --only-binary=:all: \
  --platform win_amd64 --python-version 3.12 --implementation cp --target "$SITE" -r requirements.txt
# Not needed at run time: packaging tools, headers, GUI toolkit, test suites, and the console-script
# wrappers pip writes for the build machine's interpreter (the app uses `python -m`).
rm -rf "$SITE"/bin "$SITE"/pip "$SITE"/pip-* "$STAGE/python/"{Scripts,include,libs,tcl} \
  "$STAGE/python/Lib/"{ensurepip,idlelib,tkinter,turtledemo,test} "$STAGE/python/DLLs/"{_tkinter.pyd,tcl86t.dll,tk86t.dll}

echo "--> backend sources (whitelist)"
B=$STAGE/backend
mkdir -p "$B/workbench" "$B/static" "$B/runtime"
cp workbench/*.py "$B/workbench/"
cp static/{index.html,app.js,gateway.js,style.css,clipboard-bridge.js,world.svg} "$B/static/"
mkdir -p "$B/static/vendor/xterm"
cp static/vendor/xterm/{xterm.mjs,addon-fit.mjs,xterm.css,LICENSE.txt} "$B/static/vendor/xterm/"
cp runtime/{Dockerfile,.dockerignore,apt-install.sh,entrypoint.py,browser.py,native_firefox.py,desktop_clipboard.py,account_info.py,welcome.html} "$B/runtime/"
cp requirements.txt THIRD_PARTY_NOTICES.md "$B/"

echo "--> bytecode (same Python version on both systems)"
"$HOST_PY" -m compileall -q -j 0 --invalidation-mode unchecked-hash -s "$STAGE/" "$B" "$STAGE/python/Lib"

if [[ -n $IMAGE_ARCHIVE ]]; then
  echo "--> bundled browser image (x64)"
  mkdir -p "$STAGE/runtime-image"
  cp "$IMAGE_ARCHIVE" "$STAGE/runtime-image/browser-runtime.tar.gz"
  manifest=${IMAGE_ARCHIVE%.tar.gz}.manifest.txt
  [[ -f $manifest ]] && cp "$manifest" "$STAGE/runtime-image/manifest.txt"
fi

echo "--> privacy check"
"$HOST_PY" scripts/check_bundle.py "$STAGE"

echo "--> WebView2 bootstrapper (installed only where the runtime is missing)"
[[ -f $WEBVIEW2_SETUP ]] || curl -fL --retry 3 -o "$WEBVIEW2_SETUP" 'https://go.microsoft.com/fwlink/p/?LinkId=2124703'
shasum -a 256 "$WEBVIEW2_SETUP"

echo "--> installer"
mkdir -p dist
OUT=dist/Browser-Workbench-$VERSION-x64-Setup.exe
# makensis converts text with the locale's character set; a shell without one makes it crash.
LC_ALL=en_US.UTF-8 "$MAKENSIS" -V2 -INPUTCHARSET UTF8 "-DVERSION=$VERSION" "-DSOURCE=$STAGE" "-DICON=$W/shell-src/app.ico" \
  "-DWEBVIEW2_SETUP=$WEBVIEW2_SETUP" "-DOUTFILE=$PWD/$OUT" windows/installer.nsi
(cd dist && shasum -a 256 "${OUT:t}" > "${OUT:t}.sha256")
ls -lh "$OUT"
cat "$OUT.sha256"
