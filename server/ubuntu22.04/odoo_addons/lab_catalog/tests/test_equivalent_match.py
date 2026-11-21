# -*- coding: utf-8 -*-
"""纯逻辑回归：等效件参数比对。不需要 Odoo、不需要数据库。"""
import importlib.util
import os
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.abspath(os.path.join(
    _HERE, '..', '..', 'lab_inventory', 'tools', 'equivalent_match.py'))
_spec = importlib.util.spec_from_file_location('lc_equivalent_match_test', _SRC)
_match = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_match)


def _params(**kwargs):
    return [{'name': name, 'value': value} for name, value in kwargs.items()]


class EquivalentMatchTest(unittest.TestCase):

    def test_identical_specs_are_strong(self):
        source = _params(容值='0.1uF', 耐压='50V', 介质='X7R')
        candidate = _params(容值='100nF', 耐压='50V', 介质='X7R')
        result = _match.compare(source, candidate)
        self.assertEqual(result['conflicts'], [])
        self.assertEqual(_match.confidence(result), 'strong')
        self.assertIn('容值', [entry['name'] for entry in result['matched']])

    def test_lower_voltage_is_hard_conflict(self):
        source = _params(容值='0.1uF', 耐压='50V')
        candidate = _params(容值='0.1uF', 耐压='25V')
        result = _match.compare(source, candidate)
        self.assertTrue(result['hard'])
        self.assertIsNone(_match.confidence(result))

    def test_higher_voltage_is_fine(self):
        source = _params(容值='0.1uF', 耐压='50V')
        candidate = _params(容值='0.1uF', 耐压='100V')
        result = _match.compare(source, candidate)
        self.assertFalse(result['hard'])
        self.assertEqual(_match.confidence(result), 'strong')

    def test_different_capacitance_is_hard_conflict(self):
        source = _params(容值='0.1uF', 耐压='50V')
        candidate = _params(容值='1uF', 耐压='50V')
        self.assertIsNone(_match.confidence(_match.compare(source, candidate)))

    def test_different_tolerance_is_weak_not_dropped(self):
        source = _params(阻值='10kΩ', 精度='±1%')
        candidate = _params(阻值='10kΩ', 精度='±5%')
        result = _match.compare(source, candidate)
        self.assertFalse(result['hard'])
        self.assertEqual(_match.confidence(result), 'weak')

    def test_missing_candidate_parameter_is_not_matched(self):
        source = _params(容值='0.1uF', 耐压='50V')
        candidate = _params(容值='0.1uF')
        result = _match.compare(source, candidate)
        self.assertNotIn('耐压', [entry['name'] for entry in result['matched']])
        self.assertNotIn('耐压', [entry['name'] for entry in result['conflicts']])
        self.assertEqual(_match.confidence(result), 'strong')

    def test_no_comparable_parameters_returns_none(self):
        result = _match.compare(_params(颜色='黑'), _params(颜色='黑'))
        self.assertEqual(result['compared'], 0)
        self.assertIsNone(_match.confidence(result))

    def test_resistor_power_below_requirement_is_hard(self):
        source = _params(阻值='10kΩ', 功率='0.25W')
        candidate = _params(阻值='10kΩ', 功率='0.1W')
        self.assertIsNone(_match.confidence(_match.compare(source, candidate)))

    def test_resistor_power_above_requirement_is_fine(self):
        source = _params(阻值='10kΩ', 功率='0.25W')
        candidate = _params(阻值='10kΩ', 功率='0.5W')
        self.assertEqual(_match.confidence(_match.compare(source, candidate)), 'strong')

    def test_parse_si_handles_common_forms(self):
        self.assertAlmostEqual(_match.parse_si('50V'), 50.0)
        self.assertAlmostEqual(_match.parse_si('1kV'), 1000.0)
        self.assertAlmostEqual(_match.parse_si('0.1uF'), 1e-7)
        self.assertAlmostEqual(_match.parse_si('100nF'), 1e-7)
        self.assertAlmostEqual(_match.parse_si('0.25W'), 0.25)
        self.assertIsNone(_match.parse_si('X7R'))
        self.assertIsNone(_match.parse_si(''))

    def test_different_capacitance_with_tolerance_suffix_is_hard(self):
        """带 ±10% 后缀的容值解析不出数值，但仍然是硬冲突。

        LCSC 的真实写法常是 ``0.1uF ±10%``；解析失败不能退化成「文本不同但
        无伤大雅」——一个 0.1uF 的需求绝不能接受 1uF 的候选。
        """
        source = _params(容值='0.1uF ±10%')
        candidate = _params(容值='1uF ±10%')
        self.assertIsNone(_match.confidence(_match.compare(source, candidate)))

    def test_same_capacitance_with_tolerance_suffix_is_matched(self):
        source = _params(容值='0.1uF ±10%')
        candidate = _params(容值='0.1uF ±10%')
        result = _match.compare(source, candidate)
        self.assertFalse(result['hard'])
        self.assertEqual(_match.confidence(result), 'strong')

    def test_compound_capacitance_compares_by_its_primary_value(self):
        """``10uF/16V`` 的主值是 10uF；耐压部分不是容值。"""
        source = _params(容值='10uF/16V')
        candidate = _params(容值='10uF')
        result = _match.compare(source, candidate)
        self.assertFalse(result['hard'])
        self.assertEqual(_match.confidence(result), 'strong')

    def test_different_resistance_with_tolerance_suffix_is_hard(self):
        self.assertIsNone(_match.confidence(_match.compare(
            _params(阻值='10kΩ ±1%'), _params(阻值='1kΩ ±1%'))))

    def test_voltage_range_value_still_compares(self):
        source = _params(耐压='1.71V~3.63V')
        candidate = _params(耐压='1.71V~3.63V')
        self.assertEqual(_match.confidence(_match.compare(source, candidate)), 'strong')

    def test_percent_only_value_is_never_parsed_as_a_number(self):
        """``±1%`` 不是容值/阻值/耐压，不能被当成数值比对。"""
        self.assertIsNone(_match.parse_si('±1%'))
        self.assertIsNone(_match.parse_si('-20%~+80%'))
        self.assertIsNone(_match.parse_si('X7R'))

    def test_operating_voltage_range_must_cover_the_requirement(self):
        """工作电压是**区间**：候选必须完整覆盖需求区间。

        只看下限会让 ``2.0V~2.5V`` 冒充 ``1.71V~3.63V`` 的等效件——上界
        2.5V 低于需求的 3.63V，实际会烧器件。
        """
        need = _params(工作电压='1.71V~3.63V')
        self.assertIsNone(_match.confidence(_match.compare(
            need, _params(工作电压='2.0V~2.5V'))))          # 上界不够
        self.assertIsNone(_match.confidence(_match.compare(
            need, _params(工作电压='1.2V~3.3V'))))          # 下界不够
        covered = _match.compare(need, _params(工作电压='1.5V~5.0V'))
        self.assertEqual(_match.confidence(covered), 'strong')   # 完整覆盖

    def test_withstand_voltage_only_needs_to_be_high_enough(self):
        """耐压是**单值上限**：只要不低于需求就行，越高越好。"""
        need = _params(耐压='50V')
        self.assertEqual(_match.confidence(_match.compare(need, _params(耐压='100V'))), 'strong')
        self.assertIsNone(_match.confidence(_match.compare(need, _params(耐压='25V'))))

    def test_range_separators_cover_dash_and_tilde(self):
        self.assertEqual(_match.parse_range('1.71V~3.63V'), (1.71, 3.63))
        self.assertEqual(_match.parse_range('1.8V-5.5V'), (1.8, 5.5))
        self.assertEqual(_match.parse_range('1.8V–5.5V'), (1.8, 5.5))

    def test_leading_minus_is_a_sign_not_a_separator(self):
        """``-55~125℃`` 的第一个 ``-`` 是负号，不能被当成区间分隔。"""
        self.assertEqual(_match.parse_range('-55~125℃'), (None, None))
        self.assertEqual(_match.parse_range('-20%~+80%'), (None, None))

    def test_equivalent_spellings_compare_equal(self):
        source = _params(阻值='4.7kΩ')
        candidate = _params(阻值='4700Ω')
        self.assertEqual(_match.confidence(_match.compare(source, candidate)), 'strong')


if __name__ == '__main__':
    unittest.main()
