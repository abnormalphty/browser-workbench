"""Where the Windows app keeps things, and what moving its data folder involves.

The data folder holds the database (subscriptions, environments, account records) and each
environment's transfer folders. The user picks its place when installing and can move it later: the
window (windows/MainForm.cs) stops the backend and runs relocate.py. Each environment's login data
is a Docker volume, inside Docker Desktop's Linux disk together with the browser image; Docker
Desktop decides where that disk is (the app installs it next to the data folder when that folder was
moved off its default place).
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .docker_env import LOCAL_APP_DATA, command_env, wsl_data_dir
from .system import quiet, windows

DATA = 'Data'
SUBFOLDER = 'BrowserWorkbench'
DEFAULT_ROOT = LOCAL_APP_DATA / SUBFOLDER
# After a move: the old folder's new name, and the record (in the moved folder) of where old copies are.
OLD_COPY = '旧数据（已移到新位置，可以删除）'
MOVE_RECORD = 'storage-move.json'
# docker's sizes come in decimal units ("45.2MB").
UNITS = {'b': 1, 'kb': 1000, 'mb': 1000 ** 2, 'gb': 1000 ** 3, 'tb': 1000 ** 4}
DRIVE_REMOTE = 4


def canonical(path):
    """For comparing places: links resolved as far as the path exists, case folded where Windows ignores it."""
    return os.path.normcase(os.path.realpath(path))


def same_path(a, b):
    return canonical(a) == canonical(b)


def inside(path, folder):
    """path is folder or somewhere below it."""
    path, folder = canonical(path), canonical(folder)
    return path == folder or path.startswith(folder.rstrip('\\/') + os.sep)


def folder_size(path):
    """Bytes in a folder's files. Links and junctions are not followed."""
    total, stack = 0, [Path(path)]
    while stack:
        try:
            with os.scandir(stack.pop()) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink() or (hasattr(entry, 'is_junction') and entry.is_junction()):
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def parse_size(text):
    match = re.fullmatch(r'\s*([\d.]+)\s*([kKmMgGtT]?[bB])\s*', text or '')
    return int(float(match.group(1)) * UNITS[match.group(2).lower()]) if match else None


def volume_sizes(docker):
    """Each Docker volume's size; empty when Docker is not running. Docker adds them up, which takes a moment."""
    if not docker:
        return {}
    try:
        result = subprocess.run([docker, 'system', 'df', '-v', '--format', '{{json .}}'], capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=120, env=command_env(docker), **quiet())
    except (OSError, subprocess.SubprocessError):
        return {}
    sizes = {}
    for line in result.stdout.splitlines() if result.returncode == 0 else []:
        try:
            data = json.loads(line)
        except ValueError:
            continue
        for volume in (data.get('Volumes') or []) if isinstance(data, dict) else []:
            size = parse_size(volume.get('Size'))
            if volume.get('Name') and size is not None:
                sizes[volume['Name']] = size
    return sizes


def data_root():
    """The folder the user chose for the data (its Data folder inside), as the window says; None when the
    data folder is set some other way (tests, the source version)."""
    root = os.environ.get('WORKBENCH_DATA_ROOT')
    return Path(root) if root else None


def docker_data_root():
    """Where a Docker Desktop installed by the app keeps its Linux disk: next to the data folder when the user
    put that elsewhere, otherwise Docker Desktop's own default (None)."""
    root = data_root()
    if not windows() or root is None or same_path(root, DEFAULT_ROOT):
        return None
    return root / 'Docker'


def docker_disk(installed=True):
    """Docker Desktop's Linux disk on Windows: its folder and the size of its disk files. Before Docker Desktop
    is installed, the folder the app would install it with (docker_setup.install_command)."""
    if not windows():
        return None
    folder = wsl_data_dir() if installed else docker_data_root() or wsl_data_dir()
    size = None
    try:
        if folder.is_dir():
            size = sum(path.stat().st_size for path in folder.rglob('*.vhdx') if path.is_file())
    except OSError:
        pass
    return {'folder': str(folder), 'bytes': size, 'free_bytes': free_space(folder), 'installed': installed}


def free_space(path):
    path = Path(path)
    while not path.exists() and path.parent != path:
        path = path.parent
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return None


def move_record(data_dir):
    try:
        record = json.loads((Path(data_dir) / MOVE_RECORD).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return record if isinstance(record, dict) else {}


def old_copies(data_dir):
    """Copies a move left behind that still exist."""
    copies = move_record(data_dir).get('old_copies')
    return [path for path in copies if isinstance(path, str) and Path(path).is_dir()] if isinstance(copies, list) else []


def overview(store, runtime):
    """Everything the storage dialog shows. Sizes are added up now, so this takes a moment."""
    data_dir = store.data_dir
    volumes = runtime.volume_profiles()
    listed = store.list_environments()
    sizes = volume_sizes(runtime.docker) if volumes and listed else {}
    environments = []
    for env in listed:
        folder = data_dir / 'environments' / env['id']
        item = {'id': env['id'], 'name': env['name'], 'folder': str(folder), 'folder_bytes': folder_size(folder)}
        if volumes:
            item['volume'] = runtime.profile_volume(env['id'])
            item['volume_bytes'] = sizes.get(item['volume'])
        environments.append(item)
    install = os.environ.get('WORKBENCH_INSTALL_DIR')
    root = data_root()
    return {
        'install_dir': install or None,
        'data_root': str(root) if root else None,
        'data_dir': str(data_dir),
        'data_bytes': folder_size(data_dir),
        'free_bytes': free_space(data_dir),
        'docker': docker_disk(bool(runtime.docker)),
        'profiles_in_docker': volumes,
        'environments': environments,
        'old_copies': [{'folder': path, 'bytes': folder_size(path)} for path in old_copies(data_dir)],
        # Only the Windows window can move the folder: it stops the backend first.
        'can_move': windows() and root is not None and os.environ.get('WORKBENCH_MODE') == 'desktop',
    }


def remote_drive(path):
    if str(path).startswith(('\\\\', '//')):
        return True
    if not windows():
        return False
    try:
        import ctypes
        return ctypes.windll.kernel32.GetDriveTypeW(Path(path).anchor) == DRIVE_REMOTE
    except (AttributeError, OSError):
        return False


def move_target(store, chosen):
    """Where moving the data to the folder the user picked would put it; a ValueError says why it cannot go there."""
    if not isinstance(chosen, str) or not chosen.strip():
        raise ValueError('请选择一个文件夹。')
    root = Path(chosen.strip())
    if not root.is_absolute() or (windows() and not root.drive):
        raise ValueError('请选择一个完整的文件夹位置。')
    if remote_drive(root):
        raise ValueError('不能放在网络位置上，请选择这台电脑上的磁盘。')
    current = store.data_dir
    # A folder already holding other things gets a subfolder of its own, like installers do.
    if root.is_dir() and any(root.iterdir()) and not same_path(root, DEFAULT_ROOT) and not same_path(root, current.parent):
        root = root / SUBFOLDER
    target = root / DATA
    if same_path(target, current):
        raise ValueError('数据已经在这个位置。')
    if inside(target, current) or inside(current, target):
        raise ValueError('新位置不能在现在的数据文件夹里面，也不能包含它。')
    install = os.environ.get('WORKBENCH_INSTALL_DIR')
    if install and inside(target, install):
        raise ValueError('不要把数据放进程序文件夹：卸载或升级时它可能被删掉。请选择其他文件夹。')
    if target.is_dir() and any(target.iterdir()):
        raise ValueError('那里已经有一份工作台数据。请选择其他文件夹。')
    created = [] if root.exists() else [folder for folder in (root, *root.parents) if not folder.exists()]
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / '.workbench-write-test'
        probe.write_bytes(b'')
        probe.unlink()
    except OSError as exc:
        raise ValueError('不能写入这个位置（可能需要管理员权限）。请选择其他文件夹，例如 D:\\BrowserWorkbench。') from exc
    finally:
        for folder in created:  # leave nothing behind if the user changes their mind
            try:
                folder.rmdir()
            except OSError:
                break
    size = folder_size(current)
    free = free_space(root)
    if free is not None and free < size + 200 * 1024 ** 2:
        raise ValueError(f'空间不够：数据约 {size / 1024 ** 2:.0f} MB，那里只剩 {free / 1024 ** 2:.0f} MB。')
    return {'root': str(root), 'data_dir': str(target), 'bytes': size, 'free_bytes': free}


def remove_tree(folder):
    def writable_again(function, path, *_):
        # Windows refuses to delete read-only files.
        os.chmod(path, 0o700)
        function(path)
    if sys.version_info >= (3, 12):
        shutil.rmtree(folder, onexc=writable_again)
    else:
        shutil.rmtree(folder, onerror=writable_again)


def delete_old_copy(store, folder):
    """Deletes one copy a move left behind, and only such a copy."""
    if not any(same_path(folder, path) for path in old_copies(store.data_dir)):
        raise ValueError('找不到这份旧数据，可能已经删除。')
    if inside(store.data_dir, folder) or inside(folder, store.data_dir):
        raise ValueError('不能删除正在使用的数据。')
    remove_tree(folder)
    record = move_record(store.data_dir)
    record['old_copies'] = old_copies(store.data_dir)
    (store.data_dir / MOVE_RECORD).write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
