#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真实 HTTP：两个库存管理员**并发互撤**，验证「至少留一名管理员」。

背景
====

``tests/test_workflow_concurrency.py::test_06`` 想验证「两个 manager 并发互撤，
后到者看到最新已提交集合 → 按最后一名拒绝」。该用例在 ``--test-enable`` 进程里
被框架锁卡住（见 ``local/concurfix-result.md``），因此这里用**真实 HTTP 请求**
补上同一条业务不变量：

* 两个**独立登录 cookie** 的会话（A、B），各自对**对方**撤销 ``lab_manager``；
* 请求真实打到 ``POST /lab/api/inventory/member_set_role``（现有 Role API，不新写业务）；
* 用**原始 SQL**（psycopg2，独立连接）核对持久化结果：A/B 里恰好只剩赢家 1 名管理员；
* 判定：必须「一个 ``changed=true``」+ SQL 核对「只剩 1 名」；拒绝证据默认接受
  ``last_manager`` 或 ``FORBIDDEN``（后者=被撤销方在请求开始时已不是管理员，会打印说明），
  可用 ``--require-last-manager`` 只接受前者。``no-op`` 不算证据，重试到
  ``--max-attempts``；``INTERNAL_ERROR``/运输异常=**对外语义缺陷**，记 FAIL(1) 并把
  code 原样交 backend，绝不计 PASS。

为了能真正触发「最后一名管理员」，脚本新建一个**独立合成公司**，只把 A、B 放进去
（``lab_workflow`` 安装钩子会给 admin 授 lab_manager，若用默认公司则永远还剩 admin，
保护逻辑不会触发）。

用法（Lead 在隔离运行时执行）::

    $R/opt/odoo-venv/bin/python tools/http_p3_role_concurrency_check.py \\
        --url http://127.0.0.1:8069 --db labwf_test --admin admin --admin-pass admin \\
        --db-host /tmp/labwf/sock --db-port 55440 \\
        --db-user lc_odoo --db-password lc_odoo_pw \\
        [--with-http-scenarios] [--json-out result.json]

退出码：0=通过；1=有失败（含 SQL 核对失败、公司 0 管理员）；2=BLOCKED（相交未发生 /
无法做数据库权威核对 / 环境引导失败）。
"""

from __future__ import print_function

import argparse
import json
import logging
import os
import sys
import threading
import traceback
import uuid

try:
    import requests
except ImportError:  # pragma: no cover
    print('需要 requests（Odoo venv 或系统 python 均可）：pip install requests')
    raise SystemExit(2)

_logger = logging.getLogger('lab_role_concurrency')
API = '/lab/api'
MANAGER_GROUP = 'group_lab_manager'


# ---------------------------------------------------------------------------
# HTTP 会话
# ---------------------------------------------------------------------------
class Session(object):
    """一个独立的 Odoo 登录会话（独立 cookie jar）。"""

    def __init__(self, base_url, db, login, password, label):
        self.base_url = base_url.rstrip('/')
        self.db = db
        self.login = login
        self.password = password
        self.label = label
        self.http = requests.Session()
        self.uid = None

    def authenticate(self):
        response = self.http.post(
            self.base_url + '/web/session/authenticate',
            json={'jsonrpc': '2.0', 'method': 'call',
                  'params': {'db': self.db, 'login': self.login,
                             'password': self.password}},
            timeout=60)
        response.raise_for_status()
        payload = response.json()
        result = payload.get('result') or {}
        if not result.get('uid'):
            raise RuntimeError('登录失败 %s: %s'
                               % (self.label, json.dumps(payload)[:300]))
        self.uid = result['uid']
        _logger.info('%s 登录成功 uid=%s', self.label, self.uid)
        return self.uid

    def call(self, route, params=None):
        body = {'jsonrpc': '2.0', 'method': 'call',
                'params': params or {}, 'id': str(uuid.uuid4())}
        response = self.http.post(self.base_url + route, json=body, timeout=120)
        response.raise_for_status()
        return response.json()

    def envelope(self, route, params=None):
        payload = self.call(route, params)
        if 'error' in payload:
            return {'ok': False, 'data': None,
                    'error': {'code': 'JSONRPC_ERROR',
                              'message': str(payload['error'])[:400],
                              'fields': {}}}
        return payload.get('result') or {}

    def call_kw(self, model, method, args, kwargs=None):
        payload = self.call('/web/dataset/call_kw', {
            'model': model, 'method': method, 'args': args,
            'kwargs': kwargs or {'context': {}}})
        if 'error' in payload:
            raise RuntimeError('%s.%s 失败：%s'
                               % (model, method, str(payload['error'])[:300]))
        return payload.get('result')


def concurrent(call_a, call_b, timeout=120):
    """barrier 对齐后同时发两个请求（真相交，不是顺序调用）。"""
    barrier = threading.Barrier(2)
    results = {}

    def runner(key, fn):
        try:
            barrier.wait(timeout=30)
        except threading.BrokenBarrierError:
            results[key] = ('barrier_error', None)
            return
        try:
            results[key] = ('ok', fn())
        except Exception as exc:  # noqa: BLE001 - 运输层异常单列，不算业务拒绝
            results[key] = ('transport_error', '%s: %s'
                            % (type(exc).__name__, exc))

    threads = [threading.Thread(target=runner, args=('a', call_a)),
               threading.Thread(target=runner, args=('b', call_b))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=timeout)
    return results


# ---------------------------------------------------------------------------
# 夹具：合成公司 + 两个管理员（都用 admin 的 ORM 会话，隔离库内合成数据）
# ---------------------------------------------------------------------------
def group_id(admin, name, module='lab_workflow'):
    rows = admin.call_kw('ir.model.data', 'search_read',
                         [[['module', '=', module], ['name', '=', name]],
                          ['res_id']], {'context': {}})
    if not rows:
        raise RuntimeError('找不到 %s.%s，模块未安装完整？' % (module, name))
    return rows[0]['res_id']


def make_company(admin, label):
    company_id = admin.call_kw('res.company', 'create',
                               [{'name': 'Lab 并发公司 %s' % label}])
    return company_id


def make_manager(admin, login, password, company_id, manager_gid):
    user_id = admin.call_kw('res.users', 'create', [{
        'name': login,
        'login': login,
        'password': password,
        'company_id': company_id,
        'company_ids': [(6, 0, [company_id])],
    }])
    admin.call_kw('res.users', 'write',
                  [[user_id], {'group_ids': [(4, manager_gid)]}])
    return user_id


def reset_roles(admin, user_ids, manager_gid):
    for user_id in user_ids:
        admin.call_kw('res.users', 'write',
                      [[user_id], {'group_ids': [(4, manager_gid)]}])


# ---------------------------------------------------------------------------
# 数据库权威核对（原始 SQL；psycopg2 独立连接）
# ---------------------------------------------------------------------------
def _connect(args):
    import psycopg2
    kwargs = {
        'dbname': args.db_name or args.db,
        'host': args.db_host,
        'port': int(args.db_port),
        'user': args.db_user,
    }
    if args.db_password:
        kwargs['password'] = args.db_password
    return psycopg2.connect(**kwargs)


def _relation_columns(cur, table):
    cur.execute(
        'SELECT column_name FROM information_schema.columns'
        ' WHERE table_name = %s AND table_schema = current_schema',
        (table,))
    return {row[0] for row in cur.fetchall()}


def db_manager_state(args, manager_gid, user_ids):
    """返回 (A/B 中仍是 active 管理员的 uid 列表, 说明)。

    用 ``res_groups_users_rel``（用户-组 m2m）直接查，列名先探测，不硬编码顺序。
    这是**数据库权威**证据：绕过接口缓存/会话状态。
    """
    conn = _connect(args)
    try:
        cur = conn.cursor()
        columns = _relation_columns(cur, 'res_groups_users_rel')
        if {'uid', 'gid'} <= columns:
            user_col, group_col = 'uid', 'gid'
        elif len(columns) == 2:
            user_col, group_col = sorted(columns, key=lambda c: c == 'gid')
        else:
            raise RuntimeError('res_groups_users_rel 列未知：%s' % sorted(columns))
        cur.execute(
            'SELECT u.id FROM res_users u'
            ' JOIN res_groups_users_rel r ON r.{user_col} = u.id'
            ' WHERE r.{group_col} = %s AND u.id = ANY(%s) AND u.active'
            .format(user_col=user_col, group_col=group_col),
            (manager_gid, list(user_ids)))
        rows = [row[0] for row in cur.fetchall()]
        cur.close()
        return rows, 'sql res_groups_users_rel(%s,%s)' % (user_col, group_col)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 场景
# ---------------------------------------------------------------------------
def classify(results):
    """把两路响应归类（只 changed=true 算真成功；no-op/其它异常都不算）。

    失败类型按**当前真实语义**分档（2026-10-28 核实）：
    ``last_manager``（串行化后按最后一名拒绝）→ 最强证据；
    ``forbidden``（请求开始前已被撤销，服务端 guard 拒）→ 次强；
    ``internal_error``（``member_set_role`` 未包整事务重试，RR 锁冲突 →
    SerializationFailure 被控制器兜底成 INTERNAL_ERROR）→ **语义缺陷，不算 PASS**。
    """
    outcome = {}
    for key in ('a', 'b'):
        status, value = results.get(key, ('missing', None))
        if status != 'ok' or not isinstance(value, dict):
            outcome[key] = {'kind': 'transport_error', 'detail': str(value)[:200]}
            continue
        data = value.get('data') or {}
        if value.get('ok') and data.get('changed') is True:
            outcome[key] = {'kind': 'changed',
                            'uid': (data.get('member') or {}).get('id')}
            continue
        if value.get('ok'):
            outcome[key] = {'kind': 'noop',
                            'detail': 'ok=true changed=%r' % data.get('changed')}
            continue
        error = value.get('error') or {}
        code = error.get('code')
        fields = error.get('fields') or {}
        if code == 'PRECONDITION_FAILED' and fields.get('role') == 'last_manager':
            kind = 'last_manager'
        elif code == 'FORBIDDEN':
            kind = 'forbidden'
        elif code == 'CONFLICT':
            kind = 'conflict'
        elif code == 'INTERNAL_ERROR':
            kind = 'internal_error'
        else:
            kind = 'other_business'
        outcome[key] = {'kind': kind, 'code': code, 'fields': fields,
                        'detail': error.get('message', '')[:200]}
    return outcome


def run_attempt(admin, sessions, user_ids, manager_gid, attacker_index):
    """一次并发互撤：A 撤 B、B 撤 A。返回 (outcome, 原始结果)。"""
    a, b = sessions
    a_id, b_id = user_ids
    target_of = {0: (a, b_id), 1: (b, a_id)}
    first, second = attacker_index % 2, (attacker_index + 1) % 2
    s1, t1 = target_of[first]
    s2, t2 = target_of[second]
    reset_roles(admin, user_ids, manager_gid)
    results = concurrent(
        lambda: s1.envelope(API + '/inventory/member_set_role',
                            {'user_id': t1, 'role': 'lab_manager', 'enabled': False}),
        lambda: s2.envelope(API + '/inventory/member_set_role',
                            {'user_id': t2, 'role': 'lab_manager', 'enabled': False}))
    return classify(results), results


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='真实 HTTP：两个库存管理员并发互撤，核对至少一人留存')
    parser.add_argument('--url', default='http://127.0.0.1:8069')
    parser.add_argument('--db', required=True)
    parser.add_argument('--admin', default='admin')
    parser.add_argument('--admin-pass', default='admin')
    parser.add_argument('--max-attempts', type=int, default=4)
    parser.add_argument('--require-last-manager', action='store_true',
                        help='只接受 PRECONDITION_FAILED/last_manager 作为拒绝证据；'
                             '默认也接受 FORBIDDEN（请求开始前已被撤销），但都会打印')
    parser.add_argument('--with-http-scenarios', action='store_true',
                        help='再跑既有 http_concurrency_check.py 的 6 个场景（组合验收）')
    parser.add_argument('--json-out', default=None)
    # 数据库权威核对（缺任何一项即 BLOCKED，不降级成“只看接口返回值”）
    parser.add_argument('--db-host', default=os.environ.get('LAB_P3_DB_HOST', ''))
    parser.add_argument('--db-port', default=os.environ.get('LAB_P3_DB_PORT', '5432'))
    parser.add_argument('--db-user', default=os.environ.get('LAB_P3_DB_USER', ''))
    parser.add_argument('--db-password',
                        default=os.environ.get('LAB_P3_DB_PASSWORD', ''))
    parser.add_argument('--db-name', default=None)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s')

    summary = {'kind': 'lab-p3-role-concurrency', 'attempts': [],
               'db_authoritative': False, 'exit_code': 2,
               'blocked_reason': None, 'combined_http': None}
    try:
        return _run(args, summary)
    finally:
        _write_json(args.json_out, summary)


def _run(args, summary):
    if not args.db_host or not args.db_user:
        summary['blocked_reason'] = (
            '缺少数据库核对参数（--db-host/--db-user）：本检查必须做原始 SQL 核对，'
            '不接受只凭接口返回值判定')
        _logger.error('BLOCKED：%s', summary['blocked_reason'])
        return 2
    try:
        import psycopg2  # noqa: F401 - 早失败，别等到最后
    except ImportError:
        summary['blocked_reason'] = '当前 python 没有 psycopg2，无法做数据库权威核对'
        _logger.error('BLOCKED：%s', summary['blocked_reason'])
        return 2

    admin = Session(args.url, args.db, args.admin, args.admin_pass, 'admin')
    try:
        admin.authenticate()
        manager_gid = group_id(admin, MANAGER_GROUP)
        company_id = make_company(admin, uuid.uuid4().hex[:6])
        truth = uuid.uuid4().hex[:6]
        password = 'LabConc-%s' % truth
        login_a = 'lab_role_mgr_a_%s' % truth
        login_b = 'lab_role_mgr_b_%s' % truth
        a_id = make_manager(admin, login_a, password, company_id, manager_gid)
        b_id = make_manager(admin, login_b, password, company_id, manager_gid)
        session_a = Session(args.url, args.db, login_a, password, 'manager-A')
        session_b = Session(args.url, args.db, login_b, password, 'manager-B')
        session_a.authenticate()
        session_b.authenticate()
    except Exception as exc:  # noqa: BLE001 - 引导失败=BLOCKED
        summary['blocked_reason'] = 'bootstrap: %s: %s' % (type(exc).__name__, exc)
        summary['bootstrap_traceback'] = traceback.format_exc()
        _logger.error('BLOCKED：%s', summary['blocked_reason'])
        return 2

    user_ids = [a_id, b_id]
    fail_reason = None
    pass_evidence = None
    try:
        # 前置：两员确实都是管理员（否则场景无意义）
        before, source = db_manager_state(args, manager_gid, user_ids)
        summary['manager_before'] = before
        summary['db_source'] = source
        if len(before) != 2:
            summary['blocked_reason'] = '前置失败：A/B 未同时是管理员（SQL 看到 %s）' % before
            _logger.error('BLOCKED：%s', summary['blocked_reason'])
            return 2

        semantic_defects = []
        for attempt in range(1, max(1, args.max_attempts) + 1):
            outcome, raw = run_attempt(admin, (session_a, session_b), user_ids,
                                       manager_gid, attempt - 1)
            after, _ = db_manager_state(args, manager_gid, user_ids)
            kinds = {key: outcome[key]['kind'] for key in ('a', 'b')}
            changed = [key for key in ('a', 'b') if kinds[key] == 'changed']
            refusals = [(key, kinds[key]) for key in ('a', 'b')
                        if kinds[key] in ('last_manager', 'forbidden', 'conflict',
                                          'internal_error', 'other_business')]
            record = {
                'attempt': attempt,
                'kinds': kinds,
                'outcome': outcome,
                'manager_after_sql': after,
                'manager_before_sql': before,
            }
            summary['attempts'].append(record)
            _logger.info('第 %d 次：kinds=%s；SQL 之后仍为管理员=%s',
                         attempt, kinds, after)

            # 硬失败 1：数据库真的掉了管理员
            if len(after) < 1:
                fail_reason = ('数据库核对失败：并发互撤后 A/B 都不是管理员（%s）'
                               % after)
                break
            # 硬失败 2：运输层异常（不是业务拒绝）
            if any(kinds[key] == 'transport_error' for key in ('a', 'b')):
                fail_reason = '出现运输层异常：%s' % {
                    key: outcome[key] for key in ('a', 'b')}
                break
            # 硬失败 3：两路都 changed=true（没有串行化）
            if len(changed) > 1:
                fail_reason = ('两路都 changed=true：并发撤销没有被串行化（%s）'
                               % kinds)
                break
            # 接口说 changed，但数据库里还留着 2 名 → 撤销没落库
            if len(changed) == 1 and len(after) != 1:
                fail_reason = ('数据库核对失败：接口报告 changed，但 A/B 中仍留下 '
                               '%d 名管理员（期望 1）' % len(after))
                break
            if len(changed) == 1 and len(after) == 1 and refusals:
                refusal_key, refusal_kind = refusals[0]
                if refusal_kind == 'last_manager':
                    pass_evidence = {
                        'attempt': attempt,
                        'changed_key': changed[0],
                        'rejected_key': refusal_key,
                        'refusal_kind': 'last_manager',
                        'fields': outcome[refusal_key].get('fields'),
                        'manager_after_sql': after,
                    }
                    summary['db_authoritative'] = True
                    break
                if refusal_kind == 'forbidden' and not args.require_last_manager:
                    # 证据说明：B 在请求开始前已被撤销（manager 组已无它），
                    # 服务端 guard/角色判断直接拒绝；数据库只剩赢家 1 名。
                    _logger.warning(
                        '拒绝码是 FORBIDDEN（不是 last_manager）：被撤销方在请求开始时'
                        '已不是管理员，服务端拒绝；SQL 核对仍只剩 1 名管理员。'
                        '若要强制要求 last_manager，加 --require-last-manager')
                    pass_evidence = {
                        'attempt': attempt,
                        'changed_key': changed[0],
                        'rejected_key': refusal_key,
                        'refusal_kind': 'forbidden',
                        'fields': outcome[refusal_key].get('fields'),
                        'manager_after_sql': after,
                    }
                    summary['db_authoritative'] = True
                    break
                # conflict / internal_error / other_business：对外语义问题。
                # 记下来继续试（可能是时序），但**绝不计 PASS**。
                semantic_defects.append({
                    'attempt': attempt, 'refusal': refusal_kind,
                    'code': outcome[refusal_key].get('code'), 'kinds': kinds})
                continue
            # 其余（no-op / 单边 no-op）：相交没发生，重试
        if pass_evidence is None and fail_reason is None:
            if semantic_defects:
                fail_reason = (
                    '对外语义缺陷：并发撤销的失败码是 %s，数据库不变量仍成立'
                    '（A/B 剩 %d 名）。原因：`lab_member_set_role` 没有整事务重试，'
                    'RR 下 `SELECT … FOR UPDATE` 撞并发删除会直接 SerializationFailure，'
                    '控制器把它兜底成 INTERNAL_ERROR；需要 backend 决定是否改为 '
                    'CONFLICT/PRECONDITION_FAILED。本检查不把它计为 PASS。'
                    % (sorted({d['refusal'] for d in semantic_defects}),
                       len(summary['attempts'][-1]['manager_after_sql'])))
            else:
                summary['blocked_reason'] = (
                    '重试 %d 次仍未取得「一个 changed + 一个拒绝证据」'
                    '（并发相交未发生或 A/B 状态被前一次尝试改变）；'
                    '最后状态=%s，见 attempts'
                    % (max(1, args.max_attempts),
                       summary['attempts'][-1]['kinds'] if summary['attempts'] else '{}'))
    finally:
        # 清理合成夹具（隔离库；失败只记 warning，不改结论）
        try:
            admin.call_kw('res.users', 'write',
                          [user_ids, {'active': False}])
        except Exception:  # noqa: BLE001
            _logger.warning('停用合成账号失败（不影响结论）', exc_info=True)

    if fail_reason:
        summary['failure_reason'] = fail_reason
        _logger.error('FAIL：%s', fail_reason)
        summary['exit_code'] = 1
        return 1
    if pass_evidence is None:
        summary['exit_code'] = 2
        _logger.error('BLOCKED：%s', summary['blocked_reason'])
        return 2

    summary['evidence'] = pass_evidence
    _logger.info('PASS：第 %d 次，一个 changed、另一个拒绝=%s；'
                 'SQL 核对后仍为管理员=%s', pass_evidence['attempt'],
                 pass_evidence.get('refusal_kind'),
                 pass_evidence['manager_after_sql'])

    combined_ok = True
    if args.with_http_scenarios:
        combined_ok = _run_base_scenarios(args, summary)

    print('\n===== 角色并发（真实 HTTP + 数据库权威核对）=====')
    print('合成公司内 A/B 并发互撤：一个 changed、另一个 %s；'
          'SQL 核对后只剩赢家 1 名管理员 ✓（%s）'
          % (pass_evidence.get('refusal_kind'), summary.get('db_source', '')))
    if args.with_http_scenarios:
        print('既有 6 个 HTTP 并发场景：%s'
              % ('通过' if combined_ok else '未通过/未执行'))
    summary['exit_code'] = 0 if combined_ok else 1
    return summary['exit_code']


def _run_base_scenarios(args, summary):
    """组合验收：用同参数调用既有 http_concurrency_check.py 的 6 个场景。"""
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        if here not in sys.path:
            sys.path.insert(0, here)
        import http_concurrency_check as base  # noqa: PLC0415 - 同目录复用
    except Exception as exc:  # noqa: BLE001
        summary['combined_http'] = {'result': 'blocked',
                                    'detail': '导入既有脚本失败：%s' % exc}
        _logger.error('既有 6 场景无法执行（blocked）：%s', exc)
        return False
    argv = ['http_concurrency_check.py', '--url', args.url, '--db', args.db,
            '--admin', args.admin, '--admin-pass', args.admin_pass]
    old_argv = sys.argv
    try:
        sys.argv = argv
        rc = base.main()
    except SystemExit as exc:  # 既有脚本内部 sys.exit
        rc = exc.code if isinstance(exc.code, int) else 2
    except Exception as exc:  # noqa: BLE001
        summary['combined_http'] = {'result': 'error',
                                    'detail': '%s: %s' % (type(exc).__name__, exc)}
        _logger.error('既有 6 场景异常：%s', exc)
        return False
    finally:
        sys.argv = old_argv
    summary['combined_http'] = {'result': 'pass' if rc == 0 else 'fail',
                                'exit_code': rc}
    return rc == 0


def _write_json(path, summary):
    if not path:
        return
    try:
        with open(path, 'w') as handle:
            json.dump(summary, handle, ensure_ascii=False, indent=2,
                      sort_keys=True, default=str)
    except Exception:  # noqa: BLE001 - 写不出结果不改变退出码
        _logger.warning('写结果 JSON 失败：%s', path, exc_info=True)


if __name__ == '__main__':
    sys.exit(main())
