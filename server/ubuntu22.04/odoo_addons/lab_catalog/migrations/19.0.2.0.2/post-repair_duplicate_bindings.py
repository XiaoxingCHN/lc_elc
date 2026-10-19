# -*- coding: utf-8 -*-
"""升级迁移：清理历史重复绑定，然后建立唯一约束。

背景（实测日志）：
    加约束**之前**的代码在每次调用时都可能新建一条绑定，导致同一个档案
    累积出多条（fixture 里实测 template 7/8 各有 7 条）。这类脏数据会让
    UNIQUE(product_template_id) 建不上，PG 报
    ``could not create unique index "lab_catalog_binding_tmpl_uniq"``。

处理原则：
    1. **只保留一条**：优先保留 catalog_code 与档案自身 ``lab_lcsc_code_norm``
       一致的那条（身份一致），否则保留 id 最小的（最早建立）；
    2. 删除前**逐条写日志**，不做静默改动；
    3. 清理后再建唯一索引；若仍有冲突则放弃并大声报错，绝不让约束"看起来存在"。
"""
import logging

_logger = logging.getLogger(__name__)

_UNIQ = ('CREATE UNIQUE INDEX IF NOT EXISTS lab_catalog_binding_tmpl_uniq '
         'ON lab_catalog_binding (product_template_id)')
_CODE = ('CREATE INDEX IF NOT EXISTS lab_catalog_binding_code_idx '
         'ON lab_catalog_binding (catalog_code)')


def migrate(cr, version):
    cr.execute("SELECT to_regclass('lab_catalog_binding')")
    if cr.fetchone()[0] is None:
        _logger.info('lab_catalog: binding table absent, skip migration')
        return

    # ---- 1. 找出重复
    cr.execute("""
        SELECT product_template_id, count(*)
          FROM lab_catalog_binding
         GROUP BY product_template_id
        HAVING count(*) > 1
    """)
    dupes = cr.fetchall()
    if dupes:
        _logger.warning('lab_catalog: repairing %d template(s) with duplicate bindings',
                        len(dupes))
    total_removed = 0
    for tid, n in dupes:
        cr.execute("SELECT lab_lcsc_code FROM product_template WHERE id = %s", (tid,))
        row = cr.fetchone()
        own = (row[0] or '').strip().upper() if row else ''
        cr.execute("""
            SELECT id, catalog_code FROM lab_catalog_binding
             WHERE product_template_id = %s
             ORDER BY (upper(catalog_code) = %s) DESC, id ASC
        """, (tid, own))
        rows = cr.fetchall()
        keep = rows[0]
        drop = [r[0] for r in rows[1:]]
        _logger.warning('lab_catalog: template %s had %d bindings; keep id=%s code=%s, '
                        'remove %s', tid, n, keep[0], keep[1], drop)
        if drop:
            cr.execute('DELETE FROM lab_catalog_binding WHERE id = ANY(%s)', (drop,))
            total_removed += len(drop)
    if total_removed:
        _logger.warning('lab_catalog: removed %d redundant binding row(s)', total_removed)

    # ---- 2. 复查：仍有重复就明确失败，不假装建好了约束
    cr.execute("""
        SELECT product_template_id, count(*) FROM lab_catalog_binding
         GROUP BY product_template_id HAVING count(*) > 1 LIMIT 3
    """)
    left = cr.fetchall()
    if left:
        _logger.error('lab_catalog: duplicate bindings remain %s; unique index NOT created',
                      left)
        return

    # ---- 3. 建索引
    for ddl in (_UNIQ, _CODE):
        cr.execute('SAVEPOINT lc_mig_idx')
        try:
            cr.execute(ddl)
            cr.execute('RELEASE SAVEPOINT lc_mig_idx')
            _logger.info('lab_catalog: migration ddl ok: %s', ddl.split(' INDEX ')[0])
        except Exception as exc:
            cr.execute('ROLLBACK TO SAVEPOINT lc_mig_idx')
            _logger.error('lab_catalog: migration ddl FAILED: %s (%s)', ddl, exc)

    cr.execute("SELECT count(*) FROM pg_indexes WHERE indexname='lab_catalog_binding_tmpl_uniq'")
    _logger.info('lab_catalog: lab_catalog_binding_tmpl_uniq present = %s', cr.fetchone()[0])
