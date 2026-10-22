import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from workbench.app import create_app


class ClipboardTests(unittest.TestCase):
    def test_copy_out_has_authenticated_endpoint_and_preserves_unicode(self):
        with tempfile.TemporaryDirectory() as tmp:
            app=create_app(Path(tmp));env=app.state.store.create_environment('copy',None,engine='firefox')
            with TestClient(app,base_url='http://127.0.0.1:8766') as client:
                token=re.search(r'name="workbench-token" content="([^"]+)"',client.get('/').text).group(1)
                endpoint='/api/environments/'+env['id']+'/clipboard'
                self.assertEqual(client.post(endpoint).status_code,403)
                runtime=app.state.runtime
                self.assertTrue(hasattr(runtime,'clipboard_text'))
                with patch.object(runtime,'clipboard_text',return_value='从环境复制 → 主电脑\n中文保持完整。'):
                    response=client.post(endpoint,headers={'X-Workbench-Token':token})
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.json()['text'],'从环境复制 → 主电脑\n中文保持完整。')

if __name__=='__main__':unittest.main()

class RuntimeClipboardTests(unittest.TestCase):
    def test_long_text_is_not_silently_cut_at_20000_characters(self):
        from types import SimpleNamespace
        from workbench.runtime import Runtime
        from workbench.store import Store
        import json
        with tempfile.TemporaryDirectory() as tmp:
            runtime=Runtime(Store(Path(tmp)))
            sample='中文 🌏\n'*6000
            with patch.object(runtime,'_inspect',return_value={'State':{'Running':True}}),patch.object(runtime,'_run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps({'text':sample,'too_large':False}))):
                self.assertEqual(runtime.clipboard_text('a'*32),sample)
