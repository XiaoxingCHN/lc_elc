#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Batched backfill for ``lab_catalog_item.search_params``.

Production-sized catalogs (695k items / 4.1M parameter rows in the 2026-11-04
audit) must not be rebuilt inside an Odoo module upgrade.  This standalone
script reads item + parameter rows in id batches, computes the same normalized
text as the importer, and updates only the derived column.

Examples::

    python3 backfill_search_params.py --dbname LcHardwareHouse --dbuser odoo
    python3 backfill_search_params.py --dbname LcHardwareHouse --dbuser odoo --dry-run
    python3 backfill_search_params.py --dbname LcHardwareHouse --dbuser odoo --limit 5000

The readiness marker ``lab_catalog.param_index_state=ready`` is written only
after a complete, non-dry run.  A partial/limited run leaves the marker alone,
so the API keeps reporting ``param_index_ready=false``.
"""
import argparse
import importlib.util
import os
import sys

try:
    import psycopg2
    from psycopg2.extras import execute_values
except ImportError:  # pragma: no cover
    print('需要 psycopg2：请用 Odoo venv 里的 python 运行本脚本', file=sys.stderr)
    raise


def _load_param_search():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.abspath(os.path.join(
        here, '..', '..', 'lab_inventory', 'tools', 'param_search.py'))
    spec = importlib.util.spec_from_file_location('lc_param_search', path)
    if spec is None or spec.loader is None:
        raise RuntimeError('cannot load param_search.py: %s' % path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build_search_params = _load_param_search().build_search_params

READY_SQL = """
    INSERT INTO ir_config_parameter
      (key, value, create_uid, create_date, write_uid, write_date)
    VALUES ('lab_catalog.param_index_state', 'ready', 1, now(), 1, now())
    ON CONFLICT (key) DO UPDATE
       SET value = EXCLUDED.value, write_uid = EXCLUDED.write_uid,
           write_date = EXCLUDED.write_date
"""


def parse_args():
    ap = argparse.ArgumentParser(description='Backfill lab_catalog_item.search_params')
    ap.add_argument('--dbname', required=True)
    ap.add_argument('--dbhost', default='/var/run/postgresql')
    ap.add_argument('--dbport', default=5432, type=int)
    ap.add_argument('--dbuser', required=True)
    ap.add_argument('--dbpassword', default=None)
    ap.add_argument('--batch', type=int, default=1000, help='items per batch')
    ap.add_argument('--start-id', type=int, default=0, help='resume after this id')
    ap.add_argument('--limit', type=int, default=0, help='process at most N items')
    ap.add_argument('--dry-run', action='store_true', help='compute but do not write')
    return ap.parse_args()


def main():
    args = parse_args()
    batch = max(10, args.batch)
    conn = psycopg2.connect(
        dbname=args.dbname, host=args.dbhost, port=args.dbport,
        user=args.dbuser, password=args.dbpassword)
    cur = conn.cursor()
    last_id = max(0, args.start_id)
    processed = updated = 0
    try:
        while True:
            remaining = batch
            if args.limit:
                remaining = min(remaining, args.limit - processed)
                if remaining <= 0:
                    break
            cur.execute(
                'SELECT id FROM lab_catalog_item WHERE id > %s ORDER BY id LIMIT %s',
                (last_id, remaining))
            ids = [row[0] for row in cur.fetchall()]
            if not ids:
                break
            cur.execute(
                'SELECT item_id, code, name, value, detail_value '
                'FROM lab_catalog_param WHERE item_id = ANY(%s) '
                'ORDER BY item_id, sequence, id', (ids,))
            grouped = {item_id: [] for item_id in ids}
            for item_id, code, name, value, detail in cur.fetchall():
                grouped[item_id].append((code or '', name or '', value or '', detail or ''))
            values = [(item_id, build_search_params(grouped[item_id]))
                      for item_id in ids]
            if not args.dry_run:
                execute_values(
                    cur,
                    'UPDATE lab_catalog_item AS i SET search_params = v.text '
                    'FROM (VALUES %s) AS v(id, text) WHERE i.id = v.id',
                    values, page_size=len(values))
                conn.commit()
            processed += len(ids)
            updated += len(values)
            last_id = ids[-1]
            print('   processed=%d updated=%d last_id=%s'
                  % (processed, updated, last_id), flush=True)
        if not args.dry_run and not args.limit:
            cur.execute(READY_SQL)
            conn.commit()
            print('参数检索索引已标记 ready。')
        elif args.limit:
            print('已按 --limit 处理 %d 件；未标记 ready。' % processed)
        else:
            print('dry-run：未写入 %d 件。' % processed)
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
