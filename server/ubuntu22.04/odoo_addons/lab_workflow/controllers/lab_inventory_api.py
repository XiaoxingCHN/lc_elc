# -*- coding: utf-8 -*-
"""lab_workflow JSON-RPC 接口（与 lc_elc/docs/business_api_contract.json 一致）。

所有接口：

* HTTP **POST**，Content-Type: application/json（Odoo 19 ``type='jsonrpc'``）
* ``auth='user'`` + 显式 lab 角色校验：匿名和有账号但无 lab 权限都不能访问
* 操作人取 ``request.env.uid``，客户端传什么都不影响
* **直接返回普通 dict** ``{"ok":...,"data":...,"error":...}``：
  Odoo 的 ``JsonRPCDispatcher`` 会自动包成
  ``{"jsonrpc":"2.0","id":X,"result":{...}}``，与 Flutter ``OdooClient.callRoute`` 读取方式一致
"""

import logging

from odoo import http
from odoo.http import request

from .lab_api_common import envelope, params, require_group, require_lab_access

_logger = logging.getLogger(__name__)

API = '/lab/api'
POST = ['POST']


class LabPendingReceiptController(http.Controller):
    @http.route(API + '/inventory/pending/list', type='jsonrpc', auth='user', methods=POST, csrf=False)
    @envelope
    def pending_list(self, **kwargs):
        return request.env['lab.workflow.common'].lab_pending_list(params().get('cursor'))

    @http.route(API + '/inventory/pending/create', type='jsonrpc', auth='user', methods=POST, csrf=False)
    @envelope
    def pending_create(self, **kwargs):
        return request.env['lab.workflow.common'].lab_pending_create(params())

    @http.route(API + '/inventory/pending/update', type='jsonrpc', auth='user', methods=POST, csrf=False)
    @envelope
    def pending_update(self, **kwargs):
        return request.env['lab.workflow.common'].lab_pending_update(params())

    @http.route(API + '/inventory/pending/resolve', type='jsonrpc', auth='user', methods=POST, csrf=False)
    @envelope
    def pending_resolve(self, **kwargs):
        return request.env['lab.workflow.common'].lab_pending_resolve(params().get('raw') or '')

    @http.route(API + '/inventory/pending/confirm', type='jsonrpc', auth='user', methods=POST, csrf=False)
    @envelope
    def pending_confirm(self, **kwargs):
        return request.env['lab.workflow.common'].lab_pending_confirm(params())


class LabInventoryApi(http.Controller):

    # ------------------------------------------------------------------
    # 引导 / 库位
    # ------------------------------------------------------------------
    @http.route(API + '/inventory/bootstrap', type='jsonrpc', auth='user',
                methods=POST, csrf=False)
    def lab_bootstrap(self, **kwargs):
        @envelope
        def handler():
            return request.env['lab.workflow.common'].lab_bootstrap()
        return handler()

    @http.route(API + '/inventory/locations', type='jsonrpc', auth='user',
                methods=POST, csrf=False)
    def lab_locations(self, **kwargs):
        @envelope
        def handler():
            require_lab_access()
            return request.env['lab.workflow.common'].lab_locations()
        return handler()

    @http.route(API + '/inventory/location_create', type='jsonrpc', auth='user',
                methods=POST, csrf=False)
    def lab_location_create(self, **kwargs):
        @envelope
        def handler():
            require_group('lab_workflow.group_lab_manager',
                          '只有库存管理员可以新建库位')
            data = params()
            return request.env['lab.workflow.common'].lab_location_create(
                data.get('name'), data.get('parent_id'))
        return handler()

    # ------------------------------------------------------------------
    # 扫码解析
    # ------------------------------------------------------------------
    @http.route(API + '/inventory/resolve_code', type='jsonrpc', auth='user',
                methods=POST, csrf=False)
    def lab_resolve_code(self, **kwargs):
        @envelope
        def handler():
            data = params()
            return request.env['lab.workflow.common'].lab_resolve_code(data.get('raw'))
        return handler()

    # ------------------------------------------------------------------
    # 入库 / 领用 / 归还
    # ------------------------------------------------------------------
    @http.route(API + '/inventory/receipt', type='jsonrpc', auth='user',
                methods=POST, csrf=False)
    def lab_receipt(self, **kwargs):
        @envelope
        def handler():
            require_group('lab_workflow.group_lab_operator',
                          '当前账号没有入库权限，请联系库存管理员开通')
            data, replayed = request.env['lab.workflow.common'].lab_receipt(params())
            data['replayed'] = replayed
            return data
        return handler()

    @http.route(API + '/inventory/issue', type='jsonrpc', auth='user',
                methods=POST, csrf=False)
    def lab_issue(self, **kwargs):
        @envelope
        def handler():
            require_group('lab_workflow.group_lab_operator',
                          '当前账号没有领料权限，请联系库存管理员开通')
            data, replayed = request.env['lab.workflow.common'].lab_issue(params())
            data['replayed'] = replayed
            return data
        return handler()

    @http.route(API + '/inventory/return', type='jsonrpc', auth='user',
                methods=POST, csrf=False)
    def lab_return(self, **kwargs):
        @envelope
        def handler():
            require_group('lab_workflow.group_lab_operator',
                          '当前账号没有归还权限，请联系库存管理员开通')
            data, replayed = request.env['lab.workflow.common'].lab_return(params())
            data['replayed'] = replayed
            return data
        return handler()

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    @http.route(API + '/inventory/issues', type='jsonrpc', auth='user',
                methods=POST, csrf=False)
    def lab_issues(self, **kwargs):
        @envelope
        def handler():
            data = params()
            common = request.env['lab.workflow.common']
            viewer_only_self = not common.lab_can_issue_for_others()
            return common.lab_issues(
                query=data.get('query') or '',
                outstanding_only=bool(data.get('outstanding_only', True)),
                cursor=data.get('cursor'),
                limit=int(data.get('limit') or 50),
                viewer_only_self=viewer_only_self,
            )
        return handler()

    @http.route(API + '/inventory/history', type='jsonrpc', auth='user',
                methods=POST, csrf=False)
    def lab_history(self, **kwargs):
        @envelope
        def handler():
            data = params()
            return request.env['lab.workflow.common'].lab_history(
                item_key=data.get('item_key'),
                bag_id=data.get('bag_id'),
                cursor=data.get('cursor'),
                limit=int(data.get('limit') or 50),
            )
        return handler()

    # ------------------------------------------------------------------
    # 历史库存分袋适配（无批次正库存的安全路径）
    # ------------------------------------------------------------------
    @http.route(API + '/inventory/legacy_stock', type='jsonrpc', auth='user',
                methods=POST, csrf=False)
    def lab_legacy_stock(self, **kwargs):
        @envelope
        def handler():
            require_group('lab_workflow.group_lab_manager',
                          '只有库存管理员可以查看历史库存适配信息')
            data = params()
            return request.env['lab.workflow.common'].lab_legacy_stock_report(
                data.get('item_key'))
        return handler()

    @http.route(API + '/inventory/adopt_stock', type='jsonrpc', auth='user',
                methods=POST, csrf=False)
    def lab_adopt_stock(self, **kwargs):
        @envelope
        def handler():
            require_group('lab_workflow.group_lab_manager',
                          '只有库存管理员可以执行历史库存分袋适配')
            data = params()
            return request.env['lab.workflow.common'].lab_adopt_untracked_stock(
                item_key=data.get('item_key'),
                bags=data.get('bags') or [],
                note=data.get('note') or '',
            )
        return handler()
