# -*- coding: utf-8 -*-
"""lab.issue.line：领用明细与未归还数量；lab.return.line：归还流水。

「未归还数量 = 领用数量 - 归还流水合计」是归还校验的唯一依据，
并且由数据库行锁（``SELECT ... FOR UPDATE``）串行化并发归还/领用。
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class LabIssueLine(models.Model):
    _name = 'lab.issue.line'
    _description = '实验室领用明细'
    _order = 'id desc'
    _check_company_auto = True

    company_id = fields.Many2one('res.company', string='公司', required=True, index=True,
                                 default=lambda self: self.env.company)
    bag_id = fields.Many2one('lab.bag', string='来源袋', required=True, index=True,
                             ondelete='restrict', check_company=True)
    product_tmpl_id = fields.Many2one('product.template', string='物料',
                                      related='bag_id.product_tmpl_id', store=True)
    product_id = fields.Many2one('product.product', string='物料变体',
                                 related='bag_id.product_id', store=True)
    lot_id = fields.Many2one('stock.lot', string='批次', related='bag_id.lot_id', store=True)
    location_id = fields.Many2one('stock.location', string='原库位',
                                  related='bag_id.location_id', store=True)
    trace_code = fields.Char(string='袋追溯码', related='bag_id.trace_code',
                             store=True, index=True)
    quantity = fields.Float(string='领用数量', digits='Product Unit', required=True)
    returned_quantity = fields.Float(string='已归还数量', digits='Product Unit',
                                     compute='_compute_outstanding', store=True,
                                     compute_sudo=False)
    outstanding_quantity = fields.Float(string='未归还数量', digits='Product Unit',
                                        compute='_compute_outstanding', store=True,
                                        compute_sudo=False)
    borrower_id = fields.Many2one('res.users', string='领用人', required=True, index=True)
    actor_id = fields.Many2one('res.users', string='操作人', required=True, index=True,
                               default=lambda self: self.env.uid,
                               help='服务端从已认证会话记录；代领时与领用人不同。')
    project = fields.Char(string='项目', required=True, index=True)
    date = fields.Datetime(string='领用时间', default=fields.Datetime.now, required=True)
    note = fields.Text(string='备注')
    issue_operation_id = fields.Many2one('lab.operation', string='领用单', copy=False,
                                         ondelete='restrict', index=True)
    return_operation_id = fields.Many2one('lab.operation', string='最近归还单', copy=False,
                                          ondelete='restrict')
    return_line_ids = fields.One2many('lab.return.line', 'issue_line_id',
                                      string='归还流水')

    @api.depends('quantity', 'return_line_ids.quantity')
    def _compute_outstanding(self):
        for line in self:
            returned = sum(line.return_line_ids.mapped('quantity'))
            line.returned_quantity = returned
            line.outstanding_quantity = line.quantity - returned

    @api.constrains('quantity')
    def _check_quantity(self):
        for line in self:
            if line.quantity <= 0:
                raise ValidationError(_('领用数量必须大于 0。'))

    def unlink(self):
        raise UserError(_('领用记录不可删除：历史流水必须可追溯。如需纠正请做归还或反向作业。'))

    # 受保护字段：领用人/操作人/数量/项目/日期不能被事后改写（伪造领用记录）
    PROTECTED_WRITE_FIELDS = ('quantity', 'borrower_id', 'actor_id', 'project', 'date',
                              'bag_id', 'company_id', 'issue_operation_id')

    def write(self, values):
        self.env['lab.workflow.common'].lab_guard_fields(
            self, values, self.PROTECTED_WRITE_FIELDS, action='修改领用记录')
        return super().write(values)

    @api.model_create_multi
    def create(self, vals_list):
        self.env['lab.workflow.common'].lab_guard_create('领用记录')
        return super().create(vals_list)

    def _lab_issue_line_dict(self):
        self.ensure_one()
        bag = self.bag_id
        return {
            'issue_line_id': self.id,
            'issue_operation_id': self.issue_operation_id.id or None,
            'issue_operation_name': self.issue_operation_id.name or None,
            'bag_id': bag.id,
            'trace_code': bag.trace_code,
            'item_key': self.env['lab.workflow.common'].lab_item_key_for_template(
                bag.product_tmpl_id),
            'product_template_id': bag.product_tmpl_id.id,
            'sn': bag.product_tmpl_id.lab_sn or None,
            'catalog_code': bag.product_tmpl_id.lab_lcsc_code or None,
            'mpn': bag.product_tmpl_id.lab_mpn or None,
            'location_id': bag.location_id.id,
            'location_code': bag.location_id.lab_code or None,
            'location_path': bag.location_id.complete_name or bag.location_id.display_name,
            'quantity': self.quantity,
            'returned_quantity': self.returned_quantity,
            'outstanding_quantity': self.outstanding_quantity,
            'borrower_id': self.borrower_id.id,
            'borrower_name': self.borrower_id.name,
            'actor_id': self.actor_id.id,
            'actor_name': self.actor_id.name,
            'project': self.project,
            'date': fields.Datetime.to_string(self.date) if self.date else None,
            'note': self.note or None,
        }


class LabReturnLine(models.Model):
    _name = 'lab.return.line'
    _description = '实验室归还流水'
    _order = 'id desc'
    _check_company_auto = True

    issue_line_id = fields.Many2one('lab.issue.line', string='原领用明细', required=True,
                                    index=True, ondelete='restrict', check_company=True)
    company_id = fields.Many2one('res.company', string='公司', required=True, index=True,
                                 default=lambda self: self.env.company)
    quantity = fields.Float(string='归还数量', digits='Product Unit', required=True)
    actor_id = fields.Many2one('res.users', string='操作人', required=True, index=True,
                               default=lambda self: self.env.uid)
    borrower_id = fields.Many2one('res.users', string='领用人', required=True, index=True)
    operation_id = fields.Many2one('lab.operation', string='归还单', ondelete='restrict',
                                   index=True)
    move_id = fields.Many2one('stock.move', string='库存移动', ondelete='restrict')
    project = fields.Char(string='项目')
    date = fields.Datetime(string='归还时间', default=fields.Datetime.now, required=True)

    @api.constrains('quantity')
    def _check_quantity(self):
        for line in self:
            if line.quantity <= 0:
                raise ValidationError(_('归还数量必须大于 0。'))

    def unlink(self):
        raise UserError(_('归还流水不可删除：历史流水必须可追溯。'))

    PROTECTED_WRITE_FIELDS = ('quantity', 'issue_line_id', 'actor_id', 'borrower_id',
                              'company_id', 'operation_id', 'move_id', 'date')

    def write(self, values):
        self.env['lab.workflow.common'].lab_guard_fields(
            self, values, self.PROTECTED_WRITE_FIELDS, action='修改归还流水')
        return super().write(values)

    @api.model_create_multi
    def create(self, vals_list):
        self.env['lab.workflow.common'].lab_guard_create('归还流水')
        return super().create(vals_list)
