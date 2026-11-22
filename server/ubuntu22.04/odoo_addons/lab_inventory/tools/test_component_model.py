# -*- coding: utf-8 -*-
"""按器件类型归类参数（纯逻辑，不需要 Odoo）。

借鉴 kitspace/electro-grammar 的思路：先判定器件类型，再按类型取对应字段。
好处是同一概念的不同写法（容值/容量/电容量）自动归到一起，不用维护别名表。

真实数据里的参数名（生产库 148 个器件抽样）：
    工作温度 148、精度 107、温度系数 95、工作电压 81、额定电压 73、
    功率 53、容值 53、电阻类型 48、阻值 48、耗散功率(Pd) 27 …
"""
import importlib.util
import os
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.abspath(os.path.join(_HERE, 'component_model.py'))
_spec = importlib.util.spec_from_file_location('component_model_test', _SRC)
_model = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_model)


def params(**kwargs):
    return [{'name': k, 'value': v} for k, v in kwargs.items()]


class ClassifyTest(unittest.TestCase):

    def test_resistor_by_value_name(self):
        self.assertEqual(
            _model.classify(params(阻值='10kΩ', 精度='±1%')), 'resistor')

    def test_capacitor_by_value_name(self):
        self.assertEqual(
            _model.classify(params(容值='100nF', 耐压='50V')), 'capacitor')

    def test_capacitor_alt_name(self):
        """电容量/容量 也是电容。"""
        self.assertEqual(_model.classify(params(电容量='10uF')), 'capacitor')
        self.assertEqual(_model.classify(params(容量='10uF')), 'capacitor')

    def test_inductor(self):
        self.assertEqual(_model.classify(params(电感值='10uH')), 'inductor')

    def test_unknown_falls_back_to_other(self):
        self.assertEqual(_model.classify(params(颜色='红色')), 'other')

    def test_empty_is_other(self):
        self.assertEqual(_model.classify([]), 'other')
        self.assertEqual(_model.classify(None), 'other')


class FieldMapTest(unittest.TestCase):

    def test_resistor_fields(self):
        m = _model.field_map(params(阻值='10kΩ', 精度='±1%', 功率='100mW'))
        self.assertEqual(m['value'], ('阻值', '10kΩ'))
        self.assertEqual(m['tolerance'], ('精度', '±1%'))
        self.assertEqual(m['power'], ('功率', '100mW'))

    def test_power_rating_with_parens(self):
        """`耗散功率(Pd)` 这种带括号的写法要能认出来。"""
        m = _model.field_map([
            {'name': '阻值', 'value': '10kΩ'},
            {'name': '耗散功率(Pd)', 'value': '100mW'},
        ])
        self.assertEqual(m['power'], ('耗散功率(Pd)', '100mW'))

    def test_capacitor_fields(self):
        m = _model.field_map(params(容值='100nF', 耐压='50V', 介质='X7R'))
        self.assertEqual(m['value'], ('容值', '100nF'))
        self.assertEqual(m['voltage'], ('耐压', '50V'))
        self.assertEqual(m['dielectric'], ('介质', 'X7R'))

    def test_voltage_prefers_withstand_rating(self):
        """耐压 优先于 工作电压/额定电压：等效判定里它们语义不同。"""
        m = _model.field_map(params(容值='100nF', 耐压='50V', 工作电压='25V'))
        self.assertEqual(m['voltage'], ('耐压', '50V'))

    def test_operating_voltage_kept_separately(self):
        m = _model.field_map(params(容值='100nF', 工作电压='1.71V~3.63V'))
        self.assertEqual(m['operating_voltage'], ('工作电压', '1.71V~3.63V'))
        self.assertIsNone(m.get('voltage'))

    def test_missing_fields_are_absent(self):
        m = _model.field_map(params(阻值='10kΩ'))
        self.assertNotIn('tolerance', m)
        self.assertNotIn('power', m)


class ValueOfTest(unittest.TestCase):

    def test_value_of_returns_raw_value(self):
        self.assertEqual(_model.value_of(params(阻值='10kΩ'), 'value'), '10kΩ')

    def test_value_of_missing_returns_none(self):
        self.assertIsNone(_model.value_of(params(阻值='10kΩ'), 'power'))


class TypeFieldsTest(unittest.TestCase):

    def test_resistor_has_no_dielectric(self):
        self.assertNotIn('dielectric', _model.TYPE_FIELDS['resistor'])

    def test_capacitor_has_dielectric(self):
        self.assertIn('dielectric', _model.TYPE_FIELDS['capacitor'])


if __name__ == '__main__':
    unittest.main()
