# -*- coding: utf-8 -*-
"""旧入口迁移层：精确白名单的旧 GET 链接 -> 自有业务页（方案 §2.3）。

职责边界
--------
1. 只登记方案矩阵中「迁移」类入口的**固定 xmlid**，每条一个静态路由
   ``/odoo/action-<xmlid>``；不做 ``/odoo/action-<任意>`` 通配，不接受任意
   URL，也不把查询串原样透传（上下文按白名单字段逐个校验类型）。
2. 顺序固定为**先鉴权、再确认目标路由已注册、最后 303**：
   * 匿名 -> 303 到自有登录页（``next`` 保留原地址，登录后回到本入口再跳）；
   * 无角色 -> 403 显式拒绝，**不回退旧台**（方案 §2.1 第 7 条）；
   * 目标页未注册（模块未安装/未升级这类部署原因）-> 503 显式说明「迁移未完成」，
     并给管理员一个 ``/web#action=<id>`` 的旧动作回退链接；不 404、不静默改道。
3. 只处理 GET：旧写入口（``/lab/scan/submit``、``/lab/labels/plan`` 等 POST）
   不经过本模块，不会被 307/308 重放（方案 §2.3）。
4. ``/lab/scan`` 的条件 303 已由 ``lab_workflow.controllers.lab_web`` 提供，
   本模块**不重复注册**该路径，避免抢路由。

菜单改指（方案 §2.6 方式 A）在 ``views/legacy_entry_menu.xml``：新增
``ir.actions.act_url`` 并用同一 xmlid 覆盖菜单的 ``action``；原 ``ir.actions.*``
记录保留，供管理员维护与回退引用。
"""

import logging
import re
from html import escape
from urllib.parse import urlencode

from werkzeug.utils import redirect

from odoo import http
from odoo.http import request

from . import common

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 目标页（全部是 workflow_pages.py / pages.py 已注册的路由，见方案 §2.2）
# ---------------------------------------------------------------------------
TARGET_CATALOG = '/team/lab'
TARGET_SCAN = '/team/scan'
TARGET_RECEIPTS = '/team/lab/receipts'
TARGET_BAGS = '/team/lab/bags'
TARGET_ISSUES = '/team/lab/issues'
TARGET_LABELS = '/team/lab/labels'
TARGET_LOCATIONS = '/team/lab/locations'
TARGET_MAPPINGS = '/team/lab/location-mappings'
TARGET_HISTORY = '/team/lab/history'
TARGET_MATERIALS = '/team/lab/materials'

#: 权限门槛（对应 common.py 的组判定；页面自身还有一层守卫，二者不互相替代）
NEED_LAB = 'lab'
NEED_CATALOG = 'catalog'
NEED_MANAGER = 'manager'

#: 403 文案 reason（命中 common.WORKFLOW_DENIED_TEXT 的键）
DENIED_LAB = 'no_lab_role'
DENIED_CATALOG = 'no_catalog_role'
DENIED_MANAGER = 'manager_only'

#: 允许保留的业务上下文（字段名白名单；未登记的参数一律丢弃）
INT_CONTEXT_KEYS = ('bag_id', 'issue_line_id', 'category_id')
KEY_CONTEXT_KEYS = ('item_key',)
MAX_INT = 2147483647
#: item_key 与 pages.py 的 /team/lab/items/<item_key> 同形：字母数字开头，允许 . _ : -
KEY_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$')


def _entry(xmlid, target, need, context=(), bag_detail=False):
    return {
        'xmlid': xmlid,
        'target': target,
        'need': need,
        'context': tuple(context),
        'bag_detail': bag_detail,
    }


#: 旧 GET 兼容白名单（方案 §2.3「只登记矩阵中迁移类入口的固定 xmlid」）。
#: 刻意**不含**下列仍保留原生的入口：
#:   lab_workflow.action_lab_request_log（低频诊断面，方式 C）
#:   lab_catalog.view_lab_catalog_category_action / view_lab_catalog_import_run_action
#:   lab_inventory.action_lab_move（stock.move 流水，新 history 只覆盖 lab.operation）
LEGACY_ACTIONS = {
    # 扫码操作台：旧台「一页四卡」拆成 /team/scan（解析）+ /team/lab/receipts（入库）
    'lab_workflow.action_lab_scan_console': _entry(
        'lab_workflow.action_lab_scan_console', TARGET_SCAN, NEED_LAB),
    'lab_workflow.action_lab_bag': _entry(
        'lab_workflow.action_lab_bag', TARGET_BAGS, NEED_LAB,
        context=('bag_id',), bag_detail=True),
    'lab_workflow.action_lab_issue_line': _entry(
        'lab_workflow.action_lab_issue_line', TARGET_ISSUES, NEED_LAB,
        context=('bag_id', 'issue_line_id', 'item_key')),
    'lab_workflow.action_lab_return_wizard': _entry(
        'lab_workflow.action_lab_return_wizard', TARGET_ISSUES, NEED_LAB,
        context=('bag_id', 'issue_line_id', 'item_key')),
    # 标签：页面级只要 lab 角色；PDF 端点仍由 lab_workflow 校验 operator
    'lab_workflow.action_lab_label_open': _entry(
        'lab_workflow.action_lab_label_open', TARGET_LABELS, NEED_LAB),
    'lab_workflow.action_lab_location': _entry(
        'lab_workflow.action_lab_location', TARGET_LOCATIONS, NEED_LAB),
    'lab_workflow.action_lab_operation': _entry(
        'lab_workflow.action_lab_operation', TARGET_HISTORY, NEED_LAB),
    # 统一器件库（OWL）-> 自有器件库页面
    'lab_catalog.action_lab_unified_catalog_client': _entry(
        'lab_catalog.action_lab_unified_catalog_client', TARGET_CATALOG, NEED_CATALOG,
        context=('category_id',)),
    'lab_catalog.view_lab_catalog_item_action': _entry(
        'lab_catalog.view_lab_catalog_item_action', TARGET_MATERIALS, NEED_CATALOG,
        context=('item_key',)),
    'lab_catalog.view_lab_catalog_binding_action': _entry(
        'lab_catalog.view_lab_catalog_binding_action', TARGET_MATERIALS, NEED_CATALOG,
        context=('item_key',)),
    'lab_inventory.action_lab_product': _entry(
        'lab_inventory.action_lab_product', TARGET_MATERIALS, NEED_CATALOG,
        context=('item_key',)),
    'lab_inventory.action_lab_location': _entry(
        'lab_inventory.action_lab_location', TARGET_LOCATIONS, NEED_LAB),
    'lab_inventory.action_lab_mapping': _entry(
        'lab_inventory.action_lab_mapping', TARGET_MAPPINGS, NEED_MANAGER),
}


def legacy_route(xmlid):
    """旧动作对应的固定路径（静态路由，不用通配）。"""
    return '/odoo/action-' + xmlid


def legacy_entry(xmlid):
    return LEGACY_ACTIONS.get(xmlid)


def is_safe_target(url):
    """站内相对路径校验：拒绝协议相对地址、绝对 URL、反斜杠与 .. 段。

    映射表是代码常量，不拼接用户输入，这里仍是最后一道闸：
    任何将来误改成可拼接的实现都会在单测里立刻失败。
    """
    if not isinstance(url, str) or not url:
        return False
    if not url.startswith('/') or url.startswith('//'):
        return False
    if '\\' in url or '://' in url:
        return False
    if any(ch in url for ch in '\r\n\t '):
        return False
    path = url.split('?', 1)[0]
    if '%' in path:          # 目标页都是固定字面量路径，不出现百分号编码
        return False
    if any(segment == '..' for segment in path.split('/')):
        return False
    return True


def sanitize_context(values):
    """按白名单字段逐个取值并校验类型；未登记/非法值一律丢弃（不透传）。"""
    result = {}
    values = values or {}
    for key in INT_CONTEXT_KEYS:
        raw = values.get(key)
        if raw is None or raw == '':
            continue
        try:
            value = int(str(raw).strip())
        except (TypeError, ValueError):
            continue
        if 1 <= value <= MAX_INT:
            result[key] = value
    for key in KEY_CONTEXT_KEYS:
        raw = values.get(key)
        if not raw:
            continue
        text = str(raw).strip()
        if KEY_RE.match(text):
            result[key] = text
    return result


def target_url(entry, context):
    """目标地址 = 固定目标页 + 白名单上下文（bag 详情走路径，其余走查询串）。"""
    target = entry['target']
    allowed = entry.get('context') or ()
    kept = dict((key, value) for key, value in (context or {}).items() if key in allowed)
    if entry.get('bag_detail') and 'bag_id' in kept:
        target = '%s/%d' % (target, kept.pop('bag_id'))
    if kept:
        target = '%s?%s' % (target, urlencode(sorted(kept.items())))
    if not is_safe_target(target):
        raise ValueError('legacy entry target is not a safe site path: %r' % (target,))
    return target


def route_registered(path):
    """目标路径是否已注册（复用 lab_web.py:88-94 的 ir.http._match 判定）。"""
    try:
        request.env['ir.http']._match(path.split('?', 1)[0])
        return True
    except Exception:  # noqa: BLE001 - NotFound 等一律视为未注册
        return False


def access_allowed(need):
    if need == NEED_LAB:
        return common.has_lab_access()
    if need == NEED_CATALOG:
        return common.has_catalog_access()
    if need == NEED_MANAGER:
        return common.is_lab_manager()
    return False


def denied_reason(need):
    if need == NEED_CATALOG:
        return DENIED_CATALOG
    if need == NEED_MANAGER:
        return DENIED_MANAGER
    return DENIED_LAB


def _fallback_action_id(xmlid):
    """旧动作 id（仅用于「目标页未部署」时的管理员回退链接）。"""
    try:
        return request.env['ir.model.data'].sudo()._xmlid_to_res_id(
            xmlid, raise_if_not_found=False)
    except Exception:  # noqa: BLE001 - 回退链接是辅助信息，取不到就不显示
        return None


def _unavailable_response(entry, target):
    """目标页未注册：503 显式说明，不 404、不静默回退旧台。"""
    action_id = _fallback_action_id(entry['xmlid'])
    fallback = ''
    if action_id:
        fallback = ('<p><a href="/web#action=%d">在 Odoo 后台打开旧动作（管理员）</a></p>'
                    % action_id)
    body = (
        '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"/>'
        '<title>目标页未部署（迁移未完成）</title></head><body>'
        '<h1>目标页未部署（迁移未完成）</h1>'
        '<p>本入口已改指自有页面 %s，但当前 lab_team_web 版本没有注册该路由。'
        '这是部署版本问题，不是权限问题。</p>%s'
        '<p><a href="/team">返回战队管理站点</a></p></body></html>'
    ) % (escape(target), fallback)
    return request.make_response(body, status=503, headers=[
        ('Content-Type', 'text/html; charset=utf-8'),
        ('Cache-Control', 'no-store'),
        ('X-Content-Type-Options', 'nosniff'),
    ])


def _legacy_redirect(xmlid, kwargs):
    entry = legacy_entry(xmlid)
    if not entry:
        return request.not_found()
    if request.httprequest.method not in ('GET', 'HEAD'):
        return request.make_response('Method Not Allowed', status=405, headers=[
            ('Content-Type', 'text/plain; charset=utf-8'),
            ('Allow', 'GET, HEAD'),
            ('Cache-Control', 'no-store'),
        ])
    # 1) 先鉴权：匿名回登录页（next 保留原地址），无角色 403，不回退旧台。
    if common.is_anonymous():
        return common.redirect_to_login()
    if not access_allowed(entry['need']):
        return common.render_denied(403, denied_reason(entry['need']),
                                    base=common.workflow_base())
    # 2) 再确认目标页已注册（部署原因才允许显式失败）。
    target = target_url(entry, sanitize_context(kwargs))
    if not route_registered(target):
        _logger.warning('lab_team_web: 旧入口 %s 的目标页 %s 未注册（迁移未完成）',
                        xmlid, target)
        return _unavailable_response(entry, target)
    # 3) 最后 303（浏览器改用 GET 打开新页；不重放任何写请求）。
    return redirect(target, code=303)


class LabTeamWebLegacyEntries(http.Controller):
    """旧 GET 入口 -> 自有业务页（每条一个静态路由，白名单即代码本身）。

    方法集合显式声明为 GET/HEAD 之外的写方法也进本控制器，只为了让
    _legacy_redirect 能亲手回 405 + Allow: GET, HEAD：如果只声明 methods=['GET']，
    同路径的 POST 会被 Odoo 核心 /odoo/<path> 兜底接走（csrf=True），返回 400 而不是
    405，看起来像"能提交"。csrf=False 只用于让请求到达这段守卫，handler 不做任何写操作。
    """

    @http.route('/odoo/action-lab_workflow.action_lab_scan_console',
        type='http', auth='public', website=False, sitemap=False, csrf=False,
        methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'])
    def legacy_scan_console(self, **kwargs):
        return _legacy_redirect('lab_workflow.action_lab_scan_console', kwargs)

    @http.route('/odoo/action-lab_workflow.action_lab_bag',
        type='http', auth='public', website=False, sitemap=False, csrf=False,
        methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'])
    def legacy_bag(self, **kwargs):
        return _legacy_redirect('lab_workflow.action_lab_bag', kwargs)

    @http.route('/odoo/action-lab_workflow.action_lab_issue_line',
        type='http', auth='public', website=False, sitemap=False, csrf=False,
        methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'])
    def legacy_issue_line(self, **kwargs):
        return _legacy_redirect('lab_workflow.action_lab_issue_line', kwargs)

    @http.route('/odoo/action-lab_workflow.action_lab_return_wizard',
        type='http', auth='public', website=False, sitemap=False, csrf=False,
        methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'])
    def legacy_return_wizard(self, **kwargs):
        return _legacy_redirect('lab_workflow.action_lab_return_wizard', kwargs)

    @http.route('/odoo/action-lab_workflow.action_lab_label_open',
        type='http', auth='public', website=False, sitemap=False, csrf=False,
        methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'])
    def legacy_label_open(self, **kwargs):
        return _legacy_redirect('lab_workflow.action_lab_label_open', kwargs)

    @http.route('/odoo/action-lab_workflow.action_lab_location',
        type='http', auth='public', website=False, sitemap=False, csrf=False,
        methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'])
    def legacy_workflow_location(self, **kwargs):
        return _legacy_redirect('lab_workflow.action_lab_location', kwargs)

    @http.route('/odoo/action-lab_workflow.action_lab_operation',
        type='http', auth='public', website=False, sitemap=False, csrf=False,
        methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'])
    def legacy_operation(self, **kwargs):
        return _legacy_redirect('lab_workflow.action_lab_operation', kwargs)

    @http.route('/odoo/action-lab_catalog.action_lab_unified_catalog_client',
        type='http', auth='public', website=False, sitemap=False, csrf=False,
        methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'])
    def legacy_unified_catalog(self, **kwargs):
        return _legacy_redirect('lab_catalog.action_lab_unified_catalog_client', kwargs)

    @http.route('/odoo/action-lab_catalog.view_lab_catalog_item_action',
        type='http', auth='public', website=False, sitemap=False, csrf=False,
        methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'])
    def legacy_catalog_item(self, **kwargs):
        return _legacy_redirect('lab_catalog.view_lab_catalog_item_action', kwargs)

    @http.route('/odoo/action-lab_catalog.view_lab_catalog_binding_action',
        type='http', auth='public', website=False, sitemap=False, csrf=False,
        methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'])
    def legacy_catalog_binding(self, **kwargs):
        return _legacy_redirect('lab_catalog.view_lab_catalog_binding_action', kwargs)

    @http.route('/odoo/action-lab_inventory.action_lab_product',
        type='http', auth='public', website=False, sitemap=False, csrf=False,
        methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'])
    def legacy_inventory_product(self, **kwargs):
        return _legacy_redirect('lab_inventory.action_lab_product', kwargs)

    @http.route('/odoo/action-lab_inventory.action_lab_location',
        type='http', auth='public', website=False, sitemap=False, csrf=False,
        methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'])
    def legacy_inventory_location(self, **kwargs):
        return _legacy_redirect('lab_inventory.action_lab_location', kwargs)

    @http.route('/odoo/action-lab_inventory.action_lab_mapping',
        type='http', auth='public', website=False, sitemap=False, csrf=False,
        methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'])
    def legacy_inventory_mapping(self, **kwargs):
        return _legacy_redirect('lab_inventory.action_lab_mapping', kwargs)
