# -*- coding: utf-8 -*-
"""Pure tests for the official JLC OpenAPI client.

No network: the HTTP layer is a fake opener, and the signing scheme is
checked against the vendor SDK's documented string layout.
"""
import base64
import hashlib
import hmac
import importlib.util
import json
import os
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.abspath(os.path.join(_HERE, '..', 'tools', 'lcsc_openapi.py'))
_spec = importlib.util.spec_from_file_location('lcsc_openapi_test', _SRC)
openapi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(openapi)


class _FakeResponse(object):

    def __init__(self, payload, status=200):
        self._raw = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.status = status

    def read(self):
        return self._raw


class _FakeOpener(object):

    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def __call__(self, request, timeout=None):
        self.calls.append({'request': request, 'timeout': timeout})
        return _FakeResponse(self.payload)


class SigningTest(unittest.TestCase):

    def test_string_to_sign_has_five_lines_and_trailing_newline(self):
        value = openapi.string_to_sign(
            'post', '/lcsc/openapi/x?a=1', '1700000000', 'abc', '{"k":1}')
        self.assertEqual(
            value,
            'POST\n/lcsc/openapi/x?a=1\n1700000000\nabc\n{"k":1}\n')

    def test_empty_body_keeps_its_line(self):
        value = openapi.string_to_sign('POST', '/p', 1, 'n', '')
        self.assertEqual(value, 'POST\n/p\n1\nn\n\n')

    def test_signature_is_base64_hmac_sha256(self):
        expected = base64.b64encode(hmac.new(
            b'secret', b'payload', hashlib.sha256).digest()).decode('ascii')
        self.assertEqual(openapi.sign('secret', 'payload'), expected)

    def test_authorization_header_layout(self):
        header = openapi.authorization_header(
            'APP1', 'KEY1', 'SIG', '1700000000', 'NONCE')
        self.assertEqual(
            header,
            'JOP appid="APP1",accesskey="KEY1",timestamp="1700000000",'
            'nonce="NONCE",signature="SIG"')

    def test_nonce_is_32_alphanumeric(self):
        value = openapi._nonce()
        self.assertEqual(len(value), 32)
        self.assertTrue(value.isalnum())


class ClientTest(unittest.TestCase):

    def client(self, payload):
        opener = _FakeOpener(payload)
        return openapi.LcscOpenApi(
            'https://api.example.jlc.com', 'APP', 'KEY', 'SECRET',
            opener=opener), opener

    def test_http_is_refused(self):
        with self.assertRaises(openapi.LcscOpenApiError) as ctx:
            openapi.LcscOpenApi('http://api.example.jlc.com', 'a', 'b', 'c')
        self.assertEqual(ctx.exception.code, 'invalid_base_url')

    def test_missing_credentials_are_refused(self):
        with self.assertRaises(openapi.LcscOpenApiError) as ctx:
            openapi.LcscOpenApi('https://api.example.jlc.com', '', 'b', 'c')
        self.assertEqual(ctx.exception.code, 'missing_credentials')

    def test_search_posts_signed_json(self):
        client, opener = self.client({
            'code': 200, 'message': 'ok',
            'data': [{'productCode': 'C8734', 'productModel': 'STM32F103C8T6'}],
        })
        rows = client.search_products('STM32F103', limit=5)

        call = opener.calls[0]
        request = call['request']
        self.assertEqual(request.get_method(), 'POST')
        self.assertTrue(request.full_url.endswith(
            openapi.SEARCH_PATH))
        self.assertEqual(json.loads(request.data.decode('utf-8')),
                         {'keyword': 'STM32F103'})
        header = request.get_header('Authorization')
        self.assertTrue(header.startswith('JOP appid="APP",accesskey="KEY"'))
        self.assertIn('signature="', header)
        self.assertEqual(len(rows), 1)

    def test_api_error_carries_server_message(self):
        client, _ = self.client({'code': 401, 'message': '签名无效'})
        with self.assertRaises(openapi.LcscOpenApiError) as ctx:
            client.search_products('x')
        self.assertEqual(ctx.exception.code, 'api_error')
        self.assertIn('签名无效', ctx.exception.message)

    def test_code_zero_is_accepted(self):
        client, _ = self.client({'code': 0, 'message': '', 'data': []})
        self.assertEqual(client.search_products('x'), [])


class CandidateMappingTest(unittest.TestCase):

    def test_official_rows_map_to_candidates(self):
        rows = openapi.candidates_from([
            {'productCode': 'C8734', 'productModel': 'STM32F103C8T6',
             'productName': 'ST STM32F103C8T6', 'brandName': 'ST',
             'standard': 'LQFP-48', 'description': 'MCU',
             'gdStockNum': 120, 'jsStockNum': 5},
            {'productCode': 'C1'},
            {'productModel': 'NO-CODE'},
        ])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['catalog_code'], 'C8734')
        self.assertEqual(rows[0]['name'], 'ST STM32F103C8T6')
        self.assertEqual(rows[0]['package'], 'LQFP-48')
        self.assertEqual(rows[0]['catalog_stock'], 120)
        self.assertEqual(rows[1]['catalog_code'], 'C1')

    def test_bare_numeric_code_gets_c_prefix(self):
        rows = openapi.candidates_from([{'productCode': '8734'}])
        self.assertEqual(rows[0]['catalog_code'], 'C8734')


class SmtChannelTest(unittest.TestCase):
    """贴片通道：按 C 编号取资料，响应里带中文参数与阶梯价。"""

    ROW = {
        'componentId': 18102,
        'componentCode': 'C17414',
        'componentName': '10kΩ ±1% 125mW 厚膜电阻',
        'componentType': '贴片电阻',
        'componentModel': '0805W8F1002T5E',
        'componentSpecification': '0805',
        'componentBrand': 'UNI-ROYAL(厚声)',
        'encapsulationNumber': 5000,
        'stockNum': 12889583,
        'paramTextAll': '阻值:10kΩ,精度:±1%,功率:1/8w',
        'smtComponentPriceInfoVOList': [
            {'startNumber': 50200, 'endNumber': -1, 'productPrice': 0.0047},
            {'startNumber': 1, 'endNumber': 50200, 'productPrice': 0.0101},
        ],
    }

    def test_codes_are_normalised_and_posted(self):
        opener = _FakeOpener({'code': 200, 'data': [self.ROW]})
        client = openapi.LcscOpenApi(
            'https://open-api.jlc.com', 'APP', 'KEY', 'SECRET',
            opener=opener)
        rows = client.smt_components(['C17414', 'c1', ' '])
        body = json.loads(opener.calls[0]['request'].data.decode('utf-8'))
        self.assertEqual(body, {'componentCodeList': ['C17414', 'C1']})
        self.assertEqual(len(rows), 1)

    def test_empty_codes_make_no_request(self):
        opener = _FakeOpener({'code': 200, 'data': []})
        client = openapi.LcscOpenApi(
            'https://open-api.jlc.com', 'APP', 'KEY', 'SECRET',
            opener=opener)
        self.assertEqual(client.smt_components([]), [])
        self.assertEqual(opener.calls, [])

    def test_param_text_becomes_parameter_list(self):
        params = openapi.parameters_from_text('阻值:10kΩ,精度:±1%,坏数据')
        self.assertEqual(params, [
            {'parameterName': '阻值', 'parameterValue': '10kΩ'},
            {'parameterName': '精度', 'parameterValue': '±1%'},
        ])

    def test_row_maps_to_upsert_shape(self):
        item = openapi.item_from_smt(self.ROW)
        self.assertEqual(item['code'], 'C17414')
        self.assertEqual(item['product_id'], 18102)
        self.assertEqual(item['mpn'], '0805W8F1002T5E')
        self.assertEqual(item['package'], '0805')
        self.assertEqual(item['stock'], 12889583)
        self.assertEqual(item['price'], 0.0101)          # 最小数量档
        self.assertEqual(item['price_basis'], 'openapi_smt_tier_price')
        self.assertEqual(len(item['parameters']), 3)
        self.assertEqual([t['start'] for t in item['price_tiers']],
                         [50200, 1])

    def test_rows_without_code_are_skipped(self):
        self.assertEqual(openapi.items_from_smt([{'componentId': 1}]), [])

    def test_merge_keeps_page_category_and_docs(self):
        merged = openapi.merge_into_parsed(
            {'code': 'C17414', 'category_path': '电阻 > 贴片电阻',
             'files': [{'url': 'x'}], 'stock': 1, 'price': 0.5,
             'parameters': [{'parameterName': '旧参数'}]},
            openapi.item_from_smt(self.ROW))
        self.assertEqual(merged['category_path'], '电阻 > 贴片电阻')
        self.assertEqual(merged['files'], [{'url': 'x'}])
        self.assertEqual(merged['stock'], 12889583)
        self.assertEqual(merged['price'], 0.0101)
        self.assertEqual(merged['price_basis'], 'openapi_smt_tier_price')
        self.assertEqual(merged['parameters'][0]['parameterName'], '阻值')
        self.assertEqual(merged['official_source'], 'openapi_smt')

    def test_merge_without_official_returns_copy(self):
        parsed = {'code': 'C1', 'stock': 3}
        merged = openapi.merge_into_parsed(parsed, None)
        self.assertEqual(merged, parsed)
        self.assertIsNot(merged, parsed)


class CredentialsFileTest(unittest.TestCase):
    """本地自检路径：只读凭据文件，断言里也不打印真实值。"""

    def _write(self, text):
        import tempfile
        handle = tempfile.NamedTemporaryFile(
            'w', suffix='.csv', delete=False, encoding='utf-8')
        handle.write(text)
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def test_row_is_access_key_and_secret(self):
        path = self._write(
            'ACCESS123,SECRETSECRETSECRETSECRETSECRET12\n'
            'OTHER1234,OTHEROTHEROTHEROTHEROTHEROTHER12\n')
        client = openapi.client_from_csv(
            path, row=2, app_id='632475146604457986',
            base_url='https://api.example.jlc.com')
        self.assertEqual(client._app_id, '632475146604457986')
        self.assertEqual(client._access_key, 'OTHER1234')
        self.assertEqual(client._secret_key,
                         'OTHEROTHEROTHEROTHEROTHEROTHER12')

    def test_bom_and_blank_lines_are_tolerated(self):
        path = self._write('﻿ACCESS123,SECRETSECRETSECRETSECRETSECRET12\n\n')
        client = openapi.client_from_csv(
            path, app_id='632475146604457986',
            base_url='https://api.example.jlc.com')
        self.assertEqual(client._access_key, 'ACCESS123')

    def test_app_id_must_come_from_elsewhere(self):
        path = self._write('ACCESS123,SECRETSECRETSECRETSECRETSECRET12\n')
        with self.assertRaises(openapi.LcscOpenApiError) as ctx:
            openapi.client_from_csv(
                path, base_url='https://api.example.jlc.com', environ={})
        self.assertEqual(ctx.exception.code, 'missing_app_id')

    def test_missing_row_is_refused(self):
        path = self._write('a,b\n')
        with self.assertRaises(openapi.LcscOpenApiError) as ctx:
            openapi.client_from_csv(
                path, row=2, app_id='632475146604457986',
                base_url='https://api.example.jlc.com')
        self.assertEqual(ctx.exception.code, 'bad_credentials_file')


if __name__ == '__main__':
    unittest.main()
