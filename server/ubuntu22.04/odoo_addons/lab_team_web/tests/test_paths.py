# -*- coding: utf-8 -*-
"""lab_team_web.tools.paths 纯函数测试（不依赖 Odoo）。

运行（仓库根目录）：
    python -m unittest discover -s server/ubuntu22.04/odoo_addons/lab_team_web/tests -v

说明
----
* 本机没有 Odoo 运行时，因此**不能** "import lab_team_web.tools.paths"：包的
  __init__ 会 import controllers -> odoo。这里用 importlib 按文件路径加载
  tools/paths.py，只执行这一个纯函数模块。
* 同目录的 test_team_web_http.py 在缺少 odoo 时于导入阶段抛
  unittest.SkipTest，所以上面的 discover 命令仍会完整执行本文件的用例。
* 断言对应 maintenance/audit/team-web-phase1-test-plan.md 的 L1 用例；
  其中 test_chinese_is_percent_encoded 是记录已知契约缺口的
  expectedFailure，不是"通过"。
"""
import importlib.util
import os
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

PATHS_PY = Path(__file__).resolve().parents[1] / 'tools' / 'paths.py'


def _load_paths_module():
    """按文件路径加载 tools/paths.py，避开包 __init__ 对 odoo 的依赖。"""
    spec = importlib.util.spec_from_file_location(
        'lab_team_web_tools_paths', str(PATHS_PY))
    if spec is None or spec.loader is None:
        raise ImportError('无法从 %s 构造 importlib spec' % PATHS_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


paths = _load_paths_module()


class NormalizeNextTest(unittest.TestCase):
    """normalize_next：next 参数只能收敛成站内相对路径。"""

    def test_keeps_site_relative_path_and_query(self):
        self.assertEqual(paths.normalize_next('/lab?q=abc'), '/lab?q=abc')
        self.assertEqual(
            paths.normalize_next('/team/lab/items/lcsc:C1'),
            '/team/lab/items/lcsc:C1')
        self.assertEqual(paths.normalize_next('/'), '/')

    def test_rejects_protocol_relative_url(self):
        for raw in ('//evil.com', '///evil.com', '//evil.com/lab'):
            with self.subTest(raw=raw):
                self.assertEqual(
                    paths.normalize_next(raw), paths.CANONICAL_BASE)

    def test_rejects_absolute_url_and_javascript_scheme(self):
        for raw in ('https://evil.com', 'http://evil.com/lab',
                    'javascript:alert(1)', 'mailto:x@example.com'):
            with self.subTest(raw=raw):
                self.assertEqual(
                    paths.normalize_next(raw), paths.CANONICAL_BASE)

    def test_rejects_backslash(self):
        for raw in ('/\\evil', '\\\\evil.com', '/lab\\..\\x'):
            with self.subTest(raw=raw):
                self.assertEqual(
                    paths.normalize_next(raw), paths.CANONICAL_BASE)

    def test_rejects_control_characters(self):
        # 中间嵌入控制字符：必须退回默认
        for raw in ('/lab\x00', '/lab\x01', '/lab\x00/evil',
                    '/lab\x1f/evil'):
            with self.subTest(raw=repr(raw)):
                self.assertEqual(
                    paths.normalize_next(raw), paths.CANONICAL_BASE)
        # 首尾空白类控制字符会被 strip；结果不得再含控制字符
        for raw in ('/lab\r', '/lab\n', '/lab\t', '/lab\x1f'):
            with self.subTest(raw=repr(raw)):
                result = paths.normalize_next(raw)
                self.assertIn(result, ('/lab', paths.CANONICAL_BASE))
                self.assertFalse(
                    any(ord(ch) < 0x20 or ord(ch) == 0x7f for ch in result))

    def test_allows_colon_in_business_path(self):
        # itemKey 自身带冒号（lcsc:C123 / lab:42），next 指向详情时必须保留
        self.assertEqual(
            paths.normalize_next('/team/lab/items/lcsc:C1'),
            '/team/lab/items/lcsc:C1')
        self.assertEqual(
            paths.normalize_next('/lab/items/lab:42'), '/lab/items/lab:42')
        self.assertEqual(paths.normalize_next('/lab?q=a:b'), '/lab?q=a:b')

    def test_rejects_percent_encoded_protocol_relative(self):
        # 最多 3 轮百分号解码后仍须是站内相对路径（防 %2f%2f 绕过）
        for raw in ('/%2f%2fevil.com', '/%2F%2Fevil.com',
                    '/%252f%252fevil.com', '/%5Cevil'):
            with self.subTest(raw=raw):
                self.assertEqual(
                    paths.normalize_next(raw), paths.CANONICAL_BASE)

    def test_rejects_non_string(self):
        for raw in (None, 123, b'/lab', ['/lab'], object()):
            with self.subTest(raw=repr(raw)):
                self.assertEqual(
                    paths.normalize_next(raw), paths.CANONICAL_BASE)
        self.assertEqual(paths.normalize_next(None), paths.CANONICAL_BASE)

    def test_accepts_explicit_default(self):
        self.assertEqual(
            paths.normalize_next('https://evil.com', default='/safe'), '/safe')
        self.assertEqual(
            paths.normalize_next(None, default='/safe'), '/safe')
        self.assertEqual(
            paths.normalize_next('', default='/safe'), '/safe')
        # normalize_next('', default=None) 的兜底是规范前缀，不是空串
        self.assertEqual(paths.normalize_next(''), paths.CANONICAL_BASE)

    def test_strips_surrounding_whitespace(self):
        self.assertEqual(paths.normalize_next('  /team/lab  '), '/team/lab')

    def test_keeps_empty_query_string_token(self):
        # '?' 后无参数也应保留，回跳不应把用户输入丢掉
        self.assertEqual(paths.normalize_next('/team/lab?'), '/team/lab?')


class ResolveBaseTest(unittest.TestCase):
    """resolve_base：由请求路径推断页面链接基址。"""

    def test_canonical_prefix_maps_to_team(self):
        for path in ('/team', '/team/', '/team/lab',
                     '/team/lab/items/lcsc:C1'):
            with self.subTest(path=path):
                self.assertEqual(paths.resolve_base(path), '/team')

    def test_root_aliases_map_to_empty_base(self):
        for path in ('/login', '/login/', '/lab', '/lab/',
                     '/lab/items/lab:42'):
            with self.subTest(path=path):
                self.assertEqual(paths.resolve_base(path), '')

    def test_unknown_paths_fall_back_to_canonical(self):
        for path in ('/web/login', '/odoo', '/', '', '/teamwork', '/labx'):
            with self.subTest(path=path):
                self.assertEqual(paths.resolve_base(path), '/team')

    def test_root_aliases_can_be_disabled(self):
        self.assertEqual(
            paths.resolve_base('/lab', root_aliases_enabled=False), '/team')
        self.assertEqual(
            paths.resolve_base('/login', root_aliases_enabled=False), '/team')
        self.assertEqual(
            paths.resolve_base('/team', root_aliases_enabled=False), '/team')

    def test_non_string_path_falls_back(self):
        for path in (None, 42, b'/team', ['/team']):
            with self.subTest(path=repr(path)):
                self.assertEqual(paths.resolve_base(path), '/team')


class ItemKeyTest(unittest.TestCase):
    """itemKey 的解析、校验与路径编码。"""

    def test_accepts_lcsc_codes(self):
        for key in ('lcsc:C123456', 'lcsc:C1'):
            with self.subTest(key=key):
                self.assertTrue(paths.is_valid_item_key(key))

    def test_accepts_lab_numeric_ids(self):
        for key in ('lab:42', 'lab:0', 'lab:100'):
            with self.subTest(key=key):
                self.assertTrue(paths.is_valid_item_key(key))

    def test_rejects_malformed_keys(self):
        for key in ('lab:abc', 'lab:12a', 'lab:', 'junk', 'lcsc:',
                    'lcsc:C', 'lcsc:X1', '', 'C123456', 'lab:-1', None, 42):
            with self.subTest(key=repr(key)):
                self.assertFalse(paths.is_valid_item_key(key))

    def test_parse_item_key_splits_kind_and_value(self):
        self.assertEqual(paths.parse_item_key('lcsc:C123456'),
                         ('lcsc', 'C123456'))
        self.assertEqual(paths.parse_item_key('lab:42'), ('lab', 42))
        self.assertEqual(paths.parse_item_key('junk'), (None, None))
        self.assertEqual(paths.parse_item_key('lcsc:'), (None, None))


class QuoteItemKeyTest(unittest.TestCase):
    """quote_item_key：路径段编码。"""

    def test_safe_key_is_unchanged(self):
        self.assertEqual(paths.quote_item_key('lcsc:C123456'), 'lcsc:C123456')
        self.assertEqual(paths.quote_item_key('lab:42'), 'lab:42')

    def test_space_is_percent_encoded(self):
        quoted = paths.quote_item_key('lcsc:C 123')
        self.assertIn('%20', quoted)
        self.assertNotIn(' ', quoted)
        self.assertEqual(quoted, 'lcsc:C%20123')

    def test_query_and_fragment_delimiters_are_encoded(self):
        quoted = paths.quote_item_key('lab:a?b#c')
        self.assertNotIn('?', quoted)
        self.assertNotIn('#', quoted)
        self.assertEqual(quoted, 'lab:a%3Fb%23c')

    def test_chinese_key_stays_path_safe(self):
        # 不论是否编码，结果都不能把 ? / # 带进路径，也不能出现 //
        quoted = paths.quote_item_key('lab:测试')
        self.assertNotIn('?', quoted)
        self.assertNotIn('#', quoted)
        self.assertNotIn('//', quoted)
    def test_chinese_is_percent_encoded(self):
        """契约：含中文的 key 必须百分号编码。

        当前实现用 str.isalnum() 判断安全字符，而它对中文返回 True，
        会把中文原样留在路径里。这是被测代码的已知缺口（不在本任务修），
        因此标记 expectedFailure；业务侧修复后本用例会转为 unexpected
        success，应删除装饰器并纳入正式回归。
        """
        quoted = paths.quote_item_key('lab:测试')
        self.assertNotIn('测', quoted)
        self.assertIn('%E6%B5%8B', quoted)


class ClampLimitTest(unittest.TestCase):
    """clamp_limit：分页上限的边界。"""

    def test_in_range_values_are_kept(self):
        self.assertEqual(paths.clamp_limit(1), 1)
        self.assertEqual(paths.clamp_limit(24), 24)
        self.assertEqual(paths.clamp_limit(100), 100)
        self.assertEqual(paths.clamp_limit('50'), 50)

    def test_below_one_falls_back_to_default(self):
        for raw in (0, -1, '-20'):
            with self.subTest(raw=raw):
                self.assertEqual(
                    paths.clamp_limit(raw), paths.DEFAULT_LIMIT)

    def test_above_maximum_is_capped(self):
        for raw in (101, 1000, '9999'):
            with self.subTest(raw=raw):
                self.assertEqual(
                    paths.clamp_limit(raw), paths.MAX_LIMIT)

    def test_invalid_values_fall_back_to_default(self):
        for raw in (None, 'abc', '', [], {}):
            with self.subTest(raw=repr(raw)):
                self.assertEqual(
                    paths.clamp_limit(raw), paths.DEFAULT_LIMIT)

    def test_custom_default_and_maximum(self):
        self.assertEqual(
            paths.clamp_limit(0, default=10, maximum=20), 10)
        self.assertEqual(
            paths.clamp_limit(21, default=10, maximum=20), 20)
        self.assertEqual(
            paths.clamp_limit(15, default=10, maximum=20), 15)


class ParseFlagTest(unittest.TestCase):
    """parse_flag：query/表单布尔值的收敛。"""

    def test_truthy_tokens(self):
        for raw in ('1', 'true', 'TRUE', ' True ', 'on', 'yes', 'y', 'Yes'):
            with self.subTest(raw=raw):
                self.assertTrue(paths.parse_flag(raw))

    def test_bool_true(self):
        self.assertTrue(paths.parse_flag(True))

    def test_falsey_tokens(self):
        for raw in ('0', 'false', 'off', 'no', '', None, False, '2',
                    'banana', 0):
            with self.subTest(raw=repr(raw)):
                self.assertFalse(paths.parse_flag(raw))


class FormatQuantityTest(unittest.TestCase):
    """format_quantity：库存数量展示。"""

    def test_integers_have_no_decimal_point(self):
        for raw, expected in ((5, '5'), (5.0, '5'), ('5.0', '5'), (0, '0')):
            with self.subTest(raw=repr(raw)):
                self.assertEqual(paths.format_quantity(raw), expected)

    def test_decimals_trim_trailing_zeros(self):
        for raw, expected in ((1.5, '1.5'), ('1.500', '1.5'),
                              (0.25, '0.25'), (12.345, '12.345')):
            with self.subTest(raw=repr(raw)):
                self.assertEqual(paths.format_quantity(raw), expected)

    def test_empty_values_use_placeholder(self):
        for raw in (None, ''):
            with self.subTest(raw=repr(raw)):
                self.assertEqual(paths.format_quantity(raw), '—')
        self.assertEqual(paths.format_quantity(None, empty='N/A'), 'N/A')

    def test_non_numeric_uses_placeholder(self):
        for raw in ('abc', object(), '—'):
            with self.subTest(raw=repr(raw)):
                self.assertEqual(paths.format_quantity(raw), '—')


class UrlBuilderTest(unittest.TestCase):
    """item_url / lab_url / login_url / logout_url 在两种 base 下的拼接。"""

    def test_welcome_url(self):
        self.assertEqual(paths.welcome_url(''), '/')
        self.assertEqual(paths.welcome_url('/team'), '/team/')

    def test_login_url_without_next(self):
        self.assertEqual(paths.login_url(''), '/login')
        self.assertEqual(paths.login_url('/team'), '/team/login')
        self.assertNotIn('//', paths.login_url(''))

    def test_login_url_encodes_next(self):
        url = paths.login_url('', next_path='/lab?q=abc')
        self.assertTrue(url.startswith('/login?next='))
        self.assertNotIn('//', url)
        self.assertEqual(parse_qs(urlsplit(url).query)['next'], ['/lab?q=abc'])

    def test_logout_url(self):
        self.assertEqual(paths.logout_url(''), '/logout')
        self.assertEqual(paths.logout_url('/team'), '/team/logout')
        self.assertNotIn('//', paths.logout_url(''))

    def test_lab_url_without_query(self):
        self.assertEqual(paths.lab_url(''), '/lab')
        self.assertEqual(paths.lab_url('/team'), '/team/lab')
        self.assertNotIn('//', paths.lab_url(''))

    def test_lab_url_with_query_parameters(self):
        url = paths.lab_url('', query='abc def', category_id=7,
                            cursor='cur', stock_only=True)
        self.assertTrue(url.startswith('/lab?'))
        self.assertEqual(urlsplit(url).path, '/lab')
        params = parse_qs(urlsplit(url).query)
        self.assertEqual(params['q'], ['abc def'])
        self.assertEqual(params['category_id'], ['7'])
        self.assertEqual(params['cursor'], ['cur'])
        self.assertEqual(params['stock_only'], ['1'])
        self.assertNotIn('//', url)

    def test_lab_url_omits_stock_only_when_false(self):
        self.assertEqual(paths.lab_url('', stock_only=False), '/lab')
        self.assertEqual(paths.lab_url('/team', stock_only=False), '/team/lab')

    def test_item_url(self):
        self.assertEqual(
            paths.item_url('', 'lcsc:C1'), '/lab/items/lcsc:C1')
        self.assertEqual(
            paths.item_url('/team', 'lcsc:C1'), '/team/lab/items/lcsc:C1')
        self.assertEqual(
            paths.item_url('', 'lcsc:C 1'), '/lab/items/lcsc:C%201')
        self.assertNotIn('//', paths.item_url('', 'lab:42'))


class ErrorMessageTest(unittest.TestCase):
    """error_message：错误码到中文文案的映射。"""

    def test_known_codes_return_mapped_message(self):
        for code, message in paths.ERROR_MESSAGES.items():
            with self.subTest(code=code):
                self.assertEqual(paths.error_message(code), message)

    def test_unknown_or_missing_code_falls_back(self):
        internal = paths.ERROR_MESSAGES['INTERNAL_ERROR']
        for code in ('NOPE', None, '', 'forbidden'):
            with self.subTest(code=repr(code)):
                self.assertEqual(paths.error_message(code), internal)

    def test_explicit_fallback_for_unknown_code(self):
        self.assertEqual(
            paths.error_message('NOPE', fallback='自定义说明'), '自定义说明')

    def test_known_code_wins_over_fallback(self):
        self.assertEqual(
            paths.error_message('FORBIDDEN', fallback='自定义说明'),
            paths.ERROR_MESSAGES['FORBIDDEN'])


class ConstantsTest(unittest.TestCase):
    """对外常量是契约的一部分，被控制器/模板共同依赖。"""

    def test_constants(self):
        self.assertEqual(paths.CANONICAL_BASE, '/team')
        # 别名集合可随实现增加（当前含 /logout）；这里锁定必须存在的成员
        self.assertIn('/login', paths.ROOT_ALIASES)
        self.assertIn('/lab', paths.ROOT_ALIASES)
        self.assertTrue(all(alias.startswith('/') and not alias.startswith('//')
                            for alias in paths.ROOT_ALIASES))
        self.assertEqual(paths.DEFAULT_LIMIT, 24)
        self.assertEqual(paths.MAX_LIMIT, 100)


if __name__ == '__main__':
    unittest.main(verbosity=2)

class HostDecisionTest(unittest.TestCase):
    """管理 Host 根入口决策（复审要求：可单测，默认关闭，不接管所有 Host 的 /）。"""

    def test_normalize_host_shapes(self):
        self.assertEqual(paths.normalize_host('Team.L-Creation.Club:8069'), 'team.l-creation.club')
        self.assertEqual(paths.normalize_host('[::1]:8069'), '::1')
        self.assertEqual(paths.normalize_host('https://team.example.com/path'), 'team.example.com')
        self.assertEqual(paths.normalize_host('team.example.com.'), 'team.example.com')
        self.assertEqual(paths.normalize_host(''), '')
        self.assertEqual(paths.normalize_host(None), '')

    def test_parse_host_list(self):
        self.assertEqual(paths.parse_host_list(''), frozenset())
        self.assertEqual(paths.parse_host_list('a.com, b.com  C.COM'), frozenset({'a.com', 'b.com', 'c.com'}))
        self.assertEqual(paths.parse_host_list('https://team.example.com/'), frozenset({'team.example.com'}))

    def test_root_served_only_on_management_host(self):
        self.assertEqual(paths.decide_root('/', 'team.example.com', 'team.example.com'), 'serve')
        self.assertEqual(paths.decide_root('/', 'lc.rm.com', 'team.example.com'), 'fallthrough')
        self.assertEqual(paths.decide_root('/lab', 'team.example.com', 'team.example.com'), 'fallthrough')

    def test_root_disabled_when_unconfigured_or_switched_off(self):
        self.assertEqual(paths.decide_root('/', 'team.example.com', ''), 'fallthrough')
        self.assertEqual(
            paths.decide_root('/', 'team.example.com', 'team.example.com', enabled=False),
            'fallthrough')

    def test_root_alias_paths_are_narrow(self):
        for value in ('/login', '/logout', '/lab', '/lab/items/lcsc:C1'):
            self.assertTrue(paths.is_root_alias_path(value), value)
        for value in ('/lab/api/catalog/search', '/lab/scan', '/lab/labels/plan',
                      '/lab/client/updates/manifest', '/web/login', '/team/lab', '/'):
            self.assertFalse(paths.is_root_alias_path(value), value)

class WorkflowRootAliasTest(unittest.TestCase):
    """P3 业务页面的根级别入口：root_aliases=0 时全部必须真实 404。

    覆盖点（Lead 要求）：**每个新根页面**都在名单里；同时不能把其它控制器
    已占用的路径（旧 /lab/scan、旧标签表单端点、/lab/api/**、更新清单）卷进来。
    """

    NEW_PAGES = (
        '/scan',
        '/account',
        '/lab/receipts',
        '/lab/bags',
        '/lab/bags/12',
        '/lab/labels',
        '/lab/issues',
        '/lab/issues/new',
        '/lab/locations',
        '/lab/location-mappings',
        '/lab/history',
        '/lab/materials',
        '/lab/settings',
    )

    OTHER_CONTROLLER_PATHS = (
        '/lab/scan',
        '/lab/scan/resolve',
        '/lab/scan/submit',
        '/lab/labels/plan',
        '/lab/labels/download',
        '/lab/api/catalog/search',
        '/lab/api/inventory/bags',
        '/lab/api/inventory/bag',
        '/lab/api/labels/plan',
        '/lab/api/labels/preview',
        '/lab/client/updates/manifest',
        '/web/login',
        '/odoo',
        '/team/lab',
        '/team/lab/receipts',
        '',
        '/',
    )

    def test_every_new_page_is_a_root_alias_path(self):
        for value in self.NEW_PAGES:
            with self.subTest(path=value):
                self.assertTrue(paths.is_root_alias_path(value), value)

    def test_other_controllers_are_never_matched(self):
        for value in self.OTHER_CONTROLLER_PATHS:
            with self.subTest(path=value):
                self.assertFalse(paths.is_root_alias_path(value), value)

    def test_new_pages_resolve_to_root_base(self):
        for value in self.NEW_PAGES:
            with self.subTest(path=value):
                self.assertEqual(paths.resolve_base(value), '', value)

    def test_new_pages_fall_back_to_team_base_when_aliases_disabled(self):
        for value in self.NEW_PAGES:
            with self.subTest(path=value):
                self.assertEqual(
                    paths.resolve_base(value, root_aliases_enabled=False),
                    paths.CANONICAL_BASE, value)

    def test_scan_and_account_are_declared_aliases(self):
        # resolve_base 依赖 ROOT_ALIASES 前缀匹配；/lab 已覆盖 /lab/* 页面
        for alias in ('/scan', '/account', '/lab', '/login', '/logout'):
            with self.subTest(alias=alias):
                self.assertIn(alias, paths.ROOT_ALIASES)


class SafeDocUrlTest(unittest.TestCase):
    """资料链接白名单：只允许站内相对路径或 http(s)。"""

    def test_allows_site_relative_and_http(self):
        for value in ('/web/content/1', '/lab/api/asset?url=x', 'https://example.com/a.pdf',
                      'http://example.com/a.pdf'):
            self.assertEqual(paths.safe_doc_url(value), value, value)

    def test_malformed_urls_do_not_raise(self):
        """畸形 URL 不能让 urlsplit 抛 ValueError（否则详情页白屏）。"""
        for value in ('https://[', 'http://[::1', 'https://exa mple.com', '://x',
                      'http://', 'https://', 'https://[]', 'https://ok host/x'):
            self.assertIsNone(paths.safe_doc_url(value), repr(value))
        # 站内相对路径即使含 % 也原样放行（同源，不构成跳转风险）
        self.assertEqual(paths.safe_doc_url('/%'), '/%')

    def test_rejects_dangerous_schemes(self):
        for value in ('javascript:alert(1)', 'data:text/html;base64,AAA', 'vbscript:x',
                      '//evil.example/a', 'httpx://example.com', 'file:///etc/passwd',
                      '\\\\evil.example', '', None, '  '):
            self.assertIsNone(paths.safe_doc_url(value), repr(value))


class LoginFormStaticTest(unittest.TestCase):
    """静态回归：登录表单必须是 POST，且不得把密码交给 GET。

    这是 Codex 复审指出的真实风险：form 缺 method 时浏览器默认 GET，
    JS 未加载会把账号密码写进 URL 与访问日志。
    """

    def setUp(self):
        import io
        import re as _re
        here = os.path.dirname(os.path.abspath(__file__))
        xml_path = os.path.join(here, os.pardir, 'views', 'pages.xml')
        with io.open(xml_path, encoding='utf-8') as handle:
            self.xml = handle.read()
        self.re = _re

    def test_login_form_uses_post(self):
        form = self.re.search(r'<form[^>]*id="lc-login-form"[^>]*>', self.xml)
        self.assertIsNotNone(form, '未找到登录表单')
        tag = form.group(0)
        self.assertIn('method="post"', tag.lower(), '登录表单必须显式 POST')
        self.assertNotIn('method="get"', tag.lower())

    def test_login_form_has_noscript_guard(self):
        self.assertIn('<noscript>', self.xml)
        self.assertIn('登录需要启用 JavaScript', self.xml)

    def test_no_password_field_in_get_action(self):
        form = self.re.search(r'<form[^>]*id="lc-login-form"[^>]*>', self.xml)
        self.assertNotIn('action="/web/session/authenticate"', form.group(0))

class FormatPriceTest(unittest.TestCase):
    """价格展示必须与 team.js 的 formatPrice 一致，避免首屏与动态卡片不一致。"""

    def test_missing_price_placeholder(self):
        for value in (None, '', 'abc'):
            self.assertEqual(paths.format_price(value), '价格待询')

    def test_currency_symbols(self):
        self.assertEqual(paths.format_price(12, 'CNY'), '¥12')
        self.assertEqual(paths.format_price(12.5, 'cny'), '¥12.50')
        self.assertEqual(paths.format_price('3', 'USD'), '$3')
        self.assertEqual(paths.format_price(3, 'EUR'), '€3')

    def test_unknown_currency_prefix(self):
        self.assertEqual(paths.format_price(1.234, 'JPY'), 'JPY 1.23')

    def test_default_currency_is_cny(self):
        self.assertEqual(paths.format_price(8), '¥8')
        self.assertEqual(paths.format_price(float('nan')), '价格待询')
