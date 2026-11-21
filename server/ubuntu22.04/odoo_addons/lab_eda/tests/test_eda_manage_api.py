# -*- coding: utf-8 -*-
"""管理页「EDA 密钥」区块的服务端逻辑。

这些端点由**网页端会话**调用（管理员在 /team/lab/settings 操作），
不是插件调用，所以用 ``auth='user'`` + manager 门禁，不走 bearer。

规则：
* 只有库存管理员能发放/吊销/查看全部；
* 发放返回明文**一次**，之后列表里只显示前缀；
* 吊销立即生效。
"""
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged('at_install', '-post_install', 'lab_eda')
class EdaManageApiTest(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Token = cls.env['lab.eda.token']
        cls.Users = cls.env['res.users'].with_context(no_reset_password=True)
        cls.manager = cls.Users.create({
            'name': 'EDA 管理页管理员',
            'login': 'eda_web_manager',
            'email': 'wm@example.test',
            'group_ids': [(6, 0, [cls.env.ref('lab_workflow.group_lab_manager').id])],
        })
        cls.operator = cls.Users.create({
            'name': 'EDA 管理页操作员',
            'login': 'eda_web_operator',
            'email': 'wo@example.test',
            'group_ids': [(6, 0, [cls.env.ref('lab_workflow.group_lab_operator').id])],
        })

    def test_manager_lists_tokens_without_plaintext(self):
        record, plaintext = self.Token.with_user(self.manager).issue(
            user_id=self.operator.id, name='列表测试')
        rows = self.Token.with_user(self.manager).lab_web_list()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['user_name'], self.operator.name)
        self.assertEqual(row['name'], '列表测试')
        self.assertTrue(row['active'])
        # 列表里绝不能出现明文
        self.assertNotIn(plaintext, str(row))
        self.assertNotIn('token_hash', row)

    def test_operator_cannot_list(self):
        with self.assertRaises(AccessError):
            self.Token.with_user(self.operator).lab_web_list()

    def test_issue_via_web_returns_plaintext_once(self):
        record, plaintext = self.Token.with_user(self.manager).issue(
            user_id=self.operator.id, name='网页发放', days=30)
        self.assertTrue(plaintext.startswith('eda_'))
        # 再查一次列表，明文不再出现
        rows = self.Token.with_user(self.manager).lab_web_list()
        self.assertNotIn(plaintext, str(rows))

    def test_revoke_via_web_marks_inactive(self):
        """吊销后**仍然出现在列表里**，只是状态为「已吊销」。

        管理页要能看到历史密钥（谁发的、什么时候吊销的），
        默认 ``search([])`` 会过滤掉 active=False 的记录，那样管理员
        吊销完就再也看不到这条记录了。
        """
        record, _ = self.Token.with_user(self.manager).issue(
            user_id=self.operator.id, name='吊销测试')
        self.Token.with_user(self.manager).browse(record.id).revoke()
        rows = self.Token.with_user(self.manager).lab_web_list()
        self.assertEqual(len(rows), 1, '吊销后的密钥必须仍可见')
        self.assertFalse(rows[0]['active'])

    def test_list_shows_expiry_and_last_used(self):
        record, _ = self.Token.with_user(self.manager).issue(
            user_id=self.operator.id, name='字段测试', days=30)
        rows = self.Token.with_user(self.manager).lab_web_list()
        self.assertTrue(rows[0]['expires_at'])
        self.assertFalse(rows[0]['last_used_at'])      # 还没用过

    def test_zero_days_means_never_expires(self):
        record, _ = self.Token.with_user(self.manager).issue(
            user_id=self.operator.id, name='永久', days=0)
        rows = self.Token.with_user(self.manager).lab_web_list()
        self.assertFalse(rows[0]['expires_at'])
