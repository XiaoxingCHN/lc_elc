# -*- coding: utf-8 -*-
"""库位库码 + lab_catalog 接口适配。

* ``stock.location.lab_code``：每个库位一个库码（LABL:xxxx），标签二维码内容
* ``stock.location._lab_get_or_create_customer_location``：实验室领用虚拟对方库位
* ``stock.quant``/``stock.lot`` 轻量扩展：把真实批次暴露给库存管理界面
* ``product.template`` 扩展：袋数量、库位数量与库存修订号（不重复造库存计数器）
"""

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from ..tools import inventory_codec

CODE_SEQUENCE = 'lab.stock.location.code'
CUSTOMER_LOCATION_XMLID = 'lab_workflow.location_lab_customer'


class StockLocation(models.Model):
    _inherit = 'stock.location'

    lab_code = fields.Char(
        string='库码', copy=False, index=True,
        help='每个库位唯一的库码，用于生成库位标签二维码（LABL:<库码>）。')
    lab_note = fields.Char(string='库位备注')
    lab_bag_ids = fields.One2many('lab.bag', 'location_id', string='在库袋')
    lab_bag_count = fields.Integer(string='袋数', compute='_compute_lab_bag_stats',
                                   compute_sudo=False)

    @api.depends('lab_bag_ids', 'lab_bag_ids.quantity')
    def _compute_lab_bag_stats(self):
        for location in self:
            location.lab_bag_count = len(location.lab_bag_ids)

    @api.constrains('lab_code')
    def _check_lab_code_unique(self):
        for location in self:
            if not location.lab_code:
                continue
            code = inventory_codec.normalize_location_code(location.lab_code)
            if not code:
                raise ValidationError(
                    _('库码「%s」非法：只能包含大写字母、数字和短横线，长度 2~24。')
                    % location.lab_code)
            duplicate = self.search([('lab_code', '=', code), ('id', '!=', location.id)],
                                    limit=1)
            if duplicate:
                raise ValidationError(
                    _('库码「%s」已被库位「%s」占用，请更换。')
                    % (code, duplicate.display_name))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('lab_code'):
                vals['lab_code'] = inventory_codec.normalize_location_code(vals['lab_code'])
        locations = super().create(vals_list)
        for location in locations:
            if not location.lab_code:
                location.lab_code = self._lab_next_code()
        return locations

    @api.model
    def _lab_next_code(self):
        sequence = self.env['ir.sequence'].sudo().search(
            [('code', '=', CODE_SEQUENCE)], limit=1)
        if not sequence:
            sequence = self.env['ir.sequence'].sudo().create({
                'name': '实验室库位库码',
                'code': CODE_SEQUENCE,
                'prefix': 'K',
                'padding': 6,
                'number_increment': 1,
                'number_next': 1,
                'company_id': False,
            })
        return sequence.next_by_code(CODE_SEQUENCE)

    @api.model
    def _lab_get_or_create_customer_location(self):
        """实验室领用虚拟客户位：领用去向、归还来源。

        使用固定 xmlid 记录，保证多公司下每公司一个，且可被审计。
        """
        company = self.env.company
        existing = self.env.ref(CUSTOMER_LOCATION_XMLID, raise_if_not_found=False)
        if existing and existing.company_id == company:
            return existing
        location = self.search([
            ('usage', '=', 'customer'),
            ('name', '=', '实验室领用'),
            '|', ('company_id', '=', False), ('company_id', '=', company.id),
        ], limit=1)
        if location:
            return location
        return self.create({
            'name': '实验室领用',
            'usage': 'customer',
            'company_id': company.id,
            'lab_note': '领用去向/归还来源的虚拟库位（不对应物理位置）',
        })

    def _lab_label_payload(self):
        """库位标签二维码载荷：LABL:<code>；无库码时按需生成。"""
        self.ensure_one()
        code = self.lab_code or self._lab_next_code()
        if not self.lab_code:
            self.lab_code = code
        payload = inventory_codec.build_location_payload(code)
        if not payload:
            raise ValidationError(_('库位「%s」的库码 %s 无法生成二维码') % (self.display_name, code))
        return payload

    def _lab_location_dict(self):
        self.ensure_one()
        return {
            'id': self.id,
            'code': self.lab_code or '',
            'name': self.name,
            'path': self.complete_name or self.display_name,
            'usage': self.usage,
            'payload': inventory_codec.build_location_payload(self.lab_code) if self.lab_code else None,
        }


class StockLot(models.Model):
    _inherit = 'stock.lot'

    lab_bag_id = fields.Many2one('lab.bag', string='关联袋', copy=False, index=True,
                                 ondelete='set null')


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    lab_bag_id = fields.Many2one('lab.bag', related='lot_id.lab_bag_id', string='关联袋',
                                 store=False, readonly=True)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    lab_bag_ids = fields.One2many('lab.bag', 'product_tmpl_id', string='库存袋')
    lab_bag_count = fields.Integer(string='袋数量', compute='_compute_lab_stock_summary',
                                   compute_sudo=False)
    lab_internal_location_count = fields.Integer(
        string='有库存的库位数', compute='_compute_lab_stock_summary', compute_sudo=False)

    @api.depends('lab_bag_ids', 'lab_bag_ids.quantity', 'lab_bag_ids.location_id')
    def _compute_lab_stock_summary(self):
        for template in self:
            bags = template.lab_bag_ids
            template.lab_bag_count = len(bags)
            template.lab_internal_location_count = len(bags.mapped('location_id'))

    def _lab_quantity(self):
        """当前内部库存合计：直接用完成移动后的真实 quant 计算，不另设计数器。"""
        self.ensure_one()
        product = self.product_variant_id
        if not product:
            return 0.0
        quants = self.env['stock.quant'].search([
            ('product_id', '=', product.id),
            ('location_id.usage', '=', 'internal'),
        ])
        return sum(quants.mapped('quantity'))

    def _lab_item_dict(self, with_parameters=True):
        """生成统一卡片所需的器件事实（供 lab_catalog / 客户端复用）。"""
        self.ensure_one()
        parameters = []
        if with_parameters and self.lab_specifications:
            parameters = self._lab_parse_specifications()
        bags = self.lab_bag_ids
        return {
            'item_key': self.env['lab.workflow.common'].lab_item_key_for_template(self),
            'product_template_id': self.id,
            'product_id': self.product_variant_id.id or None,
            'catalog_code': self.lab_lcsc_code or None,
            'sn': self.lab_sn or None,
            'name': self.name,
            'mpn': self.lab_mpn or None,
            'brand': self.lab_brand or None,
            'package': self.lab_package or None,
            'lab_quantity': self._lab_quantity(),
            'bag_count': len(bags),
            'location_count': len(bags.mapped('location_id')),
            'parameters': parameters,
        }

    def _lab_parse_specifications(self):
        """lab_specifications 存的是 JSON 字符串（lab_inventory 约定），容错解析。"""
        import json as _json
        raw = self.lab_specifications
        if not raw:
            return []
        try:
            data = _json.loads(raw)
        except (ValueError, TypeError):
            return [{'name': '规格', 'value': str(raw)}]
        pairs = []
        if isinstance(data, dict):
            for key, value in data.items():
                pairs.append({'name': str(key), 'value': str(value)})
        elif isinstance(data, list):
            for entry in data:
                if isinstance(entry, dict):
                    pairs.append({
                        'name': str(entry.get('name') or entry.get('key') or ''),
                        'value': str(entry.get('value') or entry.get('val') or ''),
                    })
                else:
                    pairs.append({'name': '规格', 'value': str(entry)})
        return [item for item in pairs if item['name'] or item['value']]
