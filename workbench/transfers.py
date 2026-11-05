"""Only designated transfer directories are exposed, never a browser profile."""
import base64
from contextlib import contextmanager
import os
import re
import stat
import time
import uuid
from urllib.parse import quote

from .system import windows

MAX_UPLOAD = 100 * 1024 * 1024
# macOS walks the folders through directory descriptors, so a name swapped for a link mid-way is
# never followed. Windows has no dir_fd: there every name is checked with lstat right before use.
DIR_FD = os.open in os.supports_dir_fd and hasattr(os, 'O_NOFOLLOW') and hasattr(os, 'O_DIRECTORY')
REPARSE_POINT = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT: Windows symbolic links and junctions
# On Windows these would be refused, or worse, "a:b" would write a hidden stream of file a.
WINDOWS_RESERVED = re.compile(r'(?i)^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?$')


def checked_name(name, max_bytes=220):
    if not isinstance(name, str) or not name or len(name.encode('utf-8')) > max_bytes:
        raise ValueError('文件名不能为空，且最多 220 字节。')
    if name in ('.', '..') or any(c in name for c in '/\\') or any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise ValueError('文件名不能包含路径或控制字符。')
    if windows() and (any(c in name for c in '<>:"|?*') or name.endswith(('.', ' ')) or WINDOWS_RESERVED.match(name)):
        raise ValueError('文件名含有 Windows 不允许的字符或名称。')
    return name


def file_id(name):
    return base64.urlsafe_b64encode(name.encode()).decode().rstrip('=')


def file_name(identity):
    try:
        if not isinstance(identity, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,400}', identity):
            raise ValueError()
        return checked_name(base64.b64decode(identity+'='*((-len(identity))%4), altchars=b'-_', validate=True).decode(), max_bytes=255)
    except (ValueError, UnicodeError):
        raise ValueError('文件标识不正确。')


def linked(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & REPARSE_POINT)


class Folder:
    """One transfer folder whose entries are never reached through a link."""
    def __init__(self, fd=None, path=None):
        self.fd, self.path = fd, path

    def at(self, name):
        return name if self.fd is not None else os.path.join(self.path, name)

    def names(self):
        return os.listdir(self.fd if self.fd is not None else self.path)

    def scan(self):
        return os.scandir(self.fd if self.fd is not None else self.path)

    def create(self, name):
        if self.fd is not None:
            return os.open(name, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600, dir_fd=self.fd)
        return os.open(self.at(name), os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os, 'O_BINARY', 0), 0o600)

    def link(self, source, target):
        if self.fd is not None:
            os.link(source, target, src_dir_fd=self.fd, dst_dir_fd=self.fd, follow_symlinks=False)
        else:
            os.link(self.at(source), self.at(target))

    def unlink(self, name):
        if self.fd is not None:
            os.unlink(name, dir_fd=self.fd)
        else:
            os.unlink(self.at(name))

    def open_file(self, name):
        if self.fd is not None:
            return os.open(name, os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK, dir_fd=self.fd)
        if linked(os.lstat(self.at(name))):
            raise OSError('links are not followed')
        return os.open(self.at(name), os.O_RDONLY|getattr(os, 'O_BINARY', 0))


class Transfers:
    def __init__(self, store, env_id):
        store.get_environment(env_id)
        self.store, self.env_id = store, env_id
        self.path = store.data_dir/'environments'/env_id/'profile'/'transfer'

    @contextmanager
    def directory(self, kind):
        if kind not in ('incoming', 'downloads'):
            raise ValueError('只能访问传入文件或下载文件。')
        fd = None
        try:
            if not DIR_FD:
                path = str(self.store.data_dir)
                for segment in (None, 'environments', self.env_id, 'profile', 'transfer', kind):
                    if segment:
                        path = os.path.join(path, segment)
                        try: os.mkdir(path, mode=0o700)
                        except FileExistsError: pass
                    info = os.lstat(path)
                    if linked(info) or not stat.S_ISDIR(info.st_mode):
                        raise OSError('links are not followed')
                yield Folder(path=path)
                return
            fd = os.open(self.store.data_dir, os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            for segment in ('environments', self.env_id, 'profile', 'transfer', kind):
                try: os.mkdir(segment, mode=0o700, dir_fd=fd)
                except FileExistsError: pass
                child = os.open(segment, os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd); fd = child
            yield Folder(fd=fd)
        except OSError as exc:
            raise ValueError('文件目录不可访问，请检查该环境的文件传输目录。') from exc
        finally:
            if fd is not None: os.close(fd)

    def list(self, kind):
        result = []
        with self.directory(kind) as folder:
            pending = kind == 'downloads' and any(name.lower().endswith(('.part','.crdownload')) for name in folder.names())
            with folder.scan() as entries:
                for item in entries:
                    if re.fullmatch(r'\.[a-f0-9]{32}\.part', item.name) or (kind == 'downloads' and (item.name.startswith('.') or item.name.lower().endswith(('.part','.tmp','.crdownload')))):
                        continue
                    try:
                        info = item.stat(follow_symlinks=False)
                        checked_name(item.name,max_bytes=255)
                    except (OSError, ValueError): continue
                    if linked(info) or not stat.S_ISREG(info.st_mode): continue
                    # Firefox creates an empty final-name placeholder while its
                    # real data is still being written to a separate .part file.
                    if kind == 'downloads' and info.st_size == 0 and (pending or time.time()-info.st_mtime < 2):
                        continue
                    name = re.sub(r'^[a-f0-9]{32}_', '', item.name)
                    result.append({'id':file_id(item.name),'name':name,'size':info.st_size,'modified':info.st_mtime,
                                   'path':f'/profile/transfer/{kind}/{item.name}'})
                    if len(result) >= 500: break
        return sorted(result, key=lambda item:item['modified'], reverse=True)

    async def upload(self, name, stream):
        name = checked_name(name)
        stored = name
        total = 0
        with self.directory('incoming') as folder:
            partial = '.'+uuid.uuid4().hex+'.part'
            out = folder.create(partial)
            try:
                with os.fdopen(out, 'wb') as target:
                    async for chunk in stream:
                        total += len(chunk)
                        if total > MAX_UPLOAD:
                            raise ValueError('单个文件最多 100 MB。')
                        target.write(chunk)
                stem, extension = os.path.splitext(name)
                for attempt in range(1,1001):
                    stored = name if attempt == 1 else f'{stem} ({attempt}){extension}'
                    try:
                        # Atomic no-clobber publication; existing names, including
                        # symbolic links, are never followed or overwritten.
                        folder.link(partial, stored)
                        folder.unlink(partial)
                        break
                    except FileExistsError:
                        continue
                else:
                    raise ValueError('同名文件过多，请改名后重试。')
            except BaseException:
                folder.unlink(partial)
                raise
        return {'id':file_id(stored),'name':stored,'size':total,'path':'/profile/transfer/incoming/'+stored}

    def read(self, kind, identity):
        name = file_name(identity)
        if re.fullmatch(r'\.[a-f0-9]{32}\.part', name) or (kind == 'downloads' and (name.startswith('.') or name.lower().endswith(('.part','.tmp','.crdownload')))):
            raise ValueError('文件尚未下载完成。')
        with self.directory(kind) as folder:
            try:
                source = folder.open_file(name)
                info = os.fstat(source)
                if not stat.S_ISREG(info.st_mode):
                    os.close(source)
                    raise ValueError('只能下载普通文件。')
            except OSError as exc:
                raise ValueError('文件不存在或暂时无法读取。') from exc
        display = re.sub(r'^[a-f0-9]{32}_', '', name)
        return source, info.st_size, "attachment; filename*=UTF-8''"+quote(display, safe='')
