#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真实 HTTP 并发验收脚本（两个登录 cookie + Barrier 相交执行）。

用途：由 root 在**独立临时 Odoo 实例 + 独立数据库**上独立验收并发行为。
它不依赖 Odoo 测试框架，只用一个纯 Python（requests）脚本打真实 JSON-RPC 接口。

用法::

    python3 tools/http_concurrency_check.py \
        --url http://127.0.0.1:8069 --db labwf_verify \
        --user-a lab_conc_a --pass-a lab_conc_a \
        --user-b lab_conc_b --pass-b lab_conc_b \
        [--item-key lcsc:C123456] [--location-id 8]

如果账号不存在，脚本会用 ``--admin``/``--admin-pass`` 登录后创建两个非 super
操作员（并给 lab 操作员组），随后所有测试都在这两个**普通账号**下执行。

覆盖 4 个场景（每个都真实相交，不是顺序调用）：

1. 袋 100，**两个登录 cookie** 各领 70 -> 最多一个成功，最终库存 30
2. 原领用 20，**两个登录 cookie** 各还 15 -> 最多一个成功，未归还 5
3. 同 request_key 同内容 **同一 cookie** 并发两次 receipt 100
   -> 只 1 个袋、总量 100（重复提交不得重复入库；
   幂等按 (request_key, user, company, method) 唯一，见 lab_request_log 约束）
4. 同 request_key 不同内容 **同一 cookie** 并发 -> 一个成功、一个 CONFLICT

退出码 0 = 全部通过（退出前打印每步的中文结论与服务端返回的 code）。
"""

import argparse
import json
import logging
import sys
import threading
import uuid

try:
    import requests
except ImportError:  # pragma: no cover
    print('需要 requests：pip install requests')
    raise SystemExit(2)

LOG_FORMAT = '%(asctime)s %(levelname)s %(message)s'
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
_logger = logging.getLogger('lab_concurrency')

API = '/lab/api'


class Session(object):
    """一个 Odoo 登录会话（独立 cookie jar）。"""

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
            raise RuntimeError('登录失败 %s: %s' % (self.label, json.dumps(payload)[:300]))
        self.uid = result['uid']
        _logger.info('%s 登录成功 uid=%s', self.label, self.uid)
        return self.uid

    def call(self, route, params=None, request_id=None):
        body = {'jsonrpc': '2.0', 'method': 'call',
                'params': params or {}, 'id': request_id or str(uuid.uuid4())}
        response = self.http.post(self.base_url + route, json=body, timeout=120)
        response.raise_for_status()
        return response.json()

    def envelope(self, route, params=None):
        """返回契约信封 dict（ok/data/error）。"""
        payload = self.call(route, params)
        if 'error' in payload:
            return {'ok': False, 'data': None,
                    'error': {'code': 'JSONRPC_ERROR',
                              'message': str(payload['error'])[:400], 'fields': {}}}
        return payload.get('result') or {}


def _login_or_create(admin, db, login, password):
    """确保存在一个非 super 的 lab 操作员账号；返回 Session。"""
    session = Session(admin.base_url, db, login, password, login)
    try:
        session.authenticate()
        return session
    except Exception:  # noqa: BLE001 - 账号不存在则创建
        pass
    _logger.info('账号 %s 不存在，用管理员创建', login)
    payload = admin.call('/web/dataset/call_kw', {
        'model': 'res.users', 'method': 'create',
        'args': [[{'name': login, 'login': login, 'password': password,
                   'company_id': admin.company_id}]],
        'kwargs': {'context': {}},
    })
    user_id = (payload.get('result') or [None])[0]
    if not user_id:
        raise RuntimeError('创建账号失败：%s' % json.dumps(payload)[:300])
    admin.call('/web/dataset/call_kw', {
        'model': 'res.users', 'method': 'write',
        'args': [[user_id], {'group_ids': [(4, admin.group_lab_operator_id)]}],
        'kwargs': {'context': {}},
    })
    session = Session(admin.base_url, db, login, password, login)
    session.authenticate()
    return session


def concurrent(call_a, call_b):
    """两个调用在 barrier 之后同时发出（真正相交执行）。"""
    barrier = threading.Barrier(2)
    results = {}

    def runner(key, fn):
        barrier.wait(timeout=30)
        try:
            results[key] = ('ok', fn())
        except Exception as exc:  # noqa: BLE001
            results[key] = ('error', '%s: %s' % (type(exc).__name__, exc))

    threads = [threading.Thread(target=runner, args=('a', call_a)),
               threading.Thread(target=runner, args=('b', call_b))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=180)
    return results


def summarize(results):
    """把两次结果归纳成 (成功数, 失败信封列表)。"""
    successes = 0
    failures = []
    for key in ('a', 'b'):
        status, value = results.get(key, ('missing', None))
        if status == 'error':
            failures.append({'code': 'TRANSPORT_ERROR', 'message': str(value)})
        elif not value.get('ok'):
            failures.append(value.get('error') or {})
        else:
            successes += 1
    return successes, failures


def main():
    parser = argparse.ArgumentParser(description='lab_workflow 真实 HTTP 并发验收')
    parser.add_argument('--url', default='http://127.0.0.1:8069')
    parser.add_argument('--db', required=True)
    parser.add_argument('--admin', default='admin')
    parser.add_argument('--admin-pass', default='admin')
    parser.add_argument('--user-a', default='lab_conc_a')
    parser.add_argument('--pass-a', default='lab_conc_a')
    parser.add_argument('--user-b', default='lab_conc_b')
    parser.add_argument('--pass-b', default='lab_conc_b')
    parser.add_argument('--item-key', default=None,
                        help='测试物料 item_key（默认用/创建 lcsc:C990001）')
    parser.add_argument('--location-id', type=int, default=None)
    args = parser.parse_args()

    admin = Session(args.url, args.db, args.admin, args.admin_pass, 'admin')
    admin.authenticate()
    bootstrap = admin.envelope(API + '/inventory/bootstrap')
    if not bootstrap.get('ok'):
        raise SystemExit('bootstrap 失败：%s' % json.dumps(bootstrap)[:400])
    data = bootstrap['data']
    admin.company_id = data['permissions']['company_id']

    # lab 操作员组 xmlid -> id（用 ir.model.data 查）
    ref = admin.call('/web/dataset/call_kw', {
        'model': 'ir.model.data', 'method': 'search_read',
        'args': [[['module', '=', 'lab_workflow'],
                  ['name', '=', 'group_lab_operator']], ['res_id']],
        'kwargs': {'context': {}},
    })
    group_rows = ref.get('result') or []
    if not group_rows:
        raise SystemExit('找不到 lab_workflow.group_lab_operator，模块未安装？')
    admin.group_lab_operator_id = group_rows[0]['res_id']

    session_a = _login_or_create(admin, args.db, args.user_a, args.pass_a)
    session_b = _login_or_create(admin, args.db, args.user_b, args.pass_b)
    device = Session(args.url, args.db, session_a.login, session_a.password, 'second-device')
    device.authenticate()

    location_id = args.location_id
    if not location_id:
        locations = data['locations']
        if not locations:
            raise SystemExit('没有内部库位，请先在 Odoo 里建一个')
        location_id = locations[0]['id']
    item_key = args.item_key or 'lcsc:C990001'

    failures_total = 0
    _logger.info('库位 id=%s，物料 item_key=%s', location_id, item_key)

    # ------------------------------------------------------------------
    # 场景 1：袋 100，两个会话各领 70
    # ------------------------------------------------------------------
    _logger.info('=== 场景1：袋 100，两个会话各领 70 ===')
    receipt = session_a.envelope(API + '/inventory/receipt', {
        'request_key': str(uuid.uuid4()), 'item_key': item_key,
        'location_id': location_id, 'quantity': 100, 'note': '并发验收-入库'})
    if not receipt.get('ok'):
        raise SystemExit('入库准备失败：%s' % json.dumps(receipt, ensure_ascii=False)[:400])
    bag_id = receipt['data']['bag']['id']
    bag_code = receipt['data']['bag']['trace_code']
    _logger.info('准备袋 %s(id=%s) 数量 100', bag_code, bag_id)

    results = concurrent(
        lambda: session_a.envelope(API + '/inventory/issue', {
            'request_key': str(uuid.uuid4()), 'borrower_id': session_a.uid,
            'project': '并发A', 'lines': [{'bag_id': bag_id, 'quantity': 70}]}),
        lambda: session_b.envelope(API + '/inventory/issue', {
            'request_key': str(uuid.uuid4()), 'borrower_id': session_b.uid,
            'project': '并发B', 'lines': [{'bag_id': bag_id, 'quantity': 70}]}),
    )
    successes, errors = summarize(results)
    _logger.info('成功 %d 次，失败：%s', successes,
                 [(e.get('code'), e.get('message', '')[:80]) for e in errors])
    if successes != 1:
        failures_total += 1
        _logger.error('场景1 失败：期望 1 次成功，实际 %d', successes)
    resolved = session_a.envelope(API + '/inventory/resolve_code', {'raw': 'LABB:' + bag_code})
    quantity = (resolved.get('data') or {}).get('bag', {}).get('quantity')
    _logger.info('结算：袋剩余数量 = %s（期望 30）', quantity)
    if quantity != 30:
        failures_total += 1
        _logger.error('场景1 失败：库存应为 30，实际 %s', quantity)
    if successes == 1 and errors:
        if errors[0].get('code') not in ('PRECONDITION_FAILED', 'CONFLICT'):
            failures_total += 1
            _logger.error('场景1 失败：拒绝原因应为库存不足，实际 %s', errors[0].get('code'))

    # ------------------------------------------------------------------
    # 场景 2：原领用 20，两个会话各还 15
    # ------------------------------------------------------------------
    _logger.info('=== 场景2：原领用 20，两个会话各还 15 ===')
    issue = session_a.envelope(API + '/inventory/issue', {
        'request_key': str(uuid.uuid4()), 'borrower_id': session_a.uid,
        'project': '并发归还准备', 'lines': [{'bag_id': bag_id, 'quantity': 20}]})
    if not issue.get('ok'):
        raise SystemExit('领用准备失败：%s' % json.dumps(issue, ensure_ascii=False)[:400])
    issue_line_id = issue['data']['lines'][0]['issue_line_id']
    _logger.info('准备领用明细 id=%s（未归还 20）', issue_line_id)

    results = concurrent(
        lambda: session_a.envelope(API + '/inventory/return', {
            'request_key': str(uuid.uuid4()), 'issue_line_id': issue_line_id,
            'quantity': 15}),
        lambda: device.envelope(API + '/inventory/return', {
            'request_key': str(uuid.uuid4()), 'issue_line_id': issue_line_id,
            'quantity': 15}),
    )
    successes, errors = summarize(results)
    _logger.info('成功 %d 次，失败：%s', successes,
                 [(e.get('code'), e.get('message', '')[:80]) for e in errors])
    if successes != 1:
        failures_total += 1
        _logger.error('场景2 失败：期望 1 次成功，实际 %d', successes)
    if any(e.get('code') not in ('PRECONDITION_FAILED', 'VALIDATION_ERROR') for e in errors):
        failures_total += 1
        _logger.error('场景2 失败：应当是明确的业务拒绝，实际 %s', [e.get('code') for e in errors])
    outstanding = None
    for entry in (results.get('a', (None, {}))[1], results.get('b', (None, {}))[1]):
        if isinstance(entry, dict) and entry.get('ok'):
            outstanding = entry['data'].get('outstanding_quantity')
    _logger.info('结算：未归还数量 = %s（期望 5）', outstanding)
    if outstanding != 5:
        failures_total += 1
        _logger.error('场景2 失败：未归还应为 5，实际 %s', outstanding)

    # ------------------------------------------------------------------
    # 场景 3：同 request_key 同内容，**同一 cookie** 并发两次 receipt 100
    # （真实重复提交：网络重试/双击；幂等按 user+company+method 唯一）
    # ------------------------------------------------------------------
    _logger.info('=== 场景3：同 request_key 同内容并发入库（同一 cookie 重复提交）===')
    shared_key = str(uuid.uuid4())
    results = concurrent(
        lambda: session_a.envelope(API + '/inventory/receipt', {
            'request_key': shared_key, 'item_key': item_key,
            'location_id': location_id, 'quantity': 100}),
        lambda: session_a.envelope(API + '/inventory/receipt', {
            'request_key': shared_key, 'item_key': item_key,
            'location_id': location_id, 'quantity': 100}),
    )
    successes, errors = summarize(results)
    _logger.info('成功 %d 次，失败：%s', successes,
                 [(e.get('code'), e.get('message', '')[:80]) for e in errors])
    new_bag_codes = []
    for entry in (results.get('a', (None, {}))[1], results.get('b', (None, {}))[1]):
        if isinstance(entry, dict) and entry.get('ok'):
            new_bag_codes.append(entry['data']['bag']['trace_code'])
    _logger.info('返回的袋：%s（期望两次返回同一个袋）', new_bag_codes)
    if len(set(new_bag_codes)) != 1:
        failures_total += 1
        _logger.error('场景3 失败：同 key 返回了不同的袋 %s', new_bag_codes)
    resolved = session_a.envelope(API + '/inventory/resolve_code',
                                  {'raw': 'LABB:' + (new_bag_codes[0] if new_bag_codes else '')})
    quantity = (resolved.get('data') or {}).get('bag', {}).get('quantity')
    _logger.info('结算：该袋数量 = %s（期望 100，不能翻倍）', quantity)
    if quantity != 100:
        failures_total += 1
        _logger.error('场景3 失败：同 key 重复记账，数量 %s', quantity)
    # 记账行必须只有一条（数据库唯一约束 + 服务端串行化的直接证据）
    log_count = admin.call('/web/dataset/call_kw', {
        'model': 'lab.request.log', 'method': 'search_count',
        'args': [[['request_key', '=', shared_key]]],
        'kwargs': {'context': {}},
    })
    log_n = (log_count.get('result') if isinstance(log_count, dict) else None)
    _logger.info('结算：lab.request.log 中该 key 的行数 = %s（期望 1）', log_n)
    if log_n != 1:
        failures_total += 1
        _logger.error('场景3 失败：记账行 %s 条，幂等记录不完整', log_n)

    # ------------------------------------------------------------------
    # 场景 4：同 key 不同 payload（同一 cookie 并发，一个成功一个 CONFLICT）
    # ------------------------------------------------------------------
    _logger.info('=== 场景4：同 key 不同 payload 并发 ===')
    conflict_key = str(uuid.uuid4())
    results = concurrent(
        lambda: session_a.envelope(API + '/inventory/receipt', {
            'request_key': conflict_key, 'item_key': item_key,
            'location_id': location_id, 'quantity': 10}),
        lambda: session_a.envelope(API + '/inventory/receipt', {
            'request_key': conflict_key, 'item_key': item_key,
            'location_id': location_id, 'quantity': 11}),
    )
    successes, errors = summarize(results)
    _logger.info('成功 %d 次，失败：%s', successes,
                 [(e.get('code'), e.get('message', '')[:100]) for e in errors])
    if successes != 1 or len(errors) != 1:
        failures_total += 1
        _logger.error('场景4 失败：期望 1 成功 1 拒绝，实际 成功=%d 拒绝=%d',
                      successes, len(errors))
    if errors and errors[0].get('code') not in ('CONFLICT', 'DUPLICATE_REQUEST'):
        failures_total += 1
        _logger.error('场景4 失败：拒绝码应为 CONFLICT，实际 %s', errors[0].get('code'))

    # ------------------------------------------------------------------
    # Two independently authenticated devices of the SAME owner prepare/confirm
    # one physical bag. Other owners remain excluded by the server record rule.
    _logger.info('=== 场景5：两设备同请求制袋，不创建库存 ===')
    prepare = {'request_key': str(uuid.uuid4()), 'item_key': item_key, 'quantity': 12, 'count': 1}
    results = concurrent(
        lambda: session_a.envelope(API + '/inventory/pending/create', prepare),
        lambda: device.envelope(API + '/inventory/pending/create', prepare))
    successes, errors = summarize(results)
    prepared = [entry[1]['data']['records'][0] for entry in results.values()
                if entry[0] == 'ok' and entry[1].get('ok')]
    if successes != 2 or len({p['id'] for p in prepared}) != 1:
        raise AssertionError('并发制袋未返回同一条记录：%s' % errors)
    record = prepared[0]
    count = admin.call('/web/dataset/call_kw', {
        'model': 'lab.bag', 'method': 'search_count',
        'args': [[['trace_code', '=', record['trace_code']]]], 'kwargs': {}})['result']
    if count != 0:
        raise AssertionError('制袋阶段错误创建了正式库存袋')

    _logger.info('=== 场景6：两设备不同请求同时确认同一袋 ===')
    def confirm(session):
        return session.envelope(API + '/inventory/pending/confirm', {
            'request_key': str(uuid.uuid4()), 'pending_id': record['id'],
            'quantity': 12, 'location_id': location_id})
    results = concurrent(lambda: confirm(session_a), lambda: confirm(device))
    successes, errors = summarize(results)
    if successes != 2:
        raise AssertionError('并发确认失败：%s' % errors)
    ids = {entry[1]['data']['record']['bag_id'] for entry in results.values()}
    resolved = session_a.envelope(API + '/inventory/resolve_code', {'raw': record['payload']})
    if len(ids) != 1 or resolved['data']['bag']['quantity'] != 12:
        raise AssertionError('同袋重复入库或数量不一致')
    _logger.info('同袋并发确认通过：一个正式袋，数量 12，二维码保持不变')

    print('\n===== 并发验收结果 =====')
    if failures_total == 0:
        print('全部 6 个并发场景通过：真实相交执行、非 super 操作员、无死锁。')
        return 0
    print('有 %d 项不通过，请查看上面的 ERROR 日志与服务端 code。' % failures_total)
    return 1


if __name__ == '__main__':
    sys.exit(main())
