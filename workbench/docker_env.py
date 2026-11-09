"""Find a Docker-compatible engine even when started from a desktop app.

Apps opened from Finder get PATH=/usr/bin:/bin:/usr/sbin:/sbin, so the docker
CLI and its credential helpers are invisible unless we look for them. On
Windows, Docker Desktop's PATH entry only reaches processes started after the
installation, so its install folders are checked as well: per user (the
installer's default since Docker Desktop 4.83, no administrator rights), for all
users, or wherever its uninstall entry says.
"""
from functools import lru_cache
import json
import os
import shutil
import subprocess
from pathlib import Path

from .system import windows

HOME = Path.home()
CLI_CANDIDATES = (
    '/usr/local/bin/docker',
    '/opt/homebrew/bin/docker',
    str(HOME/'.docker/bin/docker'),
    '/Applications/Docker.app/Contents/Resources/bin/docker',
    str(HOME/'Applications/Docker.app/Contents/Resources/bin/docker'),
    str(HOME/'.orbstack/bin/docker'),
    '/Applications/OrbStack.app/Contents/MacOS/xbin/docker',
)
# Engines the workbench may open for the user; anything else must already run.
ENGINE_APPS = (
    ('Docker Desktop', '/Applications/Docker.app'),
    ('Docker Desktop', str(HOME/'Applications/Docker.app')),
    ('OrbStack', '/Applications/OrbStack.app'),
    ('OrbStack', str(HOME/'Applications/OrbStack.app')),
)
PROGRAM_FILES = Path(os.environ.get('ProgramFiles', r'C:\Program Files'))
LOCAL_APP_DATA = Path(os.environ.get('LOCALAPPDATA', str(HOME/'AppData'/'Local')))
APP_DATA = Path(os.environ.get('APPDATA', str(HOME/'AppData'/'Roaming')))
# Docker Desktop's own settings on Windows: settings-store.json since 4.35, settings.json before.
DESKTOP_SETTINGS = (APP_DATA/'Docker'/'settings-store.json', APP_DATA/'Docker'/'settings.json')
# Docker Desktop installed for this user only, then for all users.
WINDOWS_ROOTS = (LOCAL_APP_DATA/'Programs'/'DockerDesktop', PROGRAM_FILES/'Docker'/'Docker')
UNINSTALL_KEY = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\Docker Desktop'
EXTRA_PATH = ('/usr/local/bin', '/opt/homebrew/bin', str(HOME/'.docker/bin'),
              '/Applications/Docker.app/Contents/Resources/bin', str(HOME/'.orbstack/bin'))


def windows_roots():
    """Docker Desktop's folders on Windows: a custom one from its uninstall entry first, then the defaults."""
    found = []
    try:
        import winreg
    except ImportError:
        winreg = None
    if winreg:
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive, UNINSTALL_KEY) as key:
                    location = winreg.QueryValueEx(key, 'InstallLocation')[0]
            except OSError:
                continue
            if isinstance(location, str) and location.strip(' "'):
                found.append(Path(location.strip(' "')))
    return list(dict.fromkeys([*found, *WINDOWS_ROOTS]))


def desktop_settings():
    """Docker Desktop's settings on Windows, with keys in lower case (their spelling changed over versions)."""
    for path in DESKTOP_SETTINGS:
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            return {str(key).lower(): value for key, value in data.items()}
    return {}


def uses_wsl():
    """False only where Docker Desktop is set to its Hyper-V engine, which does not run on WSL 2."""
    return desktop_settings().get('wslengineenabled') is not False


def wsl_data_dir():
    """Where Docker Desktop keeps its Linux disk with the WSL 2 engine: every image, container and volume,
    so the browser image and each environment's login data. Changed in Docker Desktop's settings
    (Resources > Advanced) or at installation (--wsl-default-data-root)."""
    custom = desktop_settings().get('customwsldistrodir')
    if isinstance(custom, str) and custom.strip():
        return Path(custom.strip())
    return LOCAL_APP_DATA/'Docker'/'wsl'


def find_cli():
    found = shutil.which('docker')
    if found:
        return found
    candidates = [str(root/'resources'/'bin'/'docker.exe') for root in windows_roots()] if windows() else CLI_CANDIDATES
    for candidate in candidates:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def engine_app():
    if windows():
        return next(({'name': 'Docker Desktop', 'path': str(root/'Docker Desktop.exe')}
                     for root in windows_roots() if (root/'Docker Desktop.exe').is_file()), None)
    for name, path in ENGINE_APPS:
        if Path(path).is_dir():
            return {'name': name, 'path': path}
    return None


def command_env(cli):
    """PATH for docker subprocesses: credential helpers live beside the CLI."""
    env = dict(os.environ)
    parts = [str(Path(cli).parent)] if cli else []
    if windows():
        env['PATH'] = os.pathsep.join(dict.fromkeys(p for p in parts + env.get('PATH', '').split(os.pathsep) if p))
        return env
    parts += [*EXTRA_PATH, *env.get('PATH', '/usr/bin:/bin:/usr/sbin:/sbin').split(':')]
    env['PATH'] = ':'.join(dict.fromkeys(p for p in parts if p))
    return env


@lru_cache(maxsize=1)
def apple_silicon():
    # platform.machine() reports x86_64 inside Rosetta; ask the hardware.
    try:
        result = subprocess.run(['sysctl', '-n', 'hw.optional.arm64'], capture_output=True, text=True, timeout=2)
        return result.stdout.strip() == '1'
    except (OSError, subprocess.SubprocessError):
        return False


def download_url():
    if windows():
        # The browser image is built for x64 Windows PCs.
        return 'https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe'
    return 'https://desktop.docker.com/mac/main/' + ('arm64' if apple_silicon() else 'amd64') + '/Docker.dmg'
