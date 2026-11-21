# -*- coding: utf-8 -*-
"""``eda_auth`` 的头部解析（纯逻辑，不需要 Odoo）。

真正把 token 换成 ``env.uid`` 的那一步依赖 Odoo 请求上下文，由
``test_eda_token.py`` 覆盖；这里只钉住「什么算带了 token」。

控制器模块会 import odoo，离线环境跑不了，所以按源码抽出 ``_bearer_token``
单独执行——保证规则本身被验证过，而不是复制一份实现来自测。
"""
import os
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_CONTROLLER = os.path.join(_HERE, '..', 'controllers', 'lab_eda_api.py')


def _load_bearer():
    with open(_CONTROLLER, encoding='utf-8') as handle:
        source = handle.read()
    start = source.index('def _bearer_token():')
    end = source.index('def _auth_error(')
    namespace = {'request': None}
    exec(source[start:end], namespace)          # noqa: S102 - 只定义纯函数
    return namespace


class EdaAuthHeaderTest(unittest.TestCase):

    def setUp(self):
        self.namespace = _load_bearer()
        self.bearer = self.namespace['_bearer_token']

    def _call_with_header(self, value):
        fake_request = mock.MagicMock()
        fake_request.httprequest.headers.get.return_value = value
        self.namespace['request'] = fake_request
        return self.bearer()

    def test_extracts_the_token(self):
        self.assertEqual(self._call_with_header('bearer eda_abc123'), 'eda_abc123')

    def test_scheme_is_case_insensitive(self):
        self.assertEqual(self._call_with_header('Bearer eda_abc123'), 'eda_abc123')
        self.assertEqual(self._call_with_header('BEARER eda_abc123'), 'eda_abc123')

    def test_missing_header_returns_empty(self):
        self.assertEqual(self._call_with_header(None), '')

    def test_empty_header_returns_empty(self):
        self.assertEqual(self._call_with_header(''), '')

    def test_non_bearer_scheme_returns_empty(self):
        self.assertEqual(self._call_with_header('Basic dXNlcjpwYXNz'), '')

    def test_strips_surrounding_whitespace(self):
        self.assertEqual(self._call_with_header('bearer   eda_abc123  '), 'eda_abc123')


if __name__ == '__main__':
    unittest.main()
