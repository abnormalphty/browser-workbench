"""Installing Docker Desktop from the Windows app, exercised on any machine by reporting win32."""
import contextlib
import hashlib
import io
import os
import re
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from workbench import docker_setup
from workbench.app import create_app
from workbench.docker_setup import MESSAGES, DockerSetup, SetupBlocked, blocker
from workbench.runtime import WINDOWS_CONTAINERS, Runtime
from workbench.store import Store


def on_windows():
    return patch('sys.platform', 'win32')


def system(**values):
    info = {'build': 22631, 'virtualization': True, 'vmp': True, 'wsl': '2.6.1.0'}
    info.update(values)
    return info


class FakeRegistry:
    """Just enough of winreg for the uninstall entry and RunOnce."""
    HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE, KEY_SET_VALUE, REG_SZ = 'HKCU', 'HKLM', 2, 1

    def __init__(self, values=None):
        self.values = values or {}

    def OpenKey(self, hive, key, *args):
        if (hive, key) not in self.values:
            raise OSError('missing')
        return contextlib.nullcontext((hive, key))

    def CreateKey(self, hive, key):
        self.values.setdefault((hive, key), {})
        return contextlib.nullcontext((hive, key))

    def QueryValueEx(self, handle, name):
        return self.values[handle][name], self.REG_SZ

    def SetValueEx(self, handle, name, reserved, kind, value):
        self.values[handle][name] = value

    def DeleteValue(self, handle, name):
        del self.values[handle][name]


class BlockerTests(unittest.TestCase):
    def test_what_the_user_must_do_first(self):
        booted = 1000.0
        cases = [
            (system(build=19044), None, 'windows'),
            (system(virtualization=False, vmp=False), None, 'virtualization'),
            (system(vmp=False, wsl=None), None, 'wsl'),
            (system(vmp=False), booted - 60, 'wsl'),        # asked before the last start: it did not work
            (system(vmp=False), booted + 60, 'restart'),    # asked since: Windows needs the restart
            (system(wsl=None), None, 'wsl'),                # platform on, WSL itself missing: one try
            (system(wsl='2.0.9.0'), None, 'wsl'),
            (system(wsl=None), booted - 60, None),          # tried once; Docker Desktop offers the update itself
            (system(), None, None),
            (system(vmp=None, virtualization=None, wsl=None), None, None),  # Windows could not tell: the installer will
        ]
        for info, requested, expected in cases:
            with self.subTest(info=info, requested=requested):
                self.assertEqual(blocker(info, requested, booted), expected)

    def test_wsl_versions(self):
        self.assertTrue(docker_setup.wsl_ready('2.6.1.0'))
        self.assertTrue(docker_setup.wsl_ready('2.1.5'))
        self.assertFalse(docker_setup.wsl_ready('2.1.4.0'))
        self.assertFalse(docker_setup.wsl_ready('1.2.5'))
        self.assertFalse(docker_setup.wsl_ready(None))

    def test_off_windows_nothing_is_checked(self):
        with patch('sys.platform', 'darwin'), patch.object(docker_setup, 'powershell') as shell:
            self.assertEqual(docker_setup.check_system(), {'build': None, 'virtualization': None, 'vmp': None, 'wsl': None})
        shell.assert_not_called()

    def test_system_check_reads_one_powershell_answer(self):
        version = SimpleNamespace(build=22631)
        with on_windows(), patch('sys.getwindowsversion', create=True, return_value=version), \
             patch.object(docker_setup, 'processor_feature', return_value=False), \
             patch.object(docker_setup, 'powershell', return_value={'hypervisor': True, 'firmware': False, 'vmp': 2, 'wsl': ''}):
            # A running hypervisor hides the firmware flag but proves virtualization works.
            self.assertEqual(docker_setup.check_system(), {'build': 22631, 'virtualization': True, 'vmp': False, 'wsl': None})
        with on_windows(), patch('sys.getwindowsversion', create=True, return_value=version), \
             patch.object(docker_setup, 'powershell', side_effect=OSError('blocked')):
            self.assertEqual(docker_setup.check_system()['vmp'], None)


class SignatureTests(unittest.TestCase):
    def verify(self, answer):
        with on_windows(), patch.object(docker_setup, 'powershell', **answer) as shell:
            result = docker_setup.verify(Path('Docker Desktop Installer.exe'))
        return result, shell

    def test_only_a_valid_signature_by_docker_passes(self):
        subject = 'CN=Docker Inc, O=Docker Inc, L=Palo Alto, S=California, C=US, SERIALNUMBER=4817464'
        ok, shell = self.verify({'return_value': {'status': 'Valid', 'subject': subject}})
        self.assertTrue(ok)
        # The path travels in the environment, never inside the script.
        self.assertEqual(shell.call_args.args[1], {'WORKBENCH_SIGNED_FILE': 'Docker Desktop Installer.exe'})
        self.assertFalse(self.verify({'return_value': {'status': 'HashMismatch', 'subject': subject}})[0])
        self.assertFalse(self.verify({'return_value': {'status': 'Valid', 'subject': 'CN=Microsoft Windows, O=Microsoft Corporation'}})[0])
        self.assertFalse(self.verify({'return_value': {'status': 'NotSigned', 'subject': ''}})[0])
        self.assertFalse(self.verify({'side_effect': OSError('no PowerShell')})[0])
        with patch('sys.platform', 'darwin'):
            self.assertFalse(docker_setup.verify(Path('x.exe')))

    def test_signer_names(self):
        self.assertEqual(docker_setup.signer_name('CN=Docker Inc, O=Docker Inc'), 'Docker Inc')
        self.assertEqual(docker_setup.signer_name('CN="Docker, Inc.", O=Docker'), 'Docker, Inc.')
        self.assertEqual(docker_setup.signer_name('O=Docker Inc'), '')


class InstallerServer:
    """Serves a fake installer with ETag and Range support; can cut the first download short."""

    def __init__(self, payload, cut_first_at=None):
        self.payload, self.cut, self.requests, self.fail = payload, cut_first_at, [], False
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                owner.requests.append(dict(self.headers))
                if owner.fail:
                    self.send_error(503)
                    return
                body, tag = owner.payload, '"' + hashlib.sha256(owner.payload).hexdigest()[:16] + '"'
                start = 0
                match = re.fullmatch(r'bytes=(\d+)-', self.headers.get('Range') or '')
                if match and self.headers.get('If-Range') == tag:
                    start = int(match.group(1))
                    if start >= len(body):
                        self.send_error(416)
                        return
                    self.send_response(206)
                    self.send_header('Content-Range', f'bytes {start}-{len(body) - 1}/{len(body)}')
                else:
                    self.send_response(200)
                self.send_header('Content-Length', str(len(body) - start))
                self.send_header('ETag', tag)
                self.end_headers()
                if owner.cut is not None:
                    cut, owner.cut = owner.cut, None
                    self.wfile.write(body[start:cut])
                    self.close_connection = True
                    return
                self.wfile.write(body[start:])

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.url = f'http://127.0.0.1:{self.server.server_port}/installer.exe'
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.setup = DockerSetup(Path(self.temp.name))
        self.payload = os.urandom(3 * 1024 * 1024 + 123)
        self.stack = contextlib.ExitStack()
        self.stack.enter_context(patch.dict(os.environ, {'no_proxy': '*', 'NO_PROXY': '*'}))
        self.stack.enter_context(patch.object(docker_setup.time, 'sleep'))

    def tearDown(self):
        self.stack.close()
        self.temp.cleanup()

    def serve(self, **options):
        server = InstallerServer(self.payload, **options)
        self.addCleanup(server.close)
        self.stack.enter_context(patch.object(docker_setup, 'INSTALLER_URL', server.url))
        return server

    def test_an_interrupted_download_resumes_where_it_stopped(self):
        server = self.serve(cut_first_at=1024 * 1024)
        seen = []
        with patch.object(docker_setup, 'verify', return_value=True):
            path = self.setup.download(lambda: seen.append(self.setup.downloaded))
        self.assertEqual(path.read_bytes(), self.payload)
        self.assertEqual(path.name, 'Docker Desktop Installer.exe')
        self.assertEqual(len(server.requests), 2)
        self.assertEqual(server.requests[1]['Range'], 'bytes=1048576-')
        self.assertEqual(seen[-1], len(self.payload))
        self.assertEqual(self.setup.total, len(self.payload))
        self.assertFalse((path.parent / 'Docker Desktop Installer.exe.part').exists())

    def test_a_newer_installer_published_meanwhile_is_fetched_whole(self):
        server = self.serve(cut_first_at=1024 * 1024)
        calls = 0

        def progress():
            nonlocal calls
            calls += 1
            if calls == 1:  # Docker publishes a new installer while the first try is cut short
                server.payload = self.payload = os.urandom(2 * 1024 * 1024)
        with patch.object(docker_setup, 'verify', return_value=True):
            path = self.setup.download(progress)
        self.assertEqual(path.read_bytes(), self.payload)
        self.assertIn('If-Range', server.requests[1])

    def test_a_file_without_dockers_signature_is_deleted(self):
        self.serve()
        with patch.object(docker_setup, 'verify', return_value=False), self.assertRaises(ValueError) as caught:
            self.setup.download()
        self.assertIn('签名', str(caught.exception))
        self.assertEqual(list((Path(self.temp.name) / 'setup').glob('*.exe*')), [])

    def test_gives_up_after_repeated_failures_but_keeps_what_it_has(self):
        server = self.serve(cut_first_at=512 * 1024)
        original = server.server.RequestHandlerClass.do_GET

        def flaky(handler):
            if server.requests:
                server.fail = True
            original(handler)
        server.server.RequestHandlerClass.do_GET = flaky
        with patch.object(docker_setup, 'verify', return_value=True), self.assertRaises(ValueError) as caught:
            self.setup.download()
        self.assertIn('下载失败', str(caught.exception))
        self.assertEqual((Path(self.temp.name) / 'setup' / 'Docker Desktop Installer.exe.part').stat().st_size, 512 * 1024)

    def test_a_complete_verified_download_is_reused(self):
        folder = Path(self.temp.name) / 'setup'
        folder.mkdir()
        (folder / 'Docker Desktop Installer.exe').write_bytes(b'ready')
        with patch.object(docker_setup, 'verify', return_value=True), patch('urllib.request.urlopen') as fetch:
            self.assertEqual(self.setup.download().read_bytes(), b'ready')
        fetch.assert_not_called()


class SetupStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_agreement_and_wsl_request_survive_a_restart(self):
        setup = DockerSetup(self.folder)
        self.assertFalse(setup.accepted())
        setup.accept()
        setup.wsl_requested()
        again = DockerSetup(self.folder)
        self.assertTrue(again.accepted())
        self.assertIn('terms_accepted', again.status())
        with on_windows(), patch.object(docker_setup, 'check_system', return_value=system(vmp=False)), \
             patch.object(docker_setup, 'booted_at', return_value=0), patch.object(docker_setup, 'resume_after_restart') as resume:
            self.assertEqual(again.check(), 'restart')
        resume.assert_called_once()
        self.assertEqual(again.status()['wsl'], 'restart')
        self.assertEqual(again.status()['message'], MESSAGES['restart'])

    def test_the_app_reopens_once_after_the_restart(self):
        exe = self.folder / 'BrowserWorkbench.exe'
        exe.write_bytes(b'')
        registry = FakeRegistry()
        with on_windows(), patch.dict('sys.modules', {'winreg': registry}), patch.dict(os.environ, {'WORKBENCH_APP_EXE': str(exe)}):
            docker_setup.resume_after_restart()
            self.assertEqual(registry.values[('HKCU', docker_setup.RUN_ONCE)][docker_setup.RUN_ONCE_NAME], f'"{exe}"')
            docker_setup.forget_restart()
            self.assertEqual(registry.values[('HKCU', docker_setup.RUN_ONCE)], {})
        with on_windows(), patch.dict('sys.modules', {'winreg': registry}), patch.dict(os.environ, {'WORKBENCH_APP_EXE': 'calc'}):
            docker_setup.resume_after_restart()  # only the app's own .exe
        self.assertEqual(registry.values[('HKCU', docker_setup.RUN_ONCE)], {})

    def test_install_runs_the_per_user_installer_and_cleans_up(self):
        setup = DockerSetup(self.folder)
        installer = self.folder / 'Docker Desktop Installer.exe'
        installer.write_bytes(b'')
        output = io.StringIO()
        with on_windows(), patch.object(docker_setup, 'verify', return_value=True), \
             patch.object(docker_setup, 'forget_restart') as forget, \
             patch('subprocess.run', return_value=SimpleNamespace(returncode=0)) as run:
            setup.install(installer, output)
        command = run.call_args.args[0]
        self.assertEqual(command[1:], ['install', '--user', '--quiet', '--accept-license', '--backend=wsl-2'])
        self.assertFalse(installer.exists())
        forget.assert_called_once()

    def test_agreement_covers_one_installation(self):
        setup = DockerSetup(self.folder)
        setup.accept()
        installer = self.folder / 'Docker Desktop Installer.exe'
        installer.write_bytes(b'')
        with on_windows(), patch.object(docker_setup, 'verify', return_value=True), patch.object(docker_setup, 'forget_restart'), \
             patch('subprocess.run', return_value=SimpleNamespace(returncode=0)):
            setup.install(installer, io.StringIO())
        # Docker Desktop removed later: the app asks again instead of reinstalling by itself.
        self.assertFalse(DockerSetup(self.folder).accepted())

    def test_install_failures_say_what_to_do(self):
        setup = DockerSetup(self.folder)
        installer = self.folder / 'Docker Desktop Installer.exe'
        installer.write_bytes(b'')
        refused = 'Prerequisite failed: Docker Desktop requires the "Virtual Machine Platform" Windows feature'
        with on_windows(), patch.object(docker_setup, 'verify', return_value=True), \
             patch.object(docker_setup, 'installer_log', return_value=refused), \
             patch('subprocess.run', return_value=SimpleNamespace(returncode=1)), self.assertRaises(SetupBlocked) as caught:
            setup.install(installer, io.StringIO())
        self.assertEqual(caught.exception.step, 'wsl')
        with on_windows(), patch.object(docker_setup, 'verify', return_value=True), \
             patch.object(docker_setup, 'installer_log', return_value='something else'), \
             patch('subprocess.run', return_value=SimpleNamespace(returncode=5)), self.assertRaises(ValueError) as caught:
            setup.install(installer, io.StringIO())
        self.assertIn('代码 5', str(caught.exception))
        with on_windows(), patch.object(docker_setup, 'verify', return_value=False), patch('subprocess.run') as run, \
             self.assertRaises(ValueError):
            setup.install(installer, io.StringIO())
        run.assert_not_called()
        self.assertFalse(installer.exists())

    def test_too_little_disk_space_is_said_before_downloading(self):
        setup = DockerSetup(self.folder)
        with patch('shutil.disk_usage', return_value=SimpleNamespace(free=2 * 1024 ** 3)), self.assertRaises(ValueError) as caught:
            setup.ensure_space()
        self.assertIn('磁盘空间不够', str(caught.exception))


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = Runtime(Store(Path(self.temp.name)))
        self.missing = {'docker_installed': False, 'docker_ready': False, 'image_ready': False}
        self.installed = {'docker_installed': True, 'docker_ready': True, 'image_ready': True}

    def tearDown(self):
        self.temp.cleanup()

    def prepare(self, statuses, steps, install=None):
        setup = self.runtime.setup
        with on_windows(), patch.object(self.runtime, 'status', side_effect=statuses), \
             patch.object(setup, 'accepted', return_value=True), patch.object(setup, 'fresh', return_value=False), \
             patch.object(setup, 'check', side_effect=steps) as check, patch.object(setup, 'ensure_space'), \
             patch.object(setup, 'download', return_value=Path('installer.exe')) as download, \
             patch.object(setup, 'install', side_effect=install) as installed, \
             patch.object(self.runtime.geography, 'start_batch'):
            self.runtime._prepare_job()
        return check, download, installed

    def test_agreed_setup_downloads_installs_then_carries_on(self):
        check, download, installed = self.prepare([self.missing, self.installed], [None, None])
        download.assert_called_once()
        installed.assert_called_once()
        self.assertEqual(check.call_count, 2)  # before the download and again before installing
        self.assertEqual(self.runtime.build_state, 'ready')

    def test_wsl_is_asked_for_after_the_download(self):
        self.runtime.setup.step = 'wsl'  # what check() sets; it is mocked here
        check, download, installed = self.prepare([self.missing], ['wsl', 'wsl'])
        download.assert_called_once()
        installed.assert_not_called()
        self.assertEqual(self.runtime.build_state, 'error')
        self.assertEqual(self.runtime.build_error, MESSAGES['wsl'])

    def test_no_virtualization_stops_before_downloading(self):
        self.runtime.setup.step = 'virtualization'
        check, download, installed = self.prepare([self.missing], ['virtualization'])
        download.assert_not_called()
        self.assertEqual(self.runtime.build_error, MESSAGES['virtualization'])

    def test_without_the_users_agreement_nothing_is_installed(self):
        with on_windows(), patch.object(self.runtime, 'status', return_value=self.missing), \
             patch.object(self.runtime.setup, 'download') as download:
            self.runtime._prepare_job()
        download.assert_not_called()
        self.assertIn('请先安装 Docker Desktop', self.runtime.build_error)

    def test_windows_containers_are_switched_to_linux(self):
        windows_engine = {'docker_installed': True, 'docker_ready': True, 'docker_os': 'windows', 'image_ready': False}
        linux = {'docker_installed': True, 'docker_ready': True, 'docker_os': 'linux', 'image_ready': False}
        with patch.object(self.runtime, 'status', return_value=windows_engine), \
             patch.object(self.runtime, '_switch_to_linux', return_value=linux) as switch, \
             patch.object(self.runtime, 'image_archive', return_value='/bundle/browser-runtime.tar.gz'), \
             patch.object(self.runtime, '_load_image') as loaded:
            self.runtime._prepare_job()
        switch.assert_called_once()
        loaded.assert_called_once()
        with patch.object(self.runtime, 'status', return_value=windows_engine), \
             patch.object(self.runtime, '_switch_to_linux', return_value=windows_engine), \
             patch.object(self.runtime, '_load_image') as loaded:
            self.runtime._prepare_job()
        loaded.assert_not_called()
        self.assertEqual(self.runtime.build_error, WINDOWS_CONTAINERS)

    def test_docker_desktop_found_nowhere_is_started_through_its_cli(self):
        with on_windows(), patch.object(Runtime, 'docker', new='docker.exe'), patch('workbench.runtime.engine_app', return_value=None), \
             patch('subprocess.run', return_value=SimpleNamespace(returncode=0)) as run:
            self.runtime._open_desktop()
        self.assertEqual(run.call_args.args[0], ['docker.exe', 'desktop', 'start', '--detach'])
        with on_windows(), patch.object(Runtime, 'docker', new='docker.exe'), patch('workbench.runtime.engine_app', return_value=None), \
             patch('subprocess.run', return_value=SimpleNamespace(returncode=1)), self.assertRaises(ValueError):
            self.runtime._open_desktop()

    def test_switching_uses_docker_desktops_cli_then_waits_for_linux(self):
        statuses = [{'docker_ready': True, 'docker_os': 'windows'}, {'docker_ready': True, 'docker_os': 'linux'}]
        with patch.object(Runtime, 'docker', new='docker.exe'), patch('workbench.runtime.engine_app', return_value=None), \
             patch('subprocess.run', return_value=SimpleNamespace(returncode=0)) as run, \
             patch.object(self.runtime, 'status', side_effect=statuses), patch.object(self.runtime.monitor, 'engine_info'), \
             patch('workbench.runtime.time.sleep'):
            result = self.runtime._switch_to_linux({'docker_os': 'windows'})
        self.assertEqual(run.call_args.args[0], ['docker.exe', 'desktop', 'engine', 'use', 'linux'])
        self.assertEqual(result['docker_os'], 'linux')


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.temp.name))
        self.client = TestClient(self.app, base_url='http://127.0.0.1:8766')
        token = re.search(r'name="workbench-token" content="([^"]+)"', self.client.get('/').text).group(1)
        self.headers = {'X-Workbench-Token': token}
        self.runtime = self.app.state.runtime

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def test_setup_needs_windows_and_the_users_agreement(self):
        with patch('sys.platform', 'darwin'):
            response = self.client.post('/api/runtime/docker-setup', json={'accept_terms': True}, headers=self.headers)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.runtime.setup.accepted())
        with on_windows(), patch.object(self.runtime, 'build') as build:
            response = self.client.post('/api/runtime/docker-setup', json={}, headers=self.headers)
        self.assertEqual(response.status_code, 400)
        build.assert_not_called()

    def test_agreeing_checks_the_pc_and_starts_the_setup(self):
        with on_windows(), patch.object(self.runtime, 'build') as build, \
             patch.object(docker_setup, 'check_system', return_value=system(vmp=False)), \
             patch.object(docker_setup, 'booted_at', return_value=0):
            response = self.client.post('/api/runtime/docker-setup', json={'accept_terms': True}, headers=self.headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['docker_setup']['step'], 'wsl')
            build.assert_called_once()
            with patch.object(docker_setup, 'resume_after_restart'):
                response = self.client.post('/api/runtime/docker-setup', json={'wsl_requested': True}, headers=self.headers)
            self.assertEqual(response.json()['docker_setup']['step'], 'restart')
        self.assertTrue(self.runtime.setup.accepted())

    def test_mac_reports_no_setup(self):
        with patch('sys.platform', 'darwin'), patch.object(self.runtime.monitor, 'engine_info', return_value={}), \
             patch('workbench.runtime.find_cli', return_value=None):
            self.assertIsNone(self.runtime.status()['docker_setup'])


if __name__ == '__main__':
    unittest.main()
