# -*- coding: utf-8 -*-
"""A4 标签 PDF 生成（reportlab，矢量）。

硬性要求（需求与契约）：

* A4 物理尺寸、毫米输入、超出可用区域明确拒绝
* 每张器件标签**只印一个**追溯二维码（LABB:）；库位标签只印一个库码二维码（LABL:）
* 二维码使用 reportlab 标准组件 ``QrCodeWidget``（barLevel='M'、barBorder=4 静区），
  矢量输出；每个标签**只画一个**二维码
* 中文必须**真实可用**：字体用 cmap ``charToGlyph`` 逐个字形实测（见 tools/font_utils.py），
  缺字形就换候选，全部失败则拒绝生成，绝不静默丢字
* 只读：本模块不写任何库存字段/移动/quant

字体候选顺序：``LAB_WORKFLOW_LABEL_FONT`` 环境变量 → 系统参数
``lab_workflow.label_font`` → 模块自带 SIL OFL 字体（``static/fonts/``） → 系统 CJK 字体。
"""

import io
import logging
import os

from odoo import _
from odoo.exceptions import UserError

from . import font_utils, label_render

_logger = logging.getLogger(__name__)


class LabelFontError(UserError):
    """找不到可用的中文字体（附中文修复步骤）。"""


class LabelPdfError(UserError):
    """标签参数/生成错误（中文可执行提示）。"""


def register_label_font(env, required_text):
    """挑选并注册一个**实测支持全部所需字形**的字体；返回 (font_name, path)。

    实现见 ``tools/font_utils.py``：用 cmap 的 ``charToGlyph`` 真实判定字形，
    不用 ``stringWidth > 0``（DejaVu 对汉字也会返回正宽度，但打印是方块）。
    """
    try:
        return font_utils.register_cjk_font(env, required_text=required_text)
    except font_utils.FontUnavailable as exc:
        raise LabelFontError(str(exc))


def _draw_qr(canvas, payload, x_mm, y_mm, size_mm):
    """用 reportlab 标准二维码组件画**矢量**二维码（不新增依赖、不丢模块）。

    * ``reportlab.graphics.barcode.qr.QrCodeWidget``：标准 QR 编码实现
    * ``barLevel='M'``：中等纠错（标签被磨花/反光时仍可扫）
    * ``barBorder=4``：严格按 ISO/IEC 18004 的 4 模块静区，避免边上被裁
    * 物理尺寸按 mm 精确设置 barWidth/barHeight，二维码是矢量、放大不失真
    """
    from reportlab.graphics import renderPDF
    from reportlab.graphics.barcode.qr import QrCodeWidget
    from reportlab.graphics.shapes import Drawing

    if not payload:
        raise LabelPdfError(_('标签缺少二维码内容，已拒绝生成（不打印空码）'))
    size_pt = size_mm * label_render.MM_TO_PT
    widget = QrCodeWidget(str(payload), barLevel='M', barBorder=4)
    try:
        widget.barWidth = size_pt
        widget.barHeight = size_pt
    except AttributeError:  # pragma: no cover - 兼容旧版属性名
        widget.width = size_pt
        widget.height = size_pt

    drawing = Drawing(size_pt, size_pt)
    drawing.add(widget)
    renderPDF.draw(drawing, canvas, x_mm * label_render.MM_TO_PT,
                   y_mm * label_render.MM_TO_PT)


def qr_modules(payload, error_level='M'):
    """返回二维码模块边长（**含**两侧共 8 模块静区），用于尺寸/可扫性校验。

    reportlab 的 ``QrCodeWidget`` 只有在 ``draw()``（内部会先 ``qr.make()``）
    之后才有完整的模块矩阵，因此这里显式触发一次编码。
    """
    matrix_modules = qr_module_count(payload, error_level)
    return matrix_modules + 8 if matrix_modules else None


def qr_module_count(payload, error_level='M'):
    """二维码矩阵边长（不含静区），例如版本 1 = 21。"""
    from reportlab.graphics.barcode.qr import QrCodeWidget

    widget = QrCodeWidget(str(payload), barLevel=error_level, barBorder=4)
    widget.draw()  # 触发标准编码器 make()
    getter = getattr(getattr(widget, 'qr', None), 'getModuleCount', None)
    if callable(getter):
        try:
            value = getter()
            if value:
                return int(value)
        except Exception:  # noqa: BLE001
            return None
    return None


def qr_module_size_mm(payload, size_mm, error_level='M'):
    """二维码模块的物理边长（mm）。

    小于 ``label_render.QR_MODULE_MIN_MM`` 说明印小了、手机/扫码枪可能扫不出。
    """
    modules = qr_modules(payload, error_level)
    if not modules or not size_mm:
        return None
    return float(size_mm) / float(modules)


def _wrap_line(text, font_name, font_size, max_width_pt):
    """按可用宽度折行（中英混排按字符折，不截断、不丢字）。"""
    from reportlab.pdfbase import pdfmetrics
    text = str(text or '')
    if not text:
        return []
    lines = []
    current = ''
    for char in text:
        candidate = current + char
        if pdfmetrics.stringWidth(candidate, font_name, font_size) <= max_width_pt:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = char
    if current:
        lines.append(current)
    return lines


def fit_text_layout(content, font_name, text_width_mm, text_height_mm,
                    title_size_pt, body_size_pt):
    """把一张标签的**全部**文字排进去，必要时真实缩小字号。

    绝不静默丢字（不截断行、不截断标题）：

    1. 用给定字号折行，算出「标题行数 + 正文行数」所需总高度
    2. 放不下就在 ``MIN_TITLE_PT..title_size_pt`` / ``MIN_BODY_PT..body_size_pt``
       范围内**逐步真实缩小字号**（每次重新折行、重新算高度）
    3. 连最小字号都放不下则抛中文错误，提示加大宽高或减少字段

    :returns: ``(title_lines, body_lines, title_size, body_size, line_height_mm)``
    :raises LabelPdfError: 合理字号下仍放不下
    """
    max_width_pt = label_render.mm_to_pt(text_width_mm)
    available_mm = text_height_mm

    title = str(content.title or '')
    body_items = [str(item) for item in (content.lines or []) if str(item).strip()]

    title_pt = float(title_size_pt)
    body_pt = float(body_size_pt)
    # 从原始字号逐步缩到 0.6 倍（14 步），每次真实重排、重新算高度；
    # 一旦放得下就采用当前字号。
    for step in range(15):
        scale = 1.0 - 0.04 * step
        current_title_pt = max(label_render.MIN_TITLE_FONT_PT, title_pt * scale)
        current_body_pt = max(label_render.MIN_BODY_FONT_PT, body_pt * scale)
        title_lines = _wrap_line(title, font_name, current_title_pt, max_width_pt) or ['']
        body_lines = []
        for item in body_items:
            body_lines.extend(_wrap_line(item, font_name, current_body_pt, max_width_pt) or [''])
        line_height_mm = current_body_pt / label_render.MM_TO_PT * 1.30
        title_height_mm = len(title_lines) * (current_title_pt / label_render.MM_TO_PT * 1.25)
        body_height_mm = len(body_lines) * line_height_mm
        needed_mm = title_height_mm + body_height_mm
        if needed_mm <= available_mm + 1e-6:
            return title_lines, body_lines, current_title_pt, current_body_pt, line_height_mm

    raise LabelPdfError(
        _('标签「{title}」的文字在 {w:.1f}×{h:.1f}mm 的文字区里放不下：'
          '最小字号 {minpt:.1f}pt 仍需要约 {need:.1f}mm 高，可用只有 {have:.1f}mm。'
          '请加大标签宽高，或减少打印字段、缩短参数内容。').format(
            title=title or content.trace_code or content.payload or '（无标题）',
            w=text_width_mm, h=text_height_mm,
            minpt=label_render.MIN_BODY_FONT_PT,
            need=needed_mm, have=available_mm))


def build_label_pdf(env, spec, contents, font_size_pt=None, title_size_pt=None,
                    border=True):
    """生成 A4 标签 PDF。

    :param env: Odoo env（用于读取系统参数字体配置；只读）
    :param spec: label_render.LabelSpec
    :param contents: list[label_render.LabelContent]（已按份数展开）
    :returns: bytes（PDF）
    """
    from reportlab.lib.colors import Color, black
    from reportlab.pdfgen import canvas as pdf_canvas

    if not contents:
        raise LabelPdfError(_('没有可打印的标签内容（ids 为空或对象已被删除）'))

    required_text = ''.join(''.join(item.lines) + item.title for item in contents)
    font_name, font_path = register_label_font(env, required_text)

    grid = label_render.compute_grid(spec)
    total = len(contents)
    pages = [contents[i:i + grid['per_page']]
             for i in range(0, total, grid['per_page'])]

    margin = grid['effective_margin_mm']
    label_w = spec.width_mm
    label_h = spec.height_mm
    gap = spec.gap_mm
    title_size = title_size_pt or max(5.5, min(9.0, label_h / 3.2))
    body_size = font_size_pt or max(4.5, min(7.5, label_h / 4.6))

    buffer = io.BytesIO()
    pdf = pdf_canvas.Canvas(
        buffer, pagesize=(label_render.mm_to_pt(label_render.A4_WIDTH_MM),
                          label_render.mm_to_pt(label_render.A4_HEIGHT_MM)))
    pdf.setTitle('实验室库存标签')
    pdf.setAuthor('lab_workflow')
    layout_stats = []

    for page_index, page_items in enumerate(pages, start=1):
        if page_index > 1:
            pdf.showPage()
        for index, content in enumerate(page_items):
            row = index // grid['cols']
            col = index % grid['cols']
            x = margin + col * (label_w + gap)
            y = label_render.A4_HEIGHT_MM - margin - (row + 1) * label_h - row * gap

            if border:
                pdf.setStrokeColor(Color(0.6, 0.6, 0.6))
                pdf.setLineWidth(0.2)
                pdf.rect(label_render.mm_to_pt(x), label_render.mm_to_pt(y),
                         label_render.mm_to_pt(label_w), label_render.mm_to_pt(label_h))
            stats = _draw_label_body(pdf, content, x, y, label_w, label_h,
                                     font_name, title_size, body_size)
            layout_stats.append({
                'ref_id': content.ref_id,
                'payload': content.payload,
                'title_lines': stats['title_lines'],
                'body_lines': stats['body_lines'],
                'title_pt': stats['title_pt'],
                'body_pt': stats['body_pt'],
                'qr_size_mm': stats['qr_size_mm'],
            })

    pdf.showPage()
    pdf.save()
    data = buffer.getvalue()
    buffer.close()
    if not data.startswith(b'%PDF'):
        raise LabelPdfError(_('PDF 生成结果非法（缺少 PDF 头）'))
    return data, {
        'font_name': font_name,
        'font_path': font_path,
        'page_count': len(pages),
        'label_count': total,
        'layout_stats': layout_stats,
    }


def _draw_label_body(pdf, content, x_mm, y_mm, width_mm, height_mm,
                     font_name, title_size, body_size, module_min_mm=None):
    """一张标签：左侧**完整**文字（自动缩放/折行），右侧唯一二维码。

    布局规则（root 验收要求）：

    * 二维码在右侧固定区域，物理尺寸按 mm；**静区不被任何文字覆盖**
    * 文字区高度 = 标签高 - 2×内边距；标题按实际需要的行数**全部**画出
    * 正文用剩余高度；放不下就真实缩小字号（下限见 label_render）
    * 仍放不下 => 抛中文错误（提示加大宽高/减少字段），**绝不静默丢字**
    """
    from reportlab.lib.colors import black

    padding = min(1.6, width_mm * 0.04, height_mm * 0.08)
    # 二维码边长：受标签高度、可用宽度与绝对上限（22mm）共同约束
    qr_size = min(height_mm - 2 * padding,
                  width_mm - 2 * padding - label_render.TEXT_MIN_WIDTH_MM
                  - label_render.QR_QUIET_ZONE_MIN_MM,
                  label_render.QR_MAX_MM)
    qr_size = max(qr_size, label_render.QR_MIN_MM)
    if qr_size > height_mm - 2 * padding + 1e-9 or qr_size > width_mm * 0.6:
        raise LabelPdfError(
            _('标签 {w:.1f}×{h:.1f}mm 放不下 {qr:.1f}mm 的二维码与文字，请加大标签尺寸。')
            .format(w=width_mm, h=height_mm, qr=qr_size))
    module_min = module_min_mm or label_render.QR_MODULE_MIN_MM
    module_size = qr_module_size_mm(content.payload, qr_size)
    if module_size is not None and module_size < module_min - 1e-9:
        raise LabelPdfError(
            _('二维码模块只有 {size:.3f}mm（下限 {min:.2f}mm），扫不出来；'
              '请加大标签高度或缩短二维码内容。')
            .format(size=module_size, min=module_min))
    # 二维码静区（每侧 4 模块，随二维码等比缩放）：文字列不得越过静区边界
    matrix_modules = qr_module_count(content.payload) or 25
    quiet_mm = qr_size * 4.0 / (matrix_modules + 8.0)
    if quiet_mm < label_render.QR_QUIET_ZONE_MIN_MM - 1e-9:
        raise LabelPdfError(
            _('二维码静区只有 {quiet:.2f}mm（下限 {min:.2f}mm），边上会被裁；'
              '请加大标签尺寸或缩短二维码内容。')
            .format(quiet=quiet_mm, min=label_render.QR_QUIET_ZONE_MIN_MM))
    text_width_mm = width_mm - 2 * padding - qr_size - max(1.0, quiet_mm)
    if text_width_mm < label_render.TEXT_MIN_WIDTH_MM - 1e-9:
        raise LabelPdfError(
            _('文字区只剩 {tw:.1f}mm（下限 {min:.1f}mm，已为二维码静区留出 {quiet:.1f}mm）；'
              '请加大标签宽度。')
            .format(tw=text_width_mm, min=label_render.TEXT_MIN_WIDTH_MM, quiet=quiet_mm))

    text_height_mm = max(1.0, height_mm - 2 * padding)
    title_lines, body_lines, title_pt, body_pt, line_height_mm = fit_text_layout(
        content, font_name, text_width_mm, text_height_mm, title_size, body_size)

    top_mm = y_mm + height_mm - padding
    cursor_mm = top_mm
    pdf.setFillColor(black)

    # 标题：**全部行**都画，不截断
    pdf.setFont(font_name, title_pt)
    title_line_height_mm = title_pt / label_render.MM_TO_PT * 1.25
    for line in title_lines:
        cursor_mm -= title_line_height_mm
        pdf.drawString(label_render.mm_to_pt(x_mm + padding),
                       label_render.mm_to_pt(cursor_mm), line)

    # 正文：按行高依次画，fit_text_layout 已保证不会越界
    pdf.setFont(font_name, body_pt)
    for line in body_lines:
        cursor_mm -= line_height_mm
        if cursor_mm < y_mm + padding * 0.5:  # 理论上不会触发（前面已校验）
            raise LabelPdfError(
                _('标签「%s」正文排版内部不一致，已拒绝生成以免丢字。')
                % (content.title or content.trace_code or content.payload,))
        pdf.drawString(label_render.mm_to_pt(x_mm + padding),
                       label_render.mm_to_pt(cursor_mm), line)

    # 二维码：每张标签**只有一个**（内容为空直接拒绝，不打印空白码）
    if not content.payload:
        raise LabelPdfError(_('标签 %s 缺少二维码内容') % (content.title,))
    qr_x = x_mm + width_mm - padding - qr_size
    qr_y = y_mm + padding
    _draw_qr(pdf, content.payload, qr_x, qr_y, qr_size)
    return {
        'title_lines': len(title_lines),
        'body_lines': len(body_lines),
        'title_pt': round(title_pt, 2),
        'body_pt': round(body_pt, 2),
        'qr_size_mm': round(qr_size, 2),
    }
