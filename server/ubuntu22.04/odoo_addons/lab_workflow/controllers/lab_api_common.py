# -*- coding: utf-8 -*-
"""控制器公用部分：统一信封、鉴权、错误关联 ID。

契约（lc_elc/docs/business_api_contract.json）：
``transport = Odoo 19 type=jsonrpc, POST, auth=user, 与 /web/session/authenticate 同一 cookie``。

**重要**：Odoo 19 的 ``JsonRPCDispatcher`` 会自动把返回值包成
``{"jsonrpc":"2.0","id":X,"result": <返回值>}``，所以控制器**必须直接 return
普通 dict** ``{"ok":...,"data":...,"error":...}``；
如果自己再构造 jsonrpc 外层或返回 HTTP Response，就会重复套壳/类型错误。
"""

import logging
import uuid

from odoo import http
from odoo.http import request

from ..models.lab_workflow_common import (
    CODE_FORBIDDEN, CODE_INTERNAL, CODE_UNAUTHORIZED, LabApiError,
)

_logger = logging.getLogger(__name__)

# 所有 lab 接口都要求的最小角色
LAB_GROUP_HIERARCHY = (
    'lab_workflow.group_lab_manager',
    'lab_workflow.group_lab_operator',
    'lab_workflow.group_lab_user',
)


def is_anonymous():
    """未登录 / 公共用户 => 匿名（用 Odoo 自身的判定，不硬编码 uid）。"""
    user = request.env.user
    if not request.env.uid or not user:
        return True
    try:
        return bool(user._is_public())
    except AttributeError:  # 兼容老版本
        public = request.env.ref('base.public_user', raise_if_not_found=False)
        return bool(public and user.id == public.id)


def guard_authenticated():
    """服务端只认已认证会话的 uid，客户端传什么都不影响操作人。"""
    if is_anonymous():
        raise LabApiError(CODE_UNAUTHORIZED,
                          '未登录或会话已过期，请重新登录后再操作',
                          {'auth': 'anonymous'})


def require_lab_access():
    """有账号但没有 lab 角色也不能访问任何 lab 接口（读接口同样受限）。"""
    guard_authenticated()
    for xmlid in LAB_GROUP_HIERARCHY:
        if request.env.user.has_group(xmlid):
            return True
    raise LabApiError(CODE_FORBIDDEN,
                      '当前账号没有实验室库存权限，请联系库存管理员加入'
                      '「实验室库存 / 操作员」组',
                      {'group': 'lab_workflow.group_lab_user'})


def require_group(xmlid, message):
    guard_authenticated()
    if not request.env.user.has_group(xmlid):
        raise LabApiError(CODE_FORBIDDEN, message, {'group': xmlid})


def envelope(handler, require_lab=True):
    """把返回 data 的函数包装成契约信封（异常 -> 中文提示 + 关联 ID）。"""
    def wrapper(*args, **kwargs):
        try:
            if require_lab:
                require_lab_access()
        except LabApiError as error:
            return request.env['lab.workflow.common'].lab_error(error)
        try:
            data = handler(*args, **kwargs)
        except LabApiError as error:
            if error.code != CODE_INTERNAL:
                _logger.info('lab_workflow API 业务失败：%s', error.message)
            else:
                _logger.error('lab_workflow API 内部失败[%s]：%s',
                              error.fields.get('error_id'), error.message)
            return request.env['lab.workflow.common'].lab_error(error)
        except Exception:  # noqa: BLE001 - 对外只给关联 ID，细节进日志
            error_id = uuid.uuid4().hex[:12]
            _logger.exception('lab_workflow API 未捕获异常 [error_id=%s]', error_id)
            request.env.cr.rollback()
            return request.env['lab.workflow.common'].lab_error(LabApiError(
                CODE_INTERNAL,
                '服务器处理失败，本次操作已全部回滚。请把「错误编号 %s」提供给管理员，'
                '日志里有完整堆栈。' % error_id,
                {'error_id': error_id}))
        return request.env['lab.workflow.common'].lab_ok(data)

    wrapper.__name__ = getattr(handler, '__name__', 'lab_api_endpoint')
    wrapper.__doc__ = handler.__doc__
    return wrapper


def params():
    """取出 jsonrpc params（Odoo 已把 params 展开到 request.params）。"""
    data = request.params or {}
    if not isinstance(data, dict):
        raise LabApiError.validation('请求参数必须是对象（按名传参）', {'params': 'invalid'})
    return data
