# -*- coding: utf-8 -*-
"""业务页面路由（P3 外壳）：只负责"地址 + 权限 + 上下文 + 模板选择"。

分工（重要）
------------
本文件由外壳任务维护，**业务界面不写在这里**：

* 入库 / 扫码 / 袋追溯 / 标签 的界面在 views/workflow_receipt.xml
  与被调用的 static/src/js/pages/{receipts,scan,bags,bag,labels}.js；
* 领用 / 归还 / 记录 在 views/workflow_issue.xml 与 pages/{issue_new,issues}.js；
* 库位 / 类别映射 / 管理 在 views/workflow_inventory.xml 与
  pages/{locations,mappings,settings}.js。

子任务的模板还没落地时回退到 lab_team_web.workflow_placeholder，路由与会话态
依然可用，便于先做联调、后做界面。

约束
----
* 全部 `auth='public'` + 显式判定：匿名 303 到**本站** /login（不跳原生 /web/login）。
* 页面只读渲染，写操作一律走既有 JSON-RPC（唯一例外是标签 PDF 的 POST 直出）。
* 每个页面都要求对应角色，服务端判定；前端隐藏入口不是权限边界。
* 未知重定向防护：本文件不接收 next，也不读任意 URL 参数来做跳转。
"""

import logging

from odoo import http
from odoo.http import request

from .common import (has_catalog_access, has_lab_access, is_anonymous,
                     is_lab_manager, redirect_to_login, render_denied,
                     render_workflow, workflow_base, workflow_context,
                     workflow_root_denied)

_logger = logging.getLogger(__name__)

#: 查询串白名单长度（页面只把 ?q=&tab=&raw= 之类当作初始值，不做 SQL/模板拼接）
QUERY_VALUE_LIMIT = 200

#: page_id -> 页面规格
#:   title/desc  : 页面标题与说明（页面头与 <title>）
#:   domain      : 负责该页面的子任务域（决定 CSS/JS 资源名）
#:   template    : 子任务应实现的 QWeb 模板 id（未实现时走占位页）
#:   need        : 'lab' | 'manager' | 'catalog' | 'user'
#:   nav_page    : 导航高亮项（缺省同 page_id）
PAGE_SPECS = {
    'receipts': {
        'title': '采购入库',
        'desc': '先建待入库袋并打印追溯标签，再扫码确认实物入库；确认前不增加库存。',
        'domain': 'receipt',
        'template': 'lab_team_web.workflow_receipt_receipts',
        'need': 'lab',
    },
    'scan': {
        'title': '扫码',
        'desc': '扫袋追溯码（LABB:）、库位库码（LABL:）、物料 SN 或立创编号，按结果进入对应操作。',
        'domain': 'receipt',
        'template': 'lab_team_web.workflow_receipt_scan',
        'need': 'lab',
    },
    'bags': {
        'title': '实物袋',
        'desc': '按袋追溯：追溯码、器件、库位、在库与未归还数量、每次作业的操作人。',
        'domain': 'receipt',
        'template': 'lab_team_web.workflow_receipt_bags',
        'need': 'lab',
    },
    'bag': {
        'title': '袋追溯',
        'desc': '单个实物袋的完整追溯：标签事实、作业流水与未归还领用。',
        'domain': 'receipt',
        'template': 'lab_team_web.workflow_receipt_bag_detail',
        'need': 'lab',
        'nav_page': 'bags',
    },
    'labels': {
        'title': '标签中心',
        'desc': '按毫米尺寸批量排版 A4 标签；每袋一个追溯二维码，库位另用库码。',
        'domain': 'receipt',
        'template': 'lab_team_web.workflow_receipt_labels',
        'need': 'lab',
    },
    'issue_new': {
        'title': '领用',
        'desc': '扫码或选袋领用，领用人必须是系统账号；一次最多 100 条明细。',
        'domain': 'issue',
        'template': 'lab_team_web.workflow_issue_new',
        'need': 'lab',
    },
    'issues': {
        'title': '领用记录',
        'desc': '查看领用与归还记录，按原领用行归还；未归还数量由服务端计算。',
        'domain': 'issue',
        'template': 'lab_team_web.workflow_issue_issues',
        'need': 'lab',
    },
    'locations': {
        'title': '库位',
        'desc': '内部库位与库码；新建、改名、停用与库位标签（仅管理员可写）。',
        'domain': 'inventory',
        'template': 'lab_team_web.workflow_inventory_locations',
        'need': 'lab',
    },
    'mappings': {
        'title': '类别映射',
        'desc': '类别到库位的推荐映射，只影响扫码上架时的库位推荐顺序，不自动入库。',
        'domain': 'inventory',
        'template': 'lab_team_web.workflow_inventory_mappings',
        'need': 'manager',
    },
    'settings': {
        'title': '管理',
        'desc': '仓库成员角色与项目参数；不提供数据库、模块或系统管理员权限管理。',
        'domain': 'inventory',
        'template': 'lab_team_web.workflow_inventory_settings',
        'need': 'manager',
    },
    'history': {
        'title': '作业流水',
        'desc': '每次入库、领用、归还的操作人、袋、数量与来源/目标库位。',
        'domain': 'issue',
        'template': 'lab_team_web.workflow_issue_history',
        'need': 'lab',
    },
    'materials': {
        'title': '器件档案',
        'desc': '本地档案与立创编号的绑定关系；不暴露通用 ORM 入口。',
        'domain': 'inventory',
        'template': 'lab_team_web.workflow_inventory_materials',
        'need': 'catalog',
    },
    'account': {
        'title': '我的账号',
        'desc': '当前登录账号、角色与会话状态；密码变更走管理员复位或原生流程。',
        'domain': 'account',
        'template': 'lab_team_web.workflow_account_page',
        'need': 'user',
    },
}


def guard_page(need):
    """页面级门槛：返回 None 放行，否则返回直接返回的响应。"""
    base = workflow_base()
    if is_anonymous():
        return redirect_to_login()
    if need == 'lab' and not has_lab_access():
        return render_denied(403, 'no_lab_role', base=base)
    if need == 'manager' and not is_lab_manager():
        return render_denied(403, 'manager_only', base=base)
    if need == 'catalog' and not has_catalog_access():
        return render_denied(403, 'no_catalog_role', base=base)
    return None


def clean_query(kwargs):
    """把查询串收敛成 {str: str}：只保留简单标识符键，值截断。

    页面把 ?q=&tab=&raw=&item_key= 当作初始值回填；不参与 SQL，也不拼 HTML。
    """
    out = {}
    for key, value in (kwargs or {}).items():
        if not isinstance(key, str) or not key.isidentifier() or key.startswith('_'):
            continue
        if isinstance(value, str):
            out[key] = value[:QUERY_VALUE_LIMIT]
        elif isinstance(value, int) and not isinstance(value, bool):
            out[key] = str(value)
    return out


class LabTeamWorkflowPages(http.Controller):
    """业务页面路由。每个方法只做 `_render`；界面在子任务模板里。"""

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _page(self, page_id, kwargs=None, extra=None):
        if workflow_root_denied():
            return request.not_found()
        spec = PAGE_SPECS[page_id]
        blocked = guard_page(spec['need'])
        if blocked is not None:
            return blocked
        query = clean_query(kwargs)
        ctx = workflow_context(
            page_id, spec['title'], spec['desc'], spec['domain'],
            query=query, extra=extra, nav_page=spec.get('nav_page'))
        return render_workflow(spec['template'], ctx)

    # ------------------------------------------------------------------
    # 入库 / 扫码 / 袋 / 标签（receipt 子任务）
    # ------------------------------------------------------------------
    @http.route(['/team/lab/receipts', '/lab/receipts'],
                type='http', auth='public', website=False, sitemap=False)
    def receipts(self, **kwargs):
        return self._page('receipts', kwargs)

    # 旧 /lab/scan 由 lab_workflow 一侧 303 到这里（不在本模块重复注册旧路径）。
    @http.route(['/team/scan', '/scan'],
                type='http', auth='public', website=False, sitemap=False)
    def scan(self, **kwargs):
        query = clean_query(kwargs)
        raw = query.get('raw') or query.get('scan') or ''
        return self._page('scan', kwargs, extra={'lc_scan_raw': raw})

    @http.route(['/team/lab/bags', '/lab/bags'],
                type='http', auth='public', website=False, sitemap=False)
    def bags(self, **kwargs):
        return self._page('bags', kwargs)

    @http.route(['/team/lab/bags/<int:bag_id>', '/lab/bags/<int:bag_id>'],
                type='http', auth='public', website=False, sitemap=False)
    def bag_detail(self, bag_id, **kwargs):
        if not bag_id or bag_id < 1:
            # 非法 id 与"不存在"同一表现，避免用 400 页面冒充业务错误。
            return render_denied(404, 'bag_not_found', base=workflow_base())
        return self._page('bag', kwargs, extra={'lc_bag_id': int(bag_id)})

    @http.route(['/team/lab/labels', '/lab/labels'],
                type='http', auth='public', website=False, sitemap=False)
    def labels(self, **kwargs):
        return self._page('labels', kwargs)

    # ------------------------------------------------------------------
    # 领用 / 归还 / 流水（issue 子任务）
    # ------------------------------------------------------------------
    @http.route(['/team/lab/issues/new', '/lab/issues/new'],
                type='http', auth='public', website=False, sitemap=False)
    def issue_new(self, **kwargs):
        query = clean_query(kwargs)
        return self._page('issue_new', kwargs, extra={
            'lc_prefill_bag': query.get('bag_id') or '',
            'lc_prefill_item': query.get('item_key') or '',
        })

    @http.route(['/team/lab/issues', '/lab/issues'],
                type='http', auth='public', website=False, sitemap=False)
    def issues(self, **kwargs):
        return self._page('issues', kwargs)

    @http.route(['/team/lab/history', '/lab/history'],
                type='http', auth='public', website=False, sitemap=False)
    def history(self, **kwargs):
        return self._page('history', kwargs)

    # ------------------------------------------------------------------
    # 库位 / 映射 / 管理 / 档案（inventory 子任务）
    # ------------------------------------------------------------------
    @http.route(['/team/lab/locations', '/lab/locations'],
                type='http', auth='public', website=False, sitemap=False)
    def locations(self, **kwargs):
        return self._page('locations', kwargs)

    @http.route(['/team/lab/location-mappings', '/lab/location-mappings'],
                type='http', auth='public', website=False, sitemap=False)
    def mappings(self, **kwargs):
        return self._page('mappings', kwargs)

    @http.route(['/team/lab/settings', '/lab/settings'],
                type='http', auth='public', website=False, sitemap=False)
    def settings(self, **kwargs):
        return self._page('settings', kwargs)

    @http.route(['/team/lab/materials', '/lab/materials'],
                type='http', auth='public', website=False, sitemap=False)
    def materials(self, **kwargs):
        return self._page('materials', kwargs)

    # ------------------------------------------------------------------
    # 账号（任意已登录账号）
    # ------------------------------------------------------------------
    @http.route(['/team/account', '/account'],
                type='http', auth='public', website=False, sitemap=False)
    def account(self, **kwargs):
        return self._page('account', kwargs)
