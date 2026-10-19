# -*- coding: utf-8 -*-
"""历史库存（无批次正库存）的安全分袋适配。

业务背景：本系统之前的物料可能已经在库里、但没有批次（``tracking='none'``）。
需求明确：**不能自动清零、不能伪造历史**。

因此这里提供一条显式路径：

1. 操作员（库存管理员）把现有无批次库存**按袋申报**（数量必须等于现有总量）
2. 系统为每个申报袋创建 lab.bag + stock.lot
3. 用**真实 stock.move** 把无批次库存搬到「库存损失」虚拟位，
   再把同样的数量带批次搬回内部库位——总量前后完全一致，且留有完整流水
4. 全程可在「库存 → 移动历史」审计，失败整体回滚

适配完成后物料的 ``tracking`` 才能安全切到 ``lot``（由本方法在适配末尾完成）。
"""

import logging

from odoo import _, api, fields, models

from ..tools import inventory_codec
from .lab_workflow_common import LabApiError, internal_only

_logger = logging.getLogger(__name__)


class LabWorkflowLegacyStock(models.AbstractModel):
    _inherit = 'lab.workflow.common'

    @api.model
    def lab_legacy_stock_report(self, item_key):
        """给网页/客户端看：该物料还有多少无批次库存、分布在哪些库位。"""
        template = self.lab_search_template(item_key)
        product = template.product_variant_id
        quants = self.lab_untracked_positive_quants(product)
        by_location = []
        for location in quants.mapped('location_id'):
            quantity = sum(quants.filtered(lambda q: q.location_id == location).mapped('quantity'))
            by_location.append({
                'location_id': location.id,
                'location_code': location.lab_code or '',
                'location_path': location.complete_name or location.display_name,
                'quantity': quantity,
            })
        return {
            'item_key': self.lab_item_key_for_template(template),
            'product_template_id': template.id,
            'product_id': product.id,
            'tracking': template.tracking,
            'is_storable': template.is_storable,
            'type': template.type,
            'untracked_quantity': sum(quants.mapped('quantity')),
            'locations': by_location,
            'needs_adoption': bool(quants),
        }

    @api.model
    @internal_only
    def lab_adopt_untracked_stock(self, item_key, bags, note=''):
        """把现有无批次库存按袋适配为真实批次库存。

        :param bags: [{'location_id': 1, 'quantity': 10, 'trace_code': None, 'note': ''}]
        :returns: {'bags': [...], 'total_quantity': ..., 'item_key': ...}
        """
        if not self.lab_can_issue_for_others():
            raise LabApiError.forbidden(
                '历史库存分袋适配会改变整批物料的追溯结构，只有库存管理员可以执行')
        if not bags:
            raise LabApiError.validation('请提供至少一个袋的分配方案', {'bags': 'required'})
        self = self.with_context(lab_workflow_internal=True)

        template = self.lab_search_template(item_key)
        product = template.product_variant_id
        if not product:
            raise LabApiError.precondition('物料没有可用变体，无法适配')
        if template.tracking != 'none':
            raise LabApiError.precondition(
                '物料「%s」已经开启批次跟踪（%s），无需再做历史适配'
                % (template.display_name, template.tracking))
        if not template.is_storable:
            raise LabApiError.precondition(
                '物料「%s」未开启库存管理，请先勾选「跟踪库存」' % template.display_name)

        untracked = self.lab_untracked_positive_quants(product)
        if not untracked:
            raise LabApiError.precondition(
                '物料「%s」当前没有无批次正库存，无需适配' % template.display_name)
        total_available = sum(untracked.mapped('quantity'))

        plan = []
        plan_total = 0.0
        for entry in bags:
            if not isinstance(entry, dict):
                raise LabApiError.validation('袋分配方案格式错误：%s' % (entry,),
                                             {'bags': 'invalid'})
            location = self.lab_location_by_id(entry.get('location_id'))
            quantity = self.lab_check_quantity(product, entry.get('quantity'))
            plan_total += quantity
            plan.append((location, quantity, entry.get('trace_code'), entry.get('note')))

        if abs(plan_total - total_available) > 1e-6:
            raise LabApiError.validation(
                '分袋合计 %s 与现有无批次库存 %s 不一致。适配必须保持总量不变，'
                '请调整分配方案。' % (plan_total, total_available),
                {'bags': 'total_mismatch'})

        inventory_location = self.lab_inventory_location()
        SourceQuant = self.env['stock.quant']
        source_locations = list({location.id: location for location, _q, _t, _n in plan}.values())
        # 行锁：所有涉及的无批次 quant
        for location in source_locations:
            self.lab_quant_lock_domain(product, None, [location])

        # 来源库位可用量按库位校验，避免把 A 库位算到 B 库位
        needed_by_location = {}
        for location, quantity, _trace, _note in plan:
            needed_by_location[location.id] = needed_by_location.get(location.id, 0.0) + quantity
        for location in source_locations:
            available = sum(SourceQuant.search([
                ('product_id', '=', product.id),
                ('location_id', '=', location.id),
                ('lot_id', '=', False),
                ('quantity', '>', 0),
            ]).mapped('quantity'))
            needed = needed_by_location[location.id]
            if needed - available > 1e-6:
                raise LabApiError.precondition(
                    '库位「%s」只有 %s 个无批次库存，分袋方案却要 %s 个，已拒绝'
                    % (location.display_name, available, needed),
                    {'bags': 'location_overdraw'})

        operation = self.env['lab.operation'].create({
            'operation_type': 'adopt',
            'actor_id': self.env.uid,
            'company_id': self.env.company.id,
            'note': note or _('历史库存分袋适配：%s') % template.display_name,
        })

        created = []
        for location, quantity, trace_code, bag_note in plan:
            bag = self.env['lab.bag'].create({
                'trace_code': inventory_codec.normalize_trace_code(trace_code) or False,
                'company_id': self.env.company.id,
                'product_tmpl_id': template.id,
                'product_id': product.id,
                'location_id': location.id,
                'initial_quantity': quantity,
                'quantity': 0.0,
                'receipt_date': fields.Datetime.now(),
                'receipt_operation_id': operation.id,
                'note': bag_note or _('历史库存适配（适配前后总量不变）'),
            })
            lot = self.env['stock.lot'].create({
                'name': bag.trace_code,
                'product_id': product.id,
                'company_id': self.env.company.id,
                'ref': template.lab_lcsc_code or template.lab_sn or '',
                'lab_bag_id': bag.id,
            })
            bag.lot_id = lot

            # 第一步：无批次库存 -> 库存损失虚拟位（真实出库移动）
            out_move = self.lab_move_stock(
                product=product,
                quantity=quantity,
                src_location=location,
                dest_location=inventory_location,
                lot=False,
                reference=operation.name,
                origin=operation.name,
                note=_('历史库存适配-移出无批次库存（袋 %s）') % bag.trace_code,
            )
            out_move.write({'lab_operation_id': operation.id, 'lab_bag_id': bag.id})
            # 第二步：库存损失虚拟位 -> 原库位，带批次（真实入库移动）
            in_move = self.lab_move_stock(
                product=product,
                quantity=quantity,
                src_location=inventory_location,
                dest_location=location,
                lot=lot,
                reference=operation.name,
                origin=operation.name,
                note=_('历史库存适配-按批次回原库位（袋 %s）') % bag.trace_code,
            )
            in_move.write({'lab_operation_id': operation.id, 'lab_bag_id': bag.id})
            for move in (out_move, in_move):
                self.env['lab.operation.line'].create({
                    'operation_id': operation.id,
                    'product_tmpl_id': template.id,
                    'product_id': product.id,
                    'bag_id': bag.id,
                    'lot_id': lot.id if move.lot_ids else False,
                    'quantity': quantity,
                    'src_location_id': move.location_id.id,
                    'dest_location_id': move.location_dest_id.id,
                    'move_id': move.id,
                })
            bag._lab_sync_quantity()
            if abs(bag.quantity - quantity) > 1e-6:
                raise LabApiError.precondition(
                    '适配后袋 %s 数量 %s 与申报 %s 不一致，已回滚'
                    % (bag.trace_code, bag.quantity, quantity))
            created.append(bag)

        # 适配后：无批次库存必须为 0，且总量不变
        remaining = self.lab_untracked_positive_quants(product)
        if remaining:
            raise LabApiError.precondition(
                '适配后仍存在 %s 个无批次库存，已回滚' % sum(remaining.mapped('quantity')))

        # 开启批次跟踪属于内部维护动作：方法本身是 @internal_only 且只允许库存管理员，
        # 这里用 sudo 写 product.template，避免要求每个管理员都拥有产品主数据写权限。
        template.sudo().write({'tracking': 'lot'})
        _logger.info('lab_workflow: 物料 %s 完成历史库存分袋适配，共 %s 袋 / 合计 %s',
                     template.display_name, len(created), plan_total)

        return {
            'item_key': self.lab_item_key_for_template(template),
            'product_template_id': template.id,
            'operation': operation._lab_operation_dict(),
            'bags': [bag._lab_bag_dict() for bag in created],
            'total_quantity': plan_total,
            'inventory_revision': self.lab_inventory_revision(),
        }
