# -*- coding: utf-8 -*-
"""Odoo 网页端入口：扫码操作台、袋/库位表单、标签预览与下载。

网页端与 JSON-RPC 走**同一套模型方法**，因此权限、幂等、行锁和原子性完全一致；
网页表单由服务端生成一次性 request_key（放在 hidden 表单里），
用户在页面上重复点击「提交」不会重复记账。

P3 变更（backend-contract §4）：

* ``GET /lab/scan`` 默认 **303 → 自有扫码页**（``/team/scan``）。判定顺序：
  参数 ``lab_workflow.scan_redirect``（``off`` 关闭 / 站内路径覆盖 / 默认
  ``/team/scan``）→ 目标路由真实存在。团队前端未安装或未升级时自动回退旧控制台，
  因此 ``lab_workflow`` 可独立运行，且**不依赖**“后加载路由覆盖”的隐式行为。
* ``/lab/scan/resolve``、``/lab/scan/submit`` 保留为内网过渡端点（deprecated），
  新页面一律用 JSON-RPC。
* 旧 ``/lab/labels/plan``、``/lab/labels/download`` 补 lab 角色 + operator 门槛，
  尺寸/批量边界前移，异常不再原样回显，并加 ``no-store``。
"""

import base64
import logging
import uuid

from odoo import http
from odoo.http import request
from werkzeug.utils import redirect

from ..models.lab_workflow_common import LabApiError
from ..tools import label_render, p3_rules
from .lab_api_common import require_group, require_lab_access

_logger = logging.getLogger(__name__)

OPERATOR_GROUP = 'lab_workflow.group_lab_operator'

_TEXT_ERROR_HEADERS = [('Content-Type', 'text/plain; charset=utf-8'),
                       ('Cache-Control', 'no-store'),
                       ('X-Content-Type-Options', 'nosniff')]


class LabWorkflowWeb(http.Controller):

    # ------------------------------------------------------------------
    # 扫码操作台
    # ------------------------------------------------------------------
    @http.route('/lab/scan', type='http', auth='user', website=False)
    def lab_scan_console(self, **kwargs):
        """旧控制台 / 迁移到自有扫码页的显式入口。"""
        target = self._scan_redirect_target()
        if target:
            # 303：浏览器改用 GET 打开新页面（不做 POST 重放）
            return redirect(target, code=303)
        try:
            require_lab_access()
        except LabApiError as error:
            return request.make_response(error.message, status=403,
                                         headers=_TEXT_ERROR_HEADERS)
        return request.render('lab_workflow.lab_scan_console', self._scan_values())

    def _scan_redirect_target(self):
        """返回要跳转的站内路径；``None`` 表示保留旧控制台。

        目标必须是**已注册**的路由：团队前端未安装/未升级时回退旧页，
        而不是把用户送到 404。参数值由 ``tools/p3_rules`` 做开放跳转校验。
        """
        try:
            param = request.env['ir.config_parameter'].sudo().get_param(
                p3_rules.SCAN_REDIRECT_PARAM, p3_rules.DEFAULT_SCAN_REDIRECT)
            candidate = p3_rules.scan_redirect_candidate(param)
        except Exception:  # noqa: BLE001 - 参数读取失败时保持旧行为
            _logger.warning('lab_workflow: 读取 %s 失败，保留旧扫码台',
                            p3_rules.SCAN_REDIRECT_PARAM, exc_info=True)
            return None
        if not candidate:
            return None
        # 路由匹配只看 path；query 由浏览器带去（`_match` 不接受查询串）
        candidate_path = candidate.split('?', 1)[0]
        if not self._route_available(candidate_path):
            return None
        # 防御自跳转（把参数误配成 /lab/scan 时不要形成 303 死循环）
        try:
            if candidate.rstrip('/') == request.httprequest.path.rstrip('/'):
                return None
        except Exception:  # noqa: BLE001
            return None
        return candidate

    def _route_available(self, path):
        """目标路径是否已注册（用 Odoo 自己的路由匹配，未知即不可用）。"""
        try:
            request.env['ir.http']._match(path)
            return True
        except Exception:  # noqa: BLE001 - NotFound 等一律视为未注册
            return False

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
        """扫码后返回解析结果（页面用 fetch 调用，返回信封 JSON）。

        deprecated：新页面走 ``/lab/api/inventory/resolve_code``，本端点仅内网过渡。
        """
        common = request.env['lab.workflow.common']
        try:
            require_lab_access()
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
                common.lab_error(LabApiError('INTERNAL_ERROR', '扫码解析失败')))

    @http.route('/lab/scan/submit', type='http', auth='user', csrf=True, website=False)
    def lab_scan_submit(self, action=None, **post):
        """扫码操作台的表单提交（与 JSON-RPC 走同一套模型方法）。

        deprecated：新页面走 ``/lab/api/inventory/{receipt,issue,return}``。
        """
        common = request.env['lab.workflow.common']
        action = (action or '').strip()
        message = ''
        error_message = ''
        payload = dict(post)
        payload.setdefault('request_key', str(uuid.uuid4()))
        try:
            require_lab_access()
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
            error_message = '操作失败并已回滚，请刷新后重试（详情见服务器日志）'

        return request.render('lab_workflow.lab_scan_console', self._scan_values(
            message=message, error_message=error_message))

    # ------------------------------------------------------------------
    # 标签（deprecated：新页面用 /lab/api/labels/plan + /lab/labels/pdf）
    # ------------------------------------------------------------------
    @http.route('/lab/labels/plan', type='http', auth='user', csrf=True, website=False)
    def lab_labels_plan(self, **post):
        """标签排版试算：返回每页能放几张、共几页（不改库存）。"""
        common = request.env['lab.workflow.common']
        try:
            require_lab_access()
            require_group(OPERATOR_GROUP, '当前账号没有标签排版权限')
            ids = _parse_ids(post.get('ids'))
            code = common.lab_int(post.get('copies'), 'copies', minimum=1,
                                  maximum=200, default=1)
            plan = common.lab_labels_plan(
                kind=post.get('kind') or 'bag',
                ids=ids,
                copies=code,
                width_mm=post.get('width_mm') or 50,
                height_mm=post.get('height_mm') or 30,
                margin_mm=post.get('margin_mm') or 10,
                gap_mm=post.get('gap_mm') or 2,
                fields=_parse_fields(post.get('fields')),
            )
            return request.make_json_response(common.lab_ok(plan))
        except LabApiError as error:
            return request.make_json_response(common.lab_error(error))
        except label_render.LabelSpecError as error:
            return request.make_json_response(
                common.lab_error(LabApiError('VALIDATION_ERROR', error.message,
                                             {error.field: 'invalid'} if error.field else {})))
        except Exception:  # noqa: BLE001
            error_id = uuid.uuid4().hex[:12]
            _logger.exception('标签试算失败 [error_id=%s]', error_id)
            return request.make_json_response(common.lab_error(
                LabApiError('INTERNAL_ERROR',
                            '标签试算失败，请把「错误编号 %s」提供给管理员' % error_id,
                            {'error_id': error_id})))

    @http.route('/lab/labels/download', type='http', auth='user', csrf=True, website=False)
    def lab_labels_download(self, **post):
        """直接下载标签 PDF（同一生成逻辑，只是不套 base64）。

        deprecated：新页面用 ``POST /lab/labels/pdf``。
        权限/边界/错误文案与 JSON-RPC 版一致，不再原样回显异常。
        """
        common = request.env['lab.workflow.common']
        try:
            require_lab_access()
            require_group(OPERATOR_GROUP, '当前账号没有生成标签的权限')
            data = common.lab_labels_preview(
                kind=post.get('kind') or 'bag',
                ids=_parse_ids(post.get('ids')),
                copies=post.get('copies') or 1,
                width_mm=post.get('width_mm') or 50,
                height_mm=post.get('height_mm') or 30,
                margin_mm=post.get('margin_mm') or 10,
                gap_mm=post.get('gap_mm') or 2,
                fields=_parse_fields(post.get('fields')),
            )
            pdf = base64.b64decode(data['pdf_base64'])
            filename = str(data.get('filename') or 'labels.pdf').replace('"', '')
            return request.make_response(pdf, headers=[
                ('Content-Type', 'application/pdf'),
                ('Content-Disposition', 'inline; filename="%s"' % filename),
                ('Content-Length', str(len(pdf))),
                ('Cache-Control', 'no-store'),
                ('X-Content-Type-Options', 'nosniff'),
            ])
        except LabApiError as error:
            request.env.cr.rollback()
            status = 403 if error.code in ('FORBIDDEN', 'UNAUTHORIZED') else 400
            return request.make_response(error.message, status=status,
                                         headers=_TEXT_ERROR_HEADERS)
        except Exception:  # noqa: BLE001
            error_id = uuid.uuid4().hex[:12]
            _logger.exception('标签 PDF 生成失败 [error_id=%s]', error_id)
            request.env.cr.rollback()
            return request.make_response(
                '标签 PDF 生成失败，请把「错误编号 %s」提供给管理员' % error_id,
                status=500, headers=_TEXT_ERROR_HEADERS)


def _parse_ids(raw):
    """把表单里的逗号串解析成 id 列表（真正的校验交给模型层）。"""
    if raw in (None, '', False):
        return []
    if isinstance(raw, str):
        return [chunk for chunk in raw.replace(' ', '').split(',') if chunk]
    return list(raw)


def _parse_fields(raw):
    if raw in (None, '', False):
        return None
    if isinstance(raw, str):
        return [chunk for chunk in raw.split(',') if chunk] or None
    return list(raw) or None


def _spec_from_post(post):
    """兼容旧调用：表单 -> LabelSpec（尺寸/份数已改为由模型层校验）。"""
    return label_render.LabelSpec(
        kind=post.get('kind') or 'bag',
        width_mm=float(post.get('width_mm') or 50),
        height_mm=float(post.get('height_mm') or 30),
        margin_mm=float(post.get('margin_mm') or 10),
        gap_mm=float(post.get('gap_mm') or 2),
        copies=int(post.get('copies') or 1),
        fields=_parse_fields(post.get('fields')),
        ids=_parse_ids(post.get('ids')) or [],
    )
