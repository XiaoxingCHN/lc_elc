# -*- coding: utf-8 -*-
"""立创器件参数行（fields_json.parameters 扁平化）。

索引建在**本模型自己的 init()** 里：lab.catalog.item 的 init() 执行时本表可能尚未创建，
放在那里会报 `relation "lab_catalog_param" does not exist` 并中断整个模块安装。
"""
import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class LabCatalogParam(models.Model):
    _name = 'lab.catalog.param'
    _description = '立创器件参数'
    _order = 'item_id, sequence, id'

    item_id = fields.Many2one('lab.catalog.item', string='资料', required=True,
                              ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    code = fields.Char(string='参数编码', index=True)
    name = fields.Char(string='参数名', index=True)
    value = fields.Char(string='参数值', index=True)
    detail_value = fields.Char(string='参数明细')

    _INDEX_DDL = [
        'CREATE INDEX IF NOT EXISTS lab_catalog_param_lookup_idx '
        'ON lab_catalog_param (code, value)',
        'CREATE INDEX IF NOT EXISTS lab_catalog_param_name_idx '
        'ON lab_catalog_param (name, value)',
        # facets 的相关子查询按 (item_id, code, value) 逐行查找；
        # 没有这个复合索引时全库 facets 要 6 秒左右，加上后显著下降。
        'CREATE INDEX IF NOT EXISTS lab_catalog_param_item_code_value_idx '
        'ON lab_catalog_param (item_id, code, value)',
        'CREATE INDEX IF NOT EXISTS lab_catalog_param_code_value_item_idx '
        'ON lab_catalog_param (code, value, item_id)',
    ]

    def init(self):
        """本表的索引在本表的 init() 里建；SAVEPOINT 保证失败不破坏安装。"""
        cr = self.env.cr
        for ddl in self._INDEX_DDL:
            cr.execute('SAVEPOINT lc_param_idx')
            try:
                cr.execute(ddl)
                cr.execute('RELEASE SAVEPOINT lc_param_idx')
            except Exception as exc:
                cr.execute('ROLLBACK TO SAVEPOINT lc_param_idx')
                _logger.warning('lab_catalog: param index skipped: %s', exc)
