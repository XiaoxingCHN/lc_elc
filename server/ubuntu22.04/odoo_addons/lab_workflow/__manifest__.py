# -*- coding: utf-8 -*-
{
    'name': '实验室库存作业与追溯 (Lab Workflow)',
    'version': '19.0.2.0.0',
    'category': 'Inventory/Inventory',
    'summary': '物料/库位/袋追溯码、扫码入库领用归还、A4 批量标签、JSON-RPC 业务接口',
    'description': """
实验室库存作业与追溯
====================

依赖 lab_catalog（统一器件库/目录索引）与 lab_inventory（立创资料字段 lab_sn 等），
在其之上实现真实库存业务：

* 每个物理袋/批次一个追溯码（LABB:xxxx），对应一个真实 stock.lot + stock.quant
* 每个库位一个库码（LABL:xxxx）
* 入库 / 领用 / 归还全部走 Odoo 原生 stock.move + stock.move.line + stock.quant
* 领用人必须是已建立的系统账号（res.users），操作人始终取 env.uid，分别保存
* 归还必须关联原领料记录，且不得超过未归还数量
* request_key + 用户 + 公司唯一 + payload 指纹，保证重试不重复记账
* A4 标签 PDF（reportlab + 矢量二维码，中文字体逐个字形实测校验）
* 网页端表单、扫码操作台、领用记录入口
    """,
    'author': 'Lab',
    'license': 'LGPL-3',
    'depends': ['lab_catalog', 'lab_inventory', 'stock'],
    'external_dependencies': {
        'python': ['reportlab'],
    },
    'data': [
        'security/lab_workflow_groups.xml',
        'security/lab_workflow_imply.xml',
        'security/ir.model.access.csv',
        'security/lab_workflow_rules.xml',
        'data/lab_workflow_data.xml',
        # 标签向导/动作先加载：lab_bag_views 里的按钮要引用 action_lab_label_open
        'views/lab_label_views.xml',
        'views/lab_location_views.xml',
        'views/lab_bag_views.xml',
        'views/lab_operation_views.xml',
        'views/lab_issue_views.xml',
        'views/lab_return_wizard_views.xml',
        'views/lab_scan_views.xml',
        'views/lab_request_log_views.xml',
        'views/menu.xml',
        'views/lab_user_access_views.xml',
    ],
    'assets': {
        'web.assets_backend': ['lab_workflow/static/src/user_access/lab_user_group_ids.js'],
    },
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'auto_install': False,
}
