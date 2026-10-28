# -*- coding: utf-8 -*-
{
    "name": "战队管理站点（仓库 Web 入口）",
    "version": "19.0.1.1.0",
    "summary": "独立于 Odoo 原生 WebClient 的战队管理前端入口：欢迎、登录、仓库检索与器件详情",
    "description": """
战队管理站点
============

自有前端外壳，地址栏使用自定义业务路径，不复用 Odoo 原生后台菜单：

* 欢迎页、登录（复用 Odoo 原生 /web/session/authenticate）、退出与回跳
* 仓库检索（分类/关键词/库存优先/游标分页）与器件详情（参数、实验室库存、袋、库位、手册）
* 只接管管理站点自身的路由；不改 website 首页/编辑器、不改原生后台、不换 lab_theme/lab_site 样式

首批只读页面（欢迎/登录/仓库/详情）已生产；P3 起在同一外壳内接入库存作业页面
（入库、领用/归还、袋追溯、库位、标签、管理、账号），页面与接口权限分别校验。

路由（页面）：/team 与根级别别名 /、/login、/logout、/lab、/lab/items/<item_key>、
/scan、/account、/lab/{receipts,bags,labels,issues,locations,location-mappings,
history,materials,settings}；根级别别名可由参数 lab_team_web.root_aliases=0 关闭
（关闭后这些根路径与旧别名一样真实 404，/team/** 不受影响）。
""",
    "author": "lc_elc",
    "license": "LGPL-3",
    "category": "Inventory/Inventory",
    "depends": ["base", "web", "lab_catalog", "lab_workflow"],
    "data": [
        "security/ir.model.access.csv",
        # 旧只读页面（欢迎/登录/仓库/详情）+ 布局（本文件由外壳任务维护）
        "views/pages.xml",
        # 业务页面公共外壳（workflow_page / 状态区 / 占位页）
        "views/team_templates.xml",
        # 各业务域的独立模板文件（写域互不重叠，见 frontend-contract.md §2）
        "views/workflow_receipt.xml",
        "views/workflow_issue.xml",
        "views/workflow_inventory.xml",
        "views/workflow_account.xml",
    ],
    "installable": True,
    "uninstall_hook": "uninstall_hook",
    "application": False,
    "auto_install": False,
}
