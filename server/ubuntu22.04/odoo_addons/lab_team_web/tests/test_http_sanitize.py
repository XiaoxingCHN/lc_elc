# -*- coding: utf-8 -*-
import importlib.util
import os
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(os.path.dirname(_HERE), 'http_sanitize.py')
_spec = importlib.util.spec_from_file_location('ltw_sanitize', _PATH)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def err(exc_name, message='x', **extra):
    data = {'name': exc_name, 'message': message, 'arguments': ['secret'],
            'context': {'path': '/home/user'}, 'debug': 'Traceback /home/user'}
    data.update(extra)
    return {'code': 0, 'message': 'Odoo Server Error', 'data': data}


class TestSanitize(unittest.TestCase):
    def test_unknown_error_whitelist_rebuild(self):
        original = err('builtins.KeyError', message='top secret /home/user SELECT * FROM res_users',
                       internal_field={'sql': 'SELECT 1'}, nested={'a': {'debug': 'x'}})
        out, tid = mod.sanitize_jsonrpc_error(original, trace_id='tid1')
        self.assertEqual(original['data']['debug'], 'Traceback /home/user')
        data = out['data']
        self.assertEqual(set(data), {'name', 'message', 'trace_id'})
        self.assertNotIn('/home/', data['message'])
        self.assertNotIn('SELECT', data['message'])
        self.assertEqual(data['name'], 'ServerError')
        self.assertIn('tid1', data['message'])
        self.assertEqual(out['message'], 'Odoo Server Error')
        self.assertEqual(out['code'], 0)

    def test_unknown_top_message_never_leaks(self):
        out, _ = mod.sanitize_jsonrpc_error(
            {'code': 0, 'message': 'Traceback /home/user SQLSTATE 42P01', 'data': {'name': 'builtins.Exception'}})
        self.assertNotIn('Traceback', out['message'])
        self.assertNotIn('/home/', out['message'])

    def test_safe_exception_keeps_full_name_and_business_message(self):
        out, _ = mod.sanitize_jsonrpc_error(err('odoo.exceptions.UserError', message='库存不足，请调整数量'))
        self.assertEqual(out['data']['name'], 'odoo.exceptions.UserError')
        self.assertEqual(out['data']['message'], '库存不足，请调整数量')
        self.assertNotIn('debug', out['data'])

    def test_safe_exception_internal_message_replaced(self):
        out, _ = mod.sanitize_jsonrpc_error(
            err('odoo.exceptions.ValidationError', message='File "/home/x" line 3 SQLSTATE 42P01'))
        self.assertEqual(out['data']['name'], 'odoo.exceptions.ValidationError')
        self.assertNotIn('/home/', out['data']['message'])
        self.assertIn('参考编号', out['data']['message'])

    def test_session_expired_full_name(self):
        out, _ = mod.sanitize_jsonrpc_error(err('odoo.http.SessionExpiredException', message='会话已过期'))
        self.assertEqual(out['data']['name'], 'odoo.http.SessionExpiredException')
        self.assertEqual(out['data']['message'], '会话已过期')

    def test_access_denied_full_name(self):
        out, _ = mod.sanitize_jsonrpc_error(err('odoo.exceptions.AccessDenied'))
        self.assertEqual(out['data']['name'], 'odoo.exceptions.AccessDenied')

    def test_extra_and_nested_fields_dropped(self):
        out, _ = mod.sanitize_jsonrpc_error(err('odoo.exceptions.AccessDenied', extra={'arguments': ['p']}))
        self.assertEqual(set(out['data']), {'name', 'message', 'trace_id'})

    def test_non_dict_passthrough(self):
        value = object()
        out, tid = mod.sanitize_jsonrpc_error(value)
        self.assertIs(out, value)
        self.assertIsNone(tid)


if __name__ == '__main__':
    unittest.main()
