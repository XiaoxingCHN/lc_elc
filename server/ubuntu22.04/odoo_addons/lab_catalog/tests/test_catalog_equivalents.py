# -*- coding: utf-8 -*-
"""BOM 等效件检索（S5）的 ORM 测试。

规则来自 ``plugins/jlc-eda/REQUIREMENTS.md`` S5：

1. 主匹配永远是 C 编号；等效候选**单独一栏**，不混进主行。
2. 硬冲突（容值/阻值不同、耐压或功率低于需求）**直接丢弃**，不展示。
3. 参数不足时退化为「同封装 + 同类别」，并明确标注依据较弱。
4. 绝不自动替换——这里只负责"给出候选"，是否替换由操作员勾选。
"""
from odoo.tests import TransactionCase, tagged


@tagged('at_install', '-post_install', 'lab_catalog')
class CatalogEquivalentsTest(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Item = cls.env['lab.catalog.item']
        cls.Param = cls.env['lab.catalog.param']
        cls.location = cls.env['stock.location'].create({
            'name': 'EQ-A01',
            'usage': 'internal',
        })
        cls.category = cls.env['lab.catalog.category'].create({
            'catalog_id': 920000,
            'name': '贴片电容',
            'name_en': 'MLCC',
        })

    # ------------------------------------------------------------------ helpers
    def _item(self, code, name, package, params, category=None):
        item = self.Item.create({
            'catalog_code': code,
            'name': name,
            'mpn': '%s-MPN' % code,
            'brand': '测试品牌',
            'package': package,
            'category_id': (category or self.category).id,
            'category_name': (category or self.category).name,
            'search_text': '%s %s' % (code, name),
            'param_count': len(params),
        })
        if params:
            self.Param.create([
                {'item_id': item.id, 'sequence': 10 + index * 10,
                 'code': code_key, 'name': name_key, 'value': value}
                for index, (code_key, name_key, value) in enumerate(params)
            ])
        return item

    def _stock(self, code, quantity):
        """给某个 C 编号建本地档案并放入库存（走 stock.quant，不直写）。"""
        template = self.env['product.template'].create({
            'name': '库存档案 %s' % code,
            'type': 'consu',
            'is_storable': True,
            'tracking': 'none',
            'lab_lcsc_code': code,
        })
        self.env['stock.quant']._update_available_quantity(
            template.product_variant_id, self.location, quantity)
        return template

    def _capacitor(self, code, capacitance='0.1uF', voltage='50V', package='0402'):
        return self._item(code, '贴片电容 %s %s' % (capacitance, voltage), package, [
            ('capacitance', '容值', capacitance),
            ('voltage', '耐压', voltage),
            ('dielectric', '介质', 'X7R'),
        ])

    def _codes(self, result, index=0):
        line = result['lines'][index]
        return [candidate['catalog_code'] for candidate in line['candidates']]

    # ------------------------------------------------------------------ tests
    def test_same_spec_different_code_is_offered(self):
        self._capacitor('C9200001')
        self._capacitor('C9200002', capacitance='100nF')
        self._stock('C9200002', 320)

        result = self.Item.equivalents([{'item_key': 'lcsc:C9200001', 'quantity': 4}])
        line = result['lines'][0]

        self.assertEqual(line['basis'], 'params')
        self.assertIn('C9200002', self._codes(result))
        candidate = line['candidates'][0]
        self.assertEqual(candidate['confidence'], 'strong')
        self.assertEqual(candidate['available'], 320)
        self.assertIn('容值', [entry['name'] for entry in candidate['matched']])

    def test_source_code_never_appears_in_its_own_candidates(self):
        self._capacitor('C9200010')
        self._stock('C9200010', 50)
        self._capacitor('C9200011')
        self._stock('C9200011', 50)

        result = self.Item.equivalents([{'item_key': 'lcsc:C9200010', 'quantity': 1}])
        self.assertNotIn('C9200010', self._codes(result))

    def test_lower_voltage_candidate_is_dropped(self):
        self._capacitor('C9200020', voltage='50V')
        self._capacitor('C9200021', voltage='25V')
        self._stock('C9200021', 500)

        result = self.Item.equivalents([{'item_key': 'lcsc:C9200020', 'quantity': 2}])
        self.assertNotIn('C9200021', self._codes(result))

    def test_different_capacitance_is_dropped(self):
        self._capacitor('C9200030', capacitance='0.1uF')
        self._capacitor('C9200031', capacitance='1uF')
        self._stock('C9200031', 500)

        result = self.Item.equivalents([{'item_key': 'lcsc:C9200030', 'quantity': 2}])
        self.assertNotIn('C9200031', self._codes(result))

    def test_no_stock_candidate_is_not_offered(self):
        self._capacitor('C9200040')
        self._capacitor('C9200041')
        # 没有库存：不该作为可替换候选出现
        result = self.Item.equivalents([{'item_key': 'lcsc:C9200040', 'quantity': 1}])
        self.assertNotIn('C9200041', self._codes(result))

    def test_missing_parameters_fall_back_to_package(self):
        self._item('C9200050', '无参数器件', 'SOT-23', [])
        self._item('C9200051', '另一个无参数器件', 'SOT-23', [])
        self._stock('C9200051', 40)

        result = self.Item.equivalents([{'item_key': 'lcsc:C9200050', 'quantity': 1}])
        line = result['lines'][0]
        self.assertEqual(line['basis'], 'package_category')
        self.assertIn('C9200051', self._codes(result))
        self.assertEqual(line['candidates'][0]['confidence'], 'weak')

    def test_batch_returns_one_entry_per_line(self):
        self._capacitor('C9200060')
        self._capacitor('C9200061')
        self._stock('C9200061', 10)

        result = self.Item.equivalents([
            {'item_key': 'lcsc:C9200060', 'quantity': 1},
            {'item_key': 'lcsc:C9999999', 'quantity': 1},
        ])
        self.assertEqual(len(result['lines']), 2)
        self.assertEqual(result['lines'][1]['basis'], 'none')
        self.assertEqual(result['lines'][1]['candidates'], [])

    def test_unindexed_eda_part_matches_only_compatible_stocked_templates(self):
        def stocked(code, package, value):
            template = self._stock(code, 100)
            template.write({
                'lab_package': package,
                'lab_specifications': '{"容值": "%s"}' % value,
            })
            return template

        compatible = stocked('C9200081', '0603', '0.1uF')
        stocked('C9200082', '0805', '100nF')
        stocked('C9200083', '0603', '110nF')
        self.env['product.template'].create({
            'name': '无库存测试物料', 'type': 'consu',
            'lab_package': '0603', 'lab_specifications': '{"容值": "100nF"}',
        })

        result = self.Item.equivalents([{
            'item_key': 'lcsc:C5137636', 'quantity': 61,
            'name': '100 nF', 'footprint': 'C0603_L1.6-W0.8',
        }])
        line = result['lines'][0]
        self.assertEqual(line['basis'], 'value_package')
        self.assertEqual([c['item_key'] for c in line['candidates']],
                         ['lab:%d' % compatible.id])
        self.assertEqual(line['candidates'][0]['sn'], compatible.lab_sn)

    def test_candidate_carries_location_and_bags(self):
        self._capacitor('C9200070')
        self._capacitor('C9200071')
        self._stock('C9200071', 25)

        result = self.Item.equivalents([{'item_key': 'lcsc:C9200070', 'quantity': 1}])
        candidate = result['lines'][0]['candidates'][0]
        self.assertIn('locations', candidate)
        self.assertIn('bags', candidate)
        self.assertEqual(candidate['locations'][0]['name'], 'EQ-A01')
