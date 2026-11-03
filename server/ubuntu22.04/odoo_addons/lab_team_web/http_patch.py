# -*- coding: utf-8 -*-
"""P2 安全候选：公网入口 JSON-RPC 错误脱敏（项目范围 gating）。

官方依据：Odoo 19 的 odoo/http.py 中 JsonRPCDispatcher.handle_error 固定把
serialize_exception()（含 debug traceback）放进 error.data；Odoo 未提供针对
JSON-RPC 错误载荷的 hook。这里仅包装 JsonRPCDispatcher._response：

- 仅当请求带有入口 Nginx 覆盖写入的 X-Team-Gateway: lab-team-web 且
  X-Forwarded-Host 等于本项目 management_host 时才脱敏；其它 Host/DB/模块、
  私有维护入口、直连 Odoo 一律走原始逻辑。
- 不修改共享 error 对象：脱敏在副本上完成（见 http_sanitize）。
- 保留 JSON-RPC id/code；安全异常保留类型；未知内部错误用通用消息 + trace_id。
- install 幂等；restore() 可还原；包装保留原调用约定。
"""
import functools
import logging

from .http_sanitize import sanitize_jsonrpc_error

_logger = logging.getLogger(__name__)

GATEWAY_HEADER = 'X-Team-Gateway'
GATEWAY_VALUE = 'lab-team-web'
# 仅公网入口列明的窄 JSON-RPC 端点允许脱敏；其它路径保持原始行为
PUBLIC_RPC_PATHS = frozenset({
    '/web/session/authenticate',
    '/web/session/get_session_info',
    '/web/session/destroy',
    '/team/api/session',
    '/api/team/session',
})
# 公网入口域名（项目常量，可被 management_host 覆盖）；用于无 env 场景（如非法 DB）兜底
DEFAULT_MANAGEMENT_HOST = 'team.l-creation.club'
_MARKER = '_lab_team_web_http_patch'
_ORIGINAL = '_lab_team_web_http_patch_original'


def _management_host(request):
    try:
        param = request.env['ir.config_parameter'].sudo().get_param('lab_team_web.management_host')
        return (param or '').strip().lower()
    except Exception:
        _logger.warning('lab_team_web: 读取 management_host 失败，按非公网请求处理', exc_info=True)
        return ''


def is_public_gateway_request(request):
    if request is None:
        return False
    try:
        headers = request.httprequest.headers
        if headers.get(GATEWAY_HEADER) != GATEWAY_VALUE:
            return False
        path = request.httprequest.path or ''
        if path not in PUBLIC_RPC_PATHS:
            return False
        forwarded = (headers.get('X-Forwarded-Host') or '').split(':')[0].strip().lower()
        expected = _management_host(request) or DEFAULT_MANAGEMENT_HOST
        # 公网入口只允许项目域名（常量）或其配置值；其他 Host 保持原逻辑
        return forwarded == DEFAULT_MANAGEMENT_HOST or forwarded == expected
    except Exception:
        _logger.warning('lab_team_web: 公网 gating 判定异常，按非公网请求处理', exc_info=True)
        return False


def install():
    try:
        from odoo.http import JsonRPCDispatcher
    except Exception:
        _logger.warning('lab_team_web: 无法导入 JsonRPCDispatcher，跳过脱敏安装', exc_info=True)
        return False
    if getattr(JsonRPCDispatcher, _MARKER, False):
        return True
    original = JsonRPCDispatcher._response

    @functools.wraps(original)
    def _response(self, result=None, error=None):
        if error is not None and is_public_gateway_request(getattr(self, 'request', None)):
            error, trace_id = sanitize_jsonrpc_error(error)
            if trace_id:
                _logger.warning('lab_team_web: 公网 JSON-RPC 错误已脱敏 trace_id=%s', trace_id)
        return original(self, result=result, error=error)

    setattr(JsonRPCDispatcher, _ORIGINAL, original)
    setattr(JsonRPCDispatcher, _MARKER, True)
    JsonRPCDispatcher._response = _response
    return True


def restore():
    try:
        from odoo.http import JsonRPCDispatcher
    except Exception:
        return False
    original = getattr(JsonRPCDispatcher, _ORIGINAL, None)
    if original is not None:
        JsonRPCDispatcher._response = original
    for attr in (_MARKER, _ORIGINAL):
        if hasattr(JsonRPCDispatcher, attr):
            delattr(JsonRPCDispatcher, attr)
    return True
