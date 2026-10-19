# -*- coding: utf-8 -*-
"""标签接口：排版试算 + PDF 生成（全程只读，不改库存）。

* ``POST /lab/api/labels/plan``：只算排版（每页几张、共几页），不生成 PDF
* ``POST /lab/api/labels/preview``：生成 A4 PDF，返回 ``pdf_base64``（契约一致）
* 两个接口都要求 lab 角色；普通用户只能给「自己有权看到的袋/库位」打印
"""

import logging

from odoo import http
from odoo.http import request

from .lab_api_common import envelope, params, require_group

_logger = logging.getLogger(__name__)

API = '/lab/api'
POST = ['POST']


class LabLabelsApi(http.Controller):

    @http.route(API + '/labels/plan', type='jsonrpc', auth='user',
                methods=POST, csrf=False)
    def lab_labels_plan(self, **kwargs):
        @envelope
        def handler():
            require_group('lab_workflow.group_lab_operator', '当前账号没有标签排版权限')
            data = params()
            return request.env['lab.workflow.common'].lab_labels_plan(
                kind=data.get('kind') or 'bag',
                ids=data.get('ids') or [],
                copies=int(data.get('copies') or 1),
                width_mm=float(data.get('width_mm') or 50),
                height_mm=float(data.get('height_mm') or 30),
                margin_mm=float(data.get('margin_mm') or 10),
                gap_mm=float(data.get('gap_mm') or 2),
                fields=data.get('fields'),
            )
        return handler()

    @http.route(API + '/labels/preview', type='jsonrpc', auth='user',
                methods=POST, csrf=False)
    def lab_labels_preview(self, **kwargs):
        @envelope
        def handler():
            require_group('lab_workflow.group_lab_operator', '当前账号没有生成标签的权限')
            data = params()
            return request.env['lab.workflow.common'].lab_labels_preview(
                kind=data.get('kind') or 'bag',
                ids=data.get('ids') or [],
                copies=int(data.get('copies') or 1),
                width_mm=float(data.get('width_mm') or 50),
                height_mm=float(data.get('height_mm') or 30),
                margin_mm=float(data.get('margin_mm') or 10),
                gap_mm=float(data.get('gap_mm') or 2),
                fields=data.get('fields'),
            )
        return handler()
