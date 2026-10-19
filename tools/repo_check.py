"""Offline source, registry, link and Git credential-boundary checks."""
import argparse,ast,hashlib,json,re,subprocess,urllib.parse
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def rawsha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
 return h.hexdigest()
def portable_sha(p):
 b=p.read_bytes()
 try:
  b.decode('utf-8');b=b.replace(b'\r\n',b'\n') if b'\0' not in b else b
 except UnicodeDecodeError:pass
 return hashlib.sha256(b).hexdigest()
def secret_findings(text):
 hits=[]
 for n,line in enumerate(text.splitlines(),1):
  if re.search(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',line):hits.append({'line':n,'rule':'private-key'})
  if re.search(r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|sk-[A-Za-z0-9_-]{30,})\b',line):hits.append({'line':n,'rule':'credential-token'})
  for m in re.finditer(r'''(?i)\b(?:password|passwd|pwd|secret|access_token|api_key)\s*[:=]\s*['"]([^'"\r\n]{6,})['"]''',line):
   v=m[1];low=v.lower()
   if any(x in v for x in ['<','>','$','%','{','}']) or low.startswith(('test','dummy','example','change','placeholder','password','fake','not-a-','wrong','correct','invalid')):continue
   if (len(v)>=10 and any(c.isupper() for c in v) and any(c.islower() for c in v) and any(c.isdigit() for c in v)) or (v.isdigit() and len(v)>=6):hits.append({'line':n,'rule':'hardcoded-credential'})
 return hits

def git_files(staged=False):
 cmd=['git','-C',str(ROOT),'ls-files','-z','--cached']
 if not staged:cmd+=['--others','--exclude-standard']
 r=subprocess.run(cmd,capture_output=True,check=True);return sorted(set(x.decode('utf-8') for x in r.stdout.split(b'\0') if x))
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--verify-payloads',action='store_true');p.add_argument('--staged-only',action='store_true');p.add_argument('--output');a=p.parse_args();passed=[];errors=[];warnings=[]
 def check(name,condition,details=None):
  (passed if condition else errors).append({'check':name,**({'details':details} if details is not None else {})})
 components=json.loads((ROOT/'maintenance/registry/components.json').read_text(encoding='utf-8'))
 files=git_files(a.staged_only)
 for c in components['components']:
  check('component-source:'+c['id'],all((ROOT/x).exists() for x in c['required_files']))
  check('component-tracked:'+c['id'],all(x in files for x in c['required_files']))
 for name in files:
  pth=ROOT/name;parts=Path(name).parts
  forbidden=(name.startswith('local/') or name.startswith('data/') and name!='data/README.md' or 'releases' in parts and name!='releases/README.md' or 'node_modules' in parts or pth.suffix.lower() in ['.keystore','.jks','.pem','.key','.sqlite3','.apk','.eext','.whl','.deb','.exe','.dll'])
  if forbidden:errors.append({'check':'git-boundary','path':name});continue
  if not pth.is_file():continue
  if pth.stat().st_size>50*1024*1024:errors.append({'check':'git-large-file','path':name});continue
  try:
   b=subprocess.check_output(['git','-C',str(ROOT),'show',':'+name]) if a.staged_only else pth.read_bytes();text=b.decode('utf-8-sig')
  except (UnicodeDecodeError,subprocess.CalledProcessError):continue
  for hit in secret_findings(text):errors.append({'check':'credential-scan','path':name,**hit})
  if pth.suffix=='.py':
   try:ast.parse(text,filename=name)
   except SyntaxError as e:errors.append({'check':'python-syntax','path':name,'line':e.lineno})
 for module in ['lab_inventory','lab_catalog','lab_workflow']:
  base=ROOT/'server/ubuntu22.04/odoo_addons'/module
  try:
   m=ast.literal_eval((base/'__manifest__.py').read_text(encoding='utf-8-sig'));check('odoo-manifest:'+module,all((base/x).is_file() for x in m.get('data',[])),m['version'])
  except Exception as e:errors.append({'check':'odoo-manifest','path':module,'error':str(e)})
 active=json.loads((ROOT/'maintenance/registry/active-sources.json').read_text(encoding='utf-8'))
 for manifest_path in active.values():
  mpath=(ROOT/manifest_path).resolve();assert mpath.is_relative_to(ROOT.resolve()),'Source manifest escapes repository'
  m=json.loads(mpath.read_text(encoding='utf-8'));diff=[n for n,h in m['files'].items() if not (ROOT/n).resolve().is_relative_to(ROOT.resolve()) or not (ROOT/n).is_file() or portable_sha(ROOT/n)!=h];check('frozen-source:'+m['component'],not diff,diff[:20] if diff else m['file_count'])
 docs=[ROOT/'README.md',ROOT/'CONTRIBUTING.md']+list((ROOT/'docs').rglob('*.md'))
 for d in ['clients/README.md','clients/app/README.md','clients/windows/README.md','clients/android/README.md','clients/linux/README.md','server/README.md','plugins/README.md','dependencies/README.md','services/lcsc/README.md','data/README.md','archive/README.md','releases/README.md']:docs.append(ROOT/d)
 for doc in docs:
  if not doc.exists():errors.append({'check':'required-doc','path':str(doc.relative_to(ROOT))});continue
  for target in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)',doc.read_text(encoding='utf-8-sig')):
   if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:',target) or target.startswith('#'):continue
   target=urllib.parse.unquote(target.split('#')[0].strip('<>'))
   if '<' in target or '>' in target:continue
   if not (doc.parent/target).exists():errors.append({'check':'doc-link','path':str(doc.relative_to(ROOT)),'target':target})
 payloads=json.loads((ROOT/'maintenance/registry/payloads.json').read_text(encoding='utf-8'))['payloads']
 for item in payloads:
  check('payload-method:'+item['id'],bool(item.get('path') and item.get('acquisition',{}).get('commands')))
  if item.get('type')=='not-yet-built':warnings.append({'check':'known-payload-not-built','id':item['id'],'recovery':'See registered preparation commands; this is not a complete offline closure.'})
  if item.get('type')=='file' and item.get('sha256'):
   file=ROOT/item['path']
   if not file.is_file():(errors if a.verify_payloads else warnings).append({'check':'payload-missing','id':item['id'],'recovery':'python tools/fetch_payload.py --id '+item['id']})
   elif a.verify_payloads:check('payload-hash:'+item['id'],rawsha(file)==item['sha256'])
 if a.verify_payloads:
  rel=json.loads((ROOT/'maintenance/registry/releases.json').read_text(encoding='utf-8'))
  for x in rel['artifacts']:
   file=ROOT/x['path'];check('release-hash:'+x['id'],file.is_file() and rawsha(file)==x['sha256'])
 result={'result':'PASS' if not errors else 'FAIL','passed_checks':len(passed),'git_candidate_files':len(files),'errors':errors,'warnings':warnings,'checks':passed,'production_access':False,'payload_verification':a.verify_payloads}
 if a.output:
  out=Path(a.output).resolve();assert out.is_relative_to(ROOT);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({k:v for k,v in result.items() if k!='checks'},ensure_ascii=False,indent=2));return 0 if not errors else 1
if __name__=='__main__':raise SystemExit(main())
