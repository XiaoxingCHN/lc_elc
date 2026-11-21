# -*- coding: utf-8 -*-
"""``/lab/api/eda/*`` 端点的认证与转发。

规则（设计文档 §3.5 / §4）：

* 只认 ``Authorization: bearer <token>``；没有 Cookie 会话这回事。
* Token 无效 / 过期 / 吊销 / 用户停用 → 统一 401，**不泄露**是哪一种。
* 认证通过后 ``env.uid`` 就是 token 绑定的用户 —— 出库时 ``actor_id`` 天然正确。
* 业务逻辑一律转发到既有模型方法，不在这里重写。
"""
import functools
import logging
import re

from odoo import http
from odoo.exceptions import AccessError
from odoo.http import request

from odoo.addons.lab_catalog.controllers.envelope import (
    VALIDATION_ERROR, as_int, require)

_logger = logging.getLogger(__name__)

API = '/lab/api/eda'
POST = ['POST']

MISSING_TOKEN = 'MISSING_TOKEN'
INVALID_TOKEN = 'INVALID_TOKEN'


def _bearer_token():
    header = request.httprequest.headers.get('Authorization', '')
    if not header or not header.lower().startswith('bearer '):
        return ''
    return header[7:].strip()


def _auth_error(code, message):
    return {
        'ok': False,
        'data': None,
        'error': {'code': code, 'message': message, 'fields': {}},
    }


def eda_endpoint(handler):
    """savepoint + 统一信封 + 业务错误映射。

    不用 ``lab_catalog`` 的 ``api_route``：那个装饰器会做器件库 ACL 校验
    （认 ``lab_catalog`` 组），而 EDA 的权限已经由 token 决定，再叠一层会
    把合法用户挡在外面。
    """
    @functools.wraps(handler)
    def wrapper(self, params):
        try:
            with request.env.cr.savepoint():
                data = handler(self, params)
            return {'ok': True, 'data': data if data is not None else {}, 'error': None}
        except Exception as error:          # noqa: BLE001
            mapped = _map_business_error(error)
            if mapped is None:
                raise
            return {'ok': False, 'data': None, 'error': mapped}

    return wrapper


def _map_business_error(error):
    """把 ``lab_workflow`` 的 ``LabApiError`` 转成错误信封。

    两个模块各有一个**同名不同类**的 ``LabApiError``；``lab_catalog`` 的
    ``api_route`` 只捕获它自己那个。不在这里转换的话，业务错误（比如「没有
    代领权限」）会掉进兜底的 ``except Exception``，用户看到「服务器内部错误」
    而不是可操作的中文提示。

    返回 ``None`` 表示这不是业务错误，交给外层兜底。
    """
    code = getattr(error, 'code', None)
    if not code:
        return None
    return {
        'code': code,
        'message': getattr(error, 'message', None) or str(error),
        'fields': getattr(error, 'fields', None) or {},
    }


def eda_auth(handler):
    """把 ``Authorization: bearer`` 换成 ``env.uid``，再执行 handler。

    错误信封与既有接口一致（``ok/data/error``），让插件能用同一套解析逻辑。
    """
    @functools.wraps(handler)
    def wrapper(self, *args, **kwargs):
        token = _bearer_token()
        if not token:
            return _auth_error(MISSING_TOKEN, '请在插件里填写 EDA 密钥。')
        record = request.env['lab.eda.token'].sudo()._resolve(token)
        if not record:
            return _auth_error(INVALID_TOKEN, 'EDA 密钥无效、已过期或已吊销。')
        request.update_env(user=record.user_id.id)
        try:
            return handler(self, *args, **kwargs)
        except Exception as error:          # noqa: BLE001
            # 业务错误（两个模块各有一个同名不同类的 LabApiError）要原样
            # 转成信封；其余交给 Odoo 的通用错误处理，不吞异常。
            mapped = _map_business_error(error)
            if mapped is None:
                raise
            request.env.cr.rollback()
            return {'ok': False, 'data': None, 'error': mapped}

    return wrapper


class LabEdaManageApi(http.Controller):
    """管理页「EDA 密钥」区块。

    走**网页端会话**（``auth='user'``），不是 bearer —— 这是管理员在
    ``/team/lab/settings`` 里操作，浏览器自带 Cookie。
    """

    @http.route(API + '/manage/tokens', type='jsonrpc', auth='user',
                methods=POST, csrf=False)
    def manage_tokens(self, **kwargs):
        return _manage(lambda params: {
            'tokens': request.env['lab.eda.token'].lab_web_list(),
        }, kwargs)

    @http.route(API + '/manage/issue', type='jsonrpc', auth='user',
                methods=POST, csrf=False)
    def manage_issue(self, **kwargs):
        def run(params):
            user_id = params.get('user_id')
            require(user_id, '请选择要发放给谁。', {'user_id': 'required'})
            days = params.get('days')
            record, plaintext = request.env['lab.eda.token'].issue(
                user_id=user_id,
                name=params.get('name') or 'EDA 插件',
                days=None if days in (None, '') else int(days),
            )
            return {
                'id': record.id,
                'user_id': record.user_id.id,
                'user_name': record.user_id.name or '',
                'token': plaintext,          # 只在这里出现一次
            }
        return _manage(run, kwargs)

    @http.route(API + '/manage/revoke', type='jsonrpc', auth='user',
                methods=POST, csrf=False)
    def manage_revoke(self, **kwargs):
        def run(params):
            token_id = params.get('id')
            require(token_id, '缺少要吊销的密钥。', {'id': 'required'})
            record = request.env['lab.eda.token'].browse(int(token_id)).exists()
            if not record:
                return {'revoked': 0}
            return {'revoked': record.revoke()}
        return _manage(run, kwargs)


def _manage(handler, kwargs):
    """管理页端点的统一信封：业务错误转中文，其余原样上抛。"""
    params = _params(kwargs)
    try:
        with request.env.cr.savepoint():
            data = handler(params)
        return {'ok': True, 'data': data, 'error': None}
    except AccessError as error:
        return {'ok': False, 'data': None,
                'error': {'code': 'FORBIDDEN', 'message': str(error), 'fields': {}}}
    except Exception as error:          # noqa: BLE001
        mapped = _map_business_error(error)
        if mapped is None:
            raise
        return {'ok': False, 'data': None, 'error': mapped}


class LabEdaApi(http.Controller):

    # ------------------------------------------------------------------ 身份
    @http.route(API + '/bootstrap', type='jsonrpc', auth='none',
                methods=POST, csrf=False, save_session=False)
    @eda_auth
    def eda_bootstrap(self, **kwargs):
        """只返回插件需要的：我能不能出库、我是谁。

        与网页端 ``/inventory/bootstrap`` 的区别：**不返回全部领用人**。
        普通操作员本来就只能领自己；管理员需要选人时单独调 ``/borrowers``。
        """
        @eda_endpoint
        def handler(self_, params):
            user = request.env.user
            common = request.env['lab.workflow.common']
            return {
                'permissions': {
                    'can_issue': user.has_group('lab_workflow.group_lab_operator'),
                    'can_issue_for_others': common.lab_can_issue_for_others(),
                    'is_manager': user.has_group('lab_workflow.group_lab_manager'),
                },
                'user': {'id': user.id, 'name': user.name, 'login': user.login},
                'inventory_revision': common.lab_inventory_revision(),
            }
        return handler(self, _params(kwargs))

    @http.route(API + '/borrowers', type='jsonrpc', auth='none',
                methods=POST, csrf=False, save_session=False)
    @eda_auth
    def eda_borrowers(self, **kwargs):
        """可选领用人。普通操作员只拿到自己；管理员拿到全公司有效账号。"""
        @eda_endpoint
        def handler(self_, params):
            borrowers = request.env['lab.workflow.common'].lab_authorized_borrowers()
            return {
                'borrowers': [{
                    'id': user.id,
                    'name': user.name,
                    'login': user.login,
                    'is_self': user.id == request.env.uid,
                } for user in borrowers],
            }
        return handler(self, _params(kwargs))

    # ------------------------------------------------------------------ 器件
    @http.route(API + '/catalog/search', type='jsonrpc', auth='none',
                methods=POST, csrf=False, save_session=False)
    @eda_auth
    def eda_catalog_search(self, **kwargs):
        @eda_endpoint
        def handler(self_, params):
            items, next_cursor, total = request.env['lab.catalog.item'].search_unified(
                query=params.get('query') or '',
                category_id=params.get('category_id'),
                brands=_as_list(params.get('brands')),
                packages=_as_list(params.get('packages')),
                parameters=_clean_parameter_filters(params.get('parameters')),
                stock_only=bool(params.get('stock_only')),
                cursor=params.get('cursor'),
                limit=as_int(params.get('limit'), 'limit', default=50,
                             minimum=1, maximum=200),
            )
            return {'items': items, 'next_cursor': next_cursor, 'total': total}
        return handler(self, _params(kwargs))

    @http.route(API + '/catalog/detail', type='jsonrpc', auth='none',
                methods=POST, csrf=False, save_session=False)
    @eda_auth
    def eda_catalog_detail(self, **kwargs):
        @eda_endpoint
        def handler(self_, params):
            item_key = (params.get('item_key') or '').strip()
            require(item_key, 'item_key 不能为空。', {'item_key': 'required'})
            data = request.env['lab.catalog.item'].detail(item_key)
            if not data:
                raise LabApiError('NOT_FOUND', '找不到器件「%s」。' % item_key,
                                  {'item_key': 'not_found'})
            return data
        return handler(self, _params(kwargs))

    @http.route(API + '/catalog/categories', type='jsonrpc', auth='none',
                methods=POST, csrf=False, save_session=False)
    @eda_auth
    def eda_catalog_categories(self, **kwargs):
        @eda_endpoint
        def handler(self_, params):
            cats = request.env['lab.catalog.category'].search(
                [], order='level, sort, catalog_id', limit=5000)
            return {'categories': [{
                'id': cat.id,
                'catalog_id': cat.catalog_id,
                'name': cat.name,
                'parent_id': cat.parent_id.id or None,
                'level': cat.level,
                'has_children': cat.has_children,
            } for cat in cats]}
        return handler(self, _params(kwargs))

    @http.route(API + '/catalog/equivalents', type='jsonrpc', auth='none',
                methods=POST, csrf=False, save_session=False)
    @eda_auth
    def eda_catalog_equivalents(self, **kwargs):
        @eda_endpoint
        def handler(self_, params):
            lines = params.get('lines')
            if not isinstance(lines, (list, tuple)):
                raise LabApiError(VALIDATION_ERROR, 'lines 必须是数组。',
                                  {'lines': 'not_a_list'})
            clean = []
            for raw in lines[:200]:
                if not isinstance(raw, dict):
                    continue
                item_key = str(raw.get('item_key') or '').strip()
                if item_key:
                    clean.append({'item_key': item_key,
                                  'quantity': raw.get('quantity')})
            try:
                limit = int(params.get('limit_per_line') or 5)
            except (TypeError, ValueError):
                limit = 5
            return request.env['lab.catalog.item'].equivalents(
                clean, limit_per_line=limit)
        return handler(self, _params(kwargs))

    @http.route(API + '/catalog/value_match', type='jsonrpc', auth='none',
                methods=POST, csrf=False, save_session=False)
    @eda_auth
    def eda_catalog_value_match(self, **kwargs):
        """原理图里没有立创编号的器件：按「值 + 封装」查候选。

        用户的原话是「像这种值有封装有为什么不做匹配」。这些器件以前只被丢进
        「未并入库存」表，什么忙都帮不上。这里用值和封装去器件库搜，**只返回
        候选供人判断，绝不自动合并或替换**。

        入参 ``queries`` 是检索词数组（如 ``["100nF 0402", "10K 0603"]``），
        出参 ``{results: [{query, items, total}]}``，顺序与入参一致。
        """
        @eda_endpoint
        def handler(self_, params):
            queries = params.get('queries')
            if not isinstance(queries, (list, tuple)):
                raise LabApiError(VALIDATION_ERROR, 'queries 必须是数组。',
                                  {'queries': 'not_a_list'})
            try:
                limit = int(params.get('limit') or 3)
            except (TypeError, ValueError):
                limit = 3
            limit = max(1, min(limit, 10))

            Catalog = request.env['lab.catalog.item']
            results = []
            # 最多 200 个不同检索词，避免一次原理图把库扫穿。
            for raw in list(queries)[:200]:
                query = str(raw or '').strip()
                if not query:
                    results.append({'query': query, 'items': [], 'total': 0})
                    continue
                # **不**加 stock_only：实验室常备库存只有几十种，绝大多数值和
                # 封装组合在库里是「有资料但无库存」。只返回有库存的会让用户
                # 看到一屏空白，反而更困惑。这里返回资料库匹配项并带上库存量
                # （0 也显示），用户自己判断要不要采购。
                # 多取一些再本地重排：search_unified 按「有库存优先 + C 码」
                # 排序，对 `10K 0603` 会把 110kΩ/210kΩ 排在 10kΩ 前面
                # （`K` 匹配了 `110k`）。这里把值完全出现在名称里的排前。
                # 取 50 条再本地重排：`10K 0603` 在库里匹配到 500+ 条
                # （`K` 命中 `110k`/`210k`），真正的 10kΩ 可能排在几十位之后。
                items, _cursor, total = Catalog.search_unified(
                    query=query, limit=50)
                value = query.split(' ')[0].lower()
                # 值必须**独立出现**：`10k` 不能因为 `110kΩ` 里含有 `10k`
                # 就当成匹配。前后不能紧邻数字或字母。
                pattern = re.compile(
                    r'(?<![0-9a-z.])' + re.escape(value) + r'(?![0-9])'
                    if value else r'(?!)')

                def _rank(item):
                    name = str(item.get('name') or '').lower()
                    return (0 if pattern.search(name) else 1,
                            0 if item.get('lab_available_quantity') else 1)
                items = sorted(items, key=_rank)[:limit]
                results.append({'query': query, 'items': items, 'total': total})
            return {'results': results}
        return handler(self, _params(kwargs))

    # ------------------------------------------------------------------ 库存
    @http.route(API + '/inventory/locations', type='jsonrpc', auth='none',
                methods=POST, csrf=False, save_session=False)
    @eda_auth
    def eda_locations(self, **kwargs):
        @eda_endpoint
        def handler(self_, params):
            return request.env['lab.workflow.common'].lab_locations(
                with_stats=bool(params.get('with_stats')))
        return handler(self, _params(kwargs))

    @http.route(API + '/inventory/issue', type='jsonrpc', auth='none',
                methods=POST, csrf=False, save_session=False)
    @eda_auth
    def eda_issue(self, **kwargs):
        @eda_endpoint
        def handler(self_, params):
            return request.env['lab.workflow.common'].lab_issue(params)
        return handler(self, _params(kwargs))


# ---------------------------------------------------------------------- 工具
def _params(kwargs):
    """兼容 jsonrpc 的几种参数投递方式（与 lab_catalog 的 api_route 一致）。"""
    data = kwargs.get('params')
    if data is None:
        data = kwargs or {}
    return data if isinstance(data, dict) else {}


def _as_list(value):
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if item]
    if isinstance(value, str) and value:
        return [value]
    return []


def _clean_parameter_filters(value):
    if not isinstance(value, dict):
        return {}
    clean = {}
    for key, raw in value.items():
        values = raw if isinstance(raw, (list, tuple)) else [raw]
        values = [str(item) for item in values if item not in (None, '')]
        if values:
            clean[str(key)] = values
    return clean
