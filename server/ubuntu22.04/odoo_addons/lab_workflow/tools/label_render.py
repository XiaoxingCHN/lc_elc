# -*- coding: utf-8 -*-
"""A4 批量标签的排版计算、字段内容与边界校验（纯逻辑，可离线单测）。

单位全部为毫米；1 mm = 72/25.4 pt。
"""

import math

__all__ = [
    'MM_TO_PT',
    'A4_WIDTH_MM',
    'A4_HEIGHT_MM',
    'PRINTABLE_MARGIN_MM',
    'KIND_BAG',
    'KIND_LOCATION',
    'ALLOWED_FIELDS',
    'REQUIRED_FIELDS',
    'LabelSpec',
    'LabelContent',
    'LabelSpecError',
    'validate_spec',
    'compute_grid',
    'paginate',
    'build_contents',
    'describe_plan',
    'mm_to_pt',
]

MM_TO_PT = 72.0 / 25.4
A4_WIDTH_MM = 210.0
A4_HEIGHT_MM = 297.0
# 常规激光/喷墨打印机不可打印边缘（左右上下各约 4~5mm）
PRINTABLE_MARGIN_MM = 5.0

KIND_BAG = 'bag'
KIND_LOCATION = 'location'

# 标签上允许出现的文字字段（与契约 labels.params.fields 对齐）
ALLOWED_FIELDS = (
    'sn',            # 物料 SN
    'location',      # 库码 / 库位路径
    'mpn',           # 型号
    'catalog_code',  # C 编号
    'parameters',    # 参数
    'quantity',      # 袋内数量
    'item_name',     # 名称
    'trace_code',    # 追溯码正文
    'supplier',      # 来料信息（订单号等）
    'name', 'brand', 'package', 'initial_quantity',
)

# 器件标签至少要有 SN 与库位；库位标签至少要显示库码
REQUIRED_FIELDS = {
    KIND_BAG: (),
    KIND_LOCATION: ('location',),
    'pending': ('trace_code',),
}

# 数值边界（业务可配置由 ir.config_parameter 覆盖，这里是硬下限/上限）
BOUNDS = {
    'width_mm': (20.0, 200.0),
    'height_mm': (12.0, 200.0),
    'margin_mm': (0.0, 40.0),
    'gap_mm': (0.0, 20.0),
    'copies': (1, 200),
    'ids': (1, 200),
    'fields': (1, len(ALLOWED_FIELDS)),
}

# 一张标签至少要能同时容纳「文字区 + 唯一的二维码 + 静区」：
#   QR_MODULE_MIN_MM：单个模块的物理下限，小于它手机/扫码枪容易扫不出
#     模块数 = 版本 1..6 的 21..41 + 两侧静区 8 模块，即 29~49 模块；
#     取 QR_MIN_MM=13mm 时最坏情况 13/49 ≈ 0.265mm/模块，
#     因此二维码在标签内的实际尺寸再按模块数校验（见 pdf_labels.qr_module_size_mm）。
#   QR_MIN_MM：二维码图形（含 4 模块静区）最小边长
#   QR_MAX_MM：二维码最大边长（再大也没必要，浪费文字空间）
#   TEXT_MIN_WIDTH_MM：文字列最小可用宽度，太窄会整列被折成 1 个字
QR_MODULE_MIN_MM = 0.26
QR_MIN_MM = 13.0
QR_MAX_MM = 18.0
QR_MAX_WIDTH_RATIO = 0.45
TEXT_MIN_WIDTH_MM = 8.0
TEXT_MIN_HEIGHT_MM = 4.0

# 二维码静区（标准 4 模块）在标签上至少要有的物理宽度，太挤会扫不出
QR_QUIET_ZONE_MIN_MM = 0.8

# 文字字号下限（顶层设计定的可读性红线）：
#   正文不得小于 5.5pt，标题不得小于 6.5pt。
# 放不下就**明确拒绝并提示加大标签/减少字段**，不缩到微字、不截断文字。
MIN_BODY_FONT_PT = 5.5
MIN_TITLE_FONT_PT = 6.5

# 推荐标签尺寸（文字较多时的默认选项；用户仍可自定毫米）
RECOMMENDED_WIDTH_MM = 60.0
RECOMMENDED_HEIGHT_MM = 40.0

# 最小合规标签（毫米）
MIN_LABEL_WIDTH_MM = round(TEXT_MIN_WIDTH_MM + QR_MIN_MM + 2.0, 2)
MIN_LABEL_HEIGHT_MM = round(QR_MIN_MM + 2.0, 2)


class LabelSpecError(ValueError):
    """标签参数不合法：参数名 -> 中文可执行提示。"""

    def __init__(self, message, field=None):
        super().__init__(message)
        self.message = message
        self.field = field

    def as_dict(self):
        return {'message': self.message, 'field': self.field}


class LabelSpec(object):
    """一次的标签排版规格（全部毫米）。"""

    __slots__ = ('kind', 'width_mm', 'height_mm', 'margin_mm', 'gap_mm',
                 'copies', 'fields', 'ids')

    def __init__(self, kind=KIND_BAG, width_mm=50.0, height_mm=30.0,
                 margin_mm=10.0, gap_mm=2.0, copies=1, fields=None, ids=None):
        self.kind = kind
        self.width_mm = float(width_mm)
        self.height_mm = float(height_mm)
        self.margin_mm = float(margin_mm)
        self.gap_mm = float(gap_mm)
        self.copies = int(copies)
        self.fields = list(fields) if fields else list(REQUIRED_FIELDS.get(kind) or ('sn',))
        self.ids = list(ids or [])

    @property
    def label_count(self):
        return len(self.ids) * self.copies


class LabelContent(object):
    """一张标签要打印的真实内容（不含排版）。"""

    __slots__ = ('kind', 'ref_id', 'payload', 'trace_code', 'lines', 'title')

    def __init__(self, kind, ref_id, payload, trace_code, lines, title):
        self.kind = kind
        self.ref_id = ref_id
        self.payload = payload
        self.trace_code = trace_code
        self.lines = list(lines)
        self.title = title

    def as_dict(self):
        return {
            'kind': self.kind,
            'ref_id': self.ref_id,
            'payload': self.payload,
            'trace_code': self.trace_code,
            'title': self.title,
            'lines': list(self.lines),
        }


def mm_to_pt(value):
    return float(value) * MM_TO_PT


def _check_range(name, value):
    low, high = BOUNDS[name]
    if value is None or (isinstance(value, float) and math.isnan(value)):
        raise LabelSpecError('%s 必须是数字（单位毫米/份）' % name, name)
    if value < low - 1e-9 or value > high + 1e-9:
        raise LabelSpecError('%s=%s 超出允许范围 %s~%s' % (name, value, low, high), name)


def validate_spec(spec):
    """校验标签规格；不合法直接抛 LabelSpecError（中文可执行提示）。"""
    if spec.kind not in (KIND_BAG, KIND_LOCATION, 'pending'):
        raise LabelSpecError('标签类型只能是 bag（器件袋标签）或 location（库位标签），收到 %r'
                             % (spec.kind,), 'kind')
    _check_range('width_mm', spec.width_mm)
    _check_range('height_mm', spec.height_mm)
    _check_range('margin_mm', spec.margin_mm)
    _check_range('gap_mm', spec.gap_mm)
    _check_range('copies', spec.copies)
    if spec.ids:
        _check_range('ids', len(spec.ids))

    fields = list(spec.fields)
    if not fields:
        raise LabelSpecError('fields 不能为空', 'fields')
    unknown = [f for f in fields if f not in ALLOWED_FIELDS]
    if unknown:
        raise LabelSpecError('不支持的文字字段：%s（可用：%s）'
                             % ('、'.join(unknown), '、'.join(ALLOWED_FIELDS)), 'fields')
    for required in REQUIRED_FIELDS.get(spec.kind, ()):
        if required not in fields:
            raise LabelSpecError('%s 标签必须包含字段 %s' % (spec.kind, required), 'fields')
    if spec.kind == KIND_BAG and not {'sn', 'trace_code'}.intersection(fields):
        raise LabelSpecError('器件标签必须包含内部 SN 或袋码文字。', 'fields')

    # 一张标签必须同时装得下「唯一二维码」+ 要求的文字，否则明确拒绝而不是裁切。
    # 先于 A4 范围判断：太小的标签要给出「装不下二维码/文字」这个更有意义的原因。
    if spec.width_mm < MIN_LABEL_WIDTH_MM - 1e-9:
        raise LabelSpecError(
            '标签宽 %.1fmm 太小：至少要 %.1fmm 才能同时放下 %.0fmm 文字列和 %.0fmm 二维码'
            '（含静区与内边距）。请加大宽度或减少打印字段。'
            % (spec.width_mm, MIN_LABEL_WIDTH_MM, TEXT_MIN_WIDTH_MM, QR_MIN_MM),
            'width_mm')
    if spec.height_mm < MIN_LABEL_HEIGHT_MM - 1e-9:
        raise LabelSpecError(
            '标签高 %.1fmm 太小：至少要 %.1fmm 才能放下 %.0fmm 二维码（含静区）与内边距。'
            % (spec.height_mm, MIN_LABEL_HEIGHT_MM, QR_MIN_MM),
            'height_mm')

    # 页边距 + 至少一张标签必须落在 A4 可打印区内
    usable_w = A4_WIDTH_MM - 2 * max(spec.margin_mm, PRINTABLE_MARGIN_MM)
    usable_h = A4_HEIGHT_MM - 2 * max(spec.margin_mm, PRINTABLE_MARGIN_MM)
    if usable_w <= 0 or usable_h <= 0:
        raise LabelSpecError('页边距 %smm 太大：A4（%sx%smm）没有可打印区域'
                             % (spec.margin_mm, A4_WIDTH_MM, A4_HEIGHT_MM), 'margin_mm')
    if spec.width_mm > usable_w + 1e-9:
        raise LabelSpecError(
            '标签宽 %.1fmm 超出 A4 可用宽度 %.1fmm（A4 宽 %.0fmm - 左右页边距 %.1fmm）'
            % (spec.width_mm, usable_w, A4_WIDTH_MM, max(spec.margin_mm, PRINTABLE_MARGIN_MM)),
            'width_mm')
    if spec.height_mm > usable_h + 1e-9:
        raise LabelSpecError(
            '标签高 %.1fmm 超出 A4 可用高度 %.1fmm（A4 高 %.0fmm - 上下页边距 %.1fmm）'
            % (spec.height_mm, usable_h, A4_HEIGHT_MM, max(spec.margin_mm, PRINTABLE_MARGIN_MM)),
            'height_mm')
    return spec


def compute_grid(spec):
    """计算每页行列数。

    :returns: dict(cols, rows, per_page, usable_width_mm, usable_height_mm,
                   usable_x_mm, usable_y_mm, effective_margin_mm)
    """
    validate_spec(spec)
    margin = max(spec.margin_mm, PRINTABLE_MARGIN_MM)
    usable_w = A4_WIDTH_MM - 2 * margin
    usable_h = A4_HEIGHT_MM - 2 * margin
    cols = int(math.floor((usable_w + spec.gap_mm + 1e-9) / (spec.width_mm + spec.gap_mm)))
    rows = int(math.floor((usable_h + spec.gap_mm + 1e-9) / (spec.height_mm + spec.gap_mm)))
    cols = max(cols, 1)
    rows = max(rows, 1)
    return {
        'cols': cols,
        'rows': rows,
        'per_page': cols * rows,
        'usable_width_mm': round(usable_w, 4),
        'usable_height_mm': round(usable_h, 4),
        'effective_margin_mm': round(margin, 4),
    }


def paginate(spec, total_labels=None):
    """把标签总数切成页。

    :returns: dict(grid=..., total_labels=..., page_count=..., pages=[每页标签数, ...])
    """
    grid = compute_grid(spec)
    total = spec.label_count if total_labels is None else int(total_labels)
    if total < 0:
        raise LabelSpecError('标签数量不能为负', 'ids')
    per_page = grid['per_page']
    pages = []
    remaining = total
    while remaining > 0:
        take = min(per_page, remaining)
        pages.append(take)
        remaining -= take
    page_count = len(pages)
    return {
        'grid': grid,
        'total_labels': total,
        'page_count': page_count,
        'pages': pages,
    }


# --------------------------------------------------------------------------
# 标签内容
# --------------------------------------------------------------------------
def _clean(value):
    if value is None:
        return ''
    text = str(value).replace('\r', ' ').replace('\n', ' ').strip()
    return text


def _format_parameters(parameters):
    """参数：dict / list[(k, v)] / JSON 字符串 都转成 'k=v' 列表。"""
    if not parameters:
        return []
    items = []
    if isinstance(parameters, dict):
        pairs = parameters.items()
    elif isinstance(parameters, (list, tuple)):
        pairs = []
        for entry in parameters:
            if isinstance(entry, dict):
                pairs.append((entry.get('name') or entry.get('key') or '',
                              entry.get('value') or entry.get('val') or ''))
            elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
                pairs.append((entry[0], entry[1]))
    else:
        return [_clean(parameters)]
    for key, value in pairs:
        key = _clean(key)
        value = _clean(value)
        if key and value:
            items.append('%s=%s' % (key, value))
        elif key or value:
            items.append(key or value)
    return items


# 打印时给「裸值」字段加中文前缀，避免操作员看不懂（例如 101 -> 数量：101）
FIELD_PREFIXES = {
    'name': '名称', 'brand': '品牌', 'package': '封装', 'initial_quantity': '初始数量',
    'quantity': '数量',
    'location': '库码',
    'mpn': '型号',
    'catalog_code': 'C编号',
    'trace_code': '追溯码',
    'item_name': '名称',
    'supplier': '来料',
    'sn': 'SN',
}


def _clean_prefix(text):
    text = _clean(text)
    return text[:-1] if text.endswith('：') else text


def _format_field(field, entry):
    """返回该字段在标签上的文字行（可能多行，例如参数）。"""
    prefix = FIELD_PREFIXES.get(field)
    if field == 'parameters':
        return _format_parameters(entry.get('parameters'))
    if field == 'trace_code':
        value = _clean(entry.get('trace_code'))
    elif field == 'location':
        value = _clean(entry.get('location_code') or entry.get('location'))
    elif field == 'catalog_code':
        value = _clean(entry.get('catalog_code'))
    elif field in ('item_name', 'name'):
        value = _clean(entry.get('item_name') or entry.get('name'))
    elif field == 'quantity':
        value = _clean(entry.get('quantity'))
    elif field == 'supplier':
        value = _clean(entry.get('supplier'))
    else:
        value = _clean(entry.get(field))
    if not value:
        return []
    if not prefix:
        return [value]
    # 值本身已经带同类前缀或已经是 k=v 形式时不要重复加
    if value.startswith(prefix + '：') or value.startswith(prefix + ':'):
        return [value]
    return ['%s：%s' % (prefix, value)]


def _line_value(line):
    """去掉「XX：」前缀后的值（用于与标题比较是否重复）。"""
    text = _clean(line)
    for separator in ('：', ':'):
        if separator in text:
            head, _sep, tail = text.partition(separator)
            if head in FIELD_PREFIXES.values() and tail.strip():
                return tail.strip()
    return text


def _same_as_title(line, title_key):
    if not title_key:
        return False
    candidate = _clean(line)
    if not candidate:
        return False
    if candidate.rstrip('：:').strip() == title_key:
        return True
    return _line_value(candidate) == title_key


def build_contents(spec, payloads):
    """根据数据库侧的 facts 生成标签内容列表。

    :param spec: LabelSpec
    :param payloads: 每张标签的 dict，必须含 kind/ref_id/payload/trace_code，
                     其余按字段提供：sn/location/code/mpn/catalog_code/parameters/
                     quantity/item_name/supplier。
    :returns: list[LabelContent]

    两条打印规则（root 反馈）：

    * 裸值加中文前缀（``数量：101``、``库码：K000001``），避免看不懂；
    * **去掉与标题重复的行**（标题通常就是 SN/库码；带前缀的 ``SN：LAB-1``
      也算重复，因为信息已在标题上），腾出的高度让默认字号更大；
      只去重、不截断：独有信息一行都不会丢。
    """
    validate_spec(spec)
    contents = []
    for entry in payloads:
        raw_title = _clean(entry.get('title')) or _clean(entry.get('sn')) \
            or _clean(entry.get('location_code')) or _clean(entry.get('trace_code'))
        title = _line_value(raw_title)
        title_key = title.rstrip('：:').strip()
        lines = []
        for field in spec.fields:
            for line in _format_field(field, entry):
                candidate = _clean(line)
                if not candidate:
                    continue
                if _same_as_title(candidate, title_key):
                    continue
                lines.append(candidate)
        contents.append(LabelContent(
            kind=entry.get('kind') or spec.kind,
            ref_id=entry.get('ref_id'),
            payload=entry.get('payload'),
            trace_code=_clean(entry.get('trace_code')),
            lines=lines,
            title=title,
        ))
    # 份数展开
    if spec.copies > 1:
        expanded = []
        for content in contents:
            expanded.extend([content] * spec.copies)
        return expanded
    return contents


def describe_plan(spec):
    """给人看的排版说明（网页端/接口调试都能用）。"""
    plan = paginate(spec)
    grid = plan['grid']
    return {
        'kind': spec.kind,
        'width_mm': spec.width_mm,
        'height_mm': spec.height_mm,
        'margin_mm': spec.margin_mm,
        'gap_mm': spec.gap_mm,
        'copies': spec.copies,
        'fields': list(spec.fields),
        'label_count': plan['total_labels'],
        'page_count': plan['page_count'],
        'labels_per_page': grid['per_page'],
        'cols': grid['cols'],
        'rows': grid['rows'],
        'effective_margin_mm': grid['effective_margin_mm'],
        'usable_width_mm': grid['usable_width_mm'],
        'usable_height_mm': grid['usable_height_mm'],
    }
