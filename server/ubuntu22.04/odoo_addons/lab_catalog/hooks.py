# -*- coding: utf-8 -*-
"""安装后钩子：给管理员做**一次性**初始授权。

为什么不用公开的模型方法：Odoo 的公开 ``@api.model`` 方法可以被任意已登录用户
通过 ``/web/dataset/call_kw`` 或 XML-RPC 直接调用。原先的
``grant_catalog_role`` 内部 ``sudo()`` 加组且**没有管理员校验**，等于任何登录用户
都能给自己提权。因此初始授权放在安装钩子里（不经 RPC），
运行期只保留带管理员校验的窄接口。
"""
import logging

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """把器件库读取角色授予系统管理员。

    普通内部账号**不会**自动获得该角色——管理员必须按人分配
    ``lab_catalog.group_lab_catalog_user``（继承 base.group_user 会导致无法单独收回）。
    """
    group = env.ref('lab_catalog.group_lab_catalog_user', raise_if_not_found=False)
    if not group:
        _logger.warning('lab_catalog: group_lab_catalog_user not found; skip grant')
        return
    admin = env.ref('base.user_admin', raise_if_not_found=False)
    if not admin:
        return
    # Odoo 19 的 res.groups **没有 users 字段**（写它报 Invalid field 'users'）。
    # 必须从 user 一侧写 Many2many；字段名在 19 是 group_ids（旧版是 groups_id）。
    field = 'group_ids' if 'group_ids' in admin._fields else 'groups_id'
    admin.sudo().write({field: [(4, group.id)]})
    _logger.info('lab_catalog: granted catalog role to %s via %s', admin.login, field)
