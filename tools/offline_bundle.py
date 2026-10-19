"""Export/import the Git-excluded offline payloads; never includes local/private."""
import argparse,hashlib,json,os,shutil,tarfile
from pathlib import Path,PurePosixPath
ROOT=Path(__file__).resolve().parents[1]
ROOTS=('dependencies','data/catalog','clients/windows/releases','clients/android/releases','clients/linux/releases','plugins/jlc-eda/releases','plugins/jlc-eda/bridge/runtime','plugins/jlc-eda/node_modules','server/releases')
BLOCK={'.keystore','.jks','.pem','.key','.log','.lock'}
def digest(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
 return h.hexdigest()
def allowed(name):
 p=PurePosixPath(name)
 return bool(name and '\\' not in name and ':' not in name and not p.is_absolute() and '..' not in p.parts and any(name.startswith(r+'/') for r in ROOTS) and p.suffix.lower() not in BLOCK and not any(x in p.parts for x in ['user-cache']) and p.name!='gradle.properties')
def export_bundle(output):
 if output.exists():raise ValueError('Refusing to overwrite archive')
 files={}
 for root in ROOTS:
  for p in sorted((ROOT/root).rglob('*')):
   name=p.relative_to(ROOT).as_posix()
   if p.is_file() and not p.is_symlink() and allowed(name):files[name]={'bytes':p.stat().st_size,'sha256':digest(p)}
 if not files:raise ValueError('No payloads to export')
 output.parent.mkdir(parents=True,exist_ok=True)
 import io
 with tarfile.open(output,'w:gz' if output.name.endswith('.gz') else 'w') as tf:
  for name,meta in files.items():
   path=ROOT/name;tf.add(path,arcname=name,recursive=False)
   if digest(path)!=meta['sha256']:raise ValueError('Source changed while exporting: '+name)
  b=json.dumps({'format':1,'files':files},sort_keys=True).encode();m=tarfile.TarInfo('LC_ELC_PAYLOAD_MANIFEST.json');m.size=len(b);tf.addfile(m,io.BytesIO(b))
 sha=digest(output);output.with_name(output.name+'.sha256').write_text(sha+'  '+output.name+'\n',encoding='utf-8');return {'files':len(files),'archive':str(output),'sha256':sha}
def import_bundle(archive):
 side=archive.with_name(archive.name+'.sha256')
 if not side.exists() or digest(archive)!=side.read_text(encoding='utf-8').split()[0]:raise ValueError('Archive sidecar SHA256 missing or mismatched')
 with tarfile.open(archive,'r:*') as tf:
  members=tf.getmembers();manifest=json.load(tf.extractfile('LC_ELC_PAYLOAD_MANIFEST.json'));assert manifest['format']==1
  files=manifest['files'];names=[m.name for m in members]
  if len(names)!=len(set(names)):raise ValueError('Duplicate archive members')
  for m in members:
   if m.name=='LC_ELC_PAYLOAD_MANIFEST.json':continue
   if not m.isfile() or not allowed(m.name) or m.name not in files:raise ValueError('Unsafe/unregistered archive member: '+m.name)
   target=(ROOT/m.name).resolve()
   if not target.is_relative_to(ROOT.resolve()):raise ValueError('Target escapes repository')
   if target.exists() and digest(target)!=files[m.name]['sha256']:raise ValueError('Existing local payload differs; refusing overwrite: '+m.name)
  if set(files)!=set(names)-{'LC_ELC_PAYLOAD_MANIFEST.json'}:raise ValueError('Manifest/member mismatch')
  for m in members:
   if m.name=='LC_ELC_PAYLOAD_MANIFEST.json':continue
   target=(ROOT/m.name).resolve()
   if target.exists():continue
   target.parent.mkdir(parents=True,exist_ok=True)
   with tf.extractfile(m) as inp,target.open('xb') as out:shutil.copyfileobj(inp,out,4*1024*1024)
   if digest(target)!=files[m.name]['sha256']:
    target.unlink();raise ValueError('Extracted hash mismatch: '+m.name)
   if os.name!='nt':target.chmod(m.mode&0o777)
 return {'verified_files':len(files)}
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['export','import']);p.add_argument('--file',required=True);a=p.parse_args();path=Path(a.file).resolve();print(json.dumps(export_bundle(path) if a.action=='export' else import_bundle(path),indent=2))
if __name__=='__main__':main()
