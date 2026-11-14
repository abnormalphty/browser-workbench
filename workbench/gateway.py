"""模型网关: one local address through which other programs on this computer (Cherry Studio, Claude Code and the
like) use Claude, GPT, Gemini, DeepSeek and other models with the user's own API keys, each program with a key
of its own from here.

The page (app.py, /api/gateway/...) keeps the settings: the API keys of the services (providers.py; they stay in
this computer's data folder and are never shown again in full), a key for each program with the models it may
use, and a history of earlier settings to go back to. A small server of its own listens on 127.0.0.1 only and
answers:

  /v1/messages, /v1/messages/count_tokens   the Messages API, passed on as it is (streaming too); Anthropic-format
                                            keys only
  /v1/chat/completions                      the OpenAI format: passed on as it is to an OpenAI-format service,
                                            carried out as Messages for Claude (openai_compat.py)
  /v1/models                                the models this program may use

A request goes to the API key that offers the model asked for (a program's own key, or every key with the
default one first). Anthropic is called with its official SDK, the other services with plain HTTP. Sign-ins
to the websites (claude.ai, ChatGPT …) are not API keys and are refused: their terms allow no such use.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
import functools
import inspect
import json
import re
import secrets
import socket
import threading
import time
from urllib.parse import urlsplit

import anyio
import httpx
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route
import uvicorn

from . import openai_compat
from .providers import (ANTHROPIC, MAX_LISTED, MODEL_ID, OPENAI, PROVIDERS, api_of, catalog, check_base, check_models, check_secret,
                        hinted, listed_model, local, mask as key_mask, openai_tokens, provider_id, provider_name)
from .system import windows

# Always named: the SDK would otherwise follow ANTHROPIC_BASE_URL, which a user may have pointed at this
# gateway for Claude Code (Windows hands user variables to every program), and the gateway would call itself.
ANTHROPIC_URL = 'https://api.anthropic.com'
DEFAULT_PORT = 18766
MAX_KEYS, MAX_CLIENTS, MAX_MODELS, HISTORY = 20, 30, 200, 40
USAGE_DAYS = 31
MAX_BODY = 32 * 1024 * 1024  # what the Messages API itself accepts
NAME = re.compile(r'[^\x00-\x1f\x7f]{1,40}')
TOKEN_PREFIX = 'bwk-'
FORWARDED = ('anthropic-version', 'anthropic-beta')
RETURNED = ('request-id', 'retry-after')
RETURNED_OPENAI = ('x-request-id', 'request-id', 'retry-after', 'openai-processing-ms')
SDK_OPTIONS = {'self', 'extra_headers', 'extra_query', 'extra_body', 'timeout'}
USAGE_FIELDS = ('requests', 'input', 'output', 'cache_read', 'cache_write', 'errors')
# An answer may take long to start (models that think first), so only connecting has a short limit.
RELAY_TIMEOUT = httpx.Timeout(connect=20, read=1800, write=120, pool=30)


class Refused(Exception):
    """A request the gateway answers itself: this status, error type and message."""

    def __init__(self, status, kind, message):
        super().__init__(message)
        self.status, self.kind, self.message = status, kind, message


class KeyProblem(ValueError):
    """Checking an API key did not succeed. status 'invalid': the service refused the key; 'unreachable': no
    proper answer came, which says nothing about the key; 'unlisted': the service has no model list to check
    the key with."""

    def __init__(self, message, status):
        super().__init__(message)
        self.status = status


def sdk():
    """Anthropic's official SDK, loaded when the gateway is first used: most people never switch it on, and
    loading it would add up to a second to every start of the workbench."""
    import anthropic
    return anthropic


@functools.cache
def parameters():
    """The Messages and token-counting parameters this SDK knows; anything else goes along as extra body."""
    from anthropic.resources.messages.messages import AsyncMessages
    names = lambda method: set(inspect.signature(method).parameters) - SDK_OPTIONS  # noqa: E731
    return names(AsyncMessages.create), names(AsyncMessages.count_tokens)


def sdk_http(base, proxy, asynchronous=False):
    """The SDK's own HTTP client for calls to base: through the proxy from the gateway settings, never through any
    proxy for this computer or the local network; None (the SDK's default, which follows the system's proxy
    settings) otherwise.

    The SDK mounts the system's proxies on http:// and https://, and those win over a proxy= argument (which only
    covers all://): a Mac with a proxy tool switched on would quietly use that one. So the proxy (or a direct
    connection) goes on the same mounts. Addresses the system leaves out of proxying (this computer's own names,
    NO_PROXY) stay direct."""
    nearby = local(urlsplit(base).hostname)
    if not proxy and not nearby:
        return None
    anthropic = sdk()
    import httpx2  # the SDK's HTTP library
    transport = (httpx2.AsyncHTTPTransport if asynchronous else httpx2.HTTPTransport)(proxy=None if nearby else proxy)
    client = anthropic.DefaultAsyncHttpxClient if asynchronous else anthropic.DefaultHttpxClient
    return client(mounts=dict.fromkeys(('all://', 'http://', 'https://'), transport))


def http_options(base, proxy, asynchronous=False):
    """The same for the plain HTTP calls to the other services."""
    if local(urlsplit(base).hostname):
        return {'trust_env': False}
    if not proxy:
        return {}
    transport = (httpx.AsyncHTTPTransport if asynchronous else httpx.HTTPTransport)(proxy=proxy)
    return {'mounts': dict.fromkeys(('all://', 'http://', 'https://'), transport)}


def now():
    return time.time()


def mask(secret):
    return TOKEN_PREFIX + '…' + secret[-4:] if secret.startswith(TOKEN_PREFIX) else key_mask(secret)


def name_of(value, what):
    if not isinstance(value, str) or not NAME.fullmatch(value.strip()):
        raise ValueError(f'{what}需要 1–40 个字。')
    return value.strip()


def empty():
    # models, models_checked_at: the one model list of the time when every key was an Anthropic one; each key
    # keeps its own now (Gateway.config).
    return {'enabled': False, 'port': DEFAULT_PORT, 'proxy': '', 'keys': [], 'default_key': None, 'clients': [],
            'models': [], 'models_checked_at': None}


def bearer(key):
    return {'authorization': f'Bearer {key["secret"]}'} if key['secret'] else {}


def key_models(key):
    """The models a key offers: those its service listed, and those typed in for it."""
    return [model['id'] for model in key.get('models') or []] + list(key.get('manual_models') or [])


def offered(keys):
    return list(dict.fromkeys(model for key in keys for model in key_models(key)))


def check_proxy(value):
    value = value.strip() if isinstance(value, str) else None
    if value and '://' not in value:
        value = 'http://' + value  # proxy tools show their address as 127.0.0.1:7890
    if value is None or (value and not re.fullmatch(r'https?://[^\s/@]+(:\d{1,5})?/?', value)):
        raise ValueError('代理地址应像 http://127.0.0.1:7890 这样；留空表示使用系统设置。')
    return value.rstrip('/')


def verdict(response, host):
    """What a service's answer to a key check says about the key."""
    status = response.status_code
    if status < 300:
        return
    text = response.text[:4000].lower()
    if status in (400, 403) and any(word in text for word in ('location', 'region', 'country')):
        raise KeyProblem(f'{host} 不对这台电脑所在的地区提供服务。需要代理时，先在网关设置里填写代理地址。', 'unreachable')
    if status in (401, 403) or (status == 400 and ('key' in text or 'auth' in text)):
        raise KeyProblem(f'{host} 不接受这个 API 密钥：它无效、已删除，或没有使用权限。', 'invalid')
    if status in (404, 405):
        raise KeyProblem('这个服务没有提供模型列表，没法用它验证密钥。请在这个密钥的“手动添加的模型”里填写要用的模型。', 'unlisted')
    raise KeyProblem(f'{host} 暂时没有正常回应（{status}），请稍后再试。', 'unreachable')


def model_info(model):
    created = model.created_at
    created = created.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ') if isinstance(created, datetime) else str(created or '')
    return {'id': model.id, 'display_name': model.display_name or model.id, 'created_at': created,
            'line': getattr(model, 'line', None), 'max_tokens': getattr(model, 'max_tokens', None),
            'max_input_tokens': getattr(model, 'max_input_tokens', None), 'lifecycle': getattr(model, 'lifecycle', None)}


def bind(port):
    """A socket on this computer's own address only, or None when the port is taken."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if not windows():
        # Elsewhere this only lets a restart reuse the port; on Windows it would let another program share it.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(('127.0.0.1', port))
    except OSError:
        sock.close()
        return None
    return sock


def named(counts):
    return dict(zip(USAGE_FIELDS, counts))


class Gateway:
    def __init__(self, store, base_url=None):
        self.store = store
        self.base_url = base_url or ANTHROPIC_URL  # tests point it at a local fake
        self.bases = {}                      # and the other services' addresses, by service
        self.lock = threading.RLock()        # settings and the server
        self.usage_lock = threading.Lock()   # the request counts, written as requests finish
        self.server = self.thread = None
        self.port = None
        self.error = None
        self.upstreams = {}
        self.asgi = self.build_app()

    # ---------- settings ----------

    def config(self):
        value = self.store.get_setting('gateway')
        config = empty()
        if isinstance(value, dict):
            config.update({k: v for k, v in value.items() if k in config})
        for key in config['keys']:
            # Keys from before other services could be added: Anthropic ones, sharing one model list.
            key.setdefault('provider', ANTHROPIC)
            if 'models' not in key:
                key['models'], key['models_checked_at'] = list(config['models'] or []), config['models_checked_at']
            key.setdefault('manual_models', [])
        config['models'], config['models_checked_at'] = [], None
        return config

    def endpoint(self, key):
        """Where a key's requests go."""
        provider = key.get('provider') or ANTHROPIC
        if provider == 'custom':
            return key.get('base_url')
        if provider == ANTHROPIC:
            return self.base_url
        return self.bases.get(provider) or PROVIDERS.get(provider, {}).get('base')

    def history(self):
        value = self.store.get_setting('gateway_history', [])
        return value if isinstance(value, list) else []

    def save(self, config, summary):
        """Settings and, beside them, what they were: the history keeps everything but the API keys themselves."""
        snapshot = {k: v for k, v in config.items() if k not in ('models', 'models_checked_at')}
        snapshot['keys'] = [{'id': key['id'], 'name': key['name'], 'manual_models': key.get('manual_models', [])}
                            for key in config['keys']]
        history = ([{'at': now(), 'summary': summary, 'config': snapshot}] + self.history())[:HISTORY]
        self.store.set_setting('gateway', config)
        self.store.set_setting('gateway_history', history)

    def change(self, summary, edit):
        """summary None: not a change worth going back to (switching the gateway on or off)."""
        with self.lock:
            config = self.config()
            result = edit(config)
            if summary:
                self.save(config, summary)
            else:
                self.store.set_setting('gateway', config)
        self.apply()
        return result

    @staticmethod
    def key(config, key_id):
        for key in config['keys']:
            if key['id'] == key_id:
                return key
        raise ValueError('找不到这个 API 密钥。')

    @staticmethod
    def client(config, client_id):
        for client in config['clients']:
            if client['id'] == client_id:
                return client
        raise ValueError('找不到这个专属密钥。')

    def fetch_models(self, key, proxy):
        """The models this API key may use; also how a key is checked."""
        return self.fetch_anthropic(key, proxy) if api_of(key) == ANTHROPIC else self.fetch_openai(key, proxy)

    def fetch_anthropic(self, key, proxy):
        anthropic = sdk()
        base = self.endpoint(key)
        host, ours = urlsplit(base).hostname, key.get('provider', ANTHROPIC) == ANTHROPIC
        try:
            with anthropic.Anthropic(api_key=key['secret'] or 'none', base_url=base, http_client=sdk_http(base, proxy), max_retries=1,
                                     timeout=20) as client:
                return [model_info(model) for model in client.models.list(limit=100)][:MAX_LISTED]
        except anthropic.AuthenticationError as exc:
            raise KeyProblem('这个 API 密钥无效，或已在 Claude Console 里删除。' if ours else f'{host} 不接受这个 API 密钥。', 'invalid') from exc
        except anthropic.PermissionDeniedError as exc:
            raise KeyProblem('这个 API 密钥没有使用权限（可能所在组织或工作区已停用）。', 'invalid') from exc
        except anthropic.NotFoundError as exc:
            raise KeyProblem('这个服务没有提供模型列表，没法用它验证密钥。请在这个密钥的“手动添加的模型”里填写要用的模型。', 'unlisted') from exc
        except anthropic.APIConnectionError as exc:
            raise KeyProblem(f'连不上 {host}。请检查网络；需要代理时，先在网关设置里填写代理地址。', 'unreachable') from exc
        except anthropic.APIStatusError as exc:
            raise KeyProblem(f'{"Anthropic" if ours else host} 暂时没有正常回应（{exc.status_code}），请稍后再试。', 'unreachable') from exc

    def fetch_openai(self, key, proxy):
        """GET /models of an OpenAI-format service. OpenRouter lists its models to anyone: its key is checked first."""
        base = self.endpoint(key)
        host = urlsplit(base).hostname
        headers = {'accept': 'application/json', **bearer(key)}
        check = PROVIDERS.get(key.get('provider'), {}).get('check')
        try:
            with httpx.Client(**http_options(base, proxy), timeout=20) as http:
                if check:
                    verdict(http.get(base + check, headers=headers), host)
                response = http.get(base + '/models', headers=headers)
        except httpx.HTTPError as exc:
            raise KeyProblem(f'连不上 {host}。请检查网络；需要代理时，先在网关设置里填写代理地址。', 'unreachable') from exc
        verdict(response, host)
        try:
            listed = response.json().get('data')
        except (ValueError, AttributeError):
            listed = None
        if not isinstance(listed, list):
            raise KeyProblem(f'{host} 返回的模型列表无法识别。请在这个密钥的“手动添加的模型”里填写要用的模型。', 'unlisted')
        models = list({model['id']: model for model in map(listed_model, listed) if model}.values())
        return models[:MAX_LISTED]

    def settings(self, data):
        current = self.config()
        port = data.get('port', current['port'])
        if 'port' in data and (isinstance(port, bool) or not isinstance(port, int) or not 1024 <= port <= 65535):
            raise ValueError('端口应是 1024–65535 之间的数字。')
        if port != current['port'] and data.get('enabled', current['enabled']):
            sock = bind(port)  # say so here, before anything changes
            if not sock:
                raise ValueError(f'端口 {port} 已被其他程序占用，请换一个。')
            sock.close()
        if 'enabled' in data and not isinstance(data['enabled'], bool):
            raise ValueError('开关的值不正确。')
        proxy = check_proxy(data['proxy']) if 'proxy' in data else current['proxy']

        def edit(config):
            config['enabled'] = data.get('enabled', config['enabled'])
            config['port'], config['proxy'] = port, proxy
        parts = [f'端口改为 {port}' if port != current['port'] else None, '修改代理设置' if proxy != current['proxy'] else None]
        self.change('、'.join(p for p in parts if p) or None, edit)

    def add_key(self, name, secret, provider=None, base_url=None, api=None, models=None):
        """Saved after the service accepted it; saved unchecked when the service could not be reached or has no
        model list. Returns a note for the page then."""
        name, provider = name_of(name, 'API 密钥的名称'), provider_id(provider)
        secret = check_secret(provider, secret)
        config = self.config()
        entry = {'provider': provider, 'secret': secret, 'manual_models': check_models(models)}
        if provider == 'custom':
            if api not in (ANTHROPIC, OPENAI):
                raise ValueError('请选择这个服务的接口格式（OpenAI 兼容或 Anthropic 兼容）。')
            entry.update(api=api, base_url=check_base(base_url, api, config['port']))
        if secret and any(secrets.compare_digest(key['secret'], secret) for key in config['keys']):
            raise ValueError('这个 API 密钥已经添加过了。')
        if len(config['keys']) >= MAX_KEYS:
            raise ValueError(f'最多保存 {MAX_KEYS} 个 API 密钥。')
        try:
            listed, status, note = self.fetch_models(entry, config['proxy'] or None), 'ok', None
        except KeyProblem as problem:
            if problem.status == 'invalid':
                raise
            listed, status = None, problem.status
            note = f'已保存，但暂时没能验证：{problem}' if status == 'unreachable' else f'已保存。{problem}'

        def edit(config):
            if secret and any(secrets.compare_digest(key['secret'], secret) for key in config['keys']):
                raise ValueError('这个 API 密钥已经添加过了。')
            key = {'id': secrets.token_hex(8), 'name': name, **entry, 'added_at': now(), 'checked_at': now(), 'status': status,
                   'models': listed or [], 'models_checked_at': now() if listed is not None else None}
            config['keys'].append(key)
            config['default_key'] = config['default_key'] or key['id']
        self.change(f'添加 API 密钥“{name}”', edit)
        return note

    def update_key(self, key_id, data):
        """A new name, models typed in by hand, or being the default key."""
        key = self.key(self.config(), key_id)
        label = key['name']
        name = name_of(data['name'], 'API 密钥的名称') if 'name' in data else label
        manual = check_models(data['models']) if 'models' in data else key['manual_models']

        def edit(config):
            key = self.key(config, key_id)
            key['name'], key['manual_models'] = name, manual
            if data.get('default') is True:
                config['default_key'] = key_id
        parts = [f'把“{label}”设为默认 API 密钥' if data.get('default') is True else None,
                 f'API 密钥“{label}”改名为“{name}”' if name != label else None,
                 f'修改“{name}”手动添加的模型' if manual != key['manual_models'] else None]
        self.change('、'.join(p for p in parts if p) or None, edit)

    def delete_key(self, key_id):
        label = self.key(self.config(), key_id)['name']

        def edit(config):
            config['keys'].remove(self.key(config, key_id))
            if config['default_key'] == key_id:
                config['default_key'] = config['keys'][0]['id'] if config['keys'] else None
            for client in config['clients']:
                if client.get('key_id') == key_id:
                    client['key_id'] = None  # chooses a key by model from now on
        self.change(f'删除 API 密钥“{label}”', edit)

    def check_key(self, key_id):
        config = self.config()
        key = self.key(config, key_id)
        models, status = None, 'unreachable'
        try:
            models, status = self.fetch_models(key, config['proxy'] or None), 'ok'
        except KeyProblem as problem:
            status = problem.status
            raise
        finally:
            with self.lock:  # a check is not a change of settings: no history entry
                config = self.config()
                for entry in config['keys']:
                    if entry['id'] == key_id:
                        entry.update(status=status, checked_at=now())
                        if models is not None:
                            entry.update(models=models, models_checked_at=now())
                self.store.set_setting('gateway', config)
        return models

    def refresh_models(self):
        """Every key's model list, read at the same time. Returns how many models there are now, and what went wrong."""
        keys = self.config()['keys']
        if not keys:
            raise ValueError('请先添加 API 密钥。')
        problems = []

        def check(key):
            try:
                self.check_key(key['id'])
            except ValueError as problem:  # KeyProblem, or a key deleted meanwhile
                problems.append(f'“{key["name"]}”：{problem}')
        with ThreadPoolExecutor(max_workers=len(keys)) as pool:
            list(pool.map(check, keys))
        return len(offered(self.config()['keys'])), problems

    def save_client(self, client_id, data):
        """A new key for a program (client_id None), or changes to one: fields left out keep their values."""
        config = self.config()
        before = self.client(config, client_id) if client_id else {}
        data = {**{k: before[k] for k in ('name', 'key_id', 'mode', 'models', 'default_model', 'enabled') if k in before}, **data}
        name = name_of(data.get('name'), '专属密钥的名称')
        key_id = data.get('key_id') or None
        if key_id is not None:
            self.key(config, key_id)
        mode = data.get('mode') or 'choice'
        if mode not in ('choice', 'fixed'):
            raise ValueError('模型方式不正确。')
        models = data.get('models') or []
        if not isinstance(models, list) or len(models) > MAX_MODELS or not all(isinstance(m, str) and MODEL_ID.fullmatch(m) for m in models):
            raise ValueError('模型列表不正确。')
        models = list(dict.fromkeys(models))
        default = data.get('default_model') or None
        if default is not None and not (isinstance(default, str) and MODEL_ID.fullmatch(default)):
            raise ValueError('默认模型不正确。')
        if mode == 'fixed' and not default:
            raise ValueError('请选择固定使用的模型。')
        if mode == 'choice' and default and models and default not in models:
            raise ValueError('默认模型需要在可选模型里。')
        enabled = data.get('enabled', True)
        if not isinstance(enabled, bool):
            raise ValueError('启用开关的值不正确。')
        values = {'name': name, 'key_id': key_id, 'mode': mode, 'models': models if mode == 'choice' else [],
                  'default_model': default, 'enabled': enabled}

        def edit(config):
            if client_id is None:
                if len(config['clients']) >= MAX_CLIENTS:
                    raise ValueError(f'最多 {MAX_CLIENTS} 个专属密钥。')
                client = {'id': secrets.token_hex(8), 'token': TOKEN_PREFIX + secrets.token_urlsafe(30), 'created_at': now(), **values}
                config['clients'].append(client)
                return client['id']
            self.client(config, client_id).update(values)
            return client_id
        if client_id is None:
            summary = f'新建专属密钥“{name}”'
        elif before.get('enabled', True) != enabled and all(before.get(k) == v for k, v in values.items() if k != 'enabled'):
            summary = f'{"启用" if enabled else "停用"}专属密钥“{name}”'
        else:
            summary = f'修改专属密钥“{name}”'
        return self.change(summary, edit)

    def delete_client(self, client_id):
        label = self.client(self.config(), client_id)['name']

        def edit(config):
            config['clients'].remove(self.client(config, client_id))
        self.change(f'删除专属密钥“{label}”', edit)

    def client_token(self, client_id):
        return self.client(self.config(), client_id)['token']

    def rotate_client(self, client_id):
        label = self.client(self.config(), client_id)['name']

        def edit(config):
            client = self.client(config, client_id)
            client['token'] = TOKEN_PREFIX + secrets.token_urlsafe(30)
            return client['token']
        return self.change(f'更换专属密钥“{label}”', edit)

    def restore(self, index):
        """Back to earlier settings. API keys stay as they are now (the history never held them; only their names
        and the models typed in for them go back), and so do the keys of programs that still exist: a key replaced
        because it leaked does not come back. Whether the gateway is on stays too: going back must not cut off
        every program. Returns the programs whose API key is gone and which now choose a key by model."""
        history = self.history()
        if isinstance(index, bool) or not isinstance(index, int) or not 0 < index < len(history):
            raise ValueError('找不到这条历史记录。')
        entry = history[index]
        snapshot = entry['config']
        missing = []

        def edit(config):
            current = {key['id'] for key in config['keys']}
            tokens = {client['id']: client['token'] for client in config['clients']}
            before = {key['id']: key for key in snapshot.get('keys', []) if isinstance(key, dict)}
            for key in config['keys']:
                key['name'] = before.get(key['id'], {}).get('name', key['name'])
                key['manual_models'] = before.get(key['id'], {}).get('manual_models', key['manual_models'])
            for name in ('port', 'proxy'):
                config[name] = snapshot.get(name, config[name])
            if snapshot.get('default_key') in current:
                config['default_key'] = snapshot['default_key']
            config['clients'] = json.loads(json.dumps(snapshot.get('clients', [])))
            for client in config['clients']:
                client['token'] = tokens.get(client['id'], client['token'])
                if client.get('key_id') and client['key_id'] not in current:
                    missing.append(client['name'])
                    client['key_id'] = None
        when = datetime.fromtimestamp(entry['at']).strftime('%m-%d %H:%M')
        self.change(f'回到这一步：{entry["summary"]}（{when}）', edit)
        return missing

    def state(self):
        config = self.config()
        usage = self.usage_summary()
        return {
            'enabled': config['enabled'], 'port': config['port'], 'proxy': config['proxy'], 'running': self.running(),
            'error': self.error if config['enabled'] else None, 'address': f'http://127.0.0.1:{config["port"]}',
            'keys': [{'id': k['id'], 'name': k['name'], 'provider': k['provider'], 'provider_name': provider_name(k), 'api': api_of(k),
                      'base_url': k.get('base_url'), 'hint': mask(k['secret']), 'status': k.get('status', 'ok'),
                      'checked_at': k.get('checked_at'), 'default': k['id'] == config['default_key'],
                      'models': [{'id': m['id'], 'display_name': m.get('display_name') or m['id']} for m in k['models']],
                      'manual_models': k['manual_models'], 'models_checked_at': k.get('models_checked_at')} for k in config['keys']],
            'clients': [{**{k: c.get(k) for k in ('id', 'name', 'key_id', 'mode', 'models', 'default_model', 'created_at')},
                         'enabled': c.get('enabled', True), 'hint': mask(c['token']), 'usage': usage.get(c['id'])} for c in config['clients']],
            # Every model once, the default key's first: what a program on the automatic choice can use.
            'models': list(known(self.ordered(config)).values()),
            'models_checked_at': max((k.get('models_checked_at') or 0 for k in config['keys']), default=0) or None,
            'providers': catalog(),
            'history': [{'index': i, 'at': entry['at'], 'summary': entry['summary']} for i, entry in enumerate(self.history())],
        }

    # ---------- usage ----------

    def usage(self):
        value = self.store.get_setting('gateway_usage', {})
        return value if isinstance(value, dict) else {}

    def record(self, client_id, model, tokens, ok=True):
        """One finished request: day → program → model → requests, input, output, cache read, cache write, errors."""
        def count(name):
            value = tokens.get(name)
            return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0
        today = date.today()
        oldest = (today - timedelta(days=USAGE_DAYS)).isoformat()
        with self.usage_lock:
            usage = {day: clients for day, clients in self.usage().items() if day > oldest}
            entry = usage.setdefault(today.isoformat(), {}).setdefault(client_id, {}).setdefault(model or '?', [])
            entry.extend([0] * (len(USAGE_FIELDS) - len(entry)))
            values = (1, count('input_tokens'), count('output_tokens'), count('cache_read_input_tokens'),
                      count('cache_creation_input_tokens'), 0 if ok else 1)
            for i, value in enumerate(values):
                entry[i] += value
            self.store.set_setting('gateway_usage', usage)

    def usage_summary(self):
        """Per program: today, the last 30 days, and the last 30 days per model."""
        today = date.today()
        first = (today - timedelta(days=29)).isoformat()
        today = today.isoformat()
        totals = {}
        for day, clients in self.usage().items():
            if day < first or not isinstance(clients, dict):
                continue
            for client_id, models in clients.items():
                target = totals.setdefault(client_id, {'today': [0] * 6, 'month': [0] * 6, 'models': {}})
                for model, counts in (models.items() if isinstance(models, dict) else []):
                    counts = ([value if isinstance(value, int) else 0 for value in counts] + [0] * 6)[:6] if isinstance(counts, list) else [0] * 6
                    places = [target['month'], target['models'].setdefault(model, [0] * 6)] + ([target['today']] if day == today else [])
                    for place in places:
                        for i, value in enumerate(counts):
                            place[i] += value
        return {client_id: {'today': named(t['today']), 'month': named(t['month']),
                            'models': {model: named(c) for model, c in t['models'].items()}} for client_id, t in totals.items()}

    # ---------- the local server ----------

    def running(self):
        return bool(self.server and self.thread and self.thread.is_alive() and self.server.started)

    def apply(self):
        """Start, stop or move the server to match the settings."""
        with self.lock:
            config = self.config()
            if not config['enabled']:
                self.stop()
                self.error = None
                return
            if self.running() and self.port == config['port']:
                return
            self.stop()
            self.start(config['port'])

    def start(self, port):
        sock = bind(port)
        if not sock:
            self.error = f'端口 {port} 已被其他程序占用。请在网关设置里换一个端口。'
            return
        server = uvicorn.Server(uvicorn.Config(self.asgi, host='127.0.0.1', port=port, lifespan='on', ws='none', log_config=None,
                                               access_log=False, server_header=False, date_header=False, proxy_headers=False,
                                               timeout_graceful_shutdown=3))
        thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, name='gateway', daemon=True)
        self.server, self.thread, self.port = server, thread, port
        thread.start()
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.02)
        self.error = None if server.started else '网关没有启动，请关闭后重新开启。'
        if not server.started:
            sock.close()

    def stop(self):
        server, thread = self.server, self.thread
        self.server = self.thread = self.port = None
        if server:
            server.should_exit = True
        if thread and thread is not threading.current_thread():
            thread.join(8)

    def build_app(self):
        @asynccontextmanager
        async def lifespan(app):
            # Connections to the services for this run of the server: they belong to its event loop, so they are
            # closed with it rather than left to the garbage collector.
            upstreams = self.upstreams = {}
            try:
                yield
            finally:
                for client in list(upstreams.values()):
                    try:
                        await (client.aclose() if isinstance(client, httpx.AsyncClient) else client.close())
                    except Exception:
                        pass
                if self.upstreams is upstreams:
                    self.upstreams = {}
        routes = [Route('/', self.home), Route('/health', self.home)]
        for prefix in ('/v1', ''):
            routes += [Route(prefix + '/models', self.models, methods=['GET']),
                       Route(prefix + '/models/{model_id:path}', self.model, methods=['GET']),
                       Route(prefix + '/messages', self.messages, methods=['POST']),
                       Route(prefix + '/messages/count_tokens', self.count_tokens, methods=['POST']),
                       Route(prefix + '/chat/completions', self.chat, methods=['POST'])]
        return Guard(Starlette(routes=routes, lifespan=lifespan))

    async def home(self, request):
        return JSONResponse({'app': 'browser-workbench-gateway', 'ok': True})

    # ---------- requests ----------

    def authenticate(self, request):
        token = request.headers.get('x-api-key', '')
        authorization = request.headers.get('authorization', '')
        if not token and authorization[:7].lower() == 'bearer ':
            token = authorization[7:].strip()
        config = self.config()
        for client in config['clients']:
            if token and secrets.compare_digest(client['token'].encode(), token.encode()):
                if not client.get('enabled', True):
                    raise Refused(403, 'permission_error', f'专属密钥“{client["name"]}”已在 Browser Workbench 里停用。')
                return config, client
        raise Refused(401, 'authentication_error', '专属密钥不正确。请在 Browser Workbench 的“模型网关”里复制专属密钥。')

    @staticmethod
    def ordered(config):
        """Every usable key, the default one first."""
        keys = [key for key in config['keys'] if api_of(key) in (ANTHROPIC, OPENAI)]
        return sorted(keys, key=lambda key: key['id'] != config['default_key'])

    def candidates(self, config, client):
        """The keys a program's requests may go to: its own, or all of them (also when its own was deleted)."""
        own = [key for key in self.ordered(config) if key['id'] == client.get('key_id')]
        return own or self.ordered(config)

    def allowed(self, config, client, api=None):
        """The models a program may use; with api, only those a request in that format can reach."""
        keys = self.candidates(config, client)
        models = [client['default_model']] if client['mode'] == 'fixed' else client['models'] or offered(keys)
        if api:
            models = [model for model in models if any(api_of(key) == api for key in self.offering(keys, model) or keys)]
        return models

    @staticmethod
    def offering(keys, model):
        return [key for key in keys if model in key_models(key)]

    def choose(self, config, client, requested):
        if client['mode'] == 'fixed':
            return client['default_model']
        if not requested:
            if client.get('default_model'):
                return client['default_model']
            raise Refused(400, 'invalid_request_error', '请求没有指定模型。')
        if not isinstance(requested, str):
            raise Refused(400, 'invalid_request_error', 'model 应是文字。')
        allowed = self.allowed(config, client)
        if allowed and requested not in allowed:
            shown = '、'.join(allowed[:20]) + (f' 等 {len(allowed)} 个' if len(allowed) > 20 else '')
            raise Refused(400, 'invalid_request_error', f'专属密钥“{client["name"]}”不能使用模型 {requested}。可以用：{shown}')
        return requested

    def route(self, config, client, model, apis):
        """The key that answers a request for this model in a format of apis: the first key that offers the model;
        for a model no key lists (one newer than the list, say), the key of the service its name points to, then
        the default key."""
        keys = self.candidates(config, client)
        if not keys:
            raise Refused(503, 'api_error', 'Browser Workbench 的模型网关里还没有添加 API 密钥。')
        offering = self.offering(keys, model)
        for key in offering or sorted(keys, key=lambda key: key['provider'] != hinted(model)):
            if api_of(key) in apis:
                return key
        if offering:
            raise Refused(400, 'invalid_request_error', f'模型 {model} 由 {provider_name(offering[0])} 提供，只能用 OpenAI 兼容格式调用'
                          '（接口地址填 …/v1，即 /v1/chat/completions）。Anthropic 格式（/v1/messages，例如 Claude Code）只能用 Claude 模型。')
        raise Refused(400, 'invalid_request_error', 'Anthropic 格式（/v1/messages，例如 Claude Code）需要 Anthropic（Claude）或 Anthropic 兼容服务的 '
                      'API 密钥，这把专属密钥能用的 API 密钥里没有。其他模型请用 OpenAI 兼容格式（/v1/chat/completions）。')

    def upstream(self, config, key):
        """The SDK client for an Anthropic-format key."""
        proxy, base = config['proxy'] or None, self.endpoint(key)
        wanted = (key['secret'], base, proxy)
        if wanted not in self.upstreams:  # kept until the server stops: a stream may still be using an old one
            self.upstreams[wanted] = sdk().AsyncAnthropic(api_key=key['secret'] or 'none', base_url=base,
                                                          http_client=sdk_http(base, proxy, asynchronous=True))
        return self.upstreams[wanted]

    def relay_client(self, config, base):
        """The HTTP client for an OpenAI-format service; the key goes with each request."""
        proxy = config['proxy'] or None
        wanted = (OPENAI, urlsplit(base).netloc, proxy)
        if wanted not in self.upstreams:
            self.upstreams[wanted] = httpx.AsyncClient(**http_options(base, proxy, asynchronous=True), timeout=RELAY_TIMEOUT)
        return self.upstreams[wanted]

    async def body(self, request):
        try:
            if int(request.headers.get('content-length') or 0) > MAX_BODY:
                raise Refused(413, 'request_too_large', '请求超过 32 MB。')
        except ValueError:
            raise Refused(400, 'invalid_request_error', '请求格式不正确。') from None
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_BODY:
                raise Refused(413, 'request_too_large', '请求超过 32 MB。')
            chunks.append(chunk)
        try:
            data = json.loads(b''.join(chunks) or b'{}')
        except (ValueError, UnicodeError):
            raise Refused(400, 'invalid_request_error', '请求内容不是有效的 JSON。') from None
        if not isinstance(data, dict):
            raise Refused(400, 'invalid_request_error', '请求内容应是 JSON 对象。')
        return data

    @staticmethod
    def returned(headers):
        return {name: value for name, value in headers.items() if name.lower() in RETURNED or name.lower().startswith('anthropic-ratelimit-')}

    async def models(self, request):
        """An Anthropic client (it sends anthropic-version) is shown only the models it can ask for in its format."""
        style = 'anthropic' if request.headers.get('anthropic-version') else 'openai'
        try:
            config, client = self.authenticate(request)
        except Refused as refused:
            return failure(style, refused)
        return JSONResponse(listing(self.candidates(config, client), self.allowed(config, client, ANTHROPIC if style == 'anthropic' else None)))

    async def model(self, request):
        try:
            config, client = self.authenticate(request)
        except Refused as refused:
            return failure('anthropic', refused)
        for entry in listing(self.candidates(config, client), self.allowed(config, client))['data']:
            if entry['id'] == request.path_params['model_id']:
                return JSONResponse(entry)
        return failure('anthropic', Refused(404, 'not_found_error', '这个专属密钥不能使用这个模型。'))

    async def messages(self, request):
        return await self.passthrough(request, count=False)

    async def count_tokens(self, request):
        return await self.passthrough(request, count=True)

    async def passthrough(self, request, count):
        """The Messages API as it is: the program's own anthropic-version and anthropic-beta go along, so a
        program on an older API version gets that version's behaviour."""
        anthropic = sdk()
        try:
            config, client = self.authenticate(request)
            body = await self.body(request)
            body['model'] = self.choose(config, client, body.get('model'))
            key = self.route(config, client, body['model'], (ANTHROPIC,))
            messages = self.upstream(config, key).messages
        except Refused as refused:
            return failure('anthropic', refused)
        names = parameters()[1] if count else parameters()[0]
        known = {k: v for k, v in body.items() if k in names}
        for field in ('messages', 'model') if count else ('max_tokens', 'messages', 'model'):
            if field not in known:
                return failure('anthropic', Refused(400, 'invalid_request_error', f'{field}: Field required'))
        options = {'extra_body': {k: v for k, v in body.items() if k not in names} or None,
                   'extra_headers': {name: request.headers[name] for name in FORWARDED if request.headers.get(name)},
                   'extra_query': {'beta': 'true'} if request.query_params.get('beta') == 'true' else None}
        model = body['model']
        try:
            if count:
                raw = await messages.with_raw_response.count_tokens(**known, **options, timeout=60)
                return Response(await raw.http_response.aread(), status_code=raw.status_code, media_type='application/json',
                                headers=self.returned(raw.headers))
            if not body.get('stream'):
                raw = await messages.with_raw_response.create(**known, **options, timeout=1800)
                content = await raw.http_response.aread()
                try:
                    answer = json.loads(content)
                except ValueError:
                    answer = {}
                tokens = answer.get('usage') if isinstance(answer, dict) and isinstance(answer.get('usage'), dict) else {}
                await asyncio.to_thread(self.record, client['id'], model, tokens)
                return Response(content, status_code=raw.status_code, media_type='application/json', headers=self.returned(raw.headers))
            opened = messages.with_streaming_response.create(**known, **options)
            upstream = await opened.__aenter__()
        except anthropic.APIStatusError as exc:
            if not count:
                await asyncio.to_thread(self.record, client['id'], model, {}, False)
            return Response(exc.response.content, status_code=exc.status_code, media_type='application/json',
                            headers=self.returned(exc.response.headers))
        except anthropic.APIConnectionError as exc:
            return failure('anthropic', unreachable(exc, self.endpoint(key)))
        meter = Meter()

        async def relay():
            broken = True
            try:
                async for chunk in upstream.iter_bytes():
                    meter.feed(chunk)
                    yield chunk
                broken = False
            finally:
                # Also when the program went away: closing the connection stops the answer and its cost.
                with anyio.CancelScope(shield=True):
                    await opened.__aexit__(None, None, None)
                    ok = not meter.failed and (meter.complete or not broken)
                    await asyncio.to_thread(self.record, client['id'], model, meter.tokens, ok)
        return StreamingResponse(relay(), status_code=upstream.status_code, media_type='text/event-stream',
                                 headers={**self.returned(upstream.headers), 'Cache-Control': 'no-cache'})

    async def chat(self, request):
        try:
            config, client = self.authenticate(request)
            body = await self.body(request)
            model = self.choose(config, client, body.get('model'))
            key = self.route(config, client, model, (ANTHROPIC, OPENAI))
        except Refused as refused:
            return failure('openai', refused)
        if api_of(key) == OPENAI:
            return await self.relay(config, client, key, body, model)
        anthropic = sdk()
        base = self.endpoint(key)
        try:
            messages = self.upstream(config, key).messages
            info = next((m for m in key['models'] if m['id'] == model), {})
            params = openai_compat.to_anthropic(body, model, info.get('max_tokens'))
        except openai_compat.RequestError as exc:
            return failure('openai', Refused(400, 'invalid_request_error', str(exc)))
        if not body.get('stream'):
            try:
                # Streamed underneath: a long answer would outlast a plain request's time limit.
                async with messages.stream(**params) as stream:
                    message = await stream.get_final_message()
            except anthropic.APIStatusError as exc:
                await asyncio.to_thread(self.record, client['id'], model, {}, False)
                return failure('openai', upstream_refusal(exc))
            except anthropic.APIConnectionError as exc:
                return failure('openai', unreachable(exc, base))
            await asyncio.to_thread(self.record, client['id'], model, message.usage.model_dump())
            return JSONResponse(openai_compat.to_openai(message, model))
        try:
            events = await messages.create(**params, stream=True)
        except anthropic.APIStatusError as exc:
            await asyncio.to_thread(self.record, client['id'], model, {}, False)
            return failure('openai', upstream_refusal(exc))
        except anthropic.APIConnectionError as exc:
            return failure('openai', unreachable(exc, base))
        chunks = openai_compat.Chunks(model)
        with_usage = isinstance(body.get('stream_options'), dict) and body['stream_options'].get('include_usage') is True

        async def relay():
            ok = False
            try:
                try:
                    async for event in events:
                        for chunk in chunks.feed(event):
                            yield openai_compat.sse(chunk)
                    ok = True
                    if with_usage:
                        yield openai_compat.sse(chunks.usage_chunk())
                except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
                    refused = upstream_refusal(exc) if isinstance(exc, anthropic.APIStatusError) else unreachable(exc, base)
                    yield openai_compat.sse(openai_compat.error_body(refused.message, refused.kind))
                yield openai_compat.sse(b'[DONE]')
            finally:
                with anyio.CancelScope(shield=True):
                    await events.close()
                    await asyncio.to_thread(self.record, client['id'], model, chunks.tokens, ok)
        return StreamingResponse(relay(), media_type='text/event-stream', headers={'Cache-Control': 'no-cache'})

    async def relay(self, config, client, key, body, model):
        """A chat-completions request to an OpenAI-format service, passed on as it is but for the model (a program
        with a fixed model gets that one) and the key. A stream reports its token counts where the service can be
        asked to (stream_options); the chunk with them goes back only to a program that asked for it itself."""
        base = self.endpoint(key)
        host = urlsplit(base).hostname
        body = {**body, 'model': model}
        stream = body.get('stream') is True
        options = body.get('stream_options') if isinstance(body.get('stream_options'), dict) else {}
        added = stream and options.get('include_usage') is not True and PROVIDERS.get(key['provider'], {}).get('usage', False)
        if added:
            body['stream_options'] = {**options, 'include_usage': True}
        http = self.relay_client(config, base)
        sent = http.build_request('POST', base + '/chat/completions', json=body,
                                  headers={'accept': 'text/event-stream' if stream else 'application/json', **bearer(key)})
        try:
            response = await http.send(sent, stream=True)
        except httpx.TimeoutException:
            return failure('openai', Refused(504, 'api_error', f'{host} 长时间没有回应，请稍后重试。'))
        except httpx.HTTPError:
            return failure('openai', Refused(502, 'api_error', f'网关连不上 {host}。请检查网络；需要代理时，在 Browser Workbench 的网关设置里填写代理地址。'))
        headers = {name: value for name, value in response.headers.items()
                   if name.lower() in RETURNED_OPENAI or name.lower().startswith('x-ratelimit-')}
        if not stream or response.status_code >= 300 or 'text/event-stream' not in response.headers.get('content-type', ''):
            try:
                content = await response.aread()
            except httpx.HTTPError:
                return failure('openai', Refused(502, 'api_error', f'{host} 的回答中途断开了，请重试。'))
            finally:
                await response.aclose()
            ok = response.status_code < 300
            try:
                answer = json.loads(content) if ok else {}
            except ValueError:
                answer = {}
            await asyncio.to_thread(self.record, client['id'], model, openai_tokens(answer.get('usage') if isinstance(answer, dict) else None), ok)
            return Response(content, status_code=response.status_code, headers=headers,
                            media_type=response.headers.get('content-type', 'application/json'))
        lines = Lines(drop_usage=added)

        async def relay():
            broken = True
            try:
                async for chunk in response.aiter_bytes():
                    if passed := lines.feed(chunk):
                        yield passed
                if rest := lines.flush():
                    yield rest
                broken = False
            except httpx.HTTPError:
                yield openai_compat.sse(openai_compat.error_body(f'{host} 的回答中途断开了，请重试。', 'api_error'))
            finally:
                # Also when the program went away: closing the connection stops the answer and its cost.
                with anyio.CancelScope(shield=True):
                    await response.aclose()
                    ok = not lines.failed and (lines.done or not broken)
                    await asyncio.to_thread(self.record, client['id'], model, lines.tokens, ok)
        return StreamingResponse(relay(), status_code=response.status_code, media_type='text/event-stream',
                                 headers={**headers, 'Cache-Control': 'no-cache'})


class Lines:
    """An OpenAI-format event stream passed on line by line: token counts read on the way, and the usage-only chunk
    the gateway asked for itself left out (a program that did not ask for it may not expect a chunk without
    choices)."""

    def __init__(self, drop_usage):
        self.pending = b''
        self.tokens = {}
        self.done = self.failed = False
        self.drop_usage = drop_usage

    def feed(self, chunk):
        self.pending += chunk
        *lines, self.pending = self.pending.split(b'\n')
        return b''.join(line + b'\n' for line in lines if self.keep(line))

    def flush(self):
        rest, self.pending = self.pending, b''
        return rest if rest and self.keep(rest) else b''

    def keep(self, line):
        if not line.startswith(b'data:'):
            return True
        payload = line[5:].strip()
        if payload == b'[DONE]':
            self.done = True
            return True
        try:
            event = json.loads(payload)
        except ValueError:
            return True
        if not isinstance(event, dict):
            return True
        self.failed |= 'error' in event
        choices, usage = event.get('choices'), event.get('usage')
        if not isinstance(usage, dict) and isinstance(choices, list) and choices and isinstance(choices[0], dict):
            usage = choices[0].get('usage')  # Moonshot puts it in the last choice
        if isinstance(usage, dict):
            self.tokens = openai_tokens(usage)
        return not (self.drop_usage and choices == [] and isinstance(event.get('usage'), dict))


class Meter:
    """Token counts from a Messages event stream while it passes through unchanged."""

    def __init__(self):
        self.pending = b''
        self.tokens = {}
        self.complete = self.failed = False

    def feed(self, chunk):
        self.pending += chunk
        *lines, self.pending = self.pending.split(b'\n')
        for line in lines:
            if not line.startswith(b'data:'):
                continue
            try:
                event = json.loads(line[5:])
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            kind = event.get('type')
            self.complete |= kind == 'message_stop'
            self.failed |= kind == 'error'
            usage = (event.get('message') or {}).get('usage') if kind == 'message_start' else event.get('usage') if kind == 'message_delta' else None
            if isinstance(usage, dict):
                self.tokens.update({k: v for k, v in usage.items() if isinstance(v, int) and not isinstance(v, bool)})


def known(keys):
    """What the keys say about their models, each model once (from the first key that has it), with the service
    it is from."""
    found = {}
    for key in keys:
        for model in key.get('models') or []:
            found.setdefault(model['id'], {**model, 'provider': key['provider'], 'key_id': key['id']})
        for model in key.get('manual_models') or []:
            found.setdefault(model, {'id': model, 'display_name': model, 'provider': key['provider'], 'key_id': key['id'], 'manual': True})
    return found


def listing(keys, allowed):
    """The models a program may use, in a shape both the Anthropic and the OpenAI clients read."""
    found = known(keys)
    data = []
    for model_id in allowed:
        info = found.get(model_id, {})
        created = info.get('created_at') or '2025-01-01T00:00:00Z'
        try:
            stamp = int(datetime.fromisoformat(created.replace('Z', '+00:00')).timestamp())
        except ValueError:
            stamp = 0
        data.append({'id': model_id, 'type': 'model', 'display_name': info.get('display_name') or model_id, 'created_at': created,
                     'object': 'model', 'created': stamp, 'owned_by': info.get('provider') or 'browser-workbench'})
    return {'data': data, 'has_more': False, 'first_id': data[0]['id'] if data else None,
            'last_id': data[-1]['id'] if data else None, 'object': 'list'}


def upstream_refusal(exc):
    body = exc.body if isinstance(exc.body, dict) else {}
    error = body.get('error') if isinstance(body.get('error'), dict) else {}
    return Refused(exc.status_code, error.get('type') or 'api_error', error.get('message') or str(exc))


def unreachable(exc, base=ANTHROPIC_URL):
    host = urlsplit(base).hostname
    if isinstance(exc, sdk().APITimeoutError):
        return Refused(504, 'api_error', f'{"Anthropic" if base == ANTHROPIC_URL else host} 长时间没有回应，请稍后重试。')
    return Refused(502, 'api_error', f'网关连不上 {host}。请检查网络；需要代理时，在 Browser Workbench 的网关设置里填写代理地址。')


def failure(style, refused):
    if style == 'openai':
        return JSONResponse(openai_compat.error_body(refused.message, refused.kind), status_code=refused.status)
    return JSONResponse({'type': 'error', 'error': {'type': refused.kind, 'message': refused.message}}, status_code=refused.status)


class Guard:
    """Only this computer's own names (a web page cannot reach the server under a name of its own), and the
    CORS answers that tools running in a browser need: every request still needs a key from the workbench."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':  # lifespan
            return await self.app(scope, receive, send)
        headers = {k.decode('latin-1').lower(): v.decode('latin-1') for k, v in scope['headers']}
        host = headers.get('host', '')
        name = host[:host.find(']') + 1] if host.startswith('[') else host.partition(':')[0]
        if name.lower() not in ('127.0.0.1', 'localhost', '[::1]'):
            response = JSONResponse({'type': 'error', 'error': {'type': 'permission_error', 'message': 'Invalid host'}}, status_code=400)
            return await response(scope, receive, send)
        cors = [(b'access-control-allow-origin', b'*'), (b'access-control-expose-headers', b'request-id, x-request-id, retry-after')]
        if scope['method'] == 'OPTIONS':
            asked = headers.get('access-control-request-headers', 'authorization, content-type, x-api-key, anthropic-version, anthropic-beta')
            await send({'type': 'http.response.start', 'status': 204, 'headers': cors + [
                (b'access-control-allow-methods', b'GET, POST, OPTIONS'), (b'access-control-allow-headers', asked.encode('latin-1')),
                (b'access-control-max-age', b'600'), (b'content-length', b'0')]})
            return await send({'type': 'http.response.body', 'body': b''})

        async def with_cors(message):
            if message['type'] == 'http.response.start':
                message = {**message, 'headers': list(message.get('headers', [])) + cors}
            await send(message)
        await self.app(scope, receive, with_cors)
