# -*- coding: utf-8 -*-
"""幂等请求键与 payload 指纹（纯逻辑，可离线单测）。

规则（lc_elc/docs/business_api_contract.json）：

* ``request_key`` 必填，长度 8~128，合法字符 ``A-Za-z0-9._:-``
* 同一 ``request_key`` + 用户 + 公司只能成功记账一次
* 同 key 但 payload 指纹不同 => 拒绝（CONFLICT），不能静默返回旧结果
* 指纹计算必须稳定：字典键排序、浮点按 UoM 精度量化、忽略网络层噪声字段
"""

import hashlib
import json
import math
import re
from decimal import Decimal, ROUND_HALF_UP

__all__ = [
    'REQUEST_KEY_RE',
    'is_valid_request_key',
    'normalize_request_key',
    'quantize_number',
    'canonicalize',
    'fingerprint',
    'payload_diff_keys',
]

REQUEST_KEY_RE = re.compile(r'^[A-Za-z0-9._:\-]{8,128}$')

# 这些字段属于传输/展示层，不参与业务指纹
_IGNORED_KEYS = frozenset({
    'csrf_token', 'context', 'lang', 'tz', 'id', 'jsonrpc', 'method',
    'note', 'client_time', 'client_timezone',
})


def normalize_request_key(value):
    return (value or '').strip() if isinstance(value, str) else ''


def is_valid_request_key(value):
    return bool(REQUEST_KEY_RE.match(normalize_request_key(value)))


def quantize_number(value, digits=6):
    """把数值量化到固定小数位，避免 20 与 20.0 产生不同指纹。

    NaN / Infinity 不是合法 JSON 数值，量化会抛 InvalidOperation；
    非法数量**不能**在生成指纹时就崩掉（否则客户端只看到 500 而不是中文校验错误），
    所以在这里原样返回，交给 ``lab_check_quantity`` 去给出中文错误。
    """
    try:
        dec = Decimal(str(value))
        quant = Decimal(1).scaleb(-digits)
        dec = dec.quantize(quant, rounding=ROUND_HALF_UP)
    except Exception:  # noqa: BLE001 - 含 InvalidOperation / ValueError
        return value
    if dec == dec.to_integral_value():
        return int(dec)
    return float(dec)


def _canonical(value, depth=0):
    if depth > 12:
        return '<deep>'
    if isinstance(value, dict):
        return {
            str(key): _canonical(val, depth + 1)
            for key, val in sorted(value.items(), key=lambda kv: str(kv[0]))
            if str(key) not in _IGNORED_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_canonical(item, depth + 1) for item in value]
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        # NaN / Infinity 不是合法 JSON：PostgreSQL 会直接拒绝写入 jsonb，
        # 所以统一归一成 None（校验层 lab_check_quantity 仍会给出中文错误）。
        if math.isnan(value) or math.isinf(value):
            return None
        return quantize_number(value)
    if isinstance(value, str):
        return value.strip()
    return value


def canonicalize(params):
    """返回可用于比较/散列的规范化结构。"""
    return _canonical(params or {})


def canonical_json(params):
    return json.dumps(canonicalize(params), ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), default=str)


def fingerprint(params):
    """业务指纹：sha256(规范化 JSON) 的十六进制。"""
    return hashlib.sha256(canonical_json(params).encode('utf-8')).hexdigest()


def payload_diff_keys(left, right):
    """列出两个 payload 规范化后真正不同的顶层键（用于错误提示）。"""
    a = canonicalize(left)
    b = canonicalize(right)
    keys = sorted(set(a) | set(b))
    diff = []
    for key in keys:
        if a.get(key) != b.get(key):
            diff.append(key)
    return diff
