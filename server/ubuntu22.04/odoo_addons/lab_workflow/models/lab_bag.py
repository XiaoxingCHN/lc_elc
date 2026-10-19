# -*- coding: utf-8 -*-
"""lab.bag：一个物理袋/批次 = 一个 stock.lot + 该库位上的 stock.quant。

设计要点（契约与需求一致）：

* 每袋一个追溯码 ``LABB:<trace-code>``，唯一且全局可反查
* 每袋绑定一个物料（product.template / product.product）与一个入库库位
* 袋内数量**永远从真实 quant 汇总**（``_lab_sync_quantity``），不维护第二套计数器
* 未归还数量来自领料明细累计，不在这里另算库存
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from ..tools import inventory_codec

_logger = logging.getLogger(__name__)

TRACE_SEQUENCE = 'lab.bag.trace'

_OPERATORS = {
    '=': lambda a, b: a == b,
    '==': lambda a, b: a == b,
    '!=': lambda a, b: a != b,
    '<>': lambda a, b: a != b,
    '>': lambda a, b: a > b,
    '>=': lambda a, b: a >= b,
    '<': lambda a, b: a < b,
    '<=': lambda a, b: a <= b,
}


def _compare(value, operator, target):
    """把计算字段的 search 操作符落到 Python 比较上（支持 >、<、=、!=）。"""
    func = _OPERATORS.get(operator)
    if func is None:
        return False
    try:
        return func(float(value), float(target))
    except (TypeError, ValueError):
        return False


class LabBag(models.Model):
    _name = 'lab.bag'
    _description = '实验室库存袋/批次'
    _order = 'create_date desc, id desc'
    _rec_name = 'trace_code'
    _check_company_auto = True

    trace_code = fields.Char(
        string='追溯码', required=True, index=True, copy=False,
        help='每个物理袋唯一；二维码内容为 LABB:<追溯码>。')
    name = fields.Char(string='袋名称', compute='_compute_name', store=True)
    company_id = fields.Many2one('res.company', string='公司', required=True,
                                 index=True, default=lambda self: self.env.company)
    product_tmpl_id = fields.Many2one(
        'product.template', string='物料', required=True, index=True, ondelete='restrict',
        check_company=True)
    product_id = fields.Many2one(
        'product.product', string='物料变体', required=True, index=True, ondelete='restrict',
        check_company=True)
    location_id = fields.Many2one(
        'stock.location', string='入库库位', required=True, index=True,
        ondelete='restrict', check_company=True,
        domain="[('usage', '=', 'internal')]")
    lot_id = fields.Many2one('stock.lot', string='批次/序列号', index=True, copy=False,
                             ondelete='set null')
    quantity = fields.Float(
        string='袋内数量', digits='Product Unit', default=0.0, copy=False,
        help='始终等于该批次在该库位真实 quant 的合计（由 _lab_sync_quantity 同步）。')
    uom_id = fields.Many2one('uom.uom', string='单位', related='product_id.uom_id',
                             readonly=True)
    initial_quantity = fields.Float(string='入库数量', digits='Product Unit', copy=False)
    receipt_date = fields.Datetime(string='入库时间', default=fields.Datetime.now,
                                   required=True, copy=False)
    receipt_operation_id = fields.Many2one('lab.operation', string='入库单', copy=False,
                                           ondelete='set null')
    supplier_order = fields.Char(string='来源订单号', copy=False)
    supplier_mpn = fields.Char(string='来料型号', copy=False)
    supplier_payload = fields.Text(string='立创袋原始内容', copy=False)
    note = fields.Char(string='备注')
    active = fields.Boolean(string='启用', default=True)
    issue_line_ids = fields.One2many('lab.issue.line', 'bag_id', string='领用明细')
    operation_line_ids = fields.One2many('lab.operation.line', 'bag_id', string='作业明细')
    outstanding_quantity = fields.Float(
        string='未归还数量', digits='Product Unit', compute='_compute_outstanding',
        compute_sudo=False, store=False, search='_search_outstanding_quantity')
    payload = fields.Char(string='追溯二维码内容', compute='_compute_payload', store=False)

    # Odoo 19 使用 models.Constraint 声明表约束（旧的 _sql_constraints 已不再生效）
    _trace_code_uniq = models.Constraint(
        'unique(trace_code)',
        '袋追溯码必须全局唯一。',
    )

    # ------------------------------------------------------------------
    # 计算字段
    # ------------------------------------------------------------------
    @api.depends('trace_code')
    def _compute_name(self):
        for bag in self:
            bag.name = bag.trace_code or _('未命名袋')

    @api.depends('trace_code')
    def _compute_payload(self):
        for bag in self:
            bag.payload = inventory_codec.build_bag_payload(bag.trace_code)

    @api.depends('issue_line_ids.outstanding_quantity')
    def _compute_outstanding(self):
        for bag in self:
            bag.outstanding_quantity = sum(bag.issue_line_ids.mapped('outstanding_quantity'))

    @api.model
    def _search_outstanding_quantity(self, operator, value):
        """让非存储的 outstanding_quantity 可被 search 视图过滤。

        先按领用明细里「未归还 > 0」的袋筛出候选，再用计算字段精确比较。
        """
        candidates = self.search([])
        matching = candidates.filtered(
            lambda bag: _compare(bag.outstanding_quantity, operator, value))
        return [('id', 'in', matching.ids)]

    # ------------------------------------------------------------------
    # 追溯码
    # ------------------------------------------------------------------
    @api.model
    def _lab_next_trace_code(self):
        """生成唯一追溯码：TRC + 序列 + 随机后缀，避免猜码。"""
        sequence = self.env['ir.sequence'].sudo().search(
            [('code', '=', TRACE_SEQUENCE)], limit=1)
        if not sequence:
            sequence = self.env['ir.sequence'].sudo().create({
                'name': '实验室袋追溯码',
                'code': TRACE_SEQUENCE,
                'prefix': 'TRC',
                'padding': 8,
                'number_increment': 1,
                'number_next': 1,
                'company_id': False,
            })
        for _attempt in range(20):
            candidate = sequence.next_by_code(TRACE_SEQUENCE)
            code = inventory_codec.normalize_trace_code(candidate)
            if (code and not self.sudo().search_count([('trace_code', '=', code)])
                    and not self.env['lab.pending.receipt'].sudo().search_count([('trace_code', '=', code)])):
                return code
        raise ValidationError(_('无法生成唯一追溯码，请检查 ir.sequence 配置。'))

    @api.constrains('trace_code')
    def _check_trace_code(self):
        for bag in self:
            code = inventory_codec.normalize_trace_code(bag.trace_code)
            if not code:
                raise ValidationError(
                    _('追溯码「%s」非法：只能包含大写字母、数字与短横线，长度 3~40。')
                    % (bag.trace_code,))
            if code != bag.trace_code:
                raise ValidationError(_('追溯码必须是大写规范形式：%s') % code)
            duplicate = self.search([('trace_code', '=', code), ('id', '!=', bag.id)], limit=1)
            if duplicate:
                raise ValidationError(_('追溯码「%s」已存在，不能重复。') % code)

    @api.constrains('location_id')
    def _check_location_internal(self):
        for bag in self:
            if bag.location_id and bag.location_id.usage != 'internal':
                raise ValidationError(
                    _('袋「%s」的库位必须是内部库位，当前是 %s。')
                    % (bag.trace_code, bag.location_id.usage))

    @api.constrains('quantity')
    def _check_quantity_not_negative(self):
        for bag in self:
            if bag.quantity < -1e-9:
                raise ValidationError(_('袋「%s」数量不能为负数。') % bag.trace_code)

    @api.constrains('company_id', 'location_id', 'product_tmpl_id')
    def _check_company_consistency(self):
        for bag in self:
            for record, label in ((bag.location_id, '库位'), (bag.product_tmpl_id, '物料')):
                if record.company_id and bag.company_id and record.company_id != bag.company_id:
                    raise ValidationError(
                        _('袋「%s」的公司与%s「%s」所属公司不一致。')
                        % (bag.trace_code, label, record.display_name))

    # ------------------------------------------------------------------
    # 创建 / 同步
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        # 服务边界：外部（RPC/网页）不能直接建袋，必须走入库接口
        self.env['lab.workflow.common'].lab_guard_create('库存袋')
        for vals in vals_list:
            if not vals.get('trace_code'):
                vals['trace_code'] = self._lab_next_trace_code()
            else:
                normalized = inventory_codec.normalize_trace_code(vals['trace_code'])
                if not normalized:
                    raise ValidationError(_('追溯码「%s」非法。') % vals['trace_code'])
                vals['trace_code'] = normalized
            reservation = self.env['lab.pending.receipt'].sudo().search(
                [('trace_code', '=', vals['trace_code'])], limit=1)
            if reservation and vals.get('pending_receipt_id') != reservation.id:
                raise ValidationError(_('该袋码已预留，请使用待入库确认流程。'))
            self.env['lab.trace.code'].sudo()._lab_reserve(vals['trace_code'], reservation or None)
            if not vals.get('product_id') and vals.get('product_tmpl_id'):
                template = self.env['product.template'].browse(vals['product_tmpl_id'])
                vals['product_id'] = template.product_variant_id.id
            if vals.get('product_id') and not vals.get('product_tmpl_id'):
                product = self.env['product.product'].browse(vals['product_id'])
                vals['product_tmpl_id'] = product.product_tmpl_id.id
        return super().create(vals_list)

    pending_receipt_id = fields.Many2one('lab.pending.receipt', ondelete='restrict', copy=False)
    _pending_receipt_unique = models.Constraint('unique(pending_receipt_id)', '同一待入库记录只能生成一个正式袋。')

    # ------------------------------------------------------------------
    # 服务边界：禁止绕过接口改追溯码/批次/数量绑定
    # ------------------------------------------------------------------
    PROTECTED_WRITE_FIELDS = ('trace_code', 'lot_id', 'location_id', 'quantity',
                              'product_id', 'product_tmpl_id', 'initial_quantity',
                              'receipt_operation_id', 'company_id', 'pending_receipt_id')

    def write(self, values):
        self.env['lab.workflow.common'].lab_guard_fields(
            self, values, self.PROTECTED_WRITE_FIELDS, action='修改库存袋')
        return super().write(values)

    def unlink(self):
        raise UserError(_('库存袋不可删除：袋上的追溯码与流水必须保留。'))

    def _lab_sync_quantity(self):
        """把袋内数量对齐到真实 quant（库位 + 批次精确匹配）。"""
        Quant = self.env['stock.quant']
        for bag in self:
            domain = [('product_id', '=', bag.product_id.id),
                      ('location_id', '=', bag.location_id.id)]
            domain.append(('lot_id', '=', bag.lot_id.id) if bag.lot_id else ('lot_id', '=', False))
            quantity = sum(Quant.search(domain).mapped('quantity'))
            quantity = bag.product_id.uom_id.round(quantity, rounding_method='HALF-UP')
            if abs(quantity - bag.quantity) > 1e-9:
                bag.write({'quantity': quantity})
        return True

    # ------------------------------------------------------------------
    # 标签 / 字典
    # ------------------------------------------------------------------
    def _lab_label_facts(self):
        """标签需要的全部文字事实（打印不改库存，只读）。"""
        self.ensure_one()
        template = self.product_tmpl_id
        parameters = template._lab_parse_specifications() if template.lab_specifications else []
        location = self.location_id
        supplier_bits = [bit for bit in (self.supplier_order, self.supplier_mpn) if bit]
        return {
            'kind': 'bag',
            'ref_id': self.id,
            'payload': self.payload,
            'trace_code': self.trace_code,
            'title': template.lab_sn or template.name,
            'sn': template.lab_sn or '',
            'location_code': location.lab_code or '',
            'location': location.complete_name or location.display_name,
            'location_id': location.id,
            'mpn': template.lab_mpn or '',
            'package': template.lab_package or '',
            'brand': template.lab_brand or '',
            'initial_quantity': self.initial_quantity,
            'catalog_code': template.lab_lcsc_code or '',
            'parameters': parameters,
            'quantity': self.quantity,
            'item_name': template.name,
            'supplier': ' / '.join(supplier_bits),
        }

    def _lab_bag_dict(self):
        self.ensure_one()
        template = self.product_tmpl_id
        common = self.env['lab.workflow.common']
        live = common.lab_live_bag_quantity(self)
        return {
            'id': self.id,
            'trace_code': self.trace_code,
            'payload': self.payload,
            'product_template_id': template.id,
            'product_id': self.product_id.id,
            'item_key': common.lab_item_key_for_template(template),
            'sn': template.lab_sn or None,
            'catalog_code': template.lab_lcsc_code or None,
            'mpn': template.lab_mpn or None,
            'name': template.name,
            'lot_id': self.lot_id.id or None,
            'lot_name': self.lot_id.name or None,
            'location_id': self.location_id.id,
            'location_code': self.location_id.lab_code or None,
            'location_path': self.location_id.complete_name or self.location_id.display_name,
            # quantity 是**实时 quant 合计**；cached_quantity 是库里那个缓存字段
            'quantity': live['quantity'],
            'available_quantity': live['available_quantity'],
            'reserved_quantity': live['reserved_quantity'],
            'cached_quantity': self.quantity,
            'outstanding_quantity': self.outstanding_quantity,
            'uom': self.uom_id.display_name,
            'receipt_date': fields.Datetime.to_string(self.receipt_date) if self.receipt_date else None,
            'supplier_order': self.supplier_order or None,
            'supplier_mpn': self.supplier_mpn or None,
            'note': self.note or None,
        }
