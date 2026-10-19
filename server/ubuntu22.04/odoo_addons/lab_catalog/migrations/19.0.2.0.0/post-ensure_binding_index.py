# -*- coding: utf-8 -*-
"""升级迁移：补齐绑定唯一性（与模型上的 models.Constraint 保持一致）。

为什么需要 migration：
    Odoo 在**安装**时会调用模型的 init() 并在 _auto_init 里建声明式约束，
    但对**已经存在**的绑定表，历史重复数据可能让约束建不上。
    这里显式检测并报告，让问题暴露在日志而不是静默通过。

语义：一个本地档案最多一个 C 绑定（多档案 -> 同一 C 允许）。
**不使用 partial index（WHERE active）**：Odoo 的声明式 UNIQUE 是全列的，
两者语义必须一致，否则 ORM 校验与 DB 约束会打架。
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("SELECT to_regclass('lab_catalog_binding')")
    if cr.fetchone()[0] is None:
        _logger.info('lab_catalog: binding table absent, skip index migration')
        return

    cr.execute("""
        SELECT product_template_id, count(*)
          FROM lab_catalog_binding
         GROUP BY product_template_id
        HAVING count(*) > 1
         LIMIT 5
    """)
    dupes = cr.fetchall()
    if dupes:
        _logger.warning(
            'lab_catalog: %d template(s) have multiple bindings; unique index NOT '
            'created, resolve these first: %s', len(dupes), dupes)
        return

    for ddl in ('CREATE UNIQUE INDEX IF NOT EXISTS lab_catalog_binding_tmpl_uniq '
                'ON lab_catalog_binding (product_template_id)',
                'CREATE INDEX IF NOT EXISTS lab_catalog_binding_code_idx '
                'ON lab_catalog_binding (catalog_code)'):
        cr.execute('SAVEPOINT lc_mig_idx')
        try:
            cr.execute(ddl)
            cr.execute('RELEASE SAVEPOINT lc_mig_idx')
            _logger.info('lab_catalog: migration ddl ok')
        except Exception as exc:
            cr.execute('ROLLBACK TO SAVEPOINT lc_mig_idx')
            _logger.warning('lab_catalog: migration ddl failed: %s (%s)', ddl, exc)
