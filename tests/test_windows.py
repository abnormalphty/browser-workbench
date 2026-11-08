"""Windows-only branches, exercised on any machine by reporting win32 as the platform."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from workbench import docker_env, system
from workbench.runtime import IMAGE, Runtime
from workbench.store import Store


def on_windows():
    return patch('sys.platform', 'win32')


def on_mac():
    return patch('sys.platform', 'darwin')


class WindowsDockerTests(unittest.TestCase):
    def test_docker_desktop_is_found_where_its_installer_puts_it(self):
        # Per user (the installer's default since 4.83) and for all users.
        self.assertEqual([root.parts[-2:] for root in docker_env.WINDOWS_ROOTS], [('Programs', 'DockerDesktop'), ('Docker', 'Docker')])
        for root in docker_env.WINDOWS_ROOTS:
            exe = str(root/'resources'/'bin'/'docker.exe')
            with on_windows(), patch('shutil.which', return_value=None), \
                 patch('os.path.isfile', side_effect=lambda path, exe=exe: path == exe), patch('os.access', return_value=True):
                self.assertEqual(docker_env.find_cli(), exe)
            app = str(root/'Docker Desktop.exe')
            with on_windows(), patch.object(Path, 'is_file', lambda self, app=app: str(self) == app):
                self.assertEqual(docker_env.engine_app(), {'name': 'Docker Desktop', 'path': app})

    def test_a_custom_install_folder_comes_from_the_uninstall_entry(self):
        from test_docker_setup import FakeRegistry  # tests/ is on the path under unittest discover
        registry = FakeRegistry({('HKCU', docker_env.UNINSTALL_KEY): {'InstallLocation': '"D:\\Apps\\Docker"'}})
        with patch.dict('sys.modules', {'winreg': registry}):
            roots = docker_env.windows_roots()
        self.assertEqual(roots[0], Path('D:\\Apps\\Docker'))
        self.assertEqual(roots[1:], list(docker_env.WINDOWS_ROOTS))

    def test_docker_commands_get_the_cli_folder_first_and_no_mac_paths(self):
        # No drive letter here: off Windows the path separator is ':' too.
        cli = os.path.join('Program Files', 'Docker', 'Docker', 'resources', 'bin', 'docker.exe')
        with on_windows(), patch.dict(os.environ, {'PATH': os.pathsep.join(['first', 'second'])}):
            parts = docker_env.command_env(cli)['PATH'].split(os.pathsep)
        self.assertEqual(parts, [os.path.dirname(cli), 'first', 'second'])

    def test_download_link_is_the_windows_installer(self):
        with on_windows():
            self.assertEqual(docker_env.download_url(), 'https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe')

    def test_child_processes_never_open_a_console_window(self):
        with on_windows():
            self.assertEqual(system.quiet(), {'creationflags': 0x08000000})
        with on_mac():
            self.assertEqual(system.quiet(), {})

    def test_folders_and_docker_desktop_open_through_the_shell(self):
        with on_windows(), patch('os.startfile', create=True) as start:
            system.open_folder(Path('transfer'))
        start.assert_called_once_with('transfer')
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(Store(Path(tmp)))
            app = {'name': 'Docker Desktop', 'path': r'C:\Program Files\Docker\Docker\Docker Desktop.exe'}
            with on_windows(), patch('workbench.runtime.engine_app', return_value=app), patch('os.startfile', create=True) as start:
                runtime._open_desktop()
            start.assert_called_once_with(app['path'])

    def test_data_folder_lock_admits_one_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = system.hold_lock(Path(tmp)/'.workbench.lock')
            self.assertIsNotNone(first)
            self.assertIsNone(system.hold_lock(Path(tmp)/'.workbench.lock'))
            first.close()
            again = system.hold_lock(Path(tmp)/'.workbench.lock')
            self.assertIsNotNone(again)
            again.close()


class WindowsFileNameTests(unittest.TestCase):
    def test_names_windows_cannot_store_are_refused_only_there(self):
        from workbench.transfers import checked_name
        for name in ['a:b.txt', 'what?.pdf', 'CON', 'nul.txt', 'com1.log', 'trailing.', 'trailing ', 'pipe|name']:
            with self.subTest(name=name), on_windows(), self.assertRaises(ValueError):
                checked_name(name)
        for name in ['报告 (2).pdf', 'console.txt', 'a.b.c']:
            with self.subTest(name=name), on_windows():
                self.assertEqual(checked_name(name), name)
        with on_mac():
            self.assertEqual(checked_name('a:b.txt'), 'a:b.txt')  # a valid name on the Mac


class WindowsProfileStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name))
        self.runtime = Runtime(self.store)
        self.env = self.store.create_environment('卷测试', None)

    def tearDown(self):
        self.tmp.cleanup()

    def start(self):
        calls = []
        def run(args, **options):
            calls.append(args)
            if args[0] == 'run':
                raise ValueError('stopped by the test')
            return MagicMock(returncode=0, stdout='')
        with patch.object(self.runtime, '_run', side_effect=run):
            self.runtime._start_job(self.store.get_environment(self.env['id']), {}, True)
        return calls

    def test_windows_keeps_profiles_in_a_volume_and_transfers_on_disk(self):
        with on_windows():
            self.assertTrue(self.runtime.volume_profiles())
            calls = self.start()
        volume = self.runtime.profile_volume(self.env['id'])
        self.assertIn(['volume', 'create', '--label', f'workbench.scope={self.runtime.scope}', '--label', f'workbench.environment={self.env["id"]}', volume], calls)
        run = next(c for c in calls if c[0] == 'run')
        _, profile = self.runtime.environment_paths(self.env['id'])
        self.assertIn(f'type=volume,source={volume},target=/profile', run)
        self.assertIn(f'type=bind,source={profile/"transfer"},target=/profile/transfer', run)
        self.assertEqual(run[-1], IMAGE)
        self.assertTrue((profile/'transfer'/'incoming').is_dir() and (profile/'transfer'/'downloads').is_dir())

    def test_mac_keeps_the_whole_profile_in_the_data_folder(self):
        with on_mac():
            self.assertFalse(self.runtime.volume_profiles())
            run = next(c for c in self.start() if c[0] == 'run')
        _, profile = self.runtime.environment_paths(self.env['id'])
        self.assertIn(f'type=bind,source={profile},target=/profile', run)
        self.assertFalse(any('type=volume' in part for part in run))

    def test_deleting_an_environment_removes_its_profile_volume(self):
        calls = []
        with patch.object(self.runtime, 'stop'), patch.object(self.runtime, '_run', side_effect=lambda args, **o: calls.append(args) or MagicMock(returncode=0)):
            self.runtime.delete(self.env['id'])
        self.assertIn(['volume', 'rm', '-f', self.runtime.profile_volume(self.env['id'])], calls)


if __name__ == '__main__':
    unittest.main()
