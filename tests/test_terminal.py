import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from workbench import terminal
from workbench.app import create_app

POSIX = os.name == 'posix'


def read_until(process, needle, seconds=10):
    """Bytes from the bridge's stdout until needle shows up (the bridge writes as the shell does)."""
    os.set_blocking(process.stdout.fileno(), False)
    output, deadline = b'', time.monotonic() + seconds
    while needle not in output and time.monotonic() < deadline:
        try:
            output += process.stdout.read(4096) or b''
        except BlockingIOError:
            pass
        time.sleep(.05)
    return output


class FakeRuntime:
    def __init__(self, config, running=True):
        self.config, self.running, self.docker = config, running, '/usr/local/bin/docker'

    def worker_address(self, env_id, port='8081/tcp'):
        if not self.running:
            raise ValueError('环境尚未运行。')
        return 'http://127.0.0.1:1'

    def environment_paths(self, env_id):
        return self.config, self.config.parent / 'profile'

    def container_name(self, env_id):
        return 'local-browser-test-' + env_id


@unittest.skipUnless(POSIX, 'the bridge runs in the Linux container; here it needs a POSIX host')
class BridgeTests(unittest.TestCase):
    """The program docker exec runs in the container, tried on this machine with its bash."""

    def test_shell_runs_commands_takes_window_sizes_and_ends_with_stdin(self):
        with tempfile.TemporaryDirectory() as home:
            process = subprocess.Popen([sys.executable, '-c', terminal.BRIDGE, '24', '80'], stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, env={'HOME': home, 'PATH': os.environ['PATH'], 'TERM': 'dumb'})
            try:
                process.stdin.write(terminal.frame(0, b'echo $((6*7))xyz\n'))
                process.stdin.flush()
                self.assertIn(b'42xyz', read_until(process, b'42xyz'))
                process.stdin.write(terminal.frame(0, b'stty size\n'))
                process.stdin.flush()
                self.assertIn(b'24 80', read_until(process, b'24 80'))
                # A new size, then keystrokes split across writes: frames are put back together.
                message = terminal.frame(1, struct.pack('>HH', 31, 101)) + terminal.frame(0, b'stty size\n')
                process.stdin.write(message[:3])
                process.stdin.flush()
                time.sleep(.1)
                process.stdin.write(message[3:])
                process.stdin.flush()
                self.assertIn(b'31 101', read_until(process, b'31 101'))
                process.stdin.close()
                self.assertEqual(process.wait(timeout=10), 0)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()

    def test_exit_in_the_shell_ends_the_bridge(self):
        with tempfile.TemporaryDirectory() as home:
            process = subprocess.Popen([sys.executable, '-c', terminal.BRIDGE, '24', '80'], stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, env={'HOME': home, 'PATH': os.environ['PATH'], 'TERM': 'dumb'})
            process.stdin.write(terminal.frame(0, b'exit\n'))
            process.stdin.flush()
            self.assertEqual(process.wait(timeout=10), 0)
            process.stdin.close()
            process.stdout.close()


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = Path(self.temp.name) / 'config'
        self.config.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def launch(self, **values):
        (self.config / 'launch.json').write_text(json.dumps({'worker_secret': 'x', 'vnc_password': 'y', **values}))

    def test_runs_as_the_browser_user_through_the_environment_route(self):
        self.launch(test_mode=False, timezone='Asia/Tokyo')
        argv = terminal.command(FakeRuntime(self.config), 'a' * 32, 30, 120)
        self.assertEqual(argv[:6], ['/usr/local/bin/docker', 'exec', '-i', '--user', '1000:1000', '--workdir'])
        self.assertIn('local-browser-test-' + 'a' * 32, argv)
        self.assertEqual(argv[-5:], ['python3', '-c', terminal.BRIDGE, '30', '120'])
        settings = [argv[i + 1] for i, part in enumerate(argv) if part == '--env']
        for name in ('http_proxy', 'HTTPS_PROXY', 'all_proxy'):
            self.assertIn(f'{name}=http://127.0.0.1:7890', settings)
        self.assertIn('TZ=Asia/Tokyo', settings)
        self.assertIn('TERM=xterm-256color', settings)
        self.assertNotIn('-t', argv)  # no terminal on this side: Windows has none

    def test_test_mode_goes_out_directly(self):
        self.launch(test_mode=True, timezone=None)
        argv = terminal.command(FakeRuntime(self.config), 'a' * 32, 24, 80)
        self.assertFalse([part for part in argv if 'proxy' in part.lower()])

    def test_only_a_running_environment(self):
        self.launch(test_mode=True)
        with self.assertRaisesRegex(ValueError, '尚未运行'):
            terminal.command(FakeRuntime(self.config, running=False), 'a' * 32, 24, 80)

    def test_page_messages(self):
        self.assertEqual(terminal.parse({'text': json.dumps({'type': 'input', 'data': 'ls\r'})}), terminal.frame(0, b'ls\r'))
        self.assertEqual(terminal.parse({'text': json.dumps({'type': 'input', 'data': '中'})}), terminal.frame(0, '中'.encode()))
        self.assertEqual(terminal.parse({'text': json.dumps({'type': 'resize', 'rows': 40, 'cols': 132})}), terminal.frame(1, struct.pack('>HH', 40, 132)))
        self.assertEqual(terminal.parse({'text': json.dumps({'type': 'resize', 'rows': 99999, 'cols': 'x'})}), terminal.frame(1, struct.pack('>HH', 500, 80)))
        for junk in ({'bytes': b'raw'}, {'text': 'not json'}, {'text': '[1]'}, {'text': json.dumps({'type': 'input', 'data': ''})},
                     {'text': json.dumps({'type': 'input', 'data': 5})}, {'text': json.dumps({'type': 'other'})},
                     {'text': json.dumps({'type': 'input', 'data': 'x' * (terminal.MAX_INPUT + 1)})}):
            self.assertIsNone(terminal.parse(junk), junk)


class WebSocketTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.temp.name))
        self.client = TestClient(self.app, base_url='http://127.0.0.1:8766')
        self.client.get('/')  # the session cookie
        self.env = self.app.state.store.create_environment('终端', None)['id']
        self.origin = {'origin': 'http://127.0.0.1:8766'}

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def test_only_the_workbench_page_may_connect(self):
        with TestClient(self.app, base_url='http://127.0.0.1:8766') as stranger:
            with self.assertRaises(WebSocketDisconnect) as refused:
                with stranger.websocket_connect(f'ws://127.0.0.1:8766/view/{self.env}/terminal', headers=self.origin):
                    pass
            self.assertEqual(refused.exception.code, 1008)
        with self.assertRaises(WebSocketDisconnect) as refused:
            with self.client.websocket_connect(f'ws://127.0.0.1:8766/view/{self.env}/terminal', headers={'origin': 'https://untrusted.example'}):
                pass
        self.assertEqual(refused.exception.code, 1008)

    def test_a_stopped_environment_says_so(self):
        with patch.object(self.app.state.runtime, 'worker_address', side_effect=ValueError('环境尚未运行。')):
            with self.client.websocket_connect(f'ws://127.0.0.1:8766/view/{self.env}/terminal', headers=self.origin) as socket:
                self.assertEqual(json.loads(socket.receive_text()), {'type': 'error', 'message': '环境尚未运行。'})
        self.assertEqual(terminal.open_sessions, {})

    @unittest.skipUnless(POSIX, 'runs the bridge on this machine')
    def test_keystrokes_and_output_travel_through(self):
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)

        def local(runtime, env_id, rows, cols):
            return [sys.executable, '-c', terminal.BRIDGE, str(rows), str(cols)]
        with patch.object(terminal, 'command', local), patch.dict(os.environ, {'HOME': home.name, 'TERM': 'dumb'}):
            with self.client.websocket_connect(f'ws://127.0.0.1:8766/view/{self.env}/terminal?rows=33&cols=99', headers=self.origin) as socket:
                self.assertEqual(terminal.open_sessions, {self.env: 1})
                # The shell echoes what is typed: the quotes keep the echo from matching.
                socket.send_text(json.dumps({'type': 'input', 'data': 'stty size; echo do""ne\n'}))
                output = b''
                while b'\ndone' not in output:
                    output += socket.receive_bytes()
                self.assertIn(b'33 99', output)
        deadline = time.monotonic() + 10
        while terminal.open_sessions and time.monotonic() < deadline:
            time.sleep(.05)
        self.assertEqual(terminal.open_sessions, {})

    def test_a_limit_per_environment(self):
        with patch.dict(terminal.open_sessions, {self.env: terminal.MAX_SESSIONS}):
            with self.client.websocket_connect(f'ws://127.0.0.1:8766/view/{self.env}/terminal', headers=self.origin) as socket:
                self.assertRegex(json.loads(socket.receive_text())['message'], re.escape(str(terminal.MAX_SESSIONS)))


if __name__ == '__main__':
    unittest.main()
