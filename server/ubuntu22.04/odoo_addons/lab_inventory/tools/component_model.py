# -*- coding: utf-8 -*-
"""按器件类型归类参数（纯逻辑，不依赖 Odoo）。

为什么要有这一层
----------------
立创的参数名不统一：同一个概念有 ``容值`` / ``容量`` / ``电容量`` 三种写法，
``耐压`` / ``额定电压`` / ``工作电压`` 三种，``功率`` / ``耗散功率(Pd)`` 两种。
以前靠 ``key_pairs`` 里的子串匹配 + 手写别名表，漏一个就静默丢参数。

这里借鉴 `kitspace/electro-grammar` 的做法：**先判定器件类型，再按类型取
字段**。类型一旦确定，字段就是有限的几个，不用维护别名表。

真实数据抽样（生产库 148 个器件）：
    工作温度 148、精度 107、温度系数 95、工作电压 81、额定电压 73、
    功率 53、容值 53、电阻类型 48、阻值 48、耗散功率(Pd) 27 …

与 ``param_search`` 的分工
--------------------------
* 本模块只管「这是什么器件、它有哪些关键字段」；
* ``param_search`` 管「这个字段的值怎么归一化成可比较的别名」。
两者都不 import odoo，可离线测试。
"""

# 字段 -> 可能的参数名（按优先级排列）。
# 用**完整名字**而不是子串：`耗散功率(Pd)` 含 `功率`，但 `功率` 不该反过来
# 匹配到 `耗散功率` 之外的无关字段。
FIELD_NAMES = {
    'value': ('阻值', '容值', '容量', '电容量', '电感值', '感值'),
    'tolerance': ('精度',),
    'dielectric': ('介质', '材质'),
    # 耐压是单值上限（越高越好）；工作电压是区间（必须覆盖需求）。
    # 两者语义不同，不能合并——见 lab_inventory/tools/equivalent_match.py。
    'voltage': ('耐压',),
    'rated_voltage': ('额定电压',),
    'operating_voltage': ('工作电压',),
    'power': ('功率', '耗散功率(Pd)', '耗散功率', '额定功率'),
}

# 每种器件关心哪些字段（顺序即展示/比对顺序）。
TYPE_FIELDS = {
    'resistor': ('value', 'tolerance', 'power'),
    'capacitor': ('value', 'tolerance', 'voltage', 'rated_voltage',
                  'operating_voltage', 'dielectric'),
    'inductor': ('value', 'tolerance', 'rated_voltage'),
    'other': (),
}

# 判定类型的依据：字段名 -> 类型。
_VALUE_TYPE = {
    '阻值': 'resistor',
    '容值': 'capacitor',
    '容量': 'capacitor',
    '电容量': 'capacitor',
    '电感值': 'inductor',
    '感值': 'inductor',
}


def _pairs(parameters):
    """把各种入参形状统一成 ``[(name, value), ...]``。"""
    out = []
    for entry in parameters or []:
        if isinstance(entry, dict):
            name = str(entry.get('name') or '')
            value = entry.get('value')
        elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
            name = str(entry[0] or '')
            value = entry[1]
        else:
            continue
        if name or value is not None:
            out.append((name, '' if value is None else str(value)))
    return out


def classify(parameters):
    """判定器件类型：``resistor`` / ``capacitor`` / ``inductor`` / ``other``。

    只看「值」类字段的名字——阻值就是电阻，容值就是电容。这比看名称里
    有没有「电阻」二字可靠，因为很多器件名称是型号不是描述。
    """
    for name, _value in _pairs(parameters):
        kind = _VALUE_TYPE.get(name)
        if kind:
            return kind
    return 'other'


def field_map(parameters):
    """返回 ``{字段: (原始参数名, 原始值)}``，只包含**存在**的字段。

    同一个字段有多个候选名时按 :data:`FIELD_NAMES` 的顺序取第一个命中的。
    """
    pairs = _pairs(parameters)
    by_name = {}
    for name, value in pairs:
        # 同名只保留第一个，避免重复行覆盖
        by_name.setdefault(name, value)
    result = {}
    for field, names in FIELD_NAMES.items():
        for name in names:
            if name in by_name:
                result[field] = (name, by_name[name])
                break
    return result


def value_of(parameters, field):
    """取某个字段的原始值；不存在返回 ``None``。"""
    entry = field_map(parameters).get(field)
    return entry[1] if entry else None
