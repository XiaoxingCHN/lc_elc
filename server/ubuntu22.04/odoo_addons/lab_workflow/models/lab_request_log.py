# -*- coding: utf-8 -*-
"""lab.request.log：request_key + 用户 + 公司 唯一 + payload 指纹 的幂等记账行。

一次业务请求只成功记账一次：

* 同一 key 重试且 payload 指纹一致 -> 直接返回保存的结果
* 同一 key 但 payload 不同 -> CONFLICT，拒绝执行
* 数据库唯一约束保证并发重复提交只有一条能成立
"""

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from ..tools import request_keys


class LabRequestLog(models.Model):
    _name = 'lab.request.log'
    _description = '实验室库存请求记账'
    _order = 'id desc'
    _rec_name = 'request_key'

    request_key = fields.Char(string='请求号', required=True, index=True, copy=False)
    method = fields.Char(string='接口', required=True, index=True)
    user_id = fields.Many2one('res.users', string='提交账号', required=True, index=True)
    company_id = fields.Many2one('res.company', string='公司', required=True, index=True)
    payload_json = fields.Json(string='请求内容（规范化后参与指纹）')
    payload_fingerprint = fields.Char(string='内容指纹', required=True, index=True)
    response_json = fields.Json(string='返回内容（重试直接返回）')
    state = fields.Selection([('pending', '进行中'), ('succeeded', '已记账'),
                              ('failed', '失败')],
                             string='状态', default='pending', required=True, index=True)
    error_code = fields.Char(string='错误码')
    error_message = fields.Char(string='错误信息')
    operation_model = fields.Char(string='业务对象')
    operation_id = fields.Integer(string='业务对象 ID')

    # Odoo 19 使用 models.Constraint 声明表约束（旧的 _sql_constraints 已不再生效）。
    # 数据库约束名：lab_request_log_request_key_user_company_method_uniq
    # 同一个 request_key 在同一账号/公司下**按接口**唯一：
    # 同 key 跨 receipt/issue 不会互相顶掉（指纹里也含接口名）。
    _request_key_user_company_method_uniq = models.Constraint(
        'unique(request_key, user_id, company_id, method)',
        '同一账号在同一公司的同一次 request_key 只能记账一次。',
    )

    @api.constrains('payload_fingerprint')
    def _check_fingerprint_format(self):
        for log in self:
            fingerprint = log.payload_fingerprint or ''
            if len(fingerprint) != 64 or not all(char in '0123456789abcdef' for char in fingerprint):
                raise ValidationError(_('请求内容指纹格式非法。'))

    def unlink(self):
        raise UserError(_('请求记账行不可删除：幂等依据必须保留。'))

    PROTECTED_WRITE_FIELDS = ('request_key', 'user_id', 'company_id', 'method',
                              'payload_fingerprint', 'payload_json')

    def write(self, values):
        from .lab_workflow_common import in_internal_service
        if not in_internal_service():
            touched = sorted(set(values or {}) & set(self.PROTECTED_WRITE_FIELDS))
            if touched:
                raise UserError(_('请求记账的字段 %s 只能由服务端记账流程写入。')
                                % '、'.join(touched))
        return super().write(values)

    @api.model_create_multi
    def create(self, vals_list):
        from .lab_workflow_common import in_internal_service
        if not in_internal_service():
            raise AccessError(_('请求记账行只能由服务端记账流程创建。'))
        return super().create(vals_list)

    @api.model
    def _lab_lookup(self, request_key, params, method=None):
        """给页面/控制器查询用：返回 (记录, 是否命中已成功结果)。"""
        domain = [
            ('request_key', '=', request_key),
            ('user_id', '=', self.env.uid),
            ('company_id', '=', self.env.company.id),
        ]
        if method:
            domain.append(('method', '=', method))
        log = self.search(domain, limit=1)
        if not log:
            return log, False
        expected = self.env['lab.workflow.common'].lab_fingerprint(params or {},
                                                                   method=log.method)
        if log.payload_fingerprint != expected:
            raise ValidationError(_('同一 request_key 被用于不同内容（或不同接口）的请求，已拒绝。'))
        return log, log.state == 'succeeded'
