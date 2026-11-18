# -*- coding: utf-8 -*-
"""Pure tests for the on-demand LCSC fetch helpers.

No Odoo database and no network: the HTTP layer is monkeypatched, and the
Chinese page fixture mirrors the real ``__NEXT_DATA__`` shape (中文参数名).
"""
import importlib.util
import json
import os
import socket
import time
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.abspath(os.path.join(_HERE, '..', 'tools', 'lcsc_remote.py'))
_spec = importlib.util.spec_from_file_location('lcsc_remote_test', _SRC)
remote = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(remote)


def _cn_html(code='C54110218', product_id='57330406', name='测试器件'):
    payload = {
        'props': {
            'pageProps': {
                'price': 12.34,
                'webData': {
                    'currentCatalog': {
                        'catalogId': 387, 'parentId': 380,
                        'catalogName': '线性稳压器(LDO)',
                    },
                    'paramList': [
                        {'parameterCode': 'param_1', 'parameterName': '输出极性',
                         'parameterValue': '正极', 'parameterDetailValue': '正极'},
                        {'parameterCode': 'param_2', 'parameterName': '输出电压',
                         'parameterValue': '3.3V', 'parameterDetailValue': '3.3V'},
                    ],
                    'productRecord': {
                        'productCode': code,
                        'productId': product_id,
                        'productModel': 'TLV77733PDBVR',
                        'productName': name,
                        'productGradePlateName': 'TI(德州仪器)',
                        'encapsulationModel': 'SOT-23-5',
                        'stockNumber': 1866,
                        'fileTypeVOList': [
                            {'fileType': 'pdf_property', 'detailVOList': [
                                {'fileName': 'ds.pdf',
                                 'fileUrl': 'https://atta.szlcsc.com/ds.pdf'}]},
                        ],
                        'breviaryImageUrl': '//alimg.szlcsc.com/a.jpg',
                    },
                },
            },
        },
    }
    return ('<html><script id="__NEXT_DATA__" type="application/json" '
            'crossorigin="anonymous">%s</script></html>'
            % json.dumps(payload, ensure_ascii=False))


class NormalizeQueryTest(unittest.TestCase):

    def test_c_code(self):
        self.assertEqual(remote.normalize_query(' c32445874 '),
                         ('c_code', 'C32445874'))

    def test_mpn_is_uppercased_and_spaces_removed(self):
        self.assertEqual(remote.normalize_query('tlv77733 pdbvr'),
                         ('mpn', 'TLV77733PDBVR'))

    def test_keywords_are_rejected(self):
        for value in ('电容', 'TLV', '12345', '', 'C0', 'a b'):
            self.assertEqual(remote.normalize_query(value), (None, None), value)


class KeywordCandidateTest(unittest.TestCase):
    """至少 5 个字符且含字母的搜索只换候选，不抓详情、不写库。"""

    def setUp(self):
        self._original = remote.search_products

    def tearDown(self):
        remote.search_products = self._original

    def test_keyword_needs_five_characters_and_a_letter(self):
        self.assertIsNone(remote.normalize_keyword('TLV9'))
        self.assertIsNone(remote.normalize_keyword('  12345 '))
        self.assertIsNone(remote.normalize_keyword('123456'))
        self.assertEqual(remote.normalize_keyword(' TLV90 '), 'TLV90')
        self.assertEqual(remote.normalize_keyword('  tlv900 '), 'tlv900')
        self.assertEqual(remote.normalize_keyword('10uF 16V'), '10uF 16V')
        self.assertEqual(remote.normalize_keyword(' 线性稳压器型号 '),
                         '线性稳压器型号')

    def test_candidates_show_the_name_and_drop_non_electronic_rows(self):
        rows = remote.candidates_from([
            {'productCode': 'C398363', 'productModel': 'TLV9001IDBVR',
             'title': 'TI TLV9001IDBVR', 'brandNameEn': 'TI',
             'encapStandard': 'SOT-23-5', 'parentCatalogId': 380,
             'isMro': False},
            {'productCode': 'C777', 'productModel': 'SCREW',
             'title': '螺丝', 'parentCatalogId': 999999, 'isMro': False},
        ])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['catalog_code'], 'C398363')
        self.assertEqual(rows[0]['name'], 'TI TLV9001IDBVR')
        self.assertEqual(rows[0]['brand'], 'TI')

    def test_search_candidates_uses_one_search_request_only(self):
        calls = []

        def fake(keyword, **_kwargs):
            calls.append(keyword)
            return [{'productCode': 'C398363', 'productModel': 'TLV9001IDBVR',
                     'title': 'TI TLV9001IDBVR', 'parentCatalogId': 380}]

        remote.search_products = fake
        rows = remote.search_candidates(' TLV9001 ')
        self.assertEqual(calls, ['TLV9001'])
        self.assertEqual([r['catalog_code'] for r in rows], ['C398363'])

    def test_short_keyword_never_reaches_the_network(self):
        remote.search_products = mock.Mock(
            side_effect=AssertionError('must not call LCSC'))
        with self.assertRaises(remote.LcscRemoteError):
            remote.search_candidates('TLV9')
        self.assertFalse(remote.search_products.called)


class ResolveMpnTest(unittest.TestCase):

    def setUp(self):
        self._original = remote.search_products

    def tearDown(self):
        remote.search_products = self._original

    def test_exact_match_is_selected(self):
        remote.search_products = lambda _kw, **_kw_extra: [
            {'productCode': 'C1', 'productModel': 'TLV77333PDQNR'},
            {'productCode': 'C54110218', 'productModel': 'TLV77733PDBVR'},
        ]
        item, candidates = remote.resolve_mpn('tlv77733pdbvr')
        self.assertEqual(item['productCode'], 'C54110218')
        self.assertEqual(candidates, [])

    def test_fuzzy_results_are_candidates_only(self):
        remote.search_products = lambda _kw, **_kw_extra: [
            {'productCode': 'C1', 'productModel': 'TLV77333PDQNR'},
            {'productCode': 'C2', 'productModel': 'TLV77333PDBVR'},
        ]
        item, candidates = remote.resolve_mpn('TLV77333')
        self.assertIsNone(item)
        self.assertEqual([c['catalog_code'] for c in candidates], ['C1', 'C2'])

    def test_duplicate_exact_rows_are_ambiguous(self):
        remote.search_products = lambda _kw, **_kw_extra: [
            {'productCode': 'C1', 'productModel': 'SAME'},
            {'productCode': 'C2', 'productModel': 'SAME'},
        ]
        item, candidates = remote.resolve_mpn('SAME')
        self.assertIsNone(item)
        self.assertEqual(len(candidates), 2)


class ClassifyRootTest(unittest.TestCase):

    def test_allowed_root(self):
        self.assertEqual(remote.classify_root(380, False, {380}), 'electronic')

    def test_mro_is_excluded(self):
        self.assertEqual(remote.classify_root(380, True, {380}), 'non_electronic')

    def test_other_root_is_non_electronic(self):
        self.assertEqual(remote.classify_root(999999, False, {380}),
                         'non_electronic')

    def test_missing_root_is_unknown(self):
        for value in (None, '', 0, 'x'):
            self.assertEqual(remote.classify_root(value, False, {380}), 'unknown')


class ParseChinesePageTest(unittest.TestCase):

    def test_chinese_fields(self):
        parsed = remote.parse_cn_page(_cn_html(), expected='C54110218')
        self.assertEqual(parsed['code'], 'C54110218')
        self.assertEqual(parsed['product_id'], '57330406')
        self.assertEqual(parsed['name'], '测试器件')
        self.assertEqual(parsed['brand'], 'TI(德州仪器)')
        self.assertEqual(parsed['package'], 'SOT-23-5')
        self.assertEqual(parsed['currency'], 'CNY')
        self.assertEqual(parsed['stock'], 1866)
        self.assertEqual(parsed['catalog']['catalogId'], 387)
        self.assertEqual(parsed['parameters'][0]['parameterName'], '输出极性')
        self.assertEqual(parsed['parameters'][1]['parameterDetailValue'], '3.3V')
        self.assertEqual(parsed['image_url'], '//alimg.szlcsc.com/a.jpg')
        self.assertEqual(parsed['source_url'],
                         'https://item.szlcsc.com/57330406.html')

    def test_code_mismatch_is_rejected(self):
        with self.assertRaises(remote.LcscRemoteError):
            remote.parse_cn_page(_cn_html(), expected='C32445874')

    def test_missing_next_data_is_rejected(self):
        with self.assertRaises(remote.LcscRemoteError):
            remote.parse_cn_page('<html>验证页</html>')

    def test_host_allowlist(self):
        with self.assertRaises(remote.LcscRemoteError):
            remote._check_host('https://evil.example.com/x')


class FilterPolicyTest(unittest.TestCase):

    def test_bundled_policy_matches_crawler_when_present(self):
        crawler = os.path.abspath(os.path.join(
            _HERE, '..', '..', '..', 'crawler',
            'lcsc_electronics_filter.json'))
        if not os.path.exists(crawler):
            self.skipTest('crawler policy not present in this checkout')
        with open(crawler, encoding='utf-8') as handle:
            expected = json.load(handle)
        self.assertEqual(
            sorted(remote.allowed_root_ids()),
            sorted(int(x) for x in expected['allowed_root_ids']))
        self.assertIn(380, remote.allowed_root_ids())



class SyncBudgetTest(unittest.TestCase):
    """The synchronous path must spend no new request once its budget is gone."""

    def test_expired_deadline_blocks_before_any_request(self):
        with self.assertRaises(remote.LcscRemoteError) as ctx:
            remote._request(
                'https://wmsc.lcsc.com/ftps/wm/product/detail',
                deadline=time.monotonic() - 1)
        self.assertEqual(ctx.exception.code, 'budget_exhausted')

    def test_host_allowlist_beats_budget_on_unknown_host(self):
        with self.assertRaises(remote.LcscRemoteError) as ctx:
            remote._request('https://evil.example.com/x',
                            deadline=time.monotonic() + 5)
        self.assertEqual(ctx.exception.code, 'host_not_allowed')

    def test_fetch_product_detail_forwards_deadline(self):
        with self.assertRaises(remote.LcscRemoteError) as ctx:
            remote.fetch_product_detail('C1',
                                        deadline=time.monotonic() - 1)
        self.assertEqual(ctx.exception.code, 'budget_exhausted')

    def test_socket_timeout_is_capped_by_remaining_budget(self):
        """The last request may not outlive the remaining budget."""
        captured = {}

        class _Response(object):
            headers = {'Content-Type': 'text/html'}

            def __init__(self):
                self._done = False

            def read(self, _size=-1):
                if self._done:
                    return b''
                self._done = True
                return b'ok'

            def close(self):
                pass

        def fake_open(request, timeout=None):
            captured['timeout'] = timeout
            return _Response()

        with mock.patch.object(remote, '_open_response', fake_open):
            remote._request('https://wmsc.lcsc.com/x', timeout=6,
                            deadline=time.monotonic() + 2)
        self.assertLessEqual(captured['timeout'], 2.0)
        self.assertGreaterEqual(captured['timeout'], 1.0)

    def test_http_transport_is_ipv4_only(self):
        """AAAA 不可达时不按 getaddrinfo 顺序去试 IPv6（会白等 120 秒）。"""
        calls = {}

        class _FakeSock(object):
            def __init__(self, family, socktype, proto):
                calls['family'] = family

            def settimeout(self, value):
                calls['timeout'] = value

            def connect(self, address):
                calls['address'] = address

            def close(self):
                pass

        context = mock.Mock()
        context.wrap_socket.side_effect = (
            lambda sock, server_hostname=None: sock)
        connection = remote._IPv4HTTPSConnection(
            'wmsc.lcsc.com', timeout=6, context=context)

        def fake_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
            calls['family_arg'] = family
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '',
                     ('3.165.39.67', 443))]

        with mock.patch.object(remote.socket, 'getaddrinfo', fake_getaddrinfo),                 mock.patch.object(remote.socket, 'socket', _FakeSock):
            connection.connect()
        self.assertEqual(calls['family_arg'], socket.AF_INET)
        self.assertEqual(calls['family'], socket.AF_INET)
        self.assertEqual(calls['address'], ('3.165.39.67', 443))
        self.assertEqual(calls['timeout'], 6)
        context.wrap_socket.assert_called_once()

    def test_resolve_mpn_forwards_deadline(self):
        with self.assertRaises(remote.LcscRemoteError) as ctx:
            remote.resolve_mpn('TLV77333PDBVR',
                               deadline=time.monotonic() - 1)
        self.assertEqual(ctx.exception.code, 'budget_exhausted')


if __name__ == '__main__':
    unittest.main()
