#!/usr/bin/env python3
"""Validate a paused migration snapshot before the first write; no network."""
import hashlib,json,pathlib,sqlite3,sys
p=pathlib.Path(sys.argv[1]).resolve()
m=json.loads((p/'components.manifest.json').read_text(encoding='utf-8'))
f=p/'components.sqlite3'
assert f.stat().st_size==m['bytes'], '数据库大小不符'
h=hashlib.sha256()
with f.open('rb') as src:
    for chunk in iter(lambda:src.read(4*1024**2),b''):h.update(chunk)
assert h.hexdigest()==m['sha256'], 'SHA256不符'
c=sqlite3.connect(f.as_uri()+'?mode=ro',uri=True)
assert c.execute('PRAGMA quick_check').fetchone()[0]=='ok', '数据库完整性检查失败'
assert dict(c.execute('SELECT market,count(*) FROM records GROUP BY market'))==m['records_by_market'], '记录计数不符'
assert dict(c.execute('SELECT state,count(*) FROM cn_queue GROUP BY state'))==m['queue_states'], '队列计数不符'
filter_mark=c.execute("SELECT value FROM meta WHERE key='electronics_filter_v1'").fetchone()
assert filter_mark and str(filter_mark[0]).strip().lower()=='true', '电子元器件筛选未完成，不允许直接启动'
c.close()
categories=json.loads((p/'categories_cn.json').read_text(encoding='utf-8'))
assert categories.get('categories'), '分类缓存为空'
print('快照SHA256、数据库完整性、计数、筛选标记和分类缓存均通过。')
