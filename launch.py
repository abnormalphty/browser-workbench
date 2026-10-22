#!/usr/bin/env python3
"""Double-click entry point: reuse a running workbench or start a local process."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
import venv
import webbrowser

ROOT = Path(__file__).resolve().parent
URL = 'http://127.0.0.1:8766'


def healthy():
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(URL+'/health', timeout=1) as response:
            return json.load(response).get('app') == 'browser-workbench'
    except Exception:
        return False


def main():
    os.umask(0o077)
    if healthy():
        webbrowser.open(URL)
        print('工作台已打开。')
        return
    with socket.socket() as sock:
        if sock.connect_ex(('127.0.0.1',8766)) == 0:
            raise RuntimeError('8766 端口已被其他程序使用，请关闭占用该端口的程序后重试。')
    if sys.version_info < (3,11):
        raise RuntimeError('需要 Python 3.11 或更新版本，请安装后重试。')
    local_python = ROOT/'.venv/bin/python'
    if not local_python.exists():
        print('首次启动，正在准备工作台组件…')
        venv.EnvBuilder(with_pip=True).create(ROOT/'.venv')
    # Complete an interrupted first install, and install newly pinned versions
    # after a source update. Never rely on unrelated system packages.
    import hashlib
    requirements = ROOT/'requirements.txt'
    marker = ROOT/'.venv/.workbench-requirements.sha256'
    digest = hashlib.sha256(requirements.read_bytes()).hexdigest()
    if not marker.exists() or marker.read_text().strip()!=digest:
        subprocess.run([str(local_python),'-m','pip','install','-r',str(requirements)],check=True)
        marker.write_text(digest)
    python = local_python
    data = ROOT/'data'
    data.mkdir(exist_ok=True,mode=0o700)
    with (data/'server.log').open('a') as log:
        process = subprocess.Popen([str(python),str(ROOT/'run.py'),'--no-open','--prepare'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    for _ in range(60):
        if healthy():
            webbrowser.open(URL)
            print('工作台已打开。可以关闭这个终端窗口。')
            return
        if process.poll() is not None:
            raise RuntimeError('工作台启动失败，详情保存在 data/server.log。')
        time.sleep(.5)
    raise RuntimeError('工作台启动超时，详情保存在 data/server.log。')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('无法打开工作台：'+str(error))
        input('按回车关闭…')
        sys.exit(1)
