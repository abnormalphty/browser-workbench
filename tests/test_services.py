import importlib.util
import json
from pathlib import Path
import re
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from workbench import services
from workbench.app import create_app
from workbench.store import Store


def browser_component(name):
    """A module of the browser component (runtime/), loaded from its file."""
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / 'runtime' / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


opening_page = browser_component('native_firefox').opening_page


class WebsiteTests(unittest.TestCase):
    """An environment is made for one AI website: the page it opens and the plans its account can have."""

    def test_known_websites_and_other_addresses(self):
        self.assertEqual(services.service_id(None), 'claude')
        self.assertEqual(services.service_id('chatgpt'), 'chatgpt')
        with self.assertRaisesRegex(ValueError, '网站'):
            services.service_id('openai.com')
        self.assertEqual(services.check_url(' example.com/chat '), 'https://example.com/chat')
        self.assertEqual(services.check_url('https://chat.example.org:8443/a?b=c'), 'https://chat.example.org:8443/a?b=c')
        for bad in ('', 'http://example.com/', 'ftp://example.com/', 'https://user:pass@example.com/', 'https://exa mple.com/',
                    'https://example.com:99999/', 'javascript:alert(1)'):
            with self.assertRaises(ValueError, msg=bad):
                services.check_url(bad)
        for inside in ('https://localhost/', 'https://127.0.0.1/', 'https://192.168.1.2/', 'https://[::1]/', 'https://intranet/',
                       'https://10.0.0.8:8080/'):
            with self.assertRaisesRegex(ValueError, '局域网', msg=inside):
                services.check_url(inside)

    def test_every_website_has_a_page_and_plans(self):
        listed = services.catalog()
        self.assertEqual(listed[0]['id'], 'claude')
        self.assertTrue(listed[0]['check'])
        for site in listed:
            self.assertTrue(site['plans'] and site['plans'][-1]['id'] == 'other', site['id'])
            if site['id'] != 'custom':
                self.assertTrue(site['url'].startswith('https://'), site['id'])
                self.assertFalse(site['check'] and site['id'] != 'claude')
        self.assertEqual(services.start_url({'service': 'chatgpt'}), 'https://chatgpt.com/')
        self.assertEqual(services.start_url({}), 'https://claude.ai/')
        self.assertEqual(services.start_url({'service': 'custom', 'start_url': 'https://example.com/'}), 'https://example.com/')

    def test_the_browser_component_opens_the_named_page(self):
        self.assertEqual(opening_page(False, 'https://chatgpt.com/'), 'https://chatgpt.com/')
        self.assertEqual(opening_page(True, 'https://chatgpt.com/'), 'file:///app/welcome.html')
        for unusable in (None, '', 'http://chatgpt.com/', 'https://a b/', 'file:///etc/passwd', 42):
            self.assertEqual(opening_page(False, unusable), 'https://claude.ai/', unusable)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)

    def test_environments_from_before_stay_claude_ones(self):
        db = sqlite3.connect(self.data / 'workbench.sqlite3')
        db.executescript('''CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE nodes (id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE environments (id TEXT PRIMARY KEY, name TEXT NOT NULL, node_id TEXT, fingerprint_seed TEXT NOT NULL,
                created_at REAL NOT NULL, engine TEXT NOT NULL DEFAULT 'firefox', timezone_mode TEXT NOT NULL DEFAULT 'node',
                cpu_limit REAL NOT NULL DEFAULT 2, memory_limit_mb INTEGER NOT NULL DEFAULT 2048);
            INSERT INTO environments (id, name, fingerprint_seed, created_at) VALUES ('{0}', '旧环境', 'seed', 1);
            INSERT INTO settings VALUES ('account:{0}', '{{"label": "a@example.com", "plan": "max", "status": "active"}}');'''
                       .format('a' * 32))
        db.commit()
        db.close()
        store = Store(self.data)
        env = store.get_environment('a' * 32)
        self.assertEqual((env['service'], env['start_url'], env['name']), ('claude', None, '旧环境'))
        self.assertEqual(store.account_info('a' * 32)['plan'], 'max')

    def test_plans_follow_the_website(self):
        store = Store(self.data)
        env = store.create_environment('GPT', None, service='chatgpt')
        self.assertEqual((env['service'], env['start_url']), ('chatgpt', None))
        store.save_account_info(env['id'], {'label': 'gpt@example.com', 'plan': 'plus', 'status': 'active'})
        with self.assertRaisesRegex(ValueError, '套餐'):
            store.save_account_info(env['id'], {'label': '', 'plan': 'max', 'status': 'active'})  # Claude's, not ChatGPT's
        # Another website: the sign-in data stays, the recorded plan and status do not.
        store.update_environment(env['id'], 'GPT', None, service='gemini')
        account = store.account_info(env['id'])
        self.assertEqual((account['label'], account['plan'], account['status']), ('gpt@example.com', 'unknown', 'unknown'))
        self.assertIn('Gemini', account['note'])
        store.update_environment(env['id'], '改名', None)  # website left out: unchanged
        self.assertEqual(store.get_environment(env['id'])['service'], 'gemini')
        custom = store.create_environment('别的', None, service='custom', start_url='chat.example.com')
        self.assertEqual(custom['start_url'], 'https://chat.example.com')
        with self.assertRaisesRegex(ValueError, 'https'):
            store.create_environment('别的', None, service='custom', start_url='')
        self.assertEqual(store.create_environment('C', None, service='claude', start_url='https://ignored.example/')['start_url'], None)

    def test_the_start_page_reaches_the_environment(self):
        from workbench.runtime import Runtime
        store = Store(self.data)
        runtime = Runtime(store)
        env = store.create_environment('GPT', None, service='chatgpt')

        def run(args, **options):
            if args[0] == 'run':
                raise ValueError('stopped by the test')
            return MagicMock(returncode=0, stdout='')
        with patch.object(runtime, '_run', side_effect=run):
            runtime._start_job(store.get_environment(env['id']), {}, False)
        launch = json.loads((runtime.environment_paths(env['id'])[0] / 'launch.json').read_text())
        self.assertEqual(launch['start_url'], 'https://chatgpt.com/')

    def test_only_claude_can_be_checked_automatically(self):
        from workbench.accounts import check_account
        from workbench.runtime import Runtime
        store = Store(self.data)
        env = store.create_environment('GPT', None, service='chatgpt')
        with self.assertRaisesRegex(ValueError, '手动记录'):
            check_account(Runtime(store), env['id'])


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_app(Path(self.temp.name))
        self.client = TestClient(self.app, base_url='http://127.0.0.1:8766')
        self.addCleanup(self.client.close)
        token = re.search(r'name="workbench-token" content="([^"]+)"', self.client.get('/').text).group(1)
        self.headers = {'X-Workbench-Token': token}

    def test_environments_for_other_websites(self):
        state = self.client.get('/api/state', headers=self.headers).json()
        self.assertIn('chatgpt', [site['id'] for site in state['services']])
        made = self.client.post('/api/environments', json={'name': 'GPT', 'service': 'chatgpt'}, headers=self.headers)
        self.assertEqual(made.status_code, 200)
        self.assertEqual(made.json()['service'], 'chatgpt')
        refused = self.client.post('/api/environments', json={'name': 'x', 'service': 'custom', 'start_url': 'https://192.168.0.1/'},
                                   headers=self.headers)
        self.assertEqual(refused.status_code, 400)
        self.assertIn('局域网', refused.json()['error'])
        moved = self.client.patch('/api/environments/' + made.json()['id'], headers=self.headers,
                                  json={'name': 'GPT', 'node_id': None, 'service': 'custom', 'start_url': 'chat.example.com'})
        self.assertEqual((moved.json()['service'], moved.json()['start_url']), ('custom', 'https://chat.example.com'))
        kept = self.client.patch('/api/environments/' + made.json()['id'], json={'name': 'GPT 2', 'node_id': None}, headers=self.headers)
        self.assertEqual(kept.json()['service'], 'custom')
        plan = self.client.patch(f'/api/environments/{made.json()["id"]}/account', headers=self.headers,
                                 json={'label': '', 'plan': 'paid', 'status': 'active'})
        self.assertEqual(plan.json()['plan'], 'paid')


if __name__ == '__main__':
    unittest.main()
