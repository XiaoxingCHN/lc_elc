# -*- coding: utf-8 -*-
"""升级前菜单快照（项目运维契约用，不参与模块运行）。

用法（升级 lab_team_web **之前**，在项目 venv 里）::

    python odoo-bin shell -c /etc/odoo.conf -d <DB> --no-http \
        < server/ubuntu22.04/odoo_addons/lab_team_web/tools/snapshot_menu_actions.py \
        -- <输出目录>

或在本模块 tools 目录直接::

    /opt/odoo/venv/bin/python -c "import json,odoo; ..."  # 见 README

本脚本只读：输出 12 条被改指菜单的当前 action（xmlid → 是否存在），
用于升级后比对"菜单改指是否仍指向自有页面"，也用于人工回退参考。
凭据一律从 odoo.conf 读取，脚本不打印任何连接串。
"""
import json
import os
import sys

from odoo.addons.lab_team_web.hooks import MENU_REWIRES, _action, _data, _menu


def snapshot(env):
    rows = []
    for menu_xmlid, (ours_xmlid, origin_xmlid) in sorted(MENU_REWIRES.items()):
        menu = _menu(env, menu_xmlid)
        ours = _data(env, ours_xmlid)
        ours_id = None
        if ours:
            ours_id = '%s,%d' % (ours.model, ours.res_id)
        current = None
        if menu and menu.action:
            current = '%s,%d' % (menu.action._name, menu.action.id)
        rows.append({
            'menu': menu_xmlid,
            'current_action': current,
            'expected_ours': ours_id,
            'points_to_own_page': bool(menu) and bool(ours) and current == ours_id,
            'origin_action': origin_xmlid,
            'origin_action_exists': bool(origin_xmlid) and bool(_action(env, origin_xmlid)),
        })
    return rows


def main(env, out_dir):
    rows = snapshot(env)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, 'menu-actions.json')
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump({'menus': rows}, handle, ensure_ascii=False, indent=2)
    bad = [row['menu'] for row in rows if not row['points_to_own_page']]
    print('menu-actions=%s total=%d not_own_page=%d' % (path, len(rows), len(bad)))
    for name in bad:
        print('  NOT_OWN_PAGE %s' % name)


if __name__ == '__main__':  # odoo-bin shell 里不会走这里
    out = sys.argv[1] if len(sys.argv) > 1 else 'menu-snapshot'
    main(env, out)  # noqa: F821 - odoo shell 注入的 env
