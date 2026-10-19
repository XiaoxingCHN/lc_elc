# -*- coding: utf-8 -*-
"""C 编号 <-> 本地档案 绑定。

统一身份规则（root 裁决）：
* canonical 身份只可能是 ``lcsc:<C编号>``；一张卡片可聚合**多个**本地档案（多 SN）；
* **一个本地档案最多只能属于一个有效 C 绑定** —— 否则同一个 SN 会同时出现在两张
  卡片上，身份就分裂了；
* 已有规范 C 的档案不能被改绑到**另一个** C（历史 SN 不许被随意覆盖）；
* 校验必须放在**模型边界**：``lab.catalog.binding`` 的 create/write 都会被
  ``/web/dataset/call_kw`` 或 XML-RPC 直接调用，不能只靠控制器。

数据库层再加一个唯一索引兜底（并发/绕过 ORM 时也不会产生重复绑定）。
"""
import logging

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError

_logger = logging.getLogger(__name__)

MARKET_CN = 'cn'


class LabBindingConflict(ValidationError):
    """绑定冲突：控制器负责转成 CONFLICT 信封。"""


class LabCatalogBinding(models.Model):
    _name = 'lab.catalog.binding'
    _description = '器件资料 <-> 本地档案绑定'
    _order = 'catalog_code, id'

    catalog_code = fields.Char(string='C 编号', required=True, index=True)
    product_template_id = fields.Many2one('product.template', string='本地档案',
                                          required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one('res.company', string='公司', required=True,
                                 index=True, default=lambda self: self.env.company)
    active = fields.Boolean(string='有效', default=True)
    source = fields.Char(string='来源')
    note = fields.Char(string='备注')

    # 声明式唯一约束（Odoo 19 的 models.Constraint，替代已废弃的 _sql_constraints）。
    # 由 Odoo 在**本模型自己的** _auto_init 里创建 —— 那时 product_template_id 列已经存在，
    # 不会出现"列还没建就抢跑建索引"的 SQL ERROR（早期版本的教训）。
    # 语义：一个本地档案最多一个 C 绑定；多个档案 -> 同一个 C 仍然允许。
    _tmpl_uniq = models.Constraint(
        'UNIQUE (product_template_id)',
        '一个本地档案只能有一个 C 绑定；同一 SN 不允许同时属于两个 C 编号。',
    )

    def init(self):
        """只建**不涉及其它列**的普通索引；唯一性交给上面的声明式约束。"""
        cr = self.env.cr
        cr.execute('SAVEPOINT lc_bind_idx')
        try:
            cr.execute('CREATE INDEX IF NOT EXISTS lab_catalog_binding_code_idx '
                       'ON lab_catalog_binding (catalog_code)')
            cr.execute('RELEASE SAVEPOINT lc_bind_idx')
        except Exception as exc:
            cr.execute('ROLLBACK TO SAVEPOINT lc_bind_idx')
            _logger.warning('lab_catalog: binding code index skipped: %s', exc)

    # ------------------------------------------------ 校验（模型边界）
    @api.model
    def _norm_code(self, value):
        from .lab_catalog_identity import normalize_catalog_code
        return normalize_catalog_code(value)

    @api.model
    def _validate_binding(self, vals, exclude_id=None):
        """返回规范化后的 (code, template)。任何不一致都抛 LabBindingConflict。"""
        code = self._norm_code(vals.get('catalog_code'))
        if not code:
            raise LabBindingConflict('绑定必须带合法的 C 编号（形如 C123456）。')
        tid = vals.get('product_template_id')
        if not tid:
            raise LabBindingConflict('绑定必须指定本地档案。')
        tmpl = self.env['product.template'].browse(int(tid)).exists()
        if not tmpl:
            raise LabBindingConflict('本地档案不存在或你无权访问（id=%s）。' % tid)
        # 权限/公司：ORM 记录规则会按公司过滤，这里显式再确认一次
        tmpl.check_access_rights('read')
        tmpl.check_access_rule('read')

        own = tmpl.lab_lcsc_code_norm or None
        if own and own != code:
            raise LabBindingConflict(
                '档案 %s（SN %s）已经属于 C 编号 %s，不能再绑定到 %s。'
                '同一个 SN 出现在两张卡片上会破坏统一身份。'
                % (tmpl.id, tmpl.lab_sn or '-', own, code))

        # 一个档案最多一个绑定（与声明式 UNIQUE 约束语义一致，不带 active 条件，
        # 否则 ORM 校验与 DB 约束不一致，会变成难懂的 IntegrityError）
        other = self.search([('product_template_id', '=', tmpl.id)], limit=1)
        if other and other.id != (exclude_id or 0):
            if other.catalog_code == code:
                return code, tmpl, other        # 幂等：同一档案同一 C 直接复用
            raise LabBindingConflict(
                '档案 %s 已绑定到 %s，不能再绑定到 %s。' % (tmpl.id, other.catalog_code, code))
        return code, tmpl, None

    @api.model_create_multi
    def create(self, vals_list):
        clean = []
        for vals in vals_list:
            code, tmpl, existing = self._validate_binding(vals)
            if existing:
                # 幂等：同 request 重复调用不报错、不新建
                clean.append(('existing', existing))
                continue
            v = dict(vals)
            v['catalog_code'] = code
            v['product_template_id'] = tmpl.id
            v.setdefault('company_id', tmpl.company_id.id or self.env.company.id)
            clean.append(('new', v))
        records = self.browse()
        for kind, payload in clean:
            if kind == 'existing':
                records |= payload
            else:
                records |= super(LabCatalogBinding, self).create(payload)
        # 绑定成功后刷新库存版本，供界面失效缓存。
        # 走**私有**方法：绑定是普通操作员的合法动作，不能要求 manager。
        self.env['lab.catalog.item']._touch_inventory_revision()
        return records

    def write(self, vals):
        if 'catalog_code' in vals or 'product_template_id' in vals:
            for rec in self:
                merged = {
                    'catalog_code': vals.get('catalog_code', rec.catalog_code),
                    'product_template_id': vals.get('product_template_id',
                                                    rec.product_template_id.id),
                }
                code, _tmpl, _ex = self._validate_binding(merged, exclude_id=rec.id)
                if 'catalog_code' in vals:
                    vals = dict(vals)
                    vals['catalog_code'] = code
        res = super().write(vals)
        self.env['lab.catalog.item']._touch_inventory_revision()
        return res

    @api.model
    def binding_map(self, codes):
        """一次性取多个 C 编号的绑定档案（避免 N+1）。"""
        codes = [c for c in (codes or []) if c]
        if not codes:
            return {}
        self.env.cr.execute(
            'SELECT catalog_code, product_template_id FROM lab_catalog_binding '
            'WHERE active AND catalog_code = ANY(%s)', (list(set(codes)),))
        out = {}
        for code, tid in self.env.cr.fetchall():
            out.setdefault(code, []).append(tid)
        for code in out:
            out[code] = sorted(set(out[code]))
        return out
