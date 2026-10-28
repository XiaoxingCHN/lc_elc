# -*- coding: utf-8 -*-
"""纯函数：路由/跳转/身份/主机决策与展示格式化。

设计约束
--------
本文件不 import odoo，因此可以在没有 Odoo 运行时的环境里直接单测
（见 tests/test_paths.py）。需要请求上下文的逻辑放 controllers/。

两处契约与既有实现严格对齐，避免前端自造规则：
* itemKey 解析与 lab_catalog/models/lab_catalog_identity.py 一致
  （lcsc: 走 NFKC+大写+C+数字且数值>0；lab: 仅十进制数字）。
* 跳转校验按 URL 解析做同源判断，不再用「路径里出现冒号就拒绝」的粗暴规则，
  否则 /lab/items/lcsc:C123、/lab/items/lab:1 这类合法业务路径会被误拒。
"""
import re
import unicodedata
from urllib.parse import quote, unquote, urlencode, urlsplit

#: 规范挂载前缀（兼容/开发入口，不是最终对外地址；最终目标是管理站点根 /）
CANONICAL_BASE = '/team'

#: 根级别别名前缀（只属于本项目自己的命名空间，不接管 /）
ROOT_ALIASES = ('/login', '/logout', '/lab', '/scan', '/account')

#: 业务页面的根级别入口（P3）。必须**精确**列出 /lab/* 页面：/lab 前缀只用于
#: 判断基址，绝不能用它把所有 /lab/** 都当成"自有页面"——那会把 /lab/api、
#: /lab/scan（旧控制台）、/lab/labels/plan（旧表单端点）、/lab/client/updates
#: 一起卷进 root_aliases 开关，破坏既有路由语义（见 tests/test_paths.py）。
WORKFLOW_ROOT_PATHS = (
    '/scan',
    '/account',
    '/lab/receipts',
    '/lab/bags',
    '/lab/labels',
    '/lab/issues',
    '/lab/locations',
    '/lab/location-mappings',
    '/lab/history',
    '/lab/materials',
    '/lab/settings',
)

#: 带子路径的业务页面（/lab/bags/<id>、/lab/issues/new）。
WORKFLOW_ROOT_PREFIXES = ('/lab/bags/', '/lab/issues/')

#: 分页
DEFAULT_LIMIT = 24
MAX_LIMIT = 100

#: itemKey 前缀（与 lab_catalog 的 parse_item_key 保持一致）
ITEM_KEY_PREFIXES = ('lcsc:', 'lab:')

#: 与 lab_catalog 完全一致的 C 编号正则：C + 一个或多个数字（真实数据含 C1 这类短码）
_CATALOG_RE = re.compile(r'^C([0-9]+)$')

#: 管理站点根路径（仅根路径允许被 management Host 接管）
MANAGEMENT_ROOT_PATHS = ('/',)


# ---------------------------------------------------------------------------
# 跳转安全
# ---------------------------------------------------------------------------
def _has_control_chars(value):
    return any(ord(ch) < 0x20 or ord(ch) == 0x7f for ch in value)


def _safe_relative_shape(value):
    """单个（已解码）字符串是否仍是安全的站内相对路径。"""
    if not isinstance(value, str) or not value:
        return False
    if not value.startswith('/'):
        return False
    if value.startswith('//'):          # 协议相对 URL
        return False
    if '\\' in value or _has_control_chars(value):
        return False
    parts = urlsplit(value)
    if parts.scheme or parts.netloc:    # 任何 scheme/netloc 都离开本站
        return False
    return True


def normalize_next(raw, default=None):
    """把 next 参数收敛成安全的站内相对路径，防开放重定向。

    规则：
      * 必须是字符串且以单个 / 开头；
      * 拒绝协议相对（//host）、反斜杠、控制字符、带 scheme/netloc 的值；
      * 对百分号编码最多做 3 轮解码后再校验一次，拦截 %2f%2f 与 %5C 这类绕过；
      * 允许路径里出现冒号（/lab/items/lcsc:C123 必须原样保留）。
    返回原始字符串（不做解码改写），不安全时返回 default。
    """
    fallback = default if default is not None else CANONICAL_BASE
    if not isinstance(raw, str):
        return fallback
    # 控制字符必须在 strip 之前判定：否则 '/lab\n' 会被 strip 成 '/lab' 而放行
    if _has_control_chars(raw) or '\\' in raw:
        return fallback
    value = raw.strip()
    if not value or not value.startswith('/'):
        return fallback

    probe = value
    for _ in range(3):
        if not _safe_relative_shape(probe):
            return fallback
        decoded = unquote(probe)
        if decoded == probe:
            break
        probe = decoded
    if not _safe_relative_shape(probe):
        return fallback
    return value


# ---------------------------------------------------------------------------
# 挂载前缀
# ---------------------------------------------------------------------------
def resolve_base(path, root_aliases_enabled=True):
    """由当前请求路径推断页面链接基址。"""
    if not isinstance(path, str):
        return CANONICAL_BASE
    if path == CANONICAL_BASE or path.startswith(CANONICAL_BASE + '/'):
        return CANONICAL_BASE
    if root_aliases_enabled:
        for alias in ROOT_ALIASES:
            if path == alias or path.startswith(alias + '/'):
                return ''
    return CANONICAL_BASE


def is_root_alias_path(path):
    """该路径是否属于本模块的根级别入口。

    覆盖两类：
      1) 旧只读批次的别名：/login、/logout、/lab、/lab/items/...；
      2) P3 业务页面：/scan、/account 与全部 /lab/<page>（精确匹配）及其子路径。

    刻意**不**匹配 /lab/api、/lab/scan、/lab/labels/plan、/lab/labels/download、
    /lab/client/updates/*：这些是其它控制器（lab_workflow / lab_catalog）的路由，
    它们不受 root_aliases 开关影响，也不能被本模块的 404 逻辑误伤。
    """
    if not isinstance(path, str):
        return False
    if path in ('/login', '/logout', '/lab'):
        return True
    if path.startswith('/lab/items/'):
        return True
    if path in WORKFLOW_ROOT_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in WORKFLOW_ROOT_PREFIXES)


def welcome_url(base):
    return (base + '/') if base else '/'


def login_url(base, next_path=None):
    url = base + '/login'
    if next_path:
        return url + '?' + urlencode({'next': next_path})
    return url


def logout_url(base):
    return base + '/logout'


def lab_url(base, query=None, category_id=None, cursor=None, stock_only=False):
    params = []
    if query:
        params.append(('q', query))
    if category_id:
        params.append(('category_id', str(category_id)))
    if cursor:
        params.append(('cursor', str(cursor)))
    if stock_only:
        params.append(('stock_only', '1'))
    url = base + '/lab'
    return url + ('?' + urlencode(params) if params else '')


def item_url(base, item_key):
    return base + '/lab/items/' + quote_item_key(item_key)


# ---------------------------------------------------------------------------
# itemKey（与 lab_catalog_identity 对齐）
# ---------------------------------------------------------------------------
def quote_item_key(item_key):
    """itemKey 的路径编码：只保留 ASCII 安全字符，其余按 UTF-8 百分号编码。

    修正两个真实缺陷：
      * 旧实现用 str.isalnum() 判安全，中文（如 lab:测试）会被原样放进 URL；
      * 非 BMP 字符（emoji）用 %%02X 会产生 %1F600 这类非法百分号序列。
    现在只认 [A-Za-z0-9:._-]，其余一律由 quote(..., safe='') 按 UTF-8 编码，
    与 controllers 传给 route 的 item_key 解码结果一致。
    """
    raw = str(item_key or '')
    out = []
    for ch in raw:
        if ch.isascii() and (ch.isalnum() or ch in ':-._'):
            out.append(ch)
        else:
            out.append(quote(ch, safe=''))
    return ''.join(out)


def normalize_catalog_code(value):
    """与 lab_catalog_identity.normalize_catalog_code 相同的规范化与有效性规则。"""
    if value is None:
        return None
    if isinstance(value, bytes):
        try:
            value = value.decode('utf-8', 'ignore')
        except Exception:
            return None
    text = unicodedata.normalize('NFKC', str(value))
    text = text.strip().strip('\ufeff').replace('\u200b', '')
    text = ''.join(text.split()).upper()
    if not text:
        return None
    match = _CATALOG_RE.match(text)
    if not match:
        return None
    if int(match.group(1)) <= 0:        # C0 / C000 不是真实编号
        return None
    return 'C' + match.group(1)


def parse_item_key(item_key):
    """返回 (kind, value)：lcsc/lab 或 (None, None)。

    与 lab_catalog_identity.parse_item_key 语义一致：lab: 只认十进制数字，
    lab:0 在语法上可解析（返回 0），是否真实存在由详情查询决定（→ 404）。
    """
    if not item_key or not isinstance(item_key, str):
        return None, None
    if item_key.startswith('lcsc:'):
        code = normalize_catalog_code(item_key[5:])
        return ('lcsc', code) if code else (None, None)
    if item_key.startswith('lab:'):
        raw = item_key[4:].strip()
        return ('lab', int(raw)) if raw.isdigit() else (None, None)
    return None, None


def is_valid_item_key(item_key):
    kind, _value = parse_item_key(item_key)
    return kind is not None


# ---------------------------------------------------------------------------
# 展示
# ---------------------------------------------------------------------------
def clamp_limit(raw, default=DEFAULT_LIMIT, maximum=MAX_LIMIT):
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    if value < 1:
        return default
    return min(value, maximum)


def parse_flag(raw):
    """把 query/表单里的 1/true/on/yes 视为真。"""
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return False
    return str(raw).strip().lower() in ('1', 'true', 'on', 'yes', 'y')


def format_price(price, currency=None, empty='价格待询'):
    """价格展示：与 static/src/js/team.js 的 formatPrice 规则一致。

    缺失/非数字 -> 占位；整数不带小数；其余两位小数；
    CNY/RMB 用人民币符号，USD 用美元符号，EUR 用欧元符号，其它币种用 "CODE " 前缀。
    """
    if price is None or price == '':
        return empty
    try:
        number = float(price)
    except (TypeError, ValueError):
        return empty
    if number != number or number in (float('inf'), float('-inf')):
        return empty
    code = (currency or 'CNY').strip().upper() or 'CNY'
    symbols = {'CNY': '\u00a5', 'RMB': '\u00a5', 'USD': '\u0024', 'EUR': '\u20ac'}
    text = str(int(number)) if number == int(number) else '%.2f' % number
    return symbols.get(code, code + ' ') + text

def format_quantity(value, empty='—'):
    """库存数量展示：None/空串显示占位符，整数不带小数点。"""
    if value is None or value == '':
        return empty
    try:
        number = float(value)
    except (TypeError, ValueError):
        return empty
    if number == int(number):
        return str(int(number))
    return ('%.3f' % number).rstrip('0').rstrip('.')


#: 后端错误码 -> 面向使用者的中文说明（页面/JS 共用同一份映射）
ERROR_MESSAGES = {
    'FORBIDDEN': '当前账号没有实验室库存权限，请联系管理员开通。',
    'UNAUTHORIZED': '登录状态已失效，请重新登录。',
    'NOT_FOUND': '找不到该器件。',
    'VALIDATION_ERROR': '请求参数不合法。',
    'AMBIGUOUS_MATERIAL': '同一立创编号存在多个本地档案，需要指定具体档案。',
    'INTERNAL_ERROR': '服务暂时不可用，请稍后重试。',
}


def error_message(code, fallback=None):
    if code and code in ERROR_MESSAGES:
        return ERROR_MESSAGES[code]
    return fallback or ERROR_MESSAGES['INTERNAL_ERROR']


# ---------------------------------------------------------------------------
# 管理 Host 根入口决策（纯函数，可单测；实际接线在 models/ir_http.py）
# ---------------------------------------------------------------------------
def normalize_host(host_header):
    """把配置值/Host 头收敛成主机名。

    兼容三种写法：纯主机名、host:port、以及误填的完整 URL
    （https://team.example.com/ -> team.example.com）；IPv6 去方括号，末尾点去掉。
    """
    if not host_header or not isinstance(host_header, str):
        return ''
    value = host_header.strip()
    if '://' in value:                              # 误填的完整 URL
        value = value.split('://', 1)[1]
    value = value.split('/', 1)[0]                  # 去掉路径
    if value.startswith('['):                       # [::1]:8069
        end = value.find(']')
        if end > 0:
            value = value[1:end]
        else:
            return ''
    elif value.count(':') == 1:                     # host:port
        value = value.split(':', 1)[0]
    return value.strip().rstrip('.').lower()


def parse_host_list(value):
    """配置值 -> 主机名集合。支持逗号/空白分隔的多主机。"""
    if not value:
        return frozenset()
    raw = str(value).replace(',', ' ').split()
    return frozenset(h for h in (normalize_host(x) for x in raw) if h)


def host_is_management(host_header, configured_hosts):
    """当前请求是否落在管理站点 Host 上。未配置任何 Host 时恒为 False。"""
    hosts = configured_hosts if isinstance(configured_hosts, (set, frozenset)) \
        else parse_host_list(configured_hosts)
    if not hosts:
        return False
    return normalize_host(host_header) in hosts


def safe_doc_url(url):
    """资料/手册链接白名单：只放行站内相对路径或 http(s) 绝对地址。

    明确拒绝：javascript:/data:/vbscript: 等伪协议、协议相对 //host、
    反斜杠、控制字符、空值。返回可安全放进 href 的字符串或 None。
    """
    if not isinstance(url, str):
        return None
    value = url.strip()
    if not value:
        return None
    if _has_control_chars(value) or '\\' in value:
        return None
    if any(ch.isspace() for ch in value):      # 主机名/URL 里不允许空白
        return None
    if value.startswith('//'):
        return None
    if value.startswith('/'):
        return value
    try:
        parts = urlsplit(value)
    except ValueError:
        # 畸形 URL（例如 'https://['）会让 urlsplit 抛 ValueError；
        # 若放任上抛，详情页在资料渲染时会白屏，这里一律视为不可用。
        return None
    if parts.scheme.lower() in ('http', 'https') and parts.netloc:
        return value
    return None


def is_management_root_path(path):
    """只接管根路径；/web、/odoo、/lab/api、/lab/scan 等永不接管。"""
    if not isinstance(path, str):
        return False
    return path.rstrip('/') == '' or path == '/'


def decide_root(path, host_header, configured_hosts, enabled=True):
    """根入口决策：返回 serve（本模块渲染）或 fallthrough（交回原逻辑）。

    三重条件同时满足才接管，任何一条不满足都原样回退：
      1) 功能开启且配置了管理 Host；
      2) 请求 Host 命中配置（其他 Host 继续走旧官网）；
      3) 路径是根路径。
    """
    if not enabled:
        return 'fallthrough'
    hosts = parse_host_list(configured_hosts) if not isinstance(
        configured_hosts, (set, frozenset)) else configured_hosts
    if not hosts:
        return 'fallthrough'
    if not host_is_management(host_header, hosts):
        return 'fallthrough'
    if not is_management_root_path(path):
        return 'fallthrough'
    return 'serve'
