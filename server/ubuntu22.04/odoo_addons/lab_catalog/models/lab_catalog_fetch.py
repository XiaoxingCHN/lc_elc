# -*- coding: utf-8 -*-
"""按需补抓：搜索未命中时，把一条精确 C 编号/MPN 从立创抓进资料索引。

设计
----
* **异步**：接口只入队，Odoo cron（每分钟）取 1–2 条处理，绝不占用搜索请求；
* **只写资料**：只 upsert ``lab.catalog.item`` / ``lab.catalog.param``，
  不创建产品、不写 quant/move；
* **中文来源**：MPN 用英文站前端接口定位 C 码，名称/品牌/分类/参数/价格
  全部取中文详情页；
* **分类前置**：``parentCatalogId`` 不在电子白名单直接跳过，不请求中文页；
* **精确匹配**：MPN 必须 ``productModel`` 相等，模糊结果只存为候选。
"""
import hashlib
import json
import logging

from odoo import api, fields, models

from odoo.addons.lab_inventory.tools.param_search import build_search_params

from ..tools import lcsc_remote

_logger = logging.getLogger(__name__)

MARKET_CN = 'cn'
LOCK_ID = 87431001          # pg_try_advisory_lock：同一时间只允许一个 worker
ACTIVE_STATES = ('queued', 'resolving', 'fetching')
TERMINAL_STATES = ('done', 'failed', 'skipped_non_electronic', 'review',
                   'not_found', 'candidates')
MAX_ATTEMPTS = 3


def _clean_scalar(value):
    if value is None:
        return None
    text = str(value).strip().replace(',', '')
    text = ''.join(text.split())
    return text or None


def _integer_or_none(value):
    text = _clean_scalar(value)
    if text is None:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return int(number) if number == int(number) else None


def _float_or_none(value):
    text = _clean_scalar(value)
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _split_brand(raw):
    """'TI(德州仪器)' -> ('TI', '德州仪器')；无括号时品牌代码即全名。"""
    if not raw:
        return '', ''
    import re
    text = str(raw).strip()
    match = re.match(r'^(.*?)\s*[\(（]([^)）]*)[\)）]\s*$', text)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return text, ''


def _pick_url(value):
    if not value:
        return None
    if isinstance(value, list):
        for item in value:
            found = _pick_url(item)
            if found:
                return found
        return None
    if isinstance(value, dict):
        for key in ('fileUrl', 'url', 'imageUrl', 'src'):
            if value.get(key):
                return _pick_url(value[key])
        for item in value.values():
            found = _pick_url(item)
            if found:
                return found
        return None
    text = str(value).strip()
    if text.startswith('//'):
        return 'https:' + text
    if text.startswith('/'):
        return 'https://www.szlcsc.com' + text
    if text.startswith('http://'):
        return 'https://' + text[7:]
    return text if text.startswith('https://') else None


def _flatten_files(files):
    out, datasheet = [], None
    for entry in files or []:
        if not isinstance(entry, dict):
            continue
        file_type = entry.get('fileType') or ''
        for detail in entry.get('detailVOList') or []:
            if not isinstance(detail, dict):
                continue
            url = _pick_url(detail.get('fileUrl'))
            out.append({'fileType': file_type,
                        'fileName': detail.get('fileName') or '',
                        'fileUrl': url})
            if file_type == 'pdf_property' and datasheet is None and url:
                datasheet = url
    if datasheet is None:
        for item in out:
            if item['fileUrl']:
                datasheet = item['fileUrl']
                break
    return out, datasheet


def _search_text(code, name, mpn, brand, category, package):
    parts = [code or '', name or '', mpn or '', brand or '',
             category or '', package or '']
    return ' '.join(part for part in parts if part).lower()[:512]


class LabCatalogFetchRequest(models.Model):
    _name = 'lab.catalog.fetch.request'
    _description = '立创资料按需抓取请求'
    _order = 'create_date desc, id desc'
    _rec_name = 'query_raw'

    query_raw = fields.Char(string='原始查询', required=True)
    query_norm = fields.Char(string='规范化查询', required=True, index=True)
    query_kind = fields.Selection(
        [('c_code', 'C 编号'), ('mpn', '型号')],
        string='查询类型', required=True, default='c_code')
    state = fields.Selection([
        ('queued', '排队中'),
        ('resolving', '解析型号'),
        ('fetching', '抓取详情'),
        ('done', '已收录'),
        ('failed', '失败'),
        ('skipped_non_electronic', '非电子元器件'),
        ('review', '待审核'),
        ('not_found', '未找到'),
        ('candidates', '需要选择'),
    ], string='状态', required=True, default='queued', index=True)
    catalog_code = fields.Char(string='C 编号', index=True)
    product_id_ext = fields.Char(string='中文商品 ID')
    parent_catalog_id = fields.Integer(string='一级分类 ID')
    candidates_json = fields.Text(string='候选列表 (JSON)')
    message = fields.Text(string='提示')
    requested_by = fields.Many2one('res.users', string='发起人',
                                   ondelete='set null', index=True)
    attempts = fields.Integer(string='尝试次数', default=0)
    result_item_id = fields.Many2one('lab.catalog.item', string='资料行',
                                     ondelete='set null')
    started_at = fields.Datetime(string='开始时间')
    finished_at = fields.Datetime(string='结束时间')

    _INDEX_DDL = [
        'CREATE INDEX IF NOT EXISTS lab_catalog_fetch_state_idx '
        'ON lab_catalog_fetch_request (state, create_date)',
        # 同一查询只允许一个活动任务；数据库层兜住并发重复提交。
        'CREATE UNIQUE INDEX IF NOT EXISTS lab_catalog_fetch_active_uniq '
        "ON lab_catalog_fetch_request (query_norm) "
        "WHERE state IN ('queued', 'resolving', 'fetching')",
    ]

    def init(self):
        cr = self.env.cr
        for ddl in self._INDEX_DDL:
            cr.execute('SAVEPOINT lc_fetch_idx')
            try:
                cr.execute(ddl)
                cr.execute('RELEASE SAVEPOINT lc_fetch_idx')
            except Exception as exc:                  # pragma: no cover
                cr.execute('ROLLBACK TO SAVEPOINT lc_fetch_idx')
                _logger.warning('lab_catalog: fetch index skipped: %s', exc)

    # ------------------------------------------------------------------ status
    def status_payload(self):
        self.ensure_one()
        try:
            candidates = json.loads(self.candidates_json or '[]')
        except ValueError:
            candidates = []
        return {
            'request_id': self.id,
            'state': self.state,
            'query': self.query_raw,
            'query_kind': self.query_kind,
            'catalog_code': self.catalog_code or '',
            'item_key': ('lcsc:%s' % self.catalog_code) if self.catalog_code else '',
            'message': self.message or '',
            'candidates': candidates,
            'created_at': fields.Datetime.to_string(self.create_date)
            if self.create_date else '',
            'finished_at': fields.Datetime.to_string(self.finished_at)
            if self.finished_at else '',
        }

    def _set(self, state, message='', **vals):
        self.write(dict(vals, state=state, message=message,
                        finished_at=fields.Datetime.now()
                        if state in TERMINAL_STATES else False))

    # ------------------------------------------------------------------ cron
    @api.model
    def _cron_process_queue(self, limit=2):
        """Process a few queued requests; safe to run at any frequency.

        Uses a PostgreSQL advisory lock so two workers can never fetch the same
        row (or hammer the same external site concurrently).
        """
        cr = self.env.cr
        cr.execute('SELECT pg_try_advisory_lock(%s)', [LOCK_ID])
        if not cr.fetchone()[0]:
            return 0
        processed = 0
        try:
            for _index in range(max(1, int(limit or 1))):
                request = self.sudo().search(
                    [('state', '=', 'queued')],
                    order='create_date asc, id asc', limit=1)
                if not request:
                    break
                with cr.savepoint():
                    request._process_one()
                processed += 1
            return processed
        finally:
            cr.execute('SELECT pg_advisory_unlock(%s)', [LOCK_ID])

    def _process_one(self):
        self.ensure_one()
        if self.state != 'queued':
            return
        self.write({'state': 'resolving' if self.query_kind == 'mpn'
                    else 'fetching',
                    'started_at': fields.Datetime.now(),
                    'attempts': self.attempts + 1,
                    'finished_at': False})
        try:
            self._run()
        except lcsc_remote.LcscRemoteError as exc:
            self._handle_remote_error(exc)
        except Exception as exc:                       # noqa: BLE001 - report to operator
            _logger.exception('lab_catalog: fetch request %s failed', self.id)
            self._set('failed', '抓取失败：%s' % exc)

    def _handle_remote_error(self, exc):
        state = 'failed'
        if exc.code == 'not_found':
            state = 'not_found'
        message = {
            'not_found': '立创未找到该型号或 C 编号。',
            'verification_page': '立创返回了验证页，请稍后重试。',
            'network_error': '无法连接立创，请稍后重试。',
        }.get(exc.code, exc.message)
        if state == 'failed' and self.attempts < MAX_ATTEMPTS:
            # 外部站点偶发超时：退回队列，让下一轮 cron 再试。
            self.write({'state': 'queued', 'message': message,
                        'finished_at': False})
            return
        self._set(state, message)

    def _run(self):
        query = self.query_norm
        if self.query_kind == 'mpn':
            item, candidates = lcsc_remote.resolve_mpn(query)
            if item is None:
                if candidates:
                    self._set(
                        'candidates',
                        '找到多个候选，请选择正确的 C 编号。',
                        candidates_json=json.dumps(candidates, ensure_ascii=False))
                else:
                    self._set('not_found', '立创未找到该型号。')
                return
            code = lcsc_remote.normalize_catalog_code(item.get('productCode'))
            if not code:
                self._set('failed', '立创返回的 C 编号无效。')
                return
            self.write({'catalog_code': code})
        else:
            code = lcsc_remote.normalize_catalog_code(query)
            if not code:
                self._set('failed', 'C 编号无效。')
                return

        detail = lcsc_remote.fetch_product_detail(code)
        parent_id = detail.get('parentCatalogId')
        self.write({'parent_catalog_id': parent_id or 0})
        decision = lcsc_remote.classify_root(
            parent_id, detail.get('isMro'), self._allowed_roots())
        if decision == 'non_electronic':
            self._set('skipped_non_electronic',
                      '该商品不属于电子元器件，未加入资料库。',
                      product_id_ext=str(detail.get('productId') or ''))
            return
        if decision == 'unknown':
            self._set('review', '分类无法识别，已跳过抓取，等待人工审核。',
                      product_id_ext=str(detail.get('productId') or ''))
            return

        product_id = detail.get('productId')
        parsed = lcsc_remote.parse_cn_page(
            lcsc_remote.fetch_cn_page(product_id), expected=code)
        self.write({'product_id_ext': parsed['product_id']})

        leaf, root_id, category_name, category_path = self._resolve_category(parsed)
        if not leaf:
            self._set('review', '中文分类无法映射到现有分类树，已跳过入库。')
            return
        if root_id is not None and root_id not in self._allowed_roots():
            self._set('skipped_non_electronic',
                      '该商品不属于电子元器件，未加入资料库。')
            return

        catalog_item = self._upsert_item(parsed, leaf, category_name,
                                         category_path)
        self._set('done', '已收录，正在刷新。', result_item_id=catalog_item.id)
        self.env['lab.catalog.item']._revision('catalog', bump=True)

    # ------------------------------------------------------------------ policy
    @api.model
    def _allowed_roots(self):
        raw = self.env['ir.config_parameter'].sudo().get_param(
            'lab_catalog.electronics_roots')
        if raw:
            try:
                return {int(part) for part in str(raw).split(',') if part.strip()}
            except ValueError:
                _logger.warning('lab_catalog: bad electronics_roots parameter')
        return lcsc_remote.allowed_root_ids()

    # ------------------------------------------------------------------ category
    def _resolve_category(self, parsed):
        """Map the Chinese leaf to an existing Odoo category.

        Returns ``(record, root_catalog_id, name, path)``.  The leaf is
        preferred; when only the parent exists (an uncrawled leaf), the parent
        row is used so the item still lands in the right subtree.
        """
        category = parsed.get('catalog') or {}
        Cat = self.env['lab.catalog.category'].sudo()
        leaf_id = category.get('catalogId')
        parent_id = category.get('parentId')
        leaf_name = category.get('catalogName') or ''
        record = Cat.browse()
        if leaf_id:
            record = Cat.search([('catalog_id', '=', int(leaf_id))], limit=1)
        if record:
            name = leaf_name or record.name
            chain, node, seen = [], record, set()
            while node and node.id not in seen:
                seen.add(node.id)
                chain.append(node.name)
                node = node.parent_id
            chain.reverse()
            root = record
            while root.parent_id:
                root = root.parent_id
            return record, root.catalog_id, name, '/'.join(chain)
        if parent_id:
            parent = Cat.search([('catalog_id', '=', int(parent_id))], limit=1)
            if parent:
                name = leaf_name or parent.name
                return parent, parent.catalog_id, name, parent.name + '/' + name
        return Cat.browse(), None, '', ''

    # ------------------------------------------------------------------ write
    def _upsert_item(self, parsed, category, category_name, category_path):
        Item = self.env['lab.catalog.item'].sudo()
        code = parsed['code']
        item = Item.search([('catalog_code', '=', code),
                            ('market', '=', MARKET_CN)], limit=1)
        brand_code, brand_cn = _split_brand(parsed.get('brand'))
        files, datasheet = _flatten_files(parsed.get('files'))
        params = []
        for entry in parsed.get('parameters') or []:
            if not isinstance(entry, dict):
                continue
            param_code = entry.get('parameterCode') or ''
            param_name = entry.get('parameterName') or ''
            param_value = (entry.get('parameterValue')
                           or entry.get('parameterDetailValue') or '')
            detail_value = entry.get('parameterDetailValue') or ''
            if not param_name and not param_code:
                continue
            params.append((param_code, param_name, param_value, detail_value))
        fingerprint = hashlib.sha256(json.dumps(
            {
                'name': parsed.get('name'), 'mpn': parsed.get('mpn'),
                'brand': parsed.get('brand'), 'package': parsed.get('package'),
                'category': category_name, 'price': parsed.get('price'),
                'stock': parsed.get('stock'), 'params': params,
                'files': files,
            }, ensure_ascii=False, sort_keys=True, default=str,
        ).encode('utf-8', 'ignore')).hexdigest()[:32]
        vals = {
            'catalog_code': code,
            'market': MARKET_CN,
            'product_id_ext': parsed.get('product_id'),
            'source_url': parsed.get('source_url'),
            'name': parsed.get('name') or code,
            'mpn': parsed.get('mpn') or False,
            'brand': parsed.get('brand') or False,
            'brand_code': brand_code or False,
            'package': parsed.get('package') or False,
            'category_id': category.id,
            'category_name': category_name or category.name,
            'category_path': category_path,
            'catalog_stock': _integer_or_none(parsed.get('stock')),
            'price': _float_or_none(parsed.get('price')),
            'currency': parsed.get('currency') or 'CNY',
            'price_basis': parsed.get('price_basis') or 'page_display_price',
            'image_url': _pick_url(parsed.get('image_url')),
            'has_image': bool(_pick_url(parsed.get('image_url'))),
            'datasheet_url': datasheet,
            'has_datasheet': bool(datasheet),
            'doc_files_json': json.dumps(files, ensure_ascii=False) if files else False,
            'param_count': len(params),
            'search_text': _search_text(
                code, parsed.get('name'), parsed.get('mpn'),
                parsed.get('brand'), category_name, parsed.get('package')),
            'fetched_at': fields.Datetime.now(),
            'source_fingerprint': fingerprint,
        }
        if item:
            if item.source_fingerprint == fingerprint:
                return item
            item.write(vals)
            item.param_ids.unlink()
        else:
            item = Item.create(vals)
        if params:
            self.env['lab.catalog.param'].sudo().create([
                {'item_id': item.id, 'sequence': 10 + index * 10,
                 'code': param_code, 'name': param_name,
                 'value': param_value, 'detail_value': detail_value}
                for index, (param_code, param_name, param_value, detail_value)
                in enumerate(params)
            ])
        return item

    # ------------------------------------------------------------------ misc
    def _searchable_text(self):
        """Only used by diagnostics/tests; never expose to clients."""
        self.ensure_one()
        return ' '.join(filter(None, [self.query_raw, self.query_norm]))
