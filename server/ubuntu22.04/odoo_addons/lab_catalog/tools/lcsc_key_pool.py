# -*- coding: utf-8 -*-
"""立创开放平台 Key 号码池（纯逻辑，不依赖 Odoo）。

背景
----
用户原话：「现在使用一个很容易就限流了我想多搞几个号做号码池」。
开放平台的限流是按 **appId** 算的，所以多套 Key 轮着用能把日额度叠加起来。

规则
----
* **轮询**：依次取用，同一把 Key 不连续用两次（除非池里只有一把）。
* **遇 429 切换**：该 Key 标记为「今日已超限」，换下一把。
* **401 / 签名错误不切换**：那是 Key 本身配错了，换一把也是错的，
  悄悄切过去只会掩盖问题。
* **全部用完就报错**：不无限重试。

限流标记只存在内存里——进程重启就清空，与开放平台按自然日重置的行为一致。
"""


class NoAvailableKey(Exception):
    """池里所有 Key 都用完了（或池是空的）。"""

    def __init__(self, message='所有立创开放平台密钥都已超限，请明天再试或补充密钥。'):
        super().__init__(message)
        self.message = message


# 这些错误说明「换一把 Key 可能就好了」
_ROTATE_STATUS = (429,)
_ROTATE_CODES = frozenset({'RATE_LIMITED', 'TOO_MANY_REQUESTS', 'QUOTA_EXCEEDED'})


def should_rotate_on_error(code):
    """该错误是否应该换下一把 Key。

    :param code: HTTP 状态码（int）或错误码字符串
    """
    if isinstance(code, int):
        return code in _ROTATE_STATUS
    return str(code or '').upper() in _ROTATE_CODES


class KeyPool:
    """一组立创 Key，轮询取用。

    :param keys: ``[{'id', 'app_id', 'access_key', 'secret_key'}, ...]``
    """

    def __init__(self, keys):
        self._keys = []
        for entry in keys or []:
            if not entry:
                continue
            if not entry.get('secret_key') or not entry.get('app_id'):
                raise ValueError('立创密钥缺少 app_id 或 secret_key')
            self._keys.append(dict(entry))
        self._cursor = 0
        self._limited = set()

    def next(self):
        """取下一把可用的 Key；全部超限时抛 :class:`NoAvailableKey`。"""
        total = len(self._keys)
        if not total:
            raise NoAvailableKey('还没有配置任何立创开放平台密钥。')
        for offset in range(total):
            index = (self._cursor + offset) % total
            entry = self._keys[index]
            if entry['id'] in self._limited:
                continue
            self._cursor = (index + 1) % total
            return entry
        raise NoAvailableKey()

    def mark_rate_limited(self, key_id):
        """把某把 Key 标记为今日超限。"""
        self._limited.add(key_id)

    def rate_limited_ids(self):
        return set(self._limited)

    def available_count(self):
        return len([k for k in self._keys if k['id'] not in self._limited])

    def total_count(self):
        return len(self._keys)

    def reset_limits(self):
        """清空超限标记（换天或管理员手动重置时用）。"""
        self._limited.clear()
