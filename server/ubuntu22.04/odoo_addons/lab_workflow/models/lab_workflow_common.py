# -*- coding: utf-8 -*-
"""lab_workflow 公共基础设施。

集中放置三类被多个模型复用的能力：

1. **HTTP/JSON-RPC 信封**：与 lc_elc/docs/business_api_contract.json 完全一致的
   ``{"ok":bool,"data":{},"error":null|{code,message,fields}}``。
2. **幂等记账**：``request_key + user + company`` 唯一 + payload 指纹，重试返回原结果，
   同 key 不同 payload 明确拒绝。
3. **真实库存移动**：全部经 stock.move / stock.move.line / stock.quant，
   并用 ``SELECT ... FOR UPDATE`` 行锁 + UoM 精度校验阻止并发超领。
"""

import contextlib
import functools
import json
import logging
import math
import random
import threading
import time

from odoo import _, api, models
from odoo.exceptions import AccessError, UserError, ValidationError
from psycopg2 import errors as pg_errors

from ..tools import inventory_codec, request_keys

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# REPEATABLE READ 并发冲突重试
#
# Odoo 19 的每个游标都是 **REPEATABLE READ**
# （``odoo/sql_db.py``: ``Cursor.__init__`` ->
#  ``set_isolation_level(ISOLATION_LEVEL_REPEATABLE_READ)``）。
# 两个事务竞争同一行时，先提交者成功，后到者在
# ``SELECT ... FOR UPDATE`` / 唯一索引插入上收到
# ``SerializationFailure(40001)`` / ``UniqueViolation(23505)``；
# 只回 savepoint **不会刷新事务快照**，必须整事务回滚后重试。
#
# Odoo 核心对 ``call_kw`` 有同样的处理（``odoo/service/model.py``
# 的 ``retrying()``：回滚 + ``transaction.reset()`` + 指数退避重试，
# 最多 5 次）。本模块的 ``/lab/api`` 控制器直接调模型方法、不走
# call_kw，所以在这里补上同一层保护。
# ---------------------------------------------------------------------------
PG_CONCURRENCY_ERRORS = (
    pg_errors.SerializationFailure,   # 40001 并发更新冲突
    pg_errors.LockNotAvailable,       # 55P03 NOWAIT 取锁失败
    pg_errors.DeadlockDetected,       # 40P01 死锁检测
)
LAB_MAX_CONCURRENCY_TRIES = 5


class LabConcurrencyRetry(Exception):
    """内部信号：需要整事务回滚、用新快照重试（不对外暴露）。"""

# ---------------------------------------------------------------------------
# 服务端内部写入能力（**不可通过 RPC 伪造**）
#
# 为什么不用 context 里的布尔标志：客户端可以给 /web/dataset/call_kw
# 自带任意 context（context 是客户端可控数据），因此
# context['lab_workflow_internal']=True 不能作为权限边界。
# 这里用「进程内线程局部状态」：只有本模块自己的服务方法能进入，
# 任何来自 RPC 的调用都在别的调用栈上，读不到这个状态。
# ---------------------------------------------------------------------------
_LOCAL = threading.local()


def _set_internal(flag):
    _LOCAL.internal = bool(flag)


def in_internal_service():
    return bool(getattr(_LOCAL, 'internal', False))


@contextlib.contextmanager
def internal_service():
    """服务端业务方法内部上下文（进入时打开内部写入能力）。"""
    previous = getattr(_LOCAL, 'internal', False)
    _LOCAL.internal = True
    try:
        yield
    finally:
        _LOCAL.internal = previous


def internal_only(func):
    """标记公开的 ORM 服务方法：自带权限校验 + 打开内部写入能力。

    这些方法会出现在 ``/web/dataset/call_kw`` 里，所以**不能**依赖控制器
    guard：方法体第一件事就是调用模型自己的 ``_lab_check_service_permission``。
    """
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        self._lab_check_service_permission(func.__name__)
        with internal_service():
            return func(self, *args, **kwargs)
    return wrapper

# ---------------------------------------------------------------------------
# 错误码（契约 error_envelope.error.code）
# ---------------------------------------------------------------------------
CODE_VALIDATION = 'VALIDATION_ERROR'
CODE_UNAUTHORIZED = 'UNAUTHORIZED'
CODE_FORBIDDEN = 'FORBIDDEN'
CODE_NOT_FOUND = 'NOT_FOUND'
CODE_CONFLICT = 'CONFLICT'
CODE_PRECONDITION = 'PRECONDITION_FAILED'
CODE_DUPLICATE = 'DUPLICATE_REQUEST'
CODE_INTERNAL = 'INTERNAL_ERROR'

ALLOWED_FIELDS = ('sn', 'location', 'mpn', 'catalog_code', 'parameters',
                  'quantity', 'item_name', 'trace_code', 'supplier')


class LabApiError(Exception):
    """业务错误 -> 统一信封 error 字段。"""

    def __init__(self, code, message, fields=None):
        super().__init__(message)
        self.code = code or CODE_VALIDATION
        self.message = message or '操作失败'
        self.fields = fields or {}

    def as_error(self):
        return {'code': self.code, 'message': self.message, 'fields': self.fields}

    @classmethod
    def validation(cls, message, fields=None):
        return cls(CODE_VALIDATION, message, fields)

    @classmethod
    def not_found(cls, message, fields=None):
        return cls(CODE_NOT_FOUND, message, fields)

    @classmethod
    def forbidden(cls, message='当前账号无权执行该操作', fields=None):
        return cls(CODE_FORBIDDEN, message, fields)

    @classmethod
    def conflict(cls, message='请求冲突', fields=None):
        return cls(CODE_CONFLICT, message, fields)

    @classmethod
    def precondition(cls, message, fields=None):
        return cls(CODE_PRECONDITION, message, fields)


class LabWorkflowCommon(models.AbstractModel):
    """无表的公共方法集合（mixin）。"""

    _name = 'lab.workflow.common'
    _description = '实验室库存公共方法'

    # ------------------------------------------------------------------
    # 信封
    # ------------------------------------------------------------------
    @api.model
    def lab_ok(self, data=None):
        return {'ok': True, 'data': data if data is not None else {}, 'error': None}

    @api.model
    def lab_error(self, error):
        if isinstance(error, LabApiError):
            payload = error.as_error()
        elif isinstance(error, dict):
            payload = {
                'code': error.get('code') or CODE_INTERNAL,
                'message': error.get('message') or '操作失败',
                'fields': error.get('fields') or {},
            }
        else:
            payload = {'code': CODE_INTERNAL, 'message': str(error), 'fields': {}}
        return {'ok': False, 'data': None, 'error': payload}

    # ------------------------------------------------------------------
    # 服务边界：普通账号不能绕过接口改关键字段
    # ------------------------------------------------------------------
    @api.model
    def lab_internal_write(self):
        """是否处于「服务端业务方法」内部写入上下文。

        实现见本文件顶部的 ``_LOCAL``：这是**进程内线程局部状态**，
        不是 env.context，因此 ``/web/dataset/call_kw`` 无法伪造。
        """
        return in_internal_service()

    @api.model
    def lab_guard_fields(self, recordset, values, protected, action='修改'):
        """拦截对受保护字段的直接写入（中文可执行提示）。"""
        if in_internal_service():
            return
        touched = sorted(set(values or {}) & set(protected))
        if touched:
            raise AccessError(
                '不能直接%s%s的字段：%s。请通过扫码操作台/库存接口完成，'
                '这样操作人、领用人与库存移动才会被真实记录。'
                % (action, recordset._description or recordset._name, '、'.join(touched)))

    @api.model
    def lab_guard_create(self, model_name, action='新建'):
        if in_internal_service():
            return
        raise AccessError(
            '不能直接%s%s记录。请通过扫码操作台或 /lab/api 接口操作。'
            % (action, model_name))

    def _lab_save(self):
        """服务端已通过校验、准备写受保护字段时调用。

        真正的开关是 ``internal_service()``（进程内线程局部），
        这里只作为「这是服务端写入」的显式标注，不承担权限判断。
        """
        return in_internal_service()

    @api.model
    def lab_guard_unlink(self, recordset, action='删除'):
        raise UserError(_('%s不可删除：历史流水必须可追溯。如需纠正请做反向作业。') % action)

    @api.model
    def _lab_check_service_permission(self, method_name):
        """公开服务方法的**服务端权限校验**（控制器 guard 不算数）。

        子类覆盖以施加更严格的角色要求；这里给的是最低门槛。
        """
        if not self.env.uid:
            raise LabApiError(CODE_UNAUTHORIZED, '未登录，不能执行库存操作',
                              {'auth': 'anonymous'})
        user = self.env.user
        if user._is_public():
            raise LabApiError(CODE_UNAUTHORIZED, '公共用户不能执行库存操作',
                              {'auth': 'public'})
        if self.env.su:
            # 超级用户（system）本身就拥有全部权限：这里不额外要求 lab 角色，
            # 否则内部调用/自动化脚本会被自己的角色门槛挡住。
            return True
        if not (user.has_group('lab_workflow.group_lab_operator')
                or user.has_group('lab_workflow.group_lab_manager')):
            raise LabApiError.forbidden(
                '当前账号没有实验室库存操作权限，不能执行 %s' % method_name,
                {'group': 'lab_workflow.group_lab_operator'})
        return True

    # ------------------------------------------------------------------
    # 幂等 / 指纹
    # ------------------------------------------------------------------
    @api.model
    def lab_request_key(self, params):
        """取出并校验 request_key。"""
        raw = (params or {}).get('request_key')
        key = request_keys.normalize_request_key(raw)
        if not key:
            raise LabApiError.validation('缺少 request_key（客户端生成的唯一请求号）',
                                         {'request_key': 'required'})
        if not request_keys.is_valid_request_key(key):
            raise LabApiError.validation(
                'request_key 只能是 8~128 位的字母/数字/._:- ，收到长度 %d' % len(key),
                {'request_key': 'invalid'})
        return key

    @api.model
    def lab_fingerprint(self, params, method=None):
        """业务指纹：payload + 接口名。

        必须包含接口名，否则同一个 request_key 可以先用 receipt 再用 issue，
        指纹一致就被当成重试直接返回旧结果，把真正的领用吞掉。
        """
        payload = dict(params or {})
        if method:
            payload['__route'] = method
        return request_keys.fingerprint(payload)

    @api.model
    def lab_savepoint(self):
        """返回一个 savepoint 上下文管理器（逐层 SAVEPOINT）。"""
        return self.env.cr.savepoint()

    @api.model
    def lab_transaction_savepoint(self):
        """在「记账结果行已经写入」之后开始保存点：子事务回滚不影响请求行。"""
        return self.env.cr.savepoint()

    @api.model
    def lab_run_with_concurrency_retry(self, func):
        """RR 并发冲突标准重试（对齐 Odoo 核心 ``service.model.retrying``）。

        用法::

            return self.lab_run_with_concurrency_retry(
                lambda: self._lab_issue_once(params))

        * 捕获 ``SerializationFailure`` / ``LockNotAvailable`` /
          ``DeadlockDetected`` 与内部 :class:`LabConcurrencyRetry` 信号；
        * **整事务回滚**（``cr.rollback()``）后重试——RR 下只有新事务
          才有新快照，只回 savepoint 会带着旧快照再撞一次；
        * 清空 env 缓存（``transaction.reset()`` + 新 Environment），
          避免重试时读到本事务已回滚的陈旧 ORM 缓存；
        * 指数退避（0~2^try 秒，封顶 2 秒），最多 5 次；
        * 业务错误（LabApiError）**不重试**，直接抛给客户端。
        """
        last_error = None
        for tryno in range(1, LAB_MAX_CONCURRENCY_TRIES + 1):
            try:
                return func()
            except LabApiError:
                raise
            except LabConcurrencyRetry as exc:
                last_error = exc
            except PG_CONCURRENCY_ERRORS as exc:
                last_error = exc
            cr = self.env.cr
            if cr._closed:
                raise
            # 整事务回滚：下一条语句将拿到全新快照（RR 必需）
            cr.rollback()
            try:
                self.env.transaction.reset()
            except Exception:  # noqa: BLE001 - reset 失败不致命，换 env 即可
                pass
            _logger.info('lab_workflow 并发冲突，整事务回滚后第 %d/%d 次重试：%s: %s',
                         tryno, LAB_MAX_CONCURRENCY_TRIES,
                         type(last_error).__name__, last_error)
            if tryno < LAB_MAX_CONCURRENCY_TRIES:
                time.sleep(random.uniform(0.0, min(2.0 ** tryno, 2.0)))
        raise LabApiError.conflict(
            '系统正忙，本次操作多次重试仍未完成，请稍后重试',
            {'concurrency': 'retry_exhausted'})

    @api.model
    def lab_begin_request(self, request_key, method, params, operation_model=False):
        """登记一次请求；返回 (log_record, replay_payload)。

        * 首次：新建 pending 行并 flush（保证唯一约束立刻生效）
        * 重试且指纹一致：返回已保存结果（replay_payload 非空）
        * 同 key 不同 payload：抛 CONFLICT
        """
        # 记账属于**内部功能**：普通用户没有、也不应该有 lab.request.log 的写 ACL。
        # 这里统一走 sudo，写入内容全部来自 env.uid/env.company 与客户端 payload，
        # user_id/company_id 不允许外部传入，因此不能借它伪造别人的记账。
        RequestLog = self.env['lab.request.log'].sudo()
        company = self.env.company
        # 指纹包含接口名：同 key 跨 receipt/issue 视为不同请求，不能互相顶掉
        fingerprint = self.lab_fingerprint(params, method=method)

        # 关键：先对 (request_key,user,company) 加行锁，让同一 request_key 的
        # 并发请求在这里串行等待；否则两个事务会同时看到 pending 行各自继续执行。
        self.lab_sql_lock(
            'lab_request_log',
            'request_key = %s AND user_id = %s AND company_id = %s',
            (request_key, self.env.uid, company.id))

        existing = RequestLog.search([
            ('request_key', '=', request_key),
            ('user_id', '=', self.env.uid),
            ('company_id', '=', company.id),
        ], limit=1)
        if existing:
            if existing.payload_fingerprint != fingerprint:
                diff = request_keys.payload_diff_keys(existing.payload_json or {}, params or {})
                raise LabApiError(
                    CODE_CONFLICT,
                    'request_key %s 已经用于另一次内容不同的请求（差异字段：%s），已拒绝，'
                    '请换一个新的 request_key 重新提交'
                    % (request_key, '、'.join(diff) or '接口/内容不同'),
                    {'request_key': 'payload_mismatch', 'diff': diff})
            if existing.state == 'succeeded':
                return existing, existing.response_json or {}
            if existing.state in ('pending', 'failed'):
                # 上次未成功：允许复用该行重试（不重复创建，避免撞唯一约束）
                existing.write({
                    'state': 'pending',
                    'method': method,
                    'payload_json': params,
                    'payload_fingerprint': fingerprint,
                    'error_code': False,
                    'error_message': False,
                })
                return existing, None
            raise LabApiError.conflict('该 request_key 状态异常（%s），请换一个新的 request_key'
                                       % existing.state,
                                       {'request_key': existing.state})

        try:
            with self.env.cr.savepoint():
                log = RequestLog.create({
                    'request_key': request_key,
                    'user_id': self.env.uid,
                    'company_id': company.id,
                    'method': method,
                    'operation_model': operation_model or False,
                    # 存的 payload 必须与指纹用的是同一份规范化数据：
                    # NaN/Infinity 会被归一成 null，否则 PostgreSQL 的 jsonb 直接报错，
                    # 客户端就看不到「数量非法」的中文校验提示。
                    'payload_json': request_keys.canonicalize(params or {}),
                    'payload_fingerprint': fingerprint,
                    'state': 'pending',
                })
                # 立刻 flush 写入行，让唯一约束（含 request_key+method）当场生效
                log.flush_recordset(['request_key', 'user_id', 'company_id', 'method'])
        except Exception as exc:  # noqa: BLE001 - 唯一约束冲突 => 并发重复提交
            log = RequestLog.search([
                ('request_key', '=', request_key),
                ('user_id', '=', self.env.uid),
                ('company_id', '=', company.id),
            ], limit=1)
            if not log:
                # RR 下本事务快照早于并发事务的提交，savepoint 回滚也刷新不了
                # 快照，这里很可能「约束已生效但本事务看不到那一行」。
                # 发重试信号：整事务回滚后新快照就能看到，届时走正常
                # 重放/冲突分支（绝不重复记账）。
                if isinstance(exc, pg_errors.UniqueViolation):
                    raise LabConcurrencyRetry(
                        '并发重复提交：唯一约束生效但当前快照不可见，整事务重试')
                raise LabApiError.conflict(
                    '重复请求检测失败：数据库唯一约束生效但找不到记账行，请联系管理员',
                    {'request_key': 'race'})
            if log.payload_fingerprint != fingerprint:
                raise LabApiError(CODE_CONFLICT,
                                  '同一次 request_key 并发提交了不同内容（或不同接口），已拒绝其中一次',
                                  {'request_key': 'payload_mismatch'})
            if log.state == 'succeeded':
                return log, log.response_json or {}
            return log, None
        return log, None

    @api.model
    def lab_finish_request(self, log, data):
        log.sudo().write({
            'state': 'succeeded',
            'response_json': data or {},
            'error_code': False,
            'error_message': False,
        })
        return data

    @api.model
    def lab_fail_request(self, log, error):
        payload = error.as_error() if isinstance(error, LabApiError) else {
            'code': CODE_INTERNAL, 'message': str(error), 'fields': {}}
        log.sudo().write({
            'state': 'failed',
            'error_code': payload['code'],
            'error_message': payload['message'],
        })
        return payload

    # ------------------------------------------------------------------
    # 条目 / 库位 / 袋 解析
    # ------------------------------------------------------------------
    @api.model
    def lab_normalize_item_key(self, item_key):
        """把 item_key 规整为 ``lcsc:C123`` 或 ``lab:<id>``；非法返回 None。"""
        key = (item_key or '').strip()
        if not key:
            return None
        lowered = key.lower()
        if lowered.startswith('lcsc:'):
            code = inventory_codec.normalize_lcsc_code(key.split(':', 1)[1])
            return 'lcsc:%s' % code if code else None
        if lowered.startswith('lab:'):
            suffix = key.split(':', 1)[1].strip()
            if suffix.isdigit() and int(suffix) > 0:
                return 'lab:%d' % int(suffix)
            return None
        code = inventory_codec.normalize_lcsc_code(key)
        if code:
            return 'lcsc:%s' % code
        return None

    @api.model
    def lab_item_key_for_template(self, template):
        """物料对应的规范 item_key：优先 lcsc:Cxxx，否则 lab:<id>。"""
        code = inventory_codec.normalize_lcsc_code(
            getattr(template, 'lab_lcsc_code', False))
        if code:
            return 'lcsc:%s' % code
        return 'lab:%d' % template.id

    @api.model
    def lab_candidate_templates(self, catalog_code):
        """某个 C 编号下**当前账号可访问**的全部本地物料档案。"""
        code = inventory_codec.normalize_lcsc_code(catalog_code)
        if not code:
            return self.env['product.template']
        return self.env['product.template'].search(
            [('lab_lcsc_code', '=', code)], order='id')

    @api.model
    def lab_ambiguous_material_error(self, catalog_code, candidates):
        """同一 C 编号有多个本地档案且调用方没选：明确报错并给出候选。

        绝不能随机取 first —— 会把新袋错误绑定到别人的档案上。
        """
        rows = [{
            'product_template_id': template.id,
            'product_id': template.product_variant_id.id or None,
            'sn': template.lab_sn or None,
            'name': template.name,
            'mpn': template.lab_mpn or None,
            'package': template.lab_package or None,
            'tracking': template.tracking,
            'is_storable': template.is_storable,
        } for template in candidates]
        detail = '、'.join(
            '%s(#%d %s)' % (row['sn'] or row['name'], row['product_template_id'],
                            row['mpn'] or '无型号') for row in rows)
        return LabApiError(
            'AMBIGUOUS_MATERIAL',
            'C 编号 %s 在本地有 %d 个物料档案（%s）。请明确选择要归到哪一个 SN 档案，'
            '或在入库界面传入 product_template_id。' % (catalog_code, len(rows), detail),
            {'item_key': 'ambiguous', 'catalog_code': catalog_code,
             'candidates': rows})

    @api.model
    def lab_pick_template_for_catalog(self, catalog_code, product_template_id=None,
                                      create_if_missing=False, origin='api'):
        """为入库确定**唯一且明确**的物料档案。

        规则（root 一致性要求）：

        * 传了 ``product_template_id``（例如扫描某 SN 后客户端保留的模板 id）：
          校验存在、公司一致、且 C 编号与目标 canonical 一致 —— 否则报错，绝不改绑
        * 没传：该 C 编号只有一个档案 -> 自动选中；多个 -> ``AMBIGUOUS_MATERIAL``
        * 一个都没有：``create_if_missing`` 时才 on-demand 建最小档案
        """
        normalized = inventory_codec.normalize_lcsc_code(catalog_code)
        if not normalized:
            raise LabApiError.validation('catalog_code 非法：%r' % (catalog_code,),
                                        {'catalog_code': 'invalid'})
        Template = self.env['product.template']
        if product_template_id:
            template = Template.browse(int(product_template_id)).exists()
            if not template:
                raise LabApiError.not_found(
                    '传入的 product_template_id=%s 不存在或无权访问' % product_template_id,
                    {'product_template_id': 'not_found'})
            template_code = inventory_codec.normalize_lcsc_code(template.lab_lcsc_code)
            if template_code != normalized:
                raise LabApiError.precondition(
                    '传入的物料档案 #%s（SN %s，C 编号 %s）与本次入库的 C 编号 %s 不一致，'
                    '已拒绝以免把袋绑定到错误档案。'
                    % (template.id, template.lab_sn or template.name,
                       template_code or '无', normalized),
                    {'product_template_id': 'catalog_mismatch',
                     'expected': normalized, 'actual': template_code})
            company = self.env.company
            if template.company_id and template.company_id != company:
                raise LabApiError.forbidden(
                    '物料档案 #%s 属于其他公司，当前账号无权入库' % template.id,
                    {'product_template_id': 'wrong_company'})
            return template

        candidates = self.lab_candidate_templates(normalized)
        if len(candidates) == 1:
            return candidates
        if len(candidates) > 1:
            raise self.lab_ambiguous_material_error(normalized, candidates)
        if not create_if_missing:
            raise LabApiError.not_found(
                '器件库中没有 C 编号 %s 的本地物料，请先在统一器件库中创建物料'
                % normalized, {'item_key': 'not_bound'})
        can_create = (self.env.user.has_group('lab_workflow.group_lab_operator')
                      or self.env.user.has_group('lab_workflow.group_lab_manager'))
        if not can_create:
            self._lab_raise_no_create_right()
        return self._lab_create_minimal_material(normalized, origin)

    @api.model
    def lab_search_template(self, item_key, create_if_missing=False, origin='api',
                            product_template_id=None):
        """按 item_key 找 product.template（ACL 生效，不 sudo）。

        * ``lcsc:C123``：走 :meth:`lab_pick_template_for_catalog`（可能报 AMBIGUOUS_MATERIAL）
        * ``lab:<id>``：精确档案（本地物料 id），不允许现场创建
        * ``product_template_id``：客户端从扫码/选择结果里带来的确切档案，
          必须与该 C 编号一致（防止扫 SN 后被改绑到别的档案）
        """
        normalized = self.lab_normalize_item_key(item_key)
        if not normalized:
            raise LabApiError.validation('item_key 非法：%r（应为 lcsc:C123 或 lab:42）'
                                         % (item_key,), {'item_key': 'invalid'})
        Template = self.env['product.template']
        if normalized.startswith('lcsc:'):
            code = normalized.split(':', 1)[1]
            return self.lab_pick_template_for_catalog(
                code, product_template_id=product_template_id,
                create_if_missing=create_if_missing, origin=origin)
        template = Template.browse(int(normalized.split(':', 1)[1])).exists()
        if not template:
            raise LabApiError.not_found('物料不存在或无权访问：%s' % normalized,
                                        {'item_key': 'not_found'})
        if product_template_id and int(product_template_id) != template.id:
            raise LabApiError.validation(
                'item_key=%s 与 product_template_id=%s 不是同一个物料档案'
                % (normalized, product_template_id),
                {'product_template_id': 'conflict'})
        return template

    @api.model
    def _lab_raise_no_create_right(self):
        raise LabApiError.forbidden(
            '当前账号没有创建物料档案的权限，无法为该 C 编号现场建档；'
            '请联系库存管理员先在统一器件库中建立物料')

    @api.model
    def _lab_create_minimal_material(self, catalog_code, origin='receipt'):
        """为 lcsc:Cxxx 建一个最小可用物料档案（可被 lab_catalog 后续补全）。

        * 只写必要字段：名称、C 编号、可库存、批次跟踪
        * SN 由 lab_inventory 的 ``lab.component.sn`` 序列生成
        * 不伪造任何库存；库存仍然只能由真实入库移动产生
        """
        category = self.env.ref('product.product_category_all', raise_if_not_found=False)
        vals = {
            'name': '立创物料 %s（待补全）' % catalog_code,
            'type': 'consu',
            'is_storable': True,
            'tracking': 'lot',
            'lab_lcsc_code': catalog_code,
            'lab_description': '由 lab_workflow 在%s时自动建立的最小档案，'
                               '请到统一器件库补全型号/品牌/封装/参数。' % origin,
            'sale_ok': False,
            'purchase_ok': True,
        }
        if category:
            vals['categ_id'] = category.id
        # 建档属于系统内部维护动作：调用方已经在 @internal_only + 角色校验里把关，
        # 这里用 sudo 建最小档案，避免普通操作员必须拥有 product.template 建权限。
        template = self.env['product.template'].sudo().with_context(
            lab_workflow_autocreate=True).create(vals)
        _logger.warning('lab_workflow: 为 %s 自动建立最小物料档案 id=%s（待 lab_catalog 补全）',
                        catalog_code, template.id)
        return template

    @api.model
    def lab_location_by_id(self, location_id, require_internal=True):
        if not location_id:
            raise LabApiError.validation('缺少 location_id（库位）', {'location_id': 'required'})
        location = self.env['stock.location'].browse(int(location_id)).exists()
        if not location:
            raise LabApiError.not_found('库位不存在或无权访问：%s' % location_id,
                                        {'location_id': 'not_found'})
        if require_internal and location.usage != 'internal':
            raise LabApiError.validation(
                '库位「%s」类型是 %s，不是内部库位，不能存放库存'
                % (location.display_name, location.usage),
                {'location_id': 'not_internal'})
        company = self.env.company
        if location.company_id and location.company_id != company:
            raise LabApiError.forbidden('库位「%s」属于其他公司，当前账号无权使用'
                                        % location.display_name,
                                        {'location_id': 'wrong_company'})
        # 参与作业的内部库位必须有自己的库码（首次使用时自动补发，便于后续贴标签扫码）
        self._lab_ensure_location_code(location)
        return location

    @api.model
    def _lab_ensure_location_code(self, location):
        """给还没有库码的内部库位补一个（序列发号，幂等）。"""
        if not location or location.lab_code or location.usage != 'internal':
            return location
        code = self.env['stock.location']._lab_next_code()
        location.sudo().write({'lab_code': code})
        return location

    @api.model
    def lab_bag_by_id(self, bag_id):
        if not bag_id:
            raise LabApiError.validation('缺少 bag_id（袋）', {'bag_id': 'required'})
        bag = self.env['lab.bag'].browse(int(bag_id)).exists()
        if not bag:
            raise LabApiError.not_found('袋不存在或无权访问：%s' % bag_id, {'bag_id': 'not_found'})
        return bag

    @api.model
    def lab_bag_by_trace_code(self, trace_code):
        code = inventory_codec.normalize_trace_code(trace_code)
        if not code:
            raise LabApiError.validation('追溯码非法：%r' % (trace_code,),
                                         {'raw': 'invalid_trace_code'})
        bag = self.env['lab.bag'].search([('trace_code', '=', code)], limit=1)
        if not bag:
            raise LabApiError.not_found('没有找到追溯码 %s 对应的袋，可能尚未入库'
                                        % inventory_codec.build_bag_payload(code),
                                        {'raw': 'unknown_trace_code'})
        return bag

    @api.model
    def lab_location_by_code(self, location_code):
        code = inventory_codec.normalize_location_code(location_code)
        if not code:
            raise LabApiError.validation('库码非法：%r' % (location_code,),
                                         {'raw': 'invalid_location_code'})
        location = self.env['stock.location'].search([('lab_code', '=', code)], limit=1)
        if not location:
            raise LabApiError.not_found('没有找到库码 %s 的库位' % code,
                                        {'raw': 'unknown_location_code'})
        return location

    @api.model
    def lab_template_by_sn(self, sn):
        code = inventory_codec.normalize_sn(sn)
        if not code:
            raise LabApiError.validation('SN 非法：%r' % (sn,), {'raw': 'invalid_sn'})
        template = self.env['product.template'].search([('lab_sn', '=', code)], limit=1)
        if not template:
            raise LabApiError.not_found('没有找到 SN %s 对应的物料' % code,
                                        {'raw': 'unknown_sn'})
        return template

    # ------------------------------------------------------------------
    # 数量与精度
    # ------------------------------------------------------------------
    @api.model
    def lab_live_bag_quantity(self, bag_or_product, location_id=None, lot_id=None):
        """**实时**库存数量：以当前 product + lot + location 的 quant 为准。

        袋上那个存储的 ``quantity`` 只是缓存/展示用，不能当真值：
        原生 Odoo 的其他库存操作（盘点、调拨、报废、手工移动）都会改动 quant，
        不一定经过本模块的同步。因此：

        * 显示、可领用量校验、归还校验 一律走本方法
        * 只读用户查询也走本方法（不依赖写 bag.quantity）
        """
        if hasattr(bag_or_product, '_name') and bag_or_product._name == 'lab.bag':
            bag = bag_or_product
            product = bag.product_id
            location_id = bag.location_id.id
            lot_id = bag.lot_id.id
            uom = product.uom_id
        else:
            bag = None
            product = bag_or_product
            uom = product.uom_id
        quant = self.env['stock.quant']
        domain = [('product_id', '=', product.id)]
        if location_id:
            domain.append(('location_id', '=', location_id))
        else:
            domain.append(('location_id.usage', '=', 'internal'))
        domain.append(('lot_id', '=', lot_id) if lot_id else ('lot_id', '=', False))
        records = quant.search(domain)
        total = sum(records.mapped('quantity'))
        reserved = sum(records.mapped('reserved_quantity'))
        available = total - reserved
        if available < -1e-9:
            _logger.warning('实时库存为负：物料 %s 库位 %s 批次 %s => %s',
                            product.display_name, location_id, lot_id, total)
        return {
            'quantity': uom.round(total, rounding_method='HALF-UP'),
            'reserved_quantity': uom.round(reserved, rounding_method='HALF-UP'),
            'available_quantity': uom.round(max(0.0, available), rounding_method='HALF-UP'),
            'quant_ids': records.ids,
        }

    @api.model
    def lab_bag_display_quantity(self, bag):
        """袋的实时数量（展示/接口用，不写库）。"""
        return self.lab_live_bag_quantity(bag)['quantity']

    @api.model
    def lab_uom_round(self, product, quantity):
        uom = product.uom_id
        return uom.round(float(quantity), rounding_method='HALF-UP')

    @api.model
    def lab_check_quantity(self, product, quantity, field='quantity'):
        """校验数量为正、有限、且符合 UoM 精度；返回四舍五入后的数量。

        必须显式拒绝 ``NaN``/``Infinity``：``float('nan') <= 0`` 是 False，
        只判正数会让 NaN 一路写进 quant。
        """
        if isinstance(quantity, bool):
            raise LabApiError.validation('数量必须是数字，不能是布尔值 %r' % (quantity,),
                                         {field: 'not_a_number'})
        try:
            value = float(quantity)
        except (TypeError, ValueError):
            raise LabApiError.validation('数量必须是数字，收到 %r' % (quantity,),
                                         {field: 'not_a_number'})
        if math.isnan(value) or math.isinf(value):
            raise LabApiError.validation('数量必须是有限数字（不接受 NaN/Infinity），收到 %r'
                                         % (quantity,), {field: 'not_finite'})
        if value <= 0:
            raise LabApiError.validation('数量必须大于 0，收到 %s' % value, {field: 'not_positive'})
        if value > 1e9:
            raise LabApiError.validation('数量 %s 明显不合理（上限 1e9），请核对' % value,
                                         {field: 'too_large'})
        rounded = self.lab_uom_round(product, value)
        if abs(rounded - value) > 1e-9:
            digits = self.env['decimal.precision'].precision_get('Product Unit')
            uom_name = product.uom_id.display_name
            raise LabApiError.validation(
                '数量 %s 不符合物料单位「%s」的精度（小数点后最多 %d 位），请修正后重试'
                % (value, uom_name, digits),
                {field: 'precision'})
        if rounded <= 0:
            raise LabApiError.validation(
                '数量 %s 四舍五入到物料单位精度后为 %s，不能记账' % (value, rounded),
                {field: 'rounds_to_zero'})
        return rounded

    @api.model
    def lab_total_on_hand(self, product, domain_extra=None):
        """内部库位 real on-hand 合计（真实 quant，不用另一套计数器）。"""
        quant = self.env['stock.quant']
        domain = [('product_id', '=', product.id),
                  ('location_id.usage', '=', 'internal')]
        if domain_extra:
            domain += list(domain_extra)
        return sum(quant.search(domain).mapped('quantity'))

    @api.model
    def lab_sql_lock(self, table, where, params):
        """对业务行加 SQL 行锁（事务提交/回滚时释放）。

        这是**唯一**使用的原生 SQL，目的只是串行化并发扣减；
        真正的库存仍然只由 stock.move/quant 记录。
        """
        self.env.cr.execute(
            'SELECT id FROM %s WHERE %s FOR UPDATE' % (table, where), params)
        return [row[0] for row in self.env.cr.fetchall()]

    @api.model
    def lab_bag_key_share(self, bag_ids):
        """对袋行加 FOR KEY SHARE：与外键引用使用同一把锁。

        原因：领用/归还时我们会创建引用 ``bag_id`` 的子表记录，
        PostgreSQL 会对外键目标行取 ``KEY SHARE``。如果另一事务已经用
        ``FOR UPDATE``（或改写了袋的缓存数量）持有该行，两边就会互相等，
        形成真实的死锁。提前用同一强度的 KEY SHARE 占位，锁顺序就统一了。
        """
        bag_ids = tuple(sorted(int(i) for i in bag_ids if i))
        if not bag_ids:
            return []
        self.env.cr.execute(
            'SELECT id FROM lab_bag WHERE id IN %s FOR KEY SHARE', (bag_ids,))
        return [row[0] for row in self.env.cr.fetchall()]

    # ------------------------------------------------------------------
    # 库存修订号
    # ------------------------------------------------------------------
    @api.model
    def lab_inventory_revision(self):
        """库存修订号：任何真实库存变化都会改变它。

        实现要求（root 反馈）：

        * 只用 ORM + 当前账号**获准的公司**（``company_ids``），不越权读别家公司历史
        * 覆盖真实库存来源：``stock.quant``（完成移动后的实际数量）+ 袋 + 作业单
        * 稳定字符串，客户端可直接比较；lab_catalog 也可复用同一个方法，
          保证统一器件库与该接口的库存版本号一致
        """
        companies = self.env.companies
        if not companies:
            companies = self.env.company
        domain = [('company_id', 'in', companies.ids)]

        quants = self.env['stock.quant'].search(
            domain + [('location_id.usage', 'in', ('internal', 'transit'))])
        bags = self.env['lab.bag'].search(domain)
        operations = self.env['lab.operation'].search(domain)
        return 'q%d.%d-b%d.%d-o%d.%d' % (
            max(quants.ids) if quants else 0, len(quants),
            max(bags.ids) if bags else 0, len(bags),
            max(operations.ids) if operations else 0, len(operations),
        )

    @api.model
    def lab_inventory_revision_for_templates(self, templates):
        """按物料清单给出库存修订号（统一卡片/目录接口用）。"""
        revision = self.lab_inventory_revision()
        return {template.id: revision for template in templates}

    # ------------------------------------------------------------------
    # 权限
    # ------------------------------------------------------------------
    @api.model
    def lab_user_is(self, group_xmlid):
        return self.env.user.has_group(group_xmlid)

    @api.model
    def lab_can_issue_for_others(self):
        """能否代他人领料：必须是库存管理员/经理。"""
        return (self.env.user.has_group('lab_workflow.group_lab_manager')
                or self.env.user.has_group('stock.group_stock_manager'))

    @api.model
    def lab_authorized_borrowers(self):
        """bootstrap.borrowers：当前操作员获准选择的**有效系统账号**。

        * 普通自助领料：只返回本人（不允许自由姓名、不允许冒用他人）
        * 库存管理员：返回同公司所有内部有效用户
        """
        Users = self.env['res.users'].with_context(active_test=False)
        if not self.lab_can_issue_for_others():
            return Users.browse(self.env.uid)
        domain = [
            ('active', '=', True),
            ('share', '=', False),
        ]
        users = Users.search(domain)
        company = self.env.company
        allowed = users.filtered(
            lambda u: not u.company_ids or company in u.company_ids)
        return allowed.sorted(lambda u: (u.name or '').lower())

    @api.model
    def lab_check_borrower(self, borrower_id):
        """领用人必须从授权列表中选出；普通用户只能是本人。"""
        if not borrower_id:
            raise LabApiError.validation(
                '必须选择领用人（已建立的系统账号），不支持只填姓名',
                {'borrower_id': 'required'})
        try:
            borrower = self.env['res.users'].browse(int(borrower_id)).exists()
        except (TypeError, ValueError):
            borrower = self.env['res.users']
        if not borrower:
            raise LabApiError.validation('领用人账号不存在：%s' % (borrower_id,),
                                         {'borrower_id': 'not_found'})
        if not borrower.active:
            raise LabApiError.validation('领用人账号「%s」已停用，不能领料' % borrower.name,
                                         {'borrower_id': 'inactive'})
        if borrower.share:
            raise LabApiError.validation('领用人「%s」是门户用户，不能作为实验室领用人'
                                         % borrower.name, {'borrower_id': 'portal_user'})
        company = self.env.company
        if borrower.company_ids and company not in borrower.company_ids:
            raise LabApiError.forbidden('领用人「%s」不属于当前公司' % borrower.name,
                                        {'borrower_id': 'wrong_company'})
        if borrower.id not in self.lab_authorized_borrowers().ids:
            raise LabApiError.forbidden(
                '当前账号没有代「%s」领料的权限；普通自助领料只能选择本人'
                % borrower.name, {'borrower_id': 'not_authorized'})
        return borrower

    # ------------------------------------------------------------------
    # 真实库存移动
    # ------------------------------------------------------------------
    @api.model
    def lab_quant_lock_domain(self, product, lot, locations):
        location_ids = tuple(loc.id for loc in locations if loc)
        if not location_ids:
            return []
        self.env.cr.execute(
            "SELECT id FROM stock_quant "
            "WHERE product_id = %s AND (lot_id = %s OR (lot_id IS NULL AND %s)) "
            "AND location_id IN %s FOR UPDATE",
            (product.id, lot.id if lot else None, lot is None, location_ids))
        return [row[0] for row in self.env.cr.fetchall()]

    @api.model
    def lab_available_qty(self, product, location, lot=None):
        """某库位（含子库位）下该批次可用数量；负数按 0 处理并告警。"""
        domain = [('product_id', '=', product.id),
                  ('location_id', 'child_of', location.id)]
        domain.append(('lot_id', '=', lot.id) if lot else ('lot_id', '=', False))
        quants = self.env['stock.quant'].search(domain)
        total = sum(quants.mapped('quantity'))
        reserved = sum(quants.mapped('reserved_quantity'))
        if total - reserved < -1e-9:
            _logger.warning('库存异常：物料 %s 在库位 %s 出现负库存 %s',
                            product.display_name, location.display_name, total)
        return self.lab_uom_round(product, max(0.0, total - reserved))

    @api.model
    def lab_move_stock(self, product, quantity, src_location, dest_location, lot=None,
                       reference='', origin='', note=''):
        """用原生 stock.move + stock.move.line 完成一次真实库存移动。

        前置条件（调用方负责）：
        * 已持有相关 quant 的 SQL 行锁
        * 已校验数量 > 0、符合 UoM 精度、来源库位可用量足够
        * 已校验公司归属

        返回完成的 stock.move 记录。
        """
        Move = self.env['stock.move']
        MoveLine = self.env['stock.move.line']
        uom = product.uom_id
        move = Move.create({
            'product_id': product.id,
            'product_uom_qty': quantity,
            'product_uom': uom.id,
            'location_id': src_location.id,
            'location_dest_id': dest_location.id,
            'reference': reference or _('实验室库存作业'),
            'origin': origin or False,
            'company_id': self.env.company.id,
            'picked': True,
        })
        MoveLine.create({
            'move_id': move.id,
            'product_id': product.id,
            'product_uom_id': uom.id,
            'quantity': quantity,
            'location_id': src_location.id,
            'location_dest_id': dest_location.id,
            'lot_id': lot.id if lot else False,
            'company_id': self.env.company.id,
            'picked': True,
        })
        move.with_context(lab_workflow_move=True)._action_done()
        if move.state != 'done':
            raise LabApiError.precondition(
                '库存移动未完成（状态 %s），已回滚本次操作' % move.state)
        if note:
            # 注意：Odoo 19 的 stock.move 不是 mail.thread，不能 message_post，
            # 说明写在专用字段里，随移动记录一起可审计。
            move.write({'lab_note': note})
        return move

    @api.model
    def lab_assert_not_negative(self, product, locations, lots):
        """移动完成后再次核对：内部库位不得出现负库存。"""
        quant = self.env['stock.quant']
        domain = [('product_id', '=', product.id),
                  ('location_id.usage', 'in', ('internal', 'transit')),
                  ('quantity', '<', 0)]
        if locations:
            domain.append(('location_id', 'child_of', [loc.id for loc in locations]))
        bad = quant.search(domain)
        if bad:
            detail = '；'.join('%s@%s=%s' % (q.lot_id.name or '无批次',
                                            q.location_id.display_name, q.quantity)
                              for q in bad)
            raise LabApiError.precondition(
                '检测到内部库位负库存，已回滚：%s' % detail,
                {'quantity': 'negative_stock'})

    @api.model
    def lab_most_common_internal_location(self):
        """默认内部库位：仓库 stock 库位，否则第一个 internal 库位。"""
        Location = self.env['stock.location']
        company = self.env.company
        warehouse = self.env['stock.warehouse'].search(
            [('company_id', '=', company.id)], limit=1)
        if warehouse and warehouse.lot_stock_id:
            return warehouse.lot_stock_id
        location = Location.search([
            ('usage', '=', 'internal'),
            '|', ('company_id', '=', False), ('company_id', '=', company.id),
        ], limit=1)
        if not location:
            raise LabApiError.precondition(
                '当前公司没有内部库位，请先到「库存 → 配置 → 库位」创建库位后再入库')
        return location

    @api.model
    def lab_supplier_location(self):
        """供应商虚拟库位（入库来源）。"""
        Location = self.env['stock.location']
        location = Location.search([('usage', '=', 'supplier'),
                                    '|', ('company_id', '=', False),
                                    ('company_id', '=', self.env.company.id)],
                                   limit=1)
        if not location:
            raise LabApiError.precondition('系统缺少「供应商」虚拟库位，无法登记入库')
        return location

    @api.model
    def lab_lab_customer_location(self):
        """实验室领用虚拟客户位（领用去向 / 归还来源）。"""
        return self.env['stock.location']._lab_get_or_create_customer_location()

    @api.model
    def lab_inventory_location(self):
        """库存盘点虚拟位（用于历史无批次库存的安全分袋适配）。"""
        Location = self.env['stock.location']
        location = Location.search([('usage', '=', 'inventory'),
                                    '|', ('company_id', '=', False),
                                    ('company_id', '=', self.env.company.id)],
                                   limit=1)
        if not location:
            raise LabApiError.precondition('系统缺少「库存损失」虚拟库位，无法做历史库存适配')
        return location

    # ------------------------------------------------------------------
    # 产品可库存 / 跟踪
    # ------------------------------------------------------------------
    @api.model
    def lab_untracked_positive_quants(self, product):
        return self.env['stock.quant'].search([
            ('product_id', '=', product.id),
            ('location_id.usage', 'in', ('internal', 'transit')),
            ('lot_id', '=', False),
            ('quantity', '>', 0),
        ])

    @api.model
    def lab_ensure_storable_tracking(self, template):
        """确保物料可库存、且开启批次跟踪。

        Odoo 19 事实（以本地官方源码 ``addons/stock/models/product.py`` 为准）：

        * 可库存 = ``product.template.type == 'consu'`` 且 ``is_storable = True``
        * ``tracking`` 仅当 ``is_storable`` 为真时才能非 none
          （``_compute_tracking`` 会把不可库存产品的 tracking 强制回 'none'）

        安全规则：**绝不清零或伪造已有正库存**。
        若该物料在内部库位存在无批次正库存，则拒绝自动改跟踪，
        必须走 ``lab_workflow_adopt``（显式分袋适配，总量与流水可审计）。
        """
        if template.type != 'consu':
            raise LabApiError.precondition(
                '物料「%s」的类型是 %s，不是可库存物料（Odoo 19 要求 type=consu + '
                'is_storable=True）。请先改正物料类型再入库。'
                % (template.display_name, template.type),
                {'item_key': 'not_consumable'})
        if not template.is_storable:
            raise LabApiError.precondition(
                '物料「%s」当前未开启库存管理（is_storable=False）。入库前请先开启，'
                '或在物料表单勾选「跟踪库存」。' % template.display_name,
                {'item_key': 'not_storable'})
        if template.tracking == 'none':
            untracked = self.lab_untracked_positive_quants(template.product_variant_id)
            if untracked:
                total = sum(untracked.mapped('quantity'))
                raise LabApiError.precondition(
                    '物料「%s」在内部库位还有 %s 个无批次库存，直接开启批次跟踪会让这些库存'
                    '无法追溯。请先使用「历史库存分袋适配」把现有库存按袋登记'
                    '（适配前后总量不变、流水可审计），再入库新袋。'
                    % (template.display_name, total),
                    {'item_key': 'legacy_untracked_stock'})
            template.write({'tracking': 'lot'})
            _logger.info('lab_workflow: 物料 %s 开启批次跟踪（原无正库存，安全）',
                         template.display_name)
        elif template.tracking not in ('lot', 'serial'):
            raise LabApiError.precondition(
                '物料「%s」的跟踪方式是 %s，本系统需要 lot 或 serial'
                % (template.display_name, template.tracking))
        return template.tracking
