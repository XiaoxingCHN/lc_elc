# -*- coding: utf-8 -*-
"""P3 窄接口的纯校验/排序规则（**不 import odoo**，可离线单测）。

为什么单独一层：本轮新增的袋列表、库位改停用、类别映射、成员角色、history 过滤、
浏览器 PDF、扫码页迁移都有"边界值/角色/层级"判定。把这些判定放在纯函数里，
既能在没有数据库的机器上回归，也让控制器与模型共享同一份规则，不会两边各写一套。

约定：所有 ``raise RuleError`` 都带 ``field`` 与可选 ``reason``，
模型层统一转成 ``LabApiError``（中文提示 + fields），控制器不再重复判断。
"""

import datetime
import re

__all__ = [
    'RuleError',
    'DEFAULT_LIMIT',
    'MAX_LIMIT',
    'MAX_QUERY_LEN',
    'MAX_NOTE_LEN',
    'MAX_IDS',
    'MAX_COPIES',
    'MAX_TOTAL_LABELS',
    'MAX_PRIORITY',
    'ROLE_GROUP_XMLIDS',
    'ROLE_ORDER',
    'OPERATION_TYPES',
    'SCAN_REDIRECT_PARAM',
    'DEFAULT_SCAN_REDIRECT',
    'clamp_limit',
    'parse_bool',
    'parse_cursor',
    'parse_int',
    'parse_text',
    'normalize_role',
    'group_xmlid_for_role',
    'ensure_role_change_allowed',
    'order_mapping_rows',
    'parse_date',
    'day_bounds',
    'history_filters',
    'location_update_guard',
    'label_bounds',
    'validate_redirect_path',
    'scan_redirect_candidate',
    'scan_redirect_target',
]

#: 分页
DEFAULT_LIMIT = 24
MAX_LIMIT = 100

#: 文本长度
MAX_QUERY_LEN = 64
MAX_NOTE_LEN = 200
MAX_NAME_LEN = 64

#: 标签批量
MAX_IDS = 200
MAX_COPIES = 200
#: **单次请求的标签总张数上限**（Lead decision：MAX_TOTAL_LABELS=200）。
#: ids 与 copies 分别不超限也不够：200×200=40000 张会让一个 operator 长时间占满 worker，
#: 因此三个标签出口（plan/preview/PDF）在**渲染前**统一按 ids×copies 校验。
MAX_TOTAL_LABELS = 200

#: 映射优先级（越小越先）
MIN_PRIORITY = 0
MAX_PRIORITY = 1000
DEFAULT_PRIORITY = 10

#: 只允许操作的库存角色 -> Odoo 组 xmlid。
#: **刻意只含 lab_workflow 库存组**：不提供 base.group_system / erp_manager /
#: lab_catalog 角色授权，避免"仓库管理员顺手提权成系统管理员"。
ROLE_GROUP_XMLIDS = {
    'lab_user': 'lab_workflow.group_lab_user',
    'lab_operator': 'lab_workflow.group_lab_operator',
    'lab_manager': 'lab_workflow.group_lab_manager',
}
ROLE_ORDER = ('lab_user', 'lab_operator', 'lab_manager')

#: 作业类型（history 过滤/展示）
OPERATION_TYPES = ('receipt', 'issue', 'return', 'adopt')

#: /lab/scan 迁移参数
SCAN_REDIRECT_PARAM = 'lab_workflow.scan_redirect'
DEFAULT_SCAN_REDIRECT = '/team/scan'
_OFF_VALUES = frozenset({'0', 'off', 'false', 'no', 'none', 'disabled', 'null'})

_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_CONTROL_RE = re.compile(r'[\x00-\x1f\x7f]')


class RuleError(ValueError):
    """纯逻辑层的校验失败（field 用于前端定位）。"""

    def __init__(self, field, message, reason=None):
        super().__init__(message)
        self.field = field
        self.message = message
        self.reason = reason or 'invalid'

    def fields(self):
        payload = {self.field: self.reason}
        return payload


# ---------------------------------------------------------------------------
# 基础类型
# ---------------------------------------------------------------------------
def clamp_limit(value, default=DEFAULT_LIMIT, maximum=MAX_LIMIT):
    """把 limit 收敛到 1..maximum；非数字用 default。"""
    if value in (None, '', False):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    if number < 1:
        return default
    return min(number, int(maximum))


def parse_bool(value, default=False):
    """宽松布尔：接受 JSON bool、'1/0'、'true/false'、'on/off'、'yes/no'。"""
    if isinstance(value, bool):
        return value
    if value is None or value == '':
        return default
    text = str(value).strip().lower()
    if text in ('1', 'true', 'on', 'yes', 'y'):
        return True
    if text in ('0', 'false', 'off', 'no', 'n'):
        return False
    return default


def parse_cursor(value):
    """递减 id 游标：空 -> None；必须是非负整数。"""
    if isinstance(value, bool):
        raise RuleError('cursor', 'cursor 非法（布尔值）', 'invalid')
    if value is None or value == '':
        return None
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        raise RuleError('cursor', 'cursor 非法：%r（应为递减的整数 ID）' % (value,), 'invalid')
    if number < 0:
        raise RuleError('cursor', 'cursor 不能为负数：%s' % number, 'invalid')
    return number


def parse_int(value, field, minimum=None, maximum=None, default=None, required=False):
    if isinstance(value, bool):
        raise RuleError(field, '%s 必须是整数，不能是布尔值' % field, 'not_a_number')
    if value is None or value == '':
        if required:
            raise RuleError(field, '缺少 %s' % field, 'required')
        return default
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        raise RuleError(field, '%s 必须是整数，收到 %r' % (field, value), 'not_an_integer')
    if minimum is not None and number < minimum:
        raise RuleError(field, '%s 不能小于 %s' % (field, minimum), 'too_small')
    if maximum is not None and number > maximum:
        raise RuleError(field, '%s 不能大于 %s' % (field, maximum), 'too_large')
    return number


def parse_text(value, field, max_length=MAX_NOTE_LEN, required=False, allow_empty=True):
    text = value.strip() if isinstance(value, str) else ('' if value in (None, False) else str(value).strip())
    if not text:
        if required:
            raise RuleError(field, '缺少 %s' % field, 'required')
        return '' if allow_empty else None
    if len(text) > max_length:
        raise RuleError(field, '%s 最多 %s 个字符（收到 %s）'
                        % (field, max_length, len(text)), 'too_long')
    return text


# ---------------------------------------------------------------------------
# 角色
# ---------------------------------------------------------------------------
def normalize_role(role):
    """只接受三个库存角色；其它（含系统组/目录组）一律拒绝。"""
    text = (role or '').strip() if isinstance(role, str) else ''
    if text.startswith('lab_workflow.'):
        text = text[len('lab_workflow.'):]
    if text == 'group_lab_operator':
        text = 'lab_operator'
    elif text == 'group_lab_user':
        text = 'lab_user'
    elif text == 'group_lab_manager':
        text = 'lab_manager'
    if text not in ROLE_GROUP_XMLIDS:
        raise RuleError(
            'role',
            '只能管理实验室库存角色（lab_user/lab_operator/lab_manager）；'
            '系统管理员与目录角色请走原生后台维护入口',
            'not_allowed')
    return text


def group_xmlid_for_role(role):
    return ROLE_GROUP_XMLIDS[normalize_role(role)]


def ensure_role_change_allowed(role, enabled, target_has_role, higher_roles, remaining_managers):
    """变更前的层级/最后管理员保护（纯判定）。

    :param role: 已归一化的角色键
    :param enabled: True=授予，False=撤销
    :param target_has_role: 目标账号当前是否已有该角色
    :param higher_roles: dict，如 {'lab_operator': True, 'lab_manager': False}
    :param remaining_managers: 撤销后该公司**其余**有效 manager 数量
    """
    role = normalize_role(role)
    if enabled:
        return True
    if role == 'lab_manager' and int(remaining_managers or 0) <= 0:
        raise RuleError(
            'role',
            '不能撤销最后一名库存管理员：这样仓库将没有人能维护库位与代领。'
            '请先把另一个账号设为管理员。',
            'last_manager')
    if role == 'lab_user' and (higher_roles.get('lab_operator')
                               or higher_roles.get('lab_manager')):
        raise RuleError(
            'role',
            '该账号仍是操作员/管理员（隐含只读角色），请先降级更高角色再撤销只读。',
            'implied_role')
    if role == 'lab_operator' and higher_roles.get('lab_manager'):
        raise RuleError(
            'role',
            '该账号仍是库存管理员（隐含操作员），请先撤销管理员再撤销操作员。',
            'implied_role')
    return True


# ---------------------------------------------------------------------------
# 映射
# ---------------------------------------------------------------------------
def order_mapping_rows(rows):
    """按 priority 升序、同优先级按 id 升序（稳定、可单测）。"""
    def key(row):
        priority = row.get('priority')
        try:
            priority = int(priority)
        except (TypeError, ValueError):
            priority = DEFAULT_PRIORITY
        try:
            row_id = int(row.get('id') or 0)
        except (TypeError, ValueError):
            row_id = 0
        return (priority, row_id)
    return sorted(list(rows or []), key=key)


# ---------------------------------------------------------------------------
# 日期 / history 过滤
# ---------------------------------------------------------------------------
def parse_date(value, field):
    if value in (None, '', False):
        return None
    text = str(value).strip()
    if not _DATE_RE.match(text):
        raise RuleError(field, '%s 必须是 YYYY-MM-DD 格式，收到 %r' % (field, value), 'invalid')
    try:
        return datetime.date(int(text[0:4]), int(text[5:7]), int(text[8:10]))
    except ValueError:
        raise RuleError(field, '%s 不是合法日期：%r' % (field, value), 'invalid')


def day_bounds(date_from, date_to):
    """把 [date_from, date_to] 转成含边界当天的 datetime 区间（左闭右开）。"""
    start = None
    end = None
    if date_from:
        start = datetime.datetime.combine(date_from, datetime.time.min)
    if date_to:
        end = datetime.datetime.combine(date_to + datetime.timedelta(days=1),
                                        datetime.time.min)
    if start and end and start >= end:
        raise RuleError('date_from', 'date_from 不能晚于 date_to', 'invalid_range')
    return start, end


def history_filters(params):
    """校验并归一化 history 过滤参数（缺失键不返回，避免覆盖默认）。"""
    params = params or {}
    out = {}
    operation_type = params.get('operation_type')
    if operation_type not in (None, '', False):
        text = str(operation_type).strip().lower()
        if text not in OPERATION_TYPES:
            raise RuleError('operation_type',
                            'operation_type 只能是 %s' % '/'.join(OPERATION_TYPES),
                            'invalid')
        out['operation_type'] = text
    date_from = parse_date(params.get('date_from'), 'date_from')
    date_to = parse_date(params.get('date_to'), 'date_to')
    start, end = day_bounds(date_from, date_to)
    if start:
        out['date_start'] = start
    if end:
        out['date_end'] = end
    for key in ('actor_id', 'borrower_id'):
        value = params.get(key)
        if value not in (None, '', False):
            out[key] = parse_int(value, key, minimum=1)
    return out


# ---------------------------------------------------------------------------
# 库位改/停用
# ---------------------------------------------------------------------------
def location_update_guard(usage, is_root, deactivating, new_parent_id, current_id,
                          parent_is_self=False, parent_is_descendant=False,
                          bag_count=0, bag_quantity=0.0, quant_quantity=0.0,
                          parent_usage=None):
    """库位更新前置校验（纯判定，返回 None 或 raise RuleError）。"""
    if usage != 'internal':
        raise RuleError('location', '只有内部库位可以修改；视图/客户位/损失位不允许改。',
                        'not_internal')
    if new_parent_id is not None:
        if parent_is_self or (current_id and int(new_parent_id) == int(current_id)):
            raise RuleError('parent_id', '不能把库位挂到自己下面。', 'cycle')
        if parent_is_descendant:
            raise RuleError('parent_id', '不能把库位挂到自己的子库位下面（会形成环）。',
                            'cycle')
        if parent_usage is not None and parent_usage not in ('view', 'internal'):
            raise RuleError('parent_id', '父级只能是视图库位或内部库位。', 'invalid_usage')
    if is_root and deactivating:
        raise RuleError('location', '根库位不能停用。', 'is_root')
    if deactivating and (float(bag_count or 0) > 0 or float(bag_quantity or 0) != 0
                         or float(quant_quantity or 0) != 0):
        raise RuleError(
            'location',
            '该库位（含子库位）仍有 %s 个袋、合计 %s 的库存，不能停用；请先搬空或调拨。'
            % (int(bag_count or 0), quant_quantity if quant_quantity else bag_quantity),
            'has_stock')
    return True


# ---------------------------------------------------------------------------
# 标签
# ---------------------------------------------------------------------------
def label_bounds(ids_count, copies):
    """标签批量边界：单个上限 + **总张数上限**（ids×copies ≤ MAX_TOTAL_LABELS）。

    为什么总量单独限：``ids=200, copies=200`` 时单看两个参数都合法，但一次请求要
    渲染 40000 张（每张一个 QR + 中文字形），任何 operator 都能把 worker 占满。
    服务端三个出口（plan / preview / PDF）都必须在**开始渲染前**调用本函数。
    """
    try:
        ids_count = int(ids_count)
    except (TypeError, ValueError):
        raise RuleError('ids', '标签对象数量必须是整数', 'invalid')
    try:
        copies = int(copies)
    except (TypeError, ValueError):
        raise RuleError('copies', '份数必须是整数', 'invalid')
    if ids_count < 1:
        raise RuleError('ids', '至少要选择一个标签对象。', 'required')
    if ids_count > MAX_IDS:
        raise RuleError('ids', '一次最多打印 %s 个标签（可用份数放大）。' % MAX_IDS,
                        'too_many')
    if copies < 1 or copies > MAX_COPIES:
        raise RuleError('copies', '份数必须在 1..%s 之间。' % MAX_COPIES, 'out_of_range')
    total = ids_count * copies
    if total > MAX_TOTAL_LABELS:
        raise RuleError(
            'copies',
            '本次共 %s 张标签（%s 个对象 × %s 份），超过单次上限 %s 张；'
            '请减少对象数或份数后分批打印。'
            % (total, ids_count, copies, MAX_TOTAL_LABELS),
            'too_many_total')
    return ids_count, copies


# ---------------------------------------------------------------------------
# /lab/scan 迁移
# ---------------------------------------------------------------------------
def validate_redirect_path(value):
    """只接受站内相对路径（防开放跳转），返回规范化路径或 None。"""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or not text.startswith('/') or text.startswith('//'):
        return None
    if '\\' in text or _CONTROL_RE.search(text):
        return None
    if '://' in text:
        return None
    return text


def scan_redirect_candidate(param_value):
    """由参数值算出"想跳到哪里"（不检查路由是否存在）。

    * 参数为 off/0/false/no 等 -> None（保留旧控制台）
    * 参数为空/未设置 -> 默认 ``/team/scan``
    * 参数非法（非站内相对路径）-> 用默认值
    """
    raw = '' if param_value is None else str(param_value).strip()
    if raw and raw.lower() in _OFF_VALUES:
        return None
    if not raw:
        return DEFAULT_SCAN_REDIRECT
    return validate_redirect_path(raw) or DEFAULT_SCAN_REDIRECT


def scan_redirect_target(param_value, target_available):
    """决定 /lab/scan 是否跳转到自有扫码页。

    * 关闭或目标路由不存在（团队前端未装/未升级）-> None（回退旧控制台）
    """
    candidate = scan_redirect_candidate(param_value)
    if not candidate or not target_available:
        return None
    return candidate
