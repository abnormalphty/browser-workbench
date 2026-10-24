#!/bin/zsh
# Design snapshots of a built app: seeds fake demo data, then captures every screen in
# light and dark with tests/ui/screens.js. Launches in the background (never takes focus).
# Usage: tests/ui/run_screens.sh "PATH/TO/Browser Workbench.app"
set -uo pipefail
cd -- "${0:A:h}/../.."

APP=${1:A}
RUN=${UI_RUN_DIR:-$HOME/Library/Caches/BrowserWorkbenchBuild/screens/$(date +%Y%m%d-%H%M%S)}
DATA="$RUN/App Data/BrowserWorkbench"
mkdir -p "$RUN/out" "$RUN/logs"
.venv/bin/python tests/ui/seed_demo.py "$DATA" || exit 1
# The app may not read ~/Documents without a privacy prompt; give it a copy.
cp tests/ui/screens.js "$RUN/screens.js"

open -g -n "$APP" \
  --env "BROWSER_WORKBENCH_DATA_DIR=$DATA" --env "BROWSER_WORKBENCH_LOG_DIR=$RUN/logs" \
  --env "BROWSER_WORKBENCH_DOWNLOADS_DIR=$RUN/downloads" \
  --env "BROWSER_WORKBENCH_UI_TEST=$RUN/screens.js" --env "BROWSER_WORKBENCH_UI_TEST_OUT=$RUN/out"
echo "run folder: $RUN"

for _ in {1..900}; do [[ -f $RUN/out/result.json ]] && break; sleep 1; done
binary="$APP/Contents/MacOS/BrowserWorkbench"
for _ in {1..120}; do pgrep -f "$binary" >/dev/null || break; sleep 1; done
cat "$RUN/out/result.json" 2>/dev/null || echo "no result.json"

scope=$(python3 -I -c 'import hashlib,pathlib,sys;print(hashlib.sha256(str(pathlib.Path(sys.argv[1]).resolve()).encode()).hexdigest()[:12])' "$DATA")
docker ps -aq --filter "label=workbench.scope=$scope" | xargs docker rm -f >/dev/null 2>&1
rm -rf "$RUN/App Data"
ls "$RUN/out"
