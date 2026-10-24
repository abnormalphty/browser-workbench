"""Importing an older data folder copies it and never changes the original."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from workbench import migrate
from workbench.store import Store


def tree(root):
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(root).rglob('*')) if p.is_file()}


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.source = base/'old'/'data'
        store = Store(self.source)
        self.env = store.create_environment('旧环境', None)
        store.set_setting('subscription_url', 'https://example.invalid/sub')
        profile = self.source/'environments'/self.env['id']/'profile'
        (profile/'firefox-standard').mkdir(parents=True)
        (profile/'firefox-standard'/'cookies.sqlite').write_bytes(b'cookie-bytes')
        (profile/'firefox-standard'/'lock').symlink_to('127.0.0.1:+42')
        self.target = base/'Application Support'/'BrowserWorkbench'
        self.before = tree(self.source)
        self.not_started = patch.object(migrate, '_started_containers', return_value=0)
        self.not_started.start()

    def tearDown(self):
        self.not_started.stop()
        self.tmp.cleanup()

    def test_inspect_counts_without_touching_source(self):
        info = migrate.inspect_source(self.source)
        self.assertEqual((info['environments'], info['nodes'], info['subscription']), (1, 0, True))
        self.assertEqual(info['scope'], hashlib.sha256(str(self.source.resolve()).encode()).hexdigest()[:12])
        self.assertEqual(tree(self.source), self.before)

    def test_copy_keeps_original_and_preserves_profile(self):
        result = migrate.copy_data(self.source, self.target)
        self.assertTrue(result['ok'])
        self.assertEqual(tree(self.source), self.before)
        copied = self.target/'environments'/self.env['id']/'profile'/'firefox-standard'
        self.assertEqual((copied/'cookies.sqlite').read_bytes(), b'cookie-bytes')
        self.assertTrue((copied/'lock').is_symlink())
        self.assertEqual(Store(self.target).get_environment(self.env['id'])['name'], '旧环境')
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o700)

    def test_empty_first_launch_folder_is_kept_aside_not_deleted(self):
        Store(self.target)
        result = migrate.copy_data(self.source, self.target)
        self.assertTrue(Path(result['previous']).is_dir())
        self.assertTrue((Path(result['previous'])/'workbench.sqlite3').exists())

    def test_never_overwrites_existing_app_data(self):
        Store(self.target).create_environment('新版环境', None)
        with self.assertRaises(migrate.MigrationError):
            migrate.copy_data(self.source, self.target)
        self.assertEqual(Store(self.target).list_environments()[0]['name'], '新版环境')

    def test_refuses_while_old_environments_run(self):
        with patch.object(migrate, '_started_containers', return_value=2):
            with self.assertRaises(migrate.MigrationError) as raised:
                migrate.copy_data(self.source, self.target)
        self.assertIn('2 个环境', str(raised.exception))
        self.assertFalse(self.target.exists())

    def test_refuses_when_docker_cannot_confirm(self):
        with patch.object(migrate, '_started_containers', return_value=None):
            with self.assertRaises(migrate.MigrationError):
                migrate.copy_data(self.source, self.target)

    def test_rejects_folder_that_is_not_workbench_data(self):
        with self.assertRaises(migrate.MigrationError):
            migrate.inspect_source(self.source.parent)

    def test_target_inside_source_is_rejected(self):
        with self.assertRaises(migrate.MigrationError):
            migrate.copy_data(self.source, self.source/'nested')

    def test_cli_prints_json_errors(self):
        with patch('builtins.print') as printed:
            self.assertEqual(migrate.main(['inspect', str(self.source.parent)]), 1)
        self.assertFalse(json.loads(printed.call_args.args[0])['ok'])


if __name__ == '__main__':
    unittest.main()
