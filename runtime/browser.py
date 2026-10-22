"""Authenticated control channel for a single persistent browser environment."""
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import secrets

from fastapi import FastAPI, HTTPException, Request
import httpx
import uvicorn

CONFIG = json.loads(Path('/run/workbench/launch.json').read_text())
STATE = {'status': 'starting', 'error': None, 'test_mode': CONFIG['test_mode'], 'exit_ip': None}
STATE['timezone'] = CONFIG.get('timezone')
NATIVE = None


async def refresh_ip():
    if CONFIG['test_mode']:
        return
    try:
        async with httpx.AsyncClient(proxy='http://127.0.0.1:7890', trust_env=False, timeout=15) as client:
            r = await client.get('https://api.ipify.org?format=json')
            r.raise_for_status()
            import ipaddress
            STATE['exit_ip'] = str(ipaddress.ip_address(r.json()['ip']))
    except Exception:
        STATE['exit_ip'] = None


async def start_browser():
    global NATIVE
    try:
        if CONFIG.get('engine','firefox') != 'firefox':
            raise ValueError('Unsupported retired engine')
        from native_firefox import NativeFirefox
        NATIVE = NativeFirefox(CONFIG['test_mode'])
        await NATIVE.start()
        STATE.update(status='running', engine='firefox', url='', title='标准 Firefox')
        asyncio.create_task(refresh_ip())
    except Exception:
        STATE.update(status='error', error='标准 Firefox 启动失败，请查看本机环境日志后重试。')
        import traceback
        traceback.print_exc()


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(start_browser())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    if NATIVE:
        await NATIVE.stop()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)


@app.middleware('http')
async def auth(request: Request, call_next):
    if not secrets.compare_digest(request.headers.get('X-Worker-Token', ''), CONFIG['worker_secret']):
        from fastapi.responses import JSONResponse
        return JSONResponse({'error':'unauthorized'}, status_code=403)
    if int(request.headers.get('content-length', '0')) > 65536:
        from fastapi.responses import JSONResponse
        return JSONResponse({'error':'too large'}, status_code=413)
    return await call_next(request)


@app.get('/status')
async def status():
    if NATIVE:
        if NATIVE.process and NATIVE.process.poll() is not None:
            STATE.update(status='error', error='标准 Firefox 已退出，请停止环境后重新打开。')
        return dict(STATE)
    return dict(STATE)


@app.post('/action')
async def action(request: Request):
    data = await request.json()
    kind = data.get('kind')
    if kind in ('paste','paste_image'):
        if STATE['status'] != 'running':
            raise HTTPException(409, '浏览器尚未就绪。')
        if kind == 'paste' and (not isinstance(data.get('text'),str) or len(data['text'])>20000):
            raise HTTPException(400, '一次最多粘贴 20000 个字符。')
        try:
            from desktop_clipboard import paste_text, paste_image
            await asyncio.to_thread(paste_text if kind=='paste' else paste_image, data.get('text') if kind=='paste' else data.get('name'))
            return {'ok': True}
        except Exception:
            raise HTTPException(400, '粘贴未完成，请先点选远程网页的输入框。')
    if NATIVE:
        if STATE['status'] != 'running':
            raise HTTPException(409, '浏览器尚未就绪。')
        if kind not in ('navigate', 'text', 'copy', 'back', 'forward', 'reload', 'new_tab'):
            raise HTTPException(400, '不支持的浏览器操作。')
        if kind == 'navigate':
            from urllib.parse import urlsplit
            url = str(data.get('url', '')).strip()
            if '://' not in url:
                url = 'https://' + url
            if len(url) > 8192 or any(ord(c) < 32 for c in url) or urlsplit(url).scheme not in ('http', 'https') or not urlsplit(url).hostname:
                raise HTTPException(400, '请输入 HTTP/HTTPS 网页地址。')
            data['url'] = url
        if kind == 'text':
            data['text'] = str(data.get('text', ''))
            if len(data['text']) > 20000:
                raise HTTPException(400, '一次最多输入 20000 个字符。')
        try:
            return await NATIVE.action(kind, data)
        except Exception:
            raise HTTPException(400, '网页操作未完成，请在浏览器画面中查看详情。')
    raise HTTPException(409,'浏览器尚未就绪。')


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=8081, access_log=False)
