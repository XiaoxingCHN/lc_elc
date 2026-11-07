# -*- coding: utf-8 -*-
"""Pure regression tests for normalized parameter keyword search.

These tests need no Odoo database and no network.  They load the shared helper
directly so both the Odoo test runner and ``python -m unittest`` can run them.
"""
import importlib.util
import os
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.abspath(os.path.join(
    _HERE, '..', '..', 'lab_inventory', 'tools', 'param_search.py'))
_spec = importlib.util.spec_from_file_location('lc_param_search_test', _SRC)
_param = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_param)


class ParamSearchTest(unittest.TestCase):

    def test_resistance_notation_aliases(self):
        cases = {
            '10kΩ': ('10k', '10000', '10kΩ'),
            '10Ω': ('10R', '10ohm', '10'),
            '4.7Ω': ('4R7', '4.7Ω'),
            '0.1Ω': ('R1', '0R1', '100mΩ'),
            '4.7kΩ': ('4k7', '4.7k', '4700'),
            '1.5kΩ': ('1k5', '1.5k', '1500'),
            '200mΩ': ('R2', '0.2Ω', '0.2'),
        }
        for value, expected in cases.items():
            aliases = set(_param.normalize_value('阻值', value))
            for token in expected:
                self.assertIn(token, aliases, '%s should alias %s' % (value, token))

    def test_search_aliases_are_symmetric(self):
        for left, right in (('10Ω', '10R'), ('4.7Ω', '4R7'), ('0.1Ω', 'R1'),
                            ('4.7kΩ', '4k7'), ('1.5kΩ', '1k5')):
            left_aliases = set(_param.normalize_value('阻值', left))
            right_aliases = set(_param.normalize_value('阻值', right))
            self.assertIn(right, left_aliases,
                          '%s should alias %s' % (left, right))
            self.assertIn(left, right_aliases,
                          '%s should alias %s' % (right, left))

    def test_capacitance_equivalence(self):
        self.assertIn('0.1uF', _param.normalize_value('容值', '100nF'))
        self.assertIn('100nF', _param.normalize_value('容值', '0.1uF'))
        self.assertIn('0.47nF', _param.normalize_value('容值', '470pF'))
        self.assertIn('1000pF', _param.normalize_value('容值', '1nF'))
        self.assertIn('0.1μF', _param.normalize_value('容值', '100nF'))
        self.assertEqual(_param.normalize_value('容值', '100'), ['100'])

    def test_tolerance_and_voltage(self):
        self.assertIn('1%', _param.normalize_value('精度', '±1%'))
        self.assertIn('±1%', _param.normalize_value('精度', '1%'))
        range_aliases = _param.normalize_value('精度', '-20%~+80%')
        self.assertIn('-20%~+80%', range_aliases)
        self.assertFalse(any('±-' in text for text in range_aliases))
        self.assertIn('1000V', _param.normalize_value('额定电压', '1kV'))
        self.assertIn('1kV', _param.normalize_value('额定电压', '1000V'))

    def test_degree_celsius_keeps_raw_and_nfkc_forms(self):
        text = _param.build_search_params([{'name': '精度', 'value': '±2℃'}])
        self.assertIn('±2℃', text)
        self.assertIn('±2°C', text)

    def test_key_parameter_selection(self):
        resistor = [
            {'name': '温度系数', 'value': '±100ppm/℃'},
            {'name': '阻值', 'value': '10kΩ'},
            {'name': '精度', 'value': '±1%'},
            {'name': '功率', 'value': '0.25W'},
        ]
        self.assertEqual([p['name'] for p in _param.key_parameter_dicts(resistor)],
                         ['阻值', '精度', '功率'])
        capacitor = [
            {'name': '容值', 'value': '100nF'},
            {'name': '耐压', 'value': '50V'},
            {'name': '介质', 'value': 'X7R'},
            {'name': '工作温度', 'value': '-55~125℃'},
        ]
        self.assertEqual([p['name'] for p in _param.key_parameter_dicts(capacitor)],
                         ['容值', '耐压', '介质'])
        other = [{'name': 'a', 'value': '1'}, {'name': 'b', 'value': '2'},
                 {'name': 'c', 'value': '3'}, {'name': 'd', 'value': '4'}]
        self.assertEqual([p['name'] for p in _param.key_parameter_dicts(other)],
                         ['a', 'b', 'c'])

    def test_build_search_specs_json_shapes(self):
        self.assertIn('4R7', _param.build_search_specs('{"阻值":"4R7"}'))
        self.assertIn('100nF', _param.build_search_specs(
            '[{"name":"容值","value":"100nF"}]'))
        self.assertIn('10kΩ', _param.build_search_specs('not-json 10kΩ'))

    def test_search_tokens_whitespace_and_nfkc(self):
        self.assertEqual(_param.search_tokens('  10k   1%  '), ['10k', '1%'])
        self.assertEqual(_param.search_tokens(''), [])
        self.assertEqual(_param.search_tokens('±2℃'), ['±2°C'])


if __name__ == '__main__':
    unittest.main()
