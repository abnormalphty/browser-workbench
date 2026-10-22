import asyncio
import json
import os
from pathlib import Path
import secrets
import re
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
import httpx

from .runtime import ROOT, Runtime
from .store import Store
from .transfers import Transfers, MAX_UPLOAD
from .subscriptions import fetch_subscription, parse_subscription


def create_app(data_dir: Path | None = None):
    data_dir = data_dir or Path(os.environ.get('WORKBENCH_DATA_DIR', ROOT / 'data'))
    store = Store(data_dir)
    runtime = Runtime(store)
    token = secrets.token_urlsafe(32)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store, app.state.runtime = store, runtime
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost'])

    @app.middleware('http')
    async def protect(request, call_next):
        try:
            upload = request.method == 'POST' and re.fullmatch(r'/api/environments/[a-f0-9]{32}/files/upload', request.url.path)
            limit = MAX_UPLOAD if upload else 65536
            if int(request.headers.get('content-length', '0')) > limit:
                return JSONResponse({'error':'请求内容过大。'}, status_code=413)
        except ValueError:
            return JSONResponse({'error':'请求格式不正确。'}, status_code=400)
        if request.url.path.startswith(('/api/', '/view/')):
            origin = request.headers.get('origin')
            expected_origin = str(request.base_url).rstrip('/')
            if origin and origin != expected_origin:
                return JSONResponse({'error':'仅允许从本机工作台操作。'}, status_code=403)
            if not secrets.compare_digest(request.cookies.get('workbench_session', ''), token):
                return JSONResponse({'error':'请重新打开本机工作台。'}, status_code=403)
            attachment = request.method == 'GET' and re.fullmatch(r'/api/environments/[a-f0-9]{32}/files/(incoming|downloads)/[A-Za-z0-9_-]+', request.url.path)
            if request.url.path.startswith('/api/') and not attachment and not secrets.compare_digest(request.headers.get('X-Workbench-Token', ''), token):
                return JSONResponse({'error':'操作校验失败，请刷新工作台。'}, status_code=403)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Cache-Control'] = 'no-store'
        # The packaged noVNC entry point has a small inline module bootstrap.
        script_policy = "'self' 'unsafe-inline'" if request.url.path.startswith('/view/') else "'self'"
        response.headers['Content-Security-Policy'] = f"default-src 'self'; script-src {script_policy}; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self' ws://127.0.0.1:* ws://localhost:*; frame-src 'self'; frame-ancestors 'self'"
        return response

    @app.exception_handler(ValueError)
    async def value_error(request, exc):
        return JSONResponse({'error':str(exc)}, status_code=400)

    async def body(request):
        raw = await request.body()
        if len(raw) > 65536:
            raise ValueError('请求内容过大。')
        try:
            data = json.loads(raw or '{}')
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise ValueError('请求格式不正确。') from exc
        if not isinstance(data, dict):
            raise ValueError('请求必须是对象。')
        return data

    def text(data, key, default=''):
        value = data.get(key, default)
        if not isinstance(value, str):
            raise ValueError('输入内容格式不正确。')
        return value

    def node_id(data):
        value = data.get('node_id')
        if value is not None:
            store.valid_id(value)
        return value

    def public_environment(env):
        return {k:v for k,v in env.items() if k != 'fingerprint_seed'}

    @app.get('/', response_class=HTMLResponse)
    def home():
        path = ROOT / 'static/index.html'
        html = path.read_text() if path.exists() else '<!doctype html><meta name="workbench-token" content="__TOKEN__"><title>本地浏览器工作台</title>'
        response = HTMLResponse(html.replace('__TOKEN__', token))
        response.set_cookie('workbench_session', token, httponly=True, samesite='strict', path='/')
        return response

    @app.get('/health')
    def health():
        return {'app':'browser-workbench', 'version':'0.6.1'}

    @app.get('/api/state')
    def state():
        result = store.public_state()
        result['runtime'] = runtime.status()
        from .geography import PLACES
        result['geography'] = {'progress':dict(runtime.geography.progress),'places':list(PLACES.values())}
        result['resources']=runtime.resource_overview()
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=8) as pool:
            statuses=list(pool.map(lambda env:runtime.state(env['id']),result['environments']))
        for env,status in zip(result['environments'],statuses):env['runtime']=status
        return result

    @app.post('/api/subscription')
    async def subscription(request: Request):
        data = await body(request)
        url = text(data, 'url').strip() or store.get_subscription_url()
        if not url:
            raise ValueError('请填写机场订阅链接。')
        content = await fetch_subscription(url)
        nodes = parse_subscription(content)
        store.save_subscription(url, nodes)
        return {'ok':True, 'count':len(store.public_state()['nodes'])}

    @app.post('/api/environments')
    async def create_environment(request: Request):
        data = await body(request)
        from .resources import validate_limits
        limits=validate_limits(data);await asyncio.to_thread(runtime._validate_capacity,limits)
        return public_environment(store.create_environment(text(data,'name'),node_id(data),engine=text(data,'engine','firefox'),**limits))

    @app.patch('/api/environments/{env_id}')
    async def update_environment(env_id: str, request: Request):
        store.get_environment(env_id)
        if env_id in runtime.jobs and runtime.jobs[env_id].is_alive():
            raise ValueError('请等待环境启动完成，再停止并编辑。')
        if (await asyncio.to_thread(runtime.state,env_id))['status'] not in ('stopped','error'):
            raise ValueError('请先停止环境，再修改名称或绑定节点。')
        data = await body(request)
        if 'engine' in data and data['engine'] != store.get_environment(env_id)['engine']:
            raise ValueError('浏览器类型创建后不能更换，请新建独立环境。')
        return public_environment(store.update_environment(env_id, text(data,'name'), node_id(data)))

    @app.delete('/api/environments/{env_id}')
    def delete_environment(env_id: str, confirm: str = ''):
        if confirm != env_id:
            raise ValueError('删除会清除环境数据，需要确认。')
        runtime.delete(env_id)
        return {'ok':True}

    @app.post('/api/environments/{env_id}/start')
    async def start_environment(env_id: str, request: Request):
        store.get_environment(env_id)
        data = await body(request)
        test_mode = data.get('test_mode', False)
        if not isinstance(test_mode, bool):
            raise ValueError('测试模式必须为 true 或 false。')
        await asyncio.to_thread(runtime.start, env_id, test_mode)
        return {'ok':True, 'status':'starting'}

    @app.post('/api/environments/{env_id}/stop')
    def stop_environment(env_id: str):
        runtime.stop(env_id)
        return {'ok':True}

    @app.post('/api/environments/{env_id}/pause')
    def pause_environment(env_id: str):
        runtime.pause(env_id);return {'ok':True,'status':'paused'}

    @app.post('/api/environments/{env_id}/resume')
    def resume_environment(env_id: str):
        runtime.resume(env_id);return {'ok':True,'status':'running'}

    @app.patch('/api/environments/{env_id}/resources')
    async def environment_resources(env_id: str,request: Request):
        data=await body(request)
        return public_environment(await asyncio.to_thread(runtime.set_limits,env_id,data))

    @app.patch('/api/resources/settings')
    async def resource_settings(request: Request):
        return await asyncio.to_thread(runtime.set_max_running,await body(request))

    @app.patch('/api/environments/{env_id}/account')
    async def account_manual(env_id: str,request: Request):
        data=await body(request)
        def save_manual():
            with runtime.lock:
                runtime._not_checking(env_id)
                return store.save_account_info(env_id,data)
        return await asyncio.to_thread(save_manual)

    @app.post('/api/environments/{env_id}/account/check')
    async def account_check(env_id: str):
        from .accounts import check_account
        return await asyncio.to_thread(check_account,runtime,env_id)

    @app.post('/api/runtime/prepare')
    def prepare():
        runtime.build()
        return {'ok':True}

    @app.post('/api/runtime/open')
    def open_docker():
        runtime.build()
        return {'ok':True}

    @app.get('/api/environments/{env_id}/view')
    def view(env_id: str):
        store.get_environment(env_id)
        runtime.worker_address(env_id)
        return {'url':f'/view/{env_id}/vnc.html?autoconnect=1&resize=scale&path=view/{env_id}/websockify&password={runtime.view_secret(env_id)}&show_dot=1'}

    @app.post('/api/environments/{env_id}/action')
    async def action(env_id: str, request: Request):
        data = await body(request)
        runtime._not_checking(env_id)
        address = await asyncio.to_thread(runtime.worker_address, env_id)
        try:
            async with httpx.AsyncClient(timeout=32, trust_env=False) as client:
                r = await client.post(address+'/action', json=data, headers={'X-Worker-Token':runtime.worker_secret(env_id)})
            if r.status_code != 200:
                raise ValueError(r.json().get('detail','浏览器操作未完成。'))
            return r.json()
        except httpx.HTTPError as exc:
            raise ValueError('浏览器连接暂时中断，请重试。') from exc

    @app.post('/api/environments/{env_id}/clipboard')
    async def clipboard(env_id: str):
        store.get_environment(env_id)
        return {'text':await asyncio.to_thread(runtime.clipboard_text,env_id)}

    @app.post('/api/geography/probe')
    def probe_geography():
        runtime.geography.start_batch()
        return {'ok':True}

    @app.post('/api/nodes/{node_id}/location')
    async def set_location(node_id: str,request: Request):
        from .geography import PLACES,validate_location
        store.get_node(node_id)
        data=await body(request)
        place=PLACES.get(text(data,'place_id'))
        if not place:raise ValueError('请选择列表中的城市。')
        geo=validate_location({**place,'source':'manual'})
        store.set_setting('node_location:'+node_id,geo)
        return geo

    @app.get('/api/environments/{env_id}/files')
    def list_files(env_id: str):
        files = Transfers(store, env_id)
        return {kind:files.list(kind) for kind in ('incoming','downloads')}

    @app.post('/api/environments/{env_id}/files/upload')
    async def upload_file(env_id: str, request: Request):
        from urllib.parse import unquote
        files = Transfers(store, env_id)
        return await files.upload(unquote(request.headers.get('X-File-Name','')), request.stream())

    @app.get('/api/environments/{env_id}/files/{kind}/{identity}')
    def download_file(env_id: str, kind: str, identity: str):
        fd, size, disposition = Transfers(store, env_id).read(kind, identity)
        def chunks():
            with os.fdopen(fd, 'rb') as source:
                while block := source.read(1024*1024):
                    yield block
        return StreamingResponse(chunks(), media_type='application/octet-stream', headers={
            'Content-Disposition':disposition, 'Content-Length':str(size), 'X-Content-Type-Options':'nosniff',
            'Content-Security-Policy':"default-src 'none'; sandbox",
        })

    @app.post('/api/environments/{env_id}/files/open')
    async def open_files(env_id: str, request: Request):
        import subprocess
        data = await body(request)
        kind = text(data,'kind','downloads')
        files = Transfers(store, env_id)
        with files.directory(kind):
            subprocess.Popen(['open',str(files.path/kind)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {'ok':True}

    @app.websocket('/view/{env_id}/websockify')
    async def bridge(websocket: WebSocket, env_id: str):
        expected = 'http://' + websocket.headers.get('host', '')
        if websocket.headers.get('origin') != expected or not secrets.compare_digest(websocket.cookies.get('workbench_session',''),token):
            await websocket.close(code=1008)
            return
        tasks = []
        try:
            import websockets
            address = await asyncio.to_thread(runtime.worker_address, env_id, '6080/tcp')
            protocols = websocket.headers.get('sec-websocket-protocol','').split(',')
            protocol = 'binary' if 'binary' in [p.strip() for p in protocols] else None
            async with websockets.connect(address.replace('http://','ws://')+'/websockify', subprotocols=[protocol] if protocol else None, max_size=8*1024*1024, proxy=None) as remote:
                await websocket.accept(subprotocol=protocol)

                async def incoming():
                    while True:
                        message = await websocket.receive()
                        if message['type'] == 'websocket.disconnect':
                            return
                        await remote.send(message.get('bytes') if message.get('bytes') is not None else message.get('text',''))

                async def outgoing():
                    async for message in remote:
                        if isinstance(message, bytes):
                            await websocket.send_bytes(message)
                        else:
                            await websocket.send_text(message)

                tasks = [asyncio.create_task(incoming()), asyncio.create_task(outgoing())]
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for t in pending:
                    t.cancel()
                for t in done:
                    try:
                        t.result()
                    except Exception:
                        pass
        except Exception:
            try:
                await websocket.close(code=1011)
            except RuntimeError:
                pass
        finally:
            for t in tasks:
                if not t.done():
                    t.cancel()

    @app.get('/view/{env_id}/{asset:path}')
    async def view_asset(env_id: str, asset: str):
        if '..' in asset or asset.startswith('/') or not asset or '\\' in asset:
            return Response(status_code=404)
        address = await asyncio.to_thread(runtime.worker_address, env_id, '6080/tcp')
        try:
            async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
                response = await client.get(address+'/'+asset)
            if asset == 'vnc.html' and response.status_code == 200:
                html = response.text.replace('</body>', '<script src="/static/clipboard-bridge.js" defer></script></body>')
                return Response(html, media_type='text/html')
            return Response(response.content, status_code=response.status_code, media_type=response.headers.get('content-type','application/octet-stream').split(';')[0])
        except httpx.HTTPError:
            return Response('浏览器连接暂时不可用。', status_code=502)

    (ROOT/'static').mkdir(exist_ok=True)
    app.mount('/static', StaticFiles(directory=str(ROOT/'static')), name='static')
    return app
