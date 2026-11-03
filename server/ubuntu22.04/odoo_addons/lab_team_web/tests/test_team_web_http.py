# -*- coding: utf-8 -*-
"""lab_team_web HTTP 契约测试（Odoo 19 HttpCase）。

本机没有 Odoo/PostgreSQL，因此本文件在导入阶段做一次环境探测：
缺少 odoo 时抛 unittest.SkipTest，让
    python -m unittest discover -s server/ubuntu22.04/odoo_addons/lab_team_web/tests -v
仍能完整执行纯 Python 的 test_paths.py（本模块只显示为 skipped）。

在 Odoo 19 隔离库中运行：
    odoo-bin --addons-path=<odoo>/addons,server/ubuntu22.04/odoo_addons \
        -d <isolated_test_db> -i lab_team_web --test-enable \
        --test-tags /lab_team_web:post_install --stop-after-init

覆盖契约见 maintenance/audit/team-web-phase1-test-plan.md 的 L2 矩阵。
数据依赖（某个 lcsc 编号是否已采集/有本地档案）不做硬编码断言。
"""
import json
import re
import unittest

try:
    import odoo  # noqa: F401
except ImportError as exc:
    raise unittest.SkipTest('需要 Odoo 19 运行时（本机未安装）：%s' % exc) from exc

from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class LabTeamWebHttpTest(HttpCase):
    """欢迎 / 登录 / 仓库 / 详情 / 会话接口 / CSRF 的 HTTP 端契约。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # 参数自给：避免测试库继承外部（如预览实例）留下的
        # management_host / root_aliases 状态导致基址与断言不一致。
        cls.env['ir.config_parameter'].sudo().set_param(
            'lab_team_web.management_host', '')
        cls.env['ir.config_parameter'].sudo().set_param(
            'lab_team_web.root_aliases', '1')
        cls.company = cls.env.company
        cls.password = 'team-web-test-2026'
        cls.no_role_login = 'team_web_no_role'
        cls.member_login = 'team_web_member'

        # 内部用户，但没有任何 lab_catalog / lab_workflow 组
        cls.no_role_user = cls._make_user(
            cls.no_role_login, ['base.group_user'])
        # 有仓库读取角色：器件库只读 + 实验室只读
        cls.member_user = cls._make_user(
            cls.member_login,
            ['base.group_user',
             'lab_catalog.group_lab_catalog_user',
             'lab_workflow.group_lab_user'])

        # 确定存在的本地器件夹具：详情流程必须能真正渲染出它的字段，
        # 不能再用"200 或 404 都可接受"来糊弄。只在隔离测试库创建。
        cls.fixture_name = '团队仓库测试器件 ZZT-001'
        cls.fixture_tmpl = cls.env['product.template'].create({
            'name': cls.fixture_name,
            'type': 'consu',
            'lab_mpn': 'ZZT-001',
            'lab_brand': '测试品牌',
        })
        cls.fixture_key = 'lab:%d' % cls.fixture_tmpl.id

    @classmethod
    def _make_user(cls, login, group_xmlids):
        group_ids = [cls.env.ref(xmlid).id for xmlid in group_xmlids]
        return cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': login,
            'login': login,
            'email': '%s@example.invalid' % login,
            'password': cls.password,
            'company_id': cls.company.id,
            'company_ids': [(6, 0, [cls.company.id])],
            'group_ids': [(6, 0, group_ids)],
        })

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _login_member(self):
        self.authenticate(self.member_login, self.password)

    def _login_no_role(self):
        self.authenticate(self.no_role_login, self.password)

    @staticmethod
    def _location(response):
        """兼容不同 Odoo 小版本 url_open 返回对象的头访问方式。"""
        headers = getattr(response, 'headers', None)
        if headers is not None:
            try:
                return headers.get('Location', '') or ''
            except AttributeError:
                pass
        getheader = getattr(response, 'getheader', None)
        if callable(getheader):
            return getheader('Location') or ''
        return ''

    def _jsonrpc(self, path, params=None):
        body = json.dumps({
            'jsonrpc': '2.0',
            'method': 'call',
            'params': params or {},
            'id': 1,
        })
        response = self.url_open(
            path, data=body, headers={'Content-Type': 'application/json'})
        self.assertEqual(
            response.status_code, 200,
            'JSON-RPC 路由应返回 200，实际 %s' % response.status_code)
        payload = response.json()
        self.assertIn('result', payload)
        return payload

    def _session_csrf_token(self):
        """取当前测试会话的 CSRF token；取不到返回 None。

        Odoo 不同小版本暴露位置不同：优先 HttpCase.csrf_token()，其次
        从已登录的 /web 页面里的 odoo.csrf_token 变量抓取。都拿不到时
        由调用方 skip 正分支，并保留缺失 CSRF 的拒绝分支断言。
        """
        candidate = getattr(self, 'csrf_token', None)
        if callable(candidate):
            try:
                candidate = candidate()
            except Exception:  # 该方法可能要求请求上下文
                candidate = None
        if isinstance(candidate, str) and candidate:
            return candidate
        try:
            response = self.url_open('/web')
        except Exception:
            return None
        if response.status_code != 200:
            return None
        text = getattr(response, 'text', '') or ''
        patterns = (
            r'csrf_token\s*[=:]\s*["\']([^"\']+)["\']',
            r'name=["\']csrf_token["\'][^>]*value=["\']([^"\']+)["\']',
        )
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1)
        return None

    # ------------------------------------------------------------------
    # 1. 匿名欢迎页
    # ------------------------------------------------------------------
    def test_01_anonymous_welcome_renders(self):
        """验证契约：匿名 GET /team 返回 200，HTML 含站点标题。"""
        response = self.url_open('/team')
        self.assertEqual(response.status_code, 200)
        title = self.env['ir.config_parameter'].sudo().get_param(
            'lab_team_web.site_title', '力创实验室 · 战队仓库')
        self.assertIn(title, response.text)

    # ------------------------------------------------------------------
    # 2. 匿名仓库页 -> 本站登录页
    # ------------------------------------------------------------------
    def test_02_anonymous_lab_redirects_to_site_login(self):
        """验证契约：匿名 GET /team/lab 为 303，Location 指向 /team/login
        且带 next 回跳参数（不跳 Odoo 原生 /web/login）。"""
        response = self.url_open('/team/lab', allow_redirects=False)
        self.assertEqual(response.status_code, 303)
        location = self._location(response)
        self.assertIn('/team/login', location)
        self.assertIn('next=', location)
        self.assertNotIn('/web/login', location)

    # ------------------------------------------------------------------
    # 3. 无权限用户被拒绝
    # ------------------------------------------------------------------
    def test_03_lab_denied_without_catalog_role(self):
        """验证契约：已登录但无 lab_catalog 权限时 GET /team/lab 为 403，
        而不是 200 或 500（后端显式判定，不靠前端隐藏入口）。"""
        self._login_no_role()
        response = self.url_open('/team/lab')
        self.assertEqual(response.status_code, 403)

    # ------------------------------------------------------------------
    # 4. 有权限用户可进仓库
    # ------------------------------------------------------------------
    def test_04_lab_renders_for_catalog_role(self):
        """验证契约：具备 lab_catalog.group_lab_catalog_user 的用户
        GET /team/lab 返回 200。"""
        self._login_member()
        response = self.url_open('/team/lab')
        self.assertEqual(response.status_code, 200)

    # ------------------------------------------------------------------
    # 5. 详情：真实夹具必须 200 且带字段
    # ------------------------------------------------------------------
    def test_05_item_detail_known_key_renders_fixture(self):
        """验证契约：对隔离库中确定存在的本地器件（lab:<id>），详情页必须
        200，且页面包含器件名称与型号；不是"200 或 404 都可"。
        另外断言页面没有把研发说明（stock.quant 等）暴露给使用者。"""
        self._login_member()
        response = self.url_open(self.fixture_key_url(), allow_redirects=False)
        self.assertEqual(
            response.status_code, 200,
            '确定存在的 lab:<id> 详情必须是 200，实际 %s' % response.status_code)
        body = response.text
        self.assertIn(self.fixture_name, body)
        self.assertIn('ZZT-001', body)
        for banned in ('stock.quant', 'stock.move'):
            self.assertNotIn(banned, body, '页面不应出现研发术语 %s' % banned)

    def fixture_key_url(self):
        return '/team/lab/items/%s' % self.fixture_key

    # ------------------------------------------------------------------
    # 6. 非法 itemKey -> 400
    # ------------------------------------------------------------------
    def test_06_item_detail_invalid_key_is_400(self):
        """验证契约：已登录且有权限时，非法 itemKey 返回 400
        （参数错误，不是 404 也不是 500）。"""
        self._login_member()
        response = self.url_open(
            '/team/lab/items/not-a-key', allow_redirects=False)
        self.assertEqual(response.status_code, 400)

    # ------------------------------------------------------------------
    # 7. 匿名会话接口
    # ------------------------------------------------------------------
    def test_07_anonymous_session_api(self):
        """验证契约：POST /team/api/session 匿名返回 ok=True、
        authenticated=False、**全部**权限位 False、无身份信息，且 base=/team。

        P3 起该接口合法增加了库存权限位（frontend-contract.md §5.1），
        因此不能再断言 permissions 等于旧的三键字典；但绝不允许"新增字段变成 True"
        或"匿名泄露身份"。这里同时校验：旧键仍在、新键在、所有值一律 False。
        """
        payload = self._jsonrpc('/team/api/session')
        result = payload['result']
        self.assertTrue(result['ok'])
        self.assertIsNone(result['error'])
        data = result['data']
        self.assertFalse(data['authenticated'])

        permissions = data['permissions']
        # 1) 旧只读批次的三个位必须仍然存在且为 False（不回退 API shape）
        for name in ('can_catalog', 'can_lab', 'is_manager'):
            self.assertIn(name, permissions, '匿名响应缺少旧权限位 %s' % name)
            self.assertFalse(permissions[name], '匿名不得拥有 %s' % name)
        # 2) P3 新增的库存权限位必须存在（前端按位渲染菜单）
        for name in ('can_receipt', 'can_issue', 'can_return',
                     'can_manage_labels', 'can_issue_for_others',
                     'can_manage_locations', 'can_manage_mappings',
                     'can_manage_members'):
            self.assertIn(name, permissions, '匿名响应缺少权限位 %s' % name)
        # 3) 任何一个权限位为 True 都是缺陷
        granted = sorted(name for name, value in permissions.items() if value)
        self.assertEqual(granted, [], '匿名会话不得拥有任何权限：%r' % permissions)

        # 4) 匿名不得泄露身份（新增字段不能变成身份泄漏）
        self.assertIsNone(data['uid'])
        self.assertEqual(data['name'], '')
        self.assertEqual(data['login'], '')
        self.assertEqual(data.get('company'), {'id': None, 'name': ''})

        self.assertEqual(data['base'], '/team')
        # 5) urls 只增不减：旧的四个入口必须还在（P3 增加了业务页地址）
        self.assertTrue(
            {'welcome', 'login', 'logout', 'lab'} <= set(data['urls']),
            'urls 缺少既有入口：%r' % sorted(data['urls']))

    # ------------------------------------------------------------------
    # 8. 已登录访问登录页 -> 回跳
    # ------------------------------------------------------------------
    def test_08_logged_in_login_redirects_to_next(self):
        """验证契约：已登录 GET /team/login?next=/team/lab 为 303，
        Location 回到站内 next 目标。"""
        self._login_member()
        response = self.url_open(
            '/team/login?next=%2Fteam%2Flab', allow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertIn('/team/lab', self._location(response))

    def test_08b_logged_in_login_rejects_offsite_next(self):
        """验证契约：已登录时 next 为协议相对 URL（//evil.example）必须
        被 normalize_next 拒绝，303 只能落在站内默认目标。"""
        self._login_member()
        response = self.url_open(
            '/team/login?next=%2F%2Fevil.example', allow_redirects=False)
        self.assertEqual(response.status_code, 303)
        location = self._location(response)
        self.assertNotIn('evil.example', location)
        self.assertIn('/team/lab', location)

    # ------------------------------------------------------------------
    # 9. 退出：CSRF 缺失必须拒绝
    # ------------------------------------------------------------------
    def test_09_logout_without_csrf_is_rejected(self):
        """验证契约：POST /team/logout 缺 CSRF token 时返回 400/403，
        不得 200/303 成功退出。"""
        self._login_member()
        response = self.url_open(
            '/team/logout', data={}, method='POST', allow_redirects=False)
        self.assertIn(response.status_code, (400, 403))
        self.assertNotEqual(response.status_code, 303)

    # ------------------------------------------------------------------
    # 10. 退出：带 CSRF 成功 -> 303 登录页
    # ------------------------------------------------------------------
    def test_10_logout_with_csrf_redirects_to_login(self):
        """验证契约：带 CSRF 的 POST /team/logout 为 303 回本站登录页。

        token 必须来自**本模块自己的退出表单**（GET /team 渲染），
        不依赖 /web 页面；取不到即视为模板缺陷直接失败，而不是静默 skip。
        """
        self._login_member()
        page = self.url_open('/team')
        self.assertEqual(page.status_code, 200)
        match = re.search(
            r'name="csrf_token"[^>]*value="([^"]+)"', page.text or '')
        self.assertIsNotNone(
            match, '本站退出表单缺少 csrf_token 隐藏域，无法验证退出流程')
        token = match.group(1)
        response = self.url_open(
            '/team/logout', data={'csrf_token': token},
            method='POST', allow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertIn('/team/login', self._location(response))


if __name__ == '__main__':
    unittest.main(verbosity=2)
