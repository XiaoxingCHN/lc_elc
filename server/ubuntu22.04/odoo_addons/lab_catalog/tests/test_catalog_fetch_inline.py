# -*- coding: utf-8 -*-
"""Odoo integration tests for synchronous (inline) on-demand fetch.

These need a real Odoo database (``--test-enable``); the pure HTTP/budget rules
are covered by ``test_lcsc_remote.py`` and run without Odoo or network.
All remote calls are patched, so no test reaches lcsc.com.
"""
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from odoo.addons.lab_catalog.models import lab_catalog_fetch as fetch_model


@tagged('at_install', '-post_install', 'lab_catalog')
class CatalogFetchInlineTest(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Fetch = cls.env['lab.catalog.fetch.request']

    def _new_request(self, query='C32445874', kind='c_code'):
        return self.Fetch.create({
            'query_raw': query,
            'query_norm': query,
            'query_kind': kind,
        })

    def test_lock_busy_leaves_request_queued(self):
        """Another worker holding the lock must not fail the API call."""
        with self.registry.cursor() as other:
            other.execute('SELECT pg_advisory_lock(%s)', [fetch_model.LOCK_ID])
            try:
                record = self._new_request()
                self.Fetch._process_inline(record, budget_seconds=1)
                self.assertEqual(record.state, 'queued')
            finally:
                other.execute('SELECT pg_advisory_unlock(%s)',
                              [fetch_model.LOCK_ID])

    def test_inline_success_marks_done_and_writes_once(self):
        parsed = {
            'code': 'C32445874', 'product_id': '57330406', 'mpn': 'X1',
            'name': '测试器件', 'brand': 'TI', 'package': 'SOT-23',
            'price': 1.23, 'stock': 10, 'parameters': [], 'catalog': {},
            'files': [], 'image_url': '', 'source_url': '',
        }
        item = self.env['lab.catalog.item'].create({
            'catalog_code': 'C32445874', 'name': '测试器件',
        })
        record = self._new_request()
        with patch.object(fetch_model.lcsc_remote, 'fetch_product_detail',
                          return_value={'productId': 57330406,
                                        'parentCatalogId': 380}), \
                patch.object(fetch_model.lcsc_remote, 'fetch_cn_page',
                             return_value='<html/>'), \
                patch.object(fetch_model.lcsc_remote, 'parse_cn_page',
                             return_value=parsed), \
                patch.object(type(record), '_resolve_category',
                             return_value=(self.env['lab.catalog.category'],
                                           380, '稳压器', '电源/稳压器')), \
                patch.object(type(record), '_upsert_item',
                             return_value=(item, True)) as upsert:
            self.Fetch._process_inline(record, budget_seconds=5)
        self.assertEqual(record.state, 'done')
        self.assertEqual(record.catalog_code, 'C32445874')
        self.assertEqual(upsert.call_count, 1)

    def test_budget_exhausted_returns_to_queue(self):
        """A spent budget is not a failure: the cron worker takes over."""
        record = self._new_request()
        error = fetch_model.lcsc_remote.LcscRemoteError(
            '抓取时间预算已用完，已转入后台队列。', 'budget_exhausted')
        with patch.object(fetch_model.lcsc_remote, 'fetch_product_detail',
                          side_effect=error):
            self.Fetch._process_inline(record, budget_seconds=1)
        self.assertEqual(record.state, 'queued')
        self.assertIn('预算', record.message or '')
        self.assertFalse(record.finished_at)

    def test_non_electronic_is_skipped_before_cn_page(self):
        record = self._new_request()
        with patch.object(fetch_model.lcsc_remote, 'fetch_product_detail',
                          return_value={'productId': 1, 'isMro': True,
                                        'parentCatalogId': 999}), \
                patch.object(fetch_model.lcsc_remote, 'classify_root',
                             return_value='non_electronic'), \
                patch.object(fetch_model.lcsc_remote, 'fetch_cn_page') as cn:
            self.Fetch._process_inline(record, budget_seconds=5)
        self.assertEqual(record.state, 'skipped_non_electronic')
        self.assertFalse(cn.called)

    def _official_facts(self, code):
        return {
            'code': code,
            'name': '官方器件',
            'mpn': 'X2',
            'brand': 'TI(德州仪器)',
            'package': 'SOT-23',
            'stock': 7,
            'price': 1.5,
            'price_basis': 'openapi_smt_tier_price',
            'currency': 'CNY',
            'category_name': '单片机(MCU/MPU/SOC)',
            'parameters': [
                {'parameterName': '阻值', 'parameterValue': '10kΩ'},
            ],
        }

    def test_verification_page_falls_back_to_official_facts(self):
        """中文页被风控拦截时，官方接口已有的事实不能一起丢掉。

        用户看到的"器件详情什么都没有"就是整条请求被验证页判失败造成的；
        官方通道已经给出名称/型号/品牌/封装/库存/价格/参数，应照常入库。
        """
        code = 'C32445875'
        item = self.env['lab.catalog.item'].create({
            'catalog_code': code, 'name': '官方器件'})
        category = self.env['lab.catalog.category'].create({
            'catalog_id': 990001, 'name': '测试分类'})
        record = self._new_request(code)
        error = fetch_model.lcsc_remote.LcscRemoteError(
            '中文详情页缺少商品数据，可能被验证页拦截。', 'verification_page')
        with patch.object(type(record), '_official_item',
                          return_value=self._official_facts(code)), \
                patch.object(fetch_model.lcsc_remote, 'fetch_product_detail',
                             return_value={'productId': 57330406,
                                           'parentCatalogId': 470}), \
                patch.object(fetch_model.lcsc_remote, 'classify_root',
                             return_value='electronic'), \
                patch.object(fetch_model.lcsc_remote, 'fetch_cn_page',
                             side_effect=error), \
                patch.object(type(record), '_resolve_category',
                             return_value=(category, 470, '测试分类',
                                           '嵌入式/测试分类')), \
                patch.object(type(record), '_upsert_item',
                             return_value=(item, True)) as upsert:
            self.Fetch._process_inline(record, budget_seconds=5)

        self.assertEqual(record.state, 'done')
        parsed = upsert.call_args[0][0]
        self.assertEqual(parsed['name'], '官方器件')
        self.assertEqual(parsed['mpn'], 'X2')
        self.assertEqual(parsed['stock'], 7)
        self.assertEqual(parsed['parameters'],
                         [{'parameterCode': '', 'parameterName': '阻值',
                           'parameterValue': '10kΩ',
                           'parameterDetailValue': ''}])
        self.assertIn('风控', record.message or '')

    def test_verification_page_without_official_stays_retryable(self):
        """没有官方事实时不能假装成功：仍按可重试错误处理。"""
        code = 'C32445876'
        record = self._new_request(code)
        error = fetch_model.lcsc_remote.LcscRemoteError(
            '中文详情页缺少商品数据，可能被验证页拦截。', 'verification_page')
        with patch.object(type(record), '_official_item', return_value=None), \
                patch.object(fetch_model.lcsc_remote, 'fetch_product_detail',
                             return_value={'productId': 57330407,
                                           'parentCatalogId': 470}), \
                patch.object(fetch_model.lcsc_remote, 'classify_root',
                             return_value='electronic'), \
                patch.object(fetch_model.lcsc_remote, 'fetch_cn_page',
                             side_effect=error), \
                patch.object(type(record), '_upsert_item') as upsert:
            self.Fetch._process_inline(record, budget_seconds=5)

        self.assertEqual(record.state, 'queued')
        self.assertFalse(upsert.called)
        self.assertIn('风控', record.message or '')

    def test_catalogued_item_enriches_placeholder_template(self):
        """资料入库后，按 C 编号建的"（待补全）"档案要就地补全。

        否则袋标签、库存卡片会一直显示占位名，用户以为资料没抓到。
        """
        code = 'C32445877'
        self.env['lab.catalog.item'].create({
            'catalog_code': code, 'name': '真实名称', 'mpn': 'ABC123',
            'brand': 'TI(德州仪器)', 'package': 'SOT-23'})
        template = self.env['product.template'].create({
            'name': '立创物料 %s（待补全）' % code, 'lab_lcsc_code': code})
        self.Fetch._enrich_stub_templates(code)
        template.invalidate_recordset()
        self.assertEqual(template.name, '真实名称')
        self.assertEqual(template.lab_mpn, 'ABC123')
        self.assertEqual(template.lab_package, 'SOT-23')
