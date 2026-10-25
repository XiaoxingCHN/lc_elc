# -*- coding: utf-8 -*-
"""站点会话态接口（供前端导航/权限判断使用，只读）。

刻意很小：只回答"当前是谁、能进哪些区域"，不复制任何业务接口。
业务数据仍走 /lab/api/catalog/* 与 /lab/api/inventory/*。
"""
from odoo import http
from odoo.http import request

from .common import (current_base, has_catalog_access, has_lab_access,
                     is_anonymous, is_lab_manager, shell_context)


class LabTeamSessionController(http.Controller):

    @http.route(['/team/api/session', '/api/team/session'],
                type='jsonrpc', auth='public', website=False, methods=['POST'])
    def session_info(self, **kwargs):
        anonymous = is_anonymous()
        user = request.env.user
        base = current_base()
        ctx = shell_context()
        return {
            'ok': True,
            'data': {
                'authenticated': not anonymous,
                'uid': None if anonymous else user.id,
                'name': '' if anonymous else (user.name or ''),
                'login': '' if anonymous else (user.login or ''),
                'base': base,
                'permissions': {
                    'can_catalog': False if anonymous else has_catalog_access(),
                    'can_lab': False if anonymous else has_lab_access(),
                    'is_manager': False if anonymous else is_lab_manager(),
                },
                'urls': {
                    'welcome': ctx['lc_welcome_url'],
                    'login': ctx['lc_login_url'],
                    'logout': ctx['lc_logout_url'],
                    'lab': ctx['lc_lab_url'],
                },
            },
            'error': None,
        }
