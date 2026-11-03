# -*- coding: utf-8 -*-
"""旧入口迁移验收：旧 GET 白名单映射 + 菜单改指（方案 §2.3 / §2.6）。

覆盖（每条都断言服务端事实，不信前端提示）：
  1. 白名单形状：只登记矩阵中迁移类入口，路径唯一、目标在站内、need 合法；
  2. 上下文白名单：bag_id/issue_line_id/category_id 必须是正整数，item_key 必须同形，
     其它参数一律丢弃，不原样透传；
  3. 无开放重定向：协议相对、绝对 URL、反斜杠、.. 段全部拒绝；
  4. 目标页必须真的已注册（ir.http._match），避免映射到 404；
  5. 权限顺序：匿名 -> 登录引导；无角色 -> 403；有权 -> 303；POST 不跳转；
  6. 菜单改指：日常菜单 action 指向 act_url，原 act_window/act_url 记录仍在，
     保留原生的入口（请求记账/分类/导入/库存流水）类型不变。

写域约定：本文件需由 Lead 登记到 `tests/__init__.py` 才会被加载。
集成项（主实施负责）：`controllers/__init__.py` 加 `legacy_entries`、
`__manifest__.py` 的 data 加 `views/legacy_entry_menu.xml`。
未集成时 HTTP / 菜单用例自动 skip，并明确说明是「未集成」而不是「通过」。
"""
import os
import unittest

try:
    import odoo  # noqa: F401
except ImportError as exc:  # 本机纯 Python 环境：整模块跳过
    raise unittest.SkipTest('需要 Odoo 19 运行时（本机未安装）：%s' % exc) from exc

from odoo.tests import HttpCase, TransactionCase, tagged

_HERE = os.path.dirname(os.path.abspath(__file__))
_ADDON = os.path.dirname(_HERE)


def _read_addon_file(relative):
    try:
        with open(os.path.join(_ADDON, relative), encoding='utf-8') as handle:
            return handle.read()
    except OSError:
        return ''


def _controller_wired():
    """controllers/__init__.py 是否已登记 legacy_entries（主实施集成项）。"""
    return 'legacy_entries' in _read_addon_file('controllers/__init__.py')


def _xml_wired():
    """__manifest__.py 的 data 是否已包含 views/legacy_entry_menu.xml（主实施集成项）。"""
    return 'legacy_entry_menu.xml' in _read_addon_file('__manifest__.py')


def _rules():
    from odoo.addons.lab_team_web.controllers import legacy_entries
    return legacy_entries


#: 目标页集合（与 workflow_pages.py / pages.py 的已注册路由一一对应）
KNOWN_PAGES = {
    '/team/lab',
    '/team/scan',
    '/team/lab/receipts',
    '/team/lab/bags',
    '/team/lab/issues',
    '/team/lab/labels',
    '/team/lab/locations',
    '/team/lab/location-mappings',
    '/team/lab/history',
    '/team/lab/materials',
}

#: 菜单改指期望（方案 §2.6 逐菜单落点）
MENU_TARGETS = {
    'lab_inventory.menu_lab_root': '/team/lab',
    'lab_catalog.menu_lab_unified_catalog': '/team/lab',
    'lab_workflow.menu_lab_scan': '/team/scan',
    'lab_workflow.menu_lab_issue_line': '/team/lab/issues',
    'lab_workflow.menu_lab_bag': '/team/lab/bags',
    'lab_workflow.menu_lab_operation_list': '/team/lab/history',
    'lab_workflow.menu_lab_location': '/team/lab/locations',
    'lab_workflow.menu_lab_labels': '/team/lab/labels',
    'lab_inventory.menu_lab_product': '/team/lab/materials',
    'lab_inventory.menu_lab_location': '/team/lab/locations',
    'lab_inventory.menu_lab_mapping': '/team/lab/location-mappings',
    'lab_catalog.menu_lab_catalog_binding': '/team/lab/materials',
}

#: 刻意保留原生的入口（方式 C）：不能出现在 GET 白名单里，菜单也不能被改成 act_url
NATIVE_ONLY = (
    'lab_workflow.action_lab_request_log',
    'lab_catalog.view_lab_catalog_category_action',
    'lab_catalog.view_lab_catalog_import_run_action',
    'lab_inventory.action_lab_move',
)


@tagged('post_install', '-at_install')
class LabTeamWebLegacyEntryRulesTest(TransactionCase):
    """纯规则层：白名单、上下文、无开放重定向、目标已注册。"""

    def test_whitelist_shape(self):
        rules = _rules()
        seen_paths = set()
        for xmlid, entry in rules.LEGACY_ACTIONS.items():
            self.assertEqual(xmlid, entry['xmlid'])
            self.assertIn(entry['need'], (rules.NEED_LAB, rules.NEED_CATALOG,
                                          rules.NEED_MANAGER), xmlid)
            self.assertIn(entry['target'], KNOWN_PAGES, xmlid)
            self.assertTrue(rules.is_safe_target(entry['target']), xmlid)
            path = rules.legacy_route(xmlid)
            self.assertTrue(path.startswith('/odoo/action-'), path)
            self.assertNotIn(path, seen_paths, '旧入口路径重复：%s' % path)
            seen_paths.add(path)
            allowed = set(rules.INT_CONTEXT_KEYS) | set(rules.KEY_CONTEXT_KEYS)
            self.assertTrue(set(entry['context']) <= allowed, xmlid)

    def test_native_only_entries_not_mapped(self):
        rules = _rules()
        for xmlid in NATIVE_ONLY:
            self.assertNotIn(xmlid, rules.LEGACY_ACTIONS,
                             '保留原生的入口不得进入旧 GET 白名单：%s' % xmlid)

    def test_targets_are_registered_routes(self):
        """目标页必须在当前版本的 routing map 里真实匹配到 GET。

        不能用 env['ir.http']._match()——它依赖已绑定的 request，
        在 TransactionCase 里会抛 RuntimeError: object unbound（本轮实测），
        那是测试写法问题，不是路由缺失。这里直接对 registry 的 routing map
        做 werkzeug 匹配，等价于「当前部署版本是否注册了该 GET 路由」。
        """
        rules = _rules()
        adapter = self.env['ir.http'].routing_map().bind('127.0.0.1')
        for xmlid, entry in rules.LEGACY_ACTIONS.items():
            path = entry['target'].split('?', 1)[0]
            if entry.get('bag_detail'):
                path = '%s/1' % path
            try:
                endpoint, _args = adapter.match(path, method='GET')
            except Exception as exc:  # noqa: BLE001
                self.fail('目标页未注册（%s -> %s）：%s' % (xmlid, path, exc))
                continue
            self.assertTrue(endpoint, '目标页匹配到空端点：%s' % xmlid)

    def test_context_whitelist(self):
        rules = _rules()
        kept = rules.sanitize_context({
            'bag_id': '12',
            'issue_line_id': '3',
            'category_id': '7',
            'item_key': 'C12345-abc',
            'unknown': 'x',
            'q': 'abc',
        })
        self.assertEqual(kept, {'bag_id': 12, 'issue_line_id': 3,
                                'category_id': 7, 'item_key': 'C12345-abc'})
        # 非法值一律丢弃，不做「尽力解析」
        dropped = rules.sanitize_context({
            'bag_id': 'abc', 'issue_line_id': '-1', 'category_id': '0',
            'item_key': '../etc/passwd',
        })
        self.assertEqual(dropped, {})
        # 超长/含空白的 item_key 也不接受
        self.assertEqual(rules.sanitize_context({'item_key': 'A' * 65}), {})
        self.assertEqual(rules.sanitize_context({'item_key': 'a b'}), {})

    def test_target_url_builds_only_whitelisted_parts(self):
        rules = _rules()
        bag_entry = rules.LEGACY_ACTIONS['lab_workflow.action_lab_bag']
        self.assertEqual(
            rules.target_url(bag_entry, {'bag_id': 42, 'q': 'x'}),
            '/team/lab/bags/42')
        issues_entry = rules.LEGACY_ACTIONS['lab_workflow.action_lab_issue_line']
        self.assertEqual(
            rules.target_url(issues_entry, {'bag_id': 5, 'item_key': 'C1'}),
            '/team/lab/issues?bag_id=5&item_key=C1')
        catalog_entry = rules.LEGACY_ACTIONS['lab_catalog.action_lab_unified_catalog_client']
        self.assertEqual(
            rules.target_url(catalog_entry, {'category_id': 9}),
            '/team/lab?category_id=9')

    def test_no_open_redirect(self):
        rules = _rules()
        for bad in ('//evil.example/x', 'https://evil.example', '/team/../x',
                    '/\\evil.example', '/team/\r\nSet-Cookie: x', '',
                    'team/lab', '/team/lab/..%2f..'):
            self.assertFalse(rules.is_safe_target(bad), bad)
        for good in ('/team/lab', '/team/scan', '/team/lab/bags/12',
                     '/team/lab/issues?bag_id=5'):
            self.assertTrue(rules.is_safe_target(good), good)


@tagged('post_install', '-at_install')
@unittest.skipUnless(_xml_wired(), 'views/legacy_entry_menu.xml 尚未加入 manifest data（主实施集成项，未部署≠已迁移）')
class LabTeamWebLegacyEntryMenuTest(TransactionCase):
    """菜单改指：日常入口指向 act_url；原动作与保留原生的入口都不动。"""

    def test_menu_actions_point_to_own_pages(self):
        for xmlid, url in MENU_TARGETS.items():
            menu = self.env.ref(xmlid)
            action = menu.action
            self.assertTrue(action, '%s 没有 action' % xmlid)
            self.assertEqual(action.type, 'ir.actions.act_url',
                             '%s 仍指向 %s' % (xmlid, action.type))
            self.assertEqual(action.url, url, xmlid)

    def test_original_actions_preserved(self):
        # 旧动作记录必须还在：兼容层、管理员维护与回退都要引用
        self.assertEqual(self.env.ref('lab_workflow.action_lab_scan_console').type,
                         'ir.actions.act_url')
        self.assertEqual(self.env.ref('lab_workflow.action_lab_bag').type,
                         'ir.actions.act_window')
        self.assertEqual(self.env.ref('lab_workflow.action_lab_label_open').type,
                         'ir.actions.act_window')
        self.assertEqual(self.env.ref('lab_catalog.action_lab_unified_catalog_client').type,
                         'ir.actions.client')

    def test_native_entries_untouched(self):
        expected = {
            'lab_workflow.menu_lab_request_log': 'ir.actions.act_window',
            'lab_catalog.menu_lab_catalog_index': 'ir.actions.act_window',
            'lab_catalog.menu_lab_catalog_category': 'ir.actions.act_window',
            'lab_catalog.menu_lab_catalog_import_run': 'ir.actions.act_window',
            'lab_inventory.menu_lab_move': 'ir.actions.act_window',
        }
        for xmlid, action_type in expected.items():
            action = self.env.ref(xmlid).action
            self.assertEqual(action.type, action_type, xmlid)

    def test_menu_visibility_not_narrowed(self):
        # 改指只动 action：原有 groups 不能因此缩小
        scan = self.env.ref('lab_workflow.menu_lab_scan')
        self.assertIn(self.env.ref('lab_workflow.group_lab_operator'),
                      scan.group_ids)
        labels = self.env.ref('lab_workflow.menu_lab_labels')
        self.assertIn(self.env.ref('lab_workflow.group_lab_manager'),
                      labels.group_ids)

    def _assert_uninstall_restores_once(self):
        """卸载还原：仍是本模块改指的菜单回到原模块 action。"""
        from odoo.addons.lab_team_web import hooks

        menu = self.env.ref('lab_workflow.menu_lab_scan')
        ours = self.env.ref('lab_team_web.action_legacy_scan')
        origin = self.env.ref('lab_workflow.action_lab_scan_console')
        self.assertEqual(menu.action, ours)

        restored, skipped = hooks.restore_menu_actions(self.env)
        self.assertGreaterEqual(restored, len(hooks.MENU_REWIRES) - 1,
                                '应至少还原除空 action 之外的全部菜单')
        self.assertEqual(menu.action, origin)
        self.env.cr.flush()
        # 还原是幂等的：再跑一次不会把 origin 又当成"我们的"改掉
        again, _ = hooks.restore_menu_actions(self.env)
        self.assertEqual(again, 0)
        self.assertEqual(menu.action, origin)
        # 还原后可重新改指（升级路径不会把菜单留在旧台）
        self.env.cr.execute(
            "UPDATE ir_ui_menu SET action = %s WHERE id = %s",
            ('ir.actions.act_url,%d' % ours.id, menu.id))
        menu.invalidate_recordset(['action'])
        self.assertEqual(menu.action, ours)
        hooks.restore_menu_actions(self.env)
        self.assertEqual(menu.action, origin)
        return restored, skipped

    def test_uninstall_restores_original_action(self):
        self._assert_uninstall_restores_once()

    def test_uninstall_keeps_custom_redirect(self):
        """用户/其它模块把菜单改到别处时，卸载不得覆盖。"""
        from odoo.addons.lab_team_web import hooks

        menu = self.env.ref('lab_inventory.menu_lab_mapping')
        custom = self.env.ref('lab_inventory.action_lab_move')
        menu.write({'action': 'ir.actions.act_window,%d' % custom.id})
        hooks.restore_menu_actions(self.env)
        self.assertEqual(menu.action, custom)
        # 复原现场，避免污染同库其它用例
        menu.write({'action': 'ir.actions.act_url,%d'
                    % self.env.ref('lab_team_web.action_legacy_mappings').id})


@tagged('post_install', '-at_install')
@unittest.skipUnless(_controller_wired(), 'controllers/__init__.py 尚未登记 legacy_entries（主实施集成项）')
class LabTeamWebLegacyEntryHttpTest(HttpCase):
    """HTTP：匿名登录引导 / 无权 403 / 有权 303 / 上下文保留 / POST 不跳转。

    断言看**首跳**（303 的 Location 才是兼容层的契约），跟随重定向后用
    response.history[0] 取；不传 allow_redirects，避免不同 Odoo 小版本的
    url_open 签名差异把用例变成假失败。
    """

    PASSWORD = 'legacy-entry-test-2026'
    LOGINS = {
        'norole': 'legacy_entry_norole',
        'catalog': 'legacy_entry_catalog',
        'lab_user': 'legacy_entry_labuser',
        'operator': 'legacy_entry_operator',
        'manager': 'legacy_entry_manager',
    }
    GROUPS = {
        'norole': ['base.group_user'],
        'catalog': ['base.group_user', 'lab_catalog.group_lab_catalog_user'],
        'lab_user': ['base.group_user', 'lab_catalog.group_lab_catalog_user',
                     'lab_workflow.group_lab_user'],
        'operator': ['base.group_user', 'lab_catalog.group_lab_catalog_user',
                     'lab_workflow.group_lab_user', 'lab_workflow.group_lab_operator'],
        'manager': ['base.group_user', 'lab_catalog.group_lab_catalog_user',
                    'lab_workflow.group_lab_user', 'lab_workflow.group_lab_operator',
                    'lab_workflow.group_lab_manager'],
    }

    @classmethod
    def _raw_db_name(cls):
        from odoo.tools import config
        name = ''
        try:
            name = config.get('db_name') or ''
        except Exception:  # noqa: BLE001
            name = ''
        if isinstance(name, (list, tuple)):
            name = name[0] if name else ''
        name = str(name).split(',')[0].strip()
        if not name:
            name = (os.environ.get('DB_NAME')
                    or os.environ.get('PGDATABASE') or '').strip()
        return name

    @classmethod
    def setUpClass(cls):
        cls.password = cls.PASSWORD
        cls.logins = dict(cls.LOGINS)
        cls._bootstrap_fixtures()   # 必须在 super() 之前提交（R4）
        super().setUpClass()
        missing = cls.env['res.users'].search_count(
            [('login', 'in', list(cls.logins.values()))])
        if missing < len(cls.logins):
            raise AssertionError('fixture 在类测试快照中不可见（%d/%d）'
                                 % (missing, len(cls.logins)))

    @classmethod
    def _bootstrap_fixtures(cls):
        from odoo import api, sql_db
        dbname = cls._raw_db_name()
        if not dbname:
            raise AssertionError('无法确定测试库名，请用 -d 指定专用测试库')
        cr = sql_db.db_connect(dbname).cursor()
        env = api.Environment(cr, 1, {})
        try:
            env['ir.config_parameter'].sudo().set_param(
                'lab_team_web.management_host', '')
            env['ir.config_parameter'].sudo().set_param(
                'lab_team_web.root_aliases', '1')
            # 幂等：HttpCase 的 fixture 必须在 super() 之前提交（R4），提交后
            # 同一测试库重复跑会撞 res_users_login_key。这里先按 login 复用，
            # 缺才 create，并每次都把密码/组写回一致状态（可重复执行）。
            for role, xmlids in cls.GROUPS.items():
                login = cls.LOGINS[role]
                groups = [(6, 0, [env.ref(x).id for x in xmlids])]
                existing = env['res.users'].sudo().with_context(
                    active_test=False).search([('login', '=', login)], limit=1)
                if existing:
                    existing.with_context(no_reset_password=True).write({
                        'name': login,
                        'email': '%s@example.invalid' % login,
                        'password': cls.PASSWORD,
                        'active': True,
                        'company_id': env.company.id,
                        'company_ids': [(6, 0, [env.company.id])],
                        'group_ids': groups,
                    })
                else:
                    env['res.users'].with_context(no_reset_password=True).create({
                        'name': login,
                        'login': login,
                        'email': '%s@example.invalid' % login,
                        'password': cls.PASSWORD,
                        'company_id': env.company.id,
                        'company_ids': [(6, 0, [env.company.id])],
                        'group_ids': groups,
                    })
            cr.commit()
        except Exception:
            cr.rollback()
            raise
        finally:
            cr.close()

    # ------------------------------------------------------------------ helpers
    def _login(self, role):
        self.authenticate(self.logins[role], self.password)

    def _open(self, path, data=None):
        """打开并跟随重定向，返回 (首跳响应, 最终响应)。"""
        response = self.url_open(path, data=data) if data is not None else self.url_open(path)
        history = getattr(response, 'history', None) or []
        return (history[0] if history else response), response

    def _location(self, first):
        headers = first.headers
        return headers.get('Location') or headers.get('location') or ''

    def _anonymous_open(self, path):
        """清空 cookie 后请求，确保真的是匿名（用例结束后恢复会话）。"""
        saved = []
        try:
            saved = list(self.session.cookies)
            self.session.cookies.clear()
        except Exception:  # noqa: BLE001 - 取不到 cookie 时按原样请求
            saved = []
        try:
            return self._open(path)
        finally:
            for cookie in saved:
                try:
                    self.session.cookies.set_cookie(cookie)
                except Exception:  # noqa: BLE001
                    pass

    # ------------------------------------------------------------------ tests
    def test_anonymous_goes_to_login_not_old_page(self):
        first, _final = self._anonymous_open(
            '/odoo/action-lab_workflow.action_lab_scan_console')
        self.assertEqual(first.status_code, 303)
        location = self._location(first)
        self.assertIn('/team/login', location)
        self.assertIn('next=', location)
        self.assertNotIn('/lab/scan', location)

    def test_no_lab_role_is_403(self):
        self._login('norole')
        first, final = self._open('/odoo/action-lab_workflow.action_lab_scan_console')
        self.assertEqual(first.status_code, 403)
        self.assertNotIn('Location', first.headers)
        self.assertIn('没有访问权限', final.text)

    def test_operator_scan_goes_to_own_page(self):
        self._login('operator')
        first, _final = self._open('/odoo/action-lab_workflow.action_lab_scan_console')
        self.assertEqual(first.status_code, 303)
        self.assertTrue(self._location(first).endswith('/team/scan'),
                        self._location(first))

    def test_bag_context_becomes_detail_path(self):
        self._login('lab_user')
        first, _final = self._open('/odoo/action-lab_workflow.action_lab_bag?bag_id=12')
        self.assertEqual(first.status_code, 303)
        self.assertTrue(self._location(first).endswith('/team/lab/bags/12'),
                        self._location(first))

    def test_invalid_context_is_dropped(self):
        self._login('lab_user')
        first, _final = self._open(
            '/odoo/action-lab_workflow.action_lab_bag?bag_id=abc&item_key=../x')
        self.assertEqual(first.status_code, 303)
        self.assertTrue(self._location(first).endswith('/team/lab/bags'),
                        self._location(first))

    def test_mapping_needs_manager(self):
        self._login('lab_user')
        first, _final = self._open('/odoo/action-lab_inventory.action_lab_mapping')
        self.assertEqual(first.status_code, 403)
        self._login('manager')
        first, _final = self._open('/odoo/action-lab_inventory.action_lab_mapping')
        self.assertEqual(first.status_code, 303)
        self.assertTrue(self._location(first).endswith('/team/lab/location-mappings'),
                        self._location(first))

    def test_catalog_entry_requires_catalog_role(self):
        # lab_workflow 组 imply lab_catalog 组，所以现实里没有「有 lab 无 catalog」
        # 的账号；这里用「完全无角色」验证 catalog 门槛确实生效。
        self._login('norole')
        first, _final = self._open('/odoo/action-lab_inventory.action_lab_product')
        self.assertEqual(first.status_code, 403)
        self._login('catalog')
        first, _final = self._open('/odoo/action-lab_inventory.action_lab_product')
        self.assertEqual(first.status_code, 303)
        self.assertTrue(self._location(first).endswith('/team/lab/materials'),
                        self._location(first))

    def test_native_only_action_is_not_redirected(self):
        self._login('manager')
        first, _final = self._open('/odoo/action-lab_workflow.action_lab_request_log')
        self.assertNotEqual(first.status_code, 303,
                            '保留原生的入口不得被兼容层改道')

    def test_post_is_not_redirected(self):
        self._login('operator')
        response = self.url_open('/odoo/action-lab_workflow.action_lab_scan_console',
                                 method='POST')
        self.assertEqual(response.status_code, 405)
        self.assertFalse(getattr(response, 'history', None),
                         '旧写入口不得被 307/308 重放')
