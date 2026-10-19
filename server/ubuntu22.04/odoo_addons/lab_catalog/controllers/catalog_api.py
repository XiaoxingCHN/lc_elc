# -*- coding: utf-8 -*-
"""统一器件库接口（root 契约 business_api_contract.json v1.0 的 catalog 段）。

全部为 ``type='jsonrpc'`` + ``auth='user'``：与 /web/session/authenticate 同一会话 cookie。
数量一律来自 Odoo 原生 quant 实时聚合（见 lab.catalog.item._live_quant），
索引表只用于筛选、排序与分页稳定性。
"""
import json
import logging

from odoo import fields, http
from odoo.http import request

from .envelope import (AMBIGUOUS_MATERIAL, CONFLICT, NOT_FOUND, VALIDATION_ERROR,
                       LabApiError, api_route, as_int, require)


def _default_categ_id(env):
    """生产环境**真实存在**的默认产品分类 id。

    root 在独立生产 HTTP 验收中实测：全新 ``without_demo=all`` 的库里
    ``env.ref('product.product_category_all')`` 不存在，导致"第一个没有模板的
    C 编号建档"必报 External ID not found -> INTERNAL_ERROR。

    优先级（都不依赖 demo XMLID）：
      1) ``product.template.default_get(['categ_id'])`` —— 最贴近 Odoo 自身默认；
      2) 本模块 ``noupdate`` 持久化的 ``lab_catalog.categ_lab_catalog``（任何安装都有）；
      3) 库里任意已存在的分类；
      4) 都没有则返回 False，交给 ORM 自己的默认，**不硬造 XMLID 引用**。
    """
    try:
        val = env['product.template'].default_get(['categ_id']).get('categ_id')
        if val:
            return val
    except Exception as exc:
        _logger.warning('lab_catalog: default_get(categ_id) 失败：%s', exc)
    own = env.ref('lab_catalog.categ_lab_catalog', raise_if_not_found=False)
    if own:
        return own.id
    categ = env['product.category'].search([], limit=1)
    if categ:
        return categ.id
    _logger.warning('lab_catalog: 没有任何 product.category，将使用 ORM 默认')
    return False

_logger = logging.getLogger(__name__)

CATEGORY_LIMIT = 4000


class LabCatalogController(http.Controller):

    # ------------------------------------------------------------------ search
    @http.route('/lab/api/catalog/search', type='jsonrpc', auth='user', methods=['POST'])
    @api_route
    def catalog_search(self, params):
        limit = as_int(params.get('limit'), 'limit', default=50, minimum=1, maximum=200)
        parameters = params.get('parameters') or {}
        if not isinstance(parameters, dict):
            raise LabApiError(VALIDATION_ERROR, 'parameters 必须是「参数编码 -> 取值数组」的对象。',
                              {'parameters': 'not_an_object'})
        clean_params = {}
        for k, v in parameters.items():
            if isinstance(v, str):
                v = [v]
            if isinstance(v, (list, tuple)) and v:
                clean_params[str(k)] = [str(x) for x in v]

        brands = params.get('brands') or []
        packages = params.get('packages') or []
        items, next_cursor, total = request.env['lab.catalog.item'].search_unified(
            query=params.get('query') or '',
            category_id=params.get('category_id'),
            brands=[str(b) for b in brands] if isinstance(brands, (list, tuple)) else [],
            packages=[str(p) for p in packages] if isinstance(packages, (list, tuple)) else [],
            parameters=clean_params,
            stock_only=bool(params.get('stock_only')),
            cursor=params.get('cursor'),
            limit=limit,
        )
        model = request.env['lab.catalog.item']
        return {
            'items': items,
            'next_cursor': next_cursor,
            'total': total,
            'inventory_revision': model._revision('inventory'),
            'catalog_revision': model._revision('catalog'),
        }

    # ------------------------------------------------------------------ detail
    @http.route('/lab/api/catalog/detail', type='jsonrpc', auth='user', methods=['POST'])
    @api_route
    def catalog_detail(self, params):
        item_key = (params.get('item_key') or '').strip()
        require(item_key, 'item_key 不能为空。', {'item_key': 'required'})
        # 原样交给模型分派：lcsc:<code>（索引内或**仅有本地档案**）与 lab:<id> 都要查得到。
        # 早期实现先剥掉 lcsc: 前缀再按 C 码查，导致 lab:42 永远 404。
        data = request.env['lab.catalog.item'].detail(item_key)
        if not data:
            raise LabApiError(NOT_FOUND, '找不到器件「%s」。' % item_key,
                              {'item_key': 'not_found'})
        return data

    # ------------------------------------------------------------------ categories
    @http.route('/lab/api/catalog/categories', type='jsonrpc', auth='user', methods=['POST'])
    @api_route
    def catalog_categories(self, params):
        """分类树。外部 ID 语义统一为 **Odoo(PG) id**：
        id / category_id / parent_id 都是 PG id（前端点击后原样回传 search）；
        商城分类号另给 catalog_id；has_children 由 child_ids 计算（已加 depends）。
        """
        cats = request.env['lab.catalog.category'].search(
            [], order='level, sort, catalog_id', limit=CATEGORY_LIMIT)
        nodes = [{
            'id': c.id,
            'category_id': c.id,
            'catalog_id': c.catalog_id,
            'parent_id': c.parent_id.id or None,
            'parent_catalog_id': c.parent_id.catalog_id or None,
            'name': c.name,
            'name_en': c.name_en or '',
            'level': c.level,
            'sort': c.sort,
            'product_count': c.product_count,
            'has_children': c.has_children,
            'pg_path': c.pg_path or '',
        } for c in cats]
        return {'categories': nodes}

    # ------------------------------------------------------------------ facets
    @http.route('/lab/api/catalog/facets', type='jsonrpc', auth='user', methods=['POST'])
    @api_route
    def catalog_facets(self, params):
        """当前检索条件下**真实可选**的品牌/封装/参数值及计数。

        直接复用模型的 ``facets()``：与 ``search`` 共用同一个过滤构造器
        （分类用 PG 祖先路径、查询复用绑定 SN/名称逻辑），
        因此「筛选面板可选项」与「实际结果」不会不一致。
        参数按 param_code 分组返回 top values（不再是空列表）。
        """
        brands = params.get('brands') or []
        packages = params.get('packages') or []
        parameters = params.get('parameters') or {}
        if not isinstance(parameters, dict):
            raise LabApiError(VALIDATION_ERROR, 'parameters 必须是「参数编码 -> 取值数组」的对象。',
                              {'parameters': 'not_an_object'})
        clean_params = {}
        for k, v in parameters.items():
            if isinstance(v, str):
                v = [v]
            if isinstance(v, (list, tuple)) and v:
                clean_params[str(k)] = [str(x) for x in v]
        return request.env['lab.catalog.item'].facets(
            query=params.get('query') or '',
            category_id=params.get('category_id'),
            brands=[str(b) for b in brands] if isinstance(brands, (list, tuple)) else [],
            packages=[str(p) for p in packages] if isinstance(packages, (list, tuple)) else [],
            parameters=clean_params,
        )

    # ------------------------------------------------------------------ bind
    @http.route('/lab/api/catalog/bind', type='jsonrpc', auth='user', methods=['POST'])
    @api_route
    def catalog_bind(self, params):
        tid = as_int(params.get('product_template_id'), 'product_template_id',
                     minimum=1)
        code_raw = params.get('catalog_code')
        require(tid, 'product_template_id 不能为空。', {'product_template_id': 'required'})

        item_model = request.env['lab.catalog.item']
        code = item_model._norm(code_raw)
        if not code:
            raise LabApiError(
                VALIDATION_ERROR,
                '「%s」不是有效的 C 编号，已拒绝绑定。合法格式为 C 加十进制数字。' % (code_raw,),
                {'catalog_code': 'invalid'})
        item = item_model.search([('catalog_code', '=', code), ('market', '=', 'cn')], limit=1)
        if not item:
            raise LabApiError(NOT_FOUND, '资料库里没有「%s」，请先导入该器件。' % code,
                              {'catalog_code': 'not_in_catalog'})

        template = request.env['product.template'].browse(tid).exists()
        if not template:
            raise LabApiError(NOT_FOUND, '本地物料 %s 不存在。' % tid)

        Binding = request.env['lab.catalog.binding']
        existing = Binding.search([('catalog_code', '=', code),
                                   ('product_template_id', '=', tid)], limit=1)
        if not existing:
            Binding.create({'catalog_code': code, 'product_template_id': tid,
                            'source': 'manual'})
        # 同步写回物料上的立创编号，让 lab_inventory 的视图也能看到
        if not template.lab_lcsc_code_norm:
            template.lab_lcsc_code = code

        request.env['lab.catalog.item']._touch_inventory_revision()
        return {'item_key': 'lcsc:%s' % code, 'product_template_id': tid}

    # ------------------------------------------------------------------ create
    @http.route('/lab/api/catalog/create_material', type='jsonrpc', auth='user', methods=['POST'])
    @api_route
    def catalog_create_material(self, params):
        """按资料库器件建立/选取本地档案并绑定。

        契约要点：
        * **只建档案，不复制任何库存**；期初数量必须由 lab_workflow 的入库流程产生。
        * ``item_key`` **恒为 ``lcsc:<code>``**，绑定状态不改变身份。
        * 同一 C 编号已有多个档案时：
            - 传了 ``product_template_id`` -> 用它（校验归属该 C 编号且当前用户可见）；
            - 只有一个档案 -> 自动选它；
            - 多个且未选择 -> 返回 ``AMBIGUOUS_MATERIAL`` + ``candidates``，
              **绝不随机取 first**（否则会把袋错绑到别人的 SN 档案上）。
        """
        item_key = (params.get('item_key') or '').strip()
        require(item_key, 'item_key 不能为空。', {'item_key': 'required'})
        code = request.env['lab.catalog.item']._norm(
            item_key[5:] if item_key.startswith('lcsc:') else item_key)
        if not code:
            raise LabApiError(VALIDATION_ERROR, 'item_key 无效：%s' % item_key,
                              {'item_key': 'invalid'})

        item = request.env['lab.catalog.item'].search(
            [('catalog_code', '=', code), ('market', '=', 'cn')], limit=1)
        if not item:
            raise LabApiError(NOT_FOUND, '资料库里没有「%s」。' % code,
                              {'item_key': 'not_found'})

        Tmpl = request.env['product.template']
        # ORM 查询自动带记录规则 => 公司/权限过滤生效，取不到别人的档案
        templates = Tmpl.search([('lab_lcsc_code_norm', '=', code)])
        picked_id = params.get('product_template_id')

        def _bind_and_return(tmpl, reused):
            Binding = request.env['lab.catalog.binding']
            if not Binding.search([('catalog_code', '=', code),
                                   ('product_template_id', '=', tmpl.id)], limit=1):
                Binding.create({'catalog_code': code, 'product_template_id': tmpl.id,
                                'source': 'import'})
            request.env['lab.catalog.item']._touch_inventory_revision()
            return {
                'product_template_id': tmpl.id,
                'product_id': tmpl.product_variant_id.id,
                'sn': tmpl.lab_sn,
                'item_key': 'lcsc:%s' % code,      # 身份恒定不变
                'reused_existing': reused,
            }

        if templates:
            if picked_id:
                chosen = templates.filtered(lambda t: t.id == int(picked_id))
                if not chosen:
                    raise LabApiError(
                        VALIDATION_ERROR,
                        '指定的档案（id=%s）不属于 C 编号 %s，或你无权访问。' % (picked_id, code),
                        {'product_template_id': 'not_in_code',
                         'candidates': [{'product_template_id': t.id, 'sn': t.lab_sn,
                                         'name': t.name} for t in templates]})
                return _bind_and_return(chosen, True)
            if len(templates) == 1:
                return _bind_and_return(templates, True)
            raise LabApiError(
                AMBIGUOUS_MATERIAL,
                'C 编号 %s 下有 %d 个实验室档案，请选择要归属的 SN。' % (code, len(templates)),
                {'code': AMBIGUOUS_MATERIAL, 'item_key': 'lcsc:%s' % code,
                 'candidates': [{'product_template_id': t.id, 'sn': t.lab_sn,
                                 'name': t.name, 'quantity': 0.0} for t in templates]})

        specs = {}
        if item.param_ids:
            specs = {p.name: p.value for p in item.param_ids if p.name}
        vals = {
            'name': item.name or code,
            'lab_lcsc_code': code,
            'lab_mpn': item.mpn or False,
            'lab_brand': item.brand or False,
            'lab_package': item.package or False,
            'lab_datasheet_url': item.datasheet_url or False,
            'lab_source_url': item.source_url or False,
            'lab_specifications': json.dumps(specs, ensure_ascii=False) if specs else False,
            'type': 'consu',          # Odoo 19：物料类型字段是 type（不是 detailed_type）
            'is_storable': True,      # 开启库存跟踪，后续 receipt 才能建库存
        }
        # 生产环境真实存在的默认分类。
        # **不能**再 env.ref('product.product_category_all')：全新 without_demo=all
        # 的生产库里这个 XMLID 不存在，会让"第一个新 C 编号建档"直接 INTERNAL_ERROR。
        categ_id = _default_categ_id(request.env)
        if categ_id:
            vals['categ_id'] = categ_id
        # 不做 sudo：普通操作员是否可建档案取决于其角色是否合法授予了 product 权限，
        # 无权限时应当抛出真实的 AccessError（而不是被 sudo 掩盖）。
        Tmpl.check_access_rights('create')
        template = Tmpl.create(vals)
        request.env['lab.catalog.binding'].create(
            {'catalog_code': code, 'product_template_id': template.id, 'source': 'import'})
        request.env['lab.catalog.item']._touch_inventory_revision()
        return {
            'product_template_id': template.id,
            'product_id': template.product_variant_id.id,
            'sn': template.lab_sn,
            'item_key': 'lcsc:%s' % code,
            'reused_existing': False,
        }
