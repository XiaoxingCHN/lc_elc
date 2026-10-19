"""Show, download or verify registered offline payloads. No implicit downloads."""
import argparse,hashlib,json,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def digest(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
 return h.hexdigest()
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--list',action='store_true');p.add_argument('--id');g=p.add_mutually_exclusive_group();g.add_argument('--download',action='store_true');g.add_argument('--verify',action='store_true');a=p.parse_args();items=json.loads((ROOT/'maintenance/registry/payloads.json').read_text(encoding='utf-8'))['payloads']
 if a.list or not a.id:
  for x in items:print(x['id']+'\t'+x.get('path','')+'\t'+x['acquisition']['method'])
  return
 item=next((x for x in items if x['id']==a.id),None)
 if not item:p.error('Unknown payload id')
 print(json.dumps(item,ensure_ascii=False,indent=2))
 if not(a.download or a.verify):return
 path=(ROOT/item['path']).resolve();assert path.is_relative_to(ROOT),'Payload path escapes repository';expected=item.get('sha256')
 if not expected or item.get('type')!='file':p.error('This is a grouped/generated payload. Follow the registered acquisition commands; no single-file download/hash is available.')
 if a.verify:
  if not path.is_file():raise SystemExit('MISSING: '+str(path))
  if digest(path)!=expected:raise SystemExit('HASH MISMATCH: '+str(path))
  print('PASS '+item['path']);return
 if path.exists():
  if digest(path)==expected:print('Already present and verified');return
  raise SystemExit('Existing file differs; refusing to overwrite. Resolve manually before downloading.')
 url=item['acquisition'].get('url')
 if not url or not url.startswith('https://'):p.error('No pinned HTTPS URL; follow registered recovery procedure')
 path.parent.mkdir(parents=True,exist_ok=True);partial=path.with_name(path.name+'.download-part')
 if partial.exists():raise SystemExit('Partial file exists; inspect it before retrying: '+str(partial))
 h=hashlib.sha256()
 try:
  with urllib.request.urlopen(url,timeout=90) as response,partial.open('xb') as f:
   for b in iter(lambda:response.read(4*1024*1024),b''):f.write(b);h.update(b)
  if h.hexdigest()!=expected:raise RuntimeError('Downloaded hash differs from pinned registry; do not use as the same version')
  partial.replace(path);print('VERIFIED '+item['path'])
 except BaseException:
  if partial.exists():partial.unlink()
  raise
if __name__=='__main__':main()
