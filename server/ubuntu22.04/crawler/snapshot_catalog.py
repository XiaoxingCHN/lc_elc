"""Create a portable, consistent SQLite checkpoint plus transfer manifest (stdlib)."""
import argparse,hashlib,json,pathlib,shutil,sqlite3,time

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--source',required=True);p.add_argument('--destination',required=True)
 a=p.parse_args();source=pathlib.Path(a.source).resolve();dest=pathlib.Path(a.destination).resolve()
 if source==dest:raise SystemExit('Source and destination must differ')
 if not source.is_file():raise SystemExit('Source does not exist')
 if dest.exists():raise SystemExit('Destination exists; refusing to overwrite checkpoint')
 dest.parent.mkdir(parents=True,exist_ok=True)
 if shutil.disk_usage(dest.parent).free<source.stat().st_size+2*1024**3:raise SystemExit('Insufficient disk space')
 src=sqlite3.connect(source,timeout=60);src.execute('PRAGMA query_only=ON')
 row=src.execute("SELECT value FROM meta WHERE key='status_snapshot'").fetchone()
 if not row or json.loads(row[0]).get('phase') not in ('stopped_by_user','details_blocked','discovered_details_finished','details_batch_finished'):
  raise SystemExit('Pause the collector before producing a cutover snapshot')
 target=sqlite3.connect(dest);last_print=[0.0]
 def progress(status,remaining,total):
  if time.monotonic()-last_print[0]>5:
   print(f'Backup: {total-remaining}/{total} pages',flush=True);last_print[0]=time.monotonic()
 try:
  src.backup(target,pages=4096,progress=progress,sleep=.01)
  checks=[r[0] for r in target.execute('PRAGMA quick_check')]
  if checks!=['ok']:raise RuntimeError('Snapshot integrity failed: '+str(checks))
  counts=dict(target.execute('SELECT market,count(*) FROM records GROUP BY market'))
  states=dict(target.execute('SELECT state,count(*) FROM cn_queue GROUP BY state'))
  target.execute('PRAGMA journal_mode=DELETE');target.commit()
 finally:target.close();src.close()
 digest=hashlib.sha256()
 with dest.open('rb') as f:
  for chunk in iter(lambda:f.read(4*1024**2),b''):digest.update(chunk)
 manifest={'source':str(source),'snapshot':str(dest),'bytes':dest.stat().st_size,'sha256':digest.hexdigest(),'records_by_market':counts,'queue_states':states,'quick_check':'ok'}
 dest.with_suffix('.manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(manifest,ensure_ascii=True,indent=2),flush=True)

if __name__=='__main__':main()
