# -*- coding: utf-8 -*-
{
    "name": "力创战队官网首页",
    "version": "19.0.1.0.0",
    "summary": "用 l-creation.club 静态站替换 Odoo 网站首页",
    "description": """
力创战队官网首页
================

用 l-creation.club 的静态页面替换 Odoo 网站的默认首页（原默认模板
"您的旅程从这里开始"）。

* 保留 #wrap.oe_structure，网站编辑器仍可进入
* 本页隐藏 Odoo 站点页眉/页脚，铺满视口
* 站点自有 CSS/JS 仅在本页按需加载，不影响其它 Odoo 页面
""",
    "author": "lc_elc",
    "license": "LGPL-3",
    "category": "Website",
    "depends": ["website"],
    "data": [
        "views/homepage.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
