# -*- coding: utf-8 -*-
"""lab_team_web 生命周期钩子。

卸载可逆性是硬要求（方案 §2.6）：本模块用**同一 xmlid** 把 lab_inventory /
lab_workflow / lab_catalog 的菜单 action 改指到自有页面，卸载时必须能把菜单
还原成"原模块自己的 action"，同时**不覆盖用户后来做的自定义改指**。

还原依据不是运行期猜测：origin 表就是各模块源码里的 xmlid（见
views/legacy_entry_menu.xml 注释）。还原规则：

* 当前 action 是本模块的 action_legacy_*  → 写回 origin（None = 原本没有 action）
* 当前 action 已被别人改过（用户自定义 / 其它模块）→ 不动，只记日志

升级路径不受影响：origin 表是常量，不需要"升级前备份"；但项目升级工具仍应先
运行 tools/snapshot_menu_actions.py 留一份升级前快照（见 maintenance 契约）。
"""
import logging

_logger = logging.getLogger(__name__)

# menu xmlid -> (ours xmlid, origin xmlid or None)
MENU_REWIRES = {
    'lab_inventory.menu_lab_root': (
        'lab_team_web.action_legacy_catalog',
        'lab_catalog.action_lab_unified_catalog_client'),
    'lab_workflow.menu_lab_scan': (
        'lab_team_web.action_legacy_scan',
        'lab_workflow.action_lab_scan_console'),
    'lab_workflow.menu_lab_issue_line': (
        'lab_team_web.action_legacy_issues',
        'lab_workflow.action_lab_issue_line'),
    'lab_workflow.menu_lab_bag': (
        'lab_team_web.action_legacy_bags',
        'lab_workflow.action_lab_bag'),
    'lab_workflow.menu_lab_operation_list': (
        'lab_team_web.action_legacy_history',
        'lab_workflow.action_lab_operation'),
    'lab_workflow.menu_lab_location': (
        'lab_team_web.action_legacy_locations',
        'lab_workflow.action_lab_location'),
    'lab_workflow.menu_lab_labels': (
        'lab_team_web.action_legacy_labels',
        'lab_workflow.action_lab_label_open'),
    'lab_inventory.menu_lab_product': (
        'lab_team_web.action_legacy_materials',
        'lab_inventory.action_lab_product'),
    'lab_inventory.menu_lab_location': (
        'lab_team_web.action_legacy_locations',
        'lab_inventory.action_lab_location'),
    'lab_inventory.menu_lab_mapping': (
        'lab_team_web.action_legacy_mappings',
        'lab_inventory.action_lab_mapping'),
    'lab_catalog.menu_lab_unified_catalog': (
        'lab_team_web.action_legacy_catalog',
        'lab_catalog.action_lab_unified_catalog_client'),
    'lab_catalog.menu_lab_catalog_binding': (
        'lab_team_web.action_legacy_materials',
        'lab_catalog.view_lab_catalog_binding_action'),
}


def _data(env, xmlid, model=None):
    module, name = xmlid.split('.', 1)
    domain = [('module', '=', module), ('name', '=', name)]
    if model:
        domain.append(('model', '=', model))
    return env['ir.model.data'].sudo().search(domain, limit=1)


def _action(env, xmlid):
    """取 xmlid 对应 action；不存在返回空记录集（模块可能已卸载）。"""
    data = _data(env, xmlid)
    if not data:
        return env['ir.actions.actions'].browse()
    return env[data.model].sudo().browse(data.res_id).exists()


def _menu(env, xmlid):
    data = _data(env, xmlid, model='ir.ui.menu')
    if not data:
        return env['ir.ui.menu'].browse()
    return env['ir.ui.menu'].sudo().browse(data.res_id).exists()


def restore_menu_actions(env):
    """把仍是本模块改指的菜单还原成原模块 action。返回 (restored, skipped)。"""
    restored, skipped = 0, 0
    for menu_xmlid, (ours_xmlid, origin_xmlid) in MENU_REWIRES.items():
        menu = _menu(env, menu_xmlid)
        ours = _action(env, ours_xmlid)
        if not menu or not ours or menu.action != ours:
            # 菜单或本模块 action 已不可用 / 菜单已被别人改指：保留现状
            skipped += 1
            continue
        origin = _action(env, origin_xmlid) if origin_xmlid else None
        # ir.ui.menu.action 是 Reference，只接受具体动作模型（act_window/act_url/...）
        menu.write({'action': ('%s,%d' % (origin._name, origin.id)) if origin else False})
        restored += 1
    _logger.info('lab_team_web: 菜单还原 restored=%d skipped=%d', restored, skipped)
    return restored, skipped


def uninstall_hook(env):
    try:
        from . import http_patch
        http_patch.restore()
    except Exception:
        _logger.exception('lab_team_web: 卸载时还原 JSON-RPC 补丁失败')
    try:
        restore_menu_actions(env)
    except Exception:
        _logger.exception('lab_team_web: 卸载时还原菜单改指失败（请手工核对 12 条菜单）')
