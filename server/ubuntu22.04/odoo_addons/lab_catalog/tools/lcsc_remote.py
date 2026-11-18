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
* 大于 5 个字符的关键词只做**候选检索**（搜索接口返回的名称/型号/封装/C 码），
  不打开中文详情页、不写库；只有人选定某个 C 码后才真正抓取；
* 中文站点是公开页面，但仍是外部依赖：调用方必须限流并把失败当作可恢复错误。
"""
import http.client
import json
import re
import socket
import time
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


MIN_KEYWORD_LEN = 5      # "至少 5 个字符且含字母才换候选"（如 TLV77、100nF）


def normalize_keyword(value):
    """Return a KEYWORD for a candidate lookup, else ``None``.

    Only used to look for candidates: a keyword never selects a product by
    itself, so a fuzzy or wrong term cannot put the wrong datasheet into the
    library.  A keyword must be at least five characters and contain at least
    one letter - pure numbers ("123456") are rejected so an arbitrary digit
    string never reaches LCSC.
    """
    if value is None:
        return None
    text = unicodedata.normalize('NFKC', str(value)).strip()
    text = ' '.join(text.split())
    if len(text) < MIN_KEYWORD_LEN:
        return None
    if not any(ch.isalpha() for ch in text):
        return None
    return text


def is_exact_model(query, item):
    return normalize_mpn(query) == normalize_mpn(item.get('productModel'))


def candidates_from(items, limit=10, allowed=None):
    """Cheap candidate rows: name/brand/package only, no detail-page request.

    ``title`` on the search response is the display name ("TI TLV9001IDBVR");
    the Chinese detail page is NOT fetched here.  Non-electronic products are
    dropped because choosing one would only end in ``skipped_non_electronic``.
    """
    allowed = allowed if allowed is not None else allowed_root_ids()
    out = []
    for item in (items or [])[:limit]:
        code = normalize_catalog_code(item.get('productCode'))
        if not code:
            continue
        if classify_root(item.get('parentCatalogId'), item.get('isMro'),
                          allowed) == 'non_electronic':
            continue
        out.append({
            'catalog_code': code,
            'mpn': item.get('productModel') or '',
            'name': item.get('title') or item.get('productName') or '',
            'brand': item.get('brandNameEn') or '',
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
class _IPv4HTTPSConnection(http.client.HTTPSConnection):
    """只用 IPv4 地址的 HTTPS 连接（证书校验仍按域名做 SNI）。

    2026-11-09 生产实测：``wmsc.lcsc.com`` 由 CloudFront 提供，AAAA 记录在本机
    网络上不可达；``urllib`` 会按 getaddrinfo 顺序逐个尝试，单次商品搜索因此
    耗掉 **120 秒**（同一时刻 curl 的 happy eyeballs 只用 0.7 秒），同步抓取
    必然超预算转后台、后台队列也被拖住。这里显式只解析 IPv4。
    """

    def connect(self):
        infos = socket.getaddrinfo(self.host, self.port,
                                   socket.AF_INET, socket.SOCK_STREAM)
        last_error = None
        sock = None
        for family, socktype, proto, _canon, address in infos:
            candidate = socket.socket(family, socktype, proto)
            candidate.settimeout(self.timeout)
            try:
                candidate.connect(address)
            except OSError as exc:
                last_error = exc
                candidate.close()
                continue
            sock = candidate
            break
        if sock is None:
            raise last_error or OSError('no IPv4 address for %s' % self.host)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _IPv4HTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_IPv4HTTPSConnection, req, context=self._context)


_HTTP_OPENER = urllib.request.build_opener(_IPv4HTTPSHandler())


def _open_response(request, timeout):
    """Single seam for tests and for forcing the IPv4-only transport."""
    return _HTTP_OPENER.open(request, timeout=timeout)


def _set_read_timeout(response, seconds):
    """Best effort: cap the socket read timeout for the current budget."""
    sock = getattr(getattr(getattr(response, 'fp', None), 'raw', None),
                   '_sock', None)
    if sock is not None:
        try:
            sock.settimeout(seconds)
        except OSError:
            pass


def _check_host(url):
    host = (urllib.parse.urlsplit(url).hostname or '').lower()
    if host not in ALLOWED_HOSTS:
        raise LcscRemoteError('拒绝访问非立创域名：%s' % host, 'host_not_allowed')


def _request(url, data=None, referer=None, timeout=None, deadline=None):
    _check_host(url)
    # 同步路径传入预算：预算用完就不再发起新请求；还没用完时，单次 socket
    # 超时也不得超过剩余预算，否则最后一个请求会把总耗时才拉长到预算之外。
    effective_timeout = timeout or TIMEOUT
    if deadline is not None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise LcscRemoteError('抓取时间预算已用完，已转入后台队列。',
                                  'budget_exhausted')
        effective_timeout = min(effective_timeout, max(1.0, remaining))
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
        response = _open_response(request, effective_timeout)
        try:
            content_type = response.headers.get('Content-Type', '')
            chunks = []
            size = 0
            while True:
                # 逐块读取并在块间核对预算：服务端慢速吐数据时，单次 socket
                # 超时管不住总耗时，这里保证超过预算立即中止。
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise LcscRemoteError(
                            '抓取时间预算已用完，已转入后台队列。',
                            'budget_exhausted')
                    _set_read_timeout(
                        response,
                        min(effective_timeout, max(1.0, remaining)))
                chunk = response.read(65536)
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > MAX_BYTES:
                    raise LcscRemoteError('立创响应过大，已中止。',
                                          'response_too_large')
            body = b''.join(chunks)
        finally:
            close = getattr(response, 'close', None)
            if close is not None:
                close()
    except LcscRemoteError:
        raise
    except Exception as exc:                 # URLError / HTTPError / timeout
        raise LcscRemoteError('访问立创失败：%s' % exc, 'network_error') from exc
    return body.decode('utf-8', 'replace'), content_type


def _json_request(url, payload=None, timeout=None, deadline=None):
    data = json.dumps(payload).encode('utf-8') if payload is not None else None
    text, _ctype = _request(url, data=data, timeout=timeout, deadline=deadline)
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
def search_products(keyword, page_size=PAGE_SIZE, timeout=None, deadline=None):
    body = _json_request(QUERY_URL, {
        'keyword': keyword,
        'currentPage': 1,
        'pageSize': max(1, min(int(page_size), PAGE_SIZE)),
    }, timeout=timeout, deadline=deadline)
    result = body.get('result') or {}
    items = result.get('dataList') or []
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def resolve_mpn(mpn, timeout=None, deadline=None):
    """Return ``(item, candidates)``.

    ``item`` is set only when exactly one row has an identical ``productModel``.
    Any other outcome returns candidates so the operator can choose; nothing is
    auto-selected from a fuzzy match.
    """
    query = normalize_mpn(mpn)
    if not query:
        raise LcscRemoteError('型号为空。', 'invalid_query')
    items = search_products(query, timeout=timeout, deadline=deadline)
    exact = [item for item in items if is_exact_model(query, item)]
    if len(exact) == 1:
        return exact[0], []
    if exact:
        return None, candidates_from(exact)
    return None, candidates_from(items)


def search_candidates(keyword, limit=10, timeout=None, deadline=None):
    """Search LCSC for a keyword and return NAME-ONLY candidates.

    This is the only entry point for fuzzy/partial terms: it makes one request
    to the public search API and returns what it found.  It never opens the
    Chinese detail page - that happens only after the operator picks one C
    code, so a wrong keyword costs one request, not a bad library row.
    """
    text = normalize_keyword(keyword)
    if not text:
        raise LcscRemoteError('关键词太短，至少需要 5 个字符。', 'invalid_query')
    return candidates_from(
        search_products(text, timeout=timeout, deadline=deadline),
        limit=limit)


def fetch_product_detail(code, timeout=None, deadline=None):
    code = normalize_catalog_code(code)
    if not code:
        raise LcscRemoteError('C 编号无效。', 'invalid_query')
    body = _json_request(DETAIL_URL + '?' + urllib.parse.urlencode(
        {'productCode': code}), timeout=timeout, deadline=deadline)
    result = body.get('result')
    if not isinstance(result, dict) or not result:
        raise LcscRemoteError('立创没有该 C 编号。', 'not_found')
    return result


def fetch_cn_page(product_id, timeout=None, deadline=None):
    pid = str(product_id or '').strip()
    if not pid.isdigit():
        raise LcscRemoteError('中文商品 ID 无效。', 'invalid_product_id')
    url = ITEM_URL % pid
    text, _ctype = _request(url, referer='https://www.szlcsc.com/',
                            timeout=timeout, deadline=deadline)
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


def fetch_one(code, timeout=None, deadline=None):
    """Fetch and parse one product by C code (no Odoo writes)."""
    code = normalize_catalog_code(code)
    if not code:
        raise LcscRemoteError('C 编号无效。', 'invalid_query')
    detail = fetch_product_detail(code, timeout=timeout, deadline=deadline)
    product_id = detail.get('productId') or detail.get('selfProductId')
    html = fetch_cn_page(product_id, timeout=timeout, deadline=deadline)
    parsed = parse_cn_page(html, expected=code)
    parsed['detail'] = detail
    return parsed
