// Design snapshots of every screen, light and dark, inside the real app window.
// Run by tests/ui/run_screens.sh with fake demo data (tests/ui/seed_demo.py).
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const bridge = (type, data = {}) => window.webkit.messageHandlers.workbench.postMessage({type, ...data});
const snap = name => bridge('test.snapshot', {name});
async function until(check, ms, every = 500) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    try { const value = await check(); if (value) return value; } catch (e) {}
    await sleep(every);
  }
  return null;
}
const modes = ['light', 'dark'];
async function both(name, settle = 500) {
  for (const mode of modes) { await bridge('test.appearance', {mode}); await sleep(settle); await snap(`${mode}-${name}`); }
}
await until(async () => { await refresh(); return state.app && state.environments.length && state.runtime.image_ready; }, 60000);
setPage('environments'); await both('01-environments');
setPage('information'); await both('02-information');
setPage('nodes'); await both('03-nodes', 800);
setPage('environments');
newEnvironment(); await both('04-new-environment'); hideDialog('environmentDialog');
showAccount(state.environments[0].id); await both('05-account'); hideDialog('accountDialog');
updateRuntime(); showDialog('runtimeDialog'); await both('06-runtime'); hideDialog('runtimeDialog');

// One running (test-mode) environment for the browser view and the running row.
await bridge('test.appearance', {mode: 'light'});
const spare = state.environments.find(e => !e.node_id);
await startEnvironment(spare.id, true);
const running = await until(async () => { await refresh(); return state.environments.find(e => e.id === spare.id)?.runtime.status === 'running'; }, 240000, 2000);
if (running) {
  if (!activeId) await openBrowser(spare.id);
  await until(() => $('browserFrame').contentDocument?.documentElement.classList.contains('noVNC_connected'), 60000);
  await sleep(5000);
  await both('07-browser', 800);
  await showTransfers(); await both('08-transfers'); hideDialog('filesDialog');
  $('exitBrowser').click(); await sleep(1500); await refresh();
  toast('已保存到“下载”文件夹：示例文件.pdf', false, {label: '在 Finder 中显示', run() {}});
  await both('09-running-list');
}
setTimeout(() => bridge('test.quit', {stopEnvironments: true}), 1500);
return {running: !!running};
