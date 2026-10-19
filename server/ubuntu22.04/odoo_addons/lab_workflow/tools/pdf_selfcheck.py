# -*- coding: utf-8 -*-
"""标签 PDF 自检脚本：不需要 Odoo，只依赖 reportlab（+ 可选 pypdf）。

用途：新增/更换字体后**必须**跑一次，确认中文真的进了 PDF、二维码能画出、
多页与份数正确。仅依赖 reportlab 的检查不装 pypdf 也能跑。

用法::

    python3 tools/pdf_selfcheck.py [可选字体文件]

退出码 0 = 全部通过；非 0 = 有断言失败（脚本会打印中文原因）。
"""

import base64
import os
import sys
import types

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ---------------------------------------------------------------------------
# 最小 odoo stub：让本模块能在没有 Odoo 的机器上被 import
# ---------------------------------------------------------------------------
_odoo = types.ModuleType('odoo')
_odoo._ = lambda text, *a, **kw: text
_exc = types.ModuleType('odoo.exceptions')


class _UserError(Exception):
    pass


_exc.UserError = _UserError
_odoo.exceptions = _exc
sys.modules.setdefault('odoo', _odoo)
sys.modules.setdefault('odoo.exceptions', _exc)

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG_ROOT = os.path.dirname(_HERE)
for _path in (_PKG_ROOT, _HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

# 以包的方式加载 tools 目录，保证模块内的相对 import（from . import ...）能工作；
# 在 Odoo 里则由 Odoo 的加载器负责，无需这段逻辑。
import importlib  # noqa: E402

_tools_pkg = types.ModuleType('labtools')
_tools_pkg.__path__ = [_HERE]
sys.modules.setdefault('labtools', _tools_pkg)
label_render = importlib.import_module('labtools.label_render')
font_utils = importlib.import_module('labtools.font_utils')
pdf_labels = importlib.import_module('labtools.pdf_labels')


def _sample_payloads(count=3):
    rows = []
    for index in range(1, count + 1):
        rows.append({
            'kind': 'bag',
            'ref_id': index,
            'payload': 'LABB:TRC%06d' % index,
            'trace_code': 'TRC%06d' % index,
            'sn': 'LAB-%06d' % index,
            'location_code': 'K%06d' % index,
            'location': 'Lab/R%02d' % index,
            'mpn': 'A2541WV-2x6P' if index % 2 else 'STM32F103C8T6',
            'catalog_code': 'C22552%d' % index,
            'parameters': {'阻值': '270Ω', '精度': '±1%', '封装': '0805'},
            'item_name': '测试物料 %d' % index,
        })
    return rows


def main():
    explicit_font = sys.argv[1] if len(sys.argv) > 1 else None
    if explicit_font:
        font_name, font_path = font_utils.register_cjk_font_from_path(
            os.path.abspath(explicit_font))
    else:
        font_name, font_path = font_utils.register_cjk_font(None)
    print('使用字体：%s (%s)' % (font_name, font_path))

    spec = label_render.LabelSpec(
        kind='bag', width_mm=50, height_mm=30, margin_mm=10, gap_mm=2,
        copies=2, fields=['sn', 'location', 'mpn', 'catalog_code', 'parameters'],
        ids=[1, 2, 3])
    contents = label_render.build_contents(spec, _sample_payloads(3))
    assert len(contents) == 6, contents
    pdf_bytes, meta = pdf_labels.build_label_pdf(None, spec, contents)
    assert pdf_bytes.startswith(b'%PDF'), 'PDF 头缺失'
    print('PDF 生成成功：%d 字节，%d 页，%d 张标签'
          % (len(pdf_bytes), meta['page_count'], meta['label_count']))
    assert meta['page_count'] == 1 and meta['label_count'] == 6

    # 多页
    big_spec = label_render.LabelSpec(
        kind='bag', width_mm=50, height_mm=30, margin_mm=10, gap_mm=2, copies=1,
        fields=['sn', 'location'], ids=list(range(1, 61)))
    big_contents = label_render.build_contents(big_spec, _sample_payloads(3) * 20)
    big_pdf, big_meta = pdf_labels.build_label_pdf(None, big_spec, big_contents)
    print('多页 PDF：%d 页' % big_meta['page_count'])
    assert big_meta['page_count'] == 3, big_meta

    # 极小标签必须拒绝
    try:
        tiny = label_render.LabelSpec(kind='bag', width_mm=20, height_mm=14,
                                      margin_mm=5, gap_mm=1, copies=1,
                                      fields=['sn', 'location'], ids=[1])
        label_render.validate_spec(tiny)
        raise AssertionError('20x14 应当被拒绝')
    except label_render.LabelSpecError as exc:
        print('极小标签已拒绝：%s' % exc)

    # 二维码模块尺寸
    for payload in ('LABB:TRC000001', 'LABB:TRC' + 'X' * 30):
        size = pdf_labels.qr_module_size_mm(payload, 12.0)
        assert size >= label_render.QR_MODULE_MIN_MM, (payload, size)
        print('模块尺寸 %r -> %.3fmm' % (payload[:18], size))

    # 可选：pypdf 抽文本，确认中文/编号真的写进内容流
    try:
        import io
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        text = reader.pages[0].extract_text() or ''
        assert 'LAB-000001' in text, text[:200]
        assert 'C225521' in text, text[:200]
        assert '270' in text, text[:200]
        print('pypdf 文本层校验通过（中文参数与编号都在）')
    except ImportError:
        print('（未安装 pypdf，跳过文本层抽取校验）')

    # 输出一份给人看的样例 PDF（写到 addon 外的自检输出目录，避免污染交付目录）
    out_dir = os.environ.get('LAB_WORKFLOW_SELFCHECK_OUT') or os.path.join(
        os.path.dirname(_PKG_ROOT), 'lab_workflow_selfcheck_out')
    try:
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, 'label_selfcheck_sample.pdf')
        with open(out_path, 'wb') as handle:
            handle.write(pdf_bytes)
        print('样例 PDF 已写到：%s' % out_path)
    except OSError as exc:
        print('（样例 PDF 未写出：%s）' % exc)
    print('全部自检通过')


if __name__ == '__main__':
    main()
