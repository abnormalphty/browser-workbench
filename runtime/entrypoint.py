"""Bring up one virtual desktop. Browser process does not run as root."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time


children = []
browser_process = None


def spawn(args, **kwargs):
    proc = subprocess.Popen(args, **kwargs)
    children.append(proc)
    return proc


def finish(*_):
    # Keep X11 and the proxy alive until Firefox has flushed its profile.
    # Tearing down the display at the same time can abort browser shutdown.
    if browser_process is not None and browser_process.poll() is None:
        browser_process.terminate()
        try:
            browser_process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            browser_process.kill()
    for proc in reversed(children):
        if proc.poll() is None:
            proc.terminate()
    deadline = time.monotonic() + 10
    for proc in reversed(children):
        try:
            proc.wait(timeout=max(.1, deadline-time.monotonic()))
        except subprocess.TimeoutExpired:
            proc.kill()
    sys.exit(0)


def wait_port(port):
    for _ in range(100):
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=.2):
                return
        except OSError:
            time.sleep(.1)
    raise RuntimeError('Internal service did not start')


def main():
    global browser_process
    signal.signal(signal.SIGTERM, finish)
    signal.signal(signal.SIGINT, finish)
    runtime = Path('/run/workbench')
    runtime.mkdir(mode=0o700)
    launch = json.loads(Path('/config/launch.json').read_text())
    for name in ['launch.json', 'proxy.yaml']:
        p = runtime / name
        p.write_bytes((Path('/config') / name).read_bytes())
        p.chmod(0o600)
        os.chown(p, 1000, 1000)
    os.chown(runtime, 1000, 1000)
    profile = Path('/profile')
    os.chown(profile, 1000, 1000)
    profile.chmod(0o700)
    for directory in [profile/'transfer', profile/'transfer'/'incoming', profile/'transfer'/'downloads']:
        if directory.is_symlink():
            raise RuntimeError('Transfer directory must not be a symbolic link')
        directory.mkdir(mode=0o700, exist_ok=True)
        os.chown(directory, 1000, 1000)
    gtk = Path('/home/browser/.config/gtk-3.0')
    gtk.mkdir(parents=True, exist_ok=True)
    (gtk/'bookmarks').write_text('file:///profile/transfer/incoming 电脑传入文件\nfile:///profile/transfer/downloads 环境下载文件\n')
    (gtk.parent/'user-dirs.dirs').write_text('XDG_DOWNLOAD_DIR="/profile/transfer/downloads"\nXDG_DOCUMENTS_DIR="/profile/transfer/incoming"\n')
    for directory in (gtk.parent, gtk):
        os.chown(directory,1000,1000)
    for file in (gtk/'bookmarks',gtk.parent/'user-dirs.dirs'):
        os.chown(file,1000,1000)
    if not launch['test_mode']:
        checked = subprocess.run(['mihomo', '-t', '-f', str(runtime/'proxy.yaml')], capture_output=True)
        if checked.returncode:
            print('Proxy configuration validation failed', flush=True)
            sys.exit(1)
        spawn(['mihomo', '-f', str(runtime/'proxy.yaml')], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wait_port(7890)
    spawn(['Xvfb', ':99', '-screen', '0', '1440x900x24', '-ac', '-nolisten', 'tcp'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        if Path('/tmp/.X11-unix/X99').exists():
            break
        time.sleep(.1)
    spawn(['openbox'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    password_file = runtime / 'vnc.pass'
    subprocess.run(['x11vnc', '-storepasswd', launch['vnc_password'], str(password_file)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    password_file.chmod(0o600)
    spawn(['x11vnc', '-display', ':99', '-rfbport', '5900', '-localhost', '-rfbauth', str(password_file), '-forever', '-shared', '-repeat', '-xkb', '-quiet'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    wait_port(5900)
    spawn(['websockify', '--web=/usr/share/novnc', '6080', '127.0.0.1:5900'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    env = {**os.environ, 'HOME': '/home/browser', 'DISPLAY': ':99'}
    if launch.get('timezone'):
        from zoneinfo import ZoneInfo
        ZoneInfo(launch['timezone'])
        env['TZ'] = launch['timezone']
    browser_process = spawn([sys.executable, '/app/browser.py'], env=env, user=1000, group=1000, extra_groups=[])
    while all(p.poll() is None for p in children):
        time.sleep(1)
    print('An environment service exited', flush=True)
    finish()


if __name__ == '__main__':
    main()
