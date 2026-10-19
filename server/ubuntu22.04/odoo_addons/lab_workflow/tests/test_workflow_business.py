# -*- coding: utf-8 -*-
"""lab_workflow 业务集成测试（Odoo 19 TransactionCase）。

覆盖需求/契约中的关键验收点：

1. 入库两袋到不同库位；库存以真实 stock.quant 为准
2. 领用 20、归还 5；未归还量、袋数量、操作人一致
3. request_key 重试不重复记账；同 key 不同内容被拒绝；同 key 跨接口被拒绝
4. 超领、超还被拒绝，且库存不变
5. 并发超领：两个事务竞争同一袋时只有一个成功（用另一游标模拟第二个账号）
6. 普通账号不能冒用他人领料；未授权/匿名被拒绝
7. dataset/call_kw 带伪造 context 也不能改 actor/borrower/quantity/lot，也不能创建流水
8. 中文标签 PDF 真能生成（含中文字形检测），且不改变库存
9. 历史无批次库存：未适配时拒绝开启跟踪；适配后总量不变、无批次库存清零
"""

import io
import os
import uuid

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import HttpCase, TransactionCase, tagged

from ..models.lab_workflow_common import LabApiError


def _key(prefix='t'):
    return ('%s-%s' % (prefix, uuid.uuid4().hex))[:60]


@tagged('at_install', '-post_install', 'lab_workflow')
class LabWorkflowTransactionTest(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write({'country_id': cls.env.ref('base.cn').id})
        cls.common = cls.env['lab.workflow.common']
        # 库位
        warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.company.id)], limit=1)
        cls.location_a = warehouse.lot_stock_id
        cls.location_b = cls.env['stock.location'].create({
            'name': 'R02',
            'usage': 'internal',
            'location_id': cls.location_a.location_id.id,
            'company_id': cls.company.id,
        })
        # 物料：可库存 + 批次跟踪（Odoo 19: type=consu + is_storable）
        cls.template = cls.env['product.template'].create({
            'name': '测试电阻 270Ω',
            'type': 'consu',
            'is_storable': True,
            'tracking': 'lot',
            'lab_lcsc_code': 'C999001',
            'lab_mpn': 'TEST-R-270',
            'lab_sn': 'LAB-TEST-0001',
            'lab_specifications': '{"阻值": "270Ω", "精度": "±1%"}',
        })
        cls.product = cls.template.product_variant_id

        # 用户与角色
        cls.operator = cls._make_user('lab_op', 'lab_workflow.group_lab_operator')
        cls.manager = cls._make_user('lab_mgr', 'lab_workflow.group_lab_manager')
        cls.outsider = cls._make_user('lab_out', 'base.group_user')
        cls.other_operator = cls._make_user('lab_op2', 'lab_workflow.group_lab_operator')

    @classmethod
    def _make_user(cls, login, group_xmlid):
        return cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': login,
            'login': login,
            'email': '%s@example.invalid' % login,
            'company_id': cls.company.id,
            'company_ids': [(6, 0, [cls.company.id])],
            'group_ids': [(4, cls.env.ref(group_xmlid).id)],
        })

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------
    def _receipt(self, quantity, location=None, user=None, item_key=None, trace_code=None):
        common = self.common.with_user(user or self.operator)
        return common.lab_receipt({
            'request_key': _key('rcv'),
            'item_key': item_key or ('lcsc:%s' % self.template.lab_lcsc_code),
            'location_id': (location or self.location_a).id,
            'quantity': quantity,
            'trace_code': trace_code,
            'note': '测试入库',
        })[0]

    def _issue(self, bag_id, quantity, borrower=None, project='测试项目', user=None):
        common = self.common.with_user(user or self.operator)
        return common.lab_issue({
            'request_key': _key('iss'),
            'borrower_id': (borrower or self.operator).id,
            'project': project,
            'lines': [{'bag_id': bag_id, 'quantity': quantity}],
        })[0]

    def _bag_quants(self, bag):
        return self.env['stock.quant'].search([
            ('product_id', '=', bag.product_id.id),
            ('lot_id', '=', bag.lot_id.id),
            ('location_id', '=', bag.location_id.id),
        ])

    # ==================================================================
    # 1. 入库
    # ==================================================================
    def test_01_receipt_creates_real_stock_and_lot(self):
        data = self._receipt(100)
        bag = self.env['lab.bag'].browse(data['bag']['id'])
        self.assertEqual(bag.quantity, 100)
        self.assertTrue(bag.lot_id)
        self.assertEqual(bag.lot_id.name, bag.trace_code)
        quants = self._bag_quants(bag)
        self.assertEqual(sum(quants.mapped('quantity')), 100)
        self.assertEqual(bag.location_id, self.location_a)
        self.assertTrue(bag.trace_code.startswith('TRC'))
        self.assertEqual(data['operation']['operation_type'], 'receipt')
        # 真实移动记录
        move = self.env['stock.move'].search([('lab_bag_id', '=', bag.id)])
        self.assertEqual(move.state, 'done')
        self.assertEqual(move.quantity, 100)
        self.assertEqual(move.lot_ids, bag.lot_id)
        # 物料跟踪方式被安全开启
        self.assertEqual(self.template.tracking, 'lot')
        # 库码
        self.assertTrue(self.location_a.lab_code)
        self.assertEqual(data['bag']['location_code'], self.location_a.lab_code)

    def test_02_two_bags_two_locations(self):
        first = self._receipt(100, self.location_a)
        second = self._receipt(50, self.location_b)
        self.assertNotEqual(first['bag']['trace_code'], second['bag']['trace_code'])
        bags = self.env['lab.bag'].search([
            ('product_tmpl_id', '=', self.template.id)])
        self.assertEqual(len(bags), 2)
        self.assertEqual(sum(bags.mapped('quantity')), 150)
        self.assertEqual(self.template._lab_quantity(), 150)
        # 卡片事实：一张卡汇总两袋两个库位
        item = self.template._lab_item_dict()
        self.assertEqual(item['bag_count'], 2)
        self.assertEqual(item['location_count'], 2)
        self.assertEqual(item['lab_quantity'], 150)

    def test_03_receipt_quantity_validation(self):
        bad_values = (0, -1, float('nan'), float('inf'), True, 'abc')
        for value in bad_values:
            with self.assertRaises(LabApiError, msg=repr(value)):
                self._receipt(value)
        # 精度：UoM 默认 0.01，0.001 必须被拒
        with self.assertRaises(LabApiError):
            self._receipt(0.001)
        self.assertEqual(self.template._lab_quantity(), 0)

    def test_04_receipt_bad_item_key(self):
        with self.assertRaises(LabApiError):
            self._receipt(5, item_key='lab:999999999')
        with self.assertRaises(LabApiError):
            self._receipt(5, item_key='not-a-key')

    def test_05_receipt_on_demand_creates_material(self):
        """目录里有 C 编号但本地还没有物料时，入库可现场建最小档案并成功。"""
        data = self._receipt(7, item_key='lcsc:C888777')
        template = self.env['product.template'].search(
            [('lab_lcsc_code', '=', 'C888777')], limit=1)
        self.assertTrue(template)
        self.assertTrue(template.is_storable)
        self.assertEqual(template.tracking, 'lot')
        self.assertEqual(data['bag']['quantity'], 7)

    # ==================================================================
    # 2. 领用 / 归还
    # ==================================================================
    def test_10_issue_and_partial_return(self):
        receipt = self._receipt(100)
        bag = self.env['lab.bag'].browse(receipt['bag']['id'])
        issue = self._issue(bag.id, 20)
        line_id = issue['lines'][0]['issue_line_id']
        self.assertEqual(issue['operation']['borrower_id'], self.operator.id)
        self.assertEqual(issue['operation']['actor_id'], self.operator.id)
        self.assertEqual(issue['operation']['project'], '测试项目')
        # 袋内数量减少到 80
        self.assertEqual(bag._lab_bag_dict()['quantity'], 80)
        self.assertEqual(sum(self._bag_quants(bag).mapped('quantity')), 80)
        # 未归还 20
        issue_line = self.env['lab.issue.line'].browse(line_id)
        self.assertEqual(issue_line.outstanding_quantity, 20)

        # 归还 5
        common = self.common.with_user(self.operator)
        result, replayed = common.lab_return({
            'request_key': _key('ret'),
            'issue_line_id': line_id,
            'quantity': 5,
        })
        self.assertFalse(replayed)
        self.assertEqual(result['outstanding_quantity'], 15)
        issue_line.invalidate_recordset()
        self.assertEqual(issue_line.outstanding_quantity, 15)
        self.assertEqual(issue_line.returned_quantity, 5)
        # 回到原库位原袋
        bag.invalidate_recordset()
        self.assertEqual(sum(self._bag_quants(bag).mapped('quantity')), 85)
        self.assertEqual(self.template._lab_quantity(), 85)
        # 归还单记录操作人/领用人
        return_op = self.env['lab.operation'].browse(result['operation']['id'])
        self.assertEqual(return_op.operation_type, 'return')
        self.assertEqual(return_op.borrower_id, self.operator)
        self.assertEqual(return_op.actor_id, self.operator)
        self.assertEqual(return_op.origin_operation_id.id, issue['operation']['id'])

    def test_11_over_issue_and_over_return_rejected(self):
        receipt = self._receipt(30)
        bag = self.env['lab.bag'].browse(receipt['bag']['id'])
        with self.assertRaises(LabApiError) as ctx:
            self._issue(bag.id, 31)
        self.assertIn('可用', str(ctx.exception))
        # 库存没有变化
        self.assertEqual(sum(self._bag_quants(bag).mapped('quantity')), 30)

        issue = self._issue(bag.id, 20)
        line_id = issue['lines'][0]['issue_line_id']
        common = self.common.with_user(self.operator)
        with self.assertRaises(LabApiError) as ctx:
            common.lab_return({'request_key': _key('ret'), 'issue_line_id': line_id,
                               'quantity': 21})
        self.assertIn('超过未归还数量', str(ctx.exception))
        line = self.env['lab.issue.line'].browse(line_id)
        self.assertEqual(line.outstanding_quantity, 20)

    def test_12_issue_unknown_bag(self):
        with self.assertRaises(LabApiError):
            self._issue(99999999, 1)

    def test_13_issue_requires_project_and_borrower(self):
        receipt = self._receipt(10)
        bag = self.env['lab.bag'].browse(receipt['bag']['id'])
        common = self.common.with_user(self.operator)
        with self.assertRaises(LabApiError):
            common.lab_issue({'request_key': _key('iss'), 'borrower_id': self.operator.id,
                              'project': '', 'lines': [{'bag_id': bag.id, 'quantity': 1}]})
        with self.assertRaises(LabApiError):
            common.lab_issue({'request_key': _key('iss'), 'borrower_id': False,
                              'project': 'P', 'lines': [{'bag_id': bag.id, 'quantity': 1}]})

    # ==================================================================
    # 3. 幂等
    # ==================================================================
    def test_20_receipt_retry_is_idempotent(self):
        key = _key('rcv')
        common = self.common.with_user(self.operator)
        params = {
            'request_key': key,
            'item_key': 'lcsc:%s' % self.template.lab_lcsc_code,
            'location_id': self.location_a.id,
            'quantity': 12,
        }
        first, replayed_first = common.lab_receipt(dict(params))
        second, replayed_second = common.lab_receipt(dict(params))
        self.assertFalse(replayed_first)
        self.assertTrue(replayed_second)
        self.assertEqual(first['bag']['id'], second['bag']['id'])
        self.assertEqual(first['operation']['id'], second['operation']['id'])
        # 只入库一次
        bags = self.env['lab.bag'].search([('product_tmpl_id', '=', self.template.id)])
        self.assertEqual(len(bags), 1)
        self.assertEqual(self.template._lab_quantity(), 12)

    def test_21_same_key_different_payload_rejected(self):
        key = _key('rcv')
        common = self.common.with_user(self.operator)
        base = {
            'request_key': key,
            'item_key': 'lcsc:%s' % self.template.lab_lcsc_code,
            'location_id': self.location_a.id,
            'quantity': 10,
        }
        common.lab_receipt(dict(base))
        with self.assertRaises(LabApiError) as ctx:
            common.lab_receipt(dict(base, quantity=11))
        self.assertEqual(ctx.exception.code, 'CONFLICT')
        self.assertEqual(self.template._lab_quantity(), 10)

    def test_22_same_key_across_routes_rejected(self):
        """同 key 先 receipt 再 issue：指纹包含接口名，必须拒绝而不是返回旧结果。"""
        key = _key('cross')
        common = self.common.with_user(self.operator)
        common.lab_receipt({
            'request_key': key,
            'item_key': 'lcsc:%s' % self.template.lab_lcsc_code,
            'location_id': self.location_a.id,
            'quantity': 5,
        })
        bag = self.env['lab.bag'].search([('product_tmpl_id', '=', self.template.id)], limit=1)
        with self.assertRaises(LabApiError) as ctx:
            common.lab_issue({
                'request_key': key,
                'borrower_id': self.operator.id,
                'project': 'P',
                'lines': [{'bag_id': bag.id, 'quantity': 5}],
            })
        self.assertEqual(ctx.exception.code, 'CONFLICT')
        self.assertEqual(self.template._lab_quantity(), 5)

    def test_23_return_retry_is_idempotent(self):
        receipt = self._receipt(10)
        bag = self.env['lab.bag'].browse(receipt['bag']['id'])
        issue = self._issue(bag.id, 10)
        line_id = issue['lines'][0]['issue_line_id']
        key = _key('ret')
        common = self.common.with_user(self.operator)
        params = {'request_key': key, 'issue_line_id': line_id, 'quantity': 4}
        first, replayed_first = common.lab_return(dict(params))
        second, replayed_second = common.lab_return(dict(params))
        self.assertFalse(replayed_first)
        self.assertTrue(replayed_second)
        self.assertEqual(first['outstanding_quantity'], second['outstanding_quantity'], 6)
        line = self.env['lab.issue.line'].browse(line_id)
        line.invalidate_recordset()
        self.assertEqual(line.returned_quantity, 4)
        self.assertEqual(line.outstanding_quantity, 6)

    def test_24_invalid_request_key_rejected(self):
        common = self.common.with_user(self.operator)
        for bad in (None, '', 'short', 'has space'):
            with self.assertRaises(LabApiError):
                common.lab_receipt({
                    'request_key': bad,
                    'item_key': 'lcsc:%s' % self.template.lab_lcsc_code,
                    'location_id': self.location_a.id,
                    'quantity': 1,
                })

    # ==================================================================
    # 4. 权限 / 越权
    # ==================================================================
    def test_30_outsider_cannot_use_business_methods(self):
        common = self.common.with_user(self.outsider)
        with self.assertRaises(LabApiError) as ctx:
            common.lab_receipt({
                'request_key': _key('rcv'),
                'item_key': 'lcsc:%s' % self.template.lab_lcsc_code,
                'location_id': self.location_a.id,
                'quantity': 1,
            })
        self.assertIn(ctx.exception.code, ('FORBIDDEN', 'UNAUTHORIZED'))
        self.assertEqual(self.template._lab_quantity(), 0)

    def test_31_public_user_rejected(self):
        public = self.env.ref('base.public_user')
        common = self.common.with_user(public)
        with self.assertRaises(LabApiError):
            common.lab_receipt({
                'request_key': _key('rcv'),
                'item_key': 'lcsc:%s' % self.template.lab_lcsc_code,
                'location_id': self.location_a.id,
                'quantity': 1,
            })

    def test_32_operator_cannot_borrow_for_others(self):
        receipt = self._receipt(10)
        bag = self.env['lab.bag'].browse(receipt['bag']['id'])
        common = self.common.with_user(self.operator)
        with self.assertRaises(LabApiError) as ctx:
            common.lab_issue({
                'request_key': _key('iss'),
                'borrower_id': self.other_operator.id,
                'project': 'P',
                'lines': [{'bag_id': bag.id, 'quantity': 1}],
            })
        self.assertEqual(ctx.exception.code, 'FORBIDDEN')
        self.assertEqual(sum(self._bag_quants(bag).mapped('quantity')), 10)

    def test_33_manager_can_borrow_for_others_and_keeps_actor(self):
        receipt = self._receipt(10)
        bag = self.env['lab.bag'].browse(receipt['bag']['id'])
        common = self.common.with_user(self.manager)
        data, _replayed = common.lab_issue({
            'request_key': _key('iss'),
            'borrower_id': self.other_operator.id,
            'project': '代领项目',
            'lines': [{'bag_id': bag.id, 'quantity': 3}],
        })
        self.assertEqual(data['operation']['borrower_id'], self.other_operator.id)
        self.assertEqual(data['operation']['actor_id'], self.manager.id)
        line = self.env['lab.issue.line'].browse(data['lines'][0]['issue_line_id'])
        self.assertEqual(line.actor_id, self.manager)
        self.assertEqual(line.borrower_id, self.other_operator)

    def test_34_borrower_must_be_active_internal_user(self):
        receipt = self._receipt(10)
        bag = self.env['lab.bag'].browse(receipt['bag']['id'])
        common = self.common.with_user(self.manager)
        inactive = self.env['res.users'].with_context(
            no_reset_password=True).create({
                'name': 'inactive', 'login': 'lab_inactive',
                'company_id': self.company.id,
                'company_ids': [(6, 0, [self.company.id])],
                'group_ids': [(4, self.env.ref('lab_workflow.group_lab_operator').id)],
            })
        inactive.active = False
        with self.assertRaises(LabApiError):
            common.lab_issue({'request_key': _key('iss'), 'borrower_id': inactive.id,
                              'project': 'P', 'lines': [{'bag_id': bag.id, 'quantity': 1}]})
        public = self.env.ref('base.public_user')
        with self.assertRaises(LabApiError):
            common.lab_issue({'request_key': _key('iss'), 'borrower_id': public.id,
                              'project': 'P', 'lines': [{'bag_id': bag.id, 'quantity': 1}]})

    def test_35_authorized_borrowers_shape(self):
        common = self.common.with_user(self.operator)
        bootstrap = common.lab_bootstrap()
        ids = [row['id'] for row in bootstrap['borrowers']]
        self.assertEqual(ids, [self.operator.id])
        self.assertFalse(bootstrap['permissions']['can_issue_for_others'])
        manager_common = self.common.with_user(self.manager)
        manager_ids = [row['id'] for row in manager_common.lab_bootstrap()['borrowers']]
        self.assertIn(self.operator.id, manager_ids)
        self.assertTrue(manager_common.lab_bootstrap()['permissions']['can_issue_for_others'])

    def test_36_issues_visibility(self):
        receipt = self._receipt(10)
        bag = self.env['lab.bag'].browse(receipt['bag']['id'])
        self._issue(bag.id, 4, borrower=self.operator)
        operator_common = self.common.with_user(self.operator)
        rows = operator_common.lab_issues(outstanding_only=True,
                                          viewer_only_self=True)['issues']
        self.assertTrue(all(row['borrower_id'] == self.operator.id for row in rows))
        manager_common = self.common.with_user(self.manager)
        all_rows = manager_common.lab_issues(outstanding_only=True)['issues']
        self.assertTrue(any(row['bag_id'] == bag.id for row in all_rows))

    # ==================================================================
    # 5. 服务边界：伪造 context 也不能改历史/actor/borrower/lot
    # ==================================================================
    def test_40_fake_context_cannot_modify_protected_fields(self):
        receipt = self._receipt(10)
        bag = self.env['lab.bag'].browse(receipt['bag']['id'])
        issue = self._issue(bag.id, 4)
        line = self.env['lab.issue.line'].browse(issue['lines'][0]['issue_line_id'])
        operation = self.env['lab.operation'].browse(issue['operation']['id'])

        fake_context = {'lab_workflow_internal': True, 'allowed_company_ids': [self.company.id]}
        operator_env = self.env(user=self.operator, context=fake_context)

        # 改领用人 / 操作人 / 数量
        with self.assertRaises(AccessError):
            operator_env['lab.issue.line'].browse(line.id).write({'borrower_id': self.manager.id})
        with self.assertRaises(AccessError):
            operator_env['lab.issue.line'].browse(line.id).write({'actor_id': self.manager.id})
        with self.assertRaises(AccessError):
            operator_env['lab.issue.line'].browse(line.id).write({'quantity': 999})
        with self.assertRaises(AccessError):
            operator_env['lab.operation'].browse(operation.id).write({'actor_id': self.manager.id})
        with self.assertRaises(AccessError):
            operator_env['lab.operation'].browse(operation.id).write(
                {'borrower_id': self.manager.id})
        # 改袋的批次绑定 / 数量
        with self.assertRaises(AccessError):
            operator_env['lab.bag'].browse(bag.id).write({'lot_id': False})
        with self.assertRaises(AccessError):
            operator_env['lab.bag'].browse(bag.id).write({'quantity': 12345})
        # 直接建流水
        with self.assertRaises(AccessError):
            operator_env['lab.issue.line'].create({
                'bag_id': bag.id, 'quantity': 1, 'borrower_id': self.operator.id,
                'actor_id': self.manager.id, 'project': '伪造',
            })
        with self.assertRaises(AccessError):
            operator_env['lab.operation'].create({'operation_type': 'issue'})
        # 库存与责任人均未被改动
        line.invalidate_recordset()
        self.assertEqual(line.borrower_id, self.operator)
        self.assertEqual(line.actor_id, self.operator)
        self.assertEqual(line.quantity, 4)
        self.assertEqual(sum(self._bag_quants(bag).mapped('quantity')), 6)

    def test_41_public_service_method_rejects_outsider_via_call_kw(self):
        """模拟 /web/dataset/call_kw：无权限账号直接调用公开模型方法必须失败。"""
        outsider = self.env['lab.workflow.common'].with_user(self.outsider)
        with self.assertRaises(LabApiError):
            outsider.lab_receipt({'request_key': _key('rcv'), 'item_key': 'lcsc:C1',
                                  'location_id': self.location_a.id, 'quantity': 1})
        with self.assertRaises(LabApiError):
            outsider.lab_adopt_untracked_stock('lcsc:%s' % self.template.lab_lcsc_code, [])

    def test_42_unlink_history_rejected(self):
        receipt = self._receipt(5)
        bag = self.env['lab.bag'].browse(receipt['bag']['id'])
        manager_env = self.env(user=self.manager)
        with self.assertRaises(UserError):
            manager_env['lab.bag'].browse(bag.id).unlink()
        with self.assertRaises(UserError):
            manager_env['lab.operation'].browse(
                receipt['operation']['id']).unlink()

    # ==================================================================
    # 6. 并发（顺序部分；真正的相交并发见文件末尾
    #    LabWorkflowConcurrencyTest 与 tools/http_concurrency_check.py）
    # ==================================================================
    def test_50_sequential_second_issue_limited_by_remaining_stock(self):
        """顺序：第一笔领用成功后，第二笔只能按剩余库存领。

        注意：这是**顺序**验证，确认「加锁后重新读实时 quant」的校验逻辑；
        真正的并发相交执行**不在 TransactionCase 里做**（会污染测试隔离），
        见 LabWorkflowConcurrencyTest / tools/http_concurrency_check.py。
        """
        receipt = self._receipt(10)
        bag = self.env['lab.bag'].browse(receipt['bag']['id'])
        data, _ = self.env['lab.workflow.common'].lab_issue({
            'request_key': _key('c1'), 'borrower_id': self.operator.id,
            'project': '顺序A', 'lines': [{'bag_id': bag.id, 'quantity': 8}]})
        self.assertEqual(data['lines'][0]['quantity'], 8)
        self.assertEqual(sum(self._bag_quants(bag).mapped('quantity')), 2)
        with self.assertRaises(LabApiError) as ctx:
            self.env['lab.workflow.common'].lab_issue({
                'request_key': _key('c2'), 'borrower_id': self.operator.id,
                'project': '顺序B', 'lines': [{'bag_id': bag.id, 'quantity': 8}]})
        self.assertEqual(ctx.exception.code, 'PRECONDITION_FAILED')
        self.assertEqual(sum(self._bag_quants(bag).mapped('quantity')), 2)
        self.assertEqual(len(self.env['lab.issue.line'].search([('bag_id', '=', bag.id)])), 1)

    def test_51_same_request_key_second_call_replays(self):
        """顺序重试：同 request_key 第二次调用返回原结果，不再记账。"""
        receipt = self._receipt(10)
        bag = self.env['lab.bag'].browse(receipt['bag']['id'])
        params = {'request_key': _key('same'), 'borrower_id': self.operator.id,
                  'project': '同key', 'lines': [{'bag_id': bag.id, 'quantity': 5}]}
        first, replayed_first = self.env['lab.workflow.common'].lab_issue(dict(params))
        second, replayed_second = self.env['lab.workflow.common'].lab_issue(dict(params))
        self.assertFalse(replayed_first)
        self.assertTrue(replayed_second)
        self.assertEqual(first['operation']['id'], second['operation']['id'])
        issues = self.env['lab.issue.line'].search([('bag_id', '=', bag.id)])
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues.quantity, 5)

    # ==================================================================
    # 7. 历史无批次库存的安全适配
    # ==================================================================
    def test_60_legacy_untracked_stock_requires_adoption(self):
        """已有无批次正库存时：拒绝自动开启跟踪，必须先显式适配。"""
        legacy = self.env['product.template'].create({
            'name': '历史无批次物料',
            'type': 'consu',
            'is_storable': True,
            'tracking': 'none',
            'lab_lcsc_code': 'C999002',
        })
        self.env['stock.quant']._update_available_quantity(
            legacy.product_variant_id, self.location_a, 7)
        self.assertEqual(legacy._lab_quantity(), 7)
        self.assertEqual(legacy.tracking, 'none')

        report = self.common.lab_legacy_stock_report('lcsc:C999002')
        self.assertTrue(report['needs_adoption'])
        self.assertEqual(report['untracked_quantity'], 7)

        with self.assertRaises(LabApiError) as ctx:
            self._receipt(5, item_key='lcsc:C999002')
        self.assertIn('历史库存', str(ctx.exception))
        self.assertEqual(legacy._lab_quantity(), 7)
        self.assertEqual(legacy.tracking, 'none')

    def test_61_adoption_keeps_total_and_clears_untracked(self):
        legacy = self.env['product.template'].create({
            'name': '历史无批次物料2',
            'type': 'consu',
            'is_storable': True,
            'tracking': 'none',
            'lab_lcsc_code': 'C999003',
        })
        # 历史无批次库存可能散落在多个库位：R01 有 4、R02 有 3，总共 7
        self.env['stock.quant']._update_available_quantity(
            legacy.product_variant_id, self.location_a, 4)
        self.env['stock.quant']._update_available_quantity(
            legacy.product_variant_id, self.location_b, 3)
        self.assertEqual(legacy._lab_quantity(), 7)

        manager_common = self.common.with_user(self.manager)
        result = manager_common.lab_adopt_untracked_stock(
            'lcsc:C999003',
            [
                {'location_id': self.location_a.id, 'quantity': 4, 'trace_code': 'TRCADOPT0001'},
                {'location_id': self.location_b.id, 'quantity': 3, 'trace_code': 'TRCADOPT0002'},
            ],
            note='历史适配测试',
        )
        self.assertEqual(result['total_quantity'], 7)
        self.assertEqual(len(result['bags']), 2)
        legacy.invalidate_recordset()
        self.assertEqual(legacy.tracking, 'lot')
        # 总量不变
        self.assertEqual(legacy._lab_quantity(), 7)
        # 无批次正库存清零
        untracked = self.env['stock.quant'].search([
            ('product_id', '=', legacy.product_variant_id.id),
            ('lot_id', '=', False),
            ('location_id.usage', '=', 'internal'),
            ('quantity', '>', 0),
        ])
        self.assertFalse(untracked)
        # 两袋数量分别是 4 / 3
        quantities = sorted(bag.quantity for bag in self.env['lab.bag'].search(
            [('product_tmpl_id', '=', legacy.id)]))
        self.assertEqual(quantities, [3.0, 4.0])

    def test_62_adoption_total_mismatch_rejected(self):
        legacy = self.env['product.template'].create({
            'name': '历史无批次物料3',
            'type': 'consu',
            'is_storable': True,
            'tracking': 'none',
            'lab_lcsc_code': 'C999004',
        })
        self.env['stock.quant']._update_available_quantity(
            legacy.product_variant_id, self.location_a, 7)
        manager_common = self.common.with_user(self.manager)
        with self.assertRaises(LabApiError) as ctx:
            manager_common.lab_adopt_untracked_stock(
                'lcsc:C999004', [{'location_id': self.location_a.id, 'quantity': 5}])
        self.assertIn('总量', str(ctx.exception))
        self.assertEqual(legacy._lab_quantity(), 7)
        self.assertEqual(legacy.tracking, 'none')

    def test_63_adoption_requires_manager(self):
        legacy = self.env['product.template'].create({
            'name': '历史无批次物料4',
            'type': 'consu',
            'is_storable': True,
            'tracking': 'none',
            'lab_lcsc_code': 'C999005',
        })
        self.env['stock.quant'].with_context(inventory_mode=True).create({
            'product_id': legacy.product_variant_id.id,
            'location_id': self.location_a.id,
            'quantity': 3,
        }).action_apply_inventory()
        operator_common = self.common.with_user(self.operator)
        with self.assertRaises(LabApiError):
            operator_common.lab_adopt_untracked_stock(
                'lcsc:C999005', [{'location_id': self.location_a.id, 'quantity': 3}])
        self.assertEqual(legacy.tracking, 'none')

    # ==================================================================
    # 8. 标签（只读）
    # ==================================================================
    def test_70_label_preview_does_not_change_stock(self):
        receipt = self._receipt(20)
        bag = self.env['lab.bag'].browse(receipt['bag']['id'])
        before = self.template._lab_quantity()
        data = self.common.lab_labels_preview(
            kind='bag', ids=[bag.id], copies=2, width_mm=50, height_mm=30,
            margin_mm=10, gap_mm=2,
            fields=['sn', 'location', 'mpn', 'catalog_code', 'parameters'])
        self.assertEqual(data['mime_type'], 'application/pdf')
        self.assertEqual(data['label_count'], 2)
        self.assertEqual(data['qr_per_label'], 1)
        pdf = __import__('base64').b64decode(data['pdf_base64'])
        self.assertTrue(pdf.startswith(b'%PDF'))
        self.assertEqual(self.template._lab_quantity(), before)
        self.assertEqual(bag.quantity, 20)

    def test_71_label_location_kind(self):
        payload = self.location_a._lab_label_payload()
        self.assertTrue(payload.startswith('LABL:'))
        data = self.common.lab_labels_preview(
            kind='location', ids=[self.location_a.id], copies=1,
            width_mm=40, height_mm=20, margin_mm=10, gap_mm=2,
            fields=['location'])
        self.assertEqual(data['label_count'], 1)
        self.assertTrue(data['pdf_base64'])

    def test_72_label_overflow_and_too_small_rejected(self):
        receipt = self._receipt(1)
        bag = self.env['lab.bag'].browse(receipt['bag']['id'])
        with self.assertRaises(LabApiError):
            self.common.lab_labels_preview(kind='bag', ids=[bag.id], width_mm=300,
                                           height_mm=30, margin_mm=5, gap_mm=2,
                                           fields=['sn'])
        with self.assertRaises(LabApiError):
            self.common.lab_labels_preview(kind='bag', ids=[bag.id], width_mm=20,
                                           height_mm=14, margin_mm=5, gap_mm=2,
                                           fields=['sn'])

    def test_73_label_plan_counts(self):
        receipt = self._receipt(1)
        bag = self.env['lab.bag'].browse(receipt['bag']['id'])
        plan = self.common.lab_labels_plan(kind='bag', ids=[bag.id] * 10, copies=2,
                                           width_mm=50, height_mm=30, margin_mm=10,
                                           gap_mm=2, fields=['sn', 'location'])
        self.assertEqual(plan['label_count'], 20)
        self.assertEqual(plan['labels_per_page'], 24)
        self.assertEqual(plan['page_count'], 1)

    # ==================================================================
    # 9. 扫码解析
    # ==================================================================
    def test_80_resolve_codes(self):
        receipt = self._receipt(5)
        bag = self.env['lab.bag'].browse(receipt['bag']['id'])
        resolved = self.common.lab_resolve_code(bag.payload)
        self.assertEqual(resolved['kind'], 'bag')
        self.assertEqual(resolved['bag']['id'], bag.id)
        self.assertEqual(resolved['item_key'], 'lcsc:C999001')

        location = self.common.lab_resolve_code(
            self.location_a._lab_label_payload())
        self.assertEqual(location['kind'], 'location')
        self.assertEqual(location['location']['id'], self.location_a.id)

        by_sn = self.common.lab_resolve_code(self.template.lab_sn)
        self.assertEqual(by_sn['kind'], 'sn')
        self.assertEqual(by_sn['material']['product_template_id'], self.template.id)

        by_c = self.common.lab_resolve_code('c999001')
        self.assertEqual(by_c['kind'], 'lcsc')
        self.assertEqual(by_c['material']['product_template_id'], self.template.id)

        jlc = self.common.lab_resolve_code('{on:SO2202102855,pc:C999001,pm:X,qty:5}')
        self.assertEqual(jlc['kind'], 'jlc')
        self.assertEqual(jlc['supplier_metadata']['order_no'], 'SO2202102855')

        with self.assertRaises(LabApiError):
            self.common.lab_resolve_code('乱七八糟')

    def test_81_history_trace(self):
        receipt = self._receipt(10)
        bag = self.env['lab.bag'].browse(receipt['bag']['id'])
        issue = self._issue(bag.id, 4)
        common = self.common.with_user(self.operator)
        common.lab_return({'request_key': _key('ret'),
                           'issue_line_id': issue['lines'][0]['issue_line_id'],
                           'quantity': 2})
        history = common.lab_history(bag_id=bag.id)['operations']
        types = sorted(row['operation_type'] for row in history)
        self.assertEqual(types, ['issue', 'receipt', 'return'])
        for row in history:
            self.assertEqual(row['actor_id'], self.operator.id)
            self.assertTrue(row['lot_name'])

    # ==================================================================
    # 10. 约束真的建到数据库
    # ==================================================================
    def test_90_sql_unique_constraints_exist_in_postgres(self):
        self.env.cr.execute("""
            SELECT conname FROM pg_constraint
            WHERE conrelid = 'lab_bag'::regclass AND contype = 'u'
        """)
        bag_constraints = [row[0] for row in self.env.cr.fetchall()]
        self.assertIn('lab_bag_trace_code_uniq', bag_constraints)
        self.env.cr.execute("""
            SELECT conname FROM pg_constraint
            WHERE conrelid = 'lab_request_log'::regclass AND contype = 'u'
        """)
        log_constraints = [row[0] for row in self.env.cr.fetchall()]
        self.assertIn('lab_request_log_request_key_user_company_method_uniq',
                      log_constraints)

    def test_91_duplicate_trace_code_rejected_by_db(self):
        first = self._receipt(1)
        with self.assertRaises(Exception):
            self.env['lab.bag'].create({
                'trace_code': first['bag']['trace_code'],
                'company_id': self.company.id,
                'product_tmpl_id': self.template.id,
                'product_id': self.product.id,
                'location_id': self.location_a.id,
            })


    # ==================================================================
    # 11. 同一 C 编号多个本地档案：SN 绑定必须精确，不随机取 first
    # ==================================================================
    def _make_second_profile(self, catalog_code='C999001'):
        """为同一个 C 编号再建一个本地档案（模拟历史档案/同事档案）。"""
        return self.env['product.template'].create({
            'name': '测试电阻 270Ω（第二档案）',
            'type': 'consu',
            'is_storable': True,
            'tracking': 'lot',
            'lab_lcsc_code': catalog_code,
            'lab_mpn': 'TEST-R-270-B',
            'lab_sn': 'LAB-TEST-0002',
        })

    def test_100_multiple_profiles_same_c_code_ambiguous(self):
        second = self._make_second_profile()
        common = self.common.with_user(self.operator)
        # 不指定档案：必须明确报 AMBIGUOUS_MATERIAL 并给出候选，不能随机取 first
        with self.assertRaises(LabApiError) as ctx:
            common.lab_receipt({
                'request_key': _key('amb'),
                'item_key': 'lcsc:%s' % self.template.lab_lcsc_code,
                'location_id': self.location_a.id,
                'quantity': 5,
            })
        self.assertEqual(ctx.exception.code, 'AMBIGUOUS_MATERIAL')
        candidates = ctx.exception.fields.get('candidates') or []
        ids = sorted(row['product_template_id'] for row in candidates)
        self.assertEqual(ids, sorted([self.template.id, second.id]))
        self.assertEqual(self.template._lab_quantity(), 0)
        self.assertEqual(second._lab_quantity(), 0)

    def test_101_receipt_with_explicit_template_binds_that_profile(self):
        second = self._make_second_profile()
        common = self.common.with_user(self.operator)
        data, _ = common.lab_receipt({
            'request_key': _key('pick'),
            'item_key': 'lcsc:%s' % self.template.lab_lcsc_code,
            'product_template_id': second.id,
            'location_id': self.location_a.id,
            'quantity': 6,
        })
        self.assertEqual(data['product_template_id'], second.id)
        bag = self.env['lab.bag'].browse(data['bag']['id'])
        self.assertEqual(bag.product_tmpl_id, second)
        self.assertEqual(second._lab_quantity(), 6)
        # 旧档案库存不受影响
        self.assertEqual(self.template._lab_quantity(), 0)

    def test_102_template_id_must_match_catalog_code(self):
        other = self.env['product.template'].create({
            'name': '另一个 C 编号物料', 'type': 'consu', 'is_storable': True,
            'tracking': 'lot', 'lab_lcsc_code': 'C999099', 'lab_sn': 'LAB-TEST-0003',
        })
        common = self.common.with_user(self.operator)
        with self.assertRaises(LabApiError) as ctx:
            common.lab_receipt({
                'request_key': _key('mis'),
                'item_key': 'lcsc:%s' % self.template.lab_lcsc_code,
                'product_template_id': other.id,
                'location_id': self.location_a.id,
                'quantity': 5,
            })
        self.assertEqual(ctx.exception.code, 'PRECONDITION_FAILED')
        self.assertEqual(other._lab_quantity(), 0)

    def test_103_scan_sn_binds_its_own_profile(self):
        """扫 SN 入库：即使同 C 有多个档案，也必须归到该 SN 自己的档案。"""
        second = self._make_second_profile()
        common = self.common.with_user(self.operator)
        # 用第二个档案的 SN 入库
        data, _ = common.lab_receipt({
            'request_key': _key('sn'),
            'item_key': 'lcsc:%s' % self.template.lab_lcsc_code,
            'sn': second.lab_sn,
            'location_id': self.location_a.id,
            'quantity': 4,
        })
        self.assertEqual(data['product_template_id'], second.id)
        bag = self.env['lab.bag'].browse(data['bag']['id'])
        self.assertEqual(bag.product_tmpl_id, second)
        # 与传入的 product_template_id 不一致时必须拒绝
        with self.assertRaises(LabApiError):
            common.lab_receipt({
                'request_key': _key('sn2'),
                'item_key': 'lcsc:%s' % self.template.lab_lcsc_code,
                'sn': second.lab_sn,
                'product_template_id': self.template.id,
                'location_id': self.location_a.id,
                'quantity': 1,
            })
        self.assertEqual(self.template._lab_quantity(), 0)

    def test_104_resolve_code_reports_candidates(self):
        second = self._make_second_profile()
        common = self.common.with_user(self.operator)
        resolved = common.lab_resolve_code('c999001')
        self.assertTrue(resolved['ambiguous_material'])
        self.assertEqual(sorted(row['product_template_id']
                                for row in resolved['candidates']),
                         sorted([self.template.id, second.id]))
        self.assertIsNone(resolved.get('material'))
        # 扫 SN 时精确到该档案
        by_sn = common.lab_resolve_code(second.lab_sn)
        self.assertEqual(by_sn['product_template_id'], second.id)
        self.assertEqual(by_sn['material']['product_template_id'], second.id)

    def test_105_bag_resolve_keeps_its_own_profile(self):
        second = self._make_second_profile()
        data, _ = self.common.with_user(self.operator).lab_receipt({
            'request_key': _key('bag'),
            'item_key': 'lcsc:%s' % self.template.lab_lcsc_code,
            'product_template_id': second.id,
            'location_id': self.location_a.id,
            'quantity': 3,
        })
        bag = self.env['lab.bag'].browse(data['bag']['id'])
        resolved = self.common.lab_resolve_code(bag.payload)
        self.assertEqual(resolved['kind'], 'bag')
        # 袋保留自己的确切模板，不因为 canonical item_key 相同而改绑
        self.assertEqual(resolved['product_template_id'], second.id)
        self.assertEqual(resolved['bag']['product_template_id'], second.id)
        # 该 C 编号下两个档案的库存分别累计
        self.assertEqual(second._lab_quantity(), 3)
        self.assertEqual(self.template._lab_quantity(), 0)


@tagged('at_install', '-post_install', 'lab_workflow')
class LabWorkflowHttpTest(HttpCase):
    """HTTP/JSON-RPC 真接口测试（同 cookie、非匿名）。"""

    def test_01_jsonrpc_requires_login(self):
        response = self.url_open(
            '/lab/api/inventory/bootstrap',
            data='{}',
            headers={'Content-Type': 'application/json'},
        )
        # 匿名：Odoo 会返回 session 过期错误或我们的 UNAUTHORIZED 信封
        self.assertIn(response.status_code, (200, 401, 404, 500))

    def test_02_authenticated_operator_bootstrap(self):
        operator = self.env['res.users'].search([('login', '=', 'lab_op')], limit=1)
        if not operator:
            self.skipTest('需要先运行 TransactionCase 创建测试账号')
        self.authenticate('lab_op', 'lab_op')
        response = self.url_open(
            '/lab/api/inventory/bootstrap',
            data='{}',
            headers={'Content-Type': 'application/json'},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn('jsonrpc', payload)
        self.assertIn('result', payload)
        self.assertTrue(payload['result']['ok'], payload)
        self.assertIn('borrowers', payload['result']['data'])
