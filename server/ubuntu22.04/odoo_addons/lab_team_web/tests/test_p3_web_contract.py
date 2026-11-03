# -*- coding: utf-8 -*-
"""P3 前端外壳的静态契约测试（无需 Odoo 运行时、无需数据库）。

只测**真实边界**，不写镜像实现：
  * 模板注册：manifest 列出的每个 xml 都真实存在；views/ 下不存在"没登记就永远
    加载不到"的孤儿文件；控制器 PAGE_SPECS 要求的模板 id 确实落在对应 domain 文件里。
  * 路由成对：每个业务页面都有 /team 前缀 + 根级别两条路由；不重复注册旧 /lab/scan。
  * 角色门槛：manager 页面的 need 必须是 manager，account 是登录即可，取值封闭。
  * 根别名：每个新根页面在 root_aliases=0 时都会 404（走 tools/paths 纯函数），
    且不得吞掉 /lab/scan、/lab/api/**、旧标签表单端点、更新清单。
  * CSP/无内联：模板里没有内联 <script>、没有 on* 事件属性、没有 javascript:；
    页面脚本没有 eval/new Function/HTML 注入/fetch 直连（写操作必须走 LC.submit）。
  * 接线一致：页面脚本用到的端点在 WORKFLOW_ENDPOINTS 里；LC.register 的 page id
    与文件名一致且是已注册页面；会话接口暴露契约要求的全部权限位。

运行（仓库根目录）：
    python -m unittest discover -s server/ubuntu22.04/odoo_addons/lab_team_web/tests -v

本文件不修改任何业务代码；发现不一致时以失败信息里的文件/名字为准，回到对应
写域修（外壳文件归 T0，页面文件归各 domain 作者）。
"""
import ast
import importlib.util
import re
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

HERE = Path(__file__).resolve().parent
MOD = HERE.parent
VIEWS = MOD / 'views'
JS_DIR = MOD / 'static' / 'src' / 'js'
PAGES_DIR = JS_DIR / 'pages'
PATHS_PY = MOD / 'tools' / 'paths.py'

#: 契约要求 session 暴露的权限位（frontend-contract.md §5.1）
CONTRACT_PERMISSIONS = (
    'can_catalog', 'can_lab', 'is_manager',
    'can_receipt', 'can_issue', 'can_return', 'can_manage_labels',
    'can_issue_for_others', 'can_manage_locations',
    'can_manage_mappings', 'can_manage_members',
)

#: 本模块需要检查的模板文件（全部已在 manifest 登记）
VIEW_XML_FILES = (
    'pages.xml',
    'team_templates.xml',
    'workflow_receipt.xml',
    'workflow_issue.xml',
    'workflow_inventory.xml',
    'workflow_account.xml',
)

#: 其它控制器已占用的路径：root_aliases 逻辑绝不能把它们卷进来
FOREIGN_PATHS = (
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
    '/web/dataset/call_kw',
    '/odoo',
    '/team/lab',
    '/team/lab/receipts',
    '/',
    '',
)

#: JS 里禁止出现的写法（CSP script-src 'self' + 不可注入 HTML）
#: core 是唯一允许直接 fetch 的地方（它就是 HTTP 层）；页面脚本只能走 LC.rpc/LC.submit。
FORBIDDEN_JS_COMMON = (
    r'\beval\s*\(',
    r'new\s+Function\s*\(',
    r'\.innerHTML',
    r'\.outerHTML',
    r'insertAdjacentHTML\s*\(',
    r'document\.write\s*\(',
)

FORBIDDEN_JS_PAGE_ONLY = (
    r'\bfetch\s*\(',
    r'new\s+XMLHttpRequest',
)


def read(*parts):
    return MOD.joinpath(*parts).read_text(encoding='utf-8')


def module_literal(path, name):
    """取模块级 name = <字面量> 的值（PAGE_SPECS / WORKFLOW_* 都是纯字面量）。"""
    tree = ast.parse(Path(path).read_text(encoding='utf-8'))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if name in targets:
                return ast.literal_eval(node.value)
    raise AssertionError('%s 中找不到模块级赋值 %s' % (path, name))


def manifest_dict():
    source = read('__manifest__.py')
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Dict):
            try:
                return ast.literal_eval(node)
            except Exception:
                continue
    raise AssertionError('__manifest__.py 里没有可解析的字典')


def strip_xml_comments(text):
    return re.sub(r'<!--.*?-->', '', text, flags=re.S)


def strip_js_comments(text):
    """去掉整行 // 与 * 注释，避免把说明文字当成代码。"""
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    kept = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith('//') or stripped.startswith('*') or stripped.startswith('/*'):
            continue
        kept.append(line)
    return '\n'.join(kept)


def template_ids(text):
    return set(re.findall(r'<template\s+id="([^"]+)"', strip_xml_comments(text)))


def route_paths():
    """[(handler_name, path), ...]，从 http.route 装饰器的字面量参数解析。"""
    tree = ast.parse(read('controllers', 'workflow_pages.py'))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            func = decorator.func
            if not (isinstance(func, ast.Attribute) and func.attr == 'route'):
                continue
            if not decorator.args:
                continue
            try:
                paths = ast.literal_eval(decorator.args[0])
            except Exception:
                continue
            if isinstance(paths, str):
                paths = [paths]
            found.extend((node.name, path) for path in paths)
    return found


def load_paths_module():
    spec = importlib.util.spec_from_file_location('ltw_paths_for_contract', str(PATHS_PY))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TemplateRegistrationTest(unittest.TestCase):
    """模板必须"登记过且真实存在"，否则线上是有路由没界面。"""

    def test_manifest_lists_existing_view_files(self):
        data = manifest_dict()['data']
        self.assertIn('views/pages.xml', data)
        self.assertIn('views/team_templates.xml', data)
        for entry in data:
            if entry.startswith('views/'):
                with self.subTest(view=entry):
                    self.assertTrue((MOD / entry).exists(), 'manifest 登记了不存在的文件：%s' % entry)

    def test_every_view_file_is_registered(self):
        registered = {Path(entry).name for entry in manifest_dict()['data']
                      if entry.startswith('views/')}
        on_disk = {path.name for path in VIEWS.glob('*.xml')}
        orphans = sorted(on_disk - registered)
        self.assertFalse(
            orphans,
            'views/ 下存在未登记的文件（Odoo 永远不会加载）：%s；'
            '要么加进 __manifest__.py data，要么删掉' % orphans)

    def test_domain_files_are_registered(self):
        registered = {Path(entry).name for entry in manifest_dict()['data']}
        for name in ('workflow_receipt.xml', 'workflow_issue.xml',
                     'workflow_inventory.xml', 'workflow_account.xml'):
            with self.subTest(file=name):
                self.assertIn(name, registered)

    def test_page_specs_templates_live_in_their_domain_file(self):
        specs = module_literal(MOD / 'controllers' / 'workflow_pages.py', 'PAGE_SPECS')
        domain_file = {
            'receipt': 'workflow_receipt.xml',
            'issue': 'workflow_issue.xml',
            'inventory': 'workflow_inventory.xml',
            'account': 'workflow_account.xml',
        }
        for page_id, spec in specs.items():
            with self.subTest(page=page_id):
                self.assertIn(spec['domain'], domain_file,
                              'PAGE_SPECS[%s] 的 domain 不在四个登记文件里' % page_id)
                key = spec['template']
                self.assertTrue(key.startswith('lab_team_web.'),
                                '模板 key 必须是 lab_team_web.<id>：%s' % key)
                short = key.split('.', 1)[1]
                ids = template_ids(read('views', domain_file[spec['domain']]))
                self.assertIn(short, ids,
                              '%s 里没有模板 %s（控制器会渲染占位页）' % (domain_file[spec['domain']], short))

    def test_shared_shell_templates_exist(self):
        ids = template_ids(read('views', 'team_templates.xml'))
        for name in ('workflow_page', 'workflow_body', 'workflow_status',
                     'workflow_page_tail', 'workflow_placeholder',
                     'workflow_placeholder_body'):
            with self.subTest(template=name):
                self.assertIn(name, ids)


class XmlWellFormedTest(unittest.TestCase):
    """Odoo 用 lxml 解析 views/*.xml：下面两类写法会让 `-u` 直接失败，不是风格问题。

    1) XML 注释体里出现连续 "--"（分隔线是最常见的踩法）；
    2) 裸布尔属性（`data-lc-readonly` 少了 `=""`）——XML 属性必须有值。
    """

    XML_FILES = VIEW_XML_FILES

    def test_comments_have_no_double_dash(self):
        for name in self.XML_FILES:
            text = read('views', name)
            for body in re.findall(r'<!--(.*?)-->', text, flags=re.S):
                with self.subTest(file=name):
                    self.assertNotIn(
                        '--', body,
                        '%s 的注释体含连续 "--"（XML 非法，lxml 会拒绝升级）：%r'
                        % (name, body.strip().splitlines()[:1]))

    def test_no_bare_boolean_attributes(self):
        for name in self.XML_FILES:
            text = strip_xml_comments(read('views', name))
            bare = re.findall(r'<[^>]*?\s(data-[a-z0-9-]+)(?=[\s/>])', text)
            with self.subTest(file=name):
                self.assertFalse(
                    bare,
                    '%s 存在裸布尔属性 %s；XML 属性必须带值，写成 data-lc-xxx=""'
                    % (name, sorted(set(bare))))

    def test_every_view_file_parses(self):
        for name in self.XML_FILES:
            with self.subTest(file=name):
                try:
                    ET.fromstring(read('views', name))
                except ET.ParseError as error:
                    self.fail('%s 不是合法 XML：%s' % (name, error))


class RoutingTest(unittest.TestCase):
    """页面路由：成对注册、不抢旧路径、门槛必须经过统一 _page。"""

    def setUp(self):
        self.routes = route_paths()
        self.registered = {path for _handler, path in self.routes}
        self.pages = module_literal(MOD / 'controllers' / 'common.py', 'WORKFLOW_PAGES')

    def test_every_page_has_team_and_root_route(self):
        for page_id, (_title, path) in self.pages.items():
            with self.subTest(page=page_id):
                self.assertIn('/team' + path, self.registered,
                              '%s 缺少规范前缀路由 /team%s' % (page_id, path))
                has_root = path in self.registered or any(
                    route.startswith(path + '/') and '<' in route
                    for route in self.registered)
                self.assertTrue(has_root, '%s 缺少根级别路由 %s' % (page_id, path))

    def test_no_duplicate_legacy_scan_route(self):
        self.assertNotIn('/lab/scan', self.registered,
                         '旧 /lab/scan 由 lab_workflow 提供 303，本模块不得重复注册')
        self.assertIn('/team/scan', self.registered, '新扫码页必须在 /team/scan')

    def test_all_page_handlers_go_through_guard(self):
        """每个路由处理函数都必须调用 self._page（统一做根别名/角色/上下文）。"""
        tree = ast.parse(read('controllers', 'workflow_pages.py'))
        handlers = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                handlers[node.name] = node
        for handler in {name for name, _path in self.routes}:
            node = handlers[handler]
            calls = [child for child in ast.walk(node)
                     if isinstance(child, ast.Call)
                     and isinstance(child.func, ast.Attribute)
                     and child.func.attr == '_page']
            with self.subTest(handler=handler):
                self.assertTrue(calls, '%s 没有走 self._page（会绕过统一门槛）' % handler)

    def test_guard_covers_every_need_value(self):
        specs = module_literal(MOD / 'controllers' / 'workflow_pages.py', 'PAGE_SPECS')
        source = read('controllers', 'workflow_pages.py')
        guard = source.split('def guard_page(', 1)[1].split('\ndef ', 1)[0]
        self.assertIn('is_anonymous()', guard, '未登录必须先 303 到本站登录')
        for need in {spec['need'] for spec in specs.values()}:
            with self.subTest(need=need):
                self.assertIn(need, ('lab', 'manager', 'catalog', 'user'))
                if need != 'user':
                    self.assertIn("need == '%s'" % need, guard,
                                  'guard_page 没有处理 need=%s' % need)


class RolePolicyTest(unittest.TestCase):
    """管理页/目录页/账号页的准入门槛是安全边界，写死在这里防漂移。"""

    EXPECTED = {
        'receipts': 'lab',
        'scan': 'lab',
        'bags': 'lab',
        'bag': 'lab',
        'labels': 'lab',
        'issue_new': 'lab',
        'issues': 'lab',
        'history': 'lab',
        'locations': 'lab',
        'materials': 'catalog',
        'mappings': 'manager',
        'settings': 'manager',
        'account': 'user',
    }

    def test_page_need_matches_policy(self):
        specs = module_literal(MOD / 'controllers' / 'workflow_pages.py', 'PAGE_SPECS')
        self.assertEqual(set(specs), set(self.EXPECTED),
                         '页面集合变化：新增/删除页面必须同时更新本测试与前端契约')
        for page_id, need in self.EXPECTED.items():
            with self.subTest(page=page_id):
                self.assertEqual(specs[page_id]['need'], need)

    def test_manager_pages_are_reachable_only_via_manager_need(self):
        specs = module_literal(MOD / 'controllers' / 'workflow_pages.py', 'PAGE_SPECS')
        manager_pages = [page for page, spec in specs.items() if spec['need'] == 'manager']
        self.assertEqual(sorted(manager_pages), ['mappings', 'settings'])


class RootAliasTest(unittest.TestCase):
    """root_aliases=0 时的 404 语义必须覆盖每个新根页面，且不误伤其它控制器。"""

    @classmethod
    def setUpClass(cls):
        cls.paths = load_paths_module()
        cls.pages = module_literal(MOD / 'controllers' / 'common.py', 'WORKFLOW_PAGES')

    def test_every_page_is_alias_and_honours_switch(self):
        for page_id, (_title, path) in self.pages.items():
            with self.subTest(page=page_id):
                self.assertTrue(self.paths.is_root_alias_path(path),
                                '%s(%s) 不在根别名名单里，root_aliases=0 时仍会响应' % (page_id, path))
                self.assertEqual(self.paths.resolve_base(path), '')
                self.assertEqual(
                    self.paths.resolve_base(path, root_aliases_enabled=False),
                    self.paths.CANONICAL_BASE)

    def test_subpaths_are_covered(self):
        for path in ('/lab/bags/12', '/lab/issues/new'):
            with self.subTest(path=path):
                self.assertTrue(self.paths.is_root_alias_path(path))
                self.assertEqual(
                    self.paths.resolve_base(path, root_aliases_enabled=False),
                    self.paths.CANONICAL_BASE)

    def test_foreign_controllers_are_never_matched(self):
        for path in FOREIGN_PATHS:
            with self.subTest(path=path):
                self.assertFalse(self.paths.is_root_alias_path(path),
                                 'root 别名逻辑吞掉了别人的路径：%r' % (path,))


class CspTest(unittest.TestCase):
    """CSP script-src 'self'：不许内联脚本/事件属性/伪协议。"""

    XML_FILES = VIEW_XML_FILES

    def test_templates_have_no_inline_script(self):
        for name in self.XML_FILES:
            text = strip_xml_comments(read('views', name))
            with self.subTest(file=name):
                inline = re.findall(r'<script(?![^>]*\bsrc=)[^>]*>', text)
                self.assertFalse(inline, '%s 存在内联 <script>：%s' % (name, inline[:2]))

    def test_templates_have_no_inline_handlers_or_javascript_uri(self):
        for name in self.XML_FILES:
            text = strip_xml_comments(read('views', name))
            with self.subTest(file=name):
                self.assertIsNone(re.search(r'\son[a-z]+\s*=', text, re.I),
                                  '%s 存在内联事件属性（CSP 会拦）' % name)
                self.assertNotIn('javascript:', text.lower())

    def test_layout_outputs_config_and_loads_core_before_team_js(self):
        text = strip_xml_comments(read('views', 'pages.xml'))
        self.assertIn('data-workflow-config', text, 'body 必须下发 data-workflow-config')
        core = text.find('workflow_core.js')
        team = text.find('src/js/team.js')
        self.assertGreater(core, -1, 'layout 必须引入 workflow_core.js')
        self.assertGreater(team, -1, 'layout 仍要引入 team.js')
        self.assertLess(core, team, 'core 必须在 team.js 之前（window.LC 先就绪）')
        head_end = text.find('</head>')
        self.assertLess(core, head_end, 'core/team.js 放在 <head> 里才能保证页面脚本后执行')
        self.assertIn('t-foreach="lc_nav"', text, '导航必须按权限循环渲染')

    def test_core_avoids_dangerous_constructs(self):
        text = strip_js_comments((JS_DIR / 'workflow_core.js').read_text(encoding='utf-8'))
        for pattern in FORBIDDEN_JS_COMMON:
            with self.subTest(pattern=pattern):
                self.assertIsNone(re.search(pattern, text),
                                  'workflow_core.js 出现被禁写法：%s' % pattern)

    def test_page_scripts_avoid_dangerous_constructs(self):
        for path in sorted(PAGES_DIR.glob('*.js')):
            text = strip_js_comments(path.read_text(encoding='utf-8'))
            for pattern in FORBIDDEN_JS_COMMON + FORBIDDEN_JS_PAGE_ONLY:
                with self.subTest(file=path.name, pattern=pattern):
                    self.assertIsNone(re.search(pattern, text),
                                      '%s 出现被禁写法：%s（写操作必须走 LC.rpc / LC.submit）'
                                      % (path.name, pattern))


class PageJavascriptWiringTest(unittest.TestCase):
    """页面脚本与外壳登记必须对得上（否则运行期 404 或静默不执行）。"""

    def setUp(self):
        self.specs = module_literal(MOD / 'controllers' / 'workflow_pages.py', 'PAGE_SPECS')
        self.endpoints = module_literal(MOD / 'controllers' / 'common.py', 'WORKFLOW_ENDPOINTS')

    def test_register_page_id_matches_filename(self):
        for path in sorted(PAGES_DIR.glob('*.js')):
            text = strip_js_comments(path.read_text(encoding='utf-8'))
            match = re.search(r"LC\.register\(\s*'([a-z_]+)'", text)
            with self.subTest(file=path.name):
                self.assertIsNotNone(match, '%s 没有 LC.register(...)' % path.name)
                self.assertEqual(match.group(1), path.stem,
                                 '%s 注册的页面 id 与文件名不一致（外壳按 page_id 选脚本）'
                                 % path.name)
                self.assertIn(path.stem, self.specs,
                              '%s 对应的 page id 不在 PAGE_SPECS 里' % path.name)

    def test_used_endpoints_are_registered(self):
        used = {}
        for path in sorted(PAGES_DIR.glob('*.js')):
            text = strip_js_comments(path.read_text(encoding='utf-8'))
            names = set(re.findall(r"LC\.rpc\(\s*'([A-Za-z]+)'", text))
            names |= set(re.findall(r"endpoint:\s*'([A-Za-z]+)'", text))
            for name in names:
                used.setdefault(name, []).append(path.name)
        missing = {name: files for name, files in used.items() if name not in self.endpoints}
        self.assertFalse(missing, '页面用了未登记的端点 key：%s（T0 需加进 WORKFLOW_ENDPOINTS）' % missing)

    def test_endpoint_paths_are_site_relative(self):
        for key, value in self.endpoints.items():
            with self.subTest(endpoint=key):
                self.assertTrue(value.startswith('/'), '%s 必须站内相对路径' % key)
                self.assertFalse(value.startswith('//'), '%s 不能是协议相对 URL' % key)
                self.assertNotIn('http', value.lower(), '%s 不能写绝对 origin' % key)

    def test_labels_pdf_is_a_form_endpoint_not_jsonrpc(self):
        # 契约：PDF 走表单 POST + CSRF，不能走 LC.rpc（JSON-RPC）
        pages_text = ''.join(
            strip_js_comments(path.read_text(encoding='utf-8'))
            for path in PAGES_DIR.glob('*.js'))
        self.assertNotIn("LC.rpc('labelsPdf'", pages_text,
                         'PDF 必须用表单 POST，不能当 JSON-RPC 调用')


class SessionPermissionTest(unittest.TestCase):
    """会话接口必须暴露契约要求的权限位（页面靠它隐藏入口）。"""

    def permission_keys(self):
        source = read('controllers', 'api.py')
        start = source.index('payload_perms = {')
        depth = 0
        end = start
        for index in range(start, len(source)):
            char = source[index]
            if char == '{':
                depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0:
                    end = index + 1
                    break
        block = source[start:end]
        return set(re.findall(r"'([a-z_]+)'\s*:", block))

    def test_contract_permissions_present(self):
        keys = self.permission_keys()
        for name in CONTRACT_PERMISSIONS:
            with self.subTest(permission=name):
                self.assertIn(name, keys, '会话接口缺少权限位 %s' % name)

    def test_anonymous_permissions_default_to_false(self):
        source = read('controllers', 'api.py')
        for name in ('can_receipt', 'can_issue', 'can_return',
                     'can_manage_locations', 'can_manage_members'):
            with self.subTest(permission=name):
                self.assertIn("'%s': bool(perms.get('%s'))" % (name, name), source,
                              '%s 必须由服务端权限位派生，不能写死 True' % name)


if __name__ == '__main__':
    unittest.main()
