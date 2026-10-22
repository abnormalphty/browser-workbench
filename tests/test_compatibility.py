import inspect
import sqlite3
import tempfile
import unittest
from pathlib import Path

from workbench.store import Store


class CompatibilityTests(unittest.TestCase):
    def test_new_environment_can_select_standard_firefox(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            self.assertIn('engine', inspect.signature(store.create_environment).parameters)
            environment = store.create_environment('兼容验证', None, engine='firefox')
            self.assertEqual(store.get_environment(environment['id'])['engine'], 'firefox')
            self.assertEqual(store.public_state()['environments'][0]['engine'], 'firefox')

    def test_new_environment_defaults_to_standard_firefox(self):
        with tempfile.TemporaryDirectory() as directory:
            env=Store(Path(directory)).create_environment('默认环境',None)
            self.assertEqual(env['engine'],'firefox')

    def test_removed_camoufox_engine_cannot_be_created(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError,'Firefox'):
                Store(Path(directory)).create_environment('旧内核',None,engine='camoufox')

    def test_unknown_engine_cannot_be_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIn('engine', inspect.signature(Store.create_environment).parameters)
            with self.assertRaises(ValueError):
                Store(Path(directory)).create_environment('x', None, engine='arbitrary-command')

    def test_existing_database_keeps_environment_and_defaults_to_camoufox(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            with sqlite3.connect(path/'workbench.sqlite3') as db:
                db.execute('CREATE TABLE environments (id TEXT PRIMARY KEY, name TEXT NOT NULL, node_id TEXT, fingerprint_seed TEXT NOT NULL, created_at REAL NOT NULL)')
                db.execute('INSERT INTO environments VALUES (?,?,?,?,?)', ('a'*32, '保留数据', None, 'existing-seed', 1))
            store = Store(path)
            environment = store.get_environment('a'*32)
            self.assertIn('engine', environment)
            self.assertEqual(environment['engine'], 'camoufox')
            self.assertEqual(environment['fingerprint_seed'], 'existing-seed')
            self.assertEqual(environment['name'], '保留数据')
            from workbench.runtime import Runtime
            from unittest.mock import patch
            runtime=Runtime(store)
            with patch.object(runtime,'_run',side_effect=AssertionError('No container changes allowed')):
                with self.assertRaisesRegex(ValueError,'旧内核已移除'):
                    runtime.start(environment['id'])
            self.assertEqual(store.get_environment(environment['id'])['fingerprint_seed'],'existing-seed')


class NativeFirefoxTests(unittest.TestCase):
    def test_manual_proxy_covers_http_https_and_has_no_direct_failover(self):
        import importlib.util
        self.assertIsNotNone(importlib.util.find_spec('runtime.native_firefox'))
        from runtime.native_firefox import firefox_preferences
        prefs = firefox_preferences(False)
        self.assertEqual(prefs['network.proxy.type'], 1)
        for scheme in ['http', 'ssl']:
            self.assertEqual(prefs['network.proxy.'+scheme], '127.0.0.1')
            self.assertEqual(prefs['network.proxy.'+scheme+'_port'], 7890)
        self.assertFalse(prefs['network.proxy.failover_direct'])
        self.assertIs(prefs.get('media.peerconnection.enabled'), False)
        self.assertEqual(prefs['network.proxy.no_proxies_on'], '')
        self.assertNotIn('general.useragent.override', prefs)
        self.assertNotIn('marionette.enabled', prefs)

    def test_direct_connection_requires_explicit_test_mode(self):
        import importlib.util
        self.assertIsNotNone(importlib.util.find_spec('runtime.native_firefox'))
        from runtime.native_firefox import firefox_preferences
        self.assertEqual(firefox_preferences(True)['network.proxy.type'], 0)


class NativeShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def test_stopping_closes_all_windows_without_forcing_the_browser(self):
        from runtime.native_firefox import NativeFirefox
        browser = NativeFirefox(False)
        windows = {'10', '20'}

        class Process:
            forced = False
            def poll(self): return None
            def wait(self, timeout=None):
                if windows and not self.forced:
                    import subprocess
                    raise subprocess.TimeoutExpired('firefox', timeout)
                return 0
            def terminate(self): self.forced = True
            def kill(self): self.forced = True

        def command(*args, **kwargs):
            if args[0] == 'xdotool': return '\n'.join(sorted(windows))
            if args[0] == 'wmctrl': windows.discard(args[-1])
            return ''

        browser.window = '10'
        browser.process = Process()
        browser.command = command
        await browser.stop()
        self.assertFalse(browser.process.forced)
        self.assertEqual(windows, set())


if __name__ == '__main__':
    unittest.main()
