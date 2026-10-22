"""Small transactional store. Secret nodes never leave this module unredacted."""
import hashlib
import json
import os
import re
import secrets
import sqlite3
import time
import uuid
from pathlib import Path

ID = re.compile(r'^[a-f0-9]{32}$')


class Store:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = self.data_dir / 'workbench.sqlite3'
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS nodes (id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS environments (id TEXT PRIMARY KEY, name TEXT NOT NULL, node_id TEXT, fingerprint_seed TEXT NOT NULL, created_at REAL NOT NULL);
            ''')
            if 'engine' not in {row[1] for row in db.execute('PRAGMA table_info(environments)')}:
                db.execute("ALTER TABLE environments ADD COLUMN engine TEXT NOT NULL DEFAULT 'camoufox'")
            if 'timezone_mode' not in {row[1] for row in db.execute('PRAGMA table_info(environments)')}:
                db.execute("ALTER TABLE environments ADD COLUMN timezone_mode TEXT NOT NULL DEFAULT 'legacy'")
            columns={row[1] for row in db.execute('PRAGMA table_info(environments)')}
            if 'cpu_limit' not in columns:db.execute('ALTER TABLE environments ADD COLUMN cpu_limit REAL NOT NULL DEFAULT 2')
            if 'memory_limit_mb' not in columns:db.execute('ALTER TABLE environments ADD COLUMN memory_limit_mb INTEGER NOT NULL DEFAULT 2048')
        os.chmod(self.db, 0o600)

    def connect(self):
        db = sqlite3.connect(self.db, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def valid_id(value: str) -> str:
        if not isinstance(value, str) or not ID.fullmatch(value):
            raise ValueError('环境或节点标识不正确。')
        return value

    def get_setting(self, key: str, default=None):
        with self.connect() as db:
            row = db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key: str, value):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO settings VALUES (?, ?)', (key, json.dumps(value)))

    def resource_settings(self):
        value=self.get_setting('resource_settings',{'max_running':2})
        return {'max_running':value.get('max_running',2)}

    def save_resource_settings(self,data):
        value=data.get('max_running')
        if isinstance(value,bool) or not isinstance(value,int) or not 1<=value<=100:
            raise ValueError('同时运行上限应为 1—100 个环境。')
        self.set_setting('resource_settings',{'max_running':value})
        return self.resource_settings()

    def set_environment_limits(self,env_id,data):
        from .resources import validate_limits
        self.get_environment(env_id);limits=validate_limits(data)
        with self.connect() as db:
            db.execute('UPDATE environments SET cpu_limit=?,memory_limit_mb=? WHERE id=?',(limits['cpu_limit'],limits['memory_limit_mb'],env_id))
        return self.get_environment(env_id)

    def account_info(self,env_id):
        self.get_environment(env_id)
        return self.get_setting('account:'+env_id,{'label':'','plan':'unknown','status':'unknown','source':'unknown','checked_at':None,'last_attempt':None,'verified':False,'plan_source':'unknown','status_source':'unknown','plan_checked_at':None,'status_checked_at':None})

    def save_account_info(self,env_id,data):
        self.get_environment(env_id)
        if data.get('plan') not in ('unknown','free','pro','max','team','enterprise') or data.get('status') not in ('unknown','active','blocked','logged_out'):
            raise ValueError('账号套餐或状态不正确。')
        label=data.get('label','')
        if not isinstance(label,str):raise ValueError('账号备注应为文字。')
        label=label.strip()
        if not isinstance(label,str) or len(label)>120 or any(ord(c)<32 for c in label):raise ValueError('账号备注最多 120 字。')
        value={'label':label,'plan':data['plan'],'status':data['status'],'source':'manual','checked_at':time.time(),'last_attempt':None,'verified':False,'plan_source':'manual','status_source':'manual','plan_checked_at':time.time(),'status_checked_at':time.time()}
        self.set_setting('account:'+env_id,value);return value

    def get_subscription_url(self):
        return self.get_setting('subscription_url')

    def save_subscription(self, url: str, nodes: list[dict]):
        if not nodes:
            raise ValueError('订阅没有可用节点，保留原来的订阅。')
        prepared = []
        for node in nodes:
            identity = json.dumps([node['type'], node['server'], node['port'], node['name']], ensure_ascii=False)
            node_id = hashlib.sha256(identity.encode()).hexdigest()[:32]
            prepared.append((node_id, json.dumps(node, ensure_ascii=False)))
        with self.connect() as db:
            db.execute('DELETE FROM nodes')
            db.executemany('INSERT OR REPLACE INTO nodes VALUES (?,?)', prepared)
            for key, value in [('subscription_url', url), ('subscription_updated', time.time())]:
                db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (key, json.dumps(value)))

    def get_node(self, node_id: str):
        self.valid_id(node_id)
        with self.connect() as db:
            row = db.execute('SELECT data FROM nodes WHERE id=?', (node_id,)).fetchone()
        if not row:
            raise ValueError('原节点已不在订阅中，请为环境重新选择节点。')
        return json.loads(row[0])

    def list_environments(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM environments ORDER BY created_at')]

    def get_environment(self, env_id: str):
        self.valid_id(env_id)
        with self.connect() as db:
            row = db.execute('SELECT * FROM environments WHERE id=?', (env_id,)).fetchone()
        if not row:
            raise ValueError('找不到这个环境。')
        return dict(row)

    def create_environment(self, name: str, node_id: str | None, engine: str = 'firefox', cpu_limit=2, memory_limit_mb=2048):
        if engine != 'firefox':
            raise ValueError('当前仅支持标准 Firefox，旧内核已移除。')
        from .resources import validate_limits
        limits=validate_limits({'cpu_limit':cpu_limit,'memory_limit_mb':memory_limit_mb})
        name = name.strip()
        if len(name) > 80 or any(ord(c) < 32 for c in name):
            raise ValueError('环境名称最多 80 个字符，不能包含控制字符。')
        if node_id:
            self.get_node(node_id)
        env_id = uuid.uuid4().hex
        with self.connect() as db:
            count = db.execute('SELECT COUNT(*) FROM environments').fetchone()[0]
            if count >= 100:
                raise ValueError('首版最多保存 100 个环境。')
            db.execute('INSERT INTO environments (id,name,node_id,fingerprint_seed,created_at,engine,timezone_mode,cpu_limit,memory_limit_mb) VALUES (?,?,?,?,?,?,?,?,?)', (env_id, name or f'环境 {count+1:02d}', node_id or None, secrets.token_hex(16), time.time(), engine,'node',limits['cpu_limit'],limits['memory_limit_mb']))
        return self.get_environment(env_id)

    def update_environment(self, env_id: str, name: str, node_id: str | None):
        self.get_environment(env_id)
        name = name.strip()
        if not name or len(name) > 80 or any(ord(c) < 32 for c in name):
            raise ValueError('请填写 1–80 个字符的环境名称。')
        if node_id:
            self.get_node(node_id)
        with self.connect() as db:
            db.execute('UPDATE environments SET name=?, node_id=? WHERE id=?', (name, node_id or None, env_id))
        return self.get_environment(env_id)

    def delete_environment(self, env_id: str):
        self.get_environment(env_id)
        with self.connect() as db:
            db.execute('DELETE FROM environments WHERE id=?', (env_id,))

    def public_state(self):
        from .geography import node_location
        with self.connect() as db:
            nodes = []
            for row in db.execute('SELECT * FROM nodes'):
                n = json.loads(row['data'])
                nodes.append({'id': row['id'], 'name': n['name'], 'type': n['type'],'geo':node_location(self,row['id'],n['name'])})
        envs = self.list_environments()
        for env in envs:
            env.pop('fingerprint_seed', None)
            env['account']=self.account_info(env['id'])
        return {'nodes': nodes, 'environments': envs, 'subscription': {'configured': bool(self.get_subscription_url()), 'updated_at': self.get_setting('subscription_updated')}}
