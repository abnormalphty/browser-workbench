"""Docker Desktop setup against real Windows (run by .github/workflows/windows.yml): the system check,
the signature check, the restart entry, and the real installer downloaded and verified. Docker Desktop
itself is not installed here: GitHub's Windows Server machines cannot run it, and its terms are for the
user to accept in the app."""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from workbench import docker_env, docker_setup  # noqa: E402

failures = []


def check(name, ok, detail=''):
    print(('ok    ' if ok else 'FAIL  ') + name + (f'  {detail}' if detail else ''), flush=True)
    if not ok:
        failures.append(name)


info = docker_setup.check_system()
check('system check answers', isinstance(info['build'], int) and info['virtualization'] in (True, False) and info['vmp'] in (True, False, None),
      json.dumps(info))
booted = docker_setup.booted_at()
check('boot time is in the past', booted is not None and time.time() - 90 * 86400 < booted < time.time(), str(booted))
check('Docker Desktop folders', [root.parts[-1] for root in docker_env.windows_roots()][-2:] == ['DockerDesktop', 'Docker'],
      ', '.join(str(root) for root in docker_env.windows_roots()))

system32 = Path(os.environ['SystemRoot']) / 'System32'
check('a Microsoft-signed program is not taken for Docker', not docker_setup.verify(system32 / 'notepad.exe'))
with tempfile.TemporaryDirectory() as folder:
    fake = Path(folder) / 'Docker Desktop Installer.exe'
    fake.write_bytes(b'MZ not really a program')
    check('an unsigned file is refused', not docker_setup.verify(fake))

    app = Path(folder) / 'BrowserWorkbench.exe'
    app.write_bytes(b'')
    os.environ['WORKBENCH_APP_EXE'] = str(app)
    import winreg
    docker_setup.resume_after_restart()
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, docker_setup.RUN_ONCE) as key:
        value = winreg.QueryValueEx(key, docker_setup.RUN_ONCE_NAME)[0]
    check('reopens after the restart', value == f'"{app}"', value)
    docker_setup.forget_restart()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, docker_setup.RUN_ONCE) as key:
            winreg.QueryValueEx(key, docker_setup.RUN_ONCE_NAME)
        gone = False
    except OSError:
        gone = True
    check('the restart entry is removed again', gone)

    setup = docker_setup.DockerSetup(Path(folder) / 'data')
    started = time.monotonic()
    try:
        installer = setup.download()
        size = installer.stat().st_size
        check("Docker's installer downloads and carries Docker Inc's signature", size > 100 * 1024 * 1024,
              f'{size} bytes in {time.monotonic() - started:.0f} s')
    except ValueError as error:
        check("Docker's installer downloads and carries Docker Inc's signature", False, str(error))

print('FAILED: ' + ', '.join(failures) if failures else 'all Docker Desktop setup checks passed')
sys.exit(1 if failures else 0)
