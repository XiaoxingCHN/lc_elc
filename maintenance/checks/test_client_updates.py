"""Signed publishing and file-serving boundaries, using only temporary fixtures."""
import base64
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('client_release_store', ROOT / 'server/ubuntu22.04/odoo_addons/lab_workflow/tools/client_release.py')
store = importlib.util.module_from_spec(spec); spec.loader.exec_module(store)


class ClientReleaseTests(unittest.TestCase):
    def setUp(self):
        private = ROOT/'local/private'; private.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='release-test-', dir=private); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT/'tools/client_release.py'), *map(str,args)],
                              capture_output=True, text=True)

    def test_no_release_and_unsupported_target(self):
        self.assertIsNone(store.ReleaseStore(self.root).manifest('windows', 'x64'))
        for target in [('../', 'x64'), ('windows', '..'), ('macos', 'x64')]:
            with self.assertRaises(ValueError): store.ReleaseStore(self.root).manifest(*target)

    def test_publish_verify_immutable_pointer_and_scoped_asset(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        key = self.root/'private.pem'; public=self.root/'public.json'
        result=self.run_cli('keygen','--private',key,'--public',public,'--key-id','test')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertNotIn('PRIVATE KEY',result.stdout)
        self.assertNotEqual(self.run_cli('keygen','--private',key,'--public',public,'--key-id','test').returncode,0)
        package=self.root/'client.zip'; package.write_bytes(b'complete fixture')
        meta=self.root/'meta.json'; meta.write_text(json.dumps({'schema':1,'app_id':'com.example.lab_inventory_client',
            'platform':'windows','arch':'x64','channel':'stable','release_id':'build-5','build_number':5,
            'release_sequence':5,'version':'1.1.2','package_type':'zip','api_min':1,'api_max':1,'requirements':{},
            'source_manifest':'maintenance/registry/source-client-test.json','source_tree_sha256':'1'*64,
            'source_manifest_sha256':'2'*64,'source_commit':'3'*40}))
        output=self.root/'published'
        args=('publish','--private',key,'--key-id','test','--root',output,'--package',package,'--metadata',meta)
        result=self.run_cli(*args); self.assertEqual(result.returncode,0,result.stderr)
        releases=store.ReleaseStore(output); envelope=releases.manifest('windows','x64')
        public_key=Ed25519PublicKey.from_public_bytes(base64.b64decode(json.loads(public.read_text())['test']))
        public_key.verify(base64.b64decode(envelope['signature']),base64.b64decode(envelope['payload']))
        path, data=releases.asset('build-5','client.zip')
        self.assertEqual(path.read_bytes(),package.read_bytes()); self.assertEqual(data['size'],package.stat().st_size)
        before=(output/'windows/x64/stable.json').read_bytes()
        self.assertNotEqual(self.run_cli(*args).returncode,0)
        payload=json.loads(meta.read_text()); payload['release_id']='other'; payload['release_sequence']=4
        meta.write_text(json.dumps(payload)); self.assertNotEqual(self.run_cli(*args).returncode,0)
        self.assertEqual((output/'windows/x64/stable.json').read_bytes(),before)
        for release, filename in [('build-5','../meta.json'),('..','client.zip'),('build-5','other.zip')]:
            with self.assertRaises((ValueError,FileNotFoundError)): releases.asset(release,filename)
        path.write_bytes(b'bad')
        with self.assertRaises(FileNotFoundError): releases.asset('build-5','client.zip')

    def test_no_symlink_escape_or_oversized_manifest(self):
        outside=self.root/'outside'; outside.mkdir()
        root=self.root/'store'; root.mkdir()
        try: (root/'releases').symlink_to(outside,target_is_directory=True)
        except OSError: self.skipTest('symlink unavailable on this host')
        with self.assertRaises(ValueError): store.safe_path(root,'releases','artifact')
        path=root/'windows/x64/stable.json'; path.parent.mkdir(parents=True)
        path.write_text('x'*65537)
        with self.assertRaises(ValueError): store.ReleaseStore(root).manifest('windows','x64')


if __name__=='__main__': unittest.main()
