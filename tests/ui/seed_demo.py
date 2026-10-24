"""Fill a throwaway data folder with clearly fake nodes and environments.

For screenshots and design work only: servers are *.example.invalid and the
subscription address does not exist. Refuses to touch a folder that has data.
Usage: .venv/bin/python tests/ui/seed_demo.py DATA_DIR
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from workbench.geography import PLACES, validate_location  # noqa: E402
from workbench.store import Store  # noqa: E402

target = Path(sys.argv[1])
if (target/'workbench.sqlite3').exists():
    raise SystemExit('refusing: this folder already holds workbench data')

store = Store(target)
NODES = [('🇯🇵 东京 01 · IEPL', 'vmess'), ('🇯🇵 东京 02', 'trojan'), ('🇺🇸 洛杉矶 01', 'ss'), ('🇺🇸 圣何塞 02', 'vless'),
         ('🇸🇬 新加坡 01', 'trojan'), ('🇭🇰 香港 01', 'ss'), ('🇭🇰 香港 02', 'vmess'), ('🇹🇼 台北 01', 'hysteria2'),
         ('🇬🇧 伦敦 01', 'trojan'), ('🇩🇪 法兰克福 01', 'vless'), ('🇰🇷 首尔 01', 'ss'), ('🇦🇺 悉尼 01', 'trojan')]
nodes = []
for index, (name, kind) in enumerate(NODES, 1):
    node = {'name': name, 'type': kind, 'server': f'node{index}.example.invalid', 'port': 443}
    if kind == 'ss':
        node.update(cipher='aes-128-gcm', password='demo')
    elif kind in ('trojan', 'hysteria2'):
        node['password'] = 'demo'
    else:
        node.update(uuid='00000000-0000-4000-8000-000000000000')
        if kind == 'vmess':
            node.update(alterId=0, cipher='auto')
    nodes.append(node)
store.save_subscription('https://example.invalid/demo-subscription', nodes)
ids = {node['name']: node['id'] for node in store.public_state()['nodes']}
for name, place in [('🇯🇵 东京 01 · IEPL', 'tokyo'), ('🇺🇸 洛杉矶 01', 'los-angeles'), ('🇸🇬 新加坡 01', 'singapore')]:
    store.set_setting('node_location:'+ids[name], validate_location({**PLACES[place], 'source': 'manual'}))

environments = [
    ('个人 Claude', '🇯🇵 东京 01 · IEPL', 2, 2048, {'label': 'me@example.com', 'plan': 'max', 'status': 'active'}),
    ('工作空间', '🇺🇸 洛杉矶 01', 1.5, 3072, {'label': 'work@example.com', 'plan': 'pro', 'status': 'active'}),
    ('测试账号', '🇸🇬 新加坡 01', 1, 1536, {'label': 'test@example.com', 'plan': 'free', 'status': 'blocked'}),
    ('备用环境', None, 1, 1536, None),
]
for name, node, cpu, memory, account in environments:
    env = store.create_environment(name, ids[node] if node else None, cpu_limit=cpu, memory_limit_mb=memory)
    if account:
        store.save_account_info(env['id'], account)
store.save_resource_settings({'max_running': 3})
print(f'seeded {len(nodes)} fake nodes and {len(environments)} environments in {target}')
