# -*- coding: utf-8 -*-
"""作业单：入库（receipt）、领用（issue）、归还（return）三种真实库存作业。

原则：

* 每次业务动作 = 一组真实 stock.move（已完成），trade 数量与作业明细一致
* 操作人固定取 ``env.uid``（控制器层不允许客户端传操作人）
* 入库创建袋 + stock.lot；领用从原库位出库到实验室领用虚拟客户位；
  归还从虚拟位回到**原袋原库位**
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from ..tools import inventory_codec

_logger = logging.getLogger(__name__)

OPERATION_TYPES = [
    ('receipt', '入库'),
    ('issue', '领用'),
    ('return', '归还'),
    ('adopt', '历史库存分袋适配'),
]


class LabOperation(models.Model):
    _name = 'lab.operation'
    _description = '实验室库存作业单'
    _order = 'create_date desc, id desc'
    _rec_name = 'name'
    _check_company_auto = True

    name = fields.Char(string='作业单号', required=True, copy=False, index=True,
                       default=lambda self: _('新建'))
    operation_type = fields.Selection(OPERATION_TYPES, string='类型', required=True,
                                      index=True)
    company_id = fields.Many2one('res.company', string='公司', required=True, index=True,
                                 default=lambda self: self.env.company)
    actor_id = fields.Many2one('res.users', string='操作人', required=True, index=True,
                               default=lambda self: self.env.uid,
                               help='服务端从已认证会话记录，客户端不可指定。')
    borrower_id = fields.Many2one('res.users', string='领用人', index=True,
                                  help='领用时的系统账号；自助领料只能是本人。')
    project = fields.Char(string='项目', index=True)
    partner_id = fields.Many2one('res.partner', string='来源/供应商')
    request_key = fields.Char(string='请求号', index=True, copy=False)
    origin_operation_id = fields.Many2one('lab.operation', string='原领用单', copy=False,
                                          ondelete='restrict')
    note = fields.Text(string='备注')
    move_ids = fields.One2many('stock.move', 'lab_operation_id', string='库存移动')
    move_count = fields.Integer(string='移动条数', compute='_compute_move_count',
                                compute_sudo=False)
    line_ids = fields.One2many('lab.operation.line', 'operation_id', string='作业明细')
    issue_line_ids = fields.One2many('lab.issue.line', 'issue_operation_id',
                                     string='领用明细')
    return_line_ids = fields.One2many('lab.issue.line', 'return_operation_id',
                                      string='归还明细')
    return_log_ids = fields.One2many('lab.return.line', 'operation_id',
                                     string='归还流水')
    total_quantity = fields.Float(string='合计数量', digits='Product Unit',
                                  compute='_compute_total', store=True)
    state = fields.Selection([('draft', '草稿'), ('done', '已完成'), ('cancel', '已取消')],
                             string='状态', default='done', required=True, index=True)

    @api.depends('move_ids')
    def _compute_move_count(self):
        for operation in self:
            operation.move_count = len(operation.move_ids)

    @api.depends('line_ids.quantity')
    def _compute_total(self):
        for operation in self:
            operation.total_quantity = sum(operation.line_ids.mapped('quantity'))

    @api.model_create_multi
    def create(self, vals_list):
        # 服务边界：外部不能直接建作业单（防止伪造流水），必须走接口/向导
        self.env['lab.workflow.common'].lab_guard_create('库存作业单')
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == _('新建'):
                vals['name'] = self._lab_next_name(vals.get('operation_type') or 'receipt')
        return super().create(vals_list)

    @api.model
    def _lab_next_name(self, operation_type):
        prefix = {
            'receipt': 'LABR',
            'issue': 'LABI',
            'return': 'LABT',
            'adopt': 'LABA',
        }.get(operation_type, 'LABO')
        sequence = self.env['ir.sequence'].sudo().search(
            [('code', '=', 'lab.operation.%s' % operation_type)], limit=1)
        if not sequence:
            sequence = self.env['ir.sequence'].sudo().create({
                'name': '实验室库存作业单 - %s' % operation_type,
                'code': 'lab.operation.%s' % operation_type,
                'prefix': '%s-' % prefix,
                'padding': 6,
                'company_id': False,
            })
        return sequence.next_by_code('lab.operation.%s' % operation_type)

    def _lab_operation_dict(self):
        self.ensure_one()
        return {
            'id': self.id,
            'name': self.name,
            'operation_type': self.operation_type,
            'state': self.state,
            'actor_id': self.actor_id.id,
            'actor_name': self.actor_id.name,
            'borrower_id': self.borrower_id.id or None,
            'borrower_name': self.borrower_id.name or None,
            'project': self.project or None,
            'note': self.note or None,
            'total_quantity': self.total_quantity,
            'move_count': self.move_count,
            'request_key': self.request_key or None,
            'origin_operation_id': self.origin_operation_id.id or None,
            'create_date': fields.Datetime.to_string(self.create_date) if self.create_date else None,
        }

    def unlink(self):
        raise UserError(_('库存作业单不可删除：历史流水必须可追溯。如需纠正请做反向作业。'))

    # 受保护字段：操作人/领用人/类型/请求号不能事后改写（伪造流水）
    PROTECTED_WRITE_FIELDS = ('actor_id', 'borrower_id', 'operation_type', 'request_key',
                              'company_id', 'origin_operation_id', 'create_date')

    def write(self, values):
        self.env['lab.workflow.common'].lab_guard_fields(
            self, values, self.PROTECTED_WRITE_FIELDS, action='修改库存作业单')
        return super().write(values)


class LabOperationLine(models.Model):
    _name = 'lab.operation.line'
    _description = '实验室库存作业明细'
    _order = 'id'
    _check_company_auto = True

    operation_id = fields.Many2one('lab.operation', string='作业单', required=True,
                                   ondelete='cascade', index=True)
    operation_type = fields.Selection(OPERATION_TYPES, related='operation_id.operation_type',
                                      string='类型', store=True)
    company_id = fields.Many2one('res.company', related='operation_id.company_id', store=True)
    product_tmpl_id = fields.Many2one('product.template', string='物料', required=True,
                                      ondelete='restrict', check_company=True)
    product_id = fields.Many2one('product.product', string='物料变体', required=True,
                                 ondelete='restrict', check_company=True)
    bag_id = fields.Many2one('lab.bag', string='袋', index=True, ondelete='restrict')
    lot_id = fields.Many2one('stock.lot', string='批次', ondelete='restrict')
    quantity = fields.Float(string='数量', digits='Product Unit', required=True)
    uom_id = fields.Many2one('uom.uom', string='单位', related='product_id.uom_id')
    src_location_id = fields.Many2one('stock.location', string='源库位', ondelete='restrict')
    dest_location_id = fields.Many2one('stock.location', string='目标库位', ondelete='restrict')
    move_id = fields.Many2one('stock.move', string='库存移动', ondelete='restrict', index=True)
    issue_line_id = fields.Many2one('lab.issue.line', string='关联领用明细', ondelete='set null')

    @api.constrains('quantity')
    def _check_positive(self):
        for line in self:
            if line.quantity <= 0:
                raise ValidationError(_('作业明细数量必须大于 0。'))
