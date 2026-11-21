# -*- coding: utf-8 -*-
"""``lab_eda`` 必须同时认得两套 ``LabApiError``。

``lab_catalog`` 和 ``lab_workflow`` 各有一个**同名不同类**的 ``LabApiError``。
``lab_catalog`` 的 ``api_route`` 只捕获它自己那个，所以 EDA 控制器转发到
``lab_workflow`` 业务方法时，业务错误会掉进兜底的 ``except Exception``，
用户看到「服务器内部错误」而不是「没有代领权限」。

这个测试用两个替身类模拟两套异常，验证映射函数把它们的 code/message/fields
原样保留。
"""
import importlib.util
import os
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_CONTROLLER = os.path.join(_HERE, '..', 'controllers', 'lab_eda_api.py')


def _load_mapper():
    with open(_CONTROLLER, encoding='utf-8') as handle:
        source = handle.read()
    start = source.index('def _map_business_error(')
    # 到下一个顶层定义为止
    end = source.index('\ndef ', start + 10)
    namespace = {'LabApiError': type('LabApiError', (Exception,), {})}
    exec(source[start:end], namespace)          # noqa: S102 - 只定义纯函数
    return namespace['_map_business_error']


class _WorkflowError(Exception):
    """模拟 lab_workflow.LabApiError 的形状。"""

    def __init__(self, code, message, fields=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.fields = fields or {}


class EdaErrorMappingTest(unittest.TestCase):

    def setUp(self):
        self.mapper = _load_mapper()

    def test_maps_a_foreign_error_with_code_and_message(self):
        error = _WorkflowError('FORBIDDEN', '当前账号没有代领权限', {'borrower_id': 'not_self'})
        mapped = self.mapper(error)
        self.assertIsNotNone(mapped)
        self.assertEqual(mapped['code'], 'FORBIDDEN')
        self.assertEqual(mapped['message'], '当前账号没有代领权限')
        self.assertEqual(mapped['fields'], {'borrower_id': 'not_self'})

    def test_returns_none_for_errors_without_a_code(self):
        """没有 code 属性的异常不是业务错误，交给外层兜底。"""
        self.assertIsNone(self.mapper(ValueError('boom')))

    def test_returns_none_for_a_bare_exception(self):
        self.assertIsNone(self.mapper(Exception('boom')))

    def test_keeps_empty_fields_when_absent(self):
        error = _WorkflowError('NOT_FOUND', '找不到')
        mapped = self.mapper(error)
        self.assertEqual(mapped['fields'], {})


if __name__ == '__main__':
    unittest.main()
