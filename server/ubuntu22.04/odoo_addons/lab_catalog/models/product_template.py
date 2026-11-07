# -*- coding: utf-8 -*-
"""product.template 扩展：归一化 C 码 + 目录身份。

只**增加**字段与方法，不改动 lab_inventory 已有的 ``lab_lcsc_code`` 等字段语义。
"""
import json

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

    # ------------------------------------------------ 绑定即带入资料库事实
    @api.model
    def _lab_catalog_facts(self, catalog_code):
        """该 C 编号在资料库索引里的只读事实；索引里没有时返回空 dict。

        入库现场建档、绑定档案、修复占位档案都从这里取同一份事实。
        """
        code = normalize_catalog_code(catalog_code)
        if not code:
            return {}
        item = self.env['lab.catalog.item'].sudo().search(
            [('catalog_code', '=', code)], limit=1)
        if not item:
            return {}
        specs = {}
        for param in item.param_ids:
            name = (param.name or '').strip()
            if name and name not in specs:
                specs[name] = param.value or ''
        return {
            'name': item.name or '',
            'mpn': item.mpn or '',
            'brand': item.brand or '',
            'package': item.package or '',
            'datasheet_url': item.datasheet_url or '',
            'source_url': item.source_url or '',
            'specifications': specs,
        }

    def _lab_apply_catalog_facts(self, catalog_code=None, overwrite=False):
        """把资料库事实写进档案，默认只填**空字段**（手填值优先）。

        绑定到立创编号时自动调用：标签、库存卡片、导出都读模板字段，
        不补这一步的话绑定完的档案仍然可能没有品牌/封装/参数。
        返回 ``{template_id: 写入值}``，没有可写字段时为空。
        """
        applied = {}
        for template in self:
            code = normalize_catalog_code(catalog_code or template.lab_lcsc_code)
            facts = self._lab_catalog_facts(code) if code else {}
            if not facts:
                continue
            values = {}

            def _fill(field, value, empty=None):
                if not value:
                    return
                current = template[field]
                if overwrite or not (empty if empty is not None else (current or '')).strip():
                    values[field] = value

            _fill('lab_mpn', facts.get('mpn'))
            _fill('lab_brand', facts.get('brand'))
            _fill('lab_package', facts.get('package'))
            _fill('lab_datasheet_url', facts.get('datasheet_url'))
            _fill('lab_source_url', facts.get('source_url'))
            if facts.get('specifications'):
                _fill('lab_specifications', json.dumps(
                    facts['specifications'], ensure_ascii=False))
            # 占位名称（"立创物料 Cxxx（待补全）"）才替换成资料库名称。
            if facts.get('name') and '（待补全）' in (template.name or ''):
                values['name'] = facts['name']
            if values:
                template.sudo().write(values)
                applied[template.id] = values
        return applied

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
