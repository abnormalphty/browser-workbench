#!/bin/zsh
# End-to-end smoke test of a built 境工作台.app with disposable data.
# Launches the app through LaunchServices (like a double-click), runs tests/ui/app_smoke.js
# inside its window, then checks quit, the backend, the container and the files on disk.
# Usage: tests/ui/run_app_smoke.sh PATH/TO/境工作台.app
# Needs Docker. Uses the Mac clipboard during the run (restores its text afterwards).
set -uo pipefail
cd -- "${0:A:h}/../.."

APP=${1:A}
RUN=${UI_RUN_DIR:-$HOME/Library/Caches/BrowserWorkbenchBuild/ui-run/$(date +%Y%m%d-%H%M%S)}
DATA="$RUN/App Data/BrowserWorkbench"   # contains a space, like "Application Support"
mkdir -p "$RUN/out" "$RUN/logs" "$RUN/downloads" "$DATA"

python3 -I tests/ui/fixture_server.py "$RUN/out" &
FIXTURE=$!
trap 'kill $FIXTURE 2>/dev/null' EXIT
for _ in {1..50}; do [[ -f $RUN/out/port ]] && break; sleep 0.2; done
sed "s#__FIXTURE__#http://host.docker.internal:$(<$RUN/out/port)#g" tests/ui/app_smoke.js > "$RUN/app_smoke.js"

# -g: launch in the background; typing elsewhere must not reach the test window.
open -g -n "$APP" \
  --env "BROWSER_WORKBENCH_DATA_DIR=$DATA" --env "BROWSER_WORKBENCH_LOG_DIR=$RUN/logs" \
  --env "BROWSER_WORKBENCH_DOWNLOADS_DIR=$RUN/downloads" \
  --env "BROWSER_WORKBENCH_UI_TEST=$RUN/app_smoke.js" --env "BROWSER_WORKBENCH_UI_TEST_OUT=$RUN/out"
echo "launched $APP"
echo "run folder: $RUN"

for _ in {1..1500}; do [[ -f $RUN/out/result.json ]] && break; sleep 1; done
[[ -f $RUN/out/result.json ]] || { echo "no result.json after 25 minutes"; exit 1; }

# The script ends by asking the app to stop its environments and quit.
binary="$APP/Contents/MacOS/BrowserWorkbench"
for _ in {1..120}; do pgrep -f "$binary" >/dev/null || break; sleep 1; done

scope=$(python3 -I -c 'import hashlib,pathlib,sys;print(hashlib.sha256(str(pathlib.Path(sys.argv[1]).resolve()).encode()).hexdigest()[:12])' "$DATA")
python3 -I - "$RUN" "$scope" "$binary" "$DATA" <<'EOF'
import json, subprocess, sys
from pathlib import Path
run, scope, binary, data = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
report = json.loads((run/'out/result.json').read_text())
result = report.get('result') or {}
checks = [(s['name'], s['ok'], s.get('detail', '')) for s in result.get('steps', [])]
marker = next((s['detail'] for s in result.get('steps', []) if s['name'] == 'paste marker'), None)
received = (run/'out/received.txt').read_text() if (run/'out/received.txt').exists() else None
checks.append(('pasted text arrived in the remote page', received == marker, received))
saved = run/'downloads/下载测试.txt'
checks.append(('downloaded file is byte-identical', saved.exists() and saved.read_bytes() == (run/'out/download-expected.txt').read_bytes(), saved))
checks.append(('app process exited after quit', subprocess.run(['pgrep', '-f', binary], capture_output=True).returncode != 0, ''))
checks.append(('backend process exited with the app', subprocess.run(['pgrep', '-f', 'workbench.desktop --data-dir ' + data], capture_output=True).returncode != 0, ''))
states = subprocess.run(['docker', 'ps', '-a', '--filter', f'label=workbench.scope={scope}', '--format', '{{.State}}'], capture_output=True, text=True).stdout.split()
checks.append(('quit stopped the running environment', bool(states) and all(s == 'exited' for s in states), states))
log = (run/'logs/backend.log').read_text(errors='replace') if (run/'logs/backend.log').exists() else ''
checks.append(('backend log shows ready line', 'WORKBENCH_READY' in log, ''))
for name, ok, detail in checks:
    mark = 'SKIP' if ok is None else 'PASS' if ok else 'FAIL'
    print(f'{mark}  {name}' + (f'  [{detail}]' if mark != 'PASS' and detail else ''))
print('phases:', ' → '.join(result.get('phases', [])))
failed = [n for n, ok, _ in checks if ok is False]
(run/'summary.json').write_text(json.dumps({'checks': [{'name': n, 'ok': ok, 'detail': str(d)} for n, ok, d in checks], 'phases': result.get('phases'), 'error': report.get('error')}, ensure_ascii=False, indent=2))
print('RESULT:', 'all passed' if not failed and report.get('ok') else f'{len(failed)} failed' + ('' if report.get('ok') else ' (script error: ' + str(report.get('error')) + ')'))
EOF
rc=$?   # (zsh reserves $status)

# Disposable test data: remove the test container and its profile.
docker ps -aq --filter "label=workbench.scope=$scope" | xargs docker rm -f >/dev/null 2>&1
rm -rf "$RUN/App Data"
exit $rc
