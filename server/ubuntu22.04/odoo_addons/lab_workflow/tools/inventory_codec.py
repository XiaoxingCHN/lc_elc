# -*- coding: utf-8 -*-
"""追溯码 / 库码 / SN / 立创物料袋二维码 的规范化与解析。

本模块是**纯逻辑**实现：不 import odoo，也不依赖数据库，可以在离线环境单独测试。

约定（与 lc_elc/docs/business_api_contract.json 一致）：

* 袋追溯码      ``LABB:<trace-code>``    扫码后按袋定位库存
* 库位库码      ``LABL:<location-code>`` 扫码后按库位定位
* 物料 SN       ``LAB-000001``           扫码后按物料定位
* 立创商城编号  ``C123456``              扫码后按目录器件定位
* 立创原厂袋二维码 ``{on:SO...,pc:C225521,pm:...,qty:5,...}``

原立创袋二维码解析复用了部署包内既有算法 ``linux_serve/tools/jlc_qr.py``
（通过 ``LAB_WORKFLOW_JLC_QR_PATH`` 环境变量或默认相对路径加载），
**不修改原文件**；加载失败时使用本文件内的等价实现兜底。
"""

import importlib.util
import json
import os
import re
import unicodedata

__all__ = [
    'normalize_lcsc_code',
    'is_lcsc_code',
    'normalize_sn',
    'normalize_trace_code',
    'normalize_location_code',
    'parse_jlc_bag_text',
    'is_jlc_bag_text',
    'build_bag_payload',
    'build_location_payload',
    'classify_scan',
    'KIND_BAG',
    'KIND_LOCATION',
    'KIND_SN',
    'KIND_LCSC',
    'KIND_JLC',
    'KIND_UNKNOWN',
]

KIND_BAG = 'bag'
KIND_LOCATION = 'location'
KIND_SN = 'sn'
KIND_LCSC = 'lcsc'
KIND_JLC = 'jlc'
KIND_UNKNOWN = 'unknown'

BAG_PREFIX = 'LABB'
LOCATION_PREFIX = 'LABL'

# 追溯码正文：大写字母/数字/连字符，长度 4~40（去掉 1~3 位前缀后至少 4 位）
_TRACE_BODY_RE = re.compile(r'^[A-Z0-9][A-Z0-9\-]{2,39}$')
# 库码正文：与 lab.stock.location.code 生成规则一致
_LOCATION_BODY_RE = re.compile(r'^[A-Z0-9][A-Z0-9\-]{1,23}$')
# 物料 SN：LAB-000001 / LAB-XXXXXXXX
_SN_RE = re.compile(r'^[A-Z][A-Z0-9]{1,11}-[A-Z0-9][A-Z0-9\-]{2,29}$')
# 立创 C 码：C + 正十进制数字（不要求 4 位以上）
_LCSC_RE = re.compile(r'^C[0-9]+$')

_JLC_QR_CACHE = []
_NULLS = {'null', 'none', 'nil', '~', ''}
_JLC_INT_FIELDS = {'qty', 'cc', 'pdi', 'hp'}


# --------------------------------------------------------------------------
# 基础规范化
# --------------------------------------------------------------------------
def _fold(text):
    """NFKC 折叠 + 去首尾空白（全角字母/数字会被折叠为半角）。"""
    if text is None:
        return ''
    text = unicodedata.normalize('NFKC', str(text))
    return text.strip()


def normalize_lcsc_code(value):
    """把任意写法规范为 ``C123``；非法返回 None。

    注意：需求明确「C 后跟正十进制数字即可，不要求 4 位以上」，
    因此 ``C1`` 合法，``C`` / ``C01x`` / 空值 非法。
    """
    text = _fold(value).upper()
    if not text:
        return None
    text = text.replace(' ', '')
    if not text.startswith('C'):
        candidate = 'C' + text.lstrip('C')
    else:
        candidate = text
    # 去掉前导零（C007 -> C7），保持同一物料只有一个规范化身份
    match = re.fullmatch(r'C0*([0-9]+)', candidate)
    if not match:
        return None
    number = match.group(1)
    if not number:
        return None
    return 'C' + number


is_lcsc_code = lambda value: normalize_lcsc_code(value) is not None  # noqa: E731


def normalize_sn(value):
    """物料 SN 规范化：去空白、转大写；非法返回 None。"""
    text = _fold(value).upper().replace(' ', '')
    if not text:
        return None
    if _SN_RE.match(text):
        return text
    return None


def normalize_trace_code(value):
    """袋追溯码正文规范化；非法返回 None。"""
    text = _fold(value).upper().replace(' ', '')
    if text.startswith(BAG_PREFIX + ':'):
        text = text[len(BAG_PREFIX) + 1:]
    if _TRACE_BODY_RE.match(text):
        return text
    return None


def normalize_location_code(value):
    """库码正文规范化；非法返回 None。"""
    text = _fold(value).upper().replace(' ', '')
    if text.startswith(LOCATION_PREFIX + ':'):
        text = text[len(LOCATION_PREFIX) + 1:]
    if _LOCATION_BODY_RE.match(text):
        return text
    return None


def build_bag_payload(trace_code):
    code = normalize_trace_code(trace_code)
    return '%s:%s' % (BAG_PREFIX, code) if code else None


def build_location_payload(location_code):
    code = normalize_location_code(location_code)
    return '%s:%s' % (LOCATION_PREFIX, code) if code else None


# --------------------------------------------------------------------------
# 立创原厂物料袋二维码
# --------------------------------------------------------------------------
def _jlc_qr_path_candidates():
    env = os.environ.get('LAB_WORKFLOW_JLC_QR_PATH')
    if env:
        yield env
    here = os.path.dirname(os.path.abspath(__file__))
    # .../odoo_addons/lab_workflow/tools -> 部署包根目录
    root = os.path.abspath(os.path.join(here, '..', '..', '..', '..', '..'))
    yield os.path.join(root, 'linux_serve', 'tools', 'jlc_qr.py')
    yield '/opt/lab/linux_serve/tools/jlc_qr.py'


def _load_reference_jlc_parser():
    """加载部署包内既有 jlc_qr.py（只读，不修改原文件）。"""
    if _JLC_QR_CACHE:
        return _JLC_QR_CACHE[0]
    for path in _jlc_qr_path_candidates():
        if not path or not os.path.isfile(path):
            continue
        try:
            spec = importlib.util.spec_from_file_location('lab_workflow_jlc_qr_ref', path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if callable(getattr(module, 'parse_jlc_qr', None)):
                _JLC_QR_CACHE.append(module)
                return module
        except Exception:  # noqa: BLE001 - 兜底解析器保证业务不中断
            continue
    _JLC_QR_CACHE.append(None)
    return None


def is_jlc_bag_text(raw):
    """粗略判断是否为立创原厂物料袋二维码文本。"""
    text = _fold(raw)
    if not text.startswith('{'):
        return False
    return bool(re.search(r'(^|[,{\s])pc\s*:', text)) and bool(
        re.search(r'(^|[,{\s])(on|pdi|pm)\s*:', text))


def _parse_jlc_fallback(raw):
    """与 linux_serve/tools/jlc_qr.py 等价的兜底解析（不覆盖原实现）。"""
    result = {'raw': raw, 'is_valid': False, 'source': 'fallback'}
    text = _fold(raw)
    if not text:
        result['error'] = '空输入'
        return result
    if text.startswith('{') and text.endswith('}'):
        text = text[1:-1]
    for part in text.split(','):
        if ':' not in part:
            continue
        key, _, value = part.partition(':')
        key = key.strip().strip('"\'')
        value = value.strip().strip('"\'')
        if not key:
            continue
        if value.lower() in _NULLS:
            result[key] = None
        elif key in _JLC_INT_FIELDS:
            try:
                result[key] = int(value)
            except ValueError:
                result[key] = value
        else:
            result[key] = value
    if 'pc' not in result:
        result['error'] = '缺少 pc 字段（立创编号）'
        return result
    result['lcsc_code'] = normalize_lcsc_code(result.get('pc'))
    result['is_valid'] = result['lcsc_code'] is not None
    if not result['is_valid']:
        result['error'] = 'pc 不是合法 C 码: %r' % (result.get('pc'),)
    return result


def parse_jlc_bag_text(raw):
    """解析立创原厂袋二维码文本，返回 dict（永不抛异常）。

    返回字段：raw / is_valid / lcsc_code / on / pm / qty / pdi / ... / source
    """
    module = _load_reference_jlc_parser()
    if module is not None:
        try:
            parsed = module.parse_jlc_qr(raw)
            if isinstance(parsed, dict):
                parsed = dict(parsed)
                parsed.setdefault('source', 'linux_serve/tools/jlc_qr.py')
                code = normalize_lcsc_code(parsed.get('lcsc_code') or parsed.get('pc'))
                parsed['lcsc_code'] = code
                parsed['is_valid'] = code is not None
                return parsed
        except Exception:  # noqa: BLE001 - 原算法异常时走兜底
            pass
    parsed = _parse_jlc_fallback(raw)
    parsed['source'] = 'lab_workflow fallback'
    return parsed


# --------------------------------------------------------------------------
# 统一扫码分流
# --------------------------------------------------------------------------
def classify_scan(raw):
    """把一段扫码文本分类。

    :returns: dict(kind=..., normalized=..., payload=..., jlc=...)
    """
    text = _fold(raw)
    result = {
        'raw': raw,
        'kind': KIND_UNKNOWN,
        'normalized': None,
        'payload': None,
        'jlc': None,
    }
    if not text:
        return result

    upper = text.upper()

    # 1) 本系统袋追溯码
    if upper.startswith(BAG_PREFIX + ':'):
        code = normalize_trace_code(upper)
        if code:
            result.update(kind=KIND_BAG, normalized=code, payload=build_bag_payload(code))
        return result

    # 2) 本系统库位库码
    if upper.startswith(LOCATION_PREFIX + ':'):
        code = normalize_location_code(upper)
        if code:
            result.update(kind=KIND_LOCATION, normalized=code,
                          payload=build_location_payload(code))
        return result

    # 3) 立创原厂物料袋二维码
    if is_jlc_bag_text(text):
        parsed = parse_jlc_bag_text(text)
        result['jlc'] = parsed
        code = parsed.get('lcsc_code')
        if code:
            result.update(kind=KIND_JLC, normalized=code, payload=code)
        return result

    # 4) 纯立创 C 码
    code = normalize_lcsc_code(upper)
    if code:
        result.update(kind=KIND_LCSC, normalized=code, payload=code)
        return result

    # 5) 物料 SN
    sn = normalize_sn(upper)
    if sn:
        result.update(kind=KIND_SN, normalized=sn, payload=sn)
        return result

    # 6) 用户可能只扫了追溯码正文或库码正文（无前缀）
    code = normalize_trace_code(upper)
    if code and not code.startswith('LAB-'):
        result.update(kind=KIND_BAG, normalized=code, payload=build_bag_payload(code))

    return result


def dumps(parsed):
    """调试用：稳定输出解析结果 JSON。"""
    return json.dumps(parsed, ensure_ascii=False, sort_keys=True, default=str)
