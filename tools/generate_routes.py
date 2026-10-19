"""Extract route registration metadata from the maintained Odoo controllers (no imports)."""
import argparse,ast,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def routes():
 result=[]
 for file in sorted((ROOT/'server/ubuntu22.04/odoo_addons').glob('*/controllers/*.py')):
  tree=ast.parse(file.read_text(encoding='utf-8-sig'))
  for func in ast.walk(tree):
   if not isinstance(func,(ast.FunctionDef,ast.AsyncFunctionDef)):continue
   for dec in func.decorator_list:
    if not isinstance(dec,ast.Call) or not isinstance(dec.func,ast.Attribute) or dec.func.attr!='route':continue
    try:urls=ast.literal_eval(dec.args[0]) if dec.args else 'dynamic-route'
    except (ValueError,TypeError):urls='dynamic-route'
    if isinstance(urls,str):urls=[urls]
    options={}
    for kw in dec.keywords:
     if kw.arg in ['type','auth','methods','csrf','readonly']:
      try:options[kw.arg]=ast.literal_eval(kw.value)
      except (ValueError,TypeError):options[kw.arg]='dynamic; inspect source'
    for url in urls:result.append({'path':url,'source':file.relative_to(ROOT).as_posix(),'handler':func.name,'line':func.lineno,'registration':options})
 return {'schema_version':1,'derived_from':'AST of current controller decorators; not runtime or full business schema','routes':sorted(result,key=lambda r:(r['path'],r['source'],r['line']))}
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--check',action='store_true');a=p.parse_args();d=routes();b=json.dumps(d,ensure_ascii=False,indent=2)+'\n';out=ROOT/'maintenance/registry/routes.json'
 if a.check:
  if not out.exists() or out.read_text(encoding='utf-8')!=b:raise SystemExit('Routes registry differs; run tools/generate_routes.py and review the API change.')
 else:out.write_text(b,encoding='utf-8')
 print('Route registrations:',len(d['routes']))
if __name__=='__main__':main()
