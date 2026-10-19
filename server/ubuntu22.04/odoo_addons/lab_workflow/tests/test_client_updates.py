import base64
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from odoo.tests import HttpCase, tagged
from ..controllers import lab_client_updates
from ..tools.client_release import ReleaseStore


@tagged('post_install', '-at_install', 'lab_workflow_business')
class TestClientUpdateHttp(HttpCase):
    def test_public_manifest_and_anonymous_download_boundary(self):
        with tempfile.TemporaryDirectory(prefix='lab-update-http-') as temp:
            root = Path(temp)
            payload = {'schema': 1, 'app_id': 'com.example.lab_inventory_client',
                       'platform': 'windows', 'arch': 'x64', 'channel': 'stable',
                       'release_id': 'fixture-5', 'filename': 'fixture.zip',
                       'size': 1, 'sha256': 'a'*64, 'build_number': 5,
                       'release_sequence': 5, 'version': '1.1.2', 'package_type': 'zip',
                       'api_min': 1, 'api_max': 1}
            envelope = {'key_id': 'http-fixture-not-trusted-by-client',
                        'payload': base64.b64encode(json.dumps(payload).encode()).decode(),
                        'signature': base64.b64encode(bytes(64)).decode()}
            path = root/'windows/x64/stable.json'; path.parent.mkdir(parents=True)
            path.write_text(json.dumps(envelope))
            with patch.object(lab_client_updates, 'store', lambda: ReleaseStore(root)):
                response = self.url_open('/lab/client/updates/manifest?platform=windows&arch=x64')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), envelope)
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
                response = self.url_open('/lab/client/updates/manifest?platform=linux&arch=x64')
                self.assertEqual(response.status_code, 204)
                response = self.url_open('/lab/client/updates/manifest?platform=windows&arch=..')
                self.assertEqual(response.status_code, 404)
                response = self.url_open('/lab/client/updates/assets/fixture-5/fixture.zip', allow_redirects=False)
                self.assertIn(response.status_code, (303, 302, 401, 403))
