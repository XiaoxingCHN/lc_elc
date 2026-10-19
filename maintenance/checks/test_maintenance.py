import importlib.util,io,json,tarfile,tempfile,types,unittest,hashlib,sys,contextlib
from unittest.mock import patch
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def load(name):
 spec=importlib.util.spec_from_file_location(name,ROOT/'tools'/(name+'.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

class CredentialBoundaryTests(unittest.TestCase):
 def test_detects_literal_credential_without_returning_value(self):
  m=load('repo_check');value=''.join(('Auth','092834','Pass'));hits=m.secret_findings('password = "'+value+'"');self.assertTrue(hits);self.assertNotIn(value,json.dumps(hits))
 def test_private_key_header_and_public_placeholders(self):
  m=load('repo_check');self.assertTrue(m.secret_findings('-----BEGIN '+'PRIVATE KEY-----'));self.assertFalse(m.secret_findings('password = "<OS_SECRET_STORE>"'))

class FrozenSourceTests(unittest.TestCase):
 def test_freeze_preserves_generated_models_but_excludes_build_cache(self):
  m=load('release')
  with tempfile.TemporaryDirectory() as temp:
   m.ROOT=Path(temp);base=m.ROOT/'clients/app';(base/'lib').mkdir(parents=True);(base/'build').mkdir();(base/'lib/model.g.dart').write_text('model\n');(base/'build/temp.dart').write_text('cache')
   result=m.snapshot('client');self.assertEqual(list(result['files']),['clients/app/lib/model.g.dart'])
 def test_freeze_is_portable_across_crlf_checkout(self):
  m=load('release')
  with tempfile.TemporaryDirectory() as temp:
   m.ROOT=Path(temp);base=m.ROOT/'clients/app';base.mkdir(parents=True);p=base/'pubspec.yaml';p.write_bytes(b'name: a\r\n');one=m.snapshot('client');p.write_bytes(b'name: a\n');two=m.snapshot('client');self.assertEqual(one['tree_sha256'],two['tree_sha256']);self.assertNotEqual(one['raw_files'],two['raw_files'])

 def test_activating_new_snapshot_preserves_old_manifest(self):
  m=load('release')
  with tempfile.TemporaryDirectory() as temp:
   m.ROOT=Path(temp).resolve();base=m.ROOT/'clients/app';base.mkdir(parents=True);(base/'pubspec.yaml').write_text('name: fixture\n');registry=m.ROOT/'maintenance/registry';registry.mkdir(parents=True);old=registry/'source-client-old.json';old.write_text('{"historical":true}');before=old.read_bytes();(registry/'active-sources.json').write_text(json.dumps({'client':'maintenance/registry/source-client-old.json'}));new=registry/'source-client-new.json'
   with patch.object(sys,'argv',['release.py','snapshot','--component','client','--output',str(new),'--activate']),contextlib.redirect_stdout(io.StringIO()):m.main()
   self.assertEqual(old.read_bytes(),before);self.assertEqual(json.loads((registry/'active-sources.json').read_text())['client'],'maintenance/registry/source-client-new.json');self.assertTrue(new.exists())

class OfflineBundleTests(unittest.TestCase):
 def test_roundtrip_is_verified_and_conflicting_file_is_not_overwritten(self):
  m=load('offline_bundle')
  with tempfile.TemporaryDirectory() as temp:
   base=Path(temp);m.ROOT=base/'source';p=m.ROOT/'dependencies/fixture.txt';p.parent.mkdir(parents=True);p.write_text('payload');private=m.ROOT/'dependencies/signing.keystore';private.write_text('synthetic fixture');archive=base/'payload.tar';m.export_bundle(archive)
   with tarfile.open(archive) as tf:self.assertNotIn('dependencies/signing.keystore',tf.getnames())
   m.ROOT=base/'target';m.ROOT.mkdir();self.assertEqual(m.import_bundle(archive)['verified_files'],1);q=m.ROOT/'dependencies/fixture.txt';self.assertEqual(q.read_text(),'payload');q.write_text('changed')
   with self.assertRaises(ValueError):m.import_bundle(archive)
   self.assertEqual(q.read_text(),'changed')
 def test_path_traversal_is_rejected_even_with_matching_archive_hash(self):
  m=load('offline_bundle')
  with tempfile.TemporaryDirectory() as temp:
   base=Path(temp);m.ROOT=base/'target';m.ROOT.mkdir();archive=base/'bad.tar';name='dependencies/../../escape.txt';data=b'synthetic';manifest={'format':1,'files':{name:{'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}}}
   with tarfile.open(archive,'w') as tf:
    for n,b in [(name,data),('LC_ELC_PAYLOAD_MANIFEST.json',json.dumps(manifest).encode())]:
     item=tarfile.TarInfo(n);item.size=len(b);tf.addfile(item,io.BytesIO(b))
   archive.with_name(archive.name+'.sha256').write_text(m.digest(archive)+'  bad.tar\n')
   with self.assertRaises(ValueError):m.import_bundle(archive)
   self.assertFalse((base/'escape.txt').exists())

class BuildPlanTests(unittest.TestCase):
 def test_dry_plan_uses_root_not_current_working_directory_and_checks_locked_dependencies(self):
  m=load('build_client');a=types.SimpleNamespace(platform='android',flutter=None,pub_cache=None,online=False,test=True,test_only=False,server='http://example.invalid',database='Example');host,flutter,cache,commands=m.plan(a);self.assertTrue(flutter.is_relative_to(m.ROOT));self.assertIn('--enforce-lockfile',commands[0]);self.assertIn('--offline',commands[0]);self.assertEqual(commands[1][1:3],['test','--no-pub']);self.assertEqual(commands[-1][1:3],['build','apk'])

if __name__=='__main__':unittest.main()
