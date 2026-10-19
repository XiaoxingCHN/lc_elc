# -*- coding: utf-8 -*-
"""安全受控的来源资产缓存（图片 / 数据手册），**真实文件缓存**。

root 复核后修正的要点
--------------------
1. **先静态校验、再查本地缓存、miss 才做 DNS 校验。**
   原实现先做 DNS，导致无外网 DNS 时**已缓存的文件也打不开**；现在缓存命中不需要 DNS。
2. **连接固定到校验过的 IP**（``socket.create_connection((ip, 443))`` +
   ``ssl.wrap_socket(server_hostname=host)`` 做 SNI 与证书校验），
   因此校验与连接之间**不存在 TOCTOU**。**不宣称**"防 DNS rebinding"——
   这里做到的是"连接的就是刚校验过的那个 IP"。
3. **禁止 SVG**：``image/svg+xml`` 同源加载可执行脚本，直接拒绝；
   其余响应强制 ``nosniff`` + CSP sandbox + inline 处置。
4. **已入库/已查看的器件会主动预热缓存**（``prefetch_stocked_assets``），
   不是只靠用户点开 ``<img>`` 才缓存。离线时直接命中磁盘缓存。
5. 只读缓存，不写任何业务数据；不做任意 URL 代理。

配置（ir.config_parameter）
---------------------------
``lab_catalog.asset_cache_enabled``  默认 1
``lab_catalog.asset_cache_max_mb``   默认 2048
``lab_catalog.asset_max_bytes``      默认 8388608
``lab_catalog.asset_connect_timeout``默认 6
``lab_catalog.asset_read_timeout``   默认 10
"""
import hashlib
import ipaddress
import logging
import os
import socket
import ssl
from urllib.parse import urlparse

from odoo import http, tools
from odoo.http import request

from .envelope import FORBIDDEN, NOT_FOUND, VALIDATION_ERROR, LabApiError, api_route

_logger = logging.getLogger(__name__)

# 立创静态资源域（图片 / 附件）。新增域必须显式加进来，不做通配。
ALLOWED_HOSTS = frozenset({
    'alimg.szlcsc.com',
    'atta.szlcsc.com',
    'www.szlcsc.com',
    'item.szlcsc.com',
})
# SVG 被明确禁止（同源可执行脚本）
ALLOWED_CONTENT_EXACT = ('application/pdf', 'image/jpeg', 'image/png', 'image/gif',
                         'image/webp', 'image/bmp')
EXT_BY_CTYPE = {
    'application/pdf': 'pdf', 'image/jpeg': 'jpg', 'image/png': 'png',
    'image/gif': 'gif', 'image/webp': 'webp', 'image/bmp': 'bmp',
}
CTYPE_BY_EXT = {v: k for k, v in EXT_BY_CTYPE.items()}

DEFAULT_MAX_MB = 2048
DEFAULT_MAX_BYTES = 8 * 1024 * 1024
DEFAULT_CONNECT_TIMEOUT = 6
DEFAULT_READ_TIMEOUT = 10


def _param(key, default):
    return request.env['ir.config_parameter'].sudo().get_param(key, default)


def _cache_root():
    data_dir = tools.config.get('data_dir') or os.path.expanduser('~/.local/share/Odoo')
    path = os.path.join(data_dir, 'lab_catalog_asset_cache')
    os.makedirs(path, exist_ok=True)
    return path


# ------------------------------------------------------------------ validation
def validate_url_static(url):
    """**不做 DNS** 的静态校验：协议、白名单域、非 IP 字面量、长度。

    缓存命中路径只需要这一步，因此离线（无 DNS）也能打开已缓存资产。
    返回 (host, path)。
    """
    if not url or len(url) > 2048:
        raise LabApiError(VALIDATION_ERROR, '资源地址无效。', {'url': 'invalid'})
    parsed = urlparse(url)
    if parsed.scheme != 'https':
        raise LabApiError(FORBIDDEN, '只允许 https 资源。', {'url': 'scheme_not_allowed'})
    host = (parsed.hostname or '').lower()
    if host not in ALLOWED_HOSTS:
        raise LabApiError(FORBIDDEN, '该来源不在允许列表内（%s），已拒绝代理。' % (host or '空'),
                          {'url': 'host_not_allowed'})
    try:
        ipaddress.ip_address(host)
        raise LabApiError(FORBIDDEN, '不允许直接使用 IP 访问。', {'url': 'ip_not_allowed'})
    except ValueError:
        pass
    path = parsed.path or '/'
    if parsed.query:
        path += '?' + parsed.query
    if any(c in path for c in ('\r', '\n', ' ')):
        raise LabApiError(VALIDATION_ERROR, '资源路径包含非法字符。', {'url': 'bad_path'})
    return host, path


def resolve_safe_ip(host):
    """DNS 解析并确认不是内网/保留地址。**只在缓存 miss 时调用。**"""
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise LabApiError(NOT_FOUND, '无法解析资源域名（可能离线）。', {'url': 'dns_failed'})
    picked = None
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_multicast or ip.is_reserved or ip.is_unspecified):
            raise LabApiError(FORBIDDEN, '资源域解析到内网地址，已拒绝。', {'url': 'private_ip'})
        if picked is None:
            picked = addr
    if picked is None:
        raise LabApiError(NOT_FOUND, '资源域没有可用地址。', {'url': 'no_address'})
    return picked


# ------------------------------------------------------------------ pinned fetch
def fetch_pinned(host, ip, path, connect_timeout, read_timeout, max_bytes):
    """直连**已校验的 IP**，用 SNI/证书针对域名校验。

    没有二次解析，所以不存在"校验一个 IP、连另一个 IP"的时间窗。
    不跟随重定向（本函数根本不处理 3xx 的 Location）。
    返回 (status, headers_dict, body_bytes)。
    """
    ctx = ssl.create_default_context()
    sock = socket.create_connection((ip, 443), timeout=connect_timeout)
    try:
        tls = ctx.wrap_socket(sock, server_hostname=host)
        try:
            tls.settimeout(read_timeout)
            req = ('GET %s HTTP/1.1\r\nHost: %s\r\n'
                   'User-Agent: lc-elc-lab-catalog/1.0\r\n'
                   'Accept: image/*,application/pdf\r\n'
                   'Accept-Encoding: identity\r\n'
                   'Connection: close\r\n\r\n') % (path, host)
            tls.sendall(req.encode('ascii', 'ignore'))

            buf = bytearray()
            while b'\r\n\r\n' not in buf:
                chunk = tls.recv(4096)
                if not chunk:
                    break
                buf.extend(chunk)
                if len(buf) > 64 * 1024:
                    raise ValueError('response headers too large')
            head, _, rest = bytes(buf).partition(b'\r\n\r\n')
            lines = head.split(b'\r\n')
            status = int(lines[0].split(b' ')[1])
            headers = {}
            for line in lines[1:]:
                if b':' in line:
                    k, v = line.split(b':', 1)
                    headers[k.decode('latin-1').strip().lower()] = v.decode('latin-1').strip()

            body = bytearray(rest)
            chunked = headers.get('transfer-encoding', '').lower() == 'chunked'
            if chunked:
                raw = bytearray(rest)
                decoded = bytearray()
                while True:
                    while b'\r\n' not in raw:
                        chunk = tls.recv(65536)
                        if not chunk:
                            break
                        raw.extend(chunk)
                    if b'\r\n' not in raw:
                        break
                    size_line, _, raw = bytes(raw).partition(b'\r\n')
                    try:
                        size = int(size_line.split(b';')[0], 16)
                    except ValueError:
                        break
                    if size == 0:
                        break
                    while len(raw) < size + 2:
                        chunk = tls.recv(65536)
                        if not chunk:
                            break
                        raw.extend(chunk)
                    decoded.extend(raw[:size])
                    raw = bytearray(raw[size + 2:])
                    if len(decoded) > max_bytes:
                        raise ValueError('asset exceeds size limit')
                body = decoded
            else:
                while True:
                    if len(body) > max_bytes:
                        raise ValueError('asset exceeds size limit')
                    chunk = tls.recv(65536)
                    if not chunk:
                        break
                    body.extend(chunk)
            return status, headers, bytes(body)
        finally:
            try:
                tls.close()
            except OSError:
                pass
    finally:
        try:
            sock.close()
        except OSError:
            pass


# ------------------------------------------------------------------ eviction
def evict(root, max_bytes):
    """按 mtime 从旧到新淘汰，直到低于上限。"""
    try:
        entries, total = [], 0
        for name in os.listdir(root):
            full = os.path.join(root, name)
            if not os.path.isfile(full):
                continue
            try:
                st = os.stat(full)
            except OSError:
                continue
            entries.append((st.st_mtime, st.st_size, full))
            total += st.st_size
        if total <= max_bytes:
            return
        entries.sort()
        for _mtime, size, full in entries:
            try:
                os.unlink(full)
            except OSError:
                continue
            total -= size
            if total <= max_bytes:
                break
    except OSError:
        pass


def cache_lookup(root, url):
    """命中则返回 (bytes, ctype, path)，否则 None。**不需要 DNS。**"""
    key = hashlib.sha256(url.encode('utf-8')).hexdigest()
    try:
        names = os.listdir(root)
    except OSError:
        return None
    for name in names:
        if name.startswith(key + '.'):
            full = os.path.join(root, name)
            try:
                with open(full, 'rb') as fh:
                    payload = fh.read()
            except OSError:
                return None
            os.utime(full, None)
            ext = name.rsplit('.', 1)[-1].lower()
            return payload, CTYPE_BY_EXT.get(ext, 'application/octet-stream'), full
    return None


def cache_store(root, url, payload, ctype, cache_max):
    key = hashlib.sha256(url.encode('utf-8')).hexdigest()
    ext = EXT_BY_CTYPE.get(ctype, 'bin')
    full = os.path.join(root, '%s.%s' % (key, ext))
    try:
        with open(full, 'wb') as fh:
            fh.write(payload)
        evict(root, cache_max)
    except OSError as exc:
        _logger.warning('lab_catalog asset cache write failed: %s', exc)
    return full


def ensure_cached(url):
    """预热单个 URL（供"已入库/已查看"主动缓存使用）。返回 True 表示本地已有。"""
    if not url:
        return False
    root = _cache_root()
    if cache_lookup(root, url):
        return True
    max_bytes = int(_param('lab_catalog.asset_max_bytes', DEFAULT_MAX_BYTES))
    cache_max = int(_param('lab_catalog.asset_cache_max_mb', DEFAULT_MAX_MB)) * 1024 * 1024
    try:
        host, path = validate_url_static(url)
        ip = resolve_safe_ip(host)
        status, headers, body = fetch_pinned(
            host, ip, path,
            int(_param('lab_catalog.asset_connect_timeout', DEFAULT_CONNECT_TIMEOUT)),
            int(_param('lab_catalog.asset_read_timeout', DEFAULT_READ_TIMEOUT)),
            max_bytes)
    except Exception as exc:
        _logger.info('lab_catalog prefetch failed for %s: %s', url, exc)
        return False
    if status != 200:
        return False
    ctype = (headers.get('content-type') or '').split(';')[0].strip().lower()
    if ctype not in ALLOWED_CONTENT_EXACT:
        return False
    cache_store(root, url, body, ctype, cache_max)
    return True


# ------------------------------------------------------------------ controller
class LabAssetCacheController(http.Controller):

    @http.route('/lab/api/asset', type='http', auth='user', methods=['GET'], csrf=False)
    def asset(self, url=None, **kwargs):
        """按白名单取回资源，命中磁盘缓存时**无需 DNS、可离线**。"""
        if _param('lab_catalog.asset_cache_enabled', '1') != '1':
            return request.not_found()

        # 1) 静态校验（无 DNS）
        try:
            host, path = validate_url_static(url)
        except LabApiError as exc:
            _logger.warning('lab_catalog asset rejected: %s (%s)', exc.message, url)
            return request.make_response(exc.message, status=403)

        # 2) 先查本地磁盘缓存——离线也必须能打开已缓存资产
        root = _cache_root()
        hit = cache_lookup(root, url)
        if hit:
            payload, ctype, _full = hit
            return self._respond(payload, ctype, hit=True)

        # 3) miss 才做 DNS 校验并回源
        try:
            ip = resolve_safe_ip(host)
        except LabApiError as exc:
            return request.make_response(exc.message,
                                         status=404 if exc.code == NOT_FOUND else 403)

        max_bytes = int(_param('lab_catalog.asset_max_bytes', DEFAULT_MAX_BYTES))
        cache_max = int(_param('lab_catalog.asset_cache_max_mb', DEFAULT_MAX_MB)) * 1024 * 1024
        try:
            status, headers, body = fetch_pinned(
                host, ip, path,
                int(_param('lab_catalog.asset_connect_timeout', DEFAULT_CONNECT_TIMEOUT)),
                int(_param('lab_catalog.asset_read_timeout', DEFAULT_READ_TIMEOUT)),
                max_bytes)
        except ValueError as exc:
            return request.make_response('资源超限：%s' % exc, status=413)
        except (OSError, ssl.SSLError) as exc:
            _logger.info('lab_catalog asset fetch failed: %s', exc)
            return request.make_response('资源暂时不可用。', status=504)

        if 300 <= status < 400:
            return request.make_response('资源被重定向，出于安全考虑已拒绝跟随。', status=403)
        if status != 200:
            return request.make_response('资源返回 %s。' % status, status=502)

        ctype = (headers.get('content-type') or '').split(';')[0].strip().lower()
        if ctype not in ALLOWED_CONTENT_EXACT:
            # SVG 等一律拒绝
            return request.make_response('资源类型 %s 不被允许。' % ctype, status=415)

        cache_store(root, url, body, ctype, cache_max)
        return self._respond(body, ctype, hit=False)

    def _respond(self, payload, ctype, hit):
        headers = [
            ('Content-Type', ctype),
            ('Content-Length', str(len(payload))),
            # 防御：禁止 MIME 嗅探，CSP 沙箱化，禁止被当成脚本/HTML 执行
            ('X-Content-Type-Options', 'nosniff'),
            ('Content-Security-Policy', "sandbox; default-src 'none'; img-src 'self'"),
            ('Content-Disposition', 'inline; filename="asset.%s"' % EXT_BY_CTYPE.get(ctype, 'bin')),
            ('Cache-Control', 'private, max-age=2592000'),
            ('X-Lab-Asset-Cache', 'hit' if hit else 'miss'),
        ]
        return request.make_response(payload, headers=headers)
