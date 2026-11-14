"""A command line inside an environment, opened only when the user asks for it (the 终端 tab in app.js).

docker exec starts a small bridge in the container as the browser's user (uid 1000): it runs bash on a
pseudo-terminal there, copies the terminal's output to its stdout, and reads frames from its stdin. This
side needs no pseudo-terminal of its own (Windows has none). When the page goes away stdin closes, which
ends the shell and whatever it started; stopping the environment ends it as well.
"""
import asyncio
import json
import struct
import subprocess
import threading

from .docker_env import command_env
from .system import quiet

# At most this many command lines per environment at once.
MAX_SESSIONS = 4
# One message from the page: a paste of this size is already a lot for a shell.
MAX_INPUT = 1 << 20
CHUNK = 65536

# Runs inside the container (Python 3.11 image) with the first window size as its arguments. Frames from the
# workbench: 1 byte kind, 4 bytes length, then the payload. Kind 0: keystrokes for the shell; kind 1: a new
# window size (rows, columns as two unsigned 16-bit numbers).
BRIDGE = r'''
import fcntl, os, pty, select, signal, struct, sys, termios
pid, fd = pty.fork()
if pid == 0:
    os.chdir(os.environ.get("HOME") or "/")
    os.execvp("bash", ["bash", "-l"])
def size(rows, cols):
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
def write_all(target, data):
    while data:
        data = data[os.write(target, data):]
size(int(sys.argv[1]), int(sys.argv[2]))
pending = b""
try:
    while True:
        ready = select.select([fd, 0], [], [])[0]
        if fd in ready:
            try:
                out = os.read(fd, 65536)
            except OSError:
                out = b""
            if not out:
                break
            write_all(1, out)
        if 0 in ready:
            data = os.read(0, 65536)
            if not data:
                break
            pending += data
            while len(pending) >= 5:
                kind, length = pending[0], struct.unpack(">I", pending[1:5])[0]
                if len(pending) < 5 + length:
                    break
                payload, pending = pending[5:5 + length], pending[5 + length:]
                if kind == 0:
                    write_all(fd, payload)
                elif kind == 1 and length == 4:
                    size(*struct.unpack(">HH", payload))
finally:
    try:
        os.killpg(pid, signal.SIGHUP)
    except OSError:
        pass
'''

open_sessions: dict[str, int] = {}


def frame(kind: int, payload: bytes) -> bytes:
    return bytes([kind]) + struct.pack('>I', len(payload)) + payload


def window_size(rows, cols):
    """The page's size in character cells, kept to what a terminal can sensibly have."""
    def clamp(value, low, high, default):
        try:
            return min(high, max(low, int(value)))
        except (TypeError, ValueError):
            return default
    return clamp(rows, 2, 500, 24), clamp(cols, 10, 1000, 80)


def command(runtime, env_id, rows, cols):
    """docker exec for the bridge. Only a running environment of this workbench (its labels are checked)."""
    runtime.worker_address(env_id)
    config, _ = runtime.environment_paths(env_id)
    launch = json.loads((config / 'launch.json').read_text(encoding='utf-8'))
    env = {'TERM': 'xterm-256color', 'COLORTERM': 'truecolor', 'LANG': 'C.UTF-8', 'HOME': '/home/browser',
           'USER': 'browser', 'SHELL': '/bin/bash', 'DISPLAY': ':99'}
    if launch.get('timezone'):
        env['TZ'] = launch['timezone']
    if not launch.get('test_mode'):
        # Commands go out through the environment's route, like its browser (mihomo listens in the container).
        for name in ('http_proxy', 'https_proxy', 'all_proxy'):
            env[name] = env[name.upper()] = 'http://127.0.0.1:7890'
        env['no_proxy'] = env['NO_PROXY'] = 'localhost,127.0.0.1,::1'
    options = [part for name, value in env.items() for part in ('--env', f'{name}={value}')]
    return [runtime.docker, 'exec', '-i', '--user', '1000:1000', '--workdir', '/home/browser', *options,
            runtime.container_name(env_id), 'python3', '-c', BRIDGE, str(rows), str(cols)]


class Session:
    def __init__(self, argv):
        self.process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                        bufsize=0, env=command_env(argv[0]), **quiet())
        self.lock = threading.Lock()

    def send(self, data: bytes):
        with self.lock:
            while data:
                data = data[self.process.stdin.write(data):]

    def read(self) -> bytes:
        return self.process.stdout.read(CHUNK)

    def close(self):
        """The bridge sees the end of its input and hangs up the shell."""
        try:
            self.process.stdin.close()
        except OSError:
            pass

    def wait(self):
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()


def parse(message: dict) -> bytes | None:
    """A frame for the bridge from one page message, or None for anything else."""
    text = message.get('text')
    if text is None or len(text) > MAX_INPUT * 2:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    if data.get('type') == 'input' and isinstance(data.get('data'), str):
        payload = data['data'].encode('utf-8', errors='replace')
        return frame(0, payload) if 0 < len(payload) <= MAX_INPUT else None
    if data.get('type') == 'resize':
        return frame(1, struct.pack('>HH', *window_size(data.get('rows'), data.get('cols'))))
    return None


async def serve(websocket, runtime, env_id, rows, cols):
    """The page sends {"type":"input","data":...} and {"type":"resize","rows":..,"cols":..}; it gets the
    terminal's output as binary messages, and {"type":"error","message":...} when it cannot open."""
    await websocket.accept()
    if open_sessions.get(env_id, 0) >= MAX_SESSIONS:
        await websocket.send_text(json.dumps({'type': 'error', 'message': f'这个环境已经开着 {MAX_SESSIONS} 个终端，请先关掉一个。'}, ensure_ascii=False))
        await websocket.close(code=1000)
        return
    open_sessions[env_id] = open_sessions.get(env_id, 0) + 1
    session = None
    tasks = []
    try:
        try:
            argv = await asyncio.to_thread(command, runtime, env_id, *window_size(rows, cols))
            session = await asyncio.to_thread(Session, argv)
        except (ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
            message = str(exc) if isinstance(exc, ValueError) and str(exc) else '终端没有打开，请确认环境正在运行。'
            await websocket.send_text(json.dumps({'type': 'error', 'message': message}, ensure_ascii=False))
            await websocket.close(code=1000)
            return
        loop = asyncio.get_running_loop()
        ended = asyncio.Event()

        def pump():
            # Each piece waits until the page has taken it: a slow page makes the shell wait, memory stays flat.
            try:
                while chunk := session.read():
                    asyncio.run_coroutine_threadsafe(websocket.send_bytes(chunk), loop).result()
            except Exception:
                pass
            finally:
                try:
                    loop.call_soon_threadsafe(ended.set)
                except RuntimeError:
                    pass  # the server is shutting down

        async def incoming():
            while True:
                message = await websocket.receive()
                if message['type'] == 'websocket.disconnect':
                    return
                data = parse(message)
                if data:
                    await asyncio.to_thread(session.send, data)

        threading.Thread(target=pump, daemon=True).start()
        tasks = [asyncio.create_task(incoming()), asyncio.create_task(ended.wait())]
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            try:
                task.result()
            except Exception:
                pass
    finally:
        # Nothing here may wait before the count and the shell's input are settled: the server can cancel us.
        open_sessions[env_id] -= 1
        if not open_sessions[env_id]:
            del open_sessions[env_id]
        for task in tasks:
            if not task.done():
                task.cancel()
        if session:
            session.close()
            await asyncio.to_thread(session.wait)
        try:
            await websocket.close(code=1000)
        except RuntimeError:
            pass
