#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P2 浏览器验收：真实 UI 登录 / 检索 / 动态详情 / 刷新 / 退出 + 独立 HTTP 旧会话失效。

设计原则
--------
1. 业务动作一律走真实 UI：输入用真实鼠标聚焦 + Input.insertText，提交用真实点击；
   测试脚本不再自己 fetch 业务接口去"证明"功能可用。
2. 检索值必须来自浏览器自己的请求：从 CDP Network.requestWillBeSent 的 body 解码
   JSON-RPC params.query，并核对请求 URL/方法，证明「UI 输入 -> 真实 RPC -> DOM 结果」一致。
3. 详情链接动态取自命中卡片，不硬编码 lab:4。
4. 导航等待以 loaderId / frameNavigated / 新 document 的 execution context 为准，
   绝不在旧 document 上读 readyState。
5. 错误零容忍：JS 异常、console.error（含无可序列化参数）、Log error（含 security /
   network）、资源/网络失败、CSP 违规全部失败；只有两类精确例外：
     * /favicon.ico + ERR_ABORTED/404 + 资源类型受限（附说明）；
     * 本脚本主动导航前逐 requestId 登记的预期中止（附原因）。
6. 证据脱敏：不写密码、Cookie、CSRF token、登录 POST body、响应正文；网络只留方法、
   path、白名单 query 字段、status、真实检索值、request/loader 标识与 CSP 来源元数据。
7. profile 边界：只在本脚本 OUT_DIR 下创建，拒绝 symlink/junction 祖先与越界，
   清理前校验独立 marker 与 realpath，等自有 Chrome 进程退出后才删除。
8. 旧会话失效用 Python 独立 HTTP 客户端验证（自己实现最小 HTTP/1.1 + 显式 TLS：
   给了测试 CA 就走 CA 链，否则用入口证书 leaf 的 SPKI pin；绝不全局关闭 TLS 校验）。

环境变量
--------
必填：CHROME_BIN  URL  LOGIN  PASSWORD  OUT_DIR
可选：SPKI（入口证书 leaf SPKI 的 base64(SHA256)；Chrome pin 与 Python pin 共用）
      P2_CA_FILE / CA_FILE（测试 CA；优先于 SPKI pin。**现有 runner 传的是 CA_FILE**）
      P2_HTTP_ADDR（独立 HTTP 客户端连接地址，默认 127.0.0.1；证书仍按 URL 主机名校验）
      P2_SEARCH_QUERY / P2_QUERY（默认 TEST-R-10K；runner 传 P2_QUERY）
      P2_DETAIL_KEY（现有 runner 仍会传，本脚本**刻意忽略**：详情链接必须取自检索命中，
       不接受外部指定的 key，否则等于回到硬编码）
      P2_EXPECT_TERMS / P2_EXCLUDE_TERMS（逗号分隔，默认见下）
      P2_DETAIL_TERM（详情页必须出现的关键词，默认取检索词）
stdout 只输出一个 JSON 对象，诊断一律走 stderr。
退出码：0 全部 pass；1 存在 fail/blocked；2 环境或运行时不可用。
"""
import base64
import hashlib
import hmac
import json
import os
import re
import shutil
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
import time
import traceback
from urllib.parse import parse_qsl, urlsplit

# ---------------------------------------------------------------------------
# 常量（纯逻辑测试直接引用）
# ---------------------------------------------------------------------------
SEARCH_PATH = '/lab/api/catalog/search'
LOGIN_PATH = '/login'
LOGOUT_PATH = '/logout'
LAB_PATH = '/lab'
DETAIL_PREFIX = '/lab/items/'
FAVICON_PATH = '/favicon.ico'

WHITELIST_METHODS = ('GET', 'POST')

SAFE_QUERY_FIELDS = frozenset({
    'q', 'category_id', 'stock_only', 'limit', 'cursor', 'next', 'id',
})

SENSITIVE_PATHS = frozenset({
    '/web/session/authenticate', '/login', '/logout',
    '/team/login', '/team/logout', '/web/session/destroy',
})

SESSION_EXPIRED_NAMES = frozenset({
    'odoo.http.SessionExpiredException',
    'SessionExpiredException',
})

DEFAULT_SEARCH_QUERY = 'TEST-R-10K'
DEFAULT_EXPECT_TERMS = ('\u7535\u963b', 'TEST-R-10K')
DEFAULT_EXCLUDE_TERMS = ('\u7535\u5bb9', '100nF')

PLANNED_STEPS = (
    'env',
    'chrome-launch',
    'cdp-connect',
    'login-page',
    'login-ui-submit',
    'lab-authenticated',
    'search-ui-input',
    'search-rpc-query',
    'search-dom-match',
    'detail-link',
    'detail-ui-click',
    'detail-content',
    'detail-not-error',
    'refresh-ui',
    'refresh-authenticated',
    'refresh-content',
    'logout-cookie-capture',
    'logout-ui-submit',
    'logout-redirect-303',
    'logout-login-page',
    'logout-session-anon',
    'anon-lab-303',
    'anon-login-page-visible',
    'anon-old-cookie-invalid',
    'console-clean',
    'network-clean',
    'evidence-redaction',
    'profile-cleanup',
)


class FlowAbort(Exception):
    """硬前置失败：未执行的步骤记 blocked，而不是假装通过。"""


class CDPError(Exception):
    """CDP 协议层错误（call 返回 error 或超时）。"""


class EvaluationError(CDPError):
    """Runtime.evaluate 出现 exceptionDetails：必须失败，绝不吞异常。"""


# ---------------------------------------------------------------------------
# 纯逻辑：文本与脱敏
# ---------------------------------------------------------------------------
_SECRET_PATTERNS = (
    (re.compile(r'session_id\s*=\s*[^;\s"\']+'), 'session_id=<redacted>'),
    (re.compile(r'csrf_token\s*=\s*[^\s"\'&;,]+'), 'csrf_token=<redacted>'),
    (re.compile(r'"(?:password|passwd|pwd)"\s*:\s*"[^"]*"'), '"password":"<redacted>"'),
    (re.compile(r'(?:Bearer|Basic)\s+[A-Za-z0-9._\-+/=]{6,}'), 'AUTH <redacted>'),
)


def truncate(text, limit=240):
    value = '' if text is None else str(text)
    value = ' '.join(value.split())
    return value if len(value) <= limit else value[:max(0, limit - 1)] + '\u2026'


def redact(text, secrets=()):
    """去掉可能混进诊断文本的凭据；调用方仍不应主动放入凭据。"""
    value = '' if text is None else str(text)
    for _label, secret in secrets or ():
        if secret and len(secret) >= 4 and secret in value:
            value = value.replace(secret, '<redacted>')
    for pattern, replacement in _SECRET_PATTERNS:
        value = pattern.sub(replacement, value)
    return value


def find_secret_leaks(serialized, secrets=()):
    """落盘前自检：返回泄露类别标签（不含任何值）。"""
    hits = []
    for label, value in secrets or ():
        if value and len(value) >= 4 and value in serialized:
            hits.append(label)
    for label, pattern in (
        ('session_id-value',
         re.compile(r'session_id\s*=\s*(?!<redacted>)[^;"\'\s]')),
        ('csrf_token-value',
         re.compile(r'csrf_token\s*=\s*(?!<redacted>)[^\s"\'&;,]')),
        ('password-field',
         re.compile(r'"(?:password|passwd|pwd)"\s*:\s*"(?!<redacted>)[^"]+"')),
    ):
        if pattern.search(serialized):
            hits.append(label)
    return hits


def digest_label(value, key):
    """不落盘的关联标签：用每次运行随机的 token 做 HMAC，事后不可反推。"""
    if not value or not key:
        return ''
    return hmac.new(key.encode('utf-8'), value.encode('utf-8'),
                    hashlib.sha256).hexdigest()[:12]


# ---------------------------------------------------------------------------
# 纯逻辑：profile 边界与所有权
# ---------------------------------------------------------------------------
FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def is_linklike(path):
    """symlink / junction / 其它 reparse point 一律视为不可信祖先。"""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    if getattr(st, 'st_reparse_tag', 0):
        return True
    if getattr(st, 'st_file_attributes', 0) & FILE_ATTRIBUTE_REPARSE_POINT:
        return True
    return False


def path_chain(path):
    """从根到 path 的完整绝对路径链。"""
    current = os.path.abspath(path)
    parts = []
    while True:
        parts.append(current)
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    parts.reverse()
    return parts


def contains_link_component(path, is_link=None):
    """path 自身或任一祖先是否 link/reparse（防止经 junction 跑出 OUT_DIR）。"""
    probe = is_link or is_linklike
    for item in path_chain(path):
        try:
            if probe(item):
                return True
        except OSError:
            return True
    return False


def is_within(real_parent, real_child):
    """real_child 是否严格位于 real_parent 之内（两者都必须已 realpath）。"""
    if not real_parent or not real_child:
        return False
    parent = os.path.normcase(os.path.abspath(real_parent)).rstrip(os.sep)
    child = os.path.normcase(os.path.abspath(real_child)).rstrip(os.sep)
    if not parent or parent == child:
        return False
    return child.startswith(parent + os.sep)


def safe_child_dir(parent, prefix='profile-', is_link=None, maker=None):
    """在 parent 内创建一个受控子目录，返回 (path, realpath)。

    拒绝：parent 缺失 / parent 链上有 link 或 reparse / 新建目录 realpath 越界 /
    新建目录本身是链接。
    """
    real_parent = os.path.realpath(parent)
    if not os.path.isdir(real_parent):
        raise ValueError('parent 不是目录')
    if contains_link_component(parent, is_link):
        raise ValueError('parent 路径链含 symlink/junction')
    make = maker or (lambda: tempfile.mkdtemp(prefix=prefix, dir=real_parent))
    created = make()
    real_created = os.path.realpath(created)
    if not is_within(real_parent, real_created):
        raise ValueError('新建目录 realpath 越界')
    if is_linklike(real_created):
        raise ValueError('新建目录本身是链接')
    return created, real_created


def write_owner_marker(profile_dir, token):
    path = os.path.join(profile_dir, '.lc_p2_owner')
    with open(path, 'w', encoding='utf-8') as handle:
        handle.write(token)
    return path


def verify_owner_marker(profile_dir, token, is_link=None):
    """清理前校验：marker 是普通文件、内容等于本次 token、realpath 就在 profile 内。"""
    probe = is_link or is_linklike
    path = os.path.join(profile_dir, '.lc_p2_owner')
    if probe(path):
        return False, 'marker 是链接或 reparse point'
    try:
        real = os.path.realpath(path)
        if os.path.normcase(os.path.dirname(real)) != os.path.normcase(
                os.path.realpath(profile_dir)):
            return False, 'marker realpath 越界'
        with open(real, 'r', encoding='utf-8') as handle:
            value = handle.read().strip()
    except OSError:
        return False, 'marker 不可读'
    if not value or not hmac.compare_digest(value, token):
        return False, 'marker 内容不匹配'
    return True, ''


# ---------------------------------------------------------------------------
# 纯逻辑：URL / JSON-RPC / CSP
# ---------------------------------------------------------------------------
def url_path(url):
    try:
        return urlsplit(url or '').path or '/'
    except ValueError:
        return ''


def url_origin(url):
    try:
        parts = urlsplit(url or '')
    except ValueError:
        return ''
    if not parts.scheme or not parts.hostname:
        return ''
    netloc = parts.hostname if parts.port in (None, 80, 443) else '%s:%d' % (
        parts.hostname, parts.port)
    return '%s://%s' % (parts.scheme.lower(), netloc)


def filter_query_params(query_string):
    """只保留白名单 query 字段的值；其它字段仅计数（不落值）。"""
    out = {}
    hidden = 0
    for key, value in parse_qsl(query_string or '', keep_blank_values=True):
        if key in SAFE_QUERY_FIELDS:
            out[key] = truncate(value, 80)
        else:
            hidden += 1
    if hidden:
        out['_hidden_fields'] = hidden
    return out


def decode_search_body(post_data):
    """从真实请求 body 解出 JSON-RPC params.query；无法解码返回 None。"""
    if not post_data or not isinstance(post_data, str):
        return None
    try:
        payload = json.loads(post_data)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    params = payload.get('params')
    if not isinstance(params, dict):
        return None
    query = params.get('query')
    if not isinstance(query, str):
        return None
    category = params.get('category_id')
    limit = params.get('limit')
    return {
        'query': truncate(query, 120),
        'jsonrpc': payload.get('jsonrpc'),
        'method': payload.get('method'),
        'category_id': category if isinstance(category, int) else None,
        'stock_only': bool(params.get('stock_only')),
        'limit': limit if isinstance(limit, int) else None,
        'cursor_present': bool(params.get('cursor')),
    }


#: 与 lab_team_web.tools.paths.is_valid_item_key 完全一致的 itemKey 形态校验。
#: 用它挑"应用真的能路由到"的详情链接；不合规的命中项会被单独记录，
#: 而不是悄悄丢弃——那是需要修模块/种子的真实缺陷。
LAB_KEY_RE = re.compile(r'^lab:[0-9]+$')
LCSC_KEY_RE = re.compile(r'^lcsc:C[0-9]+$')


def is_routable_detail_key(item_key):
    """该 itemKey 是否能被应用的 /lab/items/<key> 路由真正受理。"""
    value = (item_key or '').strip()
    if LCSC_KEY_RE.match(value):
        return int(value[5:][1:]) > 0
    if LAB_KEY_RE.match(value):
        return True
    return False


def detail_path_for(item_key):
    """itemKey -> 详情页相对路径（与后端 quote_item_key 规则一致）。

    安全字符集是 [A-Za-z0-9:._-]；其余字符必须按 **UTF-8 字节**做百分号编码，
    而不是按 Unicode 码点（否则中文/emoji 会生成非法或不一致的百分号序列）。
    """
    raw = str(item_key or '')
    out = []
    for ch in raw:
        if ch.isascii() and (ch.isalnum() or ch in ':-._'):
            out.append(ch)
        else:
            out.append(''.join('%%%02X' % byte
                               for byte in ch.encode('utf-8')))
    return DETAIL_PREFIX + ''.join(out)


def parse_csp_header(value):
    """Content-Security-Policy -> {directive: [sources]}（只留来源元数据）。"""
    directives = {}
    for chunk in str(value or '').split(';'):
        tokens = chunk.strip().split()
        if not tokens:
            continue
        name = tokens[0].lower()
        if not re.match(r'^[a-z][a-z0-9-]*$', name):
            continue
        directives[name] = [truncate(tok, 60) for tok in tokens[1:]]
    return directives


def extract_session_uid(text):
    """从 get_session_info 响应里取出 result.uid（取不到返回 ("missing", None)）。"""
    try:
        payload = json.loads(text if isinstance(text, str) else '')
    except (ValueError, TypeError):
        return ('unparsable', None)
    if not isinstance(payload, dict):
        return ('unparsable', None)
    result = payload.get('result')
    if isinstance(result, dict) and 'uid' in result:
        return ('present', result.get('uid'))
    return ('missing', None)


def classify_session_payload(text=None, transport_error=None, content_type=''):
    """判定会话是否真的匿名。

    只接受两种证据：
      * 结构化 result 里显式 uid 为 false/null；
      * 精确的 SessionExpiredException 错误名。
    未知 error / HTML / 网络失败 / 别的 JSON 形状 / 有 uid，一律 unknown，
    不能算匿名（宁可 fail，也不把"未确认"当成"已登出"）。
    """
    if transport_error:
        return ('neterr', 'transport: ' + truncate(transport_error, 100))
    if text is None:
        return ('neterr', 'no response body')
    body = str(text)
    if content_type and 'json' not in str(content_type).lower():
        return ('html', 'content-type=' + truncate(content_type, 60))
    try:
        payload = json.loads(body)
    except (ValueError, TypeError):
        return ('html', 'non-json body len=%d' % len(body))
    if not isinstance(payload, dict):
        return ('unknown', 'unexpected json shape')
    error = payload.get('error')
    if isinstance(error, dict):
        data = error.get('data')
        name = ''
        if isinstance(data, dict):
            name = str(data.get('name') or '').strip()
        if not name:
            name = str(error.get('name') or '').strip()
        if name in SESSION_EXPIRED_NAMES:
            return ('expired', 'error name=' + name)
        return ('unknown', 'error name=' + (truncate(name, 60) or '<none>'))
    if 'result' in payload:
        result = payload.get('result')
        if isinstance(result, dict) and 'uid' in result:
            uid = result.get('uid')
            if not uid:
                return ('anon', 'result.uid=%s' % ('null' if uid is None else 'false'))
            return ('uid', 'result.uid present (still an authenticated identity)')
        return ('unknown', 'result without uid key')
    return ('unknown', 'no result and no error')


def classify_network_failure(path, error_text, resource_type, request_id,
                             blocked_reason='', allowed_aborts=None):
    """网络失败归类：只有两类可以不是 fail，且都精确限定。"""
    allowed = allowed_aborts or {}
    if blocked_reason:
        return ('fail', 'blocked-by:' + truncate(blocked_reason, 40))
    if (path == FAVICON_PATH and error_text == 'net::ERR_ABORTED'
            and resource_type in ('Other', 'Image')):
        return ('ignored',
                'favicon: headless Chrome 自动请求 /favicon.ico，页面未声明 icon；'
                '仅此精确 URL + ERR_ABORTED + Other/Image 可排除')
    if error_text == 'net::ERR_ABORTED' and request_id in allowed:
        return ('allowed-abort', 'expected abort: ' + truncate(allowed[request_id], 90))
    return ('fail', '')


def classify_status(path, status, resource_type):
    """非 2xx/3xx 状态归类；favicon 404 是唯一精确例外。"""
    if status is None:
        return ('unknown', '')
    try:
        code = int(status)
    except (TypeError, ValueError):
        return ('unknown', '')
    if 200 <= code < 400:
        return ('ok', '')
    if code == 404 and path == FAVICON_PATH and resource_type in ('Other', 'Image'):
        return ('ignored',
                'favicon: 页面未声明 icon，Chrome 自动请求 /favicon.ico 得 404；'
                '仅此精确 URL + 404 可排除')
    return ('fail', '')


# ---------------------------------------------------------------------------
# 纯逻辑：DER 里取 SPKI（供 Python 侧证书 pin，不做全局 TLS 关闭）
# ---------------------------------------------------------------------------
def der_tlv(data, offset):
    """返回 (tag, value_start, value_end)。"""
    if offset + 2 > len(data):
        raise ValueError('DER truncated header')
    tag = data[offset]
    first = data[offset + 1]
    cursor = offset + 2
    if first & 0x80:
        count = first & 0x7F
        if count == 0 or count > 4 or cursor + count > len(data):
            raise ValueError('DER bad length encoding')
        length = int.from_bytes(data[cursor:cursor + count], 'big')
        cursor += count
    else:
        length = first
    end = cursor + length
    if end > len(data):
        raise ValueError('DER truncated value')
    return tag, cursor, end


def extract_spki_der(cert_der):
    """从 X.509 DER 里取出 SubjectPublicKeyInfo 的完整 TLV 字节。"""
    if not isinstance(cert_der, (bytes, bytearray)) or not cert_der:
        raise ValueError('empty certificate')
    tag, start, end = der_tlv(cert_der, 0)
    if tag != 0x30:
        raise ValueError('certificate is not a SEQUENCE')
    tbs_tag, tbs_start, tbs_end = der_tlv(cert_der, start)
    if tbs_tag != 0x30:
        raise ValueError('tbsCertificate is not a SEQUENCE')
    cursor = tbs_start
    tag, _s, _e = der_tlv(cert_der, cursor)
    cursor = _e
    if tag == 0xA0:                                  # [0] version
        _t, _s, cursor = der_tlv(cert_der, cursor)
    for _ in range(4):                               # signature, issuer, validity, subject
        _t, _s, cursor = der_tlv(cert_der, cursor)
    spki_start = cursor
    spki_tag, _s, spki_end = der_tlv(cert_der, cursor)
    if spki_tag != 0x30:
        raise ValueError('subjectPublicKeyInfo is not a SEQUENCE')
    if spki_end > tbs_end:
        raise ValueError('spki escapes tbsCertificate')
    return bytes(cert_der[spki_start:spki_end])


def spki_sha256_b64(cert_der):
    return base64.b64encode(hashlib.sha256(extract_spki_der(cert_der)).digest()).decode('ascii')

# ---------------------------------------------------------------------------
# 网络记录器（纯逻辑：CDP 事件 -> 可审计、已脱敏的证据）
# ---------------------------------------------------------------------------
class NetworkRecorder(object):
    """把 CDP 网络事件收敛成脱敏证据，并正确处理 redirect 的 requestId 归属。

    关键点（对应本轮验收要求）：
    * ExtraInfo 用 requestId + "该 id 的第几个 hop" 归属，跨 redirect 不会错记；
      并且它只作来源元数据，绝不拿来当 303 判据。
    * 303 判据来自 requestWillBeSent 里的 redirectResponse（同一 requestId 的上一条
      hop 才是被重定向的请求），并显式区分 from_method / from_path。
    * 敏感路径的 POST body（登录/退出/CSRF）永不落盘，只记 hasPostData。
    * 只有 /lab/api/catalog/search 会解码 body 里的 params.query。
    """

    def __init__(self, max_evidence=240, secrets=(), entry_origin=''):
        self.max_evidence = max_evidence
        self.secrets = list(secrets)
        #: 入口 origin：证据里只落"是否同源"布尔值，不落原始 origin 字符串
        self.entry_origin = (entry_origin or '').rstrip('/')
        self.seq = 0
        self.requests = []
        self.responses = []
        self.redirects = []
        self.failures = []
        self.ignored = []
        self.extra_info = []
        self.evidence = []
        self.csp = []
        self.inflight = {}
        self.allowed_aborts = {}
        self.dropped = 0
        self._extra_seen = {}

    # -- 内部 -------------------------------------------------------------
    def _tick(self):
        self.seq += 1
        return self.seq

    def _hops(self, request_id):
        return [hop for hop in self.requests if hop['request_id'] == request_id]

    def _match_hop(self, request_id, url):
        hops = self._hops(request_id)
        for hop in reversed(hops):
            if hop['url'] == url and hop['status'] is None:
                return hop
        for hop in reversed(hops):
            if hop['url'] == url:
                return hop
        return None

    def in_flight(self):
        """真正还在飞的请求：既没拿到响应，也没失败（不含已完成的旧 hop）。"""
        out = []
        for hop in self.requests:
            if hop.get('settled'):
                continue
            out.append(hop)
        return out

    def allow_aborts(self, reason, path=None):
        """把**当前仍在飞**的请求逐 requestId 登记为"本次 UI 动作的预期中止"。

        两个收窄条件缺一不可：
          * 只登记 settled 尚未置位的请求（否则历史上所有 id 都会被放行）；
          * 可选按 path 再收窄（例如只允许被后续显式提交 abort 的那个检索请求）。
        """
        for hop in self.in_flight():
            if path is not None and hop.get('path') != path:
                continue
            request_id = hop['request_id']
            if request_id not in self.allowed_aborts:
                self.allowed_aborts[request_id] = '%s (%s %s)' % (
                    truncate(reason, 60), hop.get('method', ''), hop.get('path', ''))

    # -- 事件 -------------------------------------------------------------
    def record_request(self, params):
        request_id = params.get('requestId') or ''
        request = params.get('request') or {}
        redirect = params.get('redirectResponse') or {}
        url = request.get('url') or ''
        path = url_path(url)
        try:
            query_string = urlsplit(url).query
        except ValueError:
            query_string = ''
        hop = {
            'request_id': request_id,
            'seq': self._tick(),
            'method': str(request.get('method') or '').upper(),
            'url': url,
            'path': path,
            'origin': url_origin(url),
            'query_fields': filter_query_params(query_string),
            'resource_type': str(params.get('type') or ''),
            'loader_id': params.get('loaderId') or '',
            'frame_id': params.get('frameId') or '',
            'status': None,
            'redirect_status': None,
            'rpc': None,
            'has_post_data': bool(request.get('postData') or params.get('hasPostData')),
            'post_data_retained': False,
            'settled': False,
        }
        previous = self._hops(request_id)
        if redirect:
            prev = previous[-1] if previous else None
            status = redirect.get('status')
            if prev is not None:
                prev['redirect_status'] = status
                prev['settled'] = True
            from_url = redirect.get('url') or (prev['url'] if prev else '')
            self.redirects.append({
                'request_id': request_id,
                'from_url': from_url,
                'from_path': url_path(from_url),
                'from_method': prev['method'] if prev else None,
                'status': status,
                'to_path': path,
                'from_hop_index': len(previous) - 1,
                'to_method': hop['method'],
                'to_hop_index': len(previous),
                'seq': hop['seq'],
            })
        self.requests.append(hop)
        self.inflight[request_id] = hop
        if path == SEARCH_PATH and not redirect:
            body = request.get('postData')
            if body is not None:
                self.attach_post_data(request_id, body)
            elif not hop['has_post_data']:
                # 检索端点必须带 JSON-RPC body；没有 body 是调用方式错误，
                # 显式记错，避免"没有 query"被当成"无需校验"。
                hop['rpc'] = {'error': 'search request without post data'}
        self._push_evidence(hop)
        return hop

    def attach_post_data(self, request_id, post_data, error=None):
        """只对检索端点解码 body；其它端点一律不保留。"""
        hops = self._hops(request_id)
        if not hops:
            return None
        hop = hops[-1]
        if hop['path'] != SEARCH_PATH:
            return None
        if hop['rpc'] is not None:
            return hop['rpc']
        if post_data is None:
            hop['rpc'] = {'error': truncate(error or 'post data unavailable', 90)}
            return hop['rpc']
        decoded = decode_search_body(post_data)
        hop['rpc'] = decoded if decoded else {'error': 'undecodable json-rpc body'}
        # 证据条目在请求到达时就已写盘；这里把真实 query 回填进去，
        # 保证"证据里的 search query"就是浏览器实际发出去的那个值。
        if hop['rpc'].get('query'):
            for entry in self.evidence:
                if (entry['request_id'] == hop['request_id']
                        and entry['path'] == SEARCH_PATH
                        and 'rpc_query' not in entry):
                    entry['rpc_query'] = hop['rpc']['query']
        return hop['rpc']

    def pending_search_bodies(self):
        """检索请求里 body 还没解出来的 hop（需要 Network.getRequestPostData 补取）。"""
        out = []
        for hop in self.requests:
            if hop['path'] == SEARCH_PATH and hop['rpc'] is None:
                out.append(hop)
        return out

    def record_extra_info(self, params):
        """ExtraInfo 按 requestId + hop 序号归属；仅作来源元数据，不作断言依据。"""
        request_id = params.get('requestId') or ''
        index = self._extra_seen.get(request_id, 0)
        self._extra_seen[request_id] = index + 1
        hops = self._hops(request_id)
        matched = hops[index] if index < len(hops) else None
        self.extra_info.append({
            'request_id': request_id,
            'hop_index': index,
            'attributed_path': matched['path'] if matched else '',
            'status': params.get('statusCode'),
            'attribution': 'requestId+hop-index' if matched else 'unmatched',
        })

    def record_response(self, params):
        request_id = params.get('requestId') or ''
        response = params.get('response') or {}
        url = response.get('url') or ''
        hop = self._match_hop(request_id, url)
        if hop is not None:
            hop['status'] = response.get('status')
            hop['mime'] = truncate(response.get('mimeType') or '', 60)
            hop['settled'] = True
        headers = response.get('headers') or {}
        csp_value = None
        for key, value in headers.items():
            if str(key).lower() == 'content-security-policy':
                csp_value = value
                break
        if csp_value and str(params.get('type') or '') == 'Document':
            self.csp.append({
                'path': url_path(url),
                'directives': parse_csp_header(csp_value),
                'source': 'response-header',
            })
        self.responses.append({
            'request_id': request_id,
            'path': url_path(url),
            'status': response.get('status'),
            'type': str(params.get('type') or ''),
        })

    def record_failure(self, params):
        request_id = params.get('requestId') or ''
        hop = self.inflight.get(request_id)
        path = hop['path'] if hop else ''
        resource_type = hop['resource_type'] if hop else str(params.get('type') or '')
        error_text = str(params.get('errorText') or '')
        blocked = str(params.get('blockedReason') or '')
        kind, reason = classify_network_failure(
            path, error_text, resource_type, request_id, blocked, self.allowed_aborts)
        if hop is not None:
            hop['settled'] = True
        entry = {
            'request_id': request_id,
            'method': hop['method'] if hop else '',
            'path': path,
            'type': resource_type,
            'error': redact(error_text, self.secrets),
            'blocked_reason': redact(blocked, self.secrets),
            'decision': kind,
            'reason': redact(reason, self.secrets),
        }
        self.failures.append(entry)
        if kind != 'fail':
            self.ignored.append(entry)

    # -- 证据 -------------------------------------------------------------
    def _push_evidence(self, hop):
        path = hop['path']
        entry = {
            'seq': hop['seq'],
            'method': hop['method'] if hop['method'] in WHITELIST_METHODS else 'OTHER',
            'path': path,
            'query': hop['query_fields'],
            'request_id': hop['request_id'],
            'resource_type': hop['resource_type'],
            'loader_id': hop['loader_id'],
            'has_post_data': hop['has_post_data'],
        }
        if hop['origin']:
            entry['same_origin_as_entry'] = bool(
                self.entry_origin and hop['origin'] == self.entry_origin)
        if hop['redirect_status'] is not None:
            entry['redirect_status'] = hop['redirect_status']
        if path == SEARCH_PATH and hop['rpc'] and hop['rpc'].get('query'):
            entry['rpc_query'] = hop['rpc']['query']
        if path in SENSITIVE_PATHS:
            entry['body'] = 'withheld'
        if len(self.evidence) < self.max_evidence:
            self.evidence.append(entry)
        else:
            self.dropped += 1
        return entry

    def finish(self):
        """回填 responseReceived 的 status 到证据条目（按 requestId + path 匹配）。"""
        by_request = {}
        for entry in self.evidence:
            by_request.setdefault(entry['request_id'], []).append(entry)
        for hop in self.requests:
            if hop['status'] is None:
                continue
            for entry in by_request.get(hop['request_id'], []):
                if entry['path'] != hop['path'] or 'status' in entry:
                    continue
                entry['status'] = hop['status']
                verdict, _note = classify_status(hop['path'], hop['status'],
                                                 hop['resource_type'])
                if verdict == 'ignored':
                    entry['status_exempt'] = 'favicon-404'
        return self

    # -- 断言用查询 -------------------------------------------------------
    def search_hops(self, since_seq=0):
        return [hop for hop in self.requests
                if hop['path'] == SEARCH_PATH and hop['seq'] >= since_seq]

    def search_queries(self, since_seq=0):
        out = []
        for hop in self.search_hops(since_seq):
            if hop['rpc'] and hop['rpc'].get('query'):
                out.append(hop['rpc']['query'])
        return out

    def logout_redirects(self, since_seq=0):
        return [item for item in self.redirects
                if item['seq'] >= since_seq and item['from_path'] == LOGOUT_PATH]

    def status_failures(self):
        out = []
        for hop in self.requests:
            if hop['status'] is None:
                continue
            verdict, _note = classify_status(hop['path'], hop['status'],
                                             hop['resource_type'])
            if verdict == 'fail':
                out.append({
                    'request_id': hop['request_id'],
                    'method': hop['method'],
                    'path': hop['path'],
                    'status': hop['status'],
                    'type': hop['resource_type'],
                })
        return out

    def failure_failures(self):
        return [item for item in self.failures if item['decision'] == 'fail']

    def first_csp(self):
        if self.csp:
            return self.csp[0]
        return {'path': '', 'directives': {}, 'source': 'absent'}

    def counts(self):
        return {
            'requests': len(self.requests),
            'responses': len(self.responses),
            'redirects': len(self.redirects),
            'navigations_failed': len(self.failures),
            'ignored': len(self.ignored),
            'status_failures': len(self.status_failures()),
            'csp_documents': len(self.csp),
            'evidence_truncated': self.dropped,
        }


# ---------------------------------------------------------------------------
# 独立 HTTP 客户端（最小 HTTP/1.1 + 显式 TLS；只信测试 CA 或精确 SPKI pin）
# ---------------------------------------------------------------------------
class HttpResult(object):
    def __init__(self, status, headers, body, url, method):
        self.status = status
        self.headers = headers
        self.body = body
        self.url = url
        self.method = method

    def header(self, name):
        return self.headers.get(name.lower(), '')

    def text(self):
        try:
            return self.body.decode('utf-8', 'replace')
        except Exception:
            return ''

    def json(self):
        try:
            return json.loads(self.text())
        except ValueError:
            return None


def _dechunk(raw):
    out = bytearray()
    index = 0
    while True:
        line_end = raw.find(b'\r\n', index)
        if line_end < 0:
            break
        try:
            size = int(raw[index:line_end].split(b';')[0].strip() or b'0', 16)
        except ValueError:
            return bytes(raw)
        if size == 0:
            break
        start = line_end + 2
        out += raw[start:start + size]
        index = start + size + 2
    return bytes(out)


def parse_http_response(raw, url, method):
    head, _, rest = raw.partition(b'\r\n\r\n')
    lines = head.decode('latin-1', 'replace').split('\r\n')
    status = 0
    if lines:
        bits = lines[0].split()
        if len(bits) >= 2 and bits[1].isdigit():
            status = int(bits[1])
    headers = {}
    for line in lines[1:]:
        if ':' not in line:
            continue
        key, value = line.split(':', 1)
        key = key.strip().lower()
        value = value.strip()
        if key in headers:
            headers[key] = headers[key] + ', ' + value
        else:
            headers[key] = value
    if 'chunked' in headers.get('transfer-encoding', '').lower():
        rest = _dechunk(rest)
    return HttpResult(status, headers, rest, url, method)


class IndependentHttp(object):
    """显式控制 TLS、Cookie 与"不跟随重定向"的最小 HTTP 客户端。"""

    def __init__(self, url, addr='127.0.0.1', ca_file=None, spki_pin=None, timeout=15):
        parts = urlsplit(url)
        self.scheme = (parts.scheme or 'https').lower()
        self.host = parts.hostname or ''
        self.port = parts.port or (443 if self.scheme == 'https' else 80)
        netloc = self.host if self.port in (80, 443) else '%s:%d' % (self.host, self.port)
        self.origin = '%s://%s' % (self.scheme, netloc)
        self.addr = addr or self.host
        self.ca_file = ca_file or None
        self.spki_pin = (spki_pin or '').strip()
        self.timeout = timeout
        self.mode = 'plain' if self.scheme != 'https' else 'system'
        self.pin_digest = ''

    def describe_tls(self):
        return {
            'mode': self.mode,
            'uses_ca_file': self.mode == 'ca',
            'uses_spki_pin': self.mode == 'spki-pin',
            'pinned_spki_sha256': self.pin_digest,
            'hostname_checked': self.mode in ('ca', 'system'),
            'connect_addr': self.addr,
            'port': self.port,
        }

    def _context(self):
        if self.scheme != 'https':
            return None, 'plain'
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        try:
            context.minimum_version = ssl.TLSVersion.TLSv1_2
        except (AttributeError, ValueError):
            pass
        if self.ca_file:
            context.load_verify_locations(cafile=self.ca_file)
            return context, 'ca'
        if self.spki_pin:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            return context, 'spki-pin'
        context.load_default_certs()
        return context, 'system'

    def _connect(self):
        context, mode = self._context()
        self.mode = mode
        sock = socket.create_connection((self.addr, self.port), timeout=self.timeout)
        if context is None:
            return sock
        tls = context.wrap_socket(sock, server_hostname=self.host)
        if mode == 'spki-pin':
            actual = spki_sha256_b64(tls.getpeercert(binary_form=True))
            self.pin_digest = actual
            if not hmac.compare_digest(actual, self.spki_pin):
                tls.close()
                raise ValueError('SPKI pin mismatch（证书不是本次测试入口）')
        return tls

    def request(self, method, path, headers=None, body=None, cookies=None):
        if not path.startswith('/'):
            path = '/' + path
        url = self.origin + path
        lines = [
            '%s %s HTTP/1.1' % (method, path),
            'Host: %s' % (self.host if self.port in (80, 443)
                          else '%s:%d' % (self.host, self.port)),
            'User-Agent: lc-elc-p2-verify/1',
            'Accept: */*',
            'Accept-Encoding: identity',
            'Connection: close',
        ]
        if cookies:
            lines.append('Cookie: ' + '; '.join(
                '%s=%s' % (item['name'], item['value']) for item in cookies))
        for key, value in (headers or {}).items():
            lines.append('%s: %s' % (key, value))
        payload = b''
        if body is not None:
            payload = body.encode('utf-8') if isinstance(body, str) else bytes(body)
            lines.append('Content-Length: %d' % len(payload))
        raw_request = ('\r\n'.join(lines) + '\r\n\r\n').encode('latin-1') + payload
        conn = self._connect()
        try:
            conn.sendall(raw_request)
            chunks = []
            while True:
                piece = conn.recv(65536)
                if not piece:
                    break
                chunks.append(piece)
        finally:
            try:
                conn.close()
            except OSError:
                pass
        return parse_http_response(b''.join(chunks), url, method)

# ---------------------------------------------------------------------------
# CDP 会话
# ---------------------------------------------------------------------------
class CDP(object):
    """最小 CDP 客户端（websockets 同步版）。

    事件分派、导航等待与求值都在这里；断言逻辑在 BrowserFlow。
    """

    def __init__(self, ws, recorder, sink):
        self.ws = ws
        self.recorder = recorder
        self.sink = sink
        self.next_id = 0
        self.frames = {}
        self.contexts = []
        self.nav_log = []
        self.lifecycle = []
        self.event_seq = 0
        self.closed = False

    # -- 传输 -------------------------------------------------------------
    def _send(self, method, params):
        self.next_id += 1
        self.ws.send(json.dumps({'id': self.next_id, 'method': method,
                                 'params': params or {}}))
        return self.next_id

    def pump(self, timeout=0.05):
        """只取一帧事件（无事件时静默返回 False）。"""
        try:
            raw = self.ws.recv(timeout=timeout)
        except TimeoutError:
            return False
        except Exception as exc:
            self.closed = True
            self.sink.add('transport-error', 'cdp', 'recv failed: ' + truncate(exc, 120))
            return False
        return self._handle_frame(raw)

    def _handle_frame(self, raw):
        try:
            message = json.loads(raw)
        except ValueError:
            self.sink.add('transport-error', 'cdp', 'non-json frame')
            return False
        if isinstance(message, dict) and 'method' in message:
            self._dispatch(message)
        return True

    def call(self, method, timeout=30, **params):
        call_id = self._send(method, params)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                raw = self.ws.recv(timeout=max(0.05, deadline - time.time()))
            except TimeoutError:
                continue
            except Exception as exc:
                self.closed = True
                raise CDPError('%s: recv failed: %s' % (method, truncate(exc, 100)))
            try:
                message = json.loads(raw)
            except ValueError:
                self.sink.add('transport-error', 'cdp', 'non-json frame')
                continue
            if message.get('id') == call_id:
                if 'error' in message:
                    raise CDPError('%s: %s' % (
                        method, truncate(json.dumps(message['error']), 200)))
                return message.get('result') or {}
            if 'method' in message:
                self._dispatch(message)
        raise CDPError('%s: timeout after %ss' % (method, timeout))

    # -- 事件 -------------------------------------------------------------
    def _dispatch(self, message):
        self.event_seq += 1
        method = message.get('method')
        params = message.get('params') or {}
        if method == 'Network.requestWillBeSent':
            self.recorder.record_request(params)
        elif method == 'Network.responseReceivedExtraInfo':
            self.recorder.record_extra_info(params)
        elif method == 'Network.responseReceived':
            self.recorder.record_response(params)
        elif method == 'Network.loadingFailed':
            self.recorder.record_failure(params)
        elif method == 'Runtime.exceptionThrown':
            self.sink.add_exception(params)
        elif method == 'Runtime.consoleAPICalled':
            self.sink.add_console(params)
        elif method == 'Log.entryAdded':
            self.sink.add_log(params)
        elif method == 'Runtime.executionContextCreated':
            ctx = params.get('context') or {}
            aux = ctx.get('auxData') or {}
            self.contexts.append({
                'seq': self.event_seq,
                'id': ctx.get('id'),
                'frame_id': aux.get('frameId') or '',
                'is_default': bool(aux.get('isDefault')),
                'origin': truncate(ctx.get('origin') or '', 80),
            })
        elif method == 'Runtime.executionContextDestroyed':
            gone = params.get('executionContextId')
            self.contexts = [item for item in self.contexts if item['id'] != gone]
        elif method == 'Runtime.executionContextsCleared':
            self.contexts = []
        elif method == 'Page.frameNavigated':
            frame = params.get('frame') or {}
            if frame.get('parentId'):
                return
            frame_id = frame.get('id') or ''
            self.frames[frame_id] = {
                'loader_id': frame.get('loaderId') or '',
                'url': frame.get('url') or '',
            }
            self.nav_log.append({
                'seq': self.event_seq,
                'frame_id': frame_id,
                'loader_id': frame.get('loaderId') or '',
                'url': frame.get('url') or '',
            })
        elif method == 'Page.lifecycleEvent':
            self.lifecycle.append({
                'seq': self.event_seq,
                'name': params.get('name') or '',
                'frame_id': params.get('frameId') or '',
                'loader_id': params.get('loaderId') or '',
            })

    # -- 求值 -------------------------------------------------------------
    def evaluate(self, expression, context_id=None, await_promise=False, timeout=25):
        params = {
            'expression': expression,
            'returnByValue': True,
            'awaitPromise': bool(await_promise),
            'userGesture': True,
        }
        if context_id is not None:
            params['contextId'] = context_id
        try:
            result = self.call('Runtime.evaluate', timeout=timeout, **params)
        except CDPError as exc:
            text = str(exc)
            if 'Cannot find context' in text or 'Execution context was destroyed' in text:
                raise EvaluationError('context gone: ' + truncate(text, 120))
            raise
        details = result.get('exceptionDetails')
        if details:
            exc_obj = details.get('exception') or {}
            summary = '%s %s %s' % (
                truncate(details.get('text') or '', 120),
                truncate(exc_obj.get('className') or '', 60),
                truncate(exc_obj.get('description') or '', 160))
            self.sink.add('evaluate-exception', 'javascript',
                          'exceptionDetails: ' + summary.strip())
            raise EvaluationError('exceptionDetails: ' + summary.strip())
        if 'exception' in result:                       # 极少数协议变体
            self.sink.add('evaluate-exception', 'javascript',
                          'evaluate returned exception object')
            raise EvaluationError('exceptionDetails: evaluate returned exception object')
        return (result.get('result') or {}).get('value')

    def try_evaluate(self, expression, context_id=None, await_promise=False,
                     transient_ok=True):
        """求值失败只在"context 已销毁"这类瞬时情况下返回 None。"""
        try:
            return self.evaluate(expression, context_id=context_id,
                                 await_promise=await_promise)
        except EvaluationError as exc:
            if transient_ok and 'context gone' in str(exc):
                return None
            raise

    # -- 真实 UI 动作 -----------------------------------------------------
    def describe_target(self, selector, index=0):
        expression = """(() => {
          const list = Array.from(document.querySelectorAll(%s));
          const el = list[%d];
          if (!el) return {found: false, count: list.length};
          el.scrollIntoView({block: 'center', inline: 'center'});
          const rect = el.getBoundingClientRect();
          const x = Math.round(rect.left + rect.width / 2);
          const y = Math.round(rect.top + rect.height / 2);
          const hit = document.elementFromPoint(x, y);
          return {
            found: true, count: list.length, x: x, y: y,
            w: Math.round(rect.width), h: Math.round(rect.height),
            hit_tag: hit ? String(hit.tagName || '') : '',
            hit_class: hit ? String(hit.className || '').slice(0, 60) : '',
            hit_inside: hit ? (el === hit || el.contains(hit) || hit.contains(el)) : false
          };
        })()""" % (json.dumps(selector), int(index))
        return self.try_evaluate(expression, transient_ok=False) or {'found': False}

    def click(self, selector, index=0, label=''):
        info = self.describe_target(selector, index)
        if not info.get('found'):
            raise FlowAbort('click target missing: %s (count=%s)' % (
                selector, info.get('count')))
        if not info.get('hit_inside'):
            raise FlowAbort('click target covered: %s hit=%s.%s' % (
                selector, info.get('hit_tag'), info.get('hit_class')))
        if info.get('w', 0) <= 0 or info.get('h', 0) <= 0:
            raise FlowAbort('click target has zero size: %s' % selector)
        x, y = int(info['x']), int(info['y'])
        self.call('Input.dispatchMouseEvent', type='mouseMoved', x=x, y=y, button='none')
        self.call('Input.dispatchMouseEvent', type='mousePressed', x=x, y=y,
                  button='left', buttons=1, clickCount=1)
        self.call('Input.dispatchMouseEvent', type='mouseReleased', x=x, y=y,
                  button='left', buttons=0, clickCount=1)
        return {
            'selector': selector, 'label': label, 'index': int(index),
            'x': x, 'y': y,
            'hit_tag': info.get('hit_tag'), 'hit_class': info.get('hit_class'),
        }

    def type_text(self, text):
        self.call('Input.insertText', text=text)

    def wait_value(self, expression, timeout=20, context_id=None, interval=0.15):
        deadline = time.time() + timeout
        pinned = context_id
        while time.time() < deadline:
            if pinned is None:
                self.pump(0.02)
            try:
                value = self.evaluate(expression, context_id=pinned)
            except EvaluationError as exc:
                if 'context gone' in str(exc):
                    pinned = None
                    time.sleep(interval)
                    continue
                raise
            if value:
                return value
            time.sleep(interval)
        return None

    # -- 导航 -------------------------------------------------------------
    def _latest_context(self, since_seq, frame_id):
        found = None
        for item in self.contexts:
            if not item['is_default'] or item['seq'] <= since_seq:
                continue
            if frame_id and item['frame_id'] and item['frame_id'] != frame_id:
                continue
            if found is None or item['seq'] >= found['seq']:
                found = item
        return found

    def expect_navigation(self, action, url_predicate, dom_expr, label='',
                          expected_loader=None, not_loader=None, timeout=35):
        """等待一次真实导航：frameNavigated(loaderId) -> 新 document context -> DOM 条件。

        * DOM 条件只在新 document 的 execution context 里求值，绝不可能读到旧
          document 的 readyState。
        * loaderId 可正匹配（Page.navigate 返回值）或反向要求不相等（reload）。
        """
        start_seq = self.event_seq
        action_result = action() or {}
        if isinstance(action_result, dict) and action_result.get('errorText'):
            raise FlowAbort('navigation error: ' + truncate(action_result['errorText'], 120))
        # Page.navigate 返回的 loaderId 只在"没有重定向链"时才等于最终 document；
        # /lab --303--> /login 这类链路会得到新的 loaderId。所以它只记为证据，
        # 不参与判定；需要严格匹配时由调用方显式传 expected_loader。
        request_loader = ''
        if isinstance(action_result, dict):
            request_loader = action_result.get('loaderId') or ''
        nav = None
        deadline = time.time() + timeout
        while time.time() < deadline:
            for item in self.nav_log:
                if item['seq'] <= start_seq:
                    continue
                if not url_predicate(item['url']):
                    continue
                nav = item
            if nav:
                break
            self.pump(0.1)
        if not nav:
            raise FlowAbort('no navigation to expected URL (%s)' % label)
        loader_id = nav['loader_id']
        if not loader_id:
            # 没有 loaderId 就无法证明这是新 document（可能读到旧 document）。
            raise FlowAbort('navigation without loaderId (%s)' % label)
        if expected_loader and loader_id != expected_loader:
            raise FlowAbort('loaderId mismatch (expected %s got %s) (%s)' % (
                truncate(expected_loader, 20), truncate(loader_id, 20), label))
        if not_loader and loader_id == not_loader:
            raise FlowAbort('document not replaced: same loaderId (%s)' % label)
        context = None
        pinned = None
        ready = None
        deadline = time.time() + timeout
        while time.time() < deadline:
            if pinned is None:
                candidate = self._latest_context(start_seq, nav['frame_id'])
                pinned = candidate['id'] if candidate else None
            if pinned is None:
                self.pump(0.05)
                continue
            try:
                ready = self.evaluate(dom_expr, context_id=pinned)
            except EvaluationError as exc:
                if 'context gone' in str(exc):
                    pinned = None
                    continue
                raise
            if ready:
                break
            ready = None
            time.sleep(0.1)
        if pinned is None:
            raise FlowAbort('no execution context for the new document (%s)' % label)
        if not ready:
            raise FlowAbort('DOM condition not met on new document (%s)' % label)
        return {
            'url': nav['url'],
            'loader_id': loader_id,
            'request_loader_id': request_loader,
            'redirected': bool(request_loader and request_loader != loader_id),
            'frame_id': nav['frame_id'],
            'context_id': pinned,
            'dom': ready,
        }


# ---------------------------------------------------------------------------
# 事件汇（console / JS 异常 / Log）
# ---------------------------------------------------------------------------
class EventSink(object):
    """收集所有 JS 异常、console.error 与 Log error，并给出可解释的分类。"""

    ERROR_KINDS = ('exception', 'console-error', 'log-error',
                   'evaluate-exception', 'transport-error')

    def __init__(self, secrets=()):
        self.secrets = list(secrets)
        self.entries = []

    def add(self, kind, source, text):
        self.entries.append({
            'kind': kind,
            'source': source,
            'text': redact(truncate(text, 320), self.secrets),
        })

    def add_exception(self, params):
        details = params.get('exceptionDetails') or {}
        exc = details.get('exception') or {}
        parts = [details.get('text') or '', exc.get('className') or '',
                 exc.get('description') or '']
        text = ' | '.join(part for part in parts if part)
        self.add('exception', 'javascript', text or 'exceptionThrown without details')

    def add_console(self, params):
        kind = params.get('type') or 'log'
        summaries = [self._describe_arg(arg) for arg in (params.get('args') or [])]
        text = ' '.join(item for item in summaries if item) or '(no serialisable args)'
        if kind == 'error':
            self.add('console-error', 'console', text)
        elif kind in ('warning', 'assert'):
            self.add('console-' + kind, 'console', text)

    @staticmethod
    def _describe_arg(arg):
        """无字符串参数的 console.error 也必须可读（object/undefined/空）。"""
        if not isinstance(arg, dict):
            return '<unparsed>'
        kind = arg.get('type')
        if kind == 'string':
            return truncate(arg.get('value') or '', 140)
        if kind in ('number', 'boolean'):
            return str(arg.get('value'))
        if kind == 'undefined':
            return 'undefined'
        if kind == 'object' and arg.get('subtype') == 'null':
            return 'null'
        description = arg.get('description')
        if isinstance(description, str) and description:
            return truncate(description, 140)
        subtype = arg.get('subtype') or ''
        return '<%s%s>' % (kind or 'unknown', (':' + subtype) if subtype else '')

    def add_log(self, params):
        entry = params.get('entry') or {}
        if str(entry.get('level') or '') != 'error':
            return
        source = str(entry.get('source') or 'unknown')
        text = str(entry.get('text') or '')
        url = str(entry.get('url') or '')
        # favicon 是唯一允许的精确例外：必须是/log/favicon.ico + network 来源。
        if source == 'network' and url_path(url) == FAVICON_PATH:
            if '404' in text or 'ERR_ABORTED' in text or 'Failed to load resource' in text:
                self.add('log-ignored-favicon', source,
                         '%s | url=%s | line=%s' % (
                             truncate(text, 200), truncate(url, 120),
                             entry.get('lineNumber')))
                return
        self.add('log-error', source, '%s | url=%s | line=%s' % (
            truncate(text, 200), truncate(url, 120), entry.get('lineNumber')))

    def error_entries(self):
        return [item for item in self.entries if item['kind'] in self.ERROR_KINDS]

    def ignored_entries(self):
        return [item for item in self.entries if item['kind'] not in self.ERROR_KINDS]

    def summary(self):
        counts = {}
        for item in self.entries:
            counts[item['kind']] = counts.get(item['kind'], 0) + 1
        return counts


# ---------------------------------------------------------------------------
# 配置

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
class Config(object):
    def __init__(self):
        def need(name):
            value = (os.environ.get(name) or '').strip()
            if not value:
                raise KeyError(name)
            return value

        def csv(name, default):
            raw = (os.environ.get(name) or '').strip()
            if not raw:
                return tuple(default)
            return tuple(part for part in (item.strip() for item in raw.split(',')) if part)

        self.chrome = need('CHROME_BIN')
        self.url = need('URL').rstrip('/')
        self.login = need('LOGIN')
        self.password = need('PASSWORD')
        self.out_dir = os.path.abspath(need('OUT_DIR'))
        self.spki = (os.environ.get('SPKI') or '').strip()
        self.ca_file = ((os.environ.get('P2_CA_FILE') or '').strip()
                        or (os.environ.get('CA_FILE') or '').strip())
        self.http_addr = (os.environ.get('P2_HTTP_ADDR') or '127.0.0.1').strip()
        # P2_QUERY 是现有 runner 的变量名；P2_SEARCH_QUERY 是本脚本更明确的别名。
        self.query = ((os.environ.get('P2_SEARCH_QUERY')
                       or os.environ.get('P2_QUERY')
                       or DEFAULT_SEARCH_QUERY).strip())
        self.expect_terms = csv('P2_EXPECT_TERMS', DEFAULT_EXPECT_TERMS)
        self.exclude_terms = csv('P2_EXCLUDE_TERMS', DEFAULT_EXCLUDE_TERMS)
        self.detail_term = (os.environ.get('P2_DETAIL_TERM') or '').strip()
        parts = urlsplit(self.url)
        self.scheme = (parts.scheme or 'https').lower()
        self.host = parts.hostname or ''
        self.port = parts.port or (443 if self.scheme == 'https' else 80)
        if not self.host:
            raise ValueError('URL lacks host')
        netloc = self.host if self.port in (80, 443) else '%s:%d' % (self.host, self.port)
        self.origin = '%s://%s' % (self.scheme, netloc)

    def secrets(self):
        return [('password', self.password)]


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def js_str(value):
    return json.dumps(value, ensure_ascii=False)


def page_state_js():
    return """(() => {
      const q = function (sel) { return document.querySelector(sel); };
      const txt = function (el) { return el ? (el.textContent || '').trim() : ''; };
      const main = q('#lc-main') || document.body;
      return {
        path: location.pathname,
        search: location.search,
        auth: document.body ? document.body.getAttribute('data-authenticated') : null,
        base: document.body ? document.body.getAttribute('data-base') : null,
        loginForm: !!q('#lc-login-form'),
        logoutForm: !!q('form.lc-logout-form'),
        csrfInput: !!q('form.lc-logout-form input[name=csrf_token]'),
        errorPage: !!q('.lc-error-page'),
        alertText: (function () {
          const el = q('.lc-alert.lc-alert-error');
          return el && !el.hasAttribute('hidden') ? (el.textContent || '').trim() : '';
        })(),
        body: (main.innerText || '').slice(0, 6000)
      };
    })()"""


class BrowserFlow(object):
    def __init__(self, cfg):
        self.cfg = cfg
        self.recorder = NetworkRecorder(secrets=[cfg.password], entry_origin=cfg.origin)
        self.sink = EventSink([('password', cfg.password)])
        self.cdp = None
        self.proc = None
        self.ws = None
        self.devtools_port = None
        self.profile_dir = None
        self.profile_real = None
        self.owner_token = hashlib.sha256(
            ('%d-%f' % (os.getpid(), time.time())).encode('ascii')).hexdigest()[:32]
        self.steps = {}
        self.screenshots = []
        self.notes = []
        self.abort_reason = ''
        self.hard_env_failure = False
        self.cookies = []                 # 仅内存；不落盘
        self.hit_links = []
        self.hit_keys = []
        self.detail_snapshot = {}
        self.details = {'search': {}, 'detail': {}, 'logout': {}, 'anonymous': {}}

    # -- 步骤登记 ---------------------------------------------------------
    def step(self, name, status, detail=''):
        if name in self.steps:
            raise RuntimeError('duplicate step: ' + name)
        self.steps[name] = {
            'name': name,
            'status': status,
            'ok': status == 'pass',
            'detail': redact(truncate(detail, 400), [('password', self.cfg.password)]),
        }

    def note(self, text):
        self.notes.append(redact(truncate(text, 240), [('password', self.cfg.password)]))

    def shot(self, name):
        if self.cdp is None:
            return
        try:
            data = self.cdp.call('Page.captureScreenshot', format='png').get('data')
            path = os.path.join(self.cfg.out_dir, 'shot-%s.png' % name)
            with open(path, 'wb') as handle:
                handle.write(base64.b64decode(data))
            self.screenshots.append(os.path.basename(path))
        except Exception as exc:
            self.note('screenshot %s failed: %s' % (name, truncate(exc, 80)))

    # -- 入口 -------------------------------------------------------------
    def run(self):
        try:
            self.check_env()
            self.launch_chrome()
            self.connect_cdp()
            self.flow_login()
            self.flow_search()
            self.flow_detail()
            self.flow_refresh()
            self.flow_logout()
            self.flow_anonymous()
            self.flow_old_cookie()
        except FlowAbort as exc:
            self.abort_reason = redact(truncate(exc, 240), [('password', self.cfg.password)])
        except Exception as exc:
            self.abort_reason = 'unexpected: ' + redact(
                truncate('%s: %s' % (type(exc).__name__, exc), 240),
                [('password', self.cfg.password)])
            self.note('traceback: ' + truncate(traceback.format_exc(limit=3), 500))
        finally:
            try:
                self.verify_events()
            except Exception as exc:
                self.note('verify_events failed: ' + truncate(exc, 160))
            try:
                self.cleanup()
            except Exception as exc:
                self.note('cleanup failed: ' + truncate(exc, 160))
        return 0

    # -- 环境 -------------------------------------------------------------
    def check_env(self):
        problems = []
        if not os.path.isfile(self.cfg.chrome):
            problems.append('CHROME_BIN 不存在')
        if self.cfg.scheme != 'https':
            problems.append('URL 必须是 https 入口')
        if not self.cfg.query:
            problems.append('检索词为空')
        try:
            os.makedirs(self.cfg.out_dir, exist_ok=True)
        except OSError as exc:
            problems.append('OUT_DIR 不可创建: ' + truncate(exc, 60))
        if not problems and contains_link_component(self.cfg.out_dir):
            problems.append('OUT_DIR 路径链含 symlink/junction')
        if problems:
            self.hard_env_failure = True
            self.step('env', 'fail', '; '.join(problems))
            raise FlowAbort('env: ' + '; '.join(problems))
        if self.cfg.ca_file:
            tls = 'ca-file'
        elif self.cfg.spki:
            tls = 'spki-pin'
        else:
            tls = 'unset'
            self.note('未提供 P2_CA_FILE/CA_FILE/SPKI：独立 HTTP 与旧 cookie 验证会被 blocked')
        self.step('env', 'pass', 'tls=%s query=%s entry=%s' % (
            tls, truncate(self.cfg.query, 40), self.cfg.origin))

    # -- Chrome -----------------------------------------------------------
    def launch_chrome(self):
        try:
            self.profile_dir, self.profile_real = safe_child_dir(
                self.cfg.out_dir, 'chrome-profile-')
            write_owner_marker(self.profile_real, self.owner_token)
        except (ValueError, OSError) as exc:
            self.step('chrome-launch', 'fail', 'profile 边界拒绝: ' + truncate(exc, 140))
            raise FlowAbort('profile: ' + truncate(exc, 120))
        args = [
            self.cfg.chrome,
            '--headless=new',
            '--disable-gpu',
            '--disable-dev-shm-usage',
            '--no-first-run',
            '--no-default-browser-check',
            '--disable-background-networking',
            '--disable-component-update',
            '--disable-sync',
            '--disable-default-apps',
            '--mute-audio',
            '--window-size=1280,900',
            '--remote-debugging-port=0',
            '--user-data-dir=' + self.profile_real,
            '--host-resolver-rules=MAP %s %s' % (self.cfg.host, self.cfg.http_addr),
            'about:blank',
        ]
        if self.cfg.spki:
            args.insert(-1, '--ignore-certificate-errors-spki-list=' + self.cfg.spki)
        try:
            self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL)
        except OSError as exc:
            self.step('chrome-launch', 'fail', 'start failed: ' + truncate(exc, 140))
            raise FlowAbort('chrome start failed')
        port_file = os.path.join(self.profile_real, 'DevToolsActivePort')
        for _ in range(400):
            if self.proc.poll() is not None:
                self.step('chrome-launch', 'fail',
                          'chrome 提前退出 rc=%s' % self.proc.returncode)
                raise FlowAbort('chrome exited early')
            if os.path.exists(port_file):
                try:
                    with open(port_file, encoding='utf-8') as handle:
                        self.devtools_port = int(handle.read().splitlines()[0].strip())
                    break
                except (OSError, ValueError, IndexError):
                    pass
            time.sleep(0.05)
        if not self.devtools_port:
            self.step('chrome-launch', 'fail', 'DevToolsActivePort 缺失')
            raise FlowAbort('DevToolsActivePort missing')
        self.step('chrome-launch', 'pass',
                  'profile=<OUT_DIR>/chrome-profile-* devtools=loopback 无 --no-sandbox')

    def connect_cdp(self):
        try:
            from websockets.sync.client import connect
        except Exception as exc:
            self.step('cdp-connect', 'fail', 'websockets 不可用: ' + truncate(exc, 100))
            raise FlowAbort('websockets missing')
        try:
            import urllib.request
            with urllib.request.urlopen(
                    'http://127.0.0.1:%d/json/list' % self.devtools_port,
                    timeout=10) as resp:
                targets = json.load(resp)
            page = None
            for item in targets:
                if item.get('type') == 'page' and item.get('webSocketDebuggerUrl'):
                    page = item
                    break
            if page is None:
                request = urllib.request.Request(
                    'http://127.0.0.1:%d/json/new?about:blank' % self.devtools_port,
                    method='PUT')
                with urllib.request.urlopen(request, timeout=10) as resp:
                    page = json.load(resp)
                targets = targets + [page]
            self.ws = connect(page['webSocketDebuggerUrl'], max_size=2 ** 25,
                              open_timeout=20)
        except Exception as exc:
            self.step('cdp-connect', 'fail', 'CDP 连接失败: ' + truncate(exc, 140))
            raise FlowAbort('cdp connect failed')
        self.cdp = CDP(self.ws, self.recorder, self.sink)
        for domain in ('Page.enable', 'Runtime.enable', 'Log.enable'):
            self.cdp.call(domain)
        self.cdp.call('Network.enable', maxPostDataSize=262144)
        self.cdp.call('Page.setLifecycleEventsEnabled', enabled=True)
        self.step('cdp-connect', 'pass',
                  'targets=%d domains=Page/Runtime/Log/Network' % len(targets))

    # -- 通用 -------------------------------------------------------------
    def current_loader(self):
        for item in reversed(self.cdp.nav_log):
            if item['loader_id']:
                return item['loader_id']
        return ''

    def prepare_navigation(self, label, path=None):
        """在**本脚本主动触发**的导航前，逐 requestId 登记预期中止。

        只登记"此刻真的在飞"的请求（可选再按 path 收窄），并把原因写进证据；
        未登记的 ERR_ABORTED 仍然算失败，所以这不是泛化过滤器。
        """
        before = len(self.recorder.allowed_aborts)
        self.recorder.allow_aborts(label, path=path)
        added = len(self.recorder.allowed_aborts) - before
        if added:
            self.details.setdefault('intentional_aborts', []).append(
                {'during': label, 'path_filter': path or '*', 'requests': added})

    def type_into(self, selector, text):
        """点真实元素聚焦 -> 清空旧值（如有）-> Input.insertText -> 回读校验。"""
        info = self.cdp.click(selector, label='focus')
        current = self.cdp.evaluate(
            "(() => { const el = document.querySelector(%s);"
            " return el ? String(el.value || '') : null; })()" % js_str(selector))
        if current is None:
            raise FlowAbort('输入框不存在: ' + selector)
        if current:
            self.cdp.call('Input.dispatchKeyEvent', type='rawKeyDown', modifiers=2,
                          key='a', code='KeyA', windowsVirtualKeyCode=65,
                          nativeVirtualKeyCode=65, commands=['selectAll'])
            self.cdp.call('Input.dispatchKeyEvent', type='keyUp', modifiers=2,
                          key='a', code='KeyA', windowsVirtualKeyCode=65,
                          nativeVirtualKeyCode=65)
            self.cdp.call('Input.dispatchKeyEvent', type='rawKeyDown', key='Backspace',
                          code='Backspace', windowsVirtualKeyCode=8,
                          nativeVirtualKeyCode=8)
            self.cdp.call('Input.dispatchKeyEvent', type='keyUp', key='Backspace',
                          code='Backspace', windowsVirtualKeyCode=8,
                          nativeVirtualKeyCode=8)
        self.cdp.type_text(text)
        value = self.cdp.evaluate(
            "(() => { const el = document.querySelector(%s);"
            " return el ? String(el.value || '') : null; })()" % js_str(selector))
        if value != text:
            raise FlowAbort('输入回读不一致（%s）' % selector)
        return {'click': info, 'len': len(value or '')}

    # -- 登录 -------------------------------------------------------------
    def flow_login(self):
        login_url = self.cfg.url + LOGIN_PATH + '?next=' + LAB_PATH
        def login_nav():
            self.prepare_navigation('initial navigation to /login')
            return self.cdp.call('Page.navigate', url=login_url)

        nav = self.cdp.expect_navigation(
            login_nav,
            lambda url: url_path(url) == LOGIN_PATH,
            "document.readyState !== 'loading'"
            " && !!document.getElementById('lc-login-form')"
            " && !!document.querySelector('#lc-login-form input[name=login]')"
            " && !!document.querySelector('#lc-login-form button[type=submit]')",
            label='login page')
        self.step('login-page', 'pass', 'path=%s loader=%s' % (
            url_path(nav['url']), truncate(nav['loader_id'], 16)))
        self.shot('01-login')

        account = self.type_into('#lc-login-form input[name=login]', self.cfg.login)
        secret = self.type_into('#lc-login-form input[name=password]', self.cfg.password)
        click_info = {}

        def submit():
            self.prepare_navigation('login submit navigates to /lab')
            click_info.update(self.cdp.click(
                '#lc-login-form button[type=submit]', label='login-submit'))
            return {}

        nav = self.cdp.expect_navigation(
            submit,
            lambda url: url_path(url) == LAB_PATH,
            "document.readyState !== 'loading'"
            " && document.body.getAttribute('data-authenticated') === '1'"
            " && !!document.getElementById('lc-grid')"
            " && !!document.getElementById('lc-q')"
            " && !!document.querySelector('form.lc-logout-form')",
            label='post-login lab')
        state = self.cdp.evaluate(page_state_js(), context_id=nav['context_id']) or {}
        logged_in = (state.get('auth') == '1' and state.get('logoutForm') is True
                     and state.get('loginForm') is False)
        self.step('login-ui-submit', 'pass' if logged_in else 'fail',
                  'account_typed=%s password_typed=%s click_hit=%s.%s'
                  % (account['len'] > 0, secret['len'] > 0,
                     click_info.get('hit_tag'), click_info.get('hit_class')))
        if not logged_in:
            raise FlowAbort('登录后未标记已登录或缺少退出表单')
        self.step('lab-authenticated', 'pass',
                  'path=%s loader=%s account_label=%s'
                  % (url_path(nav['url']), truncate(nav['loader_id'], 16),
                     digest_label(self.cfg.login, self.owner_token)))
        self.shot('02-lab')

    # -- 检索：真实 UI 输入 + 真实提交 + RPC 解码 ------------------------
    def flow_search(self):
        before = self.recorder.seq
        typed = self.type_into('#lc-q', self.cfg.query)
        self.step('search-ui-input', 'pass',
                  'value_len=%d focus_hit=%s.%s' % (
                      typed['len'], typed['click'].get('hit_tag'),
                      typed['click'].get('hit_class')))
        click_info = {}

        def submit():
            # 打字会触发 450ms 防抖检索；显式提交会 abort 它，这是预期行为。
            self.prepare_navigation('explicit search submit aborts debounce request',
                                    path=SEARCH_PATH)
            click_info.update(self.cdp.click('#lc-search-form button[type=submit]',
                                             label='search-submit'))
            return {}

        submit()

        # 浏览器自己的检索 RPC：只在 /lab/api/catalog/search 上解码 params.query
        #
        # Chrome 通常直接在 requestWillBeSent 里给出 postData（已在 record_request 里解码），
        # 只有缺失时才需要 Network.getRequestPostData 补取；两条路径都要覆盖。
        # 取"最后一次"命中的请求：打字触发的防抖检索可能先到，显式提交的结果才是最终界面。
        found = None
        deadline = time.time() + 30
        while time.time() < deadline:
            self.cdp.pump(0.05)
            for hop in self.recorder.pending_search_bodies():
                if hop['seq'] < before:
                    continue
                try:
                    body = self.cdp.call('Network.getRequestPostData',
                                         requestId=hop['request_id'], timeout=10)
                    post_data = (body or {}).get('postData')
                except CDPError as exc:
                    post_data = None
                    self.recorder.attach_post_data(
                        hop['request_id'], None, 'getRequestPostData: ' + truncate(exc, 80))
                    continue
                if post_data:
                    self.recorder.attach_post_data(hop['request_id'], post_data)
            decoded = [hop for hop in self.recorder.search_hops(before)
                       if hop['rpc'] and hop['rpc'].get('query')]
            if decoded:
                found = decoded[-1]
                # 给可能的第二个（显式提交）检索一点时间到齐，再以最后一个为准
                settle_until = time.time() + 1.0
                while time.time() < settle_until:
                    self.cdp.pump(0.05)
                    newer = [hop for hop in self.recorder.search_hops(before)
                             if hop['rpc'] and hop['rpc'].get('query')]
                    if newer and newer[-1]['seq'] != found['seq']:
                        found = newer[-1]
                break
            time.sleep(0.1)
        if not found:
            rpc_hops = self.recorder.search_hops(before)
            self.details['search'] = {
                'search_hops': len(rpc_hops),
                'rpc_query': None,
                'click_hit': click_info.get('hit_class'),
            }
            self.step('search-rpc-query', 'fail',
                      '未从真实请求解码到 params.query（search_hops=%d）' % len(rpc_hops))
            raise FlowAbort('search RPC not captured')

        rpc = found['rpc'] or {}
        same_origin = found['origin'] == self.cfg.origin
        method_ok = found['method'] == 'POST'
        query_ok = rpc.get('query') == self.cfg.query
        self.details['search'] = {
            'request_method': found['method'],
            'request_path': found['path'],
            'request_origin_matches_entry': same_origin,
            'request_id': found['request_id'],
            'loader_id': truncate(found['loader_id'], 32),
            'jsonrpc': truncate(rpc.get('jsonrpc') or '', 10),
            'rpc_method': truncate(rpc.get('method') or '', 20),
            'rpc_query': truncate(rpc.get('query') or '', 120),
            'rpc_query_matches_ui_input': query_ok,
            'rpc_category_id': rpc.get('category_id'),
            'rpc_stock_only': rpc.get('stock_only'),
            'rpc_limit': rpc.get('limit'),
            'click_hit': '%s.%s' % (click_info.get('hit_tag'),
                                    click_info.get('hit_class')),
        }
        rpc_ok = bool(same_origin and method_ok and query_ok)
        self.step('search-rpc-query', 'pass' if rpc_ok else 'fail',
                  'post=%s same_origin=%s jsonrpc=%s decoded_query=%s ui_input=%s'
                  % (method_ok, same_origin, rpc.get('jsonrpc'),
                     truncate(rpc.get('query') or '-', 40),
                     truncate(self.cfg.query, 40)))
        if not rpc_ok:
            raise FlowAbort('检索 RPC 的 params.query/来源与 UI 输入不一致')

        # DOM 必须渲染完：meta 含本次关键词 + 卡片存在 + 无错误提示
        wait_expr = ("(() => {"
                     " const meta = document.querySelector('#lc-results .lc-results-meta');"
                     " const grid = document.getElementById('lc-grid');"
                     " if (!meta || !grid) return null;"
                     " const metaText = meta.textContent || '';"
                     " const cards = grid.querySelectorAll('article.lc-item').length;"
                     " const alertEl = document.querySelector('.lc-alert.lc-alert-error');"
                     " const alertOn = alertEl && !alertEl.hasAttribute('hidden');"
                     " if (alertOn) return {alert: (alertEl.textContent || '').trim()};"
                     " if (metaText.indexOf(%s) === -1) return null;"
                     " if (!cards) return null;"
                     " return {meta: metaText.slice(0, 160), cards: cards,"
                     "   total: document.getElementById('lc-results')"
                     "     .getAttribute('data-total'),"
                     "   url: location.pathname + location.search};"
                     "})()" % js_str(self.cfg.query))
        rendered = self.cdp.wait_value(wait_expr, timeout=30)
        if not rendered or rendered.get('alert'):
            detail = '未渲染（meta/cards 未更新）' if not rendered else (
                '页面错误提示: ' + truncate(rendered.get('alert') or '', 100))
            self.details['search']['dom_ready'] = False
            self.details['search']['dom_alert'] = truncate(
                (rendered or {}).get('alert') or '', 120)
            self.step('search-dom-match', 'fail', detail)
            raise FlowAbort('检索结果未渲染到 DOM')

        grid = self.cdp.evaluate("""(() => {
          const grid = document.getElementById('lc-grid');
          const cards = Array.from(grid.querySelectorAll('article.lc-item'));
          return {
            text: (grid.innerText || '').slice(0, 4000),
            keys: cards.map(function (c) { return c.getAttribute('data-item-key') || ''; }),
            names: cards.map(function (c) {
              const el = c.querySelector('.lc-item-name');
              return el ? (el.textContent || '').trim() : '';
            }),
            links: cards.map(function (c) {
              const a = c.querySelector('a.lc-item-link');
              return a ? a.getAttribute('href') : '';
            })
          };
        })()""") or {}
        text = grid.get('text') or ''
        missing = [term for term in self.cfg.expect_terms if term not in text]
        excluded = [term for term in self.cfg.exclude_terms if term in text]
        keys = [key for key in grid.get('keys') or [] if key]
        links = [link for link in grid.get('links') or [] if link]
        url_synced = self.cfg.query in (rendered.get('url') or '')
        dom_ok = bool(not missing and not excluded and keys and links and url_synced)
        self.details['search'].update({
            'dom_cards': rendered.get('cards'),
            'dom_total': rendered.get('total'),
            'dom_missing_terms': missing,
            'dom_excluded_terms_found': excluded,
            'dom_url_has_query': url_synced,
            'dom_item_keys': [truncate(key, 60) for key in keys[:6]],
            'dom_ready': True,
        })
        self.step('search-dom-match', 'pass' if dom_ok else 'fail',
                  'cards=%s missing=%s excluded=%s url_has_query=%s'
                  % (rendered.get('cards'), missing or '-', excluded or '-', url_synced))
        self.shot('03-search')
        if not dom_ok:
            raise FlowAbort('检索 DOM 与查询不一致（缺词/含电容对照/链接缺失/URL 未同步）')
        self.hit_links = links
        self.hit_keys = keys

    # -- 详情：点击命中项的真实链接 --------------------------------------
    def flow_detail(self):
        # 按检索结果的真实顺序，挑第一个"应用路由真的受理"的链接（不写死任何 key）。
        # 不合格的命中项要单独记下来：那是模块/种子的问题，不能被静默跳过。
        chosen = None
        rejected = []
        for index, link in enumerate(self.hit_links):
            key = self.hit_keys[index] if index < len(self.hit_keys) else ''
            if not link.startswith(DETAIL_PREFIX):
                rejected.append({'index': index, 'item_key': truncate(key, 60),
                                 'reason': 'href not a detail route'})
                continue
            if not is_routable_detail_key(key):
                rejected.append({'index': index, 'item_key': truncate(key, 60),
                                 'href': truncate(link, 90),
                                 'reason': 'itemKey not accepted by app route '
                                           '(expect lab:<id> or lcsc:C<digits>)'})
                continue
            chosen = (index, link, key)
            break
        self.details['detail'] = {
            'hit_count': len(self.hit_links),
            'rejected_links': rejected,
            'link_from_search_results': True,
            'link_is_dynamic': True,
            'hardcoded_item_key': False,
        }
        if chosen is None:
            self.step('detail-link', 'fail',
                      '没有可路由的详情链接（命中 %d 个，拒绝 %d 个）'
                      % (len(self.hit_links), len(rejected)))
            raise FlowAbort('no routable detail link in search results')
        index, link, key = chosen
        self.details['detail'].update({
            'href': truncate(link, 120),
            'item_key': truncate(key, 60),
            'hit_index': index,
            'path_matches_key': link == detail_path_for(key),
        })
        self.step('detail-link', 'pass', 'href=%s key=%s index=%d rejected=%d'
                  % (truncate(link, 90), truncate(key, 60), index, len(rejected)))

        click_info = {}

        def click_link():
            self.prepare_navigation('detail link navigation cancels pending subresources')
            click_info.update(self.cdp.click('#lc-grid a.lc-item-link', index,
                                             label='detail-link'))
            return {}

        nav = self.cdp.expect_navigation(
            click_link,
            lambda url: url_path(url).startswith(DETAIL_PREFIX),
            "document.readyState !== 'loading'"
            " && !!document.querySelector('.lc-detail')"
            " && !!document.querySelector('.lc-detail-title')",
            label='detail page')
        self.step('detail-ui-click', 'pass',
                  'path=%s click_hit=%s.%s loader=%s'
                  % (url_path(nav['url']), click_info.get('hit_tag'),
                     click_info.get('hit_class'), truncate(nav['loader_id'], 16)))

        state = self.cdp.evaluate(page_state_js(), context_id=nav['context_id']) or {}
        body_text = state.get('body') or ''
        expect = [self.cfg.query]
        if self.cfg.detail_term:
            expect.append(self.cfg.detail_term)
        for term in self.cfg.expect_terms:
            if term not in expect:
                expect.append(term)
        missing = [term for term in expect if term not in body_text]
        path = state.get('path') or ''
        # 地址栏是百分号编码后的形态；直接比"解码前后的同一个 key"
        key_in_path = path in (detail_path_for(key), DETAIL_PREFIX + key)
        is_error_page = bool(state.get('errorPage'))
        title = ''
        for line in body_text.split('\n'):
            if line.strip():
                title = line.strip()
                break
        content_ok = (not missing and key_in_path and not is_error_page
                      and '暂时无法显示器件' not in body_text)
        self.details['detail'].update({
            'path': truncate(path, 100),
            'key_in_path': key_in_path,
            'loader_id': truncate(nav['loader_id'], 32),
            'body_len': len(body_text),
            'missing_terms': missing,
            'authenticated': state.get('auth'),
            'logout_form_present': state.get('logoutForm'),
            'is_error_page': is_error_page,
        })
        self.step('detail-content', 'pass' if content_ok else 'fail',
                  'path=%s key_in_path=%s body_len=%d missing=%s'
                  % (truncate(path, 60), key_in_path, len(body_text), missing or '-'))
        self.step('detail-not-error', 'pass' if not is_error_page else 'fail',
                  'error_page=%s alert=%s' % (
                      is_error_page, truncate(state.get('alertText') or '-', 80)))
        self.shot('04-detail')
        if not content_ok:
            raise FlowAbort('详情页内容与命中项不一致')
        if is_error_page:
            raise FlowAbort('详情页渲染为错误页')
        self.detail_snapshot = {
            'path': path,
            'body_len': len(body_text),
            'text': body_text[:1200],
        }

    # -- 刷新：仍登录 + 内容保持（且确实是新 document） ------------------
    def flow_refresh(self):
        before_loader = ''
        for item in reversed(self.cdp.nav_log):
            if url_path(item['url']).startswith(DETAIL_PREFIX):
                before_loader = item['loader_id']
                break
        def reload_action():
            self.prepare_navigation('intentional Page.reload')
            return self.cdp.call('Page.reload', ignoreCache=False)

        nav = self.cdp.expect_navigation(
            reload_action,
            lambda url: url_path(url).startswith(DETAIL_PREFIX),
            "document.readyState !== 'loading'"
            " && document.body.getAttribute('data-authenticated') === '1'"
            " && !!document.querySelector('.lc-detail')"
            " && !!document.querySelector('.lc-detail-title')",
            label='refresh detail', not_loader=before_loader)
        state = self.cdp.evaluate(page_state_js(), context_id=nav['context_id']) or {}
        body_text = state.get('body') or ''
        replaced = bool(before_loader) and before_loader != nav['loader_id']
        still_auth = (state.get('auth') == '1' and state.get('loginForm') is False
                      and state.get('logoutForm') is True)
        snapshot = self.detail_snapshot or {}
        content_kept = (self.cfg.query in body_text
                        and not state.get('errorPage')
                        and (state.get('path') or '') == snapshot.get('path'))
        self.details['detail'].update({
            'refresh_loader_before': truncate(before_loader, 32),
            'refresh_loader_after': truncate(nav['loader_id'], 32),
            'refresh_document_replaced': replaced,
            'refresh_authenticated': still_auth,
            'refresh_content_kept': content_kept,
        })
        self.step('refresh-ui', 'pass' if replaced else 'fail',
                  'loader_changed=%s after=%s' % (replaced,
                                                  truncate(nav['loader_id'], 16)))
        self.step('refresh-authenticated', 'pass' if still_auth else 'fail',
                  'auth=%s login_form=%s logout_form=%s account_label=%s'
                  % (state.get('auth'), state.get('loginForm'),
                     state.get('logoutForm'),
                     digest_label(self.cfg.login, self.owner_token)))
        self.step('refresh-content', 'pass' if content_kept else 'fail',
                  'path=%s query_present=%s error_page=%s'
                  % (truncate(state.get('path') or '', 50),
                     self.cfg.query in body_text, bool(state.get('errorPage'))))
        self.shot('05-refresh')
        if not (replaced and still_auth and content_kept):
            raise FlowAbort('刷新后未保持登录或内容丢失')

    # -- 退出：真实 UI 提交 + 303 精确归属 + 显式匿名 --------------------
    def flow_logout(self):
        # 1) 退出前抓会话 cookie，只放内存（下面用它做独立 HTTP 的旧会话失效验证）
        cookies = self.cdp.call('Network.getAllCookies').get('cookies') or []
        jar = []
        for item in cookies:
            jar.append({
                'name': str(item.get('name') or ''),
                'value': str(item.get('value') or ''),
                'domain': str(item.get('domain') or ''),
                'path': str(item.get('path') or ''),
                'secure': bool(item.get('secure')),
                'http_only': bool(item.get('httpOnly')),
                'same_site': str(item.get('sameSite') or ''),
            })
        self.cookies = jar
        names = sorted(item['name'] for item in jar)
        session_cookie = [item for item in jar if item['name'] == 'session_id']
        self.details['logout'] = {
            'cookie_names': names,
            'cookie_count': len(jar),
            'session_cookie_present': bool(session_cookie),
            'session_cookie_httponly': bool(session_cookie and session_cookie[0]['http_only']),
            'session_cookie_secure': bool(session_cookie and session_cookie[0]['secure']),
            'session_cookie_samesite': (session_cookie[0]['same_site']
                                        if session_cookie else ''),
            'cookie_retained': 'in-memory only',
        }
        self.step('logout-cookie-capture', 'pass' if session_cookie else 'fail',
                  'cookie_count=%d names=%s httponly=%s secure=%s samesite=%s (仅内存)'
                  % (len(jar), ','.join(names) or '-',
                     self.details['logout']['session_cookie_httponly'],
                     self.details['logout']['session_cookie_secure'],
                     self.details['logout']['session_cookie_samesite'] or '-'))
        if not session_cookie:
            raise FlowAbort('未抓到会话 cookie，无法验证旧会话失效')

        before = self.recorder.seq
        click_info = {}

        def submit():
            self.prepare_navigation('logout submit navigates to /login')
            click_info.update(self.cdp.click('form.lc-logout-form button[type=submit]',
                                             label='logout-submit'))
            return {}

        nav = self.cdp.expect_navigation(
            submit,
            lambda url: url_path(url) == LOGIN_PATH,
            "document.readyState !== 'loading'"
            " && !!document.getElementById('lc-login-form')"
            " && document.body.getAttribute('data-authenticated') === '0'",
            label='logout -> login')
        self.step('logout-ui-submit', 'pass',
                  'click_hit=%s.%s landed=%s（真实表单提交，非测试 fetch）'
                  % (click_info.get('hit_tag'), click_info.get('hit_class'),
                     url_path(nav['url'])))

        # 2) 303 归属：只看该 requestId 自己的 redirectResponse，from 必须是 POST /logout
        redirect = None
        deadline = time.time() + 15
        while time.time() < deadline:
            candidates = [item for item in self.recorder.logout_redirects(before)
                          if item['status'] == 303]
            if candidates:
                redirect = candidates[-1]
                break
            self.cdp.pump(0.05)
            time.sleep(0.1)
        if redirect is None:
            self.step('logout-redirect-303', 'fail',
                      '未捕获 POST /logout 的 303（/logout redirect 数=%d）'
                      % len(self.recorder.logout_redirects(before)))
            raise FlowAbort('logout 303 not captured')
        # 同源判定：被重定向的请求本身就在入口 origin 上，且跳转落在登录页；
        # 再看浏览器实际落地的 URL 是否仍在同一个 origin（相对跳转应保留端口）。
        from_origin_ok = (redirect['from_url'] or '').startswith(self.cfg.origin + '/')
        landed_origin_ok = url_origin(nav['url']) == self.cfg.origin
        self.details['logout'].update({
            'redirect_status': redirect['status'],
            'redirect_from_path': redirect['from_path'],
            'redirect_from_method': redirect['from_method'],
            'redirect_to_path': redirect['to_path'],
            'redirect_request_id': redirect['request_id'],
            'redirect_from_hop_index': redirect['from_hop_index'],
            'redirect_same_origin': bool(from_origin_ok and landed_origin_ok),
            'landed_url_same_origin': landed_origin_ok,
            'navigation_redirected': bool(nav.get('redirected')),
            'redirect_attribution': 'requestWillBeSent.redirectResponse by requestId+hop',
        })
        redirect_ok = (redirect['status'] == 303
                       and redirect['from_method'] == 'POST'
                       and redirect['from_path'] == LOGOUT_PATH
                       and redirect['to_path'] == LOGIN_PATH
                       and from_origin_ok
                       and landed_origin_ok)
        self.step('logout-redirect-303', 'pass' if redirect_ok else 'fail',
                  'status=%s from=%s %s to=%s same_origin=%s landed_same_origin=%s '
                  'requestId=%s hop=%d'
                  % (redirect['status'], redirect['from_method'],
                     redirect['from_path'], redirect['to_path'], from_origin_ok,
                     landed_origin_ok, truncate(redirect['request_id'], 12),
                     redirect['from_hop_index']))
        if not redirect_ok:
            raise FlowAbort('退出跳转不是预期的 POST /logout -> 303 -> /login 同源')

        # 3) 浏览器已真正导航到登录页，且页面可见
        state = self.cdp.evaluate("""(() => {
          const form = document.getElementById('lc-login-form');
          const rect = form ? form.getBoundingClientRect() : null;
          return {
            path: location.pathname,
            auth: document.body.getAttribute('data-authenticated'),
            login_form: !!form,
            login_visible: !!(rect && rect.height > 0 && rect.width > 0),
            logout_form: !!document.querySelector('form.lc-logout-form'),
            next_value: form ? (form.getAttribute('data-next') || '') : ''
          };
        })()""", context_id=nav['context_id']) or {}
        visible = bool(state.get('login_form') and state.get('login_visible')
                       and state.get('auth') == '0' and not state.get('logout_form'))
        self.details['logout'].update({
            'login_path': truncate(state.get('path') or '', 40),
            'login_visible': bool(state.get('login_visible')),
            'next_after_logout': truncate(state.get('next_value') or '', 60),
        })
        self.step('logout-login-page', 'pass' if visible else 'fail',
                  'path=%s auth=%s login_visible=%s logout_form=%s'
                  % (truncate(state.get('path') or '', 40), state.get('auth'),
                     state.get('login_visible'), state.get('logout_form')))
        self.shot('06-logout')

        # 4) 显式匿名：result.uid=false/null 或精确 SessionExpired；其余一律 fail
        session = self.session_via_browser(nav['context_id'])
        kind, reason = classify_session_payload(
            session.get('text'), session.get('transport_error'),
            session.get('content_type'))
        self.details['logout'].update({
            'session_status': session.get('status'),
            'session_content_type': truncate(session.get('content_type') or '', 40),
            'session_classification': kind,
            'session_reason': truncate(reason, 110),
        })
        anon_ok = kind in ('anon', 'expired')
        self.step('logout-session-anon', 'pass' if anon_ok else 'fail',
                  'class=%s reason=%s status=%s'
                  % (kind, truncate(reason, 70), session.get('status')))
        if not anon_ok:
            raise FlowAbort('退出后会话状态不是显式匿名（%s）' % kind)
        if not visible:
            raise FlowAbort('退出后未停在可见登录页')

    def session_via_browser(self, context_id=None):
        """浏览器内会话状态检查：只用于验证状态，不替代任何一个 UI 步骤。"""
        expression = """(async () => {
          try {
            const r = await fetch('/web/session/get_session_info', {
              method: 'POST', credentials: 'same-origin',
              headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({jsonrpc: '2.0', method: 'call', params: {}, id: 1})
            });
            const text = await r.text();
            return {status: r.status,
                    content_type: r.headers.get('Content-Type') || '',
                    text: text.slice(0, 4000)};
          } catch (e) {
            return {status: 0, content_type: '',
                    transport_error: String((e && e.name) || e)};
          }
        })()"""
        value = self.cdp.evaluate(expression, context_id=context_id, await_promise=True)
        return value or {'status': 0, 'transport_error': 'empty evaluate result'}

    # -- 匿名访问 /lab：真实 303 到同源登录 ------------------------------
    def flow_anonymous(self):
        before = self.recorder.seq
        def anon_nav():
            self.prepare_navigation('intentional navigation to /lab while anonymous')
            return self.cdp.call('Page.navigate', url=self.cfg.url + LAB_PATH)

        nav = self.cdp.expect_navigation(
            anon_nav,
            lambda url: url_path(url) == LOGIN_PATH,
            "document.readyState !== 'loading'"
            " && !!document.getElementById('lc-login-form')"
            " && document.body.getAttribute('data-authenticated') === '0'",
            label='anonymous /lab')
        redirect = None
        deadline = time.time() + 12
        while time.time() < deadline:
            candidates = [item for item in self.recorder.redirects
                          if item['seq'] >= before and item['from_path'] == LAB_PATH]
            if candidates:
                redirect = candidates[-1]
                break
            self.cdp.pump(0.05)
            time.sleep(0.1)
        redirect_ok = bool(redirect) and redirect['status'] == 303
        same_origin = (bool(redirect)
                       and (redirect['from_url'] or '').startswith(self.cfg.origin + '/')
                       and redirect['to_path'] == LOGIN_PATH)
        state = self.cdp.evaluate("""(() => {
          const form = document.getElementById('lc-login-form');
          const rect = form ? form.getBoundingClientRect() : null;
          return {
            path: location.pathname,
            login_form: !!form,
            login_visible: !!(rect && rect.height > 0 && rect.width > 0),
            auth: document.body.getAttribute('data-authenticated'),
            next_value: form ? (form.getAttribute('data-next') || '') : ''
          };
        })()""", context_id=nav['context_id']) or {}
        self.details['anonymous'] = {
            'lab_redirect_status': redirect['status'] if redirect else None,
            'lab_redirect_from_path': redirect['from_path'] if redirect else '',
            'lab_redirect_to_path': redirect['to_path'] if redirect else '',
            'lab_redirect_same_origin': same_origin,
            'navigation_redirected': bool(nav.get('redirected')),
            'login_path': truncate(state.get('path') or '', 40),
            'login_form_visible': bool(state.get('login_visible')),
            'login_next': truncate(state.get('next_value') or '', 60),
            'login_loader_id': truncate(nav['loader_id'], 32),
        }
        self.step('anon-lab-303', 'pass' if (redirect_ok and same_origin) else 'fail',
                  'status=%s from=%s to=%s same_origin=%s'
                  % (redirect['status'] if redirect else None,
                     redirect['from_path'] if redirect else '-',
                     redirect['to_path'] if redirect else '-', same_origin))
        self.step('anon-login-page-visible',
                  'pass' if state.get('login_visible') else 'fail',
                  'path=%s visible=%s next=%s'
                  % (truncate(state.get('path') or '', 30),
                     state.get('login_visible'),
                     truncate(state.get('next_value') or '', 40)))
        self.shot('07-anon-lab')
        if not (redirect_ok and same_origin and state.get('login_visible')):
            raise FlowAbort('匿名 /lab 未真实 303 到同源登录页')

    # -- 旧 cookie 失效：Python 独立 HTTP，经同一入口 --------------------
    def flow_old_cookie(self):
        cookies = [item for item in self.cookies if item['name'] == 'session_id']
        if not cookies:
            self.step('anon-old-cookie-invalid', 'fail', '没有可用的旧会话 cookie')
            raise FlowAbort('old session cookie missing')
        if not (self.cfg.ca_file or self.cfg.spki):
            self.step('anon-old-cookie-invalid', 'blocked',
                      '需要 P2_CA_FILE/CA_FILE 或 SPKI（不全局关闭 TLS 校验）')
            raise FlowAbort('no test CA or SPKI for independent HTTP')
        http = IndependentHttp(self.cfg.url, addr=self.cfg.http_addr,
                               ca_file=self.cfg.ca_file, spki_pin=self.cfg.spki,
                               timeout=20)
        problems = []
        session_class = None
        session_reason = ''
        session_status = None
        lab_status = None
        location = ''
        try:
            info = http.request(
                'POST', '/web/session/get_session_info',
                headers={'Content-Type': 'application/json'},
                body='{"jsonrpc":"2.0","method":"call","params":{},"id":1}',
                cookies=cookies)
            session_status = info.status
            session_class, session_reason = classify_session_payload(
                info.text(), None, info.header('content-type'))
            if session_class not in ('anon', 'expired'):
                problems.append('旧 cookie 仍有效或异常（%s）' % session_class)
        except Exception as exc:
            session_reason = 'request failed'
            problems.append('独立会话请求失败: ' + truncate(exc, 100))
        try:
            lab = http.request('GET', LAB_PATH, cookies=cookies)
            lab_status = lab.status
            location = lab.header('location')
            lab_ok = (lab.status == 303
                      and (location.startswith('/login')
                           or location.startswith(self.cfg.origin + '/login')))
            if not lab_ok:
                problems.append('旧 cookie 访问 /lab 非 303 同源登录（%s）' % lab.status)
        except Exception as exc:
            location = ''
            problems.append('独立 /lab 请求失败: ' + truncate(exc, 100))
        tls_info = http.describe_tls()
        self.details['anonymous'].update({
            'independent_tls': tls_info,
            'independent_session_status': session_status,
            'independent_session_classification': session_class,
            'independent_session_reason': truncate(session_reason, 110),
            'independent_lab_status': lab_status,
            'independent_lab_location': truncate(location, 80),
            'independent_used_browser_cookies': True,
            'independent_persisted_cookies': False,
        })
        self.details['tls'] = {
            'browser': 'spki-pin' if self.cfg.spki else 'system-trust',
            'independent': tls_info,
            'global_certificate_errors_ignored': False,
        }
        ok = not problems
        self.step('anon-old-cookie-invalid', 'pass' if ok else 'fail',
                  'tls=%s session=%s lab=%s %s'
                  % (tls_info.get('mode'), session_class, lab_status,
                     '; '.join(problems) or 'ok'))
        if not ok:
            raise FlowAbort('旧会话在独立 HTTP 中仍有效或校验失败')

    # -- 收尾 -------------------------------------------------------------
    def verify_events(self):
        # 没连上浏览器就不存在"浏览器错误"，只能是 blocked，不能算 clean。
        connected = self.cdp is not None
        errors = self.sink.error_entries()
        if connected:
            self.step('console-clean', 'pass' if not errors else 'fail',
                      'errors=%d ignored=%d kinds=%s' % (
                          len(errors), len(self.sink.ignored_entries()),
                          json.dumps(self.sink.summary(), ensure_ascii=False)))
        else:
            self.step('console-clean', 'blocked', '未连接浏览器，无从判定')
        net_fail = self.recorder.failure_failures()
        status_fail = self.recorder.status_failures()
        net_ok = not net_fail and not status_fail
        if connected:
            self.step('network-clean', 'pass' if net_ok else 'fail',
                      'failures=%d status=%d ignored=%d requests=%d'
                      % (len(net_fail), len(status_fail), len(self.recorder.ignored),
                         len(self.recorder.requests)))
        else:
            self.step('network-clean', 'blocked', '未连接浏览器，无从判定')
        leaks = []
        try:
            snapshot = {
                'notes': self.notes,
                'steps': list(self.steps.values()),
                'details': self.details,
                'evidence': self.recorder.evidence,
                'console': self.sink.entries,
                'failures': self.recorder.failures,
                'redirects': self.recorder.redirects,
                'extra_info': self.recorder.extra_info,
            }
            leaks = find_secret_leaks(json.dumps(snapshot, ensure_ascii=False),
                                      self.cfg.secrets())
            cookie_values = [('cookie:' + item['name'], item['value'])
                             for item in self.cookies if item.get('value')]
            leaks += find_secret_leaks(json.dumps(snapshot, ensure_ascii=False),
                                       cookie_values)
        except Exception as exc:
            leaks = ['serialisation-error']
            self.note('redaction snapshot failed: ' + truncate(exc, 140))
        self.step('evidence-redaction', 'pass' if not leaks else 'fail',
                  'leaks=%s cookies_memory_only=1 bodies_withheld=1'
                  % (','.join(sorted(set(leaks))) if leaks else 'none'))

    def cleanup(self):
        """先等自有 Chrome 退出，再按 marker/realpath 校验后删除 profile。"""
        if self.ws is not None:
            try:
                self.ws.close()
            except Exception:
                pass
            self.ws = None
        exited = False
        if self.proc is not None:
            if self.proc.poll() is None:
                try:
                    self.proc.terminate()
                except OSError:
                    pass
            try:
                self.proc.wait(timeout=25)
            except Exception:
                try:
                    self.proc.kill()
                except OSError:
                    pass
                try:
                    self.proc.wait(timeout=15)
                except Exception:
                    pass
            exited = self.proc.poll() is not None
        self.cookies = []                 # 内存中的 cookie 立即丢弃
        if not self.profile_dir:
            self.step('profile-cleanup', 'blocked', '未创建 profile')
            return
        if not exited:
            self.step('profile-cleanup', 'fail',
                      '自有 Chrome 未在超时内退出，保留目录待排查')
            return
        real_out = os.path.realpath(self.cfg.out_dir)
        real_profile = os.path.realpath(self.profile_dir)
        if not is_within(real_out, real_profile):
            self.step('profile-cleanup', 'fail', 'profile realpath 越界，拒绝删除')
            return
        if contains_link_component(self.profile_dir):
            self.step('profile-cleanup', 'fail', 'profile 路径链含链接，拒绝递归删除')
            return
        marker_ok, why = verify_owner_marker(self.profile_dir, self.owner_token)
        if not marker_ok:
            self.step('profile-cleanup', 'fail', 'ownership 校验失败: ' + why)
            return
        try:
            shutil.rmtree(real_profile)
        except OSError as exc:
            self.step('profile-cleanup', 'fail', '删除失败: ' + truncate(exc, 140))
            return
        self.step('profile-cleanup', 'pass' if not os.path.exists(real_profile)
                  else 'fail',
                  'chrome_exited=1 marker_ok=1 removed=%s'
                  % (not os.path.exists(real_profile)))

    # -- 结果 -------------------------------------------------------------
    def ordered_steps(self):
        executed = {item['name'] for item in self.steps.values()}
        out = [self.steps[name] for name in PLANNED_STEPS if name in executed]
        for name in sorted(self.steps):
            if name not in PLANNED_STEPS:
                out.append(self.steps[name])
        return out

    def build_result(self):
        self.recorder.finish()
        steps = self.ordered_steps()
        counts = {'pass': 0, 'fail': 0, 'blocked': 0}
        for item in steps:
            counts[item['status']] = counts.get(item['status'], 0) + 1
        executed = {item['name'] for item in steps}
        unreached = [name for name in PLANNED_STEPS if name not in executed]
        # 未执行到的步骤必须显式记 blocked 才会影响 ok，而不是悄悄消失
        for name in unreached:
            steps.append({'name': name, 'status': 'blocked', 'ok': False,
                          'detail': '未执行（前置步骤失败）'})
            counts['blocked'] += 1
        ok = (counts['fail'] == 0 and counts['blocked'] == 0
              and not self.abort_reason)
        return {
            'schema': 'lc-elc-p2-browser-flow/2',
            'ok': ok,
            'exit_code': 0 if ok else (2 if self.hard_env_failure else 1),
            'abort_reason': self.abort_reason,
            'counts': {
                'steps': len(steps),
                'pass': counts['pass'],
                'fail': counts['fail'],
                'blocked': counts['blocked'],
                'planned_total': len(PLANNED_STEPS),
                'unreached': len(unreached),
            },
            'unreached_steps': unreached,
            'steps': steps,
            'search': self.details.get('search', {}),
            'detail': self.details.get('detail', {}),
            'logout': self.details.get('logout', {}),
            'anonymous': self.details.get('anonymous', {}),
            'tls': self.details.get('tls', {
                'browser': 'spki-pin' if self.cfg.spki else 'system-trust',
                'independent': {},
                'global_certificate_errors_ignored': False,
            }),
            'console': {
                'summary': self.sink.summary(),
                'errors': self.sink.error_entries(),
                'ignored': self.sink.ignored_entries(),
            },
            'network': {
                'counts': self.recorder.counts(),
                'evidence': self.recorder.evidence,
                'redirects': [{
                    'request_id': item['request_id'],
                    'from_path': item['from_path'],
                    'from_method': item['from_method'],
                    'status': item['status'],
                    'to_path': item['to_path'],
                    'to_method': item['to_method'],
                    'from_hop_index': item['from_hop_index'],
                    'to_hop_index': item['to_hop_index'],
                } for item in self.recorder.redirects],
                'failures': self.recorder.failures,
                'ignored_failures': self.recorder.ignored,
                'extra_info': self.recorder.extra_info[-40:],
                'csp': [{
                    'path': self.recorder.first_csp()['path'],
                    'source': self.recorder.first_csp()['source'],
                    'directives': sorted(self.recorder.first_csp()['directives'].keys()),
                    'script_src': self.recorder.first_csp()['directives'].get('script-src', []),
                    'connect_src': self.recorder.first_csp()['directives'].get('connect-src', []),
                    'img_src': self.recorder.first_csp()['directives'].get('img-src', []),
                    'style_src': self.recorder.first_csp()['directives'].get('style-src', []),
                    'form_action': self.recorder.first_csp()['directives'].get(
                        'form-action', []),
                    'frame_ancestors': self.recorder.first_csp()['directives'].get(
                        'frame-ancestors', []),
                    'documents_observed': len(self.recorder.csp),
                }],
            },
            'screenshots': self.screenshots,
            'intentional_aborts': self.details.get('intentional_aborts', []),
            'notes': self.notes,
        }


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def fallback_result(message, planned=None):
    names = list(planned or PLANNED_STEPS)
    return {
        'schema': 'lc-elc-p2-browser-flow/2',
        'ok': False,
        'exit_code': 2,
        'abort_reason': truncate(message, 240),
        'counts': {'steps': len(names), 'pass': 0, 'fail': 0, 'blocked': len(names),
                   'planned_total': len(names), 'unreached': len(names)},
        'unreached_steps': names,
        'steps': [{'name': name, 'status': 'blocked', 'ok': False,
                   'detail': 'environment unavailable'} for name in names],
        'screenshots': [],
        'notes': [truncate(message, 240)],
    }


def write_result(out_dir, payload):
    try:
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, 'browser.json')
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        return path
    except Exception as exc:
        sys.stderr.write('browser.json write failed: %s\n' % truncate(exc, 140))
        return ''


def main():
    out_dir = os.environ.get('OUT_DIR') or os.getcwd()
    try:
        cfg = Config()
        out_dir = cfg.out_dir
        flow = BrowserFlow(cfg)
        flow.run()
        payload = flow.build_result()
    except KeyError as exc:
        payload = fallback_result('missing env: ' + str(exc))
    except Exception as exc:
        payload = fallback_result('%s: %s' % (type(exc).__name__, exc))
    write_result(out_dir, payload)
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + '\n')
    sys.stdout.flush()
    return int(payload.get('exit_code') or 0)


if __name__ == '__main__':
    sys.exit(main())
