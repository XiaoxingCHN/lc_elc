# -*- coding: utf-8 -*-
"""标签打印向导：毫米输入 + 排版试算 + 生成 A4 PDF（只读，不改库存）。"""

import base64
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..tools import label_render

_logger = logging.getLogger(__name__)


class LabLabelWizard(models.TransientModel):
    _name = 'lab.label.wizard'
    _description = '实验室标签打印向导'

    kind = fields.Selection([('bag', '器件袋标签（含追溯二维码）'),
                             ('location', '库位标签（含库码二维码）')],
                            string='标签类型', required=True, default='bag')
    ids_text = fields.Char(
        string='对象 ID', required=True,
        help='袋或库位的 id，用逗号分隔，例如 12,15,18。'
             '从库存袋/库位列表选中记录后点「打印标签」会自动带入。')
    width_mm = fields.Float(string='标签宽 (mm)', default=60.0, required=True,
                            help='推荐 60mm；字段多或型号长时请加大，系统不会缩到看不清的字号')
    height_mm = fields.Float(string='标签高 (mm)', default=40.0, required=True,
                             help='推荐 40mm；文字放不下时会明确提示加大尺寸或减少字段')
    margin_mm = fields.Float(string='页边距 (mm)', default=10.0, required=True)
    gap_mm = fields.Float(string='标签间距 (mm)', default=2.0, required=True)
    copies = fields.Integer(string='每张份数', default=1, required=True)
    sn = fields.Boolean(string='SN', default=True)
    location = fields.Boolean(string='库码/库位', default=True)
    mpn = fields.Boolean(string='型号', default=True)
    catalog_code = fields.Boolean(string='C 编号', default=True)
    parameters = fields.Boolean(string='参数', default=True)
    quantity = fields.Boolean(string='数量', default=False)
    item_name = fields.Boolean(string='名称', default=False)
    trace_code = fields.Boolean(string='追溯码正文', default=False)
    supplier = fields.Boolean(string='来料信息', default=False)

    plan_text = fields.Text(string='排版试算结果', readonly=True)
    pdf = fields.Binary(string='标签 PDF', readonly=True)
    pdf_filename = fields.Char(string='文件名', readonly=True)
    label_count = fields.Integer(string='标签总数', readonly=True)
    page_count = fields.Integer(string='页数', readonly=True)

    # ------------------------------------------------------------------
    def _selected_fields(self):
        mapping = (
            ('sn', self.sn), ('location', self.location), ('mpn', self.mpn),
            ('catalog_code', self.catalog_code), ('parameters', self.parameters),
            ('quantity', self.quantity), ('item_name', self.item_name),
            ('trace_code', self.trace_code), ('supplier', self.supplier),
        )
        return [name for name, enabled in mapping if enabled]

    def _selected_label_ids(self):
        """解析用户输入的袋/库位 id。

        注意：方法**不能**叫 ``_ids`` —— 那是 Odoo ORM 的保留实例属性，
        自定义同名方法会在 registry 装配时抛
        ``AttributeError: 'lab.label.wizard' object attribute '_ids' is read-only``。
        """
        raw = (self.ids_text or '').replace('，', ',').replace(' ', '')
        ids = []
        for chunk in raw.split(','):
            if not chunk:
                continue
            if not chunk.isdigit():
                raise UserError(_('对象 ID 必须是数字，用逗号分隔；收到「%s」') % chunk)
            ids.append(int(chunk))
        if not ids:
            raise UserError(_('请填写至少一个袋或库位的 ID'))
        return ids

    def _call(self, method, **kwargs):
        common = self.env['lab.workflow.common']
        return getattr(common, method)(
            kind=self.kind,
            ids=self._selected_label_ids(),
            copies=self.copies,
            width_mm=self.width_mm,
            height_mm=self.height_mm,
            margin_mm=self.margin_mm,
            gap_mm=self.gap_mm,
            fields=self._selected_fields(),
            **kwargs)

    # ------------------------------------------------------------------
    def action_plan(self):
        """只算排版：每页几张、共几页、是否超界。"""
        self.ensure_one()
        from ..models.lab_workflow_common import LabApiError
        try:
            plan = self._call('lab_labels_plan')
        except LabApiError as error:
            raise UserError(error.message)
        self.plan_text = (
            '标签尺寸：%(width_mm)s × %(height_mm)s mm，页边距 %(margin_mm)s mm，'
            '间距 %(gap_mm)s mm\n'
            'A4 每页可放：%(cols)s 列 × %(rows)s 行 = %(labels_per_page)s 张\n'
            '本次共 %(label_count)s 张，需要 %(page_count)s 页\n'
            '可用区域：%(usable_width_mm)s × %(usable_height_mm)s mm\n'
            '字号红线：标题 ≥ %(min_title_pt)spt，正文 ≥ %(min_body_pt)spt；'
            '推荐尺寸 %(recommended_width_mm)s × %(recommended_height_mm)s mm\n'
            '%(font_hint)s'
            % dict(plan, font_hint=self._font_hint(plan)))
        self.label_count = plan['label_count']
        self.page_count = plan['page_count']
        return self._reopen()

    @staticmethod
    def _font_hint(plan):
        if not plan.get('ready'):
            return '排版试算：%s' % plan.get('blocking_reason', '无法试算')
        hint = ('预计 %(estimated_lines)s 行，需要约 %(estimated_text_height_mm)smm，'
                '可用 %(available_text_height_mm)smm' % plan)
        if plan.get('may_need_scaling'):
            hint += ' —— 会真实缩小字号（下限 6.5/5.5pt）；若被拒绝请加大标签或减少字段'
        else:
            hint += ' —— 按原始字号即可排下'
        return hint

    def action_generate(self):
        """生成 PDF 并留在向导里预览/下载。"""
        self.ensure_one()
        from ..models.lab_workflow_common import LabApiError
        try:
            data = self._call('lab_labels_preview')
        except LabApiError as error:
            raise UserError(error.message)
        self.pdf = data['pdf_base64']  # Binary 字段按 base64 赋值
        self.pdf_filename = data['filename']
        self.label_count = data['label_count']
        self.page_count = data['page_count']
        self.plan_text = (self.plan_text or '') + (
            '\n已生成：%(filename)s，%(_page)s 页，字体 %(font)s，约 %(kb)s KB'
            % {'filename': data['filename'], '_page': data['page_count'],
               'font': data.get('font') or '',
               'kb': max(1, len(data['pdf_base64']) * 3 // 4 // 1024)})
        return self._reopen()

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
