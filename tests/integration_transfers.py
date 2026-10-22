"""Actual clipboard + upload + download verification, disposable local fixtures only."""
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import sys
import tempfile
import threading
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
from fastapi.testclient import TestClient
from workbench.app import create_app

PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=')
PAYLOAD=('从浏览器下载到主电脑。\n'.encode()*1000)+bytes(range(256))
records=[]


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*_): pass
    def do_POST(self):
        raw=self.rfile.read(int(self.headers.get('content-length','0')))
        records.append(json.loads(raw))
        self.send_response(200);self.end_headers();self.wfile.write(b'ok')
    def do_GET(self):
        if self.path=='/download':
            data=PAYLOAD
            self.send_response(200)
            self.send_header('Content-Type','application/octet-stream')
            self.send_header('Content-Disposition',"attachment; filename*=UTF-8''%E4%B8%8B%E8%BD%BD%E9%AA%8C%E6%94%B6.bin")
        else:
            data=b'''<!doctype html><meta charset="utf-8"><title>Transfer verification</title>
            <h1>Local transfer verification</h1><textarea id="input"></textarea>
            <input id="file" type="file"><a href="/download">Download test file</a>
            <script>
            const report=x=>fetch('/report',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(x)});
            input.oninput=()=>report({type:'text',value:input.value});
            input.onpaste=e=>{const f=e.clipboardData.files[0];if(f){e.preventDefault();const reader=new FileReader();reader.onload=()=>report({type:'image',data:reader.result});reader.readAsDataURL(f);}};
            input.focus();report({type:'ready'});
            </script>'''
            self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8')
        self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)


def wait_for(predicate,timeout=25):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        value=predicate()
        if value:return value
        time.sleep(.2)
    raise AssertionError('Timed out waiting for local verification result')


def main():
    root=Path(__file__).resolve().parents[1]/'verification-data'
    root.mkdir(exist_ok=True)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    checks=[]
    with tempfile.TemporaryDirectory(dir=root) as tmp:
        app=create_app(Path(tmp));runtime=app.state.runtime;store=app.state.store
        with TestClient(app,base_url='http://127.0.0.1:8766') as client:
            token=re.search(r'name="workbench-token" content="([^"]+)"',client.get('/').text).group(1)
            headers={'X-Workbench-Token':token}
            try:
                for engine in ['firefox']:
                    env=store.create_environment('Disposable transfers '+engine,None,engine=engine)
                    identity=env['id'];base='/api/environments/'+identity+'/files'
                    def action(kind,**kwargs):
                        return httpx.post(runtime.worker_address(identity)+'/action',json={'kind':kind,**kwargs},headers={'X-Worker-Token':runtime.worker_secret(identity)},timeout=35,trust_env=False)
                    try:
                        runtime.start(identity,test_mode=True)
                        wait_for(lambda:runtime.state(identity)['status']=='running',130)
                        records.clear()
                        action('navigate',url=f'http://host.docker.internal:{server.server_port}/')
                        wait_for(lambda:any(r.get('type')=='ready' for r in records))
                        text='主电脑复制 → 浏览器粘贴：中文和 English。'
                        response=action('paste',text=text);assert response.status_code==200,response.text
                        wait_for(lambda:any(r.get('value')==text for r in records))
                        checks.append(engine+': real desktop text paste preserves Chinese')
                        image=client.post(base+'/upload',content=PNG,headers={**headers,'X-File-Name':'clipboard.png'})
                        assert image.status_code==200,image.text
                        assert client.get(base+'/incoming/'+image.json()['id'],headers=headers).content==PNG
                        checks.append(engine+': host upload reaches shared environment directory intact')
                        response=action('paste_image',name=image.json()['path'].split('/')[-1]);assert response.status_code==200,response.text
                        report=wait_for(lambda:next((r for r in records if r.get('type')=='image'),None))
                        assert base64.b64decode(report['data'].split(',',1)[1])==PNG
                        checks.append(engine+': PNG clipboard paste reaches the webpage intact')
                        action('navigate',url=f'http://host.docker.internal:{server.server_port}/download')
                        files=wait_for(lambda:client.get(base,headers=headers).json()['downloads'])
                        downloaded=client.get(base+'/downloads/'+files[0]['id'])
                        assert downloaded.status_code==200,downloaded.text
                        assert downloaded.content==PAYLOAD
                        checks.append(engine+': actual browser download is retrievable on host byte-for-byte')
                        runtime.stop(identity)
                        saved=client.get(base,headers=headers).json()['downloads']
                        assert saved and client.get(base+'/downloads/'+saved[0]['id']).content==PAYLOAD
                        checks.append(engine+': downloaded files survive stopping the environment')
                        print(engine+': five transfer checks passed',flush=True)
                    finally:
                        runtime.delete(identity)
            finally:
                server.shutdown();server.server_close()
                result={'checks':checks,'all_passed':len(checks)==5,'download_sha256':hashlib.sha256(PAYLOAD).hexdigest()}
                (root/'results-transfers.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
                print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
    assert len(checks)==5


if __name__=='__main__':main()
