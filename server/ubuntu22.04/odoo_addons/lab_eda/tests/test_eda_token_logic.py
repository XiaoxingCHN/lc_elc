# -*- coding: utf-8 -*-
"""EDA Token 的纯逻辑回归（不需要 Odoo、不需要数据库）。

与 ``lab_inventory/tools/param_search.py`` 同样的分层：可离线验证的规则放在
``tools/`` 下，Odoo 模型只负责持久化与权限。
"""
import importlib.util
import os
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.abspath(os.path.join(_HERE, '..', 'tools', 'eda_token.py'))
_spec = importlib.util.spec_from_file_location('lc_eda_token_test', _SRC)
_token = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_token)


class EdaTokenLogicTest(unittest.TestCase):

    def test_generated_token_has_the_expected_shape(self):
        token = _token.generate()
        self.assertTrue(token.startswith('eda_'), token[:12])
        # 'eda_' + 43 chars (token_urlsafe(32))
        self.assertEqual(len(token), 4 + 43)

    def test_generated_tokens_are_unique(self):
        tokens = {_token.generate() for _ in range(50)}
        self.assertEqual(len(tokens), 50)

    def test_generated_token_is_url_safe(self):
        """Token 会出现在 HTTP 头与配置文件里，不能含空白或引号。"""
        for _ in range(20):
            token = _token.generate()
            self.assertRegex(token, r'^eda_[A-Za-z0-9_-]+$')

    def test_hash_is_sha256_hex(self):
        token = _token.generate()
        digest = _token.hash_token(token)
        self.assertEqual(len(digest), 64)
        self.assertRegex(digest, r'^[0-9a-f]{64}$')

    def test_hash_is_stable(self):
        token = _token.generate()
        self.assertEqual(_token.hash_token(token), _token.hash_token(token))

    def test_hash_never_contains_the_plaintext(self):
        token = _token.generate()
        self.assertNotIn(token, _token.hash_token(token))

    def test_different_tokens_hash_differently(self):
        a, b = _token.generate(), _token.generate()
        self.assertNotEqual(_token.hash_token(a), _token.hash_token(b))

    def test_matches_accepts_the_right_token(self):
        token = _token.generate()
        self.assertTrue(_token.matches(token, _token.hash_token(token)))

    def test_matches_rejects_a_wrong_token(self):
        token = _token.generate()
        self.assertFalse(_token.matches(_token.generate(), _token.hash_token(token)))

    def test_matches_rejects_empty_and_none(self):
        token = _token.generate()
        digest = _token.hash_token(token)
        self.assertFalse(_token.matches('', digest))
        self.assertFalse(_token.matches(None, digest))

    def test_matches_rejects_a_malformed_stored_hash(self):
        self.assertFalse(_token.matches(_token.generate(), 'not-a-hash'))

    def test_is_valid_rejects_inactive(self):
        self.assertFalse(_token.is_valid(active=False, expires_at=None, now=1000.0))

    def test_is_valid_accepts_no_expiry(self):
        self.assertTrue(_token.is_valid(active=True, expires_at=None, now=1000.0))

    def test_is_valid_accepts_future_expiry(self):
        self.assertTrue(_token.is_valid(active=True, expires_at=2000.0, now=1000.0))

    def test_is_valid_rejects_past_expiry(self):
        self.assertFalse(_token.is_valid(active=True, expires_at=900.0, now=1000.0))

    def test_is_valid_rejects_expiry_equal_to_now(self):
        """到点即失效，不留一个边界窗口。"""
        self.assertFalse(_token.is_valid(active=True, expires_at=1000.0, now=1000.0))

    def test_expiry_from_days(self):
        self.assertAlmostEqual(_token.expiry_from_days(365, now=0.0), 365 * 86400.0)
        self.assertAlmostEqual(_token.expiry_from_days(1, now=0.0), 86400.0)

    def test_expiry_from_days_zero_means_never(self):
        self.assertIsNone(_token.expiry_from_days(0, now=1000.0))

    def test_expiry_from_days_rejects_negative(self):
        with self.assertRaises(ValueError):
            _token.expiry_from_days(-1, now=0.0)

    def test_default_validity_is_one_year(self):
        self.assertEqual(_token.DEFAULT_VALIDITY_DAYS, 365)


if __name__ == '__main__':
    unittest.main()
