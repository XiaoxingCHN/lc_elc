"""Record a deterministic source manifest or register an immutable artifact."""
import argparse,hashlib,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SOURCE={'client':['clients/app'],'server':['server/ubuntu22.04'],'eda':['plugins/jlc-eda']}
SKIP={'.git','node_modules','build','dist','ephemeral','.dart_tool','.gradle','.cxx','__pycache__','releases','runtime','.idea'}
def digest(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
 return h.hexdigest()
def snapshot(component):
 result={};raw={}
 for r in SOURCE[component]:
  for p in sorted((ROOT/r).rglob('*')):
   if not p.is_file() or any(x in SKIP for x in p.relative_to(ROOT).parts) or p.name in ['local.properties','.flutter-plugins-dependencies','GeneratedPluginRegistrant.java'] or p.suffix in ['.pyc','.log','.iml']:continue
   name=p.relative_to(ROOT).as_posix();raw[name]=digest(p);b=p.read_bytes()
   try:
    b.decode('utf-8');b=b.replace(b'\r\n',b'\n') if b'\x00' not in b else b
   except UnicodeDecodeError:pass
   result[name]=hashlib.sha256(b).hexdigest()
 return {'component':component,'source_roots':SOURCE[component],'hash_mode':'UTF8 text LF-normalized; binaries raw SHA256','files':result,'raw_files':raw,'file_count':len(result),'tree_sha256':hashlib.sha256(json.dumps(result,sort_keys=True,separators=(',',':')).encode()).hexdigest()}
def main():
 p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True);a=sub.add_parser('snapshot');a.add_argument('--component',choices=SOURCE,required=True);a.add_argument('--output',required=True);a.add_argument('--activate',action='store_true');a=sub.add_parser('artifact');a.add_argument('--file',required=True);a.add_argument('--source-manifest',required=True);a.add_argument('--version',required=True);a.add_argument('--output',required=True);x=p.parse_args()
 out=Path(x.output).resolve();assert out.is_relative_to(ROOT),'output must stay inside repository'
 if out.exists():p.error('Output already exists; do not overwrite immutable manifests')
 if x.action=='snapshot':result=snapshot(x.component)
 else:
  file=Path(x.file).resolve();source=Path(x.source_manifest).resolve();assert file.is_relative_to(ROOT) and source.is_relative_to(ROOT);m=json.loads(source.read_text(encoding='utf-8'));result={'file':file.relative_to(ROOT).as_posix(),'bytes':file.stat().st_size,'sha256':digest(file),'version':x.version,'source_manifest':source.relative_to(ROOT).as_posix(),'source_tree_sha256':m['tree_sha256'],'validation':'pending; add actual build/test environment and results before release'}
 out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(str(out.relative_to(ROOT)))
 if x.action=='snapshot' and x.activate:
  index=ROOT/'maintenance/registry/active-sources.json';active=json.loads(index.read_text(encoding='utf-8')) if index.exists() else {};active[x.component]=out.relative_to(ROOT).as_posix();index.write_text(json.dumps(active,indent=2)+'\n',encoding='utf-8');print('Active source pointer updated: '+x.component)
if __name__=='__main__':main()
