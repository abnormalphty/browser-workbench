import base64
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from workbench.store import Store
from workbench.subscriptions import SubscriptionError, parse_subscription, validate_node, _public_url


class SubscriptionTests(unittest.TestCase):
    def test_yaml_imports_nodes_without_importing_core_settings(self):
        nodes = parse_subscription('external-controller: 0.0.0.0:9999\nproxies:\n  - {name: 测试香港, type: trojan, server: proxy.example, port: 443, password: secret}\n')
        self.assertEqual(nodes[0]['name'], '测试香港')
        self.assertNotIn('external-controller', nodes[0])

    def test_base64_vless_subscription(self):
        text = 'vless://12345678-1234-1234-1234-123456789012@proxy.example:443?security=tls&type=ws&path=%2Fws&host=example.org#Tokyo'
        nodes = parse_subscription(base64.b64encode(text.encode()).decode())
        self.assertEqual(nodes[0]['type'], 'vless')
        self.assertEqual(nodes[0]['ws-opts']['path'], '/ws')
        self.assertTrue(nodes[0]['tls'])

    def test_shadowsocks_encoded_userinfo(self):
        auth = base64.urlsafe_b64encode(b'aes-256-gcm:private:password').decode().rstrip('=')
        n = parse_subscription(f'ss://{auth}@proxy.example:8388#SS')[0]
        self.assertEqual(n['password'], 'private:password')
        self.assertEqual(n['cipher'], 'aes-256-gcm')

    def test_vmess_json(self):
        info = dict(v='2', ps='vmess', add='proxy.example', port='443', id='a-b-c', aid='0', net='ws', path='/ws', host='cdn.example', tls='tls')
        n = parse_subscription('vmess://' + base64.b64encode(json.dumps(info).encode()).decode())[0]
        self.assertEqual(n['server'], 'proxy.example')
        self.assertEqual(n['network'], 'ws')

    def test_html_is_not_a_subscription(self):
        with self.assertRaises(SubscriptionError):
            parse_subscription('<html><body>请登录</body></html>')

    def test_node_cannot_add_file_or_dialer_configuration(self):
        for field in ['dialer-proxy', 'certificate-path', 'private-key', 'interface-name']:
            with self.subTest(field=field), self.assertRaises(SubscriptionError):
                validate_node({'name': 'bad', 'type': 'trojan', 'server': 'proxy.example', 'port': 443, 'password': 'x', field: '/etc/private'})

    def test_rejects_invalid_ports_and_large_payload(self):
        with self.assertRaises(SubscriptionError):
            validate_node({'name': 'x', 'type': 'ss', 'server': 'host', 'port': 70000, 'cipher': 'none', 'password': 'x'})
        with self.assertRaises(SubscriptionError):
            parse_subscription('x' * 2_100_000)

    def test_rejects_unsafe_nested_transport_settings(self):
        with self.assertRaises(SubscriptionError):
            validate_node({'name': 'x', 'type': 'vless', 'server': 'host', 'port': 443, 'uuid': 'a', 'ws-opts': {'path': '/', 'arbitrary-file': '/etc/passwd'}})

    def test_proxy_fake_ip_dns_does_not_block_public_subscription_hostname(self):
        result = [(2, 1, 6, '', ('198.18.0.230', 443))]
        with patch('socket.getaddrinfo', return_value=result):
            self.assertIsNone(_public_url('https://subscription.example/sub'))

    def test_private_addresses_and_literal_fake_ip_remain_blocked(self):
        result = [(2, 1, 6, '', ('127.0.0.1', 443))]
        with patch('socket.getaddrinfo', return_value=result):
            with self.assertRaises(SubscriptionError):
                _public_url('https://subscription.example/sub')
        with self.assertRaises(SubscriptionError):
            _public_url('https://198.18.0.230/sub')


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def test_public_metadata_hides_credentials(self):
        self.store.save_subscription('https://subscription.example/secret-token', [{'name': 'HK', 'type': 'trojan', 'server': 'host', 'port': 443, 'password': 'very-secret'}])
        public = json.dumps(self.store.public_state())
        self.assertNotIn('secret-token', public)
        self.assertNotIn('very-secret', public)
        self.assertNotIn('password', public)
        self.assertEqual(len(self.store.public_state()['nodes']), 1)

    def test_environment_fingerprint_and_data_path_are_stable(self):
        env = self.store.create_environment('工作', None)
        loaded = self.store.get_environment(env['id'])
        self.assertEqual(env['fingerprint_seed'], loaded['fingerprint_seed'])
        self.assertEqual(env['id'], loaded['id'])
        with self.assertRaises(ValueError):
            self.store.get_environment('../other')

    def test_empty_names_get_a_default_and_names_are_bounded(self):
        self.assertTrue(self.store.create_environment('', None)['name'])
        with self.assertRaises(ValueError):
            self.store.create_environment('x'*81, None)

    def test_subscription_refresh_keeps_bound_node_identity(self):
        nodes = [{'name': 'HK', 'type': 'trojan', 'server': 'host', 'port': 443, 'password': 'one'}]
        self.store.save_subscription('https://example.org/sub', nodes)
        first = self.store.public_state()['nodes'][0]['id']
        env = self.store.create_environment('HK', first)
        nodes[0]['password'] = 'two'
        self.store.save_subscription('https://example.org/sub', nodes)
        self.assertEqual(self.store.get_environment(env['id'])['node_id'], first)
        self.assertEqual(self.store.get_node(first)['password'], 'two')

    def test_failed_write_keeps_old_subscription(self):
        self.store.save_subscription('https://example.org/one', [{'name':'n','type':'trojan','server':'host','port':443,'password':'x'}])
        with self.assertRaises(ValueError):
            self.store.save_subscription('https://example.org/two', [])
        self.assertEqual(self.store.get_subscription_url(), 'https://example.org/one')


if __name__ == '__main__':
    unittest.main()
