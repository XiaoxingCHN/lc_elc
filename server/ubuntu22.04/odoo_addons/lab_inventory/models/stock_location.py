# -*- coding: utf-8 -*-
"""stock.location 扩展：库位类型 / 颜色 / 排序。

库位结构：实验室(view) -> 类型组(view: R/C/L/D/Q/U/J/Y/F/SW) -> 具体库位(internal)
"""
from odoo import fields, models

LOCATION_TYPES = [
    ('R', '电阻'),
    ('C', '电容'),
    ('L', '电感'),
    ('D', '二极管'),
    ('Q', '三极管/MOS'),
    ('U', 'IC芯片'),
    ('J', '连接器'),
    ('Y', '晶振'),
    ('F', '保险丝'),
    ('SW', '开关'),
]


class StockLocation(models.Model):
    _inherit = 'stock.location'

    lab_location_type = fields.Selection(
        selection=LOCATION_TYPES, string='库位类型',
        help='对应源系统 storage_locations.location_type')
    lab_color = fields.Char(
        string='颜色', help='#RRGGBB，与源系统 color_hex 一致')
    lab_sort = fields.Integer(string='排序', default=10)
