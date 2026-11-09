"""Installs Docker Desktop on Windows for a user who asked for it in the app.

Docker Desktop installs per user without administrator rights (its installer's
default since 4.83). Only the Windows feature WSL 2 runs on, Virtual Machine
Platform, needs an administrator once per computer and then a restart: the app
window asks Windows for that (windows/MainForm.cs, "setup.enableWsl") so the
consent prompt opens in front of it, and this backend only checks the outcome.

The installer comes from Docker's site and runs only with a valid Authenticode
signature by Docker Inc. The user agrees to Docker's terms in the app before
anything is downloaded; the installer is then told so (--accept-license).
"""
import ctypes
import http.client
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .docker_env import LOCAL_APP_DATA
from .storage import docker_data_root, free_space
from .system import quiet, windows

INSTALLER_URL = 'https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe'
INSTALLER = 'Docker Desktop Installer.exe'
TERMS_URL = 'https://www.docker.com/legal/docker-subscription-service-agreement/'
PUBLISHER = 'dockerinc'  # the signer's name in letters only: "Docker Inc" (or "Docker, Inc.")
MIN_BUILD = 19045        # Windows 10 22H2; Windows 11 starts at 22000
MIN_WSL = (2, 1, 5)      # Docker Desktop's requirement
# Free space needed, in GB: the installer (in the data folder), Docker Desktop itself (per user, in
# %LOCALAPPDATA%) and its Linux disk with the browser image (next to the data folder if it was moved).
SPACE_GB = {'installer': 0.5, 'program': 3, 'disk': 2.5}
RUN_ONCE = r'Software\Microsoft\Windows\CurrentVersion\RunOnce'
# Windows' own flag for servicing changes (such as a feature just switched on) that wait for a restart.
REBOOT_PENDING = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending'
RUN_ONCE_NAME = 'BrowserWorkbenchSetup'
PF_VIRT_FIRMWARE_ENABLED = 21

MESSAGES = {
    'windows': 'Docker Desktop 需要 Windows 10 22H2 或 Windows 11 23H2 及以上版本。请先运行 Windows 更新，再点“重新检查”。',
    'virtualization': '这台电脑没有开启 CPU 虚拟化，Docker 无法运行。请重启电脑进入 BIOS/UEFI 设置，开启 Intel VT-x 或 AMD-V（SVM），'
                      '保存后再打开本应用（虚拟机里则要开启嵌套虚拟化）。',
    'wsl': '还差一步：开启 Windows 的 WSL 2。需要管理员授权一次，之后通常要重启电脑。',
    'restart': 'WSL 2 已开启，重启电脑后生效。重启后 Browser Workbench 会自动打开并继续。',
    'hypervisor': 'Windows 的“虚拟机平台”已经开启，但还没有运行，Docker 无法启动。请先重启一次电脑。'
                  '如果重启后仍然这样，可能是其他软件（例如部分安卓模拟器）关掉了 Windows 的虚拟化：'
                  '以管理员身份打开命令提示符，运行 bcdedit /set hypervisorlaunchtype auto，再重启电脑。',
}

# One PowerShell call answers everything: virtualization (a running hypervisor hides the firmware flag),
# Virtual Machine Platform (InstallState 1 = enabled) and the WSL version (WSL 2.x lives in Program Files).
SYSTEM_SCRIPT = ';'.join([
    "$ErrorActionPreference='Stop'", "$ProgressPreference='SilentlyContinue'",
    '$c=Get-CimInstance -ClassName Win32_ComputerSystem',
    '$p=@(Get-CimInstance -ClassName Win32_Processor)[0]',
    "$f=Get-CimInstance -ClassName Win32_OptionalFeature -Filter \"Name='VirtualMachinePlatform'\"",
    "$w=Join-Path $env:ProgramFiles 'WSL\\wsl.exe'",
    '@{hypervisor=[bool]$c.HypervisorPresent;firmware=[bool]$p.VirtualizationFirmwareEnabled;'
    'vmp=$(if($f){[int]$f.InstallState}else{0});'
    'wsl=$(if(Test-Path -LiteralPath $w){[string](Get-Item -LiteralPath $w).VersionInfo.ProductVersion}else{\'\'})}'
    '|ConvertTo-Json -Compress',
])
VERIFY_SCRIPT = ';'.join([
    "$ErrorActionPreference='Stop'",
    '$s=Get-AuthenticodeSignature -LiteralPath $env:WORKBENCH_SIGNED_FILE',
    "@{status=[string]$s.Status;subject=$(if($s.SignerCertificate){[string]$s.SignerCertificate.Subject}else{''})}"
    '|ConvertTo-Json -Compress',
])


class SetupBlocked(ValueError):
    """Setup waits for something only the user can do; the message says what."""

    def __init__(self, step):
        super().__init__(MESSAGES[step])
        self.step = step


def log(message):
    # The app window writes this process's output to Logs\backend.log, so a setup on someone else's PC can be traced.
    print('[docker-setup] ' + message, file=sys.stderr, flush=True)


def powershell(script, extra_env=None, timeout=60):
    """Runs one of the fixed scripts above, which print a JSON object; values reach it through the environment."""
    exe = Path(os.environ.get('SystemRoot', r'C:\Windows'))/'System32'/'WindowsPowerShell'/'v1.0'/'powershell.exe'
    # A PSModulePath inherited from PowerShell 7 makes Windows PowerShell load PowerShell 7's modules, which
    # it cannot (Get-AuthenticodeSignature goes missing); without it, Windows PowerShell uses its own.
    env = {key: value for key, value in os.environ.items() if key.upper() != 'PSMODULEPATH'}
    result = subprocess.run([str(exe), '-NoLogo', '-NoProfile', '-NonInteractive', '-Command', script],
                            capture_output=True, stdin=subprocess.DEVNULL, timeout=timeout,
                            env={**env, **(extra_env or {})}, **quiet())
    if result.returncode:
        raise OSError(result.stderr.decode('utf-8', 'replace').strip()[-300:])
    return json.loads(result.stdout.decode('utf-8', 'replace').strip() or '{}')


def processor_feature(feature):
    try:
        return bool(ctypes.windll.kernel32.IsProcessorFeaturePresent(feature))
    except (AttributeError, OSError):
        return False


def reboot_pending():
    """True while Windows waits for a restart to finish a change, None if it cannot be read."""
    if not windows():
        return None
    try:
        import winreg
    except ImportError:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, REBOOT_PENDING):
            return True
    except FileNotFoundError:
        return False
    except OSError:
        return None


def check_system():
    """What Docker Desktop needs from this PC; None where Windows could not tell."""
    info = {'build': None, 'virtualization': None, 'vmp': None, 'hypervisor': None, 'reboot_pending': None, 'wsl': None}
    if not windows():
        return info
    info['build'] = sys.getwindowsversion().build
    info['reboot_pending'] = reboot_pending()
    try:
        found = powershell(SYSTEM_SCRIPT, timeout=90)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        log(f'system check failed: {str(exc)[:200]}')
        return info
    firmware = bool(found.get('firmware')) or processor_feature(PF_VIRT_FIRMWARE_ENABLED)
    # A running hypervisor: what Virtual Machine Platform starts at boot (Hyper-V and memory integrity do too).
    info['hypervisor'] = bool(found.get('hypervisor'))
    info['virtualization'] = info['hypervisor'] or firmware
    state = found.get('vmp')
    info['vmp'] = True if state == 1 else False if state in (2, 3) else None
    info['wsl'] = found.get('wsl') or None
    return info


def wsl_ready(version):
    numbers = re.findall(r'\d+', version or '')
    return len(numbers) >= 3 and tuple(int(n) for n in numbers[:3]) >= MIN_WSL


def blocker(system, wsl_requested_at=None, booted_at=None, installed=False):
    """The first thing the user must do before Docker Desktop can install and run, or None. For a Docker
    Desktop already installed, only what keeps it from starting at all: it updates WSL itself."""
    if system.get('build') and system['build'] < MIN_BUILD:
        return 'windows'
    if system.get('virtualization') is False:
        return 'virtualization'
    since_boot = bool(wsl_requested_at) and booted_at is not None and wsl_requested_at > booted_at
    vmp, hypervisor, pending = system.get('vmp'), system.get('hypervisor'), system.get('reboot_pending')
    if vmp is False:
        # Switching it on takes effect after a restart; a request from before the last start did not work.
        return 'restart' if since_boot else 'wsl'
    if since_boot and (vmp is None or pending or hypervisor is False):
        # Switched on in this Windows session: Windows may already list it as on, but it only runs after
        # the restart. Going on would leave Docker Desktop at "Virtual Machine Platform is not enabled".
        return 'restart'
    if vmp is True and hypervisor is False:
        # On but not running: the restart is still due, or something keeps Windows' hypervisor off.
        return 'restart' if pending else 'hypervisor'
    if vmp is True and not installed and not wsl_ready(system.get('wsl')) and not wsl_requested_at:
        # Tried once; if WSL still is not current, Docker Desktop offers to update it when it starts.
        # Where Windows could not tell at all, the installer itself refuses a missing platform (install()).
        return 'wsl'
    return None


def booted_at():
    """When Windows last started, as a Unix time."""
    if not windows():
        return None
    kernel32 = ctypes.windll.kernel32
    kernel32.GetTickCount64.restype = ctypes.c_ulonglong
    return time.time() - kernel32.GetTickCount64() / 1000


def signer_name(subject):
    match = re.search(r'(?:^|,)\s*CN=(?:"([^"]*)"|([^,]*))', subject or '')
    return (match.group(1) or match.group(2) or '').strip() if match else ''


def verify(path):
    """True only for a file carrying a valid Authenticode signature by Docker Inc."""
    if not windows():
        return False
    try:
        result = powershell(VERIFY_SCRIPT, {'WORKBENCH_SIGNED_FILE': str(path)}, timeout=300)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        log(f'signature check did not run: {str(exc)[:200]}')
        return False
    name = signer_name(result.get('subject'))
    log(f"signature {result.get('status')}, signed by {name or 'nobody'}")
    return result.get('status') == 'Valid' and re.sub(r'[^a-z]', '', name.lower()) == PUBLISHER


def content_total(headers, offset):
    """The whole file's size from a full (200) or partial (206) response."""
    match = re.search(r'/(\d+)\s*$', headers.get('Content-Range') or '')
    if match:
        return int(match.group(1))
    length = headers.get('Content-Length') or ''
    return offset + int(length) if length.isdigit() else None


def installer_log():
    """The end of Docker's own installer log, newest first found, for build.log."""
    folders = [(os.environ.get('LOCALAPPDATA'), 'Docker'), (os.environ.get('ProgramData'), 'DockerDesktop')]
    logs = [path for base, name in folders if base for path in (Path(base) / name).glob('install-log*.txt')]
    if not logs:
        return ''
    try:
        return max(logs, key=lambda path: path.stat().st_mtime).read_text(encoding='utf-8', errors='replace')[-6000:]
    except OSError:
        return ''


def resume_after_restart():
    """Opens the app once after the next sign-in, so the setup goes on by itself after the restart."""
    exe = os.environ.get('WORKBENCH_APP_EXE') or ''
    if not windows() or not exe.lower().endswith('.exe') or not os.path.isfile(exe):
        return
    try:
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_ONCE) as key:
            winreg.SetValueEx(key, RUN_ONCE_NAME, 0, winreg.REG_SZ, f'"{exe}"')
    except OSError as exc:
        log(f'could not arrange to reopen after the restart: {exc}')


def forget_restart():
    if not windows():
        return
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_ONCE, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, RUN_ONCE_NAME)
    except OSError:
        pass


def install_command(installer):
    """Per user, no administrator rights, the WSL 2 engine. Its Linux disk, which grows with the browser image and
    each environment's login data, goes next to the data folder when the user put that on another place."""
    command = [str(installer), 'install', '--user', '--quiet', '--accept-license', '--backend=wsl-2']
    disk = docker_data_root()
    if disk:
        command.append(f'--wsl-default-data-root={disk}')
    return command


class DockerSetup:
    """The one-click setup's state: the user's agreement and the WSL request are remembered in the
    data folder, so the setup carries on after the restart WSL needs."""

    def __init__(self, data_dir):
        self.folder = Path(data_dir) / 'setup'
        self.memory = self.folder / 'docker.json'
        self.lock = threading.Lock()
        self.step = None
        self.system = None
        self.checked_at = None
        self.checked_installed = False  # whether that check was for a Docker Desktop already installed
        self.downloaded = 0
        self.total = None

    def _read(self):
        try:
            data = json.loads(self.memory.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, **changes):
        # The page's requests and the setup job both record things here.
        with self.lock:
            self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            temporary = self.memory.with_suffix('.tmp')
            temporary.write_text(json.dumps({**self._read(), **changes}), encoding='utf-8')
            temporary.replace(self.memory)

    def accepted(self):
        """The user asked for this installation and it has not finished: it carries on by itself."""
        return bool(self._read().get('pending'))

    def accept(self):
        # Good for one installation: if Docker Desktop is removed later, the app asks again.
        self._write(pending=True, terms_accepted_at=datetime.now(timezone.utc).isoformat(timespec='seconds'), terms_url=TERMS_URL)

    def wsl_requested(self):
        self._write(wsl_requested_at=time.time())

    def wsl_state(self):
        if self.step in ('wsl', 'restart', 'hypervisor'):
            return self.step
        if self.system is None or self.system.get('vmp') is None:
            return None
        return 'ready' if self.system['vmp'] else 'wsl'

    def status(self):
        return {'terms_accepted': self.accepted(), 'terms_url': TERMS_URL, 'step': self.step,
                'message': MESSAGES.get(self.step), 'wsl': self.wsl_state(),
                'downloaded': self.downloaded, 'total': self.total}

    def fresh(self, seconds=60):
        return self.checked_at is not None and time.monotonic() - self.checked_at < seconds

    def check(self, installed=False):
        """Looks at the PC again; sets and returns the step the user must take, or None."""
        system = check_system()
        self.system, self.checked_at, self.checked_installed = system, time.monotonic(), installed
        self.step = blocker(system, self._read().get('wsl_requested_at'), booted_at(), installed)
        log(f"build {system.get('build')}, virtualization {system.get('virtualization')}, platform {system.get('vmp')}, "
            f"hypervisor {system.get('hypervisor')}, restart pending {system.get('reboot_pending')}, wsl {system.get('wsl')}: "
            f"{self.step or 'nothing to do first'}")
        if self.step in ('restart', 'hypervisor'):
            resume_after_restart()
        return self.step

    def ensure_space(self):
        places = {'installer': self.folder, 'program': LOCAL_APP_DATA, 'disk': docker_data_root() or LOCAL_APP_DATA}
        drives = {}
        for part, place in places.items():
            drive = Path(place).drive.upper()
            needed, where = drives.get(drive, (0, place))
            drives[drive] = (needed + SPACE_GB[part], where)
        for drive, (needed, place) in drives.items():
            free = free_space(place)
            if free is not None and free < needed * 1024 ** 3:
                name = f'{drive} 盘' if drive.endswith(':') else '磁盘'
                raise ValueError(f'{name}空间不够：安装 Docker Desktop 和浏览器组件在这里约需 {needed:g} GB，'
                                 f'现在只剩 {free / 1024 ** 3:.1f} GB。请清理后点“重试”。')

    def download(self, progress=lambda: None):
        """Docker's installer, resumed after interruptions; returns its path once its signature checks out."""
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        target, part = self.folder / INSTALLER, self.folder / (INSTALLER + '.part')
        if target.is_file():
            if verify(target):
                self.downloaded = self.total = target.stat().st_size
                return target
            target.unlink()
        failures = 0
        while True:
            have = part.stat().st_size if part.is_file() else 0
            tag = self._read().get('download_etag')
            headers = {'User-Agent': f'BrowserWorkbench/{__version__}'}
            if have and tag:
                # If-Range: a newer installer published meanwhile comes whole instead of being spliced on.
                headers.update({'Range': f'bytes={have}-', 'If-Range': tag})
            self.downloaded, received = have, 0
            try:
                # urllib uses Windows' proxy settings, like a browser; HTTPS is checked against Windows' certificates.
                with urllib.request.urlopen(urllib.request.Request(INSTALLER_URL, headers=headers), timeout=60) as response:
                    resumed = response.status == 206
                    if not resumed:
                        have = 0
                    self.total = content_total(response.headers, have)
                    self._write(download_etag=response.headers.get('ETag'), download_total=self.total)
                    with part.open('ab' if resumed else 'wb') as output:
                        while chunk := response.read(1 << 20):
                            output.write(chunk)
                            received += len(chunk)
                            self.downloaded = have + received
                            progress()
                if self.total and self.downloaded != self.total:
                    raise OSError('the download ended early')
                break
            except urllib.error.HTTPError as exc:
                if exc.code == 416 and have and have == self._read().get('download_total'):
                    break  # the partial file was already complete
                error = exc
            except (OSError, http.client.HTTPException) as exc:  # timeouts and lost connections included
                error = exc
            failures = 0 if received else failures + 1
            log(f'download interrupted at {self.downloaded} bytes: {type(error).__name__}')
            if failures >= 5:
                raise ValueError('Docker Desktop 安装包下载失败。请检查网络或代理后点“重试”，已下载的部分会保留。') from error
            time.sleep(min(30, 5 * failures + 2))
        part.replace(target)
        if not verify(target):
            target.unlink(missing_ok=True)
            raise ValueError('下载的 Docker Desktop 安装包没有通过签名校验，已删除。请点“重试”重新下载。')
        log(f'downloaded {target.stat().st_size} bytes')
        return target

    def install(self, installer, output):
        """Docker Desktop for this Windows user only: no administrator rights, the WSL 2 engine."""
        if not verify(installer):
            installer.unlink(missing_ok=True)
            raise ValueError('Docker Desktop 安装包没有通过签名校验，已删除。请点“重试”重新下载。')
        log('installing for this user')
        try:
            result = subprocess.run(install_command(installer), stdin=subprocess.DEVNULL, stdout=output,
                                    stderr=subprocess.STDOUT, timeout=1800, **quiet())
        except subprocess.TimeoutExpired as exc:
            raise ValueError('Docker Desktop 安装超时，请点“重试”。') from exc
        except OSError as exc:
            raise ValueError('未能启动 Docker Desktop 安装程序，请点“重试”。') from exc
        log(f'installer finished with code {result.returncode}')
        if result.returncode:
            details = installer_log()
            output.write('\n--- Docker Desktop installer log (end) ---\n' + details + '\n')
            if re.search(r'Virtual ?Machine ?Platform', details, re.IGNORECASE):
                self.step = 'wsl'
                raise SetupBlocked('wsl')
            raise ValueError(f'Docker Desktop 安装没有完成（代码 {result.returncode}）。请点“重试”；详情见数据文件夹里的 build.log。')
        installer.unlink(missing_ok=True)
        forget_restart()
        self._write(pending=False, installed_at=datetime.now(timezone.utc).isoformat(timespec='seconds'))
        self.step = None
