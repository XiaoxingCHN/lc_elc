#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把立创中文资料快照导入 Odoo PostgreSQL 的只读索引（lab_catalog_item / _param）。

设计约束（root 契约）
--------------------
* **原快照 SQLite 只读**，本工具从不写它（``mode=ro`` URI 打开）。
* **不在请求路径里解析 JSON**：这里一次性扁平化写入索引表与参数表。
* **不把全库读进内存**：按 ``code`` 流式分批（默认 500 行/批），每批临时表 COPY + upsert。
* **幂等可断点续跑**：按 ``source_fingerprint`` 跳过未变行；``--resume-from`` 从断点继续。
* ``cn_excluded`` 的市场**不导入**（不展示）。
* ``raw_json_gzip`` **只在导入期**为补真实图片/手册而解压，且仅当 ``--scan-raw`` 打开。

用法
----
    python3 import_catalog.py --snapshot /path/components.sqlite3 \
        --categories /path/categories_cn.json \
        --dbname LcHardwareHouse --dbhost /var/run/postgresql --dbuser odoo

    # 先小批试跑
    python3 import_catalog.py ... --limit 5000

    # 全量并按指纹跳过未变行，结束后打印覆盖率校验
    python3 import_catalog.py ... --verify
"""
import argparse
import gzip
import hashlib
import io
import json
import os
import re
import sqlite3
import sys
import time
import unicodedata
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

try:
    import psycopg2
    from psycopg2 import sql as pgsql
except ImportError:  # pragma: no cover
    print('需要 psycopg2：请用 Odoo venv 里的 python 运行本脚本', file=sys.stderr)
    raise

MARKET_CN = 'cn'
BATCH = 500

# ---------------------------------------------------------------- identity
_CATALOG_RE = re.compile(r'^C([0-9]+)$')


def normalize_code(value):
    if value is None:
        return None
    text = unicodedata.normalize('NFKC', str(value)).strip().strip('\ufeff').replace('\u200b', '')
    text = ''.join(text.split()).upper()
    m = _CATALOG_RE.match(text)
    if not m or int(m.group(1)) <= 0:
        return None
    return 'C' + m.group(1)


# ---------------------------------------------------------------- scalars
def _clean_scalar(value):
    """去掉空白与千位分隔逗号；空值（含 '-' 这类占位）由调用方判非法。"""
    if value is None:
        return None
    text = str(value).strip().replace(',', '')
    text = ''.join(text.split())
    return text or None


def integer_or_none(value):
    """库存列：清洗后能整出整数就返回 int，否则 None。

    例：'1,234' -> 1234；'12' -> 12；'-' / '' / 'abc' -> None。
    """
    text = _clean_scalar(value)
    if text is None:
        return None
    try:
        dec = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if not dec.is_finite() or dec != dec.to_integral_value():
        return None
    return int(dec)


def numeric_or_none(value):
    """价格列：清洗后是合法有限数字就返回规范文本，否则 None。

    例：'12.34' -> '12.34'；'1,234.50' -> '1234.50'；'-' / '' -> None。
    """
    text = _clean_scalar(value)
    if text is None:
        return None
    try:
        dec = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if not dec.is_finite():
        return None
    return text


# ---------------------------------------------------------------- flatten
BRAND_RE = re.compile(r'^(.*?)\s*[\(（]([^)）]*)[\)）]\s*$')


def split_brand(raw):
    """'VISHAY(威世)' -> ('VISHAY', '威世')。"""
    if not raw:
        return ('', '')
    m = BRAND_RE.match(str(raw).strip())
    if m:
        return (m.group(1).strip(), m.group(2).strip())
    return (str(raw).strip(), '')


IMAGE_HOST_OK = ('alimg.szlcsc.com', 'atta.szlcsc.com')


def pick_url(value):
    if not value:
        return None
    if isinstance(value, list):
        for v in value:
            got = pick_url(v)
            if got:
                return got
        return None
    if isinstance(value, dict):
        for key in ('fileUrl', 'url', 'imageUrl', 'src'):
            if value.get(key):
                return pick_url(value[key])
        for v in value.values():
            got = pick_url(v)
            if got:
                return got
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.startswith('//'):
        return 'https:' + text
    if text.startswith('/'):
        return 'https://www.szlcsc.com' + text
    if text.startswith('http://'):
        return 'https://' + text[7:]
    return text if text.startswith('https://') else None


def flatten_files(files):
    out = []
    datasheet = None
    for f in files or []:
        if not isinstance(f, dict):
            continue
        ftype = f.get('fileType') or ''
        for d in (f.get('detailVOList') or []):
            if not isinstance(d, dict):
                continue
            url = pick_url(d.get('fileUrl'))
            item = {'fileType': ftype, 'fileName': d.get('fileName') or '', 'fileUrl': url}
            out.append(item)
            if ftype == 'pdf_property' and datasheet is None and url:
                datasheet = url
    if datasheet is None:
        for item in out:
            if item['fileUrl']:
                datasheet = item['fileUrl']
                break
    return out, datasheet


def search_text_of(code, name, mpn, brand, category, package):
    parts = [code or '', name or '', mpn or '', brand or '', category or '', package or '']
    return ' '.join(p for p in parts if p).lower()[:512]


def extract_extra_image(raw_gzip, log=None):
    """从原 gzip 原始 JSON 里尽力找回真实图片地址。

    只在导入期调用（``--scan-raw``）。绝不写入任何非实测地址，找不到就返回 None，
    由前端显示明确占位——**不生成假器件图**。
    """
    if not raw_gzip:
        return None
    try:
        data = gzip.decompress(raw_gzip)
        obj = json.loads(data.decode('utf-8', 'ignore'))
    except Exception:
        return None

    found = []

    def walk(node, depth=0):
        if depth > 6 or len(found) > 4:
            return
        if isinstance(node, dict):
            for k, v in node.items():
                kl = str(k).lower()
                if isinstance(v, str) and ('image' in kl or 'img' in kl or 'pic' in kl):
                    url = pick_url(v)
                    if url and any(h in url for h in IMAGE_HOST_OK):
                        found.append(url)
                else:
                    walk(v, depth + 1)
        elif isinstance(node, list):
            for v in node[:20]:
                walk(v, depth + 1)

    walk(obj)
    return found[0] if found else None


# ---------------------------------------------------------------- categories
def load_categories(path):
    """返回 (nodes, parent_of)：nodes 按 catalogId 索引。"""
    with open(path, 'r', encoding='utf-8') as fh:
        data = json.load(fh)
    nodes = {}
    parent_of = {}

    def walk(items, level):
        for it in items or []:
            if not isinstance(it, dict):
                continue
            cid = it.get('catalogId')
            if cid is None:
                continue
            if cid in nodes:
                continue
            nodes[cid] = {
                'catalog_id': int(cid),
                'parent_id': it.get('parentId') or None,
                'code': it.get('catalogCode') or '',
                'name': it.get('catalogName') or '',
                'name_en': it.get('catalogNameEn') or it.get('catalogNameEN') or '',
                'level': level,
                'sort': it.get('sort') or 0,
                'product_count': it.get('groupProductCount') or 0,
            }
            if it.get('parentId'):
                parent_of[int(cid)] = int(it['parentId'])
            for key in ('sonCatalogList', 'children', 'child'):
                if isinstance(it.get(key), list):
                    walk(it[key], level + 1)
                    break

    walk(data.get('categories') or [], 1)
    return nodes, parent_of


def path_of(cid, parent_of):
    chain = []
    seen = set()
    cur = cid
    while cur and cur not in seen:
        seen.add(cur)
        chain.append(cur)
        cur = parent_of.get(cur)
    chain.reverse()
    return '/' + '/'.join(str(x) for x in chain) + '/' if chain else ''


def pg_path_of(cid, parent_of, cat_pg):
    """祖先路径，但用 **Odoo(PG) id** 组成。

    分类筛选统一用 PG id（外部 API 的 id/category_id 也是 PG id），
    所以 item.category_path 必须存 PG id 路径，否则点击分类会失配、
    且只按 '/cid/' 前缀匹配会漏掉下级。
    """
    chain, seen = [], set()
    cur = cid
    while cur and cur not in seen:
        seen.add(cur)
        chain.append(cur)
        cur = parent_of.get(cur)
    chain.reverse()
    ids = [str(cat_pg[m]) for m in chain if m in cat_pg]
    return '/' + '/'.join(ids) + '/' if ids else ''


def import_categories(cur, nodes, parent_of):
    if not nodes:
        return {}
    now = datetime.now(timezone.utc)
    # 先 upsert 所有节点（父引用稍后补），再回填 parent_id
    rows = [(n['catalog_id'], n['code'], n['name'], n['name_en'], n['level'],
             n['sort'], n['product_count'], 1, now, 1, now) for n in nodes.values()]
    with cur.connection.cursor() as c2:
        # 临时表在事务内只建一次；每批 TRUNCATE 复用。
        # 早期实现在分块循环里反复 CREATE，第二批就报 DuplicateTable 并中断导入。
        c2.execute('CREATE TEMP TABLE IF NOT EXISTS tmp_cat (catalog_id int, code text, name text,'
                   ' name_en text, level int, sort int, product_count int, create_uid int,'
                   ' create_date timestamptz, write_uid int, write_date timestamptz) ON COMMIT DROP')
        for chunk_start in range(0, len(rows), 1000):
            chunk = rows[chunk_start:chunk_start + 1000]
            c2.execute('TRUNCATE tmp_cat')
            buf = '\n'.join('\t'.join('\\N' if v is None else str(v).replace('\t', ' ').replace('\n', ' ')
                                      for v in r) for r in chunk)
            c2.copy_expert('COPY tmp_cat FROM STDIN', io.StringIO(buf))
            c2.execute("""
                INSERT INTO lab_catalog_category
                  (catalog_id, code, name, name_en, level, sort, product_count,
                   create_uid, create_date, write_uid, write_date)
                SELECT catalog_id, code, name, name_en, level, sort, product_count,
                       create_uid, create_date, write_uid, write_date FROM tmp_cat
                ON CONFLICT (catalog_id) DO UPDATE SET
                  code=EXCLUDED.code, name=EXCLUDED.name, name_en=EXCLUDED.name_en,
                  level=EXCLUDED.level, sort=EXCLUDED.sort,
                  product_count=EXCLUDED.product_count, write_date=EXCLUDED.write_date
            """)
    # 回填父子关系
    for cid, pid in parent_of.items():
        cur.execute("""
            UPDATE lab_catalog_category c SET parent_id = p.id
            FROM lab_catalog_category p
            WHERE c.catalog_id = %s AND p.catalog_id = %s
        """, (cid, pid))
    # catalog_id -> pg id
    cur.execute('SELECT catalog_id, id FROM lab_catalog_category')
    cat_pg = {int(r[0]): int(r[1]) for r in cur.fetchall()}
    # 回填 PG id 祖先路径（供"含下级"筛选，必须用 PG id）
    for cid in nodes:
        cur.execute('UPDATE lab_catalog_category SET pg_path = %s WHERE catalog_id = %s',
                    (pg_path_of(cid, parent_of, cat_pg), cid))
    return cat_pg


# ---------------------------------------------------------------- main import
ITEM_COLUMNS = [
    'catalog_code', 'market', 'product_id_ext', 'source_url', 'name', 'mpn', 'brand',
    'brand_code', 'package', 'category_id', 'category_name', 'category_path',
    'catalog_stock', 'price', 'currency', 'price_basis', 'image_url', 'has_image',
    'datasheet_url', 'has_datasheet', 'doc_files_json', 'param_count', 'search_text',
    'fetched_at', 'source_fingerprint', 'import_run_id',
    # 注意：hs_rank / lab_quantity / lab_available_quantity / bound_template_count / has_stock
    # 已从模型删除（库存改为请求时实时聚合）。导入列必须与模型一致，否则
    # INSERT 会报 UndefinedColumn 并且整批失败。
    'create_uid', 'create_date', 'write_uid', 'write_date',
]
PARAM_COLUMNS = ['catalog_code', 'market', 'sequence', 'code', 'name', 'value', 'detail_value']


def create_temp_tables(cur):
    """建临时表。

    **必须 ON COMMIT PRESERVE ROWS**：这些表在循环外只建一次，
    若用 ON COMMIT DROP，第一批 pg.commit() 之后临时表就消失，后续批次必然失败。
    每批开始时用 TRUNCATE 复用即可。
    """
    cur.execute("""
        CREATE TEMP TABLE IF NOT EXISTS tmp_item (
            catalog_code text, market text, product_id_ext text, source_url text,
            name text, mpn text, brand text, brand_code text, package text,
            category_id int, category_name text, category_path text,
            catalog_stock int, price numeric, currency text, price_basis text,
            image_url text, has_image boolean, datasheet_url text, has_datasheet boolean,
            doc_files_json text, param_count int, search_text text,
            fetched_at timestamptz, source_fingerprint text, import_run_id int,
            create_uid int, create_date timestamptz, write_uid int, write_date timestamptz
        ) ON COMMIT PRESERVE ROWS
    """)
    cur.execute("""
        CREATE TEMP TABLE IF NOT EXISTS tmp_param (
            catalog_code text, market text, sequence int, code text, name text,
            value text, detail_value text
        ) ON COMMIT PRESERVE ROWS
    """)


def upsert_batch(cur, items, params_map):
    if not items:
        return 0
    now = datetime.now(timezone.utc)

    def cell(v):
        # COPY text 的转义：先转义反斜线，再转义控制字符；NULL 用 \N
        if v is None:
            return '\\N'
        if isinstance(v, bool):
            return 't' if v else 'f'
        s = str(v)
        return (s.replace('\\', '\\\\').replace('\t', '\\t')
                 .replace('\n', '\\n').replace('\r', '\\r'))

    # 临时表是 ON COMMIT PRESERVE ROWS（在循环外只建一次），每批复用前清空
    cur.execute('TRUNCATE tmp_item, tmp_param')

    buf = '\n'.join('\t'.join(cell(v) for v in r) for r in items)
    cur.copy_expert('COPY tmp_item (catalog_code, market, product_id_ext, source_url, name, mpn, brand,'
                    ' brand_code, package, category_id, category_name, category_path, catalog_stock,'
                    ' price, currency, price_basis, image_url, has_image, datasheet_url, has_datasheet,'
                    ' doc_files_json, param_count, search_text, fetched_at, source_fingerprint,'
                    ' import_run_id, create_uid, create_date, write_uid, write_date)'
                    ' FROM STDIN', io.StringIO(buf))

    cur.execute("""
        INSERT INTO lab_catalog_item
          (catalog_code, market, product_id_ext, source_url, name, mpn, brand, brand_code,
           package, category_id, category_name, category_path, catalog_stock, price, currency,
           price_basis, image_url, has_image, datasheet_url, has_datasheet, doc_files_json,
           param_count, search_text, fetched_at, source_fingerprint, import_run_id,
           create_uid, create_date, write_uid, write_date)
        SELECT catalog_code, market, product_id_ext, source_url, name, mpn, brand, brand_code,
               package, category_id, category_name, category_path, catalog_stock, price, currency,
               price_basis, image_url, has_image, datasheet_url, has_datasheet, doc_files_json,
               param_count, search_text, fetched_at, source_fingerprint, import_run_id,
               create_uid, create_date, write_uid, write_date
        FROM tmp_item
        ON CONFLICT (catalog_code, market) DO UPDATE SET
          product_id_ext=EXCLUDED.product_id_ext, source_url=EXCLUDED.source_url,
          name=EXCLUDED.name, mpn=EXCLUDED.mpn, brand=EXCLUDED.brand,
          brand_code=EXCLUDED.brand_code, package=EXCLUDED.package,
          category_id=EXCLUDED.category_id, category_name=EXCLUDED.category_name,
          category_path=EXCLUDED.category_path, catalog_stock=EXCLUDED.catalog_stock,
          price=EXCLUDED.price, currency=EXCLUDED.currency, price_basis=EXCLUDED.price_basis,
          image_url=COALESCE(EXCLUDED.image_url, lab_catalog_item.image_url),
          has_image=EXCLUDED.has_image OR (EXCLUDED.image_url IS NULL AND lab_catalog_item.has_image),
          datasheet_url=COALESCE(EXCLUDED.datasheet_url, lab_catalog_item.datasheet_url),
          has_datasheet=EXCLUDED.has_datasheet,
          doc_files_json=EXCLUDED.doc_files_json, param_count=EXCLUDED.param_count,
          search_text=EXCLUDED.search_text, fetched_at=EXCLUDED.fetched_at,
          source_fingerprint=EXCLUDED.source_fingerprint, write_uid=EXCLUDED.write_uid,
          write_date=EXCLUDED.write_date
    """)

    # 参数：整体替换该批器件的参数（大件参数是列表，逐条 upsert 不如整批替换干净）
    if params_map:
        pb = []
        for (code, market), plist in params_map.items():
            for seq, (pcode, pname, pvalue, pdetail) in enumerate(plist, start=1):
                pb.append('\t'.join(cell(v) for v in
                                   (code, market, seq, pcode, pname, pvalue, pdetail)))
        if pb:
            cur.copy_expert('COPY tmp_param (catalog_code, market, sequence, code, name, value,'
                            ' detail_value) FROM STDIN', io.StringIO('\n'.join(pb)))
            cur.execute("""
                DELETE FROM lab_catalog_param p
                USING tmp_item t, lab_catalog_item i
                WHERE i.catalog_code = t.catalog_code AND i.market = t.market
                  AND p.item_id = i.id
            """)
            cur.execute("""
                INSERT INTO lab_catalog_param
                  (item_id, sequence, code, name, value, detail_value,
                   create_uid, create_date, write_uid, write_date)
                SELECT i.id, t.sequence, t.code, t.name, t.value, t.detail_value,
                       1, now(), 1, now()
                FROM tmp_param t
                JOIN lab_catalog_item i ON i.catalog_code = t.catalog_code AND i.market = t.market
            """)
    return len(items)


def fingerprint(fields_json):
    return hashlib.sha256(fields_json.encode('utf-8', 'ignore')).hexdigest()[:32]


def pick_code_index(sqc):
    """探测可安全用于 ``ORDER BY code`` 的 ``(code, market)`` 索引名。

    **只读探测，不改快照、不建索引**（root 明确要求不依赖新建 snapshot 索引）。

    为什么必须这么做：snapshot 上唯一的次要索引是
    ``records_market_time(market, fetched_at)``。若让 SQLite 自选，
    ``WHERE market=? AND code>? ORDER BY code`` 会变成
    ``SEARCH records USING INDEX records_market_time (market=?)``
    + ``USE TEMP B-TREE FOR ORDER BY`` —— 也就是先把整库
    ``fields_json``/``raw_json_gzip``（约 3.5 GB）临时排序，
    首批要等 20 秒以上，完全违背"流式、低内存、快速首批"。
    PK 索引 ``sqlite_autoindex_records_1(code, market)`` 则给出
    ``SEARCH ... USING INDEX ...(code>?)``，无临时排序，首批 0 毫秒。
    """
    try:
        rows = sqc.execute("PRAGMA index_list('records')").fetchall()
    except Exception as exc:                      # pragma: no cover
        print('   索引探测失败（退回默认计划）：%s' % exc)
        return None
    for row in rows:
        name = row[1]
        try:
            cols = [r[2] for r in
                    sqc.execute("PRAGMA index_info('%s')" % name).fetchall()]
        except Exception:
            continue
        if cols[:2] == ['code', 'market'] or cols[:2] == ['market', 'code']:
            return name
    return None


def main():
    ap = argparse.ArgumentParser(description='导入立创中文资料到 lab_catalog 索引')
    ap.add_argument('--snapshot', required=True, help='components.sqlite3（只读打开）')
    ap.add_argument('--categories', required=True, help='categories_cn.json')
    ap.add_argument('--dbname', required=True)
    ap.add_argument('--dbhost', default='/var/run/postgresql')
    ap.add_argument('--dbport', default=5432, type=int)
    ap.add_argument('--dbuser', required=True)
    ap.add_argument('--dbpassword', default=None)
    ap.add_argument('--limit', type=int, default=0, help='只导入前 N 行（试跑用）')
    ap.add_argument('--batch', type=int, default=BATCH)
    ap.add_argument('--resume-from', default=None, help='从该 C 编号之后继续')
    ap.add_argument('--scan-raw', action='store_true',
                    help='解压 raw_json_gzip 尽力补真实图片（只在导入期，慢）')
    ap.add_argument('--verify', action='store_true', help='结束后打印覆盖率校验')
    args = ap.parse_args()

    if not os.path.exists(args.snapshot):
        print('快照不存在：%s' % args.snapshot, file=sys.stderr)
        return 2

    t0 = time.time()
    print('== 连接 Odoo PostgreSQL ==')
    pg = psycopg2.connect(dbname=args.dbname, host=args.dbhost, port=args.dbport,
                          user=args.dbuser, password=args.dbpassword)
    pg.autocommit = False
    cur = pg.cursor()
    cur.execute("SELECT to_regclass('lab_catalog_item')")
    if cur.fetchone()[0] is None:
        print('表 lab_catalog_item 不存在：请先在 Odoo 里安装/升级 lab_catalog 模块', file=sys.stderr)
        return 3

    print('== 导入分类树 ==')
    nodes, parent_of = load_categories(args.categories)
    cat_pg = import_categories(pg.cursor(), nodes, parent_of)
    print('   分类节点 %d 个，已映射 %d 个' % (len(nodes), len(cat_pg)))
    pg.commit()

    run_name = 'catalog-import-%s' % datetime.now().strftime('%Y%m%d-%H%M%S')
    cur.execute("""
        INSERT INTO lab_catalog_import_run
          (name, source_path, market, state, started_at, create_uid, create_date, write_uid, write_date)
        VALUES (%s,%s,%s,'running',now(),1,now(),1,now()) RETURNING id
    """, (run_name, args.snapshot, MARKET_CN))
    run_id = cur.fetchone()[0]
    pg.commit()
    print('   导入批次 id=%s' % run_id)

    # 只读打开快照（query_only 双保险：本工具从不写原快照）。
    # immutable=1 让 SQLite 跳过变更检测与加锁，大幅提速——**前提是 crawler 已停止、
    # 快照文件不会再被写入**；crawler 仍在跑时绝不能这样打开（会读到不一致的数据）。
    uri = 'file:%s?mode=ro&immutable=1' % args.snapshot.replace('\\', '/')
    sq = sqlite3.connect(uri, uri=True)
    sq.execute('PRAGMA query_only = ON')
    sqc = sq.cursor()

    # 显式选用 (code, market) 索引，避免整库临时排序（见 pick_code_index 注释）
    code_index = pick_code_index(sqc)
    if code_index:
        print('   选用索引 INDEXED BY %s（避免 ORDER BY code 触发整库临时排序）' % code_index)
    else:
        print('   警告：未发现 (code, market) 索引；ORDER BY code 可能整库临时排序')

    where = "market = ?"
    sargs = [MARKET_CN]
    if args.resume_from:
        where += " AND code > ?"
        sargs.append(args.resume_from)
    order = "ORDER BY code"
    lim = "LIMIT %d" % args.limit if args.limit else ''
    indexed = ('INDEXED BY %s' % code_index) if code_index else ''
    # 打印**真实查询计划**作为证据（小查询，不扫数据）
    try:
        for r in sqc.execute(
                'EXPLAIN QUERY PLAN SELECT code, fields_json, raw_json_gzip, fetched_at, '
                'source_url FROM records %s WHERE %s %s %s' % (indexed, where, order, lim),
                sargs).fetchall():
            detail = r[3] if len(r) > 3 else str(r)
            print('   查询计划: %s' % detail)
            if 'TEMP B-TREE' in str(detail):
                print('   ！仍存在临时排序，请检查索引选择')
    except Exception as exc:
        print('   EXPLAIN 失败（不影响导入）：%s' % exc)

    _t_first = time.time()
    sqc.execute('SELECT code, fields_json, raw_json_gzip, fetched_at, source_url '
                'FROM records %s WHERE %s %s %s' % (indexed, where, order, lim), sargs)
    # 首批耗时：SQLite 是惰性的，fetchone() 才真正触发第一次读
    try:
        _probe = sqc.fetchone()
        print('   首批（第 1 行）耗时 %.1f ms（含真实 blob 列）'
              % ((time.time() - _t_first) * 1000.0))
    except Exception:
        _probe = None
    sqc.execute('SELECT code, fields_json, raw_json_gzip, fetched_at, source_url '
                'FROM records %s WHERE %s %s %s' % (indexed, where, order, lim), sargs)

    # 已存在指纹，用于跳过未变行
    cur.execute('SELECT catalog_code, source_fingerprint FROM lab_catalog_item WHERE market = %s',
                (MARKET_CN,))
    known = dict(cur.fetchall())

    seen = written = skipped = failed = 0
    raw_images_recovered = 0
    last_code = None
    committed_last = args.resume_from      # 只有**提交成功**的批次才推进断点
    run_ok = True
    create_temp_tables(cur)

    print('== 流式导入（批次 %d 行，不整库载入内存） ==' % args.batch)
    while True:
        rows = sqc.fetchmany(args.batch)
        if not rows:
            break
        items, pmap = [], {}
        for code, fields_json, raw_gz, fetched_at, src_url in rows:
            seen += 1
            last_code = code
            try:
                fp = fingerprint(fields_json or '')
                if known.get(code) == fp:
                    skipped += 1
                    continue
                obj = json.loads(fields_json or '{}')
            except Exception:
                failed += 1
                continue

            norm = normalize_code(code) or normalize_code(obj.get('part_number'))
            if not norm:
                failed += 1          # 非法 C 编号不导入，避免任何误合并
                continue

            brand_code, brand_cn = split_brand(obj.get('brand'))
            cat_leaf = None
            cp = obj.get('category_path')
            if isinstance(cp, dict) and cp.get('catalogId'):
                cat_leaf = cat_pg.get(int(cp['catalogId']))
            image = pick_url(obj.get('image_url'))
            if not image and args.scan_raw:
                extra = extract_extra_image(raw_gz)
                if extra:
                    image = extra
                    raw_images_recovered += 1
            files, datasheet = flatten_files(obj.get('files'))
            params = []
            for p in (obj.get('parameters') or []):
                if not isinstance(p, dict):
                    continue
                pcode = p.get('parameterCode') or ''
                pname = p.get('parameterName') or ''
                pval = p.get('parameterValue') or p.get('parameterDetailValue') or ''
                pdetail = p.get('parameterDetailValue') or ''
                if not pname and not pcode:
                    continue
                params.append((pcode, pname, pval, pdetail))

            items.append([
                norm, MARKET_CN, obj.get('product_id'), src_url,
                obj.get('name'), obj.get('mpn'), obj.get('brand'), brand_code,
                obj.get('package'), cat_leaf, obj.get('category'),
                pg_path_of(int(cp['catalogId']), parent_of, cat_pg)
                if isinstance(cp, dict) and cp.get('catalogId') else None,
                integer_or_none(obj.get('stock')), numeric_or_none(obj.get('price')),
                obj.get('currency'), obj.get('price_basis'),
                image, bool(image), datasheet, bool(datasheet),
                json.dumps(files, ensure_ascii=False) if files else None,
                len(params),
                search_text_of(norm, obj.get('name'), obj.get('mpn'), obj.get('brand'),
                               obj.get('category'), obj.get('package')),
                fetched_at, fp, run_id, 1, datetime.now(timezone.utc),
                1, datetime.now(timezone.utc),
            ])
            pmap[(norm, MARKET_CN)] = params

        try:
            written += upsert_batch(cur, items, pmap)
            pg.commit()
            committed_last = last_code          # 仅提交成功后才推进断点
        except Exception as exc:
            pg.rollback()
            print('   批次失败，已回滚（导入中止，不推进断点）：%s' % exc, file=sys.stderr)
            failed += len(items)
            run_ok = False
            break                               # 不再 continue：避免静默漏数据后仍 exit 0

        if seen % (args.batch * 10) == 0:
            print('   已扫描 %d  写入 %d  跳过 %d  失败 %d  (断点 %s)  %.0fs'
                  % (seen, written, skipped, failed, last_code, time.time() - t0))
            cur.execute('UPDATE lab_catalog_import_run SET rows_seen=%s, rows_written=%s,'
                        ' rows_skipped=%s, rows_failed=%s, last_code=%s WHERE id=%s',
                        (seen, written, skipped, failed, last_code, run_id))
            pg.commit()

    sq.close()
    state = 'done' if (run_ok and failed == 0) else 'failed'
    cur.execute("""UPDATE lab_catalog_import_run SET state=%s, finished_at=now(),
                   rows_seen=%s, rows_written=%s, rows_skipped=%s, rows_failed=%s,
                   last_code=%s, log=%s WHERE id=%s""",
                (state, seen, written, skipped, failed, committed_last,
                 'state=%s seen=%s written=%s skipped=%s failed=%s' %
                 (state, seen, written, skipped, failed), run_id))
    pg.commit()

    print('== 完成（state=%s） ==' % state)
    print('   扫描 %d  写入 %d  跳过 %d  失败 %d  用时 %.1fs'
          % (seen, written, skipped, failed, time.time() - t0))
    print('   断点（仅已提交批次）: %s' % (committed_last or '<none>'))
    if args.scan_raw:
        print('   从原始 JSON 补回图片：%d 行' % raw_images_recovered)

    if state != 'done':
        print('== 导入失败，保留断点供续跑；未完成，不输出通过结论 ==', file=sys.stderr)
        cur.close(); pg.close()
        return 4

    if args.verify:
        print('== 覆盖率校验 ==')
        cur.execute("""SELECT
              COUNT(*),
              COUNT(*) FILTER (WHERE has_image),
              COUNT(*) FILTER (WHERE has_datasheet),
              COUNT(*) FILTER (WHERE name IS NOT NULL AND name <> ''),
              COUNT(*) FILTER (WHERE brand_code IS NOT NULL AND brand_code <> ''),
              COUNT(*) FILTER (WHERE package IS NOT NULL AND package <> ''),
              COUNT(*) FILTER (WHERE category_id IS NOT NULL),
              COUNT(*) FILTER (WHERE param_count > 0)
            FROM lab_catalog_item WHERE market = %s""", (MARKET_CN,))
        total, img, ds, nm, br, pk, cat, prm = cur.fetchone()

        def pct(v):
            return '%.1f%%' % (100.0 * v / total) if total else '-'

        print('   索引行数      : %d' % total)
        print('   有图片        : %d (%s)' % (img, pct(img)))
        print('   有手册        : %d (%s)' % (ds, pct(ds)))
        print('   有名称        : %d (%s)' % (nm, pct(nm)))
        print('   有品牌代码    : %d (%s)' % (br, pct(br)))
        print('   有封装        : %d (%s)' % (pk, pct(pk)))
        print('   有分类        : %d (%s)' % (cat, pct(cat)))
        print('   有参数        : %d (%s)' % (prm, pct(prm)))
        cur.execute('SELECT COUNT(*) FROM lab_catalog_param')
        print('   参数行数      : %d' % cur.fetchone()[0])
        cur.execute("SELECT COUNT(*) FROM lab_catalog_item WHERE market <> %s", (MARKET_CN,))
        print('   非 cn 行数    : %d（应为 0，cn_excluded 不导入）' % cur.fetchone()[0])
        cur.execute("""SELECT COUNT(*) FROM lab_catalog_item
                       WHERE catalog_code !~ '^C[0-9]+$'""")
        print('   非法 C 编号行 : %d（应为 0）' % cur.fetchone()[0])

    cur.close()
    pg.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
