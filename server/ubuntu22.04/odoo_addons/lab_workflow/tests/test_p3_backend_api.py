# -*- coding: utf-8 -*-
"""P3 后端窄接口与安全修复的 ORM 集成测试（Odoo 19 TransactionCase）。

覆盖点（与 backend-contract.md §3/§3.8 对应）：

1. 袋分页/袋详情（过滤、游标、只读角色、label_facts 仅 operator）
2. 库位改名/停用/换父级的守卫（有库存拒绝、成环拒绝、根库位拒绝）
3. 类别→库位映射 upsert/停用 + 真正进入 ``pending/resolve`` 推荐（只读）
4. 成员库存角色：manager-only、白名单（拒绝系统组）、最后管理员保护、
   不影响其它组
5. history 过滤（类型/日期/操作人）
6. ``pending/confirm`` 透传 ``supplier_qr`` / ``sn``（security/backend-audit G1）
7. ``labels/preview`` 不再返回 ``font_path``；畸形 id → VALIDATION_ERROR；
   缺失 id → NOT_FOUND
8. **S1 跨账号归还**：非 manager 归还他人领用行 → FORBIDDEN，库存与未归还量不变；
   manager 可代还且 actor/borrower 分别记录
9. **S3 adopt_stock 部分提交**：重复 trace_code → CONFLICT 且零残留
10. **S5 停用库位**：不能用于入库
11. **S2 畸形入参**：非法 id 一律 VALIDATION_ERROR（不是 INTERNAL_ERROR）

运行（隔离库，由 Lead 统一执行）::

    odoo-bin ... -d <isolated_db> -u lab_workflow --test-enable \
        --test-tags at_install --stop-after-init
"""

import uuid

from odoo.tests import TransactionCase, tagged

from ..models.lab_workflow_common import (
    CODE_CONFLICT, CODE_FORBIDDEN, CODE_NOT_FOUND, CODE_PRECONDITION,
    CODE_VALIDATION, LabApiError, internal_service,
)


def _key(prefix='p3'):
    return ('%s-%s' % (prefix, uuid.uuid4().hex))[:60]


@tagged('at_install', '-post_install', 'lab_workflow')
class LabP3BackendTest(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.common = cls.env['lab.workflow.common']
        warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.company.id)], limit=1)
        root = warehouse.lot_stock_id
        cls.location_a = root
        cls.location_b = cls.env['stock.location'].create({
            'name': 'P3B',
            'usage': 'internal',
            'location_id': root.location_id.id,
            'company_id': cls.company.id,
        })
        cls.categ = cls.env['product.category'].create({'name': 'P3 电阻类'})
        cls.template = cls.env['product.template'].create({
            'name': 'P3 测试电阻 100Ω',
            'type': 'consu',
            'is_storable': True,
            'tracking': 'lot',
            'categ_id': cls.categ.id,
            'lab_lcsc_code': 'C999101',
            'lab_mpn': 'P3-R-100',
            'lab_sn': 'LAB-P3-0001',
            'lab_specifications': '{"阻值": "100Ω"}',
        })
        cls.product = cls.template.product_variant_id
        cls.operator = cls._make_user('p3_op', 'lab_workflow.group_lab_operator')
        cls.operator2 = cls._make_user('p3_op2', 'lab_workflow.group_lab_operator')
        cls.viewer = cls._make_user('p3_view', 'lab_workflow.group_lab_user')
        cls.manager = cls._make_user('p3_mgr', 'lab_workflow.group_lab_manager')
        cls.outsider = cls._make_user('p3_out', 'base.group_user')

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
    def _receipt(self, quantity=10, location=None, user=None, item_key=None):
        data, _replayed = self.common.with_user(user or self.operator).lab_receipt({
            'request_key': _key('rcv'),
            'item_key': item_key or 'lcsc:C999101',
            'product_template_id': self.template.id,
            'location_id': (location or self.location_a).id,
            'quantity': quantity,
        })
        return data

    def _stored_quantity(self, location=None, lot=None):
        domain = [('product_id', '=', self.product.id),
                  ('location_id', '=', (location or self.location_a).id)]
        domain.append(('lot_id', '=', lot.id) if lot else ('lot_id', '=', False))
        return sum(self.env['stock.quant'].search(domain).mapped('quantity'))

    def _issue(self, bag, quantity=5, user=None, borrower=None, project='P3'):
        data, _replayed = self.common.with_user(user or self.operator).lab_issue({
            'request_key': _key('iss'),
            'borrower_id': (borrower or self.operator).id,
            'project': project,
            'lines': [{'bag_id': bag['id'], 'quantity': quantity}],
        })
        return data

    def _pending(self, count=1):
        return self.common.with_user(self.operator).lab_pending_create({
            'request_key': _key('prep'), 'item_key': 'lcsc:C999101',
            'product_template_id': self.template.id, 'quantity': 4, 'count': count,
        })['records']

    def _assert_code(self, code, func, *args, **kwargs):
        with self.assertRaises(LabApiError) as ctx:
            func(*args, **kwargs)
        self.assertEqual(ctx.exception.code, code, ctx.exception.message)
        return ctx.exception

    # ==================================================================
    # 1/2. 袋分页 + 袋详情
    # ==================================================================
    def test_01_bags_pagination_and_filters(self):
        first = self._receipt(10, self.location_a)
        second = self._receipt(6, self.location_b)

        data = self.common.with_user(self.viewer).lab_bags(has_stock=True)
        self.assertEqual({row['id'] for row in data['bags']},
                         {first['bag']['id'], second['bag']['id']})
        self.assertIsNone(data['next_cursor'])

        by_location = self.common.lab_bags(location_id=self.location_b.id)
        self.assertEqual([row['id'] for row in by_location['bags']],
                         [second['bag']['id']])

        by_code = self.common.lab_bags(query=first['bag']['trace_code'])
        self.assertEqual([row['id'] for row in by_code['bags']], [first['bag']['id']])

        by_item = self.common.lab_bags(item_key='lcsc:C999101')
        self.assertEqual(len(by_item['bags']), 2)

        page1 = self.common.lab_bags(limit=1)
        self.assertEqual(len(page1['bags']), 1)
        self.assertIsNotNone(page1['next_cursor'])
        page2 = self.common.lab_bags(limit=1, cursor=page1['next_cursor'])
        self.assertEqual(len(page2['bags']), 1)
        self.assertNotEqual(page1['bags'][0]['id'], page2['bags'][0]['id'])

        # 没有库存的袋（领空后）在 has_stock=true 时被过滤
        self._issue(first['bag'], quantity=10)
        self.env['lab.bag'].browse(first['bag']['id'])._lab_sync_quantity()
        self.assertEqual(len(self.common.lab_bags(has_stock=True)['bags']), 1)
        self.assertEqual(len(self.common.lab_bags(has_stock=False)['bags']), 2)

    def test_02_bag_detail_and_label_facts(self):
        receipt = self._receipt(10)
        bag = receipt['bag']
        issue = self._issue(bag, quantity=4)

        detail = self.common.with_user(self.operator).lab_bag_detail(bag_id=bag['id'])
        self.assertEqual(detail['bag']['trace_code'], bag['trace_code'])
        self.assertIn('parameters', detail['item'])
        self.assertEqual(len(detail['open_issues']), 1)
        self.assertEqual(detail['open_issues'][0]['issue_line_id'],
                         issue['lines'][0]['issue_line_id'])
        self.assertTrue(detail['history'])
        self.assertTrue(detail['label_facts'])
        self.assertNotIn('font_path', detail['label_facts'])

        # 只读角色：能看事实，但拿不到可打印载荷
        viewer_detail = self.common.with_user(self.viewer).lab_bag_detail(bag_id=bag['id'])
        self.assertIsNone(viewer_detail['label_facts'])

        # 用 trace_code 也能查
        by_code = self.common.lab_bag_detail(trace_code=bag['payload'])
        self.assertEqual(by_code['bag']['id'], bag['id'])

    def test_03_bag_detail_validation_and_not_found(self):
        self._assert_code(CODE_VALIDATION, self.common.lab_bag_detail)
        self._assert_code(CODE_VALIDATION, self.common.lab_bag_detail, bag_id='abc')
        self._assert_code(CODE_NOT_FOUND, self.common.lab_bag_detail, bag_id=9999999)

    def test_04_bags_outstanding_filter_has_no_silent_cap(self):
        """旧实现取前 2000 条未还袋会静默漏；现在必须是 SQL 子查询（无截断）。"""
        leaf = self.common._lab_outstanding_leaf()
        self.assertEqual(leaf[0], 'id')
        self.assertEqual(leaf[1], 'inselect')
        self.assertIn('outstanding_quantity > 0', leaf[2][0])

        first = self._receipt(5)
        second = self._receipt(5)
        self._issue(first['bag'], quantity=1)
        self._issue(second['bag'], quantity=1)
        data = self.common.with_user(self.operator).lab_bags(
            outstanding_only=True, has_stock=True)
        self.assertEqual({row['id'] for row in data['bags']},
                         {first['bag']['id'], second['bag']['id']})

        # 还清后不再出现
        line = self.env['lab.issue.line'].search(
            [('bag_id', '=', first['bag']['id'])], limit=1)
        self.common.with_user(self.operator).lab_return({
            'request_key': _key('ret'),
            'issue_line_id': line.id,
            'quantity': 1,
        })
        data = self.common.with_user(self.operator).lab_bags(outstanding_only=True)
        self.assertEqual([row['id'] for row in data['bags']], [second['bag']['id']])

    # ==================================================================
    # 3. 库位改/停用
    # ==================================================================
    def test_10_location_update_rename_and_deactivate_guard(self):
        result = self.common.with_user(self.manager).lab_location_update(
            location_id=self.location_b.id, name='P3B-改', note='备注')
        self.assertEqual(result['location']['name'], 'P3B-改')

        # 空库位可以停用
        self.common.with_user(self.manager).lab_location_update(
            location_id=self.location_b.id, active=False)
        self.assertFalse(self.env['stock.location'].browse(self.location_b.id).active)
        self.common.with_user(self.manager).lab_location_update(
            location_id=self.location_b.id, active=True)

        # 有库存后不能停用（含子库位口径）
        self._receipt(3, self.location_b)
        error = self._assert_code(
            CODE_PRECONDITION, self.common.with_user(self.manager).lab_location_update,
            location_id=self.location_b.id, active=False)
        self.assertEqual(error.fields.get('location'), 'has_stock')
        self.assertTrue(self.env['stock.location'].browse(self.location_b.id).active)

    def test_11_location_update_rejects_cycle_and_non_internal(self):
        child = self.env['stock.location'].create({
            'name': 'P3B-child', 'usage': 'internal',
            'location_id': self.location_b.id, 'company_id': self.company.id,
        })
        error = self._assert_code(
            CODE_PRECONDITION, self.common.with_user(self.manager).lab_location_update,
            location_id=self.location_b.id, update_parent=True, parent_id=child.id)
        self.assertEqual(error.fields.get('parent_id'), 'cycle')

        customer = self.env['stock.location'].create({
            'name': 'P3 客户位', 'usage': 'customer', 'company_id': self.company.id})
        self._assert_code(
            CODE_PRECONDITION, self.common.with_user(self.manager).lab_location_update,
            location_id=customer.id, name='不允许')

        # 非 manager 不能改库位
        self._assert_code(
            CODE_FORBIDDEN, self.common.with_user(self.operator).lab_location_update,
            location_id=self.location_b.id, name='越权')

    def test_12_inactive_location_cannot_receive(self):
        """S5：停用库位不能入库。"""
        empty = self.env['stock.location'].create({
            'name': 'P3-empty', 'usage': 'internal',
            'location_id': self.location_a.location_id.id,
            'company_id': self.company.id})
        self.common.with_user(self.manager).lab_location_update(
            location_id=empty.id, active=False)
        error = self._assert_code(CODE_VALIDATION, self.common.with_user(self.operator).lab_receipt, {
            'request_key': _key('rcv'),
            'item_key': 'lcsc:C999101',
            'location_id': empty.id,
            'quantity': 1,
        })
        self.assertEqual(error.fields.get('location_id'), 'inactive')

    # ==================================================================
    # 4. 类别→库位映射
    # ==================================================================
    def test_20_mapping_upsert_and_recommendation(self):
        created = self.common.with_user(self.manager).lab_mapping_set(
            category_id=self.categ.id, location_id=self.location_b.id, priority=5,
            note='P3 映射')
        self.assertTrue(created['created'])
        self.assertEqual(created['mapping']['priority'], 5)

        updated = self.common.with_user(self.manager).lab_mapping_set(
            category_id=self.categ.id, location_id=self.location_b.id, priority=1)
        self.assertFalse(updated['created'])
        self.assertEqual(updated['mapping']['priority'], 1)

        listing = self.common.with_user(self.viewer).lab_mapping_list()
        self.assertEqual(len(listing['mappings']), 1)
        self.assertEqual(listing['mappings'][0]['location_id'], self.location_b.id)

        # 推荐顺序：没有其它库存时，映射库位以"类别映射"出现（只读、不写库存）
        pending = self._pending(1)[0]
        resolved = self.common.with_user(self.operator).lab_pending_resolve(pending['payload'])
        reasons = {(row['id'], row['reason']) for row in resolved['recommendations']}
        self.assertIn((self.location_b.id, '类别映射'), reasons)
        self.assertFalse(self.env['lab.bag'].search(
            [('product_tmpl_id', '=', self.template.id)]))

        # 软停用后不再推荐
        self.common.with_user(self.manager).lab_mapping_remove(
            mapping_id=created['mapping']['id'])
        listing = self.common.with_user(self.viewer).lab_mapping_list()
        self.assertEqual(listing['mappings'], [])

    def test_21_mapping_permissions_and_validation(self):
        self._assert_code(
            CODE_FORBIDDEN, self.common.with_user(self.operator).lab_mapping_set,
            category_id=self.categ.id, location_id=self.location_b.id)
        self._assert_code(
            CODE_VALIDATION, self.common.with_user(self.manager).lab_mapping_set,
            category_id='abc', location_id=self.location_b.id)
        self._assert_code(
            CODE_NOT_FOUND, self.common.with_user(self.manager).lab_mapping_remove,
            mapping_id=9876543)

    # ==================================================================
    # 5. 成员 / 库存角色
    # ==================================================================
    def test_30_members_manager_only_and_role_whitelist(self):
        self._assert_code(CODE_FORBIDDEN, self.common.with_user(self.operator).lab_members)
        self._assert_code(CODE_FORBIDDEN, self.common.with_user(self.outsider).lab_members)

        data = self.common.with_user(self.manager).lab_members(query='p3_')
        logins = {row['login'] for row in data['members']}
        self.assertIn('p3_op', logins)
        self.assertIn('p3_mgr', logins)
        manager_row = [row for row in data['members'] if row['login'] == 'p3_mgr'][0]
        self.assertTrue(manager_row['roles']['lab_manager'])
        self.assertTrue(manager_row['is_self'])
        # 角色位是**按目标账号**算的：只读账号不应因为调用者是管理员而显示 manager
        viewer_row = [row for row in data['members'] if row['login'] == 'p3_view'][0]
        self.assertTrue(viewer_row['roles']['lab_user'])
        self.assertFalse(viewer_row['roles']['lab_manager'])
        self.assertFalse(viewer_row['roles']['lab_operator'])
        self.assertFalse(viewer_row['is_self'])

        # 只允许三个库存组
        self._assert_code(
            CODE_FORBIDDEN, self.common.with_user(self.manager).lab_member_set_role,
            user_id=self.outsider.id, role='system', enabled=True)
        self._assert_code(
            CODE_FORBIDDEN, self.common.with_user(self.manager).lab_member_set_role,
            user_id=self.outsider.id, role='catalog_user', enabled=True)

    def test_31_member_set_role_and_last_manager(self):
        member = self.common.with_user(self.manager).lab_member_set_role(
            user_id=self.outsider.id, role='lab_operator', enabled=True)
        # 返回的 roles 必须是**目标账号**的，而不是调用者的
        self.assertEqual(member['member']['id'], self.outsider.id)
        self.assertTrue(member['member']['roles']['lab_operator'])
        self.assertFalse(member['member']['roles']['lab_manager'])
        self.assertTrue(self.outsider.has_group('base.group_user'))

        member = self.common.with_user(self.manager).lab_member_set_role(
            user_id=self.outsider.id, role='lab_operator', enabled=False)
        self.assertFalse(member['member']['roles']['lab_operator'])
        self.assertTrue(self.outsider.has_group('base.group_user'))

        # 最后一名管理员：模块安装时会把默认 admin 加进管理员组，所以默认公司
        # 里"撤销自己"并不是真的最后一名。这里用**私有公司**隔离出"唯一 manager"，
        # 先证明该场景确实只有一名管理员，再断言拒绝。
        company_c, sole_manager = self._make_isolated_manager_company('p3_c_sole')
        self.assertEqual(self._managers_in_company(company_c).ids, [sole_manager.id])
        error = self._assert_code(
            CODE_PRECONDITION,
            self.common.with_company(company_c).with_user(sole_manager).lab_member_set_role,
            user_id=sole_manager.id, role='lab_manager', enabled=False)
        self.assertEqual(error.fields.get('role'), 'last_manager')
        self.assertIn(company_c.name, error.fields.get('company') or '')
        self.assertTrue(sole_manager.has_group('lab_workflow.group_lab_manager'))

    def test_34_two_managers_can_revoke_one(self):
        """正向：公司里有第二名 manager 时允许撤销，且角色位按目标账号返回。"""
        company_d, mgr1 = self._make_isolated_manager_company('p3_d_mgr1')
        mgr2 = self._make_company_manager(company_d, 'p3_d_mgr2')
        self.assertEqual(set(self._managers_in_company(company_d).ids),
                         {mgr1.id, mgr2.id})

        # 两个 managers 的成员列表：角色位各自独立（不是调用者的）
        listing = self.common.with_company(company_d).with_user(mgr1).lab_members(
            query='p3_d_')
        rows = {row['login']: row for row in listing['members']}
        self.assertTrue(rows['p3_d_mgr1']['roles']['lab_manager'])
        self.assertTrue(rows['p3_d_mgr2']['roles']['lab_manager'])

        result = self.common.with_company(company_d).with_user(mgr1).lab_member_set_role(
            user_id=mgr2.id, role='lab_manager', enabled=False)
        self.assertEqual(result['member']['id'], mgr2.id)
        self.assertFalse(result['member']['roles']['lab_manager'])
        self.assertTrue(result['changed'])
        # 调用者自己仍是 manager，公司里仍保留一名
        self.assertTrue(mgr1.has_group('lab_workflow.group_lab_manager'))
        self.assertEqual(self._managers_in_company(company_d).ids, [mgr1.id])

    # ------------------------------------------------------------------
    # 私有多公司/单公司夹具
    # ------------------------------------------------------------------
    def _managers_in_company(self, company):
        group = self.env.ref('lab_workflow.group_lab_manager')
        field = self.common._lab_user_group_field()
        users = self.env['res.users'].sudo().search([
            ('active', '=', True), ('share', '=', False), (field, 'in', [group.id]),
        ])
        return users.filtered(
            lambda user: not user.company_ids or company in user.company_ids)

    def _make_company_manager(self, company, login):
        return self.env['res.users'].with_context(no_reset_password=True).create({
            'name': login,
            'login': login,
            'email': '%s@example.invalid' % login,
            'company_id': company.id,
            'company_ids': [(6, 0, [company.id])],
            'group_ids': [(4, self.env.ref('lab_workflow.group_lab_manager').id)],
        })

    def _make_isolated_manager_company(self, login):
        """私有公司 + 唯一 manager：把"最后一名管理员"从默认公司的 admin 干扰里隔离。"""
        company = self.env['res.company'].create({'name': 'P3 测试公司 %s' % login})
        return company, self._make_company_manager(company, login)

    def test_32_member_set_role_cannot_skip_higher_role(self):
        self.common.with_user(self.manager).lab_member_set_role(
            user_id=self.outsider.id, role='lab_manager', enabled=True)
        error = self._assert_code(
            CODE_PRECONDITION, self.common.with_user(self.manager).lab_member_set_role,
            user_id=self.outsider.id, role='lab_user', enabled=False)
        self.assertEqual(error.fields.get('role'), 'implied_role')
        self.common.with_user(self.manager).lab_member_set_role(
            user_id=self.outsider.id, role='lab_manager', enabled=False)

    def test_33_multi_company_target_requires_system_admin(self):
        """S2-3：全局组对多公司账号只有系统管理员可改；撤销要按每个公司保证。"""
        other = self.env['res.company'].create({'name': 'P3 B 公司'})
        target = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'p3_multi',
            'login': 'p3_multi',
            'email': 'p3_multi@example.invalid',
            'company_id': self.company.id,
            'company_ids': [(6, 0, [self.company.id, other.id])],
            'group_ids': [(4, self.env.ref('lab_workflow.group_lab_user').id)],
        })

        # 非系统管理员：多公司目标 -> 安全拒绝（组是全局的，会连带影响 B 公司）
        error = self._assert_code(CODE_FORBIDDEN,
                                  self.common.with_user(self.manager).lab_member_set_role,
                                  user_id=target.id, role='lab_operator', enabled=True)
        self.assertEqual(error.fields.get('user_id'), 'multi_company')

        listing = self.common.lab_members(query='p3_multi')
        row = [item for item in listing['members'] if item['id'] == target.id][0]
        self.assertTrue(row['multi_company'])
        self.assertEqual(row['company_count'], 2)
        self.assertEqual(sorted(row['company_ids']), sorted([self.company.id, other.id]))

        # 系统管理员（测试环境 su）可以授予；授予后 B 公司也生效
        granted = self.common.lab_member_set_role(
            user_id=target.id, role='lab_manager', enabled=True)
        self.assertTrue(granted['member']['roles']['lab_manager'])

        # B 公司没有其它 manager -> 撤销必须被拒，并指名公司
        error = self._assert_code(CODE_PRECONDITION, self.common.lab_member_set_role,
                                  user_id=target.id, role='lab_manager', enabled=False)
        self.assertEqual(error.fields.get('role'), 'last_manager')
        self.assertIn(other.name, error.fields.get('company') or '')

        # 给 B 公司补一个管理员后，同一请求成功
        self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'p3_mgr_b',
            'login': 'p3_mgr_b',
            'email': 'p3_mgr_b@example.invalid',
            'company_id': other.id,
            'company_ids': [(6, 0, [other.id])],
            'group_ids': [(4, self.env.ref('lab_workflow.group_lab_manager').id)],
        })
        revoked = self.common.lab_member_set_role(
            user_id=target.id, role='lab_manager', enabled=False)
        self.assertFalse(revoked['member']['roles']['lab_manager'])

    # ==================================================================
    # 6. history 过滤
    # ==================================================================
    def test_40_history_filters(self):
        receipt = self._receipt(10)
        self._issue(receipt['bag'], quantity=3)

        all_rows = self.common.lab_history()['operations']
        types = {row['operation_type'] for row in all_rows}
        self.assertIn('receipt', types)
        self.assertIn('issue', types)

        only_issue = self.common.lab_history(operation_type='issue')['operations']
        self.assertTrue(only_issue)
        self.assertEqual({row['operation_type'] for row in only_issue}, {'issue'})

        by_actor = self.common.lab_history(actor_id=self.operator.id)['operations']
        self.assertTrue(by_actor)
        self.assertEqual({row['actor_id'] for row in by_actor}, {self.operator.id})

        future = self.common.lab_history(date_from='2999-01-01')['operations']
        self.assertEqual(future, [])
        self._assert_code(CODE_VALIDATION, self.common.lab_history,
                          operation_type='sale')
        self._assert_code(CODE_VALIDATION, self.common.lab_history,
                          date_from='2026/01/01')

    # ==================================================================
    # 7. pending/confirm 透传 supplier_qr / sn
    # ==================================================================
    def test_50_pending_confirm_passes_supplier_qr_and_sn(self):
        pending = self._pending(1)[0]
        data = self.common.with_user(self.operator).lab_pending_confirm({
            'request_key': _key('cfm'),
            'pending_id': pending['id'],
            'quantity': 4,
            'location_id': self.location_a.id,
            'supplier_qr': '{on:SO-P3-1,pc:C999101,pm:P3-R-100,qty:4}',
            'sn': self.template.lab_sn,
        })
        # pending/confirm 返回的是 receipt 结果 + record（单字典，不是元组）
        self.assertFalse(data.get('replayed'))
        bag = self.env['lab.bag'].browse(data['bag']['id'])
        self.assertEqual(bag.supplier_order, 'SO-P3-1')
        self.assertEqual(bag.supplier_mpn, 'P3-R-100')
        self.assertTrue(bag.supplier_payload)
        self.assertEqual(bag.quantity, 4)
        self.assertEqual(self.env['lab.pending.receipt'].browse(
            pending['id']).state, 'done')

    def test_51_pending_confirm_rejects_mismatched_sn(self):
        other = self.env['product.template'].create({
            'name': 'P3 另一档案', 'type': 'consu', 'is_storable': True,
            'tracking': 'lot', 'lab_lcsc_code': 'C999101',
            'lab_sn': 'LAB-P3-OTHER'})
        pending = self._pending(1)[0]
        error = self._assert_code(CODE_VALIDATION,
                                  self.common.with_user(self.operator).lab_pending_confirm, {
                                      'request_key': _key('cfm'),
                                      'pending_id': pending['id'],
                                      'quantity': 4,
                                      'location_id': self.location_a.id,
                                      'sn': other.lab_sn,
                                  })
        self.assertIn('sn', error.fields)
        self.assertEqual(self.env['lab.pending.receipt'].browse(pending['id']).state,
                         'pending')

    # ==================================================================
    # 8. 标签：无 font_path / 畸形 id / 缺失 id
    # ==================================================================
    def test_60_label_preview_has_no_font_path(self):
        receipt = self._receipt(2)
        data = self.common.with_user(self.operator).lab_labels_preview(
            kind='bag', ids=[receipt['bag']['id']], width_mm=60, height_mm=40,
            fields=['trace_code', 'name', 'mpn'])
        self.assertTrue(data['pdf_base64'])
        self.assertEqual(data['qr_per_label'], 1)
        self.assertNotIn('font_path', data)
        self.assertIn('font', data)

    def test_62_label_total_limit_enforced_before_rendering(self):
        """S2-2：ids×copies 总量在渲染前被拒（Lead 定 MAX_TOTAL_LABELS=200）。"""
        bag_ids = [self._receipt(1)['bag']['id'] for _ in range(10)]

        legal = self.common.with_user(self.operator).lab_labels_plan(
            kind='bag', ids=bag_ids, copies=20, width_mm=60, height_mm=40,
            fields=['trace_code'])
        self.assertEqual(legal['label_count'], 200)

        for copies in (21, 200):
            error = self._assert_code(
                CODE_VALIDATION, self.common.with_user(self.operator).lab_labels_plan,
                kind='bag', ids=bag_ids, copies=copies,
                width_mm=60, height_mm=40, fields=['trace_code'])
            self.assertEqual(error.fields.get('copies'), 'too_many_total')

        # 200 个不存在的 id × 200 份：总量校验必须先于 id 存在性（不泄露、不做重活）
        error = self._assert_code(
            CODE_VALIDATION, self.common.with_user(self.operator).lab_labels_preview,
            kind='bag', ids=list(range(1, 201)), copies=200,
            width_mm=60, height_mm=40, fields=['trace_code'])
        self.assertEqual(error.fields.get('copies'), 'too_many_total')

        # 合法上限（10×20=200）仍能真实生成 PDF，且张数一致
        data = self.common.with_user(self.operator).lab_labels_preview(
            kind='bag', ids=bag_ids, copies=20, width_mm=60, height_mm=40,
            fields=['trace_code'])
        self.assertTrue(data['pdf_base64'])
        self.assertEqual(data['label_count'], 200)

    def test_64_label_cross_company_is_active_company_scoped(self):
        """labels 按**当前活动公司**隔离：跨公司 bag/库位必须 NOT_FOUND。

        HTTP R2 test_05 暴露两点：①`labels/plan` 曾把 NOT_FOUND 吞成 ok=true；
        ②只靠记录规则（allowed_company_ids）不等于"活动公司隔离"。
        这里先用**普通 operator** 复现，再用 su + with_company(当前公司) 证明
        是显式 domain 在挡，而不是靠记录规则/sudo 绕过。
        """
        company_b, location_b = self._make_cross_company_location()

        for common in (self.common.with_user(self.operator),
                       self.common.with_company(self.company)):
            self._assert_code(
                CODE_NOT_FOUND, common.lab_labels_plan,
                kind='location', ids=[location_b.id],
                width_mm=60, height_mm=40, fields=['location'])

        _, line_b = self._make_cross_company_issue_line()
        bag_b = line_b.bag_id
        for common in (self.common.with_user(self.operator),
                       self.common.with_company(self.company)):
            self._assert_code(
                CODE_NOT_FOUND, common.lab_labels_preview,
                kind='bag', ids=[bag_b.id],
                width_mm=60, height_mm=40, fields=['trace_code'])

        # 共享库位（company_id=False）是允许的：不是"一刀切拒绝"
        shared = self.env['stock.location'].create({
            'name': 'P3 共享库位',
            'usage': 'internal',
            'company_id': False,
        })
        data = self.common.with_user(self.operator).lab_labels_preview(
            kind='location', ids=[shared.id], width_mm=60, height_mm=40,
            fields=['location'])
        self.assertTrue(data['pdf_base64'])
        self.assertTrue(company_b.exists())

    def test_63_label_malformed_ids_are_validation_errors(self):
        self._assert_code(CODE_VALIDATION, self.common.with_user(self.operator).lab_labels_preview,
                          kind='bag', ids=['x'], width_mm=60, height_mm=40)
        self._assert_code(CODE_VALIDATION, self.common.with_user(self.operator).lab_labels_preview,
                          kind='bag', ids=[1], copies='abc')
        self._assert_code(CODE_NOT_FOUND, self.common.with_user(self.operator).lab_labels_preview,
                          kind='bag', ids=[99999999])

    # ==================================================================
    # 9. S1 跨账号归还
    # ==================================================================
    def test_70_cross_owner_return_rejected(self):
        receipt = self._receipt(10)
        issue = self._issue(receipt['bag'], quantity=5)
        line_id = issue['lines'][0]['issue_line_id']
        line = self.env['lab.issue.line'].browse(line_id)
        outstanding_before = line.outstanding_quantity

        error = self._assert_code(CODE_FORBIDDEN,
                                  self.common.with_user(self.operator2).lab_return, {
                                      'request_key': _key('ret'),
                                      'issue_line_id': line_id,
                                      'quantity': 1,
                                  })
        self.assertEqual(error.fields.get('issue_line_id'), 'not_owner')
        self.assertEqual(line.outstanding_quantity, outstanding_before)
        self.assertFalse(self.env['lab.return.line'].search(
            [('issue_line_id', '=', line_id)]))
        # 库存未被扣减：袋里仍是 5（10 - 5）
        self.assertEqual(line.bag_id.quantity, 5)

        # manager 可以代还，actor/borrower 分开记录
        data, _ = self.common.with_user(self.manager).lab_return({
            'request_key': _key('ret'),
            'issue_line_id': line_id,
            'quantity': 2,
        })
        return_line = self.env['lab.return.line'].search(
            [('issue_line_id', '=', line_id)], limit=1)
        self.assertEqual(return_line.actor_id, self.manager)
        self.assertEqual(return_line.borrower_id, self.operator)
        self.assertEqual(data['outstanding_quantity'], 3)

    def test_71_return_id_boundaries(self):
        """不存在的行 -> NOT_FOUND；畸形 id -> VALIDATION_ERROR（不再是 INTERNAL）。"""
        self._assert_code(CODE_NOT_FOUND, self.common.with_user(self.operator).lab_return, {
            'request_key': _key('ret'), 'issue_line_id': 99999999, 'quantity': 1})
        self._assert_code(CODE_VALIDATION, self.common.with_user(self.operator).lab_return, {
            'request_key': _key('ret'), 'issue_line_id': 'abc', 'quantity': 1})

    def test_72_cross_company_return_is_not_found(self):
        """S2-4：归还取记录用 search（显式公司 domain），跨公司 = NOT_FOUND。

        跨公司夹具必须在服务端内部上下文里建（bag/issue.line 禁止直接 RPC 建档），
        并用 `with_company(B)` 建真实属于 B 公司的袋与领用行。
        """
        other, line_b = self._make_cross_company_issue_line()
        error = self._assert_code(
            CODE_NOT_FOUND,
            self.common.with_user(self.operator).lab_return, {
                'request_key': _key('ret'),
                'issue_line_id': line_b.id,
                'quantity': 1,
            })
        self.assertEqual(error.fields.get('issue_line_id'), 'not_found')
        # 他公司的领用行与库存都没有被改动
        self.env.invalidate_all()
        line = self.env['lab.issue.line'].browse(line_b.id)
        self.assertEqual(line.outstanding_quantity, 1)
        self.assertFalse(self.env['lab.return.line'].search(
            [('issue_line_id', '=', line_b.id)]))
        self.assertTrue(other.exists())

    def _make_cross_company_location(self):
        """B 公司 + 一个 B 公司内部库位（跨公司隔离断言用）。"""
        other = self.env['res.company'].create({
            'name': 'P3 跨公司 B 公司 ' + uuid.uuid4().hex[:8],
        })
        location = self.env['stock.location'].sudo().create({
            'name': 'P3 B-LOC-01',
            'usage': 'internal',
            'company_id': other.id,
        })
        return other, location

    def _make_cross_company_issue_line(self):
        """在 B 公司造一条真实领用行（内部服务上下文；只用于跨公司拒绝断言）。"""
        other, location_b = self._make_cross_company_location()
        with internal_service():
            template_b = self.env['product.template'].sudo().with_company(other).create({
                'name': 'P3 B 公司物料',
                'type': 'consu',
                'is_storable': True,
                'tracking': 'lot',
                'company_id': other.id,
            })
            bag_b = self.env['lab.bag'].sudo().with_company(other).create({
                'company_id': other.id,
                'product_tmpl_id': template_b.id,
                'product_id': template_b.product_variant_id.id,
                'location_id': location_b.id,
                'initial_quantity': 1,
                'quantity': 1,
            })
            line_b = self.env['lab.issue.line'].sudo().with_company(other).create({
                'company_id': other.id,
                'bag_id': bag_b.id,
                'quantity': 1,
                'borrower_id': self.operator.id,
                'actor_id': self.operator.id,
                'project': 'P3-CROSS',
            })
        return other, line_b

    # ==================================================================
    # 10. S3 adopt_stock：失败零残留
    # ==================================================================
    def _make_untracked_template(self):
        template = self.env['product.template'].create({
            'name': 'P3 历史库存件', 'type': 'consu', 'is_storable': True,
            'tracking': 'none', 'lab_lcsc_code': 'C999102'})
        product = template.product_variant_id
        return template, product

    def _add_untracked_stock(self, product, location, quantity):
        Quant = self.env['stock.quant'].sudo()
        try:
            Quant._update_available_quantity(product, location, quantity)
        except Exception:  # noqa: BLE001 - 兼容不同 19.0 小版本
            Quant.create({'product_id': product.id, 'location_id': location.id,
                          'quantity': quantity})
        return sum(Quant.search([('product_id', '=', product.id),
                                 ('location_id', '=', location.id)]).mapped('quantity'))

    def test_80_adopt_stock_duplicate_code_rolls_back(self):
        template, product = self._make_untracked_template()
        total = self._add_untracked_stock(product, self.location_a, 7.0)
        self.assertEqual(total, 7.0)

        error = self._assert_code(CODE_CONFLICT,
                                  self.common.with_user(self.manager).lab_adopt_untracked_stock,
                                  'lcsc:C999102', [
                                      {'location_id': self.location_a.id, 'quantity': 4,
                                       'trace_code': 'TRCP3ADOPT1'},
                                      {'location_id': self.location_a.id, 'quantity': 3,
                                       'trace_code': 'TRCP3ADOPT1'},
                                  ])
        self.assertTrue(error.message)
        self.env.invalidate_all()
        # 零残留：没有袋、没有作业单、无批次库存原样、跟踪仍为 none
        self.assertFalse(self.env['lab.bag'].search(
            [('product_tmpl_id', '=', template.id)]))
        self.assertFalse(self.env['lab.operation'].search(
            [('operation_type', '=', 'adopt')]))
        untracked = self.env['lab.workflow.common'].lab_untracked_positive_quants(
            product)
        self.assertEqual(sum(untracked.mapped('quantity')), 7.0)
        self.assertEqual(template.tracking, 'none')

    # ==================================================================
    # 11. S2 畸形入参
    # ==================================================================
    def test_90_malformed_inputs_are_validation_errors(self):
        self._receipt(5)

        self._assert_code(CODE_VALIDATION, self.common.with_user(self.operator).lab_receipt, {
            'request_key': _key('rcv'), 'item_key': 'lcsc:C999101',
            'location_id': 'abc', 'quantity': 1})
        self._assert_code(CODE_VALIDATION, self.common.with_user(self.operator).lab_issue, {
            'request_key': _key('iss'), 'borrower_id': self.operator.id,
            'project': 'P3', 'lines': [{'bag_id': 'abc', 'quantity': 1}]})
        self._assert_code(CODE_VALIDATION, self.common.with_user(self.operator).lab_return, {
            'request_key': _key('ret'), 'issue_line_id': 'abc', 'quantity': 1})
        self._assert_code(CODE_VALIDATION, self.common.lab_issues, limit='abc')
        self._assert_code(CODE_VALIDATION, self.common.lab_bags, limit=None,
                          cursor='abc')
        self._assert_code(CODE_VALIDATION, self.common.with_user(self.operator).lab_bag_detail,
                          bag_id='abc')
        self._assert_code(CODE_VALIDATION, self.common.with_user(self.manager).lab_location_update,
                          location_id='abc', name='x')

    def test_91_outsider_cannot_use_manager_endpoints(self):
        """无 lab 角色的内部账号：写/管理端点一律 FORBIDDEN。"""
        self._assert_code(CODE_FORBIDDEN,
                          self.common.with_user(self.outsider).lab_location_update,
                          location_id=self.location_b.id, name='越权')
        self._assert_code(CODE_FORBIDDEN,
                          self.common.with_user(self.outsider).lab_member_set_role,
                          user_id=self.outsider.id, role='lab_manager', enabled=True)
        self._assert_code(CODE_FORBIDDEN,
                          self.common.with_user(self.outsider).lab_mapping_set,
                          category_id=self.categ.id, location_id=self.location_b.id)
