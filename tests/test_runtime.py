import tempfile
import unittest
from pathlib import Path

from workbench.runtime import build_proxy_config, Runtime
from workbench.store import Store


class RuntimeTests(unittest.TestCase):
    def test_proxy_config_only_routes_to_selected_node(self):
        n = {'name': 'original', 'type': 'trojan', 'server': 'proxy.example', 'port': 443, 'password': 'secret'}
        c = build_proxy_config(n)
        self.assertEqual(len(c['proxies']), 1)
        self.assertEqual(c['proxies'][0]['name'], 'environment-node')
        self.assertEqual(c['rules'], ['MATCH,environment-node'])
        self.assertEqual(c['bind-address'], '127.0.0.1')
        self.assertNotIn('external-controller', c)
        self.assertNotIn('proxy-providers', c)

    def test_unconfigured_environment_cannot_silently_use_direct_connection(self):
        with self.assertRaises(ValueError):
            build_proxy_config(None)

    def test_runtime_labels_are_scoped_to_environment(self):
        with tempfile.TemporaryDirectory() as td:
            store = Store(Path(td))
            env = store.create_environment('test', None)
            runtime = Runtime(store)
            self.assertTrue(runtime.container_name(env['id']).startswith('local-browser-'))
            with self.assertRaises(ValueError):
                runtime.container_name('../someone-else')

    def test_browser_profile_directory_is_separate_from_launch_config(self):
        with tempfile.TemporaryDirectory() as td:
            store = Store(Path(td))
            e = store.create_environment('test', None)
            r = Runtime(store)
            launch, profile = r.environment_paths(e['id'])
            self.assertNotEqual(launch, profile)
            self.assertEqual(profile.name, 'profile')
            self.assertEqual(launch.name, 'config')


if __name__ == '__main__':
    unittest.main()
