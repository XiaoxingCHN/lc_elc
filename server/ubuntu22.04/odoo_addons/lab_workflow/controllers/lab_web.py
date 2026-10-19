# -*- coding: utf-8 -*-
"""Odoo 网页端入口：扫码操作台、袋/库位表单、标签预览与下载。

网页端与 JSON-RPC 走**同一套模型方法**，因此权限、幂等、行锁和原子性完全一致；
网页表单由服务端生成一次性 request_key（放在 hidden 表单里），
用户在页面上重复点击「提交」不会重复记账。
"""

import base64
import logging
import uuid

from odoo import http
from odoo.http import request

from ..models.lab_workflow_common import LabApiError
from ..tools import label_render

_logger = logging.getLogger(__name__)


class LabWorkflowWeb(http.Controller):

    # ------------------------------------------------------------------
    # 扫码操作台
    # ------------------------------------------------------------------
    @http.route('/lab/scan', type='http', auth='user', website=False)
    def lab_scan_console(self, **kwargs):
        return request.render('lab_workflow.lab_scan_console', self._scan_values())

    def _scan_values(self, message='', error_message=''):
        common = request.env['lab.workflow.common']
        bootstrap = common.lab_bootstrap()
        open_issues = []
        if bootstrap['permissions'].get('can_return'):
            try:
                open_issues = common.lab_issues(
                    outstanding_only=True,
                    limit=50,
                    viewer_only_self=not common.lab_can_issue_for_others(),
                )['issues']
            except Exception as exc:  # noqa: BLE001 - 列表失败不影响操作台
                _logger.warning('lab_workflow 操作台读取未归还列表失败：%s', exc)
        return {
            'locations': bootstrap['locations'],
            'borrowers': bootstrap['borrowers'],
            'permissions': bootstrap['permissions'],
            'request_key': str(uuid.uuid4()),
            'uid': request.env.uid,
            'username': request.env.user.name,
            'open_issues': open_issues,
            'message': message,
            'error_message': error_message,
        }

    @http.route('/lab/scan/resolve', type='http', auth='user', csrf=True, website=False)
    def lab_scan_resolve(self, raw=None, **kwargs):
        """扫码后返回解析结果（页面用 fetch 调用，返回信封 JSON）。"""
        common = request.env['lab.workflow.common']
        try:
            if not raw:
                raise LabApiError.validation('请先扫码或输入编码', {'raw': 'required'})
            data = common.lab_resolve_code(raw)
            return request.make_json_response(common.lab_ok(data))
        except LabApiError as error:
            return request.make_json_response(common.lab_error(error))
        except Exception as exc:  # noqa: BLE001
            _logger.exception('lab_workflow 扫码解析失败：%s', exc)
            request.env.cr.rollback()
            return request.make_json_response(
                common.lab_error(LabApiError('INTERNAL_ERROR', '扫码解析失败：%s' % exc)))

    @http.route('/lab/scan/submit', type='http', auth='user', csrf=True, website=False)
    def lab_scan_submit(self, action=None, **post):
        """扫码操作台的表单提交：与 JSON-RPC 走同一套模型方法。"""
        common = request.env['lab.workflow.common']
        action = (action or '').strip()
        message = ''
        error_message = ''
        payload = dict(post)
        payload.setdefault('request_key', str(uuid.uuid4()))
        try:
            if action == 'receipt':
                data, _replayed = common.lab_receipt({
                    'request_key': payload['request_key'],
                    'item_key': payload.get('item_key'),
                    # 扫码/选择后带回来的确切档案（同 C 多档案时避免错绑）
                    'product_template_id': payload.get('product_template_id') or None,
                    'sn': payload.get('sn') or None,
                    'location_id': payload.get('location_id'),
                    'quantity': payload.get('quantity'),
                    'supplier_qr': payload.get('supplier_qr') or None,
                    'note': payload.get('note') or '',
                })
                message = '入库成功：%s（SN %s），袋 %s，数量 %s' % (
                    data['material']['name'], data['sn'] or '无',
                    data['bag']['trace_code'], data['bag']['quantity'])
            elif action == 'issue':
                borrower_id = payload.get('borrower_id')
                if not borrower_id:
                    raise LabApiError.validation('请选择领用人（系统账号）',
                                                 {'borrower_id': 'required'})
                data, _replayed = common.lab_issue({
                    'request_key': payload['request_key'],
                    'borrower_id': borrower_id,
                    'project': payload.get('project'),
                    'lines': [{'bag_id': payload.get('bag_id'),
                               'quantity': payload.get('quantity')}],
                    'note': payload.get('note') or '',
                })
                message = '领用成功：%s，领用单 %s' % (
                    data['operation']['borrower_name'], data['operation']['name'])
            elif action == 'return':
                data, _replayed = common.lab_return({
                    'request_key': payload['request_key'],
                    'issue_line_id': payload.get('issue_line_id'),
                    'quantity': payload.get('quantity'),
                    'note': payload.get('note') or '',
                })
                message = '归还成功：未归还数量 %s' % data['outstanding_quantity']
            else:
                raise LabApiError.validation('未知操作类型：%r' % (action,),
                                             {'action': 'unknown'})
        except LabApiError as error:
            error_message = error.message
        except Exception as exc:  # noqa: BLE001
            _logger.exception('lab_workflow 操作台提交失败：%s', exc)
            request.env.cr.rollback()
            error_message = '操作失败并已回滚：%s' % exc

        return request.render('lab_workflow.lab_scan_console', self._scan_values(
            message=message, error_message=error_message))

    # ------------------------------------------------------------------
    # 标签
    # ------------------------------------------------------------------
    @http.route('/lab/labels/plan', type='http', auth='user', csrf=True, website=False)
    def lab_labels_plan(self, **post):
        """标签排版试算：返回每页能放几张、共几页（不改库存）。"""
        common = request.env['lab.workflow.common']
        try:
            spec = _spec_from_post(post)
            plan = label_render.describe_plan(spec)
            return request.make_json_response(common.lab_ok(plan))
        except LabApiError as error:
            return request.make_json_response(common.lab_error(error))
        except label_render.LabelSpecError as error:
            return request.make_json_response(
                common.lab_error(LabApiError('VALIDATION_ERROR', error.message,
                                             {error.field: 'invalid'} if error.field else {})))
        except Exception as exc:  # noqa: BLE001
            _logger.exception('标签试算失败：%s', exc)
            return request.make_json_response(
                common.lab_error(LabApiError('INTERNAL_ERROR', '标签试算失败：%s' % exc)))

    @http.route('/lab/labels/download', type='http', auth='user', csrf=True, website=False)
    def lab_labels_download(self, **post):
        """直接下载标签 PDF（同一生成逻辑，只是不套 base64）。"""
        common = request.env['lab.workflow.common']
        try:
            data = common.lab_labels_preview(
                kind=post.get('kind') or 'bag',
                ids=[int(x) for x in (post.get('ids') or '').replace(' ', '').split(',') if x],
                copies=int(post.get('copies') or 1),
                width_mm=float(post.get('width_mm') or 50),
                height_mm=float(post.get('height_mm') or 30),
                margin_mm=float(post.get('margin_mm') or 10),
                gap_mm=float(post.get('gap_mm') or 2),
                fields=[f for f in (post.get('fields') or '').split(',') if f] or None,
            )
            pdf = base64.b64decode(data['pdf_base64'])
            return request.make_response(pdf, headers=[
                ('Content-Type', 'application/pdf'),
                ('Content-Disposition', 'inline; filename="%s"' % data['filename']),
                ('Content-Length', str(len(pdf))),
            ])
        except LabApiError as error:
            return request.make_response(error.message, status=400)
        except Exception as exc:  # noqa: BLE001
            _logger.exception('标签 PDF 生成失败：%s', exc)
            request.env.cr.rollback()
            return request.make_response('标签 PDF 生成失败并已回滚：%s' % exc, status=500)


def _spec_from_post(post):
    fields = post.get('fields')
    if isinstance(fields, str):
        fields = [item for item in fields.split(',') if item]
    ids = post.get('ids')
    if isinstance(ids, str):
        ids = [int(item) for item in ids.replace(' ', '').split(',') if item]
    return label_render.LabelSpec(
        kind=post.get('kind') or 'bag',
        width_mm=float(post.get('width_mm') or 50),
        height_mm=float(post.get('height_mm') or 30),
        margin_mm=float(post.get('margin_mm') or 10),
        gap_mm=float(post.get('gap_mm') or 2),
        copies=int(post.get('copies') or 1),
        fields=fields,
        ids=ids or [],
    )
