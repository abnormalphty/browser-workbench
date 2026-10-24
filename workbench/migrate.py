"""Copy an older workbench data folder into the app's data folder.

The source is only read: its SQLite database is snapshotted with the backup
API and its files are copied with ditto, so the old workbench keeps working.
Refuses while the old environments run (their Firefox profiles are live) and
never overwrites a destination that already holds environments or nodes.

    python -m workbench.migrate inspect SOURCE
    python -m workbench.migrate copy SOURCE TARGET
"""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid

from .docker_env import command_env, find_cli

DATABASE = 'workbench.sqlite3'


class MigrationError(ValueError):
    pass


def _counts(database):
    try:
        with closing(sqlite3.connect(Path(database).resolve().as_uri()+'?mode=ro', uri=True)) as db:
            environments = db.execute('SELECT COUNT(*) FROM environments').fetchone()[0]
            nodes = db.execute('SELECT COUNT(*) FROM nodes').fetchone()[0]
            subscription = db.execute("SELECT COUNT(*) FROM settings WHERE key='subscription_url'").fetchone()[0]
        return {'environments':environments, 'nodes':nodes, 'subscription':bool(subscription)}
    except sqlite3.Error as exc:
        raise MigrationError('数据文件无法读取，可能不是工作台的数据文件夹。') from exc


def _started_containers(scope):
    """Started containers of that data folder; None when Docker cannot be asked."""
    docker = find_cli()
    if not docker:
        return 0
    try:
        engine = subprocess.run([docker, 'info', '--format', '{{.ServerVersion}}'], capture_output=True, text=True, timeout=10, env=command_env(docker))
        if engine.returncode:
            return 0  # No running engine means no environment can be running.
        listed = subprocess.run([docker, 'ps', '--filter', f'label=workbench.scope={scope}', '--format', '{{.State}}'], capture_output=True, text=True, timeout=10, env=command_env(docker))
    except (OSError, subprocess.SubprocessError):
        return None
    if listed.returncode:
        return None
    return sum(state.strip() in ('running', 'paused', 'restarting') for state in listed.stdout.splitlines())


def inspect_source(source):
    source = Path(source).expanduser().resolve()
    if not (source/DATABASE).is_file():
        raise MigrationError('所选文件夹不是工作台数据文件夹（里面应有 workbench.sqlite3）。请选择旧版工作台目录里的 data 文件夹。')
    size = files = 0
    for path in source.rglob('*'):
        if path.is_file() and not path.is_symlink():
            files += 1
            size += path.stat().st_size
    # Same scope rule as Runtime: containers are labelled by data folder path.
    scope = hashlib.sha256(str(source).encode()).hexdigest()[:12]
    return {'source':str(source), **_counts(source/DATABASE), 'files':files, 'size_bytes':size, 'scope':scope, 'started':_started_containers(scope)}


def target_has_data(target):
    target = Path(target)
    if (target/DATABASE).is_file():
        counts = _counts(target/DATABASE)
        if counts['environments'] or counts['nodes'] or counts['subscription']:
            return True
    environments = target/'environments'
    return environments.is_dir() and any(environments.iterdir())


def copy_data(source, target):
    info = inspect_source(source)
    if info['started'] is None:
        raise MigrationError('暂时无法向 Docker 确认旧环境是否已停止，请稍后重试。')
    if info['started']:
        raise MigrationError(f"旧版工作台还有 {info['started']} 个环境在运行或低功耗。请先在旧版里停止它们再导入，避免复制到正在写入的登录数据。")
    source, target = Path(info['source']), Path(target).expanduser()
    if target.resolve() == source or source in target.resolve().parents:
        raise MigrationError('导入位置不能在旧数据文件夹里面。')
    if target.exists() and target_has_data(target):
        raise MigrationError('新版里已经有环境或订阅，为避免覆盖，不能再导入。')
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.parent/f'.{target.name}.import-{uuid.uuid4().hex[:8]}'
    try:
        # ditto keeps permissions, extended attributes and symbolic links.
        copied = subprocess.run(['/usr/bin/ditto', str(source), str(staging)], capture_output=True, timeout=3600)
        if copied.returncode:
            raise MigrationError('复制数据时出错，请检查磁盘空间后重试；旧数据没有改动。')
        for name in (DATABASE, DATABASE+'-journal', DATABASE+'-wal', DATABASE+'-shm', '.workbench.lock'):
            (staging/name).unlink(missing_ok=True)
        # A file copy of a database in use can be torn; the backup API cannot.
        with closing(sqlite3.connect((source/DATABASE).as_uri()+'?mode=ro', uri=True)) as old, closing(sqlite3.connect(staging/DATABASE)) as new:
            old.backup(new)
            if new.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise MigrationError('数据库副本校验失败，没有导入；旧数据没有改动。')
        os.chmod(staging/DATABASE, 0o600)
        copied_counts = _counts(staging/DATABASE)
        if (copied_counts['environments'], copied_counts['nodes']) != (info['environments'], info['nodes']):
            raise MigrationError('复制后的环境数量不一致，没有导入；旧数据没有改动。')
        previous = None
        if target.exists():
            # Keep what the app created on first launch instead of deleting it.
            previous = target.parent/f'{target.name}.before-import-{time.strftime("%Y%m%d-%H%M%S")}'
            target.rename(previous)
        staging.rename(target)
        os.chmod(target, 0o700)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {'ok':True, 'target':str(target), 'previous':str(previous) if previous else None,
            'environments':info['environments'], 'nodes':info['nodes'], 'files':info['files'], 'size_bytes':info['size_bytes']}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        if len(argv) == 2 and argv[0] == 'inspect':
            result = {'ok':True, **inspect_source(argv[1])}
        elif len(argv) == 3 and argv[0] == 'copy':
            result = copy_data(argv[1], argv[2])
        elif len(argv) == 2 and argv[0] == 'has-data':
            result = {'ok':True, 'has_data':Path(argv[1]).exists() and target_has_data(argv[1])}
        else:
            raise MigrationError('用法：inspect SOURCE | copy SOURCE TARGET | has-data TARGET')
    except (MigrationError, OSError) as exc:
        message = str(exc) if isinstance(exc, MigrationError) else '读取或复制数据时出错，旧数据没有改动。'
        print(json.dumps({'ok':False, 'error':message}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
