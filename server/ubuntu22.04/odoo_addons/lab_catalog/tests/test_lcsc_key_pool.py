# -*- coding: utf-8 -*-
"""立创开放平台 Key 号码池的纯逻辑（不需要 Odoo）。

用户的原话：「现在使用一个很容易就限流了我想多搞几个号做号码池」。

规则：
* 轮询取用，同一个 Key 不连续用两次（除非只有一个）；
* 返回 429（超限）就把该 Key 标记为「今日不可用」并换下一个；
* 全部用完就报错，不无限重试；
* 401/签名错误不自动切换——那是 Key 本身配错了，换也没用。
"""
import importlib.util
import os
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.abspath(os.path.join(_HERE, '..', 'tools', 'lcsc_key_pool.py'))
_spec = importlib.util.spec_from_file_location('lcsc_key_pool_test', _SRC)
_pool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_pool)


def key(ident, app_id='app', access='ak', secret='sk'):
    return {'id': ident, 'app_id': app_id, 'access_key': access, 'secret_key': secret}


class KeyPoolTest(unittest.TestCase):

    def test_round_robin_rotates_between_keys(self):
        pool = _pool.KeyPool([key(1), key(2), key(3)])
        picked = [pool.next()['id'] for _ in range(6)]
        self.assertEqual(picked, [1, 2, 3, 1, 2, 3])

    def test_single_key_is_reused(self):
        pool = _pool.KeyPool([key(1)])
        self.assertEqual([pool.next()['id'] for _ in range(3)], [1, 1, 1])

    def test_rate_limited_key_is_skipped(self):
        pool = _pool.KeyPool([key(1), key(2)])
        first = pool.next()
        pool.mark_rate_limited(first['id'])
        for _ in range(4):
            self.assertEqual(pool.next()['id'], 2)

    def test_all_keys_limited_raises(self):
        pool = _pool.KeyPool([key(1), key(2)])
        pool.mark_rate_limited(1)
        pool.mark_rate_limited(2)
        with self.assertRaises(_pool.NoAvailableKey):
            pool.next()

    def test_empty_pool_raises(self):
        with self.assertRaises(_pool.NoAvailableKey):
            _pool.KeyPool([]).next()

    def test_auth_error_is_not_auto_skipped(self):
        """401 是 Key 配错了，换一个也没用——不该悄悄切换掩盖问题。"""
        pool = _pool.KeyPool([key(1), key(2)])
        first = pool.next()
        self.assertFalse(_pool.should_rotate_on_error(401))
        self.assertFalse(_pool.should_rotate_on_error('INVALID_CREDENTIALS'))
        self.assertNotIn(first['id'], pool.rate_limited_ids())

    def test_429_triggers_rotation(self):
        self.assertTrue(_pool.should_rotate_on_error(429))
        self.assertTrue(_pool.should_rotate_on_error('RATE_LIMITED'))

    def test_other_errors_do_not_rotate(self):
        for code in (500, 502, 400, 'NETWORK_ERROR'):
            self.assertFalse(_pool.should_rotate_on_error(code), code)

    def test_available_count_reflects_limits(self):
        pool = _pool.KeyPool([key(1), key(2), key(3)])
        self.assertEqual(pool.available_count(), 3)
        pool.mark_rate_limited(2)
        self.assertEqual(pool.available_count(), 2)

    def test_reset_clears_daily_limits(self):
        pool = _pool.KeyPool([key(1), key(2)])
        pool.mark_rate_limited(1)
        self.assertEqual(pool.available_count(), 1)
        pool.reset_limits()
        self.assertEqual(pool.available_count(), 2)

    def test_key_without_secret_is_rejected(self):
        with self.assertRaises(ValueError):
            _pool.KeyPool([key(1, secret='')])


if __name__ == '__main__':
    unittest.main()
