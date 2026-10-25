"""Desktop-app backend: engine discovery, bundled image, control API, lifetime."""
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from workbench import docker_env
from workbench.app import create_app
from workbench.runtime import IMAGE, Runtime
from workbench.store import Store

ROOT = Path(__file__).resolve().parent.parent


class DockerDiscoveryTests(unittest.TestCase):
    def test_cli_on_path_wins_then_known_app_locations_are_searched(self):
        with patch.object(docker_env.shutil, 'which', return_value='/custom/bin/docker'):
            self.assertEqual(docker_env.find_cli(), '/custom/bin/docker')
        with tempfile.TemporaryDirectory() as tmp:
            cli = Path(tmp)/'docker'
            cli.write_text('#!/bin/sh\n')
            cli.chmod(0o755)
            with patch.object(docker_env.shutil, 'which', return_value=None), patch.object(docker_env, 'CLI_CANDIDATES', ('/missing/docker', str(cli))):
                self.assertEqual(docker_env.find_cli(), str(cli))
            with patch.object(docker_env.shutil, 'which', return_value=None), patch.object(docker_env, 'CLI_CANDIDATES', ('/missing/docker',)):
                self.assertIsNone(docker_env.find_cli())

    def test_subprocess_path_includes_cli_directory_for_credential_helpers(self):
        with patch.dict(os.environ, {'PATH':'/usr/bin:/bin'}):
            path = docker_env.command_env('/Applications/Docker.app/Contents/Resources/bin/docker')['PATH'].split(':')
        self.assertEqual(path[0], '/Applications/Docker.app/Contents/Resources/bin')
        self.assertIn('/usr/bin', path)
        self.assertEqual(len(path), len(set(path)))

    def test_download_link_matches_the_mac_chip(self):
        with patch.object(docker_env, 'apple_silicon', return_value=True):
            self.assertIn('/arm64/', docker_env.download_url())
        with patch.object(docker_env, 'apple_silicon', return_value=False):
            self.assertIn('/amd64/', docker_env.download_url())


class BundledImageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.runtime = Runtime(Store(Path(self.tmp.name)/'data'))
        self.archive = Path(self.tmp.name)/'browser-runtime.tar.gz'
        self.archive.write_bytes(b'x'*(3 << 20))

    def tearDown(self):
        self.tmp.cleanup()

    def ready_status(self):
        return {'docker_installed':True, 'docker_ready':True, 'image_ready':False}

    def test_bundled_archive_is_loaded_instead_of_building_from_the_network(self):
        with patch.dict(os.environ, {'WORKBENCH_IMAGE_ARCHIVE':str(self.archive)}), patch.object(self.runtime, 'status', return_value=self.ready_status()), \
             patch.object(self.runtime, '_load_image') as loaded, patch.object(self.runtime, '_build_job') as built:
            self.runtime._prepare_job()
        loaded.assert_called_once_with(str(self.archive))
        built.assert_not_called()

    def test_damaged_archive_falls_back_to_building(self):
        with patch.dict(os.environ, {'WORKBENCH_IMAGE_ARCHIVE':str(self.archive)}), patch.object(self.runtime, 'status', return_value=self.ready_status()), \
             patch.object(self.runtime, '_load_image', side_effect=ValueError('broken')), patch.object(self.runtime, '_build_job') as built:
            self.runtime._prepare_job()
        built.assert_called_once()

    def test_missing_archive_setting_is_ignored(self):
        with patch.dict(os.environ, {'WORKBENCH_IMAGE_ARCHIVE':str(self.archive)+'.missing'}):
            self.assertIsNone(self.runtime.image_archive())

    def test_archive_is_streamed_into_docker_load_and_verified(self):
        process = MagicMock()
        process.stdin = io.BytesIO()
        process.stdin.close = MagicMock()
        process.wait.return_value = 0
        with patch.object(Runtime, 'docker', '/usr/bin/true'), patch('workbench.runtime.subprocess.Popen', return_value=process) as popen, \
             patch.object(self.runtime, '_run', return_value=MagicMock(returncode=0)) as run:
            self.runtime._load_image(str(self.archive))
        self.assertEqual(popen.call_args.args[0], ['/usr/bin/true', 'load'])
        self.assertEqual(len(process.stdin.getvalue()), 3 << 20)
        run.assert_called_with(['image', 'inspect', IMAGE], timeout=10, check=False)
        self.assertEqual(self.runtime.build_state, 'ready')
        self.assertIsNone(self.runtime.prepare_progress)

    def test_failed_load_reports_error_and_clears_progress(self):
        process = MagicMock()
        process.stdin = io.BytesIO()
        process.stdin.close = MagicMock()
        process.wait.return_value = 1
        with patch.object(Runtime, 'docker', '/usr/bin/true'), patch('workbench.runtime.subprocess.Popen', return_value=process), \
             patch.object(self.runtime, '_run', return_value=MagicMock(returncode=1)):
            with self.assertRaises(ValueError):
                self.runtime._load_image(str(self.archive))
        self.assertIsNone(self.runtime.prepare_progress)
        self.assertNotEqual(self.runtime.build_state, 'ready')


class StatsSamplingTests(unittest.TestCase):
    def test_only_existing_started_containers_are_sampled(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp))
            started, never_started, stopped = (store.create_environment(name, None)['id'] for name in ('a', 'b', 'c'))
            runtime = Runtime(store)
            rows = [{'Names':runtime.container_name(started), 'State':'running', 'Status':'Up'},
                    {'Names':runtime.container_name(stopped), 'State':'exited', 'Status':'Exited (0)'}]
            stats = json.dumps({'Name':runtime.container_name(started), 'CPUPerc':'12.5%', 'MemUsage':'300MiB / 2GiB', 'PIDs':'40'})
            with patch.object(runtime, 'containers', return_value=rows), patch.object(runtime, '_run', return_value=MagicMock(returncode=0, stdout=stats)) as run:
                metrics = runtime.monitor.collect(force=True)
            asked = run.call_args.args[0]
            self.assertIn(runtime.container_name(started), asked)
            self.assertNotIn(runtime.container_name(never_started), asked)
            self.assertNotIn(runtime.container_name(stopped), asked)
            self.assertEqual(metrics[started]['memory_mb'], 300)


class ControlApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.tmp.name), control_token='native-secret')
        self.client = TestClient(self.app, base_url='http://127.0.0.1:8766')

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def test_control_requires_native_secret_and_rejects_pages(self):
        self.assertEqual(self.client.get('/control/summary').status_code, 403)
        self.assertEqual(self.client.get('/control/summary', headers={'X-Workbench-Control':'wrong'}).status_code, 403)
        page = self.client.get('/control/summary', headers={'X-Workbench-Control':'native-secret', 'Origin':'http://127.0.0.1:8766'})
        self.assertEqual(page.status_code, 403)

    def test_page_token_does_not_open_control(self):
        html = self.client.get('/').text
        token = re.search(r'name="workbench-token" content="([^"]+)"', html).group(1)
        self.assertEqual(self.client.post('/control/stop-all', headers={'X-Workbench-Token':token}).status_code, 403)

    def test_summary_and_stop_all(self):
        headers = {'X-Workbench-Control':'native-secret'}
        with patch.object(self.app.state.runtime, 'active_objects', return_value={}):
            summary = self.client.get('/control/summary', headers=headers)
        self.assertEqual(summary.json(), {'running':0, 'paused':0, 'starting':0, 'names':[]})
        with patch.object(self.app.state.runtime, 'stop_all', return_value={'stopped':2, 'ok':True}) as stopped:
            self.assertEqual(self.client.post('/control/stop-all', headers=headers).json()['stopped'], 2)
        stopped.assert_called_once()

    def test_without_configured_secret_control_is_closed(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=False):
            os.environ.pop('WORKBENCH_CONTROL_TOKEN', None)
            client = TestClient(create_app(Path(tmp)), base_url='http://127.0.0.1:8766')
            self.assertEqual(client.get('/control/summary', headers={'X-Workbench-Control':''}).status_code, 403)
            client.close()

    def test_state_reports_app_version(self):
        html = self.client.get('/').text
        token = re.search(r'name="workbench-token" content="([^"]+)"', html).group(1)
        state = self.client.get('/api/state', headers={'X-Workbench-Token':token}).json()
        self.assertEqual(state['app']['version'], '0.7.2')
        self.assertIn('docker_download_url', state['runtime'])


class StopAllTests(unittest.TestCase):
    def test_paused_are_woken_and_all_started_are_stopped_in_one_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp))
            a, b = (store.create_environment(name, None)['id'] for name in ('a', 'b'))
            runtime = Runtime(store)
            objects = {a:{'State':{'Running':True}}, b:{'State':{'Running':True, 'Paused':True}}}
            with patch.object(runtime, 'active_objects', return_value=objects), patch.object(runtime, '_run', return_value=MagicMock(returncode=0)) as run:
                self.assertEqual(runtime.stop_all(), {'stopped':2, 'ok':True})
            calls = [c.args[0] for c in run.call_args_list]
            self.assertEqual(calls[0], ['unpause', runtime.container_name(b)])
            self.assertEqual(calls[1][:3], ['stop', '-t', '15'])
            self.assertEqual(set(calls[1][3:]), {runtime.container_name(a), runtime.container_name(b)})


class DesktopProcessTests(unittest.TestCase):
    def start(self, data):
        env = {**os.environ, 'WORKBENCH_CONTROL_TOKEN':'t'}
        return subprocess.Popen([sys.executable, '-m', 'workbench.desktop', '--data-dir', str(data), '--exit-on-stdin-eof', '--no-prepare'],
                                cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, text=True)

    def test_ready_line_lock_and_exit_when_app_pipe_closes(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = self.start(tmp)
            try:
                line = first.stdout.readline()
                self.assertTrue(line.startswith('WORKBENCH_READY '), line)
                port = json.loads(line.split(' ', 1)[1])['port']
                self.assertGreater(port, 0)
                second = self.start(tmp)
                self.assertTrue(second.stdout.readline().startswith('WORKBENCH_ERROR '))
                self.assertEqual(second.wait(timeout=20), 3)
                first.stdin.close()
                self.assertEqual(first.wait(timeout=20), 0)
            finally:
                if first.poll() is None:
                    first.kill()
                for process in (first, second):
                    for pipe in (process.stdin, process.stdout):
                        if not pipe.closed:
                            pipe.close()


if __name__ == '__main__':
    unittest.main()
