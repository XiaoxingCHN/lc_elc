# -*- coding: utf-8 -*-
{
    "name": "战队管理站点（仓库 Web 入口）",
    "version": "19.0.1.0.0",
    "summary": "独立于 Odoo 原生 WebClient 的战队管理前端入口：欢迎、登录、仓库检索与器件详情",
    "description": """
战队管理站点
============

自有前端外壳，地址栏使用自定义业务路径，不复用 Odoo 原生后台菜单：

* 欢迎页、登录（复用 Odoo 原生 /web/session/authenticate）、退出与回跳
* 仓库检索（分类/关键词/库存优先/游标分页）与器件详情（参数、实验室库存、袋、库位、手册）
* 只接管管理站点自身的路由；不改 website 首页/编辑器、不改原生后台、不换 lab_theme/lab_site 样式

首批为**只读**流程：未实现的采购入库、领用归还等操作不在页面上呈现为可执行。

路由（默认）：/team、/team/login、/team/lab、/team/lab/items/<item_key>
根级别别名（可由参数 lab_team_web.root_aliases=0 关闭）：/login、/lab、/lab/items/<item_key>
""",
    "author": "lc_elc",
    "license": "LGPL-3",
    "category": "Inventory/Inventory",
    "depends": ["base", "web", "lab_catalog", "lab_workflow"],
    "data": [
        "security/ir.model.access.csv",
        "views/pages.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
