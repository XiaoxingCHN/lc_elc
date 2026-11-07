# -*- coding: utf-8 -*-
"""Pure tests for the on-demand LCSC fetch helpers.

No Odoo database and no network: the HTTP layer is monkeypatched, and the
Chinese page fixture mirrors the real ``__NEXT_DATA__`` shape (中文参数名).
"""
import importlib.util
import json
import os
import unittest

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


class ResolveMpnTest(unittest.TestCase):

    def setUp(self):
        self._original = remote.search_products

    def tearDown(self):
        remote.search_products = self._original

    def test_exact_match_is_selected(self):
        remote.search_products = lambda _kw: [
            {'productCode': 'C1', 'productModel': 'TLV77333PDQNR'},
            {'productCode': 'C54110218', 'productModel': 'TLV77733PDBVR'},
        ]
        item, candidates = remote.resolve_mpn('tlv77733pdbvr')
        self.assertEqual(item['productCode'], 'C54110218')
        self.assertEqual(candidates, [])

    def test_fuzzy_results_are_candidates_only(self):
        remote.search_products = lambda _kw: [
            {'productCode': 'C1', 'productModel': 'TLV77333PDQNR'},
            {'productCode': 'C2', 'productModel': 'TLV77333PDBVR'},
        ]
        item, candidates = remote.resolve_mpn('TLV77333')
        self.assertIsNone(item)
        self.assertEqual([c['catalog_code'] for c in candidates], ['C1', 'C2'])

    def test_duplicate_exact_rows_are_ambiguous(self):
        remote.search_products = lambda _kw: [
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


if __name__ == '__main__':
    unittest.main()
