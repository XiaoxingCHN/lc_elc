# -*- coding: utf-8 -*-
"""Odoo integration tests for parameter keyword search.

These tests need a real Odoo database (``--test-enable``); the pure alias logic
is covered separately by ``test_param_search.py`` and can run without Odoo.
"""
from odoo.tests import TransactionCase, tagged


@tagged('at_install', '-post_install', 'lab_catalog')
class CatalogParamSearchTest(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Item = cls.env['lab.catalog.item']
        cls.Param = cls.env['lab.catalog.param']

    def _catalog_item(self, code, name='测试电阻', params=None, search_text=''):
        item = self.Item.create({
            'catalog_code': code,
            'name': name,
            'mpn': '%s-MPN' % code,
            'search_text': search_text or '%s %s' % (code, name),
            'param_count': len(params or []),
        })
        if params:
            self.Param.create([
                {'item_id': item.id, 'sequence': 10 + index, 'code': code_key,
                 'name': name_key, 'value': value}
                for index, (code_key, name_key, value) in enumerate(params)
            ])
        return item

    def _keys(self, query):
        items, _cursor, _total = self.Item.search_unified(query=query, limit=50)
        return [row['item_key'] for row in items]

    def test_param_hook_builds_search_text(self):
        item = self._catalog_item('C9100001', params=[
            ('resistance', '阻值', '10Ω'),
            ('tolerance', '精度', '±1%'),
            ('power', '功率', '0.1W'),
        ])
        item.invalidate_recordset()
        self.assertIn('10R', item.search_params)
        self.assertIn('±1%', item.search_params)

    def test_catalog_search_accepts_r_notation(self):
        item = self._catalog_item('C9100002', params=[('resistance', '阻值', '10Ω')])
        self.assertIn('lcsc:C9100002', self._keys('10R'))
        # The stored value still matches its original spelling.
        self.assertIn('lcsc:C9100002', self._keys('10Ω'))

    def test_catalog_search_normalizes_capacitance(self):
        self._catalog_item('C9100003', params=[('capacitance', '容值', '100nF')])
        self.assertIn('lcsc:C9100003', self._keys('0.1uF'))

    def test_r_notation_does_not_match_longer_values(self):
        ten = self._catalog_item('C9100008', params=[('resistance', '阻值', '10Ω')])
        hundred_ten = self._catalog_item('C9100009', params=[('resistance', '阻值', '110Ω')])
        keys = self._keys('10R')
        self.assertIn('lcsc:%s' % ten.catalog_code, keys)
        self.assertNotIn('lcsc:%s' % hundred_ten.catalog_code, keys)

    def test_compound_value_parts_are_searchable(self):
        voltage = self._catalog_item('C9100010', params=[
            ('voltage', '工作电压', '1.71V~3.63V'),
        ])
        compact = self._catalog_item('C9100011', params=[
            ('capacitance', '容值', '10uF/16V'),
        ])
        for query in ('1.71V', '3.63V'):
            self.assertIn('lcsc:%s' % voltage.catalog_code, self._keys(query))
        self.assertIn('lcsc:%s' % compact.catalog_code, self._keys('10uF'))
        # Still a token match: 63V is not a value on its own here.
        self.assertNotIn('lcsc:%s' % voltage.catalog_code, self._keys('63V'))

    def test_catalog_search_requires_every_token(self):
        complete = self._catalog_item('C9100004', params=[
            ('resistance', '阻值', '10Ω'),
            ('tolerance', '精度', '±1%'),
        ])
        resistance_only = self._catalog_item('C9100005', params=[
            ('resistance', '阻值', '10Ω'),
        ])
        keys = self._keys('10R 1%')
        self.assertIn('lcsc:%s' % complete.catalog_code, keys)
        self.assertNotIn('lcsc:%s' % resistance_only.catalog_code, keys)

    def test_local_archive_specs_are_searchable(self):
        template = self.env['product.template'].create({
            'name': '本地档案电容 100nF',
            'type': 'consu',
            'lab_specifications': '{"容值": "100nF", "耐压": "50V"}',
        })
        template.invalidate_recordset()
        self.assertIn('0.1uF', template.lab_search_specs)
        self.assertIn('lab:%d' % template.id, self._keys('0.1uF'))
        self.assertNotIn('lab:%d' % template.id, self._keys('0.1uF 100V'))

    def test_param_index_readiness_marker_and_null_scan(self):
        item = self._catalog_item('C9100006', params=[('resistance', '阻值', '10Ω')])
        param = self.env['ir.config_parameter'].sudo()
        param.set_param('lab_catalog.param_index_state', 'ready')
        self.assertTrue(self.Item.param_index_ready())

        param.set_param('lab_catalog.param_index_state', '')
        self.env.cr.execute(
            'UPDATE lab_catalog_item SET search_params = NULL WHERE id = %s',
            (item.id,))
        self.assertFalse(self.Item.param_index_ready())

    def test_binding_applies_catalog_facts_to_empty_template(self):
        item = self._catalog_item('C9100020', name='厚膜电阻 100kΩ ±5% 100mW', params=[
            ('resistance', '阻值', '100kΩ'),
            ('tolerance', '精度', '±5%'),
        ])
        item.write({'mpn': 'RC0603JR-07100KL', 'brand': 'YAGEO(国巨)', 'package': '0603'})
        template = self.env['product.template'].create({
            'name': '立创物料 C9100020（待补全）',
            'type': 'consu',
            'lab_lcsc_code': 'C9100020',
        })
        self.env['lab.catalog.binding'].create({
            'catalog_code': 'C9100020',
            'product_template_id': template.id,
        })
        template.invalidate_recordset()
        self.assertEqual(template.name, '厚膜电阻 100kΩ ±5% 100mW')
        self.assertEqual(template.lab_mpn, 'RC0603JR-07100KL')
        self.assertEqual(template.lab_brand, 'YAGEO(国巨)')
        self.assertEqual(template.lab_package, '0603')
        self.assertIn('100kΩ', template.lab_specifications or '')

    def test_binding_keeps_manual_values(self):
        item = self._catalog_item('C9100021', name='厚膜电阻 1kΩ ±1%', params=[])
        item.write({'brand': '资料库品牌', 'package': '0603'})
        template = self.env['product.template'].create({
            'name': '手填名称电阻',
            'type': 'consu',
            'lab_lcsc_code': 'C9100021',
            'lab_brand': '手填品牌',
        })
        self.env['lab.catalog.binding'].create({
            'catalog_code': 'C9100021',
            'product_template_id': template.id,
        })
        template.invalidate_recordset()
        self.assertEqual(template.name, '手填名称电阻')
        self.assertEqual(template.lab_brand, '手填品牌')
        self.assertEqual(template.lab_package, '0603')

    def test_param_removal_keeps_index_ready(self):
        item = self._catalog_item('C9100007', params=[
            ('resistance', '阻值', '10Ω'),
        ])
        param = self.env['ir.config_parameter'].sudo()
        param.set_param('lab_catalog.param_index_state', '')
        item.param_ids.unlink()
        item.invalidate_recordset()
        # Empty text is stored as a non-NULL sentinel, not mistaken for an
        # unprocessed row.
        self.assertIsNotNone(item.search_params)
        self.assertTrue(self.Item.param_index_ready())
