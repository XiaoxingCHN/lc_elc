# -*- coding: utf-8 -*-
"""统一器件库：立创资料索引 + 本地物料（含无 C 码与"有码但未采集"），同一次分页。

root 两轮复核后修正的要点
------------------------
1. ``init()`` 用 SAVEPOINT 建索引，**绝不 rollback 整个安装事务**。
2. 库存只统计 ``location_id.usage = 'internal'`` 的 quant（虚拟位置不计）。
3. **不写全局共享库存信号**。排序 / ``stock_only`` 用每次请求实时计算、
   经 ORM（公司规则 + ACL）得到的"当前用户可见的有库存 C 码集合"；
   **按 C 聚合净数量 > 0** 才算有库存（不是"任一模板为正"）。
4. keyset 与排序方向一致；``stock_only`` 与 cursorkey 用 ``AND`` 拼接，**不再出现两个 WHERE**。
5. **未绑定本地物料（``lab:<id>``）同列分页**，并遵守品牌/封装筛选；
   类别/参数筛选生效时本地物料无该维度，直接排除（避免出现无关本地件）。
6. 命中"本地 SN / 名称"的查询会**带入其绑定的 C 码卡片**。
7. **有合法 C 码但索引里没有的本地物料不会消失**：以 canonical ``lcsc:<code>`` 键
   合成一张"仅本地"卡片，且不会与已存在的同码卡片重复。
8. 走原生 SQL 前**显式检查模型读取权限**（``auth='user'`` 不等于可以读资料模型）。
9. 原快照 SQLite 只读；请求里不解析 JSON、不解压 gzip。
"""
import base64
import io
import json
import logging

from odoo import api, fields, models
from odoo.exceptions import AccessError

from .lab_catalog_identity import normalize_catalog_code

_logger = logging.getLogger(__name__)
_log = _logger

# 可失效的 facets 缓存：key 含完整筛选组合 + 目录/库存版本，
# 任何导入或绑定都会 bump 版本 -> 自动失效。全库实测约 8.7s，缓存后重访为毫秒级。
_FACETS_CACHE = {}
_FACETS_CACHE_MAX = 64

MARKET_CN = 'cn'


def _copy_escape(value):
    """COPY ... FROM STDIN (text) 的正确转义。"""
    if value is None or value is False:
        return '\\N'
    if value is True:
        return 't'
    s = str(value)
    return (s.replace('\\', '\\\\').replace('\t', '\\t')
             .replace('\n', '\\n').replace('\r', '\\r'))


class LabCatalogItem(models.Model):
    _name = 'lab.catalog.item'
    _description = '立创中文资料库索引'
    _order = 'catalog_code asc'
    _rec_name = 'catalog_code'

    catalog_code = fields.Char(string='C 编号', required=True, index=True, copy=False)
    market = fields.Char(string='站点', default=MARKET_CN, required=True, index=True)
    product_id_ext = fields.Char(string='商城商品 ID', index=True)
    source_url = fields.Char(string='来源链接')

    name = fields.Char(string='名称', index=True)
    mpn = fields.Char(string='型号 (MPN)', index=True)
    brand = fields.Char(string='品牌', index=True)
    brand_code = fields.Char(string='品牌代码', index=True)
    package = fields.Char(string='封装', index=True)
    category_id = fields.Many2one('lab.catalog.category', string='分类',
                                  ondelete='set null', index=True)
    category_name = fields.Char(string='分类名', index=True)
    category_path = fields.Char(string='分类路径', index=True)

    catalog_stock = fields.Integer(string='商城现货', help='商城数据，绝不参与实验室库存计算')
    price = fields.Float(string='商城价格', digits=(16, 6))
    currency = fields.Char(string='币种')
    price_basis = fields.Char(string='价格口径')

    image_url = fields.Char(string='图片地址')
    has_image = fields.Boolean(string='有图', index=True, default=False)
    datasheet_url = fields.Char(string='数据手册')
    has_datasheet = fields.Boolean(string='有手册', index=True, default=False)
    doc_files_json = fields.Text(string='全部文档 (JSON)')

    param_ids = fields.One2many('lab.catalog.param', 'item_id', string='参数')
    param_count = fields.Integer(string='参数个数', default=0)

    search_text = fields.Char(string='检索文本', index=True)

    fetched_at = fields.Datetime(string='采集时间', index=True)
    source_fingerprint = fields.Char(string='来源指纹', index=True)
    import_run_id = fields.Many2one('lab.catalog.import.run', string='导入批次', ondelete='set null')

    _INDEX_DDL = [
        'CREATE UNIQUE INDEX IF NOT EXISTS lab_catalog_item_code_market_uniq '
        'ON lab_catalog_item (catalog_code, market)',
        'CREATE UNIQUE INDEX IF NOT EXISTS lab_catalog_category_catalog_id_uniq '
        'ON lab_catalog_category (catalog_id)',
        'CREATE INDEX IF NOT EXISTS lab_catalog_item_code_idx ON lab_catalog_item (catalog_code)',
        'CREATE INDEX IF NOT EXISTS lab_catalog_item_cat_idx ON lab_catalog_item (category_id)',
        'CREATE INDEX IF NOT EXISTS lab_catalog_item_brand_idx ON lab_catalog_item (brand_code)',
        'CREATE INDEX IF NOT EXISTS lab_catalog_item_pkg_idx ON lab_catalog_item (package)',
        'CREATE INDEX IF NOT EXISTS lab_catalog_item_mpn_idx ON lab_catalog_item (mpn)',
        # 注意 2：**不要**在这里给 lab_catalog_binding 建带 WHERE active 的索引 ——
        #         本模型 init() 早于 binding 的 _auto_init，那时 active 列还不存在，
        #         会真实抛出 "column active does not exist" 的 SQL ERROR。
        #         绑定唯一性改用 binding 模型上的 models.Constraint。
        # 注意：lab_catalog_param 的索引必须建在它自己的 init() 里。
        # 放在这里时该表可能尚未创建 -> relation does not exist -> 整个模块安装失败。
    ]

    def init(self):
        """每个 DDL 独立 SAVEPOINT：失败只丢该索引，绝不回滚安装事务。"""
        cr = self.env.cr
        for ddl in self._INDEX_DDL:
            cr.execute('SAVEPOINT lc_idx')
            try:
                cr.execute(ddl)
                cr.execute('RELEASE SAVEPOINT lc_idx')
            except Exception as exc:
                cr.execute('ROLLBACK TO SAVEPOINT lc_idx')
                _logger.warning('lab_catalog: index skipped: %s', exc)
        cr.execute('SAVEPOINT lc_trgm')
        try:
            cr.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm')
            cr.execute('CREATE INDEX IF NOT EXISTS lab_catalog_item_trgm_idx '
                       'ON lab_catalog_item USING gin (search_text gin_trgm_ops)')
            cr.execute('CREATE INDEX IF NOT EXISTS lab_catalog_item_name_trgm_idx '
                       'ON lab_catalog_item USING gin (name gin_trgm_ops)')
            cr.execute('RELEASE SAVEPOINT lc_trgm')
            _logger.info('lab_catalog: pg_trgm indexes ready')
        except Exception as exc:
            cr.execute('ROLLBACK TO SAVEPOINT lc_trgm')
            _logger.warning('lab_catalog: pg_trgm unavailable (%s); using ILIKE', exc)

    # ------------------------------------------------------------------ helpers
    @api.model
    def _norm(self, value):
        return normalize_catalog_code(value)

    @api.model
    def _revision(self, key, bump=False):
        param = self.env['ir.config_parameter'].sudo()
        name = 'lab_catalog.%s_revision' % key
        cur = int(param.get_param(name, '0') or 0)
        if bump:
            cur += 1
            param.set_param(name, str(cur))
        return str(cur)

    @api.model
    def bump_inventory_revision(self):
        self._require_manager()
        return self._revision('inventory', bump=True)

    @api.model
    def bump_catalog_revision(self):
        self._require_manager()
        return self._revision('catalog', bump=True)

    @api.model
    def _touch_inventory_revision(self):
        """**内部**版本号自增（不做 manager 守卫）。

        绑定/建档是普通操作员的**合法**业务动作（见 ``group_lab_catalog_user``
        的 comment），但它们同样改变卡片的可见状态，必须让客户端缓存失效。
        早期实现让 binding.create/write 与控制器都调用公开的
        ``bump_inventory_revision``，而那个方法带 manager 守卫 ——
        于是"普通操作员首次建档"必然 FORBIDDEN，且 ACL 补了也无效。

        公开方法保留守卫（防止经 /web/dataset/call_kw 或 XML-RPC 被越权直接调用）；
        内部路径一律走这个私有方法，下划线开头 => Odoo 不允许 RPC 调用。
        """
        return self._revision('inventory', bump=True)

    @api.model
    def prefetch_stocked_assets(self, limit=50):
        """已入库器件的图片/手册主动写入磁盘缓存（不是只靠 <img> 访问）。

        会回源抓取，属于有副作用的公开方法 -> 必须管理员。
        """
        self._require_manager()
        from ..controllers.asset_cache import ensure_cached
        stocked, _q, _a, _c = self._stocked_state()
        if not stocked:
            return {'processed': 0, 'cached': 0}
        items = self.search([('market', '=', MARKET_CN),
                             ('catalog_code', 'in', sorted(stocked))], limit=limit)
        processed = cached = 0
        for item in items:
            for url in (item.image_url, item.datasheet_url):
                if not url:
                    continue
                processed += 1
                try:
                    if ensure_cached(url):
                        cached += 1
                except Exception as exc:
                    _logger.info('lab_catalog prefetch skipped %s: %s', url, exc)
        return {'processed': processed, 'cached': cached}

    # ---------------------------------------------- live, ACL-safe inventory
    @api.model
    def _live_state(self):
        """一次请求内算一次：实时库存（内部库位、公司/ACL 生效、按 C 聚合净量）。

        返回 (stocked_codes:set, qty_by_tmpl, avail_by_tmpl, code_qty)
        """
        quants = self.env['stock.quant'].search_read(
            [('location_id.usage', '=', 'internal')],
            ['product_id', 'quantity', 'available_quantity'])
        if not quants:
            return set(), {}, {}, {}

        product_ids = sorted({q['product_id'][0] for q in quants if q.get('product_id')})
        products = self.env['product.product'].browse(product_ids)
        # 只做 product_id -> template_id 映射（旧实现把模板 id 也写进同一个 dict，会互相覆盖）
        pid2tid = {}
        for p in products:
            pid2tid[p.id] = p.product_tmpl_id.id
        tids = sorted(set(pid2tid.values()))
        tid2code = {}
        for t in self.env['product.template'].browse(tids).read(['id', 'lab_lcsc_code_norm']):
            tid2code[t['id']] = t['lab_lcsc_code_norm'] or None

        qty, avail, code_qty = {}, {}, {}
        for q in quants:
            pid = q['product_id'][0] if q.get('product_id') else None
            tid = pid2tid.get(pid)
            if not tid:
                continue
            qty[tid] = qty.get(tid, 0.0) + (q.get('quantity') or 0.0)
            avail[tid] = avail.get(tid, 0.0) + (q.get('available_quantity') or 0.0)
        # 有库存 = **按 C 聚合后的净数量 > 0**（单个模板为正不算数）
        for tid, v in qty.items():
            code = tid2code.get(tid)
            if code:
                code_qty[code] = code_qty.get(code, 0.0) + v
        stocked = {c for c, v in code_qty.items() if v > 0}
        return stocked, qty, avail, code_qty

    # 兼容旧调用名
    @api.model
    def _stocked_state(self):
        return self._live_state()

    # ------------------------------------------------ 权限：公开方法必须自校验
    @api.model
    def _is_manager(self):
        u = self.env.user
        return (u.has_group('lab_catalog.group_lab_catalog_manager')
                or u.has_group('base.group_system'))

    @api.model
    def _require_manager(self):
        """公开写方法的守卫。

        Odoo 的公开 ``@api.model`` 方法可被任意登录用户经 ``/web/dataset/call_kw``
        或 XML-RPC 直接调用，**不能只靠 controller 的 api_route 守卫**。
        """
        if not self._is_manager():
            raise AccessError('只有器件库管理员可以执行该操作。')

    @api.model
    def _grant_catalog_role(self, user_ids):
        """**私有**（下划线开头 => 不可 RPC）授权实现，仅供安装钩子调用。

        res.groups 在 Odoo 19 没有 users 字段，必须从 user 侧写 Many2many。
        """
        group = self.env.ref('lab_catalog.group_lab_catalog_user', raise_if_not_found=False)
        if not group:
            return 0
        users = self.env['res.users'].sudo().browse(list(user_ids or [])).exists()
        count = 0
        for user in users:
            field = 'group_ids' if 'group_ids' in user._fields else 'groups_id'
            if group.id not in user[field].ids:
                user.sudo().write({field: [(4, group.id)]})
            count += 1
        return count

    @api.model
    def grant_catalog_role(self, user_ids):
        """公开授权入口，但**先校验管理员**（防止自提权）。"""
        self._require_manager()
        return self._grant_catalog_role(user_ids)

    @api.model
    def bootstrap(self):
        """界面首屏信息（只读）。初始授权由 post_init_hook 完成，不经 RPC。"""
        self._check_catalog_read_access()
        return {
            'can_manage': self._is_manager(),
            'can_read': True,
            'borrowers': [],          # 由 lab_workflow 的 bootstrap 提供
            'inventory_revision': self._revision('inventory'),
            'catalog_revision': self._revision('catalog'),
        }

    @api.model
    def _check_catalog_read_access(self):
        """显式检查读取权限：auth='user' 不允许绕过资料模型的 ACL。"""
        self.check_access_rights('read')
        self.check_access_rule('read')

    # ------------------------------------------------ lab_workflow 整合（安全延迟检测）
    @api.model
    def _safe_read(self, model, domain, fields, order=None, limit=None):
        """只读存在的字段：lab_workflow 的模型字段可能随后续版本变化。"""
        if model not in self.env:
            return []
        Model = self.env[model]
        have = [f for f in fields if f in Model._fields]
        kw = {}
        if order and 'create_date' in Model._fields:
            kw['order'] = order
        if limit:
            kw['limit'] = limit
        return Model.search_read(domain, have, **kw)

    @api.model
    def _workflow_overlay(self, tids):
        """袋 / 库位 / 未归还 / 历史。

        * **所有**绑定模板一起查（不是只取一个）；
        * `lab_workflow` 未安装时 env 里没有 `lab.bag`，返回空并且**不报错**；
        * 这里不捕获业务异常去谎称"模块未安装"——真正的错误要原样上抛。
        """
        tids = [t for t in (tids or []) if t]
        if not tids or 'lab.bag' not in self.env:
            return [], [], [], []

        bags = self._safe_read(
            'lab.bag', [('product_tmpl_id', 'in', tids)],
            ['id', 'trace_code', 'name', 'product_tmpl_id', 'product_id', 'location_id',
             'quantity', 'outstanding_quantity', 'receipt_date', 'supplier_order',
             'supplier_mpn', 'lot_id', 'active'],
            order='receipt_date desc', limit=500)

        locations = {}
        for q in self.env['stock.quant'].search_read(
                [('product_id.product_tmpl_id', 'in', tids),
                 ('location_id.usage', '=', 'internal'), ('quantity', '!=', 0)],
                ['product_id', 'location_id', 'quantity', 'available_quantity']):
            loc = q['location_id'][1] if q['location_id'] else '?'
            slot = locations.setdefault(loc, {'location': loc, 'quantity': 0.0,
                                              'available_quantity': 0.0})
            slot['quantity'] += q.get('quantity') or 0.0
            slot['available_quantity'] += q.get('available_quantity') or 0.0

        # 未归还（领料明细）：归还必须选真实 issue_line_id 并做余额校验
        issues = self._safe_read(
            'lab.issue.line',
            [('bag_id', 'in', [b['id'] for b in bags])] if bags else [('id', '=', 0)],
            ['id', 'bag_id', 'quantity', 'returned_quantity', 'outstanding_quantity',
             'borrower_id', 'actor_id', 'project', 'date'],
            order='date desc', limit=200)
        issues = [i for i in issues if (i.get('outstanding_quantity') or 0) > 0]

        history = self._safe_read(
            'lab.operation.line',
            [('bag_id', 'in', [b['id'] for b in bags])] if bags else [('id', '=', 0)],
            ['id', 'bag_id', 'operation_id', 'quantity', 'create_date'],
            order='create_date desc', limit=200)

        return sorted(locations.values(), key=lambda x: x['location']), bags, issues, history

    # ------------------------------------------------------------------ cursor
    @api.model
    def _encode_cursor(self, rank, sort_key):
        raw = json.dumps({'v': 3, 'r': int(rank), 'k': sort_key}, separators=(',', ':'))
        return base64.urlsafe_b64encode(raw.encode('utf-8')).decode('ascii')

    @api.model
    def _decode_cursor(self, cursor):
        if not cursor:
            return None
        try:
            raw = base64.urlsafe_b64decode(cursor.encode('ascii')).decode('utf-8')
            obj = json.loads(raw)
            if int(obj.get('v', 0)) != 3:
                return None
            return (int(obj['r']), str(obj['k']))
        except Exception:
            return None

    # ------------------------------------------------------------------ lab side
    @api.model
    def _lab_rows(self, query, brands, packages, has_dimension_filter, matched_codes):
        """构造本地物料行。返回 (rows, matched_codes_updated)。

        * 无 C 码的物料 -> uid ``lab:<id>``
        * **有合法 C 码但索引里没有该 C 码** -> uid ``lcsc:<code>``（合成"仅本地"卡片），
          避免本地物料因为没被采集而消失，也不会与索引里已有的同码卡片重复。
        """
        Tmpl = self.env['product.template']
        # 本地档案的检索维度：名称 / SN / 内部编码 / 型号 / **C 编号**
        # （直接搜 C 编号必须能命中"有码但资料库未采集"的本地件）
        dom = []
        if query:
            q = query.strip()
            dom = ['|', '|', '|', '|',
                   ('name', 'ilike', q), ('lab_sn', 'ilike', q),
                   ('default_code', 'ilike', q), ('lab_mpn', 'ilike', q),
                   ('lab_lcsc_code', '=ilike', q)]
        if brands:
            dom.append(('lab_brand', 'in', list(brands)))
        if packages:
            dom.append(('lab_package', 'in', list(packages)))
        templates = Tmpl.search(dom)

        # 1) **先无条件求 matched_codes**：本地 SN / 名称命中的绑定 C 码必须带出对应卡片，
        #    即使同时启用了类别/参数筛选也不能漏（早期实现在维度筛选时直接 return，
        #    导致"按本地 SN 搜到物料却看不到它的资料卡片"）。
        index_codes = set()
        codes = [t.lab_lcsc_code_norm for t in templates if t.lab_lcsc_code_norm]
        if codes:
            self.env.cr.execute(
                'SELECT catalog_code FROM lab_catalog_item WHERE market = %s '
                'AND catalog_code = ANY(%s)', (MARKET_CN, list(set(codes))))
            index_codes = {r[0] for r in self.env.cr.fetchall()}
        for t in templates:
            if t.lab_lcsc_code_norm:
                matched_codes.add(t.lab_lcsc_code_norm)

        # 2) 再决定是否输出本地行：类别/参数是**资料库维度**，本地物料没有该维度，
        #    一旦启用这些筛选就不该混入无关本地件。
        rows = []
        if has_dimension_filter:
            return rows, matched_codes

        qty_all, avail_all, _cq = self._live_state()[1:4]
        rows = []
        # 同一 C 编号的多个本地档案必须聚合成**一张**卡片（root 裁决：一码一卡）。
        # 早期实现一条档案一行 -> 同一 uid 出现多次 -> 界面出现 4 张重复卡片。
        agg_by_code = {}
        order = []
        for t in templates:
            # Odoo 空 Char 是 False（bool），不是 None。若原样交给 COPY 转义会被写成
            # PG 布尔文本 'f'，未绑定物料就会变成 "lcsc:f" 卡片。必须归一到 None。
            code = t.lab_lcsc_code_norm or None
            if code:
                if code in index_codes:
                    continue                      # 已在索引卡片里聚合，别重复出卡片
                if code not in agg_by_code:
                    uid = 'lcsc:%s' % code
                    agg_by_code[code] = [uid, t.id, t.lab_sn or '', t.name or '',
                                         t.lab_mpn or '', t.lab_brand or '',
                                         t.lab_package or '', 0.0, 0.0, code, code]
                    order.append(code)
                slot = agg_by_code[code]
                slot[7] += qty_all.get(t.id, 0.0)
                slot[8] += avail_all.get(t.id, 0.0)
                continue
            uid = 'lab:%d' % t.id
            q = qty_all.get(t.id, 0.0)
            rows.append((uid, t.id, t.lab_sn or '', t.name or '', t.lab_mpn or '',
                         t.lab_brand or '', t.lab_package or '', q,
                         avail_all.get(t.id, 0.0), None, uid))
        rows.extend(agg_by_code[c] for c in order)
        return rows, matched_codes

    @api.model
    def backfill_category_paths(self):
        """把 item.category_path 刷成 **PG id 祖先路径**（从分类表的 pg_path 回填）。

        导入工具已改成直接写 PG 路径；这个方法用于修复历史数据
        （早期版本写的是商城分类号路径，导致"点分类"筛不出任何结果）。
        """
        cr = self.env.cr
        cr.execute("""
            UPDATE lab_catalog_item i
               SET category_path = c.pg_path
              FROM lab_catalog_category c
             WHERE i.category_id = c.id
               AND c.pg_path IS NOT NULL
               AND c.pg_path <> ''
               AND (i.category_path IS DISTINCT FROM c.pg_path)
        """)
        n = cr.rowcount
        cr.execute("SELECT count(*) FROM lab_catalog_item WHERE category_id IS NOT NULL "
                   "AND (category_path IS NULL OR category_path = '')")
        left = cr.fetchone()[0]
        return {'updated': n, 'still_empty': left}

    # ------------------------------------- 共享过滤条件（search 与 facets 必须一致）
    @api.model
    def _matched_codes_for_query(self, query, brands=None, packages=None):
        """绑定本地 SN/名称命中时对应的 C 码集合。

        search 与 facets 共用，保证「分类/品牌/封装列表」与「结果」永远不会不一致。
        """
        matched = set()
        if not query:
            return matched
        dom = ['|', '|', '|', '|',
               ('name', 'ilike', query), ('lab_sn', 'ilike', query),
               ('default_code', 'ilike', query), ('lab_mpn', 'ilike', query),
               # 直接搜 C 编号也必须命中本地档案（否则"有码未采集"的物料搜不到）
               ('lab_lcsc_code', '=ilike', query)]
        if brands:
            dom.append(('lab_brand', 'in', list(brands)))
        if packages:
            dom.append(('lab_package', 'in', list(packages)))
        for t in self.env['product.template'].search(dom):
            if t.lab_lcsc_code_norm:
                matched.add(t.lab_lcsc_code_norm)
        return matched

    @api.model
    def _catalog_where(self, query=None, category_id=None, brands=None, packages=None,
                       parameters=None, include_parameters=True):
        """构造资料库侧的 (where_sql, args)。

        **search 与 facets 共用同一个构造器**：分类用 PG 祖先路径（不是 /cid/ 前缀），
        查询复用「绑定本地 SN/名称 -> C 码」逻辑（不只是 search_text）。
        """
        where = ["i.market = %s"]
        args = [MARKET_CN]
        q = (query or '').strip()
        if q:
            like = '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
            matched = self._matched_codes_for_query(q, brands, packages)
            if matched:
                where.append("(i.search_text ILIKE %s OR i.catalog_code = %s "
                             "OR i.catalog_code = ANY(%s))")
                args.extend([like, q.upper(), sorted(matched)])
            else:
                where.append("(i.search_text ILIKE %s OR i.catalog_code = %s)")
                args.extend([like, q.upper()])
        if category_id:
            # 关键：解析与"追加 SQL + 追加参数"必须分开。
            # 早期把 where.append 和 args.extend 放在同一个 try 里，
            # 一旦 extend 抛错就被 except 吞掉 -> SQL 里多了占位符而参数没跟上，
            # 上层只会看到难懂的 IndexError。现在两者保证同时发生。
            try:
                cid = int(category_id)          # 外部语义统一为 Odoo(PG) id
            except (TypeError, ValueError):
                cid = None
            if cid:
                # item.category_path 存 PG id 祖先路径 /3/12/45/ -> 子串匹配覆盖所有下级。
                # 注意：这里是 **psycopg2 参数**，所以要写真正想要的通配模式 %/24/%，
                # 不能写 '/%d/'（那样只匹配自身，子类全部漏掉）。
                where.append("(i.category_id = %s OR i.category_path LIKE %s)")
                args.append(cid)
                args.append('%%/%d/%%' % cid)
        if brands:
            where.append("i.brand_code = ANY(%s)")
            args.append(list(brands))
        if packages:
            where.append("i.package = ANY(%s)")
            args.append(list(packages))
        if include_parameters and parameters:
            for idx, (pcode, values) in enumerate(sorted(parameters.items())):
                if not values:
                    continue
                a = 'p%d' % idx
                ph = ','.join(['%s'] * len(values))
                # 用 .format 而非 % 格式化：避免 %% 转义残留导致占位符/参数错位
                where.append(
                    "EXISTS (SELECT 1 FROM lab_catalog_param {a} WHERE {a}.item_id = i.id "
                    "AND {a}.code = %s AND {a}.value IN ({ph}))".format(a=a, ph=ph))
                args.append(pcode)
                args.extend(list(values))
        # 自检：占位符数量必须与参数数量一致（不一致会变成难查的 IndexError）
        full_sql = ' AND '.join(where)
        ph_count = full_sql.count('%s')
        if ph_count != len(args):
            raise AssertionError(
                'catalog where mismatch: ph=%d args=%d\nSQL=%s\nARGS=%r'
                % (ph_count, len(args), full_sql[:800], args))
        return full_sql, args

    @api.model
    def facets(self, query=None, category_id=None, brands=None, packages=None,
               parameters=None, brand_limit=60, package_limit=60,
               param_limit=60, value_limit=12):
        """当前检索条件下**真实可选**的品牌/封装/参数值。

        root 复核后重写的两点（原实现有真实缺陷）：

        1. **性能：不再 N+1。** 旧实现先取最多 200 个参数码，再为每个码单独跑一条
           全库 JOIN + GROUP BY（最多 200 条重查询），实测把界面卡死十几分钟。
           现在参数值用**一条**带窗口函数的查询（ROW_NUMBER OVER (PARTITION BY code
           ORDER BY count DESC)）算出所有维度的 top-N、总数与 has_more。
        2. **语义：不能无声忽略筛选。** 旧实现用 ``include_parameters=False`` 把
           **所有**参数筛选都丢了，却注释成"只排除自身"。正确做法是标准分面语义：
           某个参数维度的候选值保留分类/品牌/封装**以及其它已选参数**，
           只排除它**自身**的筛选（见下面的 sel_codes/sel_values 相关子查询）。

        同时品牌/封装明确返回 ``total`` 与 ``has_more``，避免用户误以为库里只有 60 个。
        返回值附带 ``timing_ms``，便于验收真实全库耗时。
        """
        import time

        cr = self.env.cr
        # 可失效缓存：key 含完整组合 + 版本；导入/绑定会 bump 版本
        _ck = json.dumps([query or '', category_id, sorted(brands or []),
                          sorted(packages or []),
                          sorted((str(k), sorted(map(str, v if isinstance(v, (list, tuple)) else [v])))
                                 for k, v in (parameters or {}).items()),
                          self._revision('catalog'), self._revision('inventory')],
                         sort_keys=True, default=str)
        _hit = _FACETS_CACHE.get(_ck)
        if _hit is not None:
            return dict(_hit, cached=True)
        timing = {}

        def run(key, sql, args):
            t0 = time.time()
            cr.execute(sql, args)
            out = cr.fetchall()
            timing[key] = round((time.time() - t0) * 1000.0, 1)
            return out

        parameters = {k: v for k, v in (parameters or {}).items() if v}

        # ---- 品牌：排除"品牌"自身维度，保留分类/封装/查询/参数
        bw, ba = self._catalog_where(query, category_id, None, packages, parameters)
        rows = run('brands', "SELECT i.brand_code, MIN(i.brand), COUNT(*) "
                            "FROM lab_catalog_item i WHERE " + bw +
                            " AND i.brand_code IS NOT NULL AND i.brand_code <> '' "
                            "GROUP BY i.brand_code ORDER BY COUNT(*) DESC, i.brand_code "
                            "LIMIT %s", ba + [brand_limit + 1])
        brands_out = [{'code': r[0], 'label': r[1] or r[0], 'count': r[2]}
                      for r in rows[:brand_limit]]
        brands_more = len(rows) > brand_limit

        # ---- 封装：排除"封装"自身维度
        pw, pa = self._catalog_where(query, category_id, brands, None, parameters)
        rows = run('packages', "SELECT i.package, COUNT(*) FROM lab_catalog_item i "
                               "WHERE " + pw + " AND i.package IS NOT NULL AND i.package <> '' "
                               "GROUP BY i.package ORDER BY COUNT(*) DESC, i.package "
                               "LIMIT %s", pa + [package_limit + 1])
        packages_out = [{'value': r[0], 'count': r[1]} for r in rows[:package_limit]]
        packages_more = len(rows) > package_limit

        # ---- 参数维度候选码（排除参数维度自身，保留其余条件）
        cw, ca = self._catalog_where(query, category_id, brands, packages, None)
        rows = run('param_codes', "SELECT p.code, MIN(p.name), COUNT(*) "
                                  "FROM lab_catalog_param p "
                                  "JOIN lab_catalog_item i ON i.id = p.item_id "
                                  "WHERE " + cw +
                                  " AND p.code IS NOT NULL AND p.code <> '' "
                                  "AND p.value IS NOT NULL AND p.value <> '' "
                                  "GROUP BY p.code ORDER BY COUNT(*) DESC, p.code "
                                  "LIMIT %s", ca + [param_limit])
        codes = [r[0] for r in rows]
        name_by_code = {r[0]: (r[1] or r[0]) for r in rows}
        context_count = {r[0]: r[2] for r in rows}

        if not codes:
            return {'brands': brands_out, 'brands_has_more': brands_more,
                    'packages': packages_out, 'packages_has_more': packages_more,
                    'parameters': [], 'parameters_has_more': False,
                    'timing_ms': timing}

        sel = sorted((str(c), str(v)) for c, vs in parameters.items()
                     for v in (vs if isinstance(vs, (list, tuple)) else [vs]))
        sel_codes = [c for c, _ in sel]
        sel_values = [v for _, v in sel]

        # ---- 参数值：**一条**查询算完所有码的 top-N（窗口函数），
        #      并且"只排除自身参数"：item 必须满足除 p.code 以外的全部已选参数。
        sql = """
            SELECT p.code, p.value, COUNT(*) AS cnt,
                   COUNT(*) OVER (PARTITION BY p.code) AS code_total,
                   ROW_NUMBER() OVER (PARTITION BY p.code
                                      ORDER BY COUNT(*) DESC, p.value) AS rn
            FROM lab_catalog_item i
            JOIN lab_catalog_param p ON p.item_id = i.id
            WHERE {cw}
              AND p.code = ANY(%s)
              AND p.value IS NOT NULL AND p.value <> ''
              AND (
                    SELECT COUNT(*)
                      FROM generate_subscripts(%s::text[], 1) AS gs(k)
                      JOIN lab_catalog_param q
                        ON q.item_id = i.id
                       AND q.code = (%s::text[])[gs.k]
                       AND q.value = (%s::text[])[gs.k]
                     WHERE (%s::text[])[gs.k] <> p.code
                  ) = (
                    SELECT COUNT(*) FROM generate_subscripts(%s::text[], 1) AS gs(k)
                     WHERE (%s::text[])[gs.k] <> p.code
                  )
            GROUP BY p.code, p.value
        """.format(cw=cw)
        rows = run('param_values', sql, list(ca) + [codes] + [sel_codes, sel_codes, sel_values,
                                                             sel_codes, sel_codes, sel_codes])

        params_out = {}
        for code, value, cnt, code_total, rn in rows:
            slot = params_out.get(code)
            if slot is None:
                slot = {'code': code, 'name': name_by_code.get(code, code),
                        'count': context_count.get(code, code_total),
                        'values': [], 'has_more': False}
                params_out[code] = slot
            if rn <= value_limit:
                slot['values'].append({'value': value, 'count': cnt})
            if code_total > value_limit:
                slot['has_more'] = True

        ordered = [params_out[c] for c in codes if c in params_out]
        timing['total'] = round(sum(timing.values()), 1)
        _result = {
            'brands': brands_out, 'brands_has_more': brands_more, 'brands_limit': brand_limit,
            'packages': packages_out, 'packages_has_more': packages_more,
            'packages_limit': package_limit,
            'parameters': ordered, 'parameters_limit': param_limit,
            'parameters_has_more': len(codes) >= param_limit,
            'timing_ms': timing,
        }
        if len(_FACETS_CACHE) >= _FACETS_CACHE_MAX:
            _FACETS_CACHE.clear()
        _FACETS_CACHE[_ck] = _result
        return _result

    # ------------------------------------------------------------------ search
    @api.model
    def search_unified(self, query=None, category_id=None, brands=None, packages=None,
                       parameters=None, stock_only=False, cursor=None, limit=50):
        """统一器件库检索：资料库 + 本地物料，一次分页，全局"有库存优先"。"""
        self._check_catalog_read_access()          # 显式 ACL
        limit = max(1, min(int(limit or 50), 200))
        cr = self.env.cr
        stocked, qty_by_tmpl, avail_by_tmpl, _code_qty = self._live_state()

        brands = [b for b in (brands or []) if b]
        packages = [p for p in (packages or []) if p]
        parameters = parameters or {}
        has_dimension_filter = bool(category_id or parameters)

        matched_codes = set()
        lab_rows, matched_codes = self._lab_rows(query, brands, packages,
                                                 has_dimension_filter, matched_codes)

        cr.execute('SAVEPOINT lc_lab')
        cr.execute("""
            CREATE TEMP TABLE IF NOT EXISTS _lc_lab (
                uid text, lab_product_id int, sn text, name text, mpn text,
                brand text, package text, qty numeric, avail numeric,
                code text, sort_key text
            ) ON COMMIT DROP
        """)
        cr.execute('DELETE FROM _lc_lab')
        if lab_rows:
            buf = io.StringIO('\n'.join(
                '\t'.join(_copy_escape(v) for v in r) for r in lab_rows))
            cr.copy_expert('COPY _lc_lab (uid, lab_product_id, sn, name, mpn, brand, package,'
                           ' qty, avail, code, sort_key) FROM STDIN', buf)
        cr.execute('RELEASE SAVEPOINT lc_lab')

        # 与 facets 共用同一个过滤构造器：分类用 PG 祖先路径、查询复用绑定 SN/名称逻辑，
        # 保证「筛选面板可选项」与「实际结果」永远一致。
        where_sql, args = self._catalog_where(
            query, category_id, brands, packages, parameters, include_parameters=True)

        stocked_list = sorted(stocked) or ['__none__']
        base_sql = """
            SELECT * FROM (
              SELECT 'lcsc:' || i.catalog_code AS uid, NULL::int AS lab_product_id,
                     i.catalog_code AS catalog_code, NULL::text AS sn,
                     i.name, i.mpn, i.brand, i.package, i.category_name, i.category_id,
                     i.image_url, i.has_image, i.has_datasheet, i.catalog_stock,
                     i.price, i.currency, i.param_count, i.source_url,
                     NULL::numeric AS qty, NULL::numeric AS avail,
                     CASE WHEN i.catalog_code = ANY(%s) THEN 0 ELSE 1 END AS rank,
                     i.catalog_code AS sort_key
              FROM lab_catalog_item i WHERE {where}
              UNION ALL
              SELECT l.uid, l.lab_product_id, l.code, l.sn, l.name, l.mpn, l.brand, l.package,
                     NULL, NULL, NULL, false, false, NULL, NULL, NULL, 0, NULL,
                     l.qty, l.avail,
                     CASE WHEN COALESCE(l.qty, 0) > 0 THEN 0 ELSE 1 END AS rank,
                     l.sort_key
              FROM _lc_lab l
            ) m
        """.format(where=where_sql)

        # 只在**外层**用 AND 叠加，避免出现两个 WHERE
        outer = []
        outer_args = []
        if stock_only:
            outer.append('rank = 0')
        key = self._decode_cursor(cursor)
        if key:
            outer.append('(rank, sort_key) > (%s, %s)')
            outer_args.extend([key[0], key[1]])

        page_where = (' WHERE ' + ' AND '.join(outer)) if outer else ''
        page_args = [stocked_list] + list(args) + outer_args + [limit + 1]
        cr.execute('SAVEPOINT lc_page')
        cr.execute(base_sql + page_where + ' ORDER BY rank ASC, sort_key ASC LIMIT %s', page_args)
        rows = cr.dictfetchall()
        cr.execute('RELEASE SAVEPOINT lc_page')

        next_cursor = None
        if len(rows) > limit:
            rows = rows[:limit]
            last = rows[-1]
            next_cursor = self._encode_cursor(last['rank'], last['sort_key'])

        # total：与游标无关（不带 keyset 条件）
        # count 的占位符与 page 同构，但**不含** outer 条件与 limit
        count_page_where = ' WHERE rank = 0' if stock_only else ''
        count_args = [stocked_list] + list(args)
        cr.execute('SAVEPOINT lc_cnt')
        cr.execute('SELECT COUNT(*) FROM (' + base_sql + count_page_where + ') c', count_args)
        total = cr.fetchone()[0]
        cr.execute('RELEASE SAVEPOINT lc_cnt')

        return self._decorate(rows, qty_by_tmpl, avail_by_tmpl), next_cursor, total

    @api.model
    def _decorate(self, rows, qty_by_tmpl, avail_by_tmpl):
        codes = [r['catalog_code'] for r in rows if r.get('catalog_code')]
        bindings = self.env['lab.catalog.binding'].binding_map(codes) if codes else {}
        sn_by_tmpl = {}
        tids = sorted({t for lst in bindings.values() for t in lst})
        if tids:
            for t in self.env['product.template'].browse(tids).read(['id', 'lab_sn']):
                sn_by_tmpl[t['id']] = t['lab_sn']
        rev = '%s.%s' % (self._revision('inventory'), self._revision('catalog'))
        items = []
        for r in rows:
            code = r.get('catalog_code')
            if code:
                bound = bindings.get(code, [])
                qty = sum(qty_by_tmpl.get(t, 0.0) for t in bound)
                avail = sum(avail_by_tmpl.get(t, 0.0) for t in bound)
                items.append({
                    'item_key': 'lcsc:%s' % code, 'catalog_code': code,
                    'lab_template_ids': bound,
                    'sn_codes': [sn_by_tmpl.get(t) for t in bound if sn_by_tmpl.get(t)],
                    'name': r['name'] or '', 'mpn': r['mpn'] or '', 'brand': r['brand'] or '',
                    'package': r['package'] or '', 'category_id': r['category_id'],
                    'category_name': r['category_name'] or '', 'image_url': r['image_url'],
                    'lab_quantity': qty, 'lab_available_quantity': avail, 'has_stock': qty > 0,
                    'catalog_stock': r['catalog_stock'], 'price': r['price'],
                    'currency': r['currency'], 'has_datasheet': bool(r['has_datasheet']),
                    'param_count': r['param_count'], 'parameters': [],
                    'source_url': r['source_url'], 'revision': rev,
                })
            else:
                # 本地行：可能自带 C 码（有码但未采集）——uid 用 canonical lcsc 键，
                # 因此详情/绑定仍以 C 码为准；无码则是 lab:<id>
                key = r['uid']
                one_code = None
                if key.startswith('lcsc:'):
                    one_code = key[5:]
                items.append({
                    'item_key': key, 'catalog_code': one_code,
                    'lab_template_ids': [r['lab_product_id']],
                    'sn_codes': [r['sn']] if r.get('sn') else [],
                    'name': r['name'] or '', 'mpn': r['mpn'] or '', 'brand': r['brand'] or '',
                    'package': r['package'] or '', 'category_id': None, 'category_name': '',
                    'image_url': None, 'lab_quantity': r['qty'],
                    'lab_available_quantity': r['avail'], 'has_stock': (r['qty'] or 0) > 0,
                    'catalog_stock': None, 'price': None, 'currency': None,
                    'has_datasheet': False, 'param_count': 0, 'parameters': [],
                    'source_url': None, 'revision': rev,
                })
        return items

    # ------------------------------------------------------------------ detail
    @api.model
    def detail(self, item_key):
        """详情：接受 ``lcsc:<code>``（索引内或**仅有本地档案**）与 ``lab:<id>``。

        root 复核指出：控制器若一律剥掉 lcsc 前缀再按 C 码查，``lab:42`` 永远查不到，
        有合法 C 码但未采集的本地物料在详情页也会消失。这里统一分派。
        """
        from .lab_catalog_identity import parse_item_key, normalize_catalog_code
        kind, val = parse_item_key(item_key)
        if not kind:
            # 便利：也接受裸 C 编号（契约里 item_key 应带 lcsc:/lab: 前缀，
            # 但界面上直接贴一个 "C123456" 不应该查不到）
            bare = normalize_catalog_code(item_key)
            if bare:
                kind, val = 'lcsc', bare
        if kind == 'lab':
            tmpl = self.env['product.template'].browse(val).exists()
            return self._detail_local_template(tmpl) if tmpl else None
        if kind == 'lcsc':
            item = self.search([('catalog_code', '=', val), ('market', '=', MARKET_CN)], limit=1)
            if item:
                return self._detail_catalog_item(item)
            # 有合法 C 码但索引里没有 -> 以"仅本地"形态返回，不能消失
            tids = self.env['product.template'].lab_template_ids_for_codes([val]).get(val, [])
            if tids:
                return self._detail_local_code(val, tids)
        return None

    @api.model
    def _detail_local_template(self, tmpl):
        """未绑定（``lab:<id>``）或无码本地物料的详情。"""
        _st, qty_by_tmpl, avail_by_tmpl, _cq = self._live_state()
        rev = '%s.%s' % (self._revision('inventory'), self._revision('catalog'))
        qty = qty_by_tmpl.get(tmpl.id, 0.0)
        _wf_locations, _wf_bags, _wf_issues, _wf_history = self._workflow_overlay([tmpl.id])
        return {
            'item': {
                'item_key': 'lab:%d' % tmpl.id, 'catalog_code': tmpl.lab_lcsc_code_norm or None,
                'name': tmpl.name or '', 'mpn': tmpl.lab_mpn or '', 'brand': tmpl.lab_brand or '',
                'package': tmpl.lab_package or '', 'category_id': None, 'category_name': '',
                'category_path': '', 'image_url': None, 'datasheet_url': tmpl.lab_datasheet_url,
                'catalog_stock': None, 'price': None, 'currency': '', 'source_url': tmpl.lab_source_url,
                'lab_template_ids': [tmpl.id], 'lab_quantity': qty,
                'lab_available_quantity': avail_by_tmpl.get(tmpl.id, 0.0),
                'has_stock': qty > 0, 'parameters': [], 'revision': rev,
                'local_only': True,
            },
            'parameters': [], 'files': [],
            'lab_templates': [{'id': tmpl.id, 'sn': tmpl.lab_sn, 'name': tmpl.name,
                               'quantity': qty,
                               'available_quantity': avail_by_tmpl.get(tmpl.id, 0.0)}],
            'locations': _wf_locations, 'bags': _wf_bags,
            'issues': _wf_issues, 'history': _wf_history,
        }

    @api.model
    def _detail_local_code(self, code, tids):
        """有合法 C 码但未被采集：合成"仅本地"详情（canonical 键仍是 lcsc:<code>）。"""
        _st, qty_by_tmpl, avail_by_tmpl, _cq = self._live_state()
        rev = '%s.%s' % (self._revision('inventory'), self._revision('catalog'))
        templates = self.env['product.template'].browse(tids)
        total_qty = sum(qty_by_tmpl.get(t, 0.0) for t in tids)
        _wf_locations, _wf_bags, _wf_issues, _wf_history = self._workflow_overlay(tids)
        return {
            'item': {
                'item_key': 'lcsc:%s' % code, 'catalog_code': code,
                'name': templates[:1].name or code, 'mpn': templates[:1].lab_mpn or '',
                'brand': templates[:1].lab_brand or '', 'package': templates[:1].lab_package or '',
                'category_id': None, 'category_name': '', 'category_path': '',
                'image_url': None, 'datasheet_url': None, 'catalog_stock': None,
                'price': None, 'currency': '', 'source_url': None,
                'lab_template_ids': list(tids), 'lab_quantity': total_qty,
                'lab_available_quantity': sum(avail_by_tmpl.get(t, 0.0) for t in tids),
                'has_stock': total_qty > 0, 'parameters': [], 'revision': rev,
                'local_only': True,
            },
            'parameters': [], 'files': [],
            'lab_templates': [{'id': t.id, 'sn': t.lab_sn, 'name': t.name,
                               'quantity': qty_by_tmpl.get(t.id, 0.0),
                               'available_quantity': avail_by_tmpl.get(t.id, 0.0)}
                              for t in templates],
            'locations': _wf_locations, 'bags': _wf_bags,
            'issues': _wf_issues, 'history': _wf_history,
        }

    @api.model
    def _detail_catalog_item(self, item):
        """索引内器件的详情：item 内含**合计**库存与 parameters（与 root 契约一致）。"""
        _st, qty_by_tmpl, avail_by_tmpl, _cq = self._live_state()
        code = item.catalog_code
        tids = self.env['lab.catalog.binding'].binding_map([code]).get(code, [])
        templates = self.env['product.template'].browse(tids)
        total_qty = sum(qty_by_tmpl.get(t, 0.0) for t in tids)
        total_avail = sum(avail_by_tmpl.get(t, 0.0) for t in tids)

        # 所有绑定模板一起聚合（含袋/未归还/历史）；lab_workflow 未装时安全返回空
        _wf_locations, _wf_bags, _wf_issues, _wf_history = self._workflow_overlay(tids)

        files = []
        if item.doc_files_json:
            try:
                files = json.loads(item.doc_files_json)
            except Exception:
                files = []
        params = [{'code': p.code, 'name': p.name, 'value': p.value} for p in item.param_ids]
        rev = '%s.%s' % (self._revision('inventory'), self._revision('catalog'))
        return {
            'item': {
                'item_key': 'lcsc:%s' % item.catalog_code, 'catalog_code': item.catalog_code,
                'name': item.name or '', 'mpn': item.mpn or '', 'brand': item.brand or '',
                'package': item.package or '', 'category_id': item.category_id.id or None,
                'category_name': item.category_name or '', 'category_path': item.category_path or '',
                'image_url': item.image_url, 'datasheet_url': item.datasheet_url,
                'catalog_stock': item.catalog_stock, 'price': item.price,
                'currency': item.currency or '', 'source_url': item.source_url,
                'lab_template_ids': tids, 'lab_quantity': total_qty,
                'lab_available_quantity': total_avail, 'has_stock': total_qty > 0,
                'parameters': params, 'revision': rev,
            },
            'parameters': params,
            'files': files,
            'lab_templates': [{
                'id': t.id, 'sn': t.lab_sn, 'name': t.name,
                'quantity': qty_by_tmpl.get(t.id, 0.0),
                'available_quantity': avail_by_tmpl.get(t.id, 0.0),
            } for t in templates],
            'locations': _wf_locations,
            'bags': _wf_bags,
            'issues': _wf_issues,
            'history': _wf_history,
        }
