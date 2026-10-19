# -*- coding: utf-8 -*-
"""离线纯逻辑测试：不依赖数据库、也不依赖 Odoo。

覆盖：

* 追溯码 / 库码 / SN / C 码 / 立创原厂袋二维码 解析
* request_key 校验与 payload 指纹（含接口名）
* A4 标签排版、份数、多页与边界校验
* 二维码：使用 **reportlab 标准组件** ``QrCodeWidget``（生产路径），
  并在装有 ``qrcode`` 时交叉核对模块数（不靠自研解码器自证）

运行（在 lab_workflow 目录下）::

    python3 -m unittest tests.test_offline_logic -v

或::

    python3 tests/test_offline_logic.py
"""

import importlib.util
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.abspath(os.path.join(_HERE, '..', 'tools'))

# 直接按文件加载纯逻辑模块：绕开 tools/__init__.py 里依赖 odoo 的部分
for _name in ('inventory_codec', 'request_keys', 'label_render'):
    _spec = importlib.util.spec_from_file_location(
        _name, os.path.join(_TOOLS, '%s.py' % _name))
    _module = importlib.util.module_from_spec(_spec)
    sys.modules[_name] = _module
    _spec.loader.exec_module(_module)

inventory_codec = sys.modules['inventory_codec']
request_keys = sys.modules['request_keys']
label_render = sys.modules['label_render']

if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def _has_reportlab():
    try:
        import reportlab  # noqa: F401
        return True
    except ImportError:
        return False


class TestInventoryCodec(unittest.TestCase):

    def test_lcsc_normalization(self):
        for raw, expected in (
            ('c123456', 'C123456'), ('C123456', 'C123456'), (' C123456 ', 'C123456'),
            ('C007', 'C7'), ('Ｃ１２３', 'C123'), ('C1', 'C1'), ('C0000001', 'C1'),
        ):
            self.assertEqual(inventory_codec.normalize_lcsc_code(raw), expected, raw)
        for raw in ('', None, 'C', 'Cx1', 'C-1'):
            self.assertIsNone(inventory_codec.normalize_lcsc_code(raw), raw)
        # 没有 C 前缀的纯数字按立创规则补 C（与 jlc_qr.normalize_lcsc_code 一致）
        self.assertEqual(inventory_codec.normalize_lcsc_code('123'), 'C123')

    def test_non_four_digit_codes_are_accepted(self):
        """需求明确：C 后跟正十进制数字即可，不要求 4 位以上。"""
        self.assertEqual(inventory_codec.normalize_lcsc_code('C7'), 'C7')
        self.assertEqual(inventory_codec.normalize_lcsc_code('C123'), 'C123')

    def test_trace_and_location_codes(self):
        self.assertEqual(inventory_codec.normalize_trace_code('labb:trc000001'), 'TRC000001')
        self.assertEqual(inventory_codec.normalize_trace_code('TRC000001'), 'TRC000001')
        self.assertIsNone(inventory_codec.normalize_trace_code('A'))
        self.assertEqual(inventory_codec.normalize_location_code('labl:k000001'), 'K000001')
        self.assertIsNone(inventory_codec.normalize_location_code('K'))

    def test_payload_builders(self):
        self.assertEqual(inventory_codec.build_bag_payload('TRC1'), 'LABB:TRC1')
        self.assertEqual(inventory_codec.build_location_payload('K1'), 'LABL:K1')
        self.assertIsNone(inventory_codec.build_bag_payload('!'))

    def test_jlc_bag_parsing(self):
        raw = '{on:SO2202102855,pc:C225521,pm:A2541WV-2x6P,qty:5,mc:null,cc:1,pdi:53220618,hp:0}'
        parsed = inventory_codec.parse_jlc_bag_text(raw)
        self.assertTrue(parsed['is_valid'], parsed)
        self.assertEqual(parsed['lcsc_code'], 'C225521')
        self.assertEqual(parsed['on'], 'SO2202102855')
        self.assertEqual(parsed['qty'], 5)
        self.assertIsNone(parsed['mc'])

    def test_classify_scan_routes(self):
        cases = (
            ('LABB:TRC000001', inventory_codec.KIND_BAG, 'TRC000001'),
            ('labl:K000001', inventory_codec.KIND_LOCATION, 'K000001'),
            ('C225521', inventory_codec.KIND_LCSC, 'C225521'),
            ('c225521', inventory_codec.KIND_LCSC, 'C225521'),
            ('LAB-000001', inventory_codec.KIND_SN, 'LAB-000001'),
        )
        for raw, kind, normalized in cases:
            parsed = inventory_codec.classify_scan(raw)
            self.assertEqual(parsed['kind'], kind, raw)
            self.assertEqual(parsed['normalized'], normalized, raw)
        jlc = inventory_codec.classify_scan('{on:SO1,pc:C225521,pm:X,qty:5}')
        self.assertEqual(jlc['kind'], inventory_codec.KIND_JLC)
        self.assertEqual(jlc['normalized'], 'C225521')
        self.assertEqual(inventory_codec.classify_scan('乱码')['kind'],
                         inventory_codec.KIND_UNKNOWN)
        self.assertEqual(inventory_codec.classify_scan('')['kind'],
                         inventory_codec.KIND_UNKNOWN)


class TestRequestKeys(unittest.TestCase):

    def test_request_key_validation(self):
        self.assertTrue(request_keys.is_valid_request_key('a' * 8))
        self.assertTrue(request_keys.is_valid_request_key('8f3c1a2b-4d5e'))
        self.assertFalse(request_keys.is_valid_request_key('short'))
        self.assertFalse(request_keys.is_valid_request_key('has space in it'))
        self.assertFalse(request_keys.is_valid_request_key('a' * 200))
        self.assertFalse(request_keys.is_valid_request_key(''))

    def test_fingerprint_stability(self):
        a = {'quantity': 20, 'bag_id': 1, 'lines': [{'bag_id': 1, 'quantity': 20}]}
        b = {'bag_id': 1, 'lines': [{'quantity': 20.0, 'bag_id': 1}], 'quantity': 20.0}
        self.assertEqual(request_keys.fingerprint(a), request_keys.fingerprint(b))
        self.assertNotEqual(request_keys.fingerprint(a),
                            request_keys.fingerprint(dict(a, quantity=21)))

    def test_fingerprint_includes_route(self):
        params = {'item_key': 'lcsc:C1', 'quantity': 5}
        receipt = dict(params, __route='inventory.receipt')
        issue = dict(params, __route='inventory.issue')
        self.assertNotEqual(request_keys.fingerprint(receipt),
                            request_keys.fingerprint(issue))

    def test_note_is_not_part_of_fingerprint(self):
        """备注属于展示层，同样的业务请求不应因为备注不同而变成两次记账。"""
        a = {'request_key': 'k' * 12, 'quantity': 5, 'note': 'A'}
        b = {'request_key': 'k' * 12, 'quantity': 5, 'note': 'B'}
        self.assertEqual(request_keys.fingerprint(a), request_keys.fingerprint(b))

    def test_payload_diff_keys(self):
        self.assertEqual(request_keys.payload_diff_keys({'quantity': 5}, {'quantity': 6}),
                         ['quantity'])


class TestLabelLayout(unittest.TestCase):

    def _spec(self, **kwargs):
        params = {'kind': 'bag', 'width_mm': 50, 'height_mm': 30, 'margin_mm': 10,
                  'gap_mm': 2, 'copies': 1, 'fields': ['sn', 'location']}
        params.update(kwargs)
        return label_render.LabelSpec(**params)

    def test_a4_grid(self):
        grid = label_render.compute_grid(self._spec())
        self.assertEqual(grid['effective_margin_mm'], 10.0)
        self.assertEqual(grid['usable_width_mm'], 190.0)
        self.assertEqual(grid['usable_height_mm'], 277.0)
        self.assertEqual(grid['cols'], 3)
        self.assertEqual(grid['rows'], 8)
        self.assertEqual(grid['per_page'], 24)

    def test_pagination(self):
        plan = label_render.paginate(self._spec(), total_labels=50)
        self.assertEqual(plan['page_count'], 3)
        self.assertEqual(plan['pages'], [24, 24, 2])
        self.assertEqual(len(label_render.build_contents(self._spec(), [{'kind': 'bag'}])), 1)

    def test_copies_expand(self):
        spec = self._spec(copies=3)
        payloads = [{'kind': 'bag', 'ref_id': 1, 'payload': 'LABB:TRC1', 'sn': 'LAB-1',
                     'location_code': 'K1'}]
        self.assertEqual(len(label_render.build_contents(spec, payloads)), 3)

    def test_overflow_rejected(self):
        with self.assertRaises(label_render.LabelSpecError):
            label_render.validate_spec(self._spec(width_mm=205, margin_mm=5))
        with self.assertRaises(label_render.LabelSpecError):
            label_render.validate_spec(self._spec(height_mm=290, margin_mm=5))
        with self.assertRaises(label_render.LabelSpecError) as ctx:
            label_render.validate_spec(self._spec(width_mm=150, height_mm=30,
                                                  margin_mm=40))
        self.assertIn('超出 A4 可用宽度', str(ctx.exception))

    def test_too_small_label_rejected(self):
        """二维码 + 文字装不下的标签必须明确拒绝，不能裁切。"""
        min_w = label_render.MIN_LABEL_WIDTH_MM
        min_h = label_render.MIN_LABEL_HEIGHT_MM
        self.assertGreaterEqual(min_w, 22.0)
        self.assertGreaterEqual(min_h, 14.0)
        with self.assertRaises(label_render.LabelSpecError) as ctx:
            label_render.validate_spec(self._spec(width_mm=min_w - 2, height_mm=min_h + 6))
        self.assertIn('太小', str(ctx.exception))
        with self.assertRaises(label_render.LabelSpecError) as ctx:
            label_render.validate_spec(self._spec(width_mm=50, height_mm=min_h - 1))
        self.assertIn('太小', str(ctx.exception))
        with self.assertRaises(label_render.LabelSpecError):
            label_render.validate_spec(self._spec(width_mm=10, height_mm=8))
        # 刚好达到下限的标签应当通过
        label_render.validate_spec(self._spec(width_mm=min_w, height_mm=min_h))

    def test_bad_field_rejected(self):
        with self.assertRaises(label_render.LabelSpecError):
            label_render.validate_spec(self._spec(fields=['sn', 'not_a_field']))
        with self.assertRaises(label_render.LabelSpecError):
            label_render.validate_spec(self._spec(kind='bag', fields=['mpn']))

    def test_parameters_flattening(self):
        spec = self._spec(fields=['sn', 'parameters'])
        contents = label_render.build_contents(spec, [{
            'kind': 'bag', 'ref_id': 1, 'payload': 'LABB:TRC1', 'sn': 'LAB-1',
            'parameters': {'阻值': '270Ω', '精度': '±1%'},
        }])
        self.assertIn('阻值=270Ω', contents[0].lines)
        self.assertIn('精度=±1%', contents[0].lines)

    def test_minimum_label_constants_are_consistent(self):
        self.assertGreaterEqual(label_render.MIN_LABEL_HEIGHT_MM,
                                label_render.QR_MIN_MM)
        self.assertGreaterEqual(label_render.MIN_LABEL_WIDTH_MM,
                                label_render.QR_MIN_MM + label_render.TEXT_MIN_WIDTH_MM)


@unittest.skipUnless(_has_reportlab(), '需要 reportlab 才能验证二维码组件')
class TestReportlabQrWidget(unittest.TestCase):
    """生产二维码路径：reportlab 标准 QrCodeWidget（矢量、barBorder=4 静区）。"""

    def _widget(self, payload, level='M'):
        from reportlab.graphics.barcode.qr import QrCodeWidget
        widget = QrCodeWidget(payload, barLevel=level, barBorder=4)
        widget.draw()  # reportlab 先 make() 才有模块矩阵
        return widget

    def _modules(self, payload, level='M'):
        """模块数（不含静区）。"""
        return self._widget(payload, level).qr.getModuleCount()

    def test_module_count_stable_and_reasonable(self):
        modules = self._modules('LABB:TRC000001')
        self.assertEqual(modules, 21)  # 版本 1 短载荷
        self.assertEqual(modules % 4, 1)  # 21/25/29... 都满足 %4==1

    def test_longer_payload_grows_version(self):
        short = self._modules('LABB:TRC000001')
        longer = self._modules('LABB:TRC' + 'X' * 30)
        self.assertGreater(longer, short)

    def test_qr_is_vector_not_bitmap(self):
        from reportlab.graphics.shapes import Group, Rect
        widget = self._widget('LABB:TRC000001')
        drawing = widget.draw()
        self.assertIsInstance(drawing, Group)
        self.assertTrue(any(isinstance(shape, Rect) for shape in drawing.contents))
        self.assertGreaterEqual(len(drawing.contents), 20)

    def test_module_size_floor(self):
        # 12mm 高、版本 1~4（29~41 模块含静区）时模块尺寸仍高于下限
        for payload in ('LABB:TRC000001', 'LABB:TRC' + 'X' * 30):
            modules = self._modules(payload) + 8
            module_mm = 12.0 / modules
            self.assertGreaterEqual(module_mm, label_render.QR_MODULE_MIN_MM,
                                    '%s -> %.3fmm' % (payload[:16], module_mm))

    def test_cross_check_with_qrcode_library_when_available(self):
        """装了 qrcode 库就交叉核对模块数（两套独立实现的版本选择必须一致）。"""
        try:
            import qrcode
            from qrcode.constants import ERROR_CORRECT_M
        except ImportError:
            self.skipTest('未安装 qrcode，跳过交叉核对')
        for payload in ('LABB:TRC000001', 'LABL:K000001', 'LABB:' + 'A' * 60):
            reference = qrcode.QRCode(error_correction=ERROR_CORRECT_M,
                                      box_size=1, border=0)
            reference.add_data(payload)
            reference.make(fit=True)
            self.assertEqual(self._modules(payload),
                             len(reference.get_matrix()), payload[:20])


class TestLegacyQrRegression(unittest.TestCase):
    """旧自研二维码编码器的回归对照（**不是生产码源**，生产用 reportlab 组件）。

    仅当仓库里还保留 ``tools/qr_encode.py`` + ``tests/qr_decode_probe.py`` 时运行，
    避免「用同一个自研解码器自证」：这里核对的是 RS 分块表与标准总码字数一致，
    以及短载荷（标签实际使用的 LABB/LABL 大写载荷）的编解码闭环。
    """

    @classmethod
    def setUpClass(cls):
        if not os.path.isfile(os.path.join(_TOOLS, 'qr_encode.py')):
            raise unittest.SkipTest('已移除自研二维码编码器')
        spec = importlib.util.spec_from_file_location(
            'qr_encode', os.path.join(_TOOLS, 'qr_encode.py'))
        module = importlib.util.module_from_spec(spec)
        sys.modules['qr_encode'] = module
        spec.loader.exec_module(module)
        cls.qr = module
        try:
            import qr_decode_probe
            cls.probe = qr_decode_probe
        except ImportError:
            raise unittest.SkipTest('没有回归解码器')

    def test_block_table_totals_match_standard(self):
        for version in range(1, 21):
            for level in 'LMQH':
                ec_per_block, groups, _blocks = self.qr.RS_BLOCK_TABLE[(version, level)]
                total = sum(count * (data + ec_per_block) for count, data in groups)
                self.assertEqual(total, self.qr.TOTAL_CODEWORDS[version],
                                 '%s-%s' % (version, level))

    def test_label_payload_round_trip(self):
        for payload in ('LABB:TRC000001', 'LABL:K000001', 'C225521', 'LAB-000001'):
            for level in 'LMQH':
                version, size, matrix, cw, mask = self.qr.encode(
                    payload, level, with_mask=True)
                self.assertEqual(self.probe.decode(matrix, mask), payload,
                                 '%s/%s' % (payload, level))


if __name__ == '__main__':
    unittest.main(verbosity=2)
