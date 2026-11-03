# -*- coding: utf-8 -*-
"""P3 窄接口控制器：袋查询、库位改/停用、类别映射、成员库存角色。

与既有接口保持完全一致的约定：

* ``type='jsonrpc'`` + ``auth='user'`` + ``methods=['POST']`` + ``csrf=False``
* ``@envelope`` 负责统一信封、lab 角色门槛、异常 -> 中文 + 关联 ID
* 参数转换/边界校验在模型层（``lab.workflow.common.lab_int`` / ``p3_rules``），
  控制器只做"取参数 -> 调模型"，避免两套校验规则。
"""

import logging

from odoo import http
from odoo.http import request

from .lab_api_common import envelope, params

_logger = logging.getLogger(__name__)

API = '/lab/api'
POST = ['POST']


class LabP3Api(http.Controller):

    # ------------------------------------------------------------------
    # 袋：分页 / 详情（lab 角色，只读）
    # ------------------------------------------------------------------
    @http.route(API + '/inventory/bags', type='jsonrpc', auth='user',
                methods=POST, csrf=False)
    @envelope
    def inventory_bags(self, **kwargs):
        data = params()
        return request.env['lab.workflow.common'].lab_bags(
            query=data.get('query'),
            item_key=data.get('item_key'),
            location_id=data.get('location_id'),
            has_stock=data.get('has_stock', True),
            outstanding_only=data.get('outstanding_only', False),
            cursor=data.get('cursor'),
            limit=data.get('limit'),
        )

    @http.route(API + '/inventory/bag', type='jsonrpc', auth='user',
                methods=POST, csrf=False)
    @envelope
    def inventory_bag(self, **kwargs):
        data = params()
        return request.env['lab.workflow.common'].lab_bag_detail(
            bag_id=data.get('bag_id'),
            trace_code=data.get('trace_code'),
            history_limit=data.get('history_limit'),
            issues_limit=data.get('issues_limit'),
        )

    # ------------------------------------------------------------------
    # 库位：安全修改 / 停用（manager）
    # ------------------------------------------------------------------
    @http.route(API + '/inventory/location_update', type='jsonrpc', auth='user',
                methods=POST, csrf=False)
    @envelope
    def inventory_location_update(self, **kwargs):
        data = params()
        return request.env['lab.workflow.common'].lab_location_update(
            location_id=data.get('location_id'),
            name=data.get('name'),
            note=data.get('note'),
            active=data.get('active'),
            parent_id=data.get('parent_id'),
            update_parent=data.get('update_parent', False),
        )

    # ------------------------------------------------------------------
    # 类别 -> 库位映射（读: lab；写: manager）
    # ------------------------------------------------------------------
    @http.route(API + '/inventory/mapping_list', type='jsonrpc', auth='user',
                methods=POST, csrf=False)
    @envelope
    def inventory_mapping_list(self, **kwargs):
        data = params()
        return request.env['lab.workflow.common'].lab_mapping_list(
            category_id=data.get('category_id'),
            include_inactive=data.get('include_inactive', False),
        )

    @http.route(API + '/inventory/mapping_set', type='jsonrpc', auth='user',
                methods=POST, csrf=False)
    @envelope
    def inventory_mapping_set(self, **kwargs):
        data = params()
        return request.env['lab.workflow.common'].lab_mapping_set(
            category_id=data.get('category_id'),
            location_id=data.get('location_id'),
            priority=data.get('priority'),
            note=data.get('note'),
            active=data.get('active'),
        )

    @http.route(API + '/inventory/mapping_remove', type='jsonrpc', auth='user',
                methods=POST, csrf=False)
    @envelope
    def inventory_mapping_remove(self, **kwargs):
        data = params()
        return request.env['lab.workflow.common'].lab_mapping_remove(
            mapping_id=data.get('mapping_id'),
            hard=data.get('hard', False),
        )

    # ------------------------------------------------------------------
    # 成员 / 库存角色（manager）
    # ------------------------------------------------------------------
    @http.route(API + '/inventory/members', type='jsonrpc', auth='user',
                methods=POST, csrf=False)
    @envelope
    def inventory_members(self, **kwargs):
        data = params()
        return request.env['lab.workflow.common'].lab_members(
            query=data.get('query'),
            only_with_role=data.get('only_with_role', False),
            cursor=data.get('cursor'),
            limit=data.get('limit'),
        )

    @http.route(API + '/inventory/member_set_role', type='jsonrpc', auth='user',
                methods=POST, csrf=False)
    @envelope
    def inventory_member_set_role(self, **kwargs):
        data = params()
        return request.env['lab.workflow.common'].lab_member_set_role(
            user_id=data.get('user_id'),
            role=data.get('role'),
            enabled=data.get('enabled'),
        )
