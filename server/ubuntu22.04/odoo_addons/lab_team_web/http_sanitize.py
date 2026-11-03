# -*- coding: utf-8 -*-
"""JSON-RPC 错误载荷脱敏（纯函数，无 Odoo 依赖，可单测）。

按白名单重建公网错误载荷，而不是"复制后删 3 个键"：未知字段/嵌套字段一律不进入输出。
- 安全异常：保留原始全限定名（如 odoo.exceptions.AccessDenied）与安全业务消息（经模式过滤）；
- 未知内部异常：data 仅 {name: ServerError, message: 通用消息 + trace_id}；
- 顶层仅重建 code/message/data，保留 JSON-RPC 兼容字段。
"""
import copy
import re
import uuid

# 已知安全异常的全限定名（按原始协议标识识别，不用 basename）
SAFE_EXCEPTION_NAMES = frozenset({
    'odoo.exceptions.AccessDenied',
    'odoo.exceptions.AccessError',
    'odoo.exceptions.UserError',
    'odoo.exceptions.ValidationError',
    'odoo.exceptions.MissingError',
    'odoo.exceptions.NotFound',
    'odoo.http.SessionExpiredException',
    'odoo.http.NotFound',
})

# 安全业务消息允许的字符/结构之外的内部信息特征（命中则转通用）
_UNSAFE_MESSAGE = re.compile(
    r'(?:/home/|/mnt/|/opt/|Traceback|File "|psycopg|SQLSTATE|SELECT\s|INSERT\s|UPDATE\s|DELETE\s|'
    r'0x[0-9a-fA-F]{6,}|at line \d+|odoo\.addons\.)'
)

GENERIC_MESSAGE = '服务器内部错误，请稍后重试'
GENERIC_TOP_MESSAGE = 'Odoo Server Error'
TRACE_PREFIX = '参考编号'


def _safe_message(message):
    if not isinstance(message, str) or not message.strip():
        return None
    if len(message) > 500:
        return None
    if _UNSAFE_MESSAGE.search(message):
        return None
    return message


def _build_data(exc_name, original_data, trace_id):
    data = {}
    if exc_name in SAFE_EXCEPTION_NAMES:
        data['name'] = exc_name
        message = _safe_message(original_data.get('message'))
        if message:
            data['message'] = message
        else:
            data['message'] = '%s（%s %s）' % (GENERIC_MESSAGE, TRACE_PREFIX, trace_id)
    else:
        data['name'] = 'ServerError'
        data['message'] = '%s（%s %s）' % (GENERIC_MESSAGE, TRACE_PREFIX, trace_id)
    data['trace_id'] = trace_id
    return data


def sanitize_jsonrpc_error(error, trace_id=None):
    if not isinstance(error, dict):
        return error, None
    trace_id = trace_id or uuid.uuid4().hex[:12]
    original_data = error.get('data') if isinstance(error.get('data'), dict) else {}
    exc_name = original_data.get('name') if isinstance(original_data.get('name'), str) else ''
    data = _build_data(exc_name, original_data, trace_id)
    top_message = error.get('message')
    if exc_name not in SAFE_EXCEPTION_NAMES:
        top_message = GENERIC_TOP_MESSAGE
    elif not _safe_message(top_message):
        top_message = GENERIC_TOP_MESSAGE
    return {'code': error.get('code', 0), 'message': top_message, 'data': data}, trace_id
