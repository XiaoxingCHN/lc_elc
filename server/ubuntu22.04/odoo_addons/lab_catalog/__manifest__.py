{
    "name": "实验室立创资料库 (LCSC catalog index)",
    "version": "19.0.2.0.5",
    "summary": "立创商城中文资料库的只读索引镜像，与实验室物料合并为一份统一器件库",
    "description": """
统一器件库（catalog side）
==========================

本模块负责把采集到的 662,768 条立创中文资料（原 components.sqlite3 快照，
**只读、不改动**）扁平化导入同一 Odoo PostgreSQL 的只读索引表，并提供：

* 统一器件库检索接口（/lab/api/catalog/*），身份恒为 ``lcsc:C123`` 或未绑定的 ``lab:42``；
* 分类树 / facets / 品牌·封装·参数组合筛选；
* 与 lab_inventory 的真实库存做**实时** quant 聚合（有库存优先排序，数量实时读取，不用陈旧快照）；
* 安全受控的来源资产缓存（不代理任意 URL，防 SSRF）。

目录导入与库存写事务分离：本模块**不写库存**。库存业务由 lab_workflow 提供。
""",
    "author": "lc_elc",
    "license": "LGPL-3",
    "category": "Inventory/Inventory",
    "depends": ["base", "web", "stock", "product", "lab_inventory"],
    "data": [
        "security/lab_catalog_security.xml",
        "security/ir.model.access.csv",
        "data/lab_catalog_data.xml",
        "views/lab_catalog_views.xml",
        "views/lab_catalog_menu.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "lab_catalog/static/src/css/lc_theme_dark.css",
            "lab_catalog/static/src/unified/**/*.js",
            "lab_catalog/static/src/unified/**/*.xml",
            "lab_catalog/static/src/unified/**/*.scss",
        ],
    },
    "installable": True,
    "application": True,
    "auto_install": False,
    "post_init_hook": "post_init_hook",
}
