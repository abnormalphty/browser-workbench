"""The AI websites an environment can be made for: the page it opens, and the plans its account can be recorded with.

An environment holds one website's sign-in. Environments from before this list existed are Claude environments.
Only Claude's plan can be checked from its own settings page (accounts.py); the others are recorded by hand.
"""
import ipaddress
from urllib.parse import urlsplit

DEFAULT = 'claude'
OTHER_PLAN = ('other', '其他套餐')

SERVICES = {
    'claude': {'name': 'Claude', 'url': 'https://claude.ai/', 'check': True,
               'plans': [('free', 'Free'), ('pro', 'Pro'), ('max', 'Max'), ('team', 'Team'), ('enterprise', 'Enterprise')]},
    'chatgpt': {'name': 'ChatGPT', 'url': 'https://chatgpt.com/',
                'plans': [('free', 'Free'), ('go', 'Go'), ('plus', 'Plus'), ('pro', 'Pro'), ('business', 'Business'),
                          ('enterprise', 'Enterprise')]},
    'gemini': {'name': 'Gemini', 'url': 'https://gemini.google.com/',
               'plans': [('free', '免费版'), ('ai_plus', 'Google AI Plus'), ('ai_pro', 'Google AI Pro'), ('ai_ultra', 'Google AI Ultra')]},
    'grok': {'name': 'Grok', 'url': 'https://grok.com/',
             'plans': [('free', 'Free'), ('supergrok', 'SuperGrok'), ('supergrok_heavy', 'SuperGrok Heavy'), ('x_premium', 'X Premium')]},
    'perplexity': {'name': 'Perplexity', 'url': 'https://www.perplexity.ai/',
                   'plans': [('free', 'Free'), ('pro', 'Pro'), ('max', 'Max'), ('enterprise', 'Enterprise')]},
    'copilot': {'name': 'Microsoft Copilot', 'url': 'https://copilot.microsoft.com/',
                'plans': [('free', '免费版'), ('pro', 'Copilot Pro'), ('m365', 'Microsoft 365')]},
    'deepseek': {'name': 'DeepSeek', 'url': 'https://chat.deepseek.com/', 'plans': [('free', '免费版')]},
    'kimi': {'name': 'Kimi', 'url': 'https://www.kimi.com/', 'plans': [('free', '免费版'), ('paid', '付费会员')]},
    'doubao': {'name': '豆包', 'url': 'https://www.doubao.com/chat/', 'plans': [('free', '免费版'), ('paid', '付费会员')]},
    'qianwen': {'name': '千问', 'url': 'https://www.qianwen.com/', 'plans': [('free', '免费版'), ('paid', '付费会员')]},
    'custom': {'name': '其他网站', 'url': None,
               'plans': [('free', '免费版'), ('paid', '付费'), ('team', '团队版'), ('enterprise', '企业版')]},
}


def service_id(value):
    """A known website's id; anything else is refused."""
    if value is None or value == '':
        return DEFAULT
    if not isinstance(value, str) or value not in SERVICES:
        raise ValueError('请选择环境要打开的网站。')
    return value


def check_url(value):
    """The page an "其他网站" environment opens: an https address of a public website."""
    value = value.strip() if isinstance(value, str) else ''
    if value and '://' not in value:
        value = 'https://' + value
    try:
        parts = urlsplit(value)
        _ = parts.port  # raises for a port that is not a number, or out of range
    except ValueError:
        parts = None
    if not parts or parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or len(value) > 500 \
            or any(c.isspace() or ord(c) < 32 for c in value):
        raise ValueError('请填写网站地址，例如 https://example.com/（只支持 https）。')
    host = parts.hostname
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if host == 'localhost' or host.endswith('.localhost') or (address and not address.is_global) or ('.' not in host and not address):
        raise ValueError('环境只能打开互联网上的网站，不能打开这台电脑或局域网里的地址。')
    return value


def start_url(env):
    """The page an environment opens when it starts."""
    service = SERVICES.get(env.get('service') or DEFAULT, SERVICES[DEFAULT])
    return env.get('start_url') or service['url'] or SERVICES[DEFAULT]['url']


def plans(service):
    return SERVICES.get(service or DEFAULT, SERVICES[DEFAULT])['plans'] + [OTHER_PLAN]


def plan_keys(service):
    return {'unknown'} | {key for key, _ in plans(service)}


def catalog():
    """What the page shows: every website with its address and plans."""
    return [{'id': key, 'name': value['name'], 'url': value['url'], 'check': bool(value.get('check')),
             'plans': [{'id': plan, 'name': name} for plan, name in plans(key)]} for key, value in SERVICES.items()]
