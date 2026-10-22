// Runs only on our local noVNC surface; forward an explicit paste gesture.
const origin=location.origin;
function prepareCanvas(){
  document.querySelectorAll('canvas').forEach(canvas=>{
    canvas.contentEditable='true';
    canvas.setAttribute('inputmode','none');
    canvas.setAttribute('spellcheck','false');
  });
}
prepareCanvas();
new MutationObserver(prepareCanvas).observe(document.documentElement,{childList:true,subtree:true});
document.addEventListener('keydown',event=>{
  if((event.metaKey||event.ctrlKey)&&event.key.toLowerCase()==='v'&&!event.altKey){
    // Preserve the browser paste event instead of sending an old remote clipboard.
    event.stopImmediatePropagation();
  }
},true);
document.addEventListener('paste',event=>{
  const text=event.clipboardData?.getData('text/plain')||'';
  const files=Array.from(event.clipboardData?.files||[]);
  if(!text&&!files.length)return;
  event.preventDefault();event.stopImmediatePropagation();
  parent.postMessage({type:'workbench-paste',text,files},origin);
},true);

let desktopUI=null;
import(new URL('./app/ui.js',location.href).href).then(module=>{desktopUI=module.default;}).catch(()=>{});
function sendControlKey(key){
  const rfb=desktopUI?.rfb;
  if(!rfb)throw new Error('Remote desktop not connected');
  rfb.sendKey(0xffe3,'ControlLeft',true);
  rfb.sendKey(key.charCodeAt(0),'Key'+key.toUpperCase(),true);
  rfb.sendKey(key.charCodeAt(0),'Key'+key.toUpperCase(),false);
  rfb.sendKey(0xffe3,'ControlLeft',false);
}
document.addEventListener('keydown',event=>{
  const inDesktop=event.target.closest?.('#noVNC_container');
  if(!inDesktop)return;
  if(event.key==='Meta'){event.preventDefault();event.stopImmediatePropagation();return;}
  const key=event.key.toLowerCase();
  if((event.metaKey||event.ctrlKey)&&key==='c'&&!event.altKey){
    event.preventDefault();event.stopImmediatePropagation();
    parent.postMessage({type:'workbench-copy-shortcut'},origin);
  }else if(event.metaKey&&key==='a'){
    event.preventDefault();event.stopImmediatePropagation();
    try{sendControlKey('a');}catch{}
  }
},true);
window.addEventListener('message',event=>{
  if(event.origin!==origin||event.source!==parent||event.data?.type!=='workbench-copy-request')return;
  const id=event.data.id;
  try{
    sendControlKey('c');
    // Read after the browser has processed Ctrl+C. The parent uses an UTF-8
    // clipboard read, avoiding classic RFB clipboard text encoding limitations.
    setTimeout(()=>parent.postMessage({type:'workbench-copy-ready',id},origin),250);
  }catch{parent.postMessage({type:'workbench-copy-ready',id,error:true},origin);}
});
// Desktop app/browser menu accelerators can dispatch a native copy event
// without a keydown reaching the page. Handle that user gesture too.
document.addEventListener('copy',event=>{
  if(!document.activeElement?.closest?.('#noVNC_container'))return;
  event.preventDefault();event.stopImmediatePropagation();
  parent.postMessage({type:'workbench-copy-shortcut'},origin);
},true);
