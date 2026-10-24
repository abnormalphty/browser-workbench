"""Find a Docker-compatible engine even when started from a Mac app.

Apps opened from Finder get PATH=/usr/bin:/bin:/usr/sbin:/sbin, so the docker
CLI and its credential helpers are invisible unless we look for them.
"""
from functools import lru_cache
import os
import shutil
import subprocess
from pathlib import Path

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
EXTRA_PATH = ('/usr/local/bin', '/opt/homebrew/bin', str(HOME/'.docker/bin'),
              '/Applications/Docker.app/Contents/Resources/bin', str(HOME/'.orbstack/bin'))


def find_cli():
    found = shutil.which('docker')
    if found:
        return found
    for candidate in CLI_CANDIDATES:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def engine_app():
    for name, path in ENGINE_APPS:
        if Path(path).is_dir():
            return {'name': name, 'path': path}
    return None


def command_env(cli):
    """PATH for docker subprocesses: credential helpers live beside the CLI."""
    env = dict(os.environ)
    parts = [str(Path(cli).parent)] if cli else []
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
    return 'https://desktop.docker.com/mac/main/' + ('arm64' if apple_silicon() else 'amd64') + '/Docker.dmg'
