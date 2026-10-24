"""Local pages for the app smoke test, reached from a test-mode environment.

/          a page whose textarea is focused; whatever is pasted is reported
/download  a file served as an attachment, so Firefox saves it to its downloads
/got       what the textarea received (recorded for the harness)
Usage: fixture_server.py OUTPUT_DIR   (writes OUTPUT_DIR/port, OUTPUT_DIR/received.txt)
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
from urllib.parse import unquote, urlsplit

OUT = Path(sys.argv[1])
DOWNLOAD = '境工作台下载测试 · download check ✓\n'.encode() * 200
PAGE = '''<!doctype html><meta charset="utf-8"><title>UI SMOKE PAGE</title>
<h1 style="font:28px sans-serif">UI smoke page</h1>
<textarea id="t" autofocus style="width:90%;height:260px;font:24px sans-serif"></textarea>
<script>
t.focus();
t.addEventListener('input',()=>{fetch('/got?'+encodeURIComponent(t.value));t.select();});
</script>'''.encode()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path == '/got':
            (OUT/'received.txt').write_text(unquote(url.query))
            with (OUT/'received-all.txt').open('a') as log:  # every input event, for diagnosis
                log.write(unquote(url.query) + '\n')
            body, kind, extra = b'ok', 'text/plain', {}
        elif url.path == '/download':
            body, kind = DOWNLOAD, 'text/plain; charset=utf-8'
            extra = {'Content-Disposition': "attachment; filename*=UTF-8''%E4%B8%8B%E8%BD%BD%E6%B5%8B%E8%AF%95.txt"}
        else:
            body, kind, extra = PAGE, 'text/html; charset=utf-8', {}
        self.send_response(200)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(body)))
        for key, value in extra.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)


server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
(OUT/'download-expected.txt').write_bytes(DOWNLOAD)
(OUT/'port').write_text(str(server.server_port))
server.serve_forever()
