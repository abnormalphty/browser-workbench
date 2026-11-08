// Runs inside the Windows app's WebView2 via BROWSER_WORKBENCH_UI_TEST (see .github/workflows/windows.yml).
// GitHub's Windows machines cannot run Linux containers, so this covers the window, the bridge, the
// bundled Python backend and the no-Docker guidance; environments themselves need a real PC.
const steps = [];
const step = (name, ok, detail = '') => { steps.push({name, ok: !!ok, detail: String(detail).slice(0, 400)}); return !!ok; };
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(check, ms, every = 500) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    try { const value = await check(); if (value) return value; } catch (e) {}
    await sleep(every);
  }
  return null;
}
try {
  step('page runs in the Windows app with the native bridge', native && document.documentElement.classList.contains('native-win') && window.workbenchNative?.platform === 'windows');
  await until(async () => { await refresh(); return state.app; }, 60000);
  step('bundled Python backend answers with the app version', state.app?.version === window.workbenchNative.version && state.app?.platform === 'win32', JSON.stringify(state.app));
  step('no Mac title band; Windows wording', document.querySelector('.brand').getBoundingClientRect().top < 40 &&
    $('runtimeInstall').textContent.includes('Docker Desktop Installer.exe') && document.querySelector('[data-open-transfer]').textContent.includes('资源管理器'));
  await native.call('test.snapshot', {name: '01-start'});

  const marker = 'Windows 剪贴板 ' + Date.now();
  await native.call('clipboard.writeText', {text: marker});
  step('clipboard round trip through the bridge', (await native.call('clipboard.read')).text === marker);
  let refused = false;
  try { await native.call('revealFile', {path: 'C:\\Windows\\win.ini'}); } catch (error) { refused = true; }
  step('bridge refuses to reveal files the app did not save', refused);

  const runtime = await until(async () => { await refresh(); return state.runtime.build_state === 'error' && state.runtime; }, 120000);
  if (runtime && runtime.docker_os === 'windows') {
    // GitHub's Windows machines come with Docker's Windows-container engine, which cannot run the Linux image.
    step('Docker in Windows-container mode: the app asks to switch to Linux containers',
      (runtime.build_error || '').includes('Switch to Linux containers'), JSON.stringify(runtime));
  } else if (runtime && runtime.docker_installed) {
    step('Docker present but not usable: the app explains what to do', !!runtime.build_error, JSON.stringify(runtime));
  } else {
    step('without Docker the backend asks to install Docker Desktop', runtime && !runtime.docker_installed &&
      runtime.docker_download_url.startsWith('https://desktop.docker.com/win/'), JSON.stringify(runtime || state.runtime));
  }
  showDialog('runtimeDialog'); updateRuntime(); await sleep(500);
  await native.call('test.snapshot', {name: '02-docker-guidance'});
  hideDialog('runtimeDialog');

  // The one administrator step of the Docker Desktop setup (Virtual Machine Platform and WSL). GitHub's
  // machines grant it without a prompt; Docker Desktop itself is never installed here.
  const began = Date.now();
  const wsl = await Promise.race([native.call('setup.enableWsl'), sleep(9 * 60000).then(() => ({timeout: true}))]);
  step('WSL step runs Windows tools elevated and reports back', wsl && wsl.ok === true && Number.isInteger(wsl.code),
    JSON.stringify({...wsl, seconds: Math.round((Date.now() - began) / 1000)}));
} catch (error) {
  step('test aborted', false, error?.message || error);
}
setTimeout(() => native.call('test.quit', {stopEnvironments: false}), 1000);
return {steps, passed: steps.filter(s => s.ok).length, failed: steps.filter(s => !s.ok).map(s => s.name)};
