# -*- coding: utf-8 -*-
"""标签接口：排版试算 + PDF 生成（全程只读，不改库存）。

* ``POST /lab/api/labels/plan``：只算排版（每页几张、共几页），不生成 PDF
* ``POST /lab/api/labels/preview``：生成 A4 PDF，返回 ``pdf_base64``（契约一致）
* ``POST /lab/labels/pdf``：**浏览器直出 PDF**（表单 POST + CSRF），给自有页面用
  两个 JSON 接口都要求 lab 角色；普通用户只能给「自己有权看到的袋/库位」打印
"""

import base64
import logging
import uuid

from odoo import http
from odoo.http import request

from ..models.lab_workflow_common import LabApiError
from .lab_api_common import envelope, params, require_group, require_lab_access

_logger = logging.getLogger(__name__)

API = '/lab/api'
POST = ['POST']

OPERATOR_GROUP = 'lab_workflow.group_lab_operator'


class LabLabelsApi(http.Controller):

    @http.route(API + '/labels/plan', type='jsonrpc', auth='user',
                methods=POST, csrf=False)
    def lab_labels_plan(self, **kwargs):
        @envelope
        def handler():
            require_group(OPERATOR_GROUP, '当前账号没有标签排版权限')
            data = params()
            return request.env['lab.workflow.common'].lab_labels_plan(
                kind=data.get('kind') or 'bag',
                ids=data.get('ids') or [],
                copies=data.get('copies') or 1,
                width_mm=data.get('width_mm') or 50,
                height_mm=data.get('height_mm') or 30,
                margin_mm=data.get('margin_mm') or 10,
                gap_mm=data.get('gap_mm') or 2,
                fields=data.get('fields'),
            )
        return handler()

    @http.route(API + '/labels/preview', type='jsonrpc', auth='user',
                methods=POST, csrf=False)
    def lab_labels_preview(self, **kwargs):
        @envelope
        def handler():
            require_group(OPERATOR_GROUP, '当前账号没有生成标签的权限')
            data = params()
            return request.env['lab.workflow.common'].lab_labels_preview(
                kind=data.get('kind') or 'bag',
                ids=data.get('ids') or [],
                copies=data.get('copies') or 1,
                width_mm=data.get('width_mm') or 50,
                height_mm=data.get('height_mm') or 30,
                margin_mm=data.get('margin_mm') or 10,
                gap_mm=data.get('gap_mm') or 2,
                fields=data.get('fields'),
            )
        return handler()


class LabLabelsPdf(http.Controller):
    """``POST /lab/labels/pdf``：浏览器安全 PDF（表单 POST + CSRF，operator）。

    为什么单独一个 HTML 端点：``/lab/api/labels/preview`` 返回 base64，
    浏览器侧只能 blob/data URL 打开，而公网 CSP 不允许（无 frame-src）。
    这里服务端直出 ``application/pdf``，浏览器自己在新标签页展示/打印。

    * 只读：不改库存、不留缓存（``no-store``）
    * 边界在渲染前校验：ids ≤ 200、copies ≤ 200、尺寸/字段由 label_render 校验
    * 错误只回中文短句，不回 traceback/SQL/路径；内部错误给错误编号
    """

    @http.route('/lab/labels/pdf', type='http', auth='user', methods=['POST'],
                csrf=True, website=False)
    def labels_pdf(self, **post):
        common = request.env['lab.workflow.common']
        headers = [('Content-Type', 'text/plain; charset=utf-8'),
                   ('Cache-Control', 'no-store'),
                   ('X-Content-Type-Options', 'nosniff')]
        try:
            require_lab_access()
            require_group(OPERATOR_GROUP, '当前账号没有生成标签的权限')
            raw_ids = str(post.get('ids') or '')
            ids = [chunk for chunk in raw_ids.replace(' ', '').split(',') if chunk]
            fields = [chunk for chunk in str(post.get('fields') or '').split(',')
                      if chunk]
            data = common.lab_labels_preview(
                kind=post.get('kind') or 'bag',
                ids=ids,
                copies=post.get('copies') or 1,
                width_mm=post.get('width_mm') or 50,
                height_mm=post.get('height_mm') or 30,
                margin_mm=post.get('margin_mm') or 10,
                gap_mm=post.get('gap_mm') or 2,
                fields=fields or None,
            )
            pdf = base64.b64decode(data['pdf_base64'])
            filename = str(data.get('filename') or 'labels.pdf')
            filename = filename.replace('"', '').replace('\\', '').replace('\n', '')
            return request.make_response(pdf, headers=[
                ('Content-Type', 'application/pdf'),
                ('Content-Disposition', 'inline; filename="%s"' % filename),
                ('Content-Length', str(len(pdf))),
                ('Cache-Control', 'no-store'),
                ('X-Content-Type-Options', 'nosniff'),
            ])
        except LabApiError as error:
            status = {
                'FORBIDDEN': 403,
                'UNAUTHORIZED': 403,
                'NOT_FOUND': 404,
                'PRECONDITION_FAILED': 409,
                'CONFLICT': 409,
            }.get(error.code, 400)
            request.env.cr.rollback()
            return request.make_response(error.message, status=status, headers=headers)
        except Exception:  # noqa: BLE001 - 对外只给关联编号
            error_id = uuid.uuid4().hex[:12]
            _logger.exception('lab_workflow 标签 PDF 生成失败 [error_id=%s]', error_id)
            request.env.cr.rollback()
            return request.make_response(
                '标签 PDF 生成失败，请把「错误编号 %s」提供给管理员' % error_id,
                status=500, headers=headers)
