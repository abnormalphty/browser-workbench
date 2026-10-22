#!/usr/bin/env python3
import argparse
import os
from pathlib import Path
import threading
import time
import webbrowser

import uvicorn
from workbench.app import create_app


def main():
    parser = argparse.ArgumentParser(description='本地托管浏览器工作台')
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--no-open', action='store_true')
    parser.add_argument('--prepare', action='store_true', help='自动检查和准备本机运行组件')
    args = parser.parse_args()
    os.umask(0o077)
    app = create_app()
    if args.prepare:
        def prepare():
            import subprocess
            runtime = app.state.runtime
            if not runtime.status()['docker_installed']:
                return
            subprocess.Popen(['open','-a','Docker'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(120):
                status = runtime.status()
                if status['docker_ready']:
                    if not status['image_ready']:
                        runtime.build()
                    return
                time.sleep(2)
        threading.Thread(target=prepare, daemon=True).start()
    if not args.no_open:
        threading.Timer(1.5, lambda:webbrowser.open(f'http://127.0.0.1:{args.port}')).start()
    uvicorn.run(app, host='127.0.0.1', port=args.port, access_log=False, proxy_headers=False)


if __name__ == '__main__':
    main()
