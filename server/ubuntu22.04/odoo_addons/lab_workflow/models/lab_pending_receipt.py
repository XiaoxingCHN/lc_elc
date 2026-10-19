"""Prepare labels without stock; only confirmation delegates to real receipt."""

import json

from odoo import api, fields, models
from odoo.exceptions import AccessError
from psycopg2 import errors as pg_errors

from ..tools import inventory_codec
from ..tools.label_parameters import key_parameters
from .lab_workflow_common import LabApiError, LabConcurrencyRetry, internal_only, in_internal_service


class LabTraceCode(models.Model):
    """One database uniqueness boundary for prepared AND direct-receipt codes."""
    _name = 'lab.trace.code'
    _description = '袋码唯一性登记'
    trace_code = fields.Char(required=True, index=True)
    pending_receipt_id = fields.Many2one('lab.pending.receipt', ondelete='restrict')
    _code_unique = models.Constraint('unique(trace_code)', '袋码已被使用。')

    def init(self):
        # Register historical identities during module installation/upgrade.
        self.env.cr.execute("SELECT to_regclass('lab_bag')")
        if self.env.cr.fetchone()[0]:
            self.env.cr.execute('''INSERT INTO lab_trace_code (trace_code)
                SELECT trace_code FROM lab_bag WHERE trace_code IS NOT NULL
                ON CONFLICT (trace_code) DO NOTHING''')

    @api.model_create_multi
    def create(self, vals_list):
        if not in_internal_service():
            raise AccessError('袋码只能由库存服务分配。')
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError('袋码登记不可改写。')

    def unlink(self):
        raise AccessError('袋码登记不可删除或重复使用。')

    def _lab_reserve(self, code, pending=None):
        existing = self.search([('trace_code', '=', code)], limit=1)
        if existing:
            if pending and existing.pending_receipt_id == pending:
                return
            raise LabApiError.conflict('该袋码已使用或预留，请使用原待入库记录。')
        try:
            with self.env.cr.savepoint():
                record = self.create({'trace_code': code,
                    'pending_receipt_id': pending.id if pending else False})
                record.flush_recordset()
        except pg_errors.UniqueViolation as error:
            raise LabConcurrencyRetry('并发袋码分配冲突，刷新事务重试。') from error


class LabPendingReceipt(models.Model):
    _name = 'lab.pending.receipt'
    _description = '待入库袋'
    _rec_name = 'trace_code'
    _order = 'id desc'

    trace_code = fields.Char(required=True, index=True, copy=False)
    company_id = fields.Many2one('res.company', required=True, index=True)
    owner_id = fields.Many2one('res.users', required=True, index=True)
    product_tmpl_id = fields.Many2one('product.template', required=True, ondelete='restrict')
    initial_quantity = fields.Float(required=True)
    quantity = fields.Float(required=True)
    note = fields.Text()
    selected = fields.Boolean(default=True)
    state = fields.Selection([('pending', '待入库'), ('done', '已入库'),
                              ('cancelled', '已取消')], default='pending', required=True)
    bag_id = fields.Many2one('lab.bag', ondelete='restrict')
    confirmed_by = fields.Many2one('res.users')
    confirmed_at = fields.Datetime()
    _trace_unique = models.Constraint('unique(trace_code)', '袋码不能重复。')

    @api.model_create_multi
    def create(self, vals_list):
        if not in_internal_service():
            raise AccessError('请通过待入库服务创建记录。')
        return super().create(vals_list)

    def write(self, vals):
        if not in_internal_service():
            raise AccessError('请通过待入库服务修改记录。')
        return super().write(vals)

    def unlink(self):
        raise AccessError('待入库记录保留追溯，请使用取消。')

    def _lab_pending_dict(self):
        self.ensure_one()
        template = self.product_tmpl_id
        return {
            'id': self.id, 'trace_code': self.trace_code,
            'payload': inventory_codec.build_bag_payload(self.trace_code),
            'state': self.state, 'selected': self.selected,
            'quantity': self.quantity, 'initial_quantity': self.initial_quantity,
            'product_template_id': template.id,
            'item_key': self.env['lab.workflow.common'].lab_item_key_for_template(template),
            'name': template.name, 'mpn': template.lab_mpn or '',
            'package': template.lab_package or '', 'sn': template.lab_sn or '',
            'parameters': template._lab_parse_specifications() if template.lab_specifications else [],
            'bag_id': self.bag_id.id or None, 'note': self.note or '',
        }

    def _lab_label_facts(self):
        self.ensure_one()
        if self.state == 'cancelled':
            raise LabApiError.precondition('已取消的袋不能打印标签。')
        if self.bag_id:
            facts = self.bag_id._lab_label_facts()
        else:
            template = self.product_tmpl_id
            facts = {
                **self._lab_pending_dict(), 'kind': 'pending', 'ref_id': self.id,
                'title': template.lab_mpn or template.name,
                'item_name': template.name, 'catalog_code': template.lab_lcsc_code or '',
                'brand': template.lab_brand or '',
            }
        facts['initial_quantity'] = self.initial_quantity
        facts['parameters'] = key_parameters(facts.get('parameters'))
        # Initial labels stay valid after shelving; location is intentionally absent.
        return facts


class LabPendingReceiptService(models.AbstractModel):
    _inherit = 'lab.workflow.common'

    def _lab_pending_record(self, pending_id, lock=False):
        try:
            record_id = int(pending_id)
        except (TypeError, ValueError):
            raise LabApiError.validation('请选择待入库袋。')
        record = self.env['lab.pending.receipt'].search([
            ('id', '=', record_id), ('owner_id', '=', self.env.uid),
            ('company_id', '=', self.env.company.id)], limit=1)
        if not record:
            raise LabApiError.not_found('待入库袋不存在或无权访问。')
        if lock:
            self.lab_sql_lock('lab_pending_receipt', 'id = %s', (record.id,))
            record.invalidate_recordset()
        return record

    @api.model
    @internal_only
    def lab_pending_list(self, cursor=None):
        domain = [('owner_id', '=', self.env.uid), ('company_id', '=', self.env.company.id)]
        if cursor:
            domain.append(('id', '<', int(cursor)))
        records = self.env['lab.pending.receipt'].search(domain, limit=101)
        page = records[:100]
        return {'records': [r._lab_pending_dict() for r in page],
                'cursor': page[-1].id if len(records) > 100 else None}

    @api.model
    @internal_only
    def lab_pending_create(self, params):
        return self.lab_run_with_concurrency_retry(lambda: self._lab_pending_create_once(params))

    def _lab_pending_create_once(self, params):
        key = self.lab_request_key(params)
        log, replay = self.lab_begin_request(key, 'pending.create', params)
        if replay:
            return replay
        with self.lab_savepoint():
            count = params.get('count', 1)
            if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 100:
                raise LabApiError.validation('每次可创建 1～100 袋。')
            if params.get('item_key'):
                template = self.lab_search_template(params.get('item_key'), create_if_missing=True,
                    origin='待入库', product_template_id=params.get('product_template_id'))
            else:
                material = params.get('material') or {}
                if not isinstance(material, dict) or not str(material.get('name') or '').strip():
                    raise LabApiError.validation('新建器件必须填写名称。')
                template = self.env['product.template'].sudo().create({
                    'name': str(material['name']).strip(), 'type': 'consu',
                    'company_id': self.env.company.id, 'purchase_ok': False, 'sale_ok': False,
                    'lab_mpn': str(material.get('mpn') or '').strip(),
                    'lab_package': str(material.get('package') or '').strip(),
                    'lab_brand': str(material.get('brand') or '').strip(),
                    'lab_specifications': json.dumps({'规格': str(material.get('specification') or '').strip()}, ensure_ascii=False),
                })
            quantity = self.lab_check_quantity(template.product_variant_id, params.get('quantity'))
            records = self.env['lab.pending.receipt'].sudo()
            for _ in range(count):
                code = self.env['lab.bag'].sudo()._lab_next_trace_code()
                records |= records.create({
                    'trace_code': code, 'owner_id': self.env.uid,
                    'company_id': self.env.company.id, 'product_tmpl_id': template.id,
                    'initial_quantity': quantity, 'quantity': quantity, 'note': params.get('note') or '',
                })
                self.env['lab.trace.code'].sudo()._lab_reserve(code, records[-1])
            data = {'records': [r._lab_pending_dict() for r in records]}
            self.lab_finish_request(log, data)
            return data

    @api.model
    @internal_only
    def lab_pending_update(self, params):
        return self.lab_run_with_concurrency_retry(lambda: self._lab_pending_update_once(params))

    def _lab_pending_update_once(self, params):
        with self.lab_savepoint():
            record = self._lab_pending_record(params.get('pending_id'), lock=True)
            action = params.get('action')
            if action == 'cancel':
                if record.state == 'done':
                    raise LabApiError.precondition('已入库记录不能取消，请走库存纠错流程。')
                record.sudo().write({'state': 'cancelled', 'selected': False})
            elif action == 'select':
                if record.state == 'cancelled':
                    raise LabApiError.precondition('已取消记录不能打印。')
                if not isinstance(params.get('selected'), bool):
                    raise LabApiError.validation('打印选择必须为布尔值。')
                record.sudo().write({'selected': params['selected']})
            else:
                raise LabApiError.validation('不支持的待入库操作。')
            return {'record': record._lab_pending_dict()}

    @api.model
    @internal_only
    def lab_pending_confirm(self, params):
        return self.lab_run_with_concurrency_retry(lambda: self._lab_pending_confirm_once(params))

    def _lab_pending_confirm_once(self, params):
        key = self.lab_request_key(params)
        log, replay = self.lab_begin_request(key, 'pending.confirm', params)
        if replay:
            return {**replay, 'replayed': True}
        with self.lab_savepoint():
            record = self._lab_pending_record(params.get('pending_id'), lock=True)
            if record.state == 'cancelled':
                raise LabApiError.precondition('该袋已取消，不能入库。')
            if record.state == 'done':
                data = {'record': record._lab_pending_dict(), 'replayed': True}
            else:
                quantity = self.lab_check_quantity(record.product_tmpl_id.product_variant_id,
                                                   params.get('quantity'))
                receipt, _ = self._lab_receipt_once({
                    'request_key': 'pending-stock-%s' % record.id,
                    'item_key': self.lab_item_key_for_template(record.product_tmpl_id),
                    'product_template_id': record.product_tmpl_id.id,
                    'trace_code': record.trace_code, 'quantity': quantity,
                    'location_id': params.get('location_id'), 'note': record.note or '',
                }, prepared=record)
                record.sudo().write({'state': 'done', 'selected': False, 'quantity': quantity,
                    'bag_id': receipt['bag']['id'], 'confirmed_by': self.env.uid,
                    'confirmed_at': fields.Datetime.now()})
                data = {**receipt, 'record': record._lab_pending_dict()}
            self.lab_finish_request(log, data)
            return data

    @api.model
    @internal_only
    def lab_pending_resolve(self, raw):
        parsed = inventory_codec.classify_scan(raw)
        if parsed['kind'] != inventory_codec.KIND_BAG:
            raise LabApiError.validation('请扫描本系统袋追溯码。')
        record = self.env['lab.pending.receipt'].search([
            ('trace_code', '=', parsed['normalized']), ('owner_id', '=', self.env.uid),
            ('company_id', '=', self.env.company.id)], limit=1)
        if not record:
            bag = self.lab_bag_by_trace_code(parsed['normalized'])
            return {'bag': bag._lab_bag_dict(), 'record': None, 'recommendations': []}
        template = record.product_tmpl_id
        templates = (self.lab_candidate_templates(template.lab_lcsc_code)
                     if template.lab_lcsc_code else template)
        # Same material first, then the same non-generic product category.
        bags = self.env['lab.bag'].search([
            ('company_id', '=', self.env.company.id),
            ('location_id.usage', '=', 'internal'), ('product_tmpl_id', 'in', templates.ids)])
        bags = bags.filtered(lambda bag: self.lab_bag_display_quantity(bag) > 0)
        locations = bags.mapped('location_id')
        recommendations = [{'id': loc.id, 'name': loc.display_name, 'reason': '相同器件'}
                           for loc in locations]
        if template.categ_id.parent_id:
            peers = self.env['lab.bag'].search([
                ('company_id', '=', self.env.company.id),
                ('location_id.usage', '=', 'internal'),
                ('product_tmpl_id.categ_id', '=', template.categ_id.id)], limit=200)
            peers = peers.filtered(lambda bag: self.lab_bag_display_quantity(bag) > 0)
            recommendations += [{'id': loc.id, 'name': loc.display_name, 'reason': '同类器件'}
                                for loc in peers.mapped('location_id') - locations]
        return {'record': record._lab_pending_dict(), 'recommendations': recommendations[:20]}
