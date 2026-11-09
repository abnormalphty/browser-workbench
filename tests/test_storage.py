"""Where things are kept, and moving the data folder (workbench/storage.py, workbench/relocate.py)."""
import contextlib
import io
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from test_docker_setup import FakeRegistry, on_windows
from workbench import relocate, storage
from workbench.app import create_app
from workbench.runtime import Runtime
from workbench.store import Store


def fill(folder, database=True):
    """A small data folder: database, an environment's transfer files, an empty folder."""
    (folder / 'environments' / 'empty').mkdir(parents=True, exist_ok=True)
    if database:
        (folder / 'workbench.sqlite3').write_bytes(b'SQLite format 3\x00' + bytes(range(256)) * 40)
    transfer = folder / 'environments' / 'env1' / 'profile' / 'transfer' / 'downloads'
    transfer.mkdir(parents=True, exist_ok=True)
    (transfer / '报告 1.pdf').write_bytes(b'%PDF' + b'x' * 3000)
    (folder / 'environments' / 'env1' / 'config').mkdir(exist_ok=True)
    (folder / 'setup').mkdir(exist_ok=True)
    return folder


class SizeTests(unittest.TestCase):
    def test_docker_sizes_are_decimal(self):
        self.assertEqual(storage.parse_size('0B'), 0)
        self.assertEqual(storage.parse_size('45.2MB'), 45_200_000)
        self.assertEqual(storage.parse_size('512kB'), 512_000)
        self.assertEqual(storage.parse_size('1.5GB'), 1_500_000_000)
        self.assertIsNone(storage.parse_size('N/A'))

    def test_volume_sizes_come_from_docker_system_df(self):
        answer = json.dumps({'Images': [], 'Volumes': [{'Name': 'workbench-abc-1', 'Links': '0', 'Size': '120.5MB'},
                                                        {'Name': 'other', 'Size': 'N/A'}]})
        with patch('subprocess.run', return_value=SimpleNamespace(returncode=0, stdout=answer + '\n')) as run:
            self.assertEqual(storage.volume_sizes('docker'), {'workbench-abc-1': 120_500_000})
        self.assertEqual(run.call_args.args[0][:4], ['docker', 'system', 'df', '-v'])
        with patch('subprocess.run', return_value=SimpleNamespace(returncode=1, stdout='')):
            self.assertEqual(storage.volume_sizes('docker'), {})  # Docker not running
        self.assertEqual(storage.volume_sizes(None), {})

    def test_folder_sizes_skip_links(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = fill(Path(temp) / 'Data')
            expected = sum(path.stat().st_size for path in folder.rglob('*') if path.is_file())
            os.symlink(folder, folder / 'loop')
            self.assertEqual(storage.folder_size(folder), expected)
            self.assertEqual(storage.folder_size(Path(temp) / 'missing'), 0)


class DockerDiskTests(unittest.TestCase):
    def test_says_where_docker_desktop_keeps_or_would_keep_its_disk(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            wsl = base / 'Docker' / 'wsl'
            (wsl / 'disk').mkdir(parents=True)
            (wsl / 'disk' / 'docker_data.vhdx').write_bytes(b'x' * 10)
            (wsl / 'main').mkdir()
            (wsl / 'main' / 'ext4.vhdx').write_bytes(b'x' * 5)
            (wsl / 'main' / 'notes.txt').write_bytes(b'x' * 100)
            with on_windows(), patch.object(storage, 'wsl_data_dir', return_value=wsl), \
                 patch.dict(os.environ, {'WORKBENCH_DATA_ROOT': str(base / 'chosen')}):
                installed = storage.docker_disk()
                planned = storage.docker_disk(installed=False)
            self.assertEqual((installed['folder'], installed['bytes'], installed['installed']), (str(wsl), 15, True))
            # Not installed yet: where the app would install it, next to the chosen data folder.
            self.assertEqual((planned['folder'], planned['bytes'], planned['installed']), (str(base / 'chosen' / 'Docker'), None, False))
            with on_windows(), patch.object(storage, 'wsl_data_dir', return_value=wsl), \
                 patch.dict(os.environ, {'WORKBENCH_DATA_ROOT': str(storage.DEFAULT_ROOT)}):
                self.assertEqual(storage.docker_disk(installed=False)['folder'], str(wsl))
        with patch('sys.platform', 'darwin'):
            self.assertIsNone(storage.docker_disk())


class MoveTargetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.store = Store(self.base / 'old' / 'Data')
        fill(self.store.data_dir, database=False)

    def tearDown(self):
        self.temp.cleanup()

    def target(self, chosen, **env):
        with patch.dict(os.environ, env):
            return storage.move_target(self.store, str(chosen))

    def test_an_empty_or_new_folder_is_used_as_it_is(self):
        result = self.target(self.base / 'new place')
        self.assertEqual(result['data_dir'], str(self.base / 'new place' / 'Data'))
        self.assertGreater(result['bytes'], 10000)
        self.assertFalse((self.base / 'new place').exists())  # made for the check, then removed again

    def test_a_folder_with_other_things_gets_a_subfolder(self):
        busy = self.base / 'D'
        busy.mkdir()
        (busy / 'photos').mkdir()
        self.assertEqual(self.target(busy)['data_dir'], str(busy / 'BrowserWorkbench' / 'Data'))

    def test_places_that_do_not_work(self):
        cases = [
            (self.base / 'old', '已经在这个位置'),                     # the current place
            (self.base / 'old' / 'Data' / 'inner', '不能在现在的数据文件夹里面'),
            ('relative/place', '完整的文件夹位置'),
        ]
        for chosen, message in cases:
            with self.subTest(chosen=chosen), self.assertRaises(ValueError) as caught:
                self.target(chosen)
            self.assertIn(message, str(caught.exception))
        program = self.base / 'Programs' / 'Browser Workbench'
        with self.assertRaises(ValueError) as caught:
            self.target(program / 'data', WORKBENCH_INSTALL_DIR=str(program))
        self.assertIn('程序文件夹', str(caught.exception))
        taken = self.base / 'taken'
        fill(taken / 'Data')
        # Holds a data folder of its own (an old copy, say): ours goes into a subfolder, never mixed in.
        self.assertEqual(self.target(taken)['data_dir'], str(taken / 'BrowserWorkbench' / 'Data'))
        with patch.object(storage, 'free_space', return_value=1024):
            with self.assertRaises(ValueError) as caught:
                self.target(self.base / 'small')
        self.assertIn('空间不够', str(caught.exception))

    def test_an_existing_workbench_data_folder_is_never_mixed_into(self):
        taken = self.base / 'taken'
        fill(taken / 'BrowserWorkbench' / 'Data')
        (taken / 'other').mkdir()
        with self.assertRaises(ValueError) as caught:
            self.target(taken)
        self.assertIn('已经有一份工作台数据', str(caught.exception))

    def test_network_places_are_refused(self):
        self.assertTrue(storage.remote_drive('\\\\server\\share\\data'))
        self.assertFalse(storage.remote_drive(self.base))


class RelocateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.source = fill(self.base / 'old' / 'Data')
        self.before = relocate.listing(self.source)

    def tearDown(self):
        self.temp.cleanup()

    def test_moves_checks_and_keeps_the_old_copy_under_a_clear_name(self):
        seen = []
        record = relocate.relocate(self.source, self.base / 'new', progress=lambda done, work: seen.append(done * 100 // work))
        target = self.base / 'new' / 'Data'
        self.assertEqual({k: v for k, v in relocate.listing(target).items() if k != storage.MOVE_RECORD}, self.before)
        self.assertEqual((target / 'workbench.sqlite3').read_bytes(), (self.base / 'old' / storage.OLD_COPY / 'workbench.sqlite3').read_bytes())
        self.assertFalse(self.source.exists())  # renamed: nothing opens it by mistake
        self.assertEqual(record['old_copies'], [str(self.base / 'old' / storage.OLD_COPY)])
        self.assertEqual(storage.old_copies(target), record['old_copies'])
        self.assertEqual(seen[-1], 100)
        self.assertEqual(seen, sorted(seen))

    def test_a_copy_that_does_not_check_out_changes_nothing(self):
        real = relocate.listing
        calls = []
        def listing(folder):
            calls.append(folder)
            found = real(folder)
            return {**found, 'extra': 1} if len(calls) == 2 else found
        with patch.object(relocate, 'listing', side_effect=listing), self.assertRaises(ValueError):
            relocate.relocate(self.source, self.base / 'new')
        self.assertEqual(relocate.listing(self.source), self.before)
        self.assertEqual(list((self.base / 'new').iterdir()), [])  # copy removed

    def test_a_damaged_copy_is_noticed(self):
        real_copy = relocate.shutil.copystat
        def damage(source, target):
            real_copy(source, target)
            if Path(target).name == 'workbench.sqlite3':
                with open(target, 'r+b') as file:
                    file.write(b'X')
        with patch.object(relocate.shutil, 'copystat', side_effect=damage), self.assertRaises(ValueError):
            relocate.relocate(self.source, self.base / 'new')
        self.assertTrue(self.source.is_dir())
        self.assertFalse((self.base / 'new' / 'Data').exists())

    def test_the_new_place_is_remembered_before_the_old_folder_is_renamed(self):
        registry = FakeRegistry()
        with on_windows(), patch.dict('sys.modules', {'winreg': registry}):
            relocate.relocate(self.source, self.base / 'new', keep=True)
        self.assertEqual(registry.values[('HKCU', relocate.SETTINGS_KEY)]['DataLocation'], str(self.base / 'new'))
        # Could not be remembered: the app keeps using the old folder, the copy goes.
        source = fill(self.base / 'again' / 'Data')
        broken = FakeRegistry()
        broken.CreateKey = lambda *args: (_ for _ in ()).throw(PermissionError('denied'))
        with on_windows(), patch.dict('sys.modules', {'winreg': broken}), self.assertRaises(PermissionError):
            relocate.relocate(source, self.base / 'elsewhere', keep=True)
        self.assertTrue((source / 'workbench.sqlite3').is_file())
        self.assertFalse((self.base / 'elsewhere' / 'Data').exists())

    def test_refuses_a_place_holding_data_or_overlapping(self):
        fill(self.base / 'taken' / 'Data')
        with self.assertRaises(ValueError):
            relocate.relocate(self.source, self.base / 'taken')
        with self.assertRaises(ValueError):
            relocate.relocate(self.source, self.source / 'inner')
        self.assertEqual(relocate.listing(self.source), self.before)

    def test_a_folder_held_for_a_moment_is_renamed_once_free(self):
        source = fill(self.base / 'old' / 'Data')
        real, calls = Path.rename, []

        def held_at_first(path, target):
            calls.append(path.name)
            if len(calls) <= 2:  # a virus scan holds a file just written
                raise PermissionError(13, 'in use')
            return real(path, target)
        with patch.object(Path, 'rename', held_at_first), patch.object(relocate, 'RENAME_WAIT', 0):
            relocate.relocate(source, self.base / 'new')
        self.assertTrue((self.base / 'new' / 'Data' / 'workbench.sqlite3').is_file())
        self.assertTrue((self.base / 'old' / storage.OLD_COPY).is_dir())
        self.assertEqual(calls[:3], ['Data.partial'] * 3)
        # Held for good: the move is undone and the old folder keeps being used.
        source = fill(self.base / 'again' / 'Data')
        with patch.object(Path, 'rename', side_effect=PermissionError(13, 'in use')), patch.object(relocate, 'RENAME_WAIT', 0), \
             self.assertRaises(PermissionError):
            relocate.relocate(source, self.base / 'elsewhere')
        self.assertFalse((self.base / 'elsewhere' / 'Data').exists())
        self.assertFalse((self.base / 'elsewhere' / 'Data.partial').exists())
        self.assertTrue((source / 'workbench.sqlite3').is_file())

    def test_moving_again_lists_every_old_copy(self):
        relocate.relocate(self.source, self.base / 'second')
        record = relocate.relocate(self.base / 'second' / 'Data', self.base / 'third')
        self.assertEqual(record['old_copies'], [str(self.base / 'old' / storage.OLD_COPY), str(self.base / 'second' / storage.OLD_COPY)])

    def test_command_line_reports_progress_and_result(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = relocate.main(['--from', str(self.source), '--to', str(self.base / 'new')])
        lines = [json.loads(line.split(' ', 1)[1]) for line in output.getvalue().splitlines()]
        self.assertEqual(code, 0)
        self.assertTrue(lines[-1]['ok'])
        self.assertIn('progress', lines[0])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = relocate.main(['--from', str(self.base / 'missing'), '--to', str(self.base / 'x')])
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(output.getvalue().split(' ', 1)[1])['ok'])


class ScopeTests(unittest.TestCase):
    def test_docker_names_survive_a_move(self):
        with tempfile.TemporaryDirectory() as temp:
            old = Path(temp) / 'old' / 'Data'
            store = Store(old)
            import hashlib
            legacy = hashlib.sha256(str(store.data_dir).encode()).hexdigest()[:12]
            self.assertEqual(store.runtime_scope(), legacy)  # what earlier versions named things
            self.assertEqual(Runtime(store).container_name('a' * 32), f'local-browser-{legacy}-' + 'a' * 32)
            relocate.relocate(old, Path(temp) / 'new')
            moved = Store(Path(temp) / 'new' / 'Data')
            self.assertEqual(moved.runtime_scope(), legacy)
            self.assertEqual(Runtime(moved).profile_volume('a' * 32), f'workbench-{legacy}-' + 'a' * 32)


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.app = create_app(self.base / 'root' / 'Data')
        self.client = TestClient(self.app, base_url='http://127.0.0.1:8766')
        token = re.search(r'name="workbench-token" content="([^"]+)"', self.client.get('/').text).group(1)
        self.headers = {'X-Workbench-Token': token}
        self.store = self.app.state.store

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def test_overview_lists_the_places(self):
        env = self.store.create_environment('工作', None)
        with patch.dict(os.environ, {'WORKBENCH_DATA_ROOT': str(self.base / 'root'), 'WORKBENCH_MODE': 'desktop',
                                     'WORKBENCH_INSTALL_DIR': str(self.base / 'program')}), \
             patch.object(storage, 'volume_sizes', return_value={}), on_windows(), \
             patch.object(storage, 'docker_disk', return_value={'folder': 'C:/Users/u/AppData/Local/Docker/wsl', 'bytes': 5, 'free_bytes': 9}) as disk, \
             patch.object(Runtime, 'docker', None):
            response = self.client.get('/api/storage', headers=self.headers)
        disk.assert_called_once_with(False)  # Docker Desktop not installed: where it would go
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result['data_dir'], str(self.store.data_dir))
        self.assertEqual(result['install_dir'], str(self.base / 'program'))
        self.assertTrue(result['can_move'])
        self.assertTrue(result['profiles_in_docker'])
        self.assertEqual(result['environments'][0]['name'], '工作')
        self.assertEqual(result['environments'][0]['volume'], self.app.state.runtime.profile_volume(env['id']))
        with patch('sys.platform', 'darwin'), patch.dict(os.environ, {}, clear=False):
            os.environ.pop('WORKBENCH_DATA_ROOT', None)
            self.assertFalse(self.client.get('/api/storage', headers=self.headers).json()['can_move'])

    def test_check_open_and_delete_old_copies(self):
        response = self.client.post('/api/storage/check', json={'path': str(self.base / 'elsewhere')}, headers=self.headers)
        self.assertEqual(response.json()['data_dir'], str(self.base / 'elsewhere' / 'Data'))
        response = self.client.post('/api/storage/check', json={'path': str(self.base / 'root')}, headers=self.headers)
        self.assertEqual(response.status_code, 400)
        with patch('workbench.system.open_folder') as opened:
            self.assertEqual(self.client.post('/api/storage/open', json={'which': 'data'}, headers=self.headers).status_code, 200)
            self.assertEqual(self.client.post('/api/storage/open', json={'which': 'old', 'folder': str(self.base)},
                                              headers=self.headers).status_code, 400)
        opened.assert_called_once()
        old = self.base / 'root' / storage.OLD_COPY
        fill(old)
        (self.store.data_dir / storage.MOVE_RECORD).write_text(json.dumps({'old_copies': [str(old)]}), encoding='utf-8')
        refused = self.client.post('/api/storage/delete-old', json={'folder': str(self.store.data_dir)}, headers=self.headers)
        self.assertEqual(refused.status_code, 400)
        self.assertTrue(self.store.data_dir.is_dir())
        deleted = self.client.post('/api/storage/delete-old', json={'folder': str(old)}, headers=self.headers)
        self.assertEqual(deleted.status_code, 200)
        self.assertFalse(old.exists())
        self.assertEqual(storage.old_copies(self.store.data_dir), [])


if __name__ == '__main__':
    unittest.main()
