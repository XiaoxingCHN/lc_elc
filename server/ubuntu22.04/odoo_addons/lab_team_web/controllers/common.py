# -*- coding: utf-8 -*-
"""战队管理站点：请求上下文、权限判定、挂载前缀与 management Host 根入口。

本模块只负责**外壳**（布局/路由/会话态），业务一律复用既有模型与接口：
* 认证：Odoo 原生 /web/session/authenticate（前端调用，本模块不重写认证）
* 权限：lab_catalog / lab_workflow 的既有组（服务端一律再校验一次）
* 数据：lab.catalog.item.search_unified / detail（与 /lab/api/catalog/* 同一实现）

权限分层要点（Codex 反馈）：库存角色（lab_workflow）与目录读取角色
（lab_catalog）不是一回事，目录页只要求目录读取权限；库存/标签能力另行判断，
不用 inventory/bootstrap 的失败去阻断只有目录权限的用户。
"""
import hashlib
import logging
import os

from odoo.http import request

from urllib.parse import urlsplit

from ..tools.paths import (CANONICAL_BASE, decide_root, format_quantity,
                           host_is_management, is_root_alias_path, login_url,
                           normalize_next, resolve_base)

_logger = logging.getLogger(__name__)

#: 本模块根目录（controllers/ 的上一级），用于按文件内容计算静态资源版本
_MODULE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 静态资源版本缓存：{绝对路径: ((mtime_ns, size), 版本串)}
#: 只有文件确实变了才重新算 hash，正常请求开销是一次 stat。
_ASSET_VERSION_CACHE = {}


def asset_version(relative_path):
    """按文件内容（SHA1 前 12 位）生成静态资源版本号。

    为什么不用模块版本号：模板里写死 `?v=19.0.x` 时，升级模块或改 CSS
    都不会改变 URL，浏览器直接命中旧缓存——实测出现过"源码有 88px 规则、
    DOM 加载的 team.css 里没有"的情况。内容哈希让"文件变了 URL 就变"。

    读取失败返回 '0'，页面仍可用（只是失去缓存失效能力），不抛异常。
    """
    full_path = os.path.join(_MODULE_ROOT, relative_path)
    try:
        stat = os.stat(full_path)
    except OSError:
        return '0'
    signature = (stat.st_mtime_ns, stat.st_size)
    cached = _ASSET_VERSION_CACHE.get(full_path)
    if cached and cached[0] == signature:
        return cached[1]
    digest = hashlib.sha1()
    try:
        with open(full_path, 'rb') as handle:
            for chunk in iter(lambda: handle.read(65536), b''):
                digest.update(chunk)
    except OSError:
        return '0'
    version = digest.hexdigest()[:12]
    _ASSET_VERSION_CACHE[full_path] = (signature, version)
    return version

#: 器件库读取权限（与 lab_catalog.controllers.envelope._has_catalog_access 一致）
CATALOG_GROUPS = (
    'lab_catalog.group_lab_catalog_user',
    'lab_catalog.group_lab_catalog_manager',
    'base.group_system',
)

#: 实验室角色（与 lab_workflow 的分层一致）
LAB_GROUPS = (
    'lab_workflow.group_lab_user',
    'lab_workflow.group_lab_operator',
    'lab_workflow.group_lab_manager',
)

LAB_MANAGER_GROUP = 'lab_workflow.group_lab_manager'

#: 参数
PARAM_ROOT_ALIASES = 'lab_team_web.root_aliases'
PARAM_SITE_TITLE = 'lab_team_web.site_title'
PARAM_MANAGEMENT_HOST = 'lab_team_web.management_host'
PARAM_MANAGEMENT_ENABLED = 'lab_team_web.management_host_enabled'


def get_param(key, default=''):
    try:
        return request.env['ir.config_parameter'].sudo().get_param(key, default)
    except Exception:
        _logger.warning('lab_team_web: 读取参数 %s 失败，使用默认值', key)
        return default


def config_enabled(key, default='1'):
    return str(get_param(key, default)).strip() not in ('0', 'false', 'False', '')


def site_title():
    return get_param(PARAM_SITE_TITLE, '力创实验室 · 战队仓库') or '力创实验室 · 战队仓库'


def management_hosts():
    return get_param(PARAM_MANAGEMENT_HOST, '') or ''


def is_anonymous():
    user = request.env.user
    if not request.env.uid or not user:
        return True
    try:
        return bool(user._is_public())
    except AttributeError:
        public = request.env.ref('base.public_user', raise_if_not_found=False)
        return bool(public and user.id == public.id)


def _has_group(user, xmlid):
    """组不存在时返回 False，而不是抛异常（模块可能未安装）。"""
    try:
        return bool(user.has_group(xmlid))
    except Exception:
        return False


def has_catalog_access(user=None):
    user = user or request.env.user
    return any(_has_group(user, xmlid) for xmlid in CATALOG_GROUPS)


def has_lab_access(user=None):
    user = user or request.env.user
    return any(_has_group(user, xmlid) for xmlid in LAB_GROUPS)


def is_lab_manager(user=None):
    user = user or request.env.user
    return _has_group(user, LAB_MANAGER_GROUP)


def permissions():
    return {
        'can_catalog': has_catalog_access(),
        'can_lab': has_lab_access(),
        'is_manager': is_lab_manager(),
    }


def management_host_active():
    """当前请求是否落在已配置的 management Host 上（与根入口开关一致）。"""
    try:
        host = request.httprequest.host
    except Exception:
        return False
    if not config_enabled(PARAM_MANAGEMENT_ENABLED):
        return False
    hosts = management_hosts()
    if not hosts:
        return False
    return host_is_management(host, hosts)


def current_base():
    """当前请求对应的链接基址。

    优先级：
      1) management Host 命中 -> ''（根级别；/、/login、/logout、/lab 全部根级）
      2) 否则按路径推断：/team/** -> '/team'，根级别别名 -> ''
      3) 其它 -> '/team'（安全回退）
    """
    try:
        path = request.httprequest.path
    except Exception:
        path = CANONICAL_BASE
    # 规范路径优先：/team/** 自己保持 /team 基址，避免在管理 Host 上
    # 出现"页面在 /team/lab、链接却跳 /login"的割裂。
    if path == CANONICAL_BASE or path.startswith(CANONICAL_BASE + '/'):
        return CANONICAL_BASE
    if management_host_active():
        return ''
    return resolve_base(path, config_enabled(PARAM_ROOT_ALIASES))


def root_alias_denied():
    """root_aliases=0 时，根级别别名必须表现得像不存在（路由真实回退）。

    * management Host 命中时不受该开关影响（此时根级别就是它的正常地址）；
    * 只对 /login、/logout、/lab、/lab/items/... 生效；
    * /lab/api、/lab/scan、/lab/labels、/lab/client 等其它控制器路由永不涉及。
    """
    if management_host_active():
        return False
    if config_enabled(PARAM_ROOT_ALIASES):
        return False
    try:
        path = request.httprequest.path
    except Exception:
        return False
    return is_root_alias_path(path)


def _request_next():
    """匿名访问时的回跳目标：完整路径 + 查询串（冒号等合法字符原样保留）。"""
    try:
        http_request = request.httprequest
        return http_request.full_path if http_request.query_string else http_request.path
    except Exception:
        return CANONICAL_BASE


def shell_context(page_title='', extra=None):
    """所有页面共用的外壳上下文。"""
    anonymous = is_anonymous()
    base = current_base()
    user = request.env.user
    perms = {} if anonymous else permissions()
    ctx = {
        'lc_base': base,
        'lc_anonymous': anonymous,
        'lc_page_title': page_title,
        'lc_site_title': site_title(),
        'lc_user_name': '' if anonymous else (user.name or user.login or ''),
        'lc_user_login': '' if anonymous else (user.login or ''),
        'lc_csrf_token': request.csrf_token(),
        'lc_permissions': perms,
        'lc_login_url': login_url(base, _request_next()),
        'lc_logout_url': base + '/logout',
        'lc_welcome_url': (base + '/') if base else '/',
        'lc_lab_url': base + '/lab',
        'lc_version': '19.0.1.0.0',
        # 静态资源版本：内容哈希，文件一变 URL 就变，无需用户手动清缓存
        'lc_css_v': asset_version('static/src/css/team.css'),
        'lc_js_v': asset_version('static/src/js/team.js'),
        'lc_lang': (getattr(request.env, 'lang', None) or 'zh_CN').replace('_', '-'),
        'lc_entries': site_entries(base, anonymous, perms),
        # 模板里直接用 format_qty(...) 渲染数量，避免在 QWeb 里写格式化逻辑
        'format_qty': format_quantity,
    }
    if extra:
        ctx.update(extra)
    return ctx


def site_entries(base, anonymous, perms):
    """欢迎页入口清单。未实现的能力不列成可执行入口（只读首批）。"""
    entries = []
    if anonymous:
        entries.append({
            'title': '登录', 'href': login_url(base, (base + '/lab') if base else '/lab'),
            'desc': '使用实验室系统账号登录后进入仓库检索。', 'state': 'available',
        })
    if not anonymous and perms.get('can_catalog'):
        entries.append({
            'title': '器件资料', 'href': (base + '/lab') if base else '/lab',
            'desc': '按分类或关键词查找器件，查看参数、实验室库存与存放位置。',
            'state': 'available',
        })
    if not anonymous and not perms.get('can_catalog'):
        entries.append({
            'title': '器件资料', 'href': '', 'desc': '当前账号没有器件资料查看权限。',
            'state': 'denied',
        })
    entries.append({
        'title': '采购入库', 'href': '', 'state': 'planned',
        'desc': '暂未开放。',
    })
    entries.append({
        'title': '领用与归还', 'href': '', 'state': 'planned',
        'desc': '暂未开放。',
    })
    entries.append({
        'title': '库位与操作记录', 'href': '', 'state': 'planned',
        'desc': '暂未开放。',
    })
    return entries


def redirect_to_login(next_path=None):
    from werkzeug.utils import redirect
    target = next_path or _request_next()
    return redirect(login_url(current_base(), normalize_next(target)), code=303)


def render(template, values=None, status=200):
    response = request.render(template, values or {})
    try:
        response.status_code = status
    except Exception:
        pass
    return response


def render_denied(status=403, reason='forbidden'):
    """403 无权限 / 404 不存在 / 400 标识非法 三种状态各有独立文案。"""
    if status == 400:
        code, title = 'INVALID_REQUEST', '器件标识不合法'
    elif status == 404:
        code, title = 'NOT_FOUND', '页面不存在'
    else:
        code, title = 'FORBIDDEN', '没有访问权限'
    ctx = shell_context(title, {
        'lc_reason': reason,
        'lc_denied_code': code,
        'lc_denied_status': status,
    })
    return render('lab_team_web.page_denied', ctx, status=status)


# ---------------------------------------------------------------------------
# management Host 根入口（供 models/ir_http.py 调用）
# ---------------------------------------------------------------------------
def is_editor_context():
    """是否处在 Odoo Website 编辑器 / 预览 iframe 里。

    真实链路（Odoo 19 website_builder_action.js）：
      iframe 初始地址是 /website/force/<id>?path=/ ，随后 website_force 会
      redirect 到那个 path —— 很可能是**不带任何 edit 参数的 /**。
    所以只看 edit/cedit/ql 不足以保护编辑器，必须识别"这是 iframe 导航"。

    采用两类信号，任一命中即回退（都不依赖 session.force_website_id，
    避免管理员用过编辑器之后普通欢迎页永久变成旧站）：
      1) Sec-Fetch-Dest: iframe / frame（现代浏览器对 iframe 导航必发）；
      2) Referer 指向本站 /website/ 下的路径（预览/编辑器上下文）。
    """
    try:
        headers = request.httprequest.headers
        dest = (headers.get('Sec-Fetch-Dest') or '').strip().lower()
        if dest in ('iframe', 'frame', 'embed', 'object'):
            return True
        referer = headers.get('Referer') or ''
        if referer:
            parsed = urlsplit(referer)
            if parsed.path.startswith('/website/'):
                return True
        args = request.httprequest.args
        if args.get('edit') or args.get('cedit') or args.get('ql'):
            return True
        path = request.httprequest.path
        if path.startswith('/website/'):
            return True
    except Exception:
        # 判定失败时保守回退到原逻辑，宁可不接管也不要抢占编辑器
        return True
    return False


def management_root_response():
    """命中 management Host 的根路径时返回响应，否则返回 None 交回原逻辑。

    安全约束：
      * 默认关闭（未配置 management_host 时不接管任何 /）；
      * 只接管根路径，且跳过 GET/HEAD 以外的请求；
      * 处在网站编辑器/预览 iframe 上下文时**必定回退**（见 is_editor_context）；
      * 其它 Host（含现有官网域名）一律 fallthrough。
    """
    try:
        http_request = request.httprequest
        path = http_request.path
        host = http_request.host
        if path != '/':
            return None
        if http_request.method not in ('GET', 'HEAD'):
            return None
        if is_editor_context():
            return None
        decision = decide_root(
            path, host, management_hosts(),
            config_enabled(PARAM_MANAGEMENT_ENABLED))
        if decision != 'serve':
            return None
        return render('lab_team_web.page_welcome', shell_context('欢迎'))
    except Exception:
        _logger.exception('lab_team_web: management Host 根入口渲染失败，回退原逻辑')
        return None
