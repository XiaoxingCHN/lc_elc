# -*- coding: utf-8 -*-
"""stock.move 扩展：来源类型 / 备注。

对应源系统 inventory_transactions.source_type (SCAN/MANUAL/BOM) 与 remark。
"""
from odoo import fields, models


class StockMove(models.Model):
    _inherit = 'stock.move'

    lab_source_type = fields.Selection(
        selection=[
            ('SCAN', '扫码'),
            ('MANUAL', '手动'),
            ('BOM', 'BOM'),
            ('MIGRATION', '迁移'),
            ('OPENING', '期初'),
        ],
        string='来源类型', default='MANUAL')
    lab_remark = fields.Char(string='备注')
