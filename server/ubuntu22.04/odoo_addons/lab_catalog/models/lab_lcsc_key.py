# -*- coding: utf-8 -*-
"""``lab.lcsc.key``：立创开放平台密钥池。

用户的原话：「现在使用一个很容易就限流了我想多搞几个号做号码池」。

开放平台的日额度按 **appId** 算，所以多套密钥轮着用能把额度叠加起来。
以前密钥只能从环境变量 ``LCSC_OPENAPI_*`` 读一套，换号得改 systemd 再重启。

安全
----
* ``secret_key`` 用 ``groups='base.group_system'`` 限制——只有系统管理员能读；
* 日志、异常、列表视图都不打印密钥内容；
* 密钥只存在数据库，不进 Git。
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)

MANAGER_GROUP = 'lab_catalog.group_lab_catalog_manager'


class LabLcscKey(models.Model):
    _name = 'lab.lcsc.key'
    _description = '立创开放平台密钥'
    _order = 'sequence, id'

    name = fields.Char(string='备注', required=True, default='立创开放平台')
    app_id = fields.Char(string='AppId', required=True, help='18 位数字，控制台「应用」页可见')
    access_key = fields.Char(string='AccessKey', required=True)
    secret_key = fields.Char(
        string='SecretKey', required=True,
        groups='base.group_system',
        help='只有系统管理员能读。不会出现在列表、日志或错误信息里。')
    active = fields.Boolean(string='启用', default=True)
    sequence = fields.Integer(string='排序', default=10)

    # 使用情况（只读，由调用方回写）
    last_used_at = fields.Datetime(string='最近使用', readonly=True, copy=False)
    rate_limited_at = fields.Datetime(
        string='最近超限', readonly=True, copy=False,
        help='返回 429 时记录；换天后自动视为可用。')
    error_count = fields.Integer(string='错误次数', default=0, readonly=True, copy=False)

    _sql_constraints = [
        ('app_access_uniq', 'unique(app_id, access_key)', '这套密钥已经登记过了。'),
    ]

    # ------------------------------------------------------------------ 权限
    @api.model
    def _is_manager(self):
        return (self.env.su
                or self.env.user.has_group(MANAGER_GROUP)
                or self.env.user.has_group('base.group_system'))

    @api.model
    def _require_manager(self, action='维护立创密钥'):
        if self.env.su:
            return True
        if not (self.env.user.has_group(MANAGER_GROUP)
                or self.env.user.has_group('base.group_system')):
            raise AccessError(_('只有器件库管理员可以%s。' % action))
        return True

    # ------------------------------------------------------------------ 解析
    @api.model
    def _usable(self):
        """当前可用的密钥（启用中、且今天没超限）。"""
        today = fields.Date.context_today(self)
        records = self.search([('active', '=', True)])
        usable = records.filtered(
            lambda rec: not rec.rate_limited_at
            or rec.rate_limited_at.date() < today)
        return usable

    @api.model
    def _pool_entries(self):
        """给 ``lcsc_key_pool.KeyPool`` 用的 dict 列表。"""
        return [{
            'id': rec.id,
            'app_id': rec.app_id,
            'access_key': rec.access_key,
            'secret_key': rec.secret_key,
        } for rec in self._usable()]

    @api.model
    def mark_rate_limited(self, key_id):
        record = self.browse(int(key_id or 0)).exists()
        if record:
            record.sudo().write({
                'rate_limited_at': fields.Datetime.now(),
                'error_count': record.error_count + 1,
            })
        return True

    @api.model
    def mark_used(self, key_id):
        record = self.browse(int(key_id or 0)).exists()
        if record:
            record.sudo().write({'last_used_at': fields.Datetime.now()})
        return True

    @api.model
    def reset_limits(self):
        """管理员手动重置今日超限标记。"""
        self._require_manager('重置密钥超限标记')
        self.sudo().search([('rate_limited_at', '!=', False)]).write(
            {'rate_limited_at': False})
        return True

    # ------------------------------------------------------------ 网页端列表
    @api.model
    def lab_web_list(self):
        """管理页列表。**绝不返回 secret_key**。"""
        self._require_manager('查看立创密钥')
        return [{
            'id': rec.id,
            'name': rec.name,
            'app_id': rec.app_id,
            'active': bool(rec.active),
            'sequence': rec.sequence,
            'last_used_at': (fields.Datetime.to_string(rec.last_used_at)
                             if rec.last_used_at else False),
            'rate_limited_at': (fields.Datetime.to_string(rec.rate_limited_at)
                                if rec.rate_limited_at else False),
            'error_count': rec.error_count,
        } for rec in self.search([], order='sequence, id', limit=200)]

    @api.model
    def lab_web_create(self, name, app_id, access_key, secret_key):
        """管理页新增一套密钥。"""
        self._require_manager('新增立创密钥')
        for label, value in (('备注', name), ('AppId', app_id),
                             ('AccessKey', access_key), ('SecretKey', secret_key)):
            if not str(value or '').strip():
                raise UserError(_('%s不能为空。' % label))
        record = self.sudo().create({
            'name': str(name).strip()[:64],
            'app_id': str(app_id).strip(),
            'access_key': str(access_key).strip(),
            'secret_key': str(secret_key).strip(),
        })
        _logger.info('lab.lcsc.key created id=%s by uid=%s', record.id, self.env.uid)
        return {'id': record.id, 'name': record.name, 'app_id': record.app_id}

    @api.model
    def lab_web_toggle(self, key_id, active):
        self._require_manager('启用或停用立创密钥')
        record = self.browse(int(key_id or 0)).exists()
        if not record:
            raise UserError(_('密钥不存在。'))
        record.sudo().write({'active': bool(active)})
        return {'id': record.id, 'active': bool(active)}

    @api.model
    def lab_web_remove(self, key_id):
        self._require_manager('删除立创密钥')
        record = self.browse(int(key_id or 0)).exists()
        if not record:
            return {'removed': 0}
        record.sudo().unlink()
        return {'removed': 1}
