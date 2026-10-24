"""Backend process owned by the Mac app.

The app reads one `WORKBENCH_READY {...}` line from stdout to learn the port,
and keeps stdin open for as long as it lives: when the app quits or crashes
the pipe closes and this server shuts down instead of lingering unseen.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import socket
import sys
import threading

import uvicorn

from . import __version__

EXIT_LOCKED = 3


class DesktopServer(uvicorn.Server):
    def __init__(self, config, port):
        super().__init__(config)
        self.port = port

    async def startup(self, sockets=None):
        await super().startup(sockets=sockets)
        if self.started:
            print('WORKBENCH_READY '+json.dumps({'port':self.port, 'version':__version__}), flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description='境工作台后台服务')
    parser.add_argument('--data-dir', required=True)
    parser.add_argument('--port', type=int, default=0, help='0 picks a free loopback port')
    parser.add_argument('--exit-on-stdin-eof', action='store_true')
    parser.add_argument('--no-prepare', action='store_true')
    args = parser.parse_args(argv)
    os.umask(0o077)
    data_dir = Path(args.data_dir).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Two backends on one data folder would race each other's containers.
    lock = open(data_dir/'.workbench.lock', 'a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print('WORKBENCH_ERROR '+json.dumps({'code':'locked'}), flush=True)
        return EXIT_LOCKED
    os.environ.setdefault('WORKBENCH_MODE', 'desktop')
    from .app import create_app
    app = create_app(data_dir)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('127.0.0.1', args.port))
    config = uvicorn.Config(app, host='127.0.0.1', port=sock.getsockname()[1], access_log=False, proxy_headers=False, log_level='info')
    server = DesktopServer(config, sock.getsockname()[1])
    if args.exit_on_stdin_eof:
        def watch_parent():
            try:
                while sys.stdin.buffer.read(4096):
                    pass
            except (OSError, ValueError):
                pass
            server.should_exit = True
        threading.Thread(target=watch_parent, daemon=True).start()
    if not args.no_prepare:
        # Start Docker / load the bundled browser image while the window opens.
        app.state.runtime.build()
    server.run(sockets=[sock])
    return 0


if __name__ == '__main__':
    sys.exit(main())
