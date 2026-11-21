# -*- coding: utf-8 -*-
"""EDA API Token 的纯逻辑：生成、哈希、比对、有效期判定。

不依赖 Odoo，可离线测试。Odoo 模型 ``lab.eda.token`` 只负责持久化与权限。

设计要点（见 ``maintenance/tasks/2026-11-21-eda-api-token-design.md`` §3）：

* 明文 token **只在发放时出现一次**，库里只存 sha256 哈希；
* 比对用 ``hmac.compare_digest``，避免时序侧信道；
* 过期边界是「到点即失效」，不留一秒窗口；
* ``days=0`` 表示永不过期（管理员显式选择）。
"""
import hashlib
import hmac
import secrets

PREFIX = 'eda_'
# token_urlsafe(32) 产生 43 个字符的 base64url 串
TOKEN_BYTES = 32
DEFAULT_VALIDITY_DAYS = 365


def generate():
    """生成一个新的明文 token。调用方负责只显示一次、随后丢弃。"""
    return PREFIX + secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token):
    """返回 sha256 十六进制摘要；空值返回空串（调用方应视为无效）。"""
    text = str(token or '').strip()
    if not text:
        return ''
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def matches(token, stored_hash):
    """恒定时间比对。存储哈希格式不对时直接 False，不抛异常。"""
    text = str(token or '').strip()
    stored = str(stored_hash or '').strip()
    if not text or not stored:
        return False
    if len(stored) != 64:
        return False
    try:
        int(stored, 16)
    except ValueError:
        return False
    return hmac.compare_digest(hash_token(text), stored)


def is_valid(active, expires_at, now):
    """``active`` 且未过期才算有效。

    :param active: 吊销开关
    :param expires_at: epoch 秒，``None`` 表示永不过期
    :param now: 当前 epoch 秒
    """
    if not active:
        return False
    if expires_at is None:
        return True
    return now < expires_at


def expiry_from_days(days, now):
    """把「有效天数」换算成 epoch 秒。``days=0`` 返回 ``None``（永不过期）。"""
    days = int(days)
    if days < 0:
        raise ValueError('有效期不能为负数')
    if days == 0:
        return None
    return float(now) + days * 86400.0
