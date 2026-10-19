# -*- coding: utf-8 -*-
"""立创商城分类树。

外部 ID 语义（root 复核后统一）
------------------------------
* ``id`` / ``category_id`` / ``parent_id`` 一律返回 **Odoo(PG) id**，前端点击时原样回传；
* 商城自己的分类号另以 ``catalog_id`` 字段返回，仅作展示/对照；
* 下级匹配用**完整祖先路径**（PG id 路径，见 lab_catalog_item.category_path），
  而不是只匹配 ``/cid/`` 前缀，避免"点父类漏子类"。
"""
from odoo import api, fields, models


class LabCatalogCategory(models.Model):
    _name = 'lab.catalog.category'
    _description = '立创商城分类'
    _order = 'catalog_id'
    _rec_name = 'name'

    catalog_id = fields.Integer(string='商城分类 ID', required=True, index=True)
    parent_id = fields.Many2one('lab.catalog.category', string='上级',
                                ondelete='set null', index=True)
    child_ids = fields.One2many('lab.catalog.category', 'parent_id', string='下级')
    code = fields.Char(string='分类编码', index=True)
    name = fields.Char(string='分类名称', required=True, index=True)
    name_en = fields.Char(string='英文名')
    level = fields.Integer(string='层级', index=True)
    sort = fields.Integer(string='排序')
    product_count = fields.Integer(string='商城商品数')
    pg_path = fields.Char(string='祖先路径(PG id)', index=True,
                          help='形如 /3/12/45/，用 PG id 组成，供"含下级"筛选')

    # **不存储**：分类是导入工具用 SQL 灌进来的，不会触发 computed 重算
    # （实测 56 个有子节点的分类 store 值全为 False）。改为读取时按 child_ids 实时计算，
    # 保证界面上的"真树"与实际层级一致。
    has_children = fields.Boolean(string='有下级', compute='_compute_has_children')

    @api.depends('child_ids')
    def _compute_has_children(self):
        for rec in self:
            rec.has_children = bool(rec.child_ids)

    @api.model
    def path_of(self, category):
        """由 PG 记录计算祖先路径 /a/b/c/。"""
        chain, seen = [], set()
        cur = category
        while cur and cur.id not in seen:
            seen.add(cur.id)
            chain.append(str(cur.id))
            cur = cur.parent_id
        chain.reverse()
        return '/' + '/'.join(chain) + '/' if chain else ''

    def _compute_pg_path(self):
        for rec in self:
            rec.pg_path = self.path_of(rec)

    @api.model
    def rebuild_paths(self):
        """导入后调用：把 pg_path 刷成 PG id 祖先路径（供 search 的含下级筛选）。"""
        for rec in self.search([]):
            rec.pg_path = self.path_of(rec)
        return True
