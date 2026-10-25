"""Read proxy subscriptions without importing a provider's application settings."""
import base64
import asyncio
import copy
import ipaddress
import json
import re
import socket
from urllib.parse import parse_qs, unquote, urlsplit

import httpx
import yaml

# Clash configs from airports often carry megabytes of rules next to a few hundred nodes.
MAX_BYTES = 32 * 1024 * 1024
MAX_MB = MAX_BYTES // (1024 * 1024)
TOP_PROXIES = re.compile(r'^proxies[ \t]*:', re.M)
TOP_ENTRY = re.compile(r'^[^\s#-]', re.M)  # a line that starts the next top-level entry
SUPPORTED = {'ss', 'vmess', 'vless', 'trojan', 'hysteria', 'hysteria2', 'tuic', 'socks5', 'http', 'snell', 'anytls'}
FIELDS = {'name', 'type', 'server', 'port', 'password', 'username', 'cipher', 'uuid', 'alterId', 'udp', 'tls', 'servername', 'sni', 'skip-cert-verify', 'network', 'flow', 'client-fingerprint', 'alpn', 'ws-opts', 'grpc-opts', 'h2-opts', 'http-opts', 'reality-opts', 'plugin', 'plugin-opts', 'obfs', 'obfs-password', 'auth', 'auth-str', 'up', 'down', 'recv-window-conn', 'recv-window', 'disable-mtu-discovery', 'fast-open', 'version', 'heartbeat-interval', 'reduce-rtt', 'request-timeout', 'udp-relay-mode', 'congestion-controller', 'disable-sni', 'idle-session-check-interval', 'idle-session-timeout', 'min-idle-session', 'ip-version', 'tfo'}
NESTED = {
    'ws-opts': {'path', 'headers', 'max-early-data', 'early-data-header-name', 'v2ray-http-upgrade', 'v2ray-http-upgrade-fast-open'},
    'grpc-opts': {'grpc-service-name'},
    'h2-opts': {'host', 'path'},
    'http-opts': {'method', 'path', 'headers'},
    'reality-opts': {'public-key', 'short-id'},
    'plugin-opts': {'mode', 'host', 'path', 'tls', 'skip-cert-verify', 'mux', 'headers', 'fingerprint'},
}


class SubscriptionError(ValueError):
    pass


def _b64(value: str) -> str:
    try:
        return base64.urlsafe_b64decode(value.strip() + '=' * (-len(value.strip()) % 4)).decode('utf-8-sig')
    except (ValueError, UnicodeError) as exc:
        raise SubscriptionError('订阅编码无法识别，请使用通用或 Clash 订阅链接。') from exc


def _bounded(value, depth=0):
    if depth > 6:
        raise SubscriptionError('节点配置层级过深。')
    if isinstance(value, dict):
        if len(value) > 64:
            raise SubscriptionError('节点字段过多。')
        for k, v in value.items():
            if not isinstance(k, str) or len(k) > 100:
                raise SubscriptionError('节点字段格式不正确。')
            _bounded(v, depth + 1)
    elif isinstance(value, list):
        if len(value) > 64:
            raise SubscriptionError('节点列表过长。')
        for v in value:
            _bounded(v, depth + 1)
    elif isinstance(value, str):
        if len(value) > 8192 or '\x00' in value:
            raise SubscriptionError('节点字段内容不正确。')
    elif value is not None and not isinstance(value, (bool, int, float)):
        raise SubscriptionError('节点字段类型不支持。')


def validate_node(node: dict) -> dict:
    if not isinstance(node, dict):
        raise SubscriptionError('节点必须是配置对象。')
    _bounded(node)
    extra = set(node) - FIELDS
    if extra:
        # Never pass file paths, interface selectors or references to arbitrary
        # provider-owned proxies into our controlled runtime configuration.
        raise SubscriptionError('节点包含不支持的配置字段：' + ', '.join(sorted(extra)[:3]))
    n = copy.deepcopy(node)
    if n.get('type') not in SUPPORTED:
        raise SubscriptionError('订阅包含暂不支持的节点协议。')
    if not isinstance(n.get('server'), str) or not n['server'].strip() or re.search(r'[\s/\\@]', n['server']):
        raise SubscriptionError('节点服务器地址不正确。')
    port = n.get('port')
    if isinstance(port, bool) or not str(port).isdigit() or not 1 <= int(port) <= 65535:
        raise SubscriptionError('节点端口必须在 1–65535 之间。')
    n['port'] = int(port)
    name = n.get('name') or n['server']
    if not isinstance(name, str) or len(name) > 150:
        raise SubscriptionError('节点名称过长。')
    n['name'] = name
    for key, allowed in NESTED.items():
        if key in n and (not isinstance(n[key], dict) or set(n[key]) - allowed):
            raise SubscriptionError(f'节点的 {key} 配置不支持。')
    if n.get('plugin') not in (None, 'obfs', 'v2ray-plugin'):
        raise SubscriptionError('暂不支持该 Shadowsocks 插件。')
    return n


def _uri(line: str) -> dict:
    if line.startswith('vmess://'):
        try:
            v = json.loads(_b64(line[8:].split('#')[0]))
            n = dict(name=v.get('ps') or 'VMess', type='vmess', server=v['add'], port=v['port'], uuid=v['id'], alterId=int(v.get('aid', 0)), cipher=v.get('scy') or 'auto', tls=v.get('tls') == 'tls')
            if v.get('sni'):
                n['servername'] = v['sni']
            if v.get('net') == 'ws':
                n.update(network='ws', **{'ws-opts': {'path': v.get('path') or '/', 'headers': {'Host': v.get('host') or v['add']}}})
            elif v.get('net') == 'grpc':
                n.update(network='grpc', **{'grpc-opts': {'grpc-service-name': v.get('path') or ''}})
            elif v.get('net') not in (None, '', 'tcp'):
                raise SubscriptionError('该 VMess 传输方式暂不支持。')
            return validate_node(n)
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise SubscriptionError('VMess 节点格式不正确。') from exc
    if line.startswith('ss://'):
        body, _, fragment = line[5:].partition('#')
        if '@' not in body:
            body = _b64(body)
        url = urlsplit('ss://' + body)
        userinfo = url.netloc.rsplit('@', 1)[0]
        auth = unquote(userinfo) if ':' in userinfo else _b64(userinfo)
        cipher, sep, password = auth.partition(':')
        if not sep:
            raise SubscriptionError('Shadowsocks 节点缺少认证信息。')
        n = dict(name=unquote(fragment) or 'Shadowsocks', type='ss', server=url.hostname, port=url.port, cipher=cipher, password=password)
        plugin = parse_qs(url.query).get('plugin', [''])[0]
        if plugin:
            parts = plugin.split(';')
            opts = dict(p.split('=', 1) for p in parts[1:] if '=' in p)
            n['plugin'] = 'obfs' if parts[0] in ('obfs-local', 'simple-obfs') else parts[0]
            n['plugin-opts'] = {('mode' if k == 'obfs' else 'host' if k == 'obfs-host' else k): v for k, v in opts.items()}
        return validate_node(n)
    url = urlsplit(line)
    scheme = {'hy2': 'hysteria2', 'socks': 'socks5', 'https': 'http'}.get(url.scheme, url.scheme)
    if scheme not in SUPPORTED:
        raise SubscriptionError('订阅含有不支持的节点链接。')
    q = {k: v[-1] for k, v in parse_qs(url.query).items()}
    n = dict(name=unquote(url.fragment) or scheme.upper(), type=scheme, server=url.hostname, port=url.port or (443 if scheme in ('trojan', 'vless', 'hysteria2') else 1080))
    if scheme in ('trojan', 'hysteria2'):
        n['password'] = unquote(url.username or '')
        if url.password:
            n['password'] += ':' + unquote(url.password)
    elif scheme == 'vless':
        n['uuid'] = unquote(url.username or '')
        n['tls'] = q.get('security') in ('tls', 'reality')
        if q.get('flow'):
            n['flow'] = q['flow']
    else:
        if url.username:
            n['username'] = unquote(url.username)
        if url.password:
            n['password'] = unquote(url.password)
        if url.scheme == 'https':
            n['tls'] = True
    if q.get('sni') or q.get('peer'):
        n['sni' if scheme == 'hysteria2' else 'servername'] = q.get('sni') or q['peer']
    if q.get('insecure') in ('1', 'true') or q.get('allowInsecure') in ('1', 'true'):
        n['skip-cert-verify'] = True
    if q.get('alpn'):
        n['alpn'] = q['alpn'].split(',')
    if q.get('fp'):
        n['client-fingerprint'] = q['fp']
    if q.get('type') == 'ws':
        n.update(network='ws', **{'ws-opts': {'path': q.get('path', '/'), 'headers': {'Host': q.get('host') or url.hostname}}})
    elif q.get('type') == 'grpc':
        n.update(network='grpc', **{'grpc-opts': {'grpc-service-name': q.get('serviceName', '')}})
    elif q.get('type') not in (None, '', 'tcp'):
        raise SubscriptionError('该节点的传输方式暂不支持。')
    if q.get('security') == 'reality':
        n['reality-opts'] = {'public-key': q.get('pbk', ''), 'short-id': q.get('sid', '')}
    if q.get('obfs'):
        n['obfs'] = q['obfs']
        n['obfs-password'] = q.get('obfs-password', '')
    return validate_node(n)


def _proxies_entry(text: str):
    """The top-level proxies list. When that entry can be cut out on its own, only it is parsed,
    so the rule lists that make these configs large never become Python objects."""
    loader = getattr(yaml, 'CSafeLoader', yaml.SafeLoader)
    starts = [m.start() for m in TOP_PROXIES.finditer(text)]
    if len(starts) == 1:
        end = TOP_ENTRY.search(text, starts[0] + 1)
        try:
            data = yaml.load(text[starts[0]:end.start() if end else None], Loader=loader)
        except yaml.YAMLError:
            data = None  # e.g. anchors defined elsewhere in the document
        if isinstance(data, dict) and isinstance(data.get('proxies'), list):
            return data['proxies']
    data = yaml.load(text, Loader=loader)
    return data.get('proxies') if isinstance(data, dict) else None


def _usable(read, items, skipped):
    """One unsupported node does not block the rest; a subscription without any usable node fails."""
    nodes, errors = [], []
    for item in items:
        try:
            nodes.append(read(item))
        except (ValueError, TypeError) as exc:
            errors.append(exc)
    if not nodes:
        raise errors[0]
    if skipped is not None:
        skipped.extend(errors)
    return nodes


def parse_subscription(text: str, skipped: list | None = None) -> list[dict]:
    """Nodes this workbench can run. Errors of the nodes left out are appended to `skipped`."""
    if not isinstance(text, str) or len(text.encode()) > MAX_BYTES:
        raise SubscriptionError(f'订阅内容过大，最多支持 {MAX_MB} MB。')
    text = text.lstrip('\ufeff').strip()
    if not text or text.startswith('<'):
        raise SubscriptionError('链接没有返回节点订阅，可能已失效或需要登录。')
    try:
        if '://' not in text and not re.search(r'(^|\n)\s*proxies\s*:', text):
            text = _b64(text)
        if re.search(r'(^|\n)\s*proxies\s*:', text):
            raw = _proxies_entry(text)
            if not isinstance(raw, list) or not raw or len(raw) > 1000:
                raise SubscriptionError('订阅中没有节点，或节点超过 1000 个。')
            return _usable(validate_node, raw, skipped)
        lines = [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith('#')]
        if not lines or len(lines) > 1000:
            raise SubscriptionError('订阅中没有可识别的节点。')
        return _usable(_uri, lines, skipped)
    except SubscriptionError:
        raise
    except (ValueError, TypeError, yaml.YAMLError, RecursionError) as exc:
        raise SubscriptionError('无法解析该订阅，请使用通用或 Clash 订阅链接。') from exc


def _public_url(url: str):
    try:
        u = urlsplit(url)
        if u.scheme not in ('http', 'https') or not u.hostname or u.username or u.password or len(url) > 8192:
            raise ValueError()
        try:
            literal = ipaddress.ip_address(u.hostname)
        except ValueError:
            literal = None
        if literal and not literal.is_global:
            raise ValueError()
        addresses = socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == 'https' else 80), type=socket.SOCK_STREAM)
        # TUN clients on this Mac resolve public names into their RFC 2544
        # fake-IP pool. Allow that DNS result, never a literal private URL.
        fake_pool = ipaddress.ip_network('198.18.0.0/15')
        def routable(address):
            ip = ipaddress.ip_address(address)
            return ip.is_global or (literal is None and ip.version == 4 and ip in fake_pool)
        if not addresses or any(not routable(a[4][0]) for a in addresses):
            raise ValueError()
    except (OSError, ValueError) as exc:
        raise SubscriptionError('订阅链接必须是可访问的公网 HTTP/HTTPS 地址。') from exc


async def fetch_subscription(url: str) -> str:
    url = url.strip()
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
            for _ in range(6):
                await asyncio.to_thread(_public_url, url)
                async with client.stream('GET', url, headers={'User-Agent': 'clash.meta/1.19', 'Accept': 'text/plain, application/yaml, */*'}) as response:
                    if response.is_redirect:
                        from urllib.parse import urljoin
                        url = urljoin(url, response.headers.get('location', ''))
                        continue
                    response.raise_for_status()
                    chunks, size = [], 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise SubscriptionError(f'订阅超过 {MAX_MB} MB，导入已停止。')
                        chunks.append(chunk)
                    return b''.join(chunks).decode('utf-8-sig')
        raise SubscriptionError('订阅跳转次数过多。')
    except SubscriptionError:
        raise
    except (httpx.HTTPError, UnicodeError) as exc:
        # Never include exception text: it commonly contains the secret URL.
        raise SubscriptionError('订阅暂时无法获取，请检查链接、网络或稍后重试。') from exc
