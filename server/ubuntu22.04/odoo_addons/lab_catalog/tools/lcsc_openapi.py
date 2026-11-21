# -*- coding: utf-8 -*-
"""立创商城官方 OpenAPI 客户端（Python 版，不依赖 JVM）。

厂商只提供 Java SDK（jlc-openapi-sdk-lcsc-java-1.3.0）；这里按它在
``SignAuthorization`` 里的签名方式重新实现，供 Odoo 服务端直接调用。

签名（与 SDK 保持一致）::

    stringToSign = METHOD + "\\n" + PATH[?QUERY] + "\\n" + 时间戳(秒) + "\\n"
                   + nonce + "\\n" + BODY + "\\n"
    signature    = Base64(HMAC-SHA256(secretKey, stringToSign))
    Authorization: JOP appid="…",accesskey="…",timestamp="…",nonce="…",signature="…"

凭据只从调用方传入或环境变量读取，任何日志/异常都不打印密钥。

运行自检（只读，不写任何业务数据）::

    LCSC_OPENAPI_BASE_URL=... LCSC_OPENAPI_APP_ID=... \\
    LCSC_OPENAPI_ACCESS_KEY=... LCSC_OPENAPI_SECRET_KEY=... \\
    python -I lcsc_openapi.py --probe TLV9001
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import string
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

SEARCH_PATH = '/lcsc/openapi/product/search/global'
BASIC_PATH = '/lcsc/openapi/sku/product/basic'
PRICE_PATH = '/lcsc/openapi/product/get/price/by/code'
STOCK_PATH = '/lcsc/openapi/stock/select/all/stock/by/id'

# 贴片（SMT）通道：按 C 编号批量取元件资料，响应里带中文参数与阶梯价。
SMT_COMPONENT_PATH = '/smtOpenApi/smtComponent/selectComponentInfoByCodes'
DEFAULT_BASE_URL = 'https://open-api.jlc.com'

AUTH_SCHEME = 'JOP'
DEFAULT_TIMEOUT = 15
_SUCCESS_CODES = (0, 200)


class LcscOpenApiError(Exception):
    """一次调用失败；code 是稳定的机器码，message 是中文字面原因。"""

    def __init__(self, code, message, status=None):
        super().__init__('%s: %s' % (code, message))
        self.code = code
        self.message = message
        self.status = status


def _nonce(length=32):
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def string_to_sign(method, path_with_query, timestamp, nonce, body):
    """SDK 的待签串：五行，每行都以 \\n 结尾（空 body 也要保留那一行）。"""
    return '\n'.join([
        str(method).upper(),
        str(path_with_query),
        str(timestamp),
        str(nonce),
        '' if body is None else str(body),
    ]) + '\n'


def sign(secret_key, payload):
    digest = hmac.new(
        str(secret_key).encode('utf-8'),
        str(payload).encode('utf-8'),
        hashlib.sha256).digest()
    return base64.b64encode(digest).decode('ascii')


def authorization_header(app_id, access_key, signature, timestamp, nonce):
    return ('%s appid="%s",accesskey="%s",timestamp="%s",nonce="%s",'
            'signature="%s"'
            % (AUTH_SCHEME, app_id, access_key, timestamp, nonce, signature))


def _check_base_url(base_url):
    parsed = urllib.parse.urlsplit(str(base_url or '').strip())
    if parsed.scheme != 'https' or not parsed.hostname:
        raise LcscOpenApiError('invalid_base_url',
                               '接入地址必须是 https 的完整域名。')
    if parsed.query or parsed.fragment:
        raise LcscOpenApiError('invalid_base_url',
                               '接入地址不能带查询参数。')
    return base_url.rstrip('/')


class LcscOpenApi(object):
    """一个账号下的只读查询（搜索/资料/价格/库存）。

    写操作（下单/询价/BOM）故意不实现：库存业务仍由本地 Odoo 管理。
    """

    def __init__(self, base_url, app_id, access_key, secret_key,
                 timeout=DEFAULT_TIMEOUT, opener=None):
        if not app_id or not access_key or not secret_key:
            raise LcscOpenApiError('missing_credentials',
                                   '缺少 appId / accessKey / secretKey。')
        self._base_url = _check_base_url(base_url)
        self._app_id = str(app_id)
        self._access_key = str(access_key)
        self._secret_key = str(secret_key)
        self._timeout = timeout
        self._opener = opener or urllib.request.urlopen

    # ------------------------------------------------------------- 传输
    def _post(self, path, payload):
        body = json.dumps(payload or {}, ensure_ascii=False,
                          separators=(',', ':'))
        timestamp = str(int(time.time()))
        nonce = _nonce()
        signature = sign(self._secret_key,
                         string_to_sign('POST', path, timestamp, nonce, body))
        request = urllib.request.Request(
            self._base_url + path,
            data=body.encode('utf-8'),
            method='POST',
            headers={
                'Authorization': authorization_header(
                    self._app_id, self._access_key, signature,
                    timestamp, nonce),
                'Content-Type': 'application/json; charset=utf-8',
                'Accept': 'application/json',
            })
        try:
            response = self._opener(request, timeout=self._timeout)
            raw = response.read()
            status = getattr(response, 'status', None) or 200
        except urllib.error.HTTPError as error:
            status = error.code
            raw = error.read() if hasattr(error, 'read') else b''
        except Exception as error:                      # 网络/DNS/超时
            raise LcscOpenApiError('network_error',
                                   '连接立创开放平台失败：%s'
                                   % error.__class__.__name__)
        try:
            envelope = json.loads(raw.decode('utf-8'))
        except Exception:
            raise LcscOpenApiError(
                'bad_response',
                '立创开放平台返回的不是 JSON（HTTP %s）。' % status, status)
        code = envelope.get('code')
        if status != 200 or code not in _SUCCESS_CODES:
            raise LcscOpenApiError(
                'api_error',
                envelope.get('message') or ('HTTP %s' % status), status)
        return envelope

    # ------------------------------------------------------------- 查询
    def search_products(self, keyword, limit=10):
        """关键词搜索；返回官方原始 data 列表（未做业务过滤）。"""
        envelope = self._post(SEARCH_PATH, {'keyword': keyword})
        rows = envelope.get('data') or []
        if not isinstance(rows, list):
            rows = [rows]
        return rows[:limit]

    def product_basic(self, product_code):
        envelope = self._post(BASIC_PATH,
                              {'productCode': product_code})
        return envelope.get('data')

    def product_price(self, product_code):
        envelope = self._post(PRICE_PATH,
                              {'productCode': product_code})
        return envelope.get('data')

    def stock_by_id(self, product_id):
        envelope = self._post(STOCK_PATH, {'productId': product_id})
        return envelope.get('data')

    def smt_components(self, codes):
        """贴片通道：按 C 编号批量取元件资料（含中文参数与阶梯价）。"""
        wanted = []
        for code in codes or []:
            text = str(code or '').strip().upper()
            if not text:
                continue
            wanted.append(text if text.startswith('C') else 'C' + text)
        if not wanted:
            return []
        envelope = self._post(SMT_COMPONENT_PATH,
                              {'componentCodeList': wanted})
        rows = envelope.get('data') or []
        if not isinstance(rows, list):
            rows = [rows]
        return rows


def candidates_from(rows):
    """官方搜索结果 → 本地候选形状（只保留核对所需的身份字段）。"""
    out = []
    for row in rows or []:
        code = str(row.get('productCode') or '').strip()
        if not code:
            continue
        if not code.upper().startswith('C'):
            code = 'C' + code
        out.append({
            'catalog_code': code,
            'mpn': row.get('productModel') or '',
            'name': row.get('productName') or '',
            'brand': row.get('brandName') or '',
            'package': row.get('standard') or '',
            'description': row.get('description') or '',
            'catalog_stock': row.get('gdStockNum'),
            'overseas_stock': row.get('jsStockNum'),
        })
    return out


def parameters_from_text(text):
    """``paramTextAll``（"阻值:10kΩ,精度:±1%"）→ 本地参数列表。"""
    out = []
    for chunk in str(text or '').split(','):
        chunk = chunk.strip()
        if not chunk or ':' not in chunk:
            continue
        name, _, value = chunk.partition(':')
        name, value = name.strip(), value.strip()
        if name:
            out.append({'parameterName': name, 'parameterValue': value})
    return out


def item_from_smt(row):
    """贴片通道的一行 → ``lab_catalog_fetch._upsert_item`` 需要的形状。"""
    code = str(row.get('componentCode') or '').strip().upper()
    if not code:
        return None
    if not code.startswith('C'):
        code = 'C' + code
    tiers = []
    for tier in row.get('smtComponentPriceInfoVOList') or []:
        try:
            tiers.append({
                'start': int(tier.get('startNumber') or 0),
                'end': int(tier.get('endNumber')) if tier.get('endNumber') is not None else -1,
                'price': float(tier.get('productPrice')),
            })
        except (TypeError, ValueError):
            continue
    price = None
    if tiers:
        price = sorted(tiers, key=lambda t: t['start'])[0]['price']
    return {
        'code': code,
        'product_id': row.get('componentId'),
        'name': row.get('componentName') or '',
        'mpn': row.get('componentModel') or '',
        'brand': row.get('componentBrand') or '',
        'package': row.get('componentSpecification') or '',
        'category_name': row.get('componentType') or '',
        'stock': row.get('stockNum'),
        'price': price,
        'currency': 'CNY',
        'price_basis': 'openapi_smt_tier_price',
        'pack_quantity': row.get('encapsulationNumber'),
        'parameters': parameters_from_text(row.get('paramTextAll')),
        'price_tiers': tiers,
        'source': 'openapi_smt',
    }


def items_from_smt(rows):
    out = []
    for row in rows or []:
        item = item_from_smt(row)
        if item:
            out.append(item)
    return out


def merge_into_parsed(parsed, official):
    """把官方 SMT 资料覆盖到页面解析结果上（分类/文档仍用页面数据）。"""
    merged = dict(parsed or {})
    if not official:
        return merged
    for key in ('name', 'mpn', 'brand', 'package'):
        if official.get(key):
            merged[key] = official[key]
    if official.get('stock') is not None:
        merged['stock'] = official['stock']
    if official.get('price') is not None:
        merged['price'] = official['price']
        merged['price_basis'] = official.get('price_basis') or 'openapi_smt_tier_price'
        merged['currency'] = official.get('currency') or 'CNY'
    if official.get('parameters'):
        merged['parameters'] = official['parameters']
    merged['price_tiers'] = official.get('price_tiers') or []
    merged['pack_quantity'] = official.get('pack_quantity')
    merged['official_source'] = official.get('source') or 'openapi_smt'
    return merged


def client_from_env(environ=None, timeout=DEFAULT_TIMEOUT):
    environ = environ if environ is not None else os.environ
    return LcscOpenApi(
        environ.get('LCSC_OPENAPI_BASE_URL') or DEFAULT_BASE_URL,
        environ.get('LCSC_OPENAPI_APP_ID', ''),
        environ.get('LCSC_OPENAPI_ACCESS_KEY', ''),
        environ.get('LCSC_OPENAPI_SECRET_KEY', ''),
        timeout=timeout)


def client_from_csv(path, row=1, app_id=None, base_url=None, environ=None):
    """凭据文件的本地自检路径。

    文件每行是 ``(accessKey, secretKey)``；appId 由控制台单独给出
    （18 位数字），通过参数或 ``LCSC_OPENAPI_APP_ID`` 提供。只读，
    不打印任何一列的内容。
    """
    environ = environ if environ is not None else os.environ
    app_id = app_id or environ.get('LCSC_OPENAPI_APP_ID', '')
    if not app_id:
        raise LcscOpenApiError('missing_app_id',
                               '需要 appId（控制台给出，不是凭据文件里的值）。')
    import csv as _csv
    with open(path, encoding='utf-8-sig', newline='') as handle:
        rows = [r for r in _csv.reader(handle) if any(c.strip() for c in r)]
    if len(rows) < row:
        raise LcscOpenApiError('bad_credentials_file',
                               '凭据文件里没有第 %d 组。' % row)
    cells = [c.strip() for c in rows[row - 1]]
    if len(cells) < 2:
        raise LcscOpenApiError('bad_credentials_file',
                               '凭据文件每行需要两列。')
    access_key, secret_key = cells[0], cells[1]
    return LcscOpenApi(
        base_url or environ.get('LCSC_OPENAPI_BASE_URL') or DEFAULT_BASE_URL,
        app_id, access_key, secret_key)


def _probe(keyword, credentials=None, row=1, base_url=None, app_id=None):
    """只读探针：只打印状态与字段名，绝不打印凭据或完整响应。"""
    try:
        if credentials:
            client = client_from_csv(credentials, row=row, app_id=app_id,
                                     base_url=base_url)
        else:
            client = client_from_env()
    except LcscOpenApiError as error:
        print('CONFIG_ERROR %s %s' % (error.code, error.message))
        return 2
    print('BASE_URL_SET %s'
          % bool(base_url or os.environ.get('LCSC_OPENAPI_BASE_URL')))
    try:
        if keyword.upper().startswith('C') and keyword[1:].isdigit():
            rows = client.smt_components([keyword])
            print('CHANNEL smt')
            print('RAW_FIELDS %s'
                  % (','.join(sorted(rows[0].keys())) if rows else ''))
            for item in items_from_smt(rows)[:3]:
                print('ITEM %s | %s | %s | %s | stock=%s | price=%s | params=%d'
                      % (item['code'], item['name'], item['mpn'],
                         item['package'], item['stock'], item['price'],
                         len(item['parameters'])))
            return 0 if rows else 3
        rows = client.search_products(keyword, limit=5)
    except LcscOpenApiError as error:
        print('PROBE_FAILED code=%s status=%s message=%s'
              % (error.code, error.status, error.message))
        return 1
    print('PROBE_OK rows=%d' % len(rows))
    if rows:
        print('FIELDS %s' % ','.join(sorted(rows[0].keys())))
        for item in candidates_from(rows)[:3]:
            print('CANDIDATE %s | %s | %s | %s'
                  % (item['catalog_code'], item['name'],
                     item['mpn'], item['package']))
    return 0


if __name__ == '__main__':
    args = sys.argv[1:]
    if args and args[0] == '--probe':
        keyword_parts = []
        credentials = None
        row = 1
        base_url = None
        app_id = None
        index = 1
        while index < len(args):
            value = args[index]
            if value == '--credentials' and index + 1 < len(args):
                credentials = args[index + 1]
                index += 2
            elif value == '--row' and index + 1 < len(args):
                row = int(args[index + 1])
                index += 2
            elif value == '--base-url' and index + 1 < len(args):
                base_url = args[index + 1]
                index += 2
            elif value == '--app-id' and index + 1 < len(args):
                app_id = args[index + 1]
                index += 2
            else:
                keyword_parts.append(value)
                index += 1
        if not keyword_parts:
            print('usage: lcsc_openapi.py --probe <keyword> '
                  '[--credentials FILE] [--row N] [--app-id ID] '
                  '[--base-url https://…]')
            sys.exit(2)
        sys.exit(_probe(' '.join(keyword_parts), credentials=credentials,
                        row=row, base_url=base_url, app_id=app_id))
    print('usage: python -I lcsc_openapi.py --probe <keyword>')
    sys.exit(2)
