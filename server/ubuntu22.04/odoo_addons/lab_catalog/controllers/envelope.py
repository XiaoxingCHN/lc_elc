# -*- coding: utf-8 -*-
"""统一响应信封与错误码（root 契约 business_api_contract.json v1.0）。

成功： {"ok": true,  "data": {...}, "error": null}
失败： {"ok": false, "data": null,  "error": {"code": "...", "message": "中文可操作信息", "fields": {}}}

root 复核后的两点硬化
--------------------
1. **savepoint 包住整个处理函数**：bind / create_material 这类会写库的接口一旦中途失败，
   整体回滚，不会留下"写了一半"的数据；异常在 savepoint **之外**捕获，才能既回滚又回响应。
2. **内部异常不把原始 SQL / 路径 / 异常文本丢给前端**：只记日志（带关联编号），
   前端只拿到简洁中文与编号，便于排查又不泄露内部细节。
"""
import functools
import logging
import uuid

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import request

_logger = logging.getLogger(__name__)

VALIDATION_ERROR = 'VALIDATION_ERROR'
NOT_FOUND = 'NOT_FOUND'
FORBIDDEN = 'FORBIDDEN'
CONFLICT = 'CONFLICT'
INTERNAL_ERROR = 'INTERNAL_ERROR'
# 同一 C 编号下有多个本地档案且调用方未指定 SN -> 明确歧义，绝不随机取 first
AMBIGUOUS_MATERIAL = 'AMBIGUOUS_MATERIAL'


class LabApiError(Exception):
    """带业务错误码的异常，控制器负责转成 error 信封。"""

    def __init__(self, code, message, fields=None, http_status=200):
        super().__init__(message)
        self.code = code
        self.message = message
        self.fields = fields or {}
        self.http_status = http_status


def ok(data):
    return {'ok': True, 'data': data, 'error': None}


def fail(code, message, fields=None):
    return {'ok': False, 'data': None,
            'error': {'code': code, 'message': message, 'fields': fields or {}}}


def _has_catalog_access(user):
    """只认**显式的 lab 角色**。

    刻意**不**把 base.group_user 当成隐含授权：组继承无法按人单独收回，
    所有内部用户自动可用等于没有权限控制。管理员通过 bootstrap 初始授权，
    普通账号由管理员显式分配 lab_catalog.group_lab_catalog_user。
    """
    return (user.has_group('lab_catalog.group_lab_catalog_user')
            or user.has_group('lab_catalog.group_lab_catalog_manager')
            or user.has_group('base.group_system'))


def api_route(func):
    """ACL 前置校验 + savepoint 事务 + 统一错误信封。"""

    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        # 参数投递方式随 Odoo 版本/分发路径不同，这里按优先级全部兼容：
        #   1) kwargs['params']        —— 显式传 params
        #   2) args[0] 是 dict         —— 位置参数传 dict
        #   3) kwargs 本身             —— jsonrpc 的 params 被展开成关键字参数
        #   4) request.params          —— Odoo 把 jsonrpc params 放在请求对象上
        # 实测（真实 HTTP）：只判断 1)+2) 会让所有端点拿到空参数，
        # 表现为"用了默认值"且必填字段报空，属于必须修的真实缺陷。
        params = kwargs.get('params')
        if params is None:
            if args and isinstance(args[0], dict):
                params = args[0]
            elif kwargs:
                params = dict(kwargs)
        if not params:
            rq = getattr(request, 'params', None)
            if isinstance(rq, dict) and rq:
                params = rq
        if not isinstance(params, dict):
            params = {}

        user = request.env.user
        if user._is_public():
            return fail(FORBIDDEN, '请先登录后再使用器件库。')
        if not _has_catalog_access(user):
            return fail(FORBIDDEN, '当前账号未被授予器件库访问权限。')

        ref = uuid.uuid4().hex[:8]
        try:
            # 整个处理放在 savepoint 内：任何异常都整体回滚，不留半成品
            with request.env.cr.savepoint():
                data = func(self, params)
            return ok(data if data is not None else {})
        except LabApiError as exc:
            return fail(exc.code, exc.message, exc.fields)
        except AccessError as exc:
            _logger.info('lab_catalog ACL denied ref=%s: %s', ref, exc)
            return fail(FORBIDDEN, '你没有权限执行该操作。')
        except ValidationError as exc:
            # 绑定冲突是明确的业务冲突（一个 SN 不能跨两张卡片），
            # 不能混在普通校验错误里，也不能被当成内部错误。
            from ..models.lab_catalog_binding import LabBindingConflict
            if isinstance(exc, LabBindingConflict):
                return fail(CONFLICT, str(exc))
            return fail(VALIDATION_ERROR, str(exc))
        except UserError as exc:
            return fail(VALIDATION_ERROR, str(exc))
        except Exception as exc:  # 内部错误：只记日志，不回显原始文本
            _logger.exception('lab_catalog internal error ref=%s handler=%s',
                              ref, getattr(func, '__name__', '?'))
            return fail(INTERNAL_ERROR,
                        '服务器内部错误，请把错误编号 %s 提供给管理员。' % ref,
                        {'ref': ref})

    # 必须返回包装后的函数：漏掉这一行会让 @http.route 收到 None，
    # 安装时报 "AttributeError: 'NoneType' object has no attribute '__module__'"。
    return wrapper


def as_int(value, field, default=None, minimum=None, maximum=None):
    if value in (None, '', False):
        return default
    try:
        out = int(value)
    except (TypeError, ValueError):
        raise LabApiError(VALIDATION_ERROR, '「%s」必须是整数。' % field,
                          {field: 'not_an_integer'})
    if minimum is not None and out < minimum:
        raise LabApiError(VALIDATION_ERROR, '「%s」不能小于 %s。' % (field, minimum))
    if maximum is not None and out > maximum:
        raise LabApiError(VALIDATION_ERROR, '「%s」不能大于 %s。' % (field, maximum))
    return out


def require(condition, message, fields=None):
    if not condition:
        raise LabApiError(VALIDATION_ERROR, message, fields)
