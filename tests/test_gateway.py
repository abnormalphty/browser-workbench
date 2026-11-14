import asyncio
import json
import os
from pathlib import Path
import re
import socket
import socketserver
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import httpx
from starlette.applications import Starlette
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route
import uvicorn

from workbench import gateway as gw
from workbench import openai_compat
from workbench.app import create_app
from workbench.store import Store

GOOD = 'sk-ant-api03-' + 'g' * 40
BAD = 'sk-ant-api03-' + 'b' * 40
MODELS = [{'id': 'claude-test-1', 'type': 'model', 'display_name': 'Claude Test 1', 'created_at': '2026-01-01T00:00:00Z',
           'max_tokens': 64000, 'max_input_tokens': 200000, 'lifecycle': 'active', 'line': 'opus'},
          {'id': 'claude-test-2', 'type': 'model', 'display_name': 'Claude Test 2', 'created_at': '2026-02-01T00:00:00Z',
           'max_tokens': 32000, 'max_input_tokens': 200000, 'lifecycle': 'active', 'line': 'haiku'}]
USER = [{'role': 'user', 'content': '你好'}]


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def event(kind, data):
    return f'event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n'.encode()


class Fake:
    """A stand-in for api.anthropic.com on this machine: it notes what reaches it."""

    def __init__(self):
        self.requests = []
        self.aborted = threading.Event()
        self.sent = 0
        app = Starlette(routes=[Route('/v1/models', self.models), Route('/v1/messages', self.messages, methods=['POST']),
                                Route('/v1/messages/count_tokens', self.count, methods=['POST'])])
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        self.url = f'http://127.0.0.1:{sock.getsockname()[1]}'
        self.server = uvicorn.Server(uvicorn.Config(app, lifespan='off', log_config=None, access_log=False))
        self.thread = threading.Thread(target=self.server.run, kwargs={'sockets': [sock]}, daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started and time.monotonic() < deadline:
            time.sleep(.01)

    def close(self):
        self.server.should_exit = True
        self.thread.join(10)

    async def models(self, request):
        if request.headers.get('authorization') != f'Bearer {GOOD}':
            return JSONResponse({'type': 'error', 'error': {'type': 'authentication_error', 'message': 'invalid x-api-key'}}, status_code=401)
        return JSONResponse({'data': MODELS, 'has_more': False, 'first_id': MODELS[0]['id'], 'last_id': MODELS[-1]['id']})

    async def note(self, request):
        body = await request.json()
        self.requests.append({'path': request.url.path, 'query': dict(request.query_params), 'headers': dict(request.headers), 'body': body})
        return body

    async def count(self, request):
        await self.note(request)
        return JSONResponse({'input_tokens': 42}, headers={'request-id': 'req_count'})

    async def messages(self, request):
        body = await self.note(request)
        model = body['model']
        if model == 'claude-missing':
            return JSONResponse({'type': 'error', 'error': {'type': 'not_found_error', 'message': 'model: claude-missing'}},
                                status_code=404, headers={'request-id': 'req_missing'})
        if not body.get('stream'):
            return JSONResponse({'id': 'msg_1', 'type': 'message', 'role': 'assistant', 'model': model,
                                 'content': [{'type': 'text', 'text': '你好！'}], 'stop_reason': 'end_turn', 'stop_sequence': None,
                                 'usage': {'input_tokens': 11, 'output_tokens': 7, 'cache_read_input_tokens': 3}},
                                headers={'request-id': 'req_1', 'anthropic-ratelimit-requests-remaining': '49'})
        return StreamingResponse(self.events(model), media_type='text/event-stream', headers={'request-id': 'req_2'})

    async def events(self, model):
        yield event('message_start', {'type': 'message_start', 'message': {
            'id': 'msg_2', 'type': 'message', 'role': 'assistant', 'model': model, 'content': [], 'stop_reason': None,
            'stop_sequence': None, 'usage': {'input_tokens': 11, 'output_tokens': 1}}})
        yield event('content_block_start', {'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}})
        if model == 'claude-slow':
            try:
                for _ in range(200):
                    self.sent += 1
                    yield event('content_block_delta', {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': '.'}})
                    await asyncio.sleep(.05)
            except BaseException:
                self.aborted.set()
                raise
            return
        yield event('ping', {'type': 'ping'})
        for text in ('你', '好！'):
            yield event('content_block_delta', {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': text}})
        yield event('content_block_stop', {'type': 'content_block_stop', 'index': 0})
        yield event('message_delta', {'type': 'message_delta', 'delta': {'stop_reason': 'end_turn', 'stop_sequence': None},
                                      'usage': {'output_tokens': 7}})
        yield event('message_stop', {'type': 'message_stop'})


class PretendProxy(socketserver.TCPServer):
    """A proxy on this machine that is not one: it notes the first line of each request, then hangs up."""

    def __init__(self):
        self.lines = []
        super().__init__(('127.0.0.1', 0), PretendProxy.Note)
        self.url = f'http://127.0.0.1:{self.server_address[1]}'
        threading.Thread(target=self.serve_forever, kwargs={'poll_interval': .05}, daemon=True).start()

    def close(self):
        self.shutdown()
        self.server_close()

    class Note(socketserver.StreamRequestHandler):
        timeout = 5

        def handle(self):
            self.server.lines.append(self.rfile.readline().decode('latin-1').strip())


class GatewayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The fake is on this machine: a system proxy (macOS / Windows settings) must not carry the calls.
        cls.environment = patch.dict(os.environ, {'NO_PROXY': '127.0.0.1,localhost', 'no_proxy': '127.0.0.1,localhost'})
        cls.environment.start()
        cls.fake = Fake()

    @classmethod
    def tearDownClass(cls):
        cls.fake.close()
        cls.environment.stop()

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.data = Path(temp.name)
        self.store = Store(self.data)
        self.gateway = gw.Gateway(self.store, base_url=self.fake.url)
        self.addCleanup(self.gateway.stop)
        self.fake.requests.clear()

    def add_key(self, name='主密钥', secret=GOOD):
        self.assertIsNone(self.gateway.add_key(name, secret))
        return self.gateway.config()['keys'][-1]['id']

    def program(self, **values):
        client_id = self.gateway.save_client(None, {'name': '测试程序', **values})
        return client_id, self.gateway.client_token(client_id)

    def serve(self):
        port = free_port()
        self.gateway.settings({'enabled': True, 'port': port})
        self.assertTrue(self.gateway.running())
        self.http = httpx.Client(base_url=f'http://127.0.0.1:{port}', trust_env=False, timeout=20)
        self.addCleanup(self.http.close)
        return port

    @staticmethod
    def headers(token, **extra):
        return {'x-api-key': token, 'anthropic-version': '2023-06-01', **extra}

    def usage(self, index=0):
        return (self.gateway.state()['clients'][index]['usage'] or {}).get('today')

    # ---------- settings ----------

    def test_only_api_keys_are_taken(self):
        for secret, words in (('sk-ant-oat01-' + 'x' * 40, '订阅'), ('sk-ant-admin01-' + 'x' * 40, '管理员'), ('hello', 'sk-ant-')):
            with self.assertRaisesRegex(ValueError, words):
                self.gateway.add_key('x', secret)
        with self.assertRaisesRegex(ValueError, '无效'):
            self.gateway.add_key('坏的', BAD)
        self.assertEqual(self.gateway.config()['keys'], [])

    def test_keys_are_checked_and_never_shown_again(self):
        self.add_key()
        state = self.gateway.state()
        self.assertEqual([m['id'] for m in state['models']], ['claude-test-1', 'claude-test-2'])
        self.assertEqual(state['models'][0]['line'], 'opus')
        self.assertEqual((state['keys'][0]['status'], state['keys'][0]['default']), ('ok', True))
        self.assertEqual(state['keys'][0]['hint'], 'sk-ant-…' + GOOD[-4:])
        self.assertNotIn(GOOD, json.dumps([state, self.gateway.history()]))
        with self.assertRaisesRegex(ValueError, '已经添加过'):
            self.gateway.add_key('又一次', GOOD)

    def test_a_key_is_kept_when_anthropic_cannot_be_reached(self):
        self.gateway.base_url = f'http://127.0.0.1:{free_port()}'
        self.assertIn('暂时没能验证', self.gateway.add_key('离线时添加', GOOD))
        self.assertEqual(self.gateway.state()['keys'][0]['status'], 'unreachable')
        self.gateway.base_url = self.fake.url
        self.gateway.check_key(self.gateway.config()['keys'][0]['id'])
        self.assertEqual(self.gateway.state()['keys'][0]['status'], 'ok')
        self.assertEqual(len(self.gateway.state()['models']), 2)

    def test_the_proxy_in_the_settings_wins_over_the_system_one(self):
        # The SDK follows the system's proxy (here from the environment, like a Mac with a proxy tool switched on);
        # the one in the gateway settings must carry both the key check and the programs' requests.
        system, chosen = PretendProxy(), PretendProxy()
        self.addCleanup(system.close)
        self.addCleanup(chosen.close)
        self.gateway.base_url = 'https://api.anthropic.invalid'  # and nothing could answer there directly
        with patch.dict(os.environ, dict.fromkeys(('HTTPS_PROXY', 'https_proxy', 'HTTP_PROXY', 'http_proxy'), system.url)):
            self.gateway.settings({'proxy': chosen.url})
            self.assertIn('暂时没能验证', self.gateway.add_key('主密钥', GOOD))
            checked = len(chosen.lines)
            _, token = self.program()
            self.serve()
            answer = self.http.post('/v1/messages', headers=self.headers(token),
                                    json={'model': 'claude-test-1', 'max_tokens': 10, 'messages': USER})
        self.assertEqual(answer.status_code, 502)
        self.assertEqual(system.lines, [])
        self.assertTrue(0 < checked < len(chosen.lines), chosen.lines)
        for line in chosen.lines:
            self.assertTrue(line.startswith('CONNECT api.anthropic.invalid:443 '), line)

    def test_program_settings_are_checked(self):
        with self.assertRaisesRegex(ValueError, '固定'):
            self.gateway.save_client(None, {'name': 'x', 'mode': 'fixed'})
        with self.assertRaisesRegex(ValueError, '默认模型'):
            self.gateway.save_client(None, {'name': 'x', 'models': ['claude-test-1'], 'default_model': 'claude-test-2'})
        with self.assertRaisesRegex(ValueError, '名称'):
            self.gateway.save_client(None, {'name': ' '})
        with self.assertRaisesRegex(ValueError, '找不到'):
            self.gateway.save_client(None, {'name': 'x', 'key_id': 'nope'})
        client_id = self.gateway.save_client(None, {'name': '甲', 'models': ['claude-test-1']})
        self.gateway.save_client(client_id, {'enabled': False})  # the rest stays as it was
        client = self.gateway.config()['clients'][0]
        self.assertEqual((client['models'], client['enabled']), (['claude-test-1'], False))
        self.assertEqual(self.gateway.history()[0]['summary'], '停用专属密钥“甲”')

    def test_history_brings_programs_back_but_not_replaced_keys(self):
        self.add_key()
        first, first_token = self.program(name='甲')
        second, second_token = self.program(name='乙')
        replaced = self.gateway.rotate_client(first)
        self.gateway.delete_client(second)
        summaries = [entry['summary'] for entry in self.gateway.history()]
        self.assertEqual(summaries, ['删除专属密钥“乙”', '更换专属密钥“甲”', '新建专属密钥“乙”', '新建专属密钥“甲”', '添加 API 密钥“主密钥”'])
        self.gateway.restore(2)
        tokens = {client['name']: client['token'] for client in self.gateway.config()['clients']}
        self.assertEqual(tokens, {'甲': replaced, '乙': second_token})
        self.assertNotEqual(replaced, first_token)
        self.assertTrue(self.gateway.history()[0]['summary'].startswith('回到这一步：新建专属密钥“乙”'))
        self.gateway.settings({'enabled': True, 'port': free_port()})
        self.gateway.settings({'proxy': '127.0.0.1:7890'})
        self.assertEqual((self.gateway.config()['proxy'], self.gateway.history()[0]['summary']), ('http://127.0.0.1:7890', '修改代理设置'))
        self.gateway.restore(1)  # back to before the proxy: the gateway stays on
        self.assertEqual((self.gateway.config()['proxy'], self.gateway.config()['enabled']), ('', True))
        self.assertTrue(self.gateway.running())
        self.assertNotIn(GOOD, json.dumps(self.gateway.history()))
        with self.assertRaises(ValueError):
            self.gateway.restore(0)

    def test_a_deleted_api_key_leaves_its_programs_on_the_default(self):
        main = self.add_key()
        self.gateway.config()
        client_id, _ = self.program(key_id=main)
        self.gateway.delete_key(main)
        self.assertIsNone(self.gateway.config()['clients'][0]['key_id'])
        self.assertIsNone(self.gateway.config()['default_key'])
        self.assertEqual(self.gateway.restore(1), ['测试程序'])  # back to before: that key is gone for good

    # ---------- the local server ----------

    def test_messages_pass_through_with_the_programs_own_headers(self):
        self.add_key()
        _, token = self.program(models=['claude-test-1'])
        self.serve()
        response = self.http.post('/v1/messages?beta=true', headers=self.headers(token, **{'anthropic-beta': 'context-1m-2025-08-07'}),
                                  json={'model': 'claude-test-1', 'max_tokens': 100, 'messages': USER, 'context_management': {'edits': []}})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['content'][0]['text'], '你好！')
        self.assertEqual(response.headers['request-id'], 'req_1')
        self.assertEqual(response.headers['anthropic-ratelimit-requests-remaining'], '49')
        self.assertEqual(response.headers['access-control-allow-origin'], '*')
        sent = self.fake.requests[-1]
        self.assertEqual(sent['headers']['authorization'], f'Bearer {GOOD}')
        self.assertNotIn(token, json.dumps(sent))
        self.assertEqual(sent['headers']['anthropic-version'], '2023-06-01')
        self.assertEqual(sent['headers']['anthropic-beta'], 'context-1m-2025-08-07')
        self.assertEqual(sent['query'], {'beta': 'true'})
        self.assertEqual(sent['body']['context_management'], {'edits': []})
        usage = self.usage()
        self.assertEqual((usage['requests'], usage['input'], usage['output'], usage['cache_read'], usage['errors']), (1, 11, 7, 3, 0))

    def test_each_program_gets_its_own_models(self):
        self.add_key()
        _, choice = self.program(name='可选', models=['claude-test-1'])
        _, fixed = self.program(name='固定', mode='fixed', default_model='claude-test-2')
        _, anything = self.program(name='全部')
        self.serve()

        def listed(token):
            return [m['id'] for m in self.http.get('/v1/models', headers={'authorization': f'Bearer {token}'}).json()['data']]
        self.assertEqual(listed(choice), ['claude-test-1'])
        self.assertEqual(listed(fixed), ['claude-test-2'])
        self.assertEqual(listed(anything), ['claude-test-1', 'claude-test-2'])
        self.assertEqual(self.http.get('/v1/models/claude-test-2', headers={'x-api-key': fixed}).json()['display_name'], 'Claude Test 2')
        refused = self.http.post('/v1/messages', headers=self.headers(choice), json={'model': 'claude-test-2', 'max_tokens': 5, 'messages': USER})
        self.assertEqual(refused.status_code, 400)
        self.assertIn('不能使用模型 claude-test-2', refused.json()['error']['message'])
        self.assertEqual(self.fake.requests, [])
        self.http.post('/v1/messages', headers=self.headers(fixed), json={'model': 'claude-test-1', 'max_tokens': 5, 'messages': USER})
        self.assertEqual(self.fake.requests[-1]['body']['model'], 'claude-test-2')

    def test_streams_pass_through_and_are_counted(self):
        self.add_key()
        _, token = self.program()
        self.serve()
        with self.http.stream('POST', '/v1/messages', headers=self.headers(token),
                              json={'model': 'claude-test-1', 'max_tokens': 100, 'stream': True, 'messages': USER}) as response:
            self.assertEqual(response.headers['content-type'].split(';')[0], 'text/event-stream')
            self.assertEqual(response.headers['request-id'], 'req_2')
            streamed = b''.join(response.iter_bytes()).decode()
        self.assertIn('好！', streamed)
        self.assertTrue(streamed.rstrip().endswith('{"type": "message_stop"}'))
        usage = self.usage()
        self.assertEqual((usage['requests'], usage['input'], usage['output'], usage['errors']), (1, 11, 7, 0))

    def test_a_program_going_away_stops_the_answer(self):
        self.add_key()
        _, token = self.program(models=['claude-slow'])
        self.serve()
        with self.http.stream('POST', '/v1/messages', headers=self.headers(token),
                              json={'model': 'claude-slow', 'max_tokens': 5, 'stream': True, 'messages': USER}) as response:
            for chunk in response.iter_bytes():
                if b'content_block_delta' in chunk:
                    break
        self.assertTrue(self.fake.aborted.wait(10), 'the call to Anthropic should end with the program')
        self.assertLess(self.fake.sent, 150)
        deadline = time.monotonic() + 5
        while not self.usage() and time.monotonic() < deadline:
            time.sleep(.05)
        self.assertEqual(self.usage()['requests'], 1)

    def test_errors_from_anthropic_come_back_as_they_are(self):
        self.add_key()
        _, token = self.program(models=['claude-missing'])
        self.serve()
        response = self.http.post('/v1/messages', headers=self.headers(token), json={'model': 'claude-missing', 'max_tokens': 5, 'messages': USER})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['error']['type'], 'not_found_error')
        self.assertEqual(response.headers['request-id'], 'req_missing')
        self.assertEqual(self.usage()['errors'], 1)

    def test_token_counting(self):
        self.add_key()
        _, token = self.program()
        self.serve()
        response = self.http.post('/v1/messages/count_tokens?beta=true', headers=self.headers(token), json={'model': 'claude-test-1', 'messages': USER})
        self.assertEqual(response.json(), {'input_tokens': 42})
        self.assertEqual(self.fake.requests[-1]['path'], '/v1/messages/count_tokens')
        self.assertIsNone(self.usage())  # counting is free: not a request to show

    def test_openai_format(self):
        self.add_key()
        _, token = self.program()
        self.serve()
        bearer = {'authorization': f'Bearer {token}'}
        asked = {'model': 'claude-test-1', 'temperature': .3, 'messages': [{'role': 'system', 'content': '简短回答'}, *USER]}
        answer = self.http.post('/v1/chat/completions', headers=bearer, json=asked).json()
        self.assertEqual(answer['choices'][0]['message']['content'], '你好！')
        self.assertEqual(answer['choices'][0]['finish_reason'], 'stop')
        self.assertEqual((answer['usage']['prompt_tokens'], answer['usage']['completion_tokens']), (11, 7))
        sent = self.fake.requests[-1]['body']
        self.assertEqual((sent['system'], sent['max_tokens']), ('简短回答', openai_compat.DEFAULT_MAX_TOKENS))
        self.assertNotIn('temperature', sent)
        with self.http.stream('POST', '/chat/completions', headers=bearer,
                              json={**asked, 'stream': True, 'stream_options': {'include_usage': True}}) as response:
            lines = [line for line in response.iter_lines() if line.startswith('data: ')]
        self.assertEqual(lines[-1], 'data: [DONE]')
        chunks = [json.loads(line[6:]) for line in lines[:-1]]
        self.assertEqual(''.join(c['choices'][0]['delta'].get('content') or '' for c in chunks if c['choices']), '你好！')
        self.assertEqual(chunks[-1]['usage']['completion_tokens'], 7)
        self.assertEqual(self.usage()['requests'], 2)
        refused = self.http.post('/v1/chat/completions', headers=bearer, json={'model': 'claude-test-1', 'messages': []})
        self.assertEqual(refused.status_code, 400)
        self.assertIn('messages', refused.json()['error']['message'])

    def test_wrong_or_stopped_keys_and_other_names(self):
        self.add_key()
        client_id, token = self.program()
        port = self.serve()
        self.assertEqual(self.http.get('/v1/models', headers={'x-api-key': 'bwk-nope'}).status_code, 401)
        self.gateway.save_client(client_id, {'enabled': False})
        stopped = self.http.post('/v1/messages', headers=self.headers(token), json={'model': 'claude-test-1', 'max_tokens': 5, 'messages': USER})
        self.assertEqual(stopped.status_code, 403)
        self.assertIn('停用', stopped.json()['error']['message'])
        # A web page that names itself after this computer (DNS rebinding) gets nothing.
        self.assertEqual(self.http.get('/', headers={'host': f'attacker.example:{port}'}).status_code, 400)
        self.assertEqual(self.http.get('/', headers={'host': f'localhost:{port}'}).status_code, 200)
        preflight = self.http.options('/v1/messages', headers={'origin': 'http://localhost:5173', 'access-control-request-method': 'POST',
                                                               'access-control-request-headers': 'x-api-key, content-type'})
        self.assertEqual(preflight.status_code, 204)
        self.assertEqual(preflight.headers['access-control-allow-headers'], 'x-api-key, content-type')
        self.assertEqual(self.fake.requests, [])

    def test_switching_off_and_ports_in_use(self):
        port = self.serve()
        holder = socket.socket()
        holder.bind(('127.0.0.1', 0))
        holder.listen()
        self.addCleanup(holder.close)
        busy = holder.getsockname()[1]
        with self.assertRaisesRegex(ValueError, '占用'):
            self.gateway.settings({'port': busy})
        self.assertEqual(self.gateway.config()['port'], port)  # nothing changed
        self.http.close()
        history = len(self.gateway.history())
        self.gateway.settings({'enabled': False})
        self.assertFalse(self.gateway.running())
        self.assertEqual(len(self.gateway.history()), history)  # on and off are not settings to go back to
        free = gw.bind(port)
        self.assertIsNotNone(free)
        free.close()
        # Taken while the gateway was off: said on the page, not raised.
        self.store.set_setting('gateway', {**self.gateway.config(), 'enabled': True, 'port': busy})
        self.gateway.apply()
        self.assertFalse(self.gateway.running())
        self.assertIn(str(busy), self.gateway.state()['error'])


class PageTests(unittest.TestCase):
    """The workbench page's side: /api/gateway behind the page's own token, and the server with the app."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.data = Path(temp.name)

    def test_secrets_stay_out_of_the_page(self):
        app = create_app(self.data)
        with TestClient(app, base_url='http://127.0.0.1:8766') as client:
            token = re.search(r'name="workbench-token" content="([^"]+)"', client.get('/').text).group(1)
            headers = {'X-Workbench-Token': token}
            self.assertEqual(client.get('/api/gateway').status_code, 403)
            refused = client.post('/api/gateway/keys', headers=headers, json={'name': '订阅', 'secret': 'sk-ant-oat01-' + 'x' * 40})
            self.assertEqual(refused.status_code, 400)
            self.assertIn('订阅', refused.json()['error'])
            app.state.gateway.base_url = f'http://127.0.0.1:{free_port()}'  # nothing answers: kept unchecked
            with patch.dict(os.environ, {'NO_PROXY': '127.0.0.1', 'no_proxy': '127.0.0.1'}):
                added = client.post('/api/gateway/keys', headers=headers, json={'name': '主密钥', 'secret': GOOD}).json()
            self.assertIn('暂时没能验证', added['notice'])
            created = client.post('/api/gateway/clients', headers=headers, json={'name': 'Cherry Studio'}).json()
            full = client.post(f'/api/gateway/clients/{created["client_id"]}/token', headers=headers).json()['token']
            self.assertTrue(full.startswith('bwk-'))
            shown = client.get('/api/gateway', headers=headers).text
            self.assertNotIn(GOOD, shown)
            self.assertNotIn(full, shown)
            restored = client.post('/api/gateway/history/1/restore', headers=headers).json()
            self.assertEqual(restored['clients'], [])

    def test_the_server_runs_while_the_workbench_does(self):
        Store(self.data).set_setting('gateway', {'enabled': True, 'port': free_port()})
        app = create_app(self.data)
        with TestClient(app, base_url='http://127.0.0.1:8766'):
            self.assertTrue(app.state.gateway.running())
        self.assertFalse(app.state.gateway.running())


if __name__ == '__main__':
    unittest.main()
