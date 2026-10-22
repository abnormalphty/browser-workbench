import re
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote
from fastapi.testclient import TestClient
from workbench.app import create_app


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.app = create_app(self.root)
        self.client = TestClient(self.app, base_url='http://127.0.0.1:8766')
        token = re.search(r'name="workbench-token" content="([^"]+)"', self.client.get('/').text).group(1)
        self.headers = {'X-Workbench-Token':token}
        self.env = self.app.state.store.create_environment('传输测试', None)
        self.base = '/api/environments/'+self.env['id']+'/files'

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def test_upload_preserves_binary_and_returns_environment_path(self):
        payload = b'file-content\x00\xff' * 6000
        response = self.client.post(self.base+'/upload', content=payload, headers={**self.headers,'X-File-Name':quote('中文材料.pdf')})
        self.assertEqual(response.status_code, 200, response.text)
        item = response.json()
        self.assertTrue(item['path'].endswith('/中文材料.pdf'))
        result = self.client.get(self.base, headers=self.headers)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['incoming'][0]['name'], '中文材料.pdf')
        downloaded = self.client.get(self.base+'/incoming/'+item['id'], headers=self.headers)
        self.assertEqual(downloaded.content, payload)
        self.assertIn('attachment', downloaded.headers['content-disposition'])

    def test_duplicate_upload_names_do_not_overwrite_the_previous_file(self):
        first = self.client.post(self.base+'/upload', content=b'first', headers={**self.headers,'X-File-Name':'same.txt'}).json()
        second = self.client.post(self.base+'/upload', content=b'second', headers={**self.headers,'X-File-Name':'same.txt'}).json()
        self.assertNotEqual(first['id'], second['id'])
        self.assertEqual(first['name'], 'same.txt')
        self.assertEqual(second['name'], 'same (2).txt')
        self.assertEqual(self.client.get(self.base+'/incoming/'+first['id']).content,b'first')
        self.assertEqual(self.client.get(self.base+'/incoming/'+second['id']).content,b'second')

    def test_long_filename_stays_listed_and_downloadable(self):
        response = self.client.post(self.base+'/upload', content=b'x', headers={**self.headers,'X-File-Name':'a'*216+'.txt'})
        self.assertEqual(response.status_code, 200)
        files = self.client.get(self.base, headers=self.headers).json()['incoming']
        self.assertEqual(len(files), 1)
        self.assertEqual(self.client.get(self.base+'/incoming/'+response.json()['id'], headers=self.headers).content, b'x')

    def test_completed_download_is_available_and_partial_is_hidden(self):
        self.assertEqual(self.client.get(self.base, headers=self.headers).status_code, 200)
        folder = self.root/'environments'/self.env['id']/'profile'/'transfer'/'downloads'
        (folder/'result.html').write_text('<script>unsafe-to-render-inline</script>')
        (folder/'not-finished.zip.part').write_bytes(b'x')
        (folder/'not-finished.zip').touch()
        files = self.client.get(self.base, headers=self.headers).json()['downloads']
        self.assertEqual([f['name'] for f in files], ['result.html'])
        response = self.client.get(self.base+'/downloads/'+files[0]['id'], headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['content-type'], 'application/octet-stream')
        self.assertIn('attachment', response.headers['content-disposition'])

    def test_symlinks_do_not_expose_profile_or_host_files(self):
        self.assertEqual(self.client.get(self.base, headers=self.headers).status_code, 200)
        root = self.root/'environments'/self.env['id']/'profile'/'transfer'
        secret = self.root/'secret.txt'; secret.write_text('not-for-transfer')
        (root/'downloads'/'shortcut.txt').symlink_to(secret)
        self.assertEqual(self.client.get(self.base, headers=self.headers).json()['downloads'], [])
        (root/'incoming').rmdir()
        (root/'incoming').symlink_to(self.root, target_is_directory=True)
        response = self.client.post(self.base+'/upload', content=b'x', headers={**self.headers,'X-File-Name':'new.txt'})
        self.assertEqual(response.status_code, 400)
        self.assertFalse((self.root/'new.txt').exists())

    def test_rejected_stream_removes_partial_upload(self):
        from unittest.mock import patch
        with patch('workbench.transfers.MAX_UPLOAD', 5):
            response = self.client.post(self.base+'/upload',content=b'too-long',headers={**self.headers,'X-File-Name':'partial.txt'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get(self.base,headers=self.headers).json()['incoming'], [])

    def test_attachment_get_requires_session_cookie(self):
        uploaded = self.client.post(self.base+'/upload',content=b'private',headers={**self.headers,'X-File-Name':'file.txt'}).json()
        self.assertEqual(self.client.get(self.base+'/incoming/'+uploaded['id']).content,b'private')
        with TestClient(self.app,base_url='http://127.0.0.1:8766') as stranger:
            self.assertEqual(stranger.get(self.base+'/incoming/'+uploaded['id']).status_code,403)

    def test_transfer_needs_csrf_and_cannot_choose_arbitrary_path(self):
        response = self.client.post(self.base+'/upload', content=b'x', headers={'X-File-Name':'x.txt'})
        self.assertEqual(response.status_code, 403)
        response = self.client.post(self.base+'/upload', content=b'x', headers={**self.headers,'X-File-Name':quote('../../profile.sqlite')})
        self.assertEqual(response.status_code, 400)
        response = self.client.get(self.base+'/config/launch.json', headers=self.headers)
        self.assertEqual(response.status_code, 400)


if __name__ == '__main__': unittest.main()


class DownloadPreferencesTests(unittest.TestCase):
    def test_standard_firefox_uses_shared_download_directory(self):
        from runtime.native_firefox import firefox_preferences
        prefs = firefox_preferences(False)
        self.assertEqual(prefs.get('browser.download.dir'), '/profile/transfer/downloads')
        self.assertIs(prefs.get('browser.download.useDownloadDir'), True)
        self.assertEqual(prefs.get('browser.download.folderList'), 2)
