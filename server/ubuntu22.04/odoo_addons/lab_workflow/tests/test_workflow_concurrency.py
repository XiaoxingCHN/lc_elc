# -*- coding: utf-8 -*-
"""真实并发测试（多线程 + 多数据库连接 + Barrier 相交执行 + 真实提交）。

**为什么用 BaseCase、为什么默认跳过**

真正的并发要求「两个事务在时间上相交」，每个线程必须自己提交，
这样才能让第二个连接看到数据、并在行锁上真实等待。

* Odoo 19 的 ``TransactionCase`` 会把 ``cr.commit`` 替换成 forbidden
  （``Cannot commit or rollback a cursor from inside a test``），
  因此本模块改用 ``BaseCase``，自己管理连接与提交。
* 测试框架的 ``registry_enter_test_mode`` 会把 ``registry.cursor``
  **实例方法**替换成 ``TestCursor``（包装主测试游标 + 共享锁 +
  savepoint 假提交）。本套件统一用 ``_real_cursor()`` 按**类方法**
  取真实独立连接，保证 commit 真正落库、线程真正相交。
  生产并发验收的主路径是**正常 HTTP 服务 + 两个登录 cookie**
  （``tools/http_concurrency_check.py``），不走测试框架锁环境。
* 默认 **skip**；只有 ``LAB_WORKFLOW_CONCURRENCY=1`` 才运行。
* 只在**独立临时数据库**上运行（``tools/run_isolation_tests.sh`` 会建库），
  结束时删掉自己创建的数据。

覆盖四个并发场景（全部用**非 super 操作员**，barrier 对齐后同时执行）：

1. 袋 100，两个线程各领 70 -> 只 1 个成功，最终库存 30
2. 原领用 20，两个线程各还 15 -> 只 1 个成功，最终未归还 5
3. 同 request_key 两次 receipt 100 -> 只 1 个袋、总量 100
4. 同 key 不同 payload -> 一个成功、一个 CONFLICT

运行::

    LAB_WORKFLOW_CONCURRENCY=1 <odoo-bin> -c <conf> \
        --test-enable --test-tags lab_workflow_concurrency --stop-after-init
"""

import logging
import os
import threading
import unittest
import uuid

from odoo import api
from odoo.orm.registry import Registry
from odoo.tests import BaseCase, get_db_name, tagged

from ..models.lab_workflow_common import LabApiError

_logger = logging.getLogger(__name__)

CONCURRENCY_ENABLED = os.environ.get('LAB_WORKFLOW_CONCURRENCY') == '1'
BARRIER_TIMEOUT = 25


def _key(prefix='c'):
    return ('%s-%s' % (prefix, uuid.uuid4().hex))[:60]


def _real_cursor(registry):
    """取**真实独立数据库连接**（绕过测试框架的 TestCursor patch）。

    Odoo 19 的测试框架（``registry_enter_test_mode`` / HttpCase）会把
    ``registry.cursor`` **实例方法**替换成 ``TestCursor``：它包装主测试
    游标、抢共享 ``_registry_test_lock``、``commit()`` 只是 RELEASE
    SAVEPOINT（不真正落库）。在那种环境里开“并发连接”只会互相串行甚至
    死等，commit 也不会被别的连接看到。

    类方法 ``Registry.cursor`` 没有被 patch，直接按类方法调用即可拿到
    ``self._db.cursor()`` —— 一条真正的独立连接，commit 是真实提交。
    """
    return type(registry).cursor(registry)


class _Runner(object):
    """一个线程 + 独立数据库连接；barrier 对齐后执行 ``work_fn(env)``。

    连接在**线程内部**新建（``registry.cursor()``），
    调用方传进来的 env 只用来借 ``registry`` / context，不能跨线程共用连接。
    """

    def __init__(self, env, user_id, barrier, work_fn, label=''):
        self.registry = env.registry
        self.uid = user_id
        self.context = dict(env.context)
        self.barrier = barrier
        self.work_fn = work_fn
        self.label = label
        self.result = None
        self.error = None
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        import time as _time
        t0 = _time.time()
        try:
            cr = _real_cursor(self.registry)
        except Exception as exc:  # noqa: BLE001
            self.error = exc
            _logger.warning('并发线程[%s] 无法取得连接：%s: %s',
                            self.label, type(exc).__name__, exc)
            return
        _logger.info('并发线程[%s] 拿到连接（%.2fs）', self.label, _time.time() - t0)
        try:
            env = api.Environment(cr, self.uid, self.context)
            _logger.info('并发线程[%s] 已就绪（uid=%s），等待 barrier（%.2fs）',
                         self.label, self.uid, _time.time() - t0)
            self.barrier.wait(timeout=BARRIER_TIMEOUT)  # 两个线程在这里相交
            _logger.info('并发线程[%s] 越过 barrier（%.2fs）', self.label, _time.time() - t0)
            self.result = self.work_fn(env)
            _logger.info('并发线程[%s] 业务完成（%.2fs），准备提交',
                         self.label, _time.time() - t0)
            cr.commit()
            _logger.info('并发线程[%s] 提交完成（%.2fs）', self.label, _time.time() - t0)
        except Exception as exc:  # noqa: BLE001 - 收集后由主线程断言
            self.error = exc
            _logger.info('并发线程[%s]失败（%.2fs）：%s: %s',
                         self.label, _time.time() - t0, type(exc).__name__, exc)
            try:
                cr.rollback()
            except Exception:  # noqa: BLE001
                pass
        finally:
            try:
                cr.close()
            except Exception:  # noqa: BLE001
                pass

    def start(self):
        self.thread.start()

    def join(self):
        self.thread.join(timeout=BARRIER_TIMEOUT * 2)


def dump_locks(env, label=''):
    """超时/失败时把 PostgreSQL 的锁等待打出来，便于定位真正的死锁。

    注意：用**自己的连接**查询，绝不共用主线程的 env.cr（否则会被主线程串行化）。
    """
    try:
        from odoo.orm.registry import Registry
        cr = _real_cursor(Registry(get_db_name()))
    except Exception as exc:  # noqa: BLE001
        _logger.warning('dump_locks 无法取连接：%s', exc)
        return
    try:
        cr.execute("""
            SELECT pid, state, wait_event_type, wait_event, left(query, 100)
              FROM pg_stat_activity WHERE datname = current_database()
             ORDER BY pid
        """)
        for row in cr.fetchall():
            _logger.info('PG[%s] pid=%s state=%s wait=%s/%s q=%s', label, *row)
        cr.execute("""
            SELECT pid, locktype, relation::regclass, mode, granted
              FROM pg_locks
             WHERE pid <> pg_backend_pid() AND NOT granted
             ORDER BY pid
        """)
        rows = cr.fetchall()
        if not rows:
            _logger.info('LOCK[%s] 没有未授予的锁（不是数据库行锁等待）', label)
        for row in rows:
            _logger.info('LOCK[%s] 等待中 pid=%s type=%s rel=%s mode=%s',
                         label, *row)
    except Exception as exc:  # noqa: BLE001
        _logger.warning('dump_locks 查询失败：%s', exc)
    finally:
        try:
            cr.close()
        except Exception:  # noqa: BLE001
            pass


def run_concurrent(env, user_id, work_fns):
    """并发执行多个 work_fn（barrier 对齐相交），返回 runner 列表。"""
    barrier = threading.Barrier(len(work_fns))
    runners = [_Runner(env, user_id, barrier, fn, label='#%d' % index)
               for index, fn in enumerate(work_fns)]
    for runner in runners:
        runner.start()
    # 卡住时提前（10 秒）抓现场：等满超时再抓可能 PG 已经退出
    watcher = threading.Timer(10.0, lambda: dump_locks(env, 'early'))
    watcher.daemon = True
    watcher.start()
    for runner in runners:
        runner.join()
    watcher.cancel()
    stuck = [r for r in runners if r.thread.is_alive()]
    if stuck:
        dump_locks(env, 'timeout')
        raise AssertionError('并发线程超时未结束（可能死锁）：%s'
                             % [r.label for r in stuck])
    return runners


@tagged('post_install', '-at_install', 'lab_workflow_concurrency')
class LabWorkflowConcurrencyTest(BaseCase):
    """真实并发（多线程 + 独立连接 + Barrier 相交 + 真实提交）。

    必须跑在 **post_install**：at_install 阶段模块 schema 还没提交，
    新开的连接看不到表/会撞 DDL 锁，线程无法相交。
    运行方式（安装完成后，用 -u 加载 suite）：:

        LAB_WORKFLOW_CONCURRENCY=1 <odoo-bin> -c <conf> -d <db> \
            --test-enable --test-tags lab_workflow_concurrency -u lab_workflow \
            --stop-after-init --no-http
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not CONCURRENCY_ENABLED:
            raise unittest.SkipTest(
                '需要 LAB_WORKFLOW_CONCURRENCY=1 与独立临时数据库'
                '（见 tools/run_isolation_tests.sh）')
        cls.registry = Registry(get_db_name())
        cr = _real_cursor(cls.registry)
        try:
            env = api.Environment(cr, api.SUPERUSER_ID, {})
            cls.company_id = env.company.id
            warehouse = env['stock.warehouse'].search(
                [('company_id', '=', cls.company_id)], limit=1)
            cls.location_id = warehouse.lot_stock_id.id
            suffix = uuid.uuid4().hex[:6].upper()
            # 只允许数字：真实 catalog 的 C 编号是纯十进制（C77 + 数字），
            # 用 A-F 会被真实目录规则拒绝，stub 能过不代表生产能过。
            digits = str(uuid.uuid4().int)[:6]
            template = env['product.template'].create({
                'name': '并发测试物料',
                'type': 'consu',
                'is_storable': True,
                'tracking': 'lot',
                'lab_lcsc_code': 'C77%s' % digits,
                'lab_sn': 'LAB-CONC-%s' % suffix,
            })
            cls.template_id = template.id
            cls.product_id = template.product_variant_id.id
            cls.item_key = 'lcsc:%s' % template.lab_lcsc_code
            operator = env['res.users'].with_context(
                no_reset_password=True).create({
                    'name': '并发操作员',
                    'login': 'lab_conc_op_%s' % suffix.lower(),
                    'company_id': cls.company_id,
                    'company_ids': [(6, 0, [cls.company_id])],
                    'group_ids': [(4, env.ref('lab_workflow.group_lab_operator').id)],
                })
            cls.operator_id = operator.id
            # 真实提交：工作线程/其它连接必须能看到这些数据
            cr.commit()
        finally:
            cr.close()

    @classmethod
    def tearDownClass(cls):
        """只清理自己创建的数据（按 template -> bag 关链），不动全库记录。

        lab.request.log 按设计不可删除（幂等依据），临时库整体丢弃，无需处理。
        """
        if CONCURRENCY_ENABLED:
            cr = _real_cursor(cls.registry)
            try:
                env = api.Environment(cr, api.SUPERUSER_ID, {})
                bags = env['lab.bag'].sudo().search(
                    [('product_tmpl_id', '=', cls.template_id)])
                bag_ids = bags.ids
                lot_ids = bags.mapped('lot_id').ids
                issue_lines = env['lab.issue.line'].sudo().search(
                    [('bag_id', 'in', bag_ids)])
                return_lines = env['lab.return.line'].sudo().search(
                    [('issue_line_id', 'in', issue_lines.ids)])
                operation_lines = env['lab.operation.line'].sudo().search(
                    [('bag_id', 'in', bag_ids)])
                operation_ids = set(
                    bags.mapped('receipt_operation_id').ids
                    + issue_lines.mapped('issue_operation_id').ids
                    + return_lines.mapped('operation_id').ids
                    + operation_lines.mapped('operation_id').ids)
                # 依外链方向反序删除：return/issue -> operation.line -> move
                # -> quant -> lot -> bag -> operation -> template -> 操作员
                return_lines.sudo().unlink()
                issue_lines.sudo().unlink()
                operation_lines.sudo().unlink()
                env['stock.move'].sudo().search(
                    [('lab_bag_id', 'in', bag_ids)]).unlink()
                env['stock.quant'].sudo().search(
                    [('lot_id', 'in', lot_ids)]).unlink()
                env['stock.lot'].sudo().search(
                    [('id', 'in', lot_ids)]).unlink()
                bags.sudo().unlink()
                env['lab.operation'].sudo().search(
                    [('id', 'in', list(operation_ids))]).unlink()
                env['product.template'].sudo().browse(cls.template_id).unlink()
                users = env['res.users'].sudo().search(
                    [('login', 'like', 'lab_conc_op_%')])
                users.unlink()
                cr.commit()
            except Exception as exc:  # noqa: BLE001
                _logger.warning('并发测试清理未完全成功（不影响用例结论）：%s', exc)
                cr.rollback()
            finally:
                cr.close()
        super().tearDownClass()

    # ------------------------------------------------------------------
    def _cursor_env(self):
        """每个用例自己的连接（提交后其它连接可见）。"""
        cr = _real_cursor(self.registry)
        return cr, api.Environment(cr, api.SUPERUSER_ID, {})

    def _borrow_env(self):
        """返回 (借用的连接, env)：**连接必须由调用方在使用完 env 后关闭**。

        线程自己在内部新建连接，只是 ``_Runner.__init__`` 需要读
        ``env.registry`` 与 context，所以这里不能提前 close。
        """
        cr = _real_cursor(self.registry)
        return cr, api.Environment(cr, api.SUPERUSER_ID, {})

    def _run_concurrent(self, work_fns):
        """统一入口：借用连接 -> 相交执行 -> 关闭连接。"""
        import time as _time
        t0 = _time.time()
        cr, env = self._borrow_env()
        _logger.info('主线程借到连接（%.2fs）', _time.time() - t0)
        try:
            return run_concurrent(env, self.operator_id, work_fns)
        finally:
            cr.close()
            _logger.info('主线程关闭借用连接（%.2fs）', _time.time() - t0)

    def _receipt(self, quantity, key=None):
        cr, env = self._cursor_env()
        try:
            common = env['lab.workflow.common'].with_user(self.operator_id)
            data, _ = common.lab_receipt({
                'request_key': key or _key('rcv'),
                'item_key': self.item_key,
                'location_id': self.location_id,
                'quantity': quantity,
            })
            cr.commit()
            return data
        except Exception:
            cr.rollback()
            raise
        finally:
            cr.close()

    def _issue(self, bag_id, quantity, project):
        cr, env = self._cursor_env()
        try:
            common = env['lab.workflow.common'].with_user(self.operator_id)
            data, _ = common.lab_issue({
                'request_key': _key('iss'),
                'borrower_id': self.operator_id,
                'project': project,
                'lines': [{'bag_id': bag_id, 'quantity': quantity}],
            })
            cr.commit()
            return data
        except Exception:
            cr.rollback()
            raise
        finally:
            cr.close()

    def _bag_quantity(self, bag_id):
        cr, env = self._cursor_env()
        try:
            bag = env['lab.bag'].browse(bag_id)
            return sum(env['stock.quant'].search([
                ('product_id', '=', bag.product_id.id),
                ('lot_id', '=', bag.lot_id.id),
                ('location_id', '=', bag.location_id.id),
            ]).mapped('quantity'))
        finally:
            cr.close()

    def _search(self, model, domain):
        cr, env = self._cursor_env()
        try:
            return env[model].search(domain).ids
        finally:
            cr.close()

    def _nth_issue_fn(self, bag_id, quantity, project):
        user_id = self.operator_id
        return lambda env: env['lab.workflow.common'].with_user(user_id).lab_issue({
            'request_key': _key('iss'),
            'borrower_id': user_id,
            'project': project,
            'lines': [{'bag_id': bag_id, 'quantity': quantity}],
        })

    # ------------------------------------------------------------------
    def test_01_two_threads_issue_70_of_100(self):
        """袋 100，两线程各领 70：只 1 个成功，最终库存 30。"""
        bag_id = self._receipt(100)['bag']['id']
        runners = self._run_concurrent([
            self._nth_issue_fn(bag_id, 70, '并发领70-A'),
            self._nth_issue_fn(bag_id, 70, '并发领70-B'),
        ])
        successes = [r for r in runners if r.error is None and r.result]
        failures = [r for r in runners if r.error is not None]
        _logger.info('并发领 70：成功 %d，失败 %d（%s）', len(successes), len(failures),
                     [type(r.error).__name__ for r in failures])
        self.assertEqual(len(successes), 1,
                         '期望只有一个成功；失败原因=%s' % [str(r.error) for r in failures])
        self.assertEqual(len(failures), 1)
        self.assertIsInstance(failures[0].error, LabApiError,
                              '并发失败必须是业务错误：%r' % (failures[0].error,))
        self.assertEqual(failures[0].error.code, 'PRECONDITION_FAILED')
        self.assertEqual(self._bag_quantity(bag_id), 30)
        self.assertEqual(len(self._search('lab.issue.line', [('bag_id', '=', bag_id)])), 1)

    def test_02_two_threads_return_15_of_20(self):
        """原领用 20，两线程各还 15：只 1 个成功，最终未归还 5。"""
        bag_id = self._receipt(100)['bag']['id']
        issue = self._issue(bag_id, 20, '并发归还')
        line_id = issue['lines'][0]['issue_line_id']

        def return_fn(env):
            return env['lab.workflow.common'].with_user(self.operator_id).lab_return({
                'request_key': _key('ret'), 'issue_line_id': line_id, 'quantity': 15})

        runners = self._run_concurrent([return_fn, return_fn])
        successes = [r for r in runners if r.error is None and r.result]
        failures = [r for r in runners if r.error is not None]
        _logger.info('并发还 15：成功 %d，失败 %d（%s）', len(successes), len(failures),
                     [type(r.error).__name__ for r in failures])
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), 1)
        self.assertIsInstance(failures[0].error, LabApiError)
        self.assertEqual(failures[0].error.code, 'PRECONDITION_FAILED')
        cr, env = self._cursor_env()
        try:
            line = env['lab.issue.line'].browse(line_id)
            self.assertEqual(line.returned_quantity, 15)
            self.assertEqual(line.outstanding_quantity, 5)
        finally:
            cr.close()
        self.assertEqual(len(self._search('lab.return.line',
                                          [('issue_line_id', '=', line_id)])), 1)

    def test_03_same_request_key_two_threads_receipt(self):
        """同 request_key 两次 receipt 100：只 1 个袋、总量 100。"""
        key = _key('same-receipt')

        def receipt_fn(env):
            return env['lab.workflow.common'].with_user(self.operator_id).lab_receipt({
                'request_key': key,
                'item_key': self.item_key,
                'location_id': self.location_id,
                'quantity': 100,
            })

        runners = self._run_concurrent([receipt_fn, receipt_fn])
        unexpected = [r.error for r in runners
                      if r.error is not None and not isinstance(r.error, LabApiError)]
        self.assertFalse(unexpected, '并发重复请求出现非业务异常：%r' % unexpected)
        for runner in runners:
            if runner.error is not None:
                _logger.info('同 key 并发其中一次被拒：%s: %s',
                             type(runner.error).__name__, runner.error)
        bags = self._search('lab.bag', [('product_tmpl_id', '=', self.template_id)])
        self.assertEqual(len(bags), 1, '同 request_key 产生了 %d 个袋' % len(bags))
        self.assertEqual(self._bag_quantity(bags[0]), 100)
        logs = self._search('lab.request.log', [('request_key', '=', key)])
        self.assertEqual(len(logs), 1)

    def test_04_same_key_different_payload_concurrent(self):
        """同 key 不同 payload：一个成功、一个 CONFLICT。"""
        key = _key('conflict')

        def make_fn(quantity):
            def fn(env):
                return env['lab.workflow.common'].with_user(self.operator_id).lab_receipt({
                    'request_key': key,
                    'item_key': self.item_key,
                    'location_id': self.location_id,
                    'quantity': quantity,
                })
            return fn

        runners = self._run_concurrent([make_fn(10), make_fn(11)])
        successes = [r for r in runners if r.error is None]
        errors = [r.error for r in runners if r.error is not None]
        _logger.info('同 key 不同 payload：成功 %d，错误 %s',
                     len(successes), [type(e).__name__ for e in errors])
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], LabApiError)
        self.assertEqual(errors[0].code, 'CONFLICT')
        bags = self._search('lab.bag', [('product_tmpl_id', '=', self.template_id)])
        self.assertEqual(len(bags), 1)
        self.assertEqual(self._bag_quantity(bags[0]), 10)

    def test_05_two_keys_confirm_one_prepared_bag(self):
        cr, env = self._cursor_env()
        try:
            record = env['lab.workflow.common'].with_user(self.operator_id).lab_pending_create({
                'request_key': _key('prepare'), 'item_key': self.item_key,
                'product_template_id': self.template_id, 'quantity': 12,
            })['records'][0]
            cr.commit()
        finally:
            cr.close()

        def confirm(key):
            return lambda env: env['lab.workflow.common'].with_user(self.operator_id).lab_pending_confirm({
                'request_key': key, 'pending_id': record['id'],
                'location_id': self.location_id, 'quantity': 12,
            })

        runners = self._run_concurrent([confirm(_key()), confirm(_key())])
        self.assertFalse([r.error for r in runners if r.error is not None])
        ids = {r.result['record']['bag_id'] for r in runners}
        self.assertEqual(len(ids), 1)
        bag_id = ids.pop()
        self.assertEqual(self._bag_quantity(bag_id), 12)
        self.assertEqual(len(self._search('lab.bag', [('trace_code', '=', record['trace_code'])])), 1)
