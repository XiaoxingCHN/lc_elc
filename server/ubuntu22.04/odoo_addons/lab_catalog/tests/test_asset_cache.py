# -*- coding: utf-8 -*-
"""lab_catalog 资产取数的纯逻辑回归测试（无 Odoo 运行时、无真实网络）。

背景（2026-10-27 真实故障）
--------------------------
本机 DNS 对 alimg.szlcsc.com 先返回不可达的 IPv6，旧实现只取**首个**已校验
地址且只试一次，于是 /lab/api/asset 取数一直失败；同一 URL 用 curl（自带多
地址回退）返回 200。修复后：

* resolve_safe_ips 返回**全部**已校验地址，IPv4 优先、去重；
  任一候选是内网/环回/链路本地/保留/组播/未指定 → 整体拒绝（语义不收窄）。
* fetch_first_ok 按序尝试，**只**在 OSError/ssl.SSLError 时回退；拿到真实
  HTTP 响应（3xx/4xx/5xx）立即返回，ValueError（超限）直接上抛。
* 连接、TLS 握手、每次 recv 都受总预算约束，慢流不能无限拖延。

因此这里用标准库 unittest.mock + 假时钟（无 sleep、无真实网络）验证行为，
不用"网络失败即跳过"来伪造通过。
"""
import importlib.util
import os
import shutil
import socket
import sys
import tempfile
import types
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_MODULE_DIR = os.path.dirname(_HERE)
_SRC = os.path.join(_MODULE_DIR, 'controllers', 'asset_cache.py')
_URL = ('https://alimg.szlcsc.com/upload/public/home/page/advertising/20250103/'
        'E1C8C8F02CB0EB1BF47EFBE03E4ACB1E.png')
_HOST = 'alimg.szlcsc.com'


def _load_asset_cache():
    """拿到被测模块：真实 Odoo 下正常 import，否则用最小 stub（用完立即撤销）。"""
    if importlib.util.find_spec('odoo') is not None:
        # 真实 Odoo 环境：正常 import。失败就让测试报错，绝不悄悄替换成 stub
        # （在活着的 Odoo 进程里临时替身 sys.modules['odoo'] 才是真风险）。
        from odoo.addons.lab_catalog.controllers import asset_cache as real
        return real
    return _load_with_stub()


def _load_with_stub():
    """用最小 Odoo stub 加载模块，加载完立刻撤掉 stub，避免污染其他 tests。"""
    created = {}
    stubs = {}

    odoo = types.ModuleType('odoo')
    odoo_http = types.ModuleType('odoo.http')
    odoo_exc = types.ModuleType('odoo.exceptions')

    class _Controller(object):
        pass

    class _Request(object):
        pass

    odoo_http.Controller = _Controller
    odoo_http.request = _Request()

    def _route(*_a, **_k):
        def _deco(fn):
            return fn
        return _deco

    odoo_http.route = _route
    odoo.http = odoo_http
    odoo.tools = types.SimpleNamespace(config={})

    class _OdooError(Exception):
        pass

    odoo_exc.AccessError = type('AccessError', (_OdooError,), {})
    odoo_exc.UserError = type('UserError', (_OdooError,), {})
    odoo_exc.ValidationError = type('ValidationError', (_OdooError,), {})
    odoo.exceptions = odoo_exc

    pkg = types.ModuleType('lab_catalog')
    pkg.__path__ = [_MODULE_DIR]
    ctl = types.ModuleType('lab_catalog.controllers')
    ctl.__path__ = [os.path.join(_MODULE_DIR, 'controllers')]

    stubs.update({
        'odoo': odoo,
        'odoo.http': odoo_http,
        'odoo.exceptions': odoo_exc,
        'lab_catalog': pkg,
        'lab_catalog.controllers': ctl,
    })
    for name, mod in stubs.items():
        created[name] = sys.modules.get(name)
        sys.modules[name] = mod

    try:
        spec = importlib.util.spec_from_file_location(
            'lab_catalog.controllers.envelope',
            os.path.join(_MODULE_DIR, 'controllers', 'envelope.py'))
        env_mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = env_mod
        spec.loader.exec_module(env_mod)

        spec = importlib.util.spec_from_file_location(
            'lab_catalog.controllers.asset_cache', _SRC)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        for name in ('lab_catalog.controllers.asset_cache',
                     'lab_catalog.controllers.envelope'):
            sys.modules.pop(name, None)
        for name, old in created.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old


asset_cache = _load_asset_cache()


# ------------------------------------------------------------------ 假网络
class FakeClock(object):
    """可控的 monotonic 时钟；不 sleep。"""

    def __init__(self, start=1000.0):
        self.now = float(start)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += float(seconds)


class FakeTLS(object):
    def __init__(self, ip, steps, clock=None, advance=0.0):
        self.ip = ip
        self.steps = list(steps)
        self.clock = clock
        self.advance = advance
        self.timeouts = []
        self.sent = b''
        self.closed = False
        self.recv_calls = 0

    def settimeout(self, value):
        self.timeouts.append(value)

    def sendall(self, data):
        self.sent += data

    def recv(self, size):
        self.recv_calls += 1
        if self.clock is not None and self.advance:
            self.clock.advance(self.advance)
        if not self.steps:
            return b''
        item = self.steps.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def close(self):
        self.closed = True


class FakeSocket(object):
    def __init__(self, ip):
        self.ip = ip
        self.closed = False
        self.timeouts = []

    def settimeout(self, value):
        self.timeouts.append(value)

    def close(self):
        self.closed = True


class FakeContext(object):
    def __init__(self, network):
        self.network = network
        self.wrap_kwargs = []

    def wrap_socket(self, sock, **kwargs):
        self.wrap_kwargs.append(dict(kwargs))
        return self.network.make_tls(sock.ip)


class FakeNetwork(object):
    """按 IP 编排"连接-响应"脚本，并记录实际连接过的地址。"""

    def __init__(self, clock=None):
        self.clock = clock or FakeClock()
        self.scripts = {}
        self.conns = []
        self.tls = []
        self.ctx = FakeContext(self)

    def script(self, ip, steps=None, connect_error=None, advance=0.0):
        self.scripts[ip] = {
            'steps': steps if steps is not None else [],
            'connect_error': connect_error,
            'advance': advance,
        }

    def create_connection(self, address, timeout=None):
        ip = address[0]
        self.conns.append((ip, address[1], timeout))
        entry = self.scripts.get(ip)
        if entry is None:
            raise OSError('no route to %s' % ip)
        if entry['connect_error'] is not None:
            if self.clock is not None and entry['advance']:
                self.clock.advance(entry['advance'])
            raise entry['connect_error']
        return FakeSocket(ip)

    def make_tls(self, ip):
        entry = self.scripts.get(ip) or {'steps': [], 'advance': 0.0}
        tls = FakeTLS(ip, entry['steps'], clock=self.clock, advance=entry['advance'])
        self.tls.append(tls)
        return tls

    def create_default_context(self, *args, **kwargs):
        self.ctx_create_args = (args, kwargs)
        return self.ctx


def _raw_http(status, body=b'', *extra_headers):
    head = ['HTTP/1.1 %s' % status, 'Content-Length: %d' % len(body)]
    for name, value in extra_headers:
        head.append('%s: %s' % (name, value))
    payload = ('\r\n'.join(head) + '\r\n\r\n').encode('latin-1')
    return [payload + body, b'']


def _png_steps(body=b'\x89PNG\r\n\x1a\n' + b'x' * 64):
    return _raw_http('200 OK', body, ('Content-Type', 'image/png'))


def _patch_network(network):
    """在模块的 socket/ssl 边界上注入假网络（不改被测代码）。"""
    return (
        mock.patch.object(asset_cache.socket, 'create_connection',
                          side_effect=network.create_connection),
        mock.patch.object(asset_cache.ssl, 'create_default_context',
                          side_effect=network.create_default_context),
    )


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.net = FakeNetwork(self.clock)
        self.conn_patch, self.ctx_patch = _patch_network(self.net)
        self.conn_patch.start()
        self.ctx_patch.start()
        self.clock_patch = mock.patch.object(asset_cache, '_clock', self.clock)
        self.clock_patch.start()

    def tearDown(self):
        self.clock_patch.stop()
        self.ctx_patch.stop()
        self.conn_patch.stop()

    def fetch(self, ips, max_bytes=8 * 1024 * 1024, connect_timeout=6,
              read_timeout=10, connect_cap=None):
        kwargs = {}
        if connect_cap is not None:
            kwargs['connect_cap'] = connect_cap
        return asset_cache.fetch_first_ok(
            _HOST, list(ips), '/a.png', connect_timeout, read_timeout,
            max_bytes, **kwargs)


# ------------------------------------------------------------------ 候选地址
class TestResolveSafeIps(BaseCase):
    def _infos(self, addrs):
        out = []
        for addr in addrs:
            fam = socket.AF_INET6 if ':' in addr else socket.AF_INET
            out.append((fam, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', (addr, 443, 0, 0)))
        return out

    def test_ipv4_first_and_deduplicated(self):
        infos = self._infos(['2606:4700::1', '93.184.216.34', '2606:4700::2',
                             '93.184.216.34', '2606:4700::1'])
        with mock.patch.object(asset_cache.socket, 'getaddrinfo', return_value=infos):
            ips = asset_cache.resolve_safe_ips(_HOST)
        self.assertEqual(ips, ['93.184.216.34', '2606:4700::1', '2606:4700::2'])

    def test_private_candidate_anywhere_rejects_whole_resolution(self):
        public = ['93.184.216.34', '2606:4700::1']
        private = ['10.0.0.5', '127.0.0.1', '169.254.1.1', '::1', 'fe80::1',
                   '0.0.0.0', '224.0.0.1', '::ffff:10.0.0.5', '::ffff:127.0.0.1']
        for bad in private:
            for position in range(len(public) + 1):
                addrs = list(public)
                addrs.insert(position, bad)
                with self.subTest(bad=bad, position=position):
                    with mock.patch.object(asset_cache.socket, 'getaddrinfo',
                                           return_value=self._infos(addrs)):
                        with self.assertRaises(asset_cache.LabApiError) as ctx:
                            asset_cache.resolve_safe_ips(_HOST)
                    self.assertEqual(ctx.exception.code, asset_cache.FORBIDDEN)
                    self.assertEqual(ctx.exception.fields, {'url': 'private_ip'})
                    # 关键：混合私网时不允许"改挑公网地址"，一个连接都不许建
                    self.assertEqual(self.net.conns, [])

    def test_dns_failure_and_empty_answer(self):
        with mock.patch.object(asset_cache.socket, 'getaddrinfo',
                               side_effect=socket.gaierror('no dns')):
            with self.assertRaises(asset_cache.LabApiError) as ctx:
                asset_cache.resolve_safe_ips(_HOST)
        self.assertEqual(ctx.exception.code, asset_cache.NOT_FOUND)
        with mock.patch.object(asset_cache.socket, 'getaddrinfo', return_value=[]):
            with self.assertRaises(asset_cache.LabApiError) as ctx:
                asset_cache.resolve_safe_ips(_HOST)
        self.assertEqual(ctx.exception.fields, {'url': 'no_address'})

    def test_resolve_safe_ip_compat_returns_first(self):
        infos = self._infos(['2606:4700::1', '93.184.216.34'])
        with mock.patch.object(asset_cache.socket, 'getaddrinfo', return_value=infos):
            self.assertEqual(asset_cache.resolve_safe_ip(_HOST), '93.184.216.34')


# ------------------------------------------------------------------ 回退取数
class TestFetchFirstOk(BaseCase):
    def test_ipv6_blackhole_falls_back_to_ipv4(self):
        # 真实故障形态：首个候选 IPv6 连接超时（黑洞），IPv4 才能连通
        self.net.script('2606:4700::1', connect_error=socket.timeout('timed out'))
        self.net.script('93.184.216.35', steps=_png_steps())
        status, headers, body = self.fetch(['2606:4700::1', '93.184.216.35'])
        self.assertEqual(status, 200)
        self.assertEqual(headers.get('content-type'), 'image/png')
        self.assertTrue(body.startswith(b'\x89PNG'))
        self.assertEqual([c[0] for c in self.net.conns],
                         ['2606:4700::1', '93.184.216.35'])

    def test_mixed_v6_v4_v6_steps_then_success(self):
        # 混合 v6/v4/v6 候选：前两个网络层失败，第三个成功
        self.net.script('2001:db8::5', connect_error=socket.timeout('timed out'))
        self.net.script('93.184.216.34', connect_error=ConnectionResetError('reset'))
        self.net.script('2001:db8::6', steps=_png_steps())
        status, _headers, _body = self.fetch(['2001:db8::5', '93.184.216.34', '2001:db8::6'])
        self.assertEqual(status, 200)
        self.assertEqual([c[0] for c in self.net.conns],
                         ['2001:db8::5', '93.184.216.34', '2001:db8::6'])

    def test_no_second_dns_lookup_and_pinned_ip(self):
        # 含回退时也绝不二次解析 host；连接目标是已校验的那个 IP
        self.net.script('2001:db8::5', connect_error=socket.timeout('timed out'))
        self.net.script('93.184.216.34', steps=_png_steps())
        with mock.patch.object(asset_cache.socket, 'getaddrinfo',
                               side_effect=AssertionError('fetch must not re-resolve DNS')):
            self.fetch(['2001:db8::5', '93.184.216.34'])
        self.assertEqual([(c[0], c[1]) for c in self.net.conns],
                         [('2001:db8::5', 443), ('93.184.216.34', 443)])

    def test_tls_uses_default_verification_and_original_sni(self):
        self.net.script('93.184.216.34', steps=_png_steps())
        self.fetch(['93.184.216.34'])
        args, kwargs = self.net.ctx_create_args
        self.assertEqual(args, ())
        self.assertEqual(kwargs, {})          # 默认上下文：验证开启，未自定义 CA
        self.assertEqual(self.net.ctx.wrap_kwargs,
                         [{'server_hostname': _HOST}])  # SNI/证书仍用原域名

    def test_http_error_does_not_fall_back(self):
        cases = [
            ('302 Found', [('Location', 'https://evil.example/x')], 302),
            ('404 Not Found', [], 404),
            ('503 Service Unavailable', [], 503),
        ]
        for status_line, extra, expected in cases:
            with self.subTest(status=expected):
                self.net.conns[:] = []
                self.net.tls[:] = []
                self.net.script('2001:db8::5', steps=_raw_http(status_line, b'nope', *extra))
                self.net.script('93.184.216.34', steps=_png_steps())
                code, _headers, _body = self.fetch(['2001:db8::5', '93.184.216.34'])
                self.assertEqual(code, expected)
                # 真实响应已拿到 → 不换地址（否则会掩盖原状态，3xx 还会被"洗白"）
                self.assertEqual([c[0] for c in self.net.conns], ['2001:db8::5'])

    def test_oversize_valueerror_propagates_without_fallback(self):
        body = b'x' * 256
        self.net.script('2001:db8::5', steps=_raw_http('200 OK', body,
                                                       ('Content-Type', 'image/png')))
        self.net.script('93.184.216.34', steps=_png_steps())
        with self.assertRaises(ValueError):
            self.fetch(['2001:db8::5', '93.184.216.34'], max_bytes=128)
        self.assertEqual([c[0] for c in self.net.conns], ['2001:db8::5'])

    def test_all_candidates_failing_stops_and_raises(self):
        self.net.script('2001:db8::5', connect_error=socket.timeout('timed out'))
        self.net.script('2001:db8::6', connect_error=ConnectionRefusedError('refused'))
        ips = ['2001:db8::5', '2001:db8::6']
        with self.assertRaises(OSError):
            self.fetch(ips)
        self.assertEqual(len(self.net.conns), len(ips))

    def test_total_budget_limits_attempts(self):
        # 每次连接吃掉 10 秒，总预算 20 秒 → 最多 2 次尝试就停
        for ip in ('2001:db8::1', '2001:db8::2', '2001:db8::3', '2001:db8::4'):
            self.net.script(ip, connect_error=socket.timeout('timed out'), advance=10.0)
        with self.assertRaises(socket.timeout):
            self.fetch(['2001:db8::1', '2001:db8::2', '2001:db8::3', '2001:db8::4'])
        self.assertEqual(len(self.net.conns), 2)
        self.assertLessEqual(self.clock.now, 1000.0 + 20.0 + 10.0)

    def test_connect_timeout_is_capped_per_attempt(self):
        self.net.script('2001:db8::1', connect_error=socket.timeout('timed out'))
        self.net.script('93.184.216.34', steps=_png_steps())
        self.fetch(['2001:db8::1', '93.184.216.34'], connect_timeout=30)
        self.assertLessEqual(self.net.conns[0][2], asset_cache.ATTEMPT_CONNECT_CAP)
        self.assertLessEqual(self.net.conns[0][2], 4)

    def test_slow_stream_recv_bounded_by_budget(self):
        body = b'x' * 64
        steps = _raw_http('200 OK', body, ('Content-Type', 'image/png'))[:1]
        steps = [steps[0], body, body, body, body, body, b'']
        self.net.script('93.184.216.34', steps=steps, advance=8.0)
        with self.assertRaises(socket.timeout):
            self.fetch(['93.184.216.34'], read_timeout=30)
        tls = self.net.tls[-1]
        # 每次 recv 都在总预算内设超时，且随剩余预算收紧
        self.assertTrue(tls.timeouts)
        self.assertLess(tls.timeouts[-1], 30)
        self.assertLessEqual(tls.recv_calls, 5)

    def test_empty_candidate_list_is_rejected(self):
        with self.assertRaises(asset_cache.LabApiError) as ctx:
            self.fetch([])
        self.assertEqual(ctx.exception.fields, {'url': 'no_address'})
        self.assertEqual(self.net.conns, [])


# ------------------------------------------------------------------ 控制器映射
class FakeResponse(object):
    def __init__(self, body, status=200, headers=None):
        self.body = body
        self.status = status
        self.headers = dict(headers or {})


class FakeParam(object):
    def __init__(self, params):
        self.params = params

    def sudo(self):
        return self

    def get_param(self, key, default):
        return self.params.get(key, default)


class FakeRequest(object):
    def __init__(self, params):
        self.env = {'ir.config_parameter': FakeParam(params)}

    def make_response(self, body, status=200, headers=None):
        return FakeResponse(body, status, headers)

    def not_found(self):
        return FakeResponse('not found', 404)


class TestControllerMapping(BaseCase):
    def setUp(self):
        super(TestControllerMapping, self).setUp()
        self.root = tempfile.mkdtemp(prefix='labcat-asset-test-')
        self.request = FakeRequest({})
        self.patches = [
            mock.patch.object(asset_cache, 'request', self.request),
            mock.patch.object(asset_cache, '_cache_root', lambda: self.root),
            mock.patch.object(asset_cache, '_param',
                              lambda key, default: self.request.env[
                                  'ir.config_parameter'].get_param(key, default)),
        ]
        for patcher in self.patches:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.patches):
            patcher.stop()
        shutil.rmtree(self.root, ignore_errors=True)
        super(TestControllerMapping, self).tearDown()

    def _serve(self, ips, steps_by_ip):
        for ip, steps in steps_by_ip.items():
            self.net.script(ip, steps=steps)
        with mock.patch.object(asset_cache, 'resolve_safe_ips', return_value=ips):
            return asset_cache.LabAssetCacheController().asset(url=_URL)

    def test_success_caches_and_marks_miss(self):
        response = self._serve(['93.184.216.34'], {'93.184.216.34': _png_steps()})
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers.get('X-Lab-Asset-Cache'), 'miss')
        self.assertEqual(response.headers.get('Content-Type'), 'image/png')
        self.assertEqual(response.headers.get('X-Content-Type-Options'), 'nosniff')
        self.assertEqual(len(os.listdir(self.root)), 1)

    def test_redirect_is_refused_without_fallback(self):
        response = self._serve(['93.184.216.34', '93.184.216.35'], {
            '93.184.216.34': _raw_http('302 Found', b'',
                                      ('Content-Type', 'image/png'),
                                      ('Location', 'https://evil.example/x')),
            '93.184.216.35': _png_steps(),
        })
        self.assertEqual(response.status, 403)
        self.assertEqual([c[0] for c in self.net.conns], ['93.184.216.34'])
        self.assertEqual(os.listdir(self.root), [])

    def test_oversize_maps_to_413(self):
        self.request.env['ir.config_parameter'].params['lab_catalog.asset_max_bytes'] = '64'
        body = b'x' * 256
        response = self._serve(['93.184.216.34', '93.184.216.35'], {
            '93.184.216.34': _raw_http('200 OK', body, ('Content-Type', 'image/png')),
            '93.184.216.35': _png_steps(),
        })
        self.assertEqual(response.status, 413)
        self.assertEqual([c[0] for c in self.net.conns], ['93.184.216.34'])

    def test_network_error_maps_to_504(self):
        self.net.script('93.184.216.34', connect_error=socket.timeout('timed out'))
        self.net.script('93.184.216.35', connect_error=ConnectionResetError('reset'))
        with mock.patch.object(asset_cache, 'resolve_safe_ips',
                               return_value=['93.184.216.34', '93.184.216.35']):
            response = asset_cache.LabAssetCacheController().asset(url=_URL)
        self.assertEqual(response.status, 504)
        self.assertEqual(len(self.net.conns), 2)

    def test_mixed_private_resolution_maps_to_403_without_connecting(self):
        infos = [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '',
                  ('93.184.216.34', 443, 0, 0)),
                 (socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, '',
                  ('fe80::1', 443, 0, 0))]
        with mock.patch.object(asset_cache.socket, 'getaddrinfo', return_value=infos):
            response = asset_cache.LabAssetCacheController().asset(url=_URL)
        self.assertEqual(response.status, 403)
        self.assertEqual(self.net.conns, [])

    def test_ensure_cached_uses_same_fallback(self):
        self.net.script('2001:db8::5', connect_error=socket.timeout('timed out'))
        self.net.script('93.184.216.34', steps=_png_steps())
        with mock.patch.object(asset_cache, 'resolve_safe_ips',
                               return_value=['2001:db8::5', '93.184.216.34']):
            self.assertTrue(asset_cache.ensure_cached(_URL))
        self.assertEqual(len(self.net.conns), 2)
        self.assertEqual(len(os.listdir(self.root)), 1)


# ------------------------------------------------------------------ 不变的边界
class TestPolicyUnchanged(unittest.TestCase):
    def test_whitelist_and_https_only_unchanged(self):
        self.assertEqual(asset_cache.ALLOWED_HOSTS,
                         frozenset({'alimg.szlcsc.com', 'atta.szlcsc.com',
                                    'www.szlcsc.com', 'item.szlcsc.com'}))
        for bad in ('http://alimg.szlcsc.com/a.png',
                    'https://evil.example/a.png',
                    'https://127.0.0.1/a.png',
                    'https://alimg.szlcsc.com/a b.png'):
            with self.subTest(url=bad):
                with self.assertRaises(asset_cache.LabApiError):
                    asset_cache.validate_url_static(bad)
        self.assertEqual(asset_cache.validate_url_static(_URL)[0], _HOST)

    def test_no_new_http_client_and_no_verification_disable(self):
        with open(_SRC, 'r', encoding='utf-8') as fh:
            src = fh.read()
        for forbidden in ('CERT_NONE', 'check_hostname', 'verify_mode',
                          'import requests', 'urlopen', 'http.client',
                          'HTTPSConnection', 'proxies'):
            self.assertNotIn(forbidden, src)


if __name__ == '__main__':
    unittest.main()
