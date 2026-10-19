#!/usr/bin/env python3
"""Import catalog using the existing Odoo DB configuration without CLI secrets."""
import argparse,configparser,importlib.util,os,pathlib,sys

def main():
    parser=argparse.ArgumentParser(description='读取Odoo配置并导入中文器件资料索引')
    parser.add_argument('--config',default='/etc/odoo.conf')
    parser.add_argument('--database',required=True)
    parser.add_argument('--snapshot',required=True)
    parser.add_argument('--categories',required=True)
    parser.add_argument('--batch',type=int,default=2000)
    parser.add_argument('--limit',type=int,default=0)
    parser.add_argument('--resume-from')
    args=parser.parse_args()
    if args.batch<1 or args.limit<0:
        parser.error('batch必须大于0，limit不能为负数')
    cfg=configparser.ConfigParser(interpolation=None)
    with open(args.config,encoding='utf-8-sig') as fh:cfg.read_file(fh)
    options=cfg['options']
    def configured(name,default=None):
        value=options.get(name,'').strip()
        return default if value.lower() in ('','false','none') else value
    candidates=[pathlib.Path(__file__).resolve().parent/'odoo_addons/lab_catalog/tools/import_catalog.py']
    candidates.extend(pathlib.Path(path.strip())/'lab_catalog/tools/import_catalog.py'
                      for path in options.get('addons_path','').split(',') if path.strip())
    source=next((path for path in candidates if path.is_file()),None)
    if source is None:
        raise SystemExit('缺少lab_catalog导入工具，请完整解压服务器包')
    for file in (args.snapshot,args.categories):
        if not pathlib.Path(file).is_file():raise SystemExit('资料文件不存在: '+file)
    user=configured('db_user')
    if not user:raise SystemExit('Odoo配置中缺少db_user，请先确认实际数据库角色')
    argv=[str(source),'--dbname',args.database,'--dbuser',user,
          '--dbhost',configured('db_host','/var/run/postgresql'),
          '--dbport',configured('db_port','5432'),
          '--snapshot',str(pathlib.Path(args.snapshot).resolve()),
          '--categories',str(pathlib.Path(args.categories).resolve()),
          '--batch',str(args.batch),'--verify']
    if args.limit:argv+=['--limit',str(args.limit)]
    if args.resume_from:argv+=['--resume-from',args.resume_from]
    password=configured('db_password')
    old_password=os.environ.get('PGPASSWORD')
    try:
        if password:os.environ['PGPASSWORD']=password
        else:os.environ.pop('PGPASSWORD',None)
        spec=importlib.util.spec_from_file_location('lc_elc_catalog_import',source)
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        previous=sys.argv
        try:
            sys.argv=argv
            return module.main()
        finally:sys.argv=previous
    finally:
        if old_password is None:os.environ.pop('PGPASSWORD',None)
        else:os.environ['PGPASSWORD']=old_password

if __name__=='__main__':raise SystemExit(main())
