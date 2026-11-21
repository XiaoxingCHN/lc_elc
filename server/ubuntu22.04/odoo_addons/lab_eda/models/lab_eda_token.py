# -*- coding: utf-8 -*-
"""``lab.eda.token``：发放给 EDA 插件的 API Token。

为什么不用 Odoo 原生 ``res.users.apikeys``
------------------------------------------
原生 Key 的生成权在**每个用户自己**手里（``check_access_make_key`` 只检查
``_is_internal()``），做不到「发放权锁在管理员」。而 EDA 插件需要的是：

* 只有库存管理员能发；
* 每个 token 的权属（绑定哪个用户）清楚可查；
* 离职时管理员能立刻吊销。

所以自建一张表，权限完全由本模块的 ACL + ir.rule 决定。

明文只在 :meth:`issue` 的返回值里出现一次，之后库里只有 sha256 哈希。
"""
import datetime
import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from ..tools import eda_token

_logger = logging.getLogger(__name__)

MANAGER_GROUP = 'lab_workflow.group_lab_manager'


class LabEdaToken(models.Model):
    _name = 'lab.eda.token'
    _description = 'EDA 插件 API Token'
    _order = 'create_date desc, id desc'
    _rec_name = 'name'

    user_id = fields.Many2one(
        'res.users', string='绑定用户', required=True, index=True,
        ondelete='cascade',
        help='出库时 actor_id 就是这个人；吊销即断开该用户的插件访问。')
    name = fields.Char(string='备注', required=True, default='EDA 插件')
    token_hash = fields.Char(
        string='Token 哈希', required=True, index=True, readonly=True, copy=False,
        help='sha256 十六进制；明文只在发放时出现一次，不落库。')
    active = fields.Boolean(string='有效', default=True)
    expires_at = fields.Datetime(
        string='到期时间', help='留空表示永不过期。')
    last_used_at = fields.Datetime(string='最近使用', readonly=True, copy=False)
    token_prefix = fields.Char(
        string='Token 前缀', compute='_compute_token_prefix',
        help='仅用于列表里区分不同 token，不足以还原明文。')

    _sql_constraints = [
        ('token_hash_uniq', 'unique(token_hash)', '该 Token 已存在。'),
    ]

    @api.depends('token_hash')
    def _compute_token_prefix(self):
        for record in self:
            record.token_prefix = (record.token_hash or '')[:8]

    # ------------------------------------------------------------------ 权限
    @api.model
    def _is_manager(self):
        return (self.env.su
                or self.env.user.has_group(MANAGER_GROUP))

    @api.model
    def _require_manager(self, action='发放或吊销 EDA 密钥'):
        if self.env.su:
            return True
        if not self.env.user.has_group(MANAGER_GROUP):
            raise AccessError(_('只有库存管理员可以%s。' % action))
        return True

    # ------------------------------------------------------------------ 发放
    @api.model
    def issue(self, user_id, name='EDA 插件', days=None):
        """发放一个 token。

        :param user_id: 绑定的 Odoo 用户 id
        :param name: 备注
        :param days: 有效天数；``None`` 用默认 365，``0`` 表示永不过期
        :return: ``(record, plaintext)`` —— 明文只在这里出现一次
        """
        self._require_manager('发放 EDA 密钥')
        user = self.env['res.users'].browse(int(user_id or 0)).exists()
        if not user:
            raise UserError(_('绑定的用户不存在。'))
        if not user.active:
            raise UserError(_('不能给已停用的账号发放密钥。'))

        validity = eda_token.DEFAULT_VALIDITY_DAYS if days is None else int(days)
        now = fields.Datetime.now()
        expiry_epoch = eda_token.expiry_from_days(validity, now.timestamp())
        expires_at = (
            datetime.datetime.fromtimestamp(expiry_epoch, tz=datetime.timezone.utc)
            .replace(tzinfo=None)
            if expiry_epoch is not None else False)

        plaintext = eda_token.generate()
        record = self.sudo().create({
            'user_id': user.id,
            'name': (name or 'EDA 插件').strip()[:64],
            'token_hash': eda_token.hash_token(plaintext),
            'active': True,
            'expires_at': expires_at,
        })
        _logger.info('lab.eda.token issued for user=%s by uid=%s',
                     user.login, self.env.uid)
        return record, plaintext

    # ------------------------------------------------------------------ 吊销
    def revoke(self):
        self._require_manager('吊销 EDA 密钥')
        count = len(self)
        self.sudo().write({'active': False})
        _logger.info('lab.eda.token revoked count=%s by uid=%s', count, self.env.uid)
        return count

    # ------------------------------------------------------------ 网页端列表
    @api.model
    def lab_web_list(self):
        """管理页用的列表。**绝不返回明文或哈希**，只给展示需要的字段。"""
        self._require_manager('查看 EDA 密钥')
        return [{
            'id': record.id,
            'user_id': record.user_id.id,
            'user_name': record.user_id.name or '',
            'user_login': record.user_id.login or '',
            'name': record.name or '',
            'active': bool(record.active),
            'expires_at': (fields.Datetime.to_string(record.expires_at)
                           if record.expires_at else False),
            'last_used_at': (fields.Datetime.to_string(record.last_used_at)
                             if record.last_used_at else False),
            'token_prefix': record.token_prefix or '',
        } for record in self.with_context(active_test=False).search(
            [], order='create_date desc, id desc', limit=200)]

    # ------------------------------------------------------------------ 校验
    @api.model
    def _resolve(self, token):
        """按明文 token 找到对应记录；无效/过期/吊销/用户停用一律返回空记录集。

        用 ``sudo`` 是因为这一步发生在认证阶段，调用者还没有可信身份。
        """
        digest = eda_token.hash_token(token)
        if not digest:
            return self.browse()
        record = self.sudo().search([('token_hash', '=', digest)], limit=1)
        if not record:
            return self.browse()
        if not record.user_id.active:
            return self.browse()
        now = fields.Datetime.now()
        expires_epoch = record.expires_at.timestamp() if record.expires_at else None
        if not eda_token.is_valid(record.active, expires_epoch, now.timestamp()):
            return self.browse()
        record.sudo().write({'last_used_at': now})
        return record
