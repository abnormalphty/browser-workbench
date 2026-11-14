// Runs inside the Windows app's WebView2 via BROWSER_WORKBENCH_UI_TEST (see .github/workflows/windows.yml).
// GitHub's Windows machines cannot run Linux containers, so this covers the window, the bridge, the
// bundled Python backend and the no-Docker guidance; environments themselves need a real PC.
// The workflow fills in the folders it installed to; with them the test ends by moving the data folder.
const expected = /*EXPECTED*/null;
const same = (a, b) => String(a).replace(/\\+$/, '').toLowerCase() === String(b).replace(/\\+$/, '').toLowerCase();
let moveTo = null;
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

  // Where things are kept: the places the installer was given, shown in the storage dialog.
  const places = await api('storage');
  step('storage overview names the program, the data and Docker\'s place', places.data_dir && places.install_dir && places.docker?.folder &&
    (!expected || (same(places.data_dir, expected.data + '\\Data') && same(places.install_dir, expected.install) && places.can_move)),
    JSON.stringify({...places, environments: places.environments.length}));
  setPage('information'); await sleep(300);
  step('storage button shown in the Windows app', !$('storageSettings').hidden);
  $('storageSettings').click();
  step('storage dialog lists the places', await until(() => $('storageContent').querySelectorAll('.storage-path').length >= 2, 120000),
    $('storageContent').textContent.slice(0, 300));
  await native.call('test.snapshot', {name: '03-storage'});
  hideDialog('storageDialog'); setPage('environments');

  // 全屏: GitHub's machines cannot run an environment, but the view and its button work without one. The click
  // comes through the DevTools input (a real user gesture); the window then fills the screen and comes back.
  $('browserView').hidden = false;
  await sleep(500);
  const button = $('fullscreenBrowser').getBoundingClientRect();
  await native.call('test.click', {x: button.left + button.width / 2, y: button.top + button.height / 2});
  const full = await until(async () => fullscreenElement() && (await native.call('test.window')).borderless, 10000);
  const win = await native.call('test.window');
  step('全屏 fills the screen with the environment picture', full && win.bounds.join() === win.screen.join(), JSON.stringify(win));
  await native.call('test.snapshot', {name: '04-fullscreen'});
  await leaveFullscreen();
  const back = await until(async () => !fullscreenElement() && !(await native.call('test.window')).borderless, 10000);
  step('leaving 全屏 restores the window', back, JSON.stringify(await native.call('test.window')));
  $('browserView').hidden = true;

  // 模型网关: its own server in the packaged backend, on 127.0.0.1.
  setPage('gateway');
  const page = await until(() => typeof gateway !== 'undefined' && gateway && $('gatewayAddress').textContent === gateway.address && gateway, 10000);
  step('模型网关 page loads', page, JSON.stringify(page && {address: page.address}));
  const on = await api('gateway/settings', {method: 'PATCH', body: {enabled: true}});
  step('模型网关 server starts in the packaged backend', on.running && !on.error, JSON.stringify({running: on.running, error: on.error}));
  await loadGateway(); await sleep(400);
  await native.call('test.snapshot', {name: '05-gateway'});
  // The SDK inside the packaged Python: a key checked through a proxy where nothing listens, so nothing leaves
  // this computer and the key is kept as not yet verified.
  await api('gateway/settings', {method: 'PATCH', body: {proxy: '127.0.0.1:9'}});
  const added = await api('gateway/keys', {method: 'POST', body: {name: '自测', secret: 'sk-ant-api03-' + 'x'.repeat(40)}});
  step('模型网关: the bundled Anthropic SDK checks a key (here through a proxy that refuses)', added.keys[0]?.status === 'unreachable' &&
    added.notice?.includes('暂时没能验证'), JSON.stringify({notice: added.notice, keys: added.keys}));
  const off = await api('gateway/settings', {method: 'PATCH', body: {enabled: false}});
  step('模型网关 stops when switched off', !off.running, JSON.stringify({running: off.running}));
  setPage('environments');
  if (expected?.moveTo) {
    const target = await api('storage/check', {method: 'POST', body: {path: expected.moveTo}});
    step('the new place is checked before moving', same(target.data_dir, expected.moveTo + '\\Data'), JSON.stringify(target));
    moveTo = target.root;
  }

  // The one administrator step of the Docker Desktop setup (Virtual Machine Platform and WSL). GitHub's
  // machines grant it without a prompt; Docker Desktop itself is never installed here.
  const began = Date.now();
  const wsl = await Promise.race([native.call('setup.enableWsl'), sleep(9 * 60000).then(() => ({timeout: true}))]);
  step('WSL step runs Windows tools elevated and reports back', wsl && wsl.ok === true && Number.isInteger(wsl.code),
    JSON.stringify({...wsl, seconds: Math.round((Date.now() - began) / 1000)}));
} catch (error) {
  step('test aborted', false, error?.message || error);
}
// Moving stops the backend and reopens the workbench from the new place; the window then reports and quits.
if (moveTo) setTimeout(() => native.call('storage.move', {target: moveTo}), 1500);
else setTimeout(() => native.call('test.quit', {stopEnvironments: false}), 1000);
return {steps, passed: steps.filter(s => s.ok).length, failed: steps.filter(s => !s.ok).map(s => s.name)};
