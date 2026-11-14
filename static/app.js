'use strict';
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="workbench-token"]').content;
// Inside the desktop app, clipboard, links and downloads use native code instead of browser
// permission prompts: WKWebView's message handler on the Mac, the WebView2 bridge on Windows.
// In a normal browser this stays null.
const native = !window.workbenchNative ? null : window.webkit?.messageHandlers?.workbench ? {call:(type,data={})=>window.webkit.messageHandlers.workbench.postMessage({type,...data})}
  : window.workbenchBridge ? {call:(type,data={})=>window.workbenchBridge.call(type,data)} : null;
const onWindows = window.workbenchNative?.platform === 'windows' || /Windows/.test(navigator.userAgent);
const keys = onWindows ? {paste:'Ctrl+V'} : {paste:'⌘V'};
const fileManager = onWindows ? '资源管理器' : 'Finder';
if(native)document.documentElement.classList.add('native-app', onWindows ? 'native-win' : 'native-mac');
// The same page runs in the Mac app, the Windows app and a browser: name each system's own tools.
document.querySelectorAll('[data-open-transfer]').forEach(button=>button.textContent=`在 ${fileManager} 中打开 ↗`);
if(onWindows){
  $('runtimeInstall').innerHTML='<li>点下方“下载 Docker Desktop”，运行下载好的 Docker Desktop Installer.exe，按默认选项（只为当前用户安装）完成安装；要求开启 WSL 或重启电脑时按提示操作。</li><li>打开 Docker Desktop，同意它的服务条款；登录和问卷可以跳过。提示安装或更新 WSL、或在 BIOS 里开启虚拟化时，按它的说明操作。</li><li>回到 Browser Workbench：它会自动连上 Docker，并载入自带的浏览器组件。</li>';
  $('dockerGuide').href='https://docs.docker.com/desktop/setup/install/windows-install/';
}
function openExternal(url){if(native)native.call('openExternal',{url}).catch(()=>{});else window.open(url,'_blank','noopener,noreferrer');}
const paths = {
  grid:'<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  globe:'<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c5 5 5 13 0 18-5-5-5-13 0-18Z"/>',
  lock:'<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3m-4 5v2"/>',
  panel:'<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16m5-11 3 3-3 3"/>',
  plus:'<path d="M12 5v14M5 12h14"/>',
  layers:'<path d="m12 3 10 5-10 5L2 8Zm-8 9 8 4 8-4m-16 5 8 4 8-4"/>',
  activity:'<path d="M2 12h5l3-8 4 16 3-8h5"/>',
  search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
  spark:'<path d="m12 2 2.5 7.5L22 12l-7.5 2.5L12 22l-2.5-7.5L2 12l7.5-2.5Z"/>',
  info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10h.01"/>',
  link:'<path d="m10 14 4-4m-6 5-2 2a4 4 0 0 1-6-6l5-5a4 4 0 0 1 6 0m2 3 2-2a4 4 0 0 1 6 6l-5 5a4 4 0 0 1-6 0" transform="translate(1 1) scale(.92)"/>',
  eye:'<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
  refresh:'<path d="M20 7v5h-5M4 17v-5h5m-4-4a8 8 0 0 1 13-3l2 3M4 16l2 3a8 8 0 0 0 13-3"/>',
  close:'<path d="m6 6 12 12M6 18 18 6"/>',
  edit:'<path d="m15 4 5 5M4 20l5-1L21 7a2 2 0 0 0-5-5L4 14Z"/>',
  trash:'<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7"/>',
  back:'<path d="M19 12H5m6-6-6 6 6 6"/>',
  'chevron-left':'<path d="m15 6-6 6 6 6"/>',
  'chevron-right':'<path d="m9 6 6 6-6 6"/>',
  clipboard:'<path d="M9 4H7a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2h-2"/><rect x="9" y="2.5" width="6" height="3.5" rx="1"/>',
  copy:'<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h8"/>',
  files:'<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/><path d="M9 13h6m-2-2 2 2-2 2"/>',
  keyboard:'<rect x="2.5" y="6" width="19" height="12" rx="2"/><path d="M6.5 10h.01m3.5 0h.01m3.5 0h.01m3.5 0h.01M7.5 14h9"/>',
  reconnect:'<path d="M3 12a9 9 0 0 1 15.5-6.3L21 8m0-5v5h-5m5 4a9 9 0 0 1-15.5 6.3L3 16m0 5v-5h5"/>',
  sliders:'<path d="M4 6h10m4 0h2M4 12h4m4 0h8M4 18h12"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
  folder:'<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/>',
  expand:'<path d="M4 9V4h5m6 0h5v5m0 6v5h-5m-6 0H4v-5"/>',
  collapse:'<path d="M9 4v5H4m16 0h-5V4m0 16v-5h5M4 15h5v5"/>',
  terminal:'<rect x="2.5" y="4" width="19" height="16" rx="2"/><path d="m7 9 3 3-3 3m5 0h5"/>',
  key:'<circle cx="7.5" cy="15.5" r="4.5"/><path d="m10.7 12.3 9.8-9.8M17 6l3 3m-5.5-.5 2.5 2.5"/>',
  history:'<path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1L3.5 8.5m0-5v5h5M12 7.5V12l3 2"/>',
  plug:'<path d="M9 2.5v5m6-5v5M6 7.5h12V11a6 6 0 0 1-12 0Zm6 9.5v4.5"/>',
};
const icon = name => `<span class="icon"><svg viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths.grid}</svg></span>`;
function paintIcons(){document.querySelectorAll('[data-icon]').forEach(e=>{e.innerHTML=`<svg viewBox="0 0 24 24" aria-hidden="true">${paths[e.dataset.icon]||paths.grid}</svg>`;e.removeAttribute('data-icon');});}
const esc = value => String(value ?? '').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let state = {environments:[],nodes:[],subscription:{},runtime:{}};
let currentPage='environments', editingId=null, activeId=null, pendingOpen=null, refreshing=false, toastTimer=null, preparationAttempted=false, previousRuntime=null;

async function api(path, options={}){
  const {method='GET', body} = options;
  const response = await fetch('/api/'+path,{method,credentials:'same-origin',headers:{'X-Workbench-Token':token,...(body!==undefined?{'Content-Type':'application/json'}:{})},...(body!==undefined?{body:JSON.stringify(body)}:{})});
  let data;try{data=await response.json();}catch{throw new Error('本机服务暂时无法连接，请刷新后重试。');}
  if(!response.ok) throw new Error(data.error||data.detail||'操作没有完成，请重试。');
  return data;
}
// An open modal dialog sits in the top layer above any z-index, so the toast joins it there; in full
// screen only the full-screen element shows.
const fullscreenElement=()=>document.fullscreenElement||document.webkitFullscreenElement||null;
function toast(message,error=false,action=null){const t=$('toast'),host=[...document.querySelectorAll('dialog[open]')].pop()||fullscreenElement()||document.body;if(t.parentElement!==host)host.append(t);t.textContent=message;if(action){const b=document.createElement('button');b.className='toast-action';b.textContent=action.label;b.onclick=()=>{t.hidden=true;action.run();};t.append(b);}t.classList.toggle('error',error);t.hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>t.hidden=true,action?9000:5500);}
function setPage(page){currentPage=page;$('environmentPage').hidden=page!=='environments';$('nodesPage').hidden=page!=='nodes';$('informationPage').hidden=page!=='information';$('gatewayPage').hidden=page!=='gateway';$('breadcrumbCurrent').textContent=page==='nodes'?'订阅与线路':page==='information'?'账号与资源':page==='gateway'?'模型网关':'浏览器环境';document.querySelectorAll('[data-page]').forEach(b=>b.classList.toggle('selected',b.dataset.page===page));if(page==='gateway'&&window.loadGateway)loadGateway().catch(e=>toast(e.message,true));}
function showDialog(id){if(!$(id).open)$(id).showModal();}
function hideDialog(id){$(id).close();}
// Windows can install Docker Desktop from here (docker_setup.py): steps only the user can take come as
// docker_setup.step — 'wsl' (one administrator prompt), 'restart', 'virtualization' or 'windows'.
let wslBusy=false;
function updateRuntime(){
  const r=state.runtime, setup=r.docker_setup, auto=!r.docker_installed&&!!setup;
  const ready=r.docker_ready&&r.image_ready;
  const engine=r.engine_app||'Docker';
  const phases={checking:'正在检查运行组件',checking_system:'正在检查这台电脑',downloading_docker:'正在下载 Docker Desktop',installing_docker:'正在安装 Docker Desktop',starting_docker:`正在打开 ${engine}`,waiting_docker:`等待 ${engine} 就绪`,switching_engine:'正在切换到 Linux 容器',loading_image:'正在载入浏览器组件',building:'正在准备浏览器组件'};
  const preparing=r.build_state==='building';
  const progress=['loading_image','downloading_docker'].includes(r.prepare_phase)&&r.prepare_progress!=null?` ${r.prepare_progress}%`:'';
  const phaseTitle=(phases[r.prepare_phase]||'正在准备运行组件')+progress;
  // Steps come before installing, and for an installed Docker Desktop that cannot start yet (WSL 2 off, restart due).
  const step=setup&&!(auto&&!setup.terms_accepted)?setup.step:null;
  const megabytes=value=>Math.round((value||0)/1048576);
  const downloaded=auto&&setup.total?`已下载 ${megabytes(setup.downloaded)} / ${megabytes(setup.total)} MB。`:'';
  const stepTitle={wsl:'还差一步：开启 WSL 2',restart:'重启电脑后继续',hypervisor:'Windows 的虚拟化没有运行',virtualization:'需要开启 CPU 虚拟化',windows:'需要更新 Windows'}[step];
  $('sidebarStatus').textContent=ready?'运行组件已就绪':wslBusy?'正在开启 WSL 2':stepTitle||(preparing?phaseTitle:!r.docker_installed?'需要安装 Docker':r.docker_ready?'浏览器组件待准备':'运行组件未就绪');
  $('sidebarDot').className='dot '+(ready?'green':'amber');
  $('setupBanner').hidden=ready;
  $('setupTitle').textContent=wslBusy?'正在开启 WSL 2':stepTitle||(preparing?phaseTitle:!r.docker_installed?(auto?(setup.terms_accepted&&r.build_error?'自动安装需要重试':'首次使用，自动安装 Docker Desktop'):'首次使用，先安装 Docker Desktop'):r.build_state==='error'?'组件准备需要重试':r.docker_ready?'还差一步，准备浏览器组件':'首次使用，准备运行组件');
  const busyText={checking_system:'正在检查 Windows 版本、虚拟化和 WSL 2。',downloading_docker:`下载完会自动安装 Docker Desktop。${downloaded}`,installing_docker:'只为当前 Windows 用户安装，约需几分钟，完成后会自动启动 Docker Desktop。',waiting_docker:`如果 ${engine} 弹出首次使用提示（服务条款等，登录可跳过），请在它的窗口完成；完成后工作台会自动继续。`,switching_engine:'浏览器组件需要 Linux 容器，正在让 Docker Desktop 自动切换。',loading_image:'正在把应用自带的浏览器组件载入 Docker。只需一次，不用联网下载。',building:'正在联网准备浏览器组件，首次下载需要一些时间。'};
  $('setupDescription').textContent=wslBusy?'请在“用户账户控制”窗口点“是”。命令行窗口会显示进度，完成后自动关闭。':step?setup.message+(preparing&&downloaded?` ${downloaded}`:''):preparing?(busyText[r.prepare_phase]||'工作台会自动启动后台服务，再继续准备浏览器组件。'):!r.docker_installed?(auto?(setup.terms_accepted&&r.build_error?r.build_error:'浏览器环境运行在 Docker 里。点“查看状态”，工作台可以自动下载并安装 Docker Desktop。'):'浏览器环境运行在 Docker 里。点“查看状态”按步骤安装，装好后回到这里会自动继续。'):r.build_error||'点击一键准备，自动完成后台启动与浏览器组件准备。';
  const memory=state.resources?.engine?.memory_mb;
  const dockerValue=r.docker_installed?(r.engine_app||'已安装'):preparing&&r.prepare_phase==='downloading_docker'?'下载中'+progress+(auto&&setup.total?` · ${megabytes(setup.downloaded)} / ${megabytes(setup.total)} MB`:''):preparing&&r.prepare_phase==='installing_docker'?'安装中…':auto&&setup.total&&setup.downloaded>=setup.total?'安装包已下载':'待安装';
  const wslRow=(auto||step)&&setup.wsl?[['WSL 2',{ready:'已开启',wsl:wslBusy?'正在开启…':'需要开启',restart:'重启后生效',hypervisor:'已开启，还没有运行'}[setup.wsl]]]:[];
  $('runtimeChecklist').innerHTML=[['Docker',dockerValue],...wslRow,['后台运行状态',r.docker_ready?'已启动':'未启动'],['浏览器与画面组件',r.image_ready?'已就绪':preparing&&['loading_image','building'].includes(r.prepare_phase)?'准备中…'+progress:'待准备'],...(r.docker_ready&&memory?[['Docker 可分配内存',`${gigabytes(memory)} · 约可同时运行 ${Math.max(1,Math.floor((memory-512)/2048))} 个 2 GB 环境`]]:[])].map(([title,value])=>`<div class="runtime-check">${title}<span>${esc(value)}</span></div>`).join('');
  $('runtimeInstall').hidden=r.docker_installed||auto;
  $('runtimeAuto').hidden=!auto||setup.terms_accepted;
  $('manualDocker').hidden=!auto;
  // A step the user must take is guidance, not a failure; an unrelated error (a broken download) still shows.
  // Before the user agreed, the backend's "install Docker first" is what the panel above already offers.
  const notice=auto&&!setup.terms_accepted?'':step?[r.build_error&&r.build_error!==setup.message?r.build_error:'',setup.message].filter(Boolean).join('\n'):r.build_error;
  $('runtimeError').hidden=!notice;$('runtimeError').textContent=notice||'';$('runtimeError').className='inline-message'+(['wsl','restart','hypervisor'].includes(step)?'':' error');
  let label,disabled=false;
  if(ready)label='组件已就绪';
  else if(auto){
    if(wslBusy){label='正在开启 WSL 2…';disabled=true;}
    else if(!setup.terms_accepted)label='同意并自动安装';
    else if(step==='wsl')label=native?'开启 WSL 2（需要管理员授权）':'查看开启方法';
    else if(['restart','hypervisor'].includes(step)&&native)label='立即重启电脑';
    else if(preparing){label='正在自动安装…';disabled=true;}
    else label=step?'重新检查':r.build_state==='error'?'重试自动安装':'继续自动安装';
  }else if(step){
    // Docker Desktop is installed but Windows must go first.
    if(wslBusy){label='正在开启 WSL 2…';disabled=true;}
    else if(step==='wsl')label=native?'开启 WSL 2（需要管理员授权）':'查看开启方法';
    else if(['restart','hypervisor'].includes(step)&&native)label='立即重启电脑';
    else label='重新检查';
  }else{label=!r.docker_installed?'下载 Docker Desktop':preparing?'正在准备…':r.build_state==='error'?'重试一键准备':'一键准备运行组件';disabled=preparing;}
  $('runtimePrimary').textContent=label;$('runtimePrimary').disabled=disabled;
}
async function dockerSetup(body={}){
  const result=await api('runtime/docker-setup',{method:'POST',body});
  state.runtime.docker_setup=result.docker_setup;state.runtime.build_state=state.runtime.docker_installed?state.runtime.build_state:'building';updateRuntime();
  return result.docker_setup;
}
// The window asks Windows for the one administrator step; the backend checks the outcome itself.
async function enableWsl(){
  if(!native){toast('请在开始菜单搜索 PowerShell，右键“以管理员身份运行”，输入 wsl --install --no-distribution 并回车；完成后重启电脑，再打开本应用。',true,null);return;}
  wslBusy=true;updateRuntime();
  try{
    const result=await native.call('setup.enableWsl');
    if(result?.cancelled){toast('开启 WSL 2 需要管理员授权。请再点一次，并在“用户账户控制”窗口点“是”。',true);return;}
    const setup=await dockerSetup({wsl_requested:true});
    toast(setup.step==='restart'?'WSL 2 已开启，重启电脑后生效。':state.runtime.docker_installed?'WSL 2 已开启，正在启动 Docker Desktop。':'WSL 2 已开启，正在继续安装 Docker Desktop。');
  }catch(e){toast(e.message,true);}
  finally{wslBusy=false;updateRuntime();await refresh();}
}
function confirmRestart(){
  $('confirmTitle').textContent='现在重启电脑？';
  $('confirmMessage').textContent='WSL 2 要重启电脑后才生效。请先保存其他程序里的工作。重启后 Browser Workbench 会自动打开并继续。';
  $('confirmAction').textContent='立即重启';$('confirmAction').className='button primary';
  $('confirmAction').onclick=async()=>{try{await native.call('setup.restart');hideDialog('confirmDialog');}catch(e){toast(e.message,true);}};
  showDialog('confirmDialog');
}
function renderEnvironments(){
  const all=state.environments, query=$('environmentSearch').value.trim().toLowerCase();
  const nodes=new Map(state.nodes.map(n=>[n.id,n]));
  const rows=all.filter(e=>(e.name+' '+serviceName(e)+' '+(nodes.get(e.node_id)?.name||'')).toLowerCase().includes(query));
  $('totalEnvs').textContent=all.length;$('navCount').textContent=all.length;$('listCount').textContent=all.length;
  $('runningLimitLabel').textContent=' / '+(state.runtime.max_running||2);$('runningEnvs').textContent=all.filter(e=>['running','starting','paused'].includes(e.runtime.status)).length;
  $('totalNodes').textContent=state.nodes.length;
  $('nodeStatCaption').textContent=state.nodes.length?'来自你导入的机场订阅':'导入你的机场订阅后显示';
  $('emptyState').hidden=all.length>0;$('noSearchResults').hidden=!all.length||rows.length>0;
  $('environmentList').innerHTML=rows.map(e=>{
    const r=e.runtime,n=nodes.get(e.node_id), index=all.findIndex(x=>x.id===e.id)+1;
    const names={running:'运行中',starting:'启动中',stopped:'已停止',error:'需要重试',paused:'低功耗'};
    const fp=r.fingerprint;
    const core=esc(serviceName(e))+' · '+(e.engine==='firefox'?'标准 Firefox · 独立环境':'旧内核已移除 · 数据保留');
    const meta=fp?`${esc(fp.language)} · ${esc(fp.timezone)} · ${esc(fp.screen)}`:(r.timezone?`zh-CN · ${esc(r.timezone)} · 独立数据目录`:n?.geo?.timezone?`时区随线路 · ${esc(n.geo.timezone)} · 独立数据目录`:'原生浏览器配置 · 独立数据目录');
    return `<article class="environment-row"><div class="environment-identity"><div class="env-avatar">${String(index).padStart(2,'0')}</div><div><div class="env-name" title="${esc(e.name)}">${esc(e.name)} ${accountPill(e)}</div><div class="env-meta env-core">${core}</div><div class="env-meta">${meta}</div></div></div><div class="env-node"><div class="node-name">${esc(n?.name|| (e.node_id?'原节点已失效':'未绑定线路'))}</div><div class="node-detail">${esc(n?.type.toUpperCase()||'可使用无代理测试')}</div></div><div class="env-status"><span class="status-pill ${esc(r.status)}">${r.status==='running'?'<i class="dot green"></i>':''}${names[r.status]||'未知状态'}</span>${r.test_mode?'<div class="node-detail">无代理测试</div>':''}</div><div class="env-runtime runtime-detail"><div class="ip">${esc(r.exit_ip|| (r.test_mode?'测试模式 · 无代理':'出口未检测'))}</div><div>${r.status==='stopped'?'未占用资源':r.memory_mb!=null?esc(r.memory_mb)+' MB · '+(r.cpu_cores!=null?r.cpu_cores.toFixed(2)+' 核':'CPU 待采样'):'等待资源采样'}</div>${r.error?`<div title="${esc(r.error)}">启动失败，点击重试</div>`:''}</div><div class="row-actions"><button class="button ${r.status==='running'?'primary':'secondary'}" data-action="open" data-id="${e.id}" ${r.status==='starting'?'disabled':''}>${r.status==='paused'?'唤醒并打开':r.status==='running'?'打开浏览器':r.status==='starting'?'启动中…':'启动环境'}</button>${['running','paused'].includes(r.status)?`<button class="button ghost" data-action="stop" data-id="${e.id}">停止</button>`:''}<button class="icon-button" data-action="info" data-id="${e.id}" title="查看信息" aria-label="查看 ${esc(e.name)} 的信息">${icon('info')}</button><button class="icon-button" data-action="edit" data-id="${e.id}" title="编辑环境" aria-label="编辑 ${esc(e.name)}" ${['running','starting','paused'].includes(r.status)?'disabled':''}>${icon('edit')}</button><button class="icon-button" data-action="delete" data-id="${e.id}" title="删除环境" aria-label="删除 ${esc(e.name)}" ${r.status==='starting'?'disabled':''}>${icon('trash')}</button></div></article>`;
  }).join('');
}
let selectedMapKey=null, locationNodeId=null;
const geoKey=g=>`${g.lat.toFixed(1)},${g.lon.toFixed(1)}`;
const geoSource=g=>g?.source==='exit'?'出口检测':g?.source==='manual'?'手动指定':'名称推测';
const zoneParts=g=>!g?.timezone?[]:g.daylight?[`冬令时 ${g.standard}`,`夏令时 ${g.daylight}`,`现在是${g.dst_now?'夏令时':'冬令时'}`]:[`全年 ${g.standard}，不用夏令时`];
const zoneText=g=>zoneParts(g).join(' · ');
function renderNodes(){
  const query=$('nodeSearch').value.trim().toLowerCase();
  const matching=state.nodes.filter(n=>n.name.toLowerCase().includes(query));
  const groups=new Map();
  for(const n of matching){if(!n.geo)continue;const key=geoKey(n.geo);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(n);}
  if(selectedMapKey&&!groups.has(selectedMapKey))selectedMapKey=null;
  const visible=matching.filter(n=>!selectedMapKey||(n.geo&&geoKey(n.geo)===selectedMapKey));
  $('nodeListCount').textContent=selectedMapKey?`${visible.length} / ${state.nodes.length}`:state.nodes.length;
  $('nodesEmpty').hidden=state.nodes.length>0;
  $('nodesList').innerHTML=visible.map(n=>{
    const g=n.geo;
    const offsets=zoneParts(g).map(part=>`<span class="zone-part">${esc(part)}</span>`).join(' · ');
    return `<article class="node-card">${icon('globe')}<div class="node-card-body"><strong>${esc(n.name)}</strong><small>${esc(n.type.toUpperCase())} · ${g?esc(g.label)+' · '+geoSource(g):'位置待确认'}</small><small>${esc(g?.timezone||'需检测或选择城市，才能确定时区')}</small>${offsets?`<small>${offsets}</small>`:''}<button class="text-button" data-set-location="${n.id}">设置城市与时区 ↗</button></div></article>`;
  }).join('');
  $('mapMarkers').innerHTML=[...groups].map(([key,nodes])=>{
    const g=nodes[0].geo,verified=nodes.some(n=>n.geo.source!=='name');
    return `<button class="map-marker ${verified?'verified':'inferred'} ${key===selectedMapKey?'active':''}" style="left:${(g.lon+180)/360*100}%;top:${(90-g.lat)/180*100}%" data-map-key="${esc(key)}" aria-label="${esc(g.label)}，${nodes.length} 个节点，${geoSource(g)}" title="${esc(g.label)} · ${nodes.length} 个节点 · ${geoSource(g)}"><span>${nodes.length}</span></button>`;
  }).join('');
  const known=matching.filter(n=>n.geo).length;
  $('mapSummary').textContent=matching.length?`${known} 个节点已标记 · ${groups.size} 个地点${matching.length>known?' · '+(matching.length-known)+' 个位置待确认':''}`:'导入订阅后显示节点位置。';
  $('clearMapSelection').hidden=!selectedMapKey;
  $('mapSelection').hidden=!selectedMapKey;
  if(selectedMapKey){const g=groups.get(selectedMapKey)[0].geo;$('mapSelection').textContent=`${g.label} · ${geoSource(g)} · ${g.timezone||'城市与时区待确认'}`;}
  const progress=state.geography?.progress;
  $('probeLocations').disabled=!state.nodes.length||!state.runtime.image_ready||progress?.running;
  $('probeLocations').textContent=progress?.running?`检测中 ${progress.done} / ${progress.total}`:'重新检测出口 ↗';
  $('mapProgress').textContent=progress?.running?'正在自动检测每条线路的实际出口，地图会随结果更新。已打开的环境不受影响。':state.nodes.length&&!state.runtime.image_ready?'运行组件准备好后，会自动检测每条线路的实际出口。':progress?.total?`检测完成 ${progress.done} / ${progress.total}${progress.failed?' · '+progress.failed+' 条未确认，保留名称推测或手动设置':''}。出口可能随线路变化。`:'点击标记筛选线路。同地点的节点合并显示；名称推测不代表实际出口。底图：Natural Earth。';
  $('refreshSubscription').hidden=!state.subscription.configured;
}

async function refresh(){
  if(refreshing)return;refreshing=true;
  try{
    state=await api('state');renderEnvironments();renderNodes();updateRuntime();renderInformation();renderStrip();forgetTerminals();
    if(!preparationAttempted&&state.runtime.docker_installed&&!state.runtime.image_ready&&state.runtime.build_state==='idle'){preparationAttempted=true;await api('runtime/prepare',{method:'POST'});}
    // Docker installed or finished its first start after preparation gave up: continue by itself.
    const was=previousRuntime,now=state.runtime;previousRuntime=now;
    if(was&&!now.image_ready&&now.build_state==='error'&&((!was.docker_installed&&now.docker_installed)||(!was.docker_ready&&now.docker_ready))){await api('runtime/prepare',{method:'POST'});}
    if(state.app)$('versionLabel').textContent='v'+state.app.version;
    if(activeId){const e=state.environments.find(e=>e.id===activeId);if(e?.runtime.url&&document.activeElement!==$('browserAddress'))$('browserAddress').value=e.runtime.url.startsWith('file:')?'':e.runtime.url;}
    if(pendingOpen){const e=state.environments.find(e=>e.id===pendingOpen);if(e?.runtime.status==='running'){pendingOpen=null;await openBrowser(e.id);}else if(e?.runtime.status==='error'){pendingOpen=null;toast(e.runtime.error||'环境未能启动。',true);}}
  }catch(e){toast(e.message,true);}finally{refreshing=false;}
}
function nodeOptions(selected){
  $('environmentNode').innerHTML='<option value="">不绑定节点（仅无代理测试）</option>'+state.nodes.map(n=>`<option value="${n.id}">${esc(n.name)} · ${esc(n.type.toUpperCase())}</option>`).join('');
  $('environmentNode').value=selected||'';updateTestOption();
}
function updateTestOption(){
  const node=state.nodes.find(n=>n.id===$('environmentNode').value),g=node?.geo;
  $('testOption').hidden=Boolean(node);
  $('environmentTimezone').textContent=!node?'无代理测试使用 UTC 时区。':g?.timezone?`时区随线路：${g.label} · ${g.timezone} · 现在 ${g.now}${g.daylight?`（${g.dst_now?'夏令时':'冬令时'}，换季时自动切换）`:''}`:'这条线路的城市还没确定：启动前会自动检测出口；检测不到时，请在“订阅与线路”里为它选择城市。';
}
function newEnvironment(test=false){
  $('resourceCreateFields').hidden=false;$('createCpuLimit').value=2;$('createMemoryLimit').value=2;setLimitInputBounds('createCpuLimit','createMemoryLimit');
  editingId=null;$('environmentEngine').disabled=false;$('environmentEngine').value='firefox';$('environmentDialogTitle').textContent='新建环境';$('saveEnvironment').innerHTML='创建环境<span>→</span>';$('environmentName').value=test?'本机测试环境':'';$('environmentError').hidden=true;$('testMode').checked=test;$('autoOpen').checked=true;$('autoOpenOption').hidden=false;
  serviceOptions(state.environments.at(-1)?.service||'claude','');
  nodeOptions(test?null:state.nodes[0]?.id);showDialog('environmentDialog');$('environmentName').focus();
}
function editEnvironment(id){
  const env=state.environments.find(e=>e.id===id);if(!env)return;
  $('resourceCreateFields').hidden=true;
  editingId=id;$('environmentEngine').value=env.engine||'firefox';$('environmentEngine').disabled=true;$('environmentDialogTitle').textContent='编辑环境';$('saveEnvironment').textContent='保存修改';$('environmentName').value=env.name;$('environmentError').hidden=true;$('testMode').checked=false;$('autoOpenOption').hidden=true;
  serviceOptions(env.service||'claude',env.start_url||'');
  nodeOptions(env.node_id);showDialog('environmentDialog');
}
// Which website the environment opens; "其他网站" takes an address.
function serviceOptions(selected,url){
  $('environmentService').innerHTML=(state.services||[]).map(s=>`<option value="${esc(s.id)}">${esc(s.name)}</option>`).join('');
  $('environmentService').value=selected;if(!$('environmentService').value)$('environmentService').value='claude';
  $('environmentUrl').value=url;serviceChanged();
}
function serviceChanged(){
  const s=serviceOf({service:$('environmentService').value}),custom=s.id==='custom',env=editingId&&state.environments.find(e=>e.id===editingId);
  $('environmentUrlField').hidden=!custom;
  $('environmentServiceNote').textContent=env&&env.service!==s.id?'改成别的网站后，环境里已有的登录数据仍然保留；账号信息里的套餐和状态会清空，需要重新记录。':custom?'环境启动后打开这个地址。只支持 https 网站。':`环境启动后打开 ${hostOf(s.url)}。一个环境建议只登录一个账号。`;
}
$('environmentService').onchange=serviceChanged;
async function startEnvironment(id,testMode=false){
  await api(`environments/${id}/start`,{method:'POST',body:{test_mode:testMode}});pendingOpen=id;toast('环境正在启动，准备好后会自动打开。');await refresh();
}
async function openBrowser(id){
  const env=state.environments.find(e=>e.id===id);if(!env)return;
  $('browserHint').textContent=env.engine==='firefox'?'标准模式：跳转后的地址请以画面内地址栏为准':'返回工作台不会停止环境';
  $('browserAddress').placeholder=`输入网页地址，例如 ${hostOf(env.start_url||serviceOf(env).url)||'claude.ai'}`;
  const view=await api(`environments/${id}/view`);activeId=id;$('browserName').textContent=env.name;$('browserMode').textContent=env.runtime.test_mode?'无代理测试':'运行中';$('browserFrame').src=view.url;$('browserAddress').value=env.runtime.url?.startsWith('http')?env.runtime.url:'';$('browserView').hidden=false;document.body.style.overflow='hidden';
  renderStrip();$('stripItems').querySelector('.current')?.scrollIntoView({block:'nearest',inline:'nearest'});
  if(viewTab==='terminal')openTerminal(id).catch(e=>toast(e.message,true));
}
function confirmDelete(id){
  const env=state.environments.find(e=>e.id===id);$('confirmTitle').textContent='删除这个环境？';$('confirmAction').textContent='确认删除';$('confirmAction').className='button danger';$('confirmMessage').textContent=`“${env.name}”的登录记录、浏览器数据和已下载文件会被清除。这个操作无法撤回。`;
  $('confirmAction').onclick=async()=>{try{await api(`environments/${id}?confirm=${id}`,{method:'DELETE'});hideDialog('confirmDialog');toast('环境已删除。');await refresh();}catch(e){toast(e.message,true);}};showDialog('confirmDialog');
}
async function browserAction(kind,extra={}){if(!activeId)return;return api(`environments/${activeId}/action`,{method:'POST',body:{kind,...extra}});}

document.addEventListener('click',async event=>{
  const close=event.target.closest('[data-close]');if(close){hideDialog(close.dataset.close);return;}
  const page=event.target.closest('[data-page]');if(page){setPage(page.dataset.page);return;}
  const browser=event.target.closest('[data-browser-action]');if(browser){try{await browserAction(browser.dataset.browserAction);}catch(e){toast(e.message,true);}return;}
  const action=event.target.closest('[data-action]');if(!action)return;
  const id=action.dataset.id;
  try{
    if(action.dataset.action==='info'){showInformation(id);return;}
    if(action.dataset.action==='edit')editEnvironment(id);
    if(action.dataset.action==='delete')confirmDelete(id);
    if(action.dataset.action==='stop'){action.disabled=true;await api(`environments/${id}/stop`,{method:'POST'});toast('环境已停止，数据已保留。');await refresh();}
    if(action.dataset.action==='open'){
      const env=state.environments.find(e=>e.id===id);
      if(env.runtime.status==='paused'){await api(`environments/${id}/resume`,{method:'POST'});pendingOpen=id;await refresh();}
      else if(env.runtime.status==='running'){await openBrowser(id);}
      else if(!env.node_id){editEnvironment(id);$('autoOpenOption').hidden=false;$('autoOpen').checked=true;toast('请绑定节点，或勾选无代理测试模式后打开。');}
      else{await startEnvironment(id);}
    }
  }catch(e){toast(e.message,true);action.disabled=false;}
});
$('newEnvironment').onclick=()=>newEnvironment();$('emptyTest').onclick=()=>newEnvironment(true);$('emptyImport').onclick=()=>{setPage('nodes');$('subscriptionUrl').focus();};
$('environmentSearch').oninput=renderEnvironments;$('nodeSearch').oninput=renderNodes;$('environmentNode').onchange=updateTestOption;
$('environmentForm').onsubmit=async event=>{
  event.preventDefault();const nodeId=$('environmentNode').value||null,autoOpen=$('autoOpen').checked&&!$('autoOpenOption').hidden;
  if(autoOpen&&!nodeId&&!$('testMode').checked){$('environmentError').hidden=false;$('environmentError').textContent='请选择节点，或勾选无代理测试模式。';return;}
  $('saveEnvironment').disabled=true;$('environmentError').hidden=true;
  try{
    const service=$('environmentService').value,website={service,start_url:service==='custom'?$('environmentUrl').value:null};
    const env=await api(editingId?`environments/${editingId}`:'environments',{method:editingId?'PATCH':'POST',body:{name:$('environmentName').value,node_id:nodeId,...website,...(!editingId?{engine:$('environmentEngine').value,cpu_limit:Number($('createCpuLimit').value),memory_limit_mb:Math.round(Number($('createMemoryLimit').value)*1024)}:{})}});
    hideDialog('environmentDialog');await refresh();
    if(autoOpen){await startEnvironment(env.id,!nodeId&&$('testMode').checked);}else{toast(editingId?'修改已保存。':'环境已创建。');}
  }catch(e){if($('environmentDialog').open){$('environmentError').hidden=false;$('environmentError').textContent=e.message;}else{toast(e.message,true);if(!state.runtime.image_ready)showDialog('runtimeDialog');}}finally{$('saveEnvironment').disabled=false;}
};
const skippedNote=r=>r.skipped?`另有 ${r.skipped} 个节点用了暂不支持的协议或设置，已跳过。`:'';
$('subscriptionForm').onsubmit=async event=>{
  event.preventDefault();$('importButton').disabled=true;$('importButton').textContent='正在导入…';$('subscriptionMessage').hidden=true;
  try{const r=await api('subscription',{method:'POST',body:{url:$('subscriptionUrl').value}});$('subscriptionUrl').value='';$('subscriptionMessage').textContent=`已导入 ${r.count} 个节点。${skippedNote(r)}现在可以为环境选择线路。`;$('subscriptionMessage').className='inline-message';$('subscriptionMessage').hidden=false;await refresh();toast(`已导入 ${r.count} 个节点。`);}catch(e){$('subscriptionMessage').textContent=e.message;$('subscriptionMessage').className='inline-message error';$('subscriptionMessage').hidden=false;}finally{$('importButton').disabled=false;$('importButton').innerHTML='导入订阅<span>→</span>';}
};
$('refreshSubscription').onclick=async()=>{try{$('refreshSubscription').disabled=true;const r=await api('subscription',{method:'POST',body:{url:''}});toast(`订阅已更新，共 ${r.count} 个节点。${skippedNote(r)}`);await refresh();}catch(e){toast(e.message,true);}finally{$('refreshSubscription').disabled=false;}};
$('toggleUrl').onclick=()=>$('subscriptionUrl').type=$('subscriptionUrl').type==='password'?'text':'password';
$('runtimeButton').onclick=$('setupAction').onclick=()=>{updateRuntime();showDialog('runtimeDialog');};
$('runtimePrimary').onclick=async()=>{
  try{const r=state.runtime,setup=r.docker_setup;
    if(setup&&(!r.docker_installed||setup.step)){
      if(!r.docker_installed&&!setup.terms_accepted){const next=await dockerSetup({accept_terms:true});toast('已开始自动安装 Docker Desktop。');if(next.step==='wsl'&&native)await enableWsl();return;}
      if(setup.step==='wsl'){await enableWsl();return;}
      if(['restart','hypervisor'].includes(setup.step)&&native){confirmRestart();return;}
      await dockerSetup();toast(r.docker_installed?'正在重新检查这台电脑。':'正在继续自动安装 Docker Desktop。');return;
    }
    if(!r.docker_installed){openExternal(r.docker_download_url||'https://www.docker.com/products/docker-desktop/');toast('正在用浏览器下载 Docker Desktop。安装并打开后，工作台会自动继续。');return;}if(r.docker_ready&&r.image_ready){hideDialog('runtimeDialog');return;}preparationAttempted=true;await api('runtime/prepare',{method:'POST'});toast('已开始一键准备，就绪后会自动继续。');await refresh();}catch(e){toast(e.message,true);}
};
$('manualDocker').onclick=()=>{openExternal(state.runtime.docker_download_url||'https://www.docker.com/products/docker-desktop/');toast('正在用浏览器下载 Docker Desktop。按默认选项装好后，工作台会自动继续。');};
$('exitBrowser').onclick=()=>{leaveFullscreen();setViewTab('browser');$('browserView').hidden=true;$('browserFrame').src='about:blank';activeId=null;document.body.style.overflow='';refresh();};
$('reconnectBrowser').onclick=async()=>{try{await openBrowser(activeId);}catch(e){toast(e.message,true);}};
$('addressForm').onsubmit=async e=>{e.preventDefault();try{await browserAction('navigate',{url:$('browserAddress').value});}catch(error){toast(error.message,true);}};
$('toggleTextInput').onclick=()=>$('browserTextPanel').hidden=!$('browserTextPanel').hidden;
$('sendBrowserText').onclick=async()=>{try{$('sendBrowserText').disabled=true;await browserAction('paste',{text:$('browserText').value});$('browserText').value='';toast('文字已发送到浏览器输入框。');}catch(e){toast(e.message,true);}finally{$('sendBrowserText').disabled=false;}};
$('copySelection').onclick=async()=>{try{const r=await browserAction('copy');if(!r.text){toast('请先在远程网页中选中文字。');return;}await navigator.clipboard.writeText(r.text);toast('选中文字已复制。');}catch(e){toast(e.message,true);}};
// The strip above an open environment lists every environment: one click switches to a started one,
// wakes a paused one or starts a stopped one (it opens by itself once ready, like from the list).
const statusNames={running:'运行中',starting:'启动中',stopped:'已停止',error:'需要重试',paused:'低功耗'};
const switchHints={running:'点击切换到这里',paused:'点击唤醒并切换',starting:'启动后自动切换',stopped:'点击启动，准备好后自动切换',error:'点击重新启动'};
let stripHtml='';
function renderStrip(){
  if($('browserView').hidden)return;
  const all=state.environments,status=e=>e.runtime?.status||'stopped';
  $('stripSummary').textContent=`${all.filter(e=>['running','starting','paused'].includes(status(e))).length} / ${all.length} 已启动`;
  const html=all.map(e=>{const s=status(e),current=e.id===activeId;
    return `<button class="strip-item${current?' current':''}" data-switch="${e.id}"${current?' aria-current="page"':''} title="${esc(e.name)} · ${esc(serviceName(e))} · ${statusNames[s]||'未知状态'}${current?' · 正在查看':' · '+(switchHints[s]||'')}"><span class="strip-dot ${esc(s)}"></span><span class="strip-name">${esc(e.name)}</span><span class="strip-service">${esc(serviceName(e))}</span></button>`;}).join('');
  // Redrawn only when something changed, so a click is never lost to the 6-second refresh.
  if(html===stripHtml)return;
  const items=$('stripItems'),scroll=items.scrollLeft;
  items.innerHTML=stripHtml=html;items.scrollLeft=scroll;
}
async function switchEnvironment(id){
  const env=state.environments.find(e=>e.id===id);if(!env||id===activeId)return;
  const s=env.runtime.status;
  if(s==='running'){await openBrowser(id);return;}
  if(s==='paused'){await api(`environments/${id}/resume`,{method:'POST'});pendingOpen=id;await refresh();return;}
  if(s==='starting'){pendingOpen=id;toast(`“${env.name}”正在启动，准备好后会自动切换过去。`);return;}
  if(!env.node_id){editEnvironment(id);$('autoOpenOption').hidden=false;$('autoOpen').checked=true;toast('请绑定线路，或勾选无代理测试模式后打开。');return;}
  await startEnvironment(id);
}
$('stripItems').addEventListener('click',async event=>{
  const item=event.target.closest('[data-switch]');if(!item)return;
  item.disabled=true;
  try{await switchEnvironment(item.dataset.switch);}catch(e){toast(e.message,true);}finally{item.disabled=false;}
});
// A mouse wheel scrolls the strip sideways when it holds more environments than fit.
$('stripItems').addEventListener('wheel',event=>{const items=$('stripItems');if(Math.abs(event.deltaY)>Math.abs(event.deltaX)&&items.scrollWidth>items.clientWidth){items.scrollLeft+=event.deltaY;event.preventDefault();}},{passive:false});

// Full screen shows only the environment's picture. The Mac and Windows windows fill the screen for it
// (MainWindow.swift, MainForm.cs); where the Fullscreen API is missing the picture fills the window instead.
// Esc ends it, also while the remote desktop has the keyboard (clipboard-bridge.js passes it on).
let fullscreenHintTimer=null, realFullscreen=false;
const frameOnly=()=>$('browserView').classList.contains('frame-only');
function showFullscreenHint(){$('fullscreenHint').hidden=false;clearTimeout(fullscreenHintTimer);fullscreenHintTimer=setTimeout(()=>$('fullscreenHint').hidden=true,2600);}
async function enterFullscreen(){
  const wrap=$('browserFrameWrap');
  let request;
  try{request=wrap.requestFullscreen?wrap.requestFullscreen():wrap.webkitRequestFullscreen?(wrap.webkitRequestFullscreen(),Promise.resolve()):Promise.reject(new Error('unsupported'));}
  catch(error){request=Promise.reject(error);}
  // Some embedded browsers never answer the request: after a moment the picture fills the window instead.
  const granted=await Promise.race([request.then(()=>true,()=>false),new Promise(resolve=>setTimeout(()=>resolve(false),1500))]);
  if(!granted&&!fullscreenElement()){$('browserView').classList.add('frame-only');$('exitFullscreen').hidden=false;fullscreenChanged();}
  showFullscreenHint();$('browserFrame').focus();
}
async function leaveFullscreen(){
  $('browserView').classList.remove('frame-only');$('exitFullscreen').hidden=true;
  if(fullscreenElement()){try{await (document.exitFullscreen?document.exitFullscreen():document.webkitExitFullscreen());}catch{}}
  fullscreenChanged();
}
function fullscreenChanged(){
  const real=!!fullscreenElement();
  // Real full screen replaces the in-window version, and ending it ends both.
  if(real||realFullscreen){$('browserView').classList.remove('frame-only');$('exitFullscreen').hidden=true;}
  realFullscreen=real;
  const on=real||frameOnly();
  $('fullscreenBrowser').classList.toggle('active',on);$('fullscreenBrowser').title=on?'退出全屏（Esc）':'全屏显示环境画面，按 Esc 退出';
  if(!on)$('fullscreenHint').hidden=true;
}
document.addEventListener('fullscreenchange',fullscreenChanged);document.addEventListener('webkitfullscreenchange',fullscreenChanged);
$('fullscreenBrowser').onclick=()=>fullscreenElement()||frameOnly()?leaveFullscreen():enterFullscreen();
$('exitFullscreen').onclick=leaveFullscreen;
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&frameOnly())leaveFullscreen();});
window.addEventListener('message',event=>{
  if(event.origin===location.origin&&event.source===$('browserFrame').contentWindow&&event.data?.type==='workbench-exit-fullscreen')leaveFullscreen();
});

// 终端: a command line inside the open environment (workbench/terminal.py), drawn by xterm.js
// (static/vendor/xterm, loaded the first time it is needed). Each environment keeps its own while you switch
// tabs or environments; it ends when the environment stops, and Enter then opens a new one.
const terminals=new Map();
let viewTab='browser', xterm=null;
$('terminalNote').textContent='环境里的命令行 · '+(onWindows?'选中文字后按 Ctrl+C 复制，Ctrl+V 粘贴':'⌘C 复制选中的文字，⌘V 粘贴');
async function loadXterm(){
  if(!xterm){
    const css=document.createElement('link');css.rel='stylesheet';css.href='/static/vendor/xterm/xterm.css';document.head.append(css);
    const [{Terminal},{FitAddon}]=await Promise.all([import('/static/vendor/xterm/xterm.mjs'),import('/static/vendor/xterm/addon-fit.mjs')]);
    xterm={Terminal,FitAddon};
  }
  return xterm;
}
function copyText(text){return native?native.call('clipboard.writeText',{text}):navigator.clipboard.writeText(text);}
async function openTerminal(envId){
  if(!terminals.has(envId)){
    const {Terminal,FitAddon}=await loadXterm();
    if(!terminals.has(envId)){
      const element=document.createElement('div');element.className='terminal-pane';$('terminalHost').append(element);
      const term=new Terminal({cursorBlink:true,fontSize:13,scrollback:5000,
        fontFamily:onWindows?'Consolas, "Microsoft YaHei UI", monospace':'"SF Mono", Menlo, "PingFang SC", monospace',
        theme:{background:'#101312',foreground:'#e3e9e6',cursor:'#6fcca4',selectionBackground:'rgba(111, 204, 164, .35)'}});
      const fit=new FitAddon();term.loadAddon(fit);term.open(element);
      const t={envId,term,fit,element,socket:null,ended:false};terminals.set(envId,t);
      term.onData(data=>{if(t.ended){if(data.includes('\r'))connectTerminal(t);return;}sendTerminal(t,{type:'input',data});});
      term.onResize(({rows,cols})=>sendTerminal(t,{type:'resize',rows,cols}));
      term.attachCustomKeyEventHandler(event=>terminalKey(t,event));
      showTerminal(envId);connectTerminal(t);return;
    }
  }
  showTerminal(envId);
}
function showTerminal(envId){
  for(const t of terminals.values())t.element.hidden=t.envId!==envId;
  const t=terminals.get(envId);
  if(t&&viewTab==='terminal'&&activeId===envId)requestAnimationFrame(()=>{t.fit.fit();t.term.focus();});
}
function connectTerminal(t){
  const env=state.environments.find(e=>e.id===t.envId);
  t.ended=false;
  t.term.writeln(`\x1b[2m“${env?.name||'环境'}”里的命令行，用户 browser。${env?.runtime?.test_mode?'无代理测试：网络直接连接，不经过线路。':'网络和浏览器一样经过这个环境的线路。'}\x1b[0m`);
  t.term.writeln('\x1b[2m停止环境后只保留 /profile 里的文件；放进 /profile/transfer/downloads 的文件可以在“文件传输”里取回。\x1b[0m');
  if(!t.element.hidden&&!$('terminalHost').hidden)t.fit.fit();
  const socket=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/view/${t.envId}/terminal?rows=${t.term.rows}&cols=${t.term.cols}`);
  socket.binaryType='arraybuffer';t.socket=socket;
  socket.onmessage=event=>{
    if(typeof event.data==='string'){try{const m=JSON.parse(event.data);if(m.type==='error')t.term.writeln(`\x1b[31m${m.message}\x1b[0m`);}catch{}return;}
    t.term.write(new Uint8Array(event.data));
  };
  socket.onclose=()=>{if(t.socket!==socket)return;t.socket=null;t.ended=true;t.term.writeln('\r\n\x1b[2m终端已结束。按回车键重新打开。\x1b[0m');};
}
function sendTerminal(t,message){if(t.socket?.readyState===WebSocket.OPEN)t.socket.send(JSON.stringify(message));}
// Windows: Ctrl+C copies a selection (without one it stops the running program) and Ctrl+V pastes, like in
// other Windows programs. The Mac's ⌘C and ⌘V are the system's copy and paste already.
function terminalKey(t,event){
  if(event.type!=='keydown'||!onWindows||!event.ctrlKey||event.altKey||event.metaKey)return true;
  const key=event.key.toLowerCase();
  if(key==='c'&&t.term.hasSelection()){copyText(t.term.getSelection()).catch(()=>{});t.term.clearSelection();return false;}
  return key!=='v';
}
// Terminals of deleted environments go away.
function forgetTerminals(){
  for(const [id,t] of terminals){
    if(state.environments.some(e=>e.id===id))continue;
    const socket=t.socket;t.socket=null;socket?.close();t.term.dispose();t.element.remove();terminals.delete(id);
  }
}
function setViewTab(tab){
  if(tab==='terminal'&&(fullscreenElement()||frameOnly()))leaveFullscreen();
  viewTab=tab;
  $('browserView').classList.toggle('terminal-mode',tab==='terminal');
  $('tabBrowser').setAttribute('aria-selected',String(tab==='browser'));$('tabTerminal').setAttribute('aria-selected',String(tab==='terminal'));
  $('terminalHost').hidden=$('terminalNote').hidden=tab!=='terminal';
  if(tab==='terminal'&&activeId)openTerminal(activeId).catch(e=>toast(e.message,true));
}
document.querySelector('.view-tabs').addEventListener('click',event=>{const tab=event.target.closest('[data-view-tab]');if(tab)setViewTab(tab.dataset.viewTab);});
new ResizeObserver(()=>{const t=terminals.get(activeId);if(viewTab==='terminal'&&t&&!t.element.hidden)t.fit.fit();}).observe($('terminalHost'));

paintIcons();refresh();setInterval(refresh,6000);

// Transfers are initiated only by an explicit paste, selection, or drop.
function fileSize(bytes){return bytes>=1048576?(bytes/1048576).toFixed(1)+' MB':bytes>=1024?(bytes/1024).toFixed(1)+' KB':bytes+' B';}
function transferMessage(message,error=false){$('transferMessage').textContent=message;$('transferMessage').hidden=false;$('transferMessage').className='inline-message'+(error?' error':'');}
async function refreshFiles(){
  if(!activeId)return;
  const result=await api(`environments/${activeId}/files`);
  for(const [kind,target] of [['incoming','incomingFiles'],['downloads','downloadFiles']]){
    $(target).innerHTML=result[kind].length?result[kind].map(f=>`<div class="transfer-file"><div><strong>${esc(f.name)}</strong><small>${esc(fileSize(f.size))} · ${esc(new Date(f.modified*1000).toLocaleString())}</small></div>${kind==='incoming'?`<button class="button secondary small" data-copy-file-path="${esc(f.path)}">复制环境路径</button>`:`<a class="button primary small" href="/api/environments/${activeId}/files/downloads/${f.id}" download>下载到电脑</a>`}</div>`).join(''):`<div class="transfer-empty">${kind==='incoming'?'还没有传入文件。':'暂无已完成的下载。'}</div>`;
  }
}
async function showTransfers(){
  if(!activeId)return;
  const transferEnv=state.environments.find(e=>e.id===activeId);
  $('transferEnvironment').textContent=transferEnv?.name||'';$('claudeDownloadNote').hidden=serviceOf(transferEnv).id!=='claude';
  $('transferMessage').hidden=true;
  showDialog('filesDialog');
  try{await refreshFiles();}catch(e){transferMessage(e.message,true);}
}
async function uploadToEnvironment(files){
  const envId=activeId;
  if(!envId)throw new Error('请先打开一个浏览器环境。');
  const results=[];
  for(const file of files){
    if(file.size>100*1024*1024)throw new Error('单个文件最多 100 MB。');
    const response=await fetch(`/api/environments/${envId}/files/upload`,{method:'POST',credentials:'same-origin',headers:{'X-Workbench-Token':token,'X-File-Name':encodeURIComponent(file.name)},body:file});
    const result=await response.json();
    if(!response.ok)throw new Error(result.error||'文件传入未完成。');
    results.push(result);
  }
  if($('filesDialog').open)await refreshFiles();
  return results;
}
async function pasteIntoEnvironment(text,files=[]){
  if(!activeId)return;
  if(files.length){
    const saved=await uploadToEnvironment(files);
    if(files.length===1&&files[0].type==='image/png'&&files[0].size<=20*1024*1024){
      await browserAction('paste_image',{name:saved[0].path.split('/').pop()});
      toast('图片已粘贴到环境，请在网页中确认附件。');
    }else{
      await showTransfers();toast('文件已送入环境。请在网站上传窗口选择“电脑传入文件”。');
    }
    return;
  }
  if(!text){toast('剪贴板里没有可粘贴的文字。图片和文件也可通过“文件传输”送入。');return;}
  if(text.length>20000)throw new Error('一次最多粘贴 20000 个字符，长文请作为文件传入。');
  await browserAction('paste',{text});
  toast('已粘贴到环境中的当前输入位置。');
}
$('pasteFromComputer').onclick=async()=>{
  try{
    if(native){
      const r=await native.call('clipboard.read');
      if(r.files?.length){await showTransfers();toast('剪贴板里是文件。请把文件拖进画面，或在这里选择文件传入。');return;}
      if(r.image){await pasteIntoEnvironment('',[new File([Uint8Array.from(atob(r.image),c=>c.charCodeAt(0))],'剪贴板图片.png',{type:'image/png'})]);return;}
      await pasteIntoEnvironment(r.text||'');return;
    }
    if(navigator.clipboard?.read){
      const items=await navigator.clipboard.read();
      for(const item of items){
        if(item.types.includes('image/png')){
          const blob=await item.getType('image/png');
          await pasteIntoEnvironment('',[new File([blob],'剪贴板图片.png',{type:'image/png'})]);return;
        }
      }
      for(const item of items){if(item.types.includes('text/plain')){await pasteIntoEnvironment(await (await item.getType('text/plain')).text());return;}}
      toast('剪贴板内容暂不支持，请通过“文件传输”选择文件。');
    }else{await pasteIntoEnvironment(await navigator.clipboard.readText());}
  }catch(e){
    if(e.name==='NotAllowedError'||e.name==='NotFoundError'){
      $('browserTextPanel').hidden=false;$('browserText').focus();toast(`浏览器未开放剪贴板读取。请在文字框里按 ${keys.paste}，再点“发送到输入框”。`);
    }else toast(e.message,true);
  }
};
$('openTransfers').onclick=showTransfers;
$('refreshFiles').onclick=()=>refreshFiles().catch(e=>transferMessage(e.message,true));
$('uploadFiles').onchange=async event=>{
  try{const files=Array.from(event.target.files);if(!files.length)return;transferMessage('正在传入文件…');await uploadToEnvironment(files);transferMessage(`已传入 ${files.length} 个文件。在网站上传窗口选择“电脑传入文件”。`);}catch(e){transferMessage(e.message,true);}finally{event.target.value='';}
};
$('fileDrop').ondragover=e=>{e.preventDefault();$('fileDrop').classList.add('dragging');};
$('fileDrop').ondragleave=()=>$('fileDrop').classList.remove('dragging');
$('fileDrop').ondrop=async e=>{e.preventDefault();$('fileDrop').classList.remove('dragging');try{const files=Array.from(e.dataTransfer.files);if(!files.length)return;transferMessage('正在传入文件…');await uploadToEnvironment(files);transferMessage(`已传入 ${files.length} 个文件。`);}catch(error){transferMessage(error.message,true);}};
document.addEventListener('click',async event=>{
  const copy=event.target.closest('[data-copy-file-path]');
  const open=event.target.closest('[data-open-transfer]');
  try{
    if(copy){await (native?native.call('clipboard.writeText',{text:copy.dataset.copyFilePath}):navigator.clipboard.writeText(copy.dataset.copyFilePath));toast('环境路径已复制。在文件窗口按 Ctrl+L，然后粘贴。');}
    if(open){await api(`environments/${activeId}/files/open`,{method:'POST',body:{kind:open.dataset.openTransfer}});}
  }catch(e){transferMessage(e.message,true);}
});
window.addEventListener('message',event=>{
  if(event.origin!==location.origin||event.source!==$('browserFrame').contentWindow||event.data?.type!=='workbench-paste')return;
  const text=typeof event.data.text==='string'?event.data.text:'';
  const files=Array.isArray(event.data.files)?event.data.files.filter(f=>f instanceof File):[];
  pasteIntoEnvironment(text,files).catch(e=>toast(e.message,true));
});
setInterval(()=>{if($('filesDialog').open)refreshFiles().catch(()=>{});},4000);
// A file dropped anywhere must never navigate away from the workbench; while an
// environment is open it is sent there, like a paste. The transfer dialog's
// own drop area handles its drops itself.
document.addEventListener('dragover',event=>{if(event.dataTransfer?.types?.includes('Files'))event.preventDefault();});
document.addEventListener('drop',event=>{
  const files=Array.from(event.dataTransfer?.files||[]);if(!files.length)return;event.preventDefault();
  if(event.target.closest?.('#fileDrop'))return;
  if(!activeId){toast('请先打开一个环境，再把文件拖进画面。');return;}
  pasteIntoEnvironment('',files).catch(e=>toast(e.message,true));
});
window.addEventListener('workbench-native-download',event=>{
  const d=event.detail||{};
  if(!d.ok){toast(`“${d.name||'文件'}”没有下载完成，请重试。`,true);return;}
  toast(`已保存到“下载”文件夹：${d.name}`,false,{label:`在 ${fileManager} 中显示`,run:()=>native?.call('revealFile',{path:d.path}).catch(()=>{})});
});

const copyRequests=new Map();
function remoteCopyText(){
  const envId=activeId;
  if(!envId)return Promise.reject(new Error('请先打开浏览器环境。'));
  return new Promise((resolve,reject)=>{
    const id=crypto.randomUUID();
    const timer=setTimeout(()=>{copyRequests.delete(id);reject(new Error('复制超时，请重连画面后重试。'));},8000);
    copyRequests.set(id,{envId,resolve,reject,timer});
    $('browserFrame').contentWindow.postMessage({type:'workbench-copy-request',id},location.origin);
  });
}
function copyFromEnvironment(){
  const text=remoteCopyText();
  if(native){text.then(value=>native.call('clipboard.writeText',{text:value})).then(()=>toast(`已复制到主电脑，可以在外面按 ${keys.paste} 粘贴。`)).catch(e=>toast(e.message,true));return;}
  let write;
  try{
    if(navigator.clipboard?.write&&typeof ClipboardItem!=='undefined'){
      // The write starts during the user's gesture; only the payload is delayed.
      write=navigator.clipboard.write([new ClipboardItem({'text/plain':text.then(value=>new Blob([value],{type:'text/plain'}))})]);
    }else{write=text.then(value=>navigator.clipboard.writeText(value));}
  }catch(error){write=Promise.reject(error);}
  write.then(()=>toast(`已复制到主电脑，可以在外面按 ${keys.paste} 粘贴。`)).catch(async error=>{
    try{
      const value=await text;
      $('copyFallbackText').value=value;showDialog('copyFallbackDialog');
      $('copyFallbackText').focus();$('copyFallbackText').select();
    }catch(failure){toast(failure.message||error.message,true);}
  });
}
window.addEventListener('message',async event=>{
  if(event.origin!==location.origin||event.source!==$('browserFrame').contentWindow)return;
  if(event.data?.type==='workbench-copy-shortcut'){copyFromEnvironment();return;}
  if(event.data?.type!=='workbench-copy-ready')return;
  const pending=copyRequests.get(event.data.id);if(!pending)return;
  copyRequests.delete(event.data.id);clearTimeout(pending.timer);
  try{
    if(event.data.error||activeId!==pending.envId)throw new Error('复制连接已改变，请重连画面后重试。');
    const result=await api(`environments/${pending.envId}/clipboard`,{method:'POST'});
    if(!result.text)throw new Error('没有取到文字。请先在环境内选中文字或点击网页的复制按钮。');
    pending.resolve(result.text);
  }catch(error){pending.reject(error);}
});
$('copySelection').onclick=copyFromEnvironment;

$('probeLocations').onclick=async()=>{try{await api('geography/probe',{method:'POST'});await refresh();toast('正在检测线路出口位置。');}catch(e){toast(e.message,true);}};
$('clearMapSelection').onclick=()=>{selectedMapKey=null;renderNodes();};
document.addEventListener('click',event=>{
  const marker=event.target.closest('[data-map-key]');
  if(marker){selectedMapKey=selectedMapKey===marker.dataset.mapKey?null:marker.dataset.mapKey;renderNodes();return;}
  const edit=event.target.closest('[data-set-location]');if(!edit)return;
  locationNodeId=edit.dataset.setLocation;const node=state.nodes.find(n=>n.id===locationNodeId);
  $('locationNodeName').textContent=node.name;
  $('locationPlace').innerHTML='<option value="" disabled selected>请选择城市</option>'+(state.geography?.places||[]).map(p=>`<option value="${esc(p.id)}">${esc(p.label)} · ${esc(p.timezone)}</option>`).join('');
  const place=state.geography?.places.find(p=>p.timezone===node.geo?.timezone);
  if(place)$('locationPlace').value=place.id;
  showDialog('locationDialog');
});
$('locationForm').onsubmit=async event=>{
  event.preventDefault();$('saveLocation').disabled=true;
  try{await api(`nodes/${locationNodeId}/location`,{method:'POST',body:{place_id:$('locationPlace').value}});hideDialog('locationDialog');await refresh();toast('城市和时区已保存，之后新建的环境会使用此设置。');}catch(e){toast(e.message,true);}finally{$('saveLocation').disabled=false;}
};

// Account records and scoped resource telemetry.
let limitsEnvironmentId=null, accountEnvironmentId=null, checkingAccount=false;
// Which website an environment is for (state.services, from workbench/services.py); environments from before are Claude ones.
const serviceOf=e=>(state.services||[]).find(s=>s.id===(e?.service||'claude'))||{id:'claude',name:'Claude',url:'https://claude.ai/',check:true,plans:[]};
const hostOf=url=>{try{return new URL(url).hostname.replace(/^www\./,'');}catch{return '';}};
const serviceName=e=>e?.service==='custom'?(hostOf(e.start_url)||'其他网站'):serviceOf(e).name;
const planLabel=(e,plan)=>!plan||plan==='unknown'?'待核实':serviceOf(e).plans.find(p=>p.id===plan)?.name||'待核实';
const accountStatusNames={unknown:'待核实',active:'可用',blocked:'已封禁 / 停用',logged_out:'未登录'};
function accountPill(e){const a=e?.account||{},plan=planLabel(e,a.plan);return `<span class="account-pill ${a.status==='blocked'?'blocked':plan!=='待核实'?'known':'unknown'}">${esc(a.status==='blocked'?'已封禁':plan)}</span>`;}
function gigabytes(mb){return mb==null?'—':(mb/1024).toFixed(mb>=1024?2:3)+' GB';}
function recordSource(a){if(a.plan_source&&a.status_source&&a.plan_source!==a.status_source)return `套餐：${a.plan_source==='manual'?'手动记录':a.plan_source==='page'?'页面核对':'未核对'}；状态：${a.status_source==='manual'?'手动记录':a.status_source==='page'?'页面核对':'未核对'}`;return a.source==='manual'?'手动记录':a.source==='page'?(a.verified?'已核对':'上次核对记录'):'尚未核对';}
function showInformation(id){setPage('information');renderInformation();if(id){const card=$('info-'+id);card?.scrollIntoView({behavior:'smooth',block:'center'});card?.classList.add('highlight');setTimeout(()=>card?.classList.remove('highlight'),1800);}}
function renderInformation(){
  const r=state.resources||{},engine=r.engine||{},host=r.host||{};
  $('infoOccupied').textContent=`${r.occupied??0} / ${r.max_running||state.runtime.max_running||2}`;
  $('infoPaused').textContent=`${r.paused||0} 个低功耗 · 保留内存与名额`;
  $('infoCpu').textContent=r.cpu_cores!=null?r.cpu_cores.toFixed(2)+' 核':'—';
  $('infoCpuCapacity').textContent=engine.cpu_count?`运行组件共有 ${engine.cpu_count} 核`:'等待运行组件连接';
  $('infoMemory').textContent=r.memory_mb!=null?gigabytes(r.memory_mb):'—';
  $('infoMemoryCapacity').textContent=r.metrics_complete?'本工作台所有已启动环境合计':'部分数据待采样';
  $('infoAllocated').textContent=gigabytes(r.allocated_memory_mb);
  $('infoBudget').textContent=`可分配总量 ${gigabytes(r.memory_budget_mb)}`;
  $('hostResources').textContent=`这台电脑：${host.cpu_count||'—'} 核 · ${gigabytes(host.memory_mb)}　/　运行组件：${engine.cpu_count||'—'} 核 · ${gigabytes(engine.memory_mb)}。内存上限合计保留 512 MB 给运行开销。`;
  $('metricTimestamp').textContent=r.sampled_at?`最近采样 ${new Date(r.sampled_at*1000).toLocaleTimeString()}${Date.now()/1000-r.sampled_at>15?' · 数据已过期':''}`:'等待采样';
  $('infoCount').textContent=state.environments.length;
  const nodes=new Map(state.nodes.map(n=>[n.id,n]));
  $('informationList').innerHTML=state.environments.length?state.environments.map(e=>{
    const x=e.runtime,a=e.account||{},paused=x.status==='paused',started=['running','paused'].includes(x.status),busy=x.status==='starting'||x.account_checking;
    const cpu=x.cpu_cores??(started?null:0),memory=x.memory_mb??(started?null:0),cpuLimit=x.effective_cpu_limit||e.cpu_limit||2,memLimit=x.effective_memory_limit_mb||e.memory_limit_mb||2048;
    const last=a.checked_at?new Date(a.checked_at*1000).toLocaleString():'暂无账号记录';
    return `<article id="info-${e.id}" class="information-card"><div class="information-card-heading"><div><h2>${esc(e.name)}</h2><small>${esc(nodes.get(e.node_id)?.name||'无代理测试 / 未绑定线路')}</small></div><span class="status-pill ${esc(x.status)}">${({running:'运行中',paused:'低功耗',starting:'启动中',error:'需要重试',stopped:'已停止'})[x.status]||'未知'}</span></div><div class="account-line">${accountPill(e)}<strong>${esc(a.label||'账号未备注')}</strong><span>${esc(accountStatusNames[a.status]||'待核实')}</span></div><div class="account-record">${esc(recordSource(a))} · ${esc(last)}${a.last_attempt&&!a.verified?'<br>最近一次核对未确认，以上为已有记录。':''}</div><div class="resource-meter"><div><span>CPU</span><strong>${cpu==null?'待采样':cpu.toFixed(2)+' 核'} <small>/ ${cpuLimit} 核</small></strong></div><progress max="${cpuLimit}" value="${cpu||0}"></progress></div><div class="resource-meter"><div><span>内存${x.memory_stale?' · 上次采样':''}</span><strong>${gigabytes(memory)} <small>/ ${gigabytes(memLimit)}</small></strong></div><progress max="${memLimit}" value="${memory||0}"></progress></div>${paused?'<p class="paused-note">浏览器已暂停，内存仍保留。打开时会唤醒。</p>':''}<div class="information-actions"><button class="button secondary small" data-manage="account" data-id="${e.id}">账号信息</button><button class="button secondary small" data-manage="limits" data-id="${e.id}" ${busy?'disabled':''}>资源额度</button>${started?`<button class="button secondary small" data-manage="${paused?'resume':'pause'}" data-id="${e.id}" ${busy?'disabled':''}>${paused?'唤醒环境':'低功耗'}</button><button class="text-button" data-manage="stop" data-id="${e.id}" ${busy?'disabled':''}>停止</button>`:''}<button class="button primary small" data-manage="open" data-id="${e.id}" ${busy?'disabled':''}>${paused?'唤醒并打开':started?'打开':'启动'}</button></div></article>`;
  }).join(''):'<div class="nodes-empty">新建环境后，可在这里查看账号与资源信息。</div>';
}
function setLimitInputBounds(cpuId,memoryId){const r=state.resources?.engine||{};$(cpuId).max=r.cpu_count||64;$(memoryId).max=r.memory_mb?Math.floor((r.memory_mb-512)/256)/4:256;}
function showLimits(id){const e=state.environments.find(e=>e.id===id);if(!e)return;limitsEnvironmentId=id;$('limitsEnvironmentName').textContent=e.name;$('cpuLimitInput').value=e.cpu_limit||2;$('memoryLimitInput').value=(e.memory_limit_mb||2048)/1024;setLimitInputBounds('cpuLimitInput','memoryLimitInput');showDialog('limitsDialog');}
function showAccount(id){const e=state.environments.find(e=>e.id===id);if(!e)return;accountEnvironmentId=id;const a=e.account||{},s=serviceOf(e);
  $('accountTitle').textContent=`${serviceName(e)} 账号信息`;$('checkAccount').hidden=!s.check;
  $('accountCheckNote').textContent=s.check?'核对会短暂打开 Claude 账单窗口，完成后关闭并返回原窗口。请暂时不要操作环境内浏览器。只读取明确的套餐与账号提示，不修改订阅。':'这个网站暂不支持自动核对：请在环境里看一下账号的套餐，再在下面手动记录。';
  $('accountPlanInput').innerHTML='<option value="unknown">待核实</option>'+s.plans.map(p=>`<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('');
  $('accountEnvironmentName').textContent=`${e.name} · ${serviceName(e)}`;$('accountLabelInput').value=a.label||'';$('accountPlanInput').value=a.plan||'unknown';if(!$('accountPlanInput').value)$('accountPlanInput').value='unknown';$('accountStatusInput').value=a.status||'unknown';updateAccountEvidence(e);showDialog('accountDialog');}
function updateAccountEvidence(e){const a=e.account||{};$('accountEvidence').textContent=`${recordSource(a)}${a.checked_at?' · '+new Date(a.checked_at*1000).toLocaleString():''}${a.note?'。'+a.note:''}`;$('checkAccount').disabled=checkingAccount||e.runtime.status!=='running'||e.runtime.account_checking;$('checkAccount').textContent=checkingAccount?'正在核对，请暂不操作浏览器…':e.runtime.status==='paused'?'请先唤醒环境再核对':e.runtime.status!=='running'?`请先启动环境并登录 ${serviceName(e)}`:'核对当前账号 ↗';}
$('resourceSettings').onclick=()=>{$('maxRunningInput').value=state.runtime.max_running||2;const r=state.resources||{};$('resourceSettingsHint').textContent=`当前已启动 ${r.occupied||0} 个，可分配内存 ${gigabytes(r.memory_budget_mb)}。CPU 和内存额度在每个环境的“资源额度”里设置。`;showDialog('resourceSettingsDialog');};
$('resourceSettingsForm').onsubmit=async event=>{event.preventDefault();$('saveResourceSettings').disabled=true;try{await api('resources/settings',{method:'PATCH',body:{max_running:Number($('maxRunningInput').value)}});hideDialog('resourceSettingsDialog');await refresh();toast('同时运行上限已保存。');}catch(e){toast(e.message,true);}finally{$('saveResourceSettings').disabled=false;}};
$('limitsForm').onsubmit=async event=>{event.preventDefault();$('saveLimits').disabled=true;try{await api(`environments/${limitsEnvironmentId}/resources`,{method:'PATCH',body:{cpu_limit:Number($('cpuLimitInput').value),memory_limit_mb:Math.round(Number($('memoryLimitInput').value)*1024)}});hideDialog('limitsDialog');await refresh();toast('资源额度已保存。');}catch(e){toast(e.message,true);}finally{$('saveLimits').disabled=false;}};
$('accountForm').onsubmit=async event=>{event.preventDefault();$('saveAccount').disabled=true;try{await api(`environments/${accountEnvironmentId}/account`,{method:'PATCH',body:{label:$('accountLabelInput').value,plan:$('accountPlanInput').value,status:$('accountStatusInput').value}});await refresh();updateAccountEvidence(state.environments.find(e=>e.id===accountEnvironmentId));toast('账号信息已保存为手动记录。');}catch(e){toast(e.message,true);}finally{$('saveAccount').disabled=false;}};
$('checkAccount').onclick=async()=>{if(checkingAccount)return;const checkedId=accountEnvironmentId;checkingAccount=true;$('saveAccount').disabled=true;updateAccountEvidence(state.environments.find(e=>e.id===accountEnvironmentId));try{const result=await api(`environments/${checkedId}/account/check`,{method:'POST'});await refresh();const e=state.environments.find(e=>e.id===checkedId);if(accountEnvironmentId===checkedId&&e){$('accountPlanInput').value=e.account.plan||'unknown';$('accountStatusInput').value=e.account.status||'unknown';}toast(result.verified?'账号信息已核对。':'未能确认，已保留上次记录；可以手动标记。',!result.verified);}catch(e){toast(e.message,true);}finally{checkingAccount=false;$('saveAccount').disabled=false;const e=state.environments.find(e=>e.id===accountEnvironmentId);if(e)updateAccountEvidence(e);}};
document.addEventListener('click',async event=>{const button=event.target.closest('[data-manage]');if(!button)return;const id=button.dataset.id,kind=button.dataset.manage;try{if(kind==='account'){showAccount(id);return;}if(kind==='limits'){showLimits(id);return;}button.disabled=true;if(kind==='pause'||kind==='resume'||kind==='stop'){await api(`environments/${id}/${kind}`,{method:'POST'});toast(kind==='pause'?'环境已进入低功耗，内存仍保留。':kind==='resume'?'环境已唤醒。':'环境已停止，内存已释放。');await refresh();return;}if(kind==='open'){const e=state.environments.find(e=>e.id===id);if(e.runtime.status==='paused'){await api(`environments/${id}/resume`,{method:'POST'});pendingOpen=id;await refresh();}else if(e.runtime.status==='running')await openBrowser(id);else if(e.node_id)await startEnvironment(id);else{editEnvironment(id);$('autoOpenOption').hidden=false;$('autoOpen').checked=true;toast('请绑定线路，或明确勾选无代理测试。');}}}catch(e){toast(e.message,true);}finally{button.disabled=false;}});

// Where things are kept (Windows app): the data folder, Docker's disk with each environment's login data,
// and the program. The data folder can move; the window stops everything and moves it (workbench/relocate.py).
let storageState=null, storageLoads=0;
function storageSize(bytes){const gb=1073741824;return bytes==null?'—':bytes>=gb?(bytes/gb).toFixed(bytes>=10*gb?0:1)+' GB':bytes>=1048576?Math.round(bytes/1048576)+' MB':bytes>=1024?Math.round(bytes/1024)+' KB':bytes+' B';}
function storageRow(path,detail,buttons=''){return `<div class="transfer-file"><div><strong class="storage-path">${esc(path)}</strong>${detail?`<small>${esc(detail)}</small>`:''}</div>${buttons?`<div class="transfer-actions">${buttons}</div>`:''}</div>`;}
function storageSection(title,copy,rows,extra='',action=''){return `<section class="transfer-section"><div class="transfer-heading"><h3>${title}</h3>${action}</div><p>${copy}</p><div class="transfer-list">${rows}</div>${extra}</section>`;}
function renderStorage(){
  const s=storageState;if(!s)return;
  const open=which=>`<button class="button secondary" data-storage-open="${which}">打开</button>`;
  const free=bytes=>bytes==null?'':` · 这个磁盘还剩 ${storageSize(bytes)}`;
  const parts=[storageSection('数据','订阅、环境列表，以及各环境“电脑传入 / 环境下载”的文件。',storageRow(s.data_dir,`共 ${storageSize(s.data_bytes)}${free(s.free_bytes)}`,open('data')),'',s.can_move?'<button class="text-button" data-storage-move>更改位置…</button>':'')];
  const d=s.docker;
  if(d)parts.push(d.installed
    ?storageSection('浏览器组件和登录状态','由 Docker Desktop 保存：浏览器组件，以及每个环境的登录状态、Cookie 和浏览记录。',storageRow(d.folder,`Docker 数据 ${storageSize(d.bytes)}${free(d.free_bytes)}`,open('docker')),'<p class="transfer-note">要移到其他磁盘：先停止所有环境，打开 Docker Desktop → Settings → Resources → Advanced，在 Disk image location 选新文件夹，再点 Apply &amp; restart。登录状态会一起移过去。</p>')
    :storageSection('浏览器组件和登录状态','还没有安装 Docker Desktop。由工作台替你安装时，浏览器组件和各环境的登录状态会放在：',storageRow(d.folder,`这个磁盘还剩 ${storageSize(d.free_bytes)}`)));
  const envRows=s.environments.map(e=>`<div class="transfer-file"><div><strong>${esc(e.name)}</strong><small>${s.profiles_in_docker?`登录状态 ${storageSize(e.volume_bytes)} · 传输的文件 ${storageSize(e.folder_bytes)}`:`登录状态和文件 ${storageSize(e.folder_bytes)}`}</small></div></div>`).join('')||'<div class="transfer-empty">还没有环境。</div>';
  const unknown=s.profiles_in_docker&&s.environments.length&&s.environments.every(e=>e.volume_bytes==null);
  parts.push(storageSection('各环境占用',s.profiles_in_docker?`登录状态在 Docker 里（上面那一处），传输的文件在数据文件夹里。删除环境会一起删掉这两部分。${unknown?'Docker 现在没有运行，登录状态的大小暂时统计不了。':''}`:'都在数据文件夹里。',envRows));
  if(s.old_copies.length)parts.push(storageSection('移动前的旧数据','移动数据后留下的原文件夹。确认新位置一切正常后，可以删除它释放空间。',s.old_copies.map((c,i)=>storageRow(c.folder,`共 ${storageSize(c.bytes)}`,`<button class="button secondary" data-storage-old="${i}">打开</button><button class="button danger" data-storage-delete="${i}">删除…</button>`)).join('')));
  if(s.install_dir)parts.push(storageSection('程序','程序文件夹。重新运行安装程序可以装到别处，数据不受影响。',storageRow(s.install_dir,'',open('install'))));
  $('storageContent').innerHTML=parts.join('');
}
async function loadStorage(){
  const load=++storageLoads;$('refreshStorage').disabled=true;
  if(!storageState)$('storageContent').innerHTML='<div class="transfer-list"><div class="transfer-empty">正在统计…</div></div>';
  try{const s=await api('storage');if(load===storageLoads){storageState=s;renderStorage();}}
  catch(e){if(load===storageLoads){$('storageContent').innerHTML=`<div class="inline-message error">${esc(e.message)}</div>`;}}
  finally{if(load===storageLoads)$('refreshStorage').disabled=false;}
}
function confirmStorage(title,message,label,kind,run){
  $('confirmTitle').textContent=title;$('confirmMessage').textContent=message;$('confirmAction').textContent=label;$('confirmAction').className='button '+kind;
  $('confirmAction').onclick=async()=>{$('confirmAction').disabled=true;try{await run();}catch(e){toast(e.message,true);}finally{$('confirmAction').disabled=false;}};
  showDialog('confirmDialog');
}
async function moveStorage(){
  const picked=await native.call('storage.chooseFolder');
  if(!picked||picked.cancelled)return;
  const target=await api('storage/check',{method:'POST',body:{path:picked.path}});
  const active=state.environments.filter(e=>['running','starting','paused'].includes(e.runtime?.status)).length;
  confirmStorage('把数据移到新位置？',`数据（约 ${storageSize(target.bytes)}）会复制到“${target.data_dir}”，逐个文件核对无误后才改用新位置。${active?`正在运行的 ${active} 个环境会先停止。`:''}移动时窗口显示进度，完成后自动重新打开工作台。各环境的登录状态在 Docker 里，不受影响。原来的文件夹会保留为“旧数据”，确认没问题后可以在“存储位置”里删除。`,'开始移动','primary',async()=>{await native.call('storage.move',{target:target.root});hideDialog('confirmDialog');hideDialog('storageDialog');});
}
if(native&&onWindows)$('storageSettings').hidden=false;
$('storageSettings').onclick=()=>{showDialog('storageDialog');loadStorage();};
$('refreshStorage').onclick=()=>loadStorage();
$('storageContent').addEventListener('click',async event=>{
  const button=event.target.closest('button');if(!button||!storageState)return;
  try{
    if(button.dataset.storageOpen){await api('storage/open',{method:'POST',body:{which:button.dataset.storageOpen}});}
    else if(button.dataset.storageOld){await api('storage/open',{method:'POST',body:{which:'old',folder:storageState.old_copies[Number(button.dataset.storageOld)].folder}});}
    else if(button.dataset.storageMove!==undefined){button.disabled=true;try{await moveStorage();}finally{button.disabled=false;}}
    else if(button.dataset.storageDelete){const copy=storageState.old_copies[Number(button.dataset.storageDelete)];
      confirmStorage('删除旧数据？',`将永久删除“${copy.folder}”（约 ${storageSize(copy.bytes)}），删除后无法恢复。这是移动数据前留下的副本；现在用的数据在“${storageState.data_dir}”，不受影响。`,'删除旧数据','danger',async()=>{await api('storage/delete-old',{method:'POST',body:{folder:copy.folder}});hideDialog('confirmDialog');toast('旧数据已删除。');await loadStorage();});}
  }catch(e){toast(e.message,true);}
});
