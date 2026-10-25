# -*- coding: utf-8 -*-
"""页面路由：欢迎 / 登录 / 仓库列表 / 器件详情。

设计要点
--------
* 页面地址与接口地址分离：页面由本模块渲染，数据仍然通过既有模型的同一份实现
  取得（搜索就是 lab.catalog.item.search_unified，前端后续翻页再走 /lab/api/catalog/search）。
* 不用 auth='user'，而是 auth='public' + 显式判定，这样匿名访问会被导到**本站自己的**
  /team/login?next=...，而不是 Odoo 原生 /web/login，地址栏不会跳进 /odoo。
* 未登录、无权限、找不到、参数非法都有独立页面状态，不用 303 回后台冒充完成。
"""
import logging

from odoo.exceptions import AccessError, MissingError, UserError
from odoo.http import request
from werkzeug.utils import redirect

from odoo import http

from urllib.parse import quote

from ..tools.paths import (clamp_limit, error_message, format_price,
                           format_quantity,
                           is_valid_item_key, item_url, lab_url,
                           normalize_next, parse_flag, resolve_base,
                           safe_doc_url)
from .common import (config_enabled, current_base, has_catalog_access,
                     is_anonymous, redirect_to_login, render, render_denied,
                     root_alias_denied, shell_context, PARAM_ROOT_ALIASES)

_logger = logging.getLogger(__name__)

CATEGORY_LIMIT = 4000


def in_savepoint(func):
    """在 SAVEPOINT 内执行一次读操作，异常在 savepoint 之外重新抛出。

    与 lab_catalog.controllers.envelope.api_route 的做法一致：数据库一旦抛错，
    当前事务已中止，若不在同层回滚到 savepoint，后续 QWeb 渲染/runtime 再访问
    数据库就会继续报 InFailedSqlTransaction，表现为整页白屏。这里先回滚再上抛，
    由调用方渲染错误页，页面其余部分仍然可渲染。
    """
    cr = request.env.cr
    cr.execute('SAVEPOINT lab_team_web')
    try:
        result = func()
    except Exception:
        try:
            cr.execute('ROLLBACK TO SAVEPOINT lab_team_web')
        finally:
            try:
                cr.execute('RELEASE SAVEPOINT lab_team_web')
            except Exception:
                pass
        raise
    cr.execute('RELEASE SAVEPOINT lab_team_web')
    return result


def _guard_catalog():
    """返回 None 表示放行；否则返回该直接返回的响应。"""
    if is_anonymous():
        return redirect_to_login()
    if not has_catalog_access():
        return render_denied(403, 'no_catalog_role')
    return None


def _image_src(url):
    """图片统一走 lab_catalog 既有的缓存代理；已经是站内路径的直接用。"""
    value = (url or '').strip() if isinstance(url, str) else ''
    if not value:
        return ''
    if value.startswith('/') and not value.startswith('//'):
        return value
    return '/lab/api/asset?url=' + quote(value, safe='')


def _decorate_items(items, base):
    """给检索结果补页面需要的派生字段（链接/图片/展示数量），不改原字段。"""
    out = []
    for item in (items or []):
        row = dict(item)
        row['href'] = item_url(base, row.get('item_key') or '')
        row['image_src'] = _image_src(row.get('image_url'))
        row['lab_quantity_display'] = format_quantity(row.get('lab_quantity'))
        row['price_display'] = format_price(row.get('price'), row.get('currency'))
        out.append(row)
    return out


def _decorate_files(files):
    """资料链接先过白名单再交给模板；不合格的只显示名称，不产生 href。"""
    out = []
    for doc in (files or []):
        if not isinstance(doc, dict):
            continue
        row = dict(doc)
        row['href'] = safe_doc_url(row.get('url'))
        out.append(row)
    return out


def _categories(base, query='', stock_only=False):
    """分类树（字段与 /lab/api/catalog/categories 对齐，id 一律 PG id）。"""
    try:
        cats = in_savepoint(lambda: request.env['lab.catalog.category'].search(
            [], order='level, sort, catalog_id', limit=CATEGORY_LIMIT))
    except Exception:                       # 分类表不可用不应让整页崩
        _logger.warning('lab_team_web: 读取分类失败', exc_info=True)
        return []
    out = []
    for c in cats:
        out.append({
            'id': c.id,
            'name': c.name,
            'level': c.level or 0,
            'parent_id': c.parent_id.id or None,
            'product_count': c.product_count or 0,
            'has_children': bool(c.has_children),
            'href': lab_url(base, query=query, category_id=c.id, stock_only=stock_only),
        })
    return out


class LabTeamPages(http.Controller):

    # ------------------------------------------------------------------ 欢迎页
    @http.route(['/team', '/team/'], type='http', auth='public',
                website=False, sitemap=False)
    def welcome(self, **kwargs):
        ctx = shell_context('欢迎')
        return render('lab_team_web.page_welcome', ctx)

    # ------------------------------------------------------------------ 登录
    @http.route(['/team/login', '/login'], type='http', auth='public',
                website=False, sitemap=False, methods=['GET', 'POST'])
    def login(self, next=None, **kwargs):
        if root_alias_denied():
            return request.not_found()
        base = current_base()
        target = normalize_next(next, base + '/lab' if base else '/lab')
        if not is_anonymous():
            return redirect(target, code=303)
        # 无 JS 时表单以 POST 提交回本页：不读取、不回显任何账号密码字段，
        # 只重新渲染登录页，避免密码进入 URL 或访问日志。
        ctx = shell_context('登录', {
            'lc_next': target,
            'lc_db': getattr(request.session, 'db', None) or getattr(request, 'db', None) or '',
            'lc_error': '',
            'lc_login_action': (base + '/login') if base else '/login',
            'lc_auth_endpoint': '/web/session/authenticate',
        })
        return render('lab_team_web.page_login', ctx)

    # ------------------------------------------------------------------ 退出
    @http.route(['/team/logout', '/logout'], type='http', auth='public',
                website=False, methods=['POST'], csrf=True)
    def logout(self, **kwargs):
        if root_alias_denied():
            return request.not_found()
        try:
            request.session.logout(keep_db=True)
        except TypeError:                    # 兼容不同小版本的签名
            request.session.logout()
        base = current_base()
        return redirect((base + '/login') if base else '/login', code=303)

    # ------------------------------------------------------------------ 仓库首页
    @http.route(['/team/lab', '/lab'], type='http', auth='public',
                website=False, sitemap=False)
    def lab(self, q=None, category_id=None, cursor=None, stock_only=None, **kwargs):
        if root_alias_denied():
            return request.not_found()
        blocked = _guard_catalog()
        if blocked is not None:
            return blocked

        base = current_base()
        query = (q or '').strip()
        limit = clamp_limit(kwargs.get('limit'))
        category = None
        if category_id:
            try:
                category = int(category_id)
            except (TypeError, ValueError):
                category = None
        only_stock = parse_flag(stock_only)

        items, next_cursor, total = [], None, 0
        error = None
        try:
            items, next_cursor, total = in_savepoint(
                lambda: request.env['lab.catalog.item'].search_unified(
                    query=query, category_id=category, stock_only=only_stock,
                    cursor=cursor or None, limit=limit))
        except (AccessError, UserError) as exc:
            _logger.info('lab_team_web: 检索被拒绝/失败: %s', exc)
            error = error_message('FORBIDDEN')
        except Exception:
            _logger.exception('lab_team_web: 检索异常')
            error = error_message('INTERNAL_ERROR')

        items = _decorate_items(items, base)
        categories = _categories(base, query, only_stock)
        next_url = None
        if next_cursor:
            next_url = lab_url(base, query=query, category_id=category,
                               cursor=next_cursor, stock_only=only_stock)
        all_url = lab_url(base, query=query, stock_only=only_stock)

        ctx = shell_context('仓库', {
            'lc_items': items,
            'lc_total': total,
            'lc_next_url': next_url,
            'lc_next_cursor': next_cursor or '',
            'lc_query': query,
            'lc_stock_only': only_stock,
            'lc_category_id': category,
            'lc_categories': categories,
            'lc_all_url': all_url,
            'lc_error': error or '',
            'lc_limit': limit,
            'lc_is_empty': (not items) and not error,
        })
        return render('lab_team_web.page_lab', ctx)

    # ------------------------------------------------------------------ 器件详情
    @http.route(['/team/lab/items/<string:item_key>', '/lab/items/<string:item_key>'],
                type='http', auth='public', website=False, sitemap=False)
    def item(self, item_key, **kwargs):
        if root_alias_denied():
            return request.not_found()
        blocked = _guard_catalog()
        if blocked is not None:
            return blocked

        if not is_valid_item_key(item_key):
            return render_denied(400, 'invalid_item_key')

        data = None
        error = None
        try:
            data = in_savepoint(
                lambda: request.env['lab.catalog.item'].detail(item_key))
        except (AccessError, UserError) as exc:
            _logger.info('lab_team_web: 详情被拒绝: %s', exc)
            error = error_message('FORBIDDEN')
        except Exception:
            _logger.exception('lab_team_web: 详情异常')
            error = error_message('INTERNAL_ERROR')

        if data is None and not error:
            return render_denied(404, 'item_not_found')
        if error:
            ctx = shell_context('器件详情', {
                'lc_error': error, 'lc_item_key': item_key,
            })
            return render('lab_team_web.page_detail_error', ctx, status=200)

        item = data.get('item') or {}
        ctx = shell_context('器件详情', {
            'lc_item': item,
            'lc_image_src': _image_src(item.get('image_url')),
            'lc_quantity_display': format_quantity(item.get('lab_quantity')),
            'lc_available_display': format_quantity(item.get('lab_available_quantity')),
            'lc_parameters': data.get('parameters') or [],
            'lc_files': _decorate_files(data.get('files') or []),
            'lc_lab_templates': data.get('lab_templates') or [],
            'lc_locations': data.get('locations') or [],
            'lc_bags': data.get('bags') or [],
            'lc_issues': data.get('issues') or [],
            'lc_history': data.get('history') or [],
            'lc_item_key': item_key,
            'lc_error': '',
        })
        return render('lab_team_web.page_detail', ctx)
