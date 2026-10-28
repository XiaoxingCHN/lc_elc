# -*- coding: utf-8 -*-
"""``lab.location.mapping``：类别 → 推荐库位映射（配置，不是库存）。

需求背景：扫码上架时希望"同一类元器件默认推荐去过的库位"。原实现只有
``pending/resolve`` 里现算的启发式（相同器件 → 同父分类），不可配置、不可解释。

设计边界（安全/业务不变量）：

* 映射**只参与推荐排序**，绝不自动选库位、绝不写库存；确认入库仍然必须由
  操作者指定 ``location_id``，并走原 ``lab_receipt`` 的真实 stock.move。
* 不是流水：可停用、可物理删除；不做历史追溯（需要审计时另立任务）。
* 同一 ``(类别, 库位, 公司)`` 唯一；``priority`` 越小越先。
* 库位只允许 ``usage='internal'``，且跨公司隔离（记录规则）。
"""

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from ..tools import p3_rules


class LabLocationMapping(models.Model):
    _name = 'lab.location.mapping'
    _description = '实验室类别→库位推荐映射'
    _order = 'priority, id'
    _check_company_auto = True
    _rec_name = 'category_id'

    category_id = fields.Many2one(
        'product.category', string='元器件类别', required=True, index=True,
        ondelete='cascade',
        help='按产品分类匹配；父分类的映射也会作为候选（子分类优先）。')
    location_id = fields.Many2one(
        'stock.location', string='推荐库位', required=True, index=True,
        ondelete='restrict', check_company=True,
        domain="[('usage', '=', 'internal')]")
    priority = fields.Integer(
        string='优先级', default=p3_rules.DEFAULT_PRIORITY, required=True,
        help='数字越小越先推荐；同优先级按创建顺序。')
    active = fields.Boolean(string='启用', default=True)
    company_id = fields.Many2one(
        'res.company', string='公司', required=True, index=True,
        default=lambda self: self.env.company)
    note = fields.Char(string='备注', size=200)

    _mapping_uniq = models.Constraint(
        'unique(category_id, location_id, company_id)',
        '同一类别与库位的推荐映射不能重复（直接修改已有映射即可）。',
    )

    @api.constrains('location_id')
    def _check_location_usage(self):
        for mapping in self:
            if mapping.location_id and mapping.location_id.usage != 'internal':
                raise ValidationError(
                    _('推荐库位「%s」不是内部库位，不能用于类别映射。')
                    % mapping.location_id.display_name)

    @api.constrains('priority')
    def _check_priority_range(self):
        for mapping in self:
            if not (p3_rules.MIN_PRIORITY <= mapping.priority <= p3_rules.MAX_PRIORITY):
                raise ValidationError(
                    _('优先级必须在 %s..%s 之间。')
                    % (p3_rules.MIN_PRIORITY, p3_rules.MAX_PRIORITY))

    # ------------------------------------------------------------------
    def _lab_mapping_dict(self):
        self.ensure_one()
        category = self.category_id
        location = self.location_id
        return {
            'id': self.id,
            'category_id': category.id,
            'category_path': category.complete_name or category.name or '',
            'location_id': location.id,
            'location_path': location.complete_name or location.display_name,
            'location_code': location.lab_code or '',
            'priority': self.priority,
            'active': bool(self.active),
            'note': self.note or '',
        }

    # ------------------------------------------------------------------
    @api.model
    def lab_mapping_locations_for_category(self, category, limit=20):
        """给 ``pending/resolve`` 用：按 priority 取该类别（含父类别）的推荐库位。

        返回 ``[(location, mapping)]``；不做库存判断——推荐里是否"真的有库存"
        由调用方决定，避免把配置误当成库存事实。
        """
        if not category:
            return []
        categories = category
        parent = category.parent_id
        # 父链有限（Odoo 分类树通常 1~3 层），显式循环而不是递归，便于测试与限深
        depth = 0
        while parent and depth < 8:
            categories |= parent
            parent = parent.parent_id
            depth += 1
        mappings = self.search([
            ('category_id', 'in', categories.ids),
            ('company_id', '=', self.env.company.id),
            ('active', '=', True),
        ], limit=max(1, int(limit or 20)) * 4)
        # 子分类优先：类别层级更深的映射排前面，再按 priority
        def sort_key(mapping):
            return (-(mapping.category_id.parent_path or '').count('/'),
                    mapping.priority, mapping.id)
        ordered = sorted(mappings, key=sort_key)
        out = []
        seen = set()
        for mapping in ordered:
            if mapping.location_id.id in seen:
                continue
            seen.add(mapping.location_id.id)
            out.append((mapping.location_id, mapping))
            if len(out) >= int(limit or 20):
                break
        return out
