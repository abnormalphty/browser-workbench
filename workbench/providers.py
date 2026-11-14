"""The services whose API keys the 模型网关 takes, and what it needs to know about each: where it calls,
which format the service speaks, and how its keys look.

Anthropic is called with its official SDK and speaks the Messages API. The others speak OpenAI's
chat-completions format; the gateway passes such requests on as they are, so a program that knows that
format can use their models through the same local address. "其他兼容服务" is any service with an address
of the user's own (a company's endpoint, or Ollama on this computer) in either format.

Only API keys are taken. Sign-ins to the websites (ChatGPT, Claude, Gemini …) are not API keys: their
terms allow no such use, and the gateway refuses the tokens they use.
"""
import ipaddress
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

ANTHROPIC, OPENAI = 'anthropic', 'openai'

# base: the address the requests go to (an OpenAI-format one ends before /chat/completions); for Anthropic the
# gateway's own setting (tests point it at a fake). usage: accepts stream_options.include_usage, so a stream
# reports its token counts. check: a path that answers only for a valid key, where /models answers anyone.
PROVIDERS = {
    'anthropic': {'name': 'Anthropic（Claude）', 'api': ANTHROPIC, 'base': None, 'example': 'sk-ant-api03-…',
                  'console': 'https://platform.claude.com/settings/keys'},
    'openai': {'name': 'OpenAI（GPT）', 'api': OPENAI, 'base': 'https://api.openai.com/v1', 'example': 'sk-proj-…', 'usage': True,
               'console': 'https://platform.openai.com/api-keys'},
    'gemini': {'name': 'Google Gemini', 'api': OPENAI, 'base': 'https://generativelanguage.googleapis.com/v1beta/openai',
               'example': 'AIza…', 'console': 'https://aistudio.google.com/apikey'},
    'deepseek': {'name': 'DeepSeek', 'api': OPENAI, 'base': 'https://api.deepseek.com/v1', 'example': 'sk-…', 'usage': True,
                 'console': 'https://platform.deepseek.com/api_keys'},
    'xai': {'name': 'xAI（Grok）', 'api': OPENAI, 'base': 'https://api.x.ai/v1', 'example': 'xai-…', 'usage': True,
            'console': 'https://console.x.ai/'},
    'moonshot': {'name': 'Moonshot（Kimi）', 'api': OPENAI, 'base': 'https://api.moonshot.cn/v1', 'example': 'sk-…',
                 'console': 'https://platform.moonshot.cn/console/api-keys'},
    'dashscope': {'name': '阿里云百炼（通义千问）', 'api': OPENAI, 'base': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
                  'example': 'sk-…', 'usage': True, 'console': 'https://bailian.console.aliyun.com/'},
    'ark': {'name': '火山方舟（豆包）', 'api': OPENAI, 'base': 'https://ark.cn-beijing.volces.com/api/v3', 'example': '',
            'usage': True, 'console': 'https://console.volcengine.com/ark/'},
    'zhipu': {'name': '智谱 BigModel（GLM）', 'api': OPENAI, 'base': 'https://open.bigmodel.cn/api/paas/v4', 'example': '',
              'console': 'https://open.bigmodel.cn/usercenter/apikeys'},
    'openrouter': {'name': 'OpenRouter', 'api': OPENAI, 'base': 'https://openrouter.ai/api/v1', 'example': 'sk-or-v1-…',
                   'usage': True, 'check': '/key', 'console': 'https://openrouter.ai/settings/keys'},
    'custom': {'name': '其他兼容服务', 'api': None, 'base': None, 'example': '', 'console': None},
}
MODEL_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:@/+~-]{0,199}', re.ASCII)
# Whose a model is by its name, for a model no key lists: it goes to that service's key first.
NAMED = (('claude-', 'anthropic'), ('gpt-', 'openai'), ('chatgpt-', 'openai'), ('o1', 'openai'), ('o3', 'openai'),
         ('o4', 'openai'), ('gemini-', 'gemini'), ('gemma-', 'gemini'), ('deepseek-', 'deepseek'), ('grok-', 'xai'),
         ('kimi-', 'moonshot'), ('moonshot-', 'moonshot'), ('qwen', 'dashscope'), ('qwq', 'dashscope'),
         ('doubao-', 'ark'), ('glm-', 'zhipu'))
MAX_LISTED = 400  # a key's model list (OpenRouter lists hundreds)
# Models a chat program cannot use through /chat/completions: left out of the lists, still usable when typed in.
NOT_CHAT = re.compile(r'embed|tts|whisper|dall-e|moderation|transcri|davinci|babbage|gpt-image|sora|rerank|realtime|imagen|veo-|^aqa$')
PREFIXES = ('sk-ant-', 'sk-proj-', 'sk-or-v1-', 'sk-', 'xai-', 'AIza')


def provider_id(value):
    if value is None or value == '':
        return ANTHROPIC  # what every key was before other services could be added
    if not isinstance(value, str) or value not in PROVIDERS:
        raise ValueError('请选择 API 密钥所属的服务。')
    return value


def provider_name(key):
    return PROVIDERS.get(key.get('provider') or ANTHROPIC, PROVIDERS['custom'])['name']


def api_of(key):
    """The format a key's service speaks; None for a service this version does not know (the key is then not used)."""
    provider = key.get('provider') or ANTHROPIC
    return key.get('api') if provider == 'custom' else PROVIDERS.get(provider, {}).get('api')


def hinted(model):
    """The service a model's name points to, or None."""
    name = model.lower() if isinstance(model, str) else ''
    return next((provider for prefix, provider in NAMED if name.startswith(prefix)), None)


def mask(secret):
    """The start and the end of a key, enough to tell keys apart."""
    if not secret:
        return '不用密钥'
    prefix = next((p for p in PREFIXES if secret.startswith(p)), '')
    return prefix + '…' + secret[-4:]


def check_secret(provider, secret):
    secret = secret.strip() if isinstance(secret, str) else ''
    if provider == 'custom' and not secret:
        return ''  # a service of one's own may need none (Ollama, LM Studio)
    # Sign-ins to the websites, not API keys: whatever service the key is said to be for.
    if secret.startswith('sk-ant-oat'):
        raise ValueError('这是 Claude 订阅（claude.ai / Claude Code 登录）用的令牌，不是 API 密钥。订阅账号不能这样使用；请在 Claude Console 创建 API 密钥。')
    if secret.startswith('sk-ant-sid'):
        raise ValueError('这是 claude.ai 网页登录的会话密钥，不是 API 密钥。网页账号不能这样使用；请在 Claude Console 创建 API 密钥。')
    if secret.startswith(('eyJ', 'sess-')):
        raise ValueError('这像是网页登录用的令牌（例如 ChatGPT 网页的登录信息），不是 API 密钥。网页订阅不能这样使用；请在对应平台的控制台创建 API 密钥。')
    if secret.startswith('ya29.'):
        raise ValueError('这是 Google 账号的登录令牌，不是 API 密钥。请在 Google AI Studio 创建 API 密钥。')
    if provider == ANTHROPIC:
        if secret.startswith('sk-ant-admin'):
            raise ValueError('这是管理员密钥（Admin key），不能调用模型。请在 Claude Console 创建普通的 API 密钥。')
        if not re.fullmatch(r'sk-ant-[A-Za-z0-9_-]{20,300}', secret):
            raise ValueError('Anthropic 的 API 密钥以 sk-ant- 开头，请从 Claude Console 完整复制。')
        return secret
    if provider != 'custom' and secret.startswith('sk-ant-'):
        raise ValueError('这是 Anthropic 的 API 密钥，“服务”请选 Anthropic（Claude）。')
    if provider == 'openai' and secret.startswith('sk-admin-'):
        raise ValueError('这是 OpenAI 的管理员密钥（Admin key），不能调用模型。请在 OpenAI 平台创建普通的 API 密钥。')
    if not re.fullmatch(r'[\x21-\x7e]{8,400}', secret):
        raise ValueError('API 密钥应是一串连续的字母、数字和符号，请从控制台完整复制。')
    return secret


def local(host):
    """This computer, or an address of the local network."""
    host = (host or '').strip('[]').lower()
    if host == 'localhost' or host.endswith('.localhost'):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private or address.is_link_local


def own_computer(host):
    host = (host or '').strip('[]').lower()
    if host == 'localhost' or host.endswith('.localhost'):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def check_base(value, api, gateway_port=None):
    """The address of an "其他兼容服务" key: https, or plain http for this computer and the local network (Ollama,
    LM Studio and the like); without the path of a single request, which people often copy along."""
    value = value.strip() if isinstance(value, str) else ''
    if value and '://' not in value:
        value = ('http://' if local(urlsplit('//' + value).hostname) else 'https://') + value
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        parts = port = None
    if not parts or parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password \
            or parts.query or parts.fragment or len(value) > 300 or any(c.isspace() or ord(c) < 32 for c in value):
        raise ValueError('请填写服务的接口地址，例如 https://api.example.com/v1。')
    if parts.scheme == 'http' and not local(parts.hostname):
        raise ValueError('互联网上的服务只能用 https 地址；http 只用于这台电脑或局域网里的服务。')
    if gateway_port and own_computer(parts.hostname) and (port or 80) == gateway_port:
        raise ValueError('这是模型网关自己的地址。请填写真正提供模型的服务地址。')
    path = parts.path.rstrip('/')
    for ending in (('/chat/completions', '/completions') if api == OPENAI else ('/v1/messages', '/messages', '/v1')):
        if path.endswith(ending):
            path = path[:-len(ending)]
            break
    return f'{parts.scheme}://{parts.netloc}{path}'


def check_models(value):
    """Models typed in by hand, for services that do not list them (or list them incompletely)."""
    if value is None:
        return []
    if isinstance(value, str):
        value = value.replace('，', ',').replace(',', '\n').split()
    if not isinstance(value, list) or len(value) > 100 or not all(isinstance(m, str) and MODEL_ID.fullmatch(m.strip()) for m in value):
        raise ValueError('模型名称不正确：每行一个，只能包含字母、数字和 . _ - : / @ 等符号。')
    return list(dict.fromkeys(m.strip() for m in value))


def listed_model(item):
    """One entry of an OpenAI-format /models answer, in the shape the gateway keeps; None for one it cannot use."""
    if not isinstance(item, dict) or not isinstance(item.get('id'), str):
        return None
    model_id = item['id'].removeprefix('models/')  # Gemini lists its models as models/…
    if not MODEL_ID.fullmatch(model_id) or NOT_CHAT.search(model_id.lower()):
        return None
    created = item.get('created')
    created = datetime.fromtimestamp(created, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ') \
        if isinstance(created, int) and not isinstance(created, bool) and 0 < created < 4e9 else ''
    name = item.get('name') if isinstance(item.get('name'), str) and 0 < len(item['name']) <= 100 else model_id
    return {'id': model_id, 'display_name': name, 'created_at': created}


def openai_tokens(usage):
    """OpenAI-format usage in the gateway's own terms: input without the cached part, which is counted apart."""
    def count(source, name):
        value = source.get(name) if isinstance(source, dict) else None
        return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0
    if not isinstance(usage, dict):
        return {}
    prompt = count(usage, 'prompt_tokens')
    cached = min(count(usage.get('prompt_tokens_details'), 'cached_tokens') or count(usage, 'prompt_cache_hit_tokens'), prompt)
    return {'input_tokens': prompt - cached, 'output_tokens': count(usage, 'completion_tokens'), 'cache_read_input_tokens': cached}


def catalog():
    """What the page offers when a key is added."""
    return [{'id': key, 'name': value['name'], 'api': value['api'], 'base': value['base'], 'example': value['example'],
             'console': value['console']} for key, value in PROVIDERS.items()]
