# -*- coding: utf-8 -*-
"""站点会话态接口（供前端导航/权限判断使用，只读）。

刻意很小：只回答"当前是谁、能进哪些区域、有哪些库存角色位"，不复制任何业务
接口。业务数据仍走 /lab/api/catalog/* 与 /lab/api/inventory/*。

权限位与 lab_workflow 的服务端门槛一一对应（见 frontend-contract.md §5.8）：
页面只按这些位**隐藏**入口；每个业务接口仍独立校验，前端隐藏不是权限边界。
匿名时全部 false，且不返回任何账号信息。
"""
from odoo import http
from odoo.http import request

from .common import (WORKFLOW_LIMITS, current_base, has_catalog_access,
                     has_lab_access, is_anonymous, is_lab_manager,
                     shell_context, workflow_urls)


class LabTeamSessionController(http.Controller):

    @http.route(['/team/api/session', '/api/team/session'],
                type='jsonrpc', auth='public', website=False, methods=['POST'])
    def session_info(self, **kwargs):
        anonymous = is_anonymous()
        user = request.env.user
        base = current_base()
        ctx = shell_context()
        # 与 page/body 配置同源的权限位（shell_context 已经算过一次）
        perms = ctx['lc_workflow_permissions'] or {}
        payload_perms = {
            'can_catalog': False if anonymous else has_catalog_access(),
            'can_lab': False if anonymous else has_lab_access(),
            'is_manager': False if anonymous else is_lab_manager(),
            'can_receipt': bool(perms.get('can_receipt')),
            'can_issue': bool(perms.get('can_issue')),
            'can_return': bool(perms.get('can_return')),
            'can_manage_labels': bool(perms.get('can_manage_labels')),
            'can_issue_for_others': bool(perms.get('can_issue_for_others')),
            'can_manage_locations': bool(perms.get('can_manage_locations')),
            'can_manage_mappings': bool(perms.get('can_manage_mappings')),
            'can_manage_members': bool(perms.get('can_manage_members')),
        }
        urls = workflow_urls(base)
        urls.update({
            'welcome': ctx['lc_welcome_url'],
            'login': ctx['lc_login_url'],
            'logout': ctx['lc_logout_url'],
            'lab': ctx['lc_lab_url'],
        })
        return {
            'ok': True,
            'data': {
                'authenticated': not anonymous,
                'uid': None if anonymous else user.id,
                'name': '' if anonymous else (user.name or ''),
                'login': '' if anonymous else (user.login or ''),
                'base': base,
                'company': {
                    'id': None if anonymous else request.env.company.id,
                    'name': '' if anonymous else (request.env.company.name or ''),
                },
                'permissions': payload_perms,
                'limits': dict(WORKFLOW_LIMITS),
                'urls': urls,
            },
            'error': None,
        }
