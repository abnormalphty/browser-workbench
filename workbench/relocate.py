"""Moves the app's data folder to a new place. The Windows window runs this while the backend is stopped:

    python -m workbench.relocate --from CURRENT_DATA_FOLDER --to NEW_ROOT --remember

Everything is copied to NEW_ROOT\\Data and checked file by file (size and SHA-256). Only then does
--remember point the app at the new place (HKCU\\Software\\BrowserWorkbench, DataLocation), and only
after that is the old folder renamed; it stays until the user deletes it in the app. If anything fails
before, the copy is removed and nothing has changed. Prints WORKBENCH_MOVE {...} lines: progress in
percent, then the result.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .storage import DATA, MOVE_RECORD, OLD_COPY, inside, old_copies, remove_tree

SETTINGS_KEY = r'Software\BrowserWorkbench'
CHUNK = 1 << 20
# Windows refuses to rename a folder while something holds a file inside it, which virus scanners do for a
# moment with files just written (and an Explorer window can too): try again for up to ten seconds.
RENAME_TRIES, RENAME_WAIT = 20, 0.5


def listing(folder):
    """Relative path → size of every file (None for a folder). Links and junctions are left out."""
    found = {}
    is_junction = getattr(os.path, 'isjunction', lambda path: False)
    for current, folders, files in os.walk(folder):
        folders[:] = [name for name in folders if not os.path.islink(os.path.join(current, name))
                      and not is_junction(os.path.join(current, name))]
        relative = Path(os.path.relpath(current, folder))
        for name in folders:
            found[(relative / name).as_posix()] = None
        for name in files:
            path = os.path.join(current, name)
            if not os.path.islink(path):
                found[(relative / name).as_posix()] = os.path.getsize(path)
    return {key.removeprefix('./'): value for key, value in found.items()}


def copy_checked(source, destination, progress):
    """Copies source into destination and reads the copy back; returns the bytes copied."""
    items = listing(source)
    total = sum(size for size in items.values() if size)
    work, done, hashes = max(1, 2 * total), 0, {}
    destination.mkdir(parents=True, exist_ok=True)
    for relative, size in sorted(items.items()):
        target = destination / relative
        if size is None:
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        with open(source / relative, 'rb') as reader, open(target, 'wb') as writer:
            while chunk := reader.read(CHUNK):
                writer.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                progress(done, work)
        shutil.copystat(source / relative, target)
        hashes[relative] = digest.hexdigest()
    if listing(destination) != items:
        raise ValueError('复制后的文件和原来的不一致，已取消移动，原来的数据没有改动。')
    for relative, expected in hashes.items():
        digest = hashlib.sha256()
        with open(destination / relative, 'rb') as reader:
            while chunk := reader.read(CHUNK):
                digest.update(chunk)
                done += len(chunk)
                progress(done, work)
        if digest.hexdigest() != expected:
            raise ValueError('复制后的文件和原来的不一致，已取消移动，原来的数据没有改动。')
    return total


def remember(root):
    """Where the Windows window looks for the data (windows/AppPaths.cs)."""
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, SETTINGS_KEY) as key:
        winreg.SetValueEx(key, 'DataLocation', 0, winreg.REG_SZ, str(root))


def rename(source, destination):
    for attempt in range(RENAME_TRIES):
        try:
            return source.rename(destination)
        except OSError:
            if attempt == RENAME_TRIES - 1:
                raise
            time.sleep(RENAME_WAIT)


def free_name(path):
    candidate, number = path, 2
    while candidate.exists():
        candidate = path.with_name(f'{path.name} {number}')
        number += 1
    return candidate


def relocate(source, root, keep=False, progress=lambda done, work: None):
    """Moves the data folder source to root\\Data; keep=True records the new place for the app."""
    source, root = Path(source), Path(root)
    target, partial = root / DATA, root / (DATA + '.partial')
    if not source.is_dir():
        raise ValueError('找不到现在的数据文件夹。')
    if inside(target, source) or inside(source, target):
        raise ValueError('新位置不能在现在的数据文件夹里面，也不能包含它。')
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ValueError('新位置已经有一份工作台数据。')
    root.mkdir(parents=True, exist_ok=True)
    if partial.exists():
        remove_tree(partial)
    try:
        total = copy_checked(source, partial, progress)
        if target.exists():
            target.rmdir()
        rename(partial, target)
        if keep:
            remember(root)
    except BaseException:
        # The app still uses the old folder (checked above to be a different one): drop the copy.
        for leftover in (partial, target):
            if leftover.exists():
                try:
                    remove_tree(leftover)
                except OSError:
                    pass
        raise
    # The app now uses the copy. The old folder gets a name that says what it is, so nothing opens it by mistake.
    old = free_name(source.parent / OLD_COPY)
    try:
        rename(source, old)
    except OSError:
        old = source
        try:
            (source / '已移到新位置.txt').write_text(f'这里的数据已复制到 {target}。确认新位置一切正常后，可以删除这个文件夹。\n',
                                                 encoding='utf-8')
        except OSError:
            pass
    record = {'from': str(source), 'to': str(target), 'moved_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'bytes': total, 'old_copies': [*old_copies(target), str(old)]}
    (target / MOVE_RECORD).write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
    return record


def report(**fields):
    print('WORKBENCH_MOVE ' + json.dumps(fields, ensure_ascii=False), flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Move the Browser Workbench data folder')
    parser.add_argument('--from', dest='source', required=True)
    parser.add_argument('--to', dest='root', required=True)
    parser.add_argument('--remember', action='store_true', help='point the Windows app at the new place')
    args = parser.parse_args(argv)
    shown = -1

    def progress(done, work):
        nonlocal shown
        percent = min(99, done * 100 // work)
        if percent != shown:
            shown = percent
            report(progress=percent)
    try:
        record = relocate(args.source, args.root, keep=args.remember, progress=progress)
    except (OSError, ValueError) as exc:
        report(ok=False, error=str(exc) if isinstance(exc, ValueError) else f'移动没有完成：{exc}。原来的数据没有改动。')
        return 1
    report(ok=True, **record)
    return 0


if __name__ == '__main__':
    sys.exit(main())
