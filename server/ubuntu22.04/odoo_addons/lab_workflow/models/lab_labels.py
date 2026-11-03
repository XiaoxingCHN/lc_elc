# -*- coding: utf-8 -*-
"""lab.workflow.common 的标签方法：排版试算与 A4 PDF 生成（只读）。"""

import base64
import logging

from odoo import _, api, models

from ..tools import label_render, p3_rules
from ..tools.pdf_labels import LabelFontError, LabelPdfError, build_label_pdf
from .lab_workflow_common import LabApiError

_logger = logging.getLogger(__name__)


class LabWorkflowLabels(models.AbstractModel):
    _inherit = 'lab.workflow.common'

    # ------------------------------------------------------------------
    @api.model
    def _lab_label_ids(self, ids):
        """把 ids 规范化成正整数列表（数组或逗号分隔字符串都接受）。

        security-review S2/S4：旧实现直接 ``int(i)`` + ``browse().exists()``，
        畸形 id 会变成 INTERNAL_ERROR，跨公司 id 还能被打印出来。
        """
        if isinstance(ids, str):
            ids = [chunk for chunk in ids.replace(' ', '').split(',') if chunk]
        if ids in (None, '', False):
            raise LabApiError.validation('必须至少指定一个 id', {'ids': 'required'})
        if not isinstance(ids, (list, tuple)):
            raise LabApiError.validation('ids 必须是数组（或用逗号分隔的字符串）',
                                         {'ids': 'invalid'})
        out = []
        for value in ids:
            out.append(self.lab_int(value, 'ids', minimum=1))
        if len(out) > 200:
            raise LabApiError.validation('一次最多打印 200 个标签（可用份数放大）',
                                         {'ids': 'too_many'})
        return out

    @api.model
    def _lab_label_request(self, kind, ids, copies, width_mm, height_mm, margin_mm,
                           gap_mm, fields):
        """**三个标签出口（plan / preview / PDF）共享入口**：先校验，再排版/渲染。

        security-round2 S2-2：``ids ≤ 200`` 与 ``copies ≤ 200`` 分开校验不够——
        ``ids=200, copies=200`` 是 40000 张，任何 operator 都能把 worker 占满。
        因此这里在任何 ``build_contents``/``build_label_pdf`` 之前统一按
        ``ids × copies ≤ MAX_TOTAL_LABELS(200)`` 拦截；载荷读取也在其之后。
        """
        spec = self._lab_build_spec(kind, width_mm, height_mm, margin_mm, gap_mm,
                                    copies, fields)
        id_list = self._lab_label_ids(ids)
        try:
            p3_rules.label_bounds(len(id_list), spec.copies)
        except p3_rules.RuleError as error:
            raise LabApiError.validation(error.message, error.fields())
        return spec, id_list

    @api.model
    def _lab_build_spec(self, kind, width_mm, height_mm, margin_mm, gap_mm, copies, fields):
        spec = label_render.LabelSpec(
            kind=kind or label_render.KIND_BAG,
            width_mm=self.lab_float(width_mm, 'width_mm', default=50.0),
            height_mm=self.lab_float(height_mm, 'height_mm', default=30.0),
            margin_mm=self.lab_float(margin_mm, 'margin_mm', default=10.0),
            gap_mm=self.lab_float(gap_mm, 'gap_mm', default=2.0),
            copies=self.lab_int(copies, 'copies', minimum=1, maximum=200, default=1),
            fields=fields,
            ids=[],
        )
        try:
            label_render.validate_spec(spec)
        except label_render.LabelSpecError as error:
            raise LabApiError.validation(error.message,
                              {error.field: 'invalid'} if error.field else {})
        return spec

    @api.model
    def _lab_label_payloads(self, spec, ids):
        """取出待打印对象的只读事实；不存在的 id 明确报错。

        读路径一律用 ``search``（记录规则参与过滤），不再 ``browse().exists()``：
        跨公司 id 必须表现为 NOT_FOUND，而不是把别家的追溯码排进 PDF。
        """
        ids = self._lab_label_ids(ids)
        payloads = []
        if spec.kind == 'pending':
            self._lab_check_service_permission('lab_pending_list')
            records = [self._lab_pending_record(i) for i in ids]
            payloads = [record._lab_label_facts() for record in records]
        elif spec.kind == label_render.KIND_BAG:
            # 显式**当前公司**域：记录规则依 allowed_company_ids，多公司用户可能
            # 同时看到别家袋；契约要求按"当前活动公司"隔离（HTTP R2 test_05 暴露）。
            bags = self.env['lab.bag'].search([
                ('id', 'in', ids),
                ('company_id', '=', self.env.company.id),
            ])
            missing = sorted(set(ids) - set(bags.ids))
            if missing:
                raise LabApiError.not_found('袋不存在或无权访问：%s' % missing,
                                            {'ids': 'not_found'})
            for bag in bags:
                facts = bag._lab_label_facts()
                payloads.append(facts)
        else:
            # 库位：允许 company_id=False 的共享库位，其余必须是当前活动公司
            locations = self.env['stock.location'].search([
                ('id', 'in', ids), ('usage', '=', 'internal'),
                '|', ('company_id', '=', False),
                ('company_id', '=', self.env.company.id),
            ])
            missing = sorted(set(ids) - set(locations.ids))
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
        spec, id_list = self._lab_label_request(
            kind, ids, copies, width_mm, height_mm, margin_mm, gap_mm, fields)
        spec.ids = id_list
        count = len(id_list) * spec.copies
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
        """试算该标签尺寸+字段组合实际会用的字号（放不下则给 ready=False）。

        注意：**只有排版问题**才降级成 ``ready=False``；
        对象不存在/无权（NOT_FOUND/FORBIDDEN）必须原样抛出——否则
        ``labels/plan`` 会对跨公司 id 返回 ok=true（HTTP R2 test_05 的根因）。
        """
        try:
            payloads = self._lab_label_payloads(spec, ids or [])
            contents = label_render.build_contents(spec, payloads)
        except LabApiError as error:
            if error.code in ('NOT_FOUND', 'FORBIDDEN', 'UNAUTHORIZED'):
                raise
            return {'ready': False, 'blocking_reason': error.message}
        except label_render.LabelSpecError as error:
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
        spec, id_list = self._lab_label_request(
            kind, ids, copies, width_mm, height_mm, margin_mm, gap_mm, fields)
        payloads = self._lab_label_payloads(spec, id_list)
        try:
            contents = label_render.build_contents(spec, payloads)
        except label_render.LabelSpecError as error:
            raise LabApiError.validation(error.message,
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
            raise LabApiError.validation(error.message,
                              {error.field: 'invalid'} if error.field else {})

        filename = 'labels_%s_%s.pdf' % (spec.kind, len(payloads))
        return {
            'pdf_base64': base64.b64encode(pdf_bytes).decode('ascii'),
            'filename': filename,
            'page_count': meta['page_count'],
            'label_count': meta['label_count'],
            'mime_type': 'application/pdf',
            'font': meta['font_name'],
            # 刻意不返回 font_path：服务器绝对路径属于内部信息，
            # 公网 JSON 只保留字体名（诊断走日志）。
            'width_mm': spec.width_mm,
            'height_mm': spec.height_mm,
            'margin_mm': spec.margin_mm,
            'gap_mm': spec.gap_mm,
            'copies': spec.copies,
            'fields': list(spec.fields),
            'qr_per_label': 1,
        }
