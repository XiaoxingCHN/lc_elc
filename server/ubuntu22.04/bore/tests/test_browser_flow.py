#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""browser_flow.py 的纯逻辑测试（不启动 Chrome / 不连网络）。

只测"错了会静默误判"的关键判定：redirect 归属、未知错误不算匿名、脱敏、
profile 边界与所有权、网络失败/状态归类、CSP 解析、DER SPKI 提取。
不复制脚本里的实现细节（例如断言某个内部字段名），只断言对外行为。
"""
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from importlib import util as importlib_util

MODULE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'browser_flow.py')


def load_module():
    spec = importlib_util.spec_from_file_location('lc_browser_flow', MODULE_PATH)
    module = importlib_util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bf = load_module()


def request_event(request_id, url, method='GET', post_data=None, redirect=None,
                  resource_type='XHR', loader_id='L1'):
    request = {'url': url, 'method': method}
    if post_data is not None:
        request['postData'] = post_data
    params = {
        'requestId': request_id,
        'request': request,
        'type': resource_type,
        'loaderId': loader_id,
        'frameId': 'F1',
    }
    if redirect:
        params['redirectResponse'] = redirect
    return params


def response_event(request_id, url, status, resource_type='XHR', headers=None):
    return {
        'requestId': request_id,
        'type': resource_type,
        'response': {
            'url': url,
            'status': status,
            'mimeType': 'text/html',
            'headers': headers or {},
        },
    }


def failure_event(request_id, error_text, blocked_reason=None):
    params = {'requestId': request_id, 'errorText': error_text}
    if blocked_reason:
        params['blockedReason'] = blocked_reason
    return params


class RedirectAttributionTest(unittest.TestCase):
    """303 必须归属到同一个 requestId 自己的 redirectResponse。"""

    def test_logout_303_captured_from_redirect_response(self):
        rec = bf.NetworkRecorder()
        rec.record_request(request_event(
            'R1', 'https://team.example/logout', method='POST',
            post_data='csrf_token=secret-token', resource_type='Document'))
        rec.record_request(request_event(
            'R1', 'https://team.example/login', method='GET',
            redirect={'url': 'https://team.example/logout', 'status': 303},
            resource_type='Document'))
        redirects = rec.logout_redirects()
        self.assertEqual(len(redirects), 1)
        item = redirects[0]
        self.assertEqual(item['status'], 303)
        self.assertEqual(item['from_method'], 'POST')
        self.assertEqual(item['from_path'], '/logout')
        self.assertEqual(item['to_path'], '/login')
        self.assertEqual(item['request_id'], 'R1')
        self.assertEqual(item['from_hop_index'], 0)
        self.assertEqual(item['to_hop_index'], 1)

    def test_extra_info_never_used_as_303_evidence(self):
        """ExtraInfo 只有 statusCode，没有 redirect 语义；它不能产生 303 记录。"""
        rec = bf.NetworkRecorder()
        rec.record_request(request_event('R2', 'https://team.example/logout',
                                         method='POST', resource_type='Document'))
        rec.record_extra_info({'requestId': 'R2', 'statusCode': 303})
        self.assertEqual(rec.logout_redirects(), [])
        self.assertTrue(rec.extra_info)
        self.assertEqual(rec.extra_info[0]['attribution'], 'requestId+hop-index')

    def test_extra_info_attribution_survives_redirect(self):
        """同一 requestId 的第二跳 ExtraInfo 不能记到第一跳（跨 redirect 不错记）。"""
        rec = bf.NetworkRecorder()
        rec.record_request(request_event('R3', 'https://team.example/logout',
                                         method='POST', resource_type='Document'))
        rec.record_request(request_event(
            'R3', 'https://team.example/login', method='GET',
            redirect={'url': 'https://team.example/logout', 'status': 303},
            resource_type='Document'))
        rec.record_extra_info({'requestId': 'R3', 'statusCode': 303})
        rec.record_extra_info({'requestId': 'R3', 'statusCode': 200})
        attributed = [item['attributed_path'] for item in rec.extra_info]
        self.assertEqual(attributed, ['/logout', '/login'])
        self.assertEqual([item['hop_index'] for item in rec.extra_info], [0, 1])

    def test_other_requestid_redirect_is_not_logout(self):
        rec = bf.NetworkRecorder()
        rec.record_request(request_event('R4', 'https://team.example/lab',
                                         method='GET', resource_type='Document'))
        rec.record_request(request_event(
            'R4', 'https://team.example/login', method='GET',
            redirect={'url': 'https://team.example/lab', 'status': 303},
            resource_type='Document'))
        self.assertEqual(rec.logout_redirects(), [])
        self.assertEqual(len(rec.redirects), 1)


class SearchBodyDecodingTest(unittest.TestCase):
    def test_query_decoded_from_real_jsonrpc_body(self):
        body = json.dumps({'jsonrpc': '2.0', 'method': 'call',
                           'params': {'query': 'TEST-R-10K', 'category_id': None,
                                      'stock_only': False, 'cursor': None, 'limit': 24}})
        decoded = bf.decode_search_body(body)
        self.assertEqual(decoded['query'], 'TEST-R-10K')
        self.assertEqual(decoded['jsonrpc'], '2.0')
        self.assertEqual(decoded['limit'], 24)
        self.assertFalse(decoded['cursor_present'])

    def test_non_jsonrpc_or_missing_query_is_rejected(self):
        for body in ('', 'not json', '{}', '{"params":{}}',
                     '{"params":{"query":123}}', '[]', None):
            self.assertIsNone(bf.decode_search_body(body), body)

    def test_recorder_only_decodes_search_endpoint(self):
        rec = bf.NetworkRecorder()
        body = json.dumps({'jsonrpc': '2.0', 'method': 'call',
                           'params': {'query': 'TEST-R-10K'}})
        rec.record_request(request_event(
            'S1', 'https://team.example/web/session/authenticate', method='POST',
            post_data=body))
        rec.record_request(request_event(
            'S2', 'https://team.example/lab/api/catalog/search', method='POST',
            post_data=body))
        self.assertEqual(rec.search_queries(), ['TEST-R-10K'])
        # 非检索端点不保留 body
        auth_entries = [e for e in rec.evidence if e['path'].endswith('/authenticate')]
        self.assertEqual(len(auth_entries), 1)
        self.assertNotIn('rpc_query', auth_entries[0])
        self.assertEqual(auth_entries[0]['body'], 'withheld')


class SessionClassificationTest(unittest.TestCase):
    """只有显式匿名或精确 SessionExpired 才算匿名。"""

    def test_explicit_false_and_null_uid_are_anonymous(self):
        for uid in (False, None):
            payload = json.dumps({'jsonrpc': '2.0', 'id': 1, 'result': {'uid': uid}})
            kind, _reason = bf.classify_session_payload(payload, None, 'application/json')
            self.assertEqual(kind, 'anon', payload)

    def test_real_uid_is_not_anonymous(self):
        payload = json.dumps({'result': {'uid': 7, 'name': 'x'}})
        kind, _reason = bf.classify_session_payload(payload, None, 'application/json')
        self.assertEqual(kind, 'uid')

    def test_any_real_uid_is_never_treated_as_anonymous(self):
        # 不允许用"匿名基线"之类的旁路把某个真实身份当成已登出
        for uid in (1, 4, 7, 99, '5'):
            payload = json.dumps({'result': {'uid': uid}})
            kind, _reason = bf.classify_session_payload(
                payload, None, 'application/json')
            self.assertEqual(kind, 'uid', payload)

    def test_exact_session_expired_is_anonymous(self):
        payload = json.dumps({'error': {'data': {
            'name': 'odoo.http.SessionExpiredException'}}})
        kind, _reason = bf.classify_session_payload(payload, None, 'application/json')
        self.assertEqual(kind, 'expired')

    def test_unknown_error_is_never_anonymous(self):
        cases = [
            {'error': {'data': {'name': 'odoo.exceptions.AccessDenied'}}},
            {'error': {'message': 'Odoo Server Error'}},
            {'error': {'data': {}}},
            {'error': {}},
            {'result': {}},
            {'result': []},
            {'result': None},
            {'jsonrpc': '2.0', 'id': 1},
            {},
        ]
        for payload in cases:
            kind, _reason = bf.classify_session_payload(
                json.dumps(payload), None, 'application/json')
            self.assertEqual(kind, 'unknown', payload)

    def test_html_and_network_errors_are_never_anonymous(self):
        kind, _ = bf.classify_session_payload('<html>login</html>', None,
                                             'text/html')
        self.assertEqual(kind, 'html')
        kind, _ = bf.classify_session_payload('{"result":{"uid":false}}', None,
                                             'text/html')
        self.assertEqual(kind, 'html')
        kind, _ = bf.classify_session_payload(None, 'ConnectionResetError')
        self.assertEqual(kind, 'neterr')
        kind, _ = bf.classify_session_payload(None, None)
        self.assertEqual(kind, 'neterr')

    def test_extract_session_uid(self):
        self.assertEqual(bf.extract_session_uid('{"result":{"uid":0}}'),
                         ('present', 0))
        self.assertEqual(bf.extract_session_uid('{"result":{}}'), ('missing', None))
        self.assertEqual(bf.extract_session_uid('garbage')[0], 'unparsable')


class NetworkFailureClassificationTest(unittest.TestCase):
    def test_generic_abort_is_a_failure(self):
        kind, _ = bf.classify_network_failure('/lab/api/catalog/search',
                                              'net::ERR_ABORTED', 'XHR', 'R9')
        self.assertEqual(kind, 'fail')

    def test_favicon_abort_is_narrowly_exempt(self):
        kind, reason = bf.classify_network_failure('/favicon.ico',
                                                   'net::ERR_ABORTED', 'Other', 'R1')
        self.assertEqual(kind, 'ignored')
        self.assertIn('favicon', reason)
        # 同一个 URL 但别的错误原因不算豁免
        kind2, _ = bf.classify_network_failure('/favicon.ico',
                                               'net::ERR_CONNECTION_REFUSED', 'Other', 'R1')
        self.assertEqual(kind2, 'fail')
        # 同样 ERR_ABORTED 但不是 favicon 也不算
        kind3, _ = bf.classify_network_failure('/lab/api/asset',
                                               'net::ERR_ABORTED', 'Image', 'R1')
        self.assertEqual(kind3, 'fail')

    def test_registered_abort_requires_exact_request_id(self):
        allowed = {'R5': 'intentional reload'}
        kind, _ = bf.classify_network_failure('/lab', 'net::ERR_ABORTED', 'Document',
                                              'R5', '', allowed)
        self.assertEqual(kind, 'allowed-abort')
        kind2, _ = bf.classify_network_failure('/lab', 'net::ERR_ABORTED', 'Document',
                                               'R6', '', allowed)
        self.assertEqual(kind2, 'fail')

    def test_blocked_reason_always_fails(self):
        kind, _ = bf.classify_network_failure('/lab_team_web/static/src/js/team.js',
                                              'net::ERR_BLOCKED_BY_CSP',
                                              'Script', 'R7', 'csp')
        self.assertEqual(kind, 'fail')

    def test_status_classification(self):
        self.assertEqual(bf.classify_status('/lab', 200, 'Document')[0], 'ok')
        self.assertEqual(bf.classify_status('/lab', 303, 'Document')[0], 'ok')
        self.assertEqual(bf.classify_status('/lab/api/catalog/search', 500, 'XHR')[0], 'fail')
        self.assertEqual(bf.classify_status('/favicon.ico', 404, 'Other')[0], 'ignored')
        self.assertEqual(bf.classify_status('/favicon.ico', 404, 'Document')[0], 'fail')

    def test_recorder_marks_csp_script_failure_as_fail(self):
        rec = bf.NetworkRecorder()
        rec.record_request(request_event(
            'C1', 'https://team.example/lab_team_web/static/src/js/team.js',
            resource_type='Script'))
        rec.record_failure(failure_event('C1', 'net::ERR_BLOCKED_BY_CSP', 'csp'))
        failures = rec.failure_failures()
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]['path'], '/lab_team_web/static/src/js/team.js')
        self.assertEqual(rec.ignored, [])

    def test_recorder_counts_status_failures(self):
        rec = bf.NetworkRecorder()
        rec.record_request(request_event('D1', 'https://team.example/lab',
                                         resource_type='Document'))
        rec.record_response(response_event('D1', 'https://team.example/lab', 500,
                                           'Document'))
        rec.record_request(request_event('D2', 'https://team.example/favicon.ico',
                                         resource_type='Other'))
        rec.record_response(response_event('D2', 'https://team.example/favicon.ico',
                                           404, 'Other'))
        failures = rec.status_failures()
        self.assertEqual([item['path'] for item in failures], ['/lab'])


class AbortWhitelistScopeTest(unittest.TestCase):
    """预期中止必须只覆盖"仍在飞"的请求，不能把历史 id 一并放行。"""

    def test_settled_request_is_not_registered(self):
        rec = bf.NetworkRecorder()
        rec.record_request(request_event('A1', 'https://team.example/lab/api/catalog/search',
                                         method='POST', resource_type='XHR'))
        rec.record_response(response_event('A1', 'https://team.example/lab/api/catalog/search',
                                           200))
        rec.record_request(request_event('A2', 'https://team.example/lab/api/catalog/search',
                                         method='POST', resource_type='XHR'))
        rec.allow_aborts('explicit submit', path=bf.SEARCH_PATH)
        self.assertNotIn('A1', rec.allowed_aborts)
        self.assertIn('A2', rec.allowed_aborts)

    def test_path_filter_keeps_unrelated_inflight_requests_strict(self):
        rec = bf.NetworkRecorder()
        rec.record_request(request_event('B1', 'https://team.example/lab_team_web/static/x.js',
                                         resource_type='Script'))
        rec.record_request(request_event('B2', 'https://team.example/lab/api/catalog/search',
                                         method='POST', resource_type='XHR'))
        rec.allow_aborts('explicit submit', path=bf.SEARCH_PATH)
        self.assertNotIn('B1', rec.allowed_aborts)
        self.assertIn('B2', rec.allowed_aborts)
        # 静态脚本被中止必须是失败，即使刚刚登记了检索请求的预期中止
        rec.record_failure(failure_event('B1', 'net::ERR_ABORTED'))
        rec.record_failure(failure_event('B2', 'net::ERR_ABORTED'))
        failures = [item['request_id'] for item in rec.failure_failures()]
        self.assertEqual(failures, ['B1'])
        allowed = [item['request_id'] for item in rec.ignored]
        self.assertEqual(allowed, ['B2'])

    def test_redirected_hop_is_settled(self):
        # 303 的前一跳已经结束，只有重定向目标那一跳仍在飞
        rec = bf.NetworkRecorder()
        rec.record_request(request_event('C1', 'https://team.example/logout',
                                         method='POST', resource_type='Document'))
        rec.record_request(request_event(
            'C1', 'https://team.example/login', method='GET',
            redirect={'url': 'https://team.example/logout', 'status': 303},
            resource_type='Document'))
        hops = [hop for hop in rec.requests if hop['request_id'] == 'C1']
        self.assertEqual(len(hops), 2)
        self.assertTrue(hops[0]['settled'])
        self.assertFalse(hops[1]['settled'])
        rec.allow_aborts('after logout')
        self.assertIn('C1', rec.allowed_aborts)
        self.assertIn('/login', rec.allowed_aborts['C1'])


class SearchCapturePathTest(unittest.TestCase):
    """两条 body 来源都要能解出 query；未解码的才需要补取。"""

    def test_inline_post_data_is_decoded_immediately(self):
        rec = bf.NetworkRecorder()
        body = json.dumps({'jsonrpc': '2.0', 'method': 'call',
                           'params': {'query': 'TEST-R-10K', 'limit': 24}})
        rec.record_request(request_event(
            'P1', 'https://team.example/lab/api/catalog/search', method='POST',
            post_data=body))
        self.assertEqual(rec.search_queries(), ['TEST-R-10K'])
        self.assertEqual(rec.pending_search_bodies(), [])

    def test_body_reported_but_not_inline_requires_fetch(self):
        # CDP 可能只给 hasPostData=true 而不给 postData（body 太大），此时要补取
        rec = bf.NetworkRecorder()
        params = request_event('P2', 'https://team.example/lab/api/catalog/search',
                               method='POST')
        params['hasPostData'] = True
        rec.record_request(params)
        self.assertEqual([hop['request_id'] for hop in rec.pending_search_bodies()],
                         ['P2'])
        self.assertEqual(rec.search_queries(), [])
        body = json.dumps({'jsonrpc': '2.0', 'method': 'call',
                           'params': {'query': 'TEST-R-10K'}})
        rec.attach_post_data('P2', body)
        self.assertEqual(rec.search_queries(), ['TEST-R-10K'])
        self.assertEqual(rec.pending_search_bodies(), [])

    def test_search_request_without_any_body_is_an_error(self):
        rec = bf.NetworkRecorder()
        rec.record_request(request_event(
            'P5', 'https://team.example/lab/api/catalog/search', method='GET'))
        hop = rec.search_hops()[0]
        self.assertIn('error', hop['rpc'])
        self.assertEqual(rec.search_queries(), [])
        self.assertEqual(rec.pending_search_bodies(), [])

    def test_undecodable_body_is_recorded_as_error_not_query(self):
        rec = bf.NetworkRecorder()
        rec.record_request(request_event(
            'P3', 'https://team.example/lab/api/catalog/search', method='POST',
            post_data='garbage'))
        self.assertEqual(rec.search_queries(), [])
        hop = rec.search_hops()[0]
        self.assertIn('error', hop['rpc'])

    def test_decoded_query_backfilled_into_evidence(self):
        # 证据条目在请求到达时就写下了；补取 body 后必须把真实 query 回填进去，
        # 否则"证据里的 search query"与"实际发出的 query"会不一致。
        rec = bf.NetworkRecorder()
        params = request_event('P4', 'https://team.example/lab/api/catalog/search',
                               method='POST')
        params['hasPostData'] = True
        rec.record_request(params)
        entries = [e for e in rec.evidence if e['request_id'] == 'P4']
        self.assertNotIn('rpc_query', entries[0])
        rec.attach_post_data('P4', json.dumps(
            {'jsonrpc': '2.0', 'method': 'call',
             'params': {'query': 'TEST-R-10K'}}))
        self.assertEqual(entries[0]['rpc_query'], 'TEST-R-10K')


class NavigationRedirectTest(unittest.TestCase):
    """导航链上的 loaderId 不能拿来当"必须是同一个 document"的判据。"""

    def _run(self, action_result, nav_events, dom_value=True, expected_loader=None,
             not_loader=None, url_filter=None):
        class FakeSink(object):
            def __init__(self):
                self.entries = []

            def add(self, *args):
                self.entries.append(args)

        sink = FakeSink()
        cdp = bf.CDP(None, bf.NetworkRecorder(), sink)
        cdp.event_seq = 1

        def action():
            # 导航事件必须在 action() 之后到达，才符合真实时序
            for event in nav_events:
                cdp.event_seq += 1
                item = dict(event)
                item['seq'] = cdp.event_seq
                cdp.nav_log.append(item)
                cdp.contexts.append({'seq': cdp.event_seq, 'id': 100 + cdp.event_seq,
                                     'frame_id': 'F1', 'is_default': True,
                                     'origin': ''})
            return dict(action_result)

        cdp.evaluate = lambda expression, context_id=None, await_promise=False: (
            {'ready': True} if dom_value else None)
        return cdp.expect_navigation(
            action,
            url_filter or (lambda url: url.endswith('/login')),
            'true', label='t', expected_loader=expected_loader,
            not_loader=not_loader, timeout=0.2)

    def test_redirect_chain_does_not_fail_on_loader_change(self):
        result = self._run(
            {'loaderId': 'LOADER-A'},
            [{'frame_id': 'F1', 'loader_id': 'LOADER-B', 'url': 'https://t/login'}])
        self.assertEqual(result['loader_id'], 'LOADER-B')
        self.assertEqual(result['request_loader_id'], 'LOADER-A')
        self.assertTrue(result['redirected'])

    def test_missing_loader_id_is_a_failure(self):
        class FakeSink(object):
            def __init__(self):
                self.entries = []

            def add(self, *args):
                self.entries.append(args)

        cdp = bf.CDP(None, bf.NetworkRecorder(), FakeSink())
        cdp.event_seq = 1
        cdp.event_seq += 1
        cdp.nav_log.append({'seq': cdp.event_seq, 'frame_id': 'F1',
                            'loader_id': '', 'url': 'https://t/login'})
        cdp.contexts.append({'seq': cdp.event_seq, 'id': 7, 'frame_id': 'F1',
                             'is_default': True, 'origin': ''})
        cdp.evaluate = lambda *a, **k: {'ready': True}
        with self.assertRaises(bf.FlowAbort):
            cdp.expect_navigation(lambda: {}, lambda url: True, 'true', label='t',
                                  timeout=0.2)

    def test_explicit_expected_loader_still_strict(self):
        with self.assertRaises(bf.FlowAbort):
            self._run({'loaderId': 'LOADER-A'},
                      [{'frame_id': 'F1', 'loader_id': 'LOADER-B',
                        'url': 'https://t/login'}],
                      expected_loader='LOADER-A')

    def test_not_loader_rejects_unreplaced_document(self):
        with self.assertRaises(bf.FlowAbort):
            self._run({'loaderId': 'LOADER-A'},
                      [{'frame_id': 'F1', 'loader_id': 'LOADER-A',
                        'url': 'https://t/login'}],
                      not_loader='LOADER-A')

    def test_no_navigation_is_a_failure(self):
        with self.assertRaises(bf.FlowAbort):
            self._run({'loaderId': 'LOADER-A'}, [])


class DetailKeyContractTest(unittest.TestCase):
    """详情链接必须动态取自命中项，且只接受应用路由真正受理的 itemKey。"""

    def test_lab_ids_are_routable(self):
        for key in ('lab:1', 'lab:4', 'lab:42', 'lab:0'):
            self.assertTrue(bf.is_routable_detail_key(key), key)

    def test_lcsc_keys_need_c_plus_digits(self):
        self.assertTrue(bf.is_routable_detail_key('lcsc:C1525'))
        self.assertTrue(bf.is_routable_detail_key('lcsc:C1'))
        # 合成数据里的 TEST-R-10K 不是合法 C 编号，应用详情路由会 400
        self.assertFalse(bf.is_routable_detail_key('lcsc:TEST-R-10K'))
        self.assertFalse(bf.is_routable_detail_key('lcsc:C0'))
        self.assertFalse(bf.is_routable_detail_key('lcsc:c1525'))

    def test_garbage_keys_rejected(self):
        for key in ('', 'lab:', 'lab:abc', 'C1525', 'lab:4/../x', 'lab:-1', None):
            self.assertFalse(bf.is_routable_detail_key(key), repr(key))

    def test_detail_path_encoding(self):
        self.assertEqual(bf.detail_path_for('lab:4'), '/lab/items/lab:4')
        self.assertEqual(bf.detail_path_for('lcsc:C1525'), '/lab/items/lcsc:C1525')
        # 与后端 quote_item_key 一致：非安全字符百分号编码
        self.assertEqual(bf.detail_path_for('lab:测试'), '/lab/items/lab:%E6%B5%8B%E8%AF%95')

    def test_detail_path_roundtrips_through_routable_check(self):
        for key in ('lab:4', 'lab:42', 'lcsc:C1525'):
            self.assertTrue(bf.detail_path_for(key).startswith(bf.DETAIL_PREFIX))
            self.assertTrue(bf.is_routable_detail_key(key))


class EmbeddedJavaScriptSyntaxTest(unittest.TestCase):
    """脚本下发的每段 JS 都必须真的能解析（否则浏览器只会静默返回 null）。

    这是"实现类"测试里唯一必须做的：拼字符串生成 JS 极易出现语法错误，
    而错误表达式在 CDP 里的表现只是返回 null/异常，会被误读成"页面没渲染"。
    """

    NODE = shutil.which('node')

    def setUp(self):
        if not self.NODE:
            self.skipTest('系统无 node，无法做 JS 语法检查')

    @staticmethod
    def collect_expressions():
        import re as _re
        with open(MODULE_PATH, encoding='utf-8') as handle:
            source = handle.read()
        found = []
        for match in _re.finditer(r'"""\s*\(?\s*(?:async\s*)?\(\)\s*=>', source):
            start = match.start() + 3
            end = source.find('"""', start)
            if end > start:
                found.append(source[start:end])
        for match in _re.finditer(r'(?m)^\s*expression = """', source):
            start = match.start() + len(match.group(0))
            end = source.find('"""', start)
            if end > start:
                found.append(source[start:end])
        ns = {'json': json}

        def js_str(value):
            return json.dumps(value, ensure_ascii=False)

        ns['js_str'] = js_str
        block = _re.search(r'wait_expr = (\(.*?js_str\(self\.cfg\.query\)\))',
                           source, _re.S)
        if block:
            class _C(object):
                query = 'TEST-R-10K'

            class _S(object):
                cfg = _C()

            ns['self'] = _S()
            found.append(eval(block.group(1), ns))
        return found

    def test_all_embedded_expressions_parse(self):
        work = tempfile.mkdtemp(prefix='lc-p2-js-')
        try:
            expressions = self.collect_expressions()
            self.assertGreaterEqual(len(expressions), 5)
            for index, expression in enumerate(expressions):
                concrete = expression
                if '%s' in concrete or '%d' in concrete:
                    concrete = concrete.replace(
                        '%s', json.dumps('#lc-grid a.lc-item-link')).replace('%d', '0')
                path = os.path.join(work, 'e%d.js' % index)
                with open(path, 'w', encoding='utf-8') as handle:
                    handle.write('void (' + concrete + ');\n')
                result = subprocess.run([self.NODE, '--check', path],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0,
                                 'expression %d 语法错误: %s\n%s'
                                 % (index, result.stderr[:400], concrete[:300]))
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_js_strings_neutralise_injection(self):
        """用户输入进入 JS 时必须经过 json.dumps，不能直接拼字符串。"""
        self.assertEqual(bf.js_str("a'b"), json.dumps("a'b"))
        self.assertIn('\\"', bf.js_str('a"b'))
        payload = bf.js_str("'); alert(1); //")
        self.assertTrue(payload.startswith('"') and payload.endswith('"'))


class RunnerEnvCompatibilityTest(unittest.TestCase):
    """现有 runner 传的变量名必须被接受，否则脚本一启动就 KeyError。"""

    ENV_KEYS = ('CHROME_BIN', 'URL', 'LOGIN', 'PASSWORD', 'OUT_DIR',
                'SPKI', 'P2_CA_FILE', 'CA_FILE', 'P2_QUERY', 'P2_SEARCH_QUERY',
                'P2_DETAIL_KEY', 'P2_SEARCH_QUERY')

    def setUp(self):
        self._saved = {key: os.environ.get(key) for key in self.ENV_KEYS}
        for key in self.ENV_KEYS:
            os.environ.pop(key, None)
        self.base = {
            'CHROME_BIN': '/bin/true',
            'URL': 'https://team.example:9500',
            'LOGIN': 'tester',
            'PASSWORD': 'secret-value',
            'OUT_DIR': os.path.join(tempfile.gettempdir(), 'lc-p2-env'),
        }
        os.environ.update(self.base)

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_runner_variable_names_are_accepted(self):
        # verify-real-odoo.sh 传的是 CA_FILE 与 P2_QUERY
        os.environ['CA_FILE'] = '/tmp/ca.pem'
        os.environ['P2_QUERY'] = 'TEST-R-10K'
        os.environ['P2_DETAIL_KEY'] = 'lab:4'
        cfg = bf.Config()
        self.assertEqual(cfg.ca_file, '/tmp/ca.pem')
        self.assertEqual(cfg.query, 'TEST-R-10K')
        self.assertEqual(cfg.origin, 'https://team.example:9500')

    def test_p2_query_preferred_over_legacy_name(self):
        os.environ['P2_QUERY'] = 'LEGACY'
        os.environ['P2_SEARCH_QUERY'] = 'PREFERRED'
        self.assertEqual(bf.Config().query, 'PREFERRED')

    def test_detail_key_from_env_is_ignored(self):
        """详情 key 必须来自检索命中；环境变量里的 key 不能影响流程。"""
        os.environ['P2_DETAIL_KEY'] = 'lab:4'
        cfg = bf.Config()
        self.assertFalse(hasattr(cfg, 'detail_key'))
        self.assertNotIn('lab:4', repr(cfg.__dict__))

    def test_missing_required_variable_raises(self):
        os.environ.pop('PASSWORD', None)
        with self.assertRaises(KeyError):
            bf.Config()

    def test_secrets_include_only_password(self):
        cfg = bf.Config()
        labels = [label for label, _value in cfg.secrets()]
        self.assertEqual(labels, ['password'])


class RedactionTest(unittest.TestCase):
    def test_password_value_is_removed(self):
        text = bf.redact('authenticate failed for P2Synth-Only-2026',
                         [('password', 'P2Synth-Only-2026')])
        self.assertNotIn('P2Synth-Only-2026', text)
        self.assertIn('<redacted>', text)

    def test_session_and_csrf_patterns_removed(self):
        text = bf.redact('Cookie: session_id=abc123; csrf_token=zzz999')
        self.assertNotIn('abc123', text)
        self.assertNotIn('zzz999', text)

    def test_json_password_field_removed(self):
        text = bf.redact('{"login": "x", "password": "hunter2"}')
        self.assertNotIn('hunter2', text)

    def test_leak_detector_flags_real_secret(self):
        payload = json.dumps({'note': 'P2Synth-Only-2026'})
        hits = bf.find_secret_leaks(payload, [('password', 'P2Synth-Only-2026')])
        self.assertIn('password', hits)

    def test_leak_detector_does_not_flag_own_placeholder(self):
        """脱敏后的占位符本身不能触发"再次泄露"的误报。"""
        payload = json.dumps({'note': 'session_id=<redacted>',
                              'password': '<redacted>'})
        self.assertEqual(bf.find_secret_leaks(payload, [('password', 'x')]), [])

    def test_short_secrets_are_not_pattern_matched(self):
        # 太短的值不参与子串扫描，避免把普通文本判成泄露
        self.assertEqual(bf.find_secret_leaks('{"a": "abc"}', [('password', 'abc')]), [])


    def test_evidence_records_same_origin_flag_not_raw_origin(self):
        rec = bf.NetworkRecorder(entry_origin='https://team.example:9500')
        rec.record_request(request_event(
            'E1', 'https://team.example:9500/lab', resource_type='Document'))
        rec.record_request(request_event(
            'E2', 'https://evil.example/lab', resource_type='Document'))
        flags = {item['request_id']: item.get('same_origin_as_entry')
                 for item in rec.evidence}
        self.assertIs(flags['E1'], True)
        self.assertIs(flags['E2'], False)
        for item in rec.evidence:
            self.assertNotIn('origin', item)
            self.assertNotIn('evil.example', json.dumps(item))

    def test_cookie_value_leak_detected(self):
        payload = json.dumps({'raw': 'cookie=deadbeefcafe'})
        hits = bf.find_secret_leaks(payload, [('cookie:session_id', 'deadbeefcafe')])
        self.assertTrue(hits)

    def test_digest_label_is_stable_and_non_reversible(self):
        first = bf.digest_label('p2_manager', 'token')
        second = bf.digest_label('p2_manager', 'token')
        self.assertEqual(first, second)
        self.assertNotEqual(first, bf.digest_label('p2_manager', 'other'))
        self.assertEqual(len(first), 12)
        self.assertNotIn('p2_manager', first)
        self.assertEqual(bf.digest_label('', 'token'), '')


class CspParsingTest(unittest.TestCase):
    def test_directives_split_correctly(self):
        value = ("default-src 'self'; script-src 'self'; connect-src 'self';"
                 " form-action 'self'; frame-ancestors 'none'")
        parsed = bf.parse_csp_header(value)
        self.assertEqual(parsed['default-src'], ["'self'"])
        self.assertEqual(parsed['frame-ancestors'], ["'none'"])
        self.assertIn('form-action', parsed)

    def test_garbage_tokens_ignored(self):
        parsed = bf.parse_csp_header("  ; ; 'self'; img-src data:")
        self.assertEqual(parsed.get('img-src'), ['data:'])

    def test_empty_header(self):
        self.assertEqual(bf.parse_csp_header(''), {})
        self.assertEqual(bf.parse_csp_header(None), {})


class ProfileBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix='lc-p2-test-'))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_safe_child_dir_stays_inside(self):
        created, real = bf.safe_child_dir(self.root, 'profile-')
        self.assertTrue(bf.is_within(os.path.realpath(self.root), real))
        self.assertTrue(os.path.isdir(real))
        self.assertFalse(bf.is_linklike(real))

    def test_parent_with_link_component_rejected(self):
        link = os.path.join(self.root, 'link')
        target = os.path.join(self.root, 'target')
        os.makedirs(target)
        try:
            os.symlink(target, link, target_is_directory=True)
        except (OSError, NotImplementedError, AttributeError):
            self.skipTest('symlink 不可用')
        with self.assertRaises(ValueError):
            bf.safe_child_dir(link, 'profile-')

    def test_escape_via_maker_is_rejected(self):
        outside = os.path.realpath(tempfile.mkdtemp(prefix='lc-p2-outside-'))
        try:
            def maker():
                return outside
            with self.assertRaises(ValueError):
                bf.safe_child_dir(self.root, 'profile-', maker=maker)
        finally:
            shutil.rmtree(outside, ignore_errors=True)

    def test_missing_parent_rejected(self):
        with self.assertRaises(ValueError):
            bf.safe_child_dir(os.path.join(self.root, 'nope'), 'profile-')

    def test_link_component_detects_reparse_probe(self):
        path = os.path.join(self.root, 'a', 'b')
        # 模拟探测函数：'a' 是链接
        probe = lambda item: item.endswith(os.sep + 'a')
        self.assertTrue(bf.contains_link_component(path, is_link=probe))
        self.assertFalse(bf.contains_link_component(self.root, is_link=lambda _p: False))

    def test_within_requires_strict_child(self):
        self.assertTrue(bf.is_within(self.root, os.path.join(self.root, 'x')))
        self.assertFalse(bf.is_within(self.root, self.root))
        self.assertFalse(bf.is_within(self.root, self.root + '-sibling'))
        self.assertFalse(bf.is_within('', self.root))

    def test_owner_marker_roundtrip(self):
        created, real = bf.safe_child_dir(self.root, 'profile-')
        bf.write_owner_marker(real, 'token-aaa')
        ok, why = bf.verify_owner_marker(real, 'token-aaa')
        self.assertTrue(ok, why)
        ok2, why2 = bf.verify_owner_marker(real, 'token-bbb')
        self.assertFalse(ok2)
        self.assertIn('不匹配', why2)

    def test_missing_marker_fails_verification(self):
        created, real = bf.safe_child_dir(self.root, 'profile-')
        ok, why = bf.verify_owner_marker(real, 'token-aaa')
        self.assertFalse(ok)
        self.assertIn('不可读', why)

    def test_marker_pointing_outside_fails(self):
        created, real = bf.safe_child_dir(self.root, 'profile-')
        other = os.path.join(self.root, 'other-marker')
        with open(other, 'w', encoding='utf-8') as handle:
            handle.write('token-aaa')
        try:
            os.symlink(other, os.path.join(real, '.lc_p2_owner'))
        except (OSError, NotImplementedError, AttributeError):
            self.skipTest('symlink 不可用')
        ok, why = bf.verify_owner_marker(real, 'token-aaa')
        self.assertFalse(ok)
        self.assertTrue('链接' in why or '越界' in why, why)


class SpkiExtractionTest(unittest.TestCase):
    """用 openssl 现场生成的证书验证 DER 解析（无 openssl 则跳过）。"""

    def test_spki_matches_openssl(self):
        openssl = shutil.which('openssl')
        if not openssl:
            self.skipTest('系统无 openssl')
        work = tempfile.mkdtemp(prefix='lc-p2-spki-')
        try:
            key = os.path.join(work, 'k.pem')
            crt = os.path.join(work, 'c.pem')
            gen = subprocess.run(
                [openssl, 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                 '-keyout', key, '-out', crt, '-days', '1', '-subj', '/CN=test'],
                capture_output=True)
            if gen.returncode != 0:
                self.skipTest('openssl 生成证书失败')
            der = subprocess.run(
                [openssl, 'x509', '-in', crt, '-outform', 'der'],
                capture_output=True, check=True).stdout
            expected = subprocess.run(
                [openssl, 'x509', '-in', crt, '-pubkey', '-noout'],
                capture_output=True, check=True).stdout
            expected_der = subprocess.run(
                [openssl, 'pkey', '-pubin', '-outform', 'der'],
                input=expected, capture_output=True, check=True).stdout
            expected_b64 = base64.b64encode(
                __import__('hashlib').sha256(expected_der).digest()).decode('ascii')
            self.assertEqual(bf.spki_sha256_b64(der), expected_b64)
            self.assertEqual(bf.extract_spki_der(der), expected_der)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_bad_der_rejected(self):
        for value in (b'', b'\x00\x01', b'\x30\x03\x00\x00\x00', None):
            with self.assertRaises(ValueError):
                bf.extract_spki_der(value)


class PlannedStepsTest(unittest.TestCase):
    def test_planned_steps_are_unique_and_positive(self):
        self.assertEqual(len(bf.PLANNED_STEPS), len(set(bf.PLANNED_STEPS)))
        self.assertGreater(len(bf.PLANNED_STEPS), 20)
        for required in ('search-ui-input', 'search-rpc-query', 'search-dom-match',
                         'detail-ui-click', 'refresh-ui', 'logout-ui-submit',
                         'logout-redirect-303', 'anon-old-cookie-invalid',
                         'console-clean', 'network-clean', 'profile-cleanup'):
            self.assertIn(required, bf.PLANNED_STEPS)

    def test_default_terms_use_synthetic_resistor_and_capacitor(self):
        self.assertIn('TEST-R-10K', bf.DEFAULT_EXPECT_TERMS)
        self.assertIn('\u7535\u963b', bf.DEFAULT_EXPECT_TERMS)
        self.assertIn('100nF', bf.DEFAULT_EXCLUDE_TERMS)
        self.assertIn('\u7535\u5bb9', bf.DEFAULT_EXCLUDE_TERMS)


class FallbackResultTest(unittest.TestCase):
    def test_fallback_is_nonzero_and_lists_all_blocked(self):
        payload = bf.fallback_result('boom')
        self.assertFalse(payload['ok'])
        self.assertNotEqual(payload['exit_code'], 0)
        self.assertEqual(payload['counts']['blocked'], len(bf.PLANNED_STEPS))
        self.assertEqual(len(payload['unreached_steps']), len(bf.PLANNED_STEPS))
        self.assertTrue(all(item['status'] == 'blocked' for item in payload['steps']))


if __name__ == '__main__':
    unittest.main(verbosity=2)
