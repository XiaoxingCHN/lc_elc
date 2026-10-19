{
    'name': '实验室元器件库存扩展',
    'version': '19.0.1.0.0',
    'category': 'Inventory/Inventory',
    'summary': '实验室元器件库存管理：立创编号、库位类型、BOM 分配、类别→库位映射',
    'author': 'Lab',
    'license': 'LGPL-3',
    'depends': ['stock', 'product', 'mrp'],
    'data': [
        'security/lab_inventory_groups.xml',
        'security/ir.model.access.csv',
        'views/product_views.xml',
        'views/location_views.xml',
        'views/move_views.xml',
        'views/lab_inbound_category_mapping_views.xml',
        'views/menu.xml',
        # 'views/inherited_views.xml',  # 暂不加载：其中的原生视图 xmlid
        # （product.product_template_tree_view / stock.view_move_form 等）
        # 在 Odoo 19 中已被重命名，加载会报 External ID not found。
        # 等 check_views.py 校验出正确的 xmlid 后再启用。
    ],
    'installable': True,
    'application': False,
}
