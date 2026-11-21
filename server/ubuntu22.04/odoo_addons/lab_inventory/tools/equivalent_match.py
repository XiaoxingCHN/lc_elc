# -*- coding: utf-8 -*-
"""等效件参数比对：纯逻辑，不依赖 Odoo，可离线测试。

规则来自 ``plugins/jlc-eda/REQUIREMENTS.md`` S5 与
``maintenance/tasks/2026-11-20-eda-persist-login-and-equivalents-design.md`` §4.2。

判定分三档：

* ``strong`` —— 关键参数全部一致；
* ``weak``   —— 有差异但差异项不是致命的（精度/介质等）；
* 丢弃        —— 硬冲突：容值/阻值不同，耐压/功率低于需求，
                或工作电压区间覆盖不了需求区间。

**绝不猜**：参数缺失一律不算一致，只算「未比对」。
"""
import re

# 关键参数分组。名字匹配用子串，因为立创的参数名有「容值」「电容量」等多种写法。
_IDENTITY_KEYS = ('容值', '容量', '电容量', '阻值')
_TOLERANCE_KEYS = ('精度',)
_DIELECTRIC_KEYS = ('介质', '材质')
# 「耐压 / 额定电压」是单值上限：越高越好。
_VOLTAGE_KEYS = ('耐压', '额定电压')
# 「工作电压」是区间：候选必须完整覆盖需求区间，否则会烧器件。
# 两者不能共用一条规则——只看下限会让 2.0V~2.5V 冒充 1.71V~3.63V。
_OPERATING_VOLTAGE_KEYS = ('工作电压',)
_POWER_KEYS = ('功率',)

# 这些分组一旦冲突就直接丢弃候选（S5 规则 4：不能判定为等效的不猜）。
_HARD_GROUPS = (_IDENTITY_KEYS, _VOLTAGE_KEYS, _OPERATING_VOLTAGE_KEYS,
                _POWER_KEYS)

_SI = {
    'p': 1e-12, 'n': 1e-9, 'u': 1e-6, 'µ': 1e-6, 'μ': 1e-6,
    'm': 1e-3, 'k': 1e3, 'K': 1e3, 'M': 1e6, 'G': 1e9,
}

# 主值：字符串开头的「数字 + 可选 SI 前缀 + 可选单位」，后面允许跟任何
# 后缀（±10%、/16V、~3.63V、@100kHz …）。不带 ``$`` 锚点，正是为了容忍
# 立创那些复合写法。
_MAIN_VALUE = re.compile(r'^([0-9]+(?:\.[0-9]+)?)\s*([pnuµμmkKMG]?)\s*[A-Za-zΩ]*')


def _clean(value):
    return ' '.join(str(value or '').split())


def parse_si(value):
    """把 ``50V`` / ``0.25W`` / ``4.7uF`` 解析成基础单位数值；解析不了返回 None。

    立创的真实写法常常带后缀或是复合值（``0.1uF ±10%``、``10uF/16V``、
    ``1.71V~3.63V``）。这里只取**主值**：第一个数字+前缀，其后必须是单位或
    分隔符。取不到主值就返回 None，由调用方按「未比对」处理——
    绝不把解析失败当成「相等」或「无害差异」。
    """
    text = _clean(value).replace(' ', '')
    if not text:
        return None
    match = _MAIN_VALUE.match(text)
    if not match:
        return None
    try:
        base = float(match.group(1))
    except ValueError:
        return None
    prefix = match.group(2) or ''
    return base * _SI.get(prefix, 1.0)


# 区间分隔符：``~``/``～`` 总是分隔符；``-``/``–``/``—`` 只有在**不是**前导
# 负号时才是分隔符（``-55~125℃`` 里的第一个 ``-`` 是符号，不是分隔）。
_RANGE_SPLIT = re.compile(r'(?:~|～|–|—|\bto\b)|(?<=[0-9A-Za-zΩµμ])-')


def parse_range(value):
    """解析 ``1.71V~3.63V`` / ``1.8V-5.5V`` 这类区间；单值 ``50V`` 返回 ``(None, 50.0)``。

    返回 ``(low, high)``，取不到的端点用 ``None``。完全解析不出主值返回
    ``(None, None)``。
    """
    text = _clean(value).replace(' ', '')
    if not text:
        return (None, None)
    parts = [part for part in _RANGE_SPLIT.split(text) if part]
    if len(parts) >= 2:
        low = parse_si(parts[0])
        high = parse_si(parts[1])
        if low is not None and high is not None:
            return (min(low, high), max(low, high))
        return (None, None)
    single = parse_si(text)
    if single is None:
        return (None, None)
    return (None, single)


def _names(params):
    return [str(entry.get('name') or '') for entry in params or []]


def _value_of(params, keys):
    """返回第一个名字命中 keys 的参数值（原始字符串）。"""
    for entry in params or []:
        name = str(entry.get('name') or '')
        if any(key in name for key in keys):
            value = entry.get('value')
            if value is None:
                continue
            text = _clean(value)
            if text:
                return text
    return None


def _same_text(left, right):
    """文本相等，忽略大小写与空格。"""
    return _clean(left).lower().replace(' ', '') == _clean(right).lower().replace(' ', '')


def compare(source_params, candidate_params):
    """比对两组参数。

    :param source_params: 源器件参数 ``[{'name','value'}]``
    :param candidate_params: 候选器件参数，同形
    :return: ``{'matched': [...], 'conflicts': [...], 'hard': bool, 'compared': int}``
        ``matched``/``conflicts`` 每项为 ``{'name','source','candidate'}``。
        ``compared`` 是实际比对过的关键参数个数；为 0 表示无从判定。
    """
    matched = []
    conflicts = []
    hard = False
    compared = 0

    groups = (
        (_IDENTITY_KEYS, True),
        (_TOLERANCE_KEYS, False),
        (_DIELECTRIC_KEYS, False),
        (_VOLTAGE_KEYS, True),
        (_OPERATING_VOLTAGE_KEYS, True),
        (_POWER_KEYS, True),
    )

    for keys, is_hard_group in groups:
        source_value = _value_of(source_params, keys)
        if source_value is None:
            continue
        candidate_value = _value_of(candidate_params, keys)
        if candidate_value is None:
            # 候选缺这个参数：不算一致，也不算冲突（「未比对」）。
            continue
        compared += 1
        name = next(n for n in _names(source_params)
                    if any(key in n for key in keys))

        if keys is _OPERATING_VOLTAGE_KEYS:
            # 区间必须完整覆盖：候选下限 <= 需求下限，候选上限 >= 需求上限。
            need_low, need_high = parse_range(source_value)
            have_low, have_high = parse_range(candidate_value)
            if need_low is not None and need_high is not None \
                    and have_low is not None and have_high is not None:
                if have_low <= need_low + 1e-9 and have_high + 1e-9 >= need_high:
                    matched.append({'name': name, 'value': candidate_value})
                else:
                    conflicts.append({'name': name, 'source': source_value,
                                      'candidate': candidate_value})
                    hard = True
                continue
        elif keys is _VOLTAGE_KEYS or keys is _POWER_KEYS:
            left = parse_si(source_value)
            right = parse_si(candidate_value)
            if left is not None and right is not None:
                if right >= left:
                    matched.append({'name': name, 'value': candidate_value})
                else:
                    conflicts.append({'name': name, 'source': source_value,
                                      'candidate': candidate_value})
                    hard = True
                continue
        elif keys is _IDENTITY_KEYS:
            # 容值/阻值可能写成 0.1uF vs 100nF，比较数值而非文本。
            left = parse_si(source_value)
            right = parse_si(candidate_value)
            if left is not None and right is not None and left > 0:
                if abs(right - left) / left < 1e-6:
                    matched.append({'name': name, 'value': candidate_value})
                else:
                    conflicts.append({'name': name, 'source': source_value,
                                      'candidate': candidate_value})
                    hard = True
                continue

        if _same_text(source_value, candidate_value):
            matched.append({'name': name, 'value': candidate_value})
        else:
            conflicts.append({'name': name, 'source': source_value,
                              'candidate': candidate_value})
            # ``is_hard_group`` 来自分组定义本身，不是「元组是否在元组里」——
            # 后者永远为 False，会让一个 1uF 的候选冒充 0.1uF 的等效件。
            if is_hard_group:
                hard = True

    return {'matched': matched, 'conflicts': conflicts,
            'hard': hard, 'compared': compared}


def confidence(result):
    """把 ``compare()`` 的结果映射成 ``strong`` / ``weak`` / ``None``（丢弃）。"""
    if result['hard']:
        return None
    if result['compared'] == 0:
        return None
    if result['conflicts']:
        return 'weak'
    return 'strong'
