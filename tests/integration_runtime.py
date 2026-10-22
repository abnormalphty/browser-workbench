"""Opt-in real Docker verification; uses only disposable local test data.

Run from the project root: python3 tests/integration_runtime.py
No account, airport subscription or existing browser data is used.
"""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlencode, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from workbench.runtime import Runtime
from workbench.store import Store
from workbench.geography import PLACES,validate_location


def test_proxy(label):
    records = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_CONNECT(self):
            if self.path.rsplit(':',1)[-1] == '443':
                self.send_error(502, 'Local verification proxy does not forward TLS')
                return
            # Mihomo's HTTP outbound uses CONNECT even for plain HTTP targets.
            # Terminate this local tunnel and answer its inner HTTP request.
            self.send_response(200, 'Connection established')
            self.end_headers()
            self.wfile.flush()
            self.close_connection = False
            self.handle_one_request()

        def do_GET(self):
            url = urlsplit(self.path)
            query = parse_qs(url.query)
            if url.path == '/report':
                records.append({k:v[0] for k,v in query.items()})
                payload = b'ok'
                kind = 'text/plain'
            else:
                set_value = json.dumps(query.get('set',[None])[0])
                payload = f'''<!doctype html><meta charset="utf-8"><title>LOCAL ROUTE {label}</title>
                <h1>LOCAL ROUTE {label}</h1><textarea id="input" style="width:90%;height:180px;font:26px sans-serif">环境复制到电脑：中文 English 🌏 — Clipboard QA</textarea>
                <script>
                const value={set_value};
                if(value!==null){{localStorage.setItem('note',value);document.cookie='note='+value+';max-age=86400;path=/';}}
                input.focus();input.select();
                fetch('/report?'+new URLSearchParams({{route:{json.dumps(label)},note:localStorage.getItem('note')||'',cookie:document.cookie,zone:Intl.DateTimeFormat().resolvedOptions().timeZone,january:new Date('2026-01-15T12:00:00Z').getTimezoneOffset(),july:new Date('2026-07-15T12:00:00Z').getTimezoneOffset()}}));
                </script>'''.encode()
                kind = 'text/html; charset=utf-8'
            self.send_response(200)
            self.send_header('Content-Type',kind)
            self.send_header('Content-Length',str(len(payload)))
            self.send_header('Cache-Control','no-store')
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    return server, records


def wait_ready(runtime, env_id):
    deadline=time.monotonic()+130
    while time.monotonic()<deadline:
        state=runtime.state(env_id)
        if state['status']=='running':
            print('browser running:',env_id[:8],flush=True)
            return state
        if state['status']=='error':
            raise AssertionError(state['error'])
        time.sleep(2)
    raise AssertionError('Browser startup timeout')


def navigate(runtime, env_id, url):
    address=runtime.worker_address(env_id)
    with httpx.Client(timeout=35,trust_env=False) as client:
        result=client.post(address+'/action',json={'kind':'navigate','url':url},headers={'X-Worker-Token':runtime.worker_secret(env_id)})
    return result


def wait_report(records, expected):
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        if any(r.get('note')==expected for r in records):
            return next(r for r in reversed(records) if r.get('note')==expected)
        time.sleep(.2)
    raise AssertionError('No matching browser storage report: '+repr(records))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--engine', choices=['firefox'], default='firefox')
    args=parser.parse_args()
    engine=args.engine
    test_root=Path(__file__).resolve().parents[1]/'verification-data'
    test_root.mkdir(exist_ok=True)
    a, records_a=test_proxy('A')
    b, records_b=test_proxy('B')
    direct, direct_records=test_proxy('DIRECT')
    env_ids=[]
    results=[]
    with tempfile.TemporaryDirectory(dir=test_root) as temp:
        store=Store(Path(temp))
        runtime=Runtime(store)
        try:
            assert runtime.status()['image_ready'], 'Build the browser image first'
            nodes=[{'name':name,'type':'http','server':'host.docker.internal','port':server.server_port} for name,server in [('A',a),('B',b)]]
            store.save_subscription('local-verification-fixture',nodes)
            mapping={n['name']:n['id'] for n in store.public_state()['nodes']}
            for name,place in [('A','new-york'),('B','sydney')]:
                store.set_setting('node_location:'+mapping[name],validate_location({**PLACES[place],'source':'manual'}))
            envs=[store.create_environment('Disposable verification '+name,mapping[name],engine=engine) for name in ['A','B']]
            env_ids=[e['id'] for e in envs]
            for env in envs:
                runtime.start(env['id'])
                wait_ready(runtime,env['id'])
            results.append('two managed ARM64 browser environments start')
            fingerprints=[runtime.state(e['id'])['fingerprint'] for e in envs]
            for env,value,records in zip(envs,['alpha','beta'],[records_a,records_b]):
                r=navigate(runtime,env['id'],'http://workbench.test/remember?'+urlencode({'set':value}))
                assert r.status_code==200,r.text
                record=wait_report(records,value)
                assert record['route']==('A' if value=='alpha' else 'B')
                assert f'note={value}' in record['cookie']
                expected=('America/New_York','300','240') if value=='alpha' else ('Australia/Sydney','-660','-600')
                assert (record['zone'],record['january'],record['july'])==expected,record
            results.append('IANA browser timezone matches node city with northern and southern DST offsets')
            results.append('requests route through each environment’s selected proxy')
            results.append('same-origin cookies and localStorage stay separate')
            for e in envs:
                runtime.stop(e['id'])
            for e in envs:
                runtime.start(e['id'])
                wait_ready(runtime,e['id'])
            for env,value,records,old_fingerprint in zip(envs,['alpha','beta'],[records_a,records_b],fingerprints):
                records.clear()
                r=navigate(runtime,env['id'],'http://workbench.test/check')
                assert r.status_code==200,r.text
                assert f'note={value}' in wait_report(records,value)['cookie']
                assert runtime.state(env['id'])['fingerprint']==old_fingerprint
            results.append('standard Firefox storage survives stop/recreate')
            direct_url=f'http://host.docker.internal:{direct.server_port}/probe'
            records_a.clear()
            assert navigate(runtime,envs[0]['id'],direct_url).status_code==200
            assert wait_report(records_a, None)['route']=='A'
            assert not direct_records, 'Request bypassed proxy'
            a.shutdown();a.server_close()
            response=navigate(runtime,envs[0]['id'],direct_url)
            # Native navigation acknowledges a keypress, not an HTTP response.
            time.sleep(3)
            assert not direct_records, 'Proxy failure caused direct connection'
            results.append('proxy interruption does not fall back to direct HTTP')
            # Verify real Docker behavior behind the review finding.
            for e in envs:
                runtime.stop(e['id'])
                stopped=runtime._run(['stop',runtime.container_name(e['id'])],check=False)
                print('docker stop already-stopped return code:',stopped.returncode,flush=True)
                runtime.delete(e['id'])
            env_ids=[]
            results.append('stopped environments and persistent test data can be deleted')
        finally:
            for env_id in env_ids:
                try:
                    runtime._run(['rm','-f',runtime.container_name(env_id)],check=False)
                except Exception:
                    pass
            for server in [a,b,direct]:
                try: server.shutdown();server.server_close()
                except Exception: pass
            report={'engine':engine,'checks':results,'all_passed':len(results)==7}
            (test_root/'results-firefox.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
            print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
    assert len(results)==7


if __name__=='__main__':
    main()
