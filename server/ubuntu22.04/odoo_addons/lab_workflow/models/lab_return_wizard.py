# -*- coding: utf-8 -*-
"""归还向导：网页端「登记归还」表单。

向导**不自己动库存**，而是调用与 JSON-RPC 完全相同的
``lab.workflow.common.lab_return``，因此幂等、行锁、超还校验全部一致。
"""

import logging
import uuid

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .lab_workflow_common import LabApiError

_logger = logging.getLogger(__name__)


class LabReturnWizard(models.TransientModel):
    _name = 'lab.return.wizard'
    _description = '实验室归还向导'

    issue_line_id = fields.Many2one('lab.issue.line', string='原领用记录', required=True,
                                    readonly=True)
    quantity = fields.Float(string='归还数量', digits='Product Unit', required=True)
    outstanding_quantity = fields.Float(string='未归还数量', related='issue_line_id.outstanding_quantity',
                                        readonly=True)
    borrower_id = fields.Many2one('res.users', related='issue_line_id.borrower_id',
                                  string='领用人', readonly=True)
    project = fields.Char(related='issue_line_id.project', readonly=True)
    trace_code = fields.Char(related='issue_line_id.bag_id.trace_code', readonly=True)
    lot_id = fields.Many2one('stock.lot', related='issue_line_id.lot_id', readonly=True)
    location_id = fields.Many2one('stock.location', related='issue_line_id.location_id',
                                  string='归还库位（原库位）', readonly=True)
    note = fields.Char(string='备注')
    request_key = fields.Char(string='本次请求号', required=True, copy=False,
                              default=lambda self: str(uuid.uuid4()))

    @api.onchange('issue_line_id')
    def _onchange_issue_line(self):
        for wizard in self:
            if wizard.issue_line_id and not wizard.quantity:
                wizard.quantity = wizard.issue_line_id.outstanding_quantity

    def action_return(self):
        self.ensure_one()
        common = self.env['lab.workflow.common']
        try:
            data, replayed = common.lab_return({
                'request_key': self.request_key,
                'issue_line_id': self.issue_line_id.id,
                'quantity': self.quantity,
                'note': self.note or '',
            })
        except LabApiError as error:
            raise UserError(error.message)
        message = _('归还成功：%s %s，未归还数量 %s') % (
            self.quantity, self.issue_line_id.bag_id.uom_id.display_name,
            data['outstanding_quantity'])
        if replayed:
            message += _('（该请求号已处理过，本次直接返回原结果，没有重复记账）')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('归还完成'),
                'message': message,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }


class LabIssueLineReturnAction(models.Model):
    _inherit = 'lab.issue.line'

    def action_open_return_form(self):
        """表单按钮：打开归还向导（不直接改库存）。"""
        self.ensure_one()
        if self.outstanding_quantity <= 1e-9:
            raise UserError(_('该领用记录已经没有未归还数量。'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('登记归还 - %s') % self.bag_id.trace_code,
            'res_model': 'lab.return.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_issue_line_id': self.id,
                'default_quantity': self.outstanding_quantity,
            },
        }
