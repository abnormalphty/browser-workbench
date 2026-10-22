"""Ordinary Firefox desktop, without a browser automation/debugging connection."""
import asyncio
import json
from pathlib import Path
import subprocess


def firefox_preferences(test_mode):
    prefs = {
        'browser.shell.checkDefaultBrowser': False,
        'intl.locale.requested': 'zh-CN',
        'browser.startup.page': 0,
        'browser.startup.homepage': 'about:blank',
        'browser.sessionstore.resume_from_crash': False,
        'browser.newtabpage.enabled': False,
        'browser.aboutwelcome.enabled': False,
        'browser.startup.homepage_override.mstone': 'ignore',
        'datareporting.policy.firstRunURL': '',
        'browser.tabs.warnOnClose': False,
        'media.peerconnection.enabled': False,
        'browser.download.dir': '/profile/transfer/downloads',
        'browser.download.folderList': 2,
        'browser.download.useDownloadDir': True,
        'network.proxy.type': 0 if test_mode else 1,
        'network.proxy.failover_direct': False,
        'network.trr.mode': 5,
    }
    if not test_mode:
        prefs.update({
            'network.proxy.http': '127.0.0.1', 'network.proxy.http_port': 7890,
            'network.proxy.ssl': '127.0.0.1', 'network.proxy.ssl_port': 7890,
            'network.proxy.no_proxies_on': '',
            'network.proxy.allow_hijacking_localhost': True,
        })
    return prefs


class NativeFirefox:
    def __init__(self, test_mode):
        self.test_mode = test_mode
        self.process = None
        self.window = None
        self.lock = asyncio.Lock()

    @staticmethod
    def command(*args, text=None, timeout=4):
        result = subprocess.run(args, input=text, capture_output=True, text=True, timeout=timeout, check=True)
        return result.stdout.strip()

    async def start(self):
        profile = Path('/profile/firefox-standard')
        profile.mkdir(mode=0o700, exist_ok=True)
        prefs = firefox_preferences(self.test_mode)
        (profile/'user.js').write_text('\n'.join(f'user_pref({json.dumps(k)}, {json.dumps(v)});' for k,v in prefs.items()))
        initial = 'file:///app/welcome.html' if self.test_mode else 'https://claude.ai/'
        self.process = subprocess.Popen(
            ['firefox-esr', '--no-remote', '--profile', str(profile), '--width', '1440', '--height', '900', 'about:blank'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for _ in range(150):
            if self.process.poll() is not None:
                raise RuntimeError('Firefox exited during startup')
            try:
                windows = await asyncio.to_thread(self.command, 'xdotool', 'search', '--onlyvisible', '--class', 'firefox')
                if windows:
                    self.window = windows.splitlines()[-1]
                    await asyncio.to_thread(self.command, 'wmctrl', '-i', '-r', self.window, '-b', 'add,maximized_vert,maximized_horz')
                    await self.action('navigate', {'url': initial})
                    # Wait for the initial navigation to leave the blank window,
                    # so the next user navigation does not race first startup.
                    for _ in range(50):
                        title = await asyncio.to_thread(self.command, 'xdotool', 'getwindowname', self.window)
                        if title.strip() not in ('Mozilla Firefox', 'Mozilla Firefox ESR', ''):
                            break
                        await asyncio.sleep(.1)
                    return
            except subprocess.CalledProcessError:
                pass
            await asyncio.sleep(.1)
        raise RuntimeError('Firefox window did not appear')

    async def stop(self):
        if self.process and self.process.poll() is None:
            try:
                # WM_DELETE_WINDOW gives Firefox its normal profile flush path.
                # SIGTERM can leave asynchronous localStorage writes behind.
                windows = await asyncio.to_thread(self.command, 'xdotool', 'search', '--onlyvisible', '--class', 'firefox')
                for window in windows.splitlines():
                    try:
                        await asyncio.to_thread(self.command, 'wmctrl', '-i', '-c', window)
                    except subprocess.CalledProcessError:
                        # Closing another window may already have closed this one.
                        pass
                await asyncio.to_thread(self.process.wait, timeout=6)
            except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
                self.process.terminate()
                try:
                    await asyncio.to_thread(self.process.wait, timeout=1)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    await asyncio.to_thread(self.process.wait)

    def _paste(self, text):
        from desktop_clipboard import paste_text
        paste_text(text)

    def _action(self, kind, data):
        self.command('xdotool', 'windowactivate', '--sync', self.window)
        if kind == 'navigate':
            self.command('xdotool', 'key', '--clearmodifiers', 'ctrl+l')
            self._paste(data['url'])
            self.command('xdotool', 'key', '--clearmodifiers', 'Return')
        elif kind in ('text', 'paste'):
            self._paste(data.get('text', ''))
        elif kind == 'paste_image':
            from desktop_clipboard import paste_image
            paste_image(data.get('name'))
        elif kind == 'copy':
            # Clear the remote clipboard so a failed copy cannot return old data.
            with subprocess.Popen(['xclip', '-selection', 'clipboard', '-in'], stdin=subprocess.PIPE,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True) as process:
                process.communicate('', timeout=3)
            self.command('xdotool', 'key', '--clearmodifiers', 'ctrl+c')
            try:
                return {'ok': True, 'text': self.command('xclip', '-selection', 'clipboard', '-out')[:20000]}
            except subprocess.CalledProcessError:
                return {'ok': True, 'text': ''}
        else:
            key = {'back': 'alt+Left', 'forward': 'alt+Right', 'reload': 'ctrl+r', 'new_tab': 'ctrl+t'}[kind]
            self.command('xdotool', 'key', '--clearmodifiers', key)
        # Navigation is driven by the native GUI; this is not an HTTP result.
        return {'ok': True, 'url': ''}

    async def action(self, kind, data):
        async with self.lock:
            return await asyncio.to_thread(self._action, kind, data)
