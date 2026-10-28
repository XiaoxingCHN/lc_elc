#!/usr/bin/env python3
"""Build an immutable manual-upload Netlify site from a frozen server source manifest."""
import argparse,hashlib,json,pathlib,re,zipfile
BASE=pathlib.Path(__file__).resolve().parents[1]
ROOT=BASE.parents[2]

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--origin-host',required=True);p.add_argument('--public-port',required=True,type=int)
 p.add_argument('--source-manifest',required=True,type=pathlib.Path)
 p.add_argument('--output',required=True,type=pathlib.Path);p.add_argument('--zip-output',required=True,type=pathlib.Path)
 a=p.parse_args()
 if len(a.origin_host)>253 or not all(re.fullmatch('[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',part) for part in a.origin_host.split('.')):p.error('invalid literal origin hostname')
 if not 1024<=a.public_port<=65535:p.error('invalid origin port')
 manifest=json.loads(a.source_manifest.read_text(encoding='utf-8'))
 if manifest.get('component')!='server':p.error('server source manifest required')
 for file in (pathlib.Path(__file__),BASE/'netlify/_redirects.template',BASE/'netlify/_headers',BASE/'netlify/index.html'):
  relative=file.relative_to(ROOT).as_posix()
  digest=hashlib.sha256(file.read_bytes().replace(bytes([13,10]),bytes([10]))).hexdigest()
  if manifest['files'].get(relative)!=digest:p.error('source differs from frozen manifest: '+relative)
 output=a.output.resolve();archive=a.zip_output.resolve();meta=archive.with_suffix('.json')
 if output.exists() or archive.exists() or meta.exists():p.error('do not overwrite an existing artifact')
 output.mkdir(parents=True);archive.parent.mkdir(parents=True,exist_ok=True)
 for name in ('index.html','_headers'):(output/name).write_bytes((BASE/'netlify'/name).read_bytes())
 rule=(BASE/'netlify/_redirects.template').read_text(encoding='utf-8').replace('@ORIGIN_HOST@',a.origin_host).replace('@PUBLIC_PORT@',str(a.public_port))
 (output/'_redirects').write_text(rule,encoding='utf-8')
 with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as z:
  for file in sorted(output.iterdir()):z.write(file,file.name)
 with zipfile.ZipFile(archive) as z:
  if z.testzip() is not None:raise RuntimeError('zip integrity failure')
 result={'kind':'netlify-public-proxy','artifact':archive.name,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'bytes':archive.stat().st_size,'source_manifest':a.source_manifest.name,'source_manifest_sha256':hashlib.sha256(a.source_manifest.read_bytes()).hexdigest(),'source_tree_sha256':manifest['tree_sha256'],'origin':'https://'+a.origin_host+':'+str(a.public_port),'files':{file.name:hashlib.sha256(file.read_bytes()).hexdigest() for file in sorted(output.iterdir())},'netlify_deployed':False}
 meta.write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result,indent=2))

if __name__=='__main__':main()
