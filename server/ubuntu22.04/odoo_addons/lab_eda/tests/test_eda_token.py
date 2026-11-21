# -*- coding: utf-8 -*-
"""``lab.eda.token``：EDA 插件的 API Token。

规则来自 ``maintenance/tasks/2026-11-21-eda-api-token-design.md`` §3：

* Token 绑定到**具体用户**；出库时 ``env.uid`` 就是那个人（``actor_id`` 不会变成管理员）。
* **只存哈希**，明文只在发放时出现一次。
* 发放/吊销权限**只给库存管理员**（``lab_workflow.group_lab_manager``）。
* 普通用户只能看到自己的 token，不能创建、不能吊销。
* 过期或吊销后立即失效。
"""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged('at_install', '-post_install', 'lab_eda')
class EdaTokenTest(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Token = cls.env['lab.eda.token']
        cls.Users = cls.env['res.users'].with_context(no_reset_password=True)
        cls.manager_group = cls.env.ref('lab_workflow.group_lab_manager')
        cls.operator_group = cls.env.ref('lab_workflow.group_lab_operator')

        cls.manager = cls.Users.create({
            'name': 'EDA 库存管理员',
            'login': 'eda_manager',
            'email': 'eda_manager@example.test',
            'group_ids': [(6, 0, [cls.manager_group.id])],
        })
        cls.operator = cls.Users.create({
            'name': 'EDA 操作员',
            'login': 'eda_operator',
            'email': 'eda_operator@example.test',
            'group_ids': [(6, 0, [cls.operator_group.id])],
        })

    # ------------------------------------------------------------------ helpers
    def _issue(self, user=None, days=365, name='EDA 插件'):
        """以管理员身份发放一个 token，返回 (记录, 明文)。"""
        return self.Token.with_user(self.manager).issue(
            user_id=(user or self.operator).id, name=name, days=days)

    # ------------------------------------------------------------------ issue
    def test_issue_returns_plaintext_once_and_stores_only_hash(self):
        record, plaintext = self._issue()

        self.assertTrue(plaintext)
        self.assertTrue(plaintext.startswith('eda_'), plaintext[:8])
        # 明文绝不落库
        self.assertNotIn(plaintext, record.token_hash)
        self.assertEqual(len(record.token_hash), 64)          # sha256 hex
        self.assertTrue(record.active)
        self.assertEqual(record.user_id, self.operator)

    def test_issue_records_who_issued_it(self):
        record, _ = self._issue()
        self.assertEqual(record.create_uid, self.manager)

    def test_operator_cannot_issue(self):
        with self.assertRaises(AccessError):
            self.Token.with_user(self.operator).issue(
                user_id=self.operator.id, name='自批', days=30)

    def test_default_expiry_is_one_year(self):
        record, _ = self._issue()
        expected = fields.Datetime.now() + timedelta(days=365)
        delta = abs((record.expires_at - expected).total_seconds())
        self.assertLess(delta, 120, 'default expiry should be ~1 year')

    def test_manager_can_issue_for_another_user(self):
        record, _ = self._issue(user=self.manager)
        self.assertEqual(record.user_id, self.manager)

    # ------------------------------------------------------------------ resolve
    def test_resolve_returns_the_bound_user(self):
        _record, plaintext = self._issue()
        resolved = self.Token.sudo()._resolve(plaintext)
        self.assertTrue(resolved)
        self.assertEqual(resolved.user_id, self.operator)

    def test_resolve_rejects_unknown_token(self):
        self.assertFalse(self.Token.sudo()._resolve('eda_not-a-real-token'))

    def test_resolve_rejects_empty(self):
        self.assertFalse(self.Token.sudo()._resolve(''))
        self.assertFalse(self.Token.sudo()._resolve(None))

    def test_revoked_token_stops_resolving(self):
        record, plaintext = self._issue()
        record.with_user(self.manager).revoke()
        self.assertFalse(self.Token.sudo()._resolve(plaintext))

    def test_expired_token_stops_resolving(self):
        record, plaintext = self._issue(days=1)
        record.sudo().write({'expires_at': fields.Datetime.now() - timedelta(days=1)})
        self.assertFalse(self.Token.sudo()._resolve(plaintext))

    def test_resolve_touches_last_used_at(self):
        record, plaintext = self._issue()
        self.assertFalse(record.last_used_at)
        self.Token.sudo()._resolve(plaintext)
        record.invalidate_recordset()
        self.assertTrue(record.last_used_at)

    def test_token_of_deactivated_user_stops_resolving(self):
        record, plaintext = self._issue()
        self.operator.active = False
        self.assertFalse(self.Token.sudo()._resolve(plaintext))

    # ------------------------------------------------------------------ acl
    def test_operator_sees_only_own_tokens(self):
        _mine, _ = self._issue(user=self.operator)
        self._issue(user=self.manager, name='管理员的')

        visible = self.Token.with_user(self.operator).search([])
        self.assertEqual(len(visible), 1)
        self.assertEqual(visible.user_id, self.operator)

    def test_operator_cannot_revoke(self):
        record, _ = self._issue()
        with self.assertRaises(AccessError):
            record.with_user(self.operator).revoke()

    def test_manager_sees_all_tokens(self):
        self._issue(user=self.operator)
        self._issue(user=self.manager, name='管理员的')
        self.assertEqual(len(self.Token.with_user(self.manager).search([])), 2)
