'use strict';
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="workbench-token"]').content;
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
};
const icon = name => `<span class="icon"><svg viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths.grid}</svg></span>`;
function paintIcons(){document.querySelectorAll('[data-icon]').forEach(e=>{e.innerHTML=`<svg viewBox="0 0 24 24" aria-hidden="true">${paths[e.dataset.icon]||paths.grid}</svg>`;e.removeAttribute('data-icon');});}
const esc = value => String(value ?? '').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let state = {environments:[],nodes:[],subscription:{},runtime:{}};
let currentPage='environments', editingId=null, activeId=null, pendingOpen=null, refreshing=false, toastTimer=null, preparationAttempted=false;

async function api(path, options={}){
  const {method='GET', body} = options;
  const response = await fetch('/api/'+path,{method,credentials:'same-origin',headers:{'X-Workbench-Token':token,...(body!==undefined?{'Content-Type':'application/json'}:{})},...(body!==undefined?{body:JSON.stringify(body)}:{})});
  let data;try{data=await response.json();}catch{throw new Error('本机服务暂时无法连接，请刷新后重试。');}
  if(!response.ok) throw new Error(data.error||data.detail||'操作没有完成，请重试。');
  return data;
}
function toast(message,error=false){$('toast').textContent=message;$('toast').classList.toggle('error',error);$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,5500);}
function setPage(page){currentPage=page;$('environmentPage').hidden=page!=='environments';$('nodesPage').hidden=page!=='nodes';$('informationPage').hidden=page!=='information';$('breadcrumbCurrent').textContent=page==='nodes'?'订阅与线路':page==='information'?'账号与资源':'浏览器环境';document.querySelectorAll('[data-page]').forEach(b=>b.classList.toggle('selected',b.dataset.page===page));}
function showDialog(id){if(!$(id).open)$(id).showModal();}
function hideDialog(id){$(id).close();}
function updateRuntime(){
  const r=state.runtime;
  const ready=r.docker_ready&&r.image_ready;
  const phases={checking:'正在检查运行组件',starting_docker:'正在打开 Docker',waiting_docker:'等待 Docker 就绪',building:'正在准备浏览器组件'};
  const preparing=r.build_state==='building';
  const phaseTitle=phases[r.prepare_phase]||'正在准备运行组件';
  $('sidebarStatus').textContent=ready?'运行组件已就绪':preparing?phaseTitle:r.docker_ready?'浏览器组件待准备':'运行组件未就绪';
  $('sidebarDot').className='dot '+(ready?'green':'amber');
  $('setupBanner').hidden=ready;
  $('setupTitle').textContent=preparing?phaseTitle:r.build_state==='error'?'组件准备需要重试':r.docker_ready?'还差一步，准备浏览器组件':'首次使用，准备运行组件';
  $('setupDescription').textContent=preparing?(r.prepare_phase==='waiting_docker'?'如果 Docker 弹出首次启动提示，请在它的窗口完成；完成后工作台会自动继续。':r.prepare_phase==='building'?'正在自动准备浏览器组件，首次下载需要一些时间。':'工作台会自动启动后台服务，再继续准备浏览器组件。'):r.build_error||'点击一键准备，自动完成后台启动与浏览器组件准备。';
  $('runtimeChecklist').innerHTML=[['本机运行服务',r.docker_installed?'已安装':'待安装'],['后台运行状态',r.docker_ready?'已启动':'未启动'],['浏览器与画面组件',r.image_ready?'已就绪':r.build_state==='building'?'准备中…':'待准备']].map(([title,value])=>`<div class="runtime-check">${title}<span>${value}</span></div>`).join('');
  $('runtimeError').hidden=!r.build_error;$('runtimeError').textContent=r.build_error||'';
  $('runtimePrimary').disabled=r.build_state==='building';
  $('runtimePrimary').textContent=ready?'组件已就绪':!r.docker_installed?'查看安装说明':preparing?'正在准备…':r.build_state==='error'?'重试一键准备':'一键准备运行组件';
}
function renderEnvironments(){
  const all=state.environments, query=$('environmentSearch').value.trim().toLowerCase();
  const nodes=new Map(state.nodes.map(n=>[n.id,n]));
  const rows=all.filter(e=>(e.name+' '+(nodes.get(e.node_id)?.name||'')).toLowerCase().includes(query));
  $('totalEnvs').textContent=all.length;$('navCount').textContent=all.length;$('listCount').textContent=all.length;
  $('runningLimitLabel').textContent=' / '+(state.runtime.max_running||2);$('runningEnvs').textContent=all.filter(e=>['running','starting','paused'].includes(e.runtime.status)).length;
  $('totalNodes').textContent=state.nodes.length;
  $('nodeStatCaption').textContent=state.nodes.length?'来自你导入的机场订阅':'导入你的机场订阅后显示';
  $('emptyState').hidden=all.length>0;$('noSearchResults').hidden=!all.length||rows.length>0;
  $('environmentList').innerHTML=rows.map(e=>{
    const r=e.runtime,n=nodes.get(e.node_id), index=all.findIndex(x=>x.id===e.id)+1;
    const names={running:'运行中',starting:'启动中',stopped:'已停止',error:'需要重试',paused:'低功耗'};
    const fp=r.fingerprint;
    const core=e.engine==='firefox'?'标准 Firefox · 独立环境':'旧内核已移除 · 数据保留';
    const meta=fp?`${esc(fp.language)} · ${esc(fp.timezone)} · ${esc(fp.screen)}`:(r.timezone?`zh-CN · ${esc(r.timezone)} · 独立数据目录`:'原生浏览器配置 · 独立数据目录');
    return `<article class="environment-row"><div class="environment-identity"><div class="env-avatar">${String(index).padStart(2,'0')}</div><div><div class="env-name" title="${esc(e.name)}">${esc(e.name)} ${accountPill(e.account)}</div><div class="env-meta env-core">${core}</div><div class="env-meta">${meta}</div></div></div><div class="env-node"><div class="node-name">${esc(n?.name|| (e.node_id?'原节点已失效':'未绑定线路'))}</div><div class="node-detail">${esc(n?.type.toUpperCase()||'可使用无代理测试')}</div></div><div class="env-status"><span class="status-pill ${esc(r.status)}">${r.status==='running'?'<i class="dot green"></i>':''}${names[r.status]||'未知状态'}</span>${r.test_mode?'<div class="node-detail">无代理测试</div>':''}</div><div class="env-runtime runtime-detail"><div class="ip">${esc(r.exit_ip|| (r.test_mode?'测试模式 · 无代理':'出口未检测'))}</div><div>${r.status==='stopped'?'未占用资源':r.memory_mb!=null?esc(r.memory_mb)+' MB · '+(r.cpu_cores!=null?r.cpu_cores.toFixed(2)+' 核':'CPU 待采样'):'等待资源采样'}</div>${r.error?`<div title="${esc(r.error)}">启动失败，点击重试</div>`:''}</div><div class="row-actions"><button class="button ${r.status==='running'?'primary':'secondary'}" data-action="open" data-id="${e.id}" ${r.status==='starting'?'disabled':''}>${r.status==='paused'?'唤醒并打开':r.status==='running'?'打开浏览器':r.status==='starting'?'启动中…':'启动环境'}</button>${['running','paused'].includes(r.status)?`<button class="button ghost" data-action="stop" data-id="${e.id}">停止</button>`:''}<button class="icon-button" data-action="info" data-id="${e.id}" title="查看信息" aria-label="查看 ${esc(e.name)} 的信息">${icon('info')}</button><button class="icon-button" data-action="edit" data-id="${e.id}" title="编辑环境" aria-label="编辑 ${esc(e.name)}" ${['running','starting','paused'].includes(r.status)?'disabled':''}>${icon('edit')}</button><button class="icon-button" data-action="delete" data-id="${e.id}" title="删除环境" aria-label="删除 ${esc(e.name)}" ${r.status==='starting'?'disabled':''}>${icon('trash')}</button></div></article>`;
  }).join('');
}
let selectedMapKey=null, locationNodeId=null;
const geoKey=g=>`${g.lat.toFixed(1)},${g.lon.toFixed(1)}`;
const geoSource=g=>g?.source==='exit'?'出口检测':g?.source==='manual'?'手动指定':'名称推测';
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
    const offsets=g?.january?`1月 ${g.january} · 7月 ${g.july}`:'';
    return `<article class="node-card">${icon('globe')}<div class="node-card-body"><strong>${esc(n.name)}</strong><small>${esc(n.type.toUpperCase())} · ${g?esc(g.label)+' · '+geoSource(g):'位置待确认'}</small><small>${esc(g?.timezone||'需检测或选择城市，才能确定时区')}</small>${offsets?`<small>${esc(offsets)}</small>`:''}<button class="text-button" data-set-location="${n.id}">设置城市与时区 ↗</button></div></article>`;
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
  $('probeLocations').textContent=progress?.running?`检测中 ${progress.done} / ${progress.total}`:'检测出口位置 ↗';
  $('mapProgress').textContent=progress?.running?'正在逐条检测节点出口，页面会自动更新。已打开的环境不受影响。':progress?.total?`检测完成 ${progress.done} / ${progress.total}${progress.failed?' · '+progress.failed+' 条未确认，保留名称推测或手动设置':''}。出口可能随线路变化。`:'点击标记筛选线路。同地点的节点合并显示；名称推测不代表实际出口。底图：Natural Earth。';
  $('refreshSubscription').hidden=!state.subscription.configured;
}

async function refresh(){
  if(refreshing)return;refreshing=true;
  try{
    state=await api('state');renderEnvironments();renderNodes();updateRuntime();renderInformation();
    if(!preparationAttempted&&state.runtime.docker_installed&&!state.runtime.image_ready&&state.runtime.build_state==='idle'){preparationAttempted=true;await api('runtime/prepare',{method:'POST'});}
    if(activeId){const e=state.environments.find(e=>e.id===activeId);if(e?.runtime.url&&document.activeElement!==$('browserAddress'))$('browserAddress').value=e.runtime.url.startsWith('file:')?'':e.runtime.url;}
    if(pendingOpen){const e=state.environments.find(e=>e.id===pendingOpen);if(e?.runtime.status==='running'){pendingOpen=null;await openBrowser(e.id);}else if(e?.runtime.status==='error'){pendingOpen=null;toast(e.runtime.error||'环境未能启动。',true);}}
  }catch(e){toast(e.message,true);}finally{refreshing=false;}
}
function nodeOptions(selected){
  $('environmentNode').innerHTML='<option value="">不绑定节点（仅无代理测试）</option>'+state.nodes.map(n=>`<option value="${n.id}">${esc(n.name)} · ${esc(n.type.toUpperCase())}</option>`).join('');
  $('environmentNode').value=selected||'';updateTestOption();
}
function updateTestOption(){$('testOption').hidden=Boolean($('environmentNode').value);}
function newEnvironment(test=false){
  $('resourceCreateFields').hidden=false;$('createCpuLimit').value=2;$('createMemoryLimit').value=2;setLimitInputBounds('createCpuLimit','createMemoryLimit');
  editingId=null;$('environmentEngine').disabled=false;$('environmentEngine').value='firefox';$('environmentDialogTitle').textContent='新建环境';$('saveEnvironment').innerHTML='创建环境<span>→</span>';$('environmentName').value=test?'本机测试环境':'';$('environmentError').hidden=true;$('testMode').checked=test;$('autoOpen').checked=true;$('autoOpenOption').hidden=false;
  nodeOptions(test?null:state.nodes[0]?.id);showDialog('environmentDialog');$('environmentName').focus();
}
function editEnvironment(id){
  const env=state.environments.find(e=>e.id===id);if(!env)return;
  $('resourceCreateFields').hidden=true;
  editingId=id;$('environmentEngine').value=env.engine||'firefox';$('environmentEngine').disabled=true;$('environmentDialogTitle').textContent='编辑环境';$('saveEnvironment').textContent='保存修改';$('environmentName').value=env.name;$('environmentError').hidden=true;$('testMode').checked=false;$('autoOpenOption').hidden=true;
  nodeOptions(env.node_id);showDialog('environmentDialog');
}
async function startEnvironment(id,testMode=false){
  await api(`environments/${id}/start`,{method:'POST',body:{test_mode:testMode}});pendingOpen=id;toast('环境正在启动，准备好后会自动打开。');await refresh();
}
async function openBrowser(id){
  const env=state.environments.find(e=>e.id===id);if(!env)return;
  $('browserHint').textContent=env.engine==='firefox'?'标准模式：跳转后的地址请以画面内地址栏为准':'返回工作台不会停止环境';
  const view=await api(`environments/${id}/view`);activeId=id;$('browserName').textContent=env.name;$('browserMode').textContent=env.runtime.test_mode?'无代理测试':'运行中';$('browserFrame').src=view.url;$('browserAddress').value=env.runtime.url?.startsWith('http')?env.runtime.url:'';$('browserView').hidden=false;document.body.style.overflow='hidden';
}
function confirmDelete(id){
  const env=state.environments.find(e=>e.id===id);$('confirmTitle').textContent='删除这个环境？';$('confirmMessage').textContent=`“${env.name}”的登录记录、浏览器数据和已下载文件会被清除。这个操作无法撤回。`;
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
    const env=await api(editingId?`environments/${editingId}`:'environments',{method:editingId?'PATCH':'POST',body:{name:$('environmentName').value,node_id:nodeId,...(!editingId?{engine:$('environmentEngine').value,cpu_limit:Number($('createCpuLimit').value),memory_limit_mb:Math.round(Number($('createMemoryLimit').value)*1024)}:{})}});
    hideDialog('environmentDialog');await refresh();
    if(autoOpen){await startEnvironment(env.id,!nodeId&&$('testMode').checked);}else{toast(editingId?'修改已保存。':'环境已创建。');}
  }catch(e){if($('environmentDialog').open){$('environmentError').hidden=false;$('environmentError').textContent=e.message;}else{toast(e.message,true);if(!state.runtime.image_ready)showDialog('runtimeDialog');}}finally{$('saveEnvironment').disabled=false;}
};
$('subscriptionForm').onsubmit=async event=>{
  event.preventDefault();$('importButton').disabled=true;$('importButton').textContent='正在导入…';$('subscriptionMessage').hidden=true;
  try{const r=await api('subscription',{method:'POST',body:{url:$('subscriptionUrl').value}});$('subscriptionUrl').value='';$('subscriptionMessage').textContent=`已导入 ${r.count} 个节点。现在可以为环境选择线路。`;$('subscriptionMessage').className='inline-message';$('subscriptionMessage').hidden=false;await refresh();toast(`已导入 ${r.count} 个节点。`);}catch(e){$('subscriptionMessage').textContent=e.message;$('subscriptionMessage').className='inline-message error';$('subscriptionMessage').hidden=false;}finally{$('importButton').disabled=false;$('importButton').innerHTML='导入订阅<span>→</span>';}
};
$('refreshSubscription').onclick=async()=>{try{$('refreshSubscription').disabled=true;const r=await api('subscription',{method:'POST',body:{url:''}});toast(`订阅已更新，共 ${r.count} 个节点。`);await refresh();}catch(e){toast(e.message,true);}finally{$('refreshSubscription').disabled=false;}};
$('toggleUrl').onclick=()=>$('subscriptionUrl').type=$('subscriptionUrl').type==='password'?'text':'password';
$('runtimeButton').onclick=$('setupAction').onclick=()=>{updateRuntime();showDialog('runtimeDialog');};
$('runtimePrimary').onclick=async()=>{
  try{const r=state.runtime;if(!r.docker_installed){window.open('https://docs.docker.com/desktop/setup/install/mac-install/','_blank','noopener,noreferrer');return;}if(r.docker_ready&&r.image_ready){hideDialog('runtimeDialog');return;}preparationAttempted=true;await api('runtime/prepare',{method:'POST'});toast('已开始一键准备，就绪后会自动继续。');await refresh();}catch(e){toast(e.message,true);}
};
$('exitBrowser').onclick=()=>{$('browserView').hidden=true;$('browserFrame').src='about:blank';activeId=null;document.body.style.overflow='';refresh();};
$('reconnectBrowser').onclick=async()=>{try{await openBrowser(activeId);}catch(e){toast(e.message,true);}};
$('addressForm').onsubmit=async e=>{e.preventDefault();try{await browserAction('navigate',{url:$('browserAddress').value});}catch(error){toast(error.message,true);}};
$('toggleTextInput').onclick=()=>$('browserTextPanel').hidden=!$('browserTextPanel').hidden;
$('sendBrowserText').onclick=async()=>{try{$('sendBrowserText').disabled=true;await browserAction('paste',{text:$('browserText').value});$('browserText').value='';toast('文字已发送到浏览器输入框。');}catch(e){toast(e.message,true);}finally{$('sendBrowserText').disabled=false;}};
$('copySelection').onclick=async()=>{try{const r=await browserAction('copy');if(!r.text){toast('请先在远程网页中选中文字。');return;}await navigator.clipboard.writeText(r.text);toast('选中文字已复制。');}catch(e){toast(e.message,true);}};
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
  $('transferEnvironment').textContent=state.environments.find(e=>e.id===activeId)?.name||'';
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
      $('browserTextPanel').hidden=false;$('browserText').focus();toast('浏览器未开放剪贴板读取。请在文字框里按 ⌘V，再点“发送到输入框”。');
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
    if(copy){await navigator.clipboard.writeText(copy.dataset.copyFilePath);toast('环境路径已复制。在文件窗口按 Ctrl+L，然后粘贴。');}
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
  let write;
  try{
    if(navigator.clipboard?.write&&typeof ClipboardItem!=='undefined'){
      // The write starts during the user's gesture; only the payload is delayed.
      write=navigator.clipboard.write([new ClipboardItem({'text/plain':text.then(value=>new Blob([value],{type:'text/plain'}))})]);
    }else{write=text.then(value=>navigator.clipboard.writeText(value));}
  }catch(error){write=Promise.reject(error);}
  write.then(()=>toast('已复制到主电脑，可以在外面按 ⌘V 粘贴。')).catch(async error=>{
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
const planNames={unknown:'待核实',free:'Free',pro:'Pro',max:'Max',team:'Team',enterprise:'Enterprise'};
const accountStatusNames={unknown:'待核实',active:'可用',blocked:'已封禁 / 停用',logged_out:'未登录'};
function accountPill(account){const a=account||{};return `<span class="account-pill ${a.status==='blocked'?'blocked':a.plan&&a.plan!=='unknown'?'known':'unknown'}">${esc(a.status==='blocked'?'已封禁':planNames[a.plan]||'待核实')}</span>`;}
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
    return `<article id="info-${e.id}" class="information-card"><div class="information-card-heading"><div><h2>${esc(e.name)}</h2><small>${esc(nodes.get(e.node_id)?.name||'无代理测试 / 未绑定线路')}</small></div><span class="status-pill ${esc(x.status)}">${({running:'运行中',paused:'低功耗',starting:'启动中',error:'需要重试',stopped:'已停止'})[x.status]||'未知'}</span></div><div class="account-line">${accountPill(a)}<strong>${esc(a.label||'账号未备注')}</strong><span>${esc(accountStatusNames[a.status]||'待核实')}</span></div><div class="account-record">${esc(recordSource(a))} · ${esc(last)}${a.last_attempt&&!a.verified?'<br>最近一次核对未确认，以上为已有记录。':''}</div><div class="resource-meter"><div><span>CPU</span><strong>${cpu==null?'待采样':cpu.toFixed(2)+' 核'} <small>/ ${cpuLimit} 核</small></strong></div><progress max="${cpuLimit}" value="${cpu||0}"></progress></div><div class="resource-meter"><div><span>内存${x.memory_stale?' · 上次采样':''}</span><strong>${gigabytes(memory)} <small>/ ${gigabytes(memLimit)}</small></strong></div><progress max="${memLimit}" value="${memory||0}"></progress></div>${paused?'<p class="paused-note">浏览器已暂停，内存仍保留。打开时会唤醒。</p>':''}<div class="information-actions"><button class="button secondary small" data-manage="account" data-id="${e.id}">账号信息</button><button class="button secondary small" data-manage="limits" data-id="${e.id}" ${busy?'disabled':''}>资源额度</button>${started?`<button class="button secondary small" data-manage="${paused?'resume':'pause'}" data-id="${e.id}" ${busy?'disabled':''}>${paused?'唤醒环境':'低功耗'}</button><button class="text-button" data-manage="stop" data-id="${e.id}" ${busy?'disabled':''}>停止</button>`:''}<button class="button primary small" data-manage="open" data-id="${e.id}" ${busy?'disabled':''}>${paused?'唤醒并打开':started?'打开':'启动'}</button></div></article>`;
  }).join(''):'<div class="nodes-empty">新建环境后，可在这里查看账号与资源信息。</div>';
}
function setLimitInputBounds(cpuId,memoryId){const r=state.resources?.engine||{};$(cpuId).max=r.cpu_count||64;$(memoryId).max=r.memory_mb?Math.floor((r.memory_mb-512)/256)/4:256;}
function showLimits(id){const e=state.environments.find(e=>e.id===id);if(!e)return;limitsEnvironmentId=id;$('limitsEnvironmentName').textContent=e.name;$('cpuLimitInput').value=e.cpu_limit||2;$('memoryLimitInput').value=(e.memory_limit_mb||2048)/1024;setLimitInputBounds('cpuLimitInput','memoryLimitInput');showDialog('limitsDialog');}
function showAccount(id){const e=state.environments.find(e=>e.id===id);if(!e)return;accountEnvironmentId=id;const a=e.account||{};$('accountEnvironmentName').textContent=e.name;$('accountLabelInput').value=a.label||'';$('accountPlanInput').value=a.plan||'unknown';$('accountStatusInput').value=a.status||'unknown';updateAccountEvidence(e);showDialog('accountDialog');}
function updateAccountEvidence(e){const a=e.account||{};$('accountEvidence').textContent=`${recordSource(a)}${a.checked_at?' · '+new Date(a.checked_at*1000).toLocaleString():''}${a.note?'。'+a.note:''}`;$('checkAccount').disabled=checkingAccount||e.runtime.status!=='running'||e.runtime.account_checking;$('checkAccount').textContent=checkingAccount?'正在核对，请暂不操作浏览器…':e.runtime.status==='paused'?'请先唤醒环境再核对':e.runtime.status!=='running'?'请先启动环境并登录 Claude':'核对当前账号 ↗';}
$('resourceSettings').onclick=()=>{$('maxRunningInput').value=state.runtime.max_running||2;const r=state.resources||{};$('resourceSettingsHint').textContent=`当前已启动 ${r.occupied||0} 个，可分配内存 ${gigabytes(r.memory_budget_mb)}。CPU 和内存额度在每个环境的“资源额度”里设置。`;showDialog('resourceSettingsDialog');};
$('resourceSettingsForm').onsubmit=async event=>{event.preventDefault();$('saveResourceSettings').disabled=true;try{await api('resources/settings',{method:'PATCH',body:{max_running:Number($('maxRunningInput').value)}});hideDialog('resourceSettingsDialog');await refresh();toast('同时运行上限已保存。');}catch(e){toast(e.message,true);}finally{$('saveResourceSettings').disabled=false;}};
$('limitsForm').onsubmit=async event=>{event.preventDefault();$('saveLimits').disabled=true;try{await api(`environments/${limitsEnvironmentId}/resources`,{method:'PATCH',body:{cpu_limit:Number($('cpuLimitInput').value),memory_limit_mb:Math.round(Number($('memoryLimitInput').value)*1024)}});hideDialog('limitsDialog');await refresh();toast('资源额度已保存。');}catch(e){toast(e.message,true);}finally{$('saveLimits').disabled=false;}};
$('accountForm').onsubmit=async event=>{event.preventDefault();$('saveAccount').disabled=true;try{await api(`environments/${accountEnvironmentId}/account`,{method:'PATCH',body:{label:$('accountLabelInput').value,plan:$('accountPlanInput').value,status:$('accountStatusInput').value}});await refresh();updateAccountEvidence(state.environments.find(e=>e.id===accountEnvironmentId));toast('账号信息已保存为手动记录。');}catch(e){toast(e.message,true);}finally{$('saveAccount').disabled=false;}};
$('checkAccount').onclick=async()=>{if(checkingAccount)return;const checkedId=accountEnvironmentId;checkingAccount=true;$('saveAccount').disabled=true;updateAccountEvidence(state.environments.find(e=>e.id===accountEnvironmentId));try{const result=await api(`environments/${checkedId}/account/check`,{method:'POST'});await refresh();const e=state.environments.find(e=>e.id===checkedId);if(accountEnvironmentId===checkedId&&e){$('accountPlanInput').value=e.account.plan||'unknown';$('accountStatusInput').value=e.account.status||'unknown';}toast(result.verified?'账号信息已核对。':'未能确认，已保留上次记录；可以手动标记。',!result.verified);}catch(e){toast(e.message,true);}finally{checkingAccount=false;$('saveAccount').disabled=false;const e=state.environments.find(e=>e.id===accountEnvironmentId);if(e)updateAccountEvidence(e);}};
document.addEventListener('click',async event=>{const button=event.target.closest('[data-manage]');if(!button)return;const id=button.dataset.id,kind=button.dataset.manage;try{if(kind==='account'){showAccount(id);return;}if(kind==='limits'){showLimits(id);return;}button.disabled=true;if(kind==='pause'||kind==='resume'||kind==='stop'){await api(`environments/${id}/${kind}`,{method:'POST'});toast(kind==='pause'?'环境已进入低功耗，内存仍保留。':kind==='resume'?'环境已唤醒。':'环境已停止，内存已释放。');await refresh();return;}if(kind==='open'){const e=state.environments.find(e=>e.id===id);if(e.runtime.status==='paused'){await api(`environments/${id}/resume`,{method:'POST'});pendingOpen=id;await refresh();}else if(e.runtime.status==='running')await openBrowser(id);else if(e.node_id)await startEnvironment(id);else{editEnvironment(id);$('autoOpenOption').hidden=false;$('autoOpen').checked=true;toast('请绑定线路，或明确勾选无代理测试。');}}}catch(e){toast(e.message,true);}finally{button.disabled=false;}});
