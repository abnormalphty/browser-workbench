#!/usr/bin/env python3
"""Fail the build if anything personal ended up inside the app bundle.

The bundle is assembled from a whitelist; this is the independent second check:
no runtime data file names, and no absolute path of the person building it.
Usage: check_bundle.py PATH.app
"""
import fnmatch
import getpass
from pathlib import Path
import sys

FORBIDDEN_NAMES = ('*.sqlite3', '*.sqlite', '*.sqlite3-*', 'launch.json', 'proxy.yaml', 'server.log', 'build.log',
                   '.workbench.lock', 'cookies.sqlite', 'places.sqlite', 'logins.json', 'key4.db', '.env')
FORBIDDEN_DIRS = ('data', 'environments', 'verification-data', '.venv', '.git', 'transfer', 'firefox-standard')


def main(bundle):
    bundle = Path(bundle)
    home = str(Path.home()).encode()
    user = getpass.getuser().encode()
    problems = []
    for path in bundle.rglob('*'):
        relative = path.relative_to(bundle)
        if path.is_dir() and path.name in FORBIDDEN_DIRS:
            problems.append(f'directory not allowed in bundle: {relative}')
        if not path.is_file() or path.is_symlink():
            continue
        if any(fnmatch.fnmatch(path.name, pattern) for pattern in FORBIDDEN_NAMES):
            problems.append(f'file not allowed in bundle: {relative}')
        if path.suffix == '.gz':
            continue  # the image archive is checked when it is exported
        data = path.read_bytes()
        if home in data or b'/Users/' + user in data:
            problems.append(f'contains a local home path: {relative}')
        if b'PRIVATE KEY-----' in data:
            problems.append(f'contains a private key: {relative}')
    for problem in problems:
        print(problem)
    print(f'privacy check: {"FAILED" if problems else "passed"} ({bundle.name})')
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
