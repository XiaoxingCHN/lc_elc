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
import time

from odoo import api, fields, models

from odoo.addons.lab_inventory.tools.param_search import build_search_params

from ..tools import lcsc_openapi, lcsc_remote

_logger = logging.getLogger(__name__)

MARKET_CN = 'cn'
LOCK_ID = 87431001          # pg_try_advisory_lock：同一时间只允许一个 worker
ACTIVE_STATES = ('queued', 'resolving', 'fetching')
TERMINAL_STATES = ('done', 'failed', 'skipped_non_electronic', 'review',
                   'not_found', 'candidates')
MAX_ATTEMPTS = 3
INLINE_BUDGET = 15          # 同步抓取的总预算（秒）
INLINE_TIMEOUT = 6          # 同步抓取时单次 HTTP 超时（秒）


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
        [('c_code', 'C 编号'), ('mpn', '型号'), ('keyword', '关键词')],
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

    @api.model
    def _process_inline(self, record, budget_seconds=INLINE_BUDGET):
        """Process one just-created request inside the HTTP request.

        The caller's worker pays for the fetch, so it is bounded twice: a wall
        clock budget stops any *new* HTTP call, and the advisory lock falls
        back to the per-minute cron when another fetch is already running.
        Anything unfinished stays ``queued`` for the cron to pick up.
        """
        if not record or record.state != 'queued':
            return record
        cr = self.env.cr
        # Transaction-scoped lock: PostgreSQL releases it at COMMIT/ROLLBACK,
        # even if the worker is killed mid-request, so a pooled connection can
        # never keep the fetch lock forever. It still conflicts with the cron's
        # session-scoped lock on the same key.
        cr.execute('SELECT pg_try_advisory_xact_lock(%s)', [LOCK_ID])
        if not cr.fetchone()[0]:
            return record
        deadline = time.monotonic() + max(1.0, float(budget_seconds))
        try:
            with cr.savepoint():
                record._process_one(timeout=INLINE_TIMEOUT, deadline=deadline)
        except Exception:                       # noqa: BLE001 - never fail the API
            _logger.exception('lab_catalog: inline fetch %s failed', record.id)
        return record

    def _process_one(self, timeout=None, deadline=None):
        self.ensure_one()
        if self.state != 'queued':
            return
        self.write({'state': 'resolving' if self.query_kind == 'mpn'
                    else 'fetching',
                    'started_at': fields.Datetime.now(),
                    'attempts': self.attempts + 1,
                    'finished_at': False})
        try:
            self._run(timeout=timeout, deadline=deadline)
        except lcsc_remote.LcscRemoteError as exc:
            self._handle_remote_error(exc)
        except Exception as exc:                       # noqa: BLE001 - report to operator
            _logger.exception('lab_catalog: fetch request %s failed', self.id)
            self._set('failed', '抓取失败：%s' % exc)

    def _handle_remote_error(self, exc):
        state = 'failed'
        if exc.code == 'not_found':
            state = 'not_found'
        if exc.code == 'budget_exhausted':
            # 同步请求的时间预算用完：不算失败，交回队列让 cron 接着抓。
            # 这次尝试没有真正发出完整的抓取，不能吃掉 cron 的重试次数。
            self.write({'state': 'queued', 'message': exc.message,
                        'attempts': max(0, self.attempts - 1),
                        'finished_at': False})
            return
        message = {
            'not_found': '立创未找到该型号或 C 编号。',
            'verification_page': '立创中文详情页触发了访问验证（风控，不是实验室系统故障）；'
                                 '官方接口资料不受影响，稍后重试即可。',
            'network_error': '无法连接立创，请稍后重试。',
        }.get(exc.code, exc.message)
        if state == 'failed' and self.attempts < MAX_ATTEMPTS:
            # 外部站点偶发超时：退回队列，让下一轮 cron 再试。
            self.write({'state': 'queued', 'message': message,
                        'finished_at': False})
            return
        self._set(state, message)

    def _run(self, timeout=None, deadline=None):
        query = self.query_norm
        if self.query_kind == 'keyword':
            # 片段/模糊关键词只做候选检索：用搜索接口返回的名称、型号、封装和
            # C 码，不打开中文详情页，也不写库。人选定某个 C 码后会以
            # query_kind='c_code' 重新提交，那一步才真正抓取。
            candidates = lcsc_remote.search_candidates(
                query, timeout=timeout, deadline=deadline)
            if not candidates:
                self._set('not_found',
                          '立创没有找到匹配的器件，请改用完整型号或 C 编号。')
            else:
                self._set(
                    'candidates',
                    '找到 %d 个候选，请选择要入库的一个。' % len(candidates),
                    candidates_json=json.dumps(candidates, ensure_ascii=False))
            return
        if self.query_kind == 'mpn':
            item, candidates = lcsc_remote.resolve_mpn(
                query, timeout=timeout, deadline=deadline)
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

        official = self._official_item(code, deadline=deadline)

        detail = lcsc_remote.fetch_product_detail(
            code, timeout=timeout, deadline=deadline)
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
        degraded = False
        try:
            parsed = lcsc_remote.parse_cn_page(
                lcsc_remote.fetch_cn_page(product_id, timeout=timeout,
                                          deadline=deadline),
                expected=code)
        except lcsc_remote.LcscRemoteError as exc:
            # 中文详情页可能被立创风控验证页拦截。官方 SMT 通道若已经给出
            # 名称/型号/品牌/封装/库存/价格/参数，就只有分类细分与文档缺失，
            # 让整条资料失败等于把已经拿到的参数一起丢掉（用户看到的就是
            # "详情里什么都没有"）。这里按官方事实先入库，如实告知缺什么。
            if exc.code != 'verification_page' or not official:
                raise
            parsed = self._parsed_from_official(official, code, detail, product_id)
            degraded = True
        if official and not degraded:
            parsed = lcsc_openapi.merge_into_parsed(parsed, official)
        self.write({'product_id_ext': parsed['product_id']})

        leaf, root_id, category_name, category_path = self._resolve_category(parsed)
        if not leaf:
            self._set('review', '分类无法映射到现有分类树，已跳过入库。')
            return
        if root_id is not None and root_id not in self._allowed_roots():
            self._set('skipped_non_electronic',
                      '该商品不属于电子元器件，未加入资料库。')
            return

        catalog_item, changed = self._upsert_item(parsed, leaf, category_name,
                                                  category_path)
        if changed:
            if degraded:
                message = ('已按官方接口收录（中文详情页被立创风控拦截：'
                           '名称/型号/品牌/封装/库存/价格/参数已到位，'
                           '分类细分与文档暂时缺失）。')
            else:
                message = '已收录，正在刷新。'
            self._set('done', message, result_item_id=catalog_item.id)
            self.env['lab.catalog.item']._revision('catalog', bump=True)
        else:
            # 单条刷新没有新内容时不做任何写入，也不触发全库 revision 变化。
            self._set('done', '资料未变化，无需更新。',
                      result_item_id=catalog_item.id)

    # ----------------------------------------------------------------- official
    @api.model
    def _parsed_from_official(self, official, code, detail, product_id):
        """官方 SMT 通道事实 → ``_upsert_item`` 需要的形状。

        仅在中文详情页不可用时使用：分类优先按官方 ``componentType`` 名称
        匹配本地分类树（与中文商城同一套分类名），匹配不到再退回 wmsc
        详情给出的 ``parentCatalogId``（一级分类），最后由 ``_resolve_category``
        统一复核根分类白名单。
        """
        product_id = str(product_id or official.get('product_id') or '')
        parameters = []
        for entry in official.get('parameters') or []:
            name = (entry.get('parameterName') or '').strip()
            if not name:
                continue
            parameters.append({
                'parameterCode': '',
                'parameterName': name,
                'parameterValue': entry.get('parameterValue') or '',
                'parameterDetailValue': '',
            })
        return {
            'code': code,
            'product_id': product_id,
            'mpn': official.get('mpn') or detail.get('productModel') or '',
            'name': official.get('name') or '',
            'brand': official.get('brand') or '',
            'package': official.get('package') or '',
            'price': official.get('price'),
            'price_basis': official.get('price_basis') or '',
            'currency': official.get('currency') or 'CNY',
            'stock': official.get('stock'),
            'parameters': parameters,
            'catalog': self._official_category(official, detail),
            'files': [],
            'image_url': '',
            'source_url': (lcsc_remote.ITEM_URL % product_id)
                          if product_id.isdigit() else '',
        }

    @api.model
    def _official_category(self, official, detail):
        """官方分类名 → 本地分类记录（``_resolve_category`` 的输入形状）。"""
        Cat = self.env['lab.catalog.category'].sudo()
        type_name = (official.get('category_name') or '').strip()
        record = Cat.browse()
        if type_name:
            matches = Cat.search([('name', '=', type_name)])
            if len(matches) > 1:
                # 分类名可能在不同子树重名：优先带上级（叶子）的那条
                matches = matches.filtered(lambda c: bool(c.parent_id)) or matches
            record = matches[:1]
        parent_id = detail.get('parentCatalogId')
        if not record and parent_id:
            try:
                record = Cat.search(
                    [('catalog_id', '=', int(parent_id))], limit=1)
            except (TypeError, ValueError):
                record = Cat.browse()
        if not record:
            return {}
        return {
            'catalogId': record.catalog_id,
            'parentId': record.parent_id.catalog_id if record.parent_id else None,
            'catalogName': record.name,
        }
    def _official_item(self, code, deadline=None):
        """官方 SMT 通道（只读）。未配置凭据、超预算或出错时返回 None。

        官方接口只提供器件资料/价格/库存，**不写库存**；分类与文档仍由页面
        解析给出，拿到结果后覆盖名称、型号、品牌、封装、库存、价格与中文参数。
        """
        if deadline is not None and time.monotonic() >= deadline:
            return None
        try:
            client = lcsc_openapi.client_from_env(timeout=INLINE_TIMEOUT)
        except lcsc_openapi.LcscOpenApiError:
            return None                       # 未配置凭据：静默跳过
        try:
            rows = client.smt_components([code])
        except lcsc_openapi.LcscOpenApiError as exc:
            _logger.warning('立创官方接口不可用（%s），本轮继续用页面解析。',
                            exc.code)
            return None
        return lcsc_openapi.item_from_smt(rows[0]) if rows else None

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
                # 资料没变也要补档案：占位档案可能在抓取之后才建立。
                self._enrich_stub_templates(code)
                return item, False
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
        self._enrich_stub_templates(code)
        return item, True

    @api.model
    def _enrich_stub_templates(self, code):
        """把资料库事实补进该 C 编号已有的本地档案。

        入库现场按 ``lcsc:Cxxx`` 建的最小档案名是
        "立创物料 Cxxx（待补全）"；资料抓取成功后如果不回填，袋标签与库存
        卡片会一直显示占位名。``_lab_apply_catalog_facts`` 只填空字段，
        手填值优先，不覆盖人工修改。
        """
        templates = self.env['product.template'].sudo().search(
            [('lab_lcsc_code_norm', '=', code)])
        if not templates:
            return
        applied = templates._lab_apply_catalog_facts(code)
        if applied:
            # 标签/卡片读的是模板字段：补上了就让客户端缓存失效
            self.env['lab.catalog.item']._touch_inventory_revision()

    # ------------------------------------------------------------------ misc
    def _searchable_text(self):
        """Only used by diagnostics/tests; never expose to clients."""
        self.ensure_one()
        return ' '.join(filter(None, [self.query_raw, self.query_norm]))
