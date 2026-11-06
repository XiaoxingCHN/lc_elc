# -*- coding: utf-8 -*-
"""单条立创资料抓取（不依赖 Odoo，可被纯 Python 测试直接加载）。

用途
----
统一器件库搜索未命中时，按 **精确 C 编号** 或 **精确 MPN** 抓取一条中文资料：

1. ``POST https://wmsc.lcsc.com/ftps/wm/product/query/list``
   —— 只做 MPN -> C 码定位，返回 ``productCode`` / ``productModel`` /
   ``parentCatalogId`` / ``isMro``。
2. ``GET https://wmsc.lcsc.com/ftps/wm/product/detail?productCode=...``
   —— 确认商品存在，取得中文商品 ``productId`` 与一级分类。
3. ``GET https://item.szlcsc.com/<productId>.html``
   —— 唯一的数据来源：中文名称、品牌、分类、参数、封装、CNY 价格、库存。

边界
----
* 只允许固定主机（防 SSRF），不接受调用方传入 URL；
* 不访问中文分类页/搜索页（WAF 203），不求解验证、不伪造 cookie；
* MPN 必须 ``productModel`` 精确相等，模糊结果只作为候选返回；
* 中文站点是公开页面，但仍是外部依赖：调用方必须限流并把失败当作可恢复错误。
"""
import json
import re
import unicodedata
import urllib.parse
import urllib.request

QUERY_URL = 'https://wmsc.lcsc.com/ftps/wm/product/query/list'
DETAIL_URL = 'https://wmsc.lcsc.com/ftps/wm/product/detail'
ITEM_URL = 'https://item.szlcsc.com/%s.html'
ALLOWED_HOSTS = frozenset({'wmsc.lcsc.com', 'item.szlcsc.com'})
USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
              'AppleWebKit/537.36 (KHTML, like Gecko) '
              'Chrome/124.0 Safari/537.36')
TIMEOUT = 15
MAX_BYTES = 2 * 1024 * 1024
PAGE_SIZE = 10

_C_CODE_RE = re.compile(r'^C([0-9]+)$')
_MPN_RE = re.compile(r'^[A-Z0-9][A-Z0-9._+\-/]*$')
_NEXT_DATA_RE = re.compile(
    r'<script\b[^>]*\bid="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


class LcscRemoteError(Exception):
    """A fetch failed in a way the queue can report to the operator."""

    def __init__(self, message, code='remote_error'):
        super().__init__(message)
        self.message = message
        self.code = code


# ---------------------------------------------------------------- identity
def normalize_catalog_code(value):
    """'c 32445874 ' -> 'C32445874'; invalid -> None."""
    if value is None:
        return None
    text = unicodedata.normalize('NFKC', str(value)).strip()
    text = text.replace('﻿', '').replace('​', '')
    text = ''.join(text.split()).upper()
    match = _C_CODE_RE.match(text)
    if not match or int(match.group(1)) <= 0:
        return None
    return 'C' + match.group(1)


def normalize_mpn(value):
    if value is None:
        return None
    text = unicodedata.normalize('NFKC', str(value)).strip()
    text = ''.join(text.split()).upper()
    return text or None


def normalize_query(value):
    """Return ``(kind, normalized)``; ``(None, None)`` when not fetchable.

    Only exact C codes and full MPNs are accepted.  A short keyword such as
    "电容" or "TLV" is intentionally rejected: the public search endpoint
    returns thousands of unrelated rows for those.
    """
    if value is None:
        return None, None
    raw = unicodedata.normalize('NFKC', str(value)).strip()
    if not raw:
        return None, None
    code = normalize_catalog_code(raw)
    if code:
        return 'c_code', code
    mpn = normalize_mpn(raw)
    if not mpn or not (4 <= len(mpn) <= 60):
        return None, None
    if not _MPN_RE.match(mpn):
        return None, None
    # Require at least one ASCII letter: prevents "12345" being treated as an MPN.
    if not re.search(r'[A-Z]', mpn):
        return None, None
    return 'mpn', mpn


def is_exact_model(query, item):
    return normalize_mpn(query) == normalize_mpn(item.get('productModel'))


def candidates_from(items, limit=10):
    out = []
    for item in (items or [])[:limit]:
        code = normalize_catalog_code(item.get('productCode'))
        if not code:
            continue
        out.append({
            'catalog_code': code,
            'mpn': item.get('productModel') or '',
            'package': item.get('encapStandard') or '',
            'parent_catalog_id': item.get('parentCatalogId'),
            'is_mro': bool(item.get('isMro')),
        })
    return out


# ---------------------------------------------------------------- policy
def load_electronics_filter(path=None):
    """Load the same policy the crawler uses (bundled copy)."""
    if path is None:
        import os
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            'lcsc_electronics_filter.json')
    with open(path, 'r', encoding='utf-8') as handle:
        return json.load(handle)


def allowed_root_ids(policy=None):
    policy = policy or load_electronics_filter()
    return {int(x) for x in policy.get('allowed_root_ids') or []}


def classify_root(parent_catalog_id, is_mro, allowed=None):
    """'electronic' / 'non_electronic' / 'unknown' for an LCSC root id.

    Unknown means "we could not map it"; such a product is NOT fetched
    further (the queue marks it ``review``), matching the crawler policy.
    """
    allowed = allowed if allowed is not None else allowed_root_ids()
    if is_mro is True:
        return 'non_electronic'
    try:
        root_id = int(parent_catalog_id)
    except (TypeError, ValueError):
        return 'unknown'
    if root_id <= 0:
        return 'unknown'
    return 'electronic' if root_id in allowed else 'non_electronic'


# ---------------------------------------------------------------- HTTP
def _check_host(url):
    host = (urllib.parse.urlsplit(url).hostname or '').lower()
    if host not in ALLOWED_HOSTS:
        raise LcscRemoteError('拒绝访问非立创域名：%s' % host, 'host_not_allowed')


def _request(url, data=None, referer=None):
    _check_host(url)
    headers = {
        'User-Agent': USER_AGENT,
        'Accept': 'application/json,text/html;q=0.9,*/*;q=0.8',
        'Accept-Encoding': 'identity',
    }
    if data is not None:
        headers['Content-Type'] = 'application/json'
    if referer:
        headers['Referer'] = referer
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = response.read(MAX_BYTES + 1)
            content_type = response.headers.get('Content-Type', '')
    except Exception as exc:                 # URLError / HTTPError / timeout
        raise LcscRemoteError('访问立创失败：%s' % exc, 'network_error') from exc
    if len(body) > MAX_BYTES:
        raise LcscRemoteError('立创响应过大，已中止。', 'response_too_large')
    return body.decode('utf-8', 'replace'), content_type


def _json_request(url, payload=None):
    data = json.dumps(payload).encode('utf-8') if payload is not None else None
    text, _ctype = _request(url, data=data)
    try:
        body = json.loads(text)
    except ValueError as exc:
        raise LcscRemoteError('立创返回了非 JSON 内容。', 'bad_response') from exc
    if not isinstance(body, dict):
        raise LcscRemoteError('立创返回结构异常。', 'bad_response')
    if body.get('code') not in (None, 200):
        raise LcscRemoteError(body.get('msg') or '立创接口返回错误。', 'remote_error')
    return body


# ---------------------------------------------------------------- API
def search_products(keyword, page_size=PAGE_SIZE):
    body = _json_request(QUERY_URL, {
        'keyword': keyword,
        'currentPage': 1,
        'pageSize': max(1, min(int(page_size), PAGE_SIZE)),
    })
    result = body.get('result') or {}
    items = result.get('dataList') or []
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def resolve_mpn(mpn):
    """Return ``(item, candidates)``.

    ``item`` is set only when exactly one row has an identical ``productModel``.
    Any other outcome returns candidates so the operator can choose; nothing is
    auto-selected from a fuzzy match.
    """
    query = normalize_mpn(mpn)
    if not query:
        raise LcscRemoteError('型号为空。', 'invalid_query')
    items = search_products(query)
    exact = [item for item in items if is_exact_model(query, item)]
    if len(exact) == 1:
        return exact[0], []
    if exact:
        return None, candidates_from(exact)
    return None, candidates_from(items)


def fetch_product_detail(code):
    code = normalize_catalog_code(code)
    if not code:
        raise LcscRemoteError('C 编号无效。', 'invalid_query')
    body = _json_request(DETAIL_URL + '?' + urllib.parse.urlencode(
        {'productCode': code}))
    result = body.get('result')
    if not isinstance(result, dict) or not result:
        raise LcscRemoteError('立创没有该 C 编号。', 'not_found')
    return result


def fetch_cn_page(product_id):
    pid = str(product_id or '').strip()
    if not pid.isdigit():
        raise LcscRemoteError('中文商品 ID 无效。', 'invalid_product_id')
    url = ITEM_URL % pid
    text, _ctype = _request(url, referer='https://www.szlcsc.com/')
    if '__NEXT_DATA__' not in text:
        raise LcscRemoteError('中文详情页缺少商品数据，可能被验证页拦截。',
                              'verification_page')
    return text


def parse_cn_page(html, expected=None):
    """Parse the Chinese item page into the same shape the crawler stores.

    Only the Chinese page is a data source: names, brand, parameters,
    category and CNY price all come from here.
    """
    match = _NEXT_DATA_RE.search(html or '')
    if not match:
        raise LcscRemoteError('中文详情页没有 __NEXT_DATA__。', 'bad_response')
    try:
        page = json.loads(match.group(1))['props']['pageProps']
    except (ValueError, KeyError, TypeError) as exc:
        raise LcscRemoteError('中文详情页 JSON 解析失败。', 'bad_response') from exc
    web = page.get('webData') or {}
    record = web.get('productRecord') or {}
    code = normalize_catalog_code(
        record.get('productCode') or record.get('selfProductCode'))
    if not code:
        raise LcscRemoteError('中文详情页缺少合法 C 编号。', 'bad_response')
    expected = normalize_catalog_code(expected)
    if expected and code != expected:
        raise LcscRemoteError(
            '详情页 C 编号不匹配：期望 %s，实际 %s。' % (expected, code),
            'code_mismatch')
    product_id = str(record.get('productId') or record.get('selfProductId') or '')
    if not product_id.isdigit():
        raise LcscRemoteError('中文详情页缺少商品 ID。', 'bad_response')
    catalog = web.get('currentCatalog') or {}
    if not isinstance(catalog, dict):
        catalog = {}
    return {
        'code': code,
        'product_id': product_id,
        'mpn': record.get('productModel') or '',
        'name': record.get('productName') or '',
        'brand': record.get('productGradePlateName') or '',
        'package': record.get('encapsulationModel') or '',
        'price': page.get('price'),
        'encaption_price': record.get('encaptionPrice'),
        'price_basis': 'page_display_price',
        'currency': 'CNY',
        'stock': record.get('stockNumber'),
        'parameters': web.get('paramList') or [],
        'catalog': catalog,
        'files': record.get('fileTypeVOList') or [],
        'image_url': record.get('breviaryImageUrl') or '',
        'source_url': ITEM_URL % product_id,
    }


def fetch_one(code):
    """Fetch and parse one product by C code (no Odoo writes)."""
    code = normalize_catalog_code(code)
    if not code:
        raise LcscRemoteError('C 编号无效。', 'invalid_query')
    detail = fetch_product_detail(code)
    product_id = detail.get('productId') or detail.get('selfProductId')
    html = fetch_cn_page(product_id)
    parsed = parse_cn_page(html, expected=code)
    parsed['detail'] = detail
    return parsed
