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
import json
import logging
import os

from odoo.http import request

from urllib.parse import urlsplit

from ..tools.paths import (CANONICAL_BASE, decide_root, format_quantity,
                           host_is_management, is_root_alias_path, login_url,
                           logout_url, normalize_next, resolve_base)

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

#: 工作流操作员 = 入库/领用/归还/标签的实际执行角色
LAB_OPERATOR_GROUPS = (
    'lab_workflow.group_lab_operator',
    'lab_workflow.group_lab_manager',
)

# ---------------------------------------------------------------------------
# 业务页面外壳（P3）：端点表、页面地址、导航、根级别名
#
# 这里只登记**地址与权限**，不含任何业务规则。业务页面由各 domain 子任务
# 在自己的 views/workflow_*.xml + static/src/js/pages/*.js 中实现；服务端
# 路由与 client 配置都在本文件与 workflow_pages.py 里维护，避免多方抢同一文件。
#
# 全部是站内相对路径（不得带 scheme/host）：绝对 URL 的 origin 由代理层推导，
# 非标准端口会被丢掉，表现为跳转跨 origin 被 CSP form-action 'self' 拒绝。
# ---------------------------------------------------------------------------
WORKFLOW_ENDPOINTS = {
    # 会话 / 引导
    'session': '/api/team/session',
    'bootstrap': '/lab/api/inventory/bootstrap',
    'locations': '/lab/api/inventory/locations',
    'locationCreate': '/lab/api/inventory/location_create',
    # 库位改/停用、映射、成员：契约见 backend-contract.md（后端任务提供）
    'locationUpdate': '/lab/api/inventory/location_update',
    'mappingList': '/lab/api/inventory/mapping_list',
    'mappingSet': '/lab/api/inventory/mapping_set',
    'mappingRemove': '/lab/api/inventory/mapping_remove',
    'members': '/lab/api/inventory/members',
    'memberSetRole': '/lab/api/inventory/member_set_role',
    # 扫码 / 两阶段入库
    'resolve': '/lab/api/inventory/resolve_code',
    'pendingList': '/lab/api/inventory/pending/list',
    'pendingCreate': '/lab/api/inventory/pending/create',
    'pendingUpdate': '/lab/api/inventory/pending/update',
    'pendingResolve': '/lab/api/inventory/pending/resolve',
    'pendingConfirm': '/lab/api/inventory/pending/confirm',
    'receipt': '/lab/api/inventory/receipt',
    # 领用 / 归还 / 查询
    'issue': '/lab/api/inventory/issue',
    'return': '/lab/api/inventory/return',
    'issues': '/lab/api/inventory/issues',
    'history': '/lab/api/inventory/history',
    # 袋（后端任务新增；未部署时页面显示空状态）
    'bags': '/lab/api/inventory/bags',
    'bag': '/lab/api/inventory/bag',
    # 标签
    'labelsPlan': '/lab/api/labels/plan',
    'labelsPreview': '/lab/api/labels/preview',
    'labelsPdf': '/lab/labels/pdf',
    # 目录（既有只读/写接口）
    'catalogSearch': '/lab/api/catalog/search',
    'catalogDetail': '/lab/api/catalog/detail',
    'catalogCategories': '/lab/api/catalog/categories',
    'catalogBind': '/lab/api/catalog/bind',
    'catalogCreateMaterial': '/lab/api/catalog/create_material',
    'asset': '/lab/api/asset',
}

#: 页面 id -> (中文标题, 站内路径)。路径用于导航与页内链接，路由注册在
#: controllers/workflow_pages.py（两处必须同时改，见 tests）。
WORKFLOW_PAGES = {
    'receipts': ('采购入库', '/lab/receipts'),
    'scan': ('扫码', '/scan'),
    'bags': ('实物袋', '/lab/bags'),
    'labels': ('标签', '/lab/labels'),
    'issue_new': ('领用', '/lab/issues/new'),
    'issues': ('领用记录', '/lab/issues'),
    'locations': ('库位', '/lab/locations'),
    'mappings': ('类别映射', '/lab/location-mappings'),
    'history': ('作业流水', '/lab/history'),
    'materials': ('器件档案', '/lab/materials'),
    'settings': ('管理', '/lab/settings'),
    'account': ('我的账号', '/account'),
}

#: 导航：(页面 id, 权限位, 是否未登录也显示)。顺序即显示顺序。
WORKFLOW_NAV = (
    ('lab', 'can_catalog', False),
    ('receipts', 'can_receipt', False),
    ('issue_new', 'can_issue', False),
    ('issues', 'can_lab', False),
    ('bags', 'can_lab', False),
    ('locations', 'can_lab', False),
    ('labels', 'can_manage_labels', False),
    ('history', 'can_lab', False),
    ('materials', 'can_catalog', False),
    ('settings', 'can_manage_members', False),
    ('account', None, True),
)

#: 权限不足时的页面文案（render_denied 通过 reason 取值）。
WORKFLOW_DENIED_TEXT = {
    'no_lab_role': ('需要实验室库存权限',
                    '当前账号没有实验室库存角色。请联系库存管理员加入「实验室库存 / 用户」组后重试。'),
    'manager_only': ('仅库存管理员可用',
                     '该页面只对「实验室库存 / 管理员」开放。需要调整库位、类别映射或成员角色时请联系管理员。'),
    'no_catalog_role': ('需要器件资料权限',
                        '当前账号没有器件库读取角色。请联系管理员分配目录权限后重试。'),
}

#: 浏览器侧上限（与 lab_workflow 服务端一致，前端先挡一次，服务端仍然校验）
#: 注：issues/history 服务端允许 limit≤200，这里给统一默认 100，页面要更多时
#: 自行传 limit（后端仍会 clamp），不要在前端假定 200。
WORKFLOW_LIMITS = {
    'pageSize': 24,
    'maxPageSize': 100,
    'maxIssueLines': 100,
    'maxPendingCount': 100,
    'labelMaxIds': 200,
    'labelMaxCopies': 200,
    'labelMinMm': 5,
}

#: 未确认结果的幂等键存储：浏览器 sessionStorage 前缀与保留时长（毫秒）。
WORKFLOW_ATTEMPT = {'prefix': 'lc-wf-attempt:', 'ttlMs': 1800000}

#: 提交/读取超时（毫秒）。
WORKFLOW_TIMEOUTS = {'submitMs': 30000, 'readMs': 20000}


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


def has_lab_operator(user=None):
    """入库/领用/归还/标签的写权限：操作员或管理员。"""
    user = user or request.env.user
    return any(_has_group(user, xmlid) for xmlid in LAB_OPERATOR_GROUPS)


def can_issue_for_others():
    """能否代他人领料。以 lab_workflow 的模型方法为准（含 stock 库存经理）。"""
    try:
        return bool(request.env['lab.workflow.common'].lab_can_issue_for_others())
    except Exception:
        # 模型不可用时退回组判定：宁可前端少给一个选项，也不放宽写权限。
        return is_lab_manager()


def permissions():
    return {
        'can_catalog': has_catalog_access(),
        'can_lab': has_lab_access(),
        'is_manager': is_lab_manager(),
    }


def workflow_permissions(user=None):
    """业务页面的权限位（只读派生，不新增身份系统）。

    与 lab_workflow 的服务端门槛一一对应：
      * 入库/领用/归还/标签 = group_lab_operator|manager
      * 库位改/映射/成员    = group_lab_manager
      * 代他人领料          = lab_can_issue_for_others()
    页面只按这些位**隐藏**入口；每个接口仍然独立校验，前端隐藏不是权限边界。
    """
    user = user or request.env.user
    perms = permissions()
    operator = has_lab_operator(user)
    manager = is_lab_manager(user)
    perms.update({
        'can_receipt': operator,
        'can_issue': operator,
        'can_return': operator,
        'can_manage_labels': operator,
        'can_issue_for_others': can_issue_for_others() if operator else False,
        'can_manage_locations': manager,
        'can_manage_mappings': manager,
        'can_manage_members': manager,
    })
    return perms


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


def workflow_base():
    """业务页面的链接基址：只由**实际路由前缀**决定（/team/** 或根级别）。

    为什么不用 current_base()：它按"根级别名白名单"推断，新增页面（/scan、
    /account、/lab/xxx）历史别名里没有，会被回退成 /team，导致"页面在 /scan、
    链接却跳 /team/lab"的割裂。这里的规则与 workflow_pages.py 注册的两种
    前缀一一对应：/team 开头 -> '/team'，其余根级别 -> ''。
    """
    try:
        path = request.httprequest.path or ''
    except Exception:
        return current_base()
    if path == CANONICAL_BASE or path.startswith(CANONICAL_BASE + '/'):
        return CANONICAL_BASE
    return ''


def workflow_root_denied():
    """root_aliases=0 时，新页面的根级别入口表现得像不存在。

    判定统一放在 tools/paths.is_root_alias_path（纯函数、有单测），本函数只负责
    "什么时候启用"：management Host 命中时不受开关影响；开关打开时一律放行。
    这样新页面的 404 语义与旧别名完全一致，不会出现两套名单漂移。
    """
    if management_host_active():
        return False
    if config_enabled(PARAM_ROOT_ALIASES):
        return False
    try:
        path = request.httprequest.path or ''
    except Exception:
        return False
    return is_root_alias_path(path)


def workflow_urls(base):
    """业务页面地址表（全部站内相对路径，随基址变化）。"""
    urls = {
        'welcome': (base + '/') if base else '/',
        'login': base + '/login',
        'logout': base + '/logout',
        'lab': base + '/lab',
        'item': base + '/lab/items/',
        'bag': base + '/lab/bags/',
    }
    for page_id, (_title, path) in WORKFLOW_PAGES.items():
        urls[page_id] = base + path
    return urls


def workflow_nav(base, perms, active='', anonymous=False):
    """站点导航。无权限的入口不渲染（不是渲染后报错）。"""
    if anonymous:
        return [{
            'id': 'login',
            'title': '登录',
            'href': login_url(base, (base + '/lab') if base else '/lab'),
            'active': False,
        }]
    items = []
    if perms.get('can_catalog'):
        items.append({'id': 'lab', 'title': '仓库',
                      'href': base + '/lab', 'active': active == 'lab'})
    for page_id, perm, _always in WORKFLOW_NAV:
        if page_id not in WORKFLOW_PAGES:
            continue
        if perm and not perms.get(perm):
            continue
        title, path = WORKFLOW_PAGES[page_id]
        items.append({'id': page_id, 'title': title,
                      'href': base + path, 'active': active == page_id})
    return items


def workflow_config(base, perms, page_id='', domain='', anonymous=False):
    """交给浏览器的工作流配置（写入 body 的 data-workflow-config）。

    只含地址、权限位与上限：**不含**用户名/登录名/会话标识/CSRF token，
    因此可以安全地放在 HTML 属性里（token 仍走模板上下文与表单隐藏域）。
    """
    return {
        'version': 1,
        'base': base,
        'page': page_id,
        'domain': domain,
        'authenticated': not anonymous,
        'endpoints': WORKFLOW_ENDPOINTS,
        'urls': workflow_urls(base),
        'permissions': {} if anonymous else dict(perms or {}),
        # 身份命名空间：未决提交按 (uid, company) 隔离存储，换账号/公司看不到别人的
        # 未决操作。只含整数 id，不含姓名/登录名/会话标识。
        'identity': {
            'uid': None if anonymous else (request.env.uid or None),
            'company_id': None if anonymous else (request.env.company.id or None),
        },
        'limits': WORKFLOW_LIMITS,
        'attempt': WORKFLOW_ATTEMPT,
        'timeouts': WORKFLOW_TIMEOUTS,
    }


def shell_context(page_title='', extra=None, base=None, active_page=''):
    """所有页面共用的外壳上下文。

    base 缺省用 current_base()（旧页面行为不变）；业务页面传入 workflow_base()。
    """
    anonymous = is_anonymous()
    base = current_base() if base is None else base
    user = request.env.user
    perms = {} if anonymous else permissions()
    # /api/team/session 与 body 配置必须同一套权限位，避免导航与接口判定打架
    workflow_perms = {} if anonymous else workflow_permissions()
    ctx = {
        'lc_base': base,
        'lc_anonymous': anonymous,
        'lc_page_title': page_title,
        'lc_active_page': active_page,
        'lc_site_title': site_title(),
        'lc_user_name': '' if anonymous else (user.name or user.login or ''),
        'lc_user_login': '' if anonymous else (user.login or ''),
        'lc_csrf_token': request.csrf_token(),
        'lc_permissions': perms,
        'lc_workflow_permissions': workflow_perms,
        'lc_login_url': login_url(base, _request_next()),
        # 站内相对路径 + 尊重当前基址：/team/** 下是 /team/logout，管理 Host 根级是 /logout。
        # 不能写绝对 URL（不能带 scheme/host）：绝对 URL 由代理层推导时会丢非标准端口。
        'lc_logout_url': logout_url(base),
        'lc_welcome_url': (base + '/') if base else '/',
        'lc_lab_url': base + '/lab',
        'lc_nav': workflow_nav(base, workflow_perms, active_page, anonymous),
        'lc_entry_urls': workflow_urls(base),
        # 业务页面元信息：旧页面（欢迎/登录/仓库/详情）也必须有默认值，
        # 否则 layout 里的条件表达式会读到未定义变量。
        'lc_page_id': '',
        'lc_page_desc': '',
        'lc_domain': '',
        'lc_domain_css_v': '0',
        'lc_page_js_v': '0',
        'lc_query': {},
        'lc_workflow_limits': WORKFLOW_LIMITS,
        'lc_workflow_config_json': json.dumps(
            workflow_config(base, workflow_perms, active_page, '', anonymous),
            ensure_ascii=True, sort_keys=True, separators=(',', ':')),
        'lc_version': '19.0.1.1.0',
        # 静态资源版本：内容哈希，文件一变 URL 就变，无需用户手动清缓存
        'lc_css_v': asset_version('static/src/css/team.css'),
        'lc_js_v': asset_version('static/src/js/team.js'),
        'lc_core_v': asset_version('static/src/js/workflow_core.js'),
        'lc_lang': (getattr(request.env, 'lang', None) or 'zh_CN').replace('_', '-'),
        'lc_entries': site_entries(base, anonymous, workflow_perms),
        # 模板里直接用 format_qty(...) 渲染数量，避免在 QWeb 里写格式化逻辑
        'format_qty': format_quantity,
    }
    if extra:
        ctx.update(extra)
    return ctx


def workflow_context(page_id, title, description='', domain='', query=None,
                     extra=None, nav_page=None):
    """业务页面上下文：外壳 + 页面元信息 + 各子任务模板需要的插槽变量。

    nav_page：导航高亮项（/lab/bags/<id> 这类子页复用父页的高亮）。
    """
    base = workflow_base()
    anonymous = is_anonymous()
    perms = {} if anonymous else workflow_permissions()
    page_meta = WORKFLOW_PAGES.get(page_id) or (title, '')
    config = workflow_config(base, perms, page_id, domain, anonymous)
    ctx = shell_context(page_meta[0] or title, base=base,
                        active_page=nav_page or page_id)
    ctx.update({
        'lc_page_id': page_id,
        'lc_page_title': title or page_meta[0],
        'lc_page_desc': description,
        'lc_domain': domain,
        'lc_query': query or {},
        'lc_workflow_config_json': json.dumps(
            config, ensure_ascii=True, sort_keys=True, separators=(',', ':')),
        # 各 domain 的静态资源版本（文件不存在时为 '0'，模板据此决定是否输出标签）
        'lc_domain_css_v': asset_version('static/src/css/workflow_%s.css' % domain)
        if domain else '0',
        'lc_page_js_v': asset_version('static/src/js/pages/%s.js' % page_id),
        'lc_workflow_limits': WORKFLOW_LIMITS,
    })
    if extra:
        ctx.update(extra)
    return ctx


def template_exists(template_key):
    """该 QWeb 模板是否已登记（子任务未落地时回退到占位页）。"""
    try:
        return bool(request.env['ir.ui.view'].sudo().search_count(
            [('key', '=', template_key)]))
    except Exception:
        _logger.warning('lab_team_web: 检查模板 %s 失败', template_key, exc_info=True)
        return False


def site_entries(base, anonymous, perms):
    """欢迎页入口清单（按权限渲染，不再出现"暂未开放"占位）。"""
    entries = []
    urls = workflow_urls(base)
    if anonymous:
        entries.append({
            'title': '登录',
            'href': login_url(base, urls['lab']),
            'desc': '使用实验室系统账号登录后进入仓库检索与库存作业。',
            'state': 'available',
        })
        return entries

    if perms.get('can_catalog'):
        entries.append({
            'title': '器件资料', 'href': urls['lab'],
            'desc': '按分类或关键词查找器件，查看参数、实验室库存与存放位置。',
            'state': 'available',
        })
    else:
        entries.append({
            'title': '器件资料', 'href': '', 'desc': '当前账号没有器件资料查看权限。',
            'state': 'denied',
        })

    if perms.get('can_lab'):
        entries.append({
            'title': '采购入库', 'href': urls['receipts'], 'state': 'available',
            'desc': '先建待入库袋并打印追溯标签，再扫码确认实物入库；确认前不增加库存。',
        })
        entries.append({
            'title': '领用与归还', 'href': urls['issues'], 'state': 'available',
            'desc': '扫码按袋领用，归还必须关联原领用行；未归还数量由系统计算。',
        })
        entries.append({
            'title': '库位与作业流水', 'href': urls['locations'], 'state': 'available',
            'desc': '查看库位与库码、扫描记录与每次入库/领用/归还的操作人。',
        })
        entries.append({
            'title': '扫码', 'href': urls['scan'], 'state': 'available',
            'desc': '扫袋追溯码、库位库码或器件编号，按扫码结果进入对应操作。',
        })
    else:
        entries.append({
            'title': '库存作业', 'href': '', 'state': 'denied',
            'desc': '当前账号没有实验室库存权限，入库、领用、归还与标签不可用。',
        })

    if perms.get('can_manage_labels'):
        entries.append({
            'title': '标签中心', 'href': urls['labels'], 'state': 'available',
            'desc': '按毫米尺寸批量排版 A4 标签，每袋一个追溯二维码、库位另用库码。',
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


def render_denied(status=403, reason='forbidden', base=None, active_page=''):
    """403 无权限 / 404 不存在 / 400 标识非法 三种状态各有独立文案。

    reason 命中 WORKFLOW_DENIED_TEXT 时用更具体的说明（例如"仅库存管理员可用"），
    未命中则沿用通用文案，保持旧页面行为不变。
    """
    if status == 400:
        code, title = 'INVALID_REQUEST', '器件标识不合法'
    elif status == 404:
        code, title = 'NOT_FOUND', '页面不存在'
    else:
        code, title = 'FORBIDDEN', '没有访问权限'
    denied_title, denied_lead = WORKFLOW_DENIED_TEXT.get(reason, ('', ''))
    ctx = shell_context(title, {
        'lc_reason': reason,
        'lc_denied_code': code,
        'lc_denied_status': status,
        'lc_denied_title': denied_title,
        'lc_denied_lead': denied_lead,
    }, base=base, active_page=active_page)
    return render('lab_team_web.page_denied', ctx, status=status)


def render_workflow(template_key, ctx):
    """渲染业务页面；子任务的模板还没落地时回退到统一占位页。

    这样 T0 可以先注册全部路由、导航与会话态，三路 UI 子任务随后只新增自己的
    views/workflow_*.xml，不需要改控制器（避免并行抢同一文件）。
    """
    if template_exists(template_key):
        return render(template_key, ctx)
    return render('lab_team_web.workflow_placeholder', ctx)


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
