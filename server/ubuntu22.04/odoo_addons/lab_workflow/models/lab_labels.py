# -*- coding: utf-8 -*-
"""lab.workflow.common 的标签方法：排版试算与 A4 PDF 生成（只读）。"""

import base64
import logging

from odoo import _, api, models

from ..tools import label_render
from ..tools.pdf_labels import LabelFontError, LabelPdfError, build_label_pdf
from .lab_workflow_common import LabApiError

_logger = logging.getLogger(__name__)


class LabWorkflowLabels(models.AbstractModel):
    _inherit = 'lab.workflow.common'

    # ------------------------------------------------------------------
    @api.model
    def _lab_build_spec(self, kind, width_mm, height_mm, margin_mm, gap_mm, copies, fields):
        spec = label_render.LabelSpec(
            kind=kind or label_render.KIND_BAG,
            width_mm=width_mm,
            height_mm=height_mm,
            margin_mm=margin_mm,
            gap_mm=gap_mm,
            copies=copies,
            fields=fields,
            ids=[],
        )
        try:
            label_render.validate_spec(spec)
        except label_render.LabelSpecError as error:
            raise LabApiError(error.message,
                              {error.field: 'invalid'} if error.field else {})
        return spec

    @api.model
    def _lab_label_payloads(self, spec, ids):
        """取出待打印对象的只读事实；不存在的 id 明确报错。"""
        if not isinstance(ids, (list, tuple)) or not ids:
            raise LabApiError.validation('必须至少指定一个 id', {'ids': 'required'})
        if len(ids) > 200:
            raise LabApiError.validation('一次最多打印 200 个标签（可用份数放大）',
                                         {'ids': 'too_many'})
        payloads = []
        if spec.kind == label_render.KIND_BAG:
            bags = self.env['lab.bag'].browse([int(i) for i in ids]).exists()
            missing = sorted(set(int(i) for i in ids) - set(bags.ids))
            if missing:
                raise LabApiError.not_found('袋不存在或无权访问：%s' % missing,
                                            {'ids': 'not_found'})
            for bag in bags:
                facts = bag._lab_label_facts()
                payloads.append(facts)
        else:
            locations = self.env['stock.location'].browse([int(i) for i in ids]).exists()
            missing = sorted(set(int(i) for i in ids) - set(locations.ids))
            if missing:
                raise LabApiError.not_found('库位不存在或无权访问：%s' % missing,
                                            {'ids': 'not_found'})
            for location in locations:
                payload = location._lab_label_payload()
                payloads.append({
                    'kind': label_render.KIND_LOCATION,
                    'ref_id': location.id,
                    'payload': payload,
                    'trace_code': location.lab_code or '',
                    'title': location.lab_code or location.name,
                    'location_code': location.lab_code or '',
                    'location': location.complete_name or location.display_name,
                    'item_name': location.name,
                })
        return payloads

    # ------------------------------------------------------------------
    @api.model
    def lab_labels_plan(self, kind='bag', ids=None, copies=1, width_mm=50, height_mm=30,
                        margin_mm=10, gap_mm=2, fields=None):
        """排版试算：每页几张、共几页，并给出**预览字号**与可读性下限。

        ``preview_title_pt/preview_body_pt`` 是真实排版会用的字号，
        低于 ``min_title_pt``/``min_body_pt``（顶层设计红线 6.5/5.5pt）时会拒绝生成，
        因此这里让界面能提前看到字号是否够读。
        """
        spec = self._lab_build_spec(kind, width_mm, height_mm, margin_mm, gap_mm,
                                    copies, fields)
        spec.ids = list(ids or [])
        count = len(spec.ids) * max(1, int(copies or 1))
        plan = label_render.describe_plan(spec)
        plan['label_count'] = count
        plan['labels_per_page'] = label_render.compute_grid(spec)['per_page']
        plan['page_count'] = ((count + plan['labels_per_page'] - 1)
                              // plan['labels_per_page']) if count else 0
        plan['min_title_pt'] = label_render.MIN_TITLE_FONT_PT
        plan['min_body_pt'] = label_render.MIN_BODY_FONT_PT
        plan['recommended_width_mm'] = label_render.RECOMMENDED_WIDTH_MM
        plan['recommended_height_mm'] = label_render.RECOMMENDED_HEIGHT_MM
        # 预览字号：按实际内容试算一次（不含字体渲染，只算排版）
        preview = self._lab_preview_font_sizes(spec, spec.ids)
        plan.update(preview)
        return plan

    @api.model
    def _lab_preview_font_sizes(self, spec, ids):
        """试算该标签尺寸+字段组合实际会用的字号（放不下则给 ready=False）。"""
        try:
            payloads = self._lab_label_payloads(spec, ids or [])
            contents = label_render.build_contents(spec, payloads)
        except (LabApiError, label_render.LabelSpecError) as error:
            return {'ready': False, 'blocking_reason': getattr(error, 'message', str(error))}
        if not contents:
            return {'ready': False, 'blocking_reason': '没有可打印的标签'}
        sample = contents[0]
        title_pt = max(label_render.MIN_TITLE_FONT_PT,
                       min(9.0, spec.height_mm / 3.2))
        body_pt = max(label_render.MIN_BODY_FONT_PT,
                      min(7.5, spec.height_mm / 4.6))
        body_text = '\n'.join(sample.lines)
        # 用不依赖字体的粗算：按字符数估算所需行数与高度
        width_chars = max(1, int((spec.width_mm * 0.45) / (body_pt * 0.35)))
        body_lines = sum(max(1, (len(line) + width_chars - 1) // width_chars)
                         for line in body_text.splitlines()) or 1
        title_lines = max(1, (len(sample.title) + width_chars - 1) // width_chars)
        line_mm = body_pt / label_render.MM_TO_PT * 1.30
        need_mm = (title_lines * (title_pt / label_render.MM_TO_PT * 1.25)
                   + body_lines * line_mm)
        have_mm = spec.height_mm - 2 * min(1.6, spec.height_mm * 0.08)
        return {
            'ready': True,
            'preview_title_pt': round(title_pt, 1),
            'preview_body_pt': round(body_pt, 1),
            'estimated_lines': title_lines + body_lines,
            'estimated_text_height_mm': round(need_mm, 1),
            'available_text_height_mm': round(have_mm, 1),
            'may_need_scaling': need_mm > have_mm,
        }

    @api.model
    def lab_labels_preview(self, kind='bag', ids=None, copies=1, width_mm=50, height_mm=30,
                           margin_mm=10, gap_mm=2, fields=None):
        """生成标签 PDF（base64）；全过程只读，不改任何库存。"""
        spec = self._lab_build_spec(kind, width_mm, height_mm, margin_mm, gap_mm,
                                    copies, fields)
        payloads = self._lab_label_payloads(spec, ids or [])
        try:
            contents = label_render.build_contents(spec, payloads)
        except label_render.LabelSpecError as error:
            raise LabApiError(error.message,
                              {error.field: 'invalid'} if error.field else {})
        if not contents:
            raise LabApiError.validation('没有可打印的标签', {'ids': 'empty'})
        try:
            pdf_bytes, meta = build_label_pdf(self.env, spec, contents)
        except LabelFontError as error:
            raise LabApiError(
                'PRECONDITION_FAILED',
                str(error),
                {'font': 'missing_cjk_font'})
        except LabelPdfError as error:
            raise LabApiError('VALIDATION_ERROR', str(error), {'layout': 'invalid'})
        except label_render.LabelSpecError as error:
            raise LabApiError(error.message,
                              {error.field: 'invalid'} if error.field else {})

        filename = 'labels_%s_%s.pdf' % (spec.kind, len(ids or []))
        return {
            'pdf_base64': base64.b64encode(pdf_bytes).decode('ascii'),
            'filename': filename,
            'page_count': meta['page_count'],
            'label_count': meta['label_count'],
            'mime_type': 'application/pdf',
            'font': meta['font_name'],
            'font_path': meta['font_path'],
            'width_mm': spec.width_mm,
            'height_mm': spec.height_mm,
            'margin_mm': spec.margin_mm,
            'gap_mm': spec.gap_mm,
            'copies': spec.copies,
            'fields': list(spec.fields),
            'qr_per_label': 1,
        }
