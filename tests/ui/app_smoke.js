// Runs inside the app's WKWebView via BROWSER_WORKBENCH_UI_TEST (see run_app_smoke.sh).
// The body is an async function with the page's globals (state, api, openBrowser…) in scope.
// __FIXTURE__ is replaced by the harness with http://host.docker.internal:PORT.
const steps = [];
const step = (name, ok, detail = '') => { steps.push({name, ok: !!ok, detail: String(detail).slice(0, 400)}); return !!ok; };
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const bridge = (type, data = {}) => window.webkit.messageHandlers.workbench.postMessage({type, ...data});
const snap = name => bridge('test.snapshot', {name}).catch(() => {});
async function until(check, ms, every = 1000) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    try { const value = await check(); if (value) return value; } catch (e) {}
    await sleep(every);
  }
  return null;
}
const phases = [];
let envId = null, clipboardBefore = null;
try {
  step('page runs in app mode with native bridge', native && document.documentElement.classList.contains('native-app'));
  // The page polls on its own; refresh() returns early while that call is in flight.
  await until(async () => { await refresh(); return state.app; }, 30000, 500);
  step('backend reports app version', state.app?.version === '0.7.0' && state.app?.mode === 'desktop', JSON.stringify(state.app));
  await snap('01-start');

  // Docker found and opened, bundled image loaded if missing.
  let shotLoading = false;
  const ready = await until(async () => {
    await refresh();
    const r = state.runtime, label = r.prepare_phase + (r.prepare_progress != null ? ' ' + r.prepare_progress + '%' : '');
    if (phases[phases.length - 1] !== label) phases.push(label);
    if (r.prepare_phase === 'loading_image' && !shotLoading && r.prepare_progress > 20) { shotLoading = true; await snap('02-loading-image'); }
    return r.docker_ready && r.image_ready;
  }, 20 * 60 * 1000, 1500);
  step('runtime ready (Docker + browser image)', ready, JSON.stringify({engine: state.runtime.engine_app, bundled: state.runtime.image_bundled, phases, error: state.runtime.build_error}));
  if (!ready) throw new Error('runtime not ready');
  showDialog('runtimeDialog'); updateRuntime(); await sleep(400); await snap('03-runtime-dialog'); hideDialog('runtimeDialog');

  // What a first-time user without Docker sees (page state only, restored right after;
  // refreshing=true keeps the page's own polling from replacing it meanwhile).
  refreshing = true;
  const realRuntime = state.runtime;
  state.runtime = {...realRuntime, docker_installed: false, docker_ready: false, image_ready: false, build_state: 'error', prepare_phase: 'error', engine_app: null, build_error: '请先安装 Docker Desktop。装好并打开后，工作台会自动继续准备。'};
  updateRuntime(); showDialog('runtimeDialog');
  step('no-Docker guidance renders', !$('runtimeInstall').hidden && $('runtimePrimary').textContent === '下载 Docker Desktop' && $('setupTitle').textContent.includes('Docker Desktop'));
  await sleep(300); await snap('03b-no-docker-guidance');
  hideDialog('runtimeDialog'); state.runtime = realRuntime; updateRuntime(); refreshing = false;

  // NSPasteboard round trip through the bridge.
  clipboardBefore = await native.call('clipboard.read');
  const marker = '境工作台剪贴板 ' + Date.now();
  await native.call('clipboard.writeText', {text: marker});
  step('native clipboard write/read', (await native.call('clipboard.read')).text === marker);

  // A disposable test-mode environment, opened in the app window.
  const env = await api('environments', {method: 'POST', body: {name: 'UI 自测环境', node_id: null, cpu_limit: 1, memory_limit_mb: 1536}});
  envId = env.id;
  await startEnvironment(env.id, true);
  const running = await until(async () => { await refresh(); return state.environments.find(e => e.id === env.id)?.runtime.status === 'running'; }, 240000, 2000);
  step('test environment starts', running);
  if (!activeId) await openBrowser(env.id);
  const connected = await until(() => $('browserFrame').contentDocument?.documentElement.classList.contains('noVNC_connected'), 60000);
  step('remote screen connects in the app window', connected && !$('browserView').hidden);
  await sleep(4000);
  await snap('04-environment-view');

  // Paste: text put on the Mac clipboard reaches a focused textarea inside Firefox.
  await browserAction('navigate', {url: '__FIXTURE__/'});
  await sleep(5000);
  const pasted = 'UI 粘贴测试：中文 English ✓ ' + Date.now();
  await native.call('clipboard.writeText', {text: pasted});
  $('pasteFromComputer').click();
  await sleep(4000);
  await snap('05-after-paste');
  steps.push({name: 'paste marker', ok: true, detail: pasted});

  // Copy back: the page selects its textarea on input; ⌘C path goes noVNC → X11 clipboard → Mac.
  await native.call('clipboard.writeText', {text: 'placeholder'});
  copyFromEnvironment();
  const copied = await until(async () => { const t = (await native.call('clipboard.read')).text; return t !== 'placeholder' && t; }, 15000);
  step('copy from environment reaches the Mac clipboard', copied === pasted, copied || 'nothing copied');

  // Drag a file onto the remote screen (synthetic drop on the noVNC page).
  const frameDoc = $('browserFrame').contentDocument;
  let transfer = null;
  try {
    transfer = new DataTransfer();
    transfer.items.add(new File(['拖入测试内容'], '拖入测试.txt', {type: 'text/plain'}));
  } catch (error) { transfer = null; }
  if (!transfer || transfer.files.length !== 1) {
    steps.push({name: 'file drop on the screen', ok: null, detail: 'skipped: this WebKit cannot build a synthetic DataTransfer'});
  } else {
    const target = frameDoc.querySelector('#noVNC_container') || frameDoc.body;
    target.dispatchEvent(new DragEvent('dragover', {dataTransfer: transfer, bubbles: true, cancelable: true}));
    target.dispatchEvent(new DragEvent('drop', {dataTransfer: transfer, bubbles: true, cancelable: true}));
    const dropped = await until(async () => (await api(`environments/${env.id}/files`)).incoming.some(f => f.name === '拖入测试.txt'), 15000);
    step('file dropped on the screen lands in 电脑传入文件 (synthetic drop event)', dropped);
  }
  if ($('filesDialog').open) { await sleep(800); await snap('06-transfers-after-drop'); hideDialog('filesDialog'); }

  // Download: Firefox saves an attachment, then “下载到电脑” goes through WKDownload.
  await browserAction('navigate', {url: '__FIXTURE__/download'});
  const inEnv = await until(async () => (await api(`environments/${env.id}/files`)).downloads.find(f => f.name === '下载测试.txt'), 30000);
  step('browser download appears in 环境下载文件', inEnv);
  await showTransfers();
  await sleep(1000);
  await snap('07-transfers');
  const saved = new Promise(resolve => window.addEventListener('workbench-native-download', e => resolve(e.detail), {once: true}));
  document.querySelector('#downloadFiles a[download]')?.click();
  const detail = await Promise.race([saved, sleep(20000).then(() => null)]);
  step('下载到电脑 saves through the app', detail?.ok && detail?.name === '下载测试.txt', JSON.stringify(detail));
  await sleep(500);
  await snap('08-download-toast');
  hideDialog('filesDialog');
} catch (error) {
  step('test aborted', false, error?.message || error);
} finally {
  if (clipboardBefore?.text != null) await native.call('clipboard.writeText', {text: clipboardBefore.text}).catch(() => {});
}
// Leave the environment running: the harness then checks “quit + stop environments”.
setTimeout(() => bridge('test.quit', {stopEnvironments: true}), 2000);
return {steps, phases, envId, passed: steps.filter(s => s.ok === true).length, failed: steps.filter(s => s.ok === false).map(s => s.name)};
