# -*- coding: utf-8 -*-
"""入库类别 -> 库位自动分配。

替代源系统的 InboundCategoryLocationMapping：
扫码入库时按元器件类别自动带出默认库位。

注：Odoo 18/19 起 `_sql_constraints` 已弃用（19 里可能直接报错），
这里改用 Python 层 @api.constrains 保证同公司内类别唯一，跨版本通用。
"""
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class LabInboundCategoryMapping(models.Model):
    _name = 'lab.inbound.category.mapping'
    _description = '入库类别→库位自动分配'
    _order = 'category, id'

    category = fields.Char(string='元器件类别', required=True,
                           help='与产品分类 / 立创分类名对齐，如 "电阻"、"LDO"')
    location_id = fields.Many2one(
        'stock.location', string='默认库位', required=True,
        domain="[('usage', '=', 'internal')]")
    company_id = fields.Many2one(
        'res.company', string='公司', default=lambda self: self.env.company)
    note = fields.Char(string='备注')

    @api.constrains('category', 'company_id')
    def _check_category_unique(self):
        for rec in self:
            if not rec.category:
                continue
            dup = self.search([
                ('category', '=', rec.category),
                ('company_id', '=', rec.company_id.id),
                ('id', '!=', rec.id),
            ], limit=1)
            if dup:
                raise ValidationError(
                    '同一公司下，类别「%s」已配置过默认库位（%s）！'
                    % (rec.category, dup.location_id.display_name))
