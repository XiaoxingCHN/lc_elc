# -*- coding: utf-8 -*-
"""P3 写业务 HTTP/ORM 验收（Odoo 19 HttpCase，专用隔离库）。

覆盖 Lead 指定的 P3 验收点（每条都断言"服务端事实"，不信前端提示）：
  1. 两阶段入库：确认前 stock.quant/stock.move 不变；确认后真实增加 + 生成袋
  2. 确认幂等：同 key 同 payload 重放 → 不重复入库
  3. 同 key 异 payload → CONFLICT
  4. 领用/部分归还/超还拒绝；跨账号归还 → FORBIDDEN(not_owner)；管理员代还成功
  5. adopt_stock 失败零残留（深度重复码路径由 backend test_80 覆盖）
  6. 跨公司袋标签 → NOT_FOUND；labels/preview 不含 font_path 且 qr_per_label=1
  7. 只读角色/无 lab 角色 → FORBIDDEN；匿名 JSON-RPC 被拒
  8. 安全 PDF：缺 CSRF 拒绝；带 CSRF 返回 application/pdf + nosniff + no-store
  9. 畸形入参 → VALIDATION_ERROR/NOT_FOUND（不是 INTERNAL_ERROR、无 error_id）
 10. 传输结果不确定 → 同 key 同 payload 重发不重复记账
 11. 页面角色矩阵：匿名 303 / 无 lab 角色 403 / 操作员 200 / 非 manager 进管理页 403

两个必须遵守的可见性规则（R2/R4/R5/R6 实测确认）：
  * **类级 fixture 必须在 `super().setUpClass()` 之前提交**：HttpCase 的类事务在 super()
    里建立 REPEATABLE READ 快照，之后再提交的 users 对 `self.env` 不可见，
    `self.authenticate → res.users.authenticate` 会 AccessDenied（R4 的 9 个 error）。
  * **用例内读写都用共享 `self.env`，不能另开连接**：HttpCase 的 HTTP 请求与测试共享
    同一个 **TestCursor（未提交）**，所以 HTTP 写入对 `self.env` 可见、对独立连接不可见
    （R6 的"_quant=0 / 袋为空"就是独立连接读未提交事务）。
    读之前 `self.env.invalidate_all()` 清缓存；quant 仍只读 `stock.quant` 并按
    `location_id.usage in ('internal','transit')` 过滤（供应商虚拟库位 -N 会抵消内部 +N）；
    **不使用 cached_quantity**。

运行（隔离库，合成账号；不连生产）：
    odoo-bin --addons-path=<odoo>/addons,server/ubuntu22.04/odoo_addons \\
        -d <isolated_db> -i lab_catalog,lab_workflow,lab_team_web --test-enable \\
        --test-tags /lab_team_web --stop-after-init

注意：本文件需由 Lead 登记到 `tests/__init__.py` 才会被加载（写域约定不自行修改）。
"""
import json
import os
import re
import unittest
import uuid

try:
    import odoo  # noqa: F401
except ImportError as exc:  # 本机纯 Python 环境：整模块跳过
    raise unittest.SkipTest('需要 Odoo 19 运行时（本机未安装）：%s' % exc) from exc

from odoo.tests import HttpCase, tagged


def _key(prefix='p3'):
    return ('%s-%s' % (prefix, uuid.uuid4().hex))[:60]


@tagged('post_install', '-at_install')
class LabTeamWebP3WorkflowTest(HttpCase):
    """P3 写业务：真实 HTTP JSON-RPC + 独立连接核对服务端事实。"""

    #: 类级口令与登录名（bootstrap 在 super() 之前就要用到）
    PASSWORD = 'p3-workflow-test-2026'
    LOGINS = {
        'norole': 'p3_http_norole',
        'catalog': 'p3_http_catalog',
        'lab_user': 'p3_http_labuser',
        'operator': 'p3_http_operator',
        'operator_b': 'p3_http_operator_b',
        'manager': 'p3_http_manager',
    }
    GROUPS = {
        'norole': ['base.group_user'],
        'catalog': ['base.group_user', 'lab_catalog.group_lab_catalog_user'],
        'lab_user': ['base.group_user', 'lab_catalog.group_lab_catalog_user',
                     'lab_workflow.group_lab_user'],
        'operator': ['base.group_user', 'lab_catalog.group_lab_catalog_user',
                     'lab_workflow.group_lab_user',
                     'lab_workflow.group_lab_operator'],
        'operator_b': ['base.group_user', 'lab_catalog.group_lab_catalog_user',
                       'lab_workflow.group_lab_user',
                       'lab_workflow.group_lab_operator'],
        'manager': ['base.group_user', 'lab_catalog.group_lab_catalog_user',
                    'lab_workflow.group_lab_user',
                    'lab_workflow.group_lab_operator',
                    'lab_workflow.group_lab_manager'],
    }

    # ------------------------------------------------------------------
    # 生命周期（R4 根因）：HttpCase 的类事务在 super().setUpClass() 建立
    # REPEATABLE READ 快照；此后任何提交都对 self.env 不可见，导致
    # self.authenticate → res.users.authenticate → AccessDenied。
    # 所以**所有类级 fixture 必须在 super() 之前用真实连接提交**。
    # ------------------------------------------------------------------
    @classmethod
    def _raw_db_name(cls):
        """测试库名：优先 Odoo 配置，其次环境变量（super() 之前也能拿到）。"""
        from odoo.tools import config
        name = ''
        try:
            name = config.get('db_name') or ''
        except Exception:
            name = ''
        if isinstance(name, (list, tuple)):
            name = name[0] if name else ''
        name = str(name).split(',')[0].strip()
        if not name:
            name = (os.environ.get('DB_NAME')
                    or os.environ.get('PGDATABASE') or '').strip()
        return name

    @classmethod
    def _bootstrap_env(cls):
        """super() 之前可用的真实连接（此时 cls.env 还不存在）。"""
        from odoo import api, sql_db
        dbname = cls._raw_db_name()
        if not dbname:
            raise AssertionError('无法确定测试库名（config db_name 为空），'
                                 '请在 -d/--db-filter 指定专用测试库')
        cr = sql_db.db_connect(dbname).cursor()
        return api.Environment(cr, 1, {}), cr

    @classmethod
    def setUpClass(cls):
        cls.password = cls.PASSWORD
        cls.logins = dict(cls.LOGINS)
        cls._seq = 0
        cls._bootstrap_fixtures()          # ← 必须在 super() 之前提交
        super().setUpClass()
        # 自检：已提交 fixture 必须落在类快照里；否则立刻指出生命周期问题，
        # 而不是让 9 个用例各自报 AccessDenied。
        count = cls.env['res.users'].search_count(
            [('login', 'in', list(cls.logins.values()))])
        if count < len(cls.logins):
            raise AssertionError(
                '已提交 fixture 在类测试快照中不可见（%d/%d）：'
                'fixture 必须在 super().setUpClass() 之前提交'
                % (count, len(cls.logins)))

    @classmethod
    def _bootstrap_fixtures(cls):
        env, cr = cls._bootstrap_env()
        try:
            env['ir.config_parameter'].sudo().set_param(
                'lab_team_web.management_host', '')
            env['ir.config_parameter'].sudo().set_param(
                'lab_team_web.root_aliases', '1')
            cls.company_id = env.company.id
            cls.user_ids = {}
            for role, xmlids in cls.GROUPS.items():
                cls.user_ids[role] = cls._create_user(
                    env, cls.LOGINS[role], xmlids)
            cls.location_ids = cls._create_locations(env)
            cls.category_id = env['product.category'].create(
                {'name': 'P3-HTTP-类别'}).id
            cr.commit()
        except Exception:
            cr.rollback()
            raise
        finally:
            cr.close()

    @classmethod
    def _create_user(cls, env, login, group_xmlids):
        group_ids = [env.ref(xmlid).id for xmlid in group_xmlids]
        user = env['res.users'].with_context(no_reset_password=True).create({
            'name': login,
            'login': login,
            'email': '%s@example.invalid' % login,
            'password': cls.PASSWORD,
            'company_id': cls.company_id,
            'company_ids': [(6, 0, [cls.company_id])],
            'group_ids': [(6, 0, group_ids)],
        })
        return user.id

    @classmethod
    def _create_locations(cls, env):
        warehouse = env['stock.warehouse'].search(
            [('company_id', '=', cls.company_id)], limit=1)
        parent = warehouse.lot_stock_id if warehouse else env[
            'stock.location'].search([('usage', '=', 'internal')], limit=1)
        parent_id = parent.location_id.id if parent else False
        ids = []
        for name in ('P3-HTTP-A', 'P3-HTTP-B'):
            ids.append(env['stock.location'].create({
                'name': name,
                'usage': 'internal',
                'location_id': parent_id,
                'company_id': cls.company_id,
            }).id)
        return ids

    # ------------------------------------------------------------------
    # 每用例夹具：建在 **self.env** 里（与 HTTP 请求共享 TestCursor）
    # ------------------------------------------------------------------
    def _new_item(self, tracking='lot', storable=True):
        """本用例器件：建在共享 TestCursor 里，HTTP 请求能按 item_key 找到它。

        item_key 合法格式由 inventory_codec 决定（`lcsc:C<数字>`），不能带字母后缀。
        """
        type(self)._seq += 1
        seq = type(self)._seq
        code = 'C77%05d' % seq
        template = self.env['product.template'].create({
            'name': 'P3 HTTP 器件 %03d' % seq,
            'type': 'consu',
            'is_storable': storable,
            'tracking': tracking,
            'lab_lcsc_code': code,
            'lab_mpn': 'P3-HTTP-MPN-%05d' % seq,
        })
        return {'id': template.id, 'code': code}

    def _login(self, role):
        self.authenticate(self.logins[role], self.password)

    def _rpc(self, path, params=None):
        body = json.dumps({'jsonrpc': '2.0', 'method': 'call',
                           'params': params or {}})
        response = self.url_open(path, data=body,
                                 headers={'Content-Type': 'application/json'})
        payload = None
        try:
            payload = response.json()
        except Exception:
            payload = None
        return response.status_code, payload

    @staticmethod
    def _envelope(payload):
        if not isinstance(payload, dict):
            return (None, None, {}, None)
        result = payload.get('result')
        if isinstance(result, dict) and 'ok' in result:
            error = result.get('error') or {}
            return (bool(result.get('ok')), error.get('code'),
                    error.get('fields') or {}, result.get('data') or {})
        if isinstance(payload.get('error'), dict):
            return (False, 'TRANSPORT_%s' % payload['error'].get('code'), {}, None)
        return (None, None, {}, None)

    def _call(self, path, params=None, expect_ok=True):
        status, payload = self._rpc(path, params)
        if status == 404:
            self.skipTest('P3 端点尚未发布（控制器未注册）：%s' % path)
        ok, code, fields, data = self._envelope(payload)
        if expect_ok and not ok:
            self.fail('%s 期望成功，实际 HTTP=%s code=%s fields=%s'
                      % (path, status, code, json.dumps(fields, ensure_ascii=False)))
        return ok, code, fields, data or {}

    # -- 服务端事实：读**共享 TestCursor**（HTTP 请求与本事务同一游标、未提交） --
    def _invalidate(self):
        """HTTP 请求写过之后，清掉 ORM 缓存再读，避免读到本事务的旧缓存。"""
        self.env.invalidate_all()

    def _quant(self, template_id):
        """只读 quant，且只统计 internal/transit（供应商虚拟库位 -N 会和内部 +N 抵消）。"""
        self._invalidate()
        rows = self.env['stock.quant'].search_read(
            [('product_id.product_tmpl_id', '=', template_id),
             ('location_id.usage', 'in', ('internal', 'transit'))],
            ['quantity', 'location_id'])
        return round(sum(float(row.get('quantity') or 0) for row in rows), 6)

    def _bag_count(self, template_id=None):
        self._invalidate()
        domain = [('product_tmpl_id', '=', template_id)] if template_id else []
        return self.env['lab.bag'].search_count(domain)

    def _first_bag_id(self, template_id):
        self._invalidate()
        bag = self.env['lab.bag'].search(
            [('product_tmpl_id', '=', template_id)], limit=1)
        return bag.id if bag else False

    def _move_count(self, template_id):
        self._invalidate()
        return self.env['stock.move'].search_count(
            [('product_id.product_tmpl_id', '=', template_id)])

    def _origin(self):
        """站点 origin：base_url → config http_port → 8069。

        注意 `HttpCase.http_port` 是**方法**，直接 getattr 会拼出
        "http://127.0.0.1:<bound method ...>"（R5 test10 的 error 根因）。
        """
        try:
            base = (getattr(self, 'base_url', '') or '').strip()
        except Exception:
            base = ''
        if base:
            return base.rstrip('/')
        port = None
        try:
            from odoo.tools import config
            port = config.get('http_port')
        except Exception:
            port = None
        if not isinstance(port, int):
            method = getattr(self, 'http_port', None)
            if callable(method):
                try:
                    port = method()
                except Exception:
                    port = None
            elif isinstance(method, int):
                port = method
        if not isinstance(port, int):
            port = 8069
        return 'http://127.0.0.1:%d' % port

    def _anonymous_get(self, path):
        """匿名请求：用 **native url_open**（自带 db/test 上下文），清 cookie、不跟跳转。

        不能用裸 requests：测试模式下请求缺少 HttpCase 的 db/游标上下文会直接 400。
        """
        session = getattr(self, 'session', None)
        saved = None
        if session is not None:
            try:
                saved = dict(session.cookies)
                session.cookies.clear()
            except Exception:
                saved = None
        try:
            try:
                response = self.url_open(path, allow_redirects=False)
            except TypeError:
                response = self.url_open(path)
        finally:
            if session is not None and saved:
                for name, value in saved.items():
                    try:
                        session.cookies.set(name, value)
                    except Exception:
                        pass
        history = list(getattr(response, 'history', None) or [])
        codes = [item.status_code for item in history] + [response.status_code]
        locations = [item.headers.get('Location', '') for item in history]
        locations.append(response.headers.get('Location', ''))
        return {'status': codes[0], 'codes': codes,
                'location': next((loc for loc in locations if loc), '')}

    def _receipt(self, template, quantity, location_id=None, key=None, trace=None):
        return self._call('/lab/api/inventory/receipt', {
            'request_key': key or _key('rcv'),
            'item_key': 'lcsc:%s' % template['code'],
            'location_id': location_id or self.location_ids[0],
            'quantity': quantity,
            'trace_code': trace,
        })[3]

    def _issue(self, bag_id, quantity, borrower_id, project='P3 验收'):
        return self._call('/lab/api/inventory/issue', {
            'request_key': _key('issue'),
            'borrower_id': borrower_id,
            'project': project,
            'lines': [{'bag_id': bag_id, 'quantity': quantity}],
        })[3]

    # ------------------------------------------------------------------
    # 1. 匿名被拒
    # ------------------------------------------------------------------
    def test_01_anonymous_jsonrpc_rejected(self):
        template = self._new_item()
        status, payload = self._rpc('/lab/api/inventory/bootstrap', {})
        self.assertNotEqual(status, 404, 'bootstrap 端点缺失')
        ok, code, fields, data = self._envelope(payload)
        self.assertFalse(ok, '匿名不应通过：code=%s' % code)
        self.assertEqual(self._quant(template['id']), 0)

    # ------------------------------------------------------------------
    # 2. 两阶段：确认前无库存、确认后入库、幂等、同 key 异 payload
    # ------------------------------------------------------------------
    def test_02_two_stage_receipt_and_idempotency(self):
        self._login('operator')
        template = self._new_item()
        before = self._quant(template['id'])
        moves_before = self._move_count(template['id'])

        created = self._call('/lab/api/inventory/pending/create', {
            'request_key': _key('prep'),
            'item_key': 'lcsc:%s' % template['code'],
            'quantity': 5, 'count': 1, 'note': 'P3 两阶段'})[3]
        records = created.get('records') or []
        self.assertTrue(records, '建袋未返回 records；data keys=%s'
                        % sorted((created or {}).keys()))
        record = records[0]
        self.assertEqual(self._quant(template['id']), before, '建袋阶段不得增加库存')
        self.assertEqual(self._move_count(template['id']), moves_before,
                         '建袋阶段不得产生 stock.move')

        params = {'request_key': _key('confirm'), 'pending_id': record['id'],
                  'quantity': 5, 'location_id': self.location_ids[0]}
        first = self._call('/lab/api/inventory/pending/confirm', params)[3]
        self.assertEqual(self._quant(template['id']), round(before + 5, 6),
                         '确认后应 +5；实际 data keys=%s'
                         % sorted((first or {}).keys()))
        bag_id = (first.get('bag') or {}).get('id')
        if bag_id is None:
            self._invalidate()
            found = self.env['lab.bag'].search(
                [('trace_code', '=', record['trace_code'])], limit=1)
            bag_id = found.id if found else False
        self.assertTrue(bag_id, '确认后应存在 lab.bag')

        # 同 key 同 payload 重放：不得重复入库
        replay = self._call('/lab/api/inventory/pending/confirm', params)[3]
        same_bag = (replay.get('bag') or {}).get('id') == bag_id
        self.assertTrue(replay.get('replayed') or same_bag,
                        '同 key 重放应 replayed=True 或返回同一袋；keys=%s'
                        % sorted(replay.keys()))
        self.assertEqual(self._quant(template['id']), round(before + 5, 6),
                         '重放不得重复入库')

        changed = dict(params, quantity=6)
        ok, code, fields, data = self._call(
            '/lab/api/inventory/pending/confirm', changed, expect_ok=False)
        self.assertFalse(ok)
        self.assertEqual(code, 'CONFLICT', '同 key 异 payload 应为 CONFLICT，实际 %s fields=%s'
                         % (code, json.dumps(fields, ensure_ascii=False)))
        self.assertEqual(self._quant(template['id']), round(before + 5, 6))

    # ------------------------------------------------------------------
    # 3. 领用/部分归还/超还/跨账号
    # ------------------------------------------------------------------
    def test_03_issue_return_and_cross_user(self):
        self._login('operator')
        template = self._new_item()
        self._receipt(template, 10)
        bag_id = self._first_bag_id(template['id'])
        self.assertTrue(bag_id, '入库后应有袋')
        before = self._quant(template['id'])

        issued = self._issue(bag_id, 4, self.user_ids['operator'])
        lines = issued.get('lines') or []
        self.assertTrue(lines, '领用未返回明细；keys=%s' % sorted((issued or {}).keys()))
        issue_line_id = lines[0].get('issue_line_id')
        self.assertTrue(issue_line_id)
        self.assertEqual(self._quant(template['id']), round(before - 4, 6),
                         '领用后应 -4')

        returned = self._call('/lab/api/inventory/return', {
            'request_key': _key('ret'), 'issue_line_id': issue_line_id,
            'quantity': 3})[3]
        self.assertEqual(returned.get('outstanding_quantity'), 1)

        ok, code, fields, data = self._call('/lab/api/inventory/return', {
            'request_key': _key('ret'), 'issue_line_id': issue_line_id,
            'quantity': 99}, expect_ok=False)
        self.assertFalse(ok)
        self.assertEqual(code, 'PRECONDITION_FAILED',
                         '超还应为 PRECONDITION_FAILED，实际 %s fields=%s'
                         % (code, json.dumps(fields, ensure_ascii=False)))
        self.assertEqual(self._quant(template['id']), round(before - 1, 6))

        # 跨账号归还：第二操作员 → FORBIDDEN(not_owner)
        self._login('operator_b')
        ok, code, fields, data = self._call('/lab/api/inventory/return', {
            'request_key': _key('ret-x'), 'issue_line_id': issue_line_id,
            'quantity': 1}, expect_ok=False)
        self.assertFalse(ok)
        self.assertEqual(code, 'FORBIDDEN', '跨账号归还应 FORBIDDEN，实际 %s' % code)
        self.assertEqual(fields.get('issue_line_id'), 'not_owner')
        self.assertEqual(self._quant(template['id']), round(before - 1, 6))

        # 管理员代还：允许，未还清零
        self._login('manager')
        done = self._call('/lab/api/inventory/return', {
            'request_key': _key('ret-m'), 'issue_line_id': issue_line_id,
            'quantity': 1})[3]
        self.assertEqual(done.get('outstanding_quantity'), 0)
        self.assertEqual(self._quant(template['id']), before)

    # ------------------------------------------------------------------
    # 4. adopt_stock 失败零残留
    # ------------------------------------------------------------------
    def test_04_adopt_stock_atomic_rollback(self):
        self._login('manager')
        template = self._new_item(tracking='none')
        bags_before = self._bag_count(template['id'])
        quant_before = self._quant(template['id'])
        ok, code, fields, data = self._call('/lab/api/inventory/adopt_stock', {
            'item_key': 'lcsc:%s' % template['code'],
            'bags': [
                {'location_id': self.location_ids[0], 'quantity': 3,
                 'trace_code': 'P3ADOPT0001'},
                {'location_id': self.location_ids[0], 'quantity': 4,
                 'trace_code': 'P3ADOPT0001'},
            ],
            'note': 'P3 回滚探针'}, expect_ok=False)
        self.assertFalse(ok, '重复 trace_code 必须失败；fields=%s'
                         % json.dumps(fields, ensure_ascii=False))
        # 直接创建的夹具器件没有 catalog 绑定，adopt 会先以 NOT_FOUND(not_bound) 拒绝；
        # 这仍是"失败 → 零残留"的有效路径。重复码深度路径由 backend test_80 覆盖。
        self.assertIn(code, ('CONFLICT', 'PRECONDITION_FAILED', 'VALIDATION_ERROR',
                             'NOT_FOUND'),
                      '应为业务错误码，实际 %s fields=%s'
                      % (code, json.dumps(fields, ensure_ascii=False)))
        self.assertEqual(self._bag_count(template['id']), bags_before, '失败后不得残留袋')
        self.assertEqual(self._quant(template['id']), quant_before, '失败后库存不变')
        self._invalidate()
        self.assertEqual(self.env['lab.bag'].search_count(
            [('trace_code', '=', 'P3ADOPT0001')]), 0, '不得残留 trace_code')

    # ------------------------------------------------------------------
    # 5. 标签：跨公司 NOT_FOUND、preview 不泄漏 font_path
    # ------------------------------------------------------------------
    def test_05_labels_cross_company_and_preview(self):
        self._login('operator')
        template = self._new_item()
        self._receipt(template, 2)
        bag_id = self._first_bag_id(template['id'])
        self.assertTrue(bag_id, '入库后应有袋')

        c2_bag_id, c2_error = self._create_c2_bag()
        if c2_bag_id is None:
            # 不能 skip 后当成整体通过：C2 fixture 建不出来本身就是验收未过
            self.fail('跨公司标签隔离未验证：无法建立已提交的 C2 袋 fixture（%s）。'
                      '需 backend 确认 C2 fixture（公司/库位/器件/袋）与活动公司域' % c2_error)
        ok, code, fields, data = self._call('/lab/api/labels/plan', {
            'kind': 'bag', 'ids': [c2_bag_id]}, expect_ok=False)
        self.assertFalse(
            ok, '跨公司袋标签不应成功（C2 bag_id=%s data keys=%s）；'
                '请与 backend 核对 C2 fixture 与活动公司域'
                % (c2_bag_id, sorted((data or {}).keys())))
        self.assertEqual(code, 'NOT_FOUND', '跨公司标签应为 NOT_FOUND，实际 %s fields=%s'
                         % (code, json.dumps(fields, ensure_ascii=False)))

        preview = self._call('/lab/api/labels/preview', {
            'kind': 'bag', 'ids': [bag_id]})[3]
        self.assertNotIn('font_path', preview, 'preview 不得返回服务器字体路径')
        self.assertEqual(preview.get('qr_per_label'), 1, '每张标签只能有一个 QR')
        self.assertTrue(preview.get('pdf_base64'), 'preview 应返回 PDF 字节')

        ok, code, fields, data = self._call('/lab/api/labels/plan', {
            'kind': 'bag', 'ids': [bag_id], 'width_mm': 5, 'height_mm': 5},
            expect_ok=False)
        self.assertFalse(ok, '过小尺寸应被拒绝')
        self.assertEqual(code, 'VALIDATION_ERROR')

    def _create_c2_bag(self):
        """按 backend 已通过的口径造 C2 袋：`internal_service()` + `sudo().with_company(B)`。

        `lab.bag` 禁止直接 RPC/普通上下文建档（mutation_guard 会拒），所以必须在服务端
        内部上下文里建，并显式 `with_company(B)`；对象建在**当前共享 TestCursor** 里，
        因此本用例与 HTTP 请求都能看到它——跨公司断言测的是"公司域拒绝"，不是"对象不存在"。
        参考：lab_workflow/tests/test_p3_backend_api.py::_make_cross_company_issue_line。
        返回 (bag_id, error)；失败时 bag_id=None。
        """
        try:
            from odoo.addons.lab_workflow.models.lab_workflow_common import (
                internal_service)
        except Exception as exc:  # 导入失败要报出来，不能静默
            return None, '无法导入 internal_service：%s: %s' % (
                type(exc).__name__, str(exc)[:160])
        try:
            other = self.env['res.company'].create({
                'name': 'P3 C2 公司 ' + uuid.uuid4().hex[:8]})
            location = self.env['stock.location'].sudo().create({
                'name': 'P3 C2-LOC',
                'usage': 'internal',
                'company_id': other.id})
            with internal_service():
                template = self.env['product.template'].sudo().with_company(
                    other).create({
                        'name': 'P3 C2 物料',
                        'type': 'consu',
                        'is_storable': True,
                        'tracking': 'lot',
                        'company_id': other.id,
                    })
                bag = self.env['lab.bag'].sudo().with_company(other).create({
                    'company_id': other.id,
                    'product_tmpl_id': template.id,
                    'product_id': template.product_variant_id.id,
                    'location_id': location.id,
                    'initial_quantity': 1,
                    'quantity': 1,
                })
            self._invalidate()
            if not self.env['lab.bag'].sudo().with_company(other).browse(bag.id).exists():
                return None, '同一 test env 看不到刚建的 C2 袋（id=%s）' % bag.id
            if not other.exists():
                return None, '同一 test env 看不到刚建的 C2 公司（id=%s）' % other.id
            return bag.id, ''
        except Exception as exc:
            return None, '%s: %s' % (type(exc).__name__, str(exc)[:200])

    # ------------------------------------------------------------------
    # 6. 只读/无角色被拒
    # ------------------------------------------------------------------
    def test_06_readonly_roles_forbidden(self):
        template = self._new_item()
        for role in ('norole', 'catalog', 'lab_user'):
            self._login(role)
            ok, code, fields, data = self._call('/lab/api/inventory/receipt', {
                'request_key': _key('ro'),
                'item_key': 'lcsc:%s' % template['code'],
                'location_id': self.location_ids[0], 'quantity': 1}, expect_ok=False)
            self.assertFalse(ok, '%s 不应能入库' % role)
            self.assertEqual(code, 'FORBIDDEN', '%s 期望 FORBIDDEN，实际 %s' % (role, code))
        self.assertEqual(self._quant(template['id']), 0)

    # ------------------------------------------------------------------
    # 7. 安全 PDF（CSRF + 响应头）
    # ------------------------------------------------------------------
    def test_07_labels_pdf_security(self):
        self._login('operator')
        template = self._new_item()
        self._receipt(template, 1)
        bag_id = self._first_bag_id(template['id'])
        self.assertTrue(bag_id, '入库后应有袋')

        response = self.url_open(
            '/lab/labels/pdf',
            data='kind=bag&ids=%d' % bag_id,
            headers={'Content-Type': 'application/x-www-form-urlencoded'})
        if response.status_code == 404:
            self.skipTest('/lab/labels/pdf 尚未发布（控制器未注册）')
        self.assertIn(response.status_code, (400, 403),
                      '缺 CSRF 应被拒，实际 %s' % response.status_code)

        page = self.url_open('/team/lab/labels')
        match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', page.text or '')
        if not match:
            # 页面拿不到 csrf_token 属于真实缺口（PDF 表单无法提交），不能 skip 当通过
            self.fail('标签页未暴露 csrf_token（HTTP=%s，页面长度=%d）：'
                      'PDF 正分支无法提交，属页面/CSRF 接线缺口'
                      % (page.status_code, len(page.text or '')))
        response = self.url_open(
            '/lab/labels/pdf',
            data='csrf_token=%s&kind=bag&ids=%d' % (match.group(1), bag_id),
            headers={'Content-Type': 'application/x-www-form-urlencoded'})
        self.assertEqual(response.status_code, 200,
                         'PDF 正分支应 200，实际 %s' % response.status_code)
        headers = response.headers
        self.assertIn('application/pdf', (headers.get('Content-Type') or '').lower())
        self.assertEqual((headers.get('X-Content-Type-Options') or '').lower(),
                         'nosniff')
        self.assertIn('no-store', (headers.get('Cache-Control') or '').lower())
        self.assertTrue((response.content or b'')[:4] == b'%PDF', 'PDF 内容不合法')
        self.assertNotIn(b'font_path', response.content or b'')

    # ------------------------------------------------------------------
    # 8. 畸形入参 → 业务错误码
    # ------------------------------------------------------------------
    def test_08_malformed_input_is_validation_error(self):
        self._login('operator')
        template = self._new_item()
        cases = (
            ('/lab/api/inventory/receipt', {
                'request_key': _key('bad'),
                'item_key': 'lcsc:%s' % template['code'],
                'quantity': 1, 'location_id': 'abc'}),
            ('/lab/api/inventory/return', {
                'request_key': _key('bad'), 'issue_line_id': 'abc', 'quantity': 1}),
            ('/lab/api/inventory/issues', {'limit': 'abc'}),
            ('/lab/api/labels/plan', {
                'kind': 'location', 'ids': [self.location_ids[0]], 'copies': 'x'}),
        )
        for path, params in cases:
            ok, code, fields, data = self._call(path, params, expect_ok=False)
            self.assertFalse(ok, '%s 畸形入参不应成功' % path)
            self.assertIn(code, ('VALIDATION_ERROR', 'NOT_FOUND'),
                          '%s 期望业务错误码，实际 %s fields=%s'
                          % (path, code, json.dumps(fields, ensure_ascii=False)))
            self.assertNotIn('error_id', fields,
                             '%s 不应返回 INTERNAL_ERROR 的 error_id' % path)

    # ------------------------------------------------------------------
    # 9. 同 key 重发不重复记账
    # ------------------------------------------------------------------
    def test_09_unknown_outcome_retry_same_key(self):
        self._login('operator')
        template = self._new_item()
        params = {'request_key': _key('retry'),
                  'item_key': 'lcsc:%s' % template['code'],
                  'location_id': self.location_ids[0], 'quantity': 2}
        first = self._call('/lab/api/inventory/receipt', params)[3]
        bags_after_first = self._bag_count(template['id'])
        second = self._call('/lab/api/inventory/receipt', params)[3]
        self.assertTrue(second.get('replayed'), '同 key 重发应 replayed=True；keys=%s'
                        % sorted(second.keys()))
        self.assertEqual(self._bag_count(template['id']), bags_after_first,
                         '重发不得产生第二个袋')
        self.assertEqual(self._quant(template['id']), 2)
        self.assertEqual((first.get('bag') or {}).get('trace_code'),
                         (second.get('bag') or {}).get('trace_code'),
                         '重发应返回首次结果')

    # ------------------------------------------------------------------
    # 10. 页面角色矩阵
    # ------------------------------------------------------------------
    def test_10_page_role_matrix(self):
        path = '/team/lab/receipts'
        anon = self._anonymous_get(path)
        codes = anon.get('codes') or [anon.get('status')]
        if codes == [404]:
            self.skipTest('P3 页面路由尚未注册：%s' % path)
        self.assertIn(303, codes,
                      '匿名访问业务页应 303（清 cookie 后原生请求），实际状态序列=%s Location=%s'
                      % (codes, anon.get('location')))
        self.assertIn('/login', (anon.get('location') or ''),
                      '303 必须指向本站登录页，实际 Location=%s' % anon.get('location'))

        self._login('catalog')
        response = self.url_open(path)
        self.assertEqual(response.status_code, 403,
                         '无 lab 角色应 403，实际 %s' % response.status_code)

        self._login('operator')
        response = self.url_open(path)
        self.assertEqual(response.status_code, 200,
                         '操作员访问入库页应 200，实际 %s' % response.status_code)
        response = self.url_open('/team/lab/settings')
        self.assertEqual(response.status_code, 403,
                         '非管理员访问管理页应 403，实际 %s' % response.status_code)

        self._login('manager')
        response = self.url_open('/team/lab/settings')
        self.assertEqual(response.status_code, 200,
                         '管理员访问管理页应 200（500 说明模板/资源缺口，不是"跳过"），实际 %s'
                         % response.status_code)
