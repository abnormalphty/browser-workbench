import re
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from workbench.app import create_app


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.temp.name))
        self.client = TestClient(self.app, base_url='http://127.0.0.1:8766')
        html = self.client.get('/').text
        self.token = re.search(r'name="workbench-token" content="([^"]+)"', html).group(1)
        self.headers = {'X-Workbench-Token': self.token}

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def test_environment_lifecycle(self):
        response = self.client.post('/api/environments', json={'name': '测试环境', 'node_id': None}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['engine'],'firefox')
        env_id = response.json()['id']
        state = self.client.get('/api/state', headers=self.headers).json()
        self.assertEqual(state['environments'][0]['name'], '测试环境')
        self.assertNotIn('fingerprint_seed', response.text)
        updated = self.client.patch('/api/environments/'+env_id, json={'name':'新的名称','node_id':None}, headers=self.headers)
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()['name'], '新的名称')

    def test_standard_firefox_choice_is_saved_and_cannot_replace_existing_engine(self):
        created = self.client.post('/api/environments', json={'name':'兼容环境','engine':'firefox'}, headers=self.headers)
        self.assertEqual(created.status_code, 200)
        env = created.json()
        self.assertEqual(env['engine'], 'firefox')
        changed = self.client.patch('/api/environments/'+env['id'], json={'name':'兼容环境','node_id':None,'engine':'camoufox'}, headers=self.headers)
        self.assertEqual(changed.status_code, 400)
        self.assertEqual(self.app.state.store.get_environment(env['id'])['engine'], 'firefox')

    def test_unknown_engine_is_rejected_by_api(self):
        response = self.client.post('/api/environments', json={'name':'x','engine':'not-an-engine'}, headers=self.headers)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.app.state.store.list_environments(), [])

    def test_cross_origin_mutation_is_rejected(self):
        r = self.client.post('/api/environments', json={'name':'x'}, headers={**self.headers, 'Origin':'https://untrusted.example'})
        self.assertEqual(r.status_code, 403)

    def test_missing_token_is_rejected(self):
        r = self.client.post('/api/environments', json={'name':'x'})
        self.assertEqual(r.status_code, 403)

    def test_invalid_environment_id_does_not_reach_docker(self):
        r = self.client.post('/api/environments/not-an-id/start', json={}, headers=self.headers)
        self.assertEqual(r.status_code, 400)

    def test_bad_subscription_does_not_replace_existing_data(self):
        r = self.client.post('/api/subscription', json={'url':'file:///etc/passwd'}, headers=self.headers)
        self.assertEqual(r.status_code, 400)
        self.assertFalse(self.app.state.store.public_state()['subscription']['configured'])

    def test_health_page_has_no_demo_nodes(self):
        state = self.client.get('/api/state', headers=self.headers).json()
        self.assertEqual(state['nodes'], [])
        self.assertEqual(state['environments'], [])
        self.assertEqual(state['runtime']['max_running'], 2)

    def test_request_body_size_is_bounded(self):
        r = self.client.post('/api/environments', content='x'*70000, headers={**self.headers, 'Content-Type':'application/json'})
        self.assertEqual(r.status_code, 413)


if __name__ == '__main__':
    unittest.main()
