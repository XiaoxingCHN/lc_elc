# -*- coding: utf-8 -*-
"""product.template 扩展：归一化 C 码 + 目录身份。

只**增加**字段与方法，不改动 lab_inventory 已有的 ``lab_lcsc_code`` 等字段语义。
"""
from odoo import api, fields, models

from .lab_catalog_identity import normalize_catalog_code


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    lab_lcsc_code_norm = fields.Char(
        string='C 编号（归一化）', compute='_compute_lab_lcsc_code_norm',
        store=True, index=True, copy=False,
        help='lab_lcsc_code 经 NFKC+去空白+大写后的结果；非法值留空，'
             '保证永远不会把无关物料错误合并。')

    @api.depends('lab_lcsc_code')
    def _compute_lab_lcsc_code_norm(self):
        for rec in self:
            rec.lab_lcsc_code_norm = normalize_catalog_code(rec.lab_lcsc_code) or False

    @api.model
    def lab_template_ids_for_codes(self, codes):
        """{catalog_code: [template_id, ...]}，直接按归一化列查，走索引。"""
        norm = [c for c in {normalize_catalog_code(c) for c in (codes or [])} if c]
        if not norm:
            return {}
        out = {}
        for r in self.search_read([('lab_lcsc_code_norm', 'in', norm)], ['id', 'lab_lcsc_code_norm']):
            out.setdefault(r['lab_lcsc_code_norm'], []).append(r['id'])
        return out

    def lab_binding_status(self):
        """给 UI 用：这个物料是否已绑定有效 C 码。"""
        self.ensure_one()
        return {
            'product_template_id': self.id,
            'lab_sn': self.lab_sn,
            'lab_lcsc_code': self.lab_lcsc_code,
            'lab_lcsc_code_norm': self.lab_lcsc_code_norm,
            'bound': bool(self.lab_lcsc_code_norm),
            'item_key': 'lcsc:%s' % self.lab_lcsc_code_norm if self.lab_lcsc_code_norm
                        else 'lab:%s' % self.id,
        }
