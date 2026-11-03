#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""静态校验旧入口迁移层（方案 §2.3 旧 GET 兼容 + §2.6 菜单改指）。

不需要 Odoo 运行时：注入最小 stub 后按文件加载控制器，只校验声明与纯函数：
  1. 13 条 `/odoo/action-<xmlid>` 静态路由：路径由白名单生成、只 GET、auth=public、
     website/sitemap 关闭、不含通配与 `/lab/scan`；
  2. 白名单形状：need 合法、目标在站内、上下文键在白名单内、保留原生的入口不在表内；
  3. 上下文与跳转安全：整数/编码校验、开放重定向拒绝；
  4. 目标页漂移：每个目标必须能在 workflow_pages.py / pages.py 的路由字面量里匹配到；
  5. 菜单 XML：9 个 act_url 的 url 是站内目标页、12 个菜单只覆盖 action、保留原生入口不动、
     标签向导回退菜单存在且限管理员；
  6. 集成状态（`controllers/__init__.py`、`__manifest__.py`、`tests/__init__.py`）只 WARN：
     集成由主实施统一做，未集成不等于已迁移，也不该让本脚本静默通过。

真实 HTTP 行为（303/403/405 顺序、登录引导、上下文落到 URL）由
tests/test_legacy_entries.py 的 HttpCase 覆盖，本脚本不替代它。

用法：python tools/legacy_entry_rules.py [--quiet]
退出码：0 = 无失败（WARN 不影响）；1 = 有失败。
"""

import importlib.util
import re
import sys
import types
from pathlib import Path
from xml.etree import ElementTree as ET

REPO_ROOT = Path(__file__).resolve().parents[1]
ODOO_ADDONS = REPO_ROOT / 'server' / 'ubuntu22.04' / 'odoo_addons'
ADDON = ODOO_ADDONS / 'lab_team_web'
CONTROLLER = ADDON / 'controllers' / 'legacy_entries.py'
MENU_XML = ADDON / 'views' / 'legacy_entry_menu.xml'
WORKFLOW_PAGES = ADDON / 'controllers' / 'workflow_pages.py'
PAGES = ADDON / 'controllers' / 'pages.py'
CONTROLLERS_INIT = ADDON / 'controllers' / '__init__.py'
MANIFEST = ADDON / '__manifest__.py'
TESTS_INIT = ADDON / 'tests' / '__init__.py'

#: 目标页（与 workflow_pages.py / pages.py 的注册路由一一对应）
KNOWN_PAGES = (
    '/team/lab', '/team/scan', '/team/lab/receipts', '/team/lab/bags',
    '/team/lab/issues', '/team/lab/labels', '/team/lab/locations',
    '/team/lab/location-mappings', '/team/lab/history', '/team/lab/materials',
)

#: 菜单 xmlid -> 期望 act_url（方案 §2.6 逐菜单落点，方式 A）
MENU_TARGETS = {
    'lab_inventory.menu_lab_root': 'action_legacy_catalog',
    'lab_catalog.menu_lab_unified_catalog': 'action_legacy_catalog',
    'lab_workflow.menu_lab_scan': 'action_legacy_scan',
    'lab_workflow.menu_lab_issue_line': 'action_legacy_issues',
    'lab_workflow.menu_lab_bag': 'action_legacy_bags',
    'lab_workflow.menu_lab_operation_list': 'action_legacy_history',
    'lab_workflow.menu_lab_location': 'action_legacy_locations',
    'lab_workflow.menu_lab_labels': 'action_legacy_labels',
    'lab_inventory.menu_lab_product': 'action_legacy_materials',
    'lab_inventory.menu_lab_location': 'action_legacy_locations',
    'lab_inventory.menu_lab_mapping': 'action_legacy_mappings',
    'lab_catalog.menu_lab_catalog_binding': 'action_legacy_materials',
}

#: 刻意保留原生（方式 C）：不得出现在 GET 白名单，菜单也不得被改指
NATIVE_ONLY = (
    'lab_workflow.action_lab_request_log',
    'lab_catalog.view_lab_catalog_category_action',
    'lab_catalog.view_lab_catalog_import_run_action',
    'lab_inventory.action_lab_move',
)

FAILURES = []
WARNINGS = []
CHECKS = [0]


def check(condition, message):
    CHECKS[0] += 1
    if not condition:
        FAILURES.append(message)
    return bool(condition)


def warn(message):
    WARNINGS.append(message)


def install_stubs():
    """注入最小 odoo/werkzeug/相对导入包，供按文件加载控制器。"""
    odoo = types.ModuleType('odoo')
    http = types.ModuleType('odoo.http')

    class Controller(object):
        pass

    def route(*rargs, **rkwargs):
        def decorator(func):
            func.lc_route = {'args': rargs, 'kwargs': rkwargs}
            return func
        return decorator

    class DummyRequest(object):
        def __getattr__(self, name):
            raise RuntimeError('静态校验不应访问 request.%s' % name)

    http.Controller = Controller
    http.route = route
    http.request = DummyRequest()
    odoo.http = http
    sys.modules['odoo'] = odoo
    sys.modules['odoo.http'] = http

    try:
        import werkzeug.utils  # noqa: F401
    except ImportError:
        werkzeug = types.ModuleType('werkzeug')
        utils = types.ModuleType('werkzeug.utils')

        def redirect(url, code=302):
            return ('redirect', url, code)

        utils.redirect = redirect
        werkzeug.utils = utils
        sys.modules['werkzeug'] = werkzeug
        sys.modules['werkzeug.utils'] = utils

    package = types.ModuleType('lc_probe')
    package.__path__ = [str(CONTROLLER.parent)]
    sys.modules['lc_probe'] = package
    common = types.ModuleType('lc_probe.common')
    for name in ('is_anonymous', 'has_lab_access', 'has_catalog_access',
                 'is_lab_manager', 'has_lab_operator', 'workflow_base',
                 'redirect_to_login', 'render_denied', 'render'):
        setattr(common, name, lambda *a, **k: None)
    common.WORKFLOW_DENIED_TEXT = {}
    common.PARAM_ROOT_ALIASES = 'lab_team_web.root_aliases'
    sys.modules['lc_probe.common'] = common


def load_rules():
    spec = importlib.util.spec_from_file_location('lc_probe.legacy_entries', str(CONTROLLER))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def route_patterns():
    patterns = []
    for path in (WORKFLOW_PAGES, PAGES):
        if not path.is_file():
            continue
        text = path.read_text(encoding='utf-8')
        for match in re.finditer(r"""['"](/team[^'"]*)['"]""", text):
            raw = match.group(1)
            patterns.append((path.name, raw,
                             re.compile('^' + re.sub(r'<[^>]+>', '[^/]+', raw) + '$')))
    return patterns


def xmlid_declared(xmlid):
    """在对应模块的 XML 里找 id="local"，确认白名单没有引用不存在的记录。"""
    module, _, local = xmlid.partition('.')
    module_dir = ODOO_ADDONS / module
    if not module_dir.is_dir():
        return False
    needle = 'id="%s"' % local
    for path in module_dir.rglob('*.xml'):
        try:
            if needle in path.read_text(encoding='utf-8'):
                return True
        except OSError:
            continue
    return False


def parse_menu_xml():
    tree = ET.parse(str(MENU_XML))
    records = {}
    menuitems = {}
    for record in tree.getroot().iter('record'):
        rid = record.get('id')
        fields = {}
        for field in record.findall('field'):
            fields[field.get('name')] = {
                'text': (field.text or '').strip(),
                'ref': field.get('ref'),
            }
        records[rid] = {'model': record.get('model'), 'fields': fields}
    for item in tree.getroot().iter('menuitem'):
        menuitems[item.get('id')] = dict(item.attrib)
    return records, menuitems


def main():
    try:                       # Windows 控制台默认 GBK，避免中文 WARN/FAIL 变成乱码
        sys.stdout.reconfigure(encoding='utf-8')
    except (AttributeError, ValueError):
        pass
    del FAILURES[:]           # 同一进程内重复调用时从干净状态开始
    del WARNINGS[:]
    CHECKS[0] = 0
    quiet = '--quiet' in sys.argv[1:]

    for path in (CONTROLLER, MENU_XML, WORKFLOW_PAGES, PAGES):
        if not check(path.is_file(), '缺少文件：%s' % path):
            print('FAIL: 缺少文件：%s' % path)
            return 1

    install_stubs()
    try:
        rules = load_rules()
    except Exception as exc:  # noqa: BLE001
        print('FAIL: 控制器无法按文件加载（语法/导入错误？）：%s: %s'
              % (type(exc).__name__, exc))
        return 1

    # ---- 1. 白名单形状 ------------------------------------------------
    whitelist = rules.LEGACY_ACTIONS
    check(len(whitelist) == 13, '白名单应为 13 条，实际 %d' % len(whitelist))
    allowed_need = (rules.NEED_LAB, rules.NEED_CATALOG, rules.NEED_MANAGER)
    allowed_ctx = set(rules.INT_CONTEXT_KEYS) | set(rules.KEY_CONTEXT_KEYS)
    for xmlid, entry in whitelist.items():
        check(entry.get('xmlid') == xmlid, '%s: entry.xmlid 不一致' % xmlid)
        check(entry.get('need') in allowed_need, '%s: need 非法 %r' % (xmlid, entry.get('need')))
        check(entry.get('target') in KNOWN_PAGES, '%s: 目标不在已知页 %r'
              % (xmlid, entry.get('target')))
        check(rules.is_safe_target(entry.get('target') or ''), '%s: 目标未通过安全检查' % xmlid)
        check(set(entry.get('context') or ()) <= allowed_ctx,
              '%s: 上下文键越界 %r' % (xmlid, entry.get('context')))
        check(xmlid_declared(xmlid), '%s: 源码中找不到该记录声明（xmlid 拼写？）' % xmlid)
        if entry.get('bag_detail'):
            check(entry.get('target') == '/team/lab/bags',
                  '%s: bag_detail 只适用于库存袋详情' % xmlid)
    for xmlid in NATIVE_ONLY:
        check(xmlid not in whitelist, '保留原生的入口不得进入白名单：%s' % xmlid)
        check(xmlid_declared(xmlid), '保留原生的入口 xmlid 不存在：%s' % xmlid)

    # ---- 2. 路由声明 --------------------------------------------------
    controllers = [value for value in vars(rules).values()
                   if isinstance(value, type) and issubclass(value, rules.http.Controller)
                   and value is not rules.http.Controller]
    check(len(controllers) == 1, '应只有一个控制器类，实际 %d' % len(controllers))
    routes = {}
    if controllers:
        for name, attr in vars(controllers[0]).items():
            meta = getattr(attr, 'lc_route', None)
            if meta is None:
                continue
            path = meta['args'][0] if meta['args'] else meta['kwargs'].get('path')
            routes[path] = (name, meta['kwargs'])
    expected_paths = {rules.legacy_route(xmlid) for xmlid in whitelist}
    check(set(routes) == expected_paths,
          '路由集合与白名单不一致：多出 %s，缺少 %s'
          % (sorted(set(routes) - expected_paths), sorted(expected_paths - set(routes))))
    for path, (name, kwargs) in routes.items():
        check(kwargs.get('type') == 'http', '%s: type 应为 http' % path)
        check(kwargs.get('auth') == 'public', '%s: auth 应为 public' % path)
        check(kwargs.get('methods') == ['GET'], '%s: 只允许 GET，实际 %r'
              % (path, kwargs.get('methods')))
        check(kwargs.get('website') is False, '%s: website 应关闭' % path)
        check(kwargs.get('sitemap') is False, '%s: sitemap 应关闭' % path)
        check('<' not in path, '%s: 不允许动态路由段' % path)
        check(path != '/lab/scan', '不得重复注册 /lab/scan（由 lab_workflow 负责）')
    check('/lab/scan' not in routes, '不得重复注册 /lab/scan')

    # ---- 3. 上下文与跳转安全 -------------------------------------------
    check(rules.sanitize_context({'bag_id': '12', 'item_key': 'C1', 'x': 'y'})
          == {'bag_id': 12, 'item_key': 'C1'}, '上下文白名单未按预期过滤')
    for bad in ({'bag_id': 'abc'}, {'bag_id': '-1'}, {'bag_id': '0'},
                {'issue_line_id': '1.5'}, {'category_id': '99999999999'},
                {'item_key': '../etc/passwd'}, {'item_key': 'A' * 65},
                {'item_key': 'a b'}, {'item_key': ''}):
        check(rules.sanitize_context(bad) == {}, '非法上下文未被丢弃：%r' % bad)
    bag_entry = whitelist.get('lab_workflow.action_lab_bag')
    issues_entry = whitelist.get('lab_workflow.action_lab_issue_line')
    catalog_entry = whitelist.get('lab_catalog.action_lab_unified_catalog_client')
    if bag_entry:
        check(rules.target_url(bag_entry, {'bag_id': 42, 'q': 'x'})
              == '/team/lab/bags/42', '库存袋详情 URL 拼接错误')
    if issues_entry:
        check(rules.target_url(issues_entry, {'bag_id': 5, 'item_key': 'C1'})
              == '/team/lab/issues?bag_id=5&item_key=C1', '领用记录 URL 拼接错误')
    if catalog_entry:
        check(rules.target_url(catalog_entry, {'category_id': 9})
              == '/team/lab?category_id=9', '器件库 URL 拼接错误')
    for bad in ('//evil.example/x', 'https://evil.example', '/team/../x',
                '/\\evil.example', '/team/\r\nSet-Cookie: x', '',
                'team/lab', '/team/lab/..%2f..', '/team/lab%00'):
        check(not rules.is_safe_target(bad), '开放重定向未被拒绝：%r' % bad)
    for good in KNOWN_PAGES:
        check(rules.is_safe_target(good), '站内目标被误判不安全：%r' % good)

    # ---- 4. 目标页漂移 -------------------------------------------------
    patterns = route_patterns()
    check(len(patterns) >= 10, '未解析到足够的路由字面量（%d）' % len(patterns))
    for xmlid, entry in whitelist.items():
        target = entry['target']
        candidate = '%s/1' % target if entry.get('bag_detail') else target
        hits = [raw for _name, raw, pattern in patterns if pattern.match(candidate)]
        check(bool(hits), '%s: 目标页 %s 在 workflow_pages.py/pages.py 中未注册（漂移）'
              % (xmlid, candidate))

    # ---- 5. 菜单 XML ---------------------------------------------------
    try:
        records, menuitems = parse_menu_xml()
    except ET.ParseError as exc:
        print('FAIL: 菜单 XML 无法解析：%s' % exc)
        return 1
    act_urls = {rid: rec for rid, rec in records.items()
                if rec['model'] == 'ir.actions.act_url'}
    check(len(act_urls) == 9, 'act_url 应为 9 个，实际 %d' % len(act_urls))
    for rid, rec in act_urls.items():
        url = rec['fields'].get('url', {}).get('text', '')
        check(url in KNOWN_PAGES, '%s: act_url 目标不是已知页 %r' % (rid, url))
        check(rules.is_safe_target(url), '%s: act_url 目标未通过安全检查' % rid)
        check(rec['fields'].get('target', {}).get('text') == 'self',
              '%s: act_url target 应为 self' % rid)
    for xmlid, expected_ref in MENU_TARGETS.items():
        rec = records.get(xmlid)
        if not check(rec is not None, '菜单未被改指：%s' % xmlid):
            continue
        check(rec['model'] == 'ir.ui.menu', '%s: 记录模型应为 ir.ui.menu' % xmlid)
        fields = rec['fields']
        ref = fields.get('action', {}).get('ref') or ''
        check(ref.split('.')[-1] == expected_ref,
              '%s: action 应为 %s，实际 %r' % (xmlid, expected_ref, ref))
        check(set(fields) == {'action'}, '%s: 改指不应覆盖 groups/sequence 等字段（%s）'
              % (xmlid, sorted(fields)))
    for xmlid in ('lab_workflow.menu_lab_request_log', 'lab_catalog.menu_lab_catalog_index',
                  'lab_catalog.menu_lab_catalog_category',
                  'lab_catalog.menu_lab_catalog_import_run', 'lab_inventory.menu_lab_move'):
        check(xmlid not in records, '保留原生的菜单不应被覆盖：%s' % xmlid)
    wizard = menuitems.get('menu_legacy_label_wizard')
    if check(wizard is not None, '缺少标签向导回退菜单（方式 B）'):
        check(wizard.get('parent') == 'lab_workflow.menu_lab_config',
              '标签向导回退菜单父级错误：%r' % wizard.get('parent'))
        check(wizard.get('action') == 'lab_workflow.action_lab_label_open',
              '标签向导回退菜单 action 错误：%r' % wizard.get('action'))
        check('lab_workflow.group_lab_manager' in (wizard.get('groups') or ''),
              '标签向导回退菜单必须限管理员：%r' % wizard.get('groups'))

    # ---- 6. 集成状态（WARN，不判失败） ---------------------------------
    init_text = CONTROLLERS_INIT.read_text(encoding='utf-8') if CONTROLLERS_INIT.is_file() else ''
    if 'legacy_entries' not in init_text:
        warn('controllers/__init__.py 未登记 legacy_entries：路由当前不生效（主实施集成项）')
    manifest_text = MANIFEST.read_text(encoding='utf-8') if MANIFEST.is_file() else ''
    if 'legacy_entry_menu.xml' not in manifest_text:
        warn('__manifest__.py 的 data 未包含 views/legacy_entry_menu.xml：菜单改指未生效（主实施集成项）')
    tests_text = TESTS_INIT.read_text(encoding='utf-8') if TESTS_INIT.is_file() else ''
    if 'test_legacy_entries' not in tests_text:
        warn('tests/__init__.py 未登记 test_legacy_entries：验收用例不会被加载（主实施集成项）')

    if not quiet:
        for message in WARNINGS:
            print('WARN: %s' % message)
        for message in FAILURES:
            print('FAIL: %s' % message)
    print('checks=%d pass=%d fail=%d warn=%d'
          % (CHECKS[0], CHECKS[0] - len(FAILURES), len(FAILURES), len(WARNINGS)))
    return 1 if FAILURES else 0


if __name__ == '__main__':
    sys.exit(main())
