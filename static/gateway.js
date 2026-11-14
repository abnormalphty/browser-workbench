'use strict';
// The 模型网关 page: settings for the local server in workbench/gateway.py. Loaded after app.js and uses its
// helpers ($, api, toast, esc, icon, showDialog, confirmStorage …). An API key never comes back from the
// backend in full; a program's own key goes straight to the clipboard when the user asks for it.
let gateway=null, gatewayParts={}, editingKey=null, editingClient=null, guideClient=null;
const keyStatus={ok:['running','可用'],invalid:['error','无效'],unreachable:['starting','未能验证'],unlisted:['starting','未验证']};
const providerOf=id=>gateway.providers.find(p=>p.id===id)||gateway.providers[0];
const groupTitle=group=>group.title||`${group.key.provider_name} · ${group.key.name}`;
const tokenCount=n=>n>=1e7?Math.round(n/1e6)+'M':n>=1e6?(n/1e6).toFixed(1)+'M':n>=1e4?Math.round(n/1e3)+'K':n>=1e3?(n/1e3).toFixed(1)+'K':String(n);
const stamp=seconds=>{if(!seconds)return'';const d=new Date(seconds*1000),two=v=>String(v).padStart(2,'0');return`${two(d.getMonth()+1)}-${two(d.getDate())} ${two(d.getHours())}:${two(d.getMinutes())}`;};
// The page refreshes every few seconds while it is open: a part is only redrawn when it changed, so a
// pointer over a button or a click in progress is not lost.
function paint(id,html){if(gatewayParts[id]!==html){gatewayParts[id]=html;$(id).innerHTML=html;}}
async function loadGateway(){gateway=await api('gateway');renderGateway();}
async function gatewayCall(path,options){const result=await api('gateway/'+path,options);if(result.keys){gateway=result;renderGateway();}return result;}
const guideCommand=key=>onWindows?`$env:ANTHROPIC_BASE_URL="${gateway.address}"; $env:ANTHROPIC_AUTH_TOKEN="${key}"; claude`:`ANTHROPIC_BASE_URL=${gateway.address} ANTHROPIC_AUTH_TOKEN=${key} claude`;
const clientKey=id=>api(`gateway/clients/${id}/token`,{method:'POST'}).then(result=>result.token);

// text may be a promise (a key fetched for this copy): in a browser the write has to start during the
// click, so only the payload waits. When the browser refuses, the text is shown selected instead.
function copyLater(text,done){
  const value=Promise.resolve(text);let write;
  try{
    if(native)write=value.then(copyText);
    else if(window.ClipboardItem&&navigator.clipboard?.write)write=navigator.clipboard.write([new ClipboardItem({'text/plain':value.then(v=>new Blob([v],{type:'text/plain'}))})]);
    else write=value.then(v=>navigator.clipboard.writeText(v));
  }catch(error){write=Promise.reject(error);}
  return write.then(()=>toast(done)).catch(async error=>{
    try{
      const dialog=$('copyFallbackDialog'),title=dialog.querySelector('h2'),before=title.textContent;
      title.textContent='手动复制';dialog.addEventListener('close',()=>title.textContent=before,{once:true});
      $('copyFallbackText').value=await value;showDialog('copyFallbackDialog');$('copyFallbackText').focus();$('copyFallbackText').select();
    }catch(failure){toast(failure.message||error.message,true);}
  });
}

function usageLine(label,u){
  if(!u||!u.requests)return`<span>${label}还没有请求</span>`;
  return`<span>${label} <strong>${u.requests.toLocaleString()}</strong> 次 · 输入 ${tokenCount(u.input+u.cache_read+u.cache_write)} · 输出 ${tokenCount(u.output)}${u.errors?` · <em>${u.errors} 次没成功</em>`:''}</span>`;
}
function renderGateway(){
  if(!gateway)return;
  const g=gateway,on=g.enabled,up=on&&g.running;
  $('gatewayAddress').textContent=g.address;
  $('gatewayPill').className='status-pill'+(up?' running':on?' error':'');$('gatewayPill').textContent=up?'运行中':on?'没有运行':'已关闭';
  $('gatewayToggle').textContent=on?'关闭网关':'开启网关';$('gatewayToggle').className='button '+(on?'secondary':'primary');
  $('gatewayNote').textContent=up?'只有这台电脑上的程序能连接。工作台开着，网关才在运行。':'开启后，其他程序把接口地址填成这个地址，就能通过网关使用你添加了 API 密钥的模型。';
  $('gatewayError').hidden=!g.error;$('gatewayError').textContent=g.error||'';
  $('gatewayKeyCount').textContent=g.keys.length;$('gatewayClientCount').textContent=g.clients.length;
  paint('gatewayKeys',g.keys.length?g.keys.map(k=>{
    const [kind,label]=keyStatus[k.status]||keyStatus.ok,count=k.models.length+k.manual_models.length;
    const where=k.provider==='custom'&&k.base_url?` · ${esc(hostOf(k.base_url)||k.base_url)}`:'';
    return`<div class="gateway-row"><div class="gateway-row-main"><strong>${esc(k.name)}<span class="gateway-provider">${esc(k.provider_name)}</span>${k.default?'<span class="account-pill known">默认</span>':''}</strong><small><code>${esc(k.hint)}</code>${where}${count?` · ${count} 个模型`:''}${k.checked_at?' · 上次检查 '+stamp(k.checked_at):''}</small></div><span class="status-pill ${kind}">${label}</span><div class="gateway-row-actions"><button class="button secondary small" data-key-check="${k.id}">检查</button>${k.default?'':`<button class="button secondary small" data-key-default="${k.id}">设为默认</button>`}<button class="icon-button" data-key-rename="${k.id}" aria-label="修改名称和模型" title="修改名称和模型">${icon('edit')}</button><button class="icon-button" data-key-delete="${k.id}" aria-label="删除 API 密钥" title="删除">${icon('trash')}</button></div></div>`;
  }).join(''):'<div class="gateway-empty"><p>还没有 API 密钥。在 Claude Console、OpenAI、DeepSeek 等平台创建 API 密钥（按用量计费），再添加到这里。</p><button class="text-button" data-add-key>添加 API 密钥</button></div>');
  paint('gatewayClients',g.clients.map(c=>{
    const keyName=g.keys.find(k=>k.id===c.key_id)?.name||'自动选择 API 密钥';
    const models=c.mode==='fixed'?`固定使用 <code>${esc(c.default_model)}</code>`:c.models.length?`可选 ${c.models.length} 个模型：${c.models.map(m=>`<code>${esc(m)}</code>`).join(' ')}`:'可以用全部模型';
    return`<article class="information-card gateway-client${c.enabled?'':' disabled'}"><div class="information-card-heading"><div><h2>${esc(c.name)}</h2><small><code>${esc(c.hint)}</code> · ${esc(keyName)}</small></div><span class="status-pill${c.enabled?' running':''}">${c.enabled?'可用':'已停用'}</span></div><p class="gateway-models">${models}</p><div class="gateway-usage">${usageLine('今天',c.usage?.today)}${usageLine('近 30 天',c.usage?.month)}</div><div class="information-actions"><button class="button secondary small" data-client-copy="${c.id}">${icon('copy')}复制密钥</button><button class="button secondary small" data-client-guide="${c.id}">接入方法</button><button class="text-button" data-client-edit="${c.id}">编辑</button><button class="text-button" data-client-toggle="${c.id}">${c.enabled?'停用':'启用'}</button><button class="text-button" data-client-rotate="${c.id}">更换密钥</button><button class="text-button danger" data-client-delete="${c.id}">删除</button></div></article>`;
  }).join(''));
  $('gatewayClients').hidden=!g.clients.length;$('gatewayClientsEmpty').hidden=!!g.clients.length;
}

// ---------- API keys ----------
// A new key is for one service; an existing one only gets a new name and the models typed in for it.
function providerChanged(){
  const p=providerOf($('gatewayKeyProvider').value),custom=p.id==='custom';
  $('gatewayKeyCustom').hidden=!custom;$('gatewayKeyCopy').hidden=custom||!p.console;
  $('gatewayKeyCopyText').textContent=`在 ${p.name} 的控制台创建 API 密钥，按实际用量计费。`;
  $('gatewayKeySecret').placeholder=custom?'本机的服务不需要密钥时可以不填':p.example||'API 密钥';$('gatewayKeySecret').required=!custom;
}
function openKeyDialog(key=null){
  editingKey=key;
  $('gatewayKeyTitle').textContent=key?`编辑 ${key.provider_name} 的 API 密钥`:'添加 API 密钥';
  $('gatewayKeyProviderField').hidden=$('gatewayKeySecretField').hidden=$('gatewayKeyNote').hidden=!!key;
  if(key){$('gatewayKeyCopy').hidden=$('gatewayKeyCustom').hidden=true;$('gatewayKeySecret').required=false;}
  else{
    $('gatewayKeyProvider').innerHTML=gateway.providers.map(p=>`<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('');
    $('gatewayKeyProvider').value=gateway.keys.some(k=>k.provider==='anthropic')?'openai':'anthropic';$('gatewayKeyBase').value='';providerChanged();
  }
  $('gatewayKeyName').value=key?key.name:'';$('gatewayKeySecret').value='';$('gatewayKeyModels').value=key?key.manual_models.join('\n'):'';
  $('saveGatewayKey').textContent=key?'保存':'验证并保存';$('gatewayKeyError').hidden=true;
  showDialog('gatewayKeyDialog');(key?$('gatewayKeyName'):$('gatewayKeyProvider')).focus();
}
$('gatewayKeyProvider').onchange=providerChanged;
$('gatewayKeyForm').onsubmit=async event=>{
  event.preventDefault();
  const save=$('saveGatewayKey'),error=$('gatewayKeyError'),label=save.textContent,provider=$('gatewayKeyProvider').value;
  save.disabled=true;error.hidden=true;if(!editingKey)save.textContent='正在验证…';
  try{
    const result=editingKey?await gatewayCall('keys/'+editingKey.id,{method:'PATCH',body:{name:$('gatewayKeyName').value,models:$('gatewayKeyModels').value}})
      :await gatewayCall('keys',{method:'POST',body:{name:$('gatewayKeyName').value,secret:$('gatewayKeySecret').value,provider,models:$('gatewayKeyModels').value,
        ...(provider==='custom'?{base_url:$('gatewayKeyBase').value,api:document.querySelector('input[name="gatewayKeyApi"]:checked').value}:{})}});
    $('gatewayKeySecret').value='';hideDialog('gatewayKeyDialog');
    toast(result.notice||(editingKey?'已保存。':'API 密钥已验证并保存。'));
  }catch(e){error.textContent=e.message;error.hidden=false;}
  finally{save.disabled=false;save.textContent=label;}
};

// ---------- a key for each program ----------
function showMode(mode){$('gatewayChoice').hidden=mode!=='choice';$('gatewayFixed').hidden=mode!=='fixed';}
// The models of the chosen API key, or of every key (each model once, the default key's first), by key.
function modelGroups(keyId){
  const keys=keyId?gateway.keys.filter(k=>k.id===keyId):[...gateway.keys].sort((a,b)=>b.default-a.default),seen=new Set();
  return keys.map(key=>({key,models:[...key.models,...key.manual_models.map(id=>({id,display_name:id}))].filter(m=>!seen.has(m.id)&&seen.add(m.id))}))
    .filter(group=>group.models.length);
}
function renderModelChoices(chosen,fixed){
  const keyId=$('gatewayClientKey').value,groups=modelGroups(keyId),anywhere=new Set(modelGroups('').flatMap(g=>g.models.map(m=>m.id)));
  // A model the program was given earlier stays listed after its service retires it, so the setting shows as it is.
  const c=editingClient,saved=c?(c.mode==='fixed'?[c.default_model]:c.models):[];
  const older=[...new Set(saved)].filter(m=>m&&!anywhere.has(m));
  if(older.length)groups.push({title:'已不在模型列表里',models:older.map(id=>({id,display_name:id}))});
  const total=groups.reduce((n,g)=>n+g.models.length,0),titled=groups.length>1||!keyId;
  const option=m=>`<label class="model-option" data-find="${esc((m.id+' '+m.display_name).toLowerCase())}"><input type="checkbox" value="${esc(m.id)}"${chosen.includes(m.id)?' checked':''}><span>${esc(m.display_name)}</span>${m.display_name!==m.id?`<code>${esc(m.id)}</code>`:''}</label>`;
  $('gatewayModelList').innerHTML=total?groups.map(g=>(titled?`<div class="model-group-title">${esc(groupTitle(g))}</div>`:'')+g.models.map(option).join('')).join('')
    :'<p class="transfer-empty">添加并验证 API 密钥后，这里会列出可以用的模型。现在保存，表示全部模型都可以用。</p>';
  $('gatewayFixedModel').innerHTML=groups.map(g=>`<optgroup label="${esc(groupTitle(g))}">${g.models.map(m=>`<option value="${esc(m.id)}">${esc(m.display_name===m.id?m.id:`${m.display_name}（${m.id}）`)}</option>`).join('')}</optgroup>`).join('');
  if(fixed&&[...$('gatewayFixedModel').options].some(o=>o.value===fixed))$('gatewayFixedModel').value=fixed;
  $('gatewayModelFilter').hidden=total<=12;filterModels();
}
function filterModels(){
  const words=$('gatewayModelFilter').hidden?'':$('gatewayModelFilter').value.trim().toLowerCase();
  $('gatewayModelList').querySelectorAll('.model-option').forEach(o=>o.hidden=!!words&&!o.dataset.find.includes(words));
  $('gatewayModelList').querySelectorAll('.model-group-title').forEach(title=>{
    let next=title.nextElementSibling,shown=false;
    while(next&&!next.classList.contains('model-group-title')){shown||=!next.hidden;next=next.nextElementSibling;}
    title.hidden=!shown;
  });
}
$('gatewayModelFilter').oninput=filterModels;
function openClientDialog(client=null){
  editingClient=client;
  $('gatewayClientTitle').textContent=client?'编辑专属密钥':'新建专属密钥';$('saveGatewayClient').textContent=client?'保存':'创建';
  $('gatewayClientName').value=client?client.name:'';
  $('gatewayClientKey').innerHTML='<option value="">自动：按模型选择 API 密钥（默认的优先）</option>'+gateway.keys.map(k=>`<option value="${esc(k.id)}">${esc(k.name)}（${esc(k.provider_name)}）</option>`).join('');
  $('gatewayClientKey').value=gateway.keys.some(k=>k.id===client?.key_id)?client.key_id:'';
  const mode=client?.mode||'choice';
  document.querySelectorAll('input[name="gatewayMode"]').forEach(radio=>radio.checked=radio.value===mode);
  $('gatewayModelFilter').value='';
  renderModelChoices(client?.mode==='choice'?client.models:[],client?.mode==='fixed'?client.default_model:null);
  showMode(mode);$('gatewayClientError').hidden=true;
  showDialog('gatewayClientDialog');$('gatewayClientName').focus();
}
// Another API key: the models chosen so far stay chosen.
$('gatewayClientKey').onchange=()=>renderModelChoices([...$('gatewayModelList').querySelectorAll('input:checked')].map(input=>input.value),$('gatewayFixedModel').value||null);
document.querySelectorAll('input[name="gatewayMode"]').forEach(radio=>radio.onchange=()=>showMode(radio.value));
$('gatewayClientForm').onsubmit=async event=>{
  event.preventDefault();
  const save=$('saveGatewayClient'),error=$('gatewayClientError'),mode=document.querySelector('input[name="gatewayMode"]:checked').value;
  const body={name:$('gatewayClientName').value,key_id:$('gatewayClientKey').value||null,mode,
    models:mode==='choice'?[...$('gatewayModelList').querySelectorAll('input:checked')].map(input=>input.value):[],
    default_model:mode==='fixed'?$('gatewayFixedModel').value||null:null};
  save.disabled=true;error.hidden=true;
  try{
    if(editingClient){await gatewayCall('clients/'+editingClient.id,{method:'PATCH',body});hideDialog('gatewayClientDialog');toast('专属密钥的设置已保存。');}
    else{const result=await gatewayCall('clients',{method:'POST',body});hideDialog('gatewayClientDialog');openGuide(result.client_id);}
  }catch(e){error.textContent=e.message;error.hidden=false;}
  finally{save.disabled=false;}
};
function openGuide(id){
  const client=gateway.clients.find(c=>c.id===id);if(!client)return;
  guideClient=client;
  $('guideClientName').textContent=client.name;
  $('guideAnthropic').textContent=gateway.address;$('guideOpenai').textContent=gateway.address+'/v1';$('guideKey').textContent=client.hint;
  $('guideCommand').textContent=guideCommand(client.hint);
  $('guideTerminal').textContent=onWindows?'在 PowerShell 里运行下面这一行':'在“终端”里运行下面这一行';
  $('guideOff').hidden=gateway.enabled&&gateway.running;
  showDialog('gatewayGuideDialog');
}
$('gatewayGuideDialog').addEventListener('click',event=>{
  const what=event.target.closest('[data-guide-copy]')?.dataset.guideCopy;if(!what)return;
  if(what==='key')copyLater(clientKey(guideClient.id),'专属密钥已复制，可以粘贴到程序里。');
  else if(what==='command')copyLater(clientKey(guideClient.id).then(guideCommand),'命令已复制（带着专属密钥），粘贴到终端里运行。');
  else copyLater(what==='openai'?gateway.address+'/v1':gateway.address,'地址已复制。');
});

// ---------- the page ----------
$('gatewayPage').addEventListener('click',async event=>{
  const button=event.target.closest('button');if(!button||!gateway)return;
  const d=button.dataset,key=gateway.keys.find(k=>k.id===(d.keyCheck||d.keyDefault||d.keyRename||d.keyDelete)),
    client=gateway.clients.find(c=>c.id===(d.clientCopy||d.clientGuide||d.clientEdit||d.clientToggle||d.clientRotate||d.clientDelete));
  try{
    if('addKey' in d)openKeyDialog();
    else if(d.keyCheck){
      button.disabled=true;button.textContent='检查中…';
      try{toast((await gatewayCall(`keys/${key.id}/check`,{method:'POST'})).notice);}
      catch(e){await loadGateway();throw e;}
      finally{button.disabled=false;button.textContent='检查';}
    }
    else if(d.keyDefault){await gatewayCall('keys/'+key.id,{method:'PATCH',body:{default:true}});toast(`“${key.name}”已设为默认 API 密钥。`);}
    else if(d.keyRename)openKeyDialog(key);
    else if(d.keyDelete)confirmStorage('删除 API 密钥',`删除“${key.name}”后，只用它的专属密钥会改为自动选择 API 密钥。API 密钥本身不在设置历史里，以后要用需要重新添加。`,'删除','danger',async()=>{await gatewayCall('keys/'+key.id,{method:'DELETE'});hideDialog('confirmDialog');toast('API 密钥已删除。');});
    else if(d.clientCopy)copyLater(clientKey(client.id),'专属密钥已复制，可以粘贴到程序里。');
    else if(d.clientGuide)openGuide(client.id);
    else if(d.clientEdit)openClientDialog(client);
    else if(d.clientToggle){await gatewayCall('clients/'+client.id,{method:'PATCH',body:{enabled:!client.enabled}});toast(client.enabled?`“${client.name}”已停用，用这把密钥的请求会被拒绝。`:`“${client.name}”已启用。`);}
    else if(d.clientRotate)confirmStorage('更换专属密钥',`更换后，“${client.name}”现在的密钥立刻失效，用它的程序要换上新密钥才能继续。`,'更换并复制新密钥','primary',async()=>{const result=await gatewayCall(`clients/${client.id}/rotate`,{method:'POST'});hideDialog('confirmDialog');copyLater(result.token,'已更换，新密钥已复制。');});
    else if(d.clientDelete)confirmStorage('删除专属密钥',`删除后，用“${client.name}”这把密钥的程序不能再通过网关使用 Claude。可以在“设置历史”里恢复。`,'删除','danger',async()=>{await gatewayCall('clients/'+client.id,{method:'DELETE'});hideDialog('confirmDialog');toast('专属密钥已删除。');});
  }catch(e){toast(e.message,true);}
});
$('gatewayToggle').onclick=async()=>{
  if(!gateway)return;
  if(!gateway.enabled&&!gateway.keys.length){openKeyDialog();toast('先添加一个 API 密钥，再开启网关。');return;}
  $('gatewayToggle').disabled=true;
  try{
    await gatewayCall('settings',{method:'PATCH',body:{enabled:!gateway.enabled}});
    if(!gateway.enabled)toast('网关已关闭。');else if(gateway.running)toast('网关已开启。');else toast(gateway.error||'网关没有启动。',true);
  }catch(e){toast(e.message,true);}
  finally{$('gatewayToggle').disabled=false;}
};
$('copyGatewayAddress').onclick=()=>gateway&&copyLater(gateway.address,'地址已复制。');
$('addGatewayKey').onclick=()=>gateway&&openKeyDialog();
$('addGatewayClient').onclick=()=>gateway&&openClientDialog();
$('openConsole').onclick=()=>{const p=providerOf($('gatewayKeyProvider').value);if(p.console)openExternal(p.console);};

// ---------- settings and history ----------
function modelsSummary(){$('gatewayModelsSummary').textContent=gateway.models.length?`已读到 ${gateway.models.length} 个模型${gateway.models_checked_at?'，更新于 '+stamp(gateway.models_checked_at):''}`:'还没有读到模型列表';}
$('gatewaySettings').onclick=()=>{
  if(!gateway)return;
  $('gatewayPort').value=gateway.port;$('gatewayProxy').value=gateway.proxy;$('gatewaySettingsError').hidden=true;modelsSummary();
  showDialog('gatewaySettingsDialog');
};
$('gatewaySettingsForm').onsubmit=async event=>{
  event.preventDefault();
  const save=$('saveGatewaySettings'),error=$('gatewaySettingsError');save.disabled=true;error.hidden=true;
  try{
    await gatewayCall('settings',{method:'PATCH',body:{port:Number($('gatewayPort').value),proxy:$('gatewayProxy').value}});
    hideDialog('gatewaySettingsDialog');toast(gateway.error||'网关设置已保存。',!!gateway.error);
  }catch(e){error.textContent=e.message;error.hidden=false;}
  finally{save.disabled=false;}
};
$('refreshGatewayModels').onclick=async()=>{
  const button=$('refreshGatewayModels');button.disabled=true;
  try{toast((await gatewayCall('models/refresh',{method:'POST'})).notice);modelsSummary();}
  catch(e){toast(e.message,true);}
  finally{button.disabled=false;}
};
function renderHistory(){
  $('gatewayHistoryList').innerHTML=gateway.history.length?gateway.history.map(entry=>`<div class="transfer-file"><div><strong>${esc(entry.summary)}</strong><small>${stamp(entry.at)}</small></div>${entry.index?`<button class="button secondary small" data-restore="${entry.index}">回到这一步</button>`:'<span class="history-current">现在的设置</span>'}</div>`).join('')
    :'<div class="transfer-empty">还没有修改过网关设置。</div>';
}
$('gatewayHistory').onclick=()=>{if(!gateway)return;renderHistory();showDialog('gatewayHistoryDialog');};
$('gatewayHistoryList').addEventListener('click',async event=>{
  const button=event.target.closest('[data-restore]');if(!button)return;
  button.disabled=true;
  try{const result=await gatewayCall(`history/${button.dataset.restore}/restore`,{method:'POST'});renderHistory();toast(result.notice);}
  catch(e){button.disabled=false;toast(e.message,true);}
});
// Request counts move while programs use the gateway.
setInterval(()=>{if(currentPage==='gateway'&&!document.hidden&&!document.querySelector('dialog[open]'))loadGateway().catch(()=>{});},6000);
