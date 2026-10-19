# -*- coding: utf-8 -*-
"""mrp.bom.line 扩展：SMT/LAB_STOCK 分配方式。

对应源系统 bom_items.allocation：
    NONE      未分配
    SMT       嘉立创贴片（不扣实验室库存）
    LAB_STOCK 实验室库存出库
"""
from odoo import fields, models


class MrpBomLine(models.Model):
    _inherit = 'mrp.bom.line'

    lab_allocation = fields.Selection(
        selection=[
            ('NONE', '未分配'),
            ('SMT', '嘉立创贴片'),
            ('LAB_STOCK', '实验室库存'),
        ],
        string='分配方式', default='NONE')
    lab_smt_note = fields.Char(string='SMT 备注')
