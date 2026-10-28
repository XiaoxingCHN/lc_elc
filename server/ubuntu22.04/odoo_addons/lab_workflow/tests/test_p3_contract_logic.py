# -*- coding: utf-8 -*-
"""P3 纯逻辑测试（不依赖 Odoo/数据库）。

覆盖 ``tools/p3_rules.py``：分页/游标、布尔、角色白名单与最后管理员、
映射排序、日期与 history 过滤、库位改/停用守卫、标签批量边界、
``/lab/scan`` 迁移决策。

运行（在 lab_workflow 目录下）::

    python3 -m unittest tests.test_p3_contract_logic -v
"""

import importlib.util
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.abspath(os.path.join(_HERE, '..', 'tools'))

_spec = importlib.util.spec_from_file_location('p3_rules', os.path.join(_TOOLS, 'p3_rules.py'))
p3_rules = importlib.util.module_from_spec(_spec)
sys.modules['p3_rules'] = p3_rules
_spec.loader.exec_module(p3_rules)


class TestPaging(unittest.TestCase):

    def test_clamp_limit(self):
        self.assertEqual(p3_rules.clamp_limit(None), 24)
        self.assertEqual(p3_rules.clamp_limit(''), 24)
        self.assertEqual(p3_rules.clamp_limit(0), 24)
        self.assertEqual(p3_rules.clamp_limit(-5), 24)
        self.assertEqual(p3_rules.clamp_limit(10), 10)
        self.assertEqual(p3_rules.clamp_limit(999), 100)
        self.assertEqual(p3_rules.clamp_limit('8'), 8)
        self.assertEqual(p3_rules.clamp_limit('abc'), 24)
        self.assertEqual(p3_rules.clamp_limit(50, default=20, maximum=50), 50)

    def test_parse_cursor(self):
        self.assertIsNone(p3_rules.parse_cursor(None))
        self.assertIsNone(p3_rules.parse_cursor(''))
        self.assertEqual(p3_rules.parse_cursor('123'), 123)
        self.assertEqual(p3_rules.parse_cursor(123), 123)
        self.assertEqual(p3_rules.parse_cursor('0'), 0)
        for bad in ('abc', [], {}, True):
            with self.assertRaises(p3_rules.RuleError) as ctx:
                p3_rules.parse_cursor(bad)
            self.assertEqual(ctx.exception.field, 'cursor')
        with self.assertRaises(p3_rules.RuleError):
            p3_rules.parse_cursor('-1')

    def test_parse_bool(self):
        self.assertTrue(p3_rules.parse_bool(True))
        self.assertFalse(p3_rules.parse_bool(False))
        for value in ('1', 'true', 'ON', 'yes', 'y'):
            self.assertTrue(p3_rules.parse_bool(value))
        for value in ('0', 'false', 'off', 'no', 'n'):
            self.assertFalse(p3_rules.parse_bool(value))
        self.assertEqual(p3_rules.parse_bool(None, 'fallback'), 'fallback')

    def test_parse_text_bounds(self):
        self.assertEqual(p3_rules.parse_text('  abc  ', 'query'), 'abc')
        self.assertEqual(p3_rules.parse_text(None, 'query'), '')
        with self.assertRaises(p3_rules.RuleError):
            p3_rules.parse_text('x' * 65, 'query', 64)
        with self.assertRaises(p3_rules.RuleError):
            p3_rules.parse_text('', 'name', required=True)


class TestRoles(unittest.TestCase):

    def test_normalize_role_accepts_only_inventory_groups(self):
        self.assertEqual(p3_rules.normalize_role('lab_user'), 'lab_user')
        self.assertEqual(p3_rules.normalize_role('lab_operator'), 'lab_operator')
        self.assertEqual(p3_rules.normalize_role('lab_manager'), 'lab_manager')
        self.assertEqual(p3_rules.normalize_role('group_lab_operator'), 'lab_operator')
        self.assertEqual(p3_rules.normalize_role('lab_workflow.group_lab_manager'),
                         'lab_manager')

    def test_normalize_role_rejects_system_and_catalog(self):
        for bad in ('base.group_system', 'base.group_erp_manager', 'system',
                    'catalog_user', 'lab_catalog.group_lab_catalog_manager', '', None):
            with self.assertRaises(p3_rules.RuleError) as ctx:
                p3_rules.normalize_role(bad)
            self.assertEqual(ctx.exception.field, 'role')

    def test_last_manager_protected(self):
        with self.assertRaises(p3_rules.RuleError) as ctx:
            p3_rules.ensure_role_change_allowed(
                'lab_manager', False, True, {'lab_operator': True, 'lab_manager': True}, 0)
        self.assertEqual(ctx.exception.reason, 'last_manager')
        # 还剩一个 manager 时可以撤销
        self.assertTrue(p3_rules.ensure_role_change_allowed(
            'lab_manager', False, True, {'lab_operator': True, 'lab_manager': True}, 1))

    def test_implied_role_conflicts(self):
        with self.assertRaises(p3_rules.RuleError) as ctx:
            p3_rules.ensure_role_change_allowed(
                'lab_user', False, True, {'lab_operator': True, 'lab_manager': False}, 5)
        self.assertEqual(ctx.exception.reason, 'implied_role')
        with self.assertRaises(p3_rules.RuleError) as ctx:
            p3_rules.ensure_role_change_allowed(
                'lab_operator', False, True, {'lab_operator': True, 'lab_manager': True}, 5)
        self.assertEqual(ctx.exception.reason, 'implied_role')
        # 只撤销自己、没有更高角色，允许
        self.assertTrue(p3_rules.ensure_role_change_allowed(
            'lab_user', False, True, {'lab_operator': False, 'lab_manager': False}, 5))

    def test_grant_always_allowed(self):
        for role in p3_rules.ROLE_ORDER:
            self.assertTrue(p3_rules.ensure_role_change_allowed(
                role, True, False, {}, 0))


class TestMappingOrder(unittest.TestCase):

    def test_priority_then_id(self):
        rows = [
            {'id': 5, 'priority': 20},
            {'id': 3, 'priority': 20},
            {'id': 9, 'priority': 5},
            {'id': 1, 'priority': 'bad'},
        ]
        ordered = [row['id'] for row in p3_rules.order_mapping_rows(rows)]
        # priority 坏的按默认 10 处理：5 -> 9；10 -> 1；20 -> 3,5
        self.assertEqual(ordered, [9, 1, 3, 5])

    def test_empty(self):
        self.assertEqual(p3_rules.order_mapping_rows(None), [])


class TestHistoryFilters(unittest.TestCase):

    def test_empty_is_empty(self):
        self.assertEqual(p3_rules.history_filters({}), {})

    def test_operation_type(self):
        self.assertEqual(p3_rules.history_filters({'operation_type': 'ISSUE'}),
                         {'operation_type': 'issue'})
        for bad in ('sale', 'x'):
            with self.assertRaises(p3_rules.RuleError) as ctx:
                p3_rules.history_filters({'operation_type': bad})
            self.assertEqual(ctx.exception.field, 'operation_type')

    def test_dates(self):
        out = p3_rules.history_filters({'date_from': '2026-10-01',
                                        'date_to': '2026-10-02'})
        self.assertEqual(out['date_start'].isoformat(), '2026-10-01T00:00:00')
        self.assertEqual(out['date_end'].isoformat(), '2026-10-03T00:00:00')
        for bad in ('2026/10/01', '2026-13-01', 'yesterday'):
            with self.assertRaises(p3_rules.RuleError) as ctx:
                p3_rules.history_filters({'date_from': bad})
            self.assertEqual(ctx.exception.field, 'date_from')
        with self.assertRaises(p3_rules.RuleError) as ctx:
            p3_rules.history_filters({'date_from': '2026-10-05',
                                      'date_to': '2026-10-01'})
        self.assertEqual(ctx.exception.reason, 'invalid_range')

    def test_id_filters(self):
        out = p3_rules.history_filters({'actor_id': '7', 'borrower_id': 8})
        self.assertEqual((out['actor_id'], out['borrower_id']), (7, 8))
        with self.assertRaises(p3_rules.RuleError):
            p3_rules.history_filters({'actor_id': 'abc'})


class TestLocationGuard(unittest.TestCase):

    def test_non_internal_rejected(self):
        with self.assertRaises(p3_rules.RuleError) as ctx:
            p3_rules.location_update_guard(usage='view', is_root=False,
                                           deactivating=False, new_parent_id=None,
                                           current_id=1)
        self.assertEqual(ctx.exception.reason, 'not_internal')

    def test_cycle_rejected(self):
        with self.assertRaises(p3_rules.RuleError) as ctx:
            p3_rules.location_update_guard(usage='internal', is_root=False,
                                           deactivating=False, new_parent_id=5,
                                           current_id=5)
        self.assertEqual(ctx.exception.reason, 'cycle')
        with self.assertRaises(p3_rules.RuleError) as ctx:
            p3_rules.location_update_guard(usage='internal', is_root=False,
                                           deactivating=False, new_parent_id=6,
                                           current_id=5, parent_is_descendant=True)
        self.assertEqual(ctx.exception.reason, 'cycle')

    def test_parent_usage(self):
        with self.assertRaises(p3_rules.RuleError) as ctx:
            p3_rules.location_update_guard(usage='internal', is_root=False,
                                           deactivating=False, new_parent_id=9,
                                           current_id=5, parent_usage='customer')
        self.assertEqual(ctx.exception.reason, 'invalid_usage')

    def test_deactivate_with_stock_rejected(self):
        with self.assertRaises(p3_rules.RuleError) as ctx:
            p3_rules.location_update_guard(usage='internal', is_root=False,
                                           deactivating=True, new_parent_id=None,
                                           current_id=5, bag_count=2, bag_quantity=10,
                                           quant_quantity=10)
        self.assertEqual(ctx.exception.reason, 'has_stock')
        self.assertEqual(ctx.exception.field, 'location')

    def test_deactivate_empty_allowed(self):
        self.assertTrue(p3_rules.location_update_guard(
            usage='internal', is_root=False, deactivating=True, new_parent_id=None,
            current_id=5))

    def test_root_cannot_deactivate(self):
        with self.assertRaises(p3_rules.RuleError) as ctx:
            p3_rules.location_update_guard(usage='internal', is_root=True,
                                           deactivating=True, new_parent_id=None,
                                           current_id=1)
        self.assertEqual(ctx.exception.reason, 'is_root')


class TestLabelBounds(unittest.TestCase):

    def test_per_object_limits(self):
        self.assertEqual(p3_rules.label_bounds(1, 1), (1, 1))
        self.assertEqual(p3_rules.label_bounds(200, 1), (200, 1))
        self.assertEqual(p3_rules.label_bounds(1, 200), (1, 200))
        for ids in (0, -1, 201):
            with self.assertRaises(p3_rules.RuleError) as ctx:
                p3_rules.label_bounds(ids, 1)
            self.assertEqual(ctx.exception.field, 'ids')
        for copies in (0, 201):
            with self.assertRaises(p3_rules.RuleError) as ctx:
                p3_rules.label_bounds(1, copies)
            self.assertEqual(ctx.exception.field, 'copies')

    def test_total_limit(self):
        """S2-2：ids×copies 必须 ≤ MAX_TOTAL_LABELS（Lead：200）。"""
        self.assertEqual(p3_rules.MAX_TOTAL_LABELS, 200)
        # 10×20 = 200 合法；10×21 / 200×200 必须拒绝
        self.assertEqual(p3_rules.label_bounds(10, 20), (10, 20))
        with self.assertRaises(p3_rules.RuleError) as ctx:
            p3_rules.label_bounds(10, 21)
        self.assertEqual(ctx.exception.reason, 'too_many_total')
        with self.assertRaises(p3_rules.RuleError) as ctx:
            p3_rules.label_bounds(200, 200)
        self.assertEqual(ctx.exception.reason, 'too_many_total')
        # 错误信息要能让用户自己改：包含总数与上限
        self.assertIn('40000', ctx.exception.message)
        self.assertIn('200', ctx.exception.message)


class TestScanRedirect(unittest.TestCase):

    def test_path_validation(self):
        self.assertEqual(p3_rules.validate_redirect_path('/team/scan'), '/team/scan')
        self.assertEqual(p3_rules.validate_redirect_path(' /team/scan?tab=2 '),
                         '/team/scan?tab=2')
        for bad in ('//evil.example', 'https://evil.example', '/a\\b', '/a\x00b',
                    'team/scan', '', None):
            self.assertIsNone(p3_rules.validate_redirect_path(bad))

    def test_candidate(self):
        self.assertEqual(p3_rules.scan_redirect_candidate(None), '/team/scan')
        self.assertEqual(p3_rules.scan_redirect_candidate(''), '/team/scan')
        for off in ('off', 'OFF', '0', 'false', 'no'):
            self.assertIsNone(p3_rules.scan_redirect_candidate(off))
        self.assertEqual(p3_rules.scan_redirect_candidate('/lab/scan2'), '/lab/scan2')
        # 非法值退回默认，而不是开放跳转
        self.assertEqual(p3_rules.scan_redirect_candidate('https://evil.example'),
                         '/team/scan')

    def test_target_requires_available_route(self):
        self.assertIsNone(p3_rules.scan_redirect_target(None, False))
        self.assertEqual(p3_rules.scan_redirect_target(None, True), '/team/scan')
        self.assertIsNone(p3_rules.scan_redirect_target('off', True))


if __name__ == '__main__':
    unittest.main()
