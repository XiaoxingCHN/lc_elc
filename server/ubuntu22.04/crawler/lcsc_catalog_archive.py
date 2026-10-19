"""Resumeable public catalog archive with pooled HTTP, bounded scheduling and source-checked hints."""
import argparse
import concurrent.futures
import csv
import gzip
import hashlib
import json
import logging
import os
import pathlib
import re
import shutil
import signal
from logging.handlers import RotatingFileHandler
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

VENDOR=pathlib.Path(__file__).resolve().parent/'_vendor'
if VENDOR.exists():sys.path.insert(0,str(VENDOR))
try:import requests
except ImportError:requests=None

AGENT = 'LabInventoryCatalog/1.0'
NS = {'s': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
STATUS_INTERVAL_SECONDS=.2  # 5 Hz

class AccessBlocked(RuntimeError):
    pass

class StopRequested(RuntimeError):
    pass

def now():
    return datetime.now(timezone.utc).isoformat()

def next_data(data):
    html = data.decode('utf-8')
    match = re.search(r'<script\b[^>]*\bid="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not match:
        raise ValueError('No product data (possibly a verification page)')
    return json.loads(match.group(1))['props']['pageProps']

def parse_cn(data, expected=None):
    page = next_data(data)
    w = page['webData']
    r = w['productRecord']
    code = r.get('productCode') or r.get('selfProductCode')
    if not code or not re.fullmatch(r'C\d+', code) or (expected and code != expected):
        raise ValueError('Product code missing or mismatched')
    return code, {
        'part_number': code, 'product_id': str(r.get('productId') or r.get('selfProductId')),
        'mpn': r.get('productModel'), 'name': r.get('productName'),
        'brand': r.get('productGradePlateName'), 'category': r.get('productType'),
        'package': r.get('encapsulationModel'), 'price': page.get('price'),
        'encaption_price': r.get('encaptionPrice'), 'price_basis': 'page_display_price',
        'currency': 'CNY', 'stock': r.get('stockNumber'),
        'parameters': w.get('paramList'), 'category_path': w.get('currentCatalog'),
        'files': r.get('fileTypeVOList'), 'image_url': r.get('breviaryImageUrl'),
    }, {'webData':w, 'display_price':page.get('price'), 'similarProductRecommend':page.get('similarProductRecommend')}

def product_hints(value):
    """Only use explicit product code/id pairs provided by real page data."""
    found={}
    def walk(node):
        if isinstance(node,dict):
            code=node.get('productCode') or node.get('selfProductCode')
            pid=node.get('productId') or node.get('selfProductId')
            if isinstance(code,str) and re.fullmatch(r'C\d+',code) and re.fullmatch(r'\d+',str(pid or '')):
                found[code]=(code,str(pid),node.get('isMro'))
            for v in node.values():
                if isinstance(v,(dict,list)):walk(v)
        elif isinstance(node,list):
            for v in node:walk(v)
    walk(value)
    return list(found.values())

class Archive:
    def __init__(self, directory, delay=.05, workers=64, retries=3, transport='auto', use_hints=True):
        self.path = pathlib.Path(directory).resolve()
        self.path.mkdir(parents=True, exist_ok=True)
        (self.path/'raw').mkdir(exist_ok=True)
        self.delay = max(.05, delay)
        self.workers = min(64,max(1,workers))
        self.retries = max(1,min(5,retries))
        self.network_lock = threading.Lock()
        self.slots = {}
        self.blocked_counts = {}
        self.pause_event = threading.Event()
        self.pause_reason = None
        self.detail_stats = None
        self.rules = {}
        self.transport=('requests' if requests else 'urllib') if transport=='auto' else transport
        if self.transport=='requests' and requests is None:raise RuntimeError('Requests is not installed')
        self.use_hints=use_hints
        self.local=threading.local()
        self.sessions=[]
        self.cooldowns={}
        self.host_intervals={}
        self.host_successes={}
        self.network_metrics={'requests':0,'bytes_decoded':0,'network_seconds':0.0,'retries':0,'hint_updates':0,'requests_saved_by_hints':0}
        self.db = sqlite3.connect(self.path/'components.sqlite3', timeout=60)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT);
        CREATE TABLE IF NOT EXISTS sitemaps(url TEXT PRIMARY KEY,state TEXT DEFAULT 'pending',count INTEGER,error TEXT);
        CREATE TABLE IF NOT EXISTS products(code TEXT PRIMARY KEY,url TEXT NOT NULL,product_id TEXT,state TEXT DEFAULT 'pending',error TEXT);
        CREATE INDEX IF NOT EXISTS products_state ON products(state);
        CREATE TABLE IF NOT EXISTS records(code TEXT NOT NULL,market TEXT NOT NULL,source_url TEXT NOT NULL,fetched_at TEXT NOT NULL,fields_json TEXT NOT NULL,raw_json_gzip BLOB NOT NULL,PRIMARY KEY(code,market));
        CREATE INDEX IF NOT EXISTS records_market_time ON records(market,fetched_at);
        CREATE TABLE IF NOT EXISTS product_hints(code TEXT PRIMARY KEY,product_id TEXT NOT NULL,is_mro INTEGER,source_url TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS products_known_queue ON products(state) WHERE product_id IS NOT NULL;
        CREATE TABLE IF NOT EXISTS cn_queue(product_id TEXT PRIMARY KEY,code TEXT,source_url TEXT NOT NULL,state TEXT DEFAULT 'pending',error TEXT);
        CREATE INDEX IF NOT EXISTS cn_queue_state ON cn_queue(state);
        ''')
        restricted=self.db.execute("SELECT value FROM meta WHERE key='mro_access_blocked'").fetchone()
        self.mro_access_blocked=bool(restricted and json.loads(restricted[0]))
        self.mro_persisted=self.mro_access_blocked
        self.electronics_allowed=set()
        self.catalog_roots={}

    def load_electronics_filter(self):
        policy=json.loads((pathlib.Path(__file__).parent/'lcsc_electronics_filter.json').read_text(encoding='utf-8'))
        self.electronics_allowed=set(policy['allowed_root_ids'])
        path=self.path/'categories_cn.json'
        if path.exists():
            roots=json.loads(path.read_text(encoding='utf-8'))['categories']
            def walk(node,root_id,root_name):
                self.catalog_roots[int(node['catalogId'])]=(root_id,root_name)
                for child in node.get('sonCatalogList') or []:walk(child,root_id,root_name)
            for root in roots:walk(root,int(root['catalogId']),root['catalogName'])

    def classify_electronics(self,fields,raw):
        web=raw.get('webData',raw)
        if web.get('isMro') is True:return 'excluded',None,'MRO 工业品'
        cat=fields.get('category_path') or {}
        root=None
        for key in ('catalogId','parentId'):
            try:cid=int(cat.get(key))
            except (TypeError,ValueError):continue
            if cid in self.catalog_roots:root=self.catalog_roots[cid];break
            if cid in self.electronics_allowed:root=(cid,cat.get('catalogName','电子元器件'));break
        if root is None:return 'review',None,'分类无法映射，待审核'
        if root[0] in self.electronics_allowed:return 'include',root,'电子元器件分类白名单'
        return 'excluded',root,'非电子元器件分类：'+root[1]

    def refilter_existing(self):
        marker='electronics_filter_v1'
        if self.db.execute('SELECT 1 FROM meta WHERE key=?',(marker,)).fetchone():return
        with self.db:
            rows=self.db.execute("SELECT code,fields_json,raw_json_gzip FROM records WHERE market='cn'").fetchall()
            for code,fields_json,compressed in rows:
                fields=json.loads(fields_json);raw=json.loads(gzip.decompress(compressed))
                decision,root,reason=self.classify_electronics(fields,raw)
                fields.update(filter_decision=decision,filter_reason=reason,catalog_root_id=root[0] if root else None,catalog_root_name=root[1] if root else None)
                market='cn' if decision=='include' else 'cn_'+decision
                self.db.execute('UPDATE records SET market=?,fields_json=? WHERE code=? AND market=?',(market,json.dumps(fields,ensure_ascii=False),code,'cn'))
                if decision!='include':self.db.execute('UPDATE cn_queue SET state=?,error=? WHERE code=?',(decision,reason,code))
            self.db.execute('INSERT INTO meta VALUES (?,?)',(marker,'true'))

    def request(self,url):
        started=time.monotonic()
        try:
            if self.transport=='requests':
                if not hasattr(self.local,'session'):
                    session=requests.Session()
                    session.headers.update({'User-Agent':AGENT,'Accept':'text/html,application/xml,application/json,*/*','Accept-Encoding':'gzip, deflate'})
                    adapter=requests.adapters.HTTPAdapter(pool_connections=4,pool_maxsize=2,max_retries=0,pool_block=True)
                    session.mount('https://',adapter);session.mount('http://',adapter)
                    self.local.session=session
                    with self.network_lock:self.sessions.append(session)
                try:
                    with self.local.session.get(url,timeout=(10,30)) as response:
                        data=response.content
                        status=response.status_code;final=response.url;headers=response.headers.copy()
                except requests.exceptions.RequestException as error:
                    raise urllib.error.URLError(str(error)) from error
            else:
                req=urllib.request.Request(url,headers={'User-Agent':AGENT,'Accept':'text/html,application/xml,application/json,*/*'})
                with urllib.request.urlopen(req,timeout=30) as response:
                    data=response.read();status=response.status;final=response.url;headers=dict(response.headers)
            with self.network_lock:
                self.network_metrics['bytes_decoded']+=len(data)
            if status>=400:raise urllib.error.HTTPError(final,status,'HTTP '+str(status),headers,None)
            return status,final,headers,data
        finally:
            with self.network_lock:
                self.network_metrics['requests']+=1
                self.network_metrics['network_seconds']+=time.monotonic()-started

    def close_network(self):
        for session in self.sessions:session.close()

    def wait_for_slot(self,origin):
        # Reserve only a request that is ready to start. Pending requests cannot
        # all burst out of a shared Retry-After cooldown at the same instant.
        while True:
            if self.pause_event.is_set():raise StopRequested(self.pause_reason or 'Paused')
            if (self.path/'STOP').exists():raise StopRequested('STOP file present')
            with self.network_lock:
                current=time.monotonic()
                until=max(self.slots.get(origin,0),self.cooldowns.get(origin,0))
                if current>=until:
                    self.slots[origin]=current+self.host_intervals.get(origin,self.delay)
                    return
                wait=min(.2,until-current)
            self.pause_event.wait(wait)

    def slow_down(self,origin):
        with self.network_lock:
            old=self.host_intervals.get(origin,self.delay)
            self.host_intervals[origin]=min(10,max(self.delay,old*2))
            self.host_successes[origin]=0
        logging.warning('Adaptive slowdown for %s: request interval %.3fs',origin,self.host_intervals[origin])

    def fetch(self, url, robots=True):
        if (self.path/'STOP').exists():
            raise StopRequested('STOP file present; checkpoint preserved')
        if self.pause_event.is_set():
            raise StopRequested(self.pause_reason or 'Paused after repeated access restrictions')
        if shutil.disk_usage(self.path).free < 2*1024**3:
            self.pause_reason='Less than 2 GiB free disk space';self.pause_event.set()
            raise RuntimeError('Less than 2 GiB free disk space; checkpoint preserved')
        from urllib.parse import urlsplit
        origin = '{0.scheme}://{0.netloc}'.format(urlsplit(url))
        if robots and origin not in self.rules:
            raise RuntimeError('robots.txt must be loaded before concurrent requests: '+origin)
        if robots and not self.rules[origin].can_fetch(AGENT, url):
            self.pause_reason='Disallowed by robots.txt: '+url;self.pause_event.set()
            raise RuntimeError('Disallowed by robots.txt: '+url)
        # No proxy rotation, captcha solving, cookie impersonation or TLS disablement.
        for attempt in range(self.retries):
            self.wait_for_slot(origin)
            try:
                status,final_url,headers,data=self.request(url)
                if status in (203,403) or any(marker in data[:50000] for marker in
                        (b'var _xvasu',b'"code":403',b'aliyun_waf_aa',b'acw_sc__v2')):
                        self.raw(url,data)
                        from urllib.parse import urlsplit
                        final_path=urlsplit(final_url).path
                        if final_path.startswith('/mro/'):
                            self.mro_access_blocked=True
                            raise AccessBlocked('MRO WAF verification; restricted MRO scope: '+final_url)
                        self.blocked(origin,url)
                if status!=200:raise RuntimeError('Unexpected HTTP '+str(status))
                with self.network_lock:
                    self.blocked_counts[origin]=0
                    successes=self.host_successes.get(origin,0)+1;self.host_successes[origin]=successes
                    if successes>=100:
                        self.host_intervals[origin]=max(self.delay,self.host_intervals.get(origin,self.delay)*.9)
                        self.host_successes[origin]=0
                return data
            except urllib.error.HTTPError as error:
                if error.code==403:self.blocked(origin,url)
                if error.code not in (429,500,502,503,504):raise
                self.slow_down(origin)
                wait=min(120,max(5,2**(attempt+2)))
                retry_after=error.headers.get('Retry-After',wait)
                try:wait=max(wait,float(retry_after))
                except (ValueError,TypeError):
                    try:wait=max(wait,parsedate_to_datetime(str(retry_after)).timestamp()-time.time())
                    except (ValueError,TypeError,OverflowError):pass
                with self.network_lock:
                    self.slots[origin]=max(self.slots.get(origin,0),time.monotonic()+wait)
                    self.cooldowns[origin]=max(self.cooldowns.get(origin,0),time.monotonic()+wait)
                    self.network_metrics['retries']+=1
                logging.warning('HTTP %s: shared cooldown %.0fs for %s (attempt %s/%s)',error.code,wait,origin,attempt+1,self.retries)
                if attempt+1==self.retries:
                    if error.code==429:
                        self.pause_reason='Repeated HTTP 429 rate limiting: '+origin;self.pause_event.set()
                    raise
            except (urllib.error.URLError,TimeoutError) as error:
                if attempt+1==self.retries:raise
                logging.warning('Network retry %s/%s for %s: %s',attempt+1,self.retries,url,error)
                with self.network_lock:self.network_metrics['retries']+=1
                if self.pause_event.wait(2**attempt):raise StopRequested('Paused')

    def blocked(self, origin, url):
        with self.network_lock:
            self.blocked_counts[origin]=self.blocked_counts.get(origin,0)+1
            if self.blocked_counts[origin]>=3:
                self.pause_reason='Three consecutive verification responses: '+origin
                self.pause_event.set()
        raise AccessBlocked('Verification/access restriction: '+url)

    def prepare_rules(self, origins):
        for origin in origins:
            if origin in self.rules:continue
            body=self.fetch(origin+'/robots.txt',robots=False)
            rule=urllib.robotparser.RobotFileParser();rule.parse(body.decode('utf-8').splitlines())
            self.rules[origin]=rule
            crawl=rule.crawl_delay(AGENT)
            if crawl:self.delay=max(self.delay,crawl)

    def raw(self, url, data):
        filename = hashlib.sha256(url.encode()).hexdigest()+'.gz'
        (self.path/'raw'/filename).write_bytes(gzip.compress(data))

    def meta(self, key, value):
        self.db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)',(key,json.dumps(value,ensure_ascii=False)))
        self.db.commit()

    def status(self, phase):
        if self.detail_stats is None and self.db.execute('SELECT 1 FROM cn_queue LIMIT 1').fetchone():
            self.detail_stats={'chinese_full_catalog_complete':False,'coverage_note':'Chinese-only link discovery; full coverage not proven.','source_mode':'chinese_only','products_discovered':self.db.execute('SELECT count(*) FROM cn_queue').fetchone()[0],'product_states':dict(self.db.execute('SELECT state,count(*) FROM cn_queue GROUP BY state')),'records_by_market':dict(self.db.execute('SELECT market,count(*) FROM records GROUP BY market')),'sitemap_states':{}}
        stats = dict(self.detail_stats) if self.detail_stats else {
            'updated_at':now(), 'phase':phase, 'chinese_full_catalog_complete':False,
            'coverage_note':'International sitemap discovery does not prove full Chinese catalog coverage.',
            'products_discovered':self.db.execute('SELECT count(*) FROM products').fetchone()[0],
            'product_states':dict(self.db.execute('SELECT state,count(*) FROM products GROUP BY state')),
            'records_by_market':dict(self.db.execute('SELECT market,count(*) FROM records GROUP BY market')),
            'sitemap_states':dict(self.db.execute('SELECT state,count(*) FROM sitemaps GROUP BY state')),
        }
        stats.update(updated_at=now(),phase=phase,workers=self.workers,request_interval_per_host=self.delay)
        with self.network_lock:stats.update(transport=self.transport,network=dict(self.network_metrics),effective_intervals=dict(self.host_intervals))
        stats['refresh_hz']=1.0/STATUS_INTERVAL_SECONDS
        payload=json.dumps(stats,ensure_ascii=False,indent=2)
        # The database is the authoritative snapshot. A Windows reader holding
        # status.json must never interrupt product collection.
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO meta(key,value) VALUES (?,?)',('status_snapshot',payload))
        self.publish_status(payload)
        logging.info('%s',json.dumps(stats,ensure_ascii=True))
        return stats

    def publish_status(self,payload):
        temporary=self.path/('status.'+str(os.getpid())+'.tmp')
        try:
            temporary.write_text(payload,encoding='utf-8')
            for attempt in range(3):
                try:
                    temporary.replace(self.path/'status.json')
                    return True
                except OSError:
                    if attempt==2:raise
                    time.sleep(.025*(attempt+1))
        except OSError as error:
            logging.warning('Progress JSON update deferred; crawl continues, latest snapshot is in SQLite: %s',error)
            return False

    def catalog(self, cached=None):
        url = 'https://www.szlcsc.com/catalog.html'
        if not cached:self.prepare_rules(['https://www.szlcsc.com'])
        data = pathlib.Path(cached).read_bytes() if cached else self.fetch(url)
        pp = next_data(data)
        self.raw(url,data)
        self.meta('chinese_catalog_count', pp['catalogCount'])
        result = {'source_url':url,'fetched_at':now(),'catalog_count':pp['catalogCount'], 'categories':pp['catalogListData']}
        (self.path/'categories_cn.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')

    def discover(self, limit=None, cached=None):
        url = 'https://www.lcsc.com/sitemap.xml'
        self.prepare_rules(['https://www.lcsc.com'])
        data = pathlib.Path(cached).read_bytes() if cached else self.fetch(url)
        self.raw(url,data)
        root = ET.fromstring(data)
        urls = [node.text for node in root.findall('s:sitemap/s:loc',NS)
                if re.fullmatch(r'https://www\.lcsc\.com/sitemap-product-en-\d+\.xml',node.text or '')]
        if not urls:
            raise ValueError('No English product sitemaps in index')
        self.meta('international_sitemap_count',len(urls))
        self.db.executemany('INSERT OR IGNORE INTO sitemaps(url) VALUES (?)',[(u,) for u in urls])
        self.db.commit()
        pending = self.db.execute("SELECT url FROM sitemaps WHERE state != 'done' ORDER BY rowid").fetchall()
        for number,(map_url,) in enumerate(pending):
            if limit and number >= limit:
                break
            try:
                data = self.fetch(map_url)
                root = ET.fromstring(data)
                entries=[]
                for loc in root.findall('s:url/s:loc',NS):
                    match=re.fullmatch(r'https://www\.lcsc\.com/product-detail/(C\d+)\.html',loc.text or '')
                    if match:
                        entries.append((match.group(1),loc.text))
                if not entries:
                    raise ValueError('Empty or unrecognized product sitemap')
                self.raw(map_url,data)
                with self.db:
                    self.db.executemany('INSERT OR IGNORE INTO products(code,url) VALUES (?,?)',entries)
                    self.db.execute("UPDATE sitemaps SET state='done',count=?,error=NULL WHERE url=?",(len(entries),map_url))
            except Exception as error:
                with self.db:
                    self.db.execute("UPDATE sitemaps SET state='failed',error=? WHERE url=?",(str(error),map_url))
                self.status('discovery_blocked')
                raise
            self.status('discovering')
        self.status('discovery_finished' if not limit else 'discovery_batch_finished')

    def store(self, code, market, url, fields, raw):
        existed=self.db.execute('SELECT 1 FROM records WHERE code=? AND market=?',(code,market)).fetchone()
        self.db.execute('INSERT OR REPLACE INTO records VALUES (?,?,?,?,?,?)',
            (code,market,url,now(),json.dumps(fields,ensure_ascii=False),gzip.compress(json.dumps(raw,ensure_ascii=False).encode(),compresslevel=3)))
        if self.use_hints:self.save_hints(raw,url)
        if self.detail_stats and not existed:
            counts=self.detail_stats['records_by_market'];counts[market]=counts.get(market,0)+1

    def save_hints(self,raw,url):
        for hint_code,pid,is_mro in product_hints(raw):
            # Never overwrite a confirmed id; mismatches stay visible for diagnosis.
            self.db.execute('INSERT OR IGNORE INTO product_hints VALUES (?,?,?,?)',(hint_code,pid,is_mro,url))
            changed=self.db.execute("UPDATE products SET product_id=? WHERE code=? AND state='pending' AND product_id IS NULL",(pid,hint_code)).rowcount
            self.network_metrics['hint_updates']+=changed

    def fetch_product(self,row):
        code,url,pid=row[:3]
        is_mro=row[3] if len(row)>3 else None
        result={'code':code,'pid':pid,'records':[],'state':'done','error':None}
        try:
            if not pid:
                pp=next_data(self.fetch(url));w=pp['webData']
                if w.get('productCode')!=code or not w.get('productId'):
                    raise ValueError('International product code/id mismatch')
                pid=str(w['productId']);result['pid']=pid
                is_mro=w.get('isMro')
                fields={
                        'part_number':code,'product_id':pid,'mpn':w.get('productModel'),
                        'name':w.get('productNameEn') or w.get('productIntroEn'), 'brand':w.get('brandNameEn'),
                        'category':w.get('catalogName'),'package':w.get('encapStandard'),
                        'currency':w.get('currencyType'),'prices':w.get('productPriceList'),
                        'stock':w.get('stockNumber'),'parameters':w.get('paramVOList'),'datasheet_url':w.get('pdfUrl'),
                }
                result['records'].append(('international',url,fields,w))
            if is_mro and self.mro_access_blocked:
                raise AccessBlocked('MRO Chinese detail unavailable behind verified WAF restriction; international record preserved')
            cn_url='https://item.szlcsc.com/'+pid+'.html'
            data=self.fetch(cn_url)
            try:_,fields,w=parse_cn(data,code)
            except (ValueError,KeyError):
                self.raw(cn_url,data)
                raise
            result['records'].append(('cn',cn_url,fields,w))
        except Exception as error:
            result['error']=str(error)
            if isinstance(error,StopRequested):result['state']='intl_done' if result['pid'] else 'pending'
            elif isinstance(error,AccessBlocked):result['state']='blocked'
            elif isinstance(error,urllib.error.HTTPError) and error.code in (404,410):result['state']='unavailable'
            else:result['state']='failed'
        return result

    def transition(self,code,state,pid=None,error=None):
        old=self.db.execute('SELECT state FROM products WHERE code=?',(code,)).fetchone()[0]
        self.db.execute('UPDATE products SET state=?,product_id=COALESCE(?,product_id),error=? WHERE code=?',(state,pid,error,code))
        if self.detail_stats and old!=state:
            counts=self.detail_stats['product_states']
            counts[old]-=1;counts[state]=counts.get(state,0)+1

    def details(self, limit=None):
        self.prepare_rules(['https://www.lcsc.com','https://item.szlcsc.com'])
        with self.db:
            self.db.execute("UPDATE products SET state=CASE WHEN product_id IS NULL THEN 'pending' ELSE 'intl_done' END WHERE state='inflight'")
            if self.use_hints and not self.db.execute("SELECT 1 FROM meta WHERE key='hints_seeded_v1'").fetchone():
                for url,raw in self.db.execute('SELECT source_url,raw_json_gzip FROM records').fetchall():
                    self.save_hints(json.loads(gzip.decompress(raw)),url)
                self.db.execute("INSERT INTO meta VALUES ('hints_seeded_v1','true')")
        self.detail_stats=self.status('fetching_details')
        logging.info('Concurrent details started: %s workers, %.2fs request interval per host',self.workers,self.delay)
        start=time.monotonic();completed=0;submitted=0;last_status=0
        initial_cn=self.detail_stats['records_by_market'].get('cn',0)
        active={}
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.workers,thread_name_prefix='lcsc') as pool:
            while True:
                stopping=self.pause_event.is_set() or (self.path/'STOP').exists()
                if not stopping and len(active)<self.workers and (not limit or submitted<limit):
                    room=self.workers-len(active)
                    if limit:room=min(room,limit-submitted)
                    # A single-state indexed query avoids sorting millions of pending rows.
                    rows=self.db.execute("SELECT code,url,product_id FROM products WHERE state='intl_done' LIMIT ?",(room,)).fetchall()
                    if len(rows)<room:
                        rows+=self.db.execute("SELECT code,url,product_id FROM products INDEXED BY products_known_queue WHERE state='pending' AND product_id IS NOT NULL LIMIT ?",(room-len(rows),)).fetchall()
                    if len(rows)<room:
                        rows+=self.db.execute("SELECT code,url,product_id FROM products WHERE state='pending' AND product_id IS NULL LIMIT ?",(room-len(rows),)).fetchall()
                    for row in rows:
                        is_mro=None
                        if row[2]:
                            raw=self.db.execute("SELECT raw_json_gzip FROM records WHERE code=? AND market='international'",(row[0],)).fetchone()
                            if raw:is_mro=json.loads(gzip.decompress(raw[0])).get('isMro')
                            else:
                                hint=self.db.execute('SELECT is_mro FROM product_hints WHERE code=?',(row[0],)).fetchone()
                                if hint:is_mro=hint[0]
                                self.network_metrics['requests_saved_by_hints']+=1
                        row=(*row,is_mro)
                        self.transition(row[0],'inflight')
                        active[pool.submit(self.fetch_product,row)]=row[0];submitted+=1
                    self.db.commit()
                if not active:break
                ready,_=concurrent.futures.wait(active,timeout=STATUS_INTERVAL_SECONDS,return_when=concurrent.futures.FIRST_COMPLETED)
                for future in ready:
                    code=active.pop(future);result=future.result()
                    with self.db:
                        for market,url,fields,raw in result['records']:self.store(code,market,url,fields,raw)
                        self.transition(code,result['state'],result['pid'],result['error'])
                    if self.mro_access_blocked and not self.mro_persisted:
                        self.meta('mro_access_blocked',True);self.mro_persisted=True
                    completed+=1
                    if result['state']=='done':logging.info('Saved Chinese detail %s',code)
                    elif result['error']:logging.warning('Product %s -> %s: %s',code,result['state'],result['error'])
                if time.monotonic()-last_status>=STATUS_INTERVAL_SECONDS:
                    self.detail_stats.update(completed_this_run=completed,products_per_minute=round(completed/max(1,time.monotonic()-start)*60,1),cn_per_minute=round((self.detail_stats['records_by_market'].get('cn',0)-initial_cn)/max(1,time.monotonic()-start)*60,1),active_workers=len(active))
                    self.status('fetching_details');last_status=time.monotonic()
        self.detail_stats.update(completed_this_run=completed,products_per_minute=round(completed/max(1,time.monotonic()-start)*60,1),cn_per_minute=round((self.detail_stats['records_by_market'].get('cn',0)-initial_cn)/max(1,time.monotonic()-start)*60,1),active_workers=0)
        if self.pause_event.is_set():
            logging.error('Worker paused: %s',self.pause_reason);self.status('details_blocked')
        elif (self.path/'STOP').exists():self.status('stopped_by_user')
        else:self.status('details_batch_finished' if limit else 'discovered_details_finished')

    def cn_enqueue(self,pid,code,source_url):
        if not re.fullmatch(r'\d+',str(pid)):return
        if code is not None and not re.fullmatch(r'C\d+',code):return
        changed=self.db.execute('INSERT OR IGNORE INTO cn_queue(product_id,code,source_url) VALUES (?,?,?)',(str(pid),code,source_url)).rowcount
        if self.detail_stats and changed:
            self.detail_stats['products_discovered']+=1
            counts=self.detail_stats['product_states'];counts['pending']=counts.get('pending',0)+1

    def cn_fetch_product(self,row):
        pid,expected=row
        url='https://item.szlcsc.com/'+pid+'.html'
        result={'pid':pid,'state':'done','error':None,'record':None,'hints':[]}
        try:
            data=self.fetch(url)
            try:code,fields,raw=parse_cn(data,expected)
            except (ValueError,KeyError):self.raw(url,data);raise
            if fields['product_id']!=pid:raise ValueError('Chinese product id mismatched')
            decision,root,reason=self.classify_electronics(fields,raw)
            fields.update(filter_decision=decision,filter_reason=reason,catalog_root_id=root[0] if root else None,catalog_root_name=root[1] if root else None)
            result['market']='cn' if decision=='include' else 'cn_'+decision
            if decision!='include':result.update(state=decision,error=reason)
            result['record']=(code,url,fields,raw)
            if decision=='include':result['hints']=product_hints(raw)
        except Exception as error:
            result['error']=str(error)
            if isinstance(error,StopRequested):result['state']='pending'
            elif isinstance(error,AccessBlocked):result['state']='blocked'
            elif isinstance(error,urllib.error.HTTPError) and error.code in (404,410):result['state']='unavailable'
            else:result['state']='failed'
        return result

    def chinese(self,limit=None):
        self.use_hints=False  # Chinese queue owns discovery; no international product requests.
        self.prepare_rules(['https://www.szlcsc.com','https://item.szlcsc.com'])
        if not self.db.execute('SELECT 1 FROM cn_queue LIMIT 1').fetchone():
            self.catalog()
            url='https://www.szlcsc.com/'
            data=self.fetch(url);self.raw(url,data)
            with self.db:
                for pid in set(re.findall(r'(?:https?:)?//item\.szlcsc\.com/(\d+)\.html',data.decode('utf-8'))):
                    self.cn_enqueue(pid,None,url)
                try:
                    for code,pid,is_mro in product_hints(next_data(data)):
                        if not is_mro:self.cn_enqueue(pid,code,url)
                except (ValueError,KeyError):pass
            if not self.db.execute('SELECT 1 FROM cn_queue LIMIT 1').fetchone():raise RuntimeError('No Chinese product seeds found')
        with self.db:self.db.execute("UPDATE cn_queue SET state='pending' WHERE state='inflight'")
        self.load_electronics_filter()
        self.refilter_existing()
        self.detail_stats={
            'chinese_full_catalog_complete':False,'coverage_note':'Chinese-only link discovery; full Chinese catalog coverage is not proven.',
            'source_mode':'chinese_only','products_discovered':self.db.execute('SELECT count(*) FROM cn_queue').fetchone()[0],
            'product_states':dict(self.db.execute('SELECT state,count(*) FROM cn_queue GROUP BY state')),
            'records_by_market':dict(self.db.execute('SELECT market,count(*) FROM records GROUP BY market')),'sitemap_states':{},
        }
        initial_cn=self.detail_stats['records_by_market'].get('cn',0)
        started=time.monotonic();completed=0;submitted=0;active={};last_status=0
        self.status('fetching_details')
        logging.info('Chinese-only crawl started: %s workers; seeds and recommendations from Chinese pages',self.workers)
        def state(pid,new,error=None):
            old=self.db.execute('SELECT state FROM cn_queue WHERE product_id=?',(pid,)).fetchone()[0]
            self.db.execute('UPDATE cn_queue SET state=?,error=? WHERE product_id=?',(new,error,pid))
            if old!=new:
                counts=self.detail_stats['product_states'];counts[old]-=1;counts[new]=counts.get(new,0)+1
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.workers,thread_name_prefix='lcsc-cn') as pool:
            while True:
                stopping=self.pause_event.is_set() or (self.path/'STOP').exists()
                if not stopping and len(active)<self.workers and (not limit or submitted<limit):
                    room=self.workers-len(active)
                    if limit:room=min(room,limit-submitted)
                    rows=self.db.execute("SELECT product_id,code FROM cn_queue WHERE state='pending' LIMIT ?",(room,)).fetchall()
                    with self.db:
                        for row in rows:
                            state(row[0],'inflight');active[pool.submit(self.cn_fetch_product,row)]=row[0];submitted+=1
                if not active:break
                ready,_=concurrent.futures.wait(active,timeout=STATUS_INTERVAL_SECONDS,return_when=concurrent.futures.FIRST_COMPLETED)
                for future in ready:
                    pid=active.pop(future);result=future.result()
                    with self.db:
                        if result['record']:
                            code,url,fields,raw=result['record'];self.store(code,result.get('market','cn'),url,fields,raw)
                            self.db.execute('UPDATE cn_queue SET code=? WHERE product_id=?',(code,pid))
                            for hc,hp,is_mro in result['hints']:
                                if not is_mro:self.cn_enqueue(hp,hc,url)
                            if result['state']=='done':logging.info('Saved Chinese detail %s | product_id=%s | category=%s',code,pid,fields.get('catalog_root_name'))
                        state(pid,result['state'],result['error'])
                    if result['error']:logging.warning('Chinese product %s -> %s: %s',pid,result['state'],result['error'])
                    completed+=1
                if time.monotonic()-last_status>=STATUS_INTERVAL_SECONDS:
                    elapsed=max(1,time.monotonic()-started)
                    self.detail_stats.update(completed_this_run=completed,cn_per_minute=round((self.detail_stats['records_by_market'].get('cn',0)-initial_cn)/elapsed*60,1),active_workers=len(active))
                    self.status('fetching_details');last_status=time.monotonic()
        self.detail_stats.update(active_workers=0,completed_this_run=completed,cn_per_minute=round((self.detail_stats['records_by_market'].get('cn',0)-initial_cn)/max(1,time.monotonic()-started)*60,1))
        if self.pause_event.is_set():self.status('details_blocked')
        elif (self.path/'STOP').exists():self.status('stopped_by_user')
        else:self.status('details_batch_finished' if limit else 'discovered_details_finished')

    def export(self):
        keys=['part_number','product_id','mpn','name','brand','category','catalog_root_name','filter_decision','filter_reason','package','price','encaption_price','price_basis','currency','stock','source_url','fetched_at','parameters','files']
        with (self.path/'components_cn.csv').open('w',encoding='utf-8-sig',newline='') as f, (self.path/'components_cn.jsonl').open('w',encoding='utf-8') as j:
            writer=csv.DictWriter(f,fieldnames=keys,extrasaction='ignore');writer.writeheader()
            for url,fetched,fields in self.db.execute("SELECT source_url,fetched_at,fields_json FROM records WHERE market='cn' ORDER BY code"):
                d=json.loads(fields);d.update(source_url=url,fetched_at=fetched)
                j.write(json.dumps(d,ensure_ascii=False)+'\n')
                for k in ('parameters','files'):
                    if d.get(k) is not None:d[k]=json.dumps(d[k],ensure_ascii=False)
                writer.writerow(d)

def main():
    global STATUS_INTERVAL_SECONDS
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['catalog','discover','details','chinese','run','export','status','retry-failed'])
    p.add_argument('--output')
    p.add_argument('--delay',type=float,default=.05)
    p.add_argument('--workers',type=int,default=64)
    p.add_argument('--transport',choices=['auto','requests','urllib'],default='auto')
    p.add_argument('--no-hints',action='store_true')
    p.add_argument('--no-export',action='store_true',help='Skip large CSV/JSONL exports on daemon shutdown')
    p.add_argument('--status-interval',type=float,default=STATUS_INTERVAL_SECONDS)
    p.add_argument('--retries',type=int,default=3)
    p.add_argument('--limit',type=int)
    p.add_argument('--cached-catalog');p.add_argument('--cached-index')
    a=p.parse_args()
    if a.status_interval<.05:p.error('--status-interval must be at least 0.05 seconds')
    STATUS_INTERVAL_SECONDS=a.status_interval
    if not a.output:
        chinese_dir=pathlib.Path(__file__).parent/'lcsc_cn_archive'
        a.output=str(chinese_dir if a.command=='chinese' or (a.command in ('status','export','retry-failed') and chinese_dir.exists()) else pathlib.Path(__file__).parent/'lcsc_archive')
    archive=Archive(a.output,a.delay,a.workers,a.retries,a.transport,not a.no_hints)
    lock=None
    if a.command not in ('status','export'):
        lock=(archive.path/'worker.lock').open('a+b')
        lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0)
        if os.name=='nt':
            import msvcrt
            try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
            except OSError:raise SystemExit('Another archive worker is already running')
        else:
            import fcntl
            try:fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            except OSError:raise SystemExit('Another archive worker is already running')
    if os.name!='nt':
        def request_stop(signum,frame):
            (archive.path/'STOP').touch()
        signal.signal(signal.SIGTERM,request_stop)
        signal.signal(signal.SIGINT,request_stop)
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(message)s',handlers=[RotatingFileHandler(archive.path/'crawl.log',maxBytes=20*1024*1024,backupCount=5,encoding='utf-8'),logging.StreamHandler()])
    try:
        if a.command in ('catalog','run'):archive.catalog(a.cached_catalog)
        if a.command in ('discover','run'):archive.discover(a.limit if a.command=='discover' else None,a.cached_index)
        if a.command in ('details','run'):archive.details(a.limit if a.command=='details' else None)
        if a.command=='chinese':archive.chinese(a.limit)
        if a.command=='retry-failed':
            with archive.db:
                archive.db.execute("UPDATE products SET state=CASE WHEN product_id IS NULL THEN 'pending' ELSE 'intl_done' END WHERE state='failed'")
                archive.db.execute("UPDATE cn_queue SET state='pending' WHERE state='failed'")
        if a.command=='export' or (not a.no_export and a.command in ('run','details','chinese')):archive.export()
        if a.command=='status':print(json.dumps(archive.status('snapshot'),ensure_ascii=True,indent=2))
    except Exception:
        logging.exception('Archive stopped; checkpoint preserved')
        if not a.no_export:archive.export()
        raise SystemExit(1)
    finally:
        archive.db.close()
        archive.close_network()
        if lock:lock.close()

if __name__=='__main__':main()
