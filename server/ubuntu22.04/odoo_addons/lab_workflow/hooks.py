# -*- coding: utf-8 -*-
"""模块安装钩子：默认给 admin 配上实验室库存管理员，避免装完没人能配库位。"""

import logging

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """保证默认管理员拥有 lab_workflow.group_lab_manager。

    新账号的角色分配步骤（写进交付文档）：
    设置 → 用户 → 选择用户 → 「实验室库存」分组里选
    「只读 / 操作员 / 管理员」之一（三者是递进的）。
    """
    try:
        group = env.ref('lab_workflow.group_lab_manager', raise_if_not_found=False)
        admin = env.ref('base.user_admin', raise_if_not_found=False)
        if group and admin and group not in admin.group_ids:
            admin.sudo().write({'group_ids': [(4, group.id)]})
            _logger.info('lab_workflow: 已把 %s 加入「实验室库存 / 管理员」', admin.login)
    except Exception as exc:  # noqa: BLE001 - 钩子失败不应阻断安装
        _logger.warning('lab_workflow post_init_hook 未能授予管理员权限：%s', exc)
