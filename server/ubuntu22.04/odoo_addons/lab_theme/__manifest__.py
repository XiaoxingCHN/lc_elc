# -*- coding: utf-8 -*-
{
    "name": "力创暗色主题",
    "version": "19.0.1.0.2",
    "summary": "全局暗色科技风主题，与官网 l-creation.club 风格统一",
    "description": """
力创实验室全局暗色主题
======================

将整个 Odoo 界面改为与官网 l-creation.club 一致的暗色科技风格。

* 深黑背景 (#070809) + 荧光绿强调色 (#c9ff3f)
* 覆盖后端后台、登录页与前台
* 高对比度文字，确保可读性

本模块通过 assets 全局加载，后端包中 prepend 优先级最高。
""",
    "author": "lc_elc",
    "license": "LGPL-3",
    "category": "Themes/Backend",
    "depends": ["web"],
    "data": [
        "security/ir.model.access.csv",
    ],
    "assets": {
        "web.assets_backend": [
            ("prepend", "lab_theme/static/src/css/global_dark_theme.css"),
        ],
        "web.assets_frontend": [
            ("prepend", "lab_theme/static/src/css/global_dark_theme.css"),
        ],
        "web.assets_frontend_minimal": [
            ("prepend", "lab_theme/static/src/css/global_dark_theme.css"),
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
