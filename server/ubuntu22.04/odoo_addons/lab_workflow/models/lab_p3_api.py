# -*- coding: utf-8 -*-
"""P3 窄接口的模型方法（袋查询、库位改/停用、类别映射、成员角色）。

设计约束（与 backend-contract.md 一致）：

* **不新造库存**：所有数量都来自 ``stock.quant`` / ``lab.bag._lab_bag_dict()``，
  本文件不写 stock.move、不改 quant。
* 写操作（库位/映射/成员）一律 ``@internal_only``：方法自身先过
  ``_lab_check_service_permission``（manager 门槛），因此即使被
  ``/web/dataset/call_kw`` 直接调用也不能绕过角色。
* 成员角色只允许三个库存组；任何系统组/目录组请求明确拒绝（
  ``p3_rules.normalize_role``），并保护"最后一名库存管理员"。
* 纯判定（边界/优先级/最后管理员）都在 ``tools/p3_rules.py``，可离线单测。
"""

import logging

from odoo import api, models
from odoo.exceptions import AccessError

from ..tools import inventory_codec, p3_rules
from .lab_workflow_common import LabApiError, internal_only

_logger = logging.getLogger(__name__)

LAB_MANAGER_GROUP = 'lab_workflow.group_lab_manager'
LAB_OPERATOR_GROUP = 'lab_workflow.group_lab_operator'
LAB_USER_GROUP = 'lab_workflow.group_lab_user'


class LabWorkflowP3Api(models.AbstractModel):
    _inherit = 'lab.workflow.common'

    # ==================================================================
    # 权限
    # ==================================================================
    @api.model
    def _lab_require_manager(self, action='该操作'):
        if self.env.su:
            return True
        if not self.env.user.has_group(LAB_MANAGER_GROUP):
            raise LabApiError.forbidden(
                '只有库存管理员可以%s；当前账号没有「实验室库存 / 管理员」组'
                % action, {'group': LAB_MANAGER_GROUP})
        return True

    @api.model
    def _lab_check_service_permission(self, method_name):
        super()._lab_check_service_permission(method_name)
        if self.env.su:
            return True
        if method_name in ('lab_location_update', 'lab_mapping_set',
                           'lab_mapping_remove', 'lab_member_set_role'):
            self._lab_require_manager('执行 %s' % method_name)
        return True

    @api.model
    def _lab_rule_error(self, error, code=None):
        """RuleError -> LabApiError；``code`` 只在需要区分业务码时指定。"""
        fields = error.fields()
        if code == 'PRECONDITION_FAILED':
            return LabApiError.precondition(error.message, fields)
        if code == 'FORBIDDEN':
            return LabApiError.forbidden(error.message, fields)
        return LabApiError.validation(error.message, fields)

    @api.model
    def _lab_page_bounds(self, limit=None, default=p3_rules.DEFAULT_LIMIT,
                         maximum=p3_rules.MAX_LIMIT):
        return p3_rules.clamp_limit(limit, default=default, maximum=maximum)

    # ==================================================================
    # 袋：分页列表 / 单袋详情
    # ==================================================================
    @api.model
    def _lab_templates_for_item_key(self, item_key):
        """把 item_key 解析成"要匹配的档案集合"（同 C 多档案全部包含）。"""
        key = (item_key or '').strip()
        lowered = key.lower()
        if lowered.startswith('lab:'):
            suffix = key.split(':', 1)[1].strip()
            if not suffix.isdigit() or int(suffix) <= 0:
                raise LabApiError.validation(
                    'item_key 非法：%r（lab: 后面应是本地物料 id）' % item_key,
                    {'item_key': 'invalid'})
            template = self.env['product.template'].browse(int(suffix)).exists()
            if not template:
                raise LabApiError.not_found('本地物料 #%s 不存在' % suffix,
                                            {'item_key': 'not_found'})
            return template
        code = inventory_codec.normalize_lcsc_code(
            key[5:] if lowered.startswith('lcsc:') else key)
        if not code:
            raise LabApiError.validation(
                'item_key 非法：%r（应为 lcsc:C123 或 lab:<id>）' % item_key,
                {'item_key': 'invalid'})
        templates = self.lab_candidate_templates(code)
        if not templates:
            raise LabApiError.not_found(
                '器件库中没有 C 编号 %s 的本地物料' % code, {'item_key': 'not_found'})
        return templates

    @api.model
    def lab_bags(self, query=None, item_key=None, location_id=None,
                 has_stock=True, outstanding_only=False, cursor=None, limit=None):
        """``/lab/api/inventory/bags``：袋分页（只读）。

        列表的数量过滤用袋上的缓存字段（性能），单袋详情用实时 quant。
        """
        try:
            page_limit = self._lab_page_bounds(limit)
            cursor_id = p3_rules.parse_cursor(cursor)
            query_text = p3_rules.parse_text(query, 'query', p3_rules.MAX_QUERY_LEN)
            only_stock = p3_rules.parse_bool(has_stock, True)
            only_outstanding = p3_rules.parse_bool(outstanding_only, False)
        except p3_rules.RuleError as error:
            raise self._lab_rule_error(error)

        domain = [('company_id', '=', self.env.company.id)]
        if location_id not in (None, '', False):
            # 过滤历史袋时允许已停用库位（停用前要求"无库存"，但仍可能有 0 库存的历史袋）
            location = self.lab_location_by_id(location_id, require_internal=False)
            domain.append(('location_id', 'child_of', location.id))
        if item_key:
            templates = self._lab_templates_for_item_key(item_key)
            if not templates:
                return {'bags': [], 'next_cursor': None}
            domain.append(('product_tmpl_id', 'in', templates.ids))
        if query_text:
            domain += ['|', '|', '|',
                       ('trace_code', 'ilike', query_text),
                       ('product_tmpl_id.name', 'ilike', query_text),
                       ('product_tmpl_id.lab_mpn', 'ilike', query_text),
                       ('product_tmpl_id.lab_lcsc_code', '=ilike', query_text)]
        if only_stock:
            domain.append(('quantity', '>', 0))
        outstanding_leaf = None
        if only_outstanding:
            # security-round2：不能用截断的 id 列表（旧实现取前 2000 条会漏未还），
            # 也不做 Python 逐袋计算；这里用 SQL 子查询，由数据库完成关联。
            outstanding_leaf = self._lab_outstanding_leaf()
            domain.append(outstanding_leaf)
        if cursor_id is not None:
            domain.append(('id', '<', int(cursor_id)))

        try:
            bags = self.env['lab.bag'].search(domain, limit=page_limit + 1,
                                              order='id desc')
        except (ValueError, KeyError):
            # 极端兼容：某个 Odoo 小版本不接受 inselect 时，退化为"一次关联查询"
            # （不设 limit、不做逐袋计算），绝不静默丢掉未归还的袋。
            if outstanding_leaf is None:
                raise
            _logger.warning('lab_workflow: inselect 不可用，改用一次性领用行查询过滤')
            domain = [leaf for leaf in domain if leaf != outstanding_leaf]
            domain.append(('id', 'in', self._lab_outstanding_bag_ids()))
            bags = self.env['lab.bag'].search(domain, limit=page_limit + 1,
                                              order='id desc')
        has_more = len(bags) > page_limit
        page = bags[:page_limit]
        return {
            'bags': [bag._lab_bag_dict() for bag in page],
            'next_cursor': str(page[-1].id) if (has_more and page) else None,
        }

    @api.model
    def _lab_outstanding_leaf(self):
        """仍有未归还的袋：SQL 子查询（无 2000 条截断、无 Python 逐袋计算）。"""
        return ('id', 'inselect', (
            'SELECT DISTINCT bag_id FROM lab_issue_line '
            'WHERE outstanding_quantity > 0 AND company_id = %s '
            'AND bag_id IS NOT NULL',
            (self.env.company.id,)))

    @api.model
    def _lab_outstanding_bag_ids(self):
        """兼容回退：一次查询未归还领用行拿袋 id（不设 limit，不逐袋算）。"""
        lines = self.env['lab.issue.line'].search([
            ('outstanding_quantity', '>', 0),
            ('company_id', '=', self.env.company.id),
        ])
        return sorted(set(lines.mapped('bag_id').ids))

    @api.model
    def _lab_open_issues_for_bag(self, bag, limit=50):
        lines = self.env['lab.issue.line'].search([
            ('bag_id', '=', bag.id),
            ('outstanding_quantity', '>', 0),
        ], limit=int(limit or 50), order='date desc, id desc')
        return [line._lab_issue_line_dict() for line in lines]

    @api.model
    def lab_bag_detail(self, bag_id=None, trace_code=None, history_limit=None,
                       issues_limit=None):
        """``/lab/api/inventory/bag``：单袋事实 + 未归还 + 最近流水（只读）。"""
        if bag_id not in (None, '', False):
            bag = self.lab_bag_by_id(bag_id)
        elif trace_code not in (None, '', False):
            bag = self.lab_bag_by_trace_code(trace_code)
        else:
            raise LabApiError.validation(
                '请提供 bag_id 或 trace_code（袋追溯码）',
                {'bag_id': 'required', 'trace_code': 'required'})
        if not bag.exists():
            raise LabApiError.not_found('袋不存在或无权访问', {'bag_id': 'not_found'})
        if bag.company_id and bag.company_id != self.env.company:
            raise LabApiError.forbidden('该袋属于其他公司，当前账号无权查看',
                                        {'bag_id': 'wrong_company'})

        history_limit = self._lab_page_bounds(history_limit, default=20, maximum=50)
        issues_limit = self._lab_page_bounds(issues_limit, default=50, maximum=100)
        history = self.lab_history(bag_id=bag.id, limit=history_limit)
        template = bag.product_tmpl_id

        data = {
            'bag': bag._lab_bag_dict(),
            'item': template._lab_item_dict() if template else None,
            'open_issues': self._lab_open_issues_for_bag(bag, limit=issues_limit),
            'history': history['operations'],
            'next_cursor': None,
            'label_facts': None,
        }
        # 只有能打印的账号才返回标签事实：只读用户拿不到可打印载荷
        if (self.env.su or self.env.user.has_group(LAB_OPERATOR_GROUP)
                or self.env.user.has_group(LAB_MANAGER_GROUP)):
            data['label_facts'] = bag._lab_label_facts()
        return data

    # ==================================================================
    # 库位：安全修改 / 停用
    # ==================================================================
    @api.model
    def _lab_location_stats_map(self, locations):
        """一次查询算多个库位的袋数/数量（供 locations?with_stats=1 用）。"""
        ids = list(locations.ids)
        stats = {loc_id: {'bag_count': 0, 'bag_quantity': 0.0, 'quantity': 0.0}
                 for loc_id in ids}
        if not ids:
            return stats
        bags = self.env['lab.bag'].search([('location_id', 'in', ids)])
        for bag in bags:
            slot = stats.get(bag.location_id.id)
            if slot is None:
                continue
            if abs(bag.quantity) > 1e-9:
                slot['bag_count'] += 1
            slot['bag_quantity'] += bag.quantity
        quants = self.env['stock.quant'].search([('location_id', 'in', ids)])
        for quant in quants:
            slot = stats.get(quant.location_id.id)
            if slot is not None:
                slot['quantity'] += quant.quantity
        return stats

    @api.model
    def _lab_location_stats(self, location, subtree=False):
        """库位袋数/袋内数量/在库数量；``subtree`` 时含子库位。"""
        Bag = self.env['lab.bag']
        domain = ([('location_id', 'child_of', location.id)] if subtree
                  else [('location_id', '=', location.id)])
        bags = Bag.search(domain)
        bag_count = len(bags.filtered(lambda bag: abs(bag.quantity) > 1e-9))
        bag_quantity = sum(bags.mapped('quantity'))
        quant_quantity = 0.0
        if location.usage == 'internal':
            quant_domain = ([('location_id', 'child_of', location.id)] if subtree
                            else [('location_id', '=', location.id)])
            quants = self.env['stock.quant'].search(quant_domain)
            quant_quantity = sum(quants.mapped('quantity'))
        return {
            'bag_count': bag_count,
            'bag_quantity': bag_quantity,
            'quantity': quant_quantity,
        }

    @api.model
    @internal_only
    def lab_location_update(self, location_id, name=None, note=None, active=None,
                            parent_id=None, update_parent=False):
        """``/lab/api/inventory/location_update``（manager）。

        只改展示/结构（名称、备注、启用、父级），不碰 usage、不改库存；
        停用前必须搬空（含子库位）。
        """
        try:
            location_id = p3_rules.parse_int(location_id, 'location_id',
                                             minimum=1, required=True)
            name_text = None
            if name is not None:
                name_text = p3_rules.parse_text(name, 'name', p3_rules.MAX_NAME_LEN)
                if not name_text:
                    raise p3_rules.RuleError('name', '库位名称不能为空', 'required')
            note_text = None
            if note is not None:
                note_text = p3_rules.parse_text(note, 'note', p3_rules.MAX_NOTE_LEN)
            set_active = None if active is None else p3_rules.parse_bool(active, True)
            wants_parent = p3_rules.parse_bool(update_parent, False)
            parent = None
            if wants_parent and parent_id not in (None, '', False):
                parent = self.env['stock.location'].browse(
                    p3_rules.parse_int(parent_id, 'parent_id', minimum=1)).exists()
                if not parent:
                    raise LabApiError.not_found('父库位不存在：%s' % parent_id,
                                                {'parent_id': 'not_found'})
        except p3_rules.RuleError as error:
            raise self._lab_rule_error(error)

        location = self.env['stock.location'].browse(int(location_id)).exists()
        if not location:
            raise LabApiError.not_found('库位不存在或无权访问：%s' % location_id,
                                        {'location_id': 'not_found'})
        company = self.env.company
        if location.company_id and location.company_id != company:
            raise LabApiError.forbidden('库位属于其他公司，当前账号无权修改',
                                        {'location_id': 'wrong_company'})
        if parent is not None:
            if parent.company_id and parent.company_id != company:
                raise LabApiError.forbidden('父库位属于其他公司，不能挂接',
                                            {'parent_id': 'wrong_company'})

        stats = self._lab_location_stats(location, subtree=True)
        parent_is_descendant = False
        if parent is not None:
            path = '/%s' % (parent.parent_path or '')
            parent_is_descendant = ('/%d/' % location.id) in path
        try:
            p3_rules.location_update_guard(
                usage=location.usage,
                is_root=not location.location_id,
                deactivating=(set_active is False),
                new_parent_id=(parent.id if (wants_parent and parent) else None),
                current_id=location.id,
                parent_is_self=bool(parent and parent.id == location.id),
                parent_is_descendant=parent_is_descendant,
                bag_count=stats['bag_count'],
                bag_quantity=stats['bag_quantity'],
                quant_quantity=stats['quantity'],
                parent_usage=(parent.usage if parent else None),
            )
        except p3_rules.RuleError as error:
            # 有库存不能停用 / 根库位 / 成环 = 业务前置失败（不是参数格式错误）
            raise self._lab_rule_error(error, 'PRECONDITION_FAILED')

        values = {}
        if name_text is not None:
            values['name'] = name_text
        if note_text is not None:
            values['lab_note'] = note_text
        if set_active is not None:
            values['active'] = set_active
        if wants_parent:
            values['location_id'] = parent.id if parent else False
        if values:
            try:
                location.write(values)
            except AccessError:
                raise LabApiError.forbidden(
                    '当前账号没有修改库位的库存权限，请联系系统管理员',
                    {'location_id': 'acl_denied'})
        return {
            'location': location._lab_location_dict(),
            'stats': self._lab_location_stats(location, subtree=False),
        }

    # ==================================================================
    # 类别→库位映射
    # ==================================================================
    @api.model
    def lab_mapping_list(self, category_id=None, include_inactive=False):
        """``/lab/api/inventory/mapping_list``（lab 角色，只读）。"""
        Mapping = self.env['lab.location.mapping']
        domain = [('company_id', '=', self.env.company.id)]
        try:
            if not p3_rules.parse_bool(include_inactive, False):
                domain.append(('active', '=', True))
            if category_id not in (None, '', False):
                domain.append(('category_id', '=', p3_rules.parse_int(
                    category_id, 'category_id', minimum=1)))
        except p3_rules.RuleError as error:
            raise self._lab_rule_error(error)
        mappings = Mapping.search(domain, limit=200)
        return {'mappings': [mapping._lab_mapping_dict() for mapping in mappings]}

    @api.model
    @internal_only
    def lab_mapping_set(self, category_id, location_id, priority=None, note=None,
                        active=None):
        """``/lab/api/inventory/mapping_set``（manager）：同类别+库位 upsert。"""
        try:
            category_id = p3_rules.parse_int(category_id, 'category_id',
                                             minimum=1, required=True)
            location_id = p3_rules.parse_int(location_id, 'location_id',
                                             minimum=1, required=True)
            priority_value = p3_rules.parse_int(
                priority, 'priority', minimum=p3_rules.MIN_PRIORITY,
                maximum=p3_rules.MAX_PRIORITY, default=p3_rules.DEFAULT_PRIORITY)
            note_text = p3_rules.parse_text(note, 'note', p3_rules.MAX_NOTE_LEN)
            # active 缺省 = 不改（新建时默认启用），避免"改优先级顺手把停用映射复活"
            active_value = None if active is None else p3_rules.parse_bool(active, True)
        except p3_rules.RuleError as error:
            raise self._lab_rule_error(error)

        category = self.env['product.category'].browse(int(category_id)).exists()
        if not category:
            raise LabApiError.not_found('器件类别不存在：%s' % category_id,
                                        {'category_id': 'not_found'})
        location = self.lab_location_by_id(location_id)  # 内部库位 + 公司校验 + 补库码

        Mapping = self.env['lab.location.mapping']
        existing = Mapping.search([
            ('category_id', '=', category.id),
            ('location_id', '=', location.id),
            ('company_id', '=', self.env.company.id),
        ], limit=1)
        values = {
            'priority': priority_value,
            'note': note_text or False,
        }
        if active_value is not None:
            values['active'] = active_value
        created = False
        if existing:
            existing.write(values)
            mapping = existing
        else:
            mapping = Mapping.create(dict(
                values, category_id=category.id, location_id=location.id,
                company_id=self.env.company.id,
                active=(True if active_value is None else active_value)))
            created = True
        _logger.info('lab_workflow 映射变更 actor=%s mapping=%s created=%s',
                     self.env.uid, mapping.id, created)
        return {'mapping': mapping._lab_mapping_dict(), 'created': created}

    @api.model
    @internal_only
    def lab_mapping_remove(self, mapping_id, hard=False):
        """``/lab/api/inventory/mapping_remove``（manager）：默认软停用。"""
        try:
            mapping_id = p3_rules.parse_int(mapping_id, 'mapping_id',
                                            minimum=1, required=True)
            hard_value = p3_rules.parse_bool(hard, False)
        except p3_rules.RuleError as error:
            raise self._lab_rule_error(error)
        mapping = self.env['lab.location.mapping'].browse(int(mapping_id)).exists()
        if not mapping:
            raise LabApiError.not_found('映射不存在：%s' % mapping_id,
                                        {'mapping_id': 'not_found'})
        if mapping.company_id != self.env.company:
            raise LabApiError.forbidden('该映射属于其他公司', {'mapping_id': 'wrong_company'})
        if hard_value:
            mapping.unlink()
            _logger.info('lab_workflow 映射物理删除 actor=%s mapping=%s',
                         self.env.uid, mapping_id)
            return {'mapping_id': int(mapping_id), 'removed': True, 'active': False}
        mapping.write({'active': False})
        _logger.info('lab_workflow 映射停用 actor=%s mapping=%s',
                     self.env.uid, mapping_id)
        return {'mapping_id': mapping.id, 'removed': False, 'active': bool(mapping.active)}

    # ==================================================================
    # 成员 / 库存角色
    # ==================================================================
    @api.model
    def _lab_user_group_field(self):
        """Odoo 19 的用户组字段是 ``group_ids``（旧版 ``groups_id``）。"""
        return 'group_ids' if 'group_ids' in self.env['res.users']._fields \
            else 'groups_id'

    @api.model
    def _lab_member_dict(self, user):
        # 管理端点的返回是"账号名 + 公司 + 角色位"，不含敏感字段；
        # 这里用 sudo 读取是为了避免"操作人恰好只能读自己"的 ACL/记录规则把
        # 整个接口变成 AccessError（R2 实测：撤销自己后读 res.users 被 ACL 拒）。
        user = user.sudo()
        company_ids = user.company_ids.ids
        return {
            'id': user.id,
            'name': user.name or '',
            'login': user.login or '',
            'active': bool(user.active),
            'is_self': user.id == self.env.uid,
            'company_id': user.company_id.id or None,
            # 库存组是**全局组**：角色变更会同时作用到该账号所属的每个公司，
            # UI 需要据此提示；多公司/全局账号只有系统管理员能改（见 set_role）。
            'company_ids': company_ids,
            'company_count': len(company_ids),
            'multi_company': len(company_ids) != 1,
            'roles': {
                'lab_user': user.has_group(LAB_USER_GROUP),
                'lab_operator': user.has_group(LAB_OPERATOR_GROUP),
                'lab_manager': user.has_group(LAB_MANAGER_GROUP),
            },
        }

    @api.model
    def _lab_company_users(self):
        company = self.env.company
        excluded = []
        for xmlid in ('base.public_user', 'base.user_root'):
            record = self.env.ref(xmlid, raise_if_not_found=False)
            if record:
                excluded.append(record.id)
        domain = [
            ('active', '=', True),
            ('share', '=', False),
            '|', ('company_ids', 'in', [company.id]), ('company_ids', '=', False),
        ]
        if excluded:
            domain.append(('id', 'not in', excluded))
        return self.env['res.users'].search(domain)

    @api.model
    def lab_members(self, query=None, only_with_role=False, cursor=None, limit=None):
        """``/lab/api/inventory/members``（manager）：本公司有效账号 + 库存角色位。"""
        self._lab_require_manager('查看成员与库存角色')
        try:
            page_limit = self._lab_page_bounds(limit, default=50)
            cursor_id = p3_rules.parse_cursor(cursor)
            query_text = p3_rules.parse_text(query, 'query', p3_rules.MAX_QUERY_LEN)
            only_roles = p3_rules.parse_bool(only_with_role, False)
        except p3_rules.RuleError as error:
            raise self._lab_rule_error(error)

        domain = [('id', 'in', self._lab_company_users().ids)]
        if query_text:
            domain += ['|', ('name', 'ilike', query_text), ('login', 'ilike', query_text)]
        if only_roles:
            group_ids = []
            for xmlid in (LAB_USER_GROUP, LAB_OPERATOR_GROUP, LAB_MANAGER_GROUP):
                group = self.env.ref(xmlid, raise_if_not_found=False)
                if group:
                    group_ids.append(group.id)
            domain.append((self._lab_user_group_field(), 'in', group_ids))
        if cursor_id is not None:
            domain.append(('id', '<', int(cursor_id)))

        users = self.env['res.users'].search(domain, limit=page_limit + 1, order='id desc')
        has_more = len(users) > page_limit
        page = users[:page_limit]
        return {
            'members': [self._lab_member_dict(user) for user in page],
            'next_cursor': str(page[-1].id) if (has_more and page) else None,
        }

    @api.model
    def _lab_manager_relation(self):
        """库存管理员组与用户的 m2m 关系表/列（取自字段元数据，避免硬编码）。"""
        Users = self.env['res.users']
        for name in (self._lab_user_group_field(), 'group_ids', 'groups_id'):
            field = Users._fields.get(name)
            if field is not None and getattr(field, 'relation', None):
                return field.relation, field.column1, field.column2
        return None

    @api.model
    def _lab_lock_manager_group(self):
        """锁定"库存管理员"成员行，串行化并发授予/撤销（RR 下的必要手段）。

        返回 ``[uid, …]``（锁定读看到的最新已提交集合）；元数据没有可用 m2m
        关系表时返回 ``None``，调用方退化为普通查询（并记 warning）。

        为什么 search 不够：REPEATABLE READ 里两个事务各自读到"还有另一个管理员"
        就都会放行，最后可能 0 管理员。这里用 ``SELECT … FOR UPDATE``：
        锁定读对**已删除的行**会做 EPQ 复检并把它过滤掉，返回的是最新已提交集合，
        因此后拿到锁的事务看不到已被并发删除的那一行，按"最后一名"拒绝。
        （新插入的行在 RR 快照里仍可能看不到 → 至多导致多拒一次，属安全方向。）
        """
        group = self.env.ref(LAB_MANAGER_GROUP, raise_if_not_found=False)
        if not group:
            return []
        relation = self._lab_manager_relation()
        if not relation:
            _logger.warning('lab_workflow: 找不到用户组 m2m 关系表，'
                            '管理员撤销无法串行化（仅普通查询）')
            return None
        table, col_user, col_group = relation
        self.env.cr.execute(
            'SELECT %s FROM %s WHERE %s = %%s FOR UPDATE'
            % (col_user, table, col_group), (group.id,))
        return [row[0] for row in self.env.cr.fetchall()]

    @api.model
    def _lab_manager_remaining_by_company(self, target):
        """撤销 target 的 manager 后，**它所属的每个公司**各剩多少 active manager。

        security-round2 S2-3：库存组是全局组，早先只按"操作人当前公司"统计，
        会出现"A 公司还有管理员 → 放行 → B 公司变成 0 管理员"的锁死。
        返回 ``(最少剩余数, [剩余为 0 的公司名])``；多公司账号取最小值即"任一公司为 0 就拒"。
        """
        group = self.env.ref(LAB_MANAGER_GROUP, raise_if_not_found=False)
        if not group:
            return 0, ['(缺少库存管理员组)']
        # 服务端管理动作：用 sudo 读取；并用**锁定读**拿最新的成员集合
        # （避免 RR 快照让并发撤销各自看到对方还在，见 _lab_lock_manager_group）。
        Users = self.env['res.users'].sudo()
        try:
            locked_uids = self._lab_lock_manager_group()
            if locked_uids is None:  # 退化路径（无 m2m 元数据）
                managers = Users.search([
                    ('active', '=', True), ('share', '=', False),
                    (self._lab_user_group_field(), 'in', [group.id]),
                ])
            else:
                managers = Users.browse(locked_uids).filtered(
                    lambda user: user.active and not user.share)
            target = target.sudo()
            # 全局账号（无 company_ids）在所有公司都生效 -> 逐公司检查全部公司
            target_companies = target.company_ids or self.env['res.company'].search([])
            remaining = []
            deficient = []
            for company in target_companies:
                in_company = managers.filtered(
                    lambda user: not user.company_ids or company in user.company_ids)
                left = len(in_company - target)
                remaining.append(left)
                if left <= 0:
                    deficient.append(company.display_name or company.name
                                     or str(company.id))
        except AccessError:  # noqa: PERF203 - 统计失败时按"最后管理员"处理（fail closed）
            _logger.warning('lab_workflow: 统计管理员失败，按最后管理员处理', exc_info=True)
            return 0, ['(统计失败)']
        if not remaining:
            return 0, []
        return min(remaining), deficient

    @api.model
    def _lab_is_system_admin(self):
        if self.env.su:
            return True
        return bool(self.env.user.has_group('base.group_system'))

    @api.model
    def _lab_target_role_change_allowed(self, target):
        """多公司/全局账号的角色变更保护（非系统管理员一律拒绝）。

        组是全局的：给"同时属于 A、B 公司"的账号加/减库存角色，会同时改动
        两个公司的权限。接口只在当前公司内操作，无法只影响一家，
        因此对非系统管理员**安全拒绝**，让他们走原生维护入口（系统管理员）。
        """
        company_ids = target.company_ids.ids
        if len(company_ids) == 1:
            return True
        if self._lab_is_system_admin():
            return True
        raise LabApiError.forbidden(
            '库存角色是全局权限：该账号属于 %s 个公司（或为全局账号），'
            '变更会同时影响其它公司。请由系统管理员在原生维护入口处理，'
            '或先把该账号限制为当前公司。' % (len(company_ids) or '全部'),
            {'user_id': 'multi_company'})

    @api.model
    @internal_only
    def lab_member_set_role(self, user_id, role, enabled):
        """``/lab/api/inventory/member_set_role``（manager）。

        只允许三个库存组；保护最后一名管理员；不提供任何系统组/目录组授权。

        并发边界（standalone concurrency R1 实测）：成员行的 ``FOR UPDATE``
        锁定读与组写入在 RR 下会撞 ``SerializationFailure``；这里复用与库存写
        完全相同的 ``lab_run_with_concurrency_retry``（整事务回滚 + 新快照重试），
        避免公开 JSON-RPC 把它吞成 ``INTERNAL_ERROR``。
        每次尝试都重新鉴权：若调用者在并发事务里已被撤销 manager，
        重试会返回 ``FORBIDDEN``（而不是继续用旧权限写）。
        """
        return self.lab_run_with_concurrency_retry(
            lambda: self._lab_member_set_role_once(user_id, role, enabled))

    @api.model
    def _lab_member_set_role_once(self, user_id, role, enabled):
        # 重试后必须重新鉴权：`@internal_only` 只在进入时校验过一次。
        self._lab_require_manager('执行 lab_member_set_role')
        try:
            role_key = p3_rules.normalize_role(role)
        except p3_rules.RuleError as error:
            # 请求了系统组/目录组：这是权限边界问题，不是参数格式问题
            raise self._lab_rule_error(error, 'FORBIDDEN')
        try:
            user_id = p3_rules.parse_int(user_id, 'user_id', minimum=1, required=True)
            if enabled is None or enabled == '':
                raise p3_rules.RuleError('enabled', '缺少 enabled（true=授予/false=撤销）',
                                         'required')
            enabled_value = p3_rules.parse_bool(enabled, None)
            if enabled_value is None:
                raise p3_rules.RuleError('enabled', 'enabled 必须是布尔值', 'invalid')
        except p3_rules.RuleError as error:
            raise self._lab_rule_error(error)

        # 管理端点已由 manager 门槛把关；这里用 sudo 取目标账号，
        # 避免"操作人只能读自己"的记录规则/ACL 让整个接口报 AccessError（R2 实测）。
        target = self.env['res.users'].sudo().browse(int(user_id)).exists()
        if not target:
            raise LabApiError.not_found('账号不存在：%s' % user_id, {'user_id': 'not_found'})
        if not target.active:
            raise LabApiError.precondition('账号「%s」已停用，不能变更角色' % target.name,
                                           {'user_id': 'inactive'})
        company = self.env.company
        if target.company_ids and company not in target.company_ids:
            raise LabApiError.forbidden('账号「%s」不属于当前公司' % target.name,
                                        {'user_id': 'wrong_company'})
        # security-round2 S2-3：多公司/全局账号的角色变更，非系统管理员安全拒绝
        self._lab_target_role_change_allowed(target)

        xmlid = p3_rules.group_xmlid_for_role(role_key)
        group = self.env.ref(xmlid, raise_if_not_found=False)
        if not group:
            raise LabApiError.precondition(
                '角色组 %s 不存在，模块可能未安装完整' % xmlid, {'role': 'group_missing'})
        has_role = target.has_group(xmlid)
        if role_key == 'lab_manager':
            # 授予/撤销都先锁同一批成员行：并发的两次撤销在这里排队，
            # 后到者拿到锁后看到的是"最新已提交"集合（见 _lab_lock_manager_group）。
            self._lab_lock_manager_group()

        if enabled_value and has_role:
            return {'member': self._lab_member_dict(target), 'changed': False}
        if (not enabled_value) and (not has_role):
            return {'member': self._lab_member_dict(target), 'changed': False}

        if not enabled_value:
            remaining, deficient = self._lab_manager_remaining_by_company(target)
            # fail-closed：撤销管理员时，只要"任一公司剩余 0"就直接拒绝，
            # 不依赖后续纯函数是否被未来的重构绕过。
            if role_key == 'lab_manager' and int(remaining or 0) <= 0:
                fields = {'role': 'last_manager'}
                if deficient:
                    fields['company'] = ', '.join(deficient)
                raise LabApiError.precondition(
                    '撤销后这些公司将没有任何库存管理员：%s。'
                    '请先为每个公司指定管理员，或由系统管理员在原生维护入口处理。'
                    % ('、'.join(deficient) or '当前公司'), fields)
            try:
                p3_rules.ensure_role_change_allowed(
                    role_key, False, has_role,
                    higher_roles={
                        'lab_user': target.has_group(LAB_USER_GROUP),
                        'lab_operator': target.has_group(LAB_OPERATOR_GROUP),
                        'lab_manager': target.has_group(LAB_MANAGER_GROUP),
                    },
                    remaining_managers=remaining)
            except p3_rules.RuleError as error:
                fields = error.fields()
                if error.reason == 'last_manager' and deficient:
                    # 指明是哪个公司会变成 0 管理员（多公司场景必须逐个公司保证）
                    fields['company'] = ', '.join(deficient)
                    raise LabApiError.precondition(
                        '撤销后这些公司将没有任何库存管理员：%s。'
                        '请先为每个公司指定管理员，或由系统管理员在原生维护入口处理。'
                        % '、'.join(deficient), fields)
                raise LabApiError.precondition(error.message, fields)

        # 只写库存组：这里用 sudo 是因为 res.users 写用户组属系统级 ACL，
        # 但"允许改哪个组"已由上面的管理器校验 + 角色白名单严格限定。
        field = self._lab_user_group_field()
        target.sudo().write({
            field: [(4, group.id)] if enabled_value else [(3, group.id)],
        })
        # 写完刷新缓存，"本次返回的 roles 位"必须是新的实际值
        target.invalidate_recordset(
            [name for name in ('group_ids', 'groups_id') if name in target._fields])
        _logger.info(
            'lab_workflow 库存角色变更 actor=%s target=%s role=%s enabled=%s company=%s',
            self.env.uid, target.id, role_key, enabled_value, company.id)
        return {'member': self._lab_member_dict(target), 'changed': True}
