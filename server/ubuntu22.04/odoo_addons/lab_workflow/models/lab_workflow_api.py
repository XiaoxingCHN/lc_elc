# -*- coding: utf-8 -*-
"""lab.workflow.common 的业务方法扩展：扫码解析、入库、领用、归还、历史、引导。"""

import logging
import time
import uuid

from odoo import _, api, fields, models

from ..tools import inventory_codec
from .lab_workflow_common import (
    CODE_INTERNAL, PG_CONCURRENCY_ERRORS, LabApiError, LabConcurrencyRetry,
    internal_only,
)

_logger = logging.getLogger(__name__)


class LabWorkflowApiPermission(models.AbstractModel):
    """公开服务方法的服务端权限校验（覆盖 mixin 的最低门槛）。"""

    _inherit = 'lab.workflow.common'

    @api.model
    def _lab_check_service_permission(self, method_name):
        super()._lab_check_service_permission(method_name)
        if self.env.su:
            # 超级用户/system：受控内部调用，跳过 lab 角色门槛
            return True
        operator = ('lab_workflow.group_lab_operator',
                    'lab_workflow.group_lab_manager')
        if method_name in ('lab_receipt', 'lab_issue', 'lab_return'):
            if not any(self.env.user.has_group(g) for g in operator):
                raise LabApiError.forbidden(
                    '当前账号没有库存作业权限（%s）' % method_name,
                    {'group': 'lab_workflow.group_lab_operator'})
        if method_name == 'lab_adopt_untracked_stock':
            if not self.env.user.has_group('lab_workflow.group_lab_manager'):
                raise LabApiError.forbidden(
                    '历史库存分袋适配只有库存管理员可以执行',
                    {'group': 'lab_workflow.group_lab_manager'})
        return True


def _internal_error(action, exc):
    """内部异常：日志留详细堆栈，对外只给中文提示 + 关联编号。"""
    error_id = uuid.uuid4().hex[:12]
    _logger.exception('lab_workflow %s 失败 [error_id=%s]', action, error_id)
    return LabApiError(
        CODE_INTERNAL,
        '%s失败并已全部回滚。请把「错误编号 %s」提供给管理员，日志里有完整原因。'
        % (action, error_id),
        {'error_id': error_id})


class StockMoveLabOperation(models.Model):
    _inherit = 'stock.move'

    lab_operation_id = fields.Many2one(
        'lab.operation', string='实验室作业单', copy=False, index=True,
        ondelete='set null', check_company=True,
        help='由实验室库存作业创建的移动，便于按作业单追溯。')
    lab_bag_id = fields.Many2one(
        'lab.bag', string='实验室袋', copy=False, index=True, ondelete='set null')
    lab_note = fields.Char(string='实验室作业说明', copy=False)


class LabWorkflowApi(models.AbstractModel):
    _inherit = 'lab.workflow.common'

    # ==================================================================
    # 扫码解析
    # ==================================================================
    @api.model
    def lab_resolve_code(self, raw):
        """``/lab/api/inventory/resolve_code``：把任意扫码文本变成业务对象。

        支持：本系统袋追溯码、库位库码、物料 SN、立创 C 码、立创原厂袋二维码。
        """
        parsed = inventory_codec.classify_scan(raw)
        kind = parsed['kind']
        if kind == inventory_codec.KIND_UNKNOWN:
            raise LabApiError.validation(
                '无法识别扫码内容：%r。请扫描本系统的袋标签（LABB:）、库位标签（LABL:）、'
                '物料 SN、立创 C 编号，或立创原厂物料袋二维码。' % (raw,),
                {'raw': 'unknown'})

        data = {
            'kind': kind,
            'raw': raw,
            'normalized': parsed['normalized'],
            'item_key': None,
            'bag': None,
            'location': None,
            'material': None,
            'supplier_metadata': {},
        }
        if parsed.get('jlc'):
            jlc = parsed['jlc']
            data['supplier_metadata'] = {
                'source': jlc.get('source'),
                'order_no': jlc.get('on'),
                'catalog_code': jlc.get('lcsc_code'),
                'mpn': jlc.get('pm'),
                'quantity': jlc.get('qty'),
                'pdi': jlc.get('pdi'),
                'is_valid': jlc.get('is_valid'),
                'raw': raw,
            }

        if kind == inventory_codec.KIND_BAG:
            bag = self.lab_bag_by_trace_code(parsed['normalized'])
            data['bag'] = bag._lab_bag_dict()
            data['item_key'] = data['bag']['item_key']
            data['product_template_id'] = bag.product_tmpl_id.id
            data['location'] = bag.location_id._lab_location_dict()
            return data

        if kind == inventory_codec.KIND_LOCATION:
            location = self.lab_location_by_code(parsed['normalized'])
            data['location'] = location._lab_location_dict()
            data['item_key'] = None
            return data

        template = None
        if kind in (inventory_codec.KIND_SN,):
            # 扫到某个 SN：**必须**绑定该 SN 自己的档案（同 C 多档案也不会错绑）
            template = self.lab_template_by_sn(parsed['normalized'])
        elif kind in (inventory_codec.KIND_LCSC, inventory_codec.KIND_JLC):
            code = parsed['normalized']
            candidates = self.lab_candidate_templates(code)
            data['candidates'] = [{
                'product_template_id': candidate.id,
                'product_id': candidate.product_variant_id.id or None,
                'sn': candidate.lab_sn or None,
                'name': candidate.name,
                'mpn': candidate.lab_mpn or None,
                'package': candidate.lab_package or None,
            } for candidate in candidates]
            data['ambiguous_material'] = len(candidates) > 1
            if len(candidates) == 1:
                template = candidates
            elif len(candidates) > 1:
                # 不随机取 first：让界面选择 SN/档案
                data['item_key'] = 'lcsc:%s' % code
                if parsed.get('jlc') and not parsed['jlc'].get('lcsc_code'):
                    data['supplier_metadata']['is_valid'] = False
                return data

        if template:
            common = self.env['lab.workflow.common']
            item = template._lab_item_dict()
            item['has_stock'] = template._lab_quantity() > 0
            data['item_key'] = item['item_key']
            data['product_template_id'] = template.id
            data['material'] = item
            bags = template.lab_bag_ids.filtered(
                lambda bag: common.lab_bag_display_quantity(bag) > 0)
            data['bags'] = [bag._lab_bag_dict() for bag in bags]
            data['locations'] = [
                location._lab_location_dict() for location in bags.mapped('location_id')]
            if parsed.get('jlc') and not parsed['jlc'].get('lcsc_code'):
                data['supplier_metadata']['is_valid'] = False
        return data

    # ==================================================================
    # 引导数据
    # ==================================================================
    @api.model
    def lab_bootstrap(self):
        """``/lab/api/inventory/bootstrap``。"""
        common = self.env['lab.workflow.common']
        locations = self.env['stock.location'].search([
            ('usage', '=', 'internal'),
            '|', ('company_id', '=', False), ('company_id', '=', self.env.company.id),
        ]).sorted(lambda loc: loc.complete_name or '')
        borrowers = common.lab_authorized_borrowers()
        permissions = {
            'can_receipt': self.env.user.has_group('lab_workflow.group_lab_operator'),
            'can_issue': self.env.user.has_group('lab_workflow.group_lab_operator'),
            'can_return': self.env.user.has_group('lab_workflow.group_lab_operator'),
            'can_issue_for_others': common.lab_can_issue_for_others(),
            'can_manage_locations': self.env.user.has_group('lab_workflow.group_lab_manager'),
            'can_manage_labels': self.env.user.has_group('lab_workflow.group_lab_operator'),
            'is_manager': self.env.user.has_group('lab_workflow.group_lab_manager'),
            'uid': self.env.uid,
            'user_name': self.env.user.name,
            'company_id': self.env.company.id,
        }
        return {
            'locations': [location._lab_location_dict() for location in locations],
            'borrowers': [{
                'id': user.id,
                'name': user.name,
                'login': user.login,
                'is_self': user.id == self.env.uid,
            } for user in borrowers],
            'permissions': permissions,
            'inventory_revision': self.lab_inventory_revision(),
            'server_time': fields.Datetime.to_string(fields.Datetime.now()),
        }

    @api.model
    def lab_locations(self):
        locations = self.env['stock.location'].search([
            ('usage', '=', 'internal'),
            '|', ('company_id', '=', False), ('company_id', '=', self.env.company.id),
        ]).sorted(lambda loc: loc.complete_name or '')
        return {'locations': [location._lab_location_dict() for location in locations]}

    @api.model
    def lab_location_create(self, name, parent_id=None):
        if not (name or '').strip():
            raise LabApiError.validation('库位名称不能为空', {'name': 'required'})
        parent = False
        if parent_id:
            parent = self.env['stock.location'].browse(int(parent_id)).exists()
            if not parent:
                raise LabApiError.not_found('父库位不存在：%s' % parent_id,
                                            {'parent_id': 'not_found'})
            if parent.usage not in ('view', 'internal'):
                raise LabApiError.validation(
                    '父库位「%s」类型是 %s，不能作为内部库位的父级'
                    % (parent.display_name, parent.usage), {'parent_id': 'invalid_usage'})
        location = self.env['stock.location'].create({
            'name': name.strip(),
            'usage': 'internal',
            'location_id': parent.id if parent else False,
            'company_id': self.env.company.id,
        })
        return {'location': location._lab_location_dict()}

    # ==================================================================
    # 入库
    # ==================================================================
    @api.model
    @internal_only
    def lab_receipt(self, params):
        """``/lab/api/inventory/receipt``：登记一个新袋（真实入库移动）。

        REPEATABLE READ 下的并发冲突（SerializationFailure / 唯一约束）
        由 :meth:`lab_run_with_concurrency_retry` 整事务回滚后重试；
        业务错误（LabApiError）不重试，直接抛给客户端。
        """
        return self.lab_run_with_concurrency_retry(
            lambda: self._lab_receipt_once(params))

    def _lab_receipt_once(self, params):
        """入库的一次尝试（被 lab_receipt 的并发重试包裹）。"""
        request_key = self.lab_request_key(params)
        log, replay = self.lab_begin_request(request_key, 'inventory.receipt', params)
        if replay:
            return replay, True

        try:
            with self.lab_savepoint():
                # 物料归属：优先用客户端从扫码/选择结果带回来的确切档案；
                # 只有在该 C 编号下唯一（或首次 on-demand 建档）时才自动选择，
                # 多个档案且未指定 => AMBIGUOUS_MATERIAL + 候选列表，绝不取 first。
                template = None
                scanned_sn = params.get('sn')
                if scanned_sn:
                    # 扫某个 SN 入库：必须绑定该 SN 自己的档案
                    sn_template = self.lab_template_by_sn(scanned_sn)
                    requested_template_id = params.get('product_template_id')
                    if requested_template_id and int(requested_template_id) != sn_template.id:
                        raise LabApiError.validation(
                            '扫描的 SN %s 属于物料档案 #%s，与传入的 '
                            'product_template_id=%s 不一致，已拒绝以免错绑。'
                            % (scanned_sn, sn_template.id, requested_template_id),
                            {'sn': 'template_mismatch',
                             'product_template_id': 'template_mismatch'})
                    # SN 所属档案的 canonical 必须与请求的 item_key 一致，
                    # 否则会出现「请求 A 器件、实际入了 B 器件库存」。
                    item_key = params.get('item_key')
                    if item_key:
                        requested_key = self.lab_normalize_item_key(item_key)
                        sn_key = self.lab_item_key_for_template(sn_template)
                        if requested_key and requested_key != sn_key:
                            raise LabApiError.precondition(
                                '请求的 item_key=%s 与扫描 SN %s 所属档案的物料（%s）不一致，'
                                '已拒绝。请对同一个物料扫码，或改用该 SN 对应的 item_key。'
                                % (item_key, scanned_sn, sn_key),
                                {'sn': 'item_key_mismatch', 'item_key': 'mismatch',
                                 'expected': sn_key})
                    template = sn_template
                if template is None:
                    template = self.lab_search_template(
                        params.get('item_key'),
                        create_if_missing=True,
                        origin='入库',
                        product_template_id=params.get('product_template_id'))
                location = self.lab_location_by_id(params.get('location_id'))
                product = template.product_variant_id
                if not product:
                    raise LabApiError.precondition(
                        '物料「%s」没有可用的物料变体，无法入库' % template.display_name)
                quantity = self.lab_check_quantity(product, params.get('quantity'))
                self.lab_ensure_storable_tracking(template)

                supplier_meta = {}
                supplier_qr = (params.get('supplier_qr') or '').strip()
                if supplier_qr:
                    parsed = inventory_codec.classify_scan(supplier_qr)
                    if parsed.get('jlc'):
                        jlc = parsed['jlc']
                        supplier_meta = {
                            'supplier_order': jlc.get('on'),
                            'supplier_mpn': jlc.get('pm'),
                            'supplier_payload': supplier_qr,
                        }
                        if jlc.get('lcsc_code') and jlc['lcsc_code'] != inventory_codec.normalize_lcsc_code(template.lab_lcsc_code):
                            raise LabApiError.validation(
                                '扫描的立创袋是 %s，与目标物料（%s）不一致，入库已拒绝，'
                                '请确认物料或重新扫码'
                                % (jlc['lcsc_code'], template.lab_lcsc_code or template.display_name),
                                {'supplier_qr': 'material_mismatch'})
                    else:
                        supplier_meta = {'supplier_payload': supplier_qr}

                # 追溯码：允许客户端自带（补打历史标签），否则服务端生成
                requested_trace = inventory_codec.normalize_trace_code(params.get('trace_code'))
                bag_model = self.env['lab.bag']
                # 内部受控写入：外部调用已经在 @internal_only + 角色校验里把关，
                # 这里用 sudo 完成建档/批次/quant，避免普通操作员被迫拥有
                # lab.bag / stock.lot 的直接 create 权限（外部 dataset 仍不能建）。
                bag = bag_model.sudo().create({
                    'trace_code': requested_trace or False,
                    'company_id': self.env.company.id,
                    'product_tmpl_id': template.id,
                    'product_id': product.id,
                    'location_id': location.id,
                    'initial_quantity': quantity,
                    'quantity': 0.0,
                    'receipt_date': fields.Datetime.now(),
                    'receipt_operation_id': False,
                    'note': params.get('note') or '',
                    **supplier_meta,
                })

                lot = self.env['stock.lot'].create({
                    'name': bag.trace_code,
                    'product_id': product.id,
                    'company_id': self.env.company.id,
                    'ref': template.lab_lcsc_code or template.lab_sn or '',
                    'lab_bag_id': bag.id,
                })
                bag.lot_id = lot

                # 行锁：同一物料+批次的 quant
                self.lab_quant_lock_domain(product, lot, [location])

                operation = self.env['lab.operation'].create({
                    'operation_type': 'receipt',
                    'actor_id': self.env.uid,
                    'company_id': self.env.company.id,
                    'request_key': request_key,
                    'note': params.get('note') or '',
                })
                bag.receipt_operation_id = operation

                move = self.lab_move_stock(
                    product=product,
                    quantity=quantity,
                    src_location=self.lab_supplier_location(),
                    dest_location=location,
                    lot=lot,
                    reference=operation.name,
                    origin=operation.name,
                    note=_('入库 %s 到 %s（袋 %s）') % (template.display_name,
                                                      location.display_name, bag.trace_code),
                )
                move.write({'lab_operation_id': operation.id, 'lab_bag_id': bag.id})
                self.env['lab.operation.line'].create({
                    'operation_id': operation.id,
                    'product_tmpl_id': template.id,
                    'product_id': product.id,
                    'bag_id': bag.id,
                    'lot_id': lot.id,
                    'quantity': quantity,
                    'src_location_id': move.location_id.id,
                    'dest_location_id': move.location_dest_id.id,
                    'move_id': move.id,
                })

                bag._lab_sync_quantity()
                if abs(bag.quantity - quantity) > 1e-6:
                    raise LabApiError.precondition(
                        '入库后袋内数量 %s 与预期 %s 不一致，已回滚'
                        % (bag.quantity, quantity))
                self.lab_assert_not_negative(product, [location], [lot])

                data = {
                    'operation': operation._lab_operation_dict(),
                    'bag': bag._lab_bag_dict(),
                    'item_key': self.lab_item_key_for_template(template),
                    'product_template_id': template.id,
                    'product_id': product.id,
                    'sn': template.lab_sn or None,
                    'material': {
                        'product_template_id': template.id,
                        'product_id': product.id,
                        'sn': template.lab_sn or None,
                        'name': template.name,
                        'catalog_code': template.lab_lcsc_code or None,
                        'mpn': template.lab_mpn or None,
                    },
                    'lab_quantity': template._lab_quantity(),
                    'inventory_revision': self.lab_inventory_revision(),
                    'replayed': False,
                }
                self.lab_finish_request(log, data)
                return data, False
        except LabApiError as error:
            self.lab_fail_request(log, error)
            raise
        except (LabConcurrencyRetry, ) + PG_CONCURRENCY_ERRORS:
            # 并发冲突：交给 lab_run_with_concurrency_retry 整事务回滚重试
            raise
        except Exception as exc:  # noqa: BLE001 - 统一转成信封错误
            wrapped = _internal_error('入库', exc)
            self.lab_fail_request(log, wrapped)
            raise wrapped

    # ==================================================================
    # 领用
    # ==================================================================
    @api.model
    @internal_only
    def lab_issue(self, params):
        """``/lab/api/inventory/issue``：按袋领用，记领用人与项目。

        REPEATABLE READ 下的并发冲突（行锁等待后 40001 等）由
        :meth:`lab_run_with_concurrency_retry` 整事务回滚后重试，
        重试时用新快照重新校验库存，超领仍然被业务拒绝。
        """
        return self.lab_run_with_concurrency_retry(
            lambda: self._lab_issue_once(params))

    def _lab_issue_once(self, params):
        """领用的一次尝试（被 lab_issue 的并发重试包裹）。"""
        # 并发排查用：分段耗时（只在 debug 级别输出，不影响正常日志）
        _t0 = time.time()

        def _mark(step):
            _logger.info('lab_issue 分段[uid=%s] %s：%.2fs', self.env.uid, step,
                         time.time() - _t0)

        request_key = self.lab_request_key(params)
        _mark('request_key')
        log, replay = self.lab_begin_request(request_key, 'inventory.issue', params)
        _mark('begin_request')
        if replay:
            return replay, True

        try:
            with self.lab_savepoint():
                borrower = self.lab_check_borrower(params.get('borrower_id'))
                _mark('check_borrower')
                project = (params.get('project') or '').strip()
                if not project:
                    raise LabApiError.validation('必须填写领用项目', {'project': 'required'})
                lines = params.get('lines') or []
                if not isinstance(lines, list) or not lines:
                    raise LabApiError.validation('领用明细不能为空',
                                                 {'lines': 'required'})
                if len(lines) > 100:
                    raise LabApiError.validation('一次领用最多 100 条明细',
                                                 {'lines': 'too_many'})

                # 1) 先锁袋行（按 id 排序，避免死锁），再校验
                bag_ids = []
                for entry in lines:
                    if not isinstance(entry, dict):
                        raise LabApiError.validation('领用明细格式错误：%s' % (entry,),
                                                     {'lines': 'invalid'})
                    if not entry.get('bag_id'):
                        raise LabApiError.validation('每条领用明细都要有 bag_id',
                                                     {'lines': 'bag_id_required'})
                    bag_ids.append(int(entry['bag_id']))
                if len(set(bag_ids)) != len(bag_ids):
                    raise LabApiError.validation(
                        '同一袋不能在一次领用中重复出现，请合并数量',
                        {'lines': 'duplicate_bag'})
                self.lab_sql_lock('lab_bag', 'id IN %s', (tuple(sorted(bag_ids)),))
                _mark('lock_bags')
                # 行锁之后必须丢弃 ORM 缓存，否则读到的还是加锁前的旧数量
                bags = self.env['lab.bag'].browse(sorted(bag_ids)).exists()
                if len(bags) != len(bag_ids):
                    missing = sorted(set(bag_ids) - set(bags.ids))
                    raise LabApiError.not_found('袋不存在或无权访问：%s' % missing,
                                                {'lines': 'bag_not_found'})
                bags.invalidate_recordset(['quantity', 'lot_id', 'location_id',
                                           'product_id', 'company_id'])
                # 子表（领用/归还明细）会以 KEY SHARE 引用袋行；
                # 用同一把锁提前占住，避免与 FOR UPDATE 形成锁环而死锁。
                self.lab_bag_key_share(bags.ids)
                # 同时锁住涉及的 quant 行，串行化与原生库存操作/其他领用的并发
                for bag in bags:
                    self.lab_quant_lock_domain(bag.product_id, bag.lot_id, [bag.location_id])

                issue_lines_data = []
                for entry in lines:
                    bag = bags.filtered(lambda b: b.id == int(entry['bag_id']))
                    quantity = self.lab_check_quantity(bag.product_id, entry.get('quantity'))
                    _mark('check_quantity bag=%s' % bag.id)
                    if bag.company_id != self.env.company:
                        raise LabApiError.forbidden(
                            '袋 %s 属于其他公司，当前账号无权领用' % bag.trace_code,
                            {'lines': 'wrong_company'})
                    # 可领用量按锁后实时 quant 计算（含已预留量）
                    live = self.lab_live_bag_quantity(bag)
                    _mark('live_bag_quantity bag=%s' % bag.id)
                    available = live['available_quantity']
                    if quantity - available > 1e-9:
                        raise LabApiError.precondition(
                            '袋 %s 在库位「%s」实时可用 %s %s（在库 %s，已预留 %s），'
                            '本次要领 %s %s，已拒绝'
                            % (bag.trace_code, bag.location_id.display_name,
                               available, bag.uom_id.display_name,
                               live['quantity'], live['reserved_quantity'],
                               quantity, bag.uom_id.display_name),
                            {'lines': 'insufficient_stock'})
                    issue_lines_data.append((bag, quantity, available))

                _mark('issue_line_data done')
                operation = self.env['lab.operation'].create({
                    'operation_type': 'issue',
                    'actor_id': self.env.uid,
                    'borrower_id': borrower.id,
                    'company_id': self.env.company.id,
                    'project': project,
                    'request_key': request_key,
                    'note': params.get('note') or '',
                })
                customer_location = self.lab_lab_customer_location()

                for bag, quantity, _available in issue_lines_data:
                    issue_line = self.env['lab.issue.line'].create({
                        'bag_id': bag.id,
                        'company_id': self.env.company.id,
                        'quantity': quantity,
                        'borrower_id': borrower.id,
                        'actor_id': self.env.uid,
                        'project': project,
                        'date': fields.Datetime.now(),
                        'note': params.get('note') or '',
                    })
                    move = self.lab_move_stock(
                        product=bag.product_id,
                        quantity=quantity,
                        src_location=bag.location_id,
                        dest_location=customer_location,
                        lot=bag.lot_id,
                        reference=operation.name,
                        origin=operation.name,
                        note=_('领用：%s 领 %s %s（袋 %s）') % (
                            borrower.name, quantity, bag.uom_id.display_name, bag.trace_code),
                    )
                    _mark('move done bag=%s' % bag.id)
                    move.write({'lab_operation_id': operation.id, 'lab_bag_id': bag.id})
                    self.env['lab.operation.line'].create({
                        'operation_id': operation.id,
                        'product_tmpl_id': bag.product_tmpl_id.id,
                        'product_id': bag.product_id.id,
                        'bag_id': bag.id,
                        'lot_id': bag.lot_id.id,
                        'quantity': quantity,
                        'src_location_id': move.location_id.id,
                        'dest_location_id': move.location_dest_id.id,
                        'move_id': move.id,
                        'issue_line_id': issue_line.id,
                    })
                    issue_line.issue_operation_id = operation.id
                    bag._lab_sync_quantity()
                    self.lab_assert_not_negative(bag.product_id, [bag.location_id],
                                                 [bag.lot_id])

                data = {
                    'operation': operation._lab_operation_dict(),
                    'lines': [{
                        'issue_line_id': line.id,
                        'bag_id': line.bag_id.id,
                        'trace_code': line.bag_id.trace_code,
                        'quantity': line.quantity,
                        'outstanding_quantity': line.outstanding_quantity,
                        'borrower_id': line.borrower_id.id,
                        'actor_id': line.actor_id.id,
                        'project': line.project,
                    } for line in operation.issue_line_ids],
                    'inventory_revision': self.lab_inventory_revision(),
                    'replayed': False,
                }
                self.lab_finish_request(log, data)
                return data, False
        except LabApiError as error:
            self.lab_fail_request(log, error)
            raise
        except (LabConcurrencyRetry, ) + PG_CONCURRENCY_ERRORS:
            # 并发冲突：整事务回滚后重试（新快照重新校验库存）
            raise
        except Exception as exc:  # noqa: BLE001
            wrapped = _internal_error('领用', exc)
            self.lab_fail_request(log, wrapped)
            raise wrapped

    # ==================================================================
    # 归还
    # ==================================================================
    @api.model
    @internal_only
    def lab_return(self, params):
        """``/lab/api/inventory/return``：按原领用明细归还，默认回原袋原库位。

        REPEATABLE READ 下的并发冲突由
        :meth:`lab_run_with_concurrency_retry` 整事务回滚后重试；
        重试用新快照重新锁定未归还余额，超还仍然被业务拒绝。
        """
        return self.lab_run_with_concurrency_retry(
            lambda: self._lab_return_once(params))

    def _lab_return_once(self, params):
        """归还的一次尝试（被 lab_return 的并发重试包裹）。"""
        request_key = self.lab_request_key(params)
        log, replay = self.lab_begin_request(request_key, 'inventory.return', params)
        if replay:
            return replay, True

        try:
            with self.lab_savepoint():
                issue_line_id = params.get('issue_line_id')
                if not issue_line_id:
                    raise LabApiError.validation('必须选择原领用记录（issue_line_id）',
                                                 {'issue_line_id': 'required'})
                self.lab_sql_lock('lab_issue_line', 'id = %s', (int(issue_line_id),))
                issue_line = self.env['lab.issue.line'].browse(int(issue_line_id)).exists()
                if not issue_line:
                    raise LabApiError.not_found('原领用记录不存在：%s' % issue_line_id,
                                                {'issue_line_id': 'not_found'})
                if issue_line.company_id != self.env.company:
                    raise LabApiError.forbidden('该领用记录属于其他公司',
                                                {'issue_line_id': 'wrong_company'})
                # 行锁后丢弃缓存：returned_quantity / outstanding_quantity 必须重新计算
                issue_line.invalidate_recordset(['quantity', 'returned_quantity',
                                                 'outstanding_quantity'])
                outstanding = issue_line.outstanding_quantity
                if outstanding <= 1e-9:
                    raise LabApiError.precondition(
                        '该领用记录（袋 %s）已经没有未归还数量' % issue_line.bag_id.trace_code,
                        {'issue_line_id': 'already_returned'})
                quantity = self.lab_check_quantity(issue_line.product_id,
                                                   params.get('quantity'))
                if quantity - outstanding > 1e-9:
                    raise LabApiError.precondition(
                        '归还数量 %s 超过未归还数量 %s（原领用 %s，已还 %s）'
                        % (quantity, outstanding, issue_line.quantity,
                           issue_line.returned_quantity),
                        {'quantity': 'exceeds_outstanding'})

                bag = issue_line.bag_id
                if not bag:
                    raise LabApiError.precondition('原领用记录的袋已不存在，无法归还',
                                                   {'issue_line_id': 'bag_gone'})
                # 行锁袋 + 目标库位 quant
                self.lab_sql_lock('lab_bag', 'id = %s', (bag.id,))

                operation = self.env['lab.operation'].create({
                    'operation_type': 'return',
                    'actor_id': self.env.uid,
                    'borrower_id': issue_line.borrower_id.id,
                    'company_id': self.env.company.id,
                    'project': issue_line.project,
                    'origin_operation_id': issue_line.issue_operation_id.id,
                    'request_key': request_key,
                    'note': params.get('note') or '',
                })
                move = self.lab_move_stock(
                    product=bag.product_id,
                    quantity=quantity,
                    src_location=self.lab_lab_customer_location(),
                    dest_location=bag.location_id,
                    lot=bag.lot_id,
                    reference=operation.name,
                    origin=operation.name,
                    note=_('归还：%s 归还 %s %s（原领用单 %s，操作人 %s）') % (
                        issue_line.borrower_id.name, quantity, bag.uom_id.display_name,
                        issue_line.issue_operation_id.name, self.env.user.name),
                )
                move.write({'lab_operation_id': operation.id, 'lab_bag_id': bag.id})
                self.env['lab.operation.line'].create({
                    'operation_id': operation.id,
                    'product_tmpl_id': bag.product_tmpl_id.id,
                    'product_id': bag.product_id.id,
                    'bag_id': bag.id,
                    'lot_id': bag.lot_id.id,
                    'quantity': quantity,
                    'src_location_id': move.location_id.id,
                    'dest_location_id': move.location_dest_id.id,
                    'move_id': move.id,
                    'issue_line_id': issue_line.id,
                })
                self.env['lab.return.line'].create({
                    'issue_line_id': issue_line.id,
                    'company_id': self.env.company.id,
                    'quantity': quantity,
                    'actor_id': self.env.uid,
                    'borrower_id': issue_line.borrower_id.id,
                    'operation_id': operation.id,
                    'move_id': move.id,
                    'project': issue_line.project,
                    'date': fields.Datetime.now(),
                })
                issue_line.return_operation_id = operation.id
                bag._lab_sync_quantity()
                self.lab_assert_not_negative(bag.product_id, [bag.location_id], [bag.lot_id])

                if issue_line.outstanding_quantity < -1e-9:
                    raise LabApiError.precondition(
                        '归还后未归还数量为负（%s），已回滚' % issue_line.outstanding_quantity)

                data = {
                    'operation': operation._lab_operation_dict(),
                    'outstanding_quantity': issue_line.outstanding_quantity,
                    'issue_line': issue_line._lab_issue_line_dict(),
                    'bag': bag._lab_bag_dict(),
                    'inventory_revision': self.lab_inventory_revision(),
                    'replayed': False,
                }
                self.lab_finish_request(log, data)
                return data, False
        except LabApiError as error:
            self.lab_fail_request(log, error)
            raise
        except (LabConcurrencyRetry, ) + PG_CONCURRENCY_ERRORS:
            # 并发冲突：整事务回滚后重试（新快照重新校验未归还量）
            raise
        except Exception as exc:  # noqa: BLE001
            wrapped = _internal_error('归还', exc)
            self.lab_fail_request(log, wrapped)
            raise wrapped

    # ==================================================================
    # 查询
    # ==================================================================
    @api.model
    def lab_issues(self, query='', outstanding_only=True, cursor=None, limit=50,
                   viewer_only_self=False):
        limit = max(1, min(int(limit or 50), 200))
        domain = [('company_id', '=', self.env.company.id)]
        if query:
            domain += ['|', ('bag_id.trace_code', 'ilike', query),
                       ('project', 'ilike', query)]
        if outstanding_only:
            domain.append(('outstanding_quantity', '>', 0))
        if cursor:
            try:
                domain.append(('id', '<', int(cursor)))
            except (TypeError, ValueError):
                raise LabApiError.validation('cursor 非法：%r' % (cursor,),
                                             {'cursor': 'invalid'})
        IssueLine = self.env['lab.issue.line']
        if viewer_only_self:
            domain.append(('borrower_id', '=', self.env.uid))
        records = IssueLine.search(domain, limit=limit + 1, order='id desc')
        has_more = len(records) > limit
        records = records[:limit]
        next_cursor = str(records[-1].id) if has_more and records else None
        return {
            'issues': [line._lab_issue_line_dict() for line in records],
            'next_cursor': next_cursor,
        }

    @api.model
    def lab_history(self, item_key=None, bag_id=None, cursor=None, limit=50):
        limit = max(1, min(int(limit or 50), 200))
        Move = self.env['stock.move']
        domain = [('state', '=', 'done'),
                  ('company_id', '=', self.env.company.id),
                  ('lab_operation_id', '!=', False)]
        if item_key:
            template = self.lab_search_template(item_key)
            domain.append(('product_id', '=', template.product_variant_id.id))
        if bag_id:
            bag = self.lab_bag_by_id(bag_id)
            domain.append(('lab_bag_id', '=', bag.id))
        if cursor:
            try:
                domain.append(('id', '<', int(cursor)))
            except (TypeError, ValueError):
                raise LabApiError.validation('cursor 非法：%r' % (cursor,),
                                             {'cursor': 'invalid'})
        moves = Move.search(domain, limit=limit + 1, order='id desc')
        has_more = len(moves) > limit
        moves = moves[:limit]
        next_cursor = str(moves[-1].id) if has_more and moves else None
        return {
            'operations': [{
                'move_id': move.id,
                'operation_id': move.lab_operation_id.id,
                'operation_name': move.lab_operation_id.name,
                'operation_type': move.lab_operation_id.operation_type,
                'bag_id': move.lab_bag_id.id or None,
                'trace_code': move.lab_bag_id.trace_code or None,
                'product_template_id': move.product_id.product_tmpl_id.id,
                'item_key': self.lab_item_key_for_template(move.product_id.product_tmpl_id),
                'lot_name': move.lab_bag_id.lot_id.name or None,
                'quantity': move.quantity,
                'src_location': move.location_id.display_name,
                'dest_location': move.location_dest_id.display_name,
                'actor_id': move.lab_operation_id.actor_id.id,
                'actor_name': move.lab_operation_id.actor_id.name,
                'borrower_id': move.lab_operation_id.borrower_id.id or None,
                'borrower_name': move.lab_operation_id.borrower_id.name or None,
                'project': move.lab_operation_id.project or None,
                'date': fields.Datetime.to_string(move.date) if move.date else None,
            } for move in moves],
            'next_cursor': next_cursor,
        }
